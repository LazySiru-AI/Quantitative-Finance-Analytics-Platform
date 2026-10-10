"""The import orchestrator and the account manifest.

What is worth pinning here is not that a CSV parses -- the adapter tests already cover that in
detail -- but the properties that only exist once the pieces are wired together, and that a caller
would otherwise have to get right for itself:

* the account attribution, which no validation can check and which the manifest exists to force the
  user to state;
* idempotency **across the whole store**, not just ``txn``, since a re-run that mints a fresh
  ``raw_import`` row and a second copy of every source row grows the database forever while
  reporting "0 inserted";
* per-file atomicity and per-file failure, so one bad export neither corrupts the ledger nor
  abandons the other seven.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from app.config import Settings
from app.core.models import AccountType, Broker, TaxTreatment
from app.db import sqlite
from app.ingest import service
from app.ingest.manifest import (
    ManifestError,
    load_manifest,
    render_template,
)

FIXTURES = Path(__file__).parent / "fixtures"

RH = FIXTURES / "robinhood" / "rh_activity.csv"
WB = FIXTURES / "webull" / "orders_sample.csv"
SOFI = FIXTURES / "sofi" / "activity_full.csv"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _place(settings: Settings, source: Path, name: str) -> Path:
    """Copy a fixture export into the settings' data directory under ``name``."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    target = settings.data_dir / name
    target.write_bytes(source.read_bytes())
    return target


def _manifest(settings: Settings, body: str) -> Path:
    path = service.manifest_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


ENTRY = """
[[account]]
file = "{file}"
account_id = "{account_id}"
label = "{label}"
tax_treatment = "{treatment}"
account_type = "{account_type}"
"""


def _entry(
    file: str,
    account_id: str,
    *,
    treatment: str = "taxable",
    account_type: str = "cash",
    label: str | None = None,
) -> str:
    return ENTRY.format(
        file=file,
        account_id=account_id,
        label=label or account_id,
        treatment=treatment,
        account_type=account_type,
    )


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


class TestManifest:
    def test_missing_manifest_names_the_init_command(self, settings: Settings) -> None:
        with pytest.raises(ManifestError) as excinfo:
            load_manifest(service.manifest_path(settings))
        message = str(excinfo.value)
        assert "--init" in message, "the error must name the command that fixes it"

    def test_tax_treatment_is_required(self, settings: Settings) -> None:
        """The one field with no safe default.

        It decides whether an account's gains are reported at all and whether a replacement purchase
        destroys a loss permanently under Rev. Rul. 2008-5. A default would be a guess about the
        highest-leverage tax input in the system.
        """
        path = _manifest(
            settings,
            '[[account]]\nfile = "RH.csv"\naccount_id = "rh"\n',
        )
        with pytest.raises(ManifestError) as excinfo:
            load_manifest(path)
        assert "tax_treatment" in str(excinfo.value)
        assert "roth_ira" in str(excinfo.value), "valid values must be listed"

    def test_account_type_defaults_to_the_conservative_option(self, settings: Settings) -> None:
        """Cash, because a cash account *is* checked for a negative running balance.

        Defaulting to margin would silently suppress that check -- see `app.core.cash`.
        """
        path = _manifest(settings, _entry("RH.csv", "rh").replace('account_type = "cash"\n', ""))
        book = load_manifest(path)
        assert book.entries[0].account.account_type is AccountType.CASH

    def test_unknown_key_is_fatal(self, settings: Settings) -> None:
        path = _manifest(settings, _entry("RH.csv", "rh") + 'nickname = "spending money"\n')
        with pytest.raises(ManifestError, match="unknown key"):
            load_manifest(path)

    def test_same_file_declared_twice_is_fatal(self, settings: Settings) -> None:
        path = _manifest(settings, _entry("RH.csv", "rh-a") + _entry("RH.csv", "rh-b"))
        with pytest.raises(ManifestError, match="declared twice"):
            load_manifest(path)

    def test_one_account_may_span_several_files(self, settings: Settings) -> None:
        """A 2025 export and a 2026 export of the same account are two files, one account."""
        path = _manifest(settings, _entry("RH-2025.csv", "rh") + _entry("RH-2026.csv", "rh"))
        book = load_manifest(path)
        assert len(book.entries) == 2
        assert {e.account.account_id for e in book.entries} == {"rh"}

    def test_but_they_must_agree_about_it(self, settings: Settings) -> None:
        """Otherwise the last entry written silently wins at `upsert_account`."""
        path = _manifest(
            settings,
            _entry("RH-2025.csv", "rh", treatment="taxable")
            + _entry("RH-2026.csv", "rh", treatment="roth_ira"),
        )
        with pytest.raises(ManifestError, match="described differently"):
            load_manifest(path)

    @pytest.mark.parametrize("bad", ["/etc/passwd", "../../secrets.csv", "C:/Windows/win.ini"])
    def test_paths_stay_inside_the_data_directory(self, settings: Settings, bad: str) -> None:
        path = _manifest(settings, _entry(bad, "rh"))
        with pytest.raises(ManifestError):
            load_manifest(path)

    def test_template_leaves_tax_treatment_empty(self, settings: Settings) -> None:
        """A pre-filled guess would be read as a suggestion and accepted unchanged."""
        text = render_template(
            [(settings.data_dir / "RH Roth.csv", "robinhood", Broker.ROBINHOOD)],
            data_dir=settings.data_dir,
        )
        assert 'tax_treatment = ""' in text
        assert "roth_ira" not in text.split("[[account]]")[1], (
            "a file named 'Roth' must not have its tax treatment guessed from the filename"
        )
        # And the template must not be silently importable as written.
        path = _manifest(settings, text)
        with pytest.raises(ManifestError, match="tax_treatment"):
            load_manifest(path)


# ---------------------------------------------------------------------------
# Discovery and planning
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_derived_stores_are_not_offered_as_exports(self, settings: Settings) -> None:
        """`store/` and `cache/` sit inside `data/` and hold no broker exports."""
        _place(settings, RH, "RH.csv")
        settings.store_dir.mkdir(parents=True, exist_ok=True)
        (settings.store_dir / "leftover.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        settings.cache_dir.mkdir(parents=True, exist_ok=True)
        (settings.cache_dir / "cached.csv").write_text("a,b\n1,2\n", encoding="utf-8")

        found = [p.name for p in service.discover_exports(settings)]
        assert found == ["RH.csv"]

    def test_plan_works_without_a_manifest(self, settings: Settings) -> None:
        """The state in which a user most needs to see what was found."""
        _place(settings, RH, "RH.csv")
        planned = service.plan_import(settings=settings)
        assert [p.status for p in planned] == [service.FileStatus.UNDECLARED]
        assert planned[0].adapter == "robinhood", "the adapter is still detected"
        assert planned[0].account_id is None

    def test_plan_writes_nothing(self, settings: Settings) -> None:
        _place(settings, RH, "RH.csv")
        _manifest(settings, _entry("RH.csv", "rh-taxable"))
        service.plan_import(settings=settings)
        assert not settings.ledger_path.exists()

    def test_plan_reports_a_file_already_imported(self, settings: Settings) -> None:
        _place(settings, RH, "RH.csv")
        _manifest(settings, _entry("RH.csv", "rh-taxable"))
        assert service.plan_import(settings=settings)[0].already_imported is False
        service.import_paths(settings=settings)
        assert service.plan_import(settings=settings)[0].already_imported is True


# ---------------------------------------------------------------------------
# Importing
# ---------------------------------------------------------------------------


class TestImport:
    def test_rows_land_under_the_declared_account(self, settings: Settings) -> None:
        _place(settings, RH, "RH Roth.csv")
        _manifest(
            settings,
            _entry("RH Roth.csv", "rh-roth", treatment="roth_ira", account_type="retirement"),
        )
        run = service.import_paths(settings=settings)

        assert run.ok
        assert run.inserted > 0
        with sqlite.connect(settings.ledger_path, read_only=True) as conn:
            accounts = sqlite.fetch_accounts(conn)
            txns = sqlite.fetch_transactions(conn)
        assert [a.account_id for a in accounts] == ["rh-roth"]
        assert accounts[0].tax_treatment is TaxTreatment.ROTH_IRA
        assert {row["account_id"] for row in txns} == {"rh-roth"}

    def test_broker_comes_from_the_header_not_the_manifest(self, settings: Settings) -> None:
        """A manifest that disagrees with the header is pointing at the wrong file."""
        _place(settings, RH, "RH.csv")
        _manifest(settings, _entry("RH.csv", "rh") + 'broker = "webull"\n')
        run = service.import_paths(settings=settings)

        assert run.files[0].status is service.FileStatus.FAILED
        assert "header is authoritative" in (run.files[0].detail or "")
        with sqlite.connect(settings.ledger_path, read_only=True) as conn:
            assert sqlite.fetch_transactions(conn) == []

    def test_undeclared_file_is_reported_not_guessed(self, settings: Settings) -> None:
        """The failure mode this guards: a hand-normalised copy of a SoFi export sits in the data
        directory beside the genuine export and is an incomplete version of it.
        Anything that imports what it finds without being told would double-count that account."""
        _place(settings, RH, "RH.csv")
        _place(settings, SOFI, "SOFI.csv")
        _manifest(settings, _entry("RH.csv", "rh-taxable"))
        run = service.import_paths(settings=settings)

        statuses = {f.path.name: f.status for f in run.files}
        assert statuses["SOFI.csv"] is service.FileStatus.UNDECLARED
        assert statuses["RH.csv"] is service.FileStatus.IMPORTED
        assert not run.ok, "a run with an unattributed file is not a clean run"

    def test_one_bad_file_does_not_abandon_the_others(self, settings: Settings) -> None:
        _place(settings, RH, "RH.csv")
        broken = settings.data_dir / "broken.csv"
        broken.write_text("Nothing,Recognisable\n1,2\n", encoding="utf-8")
        _manifest(settings, _entry("RH.csv", "rh-taxable") + _entry("broken.csv", "mystery"))

        run = service.import_paths(settings=settings)
        by_name = {f.path.name: f for f in run.files}
        assert by_name["broken.csv"].status is service.FileStatus.NO_ADAPTER
        assert by_name["RH.csv"].status is service.FileStatus.IMPORTED
        assert by_name["RH.csv"].inserted > 0, "the good file still landed"

    def test_a_failed_file_writes_nothing_at_all(self, settings: Settings) -> None:
        """Per-file atomicity. The connection is in autocommit mode, so without an explicit
        transaction a file that failed after writing its account row would leave that row behind."""
        _place(settings, WB, "WB.csv")
        _manifest(settings, _entry("WB.csv", "wb-cash") + 'broker = "sofi"\n')
        run = service.import_paths(settings=settings)

        assert run.files[0].status is service.FileStatus.FAILED
        with sqlite.connect(settings.ledger_path, read_only=True) as conn:
            assert sqlite.fetch_accounts(conn) == []
            assert conn.execute("SELECT COUNT(*) AS n FROM raw_import").fetchone()["n"] == 0

    def test_source_rows_are_stored_verbatim(self, settings: Settings) -> None:
        """`provenance.py` opens by promising this, and until the orchestrator existed nothing
        performed it: `raw_row` was empty in a real ledger while every transaction in it carried a
        `source_row` pointing into that empty table."""
        target = _place(settings, RH, "RH.csv")
        _manifest(settings, _entry("RH.csv", "rh-taxable"))
        run = service.import_paths(settings=settings)

        expected = run.files[0].row_count
        assert expected > 0
        with sqlite.connect(settings.ledger_path, read_only=True) as conn:
            stored = conn.execute("SELECT COUNT(*) AS n FROM raw_row").fetchone()["n"]
        assert stored == expected, "every source row, not only the usable ones"
        assert target.exists()

    def test_a_row_wider_than_the_header_still_stores(self, settings: Settings) -> None:
        """Robinhood's second footer row carries a tax disclaimer past the last declared column.
        `csv.DictReader` files it under a `None` key, which is not a JSON object key and is not
        sortable against the real ones -- so every real Robinhood import hits this."""
        _place(settings, RH, "RH.csv")
        _manifest(settings, _entry("RH.csv", "rh-taxable"))
        run = service.import_paths(settings=settings)

        assert run.ok
        with sqlite.connect(settings.ledger_path, read_only=True) as conn:
            rows = [r["content"] for r in conn.execute("SELECT content FROM raw_row")]
        assert any("__unmapped__" in row for row in rows), "the overflow content is preserved"


class TestIdempotency:
    def test_reimport_changes_nothing(self, settings: Settings) -> None:
        _place(settings, RH, "RH.csv")
        _manifest(settings, _entry("RH.csv", "rh-taxable"))

        first = service.import_paths(settings=settings)
        second = service.import_paths(settings=settings)

        assert second.files[0].status is service.FileStatus.UNCHANGED
        assert second.inserted == 0
        assert second.files[0].duplicates == first.files[0].inserted
        assert second.ledger_fingerprint == first.ledger_fingerprint
        assert second.txn_count == first.txn_count

    def test_reimport_does_not_grow_the_store(self, settings: Settings) -> None:
        """`import_id` is derived from the content hash, the account *and the timestamp*, so a naive
        re-run mints a second import record and a second verbatim copy of every source row -- while
        correctly reporting "0 inserted" for the transactions and looking idempotent."""
        _place(settings, RH, "RH.csv")
        _manifest(settings, _entry("RH.csv", "rh-taxable"))

        service.import_paths(settings=settings, imported_at=dt.datetime(2026, 8, 1, tzinfo=dt.UTC))
        counts_first = _store_counts(settings)
        service.import_paths(settings=settings, imported_at=dt.datetime(2026, 9, 1, tzinfo=dt.UTC))
        counts_second = _store_counts(settings)

        assert counts_second == counts_first

    def test_provenance_keeps_pointing_at_the_first_import(self, settings: Settings) -> None:
        """The stored row is the one that was there; its provenance is the import that produced it."""
        _place(settings, RH, "RH.csv")
        _manifest(settings, _entry("RH.csv", "rh-taxable"))

        first = service.import_paths(settings=settings)
        second = service.import_paths(settings=settings)
        assert second.files[0].import_id == first.files[0].import_id

    def test_a_restated_row_is_a_conflict_not_an_overwrite(self, settings: Settings) -> None:
        """A figure that may already have been reported on a tax form is never silently replaced."""
        _place(settings, RH, "RH.csv")
        _manifest(settings, _entry("RH.csv", "rh-taxable"))
        service.import_paths(settings=settings)

        with sqlite.connect(settings.ledger_path) as conn:
            row = conn.execute(
                "SELECT txn_id, amount FROM txn WHERE amount IS NOT NULL LIMIT 1"
            ).fetchone()
            conn.execute(
                "UPDATE txn SET amount = ? WHERE txn_id = ?", ("999999.99", row["txn_id"])
            )

        run = service.import_paths(settings=settings)
        assert run.files[0].status is service.FileStatus.CONFLICTS
        assert not run.ok, "a conflict is not a successful import"
        assert any(row["txn_id"] in c for c in run.files[0].conflicts)

        with sqlite.connect(settings.ledger_path, read_only=True) as conn:
            after = conn.execute(
                "SELECT amount FROM txn WHERE txn_id = ?", (row["txn_id"],)
            ).fetchone()
        assert after["amount"] == "999999.99", "the stored row was left alone"

    def test_reassigning_a_file_to_another_account_warns(self, settings: Settings) -> None:
        """The old rows do not move, so the same trades now exist under two account ids."""
        _place(settings, RH, "RH.csv")
        _manifest(settings, _entry("RH.csv", "rh-taxable"))
        service.import_paths(settings=settings)

        _manifest(settings, _entry("RH.csv", "rh-roth", treatment="roth_ira"))
        run = service.import_paths(settings=settings)

        assert run.files[0].warnings, "silently duplicating an account's history is not acceptable"
        assert "rh-taxable" in run.files[0].warnings[0]


def _store_counts(settings: Settings) -> dict[str, int]:
    with sqlite.connect(settings.ledger_path, read_only=True) as conn:
        return {
            table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in ("txn", "raw_import", "raw_row", "account", "instrument")
        }

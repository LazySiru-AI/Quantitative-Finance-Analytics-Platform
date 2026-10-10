"""Account status: open | closed, from the manifest through to the hydrated `Account`.

Three properties matter here that no other test covers:

* the manifest default (absent means open) and the "any entry says closed" merge rule for an
  account_id declared across several files -- the identity check in `load_manifest` deliberately
  ignores `status` so those entries are allowed to disagree about it;
* the `_migrate_account_status` ALTER TABLE is guarded and safe to run twice, like the other
  migrations in `app.db.sqlite`;
* `status` round-trips through `upsert_account` / `fetch_accounts` like every other `Account` field.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.core.models import Account, AccountStatus, AccountType, Broker, TaxTreatment
from app.db import sqlite as ledger
from app.ingest.manifest import ManifestError, load_manifest

ENTRY = """
[[account]]
file = "{file}"
account_id = "{account_id}"
label = "{label}"
tax_treatment = "{treatment}"
account_type = "{account_type}"
{status_line}"""


def _entry(
    file: str,
    account_id: str,
    *,
    treatment: str = "taxable",
    account_type: str = "cash",
    label: str | None = None,
    status: str | None = None,
) -> str:
    return ENTRY.format(
        file=file,
        account_id=account_id,
        label=label or account_id,
        treatment=treatment,
        account_type=account_type,
        status_line=f'status = "{status}"\n' if status is not None else "",
    )


def _manifest(settings: Settings, body: str) -> Path:
    path = settings.data_dir / "accounts.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Manifest parsing
# ---------------------------------------------------------------------------


class TestManifestStatus:
    def test_absent_status_is_open(self, settings: Settings) -> None:
        path = _manifest(settings, _entry("RH.csv", "rh"))
        book = load_manifest(path)
        assert book.entries[0].account.status is AccountStatus.OPEN

    def test_status_closed_parses(self, settings: Settings) -> None:
        path = _manifest(settings, _entry("RH.csv", "rh", status="closed"))
        book = load_manifest(path)
        assert book.entries[0].account.status is AccountStatus.CLOSED

    def test_status_open_parses_explicitly_too(self, settings: Settings) -> None:
        path = _manifest(settings, _entry("RH.csv", "rh", status="open"))
        book = load_manifest(path)
        assert book.entries[0].account.status is AccountStatus.OPEN

    def test_invalid_status_names_the_valid_values(self, settings: Settings) -> None:
        path = _manifest(settings, _entry("RH.csv", "rh", status="retired"))
        with pytest.raises(ManifestError) as excinfo:
            load_manifest(path)
        message = str(excinfo.value)
        assert "retired" in message
        assert "open" in message
        assert "closed" in message

    def test_any_entry_closed_closes_the_account(self, settings: Settings) -> None:
        """Two files, one account_id: the later file marks it closed, the earlier one said nothing."""
        path = _manifest(
            settings,
            _entry("RH-2025.csv", "rh") + _entry("RH-2026.csv", "rh", status="closed"),
        )
        book = load_manifest(path)
        assert len(book.entries) == 2
        assert {e.account.status for e in book.entries} == {AccountStatus.CLOSED}

    def test_order_of_the_closed_declaration_does_not_matter(self, settings: Settings) -> None:
        """Same rule, closed entry declared first this time."""
        path = _manifest(
            settings,
            _entry("RH-2025.csv", "rh", status="closed") + _entry("RH-2026.csv", "rh"),
        )
        book = load_manifest(path)
        assert {e.account.status for e in book.entries} == {AccountStatus.CLOSED}

    def test_all_entries_open_stays_open(self, settings: Settings) -> None:
        path = _manifest(
            settings,
            _entry("RH-2025.csv", "rh", status="open") + _entry("RH-2026.csv", "rh"),
        )
        book = load_manifest(path)
        assert {e.account.status for e in book.entries} == {AccountStatus.OPEN}

    def test_entries_may_disagree_about_status_without_raising(self, settings: Settings) -> None:
        """The `described differently` guard covers label/tax_treatment/account_type, not status."""
        path = _manifest(
            settings,
            _entry("RH-2025.csv", "rh") + _entry("RH-2026.csv", "rh", status="closed"),
        )
        # Must not raise ManifestError("described differently ...").
        load_manifest(path)

    def test_entries_still_must_agree_about_tax_treatment(self, settings: Settings) -> None:
        """The merge is specific to `status` -- every other identity field is still enforced."""
        path = _manifest(
            settings,
            _entry("RH-2025.csv", "rh", treatment="taxable", status="closed")
            + _entry("RH-2026.csv", "rh", treatment="roth_ira"),
        )
        with pytest.raises(ManifestError, match="described differently"):
            load_manifest(path)


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


class TestMigration:
    def test_account_status_migration_is_idempotent(self, settings: Settings) -> None:
        with ledger.connect(settings.ledger_path) as conn:
            ledger.migrate(conn)
            ledger.migrate(conn)  # must not raise "duplicate column name"

            columns = [row["name"] for row in conn.execute("PRAGMA table_info(account)")]
            assert columns.count("status") == 1

    def test_guarded_alter_runs_cleanly_against_a_pre_existing_table(
        self, settings: Settings
    ) -> None:
        """Simulate a database that predates `status`, the way a real upgrade will find one."""
        with ledger.connect(settings.ledger_path) as conn:
            conn.executescript(ledger.SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.execute("ALTER TABLE account DROP COLUMN status")
            columns_before = {row["name"] for row in conn.execute("PRAGMA table_info(account)")}
            assert "status" not in columns_before

            ledger._migrate_account_status(conn)
            ledger._migrate_account_status(conn)  # idempotent on its own, not just via migrate()

            columns_after = [row["name"] for row in conn.execute("PRAGMA table_info(account)")]
            assert columns_after.count("status") == 1

    def test_migration_backfills_open_for_existing_rows(self, settings: Settings) -> None:
        with ledger.connect(settings.ledger_path) as conn:
            conn.executescript(ledger.SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.execute("ALTER TABLE account DROP COLUMN status")
            conn.execute(
                "INSERT INTO account (account_id, broker, label, tax_treatment, account_type) "
                "VALUES ('rh-taxable', 'robinhood', 'RH taxable', 'taxable', 'cash')"
            )

            ledger._migrate_account_status(conn)

            row = conn.execute(
                "SELECT status FROM account WHERE account_id = 'rh-taxable'"
            ).fetchone()
            assert row["status"] == "open"


# ---------------------------------------------------------------------------
# Round-trip through sqlite
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_status_round_trips_through_upsert_and_fetch(self, settings: Settings) -> None:
        with ledger.connect(settings.ledger_path) as conn:
            ledger.migrate(conn)
            account = Account(
                account_id="rh-roth",
                broker=Broker.ROBINHOOD,
                label="RH Roth",
                tax_treatment=TaxTreatment.ROTH_IRA,
                account_type=AccountType.RETIREMENT,
                status=AccountStatus.CLOSED,
            )
            ledger.upsert_account(conn, account)

            [fetched] = ledger.fetch_accounts(conn)
            assert fetched.status is AccountStatus.CLOSED
            assert fetched == account

    def test_default_status_round_trips_as_open(self, settings: Settings) -> None:
        with ledger.connect(settings.ledger_path) as conn:
            ledger.migrate(conn)
            account = Account(
                account_id="rh-taxable",
                broker=Broker.ROBINHOOD,
                label="RH taxable",
                tax_treatment=TaxTreatment.TAXABLE,
                account_type=AccountType.CASH,
            )
            ledger.upsert_account(conn, account)

            [fetched] = ledger.fetch_accounts(conn)
            assert fetched.status is AccountStatus.OPEN

    def test_upsert_can_flip_an_account_from_open_to_closed(self, settings: Settings) -> None:
        """A re-ingest after the manifest is edited to declare the account closed."""
        with ledger.connect(settings.ledger_path) as conn:
            ledger.migrate(conn)
            base = Account(
                account_id="rh-roth",
                broker=Broker.ROBINHOOD,
                label="RH Roth",
                tax_treatment=TaxTreatment.ROTH_IRA,
                account_type=AccountType.RETIREMENT,
            )
            ledger.upsert_account(conn, base)
            [fetched] = ledger.fetch_accounts(conn)
            assert fetched.status is AccountStatus.OPEN

            ledger.upsert_account(conn, base.model_copy(update={"status": AccountStatus.CLOSED}))
            [fetched_again] = ledger.fetch_accounts(conn)
            assert fetched_again.status is AccountStatus.CLOSED

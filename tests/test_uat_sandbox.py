"""Per-run sandbox isolation.

Runs 3-5 replay July 2026 sessions, but before ``sandbox_settings`` took a ``name`` parameter every
run shared one ledger at ``uat/sandbox/store/ledger.sqlite``. A July run would then have browsed
August trades left by runs 1 and 2 through the dashboard -- future data reaching the decision-maker
through the UI, which is exactly the lookahead defect ``uat.harness.marketdata.AsOfMarket`` exists to
make impossible at the *price* boundary. These tests pin the same guarantee at the *ledger* boundary:
two named sandboxes resolve to different paths, cannot see each other's transactions, never resolve
under the repository's real ``data/``, and ``serve.py`` still refuses to start against the wrong one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_txn, sample_account

from app.config import get_settings
from app.db import sqlite as ledger
from uat.harness.ingest import _link_bars, provision_sandbox, sandbox_settings


def _register_import(conn, import_id: str = "imp1") -> None:
    """The minimum `raw_import` row `make_txn`'s default `import_id` needs to satisfy the FK.

    Mirrors the `stocked` fixture in `tests/test_matching.py` -- `txn.import_id` is a foreign key,
    so a bare account is not enough to insert a transaction.
    """
    conn.execute(
        "INSERT OR IGNORE INTO raw_import (import_id, source_path, filename, file_sha256, "
        "content_hash, broker, account_id, adapter, adapter_version, row_count, usable_row_count, "
        f"imported_at) VALUES ('{import_id}','p','f','s','c','robinhood','rh-taxable',"
        "'robinhood','1',1,1,'2026-01-01T00:00:00Z')"
    )


class TestSandboxSettings:
    def test_default_name_resolves_to_the_original_sandbox_path(self, tmp_path: Path) -> None:
        settings = sandbox_settings(tmp_path)
        assert settings.ledger_path == tmp_path / "uat" / "sandbox" / "store" / "ledger.sqlite"

    def test_named_sandbox_resolves_under_its_own_subdirectory(self, tmp_path: Path) -> None:
        settings = sandbox_settings(tmp_path, "run3")
        assert settings.ledger_path == (
            tmp_path / "uat" / "sandbox" / "run3" / "store" / "ledger.sqlite"
        )

    def test_default_and_named_sandboxes_have_different_ledger_paths(self, tmp_path: Path) -> None:
        default = sandbox_settings(tmp_path)
        named = sandbox_settings(tmp_path, "run3")
        assert default.ledger_path != named.ledger_path

    def test_two_named_sandboxes_have_different_ledger_paths(self, tmp_path: Path) -> None:
        run3 = sandbox_settings(tmp_path, "run3")
        run4 = sandbox_settings(tmp_path, "run4")
        assert run3.ledger_path != run4.ledger_path

    @pytest.mark.parametrize("name", ["sandbox", "run3", "run4", "run5"])
    def test_never_resolves_under_the_repos_real_data_directory(
        self, tmp_path: Path, name: str
    ) -> None:
        """The real `data_dir`/`store_dir` default to `<repo_root>/data` and `<repo_root>/data/store`
        (see `app.config.Settings`); a sandbox must never land there regardless of its name."""
        settings = sandbox_settings(tmp_path, name)
        real_data = tmp_path / "data"
        assert not settings.data_dir.is_relative_to(real_data)
        assert not settings.store_dir.is_relative_to(real_data)

    @pytest.mark.parametrize("bad", ["../escape", "a/b", "a\\b", "..", ".", ""])
    def test_rejects_names_that_are_not_a_plain_directory_component(
        self, tmp_path: Path, bad: str
    ) -> None:
        with pytest.raises(ValueError):
            sandbox_settings(tmp_path, bad)


class TestSandboxLedgerIsolation:
    def test_a_transaction_in_one_sandbox_is_absent_from_another(self, tmp_path: Path) -> None:
        run3 = provision_sandbox(tmp_path, "run3")
        run4 = provision_sandbox(tmp_path, "run4")

        with ledger.connect(run3.ledger_path) as conn:
            ledger.migrate(conn)
            ledger.upsert_account(conn, sample_account())
            _register_import(conn)
            report = ledger.insert_transactions(conn, [make_txn(txn_id="only-in-run3")])
            conn.commit()
        assert report.inserted == 1

        # run4's ledger file must not even exist yet -- nothing has touched it.
        assert not run4.ledger_path.exists()

        with ledger.connect(run4.ledger_path) as conn:
            ledger.migrate(conn)
            run4_fingerprint, run4_count = ledger.ledger_fingerprint(conn)
        assert run4_count == 0

        # The row really is still there in run3, unaffected by run4 having been touched at all, and
        # the two ledgers' fingerprints disagree -- they are not looking at the same data.
        with ledger.connect(run3.ledger_path, read_only=True) as conn:
            run3_fingerprint, run3_count = ledger.ledger_fingerprint(conn)
        assert run3_count == 1
        assert run3_fingerprint != run4_fingerprint

    def test_provisioning_a_sandbox_does_not_create_the_others(self, tmp_path: Path) -> None:
        run3 = provision_sandbox(tmp_path, "run3")
        assert run3.store_dir.exists()
        assert not (tmp_path / "uat" / "sandbox" / "run4").exists()
        assert not (tmp_path / "uat" / "sandbox" / "run5").exists()


class TestProvisionSandbox:
    def test_named_sandbox_links_to_the_canonical_bars_store(self, tmp_path: Path) -> None:
        """The default sandbox is the canonical bar copy; every other sandbox shares it rather than
        copying it, which is what lets three parallel runs each provision cheaply."""
        canonical = provision_sandbox(tmp_path, "sandbox")
        marker = canonical.bars_dir / "interval=1d" / "symbol=AAPL" / "bars.parquet"
        marker.parent.mkdir(parents=True)
        marker.write_bytes(b"not real parquet, just a marker")

        run3 = provision_sandbox(tmp_path, "run3")

        assert run3.bars_dir != canonical.bars_dir
        linked = run3.bars_dir / "interval=1d" / "symbol=AAPL" / "bars.parquet"
        assert linked.read_bytes() == b"not real parquet, just a marker"

    def test_is_idempotent(self, tmp_path: Path) -> None:
        provision_sandbox(tmp_path, "sandbox")
        first = provision_sandbox(tmp_path, "run3")
        second = provision_sandbox(tmp_path, "run3")  # must not raise on the second call
        assert first.store_dir == second.store_dir

    def test_canonical_sandbox_owns_a_plain_bars_directory(self, tmp_path: Path) -> None:
        """The default sandbox is the link *source* for everything else, not itself a link."""
        settings = provision_sandbox(tmp_path, "sandbox")
        assert settings.bars_dir.exists()
        assert settings.bars_dir.is_dir()


class TestLinkBars:
    def test_target_files_are_readable_through_whichever_mechanism_worked(
        self, tmp_path: Path
    ) -> None:
        source = tmp_path / "source-bars"
        marker = source / "interval=1d" / "symbol=AAPL" / "bars.parquet"
        marker.parent.mkdir(parents=True)
        marker.write_bytes(b"a bar store worth sharing")

        target = tmp_path / "sandbox" / "store" / "bars"
        mechanism = _link_bars(source, target)

        assert mechanism in ("junction", "symlink", "copy")
        linked = target / "interval=1d" / "symbol=AAPL" / "bars.parquet"
        assert linked.read_bytes() == b"a bar store worth sharing"


class TestServeRefusalCheck:
    def test_refuses_to_start_when_the_resolved_store_is_not_the_requested_sandbox(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulates the exact failure this check exists for: `app.config.get_settings` is a
        process-wide `lru_cache`d singleton, so a call from earlier in the process (a stale cache
        populated before `--sandbox` is parsed, or a leftover `.env`) can leave `get_settings()`
        pointed somewhere other than the sandbox `serve.py` was just told to serve. The check must
        still catch that rather than silently serving the wrong ledger.
        """
        import uat.harness.serve as serve_mod

        other = tmp_path / "somewhere-else"
        monkeypatch.setenv("INVDASH_REPO_ROOT", str(tmp_path))
        monkeypatch.setenv("INVDASH_DATA_DIR", str(other / "data"))
        monkeypatch.setenv("INVDASH_STORE_DIR", str(other / "store"))
        monkeypatch.setenv("INVDASH_CACHE_DIR", str(other / "cache"))
        get_settings.cache_clear()
        get_settings()  # pre-populate the singleton with the "stale" settings, as a prior caller would

        monkeypatch.setattr(serve_mod, "_REPO", tmp_path)
        try:
            with pytest.raises(SystemExit, match="refusing to start"):
                serve_mod.main(["--sandbox", "run3", "--port", "8003"])
        finally:
            get_settings.cache_clear()

    def test_still_refuses_when_the_stale_settings_happen_to_be_the_real_data_store(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The refusal is not specific to one particular wrong path -- it must fire just as hard if
        the stale cache happens to be the user's real `data/store`, which is the one case that must
        never be silently served to a UAT persona."""
        import uat.harness.serve as serve_mod

        real_looking = tmp_path / "data"
        monkeypatch.setenv("INVDASH_REPO_ROOT", str(tmp_path))
        monkeypatch.setenv("INVDASH_DATA_DIR", str(real_looking))
        monkeypatch.setenv("INVDASH_STORE_DIR", str(real_looking / "store"))
        monkeypatch.setenv("INVDASH_CACHE_DIR", str(real_looking / "cache"))
        get_settings.cache_clear()
        get_settings()

        monkeypatch.setattr(serve_mod, "_REPO", tmp_path)
        try:
            with pytest.raises(SystemExit, match="refusing to start"):
                serve_mod.main(["--sandbox", "sandbox", "--port", "8001"])
        finally:
            get_settings.cache_clear()

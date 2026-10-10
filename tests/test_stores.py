"""Store behaviour: schema, idempotent re-import, replay ordering, and the bar store.

The idempotency tests are the point of this file. Re-importing an overlapping export is the normal
monthly workflow, and if it duplicates rows every tax number downstream doubles.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import threading
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from app.config import Settings
from app.core.models import TaxTreatment, TxnAction
from app.db import duck
from app.db import sqlite as ledger
from tests.conftest import make_txn, sample_account


class TestSchema:
    def test_migrate_is_idempotent(self, settings: Settings) -> None:
        with ledger.connect(settings.ledger_path) as conn:
            assert ledger.migrate(conn) == ledger.SCHEMA_VERSION
            assert ledger.migrate(conn) == ledger.SCHEMA_VERSION
            versions = conn.execute("SELECT COUNT(*) AS n FROM schema_version").fetchone()["n"]
        assert versions == 1

    def test_derived_build_is_gone(self, conn: sqlite3.Connection) -> None:
        """A fresh database has no `derived_build`, because there is no derived tier to track.

        It recorded rebuilds of materialised lots, positions and gains -- tables the design moved
        away from. Nothing ever wrote it, so `/api/health/stores` reported "never built" forever and
        the Portfolio page rendered that beside figures that were correct.
        """
        found = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'derived_build'"
        ).fetchone()
        assert found is None

    def test_an_existing_database_has_the_table_dropped(self, settings: Settings) -> None:
        """The upgrade path: a ledger created before version 3 still carries the table.

        Recreated here as a pre-3 database would have it, because `schema.sql` no longer contains
        the DDL and a test that only checked a fresh database would prove nothing about the ledgers
        this migration exists for.
        """
        with ledger.connect(settings.ledger_path) as conn:
            ledger.migrate(conn)
            conn.execute(
                "CREATE TABLE derived_build ("
                "build_id TEXT PRIMARY KEY, built_at TEXT NOT NULL, "
                "ledger_fingerprint TEXT NOT NULL, txn_count INTEGER NOT NULL, "
                "code_version TEXT NOT NULL, note TEXT)"
            )
            assert ledger.migrate(conn) == ledger.SCHEMA_VERSION
            found = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'derived_build'"
            ).fetchone()
        assert found is None

    def test_a_non_empty_derived_build_is_left_alone(self, settings: Settings) -> None:
        """Only dropped when empty.

        Nothing ever wrote this table, so it is empty everywhere -- but rows in it would be evidence
        that something did, which is a thing to look at rather than to delete. This file's standing
        rule is that source data is never destroyed, and "we checked" is a cheaper guarantee than
        "we were sure".
        """
        with ledger.connect(settings.ledger_path) as conn:
            ledger.migrate(conn)
            conn.execute(
                "CREATE TABLE derived_build ("
                "build_id TEXT PRIMARY KEY, built_at TEXT NOT NULL, "
                "ledger_fingerprint TEXT NOT NULL, txn_count INTEGER NOT NULL, "
                "code_version TEXT NOT NULL, note TEXT)"
            )
            conn.execute(
                "INSERT INTO derived_build VALUES ('b1','2026-01-01T00:00:00Z','fp',0,'0.1.0',NULL)"
            )
            ledger.migrate(conn)
            rows = conn.execute("SELECT COUNT(*) AS n FROM derived_build").fetchone()["n"]
        assert rows == 1

    def test_foreign_keys_are_enforced(self, conn: sqlite3.Connection) -> None:
        """SQLite disables FK enforcement by default; without the pragma the schema is decorative."""
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO txn (txn_id, import_id, source_row, account_id, broker, action, trade_date) "
                "VALUES ('x', 'nonexistent-import', 0, 'rh-taxable', 'robinhood', 'buy', '2026-01-01')"
            )

    def test_cusip_uniqueness_is_enforced(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO instrument (instrument_id, primary_symbol, cusip, kind) "
            "VALUES ('i1', 'BRK.B', '084670702', 'equity')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO instrument (instrument_id, primary_symbol, cusip, kind) "
                "VALUES ('i2', 'BRK-B', '084670702', 'equity')"
            )

    def test_null_cusips_do_not_collide(self, conn: sqlite3.Connection) -> None:
        """The unique index is partial: many instruments legitimately have no CUSIP."""
        conn.execute(
            "INSERT INTO instrument (instrument_id, primary_symbol, cusip, kind) "
            "VALUES ('i1', 'ETH', NULL, 'crypto')"
        )
        conn.execute(
            "INSERT INTO instrument (instrument_id, primary_symbol, cusip, kind) "
            "VALUES ('i2', 'ETHD', NULL, 'crypto')"
        )


class TestIdempotentImport:
    def _import(self, conn: sqlite3.Connection, import_id: str = "imp1") -> None:
        conn.execute(
            "INSERT OR IGNORE INTO raw_import (import_id, source_path, filename, file_sha256, "
            "content_hash, broker, account_id, adapter, adapter_version, row_count, "
            "usable_row_count, imported_at) VALUES (?, 'p', 'f.csv', 'sha', 'content', "
            "'robinhood', 'rh-taxable', 'robinhood', '1', 1, 1, '2026-01-01T00:00:00Z')",
            (import_id,),
        )

    def test_first_insert_writes_rows(self, conn: sqlite3.Connection) -> None:
        self._import(conn)
        report = ledger.insert_transactions(conn, [make_txn(txn_id="a"), make_txn(txn_id="b")])
        assert (report.inserted, report.duplicates, report.conflicts) == (2, 0, [])

    def test_reimport_of_identical_rows_is_a_noop(self, conn: sqlite3.Connection) -> None:
        """The monthly workflow: a fresh export overlapping the previous one."""
        self._import(conn)
        rows = [make_txn(txn_id="a"), make_txn(txn_id="b")]
        ledger.insert_transactions(conn, rows)
        report = ledger.insert_transactions(conn, rows)

        assert report.inserted == 0
        assert report.duplicates == 2
        assert report.is_clean
        total = conn.execute("SELECT COUNT(*) AS n FROM txn").fetchone()["n"]
        assert total == 2

    def test_reimport_tolerates_trailing_zero_changes(self, conn: sqlite3.Connection) -> None:
        """A broker writing 50.00 where it once wrote 50 is not a restatement."""
        self._import(conn)
        ledger.insert_transactions(conn, [make_txn(txn_id="a", quantity="50", price="24.10")])
        report = ledger.insert_transactions(
            conn, [make_txn(txn_id="a", quantity="50.00", price="24.1000")]
        )
        assert report.duplicates == 1
        assert report.is_clean

    def test_overlapping_import_adds_only_new_rows(self, conn: sqlite3.Connection) -> None:
        self._import(conn, "imp1")
        self._import(conn, "imp2")
        ledger.insert_transactions(conn, [make_txn(txn_id="a"), make_txn(txn_id="b")])
        report = ledger.insert_transactions(
            conn,
            [
                make_txn(txn_id="b", import_id="imp2"),
                make_txn(txn_id="c", import_id="imp2"),
            ],
        )
        assert (report.inserted, report.duplicates) == (1, 1)
        assert conn.execute("SELECT COUNT(*) AS n FROM txn").fetchone()["n"] == 3

    def test_changed_content_is_a_conflict_not_an_overwrite(self, conn: sqlite3.Connection) -> None:
        """A restated figure must not silently replace one that may already be on a filed return."""
        self._import(conn)
        ledger.insert_transactions(conn, [make_txn(txn_id="a", amount="-1205.00")])
        report = ledger.insert_transactions(conn, [make_txn(txn_id="a", amount="-1300.00")])

        assert report.inserted == 0
        assert not report.is_clean
        assert [c[1] for c in report.conflicts] == ["amount"]

        stored = conn.execute("SELECT amount FROM txn WHERE txn_id = 'a'").fetchone()["amount"]
        assert Decimal(stored) == Decimal("-1205.00")

    def test_provenance_change_alone_is_not_a_conflict(self, conn: sqlite3.Connection) -> None:
        """The same trade from a newer export arrives with a different import_id. Not a restatement."""
        self._import(conn, "imp1")
        self._import(conn, "imp2")
        ledger.insert_transactions(conn, [make_txn(txn_id="a", import_id="imp1", source_row=3)])
        report = ledger.insert_transactions(
            conn, [make_txn(txn_id="a", import_id="imp2", source_row=17)]
        )
        assert report.duplicates == 1
        assert report.is_clean


class TestReplayOrdering:
    def test_order_is_total_and_deterministic(self, conn: sqlite3.Connection) -> None:
        """Robinhood supplies no time-of-day, so ordering must still be total or lot replay drifts."""
        conn.execute(
            "INSERT INTO raw_import (import_id, source_path, filename, file_sha256, content_hash, "
            "broker, account_id, adapter, adapter_version, row_count, usable_row_count, imported_at) "
            "VALUES ('imp1','p','f','s','c','robinhood','rh-taxable','robinhood','1',3,3,'2026-01-01T00:00:00Z')"
        )
        same_day = dt.date(2026, 3, 2)
        ledger.insert_transactions(
            conn,
            [
                make_txn(txn_id="c", trade_date=same_day, sequence=2),
                make_txn(txn_id="a", trade_date=same_day, sequence=0),
                make_txn(txn_id="b", trade_date=same_day, sequence=1),
            ],
        )
        first = [r["txn_id"] for r in ledger.fetch_transactions(conn)]
        second = [r["txn_id"] for r in ledger.fetch_transactions(conn)]
        assert first == ["a", "b", "c"] == second


class TestExecutedAtUtcOrdering:
    """`fetch_transactions` must sort by instant, not by the text of `executed_at`.

    Regression tests for a real ordering bug: `executed_at` is stored as ``.isoformat()`` text
    carrying a *fixed* UTC offset, and the Webull adapter deliberately changes that offset across a
    DST boundary (``-04:00``/EDT before the November fall-back, ``-05:00``/EST after -- see
    `_pin_offset` in ``app/ingest/adapters/webull.py``, which explains why pinning the offset rather
    than the ``ZoneInfo`` itself is required for *its* ordering to work). SQL text comparison does not
    know about UTC offsets, so ordering directly on `executed_at` can return the later instant first.
    `core/lots.py` `_consume_fifo` trusts `fetch_transactions`' order to break ties when two lots
    share an `acquired_date`, so a reversed fetch on a same-day sale picks the wrong lot -- wrong cost
    basis, wrong realised gain. 2026-11-01 is a real US fall-back Sunday, used verbatim below rather
    than a synthetic date so the test exercises the exact calendar mechanics in production.
    """

    _EDT = dt.timezone(dt.timedelta(hours=-4), "EDT")
    _EST = dt.timezone(dt.timedelta(hours=-5), "EST")

    def _import(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO raw_import (import_id, source_path, filename, file_sha256, content_hash, "
            "broker, account_id, adapter, adapter_version, row_count, usable_row_count, imported_at) "
            "VALUES ('imp1','p','f','s','c','webull','rh-taxable','webull','1',3,3,'2026-01-01T00:00:00Z')"
        )

    def test_fall_back_hour_sorts_by_instant_not_by_text(self, conn: sqlite3.Connection) -> None:
        """The repeated ET hour: 01:30 EDT (05:30 UTC) happens before 01:15 EST (06:15 UTC) even
        though '01:15' sorts before '01:30' as text -- the case that breaks plain text ordering."""
        self._import(conn)
        same_day = dt.date(2026, 11, 1)
        first_pass = make_txn(txn_id="first-pass", trade_date=same_day, sequence=0).model_copy(
            update={"executed_at": dt.datetime(2026, 11, 1, 1, 30, tzinfo=self._EDT)}
        )
        second_pass = make_txn(txn_id="second-pass", trade_date=same_day, sequence=1).model_copy(
            update={"executed_at": dt.datetime(2026, 11, 1, 1, 15, tzinfo=self._EST)}
        )

        # Inserted out of chronological order deliberately -- insertion order must not matter.
        ledger.insert_transactions(conn, [second_pass, first_pass])

        order = [r["txn_id"] for r in ledger.fetch_transactions(conn)]
        assert order == ["first-pass", "second-pass"]

    def test_null_executed_at_rows_keep_falling_back_to_sequence(
        self, conn: sqlite3.Connection
    ) -> None:
        """A mix of timed and untimed rows on one trade_date: untimed rows must not scatter among the
        timed ones on account_id/import_id text quirks -- they still resolve by (sequence, txn_id),
        exactly as before this column existed."""
        self._import(conn)
        same_day = dt.date(2026, 3, 2)
        timed = make_txn(txn_id="timed", trade_date=same_day, sequence=5).model_copy(
            update={"executed_at": dt.datetime(2026, 3, 2, 10, 0, tzinfo=dt.UTC)}
        )
        untimed_b = make_txn(txn_id="untimed-b", trade_date=same_day, sequence=1)
        untimed_a = make_txn(txn_id="untimed-a", trade_date=same_day, sequence=0)

        ledger.insert_transactions(conn, [timed, untimed_b, untimed_a])

        order = [r["txn_id"] for r in ledger.fetch_transactions(conn)]
        assert order == ["untimed-a", "untimed-b", "timed"]

    def test_ordering_is_stable_across_a_reread(self, conn: sqlite3.Connection) -> None:
        self._import(conn)
        same_day = dt.date(2026, 11, 1)
        first_pass = make_txn(txn_id="a", trade_date=same_day, sequence=0).model_copy(
            update={"executed_at": dt.datetime(2026, 11, 1, 1, 30, tzinfo=self._EDT)}
        )
        second_pass = make_txn(txn_id="b", trade_date=same_day, sequence=1).model_copy(
            update={"executed_at": dt.datetime(2026, 11, 1, 1, 15, tzinfo=self._EST)}
        )
        ledger.insert_transactions(conn, [first_pass, second_pass])

        first_read = [r["txn_id"] for r in ledger.fetch_transactions(conn)]
        second_read = [r["txn_id"] for r in ledger.fetch_transactions(conn)]
        assert first_read == ["a", "b"] == second_read


class TestExecutedAtUtcMigration:
    """`executed_at_utc` must be backfillable on a real, already-populated database.

    There is real user data in this ledger, so the fix for the ordering bug cannot require a
    re-import: it has to add the column and derive its value from what is already stored. This
    reproduces a genuine pre-fix database (schema_version 1, no `executed_at_utc` column at all) by
    stripping the current schema back down rather than hand-maintaining a frozen copy, so the test
    breaks if the legacy shape it simulates ever drifts from `schema.sql`.
    """

    def _seed_legacy_database(self, conn: sqlite3.Connection) -> None:
        conn.execute("ALTER TABLE txn DROP COLUMN executed_at_utc")
        conn.execute("DELETE FROM schema_version")
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (1, '2020-01-01T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO raw_import (import_id, source_path, filename, file_sha256, content_hash, "
            "broker, account_id, adapter, adapter_version, row_count, usable_row_count, imported_at) "
            "VALUES ('imp1','p','f','s','c','webull','rh-taxable','webull','1',3,3,'2026-01-01T00:00:00Z')"
        )
        # 'a': 01:30 EDT = 05:30 UTC, the earlier instant. 'b': 01:15 EST = 06:15 UTC, the later
        # instant -- same repeated-hour case as TestExecutedAtUtcOrdering, seeded directly as text the
        # way a real pre-fix row would already be on disk. 'c' has no executed_at at all, the common
        # case for Robinhood/SoFi rows.
        for txn_id, executed_at, seq in (
            ("a", "2026-11-01T01:30:00-04:00", 0),
            ("b", "2026-11-01T01:15:00-05:00", 1),
        ):
            conn.execute(
                "INSERT INTO txn (txn_id, import_id, source_row, account_id, broker, action, "
                "trade_date, executed_at, sequence, quantity, price, fees, amount) VALUES "
                "(?, 'imp1', ?, 'rh-taxable', 'webull', 'buy', '2026-11-01', ?, ?, '1', '10', '0', '-10')",
                (txn_id, seq, executed_at, seq),
            )
        conn.execute(
            "INSERT INTO txn (txn_id, import_id, source_row, account_id, broker, action, "
            "trade_date, sequence, quantity, price, fees, amount) VALUES "
            "('c', 'imp1', 2, 'rh-taxable', 'webull', 'buy', '2026-11-01', 2, '1', '10', '0', '-10')"
        )

    def test_migration_backfills_and_is_safe_to_run_twice(self, conn: sqlite3.Connection) -> None:
        self._seed_legacy_database(conn)

        first_version = ledger.migrate(conn)
        versions_after_first = conn.execute(
            "SELECT COUNT(*) AS n FROM schema_version"
        ).fetchone()["n"]
        assert versions_after_first == 2  # the seeded v1 row, plus the new v2 row this call adds

        columns = {row["name"] for row in conn.execute("PRAGMA table_info(txn)")}
        assert "executed_at_utc" in columns

        backfilled = {
            row["txn_id"]: row["executed_at_utc"]
            for row in conn.execute("SELECT txn_id, executed_at_utc FROM txn")
        }
        assert backfilled["a"] == "2026-11-01T05:30:00.000000+00:00"
        assert backfilled["b"] == "2026-11-01T06:15:00.000000+00:00"
        assert backfilled["c"] is None  # nothing to derive from -- executed_at was never set

        # The point of the whole fix: replay order is now correct on data that predates it.
        assert [r["txn_id"] for r in ledger.fetch_transactions(conn)] == ["c", "a", "b"]

        second_version = ledger.migrate(conn)
        assert second_version == first_version == ledger.SCHEMA_VERSION

        unchanged = {
            row["txn_id"]: row["executed_at_utc"]
            for row in conn.execute("SELECT txn_id, executed_at_utc FROM txn")
        }
        assert unchanged == backfilled, "a second migrate() call rewrote already-backfilled rows"
        versions_after_second = conn.execute(
            "SELECT COUNT(*) AS n FROM schema_version"
        ).fetchone()["n"]
        assert versions_after_second == versions_after_first, (
            "a second migrate() call must not insert another schema_version row"
        )


class TestReplayOrderMigration:
    """`replay_order` must be backfillable on a real, already-populated database -- see
    `_migrate_replay_order`'s docstring for the correctness bug this repairs: a database written
    before this column existed replayed every trading day backwards for Robinhood and SoFi.

    Reproduces a genuine pre-fix database (schema_version 3, no `replay_order` column) by stripping
    the column back off a freshly migrated one, the same approach `TestExecutedAtUtcMigration` takes
    and for the same reason -- the legacy shape then breaks if it ever drifts from `schema.sql`
    instead of silently testing something that no longer matches production.
    """

    def _seed_legacy_database(self, conn: sqlite3.Connection) -> None:
        conn.execute("ALTER TABLE txn DROP COLUMN replay_order")
        conn.execute("DELETE FROM schema_version")
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (3, '2020-01-01T00:00:00Z')"
        )
        for import_id, adapter in (
            ("imp-rh", "robinhood"),
            ("imp-wb", "webull"),
            # A stand-in for a hypothetical adapter that writes oldest-first and is therefore
            # absent from `_NEWEST_FIRST_ADAPTERS` -- the backfill must leave its rows alone.
            ("imp-schwab", "schwab"),
        ):
            conn.execute(
                "INSERT INTO raw_import (import_id, source_path, filename, file_sha256, "
                "content_hash, broker, account_id, adapter, adapter_version, row_count, "
                "usable_row_count, imported_at) VALUES (?, 'p', 'f', 's', ?, 'robinhood', "
                "'rh-taxable', ?, '1', 3, 3, '2026-01-01T00:00:00Z')",
                (import_id, import_id, adapter),
            )

        # Robinhood, newest-first: source_row 0 is the file's first, most-recent row.
        for txn_id, source_row in (("a", 0), ("b", 1), ("c", 2)):
            conn.execute(
                "INSERT INTO txn (txn_id, import_id, source_row, account_id, broker, action, "
                "trade_date, sequence, quantity, price, fees, amount) VALUES "
                "(?, 'imp-rh', ?, 'rh-taxable', 'robinhood', 'buy', '2026-03-02', ?, "
                "'1', '10', '0', '-10')",
                (txn_id, source_row, source_row),
            )
        # Webull, also newest-first, in a separate import on a separate date -- proves the backfill
        # is scoped per import (MAX(source_row) within that import) rather than reading source_row
        # globally, which would let one file's numbering leak into another's.
        for txn_id, source_row in (("d", 0), ("e", 1)):
            conn.execute(
                "INSERT INTO txn (txn_id, import_id, source_row, account_id, broker, action, "
                "trade_date, sequence, quantity, price, fees, amount) VALUES "
                "(?, 'imp-wb', ?, 'rh-taxable', 'webull', 'buy', '2026-04-01', ?, "
                "'1', '10', '0', '-10')",
                (txn_id, source_row, source_row),
            )
        # 'schwab': not in `_NEWEST_FIRST_ADAPTERS`, so its rows must be left at the column default.
        for txn_id, source_row in (("f", 0), ("g", 1)):
            conn.execute(
                "INSERT INTO txn (txn_id, import_id, source_row, account_id, broker, action, "
                "trade_date, sequence, quantity, price, fees, amount) VALUES "
                "(?, 'imp-schwab', ?, 'rh-taxable', 'robinhood', 'buy', '2026-05-01', ?, "
                "'1', '10', '0', '-10')",
                (txn_id, source_row, source_row),
            )

    def test_migration_backfills_reversed_ranks_grouped_per_import(
        self, conn: sqlite3.Connection
    ) -> None:
        self._seed_legacy_database(conn)

        first_version = ledger.migrate(conn)
        versions_after_first = conn.execute(
            "SELECT COUNT(*) AS n FROM schema_version"
        ).fetchone()["n"]
        assert versions_after_first == 2  # the seeded v3 row, plus the new v4 row this call adds
        assert first_version == ledger.SCHEMA_VERSION

        columns = {row["name"] for row in conn.execute("PRAGMA table_info(txn)")}
        assert "replay_order" in columns

        ranks = {
            row["txn_id"]: row["replay_order"]
            for row in conn.execute("SELECT txn_id, replay_order FROM txn")
        }
        # Robinhood: source_row 0,1,2 (newest-first) -> replay_order 2,1,0 -- the file read
        # backwards, matching ExportOrder.replay_order_for(index, 3) exactly.
        assert (ranks["a"], ranks["b"], ranks["c"]) == (2, 1, 0)
        # Webull, a separate import: source_row 0,1 -> replay_order 1,0, not 4,3 -- confirms the
        # backfill is scoped per import rather than to one global source_row range.
        assert (ranks["d"], ranks["e"]) == (1, 0)
        # An adapter absent from `_NEWEST_FIRST_ADAPTERS` is left at the column's default (0),
        # not reversed.
        assert (ranks["f"], ranks["g"]) == (0, 0)

        # The point of the whole fix, on data that predates it: replay order is now correct.
        rh_order = [
            r["txn_id"] for r in ledger.fetch_transactions(conn) if r["import_id"] == "imp-rh"
        ]
        assert rh_order == ["c", "b", "a"]
        wb_order = [
            r["txn_id"] for r in ledger.fetch_transactions(conn) if r["import_id"] == "imp-wb"
        ]
        assert wb_order == ["e", "d"]
        # The untouched import falls back to (replay_order=0, source_row) -- unchanged from
        # before replay_order existed.
        schwab_order = [
            r["txn_id"] for r in ledger.fetch_transactions(conn) if r["import_id"] == "imp-schwab"
        ]
        assert schwab_order == ["f", "g"]

        second_version = ledger.migrate(conn)
        assert second_version == first_version == ledger.SCHEMA_VERSION

        unchanged = {
            row["txn_id"]: row["replay_order"]
            for row in conn.execute("SELECT txn_id, replay_order FROM txn")
        }
        assert unchanged == ranks, "a second migrate() call rewrote already-backfilled ranks"
        versions_after_second = conn.execute(
            "SELECT COUNT(*) AS n FROM schema_version"
        ).fetchone()["n"]
        assert versions_after_second == versions_after_first, (
            "a second migrate() call must not insert another schema_version row"
        )


class TestLedgerFingerprint:
    def test_fingerprint_tracks_content(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO raw_import (import_id, source_path, filename, file_sha256, content_hash, "
            "broker, account_id, adapter, adapter_version, row_count, usable_row_count, imported_at) "
            "VALUES ('imp1','p','f','s','c','robinhood','rh-taxable','robinhood','1',1,1,'2026-01-01T00:00:00Z')"
        )
        empty, count = ledger.ledger_fingerprint(conn)
        assert count == 0

        ledger.insert_transactions(conn, [make_txn(txn_id="a")])
        after, count = ledger.ledger_fingerprint(conn)
        assert count == 1
        assert after != empty

        ledger.insert_transactions(conn, [make_txn(txn_id="a")])
        unchanged, _ = ledger.ledger_fingerprint(conn)
        assert unchanged == after, "a no-op re-import must not invalidate derived state"


class TestAccounts:
    def test_upsert_updates_in_place(self, conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM account")
        ledger.upsert_account(conn, sample_account())
        ledger.upsert_account(
            conn, sample_account(tax_treatment=TaxTreatment.ROTH_IRA)
        )
        rows = conn.execute("SELECT * FROM account").fetchall()
        assert len(rows) == 1
        assert rows[0]["tax_treatment"] == "roth_ira"


class TestMoneyStorage:
    def test_decimals_survive_a_round_trip_exactly(self, conn: sqlite3.Connection) -> None:
        """TEXT storage, not REAL: a double would not represent 1234567.89012345 exactly."""
        conn.execute(
            "INSERT INTO raw_import (import_id, source_path, filename, file_sha256, content_hash, "
            "broker, account_id, adapter, adapter_version, row_count, usable_row_count, imported_at) "
            "VALUES ('imp1','p','f','s','c','robinhood','rh-taxable','robinhood','1',1,1,'2026-01-01T00:00:00Z')"
        )
        precise = Decimal("1234567.89012345")
        ledger.insert_transactions(
            conn,
            [make_txn(txn_id="a", action=TxnAction.BUY, quantity="0.000001", amount=str(-precise))],
        )
        row = conn.execute("SELECT quantity, amount FROM txn WHERE txn_id='a'").fetchone()
        assert Decimal(row["amount"]) == -precise
        assert Decimal(row["quantity"]) == Decimal("0.000001")


class TestIntervalEnum:
    """`duck.Interval` covers seven members: 5m/15m/30m/1h/4h/1d/1w.

    ``15m``, ``30m`` and ``4h`` were added alongside the pre-existing four on the strength of a live
    probe against Yahoo's chart endpoint (2026-08-25) confirming it natively serves all three at their
    requested granularity -- no local resampling required, unlike ``1w``.
    """

    @pytest.mark.parametrize(
        ("value", "member"),
        [
            ("5m", duck.Interval.FIVE_MIN),
            ("15m", duck.Interval.FIFTEEN_MIN),
            ("30m", duck.Interval.THIRTY_MIN),
            ("1h", duck.Interval.HOUR),
            ("4h", duck.Interval.FOUR_HOUR),
            ("1d", duck.Interval.DAY),
            ("1w", duck.Interval.WEEK),
        ],
    )
    def test_every_member_round_trips_from_its_string_value(
        self, value: str, member: duck.Interval
    ) -> None:
        assert duck.Interval(value) is member
        assert member.value == value

    @pytest.mark.parametrize(
        ("interval", "expected"),
        [
            (duck.Interval.FIVE_MIN, True),
            (duck.Interval.FIFTEEN_MIN, True),
            (duck.Interval.THIRTY_MIN, True),
            (duck.Interval.HOUR, True),
            (duck.Interval.FOUR_HOUR, True),
            (duck.Interval.DAY, False),
            (duck.Interval.WEEK, False),
        ],
    )
    def test_is_intraday_covers_all_seven_members(
        self, interval: duck.Interval, expected: bool
    ) -> None:
        """``4h`` counts as intraday: it is sub-daily, shares the 730-day retention ceiling with
        ``1h``, and Yahoo stamps it with a true instant rather than a session date, exactly like
        every other intraday member (see ``YahooProvider._to_frame``)."""
        assert interval.is_intraday is expected

    def test_seven_members_exist_and_nothing_else(self) -> None:
        """A completeness guard: fails loudly if a member is added or removed without the rest of
        this test module (and the sibling completeness tests in test_providers.py,
        test_market_api.py, test_market_registry.py and test_strategy.py) being updated to match."""
        assert {i.value for i in duck.Interval} == {"5m", "15m", "30m", "1h", "4h", "1d", "1w"}


class TestBarStore:
    def _frame(self, start: str, periods: int, close: float = 100.0) -> pd.DataFrame:
        ts = pd.date_range(start, periods=periods, freq="D", tz="UTC")
        return pd.DataFrame(
            {
                "ts": ts,
                "open": [close] * periods,
                "high": [close + 1] * periods,
                "low": [close - 1] * periods,
                "close": [close] * periods,
                "adj_close": [close] * periods,
                "volume": [1_000] * periods,
            }
        )

    def test_write_then_read(self, settings: Settings) -> None:
        with duck.connect() as conn:
            written = duck.write_bars(
                conn, settings.bars_dir, "SOXL", duck.Interval.DAY, self._frame("2026-01-01", 5)
            )
            assert written == 5
            got = duck.read_bars(conn, settings.bars_dir, "SOXL", duck.Interval.DAY)
        assert len(got) == 5

    def test_overlapping_write_deduplicates_on_timestamp(self, settings: Settings) -> None:
        """Incremental fetches deliberately re-request recent sessions; overlap must not duplicate."""
        with duck.connect() as conn:
            duck.write_bars(
                conn, settings.bars_dir, "SOXL", duck.Interval.DAY, self._frame("2026-01-01", 5)
            )
            total = duck.write_bars(
                conn, settings.bars_dir, "SOXL", duck.Interval.DAY, self._frame("2026-01-03", 5)
            )
        assert total == 7  # 5 + 5 with 3 overlapping

    def test_incoming_bar_wins_on_collision(self, settings: Settings) -> None:
        """A corrected bar from the provider must replace the stale one, not be discarded."""
        with duck.connect() as conn:
            duck.write_bars(
                conn, settings.bars_dir, "SOXL", duck.Interval.DAY,
                self._frame("2026-01-01", 3, close=100.0),
            )
            duck.write_bars(
                conn, settings.bars_dir, "SOXL", duck.Interval.DAY,
                self._frame("2026-01-01", 3, close=222.0),
            )
            got = duck.read_bars(conn, settings.bars_dir, "SOXL", duck.Interval.DAY)
        assert set(got["close"]) == {222.0}

    def test_timestamps_round_trip_as_utc_not_host_local_time(self, settings: Settings) -> None:
        """A stored bar must read back on the same calendar day it was written.

        DuckDB re-labels a ``TIMESTAMP WITH TIME ZONE`` with the connection's timezone on read.
        Left at the host default, a bar written as ``2026-01-09T00:00Z`` returned as
        ``2026-01-08T18:00-06:00`` in US Central -- the right instant on the wrong day, which is
        exactly what the daily-bar session-date convention exists to rule out. The failure is
        invisible on a UTC machine, so it gets an explicit test rather than trusting the default.
        """
        written = self._frame("2026-01-09", 3)
        with duck.connect() as conn:
            duck.write_bars(conn, settings.bars_dir, "SOXL", duck.Interval.DAY, written)
            got = duck.read_bars(conn, settings.bars_dir, "SOXL", duck.Interval.DAY)

        assert str(got["ts"].dt.tz) == "UTC"
        assert [t.date() for t in got["ts"]] == [t.date() for t in written["ts"]]

    def test_missing_symbol_returns_empty_frame(self, settings: Settings) -> None:
        """"No data yet" is an ordinary state, not an exception."""
        with duck.connect() as conn:
            got = duck.read_bars(conn, settings.bars_dir, "NOPE", duck.Interval.DAY)
        assert got.empty
        assert list(got.columns) == list(duck.BAR_COLUMNS)

    def test_missing_columns_raise(self, settings: Settings) -> None:
        bad = pd.DataFrame({"ts": [1], "close": [2]})
        with duck.connect() as conn, pytest.raises(ValueError, match="missing columns"):
            duck.write_bars(conn, settings.bars_dir, "SOXL", duck.Interval.DAY, bad)

    def test_partition_layout(self, settings: Settings) -> None:
        path = duck.bar_path(settings.bars_dir, "SOXL", duck.Interval.FIVE_MIN)
        assert path.parent.name == "symbol=SOXL"
        assert path.parent.parent.name == "interval=5m"

    def test_stored_symbols_listing(self, settings: Settings) -> None:
        with duck.connect() as conn:
            for sym in ("SOXL", "NVDA"):
                duck.write_bars(
                    conn, settings.bars_dir, sym, duck.Interval.DAY, self._frame("2026-01-01", 2)
                )
        assert duck.stored_symbols(settings.bars_dir, duck.Interval.DAY) == ["NVDA", "SOXL"]
        assert duck.stored_symbols(settings.bars_dir, duck.Interval.HOUR) == []

    @pytest.mark.parametrize(
        ("interval", "backtestable"),
        [
            (duck.Interval.FIVE_MIN, False),
            (duck.Interval.HOUR, False),
            (duck.Interval.DAY, True),
            (duck.Interval.WEEK, True),
        ],
    )
    def test_only_daily_and_weekly_are_backtestable(
        self, interval: duck.Interval, backtestable: bool
    ) -> None:
        """Yahoo serves 60 days of 5m bars; no statistical claim can rest on that."""
        assert interval.backtestable is backtestable


class TestAtomicReplaceRetry:
    """The bounded retry that closes the residual gap `_write_lock` cannot.

    `_WRITE_LOCKS` stops a reader scanning while a writer replaces, but DuckDB's handle on a scanned
    Parquet outlives both the query and the connection's `close()` -- measured, and recorded on that
    constant. So the handle can still be open just after `read_bars` releases the lock, and on
    Windows `Path.replace` refuses to replace a file that has one. The lock took the original
    failure rate from 62 of 96 writes (65%) down to something that surfaced once in a full-suite run
    and never in eight isolated ones; the retry is what closes the remainder.

    Driven by faking the failure rather than racing for it: a test that waits for a real race is a
    test that passes on a fast machine and tells you nothing.
    """

    def test_a_transient_permission_error_is_retried_and_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        staging = tmp_path / "bars.parquet.tmp"
        target = tmp_path / "bars.parquet"
        staging.write_bytes(b"new")
        target.write_bytes(b"old")

        real_replace = Path.replace
        calls = {"n": 0}

        def flaky(self: Path, other: Path) -> Path:
            calls["n"] += 1
            if calls["n"] < 3:
                raise PermissionError(13, "Access is denied")
            return real_replace(self, other)

        monkeypatch.setattr(Path, "replace", flaky)
        duck._replace_with_retry(staging, target)

        assert calls["n"] == 3
        assert target.read_bytes() == b"new"

    def test_a_persistent_permission_error_still_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exhausting the budget must raise, not hang or swallow.

        A handle still open after the whole backoff is a leak, not a transient scan, and the
        `PermissionError` is then the useful outcome.
        """
        staging = tmp_path / "bars.parquet.tmp"
        target = tmp_path / "bars.parquet"
        staging.write_bytes(b"new")
        target.write_bytes(b"old")

        def always_denied(self: Path, other: Path) -> Path:
            raise PermissionError(13, "Access is denied")

        monkeypatch.setattr(Path, "replace", always_denied)
        monkeypatch.setattr(duck, "_REPLACE_BACKOFF_SECONDS", 0.0)

        with pytest.raises(PermissionError):
            duck._replace_with_retry(staging, target)

        assert target.read_bytes() == b"old"


class TestBarStoreConcurrency:
    """A concurrent reader must not crash a writer's atomic replace.

    Regression test for a real production failure: FastAPI runs synchronous endpoints in a
    threadpool, so a chart read and a background sync for the same symbol/interval genuinely
    overlap. `_WRITE_LOCKS` in `duck.py` originally guarded writer-vs-writer only; `read_bars` took
    no lock at all, even though DuckDB keeps `bars.parquet` open past the query that scanned it. On
    Windows, `Path.replace()` refuses to replace a file with any open handle in the process, so an
    unlocked reader turns the writer's supposedly-atomic ``staging.replace(target)`` into an
    unhandled ``PermissionError`` -- reproduced below with a single writer thread and zero
    writer-vs-writer contention, matching how QA found it (62 of 96 writes, 65%, failed).

    This must run against real files, not `duck.connect()`'s in-memory mode: the race is a Windows
    filesystem-handle interaction that an in-memory database cannot exhibit, and `settings` (see
    `tests/conftest.py`) already points every path at a throwaway temp directory.
    """

    @staticmethod
    def _frame(start: str, periods: int = 3, close: float = 100.0) -> pd.DataFrame:
        ts = pd.date_range(start, periods=periods, freq="D", tz="UTC")
        return pd.DataFrame(
            {
                "ts": ts,
                "open": [close] * periods,
                "high": [close + 1] * periods,
                "low": [close - 1] * periods,
                "close": [close] * periods,
                "adj_close": [close] * periods,
                "volume": [1_000] * periods,
            }
        )

    def test_reader_does_not_crash_a_concurrent_writer(self, settings: Settings) -> None:
        symbol, interval = "SOXL", duck.Interval.DAY

        # Seed the file so readers have something to scan from the very first iteration -- an empty
        # store short-circuits `read_bars` before it ever opens the parquet file.
        with duck.connect(settings.analytics_path) as conn:
            duck.write_bars(conn, settings.bars_dir, symbol, interval, self._frame("2026-01-01"))

        write_errors: list[BaseException] = []
        read_errors: list[BaseException] = []
        writes_done = 0
        stop = threading.Event()
        lock = threading.Lock()

        def writer() -> None:
            nonlocal writes_done
            day = 10
            # 40 writes reproduced the failure reliably in manual testing; bounded so the test has a
            # deterministic end rather than running until a time budget expires.
            for _ in range(40):
                try:
                    with duck.connect(settings.analytics_path) as conn:
                        duck.write_bars(
                            conn, settings.bars_dir, symbol, interval, self._frame(f"2026-01-{day:02d}")
                        )
                except BaseException as exc:
                    with lock:
                        write_errors.append(exc)
                else:
                    with lock:
                        writes_done += 1
                day = (day % 20) + 10

        def reader() -> None:
            while not stop.is_set():
                try:
                    with duck.connect(settings.analytics_path) as conn:
                        duck.read_bars(conn, settings.bars_dir, symbol, interval)
                except BaseException as exc:
                    with lock:
                        read_errors.append(exc)

        readers = [threading.Thread(target=reader) for _ in range(6)]
        writer_thread = threading.Thread(target=writer)

        for t in readers:
            t.start()
        writer_thread.start()
        writer_thread.join()
        stop.set()
        for t in readers:
            t.join()

        assert read_errors == []
        assert write_errors == [], (
            f"{len(write_errors)} of 40 writes raised while a reader ran concurrently: "
            f"{write_errors[:1]!r}"
        )
        assert writes_done == 40


class TestCrossStoreJoin:
    def test_duckdb_can_read_the_sqlite_ledger(
        self, settings: Settings, conn: sqlite3.Connection
    ) -> None:
        """The two-engine split only works if a single query can span both."""
        conn.execute(
            "INSERT INTO raw_import (import_id, source_path, filename, file_sha256, content_hash, "
            "broker, account_id, adapter, adapter_version, row_count, usable_row_count, imported_at) "
            "VALUES ('imp1','p','f','s','c','robinhood','rh-taxable','robinhood','1',1,1,'2026-01-01T00:00:00Z')"
        )
        ledger.insert_transactions(conn, [make_txn(txn_id="a", symbol="SOXL")])
        conn.commit()

        with duck.connect() as dconn:
            duck.attach_ledger(dconn, settings.ledger_path)
            rows = dconn.execute("SELECT symbol, quantity FROM ledger.txn").fetchall()
        assert rows == [("SOXL", "50")]


class TestPaths:
    def test_store_paths_derive_from_root(self, tmp_path: Path) -> None:
        cfg = Settings(repo_root=tmp_path, store_dir=tmp_path / "store")
        assert cfg.ledger_path == tmp_path / "store" / "ledger.sqlite"
        assert cfg.analytics_path == tmp_path / "store" / "analytics.duckdb"
        assert cfg.bars_dir == tmp_path / "store" / "bars"

    def test_ensure_dirs_is_repeatable(self, tmp_path: Path) -> None:
        cfg = Settings(repo_root=tmp_path, store_dir=tmp_path / "s", cache_dir=tmp_path / "c")
        cfg.ensure_dirs()
        cfg.ensure_dirs()
        assert cfg.bars_dir.is_dir()


class TestDotenvIsolation:
    """A `Settings` built inside a test must not see the repository's `.env`.

    `Settings.model_config["env_file"]` is an absolute path to the real repository root, so without
    the session-scoped `_detach_dotenv` fixture in `tests/conftest.py` every Settings object in the
    suite -- including the four dozen built by direct `Settings(...)` calls that no fixture touches
    -- inherits whatever the developer happens to have configured locally. That made a
    social-history test fail on one machine and pass everywhere else; see `_detach_dotenv` for the
    full account.

    Asserted against `model_config` rather than by writing a `.env` and checking a field, because
    `.env` is gitignored: a content-based test would be vacuously green on CI and on any fresh
    clone, which is precisely the failure mode being guarded against.
    """

    def test_settings_construction_is_detached_from_the_repo_dotenv(self) -> None:
        assert Settings.model_config["env_file"] is None

    def test_a_field_set_only_in_dotenv_falls_back_to_its_model_default(self) -> None:
        """The consequence of the line above, spelled out on the field that actually broke.

        `INVDASH_SOCIAL_SNAPSHOT_SCHEDULER_ENABLED=1` in `.env` is the documented way to start the
        Phase D-social clock, so this is the state a developer running that clock is really in.
        Skipped rather than asserted when the variable is exported in the shell: `_detach_dotenv`
        detaches the file and not the environment, on purpose.
        """
        import os

        if "INVDASH_SOCIAL_SNAPSHOT_SCHEDULER_ENABLED" in os.environ:
            pytest.skip("flag exported in the shell, which legitimately overrides the default")
        assert Settings().social_snapshot_scheduler_enabled is False


class TestSecretHandling:
    """The FRED key must not reach a log.

    Pydantic renders the whole settings object in pytest failure output and FastAPI tracebacks, so a
    plain ``str`` field would put the key into any captured log. This was observed happening before
    the field was changed to ``SecretStr``.
    """

    def test_key_is_masked_in_repr(self, tmp_path: Path) -> None:
        cfg = Settings(repo_root=tmp_path, fred_api_key="super-secret-value")  # type: ignore[arg-type]
        assert "super-secret-value" not in repr(cfg)
        assert "super-secret-value" not in str(cfg)

    def test_key_is_masked_when_serialised(self, tmp_path: Path) -> None:
        cfg = Settings(repo_root=tmp_path, fred_api_key="super-secret-value")  # type: ignore[arg-type]
        assert "super-secret-value" not in str(cfg.model_dump())

    def test_plaintext_available_at_the_call_site(self, tmp_path: Path) -> None:
        cfg = Settings(repo_root=tmp_path, fred_api_key="super-secret-value")  # type: ignore[arg-type]
        assert cfg.fred_key == "super-secret-value"

    def test_absent_key_is_none(self, tmp_path: Path) -> None:
        assert Settings(repo_root=tmp_path, fred_api_key=None).fred_key is None

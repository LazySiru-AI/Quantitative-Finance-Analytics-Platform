"""Verifies `connect()`'s busy timeout: a second writer that loses a lock race waits and then
succeeds, instead of `sqlite3.OperationalError: database is locked` surfacing straight through
to a caller (a 500, in the thesis holdout endpoint's case).

`test_second_writer_waits_then_succeeds` and `test_read_only_connection_reads_while_writer_holds_lock`
demonstrate the *mechanism* -- concurrent writers to a scratch table in a `tmp_path` database. They
do not reproduce the specific UAT report (`thesis-holdout-ledger-race-database-locked-500`), which
would require driving the thesis holdout endpoint against a real ledger; that was deliberately not
attempted here because it writes to `data/store/ledger.sqlite` permanently. `_make_db` never touches
that file -- every test builds its own database under `tmp_path`.

`test_without_busy_timeout_still_locks` is the control: it proves the other two tests are actually
exercising SQLite's write lock rather than passing regardless of contention, by reproducing the
pre-fix failure with a hand-built connection (`timeout=0`, no `busy_timeout` pragma) rather than by
adding a test-only parameter to `connect()`.

All timing below is intentionally loose. The lock is held for a fraction of a second and released
long before the (15s) busy timeout would ever be reached, and assertions only check that the second
writer's insert eventually landed -- not how long it waited. That said, this is still a real thread
handoff racing a real timer: on a sufficiently starved CI runner, `_JOIN_TIMEOUT_S` could in
principle be too tight. There is no way to make the *scheduling* fully deterministic without
mocking SQLite's lock manager, which would stop testing the real behaviour -- so this is flagged
here rather than shipped silently. It has not been observed to flake in local runs.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from app.db.sqlite import connect

#: How long connection A holds the write lock before committing. Small so the suite stays fast,
#: and far below the module's busy timeout so the waiting writer always has room to succeed.
_LOCK_HOLD_S = 0.2

#: Upper bound on how long we wait for the second writer's thread to finish. Generous relative to
#: `_LOCK_HOLD_S` (25x) so a loaded machine has headroom, but far below the module's busy timeout
#: so a real regression (the pragma silently not applying) fails this test instead of hanging it.
_JOIN_TIMEOUT_S = 5.0


def _make_db(path: Path) -> None:
    """A throwaway single-table database under `tmp_path` -- never the real ledger schema."""
    with connect(path) as conn:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT)")


def test_second_writer_waits_then_succeeds(tmp_path: Path) -> None:
    """A writer that arrives while another holds the write lock waits, rather than raising.

    This is the mechanism behind the UAT report: two requests that both want to write to the
    ledger at close to the same moment used to race, and the loser got `database is locked`
    surfaced as a 500 instead of simply going second.
    """
    db_path = tmp_path / "ledger.sqlite"
    _make_db(db_path)

    results: dict[str, object] = {}

    def second_writer() -> None:
        try:
            with connect(db_path) as conn:
                conn.execute("INSERT INTO t (value) VALUES ('from-thread')")
            results["ok"] = True
        except sqlite3.OperationalError as exc:
            results["ok"] = False
            results["error"] = str(exc)

    with connect(db_path) as first:
        first.execute("BEGIN IMMEDIATE")
        first.execute("INSERT INTO t (value) VALUES ('from-main')")

        thread = threading.Thread(target=second_writer)
        thread.start()
        time.sleep(_LOCK_HOLD_S)  # give the thread time to arrive and start waiting on the lock
        first.execute("COMMIT")

        thread.join(timeout=_JOIN_TIMEOUT_S)

    assert not thread.is_alive(), (
        "second writer never finished -- busy_timeout is not taking effect"
    )
    assert results.get("ok") is True, results.get("error")

    with connect(db_path, read_only=True) as check:
        rows = check.execute("SELECT value FROM t ORDER BY value").fetchall()
    assert [r["value"] for r in rows] == ["from-main", "from-thread"]


def test_without_busy_timeout_still_locks(tmp_path: Path) -> None:
    """Control: a writer with no busy timeout at all still raises immediately when locked out.

    Proves `test_second_writer_waits_then_succeeds` is exercising a real lock rather than passing
    vacuously. Built by hand with `sqlite3.connect` directly -- `connect()` itself gets no
    parameter to disable the fix just so this test can ask for it.
    """
    db_path = tmp_path / "ledger.sqlite"
    _make_db(db_path)

    with connect(db_path) as first:
        first.execute("BEGIN IMMEDIATE")
        first.execute("INSERT INTO t (value) VALUES ('from-main')")

        uri = f"file:{db_path.as_posix()}"
        no_wait = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=0)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                no_wait.execute("BEGIN IMMEDIATE")
        finally:
            no_wait.close()

        first.execute("COMMIT")


def test_read_only_connection_reads_while_writer_holds_lock(tmp_path: Path) -> None:
    """A reader is not blocked by a pending writer -- WAL still works with the pragma applied.

    `connect` only sets `busy_timeout` on writable connections (see its docstring: a `mode=ro`
    connection never takes a write lock, so there is nothing for it to wait for). This confirms
    that guard is intact and that a read-only connection still opens and reads cleanly while
    another connection holds the write lock -- i.e. that the fix didn't turn a reader into a
    writer by accident.
    """
    db_path = tmp_path / "ledger.sqlite"
    _make_db(db_path)
    with connect(db_path) as setup:
        setup.execute("INSERT INTO t (value) VALUES ('seed')")

    with connect(db_path) as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO t (value) VALUES ('uncommitted')")

        with connect(db_path, read_only=True) as reader:
            rows = reader.execute("SELECT value FROM t ORDER BY value").fetchall()

        writer.execute("COMMIT")

    assert [r["value"] for r in rows] == ["seed"]

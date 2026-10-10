"""DuckDB analytics store: OHLCV bars on Parquet, plus cross-store joins into the SQLite ledger.

Two engines rather than one, because the workloads differ. The ledger is small, append-heavy and
transactional, and it is written by the API process while a scheduled fetch job runs -- SQLite handles
that concurrency. Bars are millions of rows scanned columnar, which is DuckDB's job and not SQLite's.

DuckDB attaches the SQLite file directly, so "which of my holdings closed below their 20-day low"
remains a single query across both stores.

Bars are partitioned on disk as::

    data/store/bars/interval=<1d|4h|1h|30m|15m|5m>/symbol=<SYMBOL>/bars.parquet

Partitioning by interval before symbol matters: almost every query fixes the interval and scans many
symbols, so this ordering lets DuckDB prune the majority of files before opening any.

``1w`` is absent from that list on purpose: weekly bars are resampled from stored daily bars on
read (:func:`app.market.store.read_series`) rather than fetched and persisted. Storing both would
create two representations of the same week that drift apart the moment a daily bar is corrected.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import duckdb

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

__all__ = [
    "Interval",
    "attach_ledger",
    "bar_path",
    "connect",
    "read_bars",
    "stored_symbols",
    "write_bars",
]


class Interval(StrEnum):
    """Bar intervals the application stores.

    Retention is dictated by what Yahoo actually serves, not by preference -- verified by a live
    probe against ``/v8/finance/chart/{symbol}`` (2026-08-25), not inferred from documentation:

    ==========  ===================  ================================================
    Interval    Available history    Use
    ==========  ===================  ================================================
    ``1w``      unbounded            charts; derived locally from daily
    ``1d``      unbounded            charts; backtests
    ``4h``      730 days             charts
    ``1h``      730 days             charts
    ``30m``     60 days              charts
    ``15m``     60 days              charts
    ``5m``      60 days              charts
    ==========  ===================  ================================================

    Daily and weekly are the only intervals with enough history for a multi-year statistical claim
    (see :attr:`backtestable`); every intraday interval, ``4h`` included, is retention-limited to a
    window (60 or 730 days) too short to support one. That is a statement about sample size, not a
    ban -- nothing stops a shorter-window study from reading intraday bars, it just cannot claim to
    speak for years it never saw.
    """

    FIVE_MIN = "5m"
    FIFTEEN_MIN = "15m"
    THIRTY_MIN = "30m"
    HOUR = "1h"
    FOUR_HOUR = "4h"
    DAY = "1d"
    WEEK = "1w"

    @property
    def is_intraday(self) -> bool:
        """Whether bars for this interval carry a true intraday timestamp rather than a session date.

        ``4h`` is included: it is sub-daily, shares the 730-day retention ceiling with ``1h``, and its
        bars are stamped with a real instant (not a session date) exactly like the other intraday
        members -- see ``YahooProvider._to_frame``, which only special-cases ``DAY``/``WEEK``.
        """
        return self in (Interval.FIVE_MIN, Interval.FIFTEEN_MIN, Interval.THIRTY_MIN, Interval.HOUR, Interval.FOUR_HOUR)

    @property
    def backtestable(self) -> bool:
        """Whether a statistical study may be run on this interval.

        Currently true only for ``DAY`` and ``WEEK``. Note this property is not read by any
        application code today -- it is asserted only by a self-referential test
        (``tests/test_stores.py::TestBarStore::test_only_daily_and_weekly_are_backtestable``) that
        checks the property against itself. Its behaviour is unchanged here; only this docstring,
        which previously overstated the property as an enforced restriction, has been corrected.
        """
        return self in (Interval.DAY, Interval.WEEK)


#: Columns every bar table carries. ``ts`` is tz-aware UTC -- for daily bars it is the exchange-local
#: session date at midnight UTC, not the provider's raw open timestamp. See
#: :func:`app.market.models.session_date` for why that distinction is not cosmetic.
#:
#: ``adj_close`` is split- *and* dividend-adjusted; the OHLC columns are split-adjusted only, which
#: is what the provider serves. Both are stored because they answer different questions: price-return
#: studies and chart overlays want ``close``, total-return studies want ``adj_close``, and a dataset
#: holding only one of them cannot be made to yield the other after the fact. It is ``NaN`` on
#: intraday intervals, where no provider supplies an adjusted series.
BAR_COLUMNS = ("ts", "open", "high", "low", "close", "adj_close", "volume")


@contextmanager
def connect(database: Path | None = None, *, read_only: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open a DuckDB connection. ``None`` gives an in-memory database, which is what tests use.

    **Choosing ``database`` and ``read_only`` together is a real decision, not two independent
    flags** -- three modes, three different purposes:

    * ``database=None`` (in-memory): no physical file is touched at all, so there is nothing to
      collide with another process over and nothing that can fail to exist. Right whenever the
      caller only needs the connection as a SQL engine over paths it supplies itself --
      :func:`read_bars` and :func:`write_bars` both work this way, driving ``read_parquet`` /
      ``COPY ... TO`` against an explicit file path rather than anything persisted in the DuckDB
      catalog. Every pure-read caller in :mod:`app.market.store` (``read_frame``, ``_read_many``,
      and ``sync_bars``'s own incremental-start read) uses this, matching
      :func:`app.tournament.roster.tradeable_universe`'s "a read path has no business creating it".
    * ``database=<path>, read_only=False`` (the default): the only mode that may create or modify
      the physical file, and the only one two processes cannot share -- DuckDB permits exactly one
      writer. Use it only where a write (or catalog-level mutation) is actually intended, such as
      :func:`app.market.store.sync_bars`'s merge-and-persist step.
    * ``database=<path>, read_only=True``: opens the real on-disk file without taking the writer
      slot. **Verified concurrent-safe** -- any number of ``read_only=True`` connections may share
      one store at once; it is only the default read-write mode that collides. This is what
      ``strategy-program/tools/windows.py`` and other ad hoc research scripts use when they
      specifically need to inspect the persisted file rather than read through
      :mod:`app.market.store`'s API. It still requires the file to already exist -- DuckDB cannot
      open a nonexistent database ``read_only`` -- so it is the wrong choice for a caller that must
      also tolerate a fresh, never-synced store; prefer in-memory for that case instead.

    Defaulting to read-write cost this project real work three times over (a prior study lost four
    symbols, one tournament round lost a card, another lost 135 card-runs across five windows to
    the exact same ``IOException`` -- see ``strategy-program/DEFECTS.md`` D3) before
    ``app.market.store``'s pure reads were moved off the physical file entirely rather than merely
    flipping to ``read_only=True`` against it.

    The connection timezone is pinned to UTC, and that is not a preference. DuckDB stores a
    ``TIMESTAMP WITH TIME ZONE`` as an instant and re-labels it with the *connection's* timezone on
    the way out, which defaults to the host's. So a bar written as ``2026-01-09T00:00Z`` came back
    as ``2026-01-08T18:00-06:00`` on a machine in US Central -- the same instant, correctly, but a
    different calendar day the moment anything called ``.date()`` on it.

    That is precisely the failure :func:`app.market.models.session_date` exists to prevent, arriving
    through the storage layer instead of the provider. It would shift every daily bar's session date
    by one day for any user west of UTC, put weekly bars in the wrong ISO week, and misalign bars
    against the ledger's trade dates -- all without an error, and all invisible on a UTC developer
    machine. Pinning it here means the round trip is identity for every caller rather than something
    each one has to remember to undo.
    """
    if database is not None:
        database.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(database) if database else ":memory:", read_only=read_only)
    try:
        conn.execute("SET TimeZone='UTC'")
        yield conn
    finally:
        conn.close()


def attach_ledger(conn: duckdb.DuckDBPyConnection, ledger_path: Path, *, alias: str = "ledger") -> None:
    """Attach the SQLite ledger read-only so bars and transactions can be joined in one query.

    Read-only is deliberate: the ledger has exactly one writer, the ingestion path. Analytics reads it
    and never writes it.
    """
    conn.execute("INSTALL sqlite")
    conn.execute("LOAD sqlite")
    # DuckDB's ATTACH does not accept bound parameters, so the path is inlined. Single quotes are
    # doubled to close the only injection route, and the alias is a caller-controlled literal.
    if not alias.isidentifier():
        raise ValueError(f"attach alias must be an identifier, got {alias!r}")
    literal = str(ledger_path).replace("'", "''")
    conn.execute(f"ATTACH '{literal}' AS {alias} (TYPE sqlite, READ_ONLY)")


def bar_path(bars_dir: Path, symbol: str, interval: Interval) -> Path:
    """Parquet location for one symbol at one interval."""
    safe = symbol.upper().replace("/", "_").replace("\\", "_")
    return bars_dir / f"interval={interval.value}" / f"symbol={safe}" / "bars.parquet"


#: One lock per target Parquet file, held by writers *and* readers, so nothing touches a partition
#: while another thread is mid-merge or mid-scan of it. FastAPI runs synchronous endpoints in a
#: threadpool, so two requests for the same symbol and interval genuinely do land here at once --
#: which is not a hypothetical: switching to the four-timeframe view fires four syncs in the same
#: breath, each racing whatever chart is simultaneously reading the same partition.
#:
#: Readers need this too, not just other writers. DuckDB's ``read_parquet`` scan does not release its
#: handle on the file the instant the query returns -- measured empirically, it outlives the query
#: *and* the connection's own ``close()``, because the scan is served through a buffer-manager cache
#: that is not scoped to one connection. On Windows, ``Path.replace()`` (see `_merge_and_write`)
#: refuses to replace a file with any open handle in the process, so an unlocked reader turns the
#: writer's supposedly-atomic replace into an unhandled ``PermissionError`` -- 62 of 96 (65%)
#: concurrent writes failed this way in testing, with a single writer and zero writer-vs-writer
#: contention. Read volume against any one partition is low, so folding reads into the same exclusive
#: lock costs little and is simpler than a read/write lock.
_WRITE_LOCKS: dict[Path, threading.Lock] = {}
_LOCK_REGISTRY = threading.Lock()


def _write_lock(target: Path) -> threading.Lock:
    """The lock guarding ``target``, shared by `write_bars` and `read_bars` -- see `_WRITE_LOCKS`."""
    with _LOCK_REGISTRY:
        return _WRITE_LOCKS.setdefault(target, threading.Lock())


def write_bars(
    conn: duckdb.DuckDBPyConnection,
    bars_dir: Path,
    symbol: str,
    interval: Interval,
    frame: pd.DataFrame,
) -> int:
    """Write or merge bars for one symbol, de-duplicating on timestamp.

    Fetches overlap by design -- an incremental daily pull re-requests the last few sessions to catch
    late corrections. Existing rows are merged with incoming ones and the *incoming* value wins on a
    timestamp collision, so a corrected bar replaces the stale one rather than being discarded.

    Read-merge-write is serialised per target file -- against other writers *and* against
    `read_bars` on the same target, see `_WRITE_LOCKS` -- and staged through a *uniquely named* temp
    file. All three matter, for different reasons. A shared staging name makes two concurrent writers
    fight over one path -- on Windows that is a hard ``IOException`` ("the process cannot access the
    file because it is being used by another process"), and on POSIX it is worse, because the rename
    silently succeeds and one writer's output replaces the other's. The lock is what makes the merge
    itself atomic: without it both writers read the same "before" state and the later rename discards
    whatever the earlier one had added. And without the lock also covering readers, a concurrent
    `read_bars` holding an open handle on `target` makes the *same-thread-safe* rename above fail on
    Windows regardless of writer-vs-writer contention -- see `_WRITE_LOCKS` for the measurement.

    In-process only. A second *process* writing (or reading) the same partition -- the scheduled fetch
    job the plan contemplates -- would still race, and would need a file lock.

    Returns the total row count on disk after the merge.
    """
    missing = [c for c in BAR_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"bar frame for {symbol} {interval} is missing columns: {missing}")

    target = bar_path(bars_dir, symbol, interval)
    target.parent.mkdir(parents=True, exist_ok=True)

    with _write_lock(target):
        return _merge_and_write(conn, target, frame)


def _merge_and_write(
    conn: duckdb.DuckDBPyConnection, target: Path, frame: pd.DataFrame
) -> int:
    cols = ", ".join(BAR_COLUMNS)
    conn.register("incoming", frame[list(BAR_COLUMNS)])
    try:
        if target.exists():
            conn.execute(
                f"""
                CREATE OR REPLACE TEMP TABLE merged AS
                SELECT {cols} FROM (
                    SELECT *, ROW_NUMBER() OVER (PARTITION BY ts ORDER BY src) AS rn
                    FROM (
                        SELECT {cols}, 0 AS src FROM incoming
                        UNION ALL
                        SELECT {cols}, 1 AS src
                        FROM read_parquet(?)
                    )
                ) WHERE rn = 1
                ORDER BY ts
                """,
                [str(target)],
            )
        else:
            conn.execute(
                f"CREATE OR REPLACE TEMP TABLE merged AS SELECT {cols} FROM incoming ORDER BY ts"
            )

        # Write via a sibling temp file then replace, so an interrupted write cannot leave a
        # truncated Parquet behind where valid history used to be. The name carries a uuid because
        # a fixed one is a shared mutable path between concurrent writers -- see `write_bars`.
        staging = target.with_name(f"{target.name}.{uuid4().hex}.tmp")
        try:
            conn.execute("COPY merged TO ? (FORMAT parquet)", [str(staging)])
            _replace_with_retry(staging, target)
        finally:
            # A crash between COPY and replace would otherwise leave the partition directory
            # accumulating orphaned staging files that nothing ever collects.
            staging.unlink(missing_ok=True)
        count = conn.execute("SELECT COUNT(*) FROM merged").fetchone()
        return int(count[0]) if count else 0
    finally:
        conn.unregister("incoming")


#: Attempts and backoff for the atomic replace. Five tries over ~310ms total.
#:
#: `_write_lock` covers the common case -- a reader mid-scan while a writer replaces underneath it --
#: but it cannot cover all of it, and the reason is recorded on `_WRITE_LOCKS`: DuckDB's handle on a
#: scanned Parquet outlives both the query and the connection's own `close()`, because the scan is
#: served from a buffer-manager cache that is not scoped to a connection. The lock is released when
#: `read_bars` returns; the handle is not necessarily gone at that moment. So a writer taking the
#: lock immediately afterwards can still meet an open handle, and on Windows `Path.replace` refuses
#: to replace a file that has one, raising `PermissionError(13)`.
#:
#: That residual race is what remained after the lock was added. It is far rarer -- the original
#: unlocked failure rate was 62 of 96 writes (65%); this surfaced once in a full-suite run and not
#: once in eight consecutive isolated runs -- but "rare" here means a user's background bar sync
#: crashes rather than a chart being briefly stale, so it is worth closing. A bounded retry is the
#: standard mitigation for this on Windows and costs nothing on POSIX, where a rename over an open
#: file succeeds and the first attempt always wins.
#:
#: Deliberately bounded rather than indefinite: a handle that is still open after a third of a
#: second is not a transient scan, it is a leak, and the `PermissionError` is then the correct and
#: useful outcome rather than a hang.
_REPLACE_ATTEMPTS = 5
_REPLACE_BACKOFF_SECONDS = 0.02


def _replace_with_retry(staging: Path, target: Path) -> None:
    """`staging.replace(target)`, retrying a `PermissionError` a bounded number of times.

    See `_REPLACE_ATTEMPTS` for why the lock alone does not make this safe on Windows. The final
    attempt is allowed to raise: exhausting the budget means the handle is not transient.
    """
    delay = _REPLACE_BACKOFF_SECONDS
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            staging.replace(target)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(delay)
            delay *= 2


def read_bars(
    conn: duckdb.DuckDBPyConnection,
    bars_dir: Path,
    symbol: str,
    interval: Interval,
    *,
    start: dt.datetime | dt.date | None = None,
    end: dt.datetime | dt.date | None = None,
) -> pd.DataFrame:
    """Read stored bars for one symbol, optionally bounded by time.

    Returns an empty frame with the right columns when nothing is stored, so callers can treat "no
    data yet" as an ordinary case rather than an exception.

    Takes the same per-target lock :func:`write_bars` does. DuckDB's Parquet reader does not release
    its handle on ``target`` the instant the query returns -- the scan is backed by an mmap that
    outlives both the ``SELECT`` and, empirically, the connection's own ``close()``, because
    ``read_parquet`` results are served from a buffer-manager cache that is not scoped to one
    connection or one query. On Windows, ``Path.replace()`` (see :func:`_merge_and_write`) refuses to
    replace a file that still has an open handle anywhere in the process, so an unguarded reader
    racing a writer turns the writer's supposedly-atomic replace into an unhandled
    ``PermissionError`` -- measured at 62 of 96 concurrent writes (65%) failing with a single writer
    and no writer-vs-writer contention at all. Serialising reads behind the writer's lock closes that
    window; read volume against any one partition is low enough that this is not a throughput
    concern.
    """
    target = bar_path(bars_dir, symbol, interval)
    if not target.exists():
        import pandas as pd

        return pd.DataFrame(columns=list(BAR_COLUMNS))

    clauses: list[str] = []
    params: list[object] = [str(target)]
    if start is not None:
        clauses.append("ts >= ?")
        params.append(start)
    if end is not None:
        clauses.append("ts <= ?")
        params.append(end)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _write_lock(target):
        return conn.execute(
            f"SELECT {', '.join(BAR_COLUMNS)} FROM read_parquet(?) {where} ORDER BY ts",
            params,
        ).df()


def stored_symbols(bars_dir: Path, interval: Interval) -> list[str]:
    """Symbols with stored bars at the given interval."""
    root = bars_dir / f"interval={interval.value}"
    if not root.exists():
        return []
    return sorted(
        p.name.removeprefix("symbol=")
        for p in root.iterdir()
        if p.is_dir() and p.name.startswith("symbol=")
    )

"""Durable, append-only store of :class:`~app.market.news_models.SocialSnapshot` observations.

**Why this module exists at all.** Every free social endpoint serves only a live window --
StockTwits returns the current tail of a symbol's stream, and there is no historical query. That is
why :class:`app.market.providers.base.SocialProvider` carries no ``as_of`` parameter: a provider
offering a bound it cannot honour would let a caller ask for 2019 and silently receive today's
messages. So there is no social *series* to read until one is built forward, one snapshot at a time,
from here. See ``strategy-program/AGENTS-INTEGRATION-PLAN.md`` Phase D for the argument in full --
this module is the prerequisite it names, not the study itself. Nothing in this file runs a study,
computes a return, or looks at price data at all.

**The scheduler at the bottom of this file is inert unless explicitly turned on.**
:func:`record_snapshot` itself is still a pure library call: give it a connection and a
:class:`SocialSnapshot`, it appends or discovers a duplicate, nothing more. :func:`start_scheduler`
is the thing Phase D-social's plan named as the missing piece -- "needs a snapshot table written on a
schedule, and time to pass" -- a daemon thread that fetches a live snapshot per watched symbol, calls
:func:`record_snapshot`, sleeps, and repeats for as long as the process runs. It has no import-time
side effect: `Settings.social_snapshot_scheduler_enabled` defaults to `False` (see that field's own
docstring for why this, unlike `Settings.refresh_on_startup`, cannot default `True`), and
`app.main.lifespan` -- the one production caller -- only calls :func:`start_scheduler` when that flag
is on. Importing this module, or calling :func:`start_scheduler` with the class default, starts no
thread and opens no socket.

Five design rules carry the whole module, and each is a direct answer to a way this kind of store
goes wrong silently:

1. **Append-only.** Rows are inserted, never updated. ``record_snapshot`` either inserts a new row
   or discovers a duplicate and inserts nothing -- there is no code path that rewrites a stored row's
   counts. A store that can be edited after the fact is not a historical record, it is a cache with
   a start date on the cache.

2. **Counts, not ratios.** The table has ``bullish``/``bearish``/``neutral`` columns and no
   ``ratio``/``score`` column. Per :mod:`app.market.news_models`'s governing rule, "100% bullish"
   over 6 labelled messages out of 20 is true, useless and confidently misleading without its
   denominator beside it -- and persisting a ratio here would let that defect leak into whatever a
   future study reads back as fact, permanently, because the count that would have revealed it was
   never stored. :func:`read_range` returns the stored counts as a real :class:`SocialSnapshot`;
   :class:`app.market.news_models.SocialSummary.of` is where a ratio gets computed, on every read,
   from the counts that are actually there.

3. **Provenance per row.** ``source`` names the provider. ``observed_at`` is the provider's own
   timestamp for the snapshot (:attr:`SocialSnapshot.as_of`) and ``recorded_at`` is when *this
   process* wrote the row -- kept as two separate columns because a future backtest needs to know
   when the information was available to have acted on, not when this store happened to persist it.
   They usually sit a few milliseconds apart (the caller fetches, then calls
   :func:`record_snapshot` immediately), but collapsing them into one column would make that
   assumption load-bearing instead of incidental.

4. **No bound the store cannot honour.** :func:`read_range` takes ``start``/``end`` the same shape
   an ``as_of`` would take, and that is exactly the trap named in the module docstring above if it
   is not handled carefully: a caller who asks for 2019 must not get back an *empty, silent* answer
   that reads the same as "nothing happened in 2019" when the true answer is "this store did not
   exist yet." So every :class:`SocialHistoryRange` carries ``coverage_start`` -- the earliest
   ``observed_at`` this store actually holds for the query's symbol/source, independent of what the
   caller asked for -- and ``requested_start_before_coverage``, computed for the caller rather than
   left as an exercise. The distinction from a provider's ``as_of`` is real, not cosmetic: this
   queries rows that are already on disk, so a bound outside the stored range is honestly answered
   as "no rows, and here is where coverage actually begins" rather than silently proxied to a live
   endpoint that would answer for *today* and call it 2019.

5. **Idempotent-ish writes.** "The scheduler fired twice in the same minute" must not produce two
   rows that both claim to be an independent observation of a changing quantity. See
   :func:`_recorded_minute` for the dedupe rule and why it buckets on *write* time rather than on
   the provider's ``as_of``.

**Storage.** A dedicated SQLite database at :func:`default_db_path` (``<store_dir>/social_history
.sqlite``), not the ledger database in :mod:`app.db.sqlite` and not the DuckDB bar store in
:mod:`app.db.duck`. Both of those are wrong homes for this: the ledger's schema is a different
domain entirely (broker transactions, accounts, tax lots), and the bar store's Parquet-partition
design exists for OHLCV series with a fixed, wide schema and no per-row provenance -- see
:mod:`app.market.store`'s module docstring on why ``1w`` bars are resampled rather than stored
twice, which is the same "one representation, not two that can drift" argument this module makes
about ratios. A handful of counts per snapshot, arriving at low frequency with a dedupe rule that
needs a unique index, is squarely SQLite's shape. The schema-versioning pattern below (a
``schema_version`` table, an idempotent ``CREATE TABLE IF NOT EXISTS`` script run on every startup)
mirrors :func:`app.db.sqlite.migrate` deliberately, so a reader who already knows that module
recognises this one.
"""

from __future__ import annotations

import datetime as dt
import logging
import sqlite3
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from app.core.ids import stable_id
from app.market import macro
from app.market.news_models import SocialSnapshot
from app.market.registry import ProviderRegistry, default_registry

if TYPE_CHECKING:
    from app.config import Settings

__all__ = [
    "SCHEMA_VERSION",
    "SocialHistoryRange",
    "SocialSchedulerStatus",
    "StoredSocialSnapshot",
    "WriteResult",
    "connect",
    "default_db_path",
    "migrate",
    "read_range",
    "record_snapshot",
    "run_scheduler_pass",
    "start_scheduler",
    "status",
]

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_BUSY_TIMEOUT_MS = 15_000
"""Same value and same reasoning as `app.db.sqlite._BUSY_TIMEOUT_MS`: this is a local, single-user
application, so the only writer a write can ever contend with is another request the same person
just made (a second tab, a scheduler tick racing a manual refresh). 15s is comfortably longer than
any write this module does."""

_DEDUPE_BUCKET = dt.timedelta(minutes=1)
"""The width of the write-time window within which two writes for the same (symbol, source) collapse
into one row. A minute, not a second or an hour, because it matches the concrete failure this rule
exists to prevent -- "the scheduler fired twice" -- without being so wide that it would also
suppress a second, genuinely-intended snapshot taken minutes apart during manual testing."""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

-- Append-only. No code path in this module executes an UPDATE against this table -- see the module
-- docstring, rule 1. `row_id` is a deterministic hash of the dedupe key (symbol, source, the
-- write-time minute bucket), so a second write within the same bucket collides on the primary key
-- and `INSERT OR IGNORE` makes it a no-op rather than a second row -- see `record_snapshot`.
CREATE TABLE IF NOT EXISTS social_snapshot (
    row_id          TEXT PRIMARY KEY,
    symbol          TEXT NOT NULL,
    source          TEXT NOT NULL,
    -- The provider's own timestamp for the snapshot (`SocialSnapshot.as_of`), timezone-aware UTC
    -- ISO-8601 text. This is when the information was available, which a backtest needs to know.
    observed_at     TEXT NOT NULL,
    -- Oldest message the snapshot covers, when the upstream lets us know (`SocialSnapshot.
    -- window_start`). Nullable: the upstream frequently does not say.
    window_start    TEXT,
    -- When this process wrote the row -- distinct from `observed_at` by design, see rule 3 in the
    -- module docstring. Never used to order a series; `observed_at` is.
    recorded_at     TEXT NOT NULL,
    bullish         INTEGER NOT NULL,
    bearish         INTEGER NOT NULL,
    neutral         INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_social_snapshot_symbol_source_observed
    ON social_snapshot (symbol, source, observed_at);
"""


def default_db_path(settings: Settings | None = None) -> Path:
    """``<store_dir>/social_history.sqlite`` -- imported lazily to avoid a hard dependency on
    `app.config` for callers (tests included) that only want to pass an explicit path to
    `connect`."""
    from app.config import get_settings

    cfg = settings or get_settings()
    return cfg.store_dir / "social_history.sqlite"


@contextmanager
def connect(path: Path, *, read_only: bool = False) -> Iterator[sqlite3.Connection]:
    """Open the store with the pragmas its writes depend on, migrating a fresh or older database.

    Mirrors `app.db.sqlite.connect`: WAL for concurrent readers, `foreign_keys` on (unused by this
    single-table schema today, but the pragma costs nothing and keeps this connection's behaviour
    consistent with every other one in the app), and a busy timeout long enough that a second writer
    waits rather than raising `sqlite3.OperationalError: database is locked` for what is really a
    transient condition. Migration runs on every non-read-only open -- see `migrate` -- which is safe
    to do unconditionally because the schema script is idempotent.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    uri = f"file:{path.as_posix()}{'?mode=ro' if read_only else ''}"
    conn = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=_BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        if not read_only:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
            migrate(conn)
        yield conn
    finally:
        conn.close()


def migrate(conn: sqlite3.Connection) -> int:
    """Apply the schema if absent. Returns the resulting schema version.

    `executescript` runs the `CREATE TABLE IF NOT EXISTS` script unconditionally and safely on every
    startup, matching `app.db.sqlite.migrate`. There is exactly one schema version today, so unlike
    that module there is no in-place `_migrate_*` step yet -- when a column needs to be added to an
    existing table, it belongs here as its own guarded step, following that module's pattern, rather
    than as a change to the `CREATE TABLE` above (which `IF NOT EXISTS` would then silently skip on
    every database that already has the table).
    """
    conn.executescript(_SCHEMA)
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    current = int(row["v"]) if row is not None and row["v"] is not None else 0
    if current < SCHEMA_VERSION:
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, dt.datetime.now(dt.UTC).isoformat()),
        )
        return SCHEMA_VERSION
    return current


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WriteResult:
    """Outcome of one `record_snapshot` call."""

    inserted: bool
    """`False` means a write within the same dedupe bucket already existed and nothing new was
    written -- not an error, the expected result of a scheduler firing twice."""
    row_id: str
    recorded_at: dt.datetime
    """The `recorded_at` actually stored for this dedupe bucket: the value just written when
    `inserted` is `True`, or the value from the prior write when it is `False`."""


def _require_aware(value: dt.datetime, *, field: str) -> dt.datetime:
    if value.tzinfo is None:
        raise ValueError(
            f"{field} must be timezone-aware: a naive value cannot be safely normalised to UTC, "
            "and assuming local time would shift stored history by the caller's own offset."
        )
    return value.astimezone(dt.UTC)


def _recorded_minute(recorded_at: dt.datetime) -> str:
    """Floor `recorded_at` to the start of its minute, as UTC ISO-8601 text.

    This -- not `SocialSnapshot.as_of` -- is what `record_snapshot` dedupes on. `as_of` is the
    provider's own clock, and StockTwits' `fetch_social` sets it to `datetime.now(UTC)` at fetch
    time (see `app.market.providers.stocktwits`), so in practice the two are close together, but the
    dedupe rule should not be *load-bearing* on a provider's timestamp discipline -- a provider that
    reported a slightly-stale `as_of` must not thereby produce a second "independent" row for a
    write that happened in the same scheduler tick. Bucketing the value this module itself stamps at
    write time keeps the rule under this module's control.
    """
    floored = recorded_at.replace(second=0, microsecond=0)
    return floored.isoformat()


def record_snapshot(
    conn: sqlite3.Connection,
    snapshot: SocialSnapshot,
    *,
    now: dt.datetime | None = None,
) -> WriteResult:
    """Append one snapshot, or discover it is a duplicate of one already written this minute.

    `now` is the write-time instant this call uses for `recorded_at` and the dedupe bucket -- it
    defaults to the real clock and exists as a parameter so tests can control bucket boundaries
    deterministically instead of racing `datetime.now`. Passed explicitly by two calls that land in
    the same minute, they collapse into one row; passed with `now` a minute or more apart, both are
    kept, because at that point they are two genuinely different observations of a stream that
    changes constantly.

    Never updates a row that already exists -- see the module docstring, rule 1. `INSERT OR IGNORE`
    makes the "already there" case a true no-op at the SQL level rather than a read-then-maybe-write
    race, matching `app.db.sqlite`'s own idempotent-insert style (see its
    `_migrate_symbol_alias_backfill`).
    """
    recorded_at = _require_aware(now or dt.datetime.now(dt.UTC), field="now")
    recorded_minute = _recorded_minute(recorded_at)
    symbol = snapshot.symbol.upper()
    row_id = stable_id(symbol, snapshot.source, recorded_minute, length=32)

    observed_at = _require_aware(snapshot.as_of, field="snapshot.as_of")
    window_start = (
        _require_aware(snapshot.window_start, field="snapshot.window_start")
        if snapshot.window_start is not None
        else None
    )

    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO social_snapshot (
            row_id, symbol, source, observed_at, window_start, recorded_at,
            bullish, bearish, neutral
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row_id,
            symbol,
            snapshot.source,
            observed_at.isoformat(),
            window_start.isoformat() if window_start is not None else None,
            recorded_at.isoformat(),
            snapshot.bullish,
            snapshot.bearish,
            snapshot.neutral,
        ),
    )
    if cursor.rowcount == 1:
        return WriteResult(inserted=True, row_id=row_id, recorded_at=recorded_at)

    # Deduped: report the recorded_at of the row that already occupies this bucket, rather than the
    # value this call would have written, so a caller inspecting WriteResult sees the truth of what
    # is actually stored.
    existing = conn.execute(
        "SELECT recorded_at FROM social_snapshot WHERE row_id = ?", (row_id,)
    ).fetchone()
    existing_recorded_at = dt.datetime.fromisoformat(existing["recorded_at"])
    return WriteResult(inserted=False, row_id=row_id, recorded_at=existing_recorded_at)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StoredSocialSnapshot:
    """One stored row, reconstructed as the same `SocialSnapshot` a provider would hand back, plus
    the write-time provenance the live model has no field for."""

    snapshot: SocialSnapshot
    recorded_at: dt.datetime
    row_id: str


@dataclass(frozen=True, slots=True)
class SocialHistoryRange:
    """The answer to a range query -- the rows, and enough about the store's own coverage that the
    caller cannot mistake "no rows in range" for "nothing happened."""

    symbol: str
    source: str | None
    rows: tuple[StoredSocialSnapshot, ...]
    """Ordered oldest to newest by `observed_at` -- the instant a study cares about, not
    `recorded_at`."""
    coverage_start: dt.datetime | None
    """The earliest `observed_at` this store holds for `symbol` (and `source`, if given),
    irrespective of what `start` was requested. `None` only when the store holds nothing at all for
    this symbol/source -- not when `rows` happens to be empty because the requested window missed
    everything that is there."""
    requested_start: dt.datetime | None

    @property
    def requested_start_before_coverage(self) -> bool:
        """`True` when the caller asked for history from before this store began recording.

        This is the guard named in the module docstring's rule 4: a caller who reads this as `False`
        (or sees `coverage_start` sitting later than `requested_start`) has an explicit signal that
        an empty or short `rows` is a coverage gap, not a report of "nothing happened" -- the
        distinction an `as_of` this store could not honour would otherwise hide.
        """
        return (
            self.requested_start is not None
            and self.coverage_start is not None
            and self.requested_start < self.coverage_start
        )


def read_range(
    conn: sqlite3.Connection,
    symbol: str,
    *,
    source: str | None = None,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
) -> SocialHistoryRange:
    """The stored series for `symbol`, ordered oldest to newest by `observed_at`.

    `start`/`end` bound rows already on disk -- they are not an `as_of` passed to a live provider,
    and this function never contacts one. See the module docstring's rule 4 for why that distinction
    matters: a bound outside what this store has accumulated is answered honestly, via
    `SocialHistoryRange.coverage_start` and `.requested_start_before_coverage`, rather than silently
    producing an empty result indistinguishable from "nothing happened."

    `source=None` reads every provider's rows for `symbol` together, oldest to newest by
    `observed_at` across providers -- useful for "everything this store has seen about AAPL." Narrow
    to one provider's series with `source=` when comparing like with like.
    """
    upper = symbol.upper()
    start_utc = _require_aware(start, field="start") if start is not None else None
    end_utc = _require_aware(end, field="end") if end is not None else None

    coverage_start = _coverage_start(conn, upper, source)

    clauses = ["symbol = ?"]
    params: list[object] = [upper]
    if source is not None:
        clauses.append("source = ?")
        params.append(source)
    if start_utc is not None:
        clauses.append("observed_at >= ?")
        params.append(start_utc.isoformat())
    if end_utc is not None:
        clauses.append("observed_at <= ?")
        params.append(end_utc.isoformat())

    where = " AND ".join(clauses)
    query_rows = conn.execute(
        f"SELECT * FROM social_snapshot WHERE {where} ORDER BY observed_at ASC, row_id ASC",
        params,
    ).fetchall()

    rows = tuple(_row_to_stored(row) for row in query_rows)
    return SocialHistoryRange(
        symbol=upper,
        source=source,
        rows=rows,
        coverage_start=coverage_start,
        requested_start=start_utc,
    )


def _coverage_start(
    conn: sqlite3.Connection, symbol: str, source: str | None
) -> dt.datetime | None:
    """The earliest `observed_at` stored for `symbol` (and `source`, if given).

    Computed unconditionally on every `read_range` call -- deliberately not limited by the caller's
    own `start`/`end`, since the whole point is to answer relative to what the *store* holds, not
    relative to what was asked for.
    """
    if source is not None:
        row = conn.execute(
            "SELECT MIN(observed_at) AS earliest FROM social_snapshot WHERE symbol = ? AND source = ?",
            (symbol, source),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT MIN(observed_at) AS earliest FROM social_snapshot WHERE symbol = ?",
            (symbol,),
        ).fetchone()
    earliest = row["earliest"] if row is not None else None
    return dt.datetime.fromisoformat(earliest) if earliest is not None else None


def _row_to_stored(row: sqlite3.Row) -> StoredSocialSnapshot:
    snapshot = SocialSnapshot(
        symbol=row["symbol"],
        source=row["source"],
        as_of=dt.datetime.fromisoformat(row["observed_at"]),
        window_start=(
            dt.datetime.fromisoformat(row["window_start"])
            if row["window_start"] is not None
            else None
        ),
        bullish=int(row["bullish"]),
        bearish=int(row["bearish"]),
        neutral=int(row["neutral"]),
    )
    return StoredSocialSnapshot(
        snapshot=snapshot,
        recorded_at=dt.datetime.fromisoformat(row["recorded_at"]),
        row_id=row["row_id"],
    )


# ---------------------------------------------------------------------------
# Scheduling -- Phase D-social's clock
# ---------------------------------------------------------------------------

#: The symbols a scheduled snapshot is taken for. Deliberately the same choice
#: `app.market.refresh._SOCIAL_WATCHLIST` already made for its own one-shot startup pass -- drawn
#: from `macro._MOVERS` rather than the bar sweep's ~650-symbol worklist or a second, hand-maintained
#: list that could silently drift from it. There is exactly one social watchlist in this app. A
#: fetch per stored symbol, on a *recurring* clock no less, would be hundreds of requests per tick
#: against a free, keyless endpoint with no SLA -- a fast route to a block, not a series.
_DEFAULT_SYMBOLS: Final[tuple[str, ...]] = tuple(symbol for symbol, _label, _unit in macro._MOVERS)

#: Delay between successive per-symbol provider calls within one scheduler tick. Wider than
#: `app.market.refresh._REQUEST_DELAY_SECONDS` (0.3s) on purpose: that pacing exists for a cold,
#: one-shot sweep at server start, bounded by its own wall-time cap. This scheduler runs for the
#: life of the process, so its pacing is as much a *politeness* constraint on StockTwits/Reddit as it
#: is about data quality -- a caller that never stops asking has to be the well-behaved one every
#: time, not just on the first restart.
_PER_SYMBOL_DELAY_SECONDS: Final[float] = 2.0


# ---------------------------------------------------------------------------
# Scheduler health -- the observable surface `GET /api/market/social/status` reads.
#
# **Why this exists.** Before this, a dead upstream logged "tick complete (0 written, N failed)" at
# INFO and ticked on forever -- nothing exposed the scheduler's health over HTTP and there was no
# breaker, so a blocked StockTwits/Reddit could leave a silent, months-long hole in the one series
# this module's own docstring says can only ever be built *forward* (rule 4 has no bound this store
# cannot honour for a gap it never recorded as a gap). This repo has already paid for exactly this
# failure shape once: `app.evolution.loop`'s own `_MAX_CONSECUTIVE_FAILURES` docstring documents a
# loop that failed 1,644 times in a row while still reporting "running". This section is that same
# fix, mirrored for this scheduler -- and `app.market.refresh.RefreshProgress`/`status()` is the
# structural model followed: a lock-guarded module-level record, a `to_dict()` for the wire, and a
# `status()` accessor a route can call unconditionally.
# ---------------------------------------------------------------------------

#: How many *consecutive* ticks in which every attempted symbol failed (or the tick could not even
#: open its store) this scheduler tolerates before `SocialSchedulerStatus.healthy` flips `False`.
#: Named after, and set to the same value as, `app.evolution.loop._MAX_CONSECUTIVE_FAILURES` -- see
#: that constant's own docstring for the incident it is traceable to. This scheduler's failure mode is
#: milder in cadence (one tick per `Settings.social_snapshot_interval_hours`, not one generation every
#: few seconds) but identical in shape, which is why the same reasoning carries over unchanged: large
#: enough that one bad hour at a free, keyless, no-SLA endpoint does not trip it, small enough that a
#: genuinely dead upstream or a broken credential is flagged within a handful of ticks rather than
#: silently for months.
_MAX_CONSECUTIVE_ALL_FAILED_TICKS: Final[int] = 5


@dataclass
class SocialSchedulerStatus:
    """The scheduler's own health record. One module-level instance (`_status` below), guarded by
    `_status_lock` since the status route reads it from a request thread while `run_scheduler_pass`
    writes it from the scheduler's daemon thread -- or, in a test, from whichever thread calls
    `run_scheduler_pass` directly, which is deliberately enough to exercise this record with no
    thread involved at all, the same way `app.market.refresh`'s tests drive `RefreshProgress` through
    `run_once`.
    """

    total_ticks: int = 0
    last_tick_at: dt.datetime | None = None
    last_written: int = 0
    last_failed: int = 0
    consecutive_all_failed_ticks: int = 0
    """Consecutive ticks that wrote nothing -- every attempted symbol failed, or the tick's own store
    connection failed outright before any symbol was even attempted. See
    `_MAX_CONSECUTIVE_ALL_FAILED_TICKS` and `_record_tick` for exactly what resets this to zero and
    what leaves it untouched."""
    last_error: str | None = None
    """Set when the most recent tick could not even open its store (a locked/corrupt database, disk
    full) -- distinct from a per-symbol provider failure, which `last_failed` already counts. Cleared
    by the next tick that does not hit this, even if that next tick has its own per-symbol failures."""

    @property
    def healthy(self) -> bool:
        return self.consecutive_all_failed_ticks < _MAX_CONSECUTIVE_ALL_FAILED_TICKS

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "total_ticks": self.total_ticks,
            "last_tick_at": self.last_tick_at.isoformat() if self.last_tick_at else None,
            "last_written": self.last_written,
            "last_failed": self.last_failed,
            "consecutive_all_failed_ticks": self.consecutive_all_failed_ticks,
            "max_consecutive_all_failed_ticks": _MAX_CONSECUTIVE_ALL_FAILED_TICKS,
            "last_error": self.last_error,
        }


_status = SocialSchedulerStatus()
_status_lock = threading.Lock()


def status() -> dict[str, Any]:
    """A JSON-serialisable snapshot of the scheduler's health, for `GET /api/market/social/status` --
    the same shape `app.market.refresh.status` already gives its own sweep. Always answers, even when
    the scheduler has never ticked in this process (`total_ticks == 0`, `healthy` is `True` -- a
    scheduler that has not run yet is not unhealthy) -- a caller can poll this unconditionally without
    first checking `Settings.social_snapshot_scheduler_enabled`.
    """
    with _status_lock:
        return _status.to_dict()


def _record_tick(
    written: int, failed: int, *, no_provider: bool = False, connection_error: str | None = None
) -> None:
    """Update `_status` with one tick's outcome, and log louder than the per-symbol `INFO` lines above
    when the tick itself is breaker-relevant -- see the section docstring for why an all-`INFO` trail
    is exactly what let this failure mode go unnoticed before this fix.

    A "no provider configured" tick (`no_provider=True`) neither increments nor resets
    `consecutive_all_failed_ticks`: it is a configuration state the scheduler correctly did nothing
    about, not a failure, and counting it toward the breaker would eventually mark a
    deliberately-unconfigured scheduler "unhealthy" for a reason waiting cannot fix -- the same
    "neither a failure nor a success" treatment `app.evolution.loop`'s own breaker gives a cancelled
    generation. Every other tick does move the streak: writing at least one symbol resets it to zero
    (a partial failure alongside a real write is not the "designed to continue hides total failure"
    case this breaker exists for -- `run_scheduler_pass`'s own per-symbol logging already names which
    symbols failed); writing nothing -- whether every symbol failed or the pass could not even open
    its store -- increments it.
    """
    with _status_lock:
        _status.total_ticks += 1
        _status.last_tick_at = dt.datetime.now(dt.UTC)
        _status.last_written = written
        _status.last_failed = failed
        _status.last_error = connection_error

        if no_provider:
            return

        wrote_nothing = written == 0 and (failed > 0 or connection_error is not None)
        if written > 0:
            _status.consecutive_all_failed_ticks = 0
            return
        if not wrote_nothing:
            return  # an empty symbol list: no attempts made, nothing to judge either way

        _status.consecutive_all_failed_ticks += 1
        logger.warning(
            "social snapshot scheduler: tick wrote nothing (%d failed, error=%r) -- %d consecutive "
            "all-failed tick(s) (unhealthy at %d)",
            failed,
            connection_error,
            _status.consecutive_all_failed_ticks,
            _MAX_CONSECUTIVE_ALL_FAILED_TICKS,
        )
        if _status.consecutive_all_failed_ticks >= _MAX_CONSECUTIVE_ALL_FAILED_TICKS:
            logger.error(
                "social snapshot scheduler: unhealthy -- %d consecutive ticks wrote nothing "
                "(threshold %d); the social-sentiment series has a growing, unbackfillable gap "
                "starting now",
                _status.consecutive_all_failed_ticks,
                _MAX_CONSECUTIVE_ALL_FAILED_TICKS,
            )


def run_scheduler_pass(
    cfg: Settings,
    registry: ProviderRegistry,
    symbols: Sequence[str] = _DEFAULT_SYMBOLS,
    *,
    stop_event: threading.Event | None = None,
    delay_seconds: float = _PER_SYMBOL_DELAY_SECONDS,
) -> tuple[int, int]:
    """One pass over `symbols`: fetch a live snapshot and `record_snapshot` it, symbol by symbol.

    Returns `(written, failed)`. **Never raises** -- this extends the "degrade a section, never
    raise" contract `app.market.news`'s module docstring states for this same provider layer (a dead
    upstream costs its own section, not the whole panel) from "one panel section" to "one scheduler
    tick": a dead StockTwits, a rate limit, a locked database -- any of it costs this tick's rows for
    the symbols it touched, and nothing else. The next tick is unaffected and the process does not
    go down. `registry.has_social_providers` is checked first so "no provider configured" is
    recorded once and skipped, rather than raised once per symbol and paced as if it were N real
    requests -- the same reasoning `app.market.refresh._record_social_snapshots` already applies.

    `stop_event`, when given, is waited on between symbols instead of a bare `time.sleep`, so a
    caller stopping the scheduler is not stuck waiting out a full `delay_seconds` on whichever symbol
    is in flight -- see `start_scheduler`.

    Public (unlike `_scheduler_loop` below) for the same reason `app.market.refresh.run_once` is
    public: a test calls this directly with a fake registry and a `tmp_path`-backed `cfg`, and
    asserts on the returned counts and the store's rows afterward, without touching a thread at all.

    Every call -- whether from `_scheduler_loop`'s daemon thread or directly from a test -- also
    updates the module-level `SocialSchedulerStatus` via `_record_tick` before returning, which is
    what makes this function's own return value and `status()`'s counters agree: there is exactly one
    place a tick's outcome is decided, not two that could drift.
    """
    written = failed = 0
    if not registry.has_social_providers:
        logger.info("social snapshot scheduler: no social provider configured, skipping tick")
        _record_tick(written, failed, no_provider=True)
        return written, failed

    connection_error: str | None = None
    try:
        with connect(default_db_path(cfg)) as conn:
            for symbol in symbols:
                if stop_event is not None and stop_event.is_set():
                    break
                try:
                    snapshot = registry.get_social(symbol)
                    record_snapshot(conn, snapshot)
                except Exception as exc:  # one dead symbol must not end the pass -- see docstring
                    failed += 1
                    logger.info("social snapshot scheduler: %s failed: %s", symbol, exc)
                else:
                    written += 1
                if stop_event is not None:
                    stop_event.wait(delay_seconds)
                else:
                    time.sleep(delay_seconds)
    except Exception as exc:
        # A connection-level failure (locked/corrupt database, disk full) lands here, uncaught by the
        # per-symbol `try` above. Same rule one level up: log it, keep whatever was written before
        # the failure, and let the *next* tick try again -- never raise past this function. Counted as
        # an all-failed tick by `_record_tick` below, same as every symbol failing would be.
        logger.exception("social snapshot scheduler: pass failed")
        connection_error = str(exc)

    _record_tick(written, failed, connection_error=connection_error)
    return written, failed


def _scheduler_loop(
    settings: Settings | None,
    interval_seconds: float,
    stop_event: threading.Event,
    symbols: Sequence[str],
) -> None:
    """The body of the daemon thread `start_scheduler` starts: tick, sleep, repeat, until stopped.

    `default_registry` is built once for the loop's lifetime, not once per tick: it only wraps
    provider HTTP clients and carries no state that goes stale between ticks, so rebuilding it every
    tick would buy nothing and would be one more thing that could fail inside the loop.
    """
    from app.config import get_settings

    cfg = settings or get_settings()
    registry = default_registry(cfg)
    while not stop_event.is_set():
        written, failed = run_scheduler_pass(cfg, registry, symbols, stop_event=stop_event)
        logger.info(
            "social snapshot scheduler: tick complete (%d written, %d failed)", written, failed
        )
        stop_event.wait(interval_seconds)


def start_scheduler(settings: Settings | None = None) -> threading.Event | None:
    """Start the recurring social-snapshot scheduler on a daemon thread and return immediately.

    This is Phase D-social's clock: the plan named a snapshot table written on a schedule as the
    prerequisite a sentiment history cannot exist without, and this is what starts writing to it
    without a person remembering to run something by hand every few hours. Mirrors
    `app.market.refresh.refresh_market_data` / `app.paperdesk.desk.warm`'s shape exactly -- called
    from `app.main.lifespan`, never blocks the caller (starting the thread costs microseconds; the
    first tick itself runs on the thread, not here), and every failure inside the loop is caught by
    `run_scheduler_pass` and logged rather than raised, so a dead provider or a locked database costs
    that tick's rows, never the server.

    **Gated at the call site, not in here.** `app.main.lifespan` checks
    `Settings.social_snapshot_scheduler_enabled` before calling this function at all -- the same
    shape `refresh_market_data`'s own docstring describes for `Settings.refresh_on_startup`, and for
    the same reason: this function has no opinion about whether it should run, so a caller that wants
    to know "was the scheduler even asked to start" can check its own gate rather than this one's
    return value. `interval_hours <= 0` is still validated here, defensively, because an invalid
    interval reaching `Event.wait` as a non-positive number would busy-loop rather than schedule.

    Returns the `threading.Event` that stops the loop, for a caller (a test, or a future shutdown
    hook) that needs to end it deterministically rather than leaving it to the daemon thread's own
    process-exit cleanup; returns `None`, and starts no thread, when `social_snapshot_interval_hours`
    is not positive.
    """
    from app.config import get_settings

    cfg = settings or get_settings()
    interval_hours = cfg.social_snapshot_interval_hours
    if interval_hours <= 0:
        logger.warning(
            "social_snapshot_interval_hours=%r must be positive; scheduler not started",
            interval_hours,
        )
        return None
    stop_event = threading.Event()
    threading.Thread(
        target=_scheduler_loop,
        args=(settings, interval_hours * 3600.0, stop_event, _DEFAULT_SYMBOLS),
        name="social-snapshot-scheduler",
        daemon=True,
    ).start()
    return stop_event

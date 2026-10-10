"""Bar store: incremental sync against the provider registry, reads, weekly resampling, coverage.

This is the only module that decides *when* to talk to a provider at all. Everything below it
(:mod:`app.market.registry`, the providers, :mod:`app.market.cache`) is stateless with respect to
"is this fresh enough" -- that question only makes sense against what is already on disk, which is
this module's job to know.

**``1w`` is never fetched or stored.** :func:`sync_bars` on ``Interval.WEEK`` syncs the underlying
daily interval instead and says so in a warning; :func:`read_series` resamples weekly bars from
stored daily bars on every read. Storing both would create two representations of the same week
that drift apart the moment a daily bar is corrected -- see ``app/db/duck.py`` for the same
decision made at the storage-partitioning level.

**A provider failure is not fatal once the store already holds data.** :func:`ensure_series` catches
:class:`~app.market.providers.base.ProviderUnavailable` and returns the stored bars with a
``stale`` warning instead of propagating the error. A chart rendering yesterday's close with a
visible caveat is worth far more to the user than an error page; only an *empty* store re-raises,
because then there is nothing to fall back to.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd

from app.config import Settings, get_settings
from app.db import duck
from app.db.duck import BAR_COLUMNS, Interval
from app.market.models import (
    Bar,
    BarSeries,
    BarSource,
    Coverage,
    MarketWarning,
    assert_not_money,
    clamp_start,
    jsonable_float,
)
from app.market.providers.base import ProviderError, ProviderUnavailable
from app.market.registry import ProviderRegistry, default_registry

__all__ = [
    "SyncOutcome",
    "coverage",
    "ensure_series",
    "latest_bars",
    "latest_two_bars",
    "read_frame",
    "read_series",
    "sync_bars",
]

#: How far behind the last stored bar an incremental sync re-requests, so a late correction to an
#: already-stored session is picked up rather than permanently missed. Daily uses a session count
#: because corrections to US equities typically land within a few trading days; intraday uses a
#: flat day because a partial bar from the previous request may since have settled.
_OVERLAP: Final[dict[Interval, dt.timedelta]] = {
    Interval.DAY: dt.timedelta(days=3),
    Interval.FOUR_HOUR: dt.timedelta(days=1),
    Interval.HOUR: dt.timedelta(days=1),
    Interval.THIRTY_MIN: dt.timedelta(days=1),
    Interval.FIFTEEN_MIN: dt.timedelta(days=1),
    Interval.FIVE_MIN: dt.timedelta(days=1),
}

#: How long since the last **fetch** before `ensure_series` syncs again. Matches the interval's own
#: cadence: a 5-minute bar is worth refetching well within the hour, a completed daily session is not
#: going anywhere for a day. Checked only during a plausible trading window for intraday intervals --
#: see `_is_stale` -- so a chart opened on a Saturday does not retry every request against a market
#: that has been closed since Friday.
#:
#: Measured against the fetch time and *not* against the newest stored bar, which is the obvious
#: reading and is wrong here. The store deliberately holds settled bars only, so during Monday's
#: session the newest daily bar is Friday's -- already older than the one-day threshold, and older
#: still every minute after. Comparing against it made every single request re-fetch from the
#: provider: not merely wasteful, but the source of the concurrent writes that then collided in the
#: bar store. Two individually correct decisions, wrong in combination.
#: Intraday entries are held to roughly one-to-three bar periods: long enough that a sync does not
#: re-fire before a new bar could exist, short enough that a chart is never more than a bar or two
#: behind. `4h` gets its nominal period rather than the 2.5h remainder bar's, deliberately -- keying
#: staleness off the shorter of the two would re-fetch mid-bar every afternoon for no new data.
_STALENESS: Final[dict[Interval, dt.timedelta]] = {
    Interval.FIVE_MIN: dt.timedelta(minutes=15),
    Interval.FIFTEEN_MIN: dt.timedelta(minutes=30),
    Interval.THIRTY_MIN: dt.timedelta(hours=1),
    Interval.HOUR: dt.timedelta(hours=1),
    Interval.FOUR_HOUR: dt.timedelta(hours=4),
    Interval.DAY: dt.timedelta(days=1),
}

#: Fallback exchange timezone for the intraday trading-window gate (`_plausible_trading_window`),
#: used only when the actual exchange timezone is unknown -- meta predating this field, a meta write
#: that failed (see `_write_meta`), or a sync served by a provider that does not report one (Stooq,
#: which in any case never serves intraday bars, so this only ever bites Yahoo edge cases). Most of
#: this portfolio is US-listed, so this is the least-wrong single default rather than a claim that
#: every symbol trades in New York -- see `_meta_exchange_tz` for where a real, per-symbol value
#: comes from instead.
_DEFAULT_EXCHANGE_TZ: Final[ZoneInfo] = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class SyncOutcome:
    """Result of one `sync_bars` call."""

    symbol: str
    interval: Interval
    source: BarSource
    rows_written: int
    coverage: Coverage
    warnings: list[MarketWarning] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


def sync_bars(
    symbol: str,
    interval: Interval,
    *,
    registry: ProviderRegistry | None = None,
    settings: Settings | None = None,
    full: bool = False,
) -> SyncOutcome:
    """Fetch new bars since the last sync (or the whole history when `full` or unstored) and merge.

    `Interval.WEEK` is redirected to `Interval.DAY` -- weekly bars are never fetched, see the module
    docstring -- and the returned `SyncOutcome` carries a warning saying so along with the daily
    sync's own warnings and row count.
    """
    cfg = settings or get_settings()
    reg = registry or default_registry(cfg)

    if interval is Interval.WEEK:
        daily = sync_bars(symbol, Interval.DAY, registry=reg, settings=cfg, full=full)
        note = MarketWarning(
            kind="derived",
            message=(
                f"{symbol}: 1w bars are not fetched or stored; synced 1d bars instead and will "
                "resample weekly on read"
            ),
        )
        return SyncOutcome(
            symbol=symbol,
            interval=Interval.WEEK,
            source=daily.source,
            rows_written=daily.rows_written,
            coverage=daily.coverage,
            warnings=[*daily.warnings, note],
        )

    bars_dir = cfg.bars_dir
    warnings: list[MarketWarning] = []

    if full:
        start: dt.date | None = None
    else:
        # In-memory, not `cfg.analytics_path` -- this only reads via `read_parquet(bar_path(...))`
        # and never touches the on-disk catalog, so there is nothing for a physical connection to
        # buy here. See `read_frame`'s matching comment for why that distinction is load-bearing.
        with duck.connect() as conn:
            existing = _normalize_utc(duck.read_bars(conn, bars_dir, symbol, interval))
        if existing.empty:
            start = None
        else:
            last_ts = existing["ts"].max()
            start = (last_ts - _OVERLAP[interval]).date()

    clamped_start, was_clamped = clamp_start(interval, start)
    if was_clamped:
        warnings.append(
            MarketWarning(
                kind="clamped",
                message=(
                    f"{symbol} {interval.value}: start clamped to {clamped_start} -- the provider "
                    "does not serve history before that date for this interval"
                ),
            )
        )

    fetch = reg.get_bars(symbol, interval, start=clamped_start, end=None)
    warnings.extend(fetch.warnings)

    with duck.connect(cfg.analytics_path) as conn:
        duck.write_bars(conn, bars_dir, symbol, interval, fetch.frame)

    meta_warning = _write_meta(
        bars_dir, symbol, interval, source=fetch.source, exchange_timezone=fetch.exchange_timezone
    )
    if meta_warning is not None:
        warnings.append(meta_warning)

    return SyncOutcome(
        symbol=symbol,
        interval=interval,
        source=fetch.source,
        rows_written=len(fetch.frame),
        coverage=coverage(symbol, interval, settings=cfg),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def read_frame(
    symbol: str,
    interval: Interval,
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
    limit: int | None = None,
    settings: Settings | None = None,
) -> pd.DataFrame:
    """Read stored bars as a frame with :data:`BAR_COLUMNS`, resampling weekly from daily on read."""
    cfg = settings or get_settings()

    if interval is Interval.WEEK:
        # Resample from the *full* daily history before applying start/end, not the other way
        # round: bounding the daily read first could cut off the earlier sessions of a week whose
        # boundary falls mid-range, which would make the resulting weekly bar's `ts` (the first
        # session actually present) wrong for that edge week.
        frame = _resample_weekly(read_frame(symbol, Interval.DAY, settings=cfg))
        if start is not None:
            frame = frame[frame["ts"] >= pd.Timestamp(start, tz="UTC")]
        if end is not None:
            frame = frame[frame["ts"] <= pd.Timestamp(end, tz="UTC")]
        frame = frame.reset_index(drop=True)
    else:
        # `duck.connect()` -- in-memory, no `cfg.analytics_path` -- not merely `read_only=True`
        # against it. `read_bars` only ever runs `read_parquet(bar_path(...))` against a path it is
        # given directly; it has no dependency on anything persisted in the on-disk DuckDB catalog
        # (this module never creates a table there -- see `app.db.duck`'s module docstring). A
        # physical connection therefore buys this function nothing, at two real costs: DuckDB cannot
        # open a nonexistent file `read_only=True` (a fresh checkout, or any symbol never synced,
        # would raise on a pure read -- see `TestCoverage.test_coverage_on_an_empty_store_...` in
        # `tests/test_market_store.py`, which exercises exactly that), and even a healthy read-only
        # connection would still be a second handle on the same physical file that a concurrent
        # writer or research script could collide with, however much safer that is than read-write.
        # An in-memory connection needs neither the file to exist nor any coordination with whoever
        # else has it open -- it is not present on disk at all. Same reasoning `_read_many` and
        # `sync_bars`'s incremental-start read below apply, and the same choice `app.tournament.
        # roster.tradeable_universe` already made for its own bar reads (its docstring: "a read path
        # has no business creating it"). The one connection in this module that must reach the real
        # file is `sync_bars`'s write below -- see `duck.connect`'s docstring for why writing still
        # needs it.
        with duck.connect() as conn:
            frame = duck.read_bars(conn, cfg.bars_dir, symbol, interval, start=start, end=end)
        frame = _normalize_utc(frame)

    return _tail(frame, limit)


def read_series(
    symbol: str,
    interval: Interval,
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
    limit: int | None = None,
    settings: Settings | None = None,
) -> BarSeries:
    """`read_frame` converted to the API-boundary shape, with provenance attached."""
    frame = read_frame(symbol, interval, start=start, end=end, limit=limit, settings=settings)
    source = BarSource.DERIVED if interval is Interval.WEEK else BarSource.STORE
    return BarSeries(symbol=symbol, interval=interval, source=source, bars=_frame_to_bars(frame))


def ensure_series(
    symbol: str,
    interval: Interval,
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
    limit: int | None = None,
    refresh: bool = False,
    registry: ProviderRegistry | None = None,
    settings: Settings | None = None,
) -> BarSeries:
    """The endpoint's entry point: sync when needed, always return something rather than an error.

    Syncs first when the store is empty, when `refresh` is set, or when the last fetch has aged past
    the interval's staleness threshold during a plausible trading window. A provider failure at that
    point is only fatal if there is nothing already stored to fall back to -- see the module
    docstring.

    The staleness check only needs to know *whether* anything is stored, not what it is -- so it asks
    `_has_stored_rows` (a file-existence check) rather than reading the full frame here just to throw
    it away. `read_series` below still does the real read; this used to call `read_frame` a second
    time for that same frame and discard it, doubling the cost of every single-symbol lookup for a
    boolean.
    """
    cfg = settings or get_settings()
    store_interval = Interval.DAY if interval is Interval.WEEK else interval
    has_rows = _has_stored_rows(cfg.bars_dir, symbol, store_interval)
    meta = _read_meta(cfg.bars_dir, symbol, store_interval)
    fetched_at = _meta_fetched_at(meta)
    exchange_tz = _meta_exchange_tz(meta)

    sync_warnings: list[MarketWarning] = []
    if refresh or not has_rows or _is_stale(
        has_rows, store_interval, fetched_at=fetched_at, exchange_tz=exchange_tz
    ):
        try:
            outcome = sync_bars(symbol, interval, registry=registry, settings=cfg)
            sync_warnings = outcome.warnings
        except ProviderUnavailable as exc:
            if not has_rows:
                raise  # nothing to fall back to -- this has to surface as an error
            sync_warnings = [
                MarketWarning(
                    kind="stale",
                    message=f"{symbol} {interval.value}: provider unavailable ({exc}); showing stored data",
                )
            ]

    series = read_series(symbol, interval, start=start, end=end, limit=limit, settings=cfg)
    return series.model_copy(update={"warnings": [*series.warnings, *sync_warnings]})


def latest_bars(
    symbols: Sequence[str],
    interval: Interval,
    *,
    registry: ProviderRegistry | None = None,
    settings: Settings | None = None,
) -> dict[str, Bar]:
    """The most recent stored bar for each of `symbols`, batched for the price-lookup fan-out.

    Built for `app.api.portfolio`, which used to call `ensure_series` once per open position -- each
    call opening (and closing) its own DuckDB connection. Connecting costs about 23ms on this machine
    regardless of database size, dwarfing the actual scan; 67 positions therefore cost well over a
    second in connection overhead alone before a single row was read. This batches the store reads
    behind one shared connection instead.

    **Same staleness rule as `ensure_series`**, applied per symbol: a sync is needed when nothing is
    stored yet or when `_is_stale` says the last fetch has aged out, using the very same
    `_read_meta` / `_meta_fetched_at` / `_meta_exchange_tz` / `_is_stale` helpers so the two entry
    points can never quietly disagree about what counts as fresh.

    **A symbol simply drops out of the result when it cannot be priced at all** -- no stored bars and
    the provider refuses it (`ProviderError`, which also covers `SymbolNotFound`: a delisted or
    mistyped ticker must not raise here any more than a network failure does). That is deliberately
    looser than `ensure_series`, which re-raises `ProviderUnavailable` when nothing is stored --
    exactly right for a single chart request, wrong here, because one bad symbol must never blank the
    other 66 in the same batch. When a symbol *does* have stored bars and only the refresh fails, the
    stale stored bar is still returned, matching `ensure_series`'s own stale-fallback behaviour.

    **Connections are never held open across a `sync_bars` call.** `sync_bars` opens its own
    connection to merge and `Path.replace()` the parquet partition, and on Windows that replace fails
    if any handle -- reader or writer -- is still open on the file anywhere in the process (see
    `read_bars`'s docstring in `app.db.duck`). So this runs in three strictly separated phases: one
    shared connection reads every symbol's stored bars and is closed; the (normally empty, at most a
    handful of) stale or missing symbols are synced one at a time through their own connections; a
    second shared connection re-reads just those symbols. No connection is held across step two.

    The three phases (and the staleness/dedup/weekly-resample decisions above) are shared with
    `latest_two_bars` via `_latest_frames`, so the two entry points can never quietly disagree about
    what counts as fresh or which symbols got synced. This function's own job is just the final
    tail-to-one-row-per-symbol shape.
    """
    frames = _latest_frames(symbols, interval, registry=registry, settings=settings)
    return {symbol: _frame_to_bars(_tail(frame, 1))[0] for symbol, frame in frames.items()}


def latest_two_bars(
    symbols: Sequence[str],
    interval: Interval,
    *,
    registry: ProviderRegistry | None = None,
    settings: Settings | None = None,
) -> dict[str, tuple[Bar, Bar | None]]:
    """`latest_bars`, but the two most recent stored bars per symbol instead of one.

    Built for a day-over-day change: the caller needs both the latest price and the session before
    it to compute a delta, and batching this the same way `latest_bars` does avoids doubling the
    per-position connection overhead `latest_bars` itself exists to eliminate (see that docstring).

    Returns `(most recent bar, the bar before it)` per symbol. The second element is `None` when
    the store (after any sync) holds only one bar for that symbol -- not an error, just not enough
    history yet for a day-over-day comparison. A symbol that could not be priced at all is simply
    absent from the dict, exactly as in `latest_bars`.

    Shares every staleness/sync/connection-phase decision with `latest_bars` through the private
    `_latest_frames` helper below -- see that function's docstring for the three-phase Windows
    constraint neither of these may violate. This function's own job is just tailing to two rows
    per symbol instead of one.
    """
    frames = _latest_frames(symbols, interval, registry=registry, settings=settings)
    result: dict[str, tuple[Bar, Bar | None]] = {}
    for symbol, frame in frames.items():
        tailed = _frame_to_bars(_tail(frame, 2))
        result[symbol] = (tailed[-1], tailed[-2]) if len(tailed) >= 2 else (tailed[-1], None)
    return result


def _latest_frames(
    symbols: Sequence[str],
    interval: Interval,
    *,
    registry: ProviderRegistry | None,
    settings: Settings | None,
) -> dict[str, pd.DataFrame]:
    """The batched sync-then-read body shared by `latest_bars` and `latest_two_bars`.

    Runs the exact three phases described in `latest_bars`'s docstring -- one shared connection to
    read every symbol, stale/missing symbols synced one at a time through their own connection(s)
    with no connection held open from phase 1 or 3 across that step, then one fresh shared
    connection to re-read just what changed -- and applies the same staleness rule and weekly
    resample decision `latest_bars` always has. Neither caller may inline any of this: doing so
    would let the two functions drift on what counts as fresh, exactly the risk this factoring
    exists to remove.

    Returns each de-duplicated (upper-cased) symbol's full stored (or, for `Interval.WEEK`,
    resampled) frame, oldest bar first, completely untailed -- callers decide how many trailing
    rows they need. A symbol with no data at all after phase 3 (never stored, and the provider
    could not supply it either) is simply absent from the returned dict.
    """
    cfg = settings or get_settings()
    reg = registry or default_registry(cfg)
    store_interval = Interval.DAY if interval is Interval.WEEK else interval

    # De-duplicate while preserving order -- a symbol held in several accounts must not be synced or
    # scanned twice.
    unique_symbols = list(dict.fromkeys(s.upper() for s in symbols))

    # Phase 1: one connection, every symbol's full stored history, then close it.
    frames = _read_many(unique_symbols, store_interval, cfg)

    to_sync: list[str] = []
    for symbol in unique_symbols:
        meta = _read_meta(cfg.bars_dir, symbol, store_interval)
        fetched_at = _meta_fetched_at(meta)
        exchange_tz = _meta_exchange_tz(meta)
        has_rows = not frames[symbol].empty
        if not has_rows or _is_stale(
            has_rows, store_interval, fetched_at=fetched_at, exchange_tz=exchange_tz
        ):
            to_sync.append(symbol)

    # Phase 2: sync the (normally few) stale/missing symbols, each through its own connection(s).
    # Absolutely no connection from phase 1 or 3 is open while this runs.
    synced_ok: list[str] = []
    for symbol in to_sync:
        try:
            sync_bars(symbol, interval, registry=reg, settings=cfg)
        except ProviderError:
            continue  # leave whatever was already stored (possibly nothing) as the answer
        synced_ok.append(symbol)

    # Phase 3: re-read just the symbols that actually changed, through one fresh shared connection.
    if synced_ok:
        frames.update(_read_many(synced_ok, store_interval, cfg))

    result: dict[str, pd.DataFrame] = {}
    for symbol in unique_symbols:
        frame = frames[symbol]
        if interval is Interval.WEEK:
            frame = _resample_weekly(frame)
        if frame.empty:
            continue
        result[symbol] = frame
    return result


def _read_many(
    symbols: Sequence[str], store_interval: Interval, cfg: Settings
) -> dict[str, pd.DataFrame]:
    """Every symbol's full stored history at `store_interval`, through one shared connection.

    `store_interval` is never `Interval.WEEK` -- callers resample from the daily frame themselves,
    same as `read_frame` does -- so this always hits `duck.read_bars` directly rather than the
    resampling branch.
    """
    frames: dict[str, pd.DataFrame] = {}
    # In-memory, same reasoning as `read_frame` -- these are pure `read_parquet` reads with no need
    # for the on-disk catalog.
    with duck.connect() as conn:
        for symbol in symbols:
            frames[symbol] = _normalize_utc(duck.read_bars(conn, cfg.bars_dir, symbol, store_interval))
    return frames


def coverage(symbol: str, interval: Interval, *, settings: Settings | None = None) -> Coverage:
    """Row count, span and last-fetch time for what the store actually holds.

    `fetched_at` has no home in the Parquet schema -- adding a column for one scalar per file would
    be a strange use of a columnar format -- so it lives in a small JSON sidecar next to the file
    instead (`bars.meta.json`), written by `sync_bars` on every successful sync.
    """
    cfg = settings or get_settings()

    if interval is Interval.WEEK:
        weekly = _resample_weekly(read_frame(symbol, Interval.DAY, settings=cfg))
        meta = _read_meta(cfg.bars_dir, symbol, Interval.DAY)
        return Coverage(
            symbol=symbol,
            interval=Interval.WEEK,
            rows=len(weekly),
            first_ts=_to_pydatetime(weekly["ts"].min()) if not weekly.empty else None,
            last_ts=_to_pydatetime(weekly["ts"].max()) if not weekly.empty else None,
            fetched_at=_meta_fetched_at(meta),
        )

    frame = read_frame(symbol, interval, settings=cfg)
    meta = _read_meta(cfg.bars_dir, symbol, interval)
    return Coverage(
        symbol=symbol,
        interval=interval,
        rows=len(frame),
        first_ts=_to_pydatetime(frame["ts"].min()) if not frame.empty else None,
        last_ts=_to_pydatetime(frame["ts"].max()) if not frame.empty else None,
        fetched_at=_meta_fetched_at(meta),
    )


# ---------------------------------------------------------------------------
# Weekly resampling
# ---------------------------------------------------------------------------


def _resample_weekly(daily: pd.DataFrame, *, today: dt.date | None = None) -> pd.DataFrame:
    """Weekly OHLCV grouped by ISO calendar week, not by a fixed-frequency resample.

    Grouping on `(iso_year, iso_week)` is what makes a holiday-shortened week come out right: the
    week's `ts` is the `ts` of the first daily bar *actually present* in the group, never a
    synthetic Monday -- a market holiday on the Monday would otherwise invent a date on which the
    exchange was shut. `open` is the group's first bar, `close` its last, `high`/`low` the group
    extremes, `volume` the group sum.

    **The most recent ISO week is excluded while it is still in progress.** The store's contract
    (see `app.market.models.Bar.partial`) is that a bar returned from a read is settled and will not
    change later. Daily and intraday bars uphold that because the provider never returns a bar for a
    session that has not closed (`YahooProvider._drop_unsettled_bar`); weekly resampling had no
    equivalent, so syncing Monday-Wednesday of the current week and reading `Interval.WEEK` produced
    `close`/`high`/`volume` that then silently changed on Thursday's read once more daily bars
    existed to fold in -- exactly the mutation `_drop_unsettled_bar` exists to prevent, one layer up.
    Dropped rather than flagged: `BAR_COLUMNS` (see `app.db.duck`) carries no `partial` column, and
    `Bar.partial` is explicitly documented as never true for a bar read from the store, so excluding
    the still-forming week keeps both of those true rather than needing to change them.

    "In progress" is judged against `today`'s own ISO (year, week), not the venue's trading calendar
    (which this function has no way to know): a week counts as settled once real calendar time has
    moved into a *later* ISO week than the group's. `today` defaults to the UTC calendar date, not
    the host machine's local date -- bar `ts` values are stored and compared in UTC throughout this
    module (see `_normalize_utc`), so judging "which ISO week is `today` in" against local time would
    disagree with that near a day boundary whenever the local offset is nonzero: a host west of UTC
    (e.g. US Pacific) has already-synced bars from the new UTC week while its local clock still
    reads the tail of the old one, which flipped `current_week_still_forming` to `False` for a week
    that had in fact just started and let a still-forming week's bar through as if it were settled --
    the exact mutation this function exists to prevent.

    The ISO-week rule correctly resolves a holiday-shortened week
    (see `TestWeeklyResampling` below) the moment the following week starts, even though its last
    session fell before Friday -- but it also means a week that finished trading on Friday is not
    served until the following Monday rather than over the weekend. That is a deliberate choice, not
    an oversight: this module already accepts the same trade-off at the daily/weekly boundary (see
    the module docstring's "1w is never fetched or stored" note) -- being briefly conservative is
    preferable to a bar that might still be wrong.
    """
    if daily.empty:
        return daily.copy()

    frame = daily.sort_values("ts").reset_index(drop=True)
    iso = frame["ts"].dt.isocalendar()
    frame = frame.assign(_iso_year=iso["year"], _iso_week=iso["week"])

    grouped = frame.groupby(["_iso_year", "_iso_week"], sort=True)
    weekly = (
        grouped.agg(
            ts=("ts", "first"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            adj_close=("adj_close", "last"),
            volume=("volume", lambda s: s.sum(min_count=1)),
        )
        .sort_values("ts")
        .reset_index(drop=True)
    )

    today_iso = (today or dt.datetime.now(dt.UTC).date()).isocalendar()
    last_daily_iso = iso.iloc[-1]
    current_week_still_forming = (int(last_daily_iso["year"]), int(last_daily_iso["week"])) == (
        today_iso.year,
        today_iso.week,
    )
    if current_week_still_forming:
        weekly = weekly.iloc[:-1].reset_index(drop=True)

    return weekly[list(BAR_COLUMNS)]


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


def _is_stale(
    has_rows: bool,
    interval: Interval,
    *,
    fetched_at: dt.datetime | None,
    exchange_tz: str | None = None,
    now: dt.datetime | None = None,
) -> bool:
    """Whether stored data is old enough to be worth re-fetching.

    Keyed on when the provider was last asked, not on how old the newest bar is. See `_STALENESS`
    for why the difference is load-bearing rather than pedantic.

    Takes `has_rows` rather than the frame itself: every caller already knows whether anything is
    stored (`_has_stored_rows`'s file-existence check for a single symbol, or a frame already read
    for another reason in the batch path) and reading a whole frame here just to check `.empty` would
    either duplicate a read the caller already did or force one that was not otherwise needed.

    `exchange_tz` is the instrument's own exchange timezone (see `_meta_exchange_tz`), threaded
    through to `_plausible_trading_window` so the intraday gate checks the venue's actual trading
    hours rather than always assuming America/New_York -- see that function's docstring. `now`
    defaults to the real clock and exists so both this and `_plausible_trading_window` can be tested
    against a fixed instant rather than by monkeypatching `datetime.now`.
    """
    if not has_rows:
        return True
    if fetched_at is None:
        return True  # written before the sidecar existed, or a partial write: treat as unknown
    moment = now or dt.datetime.now(dt.UTC)
    if not _plausible_trading_window(interval, now=moment, exchange_tz=exchange_tz):
        return False
    return moment - fetched_at > _STALENESS[interval]


def _plausible_trading_window(
    interval: Interval, *, now: dt.datetime | None = None, exchange_tz: str | None = None
) -> bool:
    """Whether it is worth checking staleness at all right now.

    Daily staleness (one day) already self-limits to roughly one sync attempt per calendar day, so
    it is not gated further. Intraday staleness (fifteen minutes, one hour) would otherwise retry on
    every single request through a closed weekend; this gate is what stops that.

    The window is evaluated in the instrument's *own* exchange timezone, not a fixed one. A fixed
    America/New_York conversion made this gate silently wrong for every non-US symbol: a Tokyo
    listing's 09:00-15:00 JST session lands at 19:00-01:00 the previous day in New York, entirely
    outside the window below, so intraday data for it read as "not worth checking" -- and therefore
    never refreshed -- for the whole real trading session, no matter how stale. `exchange_tz` falls
    back to `_DEFAULT_EXCHANGE_TZ` when unknown (see that constant); an unrecognised zone name (a
    corrupted sidecar, or a provider reporting something `zoneinfo` cannot parse) falls back the
    same way rather than raising, because a bad timezone string should degrade the staleness check,
    not the request.
    """
    if not interval.is_intraday:
        return True
    tz = _DEFAULT_EXCHANGE_TZ
    if exchange_tz is not None:
        try:
            tz = ZoneInfo(exchange_tz)
        except (KeyError, ValueError):
            tz = _DEFAULT_EXCHANGE_TZ
    moment = (now or dt.datetime.now(dt.UTC)).astimezone(tz)
    if moment.weekday() >= 5:  # Saturday, Sunday
        return False
    return dt.time(4, 0) <= moment.time() <= dt.time(20, 0)  # generous pre/post-market bound


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _has_stored_rows(bars_dir: Path, symbol: str, interval: Interval) -> bool:
    """Cheap emptiness check: does the partition file exist at all.

    Existence rather than a row count -- `duck.write_bars` never publishes an empty parquet file (a
    fetch with zero rows never reaches `write_bars`, see `sync_bars`), so "the file is there" and
    "there are rows in it" coincide in practice, and checking the former needs no DuckDB connection
    at all. That is the entire point of this helper: `ensure_series` used to read the whole frame
    just to ask this one boolean question.
    """
    return duck.bar_path(bars_dir, symbol, interval).exists()


def _tail(frame: pd.DataFrame, limit: int | None) -> pd.DataFrame:
    """`limit` keeps the most recent N rows -- a chart wants the latest bars, not the earliest."""
    if limit is None or len(frame) <= limit:
        return frame
    return frame.iloc[-limit:].reset_index(drop=True)


def _normalize_utc(frame: pd.DataFrame) -> pd.DataFrame:
    """Re-express `ts` in UTC after a round trip through the DuckDB/Parquet store.

    DuckDB re-labels a ``TIMESTAMP WITH TIME ZONE`` column with the *connection's local* timezone on
    read rather than UTC -- verified directly: writing a UTC midnight timestamp and reading it back
    yields the same instant tagged with the machine's local zone instead. The instant is correct, but
    ``.date()`` and ISO-calendar week extraction depend on *which* timezone the value is expressed
    in, and would silently pick the wrong session date and the wrong weekly bucket on any machine not
    running in UTC -- exactly the failure mode `app.market.models.session_date` exists to prevent,
    reintroduced one layer down by the storage engine. Every read normalises back to UTC here so
    nothing downstream needs to know this quirk exists.
    """
    if frame.empty or "ts" not in frame.columns:
        return frame
    frame = frame.copy()
    frame["ts"] = frame["ts"].dt.tz_convert("UTC")
    return frame


def _to_pydatetime(value: pd.Timestamp) -> dt.datetime:
    result = value.to_pydatetime()
    assert isinstance(result, dt.datetime)
    return result


def _frame_to_bars(frame: pd.DataFrame) -> list[Bar]:
    bars: list[Bar] = []
    for row in frame.itertuples(index=False):
        volume = row.volume
        bars.append(
            Bar(
                ts=_to_pydatetime(row.ts),
                open=assert_not_money(row.open, field="open"),
                high=assert_not_money(row.high, field="high"),
                low=assert_not_money(row.low, field="low"),
                close=assert_not_money(row.close, field="close"),
                adj_close=jsonable_float(row.adj_close),
                volume=int(volume) if pd.notna(volume) else None,
            )
        )
    return bars


def _meta_path(bars_dir: Path, symbol: str, interval: Interval) -> Path:
    return duck.bar_path(bars_dir, symbol, interval).with_name("bars.meta.json")


#: One lock per meta sidecar path, exactly `app.db.duck._WRITE_LOCKS` one layer down. Measured
#: directly before adding this: a uuid-suffixed staging name alone is *not* sufficient on Windows,
#: because the collision is not really about the staging path -- it is `staging.replace(path)`
#: itself, and two threads calling that concurrently against the same destination `path` raced with
#: `PermissionError` regardless of the staging file's name, 90 times out of 240 in a genuinely
#: concurrent 8-threads-x-30-rounds test. `app.market.cache.CachingTransport._write` hits the same
#: wall and swallows the resulting `OSError` unconditionally -- acceptable there because every
#: racing writer is caching an identical HTTP response and the collision is comparatively rare
#: (bounded by the cache's own TTL, not by every sync). Neither holds here: a 37% hit rate under
#: real concurrency would make the "stale" warning in `_write_meta` routine noise on any concurrent
#: access pattern, not a rare fallback. A lock is the actual fix `app.db.duck.write_bars` already
#: uses for this same problem; the `OSError` handling in `_write_meta` remains as defense against a
#: genuine filesystem failure the lock cannot prevent (permissions, a full disk).
_META_WRITE_LOCKS: dict[Path, threading.Lock] = {}
_META_LOCK_REGISTRY = threading.Lock()


def _meta_write_lock(path: Path) -> threading.Lock:
    """The lock guarding one meta sidecar path -- see `_META_WRITE_LOCKS`."""
    with _META_LOCK_REGISTRY:
        return _META_WRITE_LOCKS.setdefault(path, threading.Lock())


def _write_meta(
    bars_dir: Path,
    symbol: str,
    interval: Interval,
    *,
    source: BarSource,
    exchange_timezone: str | None = None,
) -> MarketWarning | None:
    """Write the fetch-time sidecar, returning a warning (never raising) if the write itself fails.

    Two things had to change from the version that raced, not one:

    * **The staging name carries a uuid**, matching `app.db.duck._merge_and_write` and
      `app.market.cache._write`, so two concurrent writers never stage through the identical
      ``bars.meta.json.tmp`` path.
    * **The write is serialised per meta path** (`_meta_write_lock`), matching
      `app.db.duck._write_lock`. The uuid alone is not enough: measured directly, `staging.replace
      (path)` itself still raced -- 90 `PermissionError`\\s out of 240 attempts in a genuinely
      concurrent 8-threads-x-30-rounds test with uuid staging and no lock -- because Windows refuses
      to complete a replace onto a destination another thread's replace is targeting at the same
      instant. The *destination* is the shared mutable resource, not just the staging name; only a
      lock removes that, which is exactly why `duck.py` uses one for the same problem.

    Before either fix, this raced as `PermissionError: Access is denied` on the final rename, 94
    times across 8 threads x 30 rounds in production, every one of them *after* `duck.write_bars`
    had already persisted the bars correctly -- so a request that had actually succeeded still came
    back as a 500.

    A failure that gets past both of the above (a genuine filesystem problem -- permissions, a full
    disk) is not swallowed to nothing, unlike `app.market.cache._write`. `cache.py` can swallow a
    losing write because every racing writer there is caching an identical HTTP response, so losing
    it costs nothing but a cache entry. This sidecar is different: it is the *only* record of when
    this symbol/interval was last fetched, and losing it makes `_meta_fetched_at` return `None`,
    which `_is_stale` treats as "unknown, refetch" -- silently losing a write here would not corrupt
    anything, but it would make every subsequent request re-sync until a write finally succeeds. That
    is a real, visible consequence, so it is surfaced as a warning rather than hidden.
    """
    path = _meta_path(bars_dir, symbol, interval)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, str] = {
        "fetched_at": dt.datetime.now(dt.UTC).isoformat(),
        "source": source.value,
    }
    if exchange_timezone is not None:
        payload["exchange_timezone"] = exchange_timezone
    staging = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        with _meta_write_lock(path):
            staging.write_text(json.dumps(payload), encoding="utf-8")
            staging.replace(path)
    except OSError as exc:
        return MarketWarning(
            kind="stale",
            message=(
                f"{symbol} {interval.value}: failed to write fetch-time metadata ({exc}); "
                "staleness checks will treat this sync as unknown-age and re-fetch on the next "
                "request until a metadata write succeeds"
            ),
        )
    finally:
        staging.unlink(missing_ok=True)
    return None


def _read_meta(bars_dir: Path, symbol: str, interval: Interval) -> dict[str, str] | None:
    path = _meta_path(bars_dir, symbol, interval)
    if not path.exists():
        return None
    try:
        data: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data


def _meta_fetched_at(meta: dict[str, str] | None) -> dt.datetime | None:
    if meta is None:
        return None
    return dt.datetime.fromisoformat(meta["fetched_at"])


def _meta_exchange_tz(meta: dict[str, str] | None) -> str | None:
    """The instrument's exchange timezone as last recorded by a successful sync, if any.

    Absent for meta written before this field existed, for a sync served by a provider that does
    not report one (Stooq), or after a failed metadata write -- all of which `_plausible_trading_window`
    treats as "unknown" and falls back to `_DEFAULT_EXCHANGE_TZ` for.
    """
    if meta is None:
        return None
    return meta.get("exchange_timezone")

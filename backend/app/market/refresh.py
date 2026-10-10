"""Background bar refresh, started from the application's `lifespan` on every server start.

**The precedent this follows is `app.paperdesk.desk.warm`.** That function solves the same shape of
problem -- something expensive that should happen automatically at startup without delaying it or
making a request pay for it cold -- with a daemon thread that returns immediately and swallows its
own failures. This module reuses that shape rather than inventing a second one: :func:`refresh_market_data`
is this package's `warm()`.

**Why this needs more machinery than `warm()` did.** `warm()` computes one thing (the paper desk) and
either succeeds or logs nothing. A market-data refresh touches up to 646 network round trips -- 635
daily symbols, 5 hourly, 6 five-minute (see `app.db.duck.stored_symbols`), plus the macro dashboard's
own movers, rate/oil tiles and Fear & Greed (`app.market.macro`). Firing all of that at every dev-server
reload, unpaced, would both make the app slow to become useful and risk tripping Yahoo's rate limiter
(`app.market.providers.base.RateLimited`) for every other request in flight at the same time. So this
module adds four things `warm()` didn't need: a **priority order** (the symbols named explicitly by the
owner first, then what the user actually holds, then everything else), a **staleness gate** (skip a
symbol whose stored data already covers the most recent plausible session), **pacing** (a delay between
requests and a hard cap on total wall time), and an **observable progress record** so a person can tell
whether it actually worked rather than inferring it from the absence of errors.

**Scope: the bar store, plus one best-effort warm of the macro page's own cache.** The priority-1 list
below is `app.market.macro._MOVERS` (already includes `BTC-USD` and `DX-Y.NYB`, the two the owner named
by ticker) plus the Yahoo-proxy symbol on every `app.market.macro._RATE_TILES` / `_OIL_TILES` entry
(`^TNX` for the 10Y, `CL=F` for WTI -- the other two names the owner used). Both constants are read
directly from `macro`, never copied, so a mover or tile added there is picked up here without a second
edit. What is genuinely out of this module's reach is the four raw FRED series ids (`DGS10`, `T10Y2Y`,
`DCOILWTICO`, `DCOILBRENTEU`) and CNN's Fear & Greed reading: neither is a bar-store symbol, so
`app.market.store.coverage`/`sync_bars` have no name for them and this module's staleness gate and
per-symbol progress counters cannot describe them either. Both already sit behind their own 24-hour
on-disk cache (`macro._MACRO_CACHE_TTL`), so :func:`_warm_macro_snapshot` makes one best-effort call to
`macro.build_snapshot` to warm that cache -- cheap once warm, a small bounded burst when cold -- and
records only whether that one call succeeded, entirely separate from the honest refreshed/skipped/failed
counts the per-symbol sweep keeps for everything it can actually name.

**Off by default.** See `Settings.refresh_on_startup` for why: `tests/conftest.py` is outside this
phase's scope fence, does not set `INVDASH_REFRESH_ON_STARTUP`, and so inherits whatever this flag
defaults to -- `False` is the only choice available here that keeps the test suite's network usage at
zero without an edit this phase is not permitted to make.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Final

from app.config import Settings, get_settings
from app.datasource import ledger_db_path
from app.db import sqlite
from app.db.duck import Interval, stored_symbols
from app.market import macro, store
from app.market.providers.base import RateLimited
from app.market.registry import ProviderRegistry, default_registry

__all__ = ["refresh_market_data", "run_once", "status"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

#: How many calendar days a symbol's newest stored session (`Coverage.last_ts`) may lag behind the
#: most recent *plausible* trading day before this sweep bothers asking the provider for more.
#: Weekends are already rolled back to the preceding Friday by `_latest_expected_session` before this
#: is applied, so `0` here means "on or after that weekday", not "today" literally -- a symbol synced
#: through Friday's close stays fresh all weekend and is only re-queued once a new weekday arrives.
#: Exchange holidays are not modelled (no calendar is threaded through this module, matching
#: `store._plausible_trading_window`'s own admitted approximation for the same reason): the cost of
#: getting a holiday wrong is one wasted, still-paced request, not a wrong skip that leaves a symbol
#: stale.
_STALE_TOLERANCE_DAYS: Final[int] = 0

#: Deliberately conservative UTC hour after which *today's* regular session can be presumed closed,
#: for the *default* US-market assumption this staleness gate makes -- see `_STALE_TOLERANCE_DAYS`
#: above for why this module does not thread a real, per-symbol exchange timezone through here
#: (matching `store._plausible_trading_window`'s own admitted approximation). US regular hours close
#: at 16:00 America/New_York, which is 20:00 UTC under EDT (summer) and 21:00 UTC under EST (winter);
#: this uses the *earlier* of the two on purpose. The later one, 21:00, would be wrong in exactly the
#: way `_STALE_TOLERANCE_DAYS`'s own docstring already rules out: for the hour between 20:00 and 21:00
#: UTC during EST season, today's session actually has closed and a fresh bar for it may already be
#: sitting at the provider, but a threshold that still called today "not yet closed" would keep
#: treating yesterday's stored bar as fresh and skip the fetch that would have picked it up -- "a
#: wrong skip that leaves a symbol stale". Using 20:00 costs the opposite, safe mistake instead: for
#: that same hour during EDT season it fires one extra, still-paced re-check of a symbol that is
#: genuinely already current, because the provider's own unsettled-bar check (see
#: `app.market.providers.yahoo._last_bar_unsettled`) still correctly refuses to hand back a bar for a
#: session in progress.
_MARKET_CLOSE_UTC_HOUR: Final[int] = 20

#: Delay between successive provider requests. This is what keeps a cold sweep of ~650 symbols from
#: firing them at Yahoo back-to-back -- the exact behaviour the owner asked this module to avoid.
#: 300ms caps the sweep's own request rate at ~3.3/s, comfortably under typical free-tier scraping
#: thresholds, while keeping a full cold sweep's pacing overhead alone under four minutes.
_REQUEST_DELAY_SECONDS: Final[float] = 0.3

#: Hard ceiling on one sweep's total wall time. The dev server restarts on every file save, so this
#: bounds how long a sweep from *this* restart can still be running -- and therefore competing for the
#: same rate-limited upstream -- once the next restart's own sweep starts. Ten minutes covers a full
#: cold sweep of ~650 symbols at the pacing above (~4 minutes of delay alone, plus request time) with
#: headroom, while still being far short of a typical gap between saves during active development.
_MAX_WALL_TIME_SECONDS: Final[float] = 600.0

#: The symbols a social snapshot is taken for on each sweep. Deliberately small and deliberately
#: *not* the sweep's own worklist: see `_record_social_snapshots` for why 650 requests per restart
#: would buy a rate-limit block instead of a series. Drawn from `macro._MOVERS` so it tracks the
#: movers grid rather than being a second hand-maintained list that drifts from it.
_SOCIAL_WATCHLIST: Final[tuple[str, ...]] = tuple(symbol for symbol, _label, _unit in macro._MOVERS)

#: Extra backoff applied on top of a `RateLimited` response's own `retry_after` (or, when the upstream
#: gave none, used on its own) before the sweep moves on to its *next* symbol. Never re-requests the
#: same symbol in a loop -- see the module docstring and `RateLimited`'s own docstring -- so this is
#: paid once per rate-limit hit, not per retry.
_RATE_LIMIT_BACKOFF_SECONDS: Final[float] = 5.0

#: How many failed symbols the status payload names individually. The count in `RefreshProgress.failed`
#: is exact regardless of this cap; this only bounds how much detail `/api/market/refresh/status`
#: returns so a bad run against hundreds of symbols does not inflate the response.
_MAX_FAILED_SYMBOLS_LISTED: Final[int] = 50

#: The bar-store intervals this sweep covers, in the order it walks them: daily first (635 symbols,
#: the bulk of the store and every priority-1/2 symbol), then the much smaller intraday tiers.
#: The three sub-hourly/multi-hour tiers cost nothing until a symbol is actually stored at them --
#: the walk below is driven by `stored_symbols(bars_dir, interval)`, so an interval with an empty
#: partition contributes zero work. Once the research backfill populates them, this is what keeps
#: them from decaying: 5m/15m/30m retention is a rolling 60 days at the provider, so a tier that is
#: not swept loses history permanently rather than merely going stale.
_SWEEP_INTERVALS: Final[tuple[Interval, ...]] = (
    Interval.DAY,
    Interval.FOUR_HOUR,
    Interval.HOUR,
    Interval.THIRTY_MIN,
    Interval.FIFTEEN_MIN,
    Interval.FIVE_MIN,
)


# ---------------------------------------------------------------------------
# Progress record
# ---------------------------------------------------------------------------


@dataclass
class RefreshProgress:
    """One sweep's counters. A module-level instance is the only mutable state here, guarded by
    `_progress_lock` since the API layer reads it from a request thread while `_sweep` writes it from
    the background one.

    `refreshed` + `skipped_fresh` + `failed` never exceeds `queued`, and equals it once `complete` is
    `True` -- see `run_once` for where each counter is incremented and `status` for how a caller tells
    a still-running sweep from a finished, and a finished-but-truncated sweep from a genuinely complete
    one.
    """

    running: bool = False
    queued: int = 0
    refreshed: int = 0
    """Symbols whose sync round-trip completed without raising -- **not** symbols that gained new
    data, which the name invites a reader to assume.

    `store.sync_bars` re-requests a short overlap behind the newest stored bar on every incremental
    call (`store._OVERLAP`), so it essentially always returns rows and essentially never raises
    merely because the provider had nothing newer. A symbol already current through the latest close
    therefore lands here, not in `skipped_fresh` -- `skipped_fresh` counts only symbols this sweep
    declined to *ask* about, which is a different statement.

    The sibling counter that does mean "something changed" is
    `app.paperdesk.models.FetchSummary.advanced`, which compares each symbol's newest stored session
    either side of its sync rather than inferring it from a row count. The two summaries deliberately
    use different vocabularies because they answer different questions: this one is "how much of the
    worklist did the sweep get through", that one is "did pressing the button move the mark".
    """
    skipped_fresh: int = 0
    failed: int = 0
    failed_symbols: list[str] = field(default_factory=list)
    """`"{symbol}:{interval}"` for up to `_MAX_FAILED_SYMBOLS_LISTED` failures -- diagnostic detail on
    top of the exact `failed` count, not a replacement for it."""
    #: Outcome of the social-snapshot pass -- `"pending"` until it runs, then `"<n> written, <m>
    #: failed"`, or `"failed"` if the whole pass could not open its store. Kept separate from the
    #: per-symbol counters above for the same reason `macro_snapshot` is: one social outage is one
    #: fact about one section, not N symbol failures inflating the sweep's own failure count.
    social_snapshots: str = "pending"

    complete: bool = True
    """`False` only when `_MAX_WALL_TIME_SECONDS` stopped the sweep before the worklist was exhausted.
    See the module docstring's honesty requirement: a partial sweep must never look finished."""
    stopped_reason: str | None = None
    macro_snapshot: str | None = None
    """`None` (not attempted yet), `"ok"` or `"failed"` -- see `_warm_macro_snapshot`. Deliberately not
    folded into `refreshed`/`failed`: it covers FRED and CNN, which are not bar-store symbols this
    sweep's per-symbol counters can name."""
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    error: str | None = None
    """Set only if `_sweep` itself raised something its own per-symbol handling did not already catch
    -- e.g. failing to read the worklist at all. A daemon thread's uncaught exception cannot crash the
    server, but it must not vanish silently either; see `run_once`."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "queued": self.queued,
            "refreshed": self.refreshed,
            "skipped_fresh": self.skipped_fresh,
            "failed": self.failed,
            "failed_symbols": list(self.failed_symbols),
            "processed": self.refreshed + self.skipped_fresh + self.failed,
            "complete": self.complete,
            "stopped_reason": self.stopped_reason,
            "macro_snapshot": self.macro_snapshot,
            "social_snapshots": self.social_snapshots,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "error": self.error,
        }


_progress = RefreshProgress()
_progress_lock = threading.Lock()
#: Non-blocking: a second `refresh_market_data()` call while one sweep is already running skips
#: starting another rather than queueing behind it or running two sweeps concurrently against the same
#: on-disk store. Nothing in this application calls this more than once per process today (the lifespan
#: hook runs once at startup), but a defensive guard here costs little.
_sweep_lock = threading.Lock()


def status() -> dict[str, Any]:
    """A JSON-serialisable snapshot of the current or most recent sweep, for the status route."""
    with _progress_lock:
        return _progress.to_dict()


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def refresh_market_data(settings: Settings | None = None) -> bool:
    """Start one refresh sweep on a daemon thread and return immediately.

    Mirrors `app.paperdesk.desk.warm`'s shape exactly: called from `lifespan`, never blocks the caller,
    and a failure here -- network, disk, anything -- must not prevent the server from starting or
    answering requests. See `run_once` for what actually happens on the thread and `status` for how to
    observe it afterwards.

    Gated by `Settings.refresh_on_startup` at the call site in `app.main.lifespan`, not in here: this
    function itself has no opinion about whether it should run, the same way `warm()` does not gate on
    anything either -- the caller decides.

    Returns `True` if a sweep was started and `False` if `_sweep_lock` was already held -- the
    "already running, not starting another" case, which was previously only visible in the log. The
    on-demand `POST /api/market/refresh` endpoint (`app.api.data_admin`) needs to tell a person which
    of the two happened when they press the button, and inferring it from `status()["running"]`
    afterwards would be a race: the sweep this call started may not have reached `run_once` yet, so
    `running` can still be `False` on a successful start. `app.main.lifespan`'s own call ignores the
    return, exactly as before.
    """
    if not _sweep_lock.acquire(blocking=False):
        logger.info("market refresh: a sweep is already running, not starting another")
        return False
    threading.Thread(
        target=_run_locked, args=(settings,), name="market-refresh", daemon=True
    ).start()
    return True


def _run_locked(settings: Settings | None) -> None:
    try:
        run_once(settings)
    finally:
        _sweep_lock.release()


def run_once(settings: Settings | None = None, *, registry: ProviderRegistry | None = None) -> None:
    """Run one full sweep synchronously, updating the module-level progress record as it goes.

    Public (unlike everything else below) so tests can call it directly with a fake `registry` and
    assert on `status()` afterwards, without touching threads at all -- `refresh_market_data` above is
    the only production caller, and it is just this function plus a daemon thread. `registry` exists
    for exactly that injection; the real entry point never passes one; `_sweep` builds
    `default_registry(cfg)` when it is omitted.
    """
    global _progress
    cfg = settings or get_settings()
    with _progress_lock:
        _progress = RefreshProgress(running=True, started_at=_now())

    try:
        _sweep(cfg, registry)
    except Exception as exc:
        # Must reach the caller as status, never as a crash. A daemon thread's own exception cannot
        # bring the server down by itself, but swallowing it with no trace anywhere would violate the
        # observability requirement this module exists to satisfy.
        logger.exception("market refresh sweep failed")
        with _progress_lock:
            _progress.error = str(exc)
    finally:
        with _progress_lock:
            _progress.running = False
            _progress.finished_at = _now()


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _sweep(cfg: Settings, registry: ProviderRegistry | None) -> None:
    reg = registry or default_registry(cfg)

    # Priority 1's macro-page warm happens first and separately from the per-symbol loop below --
    # see the module docstring for why FRED/CNN cannot go through that loop at all.
    _warm_macro_snapshot(cfg, reg)

    worklist = _build_worklist(cfg)
    with _progress_lock:
        _progress.queued = len(worklist)

    deadline = time.monotonic() + _MAX_WALL_TIME_SECONDS
    for symbol, interval in worklist:
        if time.monotonic() >= deadline:
            with _progress_lock:
                processed = _progress.refreshed + _progress.skipped_fresh + _progress.failed
                _progress.complete = False
                _progress.stopped_reason = (
                    f"wall-time cap ({_MAX_WALL_TIME_SECONDS:.0f}s) reached after {processed}/"
                    f"{_progress.queued} symbols"
                )
            logger.warning("market refresh: %s", _progress.stopped_reason)
            return
        _refresh_one(symbol, interval, cfg=cfg, registry=reg)
        time.sleep(_REQUEST_DELAY_SECONDS)

    _record_social_snapshots(cfg, reg)


def _record_social_snapshots(cfg: Settings, registry: ProviderRegistry) -> None:
    """Append one social snapshot per watched symbol, starting Phase D-social's clock.

    `AGENTS-INTEGRATION-PLAN.md` Phase D is explicit that a social *history* cannot be fetched: every
    free endpoint serves only a live window, `SocialProvider` deliberately has no `as_of`, and there
    is no way to manufacture a series retroactively. It has to be accumulated forward from stored
    snapshots -- which cannot begin until something writes them on a schedule. This is that
    something, and until it ran, the earliest honest D-social study was always "months from now,
    counting from a day that had not happened yet."

    **Bounded to `_SOCIAL_WATCHLIST`, not the sweep's ~650-symbol worklist.** A social fetch per
    stored symbol would be 650 requests at StockTwits on every dev-server restart, which is a
    different order of imposition from the bar sweep's own pacing and would earn a block rather than
    a series. A study over twenty symbols observed faithfully is worth more than one over six hundred
    observed until the provider stops answering.

    Failures are swallowed per symbol and logged: a dead provider costs this section and nothing
    else, matching `_warm_macro_snapshot`'s contract above and `app.market.news`'s own never-raises
    rule. Nothing downstream of the sweep depends on a snapshot being written.

    The cadence this produces is irregular -- one observation per server start, not one per hour.
    That is honest rather than ideal: every row carries its own `observed_at`, so a gap is visible in
    the data instead of being smoothed over by an assumed frequency. A real scheduler is the right
    eventual home; this starts the clock now, which is the part that cannot be bought back later.
    """
    try:
        from app.market import social_history
    except Exception:  # pragma: no cover -- module is present; guard keeps the sweep alive regardless
        logger.exception("market refresh: social history module unavailable")
        return

    # No social provider configured means there is nothing to observe, and looping the watchlist to
    # raise twenty times would be twenty pointless failures in the status and -- worse -- twenty
    # pacing sleeps paid for requests that were never made. `_REQUEST_DELAY_SECONDS` exists to space
    # out *network calls*; spacing out local exceptions is pure cost. This is also what keeps the
    # sweep's pacing assertions honest: a test registry with no social provider pays no social delay.
    if not registry.has_social_providers:
        with _progress_lock:
            _progress.social_snapshots = "no provider configured"
        return

    written = failed = 0
    try:
        with social_history.connect(social_history.default_db_path(cfg)) as conn:
            social_history.migrate(conn)
            for symbol in _SOCIAL_WATCHLIST:
                try:
                    snapshot = registry.get_social(symbol)
                except Exception as exc:  # one dead symbol must not end the pass
                    failed += 1
                    logger.info("market refresh: social snapshot for %s failed: %s", symbol, exc)
                else:
                    social_history.record_snapshot(conn, snapshot)
                    written += 1
                time.sleep(_REQUEST_DELAY_SECONDS)
    except Exception as exc:  # see docstring: this section never fails the sweep
        logger.warning("market refresh: social snapshot pass failed: %s", exc)
        with _progress_lock:
            _progress.social_snapshots = "failed"
        return

    with _progress_lock:
        _progress.social_snapshots = f"{written} written, {failed} failed"


def _warm_macro_snapshot(cfg: Settings, registry: ProviderRegistry) -> None:
    """Best-effort warm of the macro dashboard's own FRED/CNN disk cache.

    `macro.build_snapshot(cfg, refresh=False)` is exactly what `GET /api/macro` itself runs: every
    rate/oil tile and mover already defers to `store.ensure_series`'s own staleness check (so a call
    here against an already-fresh store costs nothing but the read), and the FRED/CNN calls that
    function makes are cheap the moment `macro._MACRO_CACHE_TTL`'s 24-hour on-disk cache is warm.
    Isolated in its own try/except and its own `macro_snapshot` status field, never folded into the
    per-symbol counters below, because one macro-page hiccup is one fact, not N symbol failures.
    """
    try:
        macro.build_snapshot(cfg, refresh=False, registry=registry)
    except Exception as exc:  # best-effort warm; see docstring above.
        logger.warning("market refresh: macro snapshot warm failed: %s", exc)
        with _progress_lock:
            _progress.macro_snapshot = "failed"
    else:
        with _progress_lock:
            _progress.macro_snapshot = "ok"


def _build_worklist(cfg: Settings) -> list[tuple[str, Interval]]:
    """Every (symbol, interval) this sweep will consider, in priority order, de-duplicated.

    A symbol that appears in more than one tier (a mover the user also holds, say) is queued once, at
    the highest priority it earned -- `_add` below keeps first-seen order and drops later repeats.
    """
    seen: set[tuple[str, Interval]] = set()
    worklist: list[tuple[str, Interval]] = []

    def _add(symbol: str, interval: Interval) -> None:
        key = (symbol, interval)
        if key not in seen:
            seen.add(key)
            worklist.append(key)

    # Priority 1: the macro key indicators and movers the owner named explicitly, read straight from
    # `macro`'s own constants -- never a second, hand-maintained copy of this list. `_MOVERS` already
    # carries `BTC-USD` and `DX-Y.NYB`; the rate/oil tiles' `yahoo_symbol` carries the 10Y (`^TNX`) and
    # WTI (`CL=F`), the other two the owner named by name.
    for symbol, _label, _unit in macro._MOVERS:
        _add(symbol, Interval.DAY)
    for spec in (*macro._RATE_TILES, *macro._OIL_TILES):
        if spec.yahoo_symbol is not None:
            _add(spec.yahoo_symbol, Interval.DAY)

    # Priority 2: symbols the user actually holds, from the ledger's own instrument table -- the same
    # source `app.api.health.stores` counts from. A missing or unreadable ledger degrades to "no
    # priority-2 symbols" rather than aborting the sweep; priority 1 and 3 do not depend on it.
    for symbol in _held_symbols(cfg):
        _add(symbol, Interval.DAY)

    # Priority 3: everything else already in the store, at every interval it is stored at.
    for interval in _SWEEP_INTERVALS:
        for symbol in stored_symbols(cfg.bars_dir, interval):
            _add(symbol, interval)

    return worklist


def _held_symbols(cfg: Settings) -> list[str]:
    """Priceable instruments the ledger actually knows about, for priority 2.

    Not `provider_symbol`-rewritten here: every store/provider call in this application takes the
    ledger's own symbol spelling (`BRK.B`, not `BRK-B`) and rewrites it internally at the HTTP call
    site -- see `app.market.providers.base.provider_symbol`'s docstring -- so passing the raw ledger
    symbol through to `store.coverage`/`sync_bars` here matches every other caller.
    """
    ledger_file = ledger_db_path(cfg)
    if not ledger_file.exists():
        return []
    try:
        with sqlite.connect(ledger_file, read_only=True) as conn:
            instruments = sqlite.fetch_instruments(conn)
    except Exception:  # degrade to "no priority-2 symbols", not an aborted sweep.
        logger.exception("market refresh: failed to read ledger instruments for priority 2")
        return []
    return [i.primary_symbol for i in instruments if i.is_priceable and i.primary_symbol]


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


def _latest_expected_session(today: dt.date) -> dt.date:
    """The most recent date a daily bar could plausibly exist for, ignoring exchange holidays.

    Saturday and Sunday have no session and roll back to the preceding Friday. Holidays are not
    modelled -- see `_STALE_TOLERANCE_DAYS` for why that is an acceptable, and cheap, approximation
    here specifically.
    """
    rollback = {5: 1, 6: 2}.get(today.weekday(), 0)
    return today - dt.timedelta(days=rollback)


def _session_has_plausibly_closed(now: dt.datetime) -> bool:
    """Whether *today's* regular session, if today turns out to be a trading day at all, can be
    presumed to have already closed -- see `_MARKET_CLOSE_UTC_HOUR` for the cutoff and why it is
    biased the direction it is. This only ever answers "closed" or "not yet"; whether today is a
    trading *day* in the first place is `_latest_expected_session`'s own question, via its weekday
    rollback, which `_latest_settled_session` below applies on top of this.
    """
    return now.astimezone(dt.UTC).hour >= _MARKET_CLOSE_UTC_HOUR


def _latest_settled_session(now: dt.datetime) -> dt.date:
    """The most recent date whose regular session can be presumed to have actually *closed* -- as
    opposed to `_latest_expected_session`'s "most recent plausible weekday", which says nothing about
    whether that weekday's session has happened yet. This function is the fix for the gap between the
    two.

    **The bug this replaces.** `_is_fresh` used to compare straight against
    `_latest_expected_session(now.date())` with no regard for the time of day at all. On any ordinary
    weekday that function returns *today* literally -- the rollback in it only ever fires for
    Saturday/Sunday -- so from midnight through market close, every single weekday, a symbol current
    through *yesterday's* close was judged stale against a threshold naming a session that had not
    happened yet. Worse, it could never be marked fresh again for the rest of that day: the fixed
    `_last_bar_unsettled` in `app.market.providers.yahoo` correctly refuses to hand back a bar for a
    session still in progress, so `store.sync_bars` kept returning the same, unchanged `last_ts` for
    yesterday no matter how many times this ran. Given the module docstring's own note that the dev
    server restarts on every file save, this meant a full re-sweep of every symbol -- the exact
    unpaced-burst behaviour this module exists to prevent -- on every single restart for the entire
    pre-close part of the day, with `RefreshProgress.skipped_fresh` staying near zero throughout.

    Rolls back one further weekday (through `_latest_expected_session` again, applied to yesterday)
    only when today has not plausibly closed yet; once it has, this returns exactly what
    `_latest_expected_session(now.date())` already did, so this changes nothing about the existing
    Friday/weekend behaviour that function already handled.
    """
    today = now.date()
    expected = _latest_expected_session(today)
    if expected == today and not _session_has_plausibly_closed(now):
        return _latest_expected_session(today - dt.timedelta(days=1))
    return expected


def _is_fresh(last_ts: dt.datetime | None) -> bool:
    """Whether `Coverage.last_ts` is recent enough that re-fetching would be wasted work.

    `last_ts` is `None` for a symbol the store has never synced at all -- never fresh, obviously. For
    daily bars this compares calendar dates directly; for the 5/6 intraday symbols this sweep also
    covers, `last_ts` keeps the true instant (see `BarProvider.fetch_bars`'s contract) rather than a
    session-normalised midnight, so the same date comparison is a coarser check for those -- adequate
    here because this sweep's job is "was this touched at all recently", not full intraday
    freshness, which `store.ensure_series`'s own `_is_stale` already enforces on the read path.

    The threshold is `_latest_settled_session`, not `_latest_expected_session` directly -- see that
    function's docstring for the bug that distinction fixes.
    """
    if last_ts is None:
        return False
    threshold = _latest_settled_session(_now()) - dt.timedelta(days=_STALE_TOLERANCE_DAYS)
    return last_ts.date() >= threshold


# ---------------------------------------------------------------------------
# Per-symbol refresh
# ---------------------------------------------------------------------------


def _refresh_one(symbol: str, interval: Interval, *, cfg: Settings, registry: ProviderRegistry) -> None:
    """Refresh one symbol if it is stale, counting the outcome into the module-level progress record.

    Every branch increments exactly one counter: fresh data is `skipped_fresh`, a successful sync is
    `refreshed`, anything that raises -- including `RateLimited` -- is `failed`. See the module
    docstring's honesty requirement: a failure must be counted and logged, never silently dropped.
    """
    try:
        coverage = store.coverage(symbol, interval, settings=cfg)
    except Exception as exc:  # a coverage read failing is still a failure to report, not a crash.
        _record_failed(symbol, interval, exc)
        return

    if _is_fresh(coverage.last_ts):
        with _progress_lock:
            _progress.skipped_fresh += 1
        return

    try:
        store.sync_bars(symbol, interval, registry=registry, settings=cfg)
    except Exception as exc:
        rate_limited = _find_rate_limited(exc)
        if rate_limited is not None:
            backoff = (
                rate_limited.retry_after
                if rate_limited.retry_after is not None
                else _RATE_LIMIT_BACKOFF_SECONDS
            )
            logger.warning(
                "market refresh: rate limited on %s %s, backing off %.1fs before the next symbol",
                symbol,
                interval.value,
                backoff,
            )
            # Backing off and moving on to the *next* symbol -- never re-requesting this one in a
            # loop -- is what `RateLimited`'s own docstring and this module's docstring both require.
            time.sleep(backoff)
        # Every other failure -- `SymbolNotFound`, a plain `ProviderUnavailable`, or anything a
        # provider or the duck/parquet layer raises that this module did not anticipate -- is still
        # counted as failed rather than propagating out and silently ending the sweep early. See the
        # module docstring's honesty requirement.
        _record_failed(symbol, interval, exc)
    else:
        with _progress_lock:
            _progress.refreshed += 1


def _find_rate_limited(exc: BaseException) -> RateLimited | None:
    """Find a `RateLimited` anywhere in `exc`'s `__cause__` chain.

    `app.market.registry._walk` never lets a provider's `RateLimited` reach this module directly: once
    every provider in the chain has failed, it raises a plain `ProviderUnavailable` summarising all of
    them (`raise ProviderUnavailable(...) from last_exc`, see that function) -- so a call through
    `store.sync_bars` that hit a rate limit surfaces here as that wrapper, not as `RateLimited` itself.
    Python's `raise ... from ...` sets exactly the `__cause__` this walks to recover the original, which
    is what lets `_refresh_one` still back off correctly instead of treating a rate limit as an
    ordinary failure. Bounded rather than following `__cause__` indefinitely: the chain is one hop deep
    in practice (`_walk` wraps once), and `BaseException.__cause__` defaults to `None` in any case, but
    an explicit bound keeps this from ever looping on a pathological exception whose `__cause__` was
    set to point at itself.
    """
    current: BaseException | None = exc
    for _ in range(5):
        if isinstance(current, RateLimited):
            return current
        if current is None:
            return None
        current = current.__cause__
    return None


def _record_failed(symbol: str, interval: Interval, exc: Exception) -> None:
    logger.warning("market refresh: failed to refresh %s %s: %s", symbol, interval.value, exc)
    with _progress_lock:
        _progress.failed += 1
        if len(_progress.failed_symbols) < _MAX_FAILED_SYMBOLS_LISTED:
            _progress.failed_symbols.append(f"{symbol}:{interval.value}")

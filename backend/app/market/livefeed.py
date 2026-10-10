"""The process-wide live-quote feed: one shared source, an opt-in keep-warm daemon, one status view.

**Why this module exists at all, given `app.market.live` already has a source and
`app.api.paperlive` already had a singleton.** That singleton lived inside an HTTP router, which
means it only ever existed on the terms of a browser request: a symbol was watched because a tab
asked for it, and it stopped being watched ten minutes after the last tab went away (see
`app.market.live.DEFAULT_WATCH_IDLE_SECONDS`). An agent, a background trading loop or an evidence
builder is not a tab. It asks once, at an unpredictable moment, and it must not pay a cold
synchronous provider fetch for the privilege -- nor should it have to import an API router to get a
price. So the singleton moves here, `app.api.paperlive._source` becomes a one-line delegation to it,
and this module adds the piece a router had no business owning: a daemon that keeps the symbols this
application actually cares about subscribed whether or not anyone is looking.

**What the daemon does, and does not, do.** Every `Settings.livefeed_keepalive_seconds` it calls
`snapshot()` on the shared source with the whole watchlist -- held ledger symbols, macro movers,
`Settings.livefeed_watchlist`, plus anything `watch()` added at runtime. That call is exactly what
`PollingQuoteSource.subscribe` counts as "a caller is still interested", so nothing gets evicted, and
a brand-new symbol pays its one-time synchronous fetch on the *daemon's* thread rather than on the
thread of whoever asks first. It does not place orders, it does not write anything to disk, and it
never touches the network itself -- every request is made by the source it delegates to.

**It is off by default, and the flag is about cost.** See `Settings.livefeed_enabled`: a standing
subscription polls every held symbol every five seconds through the whole regular session. Reading
one quote on demand -- `latest()`, and the `live_quote` evidence section built on it -- deliberately
does *not* require the flag, because that is a single request paid for by the caller who wanted it.

**"Running" is not "working".** This module carries the aggregate check this codebase has been
burned for omitting: a loop that fails on every iteration and still reports itself healthy. The
source's own `healthy` property already counts fully-failed poll cycles
(`PollingQuoteSource._consecutive_total_failures`); `status()["healthy"]` is that **and** this
daemon's own streak of ticks in which the snapshot call raised or came back with no quotes at all.
Either one reaching `_UNHEALTHY_AFTER_TICKS` makes `healthy` `False` while `running` stays `True`,
which is the honest description of a daemon that is alive and achieving nothing. `healthy` is `None`
-- not `True` -- until the daemon has actually looked at the source once, because "no evidence yet"
and "fine" are different answers.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from collections.abc import Sequence
from typing import Any, Final

from app.config import Settings, get_settings
from app.market.live import LiveQuote, LiveQuoteSource, LiveSnapshot, build_source

logger = logging.getLogger(__name__)

__all__ = [
    "latest",
    "latest_with_snapshot",
    "reset",
    "snapshot",
    "source",
    "start",
    "status",
    "stop",
    "unwatch",
    "watch",
]


#: How many consecutive keep-warm ticks may produce nothing at all -- the snapshot call raised, or it
#: returned zero quotes for a non-empty watchlist -- before `status()["healthy"]` goes `False`.
#: Three, the same number and the same reasoning as `app.market.live._UNHEALTHY_AFTER_CYCLES`: one
#: dead tick against a flaky upstream is ordinary and already visible per-symbol in the snapshot's
#: `errors`, three in a row is an outage.
_UNHEALTHY_AFTER_TICKS: Final[int] = 3

#: Granularity of the daemon's interruptible sleep, copied in shape from
#: `app.workflow.loop._sleep_checking_stop`: never one long `time.sleep` (a stop requested mid-wait
#: would not take effect until the full keepalive interval elapsed) and never a spin loop.
_SLEEP_SLICE_SECONDS: Final[float] = 0.5

#: Hard ceiling on how many symbols the daemon will keep subscribed at once.
#:
#: The watchlist is assembled from the ledger, which is unbounded by anything this module controls --
#: and every symbol on it costs one provider request per poll interval (5s during regular hours) for
#: as long as the daemon runs. A ledger that grows to 400 priceable instruments would silently turn
#: this into 80 requests a second against Yahoo, which is not a feature anyone asked for; it is a rate
#: limit waiting to happen. Truncation is logged, and it drops from the *tail* of a priority-ordered
#: list (see `_watch_targets`), so the symbols someone explicitly asked for survive it.
_MAX_WATCHED: Final[int] = 120


# ---------------------------------------------------------------------------
# Module state. Two locks, on purpose: `_source_lock` guards only the singleton's construction (which
# can be slow -- it builds an httpx client), `_state_lock` guards the watchlist and daemon bookkeeping
# (which every tick touches). Keeping them separate means a status() call never waits behind a source
# being built, and building a source never waits behind a tick.
# ---------------------------------------------------------------------------

_source_lock = threading.Lock()
_source_instance: LiveQuoteSource | None = None

_state_lock = threading.RLock()
_manual: set[str] = set()
"""Symbols added by `watch()` -- runtime interest, on top of whatever the settings and the ledger
already imply."""
_effective: tuple[str, ...] = ()
"""The full watchlist as of the daemon's most recent tick. Empty until it has run once."""
_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None
_settings: Settings | None = None
_started_at: dt.datetime | None = None
_last_snapshot_at: dt.datetime | None = None
_market_state: str | None = None
_ticks: int = 0
_consecutive_failures: int = 0


def _normalize(symbols: Sequence[str]) -> list[str]:
    """Upper-cased, whitespace-stripped, de-duplicated, first occurrence wins."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        symbol = raw.strip().upper()
        if symbol and symbol not in seen:
            seen.add(symbol)
            out.append(symbol)
    return out


# ---------------------------------------------------------------------------
# The shared source
# ---------------------------------------------------------------------------


def source(settings: Settings | None = None) -> LiveQuoteSource:
    """The one `LiveQuoteSource` this process uses, built on first call and reused forever after.

    `settings` is read only when the singleton does not exist yet -- a later call passing different
    settings gets the source that was already built, deliberately: two sources would mean two poll
    threads racing the same provider for the same symbols, and the transport choice is a deployment
    setting, not a per-call one. `reset()` is how a test gets a fresh one.
    """
    global _source_instance
    with _source_lock:
        if _source_instance is None:
            _source_instance = build_source(settings or get_settings())
        return _source_instance


def snapshot(symbols: Sequence[str]) -> LiveSnapshot:
    """One snapshot of `symbols` from the shared source, which also re-stamps their idle timers.

    Raises whatever the source raises -- this is the plumbing call, and a caller that wants the
    fail-soft version wants `latest()` (or the `live_quote` evidence section) instead.
    """
    return source().snapshot(_normalize(symbols))


def latest_with_snapshot(symbol: str) -> tuple[LiveQuote | None, LiveSnapshot | None]:
    """`latest()`, plus the snapshot it came out of -- which is where `transport` lives.

    Exists because the quote alone cannot say whether it was served by the polling transport or the
    stream: `LiveQuote.source` names the *provider* (`"yahoo"`), while `LiveSnapshot.transport` names
    how this process got it. `app.agentdesk.evidence.live_quote_evidence` attributes its items to the
    transport, so it needs both halves of one call rather than two calls that could disagree.

    Never raises: any failure is logged and returns `(None, None)`, because every caller of this is
    either fail-soft by contract (the evidence layer) or wants a plain "no quote right now".
    """
    upper = symbol.strip().upper()
    if not upper:
        return None, None
    try:
        snap = source().snapshot([upper])
    except Exception:
        logger.exception("livefeed: snapshot for %s failed", upper)
        return None, None
    for quote in snap.quotes:
        if quote.symbol == upper:
            return quote, snap
    return None, snap


def latest(symbol: str) -> LiveQuote | None:
    """The newest quote the shared source holds for one symbol, or `None`.

    `None` covers all three of "the source failed", "the source has no quote for this symbol yet" and
    "this symbol is not a thing" -- none of which is an error a caller of a live quote should have to
    handle differently. A brand-new symbol pays the same one-time synchronous fetch
    `PollingQuoteSource.subscribe` documents; every later call for it answers from cache.
    """
    quote, _snap = latest_with_snapshot(symbol)
    return quote


# ---------------------------------------------------------------------------
# The watchlist
# ---------------------------------------------------------------------------


def watch(symbols: Sequence[str]) -> None:
    """Add `symbols` to the keep-warm watchlist. Idempotent, upper-cased, safe before `start()`.

    Adding a symbol does **not** fetch it: it means "the daemon should keep this warm from its next
    tick onward". A caller that wants the quote now calls `latest()`.
    """
    with _state_lock:
        _manual.update(_normalize(symbols))


def unwatch(symbols: Sequence[str]) -> None:
    """Drop `symbols` from the runtime watchlist. A no-op for anything not in it.

    This only removes what `watch()` added. A symbol the ledger holds, or one named in
    `Settings.livefeed_watchlist`, is re-derived on every tick and comes straight back -- unwatching
    it here would be a lie, so it is not attempted.
    """
    with _state_lock:
        _manual.difference_update(_normalize(symbols))


def _configured_symbols(cfg: Settings) -> list[str]:
    return _normalize(cfg.livefeed_watchlist.split(","))


def _mover_symbols() -> list[str]:
    """The macro page's movers. Imported lazily -- `app.market.macro` pulls in the whole provider
    stack, and this module must stay importable (and cheap) for callers that only want `status()`."""
    try:
        from app.market.macro import _MOVERS

        return _normalize([symbol for symbol, _label, _unit in _MOVERS])
    except Exception:  # pragma: no cover - defensive; a broken import must not kill the daemon
        logger.exception("livefeed: could not read the macro movers")
        return []


def _held_ledger_symbols(cfg: Settings) -> list[str]:
    """Priceable instruments the ledger knows about, via `app.market.refresh._held_symbols`.

    Reusing that private helper rather than re-querying the ledger here is deliberate: it already
    handles the missing-ledger and unreadable-ledger cases by degrading to an empty list, and two
    definitions of "which symbols does this application hold" would drift.
    """
    try:
        from app.market.refresh import _held_symbols

        return _normalize(_held_symbols(cfg))
    except Exception:  # pragma: no cover - defensive; _held_symbols already swallows its own errors
        logger.exception("livefeed: could not read held ledger symbols")
        return []


def _watch_targets(cfg: Settings) -> list[str]:
    """The full watchlist for one tick, in priority order and capped at `_MAX_WATCHED`.

    Order is the truncation policy: explicit runtime interest (`watch()`) first, then the configured
    watchlist, then the macro movers, then the ledger's holdings -- so if a large ledger pushes the
    list past the cap, what falls off the end is the part nobody named individually.
    """
    with _state_lock:
        manual = sorted(_manual)
    ordered = _normalize([*manual, *_configured_symbols(cfg), *_mover_symbols(), *_held_ledger_symbols(cfg)])
    if len(ordered) > _MAX_WATCHED:
        logger.warning(
            "livefeed: watchlist of %d symbols exceeds the %d cap; keeping the first %d and dropping %s",
            len(ordered),
            _MAX_WATCHED,
            _MAX_WATCHED,
            ", ".join(ordered[_MAX_WATCHED:]),
        )
        ordered = ordered[:_MAX_WATCHED]
    return ordered


# ---------------------------------------------------------------------------
# The daemon
# ---------------------------------------------------------------------------


def _sleep_checking_stop(stop_event: threading.Event, seconds: float) -> None:
    """Sleep up to `seconds` in `_SLEEP_SLICE_SECONDS` slices, returning early once `stop_event` is
    set -- the same shape as `app.workflow.loop._sleep_checking_stop`, for the same reason."""
    deadline = time.monotonic() + max(seconds, 0.0)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or stop_event.is_set():
            return
        time.sleep(min(_SLEEP_SLICE_SECONDS, remaining))


def _tick(cfg: Settings) -> None:
    """One keep-warm pass: re-subscribe the whole watchlist and record what came back.

    Never raises. A failed tick increments `_consecutive_failures`, which is half of what
    `status()["healthy"]` reports; a tick that produced at least one quote resets it. A tick with an
    empty watchlist touches the source not at all and counts as neither -- there is nothing to be
    healthy or unhealthy about.
    """
    global _effective, _ticks, _consecutive_failures, _last_snapshot_at, _market_state

    targets = _watch_targets(cfg)
    with _state_lock:
        _effective = tuple(targets)
    if not targets:
        logger.debug("livefeed: nothing to keep warm this tick")
        return

    try:
        snap = source(cfg).snapshot(targets)
    except Exception:
        logger.exception("livefeed: keep-warm snapshot failed for %d symbol(s)", len(targets))
        with _state_lock:
            _ticks += 1
            _consecutive_failures += 1
        return

    with _state_lock:
        _ticks += 1
        _last_snapshot_at = snap.as_of
        _market_state = snap.market_state
        if snap.quotes:
            _consecutive_failures = 0
        else:
            _consecutive_failures += 1
            logger.warning(
                "livefeed: keep-warm tick produced no quotes at all for %d watched symbol(s) "
                "(%d consecutive)",
                len(targets),
                _consecutive_failures,
            )


def _daemon_loop(cfg: Settings, stop_event: threading.Event, keepalive_seconds: float) -> None:
    """Tick, then sleep, until stopped. Ticks first so `start()` warms the watchlist immediately
    rather than after one full keepalive interval of nothing."""
    logger.info(
        "livefeed: keep-warm daemon started, re-subscribing every %.0fs (transport %s)",
        keepalive_seconds,
        cfg.paperlive_transport,
    )
    while not stop_event.is_set():
        _tick(cfg)
        _sleep_checking_stop(stop_event, keepalive_seconds)
    logger.info("livefeed: keep-warm daemon stopped")


def start(settings: Settings) -> None:
    """Launch the keep-warm daemon, or do nothing (and say so) when it is switched off.

    Called unconditionally from `app.main.lifespan`, with the "should this do anything" decision
    living here rather than at the call site -- the same shape as `app.workflow.loop.start` and
    `app.market.social_history.start_scheduler`. A second call while a daemon is already alive is a
    logged no-op, not an error: two daemons would poll the same source twice on independent
    schedules, which buys nothing and costs double.
    """
    global _thread, _stop_event, _settings, _started_at

    with _state_lock:
        # Recorded even when disabled, so `status()` reports the flags this process was actually
        # started with rather than whatever `get_settings()` happens to answer later.
        _settings = settings

        if not settings.livefeed_enabled:
            logger.info("livefeed: disabled (livefeed_enabled=False); keep-warm daemon not started")
            return

        if _thread is not None and _thread.is_alive():
            logger.info("livefeed: keep-warm daemon already running; not starting a second one")
            return

        stop_event = threading.Event()
        thread = threading.Thread(
            target=_daemon_loop,
            args=(settings, stop_event, settings.livefeed_keepalive_seconds),
            daemon=True,
            name="livefeed-keepalive",
        )
        _stop_event = stop_event
        _thread = thread
        _started_at = dt.datetime.now(dt.UTC)
        thread.start()


def stop(*, timeout: float = 5.0) -> None:
    """Signal the daemon to stop and join it, up to `timeout` seconds. A no-op if none is running.

    The stop takes effect at the next sleep slice (`_SLEEP_SLICE_SECONDS`) or when the tick in flight
    returns, whichever is later; a tick is not interrupted, since abandoning a snapshot mid-flight
    would leave the source's bookkeeping half-updated for no benefit at shutdown.
    """
    global _thread, _stop_event, _started_at

    with _state_lock:
        thread = _thread
        stop_event = _stop_event

    if thread is None or stop_event is None:
        return

    stop_event.set()
    thread.join(timeout=timeout)
    if thread.is_alive():
        logger.warning("livefeed: keep-warm daemon did not stop within %.1fs", timeout)

    with _state_lock:
        if _thread is thread:
            _thread = None
            _stop_event = None
            _started_at = None


def reset() -> None:
    """Drop the singleton, the watchlist and every scrap of daemon state. **For tests.**

    Production never calls this: the source lives for the process, exactly as `app.market.refresh`'s
    own module state does. A test calls it between cases so one case's fake source, watchlist or
    failure streak cannot be observed by the next.
    """
    global _source_instance, _effective, _settings, _started_at
    global _last_snapshot_at, _market_state, _ticks, _consecutive_failures

    stop()

    with _source_lock:
        instance = _source_instance
        _source_instance = None
    if instance is not None:
        try:
            instance.close()
        except Exception:  # pragma: no cover - a close that fails must not fail the reset
            logger.exception("livefeed: closing the live-quote source failed")

    with _state_lock:
        _manual.clear()
        _effective = ()
        _settings = None
        _started_at = None
        _last_snapshot_at = None
        _market_state = None
        _ticks = 0
        _consecutive_failures = 0


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def status() -> dict[str, Any]:
    """A JSON-ready view of the feed, for the data-admin API and anything else that has to answer
    "is the live feed actually working".

    **Never builds the source and never reads the ledger.** Both would turn a status call into real
    work -- a provider client constructed, a SQLite file opened -- which is exactly wrong for the
    endpoint whose job is to report on a subsystem that may be deliberately switched off. So
    `healthy` is `None` until the daemon has ticked at least once against a source that exists, and
    `symbols` reports the watchlist as of the last tick (plus any `watch()` additions), not a
    freshly-derived one.

    The keys are a pinned contract -- `app.market.freshness` and `app.api.data_admin` are written
    against exactly these nine:

    * `enabled` -- `Settings.livefeed_enabled`, i.e. whether the daemon is allowed to run at all.
    * `transport` -- `Settings.paperlive_transport` (`"poll"` / `"stream"`), the configured choice.
      Not the transport a given snapshot actually used: a `"stream"` source that has fallen back
      reports `"poll"` on its own snapshots, and that is a per-snapshot fact, not a setting.
    * `running` -- the daemon thread is alive.
    * `healthy` -- `None` before the first tick; otherwise the source's own health **and** this
      daemon's (see the module docstring on why "running" is not "working").
    * `watched` / `symbols` -- how many, and which.
    * `market_state` / `last_snapshot_at` -- from the most recent successful tick; `None` before one.
    * `started_at` -- when the daemon thread was launched, ISO-8601 UTC; `None` when it is not
      running.
    """
    with _state_lock:
        cfg = _settings
        thread = _thread
        symbols = sorted(set(_effective) | _manual)
        ticks = _ticks
        failures = _consecutive_failures
        last_snapshot_at = _last_snapshot_at
        market_state = _market_state
        started_at = _started_at

    with _source_lock:
        instance = _source_instance

    healthy: bool | None = None
    if ticks > 0 and instance is not None:
        reported = getattr(instance, "healthy", None)
        if isinstance(reported, bool):
            healthy = reported and failures < _UNHEALTHY_AFTER_TICKS

    settings = cfg if cfg is not None else get_settings()
    return {
        "enabled": bool(settings.livefeed_enabled),
        "transport": settings.paperlive_transport,
        "running": thread is not None and thread.is_alive(),
        "healthy": healthy,
        "watched": len(symbols),
        "symbols": symbols,
        "market_state": market_state,
        "last_snapshot_at": last_snapshot_at.isoformat() if last_snapshot_at is not None else None,
        "started_at": started_at.isoformat() if started_at is not None else None,
    }

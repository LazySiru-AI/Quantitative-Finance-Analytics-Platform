"""The manager desk's opt-in daily-brief autopilot: an in-process daemon that, once a day near market
open, produces one `window="yesterday"` brief with nobody in the loop.

**In-process only -- never a detached scheduler.** This mirrors `app.workflow.loop`'s own precedent,
recorded in that module's docstring from `strategy-program/DEFECTS.md` D3: a round launched detached
from a shell script had no completion signal, was killed by name rather than through its own
cancellation path, and fought a zombie for a lock on the next run. A scheduled brief is worse in one
concrete way that precedent did not have to deal with -- `app.manager.service.run_scheduled_brief`
commissions child research (`app.manager.pipeline`'s `commission` stage can spawn its own subprocess
work), and a detached parent scheduler crashes outright when it tries to spawn that child (see
`strategy-program/tools/phase_b_daily.cmd`, cited by `Settings.manager_autopilot_enabled`'s own
docstring). So this daemon is a `threading.Thread(daemon=True)` living inside the same server process
that already owns the manager desk's on-demand endpoints, started from `app.main`'s lifespan, never a
Task Scheduler / cron entry that execs a fresh interpreter once a day.

**Off by default -- this spends tokens unattended.** `Settings.manager_autopilot_enabled` gates
`start()`: several grounded model calls happen once a day with no person confirming any single run,
the same shape `workflow_autopilot` and `persona_trader_enabled` already use for the same reason. A
deployment that only wants the on-demand `/manager/brief` endpoint (a person clicking a button) never
needs this flag at all -- those endpoints work regardless of it.

**No brief logic lives here.** Every real decision -- what to collect, what changed, what to
research, what the brief says -- lives in `app.manager.service.run_scheduled_brief` and the pipeline
it calls. This module's whole job is to call that one function, once a day, at
`Settings.manager_brief_time_et`, and to keep calling it on schedule even when one day's call raises.
Exactly `app.workflow.loop`'s own rule ("no trading logic in the loop"), restated for this desk: no
brief logic in the loop, it only schedules.

**`service.run_scheduled_brief` is imported lazily, inside `run_once`.** `app.manager.service` is the
orchestrator's module, not this one's, and importing it at module load time would risk a circular
import the moment `service` (or anything it transitively imports) ever needs something from
`app.manager.loop` -- the same reason `app.personas.trader_loop._sweep` imports `app.personas.service`
and `app.personas.trader_service` inside the function rather than at the top of the file. A lazy
import also means a test can monkeypatch `app.manager.service.run_scheduled_brief` freely without this
module having already bound its own name to the pre-patch function object.

**`run_once` takes `today` as a parameter and never reads the wall clock itself** -- copied from
`app.workflow.loop.run_once`'s own discipline. The daemon's clock lives in `_daemon_loop`/
`_next_wake_at`, not here, so a test can call `run_once` directly and get a deterministic result.

**A failing day must not kill the daemon, but a long streak of them must be loud.** `_run_once_safely`
catches everything `run_once` raises, logs it, and returns without re-raising, so `_daemon_loop` moves
on to tomorrow. `_MAX_CONSECUTIVE_FAILURES` mirrors `app.workflow.loop`'s own constant (itself citing
`app.evolution.loop`'s 1,644-failures-reported-as-ordinary incident): the daemon never stops on a
streak, but logs at `logging.ERROR` once it reaches that streak length, so a systemic fault cannot
scroll out of a bounded log unnoticed.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from collections.abc import Callable
from zoneinfo import ZoneInfo

from app.config import Settings, get_settings

__all__ = ["run_once", "start", "stop"]

logger = logging.getLogger(__name__)

_EASTERN = ZoneInfo("America/New_York")

#: How many *consecutive* failed `run_once` calls the daemon tolerates before it starts logging the
#: streak at `logging.ERROR` instead of `logging.WARNING`. Mirrors `app.workflow.loop.
#: _MAX_CONSECUTIVE_FAILURES` -- see the module docstring's own paragraph on why "must not kill the
#: daemon" and "must be loud" are both true at once.
_MAX_CONSECUTIVE_FAILURES = 5

#: Slice length for the interruptible sleep -- short enough that `stop()` takes effect within a second
#: or two of being called even during an overnight wait. Mirrors `app.workflow.loop._SLEEP_SLICE_SECONDS`.
_SLEEP_SLICE_SECONDS = 1.0

_singleton_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None


def run_once(settings: Settings, *, today: dt.date | None = None) -> None:
    """One day's autopilot work: produce one `window="yesterday"` brief via
    `app.manager.service.run_scheduled_brief`. The unit-testable core the daemon below schedules.

    `today` is accepted for the same reason `app.workflow.loop.run_once` accepts it -- so a caller
    (a test, or a future backfill) can drive this deterministically -- but this function itself never
    reads or branches on the wall clock; it exists purely so this signature matches that discipline
    and stays available should `run_scheduled_brief` ever want an explicit date. Imports
    `app.manager.service` lazily (see the module docstring) so this module can be imported at server
    startup with no risk of a circular import, and so a test can monkeypatch
    `app.manager.service.run_scheduled_brief` after this module is already loaded.
    """
    from app.manager import service

    # `run_scheduled_brief` is owned by `app.manager.service` and imported lazily here (see the module
    # docstring) so this daemon carries no brief logic and a test can monkeypatch it freely.
    service.run_scheduled_brief(settings)


def _run_once_safely(
    settings: Settings,
    *,
    today: dt.date | None = None,
    run_once_fn: Callable[..., None] = run_once,
) -> bool:
    """`run_once_fn(settings, today=today)`, with any exception it raises caught and logged.

    Returns `True` on success, `False` on a caught failure -- the one-day wrapper `_daemon_loop`
    actually calls, so a single bad day never reaches the daemon's own `while` loop and stops it. See
    the module docstring's "must not kill the daemon" paragraph. `run_once_fn` is injectable so a test
    can exercise this wrapper's own catch-and-continue behaviour against a fake that always raises,
    without needing a real failure inside `run_once` itself to trigger it.
    """
    try:
        run_once_fn(settings, today=today)
        return True
    except Exception:
        logger.exception("manager autopilot: run_once failed for %s", today or dt.date.today())
        return False


def _parse_wake_time(value: str) -> dt.time:
    """Parse `Settings.manager_brief_time_et`'s `HH:MM` string into a `dt.time`.

    Falls back to the field's own default (`09:45`) on a malformed value rather than raising out of
    `_daemon_loop` -- a typo'd override must not crash the daemon before it ever gets to run a brief.
    """
    try:
        hour_str, minute_str = value.split(":", 1)
        return dt.time(int(hour_str), int(minute_str))
    except (ValueError, TypeError):
        logger.warning(
            "manager autopilot: manager_brief_time_et=%r is not HH:MM; falling back to 09:45", value
        )
        return dt.time(9, 45)


def _next_wake_at(now_et: dt.datetime, wake_time: dt.time) -> dt.datetime:
    """The next moment at or after `now_et` whose time-of-day is `wake_time`, in `now_et`'s own
    timezone. Strictly *after* `now_et` when `now_et` already sits exactly on `wake_time`. Copied from
    `app.workflow.loop._next_wake_at`."""
    candidate = now_et.replace(
        hour=wake_time.hour, minute=wake_time.minute, second=0, microsecond=0
    )
    if candidate <= now_et:
        candidate += dt.timedelta(days=1)
    return candidate


def _sleep_checking_stop(
    stop_event: threading.Event, seconds: float, *, interval: float = _SLEEP_SLICE_SECONDS
) -> None:
    """Sleep up to `seconds`, in slices, returning early the moment `stop_event` is set. Copied from
    `app.workflow.loop._sleep_checking_stop`."""
    deadline = time.monotonic() + max(seconds, 0.0)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or stop_event.is_set():
            return
        time.sleep(min(interval, remaining))


def _daemon_loop(
    settings: Settings,
    stop_event: threading.Event,
    *,
    run_once_fn: Callable[..., None] = run_once,
) -> None:
    """Wake once a day at `settings.manager_brief_time_et` (Eastern time), run one day's autopilot
    step through `_run_once_safely`, and sleep-checking-stop until the next wake -- forever, until
    `stop_event` is set.

    Not part of this module's `__all__` and not normally called directly outside `start`; a test
    drives it with a short-lived `stop_event` and a fake `run_once_fn` rather than waiting for a real
    overnight sleep.
    """
    wake_time = _parse_wake_time(settings.manager_brief_time_et)
    logger.info("manager autopilot: daemon started, waking daily at %s ET", wake_time)
    consecutive_failures = 0

    while not stop_event.is_set():
        now_et = dt.datetime.now(_EASTERN)
        wake_at = _next_wake_at(now_et, wake_time)
        _sleep_checking_stop(stop_event, (wake_at - now_et).total_seconds())
        if stop_event.is_set():
            break

        today = dt.datetime.now(_EASTERN).date()
        ok = _run_once_safely(settings, today=today, run_once_fn=run_once_fn)

        if not ok:
            consecutive_failures += 1
            level = logging.ERROR if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES else logging.WARNING
            logger.log(
                level,
                "manager autopilot: %d consecutive run_once failures as of %s%s",
                consecutive_failures,
                today,
                (
                    " -- this needs attention; the daemon keeps retrying daily so it can catch back "
                    "up once the fault clears, but it is not making progress"
                    if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES
                    else ""
                ),
            )
        else:
            consecutive_failures = 0
            logger.info("manager autopilot: brief produced for %s", today)

    logger.info("manager autopilot: daemon stopped")


def start(settings: Settings | None = None) -> threading.Event | None:
    """Launch the daemon thread, or do nothing when `settings.manager_autopilot_enabled` is off.

    Returns the `threading.Event` that stops the loop (for a caller that wants to join it), or `None`
    when the feature is disabled -- mirroring `app.personas.trader_loop.start`'s own return contract.
    Idempotent: a second call while a loop is already running in this process returns the existing
    event rather than starting a second daemon (two daemons independently calling
    `run_scheduled_brief` on the same schedule would be redundant spend, not redundancy that helps
    anything).
    """
    global _thread, _stop_event

    cfg = settings or get_settings()
    if not cfg.manager_autopilot_enabled:
        logger.info("manager autopilot: disabled (manager_autopilot_enabled=False); not starting")
        return None

    with _singleton_lock:
        if _thread is not None and _thread.is_alive():
            logger.info("manager autopilot: already running in this process; not starting a second one")
            return _stop_event

        stop_event = threading.Event()
        thread = threading.Thread(
            target=_daemon_loop,
            args=(cfg, stop_event),
            daemon=True,
            name="manager-brief",
        )
        _stop_event = stop_event
        _thread = thread
        thread.start()
        return stop_event


def stop(*, timeout: float = 5.0) -> None:
    """Signal the running daemon to stop and join it, up to `timeout` seconds.

    A no-op when no daemon is running (never started, or `manager_autopilot_enabled` was `False` at
    `start` time). `timeout` bounds how long this blocks the caller -- `stop_event.set()` takes effect
    at the daemon's next sleep-slice boundary (at most `_SLEEP_SLICE_SECONDS`) or the moment its
    current `run_once` call returns, whichever is later.
    """
    global _thread, _stop_event

    with _singleton_lock:
        thread = _thread
        stop_event = _stop_event

    if thread is None or stop_event is None:
        return

    stop_event.set()
    thread.join(timeout=timeout)

    with _singleton_lock:
        if _thread is thread:
            _thread = None
            _stop_event = None

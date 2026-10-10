"""The Agent Workflow desk's daily-cadence autopilot: an optional in-process daemon that, once a day
near the market open, fills yesterday's staged workflow orders and resolves matured candidate
observations -- with no person in the loop.

**Why an in-process daemon thread, not a subprocess -- exactly `app.evolution.loop`'s own precedent.**
That module's docstring recounts `strategy-program/DEFECTS.md` D3 in full: a round launched detached
from a shell script had no completion signal, was killed by name rather than through its own
cancellation path, and a second run then fought the zombie for the DuckDB lock -- 135 card-runs, zero
results, recorded as ordinary failures. A daemon that wakes once a day, forever, for the life of the
server process is exactly the same shape of long-lived background work, so it gets the same answer:
`threading.Thread(daemon=True)`, a `threading.Event` a caller can actually set, and a
`_sleep_checking_stop`-style wait that never blocks on a bare `time.sleep` a stop request cannot
interrupt. `start`/`stop` below are deliberately thin next to `app.evolution.loop`'s own `start_loop`/
`stop_loop` -- this daemon carries no generations, no ledger, no promotion gate, just "did today's step
run yet" -- but the threading shape is copied on purpose, not reinvented.

**No trading logic lives here.** Every real decision -- what to fill, at what price, whether an order
is due, which candidate observations have matured enough to price -- already exists in
`app.workflow.book.execute_pending` and `app.workflow.candidates.resolve_pending`. This module's whole
job is to call those, once a day, for every arm, and to keep calling them on schedule even when one
day's call raises. See `run_once` for the actual work and `_run_once_safely`/`_daemon_loop` for the
schedule wrapped around it.

**`run_once` takes `today` as a parameter, never reads the wall clock itself.** The daemon's own clock
lives in `_daemon_loop`/`_next_wake_at`, not in `run_once` -- so a test can call `run_once` directly
with a fixed date and get a deterministic result, and the one call to `dt.date.today()` a real
(non-test) invocation needs happens at the daemon's own call site, not buried inside the logic under
test. This is the same discipline `app.workflow.book.execute_pending` and `app.workflow.candidates.
resolve_pending` already apply to their own `today` parameters -- this module keeps it going one layer
up rather than breaking it at the first caller that happens to run on a schedule.

**A failing day must not kill the daemon -- but an unbroken run of them must be loud, not silent.**
`_run_once_safely` catches everything `run_once` raises, logs it, and returns `None` so `_daemon_loop`
can move on to tomorrow -- a single bad day (a transient market-data gap, one unpriceable symbol) must
not stop an autopilot that is otherwise working. But "designed to continue" is not the same claim as
"working": a loop that keeps sleeping and retrying forever while doing nothing useful, reporting
nothing, is indistinguishable from a healthy one to anyone not reading its logs line by line -- see
`app.evolution.loop`'s own `_MAX_CONSECUTIVE_FAILURES` for the incident (1,644 identical failures,
reported as ordinary, one after another) this same shape exists to catch one layer up. `_daemon_loop`
tracks *consecutive* `run_once` failures and logs loudly, at `logging.ERROR`, once the streak reaches
`_MAX_CONSECUTIVE_FAILURES` -- and again on every failure past it, so the condition cannot scroll out of
a bounded log unnoticed. It does not stop the daemon: an autopilot that quietly stops autopiloting the
moment a systemic fault appears is its own silent failure, and the daemon's entire reason to exist is to
keep trying to catch back up once the fault clears (see `execute_pending`'s own "catch-up" semantics --
a stale order stays fillable indefinitely, off its own original `fill_date`'s stored open).

**Live quote source: `None`, deliberately.** `execute_pending`'s `live_quote_source` lets a fill price
against `app.market.live` when today's own open bar is not stored yet. Wiring a real one in here would
mean the daemon owning a `LiveQuoteSource`'s own background polling machinery for a call that runs once
a day -- a second, independent lifecycle this module would then have to start and tear down correctly,
for a benefit `execute_pending`'s own "catch-up" semantics already make optional: an order whose fill
date's open is not stored yet simply stays `"pending"` and fills off that same date's stored open the
next time `run_once` runs, exactly like an order two sessions stale from the app not running that
morning. `run_once` passes `live_quote_source=None` and relies entirely on this catch-up path -- a
deployment that wants same-day live fills instead can wire a real source in by calling
`app.workflow.book.execute_pending` directly, outside this daemon.

**Mandate: `app.paper.mandate.default_mandate`, matching `app.api.workflow`'s own `/book/execute`.**
That router's endpoint is the one other caller that fills workflow orders, and a different mandate
here would size and gate this daemon's fills under different cash/position/clip rules than a person
clicking the same button in the UI -- making the two paths for "fill the workflow books" silently
disagree about what counts as a valid order. It is the code-defined default rather than a
`uat/personas/*.json` read on purpose: served code must not depend on a tree the container does not
ship, which `tests/test_deployment_paths.py` enforces -- the paper desk uses `default_mandate` for
the same reason.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal
from zoneinfo import ZoneInfo

from app.config import Settings
from app.paper.mandate import default_mandate
from app.workflow import book as book_mod
from app.workflow import candidates
from app.workflow import exits as exits_mod
from app.workflow.book_models import WorkflowArm
from app.workflow.pipeline import ALL_ARMS, STARTING_CASH

__all__ = [
    "ExecuteSummary",
    "run_once",
    "start",
    "stop",
]

logger = logging.getLogger(__name__)

#: US market open, Eastern time. The daemon wakes a few minutes after the open rather than exactly at
#: it so the first minute's own regular-session bars have a moment to exist upstream before anything
#: tries to catch up against them -- not that `run_once` needs same-day bars at all (see the module
#: docstring's "Live quote source" section), but there is no reason to race the open when nothing here
#: is time-sensitive at the minute scale.
_DEFAULT_WAKE_TIME_ET = dt.time(9, 35)

_EASTERN = ZoneInfo("America/New_York")

#: How many *consecutive* failed `run_once` calls the daemon tolerates before it starts logging the
#: streak at `logging.ERROR` instead of `logging.WARNING`. Mirrors `app.evolution.loop.
#: _MAX_CONSECUTIVE_FAILURES`'s own module constant and the incident it documents (1,644 identical,
#: silently-tolerated failures) -- the daemon itself never stops on this (see the module docstring's
#: own paragraph on why "must not kill the daemon" and "must be loud" are both true at once), only its
#: log level does.
_MAX_CONSECUTIVE_FAILURES = 5

#: Slice length for the interruptible sleep -- short enough that `stop()` takes effect within a second
#: of being called even during an overnight wait, matching `app.evolution.loop._sleep_checking_stop`'s
#: own `interval` default in spirit (that one is tuned for a sub-second test; a daily cadence can afford
#: a full second per slice without costing a test suite anything noticeable).
_SLEEP_SLICE_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class ExecuteSummary:
    """What one `run_once` call did, across every workflow arm -- returned for a caller (a log line, a
    future status endpoint) to inspect, not persisted anywhere itself. The durable record is each
    arm's own `BookState`, already written to disk by `run_once` before this is returned."""

    today: dt.date
    observations_resolved: int
    """`app.workflow.candidates.resolve_pending`'s own return value: how many matured candidate
    observations were priced this call."""

    filled: int
    rejected: int
    still_pending: int
    stored_open_fills: int
    live_quote_fills: int
    """Summed across every arm in `app.workflow.pipeline.ALL_ARMS` -- see `per_arm` below for the
    same figures broken out one arm at a time. The `filled`/`rejected` totals also fold in the
    screen-mode books' fills (see `run_once`), which `per_arm` does not break out."""

    exits_staged: int = 0
    """Sell orders this call staged across every book, card- and screen-mode, from the strategy
    cards' own mechanical exit rules (`app.workflow.exits`). Zero on any day nothing's stop, target,
    hold cap or exit rule fired -- the ordinary case, and not a failure. Defaulted so a caller that
    predates the exit path still constructs an `ExecuteSummary` unchanged."""

    per_arm: Mapping[WorkflowArm, book_mod.ExecuteOutcome] = field(default_factory=dict)
    """Each arm's own `ExecuteOutcome`, keyed by arm -- everything the summed totals above collapse
    together, still available to a caller that wants to know which arm actually did something today."""


def run_once(settings: Settings, *, today: dt.date | None = None) -> ExecuteSummary:
    """One day's autopilot work: resolve matured candidate observations, then fill every workflow
    arm's due pending orders. The unit-testable core the daemon below schedules.

    **Order matters, but only slightly.** `candidates.resolve_pending` prices observations off the
    stored bar store and never reads or writes a workflow book, so running it before or after the
    per-arm fill loop cannot change either one's result -- it runs first here simply so `ExecuteSummary`
    can report `observations_resolved` first, matching the order this docstring describes the day's
    work in.

    **Never touches the network.** `resolve_pending` reads only the stored bar store;
    `execute_pending` is called with `live_quote_source=None` (see the module docstring's "Live quote
    source" section), so every fill this function ever produces is priced off a stored open, never a
    live quote. A caller that wants same-day live fills is calling the wrong function -- see that same
    docstring section for where those belong instead.

    Loads, executes and saves each arm's book independently: one arm whose book fails to save (a full
    disk, a permissions error) does not stop `execute_pending` from having already been attempted for
    the arms before it in `ALL_ARMS`, nor does it prevent the arms after it from being attempted too --
    each arm's `save_book` call can raise on its own, and if it does, this function lets that exception
    propagate exactly as it arose rather than swallowing it, since a caller (`_run_once_safely` below,
    in the daemon's own case) is what decides whether a failed day is tolerable, not this function.
    """
    as_of = today if today is not None else dt.date.today()

    observations_resolved = candidates.resolve_pending(settings=settings, today=as_of)

    mandate = default_mandate(starting_cash=STARTING_CASH)

    filled = rejected = still_pending = 0
    stored_open_fills = live_quote_fills = exits_staged = 0
    per_arm: dict[WorkflowArm, book_mod.ExecuteOutcome] = {}

    def _step_book(arm: WorkflowArm, source: Literal["card", "screen"]) -> book_mod.ExecuteOutcome:
        """One book's whole day, in order: fill what is due, decide new exits on the resulting
        holdings, mark equity, save. Returns the fill outcome and accumulates the shared counters.

        **Fill first, then decide exits.** A stop that would fire today is decided against today's
        close, *after* today's due orders have filled -- so a position bought this morning is in the
        book its own exit is evaluated against, and an exit decided today fills at the next open, one
        session later, exactly as a buy does. Reversing the two would decide exits against yesterday's
        book and miss a same-day entry entirely."""
        nonlocal exits_staged
        book = book_mod.load_book(
            settings, arm, starting_cash=STARTING_CASH, card_id="", universe_source=source
        )
        book, outcome = book_mod.execute_pending(
            book, settings=settings, mandate=mandate, live_quote_source=None, today=as_of
        )
        book, decisions = exits_mod.stage_due_exits(
            book, settings=settings, today=as_of, allow_fractional=mandate.allow_fractional_shares
        )
        exits_staged += sum(1 for d in decisions if d.reason in ("stop", "target", "time", "rule"))
        try:
            book = book_mod.mark_equity_through(
                book, settings=settings, mandate=mandate, through=as_of
            )
        except Exception:
            logger.warning(
                "workflow autopilot: equity marking failed for %s/%s through %s; saving fills "
                "without it",
                arm, source, as_of, exc_info=True,
            )
        book_mod.save_book(settings, book)
        return outcome

    def _accumulate(outcome: book_mod.ExecuteOutcome) -> None:
        nonlocal filled, rejected, still_pending, stored_open_fills, live_quote_fills
        filled += outcome.filled
        rejected += outcome.rejected
        still_pending += outcome.still_pending
        stored_open_fills += outcome.stored_open_fills
        live_quote_fills += outcome.live_quote_fills

    # Card-mode books: all four arms, always present (seeded on first read). `per_arm` is keyed by
    # these and by these alone, unchanged, so every existing reader of it keeps meaning what it did.
    for arm in ALL_ARMS:
        outcome = _step_book(arm, "card")
        per_arm[arm] = outcome
        _accumulate(outcome)

    # Screen-mode books: only the ones a dynamic-universe (Phase B) study has actually written. A
    # deployment that has never run one has no screen files and this loop does nothing -- the daemon
    # then behaves exactly as it did before it learned to fill them. Folded into the summed totals
    # (and the exits counter) but deliberately not into `per_arm`, whose arm keys cannot distinguish
    # a card book from a screen book of the same arm without becoming a `(arm, source)` map its
    # existing consumers are not written for.
    for arm in ALL_ARMS:
        if book_mod.book_path(settings, arm, universe_source="screen").is_file():
            _accumulate(_step_book(arm, "screen"))

    return ExecuteSummary(
        today=as_of,
        observations_resolved=observations_resolved,
        filled=filled,
        rejected=rejected,
        still_pending=still_pending,
        stored_open_fills=stored_open_fills,
        live_quote_fills=live_quote_fills,
        exits_staged=exits_staged,
        per_arm=per_arm,
    )


def _run_once_safely(
    settings: Settings,
    *,
    today: dt.date | None = None,
    run_once_fn: Callable[..., ExecuteSummary] = run_once,
) -> ExecuteSummary | None:
    """`run_once_fn(settings, today=today)`, with any exception it raises caught, logged, and turned
    into `None` rather than propagated.

    The one-day wrapper `_daemon_loop` actually calls, so a single bad day never reaches the daemon's
    own `while` loop and stops it -- see the module docstring's "must not kill the daemon" paragraph.
    `run_once_fn` is injectable so a test can exercise this wrapper's own catch-and-continue behaviour
    against a fake that always raises, without needing a real failure inside `run_once` itself to
    trigger it.
    """
    try:
        return run_once_fn(settings, today=today)
    except Exception:
        logger.exception("workflow autopilot: run_once failed for %s", today or dt.date.today())
        return None


def _next_wake_at(now_et: dt.datetime, wake_time: dt.time) -> dt.datetime:
    """The next moment at or after `now_et` whose time-of-day is `wake_time`, in `now_et`'s own
    timezone.

    Strictly *after* `now_et` when `now_et` already sits exactly on `wake_time` -- a daemon that woke
    at 09:35:00.000000 sharp, ran `run_once`, and came back to compute its next wake before the clock
    had visibly moved must not immediately re-wake for the same day it just finished; see
    `_daemon_loop` for why this can only happen right after a run, never mid-sleep.
    """
    candidate = now_et.replace(
        hour=wake_time.hour, minute=wake_time.minute, second=0, microsecond=0
    )
    if candidate <= now_et:
        candidate += dt.timedelta(days=1)
    return candidate


def _sleep_checking_stop(
    stop_event: threading.Event, seconds: float, *, interval: float = _SLEEP_SLICE_SECONDS
) -> None:
    """Sleep up to `seconds`, in slices, returning early the moment `stop_event` is set.

    Copied in shape from `app.evolution.loop._sleep_checking_stop` -- see that function's own
    docstring for why this is never a bare `time.sleep(seconds)` (a stop requested mid-wait must take
    effect at the next slice boundary, potentially an overnight wait away otherwise) and never a bare
    spin loop either (that would burn a CPU core for the entire wait).
    """
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
    wake_time: dt.time = _DEFAULT_WAKE_TIME_ET,
    run_once_fn: Callable[..., ExecuteSummary] = run_once,
) -> None:
    """Wake once a day at `wake_time` (Eastern time), run one day's autopilot step through
    `_run_once_safely`, and sleep-checking-stop until the next wake -- forever, until `stop_event` is
    set.

    Not part of this module's `__all__` and not normally called directly outside `start`; a test drives
    it with a short-lived `stop_event` and a fake `run_once_fn` rather than waiting for a real overnight
    sleep. `wake_time`/`run_once_fn` are both injectable for exactly that reason -- see the module
    docstring's paragraph on `run_once` never reading the wall clock itself; this function is where that
    clock actually lives for a real (non-test) run.
    """
    logger.info("workflow autopilot: daemon started, waking daily at %s ET", wake_time)
    consecutive_failures = 0

    while not stop_event.is_set():
        now_et = dt.datetime.now(_EASTERN)
        wake_at = _next_wake_at(now_et, wake_time)
        _sleep_checking_stop(stop_event, (wake_at - now_et).total_seconds())
        if stop_event.is_set():
            break

        today = dt.datetime.now(_EASTERN).date()
        summary = _run_once_safely(settings, today=today, run_once_fn=run_once_fn)

        if summary is None:
            consecutive_failures += 1
            level = logging.ERROR if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES else logging.WARNING
            logger.log(
                level,
                "workflow autopilot: %d consecutive run_once failures as of %s%s",
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
            logger.info(
                "workflow autopilot: %s -- filled=%d rejected=%d still_pending=%d "
                "observations_resolved=%d",
                summary.today,
                summary.filled,
                summary.rejected,
                summary.still_pending,
                summary.observations_resolved,
            )

    logger.info("workflow autopilot: daemon stopped")


# ---------------------------------------------------------------------------
# Public API -- a process-wide singleton, mirroring app.evolution.loop's "at most one" rule
# ---------------------------------------------------------------------------

_singleton_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None


def start(settings: Settings) -> None:
    """Launch the daemon thread and return immediately -- a no-op, logged, when
    `settings.workflow_autopilot` is not set, and a no-op, logged, when a daemon is already running in
    this process.

    Called from `app.main.lifespan` exactly the way `app.market.social_history.start_scheduler` and
    `app.paperdesk.desk.warm` already are: unconditionally at the call site, with the "should this
    actually do anything" check living inside the function itself rather than at the caller -- see
    `Settings.workflow_autopilot`'s own docstring for why the flag defaults `False`.

    **At most one daemon, process-wide.** A second `start` call while one is already running would mint
    a second thread independently calling `run_once` on its own schedule against the same books on
    disk -- two writers racing `save_book` for the same file is not "twice the autopiloting", it is a
    lost update. Unlike `app.evolution.loop.start_loop`, which raises `LoopAlreadyRunning` for the
    analogous case, this is a silent no-op: `lifespan` calls this once per server start and has no
    branch that would call it twice on purpose, so a raised exception here would only ever fire from a
    caller bug, and a log line is enough to make that bug visible without turning an idempotent
    "autopilot is already running, which is what you asked for" into a startup-time crash.
    """
    global _thread, _stop_event

    if not settings.workflow_autopilot:
        logger.info("workflow autopilot: disabled (workflow_autopilot=False); not starting")
        return

    with _singleton_lock:
        if _thread is not None and _thread.is_alive():
            logger.info("workflow autopilot: already running in this process; not starting a second one")
            return

        stop_event = threading.Event()
        thread = threading.Thread(
            target=_daemon_loop,
            args=(settings, stop_event),
            daemon=True,
            name="workflow-autopilot",
        )
        _stop_event = stop_event
        _thread = thread
        thread.start()


def stop(*, timeout: float = 5.0) -> None:
    """Signal the running daemon to stop and join it, up to `timeout` seconds.

    A no-op when no daemon is running (never started, or `settings.workflow_autopilot` was `False` at
    `start` time). `timeout` bounds how long this blocks the caller -- `stop_event.set()` takes effect
    at the daemon's next sleep-slice boundary (at most `_SLEEP_SLICE_SECONDS`) or the moment its current
    `run_once` call returns, whichever is later; a `run_once` call itself is not interrupted mid-flight,
    since a fill half-applied to a book is a worse state than a slow shutdown.
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

"""Run one generation of auto-proposed cards through the existing round machinery.

**What this module is, and is not.** `app.tournament.jobs` already knows how to run a round: resolve
a mandate, iterate `(window, card)` pairs, write a run file per pair, record a per-card failure and
walk past it, reconcile written files against attempted runs, and hold the engine's single execution
slot so no second reader ever collides with this one on the bar store (`strategy-program/DEFECTS.md`
D3). Every one of those decisions belongs to that module, not this one, and `run_generation` below
copies `app.tournament.jobs._worker`'s call convention line for line rather than inventing a second
opinion about any of them. What `_worker` cannot do is run an `app.tournament.allocation.
AllocationCard` -- it is wired to `_load_library_index`'s `StrategyCard`-only resolution and
`app.tournament.runner.run_card`'s `StrategyCard`-only signature -- and a searcher's generation needs
both shapes, because only an `AllocationCard` can express "mostly trend, a few percent semis, the
rest stability" (see `app.evolution.models.CardShape`'s own docstring). This module is the smallest
extension that runs both shapes through the same machinery, the same lock, and the same on-disk
convention, so a generation's run files are indistinguishable on disk from a hand-run round's.

**The lock, restated because it is the one invariant this module is not allowed to get wrong.**
`app.tournament.jobs.external_round_slot` is the same process-wide single-slot lock `POST
/api/competition/jobs` takes, reserved for a caller that is not `_worker` itself. `run_generation`
takes it once, for the whole generation, and every `(window, card)` pair in that generation runs
inside it -- never a second lock, never a second registry, never a caller that bypasses it. If
`external_round_slot` raises `JobAlreadyRunning` -- another round or another generation already holds
the slot -- this module does not retry, poll, or queue behind it. It propagates immediately, and the
caller (the evolution loop's supervisor) decides what "try again later" means; a spin loop here would
just move the polling into the one place that is supposed to be a hard boundary.

**Cards within a generation now run in parallel processes -- this does not reopen D3.** `max_workers`
(default `1`, fully serial) controls how many cards of the *same window* run at once, each in its own
OS process via `ProcessPoolExecutor`. D3 was two concurrent *rounds* -- two independent callers, each
believing it alone held the engine, racing each other's writes and reads against the shared DuckDB bar
store; the failure mode was that a colliding reader's `IOException` looked exactly like an ordinary
per-card failure, so a contended round silently reported an empty field as if it were a legitimately
ineligible one. `PROTOCOL.md` section 8 records that as closed *at the round level*: exactly one round
or generation may hold `external_round_slot` at a time, full stop, and that has not changed by one
line in this module. What is parallel here is strictly *inside* the single slot one generation already
holds: every worker process is reading the same read-only, already-synced bar store that a serial run
would have read anyway, through the exact same `AsOfMarket` / `app.paper.marketdata._FRAME_CACHE`
machinery (each worker just gets its own copy of that process-wide cache, one per OS process, the same
way the single-threaded case already gets exactly one). Nothing here writes to the bar store, nothing
here writes a run file except the parent process (see `_apply_outcome`), and nothing here changes how
many rounds/generations may be in flight at once -- still exactly one, enforced exactly as before.
Parallelism inside that one slot was always safe by the store's own read-only contract; D3 was never
about a single caller reading its own data on several threads or processes, it was about two callers
that did not know about each other at all. `max_workers > 1` cannot create a second such caller: it is
still one `external_round_slot` holder, spawning workers that answer only to it and write nothing
themselves.

**Card-shape dispatch, window-major scheduling, failure isolation and cancellation are described in
each helper's own docstring below** (`_execute_card`, `_run_window_serially`, `_run_window_in_pool`,
`_run_one_card_in_worker`, `_pool_initializer`) rather than repeated here.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import CancelledError, Future, ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal

from app.config import Settings
from app.paper.paperbroker import Mandate
from app.tournament import jobs
from app.tournament.allocation import AllocationCard, AllocationResult, run_allocation
from app.tournament.models import AgentResult, StrategyCard
from app.tournament.runner import run_card

__all__ = ["ExecutionReport", "run_generation"]


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    """What one call to `run_generation` did -- the evolution loop's own record of a generation's
    execution, independent of `app.tournament.jobs.JobStatus` (which is a live/polled snapshot, not a
    return value, and is keyed by `job_id` rather than by the caller's own `round_id`)."""

    round_id: str

    job_id: str | None
    """The `_Job.job_id` the run was reserved under, so a caller can still `GET
    /api/competition/jobs/{job_id}` (or `DELETE` it) while poking around, even though this module
    never itself calls `app.tournament.jobs.start_job`. `None` only if the slot was never acquired --
    which cannot happen for a normal return, since `external_round_slot`'s `JobAlreadyRunning` is left
    to propagate rather than caught -- so in practice this is always set on every `ExecutionReport`
    this function actually returns."""

    status: Literal["succeeded", "failed", "cancelled"]
    """`"failed"` is reserved for a failure that killed the *generation* -- the mandate would not
    load, or a window's `runs_dir` could not be created -- never for an individual card's failure,
    which is recorded in `errors`/`failed_runs` instead and does not stop the generation. Matches
    `app.tournament.jobs.JobStatus.error`'s identical contract."""

    windows: tuple[str, ...]
    """Every window this generation was asked to run, in request order -- not filtered down to the
    ones actually reached before a cancellation, matching `JobStatus.windows`'s own convention of
    reporting the request rather than the partial outcome."""

    completed_runs: int
    failed_runs: int

    errors: tuple[str, ...]
    """One line per failed `(window, card)` pair: `"[window] agent_id: ExceptionType: message"`.
    Empty on a clean run. Not the same list as a job-killing `error` -- see `status`'s docstring."""


def _emit_noop(_line: str) -> None:
    return None


# ---------------------------------------------------------------------------
# Per-card execution -- shared by the serial path and the in-worker path, so a card's own semantics
# (which engine it dispatches to, what counts as success/failure) cannot drift between max_workers=1
# and max_workers>1.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Outcome:
    """One card's finished run, in a form that can cross a process boundary (every field is a plain,
    picklable value -- no open file handles, no live `AsOfMarket`/`PaperBroker` state) and that
    carries everything `_apply_outcome` needs to write a run file and a `RunResult` without having to
    re-derive anything from a live `AgentResult`/`AllocationResult` object.

    `total_return`/`benchmark_return`/`excess`/`capital_exposure`/`trades` are computed once, here,
    by whichever process actually ran the card -- not recomputed by the parent from `result_json` --
    so there is exactly one place this arithmetic happens regardless of `max_workers`, matching
    `app.tournament.jobs.RunResult.total_return`'s own D1 rebasing note.
    """

    agent_id: str
    status: Literal["ok", "failed"]
    elapsed: float
    result_json: str | None = None
    total_return: Decimal | None = None
    benchmark_return: Decimal | None = None
    excess: Decimal | None = None
    capital_exposure: float | None = None
    trades: int | None = None
    error: str | None = None


def _outcome_from_result(
    agent_id: str, result: AgentResult | AllocationResult, elapsed: float
) -> _Outcome:
    # Same `total_return`/`excess` arithmetic `_worker` uses -- `ending_equity / starting_equity - 1`,
    # **not** `AgentResult.total_return`, for the D1 rebasing reason `RunResult.total_return`'s own
    # docstring gives. `AllocationResult` carries the identical `starting_equity`/`ending_equity`/
    # `benchmark_return` fields, so the same expression is correct for both card shapes without a
    # branch.
    total_return = result.ending_equity / result.starting_equity - Decimal(1)
    excess = (
        total_return - result.benchmark_return if result.benchmark_return is not None else None
    )
    return _Outcome(
        agent_id=agent_id,
        status="ok",
        elapsed=elapsed,
        result_json=result.model_dump_json(indent=2),
        total_return=total_return,
        benchmark_return=result.benchmark_return,
        excess=excess,
        capital_exposure=result.capital_exposure,
        trades=len(result.trades),
    )


def _outcome_from_exception(agent_id: str, exc: BaseException, elapsed: float) -> _Outcome:
    return _Outcome(
        agent_id=agent_id,
        status="failed",
        elapsed=elapsed,
        error=f"{type(exc).__name__}: {exc}",
    )


def _execute_card(
    card: StrategyCard | AllocationCard,
    *,
    settings: Settings,
    mandate: Mandate,
    start: dt.date,
    end: dt.date,
) -> _Outcome:
    """Run one card and turn it into an `_Outcome`, catching whatever it raises rather than letting
    it propagate -- recorded and walked past, exactly as `app.tournament.jobs._worker` does for a
    `StrategyCard`. `isinstance(card, AllocationCard)` selects `app.tournament.allocation.
    run_allocation`; everything else goes through `app.tournament.runner.run_card`. Both calls use the
    identical `settings=`/`mandate=`/`start=`/`end=` convention `_worker` uses, and both results are
    written with the identical `result.model_dump_json(indent=2)` call `_worker` uses (inside
    `_outcome_from_result`) -- see `app.tournament.results.parse_scored_run`/`_card_shape`, which
    dispatch on the written `"card"` payload's own keys, never on which function produced it.

    Called from two places: `_run_window_serially`, in this process, on the objects `run_generation`
    was given directly; and `_run_one_card_in_worker`, in a worker process, on a card rebuilt from
    JSON. Both call sites reference the module-level `run_card`/`run_allocation` names below by a bare
    lookup at call time (not a bound reference captured earlier), which is what lets
    `tests/test_evolution_execute.py` monkeypatch `execute.run_card`/`execute.run_allocation` and have
    the serial path pick the patched version up -- see that test file's fixtures. A worker process
    never sees that monkeypatch (it is a separate process with its own fresh import of this module),
    which is expected and is why every parallelism test in that file drives a genuine `run_card`/
    `run_allocation` call rather than a monkeypatched fake.
    """
    started = time.time()
    try:
        result: AgentResult | AllocationResult
        if isinstance(card, AllocationCard):
            result = run_allocation(card, settings=settings, mandate=mandate, start=start, end=end)
        else:
            result = run_card(card, settings=settings, mandate=mandate, start=start, end=end)
    except Exception as exc:  # recorded and walked past by the caller, exactly as `_worker` does
        return _outcome_from_exception(card.agent_id, exc, time.time() - started)
    return _outcome_from_result(card.agent_id, result, time.time() - started)


# ---------------------------------------------------------------------------
# The worker-process side of the process pool.
# ---------------------------------------------------------------------------


def _pool_initializer() -> None:
    """Runs once per worker process, before that worker is ever handed a card. Its only purpose is to
    pay the interpreter/import cost -- `app.tournament.runner` and `app.tournament.allocation` pull in
    pandas, duckdb and this application's whole model graph -- once per worker process, up front,
    rather than folded invisibly into whichever card happens to land on a fresh worker first. See
    `app.evolution.models.LoopConfig.max_workers`'s docstring for the profiling this is based on: an
    8-task benchmark was dominated by exactly this cost, and a real ~80-task generation should amortise
    it far better *if* every worker pays it once, up front, rather than the first task on each worker
    paying it inline.

    There is nothing to *do* here beyond referencing the names below: importing this module --
    `app.evolution.execute` -- to locate this very function (which is what `ProcessPoolExecutor` must
    do to run it as the pool's `initializer`) already executed every import at the top of this file,
    and Python only runs a module's top-level code once per process no matter how many times it is
    imported afterward. The reference below exists so a linter cannot flag those imports as unused
    from this function's point of view, not because it does anything at runtime.
    """
    _ = (run_card, run_allocation, AllocationCard, StrategyCard, Settings, Mandate)


def _run_one_card_in_worker(
    *,
    card_json: str,
    shape: Literal["strategy", "allocation"],
    agent_id: str,
    settings: Settings,
    mandate: Mandate,
    start: dt.date,
    end: dt.date,
) -> _Outcome:
    """The function `ProcessPoolExecutor.submit` actually calls, in a worker process. Module-level
    and picklable-by-reference (`concurrent.futures` pickles the *callable itself* by qualified name,
    not its bytecode -- the worker process imports `app.evolution.execute` to find it, which is what
    `_pool_initializer` above front-loads).

    **Why the card crosses as `model_dump_json()` plus a shape tag, re-validated here, while
    `settings` and `mandate` cross as the live pydantic model / dataclass instances.** `Settings` and
    `Mandate` are each a single concrete class -- pickling them is exactly as reliable as pickling any
    other plain object (both are plain field containers with no open handles or live connections), and
    there is nothing polymorphic about them for the unpickling side to get wrong. `card` is one of two
    unrelated classes (`StrategyCard` or `AllocationCard`), and this function needs to know which
    *before* it can call the right engine; `shape` makes that an explicit, inspectable value in the
    payload instead of leaning on pickle to preserve `isinstance` identity correctly across the
    process boundary. JSON is also the exact wire format every run file on disk already uses, so a
    `card_json` that failed to round-trip here would be a card that could never have been written to
    `cards/{agent_id}.json` in the first place.

    Exceptions are not allowed to escape this function. `_execute_card` already catches everything a
    card's own run can raise; a `ValidationError` from a malformed `card_json` (should never happen --
    `run_generation` only ever serialises a card it already holds as a validated object -- but caught
    rather than assumed) is caught here too, so the parent's contract is identical regardless of which
    stage inside this worker failed: a `_Outcome` with `status="failed"` is the only thing this
    function ever returns, short of the worker process itself dying, which surfaces to the parent as
    `concurrent.futures.process.BrokenProcessPool` on `Future.result()` -- see `_run_window_in_pool`
    for how that is caught and turned into a serial fallback rather than a silently lost generation.
    """
    try:
        card: StrategyCard | AllocationCard = (
            AllocationCard.model_validate_json(card_json)
            if shape == "allocation"
            else StrategyCard.model_validate_json(card_json)
        )
    except Exception as exc:
        return _outcome_from_exception(agent_id, exc, 0.0)
    return _execute_card(card, settings=settings, mandate=mandate, start=start, end=end)


# ---------------------------------------------------------------------------
# Recording -- the one place both the serial and parallel paths funnel an `_Outcome` through, so
# `max_workers` cannot change what gets written for an identical outcome. Never called from a worker
# process: every run file and every `job.results` append happens in the parent, on purpose -- see
# `run_generation`'s own docstring ("Run files are written by the parent, not the workers").
# ---------------------------------------------------------------------------


class _Counts:
    """Mutable completed/failed tallies, passed by reference into the serial/parallel window runners.
    A plain pair of ints would not let a helper function mutate the caller's copy; this is that
    mutable cell, nothing more."""

    __slots__ = ("completed", "failed")

    def __init__(self) -> None:
        self.completed = 0
        self.failed = 0


def _apply_outcome(
    *,
    job: jobs._Job,
    window: str,
    runs_dir: Path,
    outcome: _Outcome,
    counts: _Counts,
    errors: list[str],
    emit: Callable[[str], None],
) -> None:
    if outcome.status == "failed":
        with job.lock:
            job.failed_runs += 1
            job.results.append(
                jobs.RunResult(
                    window=window,
                    agent_id=outcome.agent_id,
                    status="failed",
                    seconds=outcome.elapsed,
                    error=outcome.error,
                )
            )
        counts.failed += 1
        errors.append(f"[{window}] {outcome.agent_id}: {outcome.error}")
        job.append_log(f"[{window}] {outcome.agent_id}: FAILED {outcome.error}")
        emit(f"[{window}] {outcome.agent_id}: FAILED {outcome.error}")
        return

    assert outcome.result_json is not None  # every "ok" outcome carries one -- see _outcome_from_result
    run_path = runs_dir / f"{jobs._TAG}-{outcome.agent_id}.json"
    run_path.write_text(outcome.result_json, encoding="utf-8")

    with job.lock:
        job.completed_runs += 1
        job.results.append(
            jobs.RunResult(
                window=window,
                agent_id=outcome.agent_id,
                status="ok",
                total_return=outcome.total_return,
                benchmark_return=outcome.benchmark_return,
                excess=outcome.excess,
                capital_exposure=outcome.capital_exposure,
                trades=outcome.trades,
                seconds=outcome.elapsed,
            )
        )
    counts.completed += 1
    ok_message = f"[{window}] {outcome.agent_id}: ok {outcome.elapsed:.1f}s trades={outcome.trades}"
    job.append_log(ok_message)
    emit(ok_message)


# ---------------------------------------------------------------------------
# Window runners -- serial (max_workers<=1, and the BrokenProcessPool fallback) and parallel
# (max_workers>1).
# ---------------------------------------------------------------------------


def _run_window_serially(
    *,
    job: jobs._Job,
    window: str,
    cards: Sequence[StrategyCard | AllocationCard],
    runs_dir: Path,
    settings: Settings,
    mandate: Mandate,
    start: dt.date,
    end: dt.date,
    cancel_requested: Callable[[], bool],
    counts: _Counts,
    errors: list[str],
    emit: Callable[[str], None],
    must_finish: bool = False,
) -> bool:
    """Run every card in `cards` for `window`, one at a time, in this process. This is both the
    `max_workers<=1` path in full, and the fallback `_run_window_in_pool` calls for whatever cards a
    broken worker pool never finished. Cancellation is checked before each card starts; a card already
    running is never interrupted (there is no way to abort a `run_card`/`run_allocation` call once it
    has started -- the same reason `app.tournament.jobs.request_cancel`'s docstring gives for its own
    identical restriction). Returns whether cancellation was observed.

    **`must_finish`.** The pre-card cancel check is the right rule for a card that has never been
    attempted, and the wrong rule for one that has. `_run_window_in_pool`'s `BrokenProcessPool`
    fallback passes `must_finish=True` because every card it hands over was already submitted to the
    pool -- under `max_workers>1` those cards finish and are recorded even when cancellation is
    observed while they run (that is the whole of `TestParallelCancellation`), and a worker dying is
    not allowed to turn that guarantee into a silent drop. In that mode no card is skipped, and the
    return value is always `False`: nothing here observed a cancellation *in place of* running a card,
    which is the only thing the caller's flag is asking about.
    """
    cancelled = False
    for card in cards:
        if not must_finish and cancel_requested():
            cancelled = True
            job.append_log(f"{window}: cancelled before {card.agent_id}")
            emit(f"{window}: cancelled before {card.agent_id}")
            break

        with job.lock:
            job.current = (window, card.agent_id)

        outcome = _execute_card(card, settings=settings, mandate=mandate, start=start, end=end)
        _apply_outcome(
            job=job, window=window, runs_dir=runs_dir, outcome=outcome, counts=counts,
            errors=errors, emit=emit,
        )

    with job.lock:
        job.current = None
    return cancelled


def _run_window_in_pool(
    *,
    executor: ProcessPoolExecutor,
    job: jobs._Job,
    window: str,
    cards: Sequence[StrategyCard | AllocationCard],
    runs_dir: Path,
    settings: Settings,
    mandate: Mandate,
    start: dt.date,
    end: dt.date,
    cancel_requested: Callable[[], bool],
    counts: _Counts,
    errors: list[str],
    emit: Callable[[str], None],
) -> tuple[bool, bool]:
    """Run every card in `cards` for `window` across `executor` -- `max_workers` of them running at
    once, the pool's own concurrency limit, not reimplemented here. Returns `(cancelled, pool_broke)`.

    **Submission and cancellation.** Every card in the window is submitted before this function waits
    on any of them (a `ProcessPoolExecutor` queues work beyond its worker count on its own, so
    submitting all of them up front is what actually gets `max_workers` running concurrently rather
    than throttling submission to match completions). `cancel_requested` is checked before each
    submission, matching `_run_window_serially`'s identical per-card check; if it fires partway through
    a window's card list, the remaining cards are never submitted, and every future already submitted
    but not yet started is cancelled (`Future.cancel()`, a no-op for one already running in a worker --
    the same "in-flight cannot be aborted" restriction `_run_window_serially` documents). This is what
    keeps a cancel *prompt*: this function returns once the cards that were already running finish --
    bounded by `max_workers` concurrent runtimes -- rather than waiting for the whole window's backlog
    to drain through the pool one batch at a time.

    **`BrokenProcessPool`.** A worker process dying -- an OOM kill, a segfault in a native dependency,
    anything that takes the process out from under its in-flight task -- surfaces to every future still
    pending in that pool as `BrokenProcessPool` on `.result()`, not just the one task that triggered it
    (this is `concurrent.futures.process`'s own behaviour, not something this function decides). This
    is caught, logged once, and every card whose future never produced a real `_Outcome` -- the one
    that surfaced the exception, and every other one still pending behind it -- is handed to
    `_run_window_serially` as a fallback, so the generation's failure-isolation guarantee holds even
    when the *pool itself*, not a card, is what failed: nothing here lets a dead worker look like a
    silently missing card the way D3's contended round did (see this module's docstring). A card is
    never double-recorded -- `_apply_outcome` is only ever called once per card, either from this
    function's own result-collection loop or from the serial fallback, never both -- because a card
    only reaches the fallback list when its future's `.result()` raised `BrokenProcessPool` rather than
    returning an `_Outcome`.

    **The fallback is not cancel-gated, deliberately.** It runs whenever `retry_cards` is non-empty,
    with `must_finish=True`, even if cancellation has been requested in the meantime. `retry_cards`
    holds only cards that were already submitted to the pool, and a submitted card finishing is the
    same promise the success path above keeps for free: the result-collection loop has no cancel check
    in it, so a cancel observed while a window's cards are in flight lets every one of them finish and
    be recorded. Cancellation skips cards *never attempted* -- that is what the pre-submit check above
    is for -- and a worker process dying is not a licence to reclassify already-submitted cards as
    never-attempted ones. Getting this wrong is not a slow cancel, it is lost work that leaves no
    trace: the dropped cards increment neither `counts.completed` nor `counts.failed` and append
    nothing to `errors`.

    The broken pool is not replaced or retried: `run_generation` reads the returned `pool_broke` flag
    and runs every subsequent window fully serially for the rest of this generation, rather than
    attempting to recover a pool whose internal state is no longer trustworthy.
    """
    pending: dict[Future[_Outcome], StrategyCard | AllocationCard] = {}
    cancelled = False
    for card in cards:
        if cancel_requested():
            cancelled = True
            job.append_log(f"{window}: cancelled before {card.agent_id}")
            emit(f"{window}: cancelled before {card.agent_id}")
            break

        with job.lock:
            job.current = (window, card.agent_id)

        shape: Literal["strategy", "allocation"] = (
            "allocation" if isinstance(card, AllocationCard) else "strategy"
        )
        future = executor.submit(
            _run_one_card_in_worker,
            card_json=card.model_dump_json(),
            shape=shape,
            agent_id=card.agent_id,
            settings=settings,
            mandate=mandate,
            start=start,
            end=end,
        )
        pending[future] = card

    if cancelled:
        for future in pending:
            future.cancel()  # no-op once a future has started running in a worker

    pool_broke = False
    retry_cards: list[StrategyCard | AllocationCard] = []
    for future in as_completed(pending):
        card = pending[future]
        try:
            outcome = future.result()
        except CancelledError:
            continue  # never actually ran -- not "attempted", matching the pre-submit cancel check
        except BrokenProcessPool as exc:
            if not pool_broke:
                pool_broke = True
                message = (
                    f"{window}: worker process pool broke ({type(exc).__name__}: {exc}) -- "
                    "falling back to serial execution for the rest of this generation"
                )
                job.append_log(message)
                emit(message)
            retry_cards.append(card)
            continue
        _apply_outcome(
            job=job, window=window, runs_dir=runs_dir, outcome=outcome, counts=counts,
            errors=errors, emit=emit,
        )

    with job.lock:
        job.current = None

    if retry_cards:
        # The pool is unusable for the rest of the run; the cards it never produced a real result for
        # are run exactly the way max_workers=1 always runs them -- one at a time, in this process.
        #
        # `must_finish=True`, and no `not cancelled` gate on reaching here at all: every card in
        # `retry_cards` was submitted to a worker before the pool died, and an already-submitted card
        # finishing is the guarantee this function's docstring makes and `TestParallelCancellation`
        # pins. Both of the obvious-looking alternatives silently lose work -- skipping the fallback
        # when `cancelled` is set, and running it under `_run_window_serially`'s ordinary cancel gate,
        # each drop those cards without touching `counts` or `errors`, so a generation that lost a
        # whole window's work reports completed/failed/errors identical to one cancelled cleanly
        # before any of it started. (The per-window reconcile in `run_generation` cannot catch it
        # either: a dropped card writes no run file *and* increments no counter, so both sides of that
        # comparison fall by the same amount. This is exactly D3's shape.)
        if cancel_requested():
            message = (
                f"{window}: cancellation is pending, but {len(retry_cards)} card(s) already "
                "submitted before the pool broke must still finish -- running them serially"
            )
            job.append_log(message)
            emit(message)
        _run_window_serially(
            job=job, window=window, cards=retry_cards, runs_dir=runs_dir, settings=settings,
            mandate=mandate, start=start, end=end, cancel_requested=cancel_requested,
            counts=counts, errors=errors, emit=emit, must_finish=True,
        )

    return cancelled, pool_broke


def run_generation(
    *,
    round_id: str,
    cards: Sequence[StrategyCard | AllocationCard],
    windows: Sequence[str],
    settings: Settings,
    cancel: threading.Event | None = None,
    log: Callable[[str], None] | None = None,
    output_root: Path | None = None,
    max_workers: int = 1,
) -> ExecutionReport:
    """Run every `(window, card)` pair in `cards` x `windows`, under the engine's single round slot,
    and write each result exactly where `app.tournament.results.load_round_scored_runs` already knows
    how to find it.

    **`max_workers`.** `<= 1` (the default) runs every `(window, card)` pair strictly serially, in
    this process -- the original, fully-tested path, kept as the fallback and left unchanged in
    behaviour and in on-disk output. `> 1` runs one window's cards across a `ProcessPoolExecutor` of
    that size before moving to the next window (window-major, not fully flattened across the whole
    generation) -- see `_run_window_in_pool`'s docstring for submission/cancellation/`BrokenProcessPool`
    handling, and this module's own docstring for why parallelising *inside* the one round slot this
    function already holds does not reopen `strategy-program/DEFECTS.md` D3. Windows are kept one in
    flight at a time deliberately: it bounds how many workers' worth of a window's symbol frames are
    resident at once, which is the whole memory argument for not also parallelising across windows.
    **Output is identical regardless of `max_workers`** -- every run file and every `RunResult` is
    built by the same `_apply_outcome` call, fed by the same `_execute_card`/`_outcome_from_result`
    arithmetic, whichever path produced the `_Outcome`; see `tests/test_evolution_execute.py`'s
    `TestParallelExecution` for the byte-for-byte comparison this claim rests on rather than assumes.

    **`output_root` defaults to `app.tournament.jobs._default_output_root()`, not
    `settings.rounds_dir`.** Those two agree in production, but not in a test that has called
    `jobs.reset_registry(output_root=...)` to redirect the module-level default without touching
    `settings` at all -- and, more importantly for this package's real caller, not for the evolution
    loop's supervisor, which points this parameter at `app.evolution.models.loop_root(settings) /
    "rounds"` (a sibling of the committed, git-tracked `data/rounds/` tree, deliberately outside it --
    see that function's own docstring) rather than at `settings.rounds_dir`. Every path this function
    writes to -- the populated-round check, the run files, and the frozen `cards/` copy -- is derived
    from the single `root` variable resolved here, and nowhere in this function does a path reach for
    `settings.rounds_dir` directly. Getting that wrong would mean a generation's run files land beside
    the human programme's committed rounds, or a redirected test still writes into the real tree.

    **Card-shape dispatch, failure handling and the `cards/` freeze** are unchanged from before
    `max_workers` existed -- see `_execute_card`'s docstring for dispatch and failure handling.

    **Cancellation is checked between windows and before submitting/running each card, never
    mid-run.** There is no way to abort a `run_card`/`run_allocation` call once it has started; `cancel`
    -- and the slot's own `job.cancel_event`, settable via `DELETE /api/competition/jobs/{job_id}`
    while this generation holds that job's id -- are polled before the next window, and before the
    next card within a window (see `_run_window_serially`/`_run_window_in_pool`). Under `max_workers >
    1`, cancellation is coarser than under the serial path: every card already dispatched to a worker
    when cancellation is observed keeps running to completion (recorded normally when it finishes) --
    up to `max_workers` of them -- rather than just the one card the serial path might have in flight.
    `run_generation` still returns `status="cancelled"` promptly once those already-running cards
    finish, not after the rest of the window's backlog would have drained through the pool.

    **Run files are written by the parent, not the workers.** `_apply_outcome` -- the only place a run
    file is ever written or a `job.results` entry appended -- runs exclusively in this process, whether
    it is fed by `_run_window_serially`'s in-process calls or by `_run_window_in_pool`'s collected
    `Future` results. Two processes writing into one round directory is exactly the concurrent-write
    shape this repo has already been burned by (D3), for an I/O cost -- one small JSON file per card --
    that is nothing next to the backtest itself; a worker's only output is the `_Outcome` it returns.
    """
    emit = log if log is not None else _emit_noop

    root = output_root if output_root is not None else jobs._default_output_root()
    round_dir = root / round_id
    jobs._check_round_not_already_populated(round_dir)

    unknown_windows = [w for w in windows if w not in jobs.WINDOWS]
    if unknown_windows:
        raise jobs.UnknownWindow(unknown_windows[0], sorted(jobs.WINDOWS))

    cards = tuple(cards)
    windows = tuple(windows)
    total_runs = len(cards) * len(windows)

    counts = _Counts()
    errors: list[str] = []
    job_id: str | None = None

    # `external_round_slot` raises `JobAlreadyRunning` here, before anything below runs, if another
    # round or generation already holds the slot -- and per this module's own docstring, that
    # propagates to the caller untouched rather than being retried.
    with jobs.external_round_slot(round_id, total_runs=total_runs, label="evolution") as job:
        job_id = job.job_id
        with job.lock:
            job.cards = cards
            job.windows = windows
            job.output_root = root
        message = (
            f"generation {round_id}: {len(cards)} card(s) x {len(windows)} window(s) "
            f"= {total_runs} run(s)"
            + (f", max_workers={max_workers}" if max_workers > 1 else "")
        )
        job.append_log(message)
        emit(message)

        # The frozen card set is written before a single card runs, matching the rounds tree's own
        # `cards/{agent_id}.json` convention (see e.g. `data/rounds/*/cards/`) -- "frozen" means
        # locked in before any run result exists to have been fitted to, and writing it here, inside
        # the slot but before the mandate is even loaded, is what makes that true regardless of how
        # the generation goes on to finish.
        cards_dir = round_dir / "cards"
        cards_dir.mkdir(parents=True, exist_ok=True)
        for card in cards:
            (cards_dir / f"{card.agent_id}.json").write_text(
                card.model_dump_json(indent=2), encoding="utf-8"
            )

        try:
            mandate = jobs._load_mandate()
        except Exception as exc:
            failure_text = f"failed to load mandate: {type(exc).__name__}: {exc}"
            with job.lock:
                job.status = "failed"
                job.error = failure_text
                job.finished_at = dt.datetime.now(dt.UTC)
            job.append_log(f"FAILED to load mandate: {failure_text}")
            emit(f"FAILED to load mandate: {failure_text}")
            return ExecutionReport(
                round_id=round_id,
                job_id=job_id,
                status="failed",
                windows=windows,
                completed_runs=0,
                failed_runs=0,
                errors=(failure_text,),
            )

        def _cancel_requested() -> bool:
            return (cancel is not None and cancel.is_set()) or job.cancel_event.is_set()

        cancelled = False
        run_failure: str | None = None
        pool_broken = False

        executor: ProcessPoolExecutor | None = None
        if max_workers > 1:
            executor = ProcessPoolExecutor(max_workers=max_workers, initializer=_pool_initializer)

        try:
            for window in windows:
                if _cancel_requested():
                    cancelled = True
                    break

                start, end, _regime = jobs.WINDOWS[window]
                runs_dir = round_dir / "results" / window / "runs"
                try:
                    runs_dir.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    # An unwritable output root kills the whole generation -- the same distinction
                    # `_worker`'s own docstring draws between a per-card misfortune and something that
                    # takes the job itself down. Nothing has been attempted in this window yet, so
                    # there is nothing to reconcile; just stop.
                    run_failure = f"could not create {runs_dir}: {type(exc).__name__}: {exc}"
                    job.append_log(f"FAILED {run_failure}")
                    emit(f"FAILED {run_failure}")
                    break

                attempted_before = counts.completed + counts.failed
                if executor is not None and not pool_broken:
                    window_cancelled, pool_broke_now = _run_window_in_pool(
                        executor=executor, job=job, window=window, cards=cards, runs_dir=runs_dir,
                        settings=settings, mandate=mandate, start=start, end=end,
                        cancel_requested=_cancel_requested, counts=counts, errors=errors, emit=emit,
                    )
                    pool_broken = pool_broken or pool_broke_now
                else:
                    window_cancelled = _run_window_serially(
                        job=job, window=window, cards=cards, runs_dir=runs_dir, settings=settings,
                        mandate=mandate, start=start, end=end, cancel_requested=_cancel_requested,
                        counts=counts, errors=errors, emit=emit,
                    )
                cancelled = cancelled or window_cancelled
                attempted = counts.completed + counts.failed - attempted_before

                # Reconcile, exactly as `_worker` does after every window: a run file count that does
                # not match the attempted count is a silent shortfall, not evidence of an empty field.
                # See `strategy-program/DEFECTS.md` D3.
                written = len(list(runs_dir.glob("*.json")))
                reconcile_message = (
                    f"{window}: reconcile {written} run file(s) written, {attempted} run(s) attempted"
                )
                job.append_log(reconcile_message)
                emit(reconcile_message)

                if cancelled or run_failure is not None:
                    break
        finally:
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=True)

        with job.lock:
            job.current = None
            job.finished_at = dt.datetime.now(dt.UTC)
            if run_failure is not None:
                job.status = "failed"
                job.error = run_failure
            else:
                job.status = "cancelled" if cancelled else "succeeded"
            status = job.status

        if run_failure is not None:
            errors.append(run_failure)

    assert job_id is not None  # set unconditionally above once the slot was acquired
    return ExecutionReport(
        round_id=round_id,
        job_id=job_id,
        status=status,
        windows=windows,
        completed_runs=counts.completed,
        failed_runs=counts.failed,
        errors=tuple(errors),
    )

"""Round 33 Phase B: the self-contained daily step that runs the screened study forward.

One session's work is: resolve any matured candidate observations, fill the screen books' due
pending orders (the fill cadence the card-mode autopilot in :mod:`app.workflow.loop` does NOT cover --
it iterates only the four card books), then launch that session's screened decision with the promoted
selector so the next session has orders to fill.

**Deliberately separate from the card autopilot.** This module never touches `loop.run_once`,
`app.main`, or the card books, so it cannot destabilise the in-flight 4-arm card study. It is off
unless something actually calls :func:`run_phase_b_step` -- a scheduled task, the step script, or a
manual run. The fill half reuses `app.workflow.book.execute_pending` and the launch half goes through
`app.workflow.service.start_workflow_run` (registry-slot-protected, agent-availability-checked), so
this module composes existing, tested pieces rather than reimplementing either.

**Live quote source: None**, matching `loop.run_once`: an order whose fill date's open is not stored
yet stays pending and fills off that same stored open on a later step -- the catch-up path that makes a
missed day harmless. **Mandate: `default_mandate`**, matching `loop.run_once` and `/book/execute`, so
screen fills obey the same cash/position/clip rules as every other workflow fill.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.config import Settings
from app.paper.mandate import default_mandate
from app.workflow import book as book_mod
from app.workflow import candidates
from app.workflow import exits as exits_mod
from app.workflow.pipeline import SCREENED_ARMS, STARTING_CASH
from app.workflow.schemas import WorkflowRunRequest

logger = logging.getLogger(__name__)

#: The frozen live Phase B config: the Round-33-promoted selector, widened to a 10-symbol shortlist
#: (owner decision, for study accrual), the two screened arms, and the study's bounded per-run spend.
PHASE_B_SELECTOR_ID = "mom12_1_hysteresis"
PHASE_B_SCREEN_TOP_N = 10
#: A less-restrictive screen-mode entry than any regime card's own: a trending *state* (above the
#: 200-day, short EMA over long) rather than the card's crossover *event*, so the study accrues
#: candidates fast enough to measure. The card's own entry fires ~2x/month on this shortlist; this
#: fires whenever a momentum-selected name is simply trending up, which is most of them most days.
PHASE_B_SCREEN_ENTRY_RULE = "close > sma(200) and ema(20) > ema(50)"
PHASE_B_ARMS = ("raw_signal", "full_workflow")
PHASE_B_BUDGET_USD = "64.00"
PHASE_B_PER_CHILD_USD = "4.00"
PHASE_B_MAX_RESEARCH_SYMBOLS = 3

_TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
_POLL_S = 8.0
_DEFAULT_LAUNCH_TIMEOUT_S = 3300.0


@dataclass(frozen=True, slots=True)
class PhaseBStepSummary:
    """One session's Phase B step outcome."""

    today: dt.date
    observations_resolved: int
    filled: int
    rejected: int
    still_pending: int
    launched_run_id: str | None
    launched_state: str | None
    launched_error: str | None
    staged: dict[str, int]  # screen arm -> orders staged this step


def phase_b_request() -> WorkflowRunRequest:
    """The frozen live Phase B run request. One place so the scheduler, the step, and any manual launch
    all issue byte-identical runs."""
    return WorkflowRunRequest(
        universe_mode="screen",
        selector_id=PHASE_B_SELECTOR_ID,
        screen_top_n=PHASE_B_SCREEN_TOP_N,
        screen_entry_rule=PHASE_B_SCREEN_ENTRY_RULE,
        arms_enabled=list(PHASE_B_ARMS),
        budget_usd=PHASE_B_BUDGET_USD,
        per_child_budget_usd=PHASE_B_PER_CHILD_USD,
        max_research_symbols=PHASE_B_MAX_RESEARCH_SYMBOLS,
    )


def _fill_screen_books(settings: Settings, *, today: dt.date) -> tuple[int, int, int]:
    """Fill every existing screen book's due pending orders off the stored open. Returns
    (filled, rejected, still_pending). A screen book that does not exist yet (no screened run has
    staged into that arm) is skipped, never seeded here."""
    mandate = default_mandate(starting_cash=STARTING_CASH)
    filled = rejected = still_pending = 0
    for arm in SCREENED_ARMS:
        if not book_mod.book_path(settings, arm, universe_source="screen").is_file():
            continue
        book = book_mod.load_book(
            settings, arm, starting_cash=STARTING_CASH, card_id="", universe_source="screen"
        )
        book, outcome = book_mod.execute_pending(
            book, settings=settings, mandate=mandate, live_quote_source=None, today=today
        )
        # Decide exits on the post-fill book, staged for the next open -- the same order `run_once`
        # uses and for the same reason (a same-day entry must be in the book its own exit is checked
        # against). Without this the screen books, which this scheduled task fills rather than the
        # in-process daemon, would buy and never sell -- the gap `app.workflow.exits` exists to close.
        book, _decisions = exits_mod.stage_due_exits(
            book, settings=settings, today=today, allow_fractional=mandate.allow_fractional_shares
        )
        try:
            book = book_mod.mark_equity_through(
                book, settings=settings, mandate=mandate, through=today
            )
        except Exception:
            logger.warning(
                "phase B: equity marking failed for screen/%s through %s; saving fills without it",
                arm, today, exc_info=True,
            )
        book_mod.save_book(settings, book)
        filled += outcome.filled
        rejected += outcome.rejected
        still_pending += outcome.still_pending
    return filled, rejected, still_pending


def _staged_counts(settings: Settings) -> dict[str, int]:
    """Pending (not-yet-filled) order count per screen arm -- a snapshot of what is awaiting fill."""
    counts: dict[str, int] = {}
    for arm in SCREENED_ARMS:
        if not book_mod.book_path(settings, arm, universe_source="screen").is_file():
            counts[arm] = 0
            continue
        book = book_mod.load_book(
            settings, arm, starting_cash=STARTING_CASH, card_id="", universe_source="screen"
        )
        counts[arm] = sum(1 for o in book.orders if o.status == "pending")
    return counts


def run_phase_b_step(
    settings: Settings,
    *,
    today: dt.date | None = None,
    launch: bool = True,
    launch_timeout_s: float = _DEFAULT_LAUNCH_TIMEOUT_S,
    sleep_fn: Callable[[float], object] | None = None,
) -> PhaseBStepSummary:
    """One session of Phase B: resolve matured observations, fill due screen orders, then (unless
    `launch=False`) launch this session's screened decision and wait for it to finish.

    `launch=False` runs the deterministic fill/resolve half only -- the unit-testable core, with no
    agent spend. `sleep_fn` is injectable so a test can drive the launch poll without real time.
    """
    as_of = today if today is not None else dt.date.today()
    sleeper = sleep_fn if sleep_fn is not None else time.sleep

    observations_resolved = candidates.resolve_pending(settings=settings, today=as_of)
    filled, rejected, still_pending = _fill_screen_books(settings, today=as_of)

    launched_run_id: str | None = None
    launched_state: str | None = None
    launched_error: str | None = None

    if launch:
        # Imported here, not at module scope: the fill/resolve half must stay importable and testable
        # without pulling the whole run registry / agent stack in behind it.
        from app.agentdesk.store import RunStore
        from app.workflow import service

        run = service.start_workflow_run(phase_b_request(), settings=settings)
        launched_run_id = run.run_id
        store = RunStore(settings, "workflow")
        deadline = time.monotonic() + launch_timeout_s
        while time.monotonic() < deadline:
            cur = store.load(run.run_id)
            if cur is None:
                launched_state = "vanished"
                break
            if cur.state in _TERMINAL:
                launched_state = cur.state
                launched_error = cur.error
                break
            sleeper(_POLL_S)
        else:
            launched_state = "timeout"
        logger.info(
            "phase B step %s: launched %s -> %s (filled=%d rejected=%d pending=%d)",
            as_of, launched_run_id, launched_state, filled, rejected, still_pending,
        )

    return PhaseBStepSummary(
        today=as_of,
        observations_resolved=observations_resolved,
        filled=filled,
        rejected=rejected,
        still_pending=still_pending,
        launched_run_id=launched_run_id,
        launched_state=launched_state,
        launched_error=launched_error,
        staged=_staged_counts(settings),
    )

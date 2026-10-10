"""The manager commissioning its own research: run a proposed `Commission`'s child desk in-process
and await its result, honoring the autonomy policy.

This is the reverse direction of `app.workflow.pipeline`'s own child-spawning (workflow -> Trading
Agents / Vibe children): here the *manager* desk is the parent, and its children are any of the four
`CommissionKind`s -- Trading Agents, Vibe Trading, the Agent Workflow desk, or a single persona-chat
turn. The spawn-and-await shape is copied verbatim from `app.workflow.pipeline._launch_ta` /
`_launch_vibe` / `_await_child`: build a request the child service's own `start_run` (or
`start_workflow_run`) validates, get back a queued `DeskRun` immediately, then poll `RunStore.load`
until the run reaches a terminal state, honoring a timeout and a cancel event exactly like the
workflow desk's own children do. `persona_chat` is the one kind with no child `DeskRun` at all --
`app.personas.service.ask` is a single synchronous grounded call, so it returns directly.

**Never spend unless approved.** `execute` only launches a commission whose `state` is already
`"approved"` (or `"running"` -- a commission the caller already flipped and is re-entering); anything
else is returned unchanged, with a note in `child_summary` saying why nothing ran. The propose ->
approved transition itself is `app.manager.service`'s job (whatever surfaces the click, or -- when
`may_run_unattended` says yes -- the autopilot loop calling `approve` itself); this module only
executes what is already approved, and exposes `approve`/`decline` as the trivial pure state flips so
that decision has one place to live.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.agentdesk.jobs import RunAlreadyActive, registry
from app.agentdesk.models import DeskKind, DeskRun
from app.agentdesk.store import RunStore
from app.agents.models import AgentUnavailable
from app.config import Settings
from app.manager.models import Commission
from app.personas import service as personas_service
from app.tradingagents import service as tradingagents_service
from app.vibedesk import service as vibedesk_service
from app.workflow import service as workflow_service

__all__ = [
    "approve",
    "decline",
    "execute",
    "may_run_unattended",
]

logger = logging.getLogger(__name__)

#: How long a commissioned child may run before the manager gives up waiting and marks the
#: commission failed, and how often it polls the child's store snapshot meanwhile. Copied from
#: `app.workflow.pipeline._CHILD_TIMEOUT_S`/`_CHILD_POLL_S` -- the same reasoning applies verbatim:
#: long enough for a real Trading Agents / Workflow run (which can itself launch further children) to
#: finish, short enough that one wedged child cannot hang the manager desk indefinitely.
_CHILD_TIMEOUT_S = 25 * 60
_CHILD_POLL_S = 2.0

_TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled"})

#: `child_summary` is "a one-liner" per this feature's own contract -- long enough to be useful on
#: the manager's commission list, short enough that it never becomes the report itself (the full
#: child run is still reachable via `child_run_id`).
_SUMMARY_MAX_CHARS = 280


@dataclass
class _TARequest:
    """A structural `app.tradingagents.service.StartRunRequest` -- copied field-for-field from
    `app.workflow.pipeline._TARequest`, which that module's own docstring explains is *not* frozen on
    purpose: `StartRunRequest` is a `typing.Protocol` whose members are plain (settable) attributes,
    and a frozen dataclass's read-only attributes fail mypy's structural check against a Protocol that
    declares them mutable. `StartSwarmRequest` and `WorkflowRunRequest`, by contrast, are concrete
    pydantic request models (not Protocols) that this module constructs directly below -- no
    structural stand-in is needed for either.
    """

    symbol: str
    trade_date: dt.date | None
    analysts: list[str] | None
    debate_rounds: int | None
    risk_rounds: int | None
    budget_usd: str | None
    model: str | None


# ---------------------------------------------------------------------------
# Autonomy policy
# ---------------------------------------------------------------------------


def may_run_unattended(commission: Commission, settings: Settings) -> bool:
    """Whether the manager may start `commission` without a person clicking Run.

    True iff `settings.manager_autonomy == "auto_bounded"` **and** `commission.kind` is one of the
    comma-separated kinds in `settings.manager_unattended_kinds`. Trading Agents and Workflow runs are
    excluded from that setting's default (`"persona_chat,vibedesk"`) precisely because they are the
    more expensive children (~$5 each) -- this function never overrides that; it is a pure read of the
    two settings plus the commission's own kind.
    """
    if settings.manager_autonomy != "auto_bounded":
        return False
    allowed = {part.strip() for part in settings.manager_unattended_kinds.split(",") if part.strip()}
    return commission.kind in allowed


def approve(commission: Commission) -> Commission:
    """`proposed` -> `approved`. Trivial and pure -- callers decide *when*; this just flips the
    field so the state machine's edges live in one place."""
    return commission.model_copy(update={"state": "approved"})


def decline(commission: Commission) -> Commission:
    """`proposed` -> `declined`. Trivial and pure, mirroring `approve`."""
    return commission.model_copy(update={"state": "declined"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _commission_budget(commission: Commission, settings: Settings) -> Decimal:
    """`commission.budget_usd` if it parses as a positive decimal, else
    `settings.manager_commission_cap_usd` (falling back to `$6` if even that fails to parse) -- the
    per-child ceiling handed to the child as its own `budget_usd`."""
    try:
        value = Decimal(commission.budget_usd)
    except (InvalidOperation, ValueError):
        value = Decimal("0")
    if value > 0:
        return value
    try:
        fallback = Decimal(settings.manager_commission_cap_usd)
    except (InvalidOperation, ValueError):
        return Decimal("6")
    return fallback if fallback > 0 else Decimal("6")


def _parse_date(value: Any) -> dt.date | None:
    """`commission.params`'s `trade_date`, which may arrive as a `dt.date` (a caller that built the
    `Commission` in-process) or an ISO date string (round-tripped through JSON/storage). Anything else
    -- missing, `None`, unparseable -- degrades to `None` ("the newest stored session"), never a
    raise; a commission's params are the proposer's own choice, not validated input this module should
    reject."""
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and value:
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _trim_summary(text: str, *, max_chars: int = _SUMMARY_MAX_CHARS) -> str:
    """Collapse `text` to one dense line, trimmed to `max_chars` -- what `child_summary` carries."""
    line = " ".join(text.strip().split())
    if len(line) <= max_chars:
        return line
    return line[: max_chars - 1].rstrip() + "…"


def _child_summary_from_run(run: DeskRun) -> str:
    """The one-liner `child_summary` for a desk-kind commission: `final_rating` (Trading Agents only)
    prefixed onto `final_md`, else `final_md` alone, else `error` for a run that produced neither --
    trimmed. Mirrors what a reader skimming the commission list needs; the full report stays reachable
    through `child_run_id`."""
    text = f"{run.final_rating} — {run.final_md}" if run.final_rating else run.final_md
    if not text.strip():
        text = run.error or f"child run ended {run.state!r} with no report"
    return _trim_summary(text)


def _await_child(
    kind: DeskKind, run_id: str, *, settings: Settings, cancel: threading.Event
) -> DeskRun | None:
    """Poll a child run's store snapshot until it reaches a terminal state, is cancelled, or times
    out. Returns the terminal `DeskRun`, or `None` on timeout/cancel/vanish.

    Re-implemented locally (not imported) per this feature's scope fence -- `app.workflow.pipeline.
    _await_child` is that module's own private helper -- but the semantics are copied exactly: poll the
    persisted snapshot (the same object the child desk's own API serves, so what the manager reads is
    exactly what a person watching the child desk directly would see), cancel the child through the
    registry on either a timeout or the caller's own cancel event, never raise.
    """
    store = RunStore(settings, kind)
    deadline = time.monotonic() + _CHILD_TIMEOUT_S
    while True:
        if cancel.is_set():
            registry().cancel(run_id)
            return None
        run = store.load(run_id)
        if run is not None and run.state in _TERMINAL_STATES:
            return run
        if time.monotonic() >= deadline:
            logger.warning(
                "manager: commissioned %s run %s timed out after %ss", kind, run_id, _CHILD_TIMEOUT_S
            )
            registry().cancel(run_id)
            return None
        time.sleep(_CHILD_POLL_S)


# ---------------------------------------------------------------------------
# Per-kind launch -- build the child's own request shape, call its start_run, return (kind, run_id)
# ---------------------------------------------------------------------------


def _launch_tradingagents(commission: Commission, *, settings: Settings) -> str:
    params = commission.params
    req = _TARequest(
        symbol=str(params.get("symbol", "")),
        trade_date=_parse_date(params.get("trade_date")),
        analysts=list(params["analysts"]) if params.get("analysts") is not None else None,
        debate_rounds=params.get("debate_rounds"),
        risk_rounds=params.get("risk_rounds"),
        budget_usd=str(_commission_budget(commission, settings)),
        model=params.get("model"),
    )
    run = tradingagents_service.start_run(req, settings=settings)
    return run.run_id


def _launch_vibedesk(commission: Commission, *, settings: Settings) -> str:
    from app.vibedesk.schemas import StartSwarmRequest

    params = commission.params
    req = StartSwarmRequest(
        preset=str(params.get("preset", "")),
        symbol=str(params.get("symbol", "")),
        question=str(params.get("question", "")),
        variables={str(k): str(v) for k, v in dict(params.get("variables") or {}).items()},
        budget_usd=str(_commission_budget(commission, settings)),
        model=params.get("model"),
    )
    run = vibedesk_service.start_run(req, settings=settings)
    return run.run_id


def _launch_workflow(commission: Commission, *, settings: Settings) -> str:
    from app.workflow.schemas import WorkflowRunRequest

    params = commission.params
    req = WorkflowRunRequest(
        agent_card_id=params.get("agent_card_id"),
        trade_date=_parse_date(params.get("trade_date")),
        budget_usd=str(_commission_budget(commission, settings)),
        per_child_budget_usd=params.get("per_child_budget_usd"),
        max_research_symbols=params.get("max_research_symbols"),
        model=params.get("model"),
    )
    run = workflow_service.start_workflow_run(req, settings=settings)
    return run.run_id


_LAUNCHERS: dict[str, tuple[DeskKind, Callable[..., str]]] = {
    "tradingagents": ("tradingagents", _launch_tradingagents),
    "vibedesk": ("vibedesk", _launch_vibedesk),
    "workflow": ("workflow", _launch_workflow),
}


# ---------------------------------------------------------------------------
# The public entry point
# ---------------------------------------------------------------------------


def execute(
    commission: Commission, *, settings: Settings, cancel: threading.Event | None = None
) -> Commission:
    """Run the child for an APPROVED commission and return an updated `Commission`.

    Only a commission whose `state` is `"approved"` or `"running"` is actually run -- see this
    module's own docstring for why `execute` never flips `proposed -> running` itself. Every other
    state (already `succeeded`/`failed`/`cancelled`/`declined`, or still `proposed`) is returned
    unchanged except for a note appended to `child_summary`, and no child is ever launched.

    Never raises for a child failure or timeout: any exception starting the child (an unavailable
    agent layer, a run already active, a bad param the child's own validation rejects) or a child that
    times out / fails / is cancelled all resolve to a returned `Commission` with `state="failed"` (or
    `"cancelled"` for the cancel-event path) and the reason in `child_summary`. A genuinely unexpected
    exception is caught by the same broad handler, not allowed to propagate -- a commissioning failure
    must never crash whatever called `execute`.
    """
    if commission.state not in ("approved", "running"):
        return commission.model_copy(
            update={
                "child_summary": (
                    f"not run: commission state is {commission.state!r}, not 'approved'"
                )
            }
        )

    if commission.kind == "persona_chat":
        return _execute_persona_chat(commission, settings=settings)

    cancel_event = cancel if cancel is not None else threading.Event()

    launcher = _LAUNCHERS.get(commission.kind)
    if launcher is None:  # pragma: no cover - defensive; COMMISSION_KINDS is exhaustive above
        return commission.model_copy(
            update={"state": "failed", "child_summary": f"unknown commission kind {commission.kind!r}"}
        )
    kind, launch = launcher

    try:
        run_id = launch(commission, settings=settings)
    except RunAlreadyActive as exc:
        return commission.model_copy(
            update={
                "state": "failed",
                "child_summary": _trim_summary(f"a {kind} run is already active: {exc}"),
            }
        )
    except AgentUnavailable as exc:
        return commission.model_copy(
            update={
                "state": "failed",
                "child_summary": _trim_summary(f"agent layer unavailable: {exc}"),
            }
        )
    except Exception as exc:  # a launch failure must degrade, never propagate
        # Covers each desk's own validation errors (`tradingagents.service.InvalidRequest`,
        # `vibedesk.service.InvalidPresetVariable`/`PresetNotFound`, `vibedesk.service.
        # AgentLayerUnavailable`, `workflow.service.InvalidRequest`, ...) without importing every
        # module's private exception type here -- the message is preserved either way.
        logger.warning(
            "manager: commission %s (%s) could not be launched: %s",
            commission.commission_id, commission.kind, exc,
        )
        return commission.model_copy(
            update={"state": "failed", "child_summary": _trim_summary(str(exc))}
        )

    child_run = _await_child(kind, run_id, settings=settings, cancel=cancel_event)
    if child_run is None:
        cancelled = cancel_event.is_set()
        return commission.model_copy(
            update={
                "state": "cancelled" if cancelled else "failed",
                "child_run_id": run_id,
                "child_summary": (
                    "cancelled before the child run finished"
                    if cancelled
                    else f"timed out after {_CHILD_TIMEOUT_S}s and was cancelled"
                ),
            }
        )

    if child_run.state != "succeeded":
        return commission.model_copy(
            update={
                "state": "failed",
                "child_run_id": run_id,
                "child_summary": _child_summary_from_run(child_run),
            }
        )

    return commission.model_copy(
        update={
            "state": "succeeded",
            "child_run_id": run_id,
            "child_summary": _child_summary_from_run(child_run),
        }
    )


def _execute_persona_chat(commission: Commission, *, settings: Settings) -> Commission:
    """`persona_chat` is a single synchronous grounded call -- `app.personas.service.ask` -- not a
    child `DeskRun`, so there is nothing to poll: `child_run_id` stays `None` and `child_summary` is
    the trimmed answer itself.
    """
    params = commission.params
    slug = str(params.get("slug", ""))
    question = str(params.get("question", ""))
    symbol = params.get("symbol")
    symbol_str = str(symbol) if symbol else None

    try:
        answer = personas_service.ask(settings, slug, question=question, symbol=symbol_str)
    except personas_service.PersonaError as exc:
        return commission.model_copy(
            update={"state": "failed", "child_summary": _trim_summary(str(exc))}
        )
    except AgentUnavailable as exc:
        return commission.model_copy(
            update={
                "state": "failed",
                "child_summary": _trim_summary(f"agent layer unavailable: {exc}"),
            }
        )
    except Exception as exc:  # e.g. app.agents.spend.SpendCapExceeded
        logger.warning(
            "manager: persona_chat commission %s could not be answered: %s",
            commission.commission_id, exc,
        )
        return commission.model_copy(
            update={"state": "failed", "child_summary": _trim_summary(str(exc))}
        )

    return commission.model_copy(
        update={
            "state": "succeeded",
            "child_run_id": None,
            "child_summary": _trim_summary(answer.answer),
        }
    )

"""The orchestration layer between `app.api.workflow` and the pipeline: config, run creation,
listing, cancellation. Mirrors `app.tradingagents.service`'s division of labour -- the router stays a
thin translator, every real decision lives here.

The one structural difference from the sibling desks: `start_workflow_run` claims the `"workflow"`
registry slot, and the run it starts goes on to claim the `"tradingagents"` and `"vibedesk"` slots
for its children. Those are different keys, so a workflow run and the child runs it launches never
contend for the same slot -- that is exactly why the registry is keyed by `DeskKind` and not global
(`app.agentdesk.jobs`). Two *workflow* runs still cannot overlap, which is the intended limit: one
agent's chain at a time.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from app.agentdesk.jobs import RunAlreadyActive, registry
from app.agentdesk.models import DeskRun
from app.agentdesk.store import RunStore
from app.agents import client as agents_client
from app.agents.models import DEFAULT_MODEL, AgentBudget, AgentUnavailable
from app.agents.spend import LEDGER
from app.config import Settings
from app.discovery.selector import RANK_KEYS
from app.discovery.workflow_selectors import SELECTOR_IDS
from app.rules.grammar import parse as parse_rule
from app.workflow import pipeline
from app.workflow.pipeline import (
    ALL_ARMS,
    DEFAULT_BUDGET_USD,
    DEFAULT_MAX_RESEARCH_SYMBOLS,
    DEFAULT_PER_CHILD_BUDGET_USD,
    SCREENED_ARMS,
    WorkflowConfig,
)
from app.workflow.schemas import ARM_DEFS, DeskRunSummary, WorkflowRunRequest
from app.workflow.universe import CANDIDATE_POOLS

__all__ = [
    "InvalidRequest",
    "RunNotFound",
    "cancel_run",
    "config_payload",
    "get_run",
    "list_runs",
    "start_workflow_run",
]

logger = logging.getLogger(__name__)

_STOPPABLE_STATES = frozenset({"queued", "running"})

DEFAULT_UNIVERSE_MODE = "card"
DEFAULT_CANDIDATE_POOL = "sector-etf"
DEFAULT_RANK_KEY = "mom12_1"
DEFAULT_SCREEN_TOP_N = 3


class InvalidRequest(ValueError):
    """A `WorkflowRunRequest` named an unknown arm, a non-positive budget, or a bad
    `max_research_symbols` -- 422."""


class RunNotFound(LookupError):
    """No workflow run with this id -- 404."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"no workflow run {run_id!r}")
        self.run_id = run_id


def config_payload(settings: Settings) -> dict[str, Any]:
    """`GET /api/workflow/config`'s body, in `WorkflowConfig` (wire) shape."""
    from app.tournament.results import load_library

    available, reason = agents_client.is_available()
    cards: list[dict[str, str]] = []
    seen: set[str] = set()
    for tier_cards in load_library(settings.library_dir).values():
        for card in tier_cards:
            if card.agent_id in seen:
                continue
            seen.add(card.agent_id)
            cards.append({
                "agent_id": card.agent_id,
                "label": card.agent_id,
                "purpose": str(getattr(card, "purpose", "")),
            })
    cards.sort(key=lambda c: c["agent_id"])
    return {
        "arms": [{"key": key, "label": label, "blurb": blurb} for key, label, blurb in ARM_DEFS],
        "default_budget_usd": str(DEFAULT_BUDGET_USD),
        "default_per_child_budget_usd": str(DEFAULT_PER_CHILD_BUDGET_USD),
        "default_max_research_symbols": DEFAULT_MAX_RESEARCH_SYMBOLS,
        "default_model": DEFAULT_MODEL,
        "agent_available": available,
        "agent_reason": reason,
        "cards": cards,
        "universe_modes": ["card", "screen"],
        "candidate_pools": list(CANDIDATE_POOLS),
        "rank_keys": sorted(RANK_KEYS),
        "selector_ids": list(SELECTOR_IDS),
        "default_universe_mode": DEFAULT_UNIVERSE_MODE,
        "default_candidate_pool": DEFAULT_CANDIDATE_POOL,
        "default_rank_key": DEFAULT_RANK_KEY,
        "default_screen_top_n": DEFAULT_SCREEN_TOP_N,
    }


def _parse_positive_decimal(value: str | None, default: Decimal, field: str) -> Decimal:
    if value is None:
        return default
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise InvalidRequest(f"invalid {field}: {value!r}") from exc
    if parsed <= 0:
        raise InvalidRequest(f"{field} must be positive: {value!r}")
    return parsed


def _validate_arms(arms: list[str] | None, *, mode: str) -> tuple[str, ...]:
    """Validate `arms` against whichever arm set `mode` permits.

    `universe_mode="screen"` is restricted to `SCREENED_ARMS` (`raw_signal`/`full_workflow`) --
    `ta_gated`/`vibe_gated` re-test the gate question the static 4-arm study already isolates, at 2x
    research cost, with no new information about *selection* (see `SCREENED_ARMS`'s own docstring in
    `app.workflow.pipeline`). Requesting either under screen mode is now a 422, not a silent no-op.
    """
    universe = ALL_ARMS if mode == "card" else SCREENED_ARMS
    if arms is None:
        return universe
    if not arms:
        raise InvalidRequest("at least one arm must be enabled")
    unknown = sorted(set(arms) - set(universe))
    if unknown:
        raise InvalidRequest(
            f"unknown arm(s) for universe_mode={mode!r}: {', '.join(unknown)}; "
            f"available: {', '.join(universe)}"
        )
    # Canonical order regardless of request order.
    return tuple(arm for arm in universe if arm in arms)


def _validate_screen_entry_rule(rule: str | None) -> str | None:
    """`None` (use the card's own entry) or a parseable rules-DSL expression. A bad expression is a
    422 up front, not a stage failure deep in a run whose spine has already executed -- the same honesty
    the availability check applies. Not gated on `universe_mode`: `_scan_signals` ignores it in card
    mode, so validating a well-formed rule that happens to be unused is harmless, while rejecting a
    malformed one regardless keeps the field's contract simple."""
    if rule is None:
        return None
    try:
        parse_rule(rule)
    except ValueError as exc:
        raise InvalidRequest(f"screen_entry_rule is not a valid entry expression: {exc}") from exc
    return rule


def _resolve_universe(
    req: WorkflowRunRequest,
) -> tuple[str, str | None, str | None, str | None, int | None]:
    """`(universe_mode, selector_id, candidate_pool, rank_key, screen_top_n)` -- the five
    `WorkflowConfig` universe fields, validated together because screen mode's sub-fields are only
    meaningful as a group.

    `universe_mode == "card"` (the default) returns immediately with everything else `None`. In
    `"screen"` mode, `selector_id` -- one of `app.discovery.workflow_selectors.SELECTOR_IDS` -- is the
    primary path and, when present, is validated and returned alone; `candidate_pool`/`rank_key` are
    not even inspected in that case (`app.workflow.schemas.WorkflowRunRequest.selector_id`'s own
    docstring: it takes precedence). With no `selector_id`, both `candidate_pool` and `rank_key` must
    be resolvable to a known value (defaulted when omitted, rejected when explicitly wrong); a request
    with neither `selector_id` nor `candidate_pool`/`rank_key` at all is rejected outright rather than
    silently defaulted -- `"screen"` mode with no way to decide *what* to screen is a shape defect in
    the request, not a normal omission with a sensible default.
    """
    mode = req.universe_mode or DEFAULT_UNIVERSE_MODE
    if mode == "card":
        return "card", None, None, None, None

    top_n = req.screen_top_n if req.screen_top_n is not None else DEFAULT_SCREEN_TOP_N
    if top_n < 1:
        raise InvalidRequest(f"screen_top_n must be >= 1: {top_n}")

    if req.selector_id:
        if req.selector_id not in SELECTOR_IDS:
            raise InvalidRequest(
                f"unknown selector_id: {req.selector_id!r}; available: {', '.join(SELECTOR_IDS)}"
            )
        return "screen", req.selector_id, None, None, top_n

    if req.candidate_pool is None and req.rank_key is None:
        raise InvalidRequest(
            "universe_mode='screen' requires either selector_id, or both candidate_pool and rank_key"
        )

    pool = req.candidate_pool or DEFAULT_CANDIDATE_POOL
    if pool not in CANDIDATE_POOLS:
        raise InvalidRequest(f"unknown candidate_pool: {pool!r}; available: {', '.join(CANDIDATE_POOLS)}")

    rank_key = req.rank_key or DEFAULT_RANK_KEY
    if rank_key not in RANK_KEYS:
        raise InvalidRequest(f"unknown rank_key: {rank_key!r}; available: {', '.join(sorted(RANK_KEYS))}")

    return "screen", None, pool, rank_key, top_n


def start_workflow_run(req: WorkflowRunRequest, *, settings: Settings) -> DeskRun:
    """Validate `req`, create the initial `DeskRun` (every fixed stage `"pending"`), and hand it to
    the job registry.

    Raises `InvalidRequest` (422), `AgentUnavailable` (503) or `RunAlreadyActive` (409) -- the same
    three the router catches for the other desks. The agent-availability check is up front because a
    workflow with no credential cannot launch its child research runs; failing at submission is
    honest, failing three stages deep after the deterministic spine has run is not.

    Also raises `SpendCapExceeded` (429, answered by `app.main`'s handler) when the rolling daily
    model-spend cap is already met.
    """
    # The rolling daily model-spend cap, checked before anything is created for this run -- the same
    # gate `app.manager.service.chat_turn` and `app.personas.service` apply before their own model
    # work. `SpendCapExceeded` propagates to `app.main`'s handler, which answers 429 with a
    # `Retry-After`; catching it here would only re-derive that answer. It is deliberately the first
    # statement in the function so a capped desk never leaves a queued run directory behind -- and it
    # matters most here, since one workflow run goes on to launch child runs of its own.
    LEDGER.check(settings.model_spend_daily_cap_usd)

    available, reason = agents_client.is_available()
    if not available:
        raise AgentUnavailable(reason)

    budget_usd = _parse_positive_decimal(req.budget_usd, DEFAULT_BUDGET_USD, "budget_usd")
    per_child = _parse_positive_decimal(
        req.per_child_budget_usd, DEFAULT_PER_CHILD_BUDGET_USD, "per_child_budget_usd"
    )
    max_symbols = req.max_research_symbols if req.max_research_symbols is not None else DEFAULT_MAX_RESEARCH_SYMBOLS
    if max_symbols < 1:
        raise InvalidRequest(f"max_research_symbols must be >= 1: {max_symbols}")
    universe_mode, selector_id, candidate_pool, rank_key, screen_top_n = _resolve_universe(req)
    arms = _validate_arms(req.arms_enabled, mode=universe_mode)
    screen_entry_rule = _validate_screen_entry_rule(req.screen_entry_rule)
    model = req.model or DEFAULT_MODEL

    config = WorkflowConfig(
        agent_card_id=(req.agent_card_id or None),
        trade_date=req.trade_date,
        budget_usd=budget_usd,
        per_child_budget_usd=per_child,
        max_research_symbols=max_symbols,
        analysts=tuple(req.analysts) if req.analysts is not None else None,
        debate_rounds=req.debate_rounds,
        risk_rounds=req.risk_rounds,
        arms_enabled=arms,  # type: ignore[arg-type]
        model=model,
        universe_mode=universe_mode,
        selector_id=selector_id,
        candidate_pool=candidate_pool,
        rank_key=rank_key,
        screen_top_n=screen_top_n,
        screen_entry_rule=screen_entry_rule,
        weekly_budget_usd=req.weekly_budget_usd,
    )

    run_id = uuid.uuid4().hex
    run = DeskRun(
        run_id=run_id,
        kind="workflow",
        state="queued",
        created_at=dt.datetime.now(dt.UTC),
        config={
            "agent_card_id": config.agent_card_id,
            "trade_date": req.trade_date.isoformat() if req.trade_date else None,
            "budget_usd": str(budget_usd),
            "per_child_budget_usd": str(per_child),
            "max_research_symbols": max_symbols,
            "analysts": list(config.analysts) if config.analysts is not None else None,
            "debate_rounds": req.debate_rounds,
            "risk_rounds": req.risk_rounds,
            "arms_enabled": list(arms),
            "model": model,
            "universe_mode": universe_mode,
            "selector_id": selector_id,
            "candidate_pool": candidate_pool,
            "rank_key": rank_key,
            "screen_top_n": screen_top_n,
            "screen_entry_rule": screen_entry_rule,
            "weekly_budget_usd": str(req.weekly_budget_usd),
            "child_runs": {},
        },
        stages=pipeline.build_stage_plan(config),
        budget=AgentBudget(cap_usd=budget_usd),
    )

    store = RunStore(settings, "workflow")
    store.save(run)
    try:
        registry().start(
            "workflow",
            run_id,
            lambda cancel_event: pipeline.run_workflow(run_id, config, settings=settings, cancel=cancel_event),
        )
    except RunAlreadyActive:
        store.delete(run_id)
        raise
    return run


def get_run(run_id: str, *, settings: Settings) -> DeskRun | None:
    """`GET /api/workflow/runs/{run_id}`. `None` is the router's 404."""
    return RunStore(settings, "workflow").load(run_id)


def _summarize(run: DeskRun) -> DeskRunSummary:
    card = str(run.config.get("agent_card_id") or "auto")
    trade_date = run.config.get("trade_date") or run.created_at.date().isoformat()
    stages_done = sum(1 for s in run.stages if s.state in ("succeeded", "degraded"))
    return DeskRunSummary(
        run_id=run.run_id,
        kind=run.kind,
        state=run.state,
        label=f"{card} · {trade_date}",
        created_at=run.created_at,
        completed_at=run.completed_at,
        degraded=run.degraded,
        error=run.error,
        final_rating=run.final_rating,
        cost_usd=run.cost_usd,
        stages_total=len(run.stages),
        stages_done=stages_done,
    )


def list_runs(*, settings: Settings, limit: int = 25) -> tuple[DeskRunSummary, ...]:
    """`GET /api/workflow/runs`: every stored run, newest first, summarised."""
    runs = RunStore(settings, "workflow").list_runs(limit=limit)
    return tuple(_summarize(run) for run in runs)


def cancel_run(run_id: str, *, settings: Settings) -> DeskRun:
    """`DELETE /api/workflow/runs/{run_id}`: request cancellation and return the run with
    `state: "cancelled"`. The worker notices at its next stage boundary and cancels any in-flight
    child run it is waiting on (see `pipeline._await_child`)."""
    store = RunStore(settings, "workflow")
    run = store.load(run_id)
    if run is None:
        raise RunNotFound(run_id)
    registry().cancel(run_id)
    if run.state in _STOPPABLE_STATES:
        run = run.model_copy(
            update={"state": "cancelled", "completed_at": run.completed_at or dt.datetime.now(dt.UTC)}
        )
        store.save(run)
    return run

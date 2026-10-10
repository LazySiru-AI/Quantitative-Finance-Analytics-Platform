"""The orchestration layer between `app.api.tradingagents` and everything else: config, run
creation, listing, cancellation, and the memory endpoint -- matching `app.vibedesk.service`'s own
division of labour for its sibling desk. The router stays a thin translator; every real decision
(symbol/analyst/budget validation, the job registry, wiring memory resolution into a new run) lives
here.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from app.agentdesk.jobs import RunAlreadyActive, registry
from app.agentdesk.models import DeskKind, DeskRun
from app.agentdesk.store import RunStore
from app.agents import client as agents_client
from app.agents.models import AgentBudget, AgentUnavailable, BudgetExhausted
from app.agents.spend import LEDGER
from app.config import Settings
from app.tradingagents import memory, pipeline

__all__ = [
    "DeskRunSummary",
    "InvalidRequest",
    "RunNotFound",
    "cancel_run",
    "config_payload",
    "get_run",
    "list_runs",
    "memory_payload",
    "start_run",
]

logger = logging.getLogger(__name__)


class StartRunRequest(Protocol):
    """The structural shape `start_run` needs from a request body -- satisfied by
    `app.api.tradingagents.StartRunRequest` without this module importing the API layer (routers
    depend on services here, never the reverse).

    **`live` is deliberately not a member of this Protocol**, even though `start_run` reads it and
    `app.api.tradingagents.StartRunRequest` carries it. A Protocol member is *required* of every
    structural implementer regardless of any default, and `app.workflow.pipeline._TARequest` -- the
    dataclass the Agent Workflow desk builds to launch a child TA run -- is one such implementer that
    predates this field and lives outside this change's scope. Adding the member here would make that
    caller a type error it cannot fix. `start_run` therefore reads it with `getattr(req, "live",
    False)`: a body that carries the field opts in, and every caller that does not is a non-live run,
    which is exactly the default.
    """

    symbol: str
    trade_date: dt.date | None
    analysts: list[str] | None
    debate_rounds: int | None
    risk_rounds: int | None
    budget_usd: str | None
    model: str | None


class InvalidRequest(ValueError):
    """A `StartRunRequest` named a bad symbol, an unknown analyst key, an empty analyst list, or a
    `budget_usd` that does not parse as a positive decimal -- 422."""


class RunNotFound(LookupError):
    """No tradingagents run with this id -- 404."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"no tradingagents run {run_id!r}")
        self.run_id = run_id


#: Terminal-for-the-worker states as far as `cancel_run` is concerned -- see that function's own
#: docstring, mirroring `app.vibedesk.service._STOPPABLE_STATES` for the sibling desk.
_STOPPABLE_STATES = frozenset({"queued", "running"})

_ANALYSTS: tuple[dict[str, str], ...] = (
    {
        "key": "market",
        "label": "Market Analyst",
        "blurb": "Price action against moving averages, momentum and volatility.",
    },
    {
        "key": "sentiment",
        "label": "Sentiment Analyst",
        "blurb": "Retail message volume and its bullish/bearish split.",
    },
    {
        "key": "news",
        "label": "News Analyst",
        "blurb": "Headlines, macro rate/inflation series and prediction markets.",
    },
    {
        "key": "fundamentals",
        "label": "Fundamentals Analyst",
        "blurb": "Company facts drawn from regulatory filings.",
    },
)
_ANALYST_KEYS: tuple[str, ...] = tuple(a["key"] for a in _ANALYSTS)

_DEFAULT_DEBATE_ROUNDS = 1
_DEFAULT_RISK_ROUNDS = 1
_DEFAULT_BUDGET_USD = Decimal("5.00")

#: The desk's default worker model. A Trading Agents run fires a dozen or more model calls, so the
#: default is the cheapest/fastest tier (Haiku 4.5) unless a run selects otherwise -- the owner's
#: standing preference for these high-volume research runs. A caller wanting more capability per call
#: still selects Sonnet 5 / Opus 5 per run via `req.model`. Changing this does not touch the evolution
#: loop's own model (Opus 5, which it justifies for card *design* under constraint).
DESK_DEFAULT_MODEL = "claude-haiku-4-5-20251001"

#: The worker models a run may select, most-to-least reached for, each `id` a real Claude model string
#: the CLI transport accepts and each `label` carrying the human-facing name and version. `id` is what
#: goes on the wire (and what a specific version is pinned by -- e.g. the dated Haiku snapshot); the
#: list is the single source of truth for both the `/config` dropdown and the `start_run` allow-list,
#: so the two cannot drift. Add a row here to offer a new model or a pinned version.
AVAILABLE_MODELS: tuple[dict[str, str], ...] = (
    {"id": "claude-haiku-4-5-20251001", "label": "Haiku 4.5 (default, fastest, cheapest)"},
    {"id": "claude-sonnet-5", "label": "Sonnet 5"},
    {"id": "claude-opus-5", "label": "Opus 5 (most capable, slower)"},
    {"id": "claude-fable-5", "label": "Fable 5"},
)
_MODEL_IDS: frozenset[str] = frozenset(m["id"] for m in AVAILABLE_MODELS)

#: A ticker: one leading letter, then up to nine more letters/digits/`.`/`-` -- wide enough for
#: `BRK.B`, `RDS-A`, tight enough to reject an empty string or something that is obviously not a
#: symbol at all. Matches this codebase's general "uppercase and move on" convention (see
#: `app.backtest.service`'s own `symbol.upper()` call sites) while still giving `422` a shape to name.
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def config_payload(settings: Settings) -> dict[str, Any]:
    """`GET /api/tradingagents/config`'s body, in `TradingAgentsConfig` shape. `settings` is accepted
    for signature symmetry with every other `*_payload`/`*_run` function in this module even though
    this particular response does not depend on it -- the desk's analyst roster and round limits are
    fixed, not configuration."""
    del settings
    available, reason = agents_client.is_available()
    return {
        "analysts": [dict(analyst) for analyst in _ANALYSTS],
        "default_debate_rounds": _DEFAULT_DEBATE_ROUNDS,
        "default_risk_rounds": _DEFAULT_RISK_ROUNDS,
        "max_rounds": pipeline.MAX_ROUNDS,
        "default_budget_usd": str(_DEFAULT_BUDGET_USD),
        "default_model": DESK_DEFAULT_MODEL,
        "available_models": [dict(m) for m in AVAILABLE_MODELS],
        "agent_available": available,
        "agent_reason": reason,
    }


def _validate_symbol(symbol: str) -> str:
    upper = symbol.strip().upper()
    if not _SYMBOL_RE.match(upper):
        raise InvalidRequest(f"invalid symbol: {symbol!r}")
    return upper


def _validate_analysts(analysts: list[str] | None) -> tuple[str, ...]:
    if analysts is None:
        return _ANALYST_KEYS
    if not analysts:
        raise InvalidRequest("at least one analyst must be selected")
    unknown = sorted(set(analysts) - set(_ANALYST_KEYS))
    if unknown:
        raise InvalidRequest(
            f"unknown analyst key(s): {', '.join(unknown)}; available: {', '.join(_ANALYST_KEYS)}"
        )
    # Fixed canonical order regardless of request order, deduplicated -- matches
    # `build_stage_plan`'s own iteration order over `_ANALYST_DEFS`.
    return tuple(key for key in _ANALYST_KEYS if key in analysts)


def _validate_model(model: str | None) -> str:
    """The worker model for a run: the request's choice if it named one, else the desk default.

    Validated against `AVAILABLE_MODELS` -- an unknown id is a 422 here rather than a wasted spawn and
    a transport error twelve stages deep, and it keeps the wire contract honest: the same list the UI
    offers is the same list a run may pick from."""
    if model is None:
        return DESK_DEFAULT_MODEL
    chosen = model.strip()
    if chosen not in _MODEL_IDS:
        available = ", ".join(m["id"] for m in AVAILABLE_MODELS)
        raise InvalidRequest(f"unknown model: {model!r}; available: {available}")
    return chosen


def _validate_live(live: bool, trade_date: dt.date | None) -> bool:
    """The `live` opt-in, refused when the run is also asked to be as of a past date.

    `app.agentdesk.evidence`'s two live sections return empty (with a warning) for any historical
    `as_of` -- a historical view that could see the current quote is exactly the look-ahead the
    evidence layer exists to prevent -- so a `live` run dated last Tuesday is not a live run at all,
    it is an ordinary run carrying a label that claims otherwise on the page. Refusing it here is the
    difference between a 422 the caller can read and a silently mislabelled run.

    `trade_date=None` ("the latest stored session") and today's date both pass; the comparison is in
    UTC, matching `evidence._is_historical`'s own.
    """
    if live and trade_date is not None and trade_date != dt.datetime.now(dt.UTC).date():
        raise InvalidRequest(
            "live runs must be as of today: a past trade_date cannot see the current market "
            f"(got {trade_date.isoformat()})"
        )
    return live


def _parse_budget(value: str | None) -> Decimal:
    if value is None:
        return _DEFAULT_BUDGET_USD
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise InvalidRequest(f"invalid budget_usd: {value!r}") from exc
    if parsed <= 0:
        raise InvalidRequest(f"budget_usd must be positive: {value!r}")
    return parsed


def start_run(req: StartRunRequest, *, settings: Settings) -> DeskRun:
    """Validate `req`, resolve this symbol's stale memory entries, create the run's initial
    `DeskRun` (every stage `"pending"`), and hand it to the job registry.

    Raises `InvalidRequest` (422), `AgentUnavailable` (503) or `RunAlreadyActive` (409) -- the
    router's whole job is catching these three and nothing else.

    Memory resolution happens here, synchronously, before the run is created -- not inside the
    background worker -- so `DeskRun.budget` on the very first poll already reflects whatever a
    reflector call just spent, and a resolution failure (`BudgetExhausted`/`AgentUnavailable`) never
    blocks a run from starting: it is caught and logged, and the run proceeds with whatever entries
    could not be resolved left `pending` for a future run to try again.

    Also raises `SpendCapExceeded` (429, answered by `app.main`'s handler) when the rolling daily
    model-spend cap is already met.
    """
    # The rolling daily model-spend cap, checked before anything is created for this run -- the same
    # gate `app.manager.service.chat_turn` and `app.personas.service` apply before their own model
    # work. `SpendCapExceeded` propagates to `app.main`'s handler, which answers 429 with a
    # `Retry-After`; catching it here would only re-derive that answer. It is deliberately the first
    # statement in the function so a capped desk never leaves a queued run directory behind.
    LEDGER.check(settings.model_spend_daily_cap_usd)

    available, reason = agents_client.is_available()
    if not available:
        raise AgentUnavailable(reason)

    symbol = _validate_symbol(req.symbol)
    analysts = _validate_analysts(req.analysts)
    debate_rounds = pipeline.clamp_rounds(
        req.debate_rounds if req.debate_rounds is not None else _DEFAULT_DEBATE_ROUNDS
    )
    risk_rounds = pipeline.clamp_rounds(
        req.risk_rounds if req.risk_rounds is not None else _DEFAULT_RISK_ROUNDS
    )
    budget_usd = _parse_budget(req.budget_usd)
    model = _validate_model(req.model)
    live = _validate_live(bool(getattr(req, "live", False)), req.trade_date)

    config = pipeline.PipelineConfig(
        symbol=symbol,
        trade_date=req.trade_date,
        analysts=analysts,
        debate_rounds=debate_rounds,
        risk_rounds=risk_rounds,
        budget_usd=budget_usd,
        model=model,
        live=live,
    )

    budget = AgentBudget(cap_usd=budget_usd)
    try:
        budget = memory.resolve_pending(symbol, settings=settings, budget=budget, model=model)
    except (BudgetExhausted, AgentUnavailable) as exc:
        logger.warning(
            "tradingagents: memory resolution for %s could not complete (%s); starting the run anyway",
            symbol, exc,
        )

    run_id = uuid.uuid4().hex
    run = DeskRun(
        run_id=run_id,
        kind="tradingagents",
        state="queued",
        created_at=dt.datetime.now(dt.UTC),
        config={
            "symbol": symbol,
            "trade_date": req.trade_date.isoformat() if req.trade_date else None,
            "analysts": list(analysts),
            "debate_rounds": debate_rounds,
            "risk_rounds": risk_rounds,
            "budget_usd": str(budget_usd),
            "model": model,
            "live": live,
        },
        stages=pipeline.build_stage_plan(config),
        budget=budget,
    )

    store = RunStore(settings, "tradingagents")
    store.save(run)

    try:
        registry().start(
            "tradingagents",
            run_id,
            lambda cancel_event: pipeline.run_pipeline(run_id, config, settings=settings, cancel=cancel_event),
        )
    except RunAlreadyActive:
        # The registry, not the store, is the single source of truth for "is a run already in
        # flight" -- this run's `run.json` was written optimistically just above and must not be left
        # behind as a queued run nothing will ever pick up.
        store.delete(run_id)
        raise

    return run


def get_run(run_id: str, *, settings: Settings) -> DeskRun | None:
    """`GET /api/tradingagents/runs/{run_id}`. `None` is the router's 404."""
    return RunStore(settings, "tradingagents").load(run_id)


class DeskRunSummary(BaseModel):
    """`DeskRunSummary` in `docs/AGENT-DESK-CONTRACT.md`'s shared wire types -- defined here rather
    than in `app.agentdesk.models` because that module is a frozen, shared contract this change does
    not own; `app.vibedesk.schemas` defines its own copy for the identical reason."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    kind: DeskKind
    state: str
    label: str
    created_at: dt.datetime
    completed_at: dt.datetime | None
    degraded: bool
    error: str
    final_rating: str
    cost_usd: Decimal
    stages_total: int
    stages_done: int


def _summarize(run: DeskRun) -> DeskRunSummary:
    symbol = str(run.config.get("symbol") or "")
    trade_date = run.config.get("trade_date") or run.created_at.date().isoformat()
    stages_done = sum(1 for stage in run.stages if stage.state in ("succeeded", "degraded"))
    return DeskRunSummary(
        run_id=run.run_id,
        kind=run.kind,
        state=run.state,
        label=f"{symbol} · {trade_date}",
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
    """`GET /api/tradingagents/runs`: every stored run, newest first, summarised -- never `stages`,
    `final_md` or `config`."""
    runs = RunStore(settings, "tradingagents").list_runs(limit=limit)
    return tuple(_summarize(run) for run in runs)


def cancel_run(run_id: str, *, settings: Settings) -> DeskRun:
    """`DELETE /api/tradingagents/runs/{run_id}`: request cancellation and return the run with
    `state: "cancelled"`.

    Sets the registry's cancellation event (the worker notices it at its next stage boundary and does
    its own per-stage bookkeeping -- see `app.tradingagents.pipeline.run_pipeline`) and, if the run has
    not already reached a terminal state, persists `"cancelled"` immediately rather than making the
    caller poll to see it -- matching the contract's literal claim that this endpoint returns the
    cancelled state, not merely requests it. A run already `succeeded`/`failed`/`cancelled` is returned
    unchanged: there is no worker left to interrupt and no result left to discard.
    """
    store = RunStore(settings, "tradingagents")
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


def memory_payload(symbol: str | None, *, settings: Settings) -> dict[str, Any]:
    """`GET /api/tradingagents/memory`'s body: `{"entries": MemoryEntry[]}`, optionally filtered to
    one symbol."""
    entries = memory.read_entries(symbol, settings=settings)
    return {"entries": [entry.model_dump(mode="json") for entry in entries]}

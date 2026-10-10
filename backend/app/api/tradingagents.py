"""HTTP surface for Trading Agents -- a full analyst-to-portfolio-manager pipeline run on one ticker.

Thin on purpose, matching `app.api.vibedesk`'s own convention for its sibling desk: every real
decision (symbol/analyst/budget validation, the job registry, the run store) lives in
`app.tradingagents.service`. This router's whole job is wiring routes and translating that module's
domain exceptions into the status codes `docs/AGENT-DESK-CONTRACT.md` pins for both desks.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict

from app.agentdesk.jobs import RunAlreadyActive
from app.agentdesk.models import RUN_ID_MAX_LENGTH, RUN_ID_PATTERN, DeskRun
from app.agents.models import AgentUnavailable
from app.config import Settings, get_settings
from app.tradingagents import service

router = APIRouter(prefix="/api/tradingagents", tags=["tradingagents"])

#: `run_id`s are `uuid.uuid4().hex` -- 32 lowercase hex characters -- but this path parameter accepts
#: a slightly wider shape so a malformed id reads as this router's own 404 rather than a 422 the
#: caller has to interpret differently for the same underlying mistake. Matches
#: `app.api.vibedesk.RunIdPath`'s own reasoning -- including the shared
#: `app.agentdesk.models.RUN_ID_PATTERN`, which is what keeps a separator or a dot segment out of the
#: `runs_dir(...) / run_id` join in `app.agentdesk.models.run_dir`.
RunIdPath = Annotated[
    str, Path(min_length=1, max_length=RUN_ID_MAX_LENGTH, pattern=RUN_ID_PATTERN)
]

SettingsDep = Annotated[Settings, Depends(get_settings)]


class AnalystOption(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    label: str
    blurb: str


class ModelOption(BaseModel):
    """One selectable worker model: `id` is the wire value (and the version pin), `label` the name
    shown in the picker."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    label: str


class TradingAgentsConfigResponse(BaseModel):
    """`TradingAgentsConfig` in `docs/AGENT-DESK-CONTRACT.md`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    analysts: list[AnalystOption]
    default_debate_rounds: int
    default_risk_rounds: int
    max_rounds: int
    default_budget_usd: str
    default_model: str
    available_models: list[ModelOption]
    agent_available: bool
    agent_reason: str


class StartRunRequest(BaseModel):
    """`StartRunRequest` in `docs/AGENT-DESK-CONTRACT.md`. Structurally satisfies
    `app.tradingagents.service.StartRunRequest`'s `Protocol` without that module importing this one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    trade_date: dt.date | None = None
    analysts: list[str] | None = None
    debate_rounds: int | None = None
    risk_rounds: int | None = None
    budget_usd: str | None = None
    model: str | None = None

    live: bool = False
    """Read the current market as well as the stored session -- see
    `app.tradingagents.pipeline.PipelineConfig.live`. Defaults `False`, so a body written before this
    field existed starts exactly the run it always did. `422` when combined with a `trade_date` that
    is neither null nor today (UTC): a historical view must not see the current quote."""


class RunsListResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    runs: list[service.DeskRunSummary]


@router.get("/config", response_model=TradingAgentsConfigResponse)
def get_config(settings: SettingsDep) -> TradingAgentsConfigResponse:
    """The desk's own configuration: which analysts exist, the default/max round counts, the default
    budget and model, and whether the agent layer can run at all right now."""
    return TradingAgentsConfigResponse(**service.config_payload(settings))


@router.post("/runs", response_model=DeskRun, status_code=202)
def create_run(body: StartRunRequest, settings: SettingsDep) -> DeskRun:
    """Launch one pipeline run; `202` with the freshly created `DeskRun` (`state: "queued"`, every
    stage `"pending"`).

    `422` for an invalid symbol, an unknown analyst key, an empty analyst list, an unparseable
    `budget_usd`, or `live: true` with a past `trade_date`; `503` if the agent layer has no usable
    credential right now; `409` if a Trading Agents run is already in flight (single-slot registry,
    keyed by desk kind).
    """
    try:
        return service.start_run(body, settings=settings)
    except service.InvalidRequest as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AgentUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RunAlreadyActive as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/runs", response_model=RunsListResponse)
def list_runs(settings: SettingsDep, limit: Annotated[int, Query(ge=1, le=200)] = 25) -> RunsListResponse:
    """Every stored Trading Agents run, newest first, summarised -- never `stages`, `final_md` or
    `config`; poll `GET /runs/{run_id}` for those."""
    return RunsListResponse(runs=list(service.list_runs(settings=settings, limit=limit)))


@router.get("/runs/{run_id}", response_model=DeskRun)
def get_run(run_id: RunIdPath, settings: SettingsDep) -> DeskRun:
    """One run's full state, for the 2s poll loop while `state` is `"queued"` or `"running"`. `404`
    for an unknown `run_id`."""
    run = service.get_run(run_id, settings=settings)
    if run is None:
        raise HTTPException(status_code=404, detail=f"no tradingagents run {run_id!r}")
    return run


@router.delete("/runs/{run_id}", response_model=DeskRun)
def cancel_run(run_id: RunIdPath, settings: SettingsDep) -> DeskRun:
    """Request cancellation and return the run with `state: "cancelled"`. `404` for an unknown
    `run_id`. Idempotent for a run that has already reached a terminal state -- see
    `app.tradingagents.service.cancel_run`'s own docstring."""
    try:
        return service.cancel_run(run_id, settings=settings)
    except service.RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/memory")
def get_memory(settings: SettingsDep, symbol: str | None = None) -> dict[str, Any]:
    """Past decisions the desk has recorded, optionally filtered to one symbol -- including entries
    whose outcome is still `"pending"`."""
    return service.memory_payload(symbol, settings=settings)

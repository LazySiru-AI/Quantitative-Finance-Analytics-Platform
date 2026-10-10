"""The orchestration layer between `app.api.vibedesk` and everything else: preset reads, run
creation, and translating this package's own domain exceptions into what the router needs to pick a
status code. The router itself stays a thin translator, per `docs/AGENT-DESK-CONTRACT.md`'s own
convention -- every real decision (variable validation, budget parsing, the job registry) lives here.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from app.agentdesk.jobs import RunAlreadyActive, registry
from app.agentdesk.models import DeskRun
from app.agentdesk.store import RunStore
from app.agents import client as agents_client
from app.agents.models import AgentBudget
from app.agents.spend import LEDGER
from app.config import Settings
from app.tradingagents.service import AVAILABLE_MODELS
from app.vibedesk.presets import Preset, PresetNotFound, list_presets, load_preset
from app.vibedesk.runtime import DESK_DEFAULT_MODEL, SwarmConfig, build_stage_plan, run_swarm
from app.vibedesk.schemas import (
    DeskRunSummary,
    PresetAgentOut,
    PresetDetail,
    PresetsResponse,
    PresetSummary,
    PresetTaskOut,
    PresetVariableOut,
    RunsResponse,
    StartSwarmRequest,
)

__all__ = [
    "AgentLayerUnavailable",
    "InvalidPresetVariable",
    "RunNotFound",
    "build_config",
    "cancel_run",
    "get_run",
    "list_runs",
    "preset_payload",
    "presets_payload",
    "start_run",
]


def build_config() -> dict[str, Any]:
    """`GET /api/vibedesk/config`'s body: the default worker model and the catalogue of models a run
    may select.

    Reuses `app.tradingagents.service.AVAILABLE_MODELS` verbatim rather than keeping a second,
    hand-typed list -- Vibe Trading and Trading Agents share the same worker fleet (both fire model
    calls through `app.agentdesk.grounding.run_grounded`/`call_structured`), so a second list could
    only ever drift from the first, never legitimately differ. Only `default_model` is Vibe's own:
    Haiku 4.5, matching `DESK_DEFAULT_MODEL` above, for the same high-volume-run reasoning
    `app.tradingagents.service.DESK_DEFAULT_MODEL` documents.
    """
    return {
        "default_model": DESK_DEFAULT_MODEL,
        "available_models": [dict(m) for m in AVAILABLE_MODELS],
    }

#: Terminal-*for-the-worker* states as far as `cancel_run` is concerned: a run in either has no
#: worker thread left to interrupt, so forcing `"cancelled"` onto it would overwrite a result that
#: already happened.
_STOPPABLE_STATES = frozenset({"queued", "running"})


class RunNotFound(LookupError):
    """No run with this id -- 404."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"no vibedesk run {run_id!r}")
        self.run_id = run_id


class InvalidPresetVariable(ValueError):
    """A `StartSwarmRequest` named a variable the preset does not declare, left a required one unset,
    or supplied a `budget_usd` that does not parse as a decimal -- 422."""


class AgentLayerUnavailable(RuntimeError):
    """`app.agents.client.is_available()` says no -- 503. Carries the reason verbatim so the router
    can put it in the response body, the same as `app.api.agents.health` already surfaces it."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------


def _agent_count(preset: Preset) -> int:
    return len(preset.agents)


def _layer_count(preset: Preset) -> int:
    if not preset.tasks:
        return 0
    return max(task.layer for task in preset.tasks) + 1


def _summary(preset: Preset) -> PresetSummary:
    return PresetSummary(
        name=preset.name,
        label=preset.label,
        blurb=preset.blurb,
        agent_count=_agent_count(preset),
        layer_count=_layer_count(preset),
    )


def presets_payload() -> PresetsResponse:
    """`GET /api/vibedesk/presets`: every preset under `presets_dir()`, sorted by name."""
    return PresetsResponse(presets=tuple(_summary(preset) for preset in list_presets()))


def preset_payload(name: str) -> PresetDetail | None:
    """`GET /api/vibedesk/presets/{name}`, or `None` for an unknown preset (the router's 404)."""
    try:
        preset = load_preset(name)
    except PresetNotFound:
        return None

    return PresetDetail(
        name=preset.name,
        label=preset.label,
        blurb=preset.blurb,
        agent_count=_agent_count(preset),
        layer_count=_layer_count(preset),
        agents=tuple(
            PresetAgentOut(id=agent.id, label=agent.label, blurb=agent.blurb) for agent in preset.agents
        ),
        tasks=tuple(
            PresetTaskOut(id=task.id, agent_id=task.agent_id, depends_on=task.depends_on, layer=task.layer)
            for task in preset.tasks
        ),
        variables=tuple(
            PresetVariableOut(name=v.name, label=v.label, required=v.required, default=v.default)
            for v in preset.variables
        ),
    )


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def _validate_variables(preset: Preset, req: StartSwarmRequest) -> None:
    declared = {variable.name: variable for variable in preset.variables}
    for key in req.variables:
        if key not in declared:
            raise InvalidPresetVariable(f"unknown preset variable: {key!r}")

    for variable in preset.variables:
        if variable.name == "symbol":
            # `symbol` is always supplied via the request's own dedicated field, never via
            # `variables` -- see `app.vibedesk.runtime._format_vars`, which injects it unconditionally
            # regardless of whether the preset also lists it as a formal variable.
            if variable.required and not req.symbol.strip():
                raise InvalidPresetVariable("symbol is required for this preset")
            continue
        supplied = req.variables.get(variable.name, "")
        if variable.required and not supplied and not variable.default:
            raise InvalidPresetVariable(f"missing required preset variable: {variable.name!r}")


def _parse_budget(raw: str) -> Decimal:
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise InvalidPresetVariable(f"budget_usd is not a valid decimal: {raw!r}") from exc
    if value <= 0:
        raise InvalidPresetVariable(f"budget_usd must be positive: {raw!r}")
    return value


def start_run(req: StartSwarmRequest, *, settings: Settings) -> DeskRun:
    """Validate `req` against its preset, create the run's initial `DeskRun` (every stage `pending`),
    and hand it to the job registry.

    Raises `PresetNotFound` (404), `InvalidPresetVariable` (422), `AgentLayerUnavailable` (503) or
    `RunAlreadyActive` (409) -- the router's whole job is catching these four and nothing else -- plus
    `SpendCapExceeded` (429), which `app.main`'s own handler answers.
    """
    # The rolling daily model-spend cap, checked before anything is created for this run -- the same
    # gate `app.manager.service.chat_turn` and `app.personas.service` apply before their own model
    # work. `SpendCapExceeded` propagates to `app.main`'s handler, which answers 429 with a
    # `Retry-After`; catching it here would only re-derive that answer. It is deliberately the first
    # statement in the function so a capped desk never leaves a queued run directory behind.
    LEDGER.check(settings.model_spend_daily_cap_usd)

    preset = load_preset(req.preset)  # PresetNotFound propagates
    _validate_variables(preset, req)
    budget_usd = _parse_budget(req.budget_usd)

    available, reason = agents_client.is_available()
    if not available:
        raise AgentLayerUnavailable(reason)

    symbol = req.symbol.strip().upper()
    model = req.model or DESK_DEFAULT_MODEL
    # `live` is read structurally rather than off `StartSwarmRequest` itself: the router's own body
    # (`app.api.vibedesk.StartSwarmBody`) adds the field, while `app.workflow.pipeline._launch_vibe`
    # still hands this function a plain `StartSwarmRequest` -- which is a non-live run, the default.
    live = bool(getattr(req, "live", False))
    config = SwarmConfig(
        preset_name=preset.name,
        symbol=symbol,
        question=req.question,
        variables=dict(req.variables),
        budget_usd=budget_usd,
        model=model,
        live=live,
    )

    run_id = uuid.uuid4().hex
    run = DeskRun(
        run_id=run_id,
        kind="vibedesk",
        state="queued",
        created_at=dt.datetime.now(dt.UTC),
        config={
            "preset": preset.name,
            "symbol": symbol,
            "question": req.question,
            "variables": dict(req.variables),
            "model": model,
            "live": live,
        },
        stages=build_stage_plan(preset),
        budget=AgentBudget(cap_usd=budget_usd),
    )

    store = RunStore(settings, "vibedesk")
    store.save(run)

    try:
        registry().start(
            "vibedesk", run_id, lambda cancel_event: run_swarm(run_id, config, settings=settings, cancel=cancel_event)
        )
    except RunAlreadyActive:
        # The registry is the single source of truth for "is a run already in flight"; this run's
        # `run.json` was written optimistically just above and must not be left behind as a queued
        # run nothing will ever pick up.
        store.delete(run_id)
        raise

    return run


def get_run(run_id: str, *, settings: Settings) -> DeskRun | None:
    """`GET /api/vibedesk/runs/{run_id}`. `None` is the router's 404."""
    return RunStore(settings, "vibedesk").load(run_id)


def _run_summary(run: DeskRun) -> DeskRunSummary:
    symbol = str(run.config.get("symbol") or "")
    preset_name = str(run.config.get("preset") or "")
    label = f"{preset_name} · {symbol}" if symbol else preset_name
    stages_done = sum(1 for stage in run.stages if stage.state in ("succeeded", "degraded"))
    return DeskRunSummary(
        run_id=run.run_id,
        kind=run.kind,
        state=run.state,
        label=label,
        created_at=run.created_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        degraded=run.degraded,
        error=run.error,
        final_rating=run.final_rating,
        cost_usd=str(run.cost_usd),
        stages_total=len(run.stages),
        stages_done=stages_done,
    )


def list_runs(*, settings: Settings, limit: int = 25) -> RunsResponse:
    """`GET /api/vibedesk/runs`: every stored run, newest first, summarised."""
    runs = RunStore(settings, "vibedesk").list_runs(limit=limit)
    return RunsResponse(runs=tuple(_run_summary(run) for run in runs))


def cancel_run(run_id: str, *, settings: Settings) -> DeskRun:
    """`DELETE /api/vibedesk/runs/{run_id}`: request cancellation and return the run with
    `state: "cancelled"`.

    Sets the registry's cancellation event (the worker notices it at its next layer boundary and does
    its own bookkeeping -- see `app.vibedesk.runtime.run_swarm`) and, if the run has not already
    reached a terminal state, persists `"cancelled"` immediately rather than making the caller poll to
    see it -- matching the contract's literal claim that this endpoint returns the cancelled state, not
    merely requests it. A run already `succeeded`/`failed`/`cancelled` is returned unchanged: there is
    no worker left to interrupt and no result left to discard.
    """
    store = RunStore(settings, "vibedesk")
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

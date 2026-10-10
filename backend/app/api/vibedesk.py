"""HTTP surface for Vibe Trading -- preset desks of role agents, run as a DAG.

Thin on purpose, matching `app.api.competition_jobs`'s own convention: every real decision (variable
validation, budget parsing, the job registry, the run store) lives in `app.vibedesk.service`. This
router's whole job is wiring routes and translating that module's domain exceptions into the status
codes `docs/AGENT-DESK-CONTRACT.md` pins for both desks.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict

from app.agentdesk.jobs import RunAlreadyActive
from app.agentdesk.models import RUN_ID_MAX_LENGTH, RUN_ID_PATTERN, DeskRun
from app.config import Settings, get_settings
from app.vibedesk import service
from app.vibedesk.presets import PresetNotFound
from app.vibedesk.schemas import PresetDetail, PresetsResponse, RunsResponse, StartSwarmRequest

router = APIRouter(prefix="/api/vibedesk", tags=["vibedesk"])

#: `run_id`s are `uuid.uuid4().hex` -- 32 lowercase hex characters -- but this path parameter accepts a
#: slightly wider shape so a malformed id reads as this router's own 404 rather than a 422 the caller
#: has to interpret differently for the same underlying mistake. Matches
#: `app.api.competition_jobs.JobIdPath`'s own reasoning.
#:
#: The `pattern` is the shared `app.agentdesk.models.RUN_ID_PATTERN`: without it, `%5C`-encoded
#: backslashes in this parameter walked out of this desk's runs tree in the `runs_dir(...) / run_id`
#: join, and `GET /api/vibedesk/runs/..\..\manager\runs/<id>` answered 200 with a manager run. Every
#: desk router points at that one constant so they cannot drift apart on what an id may contain.
RunIdPath = Annotated[
    str, Path(min_length=1, max_length=RUN_ID_MAX_LENGTH, pattern=RUN_ID_PATTERN)
]

SettingsDep = Annotated[Settings, Depends(get_settings)]


class ModelOption(BaseModel):
    """One selectable worker model: `id` is the wire value (and the version pin), `label` the name
    shown in the picker. Mirrors `app.api.tradingagents.ModelOption` field-for-field -- the two desks
    offer the identical catalogue, see `app.vibedesk.service.build_config`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    label: str


class VibedeskConfigResponse(BaseModel):
    """`GET /api/vibedesk/config`'s response body."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    default_model: str
    available_models: list[ModelOption]


@router.get("/config", response_model=VibedeskConfigResponse)
def get_config() -> VibedeskConfigResponse:
    """The desk's own configuration: the default worker model and the catalogue of models a run may
    select from -- the same catalogue `GET /api/tradingagents/config` exposes, so the two desks' model
    pickers cannot drift apart."""
    return VibedeskConfigResponse(**service.build_config())


@router.get("/presets", response_model=PresetsResponse)
def list_presets() -> PresetsResponse:
    """Every preset under `app.vibedesk.presets.presets_dir()`, sorted by name."""
    return service.presets_payload()


@router.get("/presets/{name}", response_model=PresetDetail)
def get_preset(name: Annotated[str, Path(min_length=1, max_length=128)]) -> PresetDetail:
    """One preset's full definition: its agents, its task DAG, and its variables. `404` if `name`
    does not match any file under `presets_dir()`."""
    detail = service.preset_payload(name)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"no vibedesk preset named {name!r}")
    return detail


class StartSwarmBody(StartSwarmRequest):
    """`StartSwarmRequest` plus this feature's `live` opt-in.

    A subclass rather than a field on `StartSwarmRequest` itself because `app.vibedesk.schemas` is
    outside this change's scope, and because the extra field genuinely belongs to the *HTTP body*: the
    other caller of `app.vibedesk.service.start_run` (`app.workflow.pipeline._launch_vibe`) constructs
    the plain schema type and is a non-live run by definition. `start_run` reads the field
    structurally, so both bodies work -- see its own comment.
    """

    live: bool = False
    """Add the current market (`live_quote` + `intraday`) to every seat's shared ground truth -- see
    `app.vibedesk.runtime.SwarmConfig.live`. Defaults `False`, so a body written before this field
    existed starts exactly the run it always did."""


@router.post("/runs", response_model=DeskRun, status_code=202)
def create_run(body: StartSwarmBody, settings: SettingsDep) -> DeskRun:
    """Launch one preset as a background worker thread; `202` with the freshly created `DeskRun`
    (`state: "queued"`, every stage `"pending"`).

    `404` for an unknown preset, `422` for an unknown/missing preset variable or an unparseable
    `budget_usd`, `503` if the agent layer has no usable credential right now, `409` if a Vibe Trading
    run is already in flight (single-slot registry, keyed by desk kind).
    """
    try:
        return service.start_run(body, settings=settings)
    except PresetNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.InvalidPresetVariable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.AgentLayerUnavailable as exc:
        raise HTTPException(status_code=503, detail=exc.reason) from exc
    except RunAlreadyActive as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/runs", response_model=RunsResponse)
def list_runs(
    settings: SettingsDep, limit: Annotated[int, Query(ge=1, le=200)] = 25
) -> RunsResponse:
    """Every stored Vibe Trading run, newest first, summarised -- never `stages`, `final_md` or
    `config`; poll `GET /runs/{run_id}` for those."""
    return service.list_runs(settings=settings, limit=limit)


@router.get("/runs/{run_id}", response_model=DeskRun)
def get_run(run_id: RunIdPath, settings: SettingsDep) -> DeskRun:
    """One run's full state, for the 2s poll loop while `state` is `"queued"` or `"running"`. `404`
    for an unknown `run_id`."""
    run = service.get_run(run_id, settings=settings)
    if run is None:
        raise HTTPException(status_code=404, detail=f"no vibedesk run {run_id!r}")
    return run


@router.delete("/runs/{run_id}", response_model=DeskRun)
def cancel_run(run_id: RunIdPath, settings: SettingsDep) -> DeskRun:
    """Request cancellation and return the run with `state: "cancelled"`. `404` for an unknown
    `run_id`. Idempotent for a run that has already reached a terminal state -- see
    `app.vibedesk.service.cancel_run`'s own docstring."""
    try:
        return service.cancel_run(run_id, settings=settings)
    except service.RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

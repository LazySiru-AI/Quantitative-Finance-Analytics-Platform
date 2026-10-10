"""Manager desk HTTP surface: the deterministic slice only (`config`, `changes`, `snapshot`) --
`docs/AGENT-DESK-CONTRACT.md` "Manager Desk". Layer C (briefs/runs/chats/commissions) is a later
shard; this router only wires the three routes it owns.

Thin by contract, same shape as `app.api.personas`: this module maps `service.ManagerError` to an
`HTTPException` and does nothing else. The whole `/api/manager` prefix is already owner-only via
`app.auth.gate.OWNER_ONLY_PREFIXES` -- no per-route auth code belongs here.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from app.agentdesk.models import RUN_ID_MAX_LENGTH, RUN_ID_PATTERN, DeskRun
from app.config import get_settings
from app.manager import service
from app.manager.models import (
    Brief,
    ChangeSet,
    Commission,
    ManagerChatThread,
    ManagerChatTurn,
    ManagerConfig,
    Scope,
    Window,
)

router = APIRouter(prefix="/api/manager", tags=["manager"])

#: Every id this router takes in a path is `uuid.uuid4().hex` (`app.manager.service.start_brief`,
#: `create_chat`, `app.manager.pipeline`'s commissions), and every one of them is joined onto a
#: directory somewhere below `data/agentdesk/manager/`: a run id in `run_dir`, a `thread_id` in
#: `app.manager.chat.ManagerChatStore._thread_path`, a `brief_id` in
#: `app.manager.pipeline._brief_path`. Constrained here, at the boundary, with the same shared
#: pattern the desk routers use -- an unconstrained `str` let `DELETE /api/manager/chats/{id}`
#: name a `.json` file outside the chats directory.
IdPath = Annotated[
    str, Path(min_length=1, max_length=RUN_ID_MAX_LENGTH, pattern=RUN_ID_PATTERN)
]


class SnapshotResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    as_of: str
    scope: Scope
    generated_at: str


@router.get("/config", response_model=ManagerConfig)
def get_config() -> ManagerConfig:
    return service.config(get_settings())


@router.get("/changes", response_model=ChangeSet)
def get_changes(
    window: Window = "yesterday",
    date: Annotated[dt.date | None, Query()] = None,
) -> ChangeSet:
    try:
        return service.changes(get_settings(), window=window, date=date)
    except service.ManagerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/snapshot", response_model=SnapshotResponse)
def post_snapshot() -> SnapshotResponse:
    try:
        snapshot = service.snapshot_now(get_settings())
    except service.ManagerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return SnapshotResponse(
        as_of=snapshot.as_of, scope=snapshot.scope, generated_at=snapshot.generated_at
    )


# ---------------------------------------------------------------------------
# Layer C -- briefs, runs, chats, commissions
# ---------------------------------------------------------------------------


class ManagerRunSummary(BaseModel):
    """Compact row for `GET /runs` -- never carries stages/config, like every desk's run list."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    kind: str
    state: str
    label: str
    created_at: str
    completed_at: str | None
    degraded: bool
    error: str
    cost_usd: str
    stages_total: int
    stages_done: int


class RunsListResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    runs: list[ManagerRunSummary]


class BriefRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    window: Window = "yesterday"
    date: dt.date | None = None


class ChatTurnRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    refresh: bool = False


def _summary(run: DeskRun) -> ManagerRunSummary:
    done = sum(1 for stage in run.stages if stage.state in ("succeeded", "degraded"))
    window = str(run.config.get("window", "")) if isinstance(run.config, dict) else ""
    label = f"brief · {window}".rstrip(" ·") or "brief"
    return ManagerRunSummary(
        run_id=run.run_id, kind=run.kind, state=run.state, label=label,
        created_at=run.created_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        degraded=run.degraded, error=run.error, cost_usd=str(run.budget.spent_usd),
        stages_total=len(run.stages), stages_done=done,
    )


@router.post("/briefs", response_model=DeskRun, status_code=202)
def post_brief(body: BriefRequest) -> DeskRun:
    try:
        return service.start_brief(get_settings(), window=body.window, date=body.date)
    except service.ManagerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/runs", response_model=RunsListResponse)
def get_runs() -> RunsListResponse:
    runs = service.list_runs(get_settings())
    return RunsListResponse(runs=[_summary(run) for run in runs])


@router.get("/runs/{run_id}", response_model=DeskRun)
def get_run(run_id: IdPath) -> DeskRun:
    try:
        return service.get_run(get_settings(), run_id)
    except service.ManagerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/runs/{run_id}/cancel", response_model=DeskRun)
def post_cancel_run(run_id: IdPath) -> DeskRun:
    try:
        return service.cancel_run(get_settings(), run_id)
    except service.ManagerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/briefs/latest", response_model=Brief)
def get_latest_brief() -> Brief:
    try:
        return service.latest_brief(get_settings())
    except service.ManagerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/briefs/{brief_id}", response_model=Brief)
def get_brief(brief_id: IdPath) -> Brief:
    try:
        return service.get_brief(get_settings(), brief_id)
    except service.ManagerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/chats", response_model=list[ManagerChatThread])
def get_chats() -> list[ManagerChatThread]:
    return service.list_chats(get_settings())


@router.post("/chats", response_model=ManagerChatThread, status_code=201)
def post_chat() -> ManagerChatThread:
    return service.create_chat(get_settings())


@router.get("/chats/{thread_id}", response_model=ManagerChatThread)
def get_chat(thread_id: IdPath) -> ManagerChatThread:
    try:
        return service.get_chat(get_settings(), thread_id)
    except service.ManagerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.delete("/chats/{thread_id}", status_code=204)
def delete_chat(thread_id: IdPath) -> None:
    service.delete_chat(get_settings(), thread_id)


@router.post("/chats/{thread_id}/turns", response_model=ManagerChatTurn)
def post_chat_turn(thread_id: IdPath, body: ChatTurnRequest) -> ManagerChatTurn:
    try:
        return service.chat_turn(
            get_settings(), thread_id, question=body.question, refresh=body.refresh
        )
    except service.ManagerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/commissions/{commission_id}/approve", response_model=Commission)
def post_approve_commission(commission_id: IdPath) -> Commission:
    settings = get_settings()
    try:
        brief = service.latest_brief(settings)
        return service.approve_commission(settings, brief.brief_id, commission_id)
    except service.ManagerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/commissions/{commission_id}/decline", response_model=Commission)
def post_decline_commission(commission_id: IdPath) -> Commission:
    settings = get_settings()
    try:
        brief = service.latest_brief(settings)
        return service.decline_commission(settings, brief.brief_id, commission_id)
    except service.ManagerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

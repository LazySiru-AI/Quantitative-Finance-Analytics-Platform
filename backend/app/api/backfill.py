"""Influencer-backfill endpoints: the HTTP surface for the manual, zero-model ingest loop.

Thin by contract, the same rule `app.api.personas` follows: this router wires routes and maps domain
exceptions to status codes, and every ounce of behaviour lives in `app.personas.backfill` (discover
new videos, render/read task packets) and `app.personas.backfill_ingest` (parse a pasted-back reply,
prove it against the packet's transcript, persist it). Nothing here fetches, summarises, validates or
writes on its own -- it shapes requests and responses and translates the two domain error types
(`BackfillResultInvalid`/`BackfillValidationFailed`) and `PersonaError` into HTTP.

The result endpoint's validation failure returns `{"detail": str, "reasons": [str]}` at the top level
(the frontend reads both off the top level), which `HTTPException`'s `{"detail": ...}` envelope cannot
express, so that one branch returns a `JSONResponse` directly. Every other error path is a plain
`HTTPException`.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.personas.backfill import (
    BackfillTask,
    TaskPacketRef,
    discover_tasks,
    find_task_packet,
    list_task_packets,
    write_task_files,
)
from app.personas.backfill_ingest import (
    BackfillResultInvalid,
    BackfillValidationFailed,
    ingest_result,
    parse_result,
    validate_result,
)
from app.personas.service import PersonaError

router = APIRouter(prefix="/api/backfill", tags=["backfill"])

VideoIdPath = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


class TaskRef(BaseModel):
    """One backfill task packet, in the wire shape the frontend was built against."""

    persona_slug: str
    persona_name: str
    video_id: str
    title: str
    url: str
    published: str
    filename: str


class TaskDetail(TaskRef):
    """A single packet plus its rendered markdown -- everything the owner pastes to an external agent."""

    markdown: str


class TasksResponse(BaseModel):
    tasks: list[TaskRef]


class GenerateRequest(BaseModel):
    model_config = {"extra": "forbid"}
    persona_slug: str | None = None
    limit: int | None = Field(default=None, ge=1)


class GenerateResponse(BaseModel):
    written: int
    tasks: list[TaskRef]


class ValidateRequest(BaseModel):
    model_config = {"extra": "forbid"}
    # Same alphabet as `VideoIdPath` above -- a YouTube video id, never a glob. Without this,
    # `find_task_packet` below globs on the raw value (`*__{video_id}.md`), and a caller-supplied
    # `*` or `?`/`[...]` would search the tasks directory rather than name one task.
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    text: str = Field(min_length=1, max_length=400_000)


class ValidateResponse(BaseModel):
    ok: bool
    reasons: list[str]
    dropped_symbols: list[str]
    ungrounded_numbers: list[str]


class ResultRequest(BaseModel):
    model_config = {"extra": "forbid"}
    text: str = Field(min_length=1, max_length=400_000)


class ResultResponse(BaseModel):
    note_id: str
    persona_slug: str
    mention_count: int
    summary_source: str


def _ref_from_packet(ref: TaskPacketRef) -> TaskRef:
    return TaskRef(
        persona_slug=ref.persona_slug,
        persona_name=ref.persona_name,
        video_id=ref.video_id,
        title=ref.title,
        url=ref.url,
        published=ref.published,
        filename=ref.filename,
    )


def _ref_from_task(task: BackfillTask) -> TaskRef:
    return TaskRef(
        persona_slug=task.persona_slug,
        persona_name=task.persona_name,
        video_id=task.video_id,
        title=task.title,
        url=task.url,
        published=task.published.date().isoformat() if task.published else "",
        filename=f"{task.persona_slug}__{task.video_id}.md",
    )


@router.get("/tasks", response_model=TasksResponse)
def list_tasks() -> TasksResponse:
    settings = get_settings()
    refs = list_task_packets(settings.backfill_tasks_dir)
    return TasksResponse(tasks=[_ref_from_packet(ref) for ref in refs])


@router.get("/tasks/{video_id}", response_model=TaskDetail)
def get_task(video_id: VideoIdPath) -> TaskDetail:
    settings = get_settings()
    packet = find_task_packet(settings.backfill_tasks_dir, video_id)
    if packet is None:
        raise HTTPException(404, f"no backfill task for {video_id!r}")
    return TaskDetail(**_ref_from_packet(packet.ref).model_dump(), markdown=packet.markdown)


@router.post("/generate", response_model=GenerateResponse)
def generate(body: GenerateRequest) -> GenerateResponse:
    settings = get_settings()
    tasks = discover_tasks(
        settings,
        limit_per_persona=body.limit,
        slugs=[body.persona_slug] if body.persona_slug else None,
    )
    written = write_task_files(
        tasks, settings.backfill_tasks_dir, summary_lang=settings.persona_summary_lang
    )
    return GenerateResponse(written=len(written), tasks=[_ref_from_task(task) for task in tasks])


@router.post("/validate", response_model=ValidateResponse)
def validate(body: ValidateRequest) -> ValidateResponse:
    # Deferred so a request to an unrelated route never loads the ledger/market registry the ticker
    # validator pulls in -- the same call-time-import discipline `backfill_ingest.ingest_result` keeps.
    from app.personas.tickers import build_symbol_validator

    settings = get_settings()
    packet = find_task_packet(settings.backfill_tasks_dir, body.video_id)
    if packet is None:
        raise HTTPException(404, f"no backfill task for {body.video_id!r}")
    try:
        result = parse_result(body.text)
    except BackfillResultInvalid as exc:
        raise HTTPException(422, str(exc)) from exc
    report = validate_result(
        result, transcript=packet.transcript, symbol_validator=build_symbol_validator(settings)
    )
    return ValidateResponse(
        ok=report.ok,
        reasons=list(report.reasons),
        dropped_symbols=list(report.dropped_symbols),
        ungrounded_numbers=list(report.ungrounded_numbers),
    )


@router.post("/tasks/{video_id}/result", response_model=ResultResponse)
def submit_result(video_id: VideoIdPath, body: ResultRequest) -> ResultResponse | JSONResponse:
    settings = get_settings()
    packet = find_task_packet(settings.backfill_tasks_dir, video_id)
    if packet is None:
        raise HTTPException(404, f"no backfill task for {video_id!r}")
    try:
        result = parse_result(body.text)
    except BackfillResultInvalid as exc:
        # Top-level `detail` + `reasons` -- the frontend reads both off the top level, which the
        # `HTTPException` `{"detail": ...}` envelope cannot express, so return the body directly.
        return JSONResponse(status_code=422, content={"detail": str(exc), "reasons": []})
    published = (
        dt.datetime.fromisoformat(packet.ref.published).replace(tzinfo=dt.UTC)
        if packet.ref.published
        else None
    )
    try:
        note = ingest_result(
            settings,
            persona_slug=packet.ref.persona_slug,
            video_id=video_id,
            result=result,
            transcript=packet.transcript,
            url=packet.ref.url,
            title=packet.ref.title,
            lang=packet.lang,
            transcript_source="auto" if packet.generated else "manual",
            published=published,
        )
    except BackfillValidationFailed as exc:
        return JSONResponse(
            status_code=422, content={"detail": str(exc), "reasons": list(exc.reasons)}
        )
    except PersonaError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return ResultResponse(
        note_id=note.note_id,
        persona_slug=note.persona,
        mention_count=len(note.mentions),
        summary_source="external",
    )

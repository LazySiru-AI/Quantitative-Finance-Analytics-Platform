"""Strategy-competition round jobs: launch, poll, list, cancel.

Thin on purpose, the same way :mod:`app.api.macro` is thin over :mod:`app.market.macro` -- every
real decision (card/window resolution, the one-round-at-a-time lock, the worker thread, the
reconciliation log) lives one layer down in :mod:`app.tournament.jobs`. This router's whole job is
translating that module's domain exceptions into the right HTTP status.

A round is a long job -- minutes to hours -- so this is deliberately not a synchronous endpoint.
``POST`` starts a worker thread and returns ``202`` immediately with a ``job_id``; the caller polls
``GET /api/competition/jobs/{job_id}`` for progress, or ``DELETE`` to request cancellation. See
:mod:`app.tournament.jobs`'s module docstring for why this shape exists at all: a round launched
detached from a shell script, with no completion signal, is the exact failure
``strategy-program/DEFECTS.md`` D3 describes.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path

from app.agentdesk.models import RUN_ID_MAX_LENGTH, RUN_ID_PATTERN
from app.tournament import jobs

router = APIRouter(prefix="/api/competition/jobs", tags=["competition"])

#: `job_id`s are `uuid.uuid4().hex` -- 32 lowercase hex characters -- but this path parameter accepts
#: a slightly wider shape than that so a malformed id reads as 404 (this router's own "not found",
#: matching `get_job`'s contract) rather than a 422 the caller has to interpret differently for the
#: same underlying mistake. The pattern is the shared `app.agentdesk.models.RUN_ID_PATTERN`, so
#: every id-keyed router in the application agrees on what an id may contain -- no separator, no
#: dot segment -- whether or not that particular id reaches the filesystem.
JobIdPath = Annotated[
    str, Path(min_length=1, max_length=RUN_ID_MAX_LENGTH, pattern=RUN_ID_PATTERN)
]


@router.post("", response_model=jobs.JobAccepted, status_code=202)
def create_job(body: jobs.JobCreateRequest) -> jobs.JobAccepted:
    """Launch one competition round as a background worker thread.

    ``cards`` empty or omitted means every card in ``tier`` (default ``"base"``); given explicitly, it
    may name any ``agent_id`` from any of the library's three tiers (``base``/``variants``/
    ``candidates``), not just ``tier``. ``windows`` empty or omitted means every window in
    ``app.tournament.jobs.MAIN_WINDOWS``. ``round_id`` must match ``^[a-z0-9][a-z0-9-]{0,63}$`` and
    must not already have run files under its ``results/`` tree -- overwriting a completed round's
    measurements silently is the kind of thing that costs a week, so that case is a ``409``, not a
    silent overwrite.

    Only one round may run at a time, process-wide: a second call while one is already
    ``queued``/``running`` is a ``409`` naming the live ``job_id``. This is not a nicety -- see
    ``app.tournament.jobs``'s module docstring for the concurrent-round disaster
    (``strategy-program/DEFECTS.md`` D3) this refusal exists to prevent.
    """
    try:
        return jobs.start_job(body)
    except jobs.JobAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except jobs.InvalidRoundId as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except jobs.RoundAlreadyExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (jobs.UnknownCard, jobs.UnknownWindow, jobs.UnknownTier) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", response_model=jobs.JobList)
def list_jobs() -> jobs.JobList:
    """Every tracked job, newest first, up to the registry's bounded history (50).

    Includes the currently running job, if any, alongside up to 49 completed ones from this process's
    lifetime -- there is no persistence across a restart, matching the in-process, no-detached-process
    design this whole module exists to enforce.
    """
    return jobs.list_jobs()


@router.get("/{job_id}", response_model=jobs.JobStatus)
def get_job(job_id: JobIdPath) -> jobs.JobStatus:
    """One job's full state: progress counters, the current `(window, agent_id)` pair, the last 200
    log lines, and every `RunResult` recorded so far. `404` for an unknown `job_id`."""
    try:
        return jobs.get_job(job_id)
    except jobs.JobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{job_id}", response_model=jobs.JobStatus)
def cancel_job(job_id: JobIdPath) -> jobs.JobStatus:
    """Request cancellation of a running job.

    Sets a `threading.Event` the worker checks between card runs -- a `run_card` already in flight
    finishes rather than being interrupted mid-window, because there is no safe interruption point
    inside it and stopping partway would write nothing useful. Returns the job's state at the moment
    cancellation was requested, which may still read `"running"` until the worker notices; poll `GET`
    for the eventual `"cancelled"`. `404` for an unknown `job_id`, `409` if the job has already reached
    a terminal status.
    """
    try:
        return jobs.request_cancel(job_id)
    except jobs.JobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except jobs.JobAlreadyFinished as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

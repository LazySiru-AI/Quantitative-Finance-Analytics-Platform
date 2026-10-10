"""HTTP surface for the endless evolution/competition loop (`app.evolution.loop`).

Thin on purpose, the same way :mod:`app.api.competition_jobs` is thin over
:mod:`app.tournament.jobs` -- every real decision (the supervisor thread, the one-loop-at-a-time
lock, the per-generation propose/run/score/promote cycle, the engine-busy retry) lives one layer down
in :mod:`app.evolution.loop`. This router's whole job is translating that module's domain exceptions
into the right HTTP status and shaping the request/response bodies.

A loop is meant to run indefinitely, so -- exactly like ``POST /api/competition/jobs`` -- ``POST``
here starts a background thread and returns ``202`` immediately with the loop's initial status; the
caller polls ``GET`` for progress and ``DELETE`` to request a stop. See
:mod:`app.evolution.loop`'s module docstring for why this is an in-process daemon thread rather than
a detached process, and for why at most one loop may run at a time.

**The four routes above this line are unchanged. Everything from `/generations` down is new, and
reads a different source of truth on purpose.** ``GET /history`` answers from `LoopStatus.history`, a
20-deep in-memory deque that a restart empties; the routes below read every ``gen{N:04d}/OUTCOME.json``
`app.evolution.loop` has ever written to disk, via :mod:`app.evolution.history`, and never consult
`LoopStatus` at all. See that module's own docstring for why a disk read is the whole point here, and
why it is safe to call whether or not a loop happens to be running in this process right now.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from app.config import Settings as _Settings
from app.evolution import dossier, history
from app.evolution import loop as loop_module
from app.evolution.history import (
    FailureStreaksResponse,
    GenerationDetail,
    GenerationsListResponse,
)
from app.evolution.models import (
    GenerationOutcome,
    LoopAlreadyRunning,
    LoopConfig,
    LoopNotRunning,
    LoopStatus,
    PendingSeat,
    UnreachablePromotionCeiling,
)
from app.evolution.promotion import (
    PendingSeatIllegalTransition,
    PendingSeatNotFound,
    read_pending_seats,
    reject_pending_seat,
    retire_pending_seat,
    seat_pending_seat,
    shelve_pending_seat,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/competition/loop", tags=["competition"])


def _settings() -> _Settings:
    """`loop_module.get_settings()`, accessed as an attribute rather than imported directly.

    `tests/test_api_evolution.py`'s `client` fixture monkeypatches exactly this attribute
    (`monkeypatch.setattr(loop_module, "get_settings", ...)`) so `POST /api/competition/loop` never
    touches real `data/` -- the three routes below need the identical `Settings` that patch produces,
    so they have to read it off `loop_module` at call time too, not via a top-level
    `from app.config import get_settings` that would bind before the patch exists and never see it.

    `loop.py` does not list `get_settings` in its own `__all__` (it is a re-export of
    `app.config.get_settings`, not something that module defines), so `strict = true` mypy flags the
    attribute access below as `[attr-defined]`. `loop.py` is not one of this router's files to edit,
    so the ignore is scoped to this one line rather than worked around by breaking the test-patching
    contract above.
    """
    return loop_module.get_settings()  # type: ignore[attr-defined]


class LoopHistoryResponse(BaseModel):
    """``GET /api/competition/loop/history`` response: the most recent generations, newest first."""

    generations: list[GenerationOutcome]


@router.post("", response_model=LoopStatus, status_code=202)
def start_loop(body: LoopConfig = LoopConfig()) -> LoopStatus:  # noqa: B008 -- frozen, immutable model
    """Start the endless evolution loop as a background supervisor thread.

    ``body`` is a `LoopConfig`; every field has a conservative default (see that model's own
    docstrings), so an empty body -- or no body at all -- is a valid request that starts a loop
    breeding both the taxable and Roth books, holding out COVID and Q4-2018, and running until
    stopped. Malformed field values (e.g. ``population`` outside ``2..16``) are rejected by FastAPI's
    own request-body validation before this function ever runs, and surface as ``422``.

    Only one loop may run at a time, process-wide: a second call while one is already
    ``"running"``/``"stopping"`` is a ``409`` naming the live ``loop_id``. This mirrors
    ``POST /api/competition/jobs``'s identical rule and exists for the identical reason -- see
    ``app.evolution.loop``'s module docstring.

    ``400`` when ``promotion_max_shared_windows`` is set below what the configured windows can
    produce. It is a ``400`` rather than a ``422`` because the body is well-formed and every field is
    individually legal -- what is wrong is the combination, against constants FastAPI's own body
    validation cannot see. The detail names the achievable floor, so the caller is told what to set
    rather than only that this is wrong.
    """
    try:
        return loop_module.start_loop(body)
    except LoopAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UnreachablePromotionCeiling as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # never a bare 500 -- see this router's module docstring
        raise HTTPException(
            status_code=500, detail=f"failed to start the evolution loop: {type(exc).__name__}: {exc}"
        ) from exc


@router.get("", response_model=LoopStatus)
def get_loop() -> LoopStatus:
    """The loop's current full state: phase, generation, best standing so far, promotions, the last
    200 log lines, and up to the most recent 20 `GenerationOutcome`s in memory (the complete history
    is on disk under `app.evolution.models.loop_root`, regardless of this bound).

    `404` when no loop has ever been started in this process -- there is no persistence across a
    restart, matching `app.tournament.jobs.JobList`'s own note on the same point.
    """
    status = loop_module.get_status()
    if status is None:
        raise HTTPException(status_code=404, detail="no evolution loop has ever been started")
    return status


@router.delete("", response_model=LoopStatus)
def stop_loop() -> LoopStatus:
    """Request a stop.

    Sets the supervisor's cancellation event -- the same `threading.Event` passed into
    `run_generation` as its `cancel` argument -- so a stop mid-round takes effect at the next card
    boundary rather than only after the whole generation finishes. Returns the loop's state at the
    moment the request was made, which may still read `"stopping"` rather than `"stopped"`; poll `GET`
    for the eventual terminal state. `409` when no loop is running (never started, or already
    `"stopped"`/`"failed"`).
    """
    try:
        return loop_module.stop_loop()
    except LoopNotRunning as exc:
        raise HTTPException(status_code=409, detail="no evolution loop is running") from exc


@router.get("/history", response_model=LoopHistoryResponse)
def get_history(
    limit: Annotated[int, Query(ge=1, le=200, description="Most recent generations to return")] = 20,
) -> LoopHistoryResponse:
    """The most recent generations, newest first, up to `limit` (default 20, capped at 200 --
    matching the loop's own in-memory bound; a longer history has to be read from disk).

    Never `404`s: no loop started yet, or a loop with zero completed generations, both answer with an
    empty `generations` list, so a caller can poll this unconditionally the same way
    `GET /api/market/refresh/status` does.
    """
    status = loop_module.get_status()
    if status is None:
        return LoopHistoryResponse(generations=[])
    return LoopHistoryResponse(generations=list(status.history[:limit]))


# ---------------------------------------------------------------------------
# The disk-backed surface: every generation, not just the last 20 in memory.
# See app.evolution.history's module docstring for why these read gen{N:04d}/OUTCOME.json directly
# and never touch LoopStatus.
# ---------------------------------------------------------------------------


@router.get("/generations", response_model=GenerationsListResponse)
def list_generations(
    limit: Annotated[int, Query(ge=1, le=200, description="Generations per page")] = 50,
    offset: Annotated[int, Query(ge=0, description="Generations to skip, newest-first")] = 0,
    purpose: Annotated[
        str | None, Query(description="Keep only this purpose (e.g. 'trading', 'roth')")
    ] = None,
    status: Annotated[
        str | None, Query(description="Keep only this status ('succeeded'/'failed'/'cancelled')")
    ] = None,
    succeeded_only: Annotated[bool, Query(description="Shorthand for status='succeeded'")] = False,
) -> GenerationsListResponse:
    """Every generation on disk under `app.evolution.models.loop_root`, newest first, paginated.

    Never `404`s: an empty or absent `loop_root` (no loop has ever run against this `Settings`) answers
    with `total=0, generations=[]`, the same "absence is not an error" rule `GET /history` already
    documents for itself. `purpose` and `status` are plain strings rather than validated against
    `Purpose`/the outcome status `Literal` -- a typo or an unrecognised value yields zero matches rather
    than a `422`, which is the more forgiving choice for a filter a UI builds from a dropdown it already
    populates from real data, not from a value a caller could get wrong in a way worth rejecting up
    front. `unreadable` counts directories whose `OUTCOME.json` could not be parsed (missing, zero-byte,
    malformed, or schema-invalid) -- see `app.evolution.history._parse_outcome` -- and is never affected
    by `purpose`/`status`/`succeeded_only`, since an unreadable directory has nothing to filter on.
    """
    settings = _settings()
    page, total, unreadable = history.list_generations(
        settings,
        limit=limit,
        offset=offset,
        purpose=purpose,
        status=status,
        succeeded_only=succeeded_only,
    )
    return GenerationsListResponse(
        total=total,
        returned=len(page),
        offset=offset,
        unreadable=unreadable,
        generations=tuple(page),
    )


@router.get("/generations/{generation}", response_model=GenerationDetail)
def get_generation(generation: int) -> GenerationDetail:
    """One generation's full record: its `GenerationOutcome` verbatim (every standing, every finding),
    `PLAN.md`'s text, and `REVIEW.json`'s raw contents if a review has been written for it yet.

    `404` when `generation`'s directory does not exist, or exists but its `OUTCOME.json` cannot be
    read -- both are "nothing to show" at this layer; see `app.evolution.history.get_generation`'s own
    docstring for why the two are not distinguished. `plan_markdown` and `review` are independently
    `None` when their respective files are absent -- `REVIEW.json` in particular is written by a
    separate, concurrently-developed review worker and will read `None` for any generation it has not
    reached yet, which is the normal, expected state and not a partial or broken record.
    """
    settings = _settings()
    detail = history.get_generation(settings, generation)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"generation {generation} not found")
    return detail


@router.get("/failure-streaks", response_model=FailureStreaksResponse)
def get_failure_streaks() -> FailureStreaksResponse:
    """Consecutive, identically-failing generations collapsed into one row each, newest first.

    Exists because a searcher can hot-fail for hundreds of generations in a row on one recurring
    defect (this task's own motivating case: 1,644 consecutive `OSError` failures from a read-only
    library path, since fixed) -- `GET /generations` would show one row per generation regardless, and
    a UI paginating through that is not a useful read of what happened. See
    `app.evolution.history.failure_streaks` for the exact collapsing rule (same error, consecutive
    generation numbers, no non-failed generation in between).
    """
    settings = _settings()
    streaks = history.failure_streaks(settings)
    return FailureStreaksResponse(streaks=streaks)


# ---------------------------------------------------------------------------
# The paper-desk seat approval queue
# ---------------------------------------------------------------------------


class PendingSeatRow(PendingSeat):
    """A `PendingSeat` plus the naming fields a person needs to read the row **before** opening it.

    These four are derived, never stored: `pending_seats.json` holds the decision record, and a
    denormalised copy of a card's name in it would go stale the moment the card changed. They are
    composed per request by `app.evolution.dossier.card_summary`, which reads the card off disk
    through its own mtime-keyed cache -- so a 25-row queue parses each card once, not once per field.

    **Why the list endpoint carries them at all.** Without these the queue rendered a bare
    `g1859-fd7c2c196f35` and four numbers, and a reader could not tell one row from another, let
    alone decide one. `headline` is derived from the *parsed rule* and never from `discipline` --
    `discipline` is a self-declared tag that has been measured disagreeing with an identical rule
    (`g1815-d05786e4c611` "breakout" and `g1823-e2a3d5060b09` "mean-reversion" are byte-identical in
    universe, entry, exit and every numeric trait), which is why it is surfaced here only as
    `discipline_label` next to a note saying so.

    Every field is `None` when the card cannot be read. That is deliberate: one missing or malformed
    card must degrade its own row, never blank the whole approval queue.
    """

    headline: str | None = None
    short_id: str | None = None
    discipline_label: str | None = None
    rule_template_id: str | None = None
    """The card's entry/exit template with its numeric parameters masked. Two rows sharing this
    string are the same strategy at different settings -- which, for every card currently in the
    queue, is all of them."""


class PendingSeatsResponse(BaseModel):
    """`GET /pending-seats`: every seat request, newest first, decided ones included."""

    requests: list[PendingSeatRow]


class SeatDecisionRequest(BaseModel):
    """The optional note a person attaches when approving or rejecting a seat."""

    note: str = ""


@router.get("/pending-seats", response_model=PendingSeatsResponse)
def get_pending_seats() -> PendingSeatsResponse:
    """Seat requests the loop has filed, awaiting (or carrying) a human decision.

    Promotion used to write the paper-desk roster overlay itself, gated only by
    `LoopConfig.seat_on_paper_desk` -- a property of the whole run, chosen before any candidate
    existed. Left running, the loop seated cards nobody had looked at. A promotion now files a
    request here, and the desk changes only after a person makes both of two separate decisions --
    `status` is the five-value `SeatStatus` enum (`pending` -> `shelved`/`rejected`, then
    `shelved` -> `seated`/`retired`) rather than the old two-value one; see
    `app.evolution.models.PendingSeat` for why the decision is split.

    Decided rows are returned alongside pending ones rather than filtered out: the useful question
    months later is "was this card considered, and what was decided", which a queue that deletes its
    history cannot answer. Never `404`s -- an empty queue is an empty list, so a UI can poll this
    unconditionally.
    """
    settings = _settings()
    rows: list[PendingSeatRow] = []
    for seat in read_pending_seats(settings):
        summary = None
        try:
            summary = dossier.card_summary(seat.genome_id, settings=settings)
        except Exception:  # pragma: no cover -- a naming failure must not blank the queue
            logger.exception("could not summarise card %s for the seat queue", seat.genome_id)
        rows.append(
            PendingSeatRow(
                **seat.model_dump(),
                headline=summary.headline if summary else None,
                short_id=summary.short_id if summary else None,
                discipline_label=summary.discipline_label if summary else None,
                rule_template_id=summary.rule_template_id if summary else None,
            )
        )
    return PendingSeatsResponse(requests=rows)


@router.post("/pending-seats/{genome_id}/shelve", response_model=PendingSeat)
def shelve_seat(genome_id: str, body: SeatDecisionRequest | None = None) -> PendingSeat:
    """Stage 1, yes: accept the card onto the review shelf.

    Keeps the card, names it, and tracks it. It places no orders and does not join the paper desk --
    seating is the separate, second decision `POST .../seat` makes. `404` when no request exists for
    `genome_id`; `409` when the request is not `"pending"` -- the message names its current status and
    what is legal from it.
    """
    try:
        return shelve_pending_seat(genome_id, note=(body.note if body else ""), settings=_settings())
    except PendingSeatNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PendingSeatIllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/pending-seats/{genome_id}/reject", response_model=PendingSeat)
def reject_seat(genome_id: str, body: SeatDecisionRequest | None = None) -> PendingSeat:
    """Stage 1, no: decline a seat request permanently. The roster overlay is not touched, so the card
    never reaches the desk.

    `404` when no request exists for `genome_id`; `409` when the request is not `"pending"` -- legal
    only from that status, same as `/shelve`. A rejection is final as far as the loop is concerned:
    `app.evolution.promotion.request_seat` will not re-open a decided genome no matter how many times
    it clears the gate again, so a tireless searcher cannot wear a reviewer down by re-asking.
    """
    try:
        return reject_pending_seat(
            genome_id, note=(body.note if body else ""), settings=_settings()
        )
    except PendingSeatNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PendingSeatIllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/pending-seats/{genome_id}/seat", response_model=PendingSeat)
def seat_seat(genome_id: str, body: SeatDecisionRequest | None = None) -> PendingSeat:
    """Stage 2, yes: seat a shelved card on the simulated paper desk.

    Adds it to the desk's roster. The desk holds no real money and seating places no order and is not
    a recommendation to. `404` when no request exists for `genome_id`; `409` when the request is not
    `"shelved"` -- in particular, a `"pending"` row must be shelved first through `POST .../shelve`;
    there is no direct `pending` -> `seated` path.
    """
    try:
        return seat_pending_seat(genome_id, note=(body.note if body else ""), settings=_settings())
    except PendingSeatNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PendingSeatIllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/pending-seats/{genome_id}/retire", response_model=PendingSeat)
def retire_seat(genome_id: str, body: SeatDecisionRequest | None = None) -> PendingSeat:
    """Stage 2, no: take a shelved card off the shelf without ever seating it. Removes it from the
    shelf; the overlay was never touched for it in the first place, since only `/seat` writes it.

    `404` when no request exists for `genome_id`; `409` when the request is not `"shelved"` -- same
    precondition as `/seat`. Final, exactly as `/reject` is final at stage one.
    """
    try:
        return retire_pending_seat(genome_id, note=(body.note if body else ""), settings=_settings())
    except PendingSeatNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PendingSeatIllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/pending-seats/{genome_id}/approve", response_model=PendingSeat, deprecated=True)
def approve_seat(
    genome_id: str, response: Response, body: SeatDecisionRequest | None = None
) -> PendingSeat:
    """Deprecated alias for `POST .../shelve` -- **not** for `POST .../seat`.

    This route used to be the single decision a promoted card got: one click put it straight on the
    paper desk. That is exactly the shape that let 22 cards get seated with nobody reviewing them (see
    `app.evolution.models.PendingSeat`'s docstring), so an old client that still calls this path is
    routed to the *safer* of the two new stages -- the review shelf, which keeps and names the card
    but places no orders -- rather than silently preserved as a one-step seat. A caller that actually
    wants the card on the desk has to call the new `/seat` route explicitly, as a second, separate
    decision; this alias cannot do it for them. Every response carries a `Deprecation: true` header so
    a caller that only checks the status code still has a way to notice.

    Same `404`/`409` rules as `/shelve`.
    """
    response.headers["Deprecation"] = "true"
    try:
        return shelve_pending_seat(genome_id, note=(body.note if body else ""), settings=_settings())
    except PendingSeatNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PendingSeatIllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

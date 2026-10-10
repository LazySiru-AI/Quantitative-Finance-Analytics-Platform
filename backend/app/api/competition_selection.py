"""One round's selection: the gates, the ranking, and the roster they produce.

Thin over :mod:`app.tournament.selection` in the same way :mod:`app.api.competition_jobs` is thin
over :mod:`app.tournament.jobs` -- every real decision (which gates, in what order, on what
evidence, and what the seating walk does) lives one layer down. This router's whole job is turning
that module's frozen dataclasses into a response model and its "cannot be computed" cases into the
right HTTP status.

**Why this endpoint exists at all.** Running a round has been a product feature since
:mod:`app.tournament.jobs` -- a button posts a job, a worker thread runs cards through windows, and
run files land on disk. *Deciding which cards win a seat* was not: it lived in one-off scripts under
``strategy-program/tools/`` and in hand-written markdown, which is why
:data:`app.paperdesk.desk.AGENT_IDS` has been edited by hand after every round. This closes that gap
for reading. It deliberately does **not** write the roster anywhere -- see below.

**Read-only, and that is a design decision rather than an omission.** This endpoint computes what
the rule *would* seat; it does not update the desk. Every round in this programme's history has ended
with the owner either accepting the rule's output or overriding it, three times out of the last four
(`data/rounds/r11-2026-08/SELECTION.md` section 8 is the most recent). A roster that silently
followed whatever the current rule computed would erase that decision point, and with it the record
of when a human disagreed with the rule and why -- which is the part of this programme that has
actually caught its own mistakes. The seat still moves by a deliberate edit.

**Slow enough to notice.** :func:`app.tournament.selection.select` reads several rounds' worth of run
files and re-prices a benchmark from the bar store, so a call is seconds rather than milliseconds. It
is a synchronous ``GET`` anyway, unlike ``POST /api/competition/jobs``: seconds is within what a page
load can wait for, and the job machinery's whole apparatus (worker thread, progress polling,
cancellation) exists for runs measured in minutes to hours. Adding it here would be cost with no
reader benefit.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, ConfigDict

from app.config import get_settings
from app.tournament import selection

#: The first sub-window of the live out-of-sample matrix. Its presence is what makes a round
#: rankable at all: the current rule ranks on the live record, so a round with no ``results/live-1``
#: directory has nothing to rank and no selection to report.
_LIVE_MATRIX_MARKER = "live-1"

router = APIRouter(prefix="/api/competition", tags=["competition"])

#: Round ids are directory names under ``data/rounds`` (``r11-2026-08``). Bounded and pattern-checked
#: here rather than left to the filesystem, because ``round_id`` is interpolated into a path: an
#: unbounded string would let ``../`` walk out of the rounds directory. The pattern is the same one
#: `app.tournament.jobs` validates new round ids against.
RoundIdPath = Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]


class GateOutcomeModel(BaseModel):
    """One card's verdict at one gate, with its figures already formatted for display.

    ``detail`` is ``dict[str, str]`` rather than typed numbers on purpose: each gate reports
    different quantities (Gate A four medians against two benchmarks, Gate C a hit count), and the
    frontend renders them as columns without needing to know which gate it is looking at. Formatting
    happens in `app.tournament.selection` so one benchmark anchor cannot be rendered two ways.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: str
    passed: bool
    reason: str
    detail: dict[str, str]


class SelectionSeatModel(BaseModel):
    """One card's position in the ranking, and whether it took a seat.

    ``seated_by`` is load-bearing for the reader, not decoration. ``"outside-competition"`` marks a
    card seated by direct analysis and never gated or ranked (`ladder-qld-schd`), and
    ``"owner-override"`` marks one seated against the rule. Both must be visually distinct from
    ``"rule"`` wherever this is rendered: a card that did not win its seat on the evidence must not
    look like one that did.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: str
    rank: int | None
    live_median: str | None
    live_hits: str | None
    novel_names: str | None
    seated: bool
    seated_by: Literal["rule", "outside-competition", "owner-override"]
    note: str


class SelectionResponse(BaseModel):
    """Everything the Selection view renders for one round.

    ``notes`` carries the measurement's standing limitations -- that the live matrix is one market
    environment cut into pieces rather than six regime draws, that the window is well short of the
    sample the programme set as its own bar, and that the rule cannot assess a card with no live
    record. They are part of the payload rather than frontend copy because they are properties of the
    evidence, not of the page, and a roster shown without them overstates what it establishes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    round_id: str
    rule_version: str
    gates: dict[str, list[GateOutcomeModel]]
    ranking: list[SelectionSeatModel]
    seats: list[SelectionSeatModel]
    notes: list[str]


@router.get("/rounds/{round_id}/selection", response_model=SelectionResponse)
def round_selection(round_id: RoundIdPath) -> SelectionResponse:
    """Apply the current selection rule to ``round_id`` and return what it seats.

    **404 means "no selection can be computed for this round"**, which covers both an unknown round
    and a known round that has no live matrix on disk -- the rule ranks on the live out-of-sample
    record, so a round that predates it has nothing to rank. Those are one case to a reader ("there
    is no selection here"), and splitting them across two statuses would ask the frontend to render
    a distinction it cannot act on differently.

    **The existence check is here rather than left to** :func:`app.tournament.selection.select`,
    which does not raise for a round it cannot find: it returns a degenerate result with an empty
    ranking and `ladder-qld-schd` still seated, because that card is seated outside the competition
    and so survives having nothing to compete against. Returned over HTTP unguarded that is a 200
    carrying a one-card roster for a round that does not exist -- a fabricated answer wearing the
    shape of a real one. Rejecting it before the call is the fix; the module's behaviour is
    reasonable for a caller that already knows the round is real, and is left alone.
    """
    rounds_dir = get_settings().rounds_dir
    if not (rounds_dir / round_id / "results" / _LIVE_MATRIX_MARKER).is_dir():
        raise HTTPException(
            status_code=404,
            detail=(
                f"no selection for {round_id!r}: the current rule ranks on the live out-of-sample "
                f"matrix and this round has no results/{_LIVE_MATRIX_MARKER} directory"
            ),
        )

    try:
        result = selection.select(round_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return SelectionResponse(
        round_id=result.round_id,
        rule_version=result.rule_version,
        gates={
            gate: [GateOutcomeModel(**vars(outcome)) for outcome in outcomes]
            for gate, outcomes in result.gates.items()
        },
        ranking=[SelectionSeatModel(**vars(seat)) for seat in result.ranking],
        seats=[SelectionSeatModel(**vars(seat)) for seat in result.seats],
        notes=list(result.notes),
    )

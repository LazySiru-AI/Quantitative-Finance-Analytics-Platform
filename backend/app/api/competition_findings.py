"""One round's own written record, as structured JSON: `GET
/api/competition/rounds/{round_id}/findings`.

Thin over :mod:`app.tournament.findings` in the same way :mod:`app.api.competition_selection` is
thin over :mod:`app.tournament.selection` -- every real judgement (which heading starts an entry,
which `kind` it gets, whether it carries forward) lives one layer down; this router only turns that
module's frozen dataclasses into a response model and its one error case into the right HTTP status.

**Why this endpoint exists.** A round's `REPORT.md` or `SELECTION.md` is the actual record of what
it found and what it left unsettled -- round 11's `SELECTION.md` §5 reverses round 8's owner
override and vindicates round 10's, in prose, and nothing about that lives anywhere machine-readable.
Someone planning round N+1 either rereads the previous round's whole document or takes someone else's
word for what it said. This closes that gap for reading, by cutting the same document into the
sections a reader would already cite (`"SELECTION.md § 8"`) and serving them as data -- it does not
re-word or summarise a single sentence of them.

**This is a reading aid over hand-written prose, not a schema, and the parser says so by degrading
rather than raising.** `app.tournament.findings`'s module docstring is the long version; the two
things worth repeating for anyone wiring a caller to this endpoint: a heading shape the parser does
not recognise is silently skipped, not reported as an error, and `carries_forward` is a heuristic
keyword match over prose (`app.tournament.findings.OPEN_ITEM_KEYWORDS`) for anything that is not a
`DEFECTS.md` entry, which reads its own `**Status:**` line instead. Both will occasionally be wrong
in the specific way heuristics are wrong -- a genuinely open item phrased without any of the keywords
reads as settled, and vice versa. A caller rendering `carries_forward` as a hard fact rather than a
"the parser's best read" signal is the mistake this docstring exists to prevent.

**404, never a 500, for an unknown round -- matching `app.api.competition`'s own contract** (see that
module's docstring): a typo or a stale build reads as "not found", not as a crash. A round that
exists but has nothing parseable is a *different* case and is not this error -- it is a normal 200
with empty `findings`/`follow_ups`, exactly the shape `app.tournament.findings.list_findings`
already returns for it; the frontend renders that as a designed empty state, not as a failure.

**`round_id` is bounded and pattern-checked before it ever reaches a path join.** Copied verbatim
from `app.api.competition_selection.RoundIdPath` rather than re-derived, because the reasoning is
identical: `round_id` is interpolated into a filesystem path (`rounds_root / round_id`), and an
unbounded string would let a value like `"../../etc"` walk out of the rounds directory. Keeping the
two declarations textually identical, rather than importing one from the other, matches how
`app.api.competition_jobs` and `app.api.competition_selection` each already carry their own copy --
this programme's routers do not share validation types across modules, so a change to one's bound
never silently moves another's.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, ConfigDict

from app.tournament import findings

router = APIRouter(prefix="/api/competition", tags=["competition"])

#: See this module's docstring -- copied from `app.api.competition_selection.RoundIdPath` verbatim.
RoundIdPath = Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]


class RoundFindingModel(BaseModel):
    """One entry: a defect, a decision, a finding, or a follow-up. Field-for-field the shape
    `frontend/src/api/competition.ts`'s `RoundFinding` already expects -- see
    `app.tournament.findings.RoundFindingData` for how each field is derived."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    round_id: str
    kind: Literal["finding", "follow-up", "defect", "decision"]
    title: str
    body: str
    source: str
    carries_forward: bool


class FindingsResponse(BaseModel):
    """`/api/competition/rounds/{round_id}/findings`'s body.

    `follow_ups` is a filtered view of `findings`, not a second list -- every id in it also appears
    in `findings`; see `app.tournament.findings.FindingsData`'s docstring for why it is built that
    way rather than independently. `sources` names the files this response actually drew an entry
    from; an unknown round is a 404 (see below), so `findings=[]` here always means "the round exists
    and wrote nothing this parser recognised", never "the round does not exist".
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    round_id: str
    findings: list[RoundFindingModel]
    follow_ups: list[RoundFindingModel]
    sources: list[str]


def _finding_model(data: findings.RoundFindingData) -> RoundFindingModel:
    return RoundFindingModel(
        id=data.id,
        round_id=data.round_id,
        kind=data.kind,  # type: ignore[arg-type]
        title=data.title,
        body=data.body,
        source=data.source,
        carries_forward=data.carries_forward,
    )


@router.get("/rounds/{round_id}/findings", response_model=FindingsResponse)
def round_findings(round_id: RoundIdPath) -> FindingsResponse:
    """`round_id`'s own written record, cut into the sections a reader would cite.

    404 when `round_id` has no directory under the rounds root -- see the module docstring. A round
    whose directory exists but holds no `REPORT.md`/`BRIEF.md`/`SELECTION.md`, or files whose
    headings this parser does not recognise, is a normal 200 with `findings=[]`, `follow_ups=[]` and
    `sources=[]`: that is the round having nothing written down, not the round being unknown.
    """
    try:
        data = findings.list_findings(round_id)
    except findings.RoundNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return FindingsResponse(
        round_id=data.round_id,
        findings=[_finding_model(f) for f in data.findings],
        follow_ups=[_finding_model(f) for f in data.follow_ups],
        sources=list(data.sources),
    )

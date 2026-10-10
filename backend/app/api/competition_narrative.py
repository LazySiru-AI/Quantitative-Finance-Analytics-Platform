"""Two read-only endpoints over a round's hand-authored narrative:
`GET /api/competition/rounds/{round_id}/narrative` serves one round's `NARRATIVE.json` verbatim, and
`GET /api/competition/next-round` assembles a briefing for whichever round would run next -- its
would-be id, whether a plan has actually been pre-registered for it, and what the previous round left
open.

Thin on purpose, same as `app.api.competition` and `app.api.competition_findings`: every real
judgement lives one layer down, in `app.tournament.narrative` (the `NARRATIVE.json` loader and the
`next_round_id`/`plan_path_for` naming logic) and `app.tournament.findings` (the previous round's
carry-forward items). This router only turns those into response models and HTTP status codes.

**`/rounds/{round_id}/narrative` has two distinct 404s, on purpose.** An unknown `round_id` (no
directory at all under the rounds root) and a known round that simply has no authored narrative yet
are different facts a caller might want to render differently -- "this round doesn't exist" versus
"this round exists but nobody has written its story yet" -- so the two get different `detail` strings
rather than being collapsed into one generic "not found".

**`/next-round` is always 200, never 404 or 500 -- it is a briefing, not a lookup.** There is always
*some* answer to "what would the next round be called and is it ready", even when there is no previous
round, no plan file, and nothing to carry forward; those are exactly the states `blockers` exists to
report. See `app.tournament.narrative`'s module docstring for the honesty requirement this endpoint is
built to satisfy: naming a round is not the same as clearing it to run, and this endpoint's whole job
is to keep that distinction visible rather than implying readiness just because an id was computed.

**Why `carries_forward` reuses `app.api.competition_findings.RoundFindingModel` instead of a second
shape.** `/api/competition/rounds/{round_id}/findings` already serves exactly this object -- id, kind,
title, body, source, `carries_forward` -- for a round's own written record; a second, parallel
"open item" shape here would just be that same fact represented twice, one copy of which would
eventually drift from the parser that actually produces it (`app.tournament.findings.list_findings`).
This module calls that same parser for the *previous* round and keeps only the entries whose
`carries_forward` flag is already `True` -- it does not re-parse `REPORT.md`/`SELECTION.md`/
`DEFECTS.md` itself, and does not invent a filtering rule of its own: it is the identical heuristic
`app.tournament.findings`'s module docstring already describes and caveats, applied here for a
different consumer.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, ConfigDict

from app.api.competition_findings import RoundFindingModel
from app.tournament import findings, narrative, results

router = APIRouter(prefix="/api/competition", tags=["competition"])

#: `round_id` is interpolated into a filesystem path (`rounds_root / round_id`), so it is bounded and
#: pattern-checked before it ever reaches a path join -- copied verbatim from
#: `app.api.competition_findings.RoundIdPath` rather than imported, per that module's own docstring on
#: why this programme's routers each carry their own copy rather than sharing validation types.
RoundIdPath = Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]

#: The bold disclaimer line every round plan under `strategy-program/` opens with (see e.g.
#: `strategy-program/ROUND-14-PLAN.md`'s second paragraph). Skipped by `_extract_focus` below so the
#: extracted `focus` is the plan's actual opening statement, not this boilerplate repeated on every
#: round.
_DISCLAIMER_PREFIX = "**Not investment advice"
# The other formulaic paragraph every recent plan opens with, immediately after the disclaimer. See
# `_extract_focus` for the measurement that put it here: without this, four of the seven real plan
# files report their pre-registration stamp as the round's focus.
_PRE_REGISTERED_PREFIX = "**Pre-registered"


class NextRoundBriefing(BaseModel):
    """`/api/competition/next-round`'s body -- see the module docstring for why this is always a 200
    and why `blockers` exists rather than a 404 or 409."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    previous_round_id: str | None
    """The newest existing round, or `None` when no round has ever run."""
    next_round_id: str
    """The id the next round would have -- see `app.tournament.narrative.next_round_id`. Naming it
    does not mean it is ready to run; see `pre_registered` and `blockers`."""
    plan_path: str | None
    """Repo-relative path to the next round's plan file, only when it actually exists; `None`
    otherwise (never a guessed or would-be path)."""
    pre_registered: bool
    """Whether `plan_path` exists -- i.e. whether a plan was committed before this briefing was
    requested, which `strategy-program/PROTOCOL.md` §2 requires before any run for that round."""
    focus: str | None
    """The plan file's first prose paragraph (H1 title and the standard disclaimer line skipped), or
    `None` when there is no plan file or its shape did not yield one."""
    carries_forward: list[RoundFindingModel]
    """The previous round's own findings whose `carries_forward` flag is `True` -- see the module
    docstring on why this reuses `app.tournament.findings.list_findings` rather than a second parser.

    **This is a heuristic, not a hard fact -- see `authored_carries_forward` for the authoritative
    list.** `app.api.competition_findings`'s own module docstring states the caveat this field
    inherits verbatim: "`carries_forward` is a heuristic keyword match over prose
    (`app.tournament.findings.OPEN_ITEM_KEYWORDS`) for anything that is not a `DEFECTS.md` entry...
    Both will occasionally be wrong in the specific way heuristics are wrong -- a genuinely open item
    phrased without any of the keywords reads as settled, and vice versa. A caller rendering
    `carries_forward` as a hard fact rather than a 'the parser's best read' signal is the mistake this
    docstring exists to prevent." A UI showing both fields should lead with
    `authored_carries_forward` and label this one as the parser's read, not the round's own word."""
    authored_carries_forward: list[str]
    """The previous round's own hand-written `NARRATIVE.json.carries_forward` -- a human's word on
    what the next round must apply, not a heuristic's. Authoritative where `carries_forward` above is
    a guess: a `NARRATIVE.json` author wrote this list from the round's actual conclusions, the same
    way every other `RoundNarrative` field is prose someone committed rather than something this
    module inferred (see `app.tournament.narrative`'s module docstring). `[]` when the previous round
    has no authored narrative yet -- an ordinary, expected state (most rounds will not have one), not
    an error."""
    blockers: list[str]
    """Plain, one-sentence, actionable reasons this round is not ready to run. Empty only when a plan
    is committed and a previous round exists to have carried anything forward from."""


def _extract_focus(plan_text: str) -> str | None:
    """The plan file's first prose paragraph: skip the leading H1 title and the two formulaic
    metadata paragraphs this programme opens every plan with, then return the next one verbatim.

    Deliberately simple and defensive, per this router's brief: paragraphs are split on a blank line,
    each candidate is checked against the skip rules, and anything unexpected (an empty file, a file
    that is nothing *but* a title and its front matter) falls through to `None` rather than raising --
    a missing `focus` degrades the briefing, it does not break it.

    **Why `**Pre-registered` is skipped alongside the disclaimer.** Measured against the seven real
    plan files, skipping only the disclaimer returned the pre-registration notice as the "focus" for
    four of them -- rounds 10, 11, 12 and 14 all open with a bold `**Pre-registered <date>, before any
    ... exists.**` paragraph. That line is the programme's integrity stamp (`PROTOCOL.md` §2 phase 2)
    and it is formulaic front matter, not a statement of what the round asks; surfacing it in a UI box
    labelled "what the next round asks" would show boilerplate identical across rounds. Rounds 4, 5
    and 6 carry no such line and were already returning real prose -- they are unaffected.

    This stays a best-effort read of hand-written prose, which is exactly why the *authored*
    narrative, not this function, is the authoritative record everywhere one exists. See
    `NextRoundBriefing.authored_carries_forward`.
    """
    for paragraph in plan_text.split("\n\n"):
        stripped = paragraph.strip()
        if not stripped:
            continue
        # A heading of any level, not just the H1: skipping only `# ` left rounds 10/11/12/14
        # returning their `---` rule, and past that sits the section heading rather than its prose.
        if stripped.startswith("#"):
            continue
        # The horizontal rule these plans put between front matter and the body.
        if set(stripped) <= {"-"}:
            continue
        if stripped.startswith(_DISCLAIMER_PREFIX):
            continue
        if stripped.startswith(_PRE_REGISTERED_PREFIX):
            continue
        return stripped
    return None


def _finding_model(data: findings.RoundFindingData) -> RoundFindingModel:
    """`findings.RoundFindingData` -> the wire model -- field-for-field the same conversion
    `app.api.competition_findings._finding_model` performs, kept as this router's own private copy
    rather than importing that one, per this codebase's established "routers do not share private
    helpers across modules" convention (see `RoundIdPath`'s docstring above for the same reasoning
    applied to a validation type instead of a converter)."""
    return RoundFindingModel(
        id=data.id,
        round_id=data.round_id,
        kind=data.kind,  # type: ignore[arg-type]
        title=data.title,
        body=data.body,
        source=data.source,
        carries_forward=data.carries_forward,
    )


@router.get("/rounds/{round_id}/narrative", response_model=narrative.RoundNarrative)
def round_narrative(round_id: RoundIdPath) -> narrative.RoundNarrative:
    """One round's `NARRATIVE.json`, verbatim.

    404 when `round_id` has no directory at all under the rounds root (`detail` says the round is
    unknown). 404 with a *different* `detail` when the round's directory exists but holds no
    `NARRATIVE.json` -- that round has simply not had its story written yet, which is a normal state
    for most rounds, not a broken one. 422 when `NARRATIVE.json` exists but fails to parse (see
    `app.tournament.narrative.MalformedNarrativeError`) -- a data problem to surface, not a missing
    resource, matching how `app.api.competition.leaderboard` turns its own malformed-data `ValueError`
    into a 422 rather than a 404.
    """
    round_dir = narrative.ROUNDS_ROOT / round_id
    if not round_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"no such round: {round_id!r}")

    try:
        data = narrative.load_narrative(round_id)
    except narrative.MalformedNarrativeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if data is None:
        raise HTTPException(
            status_code=404,
            detail=f"round {round_id!r} has no authored narrative (no NARRATIVE.json)",
        )
    return data


@router.get("/next-round", response_model=NextRoundBriefing)
def next_round() -> NextRoundBriefing:
    """A briefing for whichever round would run next -- always 200, see the module docstring.

    `previous_round_id` is the newest round under the rounds root (or `None` if there is none).
    `next_round_id` is `app.tournament.narrative.next_round_id`'s answer -- a free directory name, not
    a claim of readiness. `pre_registered`/`plan_path`/`focus` report whether that round's plan has
    actually been committed under `strategy-program/`. `carries_forward` is the previous round's own
    `carries_forward=True` findings, reusing `app.tournament.findings.list_findings` rather than
    re-parsing anything -- a heuristic read over prose, per `NextRoundBriefing.carries_forward`'s own
    docstring. `authored_carries_forward` is the previous round's hand-written `NARRATIVE.json`
    `carries_forward` list instead -- the authoritative counterpart, `[]` (not an error) when that
    round has no authored narrative. `blockers` collects, in plain language, every reason this round
    is not ready: no committed plan (quoting `PROTOCOL.md` §2's pre-registration rule), no previous
    round to have carried anything forward from, a previous round whose findings could not be loaded,
    or a previous round whose narrative was malformed.
    """
    root = narrative.ROUNDS_ROOT
    round_ids = results.list_round_ids(root)
    previous_round_id = round_ids[0] if round_ids else None

    next_id = narrative.next_round_id(rounds_root=root)
    plan_file = narrative.plan_path_for(next_id)
    pre_registered = plan_file.is_file()

    n = results.round_sequence(next_id)
    plan_path = f"strategy-program/ROUND-{n}-PLAN.md" if pre_registered else None
    focus = _extract_focus(plan_file.read_text(encoding="utf-8")) if pre_registered else None

    blockers: list[str] = []
    if not pre_registered:
        blockers.append(
            "No plan file committed for the next round yet -- strategy-program/PROTOCOL.md §2 "
            'requires a round to be pre-registered before it runs: "A card edited after any result '
            'exists is not a strategy, it is a memory of one."'
        )
    if previous_round_id is None:
        blockers.append("No previous round found -- there is nothing yet to carry forward.")

    carries_forward: list[RoundFindingModel] = []
    if previous_round_id is not None:
        try:
            prev_data = findings.list_findings(previous_round_id, rounds_root=root)
        except findings.RoundNotFoundError:
            blockers.append(
                f"Previous round {previous_round_id!r} has no findings source to carry forward from."
            )
        else:
            carries_forward = [_finding_model(f) for f in prev_data.follow_ups]

    authored_carries_forward: list[str] = []
    if previous_round_id is not None:
        try:
            previous_narrative = narrative.load_narrative(previous_round_id, rounds_root=root)
        except narrative.MalformedNarrativeError as exc:
            # This endpoint is a briefing, never a 500 -- see the module docstring. A broken
            # `NARRATIVE.json` on the previous round is worth surfacing as a blocker, the same as any
            # other reason `authored_carries_forward` could not be trusted, rather than crashing a
            # page whose whole job is to say what is and is not ready.
            blockers.append(f"Previous round {previous_round_id!r}'s narrative is malformed: {exc}")
        else:
            if previous_narrative is not None:
                authored_carries_forward = list(previous_narrative.carries_forward)

    return NextRoundBriefing(
        previous_round_id=previous_round_id,
        next_round_id=next_id,
        plan_path=plan_path,
        pre_registered=pre_registered,
        focus=focus,
        carries_forward=carries_forward,
        authored_carries_forward=authored_carries_forward,
        blockers=blockers,
    )

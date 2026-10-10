"""A finished generation's standings + findings + history -> a model-written post-mortem.

`review_generation` is the one function this module exports. It is phase 6 to
`app.agents.designer.design_generation`'s phase 1: where the designer reads what the *previous*
generation found and proposes what to try next, this module reads what the *just-finished* generation
actually did and writes an account of it -- a verdict, prose about why, a note on every candidate that
ran (not only the winner), and, because the owner granted it, proposed changes to how the next
generation should be configured.

**This never replaces `app.evolution.feedback.derive_findings`.** That function is fixed, deterministic
rules over a set of standings; two passes over the same standings produce the same findings, which is
what lets a finding be trusted as a measurement rather than read as an opinion. Nothing about that
changes here. `derive_findings`'s output is handed to this module as *input* -- see `_format_findings`
below -- and `GenerationReview` is deliberately a different, model-authored thing sitting beside it,
never instead of it. `strategy-program/AGENTS-INTEGRATION-PLAN.md` Phase F is explicit that phases 3-5
(eligibility, running, scoring) stay deterministic and serial; this module is phase 6, and phase 6
alone.

**Validate, never repair -- the same line `app.agents.designer` already draws, held here for a
different failure shape.** A `ProposedCard` that fails validation describes a strategy that would not
be what its `rationale` claims; a `GenerationReview` that fails validation would either state a number
it did not compute or silently drop a candidate the deterministic rules never would have. Both are
refused for the whole response at once, raising `app.agents.models.AgentUnavailable`, rather than
patched -- see `_validate_review` below for exactly what is checked and why each check exists.

**The no-measurement check is mechanical, not a `pydantic` validator.** `app.agents.review_models`'s
own module docstring explains why: `app.agents.client.call_structured` constructs the model's parsed
response inside a `try` block that only catches `anthropic.*` exceptions, so a `field_validator` on
`CandidateNote`/`ReviewDirection`/`ProposedAmendment` that raised there would surface as a bare
`pydantic.ValidationError` rather than the `AgentUnavailable` every other failure in this package
degrades to. `_reject_measurement` below runs after `call_structured` has already returned, exactly
where `app.agents.designer._validate_card` runs its own checks, for the identical reason.

**Reusing `app.report.narrative`'s digit detector rather than writing a second one.** `_is_digit` there
already solved the real problem: an ASCII-only `0-9` check waves through U+0664 (Arabic-Indic four) and
U+216B (Roman numeral twelve), both of which read as a number to anyone looking at the screen. It is
imported here as a private name (it is not in that module's `__all__`) because duplicating a Unicode
category set is exactly the kind of thing that silently drifts from its original the next time someone
tunes one copy and forgets the other -- see that module's own docstring for the enumerated set of
categories (`Nd`, `Nl`, `No`) and why each one is in it.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.agents.client import call_structured
from app.agents.models import DEFAULT_MODEL, AgentBudget, AgentUnavailable
from app.agents.prompts import REVIEWER_SYSTEM_PROMPT
from app.agents.review_models import (
    CandidateNote,
    GenerationReview,
    ProposedAmendment,
    ReviewDirection,
    ReviewVerdict,
)
from app.config import Settings
from app.evolution.models import CardShape, Finding, GenerationOutcome, Genome, LoopConfig, Standing
from app.report.narrative import _is_digit
from app.tournament.purposes import Purpose

__all__ = ["review_generation"]


class _ReviewerOutput(BaseModel):
    """The shape `call_structured` parses a reviewer call's response into.

    Not `GenerationReview` itself -- `generation`, `purpose`, `shape` and `call` are structural facts
    the caller owns, the same line `app.agents.designer._DesignerOutput`'s own docstring draws against
    `AgentProposal.call`. `CandidateNote`, `ReviewDirection` and `ProposedAmendment` are reused
    directly (unlike `designer`'s `ProposedCard` -> `Genome` step, nothing here needs converting into
    a different runtime type before it can be trusted), so this model only adds the fields a caller
    could not have supplied itself: the verdict, the narrative, and the model's own account of every
    candidate and every proposed change.

    **`extra="ignore"`, not `extra="forbid"` -- this is the one boundary in the package where a
    language model writes the JSON.** See `app.agents.review_models`' own module docstring for the
    measured failure that forced it. The first attempt at this fix made the three nested types
    `extra="ignore"` *subclasses* declared here rather than loosening the public models, to keep the
    stored contract strict. That does not work and the tests caught it immediately: a field typed as a
    subclass rejects an instance of its parent (`Input should be a valid dictionary or instance of
    _ReviewDirectionInput [input_type=ReviewDirection]`), so every caller constructing a real
    `ReviewDirection` -- which is every test, and `app.evolution.loop` -- broke. The leniency belongs
    on the public models themselves.
    """

    model_config = ConfigDict(extra="ignore")

    verdict: ReviewVerdict
    post_mortem: str
    per_candidate: list[CandidateNote] = Field(default_factory=list)
    direction: ReviewDirection
    amendments: list[ProposedAmendment] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# User-turn assembly -- every number here is either a config value the caller already set, or copied
# verbatim off a Standing/Finding this package did not compute.
# ---------------------------------------------------------------------------

#: `LoopConfig` fields `app.agents.review_models.AmendmentField` names, in the same order, so the
#: "current configuration" section a reviewer is shown lists exactly the fields it is allowed to
#: propose changing -- a reviewer arguing to change `population` needs to see the current `population`
#: in the same message, not a different subset of `LoopConfig` than its own output vocabulary covers.
_AMENDABLE_FIELDS: tuple[str, ...] = (
    "promotion_margin_pp",
    "holdout_windows",
    "windows",
    "population",
    "elite_count",
    "focus_symbols",
    "avoid_symbols",
    "use_news",
    "news_fraction",
    "rank_by",
    "promotion_consecutive",
    "cooldown_seconds",
)


def _format_lane(purpose: Purpose, shape: CardShape | None) -> str:
    shape_text = shape if shape is not None else "(not determinable from the genomes supplied)"
    return f"Lane: purpose={purpose.value!r}, shape={shape_text!r}"


def _format_windows(outcome: GenerationOutcome) -> str:
    selection = ", ".join(outcome.windows) if outcome.windows else "(none recorded)"
    holdout = ", ".join(outcome.holdout_windows) if outcome.holdout_windows else "(none)"
    return f"Selection windows: {selection}\nHoldout windows (selection never saw these): {holdout}"


def _format_current_config(config: LoopConfig) -> str:
    lines = ["Current configuration (you may propose amending any of these fields by name):"]
    for field in _AMENDABLE_FIELDS:
        lines.append(f"  {field} = {getattr(config, field)!r}")
    return "\n".join(lines)


def _format_standings(standings: Sequence[Standing]) -> str:
    if not standings:
        return "(no standings recorded -- see the failure notice below, if this generation failed)"
    lines = [
        f"Every standing this generation produced ({len(standings)} total -- a CandidateNote is "
        "required for each one, eligible or not, ranked well or not):"
    ]
    for standing in sorted(standings, key=lambda s: s.rank):
        lines.append(
            f"  - rank {standing.rank} {standing.display_name!r} (genome {standing.genome_id}): "
            f"eligible={standing.eligible}, windows_run={standing.windows_run}, "
            f"selection_median={standing.median_excess}, worst={standing.worst_excess}, "
            f"hit_rate={standing.hit_rate}, holdout_median={standing.holdout_median_excess}, "
            f"trades={standing.total_trades}, q_value={standing.q_value}"
        )
    return "\n".join(lines)


def _format_findings(findings: Sequence[Finding]) -> str:
    if not findings:
        return "(no deterministic findings were computed for this generation)"
    lines = ["Deterministic findings app.evolution.feedback already computed from these standings "
             "(stated exactly as computed -- read them, never restate their numbers as your own):"]
    for finding in findings:
        lines.append(f"  - ({finding.kind}) {finding.summary}")
    return "\n".join(lines)


def _format_candidates(genomes: Sequence[Genome], standings: Sequence[Standing]) -> str:
    if not genomes:
        return "(no genome detail was supplied for this generation -- design is unavailable, only " \
               "the standings above)"
    by_id = {genome.genome_id: genome for genome in genomes}
    lines = ["Each candidate's design, for tying an outcome to why it was built that way:"]
    for standing in sorted(standings, key=lambda s: s.rank):
        genome = by_id.get(standing.genome_id)
        if genome is None:
            continue
        lines.append(
            f"  - genome {genome.genome_id} (origin={genome.origin}): universe={list(genome.universe)}; "
            f"traits={genome.traits}; notes={genome.notes!r}"
        )
    return "\n".join(lines)


def _format_history(history: Sequence[GenerationOutcome]) -> str:
    if not history:
        return "(no prior generation recorded for this lane -- this is the earliest one on file)"
    lines = ["This lane's prior generations, oldest first (compact -- for judging whether the search "
             "is still moving or has stalled):"]
    for prior in history:
        if prior.status != "succeeded":
            lines.append(f"  - generation {prior.generation}: status={prior.status}, error={prior.error!r}")
            continue
        eligible = [s for s in prior.standings if s.eligible]
        best = min(eligible, key=lambda s: s.rank) if eligible else None
        best_text = (
            f"best={best.display_name!r} median={best.median_excess}" if best is not None else "no eligible candidate"
        )
        lines.append(
            f"  - generation {prior.generation}: {len(prior.standings)} candidate(s), {best_text}, "
            f"promoted={list(prior.promoted)}"
        )
    return "\n".join(lines)


def _format_failure(outcome: GenerationOutcome) -> str | None:
    if outcome.status != "failed":
        return None
    return (
        f"THIS GENERATION FAILED. Recorded error: {outcome.error!r}. It could not be measured, so "
        "there is little or nothing above in the way of standings or findings. Review the failure "
        "itself: say what the recorded error suggests went wrong, and choose verdict \"broken\" "
        "unless you have a specific reason to call it something else."
    )


def _build_user_turn(
    *,
    outcome: GenerationOutcome,
    config: LoopConfig,
    shape: CardShape | None,
    genomes: Sequence[Genome],
    history: Sequence[GenerationOutcome],
) -> str:
    sections = [
        f"Generation: {outcome.generation}",
        _format_lane(outcome.purpose, shape),
        f"Owner's stated goal (their own words -- context only, never a source of numbers): "
        f"{config.goal or '(none given)'}",
        _format_windows(outcome),
        _format_current_config(config),
        _format_standings(outcome.standings),
        _format_findings(outcome.findings),
        _format_candidates(genomes, outcome.standings),
        _format_history(history),
    ]
    failure = _format_failure(outcome)
    if failure is not None:
        sections.append(failure)
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Validation -- raises AgentUnavailable on any violation, for the whole response at once
# ---------------------------------------------------------------------------


def _reject_measurement(text: str, *, where: str) -> None:
    """Raise `AgentUnavailable` naming `where` if `text` contains any character that reads as a
    number to a reader, in any of Unicode categories `Nd`, `Nl` or `No` -- see this module's own
    docstring for why this check runs here, after `call_structured` returns, rather than as a
    `pydantic` field validator on the model classes themselves."""
    for char in text:
        if _is_digit(char):
            raise AgentUnavailable(
                f"{where}: contains {char!r}, which reads as a number to a reader -- every field the "
                "reviewer writes prose into may state a design choice but never a measurement; see "
                "app.agents.review_models' module docstring for the one field (ProposedAmendment."
                "value) that is exempt and why"
            )


def _validate_review(parsed: _ReviewerOutput, *, outcome: GenerationOutcome) -> None:
    """Raise `AgentUnavailable` naming exactly what is wrong with `parsed`, or return silently.

    Two independent things are checked: that no prose field states a measurement (see
    `_reject_measurement`), and that `per_candidate` covers the generation's whole field -- every
    `genome_id` in `outcome.standings` gets a note, and no note names a `genome_id` no standing has.
    See `app.agents.review_models.CandidateNote`'s own docstring for why both directions of the second
    check matter: an invented id could point a caller at a candidate that never ran, and an omitted id
    reproduces, inside the review that exists to catch it, the exact "only the winner matters" blind
    spot a median-only ranking already has.
    """
    _reject_measurement(parsed.post_mortem, where="post_mortem")
    _reject_measurement(parsed.direction.headline, where="direction.headline")
    for index, hypothesis in enumerate(parsed.direction.hypotheses):
        _reject_measurement(hypothesis, where=f"direction.hypotheses[{index}]")

    standing_ids = {standing.genome_id for standing in outcome.standings}
    seen_ids: set[str] = set()
    for note in parsed.per_candidate:
        _reject_measurement(note.note, where=f"per_candidate[{note.genome_id!r}].note")
        if note.genome_id not in standing_ids:
            raise AgentUnavailable(
                f"per_candidate names genome_id {note.genome_id!r}, which is not among this "
                f"generation's {len(standing_ids)} standing(s) -- a candidate that never ran cannot "
                "be reviewed"
            )
        seen_ids.add(note.genome_id)

    missing = standing_ids - seen_ids
    if missing:
        raise AgentUnavailable(
            f"per_candidate omits {sorted(missing)} -- every standing in this generation's field "
            "requires a note, including the ineligible and the unranked, or the review reproduces "
            "the median-only ranking's blind spot instead of catching it"
        )

    for index, amendment in enumerate(parsed.amendments):
        _reject_measurement(amendment.reason, where=f"amendments[{index}].reason")


# ---------------------------------------------------------------------------
# GenerationOutcome/Genome -> shape
# ---------------------------------------------------------------------------


def _infer_shape(genomes: Sequence[Genome]) -> CardShape | None:
    """The lane's card shape, when `genomes` unambiguously has one.

    Unlike `app.agents.designer.design_generation` (always asked to design for one named shape),
    `review_generation` is not given a `shape` parameter -- a `GenerationOutcome` does not carry one
    itself, and the caller may not always have the generation's genomes on hand to supply it
    explicitly. `None` is returned rather than guessed at when `genomes` is empty or (structurally
    unlikely, since a lane is one purpose crossed with one shape by construction) mixes shapes; see
    `app.agents.review_models.GenerationReview.shape`'s own docstring for what a caller should read
    into a `None` here.
    """
    shapes = {genome.shape for genome in genomes}
    if len(shapes) == 1:
        return next(iter(shapes))
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def review_generation(
    *,
    outcome: GenerationOutcome,
    config: LoopConfig,
    settings: Settings,
    budget: AgentBudget,
    genomes: Sequence[Genome] = (),
    history: Sequence[GenerationOutcome] = (),
) -> tuple[GenerationReview, AgentBudget]:
    """One model-written post-mortem for `outcome`, plus the budget after paying for the call.

    `genomes` should be this generation's own `Genome`s (matched to `outcome.standings` by
    `genome_id`) -- optional and defaulting to empty because a caller reviewing an old generation may
    not have them readily on hand, in which case the review still runs on standings and findings
    alone, just without the "why was this candidate built this way" context genomes provide and
    without an inferred `shape` (see `_infer_shape`).

    `history` should be this same lane's own prior `GenerationOutcome`s, oldest first -- never merely
    "the generation immediately prior" in a loop that interleaves multiple lanes, exactly the
    distinction `app.evolution.feedback.derive_findings`'s own docstring draws for its
    `previous_generation` parameter. Optional and defaulting to empty for the same reason: the first
    generation in a lane has no history to show.

    On `outcome.status == "failed"`, this still runs and still calls the model -- a failed generation
    deserves a review naming the likely cause, not silence. `_format_failure` puts `outcome.error` in
    the user turn and asks explicitly for `verdict="broken"`; nothing in this function enforces that
    the model actually chose it, since a *succeeded* generation that measured nothing meaningful can
    honestly deserve the same verdict, and the mapping from status to verdict is guidance the prompt
    gives, not a structural fact this module is positioned to check.

    Raises `app.agents.models.AgentUnavailable` or `BudgetExhausted` on any failure -- missing
    credentials, an exhausted budget, a refusal, or a model response that fails validation. This
    function never falls back to anything itself; that is the caller's job, exactly as
    `app.agents.designer.design_generation`'s own docstring describes for the phase-1 half of this
    same package.
    """
    shape = _infer_shape(genomes)
    user_text = _build_user_turn(outcome=outcome, config=config, shape=shape, genomes=genomes, history=history)

    model = config.agent_model or DEFAULT_MODEL
    parsed, call, new_budget = call_structured(
        role="reviewer",
        system=REVIEWER_SYSTEM_PROMPT,
        user=user_text,
        output_format=_ReviewerOutput,
        model=model,
        settings=settings,
        budget=budget,
        effort="high",
    )

    _validate_review(parsed, outcome=outcome)

    review = GenerationReview(
        generation=outcome.generation,
        purpose=outcome.purpose,
        shape=shape,
        verdict=parsed.verdict,
        post_mortem=parsed.post_mortem,
        per_candidate=tuple(parsed.per_candidate),
        direction=parsed.direction,
        amendments=tuple(parsed.amendments),
        call=call,
    )
    return review, new_budget

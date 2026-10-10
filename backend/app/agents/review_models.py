"""The reviewer's output contract: what a model may say about a finished generation.

`app.agents.designer` is phase 1 -- an agent proposing candidates before anything is measured. This
module is the shape of phase 6: an agent writing a post-mortem *after* `app.tournament` has run every
candidate and `app.evolution.feedback.derive_findings` has already produced its fixed, deterministic
findings. Nothing here replaces that deterministic review; `GenerationReview` sits beside it as a
second opinion with the one thing fixed rules cannot have -- judgement about the *set* of candidates
as a set, not just the one at the top.

**Why this package needs its own `GenerationReview` and not a repurposed `Finding`.** A `Finding`
(`app.evolution.models`) is one fixed-shape sentence a deterministic rule computed; `derive_findings`
runs the same seven rules over any standings and gets the same seven-or-so findings back. A model
reviewing a generation is not filling in blanks in a template -- it is deciding what the generation
*means* (`verdict`), writing prose about why (`post_mortem`), judging every candidate individually
(`per_candidate`), and proposing where the search goes next (`direction`, `amendments`). None of that
has a `FindingKind` shaped for it, and forcing it into one would either lose the judgement or corrupt
`derive_findings`'s own guarantee that two passes over the same standings produce the same output --
a model is not a pure function of its input, and pretending its output belongs to the same type as a
pure function's output would blur a line this codebase otherwise draws everywhere.

**The one rule that decides every field below: a model may choose a number but may never claim one.**
`strategy-program/AGENTS-INTEGRATION-PLAN.md` section 0 states the constraint this whole package
exists under: "an agent may propose, name, argue and select. an agent may never emit a number." Every
prose field on every model here -- `CandidateNote.note`, `ProposedAmendment.reason`,
`ReviewDirection.headline`, every element of `ReviewDirection.hypotheses`, and
`GenerationReview.post_mortem` -- is mechanically checked by `app.agents.reviewer` for any character
in Unicode category `Nd`, `Nl` or `No` (reusing `app.report.narrative`'s own detector rather than
writing a second one that could quietly diverge from it). That check does not live on these models as
a `pydantic` field validator: `app.agents.client.call_structured` constructs the model's structured
response internally, inside a `try` block that only catches `anthropic.*` exceptions, and a
`field_validator` raising there would surface as a bare `pydantic.ValidationError` rather than the
`AgentUnavailable` every other failure in this package degrades to -- the exact shape
`app.agents.designer`'s own docstring already chose for `ProposedCard` ("validate, never repair"),
applied here for the same reason.

**`ProposedAmendment.value` is the one field this rule does not touch, and the exemption is load-
bearing rather than an oversight.** A promotion margin, a window list, a population size -- these are
*control settings the agent is choosing for the next generation*, not measurements it is claiming
about this one. The distinction is the same one `app.agents.designer`'s own module docstring draws
for a proposed card's trait values ("those are *hypotheses*... a claim about what is worth testing,
which the backtest then judges") -- an amendment's `value` is exactly that kind of number, chosen
before anything runs against it, never a return or a q-value read off a result. Losing this exemption
would make the reviewer unable to propose e.g. `promotion_margin_pp=25` at all, which would silently
remove the authority `strategy-program/EVOLUTION-LOOP.md` section 4 and the owner both grant it.
`app.evolution.amend` (owned elsewhere) is what actually applies a `value`; this module only carries
it and checks that `field` names something `AmendmentField` recognises.

**The whole field, not the winner.** `app.evolution.feedback.derive_findings(kind="winner")` names
rank 1 and `app.evolution.feedback.select_elites` breeds the top `elite_count` by median alone --
correct for what each is for, but neither one looks at candidate 6 of 8, the one that ranked mid-pack
on the selection median and was the only candidate whose holdout median stayed positive. A median-
only ranking cannot see that candidate as anything but average; a reviewer that only ever wrote about
the winner would reproduce the same blind spot one layer up. `CandidateNote` exists so every standing
-- eligible or not, ranked first or last -- gets a `keep` decision and a reason, and
`app.agents.reviewer` refuses a response that is missing one.

Every model here subclasses `app.agents.models._Frozen` (`frozen=True, extra="forbid"`) -- imported
from that module rather than redefined -- and then **re-opens `extra` to `"ignore"`**, which is the
one place this package departs from the house default and needs its reason on the record.

**The measured failure.** On the first real reviewer call ever made, the model returned a complete,
well-formed review: correct verdict, a note for every candidate, amendments naming valid
`AmendmentField`s with reasoned prose. It also attached `"expandedValue": null` to each amendment
object. `extra="forbid"` rejected the whole response over two null keys carrying no information, and
the generation finished with no review at all. The schema was not the problem -- `model_json_schema()`
on an `extra="forbid"` model emits `"additionalProperties": false`, so the model was told and emitted
the key regardless.

**Why loosening here costs nothing.** `extra="forbid"` earns its place on a model whose input is a
config file, a stored record, or another module's call -- there, an unrecognised key is a typo or a
schema drift, and accepting it silently is how a field quietly stops being read. These models have
exactly one input path that is not our own code: `app.agents.reviewer._ReviewerOutput`, parsing JSON a
language model wrote. Nothing reads `gen{N:04d}/REVIEW.json` back *through* these types --
`app.evolution.history` deliberately treats that file as an untyped `dict` so the evolution package
does not depend on this one -- so the strictness only ever applied at the model boundary.

**What is still refused.** This is not "accept anything". A response missing a required field, giving
a field the wrong type, or naming an `AmendmentField` that does not exist is rejected exactly as
before -- those are the model getting the *answer* wrong. An unknown key is the model getting the
*envelope* wrong while the answer is intact; the key is dropped either way, and the only thing
`forbid` adds is that the review is destroyed with it. `app.agents.designer`'s "validate, never
repair" rule is untouched: ignoring a field nobody declared is not repairing one that was.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field

from app.agents.models import AgentCall, _Frozen
from app.evolution.models import CardShape
from app.tournament.purposes import Purpose

__all__ = [
    "AmendmentField",
    "CandidateNote",
    "GenerationReview",
    "ProposedAmendment",
    "ReviewDirection",
    "ReviewVerdict",
]

#: Re-opens `extra` on every model in this module. `_Frozen` sets `extra="forbid"`; these four types
#: are parsed from JSON a language model wrote, which is the one input path in this package where an
#: unrecognised key is noise rather than a defect. See this module's docstring for the review that was
#: destroyed by two `"expandedValue": null` keys, and for what this still refuses.
_MODEL_WRITTEN = ConfigDict(extra="ignore")


class CandidateNote(_Frozen):
    """One candidate's place in the post-mortem -- required for **every** standing in the
    generation, not only the ones that ranked well.

    `app.agents.reviewer.review_generation` refuses a response that omits any `genome_id` present in
    `GenerationOutcome.standings`, and refuses one that names a `genome_id` no standing actually has --
    see that module's own docstring for why both directions of that check exist. A note the model
    could not write anything specific about is still required to say so; there is no way to represent
    "skipped" here on purpose, because a reviewer is exactly as likely to skip the candidate that
    quietly did the interesting thing as the one that did nothing.
    """

    model_config = _MODEL_WRITTEN

    genome_id: str

    note: str
    """Prose: what happened to this candidate and why it might matter, in the model's own words.

    Never a measurement -- `app.agents.reviewer` rejects any character in Unicode category `Nd`,
    `Nl` or `No`, mechanically, before this field is trusted for anything. The candidate's actual
    numbers (`Standing.median_excess`, `.holdout_median_excess`, `.q_value`, ...) are already in the
    user turn the model was shown; this field is the judgement about them, not a restatement of them.
    """

    keep: bool
    """Should this genome breed into the next generation?

    Deliberately a second opinion beside `app.evolution.feedback.select_elites`, not a replacement for
    it -- `select_elites` still decides mechanically who actually breeds, by `median_excess` and a
    fixed tie-break, because a model's `keep` is not reproducible the way that selection needs to be.
    What this field is for is the case `select_elites` cannot see at all: a candidate ranked outside
    `elite_count` whose *reason* for being interesting a human reviewer would have flagged -- the
    lone holdout survivor, the one that failed for an instructive reason rather than a boring one --
    surfaced here for a caller (or a future generation's prompt) to act on deliberately, rather than
    silently dropped because it did not clear a median cutoff.
    """


class ReviewDirection(_Frozen):
    """Where the reviewer thinks the search should go next, as argument rather than as a number.

    Every field here is advisory. `app.evolution.loop` (owned elsewhere) decides whether and how to
    act on it; nothing in this package writes `focus_symbols` or `avoid_symbols` back into a
    `LoopConfig` by itself. Keeping the two lists here separate from `ProposedAmendment` even though
    `AmendmentField` also names `"focus_symbols"`/`"avoid_symbols"` is deliberate: this field is the
    reviewer's *argument* for a direction ("the field kept finding an edge in names it didn't ask
    for"), while a `ProposedAmendment` with the same field name is the reviewer actually proposing to
    change the run-wide default. A caller may read one, both, or neither.
    """

    model_config = _MODEL_WRITTEN

    headline: str
    """One line on what this generation showed, before the detail in `post_mortem`. Prose, never a
    measurement -- checked exactly like `CandidateNote.note`."""

    hypotheses: tuple[str, ...] = ()
    """Ideas worth testing next, each written as a falsifiable claim the way
    `app.agents.prompts.DESIGNER_SYSTEM_PROMPT` already asks a card's own `rationale` to be -- a
    hypothesis with no way to be wrong is not one. Every element is checked for a bare measurement
    individually, so one bad hypothesis among several good ones is named precisely rather than
    failing the whole tuple with no indication of which entry was the problem.
    """

    focus_symbols: tuple[str, ...] = ()
    avoid_symbols: tuple[str, ...] = ()

    emphasise_disciplines: tuple[str, ...] = ()
    """Trading disciplines (`ProposedCard`'s own vocabulary -- `"trend"`, `"mean-reversion"`,
    `"momentum"`, `"breakout"`, `"volatility"`, `"pairs-rotation"`, `"risk-managed"`) the reviewer
    thinks the next generation's designer should lean into. Not validated against that vocabulary
    here -- a reviewer naming a discipline the designer's own schema does not recognise is a
    downstream designer's problem to refuse, exactly as `app.agents.designer._validate_card` already
    refuses an unrecognised `discipline` on a proposed card."""

    retire_disciplines: tuple[str, ...] = ()
    """The inverse of `emphasise_disciplines` -- disciplines this generation's evidence argues against
    continuing to explore."""


AmendmentField = Literal[
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
]
"""Every `LoopConfig` field a reviewer may propose to amend for the next generation.

The owner explicitly granted the reviewer authority over the whole run -- gates, windows, steering,
anything -- so this is not a narrowed subset of `LoopConfig`; it is every field
`strategy-program/EVOLUTION-LOOP.md` describes as something a generation-to-generation decision could
reasonably touch. What it excludes is deliberate too: `seed`, `max_workers`, `seat_on_paper_desk`,
`agent_budget_usd`, `agent_model` and `goal` are operational or owner-set choices, not something a
model reviewing search results has grounds to second-guess from a generation's evidence alone.
"""


class ProposedAmendment(_Frozen):
    """One change the reviewer proposes to `LoopConfig` for the next generation.

    Applying it is `app.evolution.amend`'s job (owned elsewhere), not this module's -- see this
    module's own docstring for why `value` is untyped and unvalidated here beyond `field` naming a
    real `AmendmentField`. This model only carries the proposal and its argument; a caller decides
    whether to act on it, and the value's own legality (a margin that cannot be negative, a window
    name that must exist in `strategy-program/WINDOWS.md`) is checked wherever it is actually applied.
    """

    model_config = _MODEL_WRITTEN

    field: AmendmentField

    value: Any
    """The proposed new value, in whatever shape `field` expects on `LoopConfig` (a `Decimal`-
    convertible number for `promotion_margin_pp`, a list of window names for `windows` or
    `holdout_windows`, a bool for `use_news`, and so on).

    **Exempt from the no-measurement rule.** Every other prose field in this package is checked for a
    bare Unicode digit; this one is not, because it is not prose and not a claim about a result -- it
    is a control setting the agent is choosing, the same status `app.agents.designer`'s trait values
    already hold for a proposed card. See this module's own docstring, "the exemption is load-bearing
    rather than an oversight," for why dropping this exemption would be a real regression and not
    tightening: it would leave the reviewer unable to state the one thing this field exists to let it
    state.
    """

    reason: str
    """Why this change, in prose. Checked for a bare measurement exactly like every other prose field
    -- the *argument* for changing `promotion_margin_pp` may never itself contain the number it is
    arguing about; state the reasoning, propose the new setting in `value`.

    `app.agents.prompts.REVIEWER_SYSTEM_PROMPT` requires this reasoning to engage honestly with the
    two arguments against loosening the gate that `strategy-program/EVOLUTION-LOOP.md` sections 2 and
    4 already make -- the 21.2-point margin is a measured noise floor, not a taste, and a holdout that
    feeds back into selection has stopped being one -- rather than simply proposing to relax either
    because results have been thin.
    """


ReviewVerdict = Literal["promising", "inconclusive", "exhausted", "broken"]
"""The reviewer's one-word conclusion about the generation as a whole.

`"promising"` -- something in this generation is worth building on directly. `"inconclusive"` -- no
candidate cleared enough of a bar to say either way; more search, not a pivot, is the right response.
`"exhausted"` -- this lane's current direction (universe, discipline mix, trait ranges) looks played
out; a change of direction is warranted, not just another generation of the same idea. `"broken"` --
reserved for a generation that could not be measured at all (`GenerationOutcome.status == "failed"`,
or every candidate ineligible), where the review is naming a process failure rather than judging a
search result. `app.agents.reviewer` does not enforce a mapping from `GenerationOutcome.status` to
this field mechanically (a *succeeded* generation can still be judged `"broken"` in substance, e.g.
every candidate at zero trades) -- `app.agents.prompts.REVIEWER_SYSTEM_PROMPT` asks for `"broken"` on
a failed generation as guidance the model is expected to follow, not a constraint this module checks.
"""


class GenerationReview(_Frozen):
    """A model's post-mortem on one finished generation of one lane -- the whole of
    `app.agents.reviewer.review_generation`'s output.

    `generation`, `purpose`, `shape` and `call` are structural facts the caller owns, never something
    the model is asked to state about itself: the same line `app.agents.designer.AgentProposal` draws
    against `ProposedCard`, restated here because a model has no way to know its own `call_id` or
    which generation it was actually handed (nor any reason to be trusted if it claimed to).
    """

    model_config = _MODEL_WRITTEN

    generation: int = Field(ge=0)
    purpose: Purpose

    shape: CardShape | None = None
    """The lane's card shape, when it could be determined from the `Genome`s the reviewer was shown.

    `None` rather than a required field because, unlike `app.agents.designer.design_generation` (which
    is always asked to design for one named shape), `review_generation` is handed a
    `GenerationOutcome` that does not itself carry a shape -- `app.agents.reviewer` infers it from the
    `genomes` a caller passed in, and reports `None` when no genomes were passed, or in the
    (structurally unlikely, since a lane is one purpose crossed with one shape by
    `app.agents.prompts.DESIGNER_SYSTEM_PROMPT`'s own definition of a lane) case that the genomes
    supplied mix shapes.
    """

    verdict: ReviewVerdict
    post_mortem: str
    """The reviewer's prose account of the generation as a whole -- what happened, why, and what it
    means. Checked for a bare measurement exactly like every other prose field in this module."""

    per_candidate: tuple[CandidateNote, ...] = ()
    """One entry per standing in the generation that produced this review. See `CandidateNote`'s own
    docstring for why every standing needs one, not only the ones that ranked well."""

    direction: ReviewDirection
    amendments: tuple[ProposedAmendment, ...] = ()
    """Changes proposed for the next generation's `LoopConfig`. May be empty -- a reviewer with
    nothing to change is not required to invent something to say."""

    call: AgentCall

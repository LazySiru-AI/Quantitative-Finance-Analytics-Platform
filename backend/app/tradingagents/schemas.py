"""The pipeline's structured outputs: one frozen Pydantic model per stage shape, plus the pure
functions that turn a parsed value into what the rest of the desk needs from it.

Every stage in `app.tradingagents.pipeline` calls `app.agentdesk.grounding.run_grounded` exactly
once, and that function's contract fixes three things this module has to supply per shape:
`output_format` (one of the models below), `prose_of` (every free-text field concatenated, because
that concatenation is the literal text the grounding gate checks numeric tokens against -- leaving a
field out of `prose_of` would let a fabricated number hide in it, ungrounded and unchecked), and,
once a value comes back, the pair of renderers a stage actually persists: `render_*` becomes
`StageRecord.output_md` (the full report a reader sees) and `summary_*` becomes `StageRecord.summary`
(the one or two sentences a downstream stage is handed instead of the full text -- see
`StageRecord.summary`'s own docstring for why the full text never travels downstream).

**Why the `prose_of_*` and `render_*` functions are not the same function.** They frequently return
overlapping text, but they answer different questions. `prose_of_*` exists only to be fed back into
`app.agentdesk.grounding.check`, so it must be *complete* -- every field that could carry a number --
and need not be readable. `render_*` exists to be read by a person, so it is formatted (headings, a
bold rating line, a placeholder sentence for an unset optional field) in ways `prose_of_*` never
needs to be.

**`parse_rating` is the one function in this module that is never a model call**, mirroring the
discipline `app.tradingagents`'s own package docstring states for the whole pipeline: a model sits in
the *design* of a decision, never in the *scoring* of one. It is a deterministic, two-pass regex over
the portfolio manager's own rendered decision, run once at the end of `app.tradingagents.pipeline.
run_pipeline` to produce `DeskRun.final_rating`.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = [
    "ACTION_3TIER",
    "RATING_5TIER",
    "AnalystReport",
    "DebateArgument",
    "PortfolioDecision",
    "ReflectionNote",
    "ResearchPlan",
    "RiskArgument",
    "TraderProposal",
    "parse_rating",
    "parse_recommendation",
    "prose_of_analyst_report",
    "prose_of_debate_argument",
    "prose_of_portfolio_decision",
    "prose_of_reflection_note",
    "prose_of_research_plan",
    "prose_of_risk_argument",
    "prose_of_trader_proposal",
    "render_analyst_report",
    "render_debate_argument",
    "render_portfolio_decision",
    "render_reflection_note",
    "render_research_plan",
    "render_risk_argument",
    "render_trader_proposal",
    "summary_analyst_report",
    "summary_debate_argument",
    "summary_portfolio_decision",
    "summary_reflection_note",
    "summary_research_plan",
    "summary_risk_argument",
    "summary_trader_proposal",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


Rating5 = Literal["Buy", "Overweight", "Hold", "Underweight", "Sell"]
"""The research manager's and the portfolio manager's own scale -- five tiers because a rating is a
claim about conviction as well as direction (see `PORTFOLIO_MANAGER_SYSTEM`)."""

Action3 = Literal["Buy", "Hold", "Sell"]
"""The trader's coarser scale. Deliberately fewer tiers than `Rating5`: Overweight and Buy both reach
the trader as "add", and the size -- not a sixth tier -- is where that distinction is expressed."""

RATING_5TIER: tuple[str, ...] = ("Buy", "Overweight", "Hold", "Underweight", "Sell")
ACTION_3TIER: tuple[str, ...] = ("Buy", "Hold", "Sell")


# ---------------------------------------------------------------------------
# Text helpers shared by every summary_* function
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_SUMMARY_MAX_LEN = 320


def _first_sentences(text: str, count: int = 2) -> str:
    """The first `count` sentences of `text`, whitespace-collapsed and length-capped.

    A cheap, deterministic stand-in for "the one or two sentences a downstream stage needs" -- no
    second model call, matching this module's own rule that only `report_md`/`argument_md`/etc. are
    ever asked of the model; everything derived from them is plain text processing.
    """
    collapsed = " ".join(text.split())
    if not collapsed:
        return ""
    sentences = _SENTENCE_SPLIT_RE.split(collapsed)
    joined = " ".join(sentences[:count]).strip()
    if len(joined) > _SUMMARY_MAX_LEN:
        joined = joined[: _SUMMARY_MAX_LEN - 1].rstrip() + "…"
    return joined


def _or_not_set(value: str | None, noun: str) -> str:
    return value.strip() if value and value.strip() else f"not set -- {noun} could not be drawn from the evidence"


# ---------------------------------------------------------------------------
# Analysts
# ---------------------------------------------------------------------------


class AnalystReport(_Frozen):
    """One analyst's independent read of the instrument, from its own `EvidencePack` alone."""

    report_md: str
    """The full report: prose and short markdown tables, per `_VOICE` in `prompts.py`."""

    takeaway: str
    """One sentence: the single thing this analyst would tell a reader who reads nothing else."""


def prose_of_analyst_report(value: AnalystReport) -> str:
    return f"{value.report_md}\n\n{value.takeaway}"


def render_analyst_report(value: AnalystReport) -> str:
    return f"{value.report_md.strip()}\n\n**Takeaway:** {value.takeaway.strip()}\n"


def summary_analyst_report(value: AnalystReport) -> str:
    return _first_sentences(value.takeaway, 2) or _first_sentences(value.report_md, 2)


# ---------------------------------------------------------------------------
# Researchers -- the bull/bear debate
# ---------------------------------------------------------------------------


class DebateArgument(_Frozen):
    """One researcher's turn in the bull/bear debate. Same shape as `AnalystReport` -- a full
    argument plus a one-line takeaway -- but kept as a distinct type because the two are never
    interchangeable at a call site: an analyst report and a debate turn are graded against different
    prompts and consumed by different downstream stages."""

    argument_md: str
    takeaway: str


def prose_of_debate_argument(value: DebateArgument) -> str:
    return f"{value.argument_md}\n\n{value.takeaway}"


def render_debate_argument(value: DebateArgument) -> str:
    return f"{value.argument_md.strip()}\n\n**Takeaway:** {value.takeaway.strip()}\n"


def summary_debate_argument(value: DebateArgument) -> str:
    return _first_sentences(value.takeaway, 2) or _first_sentences(value.argument_md, 2)


# ---------------------------------------------------------------------------
# The three judges
# ---------------------------------------------------------------------------


class ResearchPlan(_Frozen):
    """The research manager's verdict on the bull/bear debate."""

    recommendation: Rating5
    rationale: str
    strategic_actions: str


def prose_of_research_plan(value: ResearchPlan) -> str:
    return f"{value.rationale}\n\n{value.strategic_actions}"


def render_research_plan(value: ResearchPlan) -> str:
    return (
        f"**Recommendation: {value.recommendation}**\n\n"
        f"{value.rationale.strip()}\n\n"
        f"### Strategic actions\n\n{value.strategic_actions.strip()}\n"
    )


def summary_research_plan(value: ResearchPlan) -> str:
    return f"{value.recommendation}: {_first_sentences(value.rationale, 1)}"


class TraderProposal(_Frozen):
    """The trader's proposal: an action, and levels drawn from the evidence -- or an honest
    statement that a level cannot be set from what was retrieved. Nothing here executes; see
    `app.tradingagents`'s own module docstring."""

    action: Action3
    reasoning: str
    entry: str | None = None
    stop: str | None = None
    sizing: str | None = None


def prose_of_trader_proposal(value: TraderProposal) -> str:
    """Every free-text field, entry/stop/sizing included -- those three are exactly where a
    fabricated price level would hide, so leaving any of them out of the grounded prose would defeat
    the one check meant to catch it."""
    parts = [value.reasoning, value.entry or "", value.stop or "", value.sizing or ""]
    return "\n".join(part for part in parts if part)


def render_trader_proposal(value: TraderProposal) -> str:
    return (
        f"**Action: {value.action}**\n\n"
        f"- Entry: {_or_not_set(value.entry, 'an entry level')}\n"
        f"- Stop: {_or_not_set(value.stop, 'a stop level')}\n"
        f"- Sizing: {_or_not_set(value.sizing, 'a size')}\n\n"
        f"{value.reasoning.strip()}\n"
    )


def summary_trader_proposal(value: TraderProposal) -> str:
    return f"{value.action}: {_first_sentences(value.reasoning, 1)}"


# ---------------------------------------------------------------------------
# The risk panel
# ---------------------------------------------------------------------------


class RiskArgument(_Frozen):
    """One risk analyst's turn: their perspective on the trader's proposal as it currently stands."""

    stance_summary: str
    """A short statement of this turn's position -- doubles as the downstream summary, since the
    risk prompts already ask each analyst to state their stance plainly (see `_RISK_COMMON`)."""

    argument: str


def prose_of_risk_argument(value: RiskArgument) -> str:
    return f"{value.stance_summary}\n\n{value.argument}"


def render_risk_argument(value: RiskArgument) -> str:
    return f"**{value.stance_summary.strip()}**\n\n{value.argument.strip()}\n"


def summary_risk_argument(value: RiskArgument) -> str:
    return _first_sentences(value.stance_summary, 2) or _first_sentences(value.argument, 2)


class PortfolioDecision(_Frozen):
    """The portfolio manager's final decision -- the run's own `DeskRun.final_md` and, via
    `parse_rating`, its `DeskRun.final_rating`."""

    rating: Rating5
    executive_summary: str
    investment_thesis: str
    price_target: str | None = None
    time_horizon: str | None = None


def prose_of_portfolio_decision(value: PortfolioDecision) -> str:
    parts = [
        value.executive_summary,
        value.investment_thesis,
        value.price_target or "",
        value.time_horizon or "",
    ]
    return "\n".join(part for part in parts if part)


def render_portfolio_decision(value: PortfolioDecision) -> str:
    lines = [
        f"rating: {value.rating}",
        "",
        "## Executive summary",
        value.executive_summary.strip(),
        "",
        "## Thesis",
        value.investment_thesis.strip(),
    ]
    if value.price_target:
        lines += ["", f"**Price target:** {value.price_target.strip()}"]
    if value.time_horizon:
        lines += ["", f"**Time horizon:** {value.time_horizon.strip()}"]
    return "\n".join(lines) + "\n"


def summary_portfolio_decision(value: PortfolioDecision) -> str:
    return f"{value.rating}: {_first_sentences(value.executive_summary, 2)}"


# ---------------------------------------------------------------------------
# The reflector -- runs after an outcome is known, never during a decision
# ---------------------------------------------------------------------------


class ReflectionNote(_Frozen):
    """Two to four sentences on one past decision, now that its outcome is known -- see
    `REFLECTOR_SYSTEM`. The single field this model carries is deliberately unstructured: the lesson
    is prose meant to be read by a future portfolio manager, not parsed by code."""

    lesson: str


def prose_of_reflection_note(value: ReflectionNote) -> str:
    return value.lesson


def render_reflection_note(value: ReflectionNote) -> str:
    return f"{value.lesson.strip()}\n"


def summary_reflection_note(value: ReflectionNote) -> str:
    return _first_sentences(value.lesson, 2)


# ---------------------------------------------------------------------------
# Deterministic rating extraction -- never a model call
# ---------------------------------------------------------------------------

_RATING_PATTERN = "|".join(RATING_5TIER)
_RATING_LINE_RE = re.compile(rf"(?im)^\s*rating\s*[:\-]\s*({_RATING_PATTERN})\b")
_RATING_WORD_RE = re.compile(rf"(?i)\b({_RATING_PATTERN})\b")


def _canonical_rating(word: str) -> str:
    lowered = word.lower()
    for candidate in RATING_5TIER:
        if candidate.lower() == lowered:
            return candidate
    return "Hold"  # unreachable: both regexes above are built from RATING_5TIER itself


def parse_rating(text: str) -> str:
    """The portfolio manager's rating, extracted deterministically from its own rendered decision.

    Two passes, mirroring the discipline this pipeline holds everywhere else: a model may design and
    argue a decision, but nothing downstream may re-score one with a second model call. Pass one looks
    for an explicit `rating: X` line -- `render_portfolio_decision` always writes one, as its first
    line -- and pass two, for any text that reached this function some other way (a hand-edited
    decision, a test fixture), falls back to the first occurrence of any of the five rating words
    anywhere in the text. Text carrying no recognizable rating at all defaults to `"Hold"`, the
    deliberately inert middle tier that never reads as an instruction to act.
    """
    line_match = _RATING_LINE_RE.search(text)
    if line_match:
        return _canonical_rating(line_match.group(1))
    word_match = _RATING_WORD_RE.search(text)
    if word_match:
        return _canonical_rating(word_match.group(1))
    return "Hold"


_RECOMMENDATION_LINE_RE = re.compile(
    rf"(?im)^\s*[*_]*\s*Recommendation\s*[*_]*\s*[:\-]\s*[*_]*\s*({_RATING_PATTERN})\b"
)


def parse_recommendation(text: str) -> str:
    """The research manager's recommendation, extracted deterministically from its own rendered
    research plan -- the call made *before* the trader and risk panel ever see the name.

    Same two-pass discipline as `parse_rating`, and for the same reason: a model may design and
    argue a recommendation, but nothing downstream may re-score one with a second model call. Pass
    one looks for the stable prefix `render_research_plan` always writes as the first line --
    `"**Recommendation: X**"` -- tolerant of the surrounding markdown emphasis and of a dash instead
    of a colon, mirroring `app.workflow.verdict.parse_verdict`'s tolerance for the same reason. Pass
    two, for text that reached this function some other way, falls back to the first occurrence of
    any of the five rating words anywhere in the text. Text carrying no recognizable tier at all
    defaults to `"Hold"`, the same inert default `parse_rating` uses.

    Exists so a caller (`app.tradingagents.analysis.rating_flip_rate`) can compare this pre-risk-panel
    call against the portfolio manager's post-risk-panel `DeskRun.final_rating` -- the one point in
    the stored record where the risk panel's actual effect on the desk's decision is visible, since
    the analysts themselves emit no structured rating for the debate to flip.
    """
    line_match = _RECOMMENDATION_LINE_RE.search(text)
    if line_match:
        return _canonical_rating(line_match.group(1))
    word_match = _RATING_WORD_RE.search(text)
    if word_match:
        return _canonical_rating(word_match.group(1))
    return "Hold"

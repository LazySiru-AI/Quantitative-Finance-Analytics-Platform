"""Shared contract for reports and the grounding of their prose.

The package docstring states the split: :mod:`app.report.builder` computes facts,
:mod:`app.report.narrative` writes prose that may only reference them. This module is where that
boundary is made unrepresentable to cross.

**A narrative holds no numbers.** :class:`NarrativeDraft` carries *template* text in which every
figure is a ``{{fact:id}}`` reference. Values are substituted from the bundle at render time, so a
stored narrative cannot drift from the data it describes -- update the bars, re-render, and the prose
moves with them or fails loudly. A draft that quotes ``-90.5%`` directly would be frozen at the moment
someone wrote it and silently wrong afterwards, which is the failure mode that makes a stale report
worse than no report.

**A bare numeral in a draft is a rejection, not a warning.** :func:`~app.report.narrative.verify`
refuses any digit outside a fact reference. This is deliberately blunt: the alternative is deciding,
per number, whether the writer had a source, and that decision cannot be made by reading the text.
Parameters that legitimately appear in prose -- the 50 in a 50/200 crossover -- are emitted by the
builder as facts like any other figure, so the strict rule costs nothing except that the builder must
have thought about what the prose is allowed to say.

**What this does not catch, stated plainly.** A verbal quantity -- "roughly a third", "nearly
doubled" -- carries no digits and passes. The check is a guarantee about *numerals*, not about
truthfulness, and :class:`GroundingReport` says so rather than implying a stronger property. A model
that writes "the drawdown was catastrophic" is making an unsourced claim this module cannot see.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.backtest.models import DrawdownProfile, StrategyResult
from app.db.duck import Interval
from app.market.models import MarketWarning, Profile, Quote
from app.rules.models import DecisionTable

__all__ = [
    "FACT_REFERENCE_PATTERN",
    "Fact",
    "FactBundle",
    "FactKind",
    "GroundingReport",
    "GroundingViolation",
    "NarrativeDraft",
    "RenderedNarrative",
    "Report",
    "ReportSection",
    "ViolationKind",
]

#: The only syntax by which a narrative may contain a number: ``{{fact:drawdown.max_depth}}``.
#:
#: Ids are lowercase dotted tokens. Restricting the alphabet keeps the pattern anchored -- a
#: permissive one would let ``{{fact:anything at all}}`` parse and then fail lookup with a confusing
#: message, instead of being rejected as malformed where the mistake actually is.
FACT_REFERENCE_PATTERN = r"\{\{fact:([a-z0-9_]+(?:\.[a-z0-9_]+)*)\}\}"


class FactKind(StrEnum):
    """How a fact should be rendered. The builder decides; the narrative never formats anything.

    Formatting lives with the fact rather than at the call site because the same number means
    different things in different units, and a percentage rendered as a raw fraction (``0.058``
    where ``5.8%`` was meant) is the kind of error that reads as merely odd rather than as wrong.
    """

    PERCENT = "percent"
    """A fraction rendered as a percentage: ``0.058`` becomes ``5.8%``."""
    SIGNED_PERCENT = "signed_percent"
    """As :attr:`PERCENT` with an explicit sign, for returns and edges where direction is the point."""
    RATIO = "ratio"
    CURRENCY = "currency"
    COUNT = "count"
    DATE = "date"
    TEXT = "text"
    """A non-numeric fact -- an instrument name, an exchange, a verdict token. Still a fact, still
    cited, so a narrative cannot invent a company name any more than it can invent a return."""


class Fact(BaseModel):
    """One computed figure, with the pointer that makes it checkable.

    :attr:`source` is not decoration. A report reader who doubts a number must be able to find out
    which engine produced it and over what window without reading the code, and a fact whose source
    cannot be named is one nobody should have put in a report.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    """Dotted token used in ``{{fact:...}}`` references: ``drawdown.max_depth``."""
    label: str
    """Human-readable name for a table or a tooltip: "Deepest drawdown"."""
    value: float | str | None
    """``None`` is a legitimate value -- a statistic that could not be measured. A fact whose value is
    ``None`` renders as an em dash and **may still be cited**; the alternative is a narrative that
    silently omits a sentence when data is missing, which reads as though the question was never
    asked."""
    kind: FactKind
    unit: str = ""
    source: str
    """Which engine and which window: ``drawdown/close/SOXL 2010-03-11..2026-08-10``,
    ``sec_edgar/0000320193-24-000123``. Specific enough to re-derive."""
    as_of: dt.date | None = None


class FactBundle(BaseModel):
    """Everything a report is allowed to say, keyed by fact id.

    The bundle is the report's whole vocabulary of numbers. Assembling it is
    :mod:`app.report.builder`'s entire job, and anything absent from it cannot appear in the prose --
    which means a missing engine shows up as a sentence that fails to verify, not as a plausible
    invented figure.
    """

    symbol: str
    interval: Interval
    generated_at: dt.datetime
    facts: dict[str, Fact] = Field(default_factory=dict)
    warnings: list[MarketWarning] = Field(default_factory=list)

    def get(self, fact_id: str) -> Fact | None:
        return self.facts.get(fact_id)


class ViolationKind(StrEnum):
    """Why a draft was refused."""

    UNKNOWN_FACT = "unknown_fact"
    """A ``{{fact:id}}`` the bundle does not hold. The headline case: the model asserted a figure
    nothing computed."""
    BARE_NUMERAL = "bare_numeral"
    """A digit outside a fact reference. Every number must come from the bundle; see the module
    docstring for why this is blunt rather than clever."""
    MALFORMED_REFERENCE = "malformed_reference"
    """Something shaped like a reference that is not one -- ``{{fact:}}``, an unclosed ``{{``.
    Rejected rather than ignored, because a reference that silently renders as literal text is a
    number that vanished from the report without anyone noticing."""
    EMPTY = "empty"


class GroundingViolation(BaseModel):
    """One specific reason a draft failed, located precisely enough to fix."""

    model_config = ConfigDict(frozen=True)

    kind: ViolationKind
    detail: str
    position: int | None = None
    """Character offset into the draft text."""
    excerpt: str = ""
    """The offending span with a little context, so a caller can show what went wrong without
    re-deriving the offset."""


class GroundingReport(BaseModel):
    """The verdict on one draft.

    ``grounded`` being ``True`` is a statement about *numerals*: every figure in the prose came from
    the bundle. It is not a statement that the prose is true. See :attr:`caveat`.
    """

    model_config = ConfigDict(frozen=True)

    grounded: bool = False
    """Defaults to ``False`` so a report that was never verified cannot be mistaken for one that
    passed -- the same reason :attr:`app.backtest.models.GuardStatus.UNVERIFIED` is a failure."""
    violations: list[GroundingViolation] = Field(default_factory=list)
    cited: list[str] = Field(default_factory=list)
    """Fact ids the draft actually referenced, in order of appearance. Lets a reader see which of the
    bundle's figures the prose leaned on -- and which it quietly ignored."""
    caveat: str = (
        "Verified: every numeral in this text resolves to a computed fact. Not verified: verbal "
        "quantities carry no digits and are outside what this check can see."
    )


class NarrativeDraft(BaseModel):
    """Prose with fact references in place of numbers, plus where it came from.

    :attr:`source` and :attr:`model` exist so a report is reproducible in the sense that matters:
    two runs that produced different prose must be distinguishable by something other than reading
    both. A deterministic draft records ``source="template"``; a model-written one records the model
    and temperature, and a card that cannot be reproduced from its own inputs is a defect.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    """Template text. Contains ``{{fact:id}}`` references and no bare digits."""
    source: str = "template"
    """``template`` for the deterministic narrator, otherwise the generator's name."""
    model: str | None = None
    temperature: float | None = None


class RenderedNarrative(BaseModel):
    """A draft that passed verification, with its values substituted.

    Constructing one requires a passing :class:`GroundingReport`; there is no path from an unverified
    draft to rendered text. That is the enforcement -- a caller cannot forget to check, because the
    check is what produces the object.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    """Fully rendered prose, safe to display."""
    draft: NarrativeDraft
    grounding: GroundingReport
    cited_facts: list[Fact] = Field(default_factory=list)
    """The facts actually used, so the UI can render footnotes without re-resolving ids."""


class ReportSection(BaseModel):
    """One titled block of a report: a heading, optional prose, and the facts it draws on."""

    section_id: str
    title: str
    narrative: RenderedNarrative | None = None
    """``None`` when a section is tables only, or when its draft failed verification -- in which case
    :attr:`warnings` says so. A section never renders unverified prose."""
    fact_ids: list[str] = Field(default_factory=list)
    warnings: list[MarketWarning] = Field(default_factory=list)


class Report(BaseModel):
    """The whole per-holding report.

    Deterministic statistics are authoritative and are carried here as their own engine types --
    :class:`~app.backtest.models.DrawdownProfile`, :class:`~app.rules.models.DecisionTable`,
    :class:`~app.backtest.models.StrategyResult`. The prose in :attr:`sections` explains them and
    never calculates; anything it says about a number came from :attr:`bundle`.
    """

    symbol: str
    interval: Interval
    generated_at: dt.datetime
    profile: Profile | None = None
    quote: Quote | None = None
    bundle: FactBundle
    sections: list[ReportSection] = Field(default_factory=list)
    drawdown: DrawdownProfile | None = None
    decisions: DecisionTable | None = None
    strategy: StrategyResult | None = None
    run_id: str | None = None
    warnings: list[MarketWarning] = Field(default_factory=list)
    disclaimer: str = (
        "Historical statistics over stored data. Not investment advice, not a recommendation, and "
        "not a prediction. Every figure is conditional on the sample window shown beside it."
    )

"""Shared contract for rules, their current state, and the historical evidence attached to them.

The decision table's job is to say, for one instrument, which rules are firing right now and
whether that has historically meant anything. The second half is where this gets dangerous, and
four rules in this module exist to keep it honest.

**A hit rate without its base rate is not evidence.** "This rule was followed by a gain 58% of the
time" is meaningless until you know the instrument rose on 56% of all bars over the same window.
:class:`Evidence` therefore carries :attr:`~Evidence.baseline_hit_rate` and
:attr:`~Evidence.baseline_median_return` computed over *every* bar in the same sample, and the UI is
expected to show the pair. An edge is the difference, not the level.

**The signal bar is not tradeable.** A rule evaluated on bar ``t`` uses that bar's close, which you
only know once the session has ended. Measuring the forward return from ``t``'s close therefore
assumes a fill at a price that was still forming when the condition became true. Every horizon here
is measured from the **open of bar t+1**; see :attr:`Evidence.entry`. Getting this wrong is the
single most common way a backtest invents an edge, and it is invisible in the output -- the numbers
just come out better.

**Overlapping windows are not independent observations.** A 20-day forward return sampled from
triggers three days apart shares 17 days of the same price path. Treating those as independent
draws is what turns noise into a p-value of 0.01. :attr:`Evidence.independent_sample_size` reports
the non-overlapping count alongside the raw one, and any significance claim must be based on the
former. See :attr:`Evidence.significance`.

**"Did not trigger" and "could not be evaluated" are different.** Through an indicator's warmup
window, or across a gap in the underlying bars, a rule has no truth value. Folding that into
``False`` silently pads the denominator with bars the rule was never given a chance to fire on.
:class:`TriState` keeps them apart, and evidence counts only evaluable bars.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.db.duck import Interval
from app.market.models import MarketWarning

__all__ = [
    "HORIZONS",
    "DecisionRow",
    "DecisionTable",
    "Entry",
    "Evidence",
    "Rule",
    "RuleState",
    "Significance",
    "TriState",
]


#: Forward-return horizons, in trading bars, that evidence is computed over.
#:
#: Bars rather than calendar days on purpose: the store holds settled sessions only, so "20 bars"
#: is 20 opportunities to trade, whereas "20 days" silently shortens across every holiday and
#: lengthens across none.
HORIZONS: tuple[int, ...] = (1, 5, 20, 60)


class TriState(StrEnum):
    """A rule's truth value on one bar.

    ``UNKNOWN`` is not a failure state -- it is the correct answer through an indicator's warmup
    window and anywhere the inputs have gaps. It exists so those bars can be excluded from a hit
    rate's denominator rather than counted as quiet days on which the rule declined to fire.
    """

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class Entry(StrEnum):
    """Where the forward-return clock starts, relative to the bar the rule fired on."""

    NEXT_OPEN = "next_open"
    """The open of bar ``t+1``. The default, and the only one that is honestly tradeable: the
    condition is known once bar ``t`` closes, and the first price available after that is the next
    session's open."""
    SAME_CLOSE = "same_close"
    """The close of bar ``t`` itself. Available for comparison and research only. It assumes a fill
    at the very price that triggered the signal, which is not obtainable in practice; any figure
    computed this way is an upper bound on a real result, never an estimate of one."""


class Significance(StrEnum):
    """How much weight a rule's measured edge can bear.

    Deliberately coarse. A precise p-value printed next to a hit rate invites reading it as a
    discovery, and these are not discoveries: the rules are chosen by a human looking at the same
    history they are then scored against, and a decision table showing twenty rules is twenty
    simultaneous tests with no correction between them. Phase 7 adds the FDR accounting that would
    justify a sharper claim; until then this says only whether there is enough non-overlapping
    evidence to bother looking.
    """

    INSUFFICIENT = "insufficient"
    """Too few independent observations to say anything. The honest default."""
    WEAK = "weak"
    SUGGESTIVE = "suggestive"
    """Worth a second look in the backtest workbench. Explicitly *not* a claim of significance."""


class Rule(BaseModel):
    """One named condition over an instrument's bars."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    """Stable token, used as the React key and in stored references: ``rsi_oversold``."""
    name: str
    expression: str
    """The DSL source, exactly as written. Round-trips: parsing and re-rendering this must produce
    an equivalent tree, which is what lets the table show the user's own words back to them."""
    description: str = ""
    intervals: tuple[Interval, ...] = ()
    """Intervals the rule is meaningful on. Empty means "any". A rule referencing an anchored VWAP
    is only defined on intraday bars, and the catalog is where that is declared rather than
    discovered by a 400 at render time."""


class RuleState(BaseModel):
    """What a rule is doing right now, on the most recent settled bar."""

    model_config = ConfigDict(frozen=True)

    state: TriState
    as_of: dt.date | None = None
    """Session date of the bar the state was evaluated on. ``None`` when there are no bars."""
    last_trigger: dt.date | None = None
    """Most recent session on which the rule was ``TRUE``. ``None`` if it never fired in the stored
    history -- which is different from "fired long ago", and must not render as an em dash that
    could mean either."""
    bars_since_trigger: int | None = None
    triggers_in_history: int = 0


class Evidence(BaseModel):
    """What historically followed this rule firing, measured against what normally happens.

    Every field is optional because a rule with too few triggers genuinely has no measurable
    history, and a table that renders that as ``0.0%`` is claiming something false. Absent means
    absent.
    """

    model_config = ConfigDict(frozen=True)

    horizon: int
    """Forward-return horizon in bars. One of :data:`HORIZONS`."""
    entry: Entry = Entry.NEXT_OPEN

    hit_rate: float | None = None
    """Fraction of triggers followed by a positive return over ``horizon``. 0-1, not a percentage."""
    baseline_hit_rate: float | None = None
    """The same measurement over *every* evaluable bar in the sample, triggered or not. Without it
    the hit rate above cannot be read: see the module docstring."""
    median_return: float | None = None
    """Median forward return following a trigger, as a fraction. Median rather than mean because a
    single 400% move in a leveraged ETF otherwise carries the whole statistic."""
    baseline_median_return: float | None = None

    sample_size: int = 0
    """Number of triggers with a complete forward window. Triggers too close to the end of the
    series to have one are excluded rather than measured over a truncated horizon."""
    independent_sample_size: int = 0
    """Triggers remaining after discarding those whose forward windows overlap an earlier one.
    This, not :attr:`sample_size`, is what any significance claim rests on."""
    significance: Significance = Significance.INSUFFICIENT

    @property
    def edge(self) -> float | None:
        """Hit rate minus baseline. The number that actually means something."""
        if self.hit_rate is None or self.baseline_hit_rate is None:
            return None
        return self.hit_rate - self.baseline_hit_rate


class DecisionRow(BaseModel):
    """One rule's row in the table: what it is, what it is doing, and what that has meant."""

    rule: Rule
    state: RuleState
    evidence: list[Evidence] = Field(default_factory=list)
    """One entry per horizon in :data:`HORIZONS`, in that order."""
    warnings: list[MarketWarning] = Field(default_factory=list)
    """Why a row is degraded -- rule not defined on this interval, not enough history, evaluation
    failed. A row that could not be evaluated still appears, carrying its reason, rather than
    silently vanishing from a table the user is reading as complete."""


class SignificanceCriteria(BaseModel):
    """The thresholds :class:`Significance` is assigned by, carried to the UI so a grade can be
    checked against the row it describes rather than taken on trust.

    Edges are absolute values in **hit-rate percentage points expressed as fractions** -- ``0.15``
    means the rule hit 15 points more often than the baseline, not that it returned 15%. Both
    conditions must hold together: a large edge on six observations stays ``insufficient``, and so
    does a two-point edge on four hundred.
    """

    model_config = ConfigDict(frozen=True)

    weak_min_independent: int
    weak_min_edge: float
    suggestive_min_independent: int
    suggestive_min_edge: float


class DecisionTable(BaseModel):
    """The whole table for one symbol and interval."""

    symbol: str
    interval: Interval
    generated_at: dt.datetime
    bars_evaluated: int = 0
    first_bar: dt.date | None = None
    last_bar: dt.date | None = None
    """The sample's span, shown because every number in the table is conditional on it. A hit rate
    measured over a period that was mostly one bull market is a fact about that period."""
    rows: list[DecisionRow] = Field(default_factory=list)
    criteria: SignificanceCriteria | None = None
    """What the :attr:`DecisionRow.evidence` grades mean. Travels with the table rather than being
    restated in a component, so the legend and the rule cannot drift apart."""
    warnings: list[MarketWarning] = Field(default_factory=list)

"""Shared contract for the thesis loop.

:mod:`app.thesis`'s docstring states the hazard and the four guards. This module is where those
guards become shapes that cannot be constructed wrongly.

**A thesis is frozen before it is tested.** :class:`Thesis` carries no results, and
:class:`ThesisRecord` -- the thing that *does* -- holds the thesis's content hash rather than the
thesis, so a result can only ever be joined to the exact wording that was registered. Editing a
thesis after seeing results produces a different hash, which is a different record, which is another
trial. That is not a convention; there is no field to overwrite.

**The falsification criterion is required, and it is written first.**
:attr:`Thesis.falsifies_if` is a non-empty string on a frozen model. A hypothesis that cannot say in
advance what would refute it is not a hypothesis, and asking for it *after* the numbers arrive gets
a criterion tuned to pass.

**Inconclusive is a verdict, not a gap.** :attr:`Verdict.INCONCLUSIVE` is the expected outcome for
most theses on most tickers, and the UI is expected to present it as a normal result. A design where
the only reportable outcomes are "survived" and "rejected" quietly pressures a loop into producing
one of them.

**A leveraged instrument's card is meaningless without its unlevered twin.** Daily-reset products
decay in choppy markets regardless of direction, so :attr:`StrategyCard.unlevered_comparison` exists
to stop a card measuring leverage decay and calling it strategy.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.backtest.models import Distribution, StrategyResult
from app.db.duck import Interval
from app.market.models import MarketWarning
from app.report.models import FactBundle

__all__ = [
    "DEFAULT_ITERATION_BUDGET",
    "MIN_HOURLY_INDEPENDENT_EVENTS",
    "Direction",
    "Evidence",
    "HoldoutState",
    "HoldoutStatus",
    "LedgerStats",
    "LoopOutcome",
    "LoopResult",
    "RegimeSlice",
    "StrategyCard",
    "TaxImpact",
    "TaxRateBasis",
    "Thesis",
    "ThesisRecord",
    "ThesisStatus",
    "Verdict",
]

#: Iterations a run may spend before it stops, whatever it has found.
#:
#: Twelve because the budget's purpose is to make "we kept going until something worked" impossible,
#: and any finite number does that. Declared up front and decremented on every iteration -- including
#: the ones that produce nothing -- so the trial count and the budget cannot diverge.
DEFAULT_ITERATION_BUDGET: int = 12

#: Independent events an hourly sub-study needs before it may be reported at all.
#:
#: Yahoo serves hourly bars back to roughly 730 days, so an hourly refinement is testable over about
#: two years and a correspondingly small number of distinct events. Below thirty, adding a free
#: parameter to an exit rule buys a better in-sample fit and nothing else, and the honest thing is to
#: decline to report rather than to report with a caveat nobody reads.
MIN_HOURLY_INDEPENDENT_EVENTS: int = 30


class Direction(StrEnum):
    """The predicted direction of the effect, declared before testing.

    Required because it is what makes a result falsifiable in the useful sense: an edge that comes
    out significant in the *opposite* direction to the prediction refutes the thesis rather than
    confirming it, and a loop that only checks magnitude would score that as a success.
    """

    UP = "up"
    DOWN = "down"


class ThesisStatus(StrEnum):
    """Where a registered thesis sits in its lifecycle."""

    REGISTERED = "registered"
    """Frozen and counted as a trial. No results attached yet -- and if the run dies here, this
    thesis still occupies its slot in the ledger, which is the entire point of registering first."""
    IN_SAMPLE_TESTED = "in_sample_tested"
    HOLDOUT_TESTED = "holdout_tested"
    ABANDONED = "abandoned"
    """Dropped mid-run without completing. **Still counted in the FDR denominator.** A loop that
    discards weak theses and forgets them is the failure mode this whole package exists to prevent."""


class Verdict(StrEnum):
    """What the evidence supports. Three values, and the third is not a failure."""

    SURVIVED = "survived"
    """Cleared in-sample, cleared the holdout, and cleared FDR against the ticker's whole ledger.
    Still not a recommendation -- see :attr:`StrategyCard.disclaimer`."""
    REJECTED = "rejected"
    """The pre-declared falsification criterion fired, or the effect ran opposite to the declared
    direction."""
    INCONCLUSIVE = "inconclusive"
    """Underpowered. The expected outcome for most theses on most tickers, and a normal result rather
    than a gap to fill with narrative."""


class Thesis(BaseModel):
    """A falsifiable claim about one instrument, written before any test runs.

    Frozen, and deliberately carries **no results field**. What gets stored with results is a
    :class:`ThesisRecord` keyed by this object's content hash, so there is no way to edit a thesis
    into agreement with numbers that already exist.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    interval: Interval = Interval.DAY
    hypothesis: str
    """Plain-language claim. Part of the hash: rewording it is a new thesis, because a reworded
    hypothesis is a different claim and pretending otherwise is how one trial becomes free."""
    entry: str
    """Rule DSL expression."""
    exit: str | None = None
    max_holding_bars: int | None = None
    stop_loss_pct: float | None = None
    horizon: int
    """Forward-return horizon the prediction is about, in bars."""
    direction: Direction
    falsifies_if: str
    """What would refute this, in advance and in plain language. Required and non-empty.

    A hypothesis that cannot say what would refute it is not one, and a criterion supplied after the
    numbers arrive is a criterion tuned to pass. This is the field most likely to feel like
    paperwork and is the one that does the most work.

    **It is recorded and hashed, not machine-evaluated.** Be precise about what that buys, because
    the wording invites a stronger reading: including it in :data:`~app.thesis.preregister.
    HASHED_FIELDS` means the criterion is fixed before any backtest runs and cannot be edited
    afterwards without minting a different thesis and another trial. That is the guarantee, and it
    is a real one. What does *not* happen is any check that the loop's verdict was reached by
    applying this particular sentence: :func:`~app.thesis.loop.evaluate_thesis` measures the same
    thing for every thesis -- the conditional hit rate against the instrument's unconditional
    baseline at the stated horizon, plus direction and sample size.

    The consequence is a constraint on how a criterion may be *worded*, and it was violated for a
    while: two catalogue templates stated their hypothesis and falsification criterion in terms of
    maximum drawdown, which nothing in the loop computes, so they were scored on hit rate while
    claiming to be about drawdown -- a verdict that did not answer the question asked. A criterion
    naming a quantity the loop does not measure is worse than a vague one, because it reads as
    though something checked it. :func:`app.thesis.author.CATALOGUE`'s entries are pinned by test to
    stay within what is measured; a quantity worth testing needs the engine extended first."""
    rationale: str = ""
    """Why this was proposed -- structure, mechanics, priors. Explicitly *not* "because the chart
    looked like this", which would make the thesis a description of the sample."""

    @field_validator("falsifies_if")
    @classmethod
    def _criterion_is_real(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(
                "falsifies_if must state what would refute this thesis; a hypothesis with no "
                "refutation condition cannot be tested, only illustrated"
            )
        return value


class Evidence(BaseModel):
    """One statistical read on a thesis, from the Phase 7 engines. Computes nothing itself."""

    model_config = ConfigDict(frozen=True)

    horizon: int
    hit_rate: float | None = None
    baseline_hit_rate: float | None = None
    median_return: float | None = None
    baseline_median_return: float | None = None
    distribution: Distribution = Field(default_factory=Distribution)
    sample_size: int = 0
    independent_sample_size: int = 0
    p_value: float | None = None
    q_value: float | None = None
    """Benjamini-Hochberg against **the ticker's whole ledger**, not this run. See
    :class:`LedgerStats`."""
    trials_at_evaluation: int = 0
    """Size of that ledger when this q-value was computed. Recorded because a q-value is meaningless
    without the family it was corrected over, and that family grows."""

    @property
    def edge(self) -> float | None:
        if self.hit_rate is None or self.baseline_hit_rate is None:
            return None
        return self.hit_rate - self.baseline_hit_rate


class HoldoutStatus(StrEnum):
    """Whether a ticker's holdout is still usable."""

    UNUSED = "unused"
    SPENT = "spent"
    """Evaluated once, as designed. The result stands and no further evaluation is permitted."""
    BURNED = "burned"
    """A second evaluation was attempted. The holdout is no longer an out-of-sample test for this
    ticker -- someone has now seen it twice, and a threshold chosen after looking is an in-sample
    threshold. The state is recorded rather than the attempt being silently refused, because a user
    who does not know the holdout is compromised will keep reading its numbers as if it were not."""


class HoldoutState(BaseModel):
    """One ticker's holdout, and what has been done to it."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    split_date: dt.date
    """Last in-sample session. Everything after is holdout."""
    status: HoldoutStatus = HoldoutStatus.UNUSED
    evaluated_at: dt.datetime | None = None
    evaluated_thesis_hash: str | None = None
    attempts: int = 0
    """Every evaluation attempt, including refused ones. The count is the evidence that a holdout was
    reused."""


class LedgerStats(BaseModel):
    """The trial family a q-value was corrected over."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    total_trials: int = 0
    """Every thesis ever registered for this ticker, across all runs and restarts -- including
    abandoned and rejected ones."""
    survived: int = 0
    rejected: int = 0
    inconclusive: int = 0
    abandoned: int = 0
    first_registered: dt.datetime | None = None
    last_registered: dt.datetime | None = None


class ThesisRecord(BaseModel):
    """A registered thesis and whatever has since been learned about it.

    Keyed by :attr:`thesis_hash`, not by the thesis object. Results join to the frozen hash, so a
    record can never describe a thesis other than the one that was registered.
    """

    thesis_hash: str
    thesis: Thesis
    registered_at: dt.datetime
    status: ThesisStatus = ThesisStatus.REGISTERED
    verdict: Verdict | None = None
    in_sample: Evidence | None = None
    holdout: Evidence | None = None
    run_id: str | None = None
    """Run card for the backtest that produced the evidence."""
    notes: str = ""


class RegimeSlice(BaseModel):
    """The same statistics inside one market regime.

    An edge that exists only in one regime is a conditional edge and must be labelled as one --
    otherwise a card promises in a calm market what it measured in a volatile one.
    """

    model_config = ConfigDict(frozen=True)

    label: str
    """``high_volatility``, ``low_volatility``, ``uptrend``, ``downtrend``."""
    bars: int = 0
    evidence: Evidence | None = None


class TaxRateBasis(StrEnum):
    """Which rate produced `TaxImpact.after_tax_return` -- the fact that must travel with the
    number itself, because the two bases mean different things to a reader.

    A figure computed from `USER_CONFIGURED` rates is this user's actual modelled tax cost. A
    figure computed from `STATUTORY_UPPER_BOUND` is a directional ceiling most filers fall under,
    not a personal number -- and without this field attached to the value, both look identical to
    a UI that just renders `after_tax_return`. See `app.thesis.strategycard.build_tax_impact`.
    """

    USER_CONFIGURED = "user_configured"
    """Both rates came from `app.config.Settings.ordinary_income_tax_rate` /
    `long_term_capital_gains_tax_rate`, which the user supplied."""
    STATUTORY_UPPER_BOUND = "statutory_upper_bound"
    """One or both rates fell back to the top federal statutory bracket because the user has not
    configured their own. An upper bound for most filers, not a filing-grade figure."""


class TaxImpact(BaseModel):
    """What the strategy would have cost in tax, from the Phase 3 engine.

    The thing a standalone backtester structurally cannot tell you. A rule turning positions over
    every three weeks generates short-term gains taxed as ordinary income and, when it re-enters
    after a losing exit, **triggers its own wash sales** -- and a rule that looks good gross and
    mediocre after tax is a common and normally invisible outcome.
    """

    model_config = ConfigDict(frozen=True)

    gross_return: float | None = None
    after_tax_return: float | None = None
    short_term_gains: float | None = None
    long_term_gains: float | None = None
    wash_sales_triggered: int = 0
    """Round trips the strategy's own re-entries would have made wash sales."""
    disallowed_loss: float | None = None
    rate_basis: TaxRateBasis | None = None
    """Which of the two rate sources produced `after_tax_return`. ``None`` exactly when
    `unavailable_reason` is set -- there is no rate to attribute when there is no figure. Required
    reading alongside `after_tax_return`: the same float means "your actual after-tax cost" under
    `USER_CONFIGURED` and "a ceiling most filers fall under" under `STATUTORY_UPPER_BOUND`, and a
    UI that drops this field loses the distinction."""
    short_term_rate_applied: float | None = None
    """The rate actually multiplied against short-term gains to produce `after_tax_return` --
    whichever of the user's configured rate or the statutory fallback was used. Recorded so the
    figure is self-describing without cross-referencing `rate_basis` against `Settings`."""
    long_term_rate_applied: float | None = None
    """Same as `short_term_rate_applied`, for the long-term side."""
    ira_exposure: bool | None = None
    """Whether the ticker is also held in an IRA, which would make a loss taken here and replaced
    in the IRA **permanently** disallowed under Rev. Rul. 2008-5 rather than merely deferred.

    Tri-state, not a plain bool: this card is built from a synthetic, single-account replay that
    has no knowledge of the user's real accounts under `data/` (see
    `app.thesis.strategycard.build_tax_impact`'s module-level comment), so the honest answer is
    always "not checked", never "no". ``None`` means unknown -- the only value this layer can ever
    produce. A caller with real cross-account visibility may set ``True``/``False``; nothing in
    this package does."""
    unavailable_reason: str | None = None
    """Why the figures are absent, when they are. Ledger not built, ticker not held, no closed
    trades. Absent with a reason beats absent."""


class StrategyCard(BaseModel):
    """The deliverable. Every figure computed, none of it advice.

    A card is produced for a *rejected* and an *inconclusive* thesis too, carrying the numbers that
    killed it. A system that only renders winners is a system whose output is selected on the
    outcome.
    """

    symbol: str
    interval: Interval
    generated_at: dt.datetime
    thesis: Thesis
    thesis_hash: str
    verdict: Verdict

    entry_rule: str
    exit_rule: str | None = None
    triggers_per_year: float | None = None
    """How often this actually fires. A rule that fires twice a decade is untradeable however good
    its statistics look."""
    holding_period_median: float | None = None
    holding_period_iqr: tuple[float, float] | None = None
    """Measured, not assumed."""

    expected_return: Distribution = Field(default_factory=Distribution)
    """A distribution, never a point estimate."""
    baseline_return: Distribution = Field(default_factory=Distribution)
    """The instrument's unconditional outcome over the same horizon. Required beside the above for
    the reason every other baseline in this project is required."""
    worst_trade: float | None = None
    max_drawdown_in_position: float | None = None

    in_sample: Evidence | None = None
    holdout: Evidence | None = None
    holdout_state: HoldoutState | None = None
    ledger: LedgerStats | None = None
    regimes: list[RegimeSlice] = Field(default_factory=list)
    tax: TaxImpact | None = None

    unlevered_comparison: StrategyCard | None = None
    """The same thesis on the unlevered equivalent, when the subject is a daily-reset leveraged or
    inverse product. Without it a card can measure leverage decay and call it strategy. Populated by
    the loop automatically from the instrument registry, not on request."""
    hourly_substudy: Evidence | None = None
    """A labelled hourly exit refinement, when one was run and cleared
    :data:`MIN_HOURLY_INDEPENDENT_EVENTS`. The daily result is always the headline."""

    strategy_result: StrategyResult | None = None
    bundle: FactBundle | None = None
    """Facts for the grounded narrative, under the Phase 8 citation contract."""
    warnings: list[MarketWarning] = Field(default_factory=list)
    disclaimer: str = (
        "What a rule did historically, with its sample size and its failures. Not a recommendation, "
        "not investment advice, and not a prediction. No orders are placed by this software."
    )


class LoopOutcome(StrEnum):
    """How a run ended. Five values, every one reportable -- none of them is an error state a UI
    may collapse into a generic failure message. See each member for what it says and about whom."""

    SURVIVOR_FOUND = "survivor_found"
    BUDGET_EXHAUSTED = "budget_exhausted"
    """Spent every declared iteration with nothing surviving. **A valid result**, and real
    information about the ticker rather than a failed run."""
    CATALOGUE_EXHAUSTED = "catalogue_exhausted"
    """Ran out of hypotheses to propose before running out of budget, with nothing surviving.

    Distinct from :attr:`BUDGET_EXHAUSTED` because the two say different things and only one of them
    is about the ticker. "No thesis survived twelve attempts" is information about the instrument;
    "the author had only five ideas and none worked" is information about the author. Reporting the
    second as the first overstates how hard the loop actually looked -- with the default catalogue of
    five or six templates against a budget of twelve, that was the *usual* outcome until this value
    existed."""
    NO_DATA = "no_data"
    HOLDOUT_UNAVAILABLE = "holdout_unavailable"
    """The ticker's holdout was already spent or burned, so nothing here could be evaluated
    out-of-sample. Refused rather than silently reported in-sample only."""


class LoopResult(BaseModel):
    """One complete run: what was tried, what survived, and what it cost in trials."""

    symbol: str
    interval: Interval
    started_at: dt.datetime
    finished_at: dt.datetime
    outcome: LoopOutcome
    budget: int
    iterations_used: int
    """Every iteration, including those that produced nothing. Equal to the number of theses
    registered by this run -- see :attr:`records`."""
    records: list[ThesisRecord] = Field(default_factory=list)
    """Every thesis this run registered, in order, whatever became of it. Abandoned ones included."""
    cards: list[StrategyCard] = Field(default_factory=list)
    """The survivor's card, when :attr:`outcome` is :attr:`LoopOutcome.SURVIVOR_FOUND` -- built by
    ``app.api.thesis`` after the loop returns, through a ``CardBuilder`` collaborator injected the
    same way :mod:`app.api.thesis` injects everything else it does not compile against, and never
    populated by this module itself. Deliberately not "every record that got far enough to have
    one": :func:`app.thesis.loop.run` returns the instant a survivor's holdout confirms, so a run
    can only ever produce zero or one survivor, and building a card re-runs a chunk of the same
    rule evaluation the loop already paid for once per record -- doing that for every rejected and
    inconclusive record in a twelve- or twenty-four-iteration run would multiply the request's cost
    for records nobody asked to see rendered. A card failing to build does not fail the request --
    see :attr:`LoopResult.warnings`, which carries a ``kind="card_failed"`` entry when that happens,
    with :attr:`cards` left empty rather than the run reporting an error it did not have."""
    ledger: LedgerStats | None = None
    holdout: HoldoutState | None = None
    warnings: list[MarketWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def _survived_only_with_a_holdout(self) -> Self:
        """`Verdict.SURVIVED`'s own docstring: "cleared in-sample, cleared the holdout, and cleared
        FDR." A ticker gets exactly one holdout evaluation, ever, so at most one record per run may
        legitimately carry that verdict. The defect this guards against: `app.thesis.loop.run`
        captured only the *first* in-sample screen that cleared the bar as the holdout candidate, but
        every record `_screen` marked `SURVIVED` was still written into `records` with that verdict --
        so a second, third, or fourth thesis that also cleared the in-sample screen kept reporting
        `SURVIVED` forever, with `holdout` left `None`, because nothing ever spent a look on it and
        nothing ever downgraded the label to match. Refusing to construct the object is the only
        enforcement that survives a producer bug like that one -- a convention the loop is supposed to
        honor is exactly what was silently broken."""
        offenders = [
            r.thesis_hash[:12]
            for r in self.records
            if r.verdict is Verdict.SURVIVED and r.holdout is None
        ]
        if offenders:
            raise ValueError(
                f"record(s) {', '.join(offenders)} carry verdict=SURVIVED with no holdout evidence "
                "attached; a thesis that never spent the ticker's one out-of-sample look has not "
                "been confirmed and must not be reported as a survivor"
            )
        return self

    @model_validator(mode="after")
    def _outcome_agrees_with_survivors(self) -> Self:
        """`LoopOutcome.SURVIVOR_FOUND` and a non-empty `survivors` are the same fact stated two
        different ways -- one in `outcome`, one derived from `records` -- and a caller may
        legitimately read either. The defect this guards against produced a `LoopResult` reporting
        `outcome=CATALOGUE_EXHAUSTED` ("nothing survived twelve attempts") while `survivors` returned
        four records, because the four extra `SURVIVED` records described above were never reconciled
        with the outcome the loop actually computed from its own budget/catalogue bookkeeping. A UI
        that trusts `outcome` and a UI that trusts `survivors` must never be able to reach opposite
        conclusions about the same run."""
        has_survivor = bool(self.survivors)
        if (self.outcome is LoopOutcome.SURVIVOR_FOUND) != has_survivor:
            state = "non-empty" if has_survivor else "empty"
            raise ValueError(
                f"outcome={self.outcome.value} but survivors is {state}; SURVIVOR_FOUND must hold "
                "exactly when a record's verdict is SURVIVED and never on its own -- a run cannot "
                "report finding a survivor it does not list, or list one it says it did not find"
            )
        return self

    @property
    def survivors(self) -> list[ThesisRecord]:
        """Records whose final verdict is :attr:`Verdict.SURVIVED`.

        Derived from :attr:`records`, **not** from :attr:`cards`, and must stay that way even now
        that :attr:`cards` is sometimes populated. This property once filtered ``cards`` instead, back
        when nothing in the codebase ever populated that field -- the property returned an empty list
        on every run whatever the verdicts were, and a test asserting ``survivors == []`` on random
        noise passed vacuously and would never have caught the regression it was written to guard.
        ``records`` is the loop's own output, always present and always reflecting what actually
        happened; ``cards`` is a best-effort attachment from a layer above the loop that can be empty
        even on a genuine survivor (card build failure -- see :attr:`cards`), so it must never be the
        thing this property, or anything else that answers "did a thesis survive", is computed from.
        """
        return [r for r in self.records if r.verdict is Verdict.SURVIVED]

    @property
    def survivor_cards(self) -> list[StrategyCard]:
        """Cards for the survivors, when a card layer has attached them. Not the same question as
        :attr:`survivors`: a run can have a survivor (:attr:`survivors` non-empty) whose card failed
        to build (:attr:`cards` empty), in which case this is empty too even though the thesis did
        survive -- check :attr:`survivors` to know whether one did, this only to know whether a card
        exists to render."""
        return [c for c in self.cards if c.verdict is Verdict.SURVIVED]

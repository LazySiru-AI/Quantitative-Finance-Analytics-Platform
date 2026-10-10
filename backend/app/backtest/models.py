"""Shared contract for the backtest workbench.

Every module in :mod:`app.backtest`, the API layer and ``frontend/src/api/backtest.ts`` agree on the
shapes here. :mod:`app.rules.models` is the sibling contract for Phase 6 and its four honesty rules
(baseline, next-open entry, independence, unknown-is-not-false) hold verbatim in this package too --
they are not restated here. What *is* stated here is the four things that only become necessary once
a study can be run over many conditions at once.

**A trial count that can be filtered is not a trial count.** :class:`ScanResult` requires
``len(entries) == trials``: every condition that was evaluated appears in the result, including the
ones that looked like nothing. A scan that reports its best six of forty rules with ``trials=6`` has
lied by subtraction, and the lie is invisible in the output -- so the model refuses to construct.

**Exploratory and confirmatory results must not share a shape.** Reverse conditioning reads the
sample and hands back the conditions that describe it; that is a fishing expedition by construction,
and a legitimate one, but its output is a *candidate*, never a finding.
:class:`ReverseConditioning` therefore carries no p-value, no q-value and no hit rate -- there is
nothing for those numbers to mean when the hypothesis was read off the same data. It is a different
class rather than a flag on the same class so the two cannot be rendered by the same component.

**A guard that can be skipped is not a guard.** :class:`GuardReport` is a required field on every
study that evaluates a condition, and :attr:`GuardStatus.UNVERIFIED` is a *failure*, not a neutral
default -- see :class:`GuardStatus`. A study whose guard did not run must not display its numbers.

**Drawdown depth is meaningless without its basis.** A close-basis drawdown is strictly shallower
than the intraday one, and a dividend-adjusted basis is shallower still for anything that pays.
Three defensible answers to "how far did it fall" differ by percentage points on the same series, so
:attr:`DrawdownProfile.basis` is required output, not an input the caller is trusted to remember.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.duck import Interval
from app.market.models import MarketWarning
from app.rules.models import Entry

__all__ = [
    "BARS_PER_YEAR",
    "SMALL_SAMPLE_THRESHOLD",
    "STUDY_HORIZONS",
    "ArmDelta",
    "ConditionArm",
    "Costs",
    "Distribution",
    "DrawdownBasis",
    "DrawdownEpisode",
    "DrawdownProfile",
    "EquityPoint",
    "EventStudy",
    "ExitReason",
    "GuardFinding",
    "GuardReport",
    "GuardStatus",
    "HorizonStats",
    "IndicatorProfile",
    "ReverseConditioning",
    "RunCard",
    "ScanEntry",
    "ScanResult",
    "StrategyMetrics",
    "StrategyResult",
    "StrategySpec",
    "Trade",
]


#: Forward-return horizons, in trading bars, that an event study reports.
#:
#: One longer than :data:`app.rules.models.HORIZONS`, which omits 10. The decision table is a
#: glanceable summary and four columns is already a lot of it; the workbench is where someone is
#: deliberately looking, and 10 bars is where a mean-reversion effect either shows up or does not.
#: The two tuples are deliberately *not* shared: a change to what the summary table shows should not
#: silently change what a stored run card means.
STUDY_HORIZONS: tuple[int, ...] = (1, 5, 10, 20, 60)

#: Independent-sample size below which a result is marked small-sample in the UI.
#:
#: Not a significance threshold -- a result above it is not thereby significant. It is the line the
#: plan draws for a visible caveat, and it is checked against the *independent* count for the reason
#: :mod:`app.rules.evidence` gives: thirty overlapping 60-bar windows drawn from ninety consecutive
#: bars are not thirty observations of anything.
SMALL_SAMPLE_THRESHOLD: int = 30


# ---------------------------------------------------------------------------
# Distributions
# ---------------------------------------------------------------------------


class Distribution(BaseModel):
    """The shape of a sample of returns, not just its centre.

    Percentiles rather than mean-and-sigma because these samples are not normal and nobody should be
    encouraged to treat them as such: a leveraged ETF's 60-bar forward returns are skewed, fat-tailed
    and occasionally dominated by one week. :attr:`p05` is the number that answers "how bad was the
    bad case", and it is the one a mean hides.
    """

    model_config = ConfigDict(frozen=True)

    count: int = 0
    mean: float | None = None
    median: float | None = None
    stdev: float | None = None
    """Sample standard deviation (ddof=1). ``None`` below two observations, where it is undefined
    rather than zero."""
    p05: float | None = None
    p25: float | None = None
    p75: float | None = None
    p95: float | None = None
    minimum: float | None = None
    maximum: float | None = None


# ---------------------------------------------------------------------------
# Drawdown
# ---------------------------------------------------------------------------


class DrawdownBasis(StrEnum):
    """Which price series a drawdown is measured on. Always reported alongside the depth.

    The three give materially different answers for the same instrument and none of them is wrong;
    what would be wrong is showing a depth without saying which was used.
    """

    CLOSE = "close"
    """Running maximum of close against subsequent closes. The default, and the most commonly quoted
    convention. Understates what an intraday holder actually experienced."""
    ADJ_CLOSE = "adj_close"
    """Dividend- and split-adjusted, so the depth is the *total-return* loss. Shallower than
    :attr:`CLOSE` for anything that pays a distribution. Note that the whole series shifts on every
    payout, so a depth computed today differs slightly from one computed before the last
    ex-dividend date -- which is why :mod:`app.rules` refuses to let a rule reference this column,
    and why a drawdown measured on it belongs in a run card with a data fingerprint."""
    INTRADAY = "intraday"
    """Running maximum of ``high`` against subsequent ``low``. The deepest of the three, and the
    only one that reflects a stop being hit. Peaks and troughs land on bars, not on the exact ticks,
    so this is still a lower bound on the true excursion."""


class DrawdownEpisode(BaseModel):
    """One peak-to-trough-to-recovery excursion.

    Episodes are the underwater periods between successive record highs, so they tile the series
    without overlapping: two "drawdowns" that share a trough are one episode, and reporting them as
    two would double-count the same decline in a top-N table.
    """

    model_config = ConfigDict(frozen=True)

    peak_date: dt.date
    peak_value: float
    trough_date: dt.date
    trough_value: float
    depth: float
    """Negative fraction: ``trough / peak - 1``. ``-0.82`` is an 82% decline. Signed so it can never
    be added to a return series with the wrong sense.

    **This is the peak-to-trough depth -- the worst the episode ever got, not where it is now.**
    For a recovered episode the two are the same question with an obvious answer. For a *live* one
    they are different numbers, and reporting this one under a "current drawdown" label said XLE was
    15.6% below its peak when the gap was 1.04%. See :attr:`depth_now`."""
    bars_to_trough: int
    """Bars from peak to trough. Bars, not calendar days -- see :data:`app.rules.models.HORIZONS`."""

    depth_now: float | None = None
    """Peak to the **latest** observation: ``last / peak - 1``. ``None`` unless
    :attr:`still_underwater`.

    The answer to "how far below the high am I today", which :attr:`depth` is not. A live episode
    that fell 40% and has since retraced most of it carries ``depth = -0.40`` and
    ``depth_now = -0.03``; both are true and a reader deciding whether to add to a position needs
    the second one. ``None`` on a recovered episode rather than ``0.0``, because "it recovered" and
    "it is exactly at its peak right now" are different statements and the first is the one being
    made -- the episode ended, so it has no current depth."""
    last_value: float | None = None
    """The observation :attr:`depth_now` is measured from, so the figure can be checked rather than
    trusted. ``None`` alongside :attr:`depth_now`."""
    last_value_date: dt.date | None = None
    """As-of for :attr:`depth_now` and :attr:`last_value`.

    Normally the series' last bar, and equal to :attr:`DrawdownProfile.last_bar`. It differs when
    the final bars carry no print on the basis column: this module's rule is that a gap must never
    silently participate in a figure, so the last *valid* observation is used and dated honestly
    rather than a missing print being treated as a price."""
    recovery_date: dt.date | None = None
    """First bar closing at or above :attr:`peak_value`. ``None`` while still underwater."""
    bars_to_recovery: int | None = None
    """Peak to recovery. ``None`` while still underwater -- deliberately *not* filled with the bars
    elapsed so far, which would render as a completed recovery time that has not happened."""
    bars_underwater: int
    """Peak to recovery, or peak to the last stored bar if still underwater. When
    :attr:`still_underwater` is set this is a **lower bound**, and the UI must say so."""
    still_underwater: bool = False


class DrawdownProfile(BaseModel):
    """Every material drawdown for one instrument, deepest first.

    Purely descriptive: no hypothesis is under test here, so there is no baseline, no p-value and
    nothing to correct for. This is the one study in the package that can be read at face value.
    """

    symbol: str
    interval: Interval
    basis: DrawdownBasis
    generated_at: dt.datetime
    bars: int = 0
    first_bar: dt.date | None = None
    last_bar: dt.date | None = None
    episodes: list[DrawdownEpisode] = Field(default_factory=list)
    """Sorted by :attr:`DrawdownEpisode.depth` ascending (deepest first), truncated to the requested
    top-N."""
    episodes_considered: int = 0
    """Total episodes found before truncation, so a top-10 table cannot be mistaken for the whole
    history."""
    current: DrawdownEpisode | None = None
    """The live drawdown, if the last bar is below its running peak. Repeated here rather than left
    for the reader to find in :attr:`episodes`, because "where am I now" is the question the
    summary card asks and it is often not in the top N.

    Read :attr:`DrawdownEpisode.depth_now` for that question, not :attr:`DrawdownEpisode.depth` --
    this object carries both, and only the first one is "now"."""
    warnings: list[MarketWarning] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


class GuardStatus(StrEnum):
    """Whether a condition may be trusted to have used only information available at the time."""

    PASSED = "passed"
    FAILED = "failed"
    """The condition can see the future, or the guard could not prove that it cannot. Fails closed:
    an unrecognised construct is a failure, not a pass, because the whole point is that a novel way
    of peeking must not slip through for want of a rule against it."""
    UNVERIFIED = "unverified"
    """The guard did not run. **This is a failure state**, not a neutral one. It exists so that a
    study which skipped verification is visibly distinguishable from one that passed, rather than
    defaulting to the reassuring value. No study may render results under this status."""


class GuardFinding(BaseModel):
    """One specific reason a condition failed, or one check that was run and passed."""

    model_config = ConfigDict(frozen=True)

    check: str
    """Stable token: ``ast_whitelist``, ``prefix_invariance``, ``adj_close``, ``unknown_indicator``,
    ``recursion_depth``."""
    passed: bool
    detail: str
    """Specific enough to act on: name the node type, the indicator, or the bar index where a
    prefix-truncated computation disagreed with the full one."""


class GuardReport(BaseModel):
    """The verdict for one condition expression.

    Required on every study that evaluates a condition. See the module docstring.
    """

    model_config = ConfigDict(frozen=True)

    status: GuardStatus = GuardStatus.UNVERIFIED
    expression: str = ""
    findings: list[GuardFinding] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status is GuardStatus.PASSED


# ---------------------------------------------------------------------------
# Event study
# ---------------------------------------------------------------------------


class HorizonStats(BaseModel):
    """One condition's measured outcome at one horizon, against the same sample's baseline."""

    model_config = ConfigDict(frozen=True)

    horizon: int
    entry: Entry = Entry.NEXT_OPEN

    hit_rate: float | None = None
    baseline_hit_rate: float | None = None
    distribution: Distribution = Field(default_factory=Distribution)
    baseline_distribution: Distribution = Field(default_factory=Distribution)

    sample_size: int = 0
    independent_sample_size: int = 0
    baseline_sample_size: int = 0

    @property
    def edge(self) -> float | None:
        """Hit rate minus baseline hit rate. The only number here that is about the *condition*
        rather than about the instrument."""
        if self.hit_rate is None or self.baseline_hit_rate is None:
            return None
        return self.hit_rate - self.baseline_hit_rate

    @property
    def small_sample(self) -> bool:
        return self.independent_sample_size < SMALL_SAMPLE_THRESHOLD


class ConditionArm(BaseModel):
    """One condition in a study, with its trigger dates and its statistics at every horizon."""

    label: str
    """Display name. For a composed arm this is the full composed expression, so the A/B table
    cannot show two rows whose difference is invisible."""
    expression: str
    guard: GuardReport = Field(default_factory=GuardReport)
    stats: list[HorizonStats] = Field(default_factory=list)
    """One per requested horizon, in the order requested."""
    trigger_dates: list[dt.date] = Field(default_factory=list)
    """Every bar the condition was ``True`` on, including those too close to the end of the series
    to have a complete forward window -- those are excluded from :attr:`HorizonStats.sample_size`
    but they did happen, and a chart overlay must be able to mark them."""
    triggers: int = 0
    evaluable_bars: int = 0
    """Bars where the condition had a truth value at all. The denominator the baseline is measured
    over; smaller than the bar count by the warmup window."""
    warnings: list[MarketWarning] = Field(default_factory=list)


class ArmDelta(BaseModel):
    """The A/B comparison: what adding a condition to the base arm changed.

    The reason this is a first-class model rather than a subtraction the frontend does: "band touch"
    vs "band touch and rsi < 30" differ in *two* ways at once -- the hit rate moves, and the sample
    shrinks. A rendered delta that shows only the first invites reading a 12-point improvement built
    on nine remaining triggers as an improvement.
    """

    model_config = ConfigDict(frozen=True)

    horizon: int
    hit_rate_delta: float | None = None
    median_delta: float | None = None
    sample_size_delta: int = 0
    independent_sample_size_delta: int = 0


class EventStudy(BaseModel):
    """One or more conditions on one instrument, measured forward against a shared baseline.

    Confirmatory only when the conditions were chosen before looking at this instrument's history.
    Nothing in the type system can enforce that; :attr:`ScanResult.trials` is what makes the
    alternative visible when several are tried at once.
    """

    symbol: str
    interval: Interval
    generated_at: dt.datetime
    entry: Entry = Entry.NEXT_OPEN
    horizons: list[int] = Field(default_factory=lambda: list(STUDY_HORIZONS))
    bars: int = 0
    first_bar: dt.date | None = None
    last_bar: dt.date | None = None
    arms: list[ConditionArm] = Field(default_factory=list)
    deltas: list[ArmDelta] = Field(default_factory=list)
    """Each non-base arm compared to ``arms[0]``, flattened as ``(arm_index - 1) * len(horizons) +
    horizon_index``. Empty for a single-arm study."""
    run_id: str | None = None
    """Content hash of the :class:`RunCard` this study was recorded under, when one was written."""
    warnings: list[MarketWarning] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Reverse conditioning
# ---------------------------------------------------------------------------


class IndicatorProfile(BaseModel):
    """How one indicator behaved before the selected moves, against how it behaves generally.

    No p-value and no q-value, by design: the moves were selected by looking at the outcome, so
    every number here is a description of the sample. See :class:`ReverseConditioning`.
    """

    model_config = ConfigDict(frozen=True)

    spec: str
    """Indicator spec text as the registry parses it: ``rsi:14``, ``bb:20,2``."""
    column: str
    """Resolved column name: ``rsi_14``, ``bb_20_2_lower``."""
    selected: Distribution
    baseline: Distribution
    separation: float | None = None
    """Median shift in units of the unconditional interquartile range:
    ``(selected.median - baseline.median) / baseline_iqr``.

    Robust and unitless, so RSI (0-100) and a price-scale band width can appear in the same table.
    ``None`` when the unconditional IQR is zero -- an indicator that is constant over the sample has
    no scale to express a shift in, and dividing by it would report an infinite separation for an
    indicator that never moved."""


class ReverseConditioning(BaseModel):
    """What the indicators were doing before the biggest moves.

    **Exploratory output.** The moves are selected on the forward return, so any condition read off
    this table was chosen by looking at the answer. It is a generator of candidates, and a candidate
    only becomes a result after being tested -- as a declared trial, in a
    :class:`ScanResult` whose ``trials`` counts it.

    Carries no hit rate, p-value or q-value. Those numbers have no meaning against a hypothesis
    derived from the same sample, and a field holding one would eventually be rendered.
    """

    symbol: str
    interval: Interval
    generated_at: dt.datetime
    horizon: int
    """Forward window the move is measured over."""
    quantile: float
    """Upper-tail cutoff, 0-1. ``0.9`` selects the top decile of forward returns."""
    lookback: int
    """Bars before each selected move whose indicator state is profiled. ``0`` profiles the signal
    bar alone."""
    selected_dates: list[dt.date] = Field(default_factory=list)
    selected_count: int = 0
    independent_selected_count: int = 0
    """Selected moves after discarding those whose windows overlap an earlier one -- top-decile
    moves cluster hard, so the raw count badly overstates how many distinct episodes this
    describes."""
    profiles: list[IndicatorProfile] = Field(default_factory=list)
    """Sorted by ``abs(separation)`` descending, unmeasurable ones last."""
    exploratory: bool = True
    """Always ``True``. A field rather than a docstring note so the renderer has something to bind
    the caveat to, and so it appears in a stored run card."""
    run_id: str | None = None
    warnings: list[MarketWarning] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


class ScanEntry(BaseModel):
    """One (condition, horizon) test in a scan, with its correction applied."""

    label: str
    expression: str
    horizon: int
    guard: GuardReport = Field(default_factory=GuardReport)
    stats: HorizonStats | None = None
    """``None`` when the condition could not be evaluated. The entry still appears -- it consumed a
    trial, and dropping it would shrink the denominator that every other entry's q-value depends
    on."""
    p_value: float | None = None
    """Two-sided exact binomial: were ``sample_size`` draws at the baseline rate likely to produce
    this many winners? Computed on :attr:`HorizonStats.independent_sample_size`, never on the raw
    count -- overlapping windows would inflate ``n`` and shrink the p-value with no new information.
    ``None`` when the entry could not be tested."""
    q_value: float | None = None
    """Benjamini-Hochberg adjusted p-value over the whole scan. The number to read."""
    discovery: bool = False
    """``q_value <= alpha``. Not "true", not "significant" -- an expected-false-discovery-rate
    statement about the set, conditional on this scan being the whole family tested."""


class ScanResult(BaseModel):
    """Many conditions tested at once, with the cost of having tested many made visible.

    :attr:`trials` must equal ``len(entries)``; see the module docstring for why this is a validator
    and not a convention.
    """

    symbol: str
    interval: Interval
    generated_at: dt.datetime
    entry: Entry = Entry.NEXT_OPEN
    alpha: float = 0.10
    """Target false-discovery rate. Higher than a conventional 0.05 on purpose: this is a screening
    step whose output is a shortlist for a human to look at, not a publication threshold, and the
    expensive error here is discarding a real effect rather than looking at one more chart."""
    trials: int = 0
    """Every (condition, horizon) pair evaluated, including failures and guard rejections."""
    entries: list[ScanEntry] = Field(default_factory=list)
    discoveries: int = 0
    bars: int = 0
    first_bar: dt.date | None = None
    last_bar: dt.date | None = None
    run_id: str | None = None
    warnings: list[MarketWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def _trials_match_entries(self) -> Self:
        """A trial count that does not match the entries is the failure mode this whole class exists
        to prevent -- reporting the best six of forty and calling it six tests. Refusing to construct
        is the only enforcement that survives a caller who filters the list afterwards."""
        if self.trials != len(self.entries):
            raise ValueError(
                f"trials={self.trials} but {len(self.entries)} entries: every evaluated "
                "condition must appear in the result, including the ones that looked like nothing"
            )
        if self.discoveries != sum(1 for e in self.entries if e.discovery):
            raise ValueError(
                f"discoveries={self.discoveries} does not match the entries flagged as discoveries"
            )
        return self


# ---------------------------------------------------------------------------
# Run card
# ---------------------------------------------------------------------------


class RunCard(BaseModel):
    """An immutable record of one study: what was asked, what data answered it, what came back.

    The point is answering "why does this number differ from the one I saw last month?" without
    guessing. Two run cards with the same :attr:`params_hash` and different
    :attr:`data_fingerprint` mean the data changed under an unchanged question -- a corporate
    action, a backfill, a provider revision -- which is otherwise indistinguishable from a code bug.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    """Content hash over kind, params, data fingerprint and code version. The filename it is stored
    under, and the identity: writing a different payload under an existing ``run_id`` is refused."""
    kind: str
    """``drawdown``, ``event_study``, ``reverse``, ``scan``."""
    created_at: dt.datetime
    symbol: str
    interval: Interval
    params: dict[str, object] = Field(default_factory=dict)
    """The request, canonicalised: sorted keys, no defaults elided. What :attr:`params_hash` is
    taken over."""
    params_hash: str
    data_fingerprint: str
    """Identifies the exact bars the study saw: symbol, interval, first and last session, row count
    and a hash of the close column. Two runs agreeing here saw the same input, and one that does not
    is why the numbers moved."""
    code_version: str
    """Git revision when resolvable, otherwise ``"unknown"`` -- never a fabricated placeholder that
    would make two different builds look identical."""
    results: dict[str, object] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Strategy backtest
# ---------------------------------------------------------------------------
#
# An event study asks "what tended to follow this condition". A strategy backtest asks the different
# and much more flattering question "what would it have returned". Three things below exist because
# that second question is so much easier to answer dishonestly.
#
# **Buy-and-hold is not optional.** `StrategyResult.buy_hold` is a required field, for exactly the
# reason `HorizonStats.baseline_hit_rate` is: a strategy that returned 14% a year over a period when
# the instrument returned 19% a year lost money relative to doing nothing, and a page showing only
# the 14% has reported a success. This is the same rule as the hit-rate baseline, one level up.
#
# **Frictions are reported, not assumed away.** A rule that trades four hundred times looks entirely
# different at 0 bps and at 5 bps, and the difference is not a rounding detail --
# `StrategyResult.cost_drag` states what the frictions took, so a strategy whose whole edge is
# slippage is visibly so.
#
# **Every metric carries the assumption it depends on.** A Sharpe ratio computed against a 0% risk-free
# rate is a different number from one against 4%, and in a 5% rate environment the gap is most of the
# number. `StrategyMetrics` therefore records `risk_free_rate` and `bars_per_year` alongside the
# results rather than leaving them in the caller's head.


#: Trading bars per year, by interval, for annualising a return or a volatility.
#:
#: 252 is the conventional US equity count. Weekly is 52. These are approximations -- an actual year
#: holds 250 to 253 sessions -- and the error is small next to the sampling error of any Sharpe ratio
#: computed over a few years, but it is an approximation and is named here rather than buried.
#:
#: The intraday entries come from measured bars/session (live-probed against Yahoo's chart endpoint,
#: 2026-08-25), times 252 sessions/year, not from dividing the trading day evenly:
#:
#: * ``5m``  -- 78 bars/session (6.5h session / 5m) -> 78 * 252 = 19656
#: * ``15m`` -- 26 bars/session                      -> 26 * 252 = 6552
#: * ``30m`` -- 13 bars/session                      -> 13 * 252 = 3276
#: * ``1h``  -- 7 bars/session, **not** 6.5 -- Yahoo's last bar of the session is a 30-minute stub,
#:   not a full hour, so the count is 7 whole bars rather than 6 bars plus a fraction -> 7 * 252 = 1764
#: * ``4h``  -- 2 bars/session (one true 4h bar plus a 2.5h remainder bar Yahoo also calls "4h") ->
#:   2 * 252 = 504
#:
#: **These entries exist to prevent a `KeyError` when an intraday interval reaches this table, not to
#: endorse annualizing intraday statistics.** Annualizing a Sharpe ratio computed on 5-minute bars by
#: multiplying its per-bar variance by `sqrt(19656)` is statistically dubious: adjacent 5m bars are
#: strongly autocorrelated (violating the i.i.d. assumption the sqrt(N) scaling relies on), and a
#: single year of 5m data is ~19,656 highly non-independent samples describing microstructure noise,
#: not 19,656 independent draws of an annual return. Treat any annualized intraday metric this table
#: enables as a rough, likely-overstated magnitude, not a number to report as-is.
BARS_PER_YEAR: dict[Interval, float] = {
    Interval.FIVE_MIN: 19656.0,
    Interval.FIFTEEN_MIN: 6552.0,
    Interval.THIRTY_MIN: 3276.0,
    Interval.HOUR: 1764.0,
    Interval.FOUR_HOUR: 504.0,
    Interval.DAY: 252.0,
    Interval.WEEK: 52.0,
}


class ExitReason(StrEnum):
    """Why a position closed. Reported per trade because the mix is diagnostic: a strategy whose
    trades almost all end on ``STOP`` is a different thing from one whose trades end on ``SIGNAL``,
    even when their summary statistics match."""

    SIGNAL = "signal"
    """The exit condition became true."""
    HORIZON = "horizon"
    """The maximum holding period elapsed."""
    STOP = "stop"
    """The stop loss was hit. Priced at the stop level, not at the bar's close -- see
    :class:`StrategySpec`."""
    END_OF_DATA = "end_of_data"
    """The series ended with the position still open. These trades are marked and reported
    separately: their return is an unrealised mark, not a result, and folding them into a win rate
    counts an open position as a decided one."""


class Costs(BaseModel):
    """Trading frictions, applied on both entry and exit."""

    model_config = ConfigDict(frozen=True)

    slippage_bps: float = Field(default=5.0, ge=0.0)
    """Basis points of the fill price, each way. The default is deliberately non-zero: zero-cost is a
    choice a caller may make, but it should be a choice rather than what happens when nobody thought
    about it. Five is a plausible round-trip cost for a liquid ETF and an optimistic one for a
    leveraged product.

    ``ge=0`` because a negative value is not a smaller cost, it is a rebate: it would push the fill
    price the *favourable* direction on every entry and exit, manufacturing return that never
    existed. Cost fields model frictions, not a place to encode an edge."""
    commission_per_trade: float = Field(default=0.0, ge=0.0)
    """Flat currency amount per fill. Zero is realistic for current US retail brokerage.

    ``ge=0`` for the same reason as :attr:`slippage_bps`: a negative commission is a per-trade
    rebate that flatters every backtest built on this cost model, not a cheaper fill."""
    notional: float = Field(default=10_000.0, gt=0.0)
    """Capital the equity curve represents, used **only** to express
    :attr:`commission_per_trade` as a fraction of it.

    A flat currency commission has no natural unit against an equity curve that starts at ``1.0``:
    bars carry prices, not share counts, and position sizing is deliberately out of scope. Some
    notional is therefore required to convert one into the other, and it lives here -- a declared
    field that travels into the run card's params and can be set by the caller -- rather than as a
    constant buried in the simulator, where it would silently determine a number the user reads
    without appearing anywhere they could see it.

    Not a position-sizing decision, and inert at the default commission of ``0.0``. A strategy on
    $1,000 pays ten times the fractional commission of one on $10,000, and that is a real effect
    this field makes visible rather than assumes away.

    ``gt=0`` because :func:`app.backtest.strategy._simulate` divides ``commission_per_trade`` by
    this to get a fractional cost: zero turns a real commission into a silent no-op (division
    skipped, cost vanishes) and negative turns it into a manufactured *positive* return. Enforced
    here, on the type, rather than only at the one call site that used to guard it -- see
    :class:`app.api.report.StrategyRequest`, whose ``gt=0`` on the same field is deliberately kept
    alongside this one rather than treated as redundant."""


class StrategySpec(BaseModel):
    """What was tested. Recorded on the result so a number can never be read without its rules."""

    model_config = ConfigDict(frozen=True)

    entry: str
    """Rule DSL expression. Entry fills at the **next** bar's open, the same convention every other
    study here uses -- the signal bar's close is not obtainable."""
    exit: str | None = None
    """Optional exit expression. With none, positions close on ``max_holding_bars`` alone."""
    max_holding_bars: int | None = None
    """Hard cap on holding period. At least one of ``exit`` or this must be set, or a position opened
    once is never closed and the "strategy" is buy-and-hold with extra steps."""
    stop_loss_pct: float | None = None
    """Fractional adverse move from the entry price that closes the position, e.g. ``0.10`` for 10%.

    Filled at the stop level when the bar's low crosses it, **not** at the bar's close. Using the
    close would let a stop that was breached intraday be filled at a price that recovered, which
    understates the loss on exactly the days it matters. This is still optimistic -- a gap through
    the stop fills at the open, and that case is handled -- but no bar-resolution backtest can model
    a queue."""


class Trade(BaseModel):
    """One round trip."""

    model_config = ConfigDict(frozen=True)

    entry_date: dt.date | dt.datetime
    """The bar the position opened on: a calendar date on a daily run, a full timestamp on an
    intraday one, where a date cannot say which of a session's bars filled. `datetime` is a subclass
    of `date`, so the union is declared explicitly rather than widened to `datetime` -- pydantic
    would otherwise coerce every existing daily date to midnight and rewrite results already on
    disk."""
    entry_price: float
    """After slippage. The raw fill is recoverable from the bar; this is what was paid."""
    exit_date: dt.date | dt.datetime
    exit_price: float
    exit_reason: ExitReason
    bars_held: int
    return_pct: float
    """Net of frictions, as a fraction."""
    open_at_end: bool = False
    """``True`` when :attr:`exit_reason` is :attr:`ExitReason.END_OF_DATA`. An unrealised mark, not a
    result."""


class EquityPoint(BaseModel):
    """One point on the equity curve, indexed by session."""

    model_config = ConfigDict(frozen=True)

    date: dt.date
    equity: float
    """Strategy equity, starting at 1.0."""
    buy_hold: float
    """The same capital held in the instrument throughout, also starting at 1.0. Carried alongside
    rather than fetched separately so the two curves can never be drawn over different windows."""
    in_position: bool


class StrategyMetrics(BaseModel):
    """Summary statistics for one equity curve. Computed identically for the strategy and for
    buy-and-hold, so the pair is comparable by construction.

    The four annualised fields (:attr:`cagr`, :attr:`volatility`, :attr:`sharpe`, :attr:`sortino`)
    are ``None`` on intraday intervals as well as under the one-year floor each documents below --
    see :func:`app.backtest.metrics.compute`'s ``annualisable`` parameter. An hourly Sharpe and a
    daily Sharpe are not on the same scale, so a run at `1h` reports ``None`` rather than a number
    that invites the comparison."""

    model_config = ConfigDict(frozen=True)

    total_return: float | None = None
    cagr: float | None = None
    """``None`` when the sample is under a year -- annualising four months of returns produces a
    number that looks like a rate and is an extrapolation."""
    volatility: float | None = None
    """Annualised standard deviation of bar returns. ``None`` when the sample is under a year, for
    the same reason as :attr:`cagr`: multiplying a short-sample stdev by ``sqrt(bars_per_year)``
    produces a number shaped like an annual figure that the sample cannot support."""
    sharpe: float | None = None
    """``(mean excess return / stdev) * sqrt(bars_per_year)``, excess over
    :attr:`risk_free_rate`. ``None`` when the sample is under a year -- see :attr:`volatility`. A
    handful of trading days can produce a Sharpe in the 5-11 range from ordinary noise once
    multiplied by ``sqrt(bars_per_year)``; that is sampling error amplified by a constant, not a
    risk-adjusted return, and is withheld rather than shown at full precision alongside a legitimate
    multi-year figure."""
    sortino: float | None = None
    """As Sharpe, but the denominator counts only returns below the target. ``None`` when there were
    no losing bars -- an infinite Sortino is not a strong result, it is an empty denominator -- and
    ``None`` under a year of elapsed data, for the same reason as :attr:`sharpe`."""
    max_drawdown: float | None = None
    """Negative fraction, on the equity curve."""
    exposure: float | None = None
    """Fraction of bars holding a position. A strategy in the market 4% of the time carries 4% of the
    risk, and comparing its raw return to buy-and-hold's without saying so is the second-commonest
    way to make a rule look good."""
    trades: int = 0
    """**Every** trade the strategy opened, including one still open on the last bar.

    Stated because it does not agree with :attr:`win_rate`, which is over closed trades only, and
    because it is displayed next to :attr:`StrategyResult.open_trades` -- where a label reading
    "closed" invited adding the two and counting the open trade twice. The two figures answer "how
    often did this fire" and "how many of the finished ones worked", and those are different
    denominators."""
    trades_per_year: float | None = None
    """:attr:`trades` over elapsed years -- so it counts openings, on the same basis as the field
    above, not completed round trips."""
    win_rate: float | None = None
    """Over *closed* trades only; a position still open at the end of the series is excluded.

    A trade with no exit has no outcome to win or lose, and scoring it either way would be a guess
    about a position the strategy is still holding."""
    risk_free_rate: float = 0.0
    """Annualised, as a fraction. Recorded because Sharpe is meaningless without it."""
    bars_per_year: float = 252.0


class StrategyResult(BaseModel):
    """A full entry/exit backtest, against buy-and-hold over the identical window."""

    symbol: str
    interval: Interval
    generated_at: dt.datetime
    spec: StrategySpec
    costs: Costs
    guard: GuardReport = Field(default_factory=GuardReport)
    """The entry and exit expressions' lookahead verdict. A result whose guard did not pass must not
    render its numbers -- see :class:`GuardStatus`."""

    metrics: StrategyMetrics = Field(default_factory=StrategyMetrics)
    buy_hold: StrategyMetrics = Field(default_factory=StrategyMetrics)
    """**Required.** See this section's header comment: a strategy return without the return of doing
    nothing is not a result."""
    cost_drag: float | None = None
    """Total return with frictions minus total return without them. Always negative or zero. A
    strategy whose entire edge is inside this number has no edge."""

    equity_curve: list[EquityPoint] = Field(default_factory=list)
    trades: list[Trade] = Field(default_factory=list)
    open_trades: int = 0
    """Trades still open at the end of the series, excluded from :attr:`StrategyMetrics.win_rate`."""

    bars: int = 0
    first_bar: dt.date | None = None
    last_bar: dt.date | None = None
    run_id: str | None = None
    warnings: list[MarketWarning] = Field(default_factory=list)

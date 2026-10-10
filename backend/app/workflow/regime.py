"""A deterministic, LLM-free live market-regime classifier for the Agent Workflow desk.

**Why a live classifier is allowed a threshold the backtest one is not.** `app.timeframes.service.
_regime_arrays` is the only other regime classifier in this codebase, and it deliberately stops at two
buckets (rising/falling, from a trailing-window return's sign) rather than three: its own docstring
says a volatility bucket "needs an additional, arbitrary volatility threshold and tends to push at
least one bucket below the sufficiency gate anyway." That reasoning does not carry over here, because
the two classifiers answer different questions. `_regime_arrays`' bucket is a **denominator in a
statistic** -- it decides which bars get pooled into a rule's hit-rate, and an arbitrary cut there
manufactures significance: choose the threshold after seeing which choice makes a rule look better,
and the "measurement" is really curve-fitting wearing a methodology's clothes. A `RegimeCall` from
this module is not a denominator anywhere. It is **one label, steering one day's decision**, recorded
on the order it produces so a later audit can see exactly what was known and assumed at the time.
Getting a threshold "wrong" here costs one day's card selection, visibly, on the record -- it does not
retroactively inflate a sample size the way a bad regime cut in the backtest path would. That is the
whole difference, and it is why this module is comfortable naming a volatility-stress bucket the
backtest path refuses to.

**Fully deterministic, on purpose.** Every input below is a plain number or a short enum-like vote,
and every rule that turns a number into a vote is a named module-level constant compared with a fixed
operator (`<=`, `>=`). No model call, no randomness, no wall-clock read inside the decision path.
Given the same `market` inputs and the same `as_of`, `classify` returns a bit-for-bit identical
`RegimeCall` every time -- which is what makes this classifier unit-testable at all, and what lets a
later study attribute a workflow run's outcome to the regime call itself rather than to sampling noise
from a model that might answer a re-asked question differently.

**The four signals fused, and how a single label emerges from them.** Each of the four signals below
casts at most one vote, from the same three-member ballot (`risk_on_trend`, `risk_off`,
`choppy_neutral`) -- except the volatility signal, which only ever votes `high_vol_stress` or
abstains. A signal that computes successfully but sits in a genuinely ambiguous middle -- a mixed
trend, a fear/greed score near 50, a 2s10s spread that is neither inverted nor steep -- abstains
(casts no vote) rather than being forced to pick a side; abstaining is a real, informative outcome,
distinct from the signal being *unavailable* (an error, recorded as a warning and excluded from the
confidence denominator too).

Combining: if the volatility signal fires (`high_vol_stress`), that is the label, full stop --
volatility stress is treated as a distinct operating mode, not a flavour of `risk_off`, because
position sizing and execution under a volatility spike are a different problem from "the trend turned
down." Otherwise the label is whichever of the three trend-ballot outcomes has the most votes among
the remaining three signals; a tie is broken by a fixed priority, `risk_off` > `risk_on_trend` >
`choppy_neutral` -- a defensive posture is the lower-regret mistake when the vote is split, since a
missed rally costs a return delta and a missed drawdown costs capital. Zero votes cast (everything
abstained or failed) falls back to `choppy_neutral`, the "no strong signal either way" bucket, which is
exactly what that situation is.

**`confidence` is a vote share, not a probability -- said plainly so nobody downstream treats it as
one.** It is `(signals whose own vote matches the final label) / (signals that were available at
all)`, both counted over all four signals, computed with `Decimal` for reproducible arithmetic. A
signal that abstained counts in the denominator (it was available, it just did not lean this way) but
never in the numerator. `0` when every signal failed; there is no case where `confidence` is reported
without at least the fallback `choppy_neutral` label attached.

**Where each signal's numbers come from, and what this module refuses to fetch itself.**

* *SPY trend* -- close vs `SMA(200)` and the direction of `SMA(50)` over the trailing
  :data:`_TREND_SLOPE_LOOKBACK` bars, both via `app.indicators.trend.sma` (never hand-rolled: see that
  module's own warmup/`min_periods` reasoning for why a naive rolling mean would poison the first
  199 bars of any series with a number no chart would show).
* *Realized-volatility percentile* -- `app.indicators.volatility.atr`, normalised by close into a
  scale-free "ATR%", ranked against its own trailing history. ATR (Wilder-smoothed true range) is
  reused rather than a hand-rolled close-to-close standard deviation for the same "do not reimplement
  indicator math" reason every other package in this codebase gives; it is also less exposed to a
  single overnight gap dominating a short window than close-to-close would be.
* *Composite Fear & Greed* -- `app.market.fear_greed.composite_fear_greed`, called on whatever raw
  `FearGreedComponent` readings the caller supplies via `market.fear_greed_components` (empty by
  default, which that function already treats as a legitimate "no data" case: a neutral 50 plus its
  own warning, not an error). This module does not talk to CNN itself. Reusing `composite_fear_greed`
  rather than trusting a live CNN score directly is also what keeps this signal deterministic: CNN's
  own scoring weights and normalisation are undocumented and can change without notice, while
  `composite_fear_greed`'s scoring is fixed, published, and re-derivable from the same raw values
  every time.
* *Macro direction* -- the 10Y-2Y spread's latest value in percentage points, via
  `market.macro_2s10s_pct`. This module does not call `app.market.macro.build_snapshot` itself: that
  function's own docstring already describes a real, independent failure-boundary-per-tile FRED/
  CNN/store fallback chain, and re-implementing a second copy of that chain inside a classifier whose
  entire point is to be a small, pure, always-succeeds-or-warns function would just be two places that
  can disagree about what "unavailable" means for the same series. The caller (the Agent Workflow
  orchestrator, which already builds a macro snapshot for other stages) is expected to pass the number
  through; `None` here is treated as "not supplied" and degrades this one signal, exactly like a caller
  that supplies it but that value came from a downstream FRED outage would.

The one signal this module *does* fetch itself, when the caller does not supply it, is SPY's stored
bar history -- via `app.market.store.read_frame`, which (like `app.timeframes.service`'s identical
choice) never talks to a network provider; it is pure disk I/O over whatever is already synced. That
is the only "live default" in this module for exactly that reason: it carries no network dependency to
make non-deterministic or slow, unlike the CNN and FRED-backed signals above.

**Thresholds are pre-registered guesses, not fitted values.** Every constant below is a named,
commented judgement call -- a round number chosen for face-validity (a 200/50-day moving-average pair,
an 85th percentile for "stressed," CNN's own extreme-fear/extreme-greed cut points, a positive/
inverted 2s10s spread) -- never a value chosen because it made a backtest look better. **Changing any
of them mid-study invalidates that study's comparability**: a regime call attached to an order is only
useful evidence if the rule that produced it was fixed before the order was placed, for the same
reason `app.tournament.models.StrategyCard.designed_through` polices strategy authors. Move a
threshold, and every `RegimeCall` recorded before the move was answering a different question than
every one recorded after it.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal, NamedTuple

import pandas as pd
from pydantic import BaseModel, ConfigDict

from app.config import Settings, get_settings
from app.db.duck import Interval
from app.indicators.trend import sma
from app.indicators.volatility import atr
from app.market.fear_greed import composite_fear_greed
from app.market.macro_models import FearGreedComponent
from app.market.store import read_frame
from app.tournament.models import StrategyCard

__all__ = [
    "RegimeCall",
    "RegimeInput",
    "RegimeLabel",
    "RegimeMapError",
    "RegimeMarketData",
    "classify",
    "load_regime_map",
]

RegimeLabel = Literal["risk_on_trend", "risk_off", "choppy_neutral", "high_vol_stress"]

#: Canonical order every `RegimeCall.inputs` tuple is built in, and the full label vocabulary
#: `load_regime_map` requires the on-disk map to cover.
_REGIME_LABELS: Final[tuple[RegimeLabel, ...]] = (
    "risk_on_trend",
    "risk_off",
    "choppy_neutral",
    "high_vol_stress",
)

# ---------------------------------------------------------------------------
# Thresholds -- see the module docstring's closing section: pre-registered judgement calls, never
# fitted to data, and never to be changed mid-study. Every one is used exactly once, at the single
# call site named in its own comment, so moving a constant here is the only edit ever needed.
# ---------------------------------------------------------------------------

#: SPY trend, `_spy_trend_signal`: the long moving average a close is compared against. 200 trading
#: days (~10 months) is the conventional "long-term trend" window on every retail and institutional
#: chart alike -- a face-valid default, not a fitted one.
_TREND_SMA_LONG: Final[int] = 200

#: SPY trend: the short moving average whose *slope* (not level) is read for trend direction.
_TREND_SMA_SHORT: Final[int] = 50

#: SPY trend: how many bars back the short moving average's slope is measured over. Two trading weeks
#: -- short enough to react within a month, long enough that one or two noisy sessions cannot flip it.
_TREND_SLOPE_LOOKBACK: Final[int] = 10

#: Realized-volatility signal, `_realized_vol_signal`: Wilder ATR's own period. 14 is Wilder's
#: published default and the one every charting platform ships; not tuned for this classifier.
_ATR_PERIOD: Final[int] = 14

#: Realized-volatility signal: minimum count of ATR% observations required before a percentile rank
#: against "its own history" means anything. Below this, a "percentile" is just a rank among a
#: handful of numbers, which can jump from the 10th to the 90th percentile on one new observation.
_VOL_MIN_HISTORY: Final[int] = 30

#: Realized-volatility signal: how much ATR% history feeds the percentile rank, at most. ~1 trading
#: year -- a ranking window this long is long enough to have seen a real calm/stressed range, and
#: capping it (rather than using the whole series) keeps a decade-old volatility spike from still
#: anchoring today's percentile.
_VOL_HISTORY_WINDOW: Final[int] = 252

#: Realized-volatility signal: the percentile rank, at or above which trailing ATR% counts as
#: "stressed." The 85th percentile is a round, conservative cut -- roughly "one session in seven" --
#: chosen for face validity, not fitted against any labelled stress episode.
_VOL_STRESS_PERCENTILE: Final[float] = 85.0

#: Fear & Greed signal, `_fear_greed_signal`: composite score at or below this counts as a `risk_off`
#: vote. Mirrors CNN's own published "extreme fear" cut point
#: (`app.market.macro_models.RATING_BANDS`), reused rather than re-invented so this classifier's
#: fear/greed vocabulary agrees with what the macro page itself already calls "extreme fear."
_FEAR_VOTE_THRESHOLD: Final[float] = 25.0

#: Fear & Greed signal: composite score at or above this counts as a `risk_on_trend` vote. Mirrors
#: CNN's own "extreme greed" cut point, same reasoning as `_FEAR_VOTE_THRESHOLD`.
_GREED_VOTE_THRESHOLD: Final[float] = 75.0

#: Macro signal, `_macro_signal`: the 10Y-2Y spread, in percentage points, at or below which the curve
#: counts as inverted and casts a `risk_off` vote. Zero is the textbook inversion line -- a policy
#: convention, not a fitted cut.
_MACRO_INVERSION_PCT: Final[float] = 0.0

#: Macro signal: the 10Y-2Y spread, in percentage points, at or above which the curve counts as
#: steepening enough to cast a `risk_on_trend` vote. 0.50 (50 basis points) is a round "clearly
#: positive, not just barely" threshold, not a fitted one.
_MACRO_STEEPENING_PCT: Final[float] = 0.50

#: Tie-break order when the three-way ballot (`risk_on_trend` / `risk_off` / `choppy_neutral`) is
#: split evenly -- see the module docstring's "Combining" section for why defense wins ties.
_VOTE_PRIORITY: Final[tuple[RegimeLabel, ...]] = ("risk_off", "risk_on_trend", "choppy_neutral")

#: `Decimal` places `confidence` is rounded to. Cosmetic only -- the vote-share arithmetic behind it
#: is exact for any four-signal count (quarters), this just keeps the field from printing a long
#: repeating-decimal artifact of `Decimal` division for other denominators.
_CONFIDENCE_PLACES: Final[Decimal] = Decimal("0.0001")


# ---------------------------------------------------------------------------
# The result models
# ---------------------------------------------------------------------------


class _Frozen(BaseModel):
    """House style, matching `app.agentdesk.models._Frozen` / `app.tournament.models._Frozen`."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class RegimeInput(_Frozen):
    """One signal's contribution to a `RegimeCall`, whether or not it ended up agreeing with the
    label that was chosen."""

    name: str
    """Stable signal name: `"spy_trend"`, `"realized_vol"`, `"fear_greed"`, `"macro_2s10s"`."""

    value: str
    """The signal's own reading, rendered for a human -- the raw numbers and the vote they produced,
    or `"unavailable: <reason>"` when the signal could not be computed at all."""

    source: str
    """Where the number came from: `"app.market.store"`, `"app.indicators.volatility.atr"`,
    `"app.market.fear_greed.composite_fear_greed"`, `"app.market.macro (caller-supplied)"`."""

    contributed: bool
    """`True` only when this signal was available *and* its own vote equals the call's final `label`
    -- see the module docstring's `confidence` section. A signal that abstained, disagreed, or was
    unavailable is `False` here even though it may still explain something about the call."""


class RegimeCall(_Frozen):
    """One deterministic market-regime label, with the full working behind it.

    Two calls built from identical `inputs`/`warnings`/`confidence`/`label`/`as_of` compare equal
    (this model is frozen and holds no non-comparable state), which is exactly what
    `tests/test_workflow_regime.py`'s determinism test relies on.
    """

    label: RegimeLabel
    as_of: dt.date
    inputs: tuple[RegimeInput, ...]
    warnings: tuple[str, ...]
    """One entry per signal that raised rather than voting or abstaining, naming the signal and why.
    Empty means every signal that was attempted produced a reading (not that every signal agreed)."""
    confidence: Decimal
    """Share of the four signals (available signals only counted in the denominator) whose own vote
    equals `label` -- a vote share, not a probability. See the module docstring."""


# ---------------------------------------------------------------------------
# Market inputs -- what `classify` reads its four signals from
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegimeMarketData:
    """Everything `classify` can be handed instead of computing or fetching it live.

    Every field independently defaults to "not supplied." For `spy_bars`, "not supplied" means
    `classify` reads it live from the local bar store (see the module docstring for why that fetch,
    and only that one, is safe to do by default). For `fear_greed_components` and `macro_2s10s_pct`,
    "not supplied" means the corresponding signal degrades exactly as it would if the caller *tried*
    to supply it and failed -- there is no live default for either (again, see the module docstring).

    Tests build this directly with fixture data and never rely on the live defaults, which is what
    keeps this module's test suite free of network calls and of dependence on whatever happens to be
    sitting in the local bar store on the machine running the tests.
    """

    spy_bars: pd.DataFrame | None = None
    """OHLCV frame with at least a `close` column, ascending by date, already bounded to
    `ts <= as_of` -- `classify` trusts this contract rather than re-truncating it. `None` means "read
    SPY's stored daily bars via `app.market.store.read_frame`, bounded to `as_of`, instead"."""

    fear_greed_components: tuple[FearGreedComponent, ...] = ()
    """Raw Fear & Greed component readings, in whatever order -- passed straight to
    `composite_fear_greed`. Empty (the default) is a legitimate "no data" input that function already
    handles gracefully."""

    macro_2s10s_pct: float | None = None
    """The 10Y-2Y Treasury spread's latest value, in percentage points (e.g. `0.35` for 35bp), as
    already resolved by the caller from `app.market.macro`. `None` (the default) marks this signal
    unavailable -- see the module docstring for why `classify` does not fetch this itself."""


class _SignalUnavailable(Exception):
    """Raised by a `_*_signal` helper when its inputs cannot support a reading at all.

    Caught once, generically, at each call site in `classify` -- never propagated -- so one signal's
    outage degrades only that signal's `RegimeInput`/warning, per the module docstring's "each in its
    own try/except" requirement.
    """


class _Signal(NamedTuple):
    """One evaluated signal, before the final label is known.

    `vote` is `None` for both an abstention (computed fine, landed in a genuinely neutral band) and an
    outright failure -- `available` is what tells the two apart when `classify` computes `confidence`
    and builds warnings.
    """

    name: str
    source: str
    available: bool
    vote: RegimeLabel | None
    value: str


# ---------------------------------------------------------------------------
# The four signals
# ---------------------------------------------------------------------------


def _load_spy_bars(*, settings: Settings, as_of: dt.date) -> pd.DataFrame:
    """The live default for `RegimeMarketData.spy_bars` -- see that field's docstring and the module
    docstring's "does not fetch itself" section for why this is the one exception."""
    try:
        return read_frame("SPY", Interval.DAY, end=as_of, settings=settings)
    except Exception as exc:
        # signals below rather than this module as a whole; see `_SignalUnavailable`'s docstring.
        raise _SignalUnavailable(f"could not read stored SPY bars: {exc}") from exc


def _spy_trend_signal(bars: pd.DataFrame | None) -> _Signal:
    """Close vs `SMA(200)`, direction of `SMA(50)` -- see the module docstring's bullet on this
    signal and `_TREND_SMA_LONG`/`_TREND_SMA_SHORT`/`_TREND_SLOPE_LOOKBACK` for the thresholds.

    Votes `risk_on_trend` only when *both* legs agree bullish (close above the long average, the
    short average still rising) and `risk_off` only when both agree bearish. Anything mixed --
    price above trend but the short average already rolling over, or the reverse -- abstains: that
    disagreement between the two legs is itself the "this is not a clean trend" reading, which is
    exactly `choppy_neutral`'s job to catch when nothing else casts a vote either.
    """
    name, source = "spy_trend", "app.market.store"
    if bars is None or "close" not in bars.columns:
        raise _SignalUnavailable("no SPY bar frame available")
    required = _TREND_SMA_LONG + _TREND_SLOPE_LOOKBACK
    if len(bars) < required:
        raise _SignalUnavailable(
            f"need at least {required} SPY bars for a {_TREND_SMA_LONG}-day SMA plus a "
            f"{_TREND_SLOPE_LOOKBACK}-bar slope, got {len(bars)}"
        )

    close = bars["close"].reset_index(drop=True)
    sma_long = sma(bars, period=_TREND_SMA_LONG).iloc[:, 0].reset_index(drop=True)
    sma_short = sma(bars, period=_TREND_SMA_SHORT).iloc[:, 0].reset_index(drop=True)

    last_close = float(close.iloc[-1])
    last_long = float(sma_long.iloc[-1])
    last_short = float(sma_short.iloc[-1])
    prior_short = float(sma_short.iloc[-1 - _TREND_SLOPE_LOOKBACK])
    if any(pd.isna(x) for x in (last_close, last_long, last_short, prior_short)):
        raise _SignalUnavailable("SMA warmup not settled over the supplied SPY bars")

    slope = last_short - prior_short
    above_long = last_close > last_long
    rising_short = slope > 0

    if above_long and rising_short:
        vote: RegimeLabel | None = "risk_on_trend"
    elif (not above_long) and (not rising_short):
        vote = "risk_off"
    else:
        vote = None

    value = (
        f"close={last_close:.2f} sma{_TREND_SMA_LONG}={last_long:.2f} "
        f"sma{_TREND_SMA_SHORT}_slope_{_TREND_SLOPE_LOOKBACK}d={slope:+.4f} -> "
        f"{vote or 'mixed/abstain'}"
    )
    return _Signal(name=name, source=source, available=True, vote=vote, value=value)


def _realized_vol_signal(bars: pd.DataFrame | None) -> _Signal:
    """ATR, normalised by close, ranked against its own trailing history -- see the module
    docstring's bullet on this signal and `_ATR_PERIOD`/`_VOL_MIN_HISTORY`/`_VOL_HISTORY_WINDOW`/
    `_VOL_STRESS_PERCENTILE` for the thresholds.

    Only ever votes `high_vol_stress` or abstains -- calm volatility has nothing distinctive to say
    about *which* of the other three regimes applies, so it does not participate in that ballot.
    """
    name, source = "realized_vol", "app.indicators.volatility.atr"
    if bars is None or "close" not in bars.columns:
        raise _SignalUnavailable("no SPY bar frame available")

    atr_series = atr(bars, period=_ATR_PERIOD).iloc[:, 0]
    close = bars["close"]
    atr_pct = (atr_series / close).dropna()
    if len(atr_pct) < _VOL_MIN_HISTORY:
        raise _SignalUnavailable(
            f"need at least {_VOL_MIN_HISTORY} settled ATR% observations, got {len(atr_pct)}"
        )

    current = float(atr_pct.iloc[-1])
    window = atr_pct.tail(_VOL_HISTORY_WINDOW)
    percentile = float((window <= current).mean() * 100.0)

    vote: RegimeLabel | None = "high_vol_stress" if percentile >= _VOL_STRESS_PERCENTILE else None
    value = (
        f"atr{_ATR_PERIOD}_pct_of_close={current * 100:.3f}% percentile_of_last_"
        f"{len(window)}={percentile:.1f} -> {vote or 'calm/abstain'}"
    )
    return _Signal(name=name, source=source, available=True, vote=vote, value=value)


def _fear_greed_signal(components: tuple[FearGreedComponent, ...], *, as_of: dt.date) -> _Signal:
    """`composite_fear_greed`'s score, banded at CNN's own extreme-fear/extreme-greed cuts -- see the
    module docstring's bullet on this signal and `_FEAR_VOTE_THRESHOLD`/`_GREED_VOTE_THRESHOLD`.
    """
    name, source = "fear_greed", "app.market.fear_greed.composite_fear_greed"
    result = composite_fear_greed(components, as_of=as_of)  # may raise; caught by the caller
    score = result.score

    vote: RegimeLabel | None
    if score <= _FEAR_VOTE_THRESHOLD:
        vote = "risk_off"
    elif score >= _GREED_VOTE_THRESHOLD:
        vote = "risk_on_trend"
    else:
        vote = None

    value = f"composite_score={score:.1f} rating={result.rating.value} -> {vote or 'neutral/abstain'}"
    signal = _Signal(name=name, source=source, available=True, vote=vote, value=value)
    return signal


def _macro_signal(spread_pct: float | None) -> _Signal:
    """The 10Y-2Y spread, banded at inversion/steepening -- see the module docstring's bullet on
    this signal and `_MACRO_INVERSION_PCT`/`_MACRO_STEEPENING_PCT`."""
    name, source = "macro_2s10s", "app.market.macro (caller-supplied)"
    if spread_pct is None:
        raise _SignalUnavailable(
            "no 2s10s spread value supplied via RegimeMarketData.macro_2s10s_pct -- classify() does "
            "not call app.market.macro itself, see the module docstring"
        )

    vote: RegimeLabel | None
    if spread_pct <= _MACRO_INVERSION_PCT:
        vote = "risk_off"
    elif spread_pct >= _MACRO_STEEPENING_PCT:
        vote = "risk_on_trend"
    else:
        vote = None

    value = f"2s10s_spread_pct={spread_pct:+.3f} -> {vote or 'flat/abstain'}"
    return _Signal(name=name, source=source, available=True, vote=vote, value=value)


# ---------------------------------------------------------------------------
# Combining the four signals into one call
# ---------------------------------------------------------------------------


def _combine_ballot(votes: list[RegimeLabel | None]) -> RegimeLabel:
    """Majority of `votes` among the three-member ballot, tie-broken by `_VOTE_PRIORITY`, falling
    back to `choppy_neutral` when nothing voted at all. See the module docstring's "Combining"
    section -- `votes` here never contains `high_vol_stress`; that label is decided by the caller
    before this function is reached."""
    counts: dict[RegimeLabel, int] = {}
    for vote in votes:
        if vote is not None:
            counts[vote] = counts.get(vote, 0) + 1
    if not counts:
        return "choppy_neutral"
    best = max(counts.values())
    for label in _VOTE_PRIORITY:
        if counts.get(label) == best:
            return label
    return "choppy_neutral"  # unreachable: _VOTE_PRIORITY covers every key `counts` can hold


def classify(
    *, settings: Settings, as_of: dt.date, market: RegimeMarketData | None = None
) -> RegimeCall:
    """Fuse four independent, individually-degrading signals into one deterministic `RegimeCall`.

    See the module docstring for the full reasoning: what each signal is, where its number comes
    from, how the four combine into one label, and what `confidence` does and does not mean. Never
    raises for a signal's own failure -- a signal that cannot be computed degrades to a warning
    naming it and is excluded from the confidence denominator; the worst case (every signal fails) is
    still a valid `RegimeCall` (`choppy_neutral`, `confidence=0`, four warnings), never an exception.
    """
    data = market if market is not None else RegimeMarketData()

    spy_bars = data.spy_bars
    if spy_bars is None:
        try:
            spy_bars = _load_spy_bars(settings=settings, as_of=as_of)
        except _SignalUnavailable:
            # Left `None`: `_spy_trend_signal`/`_realized_vol_signal` each raise their own
            # self-explanatory "no SPY bar frame available" for this case, one warning per signal
            # rather than one shared one -- consistent with every other signal degrading on its own.
            spy_bars = None

    signal_thunks: tuple[tuple[str, str, Callable[[], _Signal]], ...] = (
        ("spy_trend", "app.market.store", lambda: _spy_trend_signal(spy_bars)),
        ("realized_vol", "app.indicators.volatility.atr", lambda: _realized_vol_signal(spy_bars)),
        (
            "fear_greed",
            "app.market.fear_greed.composite_fear_greed",
            lambda: _fear_greed_signal(data.fear_greed_components, as_of=as_of),
        ),
        (
            "macro_2s10s",
            "app.market.macro (caller-supplied)",
            lambda: _macro_signal(data.macro_2s10s_pct),
        ),
    )

    signals: list[_Signal] = []
    warnings: list[str] = []
    for name, source, thunk in signal_thunks:
        try:
            signals.append(thunk())
        except Exception as exc:
            # `_SignalUnavailable`, or a third-party/monkeypatched exception from e.g.
            # `composite_fear_greed`) degrades only this one signal, per the module docstring.
            signals.append(
                _Signal(
                    name=name, source=source, available=False, vote=None, value=f"unavailable: {exc}"
                )
            )
            warnings.append(f"{name} unavailable: {exc}")

    by_name = {s.name: s for s in signals}
    vol_signal = by_name["realized_vol"]

    label: RegimeLabel
    if vol_signal.available and vol_signal.vote == "high_vol_stress":
        label = "high_vol_stress"
    else:
        ballot_votes = [
            by_name["spy_trend"].vote,
            by_name["fear_greed"].vote,
            by_name["macro_2s10s"].vote,
        ]
        label = _combine_ballot(ballot_votes)

    available_count = sum(1 for s in signals if s.available)
    agreeing_count = sum(1 for s in signals if s.available and s.vote == label)
    confidence = (
        (Decimal(agreeing_count) / Decimal(available_count)).quantize(_CONFIDENCE_PLACES)
        if available_count > 0
        else Decimal("0")
    )

    inputs = tuple(
        RegimeInput(
            name=s.name,
            value=s.value,
            source=s.source,
            contributed=s.available and s.vote == label,
        )
        for s in signals
    )

    return RegimeCall(
        label=label,
        as_of=as_of,
        inputs=inputs,
        warnings=tuple(warnings),
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# The static regime -> strategy-card map
# ---------------------------------------------------------------------------

_REGIME_MAP_PATH: Final[Path] = Path(__file__).resolve().parent / "regime_map.json"


class RegimeMapError(ValueError):
    """`regime_map.json` is malformed, incomplete, or names an `agent_id` this build's strategy
    library cannot resolve. Raised at load time, deliberately loud -- see `load_regime_map`."""


def _index_library_by_agent_id(settings: Settings) -> dict[str, Path]:
    """`agent_id -> file path`, over every `StrategyCard`-shaped JSON file under `settings.
    library_dir` (recursively, across every tier).

    Tolerant of files that are not a `StrategyCard` at all: `ladder/` and `allocation/` cards
    validate against a different model entirely (`AllocationCard`/`LadderCard` -- see
    `app.tournament.results`'s own tier handling for why those two tiers are not part of
    `StrategyCard`'s world), and a stray sidecar (`provenance.json`, `README.md`) is not a card
    either. All of that is skipped here rather than raising -- this function only builds a lookup
    table; `load_regime_map` below is what raises loudly, and only when a card the map actually
    *references* cannot be found.
    """
    index: dict[str, Path] = {}
    root = settings.library_dir
    if not root.is_dir():
        return index
    for path in sorted(root.rglob("*.json")):
        try:
            card = StrategyCard.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            # defect; see the docstring above.
            continue
        index.setdefault(card.agent_id, path)
    return index


def load_regime_map(settings: Settings | None = None) -> dict[RegimeLabel, tuple[str, ...]]:
    """Load and validate `regime_map.json`: every `RegimeLabel` covered, every `agent_id` real.

    A map pointing at a card that does not exist fails loudly here, at load time, naming the label
    and the missing `agent_id` -- never silently at the moment a live workflow run tries to trade a
    regime nobody caught was pointing at a typo.
    """
    cfg = settings if settings is not None else get_settings()

    try:
        raw_text = _REGIME_MAP_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegimeMapError(f"cannot read regime map at {_REGIME_MAP_PATH}: {exc}") from exc

    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RegimeMapError(f"regime map at {_REGIME_MAP_PATH} is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise RegimeMapError(f"regime map at {_REGIME_MAP_PATH} must be a JSON object")

    index = _index_library_by_agent_id(cfg)

    result: dict[RegimeLabel, tuple[str, ...]] = {}
    for label in _REGIME_LABELS:
        agent_ids = raw.get(label)
        if agent_ids is None:
            raise RegimeMapError(
                f"regime map at {_REGIME_MAP_PATH} has no entry for {label!r}; every one of "
                f"{_REGIME_LABELS} must be covered"
            )
        if not isinstance(agent_ids, list) or not agent_ids:
            raise RegimeMapError(
                f"regime map label {label!r} at {_REGIME_MAP_PATH} must be a non-empty list of "
                "agent_id strings"
            )
        resolved: list[str] = []
        for agent_id in agent_ids:
            path = index.get(agent_id)
            if path is None:
                raise RegimeMapError(
                    f"regime map label {label!r} references agent_id {agent_id!r}, which does not "
                    f"resolve to a StrategyCard anywhere under {cfg.library_dir} -- check for a typo "
                    "or a card that was moved or retired"
                )
            resolved.append(agent_id)
        result[label] = tuple(resolved)
    return result

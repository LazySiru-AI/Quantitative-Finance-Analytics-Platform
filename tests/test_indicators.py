"""Tests for the indicator library.

Every numeric assertion is checked against an independently computed value -- a hand-worked
example, or a small reference implementation that does not share code with the module under test --
never against the module's own output fed back through itself. That is the only way a wrong default
(``ddof=1``, ``adjust=True``, a plain rolling mean where Wilder's smoothing belongs) gets caught
instead of silently matching "the code does what the code does."
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
import pytest

from app.indicators.base import IndicatorError, IndicatorSpec
from app.indicators.momentum import rsi
from app.indicators.registry import catalog, compute, default_spec, get, request
from app.indicators.trend import ema, macd, sma
from app.indicators.volatility import atr, bollinger
from app.indicators.vwap import anchored_vwap
from app.market.models import BAR_COLUMNS, Interval

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _bars(
    *,
    close: Sequence[float],
    high: Sequence[float] | None = None,
    low: Sequence[float] | None = None,
    volume: Sequence[float | None] | None = None,
    start: dt.datetime = dt.datetime(2026, 1, 2, 13, 30, tzinfo=dt.UTC),
    step: dt.timedelta = dt.timedelta(days=1),
) -> pd.DataFrame:
    """A minimal bar frame: enough columns for every indicator, real UTC timestamps."""
    n = len(close)
    high_ = list(high) if high is not None else [c + 0.5 for c in close]
    low_ = list(low) if low is not None else [c - 0.5 for c in close]
    volume_ = list(volume) if volume is not None else [1_000.0] * n
    ts = pd.to_datetime([start + step * i for i in range(n)], utc=True)
    return pd.DataFrame(
        {
            "ts": ts,
            "open": close,
            "high": high_,
            "low": low_,
            "close": close,
            "adj_close": close,
            "volume": volume_,
        }
    )


def _empty_bars() -> pd.DataFrame:
    return pd.DataFrame(columns=list(BAR_COLUMNS))


def _default_params(spec: IndicatorSpec) -> dict[str, Any]:
    return {p.name: p.default for p in spec.params}


# A long, gently oscillating close series -- enough bars that every registered indicator's default
# warmup (the longest is MACD's) leaves plenty of settled values to inspect.
_LONG_CLOSE = [100 + 5 * math.sin(i / 4) + 0.1 * i for i in range(60)]


# ---------------------------------------------------------------------------
# SMA
# ---------------------------------------------------------------------------


class TestSMA:
    def test_matches_hand_computed_rolling_mean(self) -> None:
        closes = [1, 2, 3, 4, 5, 6, 7]
        bars = _bars(close=closes)
        result = sma(bars, period=3)
        values = result["sma_3"].tolist()

        expected = [None, None, 2.0, 3.0, 4.0, 5.0, 6.0]
        for got, want in zip(values, expected, strict=True):
            if want is None:
                assert math.isnan(got)
            else:
                assert got == pytest.approx(want)

    def test_min_periods_enforced_differs_from_pandas_rolling_default(self) -> None:
        """`min_periods=period` is mandatory -- pandas' default of 1 would average a partial window."""
        closes = [1, 2, 3, 4, 5]
        bars = _bars(close=closes)
        result = sma(bars, period=3)["sma_3"]
        naive = bars["close"].rolling(3, min_periods=1).mean()  # the wrong default
        # They agree once the window is full, but the naive version fabricates values at the head
        # where the correct one is NaN.
        assert result.isna().sum() == 2
        assert naive.isna().sum() == 0
        assert not naive.iloc[0:2].isna().any()


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------


class TestEMA:
    def test_matches_recursive_formula_by_hand(self) -> None:
        closes = [10.0, 11.0, 12.0, 13.0, 14.0]
        period = 3
        bars = _bars(close=closes)
        result = ema(bars, period=period)["ema_3"]

        alpha = 2 / (period + 1)
        # adjust=False recursion, seeded at the first observation, masked to NaN until min_periods.
        recursive = [closes[0]]
        for c in closes[1:]:
            recursive.append(alpha * c + (1 - alpha) * recursive[-1])

        assert math.isnan(result.iloc[0])
        assert math.isnan(result.iloc[1])
        for i in range(2, len(closes)):
            assert result.iloc[i] == pytest.approx(recursive[i])

    def test_differs_from_adjust_true_default(self) -> None:
        """`adjust=True` (pandas' default) is a different series, most divergent at the start."""
        closes = [10.0, 20.0, 15.0, 30.0, 25.0, 40.0, 35.0]
        bars = _bars(close=closes)
        correct = ema(bars, period=3)["ema_3"]
        wrong = bars["close"].ewm(span=3, adjust=True, min_periods=3).mean()
        # Both are defined from the same point on, but the values disagree.
        assert not np.allclose(correct.dropna().to_numpy(), wrong.dropna().to_numpy())

    def test_missing_close_is_remasked_to_nan_not_held_from_previous_bar(self) -> None:
        """`ewm(adjust=False)` treats a missing `close` as "hold state" and would otherwise
        fabricate an exact repeat of the previous EMA at that bar -- indistinguishable downstream
        from a genuinely flat close. Contrast `sma`'s `rolling(min_periods=period)`, which already
        propagates a gap correctly without needing this re-mask.
        """
        closes = list(_LONG_CLOSE)
        closes[20] = math.nan
        bars = _bars(close=closes)
        result = ema(bars, period=5)["ema_5"]

        assert not math.isnan(result.iloc[19])  # unaffected: gap not reached yet
        assert math.isnan(result.iloc[20])  # the missing bar itself -- not held from bar 19
        assert not math.isnan(result.iloc[21])  # the *next* bar has a real close, unlike RSI's diff


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------


class TestMACD:
    def test_hist_equals_macd_minus_signal(self) -> None:
        bars = _bars(close=_LONG_CLOSE)
        result = macd(bars, fast=12, slow=26, signal=9)
        macd_line = result["macd_12_26_9_macd"]
        signal_line = result["macd_12_26_9_signal"]
        hist = result["macd_12_26_9_hist"]
        diff = (macd_line - signal_line - hist).dropna()
        assert (diff.abs() < 1e-9).all()

    def test_combined_warmup_is_slow_minus_one_plus_signal_minus_one(self) -> None:
        """Composed NaN counts, not `slow + signal - 1`.

        Chaining two `ewm(..., min_periods=p)` calls adds `p - 1` on top of however many leading
        NaNs the input already carried -- `min_periods` counts *non-null* observations, so it does
        not re-count NaNs the upstream EMA already produced. The macd line itself is NaN through
        `slow - 1` bars; re-smoothing it with `min_periods=signal` adds `signal - 1` more before its
        own first valid value, for a total of `(slow - 1) + (signal - 1)`. This was verified against
        actual pandas output (not derived on paper alone) before being pinned here -- an earlier
        draft of the spec described this as `slow + signal - 1`, which is off by one; see this
        module's final report for the flag.
        """
        fast, slow, signal = 3, 6, 2
        bars = _bars(close=list(range(1, 41)))
        result = macd(bars, fast=fast, slow=slow, signal=signal)

        macd_nan = result["macd_3_6_2_macd"].isna().sum()
        hist_nan = result["macd_3_6_2_hist"].isna().sum()
        signal_nan = result["macd_3_6_2_signal"].isna().sum()

        assert macd_nan == slow - 1
        assert signal_nan == (slow - 1) + (signal - 1)
        assert hist_nan == (slow - 1) + (signal - 1)

        spec = get("macd")
        assert spec is not None
        assert spec.warmup({"fast": fast, "slow": slow, "signal": signal}) == (slow - 1) + (
            signal - 1
        )

    def test_fast_greater_than_or_equal_to_slow_raises(self) -> None:
        """Nothing about subtracting two EMAs requires the faster one to actually be faster --
        `EMA(26) - EMA(12)` computes just fine -- but it silently inverts the sign of every
        crossover a momentum rule keys off, labelled with the user's own parameters. `fast == slow`
        is equally nonsensical (a MACD line of exactly zero throughout) and must also raise.
        """
        bars = _bars(close=_LONG_CLOSE)
        with pytest.raises(IndicatorError):
            macd(bars, fast=26, slow=12, signal=9)
        with pytest.raises(IndicatorError):
            macd(bars, fast=12, slow=12, signal=9)
        # The ordinary, correctly-ordered configuration is unaffected.
        macd(bars, fast=12, slow=26, signal=9)

    def test_missing_close_propagates_as_nan_through_macd_signal_and_hist(self) -> None:
        """A bar with a missing `close` is NaN in both EMAs, therefore NaN in `macd` (subtraction
        of NaN), and the `signal` EMA -- itself another `.ewm(adjust=False)` chained on top of the
        now-NaN-bearing `macd` line -- must be explicitly re-masked at that same bar too, or its
        own `ewm` would hold its previous `signal` value forward across the gap exactly like RSI's
        and EMA's did before their fixes. `hist` needs no separate re-mask: `macd - signal` is
        already NaN because either operand is.
        """
        closes = list(_LONG_CLOSE)
        closes[30] = math.nan
        bars = _bars(close=closes)
        result = macd(bars, fast=3, slow=6, signal=2)

        assert math.isnan(result["macd_3_6_2_macd"].iloc[30])
        assert math.isnan(result["macd_3_6_2_signal"].iloc[30])
        assert math.isnan(result["macd_3_6_2_hist"].iloc[30])
        # Well clear of the gap, all three legs settle back to ordinary values.
        for col in ("macd_3_6_2_macd", "macd_3_6_2_signal", "macd_3_6_2_hist"):
            assert not math.isnan(result[col].iloc[40])


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    """RSI's boundary-degenerate formula, shared by the reference and (independently) by `rsi`
    itself -- this is the textbook tie-break (no losses at all is unambiguously 100, no gains at
    all is unambiguously 0), not an implementation detail being mirrored."""
    if avg_loss == 0:
        return 100.0
    if avg_gain == 0:
        return 0.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def _reference_rsi(closes: Sequence[float], period: int) -> list[float]:
    """Wilder's RSI **from the textbook definition**, via an explicit Python loop independent of
    the pandas `.ewm` call under test.

    Wilder's own seed is the *simple mean* of the first `period` gains and the first `period`
    losses -- not, as an earlier draft of this reference did, the single first observation. That
    earlier version was seeding itself the same way the buggy implementation seeded its `.ewm`
    call, so it agreed with the bug instead of catching it: both converged eventually, but a wrong
    seed and a right one produce very different RSI values for the first several dozen bars (see
    `TestRSI.test_matches_published_wilder_worked_example` for how far off -- tens of RSI points).
    """
    n = len(closes)
    out = [math.nan] * n
    if n <= period:
        return out
    changes = [closes[i] - closes[i - 1] for i in range(1, n)]
    gains = [max(c, 0.0) for c in changes]
    losses = [max(-c, 0.0) for c in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    out[period] = _rsi_from_averages(avg_gain, avg_loss)

    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i + 1] = _rsi_from_averages(avg_gain, avg_loss)
    return out


class TestRSI:
    def test_matches_hand_computed_wilder_series(self) -> None:
        closes = [44.0, 44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84]
        period = 3
        bars = _bars(close=closes)
        result = rsi(bars, period=period)["rsi_3"]
        reference = _reference_rsi(closes, period)

        for i in range(len(closes)):
            if math.isnan(reference[i]):
                assert math.isnan(result.iloc[i])
            else:
                assert result.iloc[i] == pytest.approx(reference[i])

    def test_all_gains_is_exactly_100_with_no_nan_or_inf(self) -> None:
        closes = [float(x) for x in range(1, 25)]  # strictly increasing: no losses at all
        bars = _bars(close=closes)
        result = rsi(bars, period=14)["rsi_14"]
        tail = result.iloc[14:]
        assert (tail == 100.0).all()
        assert not tail.isna().any()
        assert np.isfinite(tail.to_numpy()).all()

    def test_all_losses_is_exactly_0_with_no_nan_or_inf(self) -> None:
        closes = [float(x) for x in range(24, 0, -1)]  # strictly decreasing: no gains at all
        bars = _bars(close=closes)
        result = rsi(bars, period=14)["rsi_14"]
        tail = result.iloc[14:]
        assert (tail == 0.0).all()
        assert not tail.isna().any()
        assert np.isfinite(tail.to_numpy()).all()

    def test_a_perfectly_flat_series_is_undefined_not_overbought(self) -> None:
        """RS is 0/0 on a flat close, and 100 is a claim, not an answer.

        This resolved to 100 until 2026-08-14, by letting the no-losses branch win the tie -- so an
        instrument that had not moved read as maximally overbought and would fire any
        `rsi(14) > 70` rule. `docs/reports/phase-5.md` flagged it, said it was pinned by a test, and
        it was not: the two tests above cover strictly monotonic series, and nothing covered this.
        """
        bars = _bars(close=[100.0] * 24)
        result = rsi(bars, period=14)["rsi_14"]
        assert result.iloc[14:].isna().all()

    def test_a_flat_stretch_inside_a_moving_series_is_still_defined(self) -> None:
        """Only a window with no movement *at all* is undefined.

        Wilder's smoothing carries earlier gains and losses forward, so a few flat bars inside a
        series that has moved leave both averages non-zero and the RSI perfectly well defined.
        Without this, "flat" could quietly come to mean "recently quiet" and blank out real readings.
        """
        closes = [float(x) for x in range(1, 20)] + [19.0] * 5
        bars = _bars(close=closes)
        result = rsi(bars, period=14)["rsi_14"]
        assert result.iloc[14:].notna().all()

    def test_warmup_nan_count_is_exactly_period(self) -> None:
        bars = _bars(close=_LONG_CLOSE)
        result = rsi(bars, period=14)["rsi_14"]
        assert result.isna().sum() == 14

    def test_matches_published_wilder_worked_example(self) -> None:
        """The canonical Wilder/StockCharts RSI(14) worked example.

        Regression test for the seeding bug: `ewm(alpha=1/period, adjust=False)` (what shipped)
        seeds its recursion from the first single gain/loss observation rather than Wilder's
        simple mean of the first 14, and is wrong by about 20 RSI points at bar 14 as a result
        (50.66 shipped vs. ~70.5 correct) -- the difference between "neutral" and "approaching
        overbought". The published StockCharts table rounds Average Gain/Loss to 2 decimal places
        at every single step, so a full-precision implementation (correctly) lands a few
        hundredths of an RSI point away from their rounded numbers -- `abs=0.1` absorbs exactly
        that rounding, not the seeding bug this test exists to catch.
        """
        closes = [
            44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
            45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64,
        ]  # fmt: skip
        bars = _bars(close=closes)
        result = rsi(bars, period=14)["rsi_14"]

        published = {14: 70.53, 15: 66.32, 16: 66.55}
        for bar, expected in published.items():
            assert result.iloc[bar] == pytest.approx(expected, abs=0.1)

        # The shipped bug's seeding is unambiguously wrong here, not just "a little off": it
        # misses bar 14 by roughly 20 points (50.66 vs ~70.5), nowhere near a rounding difference.
        broken_seed_bug_value = 50.66
        assert abs(result.iloc[14] - broken_seed_bug_value) > 15

    def test_missing_close_is_remasked_to_nan_not_held_from_previous_bar(self) -> None:
        """`ewm(adjust=False)` treats a missing gain/loss as "hold state" and would otherwise
        fabricate a repeat of the previous RSI at the missing bar. `close.diff()` also makes the
        *following* bar's gain/loss NaN (both differences touch the missing close), so both bars
        must come back NaN, not just the one with the missing close -- and the held-forward value
        a "hold" would have produced (the prior bar's RSI, unchanged) must not appear there either.
        """
        closes = list(_LONG_CLOSE)
        closes[20] = math.nan
        bars = _bars(close=closes)
        result = rsi(bars, period=5)["rsi_5"]

        assert not math.isnan(result.iloc[19])  # unaffected: the gap hasn't been reached yet
        # A bug that just lets `ewm` hold its state forward would have fabricated bar 20 as an
        # exact repeat of bar 19 instead of NaN -- this is exactly that value, ruled out.
        assert math.isnan(result.iloc[20])
        assert math.isnan(result.iloc[21])  # diff() also NaNs the *next* bar's gain/loss
        assert not math.isnan(result.iloc[25])  # bars well clear of the gap settle normally


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------


class TestBollinger:
    def test_mid_is_the_sma(self) -> None:
        bars = _bars(close=_LONG_CLOSE)
        bb = bollinger(bars, period=20, stddev=2.0)
        plain_sma = bars["close"].rolling(20, min_periods=20).mean()
        assert np.allclose(
            bb["bb_20_2_mid"].dropna().to_numpy(), plain_sma.dropna().to_numpy()
        )

    def test_uses_population_stddev_ddof0(self) -> None:
        closes = [10, 11, 12, 13, 12, 11, 10, 9]
        window = closes[-5:]
        mean = sum(window) / len(window)
        population_std = math.sqrt(sum((x - mean) ** 2 for x in window) / len(window))

        bars = _bars(close=closes)
        bb = bollinger(bars, period=5, stddev=2.0)
        last = bb.iloc[-1]
        assert last["bb_5_2_upper"] == pytest.approx(mean + 2.0 * population_std)
        assert last["bb_5_2_lower"] == pytest.approx(mean - 2.0 * population_std)

    def test_differs_from_ddof1_sample_stddev(self) -> None:
        bars = _bars(close=_LONG_CLOSE)
        correct = bollinger(bars, period=20, stddev=2.0)["bb_20_2_upper"].dropna()
        sample_std = bars["close"].rolling(20, min_periods=20).std(ddof=1)  # the wrong default
        mid = bars["close"].rolling(20, min_periods=20).mean()
        wrong = (mid + 2.0 * sample_std).dropna()
        assert not np.allclose(correct.to_numpy(), wrong.to_numpy())


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------


def _reference_atr(
    high: Sequence[float], low: Sequence[float], close: Sequence[float], period: int
) -> list[float]:
    """Wilder-smoothed true range **from the textbook definition**, via an explicit loop
    independent of the `.ewm` call under test.

    Wilder's own seed is the *simple mean* of the first `period` true range values -- not, as an
    earlier draft of this reference did, `tr[0]` alone (the same single-observation seeding flaw
    the implementation itself had). The first settled value therefore lands at index
    `period - 1`, not index 0.
    """
    n = len(high)
    tr = [0.0] * n
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
    out = [math.nan] * n
    if n < period:
        return out
    avg = sum(tr[:period]) / period
    out[period - 1] = avg
    for i in range(period, n):
        avg = (avg * (period - 1) + tr[i]) / period
        out[i] = avg
    return out


class TestATR:
    def test_first_true_range_is_high_minus_low_then_wilder_smoothed(self) -> None:
        high = [10.0, 11.0, 12.0, 11.0, 10.0, 11.0, 12.0]
        low = [9.0, 10.0, 11.0, 10.0, 9.0, 10.0, 11.0]
        close = [9.5, 10.5, 11.5, 10.5, 9.5, 10.5, 11.5]
        period = 3
        bars = _bars(close=close, high=high, low=low)
        result = atr(bars, period=period)["atr_3"]
        reference = _reference_atr(high, low, close, period)

        for i in range(len(high)):
            if math.isnan(reference[i]):
                assert math.isnan(result.iloc[i])
            else:
                assert result.iloc[i] == pytest.approx(reference[i])

    def test_differs_from_plain_rolling_mean_of_true_range(self) -> None:
        high = [x + 0.5 for x in _LONG_CLOSE]
        low = [x - 0.5 for x in _LONG_CLOSE]
        bars = _bars(close=_LONG_CLOSE, high=high, low=low)
        period = 14
        correct = atr(bars, period=period)["atr_14"].dropna()

        prev_close = bars["close"].shift(1)
        tr = pd.concat(
            [bars["high"] - bars["low"], (bars["high"] - prev_close).abs(), (bars["low"] - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        simple_mean = tr.rolling(period, min_periods=period).mean().dropna()

        assert not np.allclose(correct.to_numpy(), simple_mean.to_numpy())

    def test_missing_high_does_not_fabricate_a_near_zero_true_range(self) -> None:
        """`DataFrame.max(axis=1)`'s default `skipna=True` silently drops a NaN `high` leg and
        maxes over whatever legs are left. With `high=NaN, low=101.0, prev_close=101.0` that
        leaves only `|low - prev_close| == 0.0` as a candidate, so the old code reported a true
        range of exactly 0.0 for a bar whose real (unobserved) range could have been enormous --
        with no NaN anywhere in the output to flag that anything was wrong. The fix must instead
        propagate the missing leg as NaN for that bar.
        """
        high = [10.0, 10.5, 11.0, 11.0, math.nan, 11.0, 11.0, 11.0]
        low = [9.0, 9.5, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0]
        close = [9.5, 10.0, 10.5, 10.0, 10.0, 10.0, 10.0, 10.0]
        bars = _bars(close=close, high=high, low=low)
        result = atr(bars, period=3)["atr_3"]

        assert math.isnan(result.iloc[4])
        # And specifically not the fabricated near-zero the skipna=True bug produced.
        assert result.iloc[4] != pytest.approx(0.0)

    def test_missing_high_low_close_is_remasked_to_nan_not_held_from_previous_bar(self) -> None:
        """Beyond defect 2's fabricated-value bug, a genuinely-NaN true range must not let
        `wilder_smooth`'s `ewm` hold the previous ATR forward across the gap either -- same
        re-masking requirement as `rsi` and `ema` (see their tests)."""
        high = [x + 0.5 for x in _LONG_CLOSE]
        low = [x - 0.5 for x in _LONG_CLOSE]
        high = list(high)
        high[20] = math.nan
        bars = _bars(close=_LONG_CLOSE, high=high, low=low)
        result = atr(bars, period=5)["atr_5"]

        assert not math.isnan(result.iloc[19])  # unaffected: gap not reached yet
        assert math.isnan(result.iloc[20])  # the bar with the missing high
        assert not math.isnan(result.iloc[25])  # settles back to normal well clear of the gap


# ---------------------------------------------------------------------------
# Anchored VWAP
# ---------------------------------------------------------------------------


class TestAnchoredVWAP:
    def _two_session_bars(self) -> pd.DataFrame:
        """Two 5-minute sessions of three bars each, one day apart, in UTC."""
        return _bars(
            close=[9.8, 10.2, 10.8, 19.8, 20.2, 20.8],
            high=[10.0, 10.5, 11.0, 20.0, 20.5, 21.0],
            low=[9.5, 10.0, 10.5, 19.5, 20.0, 20.5],
            volume=[100, 0, 200, 50, 50, 0],
            start=dt.datetime(2026, 6, 1, 13, 30, tzinfo=dt.UTC),
            step=dt.timedelta(minutes=5),
        )

    def test_session_anchor_restarts_at_each_session_boundary(self) -> None:
        bars = self._two_session_bars()
        # Advance the second half of the fixture to the next calendar day so it is a new session.
        bars.loc[3:, "ts"] = pd.to_datetime(
            [
                dt.datetime(2026, 6, 2, 13, 30, tzinfo=dt.UTC),
                dt.datetime(2026, 6, 2, 13, 35, tzinfo=dt.UTC),
                dt.datetime(2026, 6, 2, 13, 40, tzinfo=dt.UTC),
            ]
        )
        result = anchored_vwap(bars, anchor="session")["vwap_session"]

        typical = (bars["high"] + bars["low"] + bars["close"]) / 3.0
        # Session 1: bar0 vol=100 seeds it; bar1 vol=0 contributes no weight, so vwap is unchanged;
        # bar2 vol=200 folds in.
        assert result.iloc[0] == pytest.approx(typical.iloc[0])
        assert result.iloc[1] == pytest.approx(typical.iloc[0])
        expected_bar2 = (typical.iloc[0] * 100 + typical.iloc[2] * 200) / 300
        assert result.iloc[2] == pytest.approx(expected_bar2)
        # Session 2 restarts from bar3's own typical price, independent of session 1's accumulation.
        assert result.iloc[3] == pytest.approx(typical.iloc[3])

    def test_date_anchor_starts_where_told(self) -> None:
        bars = self._two_session_bars()
        bars.loc[3:, "ts"] = pd.to_datetime(
            [
                dt.datetime(2026, 6, 2, 13, 30, tzinfo=dt.UTC),
                dt.datetime(2026, 6, 2, 13, 35, tzinfo=dt.UTC),
                dt.datetime(2026, 6, 2, 13, 40, tzinfo=dt.UTC),
            ]
        )
        result = anchored_vwap(bars, anchor=dt.date(2026, 6, 2))["vwap_2026-06-02"]

        assert result.iloc[0:3].isna().all()
        typical = (bars["high"] + bars["low"] + bars["close"]) / 3.0
        assert result.iloc[3] == pytest.approx(typical.iloc[3])

    def test_zero_volume_bars_do_not_divide_by_zero(self) -> None:
        bars = _bars(
            close=[10.0, 11.0],
            high=[10.5, 11.5],
            low=[9.5, 10.5],
            volume=[0.0, 5.0],
        )
        result = anchored_vwap(bars, anchor="session")["vwap_session"]
        assert math.isnan(result.iloc[0])  # zero cumulative volume: undefined, not inf/error
        typical1 = (bars["high"].iloc[1] + bars["low"].iloc[1] + bars["close"].iloc[1]) / 3.0
        assert result.iloc[1] == pytest.approx(typical1)  # first bar contributed zero weight

    def test_missing_volume_does_not_divide_by_zero(self) -> None:
        bars = _bars(close=[10.0, 11.0], volume=[None, 5.0])
        result = anchored_vwap(bars, anchor="session")["vwap_session"]
        assert math.isnan(result.iloc[0])
        assert np.isfinite(result.iloc[1])

    def test_requesting_it_on_1d_raises_through_parse_spec(self) -> None:
        with pytest.raises(IndicatorError):
            request("vwap", interval=Interval.DAY)

    def test_allowed_on_5m_and_1h(self) -> None:
        request("vwap", interval=Interval.FIVE_MIN)
        request("vwap", interval=Interval.HOUR)


# ---------------------------------------------------------------------------
# parse_spec: blank positional fields must not shift later arguments
# ---------------------------------------------------------------------------


class TestParseSpecBlankFields:
    def test_leading_blank_field_raises_instead_of_shifting(self) -> None:
        """`"macd:,26,9"` used to silently become `fast=26, slow=9, signal=9` -- every argument
        after the gap shifted one slot left, passing range validation and producing a nonsensical
        MACD labelled with the user's own parameters instead of raising."""
        with pytest.raises(IndicatorError):
            request("macd:,26,9")

    def test_interior_blank_field_raises_instead_of_shifting(self) -> None:
        """`"macd:12,,9"` used to silently become `fast=12, slow=9, signal=9`."""
        with pytest.raises(IndicatorError):
            request("macd:12,,9")

    def test_single_trailing_blank_field_is_tolerated(self) -> None:
        """A harmless trailing comma (`"macd:12,26,9,"`) is not the same ambiguity -- nothing
        after it could have shifted -- so it is dropped rather than rejected."""
        parsed = request("macd:12,26,9,")
        assert dict(parsed.params) == {"fast": 12, "slow": 26, "signal": 9}

    def test_two_trailing_blank_fields_raises(self) -> None:
        """Only a *single* trailing empty field is tolerated; a second one is still a gap."""
        with pytest.raises(IndicatorError):
            request("macd:12,26,9,,")

    def test_no_colon_still_means_defaults(self) -> None:
        """`"sma"` alone (no `:` at all) is the ordinary all-defaults case, not an empty-argument
        error -- must keep working exactly as before."""
        parsed = request("sma")
        assert dict(parsed.params) == {"period": 20}


# ---------------------------------------------------------------------------
# Registry-wide sweeps: every indicator must obey the same contract.
# ---------------------------------------------------------------------------

_CATALOG = catalog()
_CATALOG_IDS = [spec.name for spec in _CATALOG]


class TestRegistryWideContract:
    """The alignment and warmup guarantees, asserted across the whole registry at once.

    A future indicator added without a correct `warmup` or without preserving the input index fails
    here automatically, because these tests parametrise over `catalog()` rather than naming
    indicators individually.
    """

    @pytest.mark.parametrize("spec", _CATALOG, ids=_CATALOG_IDS)
    def test_warmup_matches_actual_leading_nan_count(self, spec: IndicatorSpec) -> None:
        bars = _bars(close=_LONG_CLOSE)
        params = _default_params(spec)
        result = spec.fn(bars, **params)
        # For a multi-column indicator, `warmup` is when *every* leg has settled -- the worst case
        # across outputs, not any single column's own warmup (MACD's own `macd` leg settles sooner
        # than its `signal`/`hist` legs; see TestMACD).
        nan_counts = [int(result[col].isna().sum()) for col in spec.columns(params)]
        if spec.data_dependent_warmup:
            # A pivot indicator cannot settle on a parameter-only schedule: it publishes nothing
            # until price actually turns, and on a monotone stretch that may be far past the
            # arithmetic minimum. `warmup` is a lower bound for these, and the bound must still
            # hold -- a value appearing *earlier* than the declared warmup would mean the pivot was
            # published before it could have been known, which is the lookahead this whole family
            # is built to avoid. See `IndicatorSpec.data_dependent_warmup`.
            assert max(nan_counts) >= spec.warmup(params)
        else:
            assert max(nan_counts) == spec.warmup(params)

    def test_only_the_swing_family_declares_a_data_dependent_warmup(self) -> None:
        """The exact-equality branch above is the contract that catches a miscounted warmup, so the
        escape hatch stays pinned to the specs that genuinely need it rather than spreading."""
        relaxed = {spec.name for spec in _CATALOG if spec.data_dependent_warmup}
        assert relaxed == {"swing", "rsi_at_swing", "macd_at_swing"}

    @pytest.mark.parametrize("spec", _CATALOG, ids=_CATALOG_IDS)
    def test_output_index_equals_input_index(self, spec: IndicatorSpec) -> None:
        bars = _bars(close=_LONG_CLOSE)
        result = spec.fn(bars, **_default_params(spec))
        assert result.index.equals(bars.index)

    @pytest.mark.parametrize("spec", _CATALOG, ids=_CATALOG_IDS)
    def test_default_spec_round_trips_through_parse_spec(self, spec: IndicatorSpec) -> None:
        text = default_spec(spec)
        parsed = request(text)
        assert parsed.spec is spec
        assert dict(parsed.params) == _default_params(spec)

    @pytest.mark.parametrize("spec", _CATALOG, ids=_CATALOG_IDS)
    def test_empty_bars_returns_empty_frame_with_expected_columns(
        self, spec: IndicatorSpec
    ) -> None:
        bars = _empty_bars()
        params = _default_params(spec)
        result = spec.fn(bars, **params)
        assert result.empty
        assert list(result.columns) == list(spec.columns(params))

    @pytest.mark.parametrize("spec", _CATALOG, ids=_CATALOG_IDS)
    def test_columns_read_close_not_adj_close(self, spec: IndicatorSpec) -> None:
        """Two frames differing only in `adj_close` must produce identical indicator output."""
        bars = _bars(close=_LONG_CLOSE)
        bars_shifted_adj = bars.copy()
        bars_shifted_adj["adj_close"] = bars_shifted_adj["adj_close"] + 1000.0
        params = _default_params(spec)
        a = spec.fn(bars, **params)
        b = spec.fn(bars_shifted_adj, **params)
        for col in spec.columns(params):
            left, right = a[col].to_numpy(), b[col].to_numpy()
            assert np.array_equal(left, right, equal_nan=True)


class TestCatalogAndGet:
    def test_get_returns_none_for_unknown_name(self) -> None:
        assert get("not_a_real_indicator") is None

    def test_get_is_case_and_whitespace_insensitive(self) -> None:
        assert get(" SMA ") is get("sma")

    def test_catalog_has_one_entry_per_registered_indicator(self) -> None:
        names = [spec.name for spec in catalog()]
        assert names == list(dict.fromkeys(names))  # no duplicates
        assert set(names) == {
            "sma",
            "ema",
            "macd",
            "rsi",
            "bb",
            "atr",
            "vwap",
            "swing",
            "rsi_at_swing",
            "macd_at_swing",
        }


# ---------------------------------------------------------------------------
# compute() and empty bars
# ---------------------------------------------------------------------------


class TestCompute:
    def test_carries_every_requested_column_indexed_like_bars(self) -> None:
        bars = _bars(close=_LONG_CLOSE)
        requests = [request("sma:5"), request("rsi:14")]
        result = compute(bars, requests)
        assert set(result.columns) == {"sma_5", "rsi_14"}
        assert result.index.equals(bars.index)

    def test_does_not_mutate_its_input(self) -> None:
        bars = _bars(close=_LONG_CLOSE)
        before = bars.copy(deep=True)
        compute(bars, [request("sma:5"), request("bb:20,2")])
        pd.testing.assert_frame_equal(bars, before)

    def test_empty_bars_yields_empty_frame_with_expected_columns(self) -> None:
        bars = _empty_bars()
        requests = [request("sma:20"), request("bb:20,2")]
        result = compute(bars, requests)
        assert result.empty
        assert set(result.columns) == {"sma_20", "bb_20_2_upper", "bb_20_2_mid", "bb_20_2_lower"}

    def test_empty_bars_with_no_requests_yields_empty_frame(self) -> None:
        result = compute(_empty_bars(), [])
        assert result.empty

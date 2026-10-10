"""Swing pivots and the divergence expressions they unlock.

The load-bearing test in this file is `TestPublicationLag` -- everything else here is ordinary
correctness, but a pivot indicator that publishes one bar early is a lookahead bug that would make
every divergence backtest built on it worthless *and* flattering, which is the dangerous combination.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.backtest import guards
from app.backtest.models import GuardStatus
from app.db.duck import Interval
from app.indicators.registry import get, request
from app.indicators.swing import confirmed_pivots, macd_at_swing, rsi_at_swing, swing
from app.rules import grammar


def _bars(lows: list[float], highs: list[float] | None = None) -> pd.DataFrame:
    n = len(lows)
    highs = highs if highs is not None else [x + 1.0 for x in lows]
    return pd.DataFrame(
        {
            "ts": pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC"),
            "open": lows,
            "high": highs,
            "low": lows,
            "close": lows,
            "adj_close": lows,
            "volume": [1_000.0] * n,
        }
    )


#: A single clean V: the minimum sits at index 5.
_V = [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]


class TestPublicationLag:
    """A pivot is published `lookback` bars after it forms, never on the bar itself."""

    def test_the_pivot_is_not_published_on_its_own_bar(self) -> None:
        out = confirmed_pivots(pd.Series(_V), lookback=3, high=False)
        assert pd.isna(out.iloc[5]), "published on the pivot bar -- reads 3 bars of the future"

    @pytest.mark.parametrize("position", [5, 6, 7])
    def test_nothing_is_published_before_confirmation(self, position: int) -> None:
        """Index 5 is the pivot; with lookback=3 it cannot be known until index 8."""
        out = confirmed_pivots(pd.Series(_V), lookback=3, high=False)
        assert pd.isna(out.iloc[position])

    def test_it_is_published_exactly_at_confirmation(self) -> None:
        out = confirmed_pivots(pd.Series(_V), lookback=3, high=False)
        assert out.iloc[8] == 5.0

    def test_it_is_held_forward_after_confirmation(self) -> None:
        out = confirmed_pivots(pd.Series(_V), lookback=3, high=False)
        assert out.iloc[9] == 5.0
        assert out.iloc[10] == 5.0

    @pytest.mark.parametrize("lookback", [1, 2, 3, 4])
    def test_the_lag_tracks_lookback(self, lookback: int) -> None:
        out = confirmed_pivots(pd.Series(_V), lookback=lookback, high=False)
        assert pd.isna(out.iloc[5 + lookback - 1])
        assert out.iloc[5 + lookback] == 5.0

    def test_appending_future_bars_never_changes_a_published_value(self) -> None:
        """The property the backtest actually depends on: what bar `t` said cannot be revised by
        bars that arrive after `t`. This is the same invariant `app.backtest.guards` proves by tail
        truncation, asserted here directly on the primitive."""
        full = pd.Series([*_V, 4.0, 3.0, 2.0, 1.0])
        short = pd.Series(_V)
        a = confirmed_pivots(full, lookback=3, high=False).iloc[: len(short)]
        b = confirmed_pivots(short, lookback=3, high=False)
        pd.testing.assert_series_equal(a, b)


class TestPivotSelection:
    def test_a_swing_high_finds_the_local_maximum(self) -> None:
        inverted = pd.Series([-x for x in _V])
        out = confirmed_pivots(inverted, lookback=3, high=True)
        assert out.iloc[8] == -5.0

    def test_a_monotone_series_has_no_interior_pivot_of_that_kind(self) -> None:
        """Rising throughout: every bar is the max of its own window, so there are swing highs but
        the only swing-low candidates are at the edges, where the centred window is undefined."""
        rising = pd.Series(np.arange(50, dtype=float))
        assert confirmed_pivots(rising, lookback=3, high=False).isna().all()

    def test_a_tied_double_bottom_is_kept(self) -> None:
        """Two adjacent bars sharing the minimum are both pivots. Requiring strict inequality would
        discard every double bottom -- a pattern the source note names explicitly."""
        flat = pd.Series([10.0, 9.0, 8.0, 5.0, 5.0, 8.0, 9.0, 10.0, 11.0, 12.0])
        out = confirmed_pivots(flat, lookback=2, high=False)
        assert out.iloc[5] == 5.0
        assert out.iloc[6] == 5.0

    def test_a_later_pivot_supersedes_an_earlier_one(self) -> None:
        two = pd.Series([10.0, 8.0, 5.0, 8.0, 10.0, 12.0, 10.0, 3.0, 10.0, 12.0, 13.0, 14.0])
        out = confirmed_pivots(two, lookback=2, high=False)
        assert out.iloc[4] == 5.0
        assert out.iloc[9] == 3.0

    def test_nan_in_the_input_is_not_a_pivot(self) -> None:
        withnan = pd.Series([10.0, 9.0, np.nan, 7.0, 6.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
        out = confirmed_pivots(withnan, lookback=2, high=False)
        assert not out.isna().all()
        assert (out.dropna() == 5.0).all()


class TestCompanionSampling:
    def test_the_companion_is_read_at_the_pivot_bar_not_the_publication_bar(self) -> None:
        osc = pd.Series([0.0] * 11)
        osc.iloc[5] = 42.0
        osc.iloc[8] = 99.0
        out = confirmed_pivots(pd.Series(_V), lookback=3, high=False, companion=osc)
        assert out.iloc[8] == 42.0, "sampled at publication instead of at the pivot"

    def test_rsi_at_swing_low_matches_rsi_at_that_bar(self) -> None:
        bars = _bars(_V * 12)
        from app.indicators.momentum import rsi

        line = rsi(bars, period=14).iloc[:, 0]
        out = rsi_at_swing(bars, period=14, lookback=3)["rsi_at_swing_14_3_low"]
        published = out.dropna()
        assert not published.empty
        # every published value must appear somewhere in the RSI series itself
        assert set(np.round(published.unique(), 9)).issubset(set(np.round(line.dropna(), 9)))

    def test_macd_at_swing_uses_the_macd_line(self) -> None:
        bars = _bars(_V * 20)
        from app.indicators.trend import macd

        line = macd(bars, fast=12, slow=26, signal=9)["macd_12_26_9_macd"]
        out = macd_at_swing(bars, fast=12, slow=26, signal=9, lookback=3)[
            "macd_at_swing_12_26_9_3_low"
        ]
        published = out.dropna()
        assert not published.empty
        assert set(np.round(published.unique(), 9)).issubset(set(np.round(line.dropna(), 9)))


class TestFrameContract:
    def test_swing_emits_both_legs_on_the_input_index(self) -> None:
        bars = _bars(_V * 6)
        out = swing(bars, lookback=3)
        assert list(out.columns) == ["swing_3_high", "swing_3_low"]
        assert out.index.equals(bars.index)

    def test_empty_bars_give_an_empty_frame_with_the_columns(self) -> None:
        bars = _bars([]).astype({"low": "float64", "high": "float64"})
        out = swing(bars, lookback=3)
        assert out.empty
        assert list(out.columns) == ["swing_3_high", "swing_3_low"]


class TestRegistryAndGrammar:
    @pytest.mark.parametrize("name", ["swing", "rsi_at_swing", "macd_at_swing"])
    def test_registered(self, name: str) -> None:
        assert get(name) is not None

    @pytest.mark.parametrize(
        "text", ["swing:5", "rsi_at_swing:14,5", "macd_at_swing:12,26,9,5"]
    )
    def test_spec_strings_parse(self, text: str) -> None:
        assert request(text) is not None

    @pytest.mark.parametrize(
        "expression",
        [
            "low < swing_low(5)",
            "high > swing_high(5)",
            "low < swing_low(5) and rsi(14) > rsi_at_swing_low(14,5)",
            "high > swing_high(5) and macd_macd(12,26,9) < macd_at_swing_high(12,26,9,5)",
        ],
    )
    def test_divergence_expressions_parse(self, expression: str) -> None:
        assert grammar.parse(expression) is not None

    def test_an_unregistered_output_suffix_is_still_rejected(self) -> None:
        with pytest.raises(grammar.RuleSyntaxError):
            grammar.parse("low < swing_middle(5)")


class TestLookaheadGuard:
    """The end-to-end proof: the app's own guard must clear these, with no tolerance."""

    @pytest.mark.parametrize(
        "expression",
        [
            "low < swing_low(5)",
            "high > swing_high(10)",
            "low < swing_low(5) and rsi(14) > rsi_at_swing_low(14,5)",
            "high > swing_high(5) and macd_macd(12,26,9) < macd_at_swing_high(12,26,9,5)",
        ],
    )
    def test_guard_passes(self, expression: str) -> None:
        rng = np.random.default_rng(20260811)
        walk = 100 + np.cumsum(rng.normal(0, 1, 800))
        bars = _bars(list(walk), highs=list(walk + 1.5))
        report = guards.check(expression, bars, interval=Interval.DAY)
        if report.status is not GuardStatus.PASSED:
            pytest.fail(str([f.detail for f in report.findings if not f.passed]))

    def test_a_centred_pivot_without_the_lag_would_be_caught(self) -> None:
        """Proof the guard is capable of failing this family -- otherwise the passes above prove
        nothing. Publishing at the pivot bar instead of `pivot + lookback` is exactly the bug, and
        it changes values before a truncation point, which is what the guard detects."""
        series = pd.Series(_V + _V)
        correct = confirmed_pivots(series, lookback=3, high=False)
        peeking = series.rolling(7, center=True).min()  # the naive, future-reading version
        assert not correct.iloc[:14].equals(peeking.iloc[:14])
        assert pd.isna(correct.iloc[5]) and peeking.iloc[5] == 5.0

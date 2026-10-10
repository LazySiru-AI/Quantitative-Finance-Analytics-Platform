"""The strategy backtester.

Every price in here is chosen so the expected trade, fill and metric can be written out as an
arithmetic expression and checked by hand -- not derived by running :func:`app.backtest.strategy`
and trusting the answer. A fake evaluator (mirroring ``tests/test_events.py``) pins the exact signal
sequence so a test is never reverse-engineered from an indicator's behaviour.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from app.backtest import strategy
from app.backtest.models import BARS_PER_YEAR, Costs, ExitReason, StrategySpec
from app.db.duck import Interval


def _frame(close: np.ndarray, *, open_: np.ndarray | None = None) -> pd.DataFrame:
    n = len(close)
    o = close if open_ is None else open_
    return pd.DataFrame(
        {
            "ts": pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC"),
            "open": o,
            "high": np.maximum(close, o) + 0.5,
            "low": np.minimum(close, o) - 0.5,
            "close": close,
            "adj_close": close,
            "volume": np.full(n, 1e6),
        }
    )


class _FixedGrammar:
    """Parses nothing; the evaluator below ignores the tree entirely."""

    def parse(self, expression: str) -> object:
        return expression


class _SignalEvaluator:
    """Returns a caller-supplied signal, so a test can pin the trigger pattern exactly rather than
    reverse-engineering one out of an indicator."""

    def __init__(self, signals: dict[str, pd.Series]) -> None:
        self._signals = signals

    def evaluate(self, node: object, bars: pd.DataFrame, *, interval: Interval) -> pd.Series:
        return self._signals[str(node)]


def _backtest(  # type: ignore[no-untyped-def]
    bars: pd.DataFrame,
    spec: StrategySpec,
    signals: dict[str, pd.Series],
    *,
    costs: Costs = Costs(),  # noqa: B008 -- `Costs` is a frozen pydantic model
    risk_free_rate: float = 0.0,
):
    return strategy.backtest(
        bars,
        spec,
        interval=Interval.DAY,
        costs=costs,
        risk_free_rate=risk_free_rate,
        grammar=_FixedGrammar(),
        evaluator=_SignalEvaluator(signals),
    )


SLIP = 5.0 / 10_000  # Costs() default: 5bp, applied both ways


class TestOneTradeHandComputed:
    """The bar-by-bar mechanics, pinned to a single trade whose every number is computed here by
    hand rather than by running the backtester."""

    def test_a_single_round_trip_matches_hand_computed_prices_and_return(self) -> None:
        n = 12
        close = np.array(
            [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111], dtype=float
        )
        open_ = close.copy()
        open_[3] = 100.0  # entry fill: bar 3's open, after the entry signal on bar 2's close
        open_[7] = 110.0  # exit fill: bar 7's open, after the exit signal on bar 6's close
        bars = _frame(close, open_=open_)

        entry = pd.Series([i == 2 for i in range(n)], dtype="boolean")
        exit_ = pd.Series([i == 6 for i in range(n)], dtype="boolean")
        spec = StrategySpec(entry="entry", exit="exit")

        _, _, trades, _, _, open_trades = _backtest(bars, spec, {"entry": entry, "exit": exit_})

        assert open_trades == 0
        assert len(trades) == 1
        trade = trades[0]

        dates = bars["ts"].dt.date
        assert trade.entry_date == dates.iloc[3]
        assert trade.exit_date == dates.iloc[7]
        assert trade.bars_held == 4
        assert trade.exit_reason == ExitReason.SIGNAL
        assert trade.open_at_end is False

        expected_entry = 100.0 * (1 + SLIP)
        expected_exit = 110.0 * (1 - SLIP)
        assert trade.entry_price == pytest.approx(expected_entry)
        assert trade.exit_price == pytest.approx(expected_exit)

        expected_return = expected_exit / expected_entry - 1.0
        assert trade.return_pct == pytest.approx(expected_return)


class TestCostDrag:
    """Slippage changes the fill price, never the signal, so the same two round trips happen at
    zero cost and at 5bp -- only their prices differ."""

    def test_five_bp_slippage_matches_the_hand_computed_drag_over_two_round_trips(self) -> None:
        n = 16
        close = np.full(n, 100.0)
        open_ = close.copy()
        open_[2] = 100.0  # trade 1 entry fill
        open_[6] = 110.0  # trade 1 exit fill: +10%
        open_[11] = 100.0  # trade 2 entry fill
        open_[15] = 105.0  # trade 2 exit fill: +5%
        bars = _frame(close, open_=open_)

        entry = pd.Series([i in (1, 10) for i in range(n)], dtype="boolean")
        exit_ = pd.Series([i in (5, 14) for i in range(n)], dtype="boolean")
        spec = StrategySpec(entry="entry", exit="exit")
        signals = {"entry": entry, "exit": exit_}

        zero_metrics, _, zero_trades, _, zero_drag, _ = _backtest(
            bars, spec, signals, costs=Costs(slippage_bps=0.0)
        )
        costed_metrics, _, costed_trades, _, costed_drag, _ = _backtest(
            bars, spec, signals, costs=Costs(slippage_bps=5.0)
        )

        assert len(zero_trades) == 2
        assert len(costed_trades) == 2
        assert zero_drag == 0.0

        zero_multiplier = (110.0 / 100.0) * (105.0 / 100.0)
        factor = (1 - SLIP) / (1 + SLIP)  # each round trip picks up this factor under 5bp slippage
        costed_multiplier = zero_multiplier * factor**2
        expected_drag = (costed_multiplier - 1.0) - (zero_multiplier - 1.0)

        assert zero_metrics.total_return == pytest.approx(zero_multiplier - 1.0)
        assert costed_metrics.total_return == pytest.approx(costed_multiplier - 1.0)
        assert costed_drag < 0.0
        assert costed_drag == pytest.approx(expected_drag)


class TestStopLoss:
    """The stop is priced at the stop level on an intrabar breach, and at the open on a gap through
    it -- never at the bar's close, which would understate the loss on exactly the days it matters."""

    def test_an_intrabar_breach_fills_at_the_stop_level_not_the_close(self) -> None:
        n = 4
        open_ = np.array([99.0, 100.0, 100.2, 98.0])
        close = np.array([99.0, 100.5, 100.0, 99.0])
        low = np.array([98.5, 99.5, 98.0, 90.0])  # bar 3 dips to 90, well through the 95 stop
        high = np.maximum(open_, close) + 0.5
        bars = pd.DataFrame(
            {
                "ts": pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC"),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "adj_close": close,
                "volume": np.full(n, 1e6),
            }
        )

        entry = pd.Series([i == 0 for i in range(n)], dtype="boolean")
        spec = StrategySpec(entry="entry", max_holding_bars=50, stop_loss_pct=0.05)

        _, _, trades, _, _, _ = _backtest(
            bars, spec, {"entry": entry}, costs=Costs(slippage_bps=0.0)
        )

        assert len(trades) == 1
        trade = trades[0]
        assert trade.exit_reason == ExitReason.STOP
        assert trade.bars_held == 2
        # entry fills at bar 1's open (100.0); stop = 100 * (1 - 0.05) = 95.0
        assert trade.exit_price == pytest.approx(95.0)
        assert trade.return_pct == pytest.approx(-0.05)
        # the close (99.0) would have shown only a 1% loss -- the stop is the real number
        assert trade.return_pct != pytest.approx(99.0 / 100.0 - 1.0)

    def test_a_gap_through_the_stop_fills_at_the_open_worse_than_the_stop_level(self) -> None:
        n = 4
        open_ = np.array([99.0, 100.0, 100.2, 90.0])  # bar 3 gaps open below the 95 stop
        close = np.array([99.0, 100.5, 100.0, 92.0])
        low = np.array([98.5, 99.5, 98.0, 85.0])
        high = np.maximum(open_, close) + 0.5
        bars = pd.DataFrame(
            {
                "ts": pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC"),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "adj_close": close,
                "volume": np.full(n, 1e6),
            }
        )

        entry = pd.Series([i == 0 for i in range(n)], dtype="boolean")
        spec = StrategySpec(entry="entry", max_holding_bars=50, stop_loss_pct=0.05)

        _, _, trades, _, _, _ = _backtest(
            bars, spec, {"entry": entry}, costs=Costs(slippage_bps=0.0)
        )

        assert len(trades) == 1
        trade = trades[0]
        assert trade.exit_reason == ExitReason.STOP
        stop_level = 100.0 * (1 - 0.05)
        assert trade.exit_price == pytest.approx(90.0)
        assert trade.exit_price < stop_level
        assert trade.return_pct == pytest.approx(90.0 / 100.0 - 1.0)


class TestExitLookahead:
    """Same construction as ``tests/test_events.py``'s lookahead test: a spike confined to the
    signal bar must not be captured by the fill."""

    def test_a_spike_confined_to_the_signal_bar_is_worth_nothing_at_next_open(self) -> None:
        n = 7
        close = np.full(n, 100.0)
        open_ = np.full(n, 100.0)
        close[5] = 110.0  # spike confined to the exit-signal bar's own close
        bars = _frame(close, open_=open_)

        entry = pd.Series([i == 0 for i in range(n)], dtype="boolean")
        exit_ = pd.Series([i == 5 for i in range(n)], dtype="boolean")
        spec = StrategySpec(entry="entry", exit="exit")

        _, _, trades, _, _, _ = _backtest(
            bars, spec, {"entry": entry, "exit": exit_}, costs=Costs(slippage_bps=0.0)
        )

        assert len(trades) == 1
        trade = trades[0]
        # exit fills at bar 6's open (100.0), not bar 5's spiked close (110.0)
        assert trade.exit_price == pytest.approx(100.0)
        assert trade.return_pct == pytest.approx(0.0)


class TestBuyHoldIdenticalWindow:
    """An always-in-the-market strategy enters at bar 1's open the same way buy-and-hold does here
    -- see the module docstring in ``app/backtest/strategy.py`` -- so the two must match exactly
    apart from the strategy's own entry friction."""

    def test_an_always_in_market_strategy_matches_buy_and_hold_minus_entry_slippage(self) -> None:
        n = 50
        close = 100.0 * 1.001**np.arange(n)
        bars = _frame(close)

        entry = pd.Series([i == 0 for i in range(n)], dtype="boolean")
        never = pd.Series([False] * n, dtype="boolean")
        spec = StrategySpec(entry="entry", exit="never")

        strat, buy_hold, trades, curve, _, open_trades = _backtest(
            bars, spec, {"entry": entry, "never": never}
        )

        assert open_trades == 1
        assert len(trades) == 1
        assert trades[0].exit_reason == ExitReason.END_OF_DATA
        assert len(curve) == n
        assert curve[0].equity == pytest.approx(1.0)
        assert curve[0].buy_hold == pytest.approx(1.0)

        opens = bars["open"].to_numpy()
        entry_price = opens[1] * (1 + SLIP)  # the strategy's only friction: one entry fill
        expected_strategy_return = close[-1] / entry_price - 1.0
        expected_buy_hold_return = close[-1] / opens[1] - 1.0

        assert strat.total_return == pytest.approx(expected_strategy_return)
        assert buy_hold.total_return == pytest.approx(expected_buy_hold_return)
        gap = buy_hold.total_return - strat.total_return
        assert 0.0 < gap < 0.001  # essentially equal: the whole gap is one entry fill's slippage
        assert strat.exposure == pytest.approx(buy_hold.exposure)


class TestExposure:
    """A strategy that is rarely in the market cannot be judged by its raw return alone --
    :attr:`~app.backtest.models.StrategyMetrics.exposure` must say how little risk it carried."""

    def test_a_strategy_in_the_market_five_percent_of_the_time_reports_that_exposure(self) -> None:
        n = 100
        close = 100.0 + np.arange(n) * 0.1
        bars = _frame(close)

        entry = pd.Series([i == 0 for i in range(n)], dtype="boolean")
        # entry at bar 0 -> fills bar 1's open; max_holding_bars=4 -> exits at bar 5's close.
        # in_position for bars 1..5 inclusive: 5 of 100 bars.
        spec = StrategySpec(entry="entry", max_holding_bars=4)

        strat, buy_hold, _, _, _, _ = _backtest(bars, spec, {"entry": entry})

        assert strat.exposure == pytest.approx(0.05)
        assert buy_hold.exposure == pytest.approx((n - 1) / n)
        assert strat.total_return is not None
        assert buy_hold.total_return is not None
        # the strategy's own return is not on the same footing as buy-hold's without the exposure
        assert strat.exposure != pytest.approx(buy_hold.exposure)


class TestCagrThreshold:
    """Annualising less than a year of data produces a number shaped like a rate that is really an
    extrapolation -- CAGR must refuse rather than report one."""

    @staticmethod
    def _always_in_market(n: int) -> tuple[StrategySpec, dict[str, pd.Series]]:
        entry = pd.Series([i == 0 for i in range(n)], dtype="boolean")
        never = pd.Series([False] * n, dtype="boolean")
        return StrategySpec(entry="entry", exit="never"), {"entry": entry, "never": never}

    def test_cagr_is_none_under_a_year(self) -> None:
        n = 100  # 99 elapsed bars at 252/year is well under a year
        close = 100.0 * 1.001**np.arange(n)
        bars = _frame(close)
        spec, signals = self._always_in_market(n)

        strat, _, _, _, _, _ = _backtest(bars, spec, signals)
        assert strat.cagr is None

    def test_cagr_is_not_none_over_three_years(self) -> None:
        n = 3 * 252 + 1  # exactly 3.0 elapsed years at 252/year
        close = 100.0 * 1.0002**np.arange(n)
        bars = _frame(close)
        spec, signals = self._always_in_market(n)

        strat, _, _, _, _, _ = _backtest(bars, spec, signals)
        assert strat.cagr is not None


class TestAnnualisedRiskFloor:
    """Sharpe, Sortino and annualised volatility share CAGR's one-year floor -- see the module
    docstring in ``app/backtest/metrics.py``. Multiplying a short-sample statistic by
    ``sqrt(bars_per_year)`` produces a number shaped like an annual risk-adjusted return; below a
    year of elapsed data that shape is not available at any sample size, no matter how the bars
    happen to move."""

    @staticmethod
    def _always_in_market(n: int) -> tuple[StrategySpec, dict[str, pd.Series]]:
        entry = pd.Series([i == 0 for i in range(n)], dtype="boolean")
        never = pd.Series([False] * n, dtype="boolean")
        return StrategySpec(entry="entry", exit="never"), {"entry": entry, "never": never}

    def test_six_bars_five_elapsed_days_withholds_sharpe_sortino_and_volatility(self) -> None:
        # Reproduces the QA finding verbatim: 6 bars, 5 elapsed trading days (0.0198 years at
        # 252/year), always in market, zero cost. The old code returned sharpe=5.02, sortino=8.51
        # and volatility=0.080 -- a Sharpe over 5 out of five days of noise.
        n = 6
        close = np.array([100.0, 101.0, 99.5, 102.0, 100.5, 103.0])
        bars = _frame(close)
        spec, signals = self._always_in_market(n)

        strat, _, _, _, _, _ = _backtest(bars, spec, signals, costs=Costs(slippage_bps=0.0))

        assert strat.cagr is None
        assert strat.sharpe is None
        assert strat.sortino is None
        assert strat.volatility is None

    def test_three_bars_one_lucky_day_withholds_sharpe(self) -> None:
        # Reproduces the QA finding verbatim: 3 bars, 2 elapsed days, one lucky day. The old code
        # returned sharpe=11.22 from a single outsized one-day gain.
        n = 3
        close = np.array([100.0, 100.0, 130.0])
        bars = _frame(close)
        spec, signals = self._always_in_market(n)

        strat, _, _, _, _, _ = _backtest(bars, spec, signals, costs=Costs(slippage_bps=0.0))

        assert strat.cagr is None
        assert strat.sharpe is None
        assert strat.sortino is None
        assert strat.volatility is None

    def test_a_series_at_or_beyond_the_floor_reports_real_numbers(self) -> None:
        n = 253  # 252 elapsed bars at 252/year == exactly 1.0 years elapsed, the floor itself
        close = 100.0 + 8.0 * np.sin(np.arange(n) * 0.35) + 0.05 * np.arange(n)
        bars = _frame(close)
        spec, signals = self._always_in_market(n)

        strat, _, _, _, _, _ = _backtest(bars, spec, signals, costs=Costs(slippage_bps=0.0))

        assert strat.cagr is not None
        assert strat.sharpe is not None
        assert strat.sortino is not None
        assert strat.volatility is not None


class TestSortinoNoLosses:
    """An infinite Sortino from a zero downside-deviation is not a strong result, it is an empty
    denominator -- see ``app/backtest/metrics.py``."""

    def test_sortino_is_none_when_no_bar_lost_money(self) -> None:
        # 253 bars (252 elapsed) clears the one-year annualisation floor by exactly one bar, so this
        # isolates the no-losses branch: without the extra length, `strat.sortino is None` would
        # hold for the unrelated reason that the sample is under a year (see
        # TestAnnualisedRiskFloor), and this test would stop testing what its name says.
        n = 253
        close = np.linspace(100.0, 180.0, n)  # strictly increasing: every held bar gains
        bars = _frame(close)
        entry = pd.Series([i == 0 for i in range(n)], dtype="boolean")
        never = pd.Series([False] * n, dtype="boolean")
        spec = StrategySpec(entry="entry", exit="never")

        strat, _, _, _, _, _ = _backtest(
            bars, spec, {"entry": entry, "never": never}, costs=Costs(slippage_bps=0.0)
        )
        assert strat.sortino is None


class TestWinRateExcludesOpenTrade:
    """A position still open at the end of the series has no decided outcome -- it must not enter
    the win-rate denominator at all, win or lose."""

    def test_the_open_trade_is_excluded_from_the_win_rate_denominator(self) -> None:
        n = 20
        close = np.full(n, 100.0)
        open_ = close.copy()
        open_[2] = 100.0  # trade 1 entry
        open_[5] = 110.0  # trade 1 exit -- a win
        open_[8] = 100.0  # trade 2 entry
        open_[11] = 90.0  # trade 2 exit -- a loss
        open_[14] = 100.0  # trade 3 entry -- never closes
        bars = _frame(close, open_=open_)

        entry = pd.Series([i in (1, 7, 13) for i in range(n)], dtype="boolean")
        exit_ = pd.Series([i in (4, 10) for i in range(n)], dtype="boolean")
        spec = StrategySpec(entry="entry", exit="exit")

        strat, _, trades, _, _, open_trades = _backtest(
            bars, spec, {"entry": entry, "exit": exit_}, costs=Costs(slippage_bps=0.0)
        )

        assert open_trades == 1
        assert len(trades) == 3
        closed = [t for t in trades if not t.open_at_end]
        assert len(closed) == 2
        assert strat.trades == 3
        assert strat.win_rate == pytest.approx(0.5)


class TestWarmupUnknownOpensNoPosition:
    """``pd.NA`` is not ``True``: a warmup bar with no truth value must not open a position."""

    def test_pd_na_during_warmup_does_not_open_a_position(self) -> None:
        n = 10
        close = np.full(n, 100.0)
        bars = _frame(close)

        entry = pd.Series([pd.NA] * 5 + [True] + [False] * (n - 6), dtype="boolean")
        never = pd.Series([False] * n, dtype="boolean")
        spec = StrategySpec(entry="entry", exit="never")

        _, _, trades, _, _, _ = _backtest(bars, spec, {"entry": entry, "never": never})

        assert len(trades) == 1
        assert trades[0].entry_date == bars["ts"].dt.date.iloc[6]


class TestEmptyAndDegenerate:
    def test_neither_exit_nor_max_holding_bars_is_refused(self) -> None:
        bars = _frame(np.array([100.0, 101.0]))
        spec = StrategySpec(entry="entry")
        with pytest.raises(ValueError, match="at least one of"):
            _backtest(bars, spec, {"entry": pd.Series([True, False], dtype="boolean")})

    def test_an_empty_frame_produces_no_trades_and_no_crash(self) -> None:
        bars = _frame(np.array([], dtype=float))
        spec = StrategySpec(entry="entry", max_holding_bars=5)

        strat, buy_hold, trades, curve, cost_drag, open_trades = _backtest(
            bars, spec, {"entry": pd.Series([], dtype="boolean")}
        )

        assert trades == []
        assert curve == []
        assert cost_drag == 0.0
        assert open_trades == 0
        assert strat.total_return is None
        assert buy_hold.total_return is None

    def test_a_single_bar_produces_no_trades(self) -> None:
        bars = _frame(np.array([100.0]))
        spec = StrategySpec(entry="entry", max_holding_bars=5)
        entry = pd.Series([True], dtype="boolean")

        _, _, trades, curve, cost_drag, open_trades = _backtest(bars, spec, {"entry": entry})

        assert trades == []
        assert len(curve) == 1
        assert open_trades == 0
        assert cost_drag == 0.0


class TestCostsValidation:
    """``Costs.notional`` converts a per-trade currency commission into the unitless equity
    multiplier -- see ``app/backtest/strategy.py``'s ``commission_frac = commission_per_trade /
    notional``. Zero makes that division undefined (the old code special-cased it to 0.0, silently
    discarding a real commission); negative flips its sign, turning a cost into a manufactured gain.
    Both are rejected on the model itself now, not only by the HTTP request schema in
    ``app/api/report.py`` -- so ``app/report/service.py::build_strategy_result``, which accepts a
    bare ``Costs``, is protected too."""

    def test_zero_notional_is_rejected_at_construction(self) -> None:
        with pytest.raises(ValidationError):
            Costs(notional=0.0)

    def test_negative_notional_is_rejected_at_construction(self) -> None:
        with pytest.raises(ValidationError):
            Costs(notional=-10_000.0)

    def test_negative_slippage_is_rejected_at_construction(self) -> None:
        """A negative slippage is a rebate, not a smaller cost: it would fill every entry and exit
        favourably rather than against the trader, flattering every backtest built on it."""
        with pytest.raises(ValidationError):
            Costs(slippage_bps=-1.0)

    def test_negative_commission_is_rejected_at_construction(self) -> None:
        """A negative commission is a per-trade rebate for the same reason -- see
        ``Costs.commission_per_trade``'s docstring."""
        with pytest.raises(ValidationError):
            Costs(commission_per_trade=-1.0)


class TestCommissionNotionalReproduction:
    """Reproduces the QA finding directly, isolated on a flat price series where the only source of
    P&L is the commission itself. At a sane notional the commission drags the return down by
    exactly its fraction of notional, paid on both entry and exit. At the notionals that used to
    produce silently wrong numbers -- zero and negative -- ``Costs`` now refuses to construct, so
    those numbers are unreachable rather than merely undesirable."""

    @staticmethod
    def _one_round_trip(n: int = 6) -> tuple[pd.DataFrame, StrategySpec, dict[str, pd.Series]]:
        close = np.full(n, 100.0)  # flat: zero price movement isolates the commission
        bars = _frame(close)
        entry = pd.Series([i == 0 for i in range(n)], dtype="boolean")
        exit_ = pd.Series([i == 3 for i in range(n)], dtype="boolean")
        spec = StrategySpec(entry="entry", exit="exit")
        return bars, spec, {"entry": entry, "exit": exit_}

    def test_fifty_dollar_commission_on_ten_thousand_notional_drags_return_down(self) -> None:
        bars, spec, signals = self._one_round_trip()
        costs = Costs(slippage_bps=0.0, commission_per_trade=50.0, notional=10_000.0)

        strat, _, trades, _, _, _ = _backtest(bars, spec, signals, costs=costs)

        assert len(trades) == 1
        commission_frac = 50.0 / 10_000.0
        expected = (1.0 - commission_frac) ** 2 - 1.0  # paid once on entry, once on exit
        assert strat.total_return == pytest.approx(expected)
        assert strat.total_return == pytest.approx(-0.009975)
        assert strat.total_return < 0.0

    def test_zero_notional_can_no_longer_silently_drop_the_commission(self) -> None:
        # Old behaviour: `commission_per_trade / notional if notional else 0.0` made the $50
        # commission vanish entirely, reporting total_return == 0.0 on a series with real cost.
        with pytest.raises(ValidationError):
            Costs(slippage_bps=0.0, commission_per_trade=50.0, notional=0.0)

    def test_negative_notional_can_no_longer_manufacture_a_positive_return(self) -> None:
        # Old behaviour: a negative notional flipped commission_frac's sign, turning a $50 cost into
        # total_return == +0.010025 -- a commission that paid the trader.
        with pytest.raises(ValidationError):
            Costs(slippage_bps=0.0, commission_per_trade=50.0, notional=-10_000.0)


class TestBarsPerYearCompleteness:
    """A loop over every `Interval` member, not a hardcoded list -- fails loudly if an eighth
    interval is added and this table forgotten, rather than `KeyError`-ing the first attempt to
    annualise a metric computed on it.

    The intraday entries exist only to prevent that crash. They are not an endorsement of
    annualising a Sharpe ratio computed on, say, 5-minute bars -- see the warning in
    `app.backtest.models.BARS_PER_YEAR`'s docstring.
    """

    def test_every_interval_has_an_entry(self) -> None:
        assert set(BARS_PER_YEAR) == set(Interval)

    def test_values_match_measured_bars_per_session_times_252(self) -> None:
        assert BARS_PER_YEAR[Interval.FIVE_MIN] == 78 * 252.0
        assert BARS_PER_YEAR[Interval.FIFTEEN_MIN] == 26 * 252.0
        assert BARS_PER_YEAR[Interval.THIRTY_MIN] == 13 * 252.0
        assert BARS_PER_YEAR[Interval.HOUR] == 7 * 252.0
        assert BARS_PER_YEAR[Interval.FOUR_HOUR] == 2 * 252.0
        assert BARS_PER_YEAR[Interval.DAY] == 252.0
        assert BARS_PER_YEAR[Interval.WEEK] == 52.0

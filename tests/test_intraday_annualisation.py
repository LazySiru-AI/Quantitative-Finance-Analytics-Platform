"""Annualised metrics are suppressed on intraday bars.

Regression guard for a defect this repository briefly shipped. Before `15m`/`30m`/`4h` were added,
`BARS_PER_YEAR` covered only `1d`/`1w`, so `app.backtest.strategy.backtest` raised `KeyError` on any
intraday interval -- loud, and impossible to mistake for a result. Filling the table removed the
crash and replaced it with something worse: `/api/report/strategy` at `1h` returned
`cagr=0.155, sharpe=0.93` against the same rule's `cagr=0.025, sharpe=0.22` at `1d`, inviting the
reader to conclude hourly was four times better. It is not. `sqrt(bars_per_year)` scaling assumes
serially independent bar returns; intraday returns are autocorrelated, so the constant inflates the
statistic rather than translating it.

The rule these tests pin: annualised statistics are `None` on intraday intervals, un-annualised ones
survive. See `app.backtest.metrics.compute`'s `annualisable` parameter.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.backtest import metrics
from app.backtest.models import BARS_PER_YEAR
from app.db.duck import Interval

#: Every annualised field, and every field that must survive regardless of bar size.
_ANNUALISED = ("cagr", "volatility", "sharpe", "sortino")
_UNANNUALISED = ("total_return", "max_drawdown", "exposure", "trades", "win_rate")


def _equity(n: int = 3000, *, seed: int = 0) -> np.ndarray:
    """A multi-year-length random walk starting at 1.0, long enough to clear the one-year floor at
    every interval -- so a `None` in these tests is attributable to `annualisable`, never to sample
    length."""
    rng = np.random.default_rng(seed)
    return np.cumprod(np.concatenate([[1.0], 1.0 + rng.normal(0.0002, 0.01, n - 1)]))


class TestAnnualisableFlag:
    def test_annualised_fields_are_none_when_not_annualisable(self) -> None:
        equity = _equity()
        result = metrics.compute(
            equity,
            in_position=np.ones(equity.size, dtype=bool),
            trades=[],
            bars_per_year=BARS_PER_YEAR[Interval.HOUR],
            annualisable=False,
        )
        for field in _ANNUALISED:
            assert getattr(result, field) is None, f"{field} must be None when not annualisable"

    def test_unannualised_fields_survive_when_not_annualisable(self) -> None:
        """The suppression must be surgical. `total_return` and `max_drawdown` are not annualised
        and stay meaningful at any bar size -- blanking them would make an intraday run useless
        rather than merely un-annualised."""
        equity = _equity()
        result = metrics.compute(
            equity,
            in_position=np.ones(equity.size, dtype=bool),
            trades=[],
            bars_per_year=BARS_PER_YEAR[Interval.HOUR],
            annualisable=False,
        )
        assert result.total_return is not None
        assert result.max_drawdown is not None
        assert result.exposure is not None

    def test_the_same_curve_does_annualise_when_permitted(self) -> None:
        """Control: the `None`s above come from the flag, not from the data."""
        equity = _equity()
        result = metrics.compute(
            equity,
            in_position=np.ones(equity.size, dtype=bool),
            trades=[],
            bars_per_year=BARS_PER_YEAR[Interval.DAY],
            annualisable=True,
        )
        for field in _ANNUALISED:
            assert getattr(result, field) is not None, f"{field} should be computed when permitted"

    def test_annualisable_defaults_to_true(self) -> None:
        """Existing callers that never heard of this parameter keep their behaviour."""
        equity = _equity()
        result = metrics.compute(
            equity,
            in_position=np.ones(equity.size, dtype=bool),
            trades=[],
            bars_per_year=BARS_PER_YEAR[Interval.DAY],
        )
        assert result.sharpe is not None


class TestIntervalPolicy:
    @pytest.mark.parametrize(
        "interval",
        [Interval.FIVE_MIN, Interval.FIFTEEN_MIN, Interval.THIRTY_MIN, Interval.HOUR, Interval.FOUR_HOUR],
    )
    def test_every_intraday_interval_is_non_annualisable(self, interval: Interval) -> None:
        """`4h` is the one worth stating explicitly: at 730 days of retention it clears the one-year
        floor comfortably, so nothing *except* this policy stops it reporting an inflated Sharpe."""
        assert interval.is_intraday is True

    @pytest.mark.parametrize("interval", [Interval.DAY, Interval.WEEK])
    def test_daily_and_weekly_remain_annualisable(self, interval: Interval) -> None:
        assert interval.is_intraday is False

    def test_every_interval_has_a_bars_per_year_entry(self) -> None:
        """The suppression is a policy, not a crash guard -- the table must still be complete so
        `metrics.compute` can record `bars_per_year` on the result at any interval."""
        missing = [i.value for i in Interval if i not in BARS_PER_YEAR]
        assert missing == []


class TestEndToEndThroughStrategy:
    """The defect was only visible end-to-end, so pin it there too."""

    @pytest.mark.parametrize("interval", [Interval.HOUR, Interval.FOUR_HOUR])
    def test_intraday_backtest_reports_no_annualised_metrics(self, interval: Interval) -> None:
        pd = pytest.importorskip("pandas")
        from app.backtest.models import StrategySpec
        from app.backtest.strategy import backtest

        n = 3000
        rng = np.random.default_rng(1)
        close = np.cumprod(np.concatenate([[100.0], 1.0 + rng.normal(0.0002, 0.01, n - 1)]))
        bars = pd.DataFrame(
            {
                "ts": pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
                "open": close,
                "high": close * 1.002,
                "low": close * 0.998,
                "close": close,
                "adj_close": close,
                "volume": np.full(n, 1000),
            }
        )
        spec = StrategySpec(entry="rsi(14) < 30", exit="rsi(14) > 70")
        strategy_metrics, buy_hold, *_ = backtest(bars, spec, interval=interval)

        for field in _ANNUALISED:
            assert getattr(strategy_metrics, field) is None, f"strategy.{field} leaked at {interval}"
            assert getattr(buy_hold, field) is None, f"buy_hold.{field} leaked at {interval}"
        # ...but the run still produced something worth reading.
        assert strategy_metrics.total_return is not None
        assert buy_hold.total_return is not None

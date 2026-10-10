"""Summary statistics for one equity curve.

**A number a caller could mistake for a stronger claim than the sample supports is not computed.**
Every statistic below returns ``None`` rather than a value once its sample is too thin to mean what
it looks like it means -- see the module docstring in :mod:`app.backtest.models`, "Strategy
backtest" section, for why that is a requirement rather than a style preference here:

* :attr:`~app.backtest.models.StrategyMetrics.cagr` is ``None`` under a year of data. Annualising
  four months of return produces a number shaped like a rate; it is an extrapolation, not a
  measurement.
* :attr:`~app.backtest.models.StrategyMetrics.sortino` is ``None`` when no bar lost money relative
  to the target. The alternative -- dividing by a zero downside-deviation -- produces an infinite
  Sortino, which reads as the strongest possible result for the least informative possible sample.
* :attr:`~app.backtest.models.StrategyMetrics.win_rate` is computed over *closed* trades only. A
  trade still open at the end of the series has no decided outcome yet.
* :attr:`~app.backtest.models.StrategyMetrics.sharpe`, :attr:`~...sortino` and
  :attr:`~...volatility` share :attr:`~...cagr`'s one-year floor (see :func:`_cagr`). All four are
  annualised -- multiplied by ``sqrt(bars_per_year)`` or raised to a ``1/years_elapsed`` power -- and
  that multiplication is exactly what turns a few days of ordinary noise into a number shaped like a
  multi-year track record. Five bars of returns have a real sample standard deviation, and
  ``sqrt(252)`` is a real number, but their product is not a measurement of annual risk; it is
  sampling error amplified by a constant. The floor is one threshold, defined once in
  :func:`_annualisation_permitted`, applied to every figure whose unit is "per year" -- not a
  separate judgment call per statistic.

**Sharpe and Sortino share one excess-return convention.** Both measure the mean per-bar return in
excess of ``risk_free_rate`` de-annualised to a per-bar figure (``risk_free_rate / bars_per_year``);
Sortino's denominator is the downside deviation around that same target rather than around zero, so
a non-zero risk-free rate shifts what counts as "downside" exactly the way it shifts what counts as
"excess" for Sharpe.

**``float('nan')``/``inf`` never reach the model.** Every division that could produce either is
guarded -- either by returning ``None`` before it happens, or by passing the result through
:func:`app.market.models.jsonable_float` on the way out.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from app.backtest.models import StrategyMetrics, Trade
from app.market.models import jsonable_float

__all__ = ["compute"]


def compute(
    equity: np.ndarray,
    *,
    in_position: np.ndarray,
    trades: Sequence[Trade],
    bars_per_year: float,
    risk_free_rate: float = 0.0,
    annualisable: bool = True,
) -> StrategyMetrics:
    """Summarise one equity curve, ``equity[0]`` normalised to ``1.0``.

    ``equity`` and ``in_position`` are one value per bar, aligned. ``trades`` is every trade the
    equity curve is built from, including one still open at the end (:attr:`Trade.open_at_end`) --
    that trade is excluded from :attr:`~app.backtest.models.StrategyMetrics.win_rate` but still
    counts toward :attr:`~app.backtest.models.StrategyMetrics.trades`, because it happened.

    Returns the all-``None`` :class:`~app.backtest.models.StrategyMetrics` (aside from
    ``risk_free_rate``/``bars_per_year``, always recorded) for an empty ``equity``: there is nothing
    to measure, and no metric here is entitled to a fabricated zero.

    ``annualisable=False`` suppresses the four annualised statistics (``cagr``, ``volatility``,
    ``sharpe``, ``sortino``) exactly as the one-year floor in :func:`_cagr` does, and for a sibling
    reason. The floor refuses to annualise when the sample is too *short*; this refuses when the bar
    is too *fine*. Scaling by ``sqrt(bars_per_year)`` assumes bar returns are serially independent,
    which intraday returns are not -- microstructure autocorrelation inflates the result, so an
    hourly Sharpe and a daily Sharpe over the same period are not on the same scale and must not be
    read side by side. Callers that know the bar interval pass
    ``annualisable=not interval.is_intraday``; see :data:`app.backtest.models.BARS_PER_YEAR`, whose
    intraday entries exist to keep this function from raising, not to endorse its output at those
    intervals.

    ``total_return``, ``max_drawdown``, ``exposure``, ``trades`` and ``win_rate`` are unaffected:
    none of them is annualised, and all remain meaningful at any bar size.
    """
    n = int(equity.size)
    base = StrategyMetrics(risk_free_rate=risk_free_rate, bars_per_year=bars_per_year)
    if n == 0:
        return base

    total_return = jsonable_float(float(equity[-1] / equity[0] - 1.0))

    bars_elapsed = n - 1
    years_elapsed = bars_elapsed / bars_per_year if bars_elapsed > 0 else 0.0
    returns = equity[1:] / equity[:-1] - 1.0 if n > 1 else np.array([], dtype=float)

    rf_per_bar = risk_free_rate / bars_per_year
    closed = [t for t in trades if not t.open_at_end]

    return StrategyMetrics(
        total_return=total_return,
        cagr=_cagr(float(equity[0]), float(equity[-1]), years_elapsed) if annualisable else None,
        volatility=_volatility(returns, bars_per_year, years_elapsed) if annualisable else None,
        sharpe=_sharpe(returns, rf_per_bar, bars_per_year, years_elapsed) if annualisable else None,
        sortino=_sortino(returns, rf_per_bar, bars_per_year, years_elapsed) if annualisable else None,
        max_drawdown=_max_drawdown(equity),
        exposure=jsonable_float(float(np.mean(in_position))) if in_position.size else None,
        trades=len(trades),
        trades_per_year=(len(trades) / years_elapsed) if years_elapsed > 0 else None,
        win_rate=_win_rate(closed),
        risk_free_rate=risk_free_rate,
        bars_per_year=bars_per_year,
    )


def _cagr(start: float, end: float, years_elapsed: float) -> float | None:
    """``None`` under a year -- see the module docstring -- and also when ``start`` is not a usable
    positive basis or the ratio is non-positive (a >=100% loss has no real-valued annualised rate)."""
    if years_elapsed < 1.0 or start <= 0.0:
        return None
    ratio = end / start
    if ratio <= 0.0:
        return None
    return jsonable_float(float(ratio ** (1.0 / years_elapsed) - 1.0))


def _annualisation_permitted(years_elapsed: float) -> bool:
    """The one floor shared by every "per year" figure -- see the module docstring.

    A statistic multiplied by ``sqrt(bars_per_year)`` (Sharpe, Sortino, volatility) or raised to
    ``1 / years_elapsed`` (CAGR) is a claim about an annual rate. Below a year of elapsed data that
    claim is not available at any sample size: five bars of daily returns can have a perfectly real
    sample standard deviation, and multiplying it by ``sqrt(252)`` is arithmetically valid, but the
    result estimates what a *year* of that process would look like from *days* of it -- a Sharpe of
    5 to 11 out of two to five trading days is ordinary short-run noise wearing the units of a
    multi-year track record, not evidence of one. Matches :func:`_cagr`'s ``years_elapsed < 1.0``
    threshold exactly, because the two are the same guard against the same mistake."""
    return years_elapsed >= 1.0


def _volatility(returns: np.ndarray, bars_per_year: float, years_elapsed: float) -> float | None:
    """Annualised sample standard deviation (``ddof=1``) of per-bar returns. ``None`` below two
    observations, where a sample standard deviation is undefined rather than zero, and ``None``
    under a year of elapsed data -- see :func:`_annualisation_permitted`."""
    if returns.size < 2 or not _annualisation_permitted(years_elapsed):
        return None
    stdev = float(np.std(returns, ddof=1))
    return jsonable_float(stdev * math.sqrt(bars_per_year))


def _sharpe(
    returns: np.ndarray, rf_per_bar: float, bars_per_year: float, years_elapsed: float
) -> float | None:
    """``(mean excess return / stdev) * sqrt(bars_per_year)``. ``None`` below two observations, when
    the sample has no dispersion to divide by (every bar returned identically), or under a year of
    elapsed data -- see :func:`_annualisation_permitted`."""
    if returns.size < 2 or not _annualisation_permitted(years_elapsed):
        return None
    stdev = float(np.std(returns, ddof=1))
    if stdev == 0.0:
        return None
    mean_excess = float(np.mean(returns)) - rf_per_bar
    return jsonable_float(mean_excess / stdev * math.sqrt(bars_per_year))


def _sortino(
    returns: np.ndarray, rf_per_bar: float, bars_per_year: float, years_elapsed: float
) -> float | None:
    """As :func:`_sharpe`, but the denominator -- the downside deviation -- is built only from
    returns below ``rf_per_bar``: ``sqrt(mean((target - r)**2))`` over just that subset. ``None``
    when there are no such bars, matching :attr:`~app.backtest.models.StrategyMetrics.sortino`'s
    documented behaviour rather than reporting the infinite ratio a zero denominator implies, and
    ``None`` under a year of elapsed data -- see :func:`_annualisation_permitted`."""
    if returns.size == 0 or not _annualisation_permitted(years_elapsed):
        return None
    downside = returns[returns < rf_per_bar]
    if downside.size == 0:
        return None
    downside_deviation = float(np.sqrt(np.mean((rf_per_bar - downside) ** 2)))
    if downside_deviation == 0.0:
        return None
    mean_excess = float(np.mean(returns)) - rf_per_bar
    return jsonable_float(mean_excess / downside_deviation * math.sqrt(bars_per_year))


def _max_drawdown(equity: np.ndarray) -> float | None:
    """Most negative ``equity / running_max(equity) - 1``, run on the equity curve itself -- never
    reconstructed from returns, which would lose the compounding path the drawdown depends on."""
    if equity.size == 0:
        return None
    running_max = np.maximum.accumulate(equity)
    drawdown = equity / running_max - 1.0
    return jsonable_float(float(np.min(drawdown)))


def _win_rate(closed_trades: list[Trade]) -> float | None:
    """Fraction of *closed* trades with a strictly positive return. ``None`` when there are none --
    see :attr:`~app.backtest.models.StrategyMetrics.win_rate`'s docstring."""
    if not closed_trades:
        return None
    return jsonable_float(float(np.mean([t.return_pct > 0 for t in closed_trades])))

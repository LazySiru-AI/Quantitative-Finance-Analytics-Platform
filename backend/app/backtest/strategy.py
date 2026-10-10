"""Entry/exit backtesting, against buy-and-hold over the identical window.

**Contract.** The rule DSL, forward-return and injectable-collaborator conventions are shared with
every other module in this package -- see :mod:`app.backtest.forward` for the entry timing and
:mod:`app.backtest.events` for the ``Grammar``/``Evaluator`` seam this module copies. What is new
here is turning a signal into an actual sequence of fills, which is where a backtest most easily
lies to itself. See the "Strategy backtest" section of :mod:`app.backtest.models` for the three
header requirements (buy-and-hold is not optional, frictions are reported not assumed away, every
metric carries its assumption); this module is what produces the inputs those requirements bind.

**Exit priority, per bar, when several conditions would fire at once**: stop loss, then max holding
bars, then the exit signal. A stop is checked against the bar's own ``low`` (and ``open``, for a
gap) every bar a position is open, including the entry bar itself -- a position bought at the open
can still be stopped out intraday the same day. See :class:`~app.backtest.models.StrategySpec` and
:class:`~app.backtest.models.ExitReason` for what each priced.

**Entry and exit signals fill one bar later than they are known**, exactly like every other module
here: a signal true at bar ``t``'s close is actionable at bar ``t + 1``'s open, because the close is
the first moment the signal has a value. This applies to entries, and to exits driven by the exit
expression -- but *not* to stop-loss or max-holding exits, which are priced against the bar they are
detected on (the stop is a price level breached intraday; the holding cap is a bar count, not a
signal that needs a close to exist).

**No pyramiding.** An entry signal that fires while a position is already open is not queued for
later -- it is simply never looked at, the same way :mod:`app.backtest.events` treats a signal's
warmup ``pd.NA`` as "no truth value" rather than "false and remembered". A flat entry signal is only
consulted once a position has actually closed that bar or earlier.

**Buy-and-hold shares the entry convention.** It is not "bought at bar 0's close" -- that would let
it start a bar earlier than any strategy ever could, which is the exact asymmetry the header comment
in :mod:`app.backtest.models` warns about. It is treated as if an entry signal fired on bar 0 itself,
so it fills at bar 1's open, precisely matching what an always-in-the-market strategy does. This is
also why :attr:`~app.backtest.models.EquityPoint.equity` and
:attr:`~app.backtest.models.EquityPoint.buy_hold` both start at exactly ``1.0`` on bar 0: neither has
entered anything yet. Buy-and-hold itself carries no frictions -- it is the frictionless baseline
:attr:`~app.backtest.models.StrategyResult.cost_drag` is implicitly measured against, not a strategy
whose own costs need reporting.

**Cost drag is measured by literally re-running the simulation at zero cost**, not by subtracting an
estimated friction, because slippage changes the fill price and therefore the *stop level* -- a
higher entry fill under nonzero slippage shifts where a stop-loss triggers, which can change the
whole trade sequence, not just its prices. Re-running is the only way to compare like for like. In
the (rare, path-dependent) case where a shifted stop level accidentally produces a better outcome,
``cost_drag`` could in principle come out fractionally positive; every scenario this module's own
tests construct avoids that, and a strategy with no ``stop_loss_pct`` cannot exhibit it at all, since
nothing about its trade sequence depends on the fill price.

**A flat per-trade commission has no natural unit against a unitless equity curve.** Bars carry
prices, not share counts, and position sizing is explicitly out of scope (see
:class:`~app.backtest.models.StrategySpec`) -- so ``Costs.commission_per_trade``, a currency amount,
cannot be converted to a fraction of an equity curve that starts at ``1.0`` without *some* assumed
notional. :attr:`~app.backtest.models.Costs.notional` exists solely for that conversion; it is not a
position-sizing decision, it is a unit converter, and it is inert at the documented commission
default of ``0.0``. It lives on the contract rather than in this module so it reaches the run card's
params and the API -- a constant here would silently set a number the reader sees without appearing
anywhere they could find it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import pandas as pd

from app.backtest import metrics
from app.backtest.models import (
    BARS_PER_YEAR,
    Costs,
    EquityPoint,
    ExitReason,
    StrategyMetrics,
    StrategySpec,
    Trade,
)
from app.db.duck import Interval
from app.market.models import jsonable_float
from app.rules.nodes import BoolExpr

__all__ = ["Evaluator", "Grammar", "backtest"]


#: The zero-friction run `cost_drag` is measured against. A local constant rather than
#: `Costs(slippage_bps=0.0)` written out at every call site.
_ZERO_COSTS = Costs(slippage_bps=0.0, commission_per_trade=0.0)


# ---------------------------------------------------------------------------
# Injectable collaborators -- see the module docstring and app.backtest.events
# ---------------------------------------------------------------------------


class Grammar(Protocol):
    """The subset of `app.rules.grammar` this module calls."""

    def parse(self, expression: str) -> BoolExpr: ...


class Evaluator(Protocol):
    """The subset of `app.rules.evaluate` this module calls.

    `macro` is optional and keyword-only so an `Evaluator` written before macro fields existed is not
    broken by a caller that passes it -- the same compatibility rule `app.backtest.events.Evaluator`
    states for `indicator_cache`. `_fired` passes `None` for every rule that references no macro
    series, which is every rule written before 2026-08-30.
    """

    def evaluate(
        self,
        node: BoolExpr,
        bars: pd.DataFrame,
        *,
        interval: Interval,
        macro: pd.DataFrame | None = None,
    ) -> pd.Series: ...


def _default_grammar() -> Grammar:
    from app.rules import grammar

    return grammar


def _default_evaluator() -> Evaluator:
    from app.rules import evaluate

    return evaluate


def _macro_binding() -> Any:
    """Imported lazily, matching how `Grammar` and `Evaluator` are resolved above.

    `app.rules.macro_binding` reaches `app.rules.macro_pin`, which touches the filesystem on its
    first macro rule. Importing that at module scope would make every consumer of this module pay for
    it, including the many that never evaluate a macro rule at all.
    """
    from app.rules import macro_binding

    return macro_binding


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------


def backtest(
    bars: pd.DataFrame,
    spec: StrategySpec,
    *,
    interval: Interval,
    costs: Costs = Costs(),  # noqa: B008 -- `Costs` is a frozen pydantic model; the shared default is inert
    risk_free_rate: float = 0.0,
    grammar: Grammar | None = None,
    evaluator: Evaluator | None = None,
) -> tuple[StrategyMetrics, StrategyMetrics, list[Trade], list[EquityPoint], float, int]:
    """Run ``spec`` over ``bars``, against buy-and-hold over the identical window.

    Returns ``(metrics, buy_hold_metrics, trades, equity_curve, cost_drag, open_trades)``. Long-only,
    all-in, no pyramiding -- see the module docstring for the fill and priority rules.

    Raises ``ValueError`` if neither ``spec.exit`` nor ``spec.max_holding_bars`` is set: a position
    opened once would otherwise never close, and the "strategy" would be buy-and-hold with extra
    steps and worse fills.
    """
    if spec.exit is None and spec.max_holding_bars is None:
        raise ValueError(
            "StrategySpec requires at least one of `exit` or `max_holding_bars` -- a position "
            "opened once would otherwise never close"
        )

    bars_per_year = BARS_PER_YEAR[interval]
    # Intraday bars get a `bars_per_year` so this function cannot raise, but not the right to be
    # annualised with it -- see `metrics.compute`'s `annualisable` for why an hourly Sharpe and a
    # daily Sharpe are not on the same scale. Suppressed here rather than in `metrics`, which knows
    # bar counts but deliberately not intervals.
    annualisable = not interval.is_intraday
    n = len(bars)

    if n == 0:
        empty = metrics.compute(
            np.array([], dtype=float),
            in_position=np.array([], dtype=bool),
            trades=[],
            bars_per_year=bars_per_year,
            risk_free_rate=risk_free_rate,
            annualisable=annualisable,
        )
        return empty, empty, [], [], 0.0, 0

    grammar_mod = grammar or _default_grammar()
    evaluator_mod = evaluator or _default_evaluator()

    entry_true = _fired(bars, spec.entry, interval=interval, grammar=grammar_mod, evaluator=evaluator_mod)
    exit_true = (
        _fired(bars, spec.exit, interval=interval, grammar=grammar_mod, evaluator=evaluator_mod)
        if spec.exit is not None
        else np.zeros(n, dtype=bool)
    )

    trades, equity, in_position = _simulate(
        bars, entry_true=entry_true, exit_true=exit_true, spec=spec, costs=costs
    )
    strategy_metrics = metrics.compute(
        equity,
        in_position=in_position,
        trades=trades,
        bars_per_year=bars_per_year,
        risk_free_rate=risk_free_rate,
        annualisable=annualisable,
    )

    cost_drag = _cost_drag(bars, entry_true, exit_true, spec, costs, strategy_metrics.total_return)

    buy_hold_equity, buy_hold_in_position = _buy_hold(bars)
    buy_hold_metrics = metrics.compute(
        buy_hold_equity,
        in_position=buy_hold_in_position,
        trades=[],
        bars_per_year=bars_per_year,
        risk_free_rate=risk_free_rate,
        annualisable=annualisable,
    )

    dates = bars["ts"].dt.date
    equity_curve = [
        EquityPoint(
            date=dates.iloc[i],
            equity=float(equity[i]),
            buy_hold=float(buy_hold_equity[i]),
            in_position=bool(in_position[i]),
        )
        for i in range(n)
    ]

    open_trades = sum(1 for t in trades if t.open_at_end)
    return strategy_metrics, buy_hold_metrics, trades, equity_curve, cost_drag, open_trades


def _fired(
    bars: pd.DataFrame,
    expression: str,
    *,
    interval: Interval,
    grammar: Grammar,
    evaluator: Evaluator,
) -> np.ndarray:
    """Evaluate ``expression`` and collapse it to a plain boolean array. ``pd.NA`` -- an unknown
    truth value, typically an indicator's warmup window -- becomes ``False``: it cannot open or
    close a position, the same rule :mod:`app.backtest.events` applies to triggers."""
    node = grammar.parse(expression)
    # `None` unless the rule actually names a macro series, so nothing about a price-only rule's path
    # changes -- and a macro rule reaches the pin rather than a live fetch. See
    # `app.rules.macro_binding.bind_for_bars`.
    macro = _macro_binding().bind_for_bars(node, bars)
    # Passed only when there is one, so a price-only rule's call is byte-identical to what it was
    # before macro fields existed. Forwarding `macro=None` unconditionally would break every
    # `Evaluator` implemented against the older signature -- which is not hypothetical: it broke
    # thirty of this module's own tests when written that way.
    extra = {"macro": macro} if macro is not None else {}
    signal = evaluator.evaluate(node, bars, interval=interval, **extra)
    result: np.ndarray = signal.fillna(False).to_numpy(dtype=bool)
    return result


def _cost_drag(
    bars: pd.DataFrame,
    entry_true: np.ndarray,
    exit_true: np.ndarray,
    spec: StrategySpec,
    costs: Costs,
    total_return: float | None,
) -> float:
    """Total return at ``costs`` minus total return at zero cost, on the identical signal sequence.
    See the module docstring for why this is a second simulation rather than an estimated drag."""
    if total_return is None:
        return 0.0
    if costs.slippage_bps == 0.0 and costs.commission_per_trade == 0.0:
        return 0.0

    _, zero_cost_equity, _ = _simulate(
        bars, entry_true=entry_true, exit_true=exit_true, spec=spec, costs=_ZERO_COSTS
    )
    if zero_cost_equity.size == 0:
        return 0.0
    zero_cost_return = jsonable_float(float(zero_cost_equity[-1] / zero_cost_equity[0] - 1.0))
    if zero_cost_return is None:
        return 0.0
    return total_return - zero_cost_return


def _buy_hold(bars: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """The identical-window baseline -- see the module docstring. Entered at bar 1's open (as if an
    entry signal fired on bar 0), held to the last bar's close, no frictions."""
    n = len(bars)
    equity = np.ones(n, dtype=float)
    in_position = np.zeros(n, dtype=bool)
    if n >= 2:
        entry_price = float(bars["open"].to_numpy(dtype=float)[1])
        closes = bars["close"].to_numpy(dtype=float)
        equity[1:] = closes[1:] / entry_price
        in_position[1:] = True
    return equity, in_position


@dataclass
class _OpenPosition:
    entry_index: int
    entry_price: float
    """After slippage -- the price actually paid, and the basis the stop level is measured from."""
    basis_equity: float
    """Equity value immediately after entry commission was charged. Mark-to-market for this position
    is ``basis_equity * (mark_price / entry_price)``."""
    pre_entry_equity: float
    """Equity value immediately *before* this trade -- entry commission included or not. A trade's
    own `return_pct` is measured against this, so it reflects exactly what this one round trip cost
    or earned, independent of the compounding history before it."""


def _simulate(
    bars: pd.DataFrame,
    *,
    entry_true: np.ndarray,
    exit_true: np.ndarray,
    spec: StrategySpec,
    costs: Costs,
) -> tuple[list[Trade], np.ndarray, np.ndarray]:
    """One pass over ``bars``, turning signals into fills. See the module docstring for the exit
    priority (stop, then max holding bars, then exit signal) and the fill/friction rules."""
    n = len(bars)
    opens = bars["open"].to_numpy(dtype=float)
    lows = bars["low"].to_numpy(dtype=float)
    closes = bars["close"].to_numpy(dtype=float)
    dates = bars["ts"].dt.date

    slip = costs.slippage_bps / 10_000.0
    commission_frac = costs.commission_per_trade / costs.notional if costs.notional else 0.0

    equity = np.empty(n, dtype=float)
    in_position = np.zeros(n, dtype=bool)
    trades: list[Trade] = []

    settled_equity = 1.0
    position: _OpenPosition | None = None
    pending_entry = False
    pending_exit = False

    for j in range(n):
        o = opens[j]
        low_j = lows[j]
        close_j = closes[j]

        if position is None and pending_entry:
            entry_price = o * (1.0 + slip)
            basis_equity = settled_equity * (1.0 - commission_frac)
            position = _OpenPosition(
                entry_index=j,
                entry_price=entry_price,
                basis_equity=basis_equity,
                pre_entry_equity=settled_equity,
            )
        pending_entry = False

        raw_exit_price: float | None = None
        exit_reason: ExitReason | None = None
        if position is not None:
            if spec.stop_loss_pct is not None:
                stop_level = position.entry_price * (1.0 - spec.stop_loss_pct)
                if o <= stop_level:
                    raw_exit_price, exit_reason = o, ExitReason.STOP
                elif low_j <= stop_level:
                    raw_exit_price, exit_reason = stop_level, ExitReason.STOP
            if (
                exit_reason is None
                and spec.max_holding_bars is not None
                and (j - position.entry_index) >= spec.max_holding_bars
            ):
                raw_exit_price, exit_reason = close_j, ExitReason.HORIZON
            if exit_reason is None and pending_exit:
                raw_exit_price, exit_reason = o, ExitReason.SIGNAL
        pending_exit = False

        exit_fill: float | None = None
        if position is not None and raw_exit_price is not None:
            exit_fill = raw_exit_price * (1.0 - slip)

        if position is not None:
            mark_price = exit_fill if exit_fill is not None else close_j
            equity_j = position.basis_equity * (mark_price / position.entry_price)
            if exit_fill is not None:
                equity_j *= 1.0 - commission_frac
            equity[j] = equity_j
            in_position[j] = True
        else:
            equity[j] = settled_equity
            in_position[j] = False

        if position is not None and exit_reason is not None and exit_fill is not None:
            trades.append(
                Trade(
                    entry_date=dates.iloc[position.entry_index],
                    entry_price=position.entry_price,
                    exit_date=dates.iloc[j],
                    exit_price=exit_fill,
                    exit_reason=exit_reason,
                    bars_held=j - position.entry_index,
                    return_pct=equity[j] / position.pre_entry_equity - 1.0,
                    open_at_end=False,
                )
            )
            settled_equity = equity[j]
            position = None

        if position is None:
            if entry_true[j]:
                pending_entry = True
        elif exit_true[j]:
            pending_exit = True

    if position is not None:
        last = n - 1
        trades.append(
            Trade(
                entry_date=dates.iloc[position.entry_index],
                entry_price=position.entry_price,
                exit_date=dates.iloc[last],
                exit_price=closes[last],
                exit_reason=ExitReason.END_OF_DATA,
                bars_held=last - position.entry_index,
                return_pct=equity[last] / position.pre_entry_equity - 1.0,
                open_at_end=True,
            )
        )

    return trades, equity, in_position

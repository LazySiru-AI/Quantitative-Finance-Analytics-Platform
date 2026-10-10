"""The decision-log replay engine: score a persisted sequence of workflow orders through a fresh
`PaperBroker`, session by session -- the sibling of `app.tournament.runner.run_card`.

**Why this exists as its own module rather than reusing `run_card`.** `run_card` derives *what* to
trade from a `StrategyCard`'s rule expressions, evaluated fresh against stored bars every session --
that is the whole point of a mechanical card, and it is exactly the thing `app.workflow`'s orders are
not (see `app.workflow.book_models`'s own module docstring: a workflow order is the output of a chain
of language-model judgements made on day N, and is not recomputable from price history alone). This
module is handed the *decisions themselves*, already made and already dated, and its only job is to
submit them through the same broker, with the same fill and slippage rules, and mark the same kind of
equity curve `run_card` does -- so that an arm's orders can be scored by the one metrics
implementation (`app.backtest.metrics.compute`) every other card in this programme is scored by.

**Reused, not reimplemented, from `run_card`:** the fill convention (`market` pinned to the *decision*
session, `fill_date` the session after it -- see `PaperBroker.submit`'s own docstring), the
equity-curve normalisation (`equity[0]` prepended as `starting_cash` so `compute()`'s "equity[0] == 1.0"
contract is satisfied without dividing away a legitimate first-session move -- see `run_card`'s own
comment on this), and the `annualisable=not interval.is_intraday` -- except this module is *always*
called `annualisable=False`, per `docs/WORKFLOW-STUDY-PLAN.md` §3: a few months of daily decisions is
never a year, so a caller that somehow got here with a year or more of data still gets the honest
answer from `metrics.compute`'s own one-year floor, not a mistaken annualisation this module invented.

**Engine-honesty control (`docs/WORKFLOW-STUDY-PLAN.md` §5).** The raw arm's orders, replayed through
this module's `run_decision_log`, must reproduce `run_card`'s own fills and equity for the same
underlying decisions -- see `tests/test_workflow_replay.py`'s `TestEngineHonestyControl` for exactly
what is and is not covered by that claim, and this module's own `run_decision_log` docstring for the
one structural difference (notional-to-quantity sizing happens here, in this module, because a
`WorkflowOrderRecord` carries a dollar notional and never a share count -- see `OrderPlan.notional`'s
own docstring for why that conversion is deferred all the way to fill time).

**Chosen over reusing `BookState`'s already-filled orders.** `app.workflow.book.execute_pending`
already turns a `WorkflowOrderRecord` into a filled order against the real broker -- but it does so
*live*, one catch-up batch at a time, against whatever `broker_state` blob happened to be persisted at
that moment, and it is not handed a `SessionCalendar` to walk. `run_decision_log` is the *scoring*
replay: given a whole decision log and a shared calendar, it rebuilds the broker from scratch and
walks every session in order, submitting each session's due orders against that session's own
decision-market instance, exactly as `run_card` does. Reusing `execute_pending`'s already-filled
`WorkflowFillRecord`s directly would have been simpler, but it would not by itself prove anything about
`run_card` parity -- the two would only agree if `execute_pending`'s per-call catch-up semantics
happen to coincide with a full session-by-session replay, which is not guaranteed and is not this
module's job to assume. Resubmitting through a fresh `PaperBroker`, driven by the same `AsOfMarket`/
`fill_date` convention `run_card` uses, is what makes the engine-honesty comparison meaningful.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import ROUND_DOWN, Decimal
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict

from app.backtest import metrics as metrics_mod
from app.backtest.models import BARS_PER_YEAR, ExitReason, StrategyMetrics
from app.backtest.models import Trade as MetricsTrade
from app.config import Settings
from app.market.models import Interval
from app.paper.marketdata import AsOfMarket, SessionCalendar, UnpricedSymbol
from app.paper.paperbroker import Fill, Mandate, Order, PaperBroker
from app.workflow.book_models import WorkflowOrderRecord

__all__ = ["EquityPoint", "ReplayResult", "run_decision_log"]


class _Frozen(BaseModel):
    """Local shorthand, mirroring `app.workflow.book_models._Frozen`."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class EquityPoint(_Frozen):
    """One mark-to-market reading in a replayed equity curve. A distinct type from
    `app.workflow.book_models.EquityPoint` -- this module never reads or writes a persisted
    `BookState`, so there is no reason to share its wire type, only its shape."""

    date: dt.date
    equity: Decimal


class ReplayResult(_Frozen):
    """What `run_decision_log` produced: an equity curve, the canonical metrics computed from it, and
    the two study-specific figures (`docs/WORKFLOW-STUDY-PLAN.md` §3) that `metrics.compute` does not
    itself carry."""

    equity_curve: tuple[EquityPoint, ...]
    metrics: StrategyMetrics
    realized_vol: Decimal
    """Non-annualised standard deviation of `daily_returns` -- see this module's docstring on why
    `StrategyMetrics.volatility` (annualised, and `None` under a year regardless) is not this figure."""
    daily_returns: tuple[Decimal, ...]
    """One entry per session in the replay's calendar, in session order -- `equity[i] / equity[i-1] -
    1` off the curve *including* its prepended `starting_cash` point, so the first entry is the first
    session's own move. Exact `Decimal` arithmetic throughout; never round-tripped through `float`."""


def _quantity_for_notional(notional: Decimal, price: Decimal, *, allow_fractional: bool) -> Decimal:
    """Dollar notional -> share count against `price`. A deliberate copy of
    `app.workflow.book._quantity_for_notional`'s body, not an import of it: that function is private
    to its module, and the two call sites (a live catch-up fill and this scoring replay) are told not
    to invent two different conventions for the same conversion, not to reach through one module's
    privacy to reuse it -- see `app.workflow.candidates._window_return`'s own docstring for the same
    convention elsewhere in this package. `price <= 0` returns zero rather than dividing, which the
    caller then treats as "nothing to fill" -- there is no mandate rejection path to route through
    here, since no `Order` is ever built for a non-positive quantity."""
    if price <= 0:
        return Decimal(0)
    raw = notional / price
    return raw if allow_fractional else raw.to_integral_value(rounding=ROUND_DOWN)


def _undilute_exposure(exposure: float | None, sessions: int) -> float | None:
    """Rescale session-presence exposure off the prepended starting-equity point -- a deliberate copy
    of `app.tournament.runner._undilute_exposure`'s body (private to its module, so copied rather than
    imported; see `_quantity_for_notional`'s docstring for this package's convention on that). Without
    it, an arm holding a position on every one of `sessions` sessions would report `sessions /
    (sessions + 1)` instead of `1.0`, because `metrics.compute` derives `exposure` as
    `mean(in_position)` over an array that includes the prepended, pre-trading alignment point."""
    if exposure is None or sessions <= 0:
        return exposure
    return exposure * (sessions + 1) / sessions


def _bars_held(entry_date: dt.date, exit_date: dt.date, calendar: SessionCalendar) -> int:
    """Sessions between two calendar dates, counted off `calendar`'s own session list -- not calendar
    days, which would overcount every run that spans a weekend. Never consumed by `metrics.compute`
    (it only reads `Trade.open_at_end` and `.return_pct`), so this exists purely so a `ReplayResult`'s
    trades carry a defensible number rather than a placeholder, and a miscount here changes no metric
    this module reports."""
    dates = [session.date for session in calendar]
    try:
        return dates.index(exit_date) - dates.index(entry_date)
    except ValueError:
        return 0


class _OpenLot:
    """One symbol's open position while walking fills in fill-date order -- average-cost, not FIFO
    lots, because `WorkflowOrderRecord` carries no lot id and a workflow book's own no-pyramiding
    convention (see `app.workflow.pipeline`) means a second buy before a sell is the uncommon case
    this module still has to handle sanely, not the common one it optimises for."""

    __slots__ = ("entry_date", "entry_fees", "entry_price", "quantity")

    def __init__(self, *, entry_price: Decimal, entry_date: dt.date, quantity: Decimal, entry_fees: Decimal) -> None:
        self.entry_price = entry_price
        self.entry_date = entry_date
        self.quantity = quantity
        self.entry_fees = entry_fees


def _trades_from_fills(
    fills: list[Fill], *, calendar: SessionCalendar, final_market: AsOfMarket
) -> tuple[MetricsTrade, ...]:
    """Reconstruct `app.backtest.models.Trade` objects from a broker's own fill list, average-cost per
    symbol, in fill-date order. See `_OpenLot`'s docstring for why average cost rather than FIFO lots.

    A sell fully or partially closing a lot always produces one closed `Trade`, sized off the
    quantity actually sold (not the whole lot) -- a partial sell's `return_pct` is priced the same as
    a full one (`(exit_price - entry_price) / entry_price`, net of the sold quantity's own fee share),
    since `return_pct` is a price ratio and does not depend on how much of the lot was sold. Any lot
    still open once every fill has been walked becomes one `open_at_end` trade, marked at
    `final_market`'s close -- falling back to the lot's own entry price (a flat, zero-return mark) when
    the symbol cannot be priced there, the same degrade `run_card._open_at_end_trade`'s sibling code
    path in this module chooses for the identical reason: report something rather than raise.
    """
    lots: dict[str, _OpenLot] = {}
    trades: list[MetricsTrade] = []

    for fill in sorted(fills, key=lambda f: (f.trade_date, f.order_id)):
        lot = lots.get(fill.symbol)
        if fill.side == "buy":
            if lot is None:
                lots[fill.symbol] = _OpenLot(
                    entry_price=fill.price,
                    entry_date=fill.trade_date,
                    quantity=fill.quantity,
                    entry_fees=fill.fees,
                )
            else:
                total_quantity = lot.quantity + fill.quantity
                if total_quantity > 0:
                    lot.entry_price = (
                        lot.entry_price * lot.quantity + fill.price * fill.quantity
                    ) / total_quantity
                lot.quantity = total_quantity
                lot.entry_fees += fill.fees
            continue

        # sell
        if lot is None or lot.quantity <= 0:
            continue  # no open lot to close against -- an order this module never staged; skip it.
        sold = min(fill.quantity, lot.quantity)
        return_pct = float((fill.price - lot.entry_price) / lot.entry_price) if lot.entry_price != 0 else 0.0
        trades.append(
            MetricsTrade(
                entry_date=lot.entry_date,
                entry_price=float(lot.entry_price),
                exit_date=fill.trade_date,
                exit_price=float(fill.price),
                exit_reason=ExitReason.SIGNAL,
                bars_held=_bars_held(lot.entry_date, fill.trade_date, calendar),
                return_pct=return_pct,
                open_at_end=False,
            )
        )
        remaining = lot.quantity - sold
        if remaining <= 0:
            del lots[fill.symbol]
        else:
            lot.quantity = remaining

    last_date = calendar.sessions[-1].date if len(calendar) else None
    for symbol, lot in lots.items():
        if lot.quantity <= 0 or last_date is None:
            continue
        try:
            mark_price = final_market.close(symbol)
        except UnpricedSymbol:
            mark_price = lot.entry_price
        return_pct = float((mark_price - lot.entry_price) / lot.entry_price) if lot.entry_price != 0 else 0.0
        trades.append(
            MetricsTrade(
                entry_date=lot.entry_date,
                entry_price=float(lot.entry_price),
                exit_date=last_date,
                exit_price=float(mark_price),
                exit_reason=ExitReason.END_OF_DATA,
                bars_held=_bars_held(lot.entry_date, last_date, calendar),
                return_pct=return_pct,
                open_at_end=True,
            )
        )
    return tuple(trades)


def run_decision_log(
    orders: list[WorkflowOrderRecord] | tuple[WorkflowOrderRecord, ...],
    *,
    settings: Settings,
    calendar: SessionCalendar,
    mandate: Mandate,
    starting_cash: Decimal,
) -> ReplayResult:
    """Score `orders` -- an arm's decision log -- through a fresh `PaperBroker`, walking `calendar`
    session by session exactly as `app.tournament.runner.run_card` walks its own sessions.

    Each order fills on the session whose `date` equals the record's own `fill_date`, priced against
    an `AsOfMarket` as of the record's own `decision_date` -- the same "decision market, next-session
    fill" pairing `PaperBroker.submit`'s docstring documents and `run_card` builds explicitly per
    session. An order's dollar `notional` is converted to a share count against that decision market's
    close (`_quantity_for_notional`), mirroring `app.workflow.book.execute_pending`'s own sizing step
    -- the one piece of real work this module performs that `run_card` does not need, because a
    `StrategyCard`'s `position_pct` already knows to size in `run_card`'s own units.

    An order whose `symbol` is unpriceable at its `decision_date`, or whose sized quantity comes out
    non-positive, is silently skipped -- no `Order` is ever built for it, mirroring
    `execute_pending`'s own "no `Order` ever constructed" branch for the identical case. This module
    has no `BookState` to write a `reject_reason` onto, so a caller that needs to know *why* an order
    never appears in the resulting equity curve should size and price it before calling.

    An order whose `fill_date` does not equal any of `calendar`'s own session dates is likewise never
    processed -- see this module's docstring for why the caller (the study, in every real use of this
    function) is expected to build `calendar` to cover exactly the decision log's own window.

    Equity is marked once per session, at that session's own close, after that session's orders have
    been submitted -- the same order `run_card` marks in. The returned curve is *not* normalised (each
    point is the broker's real dollar equity); the metrics passed to `app.backtest.metrics.compute`
    are normalised internally, with `starting_cash` prepended as the `equity[0] == 1.0` anchor point,
    for the identical reason `run_card` prepends one (see this module's docstring).

    Always calls `compute(..., annualisable=False)` -- see this module's docstring for why a study
    replay never annualises, regardless of how much data it is ever handed.
    """
    broker = PaperBroker(mandate)

    by_fill_date: dict[dt.date, list[WorkflowOrderRecord]] = defaultdict(list)
    for record in orders:
        by_fill_date[record.fill_date].append(record)

    equity_points: list[EquityPoint] = []
    in_position_flags: list[bool] = []

    for session in calendar:
        due = sorted(by_fill_date.get(session.date, ()), key=lambda r: r.order_id)
        for record in due:
            decision_market = AsOfMarket(as_of=record.decision_date, settings=settings)
            try:
                decision_close = decision_market.close(record.symbol)
            except UnpricedSymbol:
                continue
            quantity = _quantity_for_notional(
                record.notional, decision_close, allow_fractional=mandate.allow_fractional_shares
            )
            if quantity <= 0:
                continue
            side: Literal["buy", "sell"] = record.side
            order = Order(
                order_id=record.order_id,
                session=session.index,
                decided_on=record.decision_date,
                symbol=record.symbol,
                side=side,
                quantity=quantity,
                thesis=record.thesis,
                invalidation=record.invalidation,
                stop_level=record.stop_level,
                regime=record.regime or None,
                conviction=int(record.conviction) if record.conviction is not None else None,
                evidence=record.evidence,
            )
            broker.submit(order, market=decision_market, fill_date=session.date)

        mark_market = AsOfMarket(as_of=session.date, settings=settings)
        equity_points.append(EquityPoint(date=session.date, equity=broker.equity(mark_market)))
        in_position_flags.append(any(q > 0 for q in broker.positions.values()))

    equity_decimal = [starting_cash, *(p.equity for p in equity_points)]
    equity_array = np.array(
        [float(e / starting_cash) for e in equity_decimal], dtype=np.float64
    )
    in_position_array = np.array([False, *in_position_flags], dtype=np.bool_)

    last_session = calendar.sessions[-1] if len(calendar) else None
    final_market = (
        AsOfMarket(as_of=last_session.date, settings=settings)
        if last_session is not None
        else AsOfMarket(as_of=dt.date.today(), settings=settings)
    )
    trades = _trades_from_fills(broker.fills, calendar=calendar, final_market=final_market)

    strategy_metrics = metrics_mod.compute(
        equity_array,
        in_position=in_position_array,
        trades=trades,
        bars_per_year=BARS_PER_YEAR[Interval.DAY],
        annualisable=False,
    )
    strategy_metrics = strategy_metrics.model_copy(
        update={"exposure": _undilute_exposure(strategy_metrics.exposure, len(equity_points))}
    )

    daily_returns = tuple(
        (equity_decimal[i] / equity_decimal[i - 1] - 1)
        for i in range(1, len(equity_decimal))
        if equity_decimal[i - 1] != 0
    )
    if len(daily_returns) >= 2:
        as_floats = np.array([float(r) for r in daily_returns], dtype=np.float64)
        realized_vol = Decimal(str(float(np.std(as_floats))))
    else:
        realized_vol = Decimal(0)

    return ReplayResult(
        equity_curve=tuple(equity_points),
        metrics=strategy_metrics,
        realized_vol=realized_vol,
        daily_returns=daily_returns,
    )

"""Tests for the autopilot paper-desk seat (`app.paperdesk.autopilot`, plus its two seams into
`app.paperdesk.desk` and `app.paperdesk.models`).

**Why this file exists apart from `tests/test_paperdesk.py`.** That file's own docstring already
explains it filters the autopilot seat out of every assertion (`_desks` vs `_all_desks`): it is not a
`StrategyCard`, has no `AgentResult` for `run_card` to return, and its whole point -- reading a
persisted ledger rather than replaying stored bars -- makes it a different thing to test, not a
variant of the same thing. This file is where that different thing gets its own coverage.

**Fixture books are built directly, never through a real workflow run.** `app.paperdesk.autopilot`
reads two things: the persisted `BookState` (via `app.workflow.book.load_book`/`save_book`) and the
workflow run store (`app.agentdesk.store.RunStore`). Every test below writes a `BookState` straight
into a temp store with `save_book` and calls `app.paperdesk.autopilot.build_desk` directly -- the
same "duplicated fakes rather than a cross-file import" convention `tests/test_paperdesk.py`'s module
docstring documents, applied here to `_filled_order`/`_pending_order`/`_rejected_order` builders
copied in spirit from `tests/test_workflow_book.py`'s own fixtures of the same shape.

**`broker_state` is computed from the fixture's own fills, never left disconnected from them.**
`tests/test_workflow_book.py`'s own book builders (`_book_with_orders`) deliberately leave
`broker_state={"cash": "0", ...}` because the tests reading them (`held_lots`, `mark_equity_through`)
never touch `PaperBroker` at all. `autopilot.build_desk` does -- `PaperBroker.from_state(mandate,
book.broker_state)` is where `Desk.cash` and `Desk.positions_value` actually come from -- so a
fixture book here would silently make the equity-identity property meaningless if its `broker_state`
did not actually reflect its own `orders`. `_broker_state_matching_fills` below computes it with the
identical `cash_delta` formula `app.paper.paperbroker.PaperBroker.submit` applies (buy:
`-(price*qty+fees)`; sell: `price*qty-fees`), so a fixture's cash and positions are never out of step
with the fills it claims to have made.

**The trading calendar is real, not faked**, the same way `tests/test_paperdesk.py`'s `_spy_bars`
works: every calendar day in a test's window gets a flat SPY (and, where needed, traded-symbol) bar
written into the temp store via `duck.write_bars`, so `app.paper.marketdata.SessionCalendar` -- which
`app.paperdesk.autopilot._curve_sessions` builds for real -- has real sessions to find. No network,
ever; every bar this file needs is written locally.

**Caches.** `app.paper.marketdata`'s process-wide frame cache is keyed independently of which temp
store a given test's `settings` fixture points at (see `tests/test_paperdesk.py`'s own module
docstring for the same trap), so it is cleared before and after every test. `app.paperdesk.autopilot`
itself is not cached at all -- see that module's own docstring on why the autopilot seat is the one
desk `app.paperdesk.desk._book` re-reads from disk on every request -- so there is no autopilot-side
cache to clear alongside it. `app.paperdesk.desk`'s own in-process run cache is cleared too, since the
one API-level test in this file (`TestApiExposesTheAutopilotSeat`) drives `desk.state()`.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agentdesk.models import run_dir
from app.api import paperdesk as paperdesk_api
from app.config import Settings
from app.db import duck
from app.market.models import BAR_COLUMNS, Interval
from app.paper.marketdata import clear_frame_cache
from app.paper.paperbroker import Mandate
from app.paperdesk import autopilot, desk
from app.tournament.models import DESIGN_THROUGH, AgentResult, Discipline, StrategyCard
from app.tournament.purposes import Purpose
from app.workflow import book as book_mod
from app.workflow.book_models import BookState, WorkflowFillRecord, WorkflowOrderRecord

# ---------------------------------------------------------------------------
# Builders -- small, local, duplicated from tests/test_workflow_book.py and tests/test_paperdesk.py
# rather than imported; see this file's module docstring.
# ---------------------------------------------------------------------------


def _mandate(**overrides: object) -> Mandate:
    fields: dict[str, object] = {
        "persona_id": "autopilot-test",
        "display_name": "Autopilot Test",
        "account_id": "acct-1",
        "account_label": "Test Account",
        "starting_cash": Decimal("60000.00"),
        "allow_fractional_shares": False,
        "max_positions": 6,
        "max_single_name_weight": Decimal("1.00"),
        "min_clip_notional": Decimal("1.00"),
        "min_cash": Decimal("0.00"),
        "settlement_days": 1,
        "slippage_bps": Decimal("0"),
        "commission_per_trade": Decimal("0"),
        "sec_fee_rate": Decimal("0"),
        "taf_per_share": Decimal("0"),
        "taf_cap": Decimal("0"),
    }
    fields.update(overrides)
    return Mandate(**fields)  # type: ignore[arg-type]


def _write_bars(settings: Settings, symbol: str, prices: dict[dt.date, tuple[float, float]]) -> None:
    """One daily `(open, close)` bar per entry in `prices`, written into `settings`'s temp store.
    Copied from `tests/test_paperdesk.py`'s own helper of the same name."""
    dates = sorted(prices)
    opens = [prices[d][0] for d in dates]
    closes = [prices[d][1] for d in dates]
    frame = pd.DataFrame(
        {
            "ts": pd.Series(
                [dt.datetime.combine(d, dt.time.min, tzinfo=dt.UTC) for d in dates],
                dtype="datetime64[us, UTC]",
            ),
            "open": opens,
            "high": [max(o, c) + 5.0 for o, c in zip(opens, closes, strict=True)],
            "low": [min(o, c) - 5.0 for o, c in zip(opens, closes, strict=True)],
            "close": closes,
            "adj_close": closes,
            "volume": [1_000_000] * len(dates),
        },
        columns=list(BAR_COLUMNS),
    )
    with duck.connect() as conn:
        duck.write_bars(conn, settings.bars_dir, symbol, Interval.DAY, frame)


def _flat_bars(start: dt.date, end: dt.date, *, price: float) -> dict[dt.date, tuple[float, float]]:
    """One `(price, price)` bar per calendar day from `start` through `end` inclusive -- weekends
    included, the same "no real trading calendar, only whichever dates a test gives it a bar for"
    convention `tests/test_paperdesk.py`'s `_spy_bars` uses. A flat series is enough to make a symbol
    priceable throughout a window without its exact daily movement mattering to the test."""
    days = (end - start).days + 1
    return {start + dt.timedelta(days=i): (price, price) for i in range(days)}


def _fill(
    *,
    price: str,
    qty: str,
    fees: str = "0",
    filled_at: dt.datetime | None = None,
) -> WorkflowFillRecord:
    return WorkflowFillRecord(
        price=Decimal(price),
        price_source="stored_open",
        qty=Decimal(qty),
        slippage=Decimal("0"),
        fees=Decimal(fees),
        reference_open=Decimal(price),
        filled_at=filled_at or dt.datetime(2026, 1, 1, 13, 30, tzinfo=dt.UTC),
    )


def _filled_order(
    *,
    order_id: str,
    symbol: str,
    side: str = "buy",
    qty: str,
    price: str,
    day: dt.date,
    fees: str = "0",
    filled_at: dt.datetime | None = None,
    regime: str = "risk_on_trend",
    run_id: str = "run-1",
) -> WorkflowOrderRecord:
    """A filled order -- `day` is `fill_date`, the trading session, and `filled_at` (default a fixed
    audit timestamp unrelated to `day`) is the wall-clock stamp `execute_pending` recorded the fill
    at. Keeping the two independent by default is deliberate: see `TestEntryDateIsTheTradingSession`
    below, the regression this file exists partly to guard."""
    return WorkflowOrderRecord(
        order_id=order_id,
        arm="full_workflow",
        agent_card_id="card-1",
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        notional=Decimal(price) * Decimal(qty),
        decision_date=day - dt.timedelta(days=1),
        fill_date=day,
        status="filled",
        regime=regime,
        created_by_run_id=run_id,
        fill=_fill(price=price, qty=qty, fees=fees, filled_at=filled_at),
        reject_reason="",
    )


def _pending_order(
    *,
    order_id: str,
    symbol: str,
    side: str = "buy",
    notional: str,
    decision_date: dt.date,
    fill_date: dt.date,
    regime: str = "risk_on_trend",
    run_id: str = "run-1",
) -> WorkflowOrderRecord:
    return WorkflowOrderRecord(
        order_id=order_id,
        arm="full_workflow",
        agent_card_id="card-1",
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        notional=Decimal(notional),
        decision_date=decision_date,
        fill_date=fill_date,
        status="pending",
        regime=regime,
        created_by_run_id=run_id,
        fill=None,
        reject_reason="",
    )


def _rejected_order(
    *,
    order_id: str,
    symbol: str,
    reason: str,
    side: str = "buy",
    notional: str = "1000.00",
    decision_date: dt.date,
    fill_date: dt.date,
    run_id: str = "run-1",
) -> WorkflowOrderRecord:
    return WorkflowOrderRecord(
        order_id=order_id,
        arm="full_workflow",
        agent_card_id="card-1",
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        notional=Decimal(notional),
        decision_date=decision_date,
        fill_date=fill_date,
        status="rejected",
        regime="",
        created_by_run_id=run_id,
        fill=None,
        reject_reason=reason,
    )


def _broker_state_matching_fills(
    starting_cash: Decimal, orders: tuple[WorkflowOrderRecord, ...]
) -> dict[str, object]:
    """The `PaperBroker.to_state()` shape produced by actually filling `orders`, computed with the
    identical `cash_delta` formula `PaperBroker.submit` applies (buy: `-(price*qty+fees)`; sell:
    `price*qty-fees`), walked in the same `(fill_date, order_id)` order `app.paperdesk.autopilot`
    itself replays fills in. See this file's module docstring for why this must never be left
    disconnected from `orders` the way `tests/test_workflow_book.py`'s own book builder leaves it."""
    cash = starting_cash
    positions: dict[str, Decimal] = {}
    filled = sorted(
        (o for o in orders if o.status == "filled" and o.fill is not None),
        key=lambda o: (o.fill_date, o.order_id),
    )
    for order in filled:
        fill = order.fill
        assert fill is not None
        if order.side == "buy":
            cash -= fill.qty * fill.price + fill.fees
            positions[order.symbol] = positions.get(order.symbol, Decimal(0)) + fill.qty
        else:
            cash += fill.qty * fill.price - fill.fees
            positions[order.symbol] = positions.get(order.symbol, Decimal(0)) - fill.qty
    return {
        "cash": format(cash, "f"),
        "positions": {s: format(q, "f") for s, q in positions.items() if q != 0},
        "unsettled": [],
        "fills": [],
        "rejections": [],
    }


def _book(
    *,
    orders: tuple[WorkflowOrderRecord, ...] = (),
    starting_cash: Decimal = autopilot.AUTOPILOT_STARTING_CASH,
    card_adopted_date: dt.date = dt.date(2026, 1, 1),
    current_card_id: str = "card-1",
    broker_state: dict[str, object] | None = None,
) -> BookState:
    return BookState(
        arm="full_workflow",
        universe_source="screen",
        current_card_id=current_card_id,
        card_adopted_date=card_adopted_date,
        starting_cash=starting_cash,
        broker_state=(
            broker_state
            if broker_state is not None
            else _broker_state_matching_fills(starting_cash, orders)
        ),
        orders=orders,
        equity_curve=(),
        as_of=None,
    )


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    desk.clear_cache()
    clear_frame_cache()
    yield
    desk.clear_cache()
    clear_frame_cache()


# ---------------------------------------------------------------------------
# 1. No book file yet -- a dormant seat, not an error
# ---------------------------------------------------------------------------


class TestDormantSeatIsTheOrdinaryFirstDayState:
    def test_a_missing_book_renders_as_a_flat_starting_equity_seat(self, settings: Settings) -> None:
        """A book that has never been written is `load_book`'s own "freshly seeded" branch, not a
        failure -- the ordinary state for a seat on its first day. A reader must see a real, flat
        $100,000 seat with no holdings, no trades and no staged orders, not an error panel and not a
        seat silently missing from the page."""
        result = autopilot.build_desk(
            settings, as_of=dt.date(2026, 8, 20), benchmark="SPY", mandate=_mandate(), taxable=False
        )

        assert result.kind == "autopilot"
        assert result.starting_equity == autopilot.AUTOPILOT_STARTING_CASH
        assert result.equity == autopilot.AUTOPILOT_STARTING_CASH
        assert result.cash == autopilot.AUTOPILOT_STARTING_CASH
        assert result.positions_value == Decimal("0")
        assert result.holdings == []
        assert result.trades == []
        assert result.staged_orders == []
        assert result.rejections == []
        assert result.rejection_count == 0

    def test_last_run_fields_are_none_when_the_run_store_has_never_recorded_a_run(
        self, settings: Settings
    ) -> None:
        """`AutopilotDescription.last_run_*` describes the most recent *workflow run*, not the book --
        a store that has never recorded one must read as `None` throughout, never as a fabricated
        "no run" sentinel string that a client would have to special-case."""
        result = autopilot.build_desk(
            settings, as_of=dt.date(2026, 8, 20), benchmark="SPY", mandate=_mandate(), taxable=False
        )

        assert result.autopilot is not None
        assert result.autopilot.last_run_id is None
        assert result.autopilot.last_run_state is None
        assert result.autopilot.last_run_at is None
        assert result.autopilot.last_run_outcome is None


# ---------------------------------------------------------------------------
# 2. equity == cash + positions_value, to the cent -- the page's hardest invariant
# ---------------------------------------------------------------------------


class TestEquityIdentity:
    def test_equity_equals_cash_plus_positions_value_across_two_symbols_and_two_lots(
        self, settings: Settings
    ) -> None:
        """`Desk.equity` must equal `Desk.cash + Desk.positions_value` to the cent, and the sum of
        every `Holding.market_value` must equal `Desk.positions_value` to the cent -- both computed
        off the *same* `AsOfMarket` close inside `build_desk` (see that module's own docstring), so a
        divergence here means `_holdings` and `PaperBroker.mark` disagree about what a position is
        worth. Two lots of one symbol (AAA, bought on two different days) plus one lot of a second
        (BBB) is enough to prove the identity survives both multi-lot netting and multi-symbol
        summation, not just the trivial one-lot case."""
        start = dt.date(2026, 6, 1)
        as_of = dt.date(2026, 6, 20)
        _write_bars(settings, "SPY", _flat_bars(dt.date(2026, 5, 15), as_of, price=500.0))
        _write_bars(settings, "AAA", _flat_bars(dt.date(2026, 5, 15), as_of, price=110.0))
        _write_bars(settings, "BBB", _flat_bars(dt.date(2026, 5, 15), as_of, price=55.0))

        orders = (
            _filled_order(order_id="o1", symbol="AAA", qty="10", price="100", day=dt.date(2026, 6, 5)),
            _filled_order(order_id="o2", symbol="AAA", qty="5", price="105", day=dt.date(2026, 6, 10)),
            _filled_order(order_id="o3", symbol="BBB", qty="8", price="50", day=dt.date(2026, 6, 10)),
        )
        book = _book(orders=orders, card_adopted_date=start, starting_cash=Decimal("100000"))
        book_mod.save_book(settings, book)

        result = autopilot.build_desk(
            settings, as_of=as_of, benchmark="SPY", mandate=_mandate(), taxable=False
        )

        assert result.equity == result.cash + result.positions_value
        assert len(result.holdings) == 3  # two AAA lots + one BBB lot
        summed_market_value = sum((h.market_value for h in result.holdings), Decimal(0))
        assert summed_market_value == result.positions_value
        # And the figures are not trivially zero -- the identity is being checked on real money.
        assert result.positions_value > Decimal("0")
        assert result.cash == Decimal("100000") - Decimal("1000") - Decimal("525") - Decimal("400")


# ---------------------------------------------------------------------------
# 3. Entry dates are the trading session, not the wall-clock write timestamp
# ---------------------------------------------------------------------------


class TestEntryDateIsTheTradingSession:
    def test_holding_entry_date_is_fill_date_even_when_filled_at_is_weeks_later(
        self, settings: Settings
    ) -> None:
        """Regression guard for a bug fixed in two places (`app.workflow.book.held_lots` and
        `app.paperdesk.autopilot._closed_trades`, per both functions' own docstrings): a deterministic
        backfill writes many sessions' worth of fills in one pass, so every fill's `filled_at` (a
        wall-clock audit stamp) lands on the day the backfill script ran, not on the trading session
        the order actually filled at. A `Holding.entry_date` read off `filled_at` would date every
        backfilled position to the same day and report `bars_held == 0` for all of them regardless of
        how long they had actually been held.

        The fixture below is exactly that shape: `fill_date` is 2026-08-04, the real trading session,
        but `filled_at` is 2026-09-01 -- four weeks later, and *after* this test's own `as_of`. If the
        bug were present, `entry_date` would read as a date in the future relative to `as_of` and
        `bars_held` would clamp to zero; this test fails loudly in that case rather than passing
        trivially, which is the whole point of not reusing `filled_at` for both fields in the fixture.
        """
        card_adopted = dt.date(2026, 7, 20)
        fill_date = dt.date(2026, 8, 4)
        filled_at = dt.datetime(2026, 9, 1, 8, 30, tzinfo=dt.UTC)
        as_of = dt.date(2026, 8, 20)
        _write_bars(settings, "SPY", _flat_bars(dt.date(2026, 7, 1), as_of, price=500.0))
        _write_bars(settings, "AAA", _flat_bars(dt.date(2026, 7, 1), as_of, price=105.0))

        order = _filled_order(
            order_id="o1", symbol="AAA", qty="10", price="100", day=fill_date, filled_at=filled_at
        )
        book = _book(orders=(order,), card_adopted_date=card_adopted)
        book_mod.save_book(settings, book)

        result = autopilot.build_desk(
            settings, as_of=as_of, benchmark="SPY", mandate=_mandate(), taxable=False
        )

        assert len(result.holdings) == 1
        holding = result.holdings[0]
        assert filled_at.date() != fill_date, "the fixture must actually exercise the two dates diverging"
        assert holding.entry_date == fill_date
        assert holding.entry_date != filled_at.date()
        assert holding.bars_held > 0


# ---------------------------------------------------------------------------
# 3b. A holding's stop / target / time-stop come from the selected card
# ---------------------------------------------------------------------------


class TestHoldingBracketsComeFromTheSelectedCard:
    def test_stop_target_and_time_stop_are_derived_from_the_card_not_left_none(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Once `app.workflow.exits` closes positions on the card's own stop, take-profit and hold
        cap, a holding's row must show the levels it would actually close at -- exactly as every
        rules-desk holding does (`app.paperdesk.desk._holdings`). They were `None` until the exit path
        existed, on the honest grounds that nothing closed a position; leaving them `None` now would
        under-state a risk control the desk genuinely applies, and a reader could not see how close a
        position sits to its stop.

        `stop_price == entry * (1 - stop_loss_pct)`, `target_price` is `None` because this card
        declares no take-profit (a `None` field must stay `None`, never a fabricated level), and
        `sessions_to_time_stop == max_hold_days - bars_held`. The card is monkeypatched in rather than
        written to the real library so the test owns its own thresholds and cannot drift when a real
        card's numbers change."""
        card = _fake_trading_card()  # stop_loss_pct=0.12, take_profit_pct=None, max_hold_days=180
        monkeypatch.setattr(autopilot, "_load_card", lambda agent_id, *, settings: card)

        card_adopted = dt.date(2026, 7, 20)
        fill_date = dt.date(2026, 8, 4)
        as_of = dt.date(2026, 8, 20)
        _write_bars(settings, "SPY", _flat_bars(dt.date(2026, 7, 1), as_of, price=500.0))
        _write_bars(settings, "AAA", _flat_bars(dt.date(2026, 7, 1), as_of, price=100.0))

        order = _filled_order(order_id="o1", symbol="AAA", qty="10", price="100", day=fill_date)
        book = _book(orders=(order,), card_adopted_date=card_adopted, current_card_id=card.agent_id)
        book_mod.save_book(settings, book)

        result = autopilot.build_desk(
            settings, as_of=as_of, benchmark="SPY", mandate=_mandate(), taxable=False
        )

        assert len(result.holdings) == 1
        holding = result.holdings[0]
        assert holding.stop_price == (holding.entry_price * (Decimal(1) - Decimal("0.12"))).quantize(
            Decimal("0.01")
        )
        assert holding.target_price is None
        assert holding.sessions_to_time_stop == 180 - holding.bars_held

    def test_brackets_stay_none_when_no_card_resolves(
        self, settings: Settings
    ) -> None:
        """The other half: a book whose `current_card_id` names no `StrategyCard` (a seat seeded but
        never traded, or a dangling id) leaves every bracket `None`, never invents one. This is the
        same degrade `_exits_policy` makes to `"none"` for the same input, and it must not raise."""
        card_adopted = dt.date(2026, 7, 20)
        fill_date = dt.date(2026, 8, 4)
        as_of = dt.date(2026, 8, 20)
        _write_bars(settings, "SPY", _flat_bars(dt.date(2026, 7, 1), as_of, price=500.0))
        _write_bars(settings, "AAA", _flat_bars(dt.date(2026, 7, 1), as_of, price=100.0))

        order = _filled_order(order_id="o1", symbol="AAA", qty="10", price="100", day=fill_date)
        book = _book(
            orders=(order,), card_adopted_date=card_adopted, current_card_id="no-such-card-xyz"
        )
        book_mod.save_book(settings, book)

        result = autopilot.build_desk(
            settings, as_of=as_of, benchmark="SPY", mandate=_mandate(), taxable=False
        )

        assert len(result.holdings) == 1
        holding = result.holdings[0]
        assert holding.stop_price is None
        assert holding.target_price is None
        assert holding.sessions_to_time_stop is None


# ---------------------------------------------------------------------------
# 4. A pending order is staged, not held
# ---------------------------------------------------------------------------


class TestPendingOrderIsStagedNotHeld:
    def test_a_pending_order_appears_in_staged_orders_and_not_in_holdings(
        self, settings: Settings
    ) -> None:
        """A `"pending"` order has no `Fill` yet -- it must render as an `AutopilotOrder` on
        `Desk.staged_orders`, carrying the symbol, notional, decision date and fill date the plan
        actually named, and must **not** be counted as a `Holding` or contribute to
        `Desk.open_positions`: no share count exists for it yet (sizing happens at fill time, see
        `AutopilotOrder.notional`'s own docstring)."""
        decision_date = dt.date(2026, 1, 10)
        fill_date = dt.date(2026, 1, 11)
        order = _pending_order(
            order_id="run-9-0",
            symbol="CCC",
            notional="2500.00",
            decision_date=decision_date,
            fill_date=fill_date,
        )
        book = _book(orders=(order,), card_adopted_date=decision_date)
        book_mod.save_book(settings, book)

        result = autopilot.build_desk(
            settings, as_of=decision_date, benchmark="SPY", mandate=_mandate(), taxable=False
        )

        assert len(result.staged_orders) == 1
        staged = result.staged_orders[0]
        assert staged.symbol == "CCC"
        assert staged.side == "buy"
        assert staged.notional == Decimal("2500.00")
        assert staged.decision_date == decision_date
        assert staged.fill_date == fill_date
        assert result.holdings == []
        assert result.open_positions == 0


# ---------------------------------------------------------------------------
# 5. Rejections are grouped, and rejection_count is the true total, not the group count
# ---------------------------------------------------------------------------


class TestRejectionGrouping:
    def test_rejections_group_by_reason_and_count_totals_every_order_not_every_group(
        self, settings: Settings
    ) -> None:
        """25 orders refused for the same reason must collapse into one `DeskRejection` group with
        `count == 25`, `detail` capped at 20 (`app.paperdesk.autopilot._MAX_REJECTION_DETAIL`) even
        though 25 reasons were recorded, and `symbols == ["AAA"]` -- not 25 unlabelled duplicate rows.
        A second group under a different reason proves grouping is by reason, and
        `Desk.rejection_count` must equal 25 + 3 = 28, the sum across every group, never `len(groups)
        == 2`."""
        decision_date = dt.date(2026, 2, 1)
        fill_date = dt.date(2026, 2, 2)
        cash_rejections = tuple(
            _rejected_order(
                order_id=f"rej-cash-{i}",
                symbol="AAA",
                reason="insufficient settled cash to cover this buy",
                decision_date=decision_date,
                fill_date=fill_date,
            )
            for i in range(25)
        )
        clip_rejections = tuple(
            _rejected_order(
                order_id=f"rej-clip-{i}",
                symbol="BBB",
                reason="below the mandate's minimum clip size",
                decision_date=decision_date,
                fill_date=fill_date,
            )
            for i in range(3)
        )
        book = _book(orders=cash_rejections + clip_rejections, card_adopted_date=decision_date)
        book_mod.save_book(settings, book)

        result = autopilot.build_desk(
            settings, as_of=fill_date, benchmark="SPY", mandate=_mandate(), taxable=False
        )

        groups = {g.rule: g for g in result.rejections}
        assert set(groups) == {"insufficient_cash", "min_clip"}
        assert groups["insufficient_cash"].count == 25
        assert groups["insufficient_cash"].symbols == ["AAA"]
        assert len(groups["insufficient_cash"].detail) == 20, "detail must be capped, not the full 25"
        assert groups["min_clip"].count == 3
        assert result.rejection_count == 28


# ---------------------------------------------------------------------------
# 6. max_drawdown / capital_exposure -- the seat's own window, and None (never 0.0) under 2 points
# ---------------------------------------------------------------------------


class TestDrawdownAndExposureOverTheSeatsOwnWindow:
    def test_the_curve_starts_at_the_books_own_adoption_date_not_a_later_operator_inception(
        self, settings: Settings
    ) -> None:
        """`_curve_sessions` must measure from `book.card_adopted_date`, never from
        `app.paperdesk.desk.effective_inception` -- an operator override on the desk's own inception
        can move it later than this seat's own book started (see `_curve_sessions`'s own docstring),
        and truncating the seat's curve to that shorter window would silently understate how long it
        has actually been trading. This test moves the desk's inception *later* than the book's
        adoption date and confirms the seat's own curve is unaffected."""
        adopted = dt.date(2026, 3, 1)
        later_operator_inception = dt.date(2026, 3, 15)
        as_of = dt.date(2026, 3, 25)
        _write_bars(settings, "SPY", _flat_bars(dt.date(2026, 2, 10), as_of, price=500.0))
        desk.set_inception(later_operator_inception, settings=settings)

        book = _book(orders=(), card_adopted_date=adopted)
        session_dates = autopilot._curve_sessions(
            book, settings=settings, benchmark="SPY", as_of=as_of
        )

        assert session_dates[0] == adopted
        assert session_dates[0] < later_operator_inception
        assert desk.effective_inception(settings) == later_operator_inception

    def test_an_unpriceable_held_symbol_drops_the_session_entirely_and_exposure_is_none(
        self, settings: Settings
    ) -> None:
        """A session where a held symbol cannot be priced must be dropped from the equity curve
        outright, never kept with a partial or fabricated figure (`_equity_curve`'s own docstring).
        With fewer than two surviving curve points there is no path to compute a drawdown or exposure
        over, so `capital_exposure` must be `None` -- **never `0.0`**, which would misreport "measured
        and found to be zero exposure" instead of "could not be measured at all"."""
        card_adopted = dt.date(2026, 4, 1)
        fill_date = dt.date(2026, 4, 2)
        as_of = dt.date(2026, 4, 6)
        _write_bars(settings, "SPY", _flat_bars(dt.date(2026, 3, 15), as_of, price=500.0))
        # Deliberately no "ZZZ" bars at all -- AsOfMarket.close raises UnpricedSymbol on every session
        # from the fill date onward.

        order = _filled_order(order_id="o1", symbol="ZZZ", qty="10", price="100", day=fill_date)
        book = _book(orders=(order,), card_adopted_date=card_adopted)
        book_mod.save_book(settings, book)

        session_dates = autopilot._curve_sessions(
            book, settings=settings, benchmark="SPY", as_of=as_of
        )
        points, _flags = autopilot._equity_curve(book, settings=settings, session_dates=session_dates)
        assert len(points) < 2, "the fixture must actually exercise the under-two-points branch"

        result = autopilot.build_desk(
            settings, as_of=as_of, benchmark="SPY", mandate=_mandate(), taxable=False
        )
        assert result.capital_exposure is None
        assert result.max_drawdown == Decimal("0")

    def test_two_or_more_priced_sessions_yield_a_real_not_none_exposure_figure(
        self, settings: Settings
    ) -> None:
        """The contrasting happy path to the test above: once a held, fully-priced symbol survives two
        or more sessions on the curve, `capital_exposure` is a real figure, not `None` -- proving the
        `None` result above is specific to the under-two-points/unpriceable case and not a blanket
        default."""
        card_adopted = dt.date(2026, 5, 1)
        fill_date = dt.date(2026, 5, 4)
        as_of = dt.date(2026, 5, 10)
        _write_bars(settings, "SPY", _flat_bars(dt.date(2026, 4, 15), as_of, price=500.0))
        _write_bars(settings, "AAA", _flat_bars(dt.date(2026, 4, 15), as_of, price=100.0))

        order = _filled_order(order_id="o1", symbol="AAA", qty="10", price="100", day=fill_date)
        book = _book(orders=(order,), card_adopted_date=card_adopted)
        book_mod.save_book(settings, book)

        result = autopilot.build_desk(
            settings, as_of=as_of, benchmark="SPY", mandate=_mandate(), taxable=False
        )

        assert result.capital_exposure is not None
        assert isinstance(result.max_drawdown, Decimal)


# ---------------------------------------------------------------------------
# 7. tax -- None when the book is not taxable, a real PaperTaxSummary when it is
# ---------------------------------------------------------------------------


class TestTax:
    def _closed_book(self) -> tuple[BookState, dt.date]:
        buy_fill = dt.date(2026, 2, 2)
        sell_fill = dt.date(2026, 2, 6)
        orders = (
            _filled_order(order_id="o1", symbol="EEE", qty="10", price="20", day=buy_fill),
            _filled_order(order_id="o2", symbol="EEE", side="sell", qty="10", price="25", day=sell_fill),
        )
        return _book(orders=orders, card_adopted_date=dt.date(2026, 2, 1)), sell_fill

    def test_tax_is_none_when_the_book_is_not_taxable_even_with_closed_trades(
        self, settings: Settings
    ) -> None:
        """`taxable=False` (the Roth book's flag) must leave `Desk.tax` at `None` regardless of how
        much realised activity the book actually has -- the gate is the caller's `taxable` flag, not
        "does this book have anything to report"."""
        book, sell_fill = self._closed_book()
        book_mod.save_book(settings, book)

        result = autopilot.build_desk(
            settings, as_of=sell_fill, benchmark="SPY", mandate=_mandate(), taxable=False
        )

        assert result.tax is None

    def test_tax_is_a_real_summary_when_the_book_is_taxable_with_closed_trades(
        self, settings: Settings
    ) -> None:
        """`taxable=True` on a book with a closed round trip must produce a real
        `PaperTaxSummary` computed by the real tax engine (`app.workflow.book.tax_summary` ->
        `app.paper.papertax.summarize_paper_tax`), not a stub. A $20 buy and $25 sell of 10 shares
        with no fees and no wash sale realises exactly a $50.00 gain."""
        book, sell_fill = self._closed_book()
        book_mod.save_book(settings, book)

        result = autopilot.build_desk(
            settings, as_of=sell_fill, benchmark="SPY", mandate=_mandate(), taxable=True
        )

        assert result.tax is not None
        assert result.tax.net_realized_gain == Decimal("50.00")


# ---------------------------------------------------------------------------
# 8. Degradation -- a corrupt book, a missing book, an unreadable run store: no exceptions where
#    the contract says there must not be any.
# ---------------------------------------------------------------------------


class TestDegradesWithoutRaising:
    def test_universe_symbols_is_empty_for_a_missing_book(self, settings: Settings) -> None:
        """No book file at all is the ordinary first-day state (see `load_book`'s own "no file yet"
        branch) -- `universe_symbols` must answer `()`, never raise."""
        assert autopilot.universe_symbols(settings) == ()

    def test_universe_symbols_is_empty_for_a_corrupt_book_and_never_raises(
        self, settings: Settings
    ) -> None:
        """A book file that exists but cannot be parsed must not take down the one fetch sweep
        `universe_symbols` feeds -- it degrades to `()` with a logged warning (see that function's own
        docstring), never an exception a caller has to guard against."""
        path = book_mod.book_path(settings, "full_workflow", universe_source="screen")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not valid json at all", encoding="utf-8")

        assert autopilot.universe_symbols(settings) == ()

    def test_build_desk_propagates_a_corrupt_book_rather_than_masking_it(
        self, settings: Settings
    ) -> None:
        """The mirror image of the two tests above: `build_desk` itself does *not* catch a corrupt
        book -- `load_book` raises `ValueError` and `build_desk`'s own docstring says that propagates
        to the caller (`app.paperdesk.desk._book`, which is where the "log it, turn it into a book
        note, never 500 the page" isolation belongs). This is the "raised error that desk._book
        catches" half of this seat's degrade contract."""
        path = book_mod.book_path(settings, "full_workflow", universe_source="screen")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not valid json at all", encoding="utf-8")

        with pytest.raises(ValueError):
            autopilot.build_desk(
                settings, as_of=dt.date(2026, 3, 20), benchmark="SPY", mandate=_mandate(), taxable=False
            )

    def test_build_desk_degrades_last_run_fields_when_the_run_store_is_unreadable(
        self, settings: Settings
    ) -> None:
        """An unreadable `run.json` in the workflow run store must not take the whole seat down --
        `app.agentdesk.store.RunStore.list_runs` already logs and skips a file it cannot parse (see
        that method's own docstring), so `build_desk` must still return a working, dormant seat with
        `last_run_*` degraded to `None` rather than raising."""
        bad_run_dir = run_dir(settings, "workflow", "corrupt-run")
        bad_run_dir.mkdir(parents=True, exist_ok=True)
        (bad_run_dir / "run.json").write_text("{not valid json at all", encoding="utf-8")

        result = autopilot.build_desk(
            settings, as_of=dt.date(2026, 3, 20), benchmark="SPY", mandate=_mandate(), taxable=False
        )

        assert result.kind == "autopilot"
        assert result.autopilot is not None
        assert result.autopilot.last_run_id is None


# ---------------------------------------------------------------------------
# 9. Through the API -- GET /api/paperdesk/state carries the seat and its two disclosure notes
# ---------------------------------------------------------------------------


def _fake_trading_card() -> StrategyCard:
    return StrategyCard(
        agent_id="fake-card",
        display_name="Fake card",
        discipline=Discipline.MOMENTUM,
        thesis="a test thesis, written before the trading window ran",
        universe=("AAA", "BBB"),
        entry="close > 0",
        exit="close < 0",
        stop_loss_pct=Decimal("0.12"),
        take_profit_pct=None,
        max_hold_days=180,
        max_positions=6,
        position_pct=Decimal("0.15"),
        designed_through=DESIGN_THROUGH,
    )  # type: ignore[arg-type]


def _fake_card_result(card: StrategyCard) -> AgentResult:
    return AgentResult(
        card=card,
        sessions=6,
        starting_equity=Decimal("60000.00"),
        ending_equity=Decimal("60000.00"),
        total_return=Decimal("0"),
        max_drawdown=Decimal("0"),
        trades=(),
        rejections=(),
        benchmark_return=Decimal("0"),
    )  # type: ignore[arg-type]


_API_WINDOW = desk._Window(
    inception=dt.date(2026, 8, 1),
    first_session=dt.date(2026, 8, 1),
    as_of=dt.date(2026, 8, 10),
    decided_on=dt.date(2026, 8, 7),
    sessions=6,
    latest_bar=dt.date(2026, 8, 10),
)


def _install_minimal_roster(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatch the trading desk's card machinery down to one synthetic card, following
    `tests/test_paperdesk.py`'s own `_install` pattern, so `desk.state()` never touches a real
    strategy card or `run_card`. The autopilot seat itself is deliberately left unpatched -- it reads
    the real (empty) temp-rooted store through `app.paperdesk.autopilot.build_desk`, which is exactly
    what proves it needs no real market data to render a dormant seat through the full API stack."""
    card = _fake_trading_card()
    monkeypatch.setattr(desk, "_trading_window", lambda settings: _API_WINDOW)
    monkeypatch.setattr(desk, "_mandate", lambda purpose: _mandate())
    monkeypatch.setattr(desk, "AGENT_IDS", (card.agent_id,))
    monkeypatch.setattr(desk, "SAVINGS_AGENT_IDS", ())
    monkeypatch.setattr(desk, "ROTH_AGENT_IDS", ())
    monkeypatch.setattr(desk, "_load_card", lambda settings, agent_id: card)
    monkeypatch.setattr(
        desk, "run_card", lambda card, *, settings, mandate, start, end: _fake_card_result(card)
    )


class TestApiExposesTheAutopilotSeat:
    def test_state_endpoint_carries_the_autopilot_seat_and_its_two_disclosure_notes(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`GET /api/paperdesk/state` must include the autopilot seat (`kind == "autopilot"`,
        `agent_id == "autopilot-workflow"`) in the trading book's desks, and the trading book's own
        `notes` must carry both disclosures `_autopilot_notes` emits whenever the seat is present: its
        opening capital differs from the book's own, and the inception picker does not move it (see
        that function's own docstring for why both are always true for a dormant seat -- its
        $100,000 starting equity never equals the trading book's own opening capital, and its
        `autopilot` block is always populated)."""
        _install_minimal_roster(monkeypatch)
        app = FastAPI()
        app.include_router(paperdesk_api.router)
        client = TestClient(app)

        body = client.get("/api/paperdesk/state").json()

        assert body != {}
        books = {b["purpose"]: b for b in body["books"]}
        trading = books["trading"]
        autopilot_desks = [d for d in trading["desks"] if d["kind"] == "autopilot"]
        assert len(autopilot_desks) == 1
        seat = autopilot_desks[0]
        assert seat["agent_id"] == "autopilot-workflow"

        notes_text = " ".join(trading["notes"])
        assert "opens with" in notes_text and "not this book's" in notes_text
        assert "inception picker" in notes_text and "does not move it" in notes_text


# ---------------------------------------------------------------------------
# 10. desk.rosters() -- the autopilot id rides last on the trading book, and nowhere else
# ---------------------------------------------------------------------------


class TestRostersPlacesTheAutopilotSeatOnTradingOnly:
    def test_autopilot_id_is_appended_last_to_trading_and_absent_elsewhere(
        self, settings: Settings
    ) -> None:
        """`desk.seats` appends the autopilot id to the trading book, last -- after every card, both
        hand-authored and overlay-promoted -- and to no other book: it is not a `StrategyCard` and
        the savings/Roth rosters must never gain a seat neither of them declared.

        **And `desk.rosters` must not carry it at all.** That is the other half of the property and
        the more important one: `rosters` means "which cards", every one of its callers feeds each id
        straight to `_load_card`, and `app.evolution.promotion`'s own tests assert its exact ordering.
        Putting the seat there (which is how this was first written) silently redefined that function
        for every existing caller and pushed an auto-promoted card one place down the book. Asserting
        both halves here is what stops that being reintroduced."""
        rendered = desk.seats(settings)
        cards_only = desk.rosters(settings)

        assert rendered[Purpose.TRADING][-1] == autopilot.AUTOPILOT_AGENT_ID
        assert autopilot.AUTOPILOT_AGENT_ID not in rendered[Purpose.SAVINGS]
        assert autopilot.AUTOPILOT_AGENT_ID not in rendered[Purpose.ROTH]

        for purpose, ids in cards_only.items():
            assert autopilot.AUTOPILOT_AGENT_ID not in ids, (
                f"the autopilot seat leaked into rosters()[{purpose}] -- every caller of that "
                "function passes each id to _load_card, which cannot resolve a seat that has no card"
            )
        # And `seats` is exactly `rosters` plus that one id: nothing reordered, nothing dropped.
        assert rendered[Purpose.TRADING][:-1] == cards_only[Purpose.TRADING]

    def test_the_seat_flag_off_hides_the_id_and_leaves_the_card_roster_untouched(
        self, settings: Settings
    ) -> None:
        """`Settings.paperdesk_autopilot_seat = False` removes the seat from every book, and -- the
        part that matters -- leaves `seats` exactly equal to `rosters`, the pure card roster. An
        operator who does not want the workflow's paper book on the page gets a desk with only its
        cards, with no other behaviour changed."""
        off = settings.model_copy(update={"paperdesk_autopilot_seat": False})
        rendered = desk.seats(off)

        for ids in rendered.values():
            assert autopilot.AUTOPILOT_AGENT_ID not in ids
        assert rendered == desk.rosters(off)


# ---------------------------------------------------------------------------
# 11. The autopilot source setting selects which workflow book the seat renders
# ---------------------------------------------------------------------------


class TestAutopilotSourceSetting:
    def test_default_source_is_the_screened_full_workflow_book(self, settings: Settings) -> None:
        """The unset default renders the researched, gated pipeline's own screened book -- the
        `(universe_source, arm)` pair the seat exists to show."""
        assert autopilot._resolve_source(settings) == ("screen", "full_workflow")

    def test_an_operator_can_point_the_seat_at_a_different_arm_or_universe(
        self, settings: Settings
    ) -> None:
        """`paperdesk_autopilot_source` moves the seat to any `<card|screen>:<arm>` book without a
        code edit -- the ungated null arm, or the fixed-universe card book -- which is the whole
        reason the setting exists."""
        for raw, expected in (
            ("screen:raw_signal", ("screen", "raw_signal")),
            ("card:full_workflow", ("card", "full_workflow")),
            ("screen:vibe_gated", ("screen", "vibe_gated")),
        ):
            cfg = settings.model_copy(update={"paperdesk_autopilot_source": raw})
            assert autopilot._resolve_source(cfg) == expected

    def test_a_malformed_source_falls_back_to_the_default_book_and_never_raises(
        self, settings: Settings
    ) -> None:
        """A display knob must not be able to crash the page or startup: every malformed value -- no
        colon, an unknown universe, an unknown arm -- pins the seat to the default book instead of
        raising, so the seat always renders *some* real book."""
        for bad in ("garbage-no-colon", "screen:not-an-arm", "wrongsource:full_workflow", "", ":"):
            cfg = settings.model_copy(update={"paperdesk_autopilot_source": bad})
            assert autopilot._resolve_source(cfg) == ("screen", "full_workflow")

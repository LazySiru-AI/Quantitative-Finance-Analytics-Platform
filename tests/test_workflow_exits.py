"""Tests for the workflow's mechanical exit path (`backend/app/workflow/exits.py`).

**Why this module exists, restated for this file's own purpose.** `app.workflow.exits` is what
closes a workflow position -- a card's own stop, target, hold cap or `exit` rule, evaluated exactly
in `app.tournament.runner._decide_exit`'s precedence (stop, then target, then time, then rule) and
staged the same "decide on the close, fill at the next open" way an entry is. Before this module
existed a workflow book only ever bought, so this file's job is to prove each leg of that path holds
on its own: the four ways an exit can fire, the two ways it correctly does not (nothing due, no card
to evaluate against), the two defensive cases (an unpriceable close, a sell already working), and one
full round trip through `execute_pending` that proves the sizing survives contact with the broker.

**Never hits the real network or the real bar store, and never writes into the real card library.**
Bars are written directly into a temp-rooted DuckDB/Parquet store via `_write_bar`, copied in spirit
from `tests/test_workflow_book.py`'s own helper of the same name. `library_dir` is additionally
redirected into this file's own tmp tree (see the local `settings` fixture below) -- the shared
`tests/conftest.py` fixture leaves it at the real, shipped `backend/app/paper/library/`, which is
correct for a test that reads the real seated cards and wrong for this file, which writes throwaway
`StrategyCard` JSON that must never land in the real repo tree.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from app.config import Settings
from app.db import duck
from app.market.models import BAR_COLUMNS, Interval
from app.paper.marketdata import clear_frame_cache
from app.paper.paperbroker import Mandate
from app.tournament.models import Discipline, StrategyCard
from app.workflow import book as workflow_book
from app.workflow.book import _quantity_for_notional
from app.workflow.book_models import BookState, OrderPlan, WorkflowFillRecord, WorkflowOrderRecord
from app.workflow.exits import ExitDecision, plan_exits, stage_due_exits

# ---------------------------------------------------------------------------
# Fixtures and builders -- local to this file, mirroring tests/test_workflow_book.py's convention.
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(settings: Settings, tmp_path: Path) -> Settings:
    """Redirects `library_dir` into this file's own tmp tree -- see the module docstring's second
    paragraph for why the shared fixture cannot be used unmodified here."""
    overridden = settings.model_copy(update={"library_dir": tmp_path / "library"})
    overridden.library_dir.mkdir(parents=True, exist_ok=True)
    return overridden


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    clear_frame_cache()
    yield
    clear_frame_cache()


def _write_bar(settings: Settings, symbol: str, day: dt.date, *, open_: float, close: float) -> None:
    """One daily bar. Copied in spirit from tests/test_workflow_book.py's `_write_bar`."""
    frame = pd.DataFrame(
        {
            "ts": pd.Series(
                [dt.datetime.combine(day, dt.time.min, tzinfo=dt.UTC)],
                dtype="datetime64[us, UTC]",
            ),
            "open": [open_],
            "high": [max(open_, close) + 5.0],
            "low": [min(open_, close) - 5.0],
            "close": [close],
            "adj_close": [close],
            "volume": [1_000_000],
        },
        columns=list(BAR_COLUMNS),
    )
    with duck.connect() as conn:
        duck.write_bars(conn, settings.bars_dir, symbol, Interval.DAY, frame)


def _write_spy_range(settings: Settings, start: dt.date, end: dt.date) -> None:
    """Every calendar day in `[start, end]` gets a flat SPY bar. `SessionCalendar` (which
    `plan_exits` builds to count `bars_held`) keys a session purely off a stored benchmark bar -- see
    that class's own docstring -- so any gap here would silently shrink the session count a lot's age
    is measured against."""
    day = start
    while day <= end:
        _write_bar(settings, "SPY", day, open_=500.0, close=501.0)
        day += dt.timedelta(days=1)


def _card(
    *,
    agent_id: str = "exit-test-card",
    entry: str = "close > 0",
    exit: str = "",
    stop_loss_pct: str | None = None,
    take_profit_pct: str | None = None,
    max_hold_days: int | None = None,
    universe: tuple[str, ...] = ("AAA",),
) -> StrategyCard:
    return StrategyCard(
        agent_id=agent_id,
        display_name="Exit Test Card",
        discipline=Discipline.MOMENTUM,
        thesis="a test thesis",
        falsification="a test falsification",
        universe=universe,
        entry=entry,
        exit=exit,
        stop_loss_pct=Decimal(stop_loss_pct) if stop_loss_pct is not None else None,
        take_profit_pct=Decimal(take_profit_pct) if take_profit_pct is not None else None,
        max_hold_days=max_hold_days,
        max_positions=5,
        position_pct=Decimal("0.15"),
        designed_through=dt.date(2026, 2, 13),
    )


def _write_card(settings: Settings, card: StrategyCard) -> None:
    settings.library_dir.mkdir(parents=True, exist_ok=True)
    (settings.library_dir / f"{card.agent_id}.json").write_text(
        card.model_dump_json(indent=2), encoding="utf-8"
    )


def _filled_buy(
    *,
    order_id: str,
    symbol: str,
    qty: str,
    price: str,
    day: dt.date,
    fees: str = "0",
    arm: str = "full_workflow",
    agent_card_id: str = "card-1",
) -> WorkflowOrderRecord:
    return WorkflowOrderRecord(
        order_id=order_id,
        arm=arm,  # type: ignore[arg-type]
        agent_card_id=agent_card_id,
        symbol=symbol,
        side="buy",
        notional=Decimal(price) * Decimal(qty),
        decision_date=day - dt.timedelta(days=1),
        fill_date=day,
        status="filled",
        thesis="t",
        invalidation="i",
        stop_level=None,
        regime="",
        conviction=None,
        evidence=(),
        created_by_run_id="seed-run",
        fill=WorkflowFillRecord(
            price=Decimal(price),
            price_source="stored_open",
            qty=Decimal(qty),
            slippage=Decimal("0"),
            fees=Decimal(fees),
            reference_open=Decimal(price),
            filled_at=dt.datetime.combine(day, dt.time(13, 30), tzinfo=dt.UTC),
        ),
        reject_reason="",
    )


def _pending_sell(
    *,
    order_id: str,
    symbol: str,
    decision_date: dt.date,
    fill_date: dt.date,
    notional: str = "500.00",
    arm: str = "full_workflow",
    agent_card_id: str = "card-1",
) -> WorkflowOrderRecord:
    return WorkflowOrderRecord(
        order_id=order_id,
        arm=arm,  # type: ignore[arg-type]
        agent_card_id=agent_card_id,
        symbol=symbol,
        side="sell",
        notional=Decimal(notional),
        decision_date=decision_date,
        fill_date=fill_date,
        status="pending",
        thesis="t",
        invalidation="i",
        stop_level=None,
        regime="",
        conviction=None,
        evidence=(),
        created_by_run_id="seed-run",
        fill=None,
        reject_reason="",
    )


def _book(
    orders: tuple[WorkflowOrderRecord, ...],
    *,
    current_card_id: str,
    arm: str = "full_workflow",
    card_adopted_date: dt.date = dt.date(2026, 3, 1),
) -> BookState:
    return BookState(
        arm=arm,  # type: ignore[arg-type]
        current_card_id=current_card_id,
        card_adopted_date=card_adopted_date,
        starting_cash=Decimal("100000"),
        broker_state={"cash": "100000", "positions": {}, "unsettled": [], "fills": [], "rejections": []},
        orders=orders,
        equity_curve=(),
        as_of=None,
    )


def _mandate(**overrides: object) -> Mandate:
    """Copied in spirit from tests/test_workflow_book.py's own `_mandate`."""
    fields: dict[str, object] = {
        "persona_id": "workflow-exits-test",
        "display_name": "Workflow Exits Test",
        "account_id": "workflow-exits-acct",
        "account_label": "Workflow Exits Test Account",
        "starting_cash": Decimal("100000.00"),
        "allow_fractional_shares": False,
        "max_positions": 10,
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


def _buy_plan(*, symbol: str, notional: str = "1000.00") -> OrderPlan:
    return OrderPlan(
        agent_card_id="ignored",
        symbol=symbol,
        side="buy",
        notional=Decimal(notional),
        thesis="a thesis",
        invalidation="an invalidation",
    )


# ---------------------------------------------------------------------------
# 1. Brackets: stop, target, and stop-wins-over-target precedence
# ---------------------------------------------------------------------------


class TestBracketExits:
    """A stop or a target must fire exactly at the card's own threshold, and when both would fire on
    the same close, the stop must win -- `app.tournament.runner._decide_exit`'s own precedence. Get
    either wrong and a position that should have been cut at a loss instead rides a bracket that never
    fires, or fires on the wrong side."""

    def test_a_stop_fires_and_resizes_to_the_exact_held_quantity(self, settings: Settings) -> None:
        card = _card(agent_id="stop-card", stop_loss_pct="0.10", take_profit_pct="0.20")
        _write_card(settings, card)
        acquired = dt.date(2026, 3, 2)
        today = dt.date(2026, 3, 9)
        _write_spy_range(settings, acquired - dt.timedelta(days=12), today)
        _write_bar(settings, "AAA", today, open_=90.00, close=89.00)  # <= 90.00 stop threshold

        lot = _filled_buy(order_id="o1", symbol="AAA", qty="10", price="100", day=acquired)
        book = _book((lot,), current_card_id="stop-card")

        plans, decisions = plan_exits(book, settings=settings, today=today, allow_fractional=False)

        assert len(plans) == 1
        plan = plans[0]
        assert plan.symbol == "AAA"
        assert plan.side == "sell"
        assert plan.notional == Decimal("934.50")  # (10 + 0.5) * 89.00
        assert _quantity_for_notional(
            plan.notional, Decimal("89.00"), allow_fractional=False
        ) == Decimal("10")
        assert decisions == [ExitDecision(symbol="AAA", reason="stop", quantity=Decimal("10"))]

    def test_a_take_profit_fires_and_resizes_to_the_exact_held_quantity(
        self, settings: Settings
    ) -> None:
        card = _card(agent_id="target-card", stop_loss_pct="0.10", take_profit_pct="0.20")
        _write_card(settings, card)
        acquired = dt.date(2026, 3, 2)
        today = dt.date(2026, 3, 9)
        _write_spy_range(settings, acquired - dt.timedelta(days=12), today)
        _write_bar(settings, "AAA", today, open_=124.00, close=125.00)  # >= 120.00 target threshold

        lot = _filled_buy(order_id="o1", symbol="AAA", qty="10", price="100", day=acquired)
        book = _book((lot,), current_card_id="target-card")

        plans, decisions = plan_exits(book, settings=settings, today=today, allow_fractional=False)

        assert len(plans) == 1
        plan = plans[0]
        assert plan.notional == Decimal("1312.50")  # (10 + 0.5) * 125.00
        assert _quantity_for_notional(
            plan.notional, Decimal("125.00"), allow_fractional=False
        ) == Decimal("10")
        assert decisions == [ExitDecision(symbol="AAA", reason="target", quantity=Decimal("10"))]

    def test_when_both_the_stop_and_the_target_trip_on_the_same_close_the_stop_wins(
        self, settings: Settings
    ) -> None:
        # A stop threshold of 95.00 and a target threshold of 90.00 (achieved with a negative
        # take_profit_pct, unusual but not forbidden by the model) both sit below entry, so a single
        # close of 92.00 trips both at once -- exactly the case `_decide_exit`'s "stop, then target"
        # order exists to resolve.
        card = _card(agent_id="both-card", stop_loss_pct="0.05", take_profit_pct="-0.10")
        _write_card(settings, card)
        acquired = dt.date(2026, 3, 2)
        today = dt.date(2026, 3, 9)
        _write_spy_range(settings, acquired - dt.timedelta(days=12), today)
        _write_bar(settings, "AAA", today, open_=93.00, close=92.00)

        lot = _filled_buy(order_id="o1", symbol="AAA", qty="5", price="100", day=acquired)
        book = _book((lot,), current_card_id="both-card")

        plans, decisions = plan_exits(book, settings=settings, today=today, allow_fractional=False)

        assert len(plans) == 1
        assert decisions == [ExitDecision(symbol="AAA", reason="stop", quantity=Decimal("5"))]


# ---------------------------------------------------------------------------
# 2. Time stop
# ---------------------------------------------------------------------------


class TestTimeStopExits:
    def test_a_time_stop_fires_once_bars_held_reaches_max_hold_days(self, settings: Settings) -> None:
        """A card with no bracket must still close a position once it has been held long enough --
        `max_hold_days` is the backstop `StrategyCard`'s own docstring calls out ("a strategy with no
        exit rule, no target and no time stop can hold forever"). Breaking `_bars_held`'s session
        count (off by one, or counting the acquisition day itself) would fire this a session early or
        late."""
        card = _card(agent_id="time-card", max_hold_days=5)
        _write_card(settings, card)
        acquired = dt.date(2026, 3, 2)
        today = acquired + dt.timedelta(days=6)  # 6 sessions elapsed (calendar days) >= 5
        _write_spy_range(settings, acquired - dt.timedelta(days=12), today)
        _write_bar(settings, "AAA", today, open_=104.00, close=105.00)

        lot = _filled_buy(order_id="o1", symbol="AAA", qty="8", price="100", day=acquired)
        book = _book((lot,), current_card_id="time-card")

        plans, decisions = plan_exits(book, settings=settings, today=today, allow_fractional=False)

        assert len(plans) == 1
        plan = plans[0]
        assert plan.notional == Decimal("892.50")  # (8 + 0.5) * 105.00
        assert _quantity_for_notional(
            plan.notional, Decimal("105.00"), allow_fractional=False
        ) == Decimal("8")
        assert decisions == [ExitDecision(symbol="AAA", reason="time", quantity=Decimal("8"))]


# ---------------------------------------------------------------------------
# 3. Exit rule
# ---------------------------------------------------------------------------


class TestRuleExits:
    def test_the_cards_exit_expression_fires_with_no_bracket_or_time_stop_set(
        self, settings: Settings
    ) -> None:
        """A card need not carry a bracket or a hold cap at all -- its `exit` rule alone must be able
        to close a position. Evaluated the same way the entry rule is (last value, NaN read as
        `False`, see `_exit_rule_fires`'s own docstring), so this also exercises that the rule sees
        the same bars an entry scan would."""
        card = _card(agent_id="rule-card", exit="close < sma(3)")
        _write_card(settings, card)
        day1 = dt.date(2026, 3, 2)  # acquisition
        day2 = day1 + dt.timedelta(days=1)
        day3 = day1 + dt.timedelta(days=2)
        today = day1 + dt.timedelta(days=3)
        _write_spy_range(settings, day1 - dt.timedelta(days=12), today)
        _write_bar(settings, "AAA", day1, open_=99.00, close=100.00)
        _write_bar(settings, "AAA", day2, open_=100.00, close=102.00)
        _write_bar(settings, "AAA", day3, open_=102.00, close=104.00)
        _write_bar(settings, "AAA", today, open_=95.00, close=90.00)  # sma(3) over [102,104,90] ~98.67

        lot = _filled_buy(order_id="o1", symbol="AAA", qty="6", price="100", day=day1)
        book = _book((lot,), current_card_id="rule-card")

        plans, decisions = plan_exits(book, settings=settings, today=today, allow_fractional=False)

        assert len(plans) == 1
        plan = plans[0]
        assert plan.notional == Decimal("585.00")  # (6 + 0.5) * 90.00
        assert _quantity_for_notional(
            plan.notional, Decimal("90.00"), allow_fractional=False
        ) == Decimal("6")
        assert decisions == [ExitDecision(symbol="AAA", reason="rule", quantity=Decimal("6"))]


# ---------------------------------------------------------------------------
# 4. Nothing fires
# ---------------------------------------------------------------------------


class TestNothingFires:
    def test_a_held_position_inside_every_threshold_is_recorded_as_hold_and_stage_due_exits_is_a_noop(
        self, settings: Settings
    ) -> None:
        card = _card(
            agent_id="hold-card", stop_loss_pct="0.5", take_profit_pct="0.5", max_hold_days=100
        )
        _write_card(settings, card)
        acquired = dt.date(2026, 3, 2)
        today = dt.date(2026, 3, 5)
        _write_spy_range(settings, acquired - dt.timedelta(days=12), today)
        _write_bar(settings, "AAA", today, open_=109.00, close=110.00)  # inside [50, 150]

        lot = _filled_buy(order_id="o1", symbol="AAA", qty="10", price="100", day=acquired)
        book = _book((lot,), current_card_id="hold-card")

        plans, decisions = plan_exits(book, settings=settings, today=today, allow_fractional=False)
        assert plans == []
        assert decisions == [ExitDecision(symbol="AAA", reason="hold", quantity=Decimal("10"))]

        staged, staged_decisions = stage_due_exits(
            book, settings=settings, today=today, allow_fractional=False
        )
        assert staged is book, "a no-op day must return the exact same book, not an equal copy"
        assert staged_decisions == decisions


# ---------------------------------------------------------------------------
# 5. No card
# ---------------------------------------------------------------------------


class TestNoCard:
    """A book seeded but never traded (`current_card_id == ""`), or one whose card id resolves to no
    file, must degrade to "nothing to close" -- never raise, and never be confused for a book with
    nothing held (see `TestNothingFires` above for that separate case)."""

    def test_an_empty_current_card_id_yields_no_plans_and_no_decisions(
        self, settings: Settings
    ) -> None:
        lot = _filled_buy(order_id="o1", symbol="AAA", qty="10", price="100", day=dt.date(2026, 3, 2))
        book = _book((lot,), current_card_id="")

        plans, decisions = plan_exits(
            book, settings=settings, today=dt.date(2026, 3, 5), allow_fractional=False
        )
        assert plans == []
        assert decisions == []

    def test_a_current_card_id_naming_no_file_yields_no_plans_and_no_decisions(
        self, settings: Settings
    ) -> None:
        lot = _filled_buy(order_id="o1", symbol="AAA", qty="10", price="100", day=dt.date(2026, 3, 2))
        book = _book((lot,), current_card_id="no-such-card")

        plans, decisions = plan_exits(
            book, settings=settings, today=dt.date(2026, 3, 5), allow_fractional=False
        )
        assert plans == []
        assert decisions == []


# ---------------------------------------------------------------------------
# 6. Unpriceable held symbol
# ---------------------------------------------------------------------------


class TestUnpriceableHeldSymbol:
    def test_a_firing_time_stop_with_no_stored_close_is_recorded_unpriceable_not_dropped(
        self, settings: Settings
    ) -> None:
        """A held symbol with no stored bar at all cannot be sized into a sell -- `plan_exits` must
        still record that the exit fired (via `reason="unpriceable"`), rather than silently treating
        it as `"hold"`, so the position is retried the next session instead of quietly staying open
        forever with no audit trail of why."""
        card = _card(agent_id="unpriceable-card", max_hold_days=1)
        _write_card(settings, card)
        acquired = dt.date(2026, 3, 2)
        today = acquired + dt.timedelta(days=2)  # bars_held=2 >= 1
        _write_spy_range(settings, acquired - dt.timedelta(days=12), today)
        # No ZZZ bar is ever written.

        lot = _filled_buy(order_id="o1", symbol="ZZZ", qty="4", price="100", day=acquired)
        book = _book((lot,), current_card_id="unpriceable-card")

        plans, decisions = plan_exits(book, settings=settings, today=today, allow_fractional=False)

        assert plans == []
        assert decisions == [ExitDecision(symbol="ZZZ", reason="unpriceable", quantity=Decimal("4"))]

        staged, _ = stage_due_exits(book, settings=settings, today=today, allow_fractional=False)
        assert staged is book


# ---------------------------------------------------------------------------
# 7. No double-sell
# ---------------------------------------------------------------------------


class TestNoDoubleSell:
    def test_a_symbol_with_a_pending_sell_already_working_is_not_staged_a_second_time(
        self, settings: Settings
    ) -> None:
        """A stop that stays triggered across several sessions must not stack a fresh pending sell
        every day -- one working sell per symbol is enough, and the broker would reject every one
        past the first as a short. Breaking this looks like a book accumulating duplicate pending
        sells for the same position."""
        card = _card(agent_id="dupe-card", stop_loss_pct="0.10", take_profit_pct="0.20")
        _write_card(settings, card)
        acquired = dt.date(2026, 3, 2)
        today = dt.date(2026, 3, 9)
        _write_spy_range(settings, acquired - dt.timedelta(days=12), today)
        _write_bar(settings, "AAA", today, open_=81.00, close=80.00)  # well past the 90.00 stop

        lot = _filled_buy(order_id="o1", symbol="AAA", qty="10", price="100", day=acquired)
        pending_sell = _pending_sell(
            order_id="p1",
            symbol="AAA",
            decision_date=today - dt.timedelta(days=1),
            fill_date=today + dt.timedelta(days=1),
        )
        book = _book((lot, pending_sell), current_card_id="dupe-card")

        plans, decisions = plan_exits(book, settings=settings, today=today, allow_fractional=False)

        assert plans == []
        assert decisions == [ExitDecision(symbol="AAA", reason="hold", quantity=Decimal("10"))]


# ---------------------------------------------------------------------------
# 8. Round trip through execute_pending
# ---------------------------------------------------------------------------


class TestStageDueExitsRoundTripsThroughExecutePending:
    def test_a_staged_stop_sell_fills_next_session_and_closes_the_position(
        self, settings: Settings
    ) -> None:
        """The property under test is the whole path working end to end: a card's stop decides a
        sell against today's close, `stage_due_exits` stages it for the next session's open exactly
        like an entry, and `execute_pending` fills it there, reducing the book's held position by the
        sold quantity. If any leg of this -- the sizing buffer in `plan_exits`, the fill-date pairing
        in `stage_due_exits`, or `execute_pending`'s own next-open fill -- disagreed with the others,
        this is where it would show up as an over-sell, a short rejection, or a lot that never
        actually closes."""
        agent_id = "roundtrip-stop-card"
        card = _card(agent_id=agent_id, stop_loss_pct="0.10", take_profit_pct="0.50", max_hold_days=60)
        _write_card(settings, card)

        decision_date = dt.date(2026, 3, 2)
        fill_date = dt.date(2026, 3, 3)  # the lot's acquired date
        today = dt.date(2026, 3, 10)  # the exit is decided here
        exit_fill_date = today + dt.timedelta(days=1)

        _write_spy_range(settings, fill_date - dt.timedelta(days=12), exit_fill_date)
        _write_bar(settings, "AAA", decision_date, open_=99.00, close=100.00)
        _write_bar(settings, "AAA", fill_date, open_=100.00, close=100.00)
        _write_bar(settings, "AAA", today, open_=90.00, close=85.00)  # <= 90.00 stop threshold
        _write_bar(settings, "AAA", exit_fill_date, open_=84.00, close=84.00)

        mandate = _mandate()
        book = workflow_book.load_book(
            settings,
            "raw_signal",
            starting_cash=mandate.starting_cash,
            card_id=agent_id,
            card_adopted_date=decision_date,
        )
        book = workflow_book.stage_orders(
            book,
            [_buy_plan(symbol="AAA")],
            decision_date=decision_date,
            fill_date=fill_date,
            run_id="seed-buy",
        )
        book, buy_outcome = workflow_book.execute_pending(
            book, settings=settings, mandate=mandate, today=fill_date
        )
        assert buy_outcome.filled == 1
        held_before = workflow_book.held_lots(book)
        assert len(held_before) == 1
        qty_held = held_before[0].quantity

        staged, decisions = stage_due_exits(
            book, settings=settings, today=today, allow_fractional=mandate.allow_fractional_shares
        )
        assert [d.reason for d in decisions] == ["stop"]
        sell_orders = [order for order in staged.orders if order.side == "sell"]
        assert len(sell_orders) == 1
        sell = sell_orders[0]
        assert sell.status == "pending"
        assert sell.symbol == "AAA"
        assert sell.decision_date == today
        assert sell.fill_date == exit_fill_date

        filled_book, outcome = workflow_book.execute_pending(
            staged, settings=settings, mandate=mandate, today=exit_fill_date
        )
        assert outcome.filled == 1
        assert outcome.rejected == 0
        filled_sell = next(order for order in filled_book.orders if order.side == "sell")
        assert filled_sell.status == "filled"
        assert filled_sell.fill is not None
        assert filled_sell.fill.qty == qty_held

        remaining = workflow_book.held_lots(filled_book)
        assert remaining == (), "the whole lot must be sold, closing the position entirely"

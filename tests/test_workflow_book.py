"""Tests for the persistent per-arm paper trade ledger (`backend/app/workflow/book.py`,
`backend/app/workflow/book_models.py`).

**Never hits the real network or the real bar store.** Every bar this file needs is written directly
into a temp-rooted DuckDB/Parquet store via `_write_bar` -- copied in spirit from
`tests/test_paper_live_fill.py`'s own helper of the same name, which is this repo's established
pattern for a paper-broker test fixture (see that file's module docstring). `tests/conftest.py` does
not expose a shared market/calendar/mandate builder for this layer -- `test_paper_live_fill.py` builds
its own locally rather than adding one, and this file follows the same convention.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

import pandas as pd
import pytest

from app.config import Settings
from app.db import duck
from app.market.live import LiveQuote, LiveQuoteError, LiveSnapshot
from app.market.models import BAR_COLUMNS, Interval
from app.paper.marketdata import clear_frame_cache
from app.paper.paperbroker import Mandate
from app.workflow import book as workflow_book
from app.workflow.book_models import BookState, OrderPlan, WorkflowFillRecord, WorkflowOrderRecord

# ---------------------------------------------------------------------------
# Builders -- local to this file, mirroring tests/test_paper_live_fill.py's own convention.
# ---------------------------------------------------------------------------


def _mandate(**overrides: object) -> Mandate:
    fields: dict[str, object] = {
        "persona_id": "workflow-test",
        "display_name": "Workflow Test",
        "account_id": "workflow-acct",
        "account_label": "Workflow Test Account",
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


def _write_bar(settings: Settings, symbol: str, day: dt.date, *, open_: float, close: float) -> None:
    """One daily bar. Copied in spirit from tests/test_paper_live_fill.py's `_write_bar`."""
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


class _StubLiveQuoteSource:
    """A fake `app.market.live.LiveQuoteSource` -- no network, ever. Copied in spirit from
    tests/test_paper_live_fill.py's stub of the same name."""

    def __init__(self, prices: dict[str, Decimal]) -> None:
        self._prices = prices
        self.calls: list[tuple[str, ...]] = []

    def snapshot(self, symbols: list[str]) -> LiveSnapshot:
        self.calls.append(tuple(symbols))
        now = dt.datetime.now(dt.UTC)
        quotes: list[LiveQuote] = []
        errors: list[LiveQuoteError] = []
        for symbol in symbols:
            price = self._prices.get(symbol.upper())
            if price is None:
                errors.append(LiveQuoteError(symbol=symbol, message="no stub price configured"))
                continue
            quotes.append(
                LiveQuote(
                    symbol=symbol.upper(),
                    price=price,
                    previous_close=None,
                    change=None,
                    change_pct=None,
                    ts=now,
                    stale=False,
                    source="stub",
                )
            )
        return LiveSnapshot(
            as_of=now,
            market_state="REGULAR",
            transport="poll",
            healthy=True,
            quotes=tuple(quotes),
            errors=tuple(errors),
        )

    def close(self) -> None:
        pass


def _plan(
    *,
    symbol: str,
    notional: str = "1000.00",
    side: str = "buy",
    thesis: str = "a test thesis",
    invalidation: str = "a test invalidation",
    agent_card_id: str = "card-1",
) -> OrderPlan:
    return OrderPlan(
        agent_card_id=agent_card_id,
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        notional=Decimal(notional),
        thesis=thesis,
        invalidation=invalidation,
    )


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    clear_frame_cache()
    yield
    clear_frame_cache()


# ---------------------------------------------------------------------------
# 1. Round trip with Decimal fidelity
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_book_state_round_trips_through_save_and_load_with_decimal_fidelity(
        self, settings: Settings
    ) -> None:
        fill = WorkflowFillRecord(
            price=Decimal("123.45"),
            price_source="stored_open",
            qty=Decimal("7"),
            slippage=Decimal("0.12"),
            fees=Decimal("1.03"),
            reference_open=Decimal("123.33"),
            filled_at=dt.datetime(2026, 3, 3, 13, 30, tzinfo=dt.UTC),
        )
        order = WorkflowOrderRecord(
            order_id="run-1-0",
            arm="raw_signal",
            agent_card_id="card-1",
            symbol="AAA",
            side="buy",
            notional=Decimal("999.99"),
            decision_date=dt.date(2026, 3, 2),
            fill_date=dt.date(2026, 3, 3),
            status="filled",
            thesis="a thesis",
            invalidation="an invalidation",
            stop_level=Decimal("50.005"),
            regime="risk_on",
            conviction=Decimal("0.8"),
            evidence=("headline-1",),
            created_by_run_id="run-1",
            fill=fill,
            reject_reason="",
        )
        book = BookState(
            arm="raw_signal",
            current_card_id="card-1",
            card_adopted_date=dt.date(2026, 3, 1),
            starting_cash=Decimal("100000.00"),
            broker_state={
                "cash": "99123.45",
                "positions": {"AAA": "7"},
                "unsettled": [],
                "fills": [],
                "rejections": [],
            },
            orders=(order,),
            equity_curve=(),
            as_of=dt.date(2026, 3, 3),
        )

        workflow_book.save_book(settings, book)
        loaded = workflow_book.load_book(
            settings, "raw_signal", starting_cash=Decimal("1"), card_id="ignored"
        )

        assert loaded == book
        assert loaded.orders[0].fill is not None
        assert loaded.orders[0].fill.price == Decimal("123.45")
        assert str(loaded.orders[0].fill.price) == "123.45"
        assert loaded.orders[0].stop_level == Decimal("50.005")
        assert loaded.starting_cash == Decimal("100000.00")

        # And the file on disk really did carry the price as a decimal string, never a JSON number.
        raw = json.loads(workflow_book.book_path(settings, "raw_signal").read_text(encoding="utf-8"))
        assert raw["orders"][0]["fill"]["price"] == "123.45"


def _filled_order(
    *, order_id: str, symbol: str, side: str, qty: str, price: str, day: dt.date, fees: str = "0"
) -> WorkflowOrderRecord:
    return WorkflowOrderRecord(
        order_id=order_id,
        arm="full_workflow",
        agent_card_id="card-1",
        symbol=symbol,
        side=side,
        notional=Decimal(price) * Decimal(qty),
        decision_date=day - dt.timedelta(days=1),
        fill_date=day,
        status="filled",
        thesis="t",
        invalidation="i",
        stop_level=None,
        regime="risk_on_trend",
        conviction=None,
        evidence=(),
        created_by_run_id="run-1",
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


def _book_with_orders(orders: tuple[WorkflowOrderRecord, ...]) -> BookState:
    return BookState(
        arm="full_workflow",
        current_card_id="card-1",
        card_adopted_date=dt.date(2026, 3, 1),
        starting_cash=Decimal("100000"),
        broker_state={"cash": "0", "positions": {}, "unsettled": [], "fills": [], "rejections": []},
        orders=orders,
        equity_curve=(),
        as_of=None,
    )


class TestHeldLots:
    """`held_lots` is what makes the tax switch check real -- it must carry each open lot's true
    acquisition date, which the broker's netted position map cannot, and it must FIFO-retire lots on a
    sell so a partially-closed position reports only what is still held."""

    def test_open_buys_become_one_lot_each_with_their_own_acquisition_date(self) -> None:
        book = _book_with_orders((
            _filled_order(order_id="o1", symbol="AAA", side="buy", qty="10", price="100",
                          day=dt.date(2026, 3, 3), fees="1"),
            _filled_order(order_id="o2", symbol="AAA", side="buy", qty="5", price="120",
                          day=dt.date(2026, 4, 1)),
            _filled_order(order_id="o3", symbol="BBB", side="buy", qty="2", price="50",
                          day=dt.date(2026, 3, 3)),
        ))
        lots = workflow_book.held_lots(book)

        by_key = {(lot.symbol, lot.acquired_date): lot for lot in lots}
        assert len(lots) == 3
        assert by_key[("AAA", dt.date(2026, 3, 3))].quantity == Decimal("10")
        # cost basis carries the entry fee: 10*100 + 1
        assert by_key[("AAA", dt.date(2026, 3, 3))].cost_basis == Decimal("1001.00")
        assert by_key[("AAA", dt.date(2026, 4, 1))].quantity == Decimal("5")
        assert by_key[("BBB", dt.date(2026, 3, 3))].quantity == Decimal("2")

    def test_a_sell_retires_the_oldest_lot_first(self) -> None:
        book = _book_with_orders((
            _filled_order(order_id="o1", symbol="AAA", side="buy", qty="10", price="100",
                          day=dt.date(2026, 3, 3)),
            _filled_order(order_id="o2", symbol="AAA", side="buy", qty="10", price="120",
                          day=dt.date(2026, 4, 1)),
            _filled_order(order_id="o3", symbol="AAA", side="sell", qty="12", price="130",
                          day=dt.date(2026, 5, 1)),
        ))
        lots = workflow_book.held_lots(book)

        # The 3/3 lot is fully consumed; 8 of the 4/1 lot remain.
        assert len(lots) == 1
        (lot,) = lots
        assert lot.acquired_date == dt.date(2026, 4, 1)
        assert lot.quantity == Decimal("8")

    def test_pending_and_rejected_orders_are_not_lots(self) -> None:
        pending = _filled_order(order_id="p", symbol="AAA", side="buy", qty="5", price="100",
                                day=dt.date(2026, 3, 3)).model_copy(update={"status": "pending", "fill": None})
        book = _book_with_orders((pending,))
        assert workflow_book.held_lots(book) == ()

    def test_load_book_returns_a_fresh_seeded_book_when_the_file_is_absent(
        self, settings: Settings
    ) -> None:
        book = workflow_book.load_book(
            settings,
            "ta_gated",
            starting_cash=Decimal("50000.00"),
            card_id="card-x",
            card_adopted_date=dt.date(2026, 1, 1),
        )

        assert book.orders == ()
        assert book.equity_curve == ()
        assert book.as_of is None
        assert book.starting_cash == Decimal("50000.00")
        assert book.current_card_id == "card-x"
        assert Decimal(book.broker_state["cash"]) == Decimal("50000.00")
        assert not workflow_book.book_path(settings, "ta_gated").exists(), (
            "load_book must not write anything to disk on its own -- only save_book does"
        )


# ---------------------------------------------------------------------------
# 1b. universe_source: screen books resolve under book/screen/, card books are unchanged
# ---------------------------------------------------------------------------


class TestUniverseSourceBookLayout:
    def test_card_book_path_is_the_exact_unchanged_path(self, settings: Settings) -> None:
        path = workflow_book.book_path(settings, "raw_signal")
        assert path == workflow_book.book_path(settings, "raw_signal", universe_source="card")
        assert path.name == "raw_signal.json"
        assert path.parent.name == "book"

    def test_screen_book_path_is_a_subdirectory_not_a_filename_suffix(
        self, settings: Settings
    ) -> None:
        path = workflow_book.book_path(settings, "raw_signal", universe_source="screen")
        assert path.name == "raw_signal.json"
        assert path.parent.name == "screen"
        assert path.parent.parent.name == "book"
        # never collides with the card-mode file at the same arm name
        assert path != workflow_book.book_path(settings, "raw_signal", universe_source="card")

    def test_a_saved_screen_book_round_trips_through_load_at_the_screen_path(
        self, settings: Settings
    ) -> None:
        book = workflow_book.load_book(
            settings,
            "full_workflow",
            starting_cash=Decimal("100000.00"),
            card_id="card-1",
            universe_source="screen",
        )
        assert book.universe_source == "screen"
        workflow_book.save_book(settings, book)

        screen_path = workflow_book.book_path(settings, "full_workflow", universe_source="screen")
        assert screen_path.is_file()
        card_path = workflow_book.book_path(settings, "full_workflow", universe_source="card")
        assert not card_path.exists(), "saving a screen book must never touch the card-mode path"

        loaded = workflow_book.load_book(
            settings,
            "full_workflow",
            starting_cash=Decimal("1"),
            card_id="ignored",
            universe_source="screen",
        )
        assert loaded == book
        assert loaded.universe_source == "screen"

    def test_saving_a_card_book_alongside_a_screen_book_writes_two_independent_files(
        self, settings: Settings
    ) -> None:
        card_book = workflow_book.load_book(
            settings, "raw_signal", starting_cash=Decimal("100000.00"), card_id="card-1"
        )
        screen_book = workflow_book.load_book(
            settings,
            "raw_signal",
            starting_cash=Decimal("50000.00"),
            card_id="card-1",
            universe_source="screen",
        )
        workflow_book.save_book(settings, card_book)
        workflow_book.save_book(settings, screen_book)

        loaded_card = workflow_book.load_book(
            settings, "raw_signal", starting_cash=Decimal("1"), card_id="ignored"
        )
        loaded_screen = workflow_book.load_book(
            settings,
            "raw_signal",
            starting_cash=Decimal("1"),
            card_id="ignored",
            universe_source="screen",
        )
        assert loaded_card.starting_cash == Decimal("100000.00")
        assert loaded_card.universe_source == "card"
        assert loaded_screen.starting_cash == Decimal("50000.00")
        assert loaded_screen.universe_source == "screen"

    def test_load_book_rejects_a_file_whose_own_universe_source_does_not_match_the_path(
        self, settings: Settings
    ) -> None:
        """A defensive guard: if a card-path file somehow carries `universe_source="screen"` (or vice
        versa), `load_book` must refuse to load it silently rather than let two ledgers blend."""
        path = workflow_book.book_path(settings, "raw_signal", universe_source="card")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "arm": "raw_signal",
                    "universe_source": "screen",
                    "current_card_id": "card-1",
                    "card_adopted_date": "2026-01-01",
                    "starting_cash": "100000.00",
                    "broker_state": {},
                    "orders": [],
                    "equity_curve": [],
                    "as_of": None,
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="universe_source"):
            workflow_book.load_book(
                settings, "raw_signal", starting_cash=Decimal("1"), card_id="card-1"
            )

    def test_an_old_shape_book_file_with_no_universe_source_key_loads_as_card(
        self, settings: Settings
    ) -> None:
        """A book written before this field existed has no `universe_source` key at all -- the
        default must fill it in as `"card"`, not fail to load."""
        path = workflow_book.book_path(settings, "raw_signal")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "arm": "raw_signal",
                    "current_card_id": "card-1",
                    "card_adopted_date": "2026-01-01",
                    "starting_cash": "100000.00",
                    "broker_state": {},
                    "orders": [],
                    "equity_curve": [],
                    "as_of": None,
                }
            ),
            encoding="utf-8",
        )
        loaded = workflow_book.load_book(
            settings, "raw_signal", starting_cash=Decimal("1"), card_id="ignored"
        )
        assert loaded.universe_source == "card"


# ---------------------------------------------------------------------------
# 2. Stage -> execute, stored-open fill
# ---------------------------------------------------------------------------


class TestStageAndExecuteStoredOpen:
    def test_order_goes_pending_to_filled_off_the_stored_open(self, settings: Settings) -> None:
        decision_date = dt.date(2026, 3, 2)
        fill_date = dt.date(2026, 3, 3)
        _write_bar(settings, "AAA", decision_date, open_=99.00, close=100.00)
        _write_bar(settings, "AAA", fill_date, open_=100.00, close=101.00)

        book = workflow_book.load_book(
            settings, "raw_signal", starting_cash=Decimal("100000.00"), card_id="card-1"
        )
        assert book.orders == ()

        book = workflow_book.stage_orders(
            book,
            [_plan(symbol="AAA")],
            decision_date=decision_date,
            fill_date=fill_date,
            run_id="run-1",
        )
        assert len(book.orders) == 1
        assert book.orders[0].status == "pending"

        mandate = _mandate()
        new_book, outcome = workflow_book.execute_pending(
            book, settings=settings, mandate=mandate, today=fill_date
        )

        assert outcome.filled == 1
        assert outcome.rejected == 0
        assert outcome.still_pending == 0
        assert outcome.stored_open_fills == 1
        assert outcome.live_quote_fills == 0

        record = new_book.orders[0]
        assert record.status == "filled"
        assert record.fill is not None
        assert record.fill.price_source == "stored_open"
        # notional 1000 / decision close 100.00 -> 10 whole shares, at the 100.00 open (no slippage).
        assert record.fill.qty == Decimal("10")
        assert record.fill.price == Decimal("100.00")

        # Cash moved by exactly the fill's cost.
        assert Decimal(new_book.broker_state["cash"]) == Decimal("100000.00") - Decimal("1000.00")


# ---------------------------------------------------------------------------
# 3. Live-quote path
# ---------------------------------------------------------------------------


class TestLiveQuotePath:
    def test_no_stored_open_and_fill_date_is_today_fills_from_the_live_source(
        self, settings: Settings
    ) -> None:
        decision_date = dt.date(2026, 3, 2)
        fill_date = dt.date(2026, 3, 3)  # today -- no stored open exists for it yet
        _write_bar(settings, "BBB", decision_date, open_=49.00, close=50.00)

        book = workflow_book.load_book(
            settings, "ta_gated", starting_cash=Decimal("100000.00"), card_id="card-1"
        )
        book = workflow_book.stage_orders(
            book,
            [_plan(symbol="BBB")],
            decision_date=decision_date,
            fill_date=fill_date,
            run_id="run-2",
        )

        stub = _StubLiveQuoteSource({"BBB": Decimal("50.00")})
        mandate = _mandate()
        new_book, outcome = workflow_book.execute_pending(
            book,
            settings=settings,
            mandate=mandate,
            live_quote_source=stub,
            today=fill_date,
        )

        assert stub.calls == [("BBB",)]
        assert outcome.filled == 1
        assert outcome.stored_open_fills == 0
        assert outcome.live_quote_fills == 1

        record = new_book.orders[0]
        assert record.status == "filled"
        assert record.fill is not None
        assert record.fill.price_source == "live_quote"
        assert record.fill.reference_open == Decimal("50.00")


# ---------------------------------------------------------------------------
# 4. Catch-up
# ---------------------------------------------------------------------------


class TestCatchUp:
    def test_an_order_stale_by_two_sessions_still_fills_off_that_dates_stored_open(
        self, settings: Settings
    ) -> None:
        decision_date = dt.date(2026, 3, 2)
        fill_date = dt.date(2026, 3, 3)  # the session the order was always meant to fill at
        today = dt.date(2026, 3, 5)  # two sessions later -- the app "was not running that morning"
        _write_bar(settings, "CCC", decision_date, open_=19.00, close=20.00)
        _write_bar(settings, "CCC", fill_date, open_=20.00, close=20.50)

        book = workflow_book.load_book(
            settings, "vibe_gated", starting_cash=Decimal("100000.00"), card_id="card-1"
        )
        book = workflow_book.stage_orders(
            book,
            [_plan(symbol="CCC")],
            decision_date=decision_date,
            fill_date=fill_date,
            run_id="run-3",
        )

        mandate = _mandate()
        new_book, outcome = workflow_book.execute_pending(
            book, settings=settings, mandate=mandate, today=today
        )

        assert outcome.filled == 1
        assert outcome.rejected == 0
        record = new_book.orders[0]
        assert record.status == "filled", "a stale-but-due order must still fill, never expire silently"
        assert record.fill is not None
        assert record.fill.price_source == "stored_open"
        assert record.fill.price == Decimal("20.00")  # the fill_date's own open, not today's anything


# ---------------------------------------------------------------------------
# 5. Mandate rejection
# ---------------------------------------------------------------------------


class TestMandateRejection:
    def test_missing_thesis_is_recorded_as_rejected_with_cash_unchanged(
        self, settings: Settings
    ) -> None:
        decision_date = dt.date(2026, 3, 2)
        fill_date = dt.date(2026, 3, 3)
        _write_bar(settings, "DDD", decision_date, open_=9.00, close=10.00)
        _write_bar(settings, "DDD", fill_date, open_=10.00, close=10.50)

        book = workflow_book.load_book(
            settings, "full_workflow", starting_cash=Decimal("100000.00"), card_id="card-1"
        )
        starting_cash_str = book.broker_state["cash"]
        book = workflow_book.stage_orders(
            book,
            [_plan(symbol="DDD", thesis="", invalidation="an invalidation")],
            decision_date=decision_date,
            fill_date=fill_date,
            run_id="run-4",
        )

        mandate = _mandate()
        new_book, outcome = workflow_book.execute_pending(
            book, settings=settings, mandate=mandate, today=fill_date
        )

        assert outcome.filled == 0
        assert outcome.rejected == 1
        record = new_book.orders[0]
        assert record.status == "rejected"
        assert record.fill is None
        assert record.reject_reason != ""
        assert "thesis" in record.reject_reason.lower()
        assert new_book.broker_state["cash"] == starting_cash_str


# ---------------------------------------------------------------------------
# 6. Unknown schema_version
# ---------------------------------------------------------------------------


class TestUnknownSchemaVersion:
    def test_unknown_schema_version_raises_a_clear_error(self, settings: Settings) -> None:
        path = workflow_book.book_path(settings, "raw_signal")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": 99,
                    "arm": "raw_signal",
                    "current_card_id": "card-1",
                    "card_adopted_date": "2026-01-01",
                    "starting_cash": "100000.00",
                    "broker_state": {},
                    "orders": [],
                    "equity_curve": [],
                    "as_of": None,
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="schema_version"):
            workflow_book.load_book(
                settings, "raw_signal", starting_cash=Decimal("1"), card_id="card-1"
            )


# ---------------------------------------------------------------------------
# Bonus: tax_summary degrades gracefully and computes on a real round trip
# ---------------------------------------------------------------------------


class TestTaxSummary:
    def test_no_filled_orders_degrades_to_none(self, settings: Settings) -> None:
        book = workflow_book.load_book(
            settings, "raw_signal", starting_cash=Decimal("100000.00"), card_id="card-1"
        )
        assert workflow_book.tax_summary(book, settings=settings) is None

    def test_a_round_trip_buy_and_sell_produces_a_summary(self, settings: Settings) -> None:
        buy_decision = dt.date(2026, 3, 2)
        buy_fill = dt.date(2026, 3, 3)
        sell_decision = dt.date(2026, 3, 4)
        sell_fill = dt.date(2026, 3, 5)
        _write_bar(settings, "EEE", buy_decision, open_=19.00, close=20.00)
        _write_bar(settings, "EEE", buy_fill, open_=20.00, close=20.00)
        _write_bar(settings, "EEE", sell_decision, open_=24.00, close=25.00)
        _write_bar(settings, "EEE", sell_fill, open_=25.00, close=25.00)

        mandate = _mandate()
        book = workflow_book.load_book(
            settings, "raw_signal", starting_cash=Decimal("100000.00"), card_id="card-1"
        )
        book = workflow_book.stage_orders(
            book, [_plan(symbol="EEE")], decision_date=buy_decision, fill_date=buy_fill, run_id="run-5"
        )
        book, buy_outcome = workflow_book.execute_pending(
            book, settings=settings, mandate=mandate, today=buy_fill
        )
        assert buy_outcome.filled == 1

        book = workflow_book.stage_orders(
            book,
            [_plan(symbol="EEE", side="sell", notional="250.00")],
            decision_date=sell_decision,
            fill_date=sell_fill,
            run_id="run-6",
        )
        book, sell_outcome = workflow_book.execute_pending(
            book, settings=settings, mandate=mandate, today=sell_fill
        )
        assert sell_outcome.filled == 1

        summary = workflow_book.tax_summary(book, settings=settings)
        assert summary is not None
        assert summary.net_realized_gain > 0


# ---------------------------------------------------------------------------
# 7. mark_equity_through -- session-by-session equity backfill from the book's own fill history
# ---------------------------------------------------------------------------


class TestMarkEquityThrough:
    """`mark_equity_through` is the actual fix for the empty-`equity_curve` defect: nothing before it
    ever called `snapshot_equity` either, so every real workflow book on disk has `equity_curve == ()`
    regardless of how many fills it holds. These tests build a `BookState` directly (never going
    through `execute_pending`) so the reconstruction is exercised against a known, hand-computed fill
    history rather than whatever `PaperBroker` itself would have produced."""

    _DAYS = (
        dt.date(2026, 3, 2),  # day 1 -- card_adopted_date, no fill yet
        dt.date(2026, 3, 3),  # day 2 -- the buy fills
        dt.date(2026, 3, 4),  # day 3
        dt.date(2026, 3, 5),  # day 4 -- `through`
    )

    def _write_spy_calendar(self, settings: Settings) -> None:
        for day in self._DAYS:
            _write_bar(settings, "SPY", day, open_=500.0, close=501.0)

    def _book(self, orders: tuple[WorkflowOrderRecord, ...]) -> BookState:
        return BookState(
            arm="full_workflow",
            current_card_id="card-1",
            card_adopted_date=self._DAYS[0],
            starting_cash=Decimal("100000"),
            broker_state={"cash": "0", "positions": {}, "unsettled": [], "fills": [], "rejections": []},
            orders=orders,
            equity_curve=(),
            as_of=None,
        )

    def test_empty_curve_with_a_fill_on_day_two_backfills_all_four_sessions(
        self, settings: Settings
    ) -> None:
        self._write_spy_calendar(settings)
        _write_bar(settings, "AAA", self._DAYS[1], open_=99.0, close=100.0)
        _write_bar(settings, "AAA", self._DAYS[2], open_=100.0, close=105.0)
        _write_bar(settings, "AAA", self._DAYS[3], open_=105.0, close=110.0)

        buy = _filled_order(
            order_id="o1", symbol="AAA", side="buy", qty="10", price="100",
            day=self._DAYS[1], fees="0",
        )
        book = self._book((buy,))

        marked = workflow_book.mark_equity_through(
            book, settings=settings, mandate=_mandate(), through=self._DAYS[3]
        )

        assert [p.date for p in marked.equity_curve] == list(self._DAYS)
        # Day 1: adopted, but the buy has not filled yet -- equity is just starting cash.
        assert marked.equity_curve[0].equity == Decimal("100000")
        # Day 2: bought 10 AAA @ 100 (no fees) -- cash 99000, valued at that same day's own close.
        assert marked.equity_curve[1].equity == Decimal("99000") + Decimal("10") * Decimal("100")
        assert marked.equity_curve[2].equity == Decimal("99000") + Decimal("10") * Decimal("105")
        assert marked.equity_curve[3].equity == Decimal("99000") + Decimal("10") * Decimal("110")
        assert marked.as_of == self._DAYS[3]

    def test_a_held_symbol_with_no_bar_at_all_marks_every_post_fill_point_none(
        self, settings: Settings
    ) -> None:
        """`AsOfMarket.close` is "the last close at or before `as_of`" -- a symbol with a stale bar
        still prices (forward-filled) on a later date within its 30-day lookback. To reach the
        genuinely-unpriced case this test asserts, the held symbol must have no stored bar at all, not
        merely no bar for that exact session."""
        self._write_spy_calendar(settings)
        # No ZZZ bar is ever written -- `AsOfMarket.close` finds an empty frame at every `as_of`.

        buy = _filled_order(
            order_id="o1", symbol="ZZZ", side="buy", qty="10", price="100",
            day=self._DAYS[1], fees="0",
        )
        book = self._book((buy,))

        marked = workflow_book.mark_equity_through(
            book, settings=settings, mandate=_mandate(), through=self._DAYS[3]
        )

        assert marked.equity_curve[0].equity == Decimal("100000")  # day 1: no holdings yet
        assert marked.equity_curve[1].equity is None  # filled today, ZZZ never priced
        assert marked.equity_curve[2].equity is None
        assert marked.equity_curve[3].equity is None

    def test_calling_it_twice_with_the_same_through_appends_nothing_the_second_time(
        self, settings: Settings
    ) -> None:
        self._write_spy_calendar(settings)
        _write_bar(settings, "AAA", self._DAYS[1], open_=99.0, close=100.0)
        _write_bar(settings, "AAA", self._DAYS[2], open_=100.0, close=105.0)
        _write_bar(settings, "AAA", self._DAYS[3], open_=105.0, close=110.0)

        buy = _filled_order(
            order_id="o1", symbol="AAA", side="buy", qty="10", price="100",
            day=self._DAYS[1], fees="0",
        )
        book = self._book((buy,))

        once = workflow_book.mark_equity_through(
            book, settings=settings, mandate=_mandate(), through=self._DAYS[3]
        )
        twice = workflow_book.mark_equity_through(
            once, settings=settings, mandate=_mandate(), through=self._DAYS[3]
        )

        assert twice.equity_curve == once.equity_curve
        assert twice.as_of == once.as_of

    def test_a_sell_reduces_quantity_and_returns_cash(self, settings: Settings) -> None:
        self._write_spy_calendar(settings)
        _write_bar(settings, "AAA", self._DAYS[1], open_=99.0, close=100.0)
        _write_bar(settings, "AAA", self._DAYS[2], open_=100.0, close=105.0)
        _write_bar(settings, "AAA", self._DAYS[3], open_=105.0, close=110.0)

        buy = _filled_order(
            order_id="o1", symbol="AAA", side="buy", qty="10", price="100",
            day=self._DAYS[1], fees="0",
        )
        sell = _filled_order(
            order_id="o2", symbol="AAA", side="sell", qty="4", price="105",
            day=self._DAYS[2], fees="0",
        )
        book = self._book((buy, sell))

        marked = workflow_book.mark_equity_through(
            book, settings=settings, mandate=_mandate(), through=self._DAYS[3]
        )

        # Day 3: bought 10 @ 100 (cash 99000), then sold 4 @ 105 (cash 99420) -- 6 shares remain.
        assert marked.equity_curve[2].equity == Decimal("99420") + Decimal("6") * Decimal("105")
        assert marked.equity_curve[3].equity == Decimal("99420") + Decimal("6") * Decimal("110")

    def test_no_stored_spy_bars_returns_the_book_unchanged(self, settings: Settings) -> None:
        book = workflow_book.load_book(
            settings, "raw_signal", starting_cash=Decimal("100000.00"), card_id="card-1"
        )
        marked = workflow_book.mark_equity_through(
            book, settings=settings, mandate=_mandate(), through=dt.date(2026, 3, 5)
        )
        assert marked == book

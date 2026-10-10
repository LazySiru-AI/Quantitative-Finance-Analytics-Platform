"""The workflow-fill notification hook in `backend/app/workflow/book.py`.

Driven through the real `execute_pending` rather than by calling `_notify_order` directly: the thing
worth pinning is that each of that function's *three* terminal paths -- an unpriceable order rejected
before an `Order` is ever built, a broker `Rejection`, and a `Fill` -- announces itself, and only
running the real thing can prove all three are wired.

Bars are written straight into the temp-rooted DuckDB/Parquet store by `_write_bar`, copied in spirit
from `tests/test_workflow_book.py`'s helper of the same name. Nothing here touches the network.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pandas as pd
import pytest

import app.notify as notify_pkg
from app.config import Settings
from app.db import duck
from app.market.models import BAR_COLUMNS, Interval
from app.notify import events as notify_events
from app.paper.marketdata import clear_frame_cache
from app.paper.paperbroker import Mandate
from app.workflow import book as workflow_book
from app.workflow.book_models import OrderPlan

_DECISION = dt.date(2026, 3, 2)
_FILL = dt.date(2026, 3, 3)


def _mandate(**overrides: object) -> Mandate:
    fields: dict[str, object] = {
        "persona_id": "notify-test",
        "display_name": "Notify Test",
        "account_id": "notify-acct",
        "account_label": "Notify Test Account",
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


def _plan(symbol: str, *, notional: str = "1000.00", side: str = "buy") -> OrderPlan:
    return OrderPlan(
        agent_card_id="card-1",
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        notional=Decimal(notional),
        thesis="a test thesis",
        invalidation="a test invalidation",
    )


def _staged(settings: Settings, plans: list[OrderPlan], *, arm: str = "raw_signal") -> object:
    book = workflow_book.load_book(
        settings, arm, starting_cash=Decimal("100000.00"), card_id="card-1"
    )
    return workflow_book.stage_orders(
        book, plans, decision_date=_DECISION, fill_date=_FILL, run_id="run-1"
    )


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    clear_frame_cache()
    yield
    clear_frame_cache()


class TestFill:
    def test_a_fill_emits_one_paper_fill_event(self, settings: Settings) -> None:
        _write_bar(settings, "AAA", _DECISION, open_=99.00, close=100.00)
        _write_bar(settings, "AAA", _FILL, open_=100.00, close=101.00)

        _book, outcome = workflow_book.execute_pending(
            _staged(settings, [_plan("AAA")]),  # type: ignore[arg-type]
            settings=settings,
            mandate=_mandate(),
            today=_FILL,
        )
        assert outcome.filled == 1

        emitted = notify_events.list_since(settings)
        assert len(emitted) == 1
        event = emitted[0]
        assert event.kind == "paper.fill"
        assert event.severity == "notable"
        assert event.headline == "Autopilot filled BUY 10 AAA @ 100.00"
        assert event.detail == "a test thesis"
        assert event.refs == ("symbol:AAA", "order:run-1-0")
        assert event.source == "workflow.book"
        assert event.id == "paper.fill:workflow:run-1-0:filled"


class TestRejections:
    def test_an_unpriceable_order_emits_a_rejected_headline(self, settings: Settings) -> None:
        """No decision-date close at all: rejected before an `Order` is ever constructed."""
        _book, outcome = workflow_book.execute_pending(
            _staged(settings, [_plan("ZZZ")]),  # type: ignore[arg-type]
            settings=settings,
            mandate=_mandate(),
            today=_FILL,
        )
        assert outcome.rejected == 1

        emitted = notify_events.list_since(settings)
        assert len(emitted) == 1
        event = emitted[0]
        assert event.kind == "paper.fill"
        assert event.severity == "notable"
        assert event.headline.startswith("Rejected:")
        assert event.headline == "Rejected: BUY ZZZ (raw_signal)"
        assert "no stored close for ZZZ" in event.detail
        assert event.id == "paper.fill:workflow:run-1-0:rejected"

    def test_a_broker_rejection_also_emits(self, settings: Settings) -> None:
        """Priced fine, but the mandate refuses it -- a different code path, same announcement."""
        _write_bar(settings, "AAA", _DECISION, open_=99.00, close=100.00)
        _write_bar(settings, "AAA", _FILL, open_=100.00, close=101.00)

        _book, outcome = workflow_book.execute_pending(
            _staged(settings, [_plan("AAA", notional="1000.00")]),  # type: ignore[arg-type]
            settings=settings,
            mandate=_mandate(min_clip_notional=Decimal("5000.00")),
            today=_FILL,
        )
        assert outcome.rejected == 1
        event = notify_events.list_since(settings)[0]
        assert event.headline.startswith("Rejected: BUY AAA")
        assert event.id == "paper.fill:workflow:run-1-0:rejected"


class TestResilience:
    def test_the_book_still_executes_when_emit_raises(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_bar(settings, "AAA", _DECISION, open_=99.00, close=100.00)
        _write_bar(settings, "AAA", _FILL, open_=100.00, close=101.00)

        def _boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("notify is broken")

        monkeypatch.setattr(notify_pkg, "emit", _boom)
        book, outcome = workflow_book.execute_pending(
            _staged(settings, [_plan("AAA")]),  # type: ignore[arg-type]
            settings=settings,
            mandate=_mandate(),
            today=_FILL,
        )

        assert outcome.filled == 1
        assert book.orders[0].status == "filled"
        assert book.orders[0].fill is not None
        assert notify_events.list_since(settings) == []

    def test_two_orders_produce_two_distinct_dedupe_ids(self, settings: Settings) -> None:
        for symbol in ("AAA", "BBB"):
            _write_bar(settings, symbol, _DECISION, open_=99.00, close=100.00)
            _write_bar(settings, symbol, _FILL, open_=100.00, close=101.00)

        _book, outcome = workflow_book.execute_pending(
            _staged(settings, [_plan("AAA"), _plan("BBB")]),  # type: ignore[arg-type]
            settings=settings,
            mandate=_mandate(),
            today=_FILL,
        )
        assert outcome.filled == 2
        assert {event.id for event in notify_events.list_since(settings)} == {
            "paper.fill:workflow:run-1-0:filled",
            "paper.fill:workflow:run-1-1:filled",
        }

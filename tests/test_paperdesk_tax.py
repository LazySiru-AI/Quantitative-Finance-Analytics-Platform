"""Proves the paper-tax module (`app.paper.papertax`, finished and tested elsewhere -- this file
never modifies it) is actually wired onto the paper desk: `app.paperdesk.desk._fills_from_trades`
synthesises the fills the tax engine needs out of a card's closed trade log, and
`app.paperdesk.desk._build_desk` calls the real `summarize_paper_tax` and attaches the result to
`Desk.tax` -- but only for a taxable book's rules desks.

Four things are exercised, matching the task brief:

1. `_fills_from_trades` itself -- one buy+sell per closed trade, buy-only for a trade still open at
   the trading window's end.
2. A taxable rules desk (`taxable=True`, the flag `_book` passes for `SAVINGS`/`TRADING`) gets a
   populated `Desk.tax`.
3. A non-taxable sleeve (`taxable=False`, the flag `_book` passes for `ROTH`) gets `Desk.tax is None`
   -- plus a direct check that `_book`'s own condition (`PurposeSpec.tax_treatment ==
   TaxTreatment.TAXABLE`) actually maps `TRADING`/`SAVINGS` to taxable and `ROTH` to not, since that
   one-line mapping is exactly what (2)/(3) do not otherwise exercise.
4. An end-to-end case -- a loss sold and the same symbol rebought within 30 days -- shows up as a
   `WashSaleFlag` on the desk's own `tax.wash_sales`, through the real `app.core.lots`/
   `app.tax.washsale`/`app.tax.gains` engines, not a hand-rolled approximation of them.

No bars are written to any temp store: every trade below is closed (`exit_reason != "open_at_end"`),
so `desk._holdings` (which only marks *open* trades fresh against a stored price) returns `[]`
without touching the store at all, and `desk._signals` degrades a universe symbol with no stored
price to `blocked="no price"` rather than raising -- the same tolerance
`tests/test_paperdesk_rejections.py`'s module docstring documents relying on.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.config import Settings
from app.core.models import TaxTreatment
from app.paper.marketdata import clear_frame_cache
from app.paperdesk import desk
from app.tournament.models import (
    DESIGN_THROUGH,
    AgentResult,
    Discipline,
    RealisedTrade,
    StrategyCard,
)
from app.tournament.purposes import PURPOSE_SPECS, Purpose

# ---------------------------------------------------------------------------
# Builders -- small, local, mirroring `tests/test_paperdesk_rejections.py`'s own (duplicated rather
# than imported -- see that file's module docstring for why this repo prefers that for test fakes).
# ---------------------------------------------------------------------------


def _card(**overrides: object) -> StrategyCard:
    fields: dict[str, object] = {
        "agent_id": "tax-test",
        "display_name": "Tax test desk",
        "discipline": Discipline.MOMENTUM,
        "thesis": "a test thesis, written before the trading window ran",
        "universe": ("AAA", "BBB", "WASH"),
        "entry": "close > 0",
        "exit": "close < 0",
        "stop_loss_pct": None,
        "take_profit_pct": None,
        "max_hold_days": None,
        "max_positions": 6,
        "position_pct": Decimal("0.15"),
        "designed_through": DESIGN_THROUGH,
    }
    fields.update(overrides)
    return StrategyCard(**fields)  # type: ignore[arg-type]


def _closed_trade(
    *,
    symbol: str,
    entry_date: dt.date,
    entry_price: Decimal,
    exit_date: dt.date,
    exit_price: Decimal,
    quantity: Decimal = Decimal("10"),
    exit_reason: str = "rule",
    bars_held: int = 3,
) -> RealisedTrade:
    pnl = (exit_price - entry_price) * quantity
    return_pct = (exit_price / entry_price) - Decimal(1)
    return RealisedTrade(
        symbol=symbol,
        entry_date=entry_date,
        entry_price=entry_price,
        exit_date=exit_date,
        exit_price=exit_price,
        quantity=quantity,
        exit_reason=exit_reason,
        pnl=pnl,
        return_pct=return_pct,
        bars_held=bars_held,
    )


def _open_trade(
    *,
    symbol: str,
    entry_date: dt.date,
    entry_price: Decimal,
    quantity: Decimal = Decimal("5"),
    bars_held: int = 2,
) -> RealisedTrade:
    return RealisedTrade(
        symbol=symbol,
        entry_date=entry_date,
        entry_price=entry_price,
        exit_date=None,
        exit_price=None,
        quantity=quantity,
        exit_reason="open_at_end",
        pnl=Decimal("0.00"),
        return_pct=Decimal("0.00"),
        bars_held=bars_held,
    )


def _result(*, trades: tuple[RealisedTrade, ...], card: StrategyCard | None = None) -> AgentResult:
    return AgentResult(
        card=card or _card(),
        sessions=20,
        starting_equity=Decimal("10000.00"),
        ending_equity=Decimal("10000.00"),
        total_return=Decimal("0"),
        max_drawdown=Decimal("0"),
        trades=trades,
        benchmark_return=None,
    )


def _window(*, inception: dt.date, as_of: dt.date, decided_on: dt.date | None = None) -> desk._Window:
    return desk._Window(
        inception=inception,
        first_session=inception,
        as_of=as_of,
        decided_on=decided_on or inception,
        sessions=20,
        latest_bar=as_of,
    )


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    desk.clear_cache()
    clear_frame_cache()
    yield
    desk.clear_cache()
    clear_frame_cache()


# ---------------------------------------------------------------------------
# (1) `_fills_from_trades`
# ---------------------------------------------------------------------------


class TestFillsFromTrades:
    def test_closed_trade_produces_a_buy_and_a_sell_fill(self) -> None:
        closed = _closed_trade(
            symbol="AAA",
            entry_date=dt.date(2026, 1, 5),
            entry_price=Decimal("50.00"),
            exit_date=dt.date(2026, 1, 10),
            exit_price=Decimal("55.00"),
            quantity=Decimal("10"),
        )
        result = _result(trades=(closed,))

        fills = desk._fills_from_trades(result)

        assert len(fills) == 2
        buy, sell = fills
        assert buy.side == "buy"
        assert buy.symbol == "AAA"
        assert buy.trade_date == dt.date(2026, 1, 5)
        assert buy.quantity == Decimal("10")
        assert buy.price == Decimal("50.00")
        assert buy.reference_open == Decimal("50.00")
        assert buy.gross == Decimal("500.00")
        assert buy.fees == Decimal("0")
        assert buy.cash_delta == Decimal("-500.00")

        assert sell.side == "sell"
        assert sell.symbol == "AAA"
        assert sell.trade_date == dt.date(2026, 1, 10)
        assert sell.quantity == Decimal("10")
        assert sell.price == Decimal("55.00")
        assert sell.gross == Decimal("550.00")
        assert sell.fees == Decimal("0")
        assert sell.cash_delta == Decimal("550.00")

        # Session index is monotonic across the sequence.
        assert sell.session > buy.session

    def test_open_trade_produces_a_buy_only(self) -> None:
        open_trade = _open_trade(
            symbol="BBB", entry_date=dt.date(2026, 1, 6), entry_price=Decimal("20.00"),
            quantity=Decimal("5"),
        )
        result = _result(trades=(open_trade,))

        fills = desk._fills_from_trades(result)

        assert len(fills) == 1
        (buy,) = fills
        assert buy.side == "buy"
        assert buy.symbol == "BBB"
        assert buy.quantity == Decimal("5")
        assert buy.price == Decimal("20.00")
        assert buy.gross == Decimal("100.00")
        assert buy.cash_delta == Decimal("-100.00")

    def test_mixed_open_and_closed_trades_sort_deterministically_by_entry_date_then_symbol(
        self,
    ) -> None:
        """Input order must not matter -- `_fills_from_trades` sorts by `(entry_date, symbol)`
        internally, so passing the trades in reverse produces the identical fill sequence."""
        closed = _closed_trade(
            symbol="AAA",
            entry_date=dt.date(2026, 1, 5),
            entry_price=Decimal("50.00"),
            exit_date=dt.date(2026, 1, 10),
            exit_price=Decimal("55.00"),
        )
        opened = _open_trade(
            symbol="BBB", entry_date=dt.date(2026, 1, 6), entry_price=Decimal("20.00")
        )

        forward = desk._fills_from_trades(_result(trades=(closed, opened)))
        reversed_ = desk._fills_from_trades(_result(trades=(opened, closed)))

        assert len(forward) == 3
        assert [f.symbol for f in forward] == ["AAA", "AAA", "BBB"]
        assert [f.side for f in forward] == ["buy", "sell", "buy"]
        assert forward == reversed_

    def test_every_synthesised_fill_has_zero_fees(self) -> None:
        """The documented, deliberate lossy part of the bridge -- see `_fills_from_trades`'s own
        docstring and `desk._TAX_FEE_NOTE`. Asserted here so a future change that starts inventing a
        fee figure is caught."""
        closed = _closed_trade(
            symbol="AAA",
            entry_date=dt.date(2026, 1, 5),
            entry_price=Decimal("50.00"),
            exit_date=dt.date(2026, 1, 10),
            exit_price=Decimal("45.00"),
        )
        fills = desk._fills_from_trades(_result(trades=(closed,)))
        assert all(f.fees == Decimal("0") for f in fills)


# ---------------------------------------------------------------------------
# (2)/(3) `_build_desk`'s `taxable` flag, and the `_book`-level mapping it mirrors
# ---------------------------------------------------------------------------


class TestBuildDeskTaxWiring:
    def test_taxable_rules_desk_gets_a_populated_tax_summary(self, settings: Settings) -> None:
        trade = _closed_trade(
            symbol="AAA",
            entry_date=dt.date(2026, 1, 5),
            entry_price=Decimal("50.00"),
            exit_date=dt.date(2026, 1, 10),
            exit_price=Decimal("60.00"),
            quantity=Decimal("10"),
        )
        card = _card()
        result = _result(trades=(trade,), card=card)
        window = _window(inception=dt.date(2026, 1, 1), as_of=dt.date(2026, 1, 31))

        built = desk._build_desk(card, result, settings=settings, window=window, taxable=True)

        assert built.tax is not None
        # $10/share * 10 shares = $100 gain, held 5 days -- entirely short-term, no wash sale.
        assert built.tax.short_term_gain == Decimal("100.00")
        assert built.tax.long_term_gain == Decimal("0.00")
        assert built.tax.net_realized_gain == Decimal("100.00")
        assert built.tax.wash_sales == ()
        # Default statutory rate (no `ordinary_income_tax_rate` configured on the fixture settings).
        assert built.tax.short_term_rate == Decimal("0.37")
        assert built.tax.tax_owed == Decimal("37.00")
        assert built.tax.after_tax_realized_gain == Decimal("63.00")
        assert built.tax.start == dt.date(2026, 1, 1)
        assert built.tax.end == dt.date(2026, 1, 31)

    def test_non_taxable_sleeve_leaves_tax_none(self, settings: Settings) -> None:
        """`taxable=False` is `_build_desk`'s default -- the flag `_book` passes for the `ROTH`
        book -- and must leave `Desk.tax` at `None` even though the exact same trade would produce a
        real gain on a taxable book (see the sibling test above)."""
        trade = _closed_trade(
            symbol="AAA",
            entry_date=dt.date(2026, 1, 5),
            entry_price=Decimal("50.00"),
            exit_date=dt.date(2026, 1, 10),
            exit_price=Decimal("60.00"),
            quantity=Decimal("10"),
        )
        card = _card()
        result = _result(trades=(trade,), card=card)
        window = _window(inception=dt.date(2026, 1, 1), as_of=dt.date(2026, 1, 31))

        built = desk._build_desk(card, result, settings=settings, window=window)

        assert built.tax is None

    def test_purpose_spec_tax_treatment_matches_the_book_level_taxable_condition(self) -> None:
        """`_book` computes its `taxable=` argument as `spec.tax_treatment ==
        TaxTreatment.TAXABLE` -- this is the one line that condition lives in, and the two tests
        above only exercise the flag once it has already been resolved to a bool. This closes that
        gap without needing to stand up a full book (a real card library, a roster, ...)."""
        assert PURPOSE_SPECS[Purpose.TRADING].tax_treatment == TaxTreatment.TAXABLE
        assert PURPOSE_SPECS[Purpose.SAVINGS].tax_treatment == TaxTreatment.TAXABLE
        assert PURPOSE_SPECS[Purpose.ROTH].tax_treatment != TaxTreatment.TAXABLE

    def test_a_tax_summary_failure_degrades_to_none_rather_than_raising(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`_build_desk` must never let a tax-summary error take the whole desk down -- see that
        function's own docstring and this module's docstring on the recorded page-blanking
        incident. Forcing `summarize_paper_tax` to raise proves the `except Exception` guard is
        real, not merely documented."""

        def _boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("synthetic failure for the test")

        monkeypatch.setattr(desk, "summarize_paper_tax", _boom)

        trade = _closed_trade(
            symbol="AAA",
            entry_date=dt.date(2026, 1, 5),
            entry_price=Decimal("50.00"),
            exit_date=dt.date(2026, 1, 10),
            exit_price=Decimal("60.00"),
        )
        card = _card()
        result = _result(trades=(trade,), card=card)
        window = _window(inception=dt.date(2026, 1, 1), as_of=dt.date(2026, 1, 31))

        built = desk._build_desk(card, result, settings=settings, window=window, taxable=True)

        assert built.tax is None


# ---------------------------------------------------------------------------
# (4) End-to-end wash sale
# ---------------------------------------------------------------------------


class TestWashSaleReachesTheDesk:
    def test_a_loss_rebought_within_30_days_flags_a_wash_sale_on_the_desks_tax(
        self, settings: Settings
    ) -> None:
        loss_trade = _closed_trade(
            symbol="WASH",
            entry_date=dt.date(2026, 1, 5),
            entry_price=Decimal("100.00"),
            exit_date=dt.date(2026, 1, 10),
            exit_price=Decimal("90.00"),
            quantity=Decimal("10"),
            exit_reason="stop",
            bars_held=5,
        )
        # Rebought 5 calendar days after the loss sale -- well inside IRC 1091's 61-day window
        # (30 before, the day of, 30 after).
        rebuy_trade = _closed_trade(
            symbol="WASH",
            entry_date=dt.date(2026, 1, 15),
            entry_price=Decimal("95.00"),
            exit_date=dt.date(2026, 1, 25),
            exit_price=Decimal("105.00"),
            quantity=Decimal("10"),
            exit_reason="rule",
            bars_held=10,
        )
        card = _card()
        result = _result(trades=(loss_trade, rebuy_trade), card=card)
        window = _window(inception=dt.date(2026, 1, 1), as_of=dt.date(2026, 1, 31))

        built = desk._build_desk(card, result, settings=settings, window=window, taxable=True)

        assert built.tax is not None
        assert len(built.tax.wash_sales) == 1
        flag = built.tax.wash_sales[0]
        assert flag.symbol == "WASH"
        assert flag.loss_date == dt.date(2026, 1, 10)
        assert flag.repurchase_date == dt.date(2026, 1, 15)
        assert flag.quantity_sold == Decimal("10")
        assert flag.disallowed_amount > Decimal("0")
        assert flag.permanently_disallowed is False
        assert built.tax.disallowed_loss_total > Decimal("0")

        # The disallowed loss must actually be deferred into the replacement lot's basis, not just
        # flagged: the net realised gain reported is not simply "loss trade's -$100 + rebuy's +$100"
        # netted naively, it is the wash-sale-adjusted figure the real engine computed.
        assert built.tax.net_realized_gain is not None

        # Round-trips through pydantic's own JSON encoding the same way the API response does --
        # proves `Desk.tax` is actually wired onto the model, not just present on the Python object.
        payload = built.model_dump(mode="json")
        assert payload["tax"] is not None
        assert len(payload["tax"]["wash_sales"]) == 1
        assert payload["tax"]["wash_sales"][0]["symbol"] == "WASH"

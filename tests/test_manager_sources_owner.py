"""Tests for `app.manager.sources_owner` -- the six section builders for the owner's own book:
account, tax, activity, paperdesk, persona_books, persona_traders.

No test depends on real repo data: every builder is exercised against a small monkeypatched fake of
the exact upstream service call it makes (`app.api.portfolio._build_report`, `app.api.tax._build` /
`.wash_sales`, `app.api.transactions.list_transactions`, `app.paperdesk.desk.state`,
`app.personas.service.persona_books`, `app.personas.trader_service.list_trader_books`), matching the
idiom used across `tests/test_personas_trader_service.py` and friends.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.config import Settings
from app.manager import sources_owner
from app.manager.models import FIGURE_KEYS, SnapshotSection
from app.manager.sources import SourceContext

AS_OF = dt.date(2026, 6, 15)
NOW = dt.datetime(2026, 6, 15, 18, 0, tzinfo=dt.UTC)


def _ctx(settings: Settings, *, as_of: dt.date = AS_OF) -> SourceContext:
    return SourceContext(settings=settings, as_of=as_of, scope="owner", now=NOW)


def _assert_figures_are_pinned_and_decimal(section: SnapshotSection) -> None:
    """Every figure key emitted -- section-level and per-item -- must be one `FIGURE_KEYS[section.key]`
    names, and every value must parse as a `Decimal` (proves nothing leaked a float repr or a percent
    sign)."""
    allowed = set(FIGURE_KEYS[section.key])
    for key, value in section.figures.items():
        assert key in allowed, f"{section.key}: section figure {key!r} not in FIGURE_KEYS"
        Decimal(value)
    for item in section.items:
        for key, value in item.figures.items():
            assert key in allowed, f"{section.key}: item figure {key!r} not in FIGURE_KEYS"
            Decimal(value)


def _assert_unique_item_ids(section: SnapshotSection) -> None:
    ids = [item.id for item in section.items]
    assert len(ids) == len(set(ids)), f"{section.key}: duplicate item ids in {ids}"


# ---------------------------------------------------------------------------
# account_section
# ---------------------------------------------------------------------------


def _position(**overrides: object) -> object:
    from app.api.portfolio import Position

    defaults: dict[str, object] = dict(
        instrument_id="inst-aapl",
        symbol="AAPL",
        quantity=Decimal(10),
        cost_basis=Decimal("1000.00"),
        basis_per_share=Decimal("100.00"),
        price=Decimal("150.00"),
        price_as_of=dt.date(2026, 6, 12),
        market_value=Decimal("1500.00"),
        unrealized=Decimal("500.00"),
        unrealized_pct=0.5,
        weight_pct=0.6,
        sector="Technology",
        previous_close=Decimal("148.00"),
        day_change=Decimal("20.00"),
        day_change_pct=0.0135,
        short_term_quantity=Decimal(10),
        long_term_quantity=Decimal(0),
        earliest_acquired=dt.date(2026, 1, 1),
        latest_acquired=dt.date(2026, 1, 1),
        lot_count=1,
        basis_uncertain=False,
        fees_unknown=False,
        wash_sale_adjustment=Decimal(0),
        accounts=[],
    )
    defaults.update(overrides)
    return Position(**defaults)


def _portfolio_report(**overrides: object) -> object:
    from app.api.portfolio import PortfolioReport

    positions = overrides.pop("positions", [_position()])
    defaults: dict[str, object] = dict(
        as_of=AS_OF,
        generated_at=NOW,
        positions=positions,
        total_cost_basis=Decimal("1000.00"),
        total_market_value=Decimal("1500.00"),
        total_unrealized=Decimal("500.00"),
        total_unrealized_pct=0.5,
        priced_position_count=len(positions),
        unpriced_symbols=[],
        cash_balance=Decimal("2500.00"),
        equity_is_complete=True,
        accounts_without_cash=[],
        positions_with_uncertain_basis=0,
        positions_with_unknown_fees=0,
        warnings=[],
        warning_groups=[],
        total_day_change=Decimal("20.00"),
        total_day_change_pct=0.0135,
    )
    defaults.update(overrides)
    return PortfolioReport(**defaults)


def test_account_section_happy_path(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    report = _portfolio_report()
    monkeypatch.setattr("app.api.portfolio._build_report", lambda: report)

    section = sources_owner.account_section(_ctx(settings))

    assert section.key == "account"
    assert section.ok is True
    assert section.figures["total_market_value"] == "1500.00"
    assert section.figures["cash_balance"] == "2500.00"
    assert section.figures["unpriced_count"] == "0"
    assert len(section.items) == 1
    assert section.items[0].id == "AAPL"
    _assert_figures_are_pinned_and_decimal(section)
    _assert_unique_item_ids(section)


def test_account_section_partial_total_omits_total_market_value(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `PortfolioReport` with `unpriced_symbols` non-empty must not emit `total_market_value`,
    even though the field itself is a non-null partial sum -- the gap stays named instead."""
    unpriced_position = _position(
        instrument_id="inst-xyz",
        symbol="XYZ",
        price=None,
        price_as_of=None,
        market_value=None,
        unrealized=None,
        unrealized_pct=None,
        weight_pct=None,
        previous_close=None,
        day_change=None,
        day_change_pct=None,
    )
    report = _portfolio_report(
        positions=[_position(), unpriced_position],
        unpriced_symbols=["XYZ"],
        priced_position_count=1,
        equity_is_complete=False,
    )
    monkeypatch.setattr("app.api.portfolio._build_report", lambda: report)

    section = sources_owner.account_section(_ctx(settings))

    assert "total_market_value" not in section.figures
    assert section.figures["unpriced_count"] == "1"
    assert any("XYZ" in w for w in section.warnings)
    assert any("equity_is_complete" in w for w in section.warnings)
    ids = [item.id for item in section.items]
    assert ids == ["AAPL", "XYZ"]
    unpriced_item = section.items[1]
    assert "market_value" not in unpriced_item.figures
    _assert_figures_are_pinned_and_decimal(section)
    _assert_unique_item_ids(section)


def test_account_section_upstream_failure_is_ok_false(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise() -> object:
        raise RuntimeError("ledger blew up")

    monkeypatch.setattr("app.api.portfolio._build_report", _raise)

    section = sources_owner.account_section(_ctx(settings))

    assert section.key == "account"
    assert section.ok is False
    assert section.warnings
    assert section.items == ()


def test_account_section_no_ledger_http_exception_is_ok_false(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    def _raise() -> object:
        raise HTTPException(status_code=404, detail="no ledger yet; import broker exports first")

    monkeypatch.setattr("app.api.portfolio._build_report", _raise)

    section = sources_owner.account_section(_ctx(settings))

    assert section.ok is False
    assert "no ledger" in section.warnings[0]


# ---------------------------------------------------------------------------
# tax_section
# ---------------------------------------------------------------------------


def _tax_report(**overrides: object) -> object:
    from app.tax.models import Form8949Report, GainsReport, TaxReport

    gains = overrides.pop(
        "gains",
        GainsReport(
            start=dt.date(2026, 1, 1),
            end=AS_OF,
            short_term_gain=Decimal("1200.00"),
            long_term_gain=Decimal("300.00"),
        ),
    )
    defaults: dict[str, object] = dict(
        tax_year=2026,
        generated_at=NOW,
        gains=gains,
        form8949=Form8949Report(),
    )
    defaults.update(overrides)
    return TaxReport(**defaults)


def _wash_symbol(**overrides: object) -> object:
    from app.tax.models import WashSaleSymbolSummary

    defaults: dict[str, object] = dict(
        symbol="TSLA",
        deferred_disallowed=Decimal("150.00"),
        permanently_disallowed=Decimal(0),
        event_count=1,
        loss_sale_count=1,
        first_sale_date=dt.date(2026, 6, 1),
        last_sale_date=dt.date(2026, 6, 1),
        repurchase_safe_on=dt.date(2026, 7, 2),
        days_until_safe=17,
        window_is_open=True,
        accounts=("acct-1",),
        sales=(),
    )
    defaults.update(overrides)
    return WashSaleSymbolSummary(**defaults)


def _wash_sale_row(**overrides: object) -> object:
    from app.tax.models import WashSaleSaleRow

    defaults: dict[str, object] = dict(
        disposal_id="disp-1",
        sale_date=dt.date(2026, 6, 1),
        account_id="acct-1",
        quantity_sold=Decimal(10),
        quantity_replaced=Decimal(10),
        loss_amount=Decimal("150.00"),
        disallowed_loss=Decimal("150.00"),
        permanently_disallowed=False,
        replacement_account_ids=("acct-1",),
        window_closes_on=dt.date(2026, 7, 2),
    )
    defaults.update(overrides)
    return WashSaleSaleRow(**defaults)


def _wash_exposure(**overrides: object) -> object:
    from app.tax.models import WashSaleExposureReport

    symbols = overrides.pop("symbols", (_wash_symbol(sales=(_wash_sale_row(),)),))
    defaults: dict[str, object] = dict(
        as_of=AS_OF,
        generated_at=NOW,
        total_deferred=Decimal("150.00"),
        total_permanently_disallowed=Decimal(0),
        open_window_count=1,
        symbol_count=len(symbols),
        symbols=symbols,
    )
    defaults.update(overrides)
    return WashSaleExposureReport(**defaults)


def test_tax_section_happy_path(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    report = _tax_report()
    exposure = _wash_exposure()
    monkeypatch.setattr("app.api.tax._build", lambda year: report)
    monkeypatch.setattr("app.api.tax.wash_sales", lambda: exposure)

    section = sources_owner.tax_section(_ctx(settings))

    assert section.key == "tax"
    assert section.ok is True
    assert section.figures["ytd_short_gain"] == "1200.00"
    assert section.figures["ytd_long_gain"] == "300.00"
    assert section.figures["ytd_net_gain"] == "1500.00"
    assert section.figures["deferred_disallowed"] == "150.00"
    assert section.figures["permanently_disallowed"] == "0"
    assert section.figures["open_window_count"] == "1"
    assert len(section.items) == 1
    item = section.items[0]
    assert item.id == "TSLA"
    assert item.figures["loss_amount"] == "150.00"
    assert item.figures["days_until_safe"] == "17"
    _assert_figures_are_pinned_and_decimal(section)
    _assert_unique_item_ids(section)


def test_tax_section_never_sums_deferred_and_permanent(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _tax_report()
    exposure = _wash_exposure(
        total_deferred=Decimal("150.00"),
        total_permanently_disallowed=Decimal("40.00"),
    )
    monkeypatch.setattr("app.api.tax._build", lambda year: report)
    monkeypatch.setattr("app.api.tax.wash_sales", lambda: exposure)

    section = sources_owner.tax_section(_ctx(settings))

    assert section.figures["deferred_disallowed"] == "150.00"
    assert section.figures["permanently_disallowed"] == "40.00"
    # Neither figure is 190.00 -- they must never be combined into one number.
    assert "190.00" not in section.figures.values()


def test_tax_section_closed_window_no_permanent_loss_is_excluded(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed_symbol = _wash_symbol(
        symbol="OLD", window_is_open=False, permanently_disallowed=Decimal(0), days_until_safe=0
    )
    open_symbol = _wash_symbol(symbol="TSLA")
    report = _tax_report()
    exposure = _wash_exposure(symbols=(closed_symbol, open_symbol))
    monkeypatch.setattr("app.api.tax._build", lambda year: report)
    monkeypatch.setattr("app.api.tax.wash_sales", lambda: exposure)

    section = sources_owner.tax_section(_ctx(settings))

    ids = [item.id for item in section.items]
    assert "OLD" not in ids
    assert "TSLA" in ids


def test_tax_section_permanent_loss_kept_even_after_window_closes(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    permanent_symbol = _wash_symbol(
        symbol="PERM", window_is_open=False, permanently_disallowed=Decimal("75.00")
    )
    report = _tax_report()
    exposure = _wash_exposure(symbols=(permanent_symbol,))
    monkeypatch.setattr("app.api.tax._build", lambda year: report)
    monkeypatch.setattr("app.api.tax.wash_sales", lambda: exposure)

    section = sources_owner.tax_section(_ctx(settings))

    ids = [item.id for item in section.items]
    assert ids == ["PERM"]


def test_tax_section_upstream_failure_is_ok_false(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(year: int) -> object:
        raise RuntimeError("replay blew up")

    monkeypatch.setattr("app.api.tax._build", _raise)

    section = sources_owner.tax_section(_ctx(settings))

    assert section.key == "tax"
    assert section.ok is False
    assert section.warnings
    assert section.items == ()


# ---------------------------------------------------------------------------
# activity_section
# ---------------------------------------------------------------------------


def _transaction_row(**overrides: object) -> object:
    from app.api.transactions import TransactionRow

    defaults: dict[str, object] = dict(
        txn_id="txn-1",
        account_id="acct-1",
        broker="robinhood",
        action="buy",
        trade_date=dt.date(2026, 6, 14),
        sequence=0,
        symbol="AAPL",
        quantity=Decimal(5),
        price=Decimal("150.00"),
        fees=Decimal(0),
        amount=Decimal("-750.00"),
        import_id="import-1",
        source_row=0,
    )
    defaults.update(overrides)
    return TransactionRow(**defaults)


def _transaction_page(**overrides: object) -> object:
    from app.api.transactions import TransactionPage

    transactions = overrides.pop("transactions", [_transaction_row()])
    defaults: dict[str, object] = dict(
        transactions=transactions,
        total=len(transactions),
        limit=200,
        offset=0,
        has_more=False,
        total_bought=Decimal("750.00"),
        total_sold=Decimal(0),
        net_cash_flow=Decimal("-750.00"),
    )
    defaults.update(overrides)
    return TransactionPage(**defaults)


def test_activity_section_happy_path(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    page = _transaction_page()
    captured: dict[str, object] = {}

    def _fake_list_transactions(**kwargs: object) -> object:
        captured.update(kwargs)
        return page

    monkeypatch.setattr("app.api.transactions.list_transactions", _fake_list_transactions)

    section = sources_owner.activity_section(_ctx(settings))

    assert section.key == "activity"
    assert section.ok is True
    assert len(section.items) == 1
    assert section.items[0].id == "txn-1"
    assert section.items[0].figures["quantity"] == "5"
    assert section.items[0].figures["amount"] == "-750.00"
    assert captured["start"] == AS_OF - dt.timedelta(days=7)
    assert captured["end"] == AS_OF
    _assert_figures_are_pinned_and_decimal(section)
    _assert_unique_item_ids(section)


def test_activity_section_upstream_failure_is_ok_false(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(**kwargs: object) -> object:
        raise RuntimeError("ledger read failed")

    monkeypatch.setattr("app.api.transactions.list_transactions", _raise)

    section = sources_owner.activity_section(_ctx(settings))

    assert section.ok is False
    assert section.warnings
    assert section.items == ()


# ---------------------------------------------------------------------------
# paperdesk_section
# ---------------------------------------------------------------------------


def _desk_seat(**overrides: object) -> object:
    from app.paperdesk.models import Desk

    defaults: dict[str, object] = dict(
        agent_id="b-momentum",
        display_name="B-Momentum",
        discipline="momentum",
        thesis="ride the trend",
        universe=["SPY", "QQQ"],
        starting_equity=Decimal("10000.00"),
        cash=Decimal("2000.00"),
        positions_value=Decimal("9500.00"),
        equity=Decimal("11500.00"),
        total_return=Decimal("0.15"),
        excess_return=Decimal("0.03"),
        max_drawdown=Decimal("0.08"),
        realised_pnl=Decimal("500.00"),
        unrealised_pnl=Decimal("1000.00"),
        open_positions=3,
        slots_free=2,
        holdings=[],
        trades=[],
        decisions=[],
        signals=[],
        rejections=[],
        rejection_count=2,
    )
    defaults.update(overrides)
    return Desk(**defaults)


def _paperdesk_book(**overrides: object) -> object:
    from app.paperdesk.models import Benchmark, Book, Funding

    desks = overrides.pop("desks", [_desk_seat()])
    defaults: dict[str, object] = dict(
        purpose="trading",
        label="Trading",
        funding=Funding(
            purpose="trading", shape="lump_sum", seed=Decimal("10000.00"),
            contribution=Decimal(0), tax_treatment="taxable",
        ),
        starting_cash=Decimal("10000.00"),
        benchmark=Benchmark(symbol="SPY"),
        desks=desks,
    )
    defaults.update(overrides)
    return Book(**defaults)


def _paperdesk_state(**overrides: object) -> object:
    from app.paperdesk.models import PaperDeskState

    books = overrides.pop("books", [_paperdesk_book()])
    defaults: dict[str, object] = dict(
        inception=dt.date(2026, 1, 1),
        as_of=AS_OF,
        latest_bar=AS_OF,
        stale_days=0,
        first_session=dt.date(2026, 1, 2),
        sessions=100,
        inception_default=dt.date(2026, 1, 1),
        inception_is_custom=False,
        design_cutoff=dt.date(2025, 12, 31),
        in_sample_sessions=0,
        earliest_inception=dt.date(2020, 1, 1),
        latest_inception=AS_OF,
        notes=[],
        books=books,
    )
    defaults.update(overrides)
    return PaperDeskState(**defaults)


def test_paperdesk_section_happy_path(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    state = _paperdesk_state()
    monkeypatch.setattr("app.paperdesk.desk.state", lambda settings: state)

    section = sources_owner.paperdesk_section(_ctx(settings))

    assert section.key == "paperdesk"
    assert section.ok is True
    assert len(section.items) == 1
    item = section.items[0]
    assert item.id == "b-momentum"
    assert item.figures["equity"] == "11500.00"
    assert item.figures["excess_return"] == "0.03"
    _assert_figures_are_pinned_and_decimal(section)
    _assert_unique_item_ids(section)


def test_paperdesk_section_upstream_failure_is_ok_false(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(settings: object) -> object:
        raise RuntimeError("desk blew up")

    monkeypatch.setattr("app.paperdesk.desk.state", _raise)

    section = sources_owner.paperdesk_section(_ctx(settings))

    assert section.ok is False
    assert section.warnings
    assert section.items == ()


# ---------------------------------------------------------------------------
# persona_books_section
# ---------------------------------------------------------------------------


def _persona_book(**overrides: object) -> object:
    from app.personas.models import PersonaBook

    defaults: dict[str, object] = dict(
        persona="alpha",
        display_name="Alpha",
        inception=dt.date(2026, 1, 1),
        as_of=AS_OF,
        notional_per_position=Decimal("1000.00"),
        equity=Decimal("10500.00"),
        return_pct=Decimal("0.05"),
        open_count=2,
        trade_count=5,
    )
    defaults.update(overrides)
    return PersonaBook(**defaults)


def test_persona_books_section_happy_path(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    books = [_persona_book()]
    monkeypatch.setattr("app.personas.service.persona_books", lambda settings: books)

    section = sources_owner.persona_books_section(_ctx(settings))

    assert section.key == "persona_books"
    assert section.ok is True
    assert len(section.items) == 1
    item = section.items[0]
    assert item.id == "alpha"
    assert item.figures["equity"] == "10500.00"
    assert item.figures["open_count"] == "2"
    _assert_figures_are_pinned_and_decimal(section)
    _assert_unique_item_ids(section)


def test_persona_books_section_upstream_failure_is_ok_false(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(settings: object) -> object:
        raise RuntimeError("vault read failed")

    monkeypatch.setattr("app.personas.service.persona_books", _raise)

    section = sources_owner.persona_books_section(_ctx(settings))

    assert section.ok is False
    assert section.warnings
    assert section.items == ()


# ---------------------------------------------------------------------------
# persona_traders_section
# ---------------------------------------------------------------------------


def _trader_decision(**overrides: object) -> object:
    from app.personas.trader import TraderDecisionRec

    defaults: dict[str, object] = dict(
        decided_on="2026-06-14",
        fill_date="2026-06-15",
        commentary="bought the dip on strong volume",
        degraded=False,
        cost_usd="0.05",
    )
    defaults.update(overrides)
    return TraderDecisionRec(**defaults)


def _trader_position(**overrides: object) -> object:
    from app.personas.trader import TraderPosition

    defaults: dict[str, object] = dict(
        symbol="AAPL", quantity="10", last_price="150.00", market_value="1500.00", weight=0.3,
    )
    defaults.update(overrides)
    return TraderPosition(**defaults)


def _trader_book(**overrides: object) -> object:
    from app.personas.trader import TraderBook

    defaults: dict[str, object] = dict(
        persona="alpha",
        display_name="Alpha",
        inception="2026-01-01",
        as_of="2026-06-15",
        starting_cash="100000.00",
        cash="98500.00",
        equity="102000.00",
        return_pct="0.02",
        benchmark_return_pct="0.01",
        excess_pct="0.01",
        positions=(_trader_position(),),
        decisions=(_trader_decision(),),
    )
    defaults.update(overrides)
    return TraderBook(**defaults)


def test_persona_traders_section_happy_path(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    books = [_trader_book()]
    monkeypatch.setattr("app.personas.trader_service.list_trader_books", lambda settings: books)

    section = sources_owner.persona_traders_section(_ctx(settings))

    assert section.key == "persona_traders"
    assert section.ok is True
    assert len(section.items) == 1
    item = section.items[0]
    assert item.id == "alpha"
    assert item.figures["equity"] == "102000.00"
    assert item.figures["decision_count"] == "1"
    assert item.figures["positions"] == "1"
    assert "bought the dip" in item.text
    _assert_figures_are_pinned_and_decimal(section)
    _assert_unique_item_ids(section)


def test_persona_traders_section_no_decisions_has_no_commentary(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    books = [_trader_book(decisions=())]
    monkeypatch.setattr("app.personas.trader_service.list_trader_books", lambda settings: books)

    section = sources_owner.persona_traders_section(_ctx(settings))

    assert section.items[0].figures["decision_count"] == "0"


def test_persona_traders_section_upstream_failure_is_ok_false(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(settings: object) -> object:
        raise RuntimeError("trader store blew up")

    monkeypatch.setattr("app.personas.trader_service.list_trader_books", _raise)

    section = sources_owner.persona_traders_section(_ctx(settings))

    assert section.ok is False
    assert section.warnings
    assert section.items == ()

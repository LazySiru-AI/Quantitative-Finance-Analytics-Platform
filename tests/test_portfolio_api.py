"""The portfolio endpoint, backed by a real SQLite ledger.

Mirrors ``tests/test_tax_engine.py``'s API section: the ledger is written through the real store
(not built in memory) so these tests exercise the same round trip a user's request takes, and pricing
is stubbed per symbol so a single request can exercise both a priced and a provider-refused symbol at
once -- the "degrade per symbol, never fail the whole request" rule this endpoint exists to prove.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api import portfolio
from app.config import Settings
from app.core.models import Account, AccountType, Broker, TaxTreatment, TxnAction
from app.db import sqlite as ledger
from app.main import app
from app.market.models import Bar, Interval
from tests.conftest import make_txn

RH_TAXABLE = Account(
    account_id="rh-taxable",
    broker=Broker.ROBINHOOD,
    label="RH Taxable",
    tax_treatment=TaxTreatment.TAXABLE,
    account_type=AccountType.CASH,
)
WB_MARGIN = Account(
    account_id="wb-margin",
    broker=Broker.WEBULL,
    label="Webull Margin",
    tax_treatment=TaxTreatment.TAXABLE,
    account_type=AccountType.MARGIN,
)
ACCOUNTS = {a.account_id: a for a in (RH_TAXABLE, WB_MARGIN)}


def _record_import(conn: sqlite3.Connection, import_id: str, account_id: str, broker: str) -> None:
    """Satisfy the provenance foreign key for one account's rows."""
    conn.execute(
        "INSERT OR IGNORE INTO raw_import (import_id, source_path, filename, file_sha256, "
        "content_hash, broker, account_id, adapter, adapter_version, row_count, "
        "usable_row_count, imported_at) VALUES (?, 'p', 'f.csv', ?, ?, ?, ?, ?, '1', 1, 1, "
        "'2026-01-01T00:00:00Z')",
        (import_id, f"sha-{import_id}", f"content-{import_id}", broker, account_id, broker),
    )


def _portfolio_transactions() -> list:
    """Three symbols across two accounts: AAA held in both, BBB and CCC each in one."""
    return [
        make_txn(
            txn_id="buy-aaa-rh",
            action=TxnAction.BUY,
            symbol="AAA",
            quantity="10",
            price="100",
            amount="-1000",
            trade_date=dt.date(2024, 1, 1),
            account_id="rh-taxable",
            broker=Broker.ROBINHOOD,
            import_id="imp-rh",
            source_row=0,
        ),
        make_txn(
            txn_id="buy-aaa-wb",
            action=TxnAction.BUY,
            symbol="AAA",
            quantity="5",
            price="90",
            amount="-450",
            trade_date=dt.date(2024, 2, 1),
            account_id="wb-margin",
            broker=Broker.WEBULL,
            import_id="imp-wb",
            source_row=0,
        ),
        make_txn(
            txn_id="buy-bbb",
            action=TxnAction.BUY,
            symbol="BBB",
            quantity="3",
            price="50",
            amount="-150",
            trade_date=dt.date(2024, 3, 1),
            account_id="rh-taxable",
            broker=Broker.ROBINHOOD,
            import_id="imp-rh",
            source_row=1,
        ),
        make_txn(
            txn_id="buy-ccc",
            action=TxnAction.BUY,
            symbol="CCC",
            quantity="2",
            price="10",
            amount="-20",
            trade_date=dt.date(2024, 4, 15),
            account_id="rh-taxable",
            broker=Broker.ROBINHOOD,
            import_id="imp-rh",
            source_row=2,
        ),
    ]


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def seeded(settings: Settings, client: TestClient) -> Settings:
    with ledger.connect(settings.ledger_path) as conn:
        ledger.migrate(conn)
        ledger.upsert_account(conn, RH_TAXABLE)
        ledger.upsert_account(conn, WB_MARGIN)
        _record_import(conn, "imp-rh", "rh-taxable", "robinhood")
        _record_import(conn, "imp-wb", "wb-margin", "webull")
        ledger.insert_transactions(conn, _portfolio_transactions())
    return settings


def _bar(price: str) -> Bar:
    value = float(price)
    return Bar(
        ts=dt.datetime(2024, 12, 31, tzinfo=dt.UTC),
        open=value,
        high=value,
        low=value,
        close=value,
        adj_close=value,
        volume=1000,
    )


def _stub_prices(monkeypatch: pytest.MonkeyPatch, prices: dict[str, str]) -> None:
    """Price every symbol in ``prices``; anything else is simply absent, as if the store had nothing
    and the provider refused it too.

    `_build_report` prices every open position through one call to `store.latest_two_bars` rather
    than `store.ensure_series` in a loop (see `app.api.portfolio._build_report`'s docstring on the
    pricing section) -- this stub patches that batched entry point instead, matching its
    ``dict[symbol, tuple[Bar, Bar | None]]`` return shape where an unpriceable symbol is simply
    absent from the dict rather than raising. The second element is ``None`` here (no prior close),
    so day-change fields come back ``None``; the day-change-specific behaviour is exercised in
    ``tests/test_portfolio_account_summary.py`` where a real prior bar is supplied. The legacy
    ``latest_bars`` entry point is patched too, harmlessly, so any caller that still reaches for it
    also gets stubbed values rather than a live network call.
    """

    def latest_bars(symbols: object, interval: Interval, **kwargs: object) -> dict[str, Bar]:
        return {symbol: _bar(prices[symbol]) for symbol in prices}

    def latest_two_bars(
        symbols: object, interval: Interval, **kwargs: object
    ) -> dict[str, tuple[Bar, Bar | None]]:
        return {symbol: (_bar(prices[symbol]), None) for symbol in prices}

    monkeypatch.setattr(portfolio.store, "latest_bars", latest_bars)
    monkeypatch.setattr(portfolio.store, "latest_two_bars", latest_two_bars)


class TestPortfolioApi:
    def test_missing_ledger_is_a_404(self, client: TestClient, settings: Settings) -> None:
        assert client.get("/api/portfolio").status_code == 404

    def test_unpriced_symbol_does_not_fail_the_request(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CCC's provider call raises; AAA and BBB still price and the request still succeeds."""
        _stub_prices(monkeypatch, {"AAA": "120", "BBB": "60"})

        response = client.get("/api/portfolio")
        assert response.status_code == 200
        body = response.json()

        assert body["unpriced_symbols"] == ["CCC"]
        assert body["priced_position_count"] == 2

        by_symbol = {p["symbol"]: p for p in body["positions"]}
        ccc = by_symbol["CCC"]
        assert ccc["price"] is None
        assert ccc["price_as_of"] is None
        assert ccc["market_value"] is None
        assert ccc["unrealized"] is None
        assert ccc["unrealized_pct"] is None
        assert ccc["weight_pct"] is None
        # Its cost basis is still known and still a decimal string, unlike the priced fields.
        assert ccc["cost_basis"] == "20.00"

    def test_priced_positions_compute_market_value_and_weights(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_prices(monkeypatch, {"AAA": "120", "BBB": "60"})

        response = client.get("/api/portfolio")
        body = response.json()
        by_symbol = {p["symbol"]: p for p in body["positions"]}

        # Prices come off `Bar.close`, a market *float*, and are quantized to cents at the boundary
        # (app.api.portfolio._price) -- so every monetary field arrives at exactly two decimal
        # places. Before that, `Decimal(str(float))` preserved the float's full repr and a $777.88
        # close crossed the wire as "1555.7600097656250"; see the comment on `_price`.
        aaa = by_symbol["AAA"]
        assert aaa["quantity"] == "15"
        assert aaa["cost_basis"] == "1450.00"
        assert aaa["price"] == "120.00"
        assert aaa["market_value"] == "1800.00"
        assert aaa["unrealized"] == "350.00"
        assert len(aaa["accounts"]) == 2

        bbb = by_symbol["BBB"]
        assert bbb["market_value"] == "180.00"

        # Money crosses the wire as a decimal string, never a bare JSON number.
        assert isinstance(aaa["market_value"], str)

        # Totals: market value sums the priced positions only; cost basis includes everything.
        assert body["total_cost_basis"] == "1620.00"  # 1450 + 150 + 20
        assert body["total_market_value"] == "1980.00"  # 1800.00 + 180.00
        assert body["total_unrealized"] == "380.00"  # 1980.00 - (1450 + 150)

        # Weights are a share of total market value and sum to 1 across priced positions -- a
        # float comparison, not a money one, so approx is the right tool here.
        weight_sum = sum(p["weight_pct"] for p in body["positions"] if p["weight_pct"] is not None)
        assert weight_sum == pytest.approx(1.0)
        assert by_symbol["CCC"]["weight_pct"] is None

    def test_a_float_stored_price_does_not_leak_binary_noise_into_money(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The bar store holds 32-bit floats, and $777.88 is not one of them.

        `777.8800048828125` is the exact float32 image of a $777.88 close, and it is what the store
        reads back. `Decimal(str(bar.close))` faithfully preserves all thirteen digits — the comment
        that used to sit on `_price` claimed the `str()` hop *avoided* the imprecision, which it
        never did — so `"market_value": "1555.7600097656250"` crossed the API in an application
        whose first standing decision is that money is never a float.

        Found by a UAT persona, who named the consequence rather than the aesthetics: a raw pull
        from this endpoint could not be trusted without re-rounding it first.

        The price is quoted to the cent, so rounding here *recovers* $777.88 rather than discarding
        precision — which is why this asserts the real value and not merely a shorter string.
        """
        _stub_prices(monkeypatch, {"AAA": "777.8800048828125"})

        body = client.get("/api/portfolio").json()
        aaa = next(p for p in body["positions"] if p["symbol"] == "AAA")

        assert aaa["price"] == "777.88"
        assert aaa["market_value"] == "11668.20"  # 15 shares
        assert body["total_market_value"] == "11668.20"

        for field in ("price", "market_value", "unrealized"):
            value = aaa[field]
            assert value is not None
            _, _, fraction = str(value).partition(".")
            assert len(fraction) <= 2, f"{field} carries sub-cent digits: {value}"

    def test_positions_sum_across_accounts_for_the_same_instrument(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_prices(monkeypatch, {"AAA": "120", "BBB": "60", "CCC": "10"})

        response = client.get("/api/portfolio")
        body = response.json()
        aaa = next(p for p in body["positions"] if p["symbol"] == "AAA")

        by_account = {a["account_id"]: a for a in aaa["accounts"]}
        assert by_account["rh-taxable"]["quantity"] == "10"
        assert by_account["rh-taxable"]["cost_basis"] == "1000.00"
        assert by_account["wb-margin"]["quantity"] == "5"
        assert by_account["wb-margin"]["cost_basis"] == "450.00"
        assert by_account["wb-margin"]["broker"] == "webull"

    def test_as_of_is_the_last_transaction_date(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_prices(monkeypatch, {"AAA": "120", "BBB": "60", "CCC": "10"})
        response = client.get("/api/portfolio")
        assert response.json()["as_of"] == "2024-04-15"

    def test_all_symbols_unpriced_yields_a_null_total_market_value(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_prices(monkeypatch, {})  # every symbol refused

        response = client.get("/api/portfolio")
        body = response.json()

        assert body["total_market_value"] is None
        assert body["total_unrealized"] is None
        assert body["priced_position_count"] == 0
        assert sorted(body["unpriced_symbols"]) == ["AAA", "BBB", "CCC"]
        # Cost basis is always knowable from the ledger, priced or not.
        assert body["total_cost_basis"] == "1620.00"


def _funded_account(settings: Settings, *, with_sale: bool = False) -> None:
    """A single account whose export starts with its deposit -- the case where cash *can* derive.

    The module-level `seeded` fixture is deliberately the opposite: neither of its accounts has a
    funding row, so it can only ever exercise the withheld path.
    """
    rows = [
        make_txn(
            txn_id="dep",
            action=TxnAction.CASH_IN,
            symbol=None,
            quantity=None,
            price=None,
            amount="5000.00",
            trade_date=dt.date(2026, 1, 2),
            import_id="imp-rh",
            source_row=0,
        ),
        make_txn(
            txn_id="buy",
            action=TxnAction.BUY,
            symbol="AAA",
            quantity="10",
            price="100.00",
            amount="-1000.00",
            trade_date=dt.date(2026, 1, 5),
            import_id="imp-rh",
            source_row=1,
        ),
    ]
    if with_sale:
        rows.append(
            make_txn(
                txn_id="sell",
                action=TxnAction.SELL,
                symbol="AAA",
                quantity="2",
                price="120.00",
                amount="240.00",
                trade_date=dt.date(2026, 1, 20),
                settle_date=dt.date(2026, 1, 21),
                import_id="imp-rh",
                source_row=2,
            )
        )

    with ledger.connect(settings.ledger_path) as conn:
        ledger.migrate(conn)
        ledger.upsert_account(conn, RH_TAXABLE)
        _record_import(conn, "imp-rh", "rh-taxable", "robinhood")
        ledger.insert_transactions(conn, rows)


def _funded_account_with_two_settlement_dates(settings: Settings) -> None:
    """One account whose pending proceeds settle on two different dates -- a sale settling the day
    after `as_of` and a dividend settling two days after that. Exercises the range behavior at the
    wire, not just inside `app.core.cash` (already covered by `tests/test_cash.py`): this pins that
    the API actually carries both ends of the range through `PortfolioReport` and `AccountCashBalance`
    rather than collapsing them along the way.
    """
    rows = [
        make_txn(
            txn_id="dep",
            action=TxnAction.CASH_IN,
            symbol=None,
            quantity=None,
            price=None,
            amount="5000.00",
            trade_date=dt.date(2026, 1, 2),
            import_id="imp-rh",
            source_row=0,
        ),
        make_txn(
            txn_id="buy",
            action=TxnAction.BUY,
            symbol="AAA",
            quantity="10",
            price="100.00",
            amount="-1000.00",
            trade_date=dt.date(2026, 1, 5),
            import_id="imp-rh",
            source_row=1,
        ),
        make_txn(
            txn_id="sell",
            action=TxnAction.SELL,
            symbol="AAA",
            quantity="2",
            price="120.00",
            amount="240.00",
            trade_date=dt.date(2026, 1, 20),
            settle_date=dt.date(2026, 1, 21),
            import_id="imp-rh",
            source_row=2,
        ),
        make_txn(
            txn_id="div",
            action=TxnAction.DIVIDEND,
            symbol=None,
            quantity=None,
            price=None,
            amount="12.34",
            trade_date=dt.date(2026, 1, 20),
            settle_date=dt.date(2026, 1, 23),
            import_id="imp-rh",
            source_row=3,
        ),
    ]

    with ledger.connect(settings.ledger_path) as conn:
        ledger.migrate(conn)
        ledger.upsert_account(conn, RH_TAXABLE)
        _record_import(conn, "imp-rh", "rh-taxable", "robinhood")
        ledger.insert_transactions(conn, rows)


class TestCashAndEquity:
    """Cash on the portfolio report.

    `tests/test_cash.py` covers the derivation rules themselves; this covers the wiring, and in
    particular the rule that equity is withheld unless *both* halves are complete.
    """

    def test_neither_seeded_account_can_supply_cash(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both seeded accounts have trades and no funding rows -- Webull's real shape."""
        _stub_prices(monkeypatch, {"AAA": "120", "BBB": "60", "CCC": "10"})

        body = client.get("/api/portfolio").json()

        assert body["cash_balance"] is None
        assert sorted(body["accounts_without_cash"]) == ["rh-taxable", "wb-margin"]
        assert {a["verdict"] for a in body["cash_by_account"]} == {"no_funding_rows"}
        assert all(a["balance"] is None for a in body["cash_by_account"])

    def test_every_withheld_account_says_why(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A withheld figure with no explanation is a dead end: the user cannot tell whether to
        re-export further back or whether this broker can never supply one."""
        _stub_prices(monkeypatch, {"AAA": "120", "BBB": "60", "CCC": "10"})

        body = client.get("/api/portfolio").json()

        for entry in body["cash_by_account"]:
            if entry["verdict"] != "derived":
                assert entry["reason"]

    def test_equity_is_withheld_when_only_cash_is_missing(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Everything prices, so market value is complete -- and equity is still null, because the
        other half is absent. An equity figure that quietly means "positions only" is the most
        misleading number this endpoint could produce."""
        _stub_prices(monkeypatch, {"AAA": "120", "BBB": "60", "CCC": "10"})

        body = client.get("/api/portfolio").json()

        assert body["unpriced_symbols"] == []
        assert body["total_market_value"] is not None
        assert body["total_equity"] is None
        assert body["equity_is_complete"] is False

    def test_equity_is_withheld_when_only_a_price_is_missing(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The mirror case: cash derives cleanly, a symbol does not price."""
        _funded_account(settings)
        _stub_prices(monkeypatch, {})

        body = client.get("/api/portfolio").json()

        assert body["cash_balance"] == "4000.00"
        assert body["unpriced_symbols"] == ["AAA"]
        assert body["total_equity"] is None
        assert body["equity_is_complete"] is False

    def test_equity_is_the_sum_when_both_halves_are_complete(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _funded_account(settings)
        _stub_prices(monkeypatch, {"AAA": "120"})

        body = client.get("/api/portfolio").json()

        assert body["cash_balance"] == "4000.00"
        assert body["equity_is_complete"] is True
        # 4000 cash + 10 shares at 120. Compared as Decimal because the price crosses a float
        # boundary on its way out of the bar store and the trailing-zero form is not guaranteed.
        assert Decimal(body["total_equity"]) == Decimal("5200")
        assert Decimal(body["total_equity"]) == Decimal(body["cash_balance"]) + Decimal(
            body["total_market_value"]
        )

    def test_settled_and_unsettled_are_broken_out(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """What can I deploy on Monday -- unanswerable from this page before."""
        _funded_account(settings, with_sale=True)
        _stub_prices(monkeypatch, {"AAA": "120"})

        body = client.get("/api/portfolio").json()

        # `as_of` is the last trade date (2026-01-20), so the next-day settlement is still pending.
        assert body["cash_balance"] == "4240.00"
        assert body["unsettled_cash"] == "240.00"
        assert body["settled_cash"] == "4000.00"

    def test_unsettled_cash_carries_its_settlement_date(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`portfolio-unsettled-cash-lacks-settlement-date` (BACKLOG.md §R13): the date the sale
        settles on was always computed inside `app.core.cash` and discarded before it reached this
        endpoint. One pending row means the report-level and per-account "next" and "full" dates all
        agree -- the range collapses to the single date that backs the whole unsettled figure."""
        _funded_account(settings, with_sale=True)
        _stub_prices(monkeypatch, {"AAA": "120"})

        body = client.get("/api/portfolio").json()

        assert body["unsettled_cash"] == "240.00"
        assert body["unsettled_next_date"] == "2026-01-21"
        assert body["unsettled_full_date"] == "2026-01-21"

        account_row = next(a for a in body["cash_by_account"] if a["account_id"] == "rh-taxable")
        assert account_row["unsettled_next_date"] == "2026-01-21"
        assert account_row["unsettled_full_date"] == "2026-01-21"

    def test_settlement_range_when_pending_inflows_differ(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A sale settling one day after `as_of` and a dividend settling three days after it are both
        inside `unsettled_cash` -- the report states when the *first* dollar clears and separately
        when *every* dollar has, rather than picking one date and letting it silently stand for the
        other."""
        _funded_account_with_two_settlement_dates(settings)
        _stub_prices(monkeypatch, {"AAA": "120"})

        body = client.get("/api/portfolio").json()

        assert body["unsettled_cash"] == "252.34"
        assert body["unsettled_next_date"] == "2026-01-21"
        assert body["unsettled_full_date"] == "2026-01-23"
        assert body["unsettled_next_date"] != body["unsettled_full_date"]

    def test_no_pending_inflow_reports_no_settlement_date(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The "nothing pending" state, distinct from "unknown": a fully-settled account reports a
        real `0` for `unsettled_cash` and `null` -- not a fabricated or stale-looking date -- for both
        settlement fields."""
        _funded_account(settings, with_sale=False)
        _stub_prices(monkeypatch, {"AAA": "120"})

        body = client.get("/api/portfolio").json()

        assert body["unsettled_cash"] == "0.00" or Decimal(body["unsettled_cash"]) == 0
        assert body["unsettled_next_date"] is None
        assert body["unsettled_full_date"] is None


class TestStatementExport:
    """The Markdown statement.

    The artifact a professional produces at the end of a period. Impossible before cash existed --
    a statement that omits the cash half of the account is not a statement -- so these tests are
    mostly about it staying honest when the underlying figures are incomplete.
    """

    def test_it_downloads_as_markdown_named_for_the_as_of(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _funded_account(settings)
        _stub_prices(monkeypatch, {"AAA": "120"})

        response = client.get("/api/portfolio/statement.md")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
        assert "portfolio-statement-2026-01-05.md" in response.headers["content-disposition"]

    def test_a_complete_statement_carries_the_figures_and_no_caveats(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _funded_account(settings)
        _stub_prices(monkeypatch, {"AAA": "120"})

        text = client.get("/api/portfolio/statement.md").text

        assert "# Portfolio statement" in text
        assert "$4,000.00" in text  # cash
        assert "$5,200.00" in text  # equity
        assert "## Completeness" not in text, "nothing is missing, so nothing should be flagged"
        assert "not investment advice" in text

    def test_caveats_travel_with_the_document(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An exported file outlives the screen it came from. A reader months later must be able to
        tell a complete statement from a partial one without this application in front of them."""
        _stub_prices(monkeypatch, {"AAA": "120", "BBB": "60"})  # CCC refused

        text = client.get("/api/portfolio/statement.md").text

        assert "## Completeness" in text
        assert "CCC" in text, "the unpriced symbol must be named in the document"
        assert "Cash unavailable" in text
        assert "No total equity is stated" in text

    def test_absent_figures_render_as_a_dash_not_zero(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`$0.00` for a withheld cash balance would be a number, and a wrong one."""
        _stub_prices(monkeypatch, {"AAA": "120", "BBB": "60", "CCC": "10"})

        text = client.get("/api/portfolio/statement.md").text
        cash_line = next(line for line in text.splitlines() if line.startswith("| Cash"))

        assert "—" in cash_line
        assert "$0.00" not in cash_line

    def test_weights_are_labelled_as_a_share_of_invested(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same trap as the UI column: weights sum to ~100% while cash sits outside them."""
        _funded_account(settings)
        _stub_prices(monkeypatch, {"AAA": "120"})

        text = client.get("/api/portfolio/statement.md").text

        assert "not of total equity" in text

    def test_the_statement_states_when_unsettled_cash_clears(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An exported statement outlives the screen it was generated from -- the same reasoning
        `test_caveats_travel_with_the_document` applies to the unpriced/withheld-cash caveats applies
        here to the settlement date behind `unsettled_cash`."""
        _funded_account(settings, with_sale=True)
        _stub_prices(monkeypatch, {"AAA": "120"})

        text = client.get("/api/portfolio/statement.md").text
        unsettled_line = next(
            line for line in text.splitlines() if line.startswith("| — unsettled")
        )

        assert "2026-01-21" in unsettled_line
        assert "clears" in unsettled_line

        by_account_line = next(
            line for line in text.splitlines() if line.startswith("| RH Taxable")
        )
        assert "2026-01-21" in by_account_line

    def test_the_statement_names_no_clearing_date_when_nothing_is_pending(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _funded_account(settings, with_sale=False)
        _stub_prices(monkeypatch, {"AAA": "120"})

        text = client.get("/api/portfolio/statement.md").text
        unsettled_line = next(
            line for line in text.splitlines() if line.startswith("| — unsettled")
        )

        assert "clears" not in unsettled_line

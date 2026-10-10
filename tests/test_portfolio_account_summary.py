"""Account summaries, sectors, day change and closed-account exclusion on the portfolio report.

Mirrors ``tests/test_portfolio_api.py``'s fixture shape (a real SQLite ledger written through the
store, pricing stubbed per symbol) but seeds one open and one closed account so the closed-account
exclusion rule, the all-time per-account realized gain aggregation, and the day-over-day pricing
added on top of `PortfolioReport` all have something to disagree about.
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
from app.core.models import Account, AccountStatus, AccountType, Broker, TaxTreatment, TxnAction
from app.db import sqlite as ledger
from app.main import app
from app.market.models import Bar, Interval
from tests.conftest import make_txn

RH_OPEN = Account(
    account_id="rh-open",
    broker=Broker.ROBINHOOD,
    label="RH Open",
    tax_treatment=TaxTreatment.TAXABLE,
    account_type=AccountType.CASH,
    status=AccountStatus.OPEN,
)
WB_CLOSED = Account(
    account_id="wb-closed",
    broker=Broker.WEBULL,
    label="WB Closed",
    tax_treatment=TaxTreatment.TAXABLE,
    account_type=AccountType.MARGIN,
    status=AccountStatus.CLOSED,
)
ACCOUNTS = {a.account_id: a for a in (RH_OPEN, WB_CLOSED)}


def _record_import(conn: sqlite3.Connection, import_id: str, account_id: str, broker: str) -> None:
    """Satisfy the provenance foreign key for one account's rows."""
    conn.execute(
        "INSERT OR IGNORE INTO raw_import (import_id, source_path, filename, file_sha256, "
        "content_hash, broker, account_id, adapter, adapter_version, row_count, "
        "usable_row_count, imported_at) VALUES (?, 'p', 'f.csv', ?, ?, ?, ?, ?, '1', 1, 1, "
        "'2026-01-01T00:00:00Z')",
        (import_id, f"sha-{import_id}", f"content-{import_id}", broker, account_id, broker),
    )


def _ledger_transactions() -> list:
    """AAA is held in both accounts; BBB only in the open account; CCC only in the closed one.

    CCC is partially sold at a gain in the closed account, so that account's all-time realized gain
    is non-zero even though its holdings drop out of the current-holdings figures entirely.
    """
    return [
        make_txn(
            txn_id="buy-aaa-rh",
            action=TxnAction.BUY,
            symbol="AAA",
            quantity="10",
            price="100",
            amount="-1000",
            trade_date=dt.date(2024, 1, 1),
            account_id="rh-open",
            broker=Broker.ROBINHOOD,
            import_id="imp-rh",
            source_row=0,
        ),
        make_txn(
            txn_id="buy-bbb-rh",
            action=TxnAction.BUY,
            symbol="BBB",
            quantity="5",
            price="50",
            amount="-250",
            trade_date=dt.date(2024, 2, 1),
            account_id="rh-open",
            broker=Broker.ROBINHOOD,
            import_id="imp-rh",
            source_row=1,
        ),
        make_txn(
            txn_id="buy-aaa-wb",
            action=TxnAction.BUY,
            symbol="AAA",
            quantity="5",
            price="90",
            amount="-450",
            trade_date=dt.date(2024, 1, 15),
            account_id="wb-closed",
            broker=Broker.WEBULL,
            import_id="imp-wb",
            source_row=0,
        ),
        make_txn(
            txn_id="buy-ccc-wb",
            action=TxnAction.BUY,
            symbol="CCC",
            quantity="10",
            price="10",
            amount="-100",
            trade_date=dt.date(2024, 1, 20),
            account_id="wb-closed",
            broker=Broker.WEBULL,
            import_id="imp-wb",
            source_row=1,
        ),
        make_txn(
            txn_id="sell-ccc-wb",
            action=TxnAction.SELL,
            symbol="CCC",
            quantity="4",
            price="15",
            amount="60",
            trade_date=dt.date(2024, 6, 1),
            account_id="wb-closed",
            broker=Broker.WEBULL,
            import_id="imp-wb",
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
        ledger.upsert_account(conn, RH_OPEN)
        ledger.upsert_account(conn, WB_CLOSED)
        _record_import(conn, "imp-rh", "rh-open", "robinhood")
        _record_import(conn, "imp-wb", "wb-closed", "webull")
        ledger.insert_transactions(conn, _ledger_transactions())
    return settings


def _bar(price: str, ts: dt.datetime) -> Bar:
    value = float(price)
    return Bar(ts=ts, open=value, high=value, low=value, close=value, adj_close=value, volume=1000)


def _stub_two_bars(monkeypatch: pytest.MonkeyPatch, pairs: dict[str, tuple[str, str | None]]) -> None:
    """Stub `store.latest_two_bars`, the entry point `_build_report` now uses for pricing.

    `pairs` maps symbol -> (latest_close, previous_close | None). A symbol absent from `pairs` is
    simply absent from the returned dict, matching a provider refusal.
    """

    def latest_two_bars(
        symbols: object, interval: Interval, **kwargs: object
    ) -> dict[str, tuple[Bar, Bar | None]]:
        result: dict[str, tuple[Bar, Bar | None]] = {}
        for symbol, (latest, previous) in pairs.items():
            latest_bar = _bar(latest, dt.datetime(2024, 12, 31, tzinfo=dt.UTC))
            previous_bar = (
                _bar(previous, dt.datetime(2024, 12, 30, tzinfo=dt.UTC))
                if previous is not None
                else None
            )
            result[symbol] = (latest_bar, previous_bar)
        return result

    monkeypatch.setattr(portfolio.store, "latest_two_bars", latest_two_bars)


class TestClosedAccountExclusion:
    def test_a_symbol_unique_to_a_closed_account_is_excluded_entirely(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_two_bars(monkeypatch, {"AAA": ("150", "140"), "BBB": ("60", None)})

        body = client.get("/api/portfolio").json()

        symbols = {p["symbol"] for p in body["positions"]}
        assert "CCC" not in symbols
        assert body["excluded_closed_symbols"] == ["CCC"]

    def test_excluded_closed_positions_counts_dropped_account_slices_not_instruments(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_two_bars(monkeypatch, {"AAA": ("150", "140"), "BBB": ("60", None)})

        body = client.get("/api/portfolio").json()

        # Two account-level slices dropped: AAA's wb-closed slice and CCC's wb-closed slice --
        # not two instruments, since AAA survives (its rh-open slice is untouched).
        assert body["excluded_closed_positions"] == 2

    def test_an_instrument_split_between_open_and_closed_keeps_only_the_open_slice(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_two_bars(monkeypatch, {"AAA": ("150", "140"), "BBB": ("60", None)})

        body = client.get("/api/portfolio").json()

        aaa = next(p for p in body["positions"] if p["symbol"] == "AAA")
        # Rolled-up figures shrink to just rh-open's 10 shares -- wb-closed's 5 no longer count.
        assert aaa["quantity"] == "10"
        assert aaa["cost_basis"] == "1000.00"
        assert len(aaa["accounts"]) == 1
        assert aaa["accounts"][0]["account_id"] == "rh-open"

    def test_totals_reflect_open_accounts_only(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_two_bars(monkeypatch, {"AAA": ("150", "140"), "BBB": ("60", None)})

        body = client.get("/api/portfolio").json()

        # AAA: 10 sh @ 150 = 1500.00; BBB: 5 sh @ 60 = 300.00. wb-closed's AAA(5) and CCC(6 open)
        # contribute nothing -- their basis would otherwise inflate cost basis and unrealized.
        assert body["total_market_value"] == "1800.00"
        assert body["total_cost_basis"] == "1250.00"  # 1000 (AAA open) + 250 (BBB)
        assert body["total_unrealized"] == "550.00"  # 1800 - 1250


class TestDayChange:
    def test_two_bars_populate_day_change_and_pct(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_two_bars(monkeypatch, {"AAA": ("150", "140"), "BBB": ("60", None)})

        body = client.get("/api/portfolio").json()
        aaa = next(p for p in body["positions"] if p["symbol"] == "AAA")

        assert aaa["previous_close"] == "140.00"
        assert aaa["day_change"] == "100.00"  # (150 - 140) * 10 shares
        assert Decimal(aaa["day_change_pct"]) == pytest.approx(Decimal("10") / Decimal("140"))

    def test_one_bar_leaves_day_change_null(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_two_bars(monkeypatch, {"AAA": ("150", "140"), "BBB": ("60", None)})

        body = client.get("/api/portfolio").json()
        bbb = next(p for p in body["positions"] if p["symbol"] == "BBB")

        assert bbb["previous_close"] is None
        assert bbb["day_change"] is None
        assert bbb["day_change_pct"] is None

    def test_total_day_change_sums_priced_positions_with_a_previous_close(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_two_bars(monkeypatch, {"AAA": ("150", "140"), "BBB": ("60", None)})

        body = client.get("/api/portfolio").json()

        # Only AAA contributes (BBB has no previous close); total_market_value is 1800.00, so
        # yesterday's reconstructed value is 1800 - 100 = 1700.
        assert body["total_day_change"] == "100.00"
        assert Decimal(body["total_day_change_pct"]) == pytest.approx(Decimal("100") / Decimal("1700"))


class TestSector:
    def test_every_position_carries_a_non_null_sector(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_two_bars(monkeypatch, {"AAA": ("150", "140"), "BBB": ("60", None)})

        body = client.get("/api/portfolio").json()

        for position in body["positions"]:
            assert position["sector"] is not None
            assert isinstance(position["sector"], str)
            assert position["sector"] != ""


class TestAccountSummaries:
    def test_one_entry_per_account_with_correct_status(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_two_bars(monkeypatch, {"AAA": ("150", "140"), "BBB": ("60", None)})

        body = client.get("/api/portfolio").json()

        by_id = {a["account_id"]: a for a in body["accounts"]}
        assert set(by_id) == {"rh-open", "wb-closed"}
        assert by_id["rh-open"]["status"] == "open"
        assert by_id["wb-closed"]["status"] == "closed"
        assert body["open_account_count"] == 1

    def test_accounts_are_sorted_by_label(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_two_bars(monkeypatch, {"AAA": ("150", "140"), "BBB": ("60", None)})

        body = client.get("/api/portfolio").json()

        labels = [a["label"] for a in body["accounts"]]
        assert labels == sorted(labels)

    def test_a_closed_account_still_reports_its_all_time_realized_gain(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_two_bars(monkeypatch, {"AAA": ("150", "140"), "BBB": ("60", None)})

        body = client.get("/api/portfolio").json()

        by_id = {a["account_id"]: a for a in body["accounts"]}
        closed = by_id["wb-closed"]
        # 4 shares of CCC sold at 15, cost basis 10 each: proceeds 60, basis 40, gain 20.
        assert closed["realized_proceeds"] == "60.00"
        assert closed["disposed_cost_basis"] == "40.00"
        assert closed["realized_gain"] == "20.00"

    def test_an_account_with_no_disposals_reports_zero(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_two_bars(monkeypatch, {"AAA": ("150", "140"), "BBB": ("60", None)})

        body = client.get("/api/portfolio").json()

        by_id = {a["account_id"]: a for a in body["accounts"]}
        opened = by_id["rh-open"]
        assert opened["realized_gain"] == "0.00"
        assert opened["realized_proceeds"] == "0.00"
        assert opened["disposed_cost_basis"] == "0.00"

    def test_position_count_is_taken_before_the_closed_account_exclusion(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """wb-closed's own position count still says 2 (AAA + CCC) even though both are excluded
        from `positions` -- it is a fact about what the account holds, not about this report's
        totals."""
        _stub_two_bars(monkeypatch, {"AAA": ("150", "140"), "BBB": ("60", None)})

        body = client.get("/api/portfolio").json()

        by_id = {a["account_id"]: a for a in body["accounts"]}
        assert by_id["wb-closed"]["position_count"] == 2
        assert by_id["rh-open"]["position_count"] == 2

    def test_cash_by_account_is_not_filtered_by_status(
        self, client: TestClient, seeded: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_two_bars(monkeypatch, {"AAA": ("150", "140"), "BBB": ("60", None)})

        body = client.get("/api/portfolio").json()

        cash_account_ids = {entry["account_id"] for entry in body["cash_by_account"]}
        assert cash_account_ids == {"rh-open", "wb-closed"}

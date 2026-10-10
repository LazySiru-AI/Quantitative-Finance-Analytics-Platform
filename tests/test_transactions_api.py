"""The transaction-history endpoint.

Unlike every other read endpoint, this one returns stored rows rather than derived state, so the
tests are about faithfulness rather than calculation: the rows that come back must be the rows in the
ledger, carrying the provenance that lets a reader find the CSV line behind each one.

The properties worth pinning are the ones a caller would otherwise get subtly wrong:

* aggregates describe the **filtered set**, not the page -- the bug a client writes for itself the
  moment it tries to compute them from ``transactions``;
* paging neither drops nor repeats a row, in either direction;
* filters compose, and an unknown filter value is a 422 rather than a silently empty result.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.models import Account, AccountType, Broker, TaxTreatment, TxnAction
from app.db import sqlite as ledger
from app.main import app
from tests.conftest import make_txn

RH = Account(
    account_id="rh-taxable",
    broker=Broker.ROBINHOOD,
    label="RH Taxable",
    tax_treatment=TaxTreatment.TAXABLE,
    account_type=AccountType.CASH,
)
WB = Account(
    account_id="wb-cash",
    broker=Broker.WEBULL,
    label="Webull Cash",
    tax_treatment=TaxTreatment.TAXABLE,
    account_type=AccountType.CASH,
)


def _record_import(conn: sqlite3.Connection, import_id: str, account_id: str, broker: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO raw_import (import_id, source_path, filename, file_sha256, "
        "content_hash, broker, account_id, adapter, adapter_version, row_count, "
        "usable_row_count, imported_at) VALUES (?, 'p', 'f.csv', ?, ?, ?, ?, ?, '1', 1, 1, "
        "'2026-01-01T00:00:00Z')",
        (import_id, f"sha-{import_id}", f"content-{import_id}", broker, account_id, broker),
    )


def _transactions() -> list:
    """A deposit, three buys, one sell and a fee, across two accounts and four months."""
    return [
        make_txn(
            txn_id="dep",
            action=TxnAction.CASH_IN,
            symbol=None,
            quantity=None,
            price=None,
            amount="10000.00",
            trade_date=dt.date(2026, 1, 2),
            import_id="imp-rh",
            source_row=0,
        ),
        make_txn(
            txn_id="buy-aaa",
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
            txn_id="buy-bbb",
            action=TxnAction.BUY,
            symbol="BBB",
            quantity="4",
            price="50.00",
            amount="-200.00",
            trade_date=dt.date(2026, 2, 5),
            import_id="imp-rh",
            source_row=2,
        ),
        make_txn(
            txn_id="sell-aaa",
            action=TxnAction.SELL,
            symbol="AAA",
            quantity="5",
            price="120.00",
            amount="600.00",
            trade_date=dt.date(2026, 3, 5),
            settle_date=dt.date(2026, 3, 6),
            import_id="imp-rh",
            source_row=3,
        ),
        make_txn(
            txn_id="fee",
            action=TxnAction.FEE,
            symbol=None,
            quantity=None,
            price=None,
            amount="-1.50",
            trade_date=dt.date(2026, 3, 5),
            import_id="imp-rh",
            source_row=4,
        ),
        make_txn(
            txn_id="buy-wb",
            action=TxnAction.BUY,
            symbol="AAA",
            quantity="2",
            price="110.00",
            amount="-220.00",
            trade_date=dt.date(2026, 4, 1),
            account_id="wb-cash",
            broker=Broker.WEBULL,
            import_id="imp-wb",
            source_row=0,
        ),
    ]


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def seeded(settings: Settings, client: TestClient) -> TestClient:
    with ledger.connect(settings.ledger_path) as conn:
        ledger.migrate(conn)
        ledger.upsert_account(conn, RH)
        ledger.upsert_account(conn, WB)
        _record_import(conn, "imp-rh", "rh-taxable", "robinhood")
        _record_import(conn, "imp-wb", "wb-cash", "webull")
        ledger.insert_transactions(conn, _transactions())
    return client


class TestEmptyLedger:
    """An empty ledger is an empty history, not an error.

    Deliberately different from ``/api/portfolio``, which 404s on an empty ledger because a portfolio
    of nothing is not a thing to render. "You have made no transactions" *is* a true and renderable
    answer, and the Activity page has an empty state that says so; a 404 would put an error message
    in front of a user whose only mistake was not having imported anything yet.

    The missing-*file* 404 is kept for the genuinely unconfigured case, though the app's lifespan
    hook creates and migrates the ledger at startup, so a served request never sees it.
    """

    def test_empty_ledger_returns_an_empty_page(self, client: TestClient) -> None:
        body = client.get("/api/portfolio/transactions").json()

        assert body["total"] == 0
        assert body["transactions"] == []
        assert body["has_more"] is False

    def test_absent_ledger_file_is_a_404(self, settings: Settings, client: TestClient) -> None:
        settings.ledger_path.unlink()

        assert client.get("/api/portfolio/transactions").status_code == 404


class TestListing:
    def test_returns_every_row_newest_first(self, seeded: TestClient) -> None:
        body = seeded.get("/api/portfolio/transactions").json()

        assert body["total"] == 6
        assert len(body["transactions"]) == 6
        dates = [row["trade_date"] for row in body["transactions"]]
        assert dates == sorted(dates, reverse=True)
        assert body["earliest"] == "2026-01-02"
        assert body["as_of"] == "2026-04-01"

    def test_oldest_first_is_the_exact_mirror(self, seeded: TestClient) -> None:
        newest = seeded.get("/api/portfolio/transactions").json()["transactions"]
        oldest = seeded.get(
            "/api/portfolio/transactions", params={"newest_first": False}
        ).json()["transactions"]

        assert [r["txn_id"] for r in oldest] == [r["txn_id"] for r in newest][::-1]

    def test_every_row_carries_its_provenance(self, seeded: TestClient) -> None:
        """The property the whole application is built around, and the reason this endpoint exists:
        each row names the import and the line within it."""
        rows = seeded.get("/api/portfolio/transactions").json()["transactions"]

        assert all(row["import_id"] for row in rows)
        assert all(isinstance(row["source_row"], int) for row in rows)
        coordinates = {(row["import_id"], row["source_row"]) for row in rows}
        assert len(coordinates) == len(rows), "a provenance coordinate must identify one row"

    def test_money_crosses_the_wire_as_strings(self, seeded: TestClient) -> None:
        """A cost basis round-tripped through an IEEE double is the bug this convention prevents."""
        raw = seeded.get("/api/portfolio/transactions").text

        assert '"amount":"-1000.00"' in raw.replace(" ", "")

    def test_rows_with_no_cash_effect_report_null_not_zero(self, seeded: TestClient) -> None:
        rows = seeded.get("/api/portfolio/transactions").json()["transactions"]
        deposit = next(r for r in rows if r["txn_id"] == "dep")

        assert deposit["quantity"] is None
        assert deposit["price"] is None
        assert deposit["symbol"] is None


class TestAggregates:
    def test_totals_cover_the_whole_filtered_set_not_the_page(self, seeded: TestClient) -> None:
        """The one thing a client cannot recompute correctly for itself."""
        page = seeded.get("/api/portfolio/transactions", params={"limit": 2}).json()

        assert len(page["transactions"]) == 2
        assert page["total"] == 6
        # 1000 + 200 + 220 across all six rows, not the two returned.
        assert Decimal(page["total_bought"]) == Decimal("1420.00")
        assert Decimal(page["total_sold"]) == Decimal("600.00")

    def test_net_cash_flow_includes_fees_and_income(self, seeded: TestClient) -> None:
        """Deliberately not ``sold - bought``: the hint on the UI tile says so because the
        arithmetic invites exactly that wrong reconciliation."""
        body = seeded.get("/api/portfolio/transactions").json()

        assert Decimal(body["net_cash_flow"]) == Decimal("9178.50")
        assert Decimal(body["net_cash_flow"]) != Decimal(body["total_sold"]) - Decimal(
            body["total_bought"]
        )

    def test_empty_result_reports_zeroes_and_null_dates(self, seeded: TestClient) -> None:
        body = seeded.get("/api/portfolio/transactions", params={"symbol": "ZZZZ"}).json()

        assert body["total"] == 0
        assert body["transactions"] == []
        assert body["as_of"] is None and body["earliest"] is None
        assert Decimal(body["total_bought"]) == 0


class TestFilters:
    def test_by_symbol_case_insensitively(self, seeded: TestClient) -> None:
        body = seeded.get("/api/portfolio/transactions", params={"symbol": "aaa"}).json()

        assert body["total"] == 3
        assert {r["symbol"] for r in body["transactions"]} == {"AAA"}

    def test_by_account(self, seeded: TestClient) -> None:
        body = seeded.get("/api/portfolio/transactions", params={"account_id": "wb-cash"}).json()

        assert body["total"] == 1
        assert body["transactions"][0]["txn_id"] == "buy-wb"

    def test_by_action(self, seeded: TestClient) -> None:
        body = seeded.get("/api/portfolio/transactions", params={"action": "sell"}).json()

        assert body["total"] == 1
        assert body["transactions"][0]["action"] == "sell"

    def test_trades_only_excludes_income_and_fees(self, seeded: TestClient) -> None:
        body = seeded.get("/api/portfolio/transactions", params={"trades_only": True}).json()

        assert body["total"] == 4
        assert {r["action"] for r in body["transactions"]} == {"buy", "sell"}

    def test_date_range_is_inclusive_at_both_ends(self, seeded: TestClient) -> None:
        body = seeded.get(
            "/api/portfolio/transactions",
            params={"start": "2026-01-02", "end": "2026-02-05"},
        ).json()

        assert {r["txn_id"] for r in body["transactions"]} == {"dep", "buy-aaa", "buy-bbb"}

    def test_filters_compose(self, seeded: TestClient) -> None:
        body = seeded.get(
            "/api/portfolio/transactions",
            params={"symbol": "AAA", "account_id": "rh-taxable", "trades_only": True},
        ).json()

        assert {r["txn_id"] for r in body["transactions"]} == {"buy-aaa", "sell-aaa"}


class TestValidation:
    def test_unknown_action_is_rejected_rather_than_returning_nothing(
        self, seeded: TestClient
    ) -> None:
        """An empty result would read as "you made no such trades" rather than "that is not a
        thing", which is a materially different answer."""
        response = seeded.get("/api/portfolio/transactions", params={"action": "purchase"})

        assert response.status_code == 422
        assert "purchase" in response.text

    def test_inverted_date_range_is_rejected(self, seeded: TestClient) -> None:
        response = seeded.get(
            "/api/portfolio/transactions", params={"start": "2026-06-01", "end": "2026-01-01"}
        )

        assert response.status_code == 422

    @pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 100_000}, {"offset": -1}])
    def test_out_of_range_paging_is_rejected(
        self, seeded: TestClient, params: dict[str, int]
    ) -> None:
        assert seeded.get("/api/portfolio/transactions", params=params).status_code == 422


class TestPaging:
    def test_pages_tile_the_set_without_gaps_or_repeats(self, seeded: TestClient) -> None:
        seen: list[str] = []
        offset = 0
        while True:
            body = seeded.get(
                "/api/portfolio/transactions", params={"limit": 2, "offset": offset}
            ).json()
            seen.extend(r["txn_id"] for r in body["transactions"])
            if not body["has_more"]:
                break
            offset += 2

        assert len(seen) == 6
        assert len(set(seen)) == 6

    def test_has_more_is_false_on_the_last_page(self, seeded: TestClient) -> None:
        body = seeded.get(
            "/api/portfolio/transactions", params={"limit": 2, "offset": 4}
        ).json()

        assert body["has_more"] is False
        assert len(body["transactions"]) == 2

    def test_offset_past_the_end_is_empty_but_still_reports_the_total(
        self, seeded: TestClient
    ) -> None:
        body = seeded.get("/api/portfolio/transactions", params={"offset": 500}).json()

        assert body["transactions"] == []
        assert body["total"] == 6
        assert body["has_more"] is False

    def test_paging_echoes_back_what_was_asked(self, seeded: TestClient) -> None:
        body = seeded.get(
            "/api/portfolio/transactions", params={"limit": 3, "offset": 1}
        ).json()

        assert body["limit"] == 3
        assert body["offset"] == 1

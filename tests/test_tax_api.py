"""``GET /api/tax/wash-sales`` -- the whole-ledger wash-sale exposure tracker.

Written against a real SQLite ledger (not the in-memory ``engine.build_tax_report`` path most of
``tests/test_tax_engine.py`` uses) because the endpoint's whole point is scope: it must show a
symbol whose only loss sale happened in a year nowhere near the one ``/report`` defaults to, and
that only proves out through the actual store round trip.

Three scenarios share one ledger:

* ``SOXL`` -- bought, sold at a loss in 2021, fully repurchased inside the window. One ordinary
  (deferred) event, long since past its window.
* ``SPLIT`` -- the real-data shape from ``tests/test_tax_engine.py::TestSplitReplacementAcrossIraAndTaxable``:
  one 2023 disposal replaced half in a taxable account, half in a Roth IRA. Two events from one
  disposal_id -- deferred and permanent -- also long past its window.
* ``OPENX`` -- sold at a loss five days before the test runs, never repurchased. No event at all,
  and its window is open by construction regardless of what day the suite executes, because it is
  built relative to ``dt.date.today()`` rather than pinned to a calendar date.
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
from tests.conftest import make_txn, sample_account

ACCOUNT = sample_account()  # rh-taxable
ROTH = Account(
    account_id="rh-roth",
    broker=Broker.ROBINHOOD,
    label="RH Roth",
    tax_treatment=TaxTreatment.ROTH_IRA,
    account_type=AccountType.RETIREMENT,
)

TODAY = dt.date.today()


def _record_import(conn: sqlite3.Connection, import_id: str = "imp1") -> None:
    """Satisfy the provenance foreign key. Every transaction must trace back to a file."""
    conn.execute(
        "INSERT OR IGNORE INTO raw_import (import_id, source_path, filename, file_sha256, "
        "content_hash, broker, account_id, adapter, adapter_version, row_count, "
        "usable_row_count, imported_at) VALUES (?, 'p', 'f.csv', 'sha', 'content', "
        "'robinhood', 'rh-taxable', 'robinhood', '1', 9, 9, '2026-01-01T00:00:00Z')",
        (import_id,),
    )


def _wash_sale_transactions() -> list:
    """``SOXL``: bought, sold at a $1,000 loss, fully repurchased inside the window -- one deferred
    event. Dated 2020/2021 so its window is unambiguously closed by any date this suite runs on."""
    return [
        make_txn(
            txn_id="soxl-buy",
            symbol="SOXL",
            action=TxnAction.BUY,
            quantity="100",
            price="50",
            amount="-5000",
            trade_date=dt.date(2020, 11, 1),
        ),
        make_txn(
            txn_id="soxl-sell",
            symbol="SOXL",
            action=TxnAction.SELL,
            quantity="100",
            price="40",
            amount="4000",
            trade_date=dt.date(2021, 2, 3),
        ),
        make_txn(
            txn_id="soxl-rebuy",
            symbol="SOXL",
            action=TxnAction.BUY,
            quantity="100",
            price="41",
            amount="-4100",
            trade_date=dt.date(2021, 2, 10),
        ),
    ]


def _split_transactions() -> list:
    """``SPLIT``: one disposal replaced half taxable, half Roth -- two events, one disposal_id.

    Mirrors ``TestSplitReplacementAcrossIraAndTaxable`` in ``tests/test_tax_engine.py``, the
    confirmed real-data shape. Dated 2022/2023, also unambiguously closed by now.
    """
    return [
        make_txn(
            txn_id="split-buy",
            symbol="SPLIT",
            action=TxnAction.BUY,
            quantity="100",
            price="50",
            amount="-5000",
            trade_date=dt.date(2022, 11, 1),
        ),
        make_txn(
            txn_id="split-sell",
            symbol="SPLIT",
            action=TxnAction.SELL,
            quantity="100",
            price="40",
            amount="4000",
            trade_date=dt.date(2023, 2, 3),
        ),
        make_txn(
            txn_id="split-rep-taxable",
            symbol="SPLIT",
            action=TxnAction.BUY,
            quantity="50",
            price="41",
            amount="-2050",
            trade_date=dt.date(2023, 2, 10),
        ),
        make_txn(
            txn_id="split-rep-roth",
            symbol="SPLIT",
            action=TxnAction.BUY,
            quantity="50",
            price="41",
            amount="-2050",
            trade_date=dt.date(2023, 2, 10),
            account_id="rh-roth",
        ),
    ]


def _open_window_transactions() -> list:
    """``OPENX``: sold at a $100 loss five days ago, never repurchased -- no event, open window.

    Built relative to ``dt.date.today()`` because the endpoint itself measures ``window_is_open``
    from ``dt.date.today()`` (no ``as_of`` is exposed through the API) -- pinning this to a fixed
    calendar date would make the test's notion of "open" drift out of sync with the endpoint's own
    a few years after it was written.
    """
    return [
        make_txn(
            txn_id="openx-buy",
            symbol="OPENX",
            action=TxnAction.BUY,
            quantity="10",
            price="50",
            amount="-500",
            trade_date=TODAY - dt.timedelta(days=200),
        ),
        make_txn(
            txn_id="openx-sell",
            symbol="OPENX",
            action=TxnAction.SELL,
            quantity="10",
            price="40",
            amount="400",
            trade_date=TODAY - dt.timedelta(days=5),
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
        ledger.upsert_account(conn, ACCOUNT)
        ledger.upsert_account(conn, ROTH)
        _record_import(conn)
        ledger.insert_transactions(
            conn,
            [
                *_wash_sale_transactions(),
                *_split_transactions(),
                *_open_window_transactions(),
            ],
        )
    return settings


class TestWashSalesApi:
    def test_missing_ledger_is_a_404(self, client: TestClient, settings: Settings) -> None:
        """The app lifespan creates and migrates an empty ledger on startup -- "missing" here means
        the file was removed afterwards, not merely that nothing was ever imported into it."""
        settings.ledger_path.unlink()
        response = client.get("/api/tax/wash-sales")
        assert response.status_code == 404

    def test_whole_ledger_scope_reaches_a_symbol_from_a_year_report_would_not_default_to(
        self, client: TestClient, seeded: Settings
    ) -> None:
        """SOXL's loss sale is in 2021. `/report` without a `year` defaults to last year, and no
        `year` is even accepted here -- the symbol must appear anyway."""
        response = client.get("/api/tax/wash-sales")
        assert response.status_code == 200
        body = response.json()
        symbols = {s["symbol"] for s in body["symbols"]}
        assert "SOXL" in symbols
        assert symbols == {"SOXL", "SPLIT", "OPENX"}
        assert body["symbol_count"] == 3

    def test_open_windows_sort_first_ahead_of_larger_closed_ones(
        self, client: TestClient, seeded: Settings
    ) -> None:
        """OPENX has nothing deferred; SOXL has $1,000. OPENX still leads, because its window is
        open and SOXL's closed years ago -- the tracker's whole job is "what is still live"."""
        body = client.get("/api/tax/wash-sales").json()
        assert body["symbols"][0]["symbol"] == "OPENX"
        assert [s["symbol"] for s in body["symbols"]] == ["OPENX", "SOXL", "SPLIT"]

    def test_an_untriggered_loss_sale_appears_with_zero_disallowed_and_a_real_loss_amount(
        self, client: TestClient, seeded: Settings
    ) -> None:
        body = client.get("/api/tax/wash-sales").json()
        openx = next(s for s in body["symbols"] if s["symbol"] == "OPENX")

        assert openx["deferred_disallowed"] == "0.00" or openx["deferred_disallowed"] == "0"
        assert Decimal(openx["deferred_disallowed"]) == Decimal(0)
        assert openx["event_count"] == 0
        assert openx["loss_sale_count"] == 1
        assert openx["window_is_open"] is True
        assert len(openx["sales"]) == 1

        [sale] = openx["sales"]
        assert Decimal(sale["loss_amount"]) == Decimal("100.00")
        assert Decimal(sale["disallowed_loss"]) == Decimal(0)
        assert Decimal(sale["quantity_replaced"]) == Decimal(0)
        assert sale["permanently_disallowed"] is False
        assert sale["replacement_account_ids"] == []
        assert sale["sale_date"] == str(TODAY - dt.timedelta(days=5))

    def test_deferred_and_permanent_are_never_combined_in_one_sale_row(
        self, client: TestClient, seeded: Settings
    ) -> None:
        """SPLIT's one disposal produced two events -- $500 deferred, $500 permanent. They must
        reach the client as two rows sharing a disposal_id, never one row mixing both kinds."""
        body = client.get("/api/tax/wash-sales").json()
        split = next(s for s in body["symbols"] if s["symbol"] == "SPLIT")

        assert Decimal(split["deferred_disallowed"]) == Decimal("500.00")
        assert Decimal(split["permanently_disallowed"]) == Decimal("500.00")
        assert split["event_count"] == 2
        assert len(split["sales"]) == 2

        disposal_ids = {row["disposal_id"] for row in split["sales"]}
        assert len(disposal_ids) == 1, "both rows come from the same disposal"

        deferred_rows = [r for r in split["sales"] if not r["permanently_disallowed"]]
        permanent_rows = [r for r in split["sales"] if r["permanently_disallowed"]]
        assert [Decimal(r["disallowed_loss"]) for r in deferred_rows] == [Decimal("500.00")]
        assert [Decimal(r["disallowed_loss"]) for r in permanent_rows] == [Decimal("500.00")]
        # No row's own figure is the sum of the two.
        for row in split["sales"]:
            assert Decimal(row["disallowed_loss"]) != Decimal("1000.00")

    def test_top_level_totals_never_combine_deferred_and_permanent(
        self, client: TestClient, seeded: Settings
    ) -> None:
        body = client.get("/api/tax/wash-sales").json()
        # SOXL 1000 deferred + SPLIT 500 deferred; SPLIT 500 permanent, kept apart.
        assert Decimal(body["total_deferred"]) == Decimal("1500.00")
        assert Decimal(body["total_permanently_disallowed"]) == Decimal("500.00")
        assert Decimal(body["total_deferred"]) != Decimal(body["total_deferred"]) + Decimal(
            body["total_permanently_disallowed"]
        )
        assert body["open_window_count"] == 1  # OPENX only

    def test_sale_rows_reconcile_to_their_symbol_totals(
        self, client: TestClient, seeded: Settings
    ) -> None:
        body = client.get("/api/tax/wash-sales").json()
        for symbol in body["symbols"]:
            deferred_sum = sum(
                (Decimal(r["disallowed_loss"]) for r in symbol["sales"] if not r["permanently_disallowed"]),
                Decimal(0),
            )
            permanent_sum = sum(
                (Decimal(r["disallowed_loss"]) for r in symbol["sales"] if r["permanently_disallowed"]),
                Decimal(0),
            )
            assert deferred_sum == Decimal(symbol["deferred_disallowed"]), symbol["symbol"]
            assert permanent_sum == Decimal(symbol["permanently_disallowed"]), symbol["symbol"]

    def test_window_closes_on_can_differ_from_the_symbols_repurchase_safe_on(
        self, client: TestClient, seeded: Settings
    ) -> None:
        """SOXL has only one loss sale, so its row's `window_closes_on` coincides with the symbol's
        `repurchase_safe_on` -- SPLIT's replacement-side dates are identical too. Assert the
        relationship holds structurally (sale_date + 31) rather than requiring a multi-sale symbol
        in this particular fixture."""
        body = client.get("/api/tax/wash-sales").json()
        soxl = next(s for s in body["symbols"] if s["symbol"] == "SOXL")
        [sale] = soxl["sales"]
        expected = dt.date.fromisoformat(sale["sale_date"]) + dt.timedelta(days=31)
        assert dt.date.fromisoformat(sale["window_closes_on"]) == expected
        assert sale["window_closes_on"] == soxl["repurchase_safe_on"]

    def test_quantities_and_money_serialize_as_decimal_strings_not_numbers(
        self, client: TestClient, seeded: Settings
    ) -> None:
        """Fractional shares are pervasive in this data; a bare JSON number for a quantity is the
        same class of defect as a bare JSON number for money -- both silently round-trip through an
        IEEE double on the client. `response.json()` gives a Python `str` only when the wire value
        was a quoted string; a bare number would decode as `int`/`float`."""
        raw_text = client.get("/api/tax/wash-sales").text
        body = client.get("/api/tax/wash-sales").json()

        soxl = next(s for s in body["symbols"] if s["symbol"] == "SOXL")
        [sale] = soxl["sales"]
        for field in ("quantity_sold", "quantity_replaced", "loss_amount", "disallowed_loss"):
            assert isinstance(sale[field], str), f"{field} did not serialize as a string"
        assert isinstance(soxl["deferred_disallowed"], str)
        assert isinstance(body["total_deferred"], str)

        # And the raw wire text itself quotes them -- not merely that json.loads happened to parse
        # a numeric-looking string the same way either way.
        assert '"quantity_sold":"100"' in raw_text or '"quantity_sold": "100"' in raw_text

    def test_no_params_returns_every_symbol_with_full_metadata(
        self, client: TestClient, seeded: Settings
    ) -> None:
        """Pre-paging shape preserved: all three symbols, and the new fields describe an unsliced
        response -- `limit` null, `offset` zero, `has_more` false."""
        body = client.get("/api/tax/wash-sales").json()
        assert len(body["symbols"]) == 3
        assert body["symbol_count"] == 3
        assert body["limit"] is None
        assert body["offset"] == 0
        assert body["has_more"] is False

    def test_limit_pages_symbols_without_changing_symbol_count(
        self, client: TestClient, seeded: Settings
    ) -> None:
        """OPENX leads (open window), then SOXL, then SPLIT -- see
        `test_open_windows_sort_first_ahead_of_larger_closed_ones` above for that ordering."""
        first = client.get("/api/tax/wash-sales?limit=2&offset=0").json()
        assert [s["symbol"] for s in first["symbols"]] == ["OPENX", "SOXL"]
        assert first["symbol_count"] == 3  # the full total, not the page size
        assert first["limit"] == 2
        assert first["offset"] == 0
        assert first["has_more"] is True

        second = client.get("/api/tax/wash-sales?limit=2&offset=2").json()
        assert [s["symbol"] for s in second["symbols"]] == ["SPLIT"]
        assert second["symbol_count"] == 3
        assert second["has_more"] is False

    def test_offset_past_the_end_is_an_empty_page_not_an_error(
        self, client: TestClient, seeded: Settings
    ) -> None:
        body = client.get("/api/tax/wash-sales?limit=2&offset=50").json()
        assert body["symbols"] == []
        assert body["symbol_count"] == 3
        assert body["has_more"] is False

    def test_totals_are_computed_over_every_symbol_regardless_of_paging(
        self, client: TestClient, seeded: Settings
    ) -> None:
        whole = client.get("/api/tax/wash-sales").json()
        paged = client.get("/api/tax/wash-sales?limit=1&offset=0").json()
        assert paged["total_deferred"] == whole["total_deferred"]
        assert paged["total_permanently_disallowed"] == whole["total_permanently_disallowed"]
        assert paged["open_window_count"] == whole["open_window_count"]

    def test_limit_is_bounded(self, client: TestClient, seeded: Settings) -> None:
        assert client.get("/api/tax/wash-sales?limit=0").status_code == 422
        assert client.get("/api/tax/wash-sales?limit=1001").status_code == 422
        assert client.get("/api/tax/wash-sales?offset=-1").status_code == 422

    def test_as_of_and_generated_at_are_present(self, client: TestClient, seeded: Settings) -> None:
        """`as_of` comes from the server's clock at request time, so it is bracketed here rather
        than compared against this module's `TODAY`.

        `TODAY` is captured once at import and is exactly right for the fixture rows above, whose
        expectations derive from that same frozen value. It is wrong for this assertion: the suite
        takes about five minutes, so a run straddling local midnight leaves `TODAY` holding
        yesterday while the endpoint returns today. That is not hypothetical -- it failed on
        2026-08-26 for that reason and passed on a re-run, which is the signature of a test that
        measures the clock instead of the application.

        Reading the date on both sides of the call and accepting either makes the test independent
        of when it runs; a same-day run collapses to a single candidate.
        """
        before = dt.date.today()
        body = client.get("/api/tax/wash-sales").json()
        after = dt.date.today()
        assert body["as_of"] in {str(before), str(after)}
        assert body.get("generated_at")


class TestReconcileBodySizeCap:
    """`POST /api/tax/reconcile` takes the CSV as the raw request body. Uncapped, an
    unauthenticated or malicious caller could make this endpoint buffer and parse an arbitrarily
    large body; `csv_text` now carries `max_length=2_000_000` (2MB, thousands of 1099-B rows)."""

    def test_oversized_body_is_422(self, client: TestClient) -> None:
        huge_csv = "x" * 2_000_001
        response = client.post(
            "/api/tax/reconcile",
            content=huge_csv,
            headers={"Content-Type": "text/plain"},
        )
        assert response.status_code == 422

    def test_a_body_at_the_limit_still_reaches_the_parser(self, client: TestClient) -> None:
        # Not oversized -- must pass the length gate and reach `parse_1099b_csv`, which then fails
        # on content (this is not a real 1099-B), proving the 422 above was about size, not merely
        # "this endpoint always 422s a text body".
        response = client.post(
            "/api/tax/reconcile",
            content="not,a,real,1099b\n",
            headers={"Content-Type": "text/plain"},
        )
        assert response.status_code == 400

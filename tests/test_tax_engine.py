"""Integration tests for the composed tax pipeline and the tax API.

The unit tests for each stage build their inputs by hand, which is the right way to test a tax rule
but leaves one class of defect invisible: an error in how the stages *hand off* to each other. Both
regressions pinned here are exactly that shape -- each stage was individually correct and the
composition was wrong.
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
from app.tax import engine
from app.tax.models import HoldingTerm
from tests.conftest import make_txn, sample_account

ACCOUNT = sample_account()
ACCOUNTS = {ACCOUNT.account_id: ACCOUNT}


def _record_import(conn: sqlite3.Connection, import_id: str = "imp1") -> None:
    """Satisfy the provenance foreign key. Every transaction must trace back to a file."""
    conn.execute(
        "INSERT OR IGNORE INTO raw_import (import_id, source_path, filename, file_sha256, "
        "content_hash, broker, account_id, adapter, adapter_version, row_count, "
        "usable_row_count, imported_at) VALUES (?, 'p', 'f.csv', 'sha', 'content', "
        "'robinhood', 'rh-taxable', 'robinhood', '1', 4, 4, '2026-01-01T00:00:00Z')",
        (import_id,),
    )


def _wash_then_resell() -> list:
    """Buy, sell at a loss, repurchase inside the window, then sell the replacement.

    The replacement lot's basis is raised by the disallowed $1,000. The final sale must be measured
    against that raised basis, which is the whole point of a deferral.
    """
    return [
        make_txn(
            txn_id="buy-1",
            action=TxnAction.BUY,
            quantity="100",
            price="50",
            amount="-5000",
            trade_date=dt.date(2024, 11, 1),
        ),
        make_txn(
            txn_id="sell-1",
            action=TxnAction.SELL,
            quantity="100",
            price="40",
            amount="4000",
            trade_date=dt.date(2025, 2, 3),
        ),
        make_txn(
            txn_id="buy-2",
            action=TxnAction.BUY,
            quantity="100",
            price="41",
            amount="-4100",
            trade_date=dt.date(2025, 2, 10),
        ),
        make_txn(
            txn_id="sell-2",
            action=TxnAction.SELL,
            quantity="100",
            price="45",
            amount="4500",
            trade_date=dt.date(2025, 6, 2),
        ),
    ]


class TestDisallowedLossReachesTheReplacementBasis:
    """Regression: a wash-sale adjustment must survive the hand-off from lots to gains.

    ``build_lots`` snapshots ``Disposal.cost_basis`` during replay; ``apply_wash_sales`` then raises
    the *lot's* basis. Without the re-sync in :func:`app.tax.engine._sync_disposal_basis`, the final
    sale is priced off the stale $4,100 snapshot and books a **$400 gain** instead of a **$600
    loss** -- a $1,000 error, in the taxpayer's disfavour, on a return.
    """

    def test_replacement_lot_carries_the_disallowed_loss(self) -> None:
        report = engine.build_tax_report(
            _wash_then_resell(), accounts=ACCOUNTS, tax_year=2025
        )
        final = next(row for row in report.gains.rows if row.disposed_date == dt.date(2025, 6, 2))

        assert final.cost_basis == Decimal("5100")
        assert final.gain_loss == Decimal("-600")

    def test_the_first_sale_is_fully_disallowed(self) -> None:
        report = engine.build_tax_report(
            _wash_then_resell(), accounts=ACCOUNTS, tax_year=2025
        )
        first = next(row for row in report.gains.rows if row.disposed_date == dt.date(2025, 2, 3))

        assert first.gain_loss == Decimal("-1000")
        assert first.disallowed_loss == Decimal("1000")
        assert first.reportable_gain_loss == Decimal("0")
        assert first.is_wash_sale

    def test_the_year_nets_to_the_deferred_loss_only(self) -> None:
        """$0 allowed on the washed sale plus a $600 loss on the resale."""
        report = engine.build_tax_report(
            _wash_then_resell(), accounts=ACCOUNTS, tax_year=2025
        )

        assert report.gains.short_term_gain == Decimal("-600")
        assert report.gains.long_term_gain == Decimal("0")
        assert report.gains.disallowed_loss_total == Decimal("1000")
        assert report.gains.permanently_disallowed_total == Decimal("0")

    def test_form8949_agrees_with_the_gains_report(self) -> None:
        report = engine.build_tax_report(
            _wash_then_resell(), accounts=ACCOUNTS, tax_year=2025
        )

        assert report.form8949.short_term_total_gain == Decimal("-600")
        washed = [row for row in report.form8949.rows if row.adjustment_code == "W"]
        assert len(washed) == 1
        assert washed[0].adjustment_amount == Decimal("1000")


class TestWashSalesRunBeforeGains:
    """Tolling must reach term classification, or a long-term gain is taxed as short-term."""

    def test_tolled_holding_period_makes_the_resale_long_term(self) -> None:
        """The replacement lot is held 4 months, but inherits a holding period opened 14 months ago.

        Classifying off the replacement's own acquisition date would call this short-term.
        """
        transactions = [
            make_txn(
                txn_id="buy-old",
                action=TxnAction.BUY,
                quantity="100",
                price="50",
                amount="-5000",
                trade_date=dt.date(2024, 1, 2),
            ),
            make_txn(
                txn_id="sell-loss",
                action=TxnAction.SELL,
                quantity="100",
                price="40",
                amount="4000",
                trade_date=dt.date(2025, 2, 3),
            ),
            make_txn(
                txn_id="buy-replacement",
                action=TxnAction.BUY,
                quantity="100",
                price="41",
                amount="-4100",
                trade_date=dt.date(2025, 2, 10),
            ),
            make_txn(
                txn_id="sell-final",
                action=TxnAction.SELL,
                quantity="100",
                price="60",
                amount="6000",
                trade_date=dt.date(2025, 6, 2),
            ),
        ]

        report = engine.build_tax_report(transactions, accounts=ACCOUNTS, tax_year=2025)
        final = next(row for row in report.gains.rows if row.disposed_date == dt.date(2025, 6, 2))

        assert final.term is HoldingTerm.LONG
        assert final.holding_start < final.acquired_date


class TestTaxAdvantagedAccountsAreScannedButNotReported:
    """Both halves of the IRA rule must hold at once through the composed pipeline."""

    def test_ira_replacement_is_permanent_and_the_ira_is_excluded(self) -> None:
        roth = Account(
            account_id="rh-roth",
            broker=Broker.ROBINHOOD,
            label="RH Roth",
            tax_treatment=TaxTreatment.ROTH_IRA,
            account_type=AccountType.RETIREMENT,
        )
        accounts = {ACCOUNT.account_id: ACCOUNT, roth.account_id: roth}

        transactions = [
            make_txn(
                txn_id="tax-buy",
                action=TxnAction.BUY,
                quantity="100",
                price="50",
                amount="-5000",
                trade_date=dt.date(2024, 11, 1),
            ),
            make_txn(
                txn_id="tax-sell",
                action=TxnAction.SELL,
                quantity="100",
                price="40",
                amount="4000",
                trade_date=dt.date(2025, 2, 3),
            ),
            make_txn(
                txn_id="roth-buy",
                action=TxnAction.BUY,
                quantity="100",
                price="41",
                amount="-4100",
                trade_date=dt.date(2025, 2, 10),
                account_id="rh-roth",
            ),
        ]

        report = engine.build_tax_report(transactions, accounts=accounts, tax_year=2025)

        assert report.permanent_disallowance_count == 1
        assert report.gains.permanently_disallowed_total == Decimal("1000")
        # Rev. Rul. 2008-5: destroyed, not deferred. It must not appear in the ordinary total.
        assert report.gains.disallowed_loss_total == Decimal("0")
        assert "rh-roth" not in [row.account_id for row in report.gains.rows]


class TestSplitReplacementAcrossIraAndTaxable:
    """Regression: one sale replaced in *both* an IRA and a taxable account.

    Found on real data — several Webull disposals do exactly this. The two halves have
    incompatible outcomes (destroyed versus deferred), so a single boolean on the disposal reported
    the entire disallowance as permanent and understated the deferred total by the same amount.
    """

    def test_each_half_lands_in_its_own_total(self) -> None:
        roth = Account(
            account_id="rh-roth",
            broker=Broker.ROBINHOOD,
            label="RH Roth",
            tax_treatment=TaxTreatment.ROTH_IRA,
            account_type=AccountType.RETIREMENT,
        )
        accounts = {ACCOUNT.account_id: ACCOUNT, roth.account_id: roth}

        transactions = [
            make_txn(
                txn_id="split-buy",
                action=TxnAction.BUY,
                quantity="100",
                price="50",
                amount="-5000",
                trade_date=dt.date(2024, 11, 1),
            ),
            make_txn(
                txn_id="split-sell",
                action=TxnAction.SELL,
                quantity="100",
                price="40",
                amount="4000",
                trade_date=dt.date(2025, 2, 3),
            ),
            make_txn(
                txn_id="split-rep-taxable",
                action=TxnAction.BUY,
                quantity="50",
                price="41",
                amount="-2050",
                trade_date=dt.date(2025, 2, 10),
            ),
            make_txn(
                txn_id="split-rep-roth",
                action=TxnAction.BUY,
                quantity="50",
                price="41",
                amount="-2050",
                trade_date=dt.date(2025, 2, 10),
                account_id="rh-roth",
            ),
        ]

        report = engine.build_tax_report(transactions, accounts=accounts, tax_year=2025)

        # The full $1,000 loss is disallowed, but only the IRA-replaced half is destroyed.
        assert report.gains.permanently_disallowed_total == Decimal("500")
        assert report.gains.disallowed_loss_total == Decimal("500")

        row = report.gains.rows[0]
        assert row.disallowed_loss == Decimal("1000")
        assert row.permanently_disallowed_loss == Decimal("500")
        assert row.reportable_gain_loss == Decimal("0")

    def test_totals_reconcile_to_the_events(self) -> None:
        """The two reported totals must sum to what the wash-sale events actually disallowed."""
        roth = Account(
            account_id="rh-roth",
            broker=Broker.ROBINHOOD,
            label="RH Roth",
            tax_treatment=TaxTreatment.ROTH_IRA,
            account_type=AccountType.RETIREMENT,
        )
        accounts = {ACCOUNT.account_id: ACCOUNT, roth.account_id: roth}
        transactions = [
            make_txn(
                txn_id="r-buy",
                action=TxnAction.BUY,
                quantity="100",
                price="50",
                amount="-5000",
                trade_date=dt.date(2024, 11, 1),
            ),
            make_txn(
                txn_id="r-sell",
                action=TxnAction.SELL,
                quantity="100",
                price="40",
                amount="4000",
                trade_date=dt.date(2025, 2, 3),
            ),
            make_txn(
                txn_id="r-rep-taxable",
                action=TxnAction.BUY,
                quantity="30",
                price="41",
                amount="-1230",
                trade_date=dt.date(2025, 2, 10),
            ),
            make_txn(
                txn_id="r-rep-roth",
                action=TxnAction.BUY,
                quantity="70",
                price="41",
                amount="-2870",
                trade_date=dt.date(2025, 2, 10),
                account_id="rh-roth",
            ),
        ]

        report = engine.build_tax_report(transactions, accounts=accounts, tax_year=2025)
        event_total = sum(
            (event.disallowed_loss for event in report.wash_sales), Decimal(0)
        )
        reported_total = (
            report.gains.disallowed_loss_total + report.gains.permanently_disallowed_total
        )

        assert reported_total == event_total
        assert report.gains.permanently_disallowed_total == Decimal("700")
        assert report.gains.disallowed_loss_total == Decimal("300")


class TestReportScoping:
    def test_only_the_requested_year_is_reported(self) -> None:
        report = engine.build_tax_report(
            _wash_then_resell(), accounts=ACCOUNTS, tax_year=2024
        )
        assert report.gains.rows == ()

    def test_default_tax_year_is_the_last_complete_one(self) -> None:
        assert engine.default_tax_year(dt.date(2026, 8, 10)) == 2025


class TestWarningAggregation:
    """Finding 3.1: the review's complaint was that 330 raw warning strings for one tax year is
    technically present but practically unreadable. `TaxReport.warning_groups` is the fix -- the
    same warnings collapsed to `(kind, account)` counts -- and this proves nothing is lost in the
    collapse: the full list still travels on `TaxReport.warnings`.
    """

    _WEBULL_ACCOUNT = Account(
        account_id="wb-margin",
        broker=Broker.WEBULL,
        label="Webull Margin",
        tax_treatment=TaxTreatment.TAXABLE,
        account_type=AccountType.CASH,
    )

    def test_two_oversold_sales_in_one_account_collapse_to_one_group(self) -> None:
        transactions = [
            make_txn(
                txn_id="wb-sell-1",
                action=TxnAction.SELL,
                symbol="SOXL",
                quantity="10",
                price="12",
                amount="120.00",
                trade_date=dt.date(2025, 2, 1),
                account_id="wb-margin",
                broker=Broker.WEBULL,
            ),
            make_txn(
                txn_id="wb-sell-2",
                action=TxnAction.SELL,
                symbol="DRAM",
                quantity="5",
                price="20",
                amount="100.00",
                trade_date=dt.date(2025, 3, 1),
                account_id="wb-margin",
                broker=Broker.WEBULL,
            ),
        ]
        report = engine.build_tax_report(
            transactions, accounts={"wb-margin": self._WEBULL_ACCOUNT}, tax_year=2025
        )

        oversold_groups = [g for g in report.warning_groups if g.kind == "oversold"]
        assert len(oversold_groups) == 1
        assert oversold_groups[0].account_id == "wb-margin"
        assert oversold_groups[0].broker == "webull"
        assert oversold_groups[0].count == 2
        assert oversold_groups[0].sample_detail

        # Nothing lost: the ungrouped list still carries both occurrences.
        raw_oversold = [w for w in report.warnings if w.kind == "oversold"]
        assert len(raw_oversold) == 2

    def test_groups_are_sorted_biggest_first(self) -> None:
        transactions = [
            make_txn(
                txn_id=f"wb-sell-{i}",
                action=TxnAction.SELL,
                symbol="SOXL",
                quantity="1",
                price="10",
                amount="10.00",
                trade_date=dt.date(2025, 1, i + 1),
                account_id="wb-margin",
                broker=Broker.WEBULL,
            )
            for i in range(3)
        ] + [
            make_txn(
                txn_id="rh-sell-1",
                action=TxnAction.SELL,
                symbol="MUU",
                quantity="1",
                price="10",
                amount="10.00",
                trade_date=dt.date(2025, 1, 10),
                account_id="rh-taxable",
                broker=Broker.ROBINHOOD,
            ),
        ]
        report = engine.build_tax_report(
            transactions,
            accounts={"wb-margin": self._WEBULL_ACCOUNT, "rh-taxable": ACCOUNT},
            tax_year=2025,
        )

        oversold_groups = [g for g in report.warning_groups if g.kind == "oversold"]
        # Webull (3 oversold sales, one group) must sort ahead of Robinhood (1).
        assert oversold_groups[0].account_id == "wb-margin"
        assert oversold_groups[0].count == 3
        assert oversold_groups[1].account_id == "rh-taxable"
        assert oversold_groups[1].count == 1

    def test_reconstructed_fee_from_a_webull_sale_reaches_the_report(self) -> None:
        buy = make_txn(
            txn_id="wb-buy",
            symbol="SOXL",
            quantity="10",
            price="10",
            amount="-100.00",
            trade_date=dt.date(2025, 1, 1),
            account_id="wb-margin",
            broker=Broker.WEBULL,
        )
        sell = make_txn(
            txn_id="wb-sell",
            action=TxnAction.SELL,
            symbol="SOXL",
            quantity="10",
            price="12",
            amount="120.00",
            trade_date=dt.date(2025, 6, 1),
            account_id="wb-margin",
            broker=Broker.WEBULL,
        )
        report = engine.build_tax_report(
            [buy, sell], accounts={"wb-margin": self._WEBULL_ACCOUNT}, tax_year=2025
        )

        # The Webull export has no fee column, but the fee is no longer an unfilled gap: it is
        # reconstructed from the SEC/TAF schedule, so the row is not flagged "unknown".
        assert report.gains.rows[0].fees_unknown is False
        assert report.gains.rows_with_unknown_fees == 0
        # For this 2025-06-01 sale the SEC fee is $0.00 and the FINRA TAF on 10 shares hits its $0.01
        # floor, so a $0.01 fee is netted from the gain: 120.00 - 0.01 - 100.00 = 19.99.
        assert report.gains.rows[0].fees == Decimal("0.01")
        assert report.gains.rows[0].gain_loss == Decimal("19.99")

        fee_groups = [g for g in report.warning_groups if g.kind == "fees_estimated"]
        assert len(fee_groups) == 1
        assert fee_groups[0].count == 1
        assert fee_groups[0].broker == "webull"
        assert fee_groups[0].account_id == "wb-margin"
        # ...and no lingering "unknown" group.
        assert not [g for g in report.warning_groups if g.kind == "fees_unknown"]


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def seeded(settings: Settings, client: TestClient) -> Settings:
    """A ledger holding the wash-sale scenario, written through the real store."""
    with ledger.connect(settings.ledger_path) as conn:
        ledger.migrate(conn)
        ledger.upsert_account(conn, ACCOUNT)
        _record_import(conn)
        ledger.insert_transactions(conn, _wash_then_resell())
    return settings


class TestTaxApi:
    def test_report_round_trips_through_sqlite(
        self, client: TestClient, seeded: Settings
    ) -> None:
        """The same figures must survive the store round trip, not just the in-memory path."""
        response = client.get("/api/tax/report?year=2025")
        assert response.status_code == 200

        body = response.json()
        assert body["tax_year"] == 2025
        # Decimals serialise as strings so precision is not lost crossing to the browser.
        assert body["gains"]["short_term_gain"] == "-600.00"
        assert len(body["wash_sales"]) == 1

    def test_empty_year_is_not_an_error(self, client: TestClient, seeded: Settings) -> None:
        response = client.get("/api/tax/report?year=2019")
        assert response.status_code == 200
        assert response.json()["gains"]["rows"] == []

    def test_missing_ledger_is_a_404(self, client: TestClient, settings: Settings) -> None:
        """Distinct from an empty year: the Tax page tells the user to import something."""
        settings.ledger_path.unlink()
        assert client.get("/api/tax/report?year=2025").status_code == 404

    def test_year_is_bounded(self, client: TestClient, seeded: Settings) -> None:
        assert client.get("/api/tax/report?year=1200").status_code == 422

    def test_form8949_csv_downloads(self, client: TestClient, seeded: Settings) -> None:
        response = client.get("/api/tax/form8949.csv?year=2025")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "form8949-2025.csv" in response.headers["content-disposition"]
        assert len(response.text.strip().splitlines()) == 3  # header + two disposals

    def test_reconcile_accepts_a_1099b(self, client: TestClient, seeded: Settings) -> None:
        csv_text = (
            "symbol,account_id,term,proceeds,cost_basis,wash_disallowed\n"
            "SOXL,rh-taxable,short,8500.00,10100.00,1000.00\n"
        )
        response = client.post(
            "/api/tax/reconcile?year=2025",
            content=csv_text,
            headers={"Content-Type": "text/plain"},
        )
        assert response.status_code == 200
        # `is_clean` is a property, so it does not serialise; the counts it derives from do.
        assert response.json()["differing_count"] == 0
        assert response.json()["matched_count"] == 1

    def test_reconcile_deltas_cross_the_wire(self, client: TestClient, seeded: Settings) -> None:
        """The one column a reconciliation exists for, computed server-side.

        Money crosses this API as a decimal string specifically so that no client does arithmetic
        on it. That rule left the deltas -- plain `@property` until they were promoted to
        `computed_field` -- unreachable by any UI that obeyed it: the only way to show "off by how
        much" would have been to subtract two decimal strings in IEEE doubles, which is what the
        string representation exists to prevent. So they are serialised, and this pins that.
        """
        # Same as the matching case above but with proceeds $100 higher, so exactly one figure
        # moves. `wash_disallowed` is carried across unchanged: without it the form's gain would
        # also shift by the $1,000 add-back, and the delta would be measuring two differences.
        csv_text = (
            "symbol,account_id,term,proceeds,cost_basis,wash_disallowed\n"
            "SOXL,rh-taxable,short,8600.00,10100.00,1000.00\n"
        )
        response = client.post(
            "/api/tax/reconcile?year=2025",
            content=csv_text,
            headers={"Content-Type": "text/plain"},
        )
        assert response.status_code == 200
        line = response.json()["lines"][0]

        assert line["status"] == "amount_differs"
        assert line["proceeds_delta"] == "-100.00"
        assert line["basis_delta"] == "0.00"
        assert line["gain_delta"] == "-100.00"
        # Exact strings, not floats: 8500.00 - 8600.00 must not arrive as -99.99999999999909.
        assert all(isinstance(line[f], str) for f in ("proceeds_delta", "basis_delta", "gain_delta"))

    def test_malformed_1099b_is_a_400_naming_the_problem(
        self, client: TestClient, seeded: Settings
    ) -> None:
        response = client.post(
            "/api/tax/reconcile?year=2025",
            content="symbol,account_id,term\nSOXL,rh-taxable,short\n",
            headers={"Content-Type": "text/plain"},
        )
        assert response.status_code == 400
        assert "proceeds" in response.json()["detail"].lower()

    def test_warnings_and_warning_groups_serialize_as_structured_objects(
        self, client: TestClient, settings: Settings
    ) -> None:
        """The Tax page's aggregation (finding 3.1) needs `kind`/`account_id` on the wire, not a
        flattened string -- this pins the JSON shape the frontend groups on."""
        webull_account = Account(
            account_id="wb-margin",
            broker=Broker.WEBULL,
            label="Webull Margin",
            tax_treatment=TaxTreatment.TAXABLE,
            account_type=AccountType.CASH,
        )
        with ledger.connect(settings.ledger_path) as conn:
            ledger.migrate(conn)
            ledger.upsert_account(conn, ACCOUNT)  # rh-taxable, referenced by _record_import
            ledger.upsert_account(conn, webull_account)
            _record_import(conn)
            ledger.insert_transactions(
                conn,
                [
                    make_txn(
                        txn_id="wb-sell",
                        action=TxnAction.SELL,
                        symbol="SOXL",
                        quantity="10",
                        price="12",
                        amount="120.00",
                        trade_date=dt.date(2025, 6, 1),
                        account_id="wb-margin",
                        broker=Broker.WEBULL,
                    )
                ],
            )

        response = client.get("/api/tax/report?year=2025")
        assert response.status_code == 200
        body = response.json()

        kinds = {w["kind"] for w in body["warnings"]}
        assert "oversold" in kinds  # no matching buy in this dataset
        assert "fees_estimated" in kinds  # every Webull sale's fee is reconstructed from schedule
        assert "fees_unknown" not in kinds

        oversold_group = next(g for g in body["warning_groups"] if g["kind"] == "oversold")
        assert oversold_group["account_id"] == "wb-margin"
        assert oversold_group["broker"] == "webull"
        assert oversold_group["count"] == 1
        assert oversold_group["sample_detail"]


class TestReportPagination:
    """`GET /api/tax/report`'s `limit`/`offset` -- see `app.api.tax._paginate_report`.

    `seeded` (above) carries exactly two 2025 disposals (`sell-1`, the wash-sale loss; `sell-2`, the
    later gain) and one triggered wash-sale event (`sell-1`'s), which is enough rows to prove a real
    page boundary -- `has_more` true then false -- without a bespoke larger fixture.
    """

    def test_no_params_returns_everything_with_full_metadata(
        self, client: TestClient, seeded: Settings
    ) -> None:
        """The exact pre-paging shape: every row present, and the new metadata fields describe an
        unsliced response -- `limit` null, `offset` zero, `has_more` false on both lists."""
        body = client.get("/api/tax/report?year=2025").json()
        assert len(body["gains"]["rows"]) == 2
        assert len(body["wash_sales"]) == 1
        assert body["disposals_total"] == 2
        assert body["wash_events_total"] == 1
        assert body["limit"] is None
        assert body["offset"] == 0
        assert body["disposals_has_more"] is False
        assert body["wash_events_has_more"] is False

    def test_limit_pages_disposals_and_wash_events_together(
        self, client: TestClient, seeded: Settings
    ) -> None:
        first = client.get("/api/tax/report?year=2025&limit=1&offset=0").json()
        assert len(first["gains"]["rows"]) == 1
        assert len(first["wash_sales"]) == 1  # only one exists, so it fits on page one too
        assert first["disposals_total"] == 2
        assert first["wash_events_total"] == 1
        assert first["limit"] == 1
        assert first["offset"] == 0
        assert first["disposals_has_more"] is True
        assert first["wash_events_has_more"] is False

        second = client.get("/api/tax/report?year=2025&limit=1&offset=1").json()
        assert len(second["gains"]["rows"]) == 1
        assert len(second["wash_sales"]) == 0  # the one event already appeared on page one
        assert second["disposals_total"] == 2
        assert second["disposals_has_more"] is False
        # The two pages of disposals are disjoint and together cover the full two-row set --
        # `disposal_id` is a derived hash, not the source `txn_id`, so this checks the *shape* of the
        # split rather than pinning specific hash values.
        first_ids = {row["disposal_id"] for row in first["gains"]["rows"]}
        second_ids = {row["disposal_id"] for row in second["gains"]["rows"]}
        assert first_ids.isdisjoint(second_ids)
        assert len(first_ids | second_ids) == 2

    def test_offset_past_the_end_is_an_empty_page_not_an_error(
        self, client: TestClient, seeded: Settings
    ) -> None:
        body = client.get("/api/tax/report?year=2025&limit=10&offset=50").json()
        assert body["gains"]["rows"] == []
        assert body["wash_sales"] == []
        assert body["disposals_total"] == 2
        assert body["disposals_has_more"] is False
        assert body["wash_events_has_more"] is False

    def test_aggregates_are_computed_over_the_whole_year_regardless_of_paging(
        self, client: TestClient, seeded: Settings
    ) -> None:
        """The whole point of slicing only `gains.rows`/`wash_sales`: every summary figure must match
        the unpaginated response exactly, not be recomputed from whatever page came back."""
        whole = client.get("/api/tax/report?year=2025").json()
        paged = client.get("/api/tax/report?year=2025&limit=1&offset=0").json()
        assert paged["gains"]["short_term_gain"] == whole["gains"]["short_term_gain"]
        assert paged["gains"]["disallowed_loss_total"] == whole["gains"]["disallowed_loss_total"]
        assert paged["warnings"] == whole["warnings"]
        assert paged["form8949"] == whole["form8949"]

    def test_limit_is_bounded(self, client: TestClient, seeded: Settings) -> None:
        assert client.get("/api/tax/report?year=2025&limit=0").status_code == 422
        assert client.get("/api/tax/report?year=2025&limit=1001").status_code == 422
        assert client.get("/api/tax/report?year=2025&offset=-1").status_code == 422


class TestLedgerRoundTrip:
    def test_transaction_survives_the_store_unchanged(self, conn: sqlite3.Connection) -> None:
        """Decimals are stored as text precisely so this holds exactly."""
        _record_import(conn)
        original = make_txn(txn_id="rt", quantity="1.48320000", price="118.4455", amount="-175.68")
        ledger.insert_transactions(conn, [original])

        row = ledger.fetch_transactions(conn)[0]
        restored = ledger.transaction_from_row(row)

        assert restored.quantity == original.quantity
        assert restored.price == original.price
        assert restored.amount == original.amount
        assert restored.trade_date == original.trade_date
        assert restored.action is original.action

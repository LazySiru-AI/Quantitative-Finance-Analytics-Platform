"""The Portfolio report must replay the ledger with the same manifest declarations as the Tax report.

`app.api.tax._build` hands `manifest.transfer_bases` to the replay; `app.api.portfolio._build_report`
used to pass only `opening_positions`. A ``[[transfer_basis]]`` declaration is exactly the kind of
fact that changes what the replay produces (see :class:`app.core.lots.TransferBasis` and
docs/basis-reconstruction.md): without it an inbound ACAT leg opens a zero-basis lot, its later
sale books a phantom gain instead of a loss, and the wash-sale pass has no loss to disallow. On a
ledger that left the two pages a wash-sale event apart when reading the
same database. This fixture reproduces that shape in miniature and asserts the two paths agree on
the wash-sale total, the realized figures and the absence of the unmatched-transfer warning.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from decimal import Decimal

import pytest

from app.api import portfolio, tax
from app.config import Settings
from app.core.lots import WarningKind
from app.core.models import (
    Account,
    AccountStatus,
    AccountType,
    Broker,
    TaxTreatment,
    Transaction,
    TxnAction,
)
from app.db import sqlite as ledger
from app.market import store
from app.market.models import Bar, Interval
from app.tax.models import TaxReport
from tests.conftest import make_txn

RH = Account(
    account_id="rh-taxable",
    broker=Broker.ROBINHOOD,
    label="Robinhood Individual",
    tax_treatment=TaxTreatment.TAXABLE,
    account_type=AccountType.CASH,
    status=AccountStatus.OPEN,
)

TRANSFER_DATE = dt.date(2026, 6, 18)
DECLARED_BASIS = Decimal("10518.50")
# 150 sh sold at 60.00 = 9000.00 proceeds against the declared 10518.50 basis: a 1518.50 loss, fully
# replaced by the 150-share repurchase eight days later, so the whole loss is disallowed and moves
# onto the replacement lot -- which is still open when the portfolio report is built.
EXPECTED_DISALLOWED = Decimal("1518.50")

MANIFEST = f"""
[[account]]
file = "RH.csv"
account_id = "rh-taxable"
label = "Robinhood Individual"
tax_treatment = "taxable"
account_type = "cash"

[[transfer_basis]]
account_id = "rh-taxable"
symbol = "QZMR"
quantity = "150"
as_of = {TRANSFER_DATE.isoformat()}
acquired_date = 2026-06-12
cost_basis = "{DECLARED_BASIS}"
note = "ACAT in from a Webull account whose export was never imported"
"""


def _record_import(conn: sqlite3.Connection, import_id: str, account_id: str, broker: str) -> None:
    """Satisfy the provenance foreign key for one account's rows."""
    conn.execute(
        "INSERT OR IGNORE INTO raw_import (import_id, source_path, filename, file_sha256, "
        "content_hash, broker, account_id, adapter, adapter_version, row_count, "
        "usable_row_count, imported_at) VALUES (?, 'p', 'f.csv', ?, ?, ?, ?, ?, '1', 1, 1, "
        "'2026-01-01T00:00:00Z')",
        (import_id, f"sha-{import_id}", f"content-{import_id}", broker, account_id, broker),
    )


def _ledger_transactions() -> list[Transaction]:
    """One inbound ACAT with no outbound leg in the dataset, sold at a loss, then repurchased."""
    transfer_in = make_txn(
        txn_id="acat-in-qzmr",
        action=TxnAction.TRANSFER_IN,
        symbol="QZMR",
        quantity="150",
        price=None,
        amount=None,
        trade_date=TRANSFER_DATE,
        import_id="imp-rh",
        source_row=0,
    ).model_copy(update={"transfer_group": "20261670037489"})
    return [
        transfer_in,
        make_txn(
            txn_id="sell-dram",
            action=TxnAction.SELL,
            symbol="QZMR",
            quantity="150",
            price="60.00",
            amount="9000.00",
            trade_date=dt.date(2026, 6, 23),
            import_id="imp-rh",
            source_row=1,
        ),
        make_txn(
            txn_id="rebuy-dram",
            action=TxnAction.BUY,
            symbol="QZMR",
            quantity="150",
            price="61.00",
            amount="-9150.00",
            trade_date=dt.date(2026, 7, 1),
            import_id="imp-rh",
            source_row=2,
        ),
    ]


@pytest.fixture
def seeded(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "accounts.toml").write_text(MANIFEST, encoding="utf-8")
    with ledger.connect(settings.ledger_path) as conn:
        ledger.migrate(conn)
        ledger.upsert_account(conn, RH)
        _record_import(conn, "imp-rh", "rh-taxable", "robinhood")
        ledger.insert_transactions(conn, _ledger_transactions())

    def latest_two_bars(
        symbols: object, interval: Interval, **kwargs: object
    ) -> dict[str, tuple[Bar, Bar | None]]:
        value = 62.0
        bar = Bar(
            ts=dt.datetime(2026, 7, 2, tzinfo=dt.UTC),
            open=value,
            high=value,
            low=value,
            close=value,
            adj_close=value,
            volume=1000,
        )
        return {"QZMR": (bar, None)}

    # `app.api.portfolio` does `from app.market import store` and calls `store.latest_two_bars`,
    # so patching the attribute on the shared module object is what its lookup sees.
    monkeypatch.setattr(store, "latest_two_bars", latest_two_bars)
    return settings


def _wash_sale_total(report: TaxReport) -> tuple[int, Decimal]:
    events = report.wash_sales
    return len(events), sum((event.disallowed_loss for event in events), Decimal(0))


class TestTransferBasisParity:
    def test_tax_path_sees_the_declared_basis(self, seeded: Settings) -> None:
        """Baseline for the parity assertions: the Tax path already threads the declaration."""
        report = tax._build(2026)
        assert _wash_sale_total(report) == (1, EXPECTED_DISALLOWED)
        assert not any(w.kind == WarningKind.UNMATCHED_TRANSFER_IN.value for w in report.warnings)

    def test_portfolio_wash_sale_total_matches_tax_path(self, seeded: Settings) -> None:
        tax_report = tax._build(2026)
        portfolio_report = portfolio._build_report()

        _, tax_disallowed = _wash_sale_total(tax_report)
        portfolio_disallowed = sum(
            (position.wash_sale_adjustment for position in portfolio_report.positions), Decimal(0)
        )
        # Without `transfer_basis` the portfolio replay books the sale at zero basis (a 9000.00
        # "gain"), so nothing is a loss, nothing is disallowed and this figure is 0.
        assert portfolio_disallowed == tax_disallowed == EXPECTED_DISALLOWED

    def test_portfolio_no_longer_warns_about_the_declared_transfer(self, seeded: Settings) -> None:
        report = portfolio._build_report()
        assert not any(w.kind == WarningKind.UNMATCHED_TRANSFER_IN.value for w in report.warnings)

    def test_account_realized_figures_match_tax_path(self, seeded: Settings) -> None:
        """`_account_summaries` replays through `report_from_ledger` separately; it must get the
        same declarations, or the summary's realized gain would disagree with the Tax page's rows."""
        tax_report = tax._build(2026)
        portfolio_report = portfolio._build_report()

        rows = [row for row in tax_report.gains.rows if row.account_id == "rh-taxable"]
        assert rows, "fixture sold something"
        tax_proceeds = sum((row.proceeds for row in rows), Decimal(0))
        tax_basis = sum((row.cost_basis for row in rows), Decimal(0))

        (summary,) = [a for a in portfolio_report.accounts if a.account_id == "rh-taxable"]
        assert summary.realized_proceeds == tax_proceeds == Decimal("9000.00")
        assert summary.disposed_cost_basis == tax_basis == DECLARED_BASIS
        assert summary.realized_gain == Decimal("9000.00") - DECLARED_BASIS

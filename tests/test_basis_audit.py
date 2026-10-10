"""The opening-basis audit: it must catch a fabricated basis, catch a phantom gain, and -- the part
that makes it usable on a live ledger -- must NOT flag a legitimate intraday round-trip whose basis
happens to sit near its proceeds.

The three failure modes it guards against were all present on a real ledger: opening lots with a
basis reverse-engineered to proceeds, and a large amount of proceeds booked at zero basis across
taxable accounts. See app.tax.basis_audit's module docstring.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.core.lots import OpeningPosition, build_lots
from app.core.models import Account, AccountType, Broker, TaxTreatment
from app.tax.basis_audit import audit_basis
from tests.conftest import make_txn

TAXABLE = Account(
    account_id="wb-margin",
    broker=Broker.WEBULL,
    label="Webull Individual Cash",
    tax_treatment=TaxTreatment.TAXABLE,
    account_type=AccountType.CASH,
)
ROTH = Account(
    account_id="wb-roth",
    broker=Broker.WEBULL,
    label="Webull Roth IRA",
    tax_treatment=TaxTreatment.ROTH_IRA,
    account_type=AccountType.RETIREMENT,
)
ACCOUNTS = {a.account_id: a for a in (TAXABLE, ROTH)}


def _audit(transactions, opening):  # type: ignore[no-untyped-def]
    ledger = build_lots(transactions, accounts=ACCOUNTS, opening=opening)
    return audit_basis(
        ledger, accounts=ACCOUNTS, opening=opening, transactions=transactions
    )


class TestSuspectBasis:
    """An undocumented opening basis set equal to the eventual sale proceeds -> ~$0 gain, unexplained."""

    def test_undocumented_basis_equal_to_proceeds_is_flagged(self) -> None:
        opening = [
            OpeningPosition(
                account_id="wb-margin",
                symbol="GLD",
                quantity=Decimal("10"),
                as_of=dt.date(2026, 1, 20),
                cost_basis=Decimal("4168.80"),  # equals the sale below, with no note explaining it
            )
        ]
        sell = make_txn(
            txn_id="s1",
            account_id="wb-margin",
            broker=Broker.WEBULL,
            action="sell",
            symbol="GLD",
            quantity="10",
            price="416.83",  # proceeds 4168.30 -- within a dollar of declared basis
            trade_date=dt.date(2026, 5, 15),
        )
        report = _audit([sell], opening)

        assert len(report.suspect) == 1
        sus = report.suspect[0]
        assert (sus.account_id, sus.symbol) == ("wb-margin", "GLD")
        assert sus.proceeds == Decimal("4168.30")
        assert sus.declared_basis == Decimal("4168.80")
        assert sus.gap == Decimal("0.50")
        assert not sus.is_tax_advantaged
        assert report.suspect_proceeds_taxable == Decimal("4168.30")
        # A lot with a (suspect) basis has non-zero basis, so it is NOT also counted as phantom gain.
        assert report.unbased == ()

    def test_documented_basis_near_proceeds_is_trusted(self) -> None:
        """The real-ledger case: a broker-reported transfer basis on a near-flat trade, with a note.

        Same near-proceeds shape as the flagged case, but the note records where the number came from,
        so it must NOT be flagged -- otherwise every legitimate near-flat transfer lot is noise.
        """
        opening = [
            OpeningPosition(
                account_id="wb-margin",
                symbol="TSIC",
                quantity=Decimal("50"),
                as_of=dt.date(2026, 1, 20),
                cost_basis=Decimal("1297.00"),
                note="Webull-reported Transfer-A cost basis (transfer_history 2.A)",
            )
        ]
        sell = make_txn(
            txn_id="s1",
            account_id="wb-margin",
            broker=Broker.WEBULL,
            action="sell",
            symbol="TSIC",
            quantity="50",
            price="25.97",  # proceeds 1298.50 -- within a dollar of basis, but documented
            trade_date=dt.date(2026, 5, 22),
        )
        report = _audit([sell], opening)
        assert report.is_clean

    def test_legitimate_opening_basis_is_not_flagged(self) -> None:
        """A real pre-window cost far from proceeds -- must stay clean even with no note."""
        opening = [
            OpeningPosition(
                account_id="wb-margin",
                symbol="GLD",
                quantity=Decimal("10"),
                as_of=dt.date(2026, 1, 20),
                cost_basis=Decimal("2100.00"),  # bought ~$210, sold ~$417: a real gain
            )
        ]
        sell = make_txn(
            txn_id="s1",
            account_id="wb-margin",
            broker=Broker.WEBULL,
            action="sell",
            symbol="GLD",
            quantity="10",
            price="416.83",
            trade_date=dt.date(2026, 5, 15),
        )
        report = _audit([sell], opening)
        assert report.is_clean


class TestPhantomGain:
    """Proceeds booked at $0 basis -- the whole proceeds are an overstatement."""

    def test_declared_opening_without_basis(self) -> None:
        opening = [
            OpeningPosition(
                account_id="wb-margin",
                symbol="NFLX",
                quantity=Decimal("75"),
                as_of=dt.date(2026, 1, 20),
                cost_basis=None,  # declared count, no basis
            )
        ]
        sell = make_txn(
            txn_id="s1",
            account_id="wb-margin",
            broker=Broker.WEBULL,
            action="sell",
            symbol="NFLX",
            quantity="75",
            price="98.77",
            trade_date=dt.date(2026, 4, 2),
        )
        report = _audit([sell], opening)

        assert report.suspect == ()
        assert len(report.unbased) == 1
        row = report.unbased[0]
        assert (row.account_id, row.symbol) == ("wb-margin", "NFLX")
        assert row.declared_opening is True
        assert row.phantom_gain == Decimal("7407.75")
        assert report.phantom_gain_taxable == Decimal("7407.75")

    def test_oversold_shortfall_is_undeclared_phantom_gain(self) -> None:
        """A sale with no prior buy and no opening -> zero-basis invented lot, flagged as undeclared."""
        sell = make_txn(
            txn_id="s1",
            account_id="wb-margin",
            broker=Broker.WEBULL,
            action="sell",
            symbol="DRAM",
            quantity="150",
            price="76.95",
            trade_date=dt.date(2026, 6, 23),
        )
        report = _audit([sell], [])

        assert len(report.unbased) == 1
        row = report.unbased[0]
        assert row.symbol == "DRAM"
        assert row.declared_opening is False
        assert row.phantom_gain == Decimal("11542.50")


class TestNoFalsePositiveOnRoundTrip:
    """The reason the fabrication check is scoped to opening lots: a real intraday round-trip bought
    and sold at nearly the same price has basis ~= proceeds too, and must never be flagged."""

    def test_intraday_scalp_near_flat_is_clean(self) -> None:
        buy = make_txn(
            txn_id="b1",
            account_id="wb-margin",
            broker=Broker.WEBULL,
            action="buy",
            symbol="TQQQ",
            quantity="50",
            price="74.10",
            trade_date=dt.date(2026, 8, 4),
        )
        sell = make_txn(
            txn_id="s1",
            account_id="wb-margin",
            broker=Broker.WEBULL,
            action="sell",
            symbol="TQQQ",
            quantity="50",
            price="74.12",  # basis 3705.00 vs proceeds 3706.00 -- within the band, but not an opening
            trade_date=dt.date(2026, 8, 4),
        )
        report = _audit([buy, sell], [])
        assert report.is_clean


class TestTaxTreatmentSplit:
    """Roth items are cosmetic; taxable items are the tax-relevant overstatement. They must not mix."""

    def test_roth_and_taxable_are_totalled_separately(self) -> None:
        opening = [
            OpeningPosition(
                account_id="wb-roth",
                symbol="AMD",
                quantity=Decimal("10"),
                as_of=dt.date(2026, 1, 20),
                cost_basis=None,
            ),
            OpeningPosition(
                account_id="wb-margin",
                symbol="NFLX",
                quantity=Decimal("75"),
                as_of=dt.date(2026, 1, 20),
                cost_basis=None,
            ),
        ]
        txns = [
            make_txn(
                txn_id="r1",
                account_id="wb-roth",
                broker=Broker.WEBULL,
                action="sell",
                symbol="AMD",
                quantity="10",
                price="255.77",
                trade_date=dt.date(2026, 1, 22),
            ),
            make_txn(
                txn_id="t1",
                account_id="wb-margin",
                broker=Broker.WEBULL,
                action="sell",
                symbol="NFLX",
                quantity="75",
                price="98.77",
                trade_date=dt.date(2026, 4, 2),
            ),
        ]
        report = _audit(txns, opening)

        assert report.phantom_gain_taxable == Decimal("7407.75")
        assert report.phantom_gain_tax_advantaged == Decimal("2557.70")

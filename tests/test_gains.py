"""Capital-gains classification and totals.

``LotLedger`` / ``Disposal`` objects are constructed by hand throughout rather than produced by
``build_lots`` -- that function is owned by another module and still raises ``NotImplementedError``
in this phase, but hand-built disposals are also simply the right level for a tax-rule test: each
case here is about one specific rule (a term boundary, an exclusion, a warning), not about replay.

Assertions are exact ``Decimal`` equality throughout. ``pytest.approx`` has no place in a tax test.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.core.lots import Disposal, LotLedger, LotWarning, WarningKind
from app.core.models import Account, Broker, TaxTreatment
from app.tax.gains import classify_term, realized_gains
from app.tax.models import HoldingTerm

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_account(
    account_id: str = "rh-taxable",
    *,
    tax_treatment: TaxTreatment = TaxTreatment.TAXABLE,
    label: str = "RH Taxable",
    broker: Broker = Broker.ROBINHOOD,
) -> Account:
    return Account(account_id=account_id, broker=broker, label=label, tax_treatment=tax_treatment)


_seq = 0


def make_disposal(
    *,
    disposal_id: str | None = None,
    lot_id: str = "lot-1",
    instrument_id: str = "instr-soxl",
    account_id: str = "rh-taxable",
    symbol: str = "SOXL",
    sell_txn_id: str | None = None,
    acquired_date: dt.date,
    holding_start: dt.date | None = None,
    disposed_date: dt.date,
    quantity: Decimal = Decimal(50),
    proceeds: Decimal = Decimal("1000.00"),
    cost_basis: Decimal = Decimal("800.00"),
    fees: Decimal = Decimal(0),
    disallowed_loss: Decimal = Decimal(0),
    permanently_disallowed: bool = False,
) -> Disposal:
    global _seq
    _seq += 1
    return Disposal(
        disposal_id=disposal_id or f"disp-{_seq}",
        lot_id=lot_id,
        instrument_id=instrument_id,
        account_id=account_id,
        symbol=symbol,
        sell_txn_id=sell_txn_id or f"sell-{_seq}",
        acquired_date=acquired_date,
        holding_start=holding_start if holding_start is not None else acquired_date,
        disposed_date=disposed_date,
        quantity=quantity,
        proceeds=proceeds,
        cost_basis=cost_basis,
        fees=fees,
        disallowed_loss=disallowed_loss,
        # `permanently_disallowed` is derived from the amount, because a sale replaced partly in an
        # IRA is partly permanent and partly deferred. These fixtures are all-or-nothing.
        permanently_disallowed_loss=(disallowed_loss if permanently_disallowed else Decimal(0)),
    )


def make_ledger(
    disposals: list[Disposal], warnings: list[LotWarning] | None = None
) -> LotLedger:
    return LotLedger(disposals=disposals, warnings=warnings or [])


def make_warning(
    kind: WarningKind,
    account_id: str,
    instrument_id: str,
    *,
    txn_id: str = "txn-1",
) -> LotWarning:
    return LotWarning(
        kind=kind,
        txn_id=txn_id,
        account_id=account_id,
        instrument_id=instrument_id,
        symbol="SOXL",
        trade_date=dt.date(2025, 1, 1),
        detail="test warning",
    )


# ---------------------------------------------------------------------------
# Term boundary -- classify_term directly
# ---------------------------------------------------------------------------


class TestClassifyTermBoundary:
    def test_exactly_one_year_is_short(self) -> None:
        assert classify_term(dt.date(2025, 1, 10), dt.date(2026, 1, 10)) is HoldingTerm.SHORT

    def test_one_year_and_a_day_is_long(self) -> None:
        assert classify_term(dt.date(2025, 1, 10), dt.date(2026, 1, 11)) is HoldingTerm.LONG

    def test_leap_year_acquisition_anniversary_is_short(self) -> None:
        """Feb 29 2024's anniversary in a non-leap year is Feb 28 2025 (Rev. Rul. 66-7)."""
        assert classify_term(dt.date(2024, 2, 29), dt.date(2025, 2, 28)) is HoldingTerm.SHORT

    def test_leap_year_acquisition_day_after_anniversary_is_long(self) -> None:
        assert classify_term(dt.date(2024, 2, 29), dt.date(2025, 3, 1)) is HoldingTerm.LONG

    def test_leap_year_acquisition_disposed_in_a_leap_year_still_correct(self) -> None:
        """Held from 2020-02-29 to 2021-02-28 exactly: still short (one year, not more)."""
        assert classify_term(dt.date(2020, 2, 29), dt.date(2021, 2, 28)) is HoldingTerm.SHORT


class TestClassifyTermEndToEnd:
    """The same boundary, through a real GainRow rather than the bare function."""

    def test_exactly_one_year_disposal_is_short(self) -> None:
        account = make_account()
        disposal = make_disposal(
            acquired_date=dt.date(2025, 1, 10),
            disposed_date=dt.date(2026, 1, 10),
        )
        report = realized_gains(
            make_ledger([disposal]),
            accounts={account.account_id: account},
            start=dt.date(2026, 1, 1),
            end=dt.date(2026, 1, 31),
        )
        assert len(report.rows) == 1
        assert report.rows[0].term is HoldingTerm.SHORT

    def test_one_year_and_a_day_disposal_is_long(self) -> None:
        account = make_account()
        disposal = make_disposal(
            acquired_date=dt.date(2025, 1, 10),
            disposed_date=dt.date(2026, 1, 11),
        )
        report = realized_gains(
            make_ledger([disposal]),
            accounts={account.account_id: account},
            start=dt.date(2026, 1, 1),
            end=dt.date(2026, 1, 31),
        )
        assert len(report.rows) == 1
        assert report.rows[0].term is HoldingTerm.LONG


# ---------------------------------------------------------------------------
# Standing test case #10: tolled holding start flips short into long
# ---------------------------------------------------------------------------


class TestTolledHoldingStart:
    def test_tolled_holding_start_converts_short_to_long(self) -> None:
        """A wash sale on an earlier lot tolled this replacement lot's holding period back to
        2023-01-01. The literal purchase (acquired_date) was only five months before the sale --
        short-term if classified naively -- but the tolled start is well over a year before the
        sale, so the correct classification is long-term. Classifying off ``acquired_date`` instead
        of ``holding_start`` is exactly the defect this test exists to catch.
        """
        acquired_date = dt.date(2025, 1, 1)
        tolled_start = dt.date(2023, 1, 1)
        disposed_date = dt.date(2025, 6, 1)

        # Prove the naive (wrong) classification really would be short-term, so the test is not
        # vacuous.
        assert classify_term(acquired_date, disposed_date) is HoldingTerm.SHORT
        assert classify_term(tolled_start, disposed_date) is HoldingTerm.LONG

        account = make_account()
        disposal = make_disposal(
            acquired_date=acquired_date,
            holding_start=tolled_start,
            disposed_date=disposed_date,
        )
        report = realized_gains(
            make_ledger([disposal]),
            accounts={account.account_id: account},
            start=dt.date(2025, 1, 1),
            end=dt.date(2025, 12, 31),
        )
        row = report.rows[0]
        assert row.term is HoldingTerm.LONG
        assert row.holding_start == tolled_start
        assert row.acquired_date == acquired_date
        # And it landed in the long-term bucket, not the short-term one.
        assert report.long_term_gain == row.reportable_gain_loss
        assert report.short_term_gain == Decimal(0)


# ---------------------------------------------------------------------------
# Tax-advantaged exclusion (dual behaviour, taxable-figures half)
# ---------------------------------------------------------------------------


class TestTaxAdvantagedExclusion:
    def test_ira_disposal_excluded_from_rows_and_totals_but_id_recorded(self) -> None:
        taxable = make_account("rh-taxable", tax_treatment=TaxTreatment.TAXABLE, label="RH Taxable")
        ira = make_account("rh-roth", tax_treatment=TaxTreatment.ROTH_IRA, label="RH Roth")

        taxable_disposal = make_disposal(
            account_id="rh-taxable",
            acquired_date=dt.date(2024, 1, 1),
            disposed_date=dt.date(2025, 6, 1),
            proceeds=Decimal("1000.00"),
            cost_basis=Decimal("800.00"),
        )
        ira_disposal = make_disposal(
            account_id="rh-roth",
            acquired_date=dt.date(2024, 1, 1),
            disposed_date=dt.date(2025, 6, 1),
            proceeds=Decimal("5000.00"),
            cost_basis=Decimal("1000.00"),
        )

        report = realized_gains(
            make_ledger([taxable_disposal, ira_disposal]),
            accounts={taxable.account_id: taxable, ira.account_id: ira},
            start=dt.date(2025, 1, 1),
            end=dt.date(2025, 12, 31),
        )

        assert len(report.rows) == 1
        assert report.rows[0].account_id == "rh-taxable"
        assert report.excluded_account_ids == ("rh-roth",)
        # The huge IRA gain must not leak into the taxable total.
        assert report.long_term_gain == Decimal("200.00")

    def test_traditional_ira_also_excluded(self) -> None:
        account = make_account("trad-ira", tax_treatment=TaxTreatment.TRADITIONAL_IRA)
        disposal = make_disposal(
            account_id="trad-ira",
            acquired_date=dt.date(2024, 1, 1),
            disposed_date=dt.date(2025, 6, 1),
        )
        report = realized_gains(
            make_ledger([disposal]),
            accounts={account.account_id: account},
            start=dt.date(2025, 1, 1),
            end=dt.date(2025, 12, 31),
        )
        assert report.rows == ()
        assert report.excluded_account_ids == ("trad-ira",)
        assert report.net_gain == Decimal(0)


# ---------------------------------------------------------------------------
# Ordinary vs. permanent disallowance -- separate totals
# ---------------------------------------------------------------------------


class TestDisallowanceTotals:
    def test_ordinary_and_permanent_kept_separate(self) -> None:
        account = make_account()
        ordinary = make_disposal(
            disposal_id="d-ordinary",
            acquired_date=dt.date(2025, 1, 1),
            disposed_date=dt.date(2025, 3, 1),
            proceeds=Decimal("500.00"),
            cost_basis=Decimal("700.00"),
            disallowed_loss=Decimal("100.00"),
            permanently_disallowed=False,
        )
        permanent = make_disposal(
            disposal_id="d-permanent",
            acquired_date=dt.date(2025, 1, 1),
            disposed_date=dt.date(2025, 3, 2),
            proceeds=Decimal("500.00"),
            cost_basis=Decimal("700.00"),
            disallowed_loss=Decimal("50.00"),
            permanently_disallowed=True,
        )
        report = realized_gains(
            make_ledger([ordinary, permanent]),
            accounts={account.account_id: account},
            start=dt.date(2025, 1, 1),
            end=dt.date(2025, 12, 31),
        )
        assert report.disallowed_loss_total == Decimal("100.00")
        assert report.permanently_disallowed_total == Decimal("50.00")
        # Never folded together: the ordinary total alone must not already contain the IRA case.
        assert report.disallowed_loss_total != Decimal("150.00")
        assert report.disallowed_loss_total + report.permanently_disallowed_total == Decimal(
            "150.00"
        )


# ---------------------------------------------------------------------------
# Date-range filtering, both boundaries inclusive
# ---------------------------------------------------------------------------


class TestDateRangeFiltering:
    def test_inclusive_start_and_end_boundaries(self) -> None:
        account = make_account()
        start = dt.date(2025, 1, 1)
        end = dt.date(2025, 12, 31)

        before = make_disposal(
            disposal_id="before",
            acquired_date=dt.date(2024, 1, 1),
            disposed_date=start - dt.timedelta(days=1),
        )
        on_start = make_disposal(
            disposal_id="on-start",
            acquired_date=dt.date(2024, 1, 1),
            disposed_date=start,
        )
        on_end = make_disposal(
            disposal_id="on-end",
            acquired_date=dt.date(2024, 1, 1),
            disposed_date=end,
        )
        after = make_disposal(
            disposal_id="after",
            acquired_date=dt.date(2024, 1, 1),
            disposed_date=end + dt.timedelta(days=1),
        )

        report = realized_gains(
            make_ledger([before, on_start, on_end, after]),
            accounts={account.account_id: account},
            start=start,
            end=end,
        )
        ids = {row.disposal_id for row in report.rows}
        assert ids == {"on-start", "on-end"}


# ---------------------------------------------------------------------------
# basis_uncertain propagation from ledger warnings
# ---------------------------------------------------------------------------


class TestBasisUncertain:
    def test_oversold_warning_marks_row_uncertain_and_is_counted(self) -> None:
        # `app.core.lots.build_ledger` always raises OVERSOLD with `txn_id` set to the very sale
        # that produced the shortfall, which becomes that disposal's `sell_txn_id` -- so a
        # realistic warning and disposal share an id, unlike the mismatched ids used for the
        # kind/account isolation tests below where the id is irrelevant to what is being proven.
        account = make_account()
        disposal = make_disposal(
            account_id="rh-taxable",
            instrument_id="instr-soxl",
            sell_txn_id="sell-oversold",
            acquired_date=dt.date(2024, 1, 1),
            disposed_date=dt.date(2025, 6, 1),
        )
        warning = make_warning(
            WarningKind.OVERSOLD, "rh-taxable", "instr-soxl", txn_id="sell-oversold"
        )
        report = realized_gains(
            make_ledger([disposal], warnings=[warning]),
            accounts={account.account_id: account},
            start=dt.date(2025, 1, 1),
            end=dt.date(2025, 12, 31),
        )
        assert report.rows[0].basis_uncertain is True
        assert report.rows_with_uncertain_basis == 1

    def test_missing_basis_warning_marks_the_matching_sale_uncertain(self) -> None:
        # Same reasoning as the OVERSOLD case: MISSING_BASIS is raised in the same per-lot loop
        # that builds the Disposal, so `warning.txn_id == disposal.sell_txn_id` for a genuine hit.
        account = make_account()
        disposal = make_disposal(
            account_id="rh-taxable",
            instrument_id="instr-soxl",
            sell_txn_id="sell-missing-basis",
            acquired_date=dt.date(2024, 1, 1),
            disposed_date=dt.date(2025, 6, 1),
        )
        warning = make_warning(
            WarningKind.MISSING_BASIS, "rh-taxable", "instr-soxl", txn_id="sell-missing-basis"
        )
        report = realized_gains(
            make_ledger([disposal], warnings=[warning]),
            accounts={account.account_id: account},
            start=dt.date(2025, 1, 1),
            end=dt.date(2025, 12, 31),
        )
        assert report.rows[0].basis_uncertain is True
        assert report.rows_with_uncertain_basis == 1

    def test_unmatched_transfer_in_marks_uncertain_despite_no_shared_txn_id(self) -> None:
        # UNMATCHED_TRANSFER_IN is raised on the *receiving transfer* transaction, never on a
        # sale, so it can never share a `txn_id` with any `Disposal.sell_txn_id` -- unlike
        # OVERSOLD/MISSING_BASIS above, this warning is deliberately matched on
        # (account_id, instrument_id) alone. See test_unmatched_transfer_in_stays_position_scoped
        # below for why that breadth is intentional rather than the bug in the other two kinds.
        account = make_account()
        disposal = make_disposal(
            account_id="rh-taxable",
            instrument_id="instr-soxl",
            sell_txn_id="sell-later",
            acquired_date=dt.date(2024, 1, 1),
            disposed_date=dt.date(2025, 6, 1),
        )
        warning = make_warning(
            WarningKind.UNMATCHED_TRANSFER_IN,
            "rh-taxable",
            "instr-soxl",
            txn_id="transfer-in-1",
        )
        report = realized_gains(
            make_ledger([disposal], warnings=[warning]),
            accounts={account.account_id: account},
            start=dt.date(2025, 1, 1),
            end=dt.date(2025, 12, 31),
        )
        assert report.rows[0].basis_uncertain is True
        assert report.rows_with_uncertain_basis == 1

    def test_unrelated_warning_kind_does_not_mark_uncertain(self) -> None:
        account = make_account()
        disposal = make_disposal(
            account_id="rh-taxable",
            instrument_id="instr-soxl",
            acquired_date=dt.date(2024, 1, 1),
            disposed_date=dt.date(2025, 6, 1),
        )
        warning = make_warning(WarningKind.UNSUPPORTED_ACTION, "rh-taxable", "instr-soxl")
        report = realized_gains(
            make_ledger([disposal], warnings=[warning]),
            accounts={account.account_id: account},
            start=dt.date(2025, 1, 1),
            end=dt.date(2025, 12, 31),
        )
        assert report.rows[0].basis_uncertain is False
        assert report.rows_with_uncertain_basis == 0

    def test_warning_on_a_different_account_does_not_mark_this_row(self) -> None:
        account = make_account()
        disposal = make_disposal(
            account_id="rh-taxable",
            instrument_id="instr-soxl",
            sell_txn_id="sell-oversold",
            acquired_date=dt.date(2024, 1, 1),
            disposed_date=dt.date(2025, 6, 1),
        )
        warning = make_warning(
            WarningKind.OVERSOLD, "some-other-account", "instr-soxl", txn_id="sell-oversold"
        )
        report = realized_gains(
            make_ledger([disposal], warnings=[warning]),
            accounts={account.account_id: account},
            start=dt.date(2025, 1, 1),
            end=dt.date(2025, 12, 31),
        )
        assert report.rows[0].basis_uncertain is False


# ---------------------------------------------------------------------------
# Defect regression: basis_uncertain must not bleed across unrelated disposals
# ---------------------------------------------------------------------------


class TestBasisUncertainScoping:
    """Proven defect: keying the uncertain-lot set on (account_id, instrument_id) alone means one
    OVERSOLD/MISSING_BASIS warning from a single sale taints *every* disposal ever made of that
    symbol in that account, including disposals from lots with a fully known basis that were
    bought and sold long after the warning's sale. The fix narrows OVERSOLD/MISSING_BASIS to the
    one sale that produced them (`LotWarning.txn_id` matched against `Disposal.sell_txn_id`)
    while leaving UNMATCHED_TRANSFER_IN broad, because that kind has no sale to narrow to (see
    `TestBasisUncertain.test_unmatched_transfer_in_marks_uncertain_despite_no_shared_txn_id`).
    """

    def test_oversold_on_one_sale_does_not_taint_a_later_clean_sale(self) -> None:
        account = make_account()

        # buy1 10sh@$10 (Jan 1); sell1 sells 20sh (Jan 2) against only the 10 held -> OVERSOLD.
        # The shortfall disposal genuinely has no known basis.
        oversold_disposal = make_disposal(
            disposal_id="sell1-shortfall",
            account_id="rh-taxable",
            instrument_id="instr-soxl",
            sell_txn_id="sell1",
            acquired_date=dt.date(2025, 1, 2),
            holding_start=dt.date(2025, 1, 2),
            disposed_date=dt.date(2025, 1, 2),
            quantity=Decimal(10),
            proceeds=Decimal("150.00"),
            cost_basis=Decimal(0),
        )
        oversold_warning = make_warning(WarningKind.OVERSOLD, "rh-taxable", "instr-soxl", txn_id="sell1")

        # buy2 10sh@$12 (Feb 1) is completely clean; sell2 sells those 10sh (Mar 1) with a fully
        # known basis and no warning of its own.
        clean_disposal = make_disposal(
            disposal_id="sell2-clean",
            account_id="rh-taxable",
            instrument_id="instr-soxl",
            sell_txn_id="sell2",
            acquired_date=dt.date(2025, 2, 1),
            holding_start=dt.date(2025, 2, 1),
            disposed_date=dt.date(2025, 3, 1),
            quantity=Decimal(10),
            proceeds=Decimal("140.00"),
            cost_basis=Decimal("120.00"),
        )

        report = realized_gains(
            make_ledger(
                [oversold_disposal, clean_disposal],
                warnings=[oversold_warning],
            ),
            accounts={account.account_id: account},
            start=dt.date(2025, 1, 1),
            end=dt.date(2025, 12, 31),
        )

        rows_by_id = {row.disposal_id: row for row in report.rows}
        assert rows_by_id["sell1-shortfall"].basis_uncertain is True
        # This is the defect: the Mar 1 disposal came out `basis_uncertain=True` despite a fully
        # known basis, purely because it shares (account_id, instrument_id) with sell1.
        assert rows_by_id["sell2-clean"].basis_uncertain is False
        assert report.rows_with_uncertain_basis == 1


# ---------------------------------------------------------------------------
# fees_unknown propagation from ledger warnings -- finding 3.2
# ---------------------------------------------------------------------------


class TestFeesUnknown:
    """`WarningKind.FEES_UNKNOWN` follows the exact same lot-scoped matching as OVERSOLD/
    MISSING_BASIS (`_FEES_UNKNOWN_KINDS`, matched on `(account_id, instrument_id, sell_txn_id)`),
    but must land on its own `GainRow.fees_unknown` flag rather than `basis_uncertain` -- a sale can
    have a fully known basis and still be missing its own fee, and the two must not be conflated.
    """

    def test_fees_unknown_warning_marks_the_matching_sale(self) -> None:
        account = make_account()
        disposal = make_disposal(
            account_id="rh-taxable",
            instrument_id="instr-soxl",
            sell_txn_id="sell-webull",
            acquired_date=dt.date(2024, 1, 1),
            disposed_date=dt.date(2025, 6, 1),
        )
        warning = make_warning(
            WarningKind.FEES_UNKNOWN, "rh-taxable", "instr-soxl", txn_id="sell-webull"
        )
        report = realized_gains(
            make_ledger([disposal], warnings=[warning]),
            accounts={account.account_id: account},
            start=dt.date(2025, 1, 1),
            end=dt.date(2025, 12, 31),
        )
        assert report.rows[0].fees_unknown is True
        assert report.rows_with_unknown_fees == 1
        # Independent of basis_uncertain: this disposal's basis is fully known.
        assert report.rows[0].basis_uncertain is False
        assert report.rows_with_uncertain_basis == 0

    def test_fees_unknown_does_not_bleed_to_an_unrelated_sale(self) -> None:
        account = make_account()
        flagged = make_disposal(
            disposal_id="flagged",
            account_id="rh-taxable",
            instrument_id="instr-soxl",
            sell_txn_id="sell-webull",
            acquired_date=dt.date(2024, 1, 1),
            disposed_date=dt.date(2025, 6, 1),
        )
        clean = make_disposal(
            disposal_id="clean",
            account_id="rh-taxable",
            instrument_id="instr-soxl",
            sell_txn_id="sell-other",
            acquired_date=dt.date(2024, 2, 1),
            disposed_date=dt.date(2025, 7, 1),
        )
        warning = make_warning(
            WarningKind.FEES_UNKNOWN, "rh-taxable", "instr-soxl", txn_id="sell-webull"
        )
        report = realized_gains(
            make_ledger([flagged, clean], warnings=[warning]),
            accounts={account.account_id: account},
            start=dt.date(2025, 1, 1),
            end=dt.date(2025, 12, 31),
        )
        rows_by_id = {row.disposal_id: row for row in report.rows}
        assert rows_by_id["flagged"].fees_unknown is True
        assert rows_by_id["clean"].fees_unknown is False
        assert report.rows_with_unknown_fees == 1

    def test_basis_uncertain_and_fees_unknown_can_coexist(self) -> None:
        """A disposal can carry both problems at once (e.g. an oversold Webull lot) -- each flag is
        independently true, neither substitutes for the other."""
        account = make_account()
        disposal = make_disposal(
            account_id="rh-taxable",
            instrument_id="instr-soxl",
            sell_txn_id="sell-both",
            acquired_date=dt.date(2025, 6, 1),
            disposed_date=dt.date(2025, 6, 1),
            cost_basis=Decimal(0),
        )
        oversold = make_warning(WarningKind.OVERSOLD, "rh-taxable", "instr-soxl", txn_id="sell-both")
        fees = make_warning(
            WarningKind.FEES_UNKNOWN, "rh-taxable", "instr-soxl", txn_id="sell-both"
        )
        report = realized_gains(
            make_ledger([disposal], warnings=[oversold, fees]),
            accounts={account.account_id: account},
            start=dt.date(2025, 1, 1),
            end=dt.date(2025, 12, 31),
        )
        assert report.rows[0].basis_uncertain is True
        assert report.rows[0].fees_unknown is True


# ---------------------------------------------------------------------------
# Totals reconcile to the sum of rows, to the cent
# ---------------------------------------------------------------------------


class TestTotalsReconcile:
    def test_totals_equal_sum_of_rows(self) -> None:
        account = make_account()
        disposals = [
            make_disposal(
                disposal_id="short-1",
                acquired_date=dt.date(2025, 1, 1),
                disposed_date=dt.date(2025, 6, 1),
                proceeds=Decimal("333.33"),
                cost_basis=Decimal("111.11"),
                fees=Decimal("1.00"),
            ),
            make_disposal(
                disposal_id="short-2",
                acquired_date=dt.date(2025, 1, 1),
                disposed_date=dt.date(2025, 6, 2),
                proceeds=Decimal("777.77"),
                cost_basis=Decimal("555.55"),
                fees=Decimal("2.50"),
            ),
            make_disposal(
                disposal_id="long-1",
                acquired_date=dt.date(2023, 1, 1),
                disposed_date=dt.date(2025, 6, 3),
                proceeds=Decimal("1234.56"),
                cost_basis=Decimal("999.99"),
                fees=Decimal("3.33"),
            ),
        ]
        report = realized_gains(
            make_ledger(disposals),
            accounts={account.account_id: account},
            start=dt.date(2025, 1, 1),
            end=dt.date(2025, 12, 31),
        )

        short_rows = [r for r in report.rows if r.term is HoldingTerm.SHORT]
        long_rows = [r for r in report.rows if r.term is HoldingTerm.LONG]

        assert report.short_term_proceeds == sum((r.proceeds for r in short_rows), Decimal(0))
        assert report.short_term_basis == sum((r.cost_basis for r in short_rows), Decimal(0))
        assert report.short_term_gain == sum(
            (r.reportable_gain_loss for r in short_rows), Decimal(0)
        )
        assert report.long_term_proceeds == sum((r.proceeds for r in long_rows), Decimal(0))
        assert report.long_term_basis == sum((r.cost_basis for r in long_rows), Decimal(0))
        assert report.long_term_gain == sum(
            (r.reportable_gain_loss for r in long_rows), Decimal(0)
        )


class TestTheSizeOfTheUncertainty:
    """A count is not a size, and on real data the two tell opposite stories.

    A small fraction of disposals carrying an unestablished basis reads as a rounding concern. On a
    real ledger those few rows contributed a large gain while all the others netted to a loss: the
    headline gain was not slightly overstated by them, it was produced by them. A caveat that reports only the count lets a
    reader conclude the figure is approximately right when it is mostly missing basis.
    """

    def _report(self, disposals, warnings):  # type: ignore[no-untyped-def]
        account = make_account()
        return realized_gains(
            make_ledger(disposals, warnings=warnings),
            accounts={account.account_id: account},
            start=dt.date(2025, 1, 1),
            end=dt.date(2025, 12, 31),
        )

    def test_the_gain_from_uncertain_rows_is_totalled_not_just_counted(self) -> None:
        uncertain = make_disposal(
            disposal_id="d-uncertain",
            sell_txn_id="sell-uncertain",
            quantity="10",
            proceeds="5000.00",
            cost_basis="0",
            acquired_date=dt.date(2024, 1, 1),
            disposed_date=dt.date(2025, 6, 1),
        )
        known = make_disposal(
            disposal_id="d-known",
            sell_txn_id="sell-known",
            quantity="10",
            proceeds="1000.00",
            cost_basis="4000.00",
            acquired_date=dt.date(2024, 1, 1),
            disposed_date=dt.date(2025, 6, 1),
        )
        report = self._report(
            [uncertain, known],
            [make_warning(WarningKind.OVERSOLD, "rh-taxable", "instr-soxl", txn_id="sell-uncertain")],
        )

        # One row of five thousand gain, one of three thousand loss: the net reads +2,000 and looks
        # modest, while every dollar of it rests on a basis nobody established.
        assert report.rows_with_uncertain_basis == 1
        assert report.gain_on_uncertain_basis == Decimal("5000.00")
        assert report.proceeds_on_uncertain_basis == Decimal("5000.00")
        assert report.basis_on_uncertain_basis == Decimal("0")
        assert report.short_term_gain + report.long_term_gain == Decimal("2000.00")

    def test_a_partly_established_basis_is_recorded_as_partial_not_zero(self) -> None:
        """A row can be flagged uncertain while still carrying real basis -- the lot was only partly
        unknown. Reporting its basis as zero would overstate the correction available."""
        row = make_disposal(
            disposal_id="d1",
            sell_txn_id="sell-1",
            quantity="10",
            proceeds="5000.00",
            cost_basis="1500.00",
            acquired_date=dt.date(2024, 1, 1),
            disposed_date=dt.date(2025, 6, 1),
        )
        report = self._report(
            [row], [make_warning(WarningKind.MISSING_BASIS, "rh-taxable", "instr-soxl", txn_id="sell-1")]
        )
        assert report.basis_on_uncertain_basis == Decimal("1500.00")
        assert report.gain_on_uncertain_basis == Decimal("3500.00")

    def test_a_clean_year_reports_zero_rather_than_nothing(self) -> None:
        """Zero rows must give zero totals, not a null a caller could divide by."""
        row = make_disposal(
            disposal_id="d1",
            sell_txn_id="sell-1",
            quantity="10",
            proceeds="5000.00",
            cost_basis="4000.00",
            acquired_date=dt.date(2024, 1, 1),
            disposed_date=dt.date(2025, 6, 1),
        )
        report = self._report([row], [])
        assert report.rows_with_uncertain_basis == 0
        assert report.gain_on_uncertain_basis == Decimal(0)
        assert report.proceeds_on_uncertain_basis == Decimal(0)
        assert report.basis_on_uncertain_basis == Decimal(0)

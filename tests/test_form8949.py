"""IRS Form 8949 box selection, the (h) identity, subtotals, and CSV output.

``GainRow`` objects are constructed by hand -- ``realized_gains`` is exercised in
``tests/test_gains.py``; here the point is Form 8949's own arithmetic and formatting, isolated from
how a row was classified.

The one exception is ``TestProceedsNetOfFeesAndGainLossIdentity``, which routes through
``realized_gains`` deliberately: the defect it guards against lives exactly on the boundary between
how ``app.tax.gains`` rounds a raw ``Disposal`` into a ``GainRow`` and how this module then nets fees
out of it, so a ``GainRow`` built by hand at 2-decimal precision cannot exercise it -- see that
class's docstring.

Assertions are exact ``Decimal`` equality throughout.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from decimal import Decimal

import pytest

from app.core.lots import Disposal, LotLedger
from app.core.models import Account, Broker, TaxTreatment
from app.tax.form8949 import (
    _FORMULA_TRIGGER_CHARS,
    _PLAIN_NUMBER_RE,
    _sanitize_cell,
    build_form8949,
    select_box,
    to_csv,
)
from app.tax.gains import realized_gains
from app.tax.models import (
    Form8949Box,
    Form8949Report,
    Form8949Row,
    GainRow,
    GainsReport,
    HoldingTerm,
)

_seq = 0


def make_row(
    *,
    disposal_id: str | None = None,
    symbol: str = "SOXL",
    account_id: str = "rh-taxable",
    account_label: str = "RH Taxable",
    quantity: Decimal = Decimal(50),
    acquired_date: dt.date = dt.date(2024, 1, 1),
    holding_start: dt.date | None = None,
    disposed_date: dt.date = dt.date(2025, 6, 1),
    term: HoldingTerm = HoldingTerm.LONG,
    proceeds: Decimal = Decimal("1000.00"),
    cost_basis: Decimal = Decimal("800.00"),
    fees: Decimal = Decimal(0),
    disallowed_loss: Decimal = Decimal(0),
    permanently_disallowed: bool = False,
    is_wash_sale: bool = False,
    basis_uncertain: bool = False,
) -> GainRow:
    global _seq
    _seq += 1
    gain_loss = proceeds - fees - cost_basis
    is_loss = gain_loss < 0
    reportable = gain_loss + disallowed_loss if is_loss else gain_loss
    return GainRow(
        disposal_id=disposal_id or f"disp-{_seq}",
        instrument_id="instr-soxl",
        symbol=symbol,
        account_id=account_id,
        account_label=account_label,
        quantity=quantity,
        lot_id=f"lot-{_seq}",
        lot_method="fifo",
        acquired_date=acquired_date,
        holding_start=holding_start if holding_start is not None else acquired_date,
        disposed_date=disposed_date,
        term=term,
        proceeds=proceeds,
        cost_basis=cost_basis,
        fees=fees,
        gain_loss=gain_loss,
        disallowed_loss=disallowed_loss,
        permanently_disallowed=permanently_disallowed,
        reportable_gain_loss=reportable,
        is_wash_sale=is_wash_sale,
        basis_uncertain=basis_uncertain,
    )


def make_report(rows: list[GainRow]) -> GainsReport:
    short_rows = [r for r in rows if r.term is HoldingTerm.SHORT]
    long_rows = [r for r in rows if r.term is HoldingTerm.LONG]
    return GainsReport(
        start=dt.date(2025, 1, 1),
        end=dt.date(2025, 12, 31),
        rows=tuple(rows),
        short_term_proceeds=sum((r.proceeds for r in short_rows), Decimal(0)),
        short_term_basis=sum((r.cost_basis for r in short_rows), Decimal(0)),
        short_term_gain=sum((r.reportable_gain_loss for r in short_rows), Decimal(0)),
        long_term_proceeds=sum((r.proceeds for r in long_rows), Decimal(0)),
        long_term_basis=sum((r.cost_basis for r in long_rows), Decimal(0)),
        long_term_gain=sum((r.reportable_gain_loss for r in long_rows), Decimal(0)),
    )


# ---------------------------------------------------------------------------
# Box selection
# ---------------------------------------------------------------------------


class TestSelectBox:
    def test_short_term_covered_is_box_a(self) -> None:
        row = make_row(term=HoldingTerm.SHORT)
        assert select_box(row, basis_reported=True) is Form8949Box.A

    def test_long_term_covered_is_box_d(self) -> None:
        row = make_row(term=HoldingTerm.LONG)
        assert select_box(row, basis_reported=True) is Form8949Box.D

    def test_short_term_basis_not_reported_is_box_b(self) -> None:
        row = make_row(term=HoldingTerm.SHORT)
        assert select_box(row, basis_reported=False) is Form8949Box.B

    def test_long_term_basis_not_reported_is_box_e(self) -> None:
        row = make_row(term=HoldingTerm.LONG)
        assert select_box(row, basis_reported=False) is Form8949Box.E

    def test_build_form8949_uses_box_b_for_basis_uncertain_row(self) -> None:
        """build_form8949 derives basis_reported from GainRow.basis_uncertain: an unmatched
        transfer-in means the receiving broker never got a basis figure to report."""
        row = make_row(term=HoldingTerm.SHORT, basis_uncertain=True)
        report = build_form8949(make_report([row]))
        assert report.rows[0].box is Form8949Box.B

    def test_build_form8949_uses_box_a_for_ordinary_row(self) -> None:
        row = make_row(term=HoldingTerm.SHORT, basis_uncertain=False)
        report = build_form8949(make_report([row]))
        assert report.rows[0].box is Form8949Box.A


# ---------------------------------------------------------------------------
# Wash-sale adjustment code and amount
# ---------------------------------------------------------------------------


class TestWashSaleAdjustment:
    def test_wash_sale_row_carries_code_w_and_positive_adjustment(self) -> None:
        row = make_row(
            proceeds=Decimal("500.00"),
            cost_basis=Decimal("700.00"),
            disallowed_loss=Decimal("200.00"),
            is_wash_sale=True,
        )
        report = build_form8949(make_report([row]))
        form_row = report.rows[0]
        assert form_row.adjustment_code == "W"
        assert form_row.adjustment_amount == Decimal("200.00")
        assert form_row.adjustment_amount > 0

    def test_non_wash_row_carries_no_code_and_zero_adjustment(self) -> None:
        row = make_row(proceeds=Decimal("1000.00"), cost_basis=Decimal("800.00"))
        report = build_form8949(make_report([row]))
        form_row = report.rows[0]
        assert form_row.adjustment_code is None
        assert form_row.adjustment_amount == Decimal(0)

    def test_fully_disallowed_wash_sale_loss_nets_to_zero(self) -> None:
        """A loss sale where the entire loss was disallowed (100% replacement) must report a $0
        gain/loss on the form, not the pre-disallowance loss."""
        row = make_row(
            proceeds=Decimal("500.00"),
            cost_basis=Decimal("700.00"),
            disallowed_loss=Decimal("200.00"),
            is_wash_sale=True,
        )
        report = build_form8949(make_report([row]))
        assert report.rows[0].gain_loss == Decimal(0)

    def test_a_disallowance_a_cent_over_the_loss_cannot_report_a_gain(self) -> None:
        """A row may never say "wash sale" in (g) and "profit" in (h) at the same time.

        The disallowance never exceeds its loss in the unrounded figures -- on a real ledger
        no wash-sale event does. But the loss and the disallowance are quantized independently, so
        a loss rounding down while its disallowance rounds up leaves them a cent apart. Two rows on
        a real ledger did exactly that, and each reported a $0.01 *gain* on a loss that had been
        disallowed in full.

        The adjustment is therefore capped at the loss the row itself reports. Note this is a cap
        on what the *form* may claim: `GainRow.disallowed_loss` stays the economic figure, because
        `GainsReport.disallowed_loss_total` has to keep reconciling to the cent with the sum of the
        wash-sale events (`test_canonical`). Capping the economic figure instead broke exactly that.
        """
        row = make_row(
            proceeds=Decimal("4104.15"),
            cost_basis=Decimal("5294.25"),
            disallowed_loss=Decimal("1190.11"),  # a cent more than the 1190.10 loss
            is_wash_sale=True,
        )
        form_row = build_form8949(make_report([row])).rows[0]

        assert form_row.gain_loss == Decimal("0.00")
        assert form_row.adjustment_amount == Decimal("1190.10")
        assert form_row.adjustment_amount <= form_row.cost_basis - form_row.proceeds
        # The identity the whole form rests on still holds after the cap.
        assert (
            form_row.proceeds - form_row.cost_basis + form_row.adjustment_amount
            == form_row.gain_loss
        )


# ---------------------------------------------------------------------------
# Column (d) is NET of fees, and the (h) = (d) - (e) + (g) identity
# ---------------------------------------------------------------------------


class TestProceedsNetOfFeesAndGainLossIdentity:
    """Ground-truth checks for (d) and the (h) = (d) - (e) + (g) identity.

    The identity checks below assert against Decimal literals computed independently by hand, not
    against ``form_row.proceeds - form_row.cost_basis + form_row.adjustment_amount`` -- that
    formula *is* how ``_to_form_row`` computes (h), so asserting a row equals its own formula
    passes unconditionally and would not have caught the defect this class exists to guard
    against (see the two-decimal-vs-sub-cent tests below).

    All of the tests up to that point use ``make_row``, whose inputs are already at 2-decimal
    precision -- exactly the case where double-rounding gross proceeds and fees separately is
    invisible, because rounding an already-2-decimal number is a no-op. The sub-cent tests that
    follow build a raw, unrounded ``Disposal`` and drive it through ``realized_gains`` instead,
    which is the only way to reach the defect: it lives in how ``app.tax.gains`` rounds
    ``Disposal.proceeds`` and ``Disposal.fees`` into a ``GainRow`` *before* this module ever sees
    them, not in this module's own arithmetic.
    """

    def test_column_d_is_gross_proceeds_minus_fees(self) -> None:
        row = make_row(
            proceeds=Decimal("1000.00"),
            fees=Decimal("9.95"),
            cost_basis=Decimal("800.00"),
        )
        report = build_form8949(make_report([row]))
        form_row = report.rows[0]
        assert form_row.proceeds == Decimal("990.05")
        assert form_row.proceeds < row.proceeds

    def test_identity_holds_on_a_plain_gain_row(self) -> None:
        row = make_row(
            proceeds=Decimal("1234.56"),
            fees=Decimal("4.56"),
            cost_basis=Decimal("900.11"),
        )
        report = build_form8949(make_report([row]))
        form_row = report.rows[0]
        assert form_row.proceeds == Decimal("1230.00")
        assert form_row.gain_loss == Decimal("329.89")

    def test_identity_holds_on_a_wash_sale_row_with_fees(self) -> None:
        row = make_row(
            proceeds=Decimal("500.00"),
            fees=Decimal("2.50"),
            cost_basis=Decimal("700.00"),
            disallowed_loss=Decimal("197.50"),
            is_wash_sale=True,
        )
        report = build_form8949(make_report([row]))
        form_row = report.rows[0]
        # This particular row was constructed to fully disallow: (500-2.50)-700+197.50 == -5.00,
        # not zero -- picked deliberately non-trivial rather than the round-number case above.
        assert form_row.gain_loss == Decimal("-5.00")

    def test_identity_holds_across_a_mixed_report(self) -> None:
        rows = [
            make_row(
                disposal_id="gain",
                term=HoldingTerm.LONG,
                proceeds=Decimal("2000.00"),
                fees=Decimal("1.23"),
                cost_basis=Decimal("1500.00"),
            ),
            make_row(
                disposal_id="wash-loss",
                term=HoldingTerm.SHORT,
                proceeds=Decimal("300.00"),
                fees=Decimal("0.75"),
                cost_basis=Decimal("500.00"),
                disallowed_loss=Decimal("199.25"),
                is_wash_sale=True,
            ),
            make_row(
                disposal_id="plain-loss",
                term=HoldingTerm.SHORT,
                proceeds=Decimal("100.00"),
                fees=Decimal("0.50"),
                cost_basis=Decimal("150.00"),
            ),
        ]
        report = build_form8949(make_report(rows))
        expected_gain_loss = {
            "gain": Decimal("498.77"),
            "wash-loss": Decimal("-1.50"),
            "plain-loss": Decimal("-50.50"),
        }
        for form_row in report.rows:
            assert form_row.gain_loss == expected_gain_loss[form_row.disposal_id], form_row.disposal_id

    # -----------------------------------------------------------------------
    # Sub-cent inputs: the actual defect. Ground truth is GainRow.reportable_gain_loss, computed
    # by app.tax.gains from the raw Disposal, independently of anything form8949.py does.
    # -----------------------------------------------------------------------

    def _account(self) -> Account:
        return Account(
            account_id="rh-taxable",
            broker=Broker.ROBINHOOD,
            label="RH Taxable",
            tax_treatment=TaxTreatment.TAXABLE,
        )

    def _build(self, disposal: Disposal) -> tuple[GainRow, Form8949Row]:
        account = self._account()
        gains = realized_gains(
            LotLedger(disposals=[disposal]),
            accounts={account.account_id: account},
            start=dt.date(2020, 1, 1),
            end=dt.date(2030, 1, 1),
        )
        form = build_form8949(gains)
        assert len(gains.rows) == 1
        assert len(form.rows) == 1
        return gains.rows[0], form.rows[0]

    def test_fractional_shares_and_sub_cent_fees_do_not_double_round(self) -> None:
        """The proven reproduction: 8 shares bought at 0.625, sold at 1.2505, fees 0.006.

        Rounding proceeds (1.2505*8 = 10.004 -> 10.00) and fees (0.006 -> 0.01) separately and
        then subtracting gives 9.99 -- one cent short of rounding the true net-of-fees amount
        (10.004 - 0.006 = 9.998) once, which is 10.00. That missing cent used to show up in (h):
        GainRow.reportable_gain_loss was 5.00 while Form8949Row.gain_loss was 4.99.
        """
        disposal = Disposal(
            disposal_id="disp-1",
            lot_id="lot-1",
            instrument_id="instr-x",
            account_id="rh-taxable",
            symbol="X",
            sell_txn_id="sell-1",
            acquired_date=dt.date(2024, 1, 1),
            holding_start=dt.date(2024, 1, 1),
            disposed_date=dt.date(2025, 6, 1),
            quantity=Decimal(8),
            proceeds=Decimal("1.2505") * Decimal(8),
            cost_basis=Decimal("0.625") * Decimal(8),
            fees=Decimal("0.006"),
        )
        gain_row, form_row = self._build(disposal)

        assert gain_row.reportable_gain_loss == Decimal("5.00")
        assert form_row.proceeds == Decimal("10.00")
        assert form_row.gain_loss == Decimal("5.00")
        assert form_row.gain_loss == gain_row.reportable_gain_loss

    def test_holds_across_several_sub_cent_price_and_fee_combinations(self) -> None:
        cases = [
            # (quantity, price, per_share_cost, fees)
            (Decimal(8), Decimal("1.2505"), Decimal("0.625"), Decimal("0.006")),
            (Decimal(3), Decimal("0.333333"), Decimal("0.1"), Decimal("0.001")),
            (Decimal("1.4832"), Decimal("70.9500000000"), Decimal("50"), Decimal("0.0049")),
            (Decimal(7), Decimal("9.995"), Decimal("10.005"), Decimal("0.0051")),
        ]
        for quantity, price, per_share_cost, fees in cases:
            disposal = Disposal(
                disposal_id=f"disp-{price}-{fees}",
                lot_id="lot-1",
                instrument_id="instr-x",
                account_id="rh-taxable",
                symbol="X",
                sell_txn_id="sell-1",
                acquired_date=dt.date(2024, 1, 1),
                holding_start=dt.date(2024, 1, 1),
                disposed_date=dt.date(2025, 6, 1),
                quantity=quantity,
                proceeds=price * quantity,
                cost_basis=per_share_cost * quantity,
                fees=fees,
            )
            gain_row, form_row = self._build(disposal)
            assert form_row.gain_loss == gain_row.reportable_gain_loss, (quantity, price, fees)


# ---------------------------------------------------------------------------
# Description formatting -- no misleading trailing zeros
# ---------------------------------------------------------------------------


class TestDescriptionFormatting:
    def test_whole_share_count_has_no_trailing_zeros(self) -> None:
        row = make_row(symbol="SOXL", quantity=Decimal(50))
        report = build_form8949(make_report([row]))
        assert report.rows[0].description == "50 SOXL"

    def test_fractional_share_count_keeps_significant_digits_only(self) -> None:
        row = make_row(symbol="VOO", quantity=Decimal("1.750"))
        report = build_form8949(make_report([row]))
        assert report.rows[0].description == "1.75 VOO"


# ---------------------------------------------------------------------------
# Column (b) is the original acquisition date, not the tolled holding start
# ---------------------------------------------------------------------------


class TestDateAcquired:
    def test_uses_original_acquisition_not_tolled_holding_start(self) -> None:
        row = make_row(
            acquired_date=dt.date(2025, 1, 1),
            holding_start=dt.date(2023, 1, 1),
            term=HoldingTerm.LONG,
        )
        report = build_form8949(make_report([row]))
        assert report.rows[0].date_acquired == dt.date(2025, 1, 1)


# ---------------------------------------------------------------------------
# Subtotals reconcile to the sum of rows
# ---------------------------------------------------------------------------


class TestSubtotalsReconcile:
    def test_subtotals_equal_sum_of_rows_per_term(self) -> None:
        rows = [
            make_row(
                disposal_id="s1",
                term=HoldingTerm.SHORT,
                proceeds=Decimal("500.00"),
                fees=Decimal("1.00"),
                cost_basis=Decimal("400.00"),
            ),
            make_row(
                disposal_id="s2",
                term=HoldingTerm.SHORT,
                proceeds=Decimal("300.00"),
                fees=Decimal("0.50"),
                cost_basis=Decimal("450.00"),
                disallowed_loss=Decimal("150.50"),
                is_wash_sale=True,
            ),
            make_row(
                disposal_id="l1",
                term=HoldingTerm.LONG,
                proceeds=Decimal("2000.00"),
                fees=Decimal("2.00"),
                cost_basis=Decimal("1200.00"),
            ),
        ]
        report = build_form8949(make_report(rows))

        short_form_rows = [r for r in report.rows if r.box in (Form8949Box.A, Form8949Box.B, Form8949Box.C)]
        long_form_rows = [r for r in report.rows if r.box in (Form8949Box.D, Form8949Box.E, Form8949Box.F)]

        assert report.short_term_total_proceeds == sum(
            (r.proceeds for r in short_form_rows), Decimal(0)
        )
        assert report.short_term_total_basis == sum(
            (r.cost_basis for r in short_form_rows), Decimal(0)
        )
        assert report.short_term_total_adjustment == sum(
            (r.adjustment_amount for r in short_form_rows), Decimal(0)
        )
        assert report.short_term_total_gain == sum(
            (r.gain_loss for r in short_form_rows), Decimal(0)
        )
        assert report.long_term_total_proceeds == sum(
            (r.proceeds for r in long_form_rows), Decimal(0)
        )
        assert report.long_term_total_basis == sum(
            (r.cost_basis for r in long_form_rows), Decimal(0)
        )
        assert report.long_term_total_gain == sum(
            (r.gain_loss for r in long_form_rows), Decimal(0)
        )


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------


class TestToCsv:
    def test_round_trips_row_count(self) -> None:
        rows = [
            make_row(disposal_id="a", term=HoldingTerm.SHORT),
            make_row(disposal_id="b", term=HoldingTerm.LONG),
            make_row(disposal_id="c", term=HoldingTerm.LONG),
        ]
        report = build_form8949(make_report(rows))
        text = to_csv(report)
        parsed = list(csv.reader(io.StringIO(text)))
        assert len(parsed) == len(report.rows) + 1  # header + one line per row

    def test_header_is_stable(self) -> None:
        report = build_form8949(make_report([make_row()]))
        text = to_csv(report)
        header_line = text.splitlines()[0]
        assert header_line == (
            "Box,Description,Date Acquired,Date Sold,Proceeds,Cost Basis,"
            "Adjustment Code,Adjustment Amount,Gain or Loss,Disposal ID"
        )

    def test_empty_report_has_header_only(self) -> None:
        report = build_form8949(make_report([]))
        text = to_csv(report)
        assert text.splitlines() == [
            "Box,Description,Date Acquired,Date Sold,Proceeds,Cost Basis,"
            "Adjustment Code,Adjustment Amount,Gain or Loss,Disposal ID"
        ]

    def test_wash_sale_row_serialises_code_and_amount(self) -> None:
        row = make_row(
            disposal_id="wash-1",
            proceeds=Decimal("500.00"),
            cost_basis=Decimal("700.00"),
            disallowed_loss=Decimal("200.00"),
            is_wash_sale=True,
        )
        report = build_form8949(make_report([row]))
        text = to_csv(report)
        rows = list(csv.DictReader(io.StringIO(text)))
        assert rows[0]["Adjustment Code"] == "W"
        assert rows[0]["Adjustment Amount"] == "200.00"
        assert rows[0]["Disposal ID"] == "wash-1"


# ---------------------------------------------------------------------------
# CSV formula injection (A3): a cell starting with =, +, -, @, tab, CR or LF is evaluated as a
# formula by Excel/LibreOffice/Google Sheets rather than displayed literally, and docs/ tells the
# user to open this exact CSV in tax software or Excel. Column (a)'s current quantity-then-symbol
# field order happens to make this unreachable today, but nothing enforces that order -- these tests
# pin the property at the actual output boundary (to_csv), independent of which column ends up
# holding broker-supplied text, so a future reorder or a new column fails the suite instead of
# silently reopening the hole.
# ---------------------------------------------------------------------------


class TestCsvFormulaInjection:
    #: Payloads shaped like real formula-injection attempts: a DDE shell-out, a bare arithmetic
    #: expression Excel auto-evaluates without a leading '=', an '@'-triggered function call, and the
    #: three whitespace triggers. None of these should ever survive into a CSV cell unneutralised.
    _PAYLOADS = (
        "=cmd|'/C calc'!A1",
        "+1+1",
        "-2+3",
        "@SUM(A1:A9)",
        "\tSOXL",
        "\rSOXL",
        "\nSOXL",
    )

    @pytest.mark.parametrize("payload", _PAYLOADS)
    def test_a_malicious_disposal_id_is_neutralised_in_every_cell(self, payload: str) -> None:
        """``Disposal ID`` is the *last* column -- nothing about column (a)'s field order protects
        it. If sanitisation were only applied to column (a), this would fail."""
        row = make_row(disposal_id=payload)
        report = build_form8949(make_report([row]))
        text = to_csv(report)
        parsed = list(csv.reader(io.StringIO(text)))
        disposal_cell = parsed[1][-1]
        assert not disposal_cell.startswith(_FORMULA_TRIGGER_CHARS)
        # Neutralised via the documented mechanism (leading single quote), not merely truncated or
        # otherwise mangled -- the original payload must still be recoverable.
        assert disposal_cell == "'" + payload

    def test_no_cell_in_the_exported_csv_begins_with_a_formula_trigger_character(self) -> None:
        """The regression pin, phrased as closely as possible to the literal property that must
        hold: scan every cell of every row, across a report that plants a malicious payload in more
        than one column *and* carries a legitimate negative dollar figure, and confirm every cell
        starting with a trigger character is a safe plain number (never anything a spreadsheet would
        evaluate). This does not depend on which column the payload was planted in, so it survives a
        future field reorder -- and it does not depend on treating every negative number as unsafe,
        which is the mistake that would turn this fix into a data-corruption bug.
        """
        rows = [
            make_row(disposal_id="=cmd|'/C calc'!A1", symbol="SOXL"),
            make_row(disposal_id="disp-2", symbol="VOO"),
            make_row(
                disposal_id="disp-3",
                proceeds=Decimal("100.00"),
                cost_basis=Decimal("500.00"),
            ),  # produces a negative Gain or Loss cell, which must stay a plain unprefixed number
        ]
        report = build_form8949(make_report(rows))
        text = to_csv(report)
        parsed = list(csv.reader(io.StringIO(text)))
        saw_a_plain_negative_number = False
        for line in parsed:
            for cell in line:
                if not cell or cell[0] not in _FORMULA_TRIGGER_CHARS:
                    continue
                # A cell is allowed to start with a trigger character only when it is, in full, a
                # safe numeric literal -- anything else must have been quote-prefixed by the sanitizer.
                assert _PLAIN_NUMBER_RE.fullmatch(cell), cell
                saw_a_plain_negative_number = True
        assert saw_a_plain_negative_number, "the negative Gain or Loss cell should have been exercised"

    def test_negative_money_amounts_still_round_trip_as_numbers(self) -> None:
        """The other half of the fix: a legitimate negative dollar figure must not be neutralised,
        or a spreadsheet would import it as text a SUM() cannot see."""
        row = make_row(proceeds=Decimal("100.00"), cost_basis=Decimal("500.00"))
        report = build_form8949(make_report([row]))
        text = to_csv(report)
        rows = list(csv.DictReader(io.StringIO(text)))
        gain_loss = rows[0]["Gain or Loss"]

        assert gain_loss == "-400.00"  # not "'-400.00"
        assert not gain_loss.startswith("'")
        # Round-trips as a number a spreadsheet will sum, not as text.
        assert Decimal(gain_loss) == Decimal("-400.00")

    def test_a_plain_negative_number_cell_is_left_untouched_by_the_sanitizer(self) -> None:
        assert _sanitize_cell("-1234.56") == "-1234.56"
        assert _sanitize_cell("-0.01") == "-0.01"

    @pytest.mark.parametrize("payload", _PAYLOADS)
    def test_the_sanitizer_prefixes_a_single_quote_on_a_non_numeric_trigger_cell(
        self, payload: str
    ) -> None:
        assert _sanitize_cell(payload) == "'" + payload

    def test_the_sanitizer_leaves_untriggered_text_alone(self) -> None:
        assert _sanitize_cell("SOXL") == "SOXL"
        assert _sanitize_cell("") == ""
        assert _sanitize_cell("50 SOXL") == "50 SOXL"

# ---------------------------------------------------------------------------
# The two presentations of one disposal must agree -- per row and in total
#
# Form 8949 and `GainsReport` describe the same disposals on the same page, and they disagreed.
# Form 8949 built each row as round(proceeds - fees) - round(basis) + round(adjustment); `GainsReport`
# rounded the combination once. Four roundings against one, so on a real ledger a number of rows
# differed by a cent and the short-term subtotal came out cents apart -- two totals of the same
# disposals, a screen apart.
#
# The fix went *towards* Form 8949's arithmetic rather than away from it, because column (h) is
# defined as (d) - (e) + (g). A row whose stated gain is not the difference of its own stated
# proceeds, basis and adjustment is a defective form whatever the raw figures said. Gain is now
# derived from the rounded components on both sides.
#
# These use raw sub-cent disposals driven through `realized_gains`, for the reason the class above
# gives: at 2-decimal inputs the double rounding is invisible.
# ---------------------------------------------------------------------------


class TestFormAndGainsAgree:
    def _account(self) -> Account:
        return Account(
            account_id="rh-taxable",
            broker=Broker.ROBINHOOD,
            label="RH Taxable",
            tax_treatment=TaxTreatment.TAXABLE,
        )

    def _disposal(
        self,
        index: int,
        *,
        proceeds: Decimal,
        cost_basis: Decimal,
        fees: Decimal,
        disallowed: Decimal = Decimal(0),
    ) -> Disposal:
        return Disposal(
            disposal_id=f"agree-{index}",
            lot_id=f"lot-{index}",
            instrument_id="instr-x",
            account_id="rh-taxable",
            symbol="X",
            sell_txn_id=f"sell-{index}",
            acquired_date=dt.date(2024, 1, 1),
            holding_start=dt.date(2024, 1, 1),
            disposed_date=dt.date(2025, 6, 1),
            quantity=Decimal(7),
            proceeds=proceeds,
            cost_basis=cost_basis,
            fees=fees,
            disallowed_loss=disallowed,
        )

    def _build(self, disposals: list[Disposal]) -> tuple[GainsReport, Form8949Report]:
        account = self._account()
        gains = realized_gains(
            LotLedger(disposals=disposals),
            accounts={account.account_id: account},
            start=dt.date(2020, 1, 1),
            end=dt.date(2030, 1, 1),
        )
        return gains, build_form8949(gains)

    def _spread(self) -> list[Disposal]:
        """A spread of sub-cent thirds and sevenths, gains and losses, some with a disallowance --
        the shapes where four independent roundings drift from one."""
        out: list[Disposal] = []
        for i in range(1, 13):
            proceeds = Decimal(f"10.00{i}") * Decimal(7) / Decimal(3)
            cost_basis = Decimal(f"9.00{i}") * Decimal(7) / Decimal(3)
            if i % 3 == 0:  # make it a loss, and disallow part of it
                proceeds, cost_basis = cost_basis, proceeds
                out.append(
                    self._disposal(
                        i,
                        proceeds=proceeds,
                        cost_basis=cost_basis,
                        fees=Decimal("0.00") + Decimal(i) / Decimal(300),
                        disallowed=Decimal("0.5") + Decimal(i) / Decimal(700),
                    )
                )
            else:
                out.append(
                    self._disposal(
                        i,
                        proceeds=proceeds,
                        cost_basis=cost_basis,
                        fees=Decimal(i) / Decimal(300),
                    )
                )
        return out

    def test_every_form_row_satisfies_its_own_column_arithmetic(self) -> None:
        """(d) - (e) + (g) = (h). The form's definition, not a house convention."""
        _gains, form = self._build(self._spread())
        assert form.rows
        for row in form.rows:
            assert row.proceeds - row.cost_basis + row.adjustment_amount == row.gain_loss

    def test_every_gain_row_satisfies_its_own_arithmetic(self) -> None:
        """proceeds - fees - basis = gain_loss, in the figures actually published."""
        gains, _form = self._build(self._spread())
        assert gains.rows
        for row in gains.rows:
            assert row.proceeds - row.fees - row.cost_basis == row.gain_loss

    def test_form_row_gain_equals_the_gain_row_it_came_from(self) -> None:
        gains, form = self._build(self._spread())
        for form_row, gain_row in zip(form.rows, gains.rows, strict=True):
            assert form_row.gain_loss == gain_row.reportable_gain_loss

    def test_subtotals_agree_to_the_cent(self) -> None:
        """The failure that was visible to a user: two totals of the same disposals, cents apart."""
        gains, form = self._build(self._spread())
        assert form.short_term_total_gain == gains.short_term_gain
        assert form.long_term_total_gain == gains.long_term_gain

    def test_a_disallowance_is_never_added_to_a_row_that_reports_a_gain(self) -> None:
        """`apply_wash_sales` returns early on `gain_loss >= 0`, so a row carrying a disallowance
        must be a loss. A row asserting both is the contradiction that put Form 8949's subtotal
        above the net-gain tile before `_sync_disposals` was corrected."""
        gains, _form = self._build(self._spread())
        for row in gains.rows:
            if row.disallowed_loss != 0:
                assert row.gain_loss < 0, f"{row.disposal_id} reports a gain and a disallowance"


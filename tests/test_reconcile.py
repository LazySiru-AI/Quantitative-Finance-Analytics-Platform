"""1099-B reconciliation.

``build_lots`` / ``apply_wash_sales`` / ``realized_gains`` are being implemented elsewhere in this
phase and currently raise ``NotImplementedError``, so every :class:`~app.tax.models.GainsReport` and
:class:`~app.tax.models.GainRow` here is constructed by hand rather than produced by the pipeline.
That is deliberate: this module only needs to know the *shape* of a gains report, not how one is
built.

Assertions use exact ``Decimal`` equality throughout -- a reconciliation test using ``pytest.approx``
would defeat the entire point of the module it is testing.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.tax.models import GainRow, GainsReport, HoldingTerm, ReconcileStatus
from app.tax.reconcile import Form1099BLine, Form1099BParseError, parse_1099b_csv, reconcile


def make_gain_row(
    *,
    disposal_id: str = "d1",
    symbol: str = "SOXL",
    account_id: str = "rh-taxable",
    term: HoldingTerm = HoldingTerm.SHORT,
    proceeds: str = "1000.00",
    cost_basis: str = "900.00",
    fees: str = "0",
    disallowed_loss: str = "0",
    reportable_gain_loss: str | None = None,
    basis_uncertain: bool = False,
) -> GainRow:
    """Build a GainRow with sensible defaults, overriding only what a test cares about.

    ``gain_loss`` and ``reportable_gain_loss`` are not derived automatically -- GainRow is a plain
    frozen model, unlike ``Disposal`` which computes them as properties -- so callers get a gain/loss
    figure consistent with proceeds/basis/fees unless they override it.
    """
    proceeds_d = Decimal(proceeds)
    cost_basis_d = Decimal(cost_basis)
    fees_d = Decimal(fees)
    disallowed_d = Decimal(disallowed_loss)
    gain_loss = proceeds_d - fees_d - cost_basis_d
    reportable = (
        Decimal(reportable_gain_loss) if reportable_gain_loss is not None else gain_loss + disallowed_d
    )
    return GainRow(
        disposal_id=disposal_id,
        instrument_id=f"instr-{symbol}",
        symbol=symbol,
        account_id=account_id,
        account_label=account_id,
        quantity=Decimal(10),
        lot_id=f"lot-{disposal_id}",
        lot_method="fifo",
        acquired_date=dt.date(2025, 1, 5),
        holding_start=dt.date(2025, 1, 5),
        disposed_date=dt.date(2026, 3, 1),
        term=term,
        proceeds=proceeds_d,
        cost_basis=cost_basis_d,
        fees=fees_d,
        gain_loss=gain_loss,
        disallowed_loss=disallowed_d,
        permanently_disallowed=False,
        reportable_gain_loss=reportable,
        is_wash_sale=disallowed_d != 0,
        basis_uncertain=basis_uncertain,
    )


def make_gains_report(rows: list[GainRow]) -> GainsReport:
    return GainsReport(start=dt.date(2026, 1, 1), end=dt.date(2026, 12, 31), rows=tuple(rows))


def make_form_line(
    *,
    symbol: str = "SOXL",
    account_id: str = "rh-taxable",
    term: HoldingTerm = HoldingTerm.SHORT,
    proceeds: str = "1000.00",
    cost_basis: str = "900.00",
    wash_disallowed: str = "0",
) -> Form1099BLine:
    return Form1099BLine(
        symbol=symbol,
        account_id=account_id,
        term=term,
        proceeds=Decimal(proceeds),
        cost_basis=Decimal(cost_basis),
        wash_disallowed=Decimal(wash_disallowed),
    )


# ---------------------------------------------------------------------------
# reconcile()
# ---------------------------------------------------------------------------


def test_clean_reconciliation_is_matched() -> None:
    gains = make_gains_report([make_gain_row(proceeds="1000.00", cost_basis="900.00")])
    form = [make_form_line(proceeds="1000.00", cost_basis="900.00")]

    report = reconcile(gains, form)

    assert report.is_clean
    assert report.matched_count == 1
    assert report.differing_count == 0
    assert len(report.lines) == 1
    line = report.lines[0]
    assert line.status is ReconcileStatus.MATCHED
    assert line.engine_gain == Decimal("100.00")
    assert line.form_gain == Decimal("100.00")
    assert line.gain_delta == Decimal("0.00")
    assert line.disposal_ids == ("d1",)
    assert report.total_gain_delta == Decimal("0.00")


def test_proceeds_difference_produces_amount_differs_with_signed_delta() -> None:
    gains = make_gains_report([make_gain_row(proceeds="1000.00", cost_basis="900.00")])
    form = [make_form_line(proceeds="950.00", cost_basis="900.00")]

    report = reconcile(gains, form)

    assert not report.is_clean
    assert report.matched_count == 0
    assert report.differing_count == 1
    line = report.lines[0]
    assert line.status is ReconcileStatus.AMOUNT_DIFFERS
    assert line.proceeds_delta == Decimal("50.00")
    assert line.basis_delta == Decimal("0.00")
    # engine gain 100.00, form gain 950-900=50.00
    assert line.gain_delta == Decimal("50.00")
    assert report.total_gain_delta == Decimal("50.00")


def test_basis_difference_produces_amount_differs_with_signed_delta() -> None:
    gains = make_gains_report([make_gain_row(proceeds="1000.00", cost_basis="900.00")])
    form = [make_form_line(proceeds="1000.00", cost_basis="850.00")]

    report = reconcile(gains, form)

    assert not report.is_clean
    line = report.lines[0]
    assert line.status is ReconcileStatus.AMOUNT_DIFFERS
    assert line.proceeds_delta == Decimal("0.00")
    assert line.basis_delta == Decimal("50.00")
    # engine gain 1000-900=100.00, form gain 1000-850=150.00
    assert line.gain_delta == Decimal("-50.00")
    assert report.total_gain_delta == Decimal("-50.00")


def test_missing_from_engine_detected() -> None:
    """The 1099-B reports a symbol/account/term the engine never computed a disposal for."""
    gains = make_gains_report([])
    form = [make_form_line(symbol="MU", proceeds="500.00", cost_basis="400.00")]

    report = reconcile(gains, form)

    assert not report.is_clean
    assert report.matched_count == 0
    assert report.differing_count == 1
    line = report.lines[0]
    assert line.symbol == "MU"
    assert line.status is ReconcileStatus.MISSING_FROM_ENGINE
    assert line.engine_proceeds == Decimal("0")
    assert line.engine_basis == Decimal("0")
    assert line.form_proceeds == Decimal("500.00")
    assert line.form_basis == Decimal("400.00")
    assert line.disposal_ids == ()
    assert line.note is not None


def test_missing_from_1099b_detected() -> None:
    """The engine computed a disposal the 1099-B does not report."""
    gains = make_gains_report(
        [make_gain_row(disposal_id="d9", symbol="TSLL", proceeds="200.00", cost_basis="150.00")]
    )
    form: list[Form1099BLine] = []

    report = reconcile(gains, form)

    assert not report.is_clean
    line = report.lines[0]
    assert line.symbol == "TSLL"
    assert line.status is ReconcileStatus.MISSING_FROM_1099B
    assert line.form_proceeds == Decimal("0")
    assert line.form_basis == Decimal("0")
    assert line.engine_proceeds == Decimal("200.00")
    assert line.disposal_ids == ("d9",)
    assert line.note is not None


def test_short_and_long_term_same_symbol_do_not_merge() -> None:
    gains = make_gains_report(
        [
            make_gain_row(
                disposal_id="short-1",
                symbol="NVDA",
                term=HoldingTerm.SHORT,
                proceeds="500.00",
                cost_basis="450.00",
            ),
            make_gain_row(
                disposal_id="long-1",
                symbol="NVDA",
                term=HoldingTerm.LONG,
                proceeds="700.00",
                cost_basis="600.00",
            ),
        ]
    )
    form = [
        make_form_line(symbol="NVDA", term=HoldingTerm.SHORT, proceeds="500.00", cost_basis="450.00"),
        make_form_line(symbol="NVDA", term=HoldingTerm.LONG, proceeds="700.00", cost_basis="600.00"),
    ]

    report = reconcile(gains, form)

    assert report.is_clean
    assert len(report.lines) == 2
    short_line = next(line for line in report.lines if line.term is HoldingTerm.SHORT)
    long_line = next(line for line in report.lines if line.term is HoldingTerm.LONG)
    assert short_line.disposal_ids == ("short-1",)
    assert long_line.disposal_ids == ("long-1",)
    assert short_line.engine_gain == Decimal("50.00")
    assert long_line.engine_gain == Decimal("100.00")


def test_total_gain_delta_is_sum_of_line_deltas() -> None:
    gains = make_gains_report(
        [
            make_gain_row(disposal_id="a", symbol="AAA", proceeds="1000.00", cost_basis="900.00"),
            make_gain_row(disposal_id="b", symbol="BBB", proceeds="500.00", cost_basis="500.00"),
        ]
    )
    form = [
        make_form_line(symbol="AAA", proceeds="950.00", cost_basis="900.00"),  # gain delta +50
        make_form_line(symbol="BBB", proceeds="500.00", cost_basis="480.00"),  # gain delta -20
        make_form_line(symbol="CCC", proceeds="100.00", cost_basis="80.00"),  # missing_from_engine
    ]

    report = reconcile(gains, form)

    expected = sum((line.gain_delta for line in report.lines), Decimal(0))
    assert report.total_gain_delta == expected
    assert report.total_gain_delta == Decimal("50.00") + Decimal("-20.00") + Decimal("-20.00")


def test_basis_difference_matching_wash_disallowed_gets_explanatory_note() -> None:
    """Engine basis 900 vs form basis 860, with the form reporting a $40 wash-sale disallowance --
    the difference is exactly the disallowed amount, which is the fingerprint of the engine not
    having applied that wash sale to this lot.
    """
    gains = make_gains_report([make_gain_row(proceeds="1000.00", cost_basis="900.00")])
    form = [make_form_line(proceeds="1000.00", cost_basis="860.00", wash_disallowed="40.00")]

    report = reconcile(gains, form)

    line = report.lines[0]
    assert line.status is ReconcileStatus.AMOUNT_DIFFERS
    assert line.basis_delta == Decimal("40.00")
    assert line.note is not None
    assert "wash" in line.note.lower()
    assert "40" in line.note


def test_unrelated_amount_difference_gets_no_overclaiming_note() -> None:
    """When the delta does not match any known cause, no note is fabricated."""
    gains = make_gains_report([make_gain_row(proceeds="1000.00", cost_basis="900.00")])
    form = [make_form_line(proceeds="1000.00", cost_basis="875.00", wash_disallowed="0")]

    report = reconcile(gains, form)

    line = report.lines[0]
    assert line.status is ReconcileStatus.AMOUNT_DIFFERS
    assert line.note is None


# ---------------------------------------------------------------------------
# parse_1099b_csv()
# ---------------------------------------------------------------------------


def test_parse_handles_currency_thousands_and_parens() -> None:
    text = (
        "Symbol,Account,Term,Proceeds,Cost Basis,Wash Sale Disallowed\n"
        "SOXL,rh-taxable,Short,\"$4,851.90\",\"$4,000.00\",$0.00\n"
        "NVDA,rh-taxable,Long,\"($5,250.00)\",\"($5,100.00)\",$150.00\n"
    )

    lines = parse_1099b_csv(text)

    assert len(lines) == 2
    assert lines[0].symbol == "SOXL"
    assert lines[0].term is HoldingTerm.SHORT
    assert lines[0].proceeds == Decimal("4851.90")
    assert lines[0].cost_basis == Decimal("4000.00")
    assert lines[0].wash_disallowed == Decimal("0.00")

    assert lines[1].symbol == "NVDA"
    assert lines[1].term is HoldingTerm.LONG
    assert lines[1].proceeds == Decimal("-5250.00")
    assert lines[1].cost_basis == Decimal("-5100.00")
    assert lines[1].wash_disallowed == Decimal("150.00")


def test_parse_is_tolerant_of_header_case_and_whitespace() -> None:
    text = "  symbol , ACCOUNT , term ,proceeds, cost basis\nSOXL,rh-taxable,short,100.00,90.00\n"

    lines = parse_1099b_csv(text)

    assert len(lines) == 1
    assert lines[0].symbol == "SOXL"
    assert lines[0].wash_disallowed == Decimal(0)


def test_parse_raises_on_missing_required_column() -> None:
    text = "Symbol,Account,Term,Proceeds\nSOXL,rh-taxable,short,100.00\n"

    with pytest.raises(Form1099BParseError):
        parse_1099b_csv(text)


def test_parse_raises_on_unknown_column() -> None:
    text = "Symbol,Account,Term,Proceeds,Cost Basis,Some Unknown Column\nSOXL,rh-taxable,short,100.00,90.00,x\n"

    with pytest.raises(Form1099BParseError):
        parse_1099b_csv(text)


def test_parse_raises_on_empty_file() -> None:
    with pytest.raises(Form1099BParseError):
        parse_1099b_csv("")


def test_parse_raises_on_unrecognised_term() -> None:
    text = "Symbol,Account,Term,Proceeds,Cost Basis\nSOXL,rh-taxable,medium,100.00,90.00\n"

    with pytest.raises(Form1099BParseError):
        parse_1099b_csv(text)


def test_parse_skips_blank_lines() -> None:
    text = "Symbol,Account,Term,Proceeds,Cost Basis\nSOXL,rh-taxable,short,100.00,90.00\n\n\n"

    lines = parse_1099b_csv(text)

    assert len(lines) == 1

"""IRS Form 8949, column for column, built from a :class:`~app.tax.models.GainsReport`.

**Column (d), proceeds, is NET of selling costs, not gross.** ``GainRow.proceeds`` is gross (the
contract in ``app.tax.models`` says so explicitly) and selling fees are carried in their own
``GainRow.fees`` field, but Form 8949 itself has no separate fee column -- a broker's 1099-B already
nets commissions out of box 1d, and this module matches that convention:

    (d) = GainRow.proceeds - GainRow.fees

That convention is what makes the column (h) identity below hold exactly, and it is why fees do not
also need to be subtracted a second time out of column (e). Do not swap this: (d) gross with fees
in a phantom column (f)/(g) slot would double-count nothing, but it would silently disagree with
every 1099-B a user pastes this against.

Column (h) is derived arithmetically from the already cent-quantized (d), (e) and (g) -- **not** by
independently rounding ``GainRow.reportable_gain_loss`` -- so the identity

    (h) = (d) - (e) + (g)

holds exactly for every row by construction, rather than merely up to a penny of independent
rounding error. Algebraically, with fees folded into (d):

    (d) - (e) + (g) = (proceeds - fees) - cost_basis + disallowed_loss
                     = gain_loss + disallowed_loss
                     = reportable_gain_loss

(``GainRow.disallowed_loss`` is zero whenever the disposal is not a loss, since §1091 only ever
disallows losses, so the last step holds on gain rows too.)
"""

from __future__ import annotations

import csv
import io
import re
from decimal import Decimal

from app.core.money import quantize_money
from app.tax.models import (
    Form8949Box,
    Form8949Report,
    Form8949Row,
    GainRow,
    GainsReport,
    HoldingTerm,
)

__all__ = ["build_form8949", "select_box", "to_csv"]

#: Column order for `to_csv`. Fixed so pasted output lines up run over run.
_CSV_HEADER = (
    "Box",
    "Description",
    "Date Acquired",
    "Date Sold",
    "Proceeds",
    "Cost Basis",
    "Adjustment Code",
    "Adjustment Amount",
    "Gain or Loss",
    "Disposal ID",
)

#: Characters that, as the *first* character of an unquoted CSV cell, make a spreadsheet program
#: (Excel, LibreOffice Calc, Google Sheets) evaluate the cell as a formula instead of displaying it
#: literally -- "CSV injection". ``=`` is the obvious trigger; ``+`` and ``-`` are less obvious but
#: just as real (type ``-2+3`` into an Excel cell and it auto-prepends ``=`` and evaluates to ``1``);
#: ``@`` triggers Lotus-1-2-3-style function syntax that Excel still honours; a leading tab, CR or LF
#: can shift what looks like inert text into a different cell or row once the file is opened. A
#: malicious formula in any of these can shell out via DDE (``=cmd|'/C calc'!A1``) or exfiltrate the
#: rest of the workbook to a URL -- this is a real code-execution primitive, not a cosmetic glitch.
#: ``Description`` (column (a)) is the column this module currently guards structurally by always
#: writing the quantity before the symbol (see `_description`), but that guarantee lives entirely in
#: field *order* and nothing enforces it -- reorder those two fields, or add a bare ``Symbol`` column,
#: and a broker-supplied symbol starting with one of these characters becomes live. Sanitising here,
#: at the actual output boundary, removes the dependency on field order entirely.
_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r", "\n")

#: A cell whose *entire* text is a signed decimal number, e.g. ``-1234.56`` or ``9.95``. Every ``-``
#: this module's money columns can produce comes from formatting a negative `Decimal` this exact way
#: (``str(quantize_money(...))``), and a spreadsheet's CSV importer recognises that shape as a numeric
#: literal on import -- it is stored as a *number*, never evaluated as a formula. Formula evaluation
#: only engages for text the importer cannot parse as a literal number, date or boolean. That is the
#: basis for exempting cells matching this pattern from the quote-prefix below: naively neutralising
#: every leading ``-`` would turn a legitimate ``"-1234.56"`` into the text ``"'-1234.56"``, which tax
#: software and Excel alike would import as a string rather than a number a column can be summed --
#: silently corrupting the one thing this report exists to get right. Deliberately narrow (a plain
#: optional sign, digits, at most one decimal point) rather than "whatever `Decimal()` accepts" --
#: this module never emits `"1E10"` or `"-Infinity"`, so there is no reason to special-case forms that
#: would only widen the exemption without a matching legitimate use.
_PLAIN_NUMBER_RE = re.compile(r"^[+-]?\d+(\.\d+)?$")


def _sanitize_cell(text: str) -> str:
    """Neutralise CSV formula injection on one cell, without mangling a legitimate negative number.

    A cell is rewritten only when it starts with a character in `_FORMULA_TRIGGER_CHARS` *and* does
    not parse as a plain number (`_PLAIN_NUMBER_RE`) -- see that pattern's docstring for why the
    numeric exemption is necessary rather than merely convenient. Neutralisation prefixes a single
    quote, the standard mitigation recognised by Excel, LibreOffice Calc and Google Sheets alike as
    "force this cell to text": it strips the character's special meaning on import without otherwise
    altering the content a person reads.

    Called on every cell `to_csv` writes, not only column (a) -- see `_FORMULA_TRIGGER_CHARS` for why
    the guarantee must not depend on which column ends up holding broker-supplied text.
    """
    if not text or text[0] not in _FORMULA_TRIGGER_CHARS:
        return text
    if _PLAIN_NUMBER_RE.match(text):
        return text
    return "'" + text


def select_box(row: GainRow, *, basis_reported: bool = True) -> Form8949Box:
    """Pick the Form 8949 box for one row: short/long term crossed with basis reporting.

    Equities acquired on or after 2011-01-01 are "covered securities" under §6045 -- the broker must
    report basis to the IRS -- and every acquisition in this dataset postdates that cutoff, so
    ``basis_reported=True`` (box A short-term / D long-term) is the normal outcome.

    ``basis_reported=False`` selects box B (short) / E (long): basis was *not* reported to the IRS
    for this lot, which in this dataset means the position arrived by an ACAT transfer the replay
    could not match to an acquisition (a :class:`~app.core.lots.WarningKind.UNMATCHED_TRANSFER_IN`
    warning) -- the receiving broker never got a basis figure to report in the first place.

    Box C (short) / F (long) -- a disposal not on any 1099-B at all -- has no caller in this dataset
    (every disposal here comes from a broker export) and is therefore not reachable through this
    two-state ``basis_reported`` flag. A hypothetical caller needing C/F would need a third state on
    this parameter; that is a real gap in the current signature, not an oversight in this
    implementation, and is called out in the accompanying test-writer's report.
    """
    if row.term is HoldingTerm.SHORT:
        return Form8949Box.A if basis_reported else Form8949Box.B
    return Form8949Box.D if basis_reported else Form8949Box.E


def _format_quantity(quantity: Decimal) -> str:
    """Column (a)'s share count, without misleading trailing zeros.

    ``50`` renders as ``"50"``, not ``"50.000"``; ``0.500`` renders as ``"0.5"``. Fixed-point
    formatting (``f``) is used rather than ``Decimal.normalize()`` because ``normalize()`` can switch
    a whole share count into exponential notation (``Decimal("50").normalize()`` is ``Decimal("5E+1")``),
    which is correct Decimal but unreadable on a tax form.
    """
    text = format(quantity, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _description(row: GainRow) -> str:
    """Column (a): quantity and symbol, e.g. ``"50 SOXL"``."""
    return f"{_format_quantity(row.quantity)} {row.symbol}"


def _to_form_row(row: GainRow) -> Form8949Row:
    box = select_box(row, basis_reported=not row.basis_uncertain)

    # This `quantize_money` is a no-op, not a second rounding: `app.tax.gains.realized_gains`
    # constructs `row.fees` as the residual that makes `row.proceeds - row.fees` already exactly
    # equal to the net-of-fees amount rounded once (see that function's comment on the GainRow it
    # builds). If `row.proceeds` and `row.fees` were instead each an independent rounding of the
    # raw disposal's gross proceeds and fees -- the previous bug -- their difference here could
    # disagree with rounding the true net once by a cent.
    proceeds = quantize_money(row.proceeds - row.fees)
    cost_basis = quantize_money(row.cost_basis)

    if row.is_wash_sale and row.disallowed_loss != 0:
        adjustment_code: str | None = "W"
        # Capped at the loss this row actually reports. §1091 defers the loss you had, not more,
        # and that holds exactly in the unrounded figures -- on a real ledger no wash-sale
        # event disallowed more than its own loss. The two are quantized independently though, so a
        # loss rounding down while its disallowance rounds up leaves them a cent apart, and column
        # (h) then came out at +$0.01 on a loss disallowed in full: a row saying "wash sale" in (g)
        # and "profit" in (h) at once. A couple of rows on a real ledger did this.
        #
        # The cap lives here rather than on `GainRow.disallowed_loss` because that field is the
        # economic figure, and `GainsReport.disallowed_loss_total` must keep reconciling to the cent
        # with the sum of the wash-sale events -- an invariant `test_canonical` pins, and the one
        # that caught the first attempt at this fix. What the form may report is a narrower question
        # than what happened.
        adjustment_amount = min(
            quantize_money(row.disallowed_loss), max(Decimal(0), cost_basis - proceeds)
        )
    else:
        adjustment_code = None
        adjustment_amount = Decimal(0)

    gain_loss = proceeds - cost_basis + adjustment_amount

    return Form8949Row(
        box=box,
        description=_description(row),
        date_acquired=row.acquired_date,
        date_sold=row.disposed_date,
        proceeds=proceeds,
        cost_basis=cost_basis,
        adjustment_code=adjustment_code,
        adjustment_amount=adjustment_amount,
        gain_loss=gain_loss,
        disposal_id=row.disposal_id,
    )


def build_form8949(gains: GainsReport) -> Form8949Report:
    """Build Form 8949 rows and per-term subtotals from a classified :class:`GainsReport`.

    One Form 8949 row per :class:`~app.tax.models.GainRow`, in the same order (``gains.rows`` is
    already sorted deterministically by ``(disposed_date, symbol, disposal_id)``). Subtotals are
    accumulated across all three boxes of a term (A+B+C for short, D+E+F for long) because that is
    what carries forward to Schedule D -- the box only affects which part of the form a row prints
    on, not which subtotal it feeds.
    """
    rows = tuple(_to_form_row(row) for row in gains.rows)

    short_proceeds = short_basis = short_adjustment = short_gain = Decimal(0)
    long_proceeds = long_basis = long_adjustment = long_gain = Decimal(0)

    for form_row, gain_row in zip(rows, gains.rows, strict=True):
        if gain_row.term is HoldingTerm.SHORT:
            short_proceeds += form_row.proceeds
            short_basis += form_row.cost_basis
            short_adjustment += form_row.adjustment_amount
            short_gain += form_row.gain_loss
        else:
            long_proceeds += form_row.proceeds
            long_basis += form_row.cost_basis
            long_adjustment += form_row.adjustment_amount
            long_gain += form_row.gain_loss

    return Form8949Report(
        rows=rows,
        short_term_total_proceeds=short_proceeds,
        short_term_total_basis=short_basis,
        short_term_total_adjustment=short_adjustment,
        short_term_total_gain=short_gain,
        long_term_total_proceeds=long_proceeds,
        long_term_total_basis=long_basis,
        long_term_total_adjustment=long_adjustment,
        long_term_total_gain=long_gain,
    )


def to_csv(report: Form8949Report) -> str:
    """Render a Form 8949 report as CSV, one line per row, suitable for pasting into tax software.

    Money is quantized to cents (rows built by :func:`build_form8949` already are, but this is the
    actual output boundary a user copies out of, so it is enforced again here rather than trusted).
    Column order is fixed (:data:`_CSV_HEADER`) so re-running against an unchanged report produces a
    byte-identical file.

    Every cell is passed through :func:`_sanitize_cell` before being written, which neutralises CSV
    formula injection (see that function and :data:`_FORMULA_TRIGGER_CHARS`) without altering a
    legitimate negative money amount. This module writes a CSV that ``docs/`` tells the user to paste
    or open directly in tax software or Excel, so a broker-supplied string reaching a cell unescaped
    is a real code-execution vector, not a formatting nicety.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_CSV_HEADER)
    for row in report.rows:
        writer.writerow(
            [
                _sanitize_cell(cell)
                for cell in (
                    row.box.value,
                    row.description,
                    row.date_acquired.isoformat(),
                    row.date_sold.isoformat(),
                    str(quantize_money(row.proceeds)),
                    str(quantize_money(row.cost_basis)),
                    row.adjustment_code or "",
                    str(quantize_money(row.adjustment_amount)),
                    str(quantize_money(row.gain_loss)),
                    row.disposal_id,
                )
            ]
        )
    return buffer.getvalue()

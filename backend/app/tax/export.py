"""CPA reconciliation exports: the Disposals and Wash sales tables, as CSV.

``app.tax.form8949.to_csv`` already exports the one table a filer types into tax software. This
module exports the other two the Tax page puts on screen, because the question a CPA asks next is
not "what goes on the form" but "show me how you got there": the per-lot disposal detail behind
each Form 8949 line, and the §1091 events that adjusted them.

Three rules hold for every writer here, and they are the reason this is a module rather than three
inline list comprehensions in the route:

* **Column order mirrors the on-screen table, left to right.** A reconciliation pack whose columns
  are ordered differently from the page they were exported from forces the reader to re-derive the
  mapping for every row. Audit-only columns that the page does not render (ids, the flags behind a
  ``?`` marker) are appended *after* the on-screen ones rather than interleaved, so the leading
  columns line up with the screen exactly.
* **Dates are ISO 8601 and money is a plain decimal** -- no currency symbol, no thousands
  separator, no locale. The file is opened in a spreadsheet and summed; a formatted string is not a
  number there.
* **Every cell goes through the same formula-injection guard the Form 8949 export uses.** These
  files carry broker-supplied text (account labels, symbols) into Excel exactly as that one does.

Deliberately *not* re-deriving anything. Each function takes the report objects the JSON routes
already return and renames their fields into columns. A second computation path to the same
figures is how an export starts disagreeing with the page it claims to mirror.
"""

from __future__ import annotations

import csv
import io

from app.core.money import quantize_money
from app.tax.form8949 import _sanitize_cell
from app.tax.models import GainsReport, WashSaleEvent

# `_sanitize_cell` is imported rather than reimplemented on purpose. It is private to
# `app.tax.form8949` only in the sense that nothing outside this package should call it; copying it
# here would give this application two CSV-injection guards that can drift apart, and the one that
# drifts is a code-execution vector in a spreadsheet, not a formatting nit. If a third exporter
# appears, lift it into `app.tax` proper rather than making a third copy.

__all__ = [
    "DISPOSALS_CSV_HEADER",
    "WASH_SALES_CSV_HEADER",
    "disposals_to_csv",
    "wash_sales_to_csv",
]

#: Column order for :func:`disposals_to_csv`. The first ten mirror the Disposals table in
#: ``frontend/src/pages/Tax.tsx`` left to right ("Sold, Symbol, Qty, Acquired, Lot, Term, Proceeds,
#: Cost basis, Gain/loss, Account"), with the page's single combined "Lot" cell (``lot_id`` + " · "
#: + method) split into its two underlying fields so each is sortable in a spreadsheet. The rest
#: are audit columns the page renders as a marker or not at all.
DISPOSALS_CSV_HEADER = (
    "Date Sold",
    "Symbol",
    "Quantity",
    "Date Acquired",
    "Lot ID",
    "Lot Method",
    "Term",
    "Proceeds",
    "Cost Basis",
    "Gain or Loss",
    "Account",
    # --- audit columns, past the on-screen ones -------------------------------------------------
    "Holding Start",
    "Fees",
    "Gain or Loss Before Disallowance",
    "Disallowed Loss",
    "Permanently Disallowed Loss",
    "Basis Uncertain",
    "Fees Unknown",
    "Account ID",
    "Disposal ID",
)

#: Column order for :func:`wash_sales_to_csv`. The first seven mirror the Wash sales table in
#: ``frontend/src/pages/Tax.tsx`` ("Date, Symbol, Accounts, Qty replaced / sold, Loss, Disallowed,
#: Treatment"), with that table's single "replaced / sold" cell split into its two quantities for
#: the same reason as above.
WASH_SALES_CSV_HEADER = (
    "Sale Date",
    "Symbol",
    "Accounts",
    "Quantity Replaced",
    "Quantity Sold",
    "Loss",
    "Disallowed",
    "Treatment",
    # --- audit columns, past the on-screen ones -------------------------------------------------
    "Sale Account ID",
    "Replacement Account IDs",
    "Basis Added To Lot ID",
    "Holding Period Tolled To",
    "Chained",
    "Event ID",
    "Disposal ID",
)

#: What the "Treatment" column says. The same two words the page's badges carry
#: (``tax.badge.permanent`` / ``tax.badge.deferred``), in English only: a CSV handed to a CPA is not
#: a localized surface, and a Korean-locale export would not reconcile against an English 1099-B.
_TREATMENT_PERMANENT = "Permanently disallowed"
_TREATMENT_DEFERRED = "Deferred"

#: Booleans as words, not ``True``/``False`` -- a spreadsheet reads "TRUE" as a boolean literal and
#: an empty string as blank, and neither is legible in a printed workpaper.
_YES = "yes"
_NO = "no"


def _write(header: tuple[str, ...], rows: list[list[str]]) -> str:
    """Render one header plus its rows, every cell sanitized, with ``\\n`` line endings.

    Fixed line terminator (rather than :mod:`csv`'s default ``\\r\\n``) so re-exporting an unchanged
    report produces a byte-identical file on every platform -- the same guarantee
    ``app.tax.form8949.to_csv`` makes, and the reason a diff of two exports is meaningful.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([_sanitize_cell(cell) for cell in row])
    return buffer.getvalue()


def disposals_to_csv(gains: GainsReport) -> str:
    """The Disposals table as CSV, one line per :class:`~app.tax.models.GainRow`.

    ``Gain or Loss`` is ``reportable_gain_loss`` -- the after-disallowance figure the page's
    "Gain/loss" column shows and the one that reaches Form 8949 -- not ``gain_loss``. The
    before-disallowance figure is carried too, in its own explicitly named audit column, because a
    reconciliation against a 1099-B needs both halves of that adjustment and reading either as "the"
    gain is exactly the ambiguity this pack exists to remove.

    A report with no rows yields the header alone: an empty year is a real answer, and a
    zero-byte file is not distinguishable from a failed download.
    """
    rows = [
        [
            row.disposed_date.isoformat(),
            row.symbol,
            str(row.quantity),
            row.acquired_date.isoformat(),
            row.lot_id,
            # `""` (not "none"/"-") where the replay found no lot to consume: the page prints its
            # own "no lot" wording there, but a CSV column that is sometimes a method token and
            # sometimes a sentence cannot be filtered on. Blank is the spreadsheet's own "absent".
            row.lot_method or "",
            row.term.value,
            str(quantize_money(row.proceeds)),
            str(quantize_money(row.cost_basis)),
            str(quantize_money(row.reportable_gain_loss)),
            row.account_label,
            row.holding_start.isoformat(),
            str(quantize_money(row.fees)),
            str(quantize_money(row.gain_loss)),
            str(quantize_money(row.disallowed_loss)),
            str(quantize_money(row.permanently_disallowed_loss)),
            _YES if row.basis_uncertain else _NO,
            _YES if row.fees_unknown else _NO,
            row.account_id,
            row.disposal_id,
        ]
        for row in gains.rows
    ]
    return _write(DISPOSALS_CSV_HEADER, rows)


def wash_sales_to_csv(events: tuple[WashSaleEvent, ...] | list[WashSaleEvent]) -> str:
    """The Wash sales table as CSV, one line per triggered :class:`~app.tax.models.WashSaleEvent`.

    ``Accounts`` is the sale account plus every replacement account, de-duplicated in that order --
    byte-for-byte the string the page's "Accounts" cell builds. The two are also carried separately
    in the audit columns, so "which account sold" survives a column the page renders as one blob.

    ``Treatment`` is one of two words, never a sum: an event is deferred (added to a replacement
    lot's basis) or permanently disallowed (Rev. Rul. 2008-5, replaced inside an IRA), and the two
    are not commensurable. A disposal replaced partly in each reaches this function as two events
    sharing a ``disposal_id`` -- two lines, one per treatment -- which is the shape a CPA needs and
    the reason this exporter never collapses them.
    """
    rows = [
        [
            event.sale_date.isoformat(),
            event.symbol,
            ", ".join(dict.fromkeys([event.sale_account_id, *event.replacement_account_ids])),
            str(event.quantity_replaced),
            str(event.quantity_sold),
            str(quantize_money(event.loss_amount)),
            str(quantize_money(event.disallowed_loss)),
            _TREATMENT_PERMANENT if event.permanently_disallowed else _TREATMENT_DEFERRED,
            event.sale_account_id,
            ", ".join(event.replacement_account_ids),
            event.basis_added_to_lot_id or "",
            event.holding_period_tolled_to.isoformat()
            if event.holding_period_tolled_to is not None
            else "",
            _YES if event.is_chained else _NO,
            event.event_id,
            event.disposal_id,
        ]
        for event in events
    ]
    return _write(WASH_SALES_CSV_HEADER, rows)

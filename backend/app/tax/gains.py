"""Capital-gains classification: short vs. long term, taxable accounts only.

This module turns a replayed :class:`~app.core.lots.LotLedger` into a
:class:`~app.tax.models.GainsReport`. It must run **after** :mod:`app.tax.washsale`, because the
wash-sale pass can toll a holding period backwards and that tolling can change the term. Classifying
off :attr:`~app.core.lots.Disposal.acquired_date` instead of the possibly-tolled
:attr:`~app.core.lots.Disposal.holding_start` produces a wrong tax rate that looks entirely
plausible -- see standing test case #10 in ``.claude/agents/tax-rule-verifier.md``.

Two behaviours must both hold for tax-advantaged accounts, and getting one right while missing the
other is the classic bug here: their disposals are **excluded** from the figures in this report, but
they are still walked by the wash-sale pass upstream, because a replacement purchase inside an IRA
permanently disallows a loss realised in a taxable account (Rev. Rul. 2008-5). This module only owns
the exclusion half; the scanning half lives in :mod:`app.tax.washsale`.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from decimal import Decimal

from app.core.lots import LotLedger, WarningKind
from app.core.models import Account
from app.core.money import quantize_money
from app.tax.models import GainRow, GainsReport, HoldingTerm

__all__ = ["classify_term", "realized_gains"]

#: Warning kinds that mean a disposal's basis could not be established from the replay. A row
#: touched by one of these overstates the gain and must be flagged rather than filed as-is.
#:
#: The two groups below are scoped differently, and the difference matters: over-scoping silently
#: mis-files a clean lot in Form 8949's basis-not-reported box, under-scoping silently trusts a
#: basis that was never established. Which applies is determined by *where* app.core.lots.build_ledger
#: raises each kind, not by a choice made here:
#:
#: - OVERSOLD and MISSING_BASIS are both raised inside the loop that turns one sale into its
#:   disposals, with ``LotWarning.txn_id`` set to that sale's own transaction id -- the same id
#:   every disposal that sale produces carries as ``Disposal.sell_txn_id``. So a warning of either
#:   kind can be matched to the exact sale it came from, and only that sale's disposals need the
#:   flag: a later, unrelated sale of a cleanly re-established lot in the same account and symbol
#:   must not inherit it.
#: - UNMATCHED_TRANSFER_IN is raised on the *receiving transfer* transaction, which opens a
#:   zero-basis lot but disposes of nothing -- it shares no ``txn_id`` with any future ``Disposal``
#:   at all, because that lot may not be sold until a later, separate sale (or several, split
#:   across sales). There is no finer identity to narrow to from a ``LotWarning`` alone, so this
#:   kind stays scoped to the whole (account, instrument) position: every disposal of that symbol
#:   in that account is flagged, which over-flags rather than risks missing a lot that really did
#:   arrive with no known basis.
_LOT_SCOPED_KINDS = frozenset({WarningKind.OVERSOLD, WarningKind.MISSING_BASIS})
_POSITION_SCOPED_KINDS = frozenset({WarningKind.UNMATCHED_TRANSFER_IN})
_BASIS_UNCERTAIN_KINDS = _LOT_SCOPED_KINDS | _POSITION_SCOPED_KINDS

#: Fees, not basis. Kept separate from `_BASIS_UNCERTAIN_KINDS`: a disposal can have a fully known
#: basis and still be missing its sale-side fee (or vice versa is not possible today, but the two
#: are independent facts and must not be conflated into one flag). Scoped to the sale transaction
#: exactly like the lot-scoped basis kinds above -- `WarningKind.FEES_UNKNOWN` is raised once per
#: `SELL` in `app.core.lots.build_lots`, keyed on that same `txn_id`.
_FEES_UNKNOWN_KINDS = frozenset({WarningKind.FEES_UNKNOWN})


def _add_one_year(day: dt.date) -> dt.date:
    """The calendar anniversary of ``day``, one year later.

    Rev. Rul. 66-7 fixes the convention this codifies: the anniversary of a given date is the same
    month and day one year on, and if that date does not exist in the following year -- the only
    case is a February 29 acquisition landing on a non-leap year -- the anniversary is the last day
    of February instead. ``date.replace`` already raises exactly on that one case, so the fallback
    only has to handle it, not detect it.
    """
    try:
        return day.replace(year=day.year + 1)
    except ValueError:
        # day is Feb 29 and day.year + 1 is not a leap year.
        return dt.date(day.year + 1, 2, 28)


def classify_term(holding_start: dt.date, disposed_date: dt.date) -> HoldingTerm:
    """Short- vs. long-term under IRC §1222, off the (possibly tolled) holding-period start.

    Long-term requires holding for **more than** one year. Publication 550 counts from the day
    *after* acquisition, but that detail cancels out arithmetically for a "more than one year" test:
    a sale on the calendar anniversary of ``holding_start`` is exactly one year held and is
    short-term; a sale the day after the anniversary is long-term. So the comparison is directly
    against the anniversary date, not against ``holding_start + 1`` day.

    Always pass :attr:`~app.core.lots.Disposal.holding_start`, never
    ``acquired_date``: a wash sale can toll the holding period backwards, and a short-term position
    tolled past its one-year mark becomes long-term on the eventual sale even though the literal
    purchase was under a year ago.
    """
    anniversary = _add_one_year(holding_start)
    if disposed_date <= anniversary:
        return HoldingTerm.SHORT
    return HoldingTerm.LONG


def realized_gains(
    ledger: LotLedger,
    *,
    accounts: Mapping[str, Account],
    start: dt.date,
    end: dt.date,
) -> GainsReport:
    """Classify and total every disposal in ``[start, end]``, taxable accounts only.

    Args:
        ledger: The replayed ledger, post wash-sale (i.e. ``ledger.disposals`` already carry any
            disallowance and tolling). This function does not call the wash-sale pass itself.
        accounts: ``account_id`` -> account, needed to test :attr:`Account.is_tax_advantaged`.
        start: Inclusive lower bound on ``disposed_date``.
        end: Inclusive upper bound on ``disposed_date``.

    Returns:
        A :class:`~app.tax.models.GainsReport` with rows sorted deterministically by
        ``(disposed_date, symbol, disposal_id)`` and totals that are the exact sum of the (cent
        -quantized) rows -- quantization happens once, per row, at this output boundary, and totals
        are then a plain sum of already-quantized figures so they reconcile to the cent by
        construction rather than by a second, independently-rounded pass.
    """
    warned_positions = {
        (warning.account_id, warning.instrument_id)
        for warning in ledger.warnings
        if warning.kind in _POSITION_SCOPED_KINDS
    }
    warned_txns = {
        (warning.account_id, warning.instrument_id, warning.txn_id)
        for warning in ledger.warnings
        if warning.kind in _LOT_SCOPED_KINDS
    }
    fee_warned_txns = {
        (warning.account_id, warning.instrument_id, warning.txn_id)
        for warning in ledger.warnings
        if warning.kind in _FEES_UNKNOWN_KINDS
    }

    excluded_account_ids: set[str] = set()
    rows: list[GainRow] = []

    for disposal in ledger.disposals:
        if not (start <= disposal.disposed_date <= end):
            continue

        account = accounts.get(disposal.account_id)
        if account is None:
            raise KeyError(
                f"no account for id {disposal.account_id!r}; cannot classify tax treatment "
                f"for disposal {disposal.disposal_id!r}"
            )

        if account.is_tax_advantaged:
            excluded_account_ids.add(disposal.account_id)
            continue

        term = classify_term(disposal.holding_start, disposal.disposed_date)
        basis_uncertain = (disposal.account_id, disposal.instrument_id) in warned_positions or (
            disposal.account_id,
            disposal.instrument_id,
            disposal.sell_txn_id,
        ) in warned_txns
        fees_unknown = (
            disposal.account_id,
            disposal.instrument_id,
            disposal.sell_txn_id,
        ) in fee_warned_txns
        is_wash_sale = disposal.disallowed_loss != 0 or disposal.permanently_disallowed

        # `proceeds` is quantized straight from the raw gross figure -- it is what a 1099-B's box
        # 1d reports and what this report's own totals sum (see the docstring above), so it must
        # stay a direct, independent rounding of `disposal.proceeds` and not be perturbed by fee
        # rounding. `fees` is solved for instead, as the residual that makes `proceeds - fees`
        # reproduce `quantize_money(disposal.proceeds - disposal.fees)` -- the true net-of-fees
        # amount, rounded exactly once -- rather than being its own independent rounding of
        # `disposal.fees`. Fees is the right field to absorb this: Form 8949 has no fee column at
        # all (app.tax.form8949's module docstring), so `fees` is never displayed on its own
        # anywhere downstream, only netted out of proceeds for column (d). Quantizing proceeds and
        # fees independently -- the previous bug -- can disagree with quantizing the net once by a
        # cent whenever a broker's per-share price carries more than two decimals, which is routine
        # for Webull's fractional shares.
        proceeds_q = quantize_money(disposal.proceeds)
        fees_q = proceeds_q - quantize_money(disposal.proceeds - disposal.fees)

        # Gain is **derived from the rounded components**, not rounded independently from the raw
        # ones. It is the difference of the figures this report publishes, and on a tax form that is
        # not a stylistic choice: Form 8949 column (h) is defined as (d) - (e) + (g), so a row whose
        # stated gain is not the difference of its own stated proceeds, basis and adjustment is a
        # defective form, whatever the underlying arithmetic said.
        #
        # Rounding each of the four figures separately and then rounding their combination again is
        # four roundings where the form allows one, and they disagree: measured on a real
        # ledger, some rows differed by a cent and Form 8949's short-term subtotal came out a few cents
        # below `GainsReport.short_term_gain` -- two totals of the same disposals, on one page.
        #
        # The loss test uses the rounded gain for the same reason. Deciding "is this a loss" on the
        # raw figure and then publishing the rounded one lets a disposal of -$0.004 be treated as a
        # loss while displaying $0.00.
        cost_basis_q = quantize_money(disposal.cost_basis)
        gain_loss_q = proceeds_q - fees_q - cost_basis_q

        # A disallowance can never exceed the loss it disallows: §1091 defers the loss you actually
        # had, not more. That holds exactly in the unrounded figures -- on a real ledger, no
        # wash-sale event disallowed more than its own loss. But the loss and the disallowance
        # are quantized independently a few lines apart, so a loss rounding down while its
        # disallowance rounds up leaves the pair a cent out of step. A couple of rows did exactly that,
        # and each then reported a $0.01 **gain** on a loss that had been disallowed in
        # full -- a row contradicting itself on the face of the form, column (g) claiming a wash sale
        # while column (h) showed a profit.
        #
        # Capping at the rounded loss is what makes the row honest, and capping at zero when the
        # rounded figure is not a loss at all is the same rule at its other end: an adjustment
        # against a gain has nothing to adjust. With both in place `reportable_q` is a plain sum --
        # the branch that used to guard it is now unreachable by construction, which is the point.
        # Costs a couple of cents against the deferred total, and buys back the invariant that a fully
        # disallowed loss reports exactly zero.
        # `disallowed_q` itself is left uncapped: it is the economic figure, and
        # `disallowed_loss_total` has to keep reconciling exactly with the sum of the wash-sale
        # events, which `test_canonical` pins and which broke the first time this was fixed by
        # capping here. The cap belongs on what the *form* may report, not on what happened.
        disallowed_q = quantize_money(disposal.disallowed_loss)
        reportable_q = min(gain_loss_q + disallowed_q, Decimal(0)) if gain_loss_q < 0 else gain_loss_q

        rows.append(
            GainRow(
                disposal_id=disposal.disposal_id,
                instrument_id=disposal.instrument_id,
                symbol=disposal.symbol,
                account_id=disposal.account_id,
                account_label=account.label,
                quantity=disposal.quantity,
                lot_id=disposal.lot_id,
                lot_method=disposal.lot_method.value if disposal.lot_method else None,
                acquired_date=disposal.acquired_date,
                holding_start=disposal.holding_start,
                disposed_date=disposal.disposed_date,
                term=term,
                proceeds=proceeds_q,
                cost_basis=cost_basis_q,
                fees=fees_q,
                gain_loss=gain_loss_q,
                disallowed_loss=disallowed_q,
                permanently_disallowed_loss=quantize_money(disposal.permanently_disallowed_loss),
                permanently_disallowed=disposal.permanently_disallowed,
                reportable_gain_loss=reportable_q,
                is_wash_sale=is_wash_sale,
                basis_uncertain=basis_uncertain,
                fees_unknown=fees_unknown,
            )
        )

    rows.sort(key=lambda r: (r.disposed_date, r.symbol, r.disposal_id))

    short_proceeds = short_basis = short_gain = Decimal(0)
    long_proceeds = long_basis = long_gain = Decimal(0)
    disallowed_total = Decimal(0)
    permanent_total = Decimal(0)
    uncertain_count = 0
    uncertain_gain = uncertain_proceeds = uncertain_basis = Decimal(0)
    unknown_fees_count = 0

    for row in rows:
        if row.term is HoldingTerm.SHORT:
            short_proceeds += row.proceeds
            short_basis += row.cost_basis
            short_gain += row.reportable_gain_loss
        else:
            long_proceeds += row.proceeds
            long_basis += row.cost_basis
            long_gain += row.reportable_gain_loss

        # Split by amount, not by flag: one sale can be replaced partly in an IRA and partly in a
        # taxable account, and the two outcomes -- destroyed versus deferred -- are not the same tax
        # event. Bucketing the whole row by a boolean reports one as the other.
        permanent_total += row.permanently_disallowed_loss
        disallowed_total += row.disallowed_loss - row.permanently_disallowed_loss

        if row.basis_uncertain:
            uncertain_count += 1
            # Accumulated alongside the count because the count alone understates the problem by an
            # order of magnitude -- see `GainsReport.gain_on_uncertain_basis`. `reportable_gain_loss`
            # rather than `gain_loss`, so this is comparable to the headline it qualifies.
            uncertain_gain += row.reportable_gain_loss
            uncertain_proceeds += row.proceeds
            uncertain_basis += row.cost_basis
        if row.fees_unknown:
            unknown_fees_count += 1

    return GainsReport(
        start=start,
        end=end,
        rows=tuple(rows),
        short_term_proceeds=short_proceeds,
        short_term_basis=short_basis,
        short_term_gain=short_gain,
        long_term_proceeds=long_proceeds,
        long_term_basis=long_basis,
        long_term_gain=long_gain,
        disallowed_loss_total=disallowed_total,
        permanently_disallowed_total=permanent_total,
        excluded_account_ids=tuple(sorted(excluded_account_ids)),
        rows_with_uncertain_basis=uncertain_count,
        gain_on_uncertain_basis=uncertain_gain,
        proceeds_on_uncertain_basis=uncertain_proceeds,
        basis_on_uncertain_basis=uncertain_basis,
        rows_with_unknown_fees=unknown_fees_count,
    )

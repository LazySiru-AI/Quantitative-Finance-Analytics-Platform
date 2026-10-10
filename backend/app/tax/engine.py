"""Composition: a ledger goes in, a :class:`~app.tax.models.TaxReport` comes out.

The order of operations is not negotiable and is the reason this module exists rather than the API
layer wiring the pieces together itself:

1. **Replay lots** across every account together (:func:`app.core.lots.build_lots`).
2. **Apply wash sales** — before any gain is classified, because the rule tolls holding periods and
   a tolled period changes short-term into long-term.
3. **Re-sync disposals** — see :func:`_sync_disposals`. Step 2 adjusts *lots*; disposals carry
   snapshots taken in step 1 and would otherwise still hold the pre-adjustment basis and the
   un-tolled holding period.
4. **Classify and total gains**, taxable accounts only.
5. **Emit Form 8949** from the classified rows.

Running step 4 before step 2, or skipping step 3, produces figures that look entirely reasonable and
are wrong.

**The output is a calculation, not tax advice.** Reconcile it against the 1099-B forms before filing.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections import defaultdict
from collections.abc import Mapping, Sequence

from app.core.canonical import canonicalize_ledger
from app.core.lots import LotLedger, LotMethod, OpeningPosition, TransferBasis, build_lots
from app.core.models import Account, Instrument, Transaction
from app.core.money import quantize_money
from app.db import sqlite as ledger_store
from app.tax.form8949 import build_form8949
from app.tax.gains import realized_gains
from app.tax.models import TaxReport, TaxWarning, WarningGroup, WashSaleEvent
from app.tax.washsale import apply_wash_sales
from app.tax.washsale_summary import LossSale, build_wash_sale_summary

__all__ = ["build_tax_report", "default_tax_year", "report_from_ledger"]

#: Kind token for the wash-sale re-sync notes. Not a `app.core.lots.WarningKind` member because
#: `_sync_disposals` runs after the lot replay is over and has no `LotWarning` of its own -- but it
#: needs a stable, machine-groupable token exactly like the replay-sourced kinds, for the same reason
#: (`TaxWarning.kind` docstring).
_BACKWARD_ATTACHMENT_KIND = "backward_basis_attachment"


def _sync_disposals(
    ledger: LotLedger, events: Sequence[WashSaleEvent], *, accounts: Mapping[str, Account]
) -> list[TaxWarning]:
    """Re-read wash-sale adjustments from the lots back onto the disposals drawn from them.

    :func:`app.core.lots.build_lots` snapshots two fields onto every ``Disposal`` at replay time —
    ``cost_basis`` and ``holding_start`` — and :func:`app.tax.washsale.apply_wash_sales` then changes
    both on the *lot*: it raises the basis by the disallowed loss and tolls the holding period back
    to the sold lot's start. A replacement lot that is itself later sold therefore carries two stale
    values, and :mod:`app.tax.gains` reads the disposal, not the lot.

    Neither staleness is cosmetic:

    * **Basis** — unsynced, the gain on every chained wash sale is overstated by exactly the deferred
      loss, which is the opposite of what a deferral is for.
    * **Holding period** — unsynced, a tolled long-term position is classified short-term. That is a
      wrong *rate*, and converting short-term into long-term is the entire purpose of tolling.

    The holding start is synced unconditionally: :attr:`~app.core.models.Lot.effective_holding_start`
    equals the acquisition date unless something tolled it, so the write is a no-op in the ordinary
    case. Basis is synced only for lots that actually took an adjustment, leaving the deliberately
    synthetic zero-basis lots created for oversold positions untouched.

    One case is genuinely unsettled and is **flagged rather than decided**: the 61-day window reaches
    30 days *backwards*, so a replacement lot can be disposed of before the loss sale that triggers
    its adjustment. Whether the increase attaches to a disposal that already happened is not
    something Pub 550 answers cleanly. The basis is adjusted uniformly — the lot's basis is what it
    is — and a note is returned naming the affected disposal so the user can rule on it.

    Returns structured notes for :attr:`~app.tax.models.TaxReport.warnings`.
    """
    lots = ledger.lots_by_id()
    triggered_on: dict[str, dt.date] = {}
    for event in events:
        if event.basis_added_to_lot_id is None:
            # Rev. Rul. 2008-5: the IRA case adds basis nowhere, so there is nothing to sync.
            continue
        # **Every** replacement lot, not just `basis_added_to_lot_id`.
        #
        # That field is singular by construction -- `_apply_ordinary_adjustment` returns the lot that
        # absorbed the *most* of a disallowance -- but the adjustment itself is spread across every
        # lot in the matched group, and `WashSaleEvent` says so in `replacement_lot_ids`. Keying this
        # map on the singular field meant a sale replaced by three lots re-synced one of them and
        # left the other two holding a basis the wash-sale pass had already raised.
        #
        # The disposals drawn from those lots then reported a gain computed against the *unraised*
        # basis while still carrying the disallowance measured against the raised one -- a row that
        # says "this was a loss, and here is the gain it made", which `apply_wash_sales` cannot
        # produce (it returns early on `gain_loss >= 0`). A handful of such rows on a real ledger put
        # Form 8949's short-term subtotal above the net-gain tile on the same page, both
        # claiming to total the same disposals.
        #
        # `basis_added_to_lot_id is None` still gates the IRA case, and the `wash_sale_adjustment`
        # check below still skips any lot that took no adjustment, so widening this cannot sync a lot
        # that was never touched.
        for lot_id in event.replacement_lot_ids:
            existing = triggered_on.get(lot_id)
            triggered_on[lot_id] = (
                event.sale_date if existing is None else min(existing, event.sale_date)
            )

    notes: list[TaxWarning] = []
    for disposal in ledger.disposals:
        lot = lots.get(disposal.lot_id)
        if lot is None:
            continue

        disposal.holding_start = lot.effective_holding_start

        trigger_date = triggered_on.get(disposal.lot_id)
        if trigger_date is None or lot.quantity == 0 or lot.wash_sale_adjustment == 0:
            continue

        disposal.cost_basis = lot.basis_per_share * disposal.quantity

        if disposal.disposed_date < trigger_date:
            account = accounts.get(disposal.account_id)
            notes.append(
                TaxWarning(
                    kind=_BACKWARD_ATTACHMENT_KIND,
                    account_id=disposal.account_id,
                    broker=account.broker.value if account is not None else None,
                    symbol=disposal.symbol,
                    trade_date=disposal.disposed_date,
                    detail=(
                        f"{disposal.symbol}: shares from lot {disposal.lot_id} were sold on "
                        f"{disposal.disposed_date.isoformat()}, before the "
                        f"{trigger_date.isoformat()} loss sale that made that lot a wash-sale "
                        "replacement. The basis increase has been applied to this earlier "
                        "disposal; whether it should be is not settled by Pub 550. Review before "
                        "filing."
                    ),
                )
            )

    return notes


def _summarize_warnings(warnings: Sequence[TaxWarning]) -> tuple[WarningGroup, ...]:
    """Collapse individual warnings into ``(kind, account)`` counts for the headline view.

    This is the aggregation the Tax page leads with: 330 individual basis-gap messages for one tax
    year is not information a reader can act on, a count and a representative example is. Nothing is
    lost -- the ungrouped list still travels as :attr:`~app.tax.models.TaxReport.warnings` for an
    expandable detail section.

    Sorted by count descending (the biggest problem first), then ``kind`` and ``account_id`` for a
    stable order among ties.
    """
    groups: dict[tuple[str, str | None], list[TaxWarning]] = defaultdict(list)
    for warning in warnings:
        groups[(warning.kind, warning.account_id)].append(warning)

    result = [
        WarningGroup(
            kind=kind,
            account_id=account_id,
            broker=items[0].broker,
            count=len(items),
            sample_detail=items[0].detail,
        )
        for (kind, account_id), items in groups.items()
    ]
    result.sort(key=lambda g: (-g.count, g.kind, g.account_id or ""))
    return tuple(result)


def build_tax_report(
    transactions: Sequence[Transaction],
    *,
    accounts: Mapping[str, Account],
    tax_year: int,
    instruments: Mapping[str, Instrument] | None = None,
    method: LotMethod = LotMethod.FIFO,
    opening: Sequence[OpeningPosition] = (),
    transfer_basis: Sequence[TransferBasis] = (),
    as_of: dt.date | None = None,
) -> TaxReport:
    """Run the full pipeline over an in-memory ledger.

    Args:
        transactions: Every account's transactions together. A per-account call would miss every
            cross-account wash sale, which is most of them in this dataset.
        accounts: ``account_id`` → account, for tax treatment.
        tax_year: Calendar year to report. Wash-sale windows still look outside it, because a
            January replacement purchase disallows a December loss.
        instruments: ``instrument_id`` → instrument, for display symbols.
        method: Lot selection method.
        opening: Positions each account already held when its export begins -- see
            :class:`app.core.lots.OpeningPosition`. Threaded through because a sale of shares older
            than the export is otherwise booked at zero basis, which overstates realised gain by the
            entire proceeds.
        as_of: The date "days until safe to repurchase" is measured from. Defaults to
            :meth:`datetime.date.today`. **This is the one clock-dependent input to an otherwise
            deterministic report** -- every other figure on :class:`~app.tax.models.TaxReport`
            follows only from ``transactions``, ``accounts``, and ``tax_year``. ``as_of`` affects
            only :attr:`~app.tax.models.WashSaleSymbolSummary.days_until_safe` and
            :attr:`~app.tax.models.WashSaleSymbolSummary.window_is_open` on
            :attr:`~app.tax.models.TaxReport.wash_sale_summary`. Tests should pin it explicitly
            rather than relying on the default, or they will start failing on whatever day they
            happen to run.
    """
    lot_ledger = build_lots(
        transactions,
        accounts=accounts,
        instruments=instruments,
        method=method,
        opening=opening,
        transfer_basis=transfer_basis,
    )

    resolved_as_of = as_of if as_of is not None else dt.date.today()

    wash = apply_wash_sales(lot_ledger, accounts=accounts)
    sync_notes = _sync_disposals(lot_ledger, wash.events, accounts=accounts)

    start = dt.date(tax_year, 1, 1)
    end = dt.date(tax_year, 12, 31)
    gains = realized_gains(lot_ledger, accounts=accounts, start=start, end=end)
    form8949 = build_form8949(gains)

    # Wash sales and unsettled pairs are reported for the year on display, but were *computed* over
    # the whole ledger -- a replacement bought in January disallows the previous December's loss.
    year_events = tuple(
        event for event in wash.events if start <= event.sale_date <= end
    )
    year_unsettled = tuple(
        pair for pair in wash.unsettled if start <= pair.sale_date <= end
    )

    # Warnings after the reporting year cannot affect its figures; everything on or before it can,
    # because an unestablished basis from an earlier year flows into this year's disposals.
    warnings: list[TaxWarning] = [
        TaxWarning(
            kind=warning.kind.value,
            account_id=warning.account_id,
            broker=(
                accounts[warning.account_id].broker.value
                if warning.account_id in accounts
                else None
            ),
            symbol=warning.symbol,
            trade_date=warning.trade_date,
            detail=warning.detail,
        )
        for warning in lot_ledger.warnings
        if warning.trade_date <= end
    ]
    warnings.extend(sync_notes)

    # Aggregated over *every* triggered event, not just `year_events`: "when is it safe to
    # repurchase" is a present-tense question about the symbol, not one scoped to the tax year on
    # display -- a deferred loss from a prior year's wash sale is exactly as real, and its
    # replacement lot's own window is exactly as live, as one triggered in December.
    #
    # The loss sales are passed separately and they are what makes the answer correct. A
    # `WashSaleEvent` exists only where a loss *already matched a replacement purchase*, so a loss
    # nobody has bought back yet produces none -- and that is the position this panel exists to
    # report on. Anchoring the dates on events alone told the user three symbols were safe to
    # repurchase while their windows were genuinely open, and omitted three more entirely. See
    # `app.tax.washsale_summary`'s module docstring for the measurement.
    #
    # Taxable accounts only, matching `apply_wash_sales`: no loss is recognised inside an IRA, so
    # there is nothing there for 1091 to disallow and nothing to warn a user away from repurchasing.
    loss_sales = [
        LossSale(
            symbol=disposal.symbol,
            sale_date=disposal.disposed_date,
            account_id=disposal.account_id,
            disposal_id=disposal.disposal_id,
            quantity=disposal.quantity,
            # Quantized here, at the same point `WashSaleEvent.loss_amount` is (see
            # `app.tax.washsale`), rather than left as `disposal.gain_loss`'s exact-precision
            # negative: this figure crosses into `LossSale`, a fold input the exposure tracker
            # serialises verbatim for a loss that never matched a replacement, and it must already
            # be at cent precision by the time it gets there.
            loss_amount=quantize_money(-disposal.gain_loss),
        )
        for disposal in lot_ledger.disposals
        if disposal.is_loss
        and disposal.account_id in accounts
        and not accounts[disposal.account_id].is_tax_advantaged
    ]
    wash_sale_summary = build_wash_sale_summary(
        wash.events, as_of=resolved_as_of, loss_sales=loss_sales
    )

    return TaxReport(
        tax_year=tax_year,
        generated_at=dt.datetime.now(dt.UTC),
        gains=gains,
        form8949=form8949,
        wash_sales=year_events,
        unsettled=year_unsettled,
        warnings=tuple(warnings),
        warning_groups=_summarize_warnings(warnings),
        wash_sale_summary=wash_sale_summary,
    )


def report_from_ledger(
    conn: sqlite3.Connection,
    *,
    tax_year: int,
    method: LotMethod = LotMethod.FIFO,
    opening: Sequence[OpeningPosition] = (),
    transfer_basis: Sequence[TransferBasis] = (),
    as_of: dt.date | None = None,
) -> TaxReport:
    """Load the ledger from SQLite and build the report.

    Reads in the deterministic replay order :func:`app.db.sqlite.fetch_transactions` guarantees, and
    reads **every** account rather than filtering, because wash-sale detection is only correct when
    it can see all of them at once.

    ``as_of`` is passed through to :func:`build_tax_report` unchanged -- see its docstring: it is
    the one clock-dependent input to an otherwise deterministic report, and tests calling this
    function should pin it rather than let it default to today.
    """
    accounts = {account.account_id: account for account in ledger_store.fetch_accounts(conn)}
    instruments = {
        instrument.instrument_id: instrument
        for instrument in ledger_store.fetch_instruments(conn)
    }
    transactions = [
        ledger_store.transaction_from_row(row) for row in ledger_store.fetch_transactions(conn)
    ]

    # A broker that never supplies a CUSIP (Webull) gets its own symbol-keyed instrument_id for a
    # security another broker (Robinhood) already identified by CUSIP -- see
    # app.core.canonical's module docstring. Wash-sale matching keys on instrument_id, so this must
    # run before build_lots or a cross-broker wash-sale pair for that security is invisible to the
    # engine regardless of what runs afterwards.
    transactions, instruments = canonicalize_ledger(transactions, instruments)

    return build_tax_report(
        transactions,
        opening=opening,
        transfer_basis=transfer_basis,
        accounts=accounts,
        tax_year=tax_year,
        instruments=instruments,
        method=method,
        as_of=as_of,
    )


def default_tax_year(today: dt.date | None = None) -> int:
    """The year the Tax page opens on: the last complete calendar year."""
    return (today or dt.date.today()).year - 1

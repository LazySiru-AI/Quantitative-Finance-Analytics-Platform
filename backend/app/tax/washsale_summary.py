"""Per-symbol wash-sale exposure: what is deferred on a ticker, and when it is safe to buy it back.

:func:`app.tax.washsale.apply_wash_sales` produces one :class:`~app.tax.models.WashSaleEvent` per
disposal (or per disposal split across a taxable and an IRA replacement -- two events from one
sale). That is the right unit for a full audit trail, and the wrong one for the question a user
actually asks on the Tax page: "what is deferred on this symbol right now, and when can I buy it
back without doing this again?" This module answers that question by folding down to one row per
symbol.

**It takes two populations, and that is the whole correctness of the module.** Events alone are not
enough, because a ``WashSaleEvent`` only exists where a loss sale has *already matched a replacement
purchase* -- ``apply_wash_sales`` emits nothing when ``quantity_replaced_total`` is zero. A loss you
have not bought back yet produces no event at all, and that is precisely the position someone opens
this panel to ask about.

Built from events alone, measured against a real ledger, the result was not
merely incomplete but **affirmatively wrong**:

* Several symbols with an open window were missing entirely -- one sold at a loss two days earlier,
  another whose window closed that very day.
* Several symbols were reported **safe to repurchase while a real window was open**: the panel showed
  an older last loss sale than the true one, so it said "safe" about a purchase that would have
  triggered 1091 that day.
* The open-window count read lower than the truth.

So ``loss_sales`` carries **every** loss disposal in a taxable account, replaced or not, and it --
not the event list -- anchors the dates and the symbol set. Events supply only the money.

Two figures must never be added together, and this module keeps them apart the whole way through:

* ``deferred_disallowed`` is loss that has **already been added to a replacement lot's cost
  basis**. It is not released by waiting -- it is recovered when that lot is eventually sold, and
  only if *that* sale is not itself replaced within 30 days. "Days until safe" describes when a new
  purchase stops re-triggering the rule, not when this money becomes available.
* ``permanently_disallowed`` is Rev. Rul. 2008-5: the replacement was bought inside an IRA, so no
  basis was added anywhere and the loss is simply gone. Summing it with the deferred figure would
  tell a user they will eventually recover money that no longer exists.

The 30/31-day boundary is IRC §1091's own, not a choice made here: a sale's window reaches 30
calendar days after the sale, inclusive, so the first day a repurchase does *not* land back inside
that window is the 31st day after. See ``app.tax.washsale`` for the full rule and its citations.

Each symbol row also carries ``sales`` -- the individual loss disposals behind its totals, for the
``GET /api/tax/wash-sales`` exposure tracker's drill-down. See :class:`~app.tax.models.WashSaleSaleRow`
for why that list is graded per triggered *event* rather than per disposal, and why an untriggered
loss -- no event, nothing disallowed yet -- still gets its own row instead of being invisible below
the symbol level. :func:`build_wash_sale_exposure_report` re-sorts the fold's output for that
endpoint; it does not rebuild it.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.tax.models import (
    WashSaleEvent,
    WashSaleExposureReport,
    WashSaleSaleRow,
    WashSaleSummary,
    WashSaleSymbolSummary,
)

__all__ = [
    "LossSale",
    "build_wash_sale_exposure_report",
    "build_wash_sale_summary",
]


@dataclass(frozen=True, slots=True)
class LossSale:
    """One loss disposal in a taxable account, replaced or not.

    Deliberately not a :class:`~app.tax.models.WashSaleEvent`: the entire point of this type is to
    carry the sales that produced *no* event. A plain dataclass rather than a pydantic model because
    it never crosses the wire directly -- it is an input to the fold, and the fold's output
    (:class:`~app.tax.models.WashSaleSymbolSummary`, via its ``sales``) is what the API serialises.
    """

    symbol: str
    sale_date: dt.date
    account_id: str
    disposal_id: str = ""
    """Joins against :attr:`~app.tax.models.WashSaleEvent.disposal_id` -- the key that tells the fold
    whether this loss ever matched a replacement. Defaulted rather than required so existing callers
    that only ever needed the date and the symbol set (every test predating the exposure tracker's
    per-sale drill-down) keep constructing this positionally without a disposal id."""
    quantity: Decimal = Decimal(0)
    """Shares sold, for the untriggered-sale row the exposure tracker shows when no event exists to
    supply ``WashSaleEvent.quantity_sold``."""
    loss_amount: Decimal = Decimal(0)
    """The full realised loss before disallowance, positive, quantized to cents at the same point
    ``WashSaleEvent.loss_amount`` is (see ``app.tax.washsale``). Real even when nothing has been
    disallowed yet -- an untriggered loss is exactly as real as a triggered one."""

#: Mirrors `app.tax.washsale._WINDOW_DAYS` -- the number of days *before or after* the sale that a
#: replacement purchase re-triggers §1091. Not imported directly: that name is private to the
#: module that enforces the rule, and this module only needs the resulting arithmetic on
#: `last_sale_date`, which the events already reflect.
_WINDOW_DAYS = 30


def _build_sale_rows(
    events: Sequence[WashSaleEvent], loss_sales: Sequence[LossSale]
) -> tuple[WashSaleSaleRow, ...]:
    """One symbol's drill-down: a row per triggered event, plus a zeroed row per untriggered loss.

    Deliberately event-grained rather than disposal-grained -- see :class:`WashSaleSaleRow`'s
    docstring. A disposal split across a taxable and an IRA replacement produces two events and
    therefore two rows here, because folding them into one would force a single ``disallowed_loss``
    to mix deferred and permanent money, which is the one combination this module never performs.

    ``loss_sales`` entries are joined against ``events`` by ``disposal_id`` purely to decide whether
    a zeroed row is needed -- a loss sale whose disposal already has an event is fully represented by
    that event's row and is not duplicated.
    """
    triggered_disposal_ids = {event.disposal_id for event in events}
    rows = [
        WashSaleSaleRow(
            disposal_id=event.disposal_id,
            sale_date=event.sale_date,
            account_id=event.sale_account_id,
            quantity_sold=event.quantity_sold,
            quantity_replaced=event.quantity_replaced,
            loss_amount=event.loss_amount,
            disallowed_loss=event.disallowed_loss,
            permanently_disallowed=event.permanently_disallowed,
            replacement_account_ids=event.replacement_account_ids,
            window_closes_on=event.sale_date + dt.timedelta(days=_WINDOW_DAYS + 1),
        )
        for event in events
    ]
    rows.extend(
        WashSaleSaleRow(
            disposal_id=sale.disposal_id,
            sale_date=sale.sale_date,
            account_id=sale.account_id,
            quantity_sold=sale.quantity,
            quantity_replaced=Decimal(0),
            loss_amount=sale.loss_amount,
            disallowed_loss=Decimal(0),
            permanently_disallowed=False,
            replacement_account_ids=(),
            window_closes_on=sale.sale_date + dt.timedelta(days=_WINDOW_DAYS + 1),
        )
        for sale in loss_sales
        if sale.disposal_id not in triggered_disposal_ids
    )
    rows.sort(key=lambda row: row.sale_date, reverse=True)
    return tuple(rows)


def build_wash_sale_summary(
    events: Sequence[WashSaleEvent],
    *,
    as_of: dt.date,
    loss_sales: Sequence[LossSale] = (),
) -> WashSaleSummary:
    """Fold loss sales, and the wash-sale events they triggered, down to one row per symbol.

    Args:
        events: Triggered disallowances. These supply the **money** -- ``deferred_disallowed`` and
            ``permanently_disallowed`` -- and nothing else.
        as_of: The only clock-dependent input; see :func:`app.tax.engine.build_tax_report`. Decides
            ``days_until_safe`` and ``window_is_open``, and nothing else.
        loss_sales: Every loss disposal in a taxable account, replaced or not. Supplies the **dates**
            and the symbol set. Defaulting to empty keeps the fold callable in isolation, but a
            caller that omits it gets event dates instead -- which is wrong for any symbol sold at a
            loss and not yet bought back. See the module docstring for what that cost on real data.

    A symbol present in ``loss_sales`` but absent from ``events`` is included with zero deferred and
    zero permanent. That row is not noise: it is a loss whose window is open and which has not yet
    been re-triggered, the one case where acting on this panel still changes the outcome.

    Empty input produces an empty, zeroed summary rather than raising -- a year with no losses is
    the common case, not an error.
    """
    by_symbol: dict[str, list[WashSaleEvent]] = defaultdict(list)
    for event in events:
        by_symbol[event.symbol].append(event)

    sales_by_symbol: dict[str, list[LossSale]] = defaultdict(list)
    for sale in loss_sales:
        sales_by_symbol[sale.symbol].append(sale)

    symbol_summaries: list[WashSaleSymbolSummary] = []
    for symbol in sorted(set(by_symbol) | set(sales_by_symbol)):
        symbol_events = by_symbol.get(symbol, [])
        symbol_sales = sales_by_symbol.get(symbol, [])
        deferred = Decimal(0)
        permanent = Decimal(0)
        disposal_ids: set[str] = set()
        accounts: set[str] = set()

        # Dates and the account set come from the loss sales wherever there are any, because that is
        # the complete population. Falling back to event dates is for the degenerate case of a caller
        # that passed events with no sales -- it is what produced the false "safe" claims.
        dates: list[dt.date] = [s.sale_date for s in symbol_sales] or [
            e.sale_date for e in symbol_events
        ]
        first_sale_date = min(dates)
        last_sale_date = max(dates)
        accounts.update(s.account_id for s in symbol_sales)

        for event in symbol_events:
            if event.permanently_disallowed:
                permanent += event.disallowed_loss
            else:
                deferred += event.disallowed_loss
            disposal_ids.add(event.disposal_id)
            accounts.add(event.sale_account_id)

        # The latest loss sale's window is the last to close -- an earlier sale on the same symbol
        # is already safe to repurchase against once this one is.
        repurchase_safe_on = last_sale_date + dt.timedelta(days=_WINDOW_DAYS + 1)
        days_until_safe = max(0, (repurchase_safe_on - as_of).days)
        window_is_open = as_of <= last_sale_date + dt.timedelta(days=_WINDOW_DAYS)

        symbol_summaries.append(
            WashSaleSymbolSummary(
                symbol=symbol,
                deferred_disallowed=deferred,
                permanently_disallowed=permanent,
                event_count=len(symbol_events),
                # Distinct loss sales over the full population, not `len(disposal_ids)` -- that
                # counts only the ones that went on to trigger a disallowance.
                loss_sale_count=len(symbol_sales) or len(disposal_ids),
                first_sale_date=first_sale_date,
                last_sale_date=last_sale_date,
                repurchase_safe_on=repurchase_safe_on,
                days_until_safe=days_until_safe,
                window_is_open=window_is_open,
                accounts=tuple(sorted(accounts)),
                sales=_build_sale_rows(symbol_events, symbol_sales),
            )
        )

    symbol_summaries.sort(key=lambda s: (-s.deferred_disallowed, s.symbol))

    total_deferred = sum((s.deferred_disallowed for s in symbol_summaries), Decimal(0))
    total_permanently_disallowed = sum(
        (s.permanently_disallowed for s in symbol_summaries), Decimal(0)
    )
    open_window_count = sum(1 for s in symbol_summaries if s.window_is_open)

    return WashSaleSummary(
        as_of=as_of,
        symbols=tuple(symbol_summaries),
        total_deferred=total_deferred,
        total_permanently_disallowed=total_permanently_disallowed,
        open_window_count=open_window_count,
    )


def build_wash_sale_exposure_report(
    summary: WashSaleSummary, *, generated_at: dt.datetime
) -> WashSaleExposureReport:
    """Re-shape a whole-ledger :class:`WashSaleSummary` into the exposure tracker's response.

    Takes an already-built ``summary`` rather than ``events``/``loss_sales`` directly: the totals,
    the per-symbol figures and the ``sales`` drill-down (see :func:`build_wash_sale_summary`) are all
    correct as they stand, and this function's only job is the tracker's own symbol order.

    ``WashSaleSummary.symbols`` is sorted by :attr:`~app.tax.models.WashSaleSymbolSummary.deferred_disallowed`
    descending for the Tax report page, where size is what a reader wants first. The tracker instead
    exists to answer "what is still live", so it leads with :attr:`~app.tax.models.WashSaleSymbolSummary.window_is_open`
    before deferred size ever breaks the tie -- a symbol with an open window and nothing deferred yet
    (see :class:`WashSaleSaleRow`) still needs to surface above a large, fully-settled figure whose
    window closed months ago. That reordering has to happen server-side, or a client re-sorting the
    same rows two different ways for two different pages is the alternative.
    """
    symbols = tuple(
        sorted(
            summary.symbols,
            key=lambda s: (not s.window_is_open, -s.deferred_disallowed, s.symbol),
        )
    )
    return WashSaleExposureReport(
        as_of=summary.as_of,
        generated_at=generated_at,
        total_deferred=summary.total_deferred,
        total_permanently_disallowed=summary.total_permanently_disallowed,
        open_window_count=summary.open_window_count,
        symbol_count=len(symbols),
        symbols=symbols,
    )

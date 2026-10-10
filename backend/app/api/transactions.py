"""Transaction history: the ledger itself, with the provenance already attached to every row.

This endpoint closes a gap that was structural rather than accidental. The application's design
premise is that every displayed figure can be walked back to a line in a broker CSV --
:class:`~app.core.models.Transaction` cannot even be constructed without its ``import_id`` and
``source_row``, and that chain is maintained faithfully through ingest, the lot engine and the tax
report. It was then never exposed. A UAT persona went looking for its own week of trades, found
positions and a tax form and nothing in between, and concluded the application could not show it
what it had done. It could not.

Unlike every other read endpoint here, this one returns **stored** rows rather than derived state.
No lot replay, no wash-sale pass, no pricing: what is in the ledger, filtered and paged. That makes
it the reference against which the derived endpoints can be checked -- which is most of its value,
since a disagreement between this and the portfolio is exactly the kind of defect the derived views
cannot reveal on their own.

**Paged, and honest about it.** A real ledger runs to about a thousand rows and a decade of activity would be
several times that. The response carries ``total`` alongside the page so a caller can tell a short
page from a last page, and ``limit``/``offset`` echo back so a client never has to remember what it
asked for.

**Ordering is the ledger's own replay order** -- ``(trade_date, executed_at_utc, sequence, txn_id)``
as documented on :func:`app.db.sqlite.fetch_transactions` -- optionally reversed for display.
Reversing is done after the deterministic sort rather than by sorting descending, so newest-first and
oldest-first are exact mirrors of each other and paging is stable in both directions.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated, Final

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from app.config import get_settings
from app.core.models import Money, Quantity, Transaction, TxnAction
from app.datasource import ledger_db_path
from app.db import sqlite

_ZERO: Final = Decimal(0)

router = APIRouter(prefix="/api/portfolio/transactions", tags=["portfolio"])

#: Rows per page when the caller does not say. Large enough that a week of activity -- the question
#: this endpoint exists to answer -- arrives in one request, small enough that a careless client
#: cannot pull the whole ledger by accident.
_DEFAULT_LIMIT: Final = 200
_MAX_LIMIT: Final = 1000


class TransactionRow(BaseModel):
    """One ledger row, as stored.

    Money and quantities cross the wire as decimal strings, matching the rest of the API: JSON
    numbers are IEEE doubles and a cost basis is not a thing to round-trip through one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    txn_id: str
    account_id: str
    broker: str
    action: str

    trade_date: dt.date
    settle_date: dt.date | None = None
    executed_at: dt.datetime | None = None
    sequence: int
    """Position within the source file. The tie-break for two same-day trades in one symbol, and
    therefore part of why a lot replay is reproducible."""

    symbol: str | None = None
    instrument_id: str | None = None
    cusip: str | None = None

    quantity: Quantity | None = None
    price: Money | None = None
    fees: Money
    amount: Money | None = None
    """Signed net cash effect: negative for outflows, ``null`` for rows that move no cash (an ACAT
    position leg, a split)."""

    description: str | None = None
    raw_code: str | None = None
    """The broker's own transaction code, retained verbatim."""

    import_id: str
    source_row: int
    """Zero-based row index in the source file, header excluded. With ``import_id``, this is the
    coordinate of the exact CSV line this row came from."""


class TransactionPage(BaseModel):
    """One page of history, plus what it took to get it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    transactions: list[TransactionRow]
    total: int
    """Rows matching the filters, ignoring paging. Compare against ``len(transactions)`` to tell a
    partial page from the last one."""
    limit: int
    offset: int
    has_more: bool

    as_of: dt.date | None = None
    """Latest trade date in the *filtered* set, or ``null`` when the filters matched nothing."""
    earliest: dt.date | None = None

    total_bought: Money
    total_sold: Money
    """Gross buy and sell notional across the filtered set -- not just this page.

    Present because the first thing anyone asks of a trade history is "how much did I trade", and
    computing it client-side from a page would silently answer for the page instead of the set.
    Gross, unsigned, fees excluded: a turnover figure, not a cash-flow one."""
    net_cash_flow: Money
    """Signed sum of ``amount`` across the filtered set. Fees and income included, so this *is* the
    cash-flow figure and will not equal ``total_sold - total_bought``."""


@router.get("", response_model=TransactionPage)
def list_transactions(
    account_id: Annotated[str | None, Query(description="Restrict to one account.")] = None,
    symbol: Annotated[str | None, Query(description="Ticker as written by the broker.")] = None,
    action: Annotated[
        str | None, Query(description="Canonical action, e.g. `buy`, `sell`, `dividend`.")
    ] = None,
    start: Annotated[dt.date | None, Query(description="Earliest trade date, inclusive.")] = None,
    end: Annotated[dt.date | None, Query(description="Latest trade date, inclusive.")] = None,
    trades_only: Annotated[
        bool, Query(description="Buys and sells only, excluding income, fees and transfers.")
    ] = False,
    newest_first: bool = True,
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = _DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TransactionPage:
    """Ledger rows matching the filters, newest first by default.

    Every row carries ``import_id`` and ``source_row``, so any figure derived from this history can
    be traced to the CSV line behind it.

    **This is stored data, not a calculation, and not investment advice.**
    """
    settings = get_settings()
    ledger_file = ledger_db_path(settings)
    if not ledger_file.exists():
        raise HTTPException(status_code=404, detail="no ledger yet; import broker exports first")

    if action is not None:
        try:
            TxnAction(action)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"unknown action {action!r}; valid actions are "
                    f"{sorted(a.value for a in TxnAction)}"
                ),
            ) from None

    if start is not None and end is not None and start > end:
        raise HTTPException(
            status_code=422, detail=f"start {start} is after end {end}"
        )

    with sqlite.connect(ledger_file, read_only=True) as conn:
        # Filtering in Python rather than SQL: `fetch_transactions` owns the replay ordering, which
        # is subtle enough (see its docstring on `executed_at_utc` and DST) that reimplementing it
        # in a second query is a worse trade than reading rows and filtering them. At ledger sizes
        # this application targets -- about a thousand rows -- the cost is not measurable.
        rows = [
            sqlite.transaction_from_row(row)
            for row in sqlite.fetch_transactions(conn, account_id=account_id)
        ]

    wanted_symbol = symbol.upper() if symbol else None
    matched = [
        txn
        for txn in rows
        if (wanted_symbol is None or (txn.symbol or "").upper() == wanted_symbol)
        and (action is None or txn.action.value == action)
        and (start is None or txn.trade_date >= start)
        and (end is None or txn.trade_date <= end)
        and (not trades_only or txn.action.is_trade)
    ]

    total_bought = sum(
        (
            txn.quantity * txn.price
            for txn in matched
            if txn.action is TxnAction.BUY and txn.quantity is not None and txn.price is not None
        ),
        start=_ZERO,
    )
    total_sold = sum(
        (
            txn.quantity * txn.price
            for txn in matched
            if txn.action is TxnAction.SELL and txn.quantity is not None and txn.price is not None
        ),
        start=_ZERO,
    )
    net_cash_flow = sum((txn.amount for txn in matched if txn.amount is not None), start=_ZERO)

    dates = [txn.trade_date for txn in matched]
    ordered = list(reversed(matched)) if newest_first else matched
    page = ordered[offset : offset + limit]

    return TransactionPage(
        transactions=[_to_row(txn) for txn in page],
        total=len(matched),
        limit=limit,
        offset=offset,
        has_more=offset + len(page) < len(matched),
        as_of=max(dates) if dates else None,
        earliest=min(dates) if dates else None,
        total_bought=total_bought,
        total_sold=total_sold,
        net_cash_flow=net_cash_flow,
    )


def _to_row(txn: Transaction) -> TransactionRow:
    """Model -> wire shape.

    Field by field rather than ``model_dump`` because the wire shape is a deliberate subset: it drops
    ``currency`` and ``transfer_group``, which no caller of this endpoint has asked for and which
    would have to be supported forever once returned. Spelling the mapping out also means adding a
    field to :class:`~app.core.models.Transaction` never silently widens this response.
    """
    return TransactionRow(
        txn_id=txn.txn_id,
        account_id=txn.account_id,
        broker=txn.broker.value,
        action=txn.action.value,
        trade_date=txn.trade_date,
        settle_date=txn.settle_date,
        executed_at=txn.executed_at,
        sequence=txn.sequence,
        symbol=txn.symbol,
        instrument_id=txn.instrument_id,
        cusip=txn.cusip,
        quantity=txn.quantity,
        price=txn.price,
        fees=txn.fees,
        amount=txn.amount,
        description=txn.description,
        raw_code=txn.raw_code,
        import_id=txn.import_id,
        source_row=txn.source_row,
    )

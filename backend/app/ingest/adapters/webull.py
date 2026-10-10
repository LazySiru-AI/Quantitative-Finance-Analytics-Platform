"""Webull order-records CSV adapter.

Header: ``Name, Symbol, Side, Status, Filled, Total Qty, Price, Avg Price, Time-in-Force,
Placed Time, Filled Time``

.. warning::

   **This export is an order log, not an activity ledger.** It records order submissions and their
   outcomes and nothing else: there are no dividends, no interest, no fees, no deposits or
   withdrawals, no ACAT transfers, and no splits or other corporate actions anywhere in it. A cost
   basis, a position, or a realised-gain figure computed from Webull data alone is therefore
   *structurally incomplete* -- not merely stale. Present Webull totals as partial in the import
   summary rather than as authoritative, and expect them to disagree with a Webull statement.

Two further gaps follow from the same fact:

* **Fees are unknown, not zero.** The export has no fee or commission column at all, so every
  transaction this adapter emits carries ``fees = 0``. That is the absence of data, not a measurement
  that no fee was charged; regulatory (SEC/TAF) fees on sales in particular are missing and slightly
  overstate sale proceeds.
* **No CUSIP.** Only a ticker is available, so instruments are emitted with ``cusip=None`` and their
  identity falls back to :func:`~app.core.ids.normalize_symbol`. Webull writes ``BRK-B`` where
  Robinhood writes ``BRK.B``; the normaliser folds both to ``BRK.B`` so the two brokers' rows land on
  one instrument. This is a heuristic. When a Robinhood import later supplies a CUSIP for the same
  ticker, that CUSIP-keyed instrument is the authoritative one.

Measured over three real exports (Cash, Margin, ROTH); the row counts below are illustrative of the shape, not exact:

============================  =====  ===========================================================
Status                        Rows   Disposition
============================  =====  ===========================================================
``Filled``                     many  All have ``Filled > 0`` -- become transactions
``Cancelled``                  many  Most with ``Filled == 0`` skipped; **partial fills booked**
``Failed``                     few   :attr:`~app.ingest.adapters.base.SkipReason.FAILED`
============================  =====  ===========================================================

**Execution is decided by ``Filled > 0``, not by ``Status``.** Two failure modes bracket this
adapter, and it has to avoid both:

* Ignoring the disposition entirely books every never-executed order as phantom trades, roughly
  doubling the apparent trading history and inventing positions the user does not hold.
* Filtering on ``Status == 'Filled'`` instead drops the orders that filled *partially* and were
  then cancelled for the remainder. Webull marks those ``Cancelled``, but the filled shares really
  traded, and some of them are disposals in taxable and Roth
  accounts. Losing them removes real taxable events from the ledger.

Counting shares rather than trusting the label handles both.

Quirks handled here, each measured rather than assumed:

* **Partial fills.** ``Filled`` and ``Total Qty`` are distinct columns and quantity always comes from
  ``Filled``. A handful of real rows have ``Filled < Total Qty``, and *all of them carry
  ``Status == 'Cancelled'``* -- orders that filled partially and were cancelled for the remainder.
  Every one of the ``Filled``
  rows has ``Filled == Total Qty``, so the ``Filled``-wins rule never fires on a
  ``Filled`` row and is exercised by tests against a constructed fixture instead. Booking these
  is why the adapter keys on quantity rather than status.
* **``Price`` is the limit, not the execution.** It is ``@``-prefixed with ten decimals
  (``@70.9500000000``); :func:`~app.core.money.parse_decimal` strips the ``@``. Execution price comes
  from ``Avg Price``. In this data the two agree on every filled row (the orders filled at their
  limit), so the distinction is invisible in the totals and would go unnoticed until the first
  marketable or partially-filled order arrives.
* **Timezone-suffixed timestamps.** ``06/15/2026 17:36:18 EDT``; both ``EDT`` and
  ``EST`` appear, because the exports span a DST change. Parsed as timezone-aware and resolved
  against ``America/New_York``. Discarding the suffix misorders the one hour that repeats each
  November, which is exactly the hour where two same-wall-clock trades must be sequenced correctly for
  lot matching. ``executed_at`` is emitted on the *resolved fixed offset* (``UTC-04:00`` named
  ``EDT``) rather than on the ``ZoneInfo`` itself, because PEP 495 makes ``fold`` invisible to
  comparisons between two datetimes sharing one ``tzinfo`` -- see :func:`_pin_offset`. The wall clock,
  the offset and ``tzname()`` are identical either way. (The one visible difference is that PEP 495
  also declares a datetime *inside* the fold unequal to any datetime in another zone, so an emitted
  01:30 EDT does not ``==`` the ``ZoneInfo``-tagged 01:30 despite denoting the same instant; compare
  in UTC if that matters.)
* **``Filled Time`` is empty on unexecuted rows** (cancelled and failed orders). Every filled row has one.
  ``Placed Time`` is the documented fallback and is defensive only -- it has never been needed.
* **Fractional quantities.** A filled row can carry fractional shares such as ``2.00491``. Everything is
  :class:`~decimal.Decimal`.

``sequence`` is the row's position in the source file, which keeps ``txn_id`` stable for rows sharing
a timestamp (Webull emits several per second).
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.core.ids import TransactionSequencer, instrument_id, normalize_symbol
from app.core.models import (
    Account,
    Broker,
    Instrument,
    Transaction,
    TxnAction,
)
from app.core.money import parse_decimal, parse_quantity
from app.ingest.adapters.base import (
    AdapterResult,
    ExportOrder,
    SkippedRow,
    SkipReason,
    UnknownTransactionCode,
)
from app.ingest.provenance import RawFile

__all__ = ["ADAPTER", "WebullAdapter"]


#: Webull timestamps are wall-clock New York with a US Eastern abbreviation appended.
EASTERN = ZoneInfo("America/New_York")

#: Offsets for the abbreviations Webull emits. Used only when the abbreviation disagrees with what
#: :data:`EASTERN` would assign, in which case the broker's stated offset wins over the wall clock.
_ABBREV_OFFSETS: dict[str, dt.timedelta] = {
    "EST": dt.timedelta(hours=-5),
    "EDT": dt.timedelta(hours=-4),
}

_TIMESTAMP_FORMAT = "%m/%d/%Y %H:%M:%S"

#: Exact normalised header of every real export.
_SIGNATURE = (
    "name|symbol|side|status|filled|total qty|price|"
    "avg price|time-in-force|placed time|filled time"
)

#: Columns the parser reads. A file carrying all of these is a Webull order log even if Webull adds a
#: column; a file missing any of them is not, and must not be guessed at.
_REQUIRED_COLUMNS = frozenset(
    {
        "name",
        "symbol",
        "side",
        "status",
        "filled",
        "total qty",
        "price",
        "avg price",
        "placed time",
        "filled time",
    }
)

#: ``Side`` -> canonical action. Webull emits exactly these two across every row. Anything else
#: raises: an unmapped side (a short, an option assignment, a new order type) booked as a guess is a
#: wrong number nobody sees.
_SIDES: dict[str, TxnAction] = {
    "BUY": TxnAction.BUY,
    "SELL": TxnAction.SELL,
}

#: ``Status`` -> skip reason, for the statuses that legitimately produce no transaction. ``Filled``
#: is handled separately because it is the only one that does.
_SKIP_STATUSES: dict[str, SkipReason] = {
    "CANCELLED": SkipReason.CANCELLED,
    "CANCELED": SkipReason.CANCELLED,  # tolerated spelling; the exports use the doubled L
    "FAILED": SkipReason.FAILED,
    # A live order still sitting on the book, not yet executed. Later exports can carry one
    # (``XXXX Buy Working 0/50``). ZERO_FILL is the exact reason -- "accepted but unfilled, not
    # formally cancelled". Mapped rather than executing so it is a recognised code; the ``Filled > 0``
    # rule below still wins, so a working order that has already filled partially books those shares.
    "WORKING": SkipReason.ZERO_FILL,
}

#: Statuses that mean shares changed hands. ``FILLED`` is the whole order; ``PARTIAL FILLED`` is
#: some of it, with the remainder cancelled.
#:
#: Webull used to express a partial execution by marking the order ``Cancelled`` and leaving
#: ``Filled`` non-zero -- the original exports look like that, and the "execution is
#: decided by ``Filled > 0``" rule below exists because of them. Later exports use an
#: explicit ``Partial Filled`` instead, every such row with
#: ``0 < Filled < Total Qty``. The adapter refused the whole file rather than guess, which is the
#: designed behaviour for an unmapped code; this is the mapping it was waiting for.
#:
#: The rule below is unchanged and still decides the outcome: these statuses are *permitted*, and
#: ``Filled > 0`` is what books the row. A ``Partial Filled`` with ``Filled == 0`` would be a
#: contradiction in the source and is skipped as a zero fill rather than trusted.
_EXECUTING_STATUSES: frozenset[str] = frozenset({"FILLED", "PARTIAL FILLED", "PARTIALLY FILLED"})

#: What a ``Symbol`` cell looks like: uppercase, optionally with a class suffix (``BRK-B`` in the real
#: export). Mirrors :data:`app.ingest.adapters.sofi._TICKER_RE` -- both bound the character set a
#: broker-supplied symbol can occupy to something that starts with a letter, which is what stops a
#: symbol shaped like a formula-injection payload (``=cmd|'/C calc'!A1``, or simply a bare ``-`` or
#: ``@``) from ever reaching a ledger row and, downstream, a Form 8949 CSV cell.
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9]{0,5}([.\-][A-Z]{1,2})?$")


def _cell(row: dict[str, str | None], column: str) -> str:
    """Read a column, tolerating both ``None`` and absent keys."""
    return (row.get(column) or "").strip()


def _pin_offset(moment: dt.datetime) -> dt.datetime:
    """Freeze a zone-resolved datetime onto the fixed offset that zone gave it.

    This is not cosmetic. :mod:`zoneinfo` represents the repeated hour of the November changeover
    with the ``fold`` flag, and **PEP 495 specifies that ``fold`` is ignored when two aware datetimes
    sharing the same ``tzinfo`` are compared.** So 01:30 EDT and 01:30 EST, both carried as
    ``ZoneInfo('America/New_York')``, compare *equal* and sort arbitrarily -- exactly the failure that
    reading the timezone suffix was supposed to prevent, reintroduced one layer down where it looks
    like it works.

    Substituting the resolved offset (``UTC-04:00`` named ``EDT``) restores instant-based comparison,
    because datetimes with differing ``tzinfo`` are compared by their UTC equivalents. The wall clock,
    the offset and ``tzname()`` are all unchanged, so the value still reads as Eastern time; only the
    ordering trap is removed.
    """
    offset = moment.utcoffset()
    name = moment.tzname()
    if offset is None or name is None:
        raise ValueError(f"cannot pin the offset of naive datetime {moment!r}")
    return moment.replace(tzinfo=dt.timezone(offset, name), fold=0)


def parse_webull_timestamp(text: str, *, field: str, row_index: int) -> dt.datetime:
    """Parse ``06/15/2026 17:36:18 EDT`` into an aware Eastern datetime.

    The abbreviation is not decoration. On the November changeover the same wall-clock hour occurs
    twice, and ``EDT`` versus ``EST`` is the only thing distinguishing the two instants; attaching the
    zone without consulting it silently collapses them onto the first, misordering trades in the one
    hour a year where ordering is least obvious.

    The abbreviation is reconciled with the zone rather than trusted blindly: the wall time is
    localised to New York via :data:`EASTERN`, and if the resulting abbreviation disagrees, the
    ``fold=1`` reading is tried (which resolves the repeated hour). If it still disagrees -- an
    ``EST`` stamp in July, say, which would mean the export was generated with a different clock --
    the stated offset is taken as the truth and converted, because the instant is what matters
    downstream.

    The returned value carries the resolved Eastern offset as a fixed-offset ``tzinfo`` rather than
    the ``ZoneInfo`` itself; see :func:`_pin_offset` for why that is required for correct ordering.

    Raises:
        ValueError: The field is empty or not in the expected shape.
    """
    parts = text.split()
    if len(parts) != 3:
        raise ValueError(
            f"Webull {field} at row {row_index} is {text!r}; expected "
            "'MM/DD/YYYY HH:MM:SS ZZZ' such as '06/15/2026 17:36:18 EDT'"
        )
    date_part, time_part, abbreviation = parts
    abbreviation = abbreviation.upper()
    if abbreviation not in _ABBREV_OFFSETS:
        raise ValueError(
            f"Webull {field} at row {row_index} carries timezone {abbreviation!r}; "
            f"only {sorted(_ABBREV_OFFSETS)} have been observed. Add it deliberately rather than "
            "dropping the suffix, which would misorder trades across a DST boundary."
        )

    try:
        naive = dt.datetime.strptime(f"{date_part} {time_part}", _TIMESTAMP_FORMAT)
    except ValueError as exc:
        raise ValueError(
            f"Webull {field} at row {row_index} is {text!r}, which is not "
            f"{_TIMESTAMP_FORMAT!r} plus a timezone abbreviation"
        ) from exc

    for fold in (0, 1):
        candidate = naive.replace(tzinfo=EASTERN, fold=fold)
        if candidate.tzname() == abbreviation:
            return _pin_offset(candidate)

    # The abbreviation contradicts the New York calendar. Trust the offset the broker stated and
    # re-express the resulting instant in New York time.
    stated = naive.replace(tzinfo=dt.timezone(_ABBREV_OFFSETS[abbreviation]))
    return _pin_offset(stated.astimezone(EASTERN))


class WebullAdapter:
    """Parses Webull order-history exports into :class:`~app.core.models.Transaction` rows."""

    name = "webull"
    # 1.2.0: `replay_order` -- see `ExportOrder`.
    version = "1.2.0"
    broker = Broker.WEBULL
    #: Verified against the real exports: the earliest trade date carries the highest row index.
    #: Webull is the one broker here that publishes an execution timestamp, so its ordering never
    #: depended on this -- which is exactly why its accounts reconciled to the share against
    #: a broker statement while Robinhood's did not. Declared anyway: the timestamp being
    #: present is a fact about today's export, not a guarantee, and a NULL would silently fall
    #: through to this.
    export_order = ExportOrder.NEWEST_FIRST

    # -- detection ---------------------------------------------------------

    def matches(self, raw: RawFile) -> bool:
        """Whether this is a Webull order log, judged by header alone.

        Mutually exclusive with the other two formats by construction: Robinhood leads with
        ``Activity Date`` and SoFi with ``Date``, and neither has a ``Side``/``Status``/``Filled``
        triple. Detection is never by filename -- the user renames exports freely.
        """
        signature = raw.header_signature()
        if signature == _SIGNATURE:
            return True
        # Tolerate an added or reordered column rather than failing an import outright, but only when
        # every column the parser reads is present.
        columns = {header.strip().lower() for header in raw.header}
        return columns >= _REQUIRED_COLUMNS

    # -- parsing -----------------------------------------------------------

    def parse(self, raw: RawFile, *, account: Account, import_id: str) -> AdapterResult:
        """Convert order rows into transactions, skipping everything that never executed.

        Raises:
            UnknownTransactionCode: ``Side`` or ``Status`` carries a value with no mapping.
            MoneyParseError: A numeric field on an executed row could not be interpreted.
            ValueError: An executed row is missing its symbol or has an unparseable timestamp.
        """
        result = AdapterResult()
        # One per parse: the ordinal counts a row's own duplicates, so it must see every row of
        # this file and only this file.
        sequencer = TransactionSequencer()

        for row_index, row in enumerate(raw.rows):
            status = _cell(row, "Status")
            status_key = status.upper()

            # Validate the status even when it will not decide the outcome: a blank or unrecognised
            # value means a shifted or truncated file, not a row to wave through.
            if status_key not in _EXECUTING_STATUSES and status_key not in _SKIP_STATUSES:
                raise UnknownTransactionCode(self.broker, status, row_index)

            # Execution is decided by shares filled, NOT by status.
            #
            # Webull marks an order 'Cancelled' when it fills partially and the remainder is then
            # cancelled -- but the filled shares really traded and really settled. Partial
            # fills in the real exports carry 'Cancelled', and some of them are disposals in
            # taxable and Roth accounts. Filtering on
            # status alone would drop genuine taxable events out of the ledger entirely.
            filled = parse_quantity(_cell(row, "Filled"), field="Filled") or Decimal(0)

            if filled <= 0:
                reason = _SKIP_STATUSES.get(status_key, SkipReason.ZERO_FILL)
                result.skipped.append(
                    SkippedRow(
                        row_index=row_index,
                        reason=reason,
                        detail=self._skip_detail(row, status),
                    )
                )
                continue

            transaction = self._build_transaction(
                row,
                row_index=row_index,
                total_rows=len(raw.rows),
                account=account,
                import_id=import_id,
                result=result,
                sequencer=sequencer,
            )
            if transaction is not None:
                result.transactions.append(transaction)

        return result

    # -- internals ---------------------------------------------------------

    def _skip_detail(self, row: dict[str, str | None], status: str) -> str:
        """Describe a skipped row.

        Only rows with ``Filled == 0`` reach this, so nothing executed. The detail still records the
        requested quantity, which makes an unexpected skip legible when reconciling counts.
        """
        symbol = _cell(row, "Symbol")
        side = _cell(row, "Side")
        filled = _cell(row, "Filled")
        total = _cell(row, "Total Qty")
        return f"{status} {side} {symbol} {filled}/{total} -- nothing executed"

    def _build_transaction(
        self,
        row: dict[str, str | None],
        *,
        row_index: int,
        total_rows: int,
        account: Account,
        import_id: str,
        result: AdapterResult,
        sequencer: TransactionSequencer,
    ) -> Transaction | None:
        """Build one transaction from a ``Filled`` row, or record a skip and return ``None``."""
        side = _cell(row, "Side")
        action = _SIDES.get(side.upper())
        if action is None:
            raise UnknownTransactionCode(self.broker, side, row_index)

        # Quantity is the executed amount. Total Qty is what was *asked for* and is wrong whenever
        # the two differ.
        quantity = parse_quantity(_cell(row, "Filled"), field="Filled", allow_empty=False)
        assert quantity is not None

        if quantity == 0:
            result.skipped.append(
                SkippedRow(
                    row_index=row_index,
                    reason=SkipReason.ZERO_FILL,
                    detail=(
                        f"status {_cell(row, 'Status')!r} with Filled=0 of "
                        f"{_cell(row, 'Total Qty')!r} {_cell(row, 'Symbol')}"
                    ),
                )
            )
            return None

        symbol = _cell(row, "Symbol")
        if not symbol:
            raise ValueError(
                f"Webull row {row_index} is filled but has no Symbol; the export is malformed and "
                "the trade cannot be attributed to an instrument"
            )
        if not _SYMBOL_RE.match(symbol):
            raise ValueError(
                f"Webull row {row_index} has Symbol {symbol!r}, which does not look like a ticker; "
                "the export may be malformed or corrupted"
            )

        # Avg Price, never Price: Price is the limit the order was placed at.
        price = parse_decimal(_cell(row, "Avg Price"), field="Avg Price", allow_empty=False)
        assert price is not None

        executed_at = self._execution_time(row, row_index=row_index)
        trade_date = executed_at.date()

        # No fee column exists in this export, so the gross trade value is the whole signed cash
        # effect the adapter can see. Sales in particular are overstated by the missing SEC/TAF fees.
        gross = quantity * price
        amount = -gross if action is TxnAction.BUY else gross

        instrument = self._instrument(symbol=symbol, name=_cell(row, "Name"))
        result.instruments.setdefault(instrument.instrument_id, instrument)

        # Ordinal among this row's own duplicates, not its position in the file -- a longer export
        # of the same account moves every row, which used to change every id and re-import the whole
        # history as new. `source_row` keeps the position for provenance.
        txn_id, sequence = sequencer.assign(
            broker=self.broker.value,
            account_id=account.account_id,
            trade_date=trade_date,
            action=action.value,
            symbol=symbol,
            quantity=quantity,
            price=price,
            amount=amount,
        )

        return Transaction(
            txn_id=txn_id,
            import_id=import_id,
            source_row=row_index,
            replay_order=self.export_order.replay_order_for(row_index, total_rows),
            account_id=account.account_id,
            broker=self.broker,
            action=action,
            trade_date=trade_date,
            executed_at=executed_at,
            sequence=sequence,
            symbol=symbol,
            cusip=None,
            instrument_id=instrument.instrument_id,
            quantity=quantity,
            price=price,
            fees=Decimal(0),
            amount=amount,
            description=_cell(row, "Name") or None,
            raw_code=side or None,
        )

    def _execution_time(self, row: dict[str, str | None], *, row_index: int) -> dt.datetime:
        """Execution instant, from ``Filled Time`` with ``Placed Time`` as the documented fallback.

        Every filled row in the real exports has a ``Filled Time``; the fallback exists so a future
        export that omits one degrades to the placement instant instead of failing the whole import.
        """
        filled_time = _cell(row, "Filled Time")
        if filled_time:
            return parse_webull_timestamp(filled_time, field="Filled Time", row_index=row_index)

        placed_time = _cell(row, "Placed Time")
        if placed_time:
            return parse_webull_timestamp(placed_time, field="Placed Time", row_index=row_index)

        raise ValueError(
            f"Webull row {row_index} is filled but carries neither a Filled Time nor a Placed Time; "
            "without an instant the trade cannot be sequenced for lot matching"
        )

    def _instrument(self, *, symbol: str, name: str) -> Instrument:
        """Build the instrument for a ticker.

        ``cusip`` is always ``None`` -- the export has no CUSIP column -- so identity falls back to
        the normalised symbol, which folds Webull's ``BRK-B`` onto Robinhood's ``BRK.B``.
        """
        return Instrument(
            instrument_id=instrument_id(cusip=None, symbol=symbol),
            primary_symbol=normalize_symbol(symbol),
            cusip=None,
            name=name or None,
        )


ADAPTER = WebullAdapter()

"""Robinhood activity-report adapter.

Robinhood exports a full *activity ledger* -- trades, dividends, interest, fees, subscriptions,
internal transfers and ACAT movements all in one file -- which makes it the only one of the three
brokers whose export is self-sufficient for basis tracking. It is also the only one that publishes a
CUSIP, which is why this adapter is the source of instrument identity for the whole system: the
``instruments`` it emits are what later let Webull's bare ``BRK-B`` resolve to Robinhood's ``BRK.B``.

Header::

    Activity Date, Process Date, Settle Date, Instrument, Description, Trans Code, Quantity, Price, Amount

Everything below was measured against three real exports, not assumed:

============================  ==========================================================
Quirk                         Handling
============================  ==========================================================
Embedded newlines             Most ``Description`` fields contain a ``\\n``.
                              :func:`app.ingest.provenance.read_rows` uses ``csv.DictReader``,
                              so the field arrives intact; nothing here may split on lines.
CUSIP inside Description      ``"Example Corp\\nCUSIP: G00000000"``. One
                              symbol->CUSIP pair per instrument. Extracted by :data:`_CUSIP_RE`.
CUSIP-less rows for a symbol  ``SLIP``/``CDIV`` rows carry ``Instrument`` but no CUSIP. A first
                              pass indexes symbol -> CUSIP across the whole file so those rows
                              still resolve to the same ``instrument_id`` as the trades.
Parenthesised negatives       ``($5,250.00)`` -- roughly half of all amounts. Handled by
                              :func:`app.core.money.parse_decimal`.
``S``-suffixed quantities     ``25S``. Appears on ``ACATO`` **and** ``ITRF``
                              -- not only on ACAT rows. ``ACATI`` quantities are
                              plain.
Two footer rows per file      The first is a lone ``""`` (one empty field, the rest ``None``);
                              the second has nine empty fields plus a tenth disclaimer field
                              that ``DictReader`` parks under the ``None`` restkey. Detection
                              therefore inspects the declared header columns only.
No time of day                Dates are ``M/D/YYYY``. ``sequence`` is the row's position in the
                              file, so two identical same-day trades get distinct ``txn_id``\\ s.
============================  ==========================================================

**ACAT groups.** An ACAT is a group of rows sharing an activity date and direction: one row per
transferred position (``Instrument`` set, ``Amount`` empty) plus one or more cash rows
(``Instrument`` empty, ``Amount`` set, ``Description`` carrying ``control_num = ...``), and
sometimes a standalone ``RESIDUAL ACAT IN/OUT`` row that trails the main transfer by weeks. Every
row in a group is emitted as its own transaction -- merging them would destroy the per-symbol
quantities the lot engine needs -- and they are linked by ``transfer_group``, the ``control_num``.
See :func:`_acat_transfer_groups` for how a group with more than one ``control_num`` is resolved.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from typing import Final

from app.core.ids import TransactionSequencer
from app.core.ids import instrument_id as make_instrument_id
from app.core.models import (
    Account,
    Broker,
    Instrument,
    InstrumentKind,
    Transaction,
    TxnAction,
)
from app.core.money import MoneyParseError, parse_decimal, parse_quantity
from app.ingest.adapters.base import (
    AdapterResult,
    ExportOrder,
    SkippedRow,
    SkipReason,
    UnknownTransactionCode,
)
from app.ingest.provenance import RawFile

__all__ = ["ADAPTER", "RobinhoodAdapter"]


# ---------------------------------------------------------------------------
# Column names and header detection
# ---------------------------------------------------------------------------

ACTIVITY_DATE: Final = "Activity Date"
PROCESS_DATE: Final = "Process Date"
SETTLE_DATE: Final = "Settle Date"
INSTRUMENT: Final = "Instrument"
DESCRIPTION: Final = "Description"
TRANS_CODE: Final = "Trans Code"
QUANTITY: Final = "Quantity"
PRICE: Final = "Price"
AMOUNT: Final = "Amount"

_COLUMNS: Final = (
    ACTIVITY_DATE,
    PROCESS_DATE,
    SETTLE_DATE,
    INSTRUMENT,
    DESCRIPTION,
    TRANS_CODE,
    QUANTITY,
    PRICE,
    AMOUNT,
)

#: Exact normalised header of every export seen so far.
HEADER_SIGNATURE: Final = "|".join(column.lower() for column in _COLUMNS)

#: Columns that must be present for the file to be a Robinhood activity report. ``trans code`` is
#: the discriminator: neither Webull (``Name,Symbol,Side,Status,Filled,...``) nor SoFi
#: (``Date,Ticker/Type,Description,Shares,Price,Notes,Amount``) has it, so the two cannot both claim
#: a file even if Robinhood adds a column later.
_REQUIRED_COLUMNS: Final = frozenset(
    {
        "activity date",
        "instrument",
        "description",
        "trans code",
        "quantity",
        "price",
        "amount",
    }
)


# ---------------------------------------------------------------------------
# Transaction codes
# ---------------------------------------------------------------------------

#: Every ``Trans Code`` in the real exports, mapped to a canonical action. A fixed set of codes appears
#: across the three files; an unseen one means the export changed and must raise rather than be
#: guessed at, because an unmapped income row silently disappears from the tax output.
#:
#: .. note::
#:    ``CFIR`` was originally specified as :attr:`~app.core.models.TxnAction.INTEREST`. That was
#:    wrong. Both ``CFIR`` rows in the real exports are described ``"Current Year Contribution"``
#:    -- both are contributions into the Roth account. Those are
#:    retirement contributions, not interest income, and booking contributions as income
#:    would be a genuine tax misstatement. Corrected to ``CASH_IN`` after verifying the row
#:    descriptions directly against the exports.
_ACTION_BY_CODE: Final[dict[str, TxnAction]] = {
    "Buy": TxnAction.BUY,
    "Sell": TxnAction.SELL,
    "ITRF": TxnAction.INTERNAL_TRANSFER,
    "SLIP": TxnAction.STOCK_LENDING_INCOME,
    "ACATO": TxnAction.TRANSFER_OUT,
    "ACATI": TxnAction.TRANSFER_IN,
    "CDIV": TxnAction.DIVIDEND,
    "ABIP": TxnAction.INTEREST,
    "FEE": TxnAction.FEE,
    "GOLD": TxnAction.SUBSCRIPTION_FEE,
    "MTCH": TxnAction.IRA_MATCH,
    "CFIR": TxnAction.CASH_IN,  # "Current Year Contribution" -- see note above
    "INT": TxnAction.INTEREST,
    "MISC": TxnAction.MISC,
    "EMRF": TxnAction.FEE,
}

#: Codes whose direction is carried by the sign of ``Amount`` rather than by the code itself.
#: ``ACH`` covers deposits, withdrawals and withdrawal cancellations; ``RTP`` is an instant bank
#: transfer. Both appear with either sign, so the amount is mandatory for these rows.
_SIGN_DIRECTED_CODES: Final = frozenset({"ACH", "RTP"})

#: Codes recognised by this adapter. Public so a test can pin the set.
KNOWN_CODES: Final = frozenset(_ACTION_BY_CODE) | _SIGN_DIRECTED_CODES

_ACAT_CODES: Final = frozenset({"ACATI", "ACATO"})


# ---------------------------------------------------------------------------
# Field-level parsing
# ---------------------------------------------------------------------------

#: ``"Example Corp\nCUSIP: G00000000"``. CUSIPs here are nine alphanumeric characters and
#: may start with a letter (``G00000000``, ``Q0000L000``), so the class cannot be restricted to
#: digits.
_CUSIP_RE: Final = re.compile(r"CUSIP:\s*([A-Za-z0-9]+)")

#: ``"ACAT IN control_num = 20000000000000, firm_id = 0000, acct_num = ..."``.
_CONTROL_NUM_RE: Final = re.compile(r"control_num\s*=\s*([A-Za-z0-9]+)")

#: What an ``Instrument`` cell looks like: uppercase, optionally with a class suffix (``XYZ.B`` in the
#: real export). Mirrors :data:`app.ingest.adapters.sofi._TICKER_RE` -- both bound the character set a
#: broker-supplied symbol can occupy to something that starts with a letter, which is what stops a
#: symbol shaped like a formula-injection payload (``=cmd|'/C calc'!A1``, or simply a bare ``-`` or
#: ``@``) from ever reaching a ledger row and, downstream, a Form 8949 CSV cell. Unlike SoFi's
#: ``Ticker/Type``, ``Instrument`` is never overloaded with a transaction-type string, so this exists
#: purely as an input boundary rather than to disambiguate a type from a ticker.
_SYMBOL_RE: Final = re.compile(r"^[A-Z][A-Z0-9]{0,5}([.\-][A-Z]{1,2})?$")

_DATE_FORMAT: Final = "%m/%d/%Y"


class RobinhoodRowError(ValueError):
    """A Robinhood row could not be interpreted, with its index so it can be found in the file."""

    def __init__(self, row_index: int, message: str) -> None:
        super().__init__(f"Robinhood row {row_index}: {message}")
        self.row_index = row_index


def _text(value: str | None) -> str:
    """A trimmed field value. ``None`` (a short CSV line) and whitespace both become ``""``."""
    return (value or "").strip()


def _parse_date(raw: str | None, *, field: str, row_index: int) -> dt.date:
    text = _text(raw)
    if not text:
        raise RobinhoodRowError(row_index, f"{field} is empty")
    try:
        return dt.datetime.strptime(text, _DATE_FORMAT).date()
    except ValueError as exc:
        raise RobinhoodRowError(row_index, f"{field} {text!r} is not in M/D/YYYY form") from exc


def _parse_optional_date(raw: str | None, *, field: str, row_index: int) -> dt.date | None:
    if not _text(raw):
        return None
    return _parse_date(raw, field=field, row_index=row_index)


def _extract_cusip(description: str) -> str | None:
    match = _CUSIP_RE.search(description)
    return match.group(1) if match else None


def _extract_control_num(description: str) -> str | None:
    match = _CONTROL_NUM_RE.search(description)
    return match.group(1) if match else None


def _extract_name(description: str) -> str | None:
    """The security name, which is the line above ``CUSIP:``.

    Some real rows carry a description of exactly ``"\\nCUSIP: 00000X000"`` -- the name line is blank.
    Those yield ``None`` rather than an empty-string name.
    """
    if "CUSIP:" not in description:
        return None
    name = description.split("CUSIP:", 1)[0].strip()
    return name or None


def _classify(name: str | None) -> InstrumentKind:
    """Kind inferred from the security name, conservatively.

    Only the explicit ``ETF``/``ETN`` tokens are trusted. Everything else stays ``UNKNOWN`` rather
    than being asserted as ``EQUITY``: an unpriceable pre-IPO vehicle such as SPCX is named like an
    ordinary company, and a wrong claim here is worse than no claim.
    """
    if not name:
        return InstrumentKind.UNKNOWN
    tokens = set(re.findall(r"[A-Za-z]+", name.upper()))
    if "ETN" in tokens:
        return InstrumentKind.ETN
    if "ETF" in tokens:
        return InstrumentKind.ETF
    return InstrumentKind.UNKNOWN


# ---------------------------------------------------------------------------
# Whole-file passes
# ---------------------------------------------------------------------------


def _index_instruments(
    rows: list[dict[str, str | None]],
) -> dict[str, tuple[str | None, str | None]]:
    """Map ``symbol -> (cusip, name)`` across the entire file, before any row is converted.

    Needed because a symbol's CUSIP is only printed on its trade and transfer rows. A ``SLIP`` or
    ``CDIV`` row names the symbol and nothing else, and resolving those by symbol alone would mint a
    second, symbol-keyed ``instrument_id`` for an instrument that already has a CUSIP-keyed one --
    splitting one holding into two. In the real exports every symbol carrying income rows also
    appears on a CUSIP-bearing row, so this pass resolves all 86 of them.
    """
    index: dict[str, tuple[str | None, str | None]] = {}
    for row in rows:
        symbol = _text(row.get(INSTRUMENT))
        if not symbol:
            continue
        description = _text(row.get(DESCRIPTION))
        cusip = _extract_cusip(description)
        name = _extract_name(description)
        known_cusip, known_name = index.get(symbol, (None, None))
        index[symbol] = (known_cusip or cusip, known_name or name)
    return index


def _acat_transfer_groups(rows: list[dict[str, str | None]]) -> dict[int, str]:
    """Map row index -> ``control_num`` for every ACAT row that belongs to a transfer.

    Rows are bucketed by ``(activity date, direction)``. A cash row carries its own ``control_num``
    and keeps it. Position rows carry none, so they inherit the bucket's *primary* control number.

    Picking the primary needs a rule because a bucket is not always one transfer: an
    ``ACATI`` bucket in a real taxable export can hold two cash rows with different control numbers,
    a small fee charge and the transfer itself. The primary is the control number
    of the cash row with the largest absolute amount -- the row that actually moved the positions --
    with ties broken toward the earlier row.
    """
    buckets: dict[tuple[str, str], list[int]] = {}
    own: dict[int, str] = {}
    magnitude: dict[int, Decimal] = {}

    for index, row in enumerate(rows):
        code = _text(row.get(TRANS_CODE))
        if code not in _ACAT_CODES:
            continue
        buckets.setdefault((_text(row.get(ACTIVITY_DATE)), code), []).append(index)
        control_num = _extract_control_num(_text(row.get(DESCRIPTION)))
        if control_num:
            own[index] = control_num
        try:
            amount = parse_decimal(row.get(AMOUNT), field=AMOUNT)
        except MoneyParseError:
            amount = None  # surfaced properly when the row itself is converted
        if amount is not None:
            magnitude[index] = abs(amount)

    assignments: dict[int, str] = {}
    for indexes in buckets.values():
        carriers = [index for index in indexes if index in own]
        primary: str | None = None
        if carriers:
            primary = own[max(carriers, key=lambda i: (magnitude.get(i, Decimal(0)), -i))]
        for index in indexes:
            control_num = own.get(index, primary)
            if control_num:
                assignments[index] = control_num
    return assignments


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class RobinhoodAdapter:
    """Parses a Robinhood activity report into canonical transactions."""

    name = "robinhood"
    # 1.1.0: `replay_order` -- the export is newest-first and was being replayed
    # backwards within each trading day. See `ExportOrder`.
    version = "1.1.0"
    broker = Broker.ROBINHOOD
    #: Verified against the real exports: row 0 is the most recent activity date, and within one
    #: date the rows descend too -- a day of round trips reads sells-then-buys top-down.
    export_order = ExportOrder.NEWEST_FIRST

    def matches(self, raw: RawFile) -> bool:
        """Detection by header signature.

        Exact match on the signature seen in every real export, with a superset fallback so a column
        appended by Robinhood does not silently orphan the file. Mutually exclusive with Webull and
        SoFi: neither declares a ``Trans Code`` column.
        """
        if raw.header_signature() == HEADER_SIGNATURE:
            return True
        columns = {column.strip().lower() for column in raw.header if column}
        return columns >= _REQUIRED_COLUMNS

    def parse(self, raw: RawFile, *, account: Account, import_id: str) -> AdapterResult:
        result = AdapterResult()
        columns = tuple(raw.header) or _COLUMNS
        instrument_index = _index_instruments(raw.rows)
        transfer_groups = _acat_transfer_groups(raw.rows)
        # One per parse, shared by every row of this file: it counts duplicates, so it has to see
        # them all.
        sequencer = TransactionSequencer()

        for index, row in enumerate(raw.rows):
            if _is_footer(row, columns):
                result.skipped.append(
                    SkippedRow(
                        row_index=index,
                        reason=SkipReason.FOOTER,
                        detail="trailing blank/disclaimer row",
                    )
                )
                continue

            transaction = self._build(
                row,
                index=index,
                total_rows=len(raw.rows),
                account=account,
                import_id=import_id,
                instrument_index=instrument_index,
                transfer_groups=transfer_groups,
                result=result,
                sequencer=sequencer,
            )
            result.transactions.append(transaction)

        return result

    # -- internals ---------------------------------------------------------

    def _build(
        self,
        row: dict[str, str | None],
        *,
        index: int,
        total_rows: int,
        account: Account,
        import_id: str,
        instrument_index: dict[str, tuple[str | None, str | None]],
        transfer_groups: dict[int, str],
        result: AdapterResult,
        sequencer: TransactionSequencer,
    ) -> Transaction:
        code = _text(row.get(TRANS_CODE))
        description = _text(row.get(DESCRIPTION))

        amount = parse_decimal(row.get(AMOUNT), field=AMOUNT)
        price = parse_decimal(row.get(PRICE), field=PRICE)
        quantity = parse_quantity(row.get(QUANTITY), field=QUANTITY)

        action = self._resolve_action(code, amount=amount, row=row, row_index=index)

        symbol = _text(row.get(INSTRUMENT)) or None
        if symbol is not None and not _SYMBOL_RE.match(symbol):
            raise RobinhoodRowError(
                index, f"Instrument {symbol!r} does not look like a ticker symbol"
            )
        cusip: str | None = None
        instrument_key: str | None = None
        if symbol:
            cusip, name = instrument_index.get(symbol, (None, None))
            cusip = cusip or _extract_cusip(description)
            instrument_key = make_instrument_id(cusip=cusip, symbol=symbol)
            if instrument_key not in result.instruments:
                result.instruments[instrument_key] = Instrument(
                    instrument_id=instrument_key,
                    primary_symbol=symbol,
                    cusip=cusip,
                    name=name,
                    kind=_classify(name),
                )

        trade_date = _parse_date(row.get(ACTIVITY_DATE), field=ACTIVITY_DATE, row_index=index)
        settle_date = _parse_optional_date(row.get(SETTLE_DATE), field=SETTLE_DATE, row_index=index)

        # Robinhood publishes no time of day, so a pair of identical same-day trades needs a
        # tie-break or the second collides on txn_id and is dropped as a re-import. The sequencer
        # supplies one that counts a row's own duplicates rather than its position in the file --
        # position moves whenever the export gets longer, which changed the id of every previously
        # stored trade. `source_row` below still records the position; that is provenance.
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
            source_row=index,
            replay_order=self.export_order.replay_order_for(index, total_rows),
            account_id=account.account_id,
            broker=self.broker,
            action=action,
            trade_date=trade_date,
            settle_date=settle_date,
            sequence=sequence,
            symbol=symbol,
            cusip=cusip,
            instrument_id=instrument_key,
            quantity=quantity,
            price=price,
            # Robinhood bills fees on their own rows (FEE, GOLD, EMRF) rather than folding them into
            # a trade, so a trade's fee component is always zero here.
            fees=Decimal(0),
            amount=amount,
            description=description or None,
            transfer_group=transfer_groups.get(index),
            raw_code=code,
        )

    def _resolve_action(
        self,
        code: str,
        *,
        amount: Decimal | None,
        row: dict[str, str | None],
        row_index: int,
    ) -> TxnAction:
        if code in _SIGN_DIRECTED_CODES:
            if amount is None:
                raise MoneyParseError(row.get(AMOUNT), f"{AMOUNT} (row {row_index}, code {code})")
            return TxnAction.CASH_OUT if amount < 0 else TxnAction.CASH_IN
        try:
            return _ACTION_BY_CODE[code]
        except KeyError:
            raise UnknownTransactionCode(self.broker, code, row_index) from None


def _is_footer(row: dict[str, str | None], columns: tuple[str, ...]) -> bool:
    """A row with nothing in any declared column.

    Only the declared columns are inspected. The second footer row has ten fields -- nine empty plus
    a legal disclaimer -- and ``csv.DictReader`` parks the overflow under the ``None`` restkey, so a
    check over ``row.values()`` would see the disclaimer and let a phantom transaction through.
    """
    return all(not _text(row.get(column)) for column in columns)


ADAPTER = RobinhoodAdapter()

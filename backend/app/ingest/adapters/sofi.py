"""SoFi activity export adapter.

Header: ``Date, Ticker/Type, Description, Shares, Price, Notes, Amount``

SoFi's export is the smallest of the three in this repo and the most treacherous, because none of its
columns mean what their names suggest:

* **``Ticker/Type`` is overloaded.** A row's second column is *either* a ticker symbol (``SPCX``) *or*
  a transaction type (``Deposit``, ``Withdrawal``, ``Transfer fee``, ``Cash sweep payment``). There is
  no flag distinguishing the two. This module keeps an explicit set of the type strings and treats
  anything else as a ticker -- but only if it is ticker-shaped. An unrecognised value that is not
  ticker-shaped raises :class:`UnknownTransactionCode` rather than being guessed into a symbol.

* **The action lives in ``Description``.** There is no side column. ``Market buy`` / ``Limit buy`` are
  buys, ``Market sell`` / ``Limit sell`` are sells, and ``Account transfer`` is a *position* transfer
  when ``Shares`` is populated.

* **Cancelled orders sit inline and carry a populated ``Amount``.** ``Market buy (Canceled)`` looks
  exactly like an execution: same date, same symbol, a plausible dollar figure in ``Amount``. Some of
  the real rows are cancellations. Booking them inflates cost basis and invents positions
  that were never held, so any description ending ``(Canceled)`` becomes a
  :class:`SkippedRow` with :attr:`SkipReason.CANCELLED`. (SoFi uses the single-L American spelling;
  the double-L spelling is accepted too, defensively.)

* **``Account transfer`` with shares is not a sale.** The real file contains rows like
  ``XXXX, Account transfer, 31.0 shares, amount -1000.00``. Booking that as a sell invents a taxable
  disposal of a position that merely moved brokers. It maps to
  :attr:`~app.core.models.TxnAction.TRANSFER_OUT`, which preserves basis and holding period.

* **Encoding.** The measured export writes the account-number separator in
  ``To SoFi Checking <bullet> 0000``. :func:`app.ingest.provenance.read_rows` already tries
  ``utf-8-sig`` then ``cp1252``, so both a UTF-8 bullet (U+2022) and a raw cp1252 ``0x95`` decode;
  ``tests/fixtures/sofi/withdrawal_cp1252.csv`` pins the fallback path.

No CUSIP is available anywhere in the export, so instruments are keyed on the normalised symbol and
emitted with ``cusip=None``. Robinhood contributes CUSIPs for the symbols it shares, which is what
later reconciles the two.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal

from app.core.ids import TransactionSequencer, instrument_id
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

__all__ = ["ADAPTER", "SoFiAdapter"]


#: Normalised header of the SoFi activity export. Matching is exact so that a
#: hand-normalised export (``Date,Symbol,Side,Qty,...``) -- which also starts
#: with ``Date`` -- cannot be claimed by this adapter.
_HEADER_SIGNATURE = "date|ticker/type|description|shares|price|notes|amount"

#: Values of ``Ticker/Type`` that are transaction types rather than tickers, mapped to the action they
#: imply. All four are measured from the real export. The action comes from the *type* for these rows;
#: the description is validated separately so that an unfamiliar one raises instead of being ignored.
_CASH_TYPE_ACTIONS: dict[str, TxnAction] = {
    "deposit": TxnAction.CASH_IN,
    "withdrawal": TxnAction.CASH_OUT,
    "transfer fee": TxnAction.FEE,
    "cash sweep payment": TxnAction.INTEREST,
}

#: Descriptions observed alongside each non-ticker type. Anything outside this table (or the prefix
#: table below) raises: an unmapped description on a cash row means SoFi changed its vocabulary, and
#: a wrong guess there books cash movement under the wrong action.
_CASH_TYPE_DESCRIPTIONS: dict[str, frozenset[str]] = {
    "deposit": frozenset({"account transfer"}),
    "withdrawal": frozenset({"account transfer"}),
    "transfer fee": frozenset({"brokerage account"}),
    "cash sweep payment": frozenset({"interest/cash sweep"}),
}

#: Descriptions whose tail varies per row and can only be matched by prefix. The measured instance is
#: ``To SoFi Checking <bullet> 0000`` -- the trailing digits are the destination account.
_CASH_TYPE_DESCRIPTION_PREFIXES: dict[str, tuple[str, ...]] = {
    "withdrawal": ("to sofi checking",),
}

#: Descriptions observed on ticker rows, mapped to their action. ``account transfer`` is absent
#: deliberately: its direction depends on the sign of ``Amount``, so it is resolved in code.
_TICKER_ACTIONS: dict[str, TxnAction] = {
    "market buy": TxnAction.BUY,
    "limit buy": TxnAction.BUY,
    "market sell": TxnAction.SELL,
    "limit sell": TxnAction.SELL,
}

_ACCOUNT_TRANSFER = "account transfer"

#: A trailing ``(Canceled)`` (or ``(Cancelled)``) marks an order that never executed. The row still
#: carries an ``Amount``, which is exactly why this must be detected before anything else.
_CANCELLED_RE = re.compile(r"\s*\(cancell?ed\)\s*$", re.IGNORECASE)

#: What a SoFi ticker looks like: uppercase, optionally with a class suffix. Deliberately narrow --
#: its job is to reject a *type* string that this adapter has never seen (``Sweep bonus payment``)
#: rather than to validate a real listing.
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]{0,5}([.\-][A-Z]{1,2})?$")

#: Symbols whose nature cannot be inferred from the export. SoFi supplies no instrument metadata at
#: all, so this table is the only place a kind can come from. It stays small and hand-verified:
#: SPCX is SoFi's pre-IPO SpaceX vehicle, which has no public quote and must surface as explicitly
#: unpriced rather than being silently marked to zero. Symbols absent from the table get
#: :attr:`InstrumentKind.UNKNOWN` -- honest, and resolvable later from a broker that does supply a
#: CUSIP.
_KNOWN_INSTRUMENTS: dict[str, tuple[InstrumentKind, bool, str | None]] = {
    "SPCX": (InstrumentKind.PRIVATE, False, "SpaceX (pre-IPO vehicle)"),
}


def _text(row: dict[str, str | None], column: str) -> str:
    """A column's value as stripped text. Missing and ``None`` both become ``""``."""
    return (row.get(column) or "").strip()


class SoFiAdapter:
    """Parses the SoFi activity export into canonical transactions."""

    name = "sofi"
    # 1.1.0: `replay_order` -- see `ExportOrder`.
    version = "1.1.0"
    broker = Broker.SOFI
    #: Verified against the real export: row 0 is the newest activity date. SoFi publishes
    #: no time of day either, so this is the only ordering signal its rows have.
    export_order = ExportOrder.NEWEST_FIRST

    # -- detection ---------------------------------------------------------

    def matches(self, raw: RawFile) -> bool:
        """Exact header-signature match.

        Exactness is the point. Three other headers in this repo begin with a date-ish column --
        Robinhood's ``Activity Date,...``, Webull's ``Name,Symbol,Side,Status,...`` and a
        hand-normalised ``Date,Symbol,Side,Qty,...`` -- and a loose prefix rule would let this
        adapter swallow the last of those and re-import already-normalised data as if it were raw.
        """
        return raw.header_signature() == _HEADER_SIGNATURE

    # -- parsing -----------------------------------------------------------

    def parse(self, raw: RawFile, *, account: Account, import_id: str) -> AdapterResult:
        result = AdapterResult()
        # One per parse -- the ordinal counts a row's own duplicates within this file.
        sequencer = TransactionSequencer()

        for index, row in enumerate(raw.rows):
            ticker_type = _text(row, "Ticker/Type")
            description = _text(row, "Description")

            # A wholly blank row is a trailing artefact, not data.
            if not any(_text(row, column) for column in raw.header):
                result.skipped.append(
                    SkippedRow(row_index=index, reason=SkipReason.FOOTER, detail="blank row")
                )
                continue

            # Cancellations first: they carry a populated Amount and are otherwise indistinguishable
            # from executions.
            if _CANCELLED_RE.search(description):
                result.skipped.append(
                    SkippedRow(
                        row_index=index,
                        reason=SkipReason.CANCELLED,
                        detail=f"{ticker_type} / {description}",
                    )
                )
                continue

            self._parse_row(
                row,
                index=index,
                total_rows=len(raw.rows),
                ticker_type=ticker_type,
                description=description,
                account=account,
                import_id=import_id,
                result=result,
                sequencer=sequencer,
            )

        return result

    # -- one row -----------------------------------------------------------

    def _parse_row(
        self,
        row: dict[str, str | None],
        *,
        index: int,
        total_rows: int,
        ticker_type: str,
        description: str,
        account: Account,
        import_id: str,
        result: AdapterResult,
        sequencer: TransactionSequencer,
    ) -> None:
        trade_date = self._parse_date(_text(row, "Date"), index)
        quantity = parse_quantity(_text(row, "Shares") or None, field="Shares")
        price = parse_decimal(_text(row, "Price") or None, field="Price")
        amount = parse_decimal(_text(row, "Amount") or None, field="Amount")

        symbol: str | None
        if ticker_type.lower() in _CASH_TYPE_ACTIONS:
            symbol = None
            action = self._cash_action(ticker_type, description, index)
            if amount is None:
                raise MoneyParseError(_text(row, "Amount"), "Amount")
        else:
            symbol = self._as_ticker(ticker_type, index)
            action = self._ticker_action(description, index, quantity=quantity, amount=amount)

        instrument = self._instrument(symbol) if symbol else None

        note = _text(row, "Notes")
        full_description = f"{description} ({note})" if note else description

        # Ordinal among this row's own duplicates rather than its position in the file, so a longer
        # export of the same account does not re-import history under fresh ids. `source_row` keeps
        # the position for provenance.
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

        txn = Transaction(
            txn_id=txn_id,
            import_id=import_id,
            source_row=index,
            replay_order=self.export_order.replay_order_for(index, total_rows),
            account_id=account.account_id,
            broker=self.broker,
            action=action,
            trade_date=trade_date,
            sequence=sequence,
            symbol=symbol,
            cusip=None,
            instrument_id=instrument.instrument_id if instrument else None,
            quantity=quantity,
            price=price,
            amount=amount,
            description=full_description or None,
            # SoFi has no code column; the pair that actually determines the mapping is the
            # overloaded type cell and the description, so that pair is what gets retained.
            raw_code=f"{ticker_type}/{description}",
        )
        result.transactions.append(txn)
        if instrument is not None:
            result.instruments.setdefault(instrument.instrument_id, instrument)

    # -- field interpretation ---------------------------------------------

    def _parse_date(self, text: str, index: int) -> dt.date:
        """SoFi writes ISO ``YYYY-MM-DD``. Anything else is a changed export, not a stray row."""
        try:
            return dt.date.fromisoformat(text)
        except ValueError as exc:
            raise UnknownTransactionCode(self.broker, f"Date={text!r}", index) from exc

    def _as_ticker(self, value: str, index: int) -> str:
        """Interpret an overloaded ``Ticker/Type`` cell that is not a known type.

        Raises rather than assuming, because assuming turns a future ``Sweep bonus payment`` row into
        a phantom holding of a stock called "Sweep bonus payment".
        """
        if not _TICKER_RE.match(value):
            raise UnknownTransactionCode(self.broker, value, index)
        return value

    def _cash_action(self, ticker_type: str, description: str, index: int) -> TxnAction:
        """Action for a non-ticker row. The type decides; the description is validated."""
        key = ticker_type.lower()
        described = description.lower()
        known = _CASH_TYPE_DESCRIPTIONS.get(key, frozenset())
        prefixes = _CASH_TYPE_DESCRIPTION_PREFIXES.get(key, ())
        recognised = described in known or (bool(prefixes) and described.startswith(prefixes))
        if not recognised:
            raise UnknownTransactionCode(self.broker, f"{ticker_type}/{description}", index)
        return _CASH_TYPE_ACTIONS[key]

    def _ticker_action(
        self,
        description: str,
        index: int,
        *,
        quantity: Decimal | None,
        amount: Decimal | None,
    ) -> TxnAction:
        """Action for a row whose ``Ticker/Type`` held a symbol.

        ``Account transfer`` is the one that matters: with ``Shares`` populated it is an ACAT
        position movement, whose direction comes from the sign of ``Amount``. Without shares it is
        cash-only movement attributed to a symbol.
        """
        described = description.lower()
        if described in _TICKER_ACTIONS:
            return _TICKER_ACTIONS[described]

        if described == _ACCOUNT_TRANSFER:
            outbound = amount is not None and amount < 0
            if quantity is not None and quantity != 0:
                return TxnAction.TRANSFER_OUT if outbound else TxnAction.TRANSFER_IN
            return TxnAction.CASH_OUT if outbound else TxnAction.CASH_IN

        raise UnknownTransactionCode(self.broker, description, index)

    def _instrument(self, symbol: str) -> Instrument:
        kind, priceable, name = _KNOWN_INSTRUMENTS.get(
            symbol.upper(), (InstrumentKind.UNKNOWN, True, None)
        )
        return Instrument(
            instrument_id=instrument_id(cusip=None, symbol=symbol),
            primary_symbol=symbol.upper(),
            cusip=None,
            name=name,
            kind=kind,
            is_priceable=priceable,
        )


ADAPTER = SoFiAdapter()

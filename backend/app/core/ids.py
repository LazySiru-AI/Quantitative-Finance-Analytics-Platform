"""Deterministic identifiers.

Re-importing an overlapping broker export must be a no-op, not a source of duplicate lots. That
property comes entirely from these functions: an identical transaction always hashes to the same
``txn_id``, so the second import collides on the primary key and is skipped.

Two rules make the hashes stable:

1. **Canonical formatting.** ``Decimal("50")``, ``Decimal("50.0")`` and the string ``"50.00"`` all
   normalise to the same token. Without this, a broker changing its trailing-zero convention between
   exports would silently duplicate every row.
2. **Explicit field order.** Components are concatenated in a fixed order with a separator that cannot
   appear in the values, so ``("AB", "C")`` and ``("A", "BC")`` cannot collide.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path

__all__ = [
    "TransactionSequencer",
    "canonical_decimal",
    "content_hash",
    "file_sha256",
    "instrument_id",
    "stable_id",
    "transaction_id",
]

#: Unit separator. Not producible by a CSV field, so it cannot be forged by input data.
_SEP = "\x1f"

#: Truncated digest length. 160 bits of a SHA-256 -- collision-free at any plausible ledger size,
#: and short enough to eyeball in a database row.
_ID_CHARS = 40


def canonical_decimal(value: Decimal | int | str | None) -> str:
    """Render a number so that numerically equal inputs produce identical text.

    ``Decimal("50")``, ``Decimal("50.00")`` and ``Decimal("5E+1")`` all yield ``"50"``. Negative zero
    normalises to ``"0"``.
    """
    if value is None:
        return ""
    dec = value if isinstance(value, Decimal) else Decimal(str(value))
    if dec == 0:
        return "0"
    # normalize() collapses trailing zeros but can produce exponent notation for integers
    # (5E+1); quantizing back through a plain string restores positional form.
    normalized = dec.normalize()
    _sign, _digits, exponent = normalized.as_tuple()
    if isinstance(exponent, int) and exponent > 0:
        normalized = normalized.quantize(Decimal(1))
    return format(normalized, "f")


def stable_id(*parts: object, length: int = _ID_CHARS) -> str:
    """Hash an ordered sequence of components into a hex identifier.

    ``Decimal`` and ``date`` components are canonicalised; everything else is stringified. ``None``
    becomes an empty token, which is distinct from the string ``"None"``.
    """
    tokens: list[str] = []
    for part in parts:
        if part is None:
            tokens.append("")
        elif isinstance(part, Decimal):
            tokens.append(canonical_decimal(part))
        elif isinstance(part, date):
            tokens.append(part.isoformat())
        else:
            tokens.append(str(part))
    digest = hashlib.sha256(_SEP.join(tokens).encode("utf-8")).hexdigest()
    return digest[:length]


def transaction_id(
    *,
    broker: str,
    account_id: str,
    trade_date: date,
    action: str,
    symbol: str | None,
    quantity: Decimal | None,
    price: Decimal | None,
    amount: Decimal | None,
    sequence: int = 0,
) -> str:
    """Identity of a single transaction, stable across re-imports.

    ``sequence`` disambiguates rows that are otherwise identical -- two 50-share buys of the same
    symbol at the same price on the same day are genuinely two transactions, not a duplicate.

    **Adapters must obtain it from** :class:`TransactionSequencer`, which assigns it as an ordinal
    among a row's own duplicates. They used to pass the row's position in the source file, and this
    docstring used to say that was "stable as long as the broker keeps emitting rows in the same
    order" -- which is not a property any broker offers. A longer export of the same account moves
    every row, so every id changed and the ledger saw a month of already-stored trades as new. See
    that class for the measurement.

    Callers outside an adapter -- anything recomputing an id to *look up* a row rather than to write
    one -- pass the ``sequence`` already stored on the transaction.
    """
    return stable_id(
        broker,
        account_id,
        trade_date,
        action,
        (symbol or "").upper(),
        quantity,
        price,
        amount,
        sequence,
    )


class TransactionSequencer:
    """Assigns ``sequence`` as an occurrence ordinal among *otherwise-identical* rows.

    ``sequence`` exists to keep two genuinely distinct transactions distinct: two 50-share buys of
    one symbol at one price on one day are two trades, and without a tie-break they collide on
    :func:`transaction_id` and the second is silently discarded as a re-import.

    **It used to be the row's absolute position in the source file, and that broke the store's
    central guarantee.** From ``docs/PLAN.md``: *"the payoff isn't query speed -- it's idempotent
    re-import. Next month's export will overlap heavily with this one, and naive appending silently
    duplicates lots, which corrupts every downstream tax number."* A longer export of the same
    account puts the same trade at a different row, which changed its ``sequence``, which changed
    its ``txn_id`` -- so the ledger saw it as new. Measured on a real ledger: a fresh
    Robinhood export of an account already holding its history shared nearly all of it by
    content and **zero** by id. Importing it would have added every row again and double-counted
    months of trades, through the exact mechanism the design was written to prevent.

    The ordinal here counts only a row's own duplicates, so it is stable across exports: a trade
    with no twin is always ``0`` no matter where it sits in the file, and a pair of identical trades
    is always ``{0, 1}``. ``source_row`` still records the file position -- that is provenance, and
    it is *supposed* to move between exports.

    One instance per parse, and the same instance for every row of that file:

        sequencer = TransactionSequencer()
        txn_id, sequence = sequencer.assign(broker=..., account_id=..., ...)

    :meth:`assign` returns both the id and the sequence, rather than exposing the counter, so the
    key that decides "is this a duplicate" and the key that gets hashed into the id cannot drift
    apart -- they are the same argument list, used once.
    """

    __slots__ = ("_seen",)

    def __init__(self) -> None:
        self._seen: dict[tuple[object, ...], int] = {}

    def assign(
        self,
        *,
        broker: str,
        account_id: str,
        trade_date: date,
        action: str,
        symbol: str | None,
        quantity: Decimal | None,
        price: Decimal | None,
        amount: Decimal | None,
    ) -> tuple[str, int]:
        """``(txn_id, sequence)`` for one row. Call once per emitted transaction, in file order."""
        key = (
            broker,
            account_id,
            trade_date,
            action,
            (symbol or "").upper(),
            None if quantity is None else canonical_decimal(quantity),
            None if price is None else canonical_decimal(price),
            None if amount is None else canonical_decimal(amount),
        )
        sequence = self._seen.get(key, 0)
        self._seen[key] = sequence + 1
        return (
            transaction_id(
                broker=broker,
                account_id=account_id,
                trade_date=trade_date,
                action=action,
                symbol=symbol,
                quantity=quantity,
                price=price,
                amount=amount,
                sequence=sequence,
            ),
            sequence,
        )


def instrument_id(*, cusip: str | None, symbol: str) -> str:
    """Identity of a tradeable instrument.

    Keyed on CUSIP when the broker supplies one, because CUSIP is what reconciles ``BRK.B``
    (Robinhood) with ``BRK-B`` (Webull) and what makes cross-broker wash-sale matching correct.
    Falls back to the normalised symbol otherwise.
    """
    if cusip:
        return stable_id("cusip", cusip.strip().upper())
    return stable_id("symbol", normalize_symbol(symbol))


def normalize_symbol(symbol: str) -> str:
    """Fold broker-specific ticker punctuation into one form.

    Robinhood writes ``BRK.B``; Webull writes ``BRK-B``. Both become ``BRK.B``. This is a fallback for
    instruments with no CUSIP -- it is a heuristic, not an identity guarantee, so CUSIP wins whenever
    it is available.
    """
    return symbol.strip().upper().replace("-", ".")


def content_hash(rows: Iterable[Sequence[str]]) -> str:
    """Hash the logical content of a parsed file, independent of encoding and line endings.

    Used to detect that an export is byte-identical to one already imported so the whole file can be
    skipped. Distinct from :func:`file_sha256`, which hashes raw bytes and therefore changes when a
    broker switches between CRLF and LF without changing any data.
    """
    digest = hashlib.sha256()
    for row in rows:
        digest.update(_SEP.join(row).encode("utf-8"))
        digest.update(b"\x1e")
    return digest.hexdigest()


def file_sha256(path: Path, *, chunk_size: int = 1 << 20) -> str:
    """SHA-256 of a file's raw bytes, read incrementally."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()

"""Decimal parsing and arithmetic for broker-supplied numbers.

Money is never a binary float in this codebase. Every amount, price and share quantity is a
:class:`~decimal.Decimal` from the moment it leaves the CSV until the moment it is rendered.

Parsing is deliberately strict. A value this module cannot interpret raises :class:`MoneyParseError`
rather than returning ``None`` or zero, because a silently mis-parsed amount produces a plausible-looking
wrong number on a tax form. The only input that legitimately yields ``None`` is an empty field.

The formats handled here were measured from real broker exports:

============================  ========================  ==========================================
Format                        Example                   Broker
============================  ========================  ==========================================
Currency with separators      ``$4,851.90``             Robinhood
Parenthesised negative        ``($5,250.00)``           Robinhood
Quantity with ``S`` suffix    ``25S``                   Robinhood ACAT rows
``@``-prefixed price          ``@70.9500000000``        Webull
Plain decimal                 ``159.93``                SoFi, Webull ``Avg Price``
============================  ========================  ==========================================
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Literal, overload

__all__ = [
    "MoneyParseError",
    "parse_decimal",
    "parse_quantity",
    "quantize_money",
]

# Matches an optional sign, digits with optional thousands separators, optional fraction.
_NUMERIC = re.compile(r"^[+-]?\d+(\.\d+)?$")

#: Reporting precision. Applied at output boundaries only -- never to intermediate arithmetic,
#: where premature rounding would accumulate error across a lot-matching chain.
CENTS = Decimal("0.01")


class MoneyParseError(ValueError):
    """A broker field could not be interpreted as a number.

    Raised rather than swallowed: an unparseable amount means the adapter's assumptions about the
    export are wrong, and continuing would book a wrong figure.
    """

    def __init__(self, raw: object, field: str | None = None) -> None:
        where = f" for field {field!r}" if field else ""
        super().__init__(f"cannot parse {raw!r} as a number{where}")
        self.raw = raw
        self.field = field


@overload
def parse_decimal(
    raw: str | int | Decimal | None,
    *,
    field: str | None = ...,
    allow_empty: Literal[False],
) -> Decimal: ...


@overload
def parse_decimal(
    raw: str | int | Decimal | None,
    *,
    field: str | None = ...,
    allow_empty: Literal[True] = ...,
) -> Decimal | None: ...


def parse_decimal(
    raw: str | int | Decimal | None,
    *,
    field: str | None = None,
    allow_empty: bool = True,
) -> Decimal | None:
    """Parse a broker-supplied numeric field into a :class:`Decimal`.

    Overloaded so that ``allow_empty=False`` narrows the return type to a plain :class:`Decimal`.
    That call form raises on an empty field rather than returning ``None``, so callers of a
    mandatory column should not have to prove that to the type checker with an ``assert``.

    Handles currency symbols, thousands separators, parenthesised negatives, ``@`` price prefixes and
    the ``S`` quantity suffix Robinhood puts on ACAT rows.

    Args:
        raw: The field value. ``None`` and whitespace-only strings are treated as empty.
        field: Column name, included in the error message to make failures locatable.
        allow_empty: When ``False``, an empty field raises instead of returning ``None``. Use this for
            columns that must always be populated, so a shifted CSV is caught immediately.

    Returns:
        The parsed value, or ``None`` when the field is empty and ``allow_empty`` is set.

    Raises:
        MoneyParseError: The value is non-empty and not interpretable as a number.
    """
    if raw is None:
        if allow_empty:
            return None
        raise MoneyParseError(raw, field)

    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, int):
        return Decimal(raw)

    text = raw.strip()
    if not text:
        if allow_empty:
            return None
        raise MoneyParseError(raw, field)

    # Parenthesised negative: ($5,250.00). Must be detected before stripping punctuation,
    # otherwise the sign is lost and a debit becomes a credit.
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()

    if text.startswith("@"):  # Webull price fields
        text = text[1:].strip()

    # Robinhood ACAT quantities: "25S", "50S". Only a trailing S, and only after digits.
    if len(text) > 1 and text[-1] in "Ss" and text[-2].isdigit():
        text = text[:-1]

    # Strip the currency symbol, thousands separators, and non-breaking spaces. NBSP is written
    # as an escape so it is visible in source rather than looking like an ordinary space; it
    # appears as a thousands separator in some exports. An ordinary internal space is
    # deliberately NOT stripped -- "1 2" is malformed input, not 12, and the regex below
    # rejects it.
    text = text.replace("$", "").replace(",", "").replace("\u00a0", "").strip()

    # A leading sign may sit outside the currency symbol ("-$100") or inside ("$-100");
    # both survive the strip above, so handle a residual sign here.
    if text.startswith("+"):
        text = text[1:]

    if not text or not _NUMERIC.match(text):
        raise MoneyParseError(raw, field)

    try:
        value = Decimal(text)
    except InvalidOperation as exc:  # pragma: no cover - guarded by the regex above
        raise MoneyParseError(raw, field) from exc

    if negative:
        if value < 0:
            # "(-$5.00)" is ambiguous -- parentheses and an explicit sign both mean negative.
            # Refuse rather than guess which the broker intended.
            raise MoneyParseError(raw, field)
        value = -value

    return value


@overload
def parse_quantity(
    raw: str | int | Decimal | None,
    *,
    field: str | None = ...,
    allow_empty: Literal[False],
) -> Decimal: ...


@overload
def parse_quantity(
    raw: str | int | Decimal | None,
    *,
    field: str | None = ...,
    allow_empty: Literal[True] = ...,
) -> Decimal | None: ...


def parse_quantity(
    raw: str | int | Decimal | None,
    *,
    field: str | None = None,
    allow_empty: bool = True,
) -> Decimal | None:
    """Parse a share quantity.

    Fractional shares are pervasive in this data, so quantities are Decimals like everything else --
    never ints. Negative quantities are permitted: some exports signal a sale by sign rather than by
    a separate action column.

    Overloaded on ``allow_empty`` exactly as :func:`parse_decimal` is; the branch below exists to
    resolve those overloads, not because the two paths differ.
    """
    if allow_empty:
        return parse_decimal(raw, field=field, allow_empty=True)
    return parse_decimal(raw, field=field, allow_empty=False)


def quantize_money(value: Decimal, places: Decimal = CENTS) -> Decimal:
    """Round to a reporting precision using banker's-rounding-free ROUND_HALF_UP.

    Call this at output boundaries only. Rounding intermediate values -- a per-share basis mid-way
    through lot matching, for instance -- accumulates error across a chain of wash-sale adjustments.
    """
    from decimal import ROUND_HALF_UP

    return value.quantize(places, rounding=ROUND_HALF_UP)

"""Money parsing.

The cases here are the literal formats brokers write in their exports (with invented amounts). Each
row of the parametrised table corresponds to something a broker actually writes.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.money import (
    CENTS,
    MoneyParseError,
    parse_decimal,
    parse_quantity,
    quantize_money,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Robinhood currency formatting
        ("$4,851.90", Decimal("4851.90")),
        ("$97.04", Decimal("97.04")),
        ("$40,000.50", Decimal("40000.50")),
        # Robinhood parenthesised negatives, common in real exports. Sign inversion here would turn
        # every debit into a credit.
        ("($5,250.00)", Decimal("-5250.00")),
        ("($0.01)", Decimal("-0.01")),
        ("($7.95)", Decimal("-7.95")),
        # Webull prices: @-prefixed, ten decimal places
        ("@70.9500000000", Decimal("70.9500000000")),
        ("@2103.5000000000", Decimal("2103.5")),
        # Robinhood ACAT quantities carry a trailing S
        ("25S", Decimal(25)),
        ("50S", Decimal(50)),
        # Plain values from SoFi and Webull
        ("159.93", Decimal("159.93")),
        ("-5946.42", Decimal("-5946.42")),
        ("0.02", Decimal("0.02")),
        ("7.95", Decimal("7.95")),
        # Fractional shares
        ("0.000001", Decimal("0.000001")),
        ("1.7539", Decimal("1.7539")),
    ],
)
def test_parses_real_broker_formats(raw: str, expected: Decimal) -> None:
    assert parse_decimal(raw) == expected


def test_parenthesised_negative_keeps_precision() -> None:
    """Trailing zeros are significant for display; parsing must not normalise them away."""
    assert str(parse_decimal("($5,250.00)")) == "-5250.00"


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_empty_is_none_by_default(raw: str | None) -> None:
    assert parse_decimal(raw) is None


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_empty_raises_when_field_is_required(raw: str | None) -> None:
    """Required columns fail loudly, so a shifted CSV is caught at the first row."""
    with pytest.raises(MoneyParseError):
        parse_decimal(raw, field="Amount", allow_empty=False)


@pytest.mark.parametrize(
    "raw",
    [
        "n/a",
        "--",
        "1.2.3",
        "12,34,56.7.8",
        "abc",
        "$",
        "()",
        "1 2",
        "12%",
        "1e5",  # exponent notation is not something a broker emits; treat as suspect
    ],
)
def test_unparseable_raises(raw: str) -> None:
    with pytest.raises(MoneyParseError):
        parse_decimal(raw)


def test_double_negative_is_rejected_rather_than_guessed() -> None:
    """"(-$5.00)" could mean -5 or +5. Refusing is correct; picking one silently is not."""
    with pytest.raises(MoneyParseError):
        parse_decimal("(-$5.00)")


def test_error_names_the_field() -> None:
    with pytest.raises(MoneyParseError, match="Avg Price"):
        parse_decimal("n/a", field="Avg Price")


def test_no_float_contamination() -> None:
    """Decimal must come from text, never via float. 0.1 + 0.2 == 0.3 has to hold exactly."""
    total = parse_decimal("0.1") + parse_decimal("0.2")
    assert total == Decimal("0.3")
    assert str(total) == "0.3"


def test_large_share_count_is_exact() -> None:
    assert parse_quantity("1,234,567.89012345") == Decimal("1234567.89012345")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("1.005"), Decimal("1.01")),  # ROUND_HALF_UP, not banker's rounding
        (Decimal("1.004"), Decimal("1.00")),
        (Decimal("2.675"), Decimal("2.68")),
        (Decimal("-1.005"), Decimal("-1.01")),
    ],
)
def test_quantize_rounds_half_up(value: Decimal, expected: Decimal) -> None:
    """Half-up matches how brokers round on statements; ROUND_HALF_EVEN would drift against them."""
    assert quantize_money(value, CENTS) == expected


def test_passthrough_of_decimal_and_int() -> None:
    assert parse_decimal(Decimal("1.23")) == Decimal("1.23")
    assert parse_decimal(50) == Decimal(50)

"""Deterministic identifiers.

Idempotent re-import rests entirely on these hashes. If ``Decimal("50")`` and ``Decimal("50.00")``
produced different ids, a broker changing its trailing-zero convention between exports would duplicate
every row in the ledger, and every downstream tax figure would double.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.core.ids import (
    canonical_decimal,
    content_hash,
    instrument_id,
    normalize_symbol,
    stable_id,
    transaction_id,
)

BASE = {
    "broker": "robinhood",
    "account_id": "rh-taxable",
    "trade_date": dt.date(2026, 6, 25),
    "action": "sell",
    "symbol": "SOXL",
    "quantity": Decimal(50),
    "price": Decimal("24.10"),
    "amount": Decimal("1205.00"),
}


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (Decimal(50), Decimal("50.00")),
        (Decimal("50.0"), Decimal("5E+1")),
        (Decimal(0), Decimal("-0")),
        (Decimal("0.10"), Decimal("0.1")),
        (Decimal("1234.5000"), Decimal("1234.5")),
    ],
)
def test_numerically_equal_decimals_canonicalise_identically(a: Decimal, b: Decimal) -> None:
    assert canonical_decimal(a) == canonical_decimal(b)


def test_canonical_decimal_avoids_exponent_notation() -> None:
    """normalize() turns 50 into 5E+1; positional form is required or ids differ by input spelling."""
    assert canonical_decimal(Decimal(50)) == "50"
    assert canonical_decimal(Decimal(1000)) == "1000"
    assert "E" not in canonical_decimal(Decimal(1000000))


def test_transaction_id_is_stable_across_equivalent_spellings() -> None:
    first = transaction_id(**BASE)
    second = transaction_id(**{**BASE, "quantity": Decimal("50.00"), "price": Decimal("24.1000")})
    assert first == second


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("account_id", "rh-roth"),
        ("trade_date", dt.date(2026, 6, 26)),
        ("action", "buy"),
        ("symbol", "SOXS"),
        ("quantity", Decimal(51)),
        ("price", Decimal("24.11")),
        ("amount", Decimal("1205.01")),
        ("sequence", 1),
    ],
)
def test_any_material_change_changes_the_id(field: str, value: object) -> None:
    assert transaction_id(**{**BASE, field: value}) != transaction_id(**BASE)


def test_sequence_separates_genuinely_repeated_trades() -> None:
    """Two identical 50-share buys on one day are two transactions, not a duplicate."""
    first = transaction_id(**BASE, sequence=0)
    second = transaction_id(**BASE, sequence=1)
    assert first != second


def test_symbol_case_is_folded() -> None:
    assert transaction_id(**{**BASE, "symbol": "soxl"}) == transaction_id(**BASE)


def test_separator_prevents_field_boundary_collisions() -> None:
    """("AB", "C") and ("A", "BC") must not hash alike."""
    assert stable_id("AB", "C") != stable_id("A", "BC")


def test_none_is_distinct_from_the_string_none() -> None:
    assert stable_id(None) != stable_id("None")


class TestInstrumentIdentity:
    def test_cusip_wins_over_symbol(self) -> None:
        """Robinhood BRK.B and Webull BRK-B are one instrument, and CUSIP is what proves it."""
        rh = instrument_id(cusip="084670702", symbol="BRK.B")
        wb = instrument_id(cusip="084670702", symbol="BRK-B")
        assert rh == wb

    def test_symbol_fallback_normalises_punctuation(self) -> None:
        assert instrument_id(cusip=None, symbol="BRK-B") == instrument_id(cusip=None, symbol="BRK.B")

    def test_different_cusips_are_different_instruments(self) -> None:
        """GOOG and GOOGL share a name and a company but are separate securities."""
        goog = instrument_id(cusip="02079K107", symbol="GOOG")
        googl = instrument_id(cusip="02079K305", symbol="GOOGL")
        assert goog != googl

    def test_cusip_case_and_padding_folded(self) -> None:
        assert instrument_id(cusip=" g25457105 ", symbol="CRDO") == instrument_id(
            cusip="G25457105", symbol="CRDO"
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("BRK-B", "BRK.B"), ("brk.b", "BRK.B"), (" SOXL ", "SOXL")],
)
def test_normalize_symbol(raw: str, expected: str) -> None:
    assert normalize_symbol(raw) == expected


class TestContentHash:
    def test_identical_content_hashes_alike(self) -> None:
        rows = [("a", "b"), ("c", "d")]
        assert content_hash(rows) == content_hash(list(rows))

    def test_row_order_matters(self) -> None:
        assert content_hash([("a", "b"), ("c", "d")]) != content_hash([("c", "d"), ("a", "b")])

    def test_cell_boundaries_matter(self) -> None:
        assert content_hash([("ab", "c")]) != content_hash([("a", "bc")])

"""SoFi adapter tests.

Two layers. The first runs against redacted fixtures in ``tests/fixtures/sofi/`` -- constructed by
hand, with scrambled symbols and amounts, preserving every structural quirk of the real export. The
second runs against the user's actual exports in ``data/`` and is skipped on a fresh clone, because
``data/`` is gitignored.

The fixture layer is the one that must never be weakened. The real-data layer is a regression
signature: **17 rows in, 12 usable, 5 cancelled.**
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.models import (
    Account,
    AccountType,
    Broker,
    InstrumentKind,
    TaxTreatment,
    TxnAction,
)
from app.core.money import MoneyParseError
from app.ingest.adapters.base import (
    AdapterResult,
    BrokerAdapter,
    ExportOrder,
    SkipReason,
    UnknownTransactionCode,
)
from app.ingest.adapters.sofi import ADAPTER, SoFiAdapter
from app.ingest.provenance import RawFile, read_rows

FIXTURES = Path(__file__).parent / "fixtures" / "sofi"

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def sofi_account() -> Account:
    return Account(
        account_id="sofi-taxable",
        broker=Broker.SOFI,
        label="SoFi taxable",
        tax_treatment=TaxTreatment.TAXABLE,
        account_type=AccountType.CASH,
    )


def parse_fixture(name: str) -> AdapterResult:
    raw = read_rows(FIXTURES / name)
    return ADAPTER.parse(raw, account=sofi_account(), import_id="imp-sofi")


def write_csv(path: Path, header: str, *rows: str) -> Path:
    path.write_text("\n".join((header, *rows)) + "\n", encoding="utf-8")
    return path


def by_symbol(result: AdapterResult, symbol: str) -> list:
    return [t for t in result.transactions if t.symbol == symbol]


# ---------------------------------------------------------------------------
# contract and detection
# ---------------------------------------------------------------------------


def test_adapter_satisfies_the_protocol() -> None:
    assert isinstance(ADAPTER, BrokerAdapter)
    assert isinstance(ADAPTER, SoFiAdapter)
    assert ADAPTER.broker is Broker.SOFI
    assert ADAPTER.name == "sofi"
    assert ADAPTER.version


def test_matches_the_sofi_activity_header() -> None:
    raw = read_rows(FIXTURES / "activity_full.csv")
    assert ADAPTER.matches(raw)


@pytest.mark.parametrize(
    ("label", "header"),
    [
        (
            "robinhood",
            '"Activity Date","Process Date","Settle Date","Instrument","Description",'
            '"Trans Code","Quantity","Price","Amount"',
        ),
        (
            "webull",
            "Name,Symbol,Side,Status,Filled,Total Qty,Price,Avg Price,Time-in-Force,"
            "Placed Time,Filled Time",
        ),
        (
            "sofi_processed",
            "Date,Symbol,Side,Qty,Price,Account,Broker,Type,SourceDescription",
        ),
    ],
)
def test_does_not_match_other_formats(tmp_path: Path, label: str, header: str) -> None:
    """Mutual exclusivity, especially against the user's own hand-normalised file.

    ``SoFi_processed taxable.csv`` also starts with ``Date`` and also describes SoFi trades. A loose
    match would re-ingest already-normalised output as if it were a raw export.
    """
    path = write_csv(tmp_path / f"{label}.csv", header)
    assert not ADAPTER.matches(read_rows(path))


def test_does_not_match_a_column_subset_or_superset(tmp_path: Path) -> None:
    missing = write_csv(tmp_path / "short.csv", "Date,Ticker/Type,Description,Shares,Price,Amount")
    extra = write_csv(
        tmp_path / "long.csv", "Date,Ticker/Type,Description,Shares,Price,Notes,Amount,Balance"
    )
    assert not ADAPTER.matches(read_rows(missing))
    assert not ADAPTER.matches(read_rows(extra))


def test_matches_ignores_header_case_and_padding(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "padded.csv", "Date, Ticker/Type ,DESCRIPTION,Shares,Price,Notes,Amount"
    )
    assert ADAPTER.matches(read_rows(path))


# ---------------------------------------------------------------------------
# cancellations -- 5 of 17, each carrying a populated Amount
# ---------------------------------------------------------------------------


def test_every_cancellation_is_skipped_and_none_is_booked() -> None:
    result = parse_fixture("activity_full.csv")

    assert result.skip_counts() == {"cancelled": 5}
    assert result.usable_row_count == 12
    assert len(result.transactions) + len(result.skipped) == 17

    cancelled_rows = {row.row_index for row in result.skipped}
    assert cancelled_rows == {4, 5, 7, 8, 11}
    booked_rows = {txn.source_row for txn in result.transactions}
    assert cancelled_rows.isdisjoint(booked_rows)


def test_cancellation_variants_all_carry_the_cancelled_reason() -> None:
    result = parse_fixture("activity_full.csv")
    assert [row.reason for row in result.skipped] == [SkipReason.CANCELLED] * 5
    details = [row.detail for row in result.skipped]
    assert details == [
        "SPCX / Limit sell (Canceled)",
        "SPCX / Limit sell (Canceled)",
        "SPCX / Market buy (Canceled)",
        "SPCX / Market buy (Canceled)",
        "ZQXT / Market buy (Canceled)",
    ]


def test_a_cancelled_row_with_a_populated_amount_is_still_skipped(tmp_path: Path) -> None:
    """The trap: cancellations look exactly like executions."""
    path = write_csv(
        tmp_path / "cancel.csv",
        "Date,Ticker/Type,Description,Shares,Price,Notes,Amount",
        "2026-02-02,ABCD,Market buy (Canceled),10.0,25.0,,-250.0",
    )
    result = ADAPTER.parse(read_rows(path), account=sofi_account(), import_id="imp")
    assert result.transactions == []
    assert result.skipped[0].reason is SkipReason.CANCELLED


def test_the_only_symbol_appearing_solely_on_cancelled_rows_is_never_an_instrument() -> None:
    """ZQXT appears once, cancelled. A cancelled order is not evidence of a holding."""
    result = parse_fixture("activity_full.csv")
    assert by_symbol(result, "ZQXT") == []
    symbols = {inst.primary_symbol for inst in result.instruments.values()}
    assert "ZQXT" not in symbols
    assert symbols == {"SPCX", "ABCD", "WXYZ"}


@pytest.mark.parametrize("spelling", ["(Canceled)", "(Cancelled)", "(CANCELED)", "(canceled)"])
def test_cancellation_marker_spellings(tmp_path: Path, spelling: str) -> None:
    """SoFi writes the single-L American spelling; the others are accepted defensively."""
    path = write_csv(
        tmp_path / "spelling.csv",
        "Date,Ticker/Type,Description,Shares,Price,Notes,Amount",
        f"2026-02-02,ABCD,Limit sell {spelling},1.0,10.0,,10.0",
    )
    result = ADAPTER.parse(read_rows(path), account=sofi_account(), import_id="imp")
    assert result.transactions == []
    assert result.skipped[0].reason is SkipReason.CANCELLED


def test_a_description_merely_containing_canceled_is_not_treated_as_a_cancellation(
    tmp_path: Path,
) -> None:
    """The marker is a suffix. ``Canceled`` mid-string is a different animal and must not silently
    swallow a real execution -- it raises instead."""
    path = write_csv(
        tmp_path / "midword.csv",
        "Date,Ticker/Type,Description,Shares,Price,Notes,Amount",
        "2026-02-02,ABCD,Canceled order fee reversal,,,,1.0",
    )
    with pytest.raises(UnknownTransactionCode):
        ADAPTER.parse(read_rows(path), account=sofi_account(), import_id="imp")


# ---------------------------------------------------------------------------
# the overloaded Ticker/Type column
# ---------------------------------------------------------------------------


def test_deposit_is_a_type_not_a_ticker() -> None:
    result = parse_fixture("activity_full.csv")
    deposit = next(t for t in result.transactions if t.action is TxnAction.CASH_IN)

    assert deposit.symbol is None
    assert deposit.instrument_id is None
    assert deposit.amount == Decimal("12.5")
    assert "Deposit" not in {inst.primary_symbol for inst in result.instruments.values()}


@pytest.mark.parametrize(
    ("type_value", "description", "amount", "expected"),
    [
        ("Deposit", "Account transfer", "12.5", TxnAction.CASH_IN),
        ("Withdrawal", "To SoFi Checking - 0000", "-1500.25", TxnAction.CASH_OUT),
        ("Transfer fee", "Brokerage account", "-75.0", TxnAction.FEE),
        ("Cash sweep payment", "Interest/Cash sweep", "0.07", TxnAction.INTEREST),
    ],
)
def test_each_non_ticker_type_maps_to_a_cash_action(
    tmp_path: Path, type_value: str, description: str, amount: str, expected: TxnAction
) -> None:
    path = write_csv(
        tmp_path / "cash.csv",
        "Date,Ticker/Type,Description,Shares,Price,Notes,Amount",
        f"2026-02-02,{type_value},{description},,,,{amount}",
    )
    result = ADAPTER.parse(read_rows(path), account=sofi_account(), import_id="imp")
    (txn,) = result.transactions
    assert txn.action is expected
    assert txn.symbol is None
    assert txn.amount == Decimal(amount)


def test_no_cash_row_produces_an_instrument() -> None:
    result = parse_fixture("activity_full.csv")
    cash_actions = {TxnAction.CASH_IN, TxnAction.CASH_OUT, TxnAction.FEE, TxnAction.INTEREST}
    for txn in result.transactions:
        if txn.action in cash_actions:
            assert txn.symbol is None
            assert txn.instrument_id is None


def test_an_unrecognised_non_ticker_shaped_type_raises() -> None:
    with pytest.raises(UnknownTransactionCode) as excinfo:
        parse_fixture("unknown_type.csv")
    assert "Sweep bonus payment" in str(excinfo.value)


def test_an_unrecognised_description_on_a_known_cash_type_raises() -> None:
    with pytest.raises(UnknownTransactionCode) as excinfo:
        parse_fixture("unknown_cash_description.csv")
    assert "Wire from elsewhere" in str(excinfo.value)


def test_an_unrecognised_description_on_a_ticker_row_raises() -> None:
    with pytest.raises(UnknownTransactionCode) as excinfo:
        parse_fixture("unknown_description.csv")
    assert "Fractional rebalance" in str(excinfo.value)


def test_a_malformed_date_raises_rather_than_defaulting(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "baddate.csv",
        "Date,Ticker/Type,Description,Shares,Price,Notes,Amount",
        "06/12/2026,ABCD,Market buy,1.0,10.0,,-10.0",
    )
    with pytest.raises(UnknownTransactionCode):
        ADAPTER.parse(read_rows(path), account=sofi_account(), import_id="imp")


def test_a_cash_row_without_an_amount_raises(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "noamount.csv",
        "Date,Ticker/Type,Description,Shares,Price,Notes,Amount",
        "2026-02-02,Deposit,Account transfer,,,,",
    )
    with pytest.raises(MoneyParseError):
        ADAPTER.parse(read_rows(path), account=sofi_account(), import_id="imp")


# ---------------------------------------------------------------------------
# encoding
# ---------------------------------------------------------------------------


def test_cp1252_withdrawal_row_decodes() -> None:
    """The fixture holds a raw ``0x95`` bullet, which is invalid UTF-8.

    ``read_rows`` must fall back to cp1252 rather than raising or -- far worse -- decoding with
    ``errors="ignore"`` and quietly corrupting the description.
    """
    path = FIXTURES / "withdrawal_cp1252.csv"
    assert b"\x95" in path.read_bytes()
    with pytest.raises(UnicodeDecodeError):
        path.read_bytes().decode("utf-8")

    raw = read_rows(path)
    assert raw.encoding == "cp1252"

    result = ADAPTER.parse(raw, account=sofi_account(), import_id="imp")
    withdrawal = result.transactions[0]
    assert withdrawal.action is TxnAction.CASH_OUT
    assert withdrawal.description == "To SoFi Checking • 0000"
    assert withdrawal.amount == Decimal("-1500.25")


def test_utf8_bullet_variant_also_parses() -> None:
    """The measured export encodes the same separator as UTF-8 U+2022; both shapes must work."""
    result = parse_fixture("activity_full.csv")
    withdrawal = next(t for t in result.transactions if t.action is TxnAction.CASH_OUT)
    assert withdrawal.description == "To SoFi Checking • 0000"


# ---------------------------------------------------------------------------
# position transfers -- the taxable-event trap
# ---------------------------------------------------------------------------


def test_account_transfer_with_shares_is_a_position_transfer_not_a_sale() -> None:
    result = parse_fixture("activity_full.csv")
    transfer = next(t for t in result.transactions if t.action.is_position_transfer)

    assert transfer.action is TxnAction.TRANSFER_OUT
    assert transfer.action is not TxnAction.SELL
    assert transfer.symbol == "SPCX"
    assert transfer.quantity == Decimal("18.0")
    assert transfer.price is None
    assert transfer.amount == Decimal("-3210.0")
    assert transfer.trade_date == dt.date(2026, 6, 19)

    assert not any(
        t.action is TxnAction.SELL and t.trade_date == dt.date(2026, 6, 19)
        for t in result.transactions
    )


def test_positive_account_transfer_with_shares_is_transfer_in() -> None:
    result = parse_fixture("transfer_in.csv")
    inbound = result.transactions[0]
    assert inbound.action is TxnAction.TRANSFER_IN
    assert inbound.quantity == Decimal("6.0")


def test_account_transfer_without_shares_is_cash_not_a_position_move() -> None:
    result = parse_fixture("transfer_in.csv")
    cash = result.transactions[1]
    assert cash.action is TxnAction.CASH_IN
    assert cash.quantity is None


# ---------------------------------------------------------------------------
# actions derived from Description
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Market buy", TxnAction.BUY),
        ("Limit buy", TxnAction.BUY),
        ("Market sell", TxnAction.SELL),
        ("Limit sell", TxnAction.SELL),
    ],
)
def test_side_comes_from_the_description(
    tmp_path: Path, description: str, expected: TxnAction
) -> None:
    path = write_csv(
        tmp_path / "side.csv",
        "Date,Ticker/Type,Description,Shares,Price,Notes,Amount",
        f"2026-02-02,ABCD,{description},3.0,11.0,,-33.0",
    )
    result = ADAPTER.parse(read_rows(path), account=sofi_account(), import_id="imp")
    assert result.transactions[0].action is expected


def test_fixture_trade_actions_and_amounts() -> None:
    result = parse_fixture("activity_full.csv")
    trades = [
        (t.trade_date, t.symbol, t.action, t.quantity, t.price)
        for t in result.transactions
        if t.action.is_trade
    ]
    assert trades == [
        (dt.date(2026, 6, 12), "SPCX", TxnAction.BUY, Decimal("14.0"), Decimal("201.25")),
        (dt.date(2026, 6, 12), "SPCX", TxnAction.BUY, Decimal("4.0"), Decimal("190.0")),
        (dt.date(2026, 5, 18), "ABCD", TxnAction.SELL, Decimal("5.0"), Decimal("100.1")),
        (dt.date(2026, 5, 18), "WXYZ", TxnAction.SELL, Decimal("3.0"), Decimal("220.0")),
        (dt.date(2026, 5, 15), "ABCD", TxnAction.BUY, Decimal("2.0"), Decimal("90.25")),
        (dt.date(2026, 5, 15), "WXYZ", TxnAction.BUY, Decimal("3.0"), Decimal("250.0")),
        (dt.date(2026, 5, 15), "ABCD", TxnAction.BUY, Decimal("4.0"), Decimal("95.0")),
    ]


def test_buys_are_negative_and_sells_positive() -> None:
    result = parse_fixture("activity_full.csv")
    for txn in result.transactions:
        if txn.action is TxnAction.BUY:
            assert txn.amount is not None and txn.amount < 0
        if txn.action is TxnAction.SELL:
            assert txn.amount is not None and txn.amount > 0


# ---------------------------------------------------------------------------
# numeric types, provenance, identity
# ---------------------------------------------------------------------------


def test_every_number_is_a_decimal() -> None:
    result = parse_fixture("activity_full.csv")
    for txn in result.transactions:
        for value in (txn.quantity, txn.price, txn.amount, txn.fees):
            assert value is None or isinstance(value, Decimal)
            assert not isinstance(value, float)


def test_provenance_and_sequence_follow_file_position() -> None:
    result = parse_fixture("activity_full.csv")
    for txn in result.transactions:
        assert txn.import_id == "imp-sofi"
        assert txn.account_id == "sofi-taxable"
        assert txn.broker is Broker.SOFI
        # `sequence` is a duplicate ordinal, not the row position -- see
        # `app.core.ids.TransactionSequencer`. Every row in this fixture is unique, so all are 0.
        assert txn.sequence == 0

    rows = [txn.source_row for txn in result.transactions]
    assert rows == sorted(rows)
    assert rows == [0, 1, 2, 3, 6, 9, 10, 12, 13, 14, 15, 16]


def test_adapter_declares_newest_first_export_order() -> None:
    """SoFi publishes no execution time of day, same as Robinhood, so getting this wrong has the
    same consequence: a same-day round trip replays sell-then-buy. See `ExportOrder`'s docstring."""
    assert ADAPTER.export_order is ExportOrder.NEWEST_FIRST


def test_replay_order_reverses_a_newest_first_same_day_round_trip(tmp_path: Path) -> None:
    """SoFi writes newest-first too: row 0 is the same-day sell (the later event), row 1 is the
    buy. `replay_order` must put the buy first regardless of file position; `source_row` keeps
    recording the literal line."""
    path = write_csv(
        tmp_path / "round_trip.csv",
        "Date,Ticker/Type,Description,Shares,Price,Notes,Amount",
        "2026-02-02,ABCD,Market sell,5.0,20.0,,100.0",
        "2026-02-02,ABCD,Market buy,5.0,20.0,,-100.0",
    )
    result = ADAPTER.parse(read_rows(path), account=sofi_account(), import_id="imp")
    sell, buy = result.transactions
    assert (sell.action, buy.action) == (TxnAction.SELL, TxnAction.BUY)

    assert (sell.source_row, buy.source_row) == (0, 1)
    assert (buy.replay_order, sell.replay_order) == (0, 1)
    assert buy.replay_order < sell.replay_order


def test_transaction_ids_are_unique_and_stable_across_reparse() -> None:
    first = parse_fixture("activity_full.csv")
    second = parse_fixture("activity_full.csv")
    ids = [txn.txn_id for txn in first.transactions]
    assert len(set(ids)) == len(ids)
    assert ids == [txn.txn_id for txn in second.transactions]


def test_identical_rows_at_different_positions_get_distinct_ids(tmp_path: Path) -> None:
    """Two identical buys on the same day are two transactions, not a duplicate."""
    path = write_csv(
        tmp_path / "dupes.csv",
        "Date,Ticker/Type,Description,Shares,Price,Notes,Amount",
        "2026-02-02,ABCD,Market buy,1.0,10.0,,-10.0",
        "2026-02-02,ABCD,Market buy,1.0,10.0,,-10.0",
    )
    result = ADAPTER.parse(read_rows(path), account=sofi_account(), import_id="imp")
    a, b = result.transactions
    assert a.txn_id != b.txn_id


def test_raw_code_retains_the_overloaded_pair() -> None:
    result = parse_fixture("activity_full.csv")
    codes = {txn.raw_code for txn in result.transactions}
    assert "Deposit/Account transfer" in codes
    assert "SPCX/Account transfer" in codes
    assert "Transfer fee/Brokerage account" in codes


# ---------------------------------------------------------------------------
# instruments
# ---------------------------------------------------------------------------


def test_no_instrument_carries_a_cusip() -> None:
    result = parse_fixture("activity_full.csv")
    assert result.instruments
    for inst in result.instruments.values():
        assert inst.cusip is None
    for txn in result.transactions:
        assert txn.cusip is None


def test_spcx_is_private_and_unpriceable() -> None:
    result = parse_fixture("activity_full.csv")
    spcx = next(i for i in result.instruments.values() if i.primary_symbol == "SPCX")
    assert spcx.kind is InstrumentKind.PRIVATE
    assert spcx.is_priceable is False


def test_unknown_symbols_are_not_guessed_into_a_kind() -> None:
    result = parse_fixture("activity_full.csv")
    other = next(i for i in result.instruments.values() if i.primary_symbol == "ABCD")
    assert other.kind is InstrumentKind.UNKNOWN
    assert other.is_priceable is True


def test_transactions_point_at_the_instruments_they_declare() -> None:
    result = parse_fixture("activity_full.csv")
    for txn in result.transactions:
        if txn.symbol:
            assert txn.instrument_id in result.instruments


def test_raw_file_helper_is_used_for_detection(tmp_path: Path) -> None:
    """``matches`` reads only the header, so a header-only file is enough to decide."""
    path = write_csv(
        tmp_path / "headeronly.csv", "Date,Ticker/Type,Description,Shares,Price,Notes,Amount"
    )
    raw = read_rows(path)
    assert isinstance(raw, RawFile)
    assert raw.rows == []
    assert ADAPTER.matches(raw)
    result = ADAPTER.parse(raw, account=sofi_account(), import_id="imp")
    assert result.transactions == [] and result.skipped == []

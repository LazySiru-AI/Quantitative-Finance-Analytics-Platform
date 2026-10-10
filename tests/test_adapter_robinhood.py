"""Robinhood adapter tests.

The fixture in ``tests/fixtures/robinhood/`` is constructed, not copied: symbols, CUSIPs, names,
account numbers and amounts are invented. Only the *structure* is real -- embedded newlines,
parenthesised negatives, ``S``-suffixed quantities, both footer shapes, a multi-``control_num`` ACAT
bucket -- because that structure is what the adapter has to survive.

One test at the bottom runs against the user's real exports in ``data/``. Those are gitignored, so it
skips on a fresh clone rather than failing.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import sample_account

from app.core.ids import instrument_id as make_instrument_id
from app.core.models import Account, Broker, InstrumentKind, TxnAction
from app.core.money import MoneyParseError
from app.ingest.adapters.base import (
    AdapterResult,
    BrokerAdapter,
    ExportOrder,
    SkipReason,
    UnknownTransactionCode,
)
from app.ingest.adapters.robinhood import (
    ADAPTER,
    HEADER_SIGNATURE,
    KNOWN_CODES,
    RobinhoodAdapter,
    RobinhoodRowError,
)
from app.ingest.provenance import RawFile, read_rows

FIXTURES = Path(__file__).parent / "fixtures" / "robinhood"
ACTIVITY_CSV = FIXTURES / "rh_activity.csv"
UNKNOWN_CODE_CSV = FIXTURES / "rh_unknown_code.csv"

#: Rows in the constructed fixture, excluding its two footer rows.
FIXTURE_USABLE_ROWS = 29


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def account() -> Account:
    return sample_account()


@pytest.fixture
def parsed(account: Account) -> AdapterResult:
    return ADAPTER.parse(read_rows(ACTIVITY_CSV), account=account, import_id="imp-rh")


def by_code(result: AdapterResult, code: str) -> list:
    return [txn for txn in result.transactions if txn.raw_code == code]


def only(result: AdapterResult, code: str):
    rows = by_code(result, code)
    assert len(rows) == 1, f"expected exactly one {code} row, got {len(rows)}"
    return rows[0]


def write_csv(path: Path, text: str) -> RawFile:
    path.write_text(text, encoding="utf-8", newline="")
    return read_rows(path)


# ---------------------------------------------------------------------------
# Contract and detection
# ---------------------------------------------------------------------------


def test_adapter_satisfies_the_protocol() -> None:
    assert isinstance(ADAPTER, BrokerAdapter)
    assert isinstance(ADAPTER, RobinhoodAdapter)
    assert ADAPTER.broker is Broker.ROBINHOOD
    assert ADAPTER.name and ADAPTER.version


def test_matches_the_robinhood_header() -> None:
    raw = read_rows(ACTIVITY_CSV)
    assert raw.header_signature() == HEADER_SIGNATURE
    assert ADAPTER.matches(raw) is True


def test_matches_tolerates_an_appended_column(tmp_path: Path) -> None:
    """A column Robinhood adds later must not orphan the file."""
    raw = write_csv(
        tmp_path / "future.csv",
        '"Activity Date","Process Date","Settle Date","Instrument","Description",'
        '"Trans Code","Quantity","Price","Amount","Currency"\n'
        '"1/2/2026","1/2/2026","1/3/2026","","Interest Payment","INT","","","$1.00","USD"\n',
    )
    assert ADAPTER.matches(raw) is True


@pytest.mark.parametrize(
    ("name", "header"),
    [
        (
            "webull",
            (
                '"Name","Symbol","Side","Status","Filled","Total Qty","Price","Avg Price",'
                '"Time-in-Force","Placed Time","Filled Time"\n'
            ),
        ),
        ("sofi", '"Date","Ticker/Type","Description","Shares","Price","Notes","Amount"\n'),
    ],
)
def test_does_not_match_other_brokers(tmp_path: Path, name: str, header: str) -> None:
    """Header signatures must be mutually exclusive or the registry raises AmbiguousAdapter."""
    raw = write_csv(tmp_path / f"{name}.csv", header)
    assert ADAPTER.matches(raw) is False


def test_header_signature_is_normalised_lowercase() -> None:
    assert HEADER_SIGNATURE.startswith("activity date|process date|settle date|instrument")
    assert HEADER_SIGNATURE.endswith("trans code|quantity|price|amount")


# ---------------------------------------------------------------------------
# Row accounting
# ---------------------------------------------------------------------------


def test_row_accounting_is_exact(parsed: AdapterResult) -> None:
    raw = read_rows(ACTIVITY_CSV)
    assert raw.row_count == FIXTURE_USABLE_ROWS + 2
    assert parsed.usable_row_count == FIXTURE_USABLE_ROWS
    assert parsed.skip_counts() == {"footer": 2}


def test_both_footer_shapes_are_skipped_as_footer(parsed: AdapterResult) -> None:
    """One footer is a lone ``""`` (fields arrive as ``None``); the other has nine empty fields plus
    a tenth disclaimer field that DictReader parks under the restkey."""
    raw = read_rows(ACTIVITY_CSV)
    short_footer = raw.rows[-2]
    disclaimer_footer = raw.rows[-1]

    assert short_footer["Process Date"] is None
    assert disclaimer_footer["Process Date"] == ""
    assert None in disclaimer_footer  # csv restkey holding the disclaimer text

    assert [row.reason for row in parsed.skipped] == [SkipReason.FOOTER, SkipReason.FOOTER]
    assert [row.row_index for row in parsed.skipped] == [
        raw.row_count - 2,
        raw.row_count - 1,
    ]


def test_no_transaction_comes_from_a_footer_row(parsed: AdapterResult) -> None:
    skipped_indexes = {row.row_index for row in parsed.skipped}
    assert not skipped_indexes & {txn.source_row for txn in parsed.transactions}


def test_every_transaction_carries_provenance(parsed: AdapterResult) -> None:
    for txn in parsed.transactions:
        assert txn.import_id == "imp-rh"
        assert txn.account_id == "rh-taxable"
        assert txn.broker is Broker.ROBINHOOD
        assert txn.raw_code in KNOWN_CODES
        assert 0 <= txn.source_row < FIXTURE_USABLE_ROWS + 2


# ---------------------------------------------------------------------------
# Transaction code mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "action"),
    [
        ("Buy", TxnAction.BUY),
        ("Sell", TxnAction.SELL),
        ("ITRF", TxnAction.INTERNAL_TRANSFER),
        ("SLIP", TxnAction.STOCK_LENDING_INCOME),
        ("ACATO", TxnAction.TRANSFER_OUT),
        ("ACATI", TxnAction.TRANSFER_IN),
        ("CDIV", TxnAction.DIVIDEND),
        ("ABIP", TxnAction.INTEREST),
        ("FEE", TxnAction.FEE),
        ("GOLD", TxnAction.SUBSCRIPTION_FEE),
        ("MTCH", TxnAction.IRA_MATCH),
        # "Current Year Contribution" -- a Roth contribution, not interest income.
        ("CFIR", TxnAction.CASH_IN),
        ("INT", TxnAction.INTEREST),
        ("MISC", TxnAction.MISC),
        ("EMRF", TxnAction.FEE),
    ],
)
def test_fixed_code_maps_to_action(parsed: AdapterResult, code: str, action: TxnAction) -> None:
    rows = by_code(parsed, code)
    assert rows, f"fixture has no {code} row"
    assert {txn.action for txn in rows} == {action}


def test_fixture_exercises_every_known_code(parsed: AdapterResult) -> None:
    assert {txn.raw_code for txn in parsed.transactions} == set(KNOWN_CODES)


def test_ach_direction_follows_the_amount_sign(parsed: AdapterResult) -> None:
    deposit, withdrawal = by_code(parsed, "ACH")
    assert deposit.action is TxnAction.CASH_IN
    assert deposit.amount == Decimal("1000.00")
    assert withdrawal.action is TxnAction.CASH_OUT
    assert withdrawal.amount == Decimal("-1000.00")


def test_rtp_direction_follows_the_amount_sign(parsed: AdapterResult) -> None:
    rtp = only(parsed, "RTP")
    assert rtp.action is TxnAction.CASH_IN
    assert rtp.amount == Decimal("250.00")


def test_sign_directed_code_without_an_amount_raises(tmp_path: Path, account: Account) -> None:
    """An ACH row with no amount has no knowable direction; guessing would invert a withdrawal."""
    raw = write_csv(
        tmp_path / "blank_ach.csv",
        '"Activity Date","Process Date","Settle Date","Instrument","Description",'
        '"Trans Code","Quantity","Price","Amount"\n'
        '"1/2/2026","1/2/2026","1/3/2026","","ACH Deposit","ACH","","",""\n',
    )
    with pytest.raises(MoneyParseError):
        ADAPTER.parse(raw, account=account, import_id="imp")


def test_unknown_code_raises(account: Account) -> None:
    raw = read_rows(UNKNOWN_CODE_CSV)
    with pytest.raises(UnknownTransactionCode) as excinfo:
        ADAPTER.parse(raw, account=account, import_id="imp")
    assert excinfo.value.code == "XFER"
    assert excinfo.value.broker is Broker.ROBINHOOD
    assert excinfo.value.row_index == 1
    assert "XFER" in str(excinfo.value)


def test_unknown_code_is_not_silently_skipped(account: Account) -> None:
    """Regression guard: the failure mode is a skipped row, not a raised error."""
    raw = read_rows(UNKNOWN_CODE_CSV)
    with pytest.raises(UnknownTransactionCode):
        ADAPTER.parse(raw, account=account, import_id="imp")


# ---------------------------------------------------------------------------
# Symbol validation (A3): Instrument must look like a ticker, never free text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "symbol",
    [
        "=cmd|'/C calc'!A1",  # DDE shell-out
        "+1+1",  # auto-evaluated arithmetic
        "-2+3",
        "@SUM(A1:A9)",
        "not a ticker",
    ],
)
def test_formula_injection_shaped_symbol_raises(
    tmp_path: Path, account: Account, symbol: str
) -> None:
    """A broker-supplied Instrument that does not look like a ticker must be rejected at ingestion,
    not silently accepted and carried downstream to the Form 8949 CSV export -- the file docs/ tells
    the user to open directly in tax software or Excel. Raising here means a bad row is visible
    immediately, matching this adapter's existing convention (RobinhoodRowError on a malformed date)
    of failing loudly rather than skipping or guessing."""
    raw = write_csv(
        tmp_path / "bad_symbol.csv",
        '"Activity Date","Process Date","Settle Date","Instrument","Description",'
        '"Trans Code","Quantity","Price","Amount"\n'
        f'"1/2/2026","1/2/2026","1/3/2026","{symbol}","Buy","Buy","10","$1.00","($10.00)"\n',
    )
    with pytest.raises(RobinhoodRowError, match=re.escape(symbol)):
        ADAPTER.parse(raw, account=account, import_id="imp")


def test_a_legitimate_class_suffixed_symbol_still_parses(
    tmp_path: Path, account: Account
) -> None:
    """Guards against an overly narrow regex: ``XYZ.B``-shaped tickers are real (see the fixture) and
    must keep working."""
    raw = write_csv(
        tmp_path / "class_suffix.csv",
        '"Activity Date","Process Date","Settle Date","Instrument","Description",'
        '"Trans Code","Quantity","Price","Amount"\n'
        '"1/2/2026","1/2/2026","1/3/2026","XYZ.B","Buy","Buy","10","$1.00","($10.00)"\n',
    )
    result = ADAPTER.parse(raw, account=account, import_id="imp")
    assert result.transactions[0].symbol == "XYZ.B"


# ---------------------------------------------------------------------------
# Money and quantity parsing
# ---------------------------------------------------------------------------


def test_parenthesised_negative_keeps_its_sign(parsed: AdapterResult) -> None:
    buys = by_code(parsed, "Buy")
    zqxa = [txn for txn in buys if txn.symbol == "ZQXA"]
    assert len(zqxa) == 2
    for txn in zqxa:
        assert txn.amount == Decimal("-125.00")
        assert txn.amount < 0
    assert only(parsed, "GOLD").amount == Decimal("-5.00")
    assert only(parsed, "EMRF").amount == Decimal("-450.00")


def test_currency_symbol_and_thousands_separator_parse(parsed: AdapterResult) -> None:
    sell = next(txn for txn in by_code(parsed, "Sell") if txn.symbol == "ZQXA")
    assert sell.amount == Decimal("4851.90")
    assert sell.price == Decimal("970.38")
    assert only(parsed, "CFIR").amount == Decimal("2000.00")


def test_amounts_and_prices_are_decimal_never_float(parsed: AdapterResult) -> None:
    for txn in parsed.transactions:
        for value in (txn.amount, txn.price, txn.quantity, txn.fees):
            assert value is None or isinstance(value, Decimal)


def test_s_suffixed_quantity_parses(parsed: AdapterResult) -> None:
    """``25S`` appears on ACATO rows *and*, contrary to a common reading, on ITRF rows."""
    kpto = next(txn for txn in by_code(parsed, "ACATO") if txn.symbol == "KPTO")
    assert kpto.quantity == Decimal(25)

    itrf_position = next(txn for txn in by_code(parsed, "ITRF") if txn.symbol == "MRDN")
    assert itrf_position.quantity == Decimal(30)


def test_acati_quantities_are_plain(parsed: AdapterResult) -> None:
    quantities = {
        txn.symbol: txn.quantity for txn in by_code(parsed, "ACATI") if txn.symbol is not None
    }
    assert quantities == {"VLTR": Decimal(20), "ZQXA": Decimal(3)}


def test_cash_rows_have_no_quantity_and_position_rows_have_no_amount(
    parsed: AdapterResult,
) -> None:
    for txn in by_code(parsed, "ACATO") + by_code(parsed, "ACATI"):
        if txn.symbol:
            assert txn.quantity is not None
            assert txn.amount is None
        else:
            assert txn.quantity is None
            assert txn.amount is not None


def test_fees_are_never_folded_into_a_trade(parsed: AdapterResult) -> None:
    """Robinhood bills fees on their own rows, so a trade's fee component is always zero."""
    assert all(txn.fees == Decimal(0) for txn in parsed.transactions)


# ---------------------------------------------------------------------------
# Dates and sequencing
# ---------------------------------------------------------------------------


def test_dates_parse_from_m_d_yyyy(parsed: AdapterResult) -> None:
    sell = next(txn for txn in by_code(parsed, "Sell") if txn.symbol == "ZQXA")
    assert sell.trade_date == dt.date(2026, 6, 11)
    assert sell.settle_date == dt.date(2026, 6, 12)
    assert sell.executed_at is None  # Robinhood publishes no time of day


def test_malformed_date_raises(tmp_path: Path, account: Account) -> None:
    raw = write_csv(
        tmp_path / "bad_date.csv",
        '"Activity Date","Process Date","Settle Date","Instrument","Description",'
        '"Trans Code","Quantity","Price","Amount"\n'
        '"2026-01-02","2026-01-02","2026-01-03","","Interest Payment","INT","","","$1.00"\n',
    )
    with pytest.raises(RobinhoodRowError):
        ADAPTER.parse(raw, account=account, import_id="imp")


def test_sequence_is_a_duplicate_ordinal_not_the_row_position(parsed: AdapterResult) -> None:
    """`sequence` counts a row's own duplicates; `source_row` keeps the file position.

    It *was* the file position, and that is what broke idempotent re-import: a longer export of the
    same account moves every row, so every id changed and already-stored trades came back as new.
    Almost every row in a real export is unique in (date, action, symbol, quantity, price, amount),
    so almost every sequence is 0 -- which is the point. `source_row` still tracks the file and is
    still ascending, because provenance is supposed to move between exports.
    """
    for txn in parsed.transactions:
        assert txn.sequence >= 0

    assert {txn.sequence for txn in parsed.transactions} == {0, 1}, (
        "this fixture has exactly one duplicated pair; everything else is unique"
    )

    rows = [txn.source_row for txn in parsed.transactions]
    assert rows == sorted(rows)


def test_adapter_declares_newest_first_export_order() -> None:
    """Every real Robinhood export writes newest-first (see the fixture, and `ExportOrder`'s
    docstring for what assuming otherwise cost). `replay_order` below only does the right thing
    because this is set correctly."""
    assert ADAPTER.export_order is ExportOrder.NEWEST_FIRST


def test_replay_order_reverses_a_newest_first_same_day_round_trip(
    tmp_path: Path, account: Account
) -> None:
    """The fixture, and every real Robinhood export, writes newest-first: row 0 is whichever trade
    executed *later* in the day. Robinhood publishes no time of day, so `replay_order` -- not
    `source_row` -- is the only thing that can put the buy before the same-day sell; getting this
    backwards is exactly the bug that replayed sell-then-buy and booked a phantom position (see
    `app.ingest.adapters.base.ExportOrder`).
    """
    raw = write_csv(
        tmp_path / "same_day_round_trip.csv",
        '"Activity Date","Process Date","Settle Date","Instrument","Description",'
        '"Trans Code","Quantity","Price","Amount"\n'
        '"6/12/2026","6/12/2026","6/15/2026","ABCD","Sell","Sell","5","$20.00","$100.00"\n'
        '"6/12/2026","6/12/2026","6/15/2026","ABCD","Buy","Buy","5","$20.00","($100.00)"\n',
    )
    result = ADAPTER.parse(raw, account=account, import_id="imp")
    sell, buy = result.transactions
    assert (sell.action, buy.action) == (TxnAction.SELL, TxnAction.BUY)

    # source_row is untouched provenance: the literal file position, newest (the sell) first.
    assert (sell.source_row, buy.source_row) == (0, 1)
    # replay_order is the corrected chronological rank: the buy replays before the sell.
    assert (buy.replay_order, sell.replay_order) == (0, 1)
    assert buy.replay_order < sell.replay_order


def test_identical_same_day_trades_get_distinct_ids(parsed: AdapterResult) -> None:
    """Two identical same-day buys are two transactions. Without ``sequence`` in the hash the second
    collides with the first and is discarded as a re-import."""
    duplicates = [
        txn
        for txn in by_code(parsed, "Buy")
        if txn.symbol == "ZQXA" and txn.trade_date == dt.date(2026, 6, 12)
    ]
    assert len(duplicates) == 2
    first, second = duplicates
    assert (first.quantity, first.price, first.amount) == (
        second.quantity,
        second.price,
        second.amount,
    )
    assert first.txn_id != second.txn_id


def test_transaction_ids_are_unique(parsed: AdapterResult) -> None:
    ids = [txn.txn_id for txn in parsed.transactions]
    assert len(set(ids)) == len(ids)


def test_reparsing_is_deterministic(account: Account) -> None:
    """Re-importing the same export must be a no-op, which requires identical ids."""
    first = ADAPTER.parse(read_rows(ACTIVITY_CSV), account=account, import_id="imp-a")
    second = ADAPTER.parse(read_rows(ACTIVITY_CSV), account=account, import_id="imp-b")
    assert [t.txn_id for t in first.transactions] == [t.txn_id for t in second.transactions]
    assert set(first.instruments) == set(second.instruments)


# ---------------------------------------------------------------------------
# Descriptions, CUSIPs and instruments
# ---------------------------------------------------------------------------


def test_multiline_description_survives_and_yields_a_cusip(parsed: AdapterResult) -> None:
    raw = read_rows(ACTIVITY_CSV)
    assert "\n" in (raw.rows[0]["Description"] or "")

    buy = by_code(parsed, "Buy")[0]
    assert buy.description is not None
    assert "\n" in buy.description
    assert buy.description.startswith("Zephyr Quantum Analytics")
    assert buy.cusip == "111AAA101"


def test_instruments_are_keyed_by_instrument_id(parsed: AdapterResult) -> None:
    assert set(parsed.instruments) == {
        make_instrument_id(cusip=cusip, symbol=symbol)
        for symbol, cusip in (
            ("ZQXA", "111AAA101"),
            ("VLTR", "222BBB202"),
            ("MRDN", "333CCC303"),
            ("KPTO", "444DDD404"),
            ("XYZ.B", "555EEE505"),
            ("SHNZ", "666FFF606"),
        )
    }
    for key, instrument in parsed.instruments.items():
        assert instrument.instrument_id == key
        assert instrument.cusip is not None


def test_instrument_id_is_cusip_derived_not_symbol_derived(parsed: AdapterResult) -> None:
    """CUSIP is the identity key: it is what reconciles Robinhood ``BRK.B`` with Webull ``BRK-B``."""
    key = make_instrument_id(cusip="555EEE505", symbol="XYZ.B")
    assert key in parsed.instruments
    assert key != make_instrument_id(cusip=None, symbol="XYZ.B")
    # A punctuation-variant ticker resolves to the same instrument when the CUSIP matches.
    assert make_instrument_id(cusip="555EEE505", symbol="XYZ-B") == key


def test_income_rows_resolve_to_the_cusip_keyed_instrument(parsed: AdapterResult) -> None:
    """SLIP and CDIV rows name a symbol but carry no CUSIP. Resolving them by symbol alone would
    mint a second instrument and split one holding in two."""
    expected = make_instrument_id(cusip="111AAA101", symbol="ZQXA")
    for code in ("SLIP", "CDIV"):
        txn = only(parsed, code)
        assert txn.symbol == "ZQXA"
        assert "CUSIP" not in (txn.description or "")
        assert txn.cusip == "111AAA101"
        assert txn.instrument_id == expected


def test_blank_name_line_yields_no_name(parsed: AdapterResult) -> None:
    """Two real rows carry a description of exactly ``"\\nCUSIP: ..."``."""
    key = make_instrument_id(cusip="222BBB202", symbol="VLTR")
    # VLTR's name comes from its ACAT row, not from the name-less Sell row.
    assert parsed.instruments[key].name == "Voltaire Robotics"

    sell = next(txn for txn in by_code(parsed, "Sell") if txn.symbol == "VLTR")
    assert sell.cusip == "222BBB202"
    assert sell.description == "CUSIP: 222BBB202"


def test_instrument_kind_is_inferred_conservatively(parsed: AdapterResult) -> None:
    kinds = {
        parsed.instruments[make_instrument_id(cusip=cusip, symbol=symbol)].kind
        for symbol, cusip in (("MRDN", "333CCC303"),)
    }
    assert kinds == {InstrumentKind.ETF}
    assert (
        parsed.instruments[make_instrument_id(cusip="666FFF606", symbol="SHNZ")].kind
        is InstrumentKind.ETN
    )
    assert (
        parsed.instruments[make_instrument_id(cusip="111AAA101", symbol="ZQXA")].kind
        is InstrumentKind.UNKNOWN
    )


def test_cash_rows_have_no_instrument(parsed: AdapterResult) -> None:
    for code in ("INT", "ABIP", "GOLD", "MISC", "EMRF", "MTCH", "CFIR", "RTP"):
        txn = only(parsed, code)
        assert txn.symbol is None
        assert txn.instrument_id is None
        assert txn.cusip is None


# ---------------------------------------------------------------------------
# ACAT groups
# ---------------------------------------------------------------------------


def test_acat_out_group_shares_one_transfer_group(parsed: AdapterResult) -> None:
    group = by_code(parsed, "ACATO")
    assert len(group) == 3  # two positions plus the cash row
    assert {txn.transfer_group for txn in group} == {"20260610000111"}
    assert {txn.symbol for txn in group} == {"KPTO", "XYZ.B", None}


def test_acat_in_group_links_positions_to_the_largest_cash_row(parsed: AdapterResult) -> None:
    """A date bucket can hold more than one control_num: in a real taxable export an ACATI bucket
    can carry a small charge alongside the main cash transfer. Position rows follow the cash row
    that actually moved them; each cash row keeps its own number."""
    bucket = [txn for txn in by_code(parsed, "ACATI") if txn.trade_date == dt.date(2026, 4, 6)]
    assert len(bucket) == 4

    positions = [txn for txn in bucket if txn.symbol]
    assert {txn.transfer_group for txn in positions} == {"20260970000333"}

    charge = next(txn for txn in bucket if txn.amount == Decimal("-7.95"))
    assert charge.transfer_group == "20260970000222"
    principal = next(txn for txn in bucket if txn.amount == Decimal("9876.54"))
    assert principal.transfer_group == "20260970000333"


def test_residual_acat_row_keeps_its_own_control_num(parsed: AdapterResult) -> None:
    residual = next(
        txn for txn in by_code(parsed, "ACATI") if txn.trade_date == dt.date(2026, 2, 10)
    )
    assert residual.transfer_group == "20260410000444"
    assert residual.amount == Decimal("1.06")
    assert residual.symbol is None


def test_acat_fee_row_is_a_fee_not_part_of_the_transfer(parsed: AdapterResult) -> None:
    """``ACAT OUT FEE`` rows carry code ``FEE`` and sit inside the ACAT date bucket, but they are
    fees, not transfers, and must not inherit the transfer group."""
    fees = by_code(parsed, "FEE")
    assert {txn.action for txn in fees} == {TxnAction.FEE}
    assert all(txn.transfer_group is None for txn in fees)


def test_non_acat_rows_have_no_transfer_group(parsed: AdapterResult) -> None:
    for txn in parsed.transactions:
        if txn.raw_code not in {"ACATI", "ACATO"}:
            assert txn.transfer_group is None


def test_transfers_are_not_trades(parsed: AdapterResult) -> None:
    """The whole point: an ACAT out is not a sale and an ACAT in is not an acquisition. Booking them
    as trades invents a taxable event and restarts the holding period."""
    transfers = by_code(parsed, "ACATI") + by_code(parsed, "ACATO")
    for txn in transfers:
        assert not txn.action.is_trade
        assert txn.action.is_position_transfer

    internal = by_code(parsed, "ITRF")
    for txn in internal:
        assert txn.action is TxnAction.INTERNAL_TRANSFER
        assert not txn.action.is_trade
        assert not txn.action.is_position_transfer


def test_trades_are_complete(parsed: AdapterResult) -> None:
    for txn in by_code(parsed, "Buy") + by_code(parsed, "Sell"):
        assert txn.action.is_trade
        assert txn.symbol
        assert txn.quantity and txn.quantity > 0
        assert txn.price is not None
        assert txn.amount is not None
    assert all(txn.amount < 0 for txn in by_code(parsed, "Buy"))  # type: ignore[operator]
    assert all(txn.amount > 0 for txn in by_code(parsed, "Sell"))  # type: ignore[operator]

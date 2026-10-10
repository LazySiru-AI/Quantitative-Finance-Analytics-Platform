"""Webull order-log adapter.

The tests that matter most here are the ones about rows that must *not* become transactions. Webull's
export is an order log: 44.7% of its rows are cancellations and failures that carry a symbol, a side,
a quantity and a price, and look exactly like executions. An adapter that loses the status filter
produces a plausible ledger with roughly twice the real trading history, and nothing downstream can
tell.

Fixtures in ``tests/fixtures/webull/`` are constructed, never copied: symbols and amounts are
invented, and only the structural quirks are reproduced.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.ids import instrument_id, normalize_symbol
from app.core.models import (
    Account,
    AccountType,
    Broker,
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
from app.ingest.adapters.webull import (
    ADAPTER,
    EASTERN,
    WebullAdapter,
    parse_webull_timestamp,
)
from app.ingest.provenance import RawFile, read_rows

FIXTURES = Path(__file__).parent / "fixtures" / "webull"

WEBULL_HEADER = (
    "Name,Symbol,Side,Status,Filled,Total Qty,Price,Avg Price,"
    "Time-in-Force,Placed Time,Filled Time"
)
ROBINHOOD_HEADER = (
    "Activity Date,Process Date,Settle Date,Instrument,Description,"
    "Trans Code,Quantity,Price,Amount"
)
SOFI_HEADER = "Date,Ticker/Type,Description,Shares,Price,Notes,Amount"

#: Row indices within ``orders_sample.csv``, zero-based and excluding the header. Named so a failure
#: says which quirk broke rather than which line number moved.
ROW_PLAIN_BUY = 0
ROW_AVG_PRICE_BELOW_LIMIT = 1
ROW_CANCELLED_UNFILLED = 2
ROW_CANCELLED_PARTIAL = 3
ROW_FAILED = 4
ROW_HYPHEN_TICKER = 5
ROW_FRACTIONAL = 6
ROW_PARTIAL_FILL = 7
ROW_DUPLICATE_A = 8
ROW_DUPLICATE_B = 9
ROW_NO_FILLED_TIME = 10


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def account() -> Account:
    return Account(
        account_id="wb-cash",
        broker=Broker.WEBULL,
        label="Webull Cash",
        tax_treatment=TaxTreatment.TAXABLE,
        account_type=AccountType.CASH,
    )


@pytest.fixture
def adapter() -> WebullAdapter:
    return WebullAdapter()


def parse_fixture(name: str, adapter: WebullAdapter, account: Account) -> AdapterResult:
    raw = read_rows(FIXTURES / name)
    return adapter.parse(raw, account=account, import_id="imp-webull")


@pytest.fixture
def sample(adapter: WebullAdapter, account: Account) -> AdapterResult:
    return parse_fixture("orders_sample.csv", adapter, account)


def write_csv(tmp_path: Path, name: str, *lines: str) -> RawFile:
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return read_rows(path)


# ---------------------------------------------------------------------------
# Contract and detection
# ---------------------------------------------------------------------------


def test_module_exposes_a_singleton_adapter() -> None:
    assert isinstance(ADAPTER, WebullAdapter)
    assert isinstance(ADAPTER, BrokerAdapter)
    assert ADAPTER.name == "webull"
    assert ADAPTER.broker is Broker.WEBULL
    assert ADAPTER.version


def test_matches_the_webull_header(adapter: WebullAdapter, tmp_path: Path) -> None:
    raw = write_csv(tmp_path, "renamed_by_the_user.csv", WEBULL_HEADER)
    assert adapter.matches(raw) is True


def test_matches_is_case_and_whitespace_insensitive(
    adapter: WebullAdapter, tmp_path: Path
) -> None:
    raw = write_csv(tmp_path, "shouty.csv", " NAME , Symbol ,SIDE,Status,FILLED,Total Qty,"
                                            "Price,AVG PRICE,Time-in-Force,Placed Time,Filled Time")
    assert adapter.matches(raw) is True


@pytest.mark.parametrize(
    ("label", "header"),
    [("robinhood", ROBINHOOD_HEADER), ("sofi", SOFI_HEADER)],
)
def test_does_not_claim_other_brokers(
    adapter: WebullAdapter, tmp_path: Path, label: str, header: str
) -> None:
    """Detection must be mutually exclusive; the registry treats two matches as a fatal bug."""
    raw = write_csv(tmp_path, f"{label}.csv", header)
    assert adapter.matches(raw) is False


def test_does_not_claim_a_file_missing_a_read_column(
    adapter: WebullAdapter, tmp_path: Path
) -> None:
    """A near-miss header must fail rather than be guessed at -- ``Avg Price`` is the exec price."""
    without_avg_price = WEBULL_HEADER.replace(",Avg Price", "")
    raw = write_csv(tmp_path, "truncated.csv", without_avg_price)
    assert adapter.matches(raw) is False


# ---------------------------------------------------------------------------
# The status filter: the thing that must never regress
# ---------------------------------------------------------------------------


def test_fixture_row_counts(sample: AdapterResult) -> None:
    # 9, not 8: the partially-filled-then-cancelled row is booked for the shares that executed.
    assert len(sample.transactions) == 9
    assert sample.usable_row_count == 9
    assert sample.skip_counts() == {"cancelled": 1, "failed": 1}


def test_unfilled_cancellation_is_skipped_not_booked(sample: AdapterResult) -> None:
    """A cancellation with nothing executed is a phantom trade if booked."""
    cancelled = [row for row in sample.skipped if row.reason is SkipReason.CANCELLED]
    assert {row.row_index for row in cancelled} == {ROW_CANCELLED_UNFILLED}
    assert ROW_CANCELLED_UNFILLED not in {t.source_row for t in sample.transactions}


def test_failed_rows_are_skipped_with_the_failed_reason(sample: AdapterResult) -> None:
    failed = [row for row in sample.skipped if row.reason is SkipReason.FAILED]
    assert [row.row_index for row in failed] == [ROW_FAILED]
    assert not [t for t in sample.transactions if t.symbol == "WRLD"]


def test_partially_filled_then_cancelled_row_is_booked_for_what_executed(
    sample: AdapterResult,
) -> None:
    """All five real ``Filled < Total Qty`` rows carry ``Status == 'Cancelled'``.

    They executed part of the order and were cancelled for the remainder. Those shares really
    traded, so they must reach the ledger -- and at the executed quantity, not the requested one.
    Filtering on status alone would have dropped real disposals from the ledger.
    """
    (txn,) = [t for t in sample.transactions if t.source_row == ROW_CANCELLED_PARTIAL]
    assert txn.quantity == Decimal(44), "must book what filled, not the 50 requested"
    assert txn.symbol == "QQAB"


def test_zero_fill_on_a_non_cancelled_row_is_skipped(
    adapter: WebullAdapter, account: Account
) -> None:
    result = parse_fixture("zero_fill.csv", adapter, account)
    assert result.transactions == []
    assert [row.reason for row in result.skipped] == [SkipReason.ZERO_FILL]


class TestPartialFilledStatus:
    """Webull's explicit ``Partial Filled``, which the adapter had never seen.

    The original exports expressed a partial execution by marking the order ``Cancelled`` with a
    non-zero ``Filled`` -- all five look like that, and the "execution is decided by ``Filled > 0``"
    rule exists because of them. Exports pulled on 2026-08-14 use ``Partial Filled`` instead: four
    rows across three files, every one with ``0 < Filled < Total Qty``.

    The adapter refused all three files outright with ``UnknownTransactionCode``. That is the
    designed response to an unmapped code and it worked exactly as intended -- an unrecognised
    status is a shifted file or a changed format, not a row to wave through -- but it meant three
    real exports could not be imported at all.
    """

    def test_a_partial_filled_row_books_what_filled(
        self, adapter: WebullAdapter, account: Account
    ) -> None:
        result = parse_fixture("partial_filled_status.csv", adapter, account)
        sells = [t for t in result.transactions if t.symbol == "AAAA"]

        assert len(sells) == 1
        assert sells[0].quantity == Decimal(7), "the 7 that filled, not the 30 requested"
        assert sells[0].action is TxnAction.SELL

    def test_every_executing_status_is_booked(
        self, adapter: WebullAdapter, account: Account
    ) -> None:
        """Two partial fills and one whole fill -- three real trades in the fixture."""
        result = parse_fixture("partial_filled_status.csv", adapter, account)
        assert {t.symbol for t in result.transactions} == {"AAAA", "BBBB", "CCCC"}
        assert len(result.transactions) == 3

    def test_a_partial_filled_row_that_filled_nothing_is_still_a_zero_fill(
        self, adapter: WebullAdapter, account: Account
    ) -> None:
        """The status is permitted; ``Filled > 0`` is what books the row.

        A ``Partial Filled`` with ``Filled == 0`` contradicts itself in the source, and the honest
        response is to skip it rather than trust the label over the quantity. This is the case that
        would silently invent a zero-share trade if the mapping had been written to treat the status
        as the decision.
        """
        result = parse_fixture("partial_filled_status.csv", adapter, account)
        skips = {row.reason for row in result.skipped}

        assert "DDDD" not in {t.symbol for t in result.transactions}
        assert SkipReason.ZERO_FILL in skips
        assert SkipReason.CANCELLED in skips

    def test_a_working_order_is_skipped_and_a_filled_part_of_one_is_booked(
        self, adapter: WebullAdapter, account: Account, tmp_path: Path
    ) -> None:
        """``Working`` is a live order at export time: unfilled is a zero fill, never a file failure.

        Mapped once on 2026-09-09 and lost again before 2026-10-07, which made ``Webull (11)`` fail
        the whole file on one resting order. ``Filled > 0`` still books any part of it that traded.
        """
        raw = write_csv(
            tmp_path,
            "working.csv",
            "Name,Symbol,Side,Status,Filled,Total Qty,Price,Avg Price,Time-in-Force,Placed Time,Filled Time",
            "Fund,AAAA,Buy,Working,0,50,@28.30,,DAY,09/09/2026 17:12:15 EDT,",
            "Fund,BBBB,Buy,Working,10,50,@5.00,5.00,DAY,09/09/2026 17:13:15 EDT,09/09/2026 17:13:20 EDT",
        )
        result = adapter.parse(raw, account=account, import_id="imp-webull")

        assert [t.symbol for t in result.transactions] == ["BBBB"]
        assert result.transactions[0].quantity == Decimal(10)
        assert [row.reason for row in result.skipped] == [SkipReason.ZERO_FILL]

    def test_an_unknown_status_still_refuses_the_file(
        self, adapter: WebullAdapter, account: Account, tmp_path: Path
    ) -> None:
        """Widening the allowlist must not have widened it to anything.

        The reason those three exports failed loudly is the property worth keeping: an unmapped
        status means the export changed or the file is shifted, and guessing produces a wrong tax
        figure nobody notices.
        """
        raw = write_csv(
            tmp_path,
            "unknown.csv",
            "Name,Symbol,Side,Status,Filled,Total Qty,Price,Avg Price,Time-in-Force,Placed Time,Filled Time",
            "Fund,AAAA,Buy,Queued,0,10,@1.00,,DAY,01/02/2026 10:00:00 EST,",
        )
        with pytest.raises(UnknownTransactionCode, match="Queued"):
            adapter.parse(raw, account=account, import_id="imp-webull")


# ---------------------------------------------------------------------------
# Quantity and price
# ---------------------------------------------------------------------------


def test_partial_fill_uses_filled_not_total_qty(sample: AdapterResult) -> None:
    """``Total Qty`` is what was asked for; only ``Filled`` was executed."""
    txn = by_row(sample, ROW_PARTIAL_FILL)
    assert txn.quantity == Decimal(7)
    assert txn.quantity != Decimal(20)
    # A Total-Qty read would produce 20 x 54.50 = 1090.00 instead.
    assert txn.amount == Decimal("381.500")


def test_avg_price_is_used_not_the_at_prefixed_limit_price(sample: AdapterResult) -> None:
    """``Price`` is the limit the order was placed at, and is ``@``-prefixed."""
    txn = by_row(sample, ROW_AVG_PRICE_BELOW_LIMIT)
    assert txn.price == Decimal("30.2500000000")
    assert txn.price != Decimal(31)
    assert txn.amount == Decimal("121.0000000000")


def test_fractional_quantities_survive_as_decimal(sample: AdapterResult) -> None:
    txn = by_row(sample, ROW_FRACTIONAL)
    assert txn.quantity == Decimal("3.14159")
    assert isinstance(txn.quantity, Decimal)
    assert isinstance(txn.amount, Decimal)


def test_amount_is_signed_by_side(sample: AdapterResult) -> None:
    buy = by_row(sample, ROW_PLAIN_BUY)
    assert buy.action is TxnAction.BUY
    assert buy.amount == Decimal("-125.0000000000")
    assert buy.amount < 0

    sell = by_row(sample, ROW_AVG_PRICE_BELOW_LIMIT)
    assert sell.action is TxnAction.SELL
    assert sell.amount > 0


def test_fees_are_zero_because_the_export_has_no_fee_column(sample: AdapterResult) -> None:
    """Zero here means "unknown", not "none charged" -- see the module docstring."""
    assert all(txn.fees == Decimal(0) for txn in sample.transactions)


def test_amounts_are_never_float(sample: AdapterResult) -> None:
    for txn in sample.transactions:
        for value in (txn.quantity, txn.price, txn.amount, txn.fees):
            assert not isinstance(value, float)


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------


def test_edt_timestamp_is_timezone_aware_and_eastern(sample: AdapterResult) -> None:
    txn = by_row(sample, ROW_PLAIN_BUY)
    assert txn.executed_at is not None
    assert txn.executed_at.tzinfo is not None
    assert txn.executed_at.utcoffset() == dt.timedelta(hours=-4)
    assert txn.executed_at.tzname() == "EDT"
    assert txn.executed_at == dt.datetime(2026, 6, 15, 17, 36, 26, tzinfo=EASTERN)


def test_est_timestamp_parses_with_the_winter_offset(sample: AdapterResult) -> None:
    txn = by_row(sample, ROW_HYPHEN_TICKER)
    assert txn.executed_at is not None
    assert txn.executed_at.utcoffset() == dt.timedelta(hours=-5)
    assert txn.executed_at.tzname() == "EST"


def test_trade_date_is_the_new_york_date_of_the_filled_time(sample: AdapterResult) -> None:
    assert by_row(sample, ROW_PLAIN_BUY).trade_date == dt.date(2026, 6, 15)
    assert by_row(sample, ROW_HYPHEN_TICKER).trade_date == dt.date(2026, 2, 19)


def test_placed_time_is_the_fallback_when_filled_time_is_empty(sample: AdapterResult) -> None:
    txn = by_row(sample, ROW_NO_FILLED_TIME)
    assert txn.executed_at == dt.datetime(2026, 1, 20, 4, 33, 49, tzinfo=EASTERN)
    assert txn.trade_date == dt.date(2026, 1, 20)


def test_dst_boundary_pair_orders_correctly(adapter: WebullAdapter, account: Account) -> None:
    """01:30 happens twice on 2026-11-01; only the EDT/EST suffix distinguishes the two instants.

    Discarding the suffix collapses them onto the same instant and leaves the ordering to chance,
    which is precisely the hour where two same-wall-clock trades must sequence correctly.
    """
    result = parse_fixture("dst_boundary.csv", adapter, account)
    first, second = result.transactions
    assert first.executed_at is not None
    assert second.executed_at is not None

    assert first.executed_at.tzname() == "EDT"
    assert second.executed_at.tzname() == "EST"
    assert first.executed_at.utcoffset() == dt.timedelta(hours=-4)
    assert second.executed_at.utcoffset() == dt.timedelta(hours=-5)

    # Same wall clock, one hour apart in real time, and in the right order.
    assert first.executed_at.replace(tzinfo=None) == second.executed_at.replace(tzinfo=None)
    assert second.executed_at - first.executed_at == dt.timedelta(hours=1)
    assert first.executed_at < second.executed_at
    assert sorted([second, first], key=lambda t: t.executed_at) == [first, second]  # type: ignore[arg-type,return-value]


def test_dst_boundary_pair_is_not_carried_on_a_fold_flag(
    adapter: WebullAdapter, account: Account
) -> None:
    """The ordering above must not depend on ``fold``, which comparisons ignore.

    PEP 495: ``fold`` is disregarded when two aware datetimes share a ``tzinfo``. Had the adapter
    handed back ``ZoneInfo('America/New_York')`` for both rows, the pair would compare *equal* and
    ``sorted`` would leave them in input order -- a bug that hides for 364 days a year.
    """
    result = parse_fixture("dst_boundary.csv", adapter, account)
    first, second = result.transactions
    assert first.executed_at is not None
    assert second.executed_at is not None

    assert first.executed_at.tzinfo != second.executed_at.tzinfo
    assert first.executed_at.fold == 0
    assert second.executed_at.fold == 0

    # The shape that would have been broken, shown explicitly.
    naive = dt.datetime(2026, 11, 1, 1, 30)
    edt = naive.replace(tzinfo=EASTERN, fold=0)
    est = naive.replace(tzinfo=EASTERN, fold=1)
    assert edt.tzname() == "EDT" and est.tzname() == "EST"
    assert not edt < est  # same tzinfo -> fold ignored -> they tie

    # And the values the adapter emits denote the same two instants. Compared in UTC, because
    # PEP 495 also declares a datetime inside the fold unequal to *any* datetime in another zone --
    # so `first.executed_at == edt` is False despite both meaning 05:30Z.
    assert first.executed_at.astimezone(dt.UTC) == edt.astimezone(dt.UTC)
    assert second.executed_at.astimezone(dt.UTC) == est.astimezone(dt.UTC)


def test_naive_parsing_would_have_tied_the_dst_pair(
    adapter: WebullAdapter, account: Account
) -> None:
    """Guards the guard: without the suffix these two rows are indistinguishable."""
    result = parse_fixture("dst_boundary.csv", adapter, account)
    naive = {txn.executed_at.replace(tzinfo=None) for txn in result.transactions}  # type: ignore[union-attr]
    assert len(naive) == 1


@pytest.mark.parametrize(
    ("text", "expected_offset"),
    [
        ("06/15/2026 17:36:18 EDT", dt.timedelta(hours=-4)),
        ("01/29/2026 08:17:50 EST", dt.timedelta(hours=-5)),
        ("11/01/2026 01:30:00 EDT", dt.timedelta(hours=-4)),
        ("11/01/2026 01:30:00 EST", dt.timedelta(hours=-5)),
    ],
)
def test_parse_webull_timestamp_offsets(text: str, expected_offset: dt.timedelta) -> None:
    parsed = parse_webull_timestamp(text, field="Filled Time", row_index=0)
    assert parsed.utcoffset() == expected_offset


@pytest.mark.parametrize(
    "text",
    [
        "06/15/2026 17:36:18",  # suffix dropped
        "06/15/2026 17:36:18 PDT",  # zone never observed in this export
        "2026-06-15 17:36:18 EDT",  # ISO, not the broker's format
        "",
    ],
)
def test_unparseable_timestamps_raise(text: str) -> None:
    with pytest.raises(ValueError):
        parse_webull_timestamp(text, field="Filled Time", row_index=3)


# ---------------------------------------------------------------------------
# Instruments and identity
# ---------------------------------------------------------------------------


def test_hyphenated_ticker_normalises_to_the_robinhood_form(sample: AdapterResult) -> None:
    """Webull writes ``BRK-B``; Robinhood writes ``BRK.B``. Both must land on one instrument."""
    txn = by_row(sample, ROW_HYPHEN_TICKER)
    # The transaction keeps the broker's spelling, as the model requires.
    assert txn.symbol == "BRK-B"
    # Identity does not.
    expected_id = instrument_id(cusip=None, symbol="BRK.B")
    assert txn.instrument_id == expected_id
    assert instrument_id(cusip=None, symbol="BRK-B") == expected_id

    instrument = sample.instruments[expected_id]
    assert instrument.primary_symbol == "BRK.B"
    assert normalize_symbol("BRK-B") == instrument.primary_symbol


def test_instruments_carry_no_cusip(sample: AdapterResult) -> None:
    """The export has no CUSIP column; claiming one would poison cross-broker matching."""
    assert sample.instruments
    assert all(inst.cusip is None for inst in sample.instruments.values())
    assert all(txn.cusip is None for txn in sample.transactions)


def test_instruments_are_deduplicated_and_named(sample: AdapterResult) -> None:
    zyx = sample.instruments[instrument_id(cusip=None, symbol="ZYX")]
    assert zyx.name == "Zylo Dynamics Inc"
    # ZYX is bought and sold; DUPE appears twice. One instrument each.
    symbols = [inst.primary_symbol for inst in sample.instruments.values()]
    assert len(symbols) == len(set(symbols))
    # QQAB is present now: its partial fill executed, so it is a real holding.
    assert set(symbols) == {"ZYX", "BRK.B", "FRAC", "PRTL", "DUPE", "FBCK", "QQAB"}


# ---------------------------------------------------------------------------
# Provenance and identity of transactions
# ---------------------------------------------------------------------------


def test_provenance_points_back_at_the_source_row(sample: AdapterResult) -> None:
    for txn in sample.transactions:
        assert txn.import_id == "imp-webull"
        assert txn.account_id == "wb-cash"
        assert txn.broker is Broker.WEBULL
    assert [txn.source_row for txn in sample.transactions] == [
        ROW_PLAIN_BUY,
        ROW_AVG_PRICE_BELOW_LIMIT,
        ROW_CANCELLED_PARTIAL,
        ROW_HYPHEN_TICKER,
        ROW_FRACTIONAL,
        ROW_PARTIAL_FILL,
        ROW_DUPLICATE_A,
        ROW_DUPLICATE_B,
        ROW_NO_FILLED_TIME,
    ]


def test_sequence_is_a_duplicate_ordinal_not_the_row_position(sample: AdapterResult) -> None:
    """Skipped rows still consume a `source_row`; `sequence` counts duplicates instead.

    Tying `sequence` to the file position made every id move when an export grew -- see
    `app.core.ids.TransactionSequencer`. Provenance keeps the position; identity does not.
    """
    for txn in sample.transactions:
        assert txn.sequence >= 0

    rows = [txn.source_row for txn in sample.transactions]
    assert rows == sorted(rows)
    assert any(txn.sequence != txn.source_row for txn in sample.transactions), (
        "the two are no longer the same thing, and this fixture must prove it"
    )


def test_adapter_declares_newest_first_export_order() -> None:
    assert ADAPTER.export_order is ExportOrder.NEWEST_FIRST


def test_replay_order_reverses_a_newest_first_round_trip(
    adapter: WebullAdapter, account: Account, tmp_path: Path
) -> None:
    """Webull carries its own execution timestamp, so `fetch_transactions` never needed
    `replay_order` to sort this broker's same-day trades correctly -- but the adapter must still
    assign it consistently with the file's newest-first direction, for symmetry with Robinhood and
    SoFi and so a future change to the timestamp logic can't quietly leave `replay_order` wrong
    underneath it."""
    raw = write_csv(
        tmp_path,
        "round_trip.csv",
        WEBULL_HEADER,
        "Zylo Dynamics Inc,DEF,Sell,Filled,5,5,@25.0000000000,25.0000000000,DAY,"
        "06/15/2026 15:00:00 EDT,06/15/2026 15:00:00 EDT",
        "Zylo Dynamics Inc,DEF,Buy,Filled,5,5,@20.0000000000,20.0000000000,DAY,"
        "06/15/2026 09:30:00 EDT,06/15/2026 09:30:00 EDT",
    )
    result = adapter.parse(raw, account=account, import_id="imp")
    sell, buy = result.transactions
    assert (sell.action, buy.action) == (TxnAction.SELL, TxnAction.BUY)

    assert (sell.source_row, buy.source_row) == (0, 1)
    assert (buy.replay_order, sell.replay_order) == (0, 1)
    assert buy.replay_order < sell.replay_order


def test_identical_rows_get_distinct_ids_via_sequence(sample: AdapterResult) -> None:
    """Two identical 5-share buys at the same instant are two trades, not a duplicate."""
    first = by_row(sample, ROW_DUPLICATE_A)
    second = by_row(sample, ROW_DUPLICATE_B)
    assert (first.symbol, first.quantity, first.price, first.executed_at) == (
        second.symbol,
        second.quantity,
        second.price,
        second.executed_at,
    )
    assert first.txn_id != second.txn_id


def test_reparsing_is_idempotent(adapter: WebullAdapter, account: Account) -> None:
    """Re-importing the same export must collide on txn_id rather than duplicate lots."""
    first = parse_fixture("orders_sample.csv", adapter, account)
    second = parse_fixture("orders_sample.csv", adapter, account)
    assert [t.txn_id for t in first.transactions] == [t.txn_id for t in second.transactions]
    assert len({t.txn_id for t in first.transactions}) == len(first.transactions)


def test_raw_code_and_description_are_retained(sample: AdapterResult) -> None:
    txn = by_row(sample, ROW_PLAIN_BUY)
    assert txn.raw_code == "Buy"
    assert txn.description == "Zylo Dynamics Inc"


# ---------------------------------------------------------------------------
# Unmapped vocabulary must raise, never be skipped
# ---------------------------------------------------------------------------


def test_unknown_side_raises(adapter: WebullAdapter, account: Account) -> None:
    with pytest.raises(UnknownTransactionCode) as excinfo:
        parse_fixture("unknown_side.csv", adapter, account)
    assert "Short" in str(excinfo.value)
    assert excinfo.value.broker is Broker.WEBULL
    assert excinfo.value.row_index == 0


def test_unknown_status_raises(adapter: WebullAdapter, account: Account) -> None:
    with pytest.raises(UnknownTransactionCode) as excinfo:
        parse_fixture("unknown_status.csv", adapter, account)
    assert "Pending" in str(excinfo.value)


def test_blank_status_raises_rather_than_passing_through(
    adapter: WebullAdapter, account: Account, tmp_path: Path
) -> None:
    raw = write_csv(
        tmp_path,
        "blank_status.csv",
        WEBULL_HEADER,
        "Shifted Row Inc,SHIF,Buy,,5,5,@20.0000000000,20.0000000000,GTC,"
        "05/04/2026 12:00:00 EDT,05/04/2026 12:00:01 EDT",
    )
    with pytest.raises(UnknownTransactionCode):
        adapter.parse(raw, account=account, import_id="imp")


def test_unparseable_price_on_a_filled_row_raises(
    adapter: WebullAdapter, account: Account, tmp_path: Path
) -> None:
    raw = write_csv(
        tmp_path,
        "bad_price.csv",
        WEBULL_HEADER,
        "Garbled Price Inc,GARB,Buy,Filled,5,5,@20.0000000000,n/a,GTC,"
        "05/04/2026 12:00:00 EDT,05/04/2026 12:00:01 EDT",
    )
    with pytest.raises(MoneyParseError):
        adapter.parse(raw, account=account, import_id="imp")


def test_empty_avg_price_on_a_filled_row_raises(
    adapter: WebullAdapter, account: Account, tmp_path: Path
) -> None:
    """An executed row with no execution price is a malformed export, not a zero-cost trade."""
    raw = write_csv(
        tmp_path,
        "missing_price.csv",
        WEBULL_HEADER,
        "No Price Inc,NOPR,Buy,Filled,5,5,@20.0000000000,,GTC,"
        "05/04/2026 12:00:00 EDT,05/04/2026 12:00:01 EDT",
    )
    with pytest.raises(MoneyParseError):
        adapter.parse(raw, account=account, import_id="imp")


def test_filled_row_without_a_symbol_raises(
    adapter: WebullAdapter, account: Account, tmp_path: Path
) -> None:
    raw = write_csv(
        tmp_path,
        "no_symbol.csv",
        WEBULL_HEADER,
        "Anonymous Inc,,Buy,Filled,5,5,@20.0000000000,20.0000000000,GTC,"
        "05/04/2026 12:00:00 EDT,05/04/2026 12:00:01 EDT",
    )
    with pytest.raises(ValueError, match="no Symbol"):
        adapter.parse(raw, account=account, import_id="imp")


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
    adapter: WebullAdapter, account: Account, tmp_path: Path, symbol: str
) -> None:
    """A Symbol that does not look like a ticker must be rejected at ingestion, not carried
    downstream to the Form 8949 CSV export -- the file docs/ tells the user to open directly in tax
    software or Excel. Raising here matches this adapter's existing convention (plain ValueError on a
    missing Symbol) of failing loudly on a malformed row rather than skipping or guessing."""
    raw = write_csv(
        tmp_path,
        "bad_symbol.csv",
        WEBULL_HEADER,
        f"Bad Symbol Inc,{symbol},Buy,Filled,5,5,@20.0000000000,20.0000000000,GTC,"
        "05/04/2026 12:00:00 EDT,05/04/2026 12:00:01 EDT",
    )
    with pytest.raises(ValueError, match="does not look like a ticker"):
        adapter.parse(raw, account=account, import_id="imp")


def test_a_legitimate_hyphenated_symbol_still_parses(
    adapter: WebullAdapter, account: Account, tmp_path: Path
) -> None:
    """Guards against an overly narrow regex: ``BRK-B``-shaped tickers are real (see
    ROW_HYPHEN_TICKER in the sample fixture) and must keep working."""
    raw = write_csv(
        tmp_path,
        "hyphen.csv",
        WEBULL_HEADER,
        "Berkshire Placeholder,BRK-B,Buy,Filled,2,2,@440.0000000000,440.1100000000,DAY,"
        "05/04/2026 12:00:00 EDT,05/04/2026 12:00:01 EDT",
    )
    result = adapter.parse(raw, account=account, import_id="imp")
    assert result.transactions[0].symbol == "BRK-B"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def by_row(result: AdapterResult, source_row: int):
    """The single transaction produced by a given source row."""
    matches = [txn for txn in result.transactions if txn.source_row == source_row]
    assert len(matches) == 1, f"expected one transaction from row {source_row}, got {len(matches)}"
    return matches[0]

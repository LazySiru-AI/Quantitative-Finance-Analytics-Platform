"""Tests for the lot replay engine.

Every basis and proceeds assertion uses exact ``Decimal`` equality -- ``pytest.approx`` would hide
the kind of penny drift that turns into a wrong number on a real Form 8949.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.core.lots import LotMethod, WarningKind, build_lots
from app.core.models import (
    Account,
    Broker,
    LotStatus,
    TaxTreatment,
    Transaction,
    TxnAction,
)
from tests.conftest import make_txn, sample_account


def _account(account_id: str, tax_treatment: TaxTreatment = TaxTreatment.TAXABLE) -> Account:
    return sample_account(account_id=account_id, tax_treatment=tax_treatment)


# ---------------------------------------------------------------------------
# 1. Simple buy -> sell
# ---------------------------------------------------------------------------


def test_simple_buy_sell_basis_and_proceeds() -> None:
    buy = make_txn(
        txn_id="buy1",
        action=TxnAction.BUY,
        symbol="SOXL",
        quantity="50",
        price="24.10",
        amount="-1205.00",
        trade_date=dt.date(2025, 3, 1),
        source_row=0,
    )
    sell = make_txn(
        txn_id="sell1",
        action=TxnAction.SELL,
        symbol="SOXL",
        quantity="50",
        price="30.00",
        amount="1500.00",
        trade_date=dt.date(2025, 6, 1),
        source_row=1,
    )
    ledger = build_lots([buy, sell], accounts={"rh-taxable": _account("rh-taxable")})

    assert len(ledger.lots) == 1
    lot = ledger.lots[0]
    assert lot.cost_basis == Decimal("1205.00")
    assert lot.remaining == Decimal(0)
    assert lot.status is LotStatus.CLOSED
    assert lot.closed_date == dt.date(2025, 6, 1)

    assert len(ledger.disposals) == 1
    disposal = ledger.disposals[0]
    assert disposal.proceeds == Decimal("1500.00")
    assert disposal.cost_basis == Decimal("1205.00")
    assert disposal.gain_loss == Decimal("295.00")
    assert disposal.acquired_date == dt.date(2025, 3, 1)
    assert disposal.holding_start == dt.date(2025, 3, 1)
    assert not ledger.warnings


# ---------------------------------------------------------------------------
# 2. Partial sale
# ---------------------------------------------------------------------------


def test_partial_sale_leaves_partial_lot_with_correct_remaining_and_basis() -> None:
    buy = make_txn(
        txn_id="buy1",
        symbol="AAA",
        quantity="100",
        price="10",
        amount="-1000",
        trade_date=dt.date(2025, 1, 1),
        source_row=0,
    )
    sell = make_txn(
        txn_id="sell1",
        action=TxnAction.SELL,
        symbol="AAA",
        quantity="40",
        price="15",
        amount="600",
        trade_date=dt.date(2025, 2, 1),
        source_row=1,
    )
    ledger = build_lots([buy, sell], accounts={"rh-taxable": _account("rh-taxable")})

    lot = ledger.lots[0]
    assert lot.quantity == Decimal(100)
    assert lot.remaining == Decimal(60)
    assert lot.cost_basis == Decimal(1000)
    assert lot.status is LotStatus.PARTIAL
    assert lot.closed_date is None

    disposal = ledger.disposals[0]
    assert disposal.quantity == Decimal(40)
    assert disposal.cost_basis == Decimal(400)
    assert disposal.proceeds == Decimal(600)


# ---------------------------------------------------------------------------
# 3. FIFO across three lots
# ---------------------------------------------------------------------------


def test_fifo_ordering_across_three_lots_spans_two_disposals() -> None:
    buys = [
        make_txn(
            txn_id="buy1",
            symbol="BBB",
            quantity="10",
            price="10",
            amount="-100",
            trade_date=dt.date(2025, 1, 1),
            source_row=0,
        ),
        make_txn(
            txn_id="buy2",
            symbol="BBB",
            quantity="10",
            price="12",
            amount="-120",
            trade_date=dt.date(2025, 2, 1),
            source_row=1,
        ),
        make_txn(
            txn_id="buy3",
            symbol="BBB",
            quantity="10",
            price="14",
            amount="-140",
            trade_date=dt.date(2025, 3, 1),
            source_row=2,
        ),
    ]
    sell = make_txn(
        txn_id="sell1",
        action=TxnAction.SELL,
        symbol="BBB",
        quantity="15",
        price="20",
        amount="300",
        trade_date=dt.date(2025, 4, 1),
        source_row=3,
    )
    ledger = build_lots([*buys, sell], accounts={"rh-taxable": _account("rh-taxable")})

    assert len(ledger.lots) == 3
    assert len(ledger.disposals) == 2

    first, second = ledger.disposals
    assert first.acquired_date == dt.date(2025, 1, 1)
    assert first.quantity == Decimal(10)
    assert first.cost_basis == Decimal(100)
    assert first.proceeds == Decimal(200)

    assert second.acquired_date == dt.date(2025, 2, 1)
    assert second.quantity == Decimal(5)
    assert second.cost_basis == Decimal(60)
    assert second.proceeds == Decimal(100)

    lots_by_date = {lot.acquired_date: lot for lot in ledger.lots}
    assert lots_by_date[dt.date(2025, 1, 1)].status is LotStatus.CLOSED
    assert lots_by_date[dt.date(2025, 2, 1)].status is LotStatus.PARTIAL
    assert lots_by_date[dt.date(2025, 2, 1)].remaining == Decimal(5)
    assert lots_by_date[dt.date(2025, 3, 1)].status is LotStatus.OPEN
    assert lots_by_date[dt.date(2025, 3, 1)].remaining == Decimal(10)

    # Every disposal states the rule that picked its lot. Previously the only way to learn this was
    # to divide cost basis by quantity and match the result against the acquisition prices by hand,
    # which is exactly what a UAT persona had to do -- for a fact that changes the tax outcome.
    assert first.lot_method is LotMethod.FIFO
    assert second.lot_method is LotMethod.FIFO
    assert first.lot_id == lots_by_date[dt.date(2025, 1, 1)].lot_id
    assert second.lot_id == lots_by_date[dt.date(2025, 2, 1)].lot_id


def test_an_oversold_shortfall_claims_no_lot_method() -> None:
    """No lot was consumed, so no rule chose one. Defaulting the row to FIFO would assert a
    selection was made over lots that do not exist."""
    sell = make_txn(
        txn_id="sell-naked",
        action=TxnAction.SELL,
        symbol="CCC",
        quantity="5",
        price="20",
        amount="100",
        trade_date=dt.date(2025, 4, 1),
    )
    ledger = build_lots([sell], accounts={"rh-taxable": _account("rh-taxable")})

    assert len(ledger.disposals) == 1
    assert ledger.disposals[0].lot_method is None
    assert ledger.disposals[0].cost_basis == Decimal(0)


# ---------------------------------------------------------------------------
# 4. Fees
# ---------------------------------------------------------------------------


def test_fees_increase_buy_basis_and_reduce_sell_proceeds() -> None:
    buy = Transaction(
        txn_id="buy1",
        import_id="imp1",
        source_row=0,
        account_id="rh-taxable",
        broker=Broker.ROBINHOOD,
        action=TxnAction.BUY,
        trade_date=dt.date(2025, 1, 1),
        symbol="CCC",
        quantity=Decimal(10),
        price=Decimal(10),
        fees=Decimal(5),
        amount=Decimal(-105),
    )
    sell = Transaction(
        txn_id="sell1",
        import_id="imp1",
        source_row=1,
        account_id="rh-taxable",
        broker=Broker.ROBINHOOD,
        action=TxnAction.SELL,
        trade_date=dt.date(2025, 2, 1),
        symbol="CCC",
        quantity=Decimal(10),
        price=Decimal(20),
        fees=Decimal(2),
        amount=Decimal(198),
    )
    ledger = build_lots([buy, sell], accounts={"rh-taxable": _account("rh-taxable")})

    lot = ledger.lots[0]
    assert lot.cost_basis == Decimal(105)  # 10*10 + 5 fees

    disposal = ledger.disposals[0]
    assert disposal.proceeds == Decimal(200)  # gross, before fees
    assert disposal.fees == Decimal(2)
    assert disposal.cost_basis == Decimal(105)
    assert disposal.gain_loss == Decimal(200) - Decimal(2) - Decimal(105)


# ---------------------------------------------------------------------------
# 5. Fractional shares
# ---------------------------------------------------------------------------


def test_fractional_share_quantities() -> None:
    buy = make_txn(
        txn_id="buy1",
        symbol="DDD",
        quantity="0.5",
        price="100",
        amount="-50",
        trade_date=dt.date(2025, 1, 1),
        source_row=0,
    )
    sell = make_txn(
        txn_id="sell1",
        action=TxnAction.SELL,
        symbol="DDD",
        quantity="0.25",
        price="120",
        amount="30",
        trade_date=dt.date(2025, 2, 1),
        source_row=1,
    )
    ledger = build_lots([buy, sell], accounts={"rh-taxable": _account("rh-taxable")})

    lot = ledger.lots[0]
    assert lot.remaining == Decimal("0.25")

    disposal = ledger.disposals[0]
    assert disposal.quantity == Decimal("0.25")
    assert disposal.cost_basis == Decimal("25")
    assert disposal.proceeds == Decimal("30")


# ---------------------------------------------------------------------------
# 6. ACAT transfer preserves acquired_date and basis (standing case #9)
# ---------------------------------------------------------------------------


def test_acat_transfer_preserves_acquired_date_and_cost_basis() -> None:
    buy = make_txn(
        txn_id="buy1",
        symbol="NVDA",
        quantity="10",
        price="10",
        amount="-100",
        trade_date=dt.date(2025, 1, 1),
        account_id="rh-taxable",
        source_row=0,
    )
    transfer_out = make_txn(
        txn_id="out1",
        action=TxnAction.TRANSFER_OUT,
        symbol="NVDA",
        quantity="10",
        price=None,
        amount=None,
        trade_date=dt.date(2025, 6, 1),
        account_id="rh-taxable",
        source_row=1,
    )
    transfer_out = transfer_out.model_copy(update={"transfer_group": "CTRL1"})
    transfer_in = make_txn(
        txn_id="in1",
        action=TxnAction.TRANSFER_IN,
        symbol="NVDA",
        quantity="10",
        price=None,
        amount=None,
        trade_date=dt.date(2025, 6, 1),
        account_id="rh-second",
        source_row=0,
    )
    transfer_in = transfer_in.model_copy(update={"transfer_group": "CTRL1"})

    # The inbound leg is listed *before* the outbound leg -- real Robinhood exports do not guarantee
    # ordering between two different accounts' rows on the same activity date, so the replay must not
    # depend on it.
    accounts = {"rh-taxable": _account("rh-taxable"), "rh-second": _account("rh-second")}
    ledger = build_lots([buy, transfer_in, transfer_out], accounts=accounts)

    assert not ledger.disposals, "a transfer must never produce a Disposal"
    assert not ledger.warnings

    source_lot = next(lot for lot in ledger.lots if lot.account_id == "rh-taxable")
    assert source_lot.remaining == Decimal(0)
    assert source_lot.status is LotStatus.CLOSED

    dest_lot = next(lot for lot in ledger.lots if lot.account_id == "rh-second")
    assert dest_lot.acquired_date == dt.date(2025, 1, 1)
    assert dest_lot.cost_basis == Decimal(100)
    assert dest_lot.quantity == Decimal(10)
    assert dest_lot.remaining == Decimal(10)


# ---------------------------------------------------------------------------
# 7. ITRF internal transfer, same preservation
# ---------------------------------------------------------------------------


def test_internal_transfer_preserves_acquired_date_and_cost_basis() -> None:
    buy = make_txn(
        txn_id="buy1",
        symbol="XYZ",
        quantity="10",
        price="10",
        amount="-100",
        trade_date=dt.date(2025, 1, 1),
        account_id="rh-taxable",
        source_row=0,
    )
    itrf_in = make_txn(
        txn_id="itrf-in",
        action=TxnAction.INTERNAL_TRANSFER,
        symbol="XYZ",
        quantity="10",
        price=None,
        amount=None,
        trade_date=dt.date(2025, 6, 1),
        account_id="rh-second",
        source_row=0,
    )
    itrf_out = make_txn(
        txn_id="itrf-out",
        action=TxnAction.INTERNAL_TRANSFER,
        symbol="XYZ",
        quantity="10",
        price=None,
        amount=None,
        trade_date=dt.date(2025, 6, 1),
        account_id="rh-taxable",
        source_row=1,
    )

    # Same trap as ACAT: the receiving leg sorts first here, and ITRF carries no transfer_group at
    # all in real exports, so direction has to be inferred from who actually holds the shares.
    accounts = {"rh-taxable": _account("rh-taxable"), "rh-second": _account("rh-second")}
    ledger = build_lots([buy, itrf_in, itrf_out], accounts=accounts)

    assert not ledger.disposals
    assert not ledger.warnings

    source_lot = next(lot for lot in ledger.lots if lot.account_id == "rh-taxable")
    assert source_lot.remaining == Decimal(0)

    dest_lot = next(lot for lot in ledger.lots if lot.account_id == "rh-second")
    assert dest_lot.acquired_date == dt.date(2025, 1, 1)
    assert dest_lot.cost_basis == Decimal(100)
    assert dest_lot.quantity == Decimal(10)


# ---------------------------------------------------------------------------
# 8. Unmatched TRANSFER_IN
# ---------------------------------------------------------------------------


def test_unmatched_transfer_in_opens_zero_basis_lot_with_warning() -> None:
    transfer_in = make_txn(
        txn_id="in1",
        action=TxnAction.TRANSFER_IN,
        symbol="ORPHAN",
        quantity="25",
        price=None,
        amount=None,
        trade_date=dt.date(2025, 3, 1),
        account_id="rh-taxable",
        source_row=0,
    )
    transfer_in = transfer_in.model_copy(update={"transfer_group": "NOMATCH"})

    ledger = build_lots([transfer_in], accounts={"rh-taxable": _account("rh-taxable")})

    assert len(ledger.lots) == 1
    lot = ledger.lots[0]
    assert lot.cost_basis == Decimal(0)
    assert lot.quantity == Decimal(25)
    assert lot.acquired_date == dt.date(2025, 3, 1)

    assert len(ledger.warnings) == 1
    warning = ledger.warnings[0]
    assert warning.kind is WarningKind.UNMATCHED_TRANSFER_IN
    assert warning.detail
    assert warning.quantity == Decimal(25)


# ---------------------------------------------------------------------------
# 9. Oversell
# ---------------------------------------------------------------------------


def test_oversell_produces_warning_and_zero_basis_disposal_for_the_excess() -> None:
    buy = make_txn(
        txn_id="buy1",
        symbol="SOXL",
        quantity="19",
        price="10",
        amount="-190",
        trade_date=dt.date(2025, 1, 1),
        account_id="webull-margin",
        source_row=0,
    )
    sell = make_txn(
        txn_id="sell1",
        action=TxnAction.SELL,
        symbol="SOXL",
        quantity="44",
        price="12",
        amount="528",
        trade_date=dt.date(2025, 6, 1),
        account_id="webull-margin",
        source_row=1,
    )
    ledger = build_lots([buy, sell], accounts={"webull-margin": _account("webull-margin")})

    assert len(ledger.disposals) == 2
    matched, excess = ledger.disposals
    assert matched.quantity == Decimal(19)
    assert matched.cost_basis == Decimal(190)
    assert excess.quantity == Decimal(25)
    assert excess.cost_basis == Decimal(0)
    assert excess.proceeds == Decimal(12) * Decimal(25)

    oversold = [w for w in ledger.warnings if w.kind is WarningKind.OVERSOLD]
    assert len(oversold) == 1
    assert oversold[0].detail == "sold 44 SOXL against 19 held in webull-margin"
    assert oversold[0].quantity == Decimal(25)


# ---------------------------------------------------------------------------
# 9b. Fees unknown (Webull) -- finding 3.2
# ---------------------------------------------------------------------------


def test_webull_sale_reconstructs_fee_and_raises_fees_estimated_warning() -> None:
    """A Webull sale carries ``fees=0`` because the export has no fee column at all -- the absence of
    data, not a measurement. The two regulatory pass-throughs (SEC Section 31 + FINRA TAF) are fixed
    by schedule, so the fee is reconstructed and netted rather than left as a $0 gap, and the
    substitution is surfaced as :data:`FEES_ESTIMATED`."""
    buy = make_txn(
        txn_id="buy1",
        symbol="SOXL",
        quantity="50",
        price="10",
        amount="-500",
        trade_date=dt.date(2025, 1, 1),
        account_id="webull-margin",
        source_row=0,
        broker=Broker.WEBULL,
    )
    sell = make_txn(
        txn_id="sell1",
        action=TxnAction.SELL,
        symbol="SOXL",
        quantity="50",
        price="12",
        amount="600",
        trade_date=dt.date(2025, 6, 1),
        account_id="webull-margin",
        source_row=1,
        broker=Broker.WEBULL,
    )
    ledger = build_lots([buy, sell], accounts={"webull-margin": _account("webull-margin")})

    # No lingering "unknown" gap: the fee is reconstructed, so the flag is FEES_ESTIMATED instead.
    assert not [w for w in ledger.warnings if w.kind is WarningKind.FEES_UNKNOWN]
    fee_warnings = [w for w in ledger.warnings if w.kind is WarningKind.FEES_ESTIMATED]
    assert len(fee_warnings) == 1
    assert fee_warnings[0].txn_id == "sell1"
    assert fee_warnings[0].account_id == "webull-margin"
    assert fee_warnings[0].symbol == "SOXL"
    assert fee_warnings[0].quantity == Decimal(50)
    assert fee_warnings[0].detail

    # Gross proceeds and cost basis are untouched -- only the sale-side fee is filled in. For a
    # 2025-06-01 sale the SEC fee is $0.00 (FY2026's rate does not begin until 2026-04-04) and the
    # FINRA TAF on 50 shares hits its $0.01 floor, so the reconstructed fee is exactly $0.01.
    assert ledger.disposals[0].cost_basis == Decimal(500)
    assert ledger.disposals[0].proceeds == Decimal(600)
    assert ledger.disposals[0].fees == Decimal("0.01")


def test_non_webull_sale_does_not_raise_a_fee_warning() -> None:
    """A Robinhood or SoFi sale's ``fees=0`` is (or may be) a genuine zero-fee trade, not a gap in
    the export -- neither flagging it nor reconstructing a fee for it is correct, since a
    commission-free broker's export already reports its regulatory fees when it charges them."""
    buy = make_txn(
        txn_id="buy1",
        symbol="SOXL",
        quantity="50",
        price="10",
        amount="-500",
        trade_date=dt.date(2025, 1, 1),
        source_row=0,
        broker=Broker.ROBINHOOD,
    )
    sell = make_txn(
        txn_id="sell1",
        action=TxnAction.SELL,
        symbol="SOXL",
        quantity="50",
        price="12",
        amount="600",
        trade_date=dt.date(2025, 6, 1),
        source_row=1,
        broker=Broker.ROBINHOOD,
    )
    ledger = build_lots([buy, sell], accounts={"rh-taxable": _account("rh-taxable")})

    assert not [
        w
        for w in ledger.warnings
        if w.kind in (WarningKind.FEES_UNKNOWN, WarningKind.FEES_ESTIMATED)
    ]
    # ...and its fee is left exactly as the export reported it (zero here), not reconstructed.
    assert ledger.disposals[0].fees == Decimal(0)


def test_webull_sale_spanning_two_lots_raises_exactly_one_fee_warning() -> None:
    """The warning is a property of the sale, not of each lot slice it draws on -- one Webull SELL
    consuming two lots must not produce two identical warnings."""
    buy1 = make_txn(
        txn_id="buy1",
        symbol="SOXL",
        quantity="20",
        price="10",
        amount="-200",
        trade_date=dt.date(2025, 1, 1),
        account_id="webull-margin",
        source_row=0,
        broker=Broker.WEBULL,
    )
    buy2 = make_txn(
        txn_id="buy2",
        symbol="SOXL",
        quantity="20",
        price="11",
        amount="-220",
        trade_date=dt.date(2025, 2, 1),
        account_id="webull-margin",
        source_row=1,
        broker=Broker.WEBULL,
    )
    sell = make_txn(
        txn_id="sell1",
        action=TxnAction.SELL,
        symbol="SOXL",
        quantity="30",
        price="12",
        amount="360",
        trade_date=dt.date(2025, 6, 1),
        account_id="webull-margin",
        source_row=2,
        broker=Broker.WEBULL,
    )
    ledger = build_lots(
        [buy1, buy2, sell], accounts={"webull-margin": _account("webull-margin")}
    )

    assert len(ledger.disposals) == 2  # spans both lots
    fee_warnings = [w for w in ledger.warnings if w.kind is WarningKind.FEES_ESTIMATED]
    assert len(fee_warnings) == 1


# ---------------------------------------------------------------------------
# 10. Split
# ---------------------------------------------------------------------------


def test_split_multiplies_shares_and_preserves_total_basis() -> None:
    buy = make_txn(
        txn_id="buy1",
        symbol="EEE",
        quantity="10",
        price="10",
        amount="-100",
        trade_date=dt.date(2025, 1, 1),
        source_row=0,
    )
    split = Transaction(
        txn_id="split1",
        import_id="imp1",
        source_row=1,
        account_id="rh-taxable",
        broker=Broker.ROBINHOOD,
        action=TxnAction.SPLIT,
        trade_date=dt.date(2025, 3, 1),
        symbol="EEE",
        description="2:1 stock split",
    )
    ledger = build_lots([buy, split], accounts={"rh-taxable": _account("rh-taxable")})

    assert not ledger.warnings
    lot = ledger.lots[0]
    assert lot.quantity == Decimal(20)
    assert lot.remaining == Decimal(20)
    assert lot.cost_basis == Decimal(100)
    assert lot.basis_per_share == Decimal(5)


def test_split_without_ratio_leaves_lots_untouched_and_warns() -> None:
    buy = make_txn(
        txn_id="buy1",
        symbol="FFF",
        quantity="10",
        price="10",
        amount="-100",
        trade_date=dt.date(2025, 1, 1),
        source_row=0,
    )
    split = Transaction(
        txn_id="split1",
        import_id="imp1",
        source_row=1,
        account_id="rh-taxable",
        broker=Broker.ROBINHOOD,
        action=TxnAction.SPLIT,
        trade_date=dt.date(2025, 3, 1),
        symbol="FFF",
        description="Forward split",
    )
    ledger = build_lots([buy, split], accounts={"rh-taxable": _account("rh-taxable")})

    lot = ledger.lots[0]
    assert lot.quantity == Decimal(10)
    assert len(ledger.warnings) == 1
    assert ledger.warnings[0].kind is WarningKind.SPLIT_WITHOUT_RATIO
    assert ledger.warnings[0].detail


# ---------------------------------------------------------------------------
# 11. Determinism
# ---------------------------------------------------------------------------


def test_determinism_same_input_yields_identical_lot_and_disposal_ids() -> None:
    buys = [
        make_txn(
            txn_id="buy1",
            symbol="GGG",
            quantity="10",
            price="10",
            amount="-100",
            trade_date=dt.date(2025, 1, 1),
            source_row=0,
        ),
        make_txn(
            txn_id="buy2",
            symbol="GGG",
            quantity="10",
            price="12",
            amount="-120",
            trade_date=dt.date(2025, 2, 1),
            source_row=1,
        ),
    ]
    sell = make_txn(
        txn_id="sell1",
        action=TxnAction.SELL,
        symbol="GGG",
        quantity="15",
        price="20",
        amount="300",
        trade_date=dt.date(2025, 4, 1),
        source_row=2,
    )
    transactions = [*buys, sell]
    accounts = {"rh-taxable": _account("rh-taxable")}

    first = build_lots(transactions, accounts=accounts)
    second = build_lots(transactions, accounts=accounts)

    assert [lot.lot_id for lot in first.lots] == [lot.lot_id for lot in second.lots]
    assert [d.disposal_id for d in first.disposals] == [d.disposal_id for d in second.disposals]
    assert [w.detail for w in first.warnings] == [w.detail for w in second.warnings]

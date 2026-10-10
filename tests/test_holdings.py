"""Portfolio aggregation: open lots -> positions.

``LotLedger`` / ``Lot`` objects are constructed by hand throughout, exactly as ``tests/test_gains.py``
builds ``Disposal`` objects by hand -- each case here is about one specific aggregation rule (a term
boundary, a warning propagating, a closed lot disappearing), not about the replay engine that
produces lots in the first place. Every dollar and share-count assertion is exact ``Decimal``
equality; ``pytest.approx`` has no place in a money test.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.core.holdings import build_positions
from app.core.lots import LotLedger, LotWarning, WarningKind
from app.core.models import Account, AccountType, Broker, Lot, LotStatus, TaxTreatment

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_account(
    account_id: str = "rh-taxable",
    *,
    label: str | None = None,
    broker: Broker = Broker.ROBINHOOD,
    tax_treatment: TaxTreatment = TaxTreatment.TAXABLE,
    account_type: AccountType = AccountType.CASH,
) -> Account:
    return Account(
        account_id=account_id,
        broker=broker,
        label=label or account_id,
        tax_treatment=tax_treatment,
        account_type=account_type,
    )


_seq = 0


def make_lot(
    *,
    instrument_id: str = "instr-aaa",
    account_id: str = "rh-taxable",
    acquired_date: dt.date,
    quantity: str,
    remaining: str | None = None,
    cost_basis: str,
    holding_period_start: dt.date | None = None,
    wash_sale_adjustment: str = "0",
    status: LotStatus = LotStatus.OPEN,
) -> Lot:
    global _seq
    _seq += 1
    qty = Decimal(quantity)
    rem = Decimal(remaining) if remaining is not None else qty
    return Lot(
        lot_id=f"lot-{_seq}",
        instrument_id=instrument_id,
        account_id=account_id,
        acquired_date=acquired_date,
        acquired_txn_id=f"buy-{_seq}",
        quantity=qty,
        remaining=rem,
        cost_basis=Decimal(cost_basis),
        wash_sale_adjustment=Decimal(wash_sale_adjustment),
        holding_period_start=holding_period_start,
        status=status if rem > 0 else LotStatus.CLOSED,
    )


def make_warning(
    kind: WarningKind,
    *,
    account_id: str,
    instrument_id: str,
    txn_id: str = "t1",
    trade_date: dt.date = dt.date(2024, 1, 1),
    symbol: str = "AAA",
) -> LotWarning:
    return LotWarning(
        kind=kind,
        txn_id=txn_id,
        account_id=account_id,
        instrument_id=instrument_id,
        symbol=symbol,
        trade_date=trade_date,
        detail="test warning",
    )


AS_OF = dt.date(2025, 1, 1)


# ---------------------------------------------------------------------------
# 1. Aggregation across multiple accounts holding the same instrument
# ---------------------------------------------------------------------------


def test_aggregates_the_same_instrument_across_accounts() -> None:
    lot_a = make_lot(
        account_id="rh-taxable",
        acquired_date=dt.date(2024, 1, 1),
        quantity="10",
        cost_basis="1000",
    )
    lot_b = make_lot(
        account_id="wb-margin",
        acquired_date=dt.date(2024, 2, 1),
        quantity="5",
        cost_basis="600",
    )
    ledger = LotLedger(lots=[lot_a, lot_b], symbols={"instr-aaa": "AAA"})
    accounts = {
        "rh-taxable": make_account("rh-taxable", label="RH Taxable"),
        "wb-margin": make_account("wb-margin", broker=Broker.WEBULL, label="Webull Margin"),
    }

    holdings = build_positions(ledger, accounts=accounts, as_of=AS_OF)

    assert len(holdings) == 1
    position = holdings[0]
    assert position.instrument_id == "instr-aaa"
    assert position.symbol == "AAA"
    assert position.quantity == Decimal(15)
    assert position.cost_basis == Decimal(1600)
    assert position.lot_count == 2

    assert len(position.accounts) == 2
    by_account = {a.account_id: a for a in position.accounts}
    assert by_account["rh-taxable"].quantity == Decimal(10)
    assert by_account["rh-taxable"].cost_basis == Decimal(1000)
    assert by_account["rh-taxable"].account_label == "RH Taxable"
    assert by_account["rh-taxable"].broker == "robinhood"
    assert by_account["wb-margin"].quantity == Decimal(5)
    assert by_account["wb-margin"].cost_basis == Decimal(600)
    assert by_account["wb-margin"].broker == "webull"


# ---------------------------------------------------------------------------
# 2. Wash-sale-tolled lot classified long-term when acquired_date alone would say short
# ---------------------------------------------------------------------------


def test_wash_sale_tolling_reclassifies_a_recent_lot_as_long_term() -> None:
    """The lot was bought 2024-06-15 -- six weeks before ``as_of`` -- so acquired_date alone would
    make it short-term. Its holding period was tolled back to 2023-01-01 by an earlier wash sale, so
    it must classify long-term instead. This is the entire reason
    ``Lot.effective_holding_start`` exists rather than the plain acquired_date being used."""
    lot = make_lot(
        acquired_date=dt.date(2024, 6, 15),
        holding_period_start=dt.date(2023, 1, 1),
        quantity="10",
        cost_basis="1200",
        wash_sale_adjustment="200",
    )
    ledger = LotLedger(lots=[lot], symbols={"instr-aaa": "AAA"})
    accounts = {"rh-taxable": make_account()}

    as_of = dt.date(2024, 8, 1)  # < 1 year from acquired_date, > 1 year from the tolled start
    holdings = build_positions(ledger, accounts=accounts, as_of=as_of)

    position = holdings[0]
    assert position.short_term_quantity == Decimal(0)
    assert position.long_term_quantity == Decimal(10)
    assert position.wash_sale_adjustment == Decimal(200)


def test_wash_sale_adjustment_is_prorated_to_the_remaining_shares() -> None:
    """A lot only 40% still held should only carry forward 40% of its wash-sale adjustment -- the
    rest left with the shares that were already sold."""
    lot = make_lot(
        acquired_date=dt.date(2024, 1, 1),
        quantity="100",
        remaining="40",
        cost_basis="4400",  # includes the full $400 wash-sale adjustment on the original 100 shares
        wash_sale_adjustment="400",
    )
    ledger = LotLedger(lots=[lot], symbols={"instr-aaa": "AAA"})
    accounts = {"rh-taxable": make_account()}

    holdings = build_positions(ledger, accounts=accounts, as_of=AS_OF)

    position = holdings[0]
    assert position.quantity == Decimal(40)
    assert position.wash_sale_adjustment == Decimal(160)  # 400 * 40/100


# ---------------------------------------------------------------------------
# 3. basis_uncertain / fees_unknown propagation
# ---------------------------------------------------------------------------


def test_unmatched_transfer_warning_marks_basis_uncertain_up_to_the_position() -> None:
    lot = make_lot(
        instrument_id="instr-bbb",
        account_id="rh-taxable",
        acquired_date=dt.date(2024, 1, 1),
        quantity="10",
        cost_basis="0",  # opened at zero basis, as an unmatched-transfer-in lot would be
    )
    other_account_lot = make_lot(
        instrument_id="instr-bbb",
        account_id="wb-margin",
        acquired_date=dt.date(2024, 3, 1),
        quantity="5",
        cost_basis="500",
    )
    warning = make_warning(
        WarningKind.UNMATCHED_TRANSFER_IN, account_id="rh-taxable", instrument_id="instr-bbb"
    )
    ledger = LotLedger(
        lots=[lot, other_account_lot], warnings=[warning], symbols={"instr-bbb": "BBB"}
    )
    accounts = {
        "rh-taxable": make_account("rh-taxable"),
        "wb-margin": make_account("wb-margin", broker=Broker.WEBULL),
    }

    holdings = build_positions(ledger, accounts=accounts, as_of=AS_OF)

    position = holdings[0]
    assert position.basis_uncertain is True
    assert position.fees_unknown is False

    by_account = {a.account_id: a for a in position.accounts}
    assert by_account["rh-taxable"].basis_uncertain is True
    # The other account's own lots carry no such warning and must not inherit one from a sibling
    # account merely because they share an instrument.
    assert by_account["wb-margin"].basis_uncertain is False


def test_fees_unknown_warning_marks_the_position_without_touching_basis_uncertain() -> None:
    lot = make_lot(
        instrument_id="instr-ccc",
        account_id="wb-margin",
        acquired_date=dt.date(2024, 1, 1),
        quantity="10",
        cost_basis="1000",
    )
    warning = make_warning(
        WarningKind.FEES_UNKNOWN,
        account_id="wb-margin",
        instrument_id="instr-ccc",
        symbol="CCC",
    )
    ledger = LotLedger(lots=[lot], warnings=[warning], symbols={"instr-ccc": "CCC"})
    accounts = {"wb-margin": make_account("wb-margin", broker=Broker.WEBULL)}

    holdings = build_positions(ledger, accounts=accounts, as_of=AS_OF)

    position = holdings[0]
    assert position.fees_unknown is True
    assert position.basis_uncertain is False
    assert position.accounts[0].fees_unknown is True
    assert position.accounts[0].basis_uncertain is False


def test_warning_on_a_different_instrument_does_not_leak_across_positions() -> None:
    flagged = make_lot(
        instrument_id="instr-ddd",
        account_id="rh-taxable",
        acquired_date=dt.date(2024, 1, 1),
        quantity="10",
        cost_basis="0",
    )
    clean = make_lot(
        instrument_id="instr-eee",
        account_id="rh-taxable",
        acquired_date=dt.date(2024, 1, 1),
        quantity="10",
        cost_basis="1000",
    )
    warning = make_warning(
        WarningKind.UNMATCHED_TRANSFER_IN, account_id="rh-taxable", instrument_id="instr-ddd"
    )
    ledger = LotLedger(
        lots=[flagged, clean],
        warnings=[warning],
        symbols={"instr-ddd": "DDD", "instr-eee": "EEE"},
    )
    accounts = {"rh-taxable": make_account()}

    holdings = build_positions(ledger, accounts=accounts, as_of=AS_OF)
    by_symbol = {p.symbol: p for p in holdings}

    assert by_symbol["DDD"].basis_uncertain is True
    assert by_symbol["EEE"].basis_uncertain is False


# ---------------------------------------------------------------------------
# 4. A fully-closed instrument does not appear at all
# ---------------------------------------------------------------------------


def test_fully_closed_instrument_does_not_appear() -> None:
    closed = make_lot(
        instrument_id="instr-fff",
        acquired_date=dt.date(2024, 1, 1),
        quantity="10",
        remaining="0",
        cost_basis="1000",
    )
    still_open = make_lot(
        instrument_id="instr-ggg",
        acquired_date=dt.date(2024, 1, 1),
        quantity="10",
        cost_basis="1000",
    )
    ledger = LotLedger(
        lots=[closed, still_open], symbols={"instr-fff": "FFF", "instr-ggg": "GGG"}
    )
    accounts = {"rh-taxable": make_account()}

    holdings = build_positions(ledger, accounts=accounts, as_of=AS_OF)

    symbols = {p.symbol for p in holdings}
    assert symbols == {"GGG"}


def test_a_position_partially_closed_still_appears_with_only_remaining_shares() -> None:
    lot = make_lot(
        acquired_date=dt.date(2024, 1, 1),
        quantity="100",
        remaining="30",
        cost_basis="10000",
    )
    ledger = LotLedger(lots=[lot], symbols={"instr-aaa": "AAA"})
    accounts = {"rh-taxable": make_account()}

    holdings = build_positions(ledger, accounts=accounts, as_of=AS_OF)

    position = holdings[0]
    assert position.quantity == Decimal(30)
    assert position.cost_basis == Decimal(3000)  # 30/100 of the lot's basis
    assert position.basis_per_share == Decimal(100)


# ---------------------------------------------------------------------------
# 5. Earliest/latest acquired and lot counts
# ---------------------------------------------------------------------------


def test_earliest_and_latest_acquired_span_every_contributing_lot() -> None:
    lot_early = make_lot(
        account_id="rh-taxable", acquired_date=dt.date(2022, 5, 1), quantity="10", cost_basis="500"
    )
    lot_late = make_lot(
        account_id="wb-margin", acquired_date=dt.date(2024, 9, 1), quantity="4", cost_basis="400"
    )
    ledger = LotLedger(lots=[lot_early, lot_late], symbols={"instr-aaa": "AAA"})
    accounts = {
        "rh-taxable": make_account("rh-taxable"),
        "wb-margin": make_account("wb-margin", broker=Broker.WEBULL),
    }

    holdings = build_positions(ledger, accounts=accounts, as_of=AS_OF)

    position = holdings[0]
    assert position.earliest_acquired == dt.date(2022, 5, 1)
    assert position.latest_acquired == dt.date(2024, 9, 1)
    assert position.lot_count == 2

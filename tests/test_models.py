"""Canonical model invariants."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.models import (
    Lot,
    LotStatus,
    Position,
    TaxTreatment,
    Transaction,
    TxnAction,
)
from tests.conftest import make_txn


class TestNoFloats:
    """Floats are rejected at the model boundary, not quietly coerced.

    Pydantic would turn 0.1 into Decimal('0.1000000000000000055511151231257827021181583404541015625'),
    and that error survives all the way into a Form 8949 line.
    """

    @pytest.mark.parametrize("field", ["quantity", "price", "amount", "fees"])
    def test_float_rejected_on_transaction(self, field: str) -> None:
        payload = {**make_txn().model_dump(), field: 0.1}
        with pytest.raises(ValidationError, match="not permitted"):
            Transaction.model_validate(payload)

    def test_float_rejected_on_lot_basis(self) -> None:
        with pytest.raises(ValidationError, match="not permitted"):
            Lot(
                lot_id="l1",
                instrument_id="i1",
                account_id="a1",
                acquired_date=dt.date(2026, 1, 2),
                acquired_txn_id="t1",
                quantity=Decimal(10),
                remaining=Decimal(10),
                cost_basis=1205.00,  # type: ignore[arg-type]
            )

    def test_decimal_and_string_accepted(self) -> None:
        lot = Lot(
            lot_id="l1",
            instrument_id="i1",
            account_id="a1",
            acquired_date=dt.date(2026, 1, 2),
            acquired_txn_id="t1",
            quantity=Decimal(10),
            remaining="10",  # type: ignore[arg-type]
            cost_basis="1205.00",  # type: ignore[arg-type]
        )
        assert lot.cost_basis == Decimal("1205.00")


class TestTransactionValidation:
    def test_trade_requires_quantity(self) -> None:
        with pytest.raises(ValidationError, match="no quantity"):
            make_txn(action=TxnAction.BUY, quantity=None)

    def test_trade_requires_symbol(self) -> None:
        with pytest.raises(ValidationError, match="no symbol"):
            make_txn(action=TxnAction.SELL, symbol=None)

    def test_trade_rejects_zero_quantity(self) -> None:
        """A zero-quantity fill is a cancelled order that leaked through the adapter's filter."""
        with pytest.raises(ValidationError, match="zero quantity"):
            make_txn(action=TxnAction.BUY, quantity="0")

    def test_non_trade_may_omit_symbol_and_quantity(self) -> None:
        """Dividends, fees and cash movements legitimately have neither."""
        txn = make_txn(action=TxnAction.FEE, symbol=None, quantity=None, price=None, amount="-7.95")
        assert txn.amount == Decimal("-7.95")

    def test_transactions_are_immutable(self) -> None:
        with pytest.raises(ValidationError):
            make_txn().symbol = "NVDA"  # type: ignore[misc]

    def test_unknown_field_rejected(self) -> None:
        """extra="forbid" catches an adapter passing a column the model does not know about."""
        with pytest.raises(ValidationError):
            Transaction.model_validate({**make_txn().model_dump(), "nonexistent": 1})


class TestReplayOrderIsNotIdentity:
    """`replay_order` corrects which shares a same-day sale consumes; it must never change which
    stored row a transaction *is*. If it were hashed into `txn_id`, backfilling it against an
    existing database (see `app.db.sqlite._migrate_replay_order`) would change the id of every
    affected row and force a re-import of the user's whole ledger to pick up a fix that only
    reorders replay -- exactly the failure `app.core.ids.TransactionSequencer`'s docstring
    describes for `source_row` before `sequence` was split out from it.
    """

    def test_same_content_at_a_different_replay_order_keeps_the_same_txn_id(self) -> None:
        base = make_txn(txn_id="t1", replay_order=0)
        moved = base.model_copy(update={"replay_order": 41})

        assert moved.replay_order != base.replay_order
        assert moved.txn_id == base.txn_id

    def test_transaction_id_helper_has_no_replay_order_parameter(self) -> None:
        """Structural guard, not just a behavioural one: `app.core.ids.transaction_id`'s signature
        does not accept `replay_order` at all, so there is nothing to accidentally start hashing
        in as the function evolves."""
        import inspect

        from app.core.ids import transaction_id

        assert "replay_order" not in inspect.signature(transaction_id).parameters


class TestActionSemantics:
    def test_acat_transfers_are_not_trades(self) -> None:
        """Treating an ACAT as a sale invents a taxable event and restarts the holding period."""
        for action in (TxnAction.TRANSFER_IN, TxnAction.TRANSFER_OUT):
            assert action.is_position_transfer
            assert not action.is_trade
            assert action.affects_position

    def test_income_does_not_affect_position(self) -> None:
        for action in (
            TxnAction.DIVIDEND,
            TxnAction.INTEREST,
            TxnAction.STOCK_LENDING_INCOME,
            TxnAction.FEE,
        ):
            assert not action.affects_position

    def test_corporate_actions_affect_position(self) -> None:
        assert TxnAction.SPLIT.affects_position
        assert TxnAction.SPINOFF.affects_position


class TestTaxTreatment:
    def test_iras_are_tax_advantaged(self) -> None:
        assert TaxTreatment.ROTH_IRA.is_tax_advantaged
        assert TaxTreatment.TRADITIONAL_IRA.is_tax_advantaged

    def test_taxable_is_not(self) -> None:
        assert not TaxTreatment.TAXABLE.is_tax_advantaged


class TestLot:
    def _lot(self, **overrides: object) -> Lot:
        base = {
            "lot_id": "l1",
            "instrument_id": "i1",
            "account_id": "a1",
            "acquired_date": dt.date(2026, 3, 2),
            "acquired_txn_id": "t1",
            "quantity": Decimal(50),
            "remaining": Decimal(50),
            "cost_basis": Decimal("1205.00"),
        }
        return Lot(**{**base, **overrides})  # type: ignore[arg-type]

    def test_basis_per_share_is_unrounded(self) -> None:
        """Rounding per-share basis would drift across a chain of partial disposals."""
        lot = self._lot(quantity=Decimal(3), cost_basis=Decimal(100))
        assert lot.basis_per_share == Decimal(100) / Decimal(3)

    def test_holding_start_defaults_to_acquisition(self) -> None:
        assert self._lot().effective_holding_start == dt.date(2026, 3, 2)

    def test_wash_sale_tolling_moves_holding_start_earlier(self) -> None:
        """The tolled start is what can convert a short-term position into a long-term one."""
        lot = self._lot(holding_period_start=dt.date(2025, 1, 10))
        assert lot.effective_holding_start == dt.date(2025, 1, 10)
        assert lot.acquired_date == dt.date(2026, 3, 2)

    def test_zero_quantity_basis_raises(self) -> None:
        with pytest.raises(ZeroDivisionError):
            _ = self._lot(quantity=Decimal(0), remaining=Decimal(0)).basis_per_share

    def test_lot_is_mutable_for_wash_sale_adjustment(self) -> None:
        """Unlike other models, lots are adjusted in place during a derived rebuild."""
        lot = self._lot()
        lot.cost_basis += Decimal("312.50")
        lot.wash_sale_adjustment = Decimal("312.50")
        lot.status = LotStatus.PARTIAL
        assert lot.cost_basis == Decimal("1517.50")


class TestPosition:
    def test_average_cost(self) -> None:
        pos = Position(
            instrument_id="i1",
            symbol="SOXL",
            quantity=Decimal(100),
            cost_basis=Decimal("2410.00"),
        )
        assert pos.average_cost == Decimal("24.10")

    def test_average_cost_of_closed_position_is_none(self) -> None:
        """A fully-closed position must not divide by zero on a portfolio page."""
        pos = Position(
            instrument_id="i1", symbol="SOXL", quantity=Decimal(0), cost_basis=Decimal(0)
        )
        assert pos.average_cost is None

    def test_consolidates_across_accounts(self) -> None:
        """55 symbols are held at more than one broker; positions consolidate by default."""
        pos = Position(
            instrument_id="i1",
            symbol="NVDA",
            quantity=Decimal(40),
            cost_basis=Decimal(4000),
            accounts=("rh-taxable", "rh-roth", "wb-margin"),
        )
        assert len(pos.accounts) == 3

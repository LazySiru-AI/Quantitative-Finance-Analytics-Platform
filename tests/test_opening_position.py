"""Opening positions: shares that are older than the export that describes them.

Every Robinhood account in this dataset begins mid-history, and until this existed the replay had no
way to know it. The consequences were not cosmetic:

* A sale of pre-window shares became ``oversold``, a zero-basis disposal, and a realised gain equal
  to the whole proceeds.
* A *transfer* of them could not be attributed at all -- neither account could be shown to hold the
  shares, so ``_split_transfer_legs`` nominated a direction, and on a real ledger it nominated
  wrongly twice, parking shares in an account the broker statement says holds none of them.

The second case is what these tests are mostly about, because it is the one where the replay was
producing a confident, specific, wrong answer rather than a flagged one.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.core.lots import OpeningPosition, WarningKind, build_lots
from app.core.models import Account, AccountType, Broker, TaxTreatment
from tests.conftest import make_txn

SENDER = Account(
    account_id="rh-taxable",
    broker=Broker.ROBINHOOD,
    label="RH taxable",
    tax_treatment=TaxTreatment.TAXABLE,
    account_type=AccountType.CASH,
)
RECEIVER = Account(
    account_id="rh-short-cash",
    broker=Broker.ROBINHOOD,
    label="RH short cash",
    tax_treatment=TaxTreatment.TAXABLE,
    account_type=AccountType.CASH,
)
ACCOUNTS = {a.account_id: a for a in (SENDER, RECEIVER)}


def opening(**kw: object) -> OpeningPosition:
    base: dict[str, object] = {
        "account_id": "rh-taxable",
        "symbol": "GOOGL",
        "quantity": Decimal("10"),
        "as_of": dt.date(2026, 1, 5),
    }
    base.update(kw)
    return OpeningPosition(**base)  # type: ignore[arg-type]


def _open_lots(ledger, account_id: str, symbol: str) -> Decimal:  # type: ignore[no-untyped-def]
    return sum(
        (
            lot.remaining
            for lot in ledger.lots
            if lot.remaining > 0
            and lot.account_id == account_id
            and ledger.symbols.get(lot.instrument_id, lot.instrument_id) == symbol
        ),
        Decimal(0),
    )


class TestTransferDirectionBecomesDeterminable:
    """The real defect. Two ITRF legs, same day, same quantity, neither account visibly holding the
    shares -- so the direction was a guess. Declaring what the sender held makes it arithmetic."""

    def _legs(self) -> list[object]:
        return [
            make_txn(
                txn_id="leg-out",
                account_id="rh-taxable",
                broker=Broker.ROBINHOOD,
                action="internal_transfer",
                trade_date=dt.date(2026, 1, 13),
                symbol="GOOGL",
                quantity="10",
            ),
            make_txn(
                txn_id="leg-in",
                account_id="rh-short-cash",
                broker=Broker.ROBINHOOD,
                action="internal_transfer",
                trade_date=dt.date(2026, 1, 13),
                symbol="GOOGL",
                quantity="10",
            ),
        ]

    def test_without_an_opening_position_the_direction_is_nominated_and_flagged(self) -> None:
        ledger = build_lots(self._legs(), accounts=ACCOUNTS)  # type: ignore[arg-type]
        kinds = [w.kind for w in ledger.warnings]
        assert WarningKind.AMBIGUOUS_TRANSFER_DIRECTION in kinds
        # Whichever way it guessed, the total is conserved -- that part was never in doubt.
        held = _open_lots(ledger, "rh-taxable", "GOOGL") + _open_lots(
            ledger, "rh-short-cash", "GOOGL"
        )
        assert held == Decimal("10")

    def test_declaring_what_the_sender_held_removes_the_guess(self) -> None:
        ledger = build_lots(
            self._legs(),  # type: ignore[arg-type]
            accounts=ACCOUNTS,
            opening=[opening()],
        )
        assert not [
            w for w in ledger.warnings if w.kind is WarningKind.AMBIGUOUS_TRANSFER_DIRECTION
        ]
        # The shares leave the account that had them and arrive in the one that did not.
        assert _open_lots(ledger, "rh-taxable", "GOOGL") == Decimal("0")
        assert _open_lots(ledger, "rh-short-cash", "GOOGL") == Decimal("10")


class TestFifoReachesTheOpeningLotFirst:
    def test_the_oldest_shares_are_sold_first(self) -> None:
        """They are the oldest shares in the account by definition, so FIFO must reach them before
        anything bought inside the window. Getting this backwards would report the wrong basis on
        every sale that spans the boundary."""
        rows = [
            make_txn(
                txn_id="buy",
                account_id="rh-taxable",
                broker=Broker.ROBINHOOD,
                trade_date=dt.date(2026, 2, 1),
                symbol="AMD",
                quantity="10",
                price="100.00",
                amount="-1000.00",
            ),
            make_txn(
                txn_id="sell",
                account_id="rh-taxable",
                broker=Broker.ROBINHOOD,
                action="sell",
                trade_date=dt.date(2026, 3, 1),
                symbol="AMD",
                quantity="5",
                price="200.00",
                amount="1000.00",
            ),
        ]
        ledger = build_lots(
            rows,  # type: ignore[arg-type]
            accounts=ACCOUNTS,
            opening=[
                opening(symbol="AMD", quantity=Decimal("5"), cost_basis=Decimal("400.00"))
            ],
        )
        assert len(ledger.disposals) == 1
        disposal = ledger.disposals[0]
        assert disposal.quantity == Decimal("5")
        # The opening lot's basis, not the February purchase's $500.
        assert disposal.cost_basis == Decimal("400.00")
        assert disposal.acquired_date == dt.date(2026, 1, 5)
        assert _open_lots(ledger, "rh-taxable", "AMD") == Decimal("10")

    def test_it_prevents_the_oversold_warning_it_exists_to_explain(self) -> None:
        rows = [
            make_txn(
                txn_id="sell",
                account_id="rh-taxable",
                broker=Broker.ROBINHOOD,
                action="sell",
                trade_date=dt.date(2026, 3, 1),
                symbol="AMD",
                quantity="5",
                price="200.00",
                amount="1000.00",
            )
        ]
        without = build_lots(rows, accounts=ACCOUNTS)  # type: ignore[arg-type]
        assert [w for w in without.warnings if w.kind is WarningKind.OVERSOLD]

        with_opening = build_lots(
            rows,  # type: ignore[arg-type]
            accounts=ACCOUNTS,
            opening=[opening(symbol="AMD", quantity=Decimal("5"), cost_basis=Decimal("400.00"))],
        )
        assert not [w for w in with_opening.warnings if w.kind is WarningKind.OVERSOLD]


class TestMissingBasisIsFlaggedNotAssumed:
    """An absent ``cost_basis`` must never be read as "these shares were free". It is the same
    distinction the rest of this module keeps between a withheld figure and a zero."""

    def _sold(self) -> list[object]:
        return [
            make_txn(
                txn_id="sell",
                account_id="rh-taxable",
                broker=Broker.ROBINHOOD,
                action="sell",
                trade_date=dt.date(2026, 3, 1),
                symbol="META",
                quantity="5",
                price="655.00",
                amount="3275.00",
            )
        ]

    def test_no_basis_raises_missing_basis_and_marks_the_lot(self) -> None:
        ledger = build_lots(
            self._sold(),  # type: ignore[arg-type]
            accounts=ACCOUNTS,
            opening=[opening(symbol="META", quantity=Decimal("5"))],
        )
        opening_warnings = [
            w
            for w in ledger.warnings
            if w.kind is WarningKind.MISSING_BASIS and "opening position" in w.detail
        ]
        assert len(opening_warnings) == 1
        assert opening_warnings[0].symbol == "META"
        # The gain is the whole proceeds, which is the bound, and the warning is what says so.
        assert ledger.disposals[0].cost_basis == Decimal("0")

    def test_a_declared_basis_is_used_and_raises_nothing(self) -> None:
        ledger = build_lots(
            self._sold(),  # type: ignore[arg-type]
            accounts=ACCOUNTS,
            opening=[
                opening(symbol="META", quantity=Decimal("5"), cost_basis=Decimal("3000.00"))
            ],
        )
        assert not [
            w
            for w in ledger.warnings
            if w.kind is WarningKind.MISSING_BASIS and "opening position" in w.detail
        ]
        assert ledger.disposals[0].cost_basis == Decimal("3000.00")
        assert ledger.disposals[0].gain_loss == Decimal("275.00")


class TestDatesAndKeys:
    def test_acquired_date_decides_the_holding_period_when_known(self) -> None:
        """`as_of` is when the position was *stated*; `acquired_date` is when it was bought. Using
        the former makes the holding period shorter than the truth, which can only overstate tax --
        the safe direction, and the reason `acquired_date` is worth supplying."""
        ledger = build_lots(
            [],  # type: ignore[arg-type]
            accounts=ACCOUNTS,
            opening=[opening(acquired_date=dt.date(2023, 4, 1))],
        )
        assert ledger.lots[0].acquired_date == dt.date(2023, 4, 1)

    def test_without_acquired_date_the_as_of_date_is_used(self) -> None:
        ledger = build_lots([], accounts=ACCOUNTS, opening=[opening()])  # type: ignore[arg-type]
        assert ledger.lots[0].acquired_date == dt.date(2026, 1, 5)

    def test_a_position_is_matched_to_the_instrument_id_its_account_already_uses(self) -> None:
        """Declared by symbol, because that is what a broker screen shows. The replay keys on
        `instrument_id`, so a mismatch here would open a lot nothing ever consumes -- which looks
        exactly like the phantom holding this feature removes."""
        # A CUSIP-resolved instrument id, which is what a real Robinhood row carries and what makes
        # the key differ from the bare symbol.
        rows = [
            make_txn(
                txn_id="buy",
                account_id="rh-taxable",
                broker=Broker.ROBINHOOD,
                trade_date=dt.date(2026, 2, 1),
                symbol="AMD",
                quantity="10",
                price="100.00",
                amount="-1000.00",
            ).model_copy(update={"instrument_id": "instr-amd-from-cusip"})
        ]
        ledger = build_lots(
            rows,  # type: ignore[arg-type]
            accounts=ACCOUNTS,
            opening=[opening(symbol="amd", quantity=Decimal("5"))],
        )
        instrument_ids = {lot.instrument_id for lot in ledger.lots}
        assert len(instrument_ids) == 1, "the opening lot must share the traded instrument's id"
        assert _open_lots(ledger, "rh-taxable", "AMD") == Decimal("15")

    def test_a_symbol_never_traded_inside_the_window_still_opens_a_lot(self) -> None:
        """The commonest case, and the one the feature is named for: held throughout, traded never."""
        ledger = build_lots(
            [],  # type: ignore[arg-type]
            accounts=ACCOUNTS,
            opening=[opening(symbol="BRK.B", quantity=Decimal("20"))],
        )
        assert _open_lots(ledger, "rh-taxable", "BRK.B") == Decimal("20")

    def test_no_openings_is_the_untouched_path(self) -> None:
        rows = [
            make_txn(
                txn_id="buy",
                account_id="rh-taxable",
                broker=Broker.ROBINHOOD,
                trade_date=dt.date(2026, 2, 1),
                symbol="AMD",
                quantity="10",
                price="100.00",
                amount="-1000.00",
            )
        ]
        assert build_lots(rows, accounts=ACCOUNTS) == build_lots(  # type: ignore[arg-type]
            rows,  # type: ignore[arg-type]
            accounts=ACCOUNTS,
            opening=[],
        )

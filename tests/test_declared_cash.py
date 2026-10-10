"""Declared cash: a balance the user states because no export contains one.

``tests/test_cash.py`` is about the module's refusal to derive a balance it cannot support. This file
is about the escape hatch that refusal made necessary. On real exports every account was
withheld -- Webull exports order history with no cash rows at all, and the Robinhood export begins
after the account was funded -- so total equity was permanently unavailable no matter how good the
derivation got. The choice was a declared figure or none.

The risk a declared figure introduces is different in kind from a derived one, and every test here
is about keeping the two apart. A derived balance is wrong only if the ledger is wrong. A declared
balance is a **snapshot**: it is correct on the day it is read and drifts silently from then on, and
nothing in this system can notice that happening. So it may not exist without its ``as_of`` date, it
carries its own verdict rather than passing as derived, and it never suppresses the derivation whose
disagreement is the only signal that one of the two is stale.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.core.cash import CashVerdict, DeclaredCash, build_cash
from app.core.models import Account, AccountType, Broker, TaxTreatment
from tests.conftest import make_txn

AS_OF = dt.date(2026, 8, 14)


def account(
    account_id: str = "wb-margin",
    *,
    broker: Broker = Broker.WEBULL,
    account_type: AccountType = AccountType.CASH,
) -> Account:
    return Account(
        account_id=account_id,
        broker=broker,
        label=account_id,
        tax_treatment=TaxTreatment.TAXABLE,
        account_type=account_type,
    )


def declaration(
    account_id: str = "wb-margin",
    *,
    balance: str = "13000.00",
    settled: str | None = None,
    unsettled: str | None = None,
    as_of: dt.date = AS_OF,
    note: str = "",
) -> DeclaredCash:
    return DeclaredCash(
        account_id=account_id,
        balance=Decimal(balance),
        as_of=as_of,
        settled=None if settled is None else Decimal(settled),
        unsettled=None if unsettled is None else Decimal(unsettled),
        note=note,
    )


# ---------------------------------------------------------------------------
# The invariant a declaration has to satisfy before it is allowed to be a figure
# ---------------------------------------------------------------------------


class TestDeclarationValidation:
    def test_a_split_that_adds_up_is_accepted(self) -> None:
        declaration(settled="1500.00", unsettled="7500.00", balance="9000.00").validate()

    def test_settled_may_be_negative(self) -> None:
        """A Webull cash account can carry unsettled proceeds against negative settled cash.
        Only *unsettled* is constrained to be non-negative -- it is proceeds not yet available, so
        there is no such thing as less than none of it."""
        declaration(settled="-4000.00", unsettled="17000.00", balance="13000.00").validate()

    def test_a_split_that_does_not_add_up_is_refused(self) -> None:
        with pytest.raises(ValueError, match="does not add up"):
            declaration(settled="1000.00", unsettled="1000.00", balance="9000.00").validate()

    def test_negative_unsettled_is_refused(self) -> None:
        with pytest.raises(ValueError, match="can never be negative"):
            declaration(settled="200.00", unsettled="-100.00", balance="100.00").validate()

    def test_half_a_split_is_refused(self) -> None:
        """Not a pedantic check: with only one side given there is nothing to test the balance
        against, so a typo in it would pass straight through into a total."""
        with pytest.raises(ValueError, match="only one of settled/unsettled"):
            declaration(settled="1000.00").validate()
        with pytest.raises(ValueError, match="only one of settled/unsettled"):
            declaration(unsettled="1000.00").validate()

    def test_no_split_at_all_is_fine(self) -> None:
        """Robinhood reports a single buying-power figure and no split. Requiring one would mean
        rejecting the balance the user actually has."""
        declaration(account_id="rh-taxable", balance="11077.15").validate()


# ---------------------------------------------------------------------------
# What a declaration does to the ledger
# ---------------------------------------------------------------------------


class TestDeclarationOverridesAWithheldBalance:
    def _webull_like(self) -> list[object]:
        """Trades and nothing else -- the shape that makes `no_funding_rows` fire."""
        return [
            make_txn(
                txn_id="t1",
                account_id="wb-margin",
                broker=Broker.WEBULL,
                trade_date=dt.date(2026, 1, 15),
                symbol="NVDA",
                quantity="10",
                price="200.00",
                amount="-2000.00",
            )
        ]

    def test_without_a_declaration_the_balance_is_withheld(self) -> None:
        ledger = build_cash(
            self._webull_like(), accounts={"wb-margin": account()}, as_of=AS_OF  # type: ignore[arg-type]
        )
        entry = ledger.accounts[0]
        assert entry.verdict is CashVerdict.NO_FUNDING_ROWS
        assert entry.balance is None
        assert ledger.total is None

    def test_a_declaration_supplies_the_balance_and_its_own_verdict(self) -> None:
        ledger = build_cash(
            self._webull_like(),  # type: ignore[arg-type]
            accounts={"wb-margin": account()},
            as_of=AS_OF,
            declared={"wb-margin": declaration(settled="-4000.00", unsettled="17000.00")},
        )
        entry = ledger.accounts[0]
        assert entry.verdict is CashVerdict.DECLARED
        assert entry.balance == Decimal("13000.00")
        assert entry.settled == Decimal("-4000.00")
        assert entry.unsettled == Decimal("17000.00")
        assert ledger.total == Decimal("13000.00")
        assert ledger.is_complete

    def test_the_as_of_date_travels_with_the_figure(self) -> None:
        """A declared balance without the date it was true is indistinguishable from a current one,
        which is the whole risk this verdict exists to keep visible."""
        ledger = build_cash(
            self._webull_like(),  # type: ignore[arg-type]
            accounts={"wb-margin": account()},
            as_of=AS_OF,
            declared={"wb-margin": declaration(as_of=dt.date(2026, 6, 1))},
        )
        entry = ledger.accounts[0]
        assert entry.declared_as_of == dt.date(2026, 6, 1)
        assert "2026-06-01" in (entry.reason or "")

    def test_a_reason_accompanies_the_figure_rather_than_replacing_one(self) -> None:
        """Everywhere else in this module a reason means "there is no number". Here there is one, and
        the reason says where it came from and that it does not move."""
        ledger = build_cash(
            self._webull_like(),  # type: ignore[arg-type]
            accounts={"wb-margin": account()},
            as_of=AS_OF,
            declared={"wb-margin": declaration(note="read off the app")},
        )
        entry = ledger.accounts[0]
        assert entry.balance is not None
        reason = entry.reason or ""
        assert "declared" in reason
        assert "does not update" in reason
        assert "read off the app" in reason

    def test_the_withheld_balance_diagnostics_are_cleared(self) -> None:
        """`missing_opening_balance` and `first_negative_on` belong to a verdict this account no
        longer has; leaving them set would have the UI explain a withholding that did not happen."""
        rows = [
            make_txn(
                txn_id="sell",
                account_id="rh-taxable",
                broker=Broker.ROBINHOOD,
                trade_date=dt.date(2026, 1, 5),
                symbol="AAPL",
                quantity="10",
                price="100.00",
                amount="-1000.00",
            ),
        ]
        accounts = {"rh-taxable": account("rh-taxable", broker=Broker.ROBINHOOD)}
        before = build_cash(rows, accounts=accounts, as_of=AS_OF)  # type: ignore[arg-type]
        assert before.accounts[0].verdict is not CashVerdict.DERIVED

        after = build_cash(
            rows,  # type: ignore[arg-type]
            accounts=accounts,
            as_of=AS_OF,
            declared={"rh-taxable": declaration("rh-taxable", balance="11077.15")},
        )
        entry = after.accounts[0]
        assert entry.missing_opening_balance is None
        assert entry.first_negative_on is None


class TestDeclarationDoesNotSuppressTheDerivation:
    """The derivation keeps running, and where it produced a trustworthy figure that figure is kept
    alongside the declared one. The two disagreeing is the only signal available that the export is
    incomplete or the declaration is stale, and resolving it silently would throw that away."""

    def _funded(self) -> list[object]:
        return [
            make_txn(
                txn_id="dep",
                account_id="rh-taxable",
                broker=Broker.ROBINHOOD,
                trade_date=dt.date(2026, 1, 2),
                action="cash_in",
                amount="5000.00",
            )
        ]

    def test_a_disagreeing_derived_balance_is_kept_and_surfaced(self) -> None:
        accounts = {"rh-taxable": account("rh-taxable", broker=Broker.ROBINHOOD)}
        derived_only = build_cash(self._funded(), accounts=accounts, as_of=AS_OF)  # type: ignore[arg-type]
        assert derived_only.accounts[0].verdict is CashVerdict.DERIVED
        assert derived_only.accounts[0].balance == Decimal("5000.00")

        ledger = build_cash(
            self._funded(),  # type: ignore[arg-type]
            accounts=accounts,
            as_of=AS_OF,
            declared={"rh-taxable": declaration("rh-taxable", balance="11077.15")},
        )
        entry = ledger.accounts[0]
        assert entry.balance == Decimal("11077.15")
        assert entry.derived_balance == Decimal("5000.00")
        assert "disagrees" in (entry.reason or "")

    def test_a_withheld_derivation_is_not_recorded_as_agreement(self) -> None:
        """`derived_balance` stays None when the derivation was withheld. A withheld figure is not
        evidence that the declaration matches anything."""
        rows = [
            make_txn(
                txn_id="t1",
                account_id="wb-margin",
                broker=Broker.WEBULL,
                trade_date=dt.date(2026, 1, 15),
                symbol="NVDA",
                quantity="10",
                price="200.00",
                amount="-2000.00",
            )
        ]
        ledger = build_cash(
            rows,  # type: ignore[arg-type]
            accounts={"wb-margin": account()},
            as_of=AS_OF,
            declared={"wb-margin": declaration()},
        )
        entry = ledger.accounts[0]
        assert entry.derived_balance is None
        assert "disagrees" not in (entry.reason or "")


class TestUndeclaredAccountsAreUnaffected:
    def test_an_account_without_a_declaration_still_derives_or_withholds(self) -> None:
        rows = [
            make_txn(
                txn_id="dep",
                account_id="rh-taxable",
                broker=Broker.ROBINHOOD,
                trade_date=dt.date(2026, 1, 2),
                action="cash_in",
                amount="5000.00",
            ),
            make_txn(
                txn_id="t1",
                account_id="wb-margin",
                broker=Broker.WEBULL,
                trade_date=dt.date(2026, 1, 15),
                symbol="NVDA",
                quantity="10",
                price="200.00",
                amount="-2000.00",
            ),
        ]
        ledger = build_cash(
            rows,  # type: ignore[arg-type]
            accounts={
                "rh-taxable": account("rh-taxable", broker=Broker.ROBINHOOD),
                "wb-margin": account(),
            },
            as_of=AS_OF,
            declared={"wb-margin": declaration()},
        )
        by_id = {entry.account_id: entry for entry in ledger.accounts}
        assert by_id["rh-taxable"].verdict is CashVerdict.DERIVED
        assert by_id["wb-margin"].verdict is CashVerdict.DECLARED
        # Both are trustworthy, so both count -- and the total is the sum of a derived and a
        # declared figure, which is exactly why the per-account verdict has to stay visible.
        assert ledger.total == Decimal("5000.00") + Decimal("13000.00")
        assert ledger.is_complete

    def test_no_declarations_at_all_is_the_untouched_path(self) -> None:
        rows = [
            make_txn(
                txn_id="dep",
                account_id="rh-taxable",
                broker=Broker.ROBINHOOD,
                trade_date=dt.date(2026, 1, 2),
                action="cash_in",
                amount="5000.00",
            )
        ]
        accounts = {"rh-taxable": account("rh-taxable", broker=Broker.ROBINHOOD)}
        assert build_cash(rows, accounts=accounts, as_of=AS_OF) == build_cash(  # type: ignore[arg-type]
            rows,  # type: ignore[arg-type]
            accounts=accounts,
            as_of=AS_OF,
            declared={},
        )


class TestInvalidDeclarationsAreRefusedAtBuildTime:
    def test_build_cash_raises_rather_than_totalling_a_contradiction(self) -> None:
        rows = [
            make_txn(
                txn_id="t1",
                account_id="wb-margin",
                broker=Broker.WEBULL,
                trade_date=dt.date(2026, 1, 15),
                symbol="NVDA",
                quantity="10",
                price="200.00",
                amount="-2000.00",
            )
        ]
        with pytest.raises(ValueError, match="does not add up"):
            build_cash(
                rows,  # type: ignore[arg-type]
                accounts={"wb-margin": account()},
                as_of=AS_OF,
                declared={
                    "wb-margin": declaration(settled="1.00", unsettled="1.00", balance="999.00")
                },
            )

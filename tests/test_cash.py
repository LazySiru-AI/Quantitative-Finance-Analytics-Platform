"""Cash derivation, and -- more importantly -- refusal to derive.

The arithmetic in :mod:`app.core.cash` is a sum. Almost every test here is instead about the two
checks that decide whether the sum may be shown at all, because that is where the harm lives: a
wrong balance is indistinguishable from a right one on screen, and it is the figure a user sizes a
trade against.

The two failure modes are drawn from the real exports this application ingests, not invented:
Webull's export is order history with no funding rows, and several Robinhood exports begin after the
account was funded. ``TestAgainstRealExports`` pins both against the user's actual data when it is
present.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.core.cash import FUNDING_ACTIONS, CashVerdict, DeclaredCash, build_cash
from app.core.models import Account, AccountType, Broker, TaxTreatment, TxnAction
from tests.conftest import make_txn, requires_real_data

AS_OF = dt.date(2026, 3, 31)


def account(
    account_id: str = "rh-taxable",
    *,
    broker: Broker = Broker.ROBINHOOD,
    account_type: AccountType = AccountType.CASH,
) -> Account:
    return Account(
        account_id=account_id,
        broker=broker,
        label=account_id.upper(),
        tax_treatment=TaxTreatment.TAXABLE,
        account_type=account_type,
    )


def funded(amount: str = "10000.00", *, day: int = 1, account_id: str = "rh-taxable"):  # type: ignore[no-untyped-def]
    """An opening deposit. Present in almost every fixture because without one, nothing derives."""
    return make_txn(
        txn_id=f"dep-{account_id}-{day}",
        action=TxnAction.CASH_IN,
        symbol=None,
        quantity=None,
        price=None,
        amount=amount,
        trade_date=dt.date(2026, 1, day),
        account_id=account_id,
    )


class TestDerivation:
    def test_deposit_less_purchase_is_the_balance(self) -> None:
        txns = [
            funded("10000.00"),
            make_txn(
                txn_id="buy",
                action=TxnAction.BUY,
                amount="-2500.00",
                trade_date=dt.date(2026, 2, 1),
            ),
        ]
        ledger = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF)

        assert ledger.total == Decimal("7500.00")
        assert ledger.is_complete
        assert ledger.accounts[0].verdict is CashVerdict.DERIVED

    def test_rows_without_an_amount_do_not_move_cash(self) -> None:
        """An ACAT position leg carries shares and no amount. Counting it would be a made-up figure,
        and counting it as zero is exactly right -- the shares moved, the cash did not."""
        txns = [
            funded("5000.00"),
            make_txn(
                txn_id="acat-position",
                action=TxnAction.TRANSFER_IN,
                symbol="AAA",
                quantity="10",
                price=None,
                amount=None,
                trade_date=dt.date(2026, 2, 1),
            ),
        ]
        ledger = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF)

        assert ledger.total == Decimal("5000.00")
        assert ledger.accounts[0].cash_row_count == 1

    def test_income_and_fees_are_included(self) -> None:
        txns = [
            funded("1000.00"),
            make_txn(
                txn_id="div",
                action=TxnAction.DIVIDEND,
                symbol="AAA",
                quantity=None,
                price=None,
                amount="12.50",
                trade_date=dt.date(2026, 2, 1),
            ),
            make_txn(
                txn_id="fee",
                action=TxnAction.FEE,
                symbol=None,
                quantity=None,
                price=None,
                amount="-2.50",
                trade_date=dt.date(2026, 2, 2),
            ),
        ]
        ledger = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF)

        assert ledger.total == Decimal("1010.00")

    def test_an_account_with_no_transactions_is_not_an_error(self) -> None:
        ledger = build_cash([], accounts={"rh-taxable": account()}, as_of=AS_OF)

        assert ledger.accounts[0].verdict is CashVerdict.NO_TRANSACTIONS
        assert ledger.total is None
        # An account with nothing in it is not a *gap* in the total -- there is nothing to exclude.
        assert ledger.accounts_without_cash == ()
        assert ledger.is_complete

    def test_transactions_for_unknown_accounts_are_ignored(self) -> None:
        """Not silently folded into some other account's balance."""
        txns = [funded("1000.00"), funded("999.00", account_id="ghost")]
        ledger = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF)

        assert ledger.total == Decimal("1000.00")
        assert [a.account_id for a in ledger.accounts] == ["rh-taxable"]


class TestNoFundingRows:
    """Webull's shape: trades and nothing else."""

    def test_trades_alone_cannot_establish_a_balance(self) -> None:
        txns = [
            make_txn(
                txn_id="b",
                action=TxnAction.BUY,
                amount="-5000.00",
                trade_date=dt.date(2026, 1, 5),
                account_id="wb-cash",
                broker=Broker.WEBULL,
            ),
            make_txn(
                txn_id="s",
                action=TxnAction.SELL,
                amount="6000.00",
                trade_date=dt.date(2026, 2, 5),
                account_id="wb-cash",
                broker=Broker.WEBULL,
            ),
        ]
        ledger = build_cash(
            txns, accounts={"wb-cash": account("wb-cash", broker=Broker.WEBULL)}, as_of=AS_OF
        )
        entry = ledger.accounts[0]

        assert entry.verdict is CashVerdict.NO_FUNDING_ROWS
        # The naive answer would have been +1000. Withheld, not returned with a flag.
        assert entry.balance is None
        assert entry.settled is None and entry.unsettled is None
        assert ledger.total is None
        assert ledger.accounts_without_cash == ("wb-cash",)
        assert not ledger.is_complete
        assert entry.reason is not None and "order history" in entry.reason

    def test_a_single_funding_row_is_enough_to_try(self) -> None:
        """The verdict is decided by what the export contains, not by which broker produced it, so an
        adapter that gains cash-row support starts deriving without any change here."""
        txns = [
            funded("10000.00", account_id="wb-cash"),
            make_txn(
                txn_id="b",
                action=TxnAction.BUY,
                amount="-5000.00",
                trade_date=dt.date(2026, 2, 5),
                account_id="wb-cash",
                broker=Broker.WEBULL,
            ),
        ]
        ledger = build_cash(
            txns, accounts={"wb-cash": account("wb-cash", broker=Broker.WEBULL)}, as_of=AS_OF
        )

        assert ledger.accounts[0].verdict is CashVerdict.DERIVED
        assert ledger.total == Decimal("5000.00")

    @pytest.mark.parametrize("action", sorted(FUNDING_ACTIONS, key=lambda a: a.value))
    def test_every_funding_action_counts_as_funding(self, action: TxnAction) -> None:
        txns = [
            make_txn(
                txn_id="fund",
                action=action,
                symbol=None,
                quantity=None,
                price=None,
                amount="1000.00",
                trade_date=dt.date(2026, 1, 2),
            )
        ]
        ledger = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF)

        assert ledger.accounts[0].funding_row_count == 1
        assert ledger.accounts[0].verdict is CashVerdict.DERIVED

    def test_a_funding_row_with_no_amount_does_not_count(self) -> None:
        """An ACAT position leg is a ``TRANSFER_IN`` and carries no cash. It must not be mistaken for
        evidence that the export records cash movements."""
        txns = [
            make_txn(
                txn_id="acat",
                action=TxnAction.TRANSFER_IN,
                symbol="AAA",
                quantity="10",
                price=None,
                amount=None,
                trade_date=dt.date(2026, 1, 2),
            ),
            make_txn(
                txn_id="sell",
                action=TxnAction.SELL,
                amount="900.00",
                trade_date=dt.date(2026, 2, 2),
            ),
        ]
        ledger = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF)

        assert ledger.accounts[0].verdict is CashVerdict.NO_FUNDING_ROWS


class TestNegativeBalance:
    def test_a_closing_negative_is_caught(self) -> None:
        txns = [
            funded("1000.00"),
            make_txn(
                txn_id="buy",
                action=TxnAction.BUY,
                amount="-1500.00",
                trade_date=dt.date(2026, 2, 1),
            ),
        ]
        ledger = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF)
        entry = ledger.accounts[0]

        assert entry.verdict is CashVerdict.NEGATIVE_IN_CASH_ACCOUNT
        assert entry.balance is None
        assert entry.missing_opening_balance == Decimal("500.00")
        assert entry.first_negative_on == dt.date(2026, 2, 1)

    def test_a_transient_negative_is_caught_even_when_the_close_is_positive(self) -> None:
        """The case a closing-balance check misses, and the reason the check is on the running
        minimum. Modelled on the real ``rh-taxable`` export: it ends solidly positive only because
        its final day is full of sales, and rewinding past them puts the account underwater."""
        txns = [
            funded("100.00"),
            make_txn(
                txn_id="buy",
                action=TxnAction.BUY,
                amount="-5000.00",
                trade_date=dt.date(2026, 2, 1),
            ),
            make_txn(
                txn_id="sell",
                action=TxnAction.SELL,
                amount="9000.00",
                trade_date=dt.date(2026, 3, 1),
            ),
        ]
        ledger = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF)
        entry = ledger.accounts[0]

        assert entry.verdict is CashVerdict.NEGATIVE_IN_CASH_ACCOUNT
        assert entry.missing_opening_balance == Decimal("4900.00")
        assert entry.reason is not None and "4,900.00" in entry.reason

    def test_same_day_ordering_uses_sequence(self) -> None:
        """A buy and a sell on one day net out, but the order decides whether the account dipped.
        ``sequence`` is the ledger's own tie-break and must be honoured here too, or a same-day pair
        would flip the verdict depending on how the caller happened to sort."""
        buy_first = [
            funded("100.00"),
            make_txn(
                txn_id="buy",
                action=TxnAction.BUY,
                amount="-500.00",
                trade_date=dt.date(2026, 2, 1),
                sequence=0,
            ),
            make_txn(
                txn_id="sell",
                action=TxnAction.SELL,
                amount="600.00",
                trade_date=dt.date(2026, 2, 1),
                sequence=1,
            ),
        ]
        # Handed in reversed, to prove the caller's order does not decide the answer.
        ledger = build_cash(
            list(reversed(buy_first)), accounts={"rh-taxable": account()}, as_of=AS_OF
        )

        assert ledger.accounts[0].verdict is CashVerdict.NEGATIVE_IN_CASH_ACCOUNT
        assert ledger.accounts[0].missing_opening_balance == Decimal("400.00")

    def test_margin_accounts_may_hold_a_debit(self) -> None:
        txns = [
            funded("1000.00", account_id="wb-margin"),
            make_txn(
                txn_id="buy",
                action=TxnAction.BUY,
                amount="-1500.00",
                trade_date=dt.date(2026, 2, 1),
                account_id="wb-margin",
            ),
        ]
        ledger = build_cash(
            txns,
            accounts={"wb-margin": account("wb-margin", account_type=AccountType.MARGIN)},
            as_of=AS_OF,
        )

        assert ledger.accounts[0].verdict is CashVerdict.DERIVED
        assert ledger.accounts[0].balance == Decimal("-500.00")


class TestSettlement:
    def test_proceeds_settling_after_as_of_are_unsettled(self) -> None:
        txns = [
            funded("1000.00"),
            make_txn(
                txn_id="sell",
                action=TxnAction.SELL,
                amount="500.00",
                trade_date=dt.date(2026, 3, 31),
                settle_date=dt.date(2026, 4, 1),
            ),
        ]
        ledger = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF)
        entry = ledger.accounts[0]

        assert entry.balance == Decimal("1500.00")
        assert entry.unsettled == Decimal("500.00")
        assert entry.settled == Decimal("1000.00")

    def test_a_row_with_no_settle_date_counts_as_settled(self) -> None:
        txns = [funded("1000.00")]
        ledger = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF)

        assert ledger.accounts[0].unsettled == Decimal(0)
        assert ledger.accounts[0].settled == Decimal("1000.00")

    def test_an_unsettled_purchase_is_not_unsettled_cash(self) -> None:
        """The money is committed at the fill, not at settlement, so it never comes back here.

        Counting purchases made ``settled`` = balance minus a negative, i.e. **larger than the
        balance**: a fresh account with a $10,000 deposit and six unsettled buys totalling $7,018.14
        reported "$10,000.00 settled" while holding $2,981.86. A UAT persona found it on the
        Portfolio page and in the downloaded statement, and named the consequence — that is the
        figure someone sizes a position against.
        """
        txns = [
            funded("10000.00"),
            make_txn(
                txn_id="buy",
                action=TxnAction.BUY,
                amount="-7018.14",
                trade_date=dt.date(2026, 3, 31),
                settle_date=dt.date(2026, 4, 1),
            ),
        ]
        entry = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF).accounts[0]

        assert entry.balance == Decimal("2981.86")
        assert entry.unsettled == Decimal(0)
        assert entry.settled == Decimal("2981.86")

    def test_settled_never_exceeds_the_balance(self) -> None:
        """The invariant behind the above, stated on its own.

        `settled` answers "what can I deploy". Any arrangement of rows that lets it exceed what is
        actually in the account is wrong regardless of how the arithmetic got there.
        """
        txns = [
            funded("10000.00"),
            make_txn(
                txn_id="b1",
                action=TxnAction.BUY,
                amount="-4000.00",
                trade_date=dt.date(2026, 3, 30),
                settle_date=dt.date(2026, 4, 2),
            ),
            make_txn(
                txn_id="s1",
                action=TxnAction.SELL,
                amount="600.00",
                trade_date=dt.date(2026, 3, 31),
                settle_date=dt.date(2026, 4, 1),
            ),
        ]
        entry = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF).accounts[0]

        assert entry.balance is not None and entry.settled is not None
        assert entry.unsettled == Decimal("600.00")
        assert entry.settled <= entry.balance
        assert entry.settled == Decimal("6000.00")

    def test_settled_plus_unsettled_is_the_balance(self) -> None:
        txns = [
            funded("1000.00"),
            make_txn(
                txn_id="s1",
                action=TxnAction.SELL,
                amount="250.00",
                trade_date=dt.date(2026, 3, 30),
                settle_date=dt.date(2026, 4, 1),
            ),
            make_txn(
                txn_id="s2",
                action=TxnAction.SELL,
                amount="125.00",
                trade_date=dt.date(2026, 3, 20),
                settle_date=dt.date(2026, 3, 21),
            ),
        ]
        entry = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF).accounts[0]

        assert entry.settled is not None and entry.unsettled is not None
        assert entry.settled + entry.unsettled == entry.balance

    def test_fee_on_a_pending_sale_nets_into_unsettled(self) -> None:
        """A regulatory fee on a not-yet-settled sale is a separate row with a negative amount and
        the *same* settle_date as the sale. The old filter (``t.amount > 0``) kept that row out of
        ``unsettled`` -- it was already inside ``balance`` but never subtracted back out -- so
        ``unsettled`` read gross proceeds and ``settled`` came in short by exactly the fee.

        Measured against two independent UAT persona runs, scaling with the fee: a TLT sale with a
        $0.02 fee showed ``settled`` 1750.66 (true 1750.68) and ``unsettled`` 837.00 gross (true
        836.98 net); a QQQ sale with a $0.06 fee showed ``settled`` 1247.61 (true 1247.67) and
        ``unsettled`` 2082.96 gross (true 2082.90 net). This fixture reproduces the same shape with
        exact, hand-checkable numbers: a $837.00 sale with a $0.02 fee, both settling after ``as_of``.

        The fix keys off what the row *is* (``action``), not the sign of its ``amount`` -- a purchase
        is excluded regardless of how negative it is, and a fee on a pending sale is included
        regardless of being negative, because it reduces proceeds that have not arrived yet rather
        than being money already spent.
        """
        txns = [
            funded("2000.00"),
            make_txn(
                txn_id="sell",
                action=TxnAction.SELL,
                amount="837.00",
                trade_date=dt.date(2026, 3, 31),
                settle_date=dt.date(2026, 4, 2),
            ),
            make_txn(
                txn_id="fee",
                action=TxnAction.FEE,
                symbol=None,
                quantity=None,
                price=None,
                amount="-0.02",
                trade_date=dt.date(2026, 3, 31),
                settle_date=dt.date(2026, 4, 2),
            ),
        ]
        entry = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF).accounts[0]

        assert entry.balance == Decimal("2836.98")
        # Net of the fee, not gross of it.
        assert entry.unsettled == Decimal("836.98")
        # Ties to what is actually spendable today: the deposit, untouched by proceeds that have
        # not landed yet.
        assert entry.settled == Decimal("2000.00")
        assert entry.settled is not None and entry.unsettled is not None
        assert entry.settled + entry.unsettled == entry.balance
        assert entry.unsettled >= 0

    def test_fee_on_an_already_settled_sale_does_not_affect_unsettled(self) -> None:
        """A fee row carries its own settle_date. When that date is not after ``as_of`` -- the sale
        it rode along with has already settled -- the fee must stay out of ``unsettled`` exactly like
        any other settled row, not get swept in just because it shares an action with a pending fee
        elsewhere in the account."""
        txns = [
            funded("1000.00"),
            make_txn(
                txn_id="sell",
                action=TxnAction.SELL,
                amount="300.00",
                trade_date=dt.date(2026, 3, 1),
                settle_date=dt.date(2026, 3, 3),
            ),
            make_txn(
                txn_id="fee",
                action=TxnAction.FEE,
                symbol=None,
                quantity=None,
                price=None,
                amount="-0.05",
                trade_date=dt.date(2026, 3, 1),
                settle_date=dt.date(2026, 3, 3),
            ),
        ]
        entry = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF).accounts[0]

        assert entry.balance == Decimal("1299.95")
        assert entry.unsettled == Decimal(0)
        assert entry.settled == Decimal("1299.95")

    def test_a_fee_with_no_settle_date_counts_as_settled(self) -> None:
        """Mirrors :meth:`TestSettlement.test_a_row_with_no_settle_date_counts_as_settled` for the
        fee case specifically: a fee row that carries no settle_date at all -- the broker did not
        say -- is treated as settled, same as any other row, and must not leak into ``unsettled``."""
        txns = [
            funded("1000.00"),
            make_txn(
                txn_id="sell",
                action=TxnAction.SELL,
                amount="300.00",
                trade_date=dt.date(2026, 3, 31),
                settle_date=dt.date(2026, 4, 2),
            ),
            make_txn(
                txn_id="fee",
                action=TxnAction.FEE,
                symbol=None,
                quantity=None,
                price=None,
                amount="-0.03",
                trade_date=dt.date(2026, 3, 31),
                settle_date=None,
            ),
        ]
        entry = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF).accounts[0]

        assert entry.balance == Decimal("1299.97")
        assert entry.unsettled == Decimal("300.00")
        assert entry.settled == Decimal("999.97")

    def test_six_unsettled_purchases_do_not_inflate_settled(self) -> None:
        """The original defect, pinned with the exact shape a UAT persona hit: several separate
        unsettled purchases -- not one row standing in for all of them -- summing to $7,018.14 on a
        $10,000 deposit. None of the six may leak into ``unsettled``, and ``settled`` must land at
        the true $2,981.86 rather than the $10,000.00 the pre-fix page showed."""
        txns = [funded("10000.00")]
        amounts = ["-1000.00", "-1200.50", "-900.25", "-1500.00", "-1418.39", "-999.00"]
        for i, amt in enumerate(amounts):
            txns.append(
                make_txn(
                    txn_id=f"buy-{i}",
                    action=TxnAction.BUY,
                    amount=amt,
                    trade_date=dt.date(2026, 3, 31),
                    settle_date=dt.date(2026, 4, 2),
                )
            )
        entry = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF).accounts[0]

        assert entry.balance == Decimal("2981.86")
        assert entry.unsettled == Decimal(0)
        assert entry.settled == Decimal("2981.86")
        assert entry.settled is not None
        assert entry.settled <= entry.balance

    def test_a_pending_withdrawal_is_not_unsettled_cash(self) -> None:
        """`cash_out` is the same *kind* of row as a purchase: money the user told the broker to
        send out, committed the moment the request was made, not proceeds still in transit. A rule
        that excludes only `BUY` (`action is not TxnAction.BUY`) lets a pending `cash_out`'s negative
        amount net into `unsettled` and drive it negative -- `settled` then exceeds `balance`, the
        identical failure the six-buys case describes, through a different action code. A large
        pending withdrawal turned up in a real ledger during review of this fix."""
        txns = [
            funded("30000.00"),
            make_txn(
                txn_id="wd",
                action=TxnAction.CASH_OUT,
                symbol=None,
                quantity=None,
                price=None,
                amount="-20000.00",
                trade_date=dt.date(2026, 3, 31),
                settle_date=dt.date(2026, 4, 2),
            ),
        ]
        entry = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF).accounts[0]

        assert entry.balance == Decimal("10000.00")
        assert entry.unsettled is not None and entry.settled is not None
        assert entry.unsettled == Decimal(0)
        assert entry.settled == Decimal("10000.00")
        assert entry.unsettled >= 0
        assert entry.settled <= entry.balance

    def test_a_pending_outbound_transfer_is_not_unsettled_cash(self) -> None:
        """`transfer_out` is the cash leg of an ACAT leaving for another institution -- committed the
        moment the transfer was initiated, same reasoning as a withdrawal. Modelled on a real
        pending `internal_transfer`-shaped row found during review of this fix (this test
        covers the ACAT-out variant; the sibling test below covers the same-broker variant)."""
        txns = [
            funded("60000.00"),
            make_txn(
                txn_id="acat-out",
                action=TxnAction.TRANSFER_OUT,
                symbol=None,
                quantity=None,
                price=None,
                amount="-54000.00",
                trade_date=dt.date(2026, 3, 31),
                settle_date=dt.date(2026, 4, 2),
            ),
        ]
        entry = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF).accounts[0]

        assert entry.balance == Decimal("6000.00")
        assert entry.unsettled is not None and entry.settled is not None
        assert entry.unsettled == Decimal(0)
        assert entry.settled == Decimal("6000.00")
        assert entry.unsettled >= 0
        assert entry.settled <= entry.balance

    def test_a_pending_negative_internal_transfer_is_not_unsettled_cash(self) -> None:
        """`internal_transfer` (Robinhood `ITRF`) moves cash between the user's own accounts at the
        same broker and can be either sign depending on which account is the source -- the action
        code alone does not say. A negative row is money leaving this account for another one of the
        user's own accounts: committed, same as a withdrawal. Only the sign decides here, because the
        kind is genuinely ambiguous; this is the one case in the classification that still looks at
        `amount`, and it is deliberate -- see `_BIDIRECTIONAL_ACTIONS`. Shape of a real
        pending `internal_transfer` row found during review of this fix."""
        txns = [
            funded("60000.00"),
            make_txn(
                txn_id="itrf-out",
                action=TxnAction.INTERNAL_TRANSFER,
                symbol=None,
                quantity=None,
                price=None,
                amount="-54000.00",
                trade_date=dt.date(2026, 3, 31),
                settle_date=dt.date(2026, 4, 2),
            ),
        ]
        entry = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF).accounts[0]

        assert entry.balance == Decimal("6000.00")
        assert entry.unsettled is not None and entry.settled is not None
        assert entry.unsettled == Decimal(0)
        assert entry.settled == Decimal("6000.00")
        assert entry.unsettled >= 0
        assert entry.settled <= entry.balance

    def test_a_pending_positive_internal_transfer_nets_into_unsettled(self) -> None:
        """The other side of `_BIDIRECTIONAL_ACTIONS`: a positive `internal_transfer` is money
        arriving from another of the user's own accounts, not yet available if pending -- ordinary
        incoming cash, netted the same as a sale."""
        txns = [
            funded("1000.00"),
            make_txn(
                txn_id="itrf-in",
                action=TxnAction.INTERNAL_TRANSFER,
                symbol=None,
                quantity=None,
                price=None,
                amount="500.00",
                trade_date=dt.date(2026, 3, 31),
                settle_date=dt.date(2026, 4, 2),
            ),
        ]
        entry = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF).accounts[0]

        assert entry.balance == Decimal("1500.00")
        assert entry.unsettled == Decimal("500.00")
        assert entry.settled == Decimal("1000.00")

    def test_split_and_unsettled_are_withheld_together_when_the_split_cannot_stand_behind_zero(
        self,
    ) -> None:
        """The structural backstop: a pending `subscription_fee` with nothing pending on the other
        side of it to net against would drive `unsettled` negative under the netting rule that fixes
        the fee-on-a-sale case (fees are summed net into `unsettled`, not excluded like a purchase).
        Rather than publish that negative "proceeds" figure or a `settled` that exceeds `balance`,
        both fields come back `None` -- `balance` is untouched, because it never depended on the
        split -- and `reason` is populated even though `verdict` stays `DERIVED` and `balance` is
        still present, which is otherwise only true of `DECLARED`."""
        txns = [
            funded("1000.00"),
            make_txn(
                txn_id="gold",
                action=TxnAction.SUBSCRIPTION_FEE,
                symbol=None,
                quantity=None,
                price=None,
                amount="-50.00",
                trade_date=dt.date(2026, 3, 31),
                settle_date=dt.date(2026, 4, 2),
            ),
        ]
        entry = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF).accounts[0]

        assert entry.verdict is CashVerdict.DERIVED
        assert entry.balance == Decimal("950.00")
        assert entry.settled is None
        assert entry.unsettled is None
        assert entry.reason is not None and "settled/unsettled split" in entry.reason


class TestSettlementDates:
    """`AccountCash.unsettled_next_date`/`unsettled_full_date` -- when the unsettled figure clears.

    Filed by a UAT persona as `portfolio-unsettled-cash-lacks-settlement-date`: the date was already
    on the row (`Transaction.settle_date`) and already used to decide *whether* a row was unsettled,
    but never carried onto the figure it produced. These tests pin the three states a reader needs to
    be able to tell apart: one date, a range of dates, and no pending inflow at all -- plus the
    withheld case, where a date must not survive attached to a figure that was not published.
    """

    def test_one_pending_inflow_surfaces_its_own_date(self) -> None:
        txns = [
            funded("1000.00"),
            make_txn(
                txn_id="sell",
                action=TxnAction.SELL,
                amount="500.00",
                trade_date=dt.date(2026, 3, 31),
                settle_date=dt.date(2026, 4, 1),
            ),
        ]
        entry = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF).accounts[0]

        assert entry.unsettled == Decimal("500.00")
        # A single pending row: the "first clears" and "all clears" dates are the same date, not
        # two coincidentally-equal values computed two different ways.
        assert entry.unsettled_next_date == dt.date(2026, 4, 1)
        assert entry.unsettled_full_date == dt.date(2026, 4, 1)

    def test_several_inflows_with_different_dates_report_the_range(self) -> None:
        """The behavior this module settled on: neither date alone, both ends of the range. A sale
        settling first and a dividend settling later both feed the same `unsettled` total, and a
        reader is told when the *first* dollar clears and separately when *every* dollar has --
        never just one of the two dressed up as "the" settlement date."""
        txns = [
            funded("1000.00"),
            make_txn(
                txn_id="sell",
                action=TxnAction.SELL,
                amount="500.00",
                trade_date=dt.date(2026, 3, 30),
                settle_date=dt.date(2026, 4, 1),
            ),
            make_txn(
                txn_id="div",
                action=TxnAction.DIVIDEND,
                symbol=None,
                quantity=None,
                price=None,
                amount="12.34",
                trade_date=dt.date(2026, 3, 31),
                settle_date=dt.date(2026, 4, 3),
            ),
        ]
        entry = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF).accounts[0]

        assert entry.unsettled == Decimal("512.34")
        assert entry.unsettled_next_date == dt.date(2026, 4, 1)
        assert entry.unsettled_full_date == dt.date(2026, 4, 3)
        assert entry.unsettled_next_date < entry.unsettled_full_date

    def test_no_pending_inflows_reports_no_date_not_an_unknown_one(self) -> None:
        """`None` here must read as "nothing pending", the same state a fully-settled account is
        always in -- not as "clears on some date this module could not determine"."""
        txns = [funded("1000.00")]
        entry = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF).accounts[0]

        assert entry.unsettled == Decimal(0)
        assert entry.unsettled_next_date is None
        assert entry.unsettled_full_date is None

    def test_withheld_split_carries_no_date(self) -> None:
        """The mirror failure this field must avoid: a date attached to a figure that was withheld
        would describe an amount the reader cannot even see. Reuses the fixture that drives
        `unsettled` to `None` via the structural backstop (a pending fee with nothing pending on the
        other side of it to net against)."""
        txns = [
            funded("1000.00"),
            make_txn(
                txn_id="gold",
                action=TxnAction.SUBSCRIPTION_FEE,
                symbol=None,
                quantity=None,
                price=None,
                amount="-50.00",
                trade_date=dt.date(2026, 3, 31),
                settle_date=dt.date(2026, 4, 2),
            ),
        ]
        entry = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF).accounts[0]

        assert entry.unsettled is None
        assert entry.unsettled_next_date is None
        assert entry.unsettled_full_date is None

    def test_a_declared_balance_carries_no_settlement_date(self) -> None:
        """A declared figure is a single number the user read off their broker, not row-level detail
        -- there is no per-row `settle_date` behind it to report, even when the derivation underneath
        (now overridden and stashed on `derived_balance`) had pending rows of its own. Cleared rather
        than left holding the superseded derivation's dates, which would silently describe the wrong
        figure."""
        txns = [
            funded("1000.00"),
            make_txn(
                txn_id="sell",
                action=TxnAction.SELL,
                amount="500.00",
                trade_date=dt.date(2026, 3, 31),
                settle_date=dt.date(2026, 4, 1),
            ),
        ]
        declared = DeclaredCash(
            account_id="rh-taxable",
            balance=Decimal("1500.00"),
            as_of=dt.date(2026, 3, 15),
            settled=Decimal("1500.00"),
            unsettled=Decimal("0.00"),
        )
        entry = build_cash(
            txns,
            accounts={"rh-taxable": account()},
            as_of=AS_OF,
            declared={"rh-taxable": declared},
        ).accounts[0]

        assert entry.verdict is CashVerdict.DECLARED
        assert entry.unsettled_next_date is None
        assert entry.unsettled_full_date is None


class TestAggregation:
    def test_the_total_is_partial_and_names_the_gap(self) -> None:
        """The convention this application already uses for unpriced symbols, applied to cash: a
        partial total beats no total, provided the gap is named."""
        txns = [
            funded("1000.00", account_id="rh-taxable"),
            make_txn(
                txn_id="wb-buy",
                action=TxnAction.BUY,
                amount="-5000.00",
                trade_date=dt.date(2026, 2, 1),
                account_id="wb-cash",
                broker=Broker.WEBULL,
            ),
        ]
        ledger = build_cash(
            txns,
            accounts={
                "rh-taxable": account(),
                "wb-cash": account("wb-cash", broker=Broker.WEBULL),
            },
            as_of=AS_OF,
        )

        assert ledger.total == Decimal("1000.00")
        assert ledger.accounts_without_cash == ("wb-cash",)
        assert not ledger.is_complete
        assert ledger.derivable_count == 1

    def test_zero_is_distinguishable_from_nothing(self) -> None:
        """An account that genuinely holds no cash reports ``0``; a set with nothing derivable
        reports ``None``. Rendering both as ``0.00`` would conflate two different facts."""
        spent = [
            funded("1000.00"),
            make_txn(
                txn_id="buy",
                action=TxnAction.BUY,
                amount="-1000.00",
                trade_date=dt.date(2026, 2, 1),
            ),
        ]
        assert build_cash(spent, accounts={"rh-taxable": account()}, as_of=AS_OF).total == Decimal(0)

        nothing = build_cash(
            [
                make_txn(
                    txn_id="b",
                    action=TxnAction.BUY,
                    amount="-1.00",
                    account_id="wb-cash",
                    broker=Broker.WEBULL,
                )
            ],
            accounts={"wb-cash": account("wb-cash", broker=Broker.WEBULL)},
            as_of=AS_OF,
        )
        assert nothing.total is None

    def test_ledger_settlement_range_spans_every_contributing_account(self) -> None:
        """`CashLedger.unsettled_next_date`/`unsettled_full_date` take the earliest and latest across
        every account that fed `unsettled_total` -- not just the first account iterated, and not
        just one account's own range when two accounts both have pending inflows."""
        txns = [
            funded("1000.00", account_id="rh-taxable"),
            make_txn(
                txn_id="rh-sell",
                action=TxnAction.SELL,
                amount="500.00",
                trade_date=dt.date(2026, 3, 30),
                settle_date=dt.date(2026, 4, 1),
                account_id="rh-taxable",
            ),
            funded("2000.00", account_id="rh-roth"),
            make_txn(
                txn_id="roth-sell",
                action=TxnAction.SELL,
                amount="300.00",
                trade_date=dt.date(2026, 3, 31),
                settle_date=dt.date(2026, 4, 5),
                account_id="rh-roth",
            ),
        ]
        ledger = build_cash(
            txns,
            accounts={"rh-taxable": account(), "rh-roth": account("rh-roth")},
            as_of=AS_OF,
        )

        assert ledger.unsettled_total == Decimal("800.00")
        assert ledger.unsettled_next_date == dt.date(2026, 4, 1)
        assert ledger.unsettled_full_date == dt.date(2026, 4, 5)

    def test_ledger_settlement_range_is_none_when_nothing_is_pending(self) -> None:
        txns = [funded("1000.00")]
        ledger = build_cash(txns, accounts={"rh-taxable": account()}, as_of=AS_OF)

        assert ledger.unsettled_total == Decimal(0)
        assert ledger.unsettled_next_date is None
        assert ledger.unsettled_full_date is None

    def test_ledger_settlement_range_is_none_when_the_total_is_withheld(self) -> None:
        """One account's split withheld makes `unsettled_total` `None` (the strict all-or-none rule
        `_sum_all_or_none` applies) -- and the settlement range must go withheld with it rather than
        describe a total that was not shown."""
        txns = [
            funded("1000.00", account_id="rh-taxable"),
            make_txn(
                txn_id="gold",
                action=TxnAction.SUBSCRIPTION_FEE,
                symbol=None,
                quantity=None,
                price=None,
                amount="-50.00",
                trade_date=dt.date(2026, 3, 31),
                settle_date=dt.date(2026, 4, 2),
                account_id="rh-taxable",
            ),
            funded("2000.00", account_id="rh-roth"),
            make_txn(
                txn_id="roth-sell",
                action=TxnAction.SELL,
                amount="300.00",
                trade_date=dt.date(2026, 3, 31),
                settle_date=dt.date(2026, 4, 5),
                account_id="rh-roth",
            ),
        ]
        ledger = build_cash(
            txns,
            accounts={"rh-taxable": account(), "rh-roth": account("rh-roth")},
            as_of=AS_OF,
        )

        assert ledger.unsettled_total is None
        assert ledger.unsettled_next_date is None
        assert ledger.unsettled_full_date is None


@requires_real_data
class TestAgainstRealExports:
    """Pins the two failure modes against the user's actual ledger.

    Skipped on a fresh clone, where ``data/`` is absent. These assertions are about the *shape* of
    the real exports -- Webull ships order history, the Robinhood window starts mid-life -- not about
    any particular dollar figure, so they do not need updating when the user re-exports.
    """

    def test_no_real_account_silently_publishes_a_balance(self, settings) -> None:  # type: ignore[no-untyped-def]
        from app.config import REPO_ROOT
        from app.db import sqlite as ledger_store

        real_ledger = REPO_ROOT / "data" / "store" / "ledger.sqlite"
        if not real_ledger.exists():
            pytest.skip("no built ledger; run an import first")

        with ledger_store.connect(real_ledger, read_only=True) as conn:
            accounts = {a.account_id: a for a in ledger_store.fetch_accounts(conn)}
            txns = [
                ledger_store.transaction_from_row(row)
                for row in ledger_store.fetch_transactions(conn)
            ]
        if not txns:
            pytest.skip("ledger is empty")

        result = build_cash(
            txns, accounts=accounts, as_of=max(t.trade_date for t in txns)
        )

        webull = [a for a in result.accounts if a.broker == "webull"]
        assert webull, "expected the real ledger to contain Webull accounts"
        assert all(a.verdict is CashVerdict.NO_FUNDING_ROWS for a in webull), (
            "Webull exports are order history with no funding rows; if this now passes, the adapter "
            "gained cash-row support and this expectation is what should change"
        )
        assert all(a.balance is None for a in webull)

        # Every withheld account must say why. A withheld figure with no reason is a dead end for
        # the user, which is the failure this whole feature exists to avoid.
        for entry in result.accounts:
            if entry.verdict is not CashVerdict.DERIVED:
                assert entry.reason

"""Cash balances derived from the transaction ledger, with an explicit verdict on trustworthiness.

Cash is arithmetically trivial -- sum :attr:`~app.core.models.Transaction.amount`, which the model
defines as the signed net cash effect -- and that triviality is the trap. The sum is always
*computable*; it is only *correct* when the export it came from captured every cash movement since
the account opened. Two of the three broker exports this application ingests do not, and summing
them anyway produces a confident, specific, wrong number.

Measured against a real multi-account ledger, a naive per-account ``SUM(amount)`` goes wrong in
two distinct shapes:

* **Order-history exports** (Webull). The export is trade history only: it has no deposit,
  dividend, interest or fee rows at all, so there is nothing to net against. The naive sum is just
  sells minus buys, and across several such accounts it invents a large amount of cash that does not
  exist.
* **Exports that start after the account did** (Robinhood Roth). A retirement account can come out
  with a negative balance, which is impossible; the export window begins after the account did, so
  the opening balance is missing.

Displaying either figure would be worse than displaying nothing: a user cannot tell a derived number
from a fabricated one by looking at it, and this number is the one they would size a trade against.

So this module returns a **verdict, not just a total**. Two failure modes are detectable without
knowing anything broker-specific, and both are decided from the data rather than from an adapter
name -- an adapter that gains cash-row support later starts passing automatically:

* :attr:`CashVerdict.NO_FUNDING_ROWS` -- the account has trades but not one external cash movement.
  Nothing could have funded those trades, so the export is order history and the balance is
  meaningless.
* :attr:`CashVerdict.NEGATIVE_IN_CASH_ACCOUNT` -- the balance goes below zero at some point in an
  account that cannot go below zero. Proof that some inflow predates the export.

  The check is against the **running** balance, not the closing one, and the difference is not
  academic. An account can close at a healthy positive balance and look fine, yet reach that figure
  only because the export's final day happens to contain a batch of large sales. Rewind past them
  and the account is negative. A closing-balance check passes it and publishes a number wrong by at
  least the size of that hole. The running minimum also yields the size of the hole, which is more
  actionable than the verdict alone: it is a lower bound on the opening balance the export is
  missing, and it tells the user how far back they need to re-export.

Anything else is reported as :attr:`CashVerdict.DERIVED`, which is a claim about arithmetic and
about the two checks above -- **not** a guarantee that the export reaches account inception, which
no amount of inspecting the export can establish. That residual uncertainty is why every balance
ships with its coverage window attached: the caller can see which dates the figure is a sum over and
judge for itself, in the same spirit as the provenance carried by every other figure in this
application.

Settlement follows the same reasoning. ``settle_date`` is present on Robinhood and SoFi rows, so
unsettled proceeds are derivable where cash itself is; a transaction with no settle date is treated
as settled, because a broker that does not distinguish is a broker whose cash is all spendable as
far as anything here can tell.

Deciding *which* rows are unsettled proceeds turned out to need more than the row's own sign. A
purchase, a withdrawal, and an outbound transfer are all committed the moment they happen regardless
of settlement and must never be counted as proceeds; a regulatory fee on a not-yet-settled sale is
the opposite case -- it reduces proceeds that have not arrived, and excluding it on sign alone left
it stranded in the balance with nothing to net it against. That fee case is not specific to this
codebase's UAT harness: real Robinhood and SoFi exports write it as its own row too (see
``app.ingest.adapters.robinhood`` and ``.sofi``), so both failures are real-data risks inside the
T+1/T+2 settlement window, not synthetic ones. :func:`_is_committed_outflow` is where the resulting
row-by-row judgment lives, and the arithmetic it feeds is never allowed to publish a negative
"unsettled" -- see :class:`AccountCash.unsettled`'s own docstring for what happens when a row this
module cannot classify with confidence would otherwise force one.

The unsettled figure used to stop there -- a dollar amount with no date, so a reader could not tell
*when* it clears without going and reconstructing the answer from the Activity page by hand (a UAT
persona did exactly that, on two separate sessions, and filed the gap: see
``uat/feedback/BACKLOG.md`` §R13). Fixing it needs an answer to a question this module had not asked
before: pending inflows can carry *different* settle dates -- a sale that settles Tuesday and a
dividend that settles Thursday are both inside the same ``unsettled`` figure -- so "the settlement
date" is not a well-formed question. :attr:`AccountCash.unsettled_next_date` and
:attr:`AccountCash.unsettled_full_date` answer the two well-formed ones instead: the soonest any of
it clears, and the date by which *all* of it has. Publishing only one of the two, unlabelled, would
have recreated the exact failure this module exists to refuse elsewhere -- a single figure that
silently means one thing while a reader assumes another -- so both travel together, collapsing to one
date on screen only when they happen to agree. Neither is invented: both come straight off the
``settle_date`` already sitting on the rows behind ``unsettled``, the same field :mod:`app.core.cash`
has read since the settlement split was added. No new T+N rule, no new calendar.

Pure: no I/O, no pricing, no network -- the same contract as :mod:`app.core.holdings`, and for the
same reason. Composition with the market store belongs to the API layer.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from app.core.models import Account, AccountType, TaxTreatment, Transaction, TxnAction

__all__ = [
    "FUNDING_ACTIONS",
    "AccountCash",
    "CashLedger",
    "CashVerdict",
    "DeclaredCash",
    "build_cash",
]

#: Actions that move cash across the account boundary from outside -- the rows whose absence proves
#: an export is order history rather than an activity ledger.
#:
#: Trades are excluded deliberately: a buy and a sell move cash, but only cash the account already
#: had, so an export containing nothing but trades cannot establish a balance no matter how many
#: rows it has. Income (dividends, interest, stock-lending) counts because it is an external inflow
#: a broker only reports on a full activity export. ``TRANSFER_IN``/``TRANSFER_OUT`` count because an
#: ACAT's cash leg is a genuine external movement -- the position legs of the same transfer carry no
#: amount and are skipped by the summation regardless.
FUNDING_ACTIONS: frozenset[TxnAction] = frozenset(
    {
        TxnAction.CASH_IN,
        TxnAction.CASH_OUT,
        TxnAction.IRA_MATCH,
        TxnAction.DIVIDEND,
        TxnAction.INTEREST,
        TxnAction.STOCK_LENDING_INCOME,
        TxnAction.TRANSFER_IN,
        TxnAction.TRANSFER_OUT,
    }
)

#: Actions whose cash effect is committed the moment they occur, unconditionally -- the action code
#: alone says the money is already out, no matter what a future settle_date on the row claims and
#: no matter the sign (these are only ever negative in practice, but the exclusion does not depend
#: on that). Paired with :data:`_BIDIRECTIONAL_ACTIONS` below to decide :func:`_is_committed_outflow`
#: for every one of :class:`~app.core.models.TxnAction`'s 17 members -- deliberately, not by falling
#: through a sign check, because a sign check is exactly what let a pending ``cash_out`` or
#: ``transfer_out`` slip into ``unsettled`` as if it were proceeds still arriving.
#:
#: * :attr:`~app.core.models.TxnAction.BUY` -- a purchase; money spent to acquire a position at
#:   fill, and cannot be un-spent because the trade has not settled. See the long comment in
#:   :func:`_account_cash` for the measured cost of getting this one wrong.
#: * :attr:`~app.core.models.TxnAction.CASH_OUT` -- a withdrawal request; the user told the broker
#:   to send money out, and that instruction is not reversible by waiting for T+1/T+2 to pass.
#: * :attr:`~app.core.models.TxnAction.TRANSFER_OUT` -- the cash leg of an ACAT leaving for another
#:   institution; same reasoning as a withdrawal, aimed at a different destination.
_COMMITTED_OUTFLOW_ACTIONS: frozenset[TxnAction] = frozenset(
    {
        TxnAction.BUY,
        TxnAction.CASH_OUT,
        TxnAction.TRANSFER_OUT,
    }
)

#: Actions that carry cash in *either* direction under one code, so the action alone cannot say
#: whether a given row is proceeds still in transit or money already spent -- only the row's own
#: sign can. A negative row here is treated exactly like a member of
#: :data:`_COMMITTED_OUTFLOW_ACTIONS`: committed and gone. A non-negative row is treated as ordinary
#: incoming cash, netted into ``unsettled`` like a sale.
#:
#: * :attr:`~app.core.models.TxnAction.INTEREST` -- interest a broker pays the user is income
#:   (positive); interest a margin account owes the broker is an expense already assessed against
#:   the balance (negative). One code, two directions, and the real ledger this module derives
#:   against has both.
#: * :attr:`~app.core.models.TxnAction.INTERNAL_TRANSFER` -- Robinhood's ``ITRF``, movement between
#:   the user's own accounts at the same broker (see the ``affects_position`` docstring on
#:   :class:`~app.core.models.TxnAction` for the position-side half of this). Cash can move either
#:   way depending on which of the user's accounts is the source.
#: * :attr:`~app.core.models.TxnAction.ADJUSTMENT` and :attr:`~app.core.models.TxnAction.MISC` --
#:   catch-all correcting entries with no dedicated code, so nothing here proves their direction.
#:   Grouped with the sign-decided actions rather than assumed to always be incoming, on the
#:   principle that an unproven inflow is the riskier assumption for a figure sized against
#:   spendable cash.
_BIDIRECTIONAL_ACTIONS: frozenset[TxnAction] = frozenset(
    {
        TxnAction.INTEREST,
        TxnAction.INTERNAL_TRANSFER,
        TxnAction.ADJUSTMENT,
        TxnAction.MISC,
    }
)

#: Every action not named above -- `SELL`, `DIVIDEND`, `STOCK_LENDING_INCOME`, `FEE`,
#: `SUBSCRIPTION_FEE`, `TRANSFER_IN`, `CASH_IN`, `IRA_MATCH`, `SPLIT`, `SPINOFF` -- is never a
#: committed outflow and is summed net into `unsettled` whenever it is pending, regardless of its
#: own sign:
#:
#: * `SELL`, `DIVIDEND`, `STOCK_LENDING_INCOME`, `TRANSFER_IN`, `CASH_IN`, `IRA_MATCH` are all
#:   incoming by construction -- proceeds, income, an ACAT cash leg arriving, a deposit, a broker
#:   match. None of these is ever money the account has already spent.
#: * `FEE` and `SUBSCRIPTION_FEE` are costs, always negative in practice, but they are costs
#:   *against proceeds not yet received* rather than money independently spent -- a regulatory fee
#:   rides on the sale it was charged against, sharing its settle_date, so excluding it the way a
#:   purchase is excluded would leave it stranded in `balance` with nothing to net it out of
#:   `unsettled`. That stranding is the defect this module now fixes: see the long comment in
#:   `_account_cash`.
#: * `SPLIT`, `SPINOFF` essentially never carry a cash amount at all (the position leg does; see
#:   `affects_position`), and on the rare row that does -- cash-in-lieu of a fractional share -- it
#:   is a payment arriving, not one leaving.


def _is_committed_outflow(t: Transaction) -> bool:
    """Whether a transaction's cash effect is already final and must never be treated as `unsettled`
    proceeds, no matter how far in the future its `settle_date` claims to be.

    Two different judgments feed this, and neither is "is `amount` negative": an action in
    `_COMMITTED_OUTFLOW_ACTIONS` is excluded regardless of sign, because the *kind* of row already
    settles the question (a purchase or a withdrawal is committed even in the hypothetical world
    where its amount were positive). An action in `_BIDIRECTIONAL_ACTIONS` needs the sign because the
    kind alone is ambiguous -- the same code covers money leaving and money arriving. Everything else
    is never a committed outflow, whatever its sign, and is netted into `unsettled` when pending.
    """
    if t.action in _COMMITTED_OUTFLOW_ACTIONS:
        return True
    if t.action in _BIDIRECTIONAL_ACTIONS:
        return t.amount is not None and t.amount < 0
    return False


class CashVerdict(StrEnum):
    """Whether an account's cash balance can be trusted, and if not, why not."""

    DERIVED = "derived"
    """Summed from the ledger and neither of the two failure checks fired."""

    DECLARED = "declared"
    """Stated by the user from their broker, not computed from the export.

    A separate verdict rather than a flag on :attr:`DERIVED`, because the two have different failure
    modes and a reader has to be able to tell them apart. A derived balance is wrong only if the
    ledger is wrong; a declared one goes stale the moment a trade settles after the date it was
    taken, and nothing in this system can notice that happening. So it always travels with its
    ``as_of`` date, and :attr:`AccountCash.reason` says where it came from even though the figure is
    present -- the one case in this module where a reason accompanies a number rather than replacing
    one.

    It exists because several real accounts export order history with no cash rows at
    all: no amount of work on the derivation recovers a balance the file does not contain. The choice
    is a declared figure or none, and none makes total equity permanently unavailable."""

    NO_FUNDING_ROWS = "no_funding_rows"
    """The export carries trades but no external cash movement. Balance withheld."""

    NEGATIVE_IN_CASH_ACCOUNT = "negative_in_cash_account"
    """The sum is negative in an account that cannot hold a debit. Balance withheld."""

    NO_TRANSACTIONS = "no_transactions"
    """Nothing in the ledger for this account. Not an error -- there is simply nothing to sum."""

    @property
    def is_trustworthy(self) -> bool:
        """Whether the balance may be shown and totalled. True for a declared figure: the user is a
        better authority on their own cash than an export that omits it. What it does not mean is
        "computed" -- callers that care about provenance test the verdict itself."""
        return self in (CashVerdict.DERIVED, CashVerdict.DECLARED)


@dataclass(frozen=True, slots=True)
class DeclaredCash:
    """A cash balance the user read off their broker, with the date they read it.

    Money is :class:`~decimal.Decimal` here as everywhere else, and the manifest carries it as a
    *string* for that reason -- TOML floats are IEEE 754 and ``1234.56`` does not survive one.

    ``settled``/``unsettled`` are optional because not every broker shows the split (Robinhood
    reports a single buying-power figure). When both are given they must satisfy the same invariant
    a derived balance does -- ``settled + unsettled == balance`` with ``unsettled >= 0`` -- and
    :meth:`validate` is what refuses a declaration that does not, rather than letting a typo become a
    confident total.
    """

    account_id: str
    balance: Decimal
    as_of: dt.date
    settled: Decimal | None = None
    unsettled: Decimal | None = None
    note: str = ""
    """Where the figure came from, in the user's own words. Shown next to it."""

    def validate(self) -> None:
        """Raise :class:`ValueError` if the parts contradict the whole."""
        if (self.settled is None) != (self.unsettled is None):
            raise ValueError(
                f"declared cash for {self.account_id} gives only one of settled/unsettled; "
                "supply both or neither -- a half-stated split cannot be checked against the balance"
            )
        if self.settled is None or self.unsettled is None:
            return
        if self.unsettled < 0:
            raise ValueError(
                f"declared unsettled cash for {self.account_id} is {self.unsettled}, but unsettled "
                "cash is proceeds not yet available and can never be negative"
            )
        if self.settled + self.unsettled != self.balance:
            raise ValueError(
                f"declared cash for {self.account_id} does not add up: settled {self.settled} + "
                f"unsettled {self.unsettled} = {self.settled + self.unsettled}, but balance is "
                f"{self.balance}"
            )


@dataclass(frozen=True)
class AccountCash:
    """One account's cash position, with the evidence behind it.

    ``balance`` is ``None`` whenever :attr:`verdict` is not trustworthy. That is deliberate: an
    untrustworthy figure is not returned alongside a flag saying to ignore it, because every caller
    that renders it would have to remember to check, and one that forgets shows a fabricated number.
    Withholding it makes the check unavoidable.
    """

    account_id: str
    account_label: str
    broker: str
    account_type: AccountType
    tax_treatment: TaxTreatment
    """Carried here because this is the per-account row the API sends. Unrealized gain inside a
    Roth is never taxed, and a per-account view that cannot say so states something false."""

    verdict: CashVerdict
    balance: Decimal | None
    settled: Decimal | None
    unsettled: Decimal | None
    """Proceeds whose ``settle_date`` is after the as-of date. Not spendable in a cash account.

    **Proceeds, so never negative.** A purchase, withdrawal, or outbound transfer that has not
    settled is already deducted from :attr:`balance` and is not money coming back; counting one of
    those here once made :attr:`settled` exceed the balance itself. The invariant this field exists
    under is ``settled + unsettled == balance`` with ``unsettled >= 0``, which means ``settled <=
    balance`` always -- see :func:`_is_committed_outflow` for how rows are kept out of this field.

    Can be ``None`` even when :attr:`verdict` is :attr:`~CashVerdict.DERIVED` and :attr:`balance` is
    not: the classification behind this field is a deliberate judgment about 17 action codes, not an
    exhaustive proof, and the arithmetic can still land below zero on a row it could not classify
    with certainty (an ``ADJUSTMENT`` or ``MISC`` row, or a pending fee with nothing pending to net
    it against). Rather than publish a negative "proceeds" figure, both this and :attr:`settled` are
    withheld together and :attr:`reason` explains why -- :attr:`balance` is unaffected, because it
    never depended on this split in the first place."""

    funding_row_count: int
    cash_row_count: int
    """Rows carrying a non-null amount -- the ones actually summed."""
    first_transaction: dt.date | None
    last_transaction: dt.date | None
    """The coverage window the balance is a sum over. The caller judges completeness from this;
    nothing in the export can prove it reaches account inception."""

    unsettled_next_date: dt.date | None = None
    """The soonest ``settle_date`` among the rows behind :attr:`unsettled` -- when the *first* of it
    clears, not necessarily all of it.

    ``None`` in exactly two cases, and they must not be confused: **nothing pending** (no row
    contributed to :attr:`unsettled`, so there is no date because there is nothing to date -- the
    common case, and the one that should read as "fully settled", not as "unknown") and **withheld**
    (:attr:`unsettled` itself is ``None`` because the split could not be computed -- see that field's
    docstring -- so attaching a date to a figure that was not published would describe an amount the
    reader cannot even see). Callers that need to tell these apart read :attr:`unsettled` alongside
    this field: ``0`` means the first case, ``None`` means the second.

    Deliberately paired with :attr:`unsettled_full_date` rather than standing alone. Pending inflows
    routinely carry different settle dates -- a sale settling Tuesday and a dividend settling Thursday
    both land inside one ``unsettled`` total -- so a single "the settlement date" field would have to
    silently pick an end of the range, and whichever end it picked, a reader assuming the other one
    would be misled by a number that looked precise. The two dates together are the honest answer;
    they only collapse to a single displayed date, at the UI layer, on the (common) day they agree."""
    unsettled_full_date: dt.date | None = None
    """The furthest-out ``settle_date`` among the rows behind :attr:`unsettled` -- the date by which
    *every* dollar of it has cleared. Equal to :attr:`unsettled_next_date` whenever every pending row
    happens to share one settle date, which is the ordinary case for a single sale. ``None`` under
    the identical two conditions as :attr:`unsettled_next_date`; see that field's docstring."""

    missing_opening_balance: Decimal | None = None
    """How far the running balance went below zero, as a positive figure. Set only on
    :attr:`CashVerdict.NEGATIVE_IN_CASH_ACCOUNT`. A lower bound on the opening cash the export omits
    -- and therefore on how much further back the user needs to re-export."""
    first_negative_on: dt.date | None = None
    """The date the running balance first went negative. Where to look in the export."""

    declared_as_of: dt.date | None = None
    """When the user read this balance off their broker. Set only on
    :attr:`CashVerdict.DECLARED`, and never omitted there: a declared balance without its date is
    indistinguishable from a current one."""
    declared_note: str = ""
    derived_balance: Decimal | None = None
    """What the ledger *would* have said, kept alongside a declared figure rather than discarded.

    Only populated when the derivation actually produced a trustworthy number and a declaration
    overrode it -- which is the one case worth surfacing, because the two disagreeing means either
    the export is incomplete or the declaration is stale, and both are worth a look. Where the
    derivation was withheld (the usual case here) this stays ``None``: there is nothing to compare
    against, and a withheld figure is not evidence of agreement."""

    @property
    def is_derivable(self) -> bool:
        return self.verdict.is_trustworthy

    @property
    def reason(self) -> str | None:
        """Why the balance -- or, on a derived account, just the settled/unsettled split -- was
        withheld, phrased for display. ``None`` when nothing was withheld."""
        if (
            self.verdict is CashVerdict.DERIVED
            and self.balance is not None
            and self.settled is None
        ):
            # The one case where `balance` is present but `reason` is not `None` on a non-DECLARED
            # verdict: the split, not the balance, failed the `unsettled >= 0` check. See the long
            # comment above `_is_committed_outflow`'s call site in `_account_cash`.
            return (
                "the settled/unsettled split could not be computed without unsettled going "
                "negative -- likely a pending fee, withdrawal, or adjustment with nothing pending "
                "on the other side of it to net against -- so the split is withheld while the "
                "total balance, which does not depend on it, stays derived"
            )
        if self.verdict is CashVerdict.NO_FUNDING_ROWS:
            return (
                f"{self.broker} exported order history only -- no deposits, withdrawals or income "
                "rows -- so a cash balance cannot be reconstructed from it"
            )
        if self.verdict is CashVerdict.NEGATIVE_IN_CASH_ACCOUNT:
            shortfall = (
                f"${self.missing_opening_balance:,.2f}"
                if self.missing_opening_balance is not None
                else "an unknown amount"
            )
            when = f" by {self.first_negative_on.isoformat()}" if self.first_negative_on else ""
            return (
                f"the running balance goes {shortfall} below zero{when} in an account that cannot "
                "hold a debit, so the export begins after the account was funded and is missing at "
                f"least {shortfall} of opening cash"
            )
        if self.verdict is CashVerdict.NO_TRANSACTIONS:
            return "no transactions in the ledger for this account"
        if self.verdict is CashVerdict.DECLARED:
            # The one reason that accompanies a figure instead of replacing one. A declared balance
            # is a snapshot, and the reader has to be told it does not move with the ledger.
            when = self.declared_as_of.isoformat() if self.declared_as_of else "an unstated date"
            drift = (
                f"; the export itself derives ${self.derived_balance:,.2f}, which disagrees"
                if self.derived_balance is not None and self.derived_balance != self.balance
                else ""
            )
            note = f" ({self.declared_note})" if self.declared_note else ""
            return (
                f"declared from the broker as of {when}, not derived from the export{note}{drift}. "
                "It does not update as transactions are imported"
            )
        return None


@dataclass(frozen=True)
class CashLedger:
    """Cash across every account, aggregated only over the accounts that could supply it."""

    as_of: dt.date
    accounts: tuple[AccountCash, ...]

    total: Decimal | None
    """Sum over derivable accounts only. ``None`` when not one account was derivable -- otherwise a
    partial sum, with the gap named in :attr:`accounts_without_cash`. This mirrors how
    ``app.api.portfolio`` already treats ``total_market_value`` against ``unpriced_symbols``: a
    partial total is more useful than no total, provided the gap is named at the point the total is
    displayed."""

    settled_total: Decimal | None
    unsettled_total: Decimal | None

    unsettled_next_date: dt.date | None
    """The aggregate counterpart of :attr:`AccountCash.unsettled_next_date`: the soonest any account's
    pending inflow clears, across every account that fed :attr:`unsettled_total`.

    Gated on :attr:`unsettled_total` rather than computed independently, for the same reason
    :func:`_sum_all_or_none` gates the settled/unsettled totals on every contributing account
    supplying a split: a date range describing an amount that was not published (because one
    contributing account's own split was withheld) is worse than publishing neither. ``None``
    whenever :attr:`unsettled_total` is ``None``, and also whenever it is a real ``0`` -- nothing
    pending across the whole ledger has no date, the same "nothing to date" rule each account applies
    to itself."""
    unsettled_full_date: dt.date | None
    """The aggregate counterpart of :attr:`AccountCash.unsettled_full_date`: the latest date by which
    every account's pending inflows have cleared. See :attr:`unsettled_next_date` for the ``None``
    rule, which is identical."""

    accounts_without_cash: tuple[str, ...]
    """Account ids excluded from the totals, in id order."""

    @property
    def is_complete(self) -> bool:
        """True when every account with transactions contributed to the total."""
        return not self.accounts_without_cash

    @property
    def derivable_count(self) -> int:
        return sum(1 for account in self.accounts if account.is_derivable)


def build_cash(
    transactions: Sequence[Transaction],
    *,
    accounts: Mapping[str, Account],
    as_of: dt.date,
    declared: Mapping[str, DeclaredCash] | None = None,
) -> CashLedger:
    """Derive per-account cash from the ledger, letting the user override where it cannot be derived.

    Args:
        transactions: Every transaction, in any order -- summation is order-independent.
        accounts: Account metadata by id. An account absent here is skipped rather than guessed at.
        as_of: The date settlement is judged against. Callers pass the portfolio's own ``as_of``
            (the ledger's last trade date), so "unsettled" means unsettled as of the same moment
            every other figure on the report is stated as of.
        declared: Balances the user stated from their broker, by ``account_id``. **The derivation
            still runs for every account**, declared or not, and its result is kept on
            :attr:`AccountCash.derived_balance` where it was trustworthy. A declaration overrides
            what is *displayed*; it does not suppress the check, so the two disagreeing stays
            visible instead of being resolved by whichever ran last.
    """
    by_account: dict[str, list[Transaction]] = {account_id: [] for account_id in accounts}
    for transaction in transactions:
        if transaction.account_id in by_account:
            by_account[transaction.account_id].append(transaction)

    declarations = declared or {}
    results = [
        _apply_declaration(
            _account_cash(accounts[account_id], rows, as_of=as_of),
            declarations.get(account_id),
        )
        for account_id, rows in sorted(by_account.items())
    ]

    derivable = [account for account in results if account.is_derivable]
    excluded = tuple(
        account.account_id
        for account in results
        if not account.is_derivable and account.verdict is not CashVerdict.NO_TRANSACTIONS
    )

    unsettled_total = _sum_all_or_none(account.unsettled for account in derivable)
    unsettled_next_date, unsettled_full_date = _settlement_range(derivable, unsettled_total)

    return CashLedger(
        as_of=as_of,
        accounts=tuple(results),
        total=_sum_or_none(account.balance for account in derivable),
        settled_total=_sum_all_or_none(account.settled for account in derivable),
        unsettled_total=unsettled_total,
        unsettled_next_date=unsettled_next_date,
        unsettled_full_date=unsettled_full_date,
        accounts_without_cash=excluded,
    )


def _settlement_range(
    derivable: Sequence[AccountCash], unsettled_total: Decimal | None
) -> tuple[dt.date | None, dt.date | None]:
    """The ledger-wide settlement range behind :attr:`CashLedger.unsettled_total`: the earliest and
    latest dates across every contributing account's own :attr:`~AccountCash.unsettled_next_date` /
    :attr:`~AccountCash.unsettled_full_date`.

    Takes ``unsettled_total`` as an argument rather than recomputing its own gate, so the two are
    built from the same pass over ``derivable`` the caller already made and cannot disagree about
    which accounts counted. ``None, None`` whenever ``unsettled_total`` is ``None`` -- a date range
    for a total that was not published would describe money the reader cannot see the size of -- and
    also whenever it is a real ``0``, the ordinary "nothing pending anywhere" case.
    """
    if unsettled_total is None:
        return None, None
    next_dates = [a.unsettled_next_date for a in derivable if a.unsettled_next_date is not None]
    full_dates = [a.unsettled_full_date for a in derivable if a.unsettled_full_date is not None]
    return (
        min(next_dates) if next_dates else None,
        max(full_dates) if full_dates else None,
    )


def _apply_declaration(derived: AccountCash, declaration: DeclaredCash | None) -> AccountCash:
    """Replace a derived balance with the user's declared one, keeping what the derivation said.

    Returns ``derived`` unchanged when there is no declaration, so the ordinary path is untouched.
    """
    if declaration is None:
        return derived
    declaration.validate()
    return replace(
        derived,
        verdict=CashVerdict.DECLARED,
        balance=declaration.balance,
        settled=declaration.settled,
        unsettled=declaration.unsettled,
        declared_as_of=declaration.as_of,
        declared_note=declaration.note,
        # Only a *trustworthy* derived figure is worth keeping to compare against -- see the field's
        # own docstring. A withheld one is not evidence of agreement.
        derived_balance=derived.balance if derived.is_derivable else None,
        # The withheld-balance diagnostics belong to a verdict this account no longer has.
        missing_opening_balance=None,
        first_negative_on=None,
        # A declared balance is a single figure the user read off their broker, not the row-level
        # detail the derivation had. There is no per-row settle_date behind a declared unsettled
        # figure to attach a date to, so both are cleared rather than left holding whatever the
        # (now-overridden) derivation happened to compute -- a stale date next to a replaced number
        # is exactly the kind of drift this module withholds elsewhere.
        unsettled_next_date=None,
        unsettled_full_date=None,
    )


def _account_cash(
    account: Account,
    transactions: Sequence[Transaction],
    *,
    as_of: dt.date,
) -> AccountCash:
    if not transactions:
        return _withheld(account, CashVerdict.NO_TRANSACTIONS, funding=0, cash_rows=0, window=None)

    dates = [transaction.trade_date for transaction in transactions]
    window = (min(dates), max(dates))

    funding = sum(1 for t in transactions if t.action in FUNDING_ACTIONS and t.amount is not None)
    if funding == 0:
        return _withheld(
            account,
            CashVerdict.NO_FUNDING_ROWS,
            funding=0,
            cash_rows=sum(1 for t in transactions if t.amount is not None),
            window=window,
        )

    # `amount` is the model's documented net cash effect, so fees are already inside it. Summing
    # `fees` on top would double-count them for any adapter that honours that contract -- and an
    # adapter that does not is a bug in the adapter, not something to compensate for here.
    cash_rows = [t for t in transactions if t.amount is not None]
    # The `is not None` is repeated rather than relying on `cash_rows`' filter: the comprehension
    # narrows nothing for a type checker, since `cash_rows` is still a `list[Transaction]` whose
    # `amount` remains `Decimal | None`. Repeating it here narrows properly and lets `balance` be a
    # plain `Decimal`, which is what every arithmetic below it assumes.
    balance = sum((t.amount for t in cash_rows if t.amount is not None), Decimal(0))

    if account.account_type is not AccountType.MARGIN:
        low, low_date = _running_minimum(cash_rows)
        if low < 0:
            return _withheld(
                account,
                CashVerdict.NEGATIVE_IN_CASH_ACCOUNT,
                funding=funding,
                cash_rows=len(cash_rows),
                window=window,
                missing_opening_balance=-low,
                first_negative_on=low_date,
            )

    # Not `t.amount > 0` -- a *purchase* awaiting settlement is not unsettled cash: the money is
    # committed the moment the order fills and cannot be spent again, so it belongs in the balance
    # as a deduction and nowhere else.
    #
    # Summing every future-settling row instead, purchases included, made `settled` = balance minus
    # a negative, i.e. **larger than the balance**. On a fresh account holding $2,981.86 after a
    # $10,000 deposit and six unsettled buys, the page read "$10,000.00 settled · -$7,018.14
    # unsettled". A UAT persona caught it and said it plainly: $10,000 shown as settled on a $2,982
    # account is the number that gets a position oversized. `settled` answers "what can I deploy",
    # and it must never exceed what is actually there.
    #
    # But a sign check throws out a different, legitimate row along with the purchases: the
    # regulatory fee on a sale that has not settled yet. It is a separate row with a negative
    # amount and the sale's own settle_date, so `t.amount > 0` excluded it from `unsettled` even
    # though it was already inside `balance` -- `unsettled` came out *gross* of the fee and
    # `settled` was short by exactly it. Two independent UAT persona runs measured this scaling
    # with the fee: a TLT sale with a $0.02 fee showed "settled" 1750.66 (true 1750.68) and
    # "unsettled" 837.00 gross (true 836.98 net); a QQQ sale with a $0.06 fee showed "settled"
    # 1247.61 (true 1247.67) and "unsettled" 2082.96 gross (true 2082.90 net). The total was right
    # either way -- only the partition was wrong. This is not a harness artifact: real Robinhood and
    # SoFi exports also write standalone fee rows -- `robinhood.py` maps both `"FEE"` and `"EMRF"`
    # to `TxnAction.FEE`, `sofi.py` maps `"transfer fee"` the same way -- so the blast radius is any
    # real account viewed inside the T+1/T+2 settlement window on a sale that carried one, not only
    # the UAT harness's deliberately-separated fee rows.
    #
    # `t.action is not TxnAction.BUY` fixed the fee case but re-opened a different door: `BUY` is
    # not the only action whose cash is committed and gone. A pending `cash_out` (a withdrawal
    # already requested) or a pending `transfer_out` (an ACAT cash leg already leaving) is just as
    # committed as a purchase, and letting either one's negative amount net into `unsettled` drives
    # it negative -- `settled` then exceeds `balance` again, the identical failure the six-buys
    # measurement above describes, through a different action code. `_is_committed_outflow` is the
    # kind-based (not sign-based) rule this needs: see its docstring and the two module-level sets
    # it reads, `_COMMITTED_OUTFLOW_ACTIONS` and `_BIDIRECTIONAL_ACTIONS`, which classify every one
    # of `TxnAction`'s members deliberately rather than falling through a default.
    #
    # A fee already tied to a *settled* sale, or carrying no settle_date at all, falls out of this
    # the same way every other row does: no settle_date reads as settled (this module's own rule,
    # see the module docstring), and a settle_date at or before `as_of` is simply not pending.
    pending_inflows = [
        t
        for t in cash_rows
        if t.settle_date is not None
        and t.settle_date > as_of
        and t.amount is not None
        and not _is_committed_outflow(t)
    ]
    unsettled_raw = sum((t.amount for t in pending_inflows if t.amount is not None), Decimal(0))

    # `_is_committed_outflow` is a deliberate, per-action judgment, not an exhaustive proof --
    # `ADJUSTMENT` and `MISC` in particular carry no evidence of direction beyond their own sign,
    # and even a correctly-classified pending fee (netted in on purpose, per the case above) can
    # still exceed whatever pending proceeds it rides with if there is nothing pending to net it
    # against. Either way the arithmetic can still land `unsettled` below zero, and `unsettled` is
    # proceeds -- it is never allowed to be negative, by the field's own contract. Rather than
    # publish a negative "proceeds" figure or let `settled` exceed `balance` -- the exact failure
    # this file exists to refuse -- the split is withheld the same way a whole balance is withheld
    # elsewhere in this module (`_withheld`, `CashVerdict.NEGATIVE_IN_CASH_ACCOUNT`): `balance`
    # stays derived, because it does not depend on this split, but `settled` and `unsettled` both
    # come back `None`, and `AccountCash.reason` explains why. This is the structural guarantee;
    # the classification above is what keeps it from firing on any case measured so far.
    settled: Decimal | None
    unsettled: Decimal | None
    unsettled_next_date: dt.date | None
    unsettled_full_date: dt.date | None
    if unsettled_raw < 0:
        # Withheld together with the split it would otherwise be attached to -- see
        # `AccountCash.unsettled_next_date`'s docstring for why a date is not published against a
        # figure that was not.
        settled, unsettled = None, None
        unsettled_next_date, unsettled_full_date = None, None
    else:
        settled, unsettled = balance - unsettled_raw, unsettled_raw
        # `pending_inflows` was already filtered on `t.settle_date is not None` above; the `is not
        # None` here repeats that for the type checker rather than the runtime, same reasoning as the
        # identical repetition on `cash_rows` a few lines up -- narrowing a comprehension's filter
        # does not narrow the type of what it draws from.
        pending_dates = sorted(
            {t.settle_date for t in pending_inflows if t.settle_date is not None}
        )
        # Both ends of the range, not one. An empty `pending_inflows` (the ordinary "fully settled"
        # case, `unsettled_raw == 0`) leaves both `None`, which is exactly the "nothing pending, so
        # no date" state -- distinct from the withheld branch above, per the field's own docstring.
        unsettled_next_date = pending_dates[0] if pending_dates else None
        unsettled_full_date = pending_dates[-1] if pending_dates else None

    return AccountCash(
        account_id=account.account_id,
        account_label=account.label,
        broker=account.broker.value,
        account_type=account.account_type,
        tax_treatment=account.tax_treatment,
        verdict=CashVerdict.DERIVED,
        balance=balance,
        settled=settled,
        unsettled=unsettled,
        unsettled_next_date=unsettled_next_date,
        unsettled_full_date=unsettled_full_date,
        funding_row_count=funding,
        cash_row_count=len(cash_rows),
        first_transaction=window[0],
        last_transaction=window[1],
    )


def _running_minimum(cash_rows: Sequence[Transaction]) -> tuple[Decimal, dt.date | None]:
    """The lowest the balance ever reaches, and the date it first got there.

    Rows are summed in ``(trade_date, sequence)`` order rather than in the order handed in, because
    the caller's order is not guaranteed and a running balance is meaningless without one. Same-day
    ordering uses ``sequence``, the tie-break the ledger already assigns from source-file position
    for exactly this purpose.

    Settlement is intentionally ignored here. The question is whether the account could ever have
    held this little cash, and a settle date does not change whether the money existed -- only when
    it became spendable.
    """
    running = Decimal(0)
    low = Decimal(0)
    low_date: dt.date | None = None
    for transaction in sorted(cash_rows, key=lambda t: (t.trade_date, t.sequence, t.txn_id)):
        assert transaction.amount is not None  # filtered by the caller
        running += transaction.amount
        if running < low:
            low = running
            low_date = transaction.trade_date
    return low, low_date


def _withheld(
    account: Account,
    verdict: CashVerdict,
    *,
    funding: int,
    cash_rows: int,
    window: tuple[dt.date, dt.date] | None,
    missing_opening_balance: Decimal | None = None,
    first_negative_on: dt.date | None = None,
) -> AccountCash:
    return AccountCash(
        account_id=account.account_id,
        account_label=account.label,
        broker=account.broker.value,
        account_type=account.account_type,
        tax_treatment=account.tax_treatment,
        verdict=verdict,
        balance=None,
        settled=None,
        unsettled=None,
        funding_row_count=funding,
        cash_row_count=cash_rows,
        first_transaction=window[0] if window else None,
        last_transaction=window[1] if window else None,
        missing_opening_balance=missing_opening_balance,
        first_negative_on=first_negative_on,
    )


def _sum_all_or_none(values: Iterable[Decimal | None]) -> Decimal | None:
    """Sum, or ``None`` if **any** contributing account could not supply the figure.

    Stricter than :func:`_sum_or_none`, and deliberately so: the settled/unsettled split is not a
    balance, it is a *partition of one*. ``settled + unsettled == balance`` is the invariant the
    whole field exists under, and summing only the accounts that happen to publish a split silently
    breaks it. On a real ledger where only some accounts declare a split, the settled and unsettled
    totals did not add to the balance total and read as "most of this portfolio's cash is
    unsettled", which is false and is exactly the kind of confident wrong number this module exists
    to refuse.

    A partial *balance* is still useful, which is why the balance total keeps the laxer rule and
    names its gap in ``accounts_without_cash``. A partial split is not useful at all -- there is no
    honest way to caption "settled cash, over some of your accounts" -- so it is withheld instead.
    """
    collected: list[Decimal] = []
    for value in values:
        if value is None:
            return None
        collected.append(value)
    if not collected:
        return None
    return sum(collected, Decimal(0))


def _sum_or_none(values: Iterable[Decimal | None]) -> Decimal | None:
    """Sum, or ``None`` if there was nothing to sum.

    Distinguishes "every account was excluded" from "the accounts summed to zero", which are
    different facts and read identically if both render as ``0.00``.
    """
    collected = [value for value in values if value is not None]
    if not collected:
        return None
    return sum(collected, Decimal(0))

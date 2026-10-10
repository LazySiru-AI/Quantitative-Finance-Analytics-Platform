"""Which existing account does this export belong to?

An adapter is chosen by header signature, and the account is declared by the user in
``data/accounts.toml`` (see :mod:`app.ingest.manifest`) because nothing in a file identifies which
of a broker's accounts it is. That is still true, and this module does not change it: **it computes
evidence, it does not decide.**

The evidence is exact rather than heuristic. ``txn_id`` is a deterministic hash of the transaction's
identifying fields *including the account*, so for any candidate account the ids an incoming file
would produce can be recomputed and looked up in the ledger. A re-export of an account already
stored overlaps heavily; a genuinely new account overlaps with nothing. No fuzzy matching on dates
or amounts is involved, and there is no threshold to tune.

**This only works because identity is stable across exports.** It was not until 2026-08-14:
``sequence`` was the row's position in the source file, so a longer export of the same account
produced different ids for the same trades and every file looked new. See
:class:`app.core.ids.TransactionSequencer`.

Two things this deliberately will not do:

* **Match across brokers.** A Robinhood export cannot be a Webull account, and offering it as a
  candidate would be noise at best.
* **Decide on a symbol or date overlap alone.** Two accounts at one broker holding the same ETFs
  over the same months overlap heavily on both and share no transactions. That signal is reported
  as context, clearly separated from the exact one, and never ranked above it -- it is the kind of
  evidence that looks convincing and merges two accounts.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.core.ids import transaction_id
from app.core.models import Account, Transaction

__all__ = ["AccountMatch", "FileMatches", "match_accounts"]

#: How much of one set must lie inside the other before the match is treated as decided rather than
#: as one candidate among several. Applied in both directions -- see
#: :attr:`AccountMatch.is_decisive`. The threshold is high because the failure it guards against,
#: merging two accounts, silently corrupts every downstream tax figure and is invisible afterwards.
_DECISIVE_COVERAGE = 0.90


@dataclass(frozen=True, slots=True)
class AccountMatch:
    """How much of an incoming file an existing account already holds."""

    account_id: str
    account_label: str
    broker: str
    tax_treatment: str

    overlapping: int
    """Incoming rows whose ``txn_id`` is already stored under this account. Exact, not inferred."""
    incoming_total: int
    account_total: int
    """Rows the account holds in total, so "42 of 45 shared" can be read against "the account has
    1,000" -- a small overlap with a large account means something different than with a small one."""

    shared_symbols: int = 0
    """Symbols appearing both in the file and in the account. **Context only.** Two accounts at one
    broker holding the same ETFs share every symbol and no transactions."""
    incoming_symbols: int = 0

    @property
    def overlap_fraction(self) -> float:
        """Share of the *incoming file* already stored here. ``0.0`` when the file has no rows.

        The weaker of the two ratios, and the misleading one on its own: a fresh export covering
        eight months against an account holding five is mostly new rows, so this reads low precisely
        when the match is certain."""
        return self.overlapping / self.incoming_total if self.incoming_total else 0.0

    @property
    def account_coverage(self) -> float:
        """Share of *this account* the file contains. The signal that actually discriminates.

        Illustration: a new Robinhood export that shares many rows with one account and a few with
        another. As a share of the file both overlaps can look small, and the second not obviously
        noise. As a share of each account they are **100%** and a small fraction: the file contains
        that entire account and coincidentally repeats a few same-day, same-price trades of
        another. Coincidence is expected between two accounts at one broker
        trading the same instruments; containing an account whole is not."""
        return self.overlapping / self.account_total if self.account_total else 0.0

    @property
    def is_exact(self) -> bool:
        """Whether any transaction is genuinely shared. The only signal worth deciding on."""
        return self.overlapping > 0

    @property
    def is_decisive(self) -> bool:
        """One of the two sets contains the other, so the answer is not a judgement call.

        Both directions count, and they are different situations with the same answer:

        * The file **contains the account** -- an ordinary re-export, months longer than what is
          stored. A new Robinhood export holds all of an account's stored rows and adds many more.
        * The account **contains the file** -- a narrow slice, often a date-bounded export pulled
          for one purpose. A date-bounded export holds a few transactions, every one of
          them already in the account, and would add nothing.

        The second reads as weak on account coverage alone (a few rows of a much larger account) and is in fact the more
        certain of the two: everything in the file is already in that account. Treating it as
        undecided pushes the user toward "create a new account", which would store all those trades a
        second time.
        """
        return (
            self.account_coverage >= _DECISIVE_COVERAGE
            or self.overlap_fraction >= _DECISIVE_COVERAGE
        )

    @property
    def new_rows(self) -> int:
        """Rows this file would add if attached here."""
        return self.incoming_total - self.overlapping


@dataclass(frozen=True, slots=True)
class FileMatches:
    """Every candidate for one file, best first."""

    candidates: tuple[AccountMatch, ...] = field(default_factory=tuple)

    @property
    def best(self) -> AccountMatch | None:
        """The single account with shared transactions, when there is exactly one.

        ``None`` when nothing overlaps -- which reads as "this is a new account" -- and also when
        two accounts both overlap, which should not happen and is not something to resolve by
        picking the larger. Identical trades in two accounts at one broker is either a genuine
        cross-account duplicate the user needs to see, or an id collision worth investigating; a
        silent choice would bury both.
        """
        # Sharing *some* rows is not enough, even when only one account shares any. Two accounts
        # running the same strategy produce genuinely identical trades -- same day, symbol, size and
        # price -- and a handful of those is not evidence that one file is the other account. Only
        # containment decides, in either direction: see :attr:`AccountMatch.is_decisive`.
        #
        # The asymmetry is deliberate. Suggesting nothing costs the user a decision they can make
        # from the evidence on screen; suggesting wrongly merges two accounts, which corrupts every
        # downstream tax figure and leaves nothing on screen to show it happened.
        decisive = [c for c in self.candidates if c.is_decisive]
        return decisive[0] if len(decisive) == 1 else None

    @property
    def ambiguous(self) -> bool:
        """More than one account contains this file, or is contained by it.

        Distinct from "several accounts share rows", which is normal and not ambiguous -- it is the
        expected shape of two accounts trading alike. This is the case where the evidence genuinely
        points two ways at once, and it should not happen: identical trades wholly duplicated across
        two accounts is either something the user needs to see or an identity collision worth
        investigating. Either way, choosing would bury it.
        """
        return sum(1 for c in self.candidates if c.is_decisive) > 1


def match_accounts(
    transactions: Sequence[Transaction],
    *,
    accounts: Sequence[Account],
    conn: sqlite3.Connection,
) -> FileMatches:
    """Score every same-broker account against the transactions an export would produce.

    ``transactions`` come from parsing the file against *any* account -- the ids are recomputed here
    per candidate, so whichever placeholder the caller used does not matter.

    Ordered by **account coverage** first -- the share of the candidate account the file contains --
    then by raw overlap, then by shared symbols, then by id for determinism. Coverage leads because
    it is the ratio that separates "this file *is* that account" from "these two accounts hold the
    same ETFs"; see :attr:`AccountMatch.account_coverage` for the measurement that settled it.
    """
    if not transactions:
        return FileMatches()

    broker = transactions[0].broker
    incoming_symbols = {t.symbol.upper() for t in transactions if t.symbol}

    stored_ids: set[str] = {
        str(row["txn_id"]) for row in conn.execute("SELECT txn_id FROM txn")
    }
    account_rows: dict[str, int] = {
        str(row["account_id"]): int(row["n"])
        for row in conn.execute("SELECT account_id, COUNT(*) AS n FROM txn GROUP BY account_id")
    }
    account_symbols: dict[str, set[str]] = {}
    for row in conn.execute(
        "SELECT account_id, symbol FROM txn WHERE symbol IS NOT NULL GROUP BY account_id, symbol"
    ):
        account_symbols.setdefault(str(row["account_id"]), set()).add(str(row["symbol"]).upper())

    candidates: list[AccountMatch] = []
    for account in accounts:
        if account.broker is not broker:
            continue

        overlapping = sum(
            1
            for txn in transactions
            if transaction_id(
                broker=txn.broker.value,
                account_id=account.account_id,
                trade_date=txn.trade_date,
                action=txn.action.value,
                symbol=txn.symbol,
                quantity=txn.quantity,
                price=txn.price,
                amount=txn.amount,
                sequence=txn.sequence,
            )
            in stored_ids
        )
        stored_symbols = account_symbols.get(account.account_id, set())
        candidates.append(
            AccountMatch(
                account_id=account.account_id,
                account_label=account.label,
                broker=account.broker.value,
                tax_treatment=account.tax_treatment.value,
                overlapping=overlapping,
                incoming_total=len(transactions),
                account_total=account_rows.get(account.account_id, 0),
                shared_symbols=len(incoming_symbols & stored_symbols),
                incoming_symbols=len(incoming_symbols),
            )
        )

    candidates.sort(
        key=lambda c: (-c.account_coverage, -c.overlapping, -c.shared_symbols, c.account_id)
    )
    return FileMatches(candidates=tuple(candidates))

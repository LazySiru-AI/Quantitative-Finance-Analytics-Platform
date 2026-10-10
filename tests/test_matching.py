"""Which existing account an incoming export belongs to.

The evidence is exact -- ``txn_id`` includes the account, so the ids a file would produce under each
candidate are recomputed and looked up -- but "exact" is not the same as "unambiguous". Two accounts
at one broker trading the same instruments genuinely share transactions: same day, same symbol, same
size, same price. The tests that matter here are the ones about telling that apart from a file that
contains an account whole.

Modelled on what real data looks like: a newer export of an account overlaps heavily with one
account and slightly with another.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from decimal import Decimal

import pytest

from app.core.models import Account, AccountType, Broker, TaxTreatment, Transaction, TxnAction
from app.db import sqlite as ledger
from app.ingest.matching import match_accounts
from tests.conftest import make_txn


def _account(account_id: str, broker: Broker = Broker.ROBINHOOD) -> Account:
    return Account(
        account_id=account_id,
        broker=broker,
        label=account_id,
        tax_treatment=TaxTreatment.TAXABLE,
        account_type=AccountType.CASH,
    )


def _txn(account_id: str, *, day: int, symbol: str = "AAAA", qty: str = "10") -> Transaction:
    """A transaction whose identity depends only on the account and the day/symbol/size."""
    return make_txn(
        txn_id="placeholder",
        account_id=account_id,
        symbol=symbol,
        quantity=qty,
        price="10.00",
        amount="-100.00",
        trade_date=dt.date(2026, 3, day),
    )


def _rebuild_ids(txns: list[Transaction], account_id: str) -> list[Transaction]:
    """Re-key transactions onto ``account_id``, exactly as an adapter would when parsing for it."""
    from app.core.ids import TransactionSequencer

    sequencer = TransactionSequencer()
    out = []
    for txn in txns:
        txn_id, sequence = sequencer.assign(
            broker=txn.broker.value,
            account_id=account_id,
            trade_date=txn.trade_date,
            action=txn.action.value,
            symbol=txn.symbol,
            quantity=txn.quantity,
            price=txn.price,
            amount=txn.amount,
        )
        out.append(
            txn.model_copy(update={"txn_id": txn_id, "sequence": sequence, "account_id": account_id})
        )
    return out


@pytest.fixture
def stocked(conn: sqlite3.Connection) -> sqlite3.Connection:
    """A ledger with two Robinhood accounts and one Webull account, plus the import rows to hang
    transactions off -- `txn.import_id` is a foreign key, so a bare account is not enough."""
    for account_id, broker in (
        ("rh-taxable", Broker.ROBINHOOD),
        ("rh-short-cash", Broker.ROBINHOOD),
        ("wb-cash", Broker.WEBULL),
    ):
        ledger.upsert_account(conn, _account(account_id, broker))
    conn.execute(
        "INSERT OR IGNORE INTO raw_import (import_id, source_path, filename, file_sha256, "
        "content_hash, broker, account_id, adapter, adapter_version, row_count, usable_row_count, "
        "imported_at) VALUES ('imp1','p','f','s','c','robinhood','rh-taxable','robinhood','1',1,1,"
        "'2026-01-01T00:00:00Z')"
    )
    return conn


class TestExactOverlap:
    def test_a_file_containing_an_account_whole_is_the_match(
        self, stocked: sqlite3.Connection
    ) -> None:
        """The shape of a re-export: it holds everything the account has, plus months more."""
        stored = _rebuild_ids([_txn("x", day=d) for d in (2, 3, 4)], "rh-taxable")
        ledger.insert_transactions(stocked, stored)

        incoming = _rebuild_ids(
            [_txn("probe", day=d) for d in (2, 3, 4, 5, 6, 7, 8)], "__probe__"
        )
        matches = match_accounts(
            incoming, accounts=ledger.fetch_accounts(stocked), conn=stocked
        )

        best = matches.best
        assert best is not None
        assert best.account_id == "rh-taxable"
        assert best.overlapping == 3
        assert best.account_coverage == 1.0
        assert best.new_rows == 4

    def test_no_overlap_reads_as_a_new_account(self, stocked: sqlite3.Connection) -> None:
        """Nothing shared with any account of the broker is the signal for "this is new"."""
        ledger.insert_transactions(
            stocked, _rebuild_ids([_txn("x", day=d) for d in (2, 3)], "rh-taxable")
        )

        incoming = _rebuild_ids([_txn("p", day=d, symbol="ZZZZ") for d in (20, 21)], "__probe__")
        matches = match_accounts(
            incoming, accounts=ledger.fetch_accounts(stocked), conn=stocked
        )

        assert matches.best is None
        assert matches.ambiguous is False
        assert all(c.overlapping == 0 for c in matches.candidates)

    def test_coverage_beats_raw_overlap_in_the_ranking(
        self, stocked: sqlite3.Connection
    ) -> None:
        """The case seen in real data, in miniature.

        A file can share more *rows* with a big account than with the small one it actually is. What
        separates them is the share of each account consumed: containing an account whole is a match,
        repeating a few of a larger account's same-price trades is a coincidence.
        """
        # The real account: small, and wholly contained in the file.
        ledger.insert_transactions(
            stocked, _rebuild_ids([_txn("x", day=d) for d in (2, 3)], "rh-taxable")
        )
        # A larger account that happens to share four same-day, same-price trades with the file.
        ledger.insert_transactions(
            stocked,
            _rebuild_ids(
                [_txn("x", day=d, symbol="BBBB") for d in (4, 5, 6, 7)]
                + [_txn("x", day=d, symbol="CCCC") for d in (10, 11, 12, 13, 14, 15)],
                "rh-short-cash",
            ),
        )

        incoming = _rebuild_ids(
            [_txn("p", day=d) for d in (2, 3)]
            + [_txn("p", day=d, symbol="BBBB") for d in (4, 5, 6, 7)],
            "__probe__",
        )
        matches = match_accounts(
            incoming, accounts=ledger.fetch_accounts(stocked), conn=stocked
        )

        by_id = {c.account_id: c for c in matches.candidates}
        assert by_id["rh-short-cash"].overlapping > by_id["rh-taxable"].overlapping
        assert by_id["rh-taxable"].account_coverage == 1.0
        assert by_id["rh-short-cash"].account_coverage == 0.4

        assert matches.candidates[0].account_id == "rh-taxable", "coverage leads the ranking"
        assert matches.best is not None and matches.best.account_id == "rh-taxable"
        assert matches.ambiguous is False, "one candidate stands out, so this is not ambiguous"

    def test_two_equally_covered_accounts_are_ambiguous(
        self, stocked: sqlite3.Connection
    ) -> None:
        """No answer is better than a coin flip when merging accounts is the failure mode.

        Two accounts both wholly contained in one file is either a genuine cross-account duplicate
        the user needs to see or an identity collision worth investigating. Picking the larger would
        bury both.
        """
        rows = [_txn("x", day=d) for d in (2, 3)]
        ledger.insert_transactions(stocked, _rebuild_ids(rows, "rh-taxable"))
        ledger.insert_transactions(stocked, _rebuild_ids(rows, "rh-short-cash"))

        incoming = _rebuild_ids([_txn("p", day=d) for d in (2, 3)], "__probe__")
        matches = match_accounts(
            incoming, accounts=ledger.fetch_accounts(stocked), conn=stocked
        )

        assert matches.best is None
        assert matches.ambiguous is True


class TestScope:
    def test_only_same_broker_accounts_are_candidates(
        self, stocked: sqlite3.Connection
    ) -> None:
        """A Robinhood export cannot be a Webull account, so offering it is noise."""
        incoming = _rebuild_ids([_txn("p", day=2)], "__probe__")
        matches = match_accounts(
            incoming, accounts=ledger.fetch_accounts(stocked), conn=stocked
        )

        assert {c.account_id for c in matches.candidates} == {"rh-taxable", "rh-short-cash"}
        assert "wb-cash" not in {c.account_id for c in matches.candidates}

    def test_shared_symbols_never_produce_a_match_on_their_own(
        self, stocked: sqlite3.Connection
    ) -> None:
        """Context, not evidence.

        Two accounts holding the same ETFs share every symbol and no transactions. Deciding on that
        is how two accounts get merged, so it is reported beside the exact count and never ranked
        above it.
        """
        ledger.insert_transactions(
            stocked, _rebuild_ids([_txn("x", day=d, symbol="SPY") for d in (2, 3)], "rh-taxable")
        )

        incoming = _rebuild_ids(
            [_txn("p", day=d, symbol="SPY", qty="99") for d in (20, 21)], "__probe__"
        )
        matches = match_accounts(
            incoming, accounts=ledger.fetch_accounts(stocked), conn=stocked
        )

        candidate = next(c for c in matches.candidates if c.account_id == "rh-taxable")
        assert candidate.shared_symbols == 1
        assert candidate.overlapping == 0
        assert candidate.is_exact is False
        assert matches.best is None

    def test_an_empty_file_yields_no_candidates(self, stocked: sqlite3.Connection) -> None:
        matches = match_accounts([], accounts=ledger.fetch_accounts(stocked), conn=stocked)
        assert matches.candidates == ()
        assert matches.best is None

    def test_an_empty_ledger_offers_nothing_to_attach_to(
        self, conn: sqlite3.Connection
    ) -> None:
        """A first import has no candidates, which is the correct answer rather than an error."""
        incoming = _rebuild_ids([_txn("p", day=2)], "__probe__")
        matches = match_accounts(incoming, accounts=[], conn=conn)

        assert matches.candidates == ()
        assert matches.best is None


def test_quantities_and_prices_participate_in_identity(stocked: sqlite3.Connection) -> None:
    """A same-day trade of the same symbol at a different size is a different transaction.

    Without this the matcher would report an overlap between two accounts that merely traded the
    same ticker on the same day, which is common and means nothing.
    """
    ledger.insert_transactions(
        stocked, _rebuild_ids([_txn("x", day=2, qty="10")], "rh-taxable")
    )
    incoming = _rebuild_ids([_txn("p", day=2, qty="11")], "__probe__")

    matches = match_accounts(incoming, accounts=ledger.fetch_accounts(stocked), conn=stocked)
    assert all(c.overlapping == 0 for c in matches.candidates)


def test_decimal_formatting_does_not_break_a_match(stocked: sqlite3.Connection) -> None:
    """``10`` and ``10.00`` are the same quantity; a broker changing its trailing zeros must not
    make an already-stored trade look new. Canonicalisation lives in `app.core.ids`, and this pins
    that the matcher inherits it."""
    ledger.insert_transactions(
        stocked, _rebuild_ids([_txn("x", day=2, qty="10")], "rh-taxable")
    )
    incoming = _rebuild_ids([_txn("p", day=2, qty="10.00")], "__probe__")

    matches = match_accounts(incoming, accounts=ledger.fetch_accounts(stocked), conn=stocked)
    best = matches.best
    assert best is not None and best.account_id == "rh-taxable"
    assert best.overlapping == 1


def test_price_precision_is_canonicalised_too(stocked: sqlite3.Connection) -> None:
    ledger.insert_transactions(
        stocked, _rebuild_ids([_txn("x", day=2)], "rh-taxable")
    )
    incoming = [
        t.model_copy(update={"price": Decimal("10.000")})
        for t in _rebuild_ids([_txn("p", day=2)], "__probe__")
    ]
    incoming = _rebuild_ids(incoming, "__probe__")

    matches = match_accounts(incoming, accounts=ledger.fetch_accounts(stocked), conn=stocked)
    assert matches.best is not None


def test_action_participates_in_identity(stocked: sqlite3.Connection) -> None:
    """A buy and a sell of the same size on the same day are not the same transaction."""
    ledger.insert_transactions(stocked, _rebuild_ids([_txn("x", day=2)], "rh-taxable"))
    incoming = [
        t.model_copy(update={"action": TxnAction.SELL})
        for t in _rebuild_ids([_txn("p", day=2)], "__probe__")
    ]
    incoming = _rebuild_ids(incoming, "__probe__")

    matches = match_accounts(incoming, accounts=ledger.fetch_accounts(stocked), conn=stocked)
    assert all(c.overlapping == 0 for c in matches.candidates)


class TestContainedEitherWay:
    """A match is decided when either set contains the other, not only when the file is bigger."""

    def test_a_narrow_slice_of_an_account_is_recognised(
        self, stocked: sqlite3.Connection
    ) -> None:
        """The mirror case, and the more certain of the two.

        A date-bounded export pulled for one purpose holds a handful of transactions, every one of
        them already stored. On account coverage alone it looks weak -- the user's own file holds 13
        of `rh-roth`'s 224, which is 6% -- while in fact it adds nothing at all. Reading that as
        undecided pushes the user toward "create a new account", which stores all 13 a second time.
        """
        ledger.insert_transactions(
            stocked,
            _rebuild_ids([_txn("x", day=d) for d in range(2, 22)], "rh-taxable"),
        )

        incoming = _rebuild_ids([_txn("p", day=d) for d in (2, 3)], "__probe__")
        matches = match_accounts(
            incoming, accounts=ledger.fetch_accounts(stocked), conn=stocked
        )

        best = matches.best
        assert best is not None
        assert best.account_id == "rh-taxable"
        assert best.new_rows == 0, "nothing to add: it is already all there"
        assert best.overlap_fraction == 1.0
        assert best.account_coverage < 0.2, "weak on this ratio, and still decided"

    def test_a_partial_overlap_of_both_stays_undecided(
        self, stocked: sqlite3.Connection
    ) -> None:
        """Neither contains the other, so there is no answer to give.

        Half a file matching half an account is the shape of two accounts that traded alike, not of
        a re-export. Suggesting one would be a guess dressed as evidence.
        """
        ledger.insert_transactions(
            stocked,
            _rebuild_ids([_txn("x", day=d) for d in range(2, 12)], "rh-taxable"),
        )

        incoming = _rebuild_ids(
            [_txn("p", day=d) for d in (2, 3, 4)]
            + [_txn("p", day=d, symbol="ZZZZ") for d in (20, 21, 22, 23, 24, 25, 26)],
            "__probe__",
        )
        matches = match_accounts(
            incoming, accounts=ledger.fetch_accounts(stocked), conn=stocked
        )

        candidate = matches.candidates[0]
        assert candidate.overlapping == 3
        assert candidate.is_decisive is False
        assert matches.best is None

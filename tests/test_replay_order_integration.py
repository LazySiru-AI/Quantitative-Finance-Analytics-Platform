"""End-to-end regression for the newest-first replay bug.

Two independent pieces were fixed together: every adapter now tags each transaction with
``replay_order`` (see ``app.ingest.adapters.base.ExportOrder``), and
``app.db.sqlite.fetch_transactions`` orders on it instead of ``source_row``. Neither half proves
anything on its own -- the per-adapter tests already pin that ``replay_order`` comes out right, and
``TestReplayOrderMigration`` in ``tests/test_stores.py`` pins the backfill. This file is the one that
exercises both halves together, through the exact path ``app.core.lots.build_lots`` sees in
production: store a same-day round trip the way a newest-first export would produce it, read it back
through ``fetch_transactions``, and replay it.

Before the fix: a same-day round trip (buy 50, sell 50) from a broker that publishes no execution
time -- Robinhood and SoFi -- replayed as sell-then-buy, because ``fetch_transactions`` broke the tie
on ``source_row`` and both brokers write newest-first. The sale found no lot, booked a zero-basis
disposal and raised ``oversold``; the purchase then opened a lot nothing ever closed. On a
real ledger this left a large phantom open position in a heavily traded symbol. See
``ExportOrder``'s docstring for the full account.

``test_the_old_source_row_ordering_produced_exactly_the_phantom_bug`` below is the check that this
test is not vacuous: feeding ``build_lots`` the same two transactions in the pre-fix order (ascending
``source_row`` on a newest-first file) reproduces the oversold warning and the phantom open lot
exactly. Confirmed by hand while writing this file, the same way: pointing
``test_build_lots_over_the_corrected_order_closes_cleanly`` at the wrong-order list instead of
``fetch_transactions``'s output turns its assertions red.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from decimal import Decimal

from app.core.lots import WarningKind, build_lots
from app.core.models import LotStatus, Transaction, TxnAction
from app.db import sqlite as ledger
from tests.conftest import make_txn, sample_account

ACCOUNT_ID = "rh-taxable"
ACCOUNTS = {ACCOUNT_ID: sample_account(account_id=ACCOUNT_ID)}


def _record_robinhood_import(conn: sqlite3.Connection, import_id: str = "imp1") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO raw_import (import_id, source_path, filename, file_sha256, "
        "content_hash, broker, account_id, adapter, adapter_version, row_count, "
        "usable_row_count, imported_at) VALUES (?, 'p', 'f.csv', 'sha', 'content', "
        "'robinhood', 'rh-taxable', 'robinhood', '1.1.0', 2, 2, '2026-01-01T00:00:00Z')",
        (import_id,),
    )


def _same_day_round_trip() -> tuple[Transaction, Transaction]:
    """A buy and a later same-day sell of the same symbol, tagged exactly as the Robinhood adapter
    would tag them from a newest-first file: row 0 (``source_row``) is the sell -- the file's own
    newest-first order puts the more recent event first -- and row 1 is the buy. ``replay_order`` is
    ``ExportOrder.NEWEST_FIRST.replay_order_for`` for a 2-row file: index 0 -> 1, index 1 -> 0.
    """
    same_day = dt.date(2026, 3, 2)
    sell = make_txn(
        txn_id="sell-same-day",
        action=TxnAction.SELL,
        symbol="SOXL",
        quantity="50",
        price="30.00",
        amount="1500.00",
        trade_date=same_day,
        source_row=0,
        replay_order=1,
    )
    buy = make_txn(
        txn_id="buy-same-day",
        action=TxnAction.BUY,
        symbol="SOXL",
        quantity="50",
        price="24.10",
        amount="-1205.00",
        trade_date=same_day,
        source_row=1,
        replay_order=0,
    )
    return sell, buy


class TestReplayOrderFixesTheSameDayRoundTrip:
    def test_fetch_transactions_replays_the_buy_before_the_sell(
        self, conn: sqlite3.Connection
    ) -> None:
        """The store half of the fix in isolation: `fetch_transactions` must use `replay_order`,
        not the newest-first file's `source_row`, to break the same-date tie."""
        _record_robinhood_import(conn)
        sell, buy = _same_day_round_trip()
        ledger.insert_transactions(conn, [sell, buy])  # inserted in file order: sell first

        ordered = [ledger.transaction_from_row(r) for r in ledger.fetch_transactions(conn)]
        assert [t.txn_id for t in ordered] == ["buy-same-day", "sell-same-day"]

    def test_build_lots_over_the_corrected_order_closes_cleanly(
        self, conn: sqlite3.Connection
    ) -> None:
        """The point of the whole fix, exercised end to end: no phantom position, no warning."""
        _record_robinhood_import(conn)
        sell, buy = _same_day_round_trip()
        ledger.insert_transactions(conn, [sell, buy])

        transactions = [ledger.transaction_from_row(r) for r in ledger.fetch_transactions(conn)]
        result = build_lots(transactions, accounts=ACCOUNTS)

        assert result.open_lots() == []
        assert result.warnings == []

        assert len(result.lots) == 1
        lot = result.lots[0]
        assert lot.status is LotStatus.CLOSED
        assert lot.remaining == Decimal(0)
        assert lot.cost_basis == Decimal("1205.00")

        assert len(result.disposals) == 1
        disposal = result.disposals[0]
        assert disposal.cost_basis == Decimal("1205.00")
        assert disposal.proceeds == Decimal("1500.00")
        assert disposal.gain_loss == Decimal("295.00")

    def test_the_old_source_row_ordering_produced_exactly_the_phantom_bug(self) -> None:
        """Not a test of production code -- a record of what the pre-fix bug looked like, built by
        handing `build_lots` the same two transactions ordered the way the old
        `ORDER BY ..., source_row, ...` tie-break would have produced from this newest-first file
        (ascending `source_row`, i.e. sell before buy). This is what confirms
        `test_build_lots_over_the_corrected_order_closes_cleanly` is not vacuous: swap which order
        is fed to `build_lots` and the phantom reappears.
        """
        sell, buy = _same_day_round_trip()
        wrong_order = sorted((sell, buy), key=lambda t: t.source_row)  # sell (0) before buy (1)
        assert [t.txn_id for t in wrong_order] == ["sell-same-day", "buy-same-day"]

        result = build_lots(wrong_order, accounts=ACCOUNTS)

        oversold = [w for w in result.warnings if w.kind is WarningKind.OVERSOLD]
        assert len(oversold) == 1
        assert oversold[0].quantity == Decimal(50)

        # The sale found no lot (a zero-basis disposal), and the later buy opened a lot nothing
        # closed -- the exact phantom-position shape seen on a real ledger.
        assert len(result.open_lots()) == 1
        assert result.open_lots()[0].remaining == Decimal(50)
        assert result.open_lots()[0].cost_basis == Decimal("1205.00")

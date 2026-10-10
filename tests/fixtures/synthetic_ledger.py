"""A frozen, deterministic ledger for pinning exact tax figures without touching real financial data.

``tests/test_canonical.py``'s ``TestRealLedgerCorrectedFigures`` used to pin absolute dollar figures
against the user's live ``data/store/ledger.sqlite``. That has two problems: the ledger is mutable
personal data, so every import re-broke the pins, and it is the densest source of real financial
figures in the repository (see ``docs/BEFORE-PUBLISHING.md``). This module replaces it with a small,
hand-built ledger of invented securities, written through the *real* production write path --
:func:`app.db.sqlite.migrate`, :func:`~app.db.sqlite.upsert_account`,
:func:`~app.db.sqlite.upsert_instrument`, :func:`~app.db.sqlite.record_import`, and
:func:`~app.db.sqlite.insert_transactions` -- so the figures it pins exercise the same
``fetch_transactions`` ordering and idempotent-write path production code does, not a
reimplementation of it.

Every figure is exact ``Decimal`` arithmetic on round or clearly-stated inputs; nothing here is
copied from or derived from any real account.

The ledger deliberately reproduces five defect shapes, each of which cost a real dollar figure on the
user's actual ledger at some point (see the git history and ``docs/BEFORE-PUBLISHING.md`` for context,
without repeating the figures here):

1. **Newest-first export ordering** (``QRVA``). A same-day round trip -- buy then sell -- tagged
   exactly as a newest-first Robinhood/SoFi export would tag it: ``replay_order`` correctly places the
   buy before the sell, but ``source_row`` (the file's own row order) is reversed. Before the
   replay-order fix, :func:`app.db.sqlite.fetch_transactions` broke the tie on ``source_row`` and
   replayed the sale first, producing a zero-basis disposal, an ``oversold`` warning, and a phantom
   open lot. See ``tests/test_replay_order_integration.py`` for the original, narrower regression test
   this mirrors at the whole-ledger level.

2. **Cross-broker instrument identity** (``KLDX``). Held at Robinhood (which supplies a CUSIP) and at
   Webull (which does not), so :func:`app.core.canonical.canonicalize_ledger` must merge the two
   ``instrument_id`` values for the wash sale between them to be visible at all -- the defect
   ``app.core.canonical``'s own module docstring is named for.

3. **A disallowance spread across two replacement lots** (``TRVK``). A single loss sale is replaced by
   two separate purchases (60 and 40 shares) bought on different dates, so the wash-sale disallowance
   splits across two lots. ``WashSaleEvent.basis_added_to_lot_id`` names only the larger one; both
   replacement lots are later sold in full, and only a correct ``_sync_disposals`` (one that walks
   every id in ``replacement_lot_ids``, not just the singular field) reports the right gain on the
   smaller lot's eventual sale.

4. **An IRA replacement** (``MRDX``, Rev. Rul. 2008-5). The loss sale is on a taxable account; the
   replacement is bought inside a Roth IRA, so the loss is permanently disallowed rather than
   deferred, and no basis is added anywhere.

5. **Sub-cent figures** (``FLNT``). A fractional-share fill (``12.3457`` shares) whose raw proceeds and
   basis carry six decimal places, exercising the rounding path where Form 8949 and ``GainsReport``
   once disagreed by a cent per row.

None of the five interact with each other: different symbols, non-overlapping wash-sale windows, and
none of the invented tickers appear in ``app.tax.washsale.DEFAULT_EQUIVALENCE``.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from app.core.ids import instrument_id as compute_instrument_id
from app.core.ids import transaction_id as compute_transaction_id
from app.core.models import (
    Account,
    AccountType,
    Broker,
    ImportRecord,
    Instrument,
    TaxTreatment,
    Transaction,
    TxnAction,
)
from app.db import sqlite as ledger_store

__all__ = [
    "ACCOUNTS",
    "AS_OF",
    "TAX_YEAR",
    "build_synthetic_ledger",
    "qrva_round_trip_in_file_order",
]

#: The tax year every disposal in this ledger falls into, and the year `report_from_ledger` should be
#: called with.
TAX_YEAR = 2026

#: `report_from_ledger`'s one clock-dependent input (see its docstring). Pinned so the wash-sale
#: summary's `days_until_safe`/`window_is_open` never drift with the calendar. Comfortably after
#: every sale date below, so every window this ledger triggers has already closed.
AS_OF = dt.date(2026, 12, 31)

RH_TAXABLE = Account(
    account_id="rh-taxable",
    broker=Broker.ROBINHOOD,
    label="RH Taxable (synthetic)",
    tax_treatment=TaxTreatment.TAXABLE,
    account_type=AccountType.CASH,
)
WB_MARGIN = Account(
    account_id="wb-margin",
    broker=Broker.WEBULL,
    label="Webull Margin (synthetic)",
    tax_treatment=TaxTreatment.TAXABLE,
    account_type=AccountType.MARGIN,
)
RH_ROTH = Account(
    account_id="rh-roth",
    broker=Broker.ROBINHOOD,
    label="RH Roth (synthetic)",
    tax_treatment=TaxTreatment.ROTH_IRA,
    account_type=AccountType.RETIREMENT,
)
ACCOUNTS = {a.account_id: a for a in (RH_TAXABLE, WB_MARGIN, RH_ROTH)}

#: Invented issuer names, in the style of `tests/fixtures`' existing CSV fixtures (`ZQXA`, "Zephyr
#: Quantum Analytics"). None of these tickers exist.
_NAMES = {
    "QRVA": "Quorion Vantage Robotics",
    "KLDX": "Kaldera Dynamics",
    "TRVK": "Traverse Kinetics",
    "MRDX": "Meridian Dax Corp",
    "FLNT": "Flint Halstead Materials",
}


def _txn(
    *,
    broker: Broker,
    account_id: str,
    import_id: str,
    action: TxnAction,
    trade_date: dt.date,
    symbol: str,
    cusip: str | None,
    quantity: Decimal,
    price: Decimal,
    amount: Decimal,
    source_row: int,
    replay_order: int,
) -> Transaction:
    """A transaction with ``instrument_id`` and ``txn_id`` computed exactly the way a real adapter
    would compute them -- CUSIP-keyed when a CUSIP is supplied, symbol-keyed otherwise, and the
    deterministic hash `app.core.ids.transaction_id` produces."""
    txn_id = compute_transaction_id(
        broker=broker.value,
        account_id=account_id,
        trade_date=trade_date,
        action=action.value,
        symbol=symbol,
        quantity=quantity,
        price=price,
        amount=amount,
        sequence=0,
    )
    return Transaction(
        txn_id=txn_id,
        import_id=import_id,
        source_row=source_row,
        replay_order=replay_order,
        account_id=account_id,
        broker=broker,
        action=action,
        trade_date=trade_date,
        sequence=0,
        symbol=symbol,
        cusip=cusip,
        instrument_id=compute_instrument_id(cusip=cusip, symbol=symbol),
        quantity=quantity,
        price=price,
        amount=amount,
    )


def _rh_taxable_transactions() -> list[Transaction]:
    """Every transaction in the taxable Robinhood account, in chronological (``replay_order``) order.

    ``source_row`` matches ``replay_order`` for every row except the ``QRVA`` same-day pair (case 1),
    where it is deliberately reversed -- see the module docstring.
    """
    account_id = RH_TAXABLE.account_id
    broker = Broker.ROBINHOOD
    import_id = "imp-rh-taxable"

    rows = [
        # idx0 -- TRVK original lot. Bought well before any wash-sale activity so the eventual
        # replacement lots' tolled holding period (case 3) lands unambiguously long-term.
        dict(
            action=TxnAction.BUY,
            trade_date=dt.date(2024, 1, 10),
            symbol="TRVK",
            cusip=None,
            quantity=Decimal("100"),
            price=Decimal("50.00"),
            amount=Decimal("-5000.00"),
        ),
        # idx1 -- FLNT fractional-share buy (case 5).
        dict(
            action=TxnAction.BUY,
            trade_date=dt.date(2025, 4, 1),
            symbol="FLNT",
            cusip=None,
            quantity=Decimal("12.3457"),
            price=Decimal("81.23"),
            amount=Decimal("-1002.841211"),
        ),
        # idx2 -- KLDX bought at Robinhood, which supplies the CUSIP (case 2).
        dict(
            action=TxnAction.BUY,
            trade_date=dt.date(2025, 6, 1),
            symbol="KLDX",
            cusip="K0000A105",
            quantity=Decimal("100"),
            price=Decimal("50.00"),
            amount=Decimal("-5000.00"),
        ),
        # idx3 -- MRDX original lot, later sold at a loss and replaced inside a Roth IRA (case 4).
        dict(
            action=TxnAction.BUY,
            trade_date=dt.date(2025, 9, 1),
            symbol="MRDX",
            cusip=None,
            quantity=Decimal("30"),
            price=Decimal("40.00"),
            amount=Decimal("-1200.00"),
        ),
        # idx4 -- KLDX sold at a loss; the replacement is bought at Webull under a bare symbol
        # (idx_w0 below), so this is only a wash sale once canonicalize_ledger merges the two ids.
        dict(
            action=TxnAction.SELL,
            trade_date=dt.date(2026, 2, 1),
            symbol="KLDX",
            cusip="K0000A105",
            quantity=Decimal("100"),
            price=Decimal("30.00"),
            amount=Decimal("3000.00"),
        ),
        # idx5 -- TRVK sold at a loss, to be replaced by two separate lots below (case 3).
        dict(
            action=TxnAction.SELL,
            trade_date=dt.date(2026, 2, 1),
            symbol="TRVK",
            cusip=None,
            quantity=Decimal("100"),
            price=Decimal("30.00"),
            amount=Decimal("3000.00"),
        ),
        # idx6 -- TRVK replacement lot 1 of 2: 60 of the 100 shares sold above.
        dict(
            action=TxnAction.BUY,
            trade_date=dt.date(2026, 2, 10),
            symbol="TRVK",
            cusip=None,
            quantity=Decimal("60"),
            price=Decimal("32.00"),
            amount=Decimal("-1920.00"),
        ),
        # idx7 -- TRVK replacement lot 2 of 2: the remaining 40 shares. Together with idx6 this fully
        # replaces the idx5 loss sale, spreading the disallowance across both lots.
        dict(
            action=TxnAction.BUY,
            trade_date=dt.date(2026, 2, 15),
            symbol="TRVK",
            cusip=None,
            quantity=Decimal("40"),
            price=Decimal("33.00"),
            amount=Decimal("-1320.00"),
        ),
        # idx8 -- MRDX sold at a loss; replaced inside the Roth IRA at idx_r0 below.
        dict(
            action=TxnAction.SELL,
            trade_date=dt.date(2026, 3, 1),
            symbol="MRDX",
            cusip=None,
            quantity=Decimal("30"),
            price=Decimal("25.00"),
            amount=Decimal("750.00"),
        ),
        # idx9 -- QRVA same-day round trip, buy leg (case 1). replay_order is correct (buy before
        # sell); source_row is swapped with idx10's below to reproduce a newest-first file, where the
        # sale -- the later event of the pair -- prints in the earlier row.
        dict(
            action=TxnAction.BUY,
            trade_date=dt.date(2026, 3, 2),
            symbol="QRVA",
            cusip=None,
            quantity=Decimal("50"),
            price=Decimal("20.00"),
            amount=Decimal("-1000.00"),
        ),
        # idx10 -- QRVA same-day round trip, sell leg. A gain, deliberately, so this case is not
        # entangled with the wash-sale machinery -- it isolates the ordering fix.
        dict(
            action=TxnAction.SELL,
            trade_date=dt.date(2026, 3, 2),
            symbol="QRVA",
            cusip=None,
            quantity=Decimal("50"),
            price=Decimal("25.00"),
            amount=Decimal("1250.00"),
        ),
        # idx11 -- FLNT sold, completing the fractional-share round trip (case 5).
        dict(
            action=TxnAction.SELL,
            trade_date=dt.date(2026, 3, 20),
            symbol="FLNT",
            cusip=None,
            quantity=Decimal("12.3457"),
            price=Decimal("95.77"),
            amount=Decimal("1182.347689"),
        ),
        # idx12 -- TRVK replacement lot 1 sold in full. Under the pre-fix `_sync_disposals`, this is
        # the one that *would* have been re-synced (it is `basis_added_to_lot_id`, the larger lot).
        dict(
            action=TxnAction.SELL,
            trade_date=dt.date(2026, 6, 1),
            symbol="TRVK",
            cusip=None,
            quantity=Decimal("60"),
            price=Decimal("40.00"),
            amount=Decimal("2400.00"),
        ),
        # idx13 -- TRVK replacement lot 2 sold in full. This is the one the pre-fix bug missed: its
        # basis was raised on the lot but never re-synced onto this disposal, so it reported a gain
        # instead of the true loss. See TestSyntheticLedgerFigures.test_multi_lot_disallowance_*.
        dict(
            action=TxnAction.SELL,
            trade_date=dt.date(2026, 6, 5),
            symbol="TRVK",
            cusip=None,
            quantity=Decimal("40"),
            price=Decimal("40.00"),
            amount=Decimal("1600.00"),
        ),
    ]

    transactions: list[Transaction] = []
    for idx, row in enumerate(rows):
        source_row = idx
        replay_order = idx
        if idx == 9:  # QRVA buy: file position swapped with the sell below.
            source_row = 10
        elif idx == 10:  # QRVA sell: file position swapped with the buy above.
            source_row = 9
        transactions.append(
            _txn(
                broker=broker,
                account_id=account_id,
                import_id=import_id,
                source_row=source_row,
                replay_order=replay_order,
                **row,
            )
        )
    return transactions


def _wb_margin_transactions() -> list[Transaction]:
    """The Webull-side replacement purchase that makes ``KLDX`` a cross-broker wash sale (case 2).
    Webull never supplies a CUSIP, so this is symbol-keyed until ``canonicalize_ledger`` merges it."""
    return [
        _txn(
            broker=Broker.WEBULL,
            account_id=WB_MARGIN.account_id,
            import_id="imp-wb-margin",
            action=TxnAction.BUY,
            trade_date=dt.date(2026, 2, 15),
            symbol="KLDX",
            cusip=None,
            quantity=Decimal("100"),
            price=Decimal("32.00"),
            amount=Decimal("-3200.00"),
            source_row=0,
            replay_order=0,
        )
    ]


def _rh_roth_transactions() -> list[Transaction]:
    """The Roth IRA replacement purchase that permanently disallows the MRDX loss (case 4, Rev. Rul.
    2008-5)."""
    return [
        _txn(
            broker=Broker.ROBINHOOD,
            account_id=RH_ROTH.account_id,
            import_id="imp-rh-roth",
            action=TxnAction.BUY,
            trade_date=dt.date(2026, 3, 10),
            symbol="MRDX",
            cusip=None,
            quantity=Decimal("30"),
            price=Decimal("26.00"),
            amount=Decimal("-780.00"),
            source_row=0,
            replay_order=0,
        )
    ]


def qrva_round_trip_in_file_order() -> tuple[Transaction, Transaction]:
    """The same-day ``QRVA`` buy/sell pair (case 1), in the source file's own row order rather than
    chronological order -- ``source_row`` ascending, which puts the sell (``source_row=9``) before the
    buy (``source_row=10``), exactly as a newest-first export prints the later of two same-day events
    first.

    Exists so a test can feed this pair straight to :func:`app.core.lots.build_lots` and reproduce the
    pre-fix phantom-open-lot bug directly, without going through SQLite -- the proof that asserting
    zero open lots against the *correctly*-ordered ledger is not a vacuous check. See
    ``TestSyntheticLedgerFigures`` in ``tests/test_canonical.py``.
    """
    buy, sell = (t for t in _rh_taxable_transactions() if t.symbol == "QRVA")
    ordered = sorted((buy, sell), key=lambda t: t.source_row)
    return ordered[0], ordered[1]


def _all_transactions() -> list[Transaction]:
    return [
        *_rh_taxable_transactions(),
        *_wb_margin_transactions(),
        *_rh_roth_transactions(),
    ]


def _instruments_for(transactions: Sequence[Transaction]) -> list[Instrument]:
    """One :class:`Instrument` per distinct ``instrument_id`` actually produced above -- exactly what
    an adapter would have discovered while parsing, before ``canonicalize_ledger`` ever runs. ``KLDX``
    therefore yields two rows (CUSIP-keyed from Robinhood, symbol-keyed from Webull), which is the
    split identity case 2 exists to exercise."""
    seen: dict[str, Instrument] = {}
    for txn in transactions:
        if txn.instrument_id is None or txn.instrument_id in seen:
            continue
        seen[txn.instrument_id] = Instrument(
            instrument_id=txn.instrument_id,
            primary_symbol=txn.symbol or "",
            cusip=txn.cusip,
            name=_NAMES.get(txn.symbol or ""),
        )
    return list(seen.values())


def _import_records(transactions: Sequence[Transaction]) -> list[ImportRecord]:
    """One synthetic import per account, satisfying ``txn.import_id``'s foreign key. Row counts are
    the real counts for that account -- there is no skipped-row gap to report, unlike a real export."""
    by_account: dict[str, list[Transaction]] = {}
    for txn in transactions:
        by_account.setdefault(txn.account_id, []).append(txn)

    imported_at = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    records: list[ImportRecord] = []
    for account_id, rows in by_account.items():
        account = ACCOUNTS[account_id]
        import_id = rows[0].import_id
        adapter = "webull" if account.broker is Broker.WEBULL else "robinhood"
        records.append(
            ImportRecord(
                import_id=import_id,
                source_path=f"synthetic://{import_id}",
                filename=f"{import_id}.csv",
                file_sha256=import_id,
                content_hash=import_id,
                broker=account.broker,
                account_id=account_id,
                adapter=adapter,
                adapter_version="synthetic-1",
                row_count=len(rows),
                usable_row_count=len(rows),
                imported_at=imported_at,
            )
        )
    return records


def build_synthetic_ledger(path: Path) -> None:
    """Write the frozen synthetic ledger to a fresh SQLite file at ``path``, through the real
    production write path -- never hand-crafted SQL.

    Safe to call against a path that does not exist yet; :func:`app.db.sqlite.connect` creates the
    parent directory and :func:`~app.db.sqlite.migrate` creates the schema.
    """
    transactions = _all_transactions()
    with ledger_store.connect(path) as conn:
        ledger_store.migrate(conn)
        for account in ACCOUNTS.values():
            ledger_store.upsert_account(conn, account)
        for instrument in _instruments_for(transactions):
            ledger_store.upsert_instrument(conn, instrument)
        for record in _import_records(transactions):
            ledger_store.record_import(conn, record)
        report = ledger_store.insert_transactions(conn, transactions)
        if not report.is_clean:  # pragma: no cover - defensive; this ledger is fixed and hand-checked
            raise AssertionError(f"synthetic ledger insert produced conflicts: {report.conflicts}")

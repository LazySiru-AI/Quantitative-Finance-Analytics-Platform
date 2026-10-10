"""Demo mode: an invented, clearly-illustrative portfolio seeded into an empty data directory.

**Everything here is made up for demonstration. It is not anyone's real portfolio.** The accounts,
share counts, prices and dates are invented; only the tickers are real, well-known public symbols so
that live market data renders on the pages that use it. Nothing here is a recommendation.

:func:`ensure_seeded` builds the ledger through the same production write path the synthetic test
fixture uses (:func:`app.db.sqlite.migrate`, ``upsert_account``, ``upsert_instrument``,
``record_import``, ``insert_transactions``), then writes the account manifest and sector labels
beside it. It is idempotent and cheap after the first call, and it never overwrites an existing
ledger or document. Fully deterministic: fixed dates, no randomness, no clock reads.

Scenarios the data exercises
----------------------------
* ``demo-taxable``: deposits, dividends, short- and long-term realized gains, and a **wash sale** --
  AMD is sold at a loss on 2025-02-10 and repurchased on 2025-02-24, so the loss is deferred into the
  replacement lot, which stays open.
* ``demo-roth``: buys XOM on 2026-03-20, ten days after ``demo-taxable`` sold XOM at a loss, so that
  loss is permanently disallowed (Rev. Rul. 2008-5).
* ``demo-margin``: a long-term gain (TSLA), a short-term loss (GOOGL) and open positions.
"""

from __future__ import annotations

import datetime as dt
import os
import threading
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from app.config import Settings
from app.core.ids import instrument_id as compute_instrument_id
from app.core.ids import transaction_id as compute_transaction_id
from app.core.models import (
    Account,
    AccountType,
    Broker,
    ImportRecord,
    Instrument,
    InstrumentKind,
    TaxTreatment,
    Transaction,
    TxnAction,
)
from app.datasource import DocumentKey, local_document_path, write_document
from app.db import sqlite as ledger_store

__all__ = ["ACCOUNTS", "DEMO_MANIFEST", "DEMO_SECTORS", "build_demo_ledger", "ensure_seeded"]

_lock = threading.Lock()

DEMO_TAXABLE = Account(
    account_id="demo-taxable",
    broker=Broker.ROBINHOOD,
    label="Demo Brokerage",
    tax_treatment=TaxTreatment.TAXABLE,
    account_type=AccountType.CASH,
)
DEMO_MARGIN = Account(
    account_id="demo-margin",
    broker=Broker.SOFI,
    label="Demo Margin",
    tax_treatment=TaxTreatment.TAXABLE,
    account_type=AccountType.MARGIN,
)
DEMO_ROTH = Account(
    account_id="demo-roth",
    broker=Broker.SOFI,
    label="Demo Roth IRA",
    tax_treatment=TaxTreatment.ROTH_IRA,
    account_type=AccountType.RETIREMENT,
)
ACCOUNTS = {a.account_id: a for a in (DEMO_TAXABLE, DEMO_MARGIN, DEMO_ROTH)}

#: Symbol -> (display name, kind, sector). Sector labels use only the frozen vocabulary.
_SECURITIES: dict[str, tuple[str, InstrumentKind, str]] = {
    "AAPL": ("Apple Inc.", InstrumentKind.EQUITY, "BIG TECH"),
    "MSFT": ("Microsoft Corp.", InstrumentKind.EQUITY, "BIG TECH"),
    "AMZN": ("Amazon.com Inc.", InstrumentKind.EQUITY, "BIG TECH"),
    "GOOGL": ("Alphabet Inc. Class A", InstrumentKind.EQUITY, "BIG TECH"),
    "META": ("Meta Platforms Inc.", InstrumentKind.EQUITY, "BIG TECH"),
    "NVDA": ("NVIDIA Corp.", InstrumentKind.EQUITY, "SEMI"),
    "AMD": ("Advanced Micro Devices", InstrumentKind.EQUITY, "SEMI"),
    "TSLA": ("Tesla Inc.", InstrumentKind.EQUITY, "AUTO/EV"),
    "JPM": ("JPMorgan Chase & Co.", InstrumentKind.EQUITY, "FINANCIALS"),
    "XOM": ("Exxon Mobil Corp.", InstrumentKind.EQUITY, "ENERGY"),
    "SPY": ("SPDR S&P 500 ETF Trust", InstrumentKind.ETF, "BROAD MARKET"),
    "QQQ": ("Invesco QQQ Trust", InstrumentKind.ETF, "BROAD MARKET"),
    "VTI": ("Vanguard Total Stock Market ETF", InstrumentKind.ETF, "BROAD MARKET"),
    "SCHD": ("Schwab US Dividend Equity ETF", InstrumentKind.ETF, "BROAD MARKET"),
}

_B, _S, _D, _C = TxnAction.BUY, TxnAction.SELL, TxnAction.DIVIDEND, TxnAction.CASH_IN
# (date, action, symbol, quantity, price). CASH_IN rows carry ("1", amount); DIVIDEND rows carry
# (shares held, per-share dividend).
_Row = tuple[dt.date, TxnAction, str | None, str, str]


def _d(y: int, m: int, d: int) -> dt.date:
    return dt.date(y, m, d)


_TAXABLE_ROWS: list[_Row] = [
    (_d(2024, 1, 8), _C, None, "1", "40000"),
    (_d(2024, 1, 12), _B, "AAPL", "40", "185.00"),
    (_d(2024, 1, 12), _B, "MSFT", "15", "400.00"),
    (_d(2024, 2, 5), _B, "JPM", "30", "180.00"),
    (_d(2024, 3, 4), _B, "AMD", "30", "195.00"),
    (_d(2024, 5, 16), _D, "AAPL", "40", "0.25"),
    (_d(2024, 6, 13), _D, "MSFT", "15", "0.75"),
    (_d(2024, 8, 7), _B, "NVDA", "40", "100.00"),
    (_d(2024, 9, 10), _B, "SPY", "10", "550.00"),
    (_d(2024, 10, 1), _C, None, "1", "10000"),
    (_d(2024, 11, 12), _S, "AAPL", "20", "224.00"),  # short-term gain
    (_d(2025, 2, 10), _S, "AMD", "30", "115.00"),  # loss ...
    (_d(2025, 2, 24), _B, "AMD", "30", "112.00"),  # ... repurchased within 30 days: wash sale
    (_d(2025, 4, 2), _S, "JPM", "30", "255.00"),  # long-term gain
    (_d(2025, 5, 15), _D, "AAPL", "20", "0.25"),
    (_d(2025, 6, 2), _B, "XOM", "40", "105.00"),
    (_d(2025, 6, 27), _D, "SPY", "10", "1.75"),
    (_d(2025, 8, 14), _B, "META", "8", "700.00"),
    (_d(2025, 9, 18), _B, "SCHD", "150", "27.00"),
    (_d(2026, 1, 15), _C, None, "1", "8000"),
    (_d(2026, 2, 10), _S, "NVDA", "20", "185.00"),  # long-term gain
    (_d(2026, 3, 10), _S, "XOM", "40", "98.00"),  # loss, replaced in the Roth on 2026-03-20
    (_d(2026, 5, 12), _B, "QQQ", "12", "520.00"),
    (_d(2026, 7, 1), _D, "SCHD", "150", "0.65"),
    (_d(2024, 7, 31), _D, "JPM", "30", "1.15"),
    (_d(2024, 8, 15), _D, "AAPL", "40", "0.25"),
    (_d(2024, 9, 12), _D, "MSFT", "15", "0.75"),
    (_d(2024, 10, 31), _D, "JPM", "30", "1.25"),
    (_d(2024, 11, 14), _D, "AAPL", "20", "0.25"),
    (_d(2024, 12, 12), _D, "MSFT", "15", "0.83"),
    (_d(2024, 12, 20), _D, "SPY", "10", "1.80"),
    (_d(2025, 3, 13), _D, "MSFT", "15", "0.83"),
    (_d(2025, 3, 21), _D, "SPY", "10", "1.75"),
    (_d(2025, 9, 19), _D, "SPY", "10", "1.80"),
    (_d(2025, 12, 12), _D, "MSFT", "15", "0.91"),
    (_d(2025, 12, 19), _D, "SPY", "10", "1.85"),
    (_d(2026, 3, 26), _D, "SCHD", "150", "0.70"),
]

_MARGIN_ROWS: list[_Row] = [
    (_d(2024, 4, 2), _C, None, "1", "25000"),
    (_d(2024, 4, 22), _B, "TSLA", "40", "170.00"),
    (_d(2024, 5, 1), _B, "AMZN", "50", "180.00"),
    (_d(2024, 5, 20), _B, "GOOGL", "30", "165.00"),
    (_d(2025, 2, 18), _C, None, "1", "5000"),
    (_d(2025, 3, 3), _B, "META", "10", "590.00"),
    (_d(2025, 4, 10), _S, "GOOGL", "30", "150.00"),  # short-term loss
    (_d(2025, 5, 6), _S, "TSLA", "40", "280.00"),  # long-term gain
    (_d(2025, 11, 4), _B, "NVDA", "25", "195.00"),
    (_d(2025, 6, 26), _D, "META", "10", "0.53"),
    (_d(2025, 9, 25), _D, "META", "10", "0.53"),
    (_d(2025, 12, 23), _D, "META", "10", "0.53"),
    (_d(2026, 3, 26), _D, "META", "10", "0.55"),
]

_ROTH_ROWS: list[_Row] = [
    (_d(2024, 1, 10), _C, None, "1", "7000"),
    (_d(2024, 1, 16), _B, "VTI", "20", "240.00"),
    (_d(2024, 6, 28), _D, "VTI", "20", "0.85"),
    (_d(2025, 1, 6), _C, None, "1", "7000"),
    (_d(2025, 1, 14), _B, "QQQ", "8", "520.00"),
    (_d(2025, 1, 14), _B, "SCHD", "100", "27.00"),
    (_d(2026, 1, 5), _C, None, "1", "7000"),
    (_d(2026, 3, 20), _B, "XOM", "40", "97.00"),  # permanently disallows the taxable XOM loss
    (_d(2024, 9, 27), _D, "VTI", "20", "0.82"),
    (_d(2024, 12, 27), _D, "VTI", "20", "0.95"),
    (_d(2025, 3, 28), _D, "VTI", "20", "0.80"),
    (_d(2025, 3, 26), _D, "SCHD", "100", "0.65"),
    (_d(2025, 6, 25), _D, "SCHD", "100", "0.65"),
    (_d(2025, 9, 24), _D, "SCHD", "100", "0.68"),
]


def _transactions(account: Account, rows: Sequence[_Row]) -> list[Transaction]:
    import_id = f"imp-{account.account_id}"
    out: list[Transaction] = []
    for idx, (date, action, symbol, qty_text, price_text) in enumerate(sorted(rows, key=lambda r: r[0])):
        quantity, price = Decimal(qty_text), Decimal(price_text)
        gross = quantity * price
        amount = -gross if action is TxnAction.BUY else gross
        is_cash = action is TxnAction.CASH_IN
        is_trade = action.is_trade
        qty_out, price_out = (quantity, price) if is_trade else (None, None)
        txn_id = compute_transaction_id(
            broker=account.broker.value,
            account_id=account.account_id,
            trade_date=date,
            action=action.value,
            symbol=None if is_cash else symbol,
            quantity=qty_out,
            price=price_out,
            amount=amount,
            sequence=0,
        )
        out.append(
            Transaction(
                txn_id=txn_id,
                import_id=import_id,
                source_row=idx,
                replay_order=idx,
                account_id=account.account_id,
                broker=account.broker,
                action=action,
                trade_date=date,
                sequence=0,
                symbol=None if is_cash else symbol,
                cusip=None,
                instrument_id=None if symbol is None else compute_instrument_id(cusip=None, symbol=symbol),
                quantity=qty_out,
                price=price_out,
                amount=amount,
            )
        )
    return out


def _all_transactions() -> list[Transaction]:
    return [
        *_transactions(DEMO_TAXABLE, _TAXABLE_ROWS),
        *_transactions(DEMO_MARGIN, _MARGIN_ROWS),
        *_transactions(DEMO_ROTH, _ROTH_ROWS),
    ]


def _instruments(transactions: Sequence[Transaction]) -> list[Instrument]:
    seen: dict[str, Instrument] = {}
    for txn in transactions:
        if txn.instrument_id is None or txn.instrument_id in seen:
            continue
        symbol = txn.symbol or ""
        name, kind, _sector = _SECURITIES[symbol]
        seen[txn.instrument_id] = Instrument(
            instrument_id=txn.instrument_id, primary_symbol=symbol, cusip=None, name=name, kind=kind
        )
    return list(seen.values())


def _imports(transactions: Sequence[Transaction]) -> list[ImportRecord]:
    imported_at = dt.datetime(2026, 9, 1, tzinfo=dt.UTC)
    records: list[ImportRecord] = []
    for account in ACCOUNTS.values():
        count = sum(1 for t in transactions if t.account_id == account.account_id)
        import_id = f"imp-{account.account_id}"
        records.append(
            ImportRecord(
                import_id=import_id,
                source_path=f"demo://{account.account_id}",
                filename=f"{account.account_id}.csv",
                file_sha256=import_id,
                content_hash=import_id,
                broker=account.broker,
                account_id=account.account_id,
                adapter="demo",
                adapter_version="demo-1",
                row_count=count,
                usable_row_count=count,
                imported_at=imported_at,
            )
        )
    return records


def build_demo_ledger(path: Path) -> None:
    """Write the demo ledger to a fresh SQLite file at ``path`` through the real write path."""
    transactions = _all_transactions()
    with ledger_store.connect(path) as conn:
        ledger_store.migrate(conn)
        for account in ACCOUNTS.values():
            ledger_store.upsert_account(conn, account)
        for instrument in _instruments(transactions):
            ledger_store.upsert_instrument(conn, instrument)
        for record in _imports(transactions):
            ledger_store.record_import(conn, record)
        report = ledger_store.insert_transactions(conn, transactions)
        if not report.is_clean:  # pragma: no cover - the data above is fixed
            raise AssertionError(f"demo ledger insert produced conflicts: {report.conflicts}")


def _manifest_text() -> str:
    lines = ["# DEMO DATA -- invented for demonstration; not anyone's real accounts.", ""]
    for account in ACCOUNTS.values():
        lines += [
            "[[account]]",
            f'file = "{account.account_id}.csv"',
            f'account_id = "{account.account_id}"',
            f'label = "{account.label}"',
            f'tax_treatment = "{account.tax_treatment.value}"',
            f'account_type = "{account.account_type.value}"',
            f'broker = "{account.broker.value}"',
            "",
        ]
    return "\n".join(lines)


def _sectors_text() -> str:
    lines = ["# DEMO DATA -- sector labels for the invented demo portfolio.", "", "[sectors]"]
    lines += [f'{symbol} = "{sector}"' for symbol, (_n, _k, sector) in sorted(_SECURITIES.items())]
    return "\n".join(lines) + "\n"


DEMO_MANIFEST = _manifest_text()
DEMO_SECTORS = _sectors_text()

_DOCUMENTS: dict[DocumentKey, str] = {"accounts-manifest": DEMO_MANIFEST, "sectors": DEMO_SECTORS}


def ensure_seeded(settings: Settings) -> None:
    """Seed the demo ledger and documents if absent. Idempotent; never overwrites anything."""
    ledger = settings.store_dir / "ledger.sqlite"
    missing_docs = [k for k in _DOCUMENTS if not local_document_path(k, settings).exists()]
    if ledger.exists() and not missing_docs:
        return
    with _lock:
        if not ledger.exists():
            staging = ledger.with_name(f".{ledger.name}.demo-{os.getpid()}.tmp")
            ledger.parent.mkdir(parents=True, exist_ok=True)
            for suffix in ("", "-wal", "-shm"):
                Path(f"{staging}{suffix}").unlink(missing_ok=True)
            try:
                build_demo_ledger(staging)
                os.replace(staging, ledger)
            finally:
                for suffix in ("", "-wal", "-shm"):
                    Path(f"{staging}{suffix}").unlink(missing_ok=True)
        for key, content in _DOCUMENTS.items():
            if not local_document_path(key, settings).exists():
                write_document(key, content, settings)

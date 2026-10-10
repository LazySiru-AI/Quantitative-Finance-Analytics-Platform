"""Demo mode: the invented portfolio seeds once, through the real engines, with no data-quality warnings."""

from __future__ import annotations

import datetime as dt
import tomllib
from decimal import Decimal
from pathlib import Path
from typing import Any

from app import datasource
from app.config import Settings
from app.core.canonical import canonicalize_ledger
from app.core.cash import CashVerdict, build_cash
from app.core.holdings import build_positions
from app.core.lots import build_lots
from app.core.models import AccountType, TaxTreatment, TxnAction
from app.datasource import demo
from app.db import sqlite as ledger_store
from app.ingest.manifest import load_manifest
from app.market.sectors import SECTOR_VOCABULARY, load_sector_map
from app.tax.engine import report_from_ledger
from app.tax.washsale import apply_wash_sales

AS_OF = dt.date(2026, 9, 30)


def _demo_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"data_source": "demo"})


def _load(path: Path) -> tuple[dict[str, Any], dict[str, Any], list[Any]]:
    with ledger_store.connect(path, read_only=True) as conn:
        accounts = {a.account_id: a for a in ledger_store.fetch_accounts(conn)}
        instruments = {i.instrument_id: i for i in ledger_store.fetch_instruments(conn)}
        txns = [ledger_store.transaction_from_row(r) for r in ledger_store.fetch_transactions(conn)]
    return accounts, instruments, txns


def test_seeds_ledger_and_documents(settings: Settings) -> None:
    cfg = _demo_settings(settings)
    assert not (cfg.store_dir / "ledger.sqlite").exists()
    demo.ensure_seeded(cfg)
    assert (cfg.store_dir / "ledger.sqlite").exists()
    assert datasource.local_document_path("accounts-manifest", cfg).exists()
    assert datasource.local_document_path("sectors", cfg).exists()
    assert not datasource.local_document_path("planner-board", cfg).exists()
    assert not list(cfg.store_dir.glob(".ledger.sqlite*"))  # staging files cleaned up


def test_ensure_seeded_is_idempotent_and_never_overwrites(settings: Settings) -> None:
    cfg = _demo_settings(settings)
    demo.ensure_seeded(cfg)
    ledger = cfg.store_dir / "ledger.sqlite"
    manifest = datasource.local_document_path("accounts-manifest", cfg)
    ledger_mtime = ledger.stat().st_mtime_ns

    manifest.write_text("# edited by the user\n" + manifest.read_text(encoding="utf-8"), encoding="utf-8")
    edited = manifest.read_text(encoding="utf-8")
    sectors = datasource.local_document_path("sectors", cfg)
    sectors.unlink()  # only the absent document is rewritten

    demo.ensure_seeded(cfg)
    assert ledger.stat().st_mtime_ns == ledger_mtime
    assert manifest.read_text(encoding="utf-8") == edited
    assert sectors.read_text(encoding="utf-8") == demo.DEMO_SECTORS


def test_seeding_is_deterministic(tmp_path: Path) -> None:
    a, b = tmp_path / "a.sqlite", tmp_path / "b.sqlite"
    demo.build_demo_ledger(a)
    demo.build_demo_ledger(b)
    assert [t.txn_id for t in _load(a)[2]] == [t.txn_id for t in _load(b)[2]]


def test_ledger_db_path_in_demo_mode_returns_a_seeded_ledger(settings: Settings) -> None:
    cfg = _demo_settings(settings)
    path = datasource.ledger_db_path(cfg)
    assert path == cfg.store_dir / "ledger.sqlite"
    assert path.exists()
    assert len(_load(path)[2]) >= 50
    assert datasource.read_document("sectors", cfg) == demo.DEMO_SECTORS


def test_ledger_writer_in_demo_mode_seeds_first(settings: Settings) -> None:
    cfg = _demo_settings(settings)
    with datasource.ledger_writer(cfg) as path:
        assert path.exists()


def test_local_mode_never_seeds(settings: Settings) -> None:
    assert settings.data_source == "local"
    path = datasource.ledger_db_path(settings)
    assert not path.exists()
    assert datasource.read_document("accounts-manifest", settings) is None


def test_manifest_parses_with_the_real_loader(settings: Settings) -> None:
    cfg = _demo_settings(settings)
    demo.ensure_seeded(cfg)
    manifest = load_manifest(datasource.local_document_path("accounts-manifest", cfg))
    by_id = {e.account.account_id: e.account for e in manifest.entries}
    assert set(by_id) == {"demo-taxable", "demo-margin", "demo-roth"}
    assert by_id["demo-taxable"].label == "Demo Brokerage"
    assert by_id["demo-margin"].account_type is AccountType.MARGIN
    assert by_id["demo-roth"].tax_treatment is TaxTreatment.ROTH_IRA


def test_sectors_use_only_the_frozen_vocabulary(settings: Settings) -> None:
    cfg = _demo_settings(settings)
    demo.ensure_seeded(cfg)
    text = datasource.local_document_path("sectors", cfg).read_text(encoding="utf-8")
    labels = tomllib.loads(text)["sectors"]
    assert set(labels.values()) <= set(SECTOR_VOCABULARY)
    traded = {t.symbol for t in _load(cfg.store_dir / "ledger.sqlite")[2] if t.symbol}
    assert traded <= set(labels)
    assert load_sector_map(settings=cfg)["AMD"] == "SEMI"


def test_ledger_shape(tmp_path: Path) -> None:
    path = tmp_path / "demo.sqlite"
    demo.build_demo_ledger(path)
    accounts, _instruments, txns = _load(path)
    assert set(accounts) == {"demo-taxable", "demo-margin", "demo-roth"}
    assert 50 <= len(txns) <= 90
    assert min(t.trade_date for t in txns) >= dt.date(2024, 1, 1)
    assert max(t.trade_date for t in txns) <= dt.date(2026, 9, 30)
    actions = {t.action for t in txns}
    assert {TxnAction.CASH_IN, TxnAction.DIVIDEND, TxnAction.BUY, TxnAction.SELL} <= actions
    assert {t.symbol for t in txns if t.symbol} >= {"AAPL", "MSFT", "NVDA", "SPY", "QQQ", "VTI", "SCHD"}


def test_cash_never_goes_negative_in_replay_order(tmp_path: Path) -> None:
    path = tmp_path / "demo.sqlite"
    demo.build_demo_ledger(path)
    txns = _load(path)[2]
    balances: dict[str, Decimal] = {}
    for txn in sorted(txns, key=lambda t: (t.account_id, t.trade_date, t.replay_order)):
        balances[txn.account_id] = balances.get(txn.account_id, Decimal(0)) + (txn.amount or Decimal(0))
        assert balances[txn.account_id] >= 0, (txn.account_id, txn.trade_date, txn.symbol)


def test_cash_engine_derives_every_account(tmp_path: Path) -> None:
    path = tmp_path / "demo.sqlite"
    demo.build_demo_ledger(path)
    accounts, _instruments, txns = _load(path)
    cash = build_cash(txns, accounts=accounts, as_of=AS_OF)
    assert {c.account_id for c in cash.accounts} == set(accounts)
    for entry in cash.accounts:
        assert entry.verdict is CashVerdict.DERIVED, entry
        assert entry.balance is not None and entry.balance >= 0


def test_tax_engine_finds_gains_a_wash_sale_and_no_warnings(tmp_path: Path) -> None:
    path = tmp_path / "demo.sqlite"
    demo.build_demo_ledger(path)
    with ledger_store.connect(path, read_only=True) as conn:
        r2024 = report_from_ledger(conn, tax_year=2024, as_of=AS_OF)
        r2025 = report_from_ledger(conn, tax_year=2025, as_of=AS_OF)
        r2026 = report_from_ledger(conn, tax_year=2026, as_of=AS_OF)
    for report in (r2024, r2025, r2026):
        assert report.warnings == ()  # no oversold / negative-cash / basis gaps
    assert r2024.gains.short_term_gain > 0
    assert r2025.gains.long_term_gain > 0 and r2025.gains.short_term_gain < 0
    assert r2026.gains.long_term_gain > 0

    # Taxable wash sale: AMD loss on 2025-02-10 repurchased on 2025-02-24 (deferred into the new lot).
    assert [e.symbol for e in r2025.wash_sales] == ["AMD"]
    assert r2025.gains.disallowed_loss_total == Decimal("2400.00")
    assert r2025.gains.permanently_disallowed_total == 0

    # Roth replacement: the 2026-03 XOM loss is permanently disallowed, not deferred.
    assert [e.symbol for e in r2026.wash_sales] == ["XOM"]
    assert r2026.gains.permanently_disallowed_total == Decimal("280.00")


def test_portfolio_has_open_positions_including_the_wash_sale_lot(tmp_path: Path) -> None:
    path = tmp_path / "demo.sqlite"
    demo.build_demo_ledger(path)
    accounts, instruments, txns = _load(path)
    txns, instruments = canonicalize_ledger(txns, instruments)
    ledger = build_lots(txns, accounts=accounts, instruments=instruments)
    apply_wash_sales(ledger, accounts=accounts)
    assert ledger.warnings == []
    holdings = {h.symbol: h for h in build_positions(ledger, accounts=accounts, as_of=AS_OF)}
    assert len(holdings) >= 10
    assert holdings["AMD"].wash_sale_adjustment == Decimal("2400.00")
    assert holdings["QQQ"].quantity == Decimal("20")  # taxable 12 + roth 8
    held_in = {a.account_id for h in holdings.values() for a in h.accounts}
    assert held_in == {"demo-taxable", "demo-margin", "demo-roth"}

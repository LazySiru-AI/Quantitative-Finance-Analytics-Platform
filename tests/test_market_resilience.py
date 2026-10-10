"""Tests for four silent-failure / resource-growth defects fixed together across the backend's
long-running machinery:

(a)/(b) `app.market.social_history`'s scheduler now tracks per-tick counters and trips a
consecutive-all-failed-ticks breaker (mirroring `app.evolution.loop._MAX_CONSECUTIVE_FAILURES`),
surfaced over `GET /api/market/social/status` (mirroring `GET /api/market/refresh/status`).

(c) `app.market.live.PollingQuoteSource` now drops a watched symbol nobody has asked about within
`watch_idle_seconds`, while a symbol still being actively (re-)requested is retained -- see that
class's own "watch set tracks current client interest, not history" docstring section.

(d) `app.db.sqlite.fetch_transactions`/`fetch_accounts` now degrade gracefully -- log a `WARNING`
naming the row and the unrecognised value, and exclude the row -- instead of letting
`Broker(...)`/`TxnAction(...)` raise `ValueError` out of row hydration and 500 every endpoint that
reads the ledger.

Every test here is offline and deterministic: no network, no real subprocess, no real daemon thread
left running past its own test (`PollingQuoteSource.close()` is always called), and the social
scheduler's module-level status singleton is reset before and after each test in this file so these
tests cannot see state left behind by `tests/test_social_history.py` (or vice versa) regardless of
run order.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from typing import Any

import pytest
from conftest import make_txn, sample_account
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.models import Broker, TaxTreatment, TxnAction
from app.db import sqlite as ledger
from app.market import live
from app.market import social_history as sh
from app.market.models import BarSource, Quote
from app.market.news_models import SocialSnapshot
from app.market.providers.base import ProviderUnavailable
from app.market.registry import ProviderRegistry

# ---------------------------------------------------------------------------
# (a) + (b) -- social snapshot scheduler breaker + status endpoint
# ---------------------------------------------------------------------------


def _snapshot(*, symbol: str, as_of: dt.datetime) -> SocialSnapshot:
    return SocialSnapshot(
        symbol=symbol, source="stocktwits", as_of=as_of, bullish=3, bearish=3, neutral=14
    )


class _FakeSocialProvider:
    """One snapshot per symbol, or a raised `ProviderUnavailable` for symbols named in `fails` --
    enough to drive `run_scheduler_pass` deterministically, no network involved."""

    def __init__(self, *, as_of: dt.datetime, fails: frozenset[str] = frozenset()) -> None:
        self.as_of = as_of
        self.fails = fails

    def fetch_social(self, symbol: str, *, limit: int = 30) -> SocialSnapshot:
        if symbol in self.fails:
            raise ProviderUnavailable(f"{symbol} is down", provider="fake")
        return _snapshot(symbol=symbol, as_of=self.as_of)


@pytest.fixture(autouse=True)
def _reset_social_scheduler_status() -> Any:
    """`app.market.social_history._status` is one module-level singleton shared with
    `tests/test_social_history.py`'s own `TestSchedulerPass`, which calls `run_scheduler_pass`
    directly too. Resetting before *and* after every test in this file is what keeps these tests
    correct regardless of which order pytest happens to run the two files in."""
    sh._status = sh.SocialSchedulerStatus()
    yield
    sh._status = sh.SocialSchedulerStatus()


class TestSocialSchedulerBreaker:
    def test_unhealthy_after_max_consecutive_all_failed_ticks_and_healthy_again_after_success(
        self, tmp_path
    ) -> None:
        cfg = Settings(store_dir=tmp_path / "store")
        failing_registry = ProviderRegistry(
            social_providers=(_FakeSocialProvider(as_of=_now(), fails=frozenset({"AAPL"})),)
        )

        assert sh.status()["healthy"] is True  # nothing has ticked yet -- not unhealthy by default

        for _ in range(sh._MAX_CONSECUTIVE_ALL_FAILED_TICKS):
            written, failed = sh.run_scheduler_pass(
                cfg, failing_registry, ("AAPL",), delay_seconds=0.0
            )
            assert (written, failed) == (0, 1)

        status = sh.status()
        assert status["healthy"] is False
        assert status["consecutive_all_failed_ticks"] == sh._MAX_CONSECUTIVE_ALL_FAILED_TICKS
        assert status["last_failed"] == 1

        # One tick that writes at least one symbol resets the breaker -- see `_record_tick`.
        ok_registry = ProviderRegistry(social_providers=(_FakeSocialProvider(as_of=_now()),))
        written, failed = sh.run_scheduler_pass(cfg, ok_registry, ("AAPL",), delay_seconds=0.0)
        assert (written, failed) == (1, 0)

        status = sh.status()
        assert status["healthy"] is True
        assert status["consecutive_all_failed_ticks"] == 0

    def test_no_provider_configured_neither_trips_nor_resets_the_breaker(self, tmp_path) -> None:
        """A tick with no social provider is a configuration state, not a failure -- it must not
        march the streak toward the breaker (a deliberately-unconfigured scheduler must not become
        "unhealthy" just by existing), matching `_record_tick`'s own `no_provider` handling."""
        cfg = Settings(store_dir=tmp_path / "store")
        empty_registry = ProviderRegistry()  # no social providers registered at all

        written, failed = sh.run_scheduler_pass(cfg, empty_registry, ("AAPL",), delay_seconds=0.0)

        assert (written, failed) == (0, 0)
        status = sh.status()
        assert status["healthy"] is True
        assert status["consecutive_all_failed_ticks"] == 0
        assert status["total_ticks"] == 1


def _now() -> dt.datetime:
    return dt.datetime(2026, 8, 1, 12, 0, tzinfo=dt.UTC)


class TestSocialStatusEndpoint:
    def test_endpoint_returns_the_counters_from_the_last_tick(self, settings: Settings) -> None:
        from app.main import app  # imported lazily so module import order never matters here

        registry = ProviderRegistry(social_providers=(_FakeSocialProvider(as_of=_now()),))
        sh.run_scheduler_pass(settings, registry, ("AAPL", "MSFT"), delay_seconds=0.0)

        client = TestClient(app)  # no lifespan: this app is never entered as a context manager
        response = client.get("/api/market/social/status")

        assert response.status_code == 200
        body = response.json()
        assert body["healthy"] is True
        assert body["total_ticks"] == 1
        assert body["last_written"] == 2
        assert body["last_failed"] == 0
        assert body["consecutive_all_failed_ticks"] == 0
        assert body["max_consecutive_all_failed_ticks"] == sh._MAX_CONSECUTIVE_ALL_FAILED_TICKS
        assert body["last_error"] is None
        assert body["last_tick_at"] is not None

    def test_endpoint_answers_even_when_the_scheduler_has_never_ticked(
        self, settings: Settings
    ) -> None:
        from app.main import app

        client = TestClient(app)
        body = client.get("/api/market/social/status").json()

        assert body["healthy"] is True
        assert body["total_ticks"] == 0
        assert body["last_tick_at"] is None


# ---------------------------------------------------------------------------
# (c) -- PollingQuoteSource's watch set stops only ever growing
# ---------------------------------------------------------------------------


class _FakeClock:
    """A settable, thread-safe stand-in for `time.monotonic` -- lets the idle-window comparison in
    `PollingQuoteSource` be driven deterministically, with no real sleeping, while the background
    poll thread itself still runs on real (tiny) intervals."""

    def __init__(self, start: float = 1_000.0) -> None:
        self._value = start
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            return self._value

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._value += seconds


class _FakeQuoteRegistry:
    def __init__(self, quotes: dict[str, Quote]) -> None:
        self.quotes = quotes

    def get_quote(self, symbol: str) -> Quote:
        return self.quotes[symbol]


def _quote(symbol: str, price: float) -> Quote:
    return Quote(
        symbol=symbol,
        price=price,
        ts=dt.datetime.now(dt.UTC),
        market_state="REGULAR",
        source=BarSource.YAHOO,
    )


def _watched_symbols(source: live.PollingQuoteSource) -> set[str]:
    with source._lock:  # test-only peek; the class has no public accessor for the watch set itself
        return set(source._watched)


class TestPollingQuoteSourceIdleEviction:
    def test_idle_symbol_is_dropped_while_an_actively_requested_one_is_retained(self) -> None:
        registry = _FakeQuoteRegistry({"KEEP": _quote("KEEP", 1.0), "IDLE": _quote("IDLE", 2.0)})
        clock = _FakeClock()
        source = live.PollingQuoteSource(
            registry_factory=lambda: registry,
            fast_interval=0.02,
            idle_interval=0.02,
            watch_idle_seconds=5.0,
            clock=clock,
        )
        try:
            source.subscribe(["KEEP", "IDLE"])
            assert _watched_symbols(source) == {"KEEP", "IDLE"}

            # Jump the fake clock well past the idle window, then re-request only KEEP -- exactly
            # the shape `GET /api/paperlive/stream` produces for a symbol a browser tab is still
            # watching (see `app.api.paperlive._event_stream`, which calls `source.snapshot` -- and
            # so `subscribe` -- on every refresh tick).
            clock.advance(10.0)
            source.subscribe(["KEEP"])

            deadline = time.monotonic() + 2.0
            while "IDLE" in _watched_symbols(source) and time.monotonic() < deadline:
                time.sleep(0.02)

            assert "IDLE" not in _watched_symbols(source)
            assert "KEEP" in _watched_symbols(source)
        finally:
            source.close()

    def test_a_dropped_symbol_can_be_freshly_resubscribed_later(self) -> None:
        """Eviction is not permanent -- the class docstring is explicit a dropped symbol is treated
        exactly like a brand-new one on its next `subscribe`/`snapshot` call."""
        registry = _FakeQuoteRegistry({"SYM": _quote("SYM", 5.0)})
        clock = _FakeClock()
        source = live.PollingQuoteSource(
            registry_factory=lambda: registry,
            fast_interval=0.02,
            idle_interval=0.02,
            watch_idle_seconds=1.0,
            clock=clock,
        )
        try:
            source.subscribe(["SYM"])
            clock.advance(5.0)

            deadline = time.monotonic() + 2.0
            while "SYM" in _watched_symbols(source) and time.monotonic() < deadline:
                time.sleep(0.02)
            assert "SYM" not in _watched_symbols(source)

            snapshot = source.snapshot(["SYM"])
            assert {q.symbol for q in snapshot.quotes} == {"SYM"}
            assert "SYM" in _watched_symbols(source)
        finally:
            source.close()


# ---------------------------------------------------------------------------
# (d) -- unknown broker/action tokens degrade gracefully instead of raising
# ---------------------------------------------------------------------------


def _record_import(conn, import_id: str = "imp1") -> None:
    """Satisfy `txn.import_id`'s provenance foreign key -- copied from `tests/test_tax_engine.py`'s
    own helper of the same name and purpose, since every transaction must trace back to a file."""
    conn.execute(
        "INSERT OR IGNORE INTO raw_import (import_id, source_path, filename, file_sha256, "
        "content_hash, broker, account_id, adapter, adapter_version, row_count, "
        "usable_row_count, imported_at) VALUES (?, 'p', 'f.csv', 'sha', 'content', "
        "'robinhood', 'rh-taxable', 'robinhood', '1', 4, 4, '2026-01-01T00:00:00Z')",
        (import_id,),
    )


class TestUnknownEnumTokensDegradeGracefully:
    def test_unknown_broker_on_a_txn_row_is_excluded_with_a_warning(self, conn, caplog) -> None:
        caplog.set_level(logging.WARNING, logger="app.db.sqlite")
        _record_import(conn)
        good = make_txn(txn_id="good-broker-1", action=TxnAction.BUY, source_row=0)
        bad = make_txn(txn_id="bad-broker-1", action=TxnAction.BUY, source_row=1)
        ledger.insert_transactions(conn, [good, bad])
        conn.execute("UPDATE txn SET broker = ? WHERE txn_id = ?", ("robinhood_v2", "bad-broker-1"))

        rows = ledger.fetch_transactions(conn)  # must not raise ValueError

        ids = {row["txn_id"] for row in rows}
        assert ids == {"good-broker-1"}
        assert any(
            record.levelno >= logging.WARNING
            and "bad-broker-1" in record.getMessage()
            and "robinhood_v2" in record.getMessage()
            for record in caplog.records
        )

    def test_unknown_action_on_a_txn_row_is_excluded_with_a_warning(self, conn, caplog) -> None:
        caplog.set_level(logging.WARNING, logger="app.db.sqlite")
        _record_import(conn)
        good = make_txn(txn_id="good-action-1", action=TxnAction.SELL, source_row=0)
        bad = make_txn(txn_id="bad-action-1", action=TxnAction.SELL, source_row=1)
        ledger.insert_transactions(conn, [good, bad])
        conn.execute("UPDATE txn SET action = ? WHERE txn_id = ?", ("crypto_stake", "bad-action-1"))

        rows = ledger.fetch_transactions(conn)  # must not raise ValueError

        ids = {row["txn_id"] for row in rows}
        assert ids == {"good-action-1"}
        assert any(
            record.levelno >= logging.WARNING
            and "bad-action-1" in record.getMessage()
            and "crypto_stake" in record.getMessage()
            for record in caplog.records
        )

    def test_unknown_broker_on_an_account_row_is_excluded_with_a_warning(
        self, conn, caplog
    ) -> None:
        caplog.set_level(logging.WARNING, logger="app.db.sqlite")
        ledger.upsert_account(
            conn,
            sample_account(account_id="future-broker-acct", tax_treatment=TaxTreatment.TAXABLE),
        )
        conn.execute(
            "UPDATE account SET broker = ? WHERE account_id = ?", ("fidelity", "future-broker-acct")
        )

        accounts = ledger.fetch_accounts(conn)  # must not raise ValueError

        ids = {a.account_id for a in accounts}
        assert "future-broker-acct" not in ids
        assert "rh-taxable" in ids  # the `conn` fixture's own good account is unaffected
        assert any(
            record.levelno >= logging.WARNING
            and "future-broker-acct" in record.getMessage()
            and "fidelity" in record.getMessage()
            for record in caplog.records
        )

    def test_a_known_broker_and_action_round_trip_unaffected(self, conn) -> None:
        """The guard must not become a second way to lose a perfectly good row."""
        _record_import(conn)
        txn = make_txn(txn_id="normal-1", action=TxnAction.BUY, broker=Broker.ROBINHOOD)
        ledger.insert_transactions(conn, [txn])

        rows = ledger.fetch_transactions(conn)

        assert {row["txn_id"] for row in rows} == {"normal-1"}

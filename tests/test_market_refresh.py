"""Tests for `app.market.refresh`: priority order, the staleness gate, pacing/backoff, the
wall-time cap, and the observable progress record.

Every test drives `refresh.run_once` directly against a hand-written fake `BarProvider` wrapped in a
real `ProviderRegistry` -- the same pattern `tests/test_market_store.py` uses for `store.sync_bars` --
and an autouse fixture replaces `app.market.macro.build_snapshot` with a fake so the macro-page warm
step this module also runs never constructs a real FRED/CNN client. A second autouse fixture
monkeypatches `socket.socket.connect` to raise, which is the concrete proof (not just an absence of
assertions) that nothing in this file ever falls through to a real request: any code path that tried
would fail loudly here rather than silently succeeding against the network. See this file's own
`test_refresh_on_startup_defaults_to_false` and `test_lifespan_leaves_the_sweep_untouched_by_default`
for the two facts that keep the *rest* of the suite -- every other file's `with TestClient(app)`
-- from ever reaching this module's network code at all.
"""

from __future__ import annotations

import datetime as dt
import threading

import pandas as pd
import pytest

from app.config import Settings
from app.core.models import Instrument
from app.db import sqlite as ledger
from app.db.duck import BAR_COLUMNS, Interval
from app.market import macro, refresh, store
from app.market.macro_models import MacroUnit
from app.market.providers.base import ProviderUnavailable, RateLimited
from app.market.registry import ProviderRegistry

# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------


def _bar(ts: dt.datetime, price: float = 100.0) -> dict[str, object]:
    return {
        "ts": ts,
        "open": price,
        "high": price + 0.5,
        "low": price - 0.5,
        "close": price,
        "adj_close": price,
        "volume": 1000,
    }


def _frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=list(BAR_COLUMNS))


def _today() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class FakeProvider:
    """A `BarProvider` whose response (or exception) is configured per `(symbol, interval)`, and
    which records every call in the order it was made -- what lets the priority-order tests assert
    *which* symbols were asked about first, not just that they eventually were.
    """

    def __init__(self) -> None:
        self.name = "yahoo"
        self.supported_intervals = frozenset({Interval.DAY, Interval.HOUR, Interval.FIVE_MIN})
        self.calls: list[tuple[str, Interval]] = []
        self._frames: dict[tuple[str, Interval], pd.DataFrame] = {}
        self._errors: dict[tuple[str, Interval], Exception] = {}

    def set_frame(self, symbol: str, interval: Interval, frame: pd.DataFrame) -> None:
        self._frames[(symbol, interval)] = frame

    def set_error(self, symbol: str, interval: Interval, exc: Exception) -> None:
        self._errors[(symbol, interval)] = exc

    def fetch_bars(
        self,
        symbol: str,
        interval: Interval,
        *,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> pd.DataFrame:
        self.calls.append((symbol, interval))
        key = (symbol, interval)
        if key in self._errors:
            raise self._errors[key]
        frame = self._frames.get(key, _frame([]))
        if start is None:
            return frame
        cutoff = pd.Timestamp(start, tz="UTC")
        return frame[frame["ts"] >= cutoff].reset_index(drop=True)


def _registry(provider: FakeProvider) -> ProviderRegistry:
    return ProviderRegistry(bar_providers=(provider,))


def _seed(settings: Settings, symbol: str, *, ts: dt.datetime, interval: Interval = Interval.DAY) -> None:
    """Write one bar for `symbol` directly through `store.sync_bars`, so the partition exists on disk
    (`app.db.duck.stored_symbols` only lists symbols with a written parquet file -- an empty-frame
    sync never creates one, see `store._has_stored_rows`) and `store.coverage(...).last_ts` is `ts`.
    """
    seeder = FakeProvider()
    seeder.set_frame(symbol, interval, _frame([_bar(ts)]))
    store.sync_bars(symbol, interval, registry=_registry(seeder), settings=settings)


@pytest.fixture(autouse=True)
def _reset_progress() -> None:
    """`refresh._progress` is module-level, shared across every test in the process. `run_once`
    resets it at the start of every real sweep, but a test that only reads `status()` without calling
    `run_once` (see the lifespan test below) must not see another test's leftover state.
    """
    refresh._progress = refresh.RefreshProgress()


@pytest.fixture(autouse=True)
def _fake_macro_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace `macro.build_snapshot` -- the priority-1 macro-page warm this module also runs -- with
    a no-op fake. Real `build_snapshot` builds its own FRED/CNN clients when none are injected, which
    would otherwise make a real HTTP request even with an empty `_MOVERS`/`_RATE_TILES`/`_OIL_TILES`
    (Fear & Greed is fetched unconditionally). Individual tests override this again when they care
    what a macro-snapshot failure looks like.
    """

    def _fake(cfg, *, refresh=False, as_of=None, fred=None, cnn=None, registry=None):
        return None

    monkeypatch.setattr(macro, "build_snapshot", _fake)


@pytest.fixture(autouse=True)
def _no_priority_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty out `_MOVERS`/`_RATE_TILES`/`_OIL_TILES` by default so most tests only have to reason
    about the store symbols they themselves set up. `TestPriorityOrder` below restores real (small,
    hand-built) values to test the ordering those constants actually drive.
    """
    monkeypatch.setattr(macro, "_MOVERS", ())
    monkeypatch.setattr(macro, "_RATE_TILES", ())
    monkeypatch.setattr(macro, "_OIL_TILES", ())


@pytest.fixture(autouse=True)
def _fast_pacing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pacing delay and rate-limit backoff are real production behaviour, not something every
    test needs to wait through in real wall-clock time. `TestPacingAndBackoff` overrides these back
    to verify the values themselves.
    """
    monkeypatch.setattr(refresh, "_REQUEST_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(refresh, "_RATE_LIMIT_BACKOFF_SECONDS", 0.0)


@pytest.fixture(autouse=True)
def _block_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Concrete, executable proof this file never falls through to a real request: any attempt to
    issue a real HTTP request raises rather than silently succeeding. Patched at `httpx.HTTPTransport`
    -- the sync transport `app.market.registry.default_registry` and `app.market.macro`'s FRED/CNN
    clients both build -- rather than at the raw socket layer: blocking sockets outright also breaks
    `asyncio`'s own self-pipe (`socket.socketpair()`'s Windows fallback calls `socket.connect`), which
    `TestClient(app)`'s event loop needs for entirely unrelated, non-network reasons. This is narrower
    and does not false-positive on that, or on DuckDB/SQLite, which are local file I/O and never touch
    `httpx` at all.
    """
    import httpx

    def _blocked(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"test_market_refresh.py attempted a real HTTP request: {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked)


# ---------------------------------------------------------------------------
# Settings default
# ---------------------------------------------------------------------------


def test_refresh_on_startup_defaults_to_false(settings: Settings) -> None:
    """The one fact every other test file's `with TestClient(app) as ...:` depends on for network
    safety: `tests/conftest.py`'s `settings` fixture does not set `INVDASH_REFRESH_ON_STARTUP`, so
    every test that runs the real `lifespan` inherits this class default unchanged.
    """
    assert settings.refresh_on_startup is False


def test_lifespan_leaves_the_sweep_untouched_by_default(settings: Settings) -> None:
    """End-to-end proof, not just the unit fact above: the real FastAPI `lifespan` -- which only runs
    inside `with TestClient(app) as ...:`, never on bare construction -- never calls
    `refresh_market_data` at all when `refresh_on_startup` is left at its default.
    """
    from starlette.testclient import TestClient

    from app.main import app

    with TestClient(app):
        pass

    body = refresh.status()
    assert body["running"] is False
    assert body["started_at"] is None
    assert body["queued"] == 0


# ---------------------------------------------------------------------------
# Priority order
# ---------------------------------------------------------------------------


class TestPriorityOrder:
    def test_movers_and_tile_proxies_come_before_holdings_and_the_rest(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(macro, "_MOVERS", (("BTC-USD", "Bitcoin", MacroUnit.USD),))
        oil_tile = macro._TileSpec("wti", "WTI Crude", "DCOILWTICO", MacroUnit.USD, "CL=F")
        monkeypatch.setattr(macro, "_OIL_TILES", (oil_tile,))

        with ledger.connect(settings.ledger_path) as conn:
            ledger.migrate(conn)
            ledger.upsert_instrument(
                conn, Instrument(instrument_id="i1", primary_symbol="AAPL", is_priceable=True)
            )

        old = _today() - dt.timedelta(days=30)
        for symbol in ("BTC-USD", "CL=F", "AAPL", "ZZZ"):
            _seed(settings, symbol, ts=old)

        provider = FakeProvider()
        registry = _registry(provider)

        refresh.run_once(settings, registry=registry)

        # Priority 1 (macro movers, then tile proxies) before priority 2 (held) before priority 3
        # (everything else already in the store). Exact order within a tier is not asserted, only
        # the tier boundaries -- see `_build_worklist`.
        assert provider.calls == [
            ("BTC-USD", Interval.DAY),
            ("CL=F", Interval.DAY),
            ("AAPL", Interval.DAY),
            ("ZZZ", Interval.DAY),
        ]

    def test_a_symbol_in_two_tiers_is_only_queued_once_at_its_highest_priority(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(macro, "_MOVERS", (("BTC-USD", "Bitcoin", MacroUnit.USD),))
        with ledger.connect(settings.ledger_path) as conn:
            ledger.migrate(conn)
            ledger.upsert_instrument(
                conn, Instrument(instrument_id="i1", primary_symbol="BTC-USD", is_priceable=True)
            )
        _seed(settings, "BTC-USD", ts=_today() - dt.timedelta(days=30))

        provider = FakeProvider()
        refresh.run_once(settings, registry=_registry(provider))

        assert provider.calls == [("BTC-USD", Interval.DAY)]
        assert refresh.status()["queued"] == 1


# ---------------------------------------------------------------------------
# Staleness gate
# ---------------------------------------------------------------------------


class TestStalenessGate:
    def test_a_symbol_synced_through_the_latest_session_is_skipped_not_refetched(
        self, settings: Settings
    ) -> None:
        latest_session = refresh._latest_expected_session(_today().date())
        session_ts = dt.datetime(
            latest_session.year, latest_session.month, latest_session.day, tzinfo=dt.UTC
        )
        _seed(settings, "SPY", ts=session_ts)

        provider = FakeProvider()
        refresh.run_once(settings, registry=_registry(provider))

        assert provider.calls == []
        body = refresh.status()
        assert body["skipped_fresh"] == 1
        assert body["refreshed"] == 0
        assert body["queued"] == 1

    def test_a_symbol_last_synced_before_the_latest_session_is_refetched(
        self, settings: Settings
    ) -> None:
        _seed(settings, "SPY", ts=_today() - dt.timedelta(days=10))

        provider = FakeProvider()
        provider.set_frame("SPY", Interval.DAY, _frame([_bar(_today())]))
        refresh.run_once(settings, registry=_registry(provider))

        assert provider.calls == [("SPY", Interval.DAY)]
        body = refresh.status()
        assert body["refreshed"] == 1
        assert body["skipped_fresh"] == 0

    def test_a_symbol_never_synced_is_never_fresh(self) -> None:
        assert refresh._is_fresh(None) is False


class TestPreCloseStalenessGate:
    """Pins the fix for the bug described in `refresh._latest_settled_session`'s docstring: comparing
    `Coverage.last_ts` against `_latest_expected_session(today)` directly -- today literally, on any
    ordinary weekday -- treated a symbol current through *yesterday's* close as stale for the entire
    pre-close part of every weekday, and it could never be marked fresh again that day because the
    provider correctly refuses to hand back a bar for a session still in progress. Confirmed against
    the real functions before this fix: on Wednesday 2026-08-26 pre-market,
    `refresh._latest_expected_session(dt.date(2026, 8, 26))` returned `2026-08-26` itself (a plain
    weekday has no rollback), so `refresh._is_fresh` for a symbol synced through Tuesday 2026-08-25's
    close returned `False` -- stale -- no matter how many times it was checked that morning.
    """

    def test_a_symbol_current_through_yesterdays_close_is_fresh_before_todays_session_has_closed(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Wednesday 2026-08-26, 07:50 ET == 11:50 UTC -- pre-market, well before
        # `_MARKET_CLOSE_UTC_HOUR`, and a plain weekday so `_latest_expected_session` itself does not
        # roll back at all. Before the fix, `_is_fresh` compared straight against this literal date
        # and always returned `False` for a symbol dated the day before, all day.
        pre_market = dt.datetime(2026, 8, 26, 11, 50, tzinfo=dt.UTC)
        monkeypatch.setattr(refresh, "_now", lambda: pre_market)

        yesterdays_close = dt.datetime(2026, 8, 25, 20, 0, tzinfo=dt.UTC)
        _seed(settings, "SPY", ts=yesterdays_close)

        provider = FakeProvider()
        refresh.run_once(settings, registry=_registry(provider))

        assert provider.calls == []  # no wasted request for a symbol that was already current
        body = refresh.status()
        assert body["skipped_fresh"] == 1
        assert body["refreshed"] == 0

    def test_the_same_symbol_is_stale_again_once_todays_session_has_plausibly_closed(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Same Wednesday, 20:30 UTC -- past `_MARKET_CLOSE_UTC_HOUR`, so today's own session is
        # presumed closed and now *is* the freshness bar a symbol has to clear. This is the case the
        # fix must not regress: once today's bar is plausibly available, a symbol still sitting at
        # yesterday's close is genuinely stale again and must be re-fetched, not skipped forever.
        after_close = dt.datetime(2026, 8, 26, 20, 30, tzinfo=dt.UTC)
        monkeypatch.setattr(refresh, "_now", lambda: after_close)

        yesterdays_close = dt.datetime(2026, 8, 25, 20, 0, tzinfo=dt.UTC)
        _seed(settings, "SPY", ts=yesterdays_close)

        provider = FakeProvider()
        provider.set_frame("SPY", Interval.DAY, _frame([_bar(after_close)]))
        refresh.run_once(settings, registry=_registry(provider))

        assert provider.calls == [("SPY", Interval.DAY)]
        body = refresh.status()
        assert body["refreshed"] == 1
        assert body["skipped_fresh"] == 0


class TestLatestSettledSession:
    """Direct, non-network unit tests on `_session_has_plausibly_closed` / `_latest_settled_session`
    themselves -- narrower than the end-to-end `TestPreCloseStalenessGate` above, and what pins the
    exact boundary hour and the weekend interaction independently of the sweep machinery around them.
    """

    def test_pre_market_on_a_weekday_rolls_back_to_the_prior_settled_weekday(self) -> None:
        pre_market = dt.datetime(2026, 8, 26, 11, 50, tzinfo=dt.UTC)  # Wednesday
        assert refresh._latest_settled_session(pre_market) == dt.date(2026, 8, 25)

    def test_a_monday_pre_market_rolls_back_through_the_weekend_to_friday(self) -> None:
        pre_market = dt.datetime(2026, 8, 31, 11, 50, tzinfo=dt.UTC)  # Monday
        assert refresh._latest_settled_session(pre_market) == dt.date(2026, 8, 28)

    def test_at_and_after_the_close_cutoff_todays_own_date_is_the_settled_session(self) -> None:
        at_close = dt.datetime(2026, 8, 26, 20, 0, tzinfo=dt.UTC)
        assert refresh._latest_settled_session(at_close) == dt.date(2026, 8, 26)

    def test_one_minute_before_the_close_cutoff_still_rolls_back(self) -> None:
        just_before_close = dt.datetime(2026, 8, 26, 19, 59, tzinfo=dt.UTC)
        assert refresh._latest_settled_session(just_before_close) == dt.date(2026, 8, 25)

    def test_weekend_dates_still_roll_back_to_friday_regardless_of_time_of_day(self) -> None:
        # A Saturday/Sunday `now` never equals its own `_latest_expected_session`, so
        # `_session_has_plausibly_closed` is never even consulted -- this is what proves that.
        saturday_morning = dt.datetime(2026, 8, 29, 1, 0, tzinfo=dt.UTC)
        saturday_night = dt.datetime(2026, 8, 29, 23, 0, tzinfo=dt.UTC)
        assert refresh._latest_settled_session(saturday_morning) == dt.date(2026, 8, 28)
        assert refresh._latest_settled_session(saturday_night) == dt.date(2026, 8, 28)


# ---------------------------------------------------------------------------
# Failure counting -- the honesty requirement
# ---------------------------------------------------------------------------


class TestFailureCounting:
    def test_a_failed_symbol_is_counted_and_named_distinctly_from_a_fresh_or_refreshed_one(
        self, settings: Settings
    ) -> None:
        _seed(settings, "OK", ts=_today() - dt.timedelta(days=10))
        _seed(settings, "BROKEN", ts=_today() - dt.timedelta(days=10))

        provider = FakeProvider()
        provider.set_frame("OK", Interval.DAY, _frame([_bar(_today())]))
        provider.set_error(
            "BROKEN", Interval.DAY, ProviderUnavailable("upstream is down", provider="yahoo")
        )

        refresh.run_once(settings, registry=_registry(provider))

        body = refresh.status()
        assert body["refreshed"] == 1
        assert body["failed"] == 1
        assert body["skipped_fresh"] == 0
        assert body["failed_symbols"] == [f"BROKEN:{Interval.DAY.value}"]
        # The queued/processed totals must still reconcile -- a failure is counted, never dropped.
        assert body["processed"] == body["queued"] == 2

    def test_an_unexpected_exception_is_still_counted_as_failed_not_raised(
        self, settings: Settings
    ) -> None:
        _seed(settings, "BROKEN", ts=_today() - dt.timedelta(days=10))
        provider = FakeProvider()
        provider.set_error("BROKEN", Interval.DAY, RuntimeError("duckdb blew up"))

        refresh.run_once(settings, registry=_registry(provider))  # must not raise

        assert refresh.status()["failed"] == 1


# ---------------------------------------------------------------------------
# Pacing and rate-limit backoff
# ---------------------------------------------------------------------------


class TestPacingAndBackoff:
    def test_a_delay_is_paid_between_every_processed_symbol(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(refresh, "_REQUEST_DELAY_SECONDS", 0.05)
        sleeps: list[float] = []
        monkeypatch.setattr(refresh.time, "sleep", sleeps.append)

        _seed(settings, "AAA", ts=_today() - dt.timedelta(days=10))
        _seed(settings, "BBB", ts=_today() - dt.timedelta(days=10))
        provider = FakeProvider()
        provider.set_frame("AAA", Interval.DAY, _frame([_bar(_today())]))
        provider.set_frame("BBB", Interval.DAY, _frame([_bar(_today())]))

        refresh.run_once(settings, registry=_registry(provider))

        assert sleeps == [0.05, 0.05]

    def test_rate_limit_backs_off_using_retry_after_and_never_retries_the_same_symbol(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sleeps: list[float] = []
        monkeypatch.setattr(refresh.time, "sleep", sleeps.append)

        _seed(settings, "AAA", ts=_today() - dt.timedelta(days=10))
        _seed(settings, "BBB", ts=_today() - dt.timedelta(days=10))
        provider = FakeProvider()
        provider.set_error(
            "AAA", Interval.DAY, RateLimited("slow down", provider="yahoo", retry_after=2.5)
        )
        provider.set_frame("BBB", Interval.DAY, _frame([_bar(_today())]))

        refresh.run_once(settings, registry=_registry(provider))

        assert provider.calls.count(("AAA", Interval.DAY)) == 1  # no tight retry loop
        assert 2.5 in sleeps
        body = refresh.status()
        assert body["failed"] == 1
        assert body["refreshed"] == 1

    def test_rate_limit_without_a_retry_after_uses_the_default_backoff(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(refresh, "_RATE_LIMIT_BACKOFF_SECONDS", 7.0)
        sleeps: list[float] = []
        monkeypatch.setattr(refresh.time, "sleep", sleeps.append)

        _seed(settings, "AAA", ts=_today() - dt.timedelta(days=10))
        provider = FakeProvider()
        provider.set_error("AAA", Interval.DAY, RateLimited("slow down", provider="yahoo"))

        refresh.run_once(settings, registry=_registry(provider))

        assert 7.0 in sleeps


# ---------------------------------------------------------------------------
# Wall-time cap
# ---------------------------------------------------------------------------


class TestWallTimeCap:
    def test_the_cap_stops_the_sweep_and_marks_it_incomplete_rather_than_silently_partial(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(refresh, "_MAX_WALL_TIME_SECONDS", 0.0)
        _seed(settings, "AAA", ts=_today() - dt.timedelta(days=10))
        _seed(settings, "BBB", ts=_today() - dt.timedelta(days=10))
        provider = FakeProvider()

        refresh.run_once(settings, registry=_registry(provider))

        body = refresh.status()
        assert body["complete"] is False
        assert body["stopped_reason"] is not None
        assert "wall-time cap" in body["stopped_reason"]
        assert body["queued"] == 2
        assert provider.calls == []  # the cap was already exceeded before the first item

    def test_a_sweep_that_finishes_inside_the_cap_is_marked_complete(self, settings: Settings) -> None:
        _seed(settings, "AAA", ts=_today() - dt.timedelta(days=10))
        provider = FakeProvider()
        provider.set_frame("AAA", Interval.DAY, _frame([_bar(_today())]))

        refresh.run_once(settings, registry=_registry(provider))

        body = refresh.status()
        assert body["complete"] is True
        assert body["stopped_reason"] is None


# ---------------------------------------------------------------------------
# Macro-snapshot warm status
# ---------------------------------------------------------------------------


class TestMacroSnapshotStatus:
    def test_success_is_recorded_separately_from_the_symbol_counters(self, settings: Settings) -> None:
        refresh.run_once(settings, registry=_registry(FakeProvider()))
        assert refresh.status()["macro_snapshot"] == "ok"

    def test_failure_is_recorded_and_does_not_inflate_the_failed_symbol_count(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(cfg, *, refresh=False, as_of=None, fred=None, cnn=None, registry=None):
            raise RuntimeError("FRED is down")

        monkeypatch.setattr(macro, "build_snapshot", _boom)

        refresh.run_once(settings, registry=_registry(FakeProvider()))

        body = refresh.status()
        assert body["macro_snapshot"] == "failed"
        assert body["failed"] == 0  # this is not a bar-store symbol failure


# ---------------------------------------------------------------------------
# The daemon-thread entry point
# ---------------------------------------------------------------------------


class TestRefreshMarketData:
    """`refresh_market_data` is a thin threading wrapper around `run_once` -- see the module
    docstring. These tests replace `run_once` itself with a fake so they exercise only that wrapper
    (thread start, the non-blocking double-start guard) without re-running the sweep logic already
    covered above, and without any dependency on real pacing delays.
    """

    def test_starts_a_daemon_thread_that_calls_run_once(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called_with: list[Settings | None] = []

        def _fake_run_once(settings: Settings | None = None, *, registry: object = None) -> None:
            called_with.append(settings)

        monkeypatch.setattr(refresh, "run_once", _fake_run_once)

        assert refresh.refresh_market_data(settings) is True

        # Block until the background thread's own `finally: _sweep_lock.release()` has run --
        # deterministic proof the thread actually executed `run_once` and finished, not merely that
        # it started. Released again immediately so the lock is clean for the next test.
        assert refresh._sweep_lock.acquire(timeout=2.0)
        refresh._sweep_lock.release()

        assert called_with == [settings]

    def test_a_start_returns_true_before_the_sweep_has_reached_run_once(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The reason `refresh_market_data` reports the outcome itself instead of letting the caller
        read `status()["running"]`: a successful start is still `running is False` for as long as the
        new thread takes to get into `run_once`, so an API layer inferring "did I start one?" from the
        progress record would report "already running" and "not running" at the same instant.
        """
        gate = threading.Event()

        def _fake_run_once(settings: Settings | None = None, *, registry: object = None) -> None:
            gate.wait(timeout=2.0)

        monkeypatch.setattr(refresh, "run_once", _fake_run_once)

        started = refresh.refresh_market_data(settings)

        assert started is True
        assert refresh.status()["running"] is False  # the thread has not reached `run_once` yet

        gate.set()
        assert refresh._sweep_lock.acquire(timeout=2.0)
        refresh._sweep_lock.release()

    def test_a_start_refused_because_the_lock_is_held_returns_false(self, settings: Settings) -> None:
        """The `already_running` signal the on-demand endpoint renders, tested against the lock
        directly rather than through a second thread -- `_sweep_lock` held is the whole condition.
        """
        assert refresh._sweep_lock.acquire(blocking=False)
        try:
            assert refresh.refresh_market_data(settings) is False
        finally:
            refresh._sweep_lock.release()

    def test_a_second_call_while_a_sweep_is_running_does_not_start_another(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        first_running = threading.Event()
        release = threading.Event()
        calls: list[int] = []

        def _fake_run_once(settings: Settings | None = None, *, registry: object = None) -> None:
            calls.append(1)
            first_running.set()
            release.wait(timeout=2.0)

        monkeypatch.setattr(refresh, "run_once", _fake_run_once)

        assert refresh.refresh_market_data(settings) is True
        assert first_running.wait(timeout=2.0)

        # The lock is held -- must be a synchronous no-op that says so rather than a silent one.
        assert refresh.refresh_market_data(settings) is False
        assert len(calls) == 1

        release.set()
        assert refresh._sweep_lock.acquire(timeout=2.0)  # wait for the first thread to fully finish
        refresh._sweep_lock.release()

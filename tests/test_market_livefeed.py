"""Tests for `app.market.livefeed`: the shared source singleton, the keep-warm daemon, and `status()`.

No test here touches the network. Two autouse fixtures make that a proven property rather than an
absence of assertions: one replaces `livefeed.build_source` with a fake that has no thread and no
socket, and one blocks `httpx.HTTPTransport.handle_request` outright so any path that slipped past
the fake fails loudly. The block is at the httpx transport rather than at `socket.socket.connect` --
`tests/test_market_refresh.py` documents why: blocking raw sockets also breaks `asyncio`'s Windows
self-pipe, which is unrelated to anything under test.

The daemon is exercised two ways on purpose. `_tick` is called directly where the assertion is about
*content* (which symbols were subscribed, how a failure streak accumulates), because a test that
sleeps to observe content is a test that flakes. A real thread is started only where the assertion is
about the thread itself -- that it repeats, and that `stop()` joins it.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from decimal import Decimal

import pytest

from app.config import Settings
from app.market import live, livefeed
from app.market.live import DEFAULT_WATCH_IDLE_SECONDS, LiveQuote, LiveQuoteError, LiveSnapshot

_NOW = dt.datetime(2026, 9, 8, 14, 32, 5, tzinfo=dt.UTC)


# ---------------------------------------------------------------------------
# Fakes and fixtures
# ---------------------------------------------------------------------------


class FakeSource:
    """A `LiveQuoteSource` with no thread and no network.

    `healthy` is a plain attribute rather than a property so a test can flip it, matching the
    duck-typed `getattr(instance, "healthy", None)` read `status()` actually performs against
    `PollingQuoteSource.healthy`.
    """

    def __init__(self, *, quotes: tuple[LiveQuote, ...] = (), raises: bool = False) -> None:
        self.quotes = quotes
        self.raises = raises
        self.healthy = True
        self.calls: list[list[str]] = []
        self.closed = 0
        self._lock = threading.Lock()

    def snapshot(self, symbols: Sequence[str]) -> LiveSnapshot:
        with self._lock:
            self.calls.append(list(symbols))
        if self.raises:
            raise RuntimeError("upstream is down")
        requested = {s.upper() for s in symbols}
        served = tuple(q for q in self.quotes if q.symbol in requested)
        return LiveSnapshot(
            as_of=_NOW,
            market_state="REGULAR",
            transport="poll",
            healthy=self.healthy,
            quotes=served,
            errors=tuple(
                LiveQuoteError(symbol=s, message="no quote available yet")
                for s in sorted(requested - {q.symbol for q in served})
            ),
        )

    def close(self) -> None:
        self.closed += 1

    @property
    def call_count(self) -> int:
        with self._lock:
            return len(self.calls)


def _quote(symbol: str = "AAPL", price: str = "231.45") -> LiveQuote:
    return LiveQuote(
        symbol=symbol,
        price=Decimal(price),
        previous_close=Decimal("228.70"),
        change=Decimal("2.75"),
        change_pct=Decimal("1.2024"),
        ts=_NOW,
        stale=False,
        source="yahoo",
    )


@pytest.fixture(autouse=True)
def _block_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any real HTTP request from this file is an assertion failure, not a slow test."""
    import httpx

    def _blocked(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"test_market_livefeed.py attempted a real HTTP request: {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked)


@pytest.fixture(autouse=True)
def _reset_livefeed() -> Iterator[None]:
    """Module-level state is process-wide by design, so every test starts and ends from zero --
    including the daemon thread, which `reset()` stops before dropping the singleton."""
    livefeed.reset()
    yield
    livefeed.reset()


@pytest.fixture
def fake_source(monkeypatch: pytest.MonkeyPatch) -> FakeSource:
    fake = FakeSource(quotes=(_quote(),))
    monkeypatch.setattr(livefeed, "build_source", lambda _settings: fake)
    return fake


def _cfg(settings: Settings, **overrides: object) -> Settings:
    return settings.model_copy(update=overrides)


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 5.0) -> bool:
    """Poll `predicate` until it is true or `timeout` elapses. Used only where the assertion is about
    a real thread doing something more than once -- never to observe content."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ---------------------------------------------------------------------------
# The shared source
# ---------------------------------------------------------------------------


class TestSourceSingleton:
    def test_the_source_is_built_once_and_reused(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        built: list[Settings] = []

        def _build(cfg: Settings) -> FakeSource:
            built.append(cfg)
            return FakeSource()

        monkeypatch.setattr(livefeed, "build_source", _build)

        first = livefeed.source(settings)
        second = livefeed.source(settings)

        assert first is second
        assert len(built) == 1

    def test_reset_drops_the_singleton_and_closes_it(
        self, settings: Settings, fake_source: FakeSource
    ) -> None:
        assert livefeed.source(settings) is fake_source
        livefeed.reset()
        assert fake_source.closed == 1

    def test_snapshot_delegates_to_the_source_upper_cased(
        self, settings: Settings, fake_source: FakeSource
    ) -> None:
        livefeed.source(settings)
        snap = livefeed.snapshot([" aapl ", "msft", "AAPL"])

        assert fake_source.calls[-1] == ["AAPL", "MSFT"]
        assert snap.transport == "poll"
        assert [q.symbol for q in snap.quotes] == ["AAPL"]


class TestLatest:
    def test_returns_the_quote_for_one_symbol(
        self, settings: Settings, fake_source: FakeSource
    ) -> None:
        livefeed.source(settings)
        quote = livefeed.latest("aapl")

        assert quote is not None
        assert quote.symbol == "AAPL"
        assert quote.price == Decimal("231.45")

    def test_returns_none_when_the_source_raises(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(livefeed, "build_source", lambda _s: FakeSource(raises=True))
        livefeed.source(settings)

        assert livefeed.latest("AAPL") is None

    def test_returns_none_when_the_snapshot_carries_no_quote_for_the_symbol(
        self, settings: Settings, fake_source: FakeSource
    ) -> None:
        livefeed.source(settings)
        assert livefeed.latest("NOSUCH") is None

    def test_latest_with_snapshot_carries_the_transport(
        self, settings: Settings, fake_source: FakeSource
    ) -> None:
        livefeed.source(settings)
        quote, snap = livefeed.latest_with_snapshot("AAPL")

        assert quote is not None
        assert snap is not None
        assert snap.transport == "poll"


# ---------------------------------------------------------------------------
# The watchlist
# ---------------------------------------------------------------------------


class TestWatchlist:
    def test_watch_is_idempotent_and_upper_cases(self, settings: Settings) -> None:
        livefeed.watch(["aapl", "AAPL", " msft "])
        livefeed.watch(["AAPL"])

        assert livefeed.status()["symbols"] == ["AAPL", "MSFT"]
        assert livefeed.status()["watched"] == 2

    def test_unwatch_removes_only_what_watch_added(self, settings: Settings) -> None:
        livefeed.watch(["AAPL", "MSFT"])
        livefeed.unwatch(["aapl"])

        assert livefeed.status()["symbols"] == ["MSFT"]

    def test_targets_include_manual_configured_and_mover_symbols(self, settings: Settings) -> None:
        livefeed.watch(["NVDA"])
        cfg = _cfg(settings, livefeed_watchlist="tsla, brk.b ,")

        targets = livefeed._watch_targets(cfg)

        assert "NVDA" in targets  # watch()
        assert "TSLA" in targets and "BRK.B" in targets  # livefeed_watchlist, trimmed and cased
        assert "SPY" in targets and "^VIX" in targets  # app.market.macro._MOVERS
        assert len(targets) == len(set(targets))  # de-duplicated
        assert len(targets) <= livefeed._MAX_WATCHED

    def test_the_watchlist_is_capped(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            livefeed, "_held_ledger_symbols", lambda _cfg: [f"S{i:04d}" for i in range(500)]
        )
        livefeed.watch(["KEEPME"])

        targets = livefeed._watch_targets(settings)

        assert len(targets) == livefeed._MAX_WATCHED
        # Explicit interest survives the truncation: it is first in the priority order.
        assert targets[0] == "KEEPME"


# ---------------------------------------------------------------------------
# The daemon
# ---------------------------------------------------------------------------


class TestStartStop:
    def test_start_is_a_no_op_when_disabled(
        self, settings: Settings, fake_source: FakeSource
    ) -> None:
        livefeed.start(_cfg(settings, livefeed_enabled=False))

        status = livefeed.status()
        assert status["running"] is False
        assert status["enabled"] is False
        assert status["started_at"] is None
        assert fake_source.call_count == 0

    def test_start_runs_the_daemon_which_re_subscribes_repeatedly_and_stop_joins_it(
        self, settings: Settings, fake_source: FakeSource
    ) -> None:
        cfg = _cfg(
            settings,
            livefeed_enabled=True,
            livefeed_watchlist="AAPL",
            livefeed_keepalive_seconds=0.05,
        )
        livefeed.start(cfg)

        assert livefeed.status()["running"] is True
        # More than one call is the actual claim: the daemon keeps the watchlist warm rather than
        # subscribing once at startup and letting PollingQuoteSource evict it later.
        assert _wait_until(lambda: fake_source.call_count >= 2), "the daemon did not tick twice"
        assert all("AAPL" in call for call in fake_source.calls)

        livefeed.stop(timeout=5.0)

        status = livefeed.status()
        assert status["running"] is False
        assert status["started_at"] is None
        settled = fake_source.call_count
        time.sleep(0.15)
        assert fake_source.call_count == settled, "the daemon kept ticking after stop()"

    def test_a_second_start_does_not_launch_a_second_daemon(
        self, settings: Settings, fake_source: FakeSource
    ) -> None:
        cfg = _cfg(settings, livefeed_enabled=True, livefeed_keepalive_seconds=1.0)
        livefeed.start(cfg)
        first = livefeed._thread
        livefeed.start(cfg)

        assert livefeed._thread is first

    def test_stop_without_a_running_daemon_is_a_no_op(self, settings: Settings) -> None:
        livefeed.stop()  # must not raise


class TestTick:
    def test_a_tick_records_the_snapshot_and_the_market_state(
        self, settings: Settings, fake_source: FakeSource
    ) -> None:
        livefeed.watch(["AAPL"])
        livefeed._tick(_cfg(settings, livefeed_enabled=True))

        status = livefeed.status()
        assert status["market_state"] == "REGULAR"
        assert status["last_snapshot_at"] == _NOW.isoformat()
        assert status["healthy"] is True

    def test_healthy_goes_false_after_consecutive_total_failures(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeSource(raises=True)
        fake.healthy = True  # the source itself still claims health; the daemon must not
        monkeypatch.setattr(livefeed, "build_source", lambda _s: fake)
        cfg = _cfg(settings, livefeed_enabled=True)
        livefeed.watch(["AAPL"])

        for _ in range(livefeed._UNHEALTHY_AFTER_TICKS - 1):
            livefeed._tick(cfg)
        assert livefeed.status()["healthy"] is True, "one bad tick must not be called an outage"

        livefeed._tick(cfg)
        assert livefeed.status()["healthy"] is False

    def test_a_tick_that_returns_no_quotes_at_all_also_counts_as_a_failure(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeSource(quotes=())  # answers, but never with a quote
        monkeypatch.setattr(livefeed, "build_source", lambda _s: fake)
        cfg = _cfg(settings, livefeed_enabled=True)
        livefeed.watch(["AAPL"])

        for _ in range(livefeed._UNHEALTHY_AFTER_TICKS):
            livefeed._tick(cfg)

        assert livefeed.status()["healthy"] is False

    def test_a_good_tick_clears_the_failure_streak(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeSource(quotes=(_quote(),), raises=True)
        monkeypatch.setattr(livefeed, "build_source", lambda _s: fake)
        cfg = _cfg(settings, livefeed_enabled=True)
        livefeed.watch(["AAPL"])

        for _ in range(livefeed._UNHEALTHY_AFTER_TICKS):
            livefeed._tick(cfg)
        assert livefeed.status()["healthy"] is False

        fake.raises = False
        livefeed._tick(cfg)
        assert livefeed.status()["healthy"] is True


# ---------------------------------------------------------------------------
# status()
# ---------------------------------------------------------------------------


class TestStatus:
    #: The pinned contract other modules (`app.market.freshness`, `app.api.data_admin`) read.
    KEYS = {
        "enabled",
        "transport",
        "running",
        "healthy",
        "watched",
        "symbols",
        "market_state",
        "last_snapshot_at",
        "started_at",
    }

    def test_the_shape_is_exactly_nine_keys(self, settings: Settings) -> None:
        status = livefeed.status()
        assert set(status) == self.KEYS
        assert len(status) == 9

    def test_a_cold_process_reports_nothing_rather_than_health(self, settings: Settings) -> None:
        status = livefeed.status()

        assert status["enabled"] is False
        assert status["transport"] == "poll"
        assert status["running"] is False
        assert status["healthy"] is None, "never ticked is not the same answer as healthy"
        assert status["watched"] == 0
        assert status["symbols"] == []
        assert status["market_state"] is None
        assert status["last_snapshot_at"] is None
        assert status["started_at"] is None

    def test_status_never_builds_the_source(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _build(_cfg: Settings) -> FakeSource:
            raise AssertionError("status() must not construct a live-quote source")

        monkeypatch.setattr(livefeed, "build_source", _build)
        assert livefeed.status()["healthy"] is None

    def test_transport_reflects_the_setting(self, settings: Settings) -> None:
        livefeed.start(_cfg(settings, livefeed_enabled=False, paperlive_transport="stream"))
        assert livefeed.status()["transport"] == "stream"


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class TestSettings:
    def test_the_keepalive_default_is_below_the_eviction_window(self) -> None:
        assert Settings().livefeed_keepalive_seconds < DEFAULT_WATCH_IDLE_SECONDS

    def test_the_configs_ceiling_is_the_real_eviction_window(self) -> None:
        """`app.config` cannot import `app.market.live` (that module imports `app.config`), so it
        carries a literal copy of the constant. This is what keeps the copy from drifting."""
        from app.config import _LIVEFEED_KEEPALIVE_CEILING_S

        assert _LIVEFEED_KEEPALIVE_CEILING_S == DEFAULT_WATCH_IDLE_SECONDS
        assert live.DEFAULT_WATCH_IDLE_SECONDS == DEFAULT_WATCH_IDLE_SECONDS

    def test_a_keepalive_at_or_above_the_eviction_window_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="livefeed_keepalive_seconds"):
            Settings(livefeed_keepalive_seconds=DEFAULT_WATCH_IDLE_SECONDS)
        with pytest.raises(ValueError, match="livefeed_keepalive_seconds"):
            Settings(livefeed_keepalive_seconds=900.0)

    def test_a_non_positive_keepalive_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="livefeed_keepalive_seconds"):
            Settings(livefeed_keepalive_seconds=0.0)

    def test_the_feed_is_off_by_default(self) -> None:
        cfg = Settings()
        assert cfg.livefeed_enabled is False
        assert cfg.livefeed_watchlist == ""

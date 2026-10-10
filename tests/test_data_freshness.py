"""Tests for `app.market.freshness` and `app.api.data_admin`: the on-demand sweep endpoint and the
per-source freshness report behind the Data page.

Three things this file exists to pin, in descending order of how expensive they would be to get
wrong:

1. **The wire contract.** The frontend maps each `key` to its own translated label and each
   `status` to its own colour, so the eleven keys, their order, and the closed sets `freshness_class`
   / `policy` / `status` draw from are not implementation details. `TestWireContract` asserts them
   directly rather than through any behaviour that happens to exercise them.
2. **No network, ever.** A freshness endpoint that fetched anything would answer its own question
   -- everything would always be fresh. `TestNoNetwork` proves it by blocking `socket.socket.connect`
   outright, which is stronger than the `httpx`-transport block the rest of this file (and
   `tests/test_market_refresh.py`) uses, and is only safe there because that test drives
   `freshness.report` directly with no `TestClient` event loop in the picture -- see
   `test_market_refresh.py::_block_real_network` for the `socketpair` problem that rules the raw
   socket block out everywhere else.
3. **Degrade, never 500.** A missing cache directory, an absent `livefeed` module or a measurement
   that raises must each cost exactly one row its number, and the other ten must still render.

The test app is built here rather than imported from `app.main`: this router is registered by
`app.main` in the integrating change, and a test that only reaches these two routes should not also
have to boot every other router (and lifespan) to do it.
"""

from __future__ import annotations

import datetime as dt
import socket
import sys
from types import ModuleType

import pandas as pd
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.api import data_admin
from app.config import Settings
from app.core.models import Instrument
from app.db import sqlite as ledger
from app.db.duck import BAR_COLUMNS, Interval
from app.market import freshness, macro, refresh, store
from app.market.registry import ProviderRegistry

# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------


class _SeedProvider:
    """The minimum `BarProvider` needed to write one partition through `store.sync_bars`, so a test
    can put a bar of a chosen age on disk without inventing a Parquet layout of its own."""

    def __init__(self, symbol: str, interval: Interval, ts: dt.datetime) -> None:
        self.name = "yahoo"
        self.supported_intervals = frozenset({Interval.DAY, Interval.HOUR, Interval.FIVE_MIN})
        self._key = (symbol, interval)
        self._frame = pd.DataFrame(
            [
                {
                    "ts": ts,
                    "open": 100.0,
                    "high": 100.5,
                    "low": 99.5,
                    "close": 100.0,
                    "adj_close": 100.0,
                    "volume": 1000,
                }
            ],
            columns=list(BAR_COLUMNS),
        )

    def fetch_bars(
        self,
        symbol: str,
        interval: Interval,
        *,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> pd.DataFrame:
        if (symbol, interval) != self._key:
            return pd.DataFrame([], columns=list(BAR_COLUMNS))
        return self._frame


def _seed_bar(
    settings: Settings, symbol: str, *, ts: dt.datetime, interval: Interval = Interval.DAY
) -> None:
    provider = _SeedProvider(symbol, interval, ts)
    store.sync_bars(
        symbol, interval, registry=ProviderRegistry(bar_providers=(provider,)), settings=settings
    )


def _hold(settings: Settings, *symbols: str) -> None:
    """Make `symbols` priceable ledger instruments, which is what puts them in the sweep's -- and
    therefore the freshness report's -- tracked set."""
    with ledger.connect(settings.ledger_path) as conn:
        ledger.migrate(conn)
        for index, symbol in enumerate(symbols):
            ledger.upsert_instrument(
                conn,
                Instrument(instrument_id=f"i{index}", primary_symbol=symbol, is_priceable=True),
            )


@pytest.fixture(autouse=True)
def _no_macro_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty the macro mover/tile constants so the tracked set is exactly what each test seeds into
    the ledger. `freshness._tracked_symbols` reads these straight from `app.market.macro`, the same
    way `refresh._build_worklist` does -- which is the property being relied on here."""
    monkeypatch.setattr(macro, "_MOVERS", ())
    monkeypatch.setattr(macro, "_RATE_TILES", ())
    monkeypatch.setattr(macro, "_OIL_TILES", ())


@pytest.fixture(autouse=True)
def _reset_progress() -> None:
    """`refresh._progress` is module-level and shared across the whole process; the freshness report
    embeds it, so a leftover record from another test would leak into these assertions."""
    refresh._progress = refresh.RefreshProgress()


@pytest.fixture(autouse=True)
def _block_real_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same block, and for the same reason, as `tests/test_market_refresh.py::_block_real_network`:
    patched at the `httpx` transport rather than the raw socket, because blocking sockets outright
    also breaks the `socketpair` that `TestClient`'s event loop needs for non-network reasons. The
    strictly stronger socket-level block is applied by `TestNoNetwork`, which uses no client."""
    import httpx

    def _blocked(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"test_data_freshness.py attempted a real HTTP request: {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked)


@pytest.fixture
def client(settings: Settings) -> TestClient:
    """A bare app holding only this router.

    `settings` is depended on rather than merely available: it is what redirects every store, cache
    and vault path into `tmp_path`, and without it this endpoint would read the developer's real
    ledger and vault. The conftest fixture also sets `INVDASH_AUTH_ENABLED=0`, so no login is needed.
    """
    app = FastAPI()
    app.include_router(data_admin.router)
    return TestClient(app)


def _sources(body: dict[str, object]) -> dict[str, dict[str, object]]:
    rows = body["sources"]
    assert isinstance(rows, list)
    return {row["key"]: row for row in rows}


# ---------------------------------------------------------------------------
# POST /api/market/refresh
# ---------------------------------------------------------------------------


class TestRefreshEndpoint:
    @pytest.fixture(autouse=True)
    def _record_calendar_warm(self, monkeypatch: pytest.MonkeyPatch) -> list[Settings | None]:
        """`calendar.warm` starts a daemon thread that would hit the blocked network; record the call
        instead so the pairing with the sweep is asserted, not merely tolerated."""
        calls: list[Settings | None] = []
        monkeypatch.setattr(data_admin.market_calendar, "warm", lambda cfg=None: calls.append(cfg))
        self._calendar_warms = calls
        return calls

    def test_a_press_of_the_button_also_warms_the_calendar(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The sweep never touches the event calendar, so the endpoint warms it itself -- but only on
        a real start: a second press while a sweep runs must not fire a second warm either."""
        monkeypatch.setattr(refresh, "refresh_market_data", lambda cfg=None: True)
        client.post("/api/market/refresh")
        assert len(self._calendar_warms) == 1

        monkeypatch.setattr(refresh, "refresh_market_data", lambda cfg=None: False)
        assert client.post("/api/market/refresh").json()["reason"] == "already_running"
        assert len(self._calendar_warms) == 1

    def test_a_press_of_the_button_starts_a_sweep_and_says_so(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        started: list[bool] = []

        def _fake_start(cfg: Settings | None = None) -> bool:
            started.append(True)
            return True

        monkeypatch.setattr(refresh, "refresh_market_data", _fake_start)

        response = client.post("/api/market/refresh")

        assert response.status_code == 202
        body = response.json()
        assert body["started"] is True
        assert body["reason"] is None
        assert started == [True]
        # The record is embedded so the caller does not need a second round trip to render progress.
        assert body["status"]["running"] is False
        assert set(body["status"]) >= {"running", "queued", "refreshed", "failed", "complete"}

    def test_a_second_press_while_a_sweep_runs_is_202_with_already_running_not_409(
        self, client: TestClient
    ) -> None:
        """409 would render as a failure in the frontend for a request that got exactly what it asked
        for -- fresh data already on its way. The lock is held directly here, which is the real
        condition `refresh_market_data` refuses on, rather than through a second live sweep thread.
        """
        assert refresh._sweep_lock.acquire(blocking=False)
        try:
            response = client.post("/api/market/refresh")
        finally:
            refresh._sweep_lock.release()

        assert response.status_code == 202
        body = response.json()
        assert body["started"] is False
        assert body["reason"] == "already_running"

    def test_the_real_sweep_is_reachable_through_the_endpoint_without_touching_the_network(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No fake on `refresh_market_data` at all -- this presses the button for real, on an empty
        tmp store with no macro proxies, and waits for the daemon thread to finish. The `httpx` block
        in `_block_real_http` is what makes it safe: a sweep that tried to fetch would fail loudly.
        """
        monkeypatch.setattr(macro, "build_snapshot", lambda cfg, **kwargs: None)
        monkeypatch.setattr(refresh, "_REQUEST_DELAY_SECONDS", 0.0)
        # The social watchlist is frozen from `macro._MOVERS` at import time, so emptying that
        # constant (as `_no_macro_proxies` does) does not reach it -- and a real sweep would
        # otherwise attempt one blocked StockTwits call per mover.
        monkeypatch.setattr(refresh, "_SOCIAL_WATCHLIST", ())

        response = client.post("/api/market/refresh")

        assert response.status_code == 202
        assert response.json()["started"] is True
        assert refresh._sweep_lock.acquire(timeout=5.0)
        refresh._sweep_lock.release()
        assert refresh.status()["complete"] is True


# ---------------------------------------------------------------------------
# The wire contract
# ---------------------------------------------------------------------------


class TestWireContract:
    _EXPECTED_KEYS = [
        "bars_daily",
        "bars_intraday",
        "macro_snapshot",
        "calendar_events",
        "fundamentals_edgar",
        "institutions_filings",
        "news",
        "social_snapshots",
        "live_quotes",
        "ledger",
        "persona_corpus",
    ]

    _EXPECTED_CLASSES = {
        "bars_daily": "day_frame",
        "bars_intraday": "intraday",
        "macro_snapshot": "day_frame",
        "calendar_events": "day_frame",
        "fundamentals_edgar": "day_frame",
        "institutions_filings": "day_frame",
        "news": "day_frame",
        "social_snapshots": "day_frame",
        "live_quotes": "intraday",
        "ledger": "local",
        "persona_corpus": "day_frame",
    }

    def test_all_eleven_keys_are_present_in_exactly_the_contracted_order(
        self, client: TestClient
    ) -> None:
        body = client.get("/api/data/freshness").json()
        assert [row["key"] for row in body["sources"]] == self._EXPECTED_KEYS

    def test_every_row_carries_the_full_field_set(self, client: TestClient) -> None:
        body = client.get("/api/data/freshness").json()
        expected = {
            "key",
            "freshness_class",
            "policy",
            "provider",
            "last_updated",
            "age_seconds",
            "status",
            "detail",
            "refreshable",
            "enabled",
        }
        for row in body["sources"]:
            assert set(row) == expected, row["key"]
            assert isinstance(row["detail"], str) and row["detail"], row["key"]
            assert isinstance(row["refreshable"], bool)
            assert isinstance(row["enabled"], bool)

    def test_class_policy_and_status_only_ever_take_values_from_their_closed_sets(
        self, client: TestClient
    ) -> None:
        body = client.get("/api/data/freshness").json()
        for row in body["sources"]:
            assert row["freshness_class"] in freshness.FRESHNESS_CLASSES, row
            assert row["policy"] in freshness.POLICIES, row
            assert row["status"] in freshness.STATUSES, row

    def test_each_key_is_pinned_to_its_own_freshness_class(self, client: TestClient) -> None:
        rows = _sources(client.get("/api/data/freshness").json())
        for key, expected in self._EXPECTED_CLASSES.items():
            assert rows[key]["freshness_class"] == expected, key

    def test_refreshable_is_true_only_for_what_the_fetch_button_actually_sweeps(
        self, client: TestClient
    ) -> None:
        """`calendar_events` is the interesting one: `refresh._sweep` itself never calls
        `calendar.warm`, so the row is refreshable only because `POST /api/market/refresh` calls
        `warm` alongside the sweep -- pinned by `test_a_press_of_the_button_also_warms_the_calendar`.
        """
        rows = _sources(client.get("/api/data/freshness").json())
        refreshable = {key for key, row in rows.items() if row["refreshable"]}
        assert refreshable == {"bars_daily", "macro_snapshot", "social_snapshots", "calendar_events"}
        assert "calendar" in rows["calendar_events"]["detail"]

    def test_the_report_carries_the_sweep_record_and_the_live_block(self, client: TestClient) -> None:
        body = client.get("/api/data/freshness").json()
        assert set(body) == {"as_of", "sources", "refresh", "live"}
        assert set(body["refresh"]) == set(refresh.status())
        assert set(body["live"]) >= {
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

    def test_as_of_is_a_parseable_utc_instant(self, client: TestClient) -> None:
        body = client.get("/api/data/freshness").json()
        parsed = dt.datetime.fromisoformat(body["as_of"])
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == dt.timedelta(0)

    def test_the_sweep_policy_follows_the_startup_flag(self, settings: Settings) -> None:
        """`policy` is what tells a reader whether a source refreshes itself on boot or only when
        they press the button, so it has to track the flag rather than being a fixed label.
        """
        rows = {row["key"]: row for row in freshness.report(settings)["sources"]}
        assert rows["bars_daily"]["policy"] == "on_demand"  # the conftest fixture pins the flag off

        on_boot = settings.model_copy(update={"refresh_on_startup": True})
        rows = {row["key"]: row for row in freshness.report(on_boot)["sources"]}
        assert rows["bars_daily"]["policy"] == "startup_sweep"
        assert rows["macro_snapshot"]["policy"] == "startup_sweep"
        assert rows["calendar_events"]["policy"] == "startup_sweep"


# ---------------------------------------------------------------------------
# bars_daily -- the one row with a real per-symbol computation
# ---------------------------------------------------------------------------


class TestBarsDaily:
    def test_symbols_synced_through_the_latest_settled_session_read_as_fresh(
        self, settings: Settings
    ) -> None:
        session = refresh._latest_settled_session(dt.datetime.now(dt.UTC))
        session_ts = dt.datetime(session.year, session.month, session.day, tzinfo=dt.UTC)
        _hold(settings, "AAA", "BBB")
        _seed_bar(settings, "AAA", ts=session_ts)
        _seed_bar(settings, "BBB", ts=session_ts)

        row = {r["key"]: r for r in freshness.report(settings)["sources"]}["bars_daily"]

        assert row["status"] == "fresh"
        assert row["detail"] == f"2 of 2 tracked symbols current through {session.isoformat()}"
        assert row["last_updated"] is not None
        assert row["age_seconds"] is not None

    def test_one_lagging_symbol_makes_the_row_stale_and_the_detail_says_how_many(
        self, settings: Settings
    ) -> None:
        session = refresh._latest_settled_session(dt.datetime.now(dt.UTC))
        session_ts = dt.datetime(session.year, session.month, session.day, tzinfo=dt.UTC)
        _hold(settings, "AAA", "BBB")
        _seed_bar(settings, "AAA", ts=session_ts)
        _seed_bar(settings, "BBB", ts=session_ts - dt.timedelta(days=30))

        row = {r["key"]: r for r in freshness.report(settings)["sources"]}["bars_daily"]

        assert row["status"] == "stale"
        assert row["detail"].startswith("1 of 2 tracked symbols")

    def test_nothing_tracked_reads_as_unknown_rather_than_as_fresh(self, settings: Settings) -> None:
        """An empty tracked set is the absence of a measurement, not a clean bill of health -- the
        distinction this project's `MarketWarning` handling makes everywhere else."""
        row = {r["key"]: r for r in freshness.report(settings)["sources"]}["bars_daily"]

        assert row["status"] == "unknown"
        assert row["last_updated"] is None
        assert row["age_seconds"] is None

    def test_the_tracked_set_is_capped_so_one_page_load_cannot_scan_the_whole_store(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(freshness, "_MAX_TRACKED_SYMBOLS", 3)
        _hold(settings, *[f"S{i}" for i in range(10)])

        assert len(freshness._tracked_symbols(settings)) == 3


class TestBarsIntraday:
    def test_an_empty_store_reads_as_unknown(self, settings: Settings) -> None:
        row = {r["key"]: r for r in freshness.report(settings)["sources"]}["bars_intraday"]
        assert row["status"] == "unknown"
        assert "no 5m or 1h bars" in row["detail"]

    def test_a_stored_intraday_symbol_is_measured(self, settings: Settings) -> None:
        session = refresh._latest_settled_session(dt.datetime.now(dt.UTC))
        ts = dt.datetime(session.year, session.month, session.day, 15, 30, tzinfo=dt.UTC)
        _seed_bar(settings, "AAA", ts=ts, interval=Interval.FIVE_MIN)

        row = {r["key"]: r for r in freshness.report(settings)["sources"]}["bars_intraday"]

        assert row["status"] == "fresh"
        assert row["last_updated"] is not None


# ---------------------------------------------------------------------------
# Local and flag-gated sources
# ---------------------------------------------------------------------------


class TestLocalSources:
    def test_the_ledger_reads_fresh_from_its_own_file_mtime(self, settings: Settings) -> None:
        _hold(settings, "AAA")

        row = {r["key"]: r for r in freshness.report(settings)["sources"]}["ledger"]

        assert row["status"] == "fresh"
        assert row["freshness_class"] == "local"
        assert row["policy"] == "computed"
        assert row["last_updated"] is not None

    def test_a_missing_ledger_reads_unknown_rather_than_raising(self, settings: Settings) -> None:
        assert not settings.ledger_path.exists()

        row = {r["key"]: r for r in freshness.report(settings)["sources"]}["ledger"]

        assert row["status"] == "unknown"
        assert "no ledger database" in row["detail"]

    def test_social_snapshots_report_disabled_while_the_scheduler_is_off(
        self, settings: Settings
    ) -> None:
        row = {r["key"]: r for r in freshness.report(settings)["sources"]}["social_snapshots"]

        assert row["status"] == "disabled"
        assert row["policy"] == "manual"
        assert row["enabled"] is False

    def test_persona_corpus_counts_notes_it_can_see(self, settings: Settings) -> None:
        notes = settings.vault_dir / "influencers" / "creatorb" / "notes"
        notes.mkdir(parents=True)
        (notes / "2026-09-08-abc.md").write_text("note", encoding="utf-8")
        (notes / "2026-09-08-def.md").write_text("note", encoding="utf-8")

        row = {r["key"]: r for r in freshness.report(settings)["sources"]}["persona_corpus"]

        assert "2 notes across 1 personas" in row["detail"]
        assert row["last_updated"] is not None
        assert row["status"] == "disabled"  # persona_refresh_enabled is off by default


# ---------------------------------------------------------------------------
# The live block
# ---------------------------------------------------------------------------


class TestLiveBlock:
    def test_an_absent_livefeed_module_falls_back_to_a_complete_block_not_an_error(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`app.market.livefeed` is owned by a different change and may simply not be present. The
        `None` entry in `sys.modules` is what makes `importlib.import_module` raise `ImportError` for
        a module that does exist; the `delattr` covers the case where it has already been imported
        and bound as an attribute of the `app.market` package.
        """
        import app.market

        monkeypatch.delattr(app.market, "livefeed", raising=False)
        monkeypatch.setitem(sys.modules, "app.market.livefeed", None)

        body = freshness.report(settings)

        assert body["live"] == {
            "enabled": settings.paperlive_enabled,
            "transport": settings.paperlive_transport,
            "running": False,
            "healthy": None,
            "watched": 0,
            "symbols": [],
            "market_state": None,
            "last_snapshot_at": None,
            "started_at": None,
        }
        row = {r["key"]: r for r in body["sources"]}["live_quotes"]
        assert row["status"] in {"unknown", "disabled"}
        assert row["policy"] == "streaming"

    def test_a_livefeed_whose_status_raises_falls_back_too(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A present-but-broken feed is a different failure from an absent one and must degrade the
        same way: the block still renders, complete, saying the feed is not running."""

        def _boom() -> dict[str, object]:
            raise RuntimeError("the feed exploded")

        module = ModuleType("app.market.livefeed")
        module.status = _boom  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "app.market.livefeed", module)

        live = freshness._live_status(settings)

        assert live["running"] is False
        assert live["healthy"] is None
        assert live["transport"] == settings.paperlive_transport

    def test_a_livefeed_returning_something_other_than_a_dict_falls_back(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = ModuleType("app.market.livefeed")
        module.status = lambda: "running"  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "app.market.livefeed", module)

        assert freshness._live_status(settings)["running"] is False

    def test_a_partial_livefeed_payload_is_filled_in_rather_than_shipped_short(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other side of this seam is being written concurrently; a missing key there must not
        become a missing key on the wire that the frontend then reads as `undefined`."""
        module = ModuleType("app.market.livefeed")
        module.status = lambda: {"running": True, "healthy": True, "watched": 3}  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "app.market.livefeed", module)

        live = freshness._live_status(settings)

        assert live["running"] is True
        assert live["watched"] == 3
        assert live["symbols"] == []  # filled in from the fallback
        assert live["transport"] == settings.paperlive_transport

    def test_the_row_follows_the_feeds_own_enabled_flag_not_the_paperlive_setting(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`app.market.livefeed` owns its own on/off switch and reports it as `enabled`; that is a
        different setting from `Settings.paperlive_enabled`. Reading the row from one while the
        `live` block beside it reports the other made the page contradict itself -- observed against
        the real store, where the block said `enabled: false` and the row said "the live feed is
        enabled but is not reporting itself as running".
        """
        assert settings.paperlive_enabled is True  # the assertion only bites while the two disagree

        module = ModuleType("app.market.livefeed")
        module.status = lambda: {"enabled": False, "running": False, "healthy": None}  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "app.market.livefeed", module)

        body = freshness.report(settings)
        row = {r["key"]: r for r in body["sources"]}["live_quotes"]

        assert body["live"]["enabled"] is False
        assert row["enabled"] is False
        assert row["status"] == "disabled"

    def test_a_running_healthy_feed_reads_as_live(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = ModuleType("app.market.livefeed")
        module.status = lambda: {  # type: ignore[attr-defined]
            "enabled": True,
            "transport": "stream",
            "running": True,
            "healthy": True,
            "watched": 2,
            "symbols": ["AAPL", "MSFT"],
            "market_state": "REGULAR",
            "last_snapshot_at": dt.datetime.now(dt.UTC).isoformat(),
            "started_at": dt.datetime.now(dt.UTC).isoformat(),
        }
        monkeypatch.setitem(sys.modules, "app.market.livefeed", module)

        row = {r["key"]: r for r in freshness.report(settings)["sources"]}["live_quotes"]

        assert row["status"] == "live"
        assert row["last_updated"] is not None


# ---------------------------------------------------------------------------
# Honest unknowns and fail-soft
# ---------------------------------------------------------------------------


class TestHonestUnknowns:
    def test_the_four_shared_cache_sources_say_unknown_and_say_why(self, settings: Settings) -> None:
        """`app.market.cache.CachingTransport` keys entries by a hash of the URL and stores no URL in
        them, and macro, the calendar, EDGAR fundamentals and news all share one root with the Yahoo
        bar fetches -- so the newest mtime there names no source. A number here would be a guess.
        """
        rows = {r["key"]: r for r in freshness.report(settings)["sources"]}
        for key in ("macro_snapshot", "calendar_events", "fundamentals_edgar", "news"):
            assert rows[key]["status"] == "unknown", key
            assert rows[key]["last_updated"] is None, key
            assert "cannot be attributed" in rows[key]["detail"], key

    def test_a_missing_edgar_cache_directory_is_unknown_not_a_500(self, client: TestClient) -> None:
        response = client.get("/api/data/freshness")

        assert response.status_code == 200
        row = _sources(response.json())["institutions_filings"]
        assert row["status"] == "unknown"
        assert "no EDGAR cache on disk" in row["detail"]

    def test_a_present_edgar_cache_is_measured_from_its_own_root(self, settings: Settings) -> None:
        entry = settings.cache_dir / "edgar" / "ab" / "abc.json"
        entry.parent.mkdir(parents=True)
        entry.write_text("{}", encoding="utf-8")

        row = {r["key"]: r for r in freshness.report(settings)["sources"]}["institutions_filings"]

        assert row["status"] == "fresh"
        assert row["last_updated"] is not None

    def test_the_macro_row_reports_this_processs_own_warm_when_a_sweep_has_run(
        self, settings: Settings
    ) -> None:
        refresh._progress = refresh.RefreshProgress(
            macro_snapshot="ok", finished_at=dt.datetime.now(dt.UTC)
        )

        row = {r["key"]: r for r in freshness.report(settings)["sources"]}["macro_snapshot"]

        assert row["status"] == "fresh"
        assert "warmed by this process" in row["detail"]

    def test_a_measurement_that_raises_degrades_to_one_unknown_row_not_a_500(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(_cfg: Settings) -> list[str]:
            raise RuntimeError("the parquet store is on fire")

        # Patched at the helper `_measure_bars_daily` calls rather than at the spec itself: the specs
        # are frozen dataclasses (deliberately -- the catalog is a constant), and this also exercises
        # the real path, where the exception comes from inside a measurement rather than from a stub
        # standing in for one.
        monkeypatch.setattr(freshness, "_tracked_symbols", _boom)

        response = client.get("/api/data/freshness")

        assert response.status_code == 200
        rows = _sources(response.json())
        assert rows["bars_daily"]["status"] == "unknown"
        assert "the parquet store is on fire" in rows["bars_daily"]["detail"]
        # Every other row still rendered -- one broken source costs one row, not the page.
        assert len(rows) == 11
        assert rows["ledger"]["status"] in {"fresh", "unknown"}


class TestNoNetwork:
    def test_building_the_report_makes_no_socket_connection_at_all(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The strongest available proof, and the reason this test uses no `TestClient`: blocking
        `socket.socket.connect` outright also breaks the `socketpair` an event loop needs on Windows,
        so it can only be done where no loop is running. `freshness.report` is a plain function, so
        here it can be.
        """
        _hold(settings, "AAA")
        _seed_bar(settings, "AAA", ts=dt.datetime.now(dt.UTC) - dt.timedelta(days=3))
        (settings.cache_dir / "edgar" / "ab").mkdir(parents=True)
        (settings.cache_dir / "edgar" / "ab" / "x.json").write_text("{}", encoding="utf-8")

        def _blocked(self: socket.socket, address: object) -> None:
            raise AssertionError(f"freshness.report attempted a network connection to {address!r}")

        monkeypatch.setattr(socket.socket, "connect", _blocked)

        body = freshness.report(settings)

        assert len(body["sources"]) == 11

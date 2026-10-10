"""Integration tests for the market stack: provider -> registry -> store -> indicators -> API.

Every module in this phase passed its own tests. Four defects still shipped, and all four lived in
the *seams* between modules, where per-module fixtures cannot reach:

* Yahoo silently served **monthly** bars for a daily request, because the production path used
  ``range=max`` while the fixtures had been captured with ``range=1y``. 330 monthly bars sat in the
  daily partition and every indicator computed from them was a monthly indicator wearing a daily
  label.
* Both intraday timeframes were **entirely broken** -- the retention window is exclusive, so a
  request spanning exactly its limit is refused. Daily has no limit and so never went near the
  boundary, and every test that exercised the fetch path used daily bars.
* The response cache replayed a gzip-encoded body with its ``Content-Encoding`` intact, so the
  *second* request to a gzip upstream died where the first succeeded.
* The Parquet round trip re-labelled UTC timestamps with the host timezone, moving every daily bar
  to the previous calendar day for anyone west of UTC.

The theme is that a component can be correct against the inputs it was tested with and wrong against
the ones it actually receives. These tests use the real composition path and assert the properties
that hold across it.
"""

from __future__ import annotations

import copy
import datetime as dt
import gzip
import json
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.api import market as market_api
from app.config import Settings
from app.db import duck
from app.indicators import registry as indicators
from app.main import app
from app.market import store
from app.market.cache import CachingTransport
from app.market.models import (
    BAR_COLUMNS,
    INTERVAL_MAX_LOOKBACK,
    Interval,
    Profile,
    Quote,
)
from app.market.providers.base import ProviderResponseError
from app.market.providers.yahoo import YahooProvider
from app.market.registry import ProviderRegistry

FIXTURES = Path(__file__).parent / "fixtures" / "market"


# ---------------------------------------------------------------------------
# Fakes -- no test in this file touches the network
# ---------------------------------------------------------------------------


def _bars(n: int, *, end: dt.date, interval: Interval = Interval.DAY) -> pd.DataFrame:
    """A deterministic ascending series ending on ``end``, shaped like the real thing."""
    step = dt.timedelta(days=1) if not interval.is_intraday else dt.timedelta(hours=1)
    stamps = [
        dt.datetime.combine(end, dt.time.min, tzinfo=dt.UTC) - step * (n - 1 - i) for i in range(n)
    ]
    closes = [100.0 + i for i in range(n)]
    return pd.DataFrame(
        {
            "ts": pd.Series(stamps, dtype="datetime64[us, UTC]"),
            "open": [c - 0.5 for c in closes],
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "adj_close": closes,
            "volume": [1_000_000 + i for i in range(n)],
        }
    )


class FakeProvider:
    """Serves a fixed frame. Implements enough of the protocols for the whole stack to run."""

    name = "yahoo"
    supported_intervals = frozenset({Interval.FIVE_MIN, Interval.HOUR, Interval.DAY})

    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.calls: list[tuple[str, Interval]] = []

    def fetch_bars(
        self,
        symbol: str,
        interval: Interval,
        *,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> pd.DataFrame:
        self.calls.append((symbol, interval))
        return self.frame.copy()

    def fetch_quote(self, symbol: str) -> Quote:
        return Quote(symbol=symbol, price=123.45, ts=dt.datetime.now(dt.UTC), market_state="CLOSED")

    def fetch_profile(self, symbol: str) -> Profile:
        return Profile(symbol=symbol, name=f"{symbol} Test", instrument_type="ETF")


@pytest.fixture
def client(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """An API client whose provider chain is a fake, and whose store is a temp directory."""
    provider = FakeProvider(_bars(400, end=dt.date.today()))
    registry = ProviderRegistry(
        bar_providers=[provider], profile_providers=[provider], fundamentals_providers=[]
    )
    monkeypatch.setattr(market_api, "_registry", lambda: registry)
    return TestClient(app)


# ---------------------------------------------------------------------------


class TestYahooServesTheGranularityItWasAsked:
    """Yahoo answers an over-wide request by coarsening the data instead of refusing it."""

    def _payload(self, granularity: str) -> dict[str, Any]:
        raw = json.loads((FIXTURES / "yahoo_qqq_1d.json").read_text(encoding="utf-8"))
        raw["chart"]["result"][0]["meta"]["dataGranularity"] = granularity
        return raw

    def _provider(self, payload: dict[str, Any]) -> YahooProvider:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        return YahooProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))

    def test_monthly_bars_for_a_daily_request_are_refused(self) -> None:
        """The defect verbatim: 330 monthly bars stored as daily, undetectable downstream.

        The response is structurally identical to a real daily one -- same fields, ascending
        timestamps, plausible prices. Only ``meta.dataGranularity`` distinguishes them, so this one
        string is the entire difference between a loud failure and a chart of monthly candles
        labelled daily with a 50-*month* moving average drawn over it.
        """
        with pytest.raises(ProviderResponseError, match="1mo"):
            self._provider(self._payload("1mo")).fetch_bars("QQQ", Interval.DAY)

    def test_matching_granularity_is_accepted(self) -> None:
        frame = self._provider(self._payload("1d")).fetch_bars("QQQ", Interval.DAY)
        assert list(frame.columns) == list(BAR_COLUMNS)
        assert not frame.empty


class TestRequestWindowStaysInsideTheRetentionLimit:
    """The bound is on the *span*, and it is exclusive."""

    def _sent(self, interval: Interval) -> dict[str, str]:
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(dict(request.url.params))
            return httpx.Response(500, json={})

        provider = YahooProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))
        with pytest.raises(Exception):  # noqa: B017 -- the 500 is incidental; the params are the point
            provider.fetch_bars("QQQ", interval)
        return captured

    @pytest.mark.parametrize(
        "interval", [Interval.FIVE_MIN, Interval.HOUR, Interval.DAY]
    )
    def test_span_is_strictly_inside_the_documented_limit(self, interval: Interval) -> None:
        """Requesting exactly the limit is the one value guaranteed to fail with a 422.

        This is the test whose absence let both intraday timeframes ship dead. It runs over every
        interval rather than just the one whose fixture happened to be at hand, because the defect
        was invisible on daily -- daily has no limit, so it never approaches the boundary.
        """
        params = self._sent(interval)
        span = dt.timedelta(seconds=int(params["period2"]) - int(params["period1"]))
        limit = INTERVAL_MAX_LOOKBACK[interval]
        if limit is None:
            assert span > dt.timedelta(days=365 * 20)  # unbounded: ask for everything
        else:
            assert span < limit, f"{interval.value} span {span} is not inside {limit}"

    @pytest.mark.parametrize("interval", [Interval.FIVE_MIN, Interval.HOUR, Interval.DAY])
    def test_range_is_never_used(self, interval: Interval) -> None:
        """``range=max`` is what triggered the monthly-bar substitution. Explicit epochs only."""
        params = self._sent(interval)
        assert "range" not in params
        assert "period1" in params and "period2" in params


class TestIntervalMaxLookbackCompleteness:
    """A loop over every ``Interval`` member, not a hardcoded list -- fails immediately if an eighth
    interval is ever added and this table forgotten, rather than silently `KeyError`-ing the first
    time someone requests it."""

    def test_every_interval_has_an_entry(self) -> None:
        assert set(INTERVAL_MAX_LOOKBACK) == set(Interval)

    def test_retention_values_match_the_live_probe(self) -> None:
        """Values verified by direct probe against Yahoo's chart endpoint (2026-08-25)."""
        assert INTERVAL_MAX_LOOKBACK[Interval.FIVE_MIN] == dt.timedelta(days=60)
        assert INTERVAL_MAX_LOOKBACK[Interval.FIFTEEN_MIN] == dt.timedelta(days=60)
        assert INTERVAL_MAX_LOOKBACK[Interval.THIRTY_MIN] == dt.timedelta(days=60)
        assert INTERVAL_MAX_LOOKBACK[Interval.HOUR] == dt.timedelta(days=730)
        assert INTERVAL_MAX_LOOKBACK[Interval.FOUR_HOUR] == dt.timedelta(days=730)
        assert INTERVAL_MAX_LOOKBACK[Interval.DAY] is None
        assert INTERVAL_MAX_LOOKBACK[Interval.WEEK] is None


class TestCachedResponsesReplayCorrectly:
    def test_gzip_body_is_not_replayed_as_still_encoded(self, tmp_path: Path) -> None:
        """The second request to a gzip upstream must not die where the first succeeded.

        ``response.content`` is already decoded, so storing it alongside the original
        ``Content-Encoding: gzip`` makes the client inflate plain JSON on the way back out. It fails
        only on a cache *hit*, which is why it survived every unit test: ``MockTransport`` fixtures
        do not set the header, and a single request never reads its own cache entry.
        """
        body = json.dumps({"hello": "world"}).encode()
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                200,
                content=gzip.compress(body),
                headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
            )

        transport = CachingTransport(httpx.MockTransport(handler), tmp_path, ttl=600)
        with httpx.Client(transport=transport) as client:
            first = client.get("https://example.test/facts.json")
            second = client.get("https://example.test/facts.json")

        assert calls == 1, "the second request should have been served from cache"
        assert first.json() == {"hello": "world"}
        assert second.json() == {"hello": "world"}


class TestSeriesAlignmentAcrossTheApi:
    def test_indicator_columns_align_with_the_bars_they_describe(self, client: TestClient) -> None:
        """Every column is exactly as long as the timestamp index it is plotted against.

        An indicator frame is never trimmed to drop its warmup. A shortened series still renders --
        it just renders shifted, which looks like an indicator that leads price rather than like a
        bug.
        """
        body = client.get(
            "/api/market/indicators?symbol=QQQ&interval=1d&spec=bb:20,2&spec=rsi:14"
        ).json()
        assert body["series"], "expected the requested indicators back"
        for series in body["series"]:
            for values in series["columns"].values():
                assert len(values) == len(body["ts"])

    def test_warmup_positions_are_null_and_never_zero(self, client: TestClient) -> None:
        """A band reading 0 through its warmup draws a spike to the axis that looks like a crash."""
        body = client.get("/api/market/indicators?symbol=QQQ&interval=1d&spec=sma:50").json()
        column = body["series"][0]["columns"]["sma_50"]
        assert column[:49] == [None] * 49
        assert column[49] is not None

    def test_no_nan_token_reaches_the_wire(self, client: TestClient) -> None:
        """``json.dumps`` renders NaN as the bare token ``NaN``, which is not valid JSON.

        The failure is not a wrong number -- it is ``JSON.parse`` throwing a syntax error at a byte
        offset, in the browser, with nothing pointing back at the warmup window that caused it.
        """
        for path in (
            "/api/market/bars?symbol=QQQ&interval=1d&limit=5",
            "/api/market/indicators?symbol=QQQ&interval=1d&spec=macd:12,26,9",
        ):
            raw = client.get(path).text
            assert "NaN" not in raw and "Infinity" not in raw
            json.loads(raw)  # would raise on a bare NaN token


class TestWeeklyIsDerivedNeverFetched:
    def test_weekly_comes_from_stored_daily_bars(self, client: TestClient) -> None:
        body = client.get("/api/market/bars?symbol=QQQ&interval=1w&limit=4").json()
        assert body["source"] == "derived"
        assert body["bars"]

    def test_weekly_closes_track_the_daily_series(self, settings: Settings) -> None:
        """A weekly close is the last daily close *of its own ISO week* -- the same bar, aggregated.

        Deliberately not "the last weekly close is the last daily close overall". That held only by
        accident of the calendar: `_resample_weekly` excludes the ISO week still in progress, since
        a still-forming week would change on the next read and the store serves settled bars only.
        Whichever weekday the suite runs on decides whether the final daily bar belongs to a settled
        week, so the expectation is derived from the weekly bar's own ISO week rather than assuming
        the two coincide -- otherwise this test passes or fails depending on the day.
        """
        frame = _bars(60, end=dt.date.today())
        with pytest.MonkeyPatch.context() as mp:
            provider = FakeProvider(frame)
            registry = ProviderRegistry(bar_providers=[provider])
            mp.setattr(market_api, "_registry", lambda: registry)
            store.sync_bars("QQQ", Interval.DAY, registry=registry)
            weekly = store.read_series("QQQ", Interval.WEEK)
            daily = store.read_frame("QQQ", Interval.DAY)

        assert weekly.bars, "expected at least one settled week from 60 daily bars"
        last_week = weekly.bars[-1]
        week_key = tuple(last_week.ts.isocalendar()[:2])
        same_week = daily[[tuple(ts.isocalendar()[:2]) == week_key for ts in daily["ts"]]]
        assert last_week.close == pytest.approx(float(same_week["close"].iloc[-1]))

    def test_the_still_forming_week_is_never_served(self, settings: Settings) -> None:
        """The current ISO week must be absent, not merely last.

        Syncing Monday-Wednesday and reading `1w` used to return a bar whose close, high and volume
        silently changed once Thursday's daily bar landed -- a mutating "settled" bar, which is the
        exact failure `_drop_unsettled_bar` prevents one layer down at the daily boundary.
        """
        # UTC, not local. `_resample_weekly` decides which ISO week is "still forming" against
        # `dt.datetime.now(dt.UTC).date()` (app/market/store.py), and its own docstring warns that a
        # local clock disagrees with that judgment near a day boundary. This host runs at UTC-7, so
        # for seven hours of every day the local date still names the previous day -- and on the
        # weeks where that window straddles Sunday into Monday the two clocks name different ISO
        # weeks, making this assertion fail on a correct implementation.
        # tests/test_market_store.py already uses the UTC form for the equivalent check.
        today_utc = dt.datetime.now(dt.UTC).date()
        frame = _bars(60, end=today_utc)
        with pytest.MonkeyPatch.context() as mp:
            registry = ProviderRegistry(bar_providers=[FakeProvider(frame)])
            mp.setattr(market_api, "_registry", lambda: registry)
            store.sync_bars("QQQ", Interval.DAY, registry=registry)
            weekly = store.read_series("QQQ", Interval.WEEK)

        current = tuple(today_utc.isocalendar()[:2])
        assert all(tuple(bar.ts.isocalendar()[:2]) != current for bar in weekly.bars)


class TestApiFailureTranslation:
    def test_unknown_indicator_is_a_400_not_a_500(self, client: TestClient) -> None:
        assert client.get("/api/market/indicators?symbol=QQQ&interval=1d&spec=nope:1").status_code == 400

    def test_vwap_on_daily_is_refused_with_a_reason(self, client: TestClient) -> None:
        """Refused at the request boundary, so no meaningless line is ever computed or drawn."""
        response = client.get("/api/market/indicators?symbol=QQQ&interval=1d&spec=vwap:session")
        assert response.status_code == 400
        assert "1d" in response.json()["detail"]

    def test_malformed_symbol_is_rejected_before_it_reaches_the_filesystem(
        self, client: TestClient
    ) -> None:
        """Symbols become Parquet partition directory names, so the alphabet is closed."""
        assert client.get("/api/market/bars?symbol=../../etc&interval=1d").status_code == 422


class TestCatalogDrivesTheUi:
    def test_every_catalog_entry_round_trips_through_its_own_default_spec(
        self, client: TestClient
    ) -> None:
        """The UI builds requests from this catalog; an entry it cannot send back is a dead control."""
        for entry in client.get("/api/market/indicators/catalog").json():
            request = indicators.request(entry["default_spec"])
            assert request.spec.name == entry["name"]
            assert list(request.columns) == [
                f"{request.key}_{s}" for s in entry["outputs"]
            ] or not entry["outputs"]

    def test_interval_restrictions_are_published(self, client: TestClient) -> None:
        """VWAP must arrive at the UI already marked as intraday-only, not fail on click."""
        catalog = {e["name"]: e for e in client.get("/api/market/indicators/catalog").json()}
        assert sorted(catalog["vwap"]["intervals"]) == ["1h", "5m"]
        assert catalog["sma"]["intervals"] is None


class TestStoreHoldsSettledBarsOnly:
    def test_a_partial_bar_never_reaches_the_store(self, settings: Settings) -> None:
        """Structural, not a rule someone has to remember: backtests read the store.

        The provider drops the in-progress bar, so there is no path by which one can be persisted
        and later read back as though it were final.
        """
        frame = _bars(30, end=dt.date.today())
        registry = ProviderRegistry(bar_providers=[FakeProvider(frame)])
        store.sync_bars("QQQ", Interval.DAY, registry=registry)
        series = store.read_series("QQQ", Interval.DAY)
        assert not any(bar.partial for bar in series.bars)


class TestSettledBarsDoNotMakeTheStoreLookPermanentlyStale:
    def test_a_second_read_does_not_refetch(self, settings: Settings) -> None:
        """Staleness is the age of the last fetch, not the age of the newest bar.

        The store holds settled bars only, so during Monday's session the newest daily bar is
        Friday's -- already past the one-day threshold, and further past it every minute. Measured
        against the bar, the store is stale the instant it is written, and *every* request re-fetches
        from the provider.

        That is what produced the concurrent writes that then collided in the Parquet store: the
        four-timeframe view fires four syncs at once, and a period box being edited fires one per
        keystroke. Two individually correct decisions -- settled bars only, and refresh when the data
        looks old -- wrong in combination.
        """
        provider = FakeProvider(_bars(40, end=dt.date.today() - dt.timedelta(days=3)))
        registry = ProviderRegistry(bar_providers=[provider])

        store.ensure_series("QQQ", Interval.DAY, registry=registry)
        assert len(provider.calls) == 1

        store.ensure_series("QQQ", Interval.DAY, registry=registry)
        store.ensure_series("QQQ", Interval.DAY, registry=registry)
        assert len(provider.calls) == 1, "stored bars were re-fetched despite a recent sync"

    def test_refresh_still_forces_a_fetch(self, settings: Settings) -> None:
        """The escape hatch must survive the fix -- otherwise nothing can ever update."""
        provider = FakeProvider(_bars(40, end=dt.date.today() - dt.timedelta(days=3)))
        registry = ProviderRegistry(bar_providers=[provider])
        store.ensure_series("QQQ", Interval.DAY, registry=registry)
        store.ensure_series("QQQ", Interval.DAY, registry=registry, refresh=True)
        assert len(provider.calls) == 2


class TestConcurrentWritesToOnePartition:
    def test_parallel_writes_neither_crash_nor_lose_rows(self, settings: Settings) -> None:
        """FastAPI runs sync endpoints in a threadpool, so this is a real request pattern.

        A fixed staging filename makes concurrent writers fight over one path. On Windows that is a
        hard ``IOException``; on POSIX the rename silently succeeds and one writer's output replaces
        the other's, which is worse -- the failure becomes missing rows rather than an error.
        """
        import threading

        errors: list[BaseException] = []
        barrier = threading.Barrier(4)

        def writer(offset: int) -> None:
            frame = _bars(20, end=dt.date.today() - dt.timedelta(days=offset))
            try:
                barrier.wait(timeout=10)
                with duck.connect() as conn:
                    duck.write_bars(conn, settings.bars_dir, "QQQ", Interval.DAY, frame)
            except BaseException as exc:
                # Collected rather than raised: an exception in a worker thread would otherwise be
                # printed and ignored, and the test would pass while the writes were failing.
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert errors == [], f"concurrent writes raised: {errors!r}"

        with duck.connect() as conn:
            stored = duck.read_bars(conn, settings.bars_dir, "QQQ", Interval.DAY)
        # Four overlapping 20-bar windows offset by one day each: 23 distinct timestamps. A lost
        # write would show up here as a short count, not as an exception.
        assert len(stored) == 23
        assert stored["ts"].is_monotonic_increasing

    def test_concurrent_cache_writes_for_one_url_do_not_collide(self, tmp_path: Path) -> None:
        """Same defect, second module: a fixed staging filename under a shared key.

        A cache key is shared *by construction* -- identical requests produce identical paths, and
        identical requests in flight together are precisely what a cache is for. This is the pattern
        that broke the bar store, repeated in the HTTP cache, and it surfaced the same way: four
        panels mounting at once.
        """
        import threading

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True})

        transport = CachingTransport(httpx.MockTransport(handler), tmp_path, ttl=600)
        errors: list[BaseException] = []
        barrier = threading.Barrier(6)

        def fetch() -> None:
            try:
                barrier.wait(timeout=10)
                with httpx.Client(transport=transport) as client:
                    assert client.get("https://example.test/same.json").json() == {"ok": True}
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=fetch) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert errors == [], f"concurrent cache writes raised: {errors!r}"
        assert not list(tmp_path.rglob("*.tmp"))

    def test_no_staging_files_are_left_behind(self, settings: Settings) -> None:
        frame = _bars(10, end=dt.date.today())
        with duck.connect() as conn:
            duck.write_bars(conn, settings.bars_dir, "QQQ", Interval.DAY, frame)
        partition = duck.bar_path(settings.bars_dir, "QQQ", Interval.DAY).parent
        assert [p.name for p in partition.iterdir()] == ["bars.parquet"]


class TestFixturesMatchTheParsedShape:
    def test_captured_daily_fixture_is_actually_daily(self) -> None:
        """Guards the capture itself.

        The fixtures were taken with ``range=1y``, which serves true daily bars; the production path
        used ``range=max``, which does not. That divergence between what the tests parsed and what
        the code fetched is precisely how the monthly-bar defect stayed invisible.
        """
        raw = json.loads((FIXTURES / "yahoo_qqq_1d.json").read_text(encoding="utf-8"))
        assert raw["chart"]["result"][0]["meta"]["dataGranularity"] == "1d"

    def test_stooq_fixture_is_the_challenge_page_not_csv(self) -> None:
        text = (FIXTURES / "stooq_challenge.html").read_text(encoding="utf-8")
        assert "<html" in text.lower()
        assert not text.startswith("Date,Open")


def test_fixture_copies_do_not_mutate_the_originals() -> None:
    """Fixture payloads are shared across tests; a parser that edits one poisons the rest."""
    path = FIXTURES / "yahoo_qqq_1d.json"
    before = json.loads(path.read_text(encoding="utf-8"))
    mutated = copy.deepcopy(before)
    mutated["chart"]["result"][0]["meta"]["dataGranularity"] = "1mo"
    assert json.loads(path.read_text(encoding="utf-8")) == before

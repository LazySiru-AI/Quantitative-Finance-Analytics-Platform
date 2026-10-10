"""Tests for the provider fallback registry and its on-disk HTTP cache.

No test in this file touches the network: bar/profile/fundamentals providers are hand-written fakes
whose failure mode is set by the test, and the caching transport is exercised over
`httpx.MockTransport`.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import httpx
import pandas as pd
import pytest

from app.db.duck import BAR_COLUMNS, Interval
from app.market.cache import CachingTransport
from app.market.models import BarSource, Profile, Quote
from app.market.providers.base import (
    ProviderUnavailable,
    RateLimited,
    SymbolNotFound,
    UnsupportedInterval,
)
from app.market.registry import ProviderRegistry, SymbolNotFoundWithContext

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _bars_frame(prices: list[float]) -> pd.DataFrame:
    base = dt.datetime(2026, 1, 5, tzinfo=dt.UTC)
    rows = [
        {
            "ts": base + dt.timedelta(days=i),
            "open": p,
            "high": p + 1,
            "low": p - 1,
            "close": p,
            "adj_close": p,
            "volume": 1000,
        }
        for i, p in enumerate(prices)
    ]
    return pd.DataFrame(rows, columns=list(BAR_COLUMNS))


class FakeBarProvider:
    """A `BarProvider` whose outcome is dictated by the test: `ok`, `not_found`, `unavailable`,
    `rate_limited` or `unsupported`."""

    def __init__(
        self,
        name: str,
        *,
        outcome: str = "ok",
        intervals: frozenset[Interval] | None = None,
        frame: pd.DataFrame | None = None,
    ) -> None:
        self.name = name
        self.supported_intervals = intervals if intervals is not None else frozenset({Interval.DAY})
        self.outcome = outcome
        self.frame = frame if frame is not None else _bars_frame([1.0, 2.0])
        self.calls: list[str] = []

    def fetch_bars(
        self, symbol: str, interval: Interval, *, start: dt.date | None = None, end: dt.date | None = None
    ) -> pd.DataFrame:
        self.calls.append(symbol)
        if self.outcome == "not_found":
            raise SymbolNotFound(f"{symbol} not found", provider=self.name)
        if self.outcome == "unavailable":
            raise ProviderUnavailable(f"{self.name} is down", provider=self.name)
        if self.outcome == "rate_limited":
            raise RateLimited(f"{self.name} rate limited", provider=self.name, retry_after=30.0)
        if self.outcome == "unsupported":
            raise UnsupportedInterval(f"{self.name} has no {interval.value}", provider=self.name)
        return self.frame


class FakeProfileProvider:
    def __init__(self, name: str, *, outcome: str = "ok") -> None:
        self.name = name
        self.outcome = outcome
        self.calls: list[str] = []

    def fetch_profile(self, symbol: str) -> Profile:
        self.calls.append(symbol)
        if self.outcome == "unavailable":
            raise ProviderUnavailable(f"{self.name} is down", provider=self.name)
        return Profile(symbol=symbol, name="Test Co", source=BarSource(self.name))

    def fetch_quote(self, symbol: str) -> Quote:
        self.calls.append(symbol)
        if self.outcome == "unavailable":
            raise ProviderUnavailable(f"{self.name} is down", provider=self.name)
        return Quote(symbol=symbol, price=1.23, ts=dt.datetime.now(dt.UTC), source=BarSource(self.name))


class FakeFundamentalsProvider:
    def __init__(self, name: str, *, outcome: str = "ok") -> None:
        self.name = name
        self.outcome = outcome

    def fetch_fundamentals(self, symbol: str) -> object:
        if self.outcome == "unavailable":
            raise ProviderUnavailable(f"{self.name} is down", provider=self.name)
        return {"symbol": symbol}


# ---------------------------------------------------------------------------
# Bar fallback
# ---------------------------------------------------------------------------


class TestBarFallback:
    def test_symbol_not_found_reraises_without_trying_next_provider(self) -> None:
        first = FakeBarProvider("yahoo", outcome="not_found")
        second = FakeBarProvider("stooq")
        registry = ProviderRegistry(bar_providers=(first, second))

        with pytest.raises(SymbolNotFound):
            registry.get_bars("ZZZZ", Interval.DAY)

        assert second.calls == []

    def test_symbol_not_found_after_an_earlier_provider_failure_keeps_that_context(self) -> None:
        """Provider A degrades (`ProviderUnavailable`, recorded as a warning/failure), provider B
        then says the ticker does not exist. Re-raising B's bare `SymbolNotFound` would silently
        discard A's failure -- the caller would see only "no such ticker" with no trace that the
        primary never actually weighed in, exactly the failure mode `providers/stooq.py`'s docstring
        warns about (a degraded fallback overruling a healthy primary). The terminal exception must
        still be a `SymbolNotFound` a caller can catch by that base type, just carrying more."""
        first = FakeBarProvider("yahoo", outcome="unavailable")
        second = FakeBarProvider("stooq", outcome="not_found")
        registry = ProviderRegistry(bar_providers=(first, second))

        with pytest.raises(SymbolNotFoundWithContext) as excinfo:
            registry.get_bars("ZZZZ", Interval.DAY)

        assert isinstance(excinfo.value, SymbolNotFound)  # still catchable by the base type
        assert len(excinfo.value.warnings) == 1
        assert excinfo.value.warnings[0].kind == "provider_fallback"
        assert "yahoo" in excinfo.value.warnings[0].message
        assert any("yahoo" in f for f in excinfo.value.failures)

    def test_symbol_not_found_with_no_prior_failures_carries_empty_context(self) -> None:
        first = FakeBarProvider("yahoo", outcome="not_found")
        registry = ProviderRegistry(bar_providers=(first,))

        with pytest.raises(SymbolNotFoundWithContext) as excinfo:
            registry.get_bars("ZZZZ", Interval.DAY)

        assert excinfo.value.warnings == []
        assert excinfo.value.failures == []

    def test_provider_unavailable_falls_through_with_a_fallback_warning(self) -> None:
        first = FakeBarProvider("yahoo", outcome="unavailable")
        second = FakeBarProvider("stooq")
        registry = ProviderRegistry(bar_providers=(first, second))

        fetch = registry.get_bars("QQQ", Interval.DAY)

        assert fetch.source == BarSource.STOOQ
        assert second.calls == ["QQQ"]
        assert len(fetch.warnings) == 1
        assert fetch.warnings[0].kind == "provider_fallback"
        assert "yahoo" in fetch.warnings[0].message

    def test_rate_limited_is_a_provider_unavailable_and_falls_through(self) -> None:
        first = FakeBarProvider("yahoo", outcome="rate_limited")
        second = FakeBarProvider("stooq")
        registry = ProviderRegistry(bar_providers=(first, second))

        fetch = registry.get_bars("QQQ", Interval.DAY)

        assert fetch.source == BarSource.STOOQ
        assert fetch.warnings[0].kind == "provider_fallback"

    def test_unsupported_interval_is_skipped_with_no_warning(self) -> None:
        stooq = FakeBarProvider("stooq", intervals=frozenset({Interval.DAY}), outcome="unsupported")
        yahoo = FakeBarProvider("yahoo", intervals=frozenset({Interval.FIVE_MIN, Interval.DAY}))
        registry = ProviderRegistry(bar_providers=(stooq, yahoo))

        fetch = registry.get_bars("QQQ", Interval.FIVE_MIN)

        assert fetch.source == BarSource.YAHOO
        assert fetch.warnings == []
        # stooq's supported_intervals already excludes 5m, so the registry should skip it before
        # ever calling fetch_bars -- it must not need the raised UnsupportedInterval to know that.
        assert stooq.calls == []

    def test_bar_fetch_carries_the_exchange_timezone_reported_on_the_frame(self) -> None:
        """`YahooProvider.fetch_bars` stashes the instrument's exchange timezone on
        `frame.attrs["exchange_timezone"]` -- there is no column for it in `BAR_COLUMNS`, and it is
        one scalar for the whole frame, not a per-row value. `get_bars` must read that back out onto
        `BarFetch` so `app.market.store` can use the instrument's own timezone for its intraday
        staleness gate instead of assuming America/New_York for every symbol."""
        frame = _bars_frame([1.0, 2.0])
        frame.attrs["exchange_timezone"] = "Asia/Tokyo"
        provider = FakeBarProvider("yahoo", frame=frame)
        registry = ProviderRegistry(bar_providers=(provider,))

        fetch = registry.get_bars("7203.T", Interval.DAY)

        assert fetch.exchange_timezone == "Asia/Tokyo"

    def test_bar_fetch_exchange_timezone_is_none_when_the_provider_does_not_report_one(self) -> None:
        provider = FakeBarProvider("stooq")  # never sets frame.attrs["exchange_timezone"]
        registry = ProviderRegistry(bar_providers=(provider,))

        fetch = registry.get_bars("AAPL", Interval.DAY)

        assert fetch.exchange_timezone is None

    def test_all_providers_failing_raises_mentioning_every_provider(self) -> None:
        first = FakeBarProvider("yahoo", outcome="unavailable")
        second = FakeBarProvider("stooq", outcome="unavailable")
        registry = ProviderRegistry(bar_providers=(first, second))

        with pytest.raises(ProviderUnavailable) as excinfo:
            registry.get_bars("QQQ", Interval.DAY)

        message = str(excinfo.value)
        assert "yahoo" in message
        assert "stooq" in message


class TestProfileAndFundamentalsFallback:
    def test_profile_provider_unavailable_falls_through(self) -> None:
        first = FakeProfileProvider("yahoo", outcome="unavailable")
        second = FakeProfileProvider("stooq")
        registry = ProviderRegistry(profile_providers=(first, second))

        profile = registry.get_profile("QQQ")

        assert profile.source == BarSource.STOOQ

    def test_fundamentals_all_unavailable_raises_with_provider_name(self) -> None:
        provider = FakeFundamentalsProvider("sec_edgar", outcome="unavailable")
        registry = ProviderRegistry(fundamentals_providers=(provider,))

        with pytest.raises(ProviderUnavailable, match="sec_edgar"):
            registry.get_fundamentals("AAPL")

    def test_no_providers_configured_raises_rather_than_crashing(self) -> None:
        registry = ProviderRegistry()

        with pytest.raises(ProviderUnavailable):
            registry.get_bars("QQQ", Interval.DAY)


# ---------------------------------------------------------------------------
# Caching transport
# ---------------------------------------------------------------------------


class TestCachingTransport:
    def test_second_identical_request_is_served_from_disk(self, tmp_path: Path) -> None:
        calls: list[httpx.URL] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url)
            return httpx.Response(200, json={"ok": True})

        transport = CachingTransport(httpx.MockTransport(handler), tmp_path / "http")
        client = httpx.Client(transport=transport)

        first = client.get("https://example.com/data", params={"b": "2", "a": "1"})
        # Same params, different insertion order -- the cache key must not care.
        second = client.get("https://example.com/data", params={"a": "1", "b": "2"})

        assert first.status_code == second.status_code == 200
        assert first.json() == second.json() == {"ok": True}
        assert len(calls) == 1

    def test_different_query_params_are_different_cache_entries(self, tmp_path: Path) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            symbol = request.url.params.get("symbol", "")
            calls.append(symbol)
            return httpx.Response(200, json={"symbol": symbol})

        transport = CachingTransport(httpx.MockTransport(handler), tmp_path / "http")
        client = httpx.Client(transport=transport)

        client.get("https://example.com/data", params={"symbol": "QQQ"})
        client.get("https://example.com/data", params={"symbol": "SOXL"})

        assert calls == ["QQQ", "SOXL"]

    def test_a_500_response_is_not_cached(self, tmp_path: Path) -> None:
        calls: list[httpx.URL] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url)
            return httpx.Response(500, text="boom")

        transport = CachingTransport(httpx.MockTransport(handler), tmp_path / "http")
        client = httpx.Client(transport=transport)

        first = client.get("https://example.com/data")
        second = client.get("https://example.com/data")

        assert first.status_code == second.status_code == 500
        assert len(calls) == 2  # never cached: a stored 500 would outlive the outage that caused it

    def test_post_requests_are_never_cached(self, tmp_path: Path) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.method)
            return httpx.Response(200, json={"ok": True})

        transport = CachingTransport(httpx.MockTransport(handler), tmp_path / "http")
        client = httpx.Client(transport=transport)

        client.post("https://example.com/data")
        client.post("https://example.com/data")

        assert calls == ["POST", "POST"]

    def test_expired_entry_is_refetched(self, tmp_path: Path) -> None:
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(200, json={"n": len(calls)})

        transport = CachingTransport(httpx.MockTransport(handler), tmp_path / "http", ttl=0.0)
        client = httpx.Client(transport=transport)

        client.get("https://example.com/data")
        client.get("https://example.com/data")

        assert len(calls) == 2  # ttl=0 means every entry is immediately stale

    def test_daily_bar_ttl_is_unaffected_by_the_meta_lookup_tier(self) -> None:
        """Pins the hour-scale daily-bar tier so `Finding 3.6`'s fix for the meta/quote lookup (see
        below) cannot silently regress it back down. If this assertion ever needs to change, that is
        a deliberate, reviewed change to how long a completed daily session is trusted -- not a side
        effect of a cache refactor."""
        from app.market.cache import cache_ttl

        assert cache_ttl(Interval.DAY) == 3600.0
        assert cache_ttl(Interval.WEEK) == 3600.0

    def test_ttl_table_covers_every_interval(self) -> None:
        """A loop over every `Interval` member, not a hardcoded list -- fails loudly if an eighth
        interval is added and this table forgotten, rather than `KeyError`-ing the first real
        request for it."""
        from app.market.cache import _TTL_BY_INTERVAL

        assert set(_TTL_BY_INTERVAL) == set(Interval)
        assert _TTL_BY_INTERVAL[Interval.FIVE_MIN] == 300.0
        assert _TTL_BY_INTERVAL[Interval.FIFTEEN_MIN] == 900.0
        assert _TTL_BY_INTERVAL[Interval.THIRTY_MIN] == 1800.0
        assert _TTL_BY_INTERVAL[Interval.HOUR] == 1800.0
        assert _TTL_BY_INTERVAL[Interval.FOUR_HOUR] == 3600.0
        assert _TTL_BY_INTERVAL[Interval.DAY] == 3600.0
        assert _TTL_BY_INTERVAL[Interval.WEEK] == 3600.0

    def test_yahoo_meta_lookup_shaped_request_gets_a_seconds_scale_ttl(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reproduces Finding 3.6: `YahooProvider._meta` (backing both `/quote` and `/profile`) sets
        `interval=1d` purely to keep the chart payload small -- see its docstring -- not because the
        caller wants a daily bar. Before the fix, that parameter alone routed the request through
        `_TTL_BY_INTERVAL[Interval.DAY]` and served a live quote from up to an hour ago. A request
        shaped like a genuine daily-bar fetch (explicit `period1`/`period2`, see
        `YahooProvider.fetch_bars`) must keep the full hour-scale TTL; only the meta-shaped request
        (relative `range`, no `period1`/`period2`) should drop to the seconds-scale tier.

        Uses a fake clock swapped into `app.market.cache`'s own `time` reference rather than the real
        stdlib module, so nothing outside this test observes the frozen time.
        """
        import app.market.cache as cache_module

        class _FakeClock:
            def __init__(self, start: float) -> None:
                self.now = start

            def time(self) -> float:
                return self.now

        clock = _FakeClock(1_700_000_000.0)
        monkeypatch.setattr(cache_module, "time", clock)

        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.params.get("range", "") or "bar")
            return httpx.Response(200, json={"ok": True})

        transport = cache_module.CachingTransport(httpx.MockTransport(handler), tmp_path / "http")
        client = httpx.Client(transport=transport)

        chart_url = "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"
        # Shaped exactly like YahooProvider._meta's request (quote, profile).
        meta_params = {
            "range": "5d",
            "interval": "1d",
            "includePrePost": "false",
            "events": "div,split",
        }
        # Shaped exactly like YahooProvider.fetch_bars's request for the same interval token.
        bar_params = {
            "interval": "1d",
            "includePrePost": "false",
            "events": "div,split",
            "period1": "0",
            "period2": "1700000000",
        }

        client.get(chart_url, params=meta_params)
        client.get(chart_url, params=bar_params)
        assert len(calls) == 2  # both cold, both fetched

        # 40s later: past the meta lookup's 30s TTL, nowhere near the daily bar's hour-scale TTL.
        clock.now += 40.0

        client.get(chart_url, params=meta_params)
        client.get(chart_url, params=bar_params)

        # Only the meta-shaped request should have gone stale and been re-fetched.
        assert len(calls) == 3
        assert calls == ["5d", "bar", "5d"]

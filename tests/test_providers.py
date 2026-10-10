"""Tests for the Yahoo, Stooq and SEC EDGAR providers.

Every test drives an ``httpx.MockTransport`` from the captured fixtures in
``tests/fixtures/market/`` -- no test in this file makes a network call. Fixture payloads are
deep-copied before mutation so tests cannot bleed state into one another through a shared dict.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest

from app.market.models import BAR_COLUMNS, Interval, session_date
from app.market.providers.base import (
    ProviderResponseError,
    ProviderUnavailable,
    RateLimited,
    SymbolNotFound,
    UnsupportedInterval,
)
from app.market.providers.sec_edgar import SecEdgarProvider
from app.market.providers.stooq import StooqProvider
from app.market.providers.yahoo import YahooProvider, _last_bar_unsettled

FIXTURES = Path(__file__).parent / "fixtures" / "market"


def _load_json(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def _load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _client_returning(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _client_json(status_code: int, payload: dict[str, Any], headers: dict[str, str] | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload, headers=headers or {})

    return _client_returning(handler)


def _client_text(status_code: int, text: str, headers: dict[str, str] | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=text, headers=headers or {})

    return _client_returning(handler)


def _client_never_called() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"no HTTP request should have been made, got {request.url}")

    return _client_returning(handler)


def _set_regular_market_time(payload: dict[str, Any], epoch: int) -> dict[str, Any]:
    """A deep copy of ``payload`` with ``meta.regularMarketTime`` patched to ``epoch``."""
    patched = copy.deepcopy(payload)
    patched["chart"]["result"][0]["meta"]["regularMarketTime"] = epoch
    return patched


# ---------------------------------------------------------------------------
# Yahoo: bars
# ---------------------------------------------------------------------------


class TestYahooDailyBars:
    def test_parses_expected_columns_row_count_and_ascending_ts(self) -> None:
        payload = _load_json("yahoo_qqq_1d.json")
        provider = YahooProvider(client=_client_json(200, payload))

        frame = provider.fetch_bars("QQQ", Interval.DAY)

        assert list(frame.columns) == list(BAR_COLUMNS)
        assert len(frame) == 90
        assert frame["ts"].is_monotonic_increasing

    def test_ts_is_midnight_utc_on_the_exchange_local_session_date(self) -> None:
        """The fixture's raw epochs are stamped 13:30 UTC (the US market open) -- .date() on that
        instant is right by luck for a UTC reader. This asserts the actual normalised value, not
        just that *some* conversion happened."""
        payload = _load_json("yahoo_qqq_1d.json")
        provider = YahooProvider(client=_client_json(200, payload))

        frame = provider.fetch_bars("QQQ", Interval.DAY)

        first_raw_epoch = payload["chart"]["result"][0]["timestamp"][0]
        raw_instant = dt.datetime.fromtimestamp(first_raw_epoch, tz=dt.UTC)
        expected_session = session_date(raw_instant, "America/New_York")

        first_bar_ts = frame["ts"].iloc[0].to_pydatetime()
        assert first_bar_ts == dt.datetime.combine(
            expected_session, dt.time.min, tzinfo=dt.UTC
        )
        assert first_bar_ts.time() == dt.time.min

    def test_soxl_fixture_parses_with_no_null_rows(self) -> None:
        payload = _load_json("yahoo_soxl_1d.json")
        provider = YahooProvider(client=_client_json(200, payload))

        frame = provider.fetch_bars("SOXL", Interval.DAY)

        assert len(frame) == 120

    def test_final_bar_kept_when_the_session_has_already_closed(self) -> None:
        """Baseline fixture: regularMarketTime equals the regular session's end -- not strictly
        before it -- so the session has fully closed and the last bar must be kept."""
        payload = _load_json("yahoo_qqq_1d.json")
        provider = YahooProvider(client=_client_json(200, payload))

        frame = provider.fetch_bars("QQQ", Interval.DAY)

        assert len(frame) == 90

    def test_final_bar_excluded_when_the_session_is_still_open(self) -> None:
        """Patch regularMarketTime to a couple of hours before the regular close, same exchange-
        local session date as the last bar: the session is still open, so the last daily bar has
        not settled and must be dropped."""
        payload = _load_json("yahoo_qqq_1d.json")
        still_open = _set_regular_market_time(payload, 1786384800)  # 18:00 UTC, same session
        provider = YahooProvider(client=_client_json(200, still_open))

        baseline = YahooProvider(client=_client_json(200, payload)).fetch_bars("QQQ", Interval.DAY)
        frame = provider.fetch_bars("QQQ", Interval.DAY)

        assert len(frame) == len(baseline) - 1
        assert frame["ts"].iloc[-1] < baseline["ts"].iloc[-1]

    def test_null_ohlc_row_is_dropped_not_forward_filled(self) -> None:
        payload = _load_json("yahoo_qqq_1d.json")
        result = payload["chart"]["result"][0]
        dropped_epoch = result["timestamp"][10]
        result["indicators"]["quote"][0]["close"][10] = None
        provider = YahooProvider(client=_client_json(200, payload))

        frame = provider.fetch_bars("QQQ", Interval.DAY)

        assert len(frame) == 89
        dropped_date = dt.datetime.fromtimestamp(dropped_epoch, tz=dt.UTC).date()
        assert dropped_date not in {ts.date() for ts in frame["ts"]}
        # No interpolation: the neighbouring bars are exactly their original quoted values, not an
        # average or a copy filling the gap.
        assert not frame["close"].isna().any()


class TestYahooIntradayBars:
    def test_hourly_bars_keep_true_instants_and_carry_nan_adj_close(self) -> None:
        payload = _load_json("yahoo_qqq_1h.json")
        provider = YahooProvider(client=_client_json(200, payload))

        frame = provider.fetch_bars("QQQ", Interval.HOUR)

        assert list(frame.columns) == list(BAR_COLUMNS)
        assert len(frame) == 59  # 60 fetched, trailing still-forming bar dropped
        assert frame["ts"].is_monotonic_increasing
        assert frame["adj_close"].isna().all()

        raw_timestamps = payload["chart"]["result"][0]["timestamp"][:59]
        expected = [dt.datetime.fromtimestamp(e, tz=dt.UTC) for e in raw_timestamps]
        assert list(frame["ts"].dt.to_pydatetime()) == expected

    def test_five_minute_bars_keep_true_instants_and_carry_nan_adj_close(self) -> None:
        payload = _load_json("yahoo_qqq_5m.json")
        provider = YahooProvider(client=_client_json(200, payload))

        frame = provider.fetch_bars("QQQ", Interval.FIVE_MIN)

        assert len(frame) == 79
        assert frame["adj_close"].isna().all()

    def test_adj_close_is_never_a_copy_of_close(self) -> None:
        payload = _load_json("yahoo_qqq_1h.json")
        provider = YahooProvider(client=_client_json(200, payload))

        frame = provider.fetch_bars("QQQ", Interval.HOUR)

        assert not (frame["adj_close"].fillna(-1.0) == frame["close"]).any()


class TestLastBarUnsettledHelper:
    """Direct tests of the settlement rule, isolated from HTTP and DataFrame plumbing -- this is
    the single most consequential decision in the module."""

    def test_daily_bar_settled_once_regular_market_time_reaches_the_close(self) -> None:
        session_ts = dt.datetime(2026, 8, 10, tzinfo=dt.UTC)
        close = dt.datetime(2026, 8, 10, 20, 0, tzinfo=dt.UTC)
        assert not _last_bar_unsettled(
            session_ts,
            Interval.DAY,
            regular_market_time=close,
            regular_end=close,
            exchange_tz="America/New_York",
        )

    def test_daily_bar_unsettled_mid_session(self) -> None:
        session_ts = dt.datetime(2026, 8, 10, tzinfo=dt.UTC)
        mid_session = dt.datetime(2026, 8, 10, 18, 0, tzinfo=dt.UTC)
        close = dt.datetime(2026, 8, 10, 20, 0, tzinfo=dt.UTC)
        assert _last_bar_unsettled(
            session_ts,
            Interval.DAY,
            regular_market_time=mid_session,
            regular_end=close,
            exchange_tz="America/New_York",
        )

    def test_daily_bar_from_a_prior_session_is_never_unsettled(self) -> None:
        """A bar from an earlier day is always final, regardless of today's market state."""
        yesterday = dt.datetime(2026, 8, 7, tzinfo=dt.UTC)
        mid_session_today = dt.datetime(2026, 8, 10, 18, 0, tzinfo=dt.UTC)
        close_today = dt.datetime(2026, 8, 10, 20, 0, tzinfo=dt.UTC)
        assert not _last_bar_unsettled(
            yesterday,
            Interval.DAY,
            regular_market_time=mid_session_today,
            regular_end=close_today,
            exchange_tz="America/New_York",
        )

    def test_yesterdays_closed_session_is_settled_before_todays_open(self) -> None:
        """The overnight case: `regularMarketTime` still reads yesterday's close while
        `currentTradingPeriod` has already rolled forward to today's not-yet-started session.

        This is what Yahoo actually returns at 07:38 ET on a Wednesday, verified against a live
        response. The previous rule compared Tuesday-16:00 against *Wednesday*-16:00 -- always true
        -- and so dropped Tuesday's fully settled bar from every fetch made overnight. The bar the
        store most needs is the one that rule was guaranteed to discard.
        """
        tuesday_close = dt.datetime(2026, 8, 25, 20, 0, tzinfo=dt.UTC)
        wednesday_close = dt.datetime(2026, 8, 26, 20, 0, tzinfo=dt.UTC)
        assert not _last_bar_unsettled(
            dt.datetime(2026, 8, 25, tzinfo=dt.UTC),
            Interval.DAY,
            regular_market_time=tuesday_close,
            regular_end=wednesday_close,
            exchange_tz="America/New_York",
        )

    def test_fridays_session_is_settled_all_weekend(self) -> None:
        """Same defect, longer blast radius: over a weekend `currentTradingPeriod` points at Monday,
        so the old rule dropped Friday's bar for two whole days."""
        friday_close = dt.datetime(2026, 8, 21, 20, 0, tzinfo=dt.UTC)
        monday_close = dt.datetime(2026, 8, 24, 20, 0, tzinfo=dt.UTC)
        assert not _last_bar_unsettled(
            dt.datetime(2026, 8, 21, tzinfo=dt.UTC),
            Interval.DAY,
            regular_market_time=friday_close,
            regular_end=monday_close,
            exchange_tz="America/New_York",
        )

    def test_todays_forming_bar_is_still_dropped_premarket(self) -> None:
        """The fix must not swing the other way. When Yahoo does emit a bar for the session that
        `currentTradingPeriod` names -- a pre-market or mid-session candle -- it is still forming and
        must still be dropped, which is the direction that would write a moving price into the store
        as if it were final."""
        yesterday_close = dt.datetime(2026, 8, 25, 20, 0, tzinfo=dt.UTC)
        today_close = dt.datetime(2026, 8, 26, 20, 0, tzinfo=dt.UTC)
        assert _last_bar_unsettled(
            dt.datetime(2026, 8, 26, tzinfo=dt.UTC),
            Interval.DAY,
            regular_market_time=yesterday_close,
            regular_end=today_close,
            exchange_tz="America/New_York",
        )

    def test_hourly_bar_unsettled_when_its_interval_has_not_elapsed(self) -> None:
        bar_open = dt.datetime(2026, 8, 10, 19, 30, tzinfo=dt.UTC)
        now = dt.datetime(2026, 8, 10, 20, 0, tzinfo=dt.UTC)  # only 30 minutes in
        assert _last_bar_unsettled(
            bar_open,
            Interval.HOUR,
            regular_market_time=now,
            regular_end=now,
            exchange_tz="America/New_York",
        )

    def test_hourly_bar_settled_once_its_full_interval_has_elapsed(self) -> None:
        bar_open = dt.datetime(2026, 8, 10, 18, 30, tzinfo=dt.UTC)
        now = dt.datetime(2026, 8, 10, 19, 30, tzinfo=dt.UTC)  # exactly one hour later
        assert not _last_bar_unsettled(
            bar_open,
            Interval.HOUR,
            regular_market_time=now,
            regular_end=now,
            exchange_tz="America/New_York",
        )


class TestYahooExchangeTimezoneAttr:
    def test_fetch_bars_stashes_exchange_timezone_on_frame_attrs(self) -> None:
        """`app.market.registry.ProviderRegistry.get_bars` reads this back out onto `BarFetch` so
        `app.market.store`'s intraday staleness gate can use the instrument's own trading hours
        instead of always assuming America/New_York -- see that module's `_plausible_trading_window`."""
        payload = _load_json("yahoo_qqq_1d.json")
        provider = YahooProvider(client=_client_json(200, payload))

        frame = provider.fetch_bars("QQQ", Interval.DAY)

        expected = payload["chart"]["result"][0]["meta"]["exchangeTimezoneName"]
        assert frame.attrs["exchange_timezone"] == expected


class TestYahooUserAgent:
    def test_user_agent_is_honest_not_a_spoofed_browser(self) -> None:
        """Mirrors `tests/test_fred.py`'s equivalent test. `app/market/providers/fred.py`'s docstring
        documents verifying, 3/3 vs 9/9 interleaved against the live endpoint, that FRED tarpits a
        Chrome-shaped User-Agent -- the request hangs until timeout and never returns -- while an
        honest one gets the same payload in under a second. Yahoo's undocumented chart endpoint
        tolerating a spoofed browser string today is not evidence it always will; spoofing is exactly
        the pattern that gets a client blocked. Must never be changed back to a Chrome/Firefox/Safari
        string."""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=_load_json("yahoo_qqq_1d.json"))

        provider = YahooProvider(client=_client_returning(handler))
        provider.fetch_bars("QQQ", Interval.DAY)

        ua = seen[0].headers.get("user-agent", "")
        assert "@" in ua  # an honest, contactable identity, not a fabricated browser string
        for spoofed in ("Mozilla", "Chrome", "Safari", "WebKit"):
            assert spoofed not in ua


class TestYahooUnsupportedInterval:
    def test_week_raises_unsupported_interval_without_any_request(self) -> None:
        provider = YahooProvider(client=_client_never_called())
        with pytest.raises(UnsupportedInterval):
            provider.fetch_bars("QQQ", Interval.WEEK)


class TestYahooIntervalTableCompleteness:
    """Loops over every ``Interval`` member rather than hardcoding a list, so an eighth interval
    added later without updating these tables fails loudly here instead of `KeyError`-ing (or
    silently falling out of `supported_intervals`) the first time it is actually requested.

    ``Interval.WEEK`` is the one deliberate exception in both tables: weekly bars are resampled
    locally from stored daily bars and must never be requested from Yahoo directly (see the module
    docstring and ``app/db/duck.py``'s), so it is asserted *absent* rather than present.
    """

    def test_yahoo_interval_map_covers_every_interval_except_week(self) -> None:
        from app.market.providers.yahoo import _YAHOO_INTERVAL

        assert set(_YAHOO_INTERVAL) == set(Interval) - {Interval.WEEK}
        assert Interval.WEEK not in _YAHOO_INTERVAL

    def test_supported_intervals_covers_every_interval_except_week(self) -> None:
        assert YahooProvider.supported_intervals == set(Interval) - {Interval.WEEK}
        assert Interval.WEEK not in YahooProvider.supported_intervals

    def test_yahoo_interval_tokens_are_yahoos_own_spelling(self) -> None:
        from app.market.providers.yahoo import _YAHOO_INTERVAL

        assert _YAHOO_INTERVAL[Interval.FIVE_MIN] == "5m"
        assert _YAHOO_INTERVAL[Interval.FIFTEEN_MIN] == "15m"
        assert _YAHOO_INTERVAL[Interval.THIRTY_MIN] == "30m"
        assert _YAHOO_INTERVAL[Interval.HOUR] == "1h"
        assert _YAHOO_INTERVAL[Interval.FOUR_HOUR] == "4h"
        assert _YAHOO_INTERVAL[Interval.DAY] == "1d"


# ---------------------------------------------------------------------------
# Yahoo: error mapping
# ---------------------------------------------------------------------------


class TestYahooErrorMapping:
    def test_http_404_raises_symbol_not_found(self) -> None:
        payload = _load_json("yahoo_not_found.json")
        provider = YahooProvider(client=_client_json(404, payload))
        with pytest.raises(SymbolNotFound):
            provider.fetch_bars("NOPE", Interval.DAY)

    def test_200_with_not_found_error_body_raises_symbol_not_found(self) -> None:
        """Yahoo sometimes answers a bad symbol with HTTP 200 and an error body rather than a
        404 -- both shapes must resolve to the same typed error."""
        payload = _load_json("yahoo_not_found.json")
        provider = YahooProvider(client=_client_json(200, payload))
        with pytest.raises(SymbolNotFound):
            provider.fetch_bars("NOPE", Interval.DAY)

    def test_429_raises_rate_limited_with_retry_after(self) -> None:
        provider = YahooProvider(
            client=_client_json(429, {}, headers={"Retry-After": "30"})
        )
        with pytest.raises(RateLimited) as exc_info:
            provider.fetch_bars("QQQ", Interval.DAY)
        assert exc_info.value.retry_after == 30.0

    def test_500_raises_provider_unavailable(self) -> None:
        provider = YahooProvider(client=_client_json(500, {}))
        with pytest.raises(ProviderUnavailable):
            provider.fetch_bars("QQQ", Interval.DAY)

    def test_malformed_200_missing_timestamp_raises_provider_response_error(self) -> None:
        payload = _load_json("yahoo_qqq_1d.json")
        del payload["chart"]["result"][0]["timestamp"]
        provider = YahooProvider(client=_client_json(200, payload))
        with pytest.raises(ProviderResponseError):
            provider.fetch_bars("QQQ", Interval.DAY)

    def test_malformed_200_missing_quote_indicator_raises_provider_response_error(self) -> None:
        payload = _load_json("yahoo_qqq_1d.json")
        del payload["chart"]["result"][0]["indicators"]["quote"]
        provider = YahooProvider(client=_client_json(200, payload))
        with pytest.raises(ProviderResponseError):
            provider.fetch_bars("QQQ", Interval.DAY)

    def test_timeout_raises_provider_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out", request=request)

        provider = YahooProvider(client=_client_returning(handler))
        with pytest.raises(ProviderUnavailable):
            provider.fetch_bars("QQQ", Interval.DAY)


# ---------------------------------------------------------------------------
# Yahoo: quote and profile
# ---------------------------------------------------------------------------


class TestYahooQuote:
    def test_maps_meta_fields_and_computes_change_pct(self) -> None:
        payload = _load_json("yahoo_qqq_1d.json")
        provider = YahooProvider(client=_client_json(200, payload))

        quote = provider.fetch_quote("QQQ")

        meta = payload["chart"]["result"][0]["meta"]
        assert quote.symbol == "QQQ"
        assert quote.price == meta["regularMarketPrice"]
        assert quote.previous_close == meta["chartPreviousClose"]
        expected_change = meta["regularMarketPrice"] - meta["chartPreviousClose"]
        assert quote.change == pytest.approx(expected_change)
        assert quote.change_pct == pytest.approx(expected_change / meta["chartPreviousClose"] * 100)
        assert quote.day_high == meta["regularMarketDayHigh"]
        assert quote.day_low == meta["regularMarketDayLow"]
        assert quote.fifty_two_week_high == meta["fiftyTwoWeekHigh"]
        assert quote.fifty_two_week_low == meta["fiftyTwoWeekLow"]
        assert quote.volume == meta["regularMarketVolume"]
        assert quote.currency == "USD"

    def test_change_and_change_pct_are_none_when_previous_close_is_absent(self) -> None:
        payload = _load_json("yahoo_qqq_1d.json")
        del payload["chart"]["result"][0]["meta"]["chartPreviousClose"]
        provider = YahooProvider(client=_client_json(200, payload))

        quote = provider.fetch_quote("QQQ")

        assert quote.previous_close is None
        assert quote.change is None
        assert quote.change_pct is None

    def test_missing_regular_market_price_raises_provider_response_error(self) -> None:
        payload = _load_json("yahoo_qqq_1d.json")
        del payload["chart"]["result"][0]["meta"]["regularMarketPrice"]
        provider = YahooProvider(client=_client_json(200, payload))
        with pytest.raises(ProviderResponseError):
            provider.fetch_quote("QQQ")


class TestYahooProfile:
    def test_maps_meta_fields(self) -> None:
        payload = _load_json("yahoo_qqq_1d.json")
        provider = YahooProvider(client=_client_json(200, payload))

        profile = provider.fetch_profile("QQQ")

        assert profile.symbol == "QQQ"
        assert profile.name == "Invesco QQQ Trust"
        assert profile.exchange == "NasdaqGM"
        assert profile.exchange_timezone == "America/New_York"
        assert profile.currency == "USD"
        assert profile.instrument_type == "ETF"
        assert profile.first_trade_date == dt.date(1999, 3, 10)

    def test_falls_back_to_short_name_when_long_name_is_absent(self) -> None:
        payload = _load_json("yahoo_qqq_1d.json")
        del payload["chart"]["result"][0]["meta"]["longName"]
        provider = YahooProvider(client=_client_json(200, payload))

        profile = provider.fetch_profile("QQQ")

        assert profile.name == "Invesco QQQ Trust, Series 1"

    def test_out_of_range_first_trade_date_yields_none_not_a_crash(self) -> None:
        """An out-of-range firstTradeDate must not sink the whole profile. On Windows
        `datetime.fromtimestamp` raises `OSError: [Errno 22]` for such values, which previously turned
        real tickers (KO, CAT, JNJ, BA) into a `fetch_profile` failure the persona validator then
        dropped. The date comes back `None`; every other field is intact."""
        payload = _load_json("yahoo_qqq_1d.json")
        payload["chart"]["result"][0]["meta"]["firstTradeDate"] = -99999999999999
        provider = YahooProvider(client=_client_json(200, payload))

        profile = provider.fetch_profile("QQQ")

        assert profile.first_trade_date is None
        assert profile.symbol == "QQQ"
        assert profile.currency == "USD"

    def test_null_currency_falls_back_to_usd(self) -> None:
        """Yahoo returns `currency` present-but-null for indices/futures; a `.get(..., "USD")` default
        only fills a *missing* key, so the null would reach `Profile(currency=None)` and fail
        validation -- dropping a real symbol. It must coalesce to USD instead."""
        payload = _load_json("yahoo_qqq_1d.json")
        payload["chart"]["result"][0]["meta"]["currency"] = None
        provider = YahooProvider(client=_client_json(200, payload))

        profile = provider.fetch_profile("QQQ")

        assert profile.currency == "USD"


# ---------------------------------------------------------------------------
# Stooq
# ---------------------------------------------------------------------------

_STOOQ_CSV = (
    "Date,Open,High,Low,Close,Volume\n"
    "2024-01-02,10.0,11.0,9.5,10.5,1000\n"
    "2024-01-03,10.5,11.5,10.0,11.0,1500\n"
)


class TestStooqBars:
    def test_daily_csv_parses_to_expected_columns_and_ascending_ts(self) -> None:
        provider = StooqProvider(client=_client_text(200, _STOOQ_CSV))

        frame = provider.fetch_bars("AAPL", Interval.DAY)

        assert list(frame.columns) == list(BAR_COLUMNS)
        assert len(frame) == 2
        assert frame["ts"].is_monotonic_increasing
        assert frame["ts"].iloc[0] == pd.Timestamp("2024-01-02", tz="UTC")
        assert frame["close"].tolist() == [10.5, 11.0]

    def test_adj_close_is_always_nan(self) -> None:
        provider = StooqProvider(client=_client_text(200, _STOOQ_CSV))
        frame = provider.fetch_bars("AAPL", Interval.DAY)
        assert frame["adj_close"].isna().all()

    def test_week_raises_unsupported_interval_without_any_request(self) -> None:
        provider = StooqProvider(client=_client_never_called())
        with pytest.raises(UnsupportedInterval):
            provider.fetch_bars("AAPL", Interval.WEEK)

    def test_hour_raises_unsupported_interval(self) -> None:
        provider = StooqProvider(client=_client_never_called())
        with pytest.raises(UnsupportedInterval):
            provider.fetch_bars("AAPL", Interval.HOUR)


class TestStooqAntiBotChallenge:
    def test_html_challenge_page_raises_provider_response_error_not_empty_series(self) -> None:
        """The behaviour most likely to be exercised in production today: Stooq answers HTTP 200
        with an HTML anti-bot page instead of CSV. Treating that as an empty series would report
        "no history" for a ticker that has thirty years of it."""
        html = _load_text("stooq_challenge.html")
        provider = StooqProvider(client=_client_text(200, html))

        with pytest.raises(ProviderResponseError):
            provider.fetch_bars("AAPL", Interval.DAY)


class TestStooqErrorMapping:
    def test_404_is_unavailable_not_symbol_not_found(self) -> None:
        """Stooq must never assert that a symbol does not exist.

        ``SymbolNotFound`` is terminal in the registry: it re-raises immediately and the user is
        told to check their ticker. Stooq cannot support that claim while it is behind an anti-bot
        challenge -- QQQ, which plainly exists, 404s there today. Since Stooq is only reached after
        the primary has already failed, letting it claim non-existence would let a degraded fallback
        overrule a healthy primary and report "Yahoo is down" as "no such ticker".
        """
        provider = StooqProvider(client=_client_text(404, "not found"))
        with pytest.raises(ProviderResponseError):
            provider.fetch_bars("AAPL", Interval.DAY)
        assert not issubclass(ProviderResponseError, SymbolNotFound)

    def test_429_raises_rate_limited(self) -> None:
        provider = StooqProvider(client=_client_text(429, "", headers={"Retry-After": "5"}))
        with pytest.raises(RateLimited) as exc_info:
            provider.fetch_bars("AAPL", Interval.DAY)
        assert exc_info.value.retry_after == 5.0

    def test_500_raises_provider_unavailable(self) -> None:
        provider = StooqProvider(client=_client_text(500, "server error"))
        with pytest.raises(ProviderUnavailable):
            provider.fetch_bars("AAPL", Interval.DAY)


# ---------------------------------------------------------------------------
# SEC EDGAR
# ---------------------------------------------------------------------------


def _sec_handler(
    calls: list[str], *, tickers_status: int = 200, facts_status: int = 200
) -> Callable[[httpx.Request], httpx.Response]:
    tickers = _load_json("sec_company_tickers.json")
    facts = _load_json("sec_companyfacts_aapl.json")

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        user_agent = request.headers.get("user-agent", "")
        assert "@" in user_agent, f"SEC requires a contactable User-Agent, got {user_agent!r}"
        if "company_tickers.json" in str(request.url):
            return httpx.Response(tickers_status, json=tickers)
        if "CIK0000320193.json" in str(request.url):
            return httpx.Response(facts_status, json=facts)
        return httpx.Response(404, json={})

    return handler


class TestSecEdgarProvider:
    def test_known_symbol_resolves_cik_and_returns_fundamentals(self) -> None:
        calls: list[str] = []
        provider = SecEdgarProvider(client=_client_returning(_sec_handler(calls)))

        result = provider.fetch_fundamentals("AAPL")

        assert result.symbol == "AAPL"
        assert result.cik == "320193"
        assert result.entity_name == "Apple Inc."
        assert result.unavailable_reason is None
        assert result.facts

    def test_ticker_map_is_cached_after_the_first_call(self) -> None:
        calls: list[str] = []
        provider = SecEdgarProvider(client=_client_returning(_sec_handler(calls)))

        provider.fetch_fundamentals("AAPL")
        provider.fetch_fundamentals("AAPL")

        ticker_map_calls = [c for c in calls if "company_tickers.json" in c]
        assert len(ticker_map_calls) == 1

    def test_symbol_absent_from_ticker_map_raises_symbol_not_found(self) -> None:
        """The common case for this portfolio: an ETF that files nothing with SEC's XBRL API."""
        calls: list[str] = []
        provider = SecEdgarProvider(client=_client_returning(_sec_handler(calls)))

        with pytest.raises(SymbolNotFound, match="ETF"):
            provider.fetch_fundamentals("QQQ")

    def test_ticker_map_404_is_provider_unavailable_not_symbol_not_found(self) -> None:
        """`_get_json` used to map *every* 404 -- including the shared, symbol-agnostic ticker map --
        to `SymbolNotFound`. `SymbolNotFound` is documented in `app.market.registry` as terminal: the
        registry does not retry it and tells the caller the ticker does not exist. A 404 on
        `company_tickers.json` says nothing about any particular ticker -- it means the endpoint moved
        or SEC is down -- so `fetch_fundamentals("AAPL")`, a real filer, must not fail claiming AAPL
        does not exist just because the shared infrastructure endpoint is unreachable."""
        calls: list[str] = []
        provider = SecEdgarProvider(
            client=_client_returning(_sec_handler(calls, tickers_status=404))
        )

        with pytest.raises(ProviderUnavailable) as excinfo:
            provider.fetch_fundamentals("AAPL")

        assert not isinstance(excinfo.value, SymbolNotFound)

    def test_facts_endpoint_404_for_a_ticker_map_hit_is_still_symbol_not_found(self) -> None:
        """The opposite case: the symbol *is* in the ticker map (a real CIK), but the company-facts
        endpoint itself 404s for that CIK -- a newly registered filer with no XBRL facts yet. This is
        a genuine per-symbol "nothing here," unlike the ticker-map case above, so it must still raise
        `SymbolNotFound`."""
        calls: list[str] = []
        provider = SecEdgarProvider(client=_client_returning(_sec_handler(calls, facts_status=404)))

        with pytest.raises(SymbolNotFound, match="AAPL"):
            provider.fetch_fundamentals("AAPL")

    def test_403_style_rejection_maps_through_generic_status_handling(self) -> None:
        provider = SecEdgarProvider(client=_client_json(403, {}))
        with pytest.raises(ProviderResponseError):
            provider.fetch_fundamentals("AAPL")

    def test_429_raises_rate_limited(self) -> None:
        provider = SecEdgarProvider(
            client=_client_json(429, {}, headers={"Retry-After": "60"})
        )
        with pytest.raises(RateLimited) as exc_info:
            provider.fetch_fundamentals("AAPL")
        assert exc_info.value.retry_after == 60.0

"""Tests for the Yahoo Finance per-symbol and free-text news provider.

Every test drives an ``httpx.MockTransport`` -- no test in this file makes a network call. The
captured fixture (``tests/fixtures/news/yahoo_news_nvda.json``, 10 NVDA-related stories trimmed from
a live 2026-08-24 response) is deep-copied before mutation so tests cannot bleed state into one
another through a shared dict.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.market.providers.base import (
    ProviderResponseError,
    ProviderUnavailable,
    RateLimited,
    SymbolNotFound,
    UnsupportedQuery,
)
from app.market.providers.yahoo_news import YahooNewsProvider

FIXTURES = Path(__file__).parent / "fixtures" / "news"


def _load_json(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _client_returning(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _client_json(
    status_code: int, payload: dict[str, Any] | list[Any], headers: dict[str, str] | None = None
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload, headers=headers or {})

    return _client_returning(handler)


def _client_text(status_code: int, body: str, headers: dict[str, str] | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=body, headers=headers or {})

    return _client_returning(handler)


def _client_raising(exc: Exception) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return _client_returning(handler)


# ---------------------------------------------------------------------------
# Parsing the real fixture
# ---------------------------------------------------------------------------


class TestYahooNewsParsing:
    def test_real_fixture_parses_all_ten_items(self) -> None:
        payload = _load_json("yahoo_news_nvda.json")
        provider = YahooNewsProvider(client=_client_json(200, payload))

        feed = provider.fetch_symbol_news("NVDA")

        assert len(feed.items) == len(payload["news"]) == 10
        assert feed.source == "yahoo_news"

    def test_published_is_tz_aware_utc_and_matches_the_expected_epoch_conversion(self) -> None:
        """`providerPublishTime` is a Unix epoch integer in seconds -- the trap this provider
        exists to guard against. Assert the concrete converted value, not just that some
        conversion happened."""
        payload = _load_json("yahoo_news_nvda.json")
        provider = YahooNewsProvider(client=_client_json(200, payload))

        feed = provider.fetch_symbol_news("NVDA")

        first_raw_epoch = payload["news"][0]["providerPublishTime"]
        expected = dt.datetime.fromtimestamp(first_raw_epoch, tz=dt.UTC)
        assert expected == dt.datetime(2026, 8, 24, 17, 1, 10, tzinfo=dt.UTC)

        newest = feed.items[0]
        assert newest.published == expected
        assert newest.published.tzinfo is not None
        assert newest.published.utcoffset() == dt.timedelta(0)

    def test_title_url_and_publisher_are_mapped_from_title_link_and_publisher(self) -> None:
        payload = _load_json("yahoo_news_nvda.json")
        provider = YahooNewsProvider(client=_client_json(200, payload))

        feed = provider.fetch_symbol_news("NVDA")

        newest = feed.items[0]
        raw = payload["news"][0]
        assert newest.title == raw["title"]
        assert newest.url == raw["link"]
        assert newest.publisher == raw["publisher"]
        assert newest.source == "yahoo_news"

    def test_summary_is_always_none_since_the_endpoint_carries_no_summary_field(self) -> None:
        payload = _load_json("yahoo_news_nvda.json")
        provider = YahooNewsProvider(client=_client_json(200, payload))

        feed = provider.fetch_symbol_news("NVDA")

        assert all(item.summary is None for item in feed.items)

    def test_items_are_sorted_newest_first(self) -> None:
        payload = _load_json("yahoo_news_nvda.json")
        provider = YahooNewsProvider(client=_client_json(200, payload))

        feed = provider.fetch_symbol_news("NVDA")

        published = [item.published for item in feed.items]
        assert published == sorted(published, reverse=True)


# ---------------------------------------------------------------------------
# limit / as_of
# ---------------------------------------------------------------------------


class TestYahooNewsLimitAndAsOf:
    def test_limit_is_honoured(self) -> None:
        payload = _load_json("yahoo_news_nvda.json")
        provider = YahooNewsProvider(client=_client_json(200, payload))

        feed = provider.fetch_symbol_news("NVDA", limit=3)

        assert len(feed.items) == 3
        # The three newest by published time, since parsing sorts newest-first.
        all_published = sorted(
            (item["providerPublishTime"] for item in payload["news"]), reverse=True
        )
        expected_newest = dt.datetime.fromtimestamp(all_published[0], tz=dt.UTC)
        assert feed.items[0].published == expected_newest

    def test_as_of_genuinely_drops_a_newer_item(self) -> None:
        """Not just 'succeeds' -- assert the drop. `as_of` set to the second-newest item's
        timestamp must exclude the newest item from the returned feed."""
        payload = _load_json("yahoo_news_nvda.json")
        provider = YahooNewsProvider(client=_client_json(200, payload))

        sorted_epochs = sorted(
            (item["providerPublishTime"] for item in payload["news"]), reverse=True
        )
        newest_epoch, second_newest_epoch = sorted_epochs[0], sorted_epochs[1]
        as_of = dt.datetime.fromtimestamp(second_newest_epoch, tz=dt.UTC)

        feed = provider.fetch_symbol_news("NVDA", as_of=as_of)

        newest_published = dt.datetime.fromtimestamp(newest_epoch, tz=dt.UTC)
        assert newest_published not in [item.published for item in feed.items]
        assert all(item.published <= as_of for item in feed.items)
        assert len(feed.items) == len(payload["news"]) - 1

    def test_naive_as_of_raises_value_error(self) -> None:
        payload = _load_json("yahoo_news_nvda.json")
        provider = YahooNewsProvider(client=_client_json(200, payload))

        with pytest.raises(ValueError, match="timezone-aware"):
            provider.fetch_symbol_news("NVDA", as_of=dt.datetime(2026, 8, 24, 12, 0, 0))

    def test_as_of_none_returns_everything(self) -> None:
        payload = _load_json("yahoo_news_nvda.json")
        provider = YahooNewsProvider(client=_client_json(200, payload))

        feed = provider.fetch_symbol_news("NVDA", as_of=None)

        assert len(feed.items) == len(payload["news"])


# ---------------------------------------------------------------------------
# fetch_query_news
# ---------------------------------------------------------------------------


class TestYahooNewsQuery:
    def test_empty_query_raises_unsupported_query(self) -> None:
        provider = YahooNewsProvider(client=_client_raising(AssertionError("should not be called")))

        with pytest.raises(UnsupportedQuery):
            provider.fetch_query_news("")

    def test_whitespace_only_query_raises_unsupported_query(self) -> None:
        provider = YahooNewsProvider(client=_client_raising(AssertionError("should not be called")))

        with pytest.raises(UnsupportedQuery):
            provider.fetch_query_news("   ")

    def test_non_empty_query_is_sent_and_parses_the_same_fixture_shape(self) -> None:
        payload = _load_json("yahoo_news_nvda.json")
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=payload)

        provider = YahooNewsProvider(client=_client_returning(handler))

        feed = provider.fetch_query_news("Fed rate cut")

        assert len(feed.items) == 10
        assert seen[0].url.params["q"] == "Fed rate cut"


# ---------------------------------------------------------------------------
# Missing 'news' key -- explained absence, not a failure
# ---------------------------------------------------------------------------


class TestYahooNewsMissingNewsKey:
    def test_response_with_no_news_key_returns_empty_feed_not_an_error(self) -> None:
        payload = copy.deepcopy(_load_json("yahoo_news_nvda.json"))
        del payload["news"]
        provider = YahooNewsProvider(client=_client_json(200, payload))

        feed = provider.fetch_symbol_news("OBSCURE")

        assert feed.items == ()
        assert len(feed.warnings) == 1
        assert feed.warnings[0].kind == "missing_news"


# ---------------------------------------------------------------------------
# User-Agent
# ---------------------------------------------------------------------------


class TestYahooNewsUserAgent:
    def test_user_agent_is_honest_not_a_spoofed_browser(self) -> None:
        """Mirrors `tests/test_fred.py` and `tests/test_provider_stocktwits.py`'s equivalent tests.
        See `app/market/providers/fred.py`'s module docstring: a Chrome-shaped User-Agent is exactly
        the pattern that gets a keyless client blocked, not a way to blend in."""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=_load_json("yahoo_news_nvda.json"))

        provider = YahooNewsProvider(client=_client_returning(handler))
        provider.fetch_symbol_news("NVDA")

        ua = seen[0].headers.get("user-agent", "")
        assert ua == "investing-dashboard/0.1"
        for spoofed in ("Mozilla", "Chrome", "Safari", "WebKit"):
            assert spoofed not in ua


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


class TestYahooNewsErrorMapping:
    def test_404_raises_symbol_not_found(self) -> None:
        provider = YahooNewsProvider(client=_client_json(404, {}))
        with pytest.raises(SymbolNotFound):
            provider.fetch_symbol_news("NOPE")

    def test_429_raises_rate_limited_with_retry_after_parsed_from_header(self) -> None:
        provider = YahooNewsProvider(client=_client_json(429, {}, headers={"Retry-After": "30"}))
        with pytest.raises(RateLimited) as exc_info:
            provider.fetch_symbol_news("NVDA")
        assert exc_info.value.retry_after == 30.0

    def test_429_without_retry_after_header_leaves_retry_after_none(self) -> None:
        provider = YahooNewsProvider(client=_client_json(429, {}))
        with pytest.raises(RateLimited) as exc_info:
            provider.fetch_symbol_news("NVDA")
        assert exc_info.value.retry_after is None

    def test_500_raises_provider_unavailable(self) -> None:
        provider = YahooNewsProvider(client=_client_json(500, {}))
        with pytest.raises(ProviderUnavailable):
            provider.fetch_symbol_news("NVDA")

    def test_503_raises_provider_unavailable(self) -> None:
        provider = YahooNewsProvider(client=_client_text(503, "service unavailable"))
        with pytest.raises(ProviderUnavailable):
            provider.fetch_symbol_news("NVDA")

    def test_other_4xx_raises_provider_response_error(self) -> None:
        provider = YahooNewsProvider(client=_client_json(403, {}))
        with pytest.raises(ProviderResponseError):
            provider.fetch_symbol_news("NVDA")

    def test_timeout_raises_provider_unavailable(self) -> None:
        provider = YahooNewsProvider(client=_client_raising(httpx.TimeoutException("timed out")))
        with pytest.raises(ProviderUnavailable):
            provider.fetch_symbol_news("NVDA")

    def test_transport_error_raises_provider_unavailable(self) -> None:
        provider = YahooNewsProvider(client=_client_raising(httpx.ConnectError("connection refused")))
        with pytest.raises(ProviderUnavailable):
            provider.fetch_symbol_news("NVDA")

    def test_body_that_is_not_json_raises_provider_response_error(self) -> None:
        provider = YahooNewsProvider(client=_client_text(200, "<html>not json</html>"))
        with pytest.raises(ProviderResponseError):
            provider.fetch_symbol_news("NVDA")

    def test_json_body_that_is_not_an_object_raises_provider_response_error(self) -> None:
        provider = YahooNewsProvider(client=_client_json(200, [1, 2, 3]))
        with pytest.raises(ProviderResponseError):
            provider.fetch_symbol_news("NVDA")

    def test_news_field_not_a_list_raises_provider_response_error(self) -> None:
        payload = copy.deepcopy(_load_json("yahoo_news_nvda.json"))
        payload["news"] = {"unexpected": "shape"}
        provider = YahooNewsProvider(client=_client_json(200, payload))
        with pytest.raises(ProviderResponseError):
            provider.fetch_symbol_news("NVDA")

    def test_entry_missing_provider_publish_time_is_dropped_not_raised(self) -> None:
        payload = copy.deepcopy(_load_json("yahoo_news_nvda.json"))
        del payload["news"][0]["providerPublishTime"]
        provider = YahooNewsProvider(client=_client_json(200, payload))

        feed = provider.fetch_symbol_news("NVDA")

        assert len(feed.items) == len(payload["news"]) - 1


# ---------------------------------------------------------------------------
# Malicious/malformed url scheme -- dropped, not a whole-feed failure
# ---------------------------------------------------------------------------


class TestYahooNewsBadUrlScheme:
    def test_an_entry_with_a_javascript_url_is_dropped_and_the_rest_still_return(self) -> None:
        """`NewsItem.url` now rejects anything but `http(s)://` -- a `javascript:` link rendered as
        a clickable article by the frontend would execute in the reader's browser. One bad entry
        must not fail the whole feed; it is dropped like any other malformed row."""
        payload = copy.deepcopy(_load_json("yahoo_news_nvda.json"))
        payload["news"][0]["link"] = "javascript:alert(1)"
        provider = YahooNewsProvider(client=_client_json(200, payload))

        feed = provider.fetch_symbol_news("NVDA")

        assert len(feed.items) == len(payload["news"]) - 1
        assert all(item.url.startswith(("http://", "https://")) for item in feed.items)

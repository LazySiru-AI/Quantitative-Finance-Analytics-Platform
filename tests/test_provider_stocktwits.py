"""Tests for the StockTwits social-message-count provider.

Every test drives an ``httpx.MockTransport`` -- no test in this file makes a network call. The
captured fixture (``tests/fixtures/news/stocktwits_aapl.json``, 12 messages, trimmed from a live
2026-08-24 response) is deep-copied before mutation so tests cannot bleed state into one another
through a shared dict. Its 12 messages carry, by direct count against the fixture: 2 labelled
``Bullish``, 2 labelled ``Bearish``, and 8 with no sentiment block at all -- the majority case this
provider must count as ``neutral`` rather than drop or misclassify.
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
)
from app.market.providers.stocktwits import StocktwitsProvider

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
# Counts
# ---------------------------------------------------------------------------


class TestStocktwitsCounts:
    def test_real_fixture_produces_expected_bullish_bearish_neutral_counts(self) -> None:
        payload = _load_json("stocktwits_aapl.json")
        provider = StocktwitsProvider(client=_client_json(200, payload))

        snapshot = provider.fetch_social("AAPL")

        assert snapshot.bullish == 2
        assert snapshot.bearish == 2
        assert snapshot.neutral == 8
        assert snapshot.total == 12
        assert snapshot.labelled == 4

    def test_unlabelled_messages_count_as_neutral_not_dropped(self) -> None:
        """8 of the fixture's 12 messages carry no sentiment block. They must all still be present
        in `total`, in the `neutral` bucket -- not silently excluded from the count."""
        payload = _load_json("stocktwits_aapl.json")
        provider = StocktwitsProvider(client=_client_json(200, payload))

        snapshot = provider.fetch_social("AAPL")

        assert snapshot.neutral == 8
        assert snapshot.total == len(payload["messages"])

    def test_message_with_entities_missing_entirely_does_not_crash(self) -> None:
        payload = copy.deepcopy(_load_json("stocktwits_aapl.json"))
        del payload["messages"][0]["entities"]
        provider = StocktwitsProvider(client=_client_json(200, payload))

        snapshot = provider.fetch_social("AAPL")

        assert snapshot.total == len(payload["messages"])
        assert snapshot.neutral == 9  # one more than the baseline 8, now that this message has no label

    def test_message_with_sentiment_null_does_not_crash(self) -> None:
        payload = copy.deepcopy(_load_json("stocktwits_aapl.json"))
        payload["messages"][1]["entities"]["sentiment"] = None
        provider = StocktwitsProvider(client=_client_json(200, payload))

        snapshot = provider.fetch_social("AAPL")

        assert snapshot.total == len(payload["messages"])

    def test_window_start_is_the_oldest_messages_created_at(self) -> None:
        payload = _load_json("stocktwits_aapl.json")
        provider = StocktwitsProvider(client=_client_json(200, payload))

        snapshot = provider.fetch_social("AAPL")

        oldest_raw = min(m["created_at"] for m in payload["messages"])
        expected = dt.datetime.fromisoformat(oldest_raw.replace("Z", "+00:00")).astimezone(dt.UTC)
        assert snapshot.window_start == expected

    def test_as_of_is_timezone_aware_utc(self) -> None:
        payload = _load_json("stocktwits_aapl.json")
        provider = StocktwitsProvider(client=_client_json(200, payload))

        snapshot = provider.fetch_social("AAPL")

        assert snapshot.as_of.tzinfo is not None
        assert snapshot.as_of.utcoffset() == dt.timedelta(0)

    def test_symbol_and_source_are_set_on_the_snapshot(self) -> None:
        payload = _load_json("stocktwits_aapl.json")
        provider = StocktwitsProvider(client=_client_json(200, payload))

        snapshot = provider.fetch_social("aapl")

        assert snapshot.symbol == "AAPL"
        assert snapshot.source == "stocktwits"

    def test_empty_messages_list_returns_all_zero_counts_and_no_window_start(self) -> None:
        payload = copy.deepcopy(_load_json("stocktwits_aapl.json"))
        payload["messages"] = []
        provider = StocktwitsProvider(client=_client_json(200, payload))

        snapshot = provider.fetch_social("AAPL")

        assert (snapshot.bullish, snapshot.bearish, snapshot.neutral, snapshot.total) == (0, 0, 0, 0)
        assert snapshot.window_start is None


class TestStocktwitsUserAgent:
    def test_user_agent_is_honest_not_a_spoofed_browser(self) -> None:
        """Mirrors `tests/test_fred.py`'s equivalent test. See `app/market/providers/fred.py`'s
        module docstring: a Chrome-shaped User-Agent is exactly the pattern that gets a keyless
        client blocked, not a way to blend in. Must never be changed to a browser string."""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=_load_json("stocktwits_aapl.json"))

        provider = StocktwitsProvider(client=_client_returning(handler))
        provider.fetch_social("AAPL")

        ua = seen[0].headers.get("user-agent", "")
        assert "@" not in ua  # not an email-style contact, but must still be honest, not spoofed
        assert ua == "investing-dashboard/0.1"
        for spoofed in ("Mozilla", "Chrome", "Safari", "WebKit"):
            assert spoofed not in ua


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


class TestStocktwitsErrorMapping:
    def test_404_raises_symbol_not_found(self) -> None:
        provider = StocktwitsProvider(client=_client_json(404, {"errors": [{"message": "Not found"}]}))
        with pytest.raises(SymbolNotFound):
            provider.fetch_social("NOPE")

    def test_429_raises_rate_limited_with_retry_after_parsed_from_header(self) -> None:
        provider = StocktwitsProvider(
            client=_client_json(429, {}, headers={"Retry-After": "30"})
        )
        with pytest.raises(RateLimited) as exc_info:
            provider.fetch_social("AAPL")
        assert exc_info.value.retry_after == 30.0

    def test_429_without_retry_after_header_leaves_retry_after_none(self) -> None:
        provider = StocktwitsProvider(client=_client_json(429, {}))
        with pytest.raises(RateLimited) as exc_info:
            provider.fetch_social("AAPL")
        assert exc_info.value.retry_after is None

    def test_500_raises_provider_unavailable(self) -> None:
        provider = StocktwitsProvider(client=_client_json(500, {}))
        with pytest.raises(ProviderUnavailable):
            provider.fetch_social("AAPL")

    def test_503_raises_provider_unavailable(self) -> None:
        provider = StocktwitsProvider(client=_client_text(503, "service unavailable"))
        with pytest.raises(ProviderUnavailable):
            provider.fetch_social("AAPL")

    def test_other_4xx_raises_provider_response_error(self) -> None:
        provider = StocktwitsProvider(client=_client_json(403, {}))
        with pytest.raises(ProviderResponseError):
            provider.fetch_social("AAPL")

    def test_timeout_raises_provider_unavailable(self) -> None:
        provider = StocktwitsProvider(
            client=_client_raising(httpx.TimeoutException("timed out"))
        )
        with pytest.raises(ProviderUnavailable):
            provider.fetch_social("AAPL")

    def test_transport_error_raises_provider_unavailable(self) -> None:
        provider = StocktwitsProvider(
            client=_client_raising(httpx.ConnectError("connection refused"))
        )
        with pytest.raises(ProviderUnavailable):
            provider.fetch_social("AAPL")

    def test_body_that_is_not_json_raises_provider_response_error(self) -> None:
        provider = StocktwitsProvider(client=_client_text(200, "<html>not json</html>"))
        with pytest.raises(ProviderResponseError):
            provider.fetch_social("AAPL")

    def test_json_body_that_is_not_an_object_raises_provider_response_error(self) -> None:
        provider = StocktwitsProvider(client=_client_json(200, [1, 2, 3]))
        with pytest.raises(ProviderResponseError):
            provider.fetch_social("AAPL")

    def test_missing_messages_key_raises_provider_response_error(self) -> None:
        payload = copy.deepcopy(_load_json("stocktwits_aapl.json"))
        del payload["messages"]
        provider = StocktwitsProvider(client=_client_json(200, payload))
        with pytest.raises(ProviderResponseError):
            provider.fetch_social("AAPL")

    def test_messages_not_a_list_raises_provider_response_error(self) -> None:
        payload = copy.deepcopy(_load_json("stocktwits_aapl.json"))
        payload["messages"] = {"unexpected": "shape"}
        provider = StocktwitsProvider(client=_client_json(200, payload))
        with pytest.raises(ProviderResponseError):
            provider.fetch_social("AAPL")

    def test_message_missing_created_at_raises_provider_response_error(self) -> None:
        payload = copy.deepcopy(_load_json("stocktwits_aapl.json"))
        del payload["messages"][0]["created_at"]
        provider = StocktwitsProvider(client=_client_json(200, payload))
        with pytest.raises(ProviderResponseError):
            provider.fetch_social("AAPL")

    def test_message_with_unparseable_created_at_raises_provider_response_error(self) -> None:
        payload = copy.deepcopy(_load_json("stocktwits_aapl.json"))
        payload["messages"][0]["created_at"] = "not-a-date"
        provider = StocktwitsProvider(client=_client_json(200, payload))
        with pytest.raises(ProviderResponseError):
            provider.fetch_social("AAPL")

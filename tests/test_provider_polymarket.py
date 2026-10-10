"""Tests for the Polymarket event-market provider.

Every test drives an ``httpx.MockTransport`` from the captured fixture at
``tests/fixtures/news/polymarket_markets.json`` or from small synthetic market objects built with
``_market()`` below -- no test in this file makes a network call. The fixture's top level is a
**bare JSON array** (not an object with a wrapper key), so ``_load_json`` is typed accordingly.
Fixture payloads are deep-copied before mutation so tests cannot bleed state into one another
through a shared list/dict.
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
    UnsupportedQuery,
)
from app.market.providers.polymarket import PolymarketProvider

FIXTURES = Path(__file__).parent / "fixtures" / "news"


def _load_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _fixture_markets() -> list[dict[str, Any]]:
    return copy.deepcopy(_load_json("polymarket_markets.json"))


def _client_returning(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _client_json(status_code: int, payload: Any, headers: dict[str, str] | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload, headers=headers or {})

    return _client_returning(handler)


def _client_raising(exc: Exception) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return _client_returning(handler)


def _client_never_called() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"no HTTP request should have been made, got {request.url}")

    return _client_returning(handler)


def _market(**overrides: Any) -> dict[str, Any]:
    """A minimal synthetic Polymarket market row, shaped like the real fixture's entries.

    Only the keys this provider actually reads are included; real rows carry ~60 keys, and a
    synthetic row that included them all would obscure which fields the test cares about.
    """
    base: dict[str, Any] = {
        "id": "999999",
        "conditionId": "0xsynthetic",
        "question": "Will the synthetic test event happen?",
        "slug": "will-the-synthetic-test-event-happen",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.5", "0.5"]',
        "volume": "123.45",
        "endDate": "2026-12-31T23:59:00Z",
        "active": True,
        "closed": False,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Real fixture
# ---------------------------------------------------------------------------


class TestPolymarketFixtureParsing:
    def test_real_fixture_parses_into_event_markets_none_skipped(self) -> None:
        """All five captured markets are plain Yes/No binaries, so all five must parse."""
        provider = PolymarketProvider(client=_client_json(200, _fixture_markets()))
        # Every question in the fixture happens to contain the letter "e", so this topic matches
        # all five without depending on exact wording.
        results = provider.fetch_events("e", limit=10)
        assert len(results) == 5
        assert all(m.source == "polymarket" for m in results)

    def test_probability_is_the_yes_outcome_price_for_the_first_fixture_market(self) -> None:
        """The first market in the fixture (`will-trump-say-race-or-indy-during-rose-garden-event`)
        has `outcomePrices` `'["0.58", "0.42"]'` paired with `outcomes` `'["Yes", "No"]'` -- the Yes
        price, 0.58, must come through untouched."""
        provider = PolymarketProvider(client=_client_json(200, _fixture_markets()))
        results = provider.fetch_events("e", limit=10)
        trump_market = next(m for m in results if m.slug == "will-trump-say-race-or-indy-during-rose-garden-event")
        assert trump_market.probability == pytest.approx(0.58)

    def test_results_are_ordered_by_volume_descending(self) -> None:
        provider = PolymarketProvider(client=_client_json(200, _fixture_markets()))
        results = provider.fetch_events("e", limit=10)
        volumes = [m.volume for m in results]
        assert volumes == sorted(volumes, reverse=True)
        # The Silkeborg/Broendby football market has by far the largest volume in the fixture
        # ("9999.280787000007" vs everything else near "99.99").
        assert results[0].slug == "den-bro-sif-2026-08-24-sif"

    def test_volume_converts_from_its_string_form_to_a_float(self) -> None:
        provider = PolymarketProvider(client=_client_json(200, _fixture_markets()))
        results = provider.fetch_events("e", limit=10)
        silkeborg = next(m for m in results if m.slug == "den-bro-sif-2026-08-24-sif")
        assert silkeborg.volume == pytest.approx(9999.280787000007)

    def test_resolution_date_is_a_date_derived_from_end_date(self) -> None:
        provider = PolymarketProvider(client=_client_json(200, _fixture_markets()))
        results = provider.fetch_events("e", limit=10)
        trump_market = next(m for m in results if m.slug == "will-trump-say-race-or-indy-during-rose-garden-event")
        assert trump_market.resolution_date == dt.date(2026, 8, 24)

    def test_as_of_is_timezone_aware_utc(self) -> None:
        provider = PolymarketProvider(client=_client_json(200, _fixture_markets()))
        results = provider.fetch_events("e", limit=10)
        for market in results:
            assert market.as_of.tzinfo is not None
            assert market.as_of.utcoffset() == dt.timedelta(0)


# ---------------------------------------------------------------------------
# Yes-outcome matched by label, not index
# ---------------------------------------------------------------------------


class TestPolymarketYesOutcomeMatchedByLabel:
    def test_yes_at_index_one_is_matched_by_label_not_position(self) -> None:
        """A market where Yes is *not* the first outcome must still resolve to the Yes price --
        proving the lookup matches the `"Yes"` label rather than assuming index 0."""
        market = _market(outcomes='["No", "Yes"]', outcomePrices='["0.35", "0.65"]')
        provider = PolymarketProvider(client=_client_json(200, [market]))
        results = provider.fetch_events("synthetic", limit=10)
        assert len(results) == 1
        assert results[0].probability == pytest.approx(0.65)

    def test_market_with_no_yes_outcome_is_skipped_not_mismapped(self) -> None:
        """A multi-outcome bracket market (no `"Yes"` among its outcomes) must be dropped from the
        results rather than reporting some other outcome's price as `probability`."""
        no_yes_market = _market(
            slug="bracket-market-no-yes",
            outcomes='["Above", "Below", "Flat"]',
            outcomePrices='["0.2", "0.5", "0.3"]',
        )
        ordinary_market = _market()
        provider = PolymarketProvider(client=_client_json(200, [no_yes_market, ordinary_market]))
        results = provider.fetch_events("synthetic", limit=10)
        assert len(results) == 1
        assert results[0].slug == "will-the-synthetic-test-event-happen"


# ---------------------------------------------------------------------------
# Malformed payloads
# ---------------------------------------------------------------------------


class TestPolymarketMalformedPayloads:
    def test_probability_outside_unit_interval_raises_rather_than_clamping(self) -> None:
        market = _market(outcomePrices='["1.5", "-0.5"]')
        provider = PolymarketProvider(client=_client_json(200, [market]))
        with pytest.raises(ProviderResponseError):
            provider.fetch_events("synthetic", limit=10)

    def test_outcome_prices_that_is_not_valid_json_raises_provider_response_error(self) -> None:
        market = _market(outcomePrices="not-json-at-all")
        provider = PolymarketProvider(client=_client_json(200, [market]))
        with pytest.raises(ProviderResponseError):
            provider.fetch_events("synthetic", limit=10)

    def test_outcomes_that_is_a_plain_list_not_a_json_string_raises(self) -> None:
        """The traps this provider guards against are specifically that `outcomes`/`outcomePrices`
        arrive as JSON-*encoded strings*; a response that (today or in a future schema) sent them as
        plain JSON arrays instead is just as much a shape this parser does not understand."""
        market = _market(outcomes=["Yes", "No"])
        provider = PolymarketProvider(client=_client_json(200, [market]))
        with pytest.raises(ProviderResponseError):
            provider.fetch_events("synthetic", limit=10)

    def test_top_level_response_that_is_not_a_json_array_raises(self) -> None:
        provider = PolymarketProvider(client=_client_json(200, {"markets": []}))
        with pytest.raises(ProviderResponseError):
            provider.fetch_events("synthetic", limit=10)

    def test_volume_missing_is_none_not_an_error(self) -> None:
        market = _market()
        del market["volume"]
        provider = PolymarketProvider(client=_client_json(200, [market]))
        results = provider.fetch_events("synthetic", limit=10)
        assert results[0].volume is None

    def test_end_date_missing_gives_none_resolution_date(self) -> None:
        market = _market()
        del market["endDate"]
        provider = PolymarketProvider(client=_client_json(200, [market]))
        results = provider.fetch_events("synthetic", limit=10)
        assert results[0].resolution_date is None


# ---------------------------------------------------------------------------
# Topic handling
# ---------------------------------------------------------------------------


class TestPolymarketTopicHandling:
    def test_empty_topic_raises_unsupported_query_without_any_request(self) -> None:
        provider = PolymarketProvider(client=_client_never_called())
        with pytest.raises(UnsupportedQuery):
            provider.fetch_events("", limit=10)

    def test_whitespace_only_topic_raises_unsupported_query(self) -> None:
        provider = PolymarketProvider(client=_client_never_called())
        with pytest.raises(UnsupportedQuery):
            provider.fetch_events("   ", limit=10)

    def test_topic_matching_nothing_returns_empty_tuple_not_an_error(self) -> None:
        provider = PolymarketProvider(client=_client_json(200, _fixture_markets()))
        results = provider.fetch_events("zzz-no-such-keyword-zzz", limit=10)
        assert results == ()

    def test_topic_match_is_case_insensitive(self) -> None:
        provider = PolymarketProvider(client=_client_json(200, [_market(question="Will SYNTHETIC Event Happen?")]))
        results = provider.fetch_events("synthetic", limit=10)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


class TestPolymarketErrorMapping:
    def test_429_raises_rate_limited_with_retry_after(self) -> None:
        provider = PolymarketProvider(client=_client_json(429, [], headers={"Retry-After": "12"}))
        with pytest.raises(RateLimited) as exc_info:
            provider.fetch_events("synthetic", limit=10)
        assert exc_info.value.retry_after == 12.0

    def test_500_raises_provider_unavailable(self) -> None:
        provider = PolymarketProvider(client=_client_json(500, []))
        with pytest.raises(ProviderUnavailable):
            provider.fetch_events("synthetic", limit=10)

    def test_timeout_raises_provider_unavailable(self) -> None:
        provider = PolymarketProvider(
            client=_client_raising(httpx.TimeoutException("timed out"))
        )
        with pytest.raises(ProviderUnavailable):
            provider.fetch_events("synthetic", limit=10)

    def test_transport_error_raises_provider_unavailable(self) -> None:
        provider = PolymarketProvider(
            client=_client_raising(httpx.ConnectError("connection refused"))
        )
        with pytest.raises(ProviderUnavailable):
            provider.fetch_events("synthetic", limit=10)

    def test_non_json_body_raises_provider_response_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="not json")

        provider = PolymarketProvider(client=_client_returning(handler))
        with pytest.raises(ProviderResponseError):
            provider.fetch_events("synthetic", limit=10)


# ---------------------------------------------------------------------------
# User-Agent
# ---------------------------------------------------------------------------


class TestPolymarketUserAgent:
    def test_user_agent_is_honest_not_a_spoofed_browser(self) -> None:
        """See `app/market/providers/fred.py`'s docstring for why this is a codebase-wide rule:
        a spoofed browser User-Agent is exactly the pattern that gets a client blocked."""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=[])

        provider = PolymarketProvider(client=_client_returning(handler))
        provider.fetch_events("synthetic", limit=10)

        ua = seen[0].headers.get("user-agent", "")
        assert ua == "investing-dashboard/0.1"
        for spoofed in ("Mozilla", "Chrome", "Safari", "WebKit"):
            assert spoofed not in ua

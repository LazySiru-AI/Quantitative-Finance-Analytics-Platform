"""Tests for the Nasdaq earnings calendar provider.

Every test drives an ``httpx.MockTransport`` against fixtures in ``tests/fixtures/market/`` -- no
test in this file makes a network call.

``nasdaq_earnings_day.json`` and ``nasdaq_earnings_empty.json`` are exactly what was captured live
from ``https://api.nasdaq.com/api/calendar/earnings`` in August 2026 (a real Wednesday and a real
Saturday, respectively), pretty-printed but otherwise untouched. The remaining tests build small
inline payloads for shapes that are real (per the live probe that specified this provider) but were
not the ones captured in either saved fixture -- an unrecognised ``time`` token and a row missing
``symbol``.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from app.market.calendar_models import (
    CalendarEvent,
    EventConfidence,
    EventKind,
    EventSource,
    SessionTiming,
)
from app.market.providers.base import (
    ProviderResponseError,
    ProviderUnavailable,
    RateLimited,
)
from app.market.providers.nasdaq_earnings import NasdaqEarningsProvider

FIXTURES = Path(__file__).parent / "fixtures" / "market"

DAY = dt.date(2026, 8, 26)
"""The calendar day the ``nasdaq_earnings_day.json`` fixture was captured for."""

WEEKEND = dt.date(2026, 8, 29)
"""The calendar day the ``nasdaq_earnings_empty.json`` fixture was captured for."""


def _load_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _client_returning(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _client_json(status_code: int, payload: dict) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload)

    return _client_returning(handler)


def _client_text(status_code: int, text: str) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=text)

    return _client_returning(handler)


def _client_capturing_url(
    status_code: int, payload: dict
) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status_code, json=payload)

    return _client_returning(handler), seen


# ---------------------------------------------------------------------------
# A populated day
# ---------------------------------------------------------------------------


class TestPopulatedDay:
    def test_parses_expected_rows(self) -> None:
        payload = _load_json("nasdaq_earnings_day.json")
        provider = NasdaqEarningsProvider(_client_json(200, payload))

        events = provider.fetch_earnings_for_day(DAY)

        by_symbol = {event.symbol: event for event in events}
        assert len(events) == len(payload["data"]["rows"])

        # NVDA: real after-hours row with a real consensus estimate.
        nvda = by_symbol["NVDA"]
        assert nvda.symbol == "NVDA"
        assert nvda.timing is SessionTiming.AFTER_CLOSE
        assert nvda.detail == "consensus EPS $2.09"
        assert nvda.kind is EventKind.EARNINGS
        assert nvda.source is EventSource.NASDAQ
        assert nvda.confidence is EventConfidence.CONFIRMED
        assert nvda.title == "NVDA earnings"
        assert nvda.date == DAY
        assert nvda.end_date is None

        # WSM: real pre-market row with a real consensus estimate.
        wsm = by_symbol["WSM"]
        assert wsm.symbol == "WSM"
        assert wsm.timing is SessionTiming.BEFORE_OPEN
        assert wsm.detail == "consensus EPS $2.05"

    def test_all_events_are_frozen_and_well_typed(self) -> None:
        payload = _load_json("nasdaq_earnings_day.json")
        provider = NasdaqEarningsProvider(_client_json(200, payload))

        events = provider.fetch_earnings_for_day(DAY)

        assert events, "fixture should contain rows"
        for event in events:
            assert isinstance(event, CalendarEvent)
            assert event.symbol == event.symbol.upper()

    def test_requests_the_day_as_a_query_param(self) -> None:
        payload = _load_json("nasdaq_earnings_day.json")
        client, seen = _client_capturing_url(200, payload)
        provider = NasdaqEarningsProvider(client)

        provider.fetch_earnings_for_day(DAY)

        assert len(seen) == 1
        assert seen[0].url.params["date"] == "2026-08-26"


# ---------------------------------------------------------------------------
# Absent-value handling
# ---------------------------------------------------------------------------


class TestAbsentEps:
    def test_empty_string_eps_forecast_yields_none_detail(self) -> None:
        """TRMD in the real fixture has epsForecast == "" (Nasdaq's actual spelling for
        'no estimate yet' on this field, observed live far more often than the literal 'N/A')."""
        payload = _load_json("nasdaq_earnings_day.json")
        provider = NasdaqEarningsProvider(_client_json(200, payload))

        events = provider.fetch_earnings_for_day(DAY)

        trmd = next(event for event in events if event.symbol == "TRMD")
        assert trmd.detail is None
        assert trmd.timing is SessionTiming.BEFORE_OPEN

    def test_literal_na_eps_forecast_yields_none_detail(self) -> None:
        """Defensive: Nasdaq spells missing values as the literal string 'N/A' on other fields in
        this same payload family (lastYearEPS, noOfEsts) -- honour it on epsForecast too, in case it
        ever appears there, rather than emitting 'consensus EPS N/A'."""
        payload = _load_json("nasdaq_earnings_day.json")
        payload["data"]["rows"] = [
            {
                "time": "time-after-hours",
                "symbol": "ZZZZ",
                "epsForecast": "N/A",
            }
        ]
        provider = NasdaqEarningsProvider(_client_json(200, payload))

        events = provider.fetch_earnings_for_day(DAY)

        assert len(events) == 1
        assert events[0].detail is None
        assert "N/A" not in (events[0].detail or "")


# ---------------------------------------------------------------------------
# Quiet days
# ---------------------------------------------------------------------------


class TestQuietDay:
    def test_weekend_response_returns_empty_tuple(self) -> None:
        """Real Saturday capture: data.rows is null, not an error."""
        payload = _load_json("nasdaq_earnings_empty.json")
        assert payload["data"]["rows"] is None  # sanity-check the fixture's real shape
        provider = NasdaqEarningsProvider(_client_json(200, payload))

        events = provider.fetch_earnings_for_day(WEEKEND)

        assert events == ()
        assert provider.last_skipped == 0

    def test_null_data_also_returns_empty_tuple(self) -> None:
        """Not observed live, but plausible per the same convention -- data itself null."""
        provider = NasdaqEarningsProvider(_client_json(200, {"data": None, "message": None}))

        events = provider.fetch_earnings_for_day(WEEKEND)

        assert events == ()


# ---------------------------------------------------------------------------
# Timing token mapping
# ---------------------------------------------------------------------------


class TestTimingMapping:
    def test_time_not_supplied_maps_to_unknown(self) -> None:
        """TCOM in the real fixture carries the real 'time-not-supplied' token."""
        payload = _load_json("nasdaq_earnings_day.json")
        provider = NasdaqEarningsProvider(_client_json(200, payload))

        events = provider.fetch_earnings_for_day(DAY)

        tcom = next(event for event in events if event.symbol == "TCOM")
        assert tcom.timing is SessionTiming.UNKNOWN

    def test_unrecognised_token_maps_to_unknown(self) -> None:
        """A token this module has never seen must not be guessed at."""
        payload = {
            "data": {
                "asOf": "Wed, Aug 26, 2026",
                "headers": {},
                "rows": [
                    {"time": "time-during-lunch", "symbol": "ACME", "epsForecast": "$1.00"},
                ],
            },
            "message": None,
        }
        provider = NasdaqEarningsProvider(_client_json(200, payload))

        events = provider.fetch_earnings_for_day(DAY)

        assert len(events) == 1
        assert events[0].timing is SessionTiming.UNKNOWN

    def test_missing_time_field_maps_to_unknown(self) -> None:
        payload = {
            "data": {"rows": [{"symbol": "ACME", "epsForecast": "$1.00"}]},
            "message": None,
        }
        provider = NasdaqEarningsProvider(_client_json(200, payload))

        events = provider.fetch_earnings_for_day(DAY)

        assert events[0].timing is SessionTiming.UNKNOWN


# ---------------------------------------------------------------------------
# Skipped rows
# ---------------------------------------------------------------------------


class TestSkippedRows:
    def test_row_missing_symbol_is_skipped_not_fatal(self) -> None:
        payload = {
            "data": {
                "rows": [
                    {"time": "time-after-hours", "symbol": "GOOD", "epsForecast": "$1.00"},
                    {"time": "time-after-hours", "epsForecast": "$2.00"},  # no symbol
                    {"time": "time-after-hours", "symbol": "", "epsForecast": "$3.00"},  # blank
                ],
            },
            "message": None,
        }
        provider = NasdaqEarningsProvider(_client_json(200, payload))

        events = provider.fetch_earnings_for_day(DAY)

        assert [event.symbol for event in events] == ["GOOD"]
        assert provider.last_skipped == 2

    def test_last_skipped_resets_between_calls(self) -> None:
        bad_payload = {
            "data": {"rows": [{"time": "time-after-hours", "epsForecast": "$1.00"}]},
            "message": None,
        }
        good_payload = _load_json("nasdaq_earnings_day.json")

        provider = NasdaqEarningsProvider(_client_json(200, bad_payload))
        provider.fetch_earnings_for_day(DAY)
        assert provider.last_skipped == 1

        provider._client = _client_json(200, good_payload)
        provider.fetch_earnings_for_day(DAY)
        assert provider.last_skipped == 0


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


class TestErrorMapping:
    def test_429_raises_rate_limited(self) -> None:
        provider = NasdaqEarningsProvider(_client_text(429, "rate limited"))

        with pytest.raises(RateLimited):
            provider.fetch_earnings_for_day(DAY)

    def test_429_carries_retry_after(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="rate limited", headers={"Retry-After": "30"})

        provider = NasdaqEarningsProvider(_client_returning(handler))

        with pytest.raises(RateLimited) as exc_info:
            provider.fetch_earnings_for_day(DAY)
        assert exc_info.value.retry_after == 30.0

    def test_503_raises_provider_unavailable(self) -> None:
        provider = NasdaqEarningsProvider(_client_text(503, "service unavailable"))

        with pytest.raises(ProviderUnavailable):
            provider.fetch_earnings_for_day(DAY)

    def test_500_raises_provider_unavailable(self) -> None:
        provider = NasdaqEarningsProvider(_client_text(500, "internal error"))

        with pytest.raises(ProviderUnavailable):
            provider.fetch_earnings_for_day(DAY)

    def test_malformed_json_raises_provider_response_error(self) -> None:
        provider = NasdaqEarningsProvider(_client_text(200, "<html>not json</html>"))

        with pytest.raises(ProviderResponseError):
            provider.fetch_earnings_for_day(DAY)

    def test_200_missing_data_key_raises_provider_response_error(self) -> None:
        provider = NasdaqEarningsProvider(_client_json(200, {"message": None}))

        with pytest.raises(ProviderResponseError):
            provider.fetch_earnings_for_day(DAY)

    def test_200_non_list_rows_raises_provider_response_error(self) -> None:
        provider = NasdaqEarningsProvider(
            _client_json(200, {"data": {"rows": "not-a-list"}})
        )

        with pytest.raises(ProviderResponseError):
            provider.fetch_earnings_for_day(DAY)

    def test_timeout_raises_provider_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timed out", request=request)

        provider = NasdaqEarningsProvider(_client_returning(handler))

        with pytest.raises(ProviderUnavailable):
            provider.fetch_earnings_for_day(DAY)

    def test_400_raises_provider_response_error(self) -> None:
        provider = NasdaqEarningsProvider(_client_text(400, "bad request"))

        with pytest.raises(ProviderResponseError):
            provider.fetch_earnings_for_day(DAY)

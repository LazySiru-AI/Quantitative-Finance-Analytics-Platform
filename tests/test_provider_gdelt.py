"""Tests for the GDELT global/macro news provider.

Every test drives an ``httpx.MockTransport`` from the captured fixtures in
``tests/fixtures/news/`` -- no test in this file makes a network call, and none sleeps: the
5-second-per-IP throttle described in ``app/market/providers/gdelt.py`` is a real-world pacing
concern, not something a unit test should ever wait out.
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

from app.market.news_models import NewsFeed, NewsVolumeSeries
from app.market.providers.base import (
    ProviderResponseError,
    ProviderUnavailable,
    RateLimited,
    UnsupportedQuery,
)
from app.market.providers.gdelt import COVERAGE_START, GdeltProvider

FIXTURES = Path(__file__).parent / "fixtures" / "news"


def _load_json(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _client_returning(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _client_json(
    status_code: int, payload: dict[str, Any], headers: dict[str, str] | None = None
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload, headers=headers or {})

    return _client_returning(handler)


def _client_text(
    status_code: int, body: str, headers: dict[str, str] | None = None
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=body, headers=headers or {})

    return _client_returning(handler)


def _client_raising(exc: Exception) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return _client_returning(handler)


NVIDIA_FIXTURE = "gdelt_nvidia.json"
RATE_LIMITED_FIXTURE = "gdelt_rate_limited.txt"


class TestFetchQueryNewsParsesTheRealFixture:
    def test_the_captured_fixture_parses_to_ten_news_items(self) -> None:
        payload = _load_json(NVIDIA_FIXTURE)
        provider = GdeltProvider(client=_client_json(200, payload))

        feed = provider.fetch_query_news("nvidia")

        assert isinstance(feed, NewsFeed)
        assert len(feed.items) == 10

    def test_published_is_tz_aware_utc_decoded_from_seendate(self) -> None:
        payload = _load_json(NVIDIA_FIXTURE)
        first_seendate = payload["articles"][0]["seendate"]
        assert first_seendate == "20260822T060000Z"
        provider = GdeltProvider(client=_client_json(200, payload))

        feed = provider.fetch_query_news("nvidia")

        first_item = feed.items[0]
        assert first_item.published == dt.datetime(2026, 8, 22, 6, 0, 0, tzinfo=dt.UTC)
        assert first_item.published.tzinfo is not None

    def test_publisher_comes_from_domain_and_source_is_gdelt(self) -> None:
        payload = _load_json(NVIDIA_FIXTURE)
        provider = GdeltProvider(client=_client_json(200, payload))

        feed = provider.fetch_query_news("nvidia")

        first_item = feed.items[0]
        assert first_item.publisher == "finance.yahoo.com"
        assert first_item.source == "gdelt"
        assert first_item.title == payload["articles"][0]["title"]
        assert first_item.url == payload["articles"][0]["url"]

    def test_feed_source_is_gdelt(self) -> None:
        payload = _load_json(NVIDIA_FIXTURE)
        provider = GdeltProvider(client=_client_json(200, payload))

        feed = provider.fetch_query_news("nvidia")

        assert feed.source == "gdelt"

    def test_an_empty_articles_list_is_a_valid_empty_feed_not_an_error(self) -> None:
        provider = GdeltProvider(client=_client_json(200, {"articles": []}))

        feed = provider.fetch_query_news("obscure query with no coverage")

        assert feed.items == ()
        assert isinstance(feed, NewsFeed)


class TestFetchSymbolNewsIsUnsupported:
    def test_fetch_symbol_news_always_raises_unsupported_query(self) -> None:
        provider = GdeltProvider(client=_client_raising(AssertionError("must not hit the network")))

        with pytest.raises(UnsupportedQuery):
            provider.fetch_symbol_news("NVDA")

    def test_fetch_symbol_news_never_makes_a_request(self) -> None:
        provider = GdeltProvider(client=_client_raising(AssertionError("no request expected")))

        with pytest.raises(UnsupportedQuery):
            provider.fetch_symbol_news("AAPL", limit=5)


class TestEmptyQueryIsUnsupported:
    def test_empty_string_query_raises_unsupported_query(self) -> None:
        provider = GdeltProvider(client=_client_raising(AssertionError("must not hit the network")))

        with pytest.raises(UnsupportedQuery):
            provider.fetch_query_news("")

    def test_whitespace_only_query_raises_unsupported_query(self) -> None:
        provider = GdeltProvider(client=_client_raising(AssertionError("must not hit the network")))

        with pytest.raises(UnsupportedQuery):
            provider.fetch_query_news("   ")


class TestThrottleDetectionIsIndependentOfStatusCode:
    """The important cases: GDELT's throttle message has been observed on both 200 and 429, with
    no content-type header and a plain-text body. The parser must catch both the same way."""

    def test_the_captured_throttle_body_served_with_http_200_raises_rate_limited(self) -> None:
        body = _load_text(RATE_LIMITED_FIXTURE)
        assert "limit requests to one every 5 seconds" in body
        provider = GdeltProvider(client=_client_text(200, body))

        with pytest.raises(RateLimited):
            provider.fetch_query_news("nvidia")

    def test_the_same_throttle_body_served_with_http_429_also_raises_rate_limited(self) -> None:
        body = _load_text(RATE_LIMITED_FIXTURE)
        provider = GdeltProvider(client=_client_text(429, body))

        with pytest.raises(RateLimited):
            provider.fetch_query_news("nvidia")

    def test_rate_limited_is_never_misclassified_as_provider_response_error(self) -> None:
        """A RateLimited that gets swallowed into ProviderResponseError loses retry_after and the
        honest 'you are being throttled' explanation -- both classes are caught here to prove the
        exception raised really is the more specific RateLimited, not just some ProviderUnavailable
        subclass."""
        body = _load_text(RATE_LIMITED_FIXTURE)
        provider = GdeltProvider(client=_client_text(200, body))

        try:
            provider.fetch_query_news("nvidia")
        except RateLimited:
            pass
        except ProviderResponseError:
            pytest.fail("throttle body was misclassified as ProviderResponseError")

    def test_retry_after_header_is_surfaced_when_present(self) -> None:
        body = _load_text(RATE_LIMITED_FIXTURE)
        provider = GdeltProvider(client=_client_text(429, body, headers={"Retry-After": "5"}))

        with pytest.raises(RateLimited) as excinfo:
            provider.fetch_query_news("nvidia")

        assert excinfo.value.retry_after == 5.0

    def test_retry_after_is_none_when_the_header_is_absent(self) -> None:
        body = _load_text(RATE_LIMITED_FIXTURE)
        provider = GdeltProvider(client=_client_text(200, body))

        with pytest.raises(RateLimited) as excinfo:
            provider.fetch_query_news("nvidia")

        assert excinfo.value.retry_after is None


class TestAsOfBoundsTheFeed:
    def test_as_of_genuinely_drops_a_newer_item(self) -> None:
        payload = _load_json(NVIDIA_FIXTURE)
        provider = GdeltProvider(client=_client_json(200, payload))

        unbounded = provider.fetch_query_news("nvidia")
        newest = max(item.published for item in unbounded.items)
        cutoff = newest - dt.timedelta(seconds=1)

        bounded = provider.fetch_query_news("nvidia", as_of=cutoff)

        assert len(bounded.items) < len(unbounded.items)
        assert all(item.published <= cutoff for item in bounded.items)

    def test_naive_as_of_raises_value_error(self) -> None:
        payload = _load_json(NVIDIA_FIXTURE)
        provider = GdeltProvider(client=_client_json(200, payload))

        with pytest.raises(ValueError):
            provider.fetch_query_news("nvidia", as_of=dt.datetime(2026, 1, 1))

    def test_as_of_none_returns_everything(self) -> None:
        payload = _load_json(NVIDIA_FIXTURE)
        provider = GdeltProvider(client=_client_json(200, payload))

        feed = provider.fetch_query_news("nvidia", as_of=None)

        assert len(feed.items) == 10


class TestMalformedResponsesAreTyped:
    def test_genuinely_malformed_json_that_is_not_the_throttle_message_raises_provider_response_error(
        self,
    ) -> None:
        provider = GdeltProvider(client=_client_text(200, "{not valid json at all"))

        with pytest.raises(ProviderResponseError):
            provider.fetch_query_news("nvidia")

    def test_a_json_response_that_is_not_an_object_raises_provider_response_error(self) -> None:
        provider = GdeltProvider(client=_client_json(200, {"articles": "not a list"}))

        with pytest.raises(ProviderResponseError):
            provider.fetch_query_news("nvidia")

    def test_an_article_missing_required_fields_raises_provider_response_error(self) -> None:
        provider = GdeltProvider(
            client=_client_json(200, {"articles": [{"title": "no url or seendate here"}]})
        )

        with pytest.raises(ProviderResponseError):
            provider.fetch_query_news("nvidia")

    def test_an_unparseable_seendate_raises_provider_response_error(self) -> None:
        provider = GdeltProvider(
            client=_client_json(
                200,
                {
                    "articles": [
                        {
                            "title": "t",
                            "url": "https://example.com/a",
                            "seendate": "not-a-timestamp",
                            "domain": "example.com",
                        }
                    ]
                },
            )
        )

        with pytest.raises(ProviderResponseError):
            provider.fetch_query_news("nvidia")


class TestUpstreamUnavailability:
    def test_5xx_raises_provider_unavailable(self) -> None:
        provider = GdeltProvider(client=_client_text(503, "internal error"))

        with pytest.raises(ProviderUnavailable):
            provider.fetch_query_news("nvidia")

    def test_timeout_raises_provider_unavailable(self) -> None:
        provider = GdeltProvider(client=_client_raising(httpx.TimeoutException("timed out")))

        with pytest.raises(ProviderUnavailable):
            provider.fetch_query_news("nvidia")

    def test_transport_error_raises_provider_unavailable(self) -> None:
        provider = GdeltProvider(
            client=_client_raising(httpx.TransportError("connection reset"))
        )

        with pytest.raises(ProviderUnavailable):
            provider.fetch_query_news("nvidia")

    def test_unexpected_4xx_raises_provider_response_error(self) -> None:
        provider = GdeltProvider(client=_client_text(400, "bad request, not a throttle"))

        with pytest.raises(ProviderResponseError):
            provider.fetch_query_news("nvidia")


class TestMalformedRowsAreDroppedNotFatal:
    """A bad row must not destroy the good rows beside it.

    These tests exist because the two in :class:`TestMalformedResponsesAreTyped` that assert a
    ``ProviderResponseError`` for a bad article each pass a list of *exactly one* article -- so once
    the row policy changed from "raise" to "drop, unless everything dropped", they kept passing via
    the all-rows-dropped schema guard rather than via the behaviour they name. They are still correct
    assertions; they are just no longer discriminating on their own. Each test below pairs a bad row
    with at least one good one, which is the case that actually tells the two policies apart.
    """

    def test_one_unparseable_seendate_drops_that_row_and_keeps_the_others(self) -> None:
        payload = copy.deepcopy(_load_json("gdelt_nvidia.json"))
        good = len(payload["articles"])
        payload["articles"].append(
            {"title": "t", "url": "https://example.com/x", "seendate": "not-a-timestamp"}
        )
        provider = GdeltProvider(client=_client_json(200, payload))

        feed = provider.fetch_query_news("NVIDIA")

        assert len(feed.items) == good
        assert all("example.com" not in item.url for item in feed.items)

    def test_one_row_missing_required_fields_drops_that_row_and_keeps_the_others(self) -> None:
        payload = copy.deepcopy(_load_json("gdelt_nvidia.json"))
        good = len(payload["articles"])
        payload["articles"].append({"domain": "example.com"})
        provider = GdeltProvider(client=_client_json(200, payload))

        feed = provider.fetch_query_news("NVIDIA")

        assert len(feed.items) == good

    def test_a_non_dict_row_is_dropped_rather_than_raising(self) -> None:
        payload = copy.deepcopy(_load_json("gdelt_nvidia.json"))
        good = len(payload["articles"])
        payload["articles"].append("this is a string, not an article")
        provider = GdeltProvider(client=_client_json(200, payload))

        feed = provider.fetch_query_news("NVIDIA")

        assert len(feed.items) == good

    def test_dropping_a_row_surfaces_a_warning_rather_than_going_quiet(self) -> None:
        payload = copy.deepcopy(_load_json("gdelt_nvidia.json"))
        payload["articles"].append(
            {"title": "t", "url": "https://example.com/x", "seendate": "not-a-timestamp"}
        )
        provider = GdeltProvider(client=_client_json(200, payload))

        feed = provider.fetch_query_news("NVIDIA")

        assert [w.kind for w in feed.warnings] == ["partial_parse"]
        assert "1 of 11" in feed.warnings[0].message

    def test_a_clean_payload_carries_no_partial_parse_warning(self) -> None:
        provider = GdeltProvider(client=_client_json(200, _load_json("gdelt_nvidia.json")))

        feed = provider.fetch_query_news("NVIDIA")

        assert feed.warnings == ()

    def test_a_row_with_a_javascript_url_is_dropped_and_the_rest_still_return(self) -> None:
        """`NewsItem.url` rejects anything but `http(s)://` -- see that class's own docstring on why
        a `javascript:`/`data:` link must never reach the frontend as a clickable article. This row
        otherwise parses cleanly (title, url, seendate all present and well-formed), so this is the
        one case in this class where the drop happens at `NewsItem` construction, not inside
        `_parse_article`'s own field checks -- and it must still be dropped, not raised."""
        payload = copy.deepcopy(_load_json("gdelt_nvidia.json"))
        good = len(payload["articles"])
        payload["articles"].append(
            {"title": "t", "url": "javascript:alert(1)", "seendate": "20260822T060000Z"}
        )
        provider = GdeltProvider(client=_client_json(200, payload))

        feed = provider.fetch_query_news("NVIDIA")

        assert len(feed.items) == good
        assert all(item.url.startswith(("http://", "https://")) for item in feed.items)

    def test_every_row_dropped_from_a_non_empty_list_still_raises(self) -> None:
        """The Stooq case: a well-formed envelope whose every row is unusable is a schema change,
        not "no news". Reporting it as an empty feed is the failure `providers/base.py` opens by
        warning about."""
        provider = GdeltProvider(
            client=_client_json(200, {"articles": [{"nope": 1}, {"also": "nope"}]})
        )

        with pytest.raises(ProviderResponseError, match="schema has probably changed"):
            provider.fetch_query_news("NVIDIA")


# ---------------------------------------------------------------------------
# fetch_volume_series -- the historical surface D-news needs
# ---------------------------------------------------------------------------


class TestVolumeSeriesCoverageBoundary:
    """**GDELT's archive begins 2017-01-01, and three of the eight programme windows end before it.**

    Established by bisection against the live endpoint on 2026-08-26 -- ``2016-12-15`` is refused
    with the plain-text body ``"Invalid query start date."``, ``2017-01-01`` returns JSON. That
    boundary is not a detail: ``gfc``, ``chop-2011`` and ``chop-2015`` are entirely before it, and
    they are the deepest drawdown available plus *both* sideways windows. These tests pin the
    behaviour that makes that visible to a caller instead of silent.
    """

    def test_window_entirely_before_coverage_returns_no_points_without_requesting(self) -> None:
        """`gfc` cannot be answered, and asking GDELT anyway would only burn the 5s/IP throttle."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError(f"no request should be sent for an unanswerable window: {request.url}")

        provider = GdeltProvider(client=_client_returning(handler))
        series = provider.fetch_volume_series(
            "Nvidia", start=dt.date(2007, 10, 9), end=dt.date(2009, 3, 9)
        )

        assert isinstance(series, NewsVolumeSeries)
        assert series.points == ()
        assert series.covered_days == 0
        assert series.requested_start_before_coverage is True
        assert series.coverage_start == COVERAGE_START

    def test_empty_points_are_distinguishable_from_a_genuinely_quiet_window(self) -> None:
        """The whole point of the coverage guard: two empty results, opposite meanings.

        Without `requested_start_before_coverage` a study cannot tell "this window predates the
        archive" from "nothing matched", and would count an unanswerable window as a measured null.
        """
        unanswerable = GdeltProvider(client=_client_json(200, {"timeline": []})).fetch_volume_series(
            "Nvidia", start=dt.date(2011, 5, 26), end=dt.date(2012, 6, 6)
        )
        answered_but_empty = GdeltProvider(
            client=_client_json(200, {"timeline": []})
        ).fetch_volume_series("Nvidia", start=dt.date(2022, 1, 3), end=dt.date(2022, 10, 12))

        assert unanswerable.points == answered_but_empty.points == ()
        assert unanswerable.requested_start_before_coverage is True
        assert answered_but_empty.requested_start_before_coverage is False

    def test_straddling_window_is_clamped_and_still_reports_the_gap(self) -> None:
        """A window that starts before coverage and ends after it must not look complete."""
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(dict(request.url.params))
            return httpx.Response(200, json=_load_json("gdelt_timeline_volraw.json"))

        provider = GdeltProvider(client=_client_returning(handler))
        series = provider.fetch_volume_series(
            "Nvidia", start=dt.date(2015, 4, 7), end=dt.date(2024, 1, 15)
        )

        # Clamped to the archive's start, not sent as requested -- sending 2015 would earn the
        # plain-text refusal this provider deliberately never triggers.
        assert captured["startdatetime"] == "20170101000000"
        assert series.requested_start == dt.date(2015, 4, 7)
        assert series.requested_start_before_coverage is True

    def test_request_inside_coverage_is_passed_through_unclamped(self) -> None:
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(dict(request.url.params))
            return httpx.Response(200, json=_load_json("gdelt_timeline_volraw.json"))

        provider = GdeltProvider(client=_client_returning(handler))
        series = provider.fetch_volume_series(
            "Nvidia", start=dt.date(2018, 9, 21), end=dt.date(2018, 12, 24)
        )

        assert captured["startdatetime"] == "20180921000000"
        # End of the requested day, so an inclusive-looking range is inclusive.
        assert captured["enddatetime"] == "20181224235959"
        assert captured["mode"] == "timelinevolraw"
        assert series.requested_start_before_coverage is False


class TestVolumeSeriesParsing:
    def test_parses_the_captured_live_timeline(self) -> None:
        """``gdelt_timeline_volraw.json`` is a real 2026-08-26 capture: Nvidia, 2024-01-01..15."""
        provider = GdeltProvider(client=_client_json(200, _load_json("gdelt_timeline_volraw.json")))
        series = provider.fetch_volume_series(
            "Nvidia", start=dt.date(2024, 1, 1), end=dt.date(2024, 1, 15)
        )

        assert series.source == "gdelt"
        assert series.covered_days == 15
        first = series.points[0]
        assert first.day == dt.date(2024, 1, 1)
        assert first.matched == 46
        assert first.indexed_total == 89190

    def test_keeps_the_denominator_rather_than_the_ratio(self) -> None:
        """`indexed_total` is what makes a spike interpretable.

        GDELT's monitored corpus grows year over year, so a raw `matched` count is not comparable
        across windows on its own. Storing the quotient instead would discard exactly the number
        that makes the comparison honest -- the module rule in `app.market.news_models`.
        """
        provider = GdeltProvider(client=_client_json(200, _load_json("gdelt_timeline_volraw.json")))
        series = provider.fetch_volume_series(
            "Nvidia", start=dt.date(2024, 1, 1), end=dt.date(2024, 1, 15)
        )

        assert all(point.indexed_total > 0 for point in series.points)
        assert not hasattr(series.points[0], "share")
        assert not hasattr(series.points[0], "score")

    def test_points_come_back_ordered_oldest_first(self) -> None:
        payload = {
            "timeline": [
                {
                    "series": "Article Count",
                    "data": [
                        {"date": "20240103T000000Z", "value": 3, "norm": 30},
                        {"date": "20240101T000000Z", "value": 1, "norm": 10},
                        {"date": "20240102T000000Z", "value": 2, "norm": 20},
                    ],
                }
            ]
        }
        provider = GdeltProvider(client=_client_json(200, payload))
        series = provider.fetch_volume_series(
            "x", start=dt.date(2024, 1, 1), end=dt.date(2024, 1, 3)
        )

        assert [point.day.day for point in series.points] == [1, 2, 3]

    def test_one_unusable_bucket_is_dropped_not_fatal(self) -> None:
        payload = {
            "timeline": [
                {
                    "series": "Article Count",
                    "data": [
                        {"date": "20240101T000000Z", "value": 1, "norm": 10},
                        {"date": "not-a-date", "value": 2, "norm": 20},
                        {"value": 3, "norm": 30},
                    ],
                }
            ]
        }
        provider = GdeltProvider(client=_client_json(200, payload))
        series = provider.fetch_volume_series(
            "x", start=dt.date(2024, 1, 1), end=dt.date(2024, 1, 3)
        )

        assert series.covered_days == 1

    def test_every_bucket_unusable_is_reported_as_a_schema_change(self) -> None:
        """Mirrors `fetch_query_news`'s all-dropped guard: a silent empty series here would read as
        'no coverage', which is the one answer this study must never manufacture."""
        payload = {
            "timeline": [
                {"series": "Article Count", "data": [{"nope": 1}, {"also": 2}]}
            ]
        }
        provider = GdeltProvider(client=_client_json(200, payload))

        with pytest.raises(ProviderResponseError, match="schema"):
            provider.fetch_volume_series("x", start=dt.date(2024, 1, 1), end=dt.date(2024, 1, 3))

    def test_non_list_timeline_is_a_response_error(self) -> None:
        provider = GdeltProvider(client=_client_json(200, {"timeline": "nope"}))

        with pytest.raises(ProviderResponseError, match="non-list"):
            provider.fetch_volume_series("x", start=dt.date(2024, 1, 1), end=dt.date(2024, 1, 3))


class TestVolumeSeriesFailureModes:
    """The historical endpoint inherits the article endpoint's traps -- these pin that it actually
    does, rather than that someone remembered to reimplement them."""

    def test_throttle_is_detected_from_the_body_on_a_200(self) -> None:
        provider = GdeltProvider(client=_client_text(200, _load_text("gdelt_rate_limited.txt")))

        with pytest.raises(RateLimited):
            provider.fetch_volume_series("x", start=dt.date(2024, 1, 1), end=dt.date(2024, 1, 3))

    def test_out_of_range_refusal_is_typed_not_a_json_decode_error(self) -> None:
        """If clamping ever regresses, the caller must get a sentence naming the archive's start --
        not the ``JSONDecodeError`` that a plain-text body would otherwise produce."""
        provider = GdeltProvider(client=_client_text(200, "Invalid query start date.\n"))

        with pytest.raises(ProviderResponseError, match="archive begins 2017-01-01"):
            provider.fetch_volume_series("x", start=dt.date(2024, 1, 1), end=dt.date(2024, 1, 3))

    def test_timeout_is_provider_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("slow", request=request)

        provider = GdeltProvider(client=_client_returning(handler))

        with pytest.raises(ProviderUnavailable, match="timed out"):
            provider.fetch_volume_series("x", start=dt.date(2024, 1, 1), end=dt.date(2024, 1, 3))

    def test_empty_query_is_refused(self) -> None:
        provider = GdeltProvider(client=_client_json(200, {"timeline": []}))

        with pytest.raises(UnsupportedQuery):
            provider.fetch_volume_series("  ", start=dt.date(2024, 1, 1), end=dt.date(2024, 1, 3))

    def test_reversed_range_is_refused_rather_than_silently_empty(self) -> None:
        provider = GdeltProvider(client=_client_json(200, {"timeline": []}))

        with pytest.raises(UnsupportedQuery, match="start <= end"):
            provider.fetch_volume_series("x", start=dt.date(2024, 1, 3), end=dt.date(2024, 1, 1))

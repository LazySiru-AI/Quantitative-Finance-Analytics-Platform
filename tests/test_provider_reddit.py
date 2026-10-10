"""Tests for the Reddit search-RSS news provider.

Every test drives an ``httpx.MockTransport`` from ``tests/fixtures/news/reddit_nvda.xml`` -- no test
in this file makes a network call. See ``backend/app/market/providers/reddit.py`` for why the JSON
endpoint (which would carry score/comment count) is never attempted: it is 403-blocked for public
clients, verified live 2026-08-24, and the Atom feed this provider parses carries neither field.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from app.market.providers.base import (
    ProviderResponseError,
    ProviderUnavailable,
    RateLimited,
    UnsupportedQuery,
)
from app.market.providers.reddit import DEFAULT_SUBREDDITS, RedditProvider

FIXTURES = Path(__file__).parent / "fixtures" / "news"


def _load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _client_returning(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _client_text(
    status_code: int, text: str, headers: dict[str, str] | None = None
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=text, headers=headers or {})

    return _client_returning(handler)


def _client_raising(exc: Exception) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return _client_returning(handler)


_NVDA_FIXTURE = _load_text("reddit_nvda.xml")

_EMPTY_FEED = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<feed xmlns="http://www.w3.org/2005/Atom">'
    '<category term="wallstreetbets" label="r/wallstreetbets"/>'
    "<updated>2026-08-24T17:09:47+00:00</updated>"
    "<title>wallstreetbets: search results - ZZZZ</title>"
    "</feed>"
)


# ---------------------------------------------------------------------------
# Parsing the captured fixture
# ---------------------------------------------------------------------------


class TestParsing:
    def test_parses_the_captured_fixture_into_news_items(self) -> None:
        client = _client_text(200, _NVDA_FIXTURE, {"Content-Type": "application/atom+xml"})
        provider = RedditProvider(client=client, subreddits=("wallstreetbets",))

        feed = provider.fetch_symbol_news("NVDA")

        assert len(feed.items) == 8
        assert feed.source == "reddit"

    def test_every_item_has_a_tz_aware_utc_published_timestamp(self) -> None:
        client = _client_text(200, _NVDA_FIXTURE)
        provider = RedditProvider(client=client, subreddits=("wallstreetbets",))

        feed = provider.fetch_symbol_news("NVDA")

        for item in feed.items:
            assert item.published.tzinfo is not None
            assert item.published.utcoffset() == dt.timedelta(0)

    def test_publisher_is_the_subreddit_the_post_came_from(self) -> None:
        client = _client_text(200, _NVDA_FIXTURE)
        provider = RedditProvider(client=client, subreddits=("wallstreetbets",))

        feed = provider.fetch_symbol_news("NVDA")

        assert all(item.publisher == "r/wallstreetbets" for item in feed.items)

    def test_source_field_on_each_item_is_the_provider_name(self) -> None:
        client = _client_text(200, _NVDA_FIXTURE)
        provider = RedditProvider(client=client, subreddits=("wallstreetbets",))

        feed = provider.fetch_symbol_news("NVDA")

        assert all(item.source == "reddit" for item in feed.items)

    def test_newest_item_is_the_weekly_earnings_thread_published_august_21st(self) -> None:
        client = _client_text(200, _NVDA_FIXTURE)
        provider = RedditProvider(client=client, subreddits=("wallstreetbets",))

        feed = provider.fetch_symbol_news("NVDA")

        newest = max(feed.items, key=lambda item: item.published)
        assert newest.title == "Weekly Earnings Thread 8/24 - 8/28"
        assert newest.published == dt.datetime(2026, 8, 21, 17, 33, 19, tzinfo=dt.UTC)

    def test_html_entities_in_titles_are_decoded(self) -> None:
        client = _client_text(200, _NVDA_FIXTURE)
        provider = RedditProvider(client=client, subreddits=("wallstreetbets",))

        feed = provider.fetch_symbol_news("NVDA")

        titles = {item.title for item in feed.items}
        assert "NVDA 4500 -> 30K" in titles

    def test_summary_is_never_populated_from_the_html_content_blob(self) -> None:
        client = _client_text(200, _NVDA_FIXTURE)
        provider = RedditProvider(client=client, subreddits=("wallstreetbets",))

        feed = provider.fetch_symbol_news("NVDA")

        assert all(item.summary is None for item in feed.items)

    def test_an_empty_feed_with_zero_entries_is_a_valid_news_feed(self) -> None:
        client = _client_text(200, _EMPTY_FEED)
        provider = RedditProvider(client=client, subreddits=("wallstreetbets",))

        feed = provider.fetch_symbol_news("ZZZZ")

        assert feed.items == ()
        assert feed.source == "reddit"

    def test_an_entry_with_a_javascript_href_is_dropped_and_the_rest_still_return(self) -> None:
        """`NewsItem.url` rejects anything but `http(s)://`. This entry otherwise parses cleanly
        (title and a usable published timestamp both present), so the drop happens at `NewsItem`
        construction, not inside `_parse_entry`'s own field checks -- and one bad post must not cost
        the caller the other, well-formed one."""
        feed_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom">'
            "<entry>"
            "<title>evil link</title>"
            '<link href="javascript:alert(1)"/>'
            "<published>2026-08-21T17:33:19+00:00</published>"
            "</entry>"
            "<entry>"
            "<title>a real post</title>"
            '<link href="https://www.reddit.com/r/wallstreetbets/comments/x/y/"/>'
            "<published>2026-08-20T10:00:00+00:00</published>"
            "</entry>"
            "</feed>"
        )
        client = _client_text(200, feed_xml)
        provider = RedditProvider(client=client, subreddits=("wallstreetbets",))

        feed = provider.fetch_symbol_news("NVDA")

        assert len(feed.items) == 1
        assert feed.items[0].title == "a real post"
        assert feed.items[0].url.startswith(("http://", "https://"))


# ---------------------------------------------------------------------------
# The look-ahead guard
# ---------------------------------------------------------------------------


class TestAsOfBound:
    def test_as_of_genuinely_excludes_items_published_after_the_bound(self) -> None:
        client = _client_text(200, _NVDA_FIXTURE)
        provider = RedditProvider(client=client, subreddits=("wallstreetbets",))
        as_of = dt.datetime(2026, 8, 15, tzinfo=dt.UTC)

        feed = provider.fetch_symbol_news("NVDA", as_of=as_of)

        titles = {item.title for item in feed.items}
        assert "Weekly Earnings Thread 8/24 - 8/28" not in titles
        assert "MU loss" not in titles
        assert all(item.published <= as_of for item in feed.items)
        assert len(feed.items) == 6

    def test_a_naive_as_of_raises_value_error(self) -> None:
        client = _client_text(200, _NVDA_FIXTURE)
        provider = RedditProvider(client=client, subreddits=("wallstreetbets",))
        naive = dt.datetime(2026, 8, 15)

        with pytest.raises(ValueError, match="timezone-aware"):
            provider.fetch_symbol_news("NVDA", as_of=naive)

    def test_a_naive_as_of_is_rejected_before_any_http_request_is_made(self) -> None:
        client = _client_returning(
            lambda request: (_ for _ in ()).throw(
                AssertionError(f"no HTTP request should have been made, got {request.url}")
            )
        )
        provider = RedditProvider(client=client, subreddits=("wallstreetbets",))
        naive = dt.datetime(2026, 8, 15)

        with pytest.raises(ValueError, match="timezone-aware"):
            provider.fetch_symbol_news("NVDA", as_of=naive)


# ---------------------------------------------------------------------------
# Unsupported queries
# ---------------------------------------------------------------------------


class TestUnsupportedQuery:
    def test_empty_query_raises_unsupported_query(self) -> None:
        client = _client_returning(
            lambda request: (_ for _ in ()).throw(
                AssertionError(f"no HTTP request should have been made, got {request.url}")
            )
        )
        provider = RedditProvider(client=client)

        with pytest.raises(UnsupportedQuery):
            provider.fetch_query_news("")

    def test_whitespace_only_query_raises_unsupported_query(self) -> None:
        client = _client_returning(
            lambda request: (_ for _ in ()).throw(
                AssertionError(f"no HTTP request should have been made, got {request.url}")
            )
        )
        provider = RedditProvider(client=client)

        with pytest.raises(UnsupportedQuery):
            provider.fetch_query_news("   ")

    def test_empty_symbol_raises_unsupported_query(self) -> None:
        client = _client_returning(
            lambda request: (_ for _ in ()).throw(
                AssertionError(f"no HTTP request should have been made, got {request.url}")
            )
        )
        provider = RedditProvider(client=client)

        with pytest.raises(UnsupportedQuery):
            provider.fetch_symbol_news("")


# ---------------------------------------------------------------------------
# HTTP failure modes
# ---------------------------------------------------------------------------


class TestHttpFailureModes:
    def test_403_is_provider_unavailable_not_symbol_not_found(self) -> None:
        client = _client_text(403, "Blocked")
        provider = RedditProvider(client=client, subreddits=("wallstreetbets",))

        with pytest.raises(ProviderUnavailable):
            provider.fetch_symbol_news("NVDA")

    def test_429_is_rate_limited_and_carries_retry_after(self) -> None:
        client = _client_text(429, "Too Many Requests", {"Retry-After": "30"})
        provider = RedditProvider(client=client, subreddits=("wallstreetbets",))

        with pytest.raises(RateLimited) as excinfo:
            provider.fetch_symbol_news("NVDA")
        assert excinfo.value.retry_after == 30.0

    def test_429_without_retry_after_header_leaves_it_none(self) -> None:
        client = _client_text(429, "Too Many Requests")
        provider = RedditProvider(client=client, subreddits=("wallstreetbets",))

        with pytest.raises(RateLimited) as excinfo:
            provider.fetch_symbol_news("NVDA")
        assert excinfo.value.retry_after is None

    def test_server_error_is_provider_unavailable(self) -> None:
        client = _client_text(503, "Service Unavailable")
        provider = RedditProvider(client=client, subreddits=("wallstreetbets",))

        with pytest.raises(ProviderUnavailable):
            provider.fetch_symbol_news("NVDA")

    def test_malformed_non_xml_body_is_provider_response_error(self) -> None:
        client = _client_text(200, "this is not xml at all {}")
        provider = RedditProvider(client=client, subreddits=("wallstreetbets",))

        with pytest.raises(ProviderResponseError):
            provider.fetch_symbol_news("NVDA")

    def test_valid_xml_that_is_not_an_atom_feed_is_provider_response_error(self) -> None:
        client = _client_text(200, "<rss><channel><title>not atom</title></channel></rss>")
        provider = RedditProvider(client=client, subreddits=("wallstreetbets",))

        with pytest.raises(ProviderResponseError):
            provider.fetch_symbol_news("NVDA")

    def test_timeout_is_provider_unavailable(self) -> None:
        client = _client_raising(httpx.TimeoutException("boom"))
        provider = RedditProvider(client=client, subreddits=("wallstreetbets",))

        with pytest.raises(ProviderUnavailable):
            provider.fetch_symbol_news("NVDA")

    def test_transport_error_is_provider_unavailable(self) -> None:
        client = _client_raising(httpx.ConnectError("dns failure"))
        provider = RedditProvider(client=client, subreddits=("wallstreetbets",))

        with pytest.raises(ProviderUnavailable):
            provider.fetch_symbol_news("NVDA")


# ---------------------------------------------------------------------------
# Subreddit fan-out and the request shape
# ---------------------------------------------------------------------------


class TestSubredditFanOut:
    def test_default_subreddits_are_wallstreetbets_stocks_investing(self) -> None:
        assert DEFAULT_SUBREDDITS == ("wallstreetbets", "stocks", "investing")

    def test_default_construction_queries_all_three_default_subreddits(self) -> None:
        requested_paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested_paths.append(request.url.path)
            return httpx.Response(200, text=_EMPTY_FEED)

        provider = RedditProvider(client=_client_returning(handler))
        provider.fetch_symbol_news("NVDA")

        assert requested_paths == [
            "/r/wallstreetbets/search.rss",
            "/r/stocks/search.rss",
            "/r/investing/search.rss",
        ]

    def test_request_carries_the_expected_query_params_and_honest_user_agent(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["q"] = request.url.params.get("q", "")
            seen["restrict_sr"] = request.url.params.get("restrict_sr", "")
            seen["sort"] = request.url.params.get("sort", "")
            seen["user_agent"] = request.headers.get("user-agent", "")
            return httpx.Response(200, text=_EMPTY_FEED)

        provider = RedditProvider(client=_client_returning(handler), subreddits=("wallstreetbets",))
        provider.fetch_symbol_news("NVDA")

        assert seen["q"] == "NVDA"
        assert seen["restrict_sr"] == "1"
        assert seen["sort"] == "new"
        assert seen["user_agent"] == "investing-dashboard/0.1"

    def test_a_custom_subreddit_set_overrides_the_default(self) -> None:
        requested_paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested_paths.append(request.url.path)
            return httpx.Response(200, text=_EMPTY_FEED)

        provider = RedditProvider(client=_client_returning(handler), subreddits=("options",))
        provider.fetch_symbol_news("NVDA")

        assert requested_paths == ["/r/options/search.rss"]

    def test_results_from_multiple_subreddits_are_merged_and_sorted_newest_first(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_NVDA_FIXTURE)

        provider = RedditProvider(
            client=_client_returning(handler), subreddits=("wallstreetbets", "stocks")
        )

        feed = provider.fetch_symbol_news("NVDA", limit=100)

        assert len(feed.items) == 16
        published_times = [item.published for item in feed.items]
        assert published_times == sorted(published_times, reverse=True)

    def test_limit_bounds_the_final_merged_result_not_just_one_subreddit(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_NVDA_FIXTURE)

        provider = RedditProvider(
            client=_client_returning(handler), subreddits=("wallstreetbets", "stocks", "investing")
        )

        feed = provider.fetch_symbol_news("NVDA", limit=5)

        assert len(feed.items) == 5

    def test_fetch_query_news_uses_the_free_text_query_as_is(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["q"] = request.url.params.get("q", "")
            return httpx.Response(200, text=_EMPTY_FEED)

        provider = RedditProvider(client=_client_returning(handler), subreddits=("stocks",))
        provider.fetch_query_news("fed rate decision")

        assert seen["q"] == "fed rate decision"

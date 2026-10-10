"""Tests for the news/sentiment service layer (`app.market.news`).

Every test drives `build_ticker_panel` / `build_macro_panel` with a `ProviderRegistry` wrapping
hand-written fakes, injected through the `registry=` parameter -- no test in this file makes a
network call or goes through `app.market.registry.default_registry`. This mirrors the pattern
`tests/test_macro.py` established for `app.market.macro.build_snapshot`: a real `ProviderRegistry`
around fakes that implement the `NewsProvider`/`SocialProvider`/`EventProvider` protocols directly,
so the registry's own fallback-walk logic (already covered by `tests/test_market_registry.py`) is
exercised for real rather than re-mocked here.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.config import Settings
from app.market import news
from app.market.models import MarketWarning
from app.market.news_models import EventMarket, NewsFeed, NewsItem, SocialSnapshot, published_before
from app.market.providers.base import ProviderUnavailable, SymbolNotFound, UnsupportedQuery
from app.market.registry import ProviderRegistry

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _item(title: str, *, published: dt.datetime, source: str = "yahoo_news") -> NewsItem:
    return NewsItem(
        title=title,
        url=f"https://example.test/{title.replace(' ', '-').lower()}",
        published=published,
        source=source,
    )


class FakeNewsProvider:
    """A `NewsProvider` whose outcome is dictated by the test: `ok`, `not_found`, `unavailable`,
    or `unsupported`. Real `as_of` bounding is applied via `published_before`, exactly as a real
    provider is documented to do -- see `app.market.providers.base.NewsProvider` -- so a naive
    `as_of` raises `ValueError` from inside this fake precisely as it would from a real one.
    """

    def __init__(
        self,
        name: str,
        items: tuple[NewsItem, ...] = (),
        *,
        outcome: str = "ok",
        feed_warnings: tuple = (),
    ) -> None:
        self.name = name
        self.items = items
        self.outcome = outcome
        self.feed_warnings = feed_warnings
        self.symbol_calls: list[str] = []
        self.query_calls: list[str] = []
        self.as_of_received: list[dt.datetime | None] = []

    def _serve(self, subject: str, limit: int, as_of: dt.datetime | None) -> NewsFeed:
        self.as_of_received.append(as_of)
        if self.outcome == "not_found":
            raise SymbolNotFound(f"{subject} not found", provider=self.name)
        if self.outcome == "unavailable":
            raise ProviderUnavailable(f"{self.name} is down", provider=self.name)
        if self.outcome == "unsupported":
            raise UnsupportedQuery(f"{self.name} does not answer that", provider=self.name)
        bounded = published_before(self.items, as_of)[:limit]
        return NewsFeed(items=bounded, source=self.name, as_of=as_of, warnings=self.feed_warnings)

    def fetch_symbol_news(
        self, symbol: str, *, limit: int = 20, as_of: dt.datetime | None = None
    ) -> NewsFeed:
        self.symbol_calls.append(symbol)
        return self._serve(symbol, limit, as_of)

    def fetch_query_news(
        self, query: str, *, limit: int = 20, as_of: dt.datetime | None = None
    ) -> NewsFeed:
        self.query_calls.append(query)
        return self._serve(query, limit, as_of)


class FakeSocialProvider:
    """A `SocialProvider` whose outcome is dictated by the test: `ok`, `not_found`, `unavailable`."""

    def __init__(self, name: str, snapshot: SocialSnapshot | None = None, *, outcome: str = "ok") -> None:
        self.name = name
        self.snapshot = snapshot
        self.outcome = outcome
        self.calls: list[str] = []

    def fetch_social(self, symbol: str, *, limit: int = 30) -> SocialSnapshot:
        self.calls.append(symbol)
        if self.outcome == "not_found":
            raise SymbolNotFound(f"{symbol} not found", provider=self.name)
        if self.outcome == "unavailable":
            raise ProviderUnavailable(f"{self.name} is down", provider=self.name)
        assert self.snapshot is not None
        return self.snapshot


class FakeEventProvider:
    """An `EventProvider` whose outcome is dictated by the test: `ok` or `unavailable`."""

    def __init__(self, name: str, events: tuple[EventMarket, ...] = (), *, outcome: str = "ok") -> None:
        self.name = name
        self.events = events
        self.outcome = outcome
        self.calls: list[str] = []

    def fetch_events(self, topic: str, *, limit: int = 10) -> tuple[EventMarket, ...]:
        self.calls.append(topic)
        if self.outcome == "unavailable":
            raise ProviderUnavailable(f"{self.name} is down", provider=self.name)
        return self.events[:limit]


def _snapshot(symbol: str = "AAPL", *, bullish: int = 5, bearish: int = 3, neutral: int = 2) -> SocialSnapshot:
    return SocialSnapshot(
        symbol=symbol,
        source="stocktwits",
        as_of=dt.datetime(2026, 8, 20, tzinfo=dt.UTC),
        bullish=bullish,
        bearish=bearish,
        neutral=neutral,
    )


def _event(question: str = "Will X happen?") -> EventMarket:
    return EventMarket(
        question=question,
        slug="will-x-happen",
        source="polymarket",
        as_of=dt.datetime(2026, 8, 20, tzinfo=dt.UTC),
        probability=0.42,
    )


NOW = dt.datetime(2026, 8, 24, 12, 0, tzinfo=dt.UTC)


# ---------------------------------------------------------------------------
# Ticker panel
# ---------------------------------------------------------------------------


class TestBuildTickerPanelHappyPath:
    def test_a_fully_working_registry_produces_a_populated_panel_with_news_source_set(
        self, settings: Settings
    ) -> None:
        news_provider = FakeNewsProvider("yahoo_news", items=(_item("Apple rallies", published=NOW),))
        social_provider = FakeSocialProvider("stocktwits", snapshot=_snapshot())
        registry = ProviderRegistry(
            news_providers=(news_provider,), social_providers=(social_provider,)
        )

        panel = news.build_ticker_panel(settings, "AAPL", registry=registry)

        assert panel.symbol == "AAPL"
        assert len(panel.news) == 1
        assert panel.news[0].title == "Apple rallies"
        assert panel.news_source == "yahoo_news"
        assert panel.social is not None
        assert panel.social.snapshot.bullish == 5
        assert panel.warnings == ()


class TestBuildTickerPanelSocialFailure:
    def test_stocktwits_down_leaves_headlines_intact_social_none_and_a_warning_naming_it(
        self, settings: Settings
    ) -> None:
        news_provider = FakeNewsProvider("yahoo_news", items=(_item("Apple rallies", published=NOW),))
        social_provider = FakeSocialProvider("stocktwits", outcome="unavailable")
        registry = ProviderRegistry(
            news_providers=(news_provider,), social_providers=(social_provider,)
        )

        panel = news.build_ticker_panel(settings, "AAPL", registry=registry)

        assert len(panel.news) == 1
        assert panel.news_source == "yahoo_news"
        assert panel.social is None
        assert any("stocktwits" in w.message for w in panel.warnings)


class TestBuildTickerPanelNewsFailure:
    def test_news_chain_down_leaves_social_intact_empty_news_and_a_warning(
        self, settings: Settings
    ) -> None:
        news_provider = FakeNewsProvider("yahoo_news", outcome="unavailable")
        social_provider = FakeSocialProvider("stocktwits", snapshot=_snapshot())
        registry = ProviderRegistry(
            news_providers=(news_provider,), social_providers=(social_provider,)
        )

        panel = news.build_ticker_panel(settings, "AAPL", registry=registry)

        assert panel.news == ()
        assert panel.news_source is None
        assert panel.social is not None
        assert panel.warnings != ()
        assert any("news" in w.message for w in panel.warnings)


class TestBuildTickerPanelEverythingDown:
    def test_everything_down_still_constructs_a_200able_panel_with_a_warning_per_section(
        self, settings: Settings
    ) -> None:
        news_provider = FakeNewsProvider("yahoo_news", outcome="unavailable")
        social_provider = FakeSocialProvider("stocktwits", outcome="unavailable")
        registry = ProviderRegistry(
            news_providers=(news_provider,), social_providers=(social_provider,)
        )

        panel = news.build_ticker_panel(settings, "AAPL", registry=registry)

        assert panel.news == ()
        assert panel.news_source is None
        assert panel.social is None
        assert len(panel.warnings) >= 2
        joined = " ".join(w.message for w in panel.warnings)
        assert "news" in joined
        assert "social" in joined


class TestSymbolNotFoundWithContextSurvives:
    def test_earlier_failure_context_and_final_not_found_both_land_in_the_panel_warnings(
        self, settings: Settings
    ) -> None:
        """Provider A degrades first (`ProviderUnavailable`), provider B then confirms the symbol
        does not exist. The registry raises `SymbolNotFoundWithContext` carrying A's warning/failure
        -- this must survive into the panel rather than being swallowed, per `app.market.registry`'s
        own reasoning for why that class exists at all.
        """
        provider_a = FakeNewsProvider("providerA", outcome="unavailable")
        provider_b = FakeNewsProvider("providerB", outcome="not_found")
        registry = ProviderRegistry(news_providers=(provider_a, provider_b))

        panel = news.build_ticker_panel(settings, "ZZZZ", registry=registry)

        assert panel.news == ()
        joined = " ".join(w.message for w in panel.warnings)
        assert "providerA" in joined  # the earlier failure's context survived
        assert "ZZZZ" in joined  # the final not-found is also recorded


class TestNewsFeedWarningsSurvive:
    def test_warnings_carried_on_the_registry_feed_land_in_the_panel(self, settings: Settings) -> None:
        feed_warning = MarketWarning(kind="partial_parse", message="2 of 5 rows unparsable")
        news_provider = FakeNewsProvider(
            "yahoo_news",
            items=(_item("Apple rallies", published=NOW),),
            feed_warnings=(feed_warning,),
        )
        registry = ProviderRegistry(news_providers=(news_provider,))

        panel = news.build_ticker_panel(settings, "AAPL", registry=registry)

        assert feed_warning in panel.warnings


class TestAsOfThreading:
    def test_as_of_is_threaded_through_to_the_news_provider(self, settings: Settings) -> None:
        as_of = dt.datetime(2026, 6, 1, tzinfo=dt.UTC)
        news_provider = FakeNewsProvider("yahoo_news", items=(_item("Apple rallies", published=NOW),))
        registry = ProviderRegistry(news_providers=(news_provider,))

        news.build_ticker_panel(settings, "AAPL", as_of=as_of, registry=registry)

        assert news_provider.as_of_received == [as_of]

    def test_a_naive_as_of_propagates_valueerror_rather_than_being_coerced(
        self, settings: Settings
    ) -> None:
        naive = dt.datetime(2026, 6, 1)  # no tzinfo -- a caller bug, not an upstream failure
        news_provider = FakeNewsProvider("yahoo_news", items=(_item("Apple rallies", published=NOW),))
        registry = ProviderRegistry(news_providers=(news_provider,))

        with pytest.raises(ValueError, match="timezone-aware"):
            news.build_ticker_panel(settings, "AAPL", as_of=naive, registry=registry)


class TestGeneratedAt:
    def test_generated_at_is_tz_aware_utc(self, settings: Settings) -> None:
        registry = ProviderRegistry()
        panel = news.build_ticker_panel(settings, "AAPL", registry=registry)

        assert panel.generated_at.tzinfo is not None
        assert panel.generated_at.utcoffset() == dt.timedelta(0)


# ---------------------------------------------------------------------------
# Macro panel
# ---------------------------------------------------------------------------


class TestBuildMacroPanelHappyPath:
    def test_a_fully_working_registry_produces_a_populated_panel_with_news_source_set(
        self, settings: Settings
    ) -> None:
        news_provider = FakeNewsProvider("gdelt", items=(_item("Fed holds rates", published=NOW),))
        event_provider = FakeEventProvider("polymarket", events=(_event(),))
        registry = ProviderRegistry(news_providers=(news_provider,), event_providers=(event_provider,))

        panel = news.build_macro_panel(settings, registry=registry)

        assert len(panel.news) == 1
        assert panel.news_source == "gdelt"
        assert len(panel.events) == 1
        assert panel.warnings == ()

    def test_empty_query_falls_back_to_the_default_macro_query(self, settings: Settings) -> None:
        news_provider = FakeNewsProvider("gdelt")
        registry = ProviderRegistry(news_providers=(news_provider,))

        panel = news.build_macro_panel(settings, query="", registry=registry)

        assert panel.query == news.DEFAULT_MACRO_QUERY
        assert news_provider.query_calls == [news.DEFAULT_MACRO_QUERY]

    def test_a_supplied_query_is_used_as_is(self, settings: Settings) -> None:
        news_provider = FakeNewsProvider("gdelt")
        registry = ProviderRegistry(news_providers=(news_provider,))

        panel = news.build_macro_panel(settings, query="inflation report", registry=registry)

        assert panel.query == "inflation report"
        assert news_provider.query_calls == ["inflation report"]


class TestBuildMacroPanelEventsFailure:
    def test_events_down_leaves_headlines_intact_and_events_empty(self, settings: Settings) -> None:
        news_provider = FakeNewsProvider("gdelt", items=(_item("Fed holds rates", published=NOW),))
        event_provider = FakeEventProvider("polymarket", outcome="unavailable")
        registry = ProviderRegistry(news_providers=(news_provider,), event_providers=(event_provider,))

        panel = news.build_macro_panel(settings, registry=registry)

        assert len(panel.news) == 1
        assert panel.events == ()
        assert any("polymarket" in w.message or "prediction markets" in w.message for w in panel.warnings)


class TestBuildMacroPanelNewsFailure:
    def test_news_chain_down_leaves_events_intact(self, settings: Settings) -> None:
        news_provider = FakeNewsProvider("gdelt", outcome="unavailable")
        event_provider = FakeEventProvider("polymarket", events=(_event(),))
        registry = ProviderRegistry(news_providers=(news_provider,), event_providers=(event_provider,))

        panel = news.build_macro_panel(settings, registry=registry)

        assert panel.news == ()
        assert panel.news_source is None
        assert len(panel.events) == 1


class TestBuildMacroPanelEverythingDown:
    def test_everything_down_still_constructs_a_200able_panel_with_a_warning_per_section(
        self, settings: Settings
    ) -> None:
        news_provider = FakeNewsProvider("gdelt", outcome="unavailable")
        event_provider = FakeEventProvider("polymarket", outcome="unavailable")
        registry = ProviderRegistry(news_providers=(news_provider,), event_providers=(event_provider,))

        panel = news.build_macro_panel(settings, registry=registry)

        assert panel.news == ()
        assert panel.events == ()
        assert len(panel.warnings) >= 2

    def test_no_configured_providers_at_all_still_constructs_a_panel(self, settings: Settings) -> None:
        """`ProviderRegistry()` with no providers registered is the extreme case: every walk is
        exhausted immediately with `ProviderUnavailable("no configured provider ...")`. Still no
        exception should reach the caller."""
        registry = ProviderRegistry()

        panel = news.build_macro_panel(settings, registry=registry)

        assert panel.news == ()
        assert panel.events == ()
        assert len(panel.warnings) == 2


class TestMacroGeneratedAt:
    def test_generated_at_is_tz_aware_utc(self, settings: Settings) -> None:
        registry = ProviderRegistry()
        panel = news.build_macro_panel(settings, registry=registry)

        assert panel.generated_at.tzinfo is not None
        assert panel.generated_at.utcoffset() == dt.timedelta(0)


class TestDefaultRegistryInjectionPoint:
    def test_omitting_registry_builds_one_via_default_registry(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`registry=None` must route through `app.market.registry.default_registry` -- the
        documented injection point -- rather than constructing providers some other way."""
        sentinel = ProviderRegistry()
        calls: list[Settings] = []

        def fake_default_registry(cfg: Settings) -> ProviderRegistry:
            calls.append(cfg)
            return sentinel

        monkeypatch.setattr(news, "default_registry", fake_default_registry)

        panel = news.build_ticker_panel(settings, "AAPL")

        assert calls == [settings]
        assert panel.news == ()
        assert panel.social is None

"""Tests for the news router.

Built around a bare `FastAPI()` carrying only `app.api.news.router`, matching `tests/test_macro_api.py`
and `tests/test_market_api.py` rather than importing `app.main` -- the router's behaviour is what is
under test here, not the application's startup.

The service layer is stubbed at the `app.market.news` module boundary. That is the seam this router
actually uses (it does `from app.market import news` and calls `news.build_ticker_panel(...)`), so
patching the attribute on that module is what a request really goes through. No test here touches the
network, and none constructs a provider: `tests/test_news_service.py` covers the degradation logic
itself, and repeating it through HTTP would test the same code twice while proving nothing extra
about the router.

**What this file is really checking** is the claim `app/api/news.py`'s docstring makes: that there is
no 5xx path. A panel assembled from four independent upstreams must answer 200 with an explained
empty section when one of them is down, because the alternative loses three working sections to one
broken one. The 422 cases are the deliberate exception -- a malformed request is the caller's, not an
outage.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import news as news_api
from app.market import news as news_service
from app.market.models import MarketWarning
from app.market.news_models import (
    MacroNewsPanel,
    NewsItem,
    SocialSnapshot,
    SocialSummary,
    TickerNewsPanel,
)

NOW = dt.datetime(2026, 8, 24, 18, 0, tzinfo=dt.UTC)


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(news_api.router)
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _item(title: str = "Chipmakers rally") -> NewsItem:
    return NewsItem(
        title=title,
        url="https://example.com/a",
        published=dt.datetime(2026, 8, 24, 17, 0, tzinfo=dt.UTC),
        source="yahoo_news",
        publisher="MT Newswires",
    )


def _social() -> SocialSummary:
    return SocialSummary.of(
        SocialSnapshot(
            symbol="AAPL", source="stocktwits", as_of=NOW, bullish=2, bearish=2, neutral=8
        )
    )


def _full_panel() -> TickerNewsPanel:
    return TickerNewsPanel(
        symbol="AAPL",
        generated_at=NOW,
        news=(_item(),),
        news_source="yahoo_news",
        social=_social(),
    )


class TestTickerEndpointServesThePanel:
    def test_a_populated_panel_comes_back_200_with_every_section(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(news_service, "build_ticker_panel", lambda *a, **k: _full_panel())

        response = client.get("/api/news/ticker/AAPL")

        assert response.status_code == 200
        body = response.json()
        assert body["symbol"] == "AAPL"
        assert body["news_source"] == "yahoo_news"
        assert len(body["news"]) == 1
        assert body["social"]["snapshot"]["neutral"] == 8

    def test_the_bull_ratio_is_served_over_the_labelled_denominator_not_the_total(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """2 bullish of 4 labelled is 0.5; of 12 total it would be 0.167. The panel must serve the
        first, and must publish the share that makes the thinness visible."""
        monkeypatch.setattr(news_service, "build_ticker_panel", lambda *a, **k: _full_panel())

        body = client.get("/api/news/ticker/AAPL").json()

        assert body["social"]["bull_ratio"] == pytest.approx(0.5)
        assert body["social"]["labelled_share"] == pytest.approx(4 / 12)

    def test_limit_and_as_of_reach_the_service(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, object] = {}

        def spy(settings: object, symbol: str, **kwargs: object) -> TickerNewsPanel:
            seen.update(kwargs)
            seen["symbol"] = symbol
            return _full_panel()

        monkeypatch.setattr(news_service, "build_ticker_panel", spy)

        client.get("/api/news/ticker/NVDA", params={"limit": 5, "as_of": "2026-08-24T12:00:00Z"})

        assert seen["symbol"] == "NVDA"
        assert seen["limit"] == 5
        assert seen["as_of"] == dt.datetime(2026, 8, 24, 12, 0, tzinfo=dt.UTC)


class TestTickerEndpointNeverFivehundreds:
    """The contract from `app/api/news.py`'s docstring: a dead upstream degrades its own section."""

    def test_a_panel_with_no_social_still_answers_200(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        degraded = TickerNewsPanel(
            symbol="AAPL",
            generated_at=NOW,
            news=(_item(),),
            news_source="yahoo_news",
            social=None,
            warnings=(MarketWarning(kind="provider_fallback", message="stocktwits unavailable"),),
        )
        monkeypatch.setattr(news_service, "build_ticker_panel", lambda *a, **k: degraded)

        response = client.get("/api/news/ticker/AAPL")

        assert response.status_code == 200
        body = response.json()
        assert body["social"] is None
        assert len(body["news"]) == 1, "a dead social upstream must not cost the headlines"
        assert body["warnings"][0]["kind"] == "provider_fallback"

    def test_a_wholly_empty_panel_still_answers_200_with_its_warnings(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty = TickerNewsPanel(
            symbol="AAPL",
            generated_at=NOW,
            news=(),
            news_source=None,
            social=None,
            warnings=(
                MarketWarning(kind="provider_fallback", message="news chain exhausted"),
                MarketWarning(kind="provider_fallback", message="stocktwits unavailable"),
            ),
        )
        monkeypatch.setattr(news_service, "build_ticker_panel", lambda *a, **k: empty)

        response = client.get("/api/news/ticker/AAPL")

        assert response.status_code == 200
        assert response.json()["news_source"] is None
        assert len(response.json()["warnings"]) == 2


class TestRequestValidationIsA422:
    def test_a_naive_as_of_is_422_not_500(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`published_before` raises ValueError for a naive bound. Surfacing that as a 500 would send
        whoever hit it looking at the server instead of at their query string."""

        def boom(*a: object, **k: object) -> TickerNewsPanel:
            raise ValueError("as_of must be timezone-aware: a naive bound cannot be compared")

        monkeypatch.setattr(news_service, "build_ticker_panel", boom)

        response = client.get("/api/news/ticker/AAPL", params={"as_of": "2024-01-01T00:00:00"})

        assert response.status_code == 422
        assert "timezone-aware" in response.json()["detail"]

    def test_a_symbol_outside_the_allowed_alphabet_is_422(self, client: TestClient) -> None:
        assert client.get("/api/news/ticker/@@bad@@").status_code == 422

    def test_a_limit_past_the_ceiling_is_422(self, client: TestClient) -> None:
        """The upstreams are keyless public endpoints -- GDELT throttles hard -- so an unbounded
        limit is a way for one page load to spend the whole budget."""
        assert client.get("/api/news/ticker/AAPL", params={"limit": 500}).status_code == 422

    def test_a_zero_limit_is_422(self, client: TestClient) -> None:
        assert client.get("/api/news/ticker/AAPL", params={"limit": 0}).status_code == 422


class TestMacroEndpoint:
    def test_it_serves_headlines_and_events(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        panel = MacroNewsPanel(
            generated_at=NOW, query="Fed", news=(_item(),), news_source="gdelt", events=()
        )
        monkeypatch.setattr(news_service, "build_macro_panel", lambda *a, **k: panel)

        response = client.get("/api/news/macro", params={"query": "Fed"})

        assert response.status_code == 200
        assert response.json()["news_source"] == "gdelt"

    def test_an_empty_query_is_not_an_error(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, object] = {}

        def spy(settings: object, **kwargs: object) -> MacroNewsPanel:
            seen.update(kwargs)
            return MacroNewsPanel(generated_at=NOW)

        monkeypatch.setattr(news_service, "build_macro_panel", spy)

        assert client.get("/api/news/macro").status_code == 200
        assert seen["query"] == "", "the router passes it through; the service owns the fallback"

    def test_a_naive_as_of_is_422_here_too(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*a: object, **k: object) -> MacroNewsPanel:
            raise ValueError("as_of must be timezone-aware")

        monkeypatch.setattr(news_service, "build_macro_panel", boom)

        response = client.get("/api/news/macro", params={"as_of": "2024-01-01T00:00:00"})

        assert response.status_code == 422


class TestTheRouterIsRegisteredOnTheRealApp:
    """A bare-router test cannot see a missing `include_router` line -- and a green suite that never
    starts the real application is exactly how a page ships unreachable. This one check imports
    `app.main` for that reason alone."""

    def test_both_paths_are_in_the_real_apps_openapi(self) -> None:
        from app.main import app as real_app

        paths = TestClient(real_app).get("/openapi.json").json()["paths"]

        assert "/api/news/ticker/{symbol}" in paths
        assert "/api/news/macro" in paths

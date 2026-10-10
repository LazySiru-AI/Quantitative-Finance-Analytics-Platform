"""HTTP-layer tests for `app.api.live_decisions`.

Follows `tests/test_api_workflow.py`'s pattern: a bare `FastAPI()` app around just this router, not
`app.main.app`, so this file exercises only the router and its exception mapping -- the decision engine
underneath has its own coverage in `tests/test_agentdesk_live_loop.py`.

The `settings` fixture (from `tests/conftest.py`) redirects every `INVDASH_*` path into a `tmp_path`
tree; every test below takes it so `get_settings()` inside the router always resolves to that isolated
tree, never the real repo's `data/`.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.agentdesk import live_loop
from app.agents.models import AgentUnavailable, BudgetExhausted
from app.agents.spend import LEDGER
from app.api import live_decisions as live_api
from app.config import Settings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _block_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any real HTTP request from this file is a bug. Patched at `httpx.HTTPTransport` rather than at
    the socket layer -- see `tests/test_market_refresh.py`'s own fixture for why blocking sockets
    breaks `TestClient`'s event loop on Windows for entirely unrelated reasons."""
    import httpx

    def _blocked(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"test_api_live_decisions.py attempted a real HTTP request: {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked)


@pytest.fixture(autouse=True)
def _clean_module_state() -> Iterator[None]:
    live_loop.reset()
    LEDGER.reset()
    yield
    live_loop.reset()
    LEDGER.reset()


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(live_api.router)
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _record(symbol: str = "AAPL", *, minutes_ago: int = 0) -> live_loop.LiveDecisionRecord:
    return live_loop.LiveDecisionRecord(
        decided_at=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=minutes_ago),
        symbol=symbol,
        stance="buy",
        confidence=0.62,
        rationale="the live quote is above the 50-day average",
        horizon="days",
        price="191.25",
        quoted_at=dt.datetime.now(dt.UTC),
        market_state="REGULAR",
        grounded=True,
        cost_usd="0.0123",
        model="claude-haiku-4-5-20251001",
        source="daemon",
        call_ids=("call-1",),
    )


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------


class TestStatus:
    def test_status_answers_even_with_the_feature_switched_off(
        self, client: TestClient, settings: Settings
    ) -> None:
        response = client.get("/api/agentdesk/live/status")
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is False
        assert body["running"] is False
        assert body["healthy"] is None
        assert set(body) == {
            "enabled", "running", "healthy", "market_state", "last_tick_at", "next_wake_at",
            "ticks", "decisions_today", "consecutive_failures", "symbols", "interval_minutes",
            "cap_usd",
        }


# ---------------------------------------------------------------------------
# GET /decisions
# ---------------------------------------------------------------------------


class TestDecisions:
    def test_empty_before_anything_has_been_decided(self, client: TestClient, settings: Settings) -> None:
        response = client.get("/api/agentdesk/live/decisions")
        assert response.status_code == 200
        assert response.json() == {"decisions": []}

    def test_records_come_back_newest_first_and_filter_by_symbol(
        self, client: TestClient, settings: Settings
    ) -> None:
        live_loop._append(_record("AAPL", minutes_ago=30), settings=settings)
        live_loop._append(_record("MSFT", minutes_ago=10), settings=settings)

        body = client.get("/api/agentdesk/live/decisions").json()
        assert [d["symbol"] for d in body["decisions"]] == ["MSFT", "AAPL"]
        # Datetimes serialise as ISO-8601 UTC (FastAPI's JSON encoder writes the `Z` form), and
        # money/prices as decimal strings.
        assert body["decisions"][0]["decided_at"].endswith(("Z", "+00:00"))
        assert body["decisions"][0]["cost_usd"] == "0.0123"
        assert body["decisions"][0]["price"] == "191.25"

        filtered = client.get("/api/agentdesk/live/decisions", params={"symbol": "aapl"}).json()
        assert [d["symbol"] for d in filtered["decisions"]] == ["AAPL"]

    def test_limit_is_bounded(self, client: TestClient, settings: Settings) -> None:
        assert client.get("/api/agentdesk/live/decisions", params={"limit": 0}).status_code == 422
        assert client.get("/api/agentdesk/live/decisions", params={"limit": 201}).status_code == 422
        assert client.get("/api/agentdesk/live/decisions", params={"limit": 200}).status_code == 200


# ---------------------------------------------------------------------------
# POST /decide
# ---------------------------------------------------------------------------


class TestDecide:
    def test_a_decision_comes_back_in_full(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            live_loop, "decide", lambda symbol, *, settings, source="manual", budget=None: _record(symbol)
        )
        response = client.post("/api/agentdesk/live/decide", json={"symbol": "AAPL"})
        assert response.status_code == 200
        decision = response.json()["decision"]
        assert decision["symbol"] == "AAPL"
        assert decision["stance"] == "buy"
        assert decision["horizon"] == "days"
        assert decision["grounded"] is True
        assert decision["call_ids"] == ["call-1"]

    def test_an_invalid_symbol_is_422(self, client: TestClient, settings: Settings) -> None:
        response = client.post("/api/agentdesk/live/decide", json={"symbol": "not a ticker!"})
        assert response.status_code == 422

    def test_a_missing_body_field_is_422(self, client: TestClient, settings: Settings) -> None:
        assert client.post("/api/agentdesk/live/decide", json={}).status_code == 422

    def test_an_unavailable_agent_layer_is_503(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _unavailable(symbol: str, **kwargs: object) -> live_loop.LiveDecisionRecord:
            raise AgentUnavailable("no credential configured")

        monkeypatch.setattr(live_loop, "decide", _unavailable)
        response = client.post("/api/agentdesk/live/decide", json={"symbol": "AAPL"})
        assert response.status_code == 503
        assert "no credential" in response.json()["detail"]

    def test_a_budget_cap_is_409(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _capped(symbol: str, **kwargs: object) -> live_loop.LiveDecisionRecord:
            raise BudgetExhausted(Decimal("1.00"), Decimal("1.00"))

        monkeypatch.setattr(live_loop, "decide", _capped)
        assert client.post("/api/agentdesk/live/decide", json={"symbol": "AAPL"}).status_code == 409

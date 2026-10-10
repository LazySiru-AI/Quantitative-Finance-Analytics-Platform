"""`GET /api/vibedesk/config`: Vibe Trading's model picker must serve the same worker-model catalogue
Trading Agents exposes (`app.tradingagents.service.AVAILABLE_MODELS`), plus Vibe's own default model,
so the two desks' pickers cannot drift apart.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import vibedesk
from app.tradingagents.service import AVAILABLE_MODELS
from app.vibedesk import service
from app.vibedesk.runtime import DESK_DEFAULT_MODEL


@pytest.fixture
def app() -> FastAPI:
    """A bare app around just the vibedesk router, matching `tests/test_api_agents.py`'s own `app`
    fixture convention -- `app.main` is not exercised here."""
    fastapi_app = FastAPI()
    fastapi_app.include_router(vibedesk.router)
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


class TestBuildConfig:
    def test_build_config_reuses_trading_agents_model_catalogue(self) -> None:
        payload = service.build_config()
        assert payload["available_models"] == [dict(m) for m in AVAILABLE_MODELS]

    def test_build_config_default_model_is_the_vibe_default(self) -> None:
        payload = service.build_config()
        assert payload["default_model"] == DESK_DEFAULT_MODEL
        # Vibe's default happens to equal Trading Agents' own default (both Haiku 4.5) but the field
        # is Vibe's own -- assert against `DESK_DEFAULT_MODEL`, not a hardcoded literal.


class TestConfigRoute:
    def test_get_config_returns_200_with_the_shared_catalogue_and_vibe_default(
        self, client: TestClient
    ) -> None:
        resp = client.get("/api/vibedesk/config")
        assert resp.status_code == 200
        body = resp.json()
        assert body["default_model"] == DESK_DEFAULT_MODEL
        assert body["available_models"] == [dict(m) for m in AVAILABLE_MODELS]

    def test_config_route_is_registered_on_the_real_app(self) -> None:
        from app.main import app as real_app

        paths = real_app.openapi()["paths"]
        assert "/api/vibedesk/config" in paths

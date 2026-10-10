"""HTTP-layer tests for `app.api.agents` -- `GET /api/agents/health`.

**`app.agents.client` does not necessarily exist yet** (another worker's concurrently-written module),
so every scenario below injects a fake straight into `sys.modules["app.agents.client"]` rather than
importing the real thing. `app.api.agents.health` is written against `importlib.import_module`
specifically so this works whether the real module exists yet or not -- see that router's own
docstring.

Covers the DoD's (a) and (b): the endpoint reports `available: false` with a reason and never 500s
when the SDK or credential is missing, and it never echoes a credential value into the response body.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import agents

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    """A bare app around just the agents router -- `app.main` is not exercised here, matching
    `tests/test_api_evolution.py`'s own `app` fixture for the same reason."""
    fastapi_app = FastAPI()
    fastapi_app.include_router(agents.router)
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _install_fake_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    is_available: Any = None,
    credential_source: Any = None,
) -> None:
    fake = types.ModuleType("app.agents.client")
    fake.is_available = is_available or (lambda: (True, "ANTHROPIC_API_KEY set"))  # type: ignore[attr-defined]
    fake.credential_source = credential_source or (lambda: "api_key")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.agents.client", fake)


# ---------------------------------------------------------------------------
# (a) available: false, with a reason, never a 500 -- both when the module is missing and when it
# resolves to "no credential"
# ---------------------------------------------------------------------------


class TestNeverA500WhenUnavailable:
    def test_module_not_importable_reports_unavailable_not_500(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The standard trick to force ModuleNotFoundError for a module Python could otherwise import.
        monkeypatch.setitem(sys.modules, "app.agents.client", None)

        response = client.get("/api/agents/health")

        assert response.status_code == 200
        body = response.json()
        assert body["available"] is False
        assert body["sdk_installed"] is False
        assert body["credential_source"] == "none"
        assert body["reason"]  # non-empty, names the actual cause
        assert "not importable" in body["reason"]

    def test_no_credential_found_reports_unavailable_not_500(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_client(
            monkeypatch,
            is_available=lambda: (False, "no ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, or profile found"),
            credential_source=lambda: "none",
        )

        response = client.get("/api/agents/health")

        assert response.status_code == 200
        body = response.json()
        assert body["available"] is False
        assert body["credential_source"] == "none"
        assert "no ANTHROPIC_API_KEY" in body["reason"]

    def test_is_available_raising_reports_unavailable_not_500(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raises() -> tuple[bool, str]:
            raise RuntimeError("unexpected failure resolving credentials")

        _install_fake_client(monkeypatch, is_available=_raises)

        response = client.get("/api/agents/health")

        assert response.status_code == 200
        body = response.json()
        assert body["available"] is False
        assert "RuntimeError" in body["reason"]

    def test_credential_source_raising_reports_unavailable_not_500(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raises() -> str:
            raise RuntimeError("unexpected failure classifying the credential")

        _install_fake_client(monkeypatch, credential_source=_raises)

        response = client.get("/api/agents/health")

        assert response.status_code == 200
        body = response.json()
        assert body["available"] is False
        assert "RuntimeError" in body["reason"]


class TestAvailable:
    def test_available_reports_the_winning_source_and_model(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_client(
            monkeypatch,
            is_available=lambda: (True, "ANTHROPIC_API_KEY set"),
            credential_source=lambda: "api_key",
        )

        response = client.get("/api/agents/health")

        assert response.status_code == 200
        body = response.json()
        assert body["available"] is True
        assert body["credential_source"] == "api_key"
        assert body["sdk_installed"] is True
        assert body["model"]  # non-empty -- DEFAULT_MODEL


# ---------------------------------------------------------------------------
# (b) Never echoes a credential value, in any of the above scenarios
# ---------------------------------------------------------------------------


class TestNeverEchoesACredential:
    def test_response_never_contains_a_fake_secret_set_in_the_environment(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_secret = "sk-ant-test-do-not-leak-9f3a7c21"
        monkeypatch.setenv("ANTHROPIC_API_KEY", fake_secret)
        _install_fake_client(
            monkeypatch,
            is_available=lambda: (True, "ANTHROPIC_API_KEY set"),
            credential_source=lambda: "api_key",
        )

        response = client.get("/api/agents/health")

        assert response.status_code == 200
        assert fake_secret not in response.text

    def test_response_never_contains_a_fake_secret_even_when_unavailable(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_secret = "sk-ant-test-do-not-leak-empty-shadow-key"
        monkeypatch.setenv("ANTHROPIC_API_KEY", fake_secret)
        _install_fake_client(
            monkeypatch,
            is_available=lambda: (False, "ANTHROPIC_API_KEY is set but empty"),
            credential_source=lambda: "none",
        )

        response = client.get("/api/agents/health")

        assert response.status_code == 200
        assert fake_secret not in response.text


# ---------------------------------------------------------------------------
# Route shape
# ---------------------------------------------------------------------------


class TestRouteShape:
    def test_health_is_a_get_only_route_under_api_agents(self, client: TestClient) -> None:
        _post = client.post("/api/agents/health")
        assert _post.status_code == 405

    def test_response_has_exactly_the_documented_fields(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_client(monkeypatch)

        response = client.get("/api/agents/health")

        assert response.status_code == 200
        assert set(response.json().keys()) == {
            "available",
            "credential_source",
            "reason",
            "model",
            "sdk_installed",
        }

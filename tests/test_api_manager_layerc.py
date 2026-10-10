"""HTTP surface for the manager desk's layer C (briefs, runs, chats, commissions).

Registration is asserted via `app.openapi()["paths"]` (FastAPI 0.141 hides `app.routes`), owner-only
is asserted for the new routes the same way `tests/test_api_manager.py` does for Phase 1, and the
service layer is monkeypatched so no route test ever makes a model call.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.manager import service as svc

PASSWORD = "correct-horse-staple"  # pragma: allowlist secret

LAYER_C_ROUTES = [
    "/api/manager/briefs",
    "/api/manager/runs",
    "/api/manager/runs/{run_id}",
    "/api/manager/runs/{run_id}/cancel",
    "/api/manager/briefs/latest",
    "/api/manager/briefs/{brief_id}",
    "/api/manager/chats",
    "/api/manager/chats/{thread_id}",
    "/api/manager/chats/{thread_id}/turns",
    "/api/manager/commissions/{commission_id}/approve",
    "/api/manager/commissions/{commission_id}/decline",
]


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    # `settings` (from conftest) disables auth, so these tests exercise the routes, not the gate.
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_all_layer_c_routes_are_registered() -> None:
    from app.main import app

    paths = app.openapi()["paths"]
    missing = [route for route in LAYER_C_ROUTES if route not in paths]
    assert not missing, f"unregistered manager routes: {missing}"


def test_post_brief_returns_202_with_a_run(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agentdesk.models import DeskRun
    from app.agents.models import AgentBudget

    fake = DeskRun(
        run_id="r1", kind="manager", state="queued", created_at=dt.datetime(2026, 9, 9, tzinfo=dt.UTC),
        config={}, stages=(), budget=AgentBudget(cap_usd=__import__("decimal").Decimal("3")),
    )
    monkeypatch.setattr(svc, "start_brief", lambda *a, **k: fake)
    r = client.post("/api/manager/briefs", json={"window": "yesterday"})
    assert r.status_code == 202
    assert r.json()["run_id"] == "r1"


def test_post_brief_conflict_is_409(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def _busy(*a: object, **k: object) -> None:
        raise svc.ManagerError("a manager brief is already running", status_code=409)

    monkeypatch.setattr(svc, "start_brief", _busy)
    r = client.post("/api/manager/briefs", json={})
    assert r.status_code == 409


def test_latest_brief_404_when_none(client: TestClient) -> None:
    r = client.get("/api/manager/briefs/latest")
    assert r.status_code == 404


def test_unknown_run_is_404(client: TestClient) -> None:
    r = client.get("/api/manager/runs/nope")
    assert r.status_code == 404


def test_runs_list_is_empty_ok(client: TestClient) -> None:
    r = client.get("/api/manager/runs")
    assert r.status_code == 200
    assert r.json() == {"runs": []}


def test_chat_create_get_delete(client: TestClient) -> None:
    created = client.post("/api/manager/chats")
    assert created.status_code == 201
    thread_id = created.json()["thread_id"]
    got = client.get(f"/api/manager/chats/{thread_id}")
    assert got.status_code == 200
    assert client.get("/api/manager/chats").json()[0]["thread_id"] == thread_id
    assert client.delete(f"/api/manager/chats/{thread_id}").status_code == 204
    assert client.get(f"/api/manager/chats/{thread_id}").status_code == 404


def test_chat_turn_maps_service_error(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    created = client.post("/api/manager/chats")
    thread_id = created.json()["thread_id"]

    def _unavailable(*a: object, **k: object) -> None:
        raise svc.ManagerError("agent layer unavailable", status_code=503)

    monkeypatch.setattr(svc, "chat_turn", _unavailable)
    r = client.post(f"/api/manager/chats/{thread_id}/turns", json={"question": "what changed?"})
    assert r.status_code == 503


def test_chat_turn_empty_question_is_422(client: TestClient) -> None:
    created = client.post("/api/manager/chats")
    thread_id = created.json()["thread_id"]
    r = client.post(f"/api/manager/chats/{thread_id}/turns", json={"question": ""})
    assert r.status_code == 422


def test_approve_commission_404_when_no_brief(client: TestClient) -> None:
    r = client.post("/api/manager/commissions/c1/approve")
    assert r.status_code == 404


# --- owner-only for the layer-C routes (auth on) ---

MEMBER_BLOCKED = [
    ("POST", "/api/manager/briefs"),
    ("GET", "/api/manager/runs"),
    ("POST", "/api/manager/chats"),
    ("POST", "/api/manager/commissions/c1/approve"),
]


@pytest.fixture
def auth_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    from app.auth import store
    from app.auth.throttle import THROTTLE

    for name, value in {
        "INVDASH_DATA_DIR": tmp_path / "data",
        "INVDASH_STORE_DIR": tmp_path / "store",
        "INVDASH_CACHE_DIR": tmp_path / "cache",
        "INVDASH_VAULT_DIR": tmp_path / "vault",
        "INVDASH_REFRESH_ON_STARTUP": "0",
        "INVDASH_SOCIAL_SNAPSHOT_SCHEDULER_ENABLED": "0",
        "INVDASH_AUTH_ENABLED": "1",
    }.items():
        monkeypatch.setenv(name, str(value))
    get_settings.cache_clear()
    cfg = get_settings()
    cfg.ensure_dirs()
    store.init_db(cfg)
    THROTTLE.reset()
    yield cfg
    get_settings.cache_clear()
    THROTTLE.reset()


@pytest.fixture
def member_client(auth_settings: Settings) -> TestClient:
    from app.auth import passwords, store
    from app.main import app

    store.create_user(auth_settings, "alice", passwords.hash_password(PASSWORD))  # first = owner
    store.create_user(auth_settings, "bob", passwords.hash_password(PASSWORD))    # member
    test_client = TestClient(app)
    r = test_client.post("/api/auth/login", json={"username": "bob", "password": PASSWORD})
    assert r.status_code == 200
    return test_client


@pytest.mark.parametrize(("method", "path"), MEMBER_BLOCKED)
def test_member_gets_403_on_layer_c(member_client: TestClient, method: str, path: str) -> None:
    r = member_client.request(method, path, json={} if method == "POST" else None)
    assert r.status_code == 403
    assert r.json() == {"detail": "owner_only"}

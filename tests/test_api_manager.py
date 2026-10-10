"""Integration tests for the manager desk's Phase 1 HTTP surface: config, changes, snapshot-now.

**No model calls anywhere in this file.** Phase 1 is layer A/B only (collect, persist, diff); one
test explicitly proves `GET /changes` works with the agent layer reported unavailable, which is the
whole point of that layering.

Route *registration* is checked via ``app.openapi()["paths"]`` rather than ``app.routes``: FastAPI
0.141 does not list these routes on the latter, a false negative that has cost this repo real time
before (see `tests/test_api_personas.py`'s own docstring and the memory note it was written from).

Owner-only coverage mirrors `tests/test_auth_gate_routes.py`'s `member_client`/`authed_client`
pattern locally, since those fixtures are defined in that file, not in `conftest.py`.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.manager import service as manager_service
from app.manager.models import ManagerSnapshot

NOW = dt.datetime(2026, 9, 9, 12, 0, tzinfo=dt.UTC)


def _fake_snapshot(*, as_of: dt.date, scope: str = "owner") -> ManagerSnapshot:
    return ManagerSnapshot(
        scope=scope,  # type: ignore[arg-type]
        as_of=as_of.isoformat(),
        generated_at=NOW.isoformat(),
        sections=(),
        warnings=(),
    )


def _fake_collect_factory():
    """A `collect()` stand-in that honours the `as_of`/`scope` kwargs the real one takes, so a
    snapshot saved for one date and read back for another stays self-consistent."""

    def _fake_collect(
        settings: object,
        *,
        scope: str = "owner",
        as_of: dt.date | None = None,
        now: dt.datetime | None = None,
    ) -> ManagerSnapshot:
        resolved = as_of or (now or NOW).date()
        return _fake_snapshot(as_of=resolved, scope=scope)

    return _fake_collect


# --- unauthenticated-gate-off fixtures (mirrors tests/test_api_personas.py) -------------------


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """Client whose stores are redirected into the test's tmp dir by the `settings` fixture (auth
    disabled there), so reads/writes hit an empty temporary tree, never the developer's real data."""
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


# --- route registration -------------------------------------------------------------------


def test_routes_registered() -> None:
    from app.main import app

    paths = app.openapi()["paths"]
    for path in ("/api/manager/config", "/api/manager/changes", "/api/manager/snapshot"):
        assert path in paths, f"{path} missing from openapi paths: {sorted(paths)}"


# --- GET /config ----------------------------------------------------------------------------


def test_config_ok_with_no_snapshot_dir_and_no_manager_run(client: TestClient) -> None:
    r = client.get("/api/manager/config")
    assert r.status_code == 200
    body = r.json()
    assert "agent_available" in body
    assert isinstance(body["agent_available"], bool)
    assert body["caps"]["brief_usd"]
    assert body["caps"]["commission_usd"]
    assert body["caps"]["chat_usd"]
    assert body["caps"]["daily_usd"]
    assert body["last_snapshot_at"] is None
    assert body["last_brief_at"] is None


# --- GET /changes -----------------------------------------------------------------------------


def test_changes_ok_with_agent_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Layer B must not care whether the agent layer is reachable at all."""
    import app.manager.service as svc

    monkeypatch.setattr(svc, "is_available", lambda: (False, "no credential"))
    monkeypatch.setattr(svc, "collect", _fake_collect_factory())

    r = client.get("/api/manager/changes", params={"window": "yesterday"})
    assert r.status_code == 200


def test_changes_no_prior_snapshot_does_not_crash(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(manager_service, "collect", _fake_collect_factory())

    r = client.get("/api/manager/changes", params={"window": "yesterday"})
    assert r.status_code == 200
    body = r.json()
    assert body["since"] is None
    assert body["items"] == []


def test_changes_bogus_window_is_422(client: TestClient) -> None:
    r = client.get("/api/manager/changes", params={"window": "bogus"})
    assert r.status_code == 422


# --- POST /snapshot then GET /changes sees it as prior --------------------------------------


def test_snapshot_then_next_day_changes_sees_it_as_prior(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(manager_service, "collect", _fake_collect_factory())

    day1 = dt.date(2026, 9, 9)
    day2 = dt.date(2026, 9, 10)

    r = client.post("/api/manager/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert body["scope"] == "owner"
    assert body["as_of"] == day1.isoformat()

    r2 = client.get(
        "/api/manager/changes",
        params={"window": "custom", "date": day2.isoformat()},
    )
    assert r2.status_code == 200
    change_set = r2.json()
    assert change_set["since"] == day1.isoformat()
    assert change_set["prior_snapshot"] == day1.isoformat()
    assert change_set["until"] == day2.isoformat()


# --- owner-only: mirrors tests/test_auth_gate_routes.py's member_client/authed_client pattern ---

PASSWORD = "correct-horse-staple"  # pragma: allowlist secret

MANAGER_ROUTES_GET = ["/api/manager/config", "/api/manager/changes"]


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
    auth_settings = get_settings()
    auth_settings.ensure_dirs()
    store.init_db(auth_settings)
    THROTTLE.reset()
    yield auth_settings
    get_settings.cache_clear()
    THROTTLE.reset()


@pytest.fixture
def owner_client(auth_settings: Settings) -> TestClient:
    from app.auth import passwords, store
    from app.main import app

    store.create_user(auth_settings, "alice", passwords.hash_password(PASSWORD))
    test_client = TestClient(app)  # no `with`: lifespan must not run
    r = test_client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
    assert r.status_code == 200
    return test_client


@pytest.fixture
def member_client(auth_settings: Settings, owner_client: TestClient) -> TestClient:
    from app.auth import passwords, store
    from app.main import app

    store.create_user(auth_settings, "bob", passwords.hash_password(PASSWORD))
    test_client = TestClient(app)
    r = test_client.post("/api/auth/login", json={"username": "bob", "password": PASSWORD})
    assert r.status_code == 200
    return test_client


@pytest.mark.parametrize("path", MANAGER_ROUTES_GET)
def test_member_gets_403(member_client: TestClient, path: str) -> None:
    r = member_client.get(path)
    assert r.status_code == 403
    assert r.json() == {"detail": "owner_only"}


def test_member_gets_403_on_snapshot(member_client: TestClient) -> None:
    r = member_client.post("/api/manager/snapshot")
    assert r.status_code == 403
    assert r.json() == {"detail": "owner_only"}


@pytest.mark.parametrize("path", MANAGER_ROUTES_GET)
def test_owner_passes(owner_client: TestClient, path: str) -> None:
    assert owner_client.get(path).status_code not in (401, 403)


def test_owner_passes_snapshot(owner_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manager_service, "collect", _fake_collect_factory())
    assert owner_client.post("/api/manager/snapshot").status_code not in (401, 403)

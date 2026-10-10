"""HTTP tests for the user-administration routes (`app.api.users`).

Auth is disabled for this suite (see the `settings` fixture in `tests/conftest.py`), so these tests
exercise the endpoints directly rather than the access gate -- that is `tests/test_auth_api.py`'s
job. `app.auth.store.init_db` is called explicitly because nothing else in this fixture chain
creates the auth database (the app's own `lifespan` does that, but a plain `TestClient(app)` used
without `with` never runs it -- `tests/test_auth_api.py` calls it explicitly for the same reason).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.auth import store
from app.config import Settings
from app.main import app


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    store.init_db(settings)
    yield TestClient(app)


def test_list_users_empty(client: TestClient) -> None:
    r = client.get("/api/users")
    assert r.status_code == 200
    assert r.json() == {"users": []}


def test_create_user(client: TestClient) -> None:
    r = client.post("/api/users", json={"username": "Alice", "password": "correct-horse"})
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "alice"  # normalized
    assert body["disabled"] is False
    assert "created_at" in body and isinstance(body["created_at"], str)
    assert "password_hash" not in body
    assert "password" not in body

    listed = client.get("/api/users").json()["users"]
    assert [u["username"] for u in listed] == ["alice"]


def test_create_user_duplicate_is_409(client: TestClient) -> None:
    client.post("/api/users", json={"username": "alice", "password": "correct-horse"})  # pragma: allowlist secret
    r = client.post("/api/users", json={"username": "alice", "password": "another-password"})
    assert r.status_code == 409

    # Case/whitespace variants normalize to the same username and still collide.
    r2 = client.post("/api/users", json={"username": " Alice ", "password": "another-password"})
    assert r2.status_code == 409


def test_create_user_weak_password_is_422(client: TestClient) -> None:
    r = client.post("/api/users", json={"username": "bob", "password": "ab"})
    assert r.status_code == 422
    assert client.get("/api/users").json() == {"users": []}


def test_set_password(client: TestClient, settings: Settings) -> None:
    from app.auth import passwords

    client.post("/api/users", json={"username": "alice", "password": "correct-horse"})  # pragma: allowlist secret
    r = client.post("/api/users/alice/password", json={"password": "brand-new-password"})
    assert r.status_code == 200
    assert r.json() == {"username": "alice"}

    # The new hash actually verifies, the old one no longer does.
    user = store.get_user(settings, "alice")
    assert user is not None
    assert passwords.verify_password("brand-new-password", user.password_hash)
    assert not passwords.verify_password("correct-horse", user.password_hash)


def test_set_password_unknown_user_is_404(client: TestClient) -> None:
    r = client.post("/api/users/ghost/password", json={"password": "brand-new-password"})
    assert r.status_code == 404


def test_set_password_weak_is_422(client: TestClient) -> None:
    client.post("/api/users", json={"username": "alice", "password": "correct-horse"})  # pragma: allowlist secret
    r = client.post("/api/users/alice/password", json={"password": "ab"})
    assert r.status_code == 422


def test_disable_then_enable_user(client: TestClient) -> None:
    # `root` goes first and is therefore the owner; `alice` is a member who can be disabled.
    client.post("/api/users", json={"username": "root", "password": "correct-horse"})  # pragma: allowlist secret
    client.post("/api/users", json={"username": "alice", "password": "correct-horse"})  # pragma: allowlist secret

    r = client.post("/api/users/alice/disable")
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "alice"
    assert body["disabled"] is True

    r2 = client.post("/api/users/alice/enable")
    assert r2.status_code == 200
    assert r2.json()["disabled"] is False


# --- roles ------------------------------------------------------------------


def test_first_user_is_owner_then_members(client: TestClient) -> None:
    r = client.post("/api/users", json={"username": "root", "password": "correct-horse"})
    assert r.status_code == 201 and r.json()["role"] == "owner"
    r2 = client.post("/api/users", json={"username": "alice", "password": "correct-horse"})
    assert r2.json()["role"] == "member"  # the default
    r3 = client.post(
        "/api/users", json={"username": "bob", "password": "correct-horse", "role": "owner"}  # pragma: allowlist secret
    )
    assert r3.json()["role"] == "owner"
    listed = {u["username"]: u["role"] for u in client.get("/api/users").json()["users"]}
    assert listed == {"root": "owner", "alice": "member", "bob": "owner"}


def test_create_user_unknown_role_is_422(client: TestClient) -> None:
    r = client.post(
        "/api/users", json={"username": "alice", "password": "correct-horse", "role": "admin"}  # pragma: allowlist secret
    )
    assert r.status_code == 422


def test_set_role_endpoint(client: TestClient) -> None:
    client.post("/api/users", json={"username": "root", "password": "correct-horse"})  # pragma: allowlist secret
    client.post("/api/users", json={"username": "alice", "password": "correct-horse"})  # pragma: allowlist secret

    r = client.post("/api/users/alice/role", json={"role": "owner"})
    assert r.status_code == 200
    assert r.json()["role"] == "owner"

    # Two owners now, so the original may step down.
    r2 = client.post("/api/users/root/role", json={"role": "member"})
    assert r2.status_code == 200 and r2.json()["role"] == "member"

    assert client.post("/api/users/ghost/role", json={"role": "owner"}).status_code == 404
    assert client.post("/api/users/alice/role", json={"role": "admin"}).status_code == 422


def test_last_owner_cannot_be_demoted_or_disabled(client: TestClient) -> None:
    client.post("/api/users", json={"username": "root", "password": "correct-horse"})  # pragma: allowlist secret
    client.post("/api/users", json={"username": "alice", "password": "correct-horse"})  # pragma: allowlist secret

    r = client.post("/api/users/root/role", json={"role": "member"})
    assert r.status_code == 409 and r.json() == {"detail": "last_owner"}
    r2 = client.post("/api/users/root/disable")
    assert r2.status_code == 409 and r2.json() == {"detail": "last_owner"}
    # Still the enabled owner afterwards.
    listed = {u["username"]: u for u in client.get("/api/users").json()["users"]}
    assert listed["root"]["role"] == "owner" and listed["root"]["disabled"] is False


def test_disable_unknown_user_is_404(client: TestClient) -> None:
    assert client.post("/api/users/ghost/disable").status_code == 404


def test_enable_unknown_user_is_404(client: TestClient) -> None:
    assert client.post("/api/users/ghost/enable").status_code == 404


def test_revoke_sessions(client: TestClient, settings: Settings) -> None:
    from app.auth import passwords as pw

    user = store.create_user(settings, "alice", pw.hash_password("correct-horse"))
    store.create_session(settings, user.id, "tokenhash-1", expires_at="2999-01-01T00:00:00+00:00")
    store.create_session(settings, user.id, "tokenhash-2", expires_at="2999-01-01T00:00:00+00:00")

    r = client.post("/api/users/alice/revoke-sessions")
    assert r.status_code == 200
    assert r.json() == {"revoked": 2}

    # A second call has nothing left to revoke.
    r2 = client.post("/api/users/alice/revoke-sessions")
    assert r2.json() == {"revoked": 0}


def test_revoke_sessions_unknown_user_is_404(client: TestClient) -> None:
    assert client.post("/api/users/ghost/revoke-sessions").status_code == 404

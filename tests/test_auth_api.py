"""HTTP tests for the auth routes and the access gate, with auth turned ON.

The suite-wide `settings` fixture disables auth; these tests do the opposite -- they build their own
tmp-rooted environment with `INVDASH_AUTH_ENABLED=1` and drive the real app through `TestClient`, so
the gate is genuinely in the request path.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import passwords, store
from app.auth.throttle import THROTTLE
from app.config import Settings, get_settings
from app.main import app

PASSWORD = "correct-horse-staple"  # pragma: allowlist secret


@pytest.fixture
def auth_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
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
    settings = get_settings()
    settings.ensure_dirs()
    store.init_db(settings)
    THROTTLE.reset()
    yield settings
    get_settings.cache_clear()
    THROTTLE.reset()


@pytest.fixture
def client(auth_settings: Settings) -> TestClient:
    store.create_user(auth_settings, "alice", passwords.hash_password(PASSWORD))
    # `raise_server_exceptions` default True is fine; we never expect a 500 here.
    return TestClient(app)


def _login(client: TestClient, username: str = "alice", password: str = PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


# --- gate -------------------------------------------------------------------


def test_gate_blocks_anonymous(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 401
    assert r.json() == {"detail": "not_authenticated"}


def test_health_is_allowlisted(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200


def test_health_stores_is_gated(client: TestClient) -> None:
    # The exact /api/health is open; its data-revealing siblings are not.
    assert client.get("/api/health/providers").status_code == 401


def test_docs_are_gated(client: TestClient) -> None:
    assert client.get("/openapi.json").status_code == 401


def test_gate_allows_after_login(client: TestClient) -> None:
    assert _login(client).status_code == 200
    r = client.get("/")  # cookie now stored on the client
    assert r.status_code == 200
    assert r.json()["name"] == "investing-dashboard"


# --- login ------------------------------------------------------------------


def test_login_sets_httponly_lax_cookie(client: TestClient) -> None:
    r = _login(client)
    assert r.status_code == 200
    assert r.json() == {"username": "alice"}
    set_cookie = r.headers["set-cookie"].lower()
    assert "invdash_session=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "secure" not in set_cookie  # auth_cookie_secure defaults False


def test_login_wrong_password(client: TestClient) -> None:
    r = _login(client, password="wrong-password-xx")
    assert r.status_code == 401
    assert r.json() == {"detail": "invalid_credentials"}


def test_login_unknown_user_is_indistinguishable(client: TestClient) -> None:
    r = _login(client, username="mallory", password="whatever-longx")
    assert r.status_code == 401
    assert r.json() == {"detail": "invalid_credentials"}


def test_disabled_user_cannot_login(client: TestClient, auth_settings: Settings) -> None:
    # alice was created first and is the owner; the store refuses to disable the last enabled
    # owner, so promote a second account before locking her out.
    store.create_user(auth_settings, "root", passwords.hash_password(PASSWORD), role="owner")
    store.set_disabled(auth_settings, "alice", True)
    assert _login(client).status_code == 401


def test_login_locks_after_five_failures(client: TestClient) -> None:
    for _ in range(5):
        assert _login(client, password="wrong-password-xx").status_code == 401  # pragma: allowlist secret
    r = _login(client, password="wrong-password-xx")
    assert r.status_code == 429
    body = r.json()
    assert body["detail"] == "locked"
    assert body["retry_after_seconds"] > 0
    # Even the correct password is refused while locked.
    assert _login(client).status_code == 429


# --- me / logout ------------------------------------------------------------


def test_me_anonymous_then_authenticated(client: TestClient) -> None:
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json() == {
        "auth_enabled": True, "authenticated": False, "username": None, "role": None
    }
    _login(client)
    r = client.get("/api/auth/me")
    # alice is the first (and only) user, hence the owner.
    assert r.json() == {
        "auth_enabled": True, "authenticated": True, "username": "alice", "role": "owner"
    }


def test_me_reports_member_role(client: TestClient, auth_settings: Settings) -> None:
    store.create_user(auth_settings, "bob", passwords.hash_password(PASSWORD))
    assert _login(client, username="bob").status_code == 200
    assert client.get("/api/auth/me").json()["role"] == "member"


def test_logout_clears_session(client: TestClient) -> None:
    _login(client)
    assert client.get("/").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/").status_code == 401


def test_me_no_store_header(client: TestClient) -> None:
    assert client.get("/api/auth/me").headers.get("cache-control") == "no-store"


# --- change password --------------------------------------------------------


def test_change_password_requires_session(client: TestClient) -> None:
    r = client.post("/api/auth/password", json={"current": PASSWORD, "new": "new-password-xy"})
    assert r.status_code == 401
    assert r.json() == {"detail": "not_authenticated"}


def test_change_password_wrong_current(client: TestClient) -> None:
    _login(client)
    r = client.post("/api/auth/password", json={"current": "nope-nope-nope", "new": "new-password-xy"})
    assert r.status_code == 401
    assert r.json() == {"detail": "invalid_credentials"}


def test_change_password_too_short(client: TestClient) -> None:
    _login(client)
    r = client.post("/api/auth/password", json={"current": PASSWORD, "new": "ab"})
    assert r.status_code == 422


def test_change_password_success_and_relogin(client: TestClient) -> None:
    _login(client)
    r = client.post("/api/auth/password", json={"current": PASSWORD, "new": "brand-new-password"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    # The current session still works (it was spared).
    assert client.get("/").status_code == 200
    # A fresh client can log in with the new password, not the old.
    fresh = TestClient(app)
    assert fresh.post("/api/auth/login", json={"username": "alice", "password": PASSWORD}).status_code == 401
    assert fresh.post(
        "/api/auth/login", json={"username": "alice", "password": "brand-new-password"}  # pragma: allowlist secret
    ).status_code == 200


def test_change_password_revokes_other_sessions(client: TestClient) -> None:
    _login(client)
    other = TestClient(app)
    assert other.post("/api/auth/login", json={"username": "alice", "password": PASSWORD}).status_code == 200
    assert other.get("/").status_code == 200
    # The first client changes the password; the other client's session is revoked.
    client.post("/api/auth/password", json={"current": PASSWORD, "new": "brand-new-password"})
    assert other.get("/").status_code == 401


# --- auth disabled ----------------------------------------------------------


def test_gate_is_noop_when_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVDASH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("INVDASH_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("INVDASH_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("INVDASH_REFRESH_ON_STARTUP", "0")
    monkeypatch.setenv("INVDASH_AUTH_ENABLED", "0")
    get_settings.cache_clear()
    try:
        c = TestClient(app)
        assert c.get("/").status_code == 200  # no session, still allowed
        # With auth off there is no session to carry a role; the gate lets everything through, so
        # the UI is told "owner" and renders every section.
        assert c.get("/api/auth/me").json() == {
            "auth_enabled": False,
            "authenticated": False,
            "username": None,
            "role": "owner",
        }
    finally:
        get_settings.cache_clear()


def test_auth_disabled_logs_a_startup_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`lifespan` must say, loudly, that every route is open when `INVDASH_AUTH_ENABLED=0` -- the
    one moment an operator watching the console can catch a deployment that forgot to turn auth back
    on before binding wider than loopback."""
    monkeypatch.setenv("INVDASH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("INVDASH_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("INVDASH_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("INVDASH_REFRESH_ON_STARTUP", "0")
    monkeypatch.setenv("INVDASH_AUTH_ENABLED", "0")
    get_settings.cache_clear()
    try:
        with caplog.at_level(logging.WARNING, logger="app.main"), TestClient(app):
            pass
    finally:
        get_settings.cache_clear()

    assert any(
        "every route" in record.message and "loopback" in record.message
        for record in caplog.records
    )


def test_auth_enabled_logs_no_such_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The mirror image: with auth on (the normal, locked default), `lifespan` must stay silent."""
    monkeypatch.setenv("INVDASH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("INVDASH_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("INVDASH_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("INVDASH_REFRESH_ON_STARTUP", "0")
    monkeypatch.setenv("INVDASH_AUTH_ENABLED", "1")
    get_settings.cache_clear()
    try:
        with caplog.at_level(logging.WARNING, logger="app.main"), TestClient(app):
            pass
    finally:
        get_settings.cache_clear()

    assert not any("every route" in record.message for record in caplog.records)


# --- X-Forwarded-For trust ---------------------------------------------------


def test_forwarded_for_ignored_by_default_for_throttle_bucket(auth_settings: Settings) -> None:
    """`auth_trust_forwarded_for` defaults `False`: a caller claiming a fresh `X-Forwarded-For` on
    every attempt must not be able to dodge the per-IP lockout, because the throttle keys on the
    real socket peer regardless of what the header claims. Distinct usernames per attempt so only
    the IP-keyed bucket (not the per-username one) is what locks the sixth request."""
    client = TestClient(app)
    for i in range(5):
        r = client.post(
            "/api/auth/login",
            json={"username": f"nobody-{i}", "password": "wrong-password-xx"},  # pragma: allowlist secret
            headers={"X-Forwarded-For": f"10.0.0.{i}"},
        )
        assert r.status_code == 401
    r = client.post(
        "/api/auth/login",
        json={"username": "nobody-fresh", "password": "wrong-password-xx"},  # pragma: allowlist secret
        headers={"X-Forwarded-For": "10.0.0.99"},
    )
    assert r.status_code == 429


def test_forwarded_for_trusted_flag_lets_a_spoofed_header_dodge_the_ip_bucket(
    auth_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the flag on (the one supported topology: this process directly behind the app's own
    nginx), a distinct `X-Forwarded-For` per attempt buys a distinct throttle bucket per attempt --
    proving the setting actually changes `_client_ip`'s behaviour, not just that it exists."""
    monkeypatch.setenv("INVDASH_AUTH_TRUST_FORWARDED_FOR", "1")
    get_settings.cache_clear()
    client = TestClient(app)
    for i in range(5):
        r = client.post(
            "/api/auth/login",
            json={"username": f"nobody-{i}", "password": "wrong-password-xx"},  # pragma: allowlist secret
            headers={"X-Forwarded-For": f"10.0.0.{i}"},
        )
        assert r.status_code == 401
    # A header value never seen before: its own bucket has zero failures, so this must not be locked.
    r = client.post(
        "/api/auth/login",
        json={"username": "nobody-fresh", "password": "wrong-password-xx"},  # pragma: allowlist secret
        headers={"X-Forwarded-For": "10.0.0.99"},
    )
    assert r.status_code == 401


def test_forwarded_for_trusted_flag_reads_the_last_hop_not_the_first(
    auth_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`frontend/Dockerfile`'s nginx config *appends* its own view of the caller
    (`$proxy_add_x_forwarded_for`) rather than overwriting the header, so a caller's own forged value
    survives as every entry except the last one nginx itself added. `_client_ip` must key on that
    last entry -- reading the first would take the attacker-supplied value straight back out of the
    header nginx was supposed to have corrected, defeating the whole point of trusting the setting."""
    monkeypatch.setenv("INVDASH_AUTH_TRUST_FORWARDED_FOR", "1")
    get_settings.cache_clear()
    client = TestClient(app)
    # Five attempts, each with the SAME real (last-hop) address behind a DIFFERENT forged leading
    # one -- simulating an attacker who varies the header's client-supplied portion while nginx keeps
    # appending its own, unchanging view of who is actually connecting.
    for i in range(5):
        r = client.post(
            "/api/auth/login",
            json={"username": f"nobody-{i}", "password": "wrong-password-xx"},  # pragma: allowlist secret
            headers={"X-Forwarded-For": f"1.2.3.{i}, 203.0.113.7"},
        )
        assert r.status_code == 401
    # The sixth attempt varies the forged leading entry yet again, but shares the same real last hop
    # -- if `_client_ip` were reading the first entry instead of the last, this would look like a
    # brand-new IP and would not be locked. It must be locked, because the real, trusted hop is the
    # one that repeated five times.
    r = client.post(
        "/api/auth/login",
        json={"username": "nobody-fresh", "password": "wrong-password-xx"},  # pragma: allowlist secret
        headers={"X-Forwarded-For": "9.9.9.9, 203.0.113.7"},
    )
    assert r.status_code == 429

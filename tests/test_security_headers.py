"""Every `/api/` response carries the security headers -- including the SSE stream.

`app.auth.headers.SecurityHeadersMiddleware` is raw ASGI for the same reason the login gate is: it
must append headers to `http.response.start` without ever touching a body frame, or
`GET /api/paperlive/stream` stops streaming. So this file checks both halves -- a plain JSON route
and the real event stream -- and asserts the stream's own frames still arrive intact, which is the
thing a buffering middleware would break (`tests/test_auth_gate_streaming.py` pins the same
property against the gate).

It also pins the two deliberate omissions: no HSTS (TLS does not terminate in front of this
process -- see `docs/AUTH.md`) and no CSP (that belongs on the nginx serving the HTML, see
`frontend/Dockerfile`). A future change that adds either here should have to update this file and
that documentation together.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import paperlive as paperlive_api
from app.auth import passwords, store
from app.auth.throttle import THROTTLE
from app.config import Settings, get_settings
from app.main import app

PASSWORD = "correct-horse-staple"  # pragma: allowlist secret

EXPECTED = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "cache-control": "no-store",
}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    for name, value in {
        "INVDASH_DATA_DIR": tmp_path / "data",
        "INVDASH_STORE_DIR": tmp_path / "store",
        "INVDASH_CACHE_DIR": tmp_path / "cache",
        "INVDASH_VAULT_DIR": tmp_path / "vault",
        "INVDASH_REFRESH_ON_STARTUP": "0",
        "INVDASH_SOCIAL_SNAPSHOT_SCHEDULER_ENABLED": "0",
        "INVDASH_AUTH_ENABLED": "1",
        "INVDASH_PAPERLIVE_ENABLED": "1",
    }.items():
        monkeypatch.setenv(name, str(value))
    get_settings.cache_clear()
    settings: Settings = get_settings()
    settings.ensure_dirs()
    store.init_db(settings)
    store.create_user(settings, "alice", passwords.hash_password(PASSWORD))
    THROTTLE.reset()
    yield TestClient(app)
    get_settings.cache_clear()
    THROTTLE.reset()


def _assert_headers(headers: object) -> None:
    for name, value in EXPECTED.items():
        assert headers[name] == value, name  # type: ignore[index]


# --- the ordinary cases ------------------------------------------------------


def test_allowlisted_health_route_carries_the_headers(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    _assert_headers(r.headers)


def test_gate_denials_carry_the_headers(client: TestClient) -> None:
    """The 401 the gate writes itself never reaches a route, so it is the response most likely to
    be missed -- which is exactly why the middleware is registered outside the gate."""
    r = client.get("/api/portfolio")
    assert r.status_code == 401
    _assert_headers(r.headers)


def test_authenticated_json_route_carries_the_headers(client: TestClient) -> None:
    assert (
        client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD}).status_code
        == 200
    )
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    _assert_headers(r.headers)


def test_non_api_paths_are_untouched(client: TestClient) -> None:
    """The middleware covers `/api/` only. `/` is a two-key JSON stub, and in the deployed topology
    the HTML is served by nginx, which owns its own headers (and the CSP)."""
    r = client.get("/")
    assert "x-frame-options" not in r.headers


# --- SSE: headers appended, body still streamed ------------------------------


def test_sse_stream_carries_the_headers_and_still_streams(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_event_stream(source: object, symbols: object, **kwargs: object):
        yield "event: quotes\ndata: {\"n\": 1}\n\n"
        yield ": keepalive\n\n"
        yield "event: quotes\ndata: {\"n\": 2}\n\n"

    monkeypatch.setattr(paperlive_api, "_event_stream", fake_event_stream)
    assert (
        client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD}).status_code
        == 200
    )

    resp = client.get("/api/paperlive/stream", params={"symbols": "AAPL"})
    assert resp.status_code == 200
    # The route's own headers survive: appending must not replace what the response already set.
    assert resp.headers["content-type"].startswith("text/event-stream")
    for name, value in EXPECTED.items():
        if name == "cache-control":
            # The SSE route sets its own `cache-control` (a stream must never be cached, and it
            # says so with more than `no-store`); the middleware appends only what is absent, so
            # the route's answer wins and there is exactly one such header.
            assert "no-cache" in resp.headers[name] or resp.headers[name] == value
            continue
        assert resp.headers[name] == value, name
    # And the body is still every frame, in order -- not one buffered blob.
    assert resp.text == (
        "event: quotes\ndata: {\"n\": 1}\n\n"
        ": keepalive\n\n"
        "event: quotes\ndata: {\"n\": 2}\n\n"
    )


# --- the deliberate omissions ------------------------------------------------


@pytest.mark.parametrize("absent", ["strict-transport-security", "content-security-policy"])
def test_hsts_and_csp_are_not_set_here(client: TestClient, absent: str) -> None:
    assert absent not in client.get("/api/health").headers


def test_no_header_is_sent_twice(client: TestClient) -> None:
    """`cache-control` is the one the gate and several routes already set for themselves. Appending
    unconditionally would send it twice, and a duplicated `cache-control` is a header a proxy is
    free to resolve either way."""
    r = client.get("/api/portfolio")  # 401 from the gate, which sets `cache-control` itself.
    assert r.status_code == 401
    assert len(r.headers.get_list("cache-control")) == 1
    assert r.headers["cache-control"] == "no-store"

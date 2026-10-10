"""The gate must not break Server-Sent Events.

`AuthGateMiddleware` is raw ASGI precisely so a `text/event-stream` response streams through it
untouched -- a `BaseHTTPMiddleware` would buffer it. This drives the real `/api/paperlive/stream`
route (real `StreamingResponse`, now behind the gate) with `_event_stream` replaced by a
multi-frame fake, exactly as `tests/test_api_paperlive.py::TestStreamRoute` does, and asserts every
frame arrives intact through an authenticated request -- and that an anonymous one is refused before
the stream ever opens.
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


def test_stream_is_gated_when_anonymous(client: TestClient) -> None:
    resp = client.get("/api/paperlive/stream", params={"symbols": "AAPL"})
    assert resp.status_code == 401
    assert resp.json() == {"detail": "not_authenticated"}


def test_stream_flows_through_the_gate_when_authenticated(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_event_stream(source: object, symbols: object, **kwargs: object):
        yield "event: quotes\ndata: {\"n\": 1}\n\n"
        yield ": keepalive\n\n"
        yield "event: quotes\ndata: {\"n\": 2}\n\n"

    monkeypatch.setattr(paperlive_api, "_event_stream", fake_event_stream)

    assert client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD}).status_code == 200

    resp = client.get("/api/paperlive/stream", params={"symbols": "AAPL"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    # Every frame the generator yielded survives the gate, in order and unbuffered-into-one.
    assert resp.text == (
        "event: quotes\ndata: {\"n\": 1}\n\n"
        ": keepalive\n\n"
        "event: quotes\ndata: {\"n\": 2}\n\n"
    )

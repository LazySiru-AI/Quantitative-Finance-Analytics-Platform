"""Pin the login gate against the app's real, sensitive data endpoints -- not the toy routes.

`tests/test_auth_api.py` proves the gate exists by hitting `/` and `/openapi.json`. It never touches
the routes that actually motivated adding a login screen: the tax routes (a complete realized-gains
history, wash-sale detections, an IRS form export) and the portfolio routes (current positions, the
transaction ledger). Those are exactly the endpoints an attacker -- or a careless refactor that adds
a new router without thinking about the gate -- would care about. This file asserts the gate covers
them too, plus the two `/api/health/*` siblings that are gated on purpose (they leak filesystem
paths and ledger transaction counts) even though the bare `/api/health` is allowlisted.

For the "signed in, no longer gated" half of the pin, this file never asserts `== 200`. Several of
these routes need real ledger/store data to compute a response, and the `auth_settings` fixture below
points every store at an empty `tmp_path` tree -- so a signed-in request can legitimately come back
404 or 422 or even 500 once it clears the gate. The gate itself only ever produces a 401, so `!= 401`
is the precise, false-positive-free way to prove the gate stopped blocking the request; asserting
`== 200` would make these tests fail on unrelated missing-data behaviour that has nothing to do with
auth.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import passwords, store
from app.auth.throttle import THROTTLE
from app.config import Settings, get_settings
from app.main import app

PASSWORD = "correct-horse-staple"  # pragma: allowlist secret

# Representative real GET routes needing no path parameters. Discovered via
# `app.openapi()["paths"]` (NOT `app.routes` -- see docs/../memory note on FastAPI 0.141). Must
# include the tax and portfolio routes (the actual reason login exists) plus the two /api/health/*
# siblings that are gated on purpose despite the bare /api/health being allowlisted.
SENSITIVE_ROUTES = [
    "/api/tax/report",
    "/api/tax/wash-sales",
    "/api/tax/form8949.csv",
    "/api/portfolio",
    "/api/portfolio/transactions",
    "/api/portfolio/statement.md",
    "/api/health/stores",
    "/api/health/providers",
    "/api/thesis/ledger",
    "/api/report/facts",
]


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
    # No `with` block: lifespan must not run, exactly as tests/test_auth_api.py does.
    return TestClient(app)


@pytest.fixture
def authed_client(client: TestClient) -> TestClient:
    r = client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
    assert r.status_code == 200
    return client  # TestClient persists the session cookie across requests.


# --- sensitive routes are gated when anonymous ------------------------------


@pytest.mark.parametrize("path", SENSITIVE_ROUTES)
def test_sensitive_route_blocks_anonymous(client: TestClient, path: str) -> None:
    r = client.get(path)
    assert r.status_code == 401
    assert r.json() == {"detail": "not_authenticated"}


# --- the same routes stop being gated once signed in ------------------------


@pytest.mark.parametrize("path", SENSITIVE_ROUTES)
def test_sensitive_route_not_gated_once_authenticated(authed_client: TestClient, path: str) -> None:
    r = authed_client.get(path)
    # Not `== 200`: these routes read from a tmp-rooted, empty store/ledger, so a signed-in request
    # can legitimately come back 404/422/500 for lack of data. The gate is the only thing that can
    # produce a 401 here, so `!= 401` is what actually pins "the gate let this request through".
    assert r.status_code != 401


# --- the owner role: members see research, not the ledger -------------------

#: Routes under `app.auth.gate.OWNER_ONLY_PREFIXES`. The transactions router lives under
#: `/api/portfolio`, and `/api/import` is the singular prefix `app.api.imports` actually registers.
OWNER_ONLY_ROUTES = [
    "/api/tax/report",
    "/api/tax/form8949.csv",
    "/api/portfolio",
    "/api/portfolio/transactions",
    "/api/import",
    "/api/users",
    "/api/health/stores",
]

#: Routes every signed-in user may reach. `/api/health/providers` is deliberately here: it is gated
#: (see `test_health_allowlisted_but_siblings_are_not`) but not owner-only, unlike its `/stores`
#: sibling which reports ledger counts.
RESEARCH_ROUTES = [
    "/api/thesis/ledger",
    "/api/report/facts",
    "/api/competition/rounds",
    "/api/health/providers",
]


@pytest.fixture
def member_client(client: TestClient, auth_settings: Settings) -> TestClient:
    """Signed in as `bob`, a member. `alice` (created first by `client`) is the owner."""
    store.create_user(auth_settings, "bob", passwords.hash_password(PASSWORD))
    r = client.post("/api/auth/login", json={"username": "bob", "password": PASSWORD})
    assert r.status_code == 200
    return client


@pytest.mark.parametrize("path", OWNER_ONLY_ROUTES)
def test_member_gets_403_on_owner_only_routes(member_client: TestClient, path: str) -> None:
    r = member_client.get(path)
    assert r.status_code == 403
    assert r.json() == {"detail": "owner_only"}


@pytest.mark.parametrize("path", OWNER_ONLY_ROUTES)
def test_owner_passes_owner_only_routes(authed_client: TestClient, path: str) -> None:
    # Same `!= 401` reasoning as above, extended: the gate is the only source of 401 *and* 403 here.
    assert authed_client.get(path).status_code not in (401, 403)


@pytest.mark.parametrize("path", RESEARCH_ROUTES)
def test_member_passes_research_routes(member_client: TestClient, path: str) -> None:
    assert member_client.get(path).status_code not in (401, 403)


def test_role_change_takes_effect_without_a_new_session(
    member_client: TestClient, auth_settings: Settings
) -> None:
    assert member_client.get("/api/tax/report").status_code == 403
    store.set_role(auth_settings, "bob", store.ROLE_OWNER)
    assert member_client.get("/api/tax/report").status_code not in (401, 403)


def test_owner_only_is_a_path_prefix_not_a_substring() -> None:
    from app.auth.gate import is_owner_only

    assert is_owner_only("/api/tax")
    assert is_owner_only("/api/tax/report")
    assert is_owner_only("/api/portfolio/transactions")
    assert is_owner_only("/api/health/stores")
    assert not is_owner_only("/api/taxonomy")
    assert not is_owner_only("/api/health")
    assert not is_owner_only("/api/health/providers")
    assert not is_owner_only("/api/competition/rounds")


# --- the allowlist is an exact match, not a prefix --------------------------


def test_health_allowlisted_but_siblings_are_not(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health/stores").status_code == 401
    assert client.get("/api/health/providers").status_code == 401


# --- OPTIONS is never gated --------------------------------------------------


@pytest.mark.parametrize("path", ["/api/tax/report", "/api/portfolio", "/api/health/stores"])
def test_options_is_never_gated(client: TestClient, path: str) -> None:
    r = client.options(path)
    assert r.status_code != 401


# --- auth disabled: the sensitive routes are not gated at all --------------


def test_sensitive_routes_are_noop_when_auth_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVDASH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("INVDASH_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("INVDASH_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("INVDASH_REFRESH_ON_STARTUP", "0")
    monkeypatch.setenv("INVDASH_AUTH_ENABLED", "0")
    get_settings.cache_clear()
    try:
        c = TestClient(app)
        for path in SENSITIVE_ROUTES:
            # Same "!= 401" reasoning as above: no ledger data behind these routes in this tmp
            # tree, but with the gate off a 401 can only mean the gate is still active.
            assert c.get(path).status_code != 401
    finally:
        get_settings.cache_clear()

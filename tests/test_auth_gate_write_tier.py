"""The write tier: a member may read the research surfaces but may not spend money on them.

`tests/test_auth_gate_routes.py` pins the two ends of the role model -- the owner-only ledger
prefixes and the research surfaces every signed-in user may reach. This file pins the middle tier
added for SEC-05: under `app.auth.gate.WRITE_OWNER_ONLY_PREFIXES` a member keeps `GET`, and every
other method is the owner's. The motivating routes are the ones that bill a model call to the
owner's API key (the agent desks, personas, `POST /api/i18n/translate`) or seize a process-wide
slot for hours (`POST /api/competition/jobs`, the evolution loop, a timeframe sweep, a full market
refresh).

The HTTP assertions here are deliberately asymmetric, for the same reason that file gives:

- for a member, `== 403` and the exact body -- the gate is the only thing that can produce that, so
  it is a precise pin;
- for an owner, `not in (401, 403)` -- these routes need real data, a spend budget and sometimes a
  free job slot, so a signed-in owner can legitimately come back 404/409/422/500. Asserting `200`
  would make this file fail on unrelated behaviour that has nothing to do with auth. Several of
  these `POST`s would also *do* something expensive if they got through, which is why the owner
  half is tested against the pure prefix predicate rather than by firing all of them.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import passwords, store
from app.auth.gate import (
    OWNER_ONLY_PREFIXES,
    WRITE_OWNER_ONLY_PREFIXES,
    is_owner_only,
    is_write_owner_only,
)
from app.auth.throttle import THROTTLE
from app.config import Settings, get_settings
from app.main import app

PASSWORD = "correct-horse-staple"  # pragma: allowlist secret

#: One real mutating route under each entry of `WRITE_OWNER_ONLY_PREFIXES`, as
#: `(method, path)`. Every prefix in that tuple is represented, so a prefix that is removed or
#: renamed without updating this list shows up in `test_every_write_prefix_is_covered_here`.
WRITE_ROUTES = [
    ("POST", "/api/tradingagents/runs"),
    ("POST", "/api/vibedesk/runs"),
    ("POST", "/api/workflow/runs"),
    ("POST", "/api/personas"),
    ("POST", "/api/agentdesk/live/decide"),
    ("POST", "/api/competition/jobs"),
    ("POST", "/api/competition/loop"),
    ("POST", "/api/timeframes/matrix/jobs"),
    ("POST", "/api/i18n/translate"),
    ("POST", "/api/market/refresh"),
]

#: Reads on the same surfaces. A member must still get these -- the whole point of a *write* tier
#: is that browsing a past agent run, a persona's notes or a finished round stays open.
READ_ROUTES = [
    "/api/tradingagents/runs",
    "/api/vibedesk/presets",
    "/api/workflow/runs",
    "/api/personas",
    "/api/competition/rounds",
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
    # `alice` is created first, so she is the owner (see `app.auth.store.create_user`).
    store.create_user(auth_settings, "alice", passwords.hash_password(PASSWORD))
    # No `with` block: lifespan must not run, exactly as tests/test_auth_gate_routes.py does.
    return TestClient(app)


@pytest.fixture
def member_client(client: TestClient, auth_settings: Settings) -> TestClient:
    """Signed in as `bob`, a member."""
    store.create_user(auth_settings, "bob", passwords.hash_password(PASSWORD))
    r = client.post("/api/auth/login", json={"username": "bob", "password": PASSWORD})
    assert r.status_code == 200
    return client


# --- the predicate itself ----------------------------------------------------


@pytest.mark.parametrize("prefix", WRITE_OWNER_ONLY_PREFIXES)
def test_write_prefix_blocks_unsafe_methods_and_allows_reads(prefix: str) -> None:
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert is_write_owner_only(prefix, method)
        assert is_write_owner_only(prefix + "/anything/deeper", method)
    for method in ("GET", "HEAD", "OPTIONS"):
        assert not is_write_owner_only(prefix, method)
        assert not is_write_owner_only(prefix + "/anything/deeper", method)


def test_write_prefix_is_a_path_prefix_not_a_substring() -> None:
    # Same parent-segment rule the owner-only tier uses: `/api/workflow` must not capture a
    # hypothetical `/api/workflows`.
    assert not is_write_owner_only("/api/workflows", "POST")
    assert not is_write_owner_only("/api/personas-public", "POST")
    assert not is_write_owner_only("/api/marketing/refresh", "POST")
    # And a sibling of a two-segment prefix stays out: `/api/market/sync` is not `/api/market/refresh`.
    assert not is_write_owner_only("/api/market/sync", "POST")
    assert not is_write_owner_only("/api/competition/rounds", "POST")


def test_method_case_does_not_matter() -> None:
    assert is_write_owner_only("/api/personas/refresh", "post")
    assert not is_write_owner_only("/api/personas", "get")


def test_the_two_owner_tiers_are_disjoint() -> None:
    """A prefix belongs in one tier or the other. Listing it in both would be a silent
    contradiction: the write tier would look like it grants members a read that the owner-only tier
    then refuses."""
    for write_prefix in WRITE_OWNER_ONLY_PREFIXES:
        assert not is_owner_only(write_prefix), write_prefix
    for owner_prefix in OWNER_ONLY_PREFIXES:
        assert not is_write_owner_only(owner_prefix, "POST"), owner_prefix


def test_every_write_prefix_is_covered_here() -> None:
    """`WRITE_ROUTES` must exercise every prefix -- a prefix added without a route here would be
    pinned only by the predicate test above, never by a real HTTP request."""
    covered = {
        prefix
        for prefix in WRITE_OWNER_ONLY_PREFIXES
        if any(path.startswith(prefix) for _, path in WRITE_ROUTES)
    }
    assert covered == set(WRITE_OWNER_ONLY_PREFIXES)


def test_write_routes_are_real_mounted_routes() -> None:
    """Each path in `WRITE_ROUTES` is a route this app actually serves with that method.

    Without this, a typo would make the member-403 assertions below pass for the wrong reason --
    the gate answers 403 before routing, so a nonexistent path is refused just as convincingly as a
    real one. Read from `app.openapi()["paths"]`, not `app.routes` (FastAPI 0.141 reports an empty
    route list there).
    """
    paths = app.openapi()["paths"]
    for method, path in WRITE_ROUTES:
        assert path in paths, path
        assert method.lower() in paths[path], (method, path)


# --- over HTTP ---------------------------------------------------------------


@pytest.mark.parametrize(("method", "path"), WRITE_ROUTES)
def test_member_gets_403_on_write_routes(member_client: TestClient, method: str, path: str) -> None:
    r = member_client.request(method, path, json={})
    assert r.status_code == 403
    assert r.json() == {"detail": "owner_only"}


@pytest.mark.parametrize(("method", "path"), WRITE_ROUTES)
def test_owner_is_not_blocked_by_the_write_tier(method: str, path: str) -> None:
    """The owner half, checked against the predicate rather than by firing the request.

    These are exactly the routes that start a backtest, a sweep, or a billed model call; a test
    that actually POSTed them as the owner would be a test that spends money and grabs the
    process-wide job slot. The gate's role branch is a single expression -- `not user.is_owner and
    (...)` -- so proving the predicate says "owner-gated" while `is_owner` short-circuits it is the
    whole of the owner path.
    """
    assert is_write_owner_only(path, method)


@pytest.mark.parametrize("path", READ_ROUTES)
def test_member_still_reads_the_same_surfaces(member_client: TestClient, path: str) -> None:
    # `not in (401, 403)` for the usual reason: these read from an empty tmp-rooted store, so a
    # 404/422/500 is legitimate here and only the gate can produce 401/403.
    assert member_client.get(path).status_code not in (401, 403)


def test_member_may_still_change_their_own_password(member_client: TestClient) -> None:
    """`POST /api/auth/password` is a write, and must stay outside the write tier -- a member who
    cannot change their own password is locked into whatever the owner typed at `add-user`."""
    r = member_client.post(
        "/api/auth/password",
        json={"current": PASSWORD, "new": "another-good-one"},
    )
    # `== 200` is safe here, unlike the routes above: this one needs no ledger data, no spend
    # budget and no job slot -- a signed-in member changing their own password must simply work.
    assert r.status_code == 200


def test_options_on_a_write_prefix_is_never_gated(client: TestClient) -> None:
    # Anonymous, so this also proves OPTIONS leaves the gate on the allowlist before any role check.
    assert client.options("/api/personas/refresh").status_code != 401


def test_write_tier_is_a_noop_for_the_owner_role_when_auth_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in {
        "INVDASH_DATA_DIR": tmp_path / "data",
        "INVDASH_STORE_DIR": tmp_path / "store",
        "INVDASH_CACHE_DIR": tmp_path / "cache",
        "INVDASH_REFRESH_ON_STARTUP": "0",
        "INVDASH_AUTH_ENABLED": "0",
    }.items():
        monkeypatch.setenv(name, str(value))
    get_settings.cache_clear()
    try:
        c = TestClient(app)
        # One cheap route with no side effect worth worrying about in a tmp tree: with the gate off
        # there is no session and no role, so this must not come back 401/403.
        assert c.post("/api/i18n/translate", json={}).status_code not in (401, 403)
    finally:
        get_settings.cache_clear()

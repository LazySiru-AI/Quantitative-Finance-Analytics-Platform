"""Path-parameter ids may not name anything outside the directory they index.

This file is the regression suite for the 2026-09-10 audit's SEC-01/03/14, plus the two smaller
information findings it raised alongside them (SEC-10, SEC-13).

The defect these tests pin: every desk router declared its run id as
``Annotated[str, Path(min_length=1, max_length=64)]`` -- a length bound and no alphabet -- and
``app.agentdesk.models.run_dir`` joined that string straight onto ``data/agentdesk/<kind>/runs/``.
A live probe of the running dev server returned **200 with a manager run** for
``GET /api/vibedesk/runs/..%5C..%5Cmanager%5Cruns%5C<id>``: the ``%2F`` spelling already 404'd
because Starlette's router never matched it, but ``%5C`` is not a path separator to the router and
is one to Windows. The manager router was worse still -- ``run_id``, ``thread_id``, ``brief_id`` and
``commission_id`` were all bare ``str``, and ``DELETE /api/manager/chats/{thread_id}`` **unlinks**
the file its id names.

Both halves are asserted here, deliberately:

* the HTTP boundary (``RUN_ID_PATTERN`` on every id path parameter), which is what turns the probe
  into a 422 or 404; and
* the containment check inside ``run_dir`` / ``_thread_path`` / ``_brief_path``, which is what makes
  the fix survive a future route that forgets the annotation.

Testing only the first would leave the class open the moment someone adds a router.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agentdesk.models import RUN_ID_PATTERN, DeskRun, run_dir, runs_dir
from app.agentdesk.store import RunStore
from app.agents.models import AgentBudget
from app.config import Settings

PASSWORD = "correct-horse-staple"  # pragma: allowlist secret

#: Ids that must never resolve to a run. Written as they travel on the wire, because that is the
#: layer the defect lived at: ``%5C`` is the one that actually got through, and it only gets through
#: if the test sends it percent-encoded rather than letting a client library normalise it away.
TRAVERSAL_IDS = [
    "..%5Cx",
    "..%5C..%5Cmanager%5Cruns%5Cabc",
    "..%5C..%5C..%5Cetc%5Cpasswd",
    "a%5Cb",
    "a%2Fb",
    "a/b",
    # Percent-encoded dot segments. The *un*-encoded `.` and `..` never reach the server at all --
    # httpx removes dot segments before sending, per RFC 3986 -- so sending them would assert
    # nothing about this application. The encoded spellings do arrive intact, which is exactly why
    # they are the ones worth pinning; the raw forms are covered against `run_dir` directly.
    "%2e",
    "%2e%2e",
    "%2e%2e%5C%2e%2e",
    "x" * 65,
]

#: The shape every id this application generates actually has (`uuid.uuid4().hex`), used wherever a
#: test needs an id that is *valid* so the rejection tests cannot pass by rejecting everything.
GOOD_ID = "0123456789abcdef0123456789abcdef"  # pragma: allowlist secret


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """The real app, auth off (the shared ``settings`` fixture pins ``INVDASH_AUTH_ENABLED=0``), so
    these tests exercise the routers rather than the gate."""
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def _seed_run(settings: Settings, kind: str, run_id: str) -> None:
    run = DeskRun(
        run_id=run_id,
        kind=kind,  # type: ignore[arg-type]
        state="succeeded",
        created_at=dt.datetime(2026, 9, 10, tzinfo=dt.UTC),
        budget=AgentBudget(cap_usd=Decimal("1")),
    )
    RunStore(settings, kind).save(run)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The pattern itself
# ---------------------------------------------------------------------------


class TestRunIdPattern:
    """`RUN_ID_PATTERN` has to admit every id already on disk and no separator at all. Chosen
    against the real alphabet: `data/agentdesk/{vibedesk,tradingagents,workflow}/runs/` is entirely
    32-character lowercase hex, and `data/agentdesk/manager/runs/` also holds `smoke-095628`, so the
    hyphen is load-bearing rather than defensive."""

    @pytest.mark.parametrize(
        "run_id",
        [
            "0123456789abcdef0123456789abcdef",  # uuid4().hex -- every generated id  # pragma: allowlist secret
            "smoke-095628",  # on disk under data/agentdesk/manager/runs/
            "r1",  # what the existing route tests use
            "not-a-real-job-id",
            "run_with_underscores",
            "a.b",
            "x" * 64,
        ],
    )
    def test_accepts_real_id_shapes(self, run_id: str) -> None:
        import re

        assert re.match(RUN_ID_PATTERN, run_id), run_id

    @pytest.mark.parametrize(
        "run_id",
        ["", ".", "..", "../x", r"..\x", "a/b", "a\\b", "/abs", "\\abs", ".hidden", "-lead"],
    )
    def test_rejects_separators_and_dot_segments(self, run_id: str) -> None:
        import re

        assert not re.match(RUN_ID_PATTERN, run_id), run_id


# ---------------------------------------------------------------------------
# The containment check, independent of any router
# ---------------------------------------------------------------------------


class TestRunDirContainment:
    def test_a_good_id_resolves_under_the_desks_runs_dir(self, settings: Settings) -> None:
        resolved = run_dir(settings, "vibedesk", GOOD_ID)
        assert resolved.parent == runs_dir(settings, "vibedesk").resolve()
        assert resolved.name == GOOD_ID

    @pytest.mark.parametrize(
        "run_id",
        ["..", "../manager/runs/x", r"..\..\manager\runs\x", "a/b", "", "."],
    )
    def test_a_non_child_id_raises(self, settings: Settings, run_id: str) -> None:
        with pytest.raises(ValueError):
            run_dir(settings, "vibedesk", run_id)

    def test_the_probe_from_the_audit_cannot_reach_the_manager_tree(
        self, settings: Settings
    ) -> None:
        """The exact traversal the live probe used, at the function the probe ultimately reached."""
        with pytest.raises(ValueError):
            run_dir(settings, "vibedesk", "..\\..\\manager\\runs\\abc")


class TestManagerStorePathContainment:
    def test_thread_path_rejects_a_non_child(self, settings: Settings) -> None:
        from app.manager.chat import ManagerChatStore

        store = ManagerChatStore(settings)
        with pytest.raises(ValueError):
            store._thread_path("..\\..\\secrets")

    def test_delete_thread_unlinks_nothing_for_a_traversal_id(self, settings: Settings) -> None:
        """`delete_thread` is the one that actually removes a file, so it gets its own test: a
        rejected id must read as "did not exist", not as "deleted something"."""
        from app.manager.chat import ManagerChatStore
        from app.manager.models import chats_dir

        chats = chats_dir(settings)
        chats.mkdir(parents=True, exist_ok=True)
        victim = chats.parent / "victim.json"
        victim.write_text("{}", encoding="utf-8")

        store = ManagerChatStore(settings)
        assert store.delete_thread("..\\victim") is False
        assert victim.is_file()

    def test_load_thread_returns_none_for_a_traversal_id(self, settings: Settings) -> None:
        from app.manager.chat import ManagerChatStore

        assert ManagerChatStore(settings).load_thread("..\\..\\anything") is None

    def test_brief_path_rejects_a_non_child(self, settings: Settings) -> None:
        from app.manager.pipeline import _brief_path

        with pytest.raises(ValueError):
            _brief_path(settings, "..\\..\\snapshots\\2026-09-09.owner")

    def test_load_brief_returns_none_for_a_traversal_id(self, settings: Settings) -> None:
        from app.manager.pipeline import load_brief

        assert load_brief(settings, "..\\..\\anything") is None


# ---------------------------------------------------------------------------
# The HTTP boundary
# ---------------------------------------------------------------------------

#: Every route whose path parameter names something on disk. The `{}` is where the id goes.
ID_ROUTES = [
    "/api/vibedesk/runs/{}",
    "/api/tradingagents/runs/{}",
    "/api/workflow/runs/{}",
    "/api/workflow/runs/{}/telemetry",
    "/api/manager/runs/{}",
    "/api/manager/briefs/{}",
    "/api/manager/chats/{}",
    "/api/competition/jobs/{}",
    "/api/timeframes/matrix/jobs/{}",
]


class TestTraversalIdsAreRefusedOverHTTP:
    @pytest.mark.parametrize("route", ID_ROUTES)
    @pytest.mark.parametrize("run_id", TRAVERSAL_IDS)
    def test_get_refuses(self, client: TestClient, route: str, run_id: str) -> None:
        response = client.get(route.format(run_id), follow_redirects=False)
        assert response.status_code in (404, 422), (
            f"{route.format(run_id)} answered {response.status_code}: {response.text[:200]}"
        )

    @pytest.mark.parametrize("run_id", TRAVERSAL_IDS)
    def test_manager_chat_delete_refuses(self, client: TestClient, run_id: str) -> None:
        """The highest-consequence route of the set -- it unlinks the file its id names -- so it is
        asserted on its own rather than folded into the GET sweep."""
        response = client.delete(f"/api/manager/chats/{run_id}", follow_redirects=False)
        assert response.status_code in (404, 422), (
            f"DELETE .../{run_id} answered {response.status_code}: {response.text[:200]}"
        )

    @pytest.mark.parametrize("route", ID_ROUTES)
    def test_an_empty_id_never_reaches_a_by_id_handler(
        self, client: TestClient, route: str
    ) -> None:
        """An empty segment collapses the URL onto a different route (or a redirect to one). What
        must not happen is a 200 from the by-id handler, which is what `min_length=1` alone left
        ambiguous."""
        response = client.get(route.format(""), follow_redirects=False)
        assert response.status_code != 200

    def test_the_exact_probe_from_the_audit_is_refused(self, client: TestClient) -> None:
        """Verbatim: this URL returned 200 with a manager run against the running dev server."""
        response = client.get(
            "/api/vibedesk/runs/..%5C..%5Cmanager%5Cruns%5C" + GOOD_ID, follow_redirects=False
        )
        assert response.status_code in (404, 422)


class TestValidIdsStillResolve:
    """The rejection tests above would all pass against a router that refused every id, so each desk
    also has to prove a real, existing run is still served."""

    def test_vibedesk(self, client: TestClient, settings: Settings) -> None:
        _seed_run(settings, "vibedesk", GOOD_ID)
        response = client.get(f"/api/vibedesk/runs/{GOOD_ID}")
        assert response.status_code == 200
        assert response.json()["run_id"] == GOOD_ID

    def test_tradingagents(self, client: TestClient, settings: Settings) -> None:
        _seed_run(settings, "tradingagents", GOOD_ID)
        response = client.get(f"/api/tradingagents/runs/{GOOD_ID}")
        assert response.status_code == 200
        assert response.json()["run_id"] == GOOD_ID

    def test_workflow(self, client: TestClient, settings: Settings) -> None:
        _seed_run(settings, "workflow", GOOD_ID)
        response = client.get(f"/api/workflow/runs/{GOOD_ID}")
        assert response.status_code == 200
        assert response.json()["run_id"] == GOOD_ID

    def test_manager_run(self, client: TestClient, settings: Settings) -> None:
        _seed_run(settings, "manager", GOOD_ID)
        response = client.get(f"/api/manager/runs/{GOOD_ID}")
        assert response.status_code == 200
        assert response.json()["run_id"] == GOOD_ID

    def test_manager_run_with_the_hyphenated_id_shape_on_disk(
        self, client: TestClient, settings: Settings
    ) -> None:
        """`data/agentdesk/manager/runs/smoke-095628` exists in the real tree; a pattern that
        rejected it would break a live run's page."""
        _seed_run(settings, "manager", "smoke-095628")
        response = client.get("/api/manager/runs/smoke-095628")
        assert response.status_code == 200

    def test_manager_chat_round_trip(self, client: TestClient) -> None:
        created = client.post("/api/manager/chats")
        assert created.status_code == 201
        thread_id = created.json()["thread_id"]

        assert client.get(f"/api/manager/chats/{thread_id}").status_code == 200
        assert client.delete(f"/api/manager/chats/{thread_id}").status_code == 204
        assert client.get(f"/api/manager/chats/{thread_id}").status_code == 404


# ---------------------------------------------------------------------------
# SEC-10 -- the health endpoint may not publish a filesystem path
# ---------------------------------------------------------------------------


class TestAgentHealthLeaksNoPath:
    def test_reason_carries_no_path_separator(self, client: TestClient) -> None:
        """`reason` on this machine read `Claude Code CLI binary found at
        C:\\Users\\<account>\\AppData\\...\\claude.exe` -- the operator's account name, on the one
        endpoint an ordinary page load hits."""
        body = client.get("/api/agents/health").json()
        reason = body["reason"]
        assert "/" not in reason
        assert "\\" not in reason

    def test_the_binary_name_survives_redaction(self) -> None:
        """Redaction has to leave the diagnosis intact: which binary was found is the useful half,
        where it lives is the half that leaks."""
        from app.api.agents import _redact_paths

        redacted = _redact_paths(
            "Claude Code CLI binary found at C:\\Users\\someone\\AppData\\Roaming\\claude.exe"
        )
        assert redacted == "Claude Code CLI binary found at claude.exe"

    @pytest.mark.parametrize(
        "reason",
        [
            "no Claude Code CLI binary found (checked INVDASH_CLAUDE_CLI, PATH, and the known "
            "install roots)",
            "ANTHROPIC_API_KEY is set",
            "",
        ],
    )
    def test_a_reason_with_no_path_is_unchanged(self, reason: str) -> None:
        from app.api.agents import _redact_paths

        assert _redact_paths(reason) == reason

    def test_a_posix_path_is_redacted_too(self) -> None:
        from app.api.agents import _redact_paths

        assert (
            _redact_paths("Claude Code CLI binary found at /usr/local/bin/claude")
            == "Claude Code CLI binary found at claude"
        )


# ---------------------------------------------------------------------------
# SEC-11 / SEC-13 -- the auth routes
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """Auth ON, rooted in a tmp dir -- the shape `tests/test_auth_api.py` uses, since the sessions
    these tests count only exist when the gate is real."""
    from app.auth import store
    from app.auth.throttle import THROTTLE
    from app.config import get_settings

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


class TestLoginDoesNotShortCircuitForAnUnknownUser:
    def test_an_unknown_username_still_verifies_a_password(
        self, auth_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Timing is not assertable on a shared CI box, so the *work* is asserted instead: the
        number of `verify_password` calls must be the same for a known and an unknown username.
        Counting the calls is what actually pins the short-circuit; a wall-clock comparison would
        be flaky and would not say which branch skipped the derivation."""
        from app.api import auth as auth_api
        from app.auth import passwords, store

        store.create_user(auth_settings, "alice", passwords.hash_password(PASSWORD))

        calls: list[str] = []
        real_verify = passwords.verify_password

        def counting_verify(password: str, encoded: str) -> bool:
            calls.append(encoded)
            return real_verify(password, encoded)

        monkeypatch.setattr(auth_api.passwords, "verify_password", counting_verify)

        from app.main import app

        client = TestClient(app)

        calls.clear()
        known = client.post("/api/auth/login", json={"username": "alice", "password": "wrong-pw"})  # pragma: allowlist secret
        known_calls = len(calls)

        calls.clear()
        unknown = client.post(
            "/api/auth/login", json={"username": "nobody-here", "password": "wrong-pw"}  # pragma: allowlist secret
        )
        unknown_calls = len(calls)

        assert known.status_code == 401
        assert unknown.status_code == 401
        assert known.json() == unknown.json()
        assert unknown_calls == known_calls == 1

    def test_a_disabled_user_also_verifies(
        self, auth_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.api import auth as auth_api
        from app.auth import passwords, store

        # The first account created is always the owner (`store.create_user`), and the store refuses
        # to disable the only enabled owner -- so `bob` needs an owner above him to be disable-able.
        store.create_user(auth_settings, "owner", passwords.hash_password(PASSWORD), role="owner")
        store.create_user(auth_settings, "bob", passwords.hash_password(PASSWORD))
        store.set_disabled(auth_settings, "bob", True)

        calls: list[str] = []
        real_verify = passwords.verify_password

        def counting_verify(password: str, encoded: str) -> bool:
            calls.append(encoded)
            return real_verify(password, encoded)

        monkeypatch.setattr(auth_api.passwords, "verify_password", counting_verify)

        from app.main import app

        response = TestClient(app).post(
            "/api/auth/login", json={"username": "bob", "password": PASSWORD}
        )
        assert response.status_code == 401
        assert len(calls) == 1

    def test_the_decoy_hash_is_a_real_hash_no_password_matches(self) -> None:
        """A decoy that failed to parse would return `False` from `verify_password` immediately and
        reintroduce the very short-circuit it exists to remove."""
        from app.api.auth import _DECOY_HASH
        from app.auth import passwords

        assert _DECOY_HASH.startswith("scrypt$")
        assert passwords.verify_password("decoy-not-a-real-password", _DECOY_HASH) is True
        assert passwords.verify_password(PASSWORD, _DECOY_HASH) is False


class TestAdminPasswordResetRevokesSessions:
    def test_set_password_deletes_the_users_sessions(self, auth_settings: Settings) -> None:
        """An owner resetting someone's password is almost always responding to a leak; leaving the
        old cookie working until it ages out defeats the reset."""
        from app.auth import passwords, sessions, store
        from app.main import app

        store.create_user(auth_settings, "owner", passwords.hash_password(PASSWORD), role="owner")
        victim = store.create_user(auth_settings, "victim", passwords.hash_password(PASSWORD))
        raw_token = sessions.start_session(auth_settings, victim)
        assert sessions.validate(auth_settings, raw_token) is not None

        client = TestClient(app)
        assert (
            client.post(
                "/api/auth/login", json={"username": "owner", "password": PASSWORD}
            ).status_code
            == 200
        )
        response = client.post(
            "/api/users/victim/password", json={"password": "brand-new-password"}  # pragma: allowlist secret
        )
        assert response.status_code == 200

        assert sessions.validate(auth_settings, raw_token) is None

    def test_the_owners_own_session_survives_resetting_someone_else(
        self, auth_settings: Settings
    ) -> None:
        """The revocation is scoped to the target user -- an owner must not log themselves out by
        resetting a member's password."""
        from app.auth import passwords, store
        from app.main import app

        store.create_user(auth_settings, "owner", passwords.hash_password(PASSWORD), role="owner")
        store.create_user(auth_settings, "victim", passwords.hash_password(PASSWORD))

        client = TestClient(app)
        client.post("/api/auth/login", json={"username": "owner", "password": PASSWORD})
        client.post("/api/users/victim/password", json={"password": "brand-new-password"})  # pragma: allowlist secret

        me = client.get("/api/auth/me").json()
        assert me["authenticated"] is True
        assert me["username"] == "owner"

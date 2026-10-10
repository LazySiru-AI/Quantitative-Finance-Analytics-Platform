"""The `/api/notify` HTTP surface, plus the gate's read-only service-token path.

Route *registration* is asserted via `app.openapi()["paths"]`, not `app.routes` -- FastAPI 0.141 does
not list these routes on the latter, a false negative that has cost this repo real time.

The service-token tests re-enable `auth_enabled` (the conftest `settings` fixture turns it off for
the whole suite), because the bearer path only exists inside the gate and a test running with the
gate disabled would pass no matter what the gate said.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.notify import events


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _no_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every API test off the delivery path. `POST /test` still reports honestly -- with
    delivery off (the shipped default) the correct answer is `sent: false`."""
    monkeypatch.setattr("app.notify.sender.dispatch", lambda settings, event: False)


class TestRegistration:
    def test_the_three_routes_are_registered_on_the_app(self, client: TestClient) -> None:
        from app.main import app

        paths = app.openapi()["paths"]
        assert "/api/notify/events" in paths
        assert "/api/notify/status" in paths
        assert "/api/notify/test" in paths
        assert "get" in paths["/api/notify/events"]
        assert "post" in paths["/api/notify/test"]


class TestEventsEndpoint:
    def test_empty_before_anything_is_emitted(self, client: TestClient) -> None:
        response = client.get("/api/notify/events")
        assert response.status_code == 200
        assert response.json() == {"events": []}

    def test_serves_emitted_events_newest_last(
        self, client: TestClient, settings: Settings
    ) -> None:
        for n in range(3):
            events.emit(
                settings,
                kind="manager.change",
                severity="notable",
                headline=f"item {n}",
                source="manager:account:cash_drift",
            )
        body = client.get("/api/notify/events").json()
        assert [event["headline"] for event in body["events"]] == ["item 0", "item 1", "item 2"]

    def test_since_and_limit_are_threaded_through(
        self, client: TestClient, settings: Settings
    ) -> None:
        first = events.emit(
            settings, kind="manager.change", severity="notable", headline="item 0"
        )
        events.emit(settings, kind="manager.change", severity="notable", headline="item 1")
        events.emit(settings, kind="manager.change", severity="notable", headline="item 2")
        assert first is not None

        body = client.get(f"/api/notify/events?since={first.id}").json()
        assert [event["headline"] for event in body["events"]] == ["item 1", "item 2"]

        body = client.get(f"/api/notify/events?since={first.id}&limit=1").json()
        assert [event["headline"] for event in body["events"]] == ["item 1"]

    def test_the_wire_shape_is_the_pinned_event_fields(
        self, client: TestClient, settings: Settings
    ) -> None:
        events.emit(
            settings,
            kind="manager.brief",
            severity="attention",
            headline="Manager brief: 2 attention item(s)",
            detail="Cash fell 4% · IRA drifted",
            refs=("brief-1",),
            source="manager:brief",
        )
        (event,) = client.get("/api/notify/events").json()["events"]
        assert set(event) == {"id", "ts", "kind", "severity", "headline", "detail", "refs", "source"}
        assert event["kind"] == "manager.brief"
        assert event["refs"] == ["brief-1"]


class TestStatusEndpoint:
    def test_reports_the_shipped_defaults_on_a_fresh_instance(self, client: TestClient) -> None:
        body = client.get("/api/notify/status").json()
        assert body["enabled"] is False
        assert body["channel"] == "log"
        assert body["total"] == 0
        assert body["last_event_ts"] is None


class TestTestEndpoint:
    def test_emits_an_attention_event_and_reports_it_was_not_sent(
        self, client: TestClient
    ) -> None:
        body = client.post("/api/notify/test").json()
        assert body["sent"] is False  # delivery is off by default; the event is logged regardless

        (event,) = client.get("/api/notify/events").json()["events"]
        assert event["kind"] == "notify.test"
        assert event["severity"] == "attention"
        assert event["id"] == body["event_id"]

    def test_reports_sent_when_the_channel_actually_delivers(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.notify.sender.dispatch", lambda settings, event: True)
        assert client.post("/api/notify/test").json()["sent"] is True


class TestServiceToken:
    """The gate's read-only bearer path (`app.auth.gate._SERVICE_TOKEN_PATHS`)."""

    TOKEN = "svc-token-for-tests"

    @pytest.fixture
    def gated(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> Iterator[TestClient]:
        """A client with the login gate ON and a service token configured."""
        monkeypatch.setenv("INVDASH_AUTH_ENABLED", "1")
        monkeypatch.setenv("INVDASH_NOTIFY_SERVICE_TOKEN", self.TOKEN)
        get_settings.cache_clear()
        from app.main import app

        with TestClient(app) as c:
            yield c
        get_settings.cache_clear()

    @pytest.fixture
    def gated_no_token(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> Iterator[TestClient]:
        """The same gate with `notify_service_token` left at its empty default."""
        monkeypatch.setenv("INVDASH_AUTH_ENABLED", "1")
        get_settings.cache_clear()
        from app.main import app

        with TestClient(app) as c:
            yield c
        get_settings.cache_clear()

    def test_without_any_credential_the_feed_is_401(self, gated: TestClient) -> None:
        response = gated.get("/api/notify/events")
        assert response.status_code == 401
        assert response.json()["detail"] == "not_authenticated"

    @pytest.mark.parametrize("path", ["/api/notify/events", "/api/notify/status"])
    def test_the_bearer_is_accepted_on_an_allowlisted_get(
        self, gated: TestClient, path: str
    ) -> None:
        response = gated.get(path, headers={"Authorization": f"Bearer {self.TOKEN}"})
        assert response.status_code == 200

    def test_a_wrong_bearer_is_rejected(self, gated: TestClient) -> None:
        response = gated.get(
            "/api/notify/events", headers={"Authorization": "Bearer not-the-token"}
        )
        assert response.status_code == 401

    def test_the_bearer_does_not_work_on_a_post(self, gated: TestClient) -> None:
        # Read-only by construction: the token names four GETs and nothing else.
        response = gated.post("/api/notify/test", headers={"Authorization": f"Bearer {self.TOKEN}"})
        assert response.status_code == 401

    def test_the_bearer_does_not_work_on_a_non_allowlisted_path(self, gated: TestClient) -> None:
        response = gated.get("/api/tax/report", headers={"Authorization": f"Bearer {self.TOKEN}"})
        assert response.status_code == 401

    def test_the_bearer_reaches_the_two_manager_feeds(self, gated: TestClient) -> None:
        # Not asserting the bodies -- the manager's own tests own those. What matters here is that
        # the gate did not answer 401, i.e. the request reached the router.
        for path in ("/api/manager/changes", "/api/manager/briefs/latest"):
            response = gated.get(path, headers={"Authorization": f"Bearer {self.TOKEN}"})
            assert response.status_code != 401, path

    def test_an_empty_token_setting_disables_the_path_entirely(
        self, gated_no_token: TestClient
    ) -> None:
        # No token configured: a bearer header must not become a way in.
        response = gated_no_token.get(
            "/api/notify/events", headers={"Authorization": "Bearer "}
        )
        assert response.status_code == 401
        assert gated_no_token.get("/api/notify/events").status_code == 401


class TestOwnerOnlyPrefixes:
    def test_notify_and_nav_telemetry_are_owner_scoped(self) -> None:
        from app.auth.gate import is_owner_only

        assert is_owner_only("/api/notify")
        assert is_owner_only("/api/notify/events")
        assert is_owner_only("/api/telemetry/nav/summary")
        # Prefix matching is segment-aware, not a bare `startswith`.
        assert not is_owner_only("/api/notifygrams")

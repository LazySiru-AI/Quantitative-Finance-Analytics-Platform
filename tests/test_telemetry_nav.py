"""Coverage for `app.telemetry.nav` (the append/summarise logic) and `app.api.telemetry_nav` (the
HTTP layer).

Follows `tests/test_api_live_decisions.py`'s pattern: a bare `FastAPI()` app around just this router,
not `app.main.app`, so the router tests exercise only this router and its role resolution -- the
access gate's own owner-only enforcement (`app.auth.gate.OWNER_ONLY_PREFIXES`) is out of scope here
by design; see this router's own module docstring for why. The `settings` fixture (from
`tests/conftest.py`) redirects every `INVDASH_*` path into a `tmp_path` tree and sets
`INVDASH_AUTH_ENABLED=0`, so `get_settings()` here always resolves to that isolated tree and
`_resolve_role` always answers `"owner"`, matching this app's single-user local-dev default.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.api import telemetry_nav as nav_api
from app.config import Settings
from app.telemetry import nav

#: A fixed recent day, so every hit below falls inside `summary`'s rolling 30-day window whatever
#: the date the suite runs on (a literal date silently aged out of the window).
_DAY = (dt.datetime.now(dt.UTC) - dt.timedelta(days=2)).date().isoformat()

# ---------------------------------------------------------------------------
# app.telemetry.nav -- record() / summary()
# ---------------------------------------------------------------------------


class TestRecordAndSummary:
    def test_round_trip_counts_hits_per_path_and_tab(self, settings: Settings) -> None:
        hits = [
            nav.NavHit(ts=f"{_DAY}T00:00:00+00:00", path="/tax", tab=None, role="owner"),
            nav.NavHit(ts=f"{_DAY}T00:05:00+00:00", path="/tax", tab="lots", role="owner"),
            nav.NavHit(ts=f"{_DAY}T00:06:00+00:00", path="/tax", tab="lots", role="owner"),
            nav.NavHit(ts=f"{_DAY}T00:10:00+00:00", path="/personas", tab=None, role="member"),
        ]

        written = nav.record(settings, hits)
        assert written == 4

        result = nav.summary(settings, days=30)
        assert result["total"] == 4
        by_key = {(r["path"], r["tab"]): r for r in result["routes"]}
        assert by_key[("/tax", None)]["hits"] == 1
        assert by_key[("/tax", "lots")]["hits"] == 2
        assert by_key[("/personas", None)]["hits"] == 1
        # Sorted by hits descending -- the busiest (path, tab) pair leads.
        assert result["routes"][0]["hits"] == 2

    def test_writes_are_appended_as_jsonl(self, settings: Settings) -> None:
        nav.record(settings, [nav.NavHit(ts=f"{_DAY}T00:00:00+00:00", path="/a", role="owner")])
        nav.record(settings, [nav.NavHit(ts=f"{_DAY}T00:01:00+00:00", path="/b", role="owner")])

        nav_path = settings.data_dir / "telemetry" / "nav.jsonl"
        lines = nav_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["path"] == "/a"
        assert json.loads(lines[1])["path"] == "/b"

    def test_validation_drops_paths_missing_a_leading_slash(self, settings: Settings) -> None:
        n = nav.record(
            settings, [nav.NavHit(ts=f"{_DAY}T00:00:00+00:00", path="tax", role="owner")]
        )
        assert n == 0
        assert nav.summary(settings, days=30)["total"] == 0

    def test_validation_drops_overlong_path(self, settings: Settings) -> None:
        n = nav.record(
            settings,
            [nav.NavHit(ts=f"{_DAY}T00:00:00+00:00", path="/" + "a" * 200, role="owner")],
        )
        assert n == 0

    def test_validation_drops_overlong_tab(self, settings: Settings) -> None:
        n = nav.record(
            settings,
            [nav.NavHit(ts=f"{_DAY}T00:00:00+00:00", path="/ok", tab="t" * 61, role="owner")],
        )
        assert n == 0

    def test_a_valid_event_survives_alongside_dropped_ones_in_the_same_batch(
        self, settings: Settings
    ) -> None:
        hits = [
            nav.NavHit(ts=f"{_DAY}T00:00:00+00:00", path="bad", role="owner"),
            nav.NavHit(ts=f"{_DAY}T00:00:00+00:00", path="/ok", tab="fine", role="owner"),
        ]
        n = nav.record(settings, hits)
        assert n == 1
        result = nav.summary(settings, days=30)
        assert result["routes"] == [
            {
                "path": "/ok",
                "tab": "fine",
                "hits": 1,
                "last_ts": f"{_DAY}T00:00:00+00:00",
            }
        ]

    def test_caps_at_100_events_per_call(self, settings: Settings) -> None:
        hits = [
            nav.NavHit(ts=f"{_DAY}T00:00:00+00:00", path=f"/p{i}", role="owner")
            for i in range(150)
        ]
        n = nav.record(settings, hits)
        assert n == 100
        assert nav.summary(settings, days=30)["total"] == 100

    def test_days_window_excludes_events_older_than_the_cutoff(self, settings: Settings) -> None:
        now = dt.datetime.now(dt.UTC)
        old = now - dt.timedelta(days=45)
        recent = now - dt.timedelta(days=1)
        nav.record(
            settings,
            [
                nav.NavHit(ts=old.isoformat(), path="/old", role="owner"),
                nav.NavHit(ts=recent.isoformat(), path="/recent", role="owner"),
            ],
        )

        result = nav.summary(settings, days=30)
        paths = {r["path"] for r in result["routes"]}
        assert paths == {"/recent"}
        assert result["total"] == 1

    def test_summary_on_an_empty_or_missing_log_is_zero_not_an_error(
        self, settings: Settings
    ) -> None:
        result = nav.summary(settings, days=30)
        assert result == {
            "days": 30,
            "since": result["since"],
            "total": 0,
            "routes": [],
        }

    def test_a_malformed_line_is_skipped_not_raised(self, settings: Settings) -> None:
        nav_path = settings.data_dir / "telemetry" / "nav.jsonl"
        nav_path.parent.mkdir(parents=True, exist_ok=True)
        good_ts = dt.datetime.now(dt.UTC).isoformat()
        with nav_path.open("w", encoding="utf-8") as handle:
            handle.write("not json at all\n")
            handle.write(json.dumps({"path": "/x", "role": "owner"}) + "\n")  # missing ts
            handle.write(
                json.dumps({"ts": good_ts, "path": "/good", "tab": None, "role": "owner"}) + "\n"
            )

        result = nav.summary(settings, days=30)
        assert result["total"] == 1
        assert result["routes"][0]["path"] == "/good"


# ---------------------------------------------------------------------------
# app.api.telemetry_nav -- HTTP layer
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(nav_api.router)
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


class TestRouter:
    def test_post_records_events_and_reports_the_count(
        self, client: TestClient, settings: Settings
    ) -> None:
        response = client.post(
            "/api/telemetry/nav",
            json={
                "events": [
                    {"path": "/tax", "tab": "lots", "ts": f"{_DAY}T00:00:00+00:00"},
                    {"path": "/overview", "ts": f"{_DAY}T00:01:00+00:00"},
                ]
            },
        )
        assert response.status_code == 200
        assert response.json() == {"recorded": 2}

    def test_post_drops_invalid_events_and_reports_the_reduced_count(
        self, client: TestClient, settings: Settings
    ) -> None:
        response = client.post(
            "/api/telemetry/nav",
            json={
                "events": [
                    {"path": "no-slash", "ts": f"{_DAY}T00:00:00+00:00"},
                    {"path": "/ok", "ts": f"{_DAY}T00:00:00+00:00"},
                ]
            },
        )
        assert response.status_code == 200
        assert response.json() == {"recorded": 1}

    def test_get_summary_reflects_what_was_posted(
        self, client: TestClient, settings: Settings
    ) -> None:
        client.post(
            "/api/telemetry/nav",
            json={"events": [{"path": "/tax", "tab": "lots", "ts": f"{_DAY}T00:00:00+00:00"}]},
        )

        response = client.get("/api/telemetry/nav/summary", params={"days": 30})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["routes"] == [
            {"path": "/tax", "tab": "lots", "hits": 1, "last_ts": f"{_DAY}T00:00:00+00:00"}
        ]

    def test_get_summary_default_window_is_30_days(
        self, client: TestClient, settings: Settings
    ) -> None:
        response = client.get("/api/telemetry/nav/summary")
        assert response.status_code == 200
        assert response.json()["days"] == 30

    def test_recorded_role_is_owner_when_auth_is_disabled(
        self, client: TestClient, settings: Settings
    ) -> None:
        # The `settings` fixture pins `INVDASH_AUTH_ENABLED=0` -- single-user local dev, so every
        # caller resolves to the owner.
        client.post(
            "/api/telemetry/nav",
            json={"events": [{"path": "/tax", "ts": f"{_DAY}T00:00:00+00:00"}]},
        )
        nav_path = settings.data_dir / "telemetry" / "nav.jsonl"
        recorded = json.loads(nav_path.read_text(encoding="utf-8").strip().splitlines()[0])
        assert recorded["role"] == "owner"
        # No username anywhere in the stored line.
        assert "username" not in recorded

    def test_client_supplied_role_is_ignored(self, client: TestClient, settings: Settings) -> None:
        """The event body has no `role` field at all (`NavEventIn`), so a client cannot spoof one --
        this proves the server-resolved role wins even if a caller tries to smuggle one in."""
        response = client.post(
            "/api/telemetry/nav",
            json={
                "events": [
                    {"path": "/tax", "ts": f"{_DAY}T00:00:00+00:00", "role": "owner-spoofed"}
                ]
            },
        )
        assert response.status_code == 200
        nav_path = settings.data_dir / "telemetry" / "nav.jsonl"
        recorded = json.loads(nav_path.read_text(encoding="utf-8").strip().splitlines()[0])
        assert recorded["role"] == "owner"

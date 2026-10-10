"""API smoke tests.

These assert the app boots, applies the schema on startup, and reports store state honestly --
which now includes *not* reporting a derived-state freshness it cannot know. This docstring used to
say the opposite, that distinguishing "current" from "stale" was the point; that distinction was
never reachable in production, and the tests asserting it are the subject of
``test_stores_reports_no_derived_state``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import sqlite as ledger
from app.main import app


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """A client whose storage is redirected into the test's temporary directory.

    The ``settings`` fixture has already pointed ``INVDASH_*`` at ``tmp_path`` and cleared the
    settings cache, so the app's lifespan hook and the health router both resolve to the temporary
    store without any patching of module internals.
    """
    with TestClient(app) as test_client:
        yield test_client


def test_health_is_live(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_advertises_docs(client: TestClient) -> None:
    assert client.get("/").json()["docs"] == "/docs"


def test_startup_creates_the_ledger(client: TestClient, settings: Settings) -> None:
    """The lifespan hook migrates on boot, so a fresh checkout works with no setup step."""
    client.get("/api/health")
    assert settings.ledger_path.exists()


class TestProviderHealth:
    """The chain reads as two sources for bars and is one. That should be stated, not inferred."""

    def test_names_the_single_point_of_failure(self, client: TestClient) -> None:
        body = client.get("/api/health/providers").json()

        assert body["bars"]["registered"] == 2
        assert body["bars"]["usable"] == 1
        assert body["bars"]["single_point_of_failure"] == "yahoo"

    def test_a_degraded_provider_carries_its_reason(self, client: TestClient) -> None:
        """"Unavailable" without a reason is indistinguishable from "not configured"."""
        body = client.get("/api/health/providers").json()
        stooq = next(p for p in body["providers"] if p["name"] == "stooq")

        assert stooq["usable"] is False
        assert "anti-bot" in stooq["degraded_reason"]

    def test_it_does_not_probe(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """Reported, not measured -- so it stays cheap and says the same thing every time.

        Asserted by making any outbound HTTP call fail: the endpoint must still answer. A probing
        implementation would put a network round trip per provider behind an endpoint meant to be
        polled, and would describe only this instant, while the fact worth knowing here is
        structural. Live failures are already reported by name on the request that hits them.
        """
        import httpx

        def refuse(*args: object, **kwargs: object) -> object:
            raise AssertionError("the providers endpoint must not make a network request")

        monkeypatch.setattr(httpx.Client, "send", refuse)
        assert client.get("/api/health/providers").status_code == 200


def test_stores_reports_empty_ledger(client: TestClient) -> None:
    body = client.get("/api/health/stores").json()
    assert body["ledger"]["exists"] is True
    assert body["ledger"]["transactions"] == 0


def test_stores_reports_no_derived_state(client: TestClient) -> None:
    """There is no derivation to be current or stale, so the endpoint claims neither.

    Two tests here used to insert into `derived_build` and assert "stale" and "current". Both passed
    for the life of the application while the field they exercised was, in production, permanently
    "never_built" -- nothing outside those tests ever wrote that table, because the materialised
    lots and gains it tracked were never built. Every derived figure is recomputed from the ledger
    per request, which is the argument `app.api.tax`'s module docstring makes: a cache that can
    silently disagree with the ledger underneath it is how a tax page shows figures that are no
    longer true.

    The tests are gone with the table. A test that exercises a state the system cannot reach is not
    coverage; it is a claim that the state matters.
    """
    body = client.get("/api/health/stores").json()
    assert "derived" not in body


def test_cors_does_not_allow_arbitrary_origins(client: TestClient) -> None:
    """The API serves the user's positions; a page on another site must not be able to read them."""
    response = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert response.headers.get("access-control-allow-origin") != "https://evil.example"


def test_unknown_route_is_404(client: TestClient) -> None:
    assert client.get("/api/nope").status_code == 404


def test_sqlite_row_factory_survives_json_encoding(client: TestClient) -> None:
    """sqlite3.Row is not JSON-serialisable; the endpoint must convert before returning."""
    body = client.get("/api/health/stores").json()
    assert isinstance(body["ledger"]["account"], int)


def test_ledger_is_readable_while_api_holds_it(settings: Settings) -> None:
    """WAL mode lets the scheduled fetch job read while the API writes -- the reason for two engines."""
    with ledger.connect(settings.ledger_path) as writer:
        ledger.migrate(writer)
        with ledger.connect(settings.ledger_path, read_only=True) as reader:
            assert reader.execute("SELECT COUNT(*) AS n FROM txn").fetchone()["n"] == 0
        with pytest.raises(sqlite3.OperationalError):
            reader_conn = ledger.connect(settings.ledger_path, read_only=True)
            with reader_conn as ro:
                ro.execute("INSERT INTO account VALUES ('x','robinhood','x','taxable','cash')")

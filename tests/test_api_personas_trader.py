"""Integration tests for the persona paper trader's HTTP surface (Phase 10).

**No model call.** Every mutating test monkeypatches `app.personas.trader_service.trader.
advance_one_decision`/`.backfill_trader` -- the same engine seam `tests/test_personas_trader_service.py`
patches -- so a request never reaches `app.agents`. Route *registration* is checked via
`app.openapi()["paths"]`, not `app.routes`: FastAPI 0.141 does not list these routes on the latter (see
`tests/test_api_personas.py`'s own docstring for the same note).
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.personas import trader, trader_service
from app.personas.models import Persona
from app.personas.store import VaultStore

NOW = dt.datetime(2026, 1, 10, 12, 0, tzinfo=dt.UTC)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def _make_persona(settings: Settings, slug: str = "alpha") -> Persona:
    persona = Persona(slug=slug, display_name=slug.title(), created_at=NOW)
    VaultStore(settings).save_persona(persona)
    return persona


def _canned_book(slug: str = "alpha") -> trader.TraderBook:
    return trader.TraderBook(
        persona=slug,
        display_name=slug.title(),
        inception=trader.DEFAULT_INCEPTION.isoformat(),
        as_of="2026-01-05",
        starting_cash=format(trader.STARTING_CASH_USD, "f"),
        cash="99000.00",
        equity="99500.00",
        return_pct="0.005",
        decisions=(
            trader.TraderDecisionRec(
                decided_on="2026-01-05", fill_date="2026-01-06", commentary="bought a dip",
                degraded=False, cost_usd="0.10",
            ),
        ),
        spent_usd="0.10",
    )


def _blob_for(book: trader.TraderBook) -> dict[str, Any]:
    return {
        "inception": book.inception, "broker_state": None, "equity_curve": [],
        "decisions": [], "spent_usd": book.spent_usd, "last_decided": book.as_of,
    }


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 5.0, interval: float = 0.02) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(interval)
    pytest.fail("timed out waiting for condition")


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


def test_trader_routes_are_registered() -> None:
    from app.main import app

    paths = app.openapi()["paths"]
    for path in (
        "/api/personas/trader/books",
        "/api/personas/{slug}/trader",
        "/api/personas/{slug}/trader/decide",
        "/api/personas/{slug}/trader/backfill",
        "/api/personas/{slug}/trader/backfill/{job_id}",
    ):
        assert path in paths, f"{path} is not registered"


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------


def test_empty_vault_trader_books_is_empty_not_error(client: TestClient) -> None:
    resp = client.get("/api/personas/trader/books")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_trader_unknown_persona_is_404(client: TestClient) -> None:
    assert client.get("/api/personas/nobody/trader").status_code == 404


def test_get_trader_never_traded_persona_is_empty_book(
    client: TestClient, settings: Settings
) -> None:
    _make_persona(settings, "alpha")
    resp = client.get("/api/personas/alpha/trader")
    assert resp.status_code == 200
    body = resp.json()
    assert body["persona"] == "alpha"
    assert body["as_of"] is None
    assert body["decisions"] == []


def test_trader_books_lists_every_persona(client: TestClient, settings: Settings) -> None:
    _make_persona(settings, "alpha")
    _make_persona(settings, "bravo")
    resp = client.get("/api/personas/trader/books")
    assert resp.status_code == 200
    slugs = {b["persona"] for b in resp.json()}
    assert slugs == {"alpha", "bravo"}


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def test_delete_trader_unknown_persona_is_404(client: TestClient) -> None:
    assert client.delete("/api/personas/nobody/trader").status_code == 404


def test_delete_trader_resets_the_book(client: TestClient, settings: Settings) -> None:
    _make_persona(settings, "alpha")
    trader.TraderStore(settings).save("alpha", {
        "inception": trader.DEFAULT_INCEPTION.isoformat(), "broker_state": None,
        "equity_curve": [], "decisions": [], "spent_usd": "1.00", "last_decided": None,
    })
    resp = client.delete("/api/personas/alpha/trader")
    assert resp.status_code == 204
    assert trader.TraderStore(settings).load("alpha") is None


# ---------------------------------------------------------------------------
# decide
# ---------------------------------------------------------------------------


def test_decide_unknown_persona_is_404(client: TestClient) -> None:
    assert client.post("/api/personas/nobody/trader/decide").status_code == 404


def test_decide_returns_book_and_persists_it(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_persona(settings, "alpha")
    canned = _canned_book("alpha")
    canned_blob = _blob_for(canned)

    def _fake_advance(**kwargs: object) -> tuple[trader.TraderBook, dict[str, Any]]:
        return canned, canned_blob

    monkeypatch.setattr(trader_service.trader, "advance_one_decision", _fake_advance)

    resp = client.post("/api/personas/alpha/trader/decide")
    assert resp.status_code == 200
    body = resp.json()
    assert body["persona"] == "alpha"
    assert body["cash"] == "99000.00"
    assert trader.TraderStore(settings).load("alpha") == canned_blob


def test_decide_budget_exhausted_is_409(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agents.models import BudgetExhausted

    _make_persona(settings, "alpha")

    def _fake_advance(**kwargs: object) -> tuple[trader.TraderBook, dict[str, Any]]:
        raise BudgetExhausted(Decimal("1"), Decimal("1"))

    monkeypatch.setattr(trader_service.trader, "advance_one_decision", _fake_advance)
    resp = client.post("/api/personas/alpha/trader/decide")
    assert resp.status_code == 409


def test_decide_agent_unavailable_is_503(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agents.models import AgentUnavailable

    _make_persona(settings, "alpha")

    def _fake_advance(**kwargs: object) -> tuple[trader.TraderBook, dict[str, Any]]:
        raise AgentUnavailable("no credential")

    monkeypatch.setattr(trader_service.trader, "advance_one_decision", _fake_advance)
    resp = client.post("/api/personas/alpha/trader/decide")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# backfill
# ---------------------------------------------------------------------------


def test_backfill_unknown_persona_is_404(client: TestClient) -> None:
    assert client.post("/api/personas/nobody/trader/backfill", json={}).status_code == 404


def test_backfill_bad_inception_is_422(client: TestClient, settings: Settings) -> None:
    _make_persona(settings, "alpha")
    resp = client.post("/api/personas/alpha/trader/backfill", json={"inception": "not-a-date"})
    assert resp.status_code == 422


def test_backfill_returns_202_then_job_is_pollable(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_persona(settings, "alpha")
    canned = _canned_book("alpha")
    canned_blob = _blob_for(canned)

    def _fake_backfill(**kwargs: object) -> tuple[trader.TraderBook, dict[str, Any]]:
        return canned, canned_blob

    monkeypatch.setattr(trader_service.trader, "backfill_trader", _fake_backfill)

    resp = client.post("/api/personas/alpha/trader/backfill", json={"inception": "2026-01-01"})
    assert resp.status_code == 202
    job = resp.json()
    assert job["persona"] == "alpha"
    assert job["state"] in ("queued", "running")

    def _poll() -> dict[str, Any]:
        r = client.get(f"/api/personas/alpha/trader/backfill/{job['job_id']}")
        assert r.status_code == 200
        return r.json()

    _wait_until(lambda: _poll()["state"] in ("succeeded", "failed"))
    final = _poll()
    assert final["state"] == "succeeded"
    assert final["decided_count"] == 1


def test_get_backfill_job_unknown_is_404(client: TestClient, settings: Settings) -> None:
    _make_persona(settings, "alpha")
    resp = client.get("/api/personas/alpha/trader/backfill/no-such-job")
    assert resp.status_code == 404

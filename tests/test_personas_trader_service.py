"""Tests for `app.personas.trader_service` -- the thin service layer over the (proven, untouched)
`app.personas.trader` engine.

**No model call, ever.** Every test monkeypatches `trader_service.trader.advance_one_decision` and/or
`.backfill_trader` with a canned callable, so nothing here reaches `app.agents`. That is the module
attribute the service calls through (`from app.personas import trader` at module scope, `trader.
advance_one_decision(...)`), so patching it there is enough -- there is no bound reference captured
elsewhere.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest

from app.agents.models import AgentUnavailable, BudgetExhausted
from app.config import Settings
from app.personas import trader, trader_service
from app.personas.models import Persona
from app.personas.service import PersonaError
from app.personas.store import VaultStore

NOW = dt.datetime(2026, 1, 10, 12, 0, tzinfo=dt.UTC)


def _make_persona(settings: Settings, slug: str = "alpha") -> Persona:
    persona = Persona(slug=slug, display_name=slug.title(), created_at=NOW)
    VaultStore(settings).save_persona(persona)
    return persona


def _canned_book(slug: str = "alpha", *, decisions: int = 1, spent: str = "0.10") -> trader.TraderBook:
    return trader.TraderBook(
        persona=slug,
        display_name=slug.title(),
        inception=trader.DEFAULT_INCEPTION.isoformat(),
        as_of="2026-01-05",
        starting_cash=format(trader.STARTING_CASH_USD, "f"),
        cash="99000.00",
        equity="99500.00",
        return_pct="0.005",
        decisions=tuple(
            trader.TraderDecisionRec(
                decided_on="2026-01-05", fill_date="2026-01-06", commentary="bought a dip",
                degraded=False, cost_usd=spent,
            )
            for _ in range(decisions)
        ),
        spent_usd=spent,
    )


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 5.0, interval: float = 0.02) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(interval)
    pytest.fail("timed out waiting for condition")


# ---------------------------------------------------------------------------
# decide_now
# ---------------------------------------------------------------------------


def test_decide_now_unknown_persona_is_404(settings: Settings) -> None:
    with pytest.raises(PersonaError) as excinfo:
        trader_service.decide_now(settings, "nobody")
    assert excinfo.value.status_code == 404


def test_decide_now_saves_blob_and_returns_book(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_persona(settings, "alpha")
    canned = _canned_book("alpha")
    canned_blob = {"inception": trader.DEFAULT_INCEPTION.isoformat(), "broker_state": None,
                    "equity_curve": [], "decisions": [], "spent_usd": "0.10", "last_decided": "2026-01-05"}

    captured: dict[str, Any] = {}

    def _fake_advance(**kwargs: object) -> tuple[trader.TraderBook, dict[str, Any]]:
        captured.update(kwargs)
        return canned, canned_blob

    monkeypatch.setattr(trader_service.trader, "advance_one_decision", _fake_advance)

    book = trader_service.decide_now(settings, "alpha")

    assert book is canned
    assert captured["model"] == settings.persona_trader_model
    assert captured["per_decision_cap_usd"] == Decimal(settings.persona_trader_decision_cap_usd)
    assert captured["daily_cap_usd"] == Decimal(settings.model_spend_daily_cap_usd)

    # the returned blob was persisted, not just the book handed back
    saved = trader.TraderStore(settings).load("alpha")
    assert saved == canned_blob


def test_decide_now_budget_exhausted_maps_to_409(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_persona(settings, "alpha")

    def _fake_advance(**kwargs: object) -> tuple[trader.TraderBook, dict[str, Any]]:
        raise BudgetExhausted(Decimal("1.00"), Decimal("1.00"))

    monkeypatch.setattr(trader_service.trader, "advance_one_decision", _fake_advance)

    with pytest.raises(PersonaError) as excinfo:
        trader_service.decide_now(settings, "alpha")
    assert excinfo.value.status_code == 409


def test_decide_now_agent_unavailable_maps_to_503(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_persona(settings, "alpha")

    def _fake_advance(**kwargs: object) -> tuple[trader.TraderBook, dict[str, Any]]:
        raise AgentUnavailable("no credential")

    monkeypatch.setattr(trader_service.trader, "advance_one_decision", _fake_advance)

    with pytest.raises(PersonaError) as excinfo:
        trader_service.decide_now(settings, "alpha")
    assert excinfo.value.status_code == 503


# ---------------------------------------------------------------------------
# backfill job lifecycle
# ---------------------------------------------------------------------------


def test_start_backfill_unknown_persona_is_404(settings: Settings) -> None:
    with pytest.raises(PersonaError) as excinfo:
        trader_service.start_backfill(settings, "nobody", inception=None)
    assert excinfo.value.status_code == 404


def test_backfill_runs_to_succeeded_and_saves_blob(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_persona(settings, "bravo")
    canned = _canned_book("bravo", decisions=3, spent="1.23")
    canned_blob = {"inception": trader.DEFAULT_INCEPTION.isoformat(), "broker_state": None,
                    "equity_curve": [], "decisions": [], "spent_usd": "1.23", "last_decided": "2026-01-05"}

    def _fake_backfill(**kwargs: object) -> tuple[trader.TraderBook, dict[str, Any]]:
        return canned, canned_blob

    monkeypatch.setattr(trader_service.trader, "backfill_trader", _fake_backfill)

    job = trader_service.start_backfill(settings, "bravo", inception=None)
    assert job.persona == "bravo"
    assert job.state in ("queued", "running")

    _wait_until(lambda: trader_service.get_backfill_job(settings, "bravo", job.job_id).state
                in ("succeeded", "failed"))

    final = trader_service.get_backfill_job(settings, "bravo", job.job_id)
    assert final.state == "succeeded"
    assert final.decided_count == 3
    assert final.spent_usd == "1.23"
    assert final.finished_at is not None

    saved = trader.TraderStore(settings).load("bravo")
    assert saved == canned_blob


def test_backfill_failure_is_reported_not_raised(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_persona(settings, "charlie")

    def _fake_backfill(**kwargs: object) -> tuple[trader.TraderBook, dict[str, Any]]:
        raise RuntimeError("boom")

    monkeypatch.setattr(trader_service.trader, "backfill_trader", _fake_backfill)

    job = trader_service.start_backfill(settings, "charlie", inception=None)
    _wait_until(lambda: trader_service.get_backfill_job(settings, "charlie", job.job_id).state
                in ("succeeded", "failed"))

    final = trader_service.get_backfill_job(settings, "charlie", job.job_id)
    assert final.state == "failed"
    assert final.error is not None and "boom" in final.error


def test_second_start_while_active_is_409(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_persona(settings, "delta")
    release = threading.Event()

    def _fake_backfill(**kwargs: object) -> tuple[trader.TraderBook, dict[str, Any]]:
        release.wait(timeout=5.0)
        return _canned_book("delta"), {
            "inception": trader.DEFAULT_INCEPTION.isoformat(), "broker_state": None,
            "equity_curve": [], "decisions": [], "spent_usd": "0", "last_decided": None,
        }

    monkeypatch.setattr(trader_service.trader, "backfill_trader", _fake_backfill)

    try:
        first = trader_service.start_backfill(settings, "delta", inception=None)
        _wait_until(lambda: trader_service.get_backfill_job(settings, "delta", first.job_id).state
                    == "running")

        with pytest.raises(PersonaError) as excinfo:
            trader_service.start_backfill(settings, "delta", inception=None)
        assert excinfo.value.status_code == 409
    finally:
        release.set()
        _wait_until(lambda: trader_service.get_backfill_job(settings, "delta", first.job_id).state
                    in ("succeeded", "failed"))


def test_get_backfill_job_unknown_job_is_404(settings: Settings) -> None:
    _make_persona(settings, "echo")
    with pytest.raises(PersonaError) as excinfo:
        trader_service.get_backfill_job(settings, "echo", "no-such-job")
    assert excinfo.value.status_code == 404


def test_backfill_inception_defaults_to_engine_default(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_persona(settings, "foxtrot")
    captured: dict[str, Any] = {}

    def _fake_backfill(**kwargs: object) -> tuple[trader.TraderBook, dict[str, Any]]:
        captured.update(kwargs)
        return _canned_book("foxtrot"), {
            "inception": trader.DEFAULT_INCEPTION.isoformat(), "broker_state": None,
            "equity_curve": [], "decisions": [], "spent_usd": "0", "last_decided": None,
        }

    monkeypatch.setattr(trader_service.trader, "backfill_trader", _fake_backfill)
    job = trader_service.start_backfill(settings, "foxtrot", inception=None)
    _wait_until(lambda: trader_service.get_backfill_job(settings, "foxtrot", job.job_id).state
                in ("succeeded", "failed"))
    assert captured["inception"] == trader.DEFAULT_INCEPTION
    assert captured["per_decision_cap_usd"] == Decimal(settings.persona_trader_decision_cap_usd)
    assert captured["daily_cap_usd"] == Decimal(settings.persona_trader_backfill_cap_usd)

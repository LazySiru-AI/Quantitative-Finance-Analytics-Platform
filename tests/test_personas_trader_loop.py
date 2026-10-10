"""Tests for the persona trader daemon (`app.personas.trader_loop`), mirroring
`tests/test_personas_refresh_loop.py`'s shape for its sibling daemon.

No network, no model, no real thread left running past the test: the enabled-thread test stops the
loop in a `finally` before returning, and the sweep-logic test drives `_sweep` directly with
`trader_service.decide_now` monkeypatched, so it proves the sweep's per-persona resilience without
spawning the daemon or spending a cent.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable
from decimal import Decimal

import pytest

from app.agents.spend import SpendCapExceeded
from app.config import Settings, get_settings
from app.personas import service, trader_loop, trader_service
from app.personas.models import Persona
from app.personas.service import PersonaError


def _cfg(monkeypatch: pytest.MonkeyPatch, **over: str) -> Settings:
    for k, v in over.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    return get_settings()


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 5.0, interval: float = 0.02) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(interval)
    pytest.fail("timed out waiting for condition")


def test_start_is_a_noop_when_disabled(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """Default off: `start` returns None and spawns nothing. The suite must never run this daemon."""
    cfg = _cfg(monkeypatch)  # settings fixture does not set the flag -> disabled
    assert cfg.persona_trader_enabled is False
    assert trader_loop.start(cfg) is None


def test_start_spawns_a_thread_and_returns_an_event_when_enabled(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Enabled: `start` returns a `threading.Event` and a live daemon thread exists. The sweep itself
    is monkeypatched to a no-op so this never reaches the model; the event is set immediately in a
    `finally` so no thread from this test outlives it."""
    cfg = _cfg(monkeypatch, INVDASH_PERSONA_TRADER_ENABLED="1")
    assert cfg.persona_trader_enabled is True

    calls: list[Settings] = []
    monkeypatch.setattr(trader_loop, "_sweep", lambda s: calls.append(s))

    event = trader_loop.start(cfg)
    try:
        assert event is not None
        _wait_until(lambda: len(calls) >= 1)  # the loop sweeps once immediately on start
        assert trader_loop._thread is not None
        assert trader_loop._thread.is_alive()

        # idempotent: a second call while running returns the same event, not a second thread
        again = trader_loop.start(cfg)
        assert again is event
    finally:
        trader_loop.stop()
        assert event.is_set()


def test_sweep_advances_every_persona_tolerating_per_persona_failure(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One sweep calls `trader_service.decide_now` once per persona, and one persona's `PersonaError`
    (no notes, already caught up, budget cap) or `SpendCapExceeded` never stops the others."""
    now = dt.datetime(2026, 1, 10, tzinfo=dt.UTC)
    calls: list[str] = []

    def _fake_list(_settings: Settings) -> tuple[Persona, ...]:
        return (
            Persona(slug="alpha", display_name="A", created_at=now),
            Persona(slug="capped", display_name="C", created_at=now),
            Persona(slug="broke", display_name="B", created_at=now),
        )

    def _fake_decide(_settings: Settings, slug: str) -> object:
        calls.append(slug)
        if slug == "capped":
            raise PersonaError("no notes yet", status_code=409)
        if slug == "broke":
            raise SpendCapExceeded(Decimal("25"), Decimal("25"), retry_after_seconds=60)
        return object()  # alpha "succeeds"

    monkeypatch.setattr(service, "list_personas", _fake_list)
    monkeypatch.setattr(trader_service, "decide_now", _fake_decide)

    trader_loop._sweep(settings)  # must not raise despite the capped/broke personas

    assert calls == ["alpha", "capped", "broke"]  # every persona attempted, in order

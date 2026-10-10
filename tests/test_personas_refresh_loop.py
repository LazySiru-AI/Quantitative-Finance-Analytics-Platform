"""Tests for the persona top-up daemon.

No network, no model, no real thread left running: the enabled-path test drives `_sweep` directly
with `start_ingest` monkeypatched, so it proves the sweep's behaviour (call once per persona, tolerate
an already-running ingest, tolerate a per-persona failure) without spawning the daemon or spending a
cent. The off-by-default path is asserted through the public `start`.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.config import Settings, get_settings
from app.personas import refresh_loop, service
from app.personas.models import Persona


def _cfg(monkeypatch: pytest.MonkeyPatch, **over: str) -> Settings:
    for k, v in over.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    return get_settings()


def test_start_is_a_noop_when_disabled(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """Default off: `start` returns None and spawns nothing. The suite must never run this daemon."""
    cfg = _cfg(monkeypatch)  # settings fixture does not set the flag -> disabled
    assert cfg.persona_refresh_enabled is False
    assert refresh_loop.start(cfg) is None


def test_sweep_tops_up_every_persona(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One sweep calls start_ingest once per persona, and one persona's failure or already-running
    ingest never stops the others."""
    from app.personas.jobs import IngestAlreadyActive

    calls: list[str] = []

    def _fake_list(_settings: Settings):  # type: ignore[no-untyped-def]
        now = dt.datetime(2026, 9, 2, tzinfo=dt.UTC)
        return (
            Persona(slug="alpha", display_name="A", created_at=now),
            Persona(slug="busy", display_name="B", created_at=now),
            Persona(slug="empty", display_name="E", created_at=now),
        )

    def _fake_start(_settings: Settings, slug: str, **kw: object):  # type: ignore[no-untyped-def]
        calls.append(slug)
        if slug == "busy":
            raise IngestAlreadyActive("busy", "job-1")
        if slug == "empty":
            raise service.PersonaError("nothing to ingest", status_code=409)
        return None  # alpha "succeeds"

    monkeypatch.setattr(service, "list_personas", _fake_list)
    monkeypatch.setattr(service, "start_ingest", _fake_start)

    refresh_loop._sweep(settings)  # must not raise despite the busy/empty personas

    assert calls == ["alpha", "busy", "empty"]  # every persona attempted, in order

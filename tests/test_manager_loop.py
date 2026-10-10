"""Tests for the manager desk's opt-in daily-brief daemon (`app.manager.loop`), mirroring
`tests/test_personas_trader_loop.py`'s shape for its sibling daemon.

No network, no model, no real thread left running past a test: every test that spawns a live thread
sets its stop event (or calls `loop.stop()`) in a `finally` before returning. The daemon's actual
scheduling logic (`_daemon_loop`, `_next_wake_at`, `_sleep_checking_stop`) is copied in shape from
`app.workflow.loop` and is not re-verified here beyond what `run_once`/`_run_once_safely` exercise --
this file's job is to prove the daemon's public contract (`start`/`stop`/idempotence) and its
resilience (`run_once` failures never propagate), always through `app.manager.service
.run_scheduled_brief` monkeypatched to a no-op, so a real brief is never produced.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from collections.abc import Callable

import pytest

from app.config import Settings
from app.manager import loop, service


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 5.0, interval: float = 0.02) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(interval)
    pytest.fail("timed out waiting for condition")


@pytest.fixture(autouse=True)
def _stop_any_daemon():
    """However a test leaves the module-level singleton, make sure the next test starts clean."""
    yield
    loop.stop(timeout=5.0)
    loop._thread = None
    loop._stop_event = None


# ---------------------------------------------------------------------------
# start() is a no-op when the autopilot flag is off
# ---------------------------------------------------------------------------


def test_start_is_a_noop_when_disabled(settings: Settings) -> None:
    """Default off: `start` returns None and spawns nothing. The suite must never run this daemon."""
    assert settings.manager_autopilot_enabled is False
    assert loop.start(settings) is None
    assert loop._thread is None
    assert loop._stop_event is None


# ---------------------------------------------------------------------------
# start() spawns a live thread and returns an Event when enabled
# ---------------------------------------------------------------------------


def test_start_spawns_a_thread_and_returns_an_event_when_enabled(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Enabled: `start` returns a `threading.Event` and a live daemon thread exists. `_daemon_loop`'s
    own wake time is pushed a day out by `_next_wake_at` the instant it computes `now_et`, so nothing
    beyond thread liveness is asserted here -- the stop event is set immediately after, in a
    `finally`, so no thread from this test outlives it and no real brief is ever produced."""
    cfg = settings.model_copy(update={"manager_autopilot_enabled": True})

    event = loop.start(cfg)
    try:
        assert event is not None
        assert isinstance(event, threading.Event)
        _wait_until(lambda: loop._thread is not None and loop._thread.is_alive())
        assert loop._thread.name == "manager-brief"

        # idempotent: a second call while running returns the same event, not a second thread
        first_thread = loop._thread
        again = loop.start(cfg)
        assert again is event
        assert loop._thread is first_thread
    finally:
        loop.stop()
        assert event.is_set()


# ---------------------------------------------------------------------------
# run_once calls app.manager.service.run_scheduled_brief exactly once
# ---------------------------------------------------------------------------


def test_run_once_calls_run_scheduled_brief(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Settings] = []
    monkeypatch.setattr(
        service, "run_scheduled_brief", lambda s: calls.append(s), raising=False
    )

    loop.run_once(settings, today=dt.date(2026, 9, 9))

    assert calls == [settings]


# ---------------------------------------------------------------------------
# A failing run_scheduled_brief does not propagate out of run_once / _run_once_safely
# ---------------------------------------------------------------------------


def test_run_once_swallows_a_raising_run_scheduled_brief(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(_settings: Settings) -> None:
        raise RuntimeError("simulated brief failure")

    monkeypatch.setattr(service, "run_scheduled_brief", boom, raising=False)

    # run_once itself is not guarded -- app.workflow.loop's own run_once is not either. The daemon's
    # resilience lives in _run_once_safely, exercised below.
    with pytest.raises(RuntimeError, match="simulated brief failure"):
        loop.run_once(settings, today=dt.date(2026, 9, 9))

    with caplog.at_level(logging.ERROR, logger="app.manager.loop"):
        result = loop._run_once_safely(settings, today=dt.date(2026, 9, 9))

    assert result is False
    assert any("run_once failed" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# stop() clears the module-level state
# ---------------------------------------------------------------------------


def test_stop_clears_state(settings: Settings) -> None:
    cfg = settings.model_copy(update={"manager_autopilot_enabled": True})

    event = loop.start(cfg)
    assert event is not None
    _wait_until(lambda: loop._thread is not None and loop._thread.is_alive())

    loop.stop()

    assert event.is_set()
    assert loop._thread is None
    assert loop._stop_event is None


def test_stop_is_a_noop_when_nothing_is_running(settings: Settings) -> None:
    assert loop._thread is None
    loop.stop()  # must not raise
    assert loop._thread is None
    assert loop._stop_event is None

"""An opt-in daemon that advances every persona's trader book forward one weekly decision as new
market sessions arrive (Phase 10).

The same in-process daemon-thread shape `app.personas.refresh_loop` uses -- a `threading.Thread(daemon
=True)` driven by a `threading.Event` that both paces the loop (`Event.wait(interval)`) and stops it
(`Event.set()`), never a detached subprocess.

**Off unless `Settings.persona_trader_enabled` is set, and for the same reason `refresh_loop` gates
itself.** Each sweep spends money on a schedule with nobody confirming any single run -- unlike the
top-up sweep (which only spends when a channel actually posted something new), a trader sweep asks the
model for a trading decision on every enabled persona, every interval. `start` is therefore a no-op
unless the flag is on -- called unconditionally from `lifespan`, deciding for itself, exactly as
`refresh_loop.start` does -- and the test suite never sets the flag, so it never spawns this daemon.

**Why this reuses `refresh_loop`'s cadence instead of a new setting.** The engine's own
`advance_one_decision` only ever advances the ONE next undone *weekly* decision, and returns cheaply
with a "already caught up" warning (no model call) when no new weekly session exists yet -- so sweeping
daily is mostly a no-op that costs nothing beyond a cheap calendar check, and there is no need for a
second interval setting duplicating `persona_refresh_interval_hours`.
"""

from __future__ import annotations

import logging
import threading

from app.config import Settings, get_settings

__all__ = ["start", "stop"]

logger = logging.getLogger(__name__)

_stop_event: threading.Event | None = None
_thread: threading.Thread | None = None


def start(settings: Settings | None = None) -> threading.Event | None:
    """Launch the trader daemon, or do nothing when `persona_trader_enabled` is off.

    Returns the `threading.Event` that stops the loop (for a caller that wants to join it), or `None`
    when the feature is disabled. Idempotent: a second call while a loop is already running returns
    the existing event rather than starting a second daemon.
    """
    global _stop_event, _thread

    cfg = settings or get_settings()
    if not cfg.persona_trader_enabled:
        return None
    if _thread is not None and _thread.is_alive():
        return _stop_event

    # No dedicated interval setting for the trader sweep -- see the module docstring for why reusing
    # the persona refresh cadence is fine here. A non-positive interval reaching `Event.wait` would
    # busy-loop rather than schedule -- floor it, the same guard `refresh_loop.start` documents.
    interval_hours = cfg.persona_refresh_interval_hours
    interval_seconds = max(interval_hours, 0.1) * 3600.0

    stop_event = threading.Event()

    def _run() -> None:
        # Sweep once on start, then every interval, until stopped. Each sweep is best-effort: one
        # persona's failure never stops the others or the loop -- see `_sweep`.
        while not stop_event.is_set():
            try:
                _sweep(cfg)
            except Exception:
                logger.exception("personas.trader_loop: sweep raised; continuing")
            stop_event.wait(interval_seconds)

    thread = threading.Thread(target=_run, daemon=True, name="personas-trader")
    _stop_event = stop_event
    _thread = thread
    thread.start()
    logger.info("personas.trader_loop: started, sweeping every %.1fh", interval_hours)
    return stop_event


def stop() -> None:
    """Signal the daemon to stop. Safe to call when nothing is running."""
    global _stop_event, _thread
    if _stop_event is not None:
        _stop_event.set()
    _thread = None
    _stop_event = None


def _sweep(settings: Settings) -> None:
    """One pass: advance every persona's trader book by at most one weekly decision.

    Imported inside the function for the same reason `refresh_loop._sweep` imports its dependencies
    lazily: an environment that cannot reach the model should lose the daemon, not fail to import the
    app. `PersonaError` (no notes yet, no methodology, "already caught up") is the ordinary steady
    state for most sweeps and is logged quietly; `SpendCapExceeded` means the daily cap is already
    spent and this persona is simply skipped this sweep, not retried in a hot loop.
    """
    from app.agents.spend import SpendCapExceeded
    from app.personas import service, trader_service
    from app.personas.service import PersonaError

    for persona in service.list_personas(settings):
        try:
            trader_service.decide_now(settings, persona.slug)
        except PersonaError as exc:
            logger.debug("personas.trader_loop: %s decision not advanced: %s", persona.slug, exc)
        except SpendCapExceeded as exc:
            logger.info("personas.trader_loop: %s skipped this sweep: %s", persona.slug, exc)
        except Exception:
            logger.exception("personas.trader_loop: %s decision raised", persona.slug)

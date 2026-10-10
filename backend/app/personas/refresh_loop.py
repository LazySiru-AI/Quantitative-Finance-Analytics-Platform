"""A daily daemon that tops up every persona's notes from its YouTube sources.

The same in-process daemon-thread shape `app.market.social_history.start_scheduler` and
`app.workflow.loop` use -- a `threading.Thread(daemon=True)` driven by a `threading.Event` that both
paces the loop (`Event.wait(interval)`) and stops it (`Event.set()`), never a detached subprocess (the
`strategy-program/DEFECTS.md` D3 precedent those modules cite).

**Off unless `Settings.persona_refresh_enabled` is set, and that gate is stronger here than for a
read-only sweep.** Each top-up ingests every persona's not-yet-seen videos *through the model*, so an
enabled loop spends money on a schedule with nobody confirming any single run. `start` is therefore a
no-op unless the flag is on -- called unconditionally from `lifespan`, deciding for itself, exactly as
`app.workflow.loop.start` does -- and the test suite never sets the flag, so it never spawns this.

**Why it reuses `service.start_ingest` rather than its own fetch loop.** A top-up is exactly a
default backfill: `start_ingest(slug, limit=...)` lists each source, skips videos already on disk via
`has_note`, and summarises only the new ones under the per-job budget cap. So the daemon does not
duplicate any ingest logic; it just calls the same entry point a manual refresh would, once per
persona per sweep, and lets the job registry's one-active-per-slug rule serialise against any manual
ingest already running (an `IngestAlreadyActive` for a persona mid-manual-ingest is caught and that
persona is simply skipped this sweep).
"""

from __future__ import annotations

import logging
import threading

from app.config import Settings, get_settings

__all__ = ["start", "stop"]

logger = logging.getLogger(__name__)

#: How many videos each per-persona top-up asks for. The same 20 the owner's manual backfill uses;
#: `has_note` means only genuinely-new videos are fetched and summarised, so on a channel that has not
#: posted since the last sweep this costs one cheap listing call and no model spend.
_TOP_UP_LIMIT = 20

_stop_event: threading.Event | None = None
_thread: threading.Thread | None = None


def start(settings: Settings | None = None) -> threading.Event | None:
    """Launch the top-up daemon, or do nothing when `persona_refresh_enabled` is off.

    Returns the `threading.Event` that stops the loop (for a caller that wants to join it), or `None`
    when the feature is disabled. Idempotent: a second call while a loop is already running returns
    the existing event rather than starting a second daemon.
    """
    global _stop_event, _thread

    cfg = settings or get_settings()
    if not cfg.persona_refresh_enabled:
        return None
    if _thread is not None and _thread.is_alive():
        return _stop_event

    interval_hours = cfg.persona_refresh_interval_hours
    # A non-positive interval reaching `Event.wait` would busy-loop rather than schedule -- floor it,
    # the same guard `social_history.start_scheduler` documents.
    interval_seconds = max(interval_hours, 0.1) * 3600.0

    stop_event = threading.Event()

    def _run() -> None:
        # Sweep once on start, then every interval, until stopped. Each sweep is best-effort: one
        # persona's failure is logged and never stops the others or the loop.
        while not stop_event.is_set():
            try:
                _sweep(cfg)
            except Exception:
                logger.exception("personas.refresh_loop: sweep raised; continuing")
            stop_event.wait(interval_seconds)

    thread = threading.Thread(target=_run, daemon=True, name="personas-refresh")
    _stop_event = stop_event
    _thread = thread
    thread.start()
    logger.info(
        "personas.refresh_loop: started, sweeping every %.1fh", interval_hours
    )
    return stop_event


def stop() -> None:
    """Signal the daemon to stop. Safe to call when nothing is running."""
    global _stop_event, _thread
    if _stop_event is not None:
        _stop_event.set()
    _thread = None
    _stop_event = None


def _sweep(settings: Settings) -> None:
    """One pass: top up every persona from its sources. Imported inside the function for the same
    reason `app.personas.service` imports its ingest dependencies lazily -- an environment missing
    `yt-dlp` should lose the daemon, not fail to import the app."""
    from app.personas import service
    from app.personas.jobs import IngestAlreadyActive

    for persona in service.list_personas(settings):
        try:
            service.start_ingest(
                settings, persona.slug, limit=_TOP_UP_LIMIT, video_urls=None, drop=None
            )
        except IngestAlreadyActive:
            logger.info("personas.refresh_loop: %s already ingesting; skipping", persona.slug)
        except service.PersonaError as exc:
            # "nothing to ingest" (everything already on disk) is the ordinary steady state, not an
            # error worth shouting about; log it quietly and move on.
            logger.debug("personas.refresh_loop: %s not topped up: %s", persona.slug, exc)
        except Exception:
            logger.exception("personas.refresh_loop: %s top-up raised", persona.slug)

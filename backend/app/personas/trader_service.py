"""Thin service layer for the persona paper trader (Phase 10) -- the one module `app.api.personas`'s
trader routes call into.

Mirrors the shape `app.personas.service` already established for every other persona feature: this
module resolves a persona, loads whatever the engine (`app.personas.trader`, built and proven, not
touched here) needs, calls the engine function, and translates the engine's own exceptions
(`BudgetExhausted`, `AgentUnavailable`) into `app.personas.service.PersonaError`s the router can map to
a status code. All the actual trading logic -- the model call, the broker, the point-in-time market
snapshot -- lives in the engine; nothing here re-implements any of it.

**Why backfill gets its own tiny job registry rather than reusing `app.personas.jobs.IngestRegistry`.**
An ingest job's shape (`items_total`/`items_done`/`items_failed`, a `cancel_event` a worker polls
between items) does not fit a trader backfill: there is no natural "item count" to plan up front (the
engine walks weekly sessions until it runs out of calendar or budget), and the contract's `TraderJob`
carries a different field set (`decided_count`, no cancellation). Rather than force one shape to serve
two different job kinds, this module keeps its own registry, copying `IngestRegistry`'s locking
discipline verbatim: one active (`queued`/`running`) job per persona slug, a daemon thread, and a
bounded in-memory history so a long-lived process cannot accumulate job records without limit. Like
`IngestRegistry`, **a server restart forgets in-flight and completed backfill job records, but never
loses a decision the engine already wrote into the trader book** -- the book on disk is the durable
output, the job record is only a progress receipt for the caller who started it.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import uuid
from collections import deque
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.config import Settings
from app.personas import trader
from app.personas.profile_store import ProfileStore
from app.personas.service import PersonaError
from app.personas.store import VaultStore

__all__ = [
    "TraderJob",
    "TraderJobState",
    "decide_now",
    "delete_trader_book",
    "get_backfill_job",
    "get_trader_book",
    "list_trader_books",
    "start_backfill",
]

logger = logging.getLogger(__name__)

#: Same cap `app.personas.jobs._HISTORY_MAXLEN` uses, for the same reason: a long-lived process must
#: not accumulate backfill job records without limit. An evicted job's *book* is still on disk; only
#: the ability to poll that particular `job_id` goes away.
_HISTORY_MAXLEN = 200

TraderJobState = Literal["queued", "running", "succeeded", "failed"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class TraderJob(_Frozen):
    """Progress of one trader backfill run (`docs/INFLUENCER-CONTRACT.md`, Phase 10). `spent_usd` is a
    decimal string, the house money rule. `error` is populated only when `state == "failed"`."""

    job_id: str
    persona: str
    state: TraderJobState
    decided_count: int = 0
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    spent_usd: str = "0"
    error: str | None = None


def _store(settings: Settings) -> VaultStore:
    return VaultStore(settings)


def _profiles(settings: Settings) -> ProfileStore:
    return ProfileStore(settings)


def _tstore(settings: Settings) -> trader.TraderStore:
    return trader.TraderStore(settings)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _decimal(value: object, *, fallback: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        logger.warning("trader_service: %r is not a decimal; falling back to %s", value, fallback)
        return Decimal(fallback)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def list_trader_books(settings: Settings) -> list[trader.TraderBook]:
    """One trader book per persona, for the Paper Desk. Always answers -- a persona that has never
    traded gets the empty book `build_trader_book` returns for a `None` blob, never an exception."""
    store = _store(settings)
    tstore = _tstore(settings)
    books: list[trader.TraderBook] = []
    for persona in store.list_personas():
        try:
            blob = tstore.load(persona.slug)
        except Exception:
            logger.warning("trader_service: could not read trader book for %s", persona.slug, exc_info=True)
            blob = None
        books.append(trader.build_trader_book(persona=persona, blob=blob, settings=settings))
    return books


def get_trader_book(settings: Settings, slug: str) -> trader.TraderBook:
    """One persona's trader book. 404 for an unknown persona; a known persona that has never traded
    gets the empty book, not an error."""
    persona = _store(settings).load_persona(slug)
    if persona is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)
    blob = _tstore(settings).load(slug)
    return trader.build_trader_book(persona=persona, blob=blob, settings=settings)


def delete_trader_book(settings: Settings, slug: str) -> None:
    """Reset a persona's trader book (delete the stored blob). 404 for an unknown persona; deleting an
    already-empty book is a no-op, not an error -- mirrors `service.delete_persona`'s idempotence."""
    if _store(settings).load_persona(slug) is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)
    _tstore(settings).delete(slug)


# ---------------------------------------------------------------------------
# One decision, synchronous
# ---------------------------------------------------------------------------


def decide_now(settings: Settings, slug: str) -> trader.TraderBook:
    """Run the persona's next undone weekly decision right now and persist the result. 404 unknown
    persona; 409 when the model call hits its per-decision budget cap; 503 when the model is
    unavailable.

    Also lets `app.agents.spend.SpendCapExceeded` propagate uncaught -- `advance_one_decision` itself
    calls `LEDGER.check(daily_cap_usd)` before the model call, and the process-wide
    `app.agents.spend_http` handler maps that to `429`, exactly as every other persona model route
    documents (see `app.personas.service.ask`'s docstring for why).
    """
    from app.agents.models import AgentUnavailable, BudgetExhausted

    store = _store(settings)
    persona = store.load_persona(slug)
    if persona is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)

    profile = _profiles(settings).load_profile(slug)
    notes = tuple(store.list_notes(slug))
    tstore = _tstore(settings)
    blob = tstore.load(slug)

    cap = _decimal(settings.persona_trader_decision_cap_usd, fallback="1")
    daily_cap = _decimal(settings.model_spend_daily_cap_usd, fallback="25")

    try:
        book, new_blob = trader.advance_one_decision(
            persona=persona,
            profile=profile,
            notes=notes,
            blob=blob,
            settings=settings,
            model=settings.persona_trader_model,
            per_decision_cap_usd=cap,
            daily_cap_usd=daily_cap,
        )
    except BudgetExhausted as exc:
        raise PersonaError(
            f"decision reached the ${exc.cap_usd} budget cap", status_code=409
        ) from exc
    except AgentUnavailable as exc:
        raise PersonaError(f"model unavailable: {exc}", status_code=503) from exc

    tstore.save(slug, new_blob)
    return book


# ---------------------------------------------------------------------------
# Backfill: async job registry (mirrors app.personas.jobs' locking discipline)
# ---------------------------------------------------------------------------


class _Slot:
    """One backfill's bookkeeping: its current record and its thread. `job` is replaced wholesale
    rather than mutated, because `TraderJob` is frozen -- a poller reading it under the lock therefore
    always sees one coherent snapshot, never a half-updated one. Mirrors `app.personas.jobs._Slot`."""

    __slots__ = ("job", "thread")

    def __init__(self, job: TraderJob) -> None:
        self.job = job
        self.thread: threading.Thread | None = None


_lock = threading.Lock()
_active: dict[str, _Slot] = {}
_history: deque[_Slot] = deque(maxlen=_HISTORY_MAXLEN)
_by_job_id: dict[str, _Slot] = {}


def _update_job(job_id: str, **changes: object) -> None:
    with _lock:
        slot = _by_job_id.get(job_id)
        if slot is None:
            return
        slot.job = slot.job.model_copy(update=changes)


def start_backfill(settings: Settings, slug: str, *, inception: dt.date | None) -> TraderJob:
    """Queue a weekly backfill for `slug` from `inception` (default `trader.DEFAULT_INCEPTION`) and
    launch it on a daemon thread. Returns the job's initial `queued` record immediately -- the route
    answers `202 Accepted` with it while the work proceeds.

    404 unknown persona. 409 if a backfill for this persona is already `queued`/`running`, checked and
    inserted atomically under the same lock the finishing job releases under, so a finishing job and a
    starting one cannot race into an inconsistent slot (same rule `IngestRegistry.start` documents).
    """
    store = _store(settings)
    persona = store.load_persona(slug)
    if persona is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)

    with _lock:
        existing = _active.get(slug)
        if existing is not None:
            raise PersonaError(
                f"a trader backfill is already running for {slug!r}: {existing.job.job_id}",
                status_code=409,
            )

        job_id = uuid.uuid4().hex[:16]
        slot = _Slot(TraderJob(job_id=job_id, persona=slug, state="queued", started_at=_now()))
        _active[slug] = slot
        if len(_by_job_id) >= _HISTORY_MAXLEN and _history:
            evicted = _history.popleft()
            _by_job_id.pop(evicted.job.job_id, None)
        _history.append(slot)
        _by_job_id[job_id] = slot

    effective_inception = inception or trader.DEFAULT_INCEPTION
    profile = _profiles(settings).load_profile(slug)
    notes = tuple(store.list_notes(slug))
    per_decision_cap = _decimal(settings.persona_trader_decision_cap_usd, fallback="1")
    backfill_cap = _decimal(settings.persona_trader_backfill_cap_usd, fallback="15")

    def _run() -> None:
        _update_job(job_id, state="running")
        try:
            book, blob = trader.backfill_trader(
                persona=persona,
                profile=profile,
                notes=notes,
                inception=effective_inception,
                settings=settings,
                model=settings.persona_trader_model,
                per_decision_cap_usd=per_decision_cap,
                daily_cap_usd=backfill_cap,
            )
        except Exception as exc:  # deliberately broad; see IngestRegistry.start's own docstring
            logger.exception("personas: trader backfill %s for %s raised out of its thread", job_id, slug)
            _update_job(job_id, state="failed", error=f"{type(exc).__name__}: {exc}", finished_at=_now())
        else:
            _tstore(settings).save(slug, blob)
            _update_job(
                job_id,
                state="succeeded",
                decided_count=len(book.decisions),
                spent_usd=book.spent_usd,
                finished_at=_now(),
            )
        finally:
            with _lock:
                if _active.get(slug) is slot:
                    del _active[slug]

    thread = threading.Thread(target=_run, daemon=True, name=f"personas-trader-backfill-{slug}-{job_id}")
    slot.thread = thread
    thread.start()
    return slot.job


def get_backfill_job(settings: Settings, slug: str, job_id: str) -> TraderJob:
    """The current record for `job_id`. 404 when this process never saw it (including after a
    restart, or once evicted from history), or when it belongs to a different persona."""
    with _lock:
        slot = _by_job_id.get(job_id)
    if slot is None or slot.job.persona != slug:
        raise PersonaError(
            f"no trader backfill job {job_id!r} for persona {slug!r}", status_code=404
        )
    return slot.job

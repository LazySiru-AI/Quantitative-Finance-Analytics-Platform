"""The Data page's endpoints: start a market-data sweep on demand, report what is stale, and report
how much this instance has accumulated in each of its stores.

**Why a router of its own rather than an addition to `app.api.health`.** `/api/health/*` answers
"is this deployment structurally sound" -- what stores exist, which providers are registered -- and
deliberately does no I/O and takes no action. These two do the opposite of both: one *starts* a
background sweep, the other reads every store and cache on disk. Mixing a write endpoint into the
liveness router would also mean a health check and a refresh button sharing a tag in the OpenAPI
schema, which is not how anyone reads that page.

**`GET /api/market/refresh/status` deliberately stays in `app.main`.** It was already there, the
frontend already polls it there, and moving it would break that poll for no gain -- so the sweep now
has its start here and its progress there. Both read the same `app.market.refresh` module-level
record, so they cannot disagree; the freshness report below also embeds that same record verbatim
under `refresh`, so a caller that only wants one round trip can have one.

**Serialisation only.** Every decision about what a source is, how its age is measured and what
counts as stale lives in `app.market.freshness`; nothing here interprets it. That is what lets the
freshness catalog be tested without a client at all.

**`GET /data/retention` is not behind an owner-only prefix, on purpose** (see `app.auth.gate`'s own
list) -- it backs the Data > About panel, which every signed-in user can open. That is exactly why
it returns *only* counts, generic store names and dates: never an absolute path, never a username or
account label. `app.api.health.stores` is the sibling endpoint that enumerates ledger/bars stores the
same way, but it is owner-only and does embed real paths -- this endpoint deliberately does not reuse
its shape for that reason. Every count below is read straight from the store a feature already owns
(`app.manager.*`, `app.personas.*`, `app.agentdesk.models.runs_dir`, `app.paperdesk.desk.seats`) --
nothing here recomputes or re-derives what those modules already know how to report.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, status

from app.agentdesk.models import DeskKind, runs_dir
from app.auth import store as auth_store
from app.config import Settings, get_settings
from app.datasource import ledger_db_path
from app.db import sqlite as ledger_db
from app.manager import models as manager_models
from app.manager import service as manager_service
from app.market import calendar as market_calendar
from app.market import freshness, refresh
from app.paperdesk import desk as paperdesk_desk
from app.personas import service as personas_service

router = APIRouter(prefix="/api", tags=["data-admin"])

#: The four desk kinds `app.agentdesk.models.DeskKind` admits -- see that module's docstring. Spelled
#: out rather than iterated from the `Literal`'s `__args__` so a reader (and `typing`) can see the
#: exact set this endpoint reports on without reflection.
_DESK_KINDS: tuple[DeskKind, ...] = ("tradingagents", "vibedesk", "workflow", "manager")

#: `DELETE` routes that already exist elsewhere in the app and actually remove something a store
#: below counts. Listed here, rather than invented as a new purge control, so the About panel can
#: link a reader to a real delete rather than implying one that does not exist. Kept as bare
#: `METHOD path` strings -- generic route shapes, never an instantiated id -- matching this endpoint's
#: no-real-identifiers contract.
_PURGE_ENDPOINTS: tuple[str, ...] = (
    "DELETE /api/manager/chats/{thread_id}",
    "DELETE /api/personas/{slug}",
    "DELETE /api/personas/{slug}/sources/{source_id}",
    "DELETE /api/personas/{slug}/chats/{thread_id}",
    "DELETE /api/personas/{slug}/trader",
)


@router.post("/market/refresh", status_code=status.HTTP_202_ACCEPTED)
def start_market_refresh() -> dict[str, Any]:
    """Start one market-data sweep in the background and return immediately.

    **202 with `started: false` rather than 409 when a sweep is already running.** A second press of
    the Fetch button while the first sweep is still going is not a client error -- the caller asked
    for fresh data and fresh data is already on its way. A 409 would make the frontend render a
    failure for a request that got exactly what it wanted, so the outcome is reported in the body
    (`started`, `reason`) and the status line stays 202 in both cases. `reason` is `null` on a start
    and `"already_running"` otherwise; a caller that only cares whether the sweep is live can ignore
    both and read the embedded `status` instead.

    The sweep itself is `app.market.refresh.refresh_market_data` -- the same call `app.main.lifespan`
    makes on startup, on the same daemon thread with the same non-blocking double-start guard, so
    pressing this button can never run two sweeps against one on-disk store.
    """
    settings = get_settings()
    started = refresh.refresh_market_data(settings)
    if started:
        # The sweep itself never touches the event calendar (see `app.market.refresh._sweep`);
        # `app.main.lifespan` warms it as a separate daemon call right after starting the sweep,
        # and the button mirrors that pairing so "Fetch data" covers every day-frame source the
        # Overview page reads. `warm` returns immediately and swallows its own failures; its
        # one-hour `CachingTransport` TTL means a press inside that hour is a cache read, not a
        # second FOMC/Nasdaq sweep.
        market_calendar.warm(settings)
    return {
        "started": started,
        "reason": None if started else "already_running",
        # The record as it stands the instant the sweep was asked for. Deliberately included rather
        # than making the caller immediately poll `/api/market/refresh/status`: the useful thing to
        # render right after pressing the button is what the sweep is doing, and the round trip to
        # find out is one this response can save.
        "status": refresh.status(),
    }


@router.get("/data/freshness")
def data_freshness() -> dict[str, Any]:
    """Per-source freshness for every market-data source the application reads.

    Does no network I/O of any kind -- see `app.market.freshness`'s module docstring for why that is
    a hard requirement of this endpoint and not merely an optimisation, and for why four of the
    eleven sources honestly report `status: "unknown"` instead of a number nobody can attribute.
    """
    return freshness.report(get_settings())


def _ledger_report(settings: Settings) -> dict[str, Any]:
    ledger_file = ledger_db_path(settings)
    exists = ledger_file.exists()
    transactions = 0
    if exists:
        with ledger_db.connect(ledger_file, read_only=True) as conn:
            _fingerprint, transactions = ledger_db.ledger_fingerprint(conn)
    return {"exists": exists, "transactions": transactions}


def _auth_report(settings: Settings) -> dict[str, Any]:
    # `auth_store.list_users` opens (and, via `sqlite3.connect`, would create) the auth database --
    # checked with `.exists()` first so a fresh instance that has never called `add-user` is reported
    # as zero users without this read-only endpoint creating a file as a side effect.
    if not settings.auth_db_path.exists():
        return {"users": 0}
    return {"users": len(auth_store.list_users(settings))}


def _manager_briefs_report(settings: Settings) -> dict[str, Any]:
    # No listing helper exists for briefs (only `get_brief`/`latest_brief`, one id at a time) -- see
    # `app.manager.pipeline`'s own "Brief persistence" section, which this mirrors read-only rather
    # than importing its private `_briefs_dir`: the directory is `manager_dir(settings) / "briefs"`
    # by that module's own docstring, composed here from the public `manager_dir`.
    directory = manager_models.manager_dir(settings) / "briefs"
    generated: list[str] = []
    if directory.is_dir():
        for entry in sorted(directory.iterdir()):
            if not entry.is_file() or not entry.name.endswith(".json"):
                continue
            try:
                payload = json.loads(entry.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            when = payload.get("generated_at")
            if isinstance(when, str) and when:
                generated.append(when)
    return {
        "count": len(generated),
        "oldest": min(generated) if generated else None,
        "newest": max(generated) if generated else None,
    }


def _persona_notes_and_chats(settings: Settings) -> tuple[int, int]:
    """`(vault note count, chat thread count)` across every persona, one pass over the roster."""
    personas = personas_service.list_personas(settings)
    notes = 0
    chats = 0
    for persona in personas:
        notes += len(personas_service.list_notes(settings, persona.slug))
        chats += len(personas_service.list_chats(settings, persona.slug))
    return notes, chats


#: `RunStore` keeps this filename private (`app.agentdesk.store._RUN_FILE`) since no caller outside
#: that module has needed the literal before; a run directory counts here only if it holds one, the
#: same test `RunStore.list_runs`/`.load` apply, so a leftover empty directory is not miscounted as
#: a run.
_RUN_FILE = "run.json"


def _desk_run_counts(settings: Settings) -> dict[str, int]:
    counts: dict[str, int] = {}
    for kind in _DESK_KINDS:
        directory = runs_dir(settings, kind)
        if not directory.is_dir():
            counts[kind] = 0
            continue
        counts[kind] = sum(1 for entry in directory.iterdir() if (entry / _RUN_FILE).is_file())
    return counts


@router.get("/data/retention")
def data_retention() -> dict[str, Any]:
    """How much this instance has accumulated in each store it keeps, for the Data > About panel.

    **Not owner-only, deliberately** -- see this module's docstring. That is the hard constraint on
    every value below: a count, a generic store name, or an ISO date, never an absolute filesystem
    path and never anything that names an account. Nothing here does network I/O; every figure is a
    local read (or, for `manager_briefs`, a handful of local reads) through a store this feature
    already owns.

    `retention_policy` is `"manual"` everywhere in this application today: nothing purges on a
    schedule. `purge_endpoints` lists the real `DELETE` routes that already exist so the panel can
    link a reader to an actual control instead of inventing a purge button this endpoint cannot back.
    """
    settings = get_settings()

    persona_notes, persona_chats = _persona_notes_and_chats(settings)

    return {
        "ledger": _ledger_report(settings),
        "auth": _auth_report(settings),
        "manager_briefs": _manager_briefs_report(settings),
        "manager_chats": {"count": len(manager_service.list_chats(settings))},
        "persona_chats": {"count": persona_chats},
        "persona_vault_notes": {"count": persona_notes},
        "desk_runs": _desk_run_counts(settings),
        "paperdesk_books": {"count": len(paperdesk_desk.seats(settings))},
        "i18n_cache": {"present": (settings.data_dir / "i18n_cache").is_dir()},
        "retention_policy": "manual",
        "purge_endpoints": list(_PURGE_ENDPOINTS),
    }

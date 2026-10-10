"""FastAPI application entry point.

Run locally from the **repository root**, not from ``backend/``::

    .venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000 --app-dir .

The root, rather than ``backend/``, because this application no longer imports only from its own
package. ``app.tournament.runner`` -- reached from ``/api/paperdesk`` and ``/api/competition/jobs``
-- imports ``uat.harness.marketdata`` and ``uat.harness.paperbroker``, which live outside
``backend/``. ``--app-dir backend`` puts only ``backend/`` on the path and the server dies at import
with ``ModuleNotFoundError: No module named 'uat'``; ``--app-dir .`` puts the repository root there,
and ``app`` itself resolves through its editable install. This mirrors what ``pytest.ini`` already
does for the same reason (``pythonpath = . backend``), which is exactly why the test suite stayed
green while the server could not start -- the suite runs with both roots on the path and cannot see
the difference.

That the served application reaches into ``uat/`` at all is a layering inversion, recorded with the
``COPY`` lines in ``backend/Dockerfile`` along with the trees it forces the image to ship.
``tests/test_deployment_paths.py`` pins the image against it.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.agentdesk import live_loop as agentdesk_live_loop
from app.agents.spend import SpendCapExceeded
from app.agents.spend_http import spend_cap_exceeded_handler
from app.api import (
    agents,
    auth,
    backfill,
    backtest,
    calendar,
    competition,
    competition_findings,
    competition_jobs,
    competition_narrative,
    competition_selection,
    data_admin,
    designer,
    evolution,
    evolution_dossier,
    evolution_journal,
    health,
    i18n,
    imports,
    institutions,
    institutions_consensus,
    live_decisions,
    macro,
    manager,
    market,
    news,
    paperdesk,
    paperlive,
    personas,
    portfolio,
    report,
    rules,
    tax,
    telemetry_nav,
    thesis,
    timeframes,
    tradingagents,
    transactions,
    users,
    vibedesk,
    workflow,
)
from app.auth import store as auth_store
from app.auth.gate import AuthGateMiddleware
from app.auth.headers import SecurityHeadersMiddleware
from app.config import get_settings
from app.datasource import DataServiceError, ledger_writer, validate_settings
from app.db import sqlite
from app.manager import loop as manager_loop
from app.market import calendar as market_calendar
from app.market import livefeed, social_history
from app.market import refresh as market_refresh
from app.notify import api as notify_api
from app.paperdesk import desk as paperdesk_desk
from app.personas import refresh_loop as personas_refresh
from app.personas import trader_loop as personas_trader_loop
from app.workflow import loop as workflow_loop

#: Vite dev server. The API binds to localhost only and holds no credentials, but the origin list
#: stays explicit rather than "*" so a page on another site cannot read the user's positions.
DEV_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create the store directories and apply the ledger schema before serving."""
    settings = get_settings()
    if not settings.auth_enabled:
        # Said once, loudly, at the one moment an operator is watching the console: every route on
        # this server -- the real ledger, tax forms, the lot -- is reachable with no session at all.
        # `Settings.auth_enabled` is meant for loopback-only local dev (see its own docstring); this
        # is the warning that catches the deployment where someone forgot to turn it back on before
        # binding to anything wider than loopback.
        logger.warning(
            "INVDASH_AUTH_ENABLED=0: every route on this server is open with no login required. "
            "This process must stay bound to loopback (127.0.0.1) only -- never expose it on a LAN "
            "or the internet while auth is disabled."
        )
    settings.ensure_dirs()
    if settings.data_source == "remote":
        # The data service owns the ledger and its schema; there is nothing local to migrate. Fail
        # now on a configuration that could never work rather than on the first request.
        validate_settings(settings)
    else:
        with ledger_writer(settings) as ledger_file, sqlite.connect(ledger_file) as conn:
            sqlite.migrate(conn)
    # Create the auth users/sessions database if absent. Separate file from the ledger (see
    # `Settings.auth_db_path`), so this never touches the ledger's schema version. Cheap and
    # idempotent -- `CREATE TABLE IF NOT EXISTS` -- so it runs unconditionally, even when
    # `auth_enabled` is off, because a deployment that later flips auth on must already have the
    # tables. Also prune any sessions that expired while the server was down.
    auth_store.init_db(settings)
    auth_store.delete_expired_sessions(settings)
    # Compute the paper desk off the request path. Running the roster cold costs seconds per card
    # -- the profile puts nearly all of it in the rule engine recomputing every indicator over a
    # symbol's whole history once per session -- and without this the first person to open
    # `/paper-desk` after a restart waits for it. `warm` returns immediately: it runs on a daemon
    # thread and swallows its own failures, so a slow or broken desk delays nothing here and the
    # endpoint still computes on demand exactly as it did before.
    paperdesk_desk.warm(settings)
    # Same shape as `paperdesk_desk.warm` above: a daemon thread that returns immediately and
    # swallows its own failures, so a slow or broken sweep delays nothing here. See
    # `app.market.refresh`'s module docstring for what it actually does (priority order, staleness
    # gate, pacing, wall-time cap) and `Settings.refresh_on_startup` for why this is gated -- on by
    # default, so a plain server start does sweep. The test suite escapes it by opting out, not by
    # inheriting the default: `tests/conftest.py`'s `settings` fixture sets
    # `INVDASH_REFRESH_ON_STARTUP=0` alongside its other `INVDASH_*` redirections.
    # Start a local server the same way on a memory-constrained host --
    # `INVDASH_REFRESH_ON_STARTUP=0 uvicorn app.main:app ...`. The sweep walks every held
    # instrument, and on a 16GB box that exhausted RAM part-way through (`MemoryError`, DuckDB
    # `Out of Memory Error: Allocation failure`) and left every endpoint hanging past a 300s client
    # timeout -- which reads like an infinite loop in whichever endpoint you happen to be testing,
    # not like a background thread eating the machine.
    if settings.refresh_on_startup:
        market_refresh.refresh_market_data(settings)
        # Prime the Overview page's remaining from-source card the same way. The sweep above warms
        # the bar store and the macro snapshot (two of the five fetches the Overview page fires --
        # see `frontend/src/pages/Overview.tsx`); the paper desk is warmed by `paperdesk_desk.warm`
        # above; and the portfolio report and wash-sale tracker are pure ledger replays with nothing
        # cached to prime. That leaves the event calendar -- FOMC/Nasdaq/FRED over the network, with
        # its own on-disk cache -- as the last Overview source that still pays a cold cost on first
        # open. `calendar.warm` primes it on a daemon thread, same shape and same gate as the two
        # warms already here, so a plain server start leaves every Overview card warm.
        market_calendar.warm(settings)
    # Phase D-social's clock: a recurring daemon thread that appends one social-sentiment snapshot
    # per watched symbol every `Settings.social_snapshot_interval_hours`, distinct from the one-shot
    # social pass `market_refresh.refresh_market_data` already runs above on every restart. See
    # `app.market.social_history.start_scheduler` for the loop itself and `Settings.
    # social_snapshot_scheduler_enabled` for why -- unlike `refresh_on_startup` -- it defaults to
    # `False`: gated here, at the call site, the same shape `refresh_on_startup` uses just above, so
    # `start_scheduler` itself has no opinion about whether it should run.
    if settings.social_snapshot_scheduler_enabled:
        social_history.start_scheduler(settings)
    # The Agent Workflow autopilot: a once-a-day in-process daemon that executes each arm's staged
    # orders at the open and resolves matured candidate observations. `start` is a no-op unless
    # `Settings.workflow_autopilot` is set, so -- like `paperdesk_desk.warm` -- it is called
    # unconditionally and decides for itself; the gate lives inside it, not here.
    workflow_loop.start(settings)
    # The persona top-up daemon: a daily in-process daemon that re-ingests each persona's new videos.
    # `start` is a no-op unless `Settings.persona_refresh_enabled` is set -- same unconditional-call,
    # gate-inside shape as `workflow_loop.start` above; the gate is stronger because a sweep spends
    # money through the model (see `app.personas.refresh_loop`).
    personas_refresh.start(settings)
    # The persona paper trader daemon: advances each persona's model-driven trader book forward one
    # weekly decision as new sessions arrive. `start` is a no-op unless `Settings.persona_trader_enabled`
    # is set -- same unconditional-call, gate-inside shape as `personas_refresh.start` just above, and
    # for the same reason: an enabled sweep spends money on a schedule with nobody confirming any single
    # run (see `app.personas.trader_loop`).
    personas_trader_loop.start(settings)
    # The live-quote keep-warm daemon: re-subscribes held symbols, macro movers and
    # `Settings.livefeed_watchlist` every `livefeed_keepalive_seconds` so the shared quote source
    # never evicts them. `start` is a no-op unless `Settings.livefeed_enabled` is set -- same
    # unconditional-call, gate-inside shape as `workflow_loop.start` above.
    livefeed.start(settings)
    # The live decisions daemon: grounded model opinions on a live tape during regular market hours.
    # `start` is a no-op unless `Settings.live_decisions_enabled` is set -- same unconditional-call,
    # gate-inside shape as `livefeed.start` just above, and gated for the stronger reason
    # `personas_trader_loop.start` is: it spends money on a timer with nobody confirming a call.
    agentdesk_live_loop.start(settings)
    # The manager brief daemon: one agent-curated cross-app brief a day near market open. A no-op
    # unless `Settings.manager_autopilot_enabled` is set -- same gate-inside shape, gated for the same
    # reason as the trader/live loops: it spends money on a timer with nobody confirming the calls,
    # and it must run in-process here (a detached scheduler crashes when a brief commissions a child).
    manager_loop.start(settings)
    yield
    manager_loop.stop()
    agentdesk_live_loop.stop()
    livefeed.stop()
    personas_trader_loop.stop()
    personas_refresh.stop()
    workflow_loop.stop()


app = FastAPI(
    title="Investing Dashboard",
    version="0.1.0",
    summary="Brokerage ledger, US tax engine, research reports and backtest workbench",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(DEV_ORIGINS),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# The login gate. Every request that is not on its small allowlist (the health check and the login
# routes themselves) needs a valid session cookie or gets a 401 -- see `app.auth.gate`. It reads
# `Settings.auth_enabled` per request, so it is a no-op when auth is off (the test suite, and
# single-user local dev) without being conditionally added here. It is raw ASGI rather than a
# `BaseHTTPMiddleware` specifically so the paperlive SSE stream still streams through it; that
# module's docstring has the detail. It ignores `OPTIONS`, so it never interferes with the CORS
# preflight the middleware above answers.
app.add_middleware(AuthGateMiddleware)

# Security response headers on every `/api/` response -- nosniff, DENY framing, no referrer, and
# `no-store` for the personal data behind the gate. See `app.auth.headers` for what each one is for
# and, more importantly, for why HSTS and CSP are deliberately *not* here (HSTS belongs on the TLS
# terminator that does not exist yet; CSP belongs on the nginx that serves the HTML). Added after
# `AuthGateMiddleware`, which in Starlette means it wraps *outside* it, so the gate's own 401/403
# denials carry the headers too. Raw ASGI like the gate, for the same SSE reason.
app.add_middleware(SecurityHeadersMiddleware)

# The rolling daily model-spend cap (`Settings.model_spend_daily_cap_usd`, see `app.agents.spend`).
# The translate route answers its own 429; the persona routes let `SpendCapExceeded` propagate out of
# `app.personas.service`, and this one handler turns it into the same `{"detail": "spend_cap", ...}`
# body so a caller sees one shape whichever surface tripped the cap.
app.add_exception_handler(SpendCapExceeded, spend_cap_exceeded_handler)


async def _data_service_unavailable(request: Request, exc: Exception) -> JSONResponse:
    """`DataServiceError` anywhere -> 503: the data service is unreachable or refused the request."""
    logger.warning("data service unavailable on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "data_service_unavailable", "message": str(exc)},
    )


app.add_exception_handler(DataServiceError, _data_service_unavailable)

app.include_router(backtest.router)
# `calendar` serves forward-looking dated events -- FOMC meetings and earnings dates for symbols the
# ledger says are held. It degrades rather than fails: an unreachable Fed page falls back to the
# snapshot committed under `data/calendar/`, and a failed earnings sweep still returns the macro
# events with a warning attached, so a flaky upstream costs the card a row, not the whole page.
app.include_router(calendar.router)
# The Data page's on-demand sweep trigger and per-source freshness report. `GET
# /api/market/refresh/status` stays below in this module; see `app.api.data_admin`'s docstring.
app.include_router(data_admin.router)
# `competition` serves the strategy program's library and past rounds; `competition_jobs` launches
# one. They are two routers rather than one because they have opposite risk profiles -- every route
# in the first is a pure read of committed JSON, while a POST to the second starts a backtest that
# can run for hours and holds a process-wide single slot. Keeping the launcher a separate module
# makes that boundary visible at the registration site rather than buried in a decorator.
app.include_router(competition.router)
app.include_router(competition_jobs.router)
# `competition_selection` derives a desk roster from a round's stored results. Read-only by design:
# it reports what the rule would seat and never writes `app.paperdesk.desk.AGENT_IDS`, so a human
# override of the rule stays a deliberate, recorded edit -- see that module's docstring.
app.include_router(competition_selection.router)
# `competition_findings` reads a round's own written record (REPORT.md/BRIEF.md/SELECTION.md,
# plus strategy-program/DEFECTS.md) as structured JSON -- see that module's docstring. Read-only,
# same as `competition_selection` above.
app.include_router(competition_findings.router)
# `competition_narrative` serves the prose companion to the two routers above: a round's
# hand-authored `NARRATIVE.json` (what it asked, how it turned out, what a person overrode), plus the
# briefing for the round that has not run yet. Read-only like its neighbours, and deliberately
# authored rather than parsed -- `SELECTION.md` headings are improvised per round, so an extractor
# over them would degrade into plausible prose rather than fail. See that module's docstring.
app.include_router(competition_narrative.router)
# `evolution` is the endless propose/run/score/promote supervisor's HTTP surface -- the button that
# starts/stops `app.evolution.loop` and polls its status, distinct from `competition_jobs` which
# launches a single manually-composed round.
app.include_router(evolution.router)
# `evolution_journal` serves the per-generation digests -- the plain-language record of what a
# generation changed, what it found, and what the next one will try. A separate router from
# `evolution` because it is a pure read of `DIGEST.md` files on disk and never consults the live
# `LoopStatus`, so it answers identically whether or not a loop is running in this process.
app.include_router(evolution_journal.router)
# `evolution_dossier` composes one candidate's full case -- what the strategy does in plain
# English, its lineage, its evidence paired with the field's own distribution, and the
# deterministic cautions against it. Separate from `evolution` because it is a read that joins
# the library, the ledger and the generation records, and because the seat queue must stay
# answerable even if this composition fails.
app.include_router(evolution_dossier.router)
# `agents` is the Claude-backed agent layer's own read-only health surface -- see that router's
# module docstring for why it never triggers a model call.
app.include_router(agents.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(health.router)
# `i18n` is Phase 4 of the i18n rollout: on-display Korean translation of model-written narrative
# prose, gated behind `Settings.translate_narratives` (default off). See `app.i18n.narrative`'s own
# module docstring for the flag gate, the number-preservation check and the persistent cache.
app.include_router(i18n.router)
app.include_router(imports.router)
app.include_router(institutions.router)
app.include_router(institutions_consensus.router)
app.include_router(macro.router)
app.include_router(market.router)
app.include_router(news.router)
app.include_router(paperdesk.router)
# `paperlive` serves live quote plumbing for symbols the paper desk holds, has signalled, or just
# traded -- a background poll (or, behind `Settings.paperlive_transport == "stream"`, a best-effort
# Yahoo WebSocket stream that falls back to polling on its own) shared across every caller, not one
# provider round trip per request. Data plumbing only: it does not touch order execution, which is a
# later shard's job. See `app.market.live`'s module docstring for the transport design.
app.include_router(paperlive.router)
app.include_router(portfolio.router)
app.include_router(designer.router)
app.include_router(transactions.router)
app.include_router(report.router)
app.include_router(rules.router)
app.include_router(tax.router)
app.include_router(thesis.router)
app.include_router(timeframes.router)
# `tradingagents` is the first Agent Desk surface: a fixed fourteen-stage analyst-to-portfolio-manager
# pipeline over one instrument. See `docs/AGENT-DESK-CONTRACT.md`'s "Trading Agents" section for the
# pinned wire shape both this and `vibedesk` share.
app.include_router(tradingagents.router)
# `vibedesk` is the second Agent Desk surface: preset-defined DAGs of role agents, distinct from
# `tradingagents`'s fixed analyst-to-portfolio-manager pipeline. See
# `docs/AGENT-DESK-CONTRACT.md`'s "Vibe Trading" section for the pinned wire shape both desks share.
app.include_router(vibedesk.router)
# `live_decisions` is the Agent Desk's live surface: an opt-in daemon's grounded buy/sell/hold
# opinions on a live tape, plus one on-demand decision. Decisions only -- nothing here trades. See
# `docs/AGENT-DESK-CONTRACT.md`'s "Live data" section.
app.include_router(live_decisions.router)
# `personas` is the influencer-persona surface: one memory-backed agent per followed influencer,
# ingesting YouTube transcripts (and manual drops) into an Obsidian-compatible markdown vault. See
# `docs/INFLUENCER-CONTRACT.md` for the pinned wire shape and vault note schema.
app.include_router(personas.router)
# `backfill` is the persona feature's manual, zero-model ingest surface: it discovers not-yet-ingested
# influencer videos as task packets the owner hands to an external agent, then ingests the pasted-back
# reply after re-imposing the ticker/number guardrails the in-house summariser gets for free. All logic
# lives in `app.personas.backfill` and `app.personas.backfill_ingest`; this router only shapes HTTP.
app.include_router(backfill.router)
# `workflow` is the third Agent Desk surface: an orchestrator that chains `tradingagents` and
# `vibedesk` runs, then stages and executes orders on a persistent per-arm paper book. See
# `docs/AGENT-DESK-CONTRACT.md`'s "Agent Workflow" section for the pinned wire shapes.
app.include_router(workflow.router)
# `manager` is the manager desk: an agent-curated second Overview with a daily brief, change
# detection and self-commissioned research. Phase 1 only -- config, changes, snapshot-now; no model
# calls behind any of these routes. See `docs/MANAGER-DESK-PLAN.md`. The whole prefix is owner-only
# (`app.auth.gate.OWNER_ONLY_PREFIXES`).
app.include_router(manager.router)
# `notify` is the notification core: an append-only event log every producer emits into, a
# policy-filtered sender (log or ntfy), and a read-only bearer for external pollers. Delivery is off
# by default (`Settings.notify_enabled`); the log fills regardless. See `docs/NOTIFY-RUNBOOK.md`.
app.include_router(notify_api.router)
# `telemetry_nav` is the local navigation hit log the SPA posts route changes to; `POST` is open to
# any signed-in user, the `/summary` read is owner-only via `OWNER_ONLY_PREFIXES`. No network.
app.include_router(telemetry_nav.router)


@app.get("/")
def root() -> dict[str, str]:
    return {"name": "investing-dashboard", "docs": "/docs", "health": "/api/health"}


@app.get("/api/market/refresh/status")
def market_refresh_status() -> dict[str, object]:
    """Progress of the background startup sweep started by `lifespan` -- see `app.market.refresh`'s
    module docstring for what each field means (queued/refreshed/skipped_fresh/failed, `complete`,
    `macro_snapshot`). Lives here rather than in `app.api.health` because that module is outside this
    change's scope; see `app.market.refresh.status` for the actual snapshot logic.

    Always answers, even when `Settings.refresh_on_startup` is off or no sweep has run yet in this
    process -- `running` is `False` and every counter is `0` in that case, not a 404, so a caller can
    poll this unconditionally without first checking whether the feature is enabled.
    """
    return market_refresh.status()

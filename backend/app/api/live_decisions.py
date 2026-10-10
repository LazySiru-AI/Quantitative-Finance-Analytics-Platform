"""HTTP surface for the live decisions loop -- status, the recorded decisions, and one on-demand
decision.

Thin on purpose, matching `app.api.tradingagents`'s own convention for the sibling desks: every real
decision (symbol validation, the spend gates, the grounding call, persistence) lives in
`app.agentdesk.live_loop`. This router wires three routes and translates that module's exceptions into
the status codes `docs/AGENT-DESK-CONTRACT.md` pins.

**No route here trades.** `POST /decide` produces an opinion and a JSONL line; there is no endpoint on
this router, or reachable from it, that places or stages an order.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from app.agentdesk import live_loop
from app.agents.models import AgentUnavailable, BudgetExhausted
from app.config import Settings, get_settings

router = APIRouter(prefix="/api/agentdesk/live", tags=["live-decisions"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


class DecisionsResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decisions: list[live_loop.LiveDecisionRecord]


class DecideRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str


class DecideResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: live_loop.LiveDecisionRecord


@router.get("/status")
def get_status() -> dict[str, Any]:
    """Whether the loop is enabled, running and healthy, and what it has done today.

    Always answers, including when the feature is switched off entirely -- the endpoint whose job is
    to report on a subsystem that may be deliberately disabled must not itself require that subsystem.
    Twelve pinned keys; see `app.agentdesk.live_loop.status`.
    """
    return live_loop.status()


@router.get("/decisions", response_model=DecisionsResponse)
def get_decisions(
    settings: SettingsDep,
    symbol: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> DecisionsResponse:
    """The most recent recorded decisions, newest first, optionally filtered to one symbol. Reads
    today's and yesterday's records only -- see `app.agentdesk.live_loop.list_decisions`."""
    return DecisionsResponse(
        decisions=live_loop.list_decisions(settings, symbol=symbol, limit=limit)
    )


@router.post("/decide", response_model=DecideResponse)
def post_decide(body: DecideRequest, settings: SettingsDep) -> DecideResponse:
    """Decide on one symbol right now, synchronously, and return the record.

    Synchronous rather than a job: this is a single model call of a few seconds, not the two desks'
    dozen-stage pipelines, and a job registry around one call would cost the caller a poll loop for
    nothing.

    `422` for an invalid symbol; `409` when the call hits its own per-decision budget cap; `503` when
    the agent layer has no usable credential. `app.agents.spend.SpendCapExceeded` (the rolling-24h
    aggregate ceiling) is deliberately *not* caught -- `app.main`'s own handler maps it to `429` with
    a `Retry-After`, exactly as every other model-spending route in this application relies on.
    """
    try:
        record = live_loop.decide(body.symbol, settings=settings, source="manual")
    except live_loop.InvalidSymbol as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BudgetExhausted as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return DecideResponse(decision=record)

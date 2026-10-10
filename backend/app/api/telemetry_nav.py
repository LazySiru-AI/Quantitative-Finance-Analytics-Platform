"""Navigation-telemetry endpoints: the SPA posts route changes here, and Data > Health reads the
rollup back.

``POST /api/telemetry/nav`` is reachable by any signed-in caller (the access gate, not this router,
enforces that a session exists at all -- see ``app.auth.gate``); ``GET /api/telemetry/nav/summary``
is meant to be owner-only, but that restriction is applied the same way every other owner-only
surface in this app is: by adding its exact path to ``app.auth.gate.OWNER_ONLY_PREFIXES``, not by a
dependency here. This router does not import ``app.auth.gate`` (nothing under ``app.api`` does --
the gate sits in front of all of it), so a member calling the summary route directly against *this*
router in isolation (as the tests below do) sees it succeed; wiring the prefix into the gate is a
one-line addition left to whoever registers this router on the app (``app.main``).
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.auth import sessions, store
from app.config import get_settings
from app.telemetry.nav import NavHit
from app.telemetry.nav import record as record_hits
from app.telemetry.nav import summary as summarize

router = APIRouter(prefix="/api/telemetry/nav", tags=["telemetry"])


class NavEventIn(BaseModel):
    """What the browser actually sends -- no ``role``. The caller cannot be trusted to report its
    own role, so it is resolved server-side from the session cookie and stamped onto every event in
    the batch (see ``_resolve_role`` below), the same way `/api/auth/me` resolves it for itself."""

    path: str
    tab: str | None = None
    ts: str


class RecordBody(BaseModel):
    events: list[NavEventIn]


class RecordResult(BaseModel):
    recorded: int


def _resolve_role(request: Request) -> str:
    """The caller's role for this request, never a username.

    Mirrors ``app.api.auth.me`` and ``app.auth.gate.AuthGateMiddleware`` -- both already read the
    session cookie this same way, so this is not a second source of truth about who the caller is,
    just the one already-cheap lookup (`sessions.validate`, a single session-store read) reused a
    third time. Falls back to ``"anon"`` for a request with no valid session; the gate normally
    would have already rejected such a request before this handler ever runs, but this router has
    no dependency on the gate having run (see the module docstring), so it degrades rather than
    assumes.
    """
    settings = get_settings()
    if not settings.auth_enabled:
        return store.ROLE_OWNER
    raw_token = request.cookies.get(sessions.COOKIE_NAME, "")
    user = sessions.validate(settings, raw_token)
    return user.role if user is not None else "anon"


@router.post("", response_model=RecordResult)
def post_events(body: RecordBody, request: Request) -> RecordResult:
    settings = get_settings()
    role = _resolve_role(request)
    hits = [NavHit(ts=event.ts, path=event.path, tab=event.tab, role=role) for event in body.events]
    return RecordResult(recorded=record_hits(settings, hits))


@router.get("/summary")
def get_summary(days: int = Query(default=30, ge=1, le=365)) -> dict[str, object]:
    settings = get_settings()
    return summarize(settings, days=days)

"""The access gate: a raw-ASGI middleware that requires a valid session on every request.

**Raw ASGI, not Starlette's ``BaseHTTPMiddleware``, and that choice is load-bearing.**
``BaseHTTPMiddleware`` buffers the response by running the downstream app inside an anyio task and
pulling its body through a memory stream, which breaks a long-lived ``text/event-stream`` -- and
this app has exactly one: ``GET /api/paperlive/stream`` (see ``app.api.paperlive``). A raw ASGI
middleware forwards ``receive``/``send`` untouched, so the SSE stream flows through the gate exactly
as if it were not there. ``tests/test_auth_gate_streaming.py`` pins that.

**What passes without a session** (the allowlist):

- ``OPTIONS`` anything -- CORS preflight carries no cookie and must not be gated.
- ``GET /api/health`` exactly -- the Docker healthcheck hits it, and it does no I/O and reveals
  nothing. Its ``/stores`` and ``/providers`` siblings are *not* on the list: they report ledger
  counts and provider status, which are exactly the kind of thing login exists to protect.
- ``/api/auth/login``, ``/api/auth/logout``, ``/api/auth/me`` -- the door itself. ``/api/auth/password``
  is deliberately absent: changing a password requires being signed in, so it is gated like
  everything else.

Everything else, including ``/docs`` and ``/openapi.json``, needs a valid session or gets a
``401`` with ``{"detail": "not_authenticated"}``.

**What needs the owner** (see ``app.auth.store`` for the role model). There are three tiers, and a
member who is refused by either owner tier gets the same ``403`` with ``{"detail": "owner_only"}``:

1. **Member read.** Everything not named below is readable *and* writable by any signed-in user:
   the read-only research surfaces (macro, news, market data, reports, thesis, rules), the paper
   desk, the backtest workbench, and each user's own ``/api/auth/password``.
2. **Owner write on the research surfaces** (:data:`WRITE_OWNER_ONLY_PREFIXES`). Members keep
   ``GET``/``HEAD`` on the agent desks, personas, the strategy-program job launchers and the
   translation surface, but only the owner may ``POST``/``PUT``/``PATCH``/``DELETE`` there. These
   are the routes that spend the owner's money (model calls) or seize a process-wide resource (a
   backtest slot, the evolution loop, a sweep of every market provider), so reading a past run is
   the member-safe half and starting a new one is not.
3. **Owner-only prefixes** (:data:`OWNER_ONLY_PREFIXES`): the personal-ledger surfaces --
   ``/api/tax``, ``/api/portfolio`` (which carries the transaction ledger under it),
   ``/api/import``, ``/api/users``, ``/api/health/stores`` and ``/api/manager``. Members are
   refused by *every* method here, reads included.

Both owner tiers are matched by path prefix here, in the one place every request already passes,
rather than as a dependency on each of those routers' ~40 routes, so a new route added under one of
those prefixes is protected by default and a new router that serves ledger data (or spends money)
has exactly one line to add. When ``auth_enabled`` is off there is no session to carry a role, and
the gate is a no-op as before: single-user local dev sees everything.
"""

from __future__ import annotations

import hmac
import json
from http.cookies import SimpleCookie

from app.auth import sessions
from app.config import get_settings

#: Exact paths that never require a session.
_ALLOWLIST = frozenset(
    {"/api/health", "/api/auth/login", "/api/auth/logout", "/api/auth/me"}
)

#: Path prefixes only an owner may reach. A prefix matches the path exactly or as a parent
#: segment -- `/api/tax` covers `/api/tax/report` but not a hypothetical `/api/taxonomy`.
OWNER_ONLY_PREFIXES: tuple[str, ...] = (
    "/api/tax",
    "/api/portfolio",
    # The planner board names the owner's accounts and the tickers they are planning around, and its
    # "pull current holdings" flow round-trips real positions through it -- owner-scoped, same as the
    # portfolio and tax ledgers it plans against.
    "/api/designer",
    "/api/import",
    "/api/users",
    "/api/health/stores",
    # The manager desk's brief folds the owner's account and tax state into one document, so the
    # whole prefix is owner-scoped in v1 rather than trying to redact per section. A member-scoped
    # brief (account/tax omitted) is a later, explicit scope -- see docs/MANAGER-DESK-PLAN.md §9.1.
    "/api/manager",
    # The notification feed carries the manager's account and tax headlines verbatim, so it inherits
    # the same owner scope the feed's source has. `GET`s under it are additionally reachable with the
    # read-only service token below.
    "/api/notify",
    # Navigation telemetry: which pages the owner visits and how often. Owner-only for the same
    # reason `/api/users` is -- it is a record about a person, not about the market.
    "/api/telemetry/nav/summary",
)

#: `GET`-only paths a read-only service token may reach with no session at all, so an external
#: poller (a phone shortcut, a cron) can watch the feeds without a browser. Enumerated rather than
#: prefixed on purpose: a leaked token must expose exactly these four reads and never a write.
_SERVICE_TOKEN_PATHS = frozenset(
    {
        "/api/notify/events",
        "/api/notify/status",
        "/api/manager/changes",
        "/api/manager/briefs/latest",
    }
)


def _read_header(headers: list[tuple[bytes, bytes]], name: bytes) -> str:
    """One header's value out of the raw ASGI header list, or ``""``."""
    for key, value in headers:
        if key.lower() == name:
            return value.decode("latin-1")
    return ""
#: Path prefixes where a member may read but only an owner may write. Checked for every method
#: except :data:`_SAFE_METHODS`; matched the same parent-segment way as
#: :data:`OWNER_ONLY_PREFIXES`. Each prefix below is a really-mounted router prefix -- verified
#: against ``grep -rn 'prefix=' backend/app/api/*.py``:
#:
#: - the three agent desks and the persona surface: every ``POST`` there is a model call billed to
#:   the owner's key (``app.agents.spend`` caps the daily total, it does not decide who may spend);
#: - ``/api/competition/jobs`` and ``/api/competition/loop``: a ``POST`` starts a backtest or the
#:   evolution supervisor, both of which hold a process-wide single slot for hours;
#: - ``/api/timeframes``: ``POST /matrix/jobs`` is the same shape (a long sweep, a shared slot);
#: - ``/api/i18n``: ``POST /translate`` is a model call;
#: - ``/api/market/refresh``: ``POST`` (mounted by ``app.api.data_admin`` under its bare ``/api``
#:   prefix) sweeps every market provider, which costs quota and can exhaust RAM on a small host.
#:
#: ``/api/agentdesk`` is the parent of the only router mounted under it,
#: ``app.api.live_decisions`` at ``/api/agentdesk/live`` -- there is no ``/api/live_decisions``
#: prefix in this app, and the parent form also covers any later sibling.
WRITE_OWNER_ONLY_PREFIXES: tuple[str, ...] = (
    "/api/tradingagents",
    "/api/vibedesk",
    "/api/workflow",
    "/api/personas",
    "/api/agentdesk",
    "/api/competition/jobs",
    "/api/competition/loop",
    "/api/timeframes",
    "/api/i18n",
    "/api/market/refresh",
)

#: Methods that read. ``OPTIONS`` never reaches the role check (it leaves the gate on the
#: allowlist), and is listed anyway so this set means what it says on its own.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _under(path: str, prefixes: tuple[str, ...]) -> bool:
    """Whether ``path`` is one of ``prefixes`` or sits below it as a parent segment."""
    return any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)


def is_owner_only(path: str) -> bool:
    """Whether ``path`` sits under one of :data:`OWNER_ONLY_PREFIXES` (every method)."""
    return _under(path, OWNER_ONLY_PREFIXES)


def is_write_owner_only(path: str, method: str) -> bool:
    """Whether ``method`` on ``path`` needs the owner under :data:`WRITE_OWNER_ONLY_PREFIXES`.

    ``GET``/``HEAD``/``OPTIONS`` are always ``False`` here: the point of this tier is that members
    keep reading these surfaces.
    """
    if method.upper() in _SAFE_METHODS:
        return False
    return _under(path, WRITE_OWNER_ONLY_PREFIXES)


def _read_cookie(headers: list[tuple[bytes, bytes]], name: str) -> str:
    """Pull one cookie's value out of the raw ASGI header list, or ``""``."""
    for key, value in headers:
        if key.lower() == b"cookie":
            jar = SimpleCookie()
            try:
                jar.load(value.decode("latin-1"))
            except Exception:
                return ""
            morsel = jar.get(name)
            return morsel.value if morsel is not None else ""
    return ""


class AuthGateMiddleware:
    """Require a valid session on every non-allowlisted HTTP request.

    Reads ``auth_enabled`` from settings on each request rather than at construction, so a test (or
    the conftest fixture) that flips ``INVDASH_AUTH_ENABLED`` and clears the settings cache changes
    the gate's behaviour without rebuilding the app.
    """

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        if not settings.auth_enabled:
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        path = scope.get("path", "")
        if method == "OPTIONS" or path in _ALLOWLIST:
            await self.app(scope, receive, send)
            return

        # Read-only service token: the owner's own bearer, for pollers that cannot hold a cookie.
        # Passes straight through as owner because the token *is* the owner's, and it can only reach
        # the four `GET`s in `_SERVICE_TOKEN_PATHS`. Unset (the default) skips this entirely; any
        # other method or path with a bearer falls through to the cookie logic below.
        service_token = settings.notify_service_token
        if service_token and method == "GET" and path in _SERVICE_TOKEN_PATHS:
            offered = _read_header(scope.get("headers", []), b"authorization")
            if hmac.compare_digest(offered, f"Bearer {service_token}"):
                await self.app(scope, receive, send)
                return

        raw_token = _read_cookie(scope.get("headers", []), sessions.COOKIE_NAME)
        user = sessions.validate(settings, raw_token)
        if user is None:
            await self._deny(send, 401, "not_authenticated")
            return
        if not user.is_owner and (is_owner_only(path) or is_write_owner_only(path, method)):
            await self._deny(send, 403, "owner_only")
            return
        await self.app(scope, receive, send)

    @staticmethod
    async def _deny(send, status: int, detail: str) -> None:  # type: ignore[no-untyped-def]
        body = json.dumps({"detail": detail}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

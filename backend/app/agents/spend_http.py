"""The FastAPI exception handler for `app.agents.spend.SpendCapExceeded`.

**Why this is a separate module rather than a `try`/`except` in a router.** `app.api.i18n` (owned by
this feature) catches `SpendCapExceeded` directly, since it can be edited freely. The persona routes in
`app.api.personas` cannot be touched here, so `app.personas.service`'s `ask`/`critique`/`consolidate`/
`strategy_card`/`start_ingest` let `SpendCapExceeded` propagate uncaught past `app.api.personas` (which
only translates `service.PersonaError`, and does not know this exception exists) all the way up to
FastAPI's exception-handling machinery -- where this handler, once registered, turns it into the same
`429` shape the i18n router returns by hand.

**This module does not register itself.** `app.main` owns the app instance and must call
`app.add_exception_handler(SpendCapExceeded, spend_cap_exceeded_handler)` once, at startup, alongside
its other handler registrations. That one line is intentionally left for `app.main`'s owner rather than
added here, per this change's scope.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from app.agents.spend import SpendCapExceeded

__all__ = ["spend_cap_exceeded_handler"]


async def spend_cap_exceeded_handler(request: Request, exc: Exception) -> JSONResponse:
    """Maps `SpendCapExceeded` to `429 Too Many Requests` with the same body shape
    `app.api.i18n.translate` returns for the same condition.

    Typed `exc: Exception` rather than `SpendCapExceeded` because that is the signature
    `FastAPI.add_exception_handler` accepts (a handler parameter is contravariant, so the narrower
    annotation fails mypy at the registration site); the `isinstance` narrows it back, and FastAPI
    only ever routes this class here.
    """
    if not isinstance(exc, SpendCapExceeded):  # pragma: no cover - registration guarantees this
        raise exc
    return JSONResponse(
        status_code=429,
        content={
            "detail": "spend_cap",
            "spent_usd": str(exc.spent_usd),
            "cap_usd": str(exc.cap_usd),
            "retry_after_seconds": exc.retry_after_seconds,
        },
    )

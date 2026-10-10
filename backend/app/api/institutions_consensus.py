"""Cross-institution consensus endpoint: across every tracked filer, which positions were bought
and sold the most in their latest disclosed change.

Thin on purpose, matching ``app.api.macro``'s shape: every failure this router could translate into
an HTTP status has already been handled one layer down, in ``app.institutions.consensus`` -- a fund
this endpoint cannot read never aborts the request, it lands in ``unchecked`` with a reason (see
that module's docstring, point 4). This router's only job is the query parameters and wiring the
settings singleton through.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Query

from app.config import get_settings
from app.institutions.consensus import ConsensusResponse, build_consensus

router = APIRouter(prefix="/api/institutions", tags=["institutions"])

_AS_OF_DESCRIPTION = (
    "Only consider filings that were public -- i.e. filed -- on or before this date (YYYY-MM-DD), "
    "passed straight through to every fund's delta the same way `/api/institutions/{key}/changes` "
    "uses it. Omit to see every filing available today."
)
_LIMIT_DESCRIPTION = "Maximum rows in `buys` and `sells`, ranked independently. Default 20."
_REFRESH_DESCRIPTION = (
    "Force a fresh walk of every tracked filer and overwrite the cached response, instead of "
    "serving a cached one -- the same escape hatch `/api/macro/snapshot?refresh=true` offers."
)

AsOfQuery = Annotated[dt.date | None, Query(description=_AS_OF_DESCRIPTION)]
RefreshQuery = Annotated[bool, Query(description=_REFRESH_DESCRIPTION)]
LimitQuery = Annotated[int, Query(ge=1, le=200, description=_LIMIT_DESCRIPTION)]


@router.get("/consensus", response_model=ConsensusResponse)
def consensus(
    as_of: AsOfQuery = None,
    refresh: RefreshQuery = False,
    limit: LimitQuery = 20,
) -> ConsensusResponse:
    """Most-bought and most-sold positions across every tracked filer's latest delta.

    **Slow when cold, and cached on disk to stay that way rarely.** This walks all twenty-two
    tracked filers, one EDGAR delta each -- see `app.institutions.consensus`'s module docstring for
    the caching contract this endpoint relies on to keep an ordinary page load fast.

    Never 4xxs on an empty catalog walk: a fund this cannot read lands in `unchecked` rather than
    aborting the request, so this endpoint always returns 200 with whatever it could check.
    """
    return build_consensus(settings=get_settings(), as_of=as_of, refresh=refresh, limit=limit)

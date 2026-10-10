"""Macro dashboard endpoints: the whole-page snapshot, one series' full history, Fear & Greed alone.

Thin on purpose. Every failure this router could translate into an HTTP status has already been
absorbed one layer down: :func:`app.market.macro.build_snapshot` never lets a
:class:`~app.market.providers.base.ProviderError` escape it -- a dead upstream degrades its own tile
into ``value=None`` plus a warning, and the endpoint below it always returns 200. The only genuine
error condition left at this boundary is :func:`app.market.macro.load_series` being asked for an id
nothing in this codebase knows how to fetch, which is a 404, not a 500 -- the frontend asks for a
tile's ``series_id`` verbatim, and a typo or a stale build must read as "not found", not crash the
expanded view.

**``as_of``** is the one query parameter all three endpoints below share. It bounds every section to
observations on or before it -- see :mod:`app.market.macro`'s module docstring for the truncation
contract and the reasoning behind stamping ``generated_at``/``fetched_at`` with the bound rather than
the newest included observation. It defaults to ``None`` (no bound, unchanged live behaviour) and is
declared as a plain ``dt.date | None`` parameter rather than an ``Annotated[..., Query(...)]`` alias,
matching ``start``/``end`` on ``/api/market/bars`` -- FastAPI already rejects an unparseable date with
422 for that shape, so there is nothing this router needs to add. ``/fear-greed`` is the one exception:
CNN has no as-of capability at all, so a non-``None`` bound there is a 422 from this router, not a
degraded 200 -- see :class:`~app.market.macro.FearGreedAsOfUnsupported`.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path

from app.config import get_settings
from app.market import macro
from app.market.macro_models import FearGreed, MacroSeries, MacroSnapshot
from app.market.providers.base import ProviderError, ProviderUnavailable, SymbolNotFound

router = APIRouter(prefix="/api/macro", tags=["macro"])

#: Same closed alphabet as `app.api.market.SymbolPath`, plus nothing extra: FRED ids (`DGS10`),
#: spreads (`T10Y2Y`) and Yahoo proxy tokens (`^TNX`, `CL=F`, `DX-Y.NYB`) are all already covered by
#: it, so there is no reason for this path to accept anything `market.py` would refuse.
SeriesIdPath = Annotated[str, Path(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9.\-^=]+$")]


def _handle(exc: ProviderError) -> HTTPException:
    """The same status mapping as `app.api.market._handle`.

    Kept as a short local copy rather than an import: it is a two-line contract (symbol confirmed
    missing -> 404, upstream down -> 503, anything else -> 502) that is cheaper to duplicate than to
    couple this router's importability to `market.py`'s internals.
    """
    if isinstance(exc, SymbolNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ProviderUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


@router.get("/snapshot", response_model=MacroSnapshot)
def snapshot(refresh: bool = False, as_of: dt.date | None = None) -> MacroSnapshot:
    """The whole macro page in one request, so no two panels disagree about what "now" means.

    ``refresh=true`` forces a provider round-trip for every section, the same escape hatch
    ``/api/market/bars`` offers. Off by default: macro series and Fear & Greed change at most daily
    (see ``app.market.macro``'s cache TTL), so a normal page open should cost no network call.

    ``as_of`` bounds every section to observations on or before it -- see the module docstring and
    ``app.market.macro``'s. Omitted, this endpoint's response is byte-for-byte what it was before
    this parameter existed. Set, ``fear_greed`` comes back ``None`` (with an explanatory warning)
    rather than a live CNN reading served under a historical label -- this endpoint never 4xxs for
    that reason, since a withheld tile is exactly the "one section degrades, the page still answers"
    contract every other tile here already has.
    """
    return macro.build_snapshot(get_settings(), refresh=refresh, as_of=as_of)


@router.get("/series/{series_id}", response_model=MacroSeries)
def series(series_id: SeriesIdPath, as_of: dt.date | None = None) -> MacroSeries:
    """Full history for one series, for the view behind an expanded tile.

    ``as_of`` truncates the returned ``points`` to observations on or before it and stamps
    ``fetched_at`` with the bound -- see ``app.market.macro``'s module docstring. A bound earlier
    than the series' first observation is not an error here: it comes back as a 200 with an empty
    ``points`` list and a warning, the same "explained absence, not a failure" shape a dead upstream
    already gets from this endpoint.
    """
    try:
        return macro.load_series(get_settings(), series_id, as_of=as_of)
    except macro.SeriesNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProviderError as exc:
        raise _handle(exc) from exc


@router.get("/fear-greed", response_model=FearGreed)
def fear_greed(as_of: dt.date | None = None) -> FearGreed:
    """The Fear & Greed index alone, for a widget that should not pay for the rest of the snapshot.

    Never a 503 when ``as_of`` is omitted: `load_fear_greed` falls back to the local composite when
    CNN is unreachable and that composite always returns *something* (neutral 50, loudly warned
    about, in the worst case) -- see `app.market.fear_greed.composite_fear_greed`.

    ``as_of`` is different from every other parameter in this router: CNN has no as-of query at all,
    so there is no degraded-but-200 answer to give, unlike a dead upstream. Passing anything other
    than ``None`` is a 422 -- the request itself asks for something this endpoint cannot do, which is
    the caller's mistake to fix, not an outage to report. See
    :class:`~app.market.macro.FearGreedAsOfUnsupported`.
    """
    try:
        return macro.load_fear_greed(get_settings(), as_of=as_of)
    except macro.FearGreedAsOfUnsupported as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

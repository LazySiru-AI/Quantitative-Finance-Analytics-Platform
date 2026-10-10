"""Institutional and fund holdings endpoints: the tracked-fund catalog, one fund's latest (or one
period's) holdings, and the change between its two most recent reporting periods.

Thin on purpose, matching ``app.api.macro``'s shape: every failure this router could translate into
an HTTP status has already been raised as a typed exception one layer down, in
``app.institutions.service``. This module's only job is mapping those exceptions onto the status
codes the frontend was built against -- it holds no fetching, parsing or diffing logic of its own.

``GET /api/institutions/funds`` is the one exception to "typed exception one layer down": it never
calls ``service`` at all and therefore never touches the network. It is this feature's first paint,
and it has to render instantly and reliably even when SEC is unreachable -- the catalog
(``app.institutions.catalog.default_catalog``) is a static tuple built into this application, not a
fetch.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict

from app.config import get_settings
from app.institutions import catalog, holders, service
from app.institutions.models import FundRef, PortfolioDelta, Snapshot
from app.institutions.parse import FilingParseError
from app.market.providers.base import (
    ProviderError,
    ProviderResponseError,
    ProviderUnavailable,
    RateLimited,
)

router = APIRouter(prefix="/api/institutions", tags=["institutions"])

#: A catalog key is short and closed-alphabet by construction (`"QQQ"`, `"BRK"`, `"BRIDGEWATER"`) --
#: see `app.institutions.catalog._DEFAULT_CATALOG`. The bound is generous headroom, not a fit to the
#: longest current key, so a future catalog addition does not need this file touched to match.
KeyPath = Annotated[str, Path(min_length=1, max_length=32)]

_PERIOD_DESCRIPTION = (
    "Quarter-end date (YYYY-MM-DD) of a specific reporting period. Omit for the fund's most "
    "recently disclosed period."
)
PeriodQuery = Annotated[dt.date | None, Query(description=_PERIOD_DESCRIPTION)]

_AS_OF_DESCRIPTION = (
    "Only consider filings that were public -- i.e. filed -- on or before this date (YYYY-MM-DD). "
    "Omit to see every filing available today, which is this endpoint's ordinary behaviour. Bounds "
    "by the filing's own filing date, not by the period it reports on: a filing covering an old "
    "quarter can itself have been filed recently, and vice versa, so bounding by period would not "
    "answer 'what was visible on this date'."
)
AsOfQuery = Annotated[dt.date | None, Query(description=_AS_OF_DESCRIPTION)]


def _resolve(key: str) -> FundRef:
    """The tracked fund named by ``key``, or a 404 naming both the bad key and the valid ones.

    The valid-keys list is not decoration: a caller staring at "unknown institution 'qqqq'" with no
    idea what *is* tracked has no next action except guessing again. Listing them costs one line and
    turns that guess into a lookup.
    """
    fund = catalog.find(key)
    if fund is not None:
        return fund
    valid_keys = ", ".join(f.key for f in catalog.default_catalog())
    raise HTTPException(
        status_code=404,
        detail=f"unknown institution key {key!r} -- valid keys are: {valid_keys}",
    )


def _map_provider_error(exc: ProviderError) -> HTTPException:
    """Status mapping for everything `app.institutions.service` can raise via `EdgarClient`.

    Checked most-specific-first because `RateLimited` and `ProviderResponseError` are both
    subclasses of `ProviderUnavailable` (see `app.market.providers.base`'s module docstring) -- an
    `isinstance(exc, ProviderUnavailable)` check alone would swallow both into 503 and never reach
    the 429 or 502 branch below it.
    """
    if isinstance(exc, RateLimited):
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
        return HTTPException(status_code=429, detail=str(exc), headers=headers)
    if isinstance(exc, ProviderResponseError):
        # SEC served a response, but not one shaped the way this application's client understands
        # -- an upstream problem, not something the caller of this endpoint did wrong.
        return HTTPException(status_code=502, detail=str(exc))
    if isinstance(exc, ProviderUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    # Every `ProviderError` this module actually raises is one of the three above; this branch
    # exists so a future subclass fails as a diagnosable 502 rather than an unhandled 500.
    return HTTPException(status_code=502, detail=str(exc))


@router.get("/funds")
def list_funds() -> dict[str, list[FundRef]]:
    """Every tracked fund. Static, network-free -- see the module docstring."""
    return {"funds": list(catalog.default_catalog())}


@router.get("/{key}/holdings", response_model=Snapshot)
def holdings(key: KeyPath, period: PeriodQuery = None, as_of: AsOfQuery = None) -> Snapshot:
    """One snapshot of ``key``'s holdings -- the most recent, or the one matching ``period``.

    ``as_of`` restricts the candidate filings to ones that were public on or before that date -- see
    `app.institutions.service.load_snapshots`'s docstring for the filing-date-not-period distinction
    this bound makes. Omitted (the default), this endpoint's behaviour is exactly what it has always
    been: every filing available today is a candidate.
    """
    fund = _resolve(key)
    settings = get_settings()
    client = service.build_client(settings)
    try:
        return service.load_latest(
            fund, client=client, settings=settings, period=period, as_of=as_of
        )
    except service.PeriodNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FilingParseError as exc:
        # SEC served a document this application's parser could not read -- an upstream problem,
        # not a bad request from the caller of this endpoint.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ProviderError as exc:
        raise _map_provider_error(exc) from exc


@router.get("/{key}/changes", response_model=PortfolioDelta)
def changes(key: KeyPath, as_of: AsOfQuery = None) -> PortfolioDelta:
    """What changed in ``key``'s holdings between its two most recent reporting periods.

    ``as_of`` narrows both periods to filings public on or before that date -- see `holdings`'s
    docstring and `app.institutions.service.load_delta`. Omitted (the default), unchanged.
    """
    fund = _resolve(key)
    settings = get_settings()
    client = service.build_client(settings)
    try:
        return service.load_delta(fund, client=client, settings=settings, as_of=as_of)
    except service.InsufficientHistory as exc:
        # Deliberately not a 200 with an empty delta -- see `InsufficientHistory`'s docstring on why
        # "only one filing on record" must not render as "nothing changed".
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FilingParseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ProviderError as exc:
        raise _map_provider_error(exc) from exc


class HolderRow(BaseModel):
    """One tracked filer's disclosed position in the requested symbol."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    name: str
    period: dt.date
    filed: dt.date
    accession: str
    cusip: str
    issuer: str
    shares: Decimal
    value: Decimal
    weight: Decimal
    value_units_rescaled: bool


class UncheckedFund(BaseModel):
    """A tracked filer whose latest filing could not be read, and why."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    name: str
    reason: str


class HoldersResponse(BaseModel):
    """Which tracked filers hold one symbol.

    ``unchecked``, ``checked`` and ``total`` are not diagnostics -- they decide what an empty
    ``holders`` list means. "No tracked filer holds NVDA" and "none of the nineteen filers I could
    reach hold NVDA" are different claims, and only these fields separate them, so the UI must
    render them rather than treat them as optional detail.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    cusips: list[str]
    symbol_resolved: bool
    holders: list[HolderRow]
    unchecked: list[UncheckedFund]
    checked: int
    total: int


@router.get("/holders/{symbol}", response_model=HoldersResponse)
def symbol_holders(
    symbol: Annotated[str, Path(min_length=1, max_length=12)],
    as_of: Annotated[dt.date | None, Query()] = None,
) -> HoldersResponse:
    """Reverse the institutions view: which tracked filers hold this symbol.

    **Slow when cold, and deliberately synchronous.** This walks every filer in the catalog, one
    EDGAR fetch each behind a six-hour cache, so the first call after a cache miss takes seconds.
    It is a GET on a page the reader has already chosen to open; the job machinery that exists for
    long work (`app.tournament.jobs`) is for runs measured in minutes, and wrapping this in it would
    buy nothing a reader would notice.

    **Never 404s on "nobody holds it".** An empty ``holders`` list with ``checked == total`` is a
    real answer and returns 200. The failure this endpoint has to avoid is the opposite one --
    returning an empty list because filings could not be read -- which is why ``unchecked`` travels
    with the result instead of the filers being silently skipped.
    """
    try:
        result = holders.find_holders(symbol, settings=get_settings(), as_of=as_of)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return HoldersResponse(
        symbol=result.symbol,
        cusips=list(result.cusips),
        symbol_resolved=result.symbol_resolved,
        holders=[HolderRow(**vars(h)) for h in result.holders],
        unchecked=[UncheckedFund(**vars(u)) for u in result.unchecked],
        checked=result.checked,
        total=result.total,
    )

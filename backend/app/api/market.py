"""Market data endpoints: bars, quotes, profiles, indicators, and the per-ticker summary.

The composition layer. It owns no maths and no I/O of its own -- the provider registry fetches, the
store persists, the indicator registry computes -- but it owns three things that only exist at this
boundary and that every one of those modules would otherwise have to guess at:

**Failure translation.** The provider error taxonomy exists so the registry can decide whether to
fall through. Here it decides an HTTP status instead: a symbol that does not exist is 404 and the
user should fix their typing; every provider being down is 503 and the user should try later. The
two are indistinguishable in a generic 500, which is why neither is allowed to reach one.

**NaN elimination.** Indicators emit ``NaN`` through their warmup window and that is correct.
``json.dumps`` renders it as the bare token ``NaN``, which is not valid JSON and fails
``JSON.parse`` in the browser with a syntax error pointing at a byte offset rather than at a cause.
Every float leaving this module passes through :func:`~app.market.models.jsonable_float`.

**Warning propagation.** Clamped ranges, provider fallbacks and stale stores are the honest part of
this product. They are collected from every layer that produced one and returned alongside the data
rather than logged, because a chart that silently shows sixty days where the user asked for five
years is worse than one that shows sixty days and says so.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.indicators import registry as indicators
from app.indicators.base import IndicatorError, IndicatorRequest, Pane, ParamKind
from app.market import social_history, store
from app.market.fundamentals import Fundamentals
from app.market.models import (
    BarSeries,
    Coverage,
    Interval,
    MarketWarning,
    Profile,
    Quote,
    jsonable_float,
)
from app.market.providers.base import ProviderError, ProviderUnavailable, SymbolNotFound
from app.market.registry import ProviderRegistry, default_registry

router = APIRouter(prefix="/api/market", tags=["market"])

#: Symbols reach the filesystem as Parquet partition directory names, so the accepted alphabet is
#: fixed here rather than sanitised downstream. ``^`` and ``=`` are included because index and
#: futures tickers need them (``^TNX``, ``CL=F``) and the macro page in Phase 5 depends on both.
_SYMBOL = {"min_length": 1, "max_length": 16, "pattern": r"^[A-Za-z0-9.\-^=]+$"}

SymbolParam = Annotated[str, Query(**_SYMBOL)]
SymbolPath = Annotated[str, Path(**_SYMBOL)]
"""Same alphabet, declared for a path segment. FastAPI rejects a ``Query`` marker on a path
parameter outright rather than coercing it, so the two cannot share one annotation."""

LimitParam = Annotated[int | None, Query(ge=1, le=20000)]


# ---------------------------------------------------------------------------
# Wire shapes that exist only at this boundary
# ---------------------------------------------------------------------------


class ParamSpecOut(BaseModel):
    """One indicator parameter, described well enough for the UI to build an input from it."""

    name: str
    kind: ParamKind
    default: Any
    minimum: float | None = None
    maximum: float | None = None
    choices: list[str] = Field(default_factory=list)
    label: str = ""


class IndicatorCatalogEntry(BaseModel):
    """A registry entry as the frontend sees it.

    The overlay menu is generated from this rather than hardcoded, which is what stops the UI from
    offering an indicator or a parameter range the backend will reject.
    """

    name: str
    title: str
    pane: Pane
    params: list[ParamSpecOut]
    outputs: list[str]
    intervals: list[Interval] | None
    description: str
    default_spec: str


class IndicatorSeriesOut(BaseModel):
    key: str
    name: str
    title: str
    pane: Pane
    columns: dict[str, list[float | None]]
    warmup: int


class IndicatorResponse(BaseModel):
    symbol: str
    interval: Interval
    ts: list[dt.datetime]
    """The aligned index. Every column below has exactly this length -- an indicator frame is never
    trimmed to drop its warmup, because a shortened series misaligns against the bars and presents
    as an indicator that leads price."""
    series: list[IndicatorSeriesOut]
    warnings: list[MarketWarning] = Field(default_factory=list)


class TickerSummary(BaseModel):
    symbol: str
    profile: Profile | None = None
    quote: Quote | None = None
    coverage: list[Coverage] = Field(default_factory=list)
    fundamentals: Fundamentals | None = None
    warnings: list[MarketWarning] = Field(default_factory=list)


class SyncResult(BaseModel):
    symbol: str
    interval: Interval
    source: str
    rows_written: int
    coverage: Coverage
    warnings: list[MarketWarning] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _registry() -> ProviderRegistry:
    """One registry per request.

    Deliberately not a module-level singleton: it holds an :class:`httpx.Client`, and a client
    created at import time outlives the event loop it was built against under ``--reload``, which
    fails at the second request rather than the first and looks like a network problem.
    """
    return default_registry()


def _handle(exc: ProviderError) -> HTTPException:
    """Map a provider failure onto the status that tells the user what to do about it."""
    if isinstance(exc, SymbolNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ProviderUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


def _series(
    symbol: str,
    interval: Interval,
    *,
    start: dt.date | None,
    end: dt.date | None,
    limit: int | None,
    refresh: bool,
) -> BarSeries:
    try:
        return store.ensure_series(
            symbol.upper(),
            interval,
            start=start,
            end=end,
            limit=limit,
            refresh=refresh,
            registry=_registry(),
        )
    except ProviderError as exc:
        raise _handle(exc) from exc


# ---------------------------------------------------------------------------
# Bars, quotes, profiles
# ---------------------------------------------------------------------------


@router.get("/bars", response_model=BarSeries)
def bars(
    symbol: SymbolParam,
    interval: Interval = Interval.DAY,
    start: dt.date | None = None,
    end: dt.date | None = None,
    limit: LimitParam = None,
    refresh: bool = False,
) -> BarSeries:
    """Stored bars for one symbol, fetching first when the store is empty or stale.

    ``refresh=true`` forces a provider round-trip. It is off by default because the store is the
    normal source: a chart redraw should not cost a network call, and the incremental sync already
    re-requests recent sessions to pick up corrections.
    """
    return _series(symbol, interval, start=start, end=end, limit=limit, refresh=refresh)


@router.get("/quote", response_model=Quote)
def quote(symbol: SymbolParam) -> Quote:
    """A last-price snapshot. Never persisted to the Parquet store -- that layer only holds
    completed bars. It can still come from the on-disk HTTP cache in `app.market.cache`, which
    gives Yahoo's meta lookup (this and `profile` both read `YahooProvider._meta`) a short,
    seconds-scale TTL of its own precisely so this endpoint does not answer with an hour-old price
    under the guise of a fresh one -- see `app.market.cache._META_LOOKUP_TTL`."""
    try:
        return _registry().get_quote(symbol.upper())
    except ProviderError as exc:
        raise _handle(exc) from exc


@router.get("/profile", response_model=Profile)
def profile(symbol: SymbolParam) -> Profile:
    """Instrument identity as the market provider sees it.

    Distinct from the ledger's :class:`~app.core.models.Instrument`, which is resolved from broker
    exports. Where the two disagree, the ledger wins for anything tax-facing; this one is for
    display.
    """
    try:
        return _registry().get_profile(symbol.upper())
    except ProviderError as exc:
        raise _handle(exc) from exc


@router.post("/sync", response_model=SyncResult)
def sync(symbol: SymbolParam, interval: Interval = Interval.DAY, full: bool = False) -> SyncResult:
    """Fetch and persist bars. The one endpoint here that writes."""
    try:
        outcome = store.sync_bars(symbol.upper(), interval, registry=_registry(), full=full)
    except ProviderError as exc:
        raise _handle(exc) from exc
    return SyncResult(
        symbol=outcome.symbol,
        interval=outcome.interval,
        source=str(outcome.source),
        rows_written=outcome.rows_written,
        coverage=outcome.coverage,
        warnings=outcome.warnings,
    )


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------


@router.get("/indicators/catalog", response_model=list[IndicatorCatalogEntry])
def catalog() -> list[IndicatorCatalogEntry]:
    """The indicator registry, so the UI builds its controls from the same definition as the maths."""
    return [
        IndicatorCatalogEntry(
            name=spec.name,
            title=spec.title,
            pane=spec.pane,
            params=[
                ParamSpecOut(
                    name=p.name,
                    kind=p.kind,
                    default=p.default,
                    minimum=p.minimum,
                    maximum=p.maximum,
                    choices=list(p.choices),
                    label=p.label or p.name,
                )
                for p in spec.params
            ],
            outputs=list(spec.outputs),
            intervals=sorted(spec.intervals) if spec.intervals is not None else None,
            description=spec.description,
            default_spec=indicators.default_spec(spec),
        )
        for spec in indicators.catalog()
    ]


@router.get("/indicators", response_model=IndicatorResponse)
def indicator_series(
    symbol: SymbolParam,
    interval: Interval = Interval.DAY,
    spec: Annotated[list[str], Query()] = [],  # noqa: B006 -- FastAPI reads the default as the schema
    start: dt.date | None = None,
    end: dt.date | None = None,
    limit: LimitParam = None,
    refresh: bool = False,
) -> IndicatorResponse:
    """Compute the requested indicators over the same bars ``/bars`` would return.

    Same window, same store, same alignment. Fetching the two independently would let the chart's
    candles and its overlays come from different reads, and a one-bar difference between them is
    invisible on screen and wrong everywhere it matters.
    """
    try:
        requests: list[IndicatorRequest] = [
            indicators.request(text, interval=interval) for text in spec
        ]
    except IndicatorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    series = _series(symbol, interval, start=start, end=end, limit=limit, refresh=refresh)

    # Built from the same bars the caller will receive rather than re-read from the store, so the
    # candles and their overlays cannot come from two different windows. `None` is mapped back to
    # NaN with an explicit float dtype: a column of Python `None` arrives as dtype `object`, and
    # every rolling and ewm operation downstream would silently fall back to slow, differently
    # behaved object arithmetic instead of raising.
    frame = pd.DataFrame(
        {
            "ts": pd.Series([b.ts for b in series.bars], dtype="datetime64[ns, UTC]"),
            **{
                column: pd.Series(
                    [getattr(b, column) for b in series.bars], dtype="float64"
                )
                for column in ("open", "high", "low", "close", "adj_close", "volume")
            },
        }
    )

    computed = indicators.compute(frame, requests)
    out: list[IndicatorSeriesOut] = []
    for request in requests:
        out.append(
            IndicatorSeriesOut(
                key=request.key,
                name=request.spec.name,
                title=request.spec.title,
                pane=request.spec.pane,
                columns={
                    column: [jsonable_float(v) for v in computed[column].tolist()]
                    for column in request.columns
                },
                warmup=request.spec.warmup(request.params),
            )
        )

    return IndicatorResponse(
        symbol=symbol.upper(),
        interval=interval,
        ts=[b.ts for b in series.bars],
        series=out,
        warnings=series.warnings,
    )


# ---------------------------------------------------------------------------
# Ticker summary
# ---------------------------------------------------------------------------


@router.get("/social/status")
def social_scheduler_status() -> dict[str, Any]:
    """Health of the recurring social-snapshot scheduler (`app.market.social_history.start_scheduler`)
    -- the counters, breaker state, and `healthy` flag `app.market.social_history.status` tracks.
    Mirrors `GET /api/market/refresh/status` (`app.main.market_refresh_status`) exactly: always
    answers, even when `Settings.social_snapshot_scheduler_enabled` is off or the scheduler has never
    ticked in this process (`total_ticks == 0`, `healthy` is `True` in that case, not a 404), so a
    caller can poll this unconditionally without first checking whether the feature is enabled.

    Lives here, on `app.market`'s own router, rather than beside the refresh endpoint in `app.main` --
    that endpoint's own docstring explains it sits in `app.main` only because `app.api.health` was
    outside *that* shard's scope fence; this shard's scope fence explicitly names this file as the
    place to add this route instead.
    """
    return social_history.status()


@router.get("/ticker/{symbol}", response_model=TickerSummary)
def ticker(symbol: SymbolPath) -> TickerSummary:
    """Everything the ticker page needs above the chart, in one round trip.

    Each part degrades on its own. A missing profile must not cost the user their quote, and
    fundamentals are absent for most of this portfolio by nature -- ETFs file nothing with the SEC,
    so "no fundamentals" is the common case and is reported as an explained absence rather than as
    a failure. Only a symbol that does not exist at all is an error.
    """
    upper = symbol.upper()
    registry = _registry()
    warnings: list[MarketWarning] = []

    try:
        prof: Profile | None = registry.get_profile(upper)
    except SymbolNotFound as exc:
        raise _handle(exc) from exc
    except ProviderError as exc:
        prof = None
        warnings.append(MarketWarning(kind="provider_fallback", message=str(exc)))

    try:
        q: Quote | None = registry.get_quote(upper)
    except ProviderError as exc:
        q = None
        warnings.append(MarketWarning(kind="provider_fallback", message=str(exc)))

    try:
        facts: Fundamentals | None = registry.get_fundamentals(upper)
    except SymbolNotFound as exc:
        facts = Fundamentals(symbol=upper, unavailable_reason=str(exc))
    except ProviderError as exc:
        facts = None
        warnings.append(MarketWarning(kind="provider_fallback", message=str(exc)))

    return TickerSummary(
        symbol=upper,
        profile=prof,
        quote=q,
        coverage=[store.coverage(upper, interval) for interval in Interval],
        fundamentals=facts,
        warnings=warnings,
    )

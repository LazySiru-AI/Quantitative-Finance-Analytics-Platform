"""The macro aggregation layer: composes FRED, CNN and the existing bar store into one page.

This module owns no HTTP of its own beyond constructing the default provider clients -- it is a
composition layer over :class:`~app.market.providers.fred.FredProvider`,
:class:`~app.market.providers.cnn.CnnFearGreedProvider`, :func:`~app.market.fear_greed.
composite_fear_greed` and :mod:`app.market.store`, in the same spirit as
:mod:`app.market.registry` composes bar providers. Three decisions carry most of the design:

**One dead upstream degrades its own tile, never the page.** Every section -- each rate, each oil
tile, Fear & Greed, each mover -- is built inside its own failure boundary. A :class:`~app.market.
providers.base.ProviderError` from FRED, CNN or the bar store is caught at the point it happens,
turned into a :class:`~app.market.models.MarketWarning`, and the affected tile arrives with
``value=None`` and an explanation rather than the whole snapshot failing. :func:`build_snapshot`
therefore has nothing left to catch: nothing it calls is allowed to raise a
:class:`~app.market.providers.base.ProviderError` past this module's boundary.

**Movers and Yahoo-proxy tiles read the bar store, they do not fetch bars themselves.** ``^TNX``,
``CL=F``, ``BZ=F`` and every mover symbol go through :func:`app.market.store.ensure_series`, exactly
the path the ticker page uses. That gets this module the store's caching, incremental sync and
provider fallback for free, and it means there is exactly one place in the codebase that decides
when a Yahoo-sourced bar is stale enough to refetch.

**A rate or a spread changes in basis points, a price changes in percent -- see
:func:`~app.market.macro_models.change_mode_for`.** The one case that makes this load-bearing rather
than cosmetic is ``T10Y2Y``: it legitimately crosses zero, and a percentage change divides by a
number that can be arbitrarily close to zero on either side of an inversion. Basis points
(``(new - old) * 100``) stay well defined on every value a spread can take, including negative ones,
which is why every change in this module is computed by :func:`_delta` against an explicit
:class:`~app.market.macro_models.ChangeMode` rather than a single hard-coded formula.

**``^TNX`` needs no unit conversion.** Yahoo already serves it in percent -- ``^TNX`` = 4.699 against
FRED's ``DGS10`` = 4.65 on the same day, a ratio of 1.01, not 10.1. Dividing by 10 here would render
the US 10-year at 0.47%. The tile is still tagged :attr:`~app.market.macro_models.MacroSource.YAHOO`
so the UI can show it is a proxy -- ``^TNX`` is a live intraday index and ``DGS10`` a daily published
constant-maturity rate, and they differ by a few basis points at any given moment even though neither
needs scaling.

**Every horizon change steps back to the nearest *valued* observation, never a fixed row offset.**
FRED publishes the calendar forward of the data (719 gap rows in ``DGS10`` alone), and the bar store
carries the same kind of trailing and interior gaps. ``points[-N]`` lands on a holiday as often as it
lands on real data; :func:`_nearest_on_or_before` walks backward from a target *date* and skips every
``None`` it passes, which is also what makes "year to date" mean "since the last observation of the
previous calendar year" rather than "since January 1st" -- a date that is never a trading day and is
frequently not an observation date for an economic series either.

**``as_of`` bounds observations, not labels.** Every public entry point (:func:`build_snapshot`,
:func:`load_series`, :func:`load_fear_greed`) takes an optional ``as_of: dt.date | None``. ``None``
(the default) means what it always meant: no bound, live data, ``generated_at``/``fetched_at`` stamp
"now". When ``as_of`` is set, :func:`_truncate_to_as_of` drops every :class:`~app.market.macro_models.
MacroPoint` dated after it from the *points list itself*, before any derived quantity is computed --
never after. A snapshot whose label says June 1st but whose ``us10y`` sparkline still carries an
August print is a worse defect than no bound at all: it *looks* trustworthy. Concretely this means
``value``, ``as_of`` (the tile's own field, not the request's), ``change`` (day/week/month/ytd) and
``spark`` on every :class:`~app.market.macro_models.MacroTile` and :class:`~app.market.macro_models.
MoverTile` are recomputed from the truncated list by the same functions that compute them for the
unbounded case (:func:`_latest_valued`, :func:`_series_change`, :func:`_spark`) -- there is no
separate "bounded" code path to compute them wrong in a different way, only a shorter list of points
feeding the same arithmetic.

``generated_at`` (on :class:`~app.market.macro_models.MacroSnapshot`) and ``fetched_at`` (on
:class:`~app.market.macro_models.MacroSeries`) stop being unconditionally :func:`dt.datetime.now`
the moment a bound is in force -- see :func:`_as_of_stamp`. They are set to the bound itself
(midnight UTC on ``as_of``), not to the latest observation actually included. A snapshot has *one*
``generated_at`` covering two rate tiles, two oil tiles, Fear & Greed and twenty movers, each
with its own publish calendar -- ``DGS10`` may have printed through the 14th while ``DCOILWTICO``'s
last print was the 12th, and neither is more "the" date than the other. Picking the bound sidesteps
that non-choice, is the same value no matter which section a reader looks at, and can never be
mistaken for a live timestamp: ``dt.datetime.now(UTC)`` at request time only equals midnight UTC of
an arbitrary caller-supplied date in the one case where that coincidence is harmless -- the caller
asked for today.

**Fear & Greed has no ``as_of`` capability, and this module refuses to fake one.** CNN's endpoint
returns one point-in-time reading -- there is no query parameter that asks CNN "what did you say on
a past date". Serving today's live score back for a request bound to an earlier date would be
exactly the lookahead this feature exists to close, just moved into the one tile the bound cannot
reach. :func:`build_snapshot` withholds it: ``fear_greed=None`` plus a warning naming the reason, the
same shape a dead CNN with a dead composite fallback would produce, so a page consumer already has to
handle "no Fear & Greed this time" as a case. :func:`load_fear_greed` -- whose response model has no
``None`` state to fall into -- raises :class:`FearGreedAsOfUnsupported` instead, which the API layer
turns into a 422: the caller asked this endpoint to do something it fundamentally cannot do, which is
a request-shape error, not a degraded-but-200 upstream outage.
"""

from __future__ import annotations

import calendar
import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import httpx

from app.config import Settings
from app.db.duck import Interval
from app.market import store
from app.market.cache import CachingTransport
from app.market.fear_greed import composite_fear_greed
from app.market.macro_models import (
    ChangeMode,
    FearGreed,
    MacroPoint,
    MacroSeries,
    MacroSnapshot,
    MacroSource,
    MacroTile,
    MacroUnit,
    MoverTile,
    SeriesChange,
    change_mode_for,
)
from app.market.models import BarSeries, BarSource, MarketWarning, jsonable_float
from app.market.providers.base import ProviderError
from app.market.providers.cnn import CnnFearGreedProvider
from app.market.providers.fred import FredProvider
from app.market.registry import ProviderRegistry, default_registry

__all__ = [
    "FearGreedAsOfUnsupported",
    "SeriesNotFound",
    "build_snapshot",
    "load_fear_greed",
    "load_series",
]


# ---------------------------------------------------------------------------
# Page contents (docs/PLAN.md section 4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _TileSpec:
    """One FRED-backed tile, with the Yahoo proxy symbol to try when FRED is unreachable."""

    key: str
    label: str
    fred_id: str
    unit: MacroUnit
    yahoo_symbol: str | None


_RATE_TILES: Final[tuple[_TileSpec, ...]] = (
    _TileSpec("us10y", "US 10-Year Treasury", "DGS10", MacroUnit.PERCENT, "^TNX"),
    # No Yahoo proxy for a spread: there is no single tradeable instrument that quotes 10y-2y
    # directly, so a dead FRED simply empties this tile rather than approximating one.
    _TileSpec("2s10s", "10Y-2Y Spread", "T10Y2Y", MacroUnit.PERCENT_SPREAD, None),
)
_OIL_TILES: Final[tuple[_TileSpec, ...]] = (
    _TileSpec("wti", "WTI Crude", "DCOILWTICO", MacroUnit.USD, "CL=F"),
    _TileSpec("brent", "Brent Crude", "DCOILBRENTEU", MacroUnit.USD, "BZ=F"),
)

#: symbol, display label, unit. Read straight from the store via `app.market.store` -- see the
#: module docstring for why this reuses the ticker page's fetch path rather than a new one.
_MOVERS: Final[tuple[tuple[str, str, MacroUnit], ...]] = (
    ("SPY", "SPDR S&P 500 ETF", MacroUnit.USD),
    ("QQQ", "Invesco QQQ Trust", MacroUnit.USD),
    ("DIA", "SPDR Dow Jones Industrial Average ETF", MacroUnit.USD),
    ("IWM", "iShares Russell 2000 ETF", MacroUnit.USD),
    ("XLK", "Technology Select Sector SPDR", MacroUnit.USD),
    ("XLF", "Financial Select Sector SPDR", MacroUnit.USD),
    ("XLE", "Energy Select Sector SPDR", MacroUnit.USD),
    ("XLV", "Health Care Select Sector SPDR", MacroUnit.USD),
    ("XLI", "Industrial Select Sector SPDR", MacroUnit.USD),
    ("XLY", "Consumer Discretionary Select Sector SPDR", MacroUnit.USD),
    ("XLP", "Consumer Staples Select Sector SPDR", MacroUnit.USD),
    ("XLU", "Utilities Select Sector SPDR", MacroUnit.USD),
    ("XLB", "Materials Select Sector SPDR", MacroUnit.USD),
    ("XLRE", "Real Estate Select Sector SPDR", MacroUnit.USD),
    ("XLC", "Communication Services Select Sector SPDR", MacroUnit.USD),
    ("^VIX", "CBOE Volatility Index", MacroUnit.INDEX),
    ("DX-Y.NYB", "US Dollar Index", MacroUnit.INDEX),
    ("GLD", "SPDR Gold Shares", MacroUnit.USD),
    ("TLT", "iShares 20+ Year Treasury Bond ETF", MacroUnit.USD),
    # Last in the cross-asset group alongside ^VIX/DX-Y.NYB/GLD/TLT, not the sector-SPDR run above --
    # BTC-USD is a cross-asset risk gauge, not an equity sector bet.
    ("BTC-USD", "Bitcoin", MacroUnit.USD),
)


class SeriesNotFound(Exception):
    """`load_series` was asked for an id this module has no fetch strategy for.

    Deliberately not a :class:`~app.market.providers.base.ProviderError`: nothing was actually asked
    of an upstream, so there is no provider name to attach and no fallback to attempt. The API layer
    maps this to 404, the same status an upstream-confirmed missing symbol gets, because from the
    caller's side the two are indistinguishable -- the series simply is not available under that id.
    """

    def __init__(self, series_id: str) -> None:
        super().__init__(f"unknown macro series id {series_id!r}")
        self.series_id = series_id


class FearGreedAsOfUnsupported(Exception):
    """`load_fear_greed` was asked for a bound it structurally cannot honour.

    CNN's endpoint has no "as of a past date" query -- it returns one live reading. Nulling out a
    field would be the natural degrade (see `build_snapshot`'s own `fear_greed=None` handling), but
    this function's return type is `FearGreed`, not `FearGreed | None`: there is no falsy value in
    that contract to fall back to that a caller could distinguish from a real score of zero. Raising
    here, for the API layer to turn into a 422, says plainly that the request itself is the problem
    -- "this endpoint cannot do that" -- rather than returning 200 with a number that would silently
    be today's live score wearing yesterday's label.
    """

    def __init__(self, as_of: dt.date) -> None:
        super().__init__(
            f"fear & greed has no as-of capability: CNN publishes one live reading, not a "
            f"queryable history, so a bound of {as_of.isoformat()} cannot be honoured without "
            "either serving today's score under a stale label or fabricating a historical one"
        )
        self.as_of = as_of


@dataclass(frozen=True)
class _CatalogEntry:
    """One entry in `_SERIES_CATALOG`: how `load_series` fetches a given id."""

    kind: str
    """`"fred"` or `"store"` -- selects the branch in :func:`load_series`."""
    unit: MacroUnit
    title: str


#: Every id `load_series` can answer: the four FRED series, their three Yahoo proxies, and every
#: mover symbol. Built from `_MOVERS` rather than duplicated, so a mover added there is immediately
#: fetchable by id without a second edit.
_SERIES_CATALOG: Final[dict[str, _CatalogEntry]] = {
    "DGS10": _CatalogEntry("fred", MacroUnit.PERCENT, "US 10-Year Treasury Yield"),
    "T10Y2Y": _CatalogEntry(
        "fred", MacroUnit.PERCENT_SPREAD, "10-Year minus 2-Year Treasury Spread"
    ),
    "DCOILWTICO": _CatalogEntry("fred", MacroUnit.USD, "WTI Crude Oil"),
    "DCOILBRENTEU": _CatalogEntry("fred", MacroUnit.USD, "Brent Crude Oil"),
    "^TNX": _CatalogEntry("store", MacroUnit.PERCENT, "US 10-Year Treasury Yield (Yahoo proxy)"),
    "CL=F": _CatalogEntry("store", MacroUnit.USD, "WTI Crude Oil (Yahoo proxy)"),
    "BZ=F": _CatalogEntry("store", MacroUnit.USD, "Brent Crude Oil (Yahoo proxy)"),
    **{symbol: _CatalogEntry("store", unit, label) for symbol, label, unit in _MOVERS},
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_snapshot(
    cfg: Settings,
    *,
    refresh: bool = False,
    as_of: dt.date | None = None,
    fred: FredProvider | None = None,
    cnn: CnnFearGreedProvider | None = None,
    registry: ProviderRegistry | None = None,
) -> MacroSnapshot:
    """Assemble the whole macro page in one call.

    ``fred``, ``cnn`` and ``registry`` default to real network-backed clients built once per call
    (see :func:`_default_fred`, :func:`_default_cnn`, :func:`~app.market.registry.default_registry`)
    -- never a module-level singleton, for the same reason ``app.api.market._registry`` builds one
    per request: a client built at import time can outlive the event loop it was constructed against.
    Tests inject fakes here instead of monkeypatching, which is what lets this function run with no
    network in the loop at all.

    Every section degrades independently -- see the module docstring. Nothing raised by an upstream
    escapes this function; the worst case is a snapshot full of empty tiles and warnings, never an
    exception the caller has to catch.

    ``as_of`` defaults to ``None``: no bound, identical to this function's behaviour before this
    parameter existed. When set, every rate, oil and mover tile is truncated to observations on or
    before it (see the module docstring's "``as_of`` bounds observations, not labels" section), and
    Fear & Greed is withheld entirely rather than served as a live reading under a historical label
    -- CNN has no as-of query, so ``fear_greed`` comes back ``None`` with a warning explaining why
    instead of the local composite (which requires its own component readings, not a fallback for
    "the CNN read is disallowed for this request shape") or, worse, today's real score.
    """
    fred_provider = fred or _default_fred(cfg, refresh=refresh)
    reg = registry or default_registry(cfg)

    all_warnings: list[MarketWarning] = []

    rates = [
        _build_tile(spec, cfg, refresh=refresh, as_of=as_of, fred=fred_provider, registry=reg)
        for spec in _RATE_TILES
    ]
    oil = [
        _build_tile(spec, cfg, refresh=refresh, as_of=as_of, fred=fred_provider, registry=reg)
        for spec in _OIL_TILES
    ]
    for tile in (*rates, *oil):
        all_warnings.extend(tile.warnings)

    fear_greed: FearGreed | None
    if as_of is None:
        cnn_provider = cnn or _default_cnn(cfg, refresh=refresh)
        fear_greed = _build_fear_greed(cnn_provider)
        all_warnings.extend(fear_greed.warnings)
    else:
        fear_greed = None
        all_warnings.append(
            MarketWarning(
                kind="as_of_unsupported",
                message=(
                    f"fear & greed withheld for as_of={as_of.isoformat()}: CNN publishes one live "
                    "reading with no as-of query, and serving it here would be exactly the "
                    "lookahead this bound exists to prevent"
                ),
            )
        )

    movers: list[MoverTile] = []
    for symbol, label, unit in _MOVERS:
        mover_tile = _build_mover(
            symbol, label, unit, cfg, refresh=refresh, as_of=as_of, registry=reg
        )
        movers.append(mover_tile)
        all_warnings.extend(mover_tile.warnings)

    return MacroSnapshot(
        generated_at=_as_of_stamp(as_of),
        rates=rates,
        oil=oil,
        fear_greed=fear_greed,
        movers=movers,
        warnings=all_warnings,
    )


def load_series(
    cfg: Settings,
    series_id: str,
    *,
    refresh: bool = False,
    as_of: dt.date | None = None,
    fred: FredProvider | None = None,
    registry: ProviderRegistry | None = None,
) -> MacroSeries:
    """Full history for one series, for the expanded view behind a tile.

    ``series_id`` is any id the snapshot can produce a tile or mover from -- a FRED id (``DGS10``), a
    Yahoo proxy symbol (``^TNX``), or a mover ticker (``SPY``). An id this module has no fetch
    strategy for raises :class:`SeriesNotFound` rather than returning an empty series, so the API
    layer can answer 404 instead of a silently blank chart.

    ``as_of`` defaults to ``None`` (no bound, unchanged behaviour). When set, the returned
    ``points`` are truncated to observations on or before it and ``fetched_at`` is stamped with the
    bound rather than "now" -- see the module docstring. A bound earlier than every observation in
    the series comes back as an explicitly empty ``points`` list with a ``short_history`` warning
    naming the requested date, never a 500 and never a fabricated zero.
    """
    entry = _SERIES_CATALOG.get(series_id)
    if entry is None:
        raise SeriesNotFound(series_id)

    if entry.kind == "fred":
        provider = fred or _default_fred(cfg, refresh=refresh)
        series = provider.fetch_series(series_id, unit=entry.unit)
        if as_of is None:
            # No copy: the provider's own `MacroSeries` -- including its own `fetched_at` -- is
            # returned exactly as received, unchanged from this parameter's introduction.
            return series
        points, trunc_warnings = _truncate_to_as_of(series.points, as_of, label=series_id)
        return series.model_copy(
            update={
                "points": points,
                "warnings": [*series.warnings, *trunc_warnings],
                "fetched_at": _as_of_stamp(as_of),
            }
        )

    reg = registry or default_registry(cfg)
    reference_date = as_of if as_of is not None else dt.date.today()
    bars = store.ensure_series(
        series_id,
        Interval.DAY,
        start=_history_start(reference_date),
        end=as_of,
        refresh=refresh,
        registry=reg,
        settings=cfg,
    )
    points, trunc_warnings = _truncate_to_as_of(_points_from_bars(bars), as_of, label=series_id)
    return MacroSeries(
        series_id=series_id,
        title=entry.title,
        unit=entry.unit,
        source=_mover_source(bars),
        points=points,
        warnings=[*bars.warnings, *trunc_warnings],
        fetched_at=_as_of_stamp(as_of),
    )


def load_fear_greed(
    cfg: Settings, *, as_of: dt.date | None = None, cnn: CnnFearGreedProvider | None = None
) -> FearGreed:
    """The Fear & Greed index alone, for a widget that should not pay for the rest of the snapshot.

    ``as_of`` is accepted only so callers who thread it through generically do not need a special
    case for this one endpoint -- passing anything other than ``None`` raises
    :class:`FearGreedAsOfUnsupported`. See the module docstring and that exception's own docstring
    for why: this function's return type has no falsy state to degrade into the way
    ``build_snapshot``'s ``fear_greed: FearGreed | None`` does.
    """
    if as_of is not None:
        raise FearGreedAsOfUnsupported(as_of)
    return _build_fear_greed(cnn or _default_cnn(cfg))


# ---------------------------------------------------------------------------
# Tile builders -- each one is its own failure boundary
# ---------------------------------------------------------------------------


def _build_tile(
    spec: _TileSpec,
    cfg: Settings,
    *,
    refresh: bool,
    as_of: dt.date | None,
    fred: FredProvider,
    registry: ProviderRegistry,
) -> MacroTile:
    """A FRED series turned into a tile, falling back to a Yahoo proxy when FRED has nothing.

    ``as_of`` truncates whichever source ends up supplying the tile, applied *before* the fallback
    decision below: if FRED has data but none of it is on or before ``as_of``, that is treated the
    same as FRED having nothing at all, and the Yahoo proxy is tried next -- bounded to the same
    ``as_of``. This is the same "next attempt is a structurally different source" reasoning the
    original fallback comment gives for a confirmed-missing FRED series; a series that exists but
    not yet as of the requested date is just one more shape of "FRED has nothing usable here".
    """
    warnings: list[MarketWarning] = []
    points: list[MacroPoint] = []
    source = MacroSource.FRED

    try:
        series = fred.fetch_series(spec.fred_id, unit=spec.unit)
        warnings.extend(series.warnings)
        points, trunc_warnings = _truncate_to_as_of(series.points, as_of, label=spec.fred_id)
        warnings.extend(trunc_warnings)
    except ProviderError as exc:
        # `SymbolNotFound` is not treated as special here even though it is terminal at the provider
        # level (see `app.market.registry`): the next attempt is not another FRED request, it is a
        # structurally different source (a Yahoo proxy), so a confirmed-missing FRED series is just
        # one more reason to try it.
        warnings.append(
            MarketWarning(
                kind="provider_fallback", message=f"fred unavailable for {spec.fred_id}: {exc}"
            )
        )
        points = []

    if _latest_valued(points) is None and spec.yahoo_symbol is not None:
        source = MacroSource.YAHOO
        reference_date = as_of if as_of is not None else dt.date.today()
        try:
            bars = store.ensure_series(
                spec.yahoo_symbol,
                Interval.DAY,
                start=_history_start(reference_date),
                end=as_of,
                refresh=refresh,
                registry=registry,
                settings=cfg,
            )
            warnings.extend(bars.warnings)
            points, trunc_warnings = _truncate_to_as_of(
                _points_from_bars(bars), as_of, label=spec.yahoo_symbol
            )
            warnings.extend(trunc_warnings)
        except ProviderError as exc:
            warnings.append(
                MarketWarning(
                    kind="provider_fallback",
                    message=f"yahoo proxy {spec.yahoo_symbol} unavailable for {spec.key}: {exc}",
                )
            )
            points = []

    mode = change_mode_for(spec.unit)
    latest = _latest_valued(points)
    if latest is None:
        return MacroTile(
            key=spec.key,
            label=spec.label,
            value=None,
            unit=spec.unit,
            as_of=None,
            change=SeriesChange(mode=mode),
            spark=[],
            source=source,
            warnings=warnings,
        )

    return MacroTile(
        key=spec.key,
        label=spec.label,
        value=jsonable_float(latest.value),
        unit=spec.unit,
        as_of=latest.date,
        change=_series_change(points, unit=spec.unit),
        spark=_spark(points),
        source=source,
        warnings=warnings,
    )


def _build_mover(
    symbol: str,
    label: str,
    unit: MacroUnit,
    cfg: Settings,
    *,
    refresh: bool,
    as_of: dt.date | None,
    registry: ProviderRegistry,
) -> MoverTile:
    """One ETF/index tile, read from the bar store -- no fetch path of its own. See module docstring."""
    mode = change_mode_for(unit)
    reference_date = as_of if as_of is not None else dt.date.today()

    try:
        bars = store.ensure_series(
            symbol,
            Interval.DAY,
            start=_history_start(reference_date),
            end=as_of,
            refresh=refresh,
            registry=registry,
            settings=cfg,
        )
    except ProviderError as exc:
        warning = MarketWarning(
            kind="provider_fallback", message=f"no data for mover {symbol}: {exc}"
        )
        return MoverTile(
            symbol=symbol,
            label=label,
            price=None,
            unit=unit,
            change=SeriesChange(mode=mode),
            spark=[],
            as_of=None,
            source=MacroSource.STORE,
            warnings=[warning],
        )

    points, trunc_warnings = _truncate_to_as_of(_points_from_bars(bars), as_of, label=symbol)
    warnings = [*bars.warnings, *trunc_warnings]
    source = _mover_source(bars)
    latest = _latest_valued(points)

    if latest is None:
        warnings.append(
            MarketWarning(kind="short_history", message=f"no bars available yet for mover {symbol}")
        )
        return MoverTile(
            symbol=symbol,
            label=label,
            price=None,
            unit=unit,
            change=SeriesChange(mode=mode),
            spark=[],
            as_of=None,
            source=source,
            warnings=warnings,
        )

    return MoverTile(
        symbol=symbol,
        label=label,
        price=jsonable_float(latest.value),
        unit=unit,
        change=_series_change(points, unit=unit),
        spark=_spark(points),
        as_of=latest.date,
        source=source,
        warnings=warnings,
    )


def _build_fear_greed(cnn: CnnFearGreedProvider) -> FearGreed:
    """CNN's real index while it answers; the local composite the moment it does not.

    The composite receives an *empty* component list here rather than a re-derivation of CNN's raw
    component values (the put/call ratio, the junk bond spread, ...) from some other source, because
    the only place those raw values are available at all is the very CNN endpoint that just failed.
    An empty input is exactly the case :func:`~app.market.fear_greed.composite_fear_greed` is built
    to handle: it reports a neutral 50 with a warning explaining that no component had usable data,
    rather than fabricating a score from nothing.
    """
    try:
        return cnn.fetch()
    except ProviderError as exc:
        warning = MarketWarning(
            kind="provider_fallback",
            message=f"cnn unavailable for fear & greed: {exc}; falling back to the local composite",
        )
        fallback = composite_fear_greed((), as_of=dt.date.today())
        return fallback.model_copy(update={"warnings": [warning, *fallback.warnings]})


def _mover_source(bars: BarSeries) -> MacroSource:
    """`BarSource` has more members than `MacroSource` -- see the latter's docstring on why the two
    are deliberately separate. Everything that is not a plain store read collapses to `YAHOO` here:
    a Stooq fallback or a fresh Yahoo fetch are both "an external market-data provider", which is the
    only distinction the macro contract draws."""
    return MacroSource.STORE if bars.source == BarSource.STORE else MacroSource.YAHOO


# ---------------------------------------------------------------------------
# Change arithmetic
# ---------------------------------------------------------------------------


def _series_change(points: Sequence[MacroPoint], *, unit: MacroUnit) -> SeriesChange:
    """Movement over the four standard horizons, anchored on the latest *valued* observation."""
    mode = change_mode_for(unit)
    latest = _latest_valued(points)
    if latest is None:
        return SeriesChange(mode=mode)
    latest_value = latest.value
    if latest_value is None:
        return SeriesChange(
            mode=mode
        )  # unreachable in practice -- `_latest_valued` already filters
    as_of = latest.date

    return SeriesChange(
        mode=mode,
        day=_horizon_change(points, as_of, latest_value, mode, as_of - dt.timedelta(days=1)),
        week=_horizon_change(points, as_of, latest_value, mode, as_of - dt.timedelta(days=7)),
        month=_horizon_change(points, as_of, latest_value, mode, _months_back(as_of, 1)),
        # Year to date is measured from the last observation of the *previous* calendar year, not
        # from January 1st -- see the module docstring. December 31st of last year is always a safe
        # target even when it falls on a weekend or holiday: `_nearest_on_or_before` steps back from
        # it to whatever the real last observation was.
        ytd=_horizon_change(points, as_of, latest_value, mode, dt.date(as_of.year - 1, 12, 31)),
    )


def _horizon_change(
    points: Sequence[MacroPoint],
    latest_date: dt.date,
    latest_value: float,
    mode: ChangeMode,
    target: dt.date,
) -> float | None:
    """One horizon's change, or `None` when the series does not reach back that far.

    `None` here means "unavailable", never "zero" -- a brand-new series with no prior observation
    must render as an em dash, not as "unchanged". See `SeriesChange`'s docstring.
    """
    baseline = _nearest_on_or_before(points, target)
    if baseline is None:
        return None
    baseline_value = baseline.value
    if baseline_value is None or baseline.date >= latest_date:
        return None
    return _delta(latest_value, baseline_value, mode)


def _nearest_on_or_before(points: Sequence[MacroPoint], target: dt.date) -> MacroPoint | None:
    """The latest valued observation at or before `target`.

    Never a fixed-offset index into `points`: FRED and the bar store both carry gap rows (holidays,
    an unsynced weekend), so `points[-N]` lands on a gap as often as it lands on real data. Walking
    backward from the end and skipping `None` values is what makes a one-basis-point Monday move not
    silently disappear because Monday happened to be a holiday.
    """
    for point in reversed(points):
        if point.date <= target and point.value is not None:
            return point
    return None


def _delta(new: float, old: float, mode: ChangeMode) -> float | None:
    """One horizon's movement, expressed the way `mode` says it must be.

    `ChangeMode.PERCENT` guards `old == 0.0` explicitly. A rate or a spread never reaches this branch
    -- both are `ChangeMode.BASIS_POINTS`, see `change_mode_for` -- but a price or index level could,
    and `(new - old) / 0.0` is exactly the bare-infinity failure `jsonable_float` exists to keep off
    the wire. Refusing it here, at the one place division happens, is cheaper than catching it after
    the fact three call frames later.
    """
    if mode is ChangeMode.BASIS_POINTS:
        return jsonable_float((new - old) * 100.0)
    if mode is ChangeMode.ABSOLUTE:
        return jsonable_float(new - old)
    if old == 0.0:
        return None
    return jsonable_float((new - old) / old * 100.0)


def _months_back(date: dt.date, months: int) -> dt.date:
    """`date` shifted back by whole calendar months, clamping the day into the target month.

    A naive `date - timedelta(days=30)` drifts against the calendar (28-31 day months) and would make
    the "month" horizon wander over a year of daily use. This lands on the same day-of-month one
    month earlier, or the last valid day of that month when there is no exact match (March 31st ->
    February 28th or 29th).
    """
    total_months = date.year * 12 + (date.month - 1) - months
    year, month0 = divmod(total_months, 12)
    month = month0 + 1
    day = min(date.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


def _latest_valued(points: Sequence[MacroPoint]) -> MacroPoint | None:
    """The most recent observation that actually has a value -- mirrors `MacroSeries.latest` for a
    plain point list, needed here because movers and Yahoo-proxy tiles build their `MacroPoint` list
    directly from bars rather than through a `MacroSeries`."""
    for point in reversed(points):
        if point.value is not None:
            return point
    return None


# ---------------------------------------------------------------------------
# as_of truncation -- see the module docstring's "`as_of` bounds observations, not labels" section
# ---------------------------------------------------------------------------


def _truncate_to_as_of(
    points: Sequence[MacroPoint], as_of: dt.date | None, *, label: str
) -> tuple[list[MacroPoint], list[MarketWarning]]:
    """Drop every observation dated after `as_of`, or return `points` unchanged when `as_of` is `None`.

    The single choke point every tile, mover and series passes its points through before computing
    anything derived. Every call site in this module calls this *before* `_latest_valued`,
    `_series_change` or `_spark` run, never after -- truncating a value that was already computed
    from the full series would leave the number right and the label lying about what produced it,
    which is the exact defect this feature exists to close (see the module docstring).

    `points <= as_of` is deliberately `<=`, not `<`: a caller who asks for `as_of=2026-06-01`
    expects the observation dated 2026-06-01 itself to be included -- "on or before", never
    "strictly before". Getting this backwards is the one-line bug that makes every boundary date
    silently one day stale.

    When `as_of` is not `None` and truncation empties an otherwise non-empty series, that is not
    "no data" in the generic sense the rest of this module already handles (a dead provider, an
    unsynced store) -- it specifically means every observation this series has is *after* the
    requested bound. Reusing a `provider_fallback`-style warning for that would send a reader
    hunting for a broken upstream that is not broken; the warning here names the bound and the
    earliest date that *is* available, which is the actual explanation.
    """
    if as_of is None:
        return list(points), []
    truncated = [point for point in points if point.date <= as_of]
    if truncated or not points:
        return truncated, []
    earliest = points[0].date.isoformat()
    warning = MarketWarning(
        kind="short_history",
        message=(
            f"{label}: no observation on or before as_of={as_of.isoformat()}; "
            f"earliest available observation is {earliest}"
        ),
    )
    return truncated, [warning]


def _as_of_stamp(as_of: dt.date | None) -> dt.datetime:
    """What `generated_at`/`fetched_at` say when a bound is or is not in force.

    `None` (no bound): "now", exactly as before this parameter existed -- see the module docstring
    for why every other behaviour must also be unchanged in this case.

    A bound: midnight UTC on `as_of` itself, not the newest observation actually included. The
    latter sounds more precise but does not have a single answer for `build_snapshot`, which stamps
    one `generated_at` across sections with independent publish calendars (see the module
    docstring's `generated_at` paragraph for the `DGS10`/`DCOILWTICO` example) -- there is no
    non-arbitrary way to pick one series' latest date to represent the whole page. Stamping the
    bound is unambiguous, identical regardless of which section produced it, and -- the property
    that actually matters here -- can never be misread as a live timestamp: `dt.datetime.now(UTC)`
    only coincides with midnight UTC on a caller-supplied date in the one case where the coincidence
    is harmless, which is a caller asking for today.
    """
    if as_of is None:
        return dt.datetime.now(dt.UTC)
    return dt.datetime.combine(as_of, dt.time.min, tzinfo=dt.UTC)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

#: Trailing window shipped for a tile's sparkline. FRED's daily series run to tens of thousands of
#: rows (16,854 for `DGS10`); shipping the full history on every snapshot would make the one payload
#: the size of the entire series for a line that renders a few hundred pixels wide.
_SPARK_LIMIT: Final[int] = 180


def _spark(points: Sequence[MacroPoint]) -> list[MacroPoint]:
    return list(points[-_SPARK_LIMIT:])


def _points_from_bars(series: BarSeries) -> list[MacroPoint]:
    """Bars, reduced to close-only observations for the macro contract.

    `Bar.ts` for a daily bar is already the exchange-local session date at midnight UTC (see
    `app.market.models.session_date`), so a plain `.date()` is safe here -- the timezone conversion
    that matters has already happened one layer down, in the provider.
    """
    return [MacroPoint(date=bar.ts.date(), value=jsonable_float(bar.close)) for bar in series.bars]


def _history_start(reference_date: dt.date) -> dt.date:
    """How far back to read stored bars for a mover or a Yahoo-proxy tile.

    Mid-December of the previous year, not December 31st: equities trade through the 31st most
    years, but a holiday landing on it or a store that has not synced in a few days both eat into the
    margin, and there is no cost to asking for a couple of extra weeks the change calculation will
    not use. `store.ensure_series`'s `start` only bounds what is *read* back out, not what gets
    fetched -- see its docstring -- so this cannot accidentally shrink what ends up on disk.

    `reference_date` is real "today" when there is no `as_of` bound in force, and `as_of` itself
    when there is. Anchoring on real "today" for a bounded request would be wrong in the direction
    that matters least visibly: the YTD horizon in `_series_change` is measured back from December
    31st of the year *before* the anchor date, so a request bounded to a date in an earlier calendar
    year would read back from the wrong December 31st and silently widen or shrink the read window
    relative to what `as_of` actually asked for.
    """
    return dt.date(reference_date.year - 1, 12, 15)


# ---------------------------------------------------------------------------
# Default provider construction
# ---------------------------------------------------------------------------

#: Macro series and the Fear & Greed index change at most once a day. Caching a response for a full
#: day -- rather than the market-data default of minutes, see `app.market.cache` -- is what keeps a
#: page refresh from re-downloading FRED's full CSV history (16,854 rows for `DGS10` alone) or
#: re-hitting CNN's undocumented endpoint on every open of the macro page.
_MACRO_CACHE_TTL: Final[float] = 86400.0


def _cached_client(cfg: Settings, *, refresh: bool = False) -> httpx.Client:
    """An `httpx.Client` over the same on-disk cache the rest of `app.market` uses, at the macro
    page's own (much longer) TTL. See `_MACRO_CACHE_TTL`.

    ``refresh`` pins that TTL to zero for this client, so every read is treated as expired and forces
    a real round trip -- the same escape hatch `app.api.calendar` builds for its own `refresh=true`,
    and the piece that makes `build_snapshot(refresh=True)` actually re-hit FRED and CNN rather than
    only bypassing the *bar-store* cache (which is all `refresh` reached before). The zero-TTL read
    still writes the fresh response back through the same on-disk cache, so the next ordinary request
    finds a warm entry -- a forced refresh updates the cache, it does not disable it."""
    transport = CachingTransport(
        httpx.HTTPTransport(), cfg.cache_dir / "http", ttl=0.0 if refresh else _MACRO_CACHE_TTL
    )
    return httpx.Client(transport=transport, timeout=10.0)


def _default_fred(cfg: Settings, *, refresh: bool = False) -> FredProvider:
    return FredProvider(_cached_client(cfg, refresh=refresh), api_key=cfg.fred_key)


def _default_cnn(cfg: Settings, *, refresh: bool = False) -> CnnFearGreedProvider:
    return CnnFearGreedProvider(_cached_client(cfg, refresh=refresh))

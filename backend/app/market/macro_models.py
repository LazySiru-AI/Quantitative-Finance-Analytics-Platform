"""Shared contract for the macro dashboard.

The macro page is a different shape of problem from the ticker page, and three distinctions drive
everything here.

**A macro observation is a date, not an instant.** FRED publishes one value per *observation date*
for a series like ``DGS10``; there is no intraday time and no exchange session behind it. Modelling
that as a :class:`~datetime.datetime` would invite exactly the timezone bug
:func:`app.market.models.session_date` exists to prevent -- a midnight-UTC stamp read in a westward
zone becomes the previous day -- so :class:`MacroPoint` carries a plain :class:`~datetime.date` and
the question never arises. Bars keep their datetimes; macro series do not have them to lose.

**Change is not always a percentage.** A 10-year yield moving 4.50 -> 4.60 is "+10 bp", not
"+2.2%", and a 2s10s spread crossing zero makes a percentage change meaningless or infinite. The
unit therefore decides how a delta is expressed, which is why :class:`MacroUnit` and
:func:`change_mode_for` exist rather than a single ``change_pct`` field that would be quietly wrong
for half the tiles on the page.

**Provenance is load-bearing, not decoration.** Every number on this page can come from more than
one place: FRED or its Yahoo proxy, CNN's own index or our approximation of it. The tile shows
which, because "the 10-year is 4.6" and "the 10-year is 4.6 according to a fallback proxy that
tracks it imperfectly" are different claims.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from app.market.models import MarketWarning

__all__ = [
    "RATING_BANDS",
    "ChangeMode",
    "FearGreed",
    "FearGreedComponent",
    "FearGreedSource",
    "MacroPoint",
    "MacroSeries",
    "MacroSnapshot",
    "MacroSource",
    "MacroTile",
    "MacroUnit",
    "MoverTile",
    "Rating",
    "SeriesChange",
    "change_mode_for",
    "rating_for",
]


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class MacroSource(StrEnum):
    """Where a macro number came from.

    Deliberately separate from :class:`app.market.models.BarSource`. The overlap is only
    ``yahoo``, and fusing them would put ``stooq`` and ``derived`` -- meaningless for an economic
    series -- into the macro contract, and ``fred`` and ``cnn`` into the bar contract where nothing
    can produce them.
    """

    FRED = "fred"
    YAHOO = "yahoo"
    """A market proxy standing in for the official series: ``^TNX`` for ``DGS10``, ``CL=F`` for
    ``DCOILWTICO``. Close, but not the same series -- ``^TNX`` is the CBOE index quoted in tenths
    of a percent and moves intraday, while ``DGS10`` is a daily constant-maturity rate published by
    the Treasury. A tile served from here is directionally right and precisely different."""
    CNN = "cnn"
    COMPUTED = "computed"
    """Calculated locally from other data we already hold. For Fear & Greed this is our own
    approximation, not CNN's number -- see :class:`FearGreedSource`."""
    STORE = "store"


# ---------------------------------------------------------------------------
# Units and change semantics
# ---------------------------------------------------------------------------


class MacroUnit(StrEnum):
    """What a macro value physically is. Decides formatting *and* change arithmetic."""

    PERCENT = "percent"
    """An interest rate or yield, already in percent (``DGS10`` = 4.65 means 4.65%)."""
    PERCENT_SPREAD = "percent_spread"
    """A difference between two rates, in percentage points (``T10Y2Y``). May be negative or zero,
    which is why it must never be given a percentage change."""
    USD = "usd"
    """A price in dollars: oil, an ETF close."""
    INDEX = "index"
    """A unitless index level: an ETF's own scale, the dollar index, a 0-100 sentiment score."""


class ChangeMode(StrEnum):
    """How a delta on this unit should be expressed."""

    PERCENT = "percent"
    """Relative: ``(new - old) / old * 100``. Only valid where the base cannot be zero or negative."""
    BASIS_POINTS = "basis_points"
    """Absolute, times 100. The conventional unit for a move in a rate or a spread."""
    ABSOLUTE = "absolute"
    """Absolute, in the series' own unit."""


#: Which change arithmetic each unit gets.
#:
#: Rates and spreads get basis points rather than percentages, and that is not a display preference.
#: ``T10Y2Y`` legitimately passes through zero; a percentage change across an inversion is division
#: by something near zero, so the tile would print a number in the thousands on a one-basis-point
#: move and ``inf`` on the day it crosses. Basis points are well defined on every value a spread can
#: take, including negative ones.
_CHANGE_MODE: Final[dict[MacroUnit, ChangeMode]] = {
    MacroUnit.PERCENT: ChangeMode.BASIS_POINTS,
    MacroUnit.PERCENT_SPREAD: ChangeMode.BASIS_POINTS,
    MacroUnit.USD: ChangeMode.PERCENT,
    MacroUnit.INDEX: ChangeMode.PERCENT,
}


def change_mode_for(unit: MacroUnit) -> ChangeMode:
    """The change arithmetic for a unit. Single source of truth for backend and frontend alike."""
    return _CHANGE_MODE[unit]


class SeriesChange(BaseModel):
    """Movement of one series over the standard horizons.

    Every field is optional because a horizon is genuinely unavailable when the series does not
    reach back that far, and a missing horizon must render as an em dash rather than as zero --
    "unchanged" and "unknown" are different statements, and conflating them is how a brand-new
    series appears to be flat.

    ``mode`` travels with the numbers so a consumer cannot format basis points as percent. It is
    duplicated onto every change object rather than looked up from the parent tile's unit because
    these objects are passed around individually.
    """

    model_config = ConfigDict(frozen=True)

    mode: ChangeMode
    day: float | None = None
    week: float | None = None
    month: float | None = None
    ytd: float | None = None
    """Year to date, measured from the last observation of the *previous* calendar year -- not from
    January 1st, which is never a trading day for a market series and is frequently not an
    observation date for an economic one."""


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------


class MacroPoint(BaseModel):
    """One observation. ``value`` is ``None`` for a published gap.

    FRED marks a non-trading day as a missing observation, and the two endpoints spell it
    differently -- the CSV download leaves the field empty, the JSON API sends the string ``"."``.
    Both must arrive here as ``None``. Coercing either to ``0.0`` would draw the 10-year yield
    collapsing to zero on every market holiday, which looks like a financial event rather than a
    parsing bug.
    """

    model_config = ConfigDict(frozen=True)

    date: dt.date
    value: float | None


class MacroSeries(BaseModel):
    """A full economic time series with provenance."""

    series_id: str
    """The upstream identifier where one exists (``DGS10``), otherwise our own stable token."""
    title: str
    unit: MacroUnit
    source: MacroSource
    points: list[MacroPoint] = Field(default_factory=list)
    warnings: list[MarketWarning] = Field(default_factory=list)
    fetched_at: dt.datetime | None = None

    @property
    def latest(self) -> MacroPoint | None:
        """The most recent observation that actually has a value.

        Not simply ``points[-1]``: a series routinely ends on one or more gap rows -- FRED publishes
        the calendar forward of the data -- and the last *row* is therefore often ``None`` while the
        last *observation* is a day or two earlier.
        """
        for point in reversed(self.points):
            if point.value is not None:
                return point
        return None


# ---------------------------------------------------------------------------
# Tiles
# ---------------------------------------------------------------------------


class MacroTile(BaseModel):
    """One headline number on the macro page, with its sparkline and provenance."""

    key: str
    """Stable token for layout and testing: ``us10y``, ``2s10s``, ``wti``, ``brent``."""
    label: str
    value: float | None
    unit: MacroUnit
    as_of: dt.date | None
    change: SeriesChange
    spark: list[MacroPoint] = Field(default_factory=list)
    """Recent history for the sparkline, oldest first. Gaps are carried as ``None`` values and must
    be rendered as breaks in the line, not bridged -- a bridged holiday is invisible, but a bridged
    two-week outage is a straight line the user will read as real."""
    source: MacroSource
    warnings: list[MarketWarning] = Field(default_factory=list)


class MoverTile(BaseModel):
    """One instrument in the ETF/index grid.

    Separate from :class:`MacroTile` because it is keyed by a tradeable symbol, where a macro tile
    is keyed by a concept and may be a rate or a spread. Most movers here are indeed prices in
    :attr:`currency` -- an ETF or crypto close -- but ``^VIX`` and ``DX-Y.NYB`` are index levels with
    no currency at all: the CBOE volatility index and the US Dollar Index both read out on their own
    unitless scale (around 15 and 99 respectively), not as a number of dollars. A reader, or a UI
    deciding whether to prefix a currency symbol, must consult :attr:`unit` before treating
    :attr:`price` as money -- that is precisely what was missing before this field existed, and why
    an index level used to render as ``$98.90``.
    """

    symbol: str
    label: str
    price: float | None
    currency: str = "USD"
    """The currency `price` is quoted in. Meaningful only when `unit` is `MacroUnit.USD` (or another
    currency-denominated unit); for `MacroUnit.INDEX` there is no currency and this field is not
    applicable to `price` at all."""
    unit: MacroUnit = MacroUnit.USD
    """What `price` physically is -- a currency-denominated price, or a unitless index level. Default
    of `MacroUnit.USD` exists only so construction sites elsewhere (tests, ad hoc tiles) do not break;
    every real construction site in `app.market.macro` passes this explicitly from `_MOVERS`."""
    change: SeriesChange
    spark: list[MacroPoint] = Field(default_factory=list)
    as_of: dt.date | None = None
    source: MacroSource = MacroSource.STORE
    warnings: list[MarketWarning] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Fear & Greed
# ---------------------------------------------------------------------------


class Rating(StrEnum):
    """CNN's five sentiment bands."""

    EXTREME_FEAR = "extreme fear"
    FEAR = "fear"
    NEUTRAL = "neutral"
    GREED = "greed"
    EXTREME_GREED = "extreme greed"


#: Upper bound (exclusive) of each band, in CNN's published scheme.
#:
#: The *fallback composite must use this same table*. If our approximation banded at different
#: cut-points, the page would show "fear" one day and "neutral" the next purely because the source
#: switched, and the reader would have no way to tell a sentiment change from a plumbing change.
RATING_BANDS: Final[tuple[tuple[float, Rating], ...]] = (
    (25.0, Rating.EXTREME_FEAR),
    (45.0, Rating.FEAR),
    (55.0, Rating.NEUTRAL),
    (75.0, Rating.GREED),
    (100.01, Rating.EXTREME_GREED),
)


def rating_for(score: float) -> Rating:
    """Band a 0-100 score. Bounds are inclusive-below, so exactly 25.0 is ``fear``."""
    for upper, rating in RATING_BANDS:
        if score < upper:
            return rating
    return Rating.EXTREME_GREED


class FearGreedSource(StrEnum):
    """Which engine produced the index, and how much to trust it."""

    CNN = "cnn"
    """CNN's own published score, fetched from their dataviz endpoint. Unofficial and undocumented,
    so it will break without notice -- but while it works it is the real number."""
    COMPOSITE = "composite"
    """Our approximation, computed locally when CNN is unreachable.

    It will not reproduce CNN's score exactly and must never be presented as if it did. CNN
    publishes the seven components' *raw underlying values* -- the S&P level, the VIX level, the
    put/call ratio -- but not the normalisation that maps each onto 0-100, nor the weights. The
    composite therefore re-derives its own scoring from those inputs. It tracks the real index's
    direction and rough level; it is not the same number, and the UI says so.
    """


#: What each component's ``raw_value`` actually measures, as ``(unit, description)``.
#:
#: Keyed on CNN's own token, and defined once here rather than in either provider, because the unit
#: is a property of the *measurement* and not of who reported it -- the CNN feed and the local
#: composite are describing the same seven quantities. Both paths read this map, so the two can
#: never disagree about what a number means.
#:
#: This exists because the value was rendered as a bare decimal under a column headed "Raw", where
#: an S&P 500 index level, a put/call ratio and a credit spread appear as three unlabelled numbers
#: on adjacent rows. The model's own docstring said they were "not comparable across components"
#: while the UI presented them as if they were. Reported as a defect by a UAT persona, and confirmed.
FEAR_GREED_UNITS: dict[str, tuple[str, str]] = {
    "market_momentum_sp500": (
        "index",
        "S&P 500 index level, against its 125-day moving average",
    ),
    "stock_price_strength": (
        "ratio",
        "stocks at 52-week highs relative to those at 52-week lows",
    ),
    "stock_price_breadth": (
        "index",
        "summation of volume in advancing versus declining stocks",
    ),
    "put_call_options": ("ratio", "put volume divided by call volume"),
    "market_volatility_vix": ("index", "VIX level"),
    "junk_bond_demand": (
        "pp",
        "yield spread between junk and investment-grade bonds, in percentage points",
    ),
    "safe_haven_demand": (
        "pp",
        "20-day stock return minus 20-day Treasury return, in percentage points",
    ),
}


class FearGreedComponent(BaseModel):
    """One of the seven inputs to the index."""

    model_config = ConfigDict(frozen=True)

    key: str
    """CNN's own token: ``market_momentum_sp500``, ``stock_price_strength``, ``put_call_options``,
    ``market_volatility_vix``, ``junk_bond_demand``, ``safe_haven_demand``, ``stock_price_breadth``."""
    label: str
    raw_value: float | None
    """The component's underlying measurement in its own unit -- an index level, a ratio, a spread.
    Not a 0-100 score, and not comparable across components. See :attr:`raw_unit`, which is what
    makes that statement visible to a reader rather than only true."""
    raw_unit: str | None = None
    """Short unit for :attr:`raw_value` -- ``index``, ``ratio``, ``pp``. ``None`` for a component
    this application has no unit on record for, which renders as no suffix rather than a guessed
    one: labelling a credit spread "index" is worse than labelling it nothing."""
    raw_description: str | None = None
    """What :attr:`raw_value` measures, in a phrase. Long enough for a tooltip, not for a column."""
    score: float | None = None
    """The component's 0-100 contribution, when known. ``None`` for a CNN-sourced component: CNN
    publishes ``raw_value`` and ``rating`` but never the score behind them. Populated only by the
    local composite, which computes it and can therefore show its work."""
    rating: Rating | None = None
    as_of: dt.date | None = None

    @classmethod
    def units_for(cls, key: str) -> tuple[str | None, str | None]:
        """``(unit, description)`` for a component key, or ``(None, None)`` if unknown.

        A key with no entry is a component CNN has added since :data:`FEAR_GREED_UNITS` was written.
        Returning nothing is the honest answer there — the alternative, inferring a unit from the
        magnitude of the number, is how a ratio gets labelled an index.
        """
        unit, description = FEAR_GREED_UNITS.get(key, (None, None))
        return unit, description


class FearGreed(BaseModel):
    """The Fear & Greed index with its components and provenance."""

    score: float
    rating: Rating
    source: FearGreedSource
    as_of: dt.date
    components: list[FearGreedComponent] = Field(default_factory=list)
    previous_close: float | None = None
    previous_week: float | None = None
    previous_month: float | None = None
    previous_year: float | None = None
    history: list[MacroPoint] = Field(default_factory=list)
    warnings: list[MarketWarning] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


class MacroSnapshot(BaseModel):
    """Everything the macro page renders, in one response.

    One payload rather than six endpoints because the page is a single glance and a per-tile
    waterfall would let the panels disagree about what "now" means. A section that failed entirely
    arrives empty with a warning attached, so one dead upstream degrades its own tile instead of
    the page.
    """

    generated_at: dt.datetime
    rates: list[MacroTile] = Field(default_factory=list)
    oil: list[MacroTile] = Field(default_factory=list)
    fear_greed: FearGreed | None = None
    movers: list[MoverTile] = Field(default_factory=list)
    warnings: list[MarketWarning] = Field(default_factory=list)

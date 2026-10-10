"""Shared market-data contract.

Every module in :mod:`app.market`, the indicator registry and the API layer agree on the shapes
here. Providers produce them, the store persists them, the API serialises them.

Three conventions carry most of the design, and getting any of them wrong produces a plausible
number rather than an error:

**Prices are floats, deliberately.** See the package docstring. :func:`assert_not_money` is the
enforcement point for the one direction that must never happen.

**Timestamps.** ``ts`` is always timezone-aware UTC. For intraday intervals it is the true instant
the bar opened. For ``1d`` and ``1w`` it is the *exchange-local session date* at midnight UTC --
not the raw provider timestamp, which for a US venue is 13:30 UTC and would silently become the
previous calendar day for anyone reading it in a westward timezone. Converting to the exchange
timezone before taking the date is mandatory; see :func:`session_date`.

**The store holds settled bars only.** A bar for a session that has not closed will change before
it is final. Rather than persist a value that mutates, the fetcher drops it, and the view layer may
append it from a live quote tagged :attr:`Bar.partial`. Backtests read the store, so they cannot
see a partial bar even by accident -- the guarantee is structural rather than a rule someone has to
remember.
"""

from __future__ import annotations

import datetime as dt
import math
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from app.db.duck import BAR_COLUMNS, Interval

__all__ = [
    "BAR_COLUMNS",
    "INTERVAL_MAX_LOOKBACK",
    "Bar",
    "BarSeries",
    "BarSource",
    "Coverage",
    "Interval",
    "MarketWarning",
    "Profile",
    "Quote",
    "SeriesPoint",
    "assert_not_money",
    "clamp_start",
    "jsonable_float",
    "session_date",
]


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

#: How far back the upstream provider will actually serve each interval. These are Yahoo's limits,
#: not preferences. A request beyond them returns a short series rather than an error, which is why
#: the store clamps explicitly and reports the clamp instead of letting the caller assume the gap
#: means "the ticker did not trade".
#:
#: The window is **exclusive at its far edge**: a request spanning exactly 730 days of 1h bars is
#: refused with HTTP 422, and 729 days is served. Enforcing that belongs in the provider, which is
#: the only layer that knows the end of the window it is about to ask for; this table states the
#: retention, and the provider keeps its request strictly inside it.
INTERVAL_MAX_LOOKBACK: Final[dict[Interval, dt.timedelta | None]] = {
    Interval.FIVE_MIN: dt.timedelta(days=60),
    Interval.FIFTEEN_MIN: dt.timedelta(days=60),
    Interval.THIRTY_MIN: dt.timedelta(days=60),
    Interval.HOUR: dt.timedelta(days=730),
    Interval.FOUR_HOUR: dt.timedelta(days=730),
    Interval.DAY: None,
    Interval.WEEK: None,
}


def clamp_start(
    interval: Interval, start: dt.date | None, *, today: dt.date | None = None
) -> tuple[dt.date | None, bool]:
    """Pull ``start`` forward to the earliest date the provider serves for ``interval``.

    Returns the effective start and whether clamping occurred, so the caller can attach a warning.
    A silent clamp is how a 60-day sample gets mistaken for the full history of a ticker.

    This reports the *retention boundary*, which is a date. It does not guarantee the resulting
    request is accepted -- the provider's limit applies to the span between its two endpoints, and
    only the provider knows where it is putting the far one. See ``yahoo._window_floor``.
    """
    limit = INTERVAL_MAX_LOOKBACK[interval]
    if limit is None:
        return start, False
    earliest = (today or dt.date.today()) - limit
    if start is None:
        return earliest, False
    if start < earliest:
        return earliest, True
    return start, False


# ---------------------------------------------------------------------------
# Float / Decimal boundary
# ---------------------------------------------------------------------------


def assert_not_money(value: Any, *, field: str = "value") -> float:
    """Reject a :class:`~decimal.Decimal` arriving in market space.

    The inverse of :func:`app.core.models._reject_float`. That one keeps market floats out of the
    tax path; this one keeps ledger Decimals out of the analytics path, where a Decimal would
    propagate into pandas as an ``object`` column and turn every downstream indicator into slow,
    silently mistyped arithmetic instead of a vectorised float operation.
    """
    if isinstance(value, Decimal):
        raise TypeError(
            f"{field}: Decimal is not permitted in market data; ledger money and market "
            "observations must not mix. Convert explicitly at the call site if that is intended."
        )
    return float(value)


def jsonable_float(value: float | None) -> float | None:
    """Map ``NaN`` and infinities to ``None`` for JSON.

    Indicators emit ``NaN`` through their warmup window -- an EMA(200) has no value until 200 bars
    exist -- and this is correct, not a defect. JSON has no NaN literal, so a raw dump produces the
    bare token ``NaN``, which is invalid JSON and fails ``JSON.parse`` in the browser with a syntax
    error pointing at a byte offset rather than at the cause. Every float crossing the API boundary
    goes through here.
    """
    if value is None:
        return None
    f = float(value)
    return None if (math.isnan(f) or math.isinf(f)) else f


def session_date(ts: dt.datetime, timezone: str) -> dt.date:
    """The exchange-local trading date of an instant.

    ``timezone`` is the provider's exchange timezone (Yahoo: ``meta.exchangeTimezoneName``). A US
    daily bar arrives stamped 13:30 UTC; ``ts.date()`` on that is right by luck for UTC readers and
    wrong for anyone else, and wrong outright for venues whose session crosses UTC midnight.
    """
    if ts.tzinfo is None:
        raise ValueError("session_date requires a timezone-aware timestamp")
    return ts.astimezone(ZoneInfo(timezone)).date()


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class BarSource(StrEnum):
    """Where a series came from. Surfaced in the UI: a fallback is worth seeing."""

    YAHOO = "yahoo"
    STOOQ = "stooq"
    STORE = "store"
    """Served from the local Parquet store without contacting a provider."""
    DERIVED = "derived"
    """Computed locally -- weekly bars resampled from stored daily bars."""


class MarketWarning(BaseModel):
    """A caveat attached to a series. Non-fatal, but the caller must be able to show it."""

    model_config = ConfigDict(frozen=True)

    kind: str
    """Stable machine token.

    Price and macro series: ``clamped``, ``short_history``, ``provider_fallback``, ``partial_bar``,
    ``stale``, ``gap``, ``missing_component``, ``derived``, ``as_of_unsupported``.

    News, social and event feeds (:mod:`app.market.news_models`): ``missing_news`` -- the upstream
    answered but carried no news field at all, which for an obscure ticker is an explained absence
    rather than a failure; ``partial_parse`` -- some rows in a well-formed payload were unusable and
    were dropped, with the count named in ``message``.

    This list is documentation, not validation: nothing enforces it, so a new token costs a line
    here and the next reader has to be able to find out what it means. ``partial_parse`` in
    particular is the token that says a feed is *incomplete* rather than short -- the reader who sees
    fifteen headlines needs to know whether that was all there was or all that survived."""
    message: str
    """Human-readable, already specific -- name the symbol, interval and dates."""


# ---------------------------------------------------------------------------
# Bars
# ---------------------------------------------------------------------------


class Bar(BaseModel):
    """One OHLCV bar as it crosses the API boundary.

    The in-memory and on-disk representation is a pandas DataFrame with :data:`BAR_COLUMNS`; this
    model exists only for serialisation. Do not build DataFrames out of these.
    """

    model_config = ConfigDict(frozen=True)

    ts: dt.datetime
    open: float
    high: float
    low: float
    close: float
    adj_close: float | None = None
    """Split- *and* dividend-adjusted close. Daily only; ``None`` on intraday intervals, where the
    provider does not supply one. Indicators default to ``close``; long-horizon total-return studies
    are the reason this column is carried from the start rather than retrofitted later."""
    volume: int | None = None
    partial: bool = False
    """The session behind this bar has not closed, so the values will still change. Never true for
    a bar read from the store -- only for one appended live at render time."""


class Coverage(BaseModel):
    """What the store actually holds for one symbol and interval."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    interval: Interval
    rows: int
    first_ts: dt.datetime | None = None
    last_ts: dt.datetime | None = None
    fetched_at: dt.datetime | None = None


class BarSeries(BaseModel):
    """A bar series with its provenance and caveats."""

    symbol: str
    interval: Interval
    source: BarSource
    bars: list[Bar] = Field(default_factory=list)
    warnings: list[MarketWarning] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.bars


# ---------------------------------------------------------------------------
# Quote and profile
# ---------------------------------------------------------------------------


class Quote(BaseModel):
    """A last-price snapshot. Not persisted -- it is stale the moment it is taken."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    price: float
    ts: dt.datetime
    currency: str = "USD"
    previous_close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    volume: int | None = None
    market_state: str | None = None
    """Provider's own label -- ``REGULAR``, ``CLOSED``, ``PRE``, ``POST``. Passed through rather
    than normalised, because the UI shows it verbatim and a wrong normalisation would be worse."""
    source: BarSource = BarSource.YAHOO


class Profile(BaseModel):
    """Instrument identity as the market data provider sees it.

    Distinct from :class:`app.core.models.Instrument`, which is the *ledger's* identity resolved
    from broker exports. This one is what Yahoo knows; they are reconciled by symbol, and where
    they disagree the ledger wins for anything tax-facing.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    name: str | None = None
    exchange: str | None = None
    exchange_timezone: str = "America/New_York"
    currency: str = "USD"
    instrument_type: str | None = None
    """Provider's own classification: ``EQUITY``, ``ETF``, ``INDEX``, ``CRYPTOCURRENCY``."""
    first_trade_date: dt.date | None = None
    source: BarSource = BarSource.YAHOO


class SeriesPoint(BaseModel):
    """One indicator value at one timestamp.

    ``value`` is ``None`` inside an indicator's warmup window. The frontend must render a gap there,
    not a zero -- a Bollinger band that reads 0 for its first twenty bars looks like a crash.
    """

    model_config = ConfigDict(frozen=True)

    ts: dt.datetime
    value: float | None

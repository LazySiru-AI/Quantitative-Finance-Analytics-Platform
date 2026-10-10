"""Shared contract for the event calendar: dated, forward-looking things worth knowing about.

The macro page (:mod:`app.market.macro_models`) answers "what is the 10-year yield today". This
module answers a different question -- "what is about to happen, and does it touch me" -- and three
distinctions drive the shapes below.

**A calendar entry is a date, sometimes a range, and only rarely an instant.** An FOMC meeting runs
two days and the decision lands at 14:00 ET on the second; an earnings report is announced "before
the open" or "after the close" on a given day, and the exact minute is not published. Modelling all
of this as a single :class:`~datetime.datetime` would force a fake precision that the upstream never
had, so :class:`CalendarEvent` carries a plain :class:`~datetime.date` plus an *optional* end date
and an optional coarse :class:`SessionTiming`. A caller that wants "when exactly" must read
``timing`` and accept that ``UNKNOWN`` is a real, common answer -- see the ``timing_known`` note
below for why that is surfaced rather than defaulted away.

**Confirmed and estimated dates are different claims and must not be mixed.** A company's earnings
date is *confirmed* once the company announces it and *estimated* (by a vendor extrapolating from
prior quarters) until then. An estimate can move by two weeks. Showing both in one column without
distinction would let a user schedule around a date that was never promised, which is precisely the
failure this feature exists to prevent, so :class:`EventConfidence` is a required field with no
default -- a producer must decide.

**Relevance is computed here, not in the UI.** "Earnings for a company I hold" and "earnings for a
company I do not hold" are the same upstream row; only the ledger distinguishes them. The backend
owns that join because the ledger lives here, so :attr:`CalendarEvent.symbol` is set only for
entries tied to a position, and :attr:`EventCalendar.holdings_covered` records how many of the
user's tickers the earnings sweep could actually speak to. A card that lists three earnings dates
out of forty holdings is telling a very different story from one that lists three out of three, and
the denominator must travel with the numerator -- the same rule the portfolio and news panels
already follow.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.market.models import MarketWarning

__all__ = [
    "CalendarEvent",
    "EventCalendar",
    "EventConfidence",
    "EventKind",
    "EventSource",
    "SessionTiming",
]


class EventKind(StrEnum):
    """What sort of thing is happening. Drives grouping and iconography in the UI."""

    FOMC = "fomc"
    """A scheduled Federal Open Market Committee meeting."""
    EARNINGS = "earnings"
    """A company's quarterly results announcement."""
    ECONOMIC_RELEASE = "economic_release"
    """A scheduled statistical release from a federal agency -- PCE, CPI, PPI, the jobs report, GDP,
    retail sales. Distinct from :attr:`FOMC` even though both are macro and neither is tied to a
    holding: an FOMC meeting is a *decision* the Committee makes, and a release is a *measurement*
    already taken that is merely being published. Collapsing them into one "macro" kind would put
    "the Fed might cut" and "July's PCE print lands" under one label and one colour, which is the
    distinction a reader scanning the calendar most needs to make."""


class EventSource(StrEnum):
    """Where the entry came from. Provenance is shown, not assumed -- see the module docstring."""

    FEDERAL_RESERVE = "federal_reserve"
    """Parsed from the Federal Reserve's own published FOMC calendar page."""
    BUNDLED_SCHEDULE = "bundled_schedule"
    """Read from the snapshot committed in this repo, because the live page was unreachable."""
    NASDAQ = "nasdaq"
    """Nasdaq's public earnings calendar."""
    FRED = "fred"
    """FRED's ``release/dates`` endpoint, which republishes each agency's own announced release
    schedule (BLS for CPI/PPI/Employment Situation, BEA for PCE and GDP, Census for retail sales).
    A forward-dated entry there is a date the agency has published, not FRED's projection, which is
    why these carry :attr:`EventConfidence.CONFIRMED`."""


class EventConfidence(StrEnum):
    """Whether the date is promised or merely projected. Never defaulted -- see module docstring."""

    CONFIRMED = "confirmed"
    """The issuing body announced this date."""
    ESTIMATED = "estimated"
    """Projected by a vendor from prior periods; may move."""


class SessionTiming(StrEnum):
    """Coarse time-of-day, at the only granularity the upstreams actually publish."""

    BEFORE_OPEN = "before_open"
    AFTER_CLOSE = "after_close"
    DURING_SESSION = "during_session"
    """Used for FOMC statements, which land at 14:00 ET mid-session."""
    UNKNOWN = "unknown"
    """The upstream carried a row but no timing. Common, and shown as such rather than guessed."""


class CalendarEvent(BaseModel):
    """One dated, forward-looking entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: EventKind
    title: str
    """Human-readable and already specific: ``"FOMC meeting"``, ``"NVDA earnings"``."""
    date: dt.date
    """The day the event happens, or the *first* day of a multi-day meeting."""
    end_date: dt.date | None = None
    """Final day of a multi-day event. ``None`` for single-day events, never equal to ``date``."""
    timing: SessionTiming = SessionTiming.UNKNOWN
    confidence: EventConfidence
    source: EventSource
    symbol: str | None = None
    """Ticker, set only when the entry is tied to a portfolio position. ``None`` for macro events."""
    detail: str | None = None
    """One short qualifier: ``"press conference and projections"``, ``"consensus EPS $2.09"``."""


class EventCalendar(BaseModel):
    """The full response: every upcoming entry, plus the honesty fields that qualify it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: dt.datetime
    start: dt.date
    """First day of the requested window, inclusive."""
    end: dt.date
    """Last day of the requested window, inclusive."""
    events: tuple[CalendarEvent, ...] = ()
    """Sorted by ``date`` ascending, then ``kind``, then ``symbol``."""
    holdings_total: int = Field(default=0, ge=0)
    """How many distinct tickers the ledger says are currently held."""
    holdings_covered: int = Field(default=0, ge=0)
    """How many of those the earnings sweep returned a date for. The denominator's partner."""
    warnings: tuple[MarketWarning, ...] = ()
    """Non-fatal caveats: an exhausted FOMC schedule, a failed earnings sweep, a partial parse."""

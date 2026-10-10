"""Scheduled federal economic releases -- PCE, CPI, PPI, the jobs report, GDP, retail sales.

The Overview calendar already answered "when does the Fed meet" and "when do my holdings report".
It could not answer the question a reader actually asks most often between those two: *when is the
next inflation print*. This module is that third source, and it is deliberately a sibling of
:mod:`app.market.fomc` rather than an extension of it -- same contract (never raises, returns
``(events, warnings)``, degrades to nothing with a named warning), different upstream.

**Source: FRED's ``release/dates`` endpoint, which republishes the agencies' own schedules.** BLS
publishes CPI, PPI and the Employment Situation schedule; BEA publishes Personal Income and Outlays
(the PCE release) and GDP; Census publishes advance retail sales. Scraping four agency pages would
mean four parsers and four ways to break, and BLS in particular refuses non-browser clients outright
(a plain ``GET`` of its schedule page answers ``403``, verified against the live site). FRED already
aggregates all of them behind one keyed JSON endpoint this codebase is set up to talk to, so this
module asks FRED once per release and translates.

A forward-dated entry from that endpoint is a date the *agency* announced, not a vendor's
extrapolation from prior months -- which is why every event here is
:attr:`~app.market.calendar_models.EventConfidence.CONFIRMED` rather than ``ESTIMATED``. That is a
real claim about the upstream and is the reason ``include_release_dates_with_no_data=true`` is sent:
without it, FRED returns only dates that already have data attached, i.e. only releases that have
already happened, and the forward half of the schedule -- the entire point of a calendar -- silently
disappears.

**Requires ``INVDASH_FRED_API_KEY``.** Unlike :mod:`app.market.providers.fred`'s series fetches,
there is no keyless CSV equivalent for the release schedule, so a missing key is reported as one
``config`` warning and zero events rather than being papered over. The calendar's other two halves
are unaffected; see :func:`app.market.calendar.build_calendar`, which treats this exactly the way it
treats a dead Nasdaq.

**Timing is stated, not fetched.** Every release named in :data:`RELEASES` is issued at 08:30 ET --
the standard hour for a Principal Federal Economic Indicator -- and the endpoint carries no time of
day at all. That constant is recorded per release rather than hardcoded in one place so a future
addition released at, say, 10:00 ET (existing-home sales) cannot inherit 08:30 by omission.

**Weekly jobless claims are deliberately absent** even though the release exists on FRED (id 180)
and is genuinely market-moving. A 60-day window holds nine of them, which would make two thirds of
the calendar one repeating row and bury the FOMC meeting and the two inflation prints a reader came
for. The bar for inclusion here is "monthly or quarterly, and moves the whole market", and that bar
is what keeps this list at six.

**Timestamps are ``dt.datetime.now(dt.UTC)``, never ``dt.datetime.utcnow()``** -- the latter is
deprecated and ``pytest.ini`` turns that deprecation into a hard test failure. Same rule the sibling
``app.market.calendar`` module states for its own ``generated_at``.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any, Final

import httpx

from app.config import Settings, get_settings
from app.market.calendar_models import (
    CalendarEvent,
    EventConfidence,
    EventKind,
    EventSource,
    SessionTiming,
)
from app.market.models import MarketWarning

__all__ = ["RELEASES", "Release", "release_events"]

logger = logging.getLogger(__name__)

_RELEASE_DATES_URL: Final[str] = "https://api.stlouisfed.org/fred/release/dates"

#: FRED tarpits a browser-shaped User-Agent -- the request hangs until timeout and never returns,
#: while an honest one answers in under a second. The same finding, against the same host, that
#: `app.market.providers.fred` records at length; repeated here rather than imported because that
#: module's constant is private to it and this one must not silently follow a change made there for
#: a different endpoint's reasons.
_USER_AGENT: Final[str] = "investing-dashboard/0.1"

_TIMEOUT: Final[float] = 10.0


@dataclass(frozen=True)
class Release:
    """One statistical release this calendar tracks.

    ``title`` is what a reader sees, and it leads with the name people actually use rather than the
    agency's own. The PCE release is filed by BEA as "Personal Income and Outlays" and is discussed
    everywhere else as "the PCE report"; a calendar row headed only by the former is a row most
    readers will not recognise as the inflation print they were waiting for, so both appear.
    """

    release_id: int
    title: str
    detail: str
    """One short qualifier naming the agency and the headline number, so a row says what it *is*
    rather than only when it is."""
    timing: SessionTiming = SessionTiming.BEFORE_OPEN


#: The releases on the calendar, in the order they are declared. Order here does not decide render
#: order -- `app.market.calendar` sorts the merged list by date -- it only decides which of two
#: releases landing on the same day is listed first, and PCE leads because it is the one this
#: calendar was extended to carry.
RELEASES: Final[tuple[Release, ...]] = (
    Release(
        release_id=54,
        title="PCE inflation (Personal Income and Outlays)",
        detail="BEA -- the Fed's preferred inflation gauge, headline and core PCE",
    ),
    Release(
        release_id=10,
        title="CPI",
        detail="BLS -- consumer price index, headline and core",
    ),
    Release(
        release_id=50,
        title="Jobs report (Employment Situation)",
        detail="BLS -- non-farm payrolls, unemployment rate, average hourly earnings",
    ),
    Release(
        release_id=53,
        title="GDP",
        detail="BEA -- quarterly output, advance/second/third estimates in successive months",
    ),
    Release(
        release_id=46,
        title="PPI",
        detail="BLS -- producer prices, an early read on the goods side of CPI",
    ),
    Release(
        release_id=9,
        title="Retail sales",
        detail="Census -- advance monthly retail and food services sales",
    ),
)


def release_events(
    *,
    start: dt.date,
    end: dt.date,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> tuple[tuple[CalendarEvent, ...], tuple[MarketWarning, ...]]:
    """Scheduled economic releases in ``[start, end]``, inclusive at both ends, plus any warnings.

    Never raises. Every failure mode -- no API key, a dead endpoint, a rejected key, a response
    whose shape changed -- comes back as a warning plus whatever events did parse, so one bad
    release never costs the other five and none of them ever costs the calendar its FOMC or
    earnings halves. That is the same contract :func:`app.market.fomc.fomc_events` keeps, and
    :func:`app.market.calendar.build_calendar` relies on both.

    Args:
        start: First day of the window, inclusive. Also sent upstream as ``realtime_start``, so the
            endpoint does the date filtering rather than this function fetching a decade and
            discarding most of it.
        end: Last day of the window, inclusive.
        settings: Defaults to :func:`app.config.get_settings`; read only for ``fred_key``.
        client: Shared ``httpx.Client``. Defaults to a plain one built and closed here. The
            calendar passes its own cached client so these six requests go through the same on-disk
            HTTP cache as everything else on the page -- a release schedule that changes a handful
            of times a year does not need a fresh round trip per page load.
    """
    cfg = settings or get_settings()
    api_key = cfg.fred_key
    if not api_key:
        return (), (
            MarketWarning(
                kind="config",
                message=(
                    "economic release dates need INVDASH_FRED_API_KEY; FRED has no keyless "
                    "equivalent of its release schedule, so PCE/CPI/jobs/GDP rows are omitted "
                    "rather than guessed"
                ),
            ),
        )

    owns_client = client is None
    active_client = client if client is not None else httpx.Client(timeout=_TIMEOUT)

    events: list[CalendarEvent] = []
    warnings: list[MarketWarning] = []
    try:
        for release in RELEASES:
            try:
                dates = _fetch_dates(active_client, release, api_key=api_key, start=start, end=end)
            except _ReleaseFetchError as exc:
                logger.warning("release calendar: %s failed: %s", release.title, exc)
                warnings.append(
                    MarketWarning(
                        kind="provider_fallback",
                        message=f"could not read the {release.title} release schedule ({exc})",
                    )
                )
                continue
            events.extend(_to_event(release, day) for day in dates if start <= day <= end)
    finally:
        if owns_client:
            active_client.close()

    events.sort(key=lambda event: (event.date, event.title))
    return tuple(events), tuple(warnings)


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


class _ReleaseFetchError(Exception):
    """One release's schedule could not be read. Caught per release, never escapes this module."""


def _fetch_dates(
    client: httpx.Client,
    release: Release,
    *,
    api_key: str,
    start: dt.date,
    end: dt.date,
) -> list[dt.date]:
    """One release's scheduled dates inside the window.

    ``include_release_dates_with_no_data=true`` is what makes this a *calendar* rather than a
    history: without it FRED answers only with dates that already carry an observation, which by
    construction excludes every release that has not happened yet. See the module docstring.
    """
    params = {
        "release_id": str(release.release_id),
        "api_key": api_key,
        "file_type": "json",
        "include_release_dates_with_no_data": "true",
        "realtime_start": start.isoformat(),
        "realtime_end": end.isoformat(),
    }
    try:
        response = client.get(
            _RELEASE_DATES_URL, params=params, headers={"User-Agent": _USER_AGENT}
        )
    except httpx.HTTPError as exc:
        raise _ReleaseFetchError(f"transport error: {exc}") from exc

    if response.status_code != 200:
        # A rejected key and an unknown release id are both 400 here, exactly as they are on the
        # observations endpoint. Neither is worth telling apart at this layer: both produce the same
        # user-visible outcome (this one release's rows are missing and the warning says so), and
        # this module has no fallback to choose between on the strength of the distinction.
        raise _ReleaseFetchError(f"HTTP {response.status_code}")

    try:
        payload: dict[str, Any] = response.json()
    except ValueError as exc:
        raise _ReleaseFetchError("response was not JSON") from exc

    rows = payload.get("release_dates")
    if not isinstance(rows, list):
        raise _ReleaseFetchError("response has no release_dates array")

    dates: list[dt.date] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("date")
        if not isinstance(raw, str):
            continue
        try:
            dates.append(dt.date.fromisoformat(raw))
        except ValueError:
            # One unparseable row is skipped rather than failing the release: five good dates are
            # worth more than a warning about the sixth.
            logger.warning("release calendar: %s has an unparseable date %r", release.title, raw)
    return sorted(set(dates))


def _to_event(release: Release, day: dt.date) -> CalendarEvent:
    return CalendarEvent(
        kind=EventKind.ECONOMIC_RELEASE,
        title=release.title,
        date=day,
        timing=release.timing,
        confidence=EventConfidence.CONFIRMED,
        source=EventSource.FRED,
        detail=release.detail,
    )

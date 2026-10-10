"""Nasdaq's public earnings calendar provider.

Nasdaq publishes a date-indexed calendar of upcoming earnings announcements at
``https://api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD`` -- one page per calendar day,
no API key, no auth. This is the *only* Nasdaq earnings surface this module talks to. A
tempting-looking sibling, ``https://api.nasdaq.com/api/analyst/{SYMBOL}/earnings-date``, was probed
live and rejected: for AAPL -- about as covered a ticker as exists -- it returned HTTP 200 with
"Our vendor, Zacks Investment Research, hasn't provided us with the upcoming earnings report date."
A 200 that means "no data" is worse than a 404, because nothing about the response shape says so; a
per-symbol sweep built on it would silently under-report holdings coverage. The date-indexed
calendar is what the frontend's own JavaScript actually renders from, and every date probed against
it (including 21 quiet weekend/holiday days) came back with a coherent shape.

Two upstream quirks are load-bearing rather than incidental, and both are exercised by fixtures in
``tests/fixtures/market/``:

* **A quiet day is HTTP 200 with ``data`` present but empty, not an error.** Weekends and market
  holidays return ``{"data": {"asOf": "...", "headers": null, "rows": null}, ...}`` -- captured live
  for a real Saturday in ``nasdaq_earnings_empty.json``. Treating a null/absent ``rows`` as malformed
  would turn every Saturday into a raised :class:`~app.market.providers.base.ProviderResponseError`,
  which is wrong: the upstream answered the question correctly, and the answer was "nothing today".
  :meth:`NasdaqEarningsProvider.fetch_earnings_for_day` returns ``()`` for this case and does not
  raise.
* **Missing values are spelled inconsistently, and rarely as JSON ``null``.** The live calendar
  spells "no consensus estimate yet" as an *empty string* (``"epsForecast": ""``) far more often than
  as the literal string ``"N/A"`` -- both appear across the upstream's own fields (``lastYearRptDt``,
  ``lastYearEPS`` and ``noOfEsts`` were observed as literal ``"N/A"`` in the same live pull that
  produced ``nasdaq_earnings_day.json``), but ``epsForecast`` itself was only ever observed empty,
  never as ``"N/A"``, across roughly 2,000 rows probed live in August-September 2026. Both spellings
  are treated as absent here regardless, on the assumption that Nasdaq's own inconsistency between
  fields is not a promise about which spelling a given field will keep using -- emitting the literal
  string ``"consensus EPS N/A"`` into ``CalendarEvent.detail`` would be a worse failure than being
  cautious about a spelling that happens not to have been observed yet.

Nasdaq's ``time`` token (``"time-after-hours"``, ``"time-pre-market"``, ``"time-not-supplied"``) is
the only session-timing signal the calendar carries, and it is mapped defensively:
:func:`_parse_timing` returns :data:`SessionTiming.UNKNOWN` for anything it does not recognise rather
than guessing, because a wrong guess here (e.g. defaulting to AFTER_CLOSE) would tell a reader a
company reports after a close it never confirmed.

The calendar carries no field distinguishing a company-confirmed report date from a vendor-projected
one -- every row it returns is a date Nasdaq itself lists for the day queried, with no "estimated"
flag anywhere in ``headers`` or a row. Every event this provider produces is therefore
:attr:`~app.market.calendar_models.EventConfidence.CONFIRMED`. If Nasdaq starts publishing such a
distinction, this mapping must change -- do not infer estimated-ness from the absence of
``epsForecast``, which merely means analyst coverage is thin, not that the date itself is a guess.

Rows that fail to parse -- most likely a missing or blank ``symbol``, since that is the one field
this module cannot substitute a sensible default for -- are skipped rather than aborting the whole
day. :attr:`NasdaqEarningsProvider.last_skipped` records how many rows the most recent call to
:meth:`fetch_earnings_for_day` dropped, so a caller assembling :class:`~app.market.calendar_models.
EventCalendar.warnings` can surface a ``partial_parse`` warning instead of the count silently
vanishing. It is an attribute rather than a return value because the public interface is pinned to
return only the events (see the module's consumers); overloading the return type to smuggle out a
count would break that contract.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Final

import httpx

from app.market.calendar_models import (
    CalendarEvent,
    EventConfidence,
    EventKind,
    EventSource,
    SessionTiming,
)
from app.market.providers.base import (
    ProviderResponseError,
    ProviderUnavailable,
    RateLimited,
)

__all__ = ["NasdaqEarningsProvider"]

_URL: Final[str] = "https://api.nasdaq.com/api/calendar/earnings"

#: Nasdaq 403s a request carrying httpx's default User-Agent (``python-httpx/x.y.z``). A plain
#: browser-shaped UA is sufficient -- no cookies, crumbs, or referer needed. Unlike FRED (see
#: ``fred.py``), Nasdaq does not tarpit this; it simply rejects the request synchronously.
_HEADERS: Final[dict[str, str]] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}

#: Nasdaq's own tokens for the ``time`` field, mapped to the calendar's coarse vocabulary. Anything
#: not a key here becomes SessionTiming.UNKNOWN -- see the module docstring.
_TIMING: Final[dict[str, SessionTiming]] = {
    "time-after-hours": SessionTiming.AFTER_CLOSE,
    "time-pre-market": SessionTiming.BEFORE_OPEN,
    "time-not-supplied": SessionTiming.UNKNOWN,
}

#: Spellings Nasdaq uses for "this field has no value". See the module docstring for why both are
#: honoured even though only one has been observed on ``epsForecast`` specifically.
_ABSENT: Final[frozenset[str]] = frozenset({"", "N/A"})


class NasdaqEarningsProvider:
    """Upcoming earnings announcement dates from Nasdaq's public, keyless calendar."""

    name = "nasdaq"

    def __init__(self, client: httpx.Client) -> None:
        self._client = client
        #: Rows dropped by the most recent :meth:`fetch_earnings_for_day` call because they could
        #: not be parsed (currently: missing/blank ``symbol``). Reset at the start of every call, so
        #: this reflects only the most recent day queried, not a running total across calls.
        self.last_skipped: int = 0

    def fetch_earnings_for_day(self, day: dt.date) -> tuple[CalendarEvent, ...]:
        """Every earnings announcement Nasdaq lists for ``day``. Empty tuple for a quiet day.

        A quiet day (weekend, market holiday, or simply a day with no scheduled reports) is not an
        error -- see the module docstring -- and returns ``()`` without raising.
        """
        self.last_skipped = 0
        response = self._get(day)
        self._raise_for_status(response, day)
        payload = self._parse_json(response, day)

        rows = self._extract_rows(payload, day)
        if not rows:
            return ()

        events: list[CalendarEvent] = []
        for row in rows:
            event = self._parse_row(row, day)
            if event is None:
                self.last_skipped += 1
                continue
            events.append(event)
        return tuple(events)

    # -- HTTP --------------------------------------------------------------

    def _get(self, day: dt.date) -> httpx.Response:
        try:
            return self._client.get(_URL, params={"date": day.isoformat()}, headers=_HEADERS)
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(
                f"nasdaq timed out fetching earnings for {day.isoformat()}", provider=self.name
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(
                f"nasdaq transport error fetching earnings for {day.isoformat()}: {exc}",
                provider=self.name,
            ) from exc

    def _raise_for_status(self, response: httpx.Response, day: dt.date) -> None:
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimited(
                f"nasdaq rate-limited the earnings request for {day.isoformat()}",
                provider=self.name,
                retry_after=float(retry_after) if retry_after else None,
            )
        if response.status_code >= 500:
            raise ProviderUnavailable(
                f"nasdaq returned {response.status_code} for earnings on {day.isoformat()}",
                provider=self.name,
            )
        if response.status_code >= 400:
            raise ProviderResponseError(
                f"nasdaq returned unexpected status {response.status_code} for earnings on "
                f"{day.isoformat()}",
                provider=self.name,
            )

    def _parse_json(self, response: httpx.Response, day: dt.date) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                f"nasdaq earnings response for {day.isoformat()} was not valid JSON",
                provider=self.name,
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderResponseError(
                f"nasdaq earnings response for {day.isoformat()} was not a JSON object",
                provider=self.name,
            )
        return payload

    # -- Shape -------------------------------------------------------------

    def _extract_rows(self, payload: dict[str, Any], day: dt.date) -> list[Any]:
        """Pull the row list out of ``payload``, treating a quiet day as legitimately empty.

        The top-level ``"data"`` key itself must be present and be an object or ``null`` -- anything
        else means the response is not shaped like the calendar endpoint at all, which is a parse
        failure, not a quiet day. Within ``data``, both ``data: null`` (never observed live, but
        plausible) and ``data.rows: null`` (the real shape of a weekend/holiday response -- see
        ``nasdaq_earnings_empty.json``) are quiet days.
        """
        if "data" not in payload:
            raise ProviderResponseError(
                f"nasdaq earnings response for {day.isoformat()} had no 'data' key", provider=self.name
            )
        data = payload["data"]
        if data is None:
            return []
        if not isinstance(data, dict):
            raise ProviderResponseError(
                f"nasdaq earnings response for {day.isoformat()} had a non-object 'data'",
                provider=self.name,
            )
        rows = data.get("rows")
        if rows is None:
            return []
        if not isinstance(rows, list):
            raise ProviderResponseError(
                f"nasdaq earnings response for {day.isoformat()} had a non-list 'rows'",
                provider=self.name,
            )
        return rows

    def _parse_row(self, row: Any, day: dt.date) -> CalendarEvent | None:
        """Build one event from one row, or ``None`` if the row is unusable.

        Only a missing/blank ``symbol`` is currently grounds to skip -- every other field has a safe
        absent-value mapping (see :func:`_parse_timing` and :func:`_parse_detail`), so a row that is
        merely thin on estimates is still a real, usable event.
        """
        if not isinstance(row, dict):
            return None
        symbol = row.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            return None
        symbol = symbol.strip().upper()

        timing = _parse_timing(row.get("time"))
        detail = _parse_detail(row.get("epsForecast"))

        return CalendarEvent(
            kind=EventKind.EARNINGS,
            title=f"{symbol} earnings",
            date=day,
            end_date=None,
            timing=timing,
            confidence=EventConfidence.CONFIRMED,
            source=EventSource.NASDAQ,
            symbol=symbol,
            detail=detail,
        )


def _parse_timing(raw: Any) -> SessionTiming:
    """Map Nasdaq's ``time`` token to :class:`SessionTiming`. Unrecognised input is UNKNOWN, never
    guessed -- see the module docstring."""
    if isinstance(raw, str) and raw in _TIMING:
        return _TIMING[raw]
    return SessionTiming.UNKNOWN


def _parse_detail(raw_eps: Any) -> str | None:
    """Render ``epsForecast`` as ``"consensus EPS $X.XX"``, or ``None`` when Nasdaq has none.

    ``None``, ``""``, and the literal string ``"N/A"`` are all treated as absent -- see the module
    docstring for why both spellings are honoured even though only ``""`` has been observed live on
    this specific field.
    """
    if not isinstance(raw_eps, str):
        return None
    value = raw_eps.strip()
    if value in _ABSENT:
        return None
    return f"consensus EPS {value}"

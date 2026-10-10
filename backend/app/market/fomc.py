"""FOMC meeting dates for the event calendar: the Fed's own page, parsed live, bundled fallback.

The Federal Reserve publishes its own meeting calendar at ``federalreserve.gov`` -- there is no API,
just an HTML page meant for humans (`fomccalendars.htm`). This module scrapes it, because it is the
one source that is never behind the actual announcement: a vendor calendar can lag a schedule change
by days, but the Fed's own page *is* the schedule. Everything below exists to make that scrape
survive the page surviving contact with reality.

**Meetings are parsed as blocks, never as two zipped lists.** The obvious approach -- collect every
``fomc-meeting__month`` value into one list, every ``fomc-meeting__date`` value into another, zip
them by position -- was tried against the live page and produced a silently wrong answer: the 2025
section returned 9 months against 8 dates, because one entry is a notation vote (``"22 (notation
vote)"``) whose date field contains letters and parentheses that a digits-only regex does not match,
so that one date is dropped from the *date* list while its month survives in the *month* list. From
that point on, every meeting after it is off by one position -- an August entry gets paired with
September's date, and so on for the rest of the year, and nothing about the output looks wrong
enough to notice by inspection. :func:`_parse_meetings` instead finds each meeting's own container
``<div>`` first (the one whose ``class`` ends in ``fomc-meeting``, not a piece of it such as
``fomc-meeting__month``) and pulls month and date *out of that one block*, so a field that fails to
parse only drops its own meeting -- it can never shift the pairing for every meeting that follows.
Regression coverage for exactly this defect lives in ``tests/fixtures/market/fomc_calendars.html``'s
2025 section, which keeps the real notation-vote markup.

**A meeting can straddle a month, and rarely a year.** The Fed spells a boundary-crossing meeting as
``"Apr/May"`` with dates ``"30-1"`` (April 30 - May 1), and the same shape appears for ``"Jan/Feb"``
and ``"Oct/Nov"``. :func:`_parse_meeting_block` never infers the rollover from whether the second day
number is smaller than the first -- a same-month meeting could coincidentally be typoed that way, and
guessing from the numbers would be silently wrong in a way that's hard to notice, exactly like the
zip-by-position bug above. Instead it always reads the month(s) actually named in the ``month`` field:
one name for both days when the field carries one, the field's two names in order when it carries two
(split on ``/``). A December/January meeting is the one case where the *year* rolls too -- the Fed
has never published one inside the window this module has been tested against, but nothing here
assumes December is impossible, so ``end_date``'s year is bumped whenever the start month is December
and the end month is January.

**Two sources, one contract, and the caller cannot tell them apart except through ``source``.** Live
parsing (:data:`~app.market.calendar_models.EventSource.FEDERAL_RESERVE`) is preferred because it is
never stale, but the page is one more upstream that can be unreachable, rate-limited, throttled by a
WAF, or restructured without notice -- and none of those are the caller's problem to handle. Any of
them degrades to the committed snapshot in ``data/calendar/fomc_schedule.json``
(:data:`~app.market.calendar_models.EventSource.BUNDLED_SCHEDULE`) with a ``provider_fallback``
warning attached, exactly the vocabulary :mod:`app.market.registry` already uses for the same
situation on the bars/profile/fundamentals chains -- one warning token means one thing everywhere in
this codebase. :func:`fomc_events` is therefore built to *never raise* for a network problem: the
one thing worse than an unreachable Fed page is a broken calendar page in the UI.

**A schedule that has simply run out is not the same failure as an unreachable page.** The Fed
publishes only the current and next year or so of meetings; a request for a window entirely beyond
the last published meeting is not a bug in this module, a network failure, or a parsing defect -- it
is an honest "nobody knows yet". That gets its own warning token, ``stale``, distinct from
``provider_fallback``, and it names the last known meeting date so a caller can decide whether to
show a "check back later" message instead of an empty calendar section. This check runs against
whichever source actually answered (live or bundled) rather than only the bundled path, because the
fact being reported -- "nothing published past this date" -- is the same fact regardless of which
source said it.

**The bundled snapshot's path is resolved from this file, not from ``Settings``.** ``Settings.
data_dir`` (``app/config.py``) is documented as the user's own gitignored broker exports, and the
test suite's ``settings`` fixture deliberately redirects it (and ``repo_root``) to a temporary
directory on every test so a test run never touches or depends on real user data. The bundled FOMC
schedule is the opposite of that: it is checked-in, versioned repository content that must resolve
the same way regardless of what a test (or a deployment) has pointed ``INVDASH_DATA_DIR`` at --
exactly the reasoning ``Settings.library_dir`` already applies to
``backend/app/paper/library/``. This module cannot reuse ``library_dir`` (a different, unrelated
package directory) and must not add a field to ``Settings`` (out of scope for this change), so it
follows the same *pattern* independently: :data:`_REPO_ROOT` is computed from ``Path(__file__)``, the
same way ``app.config.REPO_ROOT`` is computed from *its* ``__file__``, just one package level deeper
(``backend/app/market/fomc.py`` -> ``backend/app/market`` -> ``backend/app`` -> ``backend`` ->
repo root).

**The default client is cached, like every other provider's.** The Fed calendar changes a handful of
times a year, not per request, so a caller that does not supply its own ``httpx.Client`` gets one
built the same way :func:`app.market.registry.default_registry` builds its shared client: a real
:class:`httpx.HTTPTransport` wrapped in :class:`~app.market.cache.CachingTransport` over
``Settings.cache_dir / "http"``. Re-fetching 165 KB of HTML on every calendar-card render would be
pure waste for data that is this slow-moving.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import httpx

from app.market.calendar_models import (
    CalendarEvent,
    EventConfidence,
    EventKind,
    EventSource,
    SessionTiming,
)
from app.market.models import MarketWarning

__all__ = ["ScheduleRefresh", "fomc_events", "refresh_bundled_schedule"]

_CALENDAR_URL: Final[str] = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

#: The live page answers a bare/`requests`-style User-Agent with the same content in practice, but
#: this is the header verified live (2026-08-25) against the real endpoint -- see the module
#: docstring's fetch-fallback section. Kept as a realistic desktop-browser string, unlike FRED's
#: provider (`app.market.providers.fred`), which deliberately avoids one; the two upstreams behave
#: oppositely and each header is tuned to the upstream it talks to, not to a house style.
_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
)

# backend/app/market/fomc.py -> backend/app/market -> backend/app -> backend -> repo root. See the
# module docstring for why this is computed independently of `app.config.REPO_ROOT` rather than
# reusing a `Settings` field.
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

#: The committed fallback schedule. Overridable at the module level (not via `Settings`) so tests can
#: point it at a fixture without needing a settings fixture of their own -- see
#: `tests/test_fomc_calendar.py`.
_SCHEDULE_PATH: Final[Path] = _REPO_ROOT / "data" / "calendar" / "fomc_schedule.json"

_DETAIL_WITH_PROJECTIONS: Final[str] = "press conference and projections"

# Matches only the meeting's own container div -- its `class` attribute ends in the literal token
# `fomc-meeting`, never `fomc-meeting__month` or `fomc-meeting__date` (those end in `col-md-2` /
# `col-lg-1` etc, so the trailing `"` after `fomc-meeting` never follows them). The live page also
# emits a malformed `class="row fomc-meeting" ">` on some (not all) meeting rows -- a stray `"` and
# `>` left over after the real close quote -- which this still matches correctly because it only
# requires the class value itself to end in the plain word, not that nothing follows the tag.
_MEETING_START_RE = re.compile(r'<div class="[^"]*\bfomc-meeting\b"')
_YEAR_HEADER_RE = re.compile(r"(\d{4})\s+FOMC Meetings")
_MONTH_FIELD_RE = re.compile(r"fomc-meeting__month[^>]*>\s*(?:<strong>)?\s*([A-Za-z/]+)")
_DATE_FIELD_RE = re.compile(r"fomc-meeting__date[^>]*>\s*(?:<strong>)?\s*([^<]*?)\s*<")
#: A plain day, an optional second day (hyphen *or* en dash -- the live page uses both), and an
#: optional trailing `*` (Summary of Economic Projections marker). Deliberately anchored at both
#: ends: `"22 (notation vote)"` must fail this match rather than partially match `"22"`, because a
#: notation vote is not a two-day meeting and has no announced end date -- see the module docstring.
#:
#: The en dash is spelled `U+2013` rather than pasted in literally, and that is not cosmetic. It is
#: load-bearing -- the live page really does separate the two days with U+2013, so "fixing" it to a
#: plain hyphen would make every two-day meeting parse as a one-day one -- but as a literal character
#: it trips ruff's RUF001 ambiguous-character rule, and the obvious way to silence that lint is
#: precisely the edit that breaks the parser. The escape reads identically to the regex engine while
#: leaving nothing ambiguous for a linter or a reviewer to want to "correct".
_DAY_RANGE_RE = re.compile(r"^(\d{1,2})(?:[\u2013\-](\d{1,2}))?(\*)?$")

_MONTH_NUMBERS: Final[dict[str, int]] = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}  # fmt: skip


class _FomcParseError(Exception):
    """The live page's structure no longer matches what this parser expects.

    Raised, never returned, so that a page the Fed has restructured degrades through exactly the
    same fallback path as a network failure -- see :func:`fomc_events`. Not exported: callers outside
    this module only ever see it as a `provider_fallback` warning.
    """


class _Meeting:
    """One parsed meeting, source-agnostic -- shared shape for the live parse and the bundled JSON."""

    __slots__ = ("date", "end_date", "projections")

    def __init__(self, date: dt.date, end_date: dt.date | None, *, projections: bool) -> None:
        self.date = date
        self.end_date = end_date
        self.projections = projections

    @property
    def last_day(self) -> dt.date:
        return self.end_date or self.date


def _month_number(name: str) -> int | None:
    return _MONTH_NUMBERS.get(name.strip().lower())


def _parse_meeting_block(block: str, year: int) -> _Meeting | None:
    """Extract one meeting from its own container's HTML, or ``None`` if this block is not one.

    ``None`` covers two unremarkable cases, not an error: a notation vote (date field carries no
    parseable day range) and a month name this table does not recognise (a defensive floor, not
    something observed on the live page). Either way, the caller drops exactly this meeting and
    nothing else -- see the module docstring's zip-by-position section for why that isolation is the
    entire point of parsing block-by-block.
    """
    month_match = _MONTH_FIELD_RE.search(block)
    date_match = _DATE_FIELD_RE.search(block)
    if month_match is None or date_match is None:
        return None

    month_names = month_match.group(1).strip().split("/")
    # Filtered rather than tested with `any(... is None)`: the comprehension is what narrows
    # these to `int`, and without it both `dt.date(...)` calls below took an `int | None` month --
    # a `TypeError`, not a rejected block. The length check preserves the original rule, since a
    # filter can only shorten the list.
    month_numbers = [n for n in (_month_number(name) for name in month_names) if n is not None]
    if len(month_numbers) != len(month_names):
        return None
    start_month = month_numbers[0]
    end_month = month_numbers[-1]

    day_match = _DAY_RANGE_RE.match(date_match.group(1).strip())
    if day_match is None:
        return None

    start_day = int(day_match.group(1))
    end_day_raw = day_match.group(2)
    projections = day_match.group(3) == "*"
    start_date = dt.date(year, start_month, start_day)

    if end_day_raw is None:
        return _Meeting(start_date, None, projections=projections)

    # Only a December-start/January-end meeting rolls the year -- see the module docstring. Every
    # other cross-month pairing observed on the live page (Apr/May, Jan/Feb, Oct/Nov) stays within
    # one calendar year.
    end_year = year + 1 if (start_month == 12 and end_month == 1) else year
    end_date = dt.date(end_year, end_month, int(end_day_raw))
    return _Meeting(start_date, end_date, projections=projections)


def _parse_meetings(html: str) -> list[_Meeting]:
    """Every meeting on the page, across every year section present.

    Raises :class:`_FomcParseError` if the page carries no recognisable year section at all -- a
    page that returns *zero* meetings from a restructuring is a parse failure, not an honestly empty
    calendar, and must go through the same fallback path as a network error rather than being
    reported as "the Fed has no meetings scheduled".
    """
    year_matches = list(_YEAR_HEADER_RE.finditer(html))
    if not year_matches:
        raise _FomcParseError("no 'YYYY FOMC Meetings' section found in the fetched page")

    meetings: list[_Meeting] = []
    for index, year_match in enumerate(year_matches):
        year = int(year_match.group(1))
        section_start = year_match.end()
        section_end = (
            year_matches[index + 1].start() if index + 1 < len(year_matches) else len(html)
        )
        section = html[section_start:section_end]

        # Meetings are parsed as blocks bounded by consecutive container starts, never as two
        # independently zipped lists -- see the module docstring.
        starts = [match.start() for match in _MEETING_START_RE.finditer(section)]
        for block_index, block_start in enumerate(starts):
            block_end = (
                starts[block_index + 1] if block_index + 1 < len(starts) else len(section)
            )
            meeting = _parse_meeting_block(section[block_start:block_end], year)
            if meeting is not None:
                meetings.append(meeting)
    return meetings


def _fetch_html(client: httpx.Client) -> str:
    """Fetch the live calendar page, or raise :class:`_FomcParseError` for any failure to do so.

    Every failure mode -- transport error, timeout, non-200 status -- collapses to the same
    exception type, because :func:`fomc_events` treats "could not get a trustworthy page" as one
    condition regardless of why. Distinguishing timeout from 500 would only matter to a caller that
    could act differently on each, and the caller here (`fomc_events`) does the same thing either
    way: fall back to the bundled snapshot.
    """
    try:
        response = client.get(_CALENDAR_URL, headers={"User-Agent": _USER_AGENT}, timeout=30.0)
    except httpx.HTTPError as exc:
        raise _FomcParseError(f"request to {_CALENDAR_URL} failed: {exc}") from exc
    if response.status_code != 200:
        raise _FomcParseError(
            f"{_CALENDAR_URL} returned HTTP {response.status_code}"
        )
    return response.text


def _default_client() -> httpx.Client:
    """A client sharing the same on-disk HTTP cache every other provider uses.

    Built lazily (imports deferred to the call site) for the same reason
    `app.market.registry.default_registry` defers its provider imports: this module must stay
    importable, and its `client=None` path unused, without pulling in the whole settings/cache stack
    at import time.
    """
    from app.config import get_settings
    from app.market.cache import CachingTransport

    cfg = get_settings()
    inner = httpx.HTTPTransport()
    transport = CachingTransport(inner, cfg.cache_dir / "http")
    return httpx.Client(transport=transport, timeout=30.0)


def _load_bundled_schedule() -> list[_Meeting]:
    """The committed fallback schedule, or an empty list if it is missing or unreadable.

    Empty-on-failure rather than raising: a missing or corrupt bundled file must not crash the one
    code path that exists specifically to survive the *live* source being broken. `fomc_events`
    turns an empty result here into a `stale` warning the same way it would for a genuinely exhausted
    schedule -- from a caller's point of view "we have no bundled data" and "the bundled data ends
    before your window" are the same actionable fact: nothing to show, here is the newest date we
    know about (or that we know nothing at all).
    """
    return _load_bundled_schedule_from(_SCHEDULE_PATH)


def _load_bundled_schedule_from(path: Path) -> list[_Meeting]:
    """:func:`_load_bundled_schedule` against an explicit path, so a refresh can read its own target
    and tests can point at a temporary file instead of the committed one."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    meetings: list[_Meeting] = []
    for entry in payload.get("meetings", []):
        try:
            date = dt.date.fromisoformat(entry["date"])
            end_date_raw = entry.get("end_date")
            end_date = dt.date.fromisoformat(end_date_raw) if end_date_raw else None
            projections = bool(entry.get("projections", False))
        except (KeyError, ValueError, TypeError):
            continue  # one malformed row must not take down the rest of the snapshot
        meetings.append(_Meeting(date, end_date, projections=projections))
    return meetings


def _to_calendar_event(meeting: _Meeting, source: EventSource) -> CalendarEvent:
    return CalendarEvent(
        kind=EventKind.FOMC,
        title="FOMC meeting",
        date=meeting.date,
        end_date=meeting.end_date,
        timing=SessionTiming.DURING_SESSION,
        confidence=EventConfidence.CONFIRMED,
        source=source,
        detail=_DETAIL_WITH_PROJECTIONS if meeting.projections else None,
    )


def _in_window(meeting: _Meeting, start: dt.date, end: dt.date) -> bool:
    """``date`` OR ``end_date`` falls in ``[start, end]`` -- see :func:`fomc_events`'s docstring.

    A meeting that starts before the window but ends inside it (or vice versa) is still relevant to
    that window; a meeting entirely outside is not. Checking either endpoint, not just `date`, is
    what makes a one-day window landing on a meeting's *second* day still return that meeting.
    """
    return (start <= meeting.date <= end) or (start <= meeting.last_day <= end)


def fomc_events(
    *,
    start: dt.date,
    end: dt.date,
    client: httpx.Client | None = None,
) -> tuple[tuple[CalendarEvent, ...], tuple[MarketWarning, ...]]:
    """Upcoming FOMC meetings in ``[start, end]``, inclusive at both ends, plus any warnings.

    Tries the live Fed calendar first; any failure to fetch or parse it (see :func:`_fetch_html` and
    :func:`_parse_meetings`) degrades to the bundled snapshot with a ``provider_fallback`` warning,
    and this function never raises for that reason -- see the module docstring. If the source that
    did answer (live or bundled) has no meeting on or after ``start``, a ``stale`` warning names the
    last known meeting date; returning zero events with that warning is correct, not an error.
    """
    owns_client = client is None
    active_client = client if client is not None else _default_client()

    warnings: list[MarketWarning] = []
    try:
        try:
            html = _fetch_html(active_client)
            meetings = _parse_meetings(html)
            source = EventSource.FEDERAL_RESERVE
        except _FomcParseError as exc:
            warnings.append(
                MarketWarning(
                    kind="provider_fallback",
                    message=(
                        f"could not read the live FOMC calendar ({exc}); "
                        "showing the bundled schedule instead"
                    ),
                )
            )
            meetings = _load_bundled_schedule()
            source = EventSource.BUNDLED_SCHEDULE
    finally:
        if owns_client:
            active_client.close()

    if not any(meeting.last_day >= start for meeting in meetings):
        last_known = max((meeting.last_day for meeting in meetings), default=None)
        last_known_text = last_known.isoformat() if last_known is not None else "none on record"
        warnings.append(
            MarketWarning(
                kind="stale",
                message=(
                    "FOMC schedule has no meetings on or after "
                    f"{start.isoformat()}; last known meeting is {last_known_text}."
                ),
            )
        )

    events = tuple(
        sorted(
            (_to_calendar_event(meeting, source) for meeting in meetings if _in_window(meeting, start, end)),
            key=lambda event: event.date,
        )
    )
    return events, tuple(warnings)


# ---------------------------------------------------------------------------
# Regenerating the committed fallback
# ---------------------------------------------------------------------------
#
# The live page is the primary source (see `fomc_events`), so the app shows a newly published year
# the moment the Fed puts it up -- `_YEAR_HEADER_RE` matches any four digits and nothing here is
# pinned to a particular year. The committed snapshot exists only for when that page is unreachable,
# which is why it goes stale silently: nothing breaks until the one day it is needed. This is the
# entry point that refreshes it.


@dataclass(frozen=True)
class ScheduleRefresh:
    """What a refresh did, or declined to do. Returned rather than printed so tests can assert it."""

    path: Path
    written: bool
    years_before: tuple[int, ...]
    years_after: tuple[int, ...]
    meetings_before: int
    meetings_after: int
    last_before: dt.date | None
    last_after: dt.date | None
    refused_reason: str | None = None

    @property
    def new_years(self) -> tuple[int, ...]:
        """Years the live page carries that the committed snapshot did not."""
        return tuple(y for y in self.years_after if y not in self.years_before)


def _schedule_payload(meetings: Sequence[_Meeting], *, today: dt.date) -> dict[str, object]:
    return {
        "source_url": _CALENDAR_URL,
        "retrieved_at": today.isoformat(),
        "note": (
            "Committed fallback used when the live page is unreachable. The live page is the "
            "primary source, so a newly published year reaches the UI without this file being "
            "touched; regenerate it with `python -m app.market.fomc` (add --check to report "
            "without writing) so the offline path does not fall behind."
        ),
        "meetings": [
            {
                "date": m.date.isoformat(),
                "end_date": m.end_date.isoformat() if m.end_date else None,
                "projections": m.projections,
            }
            for m in meetings
        ],
    }


def refresh_bundled_schedule(
    *,
    client: httpx.Client | None = None,
    path: Path | None = None,
    today: dt.date | None = None,
    dry_run: bool = False,
) -> ScheduleRefresh:
    """Re-scrape the Fed calendar and rewrite the committed fallback snapshot.

    Two rules make this safe to run unattended, and each exists because the failure it prevents is
    silent rather than loud:

    **It refuses to shrink coverage.** If the scrape yields fewer forward meetings than the
    committed file, or an earlier final meeting, the file is left alone and ``refused_reason`` says
    why. The Fed restyles this page every few years, and a parser that quietly returned nothing
    would otherwise replace a good snapshot with an empty one -- destroying the fallback at exactly
    the moment the live page is the thing that broke. A refusal is a signal to fix the parser, not a
    no-op, which is why :func:`_main` exits non-zero on it.

    **It is idempotent.** When the scraped meetings match what is already on disk, nothing is
    written, so running this on a schedule does not produce a recurring one-line diff. Only
    ``retrieved_at`` would have moved, and a date stamp is not worth a commit.

    Past years are dropped: only meetings whose final day falls on or after 1 January of ``today``'s
    year are kept, which is everything a forward-looking window can ever ask for.
    """
    target = path if path is not None else _SCHEDULE_PATH
    now = today if today is not None else dt.datetime.now(dt.UTC).date()

    before = _load_bundled_schedule_from(target)
    owns_client = client is None
    active = client if client is not None else _default_client()
    fetch_error: str | None = None
    scraped: list[_Meeting] = []
    try:
        scraped = _parse_meetings(_fetch_html(active))
    except _FomcParseError as exc:
        # Unreachable page, non-200, or a layout the parser no longer recognises -- `_fetch_html`
        # funnels all three into this one type. A refresh is expected to run unattended, so this
        # becomes a reported refusal (file untouched, exit 1) rather than a traceback: the outcome
        # a scheduler must act on is "the snapshot was not updated, and here is why".
        fetch_error = str(exc)
    finally:
        if owns_client:
            active.close()

    cutoff = dt.date(now.year, 1, 1)
    after = sorted((m for m in scraped if m.last_day >= cutoff), key=lambda m: m.date)
    forward_before = [m for m in before if m.last_day >= cutoff]

    def _years(meetings: Sequence[_Meeting]) -> tuple[int, ...]:
        return tuple(sorted({m.date.year for m in meetings}))

    def _last(meetings: Sequence[_Meeting]) -> dt.date | None:
        return max((m.last_day for m in meetings), default=None)

    years_before = _years(before)
    years_after = _years(after)
    last_before = _last(before)
    last_after = _last(after)

    def _result(*, written: bool, refused: str | None = None) -> ScheduleRefresh:
        return ScheduleRefresh(
            path=target,
            written=written,
            years_before=years_before,
            years_after=years_after,
            meetings_before=len(before),
            meetings_after=len(after),
            last_before=last_before,
            last_after=last_after,
            refused_reason=refused,
        )

    refusal: str | None = None
    if fetch_error is not None:
        refusal = f"could not read the live FOMC calendar ({fetch_error})"
    elif not after:
        refusal = "the live page yielded no meetings; the parser or the page layout has changed"
    elif len(after) < len(forward_before):
        refusal = (
            f"the live page yielded {len(after)} forward meetings against "
            f"{len(forward_before)} already committed; refusing to shrink the fallback"
        )
    else:
        prior_last = _last(forward_before)
        if prior_last is not None and last_after is not None and last_after < prior_last:
            refusal = (
                f"the live page's final meeting ({last_after.isoformat()}) precedes the committed "
                f"one ({prior_last.isoformat()}); refusing to shrink the fallback"
            )

    if refusal is not None:
        return _result(written=False, refused=refusal)

    identical = [(m.date, m.end_date, m.projections) for m in forward_before] == [
        (m.date, m.end_date, m.projections) for m in after
    ]
    if identical or dry_run:
        return _result(written=False)

    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_suffix(target.suffix + ".staging")
    staging.write_text(
        json.dumps(_schedule_payload(after, today=now), indent=2) + "\n", encoding="utf-8"
    )
    staging.replace(target)  # atomic, the same idiom as app.market.cache's writes
    return _result(written=True)


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.market.fomc",
        description="Refresh the committed FOMC fallback schedule from the Federal Reserve's page.",
    )
    parser.add_argument(
        "--check", action="store_true", help="report what a refresh would do, without writing"
    )
    parser.add_argument("--json", action="store_true", help="emit the summary as JSON")
    args = parser.parse_args(argv)

    result = refresh_bundled_schedule(dry_run=args.check)

    if args.json:
        print(
            json.dumps(
                {
                    "written": result.written,
                    "checked_only": args.check,
                    "years_before": list(result.years_before),
                    "years_after": list(result.years_after),
                    "new_years": list(result.new_years),
                    "meetings_before": result.meetings_before,
                    "meetings_after": result.meetings_after,
                    "last_before": result.last_before.isoformat() if result.last_before else None,
                    "last_after": result.last_after.isoformat() if result.last_after else None,
                    "refused_reason": result.refused_reason,
                    "path": str(result.path),
                },
                indent=2,
            )
        )
    elif result.refused_reason is not None:
        print(f"REFUSED: {result.refused_reason}")
        print(f"  left alone: {result.path}")
    elif result.new_years:
        years = ", ".join(str(year) for year in result.new_years)
        verb = "would add" if args.check else "added"
        print(f"{verb} {years} ({result.meetings_before} -> {result.meetings_after} meetings)")
        if args.check:
            print(f"  run without --check to write {result.path}")
    elif result.written:
        print(f"updated {result.path} ({result.meetings_after} meetings, no new year)")
    else:
        last = result.last_after.isoformat() if result.last_after else "nothing"
        print(f"up to date: {result.meetings_after} meetings, last {last}")

    # A refusal is the one outcome a scheduled run must not swallow -- see refresh_bundled_schedule.
    return 1 if result.refused_reason is not None else 0


if __name__ == "__main__":  # pragma: no cover - the body is exercised through _main in tests
    raise SystemExit(_main())

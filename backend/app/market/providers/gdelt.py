"""GDELT global/macro news provider.

Everything comes off one endpoint: ``api.gdeltproject.org/api/v2/doc/doc``, queried with
``mode=artlist&format=json``. It is public and keyless -- verified live 2026-08-24, HTTP 200 JSON,
no registration required -- and it indexes global news coverage, searchable by free-text query. There
is no per-symbol endpoint on this API at all, which is why :meth:`GdeltProvider.fetch_symbol_news`
does not attempt one: a ticker like ``NVDA`` is not a GDELT query in any meaningful sense (it would
search for the literal three-letter string across global text, not "news about Nvidia"), and
returning whatever that search happens to match would look like real per-symbol coverage while
actually being noise. It raises :class:`~app.market.providers.base.UnsupportedQuery` instead, which
the registry skips silently and falls through to Yahoo -- the same treatment
:class:`~app.market.providers.base.UnsupportedInterval` gets from :class:`~app.market.providers.stooq.
StooqProvider` for the same reason: this is not a failure, it is the wrong question for this
upstream. :meth:`fetch_query_news` -- a free-text macro/topic query -- is GDELT's real surface.

**The throttle is the whole reason this module is not trivial, and it does not behave the way its
own message claims.** GDELT limits requests to roughly one every 5 seconds per IP. Verified directly
against the live endpoint while this module was written: a request sent 12 seconds after the
previous one *still* came back throttled, so the limit is stickier than "one every 5 seconds" and a
provider that sleeps 5 seconds and retries once is not actually safe. This module does not attempt to
pace requests itself (that is a caller/registry concern -- a provider is a stateless translator, per
``app.market.providers.base``); it exists to *detect* the throttle correctly and say so honestly via
:class:`~app.market.providers.base.RateLimited`, rather than mis-reporting it as a broken response.

Two traps in the throttled response are both captured in
``tests/fixtures/news/gdelt_rate_limited.txt`` (the real body, captured live):

1. **It carries no ``content-type`` header and a plain-text body.** Calling ``response.json()``
   straight on it raises ``JSONDecodeError``, not a clean, typed error -- so the throttle must be
   detected from the raw text *before* any JSON parsing is attempted, not by handling a parse
   failure after the fact.
2. **The HTTP status code is not reliable.** One live capture returned the throttle body on a 429,
   which looks self-explanatory, but nothing about this upstream guarantees a 429 shows up on every
   throttled call -- the message text is the only stable signal GDELT gives. This parser therefore
   scans the response body for the throttle marker *regardless of status code*, and only falls back
   to status-code handling once that check has cleared. Skipping this and keying off ``429`` alone
   would misclassify a throttle served on some other status as
   :class:`~app.market.providers.base.ProviderResponseError` -- which the registry also treats as
   retryable-elsewhere, but silently drops the ``retry_after`` hint and the honest "you are being
   throttled" explanation that :class:`RateLimited` alone carries.

A real 200 response is captured in ``tests/fixtures/news/gdelt_nvidia.json`` (10 articles, a genuine
live search). Each article carries exactly ``domain``, ``language``, ``seendate``, ``socialimage``,
``sourcecountry``, ``title``, ``url``, ``url_mobile``. Only four are used: ``title`` -> ``title``,
``url`` -> ``url``, ``domain`` -> ``publisher``, and ``seendate`` -> ``published``. ``seendate`` is a
compact timestamp with no separators (``"20260822T060000Z"``) -- it is *not* accepted by
``dt.datetime.fromisoformat`` on this Python version, so it is parsed explicitly with
``dt.datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.UTC)`` rather than assumed to be
ISO-8601-compatible because it looks close.

The User-Agent is an honest, contactable identity (``investing-dashboard/0.1``), never a spoofed
browser string -- and, unlike FRED (see ``app/market/providers/fred.py``), this is not a case where
spoofing would even help: the same live probe that found the 12-second throttle also compared an
honest UA against a Chrome-shaped one and got the identical throttled response from both. GDELT's
limiter keys on the requesting IP, not the UA string, so pretending to be a browser here buys
nothing and only makes the request dishonest.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Final

import httpx
from pydantic import ValidationError

from app.market.models import MarketWarning
from app.market.news_models import (
    NewsFeed,
    NewsItem,
    NewsVolumePoint,
    NewsVolumeSeries,
    published_before,
)
from app.market.providers.base import (
    ProviderResponseError,
    ProviderUnavailable,
    RateLimited,
    UnsupportedQuery,
)

logger = logging.getLogger(__name__)

__all__ = ["COVERAGE_START", "GdeltProvider"]

_URL: Final[str] = "https://api.gdeltproject.org/api/v2/doc/doc"

#: An honest, contactable identity -- never a spoofed browser string. See the module docstring:
#: GDELT's throttle is not UA-sensitive, so there is nothing to gain by pretending otherwise.
_USER_AGENT: Final[str] = "investing-dashboard/0.1"

#: GDELT's ``seendate`` format -- compact, no separators, always UTC (the trailing ``Z``).
_SEENDATE_FORMAT: Final[str] = "%Y%m%dT%H%M%SZ"

#: The compact timestamp the ``startdatetime``/``enddatetime`` range parameters take.
_RANGE_FORMAT: Final[str] = "%Y%m%d%H%M%S"

#: **The earliest day the DOC 2.0 API will answer for at all** -- not a guess, and not a number read
#: off GDELT's documentation. Established by bisection against the live endpoint on 2026-08-26:
#: ``2016-12-15`` returns the plain-text body ``"Invalid query start date."`` and ``2017-01-01``
#: returns JSON. ``2008-01-01``, ``2011-08-01`` and ``2014-01-01`` were all refused the same way.
#:
#: **This sits in the middle of the programme's window matrix, which is why it is a named constant
#: rather than an inline literal.** Of the eight windows in ``strategy-program/WINDOWS.md``, three --
#: ``gfc`` (2007-10-09), ``chop-2011`` and ``chop-2015`` -- end entirely before this date and can
#: never be answered by this upstream. Those are the deepest drawdown available and *both* sideways
#: windows, which ``WINDOWS.md`` calls "round 2's most important addition". Any study built on this
#: provider therefore runs on a structurally truncated matrix and must say so, rather than reporting
#: five windows as though the other three merely happened not to trigger. See
#: ``strategy-program/PHASE-D-NEWS-FEASIBILITY.md``.
#:
#: The refusal arrives as a **plain-text body**, exactly like the throttle does, so it is detected
#: from the text before any JSON parsing -- see :meth:`GdeltProvider._get_json`.
COVERAGE_START: Final[dt.date] = dt.date(2017, 1, 1)

#: A substring of the out-of-range response body (captured live 2026-08-26), matched
#: case-insensitively. Same trap as the throttle: plain text, no ``content-type``, and
#: ``response.json()`` on it raises ``JSONDecodeError`` rather than anything a caller can act on.
_OUT_OF_RANGE_MARKER: Final[str] = "invalid query start date"

#: A substring of the throttled response body (see ``tests/fixtures/news/gdelt_rate_limited.txt``),
#: matched case-insensitively. This is the *only* reliable signal that a response is a throttle --
#: see the module docstring for why the status code cannot be trusted.
_THROTTLE_MARKER: Final[str] = "limit requests to one every"

#: The shortest gap between requests this provider has been *observed* to tolerate -- deliberately
#: not the figure GDELT advertises.
#:
#: **The upstream's own error message asks for one request every 5 seconds. That figure is wrong, or
#: at least incomplete.** Measured live on 2026-08-24: a retry sent **12 seconds** after the previous
#: request was still throttled. Whatever the limiter is actually keying on -- a longer window, a
#: token bucket, IP reputation after a burst -- it is not a flat 5-second gap, so a constant copied
#: from the documentation would be more than 2x too aggressive and would look, from the outside,
#: exactly like the feed being broken.
#:
#: Nothing in this module enforces this today: the provider does not pace itself, because the shared
#: `app.market.cache.CachingTransport` already collapses repeat calls and a self-pacing provider
#: would block the caller's thread to do it. It is recorded here for whoever adds pacing -- most
#: likely `app.market.refresh`, whose sweep delay is per-symbol and uniform and would drag every
#: other source down to this one's speed if this were folded into the shared bucket. Give it its own.
#:
#: If you tune this, tune it from a fresh measurement, not from the vendor's claim.
_OBSERVED_MIN_INTERVAL_SECONDS: Final[float] = 12.0


def _is_throttled_body(text: str) -> bool:
    return _THROTTLE_MARKER in text.lower()


def _parse_article(article: Any, *, provider: str) -> NewsItem | None:
    """One article, or ``None`` when this row cannot be trusted.

    **A bad row is dropped, not raised.** The distinction this codebase draws -- see
    :mod:`app.market.providers.base`'s docstring on Stooq's challenge page -- is between a malformed
    *payload*, which must raise because treating it as empty would report "no news" for a query with
    plenty, and a malformed *row* inside an otherwise well-formed payload, which is dropped for the
    same reason :class:`~app.market.providers.base.BarProvider` drops a null-OHLC bar: an invented
    value is worse than a gap. Raising here let one undateable article destroy the other ninety-nine
    and fall the whole chain through to Reddit.

    An article with an unparseable ``seendate`` is exactly the row that must not be kept: this feed is
    bounded by :func:`~app.market.news_models.published_before`, and an item whose publication time is
    unknown cannot be bounded at all. Dropping it is the only answer that keeps the look-ahead guard
    meaningful.

    The caller is responsible for noticing that *every* row was dropped -- see
    :meth:`GdeltProvider.fetch_query_news`, which treats that as the schema change it almost certainly
    is rather than as an empty result.
    """
    if not isinstance(article, dict):
        return None

    title = article.get("title")
    url = article.get("url")
    seendate = article.get("seendate")
    if not isinstance(title, str) or not isinstance(url, str) or not isinstance(seendate, str):
        return None

    try:
        published = dt.datetime.strptime(seendate, _SEENDATE_FORMAT).replace(tzinfo=dt.UTC)
    except ValueError:
        return None

    domain = article.get("domain")
    publisher = domain if isinstance(domain, str) and domain else None

    try:
        return NewsItem(
            title=title,
            url=url,
            published=published,
            source=provider,
            publisher=publisher,
            summary=None,
        )
    except ValidationError as exc:
        # A `url` with a scheme other than http(s) -- see `NewsItem.url`'s own docstring. Dropped
        # like any other malformed row this function already returns `None` for above, not raised:
        # one bad article must not take down the other ninety-nine.
        logger.debug("gdelt: dropping article with invalid url %r: %s", url, exc)
        return None


def _parse_volume_point(row: Any) -> NewsVolumePoint | None:
    """One ``timelinevolraw`` bucket, or ``None`` if it is not usable.

    Returns ``None`` rather than raising for the same reason :func:`_parse_article` does: one
    malformed bucket in a year of them is not a reason to lose the year. The caller counts what it
    dropped and refuses only when *everything* dropped, which is the signal that the schema moved.

    ``date`` is the same compact format ``seendate`` uses (``"20240101T000000Z"``) and is parsed with
    the same explicit ``strptime`` -- ``dt.datetime.fromisoformat`` does not accept it. Only the date
    part survives: see :class:`~app.market.news_models.NewsVolumePoint` for why a daily bucket must
    not be typed as an instant.
    """
    if not isinstance(row, dict):
        return None
    raw_date = row.get("date")
    if not isinstance(raw_date, str):
        return None
    try:
        stamp = dt.datetime.strptime(raw_date, _SEENDATE_FORMAT)
    except ValueError:
        return None

    matched = row.get("value")
    indexed_total = row.get("norm", 0)
    if not isinstance(matched, (int, float)) or isinstance(matched, bool):
        return None
    if not isinstance(indexed_total, (int, float)) or isinstance(indexed_total, bool):
        indexed_total = 0
    if matched < 0 or indexed_total < 0:
        return None

    return NewsVolumePoint(
        day=stamp.date(), matched=int(matched), indexed_total=int(indexed_total)
    )


class GdeltProvider:
    """Global news search from GDELT's ``doc/doc`` API. See the module docstring before wiring this up."""

    name = "gdelt"

    def __init__(self, client: httpx.Client | None = None, *, timeout: float = 20.0) -> None:
        self._client = client or httpx.Client(timeout=timeout)

    def fetch_symbol_news(
        self, symbol: str, *, limit: int = 20, as_of: dt.datetime | None = None
    ) -> NewsFeed:
        """Always raises. See the module docstring -- GDELT has no per-ticker endpoint."""
        raise UnsupportedQuery(
            f"gdelt has no per-ticker endpoint; {symbol!r} is not a meaningful GDELT query -- use "
            "fetch_query_news with a topic or macro query instead",
            provider=self.name,
        )

    def fetch_query_news(
        self, query: str, *, limit: int = 20, as_of: dt.datetime | None = None
    ) -> NewsFeed:
        if not query or not query.strip():
            raise UnsupportedQuery(
                "gdelt requires a non-empty free-text query", provider=self.name
            )

        try:
            response = self._client.get(
                _URL,
                params={
                    "query": query,
                    "mode": "artlist",
                    "format": "json",
                    "maxrecords": limit,
                },
                headers={"User-Agent": _USER_AGENT},
            )
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(
                f"gdelt timed out fetching query {query!r}", provider=self.name
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(
                f"gdelt transport error fetching query {query!r}: {exc}", provider=self.name
            ) from exc

        # Checked first and unconditionally, before any status-code branching: the throttled body
        # has shown up on both 200 and 429 in live captures, so the status code alone cannot be
        # trusted to detect it. See the module docstring.
        if _is_throttled_body(response.text):
            retry_after = response.headers.get("Retry-After")
            raise RateLimited(
                f"gdelt rate-limited the request for query {query!r}",
                provider=self.name,
                retry_after=float(retry_after) if retry_after else None,
            )

        if response.status_code >= 500:
            raise ProviderUnavailable(
                f"gdelt returned {response.status_code} for query {query!r}", provider=self.name
            )
        if response.status_code >= 400:
            raise ProviderResponseError(
                f"gdelt returned unexpected status {response.status_code} for query {query!r}",
                provider=self.name,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                f"gdelt response for query {query!r} was not valid JSON", provider=self.name
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderResponseError(
                f"gdelt response for query {query!r} was not a JSON object", provider=self.name
            )

        articles = payload.get("articles", [])
        if not isinstance(articles, list):
            raise ProviderResponseError(
                f"gdelt response for query {query!r} has a non-list 'articles' field",
                provider=self.name,
            )

        parsed = tuple(_parse_article(article, provider=self.name) for article in articles)
        items = tuple(item for item in parsed if item is not None)

        # Every row dropped, from a non-empty list, is not "no news" -- it is the schema having moved
        # under us. Reporting it as an empty feed is the Stooq failure this package's base module
        # opens by warning about: a well-formed-looking answer that quietly says nothing exists.
        if articles and not items:
            raise ProviderResponseError(
                f"gdelt returned {len(articles)} article(s) for query {query!r} and none carried a "
                "usable title, url and seendate -- the response schema has probably changed",
                provider=self.name,
            )

        dropped = len(parsed) - len(items)
        warnings = (
            (
                MarketWarning(
                    kind="partial_parse",
                    message=(
                        f"gdelt: {dropped} of {len(parsed)} articles for {query!r} lacked a usable "
                        "title, url or seendate and were dropped"
                    ),
                ),
            )
            if dropped
            else ()
        )

        return NewsFeed(
            items=published_before(items, as_of),
            source=self.name,
            as_of=as_of,
            warnings=warnings,
        )

    def fetch_volume_series(self, query: str, *, start: dt.date, end: dt.date) -> NewsVolumeSeries:
        """Daily article counts for ``query`` between ``start`` and ``end``, both ends inclusive.

        This is the historical surface :meth:`fetch_query_news` deliberately does not have. The
        article list is a *live* endpoint -- it answers "what is being said now" and cannot be asked
        about 2018 -- whereas ``mode=timelinevolraw`` accepts ``startdatetime``/``enddatetime`` and
        returns one bucket per day. That difference is the whole reason
        ``strategy-program/AGENTS-INTEGRATION-PLAN.md`` splits Phase D into a runnable D-news and a
        blocked D-social: news has a queryable history and social does not.

        **A request starting before :data:`COVERAGE_START` is clamped, not refused.** Refusing would
        be defensible, but it would make the intended caller -- "run this study across the window
        matrix" -- raise on three of eight windows, and the natural way to write that caller is a
        ``try/except`` that swallows the window silently. Putting the gap *in the result* instead,
        as ``requested_start_before_coverage``, means a study has to either report it or actively
        discard it. That is the call :func:`app.market.social_history.read_range` already makes, and
        it is made here for the stronger reason: this boundary is fixed and permanent, so a caller
        meets it on every single run rather than only until the store fills up.

        A window ending entirely before ``COVERAGE_START`` returns no points and is not a failure --
        it is that window being unanswerable, reported as such.
        """
        if not query or not query.strip():
            raise UnsupportedQuery("gdelt requires a non-empty free-text query", provider=self.name)
        if end < start:
            raise UnsupportedQuery(
                f"gdelt volume series needs start <= end, got {start} .. {end}",
                provider=self.name,
            )

        if end < COVERAGE_START:
            # Nothing askable. Returning before sending a request GDELT would refuse keeps the
            # caller off the 5-second throttle for a window that can never be answered anyway.
            return NewsVolumeSeries(
                query=query,
                source=self.name,
                points=(),
                coverage_start=COVERAGE_START,
                requested_start=start,
            )

        effective_start = max(start, COVERAGE_START)
        payload = self._get_json(
            {
                "query": query,
                "mode": "timelinevolraw",
                "format": "json",
                "startdatetime": dt.datetime.combine(effective_start, dt.time.min).strftime(
                    _RANGE_FORMAT
                ),
                # End of the requested day, so an inclusive-looking range really is inclusive.
                "enddatetime": dt.datetime.combine(end, dt.time.max).strftime(_RANGE_FORMAT),
            },
            what=f"volume series for {query!r}",
        )

        timeline = payload.get("timeline", [])
        if not isinstance(timeline, list):
            raise ProviderResponseError(
                f"gdelt volume series for {query!r} has a non-list 'timeline' field",
                provider=self.name,
            )

        rows: list[Any] = []
        for series in timeline:
            if isinstance(series, dict) and isinstance(series.get("data"), list):
                rows.extend(series["data"])

        points = tuple(
            point for point in (_parse_volume_point(row) for row in rows) if point is not None
        )

        # Same reasoning as `fetch_query_news`'s all-dropped guard: buckets that arrived and all
        # failed to parse is a schema change, not a quiet fortnight.
        if rows and not points:
            raise ProviderResponseError(
                f"gdelt returned {len(rows)} volume bucket(s) for {query!r} and none carried a "
                "usable date and value -- the response schema has probably changed",
                provider=self.name,
            )

        return NewsVolumeSeries(
            query=query,
            source=self.name,
            points=tuple(sorted(points, key=lambda point: point.day)),
            coverage_start=COVERAGE_START,
            requested_start=start,
        )

    def _get_json(self, params: dict[str, Any], *, what: str) -> dict[str, Any]:
        """One GET, with every failure this upstream is known to produce turned into a typed error.

        Extracted so :meth:`fetch_volume_series` inherits the throttle detection
        :meth:`fetch_query_news` already had rather than reimplementing it -- the module docstring's
        two traps (plain-text body, unreliable status code) apply identically to both endpoints, and
        a second hand-rolled copy of that logic is how one of them ends up fixed and the other not.
        """
        try:
            response = self._client.get(_URL, params=params, headers={"User-Agent": _USER_AGENT})
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(
                f"gdelt timed out fetching {what}", provider=self.name
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(
                f"gdelt transport error fetching {what}: {exc}", provider=self.name
            ) from exc

        # Checked first and unconditionally, before any status-code branching -- see the module
        # docstring. Both of these bodies arrive as plain text on a status code that cannot be
        # trusted to identify them.
        if _is_throttled_body(response.text):
            retry_after = response.headers.get("Retry-After")
            raise RateLimited(
                f"gdelt rate-limited the request for {what}",
                provider=self.name,
                retry_after=float(retry_after) if retry_after else None,
            )
        if _OUT_OF_RANGE_MARKER in response.text.lower():
            raise ProviderResponseError(
                f"gdelt refused {what} as out of range -- its archive begins {COVERAGE_START}; "
                "this should have been clamped before the request was sent",
                provider=self.name,
            )

        if response.status_code >= 500:
            raise ProviderUnavailable(
                f"gdelt returned {response.status_code} for {what}", provider=self.name
            )
        if response.status_code >= 400:
            raise ProviderResponseError(
                f"gdelt returned unexpected status {response.status_code} for {what}",
                provider=self.name,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                f"gdelt response for {what} was not valid JSON", provider=self.name
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderResponseError(
                f"gdelt response for {what} was not a JSON object", provider=self.name
            )
        return payload

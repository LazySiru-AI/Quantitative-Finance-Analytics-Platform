"""Yahoo Finance per-symbol and free-text news provider.

Everything comes off one endpoint: ``query1.finance.yahoo.com/v1/finance/search``. It is the same
search box Yahoo Finance's own site uses (type a ticker or a phrase, get quotes *and* news back), and
it is public and keyless -- verified live 2026-08-24, ``GET .../v1/finance/search?
q={SYMBOL}&newsCount=N&quotesCount=0``, HTTP 200, JSON, no auth header required. The response carries
many top-level keys this module never reads (``explains``, ``quotes``, ``nav``, ``lists``,
``researchReports``, and a pile of ``timeTakenFor*`` timing fields) -- the only one that matters here
is ``news``, a flat list of article stubs. The captured fixture is
``tests/fixtures/news/yahoo_news_nvda.json``, ten NVDA-related stories trimmed from a live response.

**The parsing trap this module exists to guard against.** Each news entry's timestamp field is
``providerPublishTime``, and it is a **Unix epoch integer in seconds** (``1787590870``), not an
ISO-8601 string the way most of this codebase's other JSON timestamps arrive. The obvious-looking
call is ``dt.datetime.utcfromtimestamp(value)`` -- it is wrong twice over: it returns a *naive*
datetime, which fails :class:`~app.market.news_models.NewsItem`'s frozen, always-tz-aware contract on
construction, and this repository's pytest configuration turns the ``DeprecationWarning``
``utcfromtimestamp`` now carries into a hard test failure before the mistake even gets that far. The
correct conversion, used throughout, is ``dt.datetime.fromtimestamp(value, tz=dt.UTC)``.

There is no summary field on this endpoint at all -- Yahoo's search results carry a title, a
publisher, a link and a timestamp, nothing else. ``NewsItem.summary`` is therefore always ``None``
here, never synthesised from the title or fetched from a second request; per
:class:`~app.market.news_models.NewsItem`'s own docstring, a missing field stays missing rather than
being dressed up as data the upstream did not provide.

Every parsed item is routed through :func:`app.market.news_models.published_before` before this
module returns anything. See that function's docstring for the failure it exists to prevent: an
article published the afternoon of a move, left in a window meant to predict the move, is a
look-ahead bug that is invisible in the output and real in a backtest's returns.

Unlike the bars/profile :class:`~app.market.providers.yahoo.YahooProvider`, which talks to the chart
endpoint and deliberately avoids the crumb-and-cookie-gated ``quoteSummary`` surface, this module's
search endpoint is a different, simpler surface with its own contract -- it is not a variant of the
chart provider and shares no code with it beyond the symbol-spelling helper
(:func:`app.market.providers.base.provider_symbol`).

The search endpoint also accepts free text, not just tickers -- searching "Fed rate cut" returns
whatever news Yahoo's index matches against that phrase the same way it would against "NVDA" -- so
:meth:`YahooNewsProvider.fetch_query_news` is implemented rather than raising
:class:`~app.market.providers.base.UnsupportedQuery` for every call. It raises that error only for an
empty query, which is not a query at all.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Final

import httpx
from pydantic import ValidationError

from app.market.models import MarketWarning
from app.market.news_models import NewsFeed, NewsItem, published_before
from app.market.providers.base import (
    ProviderResponseError,
    ProviderUnavailable,
    RateLimited,
    SymbolNotFound,
    UnsupportedQuery,
    provider_symbol,
)

__all__ = ["YahooNewsProvider"]

_URL: Final[str] = "https://query1.finance.yahoo.com/v1/finance/search"

logger = logging.getLogger(__name__)

#: Honest, not a spoofed browser string -- see `app/market/providers/fred.py`'s module docstring for
#: why: a Chrome-shaped User-Agent is exactly the pattern that gets a keyless client blocked, not a
#: way to blend in safely. Do not "fix" this to look more like a browser.
_USER_AGENT: Final[str] = "investing-dashboard/0.1"


def _parse_published(raw: Any) -> dt.datetime | None:
    """``providerPublishTime`` as a tz-aware UTC instant, or ``None`` if it is not a usable number.

    **The trap this function exists to close.** The field is a Unix epoch integer in *seconds*
    (``1787590870``), not an ISO string. ``dt.datetime.fromtimestamp(value, tz=dt.UTC)`` is the only
    conversion used -- never ``utcfromtimestamp``, which returns a naive datetime that fails
    :class:`~app.market.news_models.NewsItem`'s frozen, always-aware contract and trips this
    repository's ``filterwarnings = error::DeprecationWarning`` before that failure is even reached.
    ``bool`` is excluded even though it is technically an ``int`` subclass, the same guard
    :func:`app.market.providers.cnn._is_finite_number` uses for the same reason.
    """
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return None
    return dt.datetime.fromtimestamp(raw, tz=dt.UTC)


class YahooNewsProvider:
    """Per-symbol and free-text news from Yahoo's public search endpoint. See the module docstring."""

    name = "yahoo_news"

    def __init__(self, client: httpx.Client | None = None, *, timeout: float = 15.0) -> None:
        self._client = client or httpx.Client(timeout=timeout)

    # -- HTTP + error mapping -------------------------------------------------

    def _search(self, q: str, *, limit: int, identifier: str) -> dict[str, Any]:
        """Fetch one search response and return the parsed JSON object.

        ``identifier`` is what error messages name -- the caller's original symbol or query, not
        necessarily ``q`` itself, so a message always names what the caller actually asked for.
        """
        try:
            response = self._client.get(
                _URL,
                params={"q": q, "newsCount": str(limit), "quotesCount": "0"},
                headers={"User-Agent": _USER_AGENT},
            )
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(
                f"yahoo news timed out searching for {identifier!r}", provider=self.name
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(
                f"yahoo news transport error searching for {identifier!r}: {exc}",
                provider=self.name,
            ) from exc

        if response.status_code == 404:
            raise SymbolNotFound(
                f"yahoo news search returned 404 for {identifier!r}", provider=self.name
            )
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimited(
                f"yahoo news rate-limited the search for {identifier!r}",
                provider=self.name,
                retry_after=float(retry_after) if retry_after else None,
            )
        if response.status_code >= 500:
            raise ProviderUnavailable(
                f"yahoo news returned {response.status_code} for {identifier!r}",
                provider=self.name,
            )
        if response.status_code >= 400:
            raise ProviderResponseError(
                f"yahoo news returned unexpected status {response.status_code} for {identifier!r}",
                provider=self.name,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                f"yahoo news response for {identifier!r} was not valid JSON", provider=self.name
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderResponseError(
                f"yahoo news response for {identifier!r} was not a JSON object", provider=self.name
            )
        return payload

    # -- Parsing ----------------------------------------------------------------

    def _parse_items(self, payload: dict[str, Any], identifier: str) -> tuple[
        list[NewsItem], list[MarketWarning]
    ]:
        news = payload.get("news")
        if news is None:
            # Yahoo does this for obscure tickers and for queries with no matches: the key is
            # simply absent, not present-and-empty. An explained absence, not a failure -- see
            # `FundamentalsProvider`'s docstring in `app/market/providers/base.py` for the same
            # convention applied to "no fundamentals filed".
            return [], [
                MarketWarning(
                    kind="missing_news",
                    message=f"yahoo news search for {identifier!r} had no 'news' list in the "
                    "response",
                )
            ]
        if not isinstance(news, list):
            raise ProviderResponseError(
                f"yahoo news 'news' field for {identifier!r} was not a list", provider=self.name
            )

        items: list[NewsItem] = []
        for entry in news:
            if not isinstance(entry, dict):
                continue
            title = entry.get("title")
            url = entry.get("link")
            published = _parse_published(entry.get("providerPublishTime"))
            if not isinstance(title, str) or not isinstance(url, str) or published is None:
                # A stub missing a title, link or usable timestamp cannot be rendered as a
                # NewsItem -- dropped rather than invented, the same rule Yahoo's own bar provider
                # applies to a halted session's null OHLC row.
                continue
            publisher = entry.get("publisher")
            try:
                item = NewsItem(
                    title=title,
                    url=url,
                    published=published,
                    source=self.name,
                    publisher=publisher if isinstance(publisher, str) else None,
                    summary=None,
                )
            except ValidationError as exc:
                # A `url` with a scheme other than http(s) -- see `NewsItem.url`'s own docstring on
                # why that must never reach the frontend as a clickable link. One bad row is dropped
                # rather than raised, the same rule this module already applies to a stub missing a
                # title, link, or usable timestamp just above: one malformed article must not cost
                # the caller the other nine.
                logger.debug(
                    "yahoo news: dropping item with invalid url %r for %r: %s", url, identifier, exc
                )
                continue
            items.append(item)

        items.sort(key=lambda item: item.published, reverse=True)
        return items, []

    def _feed(
        self, q: str, *, limit: int, as_of: dt.datetime | None, identifier: str
    ) -> NewsFeed:
        payload = self._search(q, limit=limit, identifier=identifier)
        items, warnings = self._parse_items(payload, identifier)
        # `published_before` is the look-ahead guard, applied before the limit is enforced so a
        # bounded feed's count reflects only articles actually visible as of `as_of` -- capping
        # first could hand back N items with none of them past the bound rather than a genuinely
        # empty answer.
        bounded = published_before(items, as_of)
        return NewsFeed(
            items=tuple(bounded[:limit]),
            source=self.name,
            as_of=as_of,
            warnings=tuple(warnings),
        )

    # -- NewsProvider ------------------------------------------------------

    def fetch_symbol_news(
        self, symbol: str, *, limit: int = 20, as_of: dt.datetime | None = None
    ) -> NewsFeed:
        requested = provider_symbol(symbol)
        return self._feed(requested, limit=limit, as_of=as_of, identifier=symbol)

    def fetch_query_news(
        self, query: str, *, limit: int = 20, as_of: dt.datetime | None = None
    ) -> NewsFeed:
        stripped = query.strip()
        if not stripped:
            raise UnsupportedQuery(
                "yahoo news search requires a non-empty query", provider=self.name
            )
        return self._feed(stripped, limit=limit, as_of=as_of, identifier=stripped)

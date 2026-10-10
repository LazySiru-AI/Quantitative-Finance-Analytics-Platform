"""Reddit search-RSS news provider.

Reddit exposes two ways to search a subreddit: a JSON endpoint
(``https://www.reddit.com/r/{sub}/search.json``) and an Atom feed
(``https://www.reddit.com/r/{sub}/search.rss``). Only the second one is usable here. Verified live
2026-08-24: the JSON endpoint answers a public client (no OAuth token, no registered app) with
**HTTP 403 Blocked**, every time, regardless of ``User-Agent``. The RSS/Atom endpoint answers the
identical query with HTTP 200 and a proper ``application/atom+xml`` body, no key or token required.
There is no header or retry that unlocks the JSON path short of registering an OAuth application,
which is out of scope for a read-only news provider -- so this module speaks Atom only, and does not
attempt the JSON endpoint at all. ``tests/fixtures/news/reddit_nvda.xml`` is a real captured response
from ``r/wallstreetbets/search.rss?q=NVDA&restrict_sr=1&sort=new&limit=8``.

**This has a direct consequence for what this provider can honestly report.** Reddit's own JSON API
carries a post's score (net upvotes) and comment count -- the numbers an "engagement-weighted" news
feed would want. The Atom feed carries neither. There is no ``<reddit:score>`` extension element, no
comment total anywhere in ``<entry>``, nothing to fall back to. A provider that invented a score here
-- guessed from post age, or backfilled with a constant -- would be fabricating a number and handing
it to a caller with no way to tell it apart from a real one. So this module reports presence and
timing only: that a post matching the query exists in a given subreddit, and when it was published.
No score, no comment count, no vote ratio. ``NewsItem.summary`` is left ``None`` for the same reason
the module docstring in ``app.market.news_models`` calls out Reddit by name: the feed's ``<content>``
is the post's self-text wrapped in a `<table>` of thumbnail/author/permalink markup (see the fixture),
not a clean summary, and rendering it as one would put raw HTML scaffolding in front of a reader
expecting prose.

Three subreddits are searched by default -- ``wallstreetbets``, ``stocks``, ``investing`` -- chosen
because they are the general-purpose US equity discussion boards with enough post volume that a
single-ticker or free-text query returns something most of the time. This is a starting point, not a
claim that it is the right set for every caller, so it is a constructor argument
(:data:`DEFAULT_SUBREDDITS`) rather than baked into the request path.

Every request carries an honest ``User-Agent`` (``investing-dashboard/0.1``), never a spoofed browser
string -- the same rule ``app.market.providers.fred`` documents, and for the same reason: an upstream
that tarpits browser-looking traffic from unrecognised clients punishes impersonation, not honesty.
"""

from __future__ import annotations

import datetime as dt
import logging
import xml.etree.ElementTree as ET
from typing import Final

import httpx
from pydantic import ValidationError

from app.market.news_models import NewsFeed, NewsItem, published_before
from app.market.providers.base import (
    ProviderResponseError,
    ProviderUnavailable,
    RateLimited,
    UnsupportedQuery,
)

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_SUBREDDITS", "RedditProvider"]

_ATOM_NS: Final[str] = "http://www.w3.org/2005/Atom"
_FEED_TAG: Final[str] = f"{{{_ATOM_NS}}}feed"
_ENTRY_TAG: Final[str] = f"{{{_ATOM_NS}}}entry"
_TITLE_TAG: Final[str] = f"{{{_ATOM_NS}}}title"
_LINK_TAG: Final[str] = f"{{{_ATOM_NS}}}link"
_PUBLISHED_TAG: Final[str] = f"{{{_ATOM_NS}}}published"
_UPDATED_TAG: Final[str] = f"{{{_ATOM_NS}}}updated"

_USER_AGENT: Final[str] = "investing-dashboard/0.1"
_SEARCH_URL_TEMPLATE: Final[str] = "https://www.reddit.com/r/{subreddit}/search.rss"

#: The subreddits searched when a caller does not supply its own set. See the module docstring for
#: why these three and not the JSON endpoint's richer (but 403-blocked) alternative.
DEFAULT_SUBREDDITS: Final[tuple[str, ...]] = ("wallstreetbets", "stocks", "investing")


class RedditProvider:
    """Post titles and timestamps from Reddit's search-RSS, across a fixed set of subreddits.

    See the module docstring before touching the parser or adding a field: the JSON endpoint that
    would carry score/comment-count is blocked for public clients, so this provider can only ever
    report what the Atom feed actually contains.
    """

    name = "reddit"

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        timeout: float = 15.0,
        subreddits: tuple[str, ...] = DEFAULT_SUBREDDITS,
    ) -> None:
        self._client = client or httpx.Client(timeout=timeout)
        self._subreddits = subreddits

    def fetch_symbol_news(
        self, symbol: str, *, limit: int = 20, as_of: dt.datetime | None = None
    ) -> NewsFeed:
        symbol = symbol.strip()
        if not symbol:
            raise UnsupportedQuery(
                "reddit requires a non-empty symbol to search for", provider=self.name
            )
        return self._search(symbol, limit=limit, as_of=as_of)

    def fetch_query_news(
        self, query: str, *, limit: int = 20, as_of: dt.datetime | None = None
    ) -> NewsFeed:
        query = query.strip()
        if not query:
            raise UnsupportedQuery(
                "reddit requires a non-empty query to search for", provider=self.name
            )
        return self._search(query, limit=limit, as_of=as_of)

    # -- Internals --------------------------------------------------------------

    def _search(self, query: str, *, limit: int, as_of: dt.datetime | None) -> NewsFeed:
        # Validate `as_of` before making any HTTP request at all -- a naive bound is a caller bug,
        # and there is no reason to pay for three subreddit fetches before reporting it. This reuses
        # the canonical validator on an empty tuple rather than re-deriving its tzinfo check, so the
        # error message and behaviour stay in exactly one place.
        published_before((), as_of)

        items: list[NewsItem] = []
        for subreddit in self._subreddits:
            items.extend(self._fetch_subreddit(subreddit, query, limit=limit))

        items.sort(key=lambda item: item.published, reverse=True)
        bounded = published_before(items, as_of)
        return NewsFeed(items=bounded[:limit], source=self.name, as_of=as_of)

    def _fetch_subreddit(self, subreddit: str, query: str, *, limit: int) -> list[NewsItem]:
        url = _SEARCH_URL_TEMPLATE.format(subreddit=subreddit)
        params = {"q": query, "restrict_sr": "1", "sort": "new", "limit": str(limit)}

        try:
            response = self._client.get(url, params=params, headers={"User-Agent": _USER_AGENT})
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(
                f"reddit timed out searching r/{subreddit} for {query!r}", provider=self.name
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(
                f"reddit transport error searching r/{subreddit} for {query!r}: {exc}",
                provider=self.name,
            ) from exc

        if response.status_code == 403:
            # Public clients get blocked on the JSON endpoint; if the RSS endpoint ever starts doing
            # the same, it is an outage of this provider, not evidence the subreddit or query is
            # invalid -- retryable elsewhere, so ProviderUnavailable rather than anything terminal.
            raise ProviderUnavailable(
                f"reddit blocked the search-RSS request for r/{subreddit} (403)", provider=self.name
            )
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimited(
                f"reddit rate-limited the search for r/{subreddit}",
                provider=self.name,
                retry_after=float(retry_after) if retry_after else None,
            )
        if response.status_code >= 500:
            raise ProviderUnavailable(
                f"reddit returned {response.status_code} for r/{subreddit}", provider=self.name
            )
        if response.status_code >= 400:
            raise ProviderResponseError(
                f"reddit returned unexpected status {response.status_code} for r/{subreddit}",
                provider=self.name,
            )

        return self._parse_atom(response.text, subreddit)

    def _parse_atom(self, text: str, subreddit: str) -> list[NewsItem]:
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise ProviderResponseError(
                f"reddit r/{subreddit} response was not valid XML: {exc}", provider=self.name
            ) from exc

        if root.tag != _FEED_TAG:
            raise ProviderResponseError(
                f"reddit r/{subreddit} response was not an Atom feed (root tag {root.tag!r})",
                provider=self.name,
            )

        items: list[NewsItem] = []
        for entry in root.findall(_ENTRY_TAG):
            item = self._parse_entry(entry, subreddit)
            if item is not None:
                items.append(item)
        return items

    def _parse_entry(self, entry: ET.Element, subreddit: str) -> NewsItem | None:
        title_el = entry.find(_TITLE_TAG)
        link_el = entry.find(_LINK_TAG)
        published_el = entry.find(_PUBLISHED_TAG)
        updated_el = entry.find(_UPDATED_TAG)

        if title_el is None or not title_el.text:
            return None
        url = link_el.get("href") if link_el is not None else None
        if not url:
            return None

        timestamp_text = (published_el.text if published_el is not None else None) or (
            updated_el.text if updated_el is not None else None
        )
        if not timestamp_text:
            return None
        try:
            published = dt.datetime.fromisoformat(timestamp_text).astimezone(dt.UTC)
        except ValueError:
            return None

        try:
            return NewsItem(
                title=title_el.text,
                url=url,
                published=published,
                source=self.name,
                publisher=f"r/{subreddit}",
            )
        except ValidationError as exc:
            # A `url` with a scheme other than http(s) -- see `NewsItem.url`'s own docstring. Dropped
            # like any other unparseable entry this function already returns `None` for above: one
            # bad post must not cost the caller every other result from this subreddit.
            logger.debug("reddit: dropping entry with invalid url %r in r/%s: %s", url, subreddit, exc)
            return None

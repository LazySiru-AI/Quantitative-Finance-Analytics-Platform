"""The provider contract and its error vocabulary.

A provider is a thin, stateless translator: HTTP in, :mod:`app.market.models` shapes out. It does
not cache, retry across providers, or decide what to do when it fails -- the registry does that,
and it can only do it if failures are *typed*. The distinction that matters most is between
:class:`SymbolNotFound` (trying another provider is pointless; the ticker does not exist) and
:class:`ProviderUnavailable` (trying another provider is exactly the right move). A registry that
cannot tell those apart either gives up too early or hammers every provider for every typo.

Parsing failures are :class:`ProviderResponseError`, and they must be *raised, not tolerated*.
Stooq currently answers a CSV request with an HTML anti-bot challenge carrying HTTP 200. Treating
that as an empty series would report "no history" for a ticker with thirty years of it.
"""

from __future__ import annotations

import datetime as dt
from typing import Protocol, runtime_checkable

import pandas as pd

from app.market.models import Interval, Profile, Quote
from app.market.news_models import EventMarket, NewsFeed, SocialSnapshot

__all__ = [
    "BarProvider",
    "EventProvider",
    "FundamentalsProvider",
    "NewsProvider",
    "ProfileProvider",
    "ProviderError",
    "ProviderResponseError",
    "ProviderUnavailable",
    "RateLimited",
    "SocialProvider",
    "SymbolNotFound",
    "UnsupportedInterval",
    "UnsupportedQuery",
]


class ProviderError(Exception):
    """Base for every provider failure. Carries the provider name for the warning text."""

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message)
        self.provider = provider


class SymbolNotFound(ProviderError):
    """The upstream is healthy and says this symbol does not exist.

    **Terminal.** The registry must not fall through to the next provider: a delisted or mistyped
    ticker is not going to be found by asking somewhere else, and pretending otherwise turns one
    fast 404 into a slow walk through every provider in the chain.
    """


class ProviderUnavailable(ProviderError):
    """Network failure, timeout, 5xx, or a bot challenge. **Retryable elsewhere** -- fall through."""


class RateLimited(ProviderUnavailable):
    """Explicit throttling. Carries ``retry_after`` seconds when the upstream supplies one."""

    def __init__(self, message: str, *, provider: str, retry_after: float | None = None) -> None:
        super().__init__(message, provider=provider)
        self.retry_after = retry_after


class ProviderResponseError(ProviderUnavailable):
    """The response arrived but is not what this provider's parser understands.

    Deliberately a subclass of :class:`ProviderUnavailable`: an upstream serving a challenge page or
    a changed schema is, from the registry's point of view, down.
    """


class UnsupportedQuery(ProviderError):
    """This provider does not answer that *kind* of question at all.

    The news analogue of :class:`UnsupportedInterval`, and skipped by the registry the same way:
    GDELT indexes global coverage and has no per-ticker endpoint, Yahoo's search serves per-symbol
    news and is a poor macro surface. Neither is a failure of the request or something the reader can
    fix, so neither should surface as a warning.
    """


class UnsupportedInterval(ProviderError):
    """This provider does not serve that interval at all -- Stooq has no intraday, for instance.

    Not a failure of the request, so the registry skips this provider silently rather than
    surfacing a warning the user can do nothing about.
    """


@runtime_checkable
class BarProvider(Protocol):
    """Fetches OHLCV history for one symbol at one interval."""

    name: str
    """Matches a :class:`~app.market.models.BarSource` value."""

    supported_intervals: frozenset[Interval]

    def fetch_bars(
        self,
        symbol: str,
        interval: Interval,
        *,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> pd.DataFrame:
        """Return a frame with exactly :data:`~app.market.models.BAR_COLUMNS`, ascending by ``ts``.

        Requirements every implementation must meet, because the store trusts them:

        * ``ts`` is tz-aware UTC. Daily and weekly bars are normalised to the *exchange-local*
          session date at midnight UTC (:func:`~app.market.models.session_date`); intraday bars keep
          the true instant.
        * ``adj_close`` is present as a column even when the provider supplies no adjusted series --
          ``NaN`` in that case, never a copy of ``close``, which would make a total-return study
          silently equal a price-return one.
        * Rows the provider returns with a null OHLC -- it does this for halted sessions -- are
          dropped, not forward-filled. An invented bar is worse than a gap.
        * **Bars for sessions that have not closed are excluded.** They are not final and would be
          persisted as though they were. See :mod:`app.market.models`.
        * An empty frame with the right columns is a valid answer, meaning "this symbol has no bars
          in that window". Not finding the *symbol* is :class:`SymbolNotFound`.
        """
        ...


@runtime_checkable
class ProfileProvider(Protocol):
    """Identity and a last-price snapshot."""

    name: str

    def fetch_profile(self, symbol: str) -> Profile: ...

    def fetch_quote(self, symbol: str) -> Quote: ...


@runtime_checkable
class FundamentalsProvider(Protocol):
    """Reported financials. SEC EDGAR is the only implementation, and it covers US filers only.

    Most of this portfolio is ETFs, which file nothing on this endpoint. "No fundamentals" is
    therefore the *common* case, and must render as an explained absence rather than an error.
    """

    name: str

    def fetch_fundamentals(self, symbol: str) -> object: ...


@runtime_checkable
class NewsProvider(Protocol):
    """Headlines for one symbol, or for the market as a whole.

    Two methods rather than one because the two questions have different shapes: a per-symbol feed is
    keyed on a ticker this codebase can validate, while a macro feed is keyed on a free-text query
    nobody can. A provider that only serves one of them raises
    :class:`UnsupportedQuery` from the other, which the registry skips silently -- the same treatment
    :class:`UnsupportedInterval` gets, and for the same reason: "GDELT has no per-ticker endpoint" is
    not news to the reader and not something they can act on.

    ``as_of`` is **not** optional politeness. It bounds the feed to articles published at or before
    that instant, and a provider implements it by routing its parsed items through
    :func:`app.market.news_models.published_before` before returning. See that function's docstring
    for the failure it exists to prevent.
    """

    name: str

    def fetch_symbol_news(
        self, symbol: str, *, limit: int = 20, as_of: dt.datetime | None = None
    ) -> NewsFeed: ...

    def fetch_query_news(
        self, query: str, *, limit: int = 20, as_of: dt.datetime | None = None
    ) -> NewsFeed: ...


@runtime_checkable
class SocialProvider(Protocol):
    """Message counts for one symbol. Counts only -- see :mod:`app.market.news_models`.

    There is no ``as_of`` parameter, and its absence is deliberate rather than an omission to fill in
    later. Every free social endpoint serves only a live window: StockTwits returns the most recent
    messages on a symbol's stream and Reddit's RSS search the most recent posts, neither with a
    historical query. A provider offering an ``as_of`` it cannot honour would let a backtest read a
    2019 bound, receive today's messages, and never know -- the exact silent look-ahead the news path
    guards against. A caller that needs history must build it forward from stored snapshots.
    """

    name: str

    def fetch_social(self, symbol: str, *, limit: int = 30) -> SocialSnapshot: ...


@runtime_checkable
class EventProvider(Protocol):
    """Prediction-market pricing for a keyword."""

    name: str

    def fetch_events(self, topic: str, *, limit: int = 10) -> tuple[EventMarket, ...]: ...


def provider_symbol(symbol: str) -> str:
    """A ledger symbol rewritten the way price providers spell it -- for share classes only.

    US class shares are the motivating case. Brokers separate the class with a dot -- Robinhood
    exports ``BRK.B``, and that is what the ledger stores because the ledger records what the broker
    said. Yahoo and Stooq both use a hyphen. Sent unchanged, ``BRK.B`` comes back "no chart data" and
    the position silently joins ``unpriced_symbols``: measured on a real portfolio, a Berkshire
    position sat unpriced and excluded from market value for exactly this reason,
    while ``BRK-B`` returns thousands of daily bars from the same endpoint.

    A blanket dot-to-hyphen is *not* right, though it looks that way from the share-class cases
    alone. The dot in a US symbol has a second, unrelated meaning: an **exchange suffix**, as in
    ``DX-Y.NYB`` (ICE US Dollar Index, ``.NYB`` = NYBOT) -- and that is already Yahoo's own correct
    spelling. Rewriting it to ``DX-Y-NYB`` 404s; the symbol was right and the rewrite broke it.

    The two cases are told apart by what follows the dot, plus one more check the ``.NYB`` case alone
    doesn't force but a fuller survey does: every real share-class suffix (BRK.A/B, BF.A/B, HEI.A,
    LEN.B) is exactly one letter, but so is at least one real exchange suffix (``.L``, London) --
    suffix length alone is not a safe discriminator. What every share-class ticker also has, and
    every exchange-suffixed one we need to handle does not, is a *plain* base: no hyphen before the
    dot. ``DX-Y.NYB`` already has one (``DX-Y``), which is itself evidence the dot is doing something
    other than marking a share class -- a symbol that has already had to reach for a separator
    wouldn't reach for a second, different one to mean the same thing. So: rewrite the dot to a
    hyphen only when the suffix is a single letter *and* the base contains no hyphen; otherwise leave
    the symbol exactly as given (still upper-cased, since providers are case-sensitive).

    This still gets one real case wrong: a single-letter exchange suffix on a plain, hyphen-free base
    -- ``VOD.L`` (Vodafone, London) would be misread as a share class and wrongly rewritten to
    ``VOD-L``. Nothing in this codebase's symbol universe currently hits that case (the ledger is
    US-broker-only and the one exchange-suffixed symbol in use, ``DX-Y.NYB``, has a hyphenated base),
    so the narrower rule that fixes the known bug without a lookup table is preferred over a broader
    one guessing at exchange codes it has never seen.
    """
    upper = symbol.upper()
    if "-" in upper:
        return upper
    base, dot, suffix = upper.rpartition(".")
    if dot and len(suffix) == 1 and suffix.isalpha():
        return f"{base}-{suffix}"
    return upper

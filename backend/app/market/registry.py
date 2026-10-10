"""The provider fallback registry: turns several flaky upstreams into one predictable failure mode.

Each walk rule exists because the opposite behaviour is actively harmful, not merely suboptimal:

* :class:`~app.market.providers.base.SymbolNotFound` is **terminal**. The upstream is healthy and
  says the ticker does not exist; asking the next provider turns one fast 404 into a slow walk
  through the whole chain and teaches the user that a typo takes four seconds to fail. Terminating
  does not mean discarding: if an earlier provider in the chain had already failed with
  :class:`~app.market.providers.base.ProviderUnavailable` before this one said "no such ticker", that
  context is attached to the raised exception (see :class:`SymbolNotFoundWithContext`) rather than
  silently dropped -- see ``app/market/providers/stooq.py``'s docstring for exactly the failure mode
  that discarding it would recreate: a degraded fallback overruling a healthy primary, "Yahoo is
  down" read back to the caller as "no such ticker".
* :class:`~app.market.providers.base.UnsupportedQuery` is **skipped silently** for the same reason
  as ``UnsupportedInterval`` below: it is the news chains' way of saying "not this kind of question".
  GDELT indexes global coverage and has no per-ticker endpoint, so it declines ``fetch_symbol_news``
  and the walk moves to Yahoo without telling anyone about a non-event.
* :class:`~app.market.providers.base.UnsupportedInterval` is **skipped silently**. Stooq having no
  intraday bars is not news to the user and not something they can act on -- surfacing it as a
  warning would just be noise on every intraday chart, forever.
* :class:`~app.market.providers.base.ProviderUnavailable` (and its subclasses ``RateLimited`` and
  ``ProviderResponseError``) is **retried on the next provider**, with a warning recording which
  provider failed and why. The warning survives into the response so the UI can show that a number
  came from the second choice, not the first.
* When every provider is exhausted, the registry raises **one exception whose message lists what
  every provider said** -- not a bare "no data available". A fallback chain that fails silently
  down to an unexplained empty result is the single most annoying thing to debug in this module.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pandas as pd

from app.market.models import BarSource, Interval, MarketWarning, Profile, Quote
from app.market.news_models import EventMarket, NewsFeed, SocialSnapshot
from app.market.providers.base import (
    BarProvider,
    EventProvider,
    FundamentalsProvider,
    NewsProvider,
    ProfileProvider,
    ProviderUnavailable,
    SocialProvider,
    SymbolNotFound,
    UnsupportedInterval,
    UnsupportedQuery,
)

if TYPE_CHECKING:
    from app.config import Settings
    from app.market.fundamentals import Fundamentals

__all__ = [
    "KNOWN_DEGRADED",
    "BarFetch",
    "ProviderRegistry",
    "ProviderStatus",
    "SymbolNotFoundWithContext",
    "default_registry",
]


class SymbolNotFoundWithContext(SymbolNotFound):
    """A terminal :class:`SymbolNotFound` carrying whatever the walk had already collected.

    Plain ``SymbolNotFound`` carries only the message of the provider that raised it. Re-raising it
    as-is from :func:`_walk` throws away anything earlier providers reported first -- if provider A
    had already failed with :class:`~app.market.providers.base.ProviderUnavailable` before provider B
    said "no such ticker", a caller (or a log line) that only sees B's bare exception cannot tell A
    was ever unhealthy. ``warnings`` and ``failures`` are exactly what a *successful* :class:`BarFetch`
    would have carried on ``BarFetch.warnings`` had the walk not terminated -- attached here so that
    information is not lost just because the walk ended in an exception instead of a return.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        warnings: list[MarketWarning],
        failures: list[str],
    ) -> None:
        super().__init__(message, provider=provider)
        self.warnings = warnings
        self.failures = failures


@dataclass(frozen=True)
class BarFetch:
    """A bar frame plus the provenance and caveats the API layer must be able to show."""

    frame: pd.DataFrame
    source: BarSource
    warnings: list[MarketWarning]
    exchange_timezone: str | None = None
    """The instrument's exchange timezone, when the provider reported one (Yahoo does, via
    ``frame.attrs["exchange_timezone"]``; Stooq never does since it never serves the intraday bars
    this is used for). Threaded through to `app.market.store` so the staleness gate can check the
    instrument's own trading hours instead of assuming America/New_York for every symbol -- see
    `app.market.store._plausible_trading_window`."""


def _walk[P, T](
    providers: Sequence[P],
    call: Callable[[P], T],
    *,
    what: str,
    symbol: str,
) -> tuple[P, T, list[MarketWarning]]:
    """Try each provider in order, applying the fallback rules described in the module docstring.

    Shared by bars, quotes, profiles and fundamentals -- the walk logic does not care what is being
    fetched, only how each provider's failure should be handled. ``call`` is expected to raise
    :class:`UnsupportedInterval` (or, for the news chains, :class:`UnsupportedQuery`) itself if the
    provider cannot serve the request at all, so this helper stays agnostic to what "unsupported"
    means for a given fetch kind. The two are handled identically and deliberately: "Stooq has no
    intraday bars" and "GDELT has no per-ticker endpoint" are the same shape of non-news to a reader,
    and neither should surface as a warning they cannot act on.
    """
    warnings: list[MarketWarning] = []
    failures: list[str] = []
    last_exc: ProviderUnavailable | None = None

    for provider in providers:
        try:
            result = call(provider)
        except SymbolNotFound as exc:
            # Terminal: the ticker does not exist, asking another provider wastes a round trip. But
            # re-raising the caught exception unchanged would discard `warnings`/`failures` collected
            # from any provider that failed earlier in this same walk -- see `SymbolNotFoundWithContext`.
            raise SymbolNotFoundWithContext(
                str(exc), provider=exc.provider, warnings=list(warnings), failures=list(failures)
            ) from exc
        except (UnsupportedInterval, UnsupportedQuery):
            continue  # not a failure, and not something the user can act on -- no warning
        except ProviderUnavailable as exc:
            name = getattr(provider, "name", type(provider).__name__)
            warnings.append(
                MarketWarning(
                    kind="provider_fallback",
                    message=f"{name} unavailable for {symbol} {what}: {exc}",
                )
            )
            failures.append(f"{name}: {exc}")
            last_exc = exc
            continue
        else:
            return provider, result, warnings

    if last_exc is not None:
        raise ProviderUnavailable(
            f"no provider could supply {what} for {symbol} -- " + "; ".join(failures),
            provider=last_exc.provider,
        ) from last_exc
    # Every provider was skipped as unsupported (or none were configured at all): there was never a
    # retryable failure to report, but the caller still needs an exception rather than a crash on an
    # unbound `result`.
    raise ProviderUnavailable(
        f"no configured provider supports {what} for {symbol}",
        provider="registry",
    )


#: Providers known to be unable to serve, and why. A chain member that is registered but cannot
#: answer is not a fallback, and the difference matters *before* an outage rather than during one:
#: with this map, :meth:`ProviderRegistry.describe` can say "one working source for daily bars"
#: while the chain still reads as two, which is the honest summary. Keyed by provider name so a
#: provider that starts working again is re-enabled by deleting a line here, with no other change.
KNOWN_DEGRADED: dict[str, str] = {
    "stooq": (
        "serves no data to this host. The anti-bot block has changed shape at least once, and the "
        "provider is written to survive both: on 2026-08-14 the CSV download answered with a "
        "JavaScript proof-of-work challenge carrying HTTP 200; re-probed on 2026-08-24 it answers "
        "a canned HTTP 404 'page you requested does not exist' instead -- for live symbols "
        "(aapl, spy, qqq) and, decisively, for https://stooq.com/ itself. A homepage that 404s is "
        "what separates an address-level block from a missing symbol, and is why this provider "
        "must never raise SymbolNotFound. Reproduced across stooq.com, stooq.pl and plain HTTP. "
        "Neither shape is fixable with headers, and clearing the challenge would mean executing "
        "its script, which is not something a data provider in this application does."
    ),
}


@dataclass(frozen=True)
class ProviderStatus:
    """One provider's place in a chain, and whether it can actually serve."""

    name: str
    role: str
    """``bars``, ``profile`` or ``fundamentals``."""
    intervals: tuple[str, ...] = ()
    degraded_reason: str | None = None

    @property
    def usable(self) -> bool:
        return self.degraded_reason is None


class ProviderRegistry:
    """Fallback chains for bars, profiles/quotes, fundamentals, news, social and events.

    Walked in constructor order. The three news-shaped chains added last reuse :func:`_walk`
    unchanged rather than growing a parallel walk of their own: a news upstream fails in exactly the
    ways a price upstream does -- throttled, down, serving a challenge page -- and the one place that
    decides what each failure means should stay one place.
    """

    def __init__(
        self,
        bar_providers: Sequence[BarProvider] = (),
        profile_providers: Sequence[ProfileProvider] = (),
        fundamentals_providers: Sequence[FundamentalsProvider] = (),
        news_providers: Sequence[NewsProvider] = (),
        social_providers: Sequence[SocialProvider] = (),
        event_providers: Sequence[EventProvider] = (),
    ) -> None:
        self._bar_providers = tuple(bar_providers)
        self._profile_providers = tuple(profile_providers)
        self._fundamentals_providers = tuple(fundamentals_providers)
        self._news_providers = tuple(news_providers)
        self._social_providers = tuple(social_providers)
        self._event_providers = tuple(event_providers)

    # --- news, social and events -------------------------------------------------------------
    #
    # Each of these returns the *first* provider's answer rather than merging every provider's, which
    # is the same contract `get_bars` has and is deliberate here too: a merged feed would have to
    # decide what to do when two upstreams disagree about an article's timestamp, and "the chain's
    # first working answer, labelled with who gave it" is a contract a reader can actually check.
    # `app.market.news_models.merge_feeds` exists for the caller that genuinely wants a union, and it
    # is the caller -- not the registry -- that knows whether it wants breadth or provenance.

    def get_symbol_news(
        self, symbol: str, *, limit: int = 20, as_of: dt.datetime | None = None
    ) -> NewsFeed:
        """Headlines for one ticker, from the first provider in the chain that serves them.

        A provider that has no per-ticker surface raises
        :class:`~app.market.providers.base.UnsupportedQuery` and is skipped silently -- that is how
        GDELT stays in the chain for macro queries without pretending to answer this one.
        """
        _, feed, warnings = _walk(
            self._news_providers,
            lambda p: p.fetch_symbol_news(symbol, limit=limit, as_of=as_of),
            what="news",
            symbol=symbol,
        )
        return feed.model_copy(update={"warnings": (*feed.warnings, *warnings)})

    def get_query_news(
        self, query: str, *, limit: int = 20, as_of: dt.datetime | None = None
    ) -> NewsFeed:
        """Headlines for a free-text macro query. ``query`` stands in for ``symbol`` in warnings."""
        _, feed, warnings = _walk(
            self._news_providers,
            lambda p: p.fetch_query_news(query, limit=limit, as_of=as_of),
            what="news",
            symbol=query,
        )
        return feed.model_copy(update={"warnings": (*feed.warnings, *warnings)})

    @property
    def has_social_providers(self) -> bool:
        """Whether any social provider is registered at all.

        Exists so a caller can tell "nothing to observe" from "observation failed" *without* making a
        request to find out. `app.market.refresh` uses it to skip its snapshot pass entirely when the
        chain is empty: looping a watchlist to raise once per symbol would report N failures that are
        really one configuration fact, and would pay N pacing delays for requests never made.
        """
        return bool(self._social_providers)

    def get_social(self, symbol: str, *, limit: int = 30) -> SocialSnapshot:
        """Message counts for one ticker. Counts only -- see :mod:`app.market.news_models`."""
        _, snapshot, _ = _walk(
            self._social_providers,
            lambda p: p.fetch_social(symbol, limit=limit),
            what="social sentiment",
            symbol=symbol,
        )
        return snapshot

    def get_events(self, topic: str, *, limit: int = 10) -> tuple[EventMarket, ...]:
        """Prediction-market pricing for a keyword."""
        _, markets, _ = _walk(
            self._event_providers,
            lambda p: p.fetch_events(topic, limit=limit),
            what="prediction markets",
            symbol=topic,
        )
        return markets

    def describe(self) -> tuple[ProviderStatus, ...]:
        """Every registered provider, in walk order, with its known status.

        Reports rather than probes. A probe on a health check would put a network round trip per
        provider behind an endpoint that gets polled, and would still only describe this instant --
        while the thing worth knowing here is structural: how many sources can serve at all, which
        does not change between requests. What a probe would add is caught by the ordinary request
        path already, which reports every provider's failure by name when a walk is exhausted.
        """
        statuses: list[ProviderStatus] = []
        for provider in self._bar_providers:
            statuses.append(
                ProviderStatus(
                    name=provider.name,
                    role="bars",
                    intervals=tuple(sorted(i.value for i in provider.supported_intervals)),
                    degraded_reason=KNOWN_DEGRADED.get(provider.name),
                )
            )
        for profile_provider in self._profile_providers:
            statuses.append(
                ProviderStatus(
                    name=profile_provider.name,
                    role="profile",
                    degraded_reason=KNOWN_DEGRADED.get(profile_provider.name),
                )
            )
        for fundamentals_provider in self._fundamentals_providers:
            statuses.append(
                ProviderStatus(
                    name=fundamentals_provider.name,
                    role="fundamentals",
                    degraded_reason=KNOWN_DEGRADED.get(fundamentals_provider.name),
                )
            )
        return tuple(statuses)

    def get_bars(
        self,
        symbol: str,
        interval: Interval,
        *,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> BarFetch:
        def call(provider: BarProvider) -> pd.DataFrame:
            if interval not in provider.supported_intervals:
                raise UnsupportedInterval(
                    f"{provider.name} does not serve {interval.value}", provider=provider.name
                )
            return provider.fetch_bars(symbol, interval, start=start, end=end)

        provider, frame, warnings = _walk(
            self._bar_providers, call, what=f"{interval.value} bars", symbol=symbol
        )
        # `frame.attrs` is how the provider hands back metadata that has no column of its own to
        # live in -- see `YahooProvider.fetch_bars`. Not every provider sets it (Stooq never does),
        # so this is `None` rather than a fabricated guess when it is absent.
        exchange_timezone = frame.attrs.get("exchange_timezone")
        if not isinstance(exchange_timezone, str):
            exchange_timezone = None
        return BarFetch(
            frame=frame,
            source=BarSource(provider.name),
            warnings=warnings,
            exchange_timezone=exchange_timezone,
        )

    def get_quote(self, symbol: str) -> Quote:
        _, quote, _ = _walk(
            self._profile_providers, lambda p: p.fetch_quote(symbol), what="quote", symbol=symbol
        )
        return quote

    def get_profile(self, symbol: str) -> Profile:
        _, profile, _ = _walk(
            self._profile_providers, lambda p: p.fetch_profile(symbol), what="profile", symbol=symbol
        )
        return profile

    def get_fundamentals(self, symbol: str) -> Fundamentals:
        # `FundamentalsProvider.fetch_fundamentals` (app.market.providers.base) is typed `-> object`
        # -- that protocol is a contract file this module must not edit -- so the walk itself only
        # knows it got *something* back. `Fundamentals` is imported under TYPE_CHECKING only (see
        # the top of this file): it is owned and actively being written by another agent in this
        # phase, and importing it for real at module scope would make this file's importability
        # depend on that file's mid-edit state. The cast below is therefore a type-checker-only
        # narrowing, not a runtime isinstance check -- if `app.market.fundamentals.build_fundamentals`
        # ever returns something else, this will not catch it.
        _, fundamentals, _ = _walk(
            self._fundamentals_providers,
            lambda p: p.fetch_fundamentals(symbol),
            what="fundamentals",
            symbol=symbol,
        )
        return cast("Fundamentals", fundamentals)


def default_registry(settings: Settings | None = None) -> ProviderRegistry:
    """The registry the running app actually uses: Yahoo, falling back to Stooq, for bars.

    **In practice that is one working source.** Stooq has been unable to serve since Phase 4 (see
    :data:`KNOWN_DEGRADED`), so every bar, quote, chart, indicator, decision table and backtest in
    this application depends on Yahoo alone. It stays in the chain because its failure is correctly
    typed and therefore harmless -- and because the day it starts answering again, deleting one line
    from ``KNOWN_DEGRADED`` is the whole change. What it must not do is let the chain *read* as two
    sources; :meth:`ProviderRegistry.describe` and ``GET /api/health/providers` exist so the single
    point of failure is visible before an outage rather than discovered during one.

    Builds exactly one :class:`httpx.Client` wrapping :class:`~app.market.cache.CachingTransport`
    over a real :class:`httpx.HTTPTransport`, and hands that one client to every provider so they
    all share the same on-disk cache rather than each keeping a redundant copy.

    The concrete provider classes are imported inside this function, not at module scope, so that
    everything else in this module -- ``ProviderRegistry``, ``BarFetch``, the walk logic -- stays
    importable and independently testable even before ``app.market.providers.yahoo`` / ``stooq`` /
    ``sec_edgar`` exist. See this file's note in the delivery report if those modules are still
    missing: this function is the only thing in the package that depends on them.
    """
    import httpx

    from app.config import get_settings
    from app.market.cache import CachingTransport
    from app.market.providers.gdelt import GdeltProvider
    from app.market.providers.polymarket import PolymarketProvider
    from app.market.providers.reddit import RedditProvider
    from app.market.providers.sec_edgar import SecEdgarProvider
    from app.market.providers.stocktwits import StocktwitsProvider
    from app.market.providers.stooq import StooqProvider
    from app.market.providers.yahoo import YahooProvider
    from app.market.providers.yahoo_news import YahooNewsProvider

    cfg = settings or get_settings()
    inner = httpx.HTTPTransport()
    transport = CachingTransport(inner, cfg.cache_dir / "http")
    client = httpx.Client(transport=transport, timeout=10.0)

    yahoo = YahooProvider(client=client)
    stooq = StooqProvider(client=client)
    sec_edgar = SecEdgarProvider(client=client)

    # News chain order is not arbitrary. Yahoo first for per-ticker questions because it is the only
    # one with a real per-symbol surface; GDELT second because it declines a ticker with
    # `UnsupportedQuery` (skipped silently) but is the better macro index; Reddit last because its
    # RSS carries no score or comment count, so it can say a thing was discussed and nothing about
    # how much. For a macro query the same order reads Yahoo's thin search first -- acceptable, since
    # the walk only moves on when a provider actually fails, and the caller wanting GDELT
    # specifically should ask the provider directly rather than through the chain.
    news = (YahooNewsProvider(client=client), GdeltProvider(client=client), RedditProvider(client=client))

    return ProviderRegistry(
        bar_providers=(yahoo, stooq),
        profile_providers=(yahoo,),
        news_providers=news,
        social_providers=(StocktwitsProvider(client=client),),
        event_providers=(PolymarketProvider(client=client),),
        fundamentals_providers=(sec_edgar,),
    )

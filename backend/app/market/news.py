"""The news/sentiment aggregation layer: composes the news, social and event provider chains into
the two panels the ticker and macro pages need.

This module owns no HTTP of its own -- it is a composition layer over
:class:`~app.market.registry.ProviderRegistry`, in the same spirit and for the same reason
:mod:`app.market.macro` composes FRED, CNN and the bar store into one page rather than letting the
router talk to providers directly. One decision carries the whole design:

**Nothing here may let a provider error reach its caller.** :func:`app.market.macro.build_snapshot`
set the precedent this module matches exactly: a dead upstream degrades its own tile into
``value=None`` plus a warning, never the whole snapshot. Here that means a dead StockTwits costs the
panel its social section and nothing else, and a dead news chain costs it headlines and leaves
prediction markets intact -- each section is built inside its own failure boundary, and
:func:`build_ticker_panel` / :func:`build_macro_panel` therefore have nothing left to catch: nothing
they call is allowed to raise a :class:`~app.market.providers.base.ProviderError` past this module's
boundary. Absence is rendered as an empty section plus a :class:`~app.market.models.MarketWarning`
naming which upstream failed and why -- never a bare empty list, which reads as "no news today" and
is a different, false claim from "we could not ask".

**`TickerNewsPanel.social` is `SocialSummary | None`, and `None` always carries a warning.** A dead
social chain must not be papered over with an all-zero :class:`~app.market.news_models.SocialSnapshot`
-- that would render as "nobody is talking about this", a claim nobody measured. See
:class:`~app.market.news_models.TickerNewsPanel`'s own docstring for the same point made from the
model side.

**`ProviderRegistry.SymbolNotFoundWithContext` is not just caught, it is unpacked.** A terminal
"no such ticker/topic" from the last provider in a chain can still carry ``warnings``/``failures``
collected from providers that failed *before* it -- see that class's docstring in
:mod:`app.market.registry`. Discarding them here would recreate the exact failure the class exists to
prevent: a reader seeing "not found" with no trace that an earlier provider was ever unhealthy. Every
catch site below folds ``.warnings`` (when present) into the panel's warnings before adding its own.

**`NewsFeed.warnings` from the registry walk are folded in too**, for the same reason: a feed that
came back from the second provider in the chain, or short, or throttled, must be able to say so on
the panel, not just on the intermediate object this module discards after reading `.items`.

**The `registry` parameter is the injection point, following `macro.build_snapshot`'s explicit
parameter rather than its module-level `_default_fred`/`_default_cnn` monkeypatch pattern.** Both of
`build_snapshot`'s own default-factories exist to give *tests* a seam, and `registry=` already *is*
that seam here: :func:`~app.market.registry.default_registry` is the one and only default-construction
path this module needs (there is no equivalent of `macro`'s two separate `fred=`/`cnn=` clients to
juggle), so a second, parallel monkeypatch target would just be another way to reach the same object.
Tests that want a network-free registry construct one directly (`ProviderRegistry(news_providers=...)`)
and pass it in; nothing in this module ever needs the object `default_registry` would have built.

**`as_of` is threaded straight through to the providers, unmodified.** `app.market.news_models.
published_before` is the single sanctioned place a feed gets bounded, and it lives one layer down, in
each provider. A naive (timezone-naive) `as_of` is therefore not caught here: it propagates as the
`ValueError` `published_before` raises, on purpose -- that is a caller bug (an unaware datetime built
by unaware code), not an upstream failure, and turning it into a degraded-but-200 section the way a
`ProviderError` is handled would hide a look-ahead bug instead of surfacing it. See that function's
own docstring for why a naive bound cannot be silently coerced.
"""

from __future__ import annotations

import datetime as dt
from typing import Final

from app.config import Settings
from app.market.models import MarketWarning
from app.market.news_models import (
    EventMarket,
    MacroNewsPanel,
    NewsItem,
    SocialSummary,
    TickerNewsPanel,
)
from app.market.providers.base import ProviderError
from app.market.registry import ProviderRegistry, SymbolNotFoundWithContext, default_registry

__all__ = ["DEFAULT_MACRO_QUERY", "build_macro_panel", "build_ticker_panel"]


#: Used whenever `build_macro_panel` is called with no `query`. Five terms rather than one, mirroring
#: TradingAgents' fixed macro search set: Fed policy, broad-market earnings/growth, geopolitical risk,
#: the other major central banks, and commodities. Those five are what most reliably move every asset
#: class at once -- a page meant to summarise "the macro backdrop" needs that breadth, not one
#: sector's headlines, and a single caller-suppliable `query: str` (not a list) is what
#: `ProviderRegistry.get_query_news`/`get_events` accept, so the five are joined with `OR` into one
#: string a search-shaped provider chain can execute in a single request.
DEFAULT_MACRO_QUERY: Final[str] = (
    "Fed interest rate decision OR S&P 500 earnings GDP OR geopolitical risk "
    "OR ECB BOJ BOE OR oil commodities"
)


def build_ticker_panel(
    settings: Settings,
    symbol: str,
    *,
    limit: int = 20,
    as_of: dt.datetime | None = None,
    registry: ProviderRegistry | None = None,
) -> TickerNewsPanel:
    """Headlines and social counts for one ticker, in one call so both sections agree on "now".

    `registry` defaults to `None` -> :func:`~app.market.registry.default_registry(settings)`; pass a
    fake registry (a `ProviderRegistry` wrapping fake providers) to run this with no network in the
    loop at all -- see the module docstring for why this is the chosen seam.

    Never raises a :class:`~app.market.providers.base.ProviderError`: a dead news chain leaves
    `news=()`, `news_source=None` and a warning; a dead social chain leaves `social=None` and a
    warning; either can fail independently of the other. A naive `as_of` is the one exception -- see
    the module docstring's closing paragraph -- and surfaces as `ValueError`, unchanged.
    """
    reg = registry or default_registry(settings)
    warnings: list[MarketWarning] = []

    news: tuple[NewsItem, ...] = ()
    news_source: str | None = None
    try:
        feed = reg.get_symbol_news(symbol, limit=limit, as_of=as_of)
    except ProviderError as exc:
        warnings.extend(_fold_provider_error(exc, what="news", subject=symbol))
    else:
        news = feed.items
        news_source = feed.source or None
        warnings.extend(feed.warnings)

    social: SocialSummary | None = None
    try:
        snapshot = reg.get_social(symbol, limit=limit)
    except ProviderError as exc:
        warnings.extend(_fold_provider_error(exc, what="social sentiment", subject=symbol))
    else:
        social = SocialSummary.of(snapshot)

    return TickerNewsPanel(
        symbol=symbol,
        generated_at=dt.datetime.now(dt.UTC),
        as_of=as_of,
        news=news,
        news_source=news_source,
        social=social,
        warnings=tuple(warnings),
    )


def build_macro_panel(
    settings: Settings,
    *,
    query: str = "",
    limit: int = 20,
    as_of: dt.datetime | None = None,
    registry: ProviderRegistry | None = None,
) -> MacroNewsPanel:
    """Global headlines and prediction-market pricing for the Macro page, in one call.

    An empty (or all-whitespace) `query` falls back to :data:`DEFAULT_MACRO_QUERY` rather than being
    sent to a provider or rejected -- the Macro page's own load has no ticker to key a query on, and
    "no query" is a request for the general macro backdrop, not a request for nothing. The panel's own
    `query` field always carries whichever string was actually searched, so a caller who left it blank
    can still see what answered.

    `registry` and the never-raises contract are exactly :func:`build_ticker_panel`'s -- see the
    module docstring. News and prediction markets are each their own failure boundary: a dead
    Polymarket costs `events` and nothing else, a dead news chain costs `news`/`news_source` and
    nothing else.
    """
    reg = registry or default_registry(settings)
    effective_query = query.strip() or DEFAULT_MACRO_QUERY
    warnings: list[MarketWarning] = []

    news: tuple[NewsItem, ...] = ()
    news_source: str | None = None
    try:
        feed = reg.get_query_news(effective_query, limit=limit, as_of=as_of)
    except ProviderError as exc:
        warnings.extend(_fold_provider_error(exc, what="news", subject=effective_query))
    else:
        news = feed.items
        news_source = feed.source or None
        warnings.extend(feed.warnings)

    events: tuple[EventMarket, ...] = ()
    try:
        events = reg.get_events(effective_query, limit=limit)
    except ProviderError as exc:
        warnings.extend(_fold_provider_error(exc, what="prediction markets", subject=effective_query))

    return MacroNewsPanel(
        generated_at=dt.datetime.now(dt.UTC),
        as_of=as_of,
        query=effective_query,
        news=news,
        news_source=news_source,
        events=events,
        warnings=tuple(warnings),
    )


def _fold_provider_error(exc: ProviderError, *, what: str, subject: str) -> list[MarketWarning]:
    """One exhausted registry walk, turned into the warnings a panel section degrades into.

    `exc` is either a plain :class:`~app.market.providers.base.ProviderUnavailable` (every provider in
    the chain failed or none were configured) or a
    :class:`~app.market.registry.SymbolNotFoundWithContext` (the walk terminated on a confirmed
    "does not exist", possibly after earlier providers in the same walk had already failed). The
    latter's `.warnings` are folded in first -- discarding them would recreate the exact failure mode
    that class exists to prevent, a reader seeing "not found" with no trace that an earlier provider
    was ever unhealthy. Either way, one more warning is appended naming this section, `subject` and
    `exc` itself, since `SymbolNotFoundWithContext.warnings` never includes a warning for the provider
    that raised it -- only for the ones that failed before it.
    """
    warnings: list[MarketWarning] = []
    if isinstance(exc, SymbolNotFoundWithContext):
        warnings.extend(exc.warnings)
    warnings.append(
        MarketWarning(
            kind="provider_fallback",
            message=f"{what} unavailable for {subject}: {exc}",
        )
    )
    return warnings

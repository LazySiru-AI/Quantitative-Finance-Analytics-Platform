"""News and sentiment endpoints: one panel per page, each of which always answers.

Thin on purpose, and thinner than most routers here, because there is genuinely nothing for it to
decide. :mod:`app.market.news` absorbs every provider failure before it reaches this layer -- a dead
StockTwits costs the social section and nothing else, a dead news chain costs the headlines and
leaves prediction markets standing -- so neither endpoint below has a 5xx path at all. That is the
same contract :mod:`app.api.macro` documents for :func:`app.market.macro.build_snapshot`, and it is
the right one for a panel assembled from four independent upstreams: a page that 500s because one of
them is throttled loses three working sections to one broken one.

**What a caller sees when something is down** is an empty section plus a ``MarketWarning`` naming the
upstream and the reason. Never an exception, and never a silently empty list -- "GDELT throttled us"
and "there is no news today" are different claims, and the frontend renders them differently.

**The one error this router does raise is a 422**, and it is the caller's own: an ``as_of`` without a
timezone. :func:`app.market.news_models.published_before` refuses a naive bound rather than coercing
it, because assuming local time silently shifts the look-ahead cutoff by the developer's own offset,
and a look-ahead cutoff that is quietly wrong is the failure the whole news path is built to avoid.
That is a malformed request, not an outage, so it is a 422 rather than a degraded 200 -- the same
distinction ``/api/macro/fear-greed`` draws for an ``as_of`` CNN cannot honour.

**There is deliberately no per-symbol social endpoint.** The Ticker panel is one request so its
sections cannot disagree about what "now" means, exactly as ``GET /api/macro/snapshot`` is one
request for the same reason.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query

from app.config import get_settings
from app.market import news
from app.market.news_models import MacroNewsPanel, TickerNewsPanel

router = APIRouter(prefix="/api/news", tags=["news"])

#: The same closed alphabet as :data:`app.api.market.SymbolPath`. Kept as a local copy rather than an
#: import for the reason ``app.api.macro`` gives for duplicating its own status mapping: it is a
#: one-line contract, and copying it is cheaper than coupling this router's importability to
#: ``market.py``'s internals.
SymbolPath = Annotated[str, Path(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9.\-^=]+$")]

#: Bounded rather than free. The upstreams this feeds are keyless public endpoints -- GDELT throttles
#: to roughly one request per five seconds and was measured still refusing at twelve -- so an
#: unbounded ``limit`` is a way for one page load to spend the whole budget. 100 is well past what
#: any panel renders.
LimitQuery = Annotated[int, Query(ge=1, le=100)]


def _naive_as_of(exc: ValueError) -> HTTPException:
    """A naive ``as_of`` is a 422, not a 500.

    ``published_before`` raises a plain ``ValueError`` for it. Letting that escape would surface a
    caller's own mistake as an internal error, which sends whoever hit it looking at the server
    instead of at their query string.
    """
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/ticker/{symbol}", response_model=TickerNewsPanel)
def ticker_news(
    symbol: SymbolPath,
    limit: LimitQuery = 20,
    as_of: dt.datetime | None = None,
) -> TickerNewsPanel:
    """Headlines and social message counts for one ticker, in a single request.

    Always 200 unless ``as_of`` is malformed. A section this could not fill comes back empty with a
    warning naming the upstream that failed -- see the module docstring.

    ``as_of`` bounds the headlines to articles published at or before it. Note it does **not** bound
    the social counts, and cannot: every free social endpoint serves only a live window, so a
    ``SocialSnapshot`` is always "now" no matter what is asked. That asymmetry is deliberate and is
    documented on :class:`~app.market.providers.base.SocialProvider` -- a provider that accepted a
    historical bound it could not honour would let a backtest read 2019, receive today's messages,
    and never know.
    """
    try:
        return news.build_ticker_panel(get_settings(), symbol, limit=limit, as_of=as_of)
    except ValueError as exc:
        raise _naive_as_of(exc) from exc


@router.get("/macro", response_model=MacroNewsPanel)
def macro_news(
    query: str = "",
    limit: LimitQuery = 20,
    as_of: dt.datetime | None = None,
) -> MacroNewsPanel:
    """Global headlines and prediction-market pricing for the macro page.

    An empty ``query`` is not an error: it falls back to
    :data:`app.market.news.DEFAULT_MACRO_QUERY`, five terms chosen to span what moves every asset
    class at once. A caller who wants one sector's headlines passes its own query.
    """
    try:
        return news.build_macro_panel(get_settings(), query=query, limit=limit, as_of=as_of)
    except ValueError as exc:
        raise _naive_as_of(exc) from exc

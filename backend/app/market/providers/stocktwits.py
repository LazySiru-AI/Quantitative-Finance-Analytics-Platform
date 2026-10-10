"""StockTwits message-count provider.

Everything comes off one endpoint: ``api.stocktwits.com/api/2/streams/symbol/{SYMBOL}.json``. It is
public and keyless -- verified live 2026-08-24, HTTP 200, JSON, no auth header required -- and it
answers with the most recent messages posted to that symbol's stream, newest first. There is no
historical query on this endpoint, which is why :class:`~app.market.providers.base.SocialProvider`
carries no ``as_of`` parameter at all; see that protocol's docstring for the look-ahead bug an
``as_of`` this endpoint could not honour would invite.

**The parsing trap this module exists to avoid.** A message's directional label -- "Bullish" or
"Bearish" -- lives three levels deep, at ``message["entities"]["sentiment"]["basic"]``, and both
``entities`` and ``entities.sentiment`` are frequently absent or ``null``. In the captured fixture
(``tests/fixtures/news/stocktwits_aapl.json``, 12 messages, trimmed from a live response), 8 of the
12 messages carry no sentiment at all. A parser that assumes the path exists throws on the *common*
case, not an edge case; a parser that instead treats a missing or malformed label as "not bullish, so
bearish" invents a number the poster never asserted. Per the module docstring on
:mod:`app.market.news_models`, an unlabelled message is counted as ``neutral`` -- its own, correctly
majority, bucket -- never silently folded into either directional count and never dropped from
``total``.

Only counts are returned, never a derived score or ratio -- see :mod:`app.market.news_models` for why
that rule holds across every provider in this package, not just this one.

``window_start`` is set from the oldest message in the batch StockTwits actually returned, not from
an assumed lookback: the endpoint does not document how far back a given call reaches (it varies with
how active the symbol's stream is), so claiming a fixed window here would assert something this
provider cannot verify.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Final

import httpx

from app.market.news_models import SocialSnapshot
from app.market.providers.base import (
    ProviderResponseError,
    ProviderUnavailable,
    RateLimited,
    SymbolNotFound,
)

__all__ = ["StocktwitsProvider"]

_URL_TEMPLATE: Final[str] = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"

#: An honest, contactable identity -- never a spoofed browser string. See
#: `app/market/providers/fred.py`'s module docstring for why: a Chrome-shaped User-Agent is exactly
#: the pattern that gets a keyless client blocked, not a way to blend in safely.
_USER_AGENT: Final[str] = "investing-dashboard/0.1"


def _message_sentiment(message: dict[str, Any]) -> str | None:
    """The upstream's own label for one message, or ``None`` when it did not supply one.

    Navigates ``entities`` -> ``sentiment`` -> ``basic`` defensively at every step: any of the three
    can be missing or ``null`` on a real message (8 of 12 in the captured fixture have no sentiment
    block at all), and that is the ordinary case, not malformed input.
    """
    entities = message.get("entities")
    if not isinstance(entities, dict):
        return None
    sentiment = entities.get("sentiment")
    if not isinstance(sentiment, dict):
        return None
    basic = sentiment.get("basic")
    return basic if isinstance(basic, str) else None


def _parse_created_at(raw: Any, symbol: str) -> dt.datetime:
    """Parse a message's ``created_at`` (ISO-8601 with a ``Z`` suffix) into a tz-aware UTC instant."""
    if not isinstance(raw, str):
        raise ProviderResponseError(
            f"stocktwits message for {symbol} has a non-string created_at: {raw!r}",
            provider="stocktwits",
        )
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderResponseError(
            f"stocktwits created_at {raw!r} for {symbol} could not be parsed", provider="stocktwits"
        ) from exc
    return parsed.astimezone(dt.UTC)


class StocktwitsProvider:
    """Message counts from StockTwits' public symbol stream. See the module docstring first."""

    name = "stocktwits"

    def __init__(self, client: httpx.Client | None = None, *, timeout: float = 15.0) -> None:
        self._client = client or httpx.Client(timeout=timeout)

    def fetch_social(self, symbol: str, *, limit: int = 30) -> SocialSnapshot:
        upper = symbol.upper()

        try:
            response = self._client.get(
                _URL_TEMPLATE.format(symbol=upper),
                params={"limit": limit},
                headers={"User-Agent": _USER_AGENT},
            )
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(
                f"stocktwits timed out fetching {upper}", provider=self.name
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(
                f"stocktwits transport error fetching {upper}: {exc}", provider=self.name
            ) from exc

        if response.status_code == 404:
            raise SymbolNotFound(f"stocktwits has no stream for {upper}", provider=self.name)
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimited(
                f"stocktwits rate-limited the request for {upper}",
                provider=self.name,
                retry_after=float(retry_after) if retry_after else None,
            )
        if response.status_code >= 500:
            raise ProviderUnavailable(
                f"stocktwits returned {response.status_code} for {upper}", provider=self.name
            )
        if response.status_code >= 400:
            raise ProviderResponseError(
                f"stocktwits returned unexpected status {response.status_code} for {upper}",
                provider=self.name,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                f"stocktwits response for {upper} was not valid JSON", provider=self.name
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderResponseError(
                f"stocktwits response for {upper} was not a JSON object", provider=self.name
            )

        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise ProviderResponseError(
                f"stocktwits response for {upper} has no 'messages' list", provider=self.name
            )

        bullish = bearish = neutral = 0
        window_start: dt.datetime | None = None
        for message in messages:
            if not isinstance(message, dict):
                raise ProviderResponseError(
                    f"stocktwits message for {upper} was not a JSON object", provider=self.name
                )

            sentiment = _message_sentiment(message)
            if sentiment == "Bullish":
                bullish += 1
            elif sentiment == "Bearish":
                bearish += 1
            else:
                # No label, or a label this parser doesn't recognise: counted as neutral rather
                # than dropped or guessed at. See the module docstring -- this is the majority case,
                # not an anomaly.
                neutral += 1

            created_at = _parse_created_at(message.get("created_at"), upper)
            if window_start is None or created_at < window_start:
                window_start = created_at

        return SocialSnapshot(
            symbol=upper,
            source=self.name,
            as_of=dt.datetime.now(dt.UTC),
            window_start=window_start,
            bullish=bullish,
            bearish=bearish,
            neutral=neutral,
        )

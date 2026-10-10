"""Polymarket prediction-market provider.

Everything comes off one endpoint: ``https://gamma-api.polymarket.com/markets``. It needs no API
key and answers with a **bare JSON array** at the top level -- not an object with a wrapper key, so
the first thing this module's parser does is reject anything that isn't a list before looking for
individual markets inside it.

Verified live 2026-08-24 with ``limit=N&closed=false&order=volume&ascending=false``: HTTP 200,
JSON, no auth. The Gamma endpoint's own text search was never exercised against the live API, so
this provider does **not** claim server-side keyword filtering -- ``topic`` is matched client-side,
case-insensitively, as a substring of ``question``, against whatever ``limit`` markets the upstream
handed back (already ordered by volume descending). A caller after a niche topic that happens to sit
outside the top ``limit`` markets by volume will see it as "no matches," not as an error; that is a
consequence of asking a volume-ranked feed for a narrow keyword, not a bug in the filter.

Five real markets are captured at ``tests/fixtures/news/polymarket_markets.json`` (each with roughly
sixty keys; only a handful matter here), and they exist specifically to pin down three traps in the
payload's typing that are easy to get wrong once and never notice, because a normal JSON decoder
does not complain about any of them:

1. **``outcomePrices`` is a JSON-encoded string, not a list.** The literal value on the wire is
   ``'["0.58", "0.42"]'`` -- a string containing JSON, itself embedded in the outer JSON document.
   It must be ``json.loads()``-ed before anything in it can be read as a price, and the elements
   that come out are themselves strings and still need ``float()``.
2. **``outcomes`` is likewise a JSON-encoded string**, e.g. ``'["Yes", "No"]'``, paired positionally
   with ``outcomePrices``. ``probability`` is the price of the outcome labelled ``"Yes"`` -- looked
   up by matching that label, never assumed to sit at index 0. Every market in the captured fixture
   happens to have Yes first, which is exactly the kind of accident that hides an index-based bug
   until a market ships with the pair reversed. Some Polymarket markets are multi-outcome brackets
   (see the SpaceX market-cap market in the fixture, which is one bracket of a larger grouped
   market) rather than a plain Yes/No binary; a market with no ``"Yes"`` outcome at all is **skipped
   entirely** rather than mapped from a guessed index -- a missing market in the result is honest,
   a mislabelled probability is not.
3. **``volume`` is a string** (``'99.997825'``), not a JSON number, and must be converted with
   ``float()`` like the outcome prices. ``lastTradePrice`` looks like a tempting shortcut for
   ``probability`` -- it is frequently ``null`` in the live feed (see the Tre Tucker market in the
   fixture) and is not used here at all.

``probability`` is passed straight through from the parsed Yes price, per
:class:`~app.market.news_models.EventMarket`'s own docstring: it is a reported observation, not
something this module computes. Pydantic's ``Field(ge=0.0, le=1.0)`` on that field means a price
outside the unit interval must surface as a loud, typed failure -- :class:`ProviderResponseError`
-- rather than being clamped into range, which would quietly invent a number no market ever quoted.

``as_of`` is the moment this provider fetched and parsed the payload, not any timestamp the upstream
carries on the market row. This mirrors :class:`~app.market.news_models.SocialSnapshot.as_of`, whose
docstring is explicit that a live snapshot's ``as_of`` means "when the snapshot was taken," not a
field borrowed from the source payload -- the same convention is followed here rather than trusting
``updatedAt``, whose semantics (last order-book activity? last resync? something else?) the live API
does not document.

``resolution_date`` on :class:`EventMarket` is a :class:`datetime.date`, because "resolution is
scheduled by day," while Polymarket's ``endDate`` is an instant (``'2026-08-24T23:59:00Z'``). This
provider parses the instant and takes its UTC calendar date. ``endDate`` is absent or ``null`` on
some markets, which becomes ``resolution_date=None`` rather than a fabricated date.

The User-Agent sent with every request is ``investing-dashboard/0.1`` -- honest, never a spoofed
browser string. See ``app.market.providers.fred`` for the concrete case (FRED tarpitting a
Chrome-shaped UA) this codebase-wide rule exists to prevent.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any, Final

import httpx

from app.market.news_models import EventMarket
from app.market.providers.base import (
    ProviderResponseError,
    ProviderUnavailable,
    RateLimited,
    UnsupportedQuery,
)

__all__ = ["PolymarketProvider"]

_URL: Final[str] = "https://gamma-api.polymarket.com/markets"

#: Honest identification, never a spoofed browser string -- see the module docstring and
#: ``app.market.providers.fred`` for why this rule is codebase-wide.
_USER_AGENT: Final[str] = "investing-dashboard/0.1"

_YES_LABEL: Final[str] = "yes"


class PolymarketProvider:
    """Prediction-market pricing from Polymarket's Gamma API, filtered client-side by keyword."""

    name = "polymarket"

    def __init__(self, client: httpx.Client | None = None, *, timeout: float = 15.0) -> None:
        self._client = client or httpx.Client(timeout=timeout)

    # -- Public API -----------------------------------------------------------

    def fetch_events(self, topic: str, *, limit: int = 10) -> tuple[EventMarket, ...]:
        if not topic or not topic.strip():
            raise UnsupportedQuery(
                "polymarket requires a non-empty topic: it has no per-topic endpoint, only a "
                "client-side filter over the volume-ranked market feed",
                provider=self.name,
            )

        payload = self._get(limit)
        markets = self._parse_markets(payload)

        needle = topic.strip().lower()
        matched = [market for market in markets if needle in market.question.lower()]
        # The upstream request already asks for volume-descending order, but re-sorting explicitly
        # here means correctness does not depend on that request param continuing to be honoured --
        # and skipped (non-Yes) markets or ties could otherwise leave the order merely "close."
        matched.sort(key=lambda market: market.volume or 0.0, reverse=True)
        return tuple(matched[:limit])

    # -- HTTP -------------------------------------------------------------------

    def _get(self, limit: int) -> Any:
        try:
            response = self._client.get(
                _URL,
                params={
                    "limit": str(limit),
                    "closed": "false",
                    "order": "volume",
                    "ascending": "false",
                },
                headers={"User-Agent": _USER_AGENT},
            )
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(
                "polymarket markets request timed out", provider=self.name
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(
                f"polymarket transport error: {exc}", provider=self.name
            ) from exc

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimited(
                "polymarket rate-limited the markets request",
                provider=self.name,
                retry_after=float(retry_after) if retry_after else None,
            )
        if response.status_code >= 500:
            raise ProviderUnavailable(
                f"polymarket returned {response.status_code}", provider=self.name
            )
        if response.status_code >= 400:
            raise ProviderResponseError(
                f"polymarket returned unexpected status {response.status_code}", provider=self.name
            )

        try:
            return response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                "polymarket response was not valid JSON", provider=self.name
            ) from exc

    # -- Parsing ------------------------------------------------------------

    def _parse_markets(self, payload: Any) -> list[EventMarket]:
        if not isinstance(payload, list):
            raise ProviderResponseError(
                "polymarket response was not a JSON array of markets", provider=self.name
            )

        markets: list[EventMarket] = []
        for raw in payload:
            market = self._parse_market(raw)
            if market is not None:
                markets.append(market)
        return markets

    def _parse_market(self, raw: Any) -> EventMarket | None:
        if not isinstance(raw, dict):
            raise ProviderResponseError(
                f"polymarket market entry was not a JSON object: {raw!r}", provider=self.name
            )

        context = raw.get("slug") or raw.get("id") or "<unknown>"

        question = raw.get("question")
        slug = raw.get("slug")
        if not isinstance(question, str) or not isinstance(slug, str):
            raise ProviderResponseError(
                f"polymarket market {context!r} is missing question/slug", provider=self.name
            )

        outcomes = self._load_json_string_array(raw.get("outcomes"), field="outcomes", context=slug)
        prices = self._load_json_string_array(
            raw.get("outcomePrices"), field="outcomePrices", context=slug
        )
        if len(outcomes) != len(prices):
            raise ProviderResponseError(
                f"polymarket market {slug!r} has {len(outcomes)} outcomes but {len(prices)} prices",
                provider=self.name,
            )

        yes_index = next(
            (
                i
                for i, label in enumerate(outcomes)
                if isinstance(label, str) and label.strip().lower() == _YES_LABEL
            ),
            None,
        )
        if yes_index is None:
            # Not a binary Yes/No market (e.g. one bracket of a multi-outcome grouped market) --
            # skip it rather than guess which price is "the" probability.
            return None

        probability = self._parse_probability(prices[yes_index], slug)
        volume = self._parse_volume(raw.get("volume"), slug)
        resolution_date = self._parse_resolution_date(raw.get("endDate"), slug)

        return EventMarket(
            question=question,
            slug=slug,
            source=self.name,
            as_of=dt.datetime.now(dt.UTC),
            probability=probability,
            volume=volume,
            resolution_date=resolution_date,
        )

    def _load_json_string_array(self, raw: Any, *, field: str, context: str) -> list[Any]:
        """Decode one of Polymarket's JSON-encoded-string array fields (``outcomes``,
        ``outcomePrices``) -- see the module docstring for why this indirection exists at all."""
        if not isinstance(raw, str):
            raise ProviderResponseError(
                f"polymarket {field!r} for {context!r} was not a JSON-encoded string: {raw!r}",
                provider=self.name,
            )
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(
                f"polymarket {field!r} for {context!r} was not valid JSON: {raw!r}",
                provider=self.name,
            ) from exc
        if not isinstance(parsed, list):
            raise ProviderResponseError(
                f"polymarket {field!r} for {context!r} decoded to a {type(parsed).__name__}, "
                "not a JSON array",
                provider=self.name,
            )
        return parsed

    def _parse_probability(self, raw_price: Any, slug: str) -> float:
        if not isinstance(raw_price, (str, int, float)) or isinstance(raw_price, bool):
            raise ProviderResponseError(
                f"polymarket Yes price {raw_price!r} for {slug!r} is neither numeric nor a string",
                provider=self.name,
            )
        try:
            probability = float(raw_price)
        except ValueError as exc:
            raise ProviderResponseError(
                f"polymarket Yes price {raw_price!r} for {slug!r} could not be parsed as a float",
                provider=self.name,
            ) from exc

        if not (0.0 <= probability <= 1.0):
            # Never clamp -- see the module docstring. A price outside the unit interval means the
            # payload does not mean what this parser assumes it means, and reporting a clamped
            # number would invent a price no market ever quoted.
            raise ProviderResponseError(
                f"polymarket Yes price {probability} for {slug!r} is outside [0, 1]",
                provider=self.name,
            )
        return probability

    def _parse_volume(self, raw: Any, slug: str) -> float | None:
        if raw is None:
            return None
        if not isinstance(raw, (str, int, float)) or isinstance(raw, bool):
            raise ProviderResponseError(
                f"polymarket volume {raw!r} for {slug!r} is neither numeric nor a string",
                provider=self.name,
            )
        try:
            return float(raw)
        except ValueError as exc:
            raise ProviderResponseError(
                f"polymarket volume {raw!r} for {slug!r} could not be parsed as a float",
                provider=self.name,
            ) from exc

    def _parse_resolution_date(self, raw: Any, slug: str) -> dt.date | None:
        if raw is None:
            return None
        if not isinstance(raw, str):
            raise ProviderResponseError(
                f"polymarket endDate {raw!r} for {slug!r} was not a string", provider=self.name
            )
        try:
            parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ProviderResponseError(
                f"polymarket endDate {raw!r} for {slug!r} is not ISO-8601", provider=self.name
            ) from exc
        # `endDate` is always UTC ("Z") on the live API; taking the date directly (rather than
        # routing through astimezone) avoids a day ever shifting across the boundary depending on
        # whatever tzinfo a future response might carry -- resolution is scheduled by UTC calendar
        # day on this endpoint.
        return parsed.date()

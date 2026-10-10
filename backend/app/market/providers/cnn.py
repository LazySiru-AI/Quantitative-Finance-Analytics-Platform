"""CNN Fear & Greed Index provider.

Everything comes off one undocumented endpoint: ``production.dataviz.cnn.io/index/fearandgreed/
graphdata``. It is not a public API -- no versioning, no changelog, no status page -- so it *will*
break without notice, which is exactly why :func:`app.market.fear_greed.composite_fear_greed`
exists as a fallback. While it works, though, it is the real, CNN-published number, and this module's
only job is to get it onto the wire faithfully.

Two things about the payload are easy to get wrong and both have a fixture built to catch them
(``tests/fixtures/macro/cnn_fear_greed.json``, component series trimmed to the last 40 points):

**Every component's ``y`` is a raw underlying measurement, not a 0-100 score.**
``market_momentum_sp500`` carries the S&P's index level (7753.11), ``market_volatility_vix`` carries
the VIX level (15.46), ``put_call_options`` carries the raw put/call ratio (0.686). Each component
block *does* carry a top-level ``score`` field alongside ``rating`` -- but this parser deliberately
does not read it. CNN never documents the normalisation or weights behind that number, so surfacing
it as ``FearGreedComponent.score`` would dress up an unexplained figure as something this codebase
computed and can show its work for. ``score`` stays ``None`` for every CNN-sourced component;
:mod:`app.market.fear_greed` is the only place a component score is ever computed, and it says so.

**A component's top-level ``rating`` and its own last data point's ``rating`` sometimes disagree.**
In the captured fixture, ``stock_price_strength`` is ``"fear"`` at the top level (paired with the
top-level ``score``) but ``"extreme fear"`` on its final historical point. This parser trusts the
**top-level block rating**, not the last point's: the top-level rating is paired with the top-level
``score`` as CNN's own "current state" summary for that component (the same pairing the top-level
``fear_and_greed.rating``/``fear_and_greed.score`` uses for the index as a whole), where the
per-point ratings inside ``data`` are a separately-stamped historical classification that can lag.
Per-point ratings are therefore never read; only ``x``/``y`` are taken from ``data``.

The seven canonical component keys are exactly the ones enumerated on
:attr:`app.market.macro_models.FearGreedComponent.key`. The payload also carries
``market_momentum_sp125`` and ``market_volatility_vix_50`` -- the 125-day S&P average and the 50-day
VIX average CNN plots alongside the two primary series for context. Neither is one of the seven
components and neither is read here.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any, Final, TypeGuard

import httpx

from app.market.macro_models import (
    FearGreed,
    FearGreedComponent,
    FearGreedSource,
    MacroPoint,
    Rating,
)
from app.market.models import MarketWarning
from app.market.providers.base import (
    ProviderResponseError,
    ProviderUnavailable,
    RateLimited,
)

__all__ = ["CnnFearGreedProvider"]

_URL: Final[str] = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

#: The seven components in the order CNN's own dashboard lists them, mapped to a display label.
#: Keys match :attr:`app.market.macro_models.FearGreedComponent.key` exactly.
_COMPONENT_LABELS: Final[dict[str, str]] = {
    "market_momentum_sp500": "Market Momentum",
    "stock_price_strength": "Stock Price Strength",
    "stock_price_breadth": "Stock Price Breadth",
    "put_call_options": "Put and Call Options",
    "market_volatility_vix": "Market Volatility",
    "junk_bond_demand": "Junk Bond Demand",
    "safe_haven_demand": "Safe Haven Demand",
}


def _component(
    *,
    key: str,
    label: str,
    raw_value: float | None,
    rating: Rating | None = None,
    as_of: dt.date | None = None,
) -> FearGreedComponent:
    """Build a component with its unit attached.

    A helper rather than four call sites repeating the lookup: a component built without its unit
    renders as a bare decimal beside six other bare decimals in different units, which is the defect
    :data:`~app.market.macro_models.FEAR_GREED_UNITS` exists to close. Going through one constructor
    means a *new* branch here cannot reintroduce it by omission.
    """
    unit, description = FearGreedComponent.units_for(key)
    return FearGreedComponent(
        key=key,
        label=label,
        raw_value=raw_value,
        rating=rating,
        as_of=as_of,
        raw_unit=unit,
        raw_description=description,
    )


def _is_finite_number(value: Any) -> TypeGuard[int | float]:
    """``True`` for a real ``int``/``float`` (never ``bool``, which is an ``int`` subclass).

    Declared as a :class:`~typing.TypeGuard` rather than a plain ``bool`` so the narrowing survives
    into the caller. Every use of this sits immediately before a ``float(...)`` on a value pulled
    out of untyped JSON; without the guard those calls read as ``float(Any | None)`` and a type
    checker is right to reject them, even though the check on the line above has already ruled the
    ``None`` out.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _epoch_ms_to_date(epoch_ms: float) -> dt.date:
    """CNN's ``x`` is epoch **milliseconds** as a float. Divide before converting -- skipping the
    ``/ 1000`` does not politely fail, it silently produces a timestamp thousands of years away from
    ``epoch_ms``'s intended date, which is why every call site here routes through this one function
    rather than inlining ``dt.datetime.fromtimestamp``."""
    return dt.datetime.fromtimestamp(epoch_ms / 1000, tz=dt.UTC).date()


def _last_numeric_point(data: Any) -> tuple[dt.date, float] | None:
    """The most recent ``{x, y}`` entry in a component's ``data`` array with a usable ``y``.

    Scans from the end rather than trusting the final row blindly: a component whose latest point
    happens to carry a non-numeric ``y`` should fall back to the last point that actually has one,
    the same way :attr:`app.market.macro_models.MacroSeries.latest` skips published gaps rather than
    reporting ``None`` just because the newest row is empty.
    """
    if not isinstance(data, list):
        return None
    for row in reversed(data):
        if not isinstance(row, dict):
            continue
        x, y = row.get("x"), row.get("y")
        if _is_finite_number(x) and _is_finite_number(y):
            return _epoch_ms_to_date(float(x)), float(y)
    return None


def _to_optional_float(value: Any) -> float | None:
    return float(value) if _is_finite_number(value) else None


class CnnFearGreedProvider:
    """The live CNN Fear & Greed index, fetched from CNN's dataviz endpoint."""

    name = "cnn"

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    # -- HTTP -----------------------------------------------------------------

    def _get(self) -> dict[str, Any]:
        try:
            response = self._client.get(_URL, headers={"User-Agent": _USER_AGENT})
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(
                "cnn fear & greed request timed out", provider=self.name
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(
                f"cnn fear & greed transport error: {exc}", provider=self.name
            ) from exc

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimited(
                "cnn rate-limited the fear & greed request",
                provider=self.name,
                retry_after=float(retry_after) if retry_after else None,
            )
        if response.status_code == 404:
            # No per-symbol semantics on this endpoint -- a 404 means the endpoint itself has moved
            # or been retired, not that "the data doesn't exist". That is retryable via the composite
            # fallback, so it is ProviderUnavailable rather than a terminal error.
            raise ProviderUnavailable(
                "cnn fear & greed endpoint returned 404 -- it may have moved or been retired",
                provider=self.name,
            )
        if response.status_code >= 500:
            raise ProviderUnavailable(
                f"cnn fear & greed returned {response.status_code}", provider=self.name
            )
        if response.status_code >= 400:
            raise ProviderResponseError(
                f"cnn fear & greed returned unexpected status {response.status_code}",
                provider=self.name,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                "cnn fear & greed response was not valid JSON", provider=self.name
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderResponseError(
                "cnn fear & greed response was not a JSON object", provider=self.name
            )
        return payload

    # -- Parsing ----------------------------------------------------------------

    def _parse_history(self, payload: dict[str, Any]) -> tuple[list[MacroPoint], list[MarketWarning]]:
        historical = payload.get("fear_and_greed_historical")
        if not isinstance(historical, dict):
            return [], [
                MarketWarning(
                    kind="missing_component",
                    message="cnn response has no fear_and_greed_historical block; "
                    "sparkline history is unavailable",
                )
            ]
        data = historical.get("data")
        if not isinstance(data, list) or not data:
            return [], [
                MarketWarning(
                    kind="missing_component",
                    message="cnn fear_and_greed_historical.data is empty; sparkline history is "
                    "unavailable",
                )
            ]

        points: list[MacroPoint] = []
        for row in data:
            if not isinstance(row, dict) or not _is_finite_number(row.get("x")):
                # No usable date -- cannot place this row anywhere on the sparkline, so it is
                # dropped rather than invented.
                continue
            date = _epoch_ms_to_date(float(row["x"]))
            # A non-numeric `y` becomes a published gap (`value=None`), the same convention
            # `MacroPoint` uses for FRED's missing observations -- not a dropped row, so a break
            # still shows in the sparkline instead of a silently shortened series.
            value = _to_optional_float(row.get("y"))
            points.append(MacroPoint(date=date, value=value))
        return points, []

    def _parse_components(
        self, payload: dict[str, Any]
    ) -> tuple[list[FearGreedComponent], list[MarketWarning]]:
        components: list[FearGreedComponent] = []
        warnings: list[MarketWarning] = []

        for key, label in _COMPONENT_LABELS.items():
            block = payload.get(key)
            if not isinstance(block, dict):
                warnings.append(
                    MarketWarning(
                        kind="missing_component",
                        message=f"cnn response has no {key!r} ({label}) block",
                    )
                )
                components.append(_component(key=key, label=label, raw_value=None))
                continue

            found = _last_numeric_point(block.get("data"))
            if found is None:
                warnings.append(
                    MarketWarning(
                        kind="missing_component",
                        message=f"cnn {key!r} ({label}) block has no usable numeric data",
                    )
                )
                components.append(_component(key=key, label=label, raw_value=None))
                continue

            as_of, raw_value = found

            # Trust the block's own top-level `rating`, paired with its top-level `score` -- see the
            # module docstring for the disagreement this sidesteps.
            rating: Rating | None = None
            rating_raw = block.get("rating")
            if isinstance(rating_raw, str):
                try:
                    rating = Rating(rating_raw)
                except ValueError:
                    rating = None

            components.append(
                _component(
                    key=key, label=label, raw_value=raw_value, rating=rating, as_of=as_of
                )
            )

        return components, warnings

    # -- Public API ---------------------------------------------------------

    def fetch(self) -> FearGreed:
        payload = self._get()

        fg = payload.get("fear_and_greed")
        if not isinstance(fg, dict):
            raise ProviderResponseError(
                "cnn response has no 'fear_and_greed' block", provider=self.name
            )

        score = fg.get("score")
        rating_raw = fg.get("rating")
        timestamp = fg.get("timestamp")
        if not _is_finite_number(score) or not isinstance(rating_raw, str) or not timestamp:
            raise ProviderResponseError(
                "cnn 'fear_and_greed' block is missing score, rating or timestamp",
                provider=self.name,
            )

        try:
            rating = Rating(rating_raw)
        except ValueError as exc:
            raise ProviderResponseError(
                f"cnn returned an unrecognised rating {rating_raw!r}", provider=self.name
            ) from exc

        try:
            as_of = dt.datetime.fromisoformat(str(timestamp)).astimezone(dt.UTC).date()
        except ValueError as exc:
            raise ProviderResponseError(
                f"cnn timestamp {timestamp!r} could not be parsed", provider=self.name
            ) from exc

        history, history_warnings = self._parse_history(payload)
        components, component_warnings = self._parse_components(payload)

        return FearGreed(
            score=float(score),
            rating=rating,
            source=FearGreedSource.CNN,
            as_of=as_of,
            components=components,
            previous_close=_to_optional_float(fg.get("previous_close")),
            previous_week=_to_optional_float(fg.get("previous_1_week")),
            previous_month=_to_optional_float(fg.get("previous_1_month")),
            previous_year=_to_optional_float(fg.get("previous_1_year")),
            history=history,
            warnings=[*history_warnings, *component_warnings],
        )

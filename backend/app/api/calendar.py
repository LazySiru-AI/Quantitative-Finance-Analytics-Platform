"""The event calendar endpoint: FOMC meetings and this portfolio's earnings dates in one request.

Thin on purpose, the same way `app.api.macro` is thin. Every failure this router could translate
into an HTTP status has already been absorbed one layer down in `app.market.calendar.build_calendar`:
FOMC never raises (it degrades to a bundled snapshot with a warning -- see `app.market.fomc`), and a
dead Nasdaq degrades only the earnings half of the response, never the whole request -- see that
module's docstring for why `holdings_covered=0` plus a `provider_fallback` warning is a 200, not a
5xx. `_handle` below exists for the genuine remainder: some other `ProviderError` this router did not
anticipate escaping the aggregator. In ordinary operation this endpoint should never actually return a
5xx.

**`refresh`** is this endpoint's escape hatch, the same shape `/api/macro/snapshot?refresh=true`
already has, but wired differently because `build_calendar` takes an `httpx.Client` rather than a
caching decorator to bypass: when `refresh` is set, this router builds its own client over a
zero-TTL `CachingTransport` and hands that to `build_calendar` instead of letting it construct its own
default (positive-TTL) client. A `ttl=0.0` entry is never fresh on read (see `CachingTransport._read`'s
own `>=` comparison), so every request under `refresh=true` pays for a real round trip to both FOMC
and Nasdaq -- still going through the same on-disk cache machinery (and therefore still leaving a
readable entry behind for the *next*, non-refresh request), just never trusting what it finds there.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.config import Settings, get_settings
from app.market import calendar
from app.market.cache import CachingTransport
from app.market.calendar_models import EventCalendar
from app.market.providers.base import ProviderError, ProviderUnavailable

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


def _handle(exc: ProviderError) -> HTTPException:
    """The same two-way split every other router in this package uses: a confirmed-down upstream is
    503, anything else this router did not specifically anticipate is 502. See the module docstring
    for why this branch should be rare in practice -- `build_calendar` absorbs provider failures
    itself rather than raising them here."""
    if isinstance(exc, ProviderUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


def _refresh_client(cfg: Settings) -> httpx.Client:
    """A client over the same on-disk cache, pinned to `ttl=0.0` so every read is treated as
    expired -- see the module docstring's `refresh` section."""
    transport = CachingTransport(httpx.HTTPTransport(), cfg.cache_dir / "http", ttl=0.0)
    return httpx.Client(transport=transport, timeout=10.0)


@router.get("/events", response_model=EventCalendar)
def events(days: int = Query(60, ge=1, le=365), refresh: bool = False) -> EventCalendar:
    """FOMC meetings plus this portfolio's earnings dates, over `[today, today + days]`.

    `days` is bounded to `[1, 365]` by FastAPI before this function ever runs -- `days=0` or a window
    over a year out is a 422, the caller's mistake to fix, not a degraded upstream to report. The
    earnings half of the response is still capped at 45 days regardless of how large `days` is; see
    `app.market.calendar`'s module docstring for why, and the `partial_window` warning that names the
    horizon actually covered when `days` exceeds it.
    """
    cfg = get_settings()
    client = _refresh_client(cfg) if refresh else None
    try:
        return calendar.build_calendar(days=days, settings=cfg, client=client)
    except ProviderError as exc:
        raise _handle(exc) from exc

"""Live-quote endpoints: `GET /api/paperlive/quotes` for a one-shot snapshot, `GET
/api/paperlive/stream` for the same shape pushed over Server-Sent Events.

Both read from one process-wide `app.market.live.LiveQuoteSource` -- a background poll (or, behind
`Settings.paperlive_transport == "stream"`, a best-effort Yahoo WebSocket stream that falls back to
polling on its own, see that module's docstring) -- rather than each request driving its own
provider round trip. N tabs watching the same symbol therefore cost one upstream fetch per interval,
not N.

**Data plumbing only.** Nothing here writes an order, and nothing under `app.paperdesk`, `app.paper`
or `app.tournament` is touched -- see this shard's own scope fence. A later shard wires this into
execution; this one only has to make the price visible.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from decimal import Decimal
from typing import Annotated, Final

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from app.config import Settings, get_settings
from app.market import livefeed
from app.market.live import LiveQuoteSource, LiveSnapshot

router = APIRouter(prefix="/api/paperlive", tags=["paperlive"])

#: Same alphabet `app.api.market._SYMBOL` uses for the same reason -- Parquet partition / Yahoo
#: ticker spellings, including index (`^TNX`) and futures (`CL=F`) forms. Declared locally rather
#: than imported: this shard's scope fence does not include `app.api.market`, and the two modules
#: agreeing on one regex is worth less than this router staying importable independent of a file
#: outside this shard.
_SYMBOL_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9.\-^=]{1,16}$")

#: Hard cap on symbols per request, for both routes. A `GET /stream` above this would hold open one
#: SSE connection re-fetching an unbounded snapshot on every tick; `/quotes` gets the same cap so the
#: two routes behave identically for the same query rather than one silently accepting what the
#: other rejects.
_MAX_SYMBOLS: Final[int] = 50

#: How often the SSE stream re-checks the client hasn't gone away, and the floor under how often it
#: can re-emit data or a keepalive. Independent of the underlying poll cadence
#: (`Settings.paperlive_poll_seconds`/`paperlive_idle_poll_seconds`, which govern how often the
#: shared `LiveQuoteSource` itself refreshes) -- this only bounds how promptly an abandoned
#: connection's generator notices and exits, which is what keeps a slow poll tier from also meaning
#: "a dropped tab's server-side generator lingers for up to a minute".
_STREAM_TICK_SECONDS: Final[float] = 1.0

#: Server-Sent Events comment line sent when no real event has gone out recently, so an intermediary
#: proxy with an idle-connection timeout does not decide the stream is dead and drop it.
_KEEPALIVE_SECONDS: Final[float] = 15.0


def _parse_symbols(raw: str) -> list[str]:
    """`"AAPL,MSFT"` -> `["AAPL", "MSFT"]`: upper-cased, de-duplicated (first occurrence wins),
    validated against `_SYMBOL_RE`, and bounded by `_MAX_SYMBOLS` -- every failure mode here is a
    client mistake, so every one of them is a 422, not a 400 or a 500.
    """
    symbols: list[str] = []
    seen: set[str] = set()
    for piece in raw.split(","):
        symbol = piece.strip().upper()
        if not symbol:
            continue
        if not _SYMBOL_RE.match(symbol):
            raise HTTPException(status_code=422, detail=f"invalid symbol: {piece!r}")
        if symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)
    if not symbols:
        raise HTTPException(status_code=422, detail="no symbols given")
    if len(symbols) > _MAX_SYMBOLS:
        raise HTTPException(
            status_code=422,
            detail=f"too many symbols: {len(symbols)} requested, {_MAX_SYMBOLS} max",
        )
    return symbols


def _require_enabled(cfg: Settings) -> None:
    if not cfg.paperlive_enabled:
        raise HTTPException(
            status_code=503,
            detail="paperlive is disabled (set INVDASH_PAPERLIVE_ENABLED=1 to turn it on)",
        )


# ---------------------------------------------------------------------------
# Wire shapes -- the frontend is written against this literal shape; do not rename any field.
# ---------------------------------------------------------------------------


class LiveQuoteOut(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    price: Decimal
    previous_close: Decimal | None = None
    change: Decimal | None = None
    change_pct: Decimal | None = None
    ts: dt.datetime
    stale: bool
    source: str


class LiveQuoteErrorOut(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    message: str


class LiveQuotesResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    as_of: dt.datetime
    market_state: str
    transport: str
    healthy: bool
    quotes: list[LiveQuoteOut]
    errors: list[LiveQuoteErrorOut]


def _to_response(snapshot: LiveSnapshot) -> LiveQuotesResponse:
    return LiveQuotesResponse(
        as_of=snapshot.as_of,
        market_state=snapshot.market_state,
        transport=snapshot.transport,
        healthy=snapshot.healthy,
        quotes=[
            LiveQuoteOut(
                symbol=q.symbol,
                price=q.price,
                previous_close=q.previous_close,
                change=q.change,
                change_pct=q.change_pct,
                ts=q.ts,
                stale=q.stale,
                source=q.source,
            )
            for q in snapshot.quotes
        ],
        errors=[LiveQuoteErrorOut(symbol=e.symbol, message=e.message) for e in snapshot.errors],
    )


# ---------------------------------------------------------------------------
# Source access -- one process-wide instance, which now lives in `app.market.livefeed` rather than
# here. Tests replace the whole accessor (`monkeypatch.setattr(paperlive, "_source", lambda: fake)`),
# the same pattern `tests/test_market_api.py` already uses for `app.api.market._registry` -- see that
# file's `client` fixture -- so this stays a function, not an imported name.
# ---------------------------------------------------------------------------


def _source() -> LiveQuoteSource:
    """The shared live-quote source, from `app.market.livefeed`.

    **This used to own the singleton itself, and moving it out is the point of the change.** A source
    built and held inside an HTTP router only ever exists on a browser request's terms: a symbol is
    watched because a tab asked, and evicted ten minutes after the last tab went away. Agents, the
    evidence layer and the keep-warm daemon are not tabs and must not have to import an API router to
    get a price -- so the instance moved to `app.market.livefeed`, which those callers share with
    these two routes. Both halves therefore see the same cached quotes and cost one upstream fetch
    between them, which was already this router's own promise (see the module docstring) and is now
    true process-wide rather than just across HTTP callers.
    """
    return livefeed.source(get_settings())


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

SymbolsParam = Annotated[str, Query(min_length=1, description="Comma-separated symbols, e.g. AAPL,MSFT")]


@router.get("/quotes", response_model=LiveQuotesResponse)
def quotes(symbols: SymbolsParam) -> LiveQuotesResponse:
    """A one-shot snapshot of the shared live-quote source for `symbols`.

    Never fetches from the network on this request thread beyond the one-time synchronous bootstrap
    a brand-new symbol pays (see `PollingQuoteSource.subscribe`) -- every symbol already being
    watched by any earlier caller answers straight from the source's own lock-guarded cache.
    """
    cfg = get_settings()
    _require_enabled(cfg)
    symbol_list = _parse_symbols(symbols)
    snapshot = _source().snapshot(symbol_list)
    return _to_response(snapshot)


async def _never_disconnected() -> bool:
    return False


async def _event_stream(
    source: LiveQuoteSource,
    symbols: Sequence[str],
    *,
    poll_interval: float,
    idle_interval: float | None = None,
    is_disconnected: Callable[[], Awaitable[bool]] = _never_disconnected,
    keepalive_interval: float = _KEEPALIVE_SECONDS,
    tick_seconds: float = _STREAM_TICK_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AsyncIterator[str]:
    """The SSE body. One `event: quotes` frame immediately on connect, another every `poll_interval`
    seconds while the market is open -- or every `idle_interval` seconds when it is not, mirroring
    the cadence `PollingQuoteSource` already applies to its own upstream fetches. Without that
    second tier this loop re-sent a byte-identical snapshot twelve times per actual refresh with the
    market closed: harmless upstream, since the source dedupes, but pointless traffic to every
    connected browser. `idle_interval` defaults to `poll_interval`, i.e. single-tier behaviour.
    Plus a `: keepalive` comment whenever `keepalive_interval` seconds pass
    without a real event -- so a proxy sitting between the browser and this process never sees the
    connection go quiet. Ticks on `tick_seconds` (short, and never the full `poll_interval` or
    `keepalive_interval` in one sleep), which bounds how promptly this loop notices anything that
    should stop it. **No thread is spawned for this connection at all** -- `source.snapshot` runs
    off the event loop via `asyncio.to_thread` so a slow first-ever lookup of a new symbol cannot
    stall every other request this process is serving, and the generator itself holds nothing but a
    coroutine frame.

    **`is_disconnected` defaults to a no-op and the real route never overrides it.** The obvious
    design -- call `Request.is_disconnected()` on every tick -- was tried and reverted: Starlette's
    own `StreamingResponse.__call__` already races a `listen_for_disconnect(receive)` task against
    the one consuming this generator (see `starlette.responses.StreamingResponse.__call__`, the
    branch taken whenever the ASGI server reports `spec_version < 2.4` -- which is every request
    real `uvicorn` serves today, per its own `h11_impl`/`httptools_impl`, not only a test-transport
    quirk). A second concurrent reader calling `receive()` for the same connection races that
    listener for the same disconnect message; under `httpx`'s ASGI test transport this reliably
    deadlocked the whole response (confirmed while writing this shard's tests -- the very first
    frame never arrived). Termination on a real disconnect is therefore left entirely to Starlette's
    own listener, which cancels this generator's task the moment it sees `http.disconnect` -- the
    ordinary, correct way an async generator "terminates cleanly" in asyncio is by being cancelled,
    not by polling for permission to stop. `is_disconnected` stays as a parameter purely so
    `tests/test_api_paperlive.py` can drive disconnect-after-N-ticks and keepalive-scheduling
    directly, without an HTTP connection in the loop at all.
    """
    idle = poll_interval if idle_interval is None else idle_interval
    tick = min(poll_interval, idle, keepalive_interval, tick_seconds)
    if tick <= 0:
        tick = 1.0
    # The cadence in force right now. Starts fast so a market-open connection never waits out a
    # full idle interval before its first frame; re-derived from each snapshot's `market_state`.
    current = poll_interval
    last_data = time.monotonic() - current  # forces the immediate first emission below
    last_event = time.monotonic()
    while True:
        if await is_disconnected():
            return
        now = time.monotonic()
        if now - last_data >= current:
            snapshot = await asyncio.to_thread(source.snapshot, symbols)
            payload = _to_response(snapshot).model_dump_json()
            yield f"event: quotes\ndata: {payload}\n\n"
            current = poll_interval if snapshot.market_state == "REGULAR" else idle
            last_data = now
            last_event = now
        elif now - last_event >= keepalive_interval:
            yield ": keepalive\n\n"
            last_event = now
        await sleep(tick)


@router.get("/stream")
async def stream(symbols: SymbolsParam) -> StreamingResponse:
    """The same shape `GET /quotes` returns, pushed as Server-Sent Events: one `event: quotes` frame
    on connect and on every refresh, plus a `: keepalive` comment line at least every 15 seconds.
    Terminates when the client disconnects -- see `_event_stream`'s docstring for why that is left to
    Starlette's own connection handling rather than checked from inside this generator.
    """
    cfg = get_settings()
    _require_enabled(cfg)
    symbol_list = _parse_symbols(symbols)
    source = _source()

    generator = _event_stream(
        source,
        symbol_list,
        poll_interval=cfg.paperlive_poll_seconds,
        idle_interval=cfg.paperlive_idle_poll_seconds,
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

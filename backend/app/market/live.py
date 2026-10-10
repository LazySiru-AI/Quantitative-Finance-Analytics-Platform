"""Live-quote plumbing for the paper desk's screen.

**This shard delivers data plumbing only.** Nothing here writes an order or touches
``app.paperdesk``/``app.paper``/``app.tournament`` -- a later shard wires this into execution. See
``backend/app/api/paperlive.py`` for the two routes built on top of this module.

**Design: the polling transport is the product; the WebSocket transport is an unverified, flagged
optimisation that must fall back automatically.** ``wss://streamer.finance.yahoo.com/?version=2``
accepts a connection and accepts a ``{"subscribe": [...]}`` message -- that much was confirmed live.
It sent **zero frames in a 20-second probe**, because the probe ran at 02:51 ET on a Sunday with the
market closed, so the socket being real is confirmed but **its frame format is not** -- there was
nothing to capture. :class:`YahooStreamQuoteSource` below hand-decodes Yahoo's ``PricingData``
protobuf message (no protobuf dependency exists in this repo, and none is added here) using field
numbers taken from the shard brief (``1`` = id, ``2`` = price, ``7`` = day volume, ``13`` = change
percent) -- **these are asserted, not verified against real bytes**, and the frame envelope
(base64 text frame vs. a JSON wrapper carrying a base64 ``message``) is likewise a best guess from
public write-ups of this endpoint, not a captured sample. Every decoded price is checked against a
fresh REST quote (:func:`ProviderRegistry.get_quote`) before it is ever trusted, and the source
falls back to :class:`PollingQuoteSource` -- permanently, for its own lifetime -- the moment the
connect fails, no frame decodes within the bootstrap window, or a decoded price disagrees with the
REST quote by more than a small tolerance. Nothing here can emit an unvalidated stream price.

**The 30-second HTTP cache is bypassed for this path.** ``app.market.cache._META_LOOKUP_TTL`` gives
Yahoo's quote/profile lookup a 30-second on-disk cache, shared by every caller of
``default_registry()``. Polling through that cache at the fast tier's default 5-second cadence would
mostly replay the same cached response -- up to five out of every six polls would not be a fresh
look at the market at all, which defeats the purpose of a *live* quote source. :func:`build_polling_
registry` therefore builds a small, private :class:`~app.market.registry.ProviderRegistry` around a
plain, uncached ``httpx.Client`` (via a bare ``YahooProvider()``) instead of sharing
``default_registry()``'s cached one -- every poll is a genuine round trip. This trades a little more
Yahoo traffic for prices that are actually as fresh as the poll interval claims; see
``Settings.paperlive_poll_seconds``.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import json
import logging
import math
import struct
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Final, Protocol

from app.config import Settings, get_settings
from app.market.models import BarSource, Quote
from app.market.providers.yahoo import YahooProvider
from app.market.registry import ProviderRegistry

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_STALE_AFTER_SECONDS",
    "DEFAULT_WATCH_IDLE_SECONDS",
    "LiveQuote",
    "LiveQuoteError",
    "LiveQuoteSource",
    "LiveSnapshot",
    "PollingQuoteSource",
    "YahooStreamQuoteSource",
    "build_polling_registry",
    "build_source",
    "decode_pricing_frame",
    "parse_protobuf_fields",
]


# ---------------------------------------------------------------------------
# Wire-shape-adjacent value types -- see app.api.paperlive for the actual pydantic response models.
# These stay plain dataclasses so this module has no FastAPI/pydantic dependency of its own.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LiveQuote:
    """One symbol's live snapshot, already shaped for the wire (``Decimal`` prices, UTC timestamp).

    Distinct from :class:`app.market.models.Quote`, which is the raw provider/store shape and
    carries a ``float`` price -- this is what actually crosses the HTTP boundary.
    """

    symbol: str
    price: Decimal
    previous_close: Decimal | None
    change: Decimal | None
    change_pct: Decimal | None
    ts: dt.datetime
    stale: bool
    source: str


@dataclass(frozen=True)
class LiveQuoteError:
    symbol: str
    message: str


@dataclass(frozen=True)
class LiveSnapshot:
    """What one call to :meth:`LiveQuoteSource.snapshot` returns -- the whole contract body except
    the pydantic wrapping, which ``app.api.paperlive`` adds."""

    as_of: dt.datetime
    market_state: str
    transport: str
    healthy: bool
    quotes: tuple[LiveQuote, ...]
    errors: tuple[LiveQuoteError, ...]


class LiveQuoteSource(Protocol):
    """What both :class:`PollingQuoteSource` and :class:`YahooStreamQuoteSource` implement.

    A ``Protocol`` rather than an ABC, matching how this codebase already describes its provider
    seams (``app.market.providers.base.BarProvider`` and friends) -- structural typing, no shared
    base class required.
    """

    def snapshot(self, symbols: Sequence[str]) -> LiveSnapshot: ...

    def close(self) -> None: ...


# ---------------------------------------------------------------------------
# Shared tuning + helpers
# ---------------------------------------------------------------------------

#: A quote older than this is reported `stale=True` rather than silently shown as current. Chosen as
#: a small multiple of the *slow* poll tier (`Settings.paperlive_idle_poll_seconds`, default 60s):
#: long enough that one ordinary idle-tier poll cycle plus network latency never trips it, short
#: enough that a genuinely stuck feed (the poll thread died, a symbol has failed every cycle) is
#: flagged well within a couple of minutes rather than showing a silently ageing price forever.
DEFAULT_STALE_AFTER_SECONDS: Final[float] = 150.0

#: How many consecutive poll cycles in which *every* watched symbol failed before `healthy` flips
#: `False`. `1` would be too twitchy -- a single bad cycle against a flaky upstream is normal and
#: already reported per-symbol via `errors`; this is specifically the "designed to continue hides
#: total failure" case, where the loop keeps running and reporting `running` while doing nothing
#: useful. Three consecutive fully-dead cycles is long enough to rule out one unlucky moment, short
#: enough that a real outage is flagged within a few poll intervals, not after everyone gives up.
_UNHEALTHY_AFTER_CYCLES: Final[int] = 3

#: How long a watched symbol may go without being re-requested (a `subscribe`/`snapshot` call naming
#: it) before the background poll loop drops it from the watch set entirely.
#:
#: **The defect this fixes.** `subscribe` had no companion `unsubscribe` and no expiry: every symbol
#: any client ever passed to `GET /api/paperlive/quotes` or `/stream` was added to `_watched` and
#: polled every `fast_interval`/`idle_interval` seconds for the rest of the *process's* life, whether
#: or not anyone was still asking about it. The per-request `_MAX_SYMBOLS` cap in `app.api.paperlive`
#: bounds one request; nothing bounded the cumulative set, so a long browsing session -- or a client
#: that changes which symbols it watches over time -- ratchets up permanent background upstream
#: traffic that never comes back down.
#:
#: **Why 600s (10 minutes).** Well above `DEFAULT_STALE_AFTER_SECONDS` (150s, 2.5x the slow poll
#: tier) so a symbol is already reported `stale=True` -- the cheap, reversible early warning -- long
#: before eviction, the expensive, only-recoverable-by-a-fresh-subscribe last resort, ever considers
#: it. Also well above `Settings.paperlive_idle_poll_seconds`'s own 60s slow tier (10x it), so neither
#: poll tier's own cadence, nor one slow or delayed request, is ever mistaken for abandonment.
#: `GET /stream` (`app.api.paperlive._event_stream`) calls `source.snapshot` -- which calls
#: `subscribe` -- on every refresh tick (every `poll_interval`/`idle_interval` seconds), so a
#: connection an active browser tab is still holding open keeps its own symbols' last-requested time
#: current on its own; only a symbol nobody has asked about in ten straight minutes is dropped.
DEFAULT_WATCH_IDLE_SECONDS: Final[float] = 600.0


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _to_decimal(value: float | None) -> Decimal | None:
    """`None` stays `None`; anything else round-trips through `str` first.

    `Decimal(some_float)` reproduces the binary float's exact (and usually ugly) value --
    `Decimal(3.3457)` is `Decimal('3.345699999999999...')`. `Decimal(str(some_float))` instead keeps
    the digits Python's own `repr`/`str` already chose, which is the shortest string that round-trips
    to the same float -- exactly what belongs on the wire.
    """
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _money(value: float | None) -> Decimal | None:
    """A price or price delta, quantized to cents for display.

    `_to_decimal` faithfully preserves whatever float the provider sent, which is the right
    behaviour for a value that is already clean -- but Yahoo computes `change` as a float
    subtraction upstream, so a $10.35 move arrives as `10.349999999999966` and `str` preserves
    every digit of it. Rendering that verbatim puts a fifteen-decimal price change on screen.
    Quantizing here rather than in the frontend keeps the rounding decision on the wire, where the
    rest of this codebase's money already lives.
    """
    dec = _to_decimal(value)
    if dec is None:
        return None
    try:
        return dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return dec


def _percent(value: float | None) -> Decimal | None:
    """A percentage, quantized to four places -- enough for a basis-point-level move."""
    dec = _to_decimal(value)
    if dec is None:
        return None
    try:
        return dec.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return dec


def _dominant_market_state(raw_quotes: Sequence[Quote]) -> str:
    """The single `market_state` a multi-symbol snapshot reports.

    The wire contract has one `market_state` field for the whole response, but each underlying
    `Quote` carries its own (different symbols can genuinely be in different sessions). `"REGULAR"`
    wins if *any* requested symbol is in it -- that is the state that matters for "is this price
    moving right now", which is the question this field exists to answer. Otherwise this reports the
    first symbol's state, and `"UNKNOWN"` only when nothing was resolved at all (every symbol errored).
    """
    if not raw_quotes:
        return "UNKNOWN"
    for q in raw_quotes:
        if q.market_state == "REGULAR":
            return "REGULAR"
    first = raw_quotes[0].market_state
    return first if first else "UNKNOWN"


def _to_live_quote(q: Quote, *, now: dt.datetime, stale_after: float) -> LiveQuote:
    ts = q.ts if q.ts.tzinfo is not None else q.ts.replace(tzinfo=dt.UTC)
    age = (now - ts).total_seconds()
    price = _money(q.price)
    return LiveQuote(
        symbol=q.symbol,
        price=price if price is not None else Decimal("0.00"),
        previous_close=_money(q.previous_close),
        change=_money(q.change),
        change_pct=_percent(q.change_pct),
        ts=ts,
        stale=age > stale_after,
        source=q.source.value if isinstance(q.source, BarSource) else str(q.source),
    )


def build_polling_registry() -> ProviderRegistry:
    """A quote-only registry that bypasses the shared 30-second HTTP cache -- see the module
    docstring's "The 30-second HTTP cache is bypassed" section for why. ``YahooProvider()`` built
    with no explicit client constructs its own plain ``httpx.Client`` (see that class's
    ``__init__``), which never passes through ``app.market.cache.CachingTransport`` the way the
    shared client ``default_registry()`` builds does.
    """
    return ProviderRegistry(profile_providers=(YahooProvider(),))


# ---------------------------------------------------------------------------
# PollingQuoteSource -- the default, standalone-verified transport.
# ---------------------------------------------------------------------------


class PollingQuoteSource:
    """Polls :meth:`ProviderRegistry.get_quote` for every watched symbol on a daemon thread,
    following the same idiom as ``app.market.refresh`` (a lock-guarded module of state, a daemon
    thread started lazily, failures counted rather than raised). Symbols are watched on demand: the
    first :meth:`snapshot`/:meth:`subscribe` call for a symbol fetches it synchronously once (so the
    caller never sees an empty result for a brand-new symbol) and adds it to the set the background
    thread keeps refreshing from then on.

    **Never dies on a bad symbol.** :meth:`_poll_symbols` wraps each symbol's fetch in its own
    ``try/except`` -- one failure is recorded in ``errors`` and the loop moves on. **Never silently
    reports "running" through total failure**: ``_consecutive_total_failures`` counts full cycles in
    which nothing succeeded, and :attr:`healthy` goes ``False`` once that streak reaches
    ``unhealthy_after_cycles`` -- seeing "healthy: true" forever while every symbol errors every
    cycle is exactly the failure mode this guards against.

    **Poll cadence adapts to the market.** One thread, one interval at a time, chosen each cycle by
    whether *any* currently-cached quote reports ``market_state == "REGULAR"`` -- ``fast_interval``
    if so, ``idle_interval`` otherwise. This is a single global cadence across every watched symbol,
    not a per-symbol one; a mixed watchlist (one open market, one closed) polls at the faster of the
    two, which costs a few extra idle-tier requests rather than under-refreshing the open one.

    **The watch set tracks current client interest, not history.** Every :meth:`subscribe` call
    (including the one :meth:`snapshot` makes internally) stamps the symbols it names with the current
    time; the poll loop drops any symbol not stamped within ``watch_idle_seconds`` from ``_watched``
    (and its cached quote/error) at the start of every cycle -- see :data:`DEFAULT_WATCH_IDLE_SECONDS`
    for why that default is well above both poll tiers and :data:`DEFAULT_STALE_AFTER_SECONDS`. A
    symbol dropped this way is not gone for good: the next :meth:`subscribe`/:meth:`snapshot` naming
    it re-adds it exactly as if it were brand new, paying the same one-time synchronous fetch a truly
    new symbol always pays.
    """

    def __init__(
        self,
        *,
        registry_factory: Callable[[], ProviderRegistry] | None = None,
        fast_interval: float = 5.0,
        idle_interval: float = 60.0,
        stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
        unhealthy_after_cycles: int = _UNHEALTHY_AFTER_CYCLES,
        watch_idle_seconds: float = DEFAULT_WATCH_IDLE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._registry_factory = registry_factory or build_polling_registry
        self._fast_interval = fast_interval
        self._idle_interval = idle_interval
        self._stale_after = stale_after_seconds
        self._unhealthy_after = unhealthy_after_cycles
        self._watch_idle_seconds = watch_idle_seconds
        #: Injectable purely so tests can move "time" without a real sleep -- defaults to the real
        #: monotonic clock, which is what every idle-window comparison should use in production (never
        #: wall-clock time, which can jump backwards across an NTP correction or a DST change).
        self._clock = clock

        self._lock = threading.Lock()
        self._watched: set[str] = set()
        self._last_requested: dict[str, float] = {}
        """`monotonic()` time of the most recent `subscribe` call naming each watched symbol -- the
        basis `_evict_idle_symbols` compares `watch_idle_seconds` against. Every entry in `_watched`
        has a corresponding entry here; the two are always updated together."""
        self._quotes: dict[str, Quote] = {}
        self._errors: dict[str, str] = {}
        self._consecutive_total_failures = 0

        self._registry: ProviderRegistry | None = None
        self._registry_lock = threading.Lock()

        self._thread_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # -- lifecycle -----------------------------------------------------------------------------

    def _ensure_thread(self) -> None:
        with self._thread_lock:
            if self._thread is None or not self._thread.is_alive():
                self._stop_event.clear()
                self._thread = threading.Thread(
                    target=self._run, name="live-quote-poll", daemon=True
                )
                self._thread.start()

    def close(self) -> None:
        """Stop the background thread. Tests use this to avoid leaking daemon threads across cases;
        production never calls it -- the source lives for the process, same as `app.market.refresh`.
        """
        self._stop_event.set()
        with self._thread_lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)

    def _get_registry(self) -> ProviderRegistry | None:
        with self._registry_lock:
            if self._registry is None:
                try:
                    self._registry = self._registry_factory()
                except Exception:
                    logger.exception("live quote poll: failed to build a provider registry")
                    return None
            return self._registry

    # -- subscription + read ---------------------------------------------------------------------

    def subscribe(self, symbols: Sequence[str]) -> None:
        """Register `symbols` for ongoing background polling, fetching any brand-new ones once,
        synchronously, right now -- see the class docstring for why.

        Every call -- new symbols and already-watched ones alike -- stamps `_last_requested` with the
        current time, which is what keeps a symbol a caller is still actively asking about (directly,
        or indirectly through `snapshot`/an open `/stream` connection) from ever being judged idle by
        `_evict_idle_symbols`.
        """
        upper = [s.upper() for s in symbols]
        now = self._clock()
        with self._lock:
            new = [s for s in upper if s not in self._watched]
            self._watched.update(upper)
            for s in upper:
                self._last_requested[s] = now
        self._ensure_thread()
        if new:
            registry = self._get_registry()
            if registry is not None:
                self._poll_symbols(new, registry)

    @property
    def healthy(self) -> bool:
        with self._lock:
            return self._consecutive_total_failures < self._unhealthy_after

    def snapshot(self, symbols: Sequence[str]) -> LiveSnapshot:
        upper = [s.upper() for s in symbols]
        self.subscribe(upper)
        now = _now()
        with self._lock:
            raw = [self._quotes[s] for s in upper if s in self._quotes]
            errors = [
                LiveQuoteError(symbol=s, message=self._errors.get(s, "no quote available yet"))
                for s in upper
                if s not in self._quotes
            ]
        quotes = tuple(_to_live_quote(q, now=now, stale_after=self._stale_after) for q in raw)
        return LiveSnapshot(
            as_of=now,
            market_state=_dominant_market_state(raw),
            transport="poll",
            healthy=self.healthy,
            quotes=quotes,
            errors=tuple(errors),
        )

    # -- the poll loop -----------------------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._evict_idle_symbols()
            with self._lock:
                watched = sorted(self._watched)
            if watched:
                registry = self._get_registry()
                if registry is not None:
                    self._poll_symbols(watched, registry)
                else:
                    with self._lock:
                        self._consecutive_total_failures += 1
            interval = self._fast_interval if self._is_regular_now() else self._idle_interval
            self._stop_event.wait(interval)

    def _evict_idle_symbols(self) -> None:
        """Drop every watched symbol not named by a `subscribe` call within `watch_idle_seconds`,
        along with its cached quote/error -- see the class docstring's "watch set tracks current
        client interest" section and `DEFAULT_WATCH_IDLE_SECONDS` for why. Runs once per poll cycle,
        before that cycle's fetch, so an evicted symbol never costs the upstream request it would
        otherwise have paid for this tick.
        """
        now = self._clock()
        with self._lock:
            idle = [
                s
                for s in self._watched
                if now - self._last_requested.get(s, now) >= self._watch_idle_seconds
            ]
            for s in idle:
                self._watched.discard(s)
                self._last_requested.pop(s, None)
                self._quotes.pop(s, None)
                self._errors.pop(s, None)
        if idle:
            logger.info(
                "live quote poll: dropping %d symbol(s) not requested in %.0fs: %s",
                len(idle),
                self._watch_idle_seconds,
                ", ".join(sorted(idle)),
            )

    def _is_regular_now(self) -> bool:
        with self._lock:
            return any(q.market_state == "REGULAR" for q in self._quotes.values())

    def _poll_symbols(self, symbols: Sequence[str], registry: ProviderRegistry) -> None:
        """Fetch every symbol in `symbols`, one at a time. Every failure is caught here -- a
        provider raising is the *expected* shape of "this symbol didn't work right now", never a
        reason to stop polling the rest, and never allowed to escape and kill the thread."""
        any_success = False
        for symbol in symbols:
            try:
                quote = registry.get_quote(symbol)
            except Exception as exc:  # one bad symbol must never stop the others
                logger.info("live quote poll: %s failed: %s", symbol, exc)
                with self._lock:
                    self._errors[symbol] = str(exc)
                continue
            any_success = True
            with self._lock:
                self._quotes[symbol] = quote
                self._errors.pop(symbol, None)
        with self._lock:
            if any_success:
                self._consecutive_total_failures = 0
            else:
                self._consecutive_total_failures += 1


# ---------------------------------------------------------------------------
# YahooStreamQuoteSource -- flagged, best-effort, falls back permanently on any doubt.
# ---------------------------------------------------------------------------

WS_URL: Final[str] = "wss://streamer.finance.yahoo.com/?version=2"

#: Field numbers inside Yahoo's `PricingData` protobuf message, as asserted by this shard's brief
#: from public reverse-engineering write-ups of this endpoint. **Not verified against a real
#: captured frame** -- see the module docstring. Named constants rather than inline numbers so the
#: day someone captures a real frame and finds one wrong, the fix is one line.
_FIELD_ID: Final[int] = 1
_FIELD_PRICE: Final[int] = 2
_FIELD_DAY_VOLUME: Final[int] = 7
_FIELD_CHANGE_PERCENT: Final[int] = 13

_WIRE_VARINT: Final[int] = 0
_WIRE_64BIT: Final[int] = 1
_WIRE_LENGTH: Final[int] = 2
_WIRE_32BIT: Final[int] = 5


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise ValueError("truncated varint")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 63:  # a real protobuf varint is never this long; treat it as corrupt input
            raise ValueError("varint too long")


def parse_protobuf_fields(data: bytes) -> dict[int, Any]:
    """A minimal, hand-rolled protobuf wire-format scanner -- not a general decoder.

    No protobuf dependency exists in this repo and this shard does not add one (see the module
    docstring), so this reads exactly enough of the wire format to recover `PricingData`'s fields by
    number: varint (wire type 0) and 32-bit (wire type 5) fields are what `decode_pricing_frame`
    below actually needs; 64-bit and length-delimited fields are captured as raw bytes for
    completeness (length-delimited holds the `id` string) but never interpreted further here. A
    field repeated more than once keeps only its last occurrence, which protobuf itself treats as
    the field's effective value for a non-repeated field.
    """
    fields: dict[int, Any] = {}
    pos = 0
    n = len(data)
    while pos < n:
        tag, pos = _read_varint(data, pos)
        field_no = tag >> 3
        wire_type = tag & 0x7
        if wire_type == _WIRE_VARINT:
            value, pos = _read_varint(data, pos)
            fields[field_no] = value
        elif wire_type == _WIRE_64BIT:
            if pos + 8 > n:
                raise ValueError("truncated 64-bit field")
            fields[field_no] = data[pos : pos + 8]
            pos += 8
        elif wire_type == _WIRE_LENGTH:
            length, pos = _read_varint(data, pos)
            if length < 0 or pos + length > n:
                raise ValueError("truncated length-delimited field")
            fields[field_no] = data[pos : pos + length]
            pos += length
        elif wire_type == _WIRE_32BIT:
            if pos + 4 > n:
                raise ValueError("truncated 32-bit field")
            fields[field_no] = data[pos : pos + 4]
            pos += 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire_type}")
    return fields


def decode_pricing_frame(raw: bytes) -> dict[str, Any] | None:
    """Best-effort decode of one `PricingData` message into `{"symbol", "price", ...}`.

    Returns `None` -- never raises -- for anything that does not parse cleanly or does not carry
    both an id and a plausible (finite, positive) price, which is exactly the "decoding yields
    nothing" case the module docstring says must fall back to polling rather than emit a guess.
    """
    try:
        fields = parse_protobuf_fields(raw)
    except ValueError:
        return None

    id_bytes = fields.get(_FIELD_ID)
    price_bytes = fields.get(_FIELD_PRICE)
    if not isinstance(id_bytes, (bytes, bytearray)) or not isinstance(
        price_bytes, (bytes, bytearray)
    ):
        return None
    if len(price_bytes) != 4:
        return None
    try:
        symbol = id_bytes.decode("utf-8")
        price = struct.unpack("<f", price_bytes)[0]
    except (UnicodeDecodeError, struct.error):
        return None
    if not symbol or not math.isfinite(price) or price <= 0:
        return None

    result: dict[str, Any] = {"symbol": symbol, "price": price}

    volume_raw = fields.get(_FIELD_DAY_VOLUME)
    if isinstance(volume_raw, int) and volume_raw >= 0:
        result["day_volume"] = volume_raw

    change_pct_bytes = fields.get(_FIELD_CHANGE_PERCENT)
    if isinstance(change_pct_bytes, (bytes, bytearray)) and len(change_pct_bytes) == 4:
        try:
            change_pct = struct.unpack("<f", change_pct_bytes)[0]
        except struct.error:
            change_pct = None
        if change_pct is not None and math.isfinite(change_pct):
            result["change_pct"] = change_pct

    return result


def _extract_frame_bytes(message: str) -> bytes | None:
    """Best-effort unwrap of one WS text frame into raw `PricingData` bytes.

    **Unverified**, same as everything else about the wire format in this module (see the module
    docstring): public write-ups of Yahoo's v1/v2 stream describe the frame as either bare base64 of
    the protobuf message, or a JSON envelope (`{"type": "pricing", "message": "<base64>"}`) carrying
    it. This tries JSON first when the text looks like an object, falls back to treating the whole
    string as base64, and returns `None` -- triggering the polling fallback -- when neither decodes.
    """
    text = message.strip()
    if not text:
        return None
    payload = text
    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(obj, dict):
            return None
        candidate = obj.get("message")
        if not isinstance(candidate, str):
            return None
        payload = candidate
    try:
        return base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError):
        return None


class _StreamConnection(Protocol):
    """What `YahooStreamQuoteSource` needs from a websocket connection -- matches the subset of
    `websockets.sync.client.ClientConnection` this module actually calls, spelled out here so tests
    can inject a fake without importing `websockets` at all."""

    def send(self, message: str) -> None: ...

    def recv(self, timeout: float | None = None) -> str: ...

    def __enter__(self) -> _StreamConnection: ...

    def __exit__(self, *exc: object) -> None: ...


ConnectFn = Callable[[], "_StreamConnection"]


def _default_connect() -> Any:
    """The real connector. Imported lazily, inside the function, so that importing this module never
    requires `websockets` -- it is present in this environment only transitively via uvicorn, not as
    a direct dependency of this package (see `backend/pyproject.toml`), and `YahooStreamQuoteSource`
    is behind a default-off flag precisely because it may not always be available or trustworthy.
    """
    from websockets.sync.client import connect as ws_connect

    return ws_connect(WS_URL, open_timeout=10.0, close_timeout=2.0)


class YahooStreamQuoteSource:
    """Best-effort live stream, behind `Settings.paperlive_transport == "stream"` and off by
    default. See the module docstring for exactly what is and is not verified about the wire format.

    **Falls back to `PollingQuoteSource` permanently, for this instance's lifetime**, the first time
    any of the following happens: the connect itself fails; the subscribe send fails; the connection
    drops or errors; no frame decodes into a validated quote within `bootstrap_timeout` seconds of
    connecting. There is no reconnect/retry loop -- once this instance has given up, it has given up,
    and `snapshot()` answers entirely from the wrapped `PollingQuoteSource` from then on, with
    `transport="poll"` so the caller can see that happened (see the class's `snapshot` docstring).

    **Never trusts a decoded price outright.** The first frame decoded for a given symbol is checked
    against a fresh REST quote (`ProviderRegistry.get_quote`) before that symbol is ever served from
    the stream; a mismatch beyond `validation_tolerance` is treated the same as a decode failure for
    that symbol (logged, not raised) and the *whole source* falls back, on the reasoning that a wrong
    field mapping is a property of the decoder, not of one unlucky symbol.
    """

    def __init__(
        self,
        *,
        fallback: PollingQuoteSource,
        registry_factory: Callable[[], ProviderRegistry] | None = None,
        connect_fn: ConnectFn | None = None,
        bootstrap_timeout: float = 10.0,
        frame_timeout: float = 5.0,
        validation_tolerance: float = 0.05,
        stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
    ) -> None:
        self._fallback = fallback
        self._registry_factory = registry_factory or build_polling_registry
        self._connect_fn = connect_fn or _default_connect
        self._bootstrap_timeout = bootstrap_timeout
        self._frame_timeout = frame_timeout
        self._validation_tolerance = validation_tolerance
        self._stale_after = stale_after_seconds

        self._lock = threading.Lock()
        self._watched: set[str] = set()
        self._quotes: dict[str, Quote] = {}
        self._validated: set[str] = set()
        self._mode = "bootstrapping"  # "bootstrapping" | "stream" | "fallback"
        self._fallback_reason: str | None = None

        self._registry: ProviderRegistry | None = None
        self._registry_lock = threading.Lock()

        self._thread_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def close(self) -> None:
        self._stop_event.set()
        with self._thread_lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._fallback.close()

    def _get_registry(self) -> ProviderRegistry | None:
        with self._registry_lock:
            if self._registry is None:
                try:
                    self._registry = self._registry_factory()
                except Exception:
                    logger.exception("live quote stream: failed to build a provider registry")
                    return None
            return self._registry

    def _ensure_thread(self) -> None:
        with self._thread_lock:
            if self._thread is None or not self._thread.is_alive():
                self._stop_event.clear()
                self._thread = threading.Thread(
                    target=self._run, name="live-quote-stream", daemon=True
                )
                self._thread.start()

    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    @property
    def fallback_reason(self) -> str | None:
        with self._lock:
            return self._fallback_reason

    def snapshot(self, symbols: Sequence[str]) -> LiveSnapshot:
        """Stream-sourced quotes where available and validated; the wrapped `PollingQuoteSource` for
        everything else -- always kept subscribed as the backstop, both for symbols the stream has
        not delivered yet and for the entire response once this source has fallen back. `transport`
        is `"stream"` only while at least one requested symbol is actually being served from the
        validated stream cache; it is `"poll"` in every other case, including "still bootstrapping"
        and "gave up".
        """
        upper = [s.upper() for s in symbols]
        with self._lock:
            self._watched.update(upper)
        self._ensure_thread()
        # The fallback is always kept warm, whether or not the stream is currently trusted -- see
        # the class docstring. Cheap once a symbol is already watched (see PollingQuoteSource.
        # subscribe): only a brand-new symbol costs a synchronous fetch.
        self._fallback.subscribe(upper)

        with self._lock:
            stream_raw = {s: self._quotes[s] for s in upper if s in self._quotes}

        if not stream_raw:
            snap = self._fallback.snapshot(upper)
            return LiveSnapshot(
                as_of=snap.as_of,
                market_state=snap.market_state,
                transport="poll",
                healthy=snap.healthy,
                quotes=snap.quotes,
                errors=snap.errors,
            )

        now = _now()
        missing = [s for s in upper if s not in stream_raw]
        fallback_snap = self._fallback.snapshot(missing) if missing else None

        quotes = [
            _to_live_quote(q, now=now, stale_after=self._stale_after) for q in stream_raw.values()
        ]
        errors: list[LiveQuoteError] = []
        if fallback_snap is not None:
            quotes.extend(fallback_snap.quotes)
            errors.extend(fallback_snap.errors)

        state = _dominant_market_state(list(stream_raw.values()))
        if state == "UNKNOWN" and fallback_snap is not None:
            state = fallback_snap.market_state

        return LiveSnapshot(
            as_of=now,
            market_state=state,
            transport="stream",
            healthy=self._fallback.healthy,
            quotes=tuple(quotes),
            errors=tuple(errors),
        )

    # -- the stream loop -----------------------------------------------------------------------

    def _run(self) -> None:
        try:
            connection = self._connect_fn()
        except Exception as exc:
            logger.warning("live quote stream: connect failed, falling back to polling: %s", exc)
            self._give_up(f"connect failed: {exc}")
            return

        with connection:
            with self._lock:
                symbols = sorted(self._watched)
            try:
                connection.send(json.dumps({"subscribe": symbols}))
            except Exception as exc:
                logger.warning(
                    "live quote stream: subscribe failed, falling back to polling: %s", exc
                )
                self._give_up(f"subscribe failed: {exc}")
                return

            deadline = time.monotonic() + self._bootstrap_timeout
            while not self._stop_event.is_set():
                with self._lock:
                    still_bootstrapping = self._mode == "bootstrapping"
                if still_bootstrapping and time.monotonic() >= deadline:
                    logger.warning(
                        "live quote stream: no validated frame within %.0fs, falling back to polling",
                        self._bootstrap_timeout,
                    )
                    self._give_up("no validated frame within the bootstrap window")
                    return
                try:
                    message = connection.recv(timeout=self._frame_timeout)
                except TimeoutError:
                    continue
                except Exception as exc:
                    logger.warning(
                        "live quote stream: recv failed, falling back to polling: %s", exc
                    )
                    self._give_up(f"recv failed: {exc}")
                    return
                self._handle_message(message)

    def _handle_message(self, message: str) -> None:
        raw = _extract_frame_bytes(message)
        if raw is None:
            return
        decoded = decode_pricing_frame(raw)
        if decoded is None:
            return

        symbol = str(decoded["symbol"]).upper()
        with self._lock:
            watched = symbol in self._watched
            already_validated = symbol in self._validated
        if not watched:
            return

        if not already_validated:
            registry = self._get_registry()
            if registry is None or not self._validate(symbol, decoded["price"], registry):
                return
            with self._lock:
                self._validated.add(symbol)
                self._mode = "stream"

        quote = Quote(
            symbol=symbol,
            price=float(decoded["price"]),
            ts=_now(),
            change_pct=decoded.get("change_pct"),
            volume=decoded.get("day_volume"),
            # Presumed, not observed: Yahoo only pushes ticks for a symbol while it is actively
            # trading, so "REGULAR" is the most likely true state for anything arriving on this
            # socket at all -- but this is an assumption, not a field the stream actually carries
            # (see the module docstring's verification note), unlike the REST `Quote.market_state`
            # this same class name shadows for polled quotes.
            market_state="REGULAR",
            source=BarSource.YAHOO,
        )
        with self._lock:
            self._quotes[symbol] = quote

    def _validate(self, symbol: str, stream_price: float, registry: ProviderRegistry) -> bool:
        try:
            rest_quote = registry.get_quote(symbol)
        except Exception as exc:
            logger.info("live quote stream: could not validate %s against REST: %s", symbol, exc)
            return False
        if rest_quote.price <= 0:
            return False
        diff = abs(stream_price - rest_quote.price) / rest_quote.price
        if diff > self._validation_tolerance:
            logger.warning(
                "live quote stream: %s decoded price %.4f disagrees with REST %.4f by %.1f%% -- "
                "treating the decoder as unverified and not trusting the stream",
                symbol,
                stream_price,
                rest_quote.price,
                diff * 100,
            )
            return False
        return True

    def _give_up(self, reason: str) -> None:
        with self._lock:
            self._mode = "fallback"
            self._fallback_reason = reason


# ---------------------------------------------------------------------------
# Composition root
# ---------------------------------------------------------------------------


def build_source(settings: Settings | None = None) -> LiveQuoteSource:
    """The source `app.api.paperlive` actually uses, chosen by `Settings.paperlive_transport`."""
    cfg = settings or get_settings()
    polling = PollingQuoteSource(
        fast_interval=cfg.paperlive_poll_seconds,
        idle_interval=cfg.paperlive_idle_poll_seconds,
    )
    if cfg.paperlive_transport == "stream":
        return YahooStreamQuoteSource(fallback=polling)
    return polling

"""On-disk HTTP response cache for market-data providers.

This is a courtesy to the upstream and to the development loop -- repeated runs of the test suite
or a chart being re-opened five times in a session should not re-hit Yahoo five times. **It is not
a source of truth.** The Parquet store (:mod:`app.market.store`) is the durable layer with its own
retention and merge semantics; this cache has a TTL measured in minutes and can be deleted at any
time with no data loss. Anyone tempted to read historical bars back out of the cache instead of the
store has reached for the wrong module.

The seam is an :class:`httpx.BaseTransport`, not a wrapper around the provider classes. That keeps
providers entirely cache-ignorant -- they build a request and hand it to whatever transport their
client was constructed with -- and it means a test can swap in ``httpx.MockTransport`` with no cache
in the loop at all, rather than needing to know how to disable one.

Two failure modes shaped the caching rules:

* **Only ``GET`` / status ``200`` is cached.** A cached ``500`` is a poison pill: it would make an
  outage outlive the outage, silently reproducing the failure on every subsequent call long after
  the upstream recovered.
* **Expired entries are ignored on read, not deleted.** Deleting on read would race a concurrent
  writer for no benefit -- the entry is simply overwritten the next time it is fetched -- and it
  turns a cheap TTL check into an unnecessary filesystem mutation on the hot read path.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

import httpx

from app.db.duck import Interval

__all__ = ["CachingTransport", "cache_ttl"]

#: How long a cached response stays fresh, per bar interval. Matches how often the underlying data
#: can plausibly change: a 5-minute bar is stale almost immediately, a completed daily session is
#: not going to change within the hour. Not the same thing as the store's staleness thresholds in
#: :mod:`app.market.store` -- those decide when to *sync*; this decides when to trust the *cache*
#: instead of making an HTTP call at all, and syncing always goes through this cache regardless.
_TTL_BY_INTERVAL: Final[dict[Interval, float]] = {
    Interval.FIVE_MIN: 300.0,
    Interval.FIFTEEN_MIN: 900.0,
    Interval.THIRTY_MIN: 1800.0,
    Interval.HOUR: 1800.0,
    Interval.FOUR_HOUR: 3600.0,
    Interval.DAY: 3600.0,
    Interval.WEEK: 3600.0,
}


def cache_ttl(interval: Interval) -> float:
    """Seconds a cached response for this interval stays fresh."""
    return _TTL_BY_INTERVAL[interval]


#: TTL for Yahoo's meta-only chart lookups (quote, profile) -- a live snapshot, not a bar. These hit
#: the same `/v8/finance/chart/{symbol}` endpoint as a bar fetch and, per `_interval_from_request`
#: below, carry an `interval` query parameter too: `YahooProvider._meta` sets `interval=1d` purely
#: to keep the response payload small (see its docstring), not because the caller wants a daily bar.
#: Left undetected, that parameter would route a live quote through `_TTL_BY_INTERVAL[Interval.DAY]`
#: and serve it from up to an hour ago -- the tier meant for a session that has already closed and
#: will not move again, not a price that is moving right now. Seconds-scale so a burst of requests
#: for the same symbol (a chart and its header both asking for the last price) shares one round trip
#: without a quote going stale enough to mislead anyone watching the screen.
_META_LOOKUP_TTL: Final[float] = 30.0


def _is_meta_lookup(request: httpx.Request) -> bool:
    """True for Yahoo's meta-only chart requests (quote, profile); false for a genuine bar fetch.

    Both call shapes hit the same chart endpoint, so `interval` alone cannot tell them apart -- see
    `_META_LOOKUP_TTL` above. What actually distinguishes them is the *window* parameter:
    `YahooProvider.fetch_bars` always pins an explicit `period1`/`period2` range, while
    `YahooProvider._meta` always asks for a relative `range` instead and never sends `period1` or
    `period2`. A request with neither pair is treated as a meta lookup rather than falling through to
    the interval table, since only these two call shapes exist for this endpoint today.
    """
    params = request.url.params
    return "period1" not in params and "period2" not in params


def _cache_key(request: httpx.Request) -> str:
    """SHA-256 of method + URL, query parameters sorted so key order cannot desync the cache."""
    sorted_params = sorted(request.url.params.multi_items())
    canonical_url = request.url.copy_with(params=sorted_params)
    return hashlib.sha256(f"{request.method}:{canonical_url}".encode()).hexdigest()


def _interval_from_request(request: httpx.Request) -> Interval | None:
    """Best-effort interval detection from the request's own query string.

    Providers are cache-ignorant by design (see module docstring), so this is the only place left
    to learn which interval a bar request is for. Yahoo's chart endpoint already spells its
    ``interval`` query parameter with the same tokens as :class:`Interval` (``5m``, ``1h``, ``1d``,
    ``1w``), so this is a lookup rather than a translation. Requests that carry no such parameter --
    fundamentals lookups, or a provider with a different query convention -- fall back to the
    transport's default TTL instead of raising. Yahoo's meta lookups (quote, profile) *do* carry this
    parameter -- see :func:`_is_meta_lookup` -- so callers of this function must not treat its
    presence alone as proof of a genuine bar request.
    """
    raw = request.url.params.get("interval")
    if raw is None:
        return None
    try:
        return Interval(raw)
    except ValueError:
        return None


class CachingTransport(httpx.BaseTransport):
    """Wraps another transport with a Parquet-adjacent, deliberately disposable HTTP cache.

    ``root`` is fanned out one level by the first two hex characters of the cache key so a single
    directory never has to hold tens of thousands of entries -- ``Path.iterdir`` and friends on
    Windows degrade noticeably once a directory gets that large, and the fan-out costs nothing on
    the read path since the key is already computed.
    """

    def __init__(self, inner: httpx.BaseTransport, root: Path, *, ttl: float = 900.0) -> None:
        self._inner = inner
        self._root = root
        self._default_ttl = ttl

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            return self._inner.handle_request(request)

        key = _cache_key(request)
        path = self._entry_path(key)
        ttl = self._resolve_ttl(request)

        cached = self._read(path, ttl=ttl)
        if cached is not None:
            status, headers, body = cached
            return httpx.Response(status, headers=headers, content=body, request=request)

        response = self._inner.handle_request(request)
        response.read()  # materialise the body now so it can be cached and still be readable later
        if response.status_code == 200:
            self._write(path, response)
        return response

    def close(self) -> None:
        self._inner.close()

    def _resolve_ttl(self, request: httpx.Request) -> float:
        """The TTL to apply on this request's read/write, cheapest check first.

        A meta lookup is checked before trusting the interval table, not after, precisely because it
        would otherwise pass the interval check -- see :func:`_is_meta_lookup`.
        """
        interval = _interval_from_request(request)
        if interval is None:
            return self._default_ttl
        if _is_meta_lookup(request):
            return _META_LOOKUP_TTL
        return cache_ttl(interval)

    def _entry_path(self, key: str) -> Path:
        return self._root / key[:2] / f"{key}.json"

    def _read(self, path: Path, *, ttl: float) -> tuple[int, dict[str, str], bytes] | None:
        if not path.exists():
            return None
        try:
            payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None  # a corrupt entry is treated as a miss, not a crash
        # `>=`, not `>`. With a strict comparison, `ttl=0.0` -- which means "never serve from cache"
        # -- served a cached entry whenever both requests landed inside one clock tick, because the
        # age was exactly 0.0 and 0.0 is not greater than 0.0. That made `test_expired_entry_is_
        # refetched` intermittently fail on a fast machine (and reliably on Windows, whose
        # `time.time()` resolution is coarse enough that two adjacent calls routinely read the same
        # value). No production TTL is 0, so nothing served to a user was affected -- but the code
        # did not mean what the test said it meant, and an entry that has reached exactly its TTL is
        # expired by the ordinary reading of the word either way.
        if time.time() - payload["cached_at"] >= ttl:
            return None
        body = bytes.fromhex(payload["body_hex"])
        return payload["status"], payload["headers"], body

    #: Headers that describe the *transfer* of the original body rather than the body being stored.
    #:
    #: ``response.content`` is httpx's already-decoded body: a gzipped response has been inflated by
    #: the time it is read. Replaying that plain body while still advertising ``Content-Encoding:
    #: gzip`` makes the client try to inflate it a second time and fail with a zlib header error --
    #: and only on a cache *hit*, so the first request of any run succeeds and the second one dies.
    #: SEC EDGAR serves gzip, which is why fetching one ticker's fundamentals worked and the next
    #: ticker's crashed. ``Content-Length`` goes for the same reason: it describes the compressed
    #: bytes, not these.
    _TRANSFER_HEADERS = frozenset({"content-encoding", "content-length", "transfer-encoding"})

    def _write(self, path: Path, response: httpx.Response) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": response.status_code,
            "headers": {
                k: v
                for k, v in response.headers.items()
                if k.lower() not in self._TRANSFER_HEADERS
            },
            "body_hex": response.content.hex(),
            "cached_at": time.time(),
        }
        # Write to a sibling temp file and rename, so a process killed mid-write cannot leave a
        # truncated JSON entry behind that the next read then fails to parse (handled above, but
        # avoiding it is cheaper than recovering from it).
        #
        # The name carries a uuid because the cache key is *shared by construction*: identical
        # requests produce identical paths, and identical requests in flight together are exactly
        # what a cache exists for. Two threads staging through one fixed filename raced on Windows
        # ("the process cannot access the file because it is being used by another process") the
        # first time the four-timeframe view mounted and fired four syncs at once.
        #
        # No lock is needed here, unlike the bar store: the racing writers are caching the same
        # response, so last-writer-wins is not a lost update. The bar store merges, so there it is.
        staging = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        try:
            staging.write_text(json.dumps(payload), encoding="utf-8")
            staging.replace(path)
        except OSError:
            # A failed cache write is not a failed request. Windows refuses to replace a destination
            # another writer is replacing at the same instant, and the unique staging name does not
            # help because the *target* is the contended path. Since every racing writer is storing
            # the same response, losing this one costs a cache entry and nothing else -- so it is
            # swallowed rather than allowed to turn a successful fetch into a 500.
            pass
        finally:
            staging.unlink(missing_ok=True)

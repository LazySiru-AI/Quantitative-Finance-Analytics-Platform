"""Per-source data freshness for the Data page's "how old is what I am looking at?" table.

**Why this is a separate module from `app.market.refresh`.** That module answers "what did the last
sweep do", which is a statement about one process's most recent *action*. This one answers "how old
is each source right now", which is a statement about what is on disk -- and the two diverge the
moment the server restarts: a sweep that ran an hour ago in a process that has since exited leaves
`refresh.status()` back at all-zeros while the bars it wrote are still perfectly current. The Data
page needs both, so the report below carries `refresh.status()` verbatim alongside its own per-source
rows rather than trying to derive one from the other.

**This function must never make a network request.** It is a read on a page a person opens to find
out whether their data is stale; if opening that page itself fetched data, the answer would always
be "fresh" and the question would be unanswerable. Every measurement below is a local file read (a
Parquet partition, a sidecar, an sqlite file's mtime, a cache directory's mtime) or a read of an
in-process status record. `tests/test_data_freshness.py` proves this by blocking `socket.socket.connect`
and calling :func:`report` anyway.

**Fail-soft, per source.** A source whose measurement raises becomes one row with
``status: "unknown"`` and a ``detail`` naming the error. It never becomes a 500, because a broken
EDGAR cache directory must not take away the reader's ability to see that their *bars* are current --
that is the whole reason they opened the page.

**"unknown" is a real answer here, not a shrug.** Four of the eleven sources below genuinely cannot
have their age read from disk, and the reason is structural rather than an omission:
:class:`app.market.cache.CachingTransport` stores each response under the SHA-256 of its URL and
writes **no URL into the entry**, and macro (FRED/CNN), the event calendar (FOMC/Nasdaq/FRED),
SEC-EDGAR fundamentals and news all share one root (``settings.cache_dir / "http"``) with the Yahoo
bar fetches. So the newest mtime in that tree says "some HTTP call happened recently" and nothing at
all about *which* source it was. Reporting that number under four different keys would be four
guesses wearing a timestamp; `unknown` with a `detail` explaining why is the honest row. The two
EDGAR-backed institution caches do have roots of their own
(``cache_dir / "edgar"``, ``cache_dir / "institutions_consensus"``) and so can be measured.

**The key set is a closed enumeration and is load-bearing.** The frontend maps each `key` to its own
translated label, so adding, renaming or reordering one of the eleven keys below is a wire-contract
change, not an implementation detail.
"""

from __future__ import annotations

import datetime as dt
import importlib
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from app.config import Settings, get_settings
from app.datasource import DataServiceError, ledger_db_path
from app.db.duck import Interval, stored_symbols
from app.market import macro, refresh, store

__all__ = ["SourceFreshness", "report"]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tuning constants -- every one of these exists to bound the work a page load pays
# ---------------------------------------------------------------------------

#: How many of the sweep's tracked symbols `bars_daily` actually reads coverage for. Each read opens
#: and scans one Parquet partition, so this is the difference between a page load costing a dozen
#: small file reads and costing six hundred: `app.db.duck.stored_symbols` routinely lists 600+ daily
#: symbols, and the question this row answers ("are the things I actually watch current?") is already
#: answered by the priority-1/2 head of the sweep's own worklist -- the macro proxies and the
#: instruments the ledger says are held. The `detail` string always names the denominator it used, so
#: a truncated sample is visible rather than presented as a full count.
_MAX_TRACKED_SYMBOLS: Final[int] = 40

#: The same bound for the intraday row, applied per interval -- but far tighter, because an intraday
#: partition is the expensive one to read: a 5m symbol holds ~4,700 rows for the provider's 60-day
#: retention window against a daily symbol's few hundred. Measured against the real store, twenty
#: symbols per interval cost ~1.1s of a page load on their own, versus ~0.45s for eight, and the row
#: only ever reports one aggregate ("the newest intraday bar anywhere"), which eight samples answer
#: as well as twenty. The `detail` names the count it actually looked at.
_MAX_INTRADAY_SYMBOLS: Final[int] = 8

#: Ceiling on how many files a cache-directory or vault mtime scan will stat before it stops and
#: reports what it found so far. A cache root can hold tens of thousands of entries; walking all of
#: them to learn one maximum would make this endpoint slower than the fetch it describes.
_MAX_SCANNED_FILES: Final[int] = 4000

#: Age at which a cache-backed source stops counting as fresh. Matched to the longest TTL any source
#: below actually uses (`macro._MACRO_CACHE_TTL` is 24h), so a source inside its own TTL is never
#: reported stale.
_CACHE_FRESH_SECONDS: Final[float] = 24 * 3600.0

#: Closed value sets, asserted by the tests. Declared here rather than left implicit in the catalog
#: so a new row cannot quietly introduce a twelfth `status` the frontend has no branch for.
FRESHNESS_CLASSES: Final[frozenset[str]] = frozenset({"day_frame", "intraday", "local"})
POLICIES: Final[frozenset[str]] = frozenset(
    {"on_demand", "startup_sweep", "scheduled", "streaming", "computed", "manual"}
)
STATUSES: Final[frozenset[str]] = frozenset({"fresh", "stale", "unknown", "disabled", "live"})


# ---------------------------------------------------------------------------
# The row
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceFreshness:
    """One row of the freshness table.

    `age_seconds` is stored rather than derived in :meth:`to_dict` so every row in one report is aged
    against the same `as_of` instant -- a report whose rows were each aged against their own
    `now()` would show a source measured last as marginally older than one measured first, for no
    reason a reader could ever account for.
    """

    key: str
    freshness_class: str
    policy: str
    provider: str
    last_updated: dt.datetime | None
    age_seconds: int | None
    status: str
    detail: str
    refreshable: bool
    enabled: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "freshness_class": self.freshness_class,
            "policy": self.policy,
            "provider": self.provider,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "age_seconds": self.age_seconds,
            "status": self.status,
            "detail": self.detail,
            "refreshable": self.refreshable,
            "enabled": self.enabled,
        }


@dataclass(frozen=True)
class _Context:
    """Everything a measurement may read, resolved once per report.

    `live` is in here rather than being fetched by the `live_quotes` measurement itself because the
    same dict is also returned at the top level of the report: fetching it twice could show the row
    and the block disagreeing about whether the feed is running.
    """

    settings: Settings
    now: dt.datetime
    live: dict[str, Any]


#: A measurement returns `(last_updated, status, detail)` and nothing else -- the static metadata
#: (key, class, provider, refreshable) lives on the spec, so a measurement that raises can still be
#: rendered as a complete, correctly-labelled row with `status: "unknown"`.
_Measure = Callable[["_Context"], tuple[dt.datetime | None, str, str]]


#: `policy` and `enabled` take the whole context rather than just `Settings` for one reason:
#: `live_quotes` cannot answer either from settings alone. The live feed reports its own `enabled`
#: (see `app.market.livefeed.status`), which is the authoritative answer whenever that module is
#: present, and a row saying "enabled" beside a `live` block saying otherwise would be the page
#: contradicting itself. Every other spec ignores everything but `ctx.settings`.
_Policy = Callable[["_Context"], str]
_Enabled = Callable[["_Context"], bool]


@dataclass(frozen=True)
class _SourceSpec:
    key: str
    freshness_class: str
    provider: str
    refreshable: bool
    policy: _Policy
    enabled: _Enabled
    measure: _Measure


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _age(now: dt.datetime, last_updated: dt.datetime | None) -> int | None:
    if last_updated is None:
        return None
    if last_updated.tzinfo is None:
        last_updated = last_updated.replace(tzinfo=dt.UTC)
    return int((now - last_updated).total_seconds())


def _age_status(age_seconds: int | None, *, max_age: float = _CACHE_FRESH_SECONDS) -> str:
    """`fresh`/`stale` from an age, `unknown` from no age at all. A *negative* age -- a file stamped
    in the future by a clock skew or an unpacked archive -- counts as fresh: it is certainly not
    evidence of staleness, and reporting "stale" for it would be the wrong direction of wrong."""
    if age_seconds is None:
        return "unknown"
    return "fresh" if age_seconds < max_age else "stale"


def _mtime(path: Path) -> dt.datetime | None:
    try:
        return dt.datetime.fromtimestamp(path.stat().st_mtime, dt.UTC)
    except OSError:
        return None


def _newest_file_mtime(root: Path, *, cap: int = _MAX_SCANNED_FILES) -> tuple[dt.datetime | None, int]:
    """Newest mtime anywhere under `root`, and how many files were stat'd getting there.

    Bounded by `cap` (see `_MAX_SCANNED_FILES`): this walks a cache tree that can hold tens of
    thousands of entries, and the caller only ever needs an approximate "when was this last written".
    A tree that hits the cap yields the newest of the files actually seen, which can only ever be an
    *under*-estimate of freshness -- the safe direction for a staleness report.
    """
    if not root.is_dir():
        return None, 0
    newest: dt.datetime | None = None
    count = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            count += 1
            try:
                stamp = os.stat(os.path.join(dirpath, name)).st_mtime
            except OSError:
                continue
            seen = dt.datetime.fromtimestamp(stamp, dt.UTC)
            if newest is None or seen > newest:
                newest = seen
            if count >= cap:
                return newest, count
    return newest, count


def _shared_http_cache_note(cfg: Settings) -> str:
    """The one sentence four rows share, kept in one place so they cannot drift apart."""
    return (
        f"age cannot be attributed: responses share the URL-less on-disk HTTP cache at "
        f"{cfg.cache_dir / 'http'} with every other HTTP source (see app.market.cache), so the "
        f"newest entry there names no source"
    )


# ---------------------------------------------------------------------------
# The live block
# ---------------------------------------------------------------------------


def _live_fallback(cfg: Settings) -> dict[str, Any]:
    return {
        "enabled": cfg.paperlive_enabled,
        "transport": cfg.paperlive_transport,
        "running": False,
        "healthy": None,
        "watched": 0,
        "symbols": [],
        "market_state": None,
        "last_snapshot_at": None,
        "started_at": None,
    }


def _live_status(cfg: Settings) -> dict[str, Any]:
    """`app.market.livefeed.status()`, or a fully-populated stand-in when that module is absent.

    Resolved through :func:`importlib.import_module` rather than a `from app.market import livefeed`
    inside the `try` on purpose. `livefeed` is a sibling module this one must tolerate the absence of
    (it is owned by a different change, and this endpoint has to keep answering either way), and a
    static import statement is exactly what a type checker resolves eagerly -- it would report the
    module as missing today and then report the suppression as unused the day it lands. The dynamic
    call has the same runtime semantics, including raising `ImportError`, with no such whiplash.

    Every key of the fallback is guaranteed present in the result even when `livefeed.status()`
    returns a partial dict, so the wire contract cannot be broken by a change on the other side of
    this seam; extra keys it adds are passed through untouched.
    """
    fallback = _live_fallback(cfg)
    try:
        module = importlib.import_module("app.market.livefeed")
        raw = module.status()
    except ImportError:
        # The expected, non-exceptional case while the live feed is not part of this deployment.
        return fallback
    except Exception as exc:  # a live feed that cannot describe itself must not blank the page
        logger.warning("freshness: livefeed.status() failed: %s", exc)
        return fallback
    if not isinstance(raw, dict):
        logger.warning("freshness: livefeed.status() returned %r, not a dict", type(raw).__name__)
        return fallback
    merged: dict[str, Any] = {**fallback, **raw}
    return merged


# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------


def _tracked_symbols(cfg: Settings) -> list[str]:
    """The head of `app.market.refresh._build_worklist`: the macro movers and rate/oil proxies, then
    the ledger's priceable instruments -- read from `macro`'s and `refresh`'s own definitions rather
    than re-listed here, so this row can never describe a different set of symbols than the button
    next to it refreshes. Truncated to `_MAX_TRACKED_SYMBOLS`; see that constant.
    """
    seen: set[str] = set()
    symbols: list[str] = []

    def _add(symbol: str) -> None:
        if symbol and symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)

    for symbol, _label, _unit in macro._MOVERS:
        _add(symbol)
    for spec in (*macro._RATE_TILES, *macro._OIL_TILES):
        if spec.yahoo_symbol is not None:
            _add(spec.yahoo_symbol)
    for symbol in refresh._held_symbols(cfg):
        _add(symbol)

    return symbols[:_MAX_TRACKED_SYMBOLS]


def _measure_bars_daily(ctx: _Context) -> tuple[dt.datetime | None, str, str]:
    cfg = ctx.settings
    tracked = _tracked_symbols(cfg)
    if not tracked:
        return (
            None,
            "unknown",
            "nothing tracked yet: the ledger holds no priceable instruments and no macro proxies "
            "are configured",
        )

    # The sweep's own bar, reused rather than re-derived -- see `refresh._latest_settled_session`
    # for why "today" is the wrong threshold before the close.
    threshold = refresh._latest_settled_session(ctx.now)
    newest: dt.datetime | None = None
    measured = 0
    current = 0
    for symbol in tracked:
        try:
            last_ts = store.coverage(symbol, Interval.DAY, settings=cfg).last_ts
        except Exception as exc:  # one unreadable partition must not blank the row
            logger.info("freshness: coverage read failed for %s: %s", symbol, exc)
            continue
        measured += 1
        if last_ts is None:
            continue
        if newest is None or last_ts > newest:
            newest = last_ts
        if last_ts.date() >= threshold:
            current += 1

    if measured == 0:
        return None, "unknown", f"no readable daily partition for any of {len(tracked)} tracked symbols"

    through = (newest.date() if newest else threshold).isoformat()
    detail = f"{current} of {measured} tracked symbols current through {through}"
    status = "fresh" if current == measured else "stale"
    return newest, status, detail


def _measure_bars_intraday(ctx: _Context) -> tuple[dt.datetime | None, str, str]:
    cfg = ctx.settings
    newest: dt.datetime | None = None
    counted = 0
    for interval in (Interval.FIVE_MIN, Interval.HOUR):
        for symbol in stored_symbols(cfg.bars_dir, interval)[:_MAX_INTRADAY_SYMBOLS]:
            try:
                last_ts = store.coverage(symbol, interval, settings=cfg).last_ts
            except Exception as exc:
                logger.info("freshness: intraday coverage read failed for %s: %s", symbol, exc)
                continue
            counted += 1
            if last_ts is not None and (newest is None or last_ts > newest):
                newest = last_ts

    if counted == 0:
        return None, "unknown", "no 5m or 1h bars are stored yet"
    if newest is None:
        return None, "unknown", f"{counted} intraday partitions exist but hold no bars"

    threshold = refresh._latest_settled_session(ctx.now)
    status = "fresh" if newest.date() >= threshold else "stale"
    return (
        newest,
        status,
        f"newest bar {newest.isoformat()}, sampled from {counted} of the stored 5m/1h symbols",
    )


def _measure_macro(ctx: _Context) -> tuple[dt.datetime | None, str, str]:
    """The macro snapshot's own FRED/CNN cache has no readable age (see the module docstring), so the
    only honest timestamp available is the one this process wrote itself: the sweep records whether
    its `_warm_macro_snapshot` call succeeded and when the sweep finished. That is a real fact about
    a real warm when it exists, and no fact at all after a restart -- which is exactly what it is
    reported as.
    """
    progress = refresh.status()
    warm = progress.get("macro_snapshot")
    finished_raw = progress.get("finished_at")
    if warm == "ok" and isinstance(finished_raw, str):
        finished = _parse_iso(finished_raw)
        if finished is not None:
            age = _age(ctx.now, finished)
            return finished, _age_status(age), "warmed by this process's most recent sweep"
    if warm == "failed":
        return None, "unknown", "the last sweep in this process could not warm the macro snapshot"
    return None, "unknown", _shared_http_cache_note(ctx.settings)


def _measure_calendar(ctx: _Context) -> tuple[dt.datetime | None, str, str]:
    """The age is unreadable for the same shared-cache reason macro's is, so the row is `unknown`.

    It *is* covered by the Fetch button, but not by the sweep: `app.market.refresh._sweep` never
    calls `app.market.calendar.warm`, so `POST /api/market/refresh` (`app.api.data_admin`) calls
    `warm` itself right after starting the sweep, mirroring the pairing `app.main.lifespan` makes at
    startup. The warm honours the calendar's one-hour `CachingTransport` TTL, which is why the
    `detail` says the cache is re-warmed rather than promising a fresh FOMC/Nasdaq round trip per
    press.
    """
    return (
        None,
        "unknown",
        f"{_shared_http_cache_note(ctx.settings)}; the Fetch button re-warms the calendar cache "
        f"(app.market.calendar.warm, one-hour TTL) alongside the sweep",
    )


def _measure_fundamentals(ctx: _Context) -> tuple[dt.datetime | None, str, str]:
    return None, "unknown", _shared_http_cache_note(ctx.settings)


def _measure_institutions(ctx: _Context) -> tuple[dt.datetime | None, str, str]:
    """Measurable, unlike the other EDGAR-derived row: `app.institutions.service.build_client` gives
    the 13F fetches a cache root of their own (``cache_dir / "edgar"``, six-hour TTL), and
    `app.institutions.consensus` writes its derived responses to another
    (``cache_dir / "institutions_consensus"``). Neither is shared with any other source, so the
    newest file in them is genuinely this source's own last write.
    """
    cfg = ctx.settings
    roots = (cfg.cache_dir / "edgar", cfg.cache_dir / "institutions_consensus")
    newest: dt.datetime | None = None
    total = 0
    for root in roots:
        stamp, count = _newest_file_mtime(root)
        total += count
        if stamp is not None and (newest is None or stamp > newest):
            newest = stamp
    if newest is None:
        return None, "unknown", "nothing fetched yet: no EDGAR cache on disk"
    age = _age(ctx.now, newest)
    return newest, _age_status(age), f"{total} cached EDGAR responses; newest written {newest.isoformat()}"


def _measure_news(ctx: _Context) -> tuple[dt.datetime | None, str, str]:
    return None, "unknown", _shared_http_cache_note(ctx.settings)


def _measure_social(ctx: _Context) -> tuple[dt.datetime | None, str, str]:
    """The sqlite file's mtime first, the in-process scheduler record second.

    The file survives a restart and the record does not, so the file is the better answer whenever it
    exists -- and it also captures the snapshots the *sweep* writes, which the scheduler's own tick
    counter never sees.
    """
    from app.market import social_history

    cfg = ctx.settings
    db_path = social_history.default_db_path(cfg)
    last_updated = _mtime(db_path)
    scheduler = social_history.status()
    if last_updated is None:
        tick_raw = scheduler.get("last_tick_at")
        if isinstance(tick_raw, str):
            last_updated = _parse_iso(tick_raw)

    ticks = scheduler.get("total_ticks", 0)
    healthy = scheduler.get("healthy")
    if not cfg.social_snapshot_scheduler_enabled:
        detail = (
            f"the snapshot scheduler is off; snapshots are only written by a manual refresh sweep "
            f"({ticks} scheduler ticks this process)"
        )
        return last_updated, "disabled", detail

    age = _age(ctx.now, last_updated)
    detail = (
        f"scheduler on at {cfg.social_snapshot_interval_hours}h intervals; "
        f"{ticks} ticks this process, healthy={healthy}"
    )
    if last_updated is None:
        return None, "unknown", f"{detail}; no snapshot store on disk yet"
    return last_updated, _age_status(age), detail


def _measure_live_quotes(ctx: _Context) -> tuple[dt.datetime | None, str, str]:
    live = ctx.live
    last_updated = None
    snapshot_raw = live.get("last_snapshot_at")
    if isinstance(snapshot_raw, str):
        last_updated = _parse_iso(snapshot_raw)

    if not _live_enabled(ctx):
        return last_updated, "disabled", "the live quote feed is switched off"
    if live.get("running") and live.get("healthy"):
        watched = live.get("watched", 0)
        state = live.get("market_state")
        return (
            last_updated,
            "live",
            f"{live.get('transport')} feed running, {watched} symbols watched, market_state={state}",
        )
    return (
        last_updated,
        "unknown",
        "the live feed is enabled but is not reporting itself as running and healthy",
    )


def _measure_ledger(ctx: _Context) -> tuple[dt.datetime | None, str, str]:
    """The one purely local source. Its "freshness" is not about an upstream at all -- the ledger is
    only ever written by an ingest the owner runs -- so the useful fact is simply when that last
    happened, and a ledger that exists is by definition current with itself.
    """
    try:
        path = ledger_db_path(ctx.settings)
    except DataServiceError as exc:
        return None, "unknown", f"data service unreachable: {exc}"
    last_updated = _mtime(path)
    if last_updated is None:
        return None, "unknown", f"no ledger database at {path}"
    return last_updated, "fresh", f"local ledger last written {last_updated.isoformat()}"


def _measure_persona_corpus(ctx: _Context) -> tuple[dt.datetime | None, str, str]:
    cfg = ctx.settings
    root = cfg.vault_dir / "influencers"
    if not root.is_dir():
        return None, "unknown", f"no persona vault at {root}"

    newest: dt.datetime | None = None
    personas = 0
    notes = 0
    scanned = 0
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        personas += 1
        stamp, count = _newest_file_mtime(entry / "notes", cap=_MAX_SCANNED_FILES - scanned)
        scanned += count
        notes += count
        if stamp is not None and (newest is None or stamp > newest):
            newest = stamp
        if scanned >= _MAX_SCANNED_FILES:
            break

    detail = f"{notes} notes across {personas} personas"
    if not cfg.persona_refresh_enabled:
        return newest, "disabled", f"{detail}; the daily top-up daemon is off (persona_refresh_enabled)"
    if newest is None:
        return None, "unknown", f"{detail}; nothing ingested yet"
    return newest, _age_status(_age(ctx.now, newest)), detail


def _parse_iso(raw: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.UTC)


# ---------------------------------------------------------------------------
# The catalog
# ---------------------------------------------------------------------------


def _sweep_policy(ctx: _Context) -> str:
    """`startup_sweep` for the three sources the server sweeps for itself on boot, `on_demand` for
    the same three when that is switched off and the only thing that refreshes them is the button."""
    return "startup_sweep" if ctx.settings.refresh_on_startup else "on_demand"


def _always(_ctx: _Context) -> bool:
    return True


def _live_enabled(ctx: _Context) -> bool:
    """The feed's own answer when it is there to give one, `Settings.paperlive_enabled` when it is
    not -- which is exactly what `_live_fallback` puts in the block, so the row and the block always
    agree."""
    value = ctx.live.get("enabled")
    return bool(value) if isinstance(value, bool) else ctx.settings.paperlive_enabled


#: Order is part of the wire contract -- the frontend renders the table in exactly this sequence.
_CATALOG: Final[tuple[_SourceSpec, ...]] = (
    _SourceSpec(
        key="bars_daily",
        freshness_class="day_frame",
        provider="Yahoo chart API",
        refreshable=True,
        policy=_sweep_policy,
        enabled=_always,
        measure=_measure_bars_daily,
    ),
    _SourceSpec(
        key="bars_intraday",
        freshness_class="intraday",
        provider="Yahoo chart API",
        refreshable=False,
        policy=lambda _ctx: "on_demand",
        enabled=_always,
        measure=_measure_bars_intraday,
    ),
    _SourceSpec(
        key="macro_snapshot",
        freshness_class="day_frame",
        provider="FRED series + CNN Fear & Greed",
        refreshable=True,
        policy=_sweep_policy,
        enabled=_always,
        measure=_measure_macro,
    ),
    _SourceSpec(
        key="calendar_events",
        freshness_class="day_frame",
        provider="Federal Reserve FOMC + Nasdaq earnings + FRED releases",
        refreshable=True,
        policy=_sweep_policy,
        enabled=_always,
        measure=_measure_calendar,
    ),
    _SourceSpec(
        key="fundamentals_edgar",
        freshness_class="day_frame",
        provider="SEC EDGAR company facts",
        refreshable=False,
        policy=lambda _ctx: "on_demand",
        enabled=_always,
        measure=_measure_fundamentals,
    ),
    _SourceSpec(
        key="institutions_filings",
        freshness_class="day_frame",
        provider="SEC EDGAR 13F filings",
        refreshable=False,
        policy=lambda _ctx: "on_demand",
        enabled=_always,
        measure=_measure_institutions,
    ),
    _SourceSpec(
        key="news",
        freshness_class="day_frame",
        provider="Yahoo Finance news + GDELT + Polymarket",
        refreshable=False,
        policy=lambda _ctx: "on_demand",
        enabled=_always,
        measure=_measure_news,
    ),
    _SourceSpec(
        key="social_snapshots",
        freshness_class="day_frame",
        provider="StockTwits + Reddit",
        refreshable=True,
        policy=lambda ctx: (
            "scheduled" if ctx.settings.social_snapshot_scheduler_enabled else "manual"
        ),
        enabled=lambda ctx: ctx.settings.social_snapshot_scheduler_enabled,
        measure=_measure_social,
    ),
    _SourceSpec(
        key="live_quotes",
        freshness_class="intraday",
        provider="Yahoo live quotes",
        refreshable=False,
        policy=lambda _ctx: "streaming",
        enabled=_live_enabled,
        measure=_measure_live_quotes,
    ),
    _SourceSpec(
        key="ledger",
        freshness_class="local",
        provider="local brokerage ingest",
        refreshable=False,
        policy=lambda _ctx: "computed",
        enabled=_always,
        measure=_measure_ledger,
    ),
    _SourceSpec(
        key="persona_corpus",
        freshness_class="day_frame",
        provider="YouTube transcripts (persona vault)",
        refreshable=False,
        policy=lambda ctx: "scheduled" if ctx.settings.persona_refresh_enabled else "manual",
        enabled=lambda ctx: ctx.settings.persona_refresh_enabled,
        measure=_measure_persona_corpus,
    ),
)

#: The eleven keys, in order. Exported for the frontend contract test and for documentation.
SOURCE_KEYS: Final[tuple[str, ...]] = tuple(spec.key for spec in _CATALOG)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _build_row(spec: _SourceSpec, ctx: _Context) -> SourceFreshness:
    """One row, with every failure mode collapsing to a complete `unknown` row rather than an error.

    The policy and enabled callables are inside the same `try` as the measurement on purpose: they
    read `Settings` attributes, and a settings object missing one of them is exactly the kind of
    integration slip that should show up as one degraded row naming the problem, not as a 500 that
    takes the other ten rows down with it.
    """
    try:
        policy = spec.policy(ctx)
        enabled = spec.enabled(ctx)
        last_updated, status, detail = spec.measure(ctx)
    except Exception as exc:
        logger.warning("freshness: source %s could not be measured: %s", spec.key, exc)
        return SourceFreshness(
            key=spec.key,
            freshness_class=spec.freshness_class,
            policy="on_demand",
            provider=spec.provider,
            last_updated=None,
            age_seconds=None,
            status="unknown",
            detail=f"could not be measured: {type(exc).__name__}: {exc}",
            refreshable=spec.refreshable,
            enabled=False,
        )
    return SourceFreshness(
        key=spec.key,
        freshness_class=spec.freshness_class,
        policy=policy,
        provider=spec.provider,
        last_updated=last_updated,
        age_seconds=_age(ctx.now, last_updated),
        status=status,
        detail=detail,
        refreshable=spec.refreshable,
        enabled=enabled,
    )


def report(settings: Settings | None = None) -> dict[str, Any]:
    """The whole freshness report: eleven source rows, the sweep's own progress record, and the live
    feed's status block.

    Purely local -- see the module docstring. Never raises for a broken source; see :func:`_build_row`.
    """
    cfg = settings or get_settings()
    now = _now()
    ctx = _Context(settings=cfg, now=now, live=_live_status(cfg))
    rows = [_build_row(spec, ctx) for spec in _CATALOG]
    _notify_flips(cfg, rows, as_of=now)
    return {
        "as_of": now.isoformat(),
        "sources": [row.to_dict() for row in rows],
        "refresh": refresh.status(),
        "live": ctx.live,
    }


#: Statuses that count as "this source was working". A flip *out* of either of these into `stale` is
#: what gets announced; `unknown` and `disabled` are excluded from both sides deliberately -- a source
#: that could not be measured, or that an operator turned off, has not gone stale, and treating either
#: as a prior good state would announce staleness the moment a measurement started working again.
_HEALTHY_STATUSES: Final = frozenset({"fresh", "live"})


def _last_status_path(settings: Settings) -> Path:
    """`data/notify/freshness_last.json` -- the previous report's status per source key.

    Under `data/notify/` rather than beside the market store because this file exists only to make
    the notification layer's edge-triggering possible; nothing in `app.market` reads it, and the whole
    freshness report is otherwise derived fresh from disk on every call.
    """
    path = settings.data_dir / "notify"
    path.mkdir(parents=True, exist_ok=True)
    return path / "freshness_last.json"


def _notify_flips(
    settings: Settings, rows: list[SourceFreshness], *, as_of: dt.datetime
) -> None:
    """Announce every source that has just gone `fresh`/`live` -> `stale`, then record this run.

    **Edge-triggered, on purpose.** `report()` is called on demand -- every load of Data > Health and
    every manager snapshot -- so a level-triggered check would announce the same stale source on every
    page view until somebody fixed it. Comparing against the previous run's statuses means the
    notification fires once, when the transition happens, and the `dedupe_id`'s UTC date bounds even
    that to once a day should the source flap fresh/stale/fresh across several refreshes.

    A key with no previous status is never announced: on the first ever report, everything already
    stale would otherwise be reported as if it had just broken. The last-status file is rewritten on
    every call, including this first one, so the *next* report differences normally.

    Wrapped whole, and the report's return value never depends on any of it -- the freshness table is
    the product here, and a notification is a side effect of computing it.
    """
    try:
        previous: dict[str, str] = {}
        path = _last_status_path(settings)
        if path.is_file():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                previous = {str(key): str(value) for key, value in loaded.items()}

        if previous:
            from app.notify import emit

            for row in rows:
                if row.status != "stale" or previous.get(row.key) not in _HEALTHY_STATUSES:
                    continue
                emit(
                    settings,
                    kind="data.stale",
                    severity="notable",
                    headline=f"Data stale: {row.key}",
                    detail=row.detail or f"policy: {row.policy}",
                    refs=(f"data:{row.key}",),
                    source="market.freshness",
                    dedupe_id=f"data.stale:{row.key}:{as_of.date().isoformat()}",
                )

        path.write_text(
            json.dumps({row.key: row.status for row in rows}, indent=2), encoding="utf-8"
        )
    except Exception:
        logger.exception("freshness: notify hook failed; the report itself is unaffected")

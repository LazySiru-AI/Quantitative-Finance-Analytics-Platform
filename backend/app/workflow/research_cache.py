"""The research-verdict cache: lets the necessity-gate chain (`app.workflow.pipeline`) answer "do we
already know the answer for this symbol" without spending on a fresh TradingAgents or Vibe child run.

**Why not `app.tradingagents.memory`.** That module is the desk's own outcome-*resolution* log --
built for the portfolio manager to read back its own past decisions, and its `resolve_pending` step
spends a real `reflector` model call the moment an entry ages past its own holding window. A
necessity-gate cache must be free to *check*, and needs a key (`symbol`, `agent_card_id`,
`child_kind`) and invalidation inputs (a regime label, an ATR reading, both frozen at cache time) that
`MemoryEntryModel` was never built to carry -- bolting them on would leak this feature's concerns into
a file every other TradingAgents caller also reads. See `docs/WORKFLOW-RESEARCH-SPEND-SPEC.md` §2 for
the full recon.

**Storage.** JSONL, append-only, one line per fresh verdict, resolved by atomic whole-file rewrite --
copying `app.workflow.candidates`/`app.tradingagents.memory`'s own convention exactly (a uuid-suffixed
staging file, then `os.replace`, which is atomic on Windows too). A `(symbol, agent_card_id,
child_kind)` key can have many historical rows; a reader always takes the most recent one for that key
as "the current cache entry" -- never mutated in place, which leaves a free audit trail of every
verdict this desk has ever cached.

**Two free invalidation triggers, checked at read time even inside the TTL window:**

* **Trigger A -- regime flip.** `ctx.regime.label != entry.regime_at_cache`.
* **Trigger B -- adverse ATR move.** The workflow only ever stages `buy` orders, so "thesis
  direction" is always long: invalidate when `entry.price_at_cache - current_close >
  2 * entry.atr14_at_cache` (strict `>`; a move of exactly `2x` stays cached).

A third, storage-free check -- "re-entry after an absence invalidates the cache" -- is derived
straight from `app.workflow.candidates`' own observation log rather than kept as separate state: if
this card ran a scan on some date between the cache entry and today and this symbol is missing from
that date's rows, the entry rule did not fire (or the symbol fell outside `max_research_symbols`) on
that day, which is a genuine absence from the shortlist and invalidates the cache regardless of TTL or
the other two triggers.

A Vibe cache entry carries one more field, `ta_rating_at_cache`, and one more check: `_followup_
question` embeds the TA rating into the literal text `_launch_vibe` sends, so a cached Vibe answer to
a question built around a *different* TA rating is not evidence for today's question, however fresh
the underlying evidence was when it was recorded. See `check_verdict_cache`'s `ta_rating_for_linked_
check` parameter.

**TTL.** `CACHE_TTL_DAYS` is imported from, and must equal, `app.workflow.candidates.HOLDING_DAYS`
(itself locked to `app.tradingagents.memory._HOLDING_DAYS` by that module's own test) -- restating the
number here would let a future edit drift the three apart silently; importing it makes drift
impossible. Calendar days, not trading sessions, matching both existing constants' own arithmetic. The
clock never resets on a hit: `decision_date` is fixed at the moment the *fresh* verdict was recorded,
so worst-case staleness is bounded at exactly `CACHE_TTL_DAYS` regardless of how many times an entry is
reused.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.agentdesk.models import agentdesk_dir
from app.config import Settings
from app.workflow.candidates import HOLDING_DAYS

__all__ = [
    "CACHE_TTL_DAYS",
    "CacheCheckResult",
    "ChildKind",
    "ResearchVerdictCacheEntry",
    "append_entry",
    "cache_path",
    "check_verdict_cache",
    "latest_entry",
    "read_entries",
    "write_entry",
]

logger = logging.getLogger(__name__)

#: Must equal `app.workflow.candidates.HOLDING_DAYS` (itself locked to
#: `app.tradingagents.memory._HOLDING_DAYS`) -- imported, not restated, so the three can never drift.
#: `tests/test_workflow_research_cache.py` asserts the three-way equality directly.
CACHE_TTL_DAYS: int = HOLDING_DAYS

ChildKind = Literal["tradingagents", "vibedesk"]
"""Which child desk a cache entry backs. Two independent stores living in one file, keyed apart by
this field -- see the module docstring's "why not memory.py" section and
`docs/WORKFLOW-RESEARCH-SPEND-SPEC.md` §2's recon note 5 on why the TA and Vibe caches must stay
independently checkable rather than one bundled verdict."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class ResearchVerdictCacheEntry(_Frozen):
    """One fresh research verdict, cached so a later cycle can reuse it instead of paying for a new
    child run. See the module docstring for the full schema rationale."""

    cache_id: str
    symbol: str
    agent_card_id: str
    child_kind: ChildKind

    decision_date: dt.date
    """The `trade_date` this verdict was produced on. TTL is anchored here and never slides forward on
    a cache hit -- see the module docstring's TTL section."""

    regime_at_cache: str
    """`RegimeLabel` active when this verdict was cached -- invalidation trigger A."""

    price_at_cache: Decimal
    """Symbol's close on `decision_date` -- the reference point for trigger B."""

    atr14_at_cache: Decimal
    """ATR(14) on `decision_date` (`app.indicators.volatility.atr`, the same free, deterministic
    reading `app.workflow.regime.classify` already uses internally) -- the volatility scale trigger B
    measures the adverse move against. Frozen at cache time, never recomputed on a later read, so the
    scale a verdict is judged against is the one that was actually in force when it was formed."""

    ta_rating: str = ""
    """`tradingagents` entries only."""
    ta_run_id: str = ""
    """`tradingagents` entries only -- the child run that produced this rating."""

    vibe_verdict: Literal["SUPPORT", "REFUTE", "INCONCLUSIVE"] | None = None
    """`vibedesk` entries only."""
    vibe_explicit: bool = True
    """`vibedesk` entries only -- `False` when the original run defaulted rather than ruled."""
    vibe_run_id: str = ""
    """`vibedesk` entries only -- the child run that produced this verdict."""
    ta_rating_at_cache: str = ""
    """`vibedesk` entries only -- the TA rating this Vibe verdict's follow-up question was actually
    built against. See the module docstring's linked-invalidation section."""

    research_cost_usd: Decimal = Decimal(0)
    """What the *original* fresh child run that produced this entry cost -- carried so a cache hit can
    report `avoided_cost_usd` (`app.workflow.candidates.CandidateObservation.avoided_cost_usd`)
    without a second lookup."""

    created_at: dt.datetime


def cache_path(settings: Settings) -> Path:
    """`data/agentdesk/workflow/research_cache.jsonl` -- nested under `agentdesk_dir` alongside
    `app.workflow.candidates.candidates_log_path` and `app.workflow.book.book_path`, matching this
    feature's established footprint."""
    return agentdesk_dir(settings) / "workflow" / "research_cache.jsonl"


def _read_all(path: Path) -> list[ResearchVerdictCacheEntry]:
    if not path.is_file():
        return []
    rows: list[ResearchVerdictCacheEntry] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            rows.append(ResearchVerdictCacheEntry.model_validate_json(line))
        except ValueError as exc:
            logger.warning(
                "research cache: skipping unreadable row at %s:%d: %s", path, line_no, exc
            )
    return rows


def append_entry(entry: ResearchVerdictCacheEntry, *, settings: Settings) -> None:
    """Append one fresh verdict. Never mutates a prior row -- see the module docstring."""
    path = cache_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(entry.model_dump_json() + "\n")


def read_entries(
    *,
    settings: Settings,
    symbol: str | None = None,
    agent_card_id: str | None = None,
    child_kind: ChildKind | None = None,
) -> tuple[ResearchVerdictCacheEntry, ...]:
    """Every logged entry, optionally filtered -- the full audit trail, oldest first."""
    rows = _read_all(cache_path(settings))
    if symbol is not None:
        upper = symbol.upper()
        rows = [row for row in rows if row.symbol == upper]
    if agent_card_id is not None:
        rows = [row for row in rows if row.agent_card_id == agent_card_id]
    if child_kind is not None:
        rows = [row for row in rows if row.child_kind == child_kind]
    return tuple(rows)


def latest_entry(
    symbol: str, agent_card_id: str, child_kind: ChildKind, *, settings: Settings
) -> ResearchVerdictCacheEntry | None:
    """The most recent cached verdict for this `(symbol, agent_card_id, child_kind)` key, or `None`
    if none was ever cached. "Most recent" is file order (this module only ever appends
    chronologically), matching `app.workflow.candidates`' own "always take the latest row" style."""
    rows = read_entries(settings=settings, symbol=symbol, agent_card_id=agent_card_id, child_kind=child_kind)
    return rows[-1] if rows else None


def write_entry(
    *,
    symbol: str,
    agent_card_id: str,
    child_kind: ChildKind,
    decision_date: dt.date,
    regime_label: str,
    price_at_cache: Decimal,
    atr14_at_cache: Decimal,
    ta_rating: str = "",
    ta_run_id: str = "",
    vibe_verdict: Literal["SUPPORT", "REFUTE", "INCONCLUSIVE"] | None = None,
    vibe_explicit: bool = True,
    vibe_run_id: str = "",
    ta_rating_at_cache: str = "",
    research_cost_usd: Decimal = Decimal(0),
    settings: Settings,
) -> ResearchVerdictCacheEntry:
    """Build and append one fresh cache entry. Called once, right after a fresh TA or Vibe child
    succeeds, from `app.workflow.pipeline`."""
    entry = ResearchVerdictCacheEntry(
        cache_id=uuid.uuid4().hex,
        symbol=symbol.upper(),
        agent_card_id=agent_card_id,
        child_kind=child_kind,
        decision_date=decision_date,
        regime_at_cache=regime_label,
        price_at_cache=price_at_cache,
        atr14_at_cache=atr14_at_cache,
        ta_rating=ta_rating,
        ta_run_id=ta_run_id,
        vibe_verdict=vibe_verdict,
        vibe_explicit=vibe_explicit,
        vibe_run_id=vibe_run_id,
        ta_rating_at_cache=ta_rating_at_cache,
        research_cost_usd=research_cost_usd,
        created_at=dt.datetime.now(dt.UTC),
    )
    append_entry(entry, settings=settings)
    return entry


# ---------------------------------------------------------------------------
# Gate 2: the cache check
# ---------------------------------------------------------------------------

#: Machine-parseable reasons `CacheCheckResult.reason` can carry when `valid=False`. Distinct from
#: `app.workflow.candidates.SKIP_REASONS` on purpose -- an invalid cache is never itself a skip (see
#: that constant's own docstring on why `"cache_hit"` is not a skip reason either); it just means
#: fresh research is needed, exactly like never having cached anything at all.
NO_ENTRY = "no_entry"
TTL_EXPIRED = "ttl_expired"
REGIME_FLIP = "regime_flip"
ADVERSE_ATR_MOVE = "adverse_atr_move"
REENTRY_AFTER_ABSENCE = "reentry_after_absence"
LINKED_TA_RATING_CHANGED = "linked_ta_rating_changed"
UNPRICEABLE = "unpriceable"
VALID = "valid"


@dataclass(frozen=True, slots=True)
class CacheCheckResult:
    """One gate-2 lookup's outcome. `entry` is the cache row consulted (`None` only for `NO_ENTRY`);
    `valid=True` means the caller may reuse it -- `verdict_source="cached"`, `$0` spend."""

    entry: ResearchVerdictCacheEntry | None
    valid: bool
    reason: str


def _ttl_expired(entry: ResearchVerdictCacheEntry, today: dt.date) -> bool:
    return today > entry.decision_date + dt.timedelta(days=CACHE_TTL_DAYS)


def _regime_flip_invalidated(entry: ResearchVerdictCacheEntry, regime_label: str) -> bool:
    return regime_label != entry.regime_at_cache


def _adverse_atr_invalidated(entry: ResearchVerdictCacheEntry, current_close: Decimal) -> bool:
    return (entry.price_at_cache - current_close) > (Decimal(2) * entry.atr14_at_cache)


def _reentry_after_absence_invalidated(
    entry: ResearchVerdictCacheEntry, *, settings: Settings, today: dt.date
) -> bool:
    """See the module docstring's third trigger. Reads `app.workflow.candidates`' own log rather than
    keeping separate state -- that log already records every scanned candidate, every run,
    unconditionally, which is exactly the continuity record this check needs."""
    from app.workflow import candidates as candidates_mod

    card_rows = candidates_mod.read_observations(settings=settings)
    same_card = [row for row in card_rows if row.agent_card_id == entry.agent_card_id]
    run_dates = sorted(
        {row.decision_date for row in same_card if entry.decision_date < row.decision_date < today}
    )
    if not run_dates:
        return False
    symbol_dates = {row.decision_date for row in same_card if row.symbol == entry.symbol.upper()}
    return any(d not in symbol_dates for d in run_dates)


def check_verdict_cache(
    symbol: str,
    agent_card_id: str,
    child_kind: ChildKind,
    *,
    settings: Settings,
    today: dt.date,
    regime_label: str,
    current_close: Decimal | None,
    ta_rating_for_linked_check: str | None = None,
) -> CacheCheckResult:
    """Gate 2: is there a still-valid cached verdict for `(symbol, agent_card_id, child_kind)`?

    Checked in this order -- absence, then TTL, then the two free invalidation triggers, then (Vibe
    only) the linked-rating check -- so the first thing that disqualifies an entry is the one
    `CacheCheckResult.reason` names. `current_close=None` (the symbol could not be priced as of
    `today`) is treated the same as any other invalidation: there is no way to evaluate trigger B, and
    the conservative direction is to fall back to fresh research rather than trust a verdict this
    check could not actually verify.

    `ta_rating_for_linked_check`, when given (Vibe lookups only), is this cycle's *effective* TA
    rating -- whichever it ends up being, fresh or itself cache-served. If it differs from the cached
    entry's own `ta_rating_at_cache`, the entry is invalidated regardless of every other check passing
    -- see the module docstring's linked-invalidation section for why a cached answer to a differently
    worded question is not evidence for today's.
    """
    entry = latest_entry(symbol, agent_card_id, child_kind, settings=settings)
    if entry is None:
        return CacheCheckResult(entry=None, valid=False, reason=NO_ENTRY)
    if _ttl_expired(entry, today):
        return CacheCheckResult(entry=entry, valid=False, reason=TTL_EXPIRED)
    if _regime_flip_invalidated(entry, regime_label):
        return CacheCheckResult(entry=entry, valid=False, reason=REGIME_FLIP)
    if current_close is None:
        return CacheCheckResult(entry=entry, valid=False, reason=UNPRICEABLE)
    if _adverse_atr_invalidated(entry, current_close):
        return CacheCheckResult(entry=entry, valid=False, reason=ADVERSE_ATR_MOVE)
    if _reentry_after_absence_invalidated(entry, settings=settings, today=today):
        return CacheCheckResult(entry=entry, valid=False, reason=REENTRY_AFTER_ABSENCE)
    if (
        child_kind == "vibedesk"
        and ta_rating_for_linked_check is not None
        and ta_rating_for_linked_check != entry.ta_rating_at_cache
    ):
        return CacheCheckResult(entry=entry, valid=False, reason=LINKED_TA_RATING_CHANGED)
    return CacheCheckResult(entry=entry, valid=True, reason=VALID)

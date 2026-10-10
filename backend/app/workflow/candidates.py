"""The candidate observation log: every entry signal the desk saw, and what each gate did with it.

**Why this exists separately from the book.** The four arms' books record orders, and an order only
exists for a candidate some gate *passed*. The refused ones leave no trace there -- and the refused
ones are half the evidence. A gate that declines candidates which then outperform is worse than no
gate at all, and a ledger of executed trades cannot say so, because the trades it would need to
compare against were never placed. So every candidate is written here the moment it is scanned,
before any gate has ruled, with each gate's decision attached.

**It is also the study's only well-powered instrument.** Comparing four equity curves over a few
months is a low-power design and `docs/WORKFLOW-STUDY-PLAN.md` §4 says so in advance. Asking instead
whether a gate's pass/fail predicts forward return moves the sample from *days* to *candidates*,
which is roughly an order of magnitude more observations for the same elapsed time. The equity curves
answer the owner's question in its own terms; this file is what can actually reach significance.

**Conventions inherited, not reinvented.** Returns are fractions of one (`0.0532` is +5.32%),
matching every other `_pct` field in this codebase and the `MemoryEntry` wire contract. Forward
return is priced exactly the way `app.tradingagents.memory._realized_return` prices it -- which in
turn mirrors `app.paperdesk.desk._buy_and_hold` -- off `app.market.store.read_frame`'s stored daily
history, raw `close` and never `adj_close`, `Decimal(str(...))` at the first and last row inside the
window, and `None` rather than a fabricated zero when the window holds fewer than two bars. The
horizon is `app.tradingagents.memory`'s own `_HOLDING_DAYS`, imported rather than restated, so these
observations stay commensurable with the decision log that desk already keeps.

JSONL, appended once per candidate and resolved by atomic whole-file rewrite, for the same reasons
`memory.py` gives: one JSON object per line resolves without needing a delimiter a model cannot
reliably emit, and `os.replace` is atomic on Windows too.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import uuid
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.agentdesk.models import agentdesk_dir
from app.config import Settings
from app.market import store as market_store
from app.market.models import Interval

__all__ = [
    "HOLDING_DAYS",
    "SKIP_REASONS",
    "CandidateObservation",
    "GateDecision",
    "UniverseSource",
    "append_observations",
    "candidates_log_path",
    "read_observations",
    "resolve_pending",
]

logger = logging.getLogger(__name__)

#: The benchmark every alpha figure here is measured against -- the same one
#: `app.tradingagents.memory` and `app.paperdesk.desk._buy_and_hold` use. Kept as a constant rather
#: than a parameter so no caller can quietly change the anchor mid-study; `SCOREBOARD.json` carries a
#: `benchmark_anchor` key precisely because mixing anchors has cost this programme a result before.
BENCHMARK_SYMBOL = "SPY"

#: Calendar days a candidate waits before its forward return is treated as realised.
#:
#: Must equal `app.tradingagents.memory._HOLDING_DAYS`, and `tests/test_workflow_candidates.py`
#: asserts that it does. Stated as its own constant rather than imported because that name is
#: private to its module -- but the two must not drift, because the whole reason for matching it is
#: that these observations and that desk's decision log then measure the same horizon and can be
#: pooled. A test is the right enforcement for a coupling that is real but not an import.
HOLDING_DAYS = 21

#: Fraction precision, matching `app.tradingagents.memory._FRACTION_QUANT` -- six places is finer
#: than a basis point, which is all daily closes can resolve to anyway.
_FRACTION_QUANT = Decimal("0.000001")

GateName = Literal["ta_gated", "vibe_gated", "full_workflow"]
"""The three gates that can refuse a candidate. `raw_signal` is not a gate -- it is the absence of
one, and it passes everything by definition, which is what makes it the study's null."""

UniverseSource = Literal["card", "screen"]
"""Which universe a candidate was scanned from -- `"card"` (a strategy card's own static `universe`,
today's only behaviour) or `"screen"` (a dynamic discovery-selector shortlist, see
`app.workflow.universe`). Restated as this module's own `Literal` rather than imported from
`app.workflow.book_models.BookState.universe_source` or `app.workflow.universe`, matching this
package's existing convention of each module owning its own two-valued `Literal` rather than reaching
across a boundary for one (see `book_models.PriceSource`'s own docstring for the same reasoning)."""

#: The `CandidateObservation.skip_reason` values the research-spend necessity-gate chain writes (see
#: `docs/WORKFLOW-RESEARCH-SPEND-SPEC.md` §1/§4). Not itself a `Literal` on the field -- `skip_reason`
#: stays `str | None` because the gate chain that populates it lives in `app.workflow.pipeline`, which
#: this module must not import (see this file's own module docstring on why the candidate log is kept
#: independent of the orchestrator). Stated here as a plain constant purely so both sides of that
#: boundary agree on the exact spelling without either importing the other.
#:
#: Deliberately excludes `"cache_hit"` -- a cache hit is carried by `GateDecision.verdict_source ==
#: "cached"`, not the skip taxonomy; a candidate whose verdict was served from cache was still
#: researched (from the cache), never skipped.
#:
#: `"over_cap"` is the one reason NOT written by the gate chain: it is assigned in
#: `app.workflow.pipeline._stage_candidate_scan`, before any gate runs, to a name that fired beyond
#: `max_research_symbols`. Such a name is logged as an observation (so the study's negative record is
#: complete) but is never gated or researched -- only the capped set is, the assumption
#: `app.workflow.power_analysis.estimate_candidate_arrival_rate` models. It lives in this taxonomy so
#: `skip_reason is None` stays the single "was actually researched" test everywhere downstream.
SKIP_REASONS: tuple[str, ...] = (
    "weekly_budget_exhausted",
    "no_book_capacity",
    "tax_wash_sale_blocked",
    "correlation_duplicate",
    "budget_exhausted",
    "over_cap",
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class GateDecision(_Frozen):
    """One gate's ruling on one candidate."""

    gate: GateName
    passed: bool

    detail: str = ""
    """The gate's own words for its ruling -- a Trading Agents rating (`"Buy"`, `"Hold"`) or a Vibe
    verdict (`"SUPPORT"`, `"REFUTE"`, `"INCONCLUSIVE"`). Stored so a later reader can ask which
    *kind* of refusal a gate made, not merely that it refused."""

    was_explicit: bool = True
    """False when the gate defaulted rather than ruled -- an unparseable Vibe report, a child run
    that degraded or never completed. A defaulted refusal is an abstention, and the study reports
    those separately from judgements: mixing them would let a model that simply failed to answer
    look like a model that thought carefully and said no."""

    verdict_source: Literal["fresh", "cached", "mixed"] = "fresh"
    """Where this ruling's verdict came from -- `"fresh"` (today's only behaviour, and every
    pre-existing row's default) when a child run actually judged this candidate this run;
    `"cached"` when a still-valid `ResearchVerdictCacheEntry` was reused instead of launching a new
    child (see `docs/WORKFLOW-RESEARCH-SPEND-SPEC.md`'s gate 2); `"mixed"` for `full_workflow` when
    one half of its pair (TA or Vibe) was cached and the other was forced fresh -- the linked-
    invalidation case that document's own recon note #5 describes. Not consulted by this module at
    all; carried here purely as a field the research-spend gate chain writes and the study can read
    back."""


class CandidateObservation(_Frozen):
    """One entry signal, every gate's ruling on it, and what the price did next."""

    obs_id: str
    run_id: str
    """The workflow `DeskRun` that scanned this candidate."""

    symbol: str
    decision_date: dt.date
    """The session whose close produced the signal. Fills would happen at the next open."""

    agent_card_id: str
    regime: str = ""

    entry_rank: int = 0
    """Position among the candidates competing for slots that session, from the rules engine's own
    `rank_by` ordering. Carried because a gate that only ever refuses low-ranked candidates is
    adding nothing the ranking did not already say."""

    gates: tuple[GateDecision, ...] = ()

    state: Literal["pending", "resolved"] = "pending"

    horizon_days: int | None = None
    forward_return_pct: Decimal | None = None
    """Fraction of one. `None` while pending, and also when the window could not be priced."""

    benchmark_return_pct: Decimal | None = None
    alpha_return_pct: Decimal | None = None
    """`forward_return_pct - benchmark_return_pct`. Fraction of one."""

    resolved_at: dt.datetime | None = None
    unpriceable: bool = False
    """True when resolution was attempted and the window held too few bars. Distinguished from
    `pending` so a symbol that simply cannot be priced does not sit in the queue forever, and from a
    zero return so it is never averaged in as if it were one."""

    universe_source: UniverseSource = "card"
    """Which universe this candidate was scanned from -- see `UniverseSource`. Default `"card"` is
    correct for every pre-existing row (nothing was ever scanned from a screened universe before this
    field existed) and is what `app.workflow.pipeline` writes unchanged when `universe_mode="card"`."""

    skip_reason: str | None = None
    """`None` when this candidate was actually researched (or its gate ruled with no upstream skip).
    One of `SKIP_REASONS` when the research-spend necessity-gate chain refused to spend on this
    candidate before any child run was even considered -- see that constant's own docstring for the
    exact taxonomy and why `"cache_hit"` is not in it. Default `None` is correct for every
    pre-existing row: the necessity-gate chain did not exist before this field, so nothing was ever
    skipped by it."""

    skip_detail: str = ""
    """Human-readable elaboration on `skip_reason` -- e.g. which arm's book was full, or the
    correlated symbol a `"correlation_duplicate"` skip was measured against. Empty string (not
    `None`) when `skip_reason` is `None`, matching this class's existing convention for optional
    prose fields (`detail` on `GateDecision`, `reject_reason` on `WorkflowOrderRecord`)."""

    avoided_cost_usd: Decimal = Decimal("0")
    """Dollars this candidate's research would have cost fresh, saved by reusing a cached verdict --
    the reused `ResearchVerdictCacheEntry.research_cost_usd` from the *original* fresh run, added on
    when a cache hit occurs (see `GateDecision.verdict_source == "cached"`). `Decimal("0")` -- the
    correct value for every pre-existing row, since nothing was ever avoided before this feature
    existed -- not `None`: summing this field across a window (`docs/WORKFLOW-RESEARCH-SPEND-SPEC.md`
    §4) must never have to skip a row for a missing value."""


def candidates_log_path(settings: Settings) -> Path:
    """`data/agentdesk/workflow/candidates.jsonl`."""
    return agentdesk_dir(settings) / "workflow" / "candidates.jsonl"


def _read_all(path: Path) -> list[CandidateObservation]:
    if not path.is_file():
        return []
    rows: list[CandidateObservation] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            rows.append(CandidateObservation.model_validate_json(line))
        except ValueError as exc:
            logger.warning(
                "workflow candidates: skipping unreadable row at %s:%d: %s", path, line_no, exc
            )
    return rows


def _write_all(path: Path, rows: Sequence[CandidateObservation]) -> None:
    """Atomic whole-file rewrite, mirroring `app.tradingagents.memory._write_all`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.parent / f"{path.name}.{uuid.uuid4().hex}.tmp"
    text = "\n".join(row.model_dump_json() for row in rows)
    staging.write_text(text + ("\n" if text else ""), encoding="utf-8")
    os.replace(staging, path)


def append_observations(
    observations: Sequence[CandidateObservation], *, settings: Settings
) -> None:
    """Append freshly scanned candidates. Called once per workflow run, from the `stage_orders`
    stage, after every gate has ruled but before any order is placed."""
    if not observations:
        return
    path = candidates_log_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in observations:
            handle.write(row.model_dump_json() + "\n")


def read_observations(
    *,
    settings: Settings,
    symbol: str | None = None,
    state: str | None = None,
    universe_source: str | None = None,
) -> tuple[CandidateObservation, ...]:
    """Every logged observation, optionally filtered. The study's data source.

    `universe_source`, when given, keeps only rows whose own `universe_source` matches -- what lets
    `app.workflow.study.build_study(universe_source="screen")` score the discrimination test and
    `vibe_verdict_compliance` against only the candidates a screened run actually produced, rather
    than mixing them with every card-mode candidate ever logged. `None` (the default) is unfiltered,
    reproducing today's behaviour exactly -- every pre-existing caller of this function omits the new
    keyword."""
    rows = _read_all(candidates_log_path(settings))
    if symbol is not None:
        upper = symbol.upper()
        rows = [row for row in rows if row.symbol == upper]
    if state is not None:
        rows = [row for row in rows if row.state == state]
    if universe_source is not None:
        rows = [row for row in rows if row.universe_source == universe_source]
    return tuple(rows)


def _window_return(
    symbol: str, start: dt.date, end: dt.date, *, settings: Settings
) -> Decimal | None:
    """Buy-and-hold return over `[start, end]` off stored daily closes.

    A deliberate copy of `app.tradingagents.memory._realized_return`'s body rather than an import of
    it: that function is private to its module, and this package was told not to invent a second
    convention, not to reach through one module's privacy to reuse it. The conventions it encodes --
    raw `close`, `Decimal(str(...))`, `None` when fewer than two bars land inside the window -- are
    restated here exactly and must not drift from it.
    """
    frame = market_store.read_frame(symbol, Interval.DAY, settings=settings)
    if frame is None or frame.empty:
        return None
    inside = frame[(frame["ts"].dt.date >= start) & (frame["ts"].dt.date <= end)]
    if len(inside) < 2:
        return None
    first = Decimal(str(inside["close"].iloc[0]))
    last = Decimal(str(inside["close"].iloc[-1]))
    if first <= 0:
        return None
    return last / first - 1


def resolve_pending(*, settings: Settings, today: dt.date | None = None) -> int:
    """Price every pending observation old enough to have an outcome. Returns how many were resolved.

    Costs nothing -- no model call, unlike `app.tradingagents.memory.resolve_pending`, which spends
    on a reflector turn. This log is measurement, not memory: nothing reads it back into a prompt, so
    there is nothing here for a model to learn from and no reason to pay one to summarise it.

    Safe to call repeatedly; already-resolved rows are left untouched.
    """
    now = today or dt.date.today()
    path = candidates_log_path(settings)
    rows = _read_all(path)
    if not rows:
        return 0

    resolved = 0
    updated: list[CandidateObservation] = []
    for row in rows:
        due = row.decision_date + dt.timedelta(days=HOLDING_DAYS)
        if row.state == "resolved" or due > now:
            updated.append(row)
            continue

        symbol_return = _window_return(row.symbol, row.decision_date, due, settings=settings)
        benchmark_return = _window_return(
            BENCHMARK_SYMBOL, row.decision_date, due, settings=settings
        )
        if symbol_return is None or benchmark_return is None:
            updated.append(
                row.model_copy(
                    update={
                        "state": "resolved",
                        "unpriceable": True,
                        "horizon_days": HOLDING_DAYS,
                        "resolved_at": dt.datetime.now(dt.UTC),
                    }
                )
            )
            resolved += 1
            continue

        symbol_q = symbol_return.quantize(_FRACTION_QUANT)
        benchmark_q = benchmark_return.quantize(_FRACTION_QUANT)
        updated.append(
            row.model_copy(
                update={
                    "state": "resolved",
                    "horizon_days": HOLDING_DAYS,
                    "forward_return_pct": symbol_q,
                    "benchmark_return_pct": benchmark_q,
                    "alpha_return_pct": (symbol_q - benchmark_q).quantize(_FRACTION_QUANT),
                    "resolved_at": dt.datetime.now(dt.UTC),
                }
            )
        )
        resolved += 1

    if resolved:
        _write_all(path, updated)
    return resolved

"""Grounded model *decisions* on a live tape -- one opinion per symbol per tick, recorded and served,
and never once acted on.

**This module decides. It does not trade.** Nothing here places, stages, queues or fills an order, and
nothing downstream of it does either: a `LiveDecisionRecord` is appended to a JSONL file and read back
by `app.api.live_decisions`. That is the whole feature. The paper desks (`app.paperdesk`,
`app.workflow`) own execution and are not wired to this; if a future change ever wants to connect the
two, that is a deliberate, separately-reviewed edit and not something this module quietly permits.

**Why a daemon at all, when both agent desks already run on demand.** Trading Agents and Vibe Trading
answer a question a person just asked, as of a session that has already closed. The thing neither can
do is notice that the tape moved while nobody was looking. This loop is the cheap version of that: on a
half-hourly cadence, during regular market hours only, ask one grounded call per watched symbol what it
makes of the live quote and the day's intraday bars. The output is research signal with no measured
edge behind it -- the same standing caveat every model-driven feature in this application carries.

**Every guard here exists because this spends money unattended.** `Settings.live_decisions_enabled`
defaults `False` and `start` is a no-op without it. One tick's calls share a single
`AgentBudget(cap_usd=live_decisions_cap_usd)` and the tick stops the moment it is exhausted rather than
walking the rest of the watchlist. `app.agents.spend.LEDGER` is checked before *every* call, so the
process-wide rolling-24h cap bounds the daemon the same way it bounds the persona routes. Outside a
`REGULAR` market state nothing is asked at all -- a pre-market opinion on a stale quote is spend for a
number the evidence layer would have flagged as stale anyway.

**Failure is counted, not swallowed.** `run_once` never raises: a symbol whose call fails is counted in
`TickSummary.failures` and the tick continues. But a tick that decided nothing while failing is a
consecutive failure, and `_MAX_CONSECUTIVE_FAILURES` of those flips `status()["healthy"]` to `False` --
see `app.workflow.loop`'s own constant and the incident it documents (1,644 identical, silently
tolerated failures reported as "running").
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agentdesk import evidence
from app.agentdesk.grounding import run_grounded
from app.agentdesk.models import EvidencePack
from app.agents.models import AgentBudget, AgentRole, AgentUnavailable, BudgetExhausted
from app.agents.spend import LEDGER, SpendCapExceeded
from app.config import Settings, get_settings
from app.market import livefeed

__all__ = [
    "InvalidSymbol",
    "LiveDecision",
    "LiveDecisionRecord",
    "TickSummary",
    "decide",
    "list_decisions",
    "reset",
    "run_once",
    "start",
    "status",
    "stop",
]

logger = logging.getLogger(__name__)

#: What one decision is allowed to read. `price`/`indicators` give the stored context a live tick has
#: to be judged against (a 2% move means nothing without the range it moved inside), `live_quote` and
#: `intraday` are the live half, and `news` is the cheapest available explanation for why the tape is
#: doing whatever it is doing. Deliberately no `fundamentals`/`macro`/`events`: this is a same-day
#: read, and every extra section is tokens on every call of every tick.
SECTIONS: tuple[str, ...] = ("price", "indicators", "live_quote", "intraday", "news")

#: The market state a tick requires. Only `"REGULAR"` -- see the module docstring.
REGULAR_MARKET_STATE = "REGULAR"

#: How many *consecutive* decided-nothing-and-failed ticks flip `status()["healthy"]` to `False`.
#: Mirrors `app.workflow.loop._MAX_CONSECUTIVE_FAILURES` and the incident its comment records.
_MAX_CONSECUTIVE_FAILURES = 5

#: Slice length for the interruptible sleep, so `stop()` takes effect within a second of being called
#: even mid-interval. Same value and same reasoning as `app.workflow.loop._SLEEP_SLICE_SECONDS`.
_SLEEP_SLICE_SECONDS = 1.0

#: A ticker, matching `app.tradingagents.service._SYMBOL_RE` exactly -- wide enough for `BRK.B`, tight
#: enough that `422` has a shape to name.
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")

#: The role every live decision archives under. `"trader"` rather than a new `AgentRole` member: this
#: is the same job `app.tradingagents.prompts.TRADER_SYSTEM` describes -- turn a read of the evidence
#: into an actionable stance -- on a shorter horizon and without a research plan upstream of it, and
#: widening the closed `AgentRole` literal for a call that groups naturally with the trader's would
#: split one audit bucket in two for no reader's benefit.
ROLE: AgentRole = "trader"

SYSTEM = """\
You are the live desk. You are handed one instrument's evidence -- its recent daily prices and
indicators, its current quote, today's intraday bars, and recent headlines -- and you return one
stance on it.

EVIDENCE ONLY. Every number in your rationale must appear in the EVIDENCE block, or be a difference or
percentage change between two figures in it. You have no memory of this instrument and cannot fetch
anything. Your rationale is checked token by token against the evidence and bounced back to you if it
is not.

If the live quote section is empty, unavailable, or reports no price, answer `no_action` and say in
one clause that there is no live quote to read. Do not reason about the current market from the stored
daily bars alone -- that is a different question than the one you were asked.

Write dates in full ISO form (YYYY-MM-DD) and state figures at the evidence's own precision.

`stance` is one of buy, sell, hold, no_action. `confidence` is 0 to 1 and should be low whenever the
evidence is thin, stale or contradictory. `horizon` is intraday, days or weeks -- the period over which
you claim the stance would be judged.

This is paper research signal, not advice, and nothing executes it. Say what the evidence supports;
where it supports nothing, say that instead. Keep the rationale under 600 characters."""


# ---------------------------------------------------------------------------
# Wire/persistence types
# ---------------------------------------------------------------------------


class InvalidSymbol(ValueError):
    """`decide` was given something that is not a ticker -- the router's 422."""


class LiveDecision(BaseModel):
    """The structured output of one live call -- what the model actually returns."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    stance: Literal["buy", "sell", "hold", "no_action"]
    """`no_action` is not a fourth flavour of hold: `hold` is a claim about the instrument, while
    `no_action` is a claim about the evidence -- there was not enough of it to have a view."""

    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(max_length=600)
    """The only prose, and the only thing `app.agentdesk.grounding` checks. Capped so a decision stays
    a decision rather than becoming the report the two agent desks already produce."""

    horizon: Literal["intraday", "days", "weeks"]


class LiveDecisionRecord(BaseModel):
    """One decision as persisted (a JSONL line) and as served (`GET /api/agentdesk/live/decisions`).

    Money and prices are decimal *strings*, per this codebase's money convention -- never JSON numbers.
    Timestamps are timezone-aware UTC.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    decided_at: dt.datetime
    symbol: str
    stance: str
    confidence: float
    rationale: str
    horizon: str

    price: str | None = None
    """The live price this decision was made against, or `None` when no quote was available -- in
    which case the model was told to answer `no_action`, and a record saying so is still worth keeping:
    "the feed was down at 14:30" is a fact about the day."""

    quoted_at: dt.datetime | None = None
    market_state: str | None = None

    grounded: bool = False
    """`GroundingVerdict.ok` -- the rationale's numbers all trace to the pack."""

    degraded: bool = False
    """`GroundingVerdict.degraded` -- released despite failing the gate after every retry. Never
    silently: this field is what the page shows the reader."""

    cost_usd: str = "0"
    model: str = ""
    source: Literal["daemon", "manual"] = "manual"
    call_ids: tuple[str, ...] = ()
    """The `AgentCall` ids under `data/loop/agent_calls/`, so a decision can be audited back to the
    exact prompt and response that produced it -- more than one when the gate forced a retry."""


@dataclass(frozen=True, slots=True)
class TickSummary:
    """What one `run_once` call did. Returned for a caller (a log line, a test) to inspect; the
    durable record is the JSONL the tick appended."""

    ticked_at: dt.datetime
    market_state: str | None
    symbols: tuple[str, ...]
    decided: int
    skipped_reason: Literal["market_closed", "spend_cap", "no_symbols"] | None = None
    failures: int = 0


# ---------------------------------------------------------------------------
# Persistence -- append-only JSONL, one file per UTC date
# ---------------------------------------------------------------------------

_write_lock = threading.Lock()


def _decisions_dir(settings: Settings) -> Path:
    return settings.data_dir / "agentdesk" / "live_decisions"


def _decisions_path(settings: Settings, day: dt.date) -> Path:
    return _decisions_dir(settings) / f"{day.isoformat()}.jsonl"


def _notify_decision(record: LiveDecisionRecord, *, settings: Settings, source: str) -> None:
    """Announce one actionable live decision through `app.notify`.

    **Only `buy`/`sell`, and only when the gate passed.** `hold` and `no_action` are the overwhelming
    majority of what a watchlist tick produces and none of them asks anything of the reader -- a phone
    that buzzes to say "nothing changed" is a phone that gets muted, and muting it loses the two
    stances that did matter. A `degraded` record is excluded for a different reason: its rationale
    carries at least one figure that could not be traced back to the evidence pack, and a lock-screen
    notification is precisely the context in which nobody will go and check. It is still logged, still
    served by `GET /api/agentdesk/live/decisions`, and still marked degraded there.

    `attention` severity because a live buy/sell is time-bound -- it is about a price that exists now
    -- which is exactly what the top severity's quiet-hours exemption is for.
    """
    if record.stance not in {"buy", "sell"} or record.degraded:
        return
    try:
        from app.notify import emit

        price = record.price if record.price is not None else "no quote"
        emit(
            settings,
            kind="signal.live",
            severity="attention",
            headline=f"Live signal: {record.stance.upper()} {record.symbol} @ {price}",
            detail=record.rationale[:300],
            refs=(f"symbol:{record.symbol}",),
            source=f"live_loop:{source}",
            dedupe_id=f"signal.live:{record.symbol}:{record.decided_at.isoformat()}",
        )
    except Exception:
        logger.exception(
            "live_loop: notify hook failed for %s; the decision itself is filed", record.symbol
        )


def _append(record: LiveDecisionRecord, *, settings: Settings) -> None:
    """Append one record to its UTC date's file, creating the directory on first write.

    Append-only and one file per day for the same reason `app.workflow`'s own logs are: a decision is
    an observation, and rewriting a whole day's file to add one line is both slower and a chance to
    lose the other lines. A failure here is logged and swallowed -- a decision that was made but could
    not be filed is still worth returning to the caller who asked for it.
    """
    path = _decisions_path(settings, record.decided_at.astimezone(dt.UTC).date())
    line = json.dumps(record.model_dump(mode="json"), separators=(",", ":"))
    try:
        with _write_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except OSError:
        logger.exception("live_loop: could not persist a decision for %s", record.symbol)


def _read_file(path: Path) -> list[LiveDecisionRecord]:
    """Every parseable record in one day's file. A malformed line is skipped, not fatal: the file is
    appended to by a long-running daemon, and one truncated line (a crash mid-write) must not hide the
    hundred good ones around it."""
    if not path.exists():
        return []
    records: list[LiveDecisionRecord] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.exception("live_loop: could not read %s", path)
        return []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            records.append(LiveDecisionRecord.model_validate_json(stripped))
        except ValueError:
            logger.warning("live_loop: skipping an unreadable decision line in %s", path)
    return records


def list_decisions(
    settings: Settings, *, symbol: str | None = None, limit: int = 50
) -> list[LiveDecisionRecord]:
    """The most recent decisions, newest first, optionally filtered to one symbol.

    Reads today's and yesterday's files only. That is a deliberate bound rather than a full scan: the
    endpoint this backs is a "what has the desk said lately" panel, a day's file holds a few hundred
    lines at most, and reading two of them keeps the answer cheap and constant-cost as the directory
    grows. Yesterday's is included so a request made just after midnight UTC -- i.e. during the US
    afternoon session -- still shows that session's decisions.
    """
    today = dt.datetime.now(dt.UTC).date()
    records: list[LiveDecisionRecord] = []
    for day in (today, today - dt.timedelta(days=1)):
        records.extend(_read_file(_decisions_path(settings, day)))

    if symbol:
        wanted = symbol.strip().upper()
        records = [record for record in records if record.symbol == wanted]

    records.sort(key=lambda record: record.decided_at, reverse=True)
    return records[: max(limit, 0)]


# ---------------------------------------------------------------------------
# One decision
# ---------------------------------------------------------------------------


def _validate_symbol(symbol: str) -> str:
    upper = symbol.strip().upper()
    if not _SYMBOL_RE.match(upper):
        raise InvalidSymbol(f"invalid symbol: {symbol!r}")
    return upper


def _rationale_of(decision: LiveDecision) -> str:
    """What the grounding gate checks. The rationale only: `stance` and `horizon` are closed
    enumerations and `confidence` is the model's own self-report, not a claim about the market, so
    none of the three can carry a fabricated figure."""
    return decision.rationale


def _user_turn(symbol: str, pack: EvidencePack) -> str:
    return (
        f"Instrument: {symbol}\n"
        f"As of: live · {dt.datetime.now(dt.UTC).isoformat()}\n\n"
        f"EVIDENCE:\n{evidence.render_pack(pack)}"
    )


def decide(
    symbol: str,
    *,
    settings: Settings,
    source: Literal["daemon", "manual"] = "manual",
    budget: AgentBudget | None = None,
) -> LiveDecisionRecord:
    """One grounded live decision on `symbol`, persisted and returned.

    Synchronous and single-call -- this is not a pipeline. `budget` lets a tick share one ceiling
    across its whole watchlist; omitted, a fresh `AgentBudget(cap_usd=live_decisions_cap_usd)` bounds
    this one call.

    Raises `InvalidSymbol` (422), `app.agents.spend.SpendCapExceeded` (429, checked *before* the call,
    matching `app.personas.trader.advance_one_decision`'s own placement), `AgentUnavailable` (503) and
    `BudgetExhausted` -- all four straight through, because each one is a different answer the caller
    has to give and collapsing them into one would lose that. A *grounding* failure is not among them:
    `run_grounded` releases the value `degraded` instead, and the record says so.
    """
    upper = _validate_symbol(symbol)

    LEDGER.check(settings.model_spend_daily_cap_usd)

    pack = evidence.build_pack(upper, None, settings=settings, sections=SECTIONS)
    run_budget = budget if budget is not None else AgentBudget(cap_usd=settings.live_decisions_cap_usd)

    result = run_grounded(
        role=ROLE,
        system=SYSTEM,
        user=_user_turn(upper, pack),
        output_format=LiveDecision,
        prose_of=_rationale_of,
        pack=pack,
        settings=settings,
        budget=run_budget,
        model=settings.live_decisions_model,
    )

    quote, snap = livefeed.latest_with_snapshot(upper)
    cost = sum((call.cost_usd for call in result.calls), Decimal(0))
    record = LiveDecisionRecord(
        decided_at=dt.datetime.now(dt.UTC),
        symbol=upper,
        stance=result.value.stance,
        confidence=result.value.confidence,
        rationale=result.value.rationale,
        horizon=result.value.horizon,
        price=f"{quote.price:.2f}" if quote is not None else None,
        quoted_at=quote.ts if quote is not None else None,
        market_state=snap.market_state if snap is not None else None,
        grounded=result.verdict.ok,
        degraded=result.verdict.degraded,
        cost_usd=str(cost),
        model=settings.live_decisions_model,
        source=source,
        call_ids=tuple(call.call_id for call in result.calls),
    )
    _append(record, settings=settings)
    _notify_decision(record, settings=settings, source=source)
    return record


# ---------------------------------------------------------------------------
# One tick
# ---------------------------------------------------------------------------


def _resolve_symbols(settings: Settings) -> tuple[str, ...]:
    """This tick's watchlist: `live_decisions_symbols` when set, else what the ledger holds, capped.

    The ledger read is `app.market.refresh._held_symbols`, imported lazily so importing this module
    never opens a SQLite connection, and cap-limited by `live_decisions_max_symbols` -- a sixty-symbol
    ledger would otherwise mean sixty model calls a tick.
    """
    configured = [part.strip().upper() for part in settings.live_decisions_symbols.split(",")]
    explicit = [part for part in configured if part]
    if explicit:
        seen: set[str] = set()
        out: list[str] = []
        for symbol in explicit:
            if symbol not in seen:
                seen.add(symbol)
                out.append(symbol)
        return tuple(out)

    from app.market.refresh import _held_symbols

    try:
        held = _held_symbols(settings)
    except Exception:
        logger.exception("live_loop: could not read held symbols; this tick has no watchlist")
        return ()
    return tuple(held[: max(settings.live_decisions_max_symbols, 0)])


def run_once(settings: Settings, *, now: dt.datetime | None = None) -> TickSummary:
    """One tick: decide on every watched symbol, under one shared budget, and never raise.

    Public and synchronous so a test (and a future manual "tick now" route) drives exactly what the
    daemon drives, rather than a second code path that only resembles it -- the same shape
    `app.workflow.loop.run_once` uses for the same reason.

    Skips, in order: no watchlist (`"no_symbols"`), a market that is not `REGULAR` (`"market_closed"`,
    which includes a feed that could not be reached at all -- an unknown market state is not a licence
    to spend), and either spend ceiling (`"spend_cap"`). A per-symbol failure is counted in `failures`
    and the tick moves on; a tick that decided nothing while failing increments the consecutive-failure
    streak `status()["healthy"]` reports on.
    """
    ticked_at = now or dt.datetime.now(dt.UTC)
    symbols = _resolve_symbols(settings)
    if not symbols:
        return _finish(TickSummary(ticked_at=ticked_at, market_state=None, symbols=(), decided=0,
                                   skipped_reason="no_symbols"))

    try:
        snap = livefeed.snapshot(symbols)
        market_state: str | None = snap.market_state
    except Exception:
        logger.warning("live_loop: could not snapshot the watchlist; skipping this tick", exc_info=True)
        market_state = None

    if market_state != REGULAR_MARKET_STATE:
        return _finish(TickSummary(ticked_at=ticked_at, market_state=market_state, symbols=symbols,
                                   decided=0, skipped_reason="market_closed"))

    budget = AgentBudget(cap_usd=settings.live_decisions_cap_usd)
    decided = 0
    failures = 0
    skipped: Literal["market_closed", "spend_cap", "no_symbols"] | None = None

    for symbol in symbols:
        if budget.exhausted:
            skipped = "spend_cap"
            break
        try:
            record = decide(symbol, settings=settings, source="daemon", budget=budget)
        except (BudgetExhausted, SpendCapExceeded) as exc:
            logger.info("live_loop: tick stopped at %s: %s", symbol, exc)
            skipped = "spend_cap"
            break
        except AgentUnavailable as exc:
            logger.warning("live_loop: %s could not be decided: %s", symbol, exc)
            failures += 1
            continue
        except Exception:
            logger.exception("live_loop: %s raised while deciding", symbol)
            failures += 1
            continue

        decided += 1
        # `decide` returns a record, not a budget, so the tick's running total is rebuilt from the
        # record's own cost -- the same figure `AgentBudget` would have accumulated, and the reason
        # `LiveDecisionRecord.cost_usd` is summed over every attempt rather than just the accepted one.
        budget = AgentBudget(
            cap_usd=budget.cap_usd,
            spent_usd=budget.spent_usd + Decimal(record.cost_usd),
            calls=budget.calls + 1,
        )

    return _finish(TickSummary(ticked_at=ticked_at, market_state=market_state, symbols=symbols,
                               decided=decided, skipped_reason=skipped, failures=failures))


# ---------------------------------------------------------------------------
# Module state -- the daemon, and what `status()` reports
# ---------------------------------------------------------------------------

_state_lock = threading.Lock()
_singleton_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None
_settings: Settings | None = None
_ticks = 0
_consecutive_failures = 0
_last_tick_at: dt.datetime | None = None
_next_wake_at: dt.datetime | None = None
_market_state: str | None = None
_symbols: tuple[str, ...] = ()


def _finish(summary: TickSummary) -> TickSummary:
    """Fold one tick's outcome into the module state `status()` reports, and return it unchanged.

    A tick that decided nothing *and* failed at least once is a consecutive failure; a tick that
    decided anything clears the streak. A skip (closed market, no watchlist, a cap already reached) is
    neither -- the daemon is behaving correctly, and counting those as failures would report a
    perfectly healthy weekend as an outage.
    """
    global _ticks, _consecutive_failures, _last_tick_at, _market_state, _symbols
    with _state_lock:
        _ticks += 1
        _last_tick_at = summary.ticked_at
        _market_state = summary.market_state
        _symbols = summary.symbols
        if summary.decided:
            _consecutive_failures = 0
        elif summary.failures:
            _consecutive_failures += 1
    return summary


def _sleep_checking_stop(
    stop_event: threading.Event, seconds: float, *, interval: float = _SLEEP_SLICE_SECONDS
) -> None:
    """Sleep up to `seconds` in slices, returning early the moment `stop_event` is set -- copied in
    shape from `app.workflow.loop._sleep_checking_stop`; see that function for why it is neither a
    bare `time.sleep` nor a spin loop."""
    deadline = time.monotonic() + max(seconds, 0.0)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or stop_event.is_set():
            return
        time.sleep(min(interval, remaining))


def _daemon_loop(settings: Settings, stop_event: threading.Event) -> None:
    """Tick, sleep, repeat until stopped. One bad tick never stops the loop -- `run_once` does not
    raise, and the `except` here covers only the pathological case of the state bookkeeping itself
    failing."""
    interval_seconds = max(settings.live_decisions_interval_minutes, 1.0) * 60.0
    logger.info(
        "live_loop: daemon started, ticking every %.1f minutes (decisions only; nothing is traded)",
        settings.live_decisions_interval_minutes,
    )

    global _next_wake_at
    while not stop_event.is_set():
        try:
            summary = run_once(settings)
            logger.info(
                "live_loop: tick %s -- market_state=%s decided=%d failures=%d skipped=%s",
                summary.ticked_at.isoformat(), summary.market_state, summary.decided,
                summary.failures, summary.skipped_reason,
            )
        except Exception:  # pragma: no cover - run_once is already total; defensive only
            logger.exception("live_loop: tick raised; continuing")

        with _state_lock:
            failures = _consecutive_failures
            _next_wake_at = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=interval_seconds)
        if failures >= _MAX_CONSECUTIVE_FAILURES:
            logger.error(
                "live_loop: %d consecutive ticks decided nothing and failed -- this needs attention; "
                "the daemon keeps ticking so it can recover once the fault clears, but it is not "
                "making progress",
                failures,
            )

        _sleep_checking_stop(stop_event, interval_seconds)

    with _state_lock:
        _next_wake_at = None
    logger.info("live_loop: daemon stopped")


def start(settings: Settings) -> None:
    """Launch the daemon and return immediately -- a no-op, logged, when
    `settings.live_decisions_enabled` is off, and a no-op when one is already running in this process.

    Called unconditionally from `app.main.lifespan` with the "should this do anything" gate inside the
    function, exactly as `app.workflow.loop.start` and `app.market.livefeed.start` are.
    """
    global _thread, _stop_event, _settings

    with _state_lock:
        _settings = settings

    if not settings.live_decisions_enabled:
        logger.info("live_loop: disabled (live_decisions_enabled=False); not starting")
        return

    with _singleton_lock:
        if _thread is not None and _thread.is_alive():
            logger.info("live_loop: already running in this process; not starting a second one")
            return

        stop_event = threading.Event()
        thread = threading.Thread(
            target=_daemon_loop, args=(settings, stop_event), daemon=True, name="agentdesk-live"
        )
        _stop_event = stop_event
        _thread = thread
        thread.start()


def stop(*, timeout: float = 5.0) -> None:
    """Signal the daemon to stop and join it, up to `timeout` seconds. A no-op when none is running.

    A tick in flight is not interrupted: its remaining symbols simply run to completion, which is at
    most one model call each and cannot corrupt anything -- the JSONL is append-only.
    """
    global _thread, _stop_event

    with _singleton_lock:
        thread = _thread
        stop_event = _stop_event

    if thread is None or stop_event is None:
        return

    stop_event.set()
    thread.join(timeout=timeout)

    with _singleton_lock:
        if _thread is thread:
            _thread = None
            _stop_event = None


def reset() -> None:
    """Drop every module-level counter and the remembered settings, stopping any running daemon
    first. For tests, and for the same reason `app.market.livefeed.reset` exists: module state that
    survives between tests makes one test's tick another test's history."""
    stop()
    global _ticks, _consecutive_failures, _last_tick_at, _next_wake_at, _market_state, _symbols, _settings
    with _state_lock:
        _ticks = 0
        _consecutive_failures = 0
        _last_tick_at = None
        _next_wake_at = None
        _market_state = None
        _symbols = ()
        _settings = None


def status() -> dict[str, Any]:
    """A JSON-ready view of the loop, for `GET /api/agentdesk/live/status`.

    **Always answers, and never does real work to do it.** No model call, no provider call, and -- like
    `app.market.livefeed.status` -- no ledger read: `symbols` reports the last tick's watchlist, or the
    configured list when no tick has run, rather than opening SQLite to derive a fresh one. The one
    file it touches is today's JSONL, to count `decisions_today`, which is a line count on a file this
    process wrote.

    The keys are a pinned contract -- exactly these twelve, per `docs/AGENT-DESK-CONTRACT.md`:
    `enabled`, `running`, `healthy`, `market_state`, `last_tick_at`, `next_wake_at`, `ticks`,
    `decisions_today`, `consecutive_failures`, `symbols`, `interval_minutes`, `cap_usd`.

    `healthy` is `None` until the first tick -- a loop that has not run yet is neither healthy nor
    unhealthy, the same three-state answer `livefeed.status` gives for the same reason.
    """
    with _state_lock:
        cfg = _settings
        thread = _thread
        ticks = _ticks
        failures = _consecutive_failures
        last_tick_at = _last_tick_at
        next_wake_at = _next_wake_at
        market_state = _market_state
        symbols = list(_symbols)

    settings = cfg if cfg is not None else get_settings()
    if not symbols:
        symbols = [part.strip().upper() for part in settings.live_decisions_symbols.split(",") if part.strip()]

    healthy: bool | None = None
    if ticks > 0:
        healthy = failures < _MAX_CONSECUTIVE_FAILURES

    today = _decisions_path(settings, dt.datetime.now(dt.UTC).date())
    decisions_today = len(_read_file(today))

    return {
        "enabled": bool(settings.live_decisions_enabled),
        "running": thread is not None and thread.is_alive(),
        "healthy": healthy,
        "market_state": market_state,
        "last_tick_at": last_tick_at.isoformat() if last_tick_at is not None else None,
        "next_wake_at": next_wake_at.isoformat() if next_wake_at is not None else None,
        "ticks": ticks,
        "decisions_today": decisions_today,
        "consecutive_failures": failures,
        "symbols": symbols,
        "interval_minutes": float(settings.live_decisions_interval_minutes),
        "cap_usd": str(settings.live_decisions_cap_usd),
    }

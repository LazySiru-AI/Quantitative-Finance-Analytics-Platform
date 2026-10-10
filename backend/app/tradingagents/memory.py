"""Outcome-resolved decision memory: the desk's own record of what it decided and what actually
happened, read back by the portfolio manager alone (see `PORTFOLIO_MANAGER_SYSTEM`).

**Two writes, one file.** `append_pending` runs at the end of every successful pipeline run and costs
no model call -- it logs the rating the run already produced. `resolve_pending` runs at the *start* of
the next run for the same symbol (`app.tradingagents.service.start_run` calls it before a new run is
created) and is the only function here that spends anything: for each pending entry old enough to have
a realised outcome, it prices the symbol and SPY over the holding window, then asks the `reflector`
role for a short, evidence-grounded lesson. JSONL rather than a single markdown file with an
`ENTRY_END` delimiter (upstream's own format) -- one JSON object per line resolves by rewriting the
file the same atomic way `app.agentdesk.store.RunStore.save` does, without needing a delimiter a model
cannot reliably reproduce. See `memory_log_path`'s own docstring for the exact path.

**Money convention -- read this before touching `raw_return_pct`/`alpha_return_pct`.** Both are
fractions of one, matching every other `_pct`/`return_pct` field in this codebase (`Holding.
return_pct`, `LadderRung.drawdown_pct`, `AllocationCardOut.stop_loss_pct`): `0.0532` means +5.32%,
never `5.32`. `docs/AGENT-DESK-CONTRACT.md`'s own `MemoryEntry` interface says so explicitly. This is
independent of how a figure is *displayed* to a model or a reader -- `_display_pct` below converts a
fraction to a percent string (`"5.32"`, unit `"%"`) purely for prose and for the `EvidenceItem`s a
model is allowed to cite, and that converted string is never what gets written back into a
`MemoryEntryModel`.

**Realised return is read the same way `app.paperdesk.desk._buy_and_hold` reads it**, per this
package's own instruction not to invent a second convention: `app.market.store.read_frame`'s full
stored history, filtered to `[start, end]`, priced off raw `close` (never `adj_close`) as
`Decimal(str(value))` at the first and last row inside the window. `None` -- not a fabricated zero --
when there are fewer than two bars inside the window, exactly `_buy_and_hold`'s own convention.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import uuid
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from app.agentdesk.evidence import render_pack
from app.agentdesk.grounding import run_grounded
from app.agentdesk.models import (
    DeskRun,
    EvidenceItem,
    EvidencePack,
    EvidenceSection,
    memory_log_path,
)
from app.agents.models import AgentBudget, AgentUnavailable, BudgetExhausted
from app.config import Settings
from app.market import store as market_store
from app.market.models import Interval
from app.tradingagents import schemas
from app.tradingagents.prompts import REFLECTOR_SYSTEM

if TYPE_CHECKING:  # pragma: no cover - typing only; avoids a runtime import cycle with pipeline.py
    from app.tradingagents.pipeline import PipelineConfig

__all__ = [
    "MemoryEntryModel",
    "append_pending",
    "lessons_evidence_items",
    "lessons_for_prompt",
    "read_entries",
    "resolve_pending",
]

logger = logging.getLogger(__name__)

#: Calendar days a pending decision waits before it is treated as having a realised outcome -- roughly
#: three trading weeks, long enough for a directional call to have actually played out and short
#: enough that a symbol run every few weeks still accumulates a track record. A judgement, not a
#: backtested optimum, exactly like `app.paperdesk.benchmarks`'s own blend weights.
_HOLDING_DAYS = 21

#: Fraction precision `raw_return_pct`/`alpha_return_pct` are stored at -- six decimal places is
#: comfortably finer than a basis point, which is all the realised-return arithmetic here can ever
#: resolve to given daily closes.
_FRACTION_QUANT = Decimal("0.000001")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class MemoryEntryModel(_Frozen):
    """One row of the desk's decision log -- the Python type behind the wire `MemoryEntry` in
    `docs/AGENT-DESK-CONTRACT.md`. `raw_return_pct`/`alpha_return_pct` are fractions of one (see this
    module's docstring); both are `None` while `state == "pending"`.
    """

    entry_id: str
    symbol: str
    trade_date: dt.date
    rating: str
    state: Literal["pending", "resolved"]
    raw_return_pct: Decimal | None = None
    alpha_return_pct: Decimal | None = None
    benchmark: str = "SPY"
    holding_days: int | None = None
    decision_md: str
    reflection: str = ""


def _frac(value: Decimal) -> Decimal:
    return value.quantize(_FRACTION_QUANT)


def _display_pct(value: Decimal | None) -> str:
    """`value` (a fraction) rendered as the percent string a model is expected to cite in prose --
    `0.0532` becomes `"5.32"`. Used only for `EvidenceItem.value` and for the markdown this module
    builds for a reader; never for what gets stored back into a `MemoryEntryModel` field."""
    if value is None:
        return "n/a"
    return str((value * 100).quantize(Decimal("0.01")))


def _realized_return(symbol: str, start: dt.date, end: dt.date, *, settings: Settings) -> Decimal | None:
    """Buy-and-hold return of `symbol` from `start` to `end`, priced off stored daily closes.

    Mirrors `app.paperdesk.desk._buy_and_hold` exactly -- same store call, same window filter, same
    `Decimal(str(...))` conversion, same `None`-for-unpriceable convention -- because that is the
    established way this codebase turns a window into a realised return, and this module was told not
    to invent a second one.
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


# ---------------------------------------------------------------------------
# File I/O -- append for a new pending entry, atomic rewrite to resolve one
# ---------------------------------------------------------------------------


def _read_all(path: Path) -> list[MemoryEntryModel]:
    if not path.is_file():
        return []
    entries: list[MemoryEntryModel] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            entries.append(MemoryEntryModel.model_validate_json(line))
        except ValueError as exc:
            logger.warning("tradingagents memory: skipping unreadable entry at %s:%d: %s", path, line_no, exc)
    return entries


def _write_all(path: Path, entries: Sequence[MemoryEntryModel]) -> None:
    """Atomic whole-file rewrite -- temp file in the same directory, then `os.replace`, matching
    `app.agentdesk.store.RunStore.save`'s own reasoning for why a direct in-place write is not safe
    against a concurrent reader."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.parent / f"{path.name}.{uuid.uuid4().hex}.tmp"
    text = "\n".join(entry.model_dump_json() for entry in entries)
    staging.write_text(text + ("\n" if text else ""), encoding="utf-8")
    os.replace(staging, path)


def append_pending(run: DeskRun, config: PipelineConfig, *, settings: Settings) -> None:
    """Log the run's own decision as a fresh `pending` entry -- no model call, no realised outcome
    yet. Called once, from `app.tradingagents.pipeline.run_pipeline`, right after a run reaches
    `"succeeded"`.
    """
    entry = MemoryEntryModel(
        entry_id=str(uuid.uuid4()),
        symbol=config.symbol.upper(),
        trade_date=config.trade_date or dt.date.today(),
        rating=run.final_rating or "Hold",
        state="pending",
        decision_md=run.final_md,
    )
    path = memory_log_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(entry.model_dump_json() + "\n")


def read_entries(symbol: str | None, *, settings: Settings) -> tuple[MemoryEntryModel, ...]:
    """Every logged entry, optionally filtered to one symbol -- `GET /api/tradingagents/memory`'s own
    data source, and `pending` entries are included (the wire contract shows them with `reflection:
    ""`)."""
    entries = _read_all(memory_log_path(settings))
    if symbol is not None:
        upper = symbol.upper()
        entries = [entry for entry in entries if entry.symbol == upper]
    return tuple(entries)


# ---------------------------------------------------------------------------
# Resolution -- the one place this module spends money
# ---------------------------------------------------------------------------


def _outcome_pack(
    entry: MemoryEntryModel, *, symbol_return: Decimal, spy_return: Decimal, alpha: Decimal
) -> EvidencePack:
    """The reflector's own `EvidencePack`: the three measured figures it is allowed to cite, plus the
    original decision as prose context (not evidence -- see `EvidenceSection.text`'s own contract)."""
    as_of = (entry.trade_date + dt.timedelta(days=_HOLDING_DAYS)).isoformat()
    items = (
        EvidenceItem(
            key="symbol_return_pct", label=f"{entry.symbol} realized return",
            value=_display_pct(symbol_return), unit="%", as_of=as_of, source="duckdb-store",
        ),
        EvidenceItem(
            key="benchmark_return_pct", label="SPY realized return",
            value=_display_pct(spy_return), unit="%", as_of=as_of, source="duckdb-store",
        ),
        EvidenceItem(
            key="alpha_return_pct", label=f"{entry.symbol} return vs SPY",
            value=_display_pct(alpha), unit="%", as_of=as_of, source="duckdb-store",
        ),
    )
    section = EvidenceSection(
        title="Outcome",
        items=items,
        text=(
            f"Original decision on {entry.trade_date.isoformat()}, rated {entry.rating}:\n"
            f"{entry.decision_md}"
        ),
    )
    return EvidencePack(symbol=entry.symbol, as_of=entry.trade_date, sections=(section,))


def _reflector_user(entry: MemoryEntryModel, pack: EvidencePack) -> str:
    return (
        f"Instrument: {entry.symbol}\n"
        f"Decision date: {entry.trade_date.isoformat()}\n"
        f"Rating at the time: {entry.rating}\n\n"
        f"EVIDENCE:\n{render_pack(pack)}"
    )


def resolve_pending(symbol: str, *, settings: Settings, budget: AgentBudget, model: str) -> AgentBudget:
    """Resolve every stale `pending` entry for `symbol` against realised return, writing a
    `reflector`-authored lesson into each -- called once, at the start of a new run on the same
    symbol, by `app.tradingagents.service.start_run`.

    An entry is left `pending` -- tried again on a future run -- for three reasons: it has not aged
    past `_HOLDING_DAYS` yet, the store cannot price the symbol or SPY over the window (no bars, or
    not enough of them), or the reflector call itself raised `BudgetExhausted`/`AgentUnavailable`. None
    of these are errors this function raises; a run must always be able to start even when memory
    resolution cannot complete, which is why `service.start_run` calls this inside a broad `except`.
    """
    upper = symbol.upper()
    path = memory_log_path(settings)
    entries = _read_all(path)
    if not entries:
        return budget

    today = dt.date.today()
    current_budget = budget
    changed = False
    updated: list[MemoryEntryModel] = []

    for entry in entries:
        if entry.symbol != upper or entry.state != "pending":
            updated.append(entry)
            continue

        window_end = entry.trade_date + dt.timedelta(days=_HOLDING_DAYS)
        if today < window_end:
            updated.append(entry)
            continue

        symbol_return = _realized_return(entry.symbol, entry.trade_date, window_end, settings=settings)
        spy_return = _realized_return("SPY", entry.trade_date, window_end, settings=settings)
        if symbol_return is None or spy_return is None:
            updated.append(entry)
            continue

        alpha = symbol_return - spy_return
        pack = _outcome_pack(entry, symbol_return=symbol_return, spy_return=spy_return, alpha=alpha)
        user = _reflector_user(entry, pack)

        try:
            result = run_grounded(
                role="reflector",
                system=REFLECTOR_SYSTEM,
                user=user,
                output_format=schemas.ReflectionNote,
                prose_of=schemas.prose_of_reflection_note,
                pack=pack,
                settings=settings,
                budget=current_budget,
                model=model,
            )
        except BudgetExhausted as exc:
            current_budget = AgentBudget(cap_usd=exc.cap_usd, spent_usd=exc.spent_usd, calls=current_budget.calls)
            updated.append(entry)
            continue
        except AgentUnavailable:
            updated.append(entry)
            continue

        current_budget = result.budget
        updated.append(
            entry.model_copy(
                update={
                    "state": "resolved",
                    "raw_return_pct": _frac(symbol_return),
                    "alpha_return_pct": _frac(alpha),
                    "benchmark": "SPY",
                    "holding_days": _HOLDING_DAYS,
                    "reflection": result.value.lesson,
                }
            )
        )
        changed = True

    if changed:
        _write_all(path, updated)
    return current_budget


# ---------------------------------------------------------------------------
# What the portfolio manager reads
# ---------------------------------------------------------------------------


def lessons_for_prompt(symbol: str, *, settings: Settings, n_same: int = 5, n_cross: int = 3) -> str:
    """The portfolio manager's own memory block: the last `n_same` resolved decisions on `symbol` in
    full (decision and reflection both), then the last `n_cross` resolved decisions on other
    instruments with the reflection alone -- see `PORTFOLIO_MANAGER_SYSTEM` for why only this one
    stage ever reads this. Empty string when there is nothing resolved yet, same-symbol or cross.
    """
    upper = symbol.upper()
    resolved = [entry for entry in _read_all(memory_log_path(settings)) if entry.state == "resolved"]
    same = sorted((e for e in resolved if e.symbol == upper), key=lambda e: e.trade_date)[-n_same:]
    cross = sorted((e for e in resolved if e.symbol != upper), key=lambda e: e.trade_date)[-n_cross:]
    if not same and not cross:
        return ""

    lines: list[str] = []
    if same:
        lines.append(f"## This desk's past decisions on {upper}")
        for entry in same:
            lines.append(
                f"- {entry.trade_date.isoformat()}: rated {entry.rating}. Realized "
                f"{_display_pct(entry.raw_return_pct)}% ({_display_pct(entry.alpha_return_pct)}% vs "
                f"{entry.benchmark} over {entry.holding_days} days).\n"
                f"  Decision: {entry.decision_md.strip()}\n"
                f"  Reflection: {entry.reflection.strip()}"
            )
    if cross:
        lines.append("## This desk's past decisions on other instruments")
        for entry in cross:
            lines.append(
                f"- {entry.symbol} {entry.trade_date.isoformat()}: rated {entry.rating}, realized "
                f"{_display_pct(entry.alpha_return_pct)}% vs {entry.benchmark}. "
                f"Reflection: {entry.reflection.strip()}"
            )
    return "\n".join(lines)


def lessons_evidence_items(
    symbol: str, *, settings: Settings, n_same: int = 5, n_cross: int = 3
) -> tuple[EvidenceItem, ...]:
    """The figures inside `lessons_for_prompt`'s text, restated as `EvidenceItem`s so the grounding
    gate lets the portfolio manager cite them -- `PORTFOLIO_MANAGER_SYSTEM` says outright that "any
    figure inside a lesson is a measured outcome and may be cited as such; it is part of your
    evidence," which is meaningless unless those figures are actually in the `EvidencePack` the gate
    checks against. A second function rather than folding this into `lessons_for_prompt` because that
    function's return type (`str`, the wire-adjacent shape this module commits to) has nowhere to
    carry a list of evidence items; `app.tradingagents.pipeline` calls both, over the same selection of
    entries, to build the portfolio manager's stage.
    """
    upper = symbol.upper()
    resolved = [entry for entry in _read_all(memory_log_path(settings)) if entry.state == "resolved"]
    same = sorted((e for e in resolved if e.symbol == upper), key=lambda e: e.trade_date)[-n_same:]
    cross = sorted((e for e in resolved if e.symbol != upper), key=lambda e: e.trade_date)[-n_cross:]

    items: list[EvidenceItem] = []
    for index, entry in enumerate(same):
        as_of = entry.trade_date.isoformat()
        if entry.raw_return_pct is not None:
            items.append(
                EvidenceItem(
                    key=f"lesson_same_{index}_raw", label=f"{entry.symbol} realized return ({as_of})",
                    value=_display_pct(entry.raw_return_pct), unit="%", as_of=as_of, source="agentdesk-memory",
                )
            )
        if entry.alpha_return_pct is not None:
            items.append(
                EvidenceItem(
                    key=f"lesson_same_{index}_alpha",
                    label=f"{entry.symbol} return vs {entry.benchmark} ({as_of})",
                    value=_display_pct(entry.alpha_return_pct), unit="%", as_of=as_of, source="agentdesk-memory",
                )
            )
    for index, entry in enumerate(cross):
        as_of = entry.trade_date.isoformat()
        if entry.alpha_return_pct is not None:
            items.append(
                EvidenceItem(
                    key=f"lesson_cross_{index}_alpha",
                    label=f"{entry.symbol} return vs {entry.benchmark} ({as_of})",
                    value=_display_pct(entry.alpha_return_pct), unit="%", as_of=as_of, source="agentdesk-memory",
                )
            )
    return tuple(items)

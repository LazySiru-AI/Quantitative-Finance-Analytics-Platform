"""A model-driven paper-trading agent per influencer persona -- Phase 10 of the persona feature.

**What this is.** Every other part of the persona feature reports what an influencer said. The
`app.personas.paperbook` book goes one step further and *replays* their dated calls into a cash book.
This module goes the whole way: it seats each persona as a live paper trader that, at each decision
date, is handed a point-in-time market snapshot and its own consolidated trading method, and asked --
via one grounded model call, as that persona -- what to buy and sell. Orders fill at the next
session's open through the same `app.paper.paperbroker.PaperBroker` and mandate the reference desk
uses, so cash discipline, position caps and no-look-ahead fills are enforced centrally rather than
reinvented here.

**The honesty this module must carry, stated once here and rendered to every reader.** Two separate
caveats, do not conflate them:

1. *Market data is point-in-time; the persona's method is not.* Every price the decision sees is read
   through `app.paper.marketdata.AsOfMarket`, which cannot look past its `as_of` -- so the backtest
   never peeks at a future price. But the persona's *method* (its consolidated `methodology`/`regime`)
   is distilled from the influencer's whole corpus, including videos published after a given backtest
   week. There is no reliable per-note upload date to restrict knowledge point-in-time (the notes
   carry `published=None` and fall back to a recent ingest time), so this is a "how this persona's
   stated approach would have traded through history" lens, NOT a claim that they made these calls at
   these times. The frontend must say so.

2. *No measured edge.* The repository's own research (33 rounds + the persona point-in-time study)
   found no durable edge in these personas, and an explicit standing guardrail forbids seating a
   persona as a *validated* competitor in the tournament. This book is descriptive and experimental;
   nothing here is promoted, gated, or treated as skill, and none of it is investment advice.

See `docs/INFLUENCER-CONTRACT.md`, "Phase 10 -- persona paper trader (pinned)".
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import uuid
from collections.abc import Iterator, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final, cast

from pydantic import BaseModel, ConfigDict, Field

from app.agentdesk.grounding import numeric_tokens, run_grounded
from app.agentdesk.models import EvidenceItem, EvidencePack, EvidenceSection
from app.agents.models import DEFAULT_MODEL, AgentBudget, AgentRole
from app.config import Settings
from app.market.models import Interval
from app.market.store import ensure_series
from app.paper.mandate import default_mandate
from app.paper.marketdata import AsOfMarket, Session, SessionCalendar, UnpricedSymbol
from app.paper.paperbroker import Fill, Order, PaperBroker, Rejection, Side
from app.personas.ask import _render_profile
from app.personas.models import EpisodicNote, Persona, PersonaProfile, persona_dir
from app.personas.tickers import build_symbol_validator

__all__ = [
    "DEFAULT_INCEPTION",
    "MAX_UNIVERSE",
    "STARTING_CASH_USD",
    "TraderBook",
    "TraderStore",
    "advance_one_decision",
    "backfill_trader",
    "build_trader_book",
    "run_decision",
]

_log = logging.getLogger(__name__)

#: Where a weekly backtest starts by default when the owner has not set an inception. Matches the
#: persona replay book's own default so the two lenses line up on the same window.
DEFAULT_INCEPTION: Final[dt.date] = dt.date(2026, 1, 1)

#: Opening cash for every persona trader book. The same $100k the replay book and the workflow
#: autopilot seat use, so equity curves are comparable across the desk.
STARTING_CASH_USD: Final[Decimal] = Decimal("100000")

#: Hard cap on how many candidate symbols one decision is shown. Bounds the prompt and the cost; the
#: persona's own most-mentioned names plus whatever it currently holds, newest-mention first.
MAX_UNIVERSE: Final[int] = 12

_ROLE: AgentRole = "swarm_worker"
_BENCHMARK: Final[str] = "SPY"


# ---------------------------------------------------------------------------
# Read models (wire shapes) -- frozen, mirrored in TS by the API/frontend
# ---------------------------------------------------------------------------


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class TraderPosition(_Frozen):
    """One open position, marked to the latest available close."""

    symbol: str
    quantity: str          # whole shares, decimal string
    last_price: str        # decimal string
    market_value: str      # decimal string
    weight: float          # fraction of equity (0-1)


class TraderTradeRec(_Frozen):
    """One fill the trader booked, buy or sell, as executed at a session open."""

    decided_on: str        # ISO date the decision was made
    fill_date: str         # ISO date the order filled (next session open)
    symbol: str
    side: str              # "buy" | "sell"
    quantity: str          # decimal string
    price: str             # fill price, decimal string
    thesis: str            # the persona's stated reason, grounded


class TraderRejectionRec(_Frozen):
    """An order the broker refused (cash, caps, unpriceable), surfaced not hidden."""

    decided_on: str
    symbol: str
    side: str
    reason: str


class TraderDecisionRec(_Frozen):
    """One decision session: the persona's commentary plus what it tried and what stuck."""

    decided_on: str
    fill_date: str
    commentary: str
    degraded: bool
    cost_usd: str
    trades: tuple[TraderTradeRec, ...] = ()
    rejections: tuple[TraderRejectionRec, ...] = ()


class TraderEquityPoint(_Frozen):
    date: str
    equity: str            # decimal string


class TraderBook(_Frozen):
    """The whole persona trader book: identity, current holdings, curve, and the decision log."""

    persona: str
    display_name: str
    inception: str
    as_of: str | None
    starting_cash: str
    cash: str
    equity: str
    return_pct: str        # 0-1 fraction over starting cash
    benchmark: str = "SPY"
    benchmark_return_pct: str | None = None   # SPY buy-and-hold over the SAME window; None if unpriceable
    excess_pct: str | None = None             # return_pct - benchmark_return_pct; None when benchmark is
    positions: tuple[TraderPosition, ...] = ()
    equity_curve: tuple[TraderEquityPoint, ...] = ()
    decisions: tuple[TraderDecisionRec, ...] = ()   # newest first
    spent_usd: str = "0"
    warnings: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# The model's decision output
# ---------------------------------------------------------------------------


class _OrderDraft(_Frozen):
    symbol: str
    side: str = Field(description='"buy" or "sell"')
    notional_usd: float = Field(default=0.0, ge=0.0)
    thesis: str
    invalidation: str = ""


class _DecisionDraft(_Frozen):
    commentary: str
    orders: tuple[_OrderDraft, ...] = ()


# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------


def _persona_universe(
    notes: Sequence[EpisodicNote], *, held: Sequence[str], settings: Settings, cap: int = MAX_UNIVERSE
) -> tuple[str, ...]:
    """The candidate symbols a persona trades: its own most-recently-mentioned tickers plus whatever
    it currently holds (so a decision can always sell what it owns), validated against the instrument
    table and capped. Held names are kept even if they fall out of the recent-mention window -- a book
    must be able to exit a stale position. Newest mention first."""
    validator = build_symbol_validator(settings, allow_network=False)
    ordered: list[str] = []
    seen: set[str] = set()
    for sym in held:
        s = sym.upper()
        if s not in seen:
            seen.add(s)
            ordered.append(s)
    # notes are newest-first from the store; walk mentions in that order
    for note in notes:
        for m in note.mentions:
            s = m.symbol.upper()
            if s not in seen and validator(s):
                seen.add(s)
                ordered.append(s)
    # keep held names regardless; trim the rest to the cap
    held_set = {s.upper() for s in held}
    extras = [s for s in ordered if s not in held_set]
    kept = [*[s for s in ordered if s in held_set], *extras][:cap]
    return tuple(kept)


# ---------------------------------------------------------------------------
# Point-in-time snapshot + evidence
# ---------------------------------------------------------------------------


def _pct(a: Decimal, b: Decimal) -> str:
    if b == 0:
        return "n/a"
    return f"{(a / b - 1) * 100:.1f}%"


def _symbol_snapshot(market: AsOfMarket, symbol: str) -> tuple[str, dict[str, str]] | None:
    """One line of point-in-time context for `symbol` as of the decision date: last close and its
    distance from 20- and 50-session moving averages. `None` when the symbol cannot be priced at the
    as-of date (it is simply left out of the decision, never fabricated)."""
    try:
        frame = market.history(symbol, lookback_days=120)
    except (UnpricedSymbol, FileNotFoundError):
        return None
    if frame.empty:
        return None
    closes = [Decimal(str(c)) for c in frame["close"].tolist()]
    last = closes[-1]
    facts: dict[str, str] = {"close": f"{last:.2f}"}
    line = f"{symbol}: close {last:.2f}"
    if len(closes) >= 20:
        ma20 = sum(closes[-20:]) / Decimal(20)
        facts["ma20"] = f"{ma20:.2f}"
        line += f", 20d MA {ma20:.2f} ({_pct(last, ma20)})"
    if len(closes) >= 50:
        ma50 = sum(closes[-50:]) / Decimal(50)
        facts["ma50"] = f"{ma50:.2f}"
        line += f", 50d MA {ma50:.2f} ({_pct(last, ma50)})"
    return line, facts


def _numeric_items(text: str, *, prefix: str) -> tuple[EvidenceItem, ...]:
    tokens = sorted(set(numeric_tokens(text)))
    return tuple(EvidenceItem(key=f"{prefix}_{i}", label="market figure", value=t) for i, t in enumerate(tokens))


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------

_SYSTEM = """You are a paper-trading engine acting in the style of the market influencer {persona}, \
using ONLY their documented trading method (given below) to manage a ${cash_fmt} paper account. You \
are NOT {persona} and this is NOT investment advice -- you are a mechanical reconstruction of how their \
stated method would act on the market data shown.

DECISION. You are shown, as of {as_of}, a candidate list with each name's latest close and its \
distance from its 20- and 50-session moving averages, plus your current cash and open positions. \
Decide the orders their method implies THIS session: buys (with a dollar notional) and sells (to exit \
or trim a name you hold). Hold by simply not ordering. Size to their method's conviction, but you have \
finite cash and a position-count cap the broker enforces -- concentrate, do not spray. It is completely \
valid to do nothing (empty orders) when their method sees no setup.

GROUNDING. Every number in your commentary and each thesis must appear in the market data shown to you \
or be a straightforward move/percentage between two figures that do. Never invent a price, a target, or \
a level the data does not contain. Keep each thesis to one sentence in the persona's own idiom, tied to \
the method (e.g. the indicator or condition that fired).

Output the orders and a one- or two-sentence commentary. Only the fields the schema names."""


def _build_prompt(
    *, persona: str, as_of: dt.date, profile_text: str | None,
    snapshot_lines: Sequence[str], cash: Decimal, positions_text: str,
) -> str:
    parts = [f"Persona: {persona}", f"Decision date: {as_of.isoformat()}"]
    if profile_text:
        parts.append(f"--- {persona}'s trading method ---\n{profile_text}")
    else:
        parts.append(
            f"--- {persona}'s trading method ---\n(No consolidated method on record; trade "
            "conservatively and mostly hold.)"
        )
    parts.append("--- Candidates (as of the decision date) ---\n" + ("\n".join(snapshot_lines) or "(none priceable)"))
    parts.append(f"--- Your account ---\nCash: {cash:.2f} USD\nOpen positions:\n{positions_text or '(none)'}")
    parts.append(
        "Decide this session's orders per the method above. Buys need a dollar notional; sells name a "
        "held symbol. Ground every number in the candidate data. Empty orders = hold everything."
    )
    return "\n\n".join(parts)


def _decide(
    *, persona_slug: str, profile: PersonaProfile | None, as_of: dt.date,
    snapshots: Sequence[tuple[str, dict[str, str]]], cash: Decimal, positions_text: str,
    settings: Settings, budget: AgentBudget, model: str,
) -> tuple[_DecisionDraft, bool, Decimal]:
    """One grounded model call: what would the persona's method do this session? Returns the parsed
    draft, whether it was released degraded (grounding failed but we keep it, like every other persona
    stage), and the dollars spent. Never raises for a grounding failure."""
    profile_text = _render_profile(profile) if profile is not None else None
    snapshot_lines = [line for line, _ in snapshots]

    sections: list[EvidenceSection] = []
    snap_text = "\n".join(snapshot_lines)
    sections.append(
        EvidenceSection(
            title="Candidate market data",
            items=_numeric_items(snap_text, prefix="mkt"),
            text=snap_text,
        )
    )
    # account figures (cash) are also grounded so "I have 100000 in cash" is not rejected
    acct_text = f"Cash: {cash:.2f}\n{positions_text}"
    sections.append(
        EvidenceSection(title="Account", items=_numeric_items(acct_text, prefix="acct"), text=acct_text)
    )
    pack = EvidencePack(symbol="", sections=tuple(sections))

    system = _SYSTEM.format(persona=persona_slug, cash_fmt=f"{STARTING_CASH_USD:,.0f}", as_of=as_of.isoformat())
    user = _build_prompt(
        persona=persona_slug, as_of=as_of, profile_text=profile_text,
        snapshot_lines=snapshot_lines, cash=cash, positions_text=positions_text,
    )

    grounded = run_grounded(
        role=_ROLE, system=system, user=user, output_format=_DecisionDraft,
        prose_of=lambda d: d.commentary + "\n" + "\n".join(o.thesis for o in d.orders),
        pack=pack, settings=settings, budget=budget, model=model,
    )
    return grounded.value, grounded.verdict.degraded, grounded.budget.spent_usd


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _trader_dir(settings: Settings, slug: str) -> Path:
    return persona_dir(settings, slug) / "trader"


def _book_path(settings: Settings, slug: str) -> Path:
    return _trader_dir(settings, slug) / "book.json"


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.parent / f"{path.name}.{uuid.uuid4().hex}.tmp"
    staging.write_text(content, encoding="utf-8")
    os.replace(staging, path)


class TraderStore:
    """Reads and writes one persona's trader book JSON under `<vault>/influencers/<slug>/trader/`.

    Stateless beyond `settings`, like `VaultStore`. The stored blob keeps the broker's own
    `to_state()` (cash/positions/fills), the equity curve, the decision log, the inception, and the
    running model spend, so a decision run resumes exactly where the last one left off."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def load(self, slug: str) -> dict[str, Any] | None:
        path = _book_path(self._settings, slug)
        if not path.is_file():
            return None
        try:
            import json

            return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            _log.warning("trader store: unreadable book for %r: %s", slug, exc)
            return None

    def save(self, slug: str, blob: dict[str, Any]) -> None:
        import json

        _write_atomic(_book_path(self._settings, slug), json.dumps(blob, indent=2))

    def delete(self, slug: str) -> bool:
        path = _book_path(self._settings, slug)
        if not path.is_file():
            return False
        path.unlink()
        return True


def _fresh_blob(inception: dt.date) -> dict[str, Any]:
    return {
        "inception": inception.isoformat(),
        "broker_state": None,     # set on first decision
        "equity_curve": [],
        "decisions": [],
        "spent_usd": "0",
        "last_decided": None,
    }


# ---------------------------------------------------------------------------
# One decision session
# ---------------------------------------------------------------------------


def run_decision(
    *, persona: Persona, profile: PersonaProfile | None, notes: Sequence[EpisodicNote],
    decided_on: dt.date, fill_date: dt.date, session_index: int,
    broker: PaperBroker, settings: Settings, budget: AgentBudget, model: str = DEFAULT_MODEL,
) -> TraderDecisionRec:
    """Run one decision: build the point-in-time market at `decided_on`, ask the persona's method for
    orders, submit them to fill at `fill_date`'s open through `broker`, and return the record. Mutates
    `broker` in place. Point-in-time is enforced by `AsOfMarket(as_of=decided_on)` -- the decision
    cannot see any price after `decided_on`; the fill is at `fill_date`'s open, the one look-ahead the
    broker itself owns."""
    decision_market = AsOfMarket(as_of=decided_on, settings=settings)

    held = sorted(s for s, q in broker.positions.items() if q != 0)
    universe = _persona_universe(notes, held=held, settings=settings)

    snapshots: list[tuple[str, dict[str, str]]] = []
    for sym in universe:
        snap = _symbol_snapshot(decision_market, sym)
        if snap is not None:
            snapshots.append(snap)

    # current positions rendered for the prompt
    pos_lines: list[str] = []
    for sym in held:
        try:
            price = decision_market.close(sym)
            pos_lines.append(f"{sym}: {broker.positions[sym]} shares @ ~{price:.2f}")
        except (UnpricedSymbol, FileNotFoundError):
            pos_lines.append(f"{sym}: {broker.positions[sym]} shares (unpriced)")
    positions_text = "\n".join(pos_lines)

    draft, degraded, spent = _decide(
        persona_slug=persona.slug, profile=profile, as_of=decided_on, snapshots=snapshots,
        cash=broker.cash, positions_text=positions_text, settings=settings, budget=budget, model=model,
    )

    trades: list[TraderTradeRec] = []
    rejections: list[TraderRejectionRec] = []

    for od in draft.orders:
        symbol = od.symbol.strip().upper()
        side = od.side.strip().lower()
        if side not in ("buy", "sell") or not symbol:
            continue
        # size to whole shares off the decision close
        try:
            decision_close = decision_market.close(symbol)
        except (UnpricedSymbol, FileNotFoundError):
            rejections.append(TraderRejectionRec(
                decided_on=decided_on.isoformat(), symbol=symbol, side=side, reason="unpriceable"))
            continue
        if side == "buy":
            notional = Decimal(str(od.notional_usd or 0))
            qty = (notional / decision_close).to_integral_value(rounding="ROUND_DOWN")
            if qty <= 0:
                rejections.append(TraderRejectionRec(
                    decided_on=decided_on.isoformat(), symbol=symbol, side=side, reason="zero_quantity"))
                continue
        else:
            qty = broker.positions.get(symbol, Decimal(0))
            if qty <= 0:
                rejections.append(TraderRejectionRec(
                    decided_on=decided_on.isoformat(), symbol=symbol, side=side, reason="not_held"))
                continue
        order = Order(
            order_id=uuid.uuid4().hex, session=session_index, decided_on=decided_on, symbol=symbol,
            side=cast("Side", side), quantity=Decimal(qty), thesis=(od.thesis or "method signal")[:400],
            invalidation=(od.invalidation or "method invalidation")[:400],
        )
        result = broker.submit(order, market=decision_market, fill_date=fill_date)
        if isinstance(result, Fill):
            trades.append(TraderTradeRec(
                decided_on=decided_on.isoformat(), fill_date=fill_date.isoformat(), symbol=symbol,
                side=side, quantity=format(result.quantity, "f"), price=format(result.price, "f"),
                thesis=order.thesis))
        elif isinstance(result, Rejection):
            rejections.append(TraderRejectionRec(
                decided_on=decided_on.isoformat(), symbol=symbol, side=side, reason=result.reason))

    return TraderDecisionRec(
        decided_on=decided_on.isoformat(), fill_date=fill_date.isoformat(),
        commentary=draft.commentary, degraded=degraded, cost_usd=format(spent, "f"),
        trades=tuple(trades), rejections=tuple(rejections),
    )


# ---------------------------------------------------------------------------
# Weekly backfill / advance
# ---------------------------------------------------------------------------


def _weekly_decision_sessions(calendar: SessionCalendar) -> Iterator[Session]:
    """One decision session per ISO week: the first session of each week in the calendar. Weekly, not
    daily, keeps the backtest's model cost bounded (roughly one call per persona per week) while still
    reacting to trend changes at a swing-trading cadence."""
    seen: set[tuple[int, int]] = set()
    for session in calendar:
        key = session.date.isocalendar()[:2]
        if key not in seen:
            seen.add(key)
            yield session


def backfill_trader(
    *, persona: Persona, profile: PersonaProfile | None, notes: Sequence[EpisodicNote],
    inception: dt.date, settings: Settings, model: str = DEFAULT_MODEL,
    per_decision_cap_usd: Decimal, daily_cap_usd: Decimal, today: dt.date | None = None,
) -> tuple[TraderBook, dict[str, Any]]:
    """Walk weekly decision sessions from `inception` to today, running one grounded decision each and
    marking the book forward, then return the built book AND the persistable on-disk blob. Point-in-time
    throughout: session N decides on data through its own `decided_on` and fills at its `date` open.
    Stops early (returning what it has) if the aggregate daily spend cap would be crossed -- a partial
    book is honest; a book built by ignoring the cap is not."""
    from app.agents.spend import LEDGER

    today = today or dt.date.today()
    broker = PaperBroker(default_mandate(starting_cash=STARTING_CASH_USD))
    try:
        calendar = SessionCalendar(start=inception, end=today, settings=settings, benchmark=_BENCHMARK)
    except (UnpricedSymbol, ValueError) as exc:
        _log.warning("trader backfill %s: no sessions (%s)", persona.slug, exc)
        book = _empty_book(persona, inception, warning=f"no market sessions since {inception}: {exc}")
        return book, _fresh_blob(inception)

    decisions: list[TraderDecisionRec] = []
    curve: list[TraderEquityPoint] = []
    spent_total = Decimal(0)
    warnings: list[str] = []

    for idx, session in enumerate(_weekly_decision_sessions(calendar), start=1):
        try:
            LEDGER.check(daily_cap_usd)
        except Exception as exc:  # SpendCapExceeded -- stop, keep what we have
            warnings.append(f"stopped at {session.decided_on}: daily spend cap reached ({exc})")
            break
        rec = run_decision(
            persona=persona, profile=profile, notes=notes,
            decided_on=session.decided_on, fill_date=session.date, session_index=idx,
            broker=broker, settings=settings, budget=AgentBudget(cap_usd=per_decision_cap_usd), model=model,
        )
        decisions.append(rec)
        spent_total += Decimal(rec.cost_usd)
        mark_market = AsOfMarket(as_of=session.date, settings=settings)
        curve.append(TraderEquityPoint(date=session.date.isoformat(),
                                       equity=format(broker.equity(mark_market), "f")))

    book = _assemble_book(
        persona=persona, inception=inception, broker=broker, decisions=decisions, curve=curve,
        spent_total=spent_total, warnings=warnings, as_of=today, settings=settings,
    )
    blob = blob_from_backfill(book, broker.to_state(), inception)
    return book, blob


def advance_one_decision(
    *, persona: Persona, profile: PersonaProfile | None, notes: Sequence[EpisodicNote],
    blob: dict[str, Any] | None, settings: Settings, model: str = DEFAULT_MODEL,
    per_decision_cap_usd: Decimal, daily_cap_usd: Decimal, today: dt.date | None = None,
) -> tuple[TraderBook, dict[str, Any]]:
    """Run the ONE next undone weekly decision on top of an existing book (the on-demand "trade this
    week now" step, and the unit the daemon advances by). Resumes from `blob`: builds the broker from
    its stored state, finds the first weekly decision session whose `decided_on` is newer than the last
    one already recorded, runs it, and returns the updated book + blob. When the book is already caught
    up (no newer weekly session exists yet), returns it unchanged with a warning rather than raising.
    `LEDGER.check(daily_cap_usd)` gates the call, exactly as the backfill does."""
    from app.agents.spend import LEDGER

    today = today or dt.date.today()
    if blob is None:
        blob = _fresh_blob(DEFAULT_INCEPTION)
    inception = dt.date.fromisoformat(blob.get("inception") or DEFAULT_INCEPTION.isoformat())

    if blob.get("broker_state"):
        broker = PaperBroker.from_state(default_mandate(starting_cash=STARTING_CASH_USD), blob["broker_state"])
    else:
        broker = PaperBroker(default_mandate(starting_cash=STARTING_CASH_USD))

    stored: list[TraderDecisionRec] = [_rec_from_json(d) for d in blob.get("decisions", [])]
    curve: list[TraderEquityPoint] = [
        TraderEquityPoint(date=p["date"], equity=p["equity"]) for p in blob.get("equity_curve", [])
    ]
    last_decided = blob.get("last_decided")
    last_date = dt.date.fromisoformat(last_decided) if last_decided else None
    try:
        spent_total = Decimal(blob.get("spent_usd", "0"))
    except InvalidOperation:
        spent_total = Decimal(0)

    try:
        calendar = SessionCalendar(start=inception, end=today, settings=settings, benchmark=_BENCHMARK)
    except (UnpricedSymbol, ValueError) as exc:
        book = build_trader_book(persona=persona, blob=blob, settings=settings, as_of=today)
        return book.model_copy(update={"warnings": (*book.warnings, f"no market sessions: {exc}")}), blob

    nxt: Session | None = None
    for session in _weekly_decision_sessions(calendar):
        if last_date is None or session.decided_on > last_date:
            nxt = session
            break
    if nxt is None:
        book = build_trader_book(persona=persona, blob=blob, settings=settings, as_of=today)
        return book.model_copy(update={"warnings": (*book.warnings, "already caught up: no new weekly session")}), blob

    LEDGER.check(daily_cap_usd)
    rec = run_decision(
        persona=persona, profile=profile, notes=notes, decided_on=nxt.decided_on, fill_date=nxt.date,
        session_index=len(stored) + 1, broker=broker, settings=settings,
        budget=AgentBudget(cap_usd=per_decision_cap_usd), model=model,
    )
    stored.append(rec)
    mark_market = AsOfMarket(as_of=nxt.date, settings=settings)
    curve.append(TraderEquityPoint(date=nxt.date.isoformat(), equity=format(broker.equity(mark_market), "f")))
    spent_total += Decimal(rec.cost_usd)

    book = _assemble_book(
        persona=persona, inception=inception, broker=broker, decisions=stored, curve=curve,
        spent_total=spent_total, warnings=(), as_of=today, settings=settings,
    )
    new_blob = {
        "inception": inception.isoformat(),
        "broker_state": broker.to_state(),
        "equity_curve": [{"date": p.date, "equity": p.equity} for p in curve],
        "decisions": [_rec_to_json(r) for r in stored],
        "spent_usd": format(spent_total, "f"),
        "last_decided": nxt.decided_on.isoformat(),
    }
    return book, new_blob


# ---------------------------------------------------------------------------
# Building the read model
# ---------------------------------------------------------------------------


def _benchmark_return(inception: dt.date, as_of: dt.date, settings: Settings) -> Decimal | None:
    """SPY buy-and-hold return (0-1 fraction) over the book's own window: the first daily close on or
    after `inception` to the last close on or before `as_of`. The honest yardstick for "did this
    persona's method beat just holding the market" -- SPY is the fixed benchmark this repo uses
    everywhere (see `app.personas.backtest`). `None` (never a fabricated 0) when the store cannot
    price the window, so the UI can distinguish "no benchmark" from "flat benchmark"."""
    try:
        series = ensure_series(_BENCHMARK, Interval.DAY, start=inception, end=as_of, settings=settings)
    except Exception:
        return None
    bars = sorted((b for b in series.bars if b.ts.date() <= as_of), key=lambda b: b.ts)
    entry = next((b for b in bars if b.ts.date() >= inception), None)
    if entry is None or not bars:
        return None
    last = bars[-1]
    first_close = Decimal(str(entry.close))
    if first_close == 0:
        return None
    return Decimal(str(last.close)) / first_close - 1


def _empty_book(persona: Persona, inception: dt.date, *, warning: str) -> TraderBook:
    return TraderBook(
        persona=persona.slug, display_name=persona.display_name, inception=inception.isoformat(),
        as_of=None, starting_cash=format(STARTING_CASH_USD, "f"), cash=format(STARTING_CASH_USD, "f"),
        equity=format(STARTING_CASH_USD, "f"), return_pct="0", warnings=(warning,),
    )


def _assemble_book(
    *, persona: Persona, inception: dt.date, broker: PaperBroker,
    decisions: Sequence[TraderDecisionRec], curve: Sequence[TraderEquityPoint],
    spent_total: Decimal, warnings: Sequence[str], as_of: dt.date, settings: Settings,
) -> TraderBook:
    mark_market = AsOfMarket(as_of=as_of, settings=settings)
    total_value, marks = broker.mark(mark_market)
    equity = broker.cash + total_value
    positions: list[TraderPosition] = []
    for sym in sorted(s for s, q in broker.positions.items() if q != 0):
        qty = broker.positions[sym]
        price = marks.get(sym)
        if price is None:
            warnings = [*warnings, f"{sym}: no market data at mark"]
            continue
        mv = price * qty
        positions.append(TraderPosition(
            symbol=sym, quantity=format(qty, "f"), last_price=format(price, "f"),
            market_value=format(mv, "f"), weight=float(mv / equity) if equity else 0.0))
    ret = (equity / STARTING_CASH_USD - 1) if STARTING_CASH_USD else Decimal(0)
    bench = _benchmark_return(inception, as_of, settings)
    return TraderBook(
        persona=persona.slug, display_name=persona.display_name, inception=inception.isoformat(),
        as_of=as_of.isoformat(), starting_cash=format(STARTING_CASH_USD, "f"),
        cash=format(broker.cash, "f"), equity=format(equity, "f"), return_pct=format(ret, "f"),
        benchmark=_BENCHMARK,
        benchmark_return_pct=format(bench, "f") if bench is not None else None,
        excess_pct=format(ret - bench, "f") if bench is not None else None,
        positions=tuple(positions), equity_curve=tuple(curve),
        decisions=tuple(reversed(decisions)), spent_usd=format(spent_total, "f"),
        warnings=tuple(warnings),
    )


def build_trader_book(
    *, persona: Persona, blob: dict[str, Any] | None, settings: Settings, as_of: dt.date | None = None,
) -> TraderBook:
    """Reconstruct the read model from a stored blob without running the model. `None` blob (never
    traded) yields an empty book at the default inception."""
    as_of = as_of or dt.date.today()
    if blob is None:
        return _empty_book(persona, DEFAULT_INCEPTION, warning="not traded yet")
    try:
        inception = dt.date.fromisoformat(blob["inception"])
    except (KeyError, ValueError):
        inception = DEFAULT_INCEPTION
    broker = PaperBroker(default_mandate(starting_cash=STARTING_CASH_USD))
    if blob.get("broker_state"):
        broker = PaperBroker.from_state(default_mandate(starting_cash=STARTING_CASH_USD), blob["broker_state"])
    decisions = tuple(_rec_from_json(d) for d in blob.get("decisions", []))
    curve = tuple(TraderEquityPoint(date=p["date"], equity=p["equity"]) for p in blob.get("equity_curve", []))
    try:
        spent = Decimal(blob.get("spent_usd", "0"))
    except InvalidOperation:
        spent = Decimal(0)
    # decisions in the blob are stored oldest-first; _assemble_book reverses to newest-first
    return _assemble_book(
        persona=persona, inception=inception, broker=broker, decisions=list(decisions),
        curve=curve, spent_total=spent, warnings=(), as_of=as_of, settings=settings,
    )


def _rec_from_json(d: dict[str, Any]) -> TraderDecisionRec:
    return TraderDecisionRec(
        decided_on=d["decided_on"], fill_date=d["fill_date"], commentary=d.get("commentary", ""),
        degraded=bool(d.get("degraded", False)), cost_usd=d.get("cost_usd", "0"),
        trades=tuple(TraderTradeRec(**t) for t in d.get("trades", [])),
        rejections=tuple(TraderRejectionRec(**r) for r in d.get("rejections", [])),
    )


def blob_from_backfill(book: TraderBook, broker_state: dict[str, Any], inception: dt.date) -> dict[str, Any]:
    """Serialise a freshly-backfilled book back to the on-disk blob shape (decisions oldest-first)."""
    return {
        "inception": inception.isoformat(),
        "broker_state": broker_state,
        "equity_curve": [{"date": p.date, "equity": p.equity} for p in book.equity_curve],
        "decisions": [_rec_to_json(r) for r in reversed(book.decisions)],  # store oldest-first
        "spent_usd": book.spent_usd,
        "last_decided": book.decisions[0].decided_on if book.decisions else None,
    }


def _rec_to_json(r: TraderDecisionRec) -> dict[str, Any]:
    return {
        "decided_on": r.decided_on, "fill_date": r.fill_date, "commentary": r.commentary,
        "degraded": r.degraded, "cost_usd": r.cost_usd,
        "trades": [t.model_dump() for t in r.trades],
        "rejections": [rj.model_dump() for rj in r.rejections],
    }

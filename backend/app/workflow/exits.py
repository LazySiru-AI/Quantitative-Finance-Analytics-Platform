"""Mechanical exits for the workflow's paper books.

**Why this exists, and why it is not in the pipeline.** `app.workflow.pipeline` decides *entries* --
which candidates to buy -- and that decision is the expensive, model-driven part the four-arm study
is built to measure. Closing a position is not that. A workflow position is closed by the same
mechanical rule the strategy card already carries: its stop, its take-profit, its hold cap, or its
`exit` expression, in exactly the precedence `app.tournament.runner` applies to a backtest
(`_decide_exit`: stop, then target, then time, then rule). No research, no model call, no judgement.
So exits live here, evaluated once a day off stored bars, and are staged the same way entries are --
decided against the latest stored close, filled at the next session's open.

**This closes the gap the Autopilot seat's own callout names.** Until this module existed the
workflow staged buys and never sold, so every book held forever and the seat's card-level stop and
target rules were inert (see `app.paperdesk.models.AutopilotDescription.exits`). A book that only ever
buys has a return that is mostly its universe's beta; letting the card's own exits fire is what makes
the seat trade the *strategy*, not just hold it.

**The design decision this encodes, stated because it was an open choice.** A workflow order's
entry is a model judgement; its exit is a mechanical rule. Pairing model-selected entries with
rule-based exits is deliberate -- it is the "combination of strategy" the desk is named for, and it
matches the programme's own finding, recorded across dozens of rounds, that whatever asymmetry a
strategy has "comes from exits and risk control, not from better ranking" (`DISCOVERY.md`). An exit
that also required a model call would double the study's cost while measuring the same gate twice.

Everything mechanical here is copied in behaviour, not imported, from `app.tournament.runner` -- the
same "duplicated small helper over a cross-package private import" choice `app.workflow.replay`,
`.pipeline` and `.regime` each already make for their own card loaders, and for the same reason: a
one-line rglob cannot cause an import cycle, and `app.workflow.book` (which this module builds on)
must stay importable without pulling the tournament runner in behind it.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.config import Settings
from app.market.models import Interval
from app.paper.marketdata import AsOfMarket, SessionCalendar, UnpricedSymbol
from app.rules import evaluate as rule_evaluate
from app.rules import grammar
from app.rules.nodes import BoolExpr
from app.tournament.models import StrategyCard
from app.workflow import book as book_mod
from app.workflow.book_models import BookState, OrderPlan

logger = logging.getLogger(__name__)

_CENTS = Decimal("0.01")
_BENCHMARK = "SPY"


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _load_card(agent_id: str, *, settings: Settings) -> StrategyCard | None:
    """The selected card, or `None` when `agent_id` names no `StrategyCard`.

    A local rglob rather than a shared import -- see this module's docstring. `None` covers three
    ordinary cases that must all mean "stage no exits" rather than raise: an empty `current_card_id`
    (a book seeded but never traded), an id that resolves to a ladder or allocation card (which have
    no per-symbol exit rule and are never seated on a workflow book anyway), and a genuinely missing
    file. None of those is an error the daily step should fail on.
    """
    if not agent_id:
        return None
    for path in sorted(settings.library_dir.rglob(f"{agent_id}.json")):
        try:
            return StrategyCard.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
    return None


@dataclass(frozen=True, slots=True)
class ExitDecision:
    """One held symbol's exit verdict this session -- the audit trail behind a staged sell, or behind
    a position deliberately left open. `reason` is `"stop"`, `"target"`, `"time"`, `"rule"` (the four
    `app.tournament.runner` precedence outcomes), `"hold"` (no exit fired), or `"unpriceable"` (the
    close needed to decide could not be read, so no verdict was possible and the position was left
    untouched)."""

    symbol: str
    reason: str
    quantity: Decimal
    """Shares held, and -- when `reason` is one of the four firing reasons -- the shares this exit
    sells. Zero only when the lot itself is empty, which `held_lots` never returns."""


def _bracket_reason(
    card: StrategyCard, symbol: str, entry_price: Decimal, bars_held: int, last_close: Decimal | None
) -> str | None:
    """`"stop"`, `"target"`, `"time"`, or `None`, in that precedence -- a behaviour copy of
    `app.tournament.runner._bracket_reason`, checked against the latest stored close the same way the
    runner checks against the previous close (both are "the last price a decision could see"). A
    `last_close` of `None` means the symbol was unpriceable this session, in which case the price
    brackets cannot be evaluated and only the time stop, which needs no price, still can."""
    if last_close is not None:
        if card.stop_loss_pct is not None and last_close <= entry_price * (
            Decimal(1) - card.stop_loss_pct
        ):
            return "stop"
        if card.take_profit_pct is not None and last_close >= entry_price * (
            Decimal(1) + card.take_profit_pct
        ):
            return "target"
    if card.max_hold_days is not None and bars_held >= card.max_hold_days:
        return "time"
    return None


def _exit_rule_fires(tree: BoolExpr, symbol: str, *, market: AsOfMarket) -> bool:
    """Whether the card's `exit` expression is true for `symbol` as of `market`'s own session --
    evaluated exactly as `app.workflow.pipeline._scan_candidates` evaluates the *entry* rule: the
    tree against the symbol's stored bars up to `as_of`, taking the last value, `NaN` read as
    `False`. An unpriceable or unparseable case is a quiet `False`, never a raise."""
    bars = market.history(symbol, lookback_days=None)
    if bars.empty:
        return False
    try:
        signal = rule_evaluate.evaluate(tree, bars, interval=Interval.DAY)
    except ValueError:
        return False
    return bool(signal.fillna(False).iloc[-1])


def _bars_held(entry_date: dt.date, today: dt.date, sessions: tuple[dt.date, ...]) -> int:
    """Trading sessions elapsed since `entry_date`, up to and including `today` -- the count of
    session dates strictly after `entry_date` and at or before `today`. Matches
    `app.workflow.replay._bars_held` and the Autopilot seat's own `_bars_between`, so a position's
    age reads the same on the panel and in the exit check."""
    return sum(1 for date in sessions if entry_date < date <= today)


def plan_exits(
    book: BookState,
    *,
    settings: Settings,
    today: dt.date,
    allow_fractional: bool,
) -> tuple[list[OrderPlan], list[ExitDecision]]:
    """Sell plans for every held lot whose exit fires as of `today`, plus a decision per held lot.

    Returns `([], [])` for a book with nothing held, a book whose `current_card_id` names no
    `StrategyCard`, or a card with no exit rule of any kind -- each an ordinary "nothing to close",
    never an error. Reads only stored bars; stages nothing and never touches the network.

    A firing lot is sold **whole**. `OrderPlan` carries a dollar `notional`, not a share count (see
    that model's docstring), and `execute_pending` re-derives the count from the decision-date close
    -- so to make that round-trip land on the exact held quantity, a whole-share book's sell notional
    is sized half a share high: `floor((qty + 0.5) * close / close) == qty` exactly, and the broker's
    own `_check_sell` would reject anything larger than `qty` as a short, so the buffer can never
    oversell. A fractional book is sized at `qty * close` and accepts up to a microshare of dust,
    which the default paper mandate (whole shares) never reaches.
    """
    held = book_mod.held_lots(book)
    if not held:
        return [], []

    card = _load_card(book.current_card_id, settings=settings)
    if card is None:
        logger.info(
            "workflow exits: book %s/%s names card %r, which resolves to no StrategyCard; "
            "no exits evaluated",
            book.arm,
            book.universe_source,
            book.current_card_id,
        )
        return [], []

    # Symbols that already have a sell working. A stop that stays triggered across several sessions,
    # or a sell that could not fill yet (its next-open bar not stored), would otherwise re-stage a
    # fresh sell every single day -- stacking duplicate pending orders for one position, all but the
    # first of which the broker then rejects as a short once the bar arrives. One working sell per
    # symbol is enough; the rest are re-evaluated only once it has resolved.
    pending_sell_symbols = {
        order.symbol for order in book.orders if order.side == "sell" and order.status == "pending"
    }

    market = AsOfMarket(as_of=today, settings=settings)
    exit_tree: BoolExpr | None = None
    if card.exit.strip():
        try:
            exit_tree = grammar.parse(card.exit)
        except ValueError:
            logger.warning(
                "workflow exits: card %s exit rule %r is unparseable; brackets and time stop still "
                "apply, the rule does not",
                card.agent_id,
                card.exit,
            )

    # One session list, built once, covering the whole book's history so every lot's age can be
    # counted against it. `earliest` is the oldest acquisition on the book (or `today`, for the
    # degenerate all-same-day case), so a `SessionCalendar` from there to `today` contains every
    # session any held lot could have been open through.
    earliest = min((lot.acquired_date for lot in held), default=today)
    try:
        sessions = tuple(
            s.date
            for s in SessionCalendar(start=earliest, end=today, settings=settings, benchmark=_BENCHMARK)
        )
    except Exception:
        # `SessionCalendar` raises when the benchmark has no stored bar across the window. Everything
        # else in this module records a problem and moves on rather than raising, and a session list
        # that cannot be built must not be the one exception -- a book with held positions would then
        # take the whole daily step down over a missing SPY bar.
        #
        # Degrades to an empty session list, which disables **only** the time stop: `_bars_held`
        # returns 0, so `max_hold_days` cannot trip. The stop, the take-profit and the exit rule all
        # read prices directly and are unaffected, so a position still closes on every condition that
        # does not depend on counting sessions. Losing the time stop for a session is a far smaller
        # harm than losing every exit on the book, which is the alternative.
        logger.warning(
            "workflow exits: no session calendar for %s..%s on %s; the time stop is skipped this "
            "session, price-based exits still apply",
            earliest.isoformat(),
            today.isoformat(),
            _BENCHMARK,
            exc_info=True,
        )
        sessions = ()

    plans: list[OrderPlan] = []
    decisions: list[ExitDecision] = []
    for lot in held:
        if lot.symbol in pending_sell_symbols:
            # A sell is already working for this symbol -- don't stack a second. Recorded as "hold"
            # because from this session's point of view the exit is already handled, not newly
            # declined.
            decisions.append(ExitDecision(symbol=lot.symbol, reason="hold", quantity=lot.quantity))
            continue
        entry_price = lot.cost_basis / lot.quantity if lot.quantity != 0 else Decimal(0)
        try:
            last_close: Decimal | None = market.close(lot.symbol)
        except UnpricedSymbol:
            last_close = None

        bars_held = _bars_held(lot.acquired_date, today, sessions)
        reason = _bracket_reason(card, lot.symbol, entry_price, bars_held, last_close)
        if reason is None and exit_tree is not None and _exit_rule_fires(exit_tree, lot.symbol, market=market):
            reason = "rule"

        if reason is None:
            decisions.append(ExitDecision(symbol=lot.symbol, reason="hold", quantity=lot.quantity))
            continue
        if last_close is None:
            # A firing time stop with no priceable close: the fill itself would have nothing to size
            # against, so the sell cannot be staged this session. Left open, recorded, retried next
            # session -- never dropped, the same discipline `execute_pending` applies to a due order
            # it cannot price.
            decisions.append(ExitDecision(symbol=lot.symbol, reason="unpriceable", quantity=lot.quantity))
            continue

        if allow_fractional:
            notional = _money(lot.quantity * last_close)
        else:
            notional = _money((lot.quantity + Decimal("0.5")) * last_close)

        plans.append(
            OrderPlan(
                agent_card_id=card.agent_id,
                symbol=lot.symbol,
                side="sell",
                notional=notional,
                thesis=card.thesis,
                invalidation=card.falsification or "",
                stop_level=None,
                regime="",
                conviction=None,
                evidence=(f"exit: {reason}",),
            )
        )
        decisions.append(ExitDecision(symbol=lot.symbol, reason=reason, quantity=lot.quantity))

    return plans, decisions


def stage_due_exits(
    book: BookState,
    *,
    settings: Settings,
    today: dt.date,
    allow_fractional: bool,
) -> tuple[BookState, list[ExitDecision]]:
    """Evaluate exits for `book` as of `today` and stage the resulting sells, returning the new book
    and the per-lot decisions. A no-op that returns `book` unchanged when nothing fires.

    Staged with `decision_date=today` and `fill_date=today+1` -- the identical "decide on the close,
    fill at the next open" pairing the entry path uses, so an exit staged today is filled by the next
    day's `execute_pending`, one session after it was decided, exactly as a buy is. The synthetic
    `run_id` (`exit-<date>`) traces every sell back to the daily step that staged it, distinct from
    the `DeskRun` ids the pipeline's own buys carry.
    """
    plans, decisions = plan_exits(
        book, settings=settings, today=today, allow_fractional=allow_fractional
    )
    if not plans:
        return book, decisions
    staged = book_mod.stage_orders(
        book,
        plans,
        decision_date=today,
        fill_date=today + dt.timedelta(days=1),
        run_id=f"exit-{today.isoformat()}",
    )
    return staged, decisions

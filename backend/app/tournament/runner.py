"""Drives one analyst's :class:`~app.tournament.models.StrategyCard` through :class:`PaperBroker`.

**Nothing here reimplements a rule engine, a metrics engine or a broker.** The rule DSL is parsed by
:mod:`app.rules.grammar` and evaluated by :mod:`app.rules.evaluate`; return/vol/Sharpe/Sortino/
max-drawdown/exposure/win-rate come from :func:`app.backtest.metrics.compute`, the single
implementation this repo has already been burned by duplicating once; cash, settlement,
concentration and whole-share rules are enforced by :class:`uat.harness.paperbroker.PaperBroker`.
This module's own job is the smallest possible thing that is not already one of those: turn one
card's rules into a sequence of :class:`~uat.harness.paperbroker.Order` objects, submit them in
session order, and translate what came back into an :class:`~app.tournament.models.AgentResult`.

**Exit precedence, when several conditions would close a position on the same session: stop, then
target, then the time stop, then the discretionary rule.** All four are checked every session a
position is open (see :func:`_decide_exit`), and only the first to fire is acted on. Stop before
target because a stop is capital preservation and a target is upside -- if both a decliner past its
stop and (implausibly, from the same single close) a riser past its target could fire at once, the
downside case is the one that must not be silently overridden. Both brackets before the time stop
because they are the analyst's explicit, pre-declared risk plan; letting a calendar deadline pre-empt
a stop that has already fired would record a stopped-out loss as a boring timeout. The time stop
before the discretionary rule exit for the same reason :mod:`app.backtest.strategy` orders its own
checks this way (stop, then max-holding-bars, then the exit signal): a mechanical, pre-committed rule
outranks a discretionary condition evaluated after the fact, because a strategy whose rule exit is
free to override its own stated risk controls has not stated risk controls, it has stated
suggestions.

**Bracket timing: a stop or target is evaluated against the *previous* close, and fills the same way
every other order does -- next session's open.** ``card.stop_loss_pct`` and ``card.take_profit_pct``
are compared against ``market.close(symbol)`` inside the decision-session ``AsOfMarket`` (i.e.
``session.decided_on``'s close, the last price the decision may see), never against ``session.date``'s
own low or high. This is deliberately the conservative choice, not the common one:
:mod:`app.backtest.strategy` (a full-history study, not a point-in-time decision) checks its stop
against the *current* bar's low, which fills a stop earlier and tighter -- an intraday breach the
decision-maker could not have observed here, since the ``AsOfMarket`` for a decision is constructed at
``as_of=session.decided_on``, strictly before ``session.date`` (see :func:`_require_decision_market`).
Using the low/high would need seeing a bar that has not happened yet as of the decision; using the
close one bar back does not. The cost of the conservative choice is real: a symbol that gaps through a
stop intraday and recovers by the next close will not be stopped out here at all until (if ever) a
later close confirms the breach, so this module's stop-outs land later and at worse prices than a
same-day intraday check would, and its equity curve is accordingly a little smoother on the way down
than a strategy that could see the low would report. That is the price of not leaking a bar the
decision-maker never had.

**Position sizing is a fraction of *starting* equity, not current equity.** ``card.position_pct *
mandate.starting_cash`` is computed once and reused for every entry over the whole run -- sizing off
the equity as it stood on any given day would let a strategy quietly re-lever after a drawdown or
delever after a gain, neither of which is what "``position_pct`` per position" as written on the card
means.

**No pyramiding, one lot per symbol.** An entry signal for a symbol already held is never evaluated
(see the ``if symbol in open_lots: continue`` guard in :func:`run_card`) -- the same convention
:mod:`app.backtest.strategy` uses, for the same reason: a card that wanted position-scaling would have
to say so, and none of these do.

**Defence in depth against the one bug this design cannot rule out by construction.**
:class:`~uat.harness.marketdata.AsOfMarket` already makes it structurally impossible for a *held*
instance to see past its own ``as_of`` -- every read derives its window from the instance, not from
the caller. What it cannot prevent is a caller building the *wrong* instance and handing it to a
decision function by mistake -- e.g. threading the end-of-session marking market (``as_of=session.date``)
into the entry-signal check instead of the decision market (``as_of=session.decided_on``).
:func:`_require_decision_market` is a loud, immediate assertion against exactly that mistake, called at
the top of every function in this module that makes a trading decision.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

import numpy as np
import pandas as pd

from app.backtest import guards, metrics
from app.backtest.models import BARS_PER_YEAR, ExitReason, GuardReport, GuardStatus
from app.backtest.models import Trade as MetricsTrade
from app.config import Settings
from app.market.models import Interval
from app.paper.marketdata import AsOfMarket, Session, SessionCalendar, UnpricedSymbol
from app.paper.paperbroker import Fill, Mandate, Order, PaperBroker, Rejection
from app.rules import evaluate as rule_evaluate
from app.rules import grammar, macro_binding
from app.rules.nodes import BoolExpr, NumExpr
from app.tournament.models import (
    TRADE_END,
    TRADE_START,
    AgentResult,
    RealisedTrade,
    RejectionRecord,
    StrategyCard,
)

__all__ = ["GuardFailed", "LookaheadError", "run_card"]

#: The tournament's benchmark, matching `app.tournament.models.TournamentResult.benchmark`'s default
#: and the verified `SessionCalendar` construction this package was built against.
_BENCHMARK = "SPY"

_CENTS = Decimal("0.01")

#: How `RealisedTrade.exit_reason` values (this module's own vocabulary, matching that field's
#: docstring) map onto `app.backtest.models.ExitReason` for the metrics-only `Trade` objects fed to
#: `app.backtest.metrics.compute`. This mapping is inert: `compute()` never reads `Trade.exit_reason`
#: (only `open_at_end` and `return_pct` are), so a "target" exit reusing `ExitReason.STOP` here
#: changes no number `compute()` produces -- it exists only because `Trade.exit_reason` is a required
#: field and needs *some* value, and `STOP` is the closer analogue of the two available codes for a
#: price bracket than `SIGNAL` or `HORIZON` would be.
_METRICS_EXIT_REASON: dict[str, ExitReason] = {
    "stop": ExitReason.STOP,
    "target": ExitReason.STOP,
    "time": ExitReason.HORIZON,
    "rule": ExitReason.SIGNAL,
}


class GuardFailed(ValueError):
    """A card's `entry`, `exit` or `rank_by` expression did not pass `app.backtest.guards.check`.

    Raised rather than letting the expression run unguarded, per this module's contract (see the
    module docstring and `app.tournament.models.StrategyCard.entry`/`.exit`): an unguarded rule
    could be causally broken -- able to see a bar it should not -- and a run built on it would
    report a number that measures nothing.

    `rank_by` is held to the same standard for a less obvious reason. It never decides *whether* a
    name may be bought, only which of the already-qualifying names takes a scarce slot, so a
    non-causal key leaves the entry rule beside it clean and passing and shows up only in the
    selection. `field` says which of the three failed.
    """

    def __init__(
        self, agent_id: str, field: str, symbol: str, expression: str, report: GuardReport
    ) -> None:
        failed = "; ".join(f"{f.check}: {f.detail}" for f in report.findings if not f.passed)
        super().__init__(
            f"{agent_id}: {field} expression {expression!r} failed the lookahead guard against "
            f"{symbol} ({report.status.value}){': ' + failed if failed else ''}"
        )
        self.agent_id = agent_id
        self.field = field
        self.symbol = symbol
        self.expression = expression
        self.report = report


class LookaheadError(RuntimeError):
    """A decision function was handed a market whose `as_of` is not strictly before the session it
    is deciding for. See the module docstring's "Defence in depth" section for why this exists
    despite `AsOfMarket` already making the mistake structurally hard."""


def _require_decision_market(market: AsOfMarket, session: Session) -> None:
    if market.as_of >= session.date:
        raise LookaheadError(
            f"session {session.index} ({session.date.isoformat()}): a decision was evaluated "
            f"against a market as of {market.as_of.isoformat()}, which is not strictly before the "
            f"session being traded -- the decision market for session {session.index} must be "
            f"as_of={session.decided_on.isoformat()} (its own `decided_on`), never `session.date` "
            "or later"
        )


@dataclass(frozen=True, slots=True)
class _OpenLot:
    """One symbol's open position, as this run's own bookkeeping -- not the broker's.

    `PaperBroker` deliberately does not track cost basis (see its own docstring: the ledger derives
    basis from fills, and a second calculation here would be a second thing to keep correct). A stop,
    a target and a time stop all need an entry price and an entry session to compare against, so this
    module keeps exactly that much state, and no more, per open symbol.
    """

    entry_price: Decimal
    entry_date: dt.date | dt.datetime
    """A date on a daily run, a timestamp on an intraday one -- see `RealisedTrade.entry_date`."""
    entry_session_index: int
    quantity: Decimal
    entry_fees: Decimal


def _money(value: Decimal) -> Decimal:
    """Round to cents, half-up -- the same convention `PaperBroker` uses for every cash figure, so a
    trade's reported P&L cannot disagree with the broker's own ledger by a rounding rule."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Guarding -- once, up front, before any session runs
# ---------------------------------------------------------------------------


def _guard_card(
    card: StrategyCard,
    *,
    settings: Settings,
    first_decided_on: dt.date,
    interval: Interval = Interval.DAY,
) -> tuple[BoolExpr, BoolExpr | None, NumExpr | None]:
    """Guard every expression against each universe symbol's history, then parse them once.

    Guarded against ``first_decided_on`` -- the very first decision this run will ever make -- rather
    than against data through the trading window's end, so the guard itself never sees a bar the
    analyst's design window did not already justify looking at. `app.backtest.guards.check` never
    raises (see its own docstring); it returns a `GuardReport` whose status this function inspects,
    and turns a non-`PASSED` verdict into a raised `GuardFailed` -- the one behaviour this module
    promises the guard by itself does not: "a card whose expression fails the guard must raise rather
    than run unguarded."

    Guarding per universe symbol, not once for the whole card, because the causality check is
    data-dependent (it recomputes each referenced indicator on leading slices of the *actual* bars),
    and a rule that is causal against one symbol's history is not guaranteed causal against another's
    shorter or gappier one. `grammar.parse` is called only after every guard has passed, so it cannot
    fail here -- a failing parse is already caught, as a `GuardReport` with a `parse` finding, inside
    `guards.check` itself.
    """
    check_market = AsOfMarket(as_of=first_decided_on, settings=settings, interval=interval)
    exit_expression = card.exit.strip()

    for symbol in card.universe:
        bars = check_market.history(symbol, lookback_days=720)

        entry_report = guards.check(card.entry, bars, interval=interval)
        if entry_report.status is not GuardStatus.PASSED:
            raise GuardFailed(card.agent_id, "entry", symbol, card.entry, entry_report)

        if exit_expression:
            exit_report = guards.check(card.exit, bars, interval=interval)
            if exit_report.status is not GuardStatus.PASSED:
                raise GuardFailed(card.agent_id, "exit", symbol, card.exit, exit_report)

        # The ranking key is guarded exactly as the two rules are, and for a sharper reason: a
        # non-causal key would pick which name gets a scarce slot using a bar from after the
        # decision, and would do it while the entry rule beside it stayed clean and passing.
        if card.rank_by is not None:
            rank_report = guards.check(
                card.rank_by, bars, interval=interval, kind="ranking"
            )
            if rank_report.status is not GuardStatus.PASSED:
                raise GuardFailed(card.agent_id, "rank_by", symbol, card.rank_by, rank_report)

    entry_tree = grammar.parse(card.entry)
    exit_tree = grammar.parse(card.exit) if exit_expression else None
    rank_tree = grammar.parse_ranking(card.rank_by) if card.rank_by is not None else None
    return entry_tree, exit_tree, rank_tree


# ---------------------------------------------------------------------------
# Per-session decisions -- every one of these takes the decision-session market and asserts it
# ---------------------------------------------------------------------------


def _rule_fires(
    tree: BoolExpr,
    symbol: str,
    *,
    market: AsOfMarket,
    session: Session,
    interval: Interval = Interval.DAY,
) -> bool:
    """Truth of `tree` on `symbol`'s last available bar at `market.as_of`.

    `pd.NA` (an indicator still in warmup, or a gap) becomes `False` -- the same rule
    `app.backtest.strategy._fired` applies: an unknown truth value cannot open or close a position.
    An empty frame (the symbol has no stored bar at or before `market.as_of` at all) is `False` for
    the same reason, without needing `evaluate` to special-case it.
    """
    _require_decision_market(market, session)
    # Full history, not a window: `ema` and Wilder `rsi` carry a seed that decays from wherever
    # their series starts, so a bounded lookback makes a crossover's timing a function of the bound.
    # `strategy-program/DEFECTS.md` D4 has the case where that flipped a real signal.
    bars = market.history(symbol, lookback_days=None)
    if bars.empty:
        return False
    signal = rule_evaluate.evaluate(tree, bars, interval=interval, macro=_macro_frame(tree, bars))
    return bool(signal.fillna(False).iloc[-1])




def _macro_frame(tree: BoolExpr | NumExpr, bars: pd.DataFrame) -> pd.DataFrame | None:
    """The release-lagged macro frame this tree needs, or ``None`` when it reads no macro series.

    ``None`` for every card written before 2026-08-30, and `app.rules.evaluate`'s own ``macro``
    parameter defaults to ``None``, so passing it explicitly is exactly what those cards already got
    and no committed figure moves. A card that *does* name a macro series gets a frame built from the
    round's pin -- never a live fetch, which would make the run reproducible in its dates and not in
    its values.

    Returns the frame rather than ``{"macro": frame}`` for splatting: a ``**dict[str, object]`` is
    untypeable at these call sites, because mypy must assume the splat could land on *any* keyword
    parameter and `evaluate`'s neighbouring ``indicator_cache`` takes an `IndicatorCache | None`.
    That was three `--strict` errors saying, correctly, that nothing checked which argument this fed.
    """
    return macro_binding.bind_for_bars(tree, bars)


@dataclass(frozen=True, slots=True)
class _SignalTable:
    """Truth of one rule expression, per symbol, per decision date -- evaluated once for the run.

    **Why this exists.** `_rule_fires` used to re-evaluate its whole expression on every session for
    every symbol, recomputing each indicator across the symbol's entire visible history and then
    reading the last value. A 55-session, three-card desk did that 1,378 times, and a profile put
    effectively the whole runtime there: full `sma`/`ema`/`rsi` passes producing a 275-element
    boolean series of which 274 elements were discarded. The same expression over the same symbol
    is now evaluated once and indexed.

    **Why it is equivalent, and why it was not before.** `_rule_fires` and this table now read the
    *same frame* -- `history(symbol, lookback_days=None)`, every stored bar up to the decision date
    -- so they hand `evaluate` identical inputs and get identical series out. Indexing that series at
    date `t` is the same operation as evaluating it and taking the last element when the frame ends
    at `t`, for any indicator that is causal, which `app.backtest.guards.check` verifies per card
    before `run_card` ever builds a table.

    This was tried once before the D4 seeding fix and **failed**, which is worth keeping. While
    `_rule_fires` used a 400-day trailing window and the table used a longer frame, the two disagreed:
    `ema` and Wilder `rsi` carry a seed that decays from the start of whatever frame they are given,
    so the frames differing meant the values differed -- by about 1.8e-5, enough to flip one crossing
    in 246 runs and cost a card a trade. The reproduction caught it and the change was reverted. What
    made this sound was not a better argument, it was removing the difference in frames.

    `_require_decision_market` still fires on every decision path, so the other half of the
    anti-lookahead design is untouched, and `tests/test_tournament_runner.py` keeps a direct
    per-session-versus-table comparison so the equivalence cannot rot silently.
    """

    by_symbol: dict[str, pd.Series]

    def fires(self, symbol: str, on: dt.date) -> bool:
        """Truth for `symbol` on decision date `on`. `False` when unknown, never an exception.

        Mirrors `_rule_fires`' own contract exactly: a symbol with no stored bar at all, and a date
        the symbol has no bar for, are both `False` -- an unknown truth value cannot open or close a
        position, the same rule `app.backtest.strategy._fired` applies.
        """
        series = self.by_symbol.get(symbol)
        if series is None:
            return False
        value = series.get(on)
        return False if value is None else bool(value)


def _bar_key(ts: pd.Timestamp, interval: Interval) -> dt.date:
    """The key a decision table is indexed by, for one bar timestamp.

    Daily runs key on the calendar date, exactly as they always have. Finer intervals key on the
    full timestamp, because 78 five-minute bars share one date and collapsing them to it would keep
    only the last and silently discard the other 77 decisions. `SessionCalendar` produces matching
    keys from the same rule, and one run never mixes the two -- `date < datetime` raises.
    """
    # Annotated locals rather than a bare return: `pandas-stubs` types both accessors as `Any`, so
    # returning either directly asserts this function's `-> dt.date` contract without anything
    # checking it. `dt.datetime` is a `dt.date` subclass, which is what makes the finer-interval
    # branch legal here rather than merely convenient.
    if interval is Interval.DAY:
        key: dt.date = ts.date()
    else:
        key = ts.to_pydatetime()
    return key


def _build_signal_table(
    tree: BoolExpr | None,
    symbols: tuple[str, ...],
    *,
    settings: Settings,
    through: dt.date,
    interval: Interval = Interval.DAY,
) -> _SignalTable:
    """Evaluate `tree` once per symbol, over every stored bar up to the run's last decision date.

    `through` is that last decision date and never anything later: the frame handed to `evaluate`
    stops where the run's own decisions stop, so no bar the run could not have seen is in scope even
    in principle.
    """
    if tree is None:
        return _SignalTable({})
    market = AsOfMarket(as_of=through, settings=settings, interval=interval)
    by_symbol: dict[str, pd.Series] = {}
    for symbol in symbols:
        bars = market.history(symbol, lookback_days=None)
        if bars.empty:
            continue
        signal = rule_evaluate.evaluate(
            tree, bars, interval=interval, macro=_macro_frame(tree, bars)
        ).fillna(False)
        signal.index = pd.Index([_bar_key(ts, interval) for ts in bars["ts"]])
        by_symbol[symbol] = signal
    return _SignalTable(by_symbol)


@dataclass(frozen=True, slots=True)
class _RankTable:
    """Value of one `StrategyCard.rank_by` key, per symbol, per decision date.

    `_SignalTable` for the numeric half of the grammar, and deliberately the same shape, the same
    frames and the same build path -- `_build_rank_table` differs from `_build_signal_table` only in
    which `app.rules.evaluate` entry point it calls. That matters for more than tidiness: the key is
    subject to the identical causality argument the entry rule is (see `_SignalTable`'s note on why
    indexing a once-evaluated series equals evaluating it per session), so giving it a different
    frame or a different lookback would reintroduce exactly the seed-decay disagreement that
    reproduction caught and reverted.

    **Unknown is a real state and is kept distinct from a value.** Through an indicator's warmup a
    symbol has no key -- `close / sma(200)` is `NaN` for a name with 150 bars of history. That is not
    "ranks lowest"; it is "this run cannot say", and `_ordered_entry_candidates` puts those names
    behind every ranked one in universe order rather than letting a `NaN` fall wherever a sort
    happens to drop it. A name with no key still trades: it qualified on the entry rule, which is
    what decides whether it may be bought at all.
    """

    by_symbol: dict[str, pd.Series]

    def value(self, symbol: str, on: dt.date) -> float | None:
        """The key for `symbol` on decision date `on`. `None` when there is no value to give.

        `None` covers all three ways that happens -- no stored bars, no bar on that date, and a
        `NaN` from an indicator still in warmup -- because the caller treats them identically and
        distinguishing them here would only invite a caller to handle two of the three.
        """
        series = self.by_symbol.get(symbol)
        if series is None:
            return None
        raw = series.get(on)
        if raw is None:
            return None
        value = float(raw)
        return None if math.isnan(value) else value


def _build_rank_table(
    tree: NumExpr | None,
    symbols: tuple[str, ...],
    *,
    settings: Settings,
    through: dt.date,
    interval: Interval = Interval.DAY,
) -> _RankTable:
    """Evaluate the ranking key once per symbol, over every stored bar up to the last decision date.

    Same contract as `_build_signal_table`, including `through` never being later than the run's own
    last decision -- see that function. `NaN` is *not* filled here, unlike the signal table's
    `fillna(False)`: false is the right reading of an unknown truth value (an unknown condition
    cannot fire), while zero is not the right reading of an unknown magnitude, and `_RankTable.value`
    turns it into `None` at the point of use instead.
    """
    if tree is None:
        return _RankTable({})
    market = AsOfMarket(as_of=through, settings=settings, interval=interval)
    by_symbol: dict[str, pd.Series] = {}
    for symbol in symbols:
        bars = market.history(symbol, lookback_days=None)
        if bars.empty:
            continue
        values = rule_evaluate.evaluate_num(
            tree, bars, interval=interval, macro=_macro_frame(tree, bars)
        )
        values.index = pd.Index([_bar_key(ts, interval) for ts in bars["ts"]])
        by_symbol[symbol] = values
    return _RankTable(by_symbol)


def _ordered_entry_candidates(
    universe: tuple[str, ...], ranks: _RankTable, *, on: dt.date
) -> tuple[str, ...]:
    """The order entries are attempted in on one session -- strongest first, or universe order.

    **This function is the whole point of `rank_by`.** The runner fills entries until the slots run
    out, so whichever order it walks the universe in *is* the selection rule whenever more names
    qualify than fit. Left unranked that order is the order the array was typed in, worth a measured
    53.9-point spread over twelve orderings of one identical card (`PROTOCOL.md` §7).

    An empty table -- the card left `rank_by` unset -- returns `universe` unchanged and byte-for-byte
    reproduces every result recorded before this field existed. That is not a convenience; the
    library's cards are frozen and their numbers are already published, so the unranked path has to
    be the identical path, not an equivalent one.

    Ranked, the order is: every symbol with a key, highest key first; then every symbol without one.
    Ties and unknowns keep universe order, because the sort is stable over a list already in that
    order -- so two names with an identical key resolve the way they always did rather than by an
    accident of sorting, and the whole function stays deterministic, which `PROTOCOL.md` §8 requires
    of every run.
    """
    if not ranks.by_symbol:
        return universe

    def sort_key(symbol: str) -> tuple[int, float]:
        value = ranks.value(symbol, on)
        # Unknown sorts to the back via the leading 1; `-value` is what makes the highest key first
        # while keeping `sorted`'s ascending default (and therefore its stability) rather than
        # `reverse=True`, which would reverse equal elements' universe order too.
        return (1, 0.0) if value is None else (0, -value)

    return tuple(sorted(universe, key=sort_key))


def _bracket_reason(
    card: StrategyCard, symbol: str, lot: _OpenLot, *, market: AsOfMarket, session: Session
) -> str | None:
    """`"stop"`, `"target"`, `"time"`, or `None` -- see the module docstring's "Bracket timing" and
    "Exit precedence" sections for why the price brackets are checked against the previous close and
    checked before the time stop."""
    _require_decision_market(market, session)

    if card.stop_loss_pct is not None or card.take_profit_pct is not None:
        try:
            last_close = market.close(symbol)
        except UnpricedSymbol:
            last_close = None
        if last_close is not None:
            if card.stop_loss_pct is not None:
                stop_level = lot.entry_price * (Decimal(1) - card.stop_loss_pct)
                if last_close <= stop_level:
                    return "stop"
            if card.take_profit_pct is not None:
                target_level = lot.entry_price * (Decimal(1) + card.take_profit_pct)
                if last_close >= target_level:
                    return "target"

    if card.max_hold_days is not None:
        held = session.index - lot.entry_session_index
        if held >= card.max_hold_days:
            return "time"

    return None


def _decide_exit(
    card: StrategyCard,
    symbol: str,
    lot: _OpenLot,
    exit_tree: BoolExpr | None,
    *,
    market: AsOfMarket,
    session: Session,
    exit_signals: _SignalTable,
) -> str | None:
    """One session's exit verdict for one open lot, in precedence order: stop, target, time, rule."""
    reason = _bracket_reason(card, symbol, lot, market=market, session=session)
    if reason is not None:
        return reason
    # `_require_decision_market` still guards this path even though the rule verdict now comes from
    # a table: the brackets above read prices straight off `market`, and the assertion is what keeps
    # a caller from threading the end-of-session marking market in here by mistake.
    _require_decision_market(market, session)
    if exit_tree is not None and exit_signals.fires(symbol, session.decided_on):
        return "rule"
    return None


def _entry_quantity(mandate: Mandate, notional: Decimal, price: Decimal) -> Decimal:
    """Whole shares (or fractional, if the mandate allows) that `notional` buys at `price`, floored --
    never rounded up, which would size a position larger than `card.position_pct` actually asked for.
    The broker itself still enforces cash and concentration; this only decides how many shares to
    *ask* for.
    """
    if price <= 0:
        return Decimal(0)
    raw = notional / price
    if mandate.allow_fractional_shares:
        return raw.quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
    return raw.to_integral_value(rounding=ROUND_DOWN)


# ---------------------------------------------------------------------------
# Trade bookkeeping -- Decimal for the reported trade, float only for the metrics call
# ---------------------------------------------------------------------------


def _close_trade(
    symbol: str, lot: _OpenLot, fill: Fill, reason: str
) -> tuple[RealisedTrade, MetricsTrade]:
    gross = (fill.price - lot.entry_price) * lot.quantity
    pnl = _money(gross - lot.entry_fees - fill.fees)
    basis = lot.entry_price * lot.quantity
    return_pct = (pnl / basis) if basis != 0 else Decimal(0)
    bars_held = fill.session - lot.entry_session_index

    realised = RealisedTrade(
        symbol=symbol,
        entry_date=lot.entry_date,
        entry_price=lot.entry_price,
        exit_date=fill.trade_date,
        exit_price=fill.price,
        quantity=lot.quantity,
        exit_reason=reason,
        pnl=pnl,
        return_pct=return_pct,
        bars_held=bars_held,
    )
    metric = MetricsTrade(
        entry_date=lot.entry_date,
        entry_price=float(lot.entry_price),
        exit_date=fill.trade_date,
        exit_price=float(fill.price),
        exit_reason=_METRICS_EXIT_REASON[reason],
        bars_held=bars_held,
        return_pct=float(return_pct),
        open_at_end=False,
    )
    return realised, metric


def _open_at_end_trade(
    symbol: str, lot: _OpenLot, mark_price: Decimal, last_session: Session
) -> tuple[RealisedTrade, MetricsTrade]:
    """A position still open when the trading window ends. `pnl`/`return_pct` are the unrealised
    mark against `mark_price` (the last session's close) -- reported anyway, because `RealisedTrade`
    has no optional-pnl escape hatch and an unrealised mark is still the honest answer to "what did
    this trade do so far". `exit_date`/`exit_price` stay `None`: nothing was actually sold."""
    gross = (mark_price - lot.entry_price) * lot.quantity
    pnl = _money(gross - lot.entry_fees)
    basis = lot.entry_price * lot.quantity
    return_pct = (pnl / basis) if basis != 0 else Decimal(0)
    bars_held = last_session.index - lot.entry_session_index

    realised = RealisedTrade(
        symbol=symbol,
        entry_date=lot.entry_date,
        entry_price=lot.entry_price,
        exit_date=None,
        exit_price=None,
        quantity=lot.quantity,
        exit_reason="open_at_end",
        pnl=pnl,
        return_pct=return_pct,
        bars_held=bars_held,
    )
    metric = MetricsTrade(
        entry_date=lot.entry_date,
        entry_price=float(lot.entry_price),
        exit_date=last_session.date,
        exit_price=float(mark_price),
        exit_reason=ExitReason.END_OF_DATA,
        bars_held=bars_held,
        return_pct=float(return_pct),
        open_at_end=True,
    )
    return realised, metric


def _undilute_exposure(exposure: float | None, sessions: int) -> float | None:
    """Rescale session-presence exposure off the prepended starting-equity point.

    Fixing D1 required prepending a point to the equity curve so it genuinely begins at starting
    equity, and `in_position` had to gain a matching leading ``False`` to stay aligned. But
    `metrics.compute` derives ``exposure`` as ``mean(in_position)``, so that alignment point silently
    became part of the denominator: a card holding a position on every one of 250 sessions reported
    ``250/251`` instead of ``1.0``.

    The dilution is small and it is also simply wrong -- ``exposure`` is defined over trading
    sessions, and the prepended point is not one. Multiplying back by ``(sessions + 1) / sessions``
    restores the intended denominator exactly, because the numerator (the count of sessions holding
    something) is untouched by the prepend.

    A cleaner fix would be a separate hook in `compute` to exclude the alignment point, which is not
    worth changing a shared contract for; this is the same arithmetic at the one call site that needs
    it.
    """
    if exposure is None or sessions <= 0:
        return exposure
    return exposure * (sessions + 1) / sessions


def _benchmark_return(
    settings: Settings,
    first_session: Session,
    last_session: Session,
    *,
    interval: Interval = Interval.DAY,
) -> Decimal | None:
    """Buy-and-hold on `_BENCHMARK`: bought at the first session's open, held to the last session's
    close -- the identical entry/exit convention every strategy in this run gets, so the comparison is
    like for like. `None` when the benchmark itself is unpriceable over the window, rather than a
    fabricated zero.
    """
    # `interval` matters here even though the benchmark is the same symbol at every interval: the
    # session keys handed in are timestamps on an intraday run, and an `AsOfMarket` left on daily
    # bars would slice a daily frame at an intraday instant, find nothing, and quietly return `None`
    # -- a missing benchmark rather than a wrong one, which is harder to notice.
    market = AsOfMarket(as_of=last_session.date, settings=settings, interval=interval)
    try:
        entry_price = market.open_on(_BENCHMARK, first_session.date)
        exit_price = market.close(_BENCHMARK)
    except (UnpricedSymbol, FileNotFoundError):
        return None
    if entry_price == 0:
        return None
    return (exit_price - entry_price) / entry_price


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def run_card(
    card: StrategyCard,
    *,
    settings: Settings,
    mandate: Mandate,
    start: dt.date = TRADE_START,
    end: dt.date = TRADE_END,
    interval: Interval = Interval.DAY,
) -> AgentResult:
    """Trade `card` through a fresh `PaperBroker` from `start` to `end`, session by session.

    See the module docstring for the exit-precedence, bracket-timing and sizing decisions this
    function embodies, and `_require_decision_market` for the lookahead defence every per-session
    decision below is routed through. `SessionCalendar` guarantees at least one session or raises
    (see its own docstring), so this function never has to special-case an empty run.
    """
    calendar = SessionCalendar(
        start=start, end=end, settings=settings, benchmark=_BENCHMARK, interval=interval
    )
    sessions = list(calendar)

    entry_tree, exit_tree, rank_tree = _guard_card(
        card, settings=settings, first_decided_on=sessions[0].decided_on, interval=interval
    )

    # Built *after* `_guard_card`, and the ordering is the safety argument, not an accident: the
    # guard is what establishes the causality these tables rely on, so a card that cannot be shown
    # causal never reaches them. See `_SignalTable`.
    entry_signals = _build_signal_table(
        entry_tree, card.universe, settings=settings, through=sessions[-1].decided_on,
        interval=interval,
    )
    exit_signals = _build_signal_table(
        exit_tree, card.universe, settings=settings, through=sessions[-1].decided_on,
        interval=interval,
    )
    entry_ranks = _build_rank_table(
        rank_tree, card.universe, settings=settings, through=sessions[-1].decided_on,
        interval=interval,
    )

    broker = PaperBroker(mandate)
    starting_equity = mandate.starting_cash
    position_notional = card.position_pct * starting_equity

    open_lots: dict[str, _OpenLot] = {}
    trades: list[RealisedTrade] = []
    metrics_trades: list[MetricsTrade] = []
    equity_curve: list[Decimal] = []
    in_position_flags: list[bool] = []
    #: Per-session sum of *entry* notional (`quantity * entry_price`, not the current mark) for every
    #: lot open at that session's close -- see `AgentResult.capital_exposure`'s docstring (DEFECTS.md
    #: D2). Entry notional, not mark-to-market value, because `position_pct` sizes off starting equity
    #: at entry time (see the module docstring's "Position sizing" section), so entry notional over
    #: starting equity is the quantity that actually corresponds to "how much of the book this
    #: position committed," and it is also what makes this sum agree with `strategy-program/tools/
    #: score.py`'s trade-log reconstruction `Σ(quantity * entry_price * bars_held)`: a lot held across
    #: several sessions contributes its entry notional once per session it was open, which is exactly
    #: `quantity * entry_price * bars_held` once summed over its lifetime.
    session_entry_notional: list[Decimal] = []
    order_seq = 0

    for session in sessions:
        decision_market = AsOfMarket(as_of=session.decided_on, settings=settings, interval=interval)

        # -- exits, before any new entry is even considered ------------------------------------
        for symbol in list(open_lots):
            lot = open_lots[symbol]
            reason = _decide_exit(
                card,
                symbol,
                lot,
                exit_tree,
                market=decision_market,
                session=session,
                exit_signals=exit_signals,
            )
            if reason is None:
                continue

            order_seq += 1
            order = Order(
                order_id=f"{card.agent_id}-s{session.index}-x{order_seq}",
                session=session.index,
                decided_on=session.decided_on,
                symbol=symbol,
                side="sell",
                quantity=lot.quantity,
                thesis=f"{reason} exit for {symbol} ({card.agent_id})",
                invalidation="n/a -- this order closes a position, it does not open one",
            )
            outcome: Fill | Rejection = broker.submit(
                order, market=decision_market, fill_date=session.date
            )
            if isinstance(outcome, Fill):
                realised, metric = _close_trade(symbol, lot, outcome, reason)
                trades.append(realised)
                metrics_trades.append(metric)
                del open_lots[symbol]
            # A `Rejection` is already recorded in `broker.rejections` (see `PaperBroker._reject`'s
            # own docstring on being the sole append site). The lot stays open and `_decide_exit`
            # is asked again next session -- a position this run cannot close is a fact about the
            # run to report via `AgentResult.rejections`, not a state to force-clear here.

        # -- entries, up to card.max_positions ---------------------------------------------------
        if len(open_lots) < card.max_positions:
            # Universe order unless the card named a ranking key -- see `_ordered_entry_candidates`
            # for why the order this loop walks in *is* the selection rule once slots are scarce.
            for symbol in _ordered_entry_candidates(
                card.universe, entry_ranks, on=session.decided_on
            ):
                if len(open_lots) >= card.max_positions:
                    break
                if symbol in open_lots:
                    continue  # no pyramiding -- see the module docstring
                _require_decision_market(decision_market, session)
                if not entry_signals.fires(symbol, session.decided_on):
                    continue

                try:
                    price = decision_market.close(symbol)
                except UnpricedSymbol:
                    continue
                quantity = _entry_quantity(mandate, position_notional, price)
                if quantity <= 0:
                    continue

                order_seq += 1
                order = Order(
                    order_id=f"{card.agent_id}-s{session.index}-e{order_seq}",
                    session=session.index,
                    decided_on=session.decided_on,
                    symbol=symbol,
                    side="buy",
                    quantity=quantity,
                    thesis=f"entry rule fired for {symbol} ({card.agent_id}): {card.entry}",
                    invalidation=(
                        f"stop_loss_pct={card.stop_loss_pct}, take_profit_pct={card.take_profit_pct}, "
                        f"max_hold_days={card.max_hold_days}, exit={card.exit!r}"
                    ),
                )
                outcome = broker.submit(order, market=decision_market, fill_date=session.date)
                if isinstance(outcome, Fill):
                    open_lots[symbol] = _OpenLot(
                        entry_price=outcome.price,
                        entry_date=outcome.trade_date,
                        entry_session_index=session.index,
                        quantity=outcome.quantity,
                        entry_fees=outcome.fees,
                    )
                # Rejection already recorded by the broker -- see the comment on the exit path above.

        # -- mark equity at this session's own close ---------------------------------------------
        mark_market = AsOfMarket(as_of=session.date, settings=settings, interval=interval)
        equity_curve.append(broker.equity(mark_market))
        in_position_flags.append(bool(open_lots))
        session_entry_notional.append(
            sum((lot.quantity * lot.entry_price for lot in open_lots.values()), start=Decimal(0))
        )

    # -- anything still open when the window ends is an unrealised, not a discarded, result -------
    last_session = sessions[-1]
    final_market = AsOfMarket(as_of=last_session.date, settings=settings, interval=interval)
    for symbol, lot in open_lots.items():
        try:
            mark_price = final_market.close(symbol)
        except UnpricedSymbol:
            mark_price = lot.entry_price  # no data to mark against; report flat rather than crash
        realised, metric = _open_at_end_trade(symbol, lot, mark_price, last_session)
        trades.append(realised)
        metrics_trades.append(metric)

    ending_equity = equity_curve[-1]

    # Normalised to `starting_equity`, not to `equity_curve[0]`: the first session's own decision was
    # made on the design window's last close (see `app.tournament.models.TRADE_START`'s docstring), so
    # a fill -- and therefore a mark different from `starting_equity` -- can legitimately happen on the
    # very first session. `compute()`'s contract is `equity[0]` normalised to `1.0`, meaning "before
    # any session's own move" -- so satisfying that contract (rather than just dividing every element
    # by the constant `starting_equity`, which cancels out of `equity[-1] / equity[0]` and does nothing
    # to `total_return` at all -- see DEFECTS.md D1) requires the array's first element to genuinely
    # be `starting_equity`. We prepend it as its own point rather than dividing by `equity_curve[0]`,
    # so `equity_curve[0]` -- the first session's actual close, which can differ from `starting_equity`
    # -- stays in the series and is not silently rebased away.
    #
    # `in_position_flags` is prepended with `False` to stay aligned: no position can be open before the
    # first session has even run. This does add one legitimate observation to the per-bar returns
    # series (`equity[1:] / equity[:-1] - 1.0` inside `compute()`) -- the first session's own move,
    # from `starting_equity` to `equity_curve[0]` -- which is correct, not incidental: that move is a
    # real return this run earned and previously never appeared in `sharpe`/`sortino`/`volatility` at
    # all. `sessions` (below) is left alone -- it counts trading sessions, not equity-curve points, and
    # the day before session one is not a session.
    equity_array = np.array(
        [1.0] + [float(e / starting_equity) for e in equity_curve], dtype=np.float64
    )
    in_position_array = np.array([False, *in_position_flags], dtype=np.bool_)

    strategy_metrics = metrics.compute(
        equity_array,
        in_position=in_position_array,
        trades=metrics_trades,
        bars_per_year=BARS_PER_YEAR[interval],
        annualisable=not interval.is_intraday,
    )
    # `equity_array` has one entry per session plus the prepended starting-equity point, and
    # `SessionCalendar` never yields zero sessions (it raises instead -- see its own docstring), so
    # `compute()` only takes its all-`None` early-return path on an empty array, which cannot happen
    # here. `total_return`/`max_drawdown` are therefore always populated; asserted rather than
    # silently coalesced to `Decimal(0)` so a future change to either contract fails loudly here
    # instead of quietly reporting a fabricated zero.
    assert strategy_metrics.total_return is not None
    assert strategy_metrics.max_drawdown is not None

    # Capital-weighted exposure (DEFECTS.md D2) -- see `AgentResult.capital_exposure`'s docstring and
    # `session_entry_notional`'s above. Averaged over `sessions`, not over `equity_array`: there is no
    # "session zero" position to weigh in, only real trading sessions, and this must match the
    # denominator `strategy-program/tools/score.py` uses (`sessions * starting_equity`).
    capital_exposure = float(
        sum(session_entry_notional, start=Decimal(0)) / (Decimal(len(sessions)) * starting_equity)
    )

    return AgentResult(
        card=card,
        sessions=len(sessions),
        starting_equity=starting_equity,
        ending_equity=ending_equity,
        total_return=Decimal(str(strategy_metrics.total_return)),
        max_drawdown=Decimal(str(strategy_metrics.max_drawdown)),
        sharpe=strategy_metrics.sharpe,
        sortino=strategy_metrics.sortino,
        volatility=strategy_metrics.volatility,
        exposure=_undilute_exposure(strategy_metrics.exposure, len(sessions)),
        capital_exposure=capital_exposure,
        win_rate=strategy_metrics.win_rate,
        trades=tuple(trades),
        rejections=tuple(r.rule for r in broker.rejections),
        rejection_details=tuple(
            RejectionRecord(rule=r.rule, symbol=r.symbol, reason=r.reason) for r in broker.rejections
        ),
        benchmark_return=_benchmark_return(settings, sessions[0], last_session, interval=interval),
    )

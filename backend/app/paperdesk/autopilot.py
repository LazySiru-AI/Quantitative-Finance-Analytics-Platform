"""Turns the Agent Workflow's persisted paper book into a :class:`~app.paperdesk.models.Desk`.

**Why this desk reads a ledger instead of replaying bars, when every other desk in this package
does the opposite.** `app.paperdesk.desk` builds every other seat by re-running a `StrategyCard`'s
boolean rules against stored bars from scratch on every request -- deterministic by construction,
because a card's decision on any given day is a pure function of price history. The Agent Workflow's
decisions are not that: each order is the output of a chain of language-model judgements (a regime
call, a strategy-card selection, a screened candidate list, a debate, a gate verdict) made against
evidence -- headlines, filings, a transcript -- that price bars alone cannot reconstruct, and that is
not guaranteed to reproduce even if re-run verbatim. `app.workflow.book_models` states this at length
for exactly this reason: an order has to be written down, once, the day it is decided, because it
cannot be recomputed the day after. This module is the read side of that ledger -- it never invents a
number the book, the broker or the run store did not already record.

**This module owns no file but its own.** It reads `app.workflow.book`'s persisted `BookState`
through the public functions that module already exports (`load_book`, `held_lots`, `tax_summary`),
reads prices through `app.paper.marketdata.AsOfMarket` exactly as every other desk does, and reads
workflow run provenance through `app.agentdesk.store.RunStore`. It does not import
`app.paperdesk.desk` -- that module is going to import *this* one to seat the desk, and an import the
other way would be a cycle.

**Two things this seat states plainly rather than fabricates.** First, the per-lot bracket columns --
`stop_price`/`target_price`/`sessions_to_time_stop` on every :class:`~app.paperdesk.models.Holding`
below -- stay `None`. The workflow *does* now close positions (`app.workflow.exits` applies the
selected card's stop, take-profit, hold cap and exit rule once a session, and the seat reports which
of those are in force through :attr:`~app.paperdesk.models.AutopilotDescription.exits`), but it
evaluates them at the **book** level against the ledger's own lots rather than attaching a bracket to
each row, and the ledger records no per-order bracket. Deriving one here would be this module
computing a risk control rather than reading one, which is exactly the line it does not cross.
Second, `BookState.equity_curve` is empty on every book on disk today --
`app.workflow.book.snapshot_equity` has no callers anywhere in this codebase (confirmed with
`grep -rn snapshot_equity backend/app`), so `max_drawdown`/`capital_exposure` cannot be read off it.
This module builds its own curve from the book's own fill history instead (see `_equity_curve`), the
same fills-forward walk `app.workflow.book.mark_equity_through` already performs, reimplemented here
because that function reads its own session list from the store directly rather than accepting one,
and because this module has to run it over the seat's *own* inception (`book.card_adopted_date`), not
the trading book's -- an operator inception override on the book can move the desk's own window well
after this seat started (see `_curve_sessions`'s own docstring).
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal, cast, get_args

import numpy as np

from app.agentdesk.models import DeskRun
from app.agentdesk.store import RunStore
from app.backtest import metrics as metrics_mod
from app.backtest.models import BARS_PER_YEAR
from app.config import Settings
from app.market.models import Interval
from app.paper.marketdata import AsOfMarket, SessionCalendar, UnpricedSymbol
from app.paper.paperbroker import Mandate, PaperBroker, rejection_label
from app.paperdesk.models import (
    AutopilotDescription,
    AutopilotOrder,
    Decision,
    Desk,
    DeskRejection,
    Holding,
    Trade,
)
from app.tournament.models import StrategyCard
from app.workflow import book as book_mod
from app.workflow.book_models import BookState, WorkflowArm, WorkflowOrderRecord

__all__ = [
    "AUTOPILOT_AGENT_ID",
    "AUTOPILOT_ARM",
    "AUTOPILOT_DISCIPLINE",
    "AUTOPILOT_DISPLAY_NAME",
    "AUTOPILOT_STARTING_CASH",
    "AUTOPILOT_UNIVERSE_SOURCE",
    "build_desk",
    "universe_symbols",
]

logger = logging.getLogger(__name__)

_CENTS = Decimal("0.01")
_MAX_REJECTION_DETAIL = 20
"""Matches `app.paperdesk.desk._MAX_REJECTION_DETAIL` exactly -- see `DeskRejection.detail`'s own
docstring for why this cap exists at all."""

# `_ARM`/`_UNIVERSE_SOURCE` carry the real `Literal` types `app.workflow.book`'s functions require;
# `AUTOPILOT_ARM`/`AUTOPILOT_UNIVERSE_SOURCE` below are the plain-`str` public constants another
# module is coding against (they feed `AutopilotDescription.arm`/`.universe_source`, both `str`
# fields). Splitting the two is what lets both sides typecheck under strict mypy without a `cast`:
# a `Literal["full_workflow"]` is a valid `str`, so the public constant can simply be assigned from
# the private one, but the reverse assignment (a bare `str` into a `Literal`-typed parameter) is not.
_ARM: WorkflowArm = "full_workflow"
_UNIVERSE_SOURCE: Literal["card", "screen"] = "screen"

AUTOPILOT_AGENT_ID: str = "autopilot-workflow"
"""Distinguishes this seat from every `StrategyCard`/`LadderCard` roster id -- see
`docs/AUTOPILOT-CARD-PLAN.md` section 2.1: `app.paperdesk.desk` branches on this id to call
`build_desk` directly rather than routing it through `_load_card`, which would try (and fail) to
validate it as a strategy card."""
AUTOPILOT_ARM: str = _ARM
"""Which of the four Agent Workflow study arms this seat trades -- see
`app.workflow.book_models.WorkflowArm`. Fixed to `"full_workflow"`, the arm the researched pipeline
(regime -> card select -> screen -> research -> gate -> stage) actually produces; the other three arms
exist for the study's own comparison, not to be seated as a tradeable desk."""
AUTOPILOT_UNIVERSE_SOURCE: str = _UNIVERSE_SOURCE
"""`"screen"` -- this seat reads the dynamically-screened book, not the fixed-card one. See
`app.workflow.book_models.BookState.universe_source`'s own docstring for why a book is identified by
the *pair* `(arm, universe_source)`, never by `arm` alone."""
AUTOPILOT_STARTING_CASH: Decimal = Decimal("100000")
"""Must track `app.workflow.pipeline.STARTING_CASH` exactly -- both name the same $100,000 seat.
Restated here rather than imported because `app.workflow.pipeline` pulls in the entire
TradingAgents/VibeDesk orchestration stack for one constant, which this display-only module has no
other reason to import. This value is consulted by `load_book` only on the branch where no book file
exists yet at all (see that function's own docstring): a real book's `starting_cash` field, once one
has been written, is read from the file instead and this constant is never consulted again for it. If
the two constants ever diverge, the only case that can go wrong is a book that has never been created
-- and a seat with no book yet is dormant regardless, so the observable effect of a stale duplicate
here is bounded by construction, not merely by discipline."""
AUTOPILOT_DISPLAY_NAME: str = "Autopilot"
AUTOPILOT_DISCIPLINE: str = "agent-workflow"


def _resolve_source(settings: Settings) -> tuple[Literal["card", "screen"], WorkflowArm]:
    """The ``(universe_source, arm)`` pair the seat renders, parsed from
    ``settings.paperdesk_autopilot_source`` (``"<universe_source>:<arm>"``).

    **A malformed or unknown value degrades to the built-in default (:data:`_UNIVERSE_SOURCE`,
    :data:`_ARM`), logged, never raised** -- see that setting's own docstring for why a display knob
    must pin the seat to the default book rather than crash the page or the app's startup. Every
    rejection path -- no colon, an unknown ``universe_source``, an unknown ``arm`` -- lands on the
    same default so the seat always renders *some* real book. `_ARM`/`_UNIVERSE_SOURCE` remain the
    single source of truth for that default; this function only *chooses between* real books, it never
    invents one.
    """
    raw = settings.paperdesk_autopilot_source
    source_str, _sep, arm_str = raw.partition(":")
    if source_str in ("card", "screen") and arm_str in get_args(WorkflowArm):
        return cast('Literal["card", "screen"]', source_str), cast("WorkflowArm", arm_str)
    logger.warning(
        "autopilot: paperdesk_autopilot_source %r is not '<card|screen>:<arm>'; falling back to the "
        "default book %s:%s",
        raw,
        _UNIVERSE_SOURCE,
        _ARM,
    )
    return _UNIVERSE_SOURCE, _ARM


def _money(value: Decimal) -> Decimal:
    """Round to cents, half-up -- the same convention every other module in this application applies
    to a cash figure at the point it becomes one (`app.paperdesk.desk._money`,
    `app.workflow.book._money`, `app.paper.paperbroker._money`)."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _bars_between(start: dt.date, end: dt.date, session_dates: tuple[dt.date, ...]) -> int:
    """Count of `session_dates` entries in `(start, end]` -- sessions actually elapsed, not a
    calendar-day subtraction that cannot see weekends or holidays. Clamped at zero: `start` can, in
    principle, sit after `end` (a fill recorded on a catch-up run whose wall-clock `filled_at` lands
    after this window's own `as_of`), and a negative bar count would be a stranger thing to render
    than a bald zero."""
    return max(0, sum(1 for d in session_dates if start < d <= end))


# ---------------------------------------------------------------------------
# Universe -- every symbol this seat needs priced, for app.paperdesk.fetch
# ---------------------------------------------------------------------------


def universe_symbols(settings: Settings) -> tuple[str, ...]:
    """Every distinct symbol the autopilot seat needs priced -- every symbol that has ever appeared
    on any order in its book (filled, pending or rejected), sorted and de-duplicated.

    `app.paperdesk.desk.universe_symbols` builds the roster of symbols `app.paperdesk.fetch` refreshes
    by walking every seated id through `_load_card`. This seat has no card to load -- see
    `AUTOPILOT_AGENT_ID`'s own docstring -- so without a function like this one, its held symbols
    would never be swept for fresh bars and its holdings could never be marked to the newest session.

    **Never raises.** A missing book file degrades to `()` through `load_book`'s own "no file yet ->
    freshly seeded, empty" branch (see that function's docstring) -- the ordinary state for a seat that
    has never traded, not an error. A book file that exists but cannot be read (corrupt JSON, an
    unrecognised `schema_version`, a `universe_source` mismatch -- every case `load_book` itself raises
    `ValueError` for) is caught here and logged, rather than taking down the one fetch sweep this
    function feeds over one seat's bad file.
    """
    source, arm = _resolve_source(settings)
    try:
        book = book_mod.load_book(
            settings,
            arm,
            starting_cash=AUTOPILOT_STARTING_CASH,
            card_id="",
            universe_source=source,
        )
    except Exception:
        logger.warning(
            "autopilot: could not read workflow book; universe_symbols degrading to ()",
            exc_info=True,
        )
        return ()
    return tuple(sorted({order.symbol for order in book.orders}))


# ---------------------------------------------------------------------------
# The seat's own trading-session list -- independent of the desk's own window
# ---------------------------------------------------------------------------


def _curve_sessions(
    book: BookState, *, settings: Settings, benchmark: str, as_of: dt.date
) -> tuple[dt.date, ...]:
    """Every session this seat's own equity curve and every holding's `bars_held` are measured over,
    from the earlier of `book.card_adopted_date` and its earliest fill through `as_of`.

    **Deliberately not the trading desk's own window.** `app.paperdesk.desk._trading_window` starts at
    `effective_inception(settings)`, which an operator override can move well after this seat's own
    `card_adopted_date` (measured 2026-09-01: the desk's own inception is 2026-08-27 under an active
    override while this seat adopted its card on 2026-08-03). Measuring this seat's drawdown and
    exposure over the desk's shorter window would silently drop its first three weeks and describe a
    shorter history than the panel claims the seat has traded. `SessionCalendar` is reused rather than
    reimplemented for the same reason `_trading_window` reuses it: it is this application's one
    definition of which dates are actually tradeable sessions.

    The start is also pulled back to the earliest *filled* order's own `fill_date` when that predates
    `card_adopted_date` -- a card rotation adopted after trading already began must not leave earlier
    fills outside the curve they are supposed to be inside.

    **Never raises; an unbuildable window degrades to `()`, an empty curve, rather than an exception**
    the caller would otherwise have to guard a second time. Two real cases produce it: a freshly seeded
    book's `card_adopted_date` is `dt.date.today()` (see `app.workflow.book.load_book`), which can sit
    after `as_of` (the store's own newest bar, on a weekend or before that day's fetch has run) -- the
    start is clamped to `min(start, as_of)` so `SessionCalendar` is never asked for a backwards window
    -- and the benchmark's own store might not cover the resulting window at all, which
    `SessionCalendar.__init__` reports as `UnpricedSymbol` (no stored bar at all) or `ValueError` (no
    session inside the window). Both, and anything else `SessionCalendar` might raise reading the
    store, are caught broadly here rather than narrowly, matching this module's "a panel that cannot
    be computed degrades, it does not take the page down" rule (see `_group_rejections`'s docstring
    and this application's own recorded incident over exactly that failure mode elsewhere).
    """
    start = book.card_adopted_date
    filled_dates = [
        order.fill_date
        for order in book.orders
        if order.status == "filled" and order.fill is not None
    ]
    if filled_dates:
        start = min(start, min(filled_dates))
    start = min(start, as_of)

    try:
        calendar = SessionCalendar(start=start, end=as_of, settings=settings, benchmark=benchmark)
    except Exception:
        logger.warning(
            "autopilot: could not build a session calendar for %s..%s; curve degrading to ()",
            start.isoformat(),
            as_of.isoformat(),
            exc_info=True,
        )
        return ()
    return tuple(session.date for session in calendar)


# ---------------------------------------------------------------------------
# Equity curve -- built from the book's own fills, never from BookState.equity_curve
# ---------------------------------------------------------------------------


def _equity_curve(
    book: BookState, *, settings: Settings, session_dates: tuple[dt.date, ...]
) -> tuple[list[Decimal], list[bool]]:
    """One `(equity, in_position)` pair per session in `session_dates` on which every symbol still
    held can be priced -- built by walking `book.orders`' own filled fills forward in `(fill_date,
    order_id)` order, the identical algorithm `app.workflow.book.mark_equity_through` uses and for the
    identical reason (see that function's docstring): replaying `PaperBroker.from_state(book.
    broker_state)` at successively earlier `as_of` dates would not reconstruct history, it would just
    re-price *today's* holdings under an earlier label, because the broker's state blob carries no
    memory of what it held on any prior date. This function is not reused directly because it reads
    its own session list from the stored SPY history rather than accepting `session_dates` from a
    caller who has already resolved the seat's own window (see `_curve_sessions`), and because it
    persists a new `BookState` this read path must never write.

    **A session where any held symbol cannot be priced is dropped from the curve entirely** -- no
    point is appended for it, rather than one carrying a partial or fabricated figure. This is the same
    rule `app.workflow.book_models.EquityPoint.equity`'s own docstring states for the identical
    situation: an unpriced holding makes that day's equity unknown, not wrong.
    """
    filled_orders = sorted(
        (order for order in book.orders if order.status == "filled" and order.fill is not None),
        key=lambda order: (order.fill_date, order.order_id),
    )

    equity_points: list[Decimal] = []
    in_position_flags: list[bool] = []
    order_idx = 0
    cash = book.starting_cash
    quantities: dict[str, Decimal] = {}

    for session_date in session_dates:
        while order_idx < len(filled_orders) and filled_orders[order_idx].fill_date <= session_date:
            order = filled_orders[order_idx]
            fill = order.fill
            assert fill is not None
            if order.side == "buy":
                cash -= fill.qty * fill.price + fill.fees
                quantities[order.symbol] = quantities.get(order.symbol, Decimal(0)) + fill.qty
            else:
                cash += fill.qty * fill.price - fill.fees
                quantities[order.symbol] = quantities.get(order.symbol, Decimal(0)) - fill.qty
            order_idx += 1

        market = AsOfMarket(as_of=session_date, settings=settings)
        total = cash
        fully_priced = True
        held_now = False
        for symbol, quantity in quantities.items():
            if quantity <= 0:
                continue
            held_now = True
            try:
                close = market.close(symbol)
            except (UnpricedSymbol, FileNotFoundError):
                fully_priced = False
                break
            total += quantity * close

        if fully_priced:
            equity_points.append(total)
            in_position_flags.append(held_now)

    return equity_points, in_position_flags


def _drawdown_and_exposure(
    equity_points: list[Decimal], in_position_flags: list[bool]
) -> tuple[Decimal, float | None]:
    """`(max_drawdown, capital_exposure)` off `_equity_curve`'s own output, via
    `app.backtest.metrics.compute` -- the one implementation of drawdown this codebase has.

    Fewer than two points means there is no path to draw a drawdown over at all (a single mark is not
    a curve), so this returns the flat `Decimal("0")`/`None` pair directly rather than handing
    `compute` a one-point series it would have to special-case identically. `compute` is always called
    with `annualisable=False`: this window is anywhere from a few days to a few months old, far short
    of the one-year floor every annualised statistic in that module already refuses below (see its own
    docstring) -- and neither figure this function actually reads (`max_drawdown`, `exposure`) is one
    of the four annualised ones anyway, so the flag changes nothing about what is returned, only
    documents that this call was never entitled to CAGR/Sharpe/Sortino/volatility in the first place.
    `trades=()` for the same reason: `compute`'s `max_drawdown`/`exposure` are computed purely from
    `equity`/`in_position`, never from `trades` (see that function's own body), so no reconstructed
    `app.backtest.models.Trade` sequence is needed to get either figure -- and `Desk.trades` below is
    built independently, off the book's fills directly, precisely because it needs a different shape
    (`app.paperdesk.models.Trade`) that `compute` does not produce.
    """
    if len(equity_points) < 2:
        return Decimal("0"), None

    base = equity_points[0]
    if base == 0:
        return Decimal("0"), None

    equity_array = np.array([float(point / base) for point in equity_points], dtype=np.float64)
    in_position_array = np.array(in_position_flags, dtype=np.bool_)
    strategy_metrics = metrics_mod.compute(
        equity_array,
        in_position=in_position_array,
        trades=(),
        bars_per_year=BARS_PER_YEAR[Interval.DAY],
        annualisable=False,
    )
    max_drawdown = (
        Decimal(str(strategy_metrics.max_drawdown))
        if strategy_metrics.max_drawdown is not None
        else Decimal("0")
    )
    return max_drawdown, strategy_metrics.exposure


# ---------------------------------------------------------------------------
# Holdings -- FIFO lots from the book's own fills, marked fresh at as_of
# ---------------------------------------------------------------------------


def _holdings(
    book: BookState,
    *,
    settings: Settings,
    as_of: dt.date,
    session_dates: tuple[dt.date, ...],
    card: StrategyCard | None,
) -> list[Holding]:
    """Every still-open lot in `book`, marked fresh at `as_of` -- one :class:`Holding` per FIFO lot
    `app.workflow.book.held_lots` returns, not one per symbol, matching that function's own contract
    (its docstring: "one per surviving buy fill").

    **`stop_price`/`target_price`/`sessions_to_time_stop` are derived from `card`, the selected
    strategy card, exactly as `app.paperdesk.desk._holdings` derives them for a rules desk** --
    `entry_price * (1 - stop_loss_pct)`, `entry_price * (1 + take_profit_pct)`, and
    `max_hold_days - bars_held`. These were `None` on every row until the exit path existed, on the
    honest grounds that the workflow applied no risk control; `app.workflow.exits` now applies exactly
    these three (plus the card's `exit` rule) once a session, so the levels a position would actually
    close at are real and belong on the row. A field stays `None` only when the card declares that
    mechanism as `None`, or when no card resolves at all -- never invented.

    A lot whose symbol cannot be priced at `as_of` is skipped from the returned list entirely -- never
    marked at a fabricated price. `weight` is left `0.0` on every row here and filled in by the caller
    once the desk's own `equity` (from `PaperBroker.mark`, not summed from these rows) is known -- the
    same two-pass shape `app.paperdesk.desk._build_desk` uses for its own holdings, for the identical
    reason: `weight` needs the total before any one row can compute its own share of it.
    """
    market = AsOfMarket(as_of=as_of, settings=settings)
    rows: list[Holding] = []
    for lot in book_mod.held_lots(book):
        try:
            last_price = market.close(lot.symbol)
        except (UnpricedSymbol, FileNotFoundError):
            logger.info(
                "autopilot: %s has no stored close at or before %s; dropping this lot from holdings",
                lot.symbol,
                as_of.isoformat(),
            )
            continue

        history = market.history(lot.symbol, lookback_days=10)
        last_price_date = history["ts"].iloc[-1].date() if not history.empty else as_of

        entry_price = lot.cost_basis / lot.quantity if lot.quantity != 0 else Decimal(0)
        market_value = _money(last_price * lot.quantity)
        unrealised_pnl = market_value - lot.cost_basis
        return_pct = (unrealised_pnl / lot.cost_basis) if lot.cost_basis != 0 else Decimal(0)
        bars_held = _bars_between(lot.acquired_date, as_of, session_dates)

        stop_price = (
            _money(entry_price * (Decimal(1) - card.stop_loss_pct))
            if card is not None and card.stop_loss_pct is not None
            else None
        )
        target_price = (
            _money(entry_price * (Decimal(1) + card.take_profit_pct))
            if card is not None and card.take_profit_pct is not None
            else None
        )
        sessions_to_time_stop = (
            card.max_hold_days - bars_held
            if card is not None and card.max_hold_days is not None
            else None
        )

        rows.append(
            Holding(
                symbol=lot.symbol,
                quantity=lot.quantity,
                entry_date=lot.acquired_date,
                entry_price=entry_price,
                cost_basis=lot.cost_basis,
                last_price=last_price,
                last_price_date=last_price_date,
                market_value=market_value,
                unrealised_pnl=unrealised_pnl,
                return_pct=return_pct,
                bars_held=bars_held,
                weight=0.0,
                stop_price=stop_price,
                target_price=target_price,
                sessions_to_time_stop=sessions_to_time_stop,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Closed trades -- FIFO sell-side walk, correct today even though it fires on nothing
# ---------------------------------------------------------------------------


@dataclass
class _FifoLot:
    """One open buy lot, mutated in place as sells retire it -- purely local bookkeeping for
    `_closed_trades`, mirroring `app.workflow.book.held_lots`'s own private `_OpenLot`."""

    quantity: Decimal
    price: Decimal
    acquired_date: dt.date


def _closed_trades(book: BookState, *, session_dates: tuple[dt.date, ...]) -> list[Trade]:
    """Every closed round trip in `book`, FIFO -- the sell-side counterpart to `app.workflow.book.
    held_lots`'s buy-side walk, reimplemented locally rather than imported because `held_lots` only
    ever returns what is *still open*; the partial or full lot closure a sell produces is exactly the
    information that function discards once it has used it to retire the oldest lots (see its own
    docstring: "the sell-reduction is here so the helper stays correct if exits are ever staged").

    **The workflow stages buys only today** (see `AutopilotDescription.exits`), so this returns `[]`
    for every book on disk right now. It is still written the same way the buy-side walk is -- FIFO,
    in `(fill_date, order_id)` order -- so that the day an exit is staged, this desk's `trades` panel
    is correct on first render rather than needing a second pass once the workflow grows an exit path.

    `exit_reason` is stamped the literal string `"workflow"` rather than one of the four bracket codes
    (`"rule"`/`"stop"`/`"target"`/`"time"`) `Trade.exit_reason`'s own docstring lists for a rules-card
    desk: none of those describe how this seat would actually close a position (a fresh model
    judgement, not a mechanical trigger evaluated against a bracket), and reusing one of the four would
    claim a rule this seat does not have. `Trade.exit_reason` is typed `str`, not the closed
    :class:`~app.backtest.models.ExitReason` enum, specifically so a fifth reason like this one can be
    added without widening a `Literal` -- see this application's own recorded incident with a throwing
    exhaustiveness check over a server-supplied string (`app.paperdesk.models.DeskRejection`'s
    docstring cites the same lesson).
    """
    open_lots: dict[str, list[_FifoLot]] = {}
    trades: list[Trade] = []
    filled_orders = sorted(
        (order for order in book.orders if order.status == "filled" and order.fill is not None),
        key=lambda order: (order.fill_date, order.order_id),
    )

    for order in filled_orders:
        fill = order.fill
        assert fill is not None
        if order.side == "buy":
            open_lots.setdefault(order.symbol, []).append(
                # `order.fill_date`, the trading session, never `fill.filled_at` -- that field is a
                # wall-clock stamp for when the fill was *written*, and its own docstring says so.
                # Using it here dated every position to the day the daily step last ran, which on a
                # backfilled book means every lot claims the same entry date and a `bars_held` of
                # zero. `app.workflow.book.held_lots` had the identical bug; both are fixed.
                _FifoLot(quantity=fill.qty, price=fill.price, acquired_date=order.fill_date)
            )
            continue

        remaining = fill.qty
        lots = open_lots.get(order.symbol, [])
        exit_date = order.fill_date
        while remaining > 0 and lots:
            lot = lots[0]
            closed_qty = min(lot.quantity, remaining)
            cost_basis = _money(lot.price * closed_qty)
            proceeds = _money(fill.price * closed_qty)
            pnl = proceeds - cost_basis
            return_pct = (pnl / cost_basis) if cost_basis != 0 else Decimal(0)
            trades.append(
                Trade(
                    symbol=order.symbol,
                    entry_date=lot.acquired_date,
                    entry_price=lot.price,
                    exit_date=exit_date,
                    exit_price=fill.price,
                    quantity=closed_qty,
                    exit_reason="workflow",
                    pnl=pnl,
                    return_pct=return_pct,
                    bars_held=_bars_between(lot.acquired_date, exit_date, session_dates),
                )
            )
            lot.quantity -= closed_qty
            remaining -= closed_qty
            if lot.quantity <= 0:
                lots.pop(0)
        if not lots:
            open_lots.pop(order.symbol, None)

    return trades


# ---------------------------------------------------------------------------
# Decisions -- one per filled order
# ---------------------------------------------------------------------------


def _decision_reason(order: WorkflowOrderRecord) -> str:
    """A human sentence naming the regime and the arm this order was staged under -- the autopilot's
    equivalent of a rules-card `Decision.reason` ("exit rule fired", "stop loss hit"), built from the
    two facts a workflow order actually carries about why it exists (`WorkflowOrderRecord.arm`,
    `.regime`) rather than a rule expression it has none of."""
    if order.regime:
        return f"staged by the {order.arm} arm under regime {order.regime}"
    return f"staged by the {order.arm} arm under no recorded regime"


def _decisions(book: BookState) -> list[Decision]:
    """One :class:`Decision` per **filled** order, oldest first -- the workflow's counterpart to
    `app.paperdesk.desk._decisions`, which likewise only ever shows a decision that resulted in a
    fill (a pending order is a :class:`AutopilotOrder`, not a `Decision` -- see that class's own
    docstring for why the two are deliberately different shapes)."""
    rows: list[Decision] = []
    for order in book.orders:
        if order.status != "filled" or order.fill is None:
            continue
        fill = order.fill
        rows.append(
            Decision(
                date=order.fill_date,
                symbol=order.symbol,
                action="enter" if order.side == "buy" else "exit",
                reason=_decision_reason(order),
                price=fill.price,
                quantity=fill.qty,
                notional=_money(fill.price * fill.qty),
            )
        )
    rows.sort(key=lambda decision: (decision.date, decision.symbol))
    return rows


# ---------------------------------------------------------------------------
# Rejections -- grouped by a slug recovered from the stored free-text reason
# ---------------------------------------------------------------------------


def _rejection_slug(reason: str) -> str:
    """A stable grouping slug for one rejected order's free-text `reject_reason`.

    `WorkflowOrderRecord` never stores the mandate rule slug `PaperBroker._reject` originally assigned
    -- `execute_pending` copies `Rejection.reason` onto `reject_reason`, not `Rejection.rule` (see
    `app.workflow.book.execute_pending`'s own body) -- so the slug has to be recovered from the
    sentence itself. Every keyword check below is matched against the exact phrasing
    `PaperBroker._check_buy`/`_check_sell`/`_precheck` and `execute_pending`'s own pricing-failure
    branch produce (see `app.paper.paperbroker`), in order from most to least specific; a reason this
    application has never actually written falls through to the generic `"rejected"` slug rather than
    being guessed at from a pattern nothing here has verified.
    """
    lowered = reason.lower()
    if "minimum clip" in lowered:
        return "min_clip"
    if "maximum" in lowered and "position" in lowered:
        return "max_positions"
    if "settled cash" in lowered:
        return "insufficient_cash"
    if "% of the book against a" in lowered:
        return "max_single_name_weight"
    if "shorting" in lowered:
        return "no_short"
    if (
        "no stored close" in lowered
        or "no stored open" in lowered
        or "no close on" in lowered
        or "no live quote" in lowered
    ):
        return "unpriceable"
    if "quantity must be greater than zero" in lowered:
        return "non_positive_quantity"
    if "fractional" in lowered:
        return "fractional_shares"
    if "without a thesis" in lowered:
        return "missing_thesis"
    if "without a written invalidation" in lowered:
        return "missing_invalidation"
    return "rejected"


def _group_rejections(orders: tuple[WorkflowOrderRecord, ...]) -> tuple[list[DeskRejection], int]:
    """Collapse every `"rejected"` order in `orders` into one :class:`DeskRejection` per slug --
    the autopilot's counterpart to `app.paperdesk.desk._group_rejections`, reimplemented locally
    (rather than imported) because that function groups by the mandate's own rule slug, which this
    book's records do not carry (see `_rejection_slug`'s own docstring for why). Sorted by `count`
    descending then `rule` ascending, `detail` capped at `_MAX_REJECTION_DETAIL` newest-first -- both
    match `DeskRejection`'s own documented contract exactly, so a client cannot tell which desk module
    produced a given group from its shape alone.
    """
    groups: dict[str, dict[str, Any]] = {}
    for order in orders:
        if order.status != "rejected":
            continue
        slug = _rejection_slug(order.reject_reason)
        group = groups.setdefault(slug, {"count": 0, "symbols": set(), "detail": []})
        group["count"] += 1
        group["symbols"].add(order.symbol)
        group["detail"].append(order.reject_reason or rejection_label(slug))

    rows = [
        DeskRejection(
            rule=slug,
            label=rejection_label(slug),
            count=group["count"],
            symbols=sorted(group["symbols"]),
            detail=list(reversed(group["detail"]))[:_MAX_REJECTION_DETAIL],
        )
        for slug, group in groups.items()
    ]
    rows.sort(key=lambda rejection: (-rejection.count, rejection.rule))
    total = sum(rejection.count for rejection in rows)
    return rows, total


# ---------------------------------------------------------------------------
# Provenance -- what the seat is, and what its most recent workflow run did
# ---------------------------------------------------------------------------


def _run_outcome(run: DeskRun, *, staged_this_run: int) -> str | None:
    """One sentence on what `run` actually did -- see `AutopilotDescription.last_run_outcome`'s own
    docstring for why this is "the field that keeps a flat panel honest".

    **A run that staged nothing must report the *cause*, not the tally.** This is the whole point of
    the field and it is the one case that is easy to get subtly wrong. The workflow's last stage
    always succeeds and always writes a per-arm count, so the naive "read the final stage's summary"
    rule reports `"raw_signal=0; full_workflow=0"` on exactly the day a reader most needs an
    explanation -- a true sentence that answers a question nobody asked, in the pipeline's own
    vocabulary, while the actual reason (`"no entry candidates fired"`) sits unread on a skipped stage
    two rows above it. `staged_this_run` is how the two cases are told apart: it is the number of
    orders in *this seat's own book* that this run created, so when it is zero we look for the reason
    the pipeline stopped rather than the count of what it did not do.

    The earliest skipped stage's reason is preferred over later ones because the later skips are
    normally consequences of the same cause -- both research stages skip for the one reason the scan
    found nothing -- and the first one names it.

    Order, then: the run's own top-level `error` (set exactly when the run failed outright) always
    wins. Then, when this run staged nothing, the earliest skipped stage's reason. Otherwise the last
    stage that reached a terminal state, its `error` preferred over its `summary` -- a `"blocked"` or
    `"failed"` stage names what happened in `error` and may carry no `summary` at all. Stages still
    `"pending"` are passed over: a run that stopped early leaves its later stages never started, and
    reporting one of those would show "pending" for a run that is actually finished.
    """
    if run.error:
        return run.error

    if staged_this_run == 0:
        for stage in run.stages:
            if stage.state == "skipped" and stage.error:
                return stage.error

    terminal_stage = None
    for stage in reversed(run.stages):
        if stage.state != "pending":
            terminal_stage = stage
            break

    if terminal_stage is not None:
        if terminal_stage.error:
            return terminal_stage.error
        if terminal_stage.summary:
            return terminal_stage.summary

    if run.state in ("queued", "running"):
        # A non-terminal run has no outcome yet -- the newest run in the store can be one another
        # session just launched and has not finished. Say so plainly rather than "the run running
        # with nothing further recorded", which reads as a stuck run even when it is merely in flight.
        return "the last run is still in progress"
    return f"the run {run.state} with nothing further recorded"


def _load_card(agent_id: str, *, settings: Settings) -> StrategyCard | None:
    """The selected card, or `None` when `agent_id` names no `StrategyCard`.

    A local copy of `app.workflow.exits._load_card`, not a shared import -- this repo's documented
    convention for this exact situation (see that module's own docstring, and `app.workflow.replay`/
    `.pipeline`/`.regime`, which each carry the identical rglob rather than reach across a package
    boundary for it). `None` covers the same three ordinary cases that function's docstring lists: an
    empty `current_card_id` (a book seeded but never traded), an id that resolves to a ladder or
    allocation card, and a genuinely missing file -- none of them an error this description should
    fail on.
    """
    if not agent_id:
        return None
    for path in sorted(settings.library_dir.rglob(f"{agent_id}.json")):
        try:
            return StrategyCard.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
    return None


def _format_pct(value: Decimal) -> str:
    """`Decimal("0.12")` -> `"12"`, `Decimal("0.125")` -> `"12.5"` -- a fraction-of-one read as a bare
    percentage number (the caller appends the `%` sign), trailing zeros and a bare trailing point
    stripped so a round figure like the stop above reads `"12%"` rather than `"12.00%"`. `format(...,
    "f")` rather than `Decimal.normalize()` deliberately: `normalize()` on a whole-number `Decimal` can
    fall back to scientific notation (`Decimal("1200.00").normalize()` is `Decimal("1.2E+3")`), which
    is correct arithmetic but not a sentence a reader should see.
    """
    scaled = (value * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = format(scaled, "f").rstrip("0").rstrip(".")
    return text or "0"


def _join_sentence(parts: list[str]) -> str:
    """`["a"]` -> `"a"`, `["a", "b"]` -> `"a and b"`, `["a", "b", "c"]` -> `"a, b, and c"` -- the
    connector `_exits_policy` needs for a card that declares two or more exit mechanisms at once, so
    "12% stop, 120-session hold cap, and exit rule ema(20) crosses_below ema(50)" reads as one sentence
    rather than a bare comma-joined fragment list."""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def _exits_policy(book: BookState, *, settings: Settings) -> str:
    """`AutopilotDescription.exits` -- see that field's own docstring for the two shapes a renderer
    must handle. Derived from the `StrategyCard` named by `book.current_card_id` rather than left
    hardcoded, because as of `app.workflow.exits` this seat's positions genuinely can close: that
    module evaluates the selected card's own stop, take-profit, hold cap and `exit` expression once a
    session, in precisely the precedence named below, and stages a sell filled at the next open. A
    description that still said `"none"` after that module existed would misstate this seat's own
    return the same way a callout claiming "this desk only ever buys" already did before it was
    corrected -- the seat's exposure is not its universe's beta once any of these can fire.

    Named in `app.tournament.runner._decide_exit`'s own precedence -- stop, then take-profit, then
    hold cap, then the rule expression -- because that is the order in which they are actually
    evaluated (`app.workflow.exits._bracket_reason`, then the rule check in `plan_exits`), not because
    the sentence needs an order at all; naming them in evaluation order rather than field-declaration
    order is the more honest sentence when a reader asks "what actually decides the exit".

    Collapses to the literal `"none"` in two cases the field's own docstring both requires: a card
    that declares no stop, no take-profit, no hold cap and no (non-blank) exit expression -- nothing
    would ever close the position even though a card resolved -- and a book where no card resolves at
    all (`current_card_id` empty, or naming a file `_load_card` cannot read as a `StrategyCard`) --
    nothing can be evaluated, so nothing can be said to fire. Both states are indistinguishable to a
    reader deciding whether to trust this seat's return as more than beta, which is exactly what
    `"none"` is defined to mean.

    **Never raises.** A card file that exists but cannot be parsed is caught inside `_load_card`
    itself (it treats a `ValueError` there as "this file is not this card", matching `app.workflow.
    exits._load_card`'s own contract); this function additionally wraps the whole lookup so a defect
    in `library_dir.rglob` or the settings object degrades the same way every other optional block in
    this module does -- logged, and `"none"`, never a 500 over one seat's provenance panel.
    """
    try:
        card = _load_card(book.current_card_id, settings=settings)
    except Exception:
        logger.warning(
            "autopilot: could not load card %r while describing exits; exits degrading to 'none'",
            book.current_card_id,
            exc_info=True,
        )
        return "none"

    if card is None:
        return "none"

    parts: list[str] = []
    if card.stop_loss_pct is not None:
        parts.append(f"{_format_pct(card.stop_loss_pct)}% stop")
    if card.take_profit_pct is not None:
        parts.append(f"{_format_pct(card.take_profit_pct)}% take-profit")
    if card.max_hold_days is not None:
        parts.append(f"{card.max_hold_days}-session hold cap")
    if card.exit.strip():
        parts.append(f"exit rule {card.exit.strip()}")

    if not parts:
        return "none"
    return _join_sentence(parts)


def _autopilot_description(book: BookState, *, settings: Settings) -> AutopilotDescription:
    """The seat's own provenance block -- see :class:`AutopilotDescription`'s own docstring for why
    this exists as a separate block rather than force-fitting a rule expression this desk does not
    have. `last_run_*` come from the newest `"workflow"` run in `app.agentdesk.store.RunStore`, never
    from the book itself (the book knows what was staged and filled; only the run store knows what the
    pipeline that staged it actually did, including the runs that staged nothing at all)."""
    orders_total = len(book.orders)
    orders_filled = sum(1 for order in book.orders if order.status == "filled")
    orders_pending = sum(1 for order in book.orders if order.status == "pending")
    orders_rejected = sum(1 for order in book.orders if order.status == "rejected")

    last_run_id: str | None = None
    last_run_state: str | None = None
    last_run_at: str | None = None
    last_run_outcome: str | None = None
    try:
        runs = RunStore(settings, "workflow").list_runs(limit=1)
        if runs:
            run = runs[0]
            last_run_id = run.run_id
            last_run_state = run.state
            last_run_at = run.created_at.isoformat()
            # Counted against this seat's own book, not the run's own record of what it staged: the
            # run stages into several arms at once and only one of them is this seat. A run that
            # filled another arm's book and left this one empty is, from this panel's point of view,
            # a run that staged nothing -- and it is this panel that has to explain why it is flat.
            last_run_outcome = _run_outcome(
                run,
                staged_this_run=sum(
                    1 for order in book.orders if order.created_by_run_id == run.run_id
                ),
            )
    except Exception:
        logger.warning(
            "autopilot: could not read the workflow run store; last_run_* degrading to None",
            exc_info=True,
        )

    source, arm = _resolve_source(settings)
    return AutopilotDescription(
        arm=arm,
        universe_source=source,
        current_card_id=book.current_card_id,
        card_adopted_date=book.card_adopted_date,
        orders_total=orders_total,
        orders_filled=orders_filled,
        orders_pending=orders_pending,
        orders_rejected=orders_rejected,
        last_run_id=last_run_id,
        last_run_state=last_run_state,
        last_run_at=last_run_at,
        last_run_outcome=last_run_outcome,
        exits=_exits_policy(book, settings=settings),
    )


# ---------------------------------------------------------------------------
# The public entry point
# ---------------------------------------------------------------------------

_THESIS = (
    "This seat trades the Agent Workflow's own staged orders -- a persistent ledger of model "
    "judgements (a regime call, a strategy-card selection, a screened candidate list, a debate, a "
    "gate verdict) recorded the day each order was decided, not a rule replayed fresh against stored "
    "bars the way every other desk on this page is. Its positions are therefore not reproducible from "
    "price history alone: what is shown here is exactly what the workflow committed to, when it "
    "committed to it, read off the ledger rather than recomputed. Its entries are judged; its exits "
    "are mechanical -- a position is closed by the selected card's own stop, take-profit, hold cap or "
    "exit rule, evaluated once a session and filled at the next open. See this seat's stated exit "
    "policy for the rules actually in force."
)


def build_desk(
    settings: Settings,
    *,
    as_of: dt.date,
    benchmark: str,
    mandate: Mandate,
    taxable: bool,
) -> Desk:
    """The autopilot seat as a :class:`~app.paperdesk.models.Desk`, read entirely from `app.workflow.
    book`'s persisted ledger and the workflow run store -- see this module's own docstring for why a
    ledger, not a bar replay.

    `benchmark` is this application's SPY-keyed trading calendar (`app.paperdesk.desk` passes `"SPY"`,
    the same symbol every other desk's own `SessionCalendar` is built against) -- used only to resolve
    which dates are real trading sessions for this seat's own equity curve and `bars_held` figures
    (see `_curve_sessions`), never to price a position; every price this function reads comes from
    `AsOfMarket`/`PaperBroker` against the traded symbol itself.

    A missing book file is not an error: `book_mod.load_book` returns a freshly seeded, empty
    `BookState` for it, and this function renders that as a dormant $100,000 seat with no holdings, no
    trades and no orders -- exactly the honest state `docs/AUTOPILOT-CARD-PLAN.md` section 2.2
    describes. A book file that exists but cannot be parsed is *not* caught here: `load_book` raises
    `ValueError` for it, and that propagates to this function's own caller, which is where the
    "log it, turn it into a book note, never 500 the page over one seat" isolation this application
    already applies to every other desk belongs -- duplicating that catch inside this function would
    only hide the distinction between "this book is dormant" and "this book is broken" from whoever
    reads the log.
    """
    source, arm = _resolve_source(settings)
    book = book_mod.load_book(
        settings,
        arm,
        starting_cash=AUTOPILOT_STARTING_CASH,
        card_id="",
        universe_source=source,
    )

    broker = PaperBroker.from_state(mandate, book.broker_state)
    market = AsOfMarket(as_of=as_of, settings=settings)
    positions_value, _marks = broker.mark(market)
    cash = broker.cash
    equity = cash + positions_value

    session_dates = _curve_sessions(book, settings=settings, benchmark=benchmark, as_of=as_of)

    # The selected card, loaded once here and threaded into `_holdings` for its per-row stop/target/
    # time-stop levels. `None` when no card resolves (a seeded-but-untraded book, or an id naming no
    # `StrategyCard`), in which case every bracket field stays `None` -- the same degrade `_holdings`
    # and `_exits_policy` already make. `_exits_policy` loads its own copy rather than sharing this
    # one, keeping that function self-contained; a second rglob for one card is negligible against the
    # book replay and market reads this build already performs.
    card = _load_card(book.current_card_id, settings=settings)
    holdings = _holdings(
        book, settings=settings, as_of=as_of, session_dates=session_dates, card=card
    )
    holdings = [
        holding.model_copy(
            update={"weight": float(holding.market_value / equity) if equity > 0 else 0.0}
        )
        for holding in holdings
    ]
    open_positions = len(holdings)
    unrealised_pnl = _money(sum((holding.unrealised_pnl for holding in holdings), Decimal(0)))

    closed_trades = _closed_trades(book, session_dates=session_dates)
    realised_pnl = _money(sum((trade.pnl for trade in closed_trades), Decimal(0)))

    equity_points, in_position_flags = _equity_curve(book, settings=settings, session_dates=session_dates)
    max_drawdown, capital_exposure = _drawdown_and_exposure(equity_points, in_position_flags)

    starting_equity = book.starting_cash
    total_return = (equity / starting_equity) - Decimal(1)

    staged_orders = [
        AutopilotOrder(
            symbol=order.symbol,
            side=order.side,
            notional=order.notional,
            decision_date=order.decision_date,
            fill_date=order.fill_date,
            regime=order.regime,
        )
        for order in book.orders
        if order.status == "pending"
    ]

    rejections, rejection_count = _group_rejections(book.orders)

    tax = None
    if taxable:
        try:
            tax = book_mod.tax_summary(book, settings=settings)
        except Exception:
            logger.warning(
                "autopilot: tax summary failed for the %s/%s book; leaving tax=None",
                arm,
                source,
                exc_info=True,
            )
            tax = None

    universe = tuple(sorted({order.symbol for order in book.orders}))
    max_positions = mandate.max_positions
    slots_free = max(0, max_positions - open_positions)

    return Desk(
        agent_id=AUTOPILOT_AGENT_ID,
        display_name=AUTOPILOT_DISPLAY_NAME,
        discipline=AUTOPILOT_DISCIPLINE,
        thesis=_THESIS,
        kind="autopilot",
        universe=list(universe),
        entry=None,
        exit=None,
        stop_loss_pct=None,
        take_profit_pct=None,
        max_hold_days=None,
        max_positions=max_positions,
        position_pct=None,
        rank_by=None,
        staged_orders=staged_orders,
        autopilot=_autopilot_description(book, settings=settings),
        ladder=None,
        starting_equity=starting_equity,
        cash=cash,
        positions_value=positions_value,
        equity=equity,
        total_return=total_return,
        excess_return=None,
        max_drawdown=max_drawdown,
        capital_exposure=capital_exposure,
        realised_pnl=realised_pnl,
        unrealised_pnl=unrealised_pnl,
        open_positions=open_positions,
        slots_free=slots_free,
        holdings=holdings,
        trades=closed_trades,
        decisions=_decisions(book),
        signals=[],
        rejections=rejections,
        rejection_count=rejection_count,
        live_fills=[],
        live_rejections=[],
        live_as_of=None,
        tax=tax,
    )

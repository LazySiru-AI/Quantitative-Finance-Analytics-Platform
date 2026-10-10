"""The persistent per-arm paper trade ledger: stage on day N, fill at day N+1's open, tax on request.

See `app.workflow.book_models`'s module docstring for *why* this ledger is written to disk at all
(short version: an agent's judgement is not a pure function of price history the way a mechanical
card's is, so `app.paperdesk`'s replay-from-bars trick cannot reproduce it -- the order has to be
recorded the day it is decided). This module is the read/write/execute layer over that shape.

**Nothing here re-implements a fill, a fee, a slippage model, a lot, a wash sale, or a gain.** Every
one of those already exists (`app.paper.paperbroker.PaperBroker`, `app.paper.papertax`), is exercised
by its own tests, and disagreeing with it here would make the workflow arms incomparable with the rest
of the programme -- see `app.workflow`'s own module docstring. This module's whole job is to drive
those two engines correctly across process restarts: convert a dollar-sized plan into a priceable
`Order` (`execute_pending`'s one piece of real work, since `PaperBroker.Order` wants a share count and
a workflow plan only ever states a notional -- see `OrderPlan.notional`'s docstring for why that
conversion cannot happen any earlier than fill time), persist the broker's own state blob verbatim
between calls, and hand `PaperBroker.fills` on to the real tax engine unmodified.

**Every function below that returns a `BookState` returns a new one.** `BookState` is frozen (see
`app.workflow.book_models`), so "stage an order" and "execute a fill" are both `old_state ->
new_state` transformations, never in-place mutation -- the same discipline `app.agentdesk.store`
applies to `DeskRun`, for the same reason: a caller holding a reference to the old state before a
transformation keeps looking at a complete, consistent one after it, and the caller decides when (or
whether) to call `save_book` on the result.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Literal

from app.agentdesk.models import agentdesk_dir
from app.config import Settings
from app.market import store as market_store
from app.market.live import LiveQuoteSource
from app.market.models import Interval
from app.paper.marketdata import AsOfMarket, UnpricedSymbol
from app.paper.paperbroker import Fill, Mandate, Order, PaperBroker, Rejection
from app.paper.papertax import PaperTaxSummary, resolve_configured_rates, summarize_paper_tax
from app.workflow.book_models import (
    BOOK_SCHEMA_VERSION,
    BookState,
    EquityPoint,
    OrderPlan,
    WorkflowArm,
    WorkflowFillRecord,
    WorkflowOrderRecord,
)

__all__ = [
    "ExecuteOutcome",
    "HeldLot",
    "book_path",
    "execute_pending",
    "held_lots",
    "load_book",
    "mark_equity_through",
    "save_book",
    "snapshot_equity",
    "stage_orders",
    "tax_summary",
]

logger = logging.getLogger(__name__)

_CENTS = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    """Round to cents, half-up -- only ever used here to derive an audit-only `Fill.gross`/
    `cash_delta` for `tax_summary`'s synthetic ledger (see `_order_to_fill`). This is *not* the fee or
    slippage model; those numbers (`WorkflowFillRecord.price`, `.fees`, `.slippage`) already came out
    of `PaperBroker` verbatim and are never recomputed here."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _notify_order(
    settings: Settings, record: WorkflowOrderRecord, *, fill: WorkflowFillRecord | None
) -> None:
    """Announce one executed order through `app.notify`.

    Called after the record has already been replaced with its outcome, never before: the ledger is
    the thing that matters and a notification is a side effect of it. The whole body is wrapped so a
    notify defect (an unwritable `data/notify/`, a channel that hangs) can only cost a log line --
    `execute_pending` performs no file I/O of its own and must stay able to return its `BookState`.

    Both outcomes are `notable` rather than a fill being quieter than a rejection: an autopilot order
    that did *not* fill is exactly as much news as one that did, and the headline prefix -- not the
    severity -- is what tells the two apart on a lock screen. `dedupe_id` carries the order id and its
    terminal status, so re-running `execute_pending` over an already-executed book (which cannot
    re-execute a non-`"pending"` order anyway) could never double-announce one.
    """
    try:
        from app.notify import emit

        status = record.status
        side = record.side.upper()
        if fill is not None:
            headline = f"Autopilot filled {side} {fill.qty} {record.symbol} @ {fill.price}"
            detail = record.thesis
        else:
            headline = f"Rejected: {side} {record.symbol} ({record.arm})"
            detail = record.reject_reason
        emit(
            settings,
            kind="paper.fill",
            severity="notable",
            headline=headline,
            detail=detail,
            refs=(f"symbol:{record.symbol}", f"order:{record.order_id}"),
            source="workflow.book",
            dedupe_id=f"paper.fill:workflow:{record.order_id}:{status}",
        )
    except Exception:
        logger.exception(
            "workflow: notify hook failed for order %s; the order itself is recorded",
            record.order_id,
        )


def _quantity_for_notional(notional: Decimal, price: Decimal, *, allow_fractional: bool) -> Decimal:
    """Convert a dollar-sized plan into a share count against `price` -- the one piece of sizing math
    this package owns, because `PaperBroker.Order.quantity` is a share count and nothing upstream of
    here (`OrderPlan`) ever names a price.

    Floors to a whole share when the mandate forbids fractional shares, matching `PaperBroker.
    _precheck`'s own fractional-share rule: a broker that rejects `10.5` shares must never be handed a
    calculated `10.5` by this function, or every whole-share mandate would refuse every workflow order.
    A `price <= 0` (never produced by `AsOfMarket.close` in practice, but defensive against a caller
    that somehow reaches this with one) returns zero rather than dividing -- `PaperBroker._precheck`'s
    `non_positive_quantity` rule then rejects it exactly as it would any other non-positive quantity.
    """
    if price <= 0:
        return Decimal(0)
    raw = notional / price
    return raw if allow_fractional else raw.to_integral_value(rounding=ROUND_DOWN)


# ---------------------------------------------------------------------------
# Location and persistence
# ---------------------------------------------------------------------------


def book_path(
    settings: Settings, arm: WorkflowArm, *, universe_source: Literal["card", "screen"] = "card"
) -> Path:
    """`data/agentdesk/workflow/book/<arm>.json` for `universe_source="card"` (the default, and the
    exact unchanged path every existing caller keeps getting without passing the new keyword at all).
    `data/agentdesk/workflow/book/screen/<arm>.json` -- a subdirectory, never a filename suffix -- for
    `universe_source="screen"`, so a screen-mode book can never collide with, or be silently confused
    for, the card-mode file at the same arm name.

    Nested under `app.agentdesk.models.agentdesk_dir` rather than given its own top-level directory,
    so this feature keeps the one footprint `app.agentdesk` already established -- see that function's
    own docstring for why `data/loop/` was deliberately avoided for the sibling `DeskRun` files, which
    applies here for the same reason.
    """
    base = agentdesk_dir(settings) / "workflow" / "book"
    if universe_source == "screen":
        return base / "screen" / f"{arm}.json"
    return base / f"{arm}.json"


def _seed_broker_state(starting_cash: Decimal) -> dict[str, object]:
    """The `PaperBroker.to_state()` shape for a broker that has never traded -- built directly rather
    than by constructing a throwaway `PaperBroker(mandate)` and calling `to_state()` on it, because
    `load_book` (unlike `execute_pending`) is never handed a `Mandate` -- a fresh book has no orders to
    check a mandate against yet, so nothing here should require one just to seed a cash figure.
    """
    return {
        "cash": format(starting_cash, "f"),
        "positions": {},
        "unsettled": [],
        "fills": [],
        "rejections": [],
    }


def load_book(
    settings: Settings,
    arm: WorkflowArm,
    *,
    starting_cash: Decimal,
    card_id: str,
    card_adopted_date: dt.date | None = None,
    universe_source: Literal["card", "screen"] = "card",
) -> BookState:
    """This arm's book, or a freshly seeded one if it has never been written.

    **Never raises on absence** -- an arm's first-ever run has no file yet, and that is the normal
    state of a brand-new book, not an error. `card_adopted_date` is not part of the brief's stated
    signature; it is an optional keyword defaulting to `dt.date.today()` so a caller (a workflow run
    starting a book for the first time) gets today's date without having to compute it, while a test
    that needs a deterministic date can still pass one explicitly.

    `universe_source`, default `"card"`, selects which of the two books at this arm name to read --
    threaded straight into `book_path`. Reproduces today's exact behaviour byte-for-byte when omitted.

    Raises `ValueError` for a file whose `schema_version` this build does not understand (checked
    against the raw JSON, before Pydantic ever validates the rest of the shape), whose contents are
    not valid JSON at all, or whose own `universe_source` does not match what was requested -- the
    last of those is a defensive guard against a caller (or a future path-construction bug) reading a
    ledger through the wrong path and silently mixing card-mode and screen-mode history. All three are
    treated as loud failures rather than a silently-fresh or silently-wrong book, since silently
    discarding or mismatching a real trading history would make it disappear -- or worse, blend --
    without a trace.
    """
    path = book_path(settings, arm, universe_source=universe_source)
    if not path.is_file():
        return BookState(
            arm=arm,
            universe_source=universe_source,
            current_card_id=card_id,
            card_adopted_date=card_adopted_date or dt.date.today(),
            starting_cash=starting_cash,
            broker_state=_seed_broker_state(starting_cash),
            orders=(),
            equity_curve=(),
            as_of=None,
        )

    text = path.read_text(encoding="utf-8")
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"workflow book {path} is not valid JSON: {exc}") from exc

    version = raw.get("schema_version")
    if version != BOOK_SCHEMA_VERSION:
        raise ValueError(
            f"workflow book {path} has schema_version {version!r}; this build only understands "
            f"{BOOK_SCHEMA_VERSION}. A version this old (or new) needs a migration, or the file must "
            "be moved aside before a fresh book can be seeded in its place."
        )
    book = BookState.model_validate(raw)
    if book.universe_source != universe_source:
        raise ValueError(
            f"workflow book {path} has universe_source {book.universe_source!r}; expected "
            f"{universe_source!r}. This means the file at this path was written for a different "
            "universe_source than its own location implies -- refusing to load it rather than risk "
            "silently mixing two ledgers."
        )
    return book


def save_book(settings: Settings, book: BookState) -> None:
    """Write `book` atomically: a uuid-suffixed staging file beside the target, then a single
    `os.replace`. Copies `app.agentdesk.store.RunStore.save`'s exact pattern (see that method's own
    docstring for why temp-file-then-replace and not a direct write) -- `os.replace` is atomic on both
    POSIX and Windows for files on the same volume, which a same-directory staging file always is.

    The path is derived from `book.universe_source` (via `book_path`), never a separate parameter --
    a `BookState` already knows which universe it belongs to, and a caller that wants to write a
    screen-mode book expresses that by setting the field on the `BookState` it hands in, not by an
    out-of-band argument that could disagree with it.
    """
    path = book_path(settings, book.arm, universe_source=book.universe_source)
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.parent / f"{path.name}.{uuid.uuid4().hex}.tmp"
    staging.write_text(book.model_dump_json(indent=2), encoding="utf-8")
    os.replace(staging, path)


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------


def stage_orders(
    book: BookState,
    plans: Sequence[OrderPlan],
    *,
    decision_date: dt.date,
    fill_date: dt.date,
    run_id: str,
) -> BookState:
    """Append `plans` to `book` as new `"pending"` orders. Pure: returns a new `BookState`, never
    mutates `book`.

    `order_id` is assigned deterministically as `f"{run_id}-{n}"`, where `n` is the order's position in
    the book *at staging time* (`len(book.orders)` plus its offset within `plans`) -- not a random id.
    That makes two independent calls with the same inputs produce the same ids, which is what lets a
    test assert on a specific order's id without having to read it back out of the return value first.
    """
    base_index = len(book.orders)
    new_records = tuple(
        WorkflowOrderRecord(
            order_id=f"{run_id}-{base_index + offset}",
            arm=book.arm,
            agent_card_id=plan.agent_card_id,
            symbol=plan.symbol,
            side=plan.side,
            notional=plan.notional,
            decision_date=decision_date,
            fill_date=fill_date,
            status="pending",
            thesis=plan.thesis,
            invalidation=plan.invalidation,
            stop_level=plan.stop_level,
            regime=plan.regime,
            conviction=plan.conviction,
            evidence=plan.evidence,
            created_by_run_id=run_id,
            fill=None,
            reject_reason="",
        )
        for offset, plan in enumerate(plans)
    )
    return book.model_copy(update={"orders": book.orders + new_records})


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExecuteOutcome:
    """What one `execute_pending` call did -- a summary for the caller to log or surface, not
    persisted anywhere itself (the durable record is each order's own `status` inside the returned
    `BookState`)."""

    filled: int
    rejected: int
    still_pending: int
    """Orders left `"pending"` after this call -- either not yet due (`fill_date > today`) or genuinely
    untouched because none were due at all."""
    stored_open_fills: int
    live_quote_fills: int
    """The `PriceSource` mix among this call's fills. Two counters rather than a dict keyed by
    `PriceSource` so a caller never has to guard a missing key for the source that did not occur."""


def execute_pending(
    book: BookState,
    *,
    settings: Settings,
    mandate: Mandate,
    live_quote_source: LiveQuoteSource | None = None,
    today: dt.date | None = None,
) -> tuple[BookState, ExecuteOutcome]:
    """Attempt every `"pending"` order whose `fill_date` is due, and return the resulting `BookState`.

    **Deviation from the brief's stated signature:** this takes `settings: Settings` rather than a
    single pre-built `market: AsOfMarket` and `calendar: SessionCalendar`. The reason is `PaperBroker.
    submit`'s own contract -- "`market` is as of the *decision* session" -- and this function processes
    orders that can carry *different* `decision_date`s in the same call (that is exactly what the
    catch-up case below produces: an order staged days ago sits next to one staged this morning). A
    single caller-supplied `AsOfMarket` cannot be as-of every order's own decision date at once, so this
    function builds one internally, per order, at that order's `decision_date` -- which needs `settings`,
    not a pre-built instance. `calendar` is dropped because nothing here needs a `SessionCalendar`: due
    orders are found by a plain date comparison against `today`, and the fill itself goes through
    `AsOfMarket.open_on`, which (by its own docstring) is never clamped to any instance's `as_of` at all.

    **Catch-up semantics:** an order is "due" whenever `fill_date <= today`, with no upper bound on how
    long ago `fill_date` was -- an order two sessions stale from the app not running that morning is
    processed exactly like one due today, off that same past date's stored open. Nothing here ever sets
    `status="expired"`; see `OrderStatus`'s own docstring for why silent expiry is the specific failure
    mode this function must not reproduce.

    For each due order: a decision-date `AsOfMarket.close` prices the order's notional into a share
    count (`_quantity_for_notional`); if that close does not exist, the order is rejected directly
    (`"unpriceable"`-flavoured `reject_reason`, no `Order` ever constructed, since there is no quantity
    to build one with) rather than reaching `PaperBroker.submit` at all. Otherwise the resulting `Order`
    is submitted with `market` pinned to that same decision-date instance -- which is also what makes
    `PaperBroker._check_buy`'s weight-cap check size against the decision-session close, precisely as
    its own docstring promises, even mid-catch-up.

    The returned `BookState` carries the broker's new `to_state()` blob and every processed order's
    outcome. **This function writes no ledger to disk** -- call `save_book` on the result to persist it;
    keeping the two separate is what lets a caller (or a test) inspect the outcome before committing it.
    The one file it does touch is the notification log: every fill and every rejection is announced
    through `_notify_order`, which is append-only, wrapped, and cannot affect the returned state.
    """
    as_of_today = today if today is not None else dt.date.today()
    broker = PaperBroker.from_state(mandate, book.broker_state)

    orders = list(book.orders)
    due_indices = sorted(
        (
            index
            for index, record in enumerate(orders)
            if record.status == "pending" and record.fill_date <= as_of_today
        ),
        key=lambda index: (orders[index].fill_date, orders[index].order_id),
    )

    filled = 0
    rejected = 0
    stored_open_fills = 0
    live_quote_fills = 0

    for index in due_indices:
        record = orders[index]
        try:
            decision_market = AsOfMarket(as_of=record.decision_date, settings=settings)
            decision_close = decision_market.close(record.symbol)
        except (UnpricedSymbol, FileNotFoundError):
            orders[index] = record.model_copy(
                update={
                    "status": "rejected",
                    "reject_reason": (
                        f"no stored close for {record.symbol} at or before "
                        f"{record.decision_date.isoformat()} to size the order against"
                    ),
                }
            )
            rejected += 1
            _notify_order(settings, orders[index], fill=None)
            continue

        quantity = _quantity_for_notional(
            record.notional, decision_close, allow_fractional=mandate.allow_fractional_shares
        )
        order = Order(
            order_id=record.order_id,
            session=0,
            decided_on=record.decision_date,
            symbol=record.symbol,
            side=record.side,
            quantity=quantity,
            thesis=record.thesis,
            invalidation=record.invalidation,
            stop_level=record.stop_level,
            regime=record.regime or None,
            conviction=int(record.conviction) if record.conviction is not None else None,
            evidence=record.evidence,
        )
        outcome = broker.submit(
            order,
            market=decision_market,
            fill_date=record.fill_date,
            live_quote_source=live_quote_source,
            today=as_of_today,
        )

        if isinstance(outcome, Fill):
            fill_record = WorkflowFillRecord(
                price=outcome.price,
                price_source=outcome.price_source,
                qty=outcome.quantity,
                slippage=abs(outcome.price - outcome.reference_open),
                fees=outcome.fees,
                reference_open=outcome.reference_open,
                filled_at=dt.datetime.now(dt.UTC),
            )
            orders[index] = record.model_copy(update={"status": "filled", "fill": fill_record})
            filled += 1
            if outcome.price_source == "stored_open":
                stored_open_fills += 1
            else:
                live_quote_fills += 1
            _notify_order(settings, orders[index], fill=fill_record)
        else:
            assert isinstance(outcome, Rejection)
            orders[index] = record.model_copy(
                update={"status": "rejected", "reject_reason": outcome.reason}
            )
            rejected += 1
            _notify_order(settings, orders[index], fill=None)

    still_pending = sum(1 for record in orders if record.status == "pending")
    new_book = book.model_copy(
        update={
            "orders": tuple(orders),
            "broker_state": broker.to_state(),
            "as_of": as_of_today,
        }
    )
    return new_book, ExecuteOutcome(
        filled=filled,
        rejected=rejected,
        still_pending=still_pending,
        stored_open_fills=stored_open_fills,
        live_quote_fills=live_quote_fills,
    )


# ---------------------------------------------------------------------------
# Equity marking
# ---------------------------------------------------------------------------


def snapshot_equity(
    book: BookState, *, market: AsOfMarket, on: dt.date, mandate: Mandate
) -> BookState:
    """Append one `{date, equity}` point to `book`'s equity curve, as of `market.as_of`.

    **Deviation from the brief's stated signature:** adds `mandate: Mandate`. `PaperBroker.from_state`
    requires one (it is how a broker knows its own constraints -- max positions, weight cap, and so on
    -- not just its cash and positions), and this function has to rebuild a broker to call `.mark()` on
    it, exactly as `execute_pending` does for the same reason.

    `equity` is `None`, not a partial figure, when **any** open position cannot be priced as of `on` --
    checked directly against `PaperBroker.mark`'s own returned `marks` dict rather than by catching an
    exception, since `mark()` itself never raises for an unpriced holding (it silently omits it from the
    total, by design -- see that method's own docstring). Recording a partial equity number here would
    make a curve point that looks like a real drawdown when it is actually a missing price; recording
    `None` says plainly that this point cannot be trusted, matching `EquityPoint.equity`'s own contract.
    """
    broker = PaperBroker.from_state(mandate, book.broker_state)
    value, marks = broker.mark(market)
    open_symbols = {symbol for symbol, quantity in broker.positions.items() if quantity > 0}

    equity: Decimal | None = None if open_symbols - set(marks) else broker.cash + value

    point = EquityPoint(date=on, equity=equity)
    return book.model_copy(update={"equity_curve": (*book.equity_curve, point), "as_of": on})


def mark_equity_through(
    book: BookState, *, settings: Settings, mandate: Mandate, through: dt.date
) -> BookState:
    """Backfill `book`'s equity curve with one point per stored SPY trading session, from the day
    after its last existing point through `through` inclusive.

    **Nothing before this function ever called `snapshot_equity`.** Every workflow book on disk today
    has an `equity_curve` of exactly `()` -- not because a day was ever skipped, but because no call
    site marked one at all (see `snapshot_equity`'s own history: it was written, exported, and never
    wired to a caller). This function is the backfill for that gap, called once per fill site alongside
    `execute_pending` (see `book_path`'s three callers) rather than a one-time migration script, so a
    book that is behind by any number of sessions -- including every session since inception, for a
    book this old -- catches all the way up on its very next call.

    **Why this cannot reuse `snapshot_equity` in a loop, and never touches `broker_state` or
    `PaperBroker.from_state`/`.mark()` at all.** `snapshot_equity` marks exactly one day, `market.
    as_of`, off `book.broker_state` -- the broker's *current* cash/positions blob, with no memory of
    what it held on any earlier date. Replaying that blob against successively earlier `as_of` dates
    would not reconstruct history; it would just re-price today's holdings under a stale label. Instead
    this function replays `book.orders` itself: every `status == "filled"` order, in `(fill_date,
    order_id)` order, applied one at a time as this loop's own session cursor advances from `start` to
    `through` -- the same buy/sell cash-and-quantity arithmetic `PaperBroker._apply_fill` performs,
    done here directly against the book's own fill history because a live broker instance only ever
    *is* one instant, and backfilling needs every instant in between.

    `start` is the day after the last point already on `book.equity_curve`, or, when the curve is
    empty, `min(book.card_adopted_date, earliest filled order's fill_date)` -- `card_adopted_date`
    alone when there are no fills yet. Anchoring an empty curve at `card_adopted_date` (not just the
    first fill) means a book that has been sitting flat with no trades still gets a real, marked-flat
    curve from the day it was adopted, which is what lets `app.workflow.study._paired_comparison` find
    common dates against an arm that traded, instead of the empty-intersection zero it gets today.

    `mandate` is accepted for signature parity with `snapshot_equity`/`execute_pending` but is not
    read by this function -- see the paragraph above for why nothing here ever reconstructs a
    `PaperBroker` (which is the only thing in this module a `Mandate` is ever used for).

    **No stored SPY bars at all, or no SPY session in `[start, through]`, returns `book` unchanged** --
    not an error, and not a curve mutated with zero points appended. The latter is also what makes this
    function idempotent: a second call with the same `through` computes a `start` strictly after the
    last point just appended, finds no sessions in the now-empty `[start, through]` window, and returns
    the input unchanged.

    A session where any symbol still held (`quantity > 0`) as of that day has no stored close records
    `equity=None` for that one point -- the same "an unpriced holding is unknown, never a silently
    partial figure" contract `snapshot_equity` and `EquityPoint.equity` already pin.
    """
    filled_orders = sorted(
        (order for order in book.orders if order.status == "filled" and order.fill is not None),
        key=lambda order: (order.fill_date, order.order_id),
    )

    if book.equity_curve:
        start = book.equity_curve[-1].date + dt.timedelta(days=1)
    elif filled_orders:
        start = min(book.card_adopted_date, filled_orders[0].fill_date)
    else:
        start = book.card_adopted_date

    frame = market_store.read_frame("SPY", Interval.DAY, start=start, end=through, settings=settings)
    if frame is None or frame.empty:
        return book

    session_dates: list[dt.date] = sorted(frame["ts"].dt.date.unique())
    if not session_dates:
        return book

    new_points: list[EquityPoint] = []
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
        for symbol, quantity in quantities.items():
            if quantity <= 0:
                continue
            try:
                close = market.close(symbol)
            except UnpricedSymbol:
                fully_priced = False
                break
            total += quantity * close

        new_points.append(EquityPoint(date=session_date, equity=total if fully_priced else None))

    return book.model_copy(
        update={
            "equity_curve": (*book.equity_curve, *new_points),
            "as_of": session_dates[-1],
        }
    )


# ---------------------------------------------------------------------------
# Tax
# ---------------------------------------------------------------------------


def _order_to_fill(order: WorkflowOrderRecord) -> Fill:
    """One filled `WorkflowOrderRecord` back into the `app.paper.paperbroker.Fill` shape
    `app.paper.papertax.fills_to_transactions` consumes.

    `gross` and `cash_delta` are not stored on `WorkflowFillRecord` (see that class's own docstring for
    which fields are and why) because `fills_to_transactions` never reads either one -- it builds a
    `Transaction` from `order_id`, `trade_date`, `symbol`, `side`, `quantity`, `price` and `fees` only.
    They are still recomputed here, from numbers already known (`price`, `qty`, `fees` all came from the
    real fill), purely so the reconstructed `Fill` is a complete, sensible-looking object for anything
    that logs or inspects it -- not because the tax pipeline needs them.
    """
    fill = order.fill
    assert fill is not None
    gross = _money(fill.price * fill.qty)
    cash_delta = -(gross + fill.fees) if order.side == "buy" else (gross - fill.fees)
    return Fill(
        order_id=order.order_id,
        session=0,
        trade_date=order.fill_date,
        symbol=order.symbol,
        side=order.side,
        quantity=fill.qty,
        price=fill.price,
        reference_open=fill.reference_open,
        gross=gross,
        fees=fill.fees,
        cash_delta=_money(cash_delta),
        price_source=fill.price_source,
    )


@dataclass(frozen=True, slots=True)
class HeldLot:
    """One currently-held tax lot derived from a book's fills -- what the tax switch check needs to
    decide whether liquidating this arm's card would cost more than the switch is worth.

    `cost_basis` is the whole lot's basis (price x qty + its share of the entry fee), not per share,
    matching `app.workflow.taxcheck.PositionLot.cost_basis`'s own contract. `current_price` is left to
    the caller to mark -- this module derives lots from the order history without touching the market,
    and the caller (`app.workflow.pipeline`) already holds an `AsOfMarket` to price them at.
    """

    symbol: str
    quantity: Decimal
    cost_basis: Decimal
    acquired_date: dt.date


def held_lots(book: BookState) -> tuple[HeldLot, ...]:
    """The lots this book still holds, FIFO, one per surviving buy fill.

    Built from the order history rather than the broker's collapsed position map because a tax lot's
    *acquisition date* is what the wash-sale and short-vs-long rules turn on, and the broker's netted
    `positions` blob does not carry it -- the same reason `app.paper.papertax` builds its lots from the
    fill stream. Filled sells reduce the oldest surviving buys first (FIFO), matching
    `app.core.lots.build_lots`'s own default method, so what remains is the set of open lots with their
    true acquisition dates. The workflow only stages buys today, so in practice this returns every
    filled buy; the sell-reduction is here so the helper stays correct if exits are ever staged.
    """
    @dataclass
    class _OpenLot:
        quantity: Decimal
        cost_basis: Decimal
        acquired_date: dt.date

    open_lots: dict[str, list[_OpenLot]] = {}
    for order in book.orders:
        if order.status != "filled" or order.fill is None:
            continue
        fill = order.fill
        if order.side == "buy":
            open_lots.setdefault(order.symbol, []).append(
                _OpenLot(
                    quantity=fill.qty,
                    cost_basis=_money(fill.price * fill.qty + fill.fees),
                    # `order.fill_date` -- the trading session this lot was acquired on -- and NOT
                    # `fill.filled_at.date()`, which is a wall-clock audit stamp saying when
                    # `execute_pending` happened to write the row (see `WorkflowFillRecord.filled_at`'s
                    # own docstring, which states the distinction in as many words).
                    #
                    # This was wrong, and it mattered. A lot's acquisition date is what the holding
                    # period and the wash-sale window are both measured from, so every figure
                    # `tax_summary` derives from these lots -- the short-versus-long-term split, the
                    # 61-day repurchase window -- was being measured from the day a script ran rather
                    # than the day the trade happened. The deterministic backfill made the gap
                    # obvious: it wrote a month of sessions in one pass, stamping every lot with the
                    # same wall-clock date, so positions entered weeks apart all claimed to have been
                    # acquired that afternoon. It stayed hidden because the tests in
                    # `tests/test_workflow_book.py` build `filled_at` as
                    # `datetime.combine(day, ...)` -- consistent with the session by construction,
                    # which is exactly the case that cannot tell the two fields apart.
                    acquired_date=order.fill_date,
                )
            )
        else:  # sell: retire oldest lots first (FIFO)
            remaining = fill.qty
            lots = open_lots.get(order.symbol, [])
            while remaining > 0 and lots:
                lot = lots[0]
                if lot.quantity <= remaining:
                    remaining -= lot.quantity
                    lots.pop(0)
                else:
                    ratio = (lot.quantity - remaining) / lot.quantity
                    lot.cost_basis = _money(lot.cost_basis * ratio)
                    lot.quantity = lot.quantity - remaining
                    remaining = Decimal(0)
    return tuple(
        HeldLot(
            symbol=symbol,
            quantity=lot.quantity,
            cost_basis=lot.cost_basis,
            acquired_date=lot.acquired_date,
        )
        for symbol, lots in open_lots.items()
        for lot in lots
    )


def tax_summary(book: BookState, *, settings: Settings) -> PaperTaxSummary | None:
    """After-tax realised results for `book`'s filled orders, computed entirely by the real tax engine
    (`app.paper.papertax.summarize_paper_tax`) -- nothing here re-derives lots, wash sales or gains.

    **Degrades to `None` with a logged warning rather than raising.** This feeds a page render, and a
    tax figure that is merely unavailable (no filled orders yet; a symbol the lot-matching engine
    chokes on for a reason unrelated to this book) must not take the whole page down with it -- the same
    choice `app.agentdesk.store.load` makes for a run file that will not parse. An empty `book.orders`
    (or one with no `"filled"` entries yet) is the ordinary state of a brand-new arm and is handled
    before ever calling `summarize_paper_tax`, which would otherwise raise `ValueError` for a
    date range it cannot infer from zero fills.

    Reads the user's configured tax brackets via `resolve_configured_rates(settings)` rather than
    accepting `summarize_paper_tax`'s statutory-upper-bound defaults silently -- this is the one
    non-pure read in this module, matching `resolve_configured_rates`'s own docstring about being kept
    separate specifically so a caller has to opt in, which this function does on `book`'s behalf because
    a paper-desk tax summary is exactly the "real bracket" case that function's docstring describes.
    """
    filled_orders = [order for order in book.orders if order.status == "filled" and order.fill is not None]
    if not filled_orders:
        logger.info("workflow book %s: no filled orders yet; skipping tax summary", book.arm)
        return None

    try:
        fills = [_order_to_fill(order) for order in filled_orders]
        short_rate, long_rate, _basis = resolve_configured_rates(settings)
        return summarize_paper_tax(
            fills,
            account_id=f"workflow-{book.arm}",
            short_term_rate=short_rate,
            long_term_rate=long_rate,
        )
    except Exception:
        logger.warning(
            "workflow book %s: tax summary computation failed; degrading to None",
            book.arm,
            exc_info=True,
        )
        return None

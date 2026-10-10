"""The persistent per-arm paper trade ledger's wire and storage shape.

**Why this ledger is persisted at all, when the rest of the paper-desk layer is not.**
`app.paperdesk` never writes a book to disk -- it recomputes one on every request by replaying a
strategy card's mechanical rules against stored bars (see that package's own docstring). That works
because a card's decision on any given day is a pure function of price history: re-run the replay and
you get the same order every time. An `app.workflow` order is not that. It is the output of a chain of
language-model judgements -- regime call, card selection, candidate research, gate verdicts -- made on
day N against evidence (headlines, filings, a debate transcript) that is never fully re-derivable from
price bars alone, and is not guaranteed to reproduce even if it were re-run verbatim (a fresh model
call is not a deterministic function of its prompt). An order this package staged on day N therefore
cannot be recomputed on day N+1; it has to be written down, exactly once, the day it was decided. This
module is the shape of what gets written down.

**Money and prices are `Decimal` in Python and decimal strings on the wire.** Same rule as the rest of
this codebase (see `app.agentdesk.models`'s own docstring for the same sentence): a float would import
IEEE binary error into a monetary figure, and `Decimal(str(some_float))` is the one safe crossing point
-- never a bare `Decimal(some_float)`. Pydantic already round-trips `Decimal` through a JSON string by
default (`model_dump_json` emits `"123.45"`, never a bare `123.45`), which is what makes this contract
enforceable without a custom encoder: every model below relies on that default rather than overriding
it.

**Every model here is frozen.** A staged order, once written, is never mutated in place -- `stage_orders`
and `execute_pending` in `app.workflow.book` each take a `BookState` and return a *new* one, the same
discipline `app.agentdesk.models.DeskRun` uses for exactly the same reason: a reader that polls the book
file mid-write must see either the last complete state or the new one, never a half-updated object.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "BOOK_SCHEMA_VERSION",
    "BookState",
    "EquityPoint",
    "OrderPlan",
    "OrderStatus",
    "PriceSource",
    "WorkflowArm",
    "WorkflowFillRecord",
    "WorkflowOrderRecord",
]


class _Frozen(BaseModel):
    """Shared config for every model in this module. Not exported -- purely local shorthand,
    mirroring `app.agentdesk.models._Frozen`."""

    model_config = ConfigDict(frozen=True, extra="forbid")


WorkflowArm = Literal["raw_signal", "ta_gated", "vibe_gated", "full_workflow"]
"""Which of the four parallel books an order belongs to. See `app.workflow`'s own module docstring
("Four books, not one.") for why these four and no others -- they diverge at exactly one point, the
gate that decides which candidates survive, from an otherwise-identical regime call, card and
candidate set."""

OrderStatus = Literal["pending", "filled", "rejected", "cancelled", "expired"]
"""An order's lifecycle state. `"pending"` is staged but not yet due (or due but not yet processed by
`execute_pending`); `"filled"`/`"rejected"` are the two terminal outcomes `PaperBroker.submit` can
produce. `"cancelled"` and `"expired"` are reserved for a future caller (a card rotation that
withdraws its own unfilled orders, or a staleness policy) -- nothing in `app.workflow.book` sets
either today. In particular, an order whose `fill_date` has already passed when `execute_pending`
finally runs is still attempted, never marked `"expired"` -- see that function's own docstring for why
silent expiry is exactly the failure mode this package must not reproduce."""

PriceSource = Literal["stored_open", "live_quote"]
"""Mirrors `app.paper.paperbroker.Fill.price_source` verbatim -- see that field's docstring for what
each value means. Restated here as its own `Literal` rather than imported, because `WorkflowFillRecord`
is a Pydantic model on the wire and `Fill` is a plain dataclass that never crosses a process boundary;
the two are independent representations of the same two-valued fact by design, not by oversight."""

BOOK_SCHEMA_VERSION = 1
"""The only version this module currently understands. Carried as `BookState.schema_version` rather
than inferred from the file's shape so that a later field addition can be migrated deliberately -- see
`app.workflow.book.load_book`, which reads this value out of the raw JSON *before* Pydantic validation
and raises a clear error for anything else, rather than letting an old or new file be silently
misread as today's shape."""


class OrderPlan(_Frozen):
    """One order as the workflow's entry-plan stage hands it to `app.workflow.book.stage_orders`.

    Not part of the persisted `BookState` -- this is the *input* shape a caller builds fresh each run;
    the persisted record it becomes is `WorkflowOrderRecord`, which additionally carries the
    bookkeeping (`order_id`, `arm`, `decision_date`, `fill_date`, `status`, ...) that only exists once
    an order has actually been staged. Kept as its own model, rather than accepting a bag of keyword
    arguments, for the same reason every other boundary in this codebase is a named Pydantic model:
    two callers building the same shape by convention drift; two callers importing the same model
    cannot.

    `notional` -- a dollar amount, not a share count -- is the one field a plan carries instead of
    `PaperBroker.Order.quantity`. The actual share count depends on a price nothing in this package
    knows at staging time (the fill has not happened yet, and even the decision-date close used to
    size it is a read `stage_orders` deliberately does not perform -- see that function's docstring for
    why sizing is deferred to `execute_pending`, which is the one place in this module that is handed
    a `Settings` and can read prices at all).
    """

    agent_card_id: str
    """Which strategy card this candidate came from -- the same id `app.thesis`/`app.tournament`
    already use, threaded through unchanged so a workflow order can be traced back to the card that
    produced it."""

    symbol: str
    side: Literal["buy", "sell"]
    notional: Decimal
    """Dollar size of the intended order, always positive. Converted to a whole (or, if the mandate
    allows it, fractional) share count in `execute_pending` against the decision-date close."""

    thesis: str = ""
    invalidation: str = ""
    stop_level: Decimal | None = None
    regime: str = ""
    conviction: Decimal | None = None
    evidence: tuple[str, ...] = ()


class WorkflowFillRecord(_Frozen):
    """What actually happened when an order was executed -- the parts of `app.paper.paperbroker.Fill`
    that survive onto a `WorkflowOrderRecord`.

    Two fields exist here that the brief for this ledger does not name outright, `fees` and
    `reference_open`, because `app.workflow.book.tax_summary` cannot do its job without them:
    `app.paper.papertax.fills_to_transactions` reads `Fill.fees` directly (a paper fill's fees are
    real, not the Webull "unknown fee" case -- see that module's own docstring), and a `Fill`
    reconstructed here without a fee figure would silently understate every disposal's cost basis.
    `reference_open` is carried alongside for the same audit reason `Fill` itself carries it: so the
    slippage assumption behind `price` can be checked against the unslipped print it was computed from,
    without having to re-open the broker's own state to find it.
    """

    price: Decimal
    """The executed, slippage-adjusted price -- `Fill.price`."""

    price_source: PriceSource
    qty: Decimal
    """Shares filled -- `Fill.quantity`. May differ from the plan's own sized quantity by nothing:
    `PaperBroker` never partially fills."""

    slippage: Decimal
    """`abs(Fill.price - Fill.reference_open)`, always non-negative regardless of side -- the
    magnitude of the adverse move `PaperBroker._slipped` applied, not a signed cash delta (that lives
    on the underlying `Fill.cash_delta`, which this record does not need to carry since nothing here
    recomputes cash -- `PaperBroker.to_state()` already owns the book's cash figure)."""

    fees: Decimal
    """`Fill.fees` -- real SEC/TAF/commission fees, required by `tax_summary` (see this class's own
    docstring) and not part of the brief's originally-listed field set."""

    reference_open: Decimal
    """`Fill.reference_open` -- the unslipped print `price` was computed from. Audit-only; nothing in
    this package recomputes `slippage` from it, since `slippage` is stored directly."""

    filled_at: dt.datetime
    """When `execute_pending` recorded this fill -- a wall-clock audit timestamp, distinct from the
    order's own `fill_date` (the trading session the fill priced against). Two orders sharing a
    `fill_date` because `execute_pending` caught them up together will differ here, which is the point:
    it is the one field that shows a fill was processed late rather than on the session it names."""


class WorkflowOrderRecord(_Frozen):
    """One order's whole lifecycle, as persisted in a `BookState`.

    Immutable once appended: `execute_pending` does not mutate an existing record's `status` field in
    place, it replaces the tuple entry with a new record carrying the outcome -- the same "replace, do
    not mutate" discipline `app.agentdesk.store.with_stage` uses for `StageRecord`.
    """

    order_id: str
    """Unique within a book. Assigned by `stage_orders` as `f"{created_by_run_id}-{n}"`, where `n` is
    the order's position in the book at staging time -- deterministic and human-traceable back to the
    run that staged it, without needing a random id generator this module would then have to seed for
    reproducible tests."""

    arm: WorkflowArm
    agent_card_id: str
    symbol: str
    side: Literal["buy", "sell"]
    notional: Decimal

    decision_date: dt.date
    """The session whose close the order was sized and reasoned against -- see `OrderPlan.notional`'s
    docstring for why sizing happens later, in `execute_pending`, but always against this date."""

    fill_date: dt.date
    """The session this order is meant to fill at the open of -- one session after `decision_date`,
    mirroring `PaperBroker.submit`'s own "next-open, never the decision close" rule exactly."""

    status: OrderStatus = "pending"

    thesis: str = ""
    invalidation: str = ""
    stop_level: Decimal | None = None
    regime: str = ""
    conviction: Decimal | None = None
    evidence: tuple[str, ...] = ()

    created_by_run_id: str
    """The `app.agentdesk` run id that produced this order -- traces a book entry back to the exact
    workflow run, and the child TradingAgents/VibeDesk runs it launched, that decided it."""

    fill: WorkflowFillRecord | None = None
    """Set once `status` becomes `"filled"`. `None` for every other status."""

    reject_reason: str = ""
    """Human-readable reason, set exactly when `status == "rejected"` -- either a `Rejection.reason`
    from `PaperBroker.submit` (a mandate rule fired) or a pricing failure `execute_pending` itself
    detected before an `Order` could even be built (no decision-date close to size against). Empty for
    every other status."""


class EquityPoint(_Frozen):
    """One mark-to-market reading in a book's equity curve."""

    date: dt.date
    equity: Decimal | None
    """`None` when `app.workflow.book.mark_equity_through`/`snapshot_equity` -- the two functions that
    actually write points onto this curve; `execute_pending` never does -- could not price every open
    position on `date` (mirrors `PaperBroker.mark`'s own "an unpriced holding contributes nothing, the
    caller notices its absence" contract) -- rather than a silently-wrong number that quietly excludes
    the unpriced position's value. A curve point is allowed to be unknown; it is not allowed to be
    wrong."""


class BookState(_Frozen):
    """One arm's whole persisted ledger -- the file `app.workflow.book.book_path` names.

    `schema_version` is checked by `app.workflow.book.load_book` before this model is ever
    constructed from a file's contents -- see `BOOK_SCHEMA_VERSION`'s own docstring. A `BookState`
    built directly in Python (every fresh-seeded book, and every test) gets the current version for
    free via the field default.
    """

    schema_version: int = BOOK_SCHEMA_VERSION

    arm: WorkflowArm
    universe_source: Literal["card", "screen"] = "card"
    """Which universe this book's orders were selected from -- `"card"` (the strategy card's own
    static `universe`, today's only behaviour) or `"screen"` (a dynamic discovery-selector shortlist,
    see `app.workflow.universe`). Books are keyed by the *pair* `(arm, universe_source)`, not by a
    widened `WorkflowArm` -- `WorkflowArm` stays a closed 4-value `Literal` on purpose (see this
    module's own docstring and `docs/closed-unions-over-server-data-kill-pages` in this repo's own
    memory: a throwing exhaustiveness check over a server-supplied string has taken a page down here
    before). A book loaded from a file written before this field existed gets the default `"card"`,
    the same Pydantic-default-fills-old-rows behaviour every other additive field on a frozen model in
    this package already relies on -- no migration, no version bump."""

    current_card_id: str
    """The strategy card this arm is presently trading. Distinct from `WorkflowOrderRecord.
    agent_card_id`, which names the card an individual *order* came from -- a card rotation changes
    `current_card_id` going forward without rewriting the history of orders staged under the old one."""

    card_adopted_date: dt.date
    """The decision date `current_card_id` took effect. Not updated by anything in this module --
    `app.workflow.book` stages and executes orders; the taxcheck/rotation decision that would change
    `current_card_id` and this date belongs to a different stage of the workflow pipeline (see
    `app.workflow`'s own module docstring, step 2)."""

    starting_cash: Decimal
    """This arm's inception cash. Fixed for the book's lifetime -- matches
    `PaperBroker.mandate.starting_cash` for the mandate this book is replayed against, and is carried
    here separately so a caller can read it (for a since-inception return figure, say) without
    reconstructing a `PaperBroker` first."""

    broker_state: dict[str, Any] = Field(default_factory=dict)
    """The exact blob `PaperBroker.to_state()` produces / `PaperBroker.from_state()` consumes --
    opaque to this module by design. `app.workflow.book` never reaches into this dict's keys; it always
    goes through `PaperBroker.from_state`/`to_state` so a future change to that shape (a new field on
    `Fill`, say) needs no matching change here."""

    orders: tuple[WorkflowOrderRecord, ...] = ()
    equity_curve: tuple[EquityPoint, ...] = ()
    as_of: dt.date | None = None
    """The date `broker_state` was last executed, or `equity_curve` last marked, through -- set by
    `execute_pending` (fills), and by `app.workflow.book.mark_equity_through`/`snapshot_equity` (the
    equity curve; `execute_pending` itself never writes an `EquityPoint`). `None` for a freshly seeded
    book that has never run any of the three."""

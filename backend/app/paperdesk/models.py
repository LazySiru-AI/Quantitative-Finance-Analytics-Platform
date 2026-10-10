"""Wire shapes for the paper desk: what ``GET /api/paperdesk/state`` and
``POST /api/paperdesk/refresh`` return.

**Money, quantities and ratios cross the wire as strings, never JSON numbers.** Every field typed
``Money``/``Quantity`` (from :mod:`app.core.models`) or plain ``Decimal`` here serialises to a JSON
string under pydantic's default ``Decimal`` handling -- the same behaviour ``app.api.portfolio``
already relies on (see its ``AccountPosition``/``Position``/``PortfolioReport`` models, and
``tests/test_portfolio_api.py`` asserting e.g. ``cost_basis == "20.00"``). ``frontend/src/api/
client.ts`` names this contract ``DecimalString = string`` and every money/ratio field below is
that type in spirit, spelled as ``Money``, ``Quantity`` or ``Decimal`` so pydantic still validates
the value's shape server-side. Only genuinely dimensionless fractions computed by
``app.backtest.metrics`` as native floats already (``capital_exposure``, ``weight``) stay ``float``
-- they were never Decimal in the first place and forcing a Decimal re-wrap on them would just be
ceremony around the same IEEE double.

Every model here is frozen and forbids extra fields, matching every other response model in this
codebase (see ``app.api.macro``, ``app.api.portfolio``).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.core.models import Money, Quantity
from app.paper.papertax import PaperTaxSummary

__all__ = [
    "AutopilotDescription",
    "AutopilotOrder",
    "Benchmark",
    "Book",
    "Decision",
    "Desk",
    "DeskRejection",
    "FetchSummary",
    "Funding",
    "Holding",
    "InceptionUpdateRequest",
    "LadderDescription",
    "LadderRungDescription",
    "LiveFill",
    "PaperDeskState",
    "Signal",
    "Trade",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Benchmark(BaseModel):
    """Buy-and-hold on one symbol over the same sessions every desk traded -- see
    ``app.tournament.runner._benchmark_return``, whose return this wraps unchanged."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    return_pct: Decimal | None = None
    """``None`` only when the benchmark itself could not be priced over the window (see
    ``_benchmark_return``'s own docstring) -- not a fabricated zero."""
    label: str | None = None
    """What this index is, in the reader's terms ("broad market", "Nasdaq-100"). Optional so the
    single-benchmark field that predates :attr:`PaperDeskState.benchmarks` keeps validating."""


class Holding(_Frozen):
    """One position still open at the trading window's end -- every ``RealisedTrade`` whose
    ``exit_reason == "open_at_end"``, reshaped for display. See :mod:`app.paperdesk.desk` for how
    ``last_price``/``market_value``/``unrealised_pnl`` are derived (fresh, off the same mark
    ``run_card`` used for ``AgentResult.ending_equity``, not recomputed from the fee-adjusted
    ``RealisedTrade.pnl`` -- that keeps ``equity == cash + positions_value`` exact to the cent)."""

    symbol: str
    quantity: Quantity
    entry_date: dt.date
    entry_price: Money
    cost_basis: Money
    last_price: Money
    last_price_date: dt.date
    market_value: Money
    unrealised_pnl: Money
    return_pct: Decimal
    bars_held: int
    weight: float
    """This holding's share of the desk's own ``equity``, as a fraction of one."""
    stop_price: Money | None = None
    """``entry_price * (1 - stop_loss_pct)``. ``None`` when the card declares no stop."""
    target_price: Money | None = None
    """``entry_price * (1 + take_profit_pct)``. ``None`` when the card declares no target -- both
    ``B-momentum`` and ``C-trend`` declare none."""
    sessions_to_time_stop: int | None = None
    """``max_hold_days - bars_held``. ``None`` when the card declares no hold cap."""


class Trade(_Frozen):
    """One closed round trip, exactly as :class:`~app.tournament.models.RealisedTrade` recorded it
    -- ``pnl``/``return_pct``/``bars_held`` are read off that record unchanged, never recomputed."""

    symbol: str
    entry_date: dt.date
    entry_price: Money
    exit_date: dt.date
    exit_price: Money
    quantity: Quantity
    exit_reason: str
    """``rule`` / ``stop`` / ``target`` / ``time`` -- never ``open_at_end``, which is a
    :class:`Holding` instead. See ``RealisedTrade.exit_reason``'s own docstring."""
    pnl: Money
    return_pct: Decimal
    bars_held: int


class Decision(_Frozen):
    """One order the desk actually placed, derived from the trade log -- **not** a per-session
    deliberation trace. See :mod:`app.paperdesk.desk`'s module docstring for why this log can only
    show decisions that resulted in a fill, and :class:`Signal` for what covers "what is the
    strategy thinking right now" instead."""

    date: dt.date
    symbol: str
    action: str
    """``"enter"`` or ``"exit"``."""
    reason: str
    """A human-readable rendering of the entry rule or the closing ``RealisedTrade.exit_reason``
    (``stop`` -> "stop loss hit", ``rule`` -> "exit rule fired", ``time`` -> "hold cap reached",
    ``target`` -> "take-profit hit")."""
    price: Money
    quantity: Quantity
    notional: Money


class Signal(_Frozen):
    """One universe symbol's current standing, evaluated once against the newest stored close
    (``PaperDeskState.as_of``) -- the same close every :class:`Holding` is marked to. This is
    deliberately the *next* decision, not the last one already acted on: a trader reads the rules
    against today's close and the resulting order fills at the next session's open, which has not
    happened yet -- evaluating here is not lookahead, since ``as_of``'s own close is already
    stored. ``entry_fires: true`` therefore reads as "this gets bought at the next open," and a
    held symbol's :attr:`last_close` always equals its :class:`Holding`'s ``last_price`` -- both are
    marked to the same date. See :mod:`app.paperdesk.desk` for exactly which ``AsOfMarket`` this
    is."""

    symbol: str
    held: bool
    entry_fires: bool
    exit_fires: bool
    """Always ``False`` when ``held`` is ``False`` -- an exit signal on a position not held is not
    a meaningful thing to report."""
    last_close: Money | None = None
    """``None`` exactly when :attr:`blocked` is ``"no price"``. Otherwise equal to the held
    symbol's own :attr:`Holding.last_price`, since both are marked to ``PaperDeskState.as_of``."""
    blocked: str | None = None
    """``"book full"``, ``"insufficient cash"``, ``"no price"``, or ``None``. Only ever set when
    :attr:`entry_fires` is ``True`` and the symbol is not already held -- a fired entry on a symbol
    already in the book is never blocked, it is simply not re-entered (no pyramiding)."""
    rank_value: float | None = None
    """This symbol's value for the card's ``rank_by`` key at ``PaperDeskState.as_of``, or ``None``.

    ``None`` covers two genuinely different things, deliberately not distinguished here because a
    reader does not act on them differently: the card set no ``rank_by`` at all (so no symbol has a
    key), and the key is unknown for *this* symbol at this date -- an indicator still in warmup, a
    ticker with no stored bars. See ``app.tournament.runner._RankTable.value``, which is where this
    number comes from and which collapses the same cases the same way.

    A raw ``float``, in the key expression's own units, not a normalised score: ``close / sma(200)``
    gives ``1.07``, ``rsi(14)`` gives ``62.4``. There is no scale to compare across cards, only
    across symbols within one card -- which is the only comparison the engine itself makes."""
    entry_rank: int | None = None
    """1-based place in the queue for this desk's free slots, or ``None`` for a symbol not in it.

    ``None`` for every symbol that is not currently contending -- already held, or whose entry rule
    is quiet -- and for every symbol on a card that left ``rank_by`` unset, since without a key the
    engine's order is the arbitrary one ``universe`` was typed in and numbering it would dress an
    accident up as a ranking. When set, ``entry_rank == 1`` is the name this desk buys next; against
    :attr:`Desk.slots_free` it says exactly how far down the queue the money reaches.

    Counted over contenders only, not over the whole universe, so the numbers mean "next", "second
    in line" rather than a position in a list most of whose rows are not competing for anything."""


class LadderRungDescription(_Frozen):
    """One step of a drawdown ladder, as submitted -- see
    `app.tournament.ladder.LadderCard.rungs`/`.Rung`, which this reshapes for display unchanged."""

    drawdown_pct: Decimal
    """A negative fraction of one -- `-0.10` reads as "SPY 10% below its own all-time closing
    high"."""
    leveraged_weight_pct: Decimal
    """Fraction of the whole book the leveraged sleeve targets once this rung has fired."""


class LadderDescription(_Frozen):
    """A drawdown-ladder card's own rules, as submitted -- the `kind == "ladder"` counterpart to the
    `entry`/`exit`/`max_positions`/`position_pct` fields a rules card carries directly on
    :class:`Desk`. Present if and only if :attr:`Desk.kind` is `"ladder"`.

    This is a separate block, not a reinterpretation of the rules-card fields, because a ladder card
    has no per-symbol boolean rule at all to put in `entry`/`exit` -- see
    `app.tournament.ladder`'s own module docstring for why the two card shapes are fundamentally
    different decisions (a portfolio weight driven by one shared signal, versus a per-symbol
    in-or-out rule), not two dialects of the same one. A page rendering `entry`/`exit` prose for a
    ladder card would be inventing a rule the card does not have; this block is what the page renders
    instead (see `frontend/src/pages/PaperDesk.tsx`'s `DeskLadderDescription`).
    """

    signal_symbol: str
    """The index whose drawdown from its own all-time closing high drives every decision -- SPY."""
    defensive_symbol: str
    bond_symbol: str
    leveraged_symbol: str
    base_defensive_weight_pct: Decimal
    """The defensive sleeve's weight in the base state (0% leveraged)."""
    base_bond_weight_pct: Decimal
    """The bond sleeve's weight in the base state."""
    rungs: list[LadderRungDescription]
    confirm_ma_sessions: int
    """Session count for the bounce-confirmation moving average -- a rung fires only once the signal
    has closed back above this trailing average, the single most important rule in the card (see
    `app.tournament.ladder`'s own module docstring)."""
    ath_haircut_pct: Decimal
    """On a new all-time high, the leveraged sleeve's weight is multiplied by this rather than sold
    outright."""
    recovery_gain_pct: Decimal
    """Full exit once the signal closes this fraction above the high the current cycle started
    from."""
    recovery_sessions: int
    """Full exit this many sessions after a new high, whichever of this or `recovery_gain_pct` comes
    first."""


class AutopilotOrder(_Frozen):
    """One order the autopilot's book has staged but not yet filled -- a `WorkflowOrderRecord` whose
    `status` is still `"pending"`, reshaped for display.

    Rendered as a *forthcoming* order rather than as a :class:`Signal`, even though the panel shows
    both under "what it would do next", because the two are genuinely different claims. A `Signal` is
    a rule re-evaluated against the newest close on every request: it says "this is what the rule says
    right now", and it changes when the bars change. A staged order is a decision already written down
    on its own `decision_date` and is not re-derivable -- see `app.workflow.book_models`' own module
    docstring for why an agent's order has to be persisted where a card's can be replayed. A reader
    must be able to tell "the strategy would buy this" from "the desk has already committed to buying
    this at the next open", and giving the second its own shape is how.
    """

    symbol: str
    side: str
    """`"buy"` or `"sell"`. The workflow stages only buys today -- see
    :attr:`AutopilotDescription.exits` -- so this is `"buy"` in practice; typed open because the
    record it comes from is."""
    notional: Money
    """The dollar size the plan asked for, **not** a share count. Sizing happens at fill time against
    the decision date's close, so no quantity exists for a pending order and none is invented here."""
    decision_date: dt.date
    fill_date: dt.date
    """The session this order is due to fill at the open of. Already in the past when the daily step
    has not run -- an order is never silently expired (see `app.workflow.book.execute_pending`)."""
    regime: str = ""
    """The regime label the run staged this order under, verbatim, or `""` when it recorded none."""


class AutopilotDescription(_Frozen):
    """The autopilot seat's own provenance block -- the `kind == "autopilot"` counterpart to
    :class:`LadderDescription`, present if and only if :attr:`Desk.kind` is `"autopilot"`.

    A separate block for the same reason the ladder got one: this desk has no per-symbol boolean rule
    to put in `entry`/`exit`, so rendering those fields would invent rules the desk does not have.
    What it has instead is a *provenance*: which arm of the four-arm study it is, which universe those
    candidates were screened from, which strategy card the regime call last selected, and what the most
    recent run actually did. That is what this block carries.

    **Every field here is read from the persisted book and the run store, never recomputed.** The
    numbers a reader checks against `/agent-workflow` and the numbers on this panel come from the same
    two files, so they cannot disagree.
    """

    arm: str
    """Which of the four study arms this seat trades -- `"full_workflow"` by default. See
    `app.workflow.book_models.WorkflowArm`."""
    universe_source: str
    """`"screen"` (candidates chosen by the dynamic selector each session) or `"card"` (the selected
    strategy card's own fixed universe). A book is identified by the *pair* `(arm, universe_source)`,
    never by `arm` alone -- the same rule `frontend/src/pages/AgentWorkflow.tsx` follows."""
    current_card_id: str
    """The strategy card the workflow's regime call last selected. Changes when the regime does; the
    book keeps trading through the switch, so this is "what it is following now", not "what produced
    every fill below"."""
    card_adopted_date: dt.date
    """When that card was adopted -- and, for a book that has never switched, this seat's own
    inception. See :attr:`Desk.starting_equity`'s note on why that is not the desk's inception."""
    orders_total: int
    orders_filled: int
    orders_pending: int
    orders_rejected: int
    """The staged-order ledger's four counts. `orders_total` is every record ever written to this
    book; the other three are its terminal and in-flight subsets. They need not sum to the total --
    `"cancelled"` and `"expired"` are legal statuses nothing sets today (see
    `app.workflow.book_models.OrderStatus`) -- so a renderer must not compute one from the others."""
    last_run_id: str | None = None
    last_run_state: str | None = None
    """`"succeeded"`, `"failed"`, `"cancelled"`, or `None` when no run has ever been recorded."""
    last_run_at: str | None = None
    """ISO-8601 UTC. When the most recent workflow run was created -- a real-time moment, not a
    session date, and deliberately not comparable to :attr:`PaperDeskState.as_of`."""
    last_run_outcome: str | None = None
    """One sentence on what that run actually did, taken from its own terminal stage record -- e.g.
    "no entry candidates fired". **This is the field that keeps a flat panel honest.** A seat showing
    $100,000 and no trades is either a strategy that found nothing or a pipeline that is broken, and
    nothing else on this desk distinguishes them."""
    exits: str = "none"
    """How this seat closes a position, in the reader's words -- the single most important fact about
    reading its return, so it travels on the wire rather than being assumed by the page.

    Two shapes, and a renderer must handle both. `"none"` means nothing ever closes a position: the
    seat buys and holds forever, its return is mostly its universe's beta, and the card's own stop and
    target are inert. Any other value is a sentence naming the exit rules actually in force -- the
    stop, the take-profit, the hold cap and the exit expression the selected card declares, which
    `app.workflow.exits` evaluates once a session and stages as a sell filled at the next open.

    **This was `"none"` for every seat until the exit path existed**, which is why `"none"` is still
    the default: a card that declares no stop, no target, no hold cap and no exit rule genuinely never
    sells, and a book whose daily step is not running does not close positions either no matter what
    its card says. The field describes the policy in force, not the card's declaration alone."""


class DeskRejection(_Frozen):
    """Every order this run refused under one mandate rule, grouped.

    Replaces the earlier ``rejections: list[str]`` -- a flat list of the bare rule slug, once per
    refused order, with no distinguishing detail -- which is what made 8 orders refused for
    insufficient cash across 3 symbols render as the same unlabelled string 8 times over. See
    `app.paperdesk.desk._group_rejections` for how the broker's per-order refusals collapse into
    one of these per rule.
    """

    rule: str
    """The stable mandate-rule slug, e.g. ``"insufficient_cash"`` -- see
    `app.paper.paperbroker.REJECTION_LABELS`."""
    label: str
    """A human title for `rule`, e.g. ``"Insufficient settled cash"`` -- from
    `app.paper.paperbroker.rejection_label`, which never raises on a slug it does not recognise."""
    count: int
    """Number of orders refused under this rule this run."""
    symbols: list[str]
    """Distinct symbols affected, sorted. May be empty when the source result only recorded the bare
    rule slug per refusal (a ladder or allocation card's run) rather than the full per-order detail
    a rules card's `AgentResult.rejection_details` carries."""
    detail: list[str]
    """One full reason sentence per refused order under this rule, newest first, capped at 20. Falls
    back to `label` per entry when only the bare rule slug was available (see `symbols` above)."""


class LiveFill(_Frozen):
    """One order the desk's live session actually filled -- priced off a real-time quote rather than
    a stored bar, because it fires for the session dated *after* the newest bar this application has
    stored, which does not exist as a session `run_card` can trade at all (see
    `app.paperdesk.desk`'s module docstring and `app.paper.paperbroker.PaperBroker.submit`'s own
    `live_quote_source` seam).

    **A live-priced projection of what the desk would do right now, recomputed on every request --
    never a persisted execution.** The paper desk has no trade ledger of its own; every other figure
    on :class:`Desk` (`trades`, `holdings`, `equity`, ...) is a deterministic replay of the same
    stored bars every time, which is exactly what makes it safe to cache and to audit. A live quote
    is neither: it changes from one call to the next with nothing about the stored bars saying so, so
    a :class:`LiveFill` is thrown away and recomputed fresh on every request rather than written
    anywhere -- see :attr:`Desk.live_fills`'s own docstring for why it must never reach the fields
    above this one.
    """

    symbol: str
    side: str
    """`"buy"` or `"sell"`."""
    quantity: str
    """Decimal string -- whole shares, or fractional if the mandate allows it."""
    price: str
    """Decimal string. The live quote with slippage applied -- what the fill actually cost, the same
    way every other `price` in this application already includes it."""
    quote_price: str
    """Decimal string. The live quote *before* slippage -- kept alongside `price` so the slippage
    assumption itself is visible, the same pairing `Fill.price`/`Fill.reference_open` already gives a
    historical fill (see `app.paper.paperbroker.Fill`)."""
    quote_ts: str
    """ISO-8601 UTC. When the quote this fill priced off was captured -- not the same clock as any
    stored bar's date, and a reader comparing a live fill's freshness needs this, not `as_of`."""
    notional: str
    """Decimal string. `quantity * price`."""


class SeatProvenance(_Frozen):
    """Where a seat came from -- the answer to "why is this card on the desk?".

    Two honest sources, and only two, because the roster has only two ways to gain a seat. A card
    auto-promoted through the evolution loop carries `source="promoted"` and the latest `generation`
    the genome cleared the gate in (`app.evolution.models.PromotionRecord.generations`, joined by
    `agent_id` from `promotions.jsonl`); the UI links it to the Loop view where that generation's run
    is shown. Every other seat is `source="owner"` with no `generation` and no link: the hand-authored
    roster constants in `app.paperdesk.desk`, and any card an operator rostered by hand, are here by a
    decision recorded in that module's own roster docstrings, not by a gate -- so there is no
    generation to name and nothing to link to. `"owner"` is a plain, deliberate fact, never an
    "unknown": a seat whose promotion record simply is not found is owner-seated by definition, which
    is exactly what the current all-hand-authored roster is."""

    source: Literal["promoted", "owner"]
    generation: int | None = None


class Desk(_Frozen):
    """One strategy card, its rules as submitted, and everything it has done since inception.

    **Two card shapes share this one response type -- `kind` says which.** Every desk this
    application has ever traded until now was a `StrategyCard`: a per-symbol universe with a boolean
    entry/exit rule, sized as a fixed fraction of equity per position (`entry`, `exit`,
    `max_positions`, `position_pct` below). `kind == "ladder"` is the first desk of a different
    shape -- a drawdown-triggered portfolio rotation with no per-symbol rule at all (see
    `app.tournament.ladder`'s own module docstring) -- and its rules live in the separate,
    optional :attr:`ladder` block instead of being force-fit into `entry`/`exit`, which would
    misrepresent how the card actually executes (see :class:`LadderDescription`'s own docstring).

    `kind` defaults to `"rules"` and every rule-shaped field below stays required in spirit (only
    loosened to `Optional` in the type system, never actually omitted for a rules card) specifically
    so this change is invisible to every desk this application already traded: an existing card's
    JSON, an existing test fixture and an existing frontend read all keep meaning exactly what they
    meant before a second `kind` existed.

    **`kind == "autopilot"` is the fourth shape, and the first that is not a card at all.** Its
    positions come from a persistent ledger of model-made decisions (`app.workflow.book`) rather than
    from any rule replayed against stored bars, so it fills :attr:`autopilot` and leaves every
    rule-shaped field `None` -- see :class:`AutopilotDescription`. It is the one desk on this page
    whose figures are read from a file rather than recomputed, which is precisely why it exists: a
    judgement made on day N cannot be re-derived on day N+1.
    """

    agent_id: str
    display_name: str
    discipline: str
    thesis: str
    kind: Literal["rules", "ladder", "allocation", "autopilot"] = "rules"
    """Which card *shape* produced this desk, and therefore which of the fields below are populated.

    `"allocation"` joins the other two here rather than being folded into `"rules"`: an allocation
    card holds continuous target weights across always-invested sleeves and rebalances on drift
    bands, so it has no `entry`/`exit` expression, no `position_pct` and no `max_positions` at all --
    the same reason `"ladder"` is its own kind. A renderer keying off `kind` therefore keeps working
    unchanged for the two shapes it already knew.
    """
    universe: list[str]
    entry: str | None = None
    """`None` only for `kind == "ladder"` -- see :class:`LadderDescription` for what that card shape
    reports instead. Always a string for `kind == "rules"`, exactly as before this field existed."""
    exit: str | None = None
    """Same `None`-only-for-a-ladder-card rule as :attr:`entry`."""
    stop_loss_pct: Decimal | None = None
    take_profit_pct: Decimal | None = None
    max_hold_days: int | None = None
    max_positions: int | None = None
    """`None` only for `kind == "ladder"`, which has no per-position slot count -- its book always
    holds all three sleeves at once, some possibly at a zero target weight."""
    position_pct: Decimal | None = None
    """`None` only for `kind == "ladder"`, which sizes every sleeve as a weight of the whole book, not
    a fixed fraction per position -- see `app.tournament.ladder.run_ladder_card`'s own docstring."""
    rank_by: str | None = None
    """The card's ranking-key expression, verbatim, or `None` if it set none -- see
    `app.tournament.models.StrategyCard.rank_by`.

    Carried on the wire because :attr:`Signal.rank_value` is meaningless without it: a column of
    numbers like `1.07`, `0.94` needs to say *what* was measured, and only this expression says so.
    `None` is also the signal to a client that :attr:`Signal.entry_rank` will be `None` throughout
    and that this desk's fills fall in `universe` order."""
    staged_orders: list[AutopilotOrder] = []
    """Orders staged but not yet filled -- see :class:`AutopilotOrder`.

    Non-empty only for `kind == "autopilot"`. Every other kind decides and fills inside one replayed
    session and never has an order in flight between requests, so `[]` is not a degraded state for
    them, it is the only state they can be in."""

    autopilot: AutopilotDescription | None = None
    """Present if and only if `kind == "autopilot"` -- see :class:`AutopilotDescription`.

    `"autopilot"` joins the other three kinds rather than being folded into `"rules"` for the same
    reason `"ladder"` and `"allocation"` are their own kinds: this desk has no per-symbol entry/exit
    expression, no `position_pct` and no `rank_by`, because its positions were chosen by a chain of
    model judgements recorded in a persistent ledger rather than by a rule replayed from bars. A
    renderer keying off `kind` keeps working unchanged for the three shapes it already knew.
    """

    ladder: LadderDescription | None = None
    """Present if and only if `kind == "ladder"` -- see :class:`LadderDescription`."""

    starting_equity: Money
    cash: Money
    positions_value: Money
    equity: Money
    total_return: Decimal
    """``equity / starting_equity - 1`` -- computed here from ``equity``, **not** read off
    ``AgentResult.total_return``. See :mod:`app.paperdesk.desk` for why (``strategy-program/
    DEFECTS.md`` D1)."""
    excess_return: Decimal | None = None
    """``total_return - benchmark.return_pct``. ``None`` when the benchmark itself is unpriced."""
    max_drawdown: Decimal
    """Read off ``AgentResult.max_drawdown`` unchanged -- see ``app.backtest.metrics.compute``,
    the single implementation this figure has."""
    capital_exposure: float | None = None
    """Read off ``AgentResult.capital_exposure`` unchanged."""
    realised_pnl: Money
    """Sum of ``RealisedTrade.pnl`` over every closed trade (``exit_reason != "open_at_end"``)."""
    unrealised_pnl: Money
    """Sum of every :class:`Holding`'s own mark-to-market P&L. A different figure from
    ``realised_pnl`` measuring a different thing -- see this package's module docstring for why a
    page must not add them into one number."""
    open_positions: int
    slots_free: int

    holdings: list[Holding]
    trades: list[Trade]
    decisions: list[Decision]
    signals: list[Signal]
    rejections: list[DeskRejection]
    """Grouped by rule, sorted by `count` descending then `rule` ascending -- see
    :class:`DeskRejection`."""
    rejection_count: int
    """Total orders refused across every rule this run, i.e. the sum of every group's `count` above.
    `0` when `rejections` is empty."""

    live_fills: list[LiveFill] = []
    """Orders this desk's *live* session -- today's already-computed signals, submitted against a
    real-time quote -- actually filled. Always `[]` when `Settings.paperdesk_live_fills` is off (the
    default), and always `[]` for `kind != "rules"` (see :func:`app.paperdesk.desk._build_ladder_desk`/
    `_build_allocation_desk`, which never attempt a live session at all) -- also `[]` when the flag is
    on but nothing fired this request, which is the ordinary case on most days.

    **Never mixed into `trades`, `holdings`, `equity` or any other field above this one, and that
    separation is the entire point of this field existing on its own.** Every figure above is a
    deterministic replay of stored bars -- the same input always produces the same output, which is
    what makes this an auditable performance record safe to cache. A live fill is priced off a quote
    that is different on every call with nothing in the stored bars saying so; folding it into the
    historical figures would make `equity`, say, silently stop being reproducible, and a record whose
    numbers move on refresh with no entry explaining why is worse than one that is simply a session
    behind. See :class:`LiveFill`'s own docstring for why this is a recomputed *projection*, not a
    persisted execution -- the paper desk keeps no trade ledger, live or otherwise."""
    live_rejections: list[DeskRejection] = []
    """The live session's own refusals, grouped the same way :attr:`rejections` is -- but never
    merged with it. A live rejection (the live quote source had nothing for a symbol this cycle, the
    live-priced order tripped the mandate's cash or weight cap) describes a moment in time, not the
    desk's audited history, so it is reported separately for the identical reason :attr:`live_fills`
    is kept apart from :attr:`trades`. `[]` under every condition :attr:`live_fills` is `[]` under."""
    live_as_of: str | None = None
    """ISO-8601 UTC timestamp of the live quote batch this session priced against, or `None` when no
    live session ran this request -- the flag is off, this desk is not a rules card, or the flag is on
    but no signal fired so no quote was ever fetched. Distinct from :attr:`~PaperDeskState.as_of`,
    which is a stored bar's *date*: this is a real-time moment, and a reader comparing the two sees
    exactly how far the live session sits ahead of the desk's own historical mark."""

    tax: PaperTaxSummary | None = None
    """After-tax / wash-sale summary for this desk's closed trades, computed by the real tax engine
    (:func:`app.paper.papertax.summarize_paper_tax`) over fills synthesised from
    :attr:`trades`/:attr:`holdings` -- see :func:`app.paperdesk.desk._fills_from_trades`.

    Populated if and only if `kind` is `"rules"` or `"autopilot"` **and** this desk's book is taxable
    (its purpose's `Funding.tax_treatment` is `"taxable"`, i.e. `SAVINGS` or `TRADING`) -- a
    Roth/savings-in-a-tax-advantaged-sense sleeve realises no taxable event, so a Roth desk always
    carries `None` here, and so does every ladder/allocation desk regardless of book: for those two,
    this field's cost basis math is built entirely from a `StrategyCard`-shaped trade log
    (`RealisedTrade`), and a ladder or allocation card's rebalance trims are not that shape.

    An `"autopilot"` desk qualifies by a different route and arrives at the same engine:
    `app.workflow.book.tax_summary` runs the real cost-basis and wash-sale engine over that book's
    own persisted fills, so the figure means exactly what it means on a rules desk. It is `None` for
    an autopilot seat whose book has no filled orders yet, which is the ordinary early state.

    Also `None` on a genuine computation failure -- see `_build_desk`'s own docstring for why a tax
    summary error degrades to `None` with a logged warning rather than ever failing the whole desk (or
    the whole page) the way one bad panel has before in this application."""

    provenance: SeatProvenance | None = None
    """Where this seat came from (`SeatProvenance`). Populated by `app.paperdesk.desk._book` for every
    seat after it is built; `None` only on a `Desk` constructed outside that path (a fixture, a
    partial). The frontend renders it as a small pill beside the discipline badge -- linked to the Loop
    view for a promoted seat, a plain label for an owner-seated one."""


class Funding(_Frozen):
    """How one book's money arrives, echoed from `app.tournament.purposes.PurposeSpec` for display.

    Read from `PURPOSE_SPECS` at build time rather than restated, so the page and the scorer cannot
    disagree about what a purpose is funded with. `shape` decides how the other fields read: a
    `lump_sum` book's `contribution` is `0` and means it, while a `monthly_contribution` book's
    `seed` is the opening deposit and `contribution` recurs on top of it.

    `horizon_years_max` is `None` for `trading` and that is a decision, not a gap --
    `strategy-program/THREE-PURPOSES-PLAN.md` section 1: "A purpose whose horizon is unstated is not
    the same as one whose horizon is short, and encoding a large number that pretends to be a bound
    would be worse than leaving it open." A renderer must show "unbounded", never a default.
    """

    purpose: str
    shape: str
    seed: Money
    contribution: Money
    horizon_years_min: int | None = None
    horizon_years_max: int | None = None
    tax_treatment: str


class Book(_Frozen):
    """One purpose's book: its funding, its own benchmark, and the desks trading it.

    Three books exist because three different questions are being asked and one leaderboard cannot
    rank all of them -- `strategy-program/THREE-PURPOSES-PLAN.md` section 2. A savings book funded
    monthly is helped by an early crash where a lump-sum trading book is hurt by a late one, and the
    plan measures that gap at 8.4 points on one strategy in one window. Merging them into one `desks`
    list, as this response did before, was asking all three questions with one answer.

    **Books carry no `inception` of their own, deliberately, and this is a divergence from the plan.**
    Section 7 describes each book "carrying its own funding, inception, benchmark and desks". The
    trading window here is derived from the benchmark's stored history against a single module-level
    `INCEPTION` (see :func:`app.paperdesk.desk._trading_window`), so all three books open on the same
    date and run the same sessions. A per-book `inception` today would be the same value written three
    times, and three copies of one fact is how two of them later disagree. It belongs on this model on
    the day a book actually starts on its own date -- funding a Roth from a different year, say -- and
    not before. The window stays on :class:`PaperDeskState`, where it is one fact.
    """

    purpose: str
    label: str
    funding: Funding
    starting_cash: Money
    """The book's opening capital -- `funding.seed`, repeated here because it is what every equity
    figure on the book's desks is measured against and a renderer should not have to reach through
    `funding` to find the denominator."""
    benchmark: Benchmark
    benchmarks: list[Benchmark] = []
    """Every benchmark this book is measured against, its own primary first.

    Per book, because a book measured against the wrong index is measured against the wrong thing:
    `trading` is scored against SPY, while `savings` and `roth` are scored against a 60/40 SPY/AGG
    blend. See `app.tournament.purposes.PurposeSpec.benchmark`, which is where the choice lives.
    """
    notes: list[str] = []
    desks: list[Desk]


class InceptionUpdateRequest(BaseModel):
    """Body for ``PUT /api/paperdesk/inception``: the desk's new inception, ``YYYY-MM-DD``.

    Not `_Frozen`'s sibling: a request body is consumed once by the route handler and never echoed
    back verbatim, unlike every other model in this module, which are all response shapes."""

    model_config = ConfigDict(extra="forbid")

    inception: dt.date


class FetchSummary(_Frozen):
    """What one press of the page's fetch button actually pulled from the market provider.

    **Populated only by ``POST /api/paperdesk/refresh?fetch=true``; ``None`` everywhere else.**
    ``GET /api/paperdesk/state`` reads the store and never touches the network, so a summary there
    would either be a lie or a stale copy of some earlier fetch's counters. ``None`` is the honest
    answer to "what did this response fetch" when the answer is "nothing", and it keeps every route
    on the one response shape this router deliberately serves (see :mod:`app.api.paperdesk`).

    **The three outcome counters are separate on purpose and are never folded into a single
    "succeeded".** ``advanced`` means that symbol's newest stored session moved forward;
    ``unchanged`` means the provider answered normally and the newest stored session stayed put (the
    ordinary case for every symbol on a weekend, or for a second press minutes after the first);
    ``failed`` means it did not answer at all. Collapsing ``advanced`` and ``unchanged`` together
    would make "the market is closed and everything is already current" indistinguishable from
    "forty symbols just moved", which is the single question a person presses this button to answer.

    **``advanced`` is measured against the store, not inferred from the response size.** The first
    draft of this model counted a symbol as updated whenever ``sync_bars`` reported any rows, and
    ``sync_bars`` deliberately re-requests a short overlap behind the newest stored bar
    (``app.market.store._OVERLAP``) so a revised session is picked up. Every symbol therefore came
    back with rows every single time, and the page cheerfully reported "28 with new bars" on a
    second press two minutes after the first, having stored no new session at all. The counter now
    compares the symbol's own newest stored session either side of the sync, which is the only
    reading of "did this do anything" that a re-sent overlap cannot fake.
    """

    requested: int
    """How many symbols the fetch asked for -- ``app.paperdesk.desk.universe_symbols``' own count,
    every book's cards plus every benchmark. Always equals ``advanced + unchanged + failed``."""
    advanced: int
    """Symbols whose newest stored session moved forward as a result of this fetch."""
    unchanged: int
    """Symbols the provider answered for whose newest stored session did not move. Not a failure,
    and deliberately not counted as one -- see this class's docstring."""
    failed: int
    """Symbols whose fetch raised -- a provider outage, a rate limit, a symbol the provider does not
    know. One bad symbol never aborts the sweep; see :func:`app.paperdesk.fetch.fetch_all`."""
    rows_merged: int
    """Total bars the provider returned and this store merged, across every symbol.

    **Not a count of new sessions**, and never to be presented as one: ``sync_bars`` asks for a
    short overlap behind the newest stored bar on every call, so most of these rows are rewrites of
    sessions already held. It is a measure of how much data moved, useful for spotting a fetch that
    returned nothing at all; :attr:`advanced` is the measure of whether anything changed."""
    failures: list[str]
    """``"SYMBOL: reason"`` for each failure, in fetch order. The detail behind :attr:`failed`, not a
    replacement for it -- a client must be able to say "3 failed" without parsing prose."""

    started_at: dt.datetime
    finished_at: dt.datetime
    """Both UTC and timezone-aware (``dt.datetime.now(dt.UTC)``, never the deprecated ``utcnow``) --
    the same rule ``app.market.calendar`` states for its own ``generated_at``."""
    duration_seconds: float
    """Wall time of the whole sweep, so a client can say "took 38s" without differencing two
    timestamps client-side and getting the timezone handling wrong."""

    latest_bar_before: dt.date | None = None
    latest_bar_after: dt.date | None = None
    """The benchmark's newest stored session either side of the fetch, or ``None`` if the benchmark
    had no stored bars at all. These are what tell a reader whether the fetch actually moved the
    desk's mark forward: forty ``updated`` symbols with an unmoved ``latest_bar`` means fresh
    *intraday-adjacent* data arrived for the constituents but no new session did, and the page's
    ``as_of`` will not have changed. Read them together with :attr:`updated`, never instead of it."""


class PaperDeskState(_Frozen):
    """The whole paper desk page in one response.

    **The trading window is global; funding, benchmarks and desks are per book.** See :class:`Book`
    for why `inception` stays here rather than being copied into each of the three.
    """

    inception: dt.date
    as_of: dt.date
    """The last traded session's own date -- always equal to :attr:`latest_bar`. The newest stored
    session is itself decided on the prior session's close and filled at its own open, both already
    in the store, so it is fully tradeable; see :mod:`app.paperdesk.desk`'s module docstring for why
    this is not one session behind."""
    latest_bar: dt.date
    """The most recent daily bar this application has stored for the benchmark, full stop --
    independent of whether any desk has traded through it yet. Equal to :attr:`as_of`."""
    stale_days: int
    """``today - latest_bar``, in calendar days -- how far behind the real wall clock the stored
    data itself is. This is the only staleness figure in this response; there is no separate gap
    between :attr:`as_of` and :attr:`latest_bar` to conflate it with."""
    first_session: dt.date
    sessions: int

    inception_default: dt.date
    """``app.paperdesk.desk.INCEPTION`` -- the desk's inception when no runtime override is in
    effect. Carried on the wire so a client can render "back to default" without hardcoding the date
    itself, and so it can tell a custom inception apart from the default one even when an operator has
    (legitimately) set the override *to* the default date."""
    inception_is_custom: bool
    """Whether an inception override file is currently in effect -- see
    ``app.paperdesk.desk.effective_inception``. `False` both when no override file exists and when one
    exists but was malformed and fell back to :attr:`inception_default`: a fallback is not "an
    override in effect" any more than a missing file is."""
    design_cutoff: dt.date
    """``app.tournament.models.DESIGN_THROUGH`` -- the last session any tournament analyst was
    permitted to have looked at while designing. Carried here so a client can explain
    :attr:`in_sample_sessions` without a second lookup."""
    in_sample_sessions: int
    """How many of this window's :attr:`sessions` fall at or before :attr:`design_cutoff` -- an
    honesty flag, not a refusal. `0` for the desk's own default inception, since that inception is
    entirely after the cutoff (see ``INCEPTION``'s own docstring), but a user-settable inception can
    move it back inside the design window, at which point returns over those sessions are fitted, not
    forward -- see ``app.paperdesk.desk._in_sample_note``, which is what adds a note to
    :attr:`PaperDeskState.notes` whenever this is nonzero."""
    earliest_inception: dt.date
    """The benchmark's first ever stored session. `PUT /api/paperdesk/inception` refuses any date
    before this outright -- see ``app.paperdesk.desk.set_inception``."""
    latest_inception: dt.date
    """The latest date that still yields at least one tradeable session -- equal to
    :attr:`latest_bar`, since an inception dated on the newest stored bar trades exactly that one
    session. `PUT /api/paperdesk/inception` refuses any date after this outright."""

    notes: list[str]
    """Notes about the desk as a whole. A note that is true of one book only belongs on that
    :class:`Book`, not here -- the single-name-cap and candidate-tier notes moved accordingly."""

    fetch: FetchSummary | None = None
    """What the request that produced this response pulled from the market provider, or ``None``
    when it pulled nothing. Only ``POST /api/paperdesk/refresh?fetch=true`` ever sets this; see
    :class:`FetchSummary` for why a state read leaves it ``None`` rather than reporting some earlier
    fetch's counters."""

    books: list[Book]
    """One per `app.tournament.purposes.Purpose`, in `savings`, `trading`, `roth` order.

    A book with an empty `desks` list is a real, renderable state, not a bug: a purpose can be
    defined and funded before any card has been designed for it. The page must say "no cards seated
    for this purpose yet" rather than hiding the book, because a hidden book reads as a purpose that
    does not exist.

    **This replaced flat `starting_cash`/`benchmark`/`benchmarks`/`desks` fields.** Those described
    one book, and there are three; keeping them alongside would have meant either a fourth answer
    that is none of the three, or a silent privileging of one purpose as "the" desk. See
    `strategy-program/THREE-PURPOSES-PLAN.md` section 7.
    """

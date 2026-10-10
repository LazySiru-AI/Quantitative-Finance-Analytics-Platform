"""A third card shape: a drawdown-triggered rotation between a defensive book and a leveraged
sleeve, and the engine to run it.

**Why this is a new module rather than new fields on `StrategyCard` or `AllocationCard`.** This
strategy has no per-symbol boolean rule at all -- `StrategyCard.entry`/`.exit` cannot express it, and
`allocation.AllocationCard.rules` cannot either: a `TiltRule` fires or does not on one symbol's own
bars (see that module's docstring), but this strategy's every decision is driven by one shared
signal -- SPY's drawdown from its own all-time closing high -- read once per session and applied to
the whole book at once, with a state machine (armed rungs, a confirmation gate, a recovery clock) that
has no analogue in either existing shape. `allocation.py`'s own module docstring already explains why
bolting a second, unrelated decision shape onto a frozen, widely-depended-on contract as a bag of
optional fields is the wrong move; the same argument applies a second time here, one level further
out -- an allocation card's sleeves rebalance toward *independently declared* target weights, while a
ladder card's sleeve weights are *entirely computed* from one external index's state. Forcing that
through `AllocationCard.sleeves`/`.rules` would mean either faking a `TiltRule` per rung (impossible --
a rung's condition is "how deep is SPY's drawdown *right now*, and did it already breach a shallower
rung this cycle", not a fact about any one sleeve's own bars) or adding an `if card.is_ladder: ...`
branch inside `allocation.py` that this package was explicitly told not to touch.

**The specification this module ports, verbatim.** `strategy-program/tools/drawdown_ladder.py`'s
`Ladder`/`run_ladder` is the settled backtest this card type exists to seat on the paper desk -- not a
sketch to improve on. Every rule below is that file's own rule, restated against this repository's
own market-data/broker machinery instead of the reference script's plain float arithmetic:

* **Bounce confirmation** (:meth:`LadderCard.confirm_ma`, :func:`_confirmed`). A rung fires only once
  SPY has closed back above its own `confirm_ma`-session average -- the reference script's own
  comment on this rule is not a stylistic choice: without it the ladder reaches its deepest rung (80%
  leveraged) at the *worst* possible moment of a 2008-shaped decline, because "drawdown crossed -30%"
  is true every single day of the plunge, not only on the day it started recovering. With the
  confirmation gate on, the reference script's own measurement over 2006-2011 moves the ladder's MAR
  from 0.06 to 0.25 and its max drawdown from -72.7% to -55.0%. This is the single most important rule
  in the whole card, named first here for the same reason it is named first in the task brief.
* **Once-per-cycle arming** (`armed_depth`, only ever rising until a full reset). A rung fires once and
  re-arms only when the ladder fully exits back to the base state -- without this, an index chopping
  around one rung's threshold (April 2025 is the reference script's own named example) round-trips the
  whole book on every touch, which is a slippage pump wearing a strategy's clothes.
* **Gap-through** (:func:`_weight_for` scans every rung and keeps the deepest one breached). A close at
  -21% that never printed -10% first jumps straight to the -20% rung's weight in one trade, rather than
  stepping through a rung the index never actually touched.
* **Recovery, not a ratchet.** "Halve the leveraged sleeve on a new high" alone never reaches zero --
  60% halves to 30%, then 15%, forever -- so leverage would accumulate across cycles with no rule ever
  closing it. The full exit (`recovery_gain` above the high the cycle started from, or
  `recovery_sessions` after the new high, whichever comes first) is what actually closes the position
  and re-arms the ladder, and it is not optional the way the reference script's own `time_stop` is.
* **No time stop.** The reference script's `time_stop` field (cut a stalled leveraged position in half
  after N sessions with no new high) exists in that file and is off by default, because it was tested
  and rejected -- cutting leverage mid-drawdown on a mechanical clock, rather than on a signal, is what
  turned the reference script's own 2006-2011 CAGR negative by selling into the trough and missing the
  recovery that followed. This module has no `time_stop` field at all, not merely one left `None`
  -- the reference script's own finding is that trying it is actively harmful, not neutral, so there is
  nothing here for a future card author to accidentally turn back on.

**The one addition this task's brief makes that the reference script does not model: a defensive
sleeve split in two.** The reference script trades exactly two sleeves -- one defensive symbol, one
leveraged symbol -- and a "weight" is simply the leveraged fraction, with `1 - weight` implicitly all
in the defensive sleeve. This card's own specification splits that defensive half into SCHD (equity)
and IEF (duration) at a declared 60/40 base ratio, and funds the leveraged sleeve *out of IEF first,
then SCHD* as the rungs deepen (see :func:`_sleeve_targets`). The signal, the rungs, the confirmation
gate, the arming, the gap-through and the recovery clock are all computed exactly as the reference
script computes them, against one scalar "how much leveraged exposure does the ladder currently want";
only the last step -- turning that one scalar into three sleeve weights instead of the reference
script's two -- is new arithmetic, and it is a pure function with no state of its own
(:func:`_sleeve_targets`), so it cannot change when a rung fires or how the confirmation gate behaves.

**What is reused, deliberately, rather than re-derived**, mirroring `allocation.py`'s own module
docstring: `app.paper.marketdata.AsOfMarket`/`SessionCalendar` for lookahead-safe bars,
`app.paper.paperbroker.PaperBroker` for fills, `app.backtest.metrics.compute` for every summary
statistic, and four of `app.tournament.runner`'s private helpers that are generic rather than
`StrategyCard`-shaped: `_require_decision_market`/`LookaheadError` (the lookahead assertion),
`_entry_quantity` (notional -> whole-or-fractional shares, floored), `_benchmark_return` (buy-and-hold
on the tournament's own SPY benchmark) and `_undilute_exposure` (the D1-alignment-point exposure fix).
None of these four read or write anything `StrategyCard`-specific, exactly as `allocation.py`'s own
docstring establishes for the same four (plus two more this module has no use for, since a ladder card
has no rule-DSL expression anywhere in it to guard or build a signal table from).

**What is duplicated rather than imported, and why.** `_Frozen`, the weighted-average-cost sleeve
bookkeeping (`_SleevePosition`/`_apply_buy`/`_apply_sell`) and the per-session book-weight reader
(`_current_weights`) all already exist, nearly verbatim, in `allocation.py` -- and are duplicated here
rather than imported from it, for the same reason `allocation.py` itself duplicates
`app.tournament.models._Frozen` instead of importing it (see that module's own docstring): two
independently-frozen card shapes that happen to need the same small piece of bookkeeping should not be
coupled to each other's internals just because the coincidence is convenient today. If `allocation.py`
ever changes how a sleeve's average cost is computed, that is a decision about allocation cards
specifically, and this module silently inheriting it through an import would be exactly the kind of
cross-module coupling this repository's "second card shape" precedent was written to avoid.

**Why this returns `LadderResult`, a new type, rather than `AllocationResult` or `AgentResult`.**
Every field `AllocationResult` carries (`sessions`, `starting_equity`, ..., `trades`, `rejections`,
`benchmark_return`) is exactly what a ladder run also produces, and abstractly the two "second card
shape" results look identical. But `AllocationResult.card` is typed `AllocationCard` specifically --
not `BaseModel`, not a union -- and pydantic validates a field typed to one model class by checking
`isinstance` against exactly that class before accepting anything else (this is `allocation.py`'s own
finding, empirically confirmed there: a `LadderCard` instance is no more an `AllocationCard` than an
`AllocationCard` is a `StrategyCard`, and would be rejected the identical way). Subclassing
`AllocationCard` to satisfy the check would resurrect the "bag of fields with no meaning for this
strategy" problem `allocation.py`'s own docstring already rejected once, one level further down. So
:class:`LadderResult` is defined here, field-for-field identical to `AllocationResult` except `card:
LadderCard` -- and, like `AllocationResult`, it is **not** `app.tournament.models.AgentResult` and
`isinstance(result, AgentResult)` is `False` for the same reasons `allocation.py`'s docstring gives at
length for its own result type. `app.paperdesk.desk` is the one caller in this repository that reads a
ladder run's result, and it reads `LadderResult` by its own attributes, never through an `AgentResult`-
shaped path.
"""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
from typing import Self

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.backtest import metrics
from app.backtest.models import BARS_PER_YEAR, ExitReason
from app.backtest.models import Trade as MetricsTrade
from app.config import Settings
from app.core.models import Money
from app.market.models import Interval
from app.paper.marketdata import AsOfMarket, SessionCalendar, UnpricedSymbol
from app.paper.paperbroker import Fill, Mandate, Order, PaperBroker
from app.tournament.models import (
    DESIGN_THROUGH,
    TRADE_END,
    TRADE_START,
    RealisedTrade,
    RejectionRecord,
)
from app.tournament.purposes import Purpose
from app.tournament.runner import (
    LookaheadError,
    _benchmark_return,
    _entry_quantity,
    _require_decision_market,
    _undilute_exposure,
)

__all__ = [
    "LadderCard",
    "LadderResult",
    "LookaheadError",
    "Rung",
    "run_ladder_card",
]

_CENTS = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    """Round to cents, half-up -- the same convention every other module in this application applies
    to a cash figure at the point it becomes one."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


class _Frozen(BaseModel):
    """Deliberately a separate definition from both `app.tournament.models._Frozen` and
    `app.tournament.allocation._Frozen` -- see this module's own docstring, and `allocation.py`'s, for
    why one small duplicated class is cheaper than coupling three independently-frozen card shapes to
    each other's private names."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# The card
# ---------------------------------------------------------------------------


class Rung(_Frozen):
    """One step of the ladder: at or below `drawdown`, the leveraged sleeve's target weight is
    `leveraged_weight` -- exactly `strategy-program/tools/drawdown_ladder.py`'s own `Rung`, restated
    as a frozen, JSON-able model instead of a plain dataclass."""

    drawdown: Decimal
    """A negative fraction of one -- `Decimal("-0.10")` is a 10% drawdown from the all-time high.
    Validated strictly negative below: a rung at `0` or positive would fire on every session,
    including one at a new all-time high, which is not a drawdown at all."""

    leveraged_weight: Decimal
    """Fraction of the whole book the leveraged sleeve targets once this rung has fired. A fraction
    of one, strictly between 0 (exclusive -- a rung that targets 0% is not a rung, it is the base
    state every cycle already re-arms to) and 1 (inclusive)."""

    @model_validator(mode="after")
    def _drawdown_is_negative(self) -> Self:
        if not (Decimal(-1) <= self.drawdown < Decimal(0)):
            raise ValueError(
                f"rung drawdown must be a negative fraction of one, in [-1, 0) -- got "
                f"{self.drawdown}. Use Decimal('-0.10') for a 10% drawdown, never a positive number "
                "or the literal percentage."
            )
        return self

    @model_validator(mode="after")
    def _leveraged_weight_is_a_fraction_of_one(self) -> Self:
        if not (Decimal(0) < self.leveraged_weight <= Decimal(1)):
            raise ValueError(
                f"rung leveraged_weight must be a fraction of one in (0, 1] -- got "
                f"{self.leveraged_weight}. Use Decimal('0.20') for 20%, never the literal percentage."
            )
        return self


class LadderCard(_Frozen):
    """One analyst's submission for a drawdown-triggered rotation between a defensive book and a
    leveraged sleeve. See this module's own docstring for the mechanism, and for exactly which parts
    of it are the reference script's own settled specification versus this task's own addition (the
    SCHD/IEF split)."""

    agent_id: str
    """Short slug, unique within whatever this card is compared alongside. Becomes a report filename
    the same way `StrategyCard.agent_id` and `AllocationCard.agent_id` do."""

    display_name: str

    purpose: Purpose = Purpose.TRADING
    """Which of the three investment goals (`app.tournament.purposes.Purpose`) this card serves -- see
    `StrategyCard.purpose`/`AllocationCard.purpose` for the same field, restated a third time because
    this is a third, independently frozen model with no shared base to hang one shared docstring on
    (the identical reason `LadderCard.thesis`, below, restates its own requirement a third time).

    Defaults to `Purpose.TRADING`, the trading-purpose card this ladder already is by omission today --
    which matters more here than for the other two card shapes, because `Purpose.ROTH` is exactly the
    purpose this card was designed for
    (`strategy-program/THREE-PURPOSES-PLAN.md` section 1: "tax-free compounding of the allocation
    strategies") and cannot yet correctly declare. The plan's own section 9 says so plainly: "The Roth
    cannot hold the ladder as it stands if the taxable books trade QLD, SCHD or IEF" -- the ladder
    committed today trades exactly those three symbols, so setting its `purpose` to `Purpose.ROTH`
    while a taxable card also holds one of them would immediately trip
    `app.tournament.purposes.find_disjointness_violations`. Leaving the default at `Purpose.TRADING`
    correctly describes the card's *current* state rather than silently resolving a conflict this
    change was not scoped to fix; re-expressing the ladder on disjoint tickers (or retiring the
    taxable books' overlapping holdings) is deferred, per this task's own scope fence."""

    thesis: str
    """Why this should work, written **before** the trading window ran -- see
    `StrategyCard.thesis`/`AllocationCard.thesis` for the same requirement, restated a third time
    because this is a third, independently frozen model, not a relaxation of either existing one."""

    falsification: str | None = None
    """What measurement would make this card's `thesis` wrong -- see `StrategyCard.falsification` and
    `AllocationCard.falsification`, restated a third time for the same reason `thesis` is: three
    independently frozen models with no shared base to hang one docstring on.

    The seated card of this shape, `ladder-sso-vig-bnd`, is the best-documented card on the desk by
    the thesis audit's count -- it states **three** distinct falsification conditions in prose and,
    for the third, explicitly declines to pre-empt the answer ("see that script's own report for the
    measured number, not a claim made here in advance of running it"). That is the standard this
    field is meant to carry, not a lower one."""

    signal_symbol: str
    """The index whose drawdown from its own all-time closing high drives every decision -- SPY in
    every card this repository ships, but named rather than hardcoded so a future card can trade the
    identical mechanism against a different index without a new card *type*."""

    defensive_symbol: str
    """The equity defensive sleeve -- SCHD."""

    bond_symbol: str
    """The duration sleeve QLD is funded out of first -- IEF. See :func:`_sleeve_targets`."""

    leveraged_symbol: str
    """The leveraged sleeve the ladder rotates into as SPY's drawdown deepens -- QLD."""

    base_defensive_weight: Decimal
    """The defensive sleeve's weight in the base state (0% leveraged) -- `Decimal("0.60")`."""

    base_bond_weight: Decimal
    """The bond sleeve's weight in the base state -- `Decimal("0.40")`. Must sum with
    `base_defensive_weight` to exactly `1`, the same "never silently normalised" discipline
    `AllocationCard._weights_are_a_complete_partition` applies to its own sleeve weights, for the
    identical reason: an analyst's `0.55`/`0.40` typo (five points of the book unaccounted for) must
    be rejected, not quietly renormalised into a base state the analyst never actually wrote."""

    rungs: tuple[Rung, ...] = Field(min_length=1, max_length=8)
    """Every rung, in order of increasing depth. At least one -- a ladder with no rung never leaves
    its base state and is a buy-and-hold card wearing this one's clothes. Order and monotonicity are
    enforced by :meth:`_rungs_are_sorted_and_strictly_deepen`, because :func:`_weight_for` depends on
    it: it is a scan for "the deepest rung breached", not a sort, and a card whose rungs were declared
    out of order would silently compute the wrong deepest rung."""

    confirm_ma: int = Field(ge=2, le=252)
    """Session count for the bounce-confirmation moving average -- see this module's docstring's
    first bullet. `2` is the shortest average that means anything as a trend filter; `252` (one
    trading year) is generous enough that anything longer is not really a *bounce* confirmation any
    more."""

    ath_haircut: Decimal
    """On a new all-time high, the leveraged sleeve's weight is multiplied by this rather than sold
    outright -- `Decimal("0.5")` halves it. A fraction of one, strictly between 0 and 1: `0` would be
    a full exit on the very first new high (which the recovery rule already handles on its own, more
    deliberately -- see `recovery_gain`/`recovery_sessions`), and `1` would mean a new high never
    reduces leverage at all, silently disabling the rule this field exists to express."""

    recovery_gain: Decimal
    """Full exit once SPY closes this fraction above the high the *current cycle* started from --
    `Decimal("0.10")` is 10%. A fraction of one, strictly greater than 0: `0` would mean "exit at the
    cycle's starting high itself", which is indistinguishable from never having made a new high at
    all and would fire on the very session `ath_haircut` already fired on."""

    recovery_sessions: int = Field(ge=1, le=1260)
    """Full exit this many sessions after the new high that triggered the haircut, whichever of this
    or `recovery_gain` comes first -- see this module's docstring on why *some* clock closing the
    position is what stops "halve on a new high" from ratcheting leverage upward forever. `1260` is
    five trading years, a generous outer bound rather than a claim about what the reference script's
    own default (60) should be."""

    designed_through: dt.date
    """The last session the analyst looked at. Must not exceed
    `app.tournament.models.DESIGN_THROUGH` -- see :meth:`_designed_through_is_before_the_cutoff`."""

    @property
    def universe(self) -> tuple[str, ...]:
        """Every sleeve this card trades, in a fixed order -- leveraged last, matching the order
        `_sleeve_targets` builds its returned mapping in. Named to match `StrategyCard.universe` and
        `AllocationCard.universe` deliberately, for the same reason `AllocationCard.universe`'s own
        docstring gives: a caller that already knows how to price or guard a universe of symbols reads
        the same way here."""
        return (self.defensive_symbol, self.bond_symbol, self.leveraged_symbol)

    @model_validator(mode="after")
    def _designed_through_is_before_the_cutoff(self) -> Self:
        if self.designed_through > DESIGN_THROUGH:
            raise ValueError(
                f"designed_through={self.designed_through.isoformat()} is after the design cutoff "
                f"{DESIGN_THROUGH.isoformat()}. The trading window starts "
                f"{TRADE_START.isoformat()}; a strategy designed with sight of it is fitted to the "
                "data it is about to be scored on, and its result would measure nothing -- the same "
                "rule `StrategyCard` and `AllocationCard` each enforce, restated here because this is "
                "a third, independent model."
            )
        return self

    @model_validator(mode="after")
    def _symbols_are_pairwise_distinct(self) -> Self:
        symbols = (self.defensive_symbol, self.bond_symbol, self.leveraged_symbol)
        if len(set(symbols)) != len(symbols):
            raise ValueError(
                f"defensive_symbol, bond_symbol and leveraged_symbol must be three distinct symbols "
                f"-- got {symbols}. A sleeve cannot fund itself or be funded from itself."
            )
        return self

    @model_validator(mode="after")
    def _base_weights_sum_to_one_and_are_fractions(self) -> Self:
        for name, value in (
            ("base_defensive_weight", self.base_defensive_weight),
            ("base_bond_weight", self.base_bond_weight),
        ):
            if not (Decimal(0) < value < Decimal(1)):
                raise ValueError(
                    f"{name} must be a fraction of one, strictly between 0 and 1 -- got {value}"
                )
        total = self.base_defensive_weight + self.base_bond_weight
        if total != Decimal(1):
            raise ValueError(
                f"base_defensive_weight + base_bond_weight = {total}, not 1 -- the base state (0% "
                "leveraged) must be a complete partition of the book, and is never silently "
                "normalised. Fix the card's own numbers, the same discipline "
                "`AllocationCard._weights_are_a_complete_partition` applies to its own sleeve weights."
            )
        return self

    @model_validator(mode="after")
    def _rungs_are_sorted_and_strictly_deepen(self) -> Self:
        for prior, current in zip(self.rungs, self.rungs[1:], strict=False):
            if not (current.drawdown < prior.drawdown):
                raise ValueError(
                    f"rungs must be declared shallowest-first with strictly deepening drawdown -- "
                    f"{prior.drawdown} is not deeper than {current.drawdown}. "
                    ":func:`_weight_for` scans in declared order and keeps the deepest breached rung; "
                    "an out-of-order or repeated drawdown would make that scan silently wrong."
                )
            if not (current.leveraged_weight > prior.leveraged_weight):
                raise ValueError(
                    f"rungs must strictly increase leveraged_weight as drawdown deepens -- "
                    f"{current.leveraged_weight} does not exceed {prior.leveraged_weight} at a deeper "
                    "drawdown. A ladder whose deeper rung targets less leverage than a shallower one "
                    "is not a ladder."
                )
        return self


# ---------------------------------------------------------------------------
# The result -- see this module's own docstring's closing section for exactly how, and how far, this
# mirrors `app.tournament.allocation.AllocationResult`, and why it cannot be that class outright.
# ---------------------------------------------------------------------------


class LadderResult(_Frozen):
    """What one ladder card did over the trading window. Field-for-field identical to
    `app.tournament.allocation.AllocationResult` except `card: LadderCard` -- see this module's own
    docstring for why that one field forces a new type rather than reusing `AllocationResult` or
    `app.tournament.models.AgentResult` outright."""

    card: LadderCard
    sessions: int
    starting_equity: Money
    ending_equity: Money

    total_return: Decimal
    max_drawdown: Decimal
    """From `app.backtest.metrics.compute`, never recomputed here -- this repository has already
    shipped a defect from two drawdown implementations disagreeing (see `allocation.py`'s own
    docstring), and this module has no interest in becoming a third."""

    sharpe: float | None = None
    sortino: float | None = None
    volatility: float | None = None
    exposure: float | None = None
    capital_exposure: float | None = None
    """`invested_value / equity` at each session's own close, averaged across sessions -- the
    identical quantity and the identical reasoning `AllocationResult.capital_exposure`'s own docstring
    gives: a ladder's sleeves are resized on every rebalance and their dollar size is meant to compound
    with the book, so entry-notional-over-starting-equity (the `StrategyCard` convention) is the wrong
    denominator here for the same reason it is wrong for an allocation card."""
    win_rate: float | None = None
    profit_factor: Decimal | None = None
    realised_reward_risk: Decimal | None = None

    trades: tuple[RealisedTrade, ...] = ()
    """Reuses `app.tournament.models.RealisedTrade` unmodified, exactly as `AllocationResult.trades`
    does and for the identical reason: nothing in that type names any other card shape. `exit_reason`
    here reads `"rebalance_trim"` for an interim sell at a state transition and `"open_at_end"` for
    whatever is still held when the window closes -- the same two values `AllocationResult.trades`
    introduced, reused rather than a fourth vocabulary invented for a third card shape that needs the
    identical two concepts."""
    rejections: tuple[str, ...] = ()
    rejection_details: tuple[RejectionRecord, ...] = ()
    """The same refusals as `rejections` above, structured: `rule`, `symbol` and the broker's full
    `reason` sentence for each, in the order the broker recorded them -- additive alongside
    `rejections`, for the identical reason `AgentResult.rejection_details` gives (see that field's own
    docstring in `app.tournament.models`). This is what `app.paperdesk.desk` groups into
    `app.paperdesk.models.DeskRejection` instead of discarding the reason text and repeating the bare
    rule slug once per refused order."""

    benchmark_return: Decimal | None = None
    p_value: float | None = None
    q_value: float | None = None
    notes: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# The state machine -- ported from strategy-program/tools/drawdown_ladder.py's `Ladder.weight_for`
# and `run_ladder`. See this module's own docstring for exactly which rule each piece below encodes.
# ---------------------------------------------------------------------------


def _weight_for(rungs: tuple[Rung, ...], drawdown: Decimal) -> Decimal:
    """The deepest rung `drawdown` has reached, or `0` if it has not breached the shallowest one.

    A scan, not a binary search or a sort -- `rungs` is already validated shallowest-first
    (:meth:`LadderCard._rungs_are_sorted_and_strictly_deepen`), and every rung `drawdown` has breached
    keeps overwriting `weight`, so the last (deepest) one breached wins. This is exactly
    `strategy-program/tools/drawdown_ladder.py`'s own `Ladder.weight_for`, restated against `Decimal`
    rungs instead of that file's plain floats.
    """
    weight = Decimal(0)
    for rung in rungs:
        if drawdown <= rung.drawdown:
            weight = rung.leveraged_weight
    return weight


def _confirmed(card: LadderCard, market: AsOfMarket) -> bool:
    """Has `card.signal_symbol` closed back above its own `confirm_ma`-session average, as of
    `market.as_of`? The bounce condition -- see this module's docstring's first bullet for why this
    single gate is what separates a working ladder from one that reaches 80% leverage at the bottom of
    a crash.

    A plain trailing mean, not a recursive indicator: `sma(n)` forgets everything older than its own
    window, so a bounded lookback is exact here (unlike `ema`/Wilder `rsi` -- see
    `AsOfMarket.history`'s own docstring on why *those* need `lookback_days=None`). `confirm_ma + 5`
    sessions of calendar lookback is comfortably enough to cover `confirm_ma` *trading* sessions even
    across a long weekend or a holiday cluster.
    """
    history = market.history(card.signal_symbol, lookback_days=card.confirm_ma * 2 + 10)
    if len(history) < card.confirm_ma:
        return False
    window = history["close"].to_numpy(dtype=float)[-card.confirm_ma :]
    return float(window[-1]) > float(window.mean())


def _sleeve_targets(card: LadderCard, leveraged_weight: Decimal) -> dict[str, Decimal]:
    """Turn one scalar -- how much leveraged exposure the ladder currently wants -- into three sleeve
    weights that sum to exactly `1`.

    **QLD is funded from IEF first, then SCHD** -- the one piece of arithmetic this module adds on top
    of the reference script's own two-sleeve model (see this module's own docstring). The bond sleeve
    absorbs the first `base_bond_weight` fraction of whatever the leveraged sleeve needs; only once the
    bond sleeve has been drawn down to zero does the defensive sleeve give up any of its own weight.
    This is a `min`/`max` clamp, not a proportional split, precisely because the card's own
    specification states an *order* ("first ... then ..."), not a blend -- a proportional split would
    draw down both sleeves simultaneously and would not reduce to "SCHD alone absorbs the last 40
    points" once the leveraged weight exceeds `base_bond_weight`, which is the behaviour the
    specification actually asks for.

    Sum-preserving by construction: `leveraged_weight + bond + defensive` is
    `leveraged_weight + max(0, base_bond - leveraged_weight) + (1 - leveraged_weight - bond)`, which
    collapses to exactly `1` regardless of how large `leveraged_weight` gets (bounded at `1` by
    `Rung.leveraged_weight`'s own validator), the identical invariant
    `AllocationCard._weights_are_a_complete_partition` establishes for its own sleeves.
    """
    bond = max(Decimal(0), card.base_bond_weight - leveraged_weight)
    defensive = Decimal(1) - leveraged_weight - bond
    return {
        card.leveraged_symbol: leveraged_weight,
        card.bond_symbol: bond,
        card.defensive_symbol: defensive,
    }


# ---------------------------------------------------------------------------
# Sleeve bookkeeping -- weighted-average cost, duplicated from `allocation.py` rather than imported.
# See this module's own docstring for why.
# ---------------------------------------------------------------------------


class _SleevePosition:
    """One sleeve's running position: whole-or-fractional shares held, and their blended cost basis.
    Not frozen -- this is this run's own mutable bookkeeping, mutated in place on every fill, the
    identical structure `allocation._SleevePosition` uses for the identical reason (see this module's
    docstring's "what is not reused" -- `runner._OpenLot`'s single-lot, single-entry-price shape does
    not fit a sleeve that is bought and sold repeatedly over the life of a run)."""

    __slots__ = ("avg_cost", "opened_date", "opened_session_index", "quantity")

    def __init__(self) -> None:
        self.quantity: Decimal = Decimal(0)
        self.avg_cost: Decimal = Decimal(0)
        self.opened_session_index: int | None = None
        self.opened_date: dt.date | None = None


def _apply_buy(position: _SleevePosition, fill: Fill) -> None:
    """Blend `fill` into `position`'s running average cost, opening it first if it was flat. Buy
    commission is folded into the cost basis alongside the gross price paid, matching
    `allocation._apply_buy`'s own convention (and a real brokerage statement's)."""
    if position.quantity == 0:
        position.opened_session_index = fill.session
        position.opened_date = fill.trade_date
    cost_basis_total = position.quantity * position.avg_cost + fill.gross + fill.fees
    new_quantity = position.quantity + fill.quantity
    position.avg_cost = (cost_basis_total / new_quantity) if new_quantity > 0 else Decimal(0)
    position.quantity = new_quantity


def _apply_sell(
    position: _SleevePosition,
    fill: Fill,
    trades: list[RealisedTrade],
    metrics_trades: list[MetricsTrade],
) -> None:
    """Realise P&L on `fill.quantity` shares against `position`'s running average cost, and shrink it.
    Every sell produces one `RealisedTrade` labelled `"rebalance_trim"` -- see `LadderResult.trades`'s
    own docstring for why that is a reused, not invented, vocabulary."""
    entry_session_index = (
        position.opened_session_index if position.opened_session_index is not None else fill.session
    )
    entry_date = position.opened_date if position.opened_date is not None else fill.trade_date

    gross = (fill.price - position.avg_cost) * fill.quantity
    pnl = _money(gross - fill.fees)
    basis = position.avg_cost * fill.quantity
    return_pct = (pnl / basis) if basis != 0 else Decimal(0)
    bars_held = fill.session - entry_session_index

    trades.append(
        RealisedTrade(
            symbol=fill.symbol,
            entry_date=entry_date,
            entry_price=_money(position.avg_cost),
            exit_date=fill.trade_date,
            exit_price=fill.price,
            quantity=fill.quantity,
            exit_reason="rebalance_trim",
            pnl=pnl,
            return_pct=return_pct,
            bars_held=bars_held,
        )
    )
    metrics_trades.append(
        MetricsTrade(
            entry_date=entry_date,
            entry_price=float(position.avg_cost),
            exit_date=fill.trade_date,
            exit_price=float(fill.price),
            exit_reason=ExitReason.SIGNAL,
            bars_held=bars_held,
            return_pct=float(return_pct),
            open_at_end=False,
        )
    )

    position.quantity -= fill.quantity
    if position.quantity <= 0:
        position.quantity = Decimal(0)
        position.avg_cost = Decimal(0)
        position.opened_session_index = None
        position.opened_date = None


def _current_weights(
    broker: PaperBroker, market: AsOfMarket, symbols: tuple[str, ...]
) -> tuple[Decimal, dict[str, Decimal]]:
    """Each sleeve's actual weight of the book, marked at `market`'s as-of close. Duplicated from
    `allocation._current_weights` -- see this module's docstring for why."""
    value, marks = broker.mark(market)
    equity = broker.cash + value
    weights: dict[str, Decimal] = {}
    for symbol in symbols:
        price = marks.get(symbol)
        quantity = broker.positions.get(symbol, Decimal(0))
        if price is None or equity <= 0:
            weights[symbol] = Decimal(0)
        else:
            weights[symbol] = _money(price * quantity) / equity
    return equity, weights


def _rebalance_orders(
    targets: dict[str, Decimal], actual_weights: dict[str, Decimal], equity: Decimal
) -> tuple[list[tuple[str, Decimal]], list[tuple[str, Decimal]]]:
    """Which sleeves need an order to reach `targets` this session, split into sells and buys, each as
    `(symbol, delta_value)`.

    No band -- unlike `allocation._rebalance_moves`, which trades only past a declared drift tolerance
    because an allocation card's sleeves are meant to be *continuously* held near their targets. A
    ladder's sleeves are meant to drift freely *within* a state (see this module's own docstring's
    "weights change only on a state transition, never on drift" framing, taken from the reference
    script) and to be trued up to fresh targets in full, every time the caller decides a rebalance is
    needed -- either because the state machine's own target changed, or because a *prior* attempt at
    reaching the current target was only partially filled (see `run_ladder_card`'s own `fully_filled`
    bookkeeping) -- and it then reconciles every sleeve, not only the ones whose *target* moved or
    whose fill fell short. A one-cent floor filters out an order that would do nothing but pay
    slippage on a rounding artefact. This is deliberately a *rejection*-driven retry, not a
    weight-drift-driven one: comparing an actual weight against its target with some small tolerance
    would also retrigger on perfectly ordinary price drift between two sleeves that were never
    rebalanced at all (SCHD and IEF returning differently over months of the base state, say), which
    is exactly the churn the "no band" design above exists to avoid. A rejection is a *fact about
    what actually happened this session* (see `PaperBroker.submit`'s own `Fill | Rejection` return),
    not an inference from a weight gap that could equally be ordinary drift.
    """
    sells: list[tuple[str, Decimal]] = []
    buys: list[tuple[str, Decimal]] = []
    for symbol, target in targets.items():
        actual = actual_weights.get(symbol, Decimal(0))
        delta_value = (target - actual) * equity
        if abs(delta_value) < Decimal("0.01"):
            continue
        (buys if delta_value > 0 else sells).append((symbol, delta_value))
    return sells, buys


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def run_ladder_card(
    card: LadderCard,
    *,
    settings: Settings,
    mandate: Mandate,
    start: dt.date = TRADE_START,
    end: dt.date = TRADE_END,
) -> LadderResult:
    """Trade `card` through a fresh `PaperBroker` from `start` to `end`, session by session.

    **The state machine is evaluated at `session.decided_on`'s close, never `session.date`'s** -- the
    same lookahead boundary every decision path in this repository observes (see
    `_require_decision_market`). The reference script's own loop reads `signal[i]` at trading-date `i`
    directly, because that script has no decide/fill split at all; porting it against real, lookahead-
    safe bars means the "day `i`" the reference script trades *on* is this run's `session.decided_on`,
    and the resulting order fills at `session.date`'s open, exactly as every other card shape in this
    repository fills.

    **A rebalance is submitted when the state machine's target sleeve weights change, and retried on
    every subsequent session until every leg of it has actually filled.** Targets are reconstructed
    fresh every session (:func:`_sleeve_targets`) and compared against `previous_targets` -- not
    against a running "did the leveraged weight change" flag, because the very first session always
    needs an initial trade (the broker starts holding 100% cash, not the base 60/40 state) even though
    the leveraged weight itself does not change on that session. `previous_targets` is only advanced to
    `targets` once every order this rebalance submitted came back a `Fill`, never a `Rejection`
    (tracked below as `fully_filled`): a buy is sized off the decision session's close but fills at the
    next session's open, and a fill-day gap or the mandate's own slippage can occasionally push a buy
    sized to use exactly the remaining cash into an `insufficient_cash` rejection by a few dollars. If
    `previous_targets` were advanced regardless, that one marginal, one-time rejection would leave a
    whole sleeve permanently missing from the book for the rest of the run, since `targets ==
    previous_targets` would already hold and nothing about the ladder's own state would ever ask to
    revisit it again. See :func:`_rebalance_orders`'s own docstring for why a retried rebalance
    reconciles the whole book, not only the sleeve whose leg was rejected, and for why this is a
    rejection-driven retry rather than a weight-drift-driven one.

    **Sizing is a fraction of current equity**, exactly as `allocation.run_allocation`'s own docstring
    argues for a continuously-rebalanced book, and for the identical reason: a sleeve's target here is
    a weight of the book as it currently stands, not a fixed dollar amount fixed at some earlier point.

    See this module's docstring for why the return type is `LadderResult`, not `AllocationResult` or
    `app.tournament.models.AgentResult`.
    """
    calendar = SessionCalendar(start=start, end=end, settings=settings, benchmark=card.signal_symbol)
    sessions = list(calendar)

    broker = PaperBroker(mandate)
    starting_equity = mandate.starting_cash

    positions: dict[str, _SleevePosition] = {symbol: _SleevePosition() for symbol in card.universe}
    trades: list[RealisedTrade] = []
    metrics_trades: list[MetricsTrade] = []
    equity_curve: list[Decimal] = []
    in_position_flags: list[bool] = []
    session_invested_ratio: list[float] = []
    order_seq = 0

    # --- ladder state, ported from strategy-program/tools/drawdown_ladder.py's run_ladder ----------
    leveraged_weight = Decimal(0)  # the state machine's own notion of "how much QLD do we want"
    peak: Decimal | None = None  # SPY's own high-water mark, tracked from this run's first session
    cycle_peak = Decimal(0)  # the high standing when the current cycle armed
    armed_depth = Decimal(0)  # deepest rung already fired this cycle; 0 means fully re-armed
    new_high_at: int | None = None  # session index of the new high that started the recovery clock
    previous_targets: dict[str, Decimal] | None = None  # None forces the very first session to trade

    for session in sessions:
        decision_market = AsOfMarket(as_of=session.decided_on, settings=settings)
        _require_decision_market(decision_market, session)

        price = decision_market.close(card.signal_symbol)
        if peak is None:
            peak = price
            cycle_peak = price

        # A new high while leveraged starts the recovery clock -- checked against `leveraged_weight`
        # as it stood at the *end of the previous session*, before this session's own transition logic
        # runs below, exactly mirroring the reference script's own ordering (its `weight > 0` check
        # runs before that iteration computes a new `target`).
        if price > peak:
            if leveraged_weight > 0 and new_high_at is None:
                new_high_at = session.index
            peak = price

        drawdown = (price / peak) - Decimal(1)
        confirmed = _confirmed(card, decision_market)
        target_weight = leveraged_weight

        if leveraged_weight == 0:
            # Base state: arm on the deepest rung this drawdown has reached, in one trade -- the
            # gap-through fix (see this module's docstring).
            reached = _weight_for(card.rungs, drawdown)
            if reached > 0 and confirmed:
                target_weight = reached
                armed_depth = reached
                cycle_peak = peak
                new_high_at = None
        else:
            deeper = _weight_for(card.rungs, drawdown)
            if deeper > armed_depth and confirmed:
                # Ladder down. Fires once per level per cycle -- `armed_depth` only ever rises until a
                # full reset, which is what stops a chop around a trigger from round-tripping the book.
                target_weight = deeper
                armed_depth = deeper
            elif new_high_at is not None:
                sessions_since = session.index - new_high_at
                recovered = price >= cycle_peak * (Decimal(1) + card.recovery_gain)
                if recovered or sessions_since >= card.recovery_sessions:
                    target_weight = Decimal(0)
                    armed_depth = Decimal(0)
                    new_high_at = None
                elif sessions_since == 0:
                    target_weight = leveraged_weight * card.ath_haircut

        leveraged_weight = target_weight
        targets = _sleeve_targets(card, leveraged_weight)

        if previous_targets is None or targets != previous_targets:
            equity, actual_weights = _current_weights(broker, decision_market, card.universe)
            sells, buys = _rebalance_orders(targets, actual_weights, equity)
            #: Whether every leg of *this* rebalance attempt actually filled -- see this function's
            #: own docstring, "A rebalance is submitted..." section, and the `previous_targets` update
            #: below for why a rejected leg must not be treated as "reached".
            fully_filled = True

            for symbol, delta_value in sells:
                try:
                    price_at_decision = decision_market.close(symbol)
                except UnpricedSymbol:
                    continue
                held = positions[symbol].quantity
                quantity = min(_entry_quantity(mandate, -delta_value, price_at_decision), held)
                if quantity <= 0:
                    continue
                order_seq += 1
                order = Order(
                    order_id=f"{card.agent_id}-s{session.index}-r{order_seq}",
                    session=session.index,
                    decided_on=session.decided_on,
                    symbol=symbol,
                    side="sell",
                    quantity=quantity,
                    thesis=(
                        f"ladder state transition: SPY drawdown {drawdown:.2%} from its own high, "
                        f"leveraged target now {leveraged_weight:.0%}; trimming {symbol} toward its "
                        f"new {targets[symbol]:.0%} target"
                    ),
                    invalidation=(
                        "n/a -- this order rebalances a continuously held sleeve toward the ladder's "
                        "own current state, it does not close a position outright"
                    ),
                )
                outcome = broker.submit(order, market=decision_market, fill_date=session.date)
                if isinstance(outcome, Fill):
                    _apply_sell(positions[symbol], outcome, trades, metrics_trades)
                else:
                    # A `Rejection` is already recorded on `broker.rejections` -- see
                    # `PaperBroker._reject`'s own docstring on being the sole append site. Recorded
                    # here too, as `fully_filled = False`, so this rebalance is retried next session
                    # instead of being mistaken for "the book now matches `targets`".
                    fully_filled = False

            for symbol, delta_value in buys:
                try:
                    price_at_decision = decision_market.close(symbol)
                except UnpricedSymbol:
                    continue
                quantity = _entry_quantity(mandate, delta_value, price_at_decision)
                if quantity <= 0:
                    continue
                order_seq += 1
                order = Order(
                    order_id=f"{card.agent_id}-s{session.index}-r{order_seq}",
                    session=session.index,
                    decided_on=session.decided_on,
                    symbol=symbol,
                    side="buy",
                    quantity=quantity,
                    thesis=(
                        f"ladder state transition: SPY drawdown {drawdown:.2%} from its own high, "
                        f"leveraged target now {leveraged_weight:.0%}; topping up {symbol} toward its "
                        f"new {targets[symbol]:.0%} target"
                    ),
                    invalidation=(
                        "n/a -- this order rebalances a continuously held sleeve toward the ladder's "
                        "own current state, it does not open a position outright"
                    ),
                )
                outcome = broker.submit(order, market=decision_market, fill_date=session.date)
                if isinstance(outcome, Fill):
                    _apply_buy(positions[symbol], outcome)
                else:
                    fully_filled = False

            # Only mark this rebalance "reached" once every leg has actually filled -- a rejected leg
            # (a buy sized off the decision close that a fill-day gap or the mandate's slippage pushed
            # just over available cash, most often on the very first session's initial allocation) is
            # retried on the next session instead of being permanently accepted as the new status quo.
            # Without this, `targets == previous_targets` would already hold from this same session
            # onward and a rejected sleeve would silently stay missing from the book for the rest of
            # the run, even though nothing about the ladder's own state ever asked for that.
            if fully_filled:
                previous_targets = targets

        mark_market = AsOfMarket(as_of=session.date, settings=settings)
        session_equity = broker.equity(mark_market)
        equity_curve.append(session_equity)
        in_position_flags.append(any(p.quantity > 0 for p in positions.values()))
        invested_value, _ = broker.mark(mark_market)
        session_invested_ratio.append(
            float(invested_value / session_equity) if session_equity > 0 else 0.0
        )

    # -- anything still held when the window ends is an unrealised, not a discarded, result --------
    last_session = sessions[-1]
    final_market = AsOfMarket(as_of=last_session.date, settings=settings)
    for symbol, position in positions.items():
        if position.quantity <= 0:
            continue
        try:
            mark_price = final_market.close(symbol)
        except UnpricedSymbol:
            mark_price = position.avg_cost  # no data to mark against; report flat rather than crash
        gross = (mark_price - position.avg_cost) * position.quantity
        pnl = _money(gross)
        basis = position.avg_cost * position.quantity
        return_pct = (pnl / basis) if basis != 0 else Decimal(0)
        entry_session_index = position.opened_session_index or last_session.index
        entry_date = position.opened_date or last_session.date
        bars_held = last_session.index - entry_session_index

        trades.append(
            RealisedTrade(
                symbol=symbol,
                entry_date=entry_date,
                entry_price=_money(position.avg_cost),
                exit_date=None,
                exit_price=None,
                quantity=position.quantity,
                exit_reason="open_at_end",
                pnl=pnl,
                return_pct=return_pct,
                bars_held=bars_held,
            )
        )
        metrics_trades.append(
            MetricsTrade(
                entry_date=entry_date,
                entry_price=float(position.avg_cost),
                exit_date=last_session.date,
                exit_price=float(mark_price),
                exit_reason=ExitReason.END_OF_DATA,
                bars_held=bars_held,
                return_pct=float(return_pct),
                open_at_end=True,
            )
        )

    ending_equity = equity_curve[-1]

    # Same D1 rebasing `run_card`/`run_allocation` apply -- see either's own docstring's long comment
    # at the equivalent point.
    equity_array = np.array(
        [1.0] + [float(e / starting_equity) for e in equity_curve], dtype=np.float64
    )
    in_position_array = np.array([False, *in_position_flags], dtype=np.bool_)

    strategy_metrics = metrics.compute(
        equity_array,
        in_position=in_position_array,
        trades=metrics_trades,
        bars_per_year=BARS_PER_YEAR[Interval.DAY],
    )
    assert strategy_metrics.total_return is not None
    assert strategy_metrics.max_drawdown is not None

    capital_exposure = sum(session_invested_ratio) / len(sessions)

    return LadderResult(
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
        benchmark_return=_benchmark_return(settings, sessions[0], last_session),
    )

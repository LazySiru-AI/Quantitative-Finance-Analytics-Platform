"""A second card shape: a continuously-rebalanced multi-sleeve portfolio, and the engine to run it.

**Why this is a new module rather than new fields on `StrategyCard`.** `app.tournament.models` is
frozen on purpose -- `_Frozen`'s `extra="forbid"` -- and roughly 35 committed card JSONs across
`backend/app/paper/library/{base,variants,candidates,retired}` and `data/rounds/*/cards/` validate
against exactly the shape that file declares today. `StrategyCard` also encodes an assumption an
allocation strategy does not share: every decision is binary in-or-out (`entry`/`exit` are boolean
expressions with no notion of "how much"), and every position the same size (`position_pct`, one
number for the whole card). Round 4's `c20-rotation` memo already recorded the underlying limit in
the *engine*, not just the card: "this engine has no cross-symbol operator -- entry and exit are
evaluated per instrument against that instrument's own bars only." An allocation card does not need a
cross-symbol operator (each tilt condition below is still evaluated against one symbol's own bars,
see :class:`TiltRule`), but it does need a fundamentally different decision -- a *weight*, not a
*signal* -- and bolting that onto a frozen, widely-depended-on contract as a bag of optional fields
would have made every one of those 35 cards' validators start asking "is `sleeves` set? then ignore
`entry`" instead of the type system doing that for free. A new, small, independently frozen contract
does the same job without touching the one 35 cards already depend on.

**What is reused, deliberately, rather than re-derived.** `app.rules.grammar.parse` and
`app.rules.evaluate.evaluate` are the one rule-expression engine this repository has, and a
:class:`TiltRule`'s `condition` is parsed and evaluated through the exact same call path as a
`StrategyCard`'s `entry`/`exit` -- see :func:`_guard_allocation_card`, which mirrors
`app.tournament.runner._guard_card` line for line except that it guards a rule's `condition` against
its own `on_symbol` instead of a card's `entry`/`exit` against every universe symbol. `PaperBroker`
and `AsOfMarket` are the same fills-cash-settlement-slippage and lookahead-safe-bars machinery
`run_card` uses, imported from the same two modules named in this package's own docstring
(`app.paper.paperbroker`, `app.paper.marketdata`). `app.backtest.metrics.compute` is the same single
metrics implementation `run_card` calls, for the same reason `runner.py`'s module docstring gives:
this repository has already shipped a defect from having two drawdown implementations that
disagreed, and this module has no interest in becoming a second one.

A handful of `app.tournament.runner`'s own private helpers are imported directly rather than
reimplemented, because they are generic (nothing in their signature or body is `StrategyCard`-shaped)
and reimplementing them would be exactly the "write a second parser" mistake this module's brief
warns against, generalised to arithmetic instead of grammar: `_require_decision_market` /
`LookaheadError` (the lookahead assertion every decision path in `runner.py` is wired to),
`_build_signal_table` / `_SignalTable` (evaluate a parsed rule tree once per run and index it per
session, rather than re-walking the whole indicator stack on every decision), `_entry_quantity`
(notional -> whole-or-fractional shares, floored), `_benchmark_return` (buy-and-hold on the
tournament's own benchmark, same entry/exit convention every card gets) and `_undilute_exposure` (the
D2/D1 exposure-rescaling fix -- see that function's own docstring). None of these read or write
anything about `StrategyCard`; they take an `AsOfMarket`/`Session`/settings/symbols and hand back a
plain value.

**What is *not* reused, and why.** `runner.py`'s per-trade bookkeeping (`_OpenLot`, `_close_trade`,
`_open_at_end_trade`) is built around "no pyramiding, one lot per symbol, entry and exit are single
events" (see that module's own docstring), which is exactly the StrategyCard-specific shape this
module exists to not have. A sleeve here is bought and sold repeatedly over the life of a run --
every band-triggered rebalance is a partial buy or a partial sell against a *continuing* position,
never a fresh entry or a full exit. Trying to force that through a single-lot, single-entry-price
bookkeeping structure would mean either fabricating a fresh "entry" on every top-up (which double
counts the sleeve's history) or refusing to record interim rebalances as trades at all (which would
make `AgentResult.trades` -- excuse the pun -- silent about most of what the strategy actually did).
:class:`_SleevePosition` below is a weighted-average-cost position instead: every buy blends into one
running average price, every sell realises P&L against that running average and shrinks the same
position rather than closing a lot and opening a new one. This is standard portfolio accounting (it
is what a real brokerage statement shows for a continuously-traded holding) and it is a *different*,
not lesser, standard from FIFO lot accounting -- the two agree only when a symbol is never re-bought
before being fully sold, which is precisely the case `StrategyCard`'s "no pyramiding" restricts itself
to and this module's whole reason for existing is to relax.

**The one place this module could not avoid a real incompatibility: `AgentResult.card`.**
`app.tournament.models.AgentResult.card` is typed as `StrategyCard`, a *specific* frozen pydantic
model, not `BaseModel` or a union -- and pydantic validates a field typed as one model class by
checking whether the value is already an instance of that exact class before it will accept anything
else; a differently-shaped `BaseModel` subclass is rejected as `model_type` (confirmed empirically: a
two-line reproduction with two disjoint frozen models raises `pydantic_core.ValidationError:
Input should be a valid dictionary or instance of A`). `AllocationCard` cannot be a `StrategyCard` --
it has none of `universe`/`entry`/`exit`/`max_positions`/`position_pct`, all required there -- and
subclassing it to satisfy the `isinstance` check would be worse than the problem it solves: every one
of those required fields would still have to be given *some* value with no meaning for an allocation
strategy, which is exactly the "bag of fields nothing validates against" outcome the module docstring
above already rejected for the opposite direction. So `run_allocation` returns
:class:`AllocationResult`, defined in this file: every field name and type `AgentResult` has except
`card`, which holds an `AllocationCard` instead of a `StrategyCard`. This is not a cosmetic
substitute -- **it is not `app.tournament.models.AgentResult` and `isinstance(result,
app.tournament.models.AgentResult)` is `False`.** Every scorer function this repository ships
(`app.tournament.scoring._rank_key`, and every function in `strategy-program/tools/score.py` that
takes a `result: AgentResult` -- checked directly against that file's source) reads only
`result.card.agent_id`, `result.card.display_name`, and then `sessions`, `starting_equity`,
`ending_equity`, `total_return`, `max_drawdown`, `exposure`, `capital_exposure`, `benchmark_return`
and `trades` by plain attribute access, with no `isinstance` check anywhere in that call path -- so
an `AllocationResult` passed directly, in-process, to any of those functions runs correctly today.
What it cannot do is round-trip through the *disk* format those same tools use to reload a finished
run: `score.py`'s `_load_results` calls `AgentResult.model_validate_json(path.read_text(...))`, and
that call validates the JSON's `"card"` object against `StrategyCard`'s schema specifically --
`AllocationResult.model_dump_json()`'s `"card"` object (`sleeves`/`band_pct`/`rules`, no
`universe`/`entry`/`exit`) would fail that validation immediately. Making an `AllocationCard` result
persist through that exact path would require widening `AgentResult.card`'s type (e.g. to
`StrategyCard | AllocationCard`) in `backend/app/tournament/models.py`, which this package's brief
explicitly puts out of scope for this change. Flagged here, and again in this change's own report,
rather than worked around by force -- see the module docstring's opening paragraph for why a forced
fit was rejected once already in this same design.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Self

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.backtest import guards, metrics
from app.backtest.models import BARS_PER_YEAR, ExitReason, GuardStatus
from app.backtest.models import Trade as MetricsTrade
from app.config import Settings
from app.core.models import Money
from app.market.models import Interval
from app.paper.marketdata import AsOfMarket, Session, SessionCalendar, UnpricedSymbol
from app.paper.paperbroker import Fill, Mandate, Order, PaperBroker
from app.rules import grammar
from app.rules.nodes import BoolExpr, NumExpr
from app.tournament.models import (
    DESIGN_THROUGH,
    TRADE_END,
    TRADE_START,
    RealisedTrade,
    RejectionRecord,
)
from app.tournament.purposes import Purpose
from app.tournament.runner import (
    GuardFailed,
    LookaheadError,
    _benchmark_return,
    _build_rank_table,
    _build_signal_table,
    _entry_quantity,
    _RankTable,
    _require_decision_market,
    _SignalTable,
    _undilute_exposure,
)

__all__ = [
    "AllocationCard",
    "AllocationResult",
    "LookaheadError",
    "Sleeve",
    "TiltRule",
    "run_allocation",
]

#: Same benchmark the rest of the tournament compares every card against (see
#: `app.tournament.runner._BENCHMARK`'s own docstring) -- imported by value, not re-derived, so an
#: allocation result's `benchmark_return` is computed against the identical symbol a StrategyCard
#: result was.
_BENCHMARK = "SPY"

_CENTS = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    """Round to cents, half-up -- the same convention `PaperBroker` and `runner.py` use, so a
    reported P&L cannot disagree with the broker's own ledger by a rounding rule."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


class _Frozen(BaseModel):
    """Deliberately a separate definition from `app.tournament.models._Frozen`, not an import of it.

    The two configs are identical today (`frozen=True, extra="forbid", str_strip_whitespace=True`),
    and that is not a coincidence -- this module is written in the same register as `models.py` on
    purpose, per this package's brief. But importing a private, underscore-prefixed name from another
    package's contract module would tie this file's basic validation behaviour to an implementation
    detail of a module this package does not own and was told not to modify; if `models.py`'s
    `_Frozen` ever changes (a new default, a new str constraint), this module should not change with
    it silently. Two lines duplicated on purpose cost nothing; a coupling to another package's private
    name would have cost a future reader the ability to reason about this file on its own.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# The card
# ---------------------------------------------------------------------------


class Sleeve(_Frozen):
    """One symbol's slice of the book, and the weight it is rebalanced back toward."""

    symbol: str
    target_weight: Decimal
    """Fraction of the whole book this sleeve is rebalanced toward, absent any firing tilt rule.
    Validated at the card level, not here, because "this one weight is between 0 and 1" says nothing
    about whether the *set* of sleeves' weights is a complete partition of the book -- that is
    `AllocationCard._weights_are_a_complete_partition`'s job, and it needs every sleeve at once."""


class TiltRule(_Frozen):
    """One conditional reallocation: when `condition` is true of `on_symbol`, shift `shift_pct` of
    the whole book's weight from `from_symbol`'s target to `to_symbol`'s.

    **`shift_pct` is a fraction of the whole portfolio, not a fraction of `from_symbol`'s own
    weight.** ``shift_pct=Decimal("0.08")`` always means "move eight percentage points of the total
    book," whether `from_symbol` currently targets 40% or 4%. A relative shift ("move 20% of
    `from_symbol`'s weight") would make the same rule move a different absolute amount depending on
    what every *other* rule ahead of it in the list already did this session, which is a much harder
    number for the card's own `thesis` to state a falsification condition against -- "shift 8 points
    into QLD when it is oversold" is a claim `AllocationCard.thesis` can be wrong about in a way a
    reader can check; "shift a fifth of whatever SCHD happens to be carrying" is not.

    **`condition` is evaluated against `on_symbol`'s own bars only**, through the identical
    `app.rules.grammar`/`app.rules.evaluate` path `StrategyCard.entry`/`.exit` use (see
    :func:`_guard_allocation_card` and :func:`_target_weights`) -- there is still no cross-symbol
    operator in this engine (see this module's own docstring), so `on_symbol` need not be
    `from_symbol` or `to_symbol`, but it is validated to be *some* sleeve on the same card
    (:meth:`AllocationCard._rules_reference_known_sleeves`), because a condition read off a symbol the
    card does not even hold would be reallocating the book based on a signal nothing here is priced
    against.

    **Rules apply in list order, each against the output of the ones before it, within one
    session.** Two rules that both name `from_symbol="SCHD"` do not each independently claim 8 points
    off SCHD's *original* target; the second claims 8 points off whatever SCHD's target already is
    after the first rule ran (see :func:`_target_weights`). This is a plain, auditable order rather
    than a simultaneous-system solve, and it is what makes `min(rule.shift_pct,
    weights[rule.from_symbol])` (the clamp that keeps a sleeve's target from ever going negative) mean
    the same thing regardless of how many rules end up firing on the same session.
    """

    condition: str
    on_symbol: str
    from_symbol: str
    to_symbol: str
    shift_pct: Decimal | None = None
    shift_expr: str | None = None
    """A rule-DSL *numeric* expression giving the shift, evaluated per session on `on_symbol`'s own
    bars -- the alternative to a constant `shift_pct`, and exactly one of the two must be set.

    **This is what makes a continuously-sized tilt expressible at all.** With a fixed `shift_pct` a
    rule can only say "move eight points when this is true"; the size of the move cannot depend on
    *how* true it is. `strategy-program/ALLOCATION-FAMILY.md` measured the two strategies that need
    that -- continuous vol-targeting and inverse-volatility risk parity -- in a bespoke harness and
    recorded that neither is expressible as an `AllocationCard`, with inverse-vol parity posting the
    family's shallowest drawdown anywhere (**-17.6%** against a static blend's -33.7%).
    `docs/research/programme/00-EVERYTHING-TESTED.md` ranks this the programme's **#2** outstanding
    change for that reason. ``shift_expr="0.4 * atr(20) / close"`` sizes the move by realised
    volatility; ``shift_expr="0.08"`` is the constant case written the long way.

    **Parsed and guarded as a ranking key, not as a condition.** It goes through
    `app.rules.grammar.parse_ranking` and `guards.check(..., kind="ranking")` -- the same path
    `StrategyCard.rank_by` uses -- because a magnitude that is not causal sizes today's position from
    tomorrow's data, which is lookahead in the *sizing* step and is harder to spot than lookahead in
    an entry rule precisely because the condition beside it stays clean.

    **Three runtime outcomes, and none of them is an error.** A value that is `None` (no bars, no bar
    on that date, or an indicator still in warmup), or is negative, means **the rule does not fire
    this session** -- identical in effect to `condition` being false. Negative is clamped rather than
    honoured because `from_symbol` and `to_symbol` are fixed by the rule: a negative shift would
    silently reverse a rule's stated direction, and "move weight the other way" is a *second* rule
    with the symbols swapped, which a reader can see. A value above `1` is clamped to `1`, and then
    to the sleeve's own available weight by the same `min()` every constant shift passes through, so
    the sum-preserving invariant in :func:`_target_weights` is untouched."""

    @model_validator(mode="after")
    def _condition_is_not_blank(self) -> Self:
        if not self.condition.strip():
            raise ValueError("a tilt rule with a blank condition can never fire or not-fire; state one")
        return self

    @model_validator(mode="after")
    def _exactly_one_shift_is_given(self) -> Self:
        """One of `shift_pct` / `shift_expr`, never both and never neither.

        Both would need a precedence rule, and any precedence rule makes one of the two a value the
        card states and the engine ignores -- the shape of defect this programme keeps finding, where
        a figure is present, plausible and unread. Neither leaves the rule with no size at all.
        """
        given = [n for n, v in (("shift_pct", self.shift_pct), ("shift_expr", self.shift_expr)) if v is not None]
        if len(given) != 1:
            raise ValueError(
                f"a tilt rule needs exactly one of shift_pct or shift_expr; got {given or 'neither'}. "
                "shift_pct is a constant fraction of the book; shift_expr is a rule-DSL numeric "
                "expression evaluated per session on on_symbol's bars."
            )
        if self.shift_expr is not None and not self.shift_expr.strip():
            raise ValueError("shift_expr is blank; state an expression or use shift_pct")
        return self

    @model_validator(mode="after")
    def _shift_is_a_fraction_of_one_and_symbols_differ(self) -> Self:
        if self.shift_pct is not None and not (Decimal(0) < self.shift_pct <= Decimal(1)):
            raise ValueError(
                f"shift_pct must be a fraction of one, not a percentage -- got {self.shift_pct}. "
                "Use Decimal('0.08') for 8 percentage points of the whole book."
            )
        if self.from_symbol == self.to_symbol:
            raise ValueError(
                f"from_symbol and to_symbol are both {self.from_symbol!r}; a rule that shifts a "
                "sleeve's weight into itself changes nothing and is not a rule"
            )
        return self


class AllocationCard(_Frozen):
    """One analyst's submission for a continuously-rebalanced multi-sleeve portfolio.

    Deliberately in the same register as `app.tournament.models.StrategyCard` -- `agent_id`,
    `display_name`, `thesis` and `designed_through` mean exactly what they mean there, including the
    same design/trading window separation (see :meth:`_designed_through_is_before_the_cutoff`) -- but
    the strategy itself is shaped differently: `sleeves` and `band_pct` replace `universe`/`entry`/
    `exit`/`max_positions`/`position_pct` because there is no binary in-or-out decision here at all,
    only a target weight per sleeve and a tolerance for how far the book may drift from it before a
    trade is worth its own slippage and fees. See this module's own docstring for why that is a
    different pydantic model rather than new fields on `StrategyCard`.
    """

    agent_id: str
    """Short slug, unique within whatever this card is compared alongside. Becomes a report filename
    the same way `StrategyCard.agent_id` does."""

    display_name: str

    purpose: Purpose = Purpose.TRADING
    """Which of the three investment goals (`app.tournament.purposes.Purpose`) this card serves. Same
    field, same default and same reasoning as `app.tournament.models.StrategyCard.purpose` -- restated
    here rather than inherited because this module's own docstring is explicit that `AllocationCard`
    shares no base class with `StrategyCard`. Every allocation card already committed is, by omission,
    a trading-purpose card (a single lump sum, no disjointness constraint on its sleeves), so
    `Purpose.TRADING` is what those cards already are, not a placeholder guess -- and defaulting to it
    means no existing allocation card JSON needs an edit and no existing test needs a `purpose` key
    added to keep validating against this model."""

    thesis: str
    """Why this should work, in the analyst's own words, written **before** the trading window ran --
    same requirement `StrategyCard.thesis` states, for the same reason: a thesis that only describes
    the card's own rules back ("shifts weight into QLD when it is oversold") has not stated a
    falsifiable claim, only a restatement of the mechanism. A thesis for this card shape additionally
    has to say what result would prove it *wrong* -- a mean-reversion tilt is cheap to state and easy
    to confuse with a trend-following one that happens to be described backwards, so the falsification
    condition is what distinguishes the two on paper before either has run a single session."""

    falsification: str | None = None
    """What measurement would make this card's `thesis` wrong -- see `StrategyCard.falsification`.

    **This shape is where the requirement already worked, which is the argument for the field.** The
    `thesis` docstring above has always demanded a falsification condition of an `AllocationCard`, and
    `StrategyCard.thesis` never did. `docs/research/programme/thesis-audit.md` found the consequence
    written across the seated roster: both allocation-family cards state what would falsify them,
    name the document that will hold the number, and the number exists -- and none of the four seated
    `StrategyCard`s states one at all. The split runs along card type because the demand did.

    So this field is not a new idea, it is the existing prose requirement given somewhere to live
    where a test can read it instead of a reader having to."""

    sleeves: tuple[Sleeve, ...] = Field(min_length=2, max_length=12)
    """At least two -- a one-sleeve "portfolio" has no rebalancing decision to make at all, which is
    a buy-and-hold card, not this card shape. Twelve mirrors `StrategyCard.universe`'s own cap, for
    the same reason: a card an analyst cannot describe a rationale for in a bounded number of sleeves
    is a diversification strategy wearing a thesis, not a thesis."""

    band_pct: Decimal
    """How far a sleeve's actual weight may drift from its target before a rebalance is worth
    submitting. A band, not a daily reset: `PaperBroker` charges slippage and floors whole shares on
    every fill, so a card that rebalanced back to its exact target every single session would be
    trading almost every session on drift that is measurement noise in a mock broker, not a real
    signal the strategy is entitled to react to -- see :func:`run_allocation`'s own docstring."""

    rules: tuple[TiltRule, ...] = ()
    """Conditional reallocations, applied in this order every session -- see `TiltRule`'s own
    docstring for why order matters. Empty by default: a card with no rules is still a complete,
    valid strategy (constant-weight, periodically rebalanced), just one with nothing conditional
    about it."""

    designed_through: dt.date
    """The last session the analyst looked at. Must not exceed
    `app.tournament.models.DESIGN_THROUGH` -- see :meth:`_designed_through_is_before_the_cutoff`."""

    @property
    def universe(self) -> tuple[str, ...]:
        """Every sleeve's symbol, in the order `sleeves` declares them. Named to match
        `StrategyCard.universe` deliberately -- both answer "what does this card need priced" -- so a
        caller that already knows how to guard or price a `StrategyCard` (e.g.
        :func:`_guard_allocation_card`, modelled on `runner._guard_card`) reads the same way here."""
        return tuple(sleeve.symbol for sleeve in self.sleeves)

    @model_validator(mode="after")
    def _designed_through_is_before_the_cutoff(self) -> Self:
        if self.designed_through > DESIGN_THROUGH:
            raise ValueError(
                f"designed_through={self.designed_through.isoformat()} is after the design cutoff "
                f"{DESIGN_THROUGH.isoformat()}. The trading window starts "
                f"{TRADE_START.isoformat()}; a strategy designed with sight of it is fitted to the "
                "data it is about to be scored on, and its result would measure nothing -- the same "
                "rule `StrategyCard` enforces, restated here because this is a different model, not "
                "a relaxed one."
            )
        return self

    @model_validator(mode="after")
    def _sleeve_symbols_are_unique(self) -> Self:
        seen: dict[str, None] = {}
        for sleeve in self.sleeves:
            if sleeve.symbol in seen:
                raise ValueError(
                    f"{sleeve.symbol!r} appears more than once in sleeves; a symbol can have exactly "
                    "one target weight, not two competing ones"
                )
            seen[sleeve.symbol] = None
        return self

    @model_validator(mode="after")
    def _weights_are_a_complete_partition(self) -> Self:
        """Weights must sum to *exactly* one, and are never silently normalised to it.

        Silent normalisation would let a card carrying `("QLD", "0.5"), ("SCHD", "0.3")` -- an
        analyst's arithmetic slip, 20 points of the book simply forgotten -- run as if it had written
        `("QLD", "0.625"), ("SCHD", "0.375")`, a materially different strategy the analyst never
        actually proposed. Refusing to construct is the only response that does not paper over that
        slip with a number the analyst did not choose. Exact equality, not a tolerance, is checkable
        here (unlike the float case a tolerance usually exists for) because every weight is a
        `Decimal` parsed from a JSON *string* (`app.core.models.Money`'s own convention, restated by
        `StrategyCard.position_pct` and followed here) -- `Decimal("0.35") + Decimal("0.40") +
        Decimal("0.25")` is exactly `Decimal("1.00")`, with no binary-float rounding in between to
        excuse.
        """
        total = sum((sleeve.target_weight for sleeve in self.sleeves), Decimal(0))
        if total != Decimal(1):
            raise ValueError(
                f"sleeve target_weight values sum to {total}, not 1 -- weights are never normalised "
                "silently (see this validator's own docstring); fix the card's own numbers"
            )
        return self

    @model_validator(mode="after")
    def _band_is_a_fraction_of_one(self) -> Self:
        if not (Decimal(0) < self.band_pct < Decimal(1)):
            raise ValueError(
                f"band_pct must be a fraction of one, strictly between 0 and 1 -- got "
                f"{self.band_pct}. A band of 0 rebalances on any drift at all (see the module "
                "docstring's slippage/whole-share-rounding argument against exactly that); a band "
                "of 1 or more can never be breached and the card would never trade."
            )
        return self

    @model_validator(mode="after")
    def _rules_reference_known_sleeves(self) -> Self:
        symbols = {sleeve.symbol for sleeve in self.sleeves}
        for index, rule in enumerate(self.rules):
            for field_name, value in (
                ("on_symbol", rule.on_symbol),
                ("from_symbol", rule.from_symbol),
                ("to_symbol", rule.to_symbol),
            ):
                if value not in symbols:
                    raise ValueError(
                        f"rules[{index}].{field_name}={value!r} is not one of this card's sleeves "
                        f"({sorted(symbols)}); a tilt cannot read a signal off, or move weight to or "
                        "from, a symbol the book does not even hold"
                    )
        return self


# ---------------------------------------------------------------------------
# The result -- see this module's own docstring's closing section for exactly how, and how far,
# this mirrors `app.tournament.models.AgentResult`, and why it cannot be that class outright.
# ---------------------------------------------------------------------------


class AllocationResult(_Frozen):
    """What one allocation card did over the trading window.

    Field-for-field identical to `app.tournament.models.AgentResult` except `card`, and except the
    fields that class carries which nothing in this module ever populates (`profit_factor`,
    `realised_reward_risk`, `p_value`, `q_value` -- all optional there too, and left at their own
    `None` defaults here for the same reason `runner.py` leaves them `None`: they are filled in by a
    scan or a tournament aggregation step this module is not one of). See the module docstring for
    the one thing this type deliberately is not: `app.tournament.models.AgentResult` itself.
    """

    card: AllocationCard
    sessions: int
    starting_equity: Money
    ending_equity: Money

    total_return: Decimal
    max_drawdown: Decimal
    """From `app.backtest.metrics.compute`, exactly as `AgentResult.max_drawdown` is -- never
    recomputed here, for the identical reason that docstring gives."""

    sharpe: float | None = None
    sortino: float | None = None
    volatility: float | None = None
    exposure: float | None = None
    capital_exposure: float | None = None
    """Capital-weighted exposure, mirroring `AgentResult.capital_exposure`'s *contract* -- "how much
    of the book is actually deployed, averaged across sessions" -- but neither its exact arithmetic
    nor, deliberately, its normalising denominator. `AgentResult.capital_exposure` sums each open
    lot's *entry* notional over `starting_equity`, which is the right question for a `StrategyCard`:
    `position_pct` sizes a fixed dollar amount off starting equity once, at entry, and never resizes
    it (see `runner.py`'s own docstring), so that entry notional is naturally bounded by the card's
    own `position_pct * max_positions` regardless of how long the run goes on. Neither half of that
    holds for an allocation card -- there is no "entry notional" (every sleeve is resized on every
    rebalance), and every sleeve's *dollar* size is meant to grow as the book compounds, by
    construction (see `run_allocation`'s own docstring on why sizing reads current, not starting,
    equity). Dividing this card's invested value by `starting_equity` the way `AgentResult` does would
    not measure exposure at all on a run of any length: a card that is fully invested every single
    session and simply compounds from $10,000 to $25,000 would report `capital_exposure ~= 1.75`
    (the *average* invested value over the run, relative to where it started) despite never once
    holding an ounce of uninvested cash relative to its own book -- a number shaped like a fraction
    that is not one. What is computed here instead is `invested_value / equity` **at that same
    session's own close** (both already computed for `_current_weights` and the equity curve; see
    `run_allocation`'s loop), averaged across sessions -- bounded in `[0, 1]` at every session
    regardless of how much the book has grown, and reading close to `1.0` for a fully invested,
    three-sleeve book (weights summing to 1, per `AllocationCard._weights_are_a_complete_partition`)
    minus whatever cash drag whole-share rounding, T+1 settlement lag on a same-session sell, and the
    band's own slack leave sitting idle at any given moment."""
    win_rate: float | None = None
    profit_factor: Decimal | None = None
    realised_reward_risk: Decimal | None = None

    trades: tuple[RealisedTrade, ...] = ()
    """Reuses `app.tournament.models.RealisedTrade` unmodified -- that type names no `StrategyCard`
    field anywhere in its own definition, so it is exactly as valid a record of a partial rebalancing
    fill as of a StrategyCard round trip. `exit_reason` here reads `"rebalance_trim"` for an interim
    partial sell and `"open_at_end"` for whatever is still held when the window closes -- a new pair
    of values, not the four (`rule`/`stop`/`target`/`time`) `RealisedTrade.exit_reason`'s own
    docstring lists for a `StrategyCard` run, because a plain `str` field validates any string and a
    different card shape is entitled to its own vocabulary for describing why a position moved."""
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
# Guarding, once, up front -- mirrors `runner._guard_card` exactly except that a tilt condition is
# checked against its own `on_symbol` rather than a StrategyCard's `entry`/`exit` against every
# universe symbol.
# ---------------------------------------------------------------------------


def _guard_allocation_card(
    card: AllocationCard, *, settings: Settings, first_decided_on: dt.date
) -> list[tuple[BoolExpr, NumExpr | None]]:
    """Guard every rule's `condition` -- and its `shift_expr`, when it has one -- then parse both.

    Same reasoning as `runner._guard_card`: guarded against `first_decided_on` (this run's very first
    decision), never against the trading window's end, so the guard itself never sees a bar the
    analyst's design window did not already justify looking at. Returns `(condition, magnitude)`
    pairs in `rules` order so a caller can zip them against `card.rules` directly; `magnitude` is
    `None` for a rule carrying a constant `shift_pct`.

    **The magnitude is guarded exactly as the condition is, and that is the whole safety argument for
    `shift_expr` existing.** A non-causal magnitude sizes today's position from tomorrow's data --
    lookahead in the *sizing* step rather than the entry step, which is harder to notice precisely
    because the condition beside it stays clean. It is checked with `kind="ranking"`, the same entry
    point `StrategyCard.rank_by` uses, for the same reason and against the same node allowlist.
    """
    check_market = AsOfMarket(as_of=first_decided_on, settings=settings)
    trees: list[tuple[BoolExpr, NumExpr | None]] = []
    for index, rule in enumerate(card.rules):
        bars = check_market.history(rule.on_symbol, lookback_days=720)
        report = guards.check(rule.condition, bars, interval=Interval.DAY)
        if report.status is not GuardStatus.PASSED:
            raise GuardFailed(
                card.agent_id, f"rules[{index}].condition", rule.on_symbol, rule.condition, report
            )
        magnitude: NumExpr | None = None
        if rule.shift_expr is not None:
            mag_report = guards.check(
                rule.shift_expr, bars, interval=Interval.DAY, kind="ranking"
            )
            if mag_report.status is not GuardStatus.PASSED:
                raise GuardFailed(
                    card.agent_id,
                    f"rules[{index}].shift_expr",
                    rule.on_symbol,
                    rule.shift_expr,
                    mag_report,
                )
            magnitude = grammar.parse_ranking(rule.shift_expr)
        trees.append((grammar.parse(rule.condition), magnitude))
    return trees


# ---------------------------------------------------------------------------
# Per-session target weights
# ---------------------------------------------------------------------------


def _target_weights(
    card: AllocationCard,
    signal_tables: Sequence[_SignalTable],
    magnitude_tables: Sequence[_RankTable | None],
    decided_on: dt.date,
) -> dict[str, Decimal]:
    """Base weights, adjusted by every tilt rule that fires on `decided_on`, in `card.rules` order.

    See `TiltRule`'s own docstring for why order matters and why the clamp below is what keeps this
    sum-preserving: every shift moves weight from one sleeve to another (never conjures or destroys
    any), and `min(shift, weights[rule.from_symbol])` never lets a shift take a sleeve's target below
    zero, so the sum stays exactly `Decimal(1)` -- the same invariant
    `AllocationCard._weights_are_a_complete_partition` establishes for the base weights -- no matter
    how many rules fire or in what combination.

    **A `shift_expr` rule passes through the identical clamp**, which is why adding continuously-sized
    tilts did not need the invariant re-argued: the only difference is where `shift` comes from, and
    it is bounded into `[0, 1]` before it reaches the same `min()`. See `TiltRule.shift_expr` for why
    an undefined or negative magnitude means "does not fire" rather than "shift zero" -- they have the
    same effect here, and stating it as non-firing is what keeps the two paths one behaviour.
    """
    weights = {sleeve.symbol: sleeve.target_weight for sleeve in card.sleeves}
    for rule, table, magnitude in zip(card.rules, signal_tables, magnitude_tables, strict=True):
        if not table.fires(rule.on_symbol, decided_on):
            continue
        raw = _rule_shift(rule, magnitude, decided_on)
        if raw is None:
            continue
        shift = min(raw, weights[rule.from_symbol])
        weights[rule.from_symbol] -= shift
        weights[rule.to_symbol] += shift
    return weights


def _rule_shift(
    rule: TiltRule, magnitude: _RankTable | None, decided_on: dt.date
) -> Decimal | None:
    """This rule's shift on `decided_on`, in `[0, 1]`, or `None` when it should not fire.

    A constant `shift_pct` is already validated into range and returned unchanged. A `shift_expr` is
    read from its own table and bounded here rather than at validation time, because its value is not
    knowable until the session it is evaluated on.

    The `float` -> `Decimal` conversion goes through `str()` deliberately.
    `Decimal(0.1)` is 0.1000000000000000055511151231257827, and every weight in this module is an
    exact `Decimal` whose sum must equal `Decimal(1)` on the nose; letting binary float error into
    that arithmetic would put the partition invariant at the mercy of how a particular indicator
    happened to round.
    """
    if rule.shift_pct is not None:
        return rule.shift_pct
    if magnitude is None:  # unreachable: validation guarantees a table when shift_expr is set
        return None
    value = magnitude.value(rule.on_symbol, decided_on)
    if value is None or value <= 0.0:
        return None
    return min(Decimal(str(value)), Decimal(1))


def _current_weights(
    broker: PaperBroker, market: AsOfMarket, symbols: tuple[str, ...]
) -> tuple[Decimal, dict[str, Decimal]]:
    """Each sleeve's actual weight of the book, marked at `market`'s as-of close.

    `broker.mark` returns *prices*, not position values (see its own docstring), so the value per
    symbol is reconstructed here as `price * quantity_held`. An unpriceable or unheld symbol
    contributes a weight of `0`, mirroring `PaperBroker.mark`'s own "absent, not fabricated" handling
    of a holding it cannot price.
    """
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


def _rebalance_moves(
    card: AllocationCard,
    targets: dict[str, Decimal],
    actual_weights: dict[str, Decimal],
    equity: Decimal,
    cash: Decimal = Decimal(0),
) -> tuple[list[tuple[str, Decimal, Decimal]], list[tuple[str, Decimal, Decimal]]]:
    """Which sleeves need a rebalancing order this session, and how large -- split into sells and
    buys, each as `(symbol, delta_value, target)`.

    A pure function of one session's already-computed targets, actual weights, equity and cash: no
    broker call, no order submitted, nothing mutated. That is deliberate -- it is what makes "does the
    band suppress a given amount of drift" a question `tests/test_allocation_card.py` can ask
    directly, by calling this function with a drift below `card.band_pct` and asserting both returned
    lists are empty, rather than having to run a full session loop through `PaperBroker` and infer the
    absence of a trade from a side effect that did not happen.

    **The band is a trigger, not a filter -- `DEFECTS.md` D8.** Until 2026-08-30 the band was applied
    to each sleeve independently on both sides: a sleeve more than `band_pct` under its target
    produced a buy, one more than `band_pct` over produced a sell, and nothing else traded. That is
    symmetric per sleeve and asymmetric in aggregate, because **the overweight offsetting a breaching
    underweight can be spread across sleeves that are each individually inside the band**. The
    function then emitted a buy with nothing sold to pay for it. Measured on `qld-schd-sgov`: 59 of 61
    band-firing sessions produced buys with no sell, the engine submitted $4,469.75 against $73.69 of
    cash, and because the rejection left the sleeve underweight the same unfundable order returned
    every session for the rest of the run. It needs three or more sleeves to occur at all, which is
    why every two-sleeve test passed throughout -- with two sleeves the deviations are always equal
    and opposite.

    So a breach still *decides* whether anything trades, and every sleeve inside the band is still
    left alone when no sleeve breaches. What changed is what happens once one does: the buys are
    funded, from `cash` first and then by selling from **every** overweight sleeve, pro-rata to each
    sleeve's overweight, for exactly the amount still needed.

    Pro-rata rather than greedy-from-the-largest because greedy is path-dependent on sleeve order, and
    this programme's own 21.2-point noise floor came from measuring how much a result moves when a
    card's symbol ordering changes. Exactly-the-amount-needed rather than a full reset to target
    because a full reset is a different, higher-turnover strategy rather than a fix. Both choices, and
    the rejected alternative of resetting the whole book on any breach, are pre-registered in
    `strategy-program/ROUND-20-PLAN.md` section 2 -- written before this code was.

    **Settlement is deliberately not worked around here.** `PaperBroker` fills buys against *settled*
    cash and a sale settles T+1, so a funding sell emitted this session does not pay for a buy in the
    same session; the buy fills a session or two later instead. That is the constraint a real cash
    account has, and pre-crediting unsettled proceeds to make the numbers tidier would reintroduce
    exactly the fiction round 19 removed from the contribution harness. What the fix changes is that
    the retry now *terminates*.
    """
    sells: list[tuple[str, Decimal, Decimal]] = []
    buys: list[tuple[str, Decimal, Decimal]] = []

    # Every sleeve's signed deviation, kept whether or not it breaches -- the sleeves that fund a
    # breaching buy are precisely the ones that do not breach, so they cannot be discarded here.
    deviations: dict[str, Decimal] = {}
    for sleeve in card.sleeves:
        symbol = sleeve.symbol
        deviations[symbol] = actual_weights[symbol] - targets[symbol]
        if abs(deviations[symbol]) <= card.band_pct:
            continue  # inside the band -- see `AllocationCard.band_pct`'s own docstring
        delta_value = -deviations[symbol] * equity
        (buys if delta_value > 0 else sells).append((symbol, delta_value, targets[symbol]))

    if not buys:
        return sells, buys

    # What the breaching buys still need after this session's cash and any breaching sells.
    needed = sum((delta for _s, delta, _t in buys), Decimal(0))
    needed -= sum((-delta for _s, delta, _t in sells), Decimal(0))
    needed -= max(cash, Decimal(0))
    if needed <= 0:
        return sells, buys

    # Fund it from the overweight sleeves that did *not* breach, pro-rata to how overweight each is.
    already_selling = {symbol for symbol, _d, _t in sells}
    donors = {
        symbol: dev
        for symbol, dev in deviations.items()
        if dev > 0 and symbol not in already_selling
    }
    donor_total = sum(donors.values(), Decimal(0))
    if donor_total <= 0:
        # Nothing is overweight enough to donate. The buy stays unfunded and will be rejected -- which
        # is honest: the book genuinely cannot afford it this session.
        return sells, buys

    for symbol, dev in donors.items():
        share = needed * (dev / donor_total)
        # Never sell a donor past its own target: that would push it underweight to fix another
        # sleeve, turning one breach into a second one next session.
        cap = dev * equity
        amount = min(share, cap)
        if amount <= 0:
            continue
        sells.append((symbol, -amount, targets[symbol]))

    return sells, buys


# ---------------------------------------------------------------------------
# Sleeve bookkeeping -- weighted-average cost, not a FIFO lot list. See the module docstring's "what
# is *not* reused" section for why this is a deliberately different structure from
# `runner._OpenLot`.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _SleevePosition:
    """One sleeve's running position: whole-or-fractional shares held, and their blended cost basis.

    Not frozen -- this is this run's own mutable bookkeeping, updated in place on every fill, exactly
    as `runner._OpenLot`'s dict-of-lots is (there, by replacing the dict entry; here, by mutating the
    one object every sleeve owns for the life of the run).
    """

    quantity: Decimal = Decimal(0)
    avg_cost: Decimal = Decimal(0)
    opened_session_index: int | None = None
    """The session this sleeve's position was most recently opened from flat. `None` while flat.
    Not reset on a partial sell that leaves shares still held -- only when the position returns all
    the way to zero -- so a `RealisedTrade`'s `bars_held` measures how long *this* stretch of holding
    has run, the same quantity `runner._OpenLot.entry_session_index` measures for a StrategyCard
    lot."""
    opened_date: dt.date | None = None


def _apply_buy(position: _SleevePosition, fill: Fill, session: Session) -> None:
    """Blend `fill` into `position`'s running average cost, opening it first if it was flat.

    Buy commission (`fill.fees`; see `PaperBroker._fees` -- buys carry only `commission_per_trade`,
    never the SEC/TAF fees that are sell-only) is folded into the cost basis alongside the gross
    price paid, the same way a real brokerage statement's cost basis includes commission: a share
    bought for $100 plus a $1 commission has cost $101, not $100.
    """
    if position.quantity == 0:
        position.opened_session_index = session.index
        position.opened_date = fill.trade_date
    cost_basis_total = position.quantity * position.avg_cost + fill.gross + fill.fees
    new_quantity = position.quantity + fill.quantity
    position.avg_cost = (cost_basis_total / new_quantity) if new_quantity > 0 else Decimal(0)
    position.quantity = new_quantity


def _apply_sell(
    position: _SleevePosition,
    fill: Fill,
    session: Session,
    trades: list[RealisedTrade],
    metrics_trades: list[MetricsTrade],
) -> None:
    """Realise P&L on `fill.quantity` shares against `position`'s running average cost, and shrink it.

    Every sell (whether it empties the sleeve or only trims it) produces exactly one `RealisedTrade`,
    labelled `"rebalance_trim"` -- see `AllocationResult.trades`'s own docstring for why that is a
    new, valid value for that field rather than a misuse of it. `position.opened_session_index` /
    `.opened_date` are *not* touched by a partial sell that leaves shares still held: the position is
    still the same continuing holding, just smaller, so its "how long has this been open" clock does
    not restart until it actually returns to flat.
    """
    entry_session_index = (
        position.opened_session_index if position.opened_session_index is not None else session.index
    )
    entry_date = position.opened_date if position.opened_date is not None else fill.trade_date

    gross = (fill.price - position.avg_cost) * fill.quantity
    pnl = _money(gross - fill.fees)
    basis = position.avg_cost * fill.quantity
    return_pct = (pnl / basis) if basis != 0 else Decimal(0)
    bars_held = session.index - entry_session_index

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


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def run_allocation(
    card: AllocationCard,
    *,
    settings: Settings,
    mandate: Mandate,
    start: dt.date = TRADE_START,
    end: dt.date = TRADE_END,
) -> AllocationResult:
    """Trade `card` through a fresh `PaperBroker` from `start` to `end`, session by session.

    **Sizing is a fraction of *current* equity, not starting equity -- the opposite of
    `run_card`'s convention, and deliberately so.** `runner.py`'s own docstring explains at length why
    a StrategyCard's `position_pct * mandate.starting_cash` is computed once and reused for the whole
    run: sizing off current equity would let a StrategyCard silently re-lever after a drawdown. That
    argument does not apply here, because it depends on "one position's size" being a fixed,
    independently-declared number (`position_pct`) that current performance should not distort. A
    sleeve's target here is not a fixed dollar amount at all -- it is a *weight of the book as it
    currently stands*, which is the entire point of a rebalanced portfolio: if the book has grown,
    every sleeve's target dollar amount should grow with it, or "40% QLD" silently drifts into
    meaning "40% of what QLD was worth back when this ran started" the longer the run goes on. Each
    session's rebalancing decision below therefore reads `equity` fresh, from that session's own
    decision-time mark (see :func:`_current_weights`), not from `mandate.starting_cash`.

    **A sleeve trades only when its own drift exceeds `card.band_pct` -- not when the book's overall
    drift does, and not on a fixed schedule.** This is evaluated independently per sleeve, every
    session, against that session's own decision-time weights; two sleeves can be on opposite sides of
    their bands in the same session (one trimmed, one topped up) or neither can trade at all. Sells are
    submitted before buys for every session that has both, mirroring `run_card`'s "exits before
    entries" ordering for the identical reason: a sell's proceeds should be available to fund the same
    session's buys before `PaperBroker`'s settled-cash check is asked to approve them, not after. This
    ordering is necessary but, under a mandate with `settlement_days > 0`, not always sufficient --
    `PaperBroker._apply` marks a sell's own proceeds unsettled until `settlement_days` business days
    after the fill (the same good-faith-violation guard a real cash account is subject to), so a same
    session buy that depends on a same-session sell's cash can still be rejected as insufficient
    *settled* cash even though total cash is enough and the sell was submitted first. That is not a
    bug this ordering is meant to paper over; it is the mandate's own settlement rule doing exactly
    what it is there to do, and a rejection from it is recorded like any other (see
    `AllocationResult.rejections`).

    **Fills are at the next session's open, exactly as `run_card`'s are.** `market=decision_market`
    (as of `session.decided_on`) sizes and prices the decision; `fill_date=session.date` is what
    `PaperBroker.submit` actually fills at -- the identical two-argument call `run_card` makes on
    every order it submits.

    See the module docstring for why the return type is `AllocationResult`, not
    `app.tournament.models.AgentResult`, and for exactly how far the two are and are not
    interchangeable.
    """
    calendar = SessionCalendar(start=start, end=end, settings=settings, benchmark=_BENCHMARK)
    sessions = list(calendar)

    rule_trees = _guard_allocation_card(card, settings=settings, first_decided_on=sessions[0].decided_on)
    signal_tables = [
        _build_signal_table(cond, (rule.on_symbol,), settings=settings, through=sessions[-1].decided_on)
        for (cond, _mag), rule in zip(rule_trees, card.rules, strict=True)
    ]
    # Built only for rules that actually carry a `shift_expr`; a constant-shift rule gets `None` and
    # costs nothing, so a card written before this field existed does exactly the work it always did.
    magnitude_tables = [
        None
        if mag is None
        else _build_rank_table(
            mag, (rule.on_symbol,), settings=settings, through=sessions[-1].decided_on
        )
        for (_cond, mag), rule in zip(rule_trees, card.rules, strict=True)
    ]

    broker = PaperBroker(mandate)
    starting_equity = mandate.starting_cash

    positions: dict[str, _SleevePosition] = {sleeve.symbol: _SleevePosition() for sleeve in card.sleeves}
    trades: list[RealisedTrade] = []
    metrics_trades: list[MetricsTrade] = []
    equity_curve: list[Decimal] = []
    in_position_flags: list[bool] = []
    #: `invested_value / equity`, both at that same session's own close -- see
    #: `AllocationResult.capital_exposure`'s docstring for why this ratio, normalised to *that
    #: session's* equity rather than `starting_equity`, is the right quantity for a book whose dollar
    #: size is meant to compound rather than stay fixed at `run_card`'s per-session entry-notional
    #: sum would be.
    session_invested_ratio: list[float] = []
    order_seq = 0

    for session in sessions:
        decision_market = AsOfMarket(as_of=session.decided_on, settings=settings)
        _require_decision_market(decision_market, session)

        targets = _target_weights(card, signal_tables, magnitude_tables, session.decided_on)
        equity, actual_weights = _current_weights(broker, decision_market, card.universe)
        # `broker.cash` so a buy fundable from cash alone does not trigger a needless sell.
        sells, buys = _rebalance_moves(card, targets, actual_weights, equity, broker.cash)

        for symbol, delta_value, target in sells:
            try:
                price = decision_market.close(symbol)
            except UnpricedSymbol:
                continue
            held = positions[symbol].quantity
            quantity = min(_entry_quantity(mandate, -delta_value, price), held)
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
                    f"rebalance {symbol}: actual weight {actual_weights[symbol]} drifted past "
                    f"target {target} by more than the {card.band_pct} band; trimming back toward it"
                ),
                invalidation=(
                    "n/a -- this order rebalances a continuously held sleeve toward its own band, it "
                    "does not close a position"
                ),
            )
            outcome = broker.submit(order, market=decision_market, fill_date=session.date)
            if isinstance(outcome, Fill):
                _apply_sell(positions[symbol], outcome, session, trades, metrics_trades)
            # A `Rejection` is already recorded on `broker.rejections` -- see `PaperBroker._reject`'s
            # own docstring on being the sole append site, and `AllocationResult.rejections`.

        for symbol, delta_value, target in buys:
            try:
                price = decision_market.close(symbol)
            except UnpricedSymbol:
                continue
            quantity = _entry_quantity(mandate, delta_value, price)
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
                    f"rebalance {symbol}: actual weight {actual_weights[symbol]} drifted past "
                    f"target {target} by more than the {card.band_pct} band; topping up toward it"
                ),
                invalidation=(
                    "n/a -- this order rebalances a continuously held sleeve toward its own band, it "
                    "does not open a fresh one"
                ),
            )
            outcome = broker.submit(order, market=decision_market, fill_date=session.date)
            if isinstance(outcome, Fill):
                _apply_buy(positions[symbol], outcome, session)

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

    # Same D1 rebasing `run_card` applies -- see its own docstring's long comment at the equivalent
    # point -- prepending `starting_equity`'s own point so `compute()`'s "equity[0] normalised to 1.0"
    # contract is satisfied by construction rather than by a division that happens to cancel out.
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
    # `SessionCalendar` never yields zero sessions (see its own docstring), so `compute()` only takes
    # its all-`None` early-return path on an empty array, which cannot happen here.
    assert strategy_metrics.total_return is not None
    assert strategy_metrics.max_drawdown is not None

    capital_exposure = sum(session_invested_ratio) / len(sessions)

    return AllocationResult(
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

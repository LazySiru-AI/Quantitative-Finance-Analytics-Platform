"""The bridge: turn a frozen tournament card into a `contributions.simulate`-shaped weight function.

`strategy-program/tools/contributions.py` scores a strategy contribution-funded ($7,500/year into a
Roth) instead of lump-sum. It knows nothing about `AllocationCard` or `LadderCard` -- it asks only
for a `WeightFn`, `Callable[[int, Mapping[str, Sequence[float]]], dict[str, float]]`: given a session
index and every symbol's close history up to and including it, return each symbol's target weight of
the book. :func:`card_weight_fn` is the one function in this module; it takes a frozen
`AllocationCard` or `LadderCard` -- the exact same object `run_allocation`/`run_ladder_card` trade --
and returns a `WeightFn` that reproduces the same card's per-session decisions from closes alone.

**`WeightFn` is redefined here, not imported.** `strategy-program/tools/contributions.py` is not an
importable package from this module: `strategy-program` is not a valid Python identifier (the
hyphen), there is no `__init__.py` anywhere under it, and `backend/app/tournament` has no business
depending on a `strategy-program/tools` script in the first place -- the dependency runs the other
way (`r15_control.py`, a `strategy-program/tools` script, imports *this* module). The type alias
below is structurally identical to `contributions.WeightFn` on purpose; the two are checked against
each other only by `r15_control.py` actually calling `contributions.simulate` with a `card_weight_fn`
result, not by a shared import.

**Behaviour must match the engine's, rule for rule -- and where it provably cannot, this module
raises rather than approximating.** Three places that could have silently diverged, and what this
module does about each:

1. **Tilt conditions need bars; `contributions.simulate` gives closes.** `TiltRule.condition` is
   parsed and evaluated through `app.rules.grammar`/`app.rules.evaluate`, the identical path
   `AllocationCard` itself uses (see `app.tournament.allocation._guard_allocation_card`,
   `_target_weights`) -- never a second, hand-rolled condition reader. What changes is the bar frame:
   `evaluate()` only ever reads `bars["close"]` for `sma`, `ema`, `macd`, `rsi` and `bb` (checked
   directly against `app.indicators.trend`/`volatility`/`momentum`'s own source: none of those five
   touch `open`/`high`/`low`/`volume`), so a synthetic one-column frame built from
   `closes[on_symbol][: i + 1]` (see :func:`_synthetic_bars`) is exact for those five, not an
   approximation -- the indicator function never asks for anything this frame doesn't have. `atr`,
   `vwap`, `swing`, `rsi_at_swing` and `macd_at_swing` all read `high`/`low` and/or `volume`, none of
   which `contributions.simulate` ever receives; a condition that needs one of those cannot be
   answered from closes at all, and :func:`card_weight_fn` raises :class:`UnsupportedConditionError`
   the moment such a card is handed to it (construction time, not the first time the tilt would have
   fired) rather than silently treating the condition as always-false. An always-false tilt is exactly
   the failure mode this package's own brief warns about: it would make a card that shifts weight look
   like its own untilted base variant and produce a confidently wrong round result. Raising loudly, at
   the earliest possible point, is the only response that does not do that. The same rule applies to a
   bare price reference -- `open`, `high`, `low` and `volume` all raise; only `close` is supported.
   Both real cards in the library today (`qld-schd-sgov`'s two rules) use only `close < sma(150)` and
   `close > bb_upper(20,2)`, both fully supported.

2. **`LadderCard._confirmed` takes an `AsOfMarket`, not a closes slice.** `app.tournament.ladder`'s
   own `_confirmed` calls `market.history(...)`, which this module has no `AsOfMarket` to hand it (see
   point 1's reasoning for why: `contributions.simulate` supplies closes, never bars). Rather than
   force that call through a fabricated market object, :func:`_ladder_confirmed` reimplements the
   identical trailing-window comparison directly against a closes slice -- the same comparison
   `strategy-program/tools/drawdown_ladder.py`'s own `confirmed(i)` closure makes (`ladder.py`'s
   `_confirmed` was itself ported from that reference script; see `ladder.py`'s own module docstring).
   This is not a silent approximation: `tests/test_tournament_weightfn.py::TestConfirmedMatchesEngine`
   runs both functions against the same stored bars and asserts they agree on every session of several
   scenarios, so the reimplementation is proven equivalent rather than assumed to be.

3. **Everything else in the ladder's state machine is reused, not rewritten.** `_weight_for` (deepest
   breached rung wins, gap-through) and `_sleeve_targets` (QLD funded from IEF first, then SCHD) are
   imported directly from `app.tournament.ladder` -- they are already pure functions of `(rungs,
   drawdown)` and `(card, leveraged_weight)` with no `AsOfMarket`/`PaperBroker` dependency, so
   reimplementing them would be exactly the "write a second parser" mistake `allocation.py`'s own
   module docstring warns against, one level further down. Only the session-to-session state
   transition (`armed_depth`, `cycle_peak`, `new_high_at`, the once-per-cycle arming, the recovery
   clock) is restated here, because in `ladder.py` it is woven directly into `run_ladder_card`'s
   broker-submitting loop and cannot be imported as a standalone function. It is restated from
   `strategy-program/tools/drawdown_ladder.py`'s own `run_ladder` loop -- the settled reference spec
   `run_ladder_card` itself was ported from (see `ladder.py`'s own module docstring) -- translated
   against a closes-indexed loop instead of that script's, which is the same translation. This is
   *translation*, not *invention*: every branch below has a line-for-line counterpart in both
   `drawdown_ladder.run_ladder` and `app.tournament.ladder.run_ladder_card`.

**No lookahead.** `closes[sym]` is documented (by `contributions.WeightFn`'s own contract) to carry
the *full* series -- every session's close, including sessions after the one being decided. Nothing in
this module ever reads `closes[sym][j]` for `j > i`: the allocation bridge slices to `[: i + 1]` before
it touches `evaluate()`, and the ladder bridge indexes only `closes[signal_symbol][i]` for the
session's own price and `closes[signal_symbol][: i + 1]` for the confirmation window.
`tests/test_tournament_weightfn.py::TestNoLookahead` proves this by construction: it corrupts every
close after index `i` to an extreme value and asserts the weight returned for session `i` is
byte-identical to the uncorrupted call.

**A `LadderCard`'s `signal_symbol` is priced but never traded.** `LadderCard.universe` already
excludes it (see that property's own docstring); the `WeightFn` this module builds for a `LadderCard`
reads `closes[card.signal_symbol]` for the drawdown signal but never places it as a key in the
returned weight dict, so a caller handing `contributions.simulate` a `closes` mapping that includes
the signal symbol gets a mapping back with no entry for it -- `simulate`'s own `targets.get(s, 0.0)`
already treats an absent key as `0.0`, so the signal symbol is correctly never allocated to.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

from app.market.models import Interval
from app.rules import grammar
from app.rules.evaluate import evaluate as _evaluate_rule
from app.rules.evaluate import evaluate_num as _evaluate_num
from app.rules.grammar import RuleSyntaxError
from app.rules.nodes import (
    Arith,
    BoolExpr,
    BoolOp,
    Comparison,
    Cross,
    IndicatorRef,
    Literal,
    Not,
    NumExpr,
    PriceField,
    PriceRef,
)
from app.tournament.allocation import AllocationCard
from app.tournament.ladder import LadderCard
from app.tournament.ladder import _sleeve_targets as _ladder_sleeve_targets
from app.tournament.ladder import _weight_for as _ladder_weight_for

__all__ = [
    "UnsupportedConditionError",
    "WeightFn",
    "card_weight_fn",
]

#: Structurally identical to `strategy-program/tools/contributions.py`'s own `WeightFn` -- see this
#: module's own docstring for why it is redefined here rather than imported.
WeightFn = Callable[[int, Mapping[str, Sequence[float]]], dict[str, float]]


class UnsupportedConditionError(ValueError):
    """A `TiltRule.condition` needs data `contributions.simulate` cannot supply.

    Raised at `card_weight_fn` construction time -- before the returned `WeightFn` is ever called --
    so a card this bridge cannot honestly score fails loudly up front rather than quietly scoring as
    if the offending rule never fired. See this module's own docstring, point 1.
    """


# ---------------------------------------------------------------------------
# Which conditions this bridge can answer from closes alone
# ---------------------------------------------------------------------------

#: `sma`, `ema`, `macd` (`app.indicators.trend`) and `rsi` (`app.indicators.momentum`) read only
#: `bars["close"]` -- checked directly against each module's own source, not assumed. `bb`
#: (`app.indicators.volatility`) computes its bands from a rolling mean/std of `close` alone (unlike
#: `atr` in the same module, which needs `high`/`low`). Every other registered indicator --
#: `atr`, `vwap`, `swing`, `rsi_at_swing`, `macd_at_swing` -- reads `high`, `low` and/or `volume`,
#: none of which `contributions.simulate` ever receives.
_SUPPORTED_INDICATORS = frozenset({"sma", "ema", "macd", "rsi", "bb"})


def _check_num_supported(node: NumExpr, *, condition: str) -> None:
    """Raise :class:`UnsupportedConditionError` if `node` reads anything beyond `close`."""
    match node:
        case Literal():
            return
        case PriceRef(field=field):
            if field is not PriceField.CLOSE:
                raise UnsupportedConditionError(
                    f"condition {condition!r} reads the {field.value!r} price field, but "
                    "contributions.simulate only ever supplies closes -- only 'close' is supported "
                    "here; open/high/low/volume have no representation in a closes-only WeightFn"
                )
        case IndicatorRef(name=name):
            if name not in _SUPPORTED_INDICATORS:
                raise UnsupportedConditionError(
                    f"condition {condition!r} uses indicator {name!r}, which this bridge does not "
                    f"support -- only {sorted(_SUPPORTED_INDICATORS)} are computable from closes "
                    "alone (e.g. atr needs high/low, vwap needs high/low/volume, neither of which "
                    "contributions.simulate ever supplies). Extend this bridge deliberately if a "
                    "future card needs one of those, rather than letting the tilt silently never fire."
                )
        case Arith(left=left, right=right):
            _check_num_supported(left, condition=condition)
            _check_num_supported(right, condition=condition)


def _check_bool_supported(node: BoolExpr, *, condition: str) -> None:
    """Walk every `NumExpr` leaf of `node` through :func:`_check_num_supported`."""
    match node:
        case Comparison(left=left, right=right):
            _check_num_supported(left, condition=condition)
            _check_num_supported(right, condition=condition)
        case Cross(left=left, right=right):
            _check_num_supported(left, condition=condition)
            _check_num_supported(right, condition=condition)
        case Not(operand=operand):
            _check_bool_supported(operand, condition=condition)
        case BoolOp(operands=operands):
            for operand in operands:
                _check_bool_supported(operand, condition=condition)


def _synthetic_bars(closes_upto: Sequence[float]) -> pd.DataFrame:
    """A one-column bar frame `evaluate()` can read `close` off, index-aligned from `0`.

    Only `close` is populated -- see this module's docstring, point 1: every indicator
    :data:`_SUPPORTED_INDICATORS` allows reads only `bars["close"]`, and `_check_bool_supported`
    already rejected any condition that would need `open`/`high`/`low`/`volume` before this function
    is ever called, so there is nothing dishonest about the missing columns -- there is no rule left
    in scope that could have read them.
    """
    return pd.DataFrame({"close": pd.Series(closes_upto, dtype="float64")})


# ---------------------------------------------------------------------------
# AllocationCard -> WeightFn
# ---------------------------------------------------------------------------



def _rule_magnitude(rule: object, magnitude: NumExpr | None, bars: pd.DataFrame) -> Decimal | None:
    """This rule's shift for the latest bar in `bars`, or `None` when it should not fire.

    Deliberately the same three outcomes, the same bounds and the same `Decimal(str(...))` conversion
    as `app.tournament.allocation._rule_shift`. Two implementations of one rule is a thing this
    module already accepts (see its docstring on why the bar frame differs), and the way it stays
    honest is that they are written to agree line for line rather than merely in spirit.
    """
    if rule.shift_pct is not None:  # type: ignore[attr-defined]
        return rule.shift_pct  # type: ignore[attr-defined,no-any-return]
    if magnitude is None:  # unreachable: validation guarantees one when shift_expr is set
        return None
    series = _evaluate_num(magnitude, bars, interval=Interval.DAY)
    if not len(series):
        return None
    value = float(series.iloc[-1])
    if math.isnan(value) or value <= 0.0:
        return None
    return min(Decimal(str(value)), Decimal(1))


def _allocation_weight_fn(card: AllocationCard) -> WeightFn:
    """Reproduce `app.tournament.allocation._target_weights`'s arithmetic exactly, from closes.

    Base weights, then every rule applied in `card.rules` order against the output of the ones before
    it, each shift clamped by `min(rule.shift_pct, weights[rule.from_symbol])` -- the identical
    formula `_target_weights` uses, so the sum stays exactly `1` for the identical reason (see that
    function's own docstring). The only thing that differs from the engine is *how* a rule's truth is
    read: `_target_weights` indexes a pre-built `_SignalTable`; this evaluates the parsed condition
    tree fresh, each call, against a synthetic frame built from `closes[on_symbol][: i + 1]` (see
    :func:`_synthetic_bars`) -- unavoidable, since a `WeightFn` has no run-wide table to pre-build
    against and `contributions.simulate` never hands this module a full session list up front.

    Every condition is parsed once, up front, via `app.rules.grammar.parse` -- the same parser
    `AllocationCard`'s own conditions are guarded through -- and checked against
    :func:`_check_bool_supported` before the returned `WeightFn` is handed back, so a card this bridge
    cannot honestly score raises immediately rather than on its first (silently wrong) evaluation.

    **A rule sized by `TiltRule.shift_expr` is handled the same way, or refused the same way.** The
    magnitude is parsed with `parse_ranking` and put through :func:`_check_num_supported` up front,
    exactly as the condition is, so a shift expression this bridge cannot compute from closes alone
    -- `0.4 * atr(20) / close`, the obvious volatility-sizing form, needs `high`/`low` -- raises
    immediately instead of quietly reproducing something other than the engine. That matters more for
    a magnitude than for a condition: a condition this bridge got wrong makes a tilt fire on the wrong
    days, which shows up as a different trade list, while a magnitude it got wrong keeps every trade
    date identical and moves only the sizes. The test that pins this bridge against the engine
    (`tests/test_tournament_weightfn.py`) is the only thing that would notice.
    """
    trees: list[BoolExpr] = []
    magnitudes: list[NumExpr | None] = []
    for rule in card.rules:
        try:
            tree = grammar.parse(rule.condition)
        except RuleSyntaxError as exc:
            raise UnsupportedConditionError(
                f"card {card.agent_id!r} rule on {rule.on_symbol!r} has an unparseable condition "
                f"{rule.condition!r}: {exc}"
            ) from exc
        _check_bool_supported(tree, condition=rule.condition)
        trees.append(tree)

        if rule.shift_expr is None:
            magnitudes.append(None)
            continue
        try:
            magnitude = grammar.parse_ranking(rule.shift_expr)
        except RuleSyntaxError as exc:
            raise UnsupportedConditionError(
                f"card {card.agent_id!r} rule on {rule.on_symbol!r} has an unparseable shift_expr "
                f"{rule.shift_expr!r}: {exc}"
            ) from exc
        _check_num_supported(magnitude, condition=rule.shift_expr)
        magnitudes.append(magnitude)

    def weight_fn(i: int, closes: Mapping[str, Sequence[float]]) -> dict[str, float]:
        weights: dict[str, Decimal] = {sleeve.symbol: sleeve.target_weight for sleeve in card.sleeves}
        for rule, tree, magnitude in zip(card.rules, trees, magnitudes, strict=True):
            history = closes[rule.on_symbol][: i + 1]
            bars = _synthetic_bars(history)
            series = _evaluate_rule(tree, bars, interval=Interval.DAY).fillna(False)
            fires = bool(series.iloc[-1]) if len(series) else False
            if not fires:
                continue
            raw = _rule_magnitude(rule, magnitude, bars)
            if raw is None:
                continue
            shift = min(raw, weights[rule.from_symbol])
            weights[rule.from_symbol] -= shift
            weights[rule.to_symbol] += shift
        return {symbol: float(weight) for symbol, weight in weights.items()}

    return weight_fn


# ---------------------------------------------------------------------------
# LadderCard -> WeightFn -- see this module's docstring, points 2 and 3
# ---------------------------------------------------------------------------


def _ladder_confirmed(confirm_ma: int, closes_upto: Sequence[float]) -> bool:
    """Has the signal closed back above its own `confirm_ma`-session trailing average?

    The bounce-confirmation gate, reimplemented directly against a closes slice -- see this module's
    docstring, point 2, for why `app.tournament.ladder._confirmed` (which takes an `AsOfMarket`)
    cannot be called from here, and for the equivalence test that proves this reimplementation agrees
    with it.
    """
    if len(closes_upto) < confirm_ma:
        return False
    window = closes_upto[-confirm_ma:]
    return window[-1] > (sum(window) / len(window))


@dataclass(slots=True)
class _LadderState:
    """The ladder's own state, carried session to session by the closure in :func:`_ladder_weight_fn`.

    Field-for-field the same state `run_ladder_card`'s loop carries in local variables (`peak`,
    `cycle_peak`, `armed_depth`, `new_high_at`, `leveraged_weight`) -- see this module's docstring,
    point 3.
    """

    peak: Decimal | None = None
    cycle_peak: Decimal = Decimal(0)
    armed_depth: Decimal = Decimal(0)
    new_high_at: int | None = None
    leveraged_weight: Decimal = Decimal(0)


def _ladder_weight_fn(card: LadderCard) -> WeightFn:
    """Translate `run_ladder_card`'s per-session state transition into a closes-only `WeightFn`.

    See this module's docstring, points 2 and 3, for exactly what is reused (`_weight_for`,
    `_sleeve_targets`, both imported directly from `app.tournament.ladder`) versus restated
    (the state transition itself, which in `ladder.py` is woven into a broker-submitting loop and has
    no standalone function to import). Every branch below has a line-for-line counterpart in
    `app.tournament.ladder.run_ladder_card`'s own loop (see that function's source, the block that
    updates `leveraged_weight`) and in `strategy-program/tools/drawdown_ladder.run_ladder`, the
    reference spec both were ported from.

    **Statefulness.** Unlike the allocation bridge, this closure carries state (`_LadderState`)
    across calls -- required, because the ladder's own decision at session `i` depends on
    `armed_depth`/`cycle_peak`/`new_high_at` as they stood at the end of session `i - 1`, exactly as
    `run_ladder_card`'s own loop depends on its local variables from one iteration to the next. This
    is safe under `contributions.simulate`'s own calling convention -- `simulate` calls `weight_fn(i,
    closes)` for `i` in `range(len(dates))`, strictly increasing, exactly once each -- but means a
    `WeightFn` built by this function must not be reused across two independent runs; call
    `card_weight_fn` again for a second run, the same way `run_ladder_card` itself is called fresh
    per run.
    """
    state = _LadderState()

    def weight_fn(i: int, closes: Mapping[str, Sequence[float]]) -> dict[str, float]:
        signal_history = closes[card.signal_symbol][: i + 1]
        price = Decimal(str(signal_history[-1]))

        if state.peak is None:
            state.peak = price
            state.cycle_peak = price

        # A new high while leveraged starts the recovery clock -- checked against `leveraged_weight`
        # as it stood at the end of the *previous* session, before this session's own transition
        # logic runs below. Mirrors `run_ladder_card`'s own ordering exactly.
        if price > state.peak:
            if state.leveraged_weight > 0 and state.new_high_at is None:
                state.new_high_at = i
            state.peak = price

        drawdown = (price / state.peak) - Decimal(1)
        confirmed = _ladder_confirmed(card.confirm_ma, signal_history)
        target_weight = state.leveraged_weight

        if state.leveraged_weight == 0:
            # Base state: arm on the deepest rung this drawdown has reached, in one trade -- the
            # gap-through fix (see `_weight_for`'s own docstring).
            reached = _ladder_weight_for(card.rungs, drawdown)
            if reached > 0 and confirmed:
                target_weight = reached
                state.armed_depth = reached
                state.cycle_peak = state.peak
                state.new_high_at = None
        else:
            deeper = _ladder_weight_for(card.rungs, drawdown)
            if deeper > state.armed_depth and confirmed:
                # Ladder down. Fires once per level per cycle -- `armed_depth` only ever rises until
                # a full reset.
                target_weight = deeper
                state.armed_depth = deeper
            elif state.new_high_at is not None:
                sessions_since = i - state.new_high_at
                recovered = price >= state.cycle_peak * (Decimal(1) + card.recovery_gain)
                if recovered or sessions_since >= card.recovery_sessions:
                    target_weight = Decimal(0)
                    state.armed_depth = Decimal(0)
                    state.new_high_at = None
                elif sessions_since == 0:
                    target_weight = state.leveraged_weight * card.ath_haircut

        state.leveraged_weight = target_weight
        targets = _ladder_sleeve_targets(card, state.leveraged_weight)
        return {symbol: float(weight) for symbol, weight in targets.items()}

    return weight_fn


# ---------------------------------------------------------------------------
# The one public entry point
# ---------------------------------------------------------------------------


def card_weight_fn(card: AllocationCard | LadderCard) -> WeightFn:
    """A `WeightFn` that reproduces `card`'s own decisions from closes alone.

    Dispatches on `card`'s type -- `AllocationCard` to :func:`_allocation_weight_fn`, `LadderCard` to
    :func:`_ladder_weight_fn` -- since the two card shapes have no shared base class (see
    `allocation.py`'s and `ladder.py`'s own module docstrings for why) and their bridges share no
    logic beyond the module-level helpers above. Raises `TypeError` for anything else: a
    `StrategyCard` is a different decision shape entirely (binary entry/exit, not a weight -- see
    `allocation.py`'s own module docstring) and has no meaningful translation into this shape at all.
    """
    if isinstance(card, AllocationCard):
        return _allocation_weight_fn(card)
    if isinstance(card, LadderCard):
        return _ladder_weight_fn(card)
    raise TypeError(
        f"card_weight_fn bridges AllocationCard or LadderCard only, got {type(card).__name__!r}"
    )

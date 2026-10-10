"""The eight rule *shapes* a `"rules"` genome may express, and the one function that reads a
`Discipline` off an emitted rule instead of asking what label was attached to it.

**Why this module exists.** `app.evolution.proposer._rules_card` used to compose every candidate's
rule from a single hardcoded f-string::

    entry     = f"close > sma({regime_ma}) and ema({fast}) crosses_above ema({slow})"
    exit_rule = f"ema({fast}) crosses_below ema({slow})"

The completed 231-generation, 2,374-candidate run therefore explored exactly one strategy form and
varied only its numbers and its ticker universe -- it was structurally incapable of proposing a
mean-reversion, breakout or volatility candidate no matter how long it ran, and masking the numbers out
of all 25 of its outstanding seat requests yields exactly one distinct entry/exit template
(`docs/research/loop/01-what-the-search-found.md`). `RENDERERS` below is what replaces that constant:
eight forms, selected by the genome's own `rule_shape` trait, so the shape of the rule is something the
search can move through rather than a fact about the source code.

**Every shape spends the same three numbers, which is what keeps the parameter budget honest.** Each
renderer is a function of `fast`, `slow` and `regime_ma` and nothing else. `strategy-program/PROTOCOL.md`
section 3 budgets *ten free numbers per card* across entry, exit, the two brackets, the hold cap, slot
count and position size, and `Genome.traits`' own validator enforces it as ten keys; a shape that needed
its own threshold trait would have to buy that key from somewhere, and the only thing there was to sell
was the `discipline` label this module makes unnecessary. So the thresholds each form needs -- RSI's
40/60, Bollinger's 2 deviations, MACD's 9-bar signal, the 2%/5% ATR band -- are **structural constants of
the hypothesis, not knobs**: they are the textbook settings each form is conventionally stated at, they
are identical across every candidate of that shape, and no search step can move them. That is deliberate
under PROTOCOL section 4 ("no grid search"): a form whose canonical setting does not work is a finding,
where a form with a tunable threshold is an invitation to fit one.

**Why `classify` reads the AST and not the label.** `discipline` used to be drawn with
`rng.choice(list(Discipline))`, mutated to a different random value by the ordinary mutation step, and
passed only to `StrategyCard(discipline=...)` for display. Measured consequences from the completed run:
26 of 673 single-parent mutations produced a card behaviourally identical to its parent, 15 of them
differing in nothing but that label; and the 25 outstanding seat requests are only 23 distinct
strategies, because `g1815-d05786e4c611`("breakout") and `g1823-e2a3d5060b09`("mean-reversion") are
byte-identical in rule, universe, brackets, hold and sizing, as are `g1763-b3154a945165`("pairs-rotation")
and `g1767-775be2277569`("mean-reversion"). :func:`classify` takes the emitted text, parses it with the
same `app.rules.grammar` `_rules_card` already validates against, and derives the label from what the
rule *does* -- so two identical rules can no longer carry two different disciplines, and a mutation that
changes the label always changed the rule to earn it. It is the same principle
`app.evolution.dossier._rule_summary` already applies to a card's headline, one step earlier: there, the
label is worked around; here, it is made true.

**Two `Discipline` members are unreachable from this module, on purpose.** `PAIRS_ROTATION` cannot be
expressed at all: `entry` is evaluated per symbol against that symbol's own bars, so the grammar has no
way to write a spread, a pair or a condition contingent on another symbol (see `StrategyCard.rank_by`'s
own docstring on the single cross-sectional step the engine does have). It was nonetheless the completed
run's single most common label -- 348 of 934 rules genomes, and 13 of the 25 seat requests -- which is
the clearest possible demonstration of what a randomly-drawn label was worth. `RISK_MANAGED` is a
statement about the brackets and the hold cap, not about the entry condition, and this module is given
only the rule text; a card whose risk management is the hypothesis is a card a human should write.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from app.evolution.models import RULE_SHAPES, RuleShape
from app.rules import grammar
from app.rules.nodes import (
    Arith,
    BoolExpr,
    BoolOp,
    CompareOp,
    Comparison,
    Cross,
    CrossDir,
    IndicatorRef,
    Literal,
    Not,
    NumExpr,
    PriceField,
    PriceRef,
)
from app.tournament.models import Discipline

__all__ = ["classify", "describe", "render"]


@dataclass(frozen=True, slots=True)
class _Form:
    """One rule shape: how it renders, and how it reads in a thesis.

    `entry` and `exit` take `(fast, slow, regime_ma)` and return DSL text.
    `phrase` is the clause `app.evolution.proposer._rules_thesis` drops into "Tests {phrase}", written so
    a reader who never opens the card knows which of the eight forms this candidate is.
    """

    entry: Callable[[int, int, int], str]
    exit: Callable[[int, int, int], str]
    phrase: Callable[[int, int, int], str]


#: The search space, keyed by `app.evolution.models.RuleShape`.
#:
#: Each form uses `regime_ma` as a long-horizon filter, `slow` as its medium-horizon parameter and `fast`
#: as its short one, so `fast < slow < regime_ma` -- the ordering `app.evolution.genome._fix_rules_ordering`
#: maintains -- keeps meaning the same thing in all eight. Every entry and every exit here is parsed by
#: `app.rules.grammar` in `_rules_card` before a card is built, and by this module's own import-time check
#: for the trait vocabulary; `tests/test_evolution_ruleforms.py` additionally parses all eight over the
#: full bounded period range so a form that only breaks at one corner of it cannot ship.
RENDERERS: dict[RuleShape, _Form] = {
    # The incumbent, unchanged: a same-family EMA crossover inside an SMA regime filter.
    "ma-crossover": _Form(
        entry=lambda f, s, r: f"close > sma({r}) and ema({f}) crosses_above ema({s})",
        exit=lambda f, s, _r: f"ema({f}) crosses_below ema({s})",
        phrase=lambda f, s, r: f"a {f}/{s}-day EMA crossover trigger inside a {r}-day SMA regime filter",
    ),
    # Trend as a *state* rather than an edge: no cross, so it can hold through the whipsaw that takes a
    # crossover card out, and enters late rather than early.
    "momentum-state": _Form(
        entry=lambda f, s, r: f"close > sma({r}) and ema({f}) > ema({s}) and rsi({f}) > 55",
        exit=lambda f, s, _r: f"ema({f}) < ema({s})",
        phrase=lambda f, s, r: (
            f"a persistent-momentum state -- {f}-day EMA above the {s}-day and {f}-day RSI over 55, "
            f"inside a {r}-day SMA regime filter"
        ),
    ),
    # Mean reversion *with* the trend: buy weakness inside strength. RSI 40, not 30 -- a 30 threshold
    # under a rising-market filter fires on well under 1% of sessions across this pool's own bars, which
    # is a card that never trades rather than a hypothesis that fails.
    "rsi-pullback": _Form(
        entry=lambda f, _s, r: f"close > sma({r}) and rsi({f}) < 40",
        exit=lambda f, _s, _r: f"rsi({f}) > 60",
        phrase=lambda f, _s, r: (
            f"an RSI pullback -- {f}-day RSI under 40 while price holds above its {r}-day SMA -- exited "
            "when RSI recovers past 60"
        ),
    ),
    # The same idea in price rather than oscillator space, and the one form whose exit is a target rather
    # than a reversal: back to the middle of the channel is the whole trade.
    "band-reversion": _Form(
        entry=lambda _f, s, r: f"close > sma({r}) and close < bb_lower({s}, 2)",
        exit=lambda _f, s, _r: f"close crosses_above bb_mid({s}, 2)",
        phrase=lambda _f, s, r: (
            f"a Bollinger reversion -- price under the lower band of a {s}-day, 2-deviation channel while "
            f"still above its {r}-day SMA -- exited back at the channel's midline"
        ),
    ),
    # A genuine breakout: the confirmed swing high is a price level the market actually made, not a
    # statistic about it, and the exit is the symmetric swing low rather than an oscillator.
    "channel-breakout": _Form(
        entry=lambda f, _s, r: f"close crosses_above swing_high({f}) and close > sma({r})",
        exit=lambda f, _s, _r: f"close crosses_below swing_low({f})",
        phrase=lambda f, _s, r: (
            f"a channel breakout -- price clearing the last confirmed {f}-bar swing high inside a "
            f"{r}-day SMA regime filter -- exited on a break of the matching swing low"
        ),
    ),
    # Breakout stated as volatility expansion instead of structure: the upper band moves with realised
    # volatility, so this fires on a different set of sessions than the swing form does.
    "band-breakout": _Form(
        entry=lambda _f, s, r: f"close crosses_above bb_upper({s}, 2) and close > sma({r})",
        exit=lambda _f, s, _r: f"close crosses_below bb_mid({s}, 2)",
        phrase=lambda _f, s, r: (
            f"a volatility-expansion breakout -- price clearing the upper band of a {s}-day, "
            f"2-deviation channel inside a {r}-day SMA regime filter"
        ),
    ),
    # The oscillator counterpart of `ma-crossover`: the same two periods, read as a MACD line against its
    # own 9-bar signal rather than as two moving averages against each other.
    "macd-cross": _Form(
        entry=lambda f, s, r: (
            f"macd_macd({f}, {s}, 9) crosses_above macd_signal({f}, {s}, 9) and close > sma({r})"
        ),
        exit=lambda f, s, _r: f"macd_macd({f}, {s}, 9) crosses_below macd_signal({f}, {s}, 9)",
        phrase=lambda f, s, r: (
            f"a MACD({f},{s},9) signal-line crossover inside a {r}-day SMA regime filter"
        ),
    ),
    # Volatility as the entry condition rather than as a by-product: buy an uptrend while it is quiet, and
    # leave when it stops being quiet. The one form whose exit is an `or`.
    "vol-compression": _Form(
        entry=lambda f, s, r: (
            f"close > sma({r}) and ema({f}) > ema({s}) and atr({f}) / close < 0.02"
        ),
        exit=lambda f, _s, r: f"atr({f}) / close > 0.05 or close crosses_below sma({r})",
        phrase=lambda f, s, r: (
            f"a volatility-compression entry -- {f}-day ATR under 2% of price while the {f}-day EMA leads "
            f"the {s}-day inside a {r}-day SMA regime filter -- exited when ATR expands past 5% or the "
            "regime filter breaks"
        ),
    ),
}

# The one thing that could silently desynchronise the trait vocabulary in `app.evolution.models` (which
# `app.evolution.genome` draws from) and the renderers here (which `app.evolution.proposer` builds from)
# is adding a name to one and forgetting the other. A genome would then be drawn carrying a `rule_shape`
# no renderer knows, and the failure would surface as a `ProposalRejected` mid-generation rather than at
# import. `models.py` cannot run this check itself -- it must not import this module, which imports the
# grammar -- so it runs here, on the side that has both halves in scope.
if set(RENDERERS) != set(RULE_SHAPES):  # pragma: no cover -- import-time invariant
    raise RuntimeError(
        "ruleforms.RENDERERS and models.RULE_SHAPES disagree: "
        f"only in RENDERERS {sorted(set(RENDERERS) - set(RULE_SHAPES))}, "
        f"only in RULE_SHAPES {sorted(set(RULE_SHAPES) - set(RENDERERS))}"
    )


def render(shape: RuleShape, *, fast: int, slow: int, regime_ma: int) -> tuple[str, str]:
    """`(entry, exit)` DSL text for `shape` at these three periods.

    Does not parse what it produced -- `app.evolution.proposer._rules_card` runs
    `app.rules.grammar.parse` on both halves and turns a failure into `ProposalRejected`, which is the
    same treatment the single hardcoded template already got and the reason a genome from an unknown
    source is refused rather than trusted.

    Raises `KeyError` for an unregistered `shape`; callers building from a genome catch it (a genome is
    data that may have come from disk, so an unknown shape is a rejection, not a crash).
    """
    form = RENDERERS[shape]
    return form.entry(fast, slow, regime_ma), form.exit(fast, slow, regime_ma)


def describe(shape: RuleShape, *, fast: int, slow: int, regime_ma: int) -> str:
    """The clause naming what `shape` tests, for a card's `thesis`. Raises `KeyError` like `render`."""
    return RENDERERS[shape].phrase(fast, slow, regime_ma)


# ---------------------------------------------------------------------------
# Discipline, derived from the rule
# ---------------------------------------------------------------------------

#: Indicator outputs that are a *ceiling* -- a level price breaks out through. A cross above one, or price
#: sitting above one, is what distinguishes a breakout from every other form here.
_CEILINGS: frozenset[tuple[str, str | None]] = frozenset({("swing", "high"), ("bb", "upper")})

#: The symmetric floors -- a level price falls through or reverts from.
_FLOORS: frozenset[tuple[str, str | None]] = frozenset({("swing", "low"), ("bb", "lower")})

#: Bounded oscillators, whose position against a *constant* is the signal. `atr` is deliberately not here:
#: it is unbounded and measures volatility, so `atr(14) < 0.02 * close` says nothing about direction and
#: is classified as volatility instead.
_OSCILLATORS: frozenset[str] = frozenset({"rsi", "macd", "rsi_at_swing", "macd_at_swing"})

#: Moving averages, whose crossing or ordering is a trend statement.
_TRENDS: frozenset[str] = frozenset({"sma", "ema", "vwap"})

#: Volatility measures. A rule that reads one at all is making a statement about volatility -- but only
#: after the breakout and reversion tests have had their turn, since a Bollinger band is built from one.
_VOLATILITY: frozenset[str] = frozenset({"atr"})

_NEGATED_COMPARE: dict[CompareOp, CompareOp] = {
    CompareOp.LT: CompareOp.GTE,
    CompareOp.LTE: CompareOp.GT,
    CompareOp.GT: CompareOp.LTE,
    CompareOp.GTE: CompareOp.LT,
    CompareOp.EQ: CompareOp.NEQ,
    CompareOp.NEQ: CompareOp.EQ,
}

_PRICE_FIELDS: frozenset[PriceField] = frozenset(
    {PriceField.CLOSE, PriceField.OPEN, PriceField.HIGH, PriceField.LOW}
)


def _leaves(node: BoolExpr, *, negated: bool = False) -> Iterator[Comparison | Cross]:
    """Every `Comparison`/`Cross` in `node`, with `not` already pushed down into the operator.

    Pushing negation into the leaf rather than tracking it beside them is what lets every predicate
    below read as the plain thing it tests: `not (rsi(14) > 70)` reaches `_is_oscillator_below` as
    `rsi(14) <= 70` and is recognised, where a predicate that ignored polarity would classify it as the
    opposite of what it means. `and` and `or` are not distinguished -- a form's identity comes from the
    conditions it contains, not from how they are joined; the shapes here all use `and`, and a
    hand-written `or` still names the same disciplines.
    """
    match node:
        case Comparison() | Cross():
            yield _flip(node) if negated else node
        case Not(operand):
            yield from _leaves(operand, negated=not negated)
        case BoolOp(_, operands):
            for operand in operands:
                yield from _leaves(operand, negated=negated)


def _flip(node: Comparison | Cross) -> Comparison | Cross:
    """`node` with its operator negated.

    A `Cross` is the one case where this is an approximation and is stated as one: the strict negation of
    "crossed above on this bar" is "did not cross above on this bar", which is not "crossed below" -- most
    bars are neither. Reading it as the opposite direction is the reading that classifies `not (a
    crosses_above b)` as the bearish half of the same idea, which is what a label is for; nothing here
    evaluates a rule, so the approximation cannot reach a backtest.
    """
    if isinstance(node, Comparison):
        return Comparison(left=node.left, op=_NEGATED_COMPARE[node.op], right=node.right)
    opposite = CrossDir.BELOW if node.direction is CrossDir.ABOVE else CrossDir.ABOVE
    return Cross(left=node.left, direction=opposite, right=node.right)


def _refs(node: NumExpr) -> Iterator[IndicatorRef]:
    """Every `IndicatorRef` inside a numeric expression, so `atr(14) / close` is seen to reference `atr`."""
    match node:
        case IndicatorRef():
            yield node
        case Arith(left, _, right):
            yield from _refs(left)
            yield from _refs(right)


def _names(node: NumExpr) -> frozenset[str]:
    return frozenset(ref.name for ref in _refs(node))


def _is_price(node: NumExpr) -> bool:
    return isinstance(node, PriceRef) and node.field in _PRICE_FIELDS


def _is_level(node: NumExpr, levels: frozenset[tuple[str, str | None]]) -> bool:
    return isinstance(node, IndicatorRef) and (node.name, node.output) in levels


def _is_oscillator(node: NumExpr) -> bool:
    return isinstance(node, IndicatorRef) and node.name in _OSCILLATORS


def _is_trend_ref(node: NumExpr) -> bool:
    return isinstance(node, IndicatorRef) and node.name in _TRENDS and node.output is None


def _is_breakout(leaf: Comparison | Cross) -> bool:
    """Price clearing a channel ceiling -- as an edge (`crosses_above`) or as a state (`>`)."""
    if isinstance(leaf, Cross):
        return leaf.direction is CrossDir.ABOVE and _is_price(leaf.left) and _is_level(leaf.right, _CEILINGS)
    return (
        leaf.op in (CompareOp.GT, CompareOp.GTE)
        and _is_price(leaf.left)
        and _is_level(leaf.right, _CEILINGS)
    )


def _is_reversion(leaf: Comparison | Cross) -> bool:
    """Price under a channel floor, or a bounded oscillator under a constant -- "this is cheap"."""
    if isinstance(leaf, Cross):
        return leaf.direction is CrossDir.BELOW and _is_price(leaf.left) and _is_level(leaf.right, _FLOORS)
    if leaf.op not in (CompareOp.LT, CompareOp.LTE):
        return False
    if _is_price(leaf.left) and _is_level(leaf.right, _FLOORS):
        return True
    return _is_oscillator(leaf.left) and isinstance(leaf.right, Literal)


def _is_volatility(leaf: Comparison | Cross) -> bool:
    """Either side reads a volatility measure. Reached only after the breakout and reversion tests, so a
    Bollinger form is classified by what it does with the band, not by the fact that it has one."""
    return bool((_names(leaf.left) | _names(leaf.right)) & _VOLATILITY)


def _is_momentum(leaf: Comparison | Cross) -> bool:
    """A bounded oscillator over a constant, or an oscillator crossing its own signal line."""
    if isinstance(leaf, Cross):
        return leaf.direction is CrossDir.ABOVE and _is_oscillator(leaf.left) and _is_oscillator(leaf.right)
    return (
        leaf.op in (CompareOp.GT, CompareOp.GTE)
        and _is_oscillator(leaf.left)
        and isinstance(leaf.right, Literal)
    )


def _is_trend(leaf: Comparison | Cross) -> bool:
    """A moving-average crossover, price against a moving average, or one average against another."""
    if isinstance(leaf, Cross):
        return (_is_trend_ref(leaf.left) and _is_trend_ref(leaf.right)) or (
            _is_price(leaf.left) and _is_trend_ref(leaf.right)
        )
    if leaf.op in (CompareOp.EQ, CompareOp.NEQ):
        return False
    return (_is_price(leaf.left) or _is_trend_ref(leaf.left)) and _is_trend_ref(leaf.right)


#: Tried in order against every leaf of the entry rule, then -- only if the entry names nothing -- against
#: the exit's.
#:
#: The order is what resolves a rule that is honestly two things at once, and it runs from the most
#: specific claim to the least. Breakout first: clearing a channel ceiling is a narrower statement than
#: "price is above an average", and every breakout form here also carries a regime filter that would
#: otherwise read as trend. Reversion next, so `close < bb_lower(20, 2)` is read as buying weakness rather
#: than as the volatility measurement a Bollinger band technically is. Volatility third, which is where an
#: `atr` rule with no directional level lands. Momentum fourth: an oscillator over a constant is a weaker
#: claim than any of the three above. Trend last, the residual -- and the one every regime filter matches,
#: which is exactly why nothing else may be decided after it.
_TESTS: tuple[tuple[Callable[[Comparison | Cross], bool], Discipline], ...] = (
    (_is_breakout, Discipline.BREAKOUT),
    (_is_reversion, Discipline.MEAN_REVERSION),
    (_is_volatility, Discipline.VOLATILITY),
    (_is_momentum, Discipline.MOMENTUM),
    (_is_trend, Discipline.TREND),
)


def _classify_tree(tree: BoolExpr) -> Discipline | None:
    leaves = list(_leaves(tree))
    for test, discipline in _TESTS:
        if any(test(leaf) for leaf in leaves):
            return discipline
    return None


def classify(entry: str, exit_rule: str) -> Discipline | None:
    """The `Discipline` this rule *is*, read off the parsed rule -- or `None` if nothing here recognises it.

    `None`, never a guess. `app.evolution.proposer._rules_card` turns it into `ProposalRejected`, which
    makes an unclassifiable card a refusal rather than a card wearing an invented label -- the same line
    `app.evolution.dossier._rule_summary` holds when it falls back to raw expression text instead of a
    category. Since `_rules_card` only ever emits from `RENDERERS`, a `None` there means a renderer and
    these predicates have drifted apart, and `tests/test_evolution_ruleforms.py` asserts every one of the
    eight classifies so that drift fails in the suite rather than mid-generation.

    The entry rule decides. The exit is consulted only when the entry names nothing at all, because an
    exit is usually the *inverse* of the hypothesis (`rsi-pullback` exits on RSI over 60, which is a
    momentum condition attached to a mean-reversion card) and letting it vote would mislabel the form it
    belongs to. Unparseable text on either side is not an error here -- it is simply not classifiable, and
    `_rules_card`'s own `grammar.parse` call has already refused it by the time this matters.
    """
    for expression in (entry, exit_rule):
        if not isinstance(expression, str) or not expression.strip():
            continue
        try:
            tree = grammar.parse(expression)
        except grammar.RuleSyntaxError:
            continue
        found = _classify_tree(tree)
        if found is not None:
            return found
    return None

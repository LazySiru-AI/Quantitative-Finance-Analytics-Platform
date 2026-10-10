"""Walks a :mod:`app.rules.nodes` tree into a per-bar truth series.

**The result is a pandas nullable ``"boolean"`` Series, never plain ``bool``.** ``pd.NA`` is the
runtime encoding of :class:`~app.rules.models.TriState.UNKNOWN`: the state a rule is in through an
indicator's warmup window, and anywhere its inputs carry a gap. ``NaN < 30`` is ``False`` in numpy,
and letting that stand would silently report "the rule did not fire" for bars it was never given a
chance to fire on -- see ``app.rules.models``'s module docstring for why that corrupts a hit rate's
denominator. Every helper below is written to keep ``pd.NA`` distinct from ``False`` all the way
through: comparisons, arithmetic, crosses, and the boolean connectives.

Pandas' nullable ``"boolean"`` dtype already implements Kleene (three-valued) logic for ``&``,
``|`` and ``~`` -- ``pd.array([pd.NA]) & pd.array([False])`` is ``False`` (a known-false operand
makes the whole conjunction false regardless of the other side), ``pd.NA & True`` is ``NA``,
``pd.NA | True`` is ``True``, ``pd.NA | False`` is ``NA``, ``not NA`` is ``NA``. This module verified
that at the console before relying on it (see ``tests/test_rule_evaluate.py::TestKleeneLogic``) and
leans on the built-in operators rather than reimplementing truth tables by hand.

**Indicator resolution never re-derives a column name.** A node's indicator spec is turned into spec
text (``"bb:20,2"``), handed to :func:`app.indicators.registry.request`, and the column is read back
off the resolved :class:`~app.indicators.base.IndicatorRequest` -- via its ``columns`` property, which
delegates to :func:`app.indicators.base.column_name`. Formatting ``f"{name}_{args}"`` locally would
fork that format the moment someone changes it in one place and not the other.

**Sharing a computed indicator across two different rule trees is opt-in, via :class:`IndicatorCache`.**
Within one tree, indicator computation is already shared (``bb_upper(20,2)``/``bb_lower(20,2)`` cost
one ``bb`` call -- see :func:`_collect_indicator_keys`). Across two *different* trees -- ``rsi_oversold``
and ``rsi_overbought`` both wanting ``rsi:14`` -- nothing shared that by default, because :func:`evaluate`
has no notion of what any other call computed. Passing the same :class:`IndicatorCache` into both calls
fixes that without any module-level mutable state: the cache is a plain object the caller constructs,
hands to every :func:`evaluate` call it wants pooled together, and discards -- nothing is shared across
threads because nothing is shared beyond the object the caller already owns. See :class:`IndicatorCache`
for the guard against the failure mode that design has to avoid: silently serving one bar frame's
indicator values to a different bar frame.
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from dataclasses import dataclass
from functools import reduce

import numpy as np
import pandas as pd

from app.indicators import registry
from app.indicators.base import IndicatorError, IndicatorRequest
from app.market.models import Interval
from app.rules.nodes import (
    Arith,
    ArithOp,
    BoolExpr,
    BoolOp,
    BoolOpKind,
    CompareOp,
    Comparison,
    Cross,
    CrossDir,
    IndicatorRef,
    Literal,
    MacroRef,
    Not,
    NumExpr,
    PriceRef,
)

__all__ = [
    "IndicatorCache",
    "IndicatorCacheError",
    "RuleEvaluationError",
    "evaluate",
    "evaluate_num",
    "required_specs",
]


class RuleEvaluationError(ValueError):
    """The tree is well-formed but cannot be evaluated here.

    Distinct from the parser's errors (a malformed rule string never reaches this module at all --
    see ``app.rules.grammar``) and from a plain :class:`~app.indicators.base.IndicatorError`, which
    this module catches and re-raises as this type so callers only need to handle one exception
    class for "this rule cannot run against this data": an unknown indicator name, an out-of-range
    parameter (``rsi(0)``), or an indicator requested on an interval it is not defined for (VWAP on
    daily bars).
    """


#: One indicator reference, deduplicated by what it computes rather than how it is displayed --
#: `bb_upper(20,2)` and `bb_lower(20,2)` share a key so the underlying `bb` computation runs once
#: (see :func:`_collect_indicator_keys`), even though they resolve to different output columns.
_IndicatorKey = tuple[str, tuple[float | str, ...]]


def _fmt_spec_arg(value: float | str) -> str:
    """Render one :class:`~app.rules.nodes.IndicatorRef` argument for spec text.

    A numeric argument must round-trip as ``"14"``, not ``"14.0"``: an integer-kind parameter's
    :meth:`~app.indicators.base.ParamSpec.coerce` calls ``int(text)`` on the raw string, and
    ``int("14.0")`` raises. That is the same problem
    :func:`app.indicators.registry._fmt_default` solves for the same reason, duplicated here because
    that helper is private to its module.

    A string argument is passed through untouched. It carries a ``CHOICE_OR_DATE`` value -- the
    token ``session`` or an ISO date for ``vwap``'s anchor -- and the registry's own coercion
    decides whether it is valid. Reformatting it here (normalising the date, lowercasing the token)
    would mean this module quietly owning a validation rule that lives in `ParamSpec`.
    """
    if isinstance(value, str):
        return value
    return str(int(value)) if float(value).is_integer() else str(value)


def _spec_text(name: str, args: tuple[float | str, ...]) -> str:
    """``("bb", (20.0, 2.0))`` -> ``"bb:20,2"``; ``("rsi", ())`` -> ``"rsi"`` (all defaults)."""
    if not args:
        return name
    return f"{name}:{','.join(_fmt_spec_arg(a) for a in args)}"


def _collect_indicator_keys(node: NumExpr | BoolExpr) -> list[_IndicatorKey]:
    """Every distinct ``(name, args)`` pair the tree references, in first-encountered order.

    A plain recursive walk over both expression kinds. Order matters for :func:`required_specs`'s
    "stable order" contract, so this uses a dict-as-ordered-set rather than building a set and
    sorting it -- sorting spec strings would reorder them away from how the user wrote the rule.

    Accepts a bare :data:`~app.rules.nodes.NumExpr` as well as a rule, because a ranking key
    (:func:`evaluate_num`) is one -- ``rsi(14)`` has indicators to resolve exactly like the rule it
    would otherwise have been an operand of, and dispatching on the node kind here is what lets both
    entry points share :func:`_resolve_requests` rather than forking it.
    """
    seen: dict[_IndicatorKey, None] = {}

    def walk_num(n: NumExpr) -> None:
        match n:
            case IndicatorRef(name=name, args=args):
                seen.setdefault((name, args), None)
            case Arith(left=left, right=right):
                walk_num(left)
                walk_num(right)
            case Literal() | PriceRef() | MacroRef():
                pass

    def walk_bool(n: BoolExpr) -> None:
        match n:
            case Comparison(left=left, right=right):
                walk_num(left)
                walk_num(right)
            case Cross(left=left, right=right):
                walk_num(left)
                walk_num(right)
            case Not(operand=operand):
                walk_bool(operand)
            case BoolOp(operands=operands):
                for operand in operands:
                    walk_bool(operand)

    if isinstance(node, Literal | PriceRef | IndicatorRef | MacroRef | Arith):
        walk_num(node)
    else:
        walk_bool(node)
    return list(seen)


def required_specs(node: BoolExpr) -> list[str]:
    """Indicator spec strings the tree needs, e.g. ``["rsi:14", "bb:20,2"]``.

    Deduplicated by the underlying computation (see :func:`_collect_indicator_keys`), in the order
    each distinct indicator first appears in the tree. Does not validate the specs -- an unknown
    indicator or an out-of-range parameter is only discovered when :func:`evaluate` actually resolves
    them against the registry, because this function has no bars or interval to evaluate against and
    raising here would just move the same error to a place with less context.
    """
    return [_spec_text(name, args) for name, args in _collect_indicator_keys(node)]


def _resolve_requests(
    node: NumExpr | BoolExpr, *, interval: Interval
) -> dict[_IndicatorKey, IndicatorRequest]:
    """Resolve every indicator key the tree needs against the registry, once each.

    This is the point where a bad rule becomes visible: an unknown name, a parameter out of range,
    or an indicator requested on an interval it does not support (VWAP on daily bars) all raise
    :class:`~app.indicators.base.IndicatorError` from :func:`app.indicators.registry.request`, caught
    here and re-raised as :class:`RuleEvaluationError` so callers have one exception type to handle.
    """
    resolved: dict[_IndicatorKey, IndicatorRequest] = {}
    for name, args in _collect_indicator_keys(node):
        try:
            resolved[(name, args)] = registry.request(_spec_text(name, args), interval=interval)
        except IndicatorError as exc:
            raise RuleEvaluationError(str(exc)) from exc
    return resolved


def _indicator_column(ref: IndicatorRef, req: IndicatorRequest) -> str:
    """The column in the computed indicator frame that ``ref`` refers to.

    Reads the name off ``req.columns`` -- itself built by
    :meth:`~app.indicators.base.IndicatorSpec.columns`, which owns the ``f"{base}_{output}"``
    suffixing -- rather than reconstructing it here. A single-output indicator (``rsi``) has one
    column and no ``output``; a multi-output one (``bb``) must have its output selected, and an
    unselected or unknown output is a rule-construction bug this surfaces as
    :class:`RuleEvaluationError` rather than a silent ``KeyError`` or the wrong column.
    """
    columns = req.columns
    if not req.spec.outputs:
        return columns[0]
    if ref.output is None or ref.output not in req.spec.outputs:
        outputs = ", ".join(req.spec.outputs)
        raise RuleEvaluationError(
            f"{ref.name} has multiple outputs ({outputs}); an output must be selected, got "
            f"{ref.output!r}"
        )
    return columns[req.spec.outputs.index(ref.output)]


#: One cache slot: which bar frame's indicator columns are stored, for a given interval and
#: indicator key. Interval is part of the key (not just something the caller happens to hold
#: constant) because nothing here stops a caller from evaluating the same tree against two
#: intervals with one cache -- an ``rsi:14`` computed on daily bars must never answer for one
#: computed on 5-minute bars just because both share a spec string.
type _IndicatorCacheKey = tuple[Interval, _IndicatorKey]


class IndicatorCacheError(ValueError):
    """An :class:`IndicatorCache` was handed bars it was not populated from.

    A programming error in the caller, not a property of any rule tree -- distinct from
    :class:`RuleEvaluationError`, which is about a tree that cannot be evaluated at all. This is
    raised instead of silently returning whatever the cache already holds: see
    :class:`IndicatorCache`'s docstring for why a stale hit is worse than the redundant computation
    this cache exists to avoid.
    """


@dataclass(frozen=True, slots=True)
class _BarsFingerprint:
    """Enough about a bar frame to catch "this is not the frame I was populated from" cheaply.

    Length plus first and last timestamp, not a hash of the whole frame: an :class:`IndicatorCache`
    is checked on every access, potentially many times per :func:`evaluate` call, so the check itself
    must not reintroduce the cost the cache exists to remove. This is a heuristic, not a
    cryptographic guarantee -- two different frames of the same length sharing both endpoint
    timestamps would slip past it -- but see :class:`IndicatorCache`: it is deliberately biased
    toward catching the mistake this cache is actually at risk of (a stale or wrong-symbol cache
    reused across a request boundary), not toward being tamper-proof.
    """

    length: int
    first_ts: pd.Timestamp | None
    last_ts: pd.Timestamp | None


def _fingerprint(bars: pd.DataFrame) -> _BarsFingerprint:
    if bars.empty:
        return _BarsFingerprint(length=0, first_ts=None, last_ts=None)
    ts = bars["ts"]
    return _BarsFingerprint(length=len(bars), first_ts=ts.iloc[0], last_ts=ts.iloc[-1])


class IndicatorCache:
    """A caller-owned, request-scoped cache of computed indicator columns, shared across however
    many :func:`evaluate` calls run against **one** bar frame.

    **Why caller-owned rather than module-level state.** ``app.rules.service``'s own docstring
    records why patching :mod:`app.indicators.registry` for the duration of a request was ruled out:
    these endpoints are synchronous FastAPI handlers dispatched to a thread pool, and two concurrent
    requests mutating and restoring the same module-level function would race. An ``IndicatorCache``
    sidesteps that by holding no global state at all -- a caller constructs one, hands it to every
    :func:`evaluate` call it wants pooled together, and lets it go out of scope when the request
    ends. Nothing is ever shared *across* threads because nothing outlives the one call stack that
    owns it; the sharing this class provides is scoped to exactly the calls its owner chooses to hand
    it to.

    **The bars-fingerprint guard exists because a stale hit is worse than a miss.** A cache
    accidentally reused across two different bar frames -- a leftover instance from a previous
    request, a bug that hands one symbol's cache to another symbol's evaluation -- would silently
    return the wrong frame's ``rsi:14`` values: numerically plausible, correctly index-aligned, and
    simply wrong. Feeding that into the statistical machinery this cache was built to speed up
    (:mod:`app.backtest.scan`'s binomial test) is a materially worse defect than the redundant
    computation this class exists to avoid, so every access binds the cache to the first bar frame it
    saw (see :func:`_fingerprint`) and raises :class:`IndicatorCacheError` on any later access with a
    different one, rather than serving whatever ``_values`` already holds.
    """

    __slots__ = ("_fingerprint", "_values")

    def __init__(self) -> None:
        self._fingerprint: _BarsFingerprint | None = None
        self._values: dict[_IndicatorCacheKey, dict[str, pd.Series]] = {}

    def _bind(self, bars: pd.DataFrame) -> None:
        """Record the first bar frame seen, or confirm this access matches it.

        Called on every :meth:`get` and :meth:`put` -- not just on writes -- so a read-only cache
        hit against the wrong bars is caught just as reliably as a write would be.
        """
        fingerprint = _fingerprint(bars)
        if self._fingerprint is None:
            self._fingerprint = fingerprint
        elif self._fingerprint != fingerprint:
            raise IndicatorCacheError(
                "this IndicatorCache was already populated from a different bar frame (cached "
                f"{self._fingerprint!r}, got {fingerprint!r}) -- construct a new IndicatorCache per "
                "(symbol, interval, bar frame) instead of reusing one across requests; reusing it "
                "here would silently serve one series' indicator values as another's"
            )

    def get(
        self, interval: Interval, key: _IndicatorKey, bars: pd.DataFrame
    ) -> dict[str, pd.Series] | None:
        """The cached ``{column: series}`` for ``key`` at ``interval``, or ``None`` on a cache miss."""
        self._bind(bars)
        return self._values.get((interval, key))

    def put(
        self,
        interval: Interval,
        key: _IndicatorKey,
        bars: pd.DataFrame,
        columns: dict[str, pd.Series],
    ) -> None:
        """Store the just-computed ``{column: series}`` for ``key`` at ``interval``."""
        self._bind(bars)
        self._values[(interval, key)] = columns


@dataclass(frozen=True, slots=True)
class _Context:
    """The immutable inputs threaded through one :func:`evaluate` call's recursion."""

    bars: pd.DataFrame
    indicators: pd.DataFrame
    requests: dict[_IndicatorKey, IndicatorRequest]
    macro: pd.DataFrame | None = None
    """Release-lagged macro columns, indexed like :attr:`bars`, or ``None`` when the caller supplied
    none. Built by :func:`app.rules.macro_binding.bind_macro` **before** evaluation, never here: the
    release-date rule is one join per card, not one decision per node, so there is a single place it
    can be got wrong. ``None`` is not "no macro data available" -- it is "this caller does not support
    macro", and a tree containing a :class:`MacroRef` raises against it rather than silently
    evaluating to ``NA``."""


_ARITH_OPS: dict[ArithOp, Callable[[pd.Series, pd.Series], pd.Series]] = {
    ArithOp.ADD: operator.add,
    ArithOp.SUB: operator.sub,
    ArithOp.MUL: operator.mul,
}

_COMPARE_OPS: dict[CompareOp, Callable[[pd.Series, pd.Series], pd.Series]] = {
    CompareOp.LT: operator.lt,
    CompareOp.LTE: operator.le,
    CompareOp.GT: operator.gt,
    CompareOp.GTE: operator.ge,
    CompareOp.EQ: operator.eq,
    CompareOp.NEQ: operator.ne,
}


def _eval_num(node: NumExpr, ctx: _Context) -> pd.Series:
    """A numeric series for ``node``, ``float64``, indexed like ``ctx.bars``, ``NaN`` where undefined.

    Plain ``NaN`` rather than pandas' nullable ``Float64`` on purpose: every numeric leaf here (a bar
    column, an indicator output, a constant broadcast) is already ``float64`` with ``NaN`` marking
    "no value", and staying in that dtype the whole way down keeps arithmetic ordinary numpy
    vectorised math. Only the boolean layer above (:func:`_kleene_compare`, :func:`_eval_cross`)
    needs the nullable dtype, because only there does "no value" need to become a third truth value
    rather than propagate as itself.
    """
    match node:
        case Literal(value=value):
            return pd.Series(float(value), index=ctx.bars.index, dtype="float64")
        case PriceRef(field=field):
            return ctx.bars[field.value].astype("float64")
        case MacroRef(field=macro_field):
            # Structurally identical to `PriceRef` above, and that is the design: by the time the
            # evaluator sees it, a macro series is just another column aligned to `bars.index`. All
            # of the release-date logic lives in `app.rules.macro_binding.bind_macro`, which ran once
            # before this walk started.
            #
            # A missing frame or column raises rather than yielding NaN. NaN would propagate to `NA`
            # through the Kleene layer and the card would simply never enter -- a card that silently
            # never trades looks like a strategy with no signals, not like a wiring bug, and this
            # programme has a documented history of exactly that shape of silent nothing
            # (`DEFECTS.md` D5).
            if ctx.macro is None:
                raise RuleEvaluationError(
                    f"rule references macro({macro_field.value}) but this evaluation was given no "
                    f"macro frame; the caller must bind one with "
                    f"app.rules.macro_binding.bind_macro before evaluating"
                )
            if macro_field.value not in ctx.macro.columns:
                raise RuleEvaluationError(
                    f"rule references macro({macro_field.value}) but the bound macro frame has only "
                    f"{sorted(ctx.macro.columns)}; bind_macro must be given every field the tree "
                    f"reaches (see app.backtest.guards.required_macro_refs)"
                )
            return ctx.macro[macro_field.value].astype("float64")
        case IndicatorRef() as ref:
            req = ctx.requests[(ref.name, ref.args)]
            column = _indicator_column(ref, req)
            return ctx.indicators[column].astype("float64")
        case Arith(left=left, op=op, right=right):
            left_s = _eval_num(left, ctx)
            right_s = _eval_num(right, ctx)
            if op is ArithOp.DIV:
                # A zero divisor must yield NaN, not the `inf` numpy produces -- `inf` compares as
                # an ordinary number (`inf > 0` is True), which would silently satisfy a downstream
                # comparison instead of reporting "undefined here". `right_s != 0` is False for NaN
                # divisors too, but that is harmless: `x / NaN` is already NaN with nothing to fix.
                with np.errstate(divide="ignore", invalid="ignore"):
                    result = left_s / right_s
                return result.where(right_s != 0, np.nan)
            return _ARITH_OPS[op](left_s, right_s)


def _kleene_compare(left: pd.Series, right: pd.Series, op: CompareOp) -> pd.Series:
    """A nullable ``"boolean"`` comparison: ``NA`` wherever either side is ``NaN``.

    ``left.gt(right)`` (and friends) already returns ``False`` for a ``NaN`` operand -- numpy's
    ordinary behaviour, and exactly the silent-``False`` failure mode this whole module exists to
    avoid. Computed anyway (it is correct everywhere both sides are defined) and then explicitly
    overwritten to ``pd.NA`` whereever either input was missing, rather than trusted at those
    positions.
    """
    raw = _COMPARE_OPS[op](left, right)
    result = raw.astype("boolean")
    result[left.isna() | right.isna()] = pd.NA
    return result


def _eval_cross(node: Cross, ctx: _Context) -> pd.Series:
    """``a crosses_above b`` <=> ``a[t] > b[t] and a[t-1] <= b[t-1]`` (below: the mirror image).

    Both halves are built from :func:`_kleene_compare` so a gap in either series' history -- not
    just the shift -- yields ``NA`` rather than a fabricated ``False``. Only ``.shift(1)`` is used:
    a rule's value at bar ``t`` may depend only on bars ``<= t``, and ``.shift(-1)`` (bar ``t+1``)
    would leak the future into "did this cross right now" -- see the module-level lookahead guard
    test in ``tests/test_rule_evaluate.py`` for the property this must satisfy across every rule.

    The very first bar has no ``t-1`` at all: ``.shift(1)`` puts a structural ``NaN`` there (there is
    no missing *data*, there is no *row*), which already makes ``prev`` come out ``NA`` at that
    position via the same masking every other gap gets. It is forced to ``NA`` explicitly anyway
    (rather than left to fall out of Kleene ``AND``) so the first bar is unconditionally "unknown"
    regardless of what ``cur`` happens to be there -- a real cross event at bar 0 is not observable no
    matter which side of the level ``a`` starts on, which is a stronger claim than "the AND happened
    to come out that way," and this makes it hold by construction rather than by accident of which
    operand Kleene's short-circuit favours.
    """
    left = _eval_num(node.left, ctx)
    right = _eval_num(node.right, ctx)
    if node.direction is CrossDir.ABOVE:
        cur = _kleene_compare(left, right, CompareOp.GT)
        prev = _kleene_compare(left.shift(1), right.shift(1), CompareOp.LTE)
    else:
        cur = _kleene_compare(left, right, CompareOp.LT)
        prev = _kleene_compare(left.shift(1), right.shift(1), CompareOp.GTE)
    result = cur & prev
    if len(result) > 0:
        result.iloc[0] = pd.NA
    return result


def _eval_bool(node: BoolExpr, ctx: _Context) -> pd.Series:
    """A nullable ``"boolean"`` series for ``node``, Kleene logic all the way through.

    ``&``, ``|`` and ``~`` on pandas' ``"boolean"`` dtype already implement three-valued logic
    (``NA & False -> False``, ``NA & True -> NA``, ``NA | True -> True``, ``NA | False -> NA``,
    ``~NA -> NA``) -- see the module docstring. Reused directly rather than reimplemented so the
    truth table this module depends on is the one pandas ships and tests, not a hand-rolled copy that
    could silently drift from it.
    """
    match node:
        case Comparison(left=left, op=op, right=right):
            return _kleene_compare(_eval_num(left, ctx), _eval_num(right, ctx), op)
        case Cross() as cross:
            return _eval_cross(cross, ctx)
        case Not(operand=operand):
            return ~_eval_bool(operand, ctx)
        case BoolOp(op=kind, operands=operands):
            evaluated = [_eval_bool(operand, ctx) for operand in operands]
            if not evaluated:
                raise RuleEvaluationError("a BoolOp node must have at least one operand")
            reducer = operator.and_ if kind is BoolOpKind.AND else operator.or_
            return reduce(reducer, evaluated)


def _compute_indicators(
    bars: pd.DataFrame,
    requests: dict[_IndicatorKey, IndicatorRequest],
    *,
    interval: Interval,
    indicator_cache: IndicatorCache | None,
) -> pd.DataFrame:
    """The indicator frame :func:`_eval_num` reads columns from.

    Without a cache (``indicator_cache`` is ``None``), this is exactly the old, uncached behaviour:
    everything in ``requests`` computed in one :func:`~app.indicators.registry.compute` call. With
    one, ``requests`` is split into what the cache already holds for ``(interval, key)`` -- reused
    untouched, no computation at all -- and what it does not, which is still computed in a single
    batched call (not one call per missing key: a multi-output indicator like ``bb`` still costs one
    call even on a cache miss) and written back before this returns.
    """
    if indicator_cache is None:
        return registry.compute(bars, list(requests.values()))

    columns: dict[str, pd.Series] = {}
    pending: dict[_IndicatorKey, IndicatorRequest] = {}
    for key, req in requests.items():
        cached = indicator_cache.get(interval, key, bars)
        if cached is None:
            pending[key] = req
        else:
            columns.update(cached)

    if pending:
        computed = registry.compute(bars, list(pending.values()))
        for key, req in pending.items():
            per_request = {col: computed[col] for col in req.columns}
            indicator_cache.put(interval, key, bars, per_request)
            columns.update(per_request)

    return pd.DataFrame(columns, index=bars.index)


def evaluate(
    node: BoolExpr,
    bars: pd.DataFrame,
    *,
    interval: Interval,
    indicator_cache: IndicatorCache | None = None,
    macro: pd.DataFrame | None = None,
) -> pd.Series:
    """Truth value per bar. dtype ``"boolean"`` (pandas nullable), index aligned to ``bars.index``.

    Resolves every indicator the tree references against :mod:`app.indicators.registry` once each
    (see :func:`_resolve_requests`), computes them all in a single
    :func:`~app.indicators.registry.compute` call, then walks the tree. Zero bars, one bar, or fewer
    bars than an indicator's warmup all fall out of that same path with no special-casing here: the
    registry already returns a correctly shaped, all-``NaN``-where-appropriate frame for those cases
    (see ``app.indicators.base``'s warmup contract), and every operator above this point propagates
    ``NaN``/``NA`` rather than raising on it.

    ``indicator_cache`` is ``None`` by default, which reproduces the paragraph above exactly --
    every existing caller is unaffected by this parameter's existence. Passed an :class:`IndicatorCache`
    shared across several calls against the *same* bars, a computation is skipped wherever that cache
    already has it: two different rule trees that both reference ``rsi:14`` (``rsi_oversold`` and
    ``rsi_overbought``, the motivating case -- see the module docstring) compute it once between them
    rather than once each. See :class:`IndicatorCache` for the design, and in particular the guard
    against handing it bars it was not populated from.
    """
    requests = _resolve_requests(node, interval=interval)
    try:
        indicators = _compute_indicators(
            bars, requests, interval=interval, indicator_cache=indicator_cache
        )
    except IndicatorError as exc:
        raise RuleEvaluationError(str(exc)) from exc
    ctx = _Context(bars=bars, indicators=indicators, requests=requests, macro=macro)
    return _eval_bool(node, ctx)


def evaluate_num(
    node: NumExpr,
    bars: pd.DataFrame,
    *,
    interval: Interval,
    indicator_cache: IndicatorCache | None = None,
    macro: pd.DataFrame | None = None,
) -> pd.Series:
    """Numeric value per bar. dtype ``float64``, index aligned to ``bars.index``, ``NaN`` undefined.

    :func:`evaluate` for the numeric half of the grammar. Same resolution, same single
    :func:`~app.indicators.registry.compute` call, same cache semantics -- the only difference is
    which of the two walkers the tree is handed to at the end, because the caller wants a magnitude
    rather than a truth value.

    **The caller is a cross-sectional comparison, and this returns a per-symbol series.** Ranking
    happens above this function, in `app.tournament.runner`, by evaluating one key against each
    symbol's own bars and then sorting the resulting scalars against each other. Nothing here sees
    more than one symbol, which is deliberate: the indicator layer's whole contract is one bar frame
    in, one frame out (`app.indicators.base.IndicatorFn`), and widening it to a panel to support
    ranking would rewrite every indicator in the registry to buy nothing this composition does not
    already give.

    ``NaN`` is not an error here and must not be read as "rank last" by accident -- through an
    indicator's warmup a symbol genuinely has no key value, and the runner drops those to the back
    of the order explicitly rather than relying on how a sort happens to treat ``NaN``.
    """
    requests = _resolve_requests(node, interval=interval)
    try:
        indicators = _compute_indicators(
            bars, requests, interval=interval, indicator_cache=indicator_cache
        )
    except IndicatorError as exc:
        raise RuleEvaluationError(str(exc)) from exc
    ctx = _Context(bars=bars, indicators=indicators, requests=requests, macro=macro)
    return _eval_num(node, ctx)

"""The rule expression AST.

Shared contract between the parser (:mod:`app.rules.grammar`) and the evaluator
(:mod:`app.rules.evaluate`). Neither owns it, because a tree the parser can build but the evaluator
cannot walk is a bug that only shows up at runtime.

**There is no ``eval`` anywhere in this package, and there must never be.** A rule is a string the
user types and the app stores; handing it to the interpreter would make "what is my RSI doing"
share an execution context with the process holding the user's brokerage ledger. The grammar here
is closed: a fixed set of node types, a fixed operator table, and function names resolved against
the indicator registry rather than any Python namespace. Anything the grammar cannot express is a
parse error, which is the point -- an expression language for charts is not supposed to be
Turing-complete.

**Every node is a pure description, not a computation.** A node holds what the user asked for; the
evaluator decides how to produce a series from it. That split is what lets the same tree be
rendered back to text for display, walked to collect the indicator requests a rule needs before any
data is fetched, and evaluated -- three jobs that would otherwise each re-parse the string.

Two expression kinds, deliberately not unified:

* :class:`NumExpr` produces a numeric series -- a price column, an indicator output, a constant, or
  arithmetic over those.
* :class:`BoolExpr` produces a boolean series -- comparisons, crosses, and the logical operators.

Keeping them apart in the *types* is what makes ``rsi(14) and close`` a parse error rather than a
silently truthy series. A DSL that lets a number stand in for a condition will eventually evaluate
``close`` as "close != 0", which is true on every bar of every instrument ever traded.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "Arith",
    "ArithOp",
    "BoolExpr",
    "BoolOp",
    "BoolOpKind",
    "CompareOp",
    "Comparison",
    "Cross",
    "CrossDir",
    "IndicatorRef",
    "Literal",
    "MacroField",
    "MacroRef",
    "Not",
    "NumExpr",
    "PriceField",
    "PriceRef",
]


class PriceField(StrEnum):
    """Raw bar columns a rule may reference by name.

    ``adj_close`` is deliberately absent. It is split- *and* dividend-adjusted, so its whole history
    shifts every time a dividend is paid -- a rule written against it would silently mean something
    different tomorrow than it did today, and a trigger date recorded last month would no longer
    reproduce. Indicators already refuse to read it for the same reason.
    """

    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"
    VOLUME = "volume"


class MacroField(StrEnum):
    """FRED series a rule may reference by name -- the first non-price input the DSL has ever had.

    Until 2026-08-29 the only leaves a rule could read were :class:`PriceField` and an indicator
    computed from those columns. `docs/research/programme/00-EVERYTHING-TESTED.md` §3b records what
    that cost: FRED's rate, curve and energy series, the Fear & Greed index and the event calendar
    are all *collected, displayed, and unreachable by any card*, and its recommendation #4 is to give
    the DSL one non-price field. `strategy-program/ROUND-21-PLAN.md` is the pre-registration that
    change exists to serve.

    **Closed at exactly seven members, deliberately.** An eighth series is an edit here plus an entry
    in :data:`app.rules.macro_binding.RELEASE_LAG`, and the guard fails closed if the second is
    forgotten (`app.backtest.guards`). A series added to this enum alone would otherwise bind with a
    zero release lag -- reading a value on the day it *refers to* rather than the day it was
    *published* -- and the first sign of it would be an inflated backtest, not an error.

    **These are levels, and three of them are not stationary.** `PCEPI`, `PCEPILFE` and `CPILFESL`
    are price indices that roughly triple in nominal terms across this programme's window matrix, so
    a bare threshold against a literal (`macro(CPILFESL) > 300`) is a date test wearing a regime
    test's clothes. Expressing "core inflation is rising" needs a year-over-year transform, which
    needs a macro value to be an *argument to an indicator* (`sma(macro(CPILFESL), 12)`), which this
    change deliberately does not build -- the indicator registry operates on the OHLCV frame and
    wiring a differently-sampled series into it is a second engine change. They are reachable here
    because excluding a series from the enum on grounds of how a rule *might misuse* it would be a
    stranger rule than documenting the trap; `ROUND-21-PLAN.md` §3 is why the round itself gates on
    `T10Y2Y` instead.
    """

    DGS10 = "DGS10"
    """10-year Treasury constant maturity yield, percent. Daily."""
    T10Y2Y = "T10Y2Y"
    """10-year minus 2-year Treasury spread, percentage points. Daily, and may be negative -- the
    one candidate that is a *spread* rather than a trending level, which is why `ROUND-21-PLAN.md`
    gates on it: `> 0` is a threshold set by the concept (the curve is or is not inverted) rather
    than a fitted parameter."""
    T10YIE = "T10YIE"
    """10-year breakeven inflation rate, percent. Daily."""
    DCOILWTICO = "DCOILWTICO"
    """WTI crude spot, USD/barrel. Daily."""
    PCEPI = "PCEPI"
    """PCE price index, level. Monthly -- see the class docstring on stationarity."""
    PCEPILFE = "PCEPILFE"
    """Core PCE price index (ex food and energy), level. Monthly."""
    CPILFESL = "CPILFESL"
    """Core CPI (ex food and energy), level. Monthly."""


class ArithOp(StrEnum):
    ADD = "+"
    SUB = "-"
    MUL = "*"
    DIV = "/"


class CompareOp(StrEnum):
    LT = "<"
    LTE = "<="
    GT = ">"
    GTE = ">="
    EQ = "=="
    NEQ = "!="


class CrossDir(StrEnum):
    """Direction of a crossing.

    A cross is an *edge*, not a level: it is true only on the bar where the relationship changed.
    ``a crosses_above b`` means ``a`` was at or below ``b`` on the previous bar and is strictly
    above it on this one. Expressing that as ``a > b`` instead would be true for every bar of a long
    trend, turning "the moment it crossed" into "the whole time it was above" -- a hit-rate
    denominator inflated by hundreds of duplicate triggers of the same single event.
    """

    ABOVE = "crosses_above"
    BELOW = "crosses_below"


class BoolOpKind(StrEnum):
    AND = "and"
    OR = "or"


# ---------------------------------------------------------------------------
# Numeric expressions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Literal:
    """A bare number: the ``30`` in ``rsi(14) < 30``."""

    value: float


@dataclass(frozen=True, slots=True)
class PriceRef:
    """A raw bar column: the ``close`` in ``close < bb_lower(20,2)``."""

    field: PriceField


@dataclass(frozen=True, slots=True)
class IndicatorRef:
    """One indicator output, as written in the rule text.

    ``name`` is the registry token (``rsi``, ``bb``) and ``output`` names the column for a
    multi-output indicator (``bb_lower(20,2)`` parses to ``name="bb", output="lower"``). A
    single-output indicator carries ``output=None``.

    ``args`` are positional, matching the order in the registry's
    :class:`~app.indicators.base.ParamSpec` list. They are *not* validated here -- range checking,
    arity and cross-parameter rules (``fast < slow``) belong to the registry, which already owns
    them, and duplicating that logic here would let the two drift.

    An argument is a ``float`` or a ``str``. The string case is not a convenience: the registry has
    a :attr:`~app.indicators.base.ParamKind.CHOICE_OR_DATE` parameter kind, and ``vwap``'s ``anchor``
    uses it -- the value is either the token ``session`` or an ISO date pinning the anchor to a
    specific bar, which is what makes post-bottom VWAP analysis expressible. A float-only tuple
    cannot hold either, so ``vwap(session)`` and ``vwap(2026-01-15)`` would have no representation
    and the rule DSL could not reach a shipped indicator's only parameter. Strings are passed
    through to the spec text verbatim; the registry does the coercion, as it does for every other
    parameter kind.

    This node is resolved into an
    :class:`~app.indicators.base.IndicatorRequest` by asking the registry, never by formatting a
    column name and hoping it matches. The column name is an *output* of
    :func:`~app.indicators.base.column_name`, so deriving it any other way couples this package to
    that function's number formatting forever.
    """

    name: str
    args: tuple[float | str, ...] = ()
    output: str | None = None


@dataclass(frozen=True, slots=True)
class MacroRef:
    """One FRED series, read as of the decision bar: the ``macro(T10Y2Y)`` in ``macro(T10Y2Y) > 0``.

    **Resolved against a release-lagged join, never against the bar frame the evaluator carries.** A
    macro series has one row per FRED observation date, not one per trading session, and the two are
    joined explicitly -- once per card, before evaluation -- by
    :func:`app.rules.macro_binding.bind_macro`. This node is only the name; it holds no value and no
    date logic, so there is exactly one place the causality rule can be got wrong rather than one per
    node.

    **Why the join cannot reuse the dashboard's.** FRED serves the *revised* value against the
    *reference* date, so reading a monthly index at its own period date is reading a number published
    weeks later -- the same shape of lookahead `strategy-program/CONSTRAINTS.md` describes for 13F
    filings, where the guard passed all three offending cards because it checks whether an indicator
    is causal on symbols already chosen, not when the information became knowable.
    :func:`app.market.macro._nearest_on_or_before` selects on ``point.date <= target``, the reference
    date; that is correct for a dashboard reader asking what a series printed through a date, and
    exactly wrong for a rule. See :mod:`app.rules.macro_binding`.
    """

    field: MacroField


@dataclass(frozen=True, slots=True)
class Arith:
    """Arithmetic over numeric expressions: ``close * 1.05``, ``bb_upper(20,2) - bb_lower(20,2)``."""

    left: NumExpr
    op: ArithOp
    right: NumExpr


type NumExpr = Literal | PriceRef | IndicatorRef | MacroRef | Arith


# ---------------------------------------------------------------------------
# Boolean expressions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Comparison:
    """A level test: ``rsi(14) < 30``."""

    left: NumExpr
    op: CompareOp
    right: NumExpr


@dataclass(frozen=True, slots=True)
class Cross:
    """An edge test: ``ema(12) crosses_above ema(26)``. See :class:`CrossDir`."""

    left: NumExpr
    direction: CrossDir
    right: NumExpr


@dataclass(frozen=True, slots=True)
class Not:
    operand: BoolExpr


@dataclass(frozen=True, slots=True)
class BoolOp:
    """``and`` / ``or`` over two or more operands.

    N-ary rather than binary so ``a and b and c`` is one node with three operands instead of a
    left-leaning chain -- it renders back to text in the shape the user wrote it, and the evaluator
    can reduce it in one pass.
    """

    op: BoolOpKind
    operands: tuple[BoolExpr, ...]


type BoolExpr = Comparison | Cross | Not | BoolOp

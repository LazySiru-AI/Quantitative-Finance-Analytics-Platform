"""The rule-expression parser: DSL text in, :mod:`app.rules.nodes` AST out, and back.

**Why a hand-written parser and not ``eval``.** A rule is user input that gets stored (see
:attr:`app.rules.models.Rule.expression`) and replayed against every future bar. Handing that
string to Python's interpreter -- ``eval``, ``exec``, ``ast.literal_eval`` (which still walks a full
Python-syntax AST and has had its own escapes), or ``compile`` -- would put whatever the user typed
in a rule editor in the same execution context as the process holding the brokerage ledger. This
module never imports any of those four names; :func:`test_no_eval_or_exec_in_source` in the test
suite greps this file's own source for them so that guard survives a future refactor rather than
relying on a reviewer noticing a newly added call to one of those names in a diff. The grammar is
closed instead: a fixed
token set, a fixed operator table, and indicator names resolved against
:func:`app.indicators.registry.get` -- never against a Python namespace, ``getattr``, or anything
else that could reach outside this file's own tables.

**Grammar (EBNF), loosest binding to tightest** -- this order is what makes
``close < bb_lower(20,2) and rsi(14) < 30`` mean "the AND of two comparisons" rather than something
stranger::

    rule        := or_expr EOF          (* parse()         -- must yield a BoolExpr *)
    ranking     := or_expr EOF          (* parse_ranking() -- must yield a NumExpr  *)
    or_expr     := and_expr ("or" and_expr)*
    and_expr    := not_expr ("and" not_expr)*
    not_expr    := "not" not_expr | comparison
    comparison  := arith [ (compare_op | cross_op) arith ]
    compare_op  := "<" | "<=" | ">" | ">=" | "==" | "!="
    cross_op    := "crosses_above" | "crosses_below"
    arith       := term (("+" | "-") term)*
    term        := unary (("*" | "/") unary)*
    unary       := "-" unary | primary
    primary     := NUMBER
                 | price_field
                 | macro_field
                 | IDENT "(" [ arg ("," arg)* ] ")"
                 | "(" or_expr ")"
    arg         := "-"? NUMBER
    price_field := "open" | "high" | "low" | "close" | "volume"
    macro_field := "macro" "(" MACRO_ID ")"

A comparison is deliberately non-chainable: ``comparison`` consumes at most one ``compare_op`` or
``cross_op``, so ``1 < rsi(14) < 2`` is a parse error (see :meth:`_Parser._reject_chained_comparison`)
rather than being read as ``1 < rsi(14) and rsi(14) < 2``, which is what a chained reading would
silently mean and is not what the grammar promises.

**Two entry points over one grammar, differing only in what they demand at the top.** :func:`parse`
requires the whole expression to be a condition; :func:`parse_ranking` requires it to be a number.
Everything between the two -- the tokenizer, the operator table, the indicator lookup, the depth
bound -- is shared, so a ranking key (`app.tournament.models.StrategyCard.rank_by`, the engine's one
cross-sectional step: which of several qualifying symbols takes a scarce slot) is written in exactly
the language an analyst already writes rules in, and no second parser has to be trusted with a stored
user string. `close / sma(200)` is the same tree either way; only the expectation at the root differs.

**Two expression kinds, enforced at every join, not just at the top.** :data:`~app.rules.nodes.NumExpr`
and :data:`~app.rules.nodes.BoolExpr` are different types in ``nodes.py`` precisely so a number
cannot stand in for a condition (see that module's docstring). This parser is where that boundary is
actually drawn: every place two subtrees are combined --  ``Arith``, ``Comparison``/``Cross``,
``Not``, ``BoolOp`` -- runs the combined operands through :func:`_expect_num` or :func:`_expect_bool`
first, so ``rsi(14) and close`` fails at the ``and`` (a ``NumExpr`` where a ``BoolExpr`` was
required), and a bare ``close`` fails at the top level the same way (see :func:`parse`). Parentheses
are polymorphic on purpose -- ``primary``'s ``"(" or_expr ")"`` branch parses a full expression of
*either* kind and returns it unchanged, which is what lets ``not (rsi(14) > 70)`` and ``(a + b) * c``
share one grouping rule instead of two.

**Depth is bounded explicitly, not left to Python's own recursion limit.** ``"(" or_expr ")"``, a
leading ``"-"`` and a leading ``"not"`` are the only three genuinely recursive productions here (every
chain of the same operator -- ``and``, ``or``, ``+``, ``*`` -- is parsed by an iterative loop, not by
recursing into itself, precisely so a long flat expression like fifty ``and``-ed comparisons costs
one stack frame per *level*, not per operand). Each of those three productions still walks all eight
parser methods per nesting level, so an *unguarded* few hundred levels of ``((((...))))`` would blow
past Python's default recursion limit and surface as ``RecursionError`` -- an implementation detail
leaking out as an unhandled 500, not a rule the user typed being told "no". :attr:`_Parser._MAX_DEPTH`
catches this explicitly, well under that ceiling, and turns it into the same :class:`RuleSyntaxError`
every other malformed rule produces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, assert_never

from app.indicators.registry import catalog as _indicator_catalog
from app.indicators.registry import get as _get_indicator_spec

if TYPE_CHECKING:
    from app.indicators.base import IndicatorSpec
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
    MacroField,
    MacroRef,
    Not,
    NumExpr,
    PriceField,
    PriceRef,
)

__all__ = ["RuleSyntaxError", "indicator_refs", "parse", "parse_ranking", "render"]


class RuleSyntaxError(ValueError):
    """A rule that does not parse.

    ``position`` is the 0-based character offset in the original expression where the problem was
    detected -- the start of the offending token, or the end of the string for "expected more input"
    errors. ``None`` only if a message is raised with no token context at all, which nothing in this
    module currently does; the attribute is optional so a caller checking for it doesn't have to
    special-case a hypothetical future raise site that lacks one.
    """

    def __init__(self, message: str, position: int | None = None) -> None:
        super().__init__(message)
        self.position = position


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str
    text: str
    pos: int


#: Longest-match-first within each row that could otherwise collide (`<=` before `<`, `==`/`!=`
#: before nothing shorter exists to collide with them since bare `=` and `!` are not tokens at all --
#: an input containing either falls through to "unexpected character").
_TOKEN_SPEC: tuple[tuple[str, str], ...] = (
    ("WS", r"[ \t\r\n]+"),
    # DATE must precede NUMBER: alternation takes the first match, and without this an ISO date
    # lexes as three arithmetic terms (`2026 - 01 - 15`), which then evaluates to 2010. It exists
    # for `CHOICE_OR_DATE` parameters -- `vwap(2026-01-15)` anchors the VWAP to a specific session.
    #
    # This does make `1000-01-01` a date rather than the subtraction it could theoretically be. That
    # is accepted deliberately: the collision needs two-digit zero-padded operands, which nobody
    # writes when they mean arithmetic, and a date is only *meaningful* in argument position -- see
    # `_parse_primary`, which rejects a DATE used as a value with an explanation rather than letting
    # it leak into a comparison.
    ("DATE", r"\d{4}-\d{2}-\d{2}"),
    ("NUMBER", r"\d+(?:\.\d+)?"),
    ("IDENT", r"[A-Za-z_][A-Za-z0-9_]*"),
    ("LE", r"<="),
    ("GE", r">="),
    ("EQEQ", r"=="),
    ("NEQ", r"!="),
    ("LT", r"<"),
    ("GT", r">"),
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
    ("COMMA", r","),
    ("PLUS", r"\+"),
    ("MINUS", r"-"),
    ("STAR", r"\*"),
    ("SLASH", r"/"),
)
_MASTER_RE = re.compile("|".join(f"(?P<{name}>{pattern})" for name, pattern in _TOKEN_SPEC))

#: Reserved words carved out of the generic IDENT pattern. Case-insensitive (matched on the lowered
#: token text) so `AND`/`And`/`and` all read the same way a rule author would expect, matching
#: `app.indicators.registry.get`'s own case-insensitive lookup rather than introducing a second,
#: stricter convention just for keywords.
#: The identifier that introduces a macro series reference: ``macro(T10Y2Y)``. Held as a
#: constant rather than written inline so the parser and any future renderer agree on one
#: spelling. Deliberately **not** in :data:`_KEYWORDS` -- see :meth:`_Parser._parse_macro_call`.
_MACRO_IDENT = "macro"


_KEYWORDS: dict[str, str] = {
    "and": "AND",
    "or": "OR",
    "not": "NOT",
    "crosses_above": "CROSSES_ABOVE",
    "crosses_below": "CROSSES_BELOW",
}

_COMPARE_OPS: dict[str, CompareOp] = {
    "LT": CompareOp.LT,
    "LE": CompareOp.LTE,
    "GT": CompareOp.GT,
    "GE": CompareOp.GTE,
    "EQEQ": CompareOp.EQ,
    "NEQ": CompareOp.NEQ,
}
_CROSS_OPS: dict[str, CrossDir] = {
    "CROSSES_ABOVE": CrossDir.ABOVE,
    "CROSSES_BELOW": CrossDir.BELOW,
}


def _tokenize(text: str) -> list[_Token]:
    """Scan ``text`` into tokens, or raise :class:`RuleSyntaxError` at the first character that
    matches nothing -- null bytes, unicode outside the ASCII identifier/operator set, stray
    punctuation. Scanning position-by-position with `.match(text, pos)` rather than `finditer`
    guarantees every character is accounted for: `finditer` would silently skip a byte that matches
    none of the alternatives instead of surfacing it.
    """
    tokens: list[_Token] = []
    pos = 0
    length = len(text)
    while pos < length:
        match = _MASTER_RE.match(text, pos)
        if match is None:
            raise RuleSyntaxError(f"unexpected character {text[pos]!r}", position=pos)
        kind = match.lastgroup
        assert kind is not None  # every alternative in _MASTER_RE is a named group
        if kind != "WS":
            if kind == "IDENT":
                kind = _KEYWORDS.get(match.group().lower(), "IDENT")
            tokens.append(_Token(kind=kind, text=match.group(), pos=pos))
        pos = match.end()
    tokens.append(_Token(kind="EOF", text="", pos=length))
    return tokens


def _describe(token: _Token) -> str:
    return "end of input" if token.kind == "EOF" else repr(token.text)


# ---------------------------------------------------------------------------
# Type-boundary helpers -- see the module docstring's "Two expression kinds" section
# ---------------------------------------------------------------------------


def _expect_num(node: NumExpr | BoolExpr, pos: int, context: str) -> NumExpr:
    match node:
        case Literal() | PriceRef() | MacroRef() | IndicatorRef() | Arith():
            return node
        case Comparison() | Cross() | Not() | BoolOp():
            raise RuleSyntaxError(
                f"expected a numeric expression for {context}, found a boolean expression",
                position=pos,
            )
        case _:
            assert_never(node)


def _expect_bool(node: NumExpr | BoolExpr, pos: int, context: str) -> BoolExpr:
    match node:
        case Comparison() | Cross() | Not() | BoolOp():
            return node
        case Literal() | PriceRef() | MacroRef() | IndicatorRef() | Arith():
            raise RuleSyntaxError(
                f"expected a boolean expression for {context}, found a numeric expression",
                position=pos,
            )
        case _:
            assert_never(node)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class _Parser:
    """Recursive-descent over the grammar in the module docstring.

    One instance per call to :func:`parse`; not reused, not thread-shared.
    """

    #: See the module docstring's "Depth is bounded explicitly" section. `100` levels of nesting
    #: through the 8-method chain (or_expr..primary) costs on the order of 800 Python stack frames,
    #: comfortably under the interpreter's default recursion limit (1000) with room left for
    #: pytest's/uvicorn's own frames beneath us -- while still rejecting anything a real rule author
    #: would write (nobody hand-types 100 levels of parentheses) long before the pathological cases
    #: this exists for (hundreds of levels) get anywhere near a stack overflow.
    _MAX_DEPTH = 100

    def __init__(self, tokens: list[_Token]) -> None:
        self._tokens = tokens
        self._i = 0
        self._depth = 0

    def _peek(self) -> _Token:
        return self._tokens[self._i]

    def _advance(self) -> _Token:
        token = self._tokens[self._i]
        if token.kind != "EOF":
            self._i += 1
        return token

    def _expect(self, kind: str, what: str) -> _Token:
        token = self._peek()
        if token.kind != kind:
            raise RuleSyntaxError(f"expected {what}, found {_describe(token)}", position=token.pos)
        return self._advance()

    def _enter(self, pos: int) -> None:
        self._depth += 1
        if self._depth > self._MAX_DEPTH:
            raise RuleSyntaxError("expression nested too deeply", position=pos)

    def _exit(self) -> None:
        self._depth -= 1

    # -- entry point ---------------------------------------------------

    def parse_rule(self) -> BoolExpr:
        start_pos = self._peek().pos
        node = self.parse_or()
        trailing = self._peek()
        if trailing.kind != "EOF":
            raise RuleSyntaxError(f"unexpected {_describe(trailing)}", position=trailing.pos)
        return _expect_bool(node, start_pos, "a rule")

    def parse_ranking(self) -> NumExpr:
        """Same grammar, opposite expectation at the top: a number, not a condition.

        `parse_or` is still the entry production rather than `parse_arith`, so that a ranking key
        gets the identical parse tree a rule's operand would -- and so that `close > sma(50)`,
        handed here by mistake, is reported as "a ranking key must be a number" by
        :func:`_expect_num` rather than as a syntax error blaming the `>`.
        """
        start_pos = self._peek().pos
        node = self.parse_or()
        trailing = self._peek()
        if trailing.kind != "EOF":
            raise RuleSyntaxError(f"unexpected {_describe(trailing)}", position=trailing.pos)
        return _expect_num(node, start_pos, "a ranking key")

    # -- or / and: n-ary, left-collected by an iterative loop ----------
    #
    # `a and b and c` must come out as one `BoolOp` with three operands (see `nodes.py`'s `BoolOp`
    # docstring), not a left-leaning chain of binary nodes -- so operands are collected into a list
    # and only wrapped in `BoolOp` once, after the loop, rather than combined pairwise on each
    # iteration the way `arith`/`term` below combine `Arith` nodes.

    def parse_or(self) -> NumExpr | BoolExpr:
        pos = self._peek().pos
        items: list[tuple[int, NumExpr | BoolExpr]] = [(pos, self.parse_and())]
        while self._peek().kind == "OR":
            self._advance()
            pos = self._peek().pos
            items.append((pos, self.parse_and()))
        if len(items) == 1:
            return items[0][1]
        operands = tuple(_expect_bool(node, p, "'or'") for p, node in items)
        return BoolOp(op=BoolOpKind.OR, operands=operands)

    def parse_and(self) -> NumExpr | BoolExpr:
        pos = self._peek().pos
        items: list[tuple[int, NumExpr | BoolExpr]] = [(pos, self.parse_not())]
        while self._peek().kind == "AND":
            self._advance()
            pos = self._peek().pos
            items.append((pos, self.parse_not()))
        if len(items) == 1:
            return items[0][1]
        operands = tuple(_expect_bool(node, p, "'and'") for p, node in items)
        return BoolOp(op=BoolOpKind.AND, operands=operands)

    def parse_not(self) -> NumExpr | BoolExpr:
        token = self._peek()
        if token.kind == "NOT":
            self._advance()
            self._enter(token.pos)
            try:
                operand = self.parse_not()
            finally:
                self._exit()
            return Not(operand=_expect_bool(operand, token.pos, "'not'"))
        return self.parse_comparison()

    # -- comparison / cross: exactly zero or one, never chained --------

    def parse_comparison(self) -> NumExpr | BoolExpr:
        left_pos = self._peek().pos
        left = self.parse_arith()
        token = self._peek()
        if token.kind in _COMPARE_OPS:
            self._advance()
            right_pos = self._peek().pos
            right = self.parse_arith()
            self._reject_chained_comparison()
            return Comparison(
                left=_expect_num(left, left_pos, "comparison"),
                op=_COMPARE_OPS[token.kind],
                right=_expect_num(right, right_pos, "comparison"),
            )
        if token.kind in _CROSS_OPS:
            self._advance()
            right_pos = self._peek().pos
            right = self.parse_arith()
            self._reject_chained_comparison()
            return Cross(
                left=_expect_num(left, left_pos, "cross"),
                direction=_CROSS_OPS[token.kind],
                right=_expect_num(right, right_pos, "cross"),
            )
        return left

    def _reject_chained_comparison(self) -> None:
        token = self._peek()
        if token.kind in _COMPARE_OPS or token.kind in _CROSS_OPS:
            raise RuleSyntaxError(
                "comparisons cannot be chained -- join two comparisons with 'and'",
                position=token.pos,
            )

    # -- arithmetic: left-associative, folded iteratively ---------------

    def parse_arith(self) -> NumExpr | BoolExpr:
        left_pos = self._peek().pos
        left = self.parse_term()
        while self._peek().kind in ("PLUS", "MINUS"):
            op_token = self._advance()
            right_pos = self._peek().pos
            right = self.parse_term()
            left = Arith(
                left=_expect_num(left, left_pos, "arithmetic"),
                op=ArithOp.ADD if op_token.kind == "PLUS" else ArithOp.SUB,
                right=_expect_num(right, right_pos, "arithmetic"),
            )
            left_pos = op_token.pos
        return left

    def parse_term(self) -> NumExpr | BoolExpr:
        left_pos = self._peek().pos
        left = self.parse_unary()
        while self._peek().kind in ("STAR", "SLASH"):
            op_token = self._advance()
            right_pos = self._peek().pos
            right = self.parse_unary()
            left = Arith(
                left=_expect_num(left, left_pos, "arithmetic"),
                op=ArithOp.MUL if op_token.kind == "STAR" else ArithOp.DIV,
                right=_expect_num(right, right_pos, "arithmetic"),
            )
            left_pos = op_token.pos
        return left

    def parse_unary(self) -> NumExpr | BoolExpr:
        token = self._peek()
        if token.kind == "MINUS":
            self._advance()
            self._enter(token.pos)
            try:
                operand = self.parse_unary()
            finally:
                self._exit()
            num_operand = _expect_num(operand, token.pos, "unary '-'")
            # `nodes.py` has no unary-negation node: a literal folds its sign directly into the
            # `Literal` (so `-5` renders back to `-5`, not `0 - 5`); anything else becomes `0 - x`,
            # which is the only way this grammar can express "negate a non-constant" with the AST
            # as given. Chained signs (`--5`) fold correctly either way since each level negates
            # whatever its single recursive call already produced.
            if isinstance(num_operand, Literal):
                return Literal(value=-num_operand.value)
            return Arith(left=Literal(value=0.0), op=ArithOp.SUB, right=num_operand)
        return self.parse_primary()

    # -- atoms ------------------------------------------------------------

    def parse_primary(self) -> NumExpr | BoolExpr:
        token = self._peek()
        if token.kind == "NUMBER":
            self._advance()
            return Literal(value=float(token.text))
        if token.kind == "LPAREN":
            self._advance()
            self._enter(token.pos)
            try:
                inner = self.parse_or()
            finally:
                self._exit()
            self._expect("RPAREN", "')'")
            return inner
        if token.kind == "IDENT":
            self._advance()
            if self._peek().kind == "LPAREN":
                # `macro` is intercepted before the indicator path rather than registered as an
                # indicator, because it is not one: an indicator is computed from the bar frame by
                # `app.indicators.registry`, and a macro series is looked up in a separately-sampled,
                # release-lagged frame (`app.rules.macro_binding`). Routing it through
                # `_parse_indicator_call` would ask the registry to resolve a name it must not own,
                # and would parse `T10Y2Y` as a numeric argument. Not a keyword either: adding
                # `macro` to `_KEYWORDS` would make it unusable as an identifier everywhere,
                # including as a future indicator or price field name, for no gain here.
                if token.text.lower() == _MACRO_IDENT:
                    return self._parse_macro_call(token)
                return self._parse_indicator_call(token)
            return self._resolve_price_field(token)
        raise RuleSyntaxError(f"expected a value, found {_describe(token)}", position=token.pos)

    def _parse_macro_call(self, name_token: _Token) -> MacroRef:
        """``macro(T10Y2Y)`` -> :class:`MacroRef`. Exactly one bare identifier, no arithmetic.

        The argument is deliberately not an ``arg`` in the grammar sense: a macro field is a name,
        not a parameter, and allowing ``macro(2)`` or ``macro(DGS10 + 1)`` would invite a reading
        where the series is selected at evaluation time. It is selected at parse time, which is what
        lets the guard enumerate every series a card can reach by walking the tree
        (``app.backtest.guards.required_macro_refs``) rather than by running it.
        """
        self._expect("LPAREN", "'('")
        token = self._peek()
        if token.kind not in ("IDENT", "KEYWORD"):
            raise RuleSyntaxError(
                f"macro() takes a series name, found {_describe(token)}", position=token.pos
            )
        self._advance()
        try:
            field = MacroField(token.text.upper())
        except ValueError:
            known = ", ".join(f.value for f in MacroField)
            raise RuleSyntaxError(
                f"unknown macro series {token.text!r}; known series are {known}",
                position=token.pos,
            ) from None
        self._expect("RPAREN", "')'")
        return MacroRef(field=field)

    def _resolve_price_field(self, token: _Token) -> PriceRef:
        try:
            field = PriceField(token.text.lower())
        except ValueError:
            raise RuleSyntaxError(
                _unknown_identifier_message(token.text), position=token.pos
            ) from None
        return PriceRef(field=field)

    def _parse_indicator_call(self, name_token: _Token) -> IndicatorRef:
        self._expect("LPAREN", "'('")
        args: list[float | str] = []
        if self._peek().kind != "RPAREN":
            while True:
                args.append(self._parse_indicator_arg(name_token))
                if self._peek().kind == "COMMA":
                    self._advance()
                    continue
                break
        self._expect("RPAREN", "')'")
        name, output = _resolve_indicator_ident(name_token.text, name_token.pos)
        return IndicatorRef(name=name, args=tuple(args), output=output)

    def _parse_indicator_arg(self, name_token: _Token) -> float | str:
        """One positional argument: an optionally-signed number, a bare token, or an ISO date.

        Arity, ranges and cross-parameter rules (`fast < slow`) are the registry's job, not this
        parser's -- see `IndicatorRef`'s docstring in `nodes.py`. Strings are passed through
        verbatim for the registry to coerce, which is what lets a `CHOICE_OR_DATE` parameter work:
        `vwap(session)` and `vwap(2026-01-15)` both reach `ParamSpec.coerce` as the text the user
        typed, and it decides whether the value is a valid choice or a valid date. Validating that
        here would duplicate the registry's own rules and let the two drift.

        A negative sign is only meaningful on a number; `-session` is rejected rather than silently
        dropped, since a caller who wrote it meant something this grammar cannot express.
        """
        token = self._peek()
        negative = False
        if token.kind == "MINUS":
            negative = True
            self._advance()
            token = self._peek()

        if token.kind == "NUMBER":
            self._advance()
            value = float(token.text)
            return -value if negative else value

        if token.kind in ("IDENT", "DATE") and not negative:
            self._advance()
            return token.text

        if negative:
            raise RuleSyntaxError(
                f"{name_token.text}: '-' may only negate a number, but {_describe(token)} follows it",
                position=token.pos,
            )
        raise RuleSyntaxError(
            f"{name_token.text}: argument {_describe(token)} is not a number, a token or an "
            "ISO date (YYYY-MM-DD)",
            position=token.pos,
        )


#: Split point for `bb_lower` -> `IndicatorRef(name="bb", output="lower")`. Resolution tries the
#: identifier whole *first* -- so a hypothetical indicator literally named `macd_hist` would resolve
#: as itself rather than being torn into `macd` + `hist` -- and only falls back to peeling a suffix
#: off the *last* underscore if no indicator is registered under the whole identifier. Splitting at
#: the last underscore (`rpartition`, not `partition`) rather than the first keeps a hypothetical
#: multi-word indicator name (e.g. a future `linear_reg`) intact as the prefix, since every output
#: suffix in the current registry (`upper`, `mid`, `lower`, `macd`, `signal`, `hist`) is itself a
#: single word with no embedded underscore to worry about instead.
#: `sma20`, `rsi14`, `ema200` -- an indicator name with its parameter glued on. The single most
#: natural thing to type, and until this existed the single most misleading thing to type: the
#: rejection named the five OHLCV fields and nothing else, so a reader concluded the engine had no
#: indicators at all. A UAT persona did exactly that, called the backtest workbench "a deal-breaker
#: for a momentum trader", and abandoned the analysis -- against an engine that supports every
#: indicator it wanted, spelled `sma(20)`.
_GLUED_PARAM_RE: Final = re.compile(r"^([a-z_]+?)(\d+(?:\.\d+)?)$", re.IGNORECASE)


def _indicator_names() -> list[str]:
    """Registered indicator tokens. Read through the registry rather than cached, so a newly
    registered indicator appears in the error text without a restart."""
    return [spec.name for spec in _indicator_catalog()]


def _call_hint(spec: IndicatorSpec, *, argument: str | None = None) -> str:
    """A concrete, paste-able call for ``spec`` -- ``sma(20)``, not ``sma(...)``.

    Uses the caller's own number when they supplied one, otherwise the spec's defaults, so the hint
    is always something that would actually parse rather than a shape to be decoded.
    """
    if argument is not None:
        return f"{spec.name}({argument})"
    if not spec.params:
        return f"{spec.name}()"
    return f"{spec.name}({', '.join(str(p.default) for p in spec.params)})"


def _unknown_identifier_message(text: str) -> str:
    """Explain a bare identifier that is not a price field.

    Ordered most-specific first, because a generic "valid fields are ..." list is what caused the
    misreading this function exists to prevent: it is *true* and it silently implies that the five
    price fields are the whole vocabulary. Every branch below either names the exact call the user
    meant, or -- failing that -- says outright that indicators exist and lists them.
    """
    lowered = text.lower()

    exact = _get_indicator_spec(lowered)
    if exact is not None:
        return (
            f"indicator {text!r} must be called with parentheses, e.g. {_call_hint(exact)}"
        )

    glued = _GLUED_PARAM_RE.match(lowered)
    if glued is not None:
        stem, argument = glued.group(1), glued.group(2)
        spec = _get_indicator_spec(stem.rstrip("_"))
        if spec is not None:
            return (
                f"unknown price field {text!r} -- did you mean {_call_hint(spec, argument=argument)}? "
                f"Indicators take their parameters in parentheses, not glued to the name"
            )

    # `bb_lower`, `macd_signal`: a real output of a real indicator, still needing a call.
    if "_" in lowered:
        prefix, _, suffix = lowered.rpartition("_")
        spec = _get_indicator_spec(prefix)
        if spec is not None and suffix in spec.outputs:
            return (
                f"{text!r} is the {suffix!r} output of {prefix!r} and must be called with "
                f"parentheses, e.g. {_call_hint(spec).replace(spec.name, lowered, 1)}"
            )

    # Keeps the original "unknown price field" opening -- an identifier that reached this branch was
    # most likely a reach for a price field (`adj_close` is a real column on a Bar, just not one the
    # rule DSL exposes) -- and appends what the original message left out: that indicators exist at
    # all, and how they are spelled.
    fields = ", ".join(f.value for f in PriceField)
    indicators = ", ".join(sorted(_indicator_names()))
    return (
        f"unknown price field {text!r} -- valid price fields are {fields}; indicators are called "
        f"with parentheses, e.g. sma(20), and the registered ones are {indicators}"
    )


def _resolve_indicator_ident(ident: str, pos: int) -> tuple[str, str | None]:
    spec = _get_indicator_spec(ident)
    if spec is not None:
        return spec.name, None
    if "_" in ident:
        prefix, _, suffix = ident.rpartition("_")
        prefix_spec = _get_indicator_spec(prefix)
        if prefix_spec is not None and suffix in prefix_spec.outputs:
            return prefix_spec.name, suffix
    raise RuleSyntaxError(f"unknown indicator {ident!r}", position=pos)


def parse(expression: str) -> BoolExpr:
    """Parse rule text into a :data:`~app.rules.nodes.BoolExpr`.

    Raises :class:`RuleSyntaxError` for anything that doesn't parse, including an expression that
    parses cleanly but evaluates to a :data:`~app.rules.nodes.NumExpr` -- ``"close"`` alone is
    syntactically fine as a numeric expression and still not a rule, since a rule is a condition, not
    a series (see the module docstring on `nodes.py`).
    """
    tokens = _tokenize(expression)
    return _Parser(tokens).parse_rule()


def parse_ranking(expression: str) -> NumExpr:
    """Parse ranking-key text into a :data:`~app.rules.nodes.NumExpr`.

    The counterpart to :func:`parse` for the one place this project compares symbols *to each other*
    rather than to a constant: `app.tournament.runner`'s entry loop, which must choose which of the
    qualifying names take the scarce slots. A ranking key is deliberately the *same* grammar a rule's
    operands already use -- `close / sma(200)`, `rsi(14)`, `(close - sma(50)) / atr(14)` -- so that
    "the strongest name" is expressed with the tokens, indicators and precedence an analyst already
    knows, and so that nothing new has to be trusted with a stored user string. In particular there
    is still no `eval` reachable from here: this shares `_Parser` and its closed indicator table
    with :func:`parse` exactly.

    Raises :class:`RuleSyntaxError` for anything that does not parse, **including a well-formed
    condition** -- `close > sma(50)` is a fine rule and is not a ranking key, for the mirror-image
    reason `close` alone is not a rule.
    """
    tokens = _tokenize(expression)
    return _Parser(tokens).parse_ranking()


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

#: Node types that must be wrapped in parentheses when they appear as a child of another node --
#: everything with internal operator structure that a neighboring operator could otherwise bind
#: through. `Literal`, `PriceRef` and `IndicatorRef` never need it: none of the three has a lower-
#: precedence operator inside it for anything outside to collide with.
_COMPOUND_TYPES = (Arith, Comparison, Cross, Not, BoolOp)


def _fmt_number(value: float) -> str:
    """No trailing `.0` on whole floats, matching the convention already used for column names and
    spec strings in `app.indicators.base._fmt` / `app.indicators.registry._fmt_default` -- and,
    unlike those, load-bearing here for a different reason: `str(value)` on a float that Python's
    own float-to-str already round-trips (which is every float `parse()` can produce, since it always
    comes from `float(some_token_text)`) is what makes `render` -> re-`parse` reproduce the exact
    same value, not just an equal-looking one.
    """
    if value.is_integer():
        return str(int(value))
    return str(value)


def _render(node: NumExpr | BoolExpr) -> str:
    def child(n: NumExpr | BoolExpr) -> str:
        text = _render(n)
        return f"({text})" if isinstance(n, _COMPOUND_TYPES) else text

    match node:
        case Literal(value):
            return _fmt_number(value)
        case PriceRef(field):
            return field.value
        case MacroRef(field):
            # Rendered uppercase, matching `MacroField`'s own values and how FRED names its series.
            # `_parse_macro_call` upper-cases before the enum lookup, so `macro(t10y2y)` parses and
            # renders back as `macro(T10Y2Y)` -- normalised, not preserved, exactly as an indicator's
            # arguments are.
            return f"{_MACRO_IDENT}({field.value})"
        case IndicatorRef(name, args, output):
            ident = f"{name}_{output}" if output else name
            # A string argument (a `CHOICE_OR_DATE` token or an ISO date) renders as itself; only
            # numbers go through `_fmt_number`, which strips the `.0` off whole floats so a rendered
            # rule re-parses to the same tree rather than to `rsi(14.0)`.
            rendered = [a if isinstance(a, str) else _fmt_number(a) for a in args]
            return f"{ident}({', '.join(rendered)})"
        case Arith(left, op, right):
            return f"{child(left)} {op.value} {child(right)}"
        case Comparison(left, op, right):
            return f"{child(left)} {op.value} {child(right)}"
        case Cross(left, direction, right):
            return f"{child(left)} {direction.value} {child(right)}"
        case Not(operand):
            return f"not {child(operand)}"
        case BoolOp(op, operands):
            return f" {op.value} ".join(child(o) for o in operands)
        case _:
            assert_never(node)


def render(node: BoolExpr | NumExpr) -> str:
    """Render a tree back to DSL text.

    Not a reproduction of whatever whitespace or parenthesisation the user originally typed --
    only ``parse(render(node)) == node`` is promised (and tested; see
    ``tests/test_rule_grammar.py``). Every compound child is parenthesised unconditionally rather
    than only where precedence would otherwise make it ambiguous, which costs a few redundant
    parens on deeply nested trees in exchange for not having to duplicate this module's precedence
    table a second time in the renderer, where it could quietly drift from the parser's.
    """
    return _render(node)


# ---------------------------------------------------------------------------
# Indicator collection
# ---------------------------------------------------------------------------


def _collect(node: NumExpr | BoolExpr, found: list[IndicatorRef]) -> None:
    match node:
        case IndicatorRef():
            found.append(node)
        # `MacroRef` is a leaf that contributes no `IndicatorRef`, exactly like `PriceRef`: a macro
        # series is bound from the pin by `app.rules.macro_binding`, not computed by an indicator, so
        # there is nothing here for this walk to find. It belongs in this arm rather than being
        # absent -- omitting it does not make the walk skip macro nodes, it makes `assert_never`
        # below raise on every rule that contains one. See `required_macro_fields` for the parallel
        # walk that *does* collect them.
        case Literal() | PriceRef() | MacroRef():
            pass
        case Arith(left, _, right) | Comparison(left, _, right) | Cross(left, _, right):
            _collect(left, found)
            _collect(right, found)
        case Not(operand):
            _collect(operand, found)
        case BoolOp(_, operands):
            for operand in operands:
                _collect(operand, found)
        case _:
            assert_never(node)


def indicator_refs(node: BoolExpr | NumExpr) -> list[IndicatorRef]:
    """Every :class:`~app.rules.nodes.IndicatorRef` in ``node``, in left-to-right occurrence order,
    duplicates included. Walking the tree once here is what lets a caller (the evaluator, fetching
    the indicator columns a rule needs before touching any bars) avoid re-parsing the expression
    just to know what it depends on. Duplicates are not collapsed: `IndicatorRef` is a frozen,
    hashable dataclass, so a caller that wants a unique set can do that in one line
    (``dict.fromkeys(...)`` or ``set(...)``) without this function guessing whether repeats matter
    to it.
    """
    found: list[IndicatorRef] = []
    _collect(node, found)
    return found

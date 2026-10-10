"""Tests for the rule-expression parser (:mod:`app.rules.grammar`).

Adversarial by design, not a happy-path demo: a DSL that is stored and replayed against real money
decisions earns its trust from the inputs it rejects, not the ones it accepts. Three shapes of test
carry that weight here:

* :class:`TestNodeTypeCoverage` / :class:`TestOperators` -- a table-driven (expression -> expected
  tree) sweep hitting every node type in ``nodes.py`` and every operator at least once, so a grammar
  construct silently going unhandled shows up as a missing row rather than an untested gap.
* :class:`TestErrors` -- a table-driven (bad expression -> expected message substring) sweep over the
  mistakes listed in the brief: unbalanced parens, a truncated comparison, a doubled operator, an
  unknown function, the deliberately-excluded ``adj_close`` field, a trailing operator, and both empty
  and whitespace-only input.
* :class:`TestPathologicalInput` -- inputs chosen to break an implementation rather than to describe a
  plausible rule: 10,000 characters, 500 nested parens, null bytes, non-ASCII text, a long run of unary
  minus. Every one of these must raise :class:`~app.rules.grammar.RuleSyntaxError`, never
  ``RecursionError`` or anything else uncaught.

**What this file does not cover:** float literals in scientific notation (``1e10``) and multi-byte
unicode *inside* an identifier are both simply unsupported by the tokenizer (see its ``NUMBER`` and
``IDENT`` patterns) -- deliberate, not an oversight, since no expression in ``app.rules.catalog`` or
the brief's own examples needs either, but worth naming so a future reader doesn't mistake silence for
an untested gap. Whitespace *inside* a rendered expression is likewise untested beyond "the renderer's
own output re-parses" (requirement 3) since the interface promises no particular formatting.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.rules import grammar
from app.rules.evaluate import required_specs
from app.rules.grammar import RuleSyntaxError, indicator_refs, parse, render
from app.rules.nodes import (
    Arith,
    ArithOp,
    BoolOp,
    BoolOpKind,
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

_CLOSE = PriceRef(field=PriceField.CLOSE)
_VOLUME = PriceRef(field=PriceField.VOLUME)


# ---------------------------------------------------------------------------
# Security guard: this module must never gain an eval/exec/compile escape hatch
# ---------------------------------------------------------------------------


def test_no_eval_exec_or_compile_in_grammar_source() -> None:
    """`nodes.py`'s module docstring explains why: a rule is user input that gets stored and
    replayed, so handing it to the interpreter would share an execution context with the rest of the
    app. Grepping the parser's own source (rather than just trusting a review) is the guard that
    survives a future refactor -- see this file's own module docstring.
    """
    source = Path(grammar.__file__).read_text(encoding="utf-8")
    # `(?<!\.)\bcompile\(` deliberately does not flag `re.compile(` (the tokenizer's own, legitimate
    # regex compilation) -- it excludes any call written as `<something>.compile(`, which is exactly
    # the shape a legitimate `re.compile` has and a bare dangerous `compile(...)` call does not.
    assert not re.search(r"(?<!\.)\beval\(", source), f"found a bare eval( call in {grammar.__file__}"
    assert not re.search(r"(?<!\.)\bexec\(", source), f"found a bare exec( call in {grammar.__file__}"
    assert not re.search(
        r"(?<!\.)\bcompile\(", source
    ), f"found a bare compile( call in {grammar.__file__}"
    assert "ast.literal_eval(" not in source, f"found ast.literal_eval( in {grammar.__file__}"


# ---------------------------------------------------------------------------
# Table-driven: expression -> expected tree, one row per node type / operator
# ---------------------------------------------------------------------------


class TestNodeTypeCoverage:
    """Every dataclass in `nodes.py`'s `NumExpr` / `BoolExpr` unions, parsed from real text."""

    def test_literal_int_and_float(self) -> None:
        assert parse("close > 30") == Comparison(_CLOSE, CompareOp.GT, Literal(30.0))
        assert parse("close > 1.05") == Comparison(_CLOSE, CompareOp.GT, Literal(1.05))

    def test_literal_negative(self) -> None:
        assert parse("close > -5") == Comparison(_CLOSE, CompareOp.GT, Literal(-5.0))

    def test_price_ref_every_field(self) -> None:
        for field in PriceField:
            assert parse(f"{field.value} > 0") == Comparison(
                PriceRef(field=field), CompareOp.GT, Literal(0.0)
            )

    def test_indicator_ref_single_output(self) -> None:
        assert parse("rsi(14) < 30") == Comparison(
            IndicatorRef(name="rsi", args=(14.0,), output=None), CompareOp.LT, Literal(30.0)
        )

    def test_indicator_ref_multi_output_suffix(self) -> None:
        assert parse("close < bb_lower(20,2)") == Comparison(
            _CLOSE, CompareOp.LT, IndicatorRef(name="bb", args=(20.0, 2.0), output="lower")
        )

    def test_indicator_ref_zero_args(self) -> None:
        """`vwap()` -- parens required even with no arguments; matches `app.rules.catalog`'s
        `vwap_reclaim` rule, the one real zero-arg call in the codebase."""
        assert parse("close crosses_above vwap()") == Cross(
            _CLOSE, CrossDir.ABOVE, IndicatorRef(name="vwap", args=(), output=None)
        )

    def test_arith_all_four_ops(self) -> None:
        cases = [
            ("close + 1 > 0", ArithOp.ADD),
            ("close - 1 > 0", ArithOp.SUB),
            ("close * 1 > 0", ArithOp.MUL),
            ("close / 1 > 0", ArithOp.DIV),
        ]
        for text, op in cases:
            node = parse(text)
            assert isinstance(node, Comparison)
            assert node.left == Arith(_CLOSE, op, Literal(1.0))

    def test_comparison_all_six_ops(self) -> None:
        cases = [
            ("close < 1", CompareOp.LT),
            ("close <= 1", CompareOp.LTE),
            ("close > 1", CompareOp.GT),
            ("close >= 1", CompareOp.GTE),
            ("close == 1", CompareOp.EQ),
            ("close != 1", CompareOp.NEQ),
        ]
        for text, op in cases:
            assert parse(text) == Comparison(_CLOSE, op, Literal(1.0))

    def test_cross_both_directions(self) -> None:
        assert parse("ema(12) crosses_above ema(26)") == Cross(
            IndicatorRef(name="ema", args=(12.0,), output=None),
            CrossDir.ABOVE,
            IndicatorRef(name="ema", args=(26.0,), output=None),
        )
        assert parse("ema(12) crosses_below ema(26)") == Cross(
            IndicatorRef(name="ema", args=(12.0,), output=None),
            CrossDir.BELOW,
            IndicatorRef(name="ema", args=(26.0,), output=None),
        )

    def test_not(self) -> None:
        assert parse("not (rsi(14) > 70)") == Not(
            Comparison(IndicatorRef(name="rsi", args=(14.0,), output=None), CompareOp.GT, Literal(70.0))
        )

    def test_bool_op_and_or(self) -> None:
        assert parse("close > 1 and close > 2") == BoolOp(
            BoolOpKind.AND,
            (
                Comparison(_CLOSE, CompareOp.GT, Literal(1.0)),
                Comparison(_CLOSE, CompareOp.GT, Literal(2.0)),
            ),
        )
        assert parse("close > 1 or close > 2") == BoolOp(
            BoolOpKind.OR,
            (
                Comparison(_CLOSE, CompareOp.GT, Literal(1.0)),
                Comparison(_CLOSE, CompareOp.GT, Literal(2.0)),
            ),
        )


class TestSuffixResolution:
    """`bb_lower(20,2)` -> `IndicatorRef(name="bb", output="lower")` -- see
    `grammar._resolve_indicator_ident`'s docstring for the longest-match-first rule this exercises.
    """

    def test_every_registered_multi_output_suffix(self) -> None:
        cases = [
            ("bb_upper(20,2)", "bb", "upper"),
            ("bb_mid(20,2)", "bb", "mid"),
            ("bb_lower(20,2)", "bb", "lower"),
            ("macd_macd(12,26,9)", "macd", "macd"),
            ("macd_signal(12,26,9)", "macd", "signal"),
            ("macd_hist(12,26,9)", "macd", "hist"),
        ]
        for text, name, output in cases:
            node = parse(f"{text} > 0")
            assert isinstance(node, Comparison)
            assert node.left == IndicatorRef(
                name=name, args=(20.0, 2.0) if name == "bb" else (12.0, 26.0, 9.0), output=output
            )

    def test_single_output_indicator_has_no_output(self) -> None:
        for text in ("sma(20)", "ema(20)", "rsi(14)", "atr(14)"):
            node = parse(f"{text} > 0")
            assert isinstance(node, Comparison)
            assert isinstance(node.left, IndicatorRef)
            assert node.left.output is None

    def test_whole_identifier_checked_before_any_split(self) -> None:
        """The registry has nothing literally named `sma_20` (an underscore-bearing name would only
        exist hypothetically), so this instead pins the *order* of resolution indirectly: `sma(20)`
        -- no underscore at all -- must resolve as the whole-name path, not by attempting a split
        that would find no `_` and fall through anyway. See `_resolve_indicator_ident`'s docstring
        for the case this order is actually written to protect: a hypothetical indicator registered
        under a name that also happens to look like `<other_name>_<output>`.
        """
        node = parse("sma(20) > 0")
        assert isinstance(node, Comparison)
        assert node.left == IndicatorRef(name="sma", args=(20.0,), output=None)


class TestPrecedenceAndNesting:
    """Precedence bugs produce a tree that still evaluates -- just against the wrong grouping. Every
    case here is checked against the *exact* expected tree shape, not just "parses without error".
    """

    def test_and_binds_tighter_than_or_left(self) -> None:
        """`a or b and c` == `a or (b and c)`."""
        a = Comparison(_CLOSE, CompareOp.GT, Literal(1.0))
        b = Comparison(_CLOSE, CompareOp.GT, Literal(2.0))
        c = Comparison(_CLOSE, CompareOp.GT, Literal(3.0))
        node = parse("close > 1 or close > 2 and close > 3")
        assert node == BoolOp(BoolOpKind.OR, (a, BoolOp(BoolOpKind.AND, (b, c))))

    def test_and_binds_tighter_than_or_right(self) -> None:
        """`a and b or c` == `(a and b) or c`."""
        a = Comparison(_CLOSE, CompareOp.GT, Literal(1.0))
        b = Comparison(_CLOSE, CompareOp.GT, Literal(2.0))
        c = Comparison(_CLOSE, CompareOp.GT, Literal(3.0))
        node = parse("close > 1 and close > 2 or close > 3")
        assert node == BoolOp(BoolOpKind.OR, (BoolOp(BoolOpKind.AND, (a, b)), c))

    def test_and_binds_tighter_than_or_both_sides(self) -> None:
        """`a and b or c and d` == `(a and b) or (c and d)`."""
        a = Comparison(_CLOSE, CompareOp.GT, Literal(1.0))
        b = Comparison(_CLOSE, CompareOp.GT, Literal(2.0))
        c = Comparison(_CLOSE, CompareOp.GT, Literal(3.0))
        d = Comparison(_CLOSE, CompareOp.GT, Literal(4.0))
        node = parse("close > 1 and close > 2 or close > 3 and close > 4")
        assert node == BoolOp(
            BoolOpKind.OR, (BoolOp(BoolOpKind.AND, (a, b)), BoolOp(BoolOpKind.AND, (c, d)))
        )

    def test_not_binds_tighter_than_and(self) -> None:
        """`not a and b` == `(not a) and b`, not `not (a and b)`."""
        a = Comparison(_CLOSE, CompareOp.GT, Literal(1.0))
        b = Comparison(_CLOSE, CompareOp.GT, Literal(2.0))
        node = parse("not close > 1 and close > 2")
        assert node == BoolOp(BoolOpKind.AND, (Not(a), b))

    def test_n_ary_and_is_one_node_not_a_chain(self) -> None:
        """`a and b and c` is one `BoolOp` with three operands -- see `nodes.py`'s `BoolOp`
        docstring for why a left-leaning chain of binary nodes would be wrong here."""
        node = parse("close > 1 and close > 2 and close > 3")
        assert isinstance(node, BoolOp)
        assert node.op is BoolOpKind.AND
        assert len(node.operands) == 3

    def test_n_ary_or_is_one_node_not_a_chain(self) -> None:
        node = parse("close > 1 or close > 2 or close > 3 or close > 4")
        assert isinstance(node, BoolOp)
        assert node.op is BoolOpKind.OR
        assert len(node.operands) == 4

    def test_mul_binds_tighter_than_add(self) -> None:
        """`a + b * c` == `a + (b * c)`."""
        node = parse("close > 1 + 2 * 3")
        assert isinstance(node, Comparison)
        assert node.right == Arith(Literal(1.0), ArithOp.ADD, Arith(Literal(2.0), ArithOp.MUL, Literal(3.0)))

    def test_unary_minus_binds_tighter_than_mul(self) -> None:
        """`-2 * 3` == `(-2) * 3` == -6, the standard reading (Python, JS, ... agree)."""
        node = parse("close > -2 * 3")
        assert isinstance(node, Comparison)
        assert node.right == Arith(Literal(-2.0), ArithOp.MUL, Literal(3.0))

    def test_arith_left_associative(self) -> None:
        """`a - b - c` == `(a - b) - c`, not `a - (b - c)` -- the two give different numbers."""
        node = parse("close > 10 - 3 - 2")
        assert isinstance(node, Comparison)
        assert node.right == Arith(Arith(Literal(10.0), ArithOp.SUB, Literal(3.0)), ArithOp.SUB, Literal(2.0))

    def test_parens_override_precedence(self) -> None:
        node = parse("close > (1 + 2) * 3")
        assert isinstance(node, Comparison)
        assert node.right == Arith(Arith(Literal(1.0), ArithOp.ADD, Literal(2.0)), ArithOp.MUL, Literal(3.0))

    def test_full_example_from_the_brief(self) -> None:
        """`not (rsi(14) > 70) or close > close * 1.05`, exactly as given in the brief."""
        rsi70 = Comparison(IndicatorRef(name="rsi", args=(14.0,), output=None), CompareOp.GT, Literal(70.0))
        right = Comparison(_CLOSE, CompareOp.GT, Arith(_CLOSE, ArithOp.MUL, Literal(1.05)))
        node = parse("not (rsi(14) > 70) or close > close * 1.05")
        assert node == BoolOp(BoolOpKind.OR, (Not(rsi70), right))


# ---------------------------------------------------------------------------
# The two expression kinds must not be interchangeable
# ---------------------------------------------------------------------------


class TestTypeBoundary:
    def test_bare_num_expr_is_not_a_rule(self) -> None:
        with pytest.raises(RuleSyntaxError, match="boolean"):
            parse("close")

    def test_bare_indicator_ref_is_not_a_rule(self) -> None:
        with pytest.raises(RuleSyntaxError, match="boolean"):
            parse("rsi(14)")

    def test_num_expr_and_bool_expr_cannot_be_anded(self) -> None:
        with pytest.raises(RuleSyntaxError, match="boolean"):
            parse("rsi(14) and close")

    def test_num_expr_and_bool_expr_cannot_be_ored(self) -> None:
        with pytest.raises(RuleSyntaxError, match="boolean"):
            parse("close or rsi(14) > 30")

    def test_not_requires_a_bool_operand(self) -> None:
        with pytest.raises(RuleSyntaxError, match="boolean"):
            parse("not close")

    def test_bool_expr_cannot_be_used_as_an_arithmetic_operand(self) -> None:
        with pytest.raises(RuleSyntaxError, match="numeric"):
            parse("(close > 1) + 1 > 0")

    def test_bool_expr_cannot_be_compared(self) -> None:
        with pytest.raises(RuleSyntaxError, match="numeric"):
            parse("(close > 1) > 0")

    def test_bool_expr_cannot_be_crossed(self) -> None:
        with pytest.raises(RuleSyntaxError, match="numeric"):
            parse("(close > 1) crosses_above 0")


# ---------------------------------------------------------------------------
# Round-trip: parse(render(parse(s))) == parse(s), over a corpus including deep/parenthesised trees
# ---------------------------------------------------------------------------


_ROUND_TRIP_CORPUS: tuple[str, ...] = (
    "close > 30",
    "close > -5",
    "close > 1.05",
    "rsi(14) < 30",
    "close < bb_lower(20,2)",
    "close crosses_above vwap()",
    "ema(12) crosses_above ema(26)",
    "ema(50) crosses_below ema(200)",
    "not (rsi(14) > 70) or close > close * 1.05",
    "macd_hist(12,26,9) > 0 and volume > 1000000",
    "close < bb_lower(20,2) and rsi(14) < 30",
    "bb_upper(20,2) - bb_lower(20,2) < close * 0.04",
    "high - low > atr(14) * 1.5",
    "close > sma(200)",
    "close > 1 and close > 2 and close > 3 and close > 4",
    "close > 1 or close > 2 or close > 3",
    "close > 1 and close > 2 or close > 3 and close > 4",
    "not close > 1 and close > 2",
    "not not close > 1",
    "((((close > 1))))",
    "(((close + 1) * 2 - 3) / 4) > 0",
    "close > (1 + (2 * (3 - (4 / 5))))",
    "not (not (not (close > 1)))",
    "close > 1 and (close > 2 or close > 3)",
    "(close > 1 and close > 2) or (close > 3 and close > 4)",
    "volume > 0 and (rsi(14) < 30 or rsi(14) > 70) and not (close < 0)",
)


class TestRoundTrip:
    @pytest.mark.parametrize("expression", _ROUND_TRIP_CORPUS)
    def test_render_then_reparse_yields_an_equal_tree(self, expression: str) -> None:
        node = parse(expression)
        rendered = render(node)
        reparsed = parse(rendered)
        assert node == reparsed, f"{expression!r} -> {rendered!r} did not round-trip"

    def test_round_trip_is_stable_under_a_second_pass(self) -> None:
        """`render(parse(render(parse(s))))` must equal `render(parse(s))` -- rendering a tree that
        already came from `render` must not drift on a second pass."""
        for expression in _ROUND_TRIP_CORPUS:
            once = render(parse(expression))
            twice = render(parse(once))
            assert once == twice

    def test_negative_literal_round_trips(self) -> None:
        node = parse("close > -5")
        assert render(node) == "close > -5"

    def test_whole_number_float_renders_without_trailing_zero(self) -> None:
        node = Comparison(_CLOSE, CompareOp.GT, Literal(30.0))
        assert render(node) == "close > 30"

    def test_fractional_literal_preserved_exactly(self) -> None:
        node = Comparison(_CLOSE, CompareOp.GT, Literal(1.05))
        assert render(node) == "close > 1.05"
        assert parse(render(node)) == node


# ---------------------------------------------------------------------------
# Table-driven: bad expression -> expected error substring, plus position sanity
# ---------------------------------------------------------------------------

_ERROR_CASES: tuple[tuple[str, str], ...] = (
    ("(close > 1", "')'"),
    ("close > 1)", "')'"),
    ("rsi(14) <", "value"),
    ("rsi(14) << 30", "value"),
    ("close >< 30", "value"),
    ("foo(1)", "unknown indicator"),
    ("adj_close > 100", "unknown price field"),
    ("close > 1 and", "value"),
    ("", "value"),
    ("   ", "value"),
    ("rsi(14) > 70 >", "chained"),
    ("1 < rsi(14) < 2", "chained"),
    ("close", "boolean"),
    ("rsi(14) and close", "boolean"),
    ("rsi", "parentheses"),
    ("close close", "unexpected"),
    ("close > ", "value"),
    ("close > 1 and or close > 2", "value"),
    ("close > 1 and and close > 2", "value"),
)


class TestErrors:
    @pytest.mark.parametrize("expression,expected_substring", _ERROR_CASES)
    def test_error_message_contains_expected_substring(
        self, expression: str, expected_substring: str
    ) -> None:
        with pytest.raises(RuleSyntaxError) as excinfo:
            parse(expression)
        assert expected_substring.lower() in str(excinfo.value).lower()

    @pytest.mark.parametrize("expression,_", _ERROR_CASES)
    def test_error_carries_a_position(self, expression: str, _: str) -> None:
        with pytest.raises(RuleSyntaxError) as excinfo:
            parse(expression)
        assert excinfo.value.position is not None
        assert 0 <= excinfo.value.position <= len(expression)

    def test_unknown_price_field_names_close_family_but_not_adj_close(self) -> None:
        """`adj_close` is deliberately excluded -- see `PriceField`'s own docstring on why a
        split/dividend-adjusted series has no place in a rule that must reproduce its trigger dates.
        """
        with pytest.raises(RuleSyntaxError) as excinfo:
            parse("adj_close > 1")
        message = str(excinfo.value)
        assert "adj_close" in message
        assert "close" in message  # the valid-fields list still mentions plain `close`

    def test_unbalanced_parens_missing_close(self) -> None:
        with pytest.raises(RuleSyntaxError):
            parse("close > (1 + 2")

    def test_unbalanced_parens_extra_close(self) -> None:
        with pytest.raises(RuleSyntaxError):
            parse("close > 1 + 2)")

    def test_unknown_function_reports_the_name(self) -> None:
        with pytest.raises(RuleSyntaxError, match="foo"):
            parse("foo(1) > 0")

    def test_indicator_name_without_parens_is_rejected_with_a_hint(self) -> None:
        with pytest.raises(RuleSyntaxError, match="parentheses"):
            parse("rsi > 30")

    def test_trailing_comma_in_call_is_rejected(self) -> None:
        with pytest.raises(RuleSyntaxError):
            parse("sma(20,) > 0")

class TestChoiceOrDateArguments:
    """`IndicatorRef.args` carries `float | str` so a `CHOICE_OR_DATE` parameter is expressible.

    `vwap`'s `anchor` is the only such parameter today, and it is the indicator's *only* parameter:
    with a float-only tuple the rule DSL could not reach it at all, so `vwap(session)` and the
    arbitrary-date anchor the plan calls for could not be written as rules.
    """

    def test_token_argument_parses_and_reaches_the_spec_text(self) -> None:
        tree = parse("close crosses_above vwap(session)")
        assert required_specs(tree) == ["vwap:session"]

    def test_iso_date_argument_survives_as_a_single_token(self) -> None:
        """A date must not lex as `2026 - 01 - 15`, which would silently evaluate to 2010."""
        tree = parse("close > vwap(2026-01-15)")
        assert required_specs(tree) == ["vwap:2026-01-15"]

    @pytest.mark.parametrize(
        "expression",
        ["close crosses_above vwap(session)", "close > vwap(2026-01-15)", "close > vwap()"],
    )
    def test_round_trips(self, expression: str) -> None:
        once = render(parse(expression))
        assert render(parse(once)) == once

    def test_date_token_does_not_break_ordinary_subtraction(self) -> None:
        """The DATE pattern precedes NUMBER in the tokenizer; plain arithmetic must be unaffected."""
        assert isinstance(parse("close - 5 > 0"), Comparison)

    def test_a_date_is_not_a_value(self) -> None:
        """Only meaningful in argument position -- elsewhere it must be refused, not coerced."""
        with pytest.raises(RuleSyntaxError):
            parse("close > 2026-01-15")

    def test_minus_may_not_negate_a_token(self) -> None:
        with pytest.raises(RuleSyntaxError, match="may only negate a number"):
            parse("close > vwap(-session)")

    def test_a_non_numeric_non_token_argument_is_still_refused(self) -> None:
        with pytest.raises(RuleSyntaxError, match="not a number, a token or an ISO date"):
            parse("rsi(<) > 30")


# ---------------------------------------------------------------------------
# Pathological input: must degrade to RuleSyntaxError, never crash
# ---------------------------------------------------------------------------


class TestPathologicalInput:
    def test_ten_thousand_character_expression_does_not_crash(self) -> None:
        """A long *flat* chain (`BoolOp` is n-ary, folded by an iterative loop -- see the grammar
        module's docstring) must parse in a reasonable shape, not merely "not crash"."""
        clause_count = 2000
        expression = " and ".join(f"close > {i}" for i in range(clause_count))
        assert len(expression) > 10_000
        node = parse(expression)
        assert isinstance(node, BoolOp)
        assert len(node.operands) == clause_count

    def test_ten_thousand_character_garbage_raises_cleanly(self) -> None:
        garbage = "close > 1 and " * 750  # trailing "and" with nothing after it
        assert len(garbage) > 10_000
        with pytest.raises(RuleSyntaxError):
            parse(garbage)

    def test_five_hundred_nested_parens_raises_syntax_error_not_recursion_error(self) -> None:
        expression = "(" * 500 + "close > 1" + ")" * 500
        with pytest.raises(RuleSyntaxError, match="nested"):
            parse(expression)

    def test_five_hundred_nested_parens_unbalanced_also_raises_syntax_error(self) -> None:
        expression = "(" * 500
        with pytest.raises(RuleSyntaxError):
            parse(expression)

    def test_long_chain_of_not_raises_syntax_error_not_recursion_error(self) -> None:
        expression = "not " * 500 + "(close > 1)"
        with pytest.raises(RuleSyntaxError, match="nested"):
            parse(expression)

    def test_unicode_raises_syntax_error_not_crash(self) -> None:
        with pytest.raises(RuleSyntaxError):
            parse("close > 1 ☃")  # snowman

    def test_unicode_in_identifier_position_raises_syntax_error(self) -> None:
        with pytest.raises(RuleSyntaxError):
            parse("clöse > 1")

    def test_null_byte_raises_syntax_error_not_crash(self) -> None:
        with pytest.raises(RuleSyntaxError):
            parse("close > 1\x00 and close > 2")

    def test_null_byte_alone_raises_syntax_error(self) -> None:
        with pytest.raises(RuleSyntaxError):
            parse("\x00")

    def test_repeated_unary_minus_does_not_crash(self) -> None:
        """`--------1` (even count of `-`) folds to `1`; the AST has no unary-negation node (see
        `nodes.py`), so the parser folds a leading run of `-` into a signed `Literal` -- see
        `_Parser.parse_unary`'s docstring. Whether or not it is itself a valid *rule* (it is not: a
        bare numeric expression is never a `BoolExpr`), it must not exhaust the stack getting there.
        """
        with pytest.raises(RuleSyntaxError, match="boolean"):
            parse("--------1")

    def test_moderately_long_unary_minus_chain_still_folds_correctly(self) -> None:
        node = parse("close > " + "-" * 8 + "5")
        assert node == Comparison(_CLOSE, CompareOp.GT, Literal(5.0))
        node_odd = parse("close > " + "-" * 7 + "5")
        assert node_odd == Comparison(_CLOSE, CompareOp.GT, Literal(-5.0))

    def test_excessively_long_unary_minus_chain_raises_syntax_error(self) -> None:
        expression = "close > " + "-" * 500 + "1"
        with pytest.raises(RuleSyntaxError, match="nested"):
            parse(expression)

    def test_whitespace_only_raises_syntax_error(self) -> None:
        with pytest.raises(RuleSyntaxError):
            parse("    \t\n  ")

    def test_empty_string_raises_syntax_error(self) -> None:
        with pytest.raises(RuleSyntaxError):
            parse("")


# ---------------------------------------------------------------------------
# indicator_refs()
# ---------------------------------------------------------------------------


class TestIndicatorRefs:
    def test_empty_for_a_rule_with_no_indicators(self) -> None:
        assert indicator_refs(parse("close > 1 and volume > 0")) == []

    def test_single_indicator(self) -> None:
        refs = indicator_refs(parse("rsi(14) < 30"))
        assert refs == [IndicatorRef(name="rsi", args=(14.0,), output=None)]

    def test_collects_across_and_or_not_arith_comparison_cross(self) -> None:
        expression = (
            "not (rsi(14) > 70) and (ema(12) crosses_above ema(26)) "
            "and (bb_upper(20,2) - bb_lower(20,2) < close * 0.04)"
        )
        refs = indicator_refs(parse(expression))
        names_and_outputs = [(r.name, r.output) for r in refs]
        assert names_and_outputs == [
            ("rsi", None),
            ("ema", None),
            ("ema", None),
            ("bb", "upper"),
            ("bb", "lower"),
        ]

    def test_walks_past_a_macro_ref_instead_of_raising(self) -> None:
        """A `macro(...)` leaf must be *handled* by the walk, not merely absent from it.

        `MacroRef` joined the `NumExpr` union when the DSL gained its first non-price field, and
        `_collect`'s match was not extended with it. That does not make the walk quietly skip macro
        nodes -- the unmatched leaf falls through to `assert_never`, so `indicator_refs` raised
        `AssertionError` on *every* rule containing one, including rules whose real subject is an
        ordinary indicator. It went unnoticed because the engine's own walks
        (`guards.required_indicator_refs`, `macro_binding.required_macro_fields`) were both extended
        and are what the rounds exercise; this one's only production caller is the warmup analysis in
        `strategy-program/tools/windows.py`.
        """
        assert indicator_refs(parse("macro(T10Y2Y) > 0")) == []
        # The mixed case is the one that matters: the macro leaf must not swallow its neighbours.
        assert indicator_refs(parse("sma(20) > close and macro(T10Y2Y) > 0")) == [
            IndicatorRef(name="sma", args=(20.0,), output=None)
        ]

    def test_duplicates_are_not_collapsed(self) -> None:
        refs = indicator_refs(parse("rsi(14) > 30 and rsi(14) < 70"))
        assert refs == [
            IndicatorRef(name="rsi", args=(14.0,), output=None),
            IndicatorRef(name="rsi", args=(14.0,), output=None),
        ]

    def test_indicator_ref_is_hashable_for_caller_side_deduplication(self) -> None:
        refs = indicator_refs(parse("rsi(14) > 30 and rsi(14) < 70"))
        assert len(dict.fromkeys(refs)) == 1

    def test_accepts_a_bare_num_expr_too(self) -> None:
        """The interface types `indicator_refs` over `BoolExpr | NumExpr` -- it must also walk a
        tree rooted at a numeric node, not just a full rule, since callers may want the indicators
        referenced by a sub-expression."""
        node: NumExpr = Arith(
            IndicatorRef(name="sma", args=(20.0,), output=None), ArithOp.SUB, IndicatorRef(name="ema", args=(20.0,), output=None)
        )
        refs = indicator_refs(node)
        assert refs == [
            IndicatorRef(name="sma", args=(20.0,), output=None),
            IndicatorRef(name="ema", args=(20.0,), output=None),
        ]


# ---------------------------------------------------------------------------
# The catalog's real expressions -- the DSL as it is actually used, not just as specified
# ---------------------------------------------------------------------------


class TestCatalogExpressionsParse:
    """Cross-check against `app.rules.catalog` directly (rather than duplicating its strings here)
    so this file fails loudly if the catalog ever adds an expression this grammar cannot parse --
    exactly the failure mode `tests/test_rule_catalog.py::TestCatalogParses` also guards, from the
    grammar side instead of the catalog side.
    """

    def test_every_catalog_expression_parses_and_round_trips(self) -> None:
        from app.rules import catalog

        for rule in catalog.catalog():
            node = parse(rule.expression)
            reparsed = parse(render(node))
            assert node == reparsed, rule.rule_id


# ---------------------------------------------------------------------------
# Case-insensitivity of keywords and identifiers
# ---------------------------------------------------------------------------


class TestCaseInsensitivity:
    def test_keywords_are_case_insensitive(self) -> None:
        assert parse("close > 1 AND close > 2") == parse("close > 1 and close > 2")
        assert parse("NOT (close > 1)") == parse("not (close > 1)")
        assert parse("ema(12) CROSSES_ABOVE ema(26)") == parse("ema(12) crosses_above ema(26)")

    def test_indicator_names_are_case_insensitive(self) -> None:
        assert parse("RSI(14) < 30") == parse("rsi(14) < 30")


# ---------------------------------------------------------------------------
# Grammar-construct coverage ledger
# ---------------------------------------------------------------------------
#
# Every production in `grammar`'s module-docstring EBNF, and where it is exercised above:
#
#   rule        -- TestTypeBoundary (bare NumExpr rejected), every TestNodeTypeCoverage case
#   or_expr     -- TestNodeTypeCoverage.test_bool_op_and_or, TestPrecedenceAndNesting (n-ary, mixed)
#   and_expr    -- same
#   not_expr    -- TestNodeTypeCoverage.test_not, TestPrecedenceAndNesting.test_not_binds_tighter...
#   comparison  -- TestNodeTypeCoverage.test_comparison_all_six_ops, TestErrors (chained rejection)
#   compare_op  -- TestNodeTypeCoverage.test_comparison_all_six_ops (all six)
#   cross_op    -- TestNodeTypeCoverage.test_cross_both_directions (both directions)
#   arith       -- TestNodeTypeCoverage.test_arith_all_four_ops, TestPrecedenceAndNesting (assoc.)
#   term        -- TestPrecedenceAndNesting.test_mul_binds_tighter_than_add
#   unary       -- TestNodeTypeCoverage.test_literal_negative, TestPathologicalInput (unary chains)
#   primary     -- TestNodeTypeCoverage (all four atom kinds), TestPrecedenceAndNesting (grouping)
#   arg         -- TestNodeTypeCoverage.test_indicator_ref_zero_args, TestErrors (non-numeric arg)
#   price_field -- TestNodeTypeCoverage.test_price_ref_every_field
#
# Deliberately NOT covered (see the module docstring's closing paragraph for why): scientific
# notation in numeric literals, non-ASCII characters inside an identifier, and any particular
# whitespace or parenthesisation surviving a render -- only tree equality after a round trip is
# promised.


class TestParseRanking:
    """`parse_ranking` -- the numeric entry point a `StrategyCard.rank_by` key is parsed through.

    The mirror image of :class:`TestTypeBoundary`: that class pins "a number is not a rule", these
    pin "a condition is not a ranking key". Both boundaries are enforced by the same two helpers
    (`_expect_bool` / `_expect_num`) at the same place, so a change that loosened one would be
    expected to loosen the other, and each direction is asserted rather than assumed from the other.
    """

    @pytest.mark.parametrize(
        "expression",
        [
            "rsi(14)",
            "close",
            "close / sma(200)",
            "(close - sma(50)) / atr(14)",
            "-rsi(14)",
            "2 * close - 1",
        ],
    )
    def test_a_numeric_expression_parses(self, expression: str) -> None:
        node = grammar.parse_ranking(expression)
        # Round-trips through the same renderer a rule does -- `render` is not kind-specific.
        assert grammar.parse_ranking(grammar.render(node)) == node

    @pytest.mark.parametrize(
        "expression",
        [
            "close > sma(50)",
            "rsi(14) < 30 and close > sma(200)",
            "not close > 1",
            "close crosses_above sma(50)",
        ],
    )
    def test_a_condition_is_rejected(self, expression: str) -> None:
        with pytest.raises(grammar.RuleSyntaxError, match="ranking key"):
            grammar.parse_ranking(expression)

    @pytest.mark.parametrize("expression", ["", "   ", "sma(", "close +", "wibble(3)"])
    def test_malformed_input_raises_the_same_error_type_a_rule_would(self, expression: str) -> None:
        with pytest.raises(grammar.RuleSyntaxError):
            grammar.parse_ranking(expression)

    def test_the_two_entry_points_build_the_same_tree_for_a_shared_subexpression(self) -> None:
        # `close / sma(200)` as a ranking key must be the identical node the same text would be as
        # the left operand of a rule -- one grammar, one tree, two expectations at the top.
        as_key = grammar.parse_ranking("close / sma(200)")
        as_operand = grammar.parse("close / sma(200) > 1").left
        assert as_key == as_operand

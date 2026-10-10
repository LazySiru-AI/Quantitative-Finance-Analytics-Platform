"""What the parser says when it says no.

Split from ``test_rule_grammar.py``, which covers what parses. These cover the *messages*, on the
grounds that a rejection is a user interface: the grammar already supported every indicator a UAT
persona wanted, and the persona abandoned the backtest workbench as "a deal-breaker for a momentum
trader" because the rejection for ``sma20 > sma50`` read

    unknown price field 'sma20' -- valid fields are open, high, low, close, volume

That message is true, and it silently implies the five price fields are the whole vocabulary. The
capability was never missing; the error taught the wrong conclusion, and a feature nobody can find
is worth exactly as much as one that does not exist.

The load-bearing property is :class:`TestEveryHintParses`: a suggestion that does not itself parse
is worse than no suggestion, because it converts a user's correct suspicion that they mistyped
something into a belief that the engine is broken.
"""

from __future__ import annotations

import re

import pytest

from app.indicators.registry import catalog
from app.rules.grammar import RuleSyntaxError, parse

#: Pulls the suggested call out of either phrasing this module emits ("did you mean X?" /
#: "e.g. X"), so the assertion below is about the hint rather than about the sentence around it.
_HINT_RE = re.compile(r"(?:did you mean|e\.g\.)\s+([a-z_]+\([^)]*\))")


def _message(expression: str) -> str:
    with pytest.raises(RuleSyntaxError) as excinfo:
        parse(expression)
    return str(excinfo.value)


class TestGluedParameter:
    """`sma20` -- an indicator name with its parameter stuck to it. The single most natural thing to
    type, and the exact input that derailed the persona."""

    @pytest.mark.parametrize(
        ("expression", "expected_hint"),
        [
            ("sma20 > sma50", "sma(20)"),
            ("rsi14 < 70", "rsi(14)"),
            ("ema200 > close", "ema(200)"),
            ("atr14 > 1", "atr(14)"),
        ],
    )
    def test_the_suggestion_uses_the_number_the_user_typed(
        self, expression: str, expected_hint: str
    ) -> None:
        message = _message(expression)

        assert expected_hint in message
        assert "parentheses" in message

    def test_a_glued_name_that_is_not_an_indicator_gets_the_general_message(self) -> None:
        """`foo20` must not be dressed up as a near-miss for something that does not exist."""
        message = _message("foo20 > 1")

        assert "did you mean" not in message
        assert "foo20" in message


class TestBareIndicatorName:
    def test_a_bare_name_suggests_the_call_with_its_defaults(self) -> None:
        message = _message("sma > close")

        assert "sma(20)" in message, "the hint should carry the spec's default, not a bare ellipsis"

    def test_an_output_suffix_is_named_as_such(self) -> None:
        message = _message("bb_lower > close")

        assert "'lower' output of 'bb'" in message
        assert "bb_lower(" in message


class TestGeneralMessage:
    """The fallback, for an identifier that resembles nothing."""

    def test_it_says_indicators_exist(self) -> None:
        """The whole failure this module exists to prevent: a message that lists only price fields
        reads as "price fields are all there is"."""
        message = _message("close > opne")

        assert "sma(20)" in message, "the general message must demonstrate the call form"
        assert "indicators" in message

    def test_it_lists_the_registered_indicators(self) -> None:
        message = _message("close > opne")

        for spec in catalog():
            assert spec.name in message

    def test_it_still_lists_the_price_fields(self) -> None:
        message = _message("close > opne")

        for field in ("open", "high", "low", "close", "volume"):
            assert field in message


class TestEveryHintParses:
    """A suggestion that does not parse is worse than none.

    Sweeps every registered indicator through all three malformed shapes, extracts whatever call the
    parser suggested, and feeds it straight back in. This is what stops a future indicator whose
    defaults render badly -- a string parameter, say -- from shipping a hint that cannot be pasted.
    """

    def _probes(self) -> list[str]:
        probes: list[str] = []
        for spec in catalog():
            probes.append(spec.name)
            probes.append(f"{spec.name}20")
            probes.extend(f"{spec.name}_{output}" for output in spec.outputs)
        return probes

    def test_the_sweep_actually_covers_something(self) -> None:
        assert len(self._probes()) >= 20

    def test_every_suggested_call_parses(self) -> None:
        failures: list[tuple[str, str, str]] = []

        for probe in self._probes():
            try:
                parse(f"{probe} > 0")
            except RuleSyntaxError as exc:
                message = str(exc)
            else:
                continue  # parsed on its own; no hint to check

            match = _HINT_RE.search(message)
            if match is None:
                failures.append((probe, "<no hint offered>", message))
                continue
            hint = match.group(1)
            try:
                parse(f"{hint} > 0")
            except RuleSyntaxError as exc:
                failures.append((probe, hint, str(exc)))

        assert not failures, f"hints that do not parse: {failures}"

"""`app.evolution.ruleforms` -- the eight rule shapes, and the discipline read off an emitted rule.

The defects these tests exist for are both measured, not hypothetical. The completed 231-generation
run explored exactly one strategy form across all 2,374 evaluations because `_rules_card` composed
every rule from one hardcoded f-string; and `discipline` was drawn with `rng.choice(list(Discipline))`,
mutated freely, and displayed as though it described the card, which is why two pairs among the 25
outstanding seat requests are byte-identical strategies wearing different labels
(`docs/research/loop/01-what-the-search-found.md`).

What the tests below hold, in order of how badly each would hurt if it broke:

(a) every shape renders text that parses under the *same* grammar `_rules_card` validates against, at
    every corner of the bounded period range -- not just at one comfortable midpoint;
(b) every shape classifies to a discipline, so `_rules_card` can never emit a card it then has to
    refuse for want of a label;
(c) the eight shapes are actually eight -- distinct entry text, and between them covering the five
    disciplines this engine can express;
(d) two rules that are byte-identical classify identically, and a rule's label does not depend on how
    its conditions happen to be ordered or negated -- the property `discipline` did not have;
(e) the two `Discipline` members this engine cannot express (`pairs-rotation`, `risk-managed`) are
    never invented, and an unrecognised rule yields `None` rather than a guess.
"""

from __future__ import annotations

import itertools

import pytest

from app.evolution import ruleforms
from app.evolution.models import LEGACY_RULE_SHAPE, RULE_SHAPES, RULES_PERIOD_BOUNDS
from app.rules import grammar
from app.tournament.models import Discipline

#: Every corner of the declared period space, plus one interior point, filtered to the orderings
#: `app.evolution.genome._fix_rules_ordering` can actually produce (`fast < slow < regime_ma`). A form
#: that only parses at the middle of the range is a form that breaks after a long enough mutation chain,
#: which is exactly the failure mode nothing would catch until a scoring run lost a card to it.
_PERIOD_CASES: tuple[tuple[int, int, int], ...] = tuple(
    combo
    for combo in itertools.product(
        (RULES_PERIOD_BOUNDS["fast"][0], 12, RULES_PERIOD_BOUNDS["fast"][1]),
        (RULES_PERIOD_BOUNDS["slow"][0], 26, RULES_PERIOD_BOUNDS["slow"][1]),
        (RULES_PERIOD_BOUNDS["regime_ma"][0], 150, RULES_PERIOD_BOUNDS["regime_ma"][1]),
    )
    if combo[0] < combo[1] < combo[2]
)


def _render(shape: str, periods: tuple[int, int, int]) -> tuple[str, str]:
    fast, slow, regime_ma = periods
    return ruleforms.render(shape, fast=fast, slow=slow, regime_ma=regime_ma)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# (a) every shape parses, everywhere in the bounded period range
# ---------------------------------------------------------------------------


class TestRendering:
    @pytest.mark.parametrize("shape", RULE_SHAPES)
    @pytest.mark.parametrize("periods", _PERIOD_CASES)
    def test_entry_and_exit_parse(self, shape: str, periods: tuple[int, int, int]) -> None:
        entry, exit_rule = _render(shape, periods)
        grammar.parse(entry)
        grammar.parse(exit_rule)

    @pytest.mark.parametrize("shape", RULE_SHAPES)
    def test_indicator_periods_stay_inside_the_registry_limits(self, shape: str) -> None:
        """The grammar does not range-check an indicator's parameters -- `sma(600)` and
        `swing_high(300)` both parse and both fail later, at evaluation time, as a whole card lost mid
        run. `RULES_PERIOD_BOUNDS` is what prevents that, and this asserts the bounds are actually tight
        enough for every indicator all eight shapes reach for."""
        from app.indicators.registry import get as indicator_spec

        for periods in _PERIOD_CASES:
            for expression in _render(shape, periods):
                for ref in grammar.indicator_refs(grammar.parse(expression)):
                    spec = indicator_spec(ref.name)
                    assert spec is not None, ref.name
                    for param, argument in zip(spec.params, ref.args, strict=False):
                        if param.minimum is None or param.maximum is None:
                            continue
                        assert param.minimum <= float(argument) <= param.maximum, (
                            shape, periods, expression, ref.name, param.name, argument,
                        )

    @pytest.mark.parametrize("shape", RULE_SHAPES)
    def test_every_shape_has_a_non_empty_exit(self, shape: str) -> None:
        """`StrategyCard._something_closes_the_position` accepts a card with no exit only when a target
        or a hold cap is set, and `take_profit_pct` is legitimately `None` on roughly half the genomes
        drawn. Every shape carrying its own exit is what keeps that validator from ever being the thing
        that decides whether a form is buildable."""
        for periods in _PERIOD_CASES:
            assert _render(shape, periods)[1].strip()

    @pytest.mark.parametrize("shape", RULE_SHAPES)
    def test_describe_names_the_form(self, shape: str) -> None:
        text = ruleforms.describe(shape, fast=12, slow=26, regime_ma=150)  # type: ignore[arg-type]
        assert text and not text.endswith(".")
        assert "150" in text, "the regime filter's period should reach the reader"

    def test_the_legacy_shape_renders_the_template_the_completed_run_actually_emitted(self) -> None:
        """Byte-for-byte what `_rules_card`'s hardcoded f-string produced. If this ever drifts, every
        genome reloaded from the 231-generation run silently becomes a different strategy than the one
        its ledger row was scored against."""
        entry, exit_rule = _render(LEGACY_RULE_SHAPE, (13, 21, 135))
        assert entry == "close > sma(135) and ema(13) crosses_above ema(21)"
        assert exit_rule == "ema(13) crosses_below ema(21)"


# ---------------------------------------------------------------------------
# (b) + (c) every shape classifies, and the eight are genuinely eight
# ---------------------------------------------------------------------------


class TestTheSearchSpaceIsWide:
    @pytest.mark.parametrize("shape", RULE_SHAPES)
    def test_every_shape_classifies(self, shape: str) -> None:
        """`_rules_card` refuses a card whose rule it cannot label. Since it only ever emits from
        `RENDERERS`, an unclassifiable shape is a renderer and the classifier having drifted apart --
        and this is where that has to fail, not mid-generation."""
        for periods in _PERIOD_CASES:
            entry, exit_rule = _render(shape, periods)
            assert ruleforms.classify(entry, exit_rule) is not None, (shape, periods, entry)

    def test_the_shapes_emit_distinct_rules(self) -> None:
        """The measurement this whole change answers: masking the numbers out of all 25 outstanding seat
        requests yielded exactly *one* entry/exit template. At one fixed set of periods, eight shapes
        must yield eight."""
        rendered = {shape: _render(shape, (12, 26, 150)) for shape in RULE_SHAPES}
        assert len(set(rendered.values())) == len(RULE_SHAPES), rendered
        assert len({entry for entry, _ in rendered.values()}) == len(RULE_SHAPES), rendered

    def test_the_shapes_cover_every_discipline_this_engine_can_express(self) -> None:
        """Five of seven. `PAIRS_ROTATION` is unreachable because `entry` is evaluated per symbol against
        that symbol's own bars, so the grammar cannot write a spread or a pair -- and it was nonetheless
        the completed run's most common label, on 348 of 934 rules genomes. `RISK_MANAGED` describes the
        brackets, which are not part of the rule text this module is given."""
        found = {ruleforms.classify(*_render(shape, (12, 26, 150))) for shape in RULE_SHAPES}
        assert found == {
            Discipline.TREND,
            Discipline.MOMENTUM,
            Discipline.MEAN_REVERSION,
            Discipline.BREAKOUT,
            Discipline.VOLATILITY,
        }

    def test_pairs_rotation_and_risk_managed_are_never_invented(self) -> None:
        for shape in RULE_SHAPES:
            for periods in _PERIOD_CASES:
                found = ruleforms.classify(*_render(shape, periods))
                assert found not in (Discipline.PAIRS_ROTATION, Discipline.RISK_MANAGED), shape


# ---------------------------------------------------------------------------
# (d) + (e) the classifier is a function of the rule, and refuses to guess
# ---------------------------------------------------------------------------


class TestClassify:
    def test_identical_rules_cannot_carry_different_labels(self) -> None:
        """The `g1815`/`g1823` defect, stated as a property. Those two cards are byte-identical in rule,
        universe, brackets, hold and sizing and were labelled `"breakout"` and `"mean-reversion"`; a
        label derived from the rule cannot do that, because it is the same function of the same input."""
        entry = "close > sma(135) and ema(13) crosses_above ema(21)"
        exit_rule = "ema(13) crosses_below ema(21)"
        assert ruleforms.classify(entry, exit_rule) == ruleforms.classify(entry, exit_rule)
        assert ruleforms.classify(entry, exit_rule) is Discipline.TREND

    def test_conjunction_order_does_not_change_the_label(self) -> None:
        a = ruleforms.classify("close > sma(150) and rsi(12) < 40", "rsi(12) > 60")
        b = ruleforms.classify("rsi(12) < 40 and close > sma(150)", "rsi(12) > 60")
        assert a is b is Discipline.MEAN_REVERSION

    def test_negation_is_pushed_into_the_condition(self) -> None:
        """`not (rsi(14) >= 40)` is `rsi(14) < 40` -- an oversold test, not an overbought one. A
        classifier that ignored polarity would read the inner comparison and label it momentum."""
        assert ruleforms.classify("not (rsi(14) >= 40)", "") is Discipline.MEAN_REVERSION
        assert ruleforms.classify("not (rsi(14) <= 55)", "") is Discipline.MOMENTUM

    def test_a_breakout_beats_the_regime_filter_it_carries(self) -> None:
        """Every shape here carries `close > sma(regime_ma)`, which is a trend condition. Precedence is
        what stops all eight collapsing to `TREND`: the narrower claim wins."""
        assert (
            ruleforms.classify("close crosses_above swing_high(12) and close > sma(150)", "")
            is Discipline.BREAKOUT
        )
        assert (
            ruleforms.classify("close > sma(150) and close < bb_lower(26, 2)", "")
            is Discipline.MEAN_REVERSION
        )

    def test_a_bollinger_band_alone_is_not_a_volatility_card(self) -> None:
        """A band is built from a standard deviation, so a rule that names one is technically reading
        volatility. What the label should say is what the rule *does* with it -- revert from the lower
        band, break out through the upper -- which is why `_is_volatility` triggers on `atr` and not on
        the presence of a `bb` reference."""
        assert (
            ruleforms.classify("close > sma(150) and close < bb_lower(26, 2)", "")
            is not Discipline.VOLATILITY
        )
        assert (
            ruleforms.classify("close > sma(150) and atr(12) / close < 0.02", "")
            is Discipline.VOLATILITY
        )

    def test_the_exit_only_votes_when_the_entry_says_nothing(self) -> None:
        """`rsi-pullback` exits on `rsi(12) > 60`, a momentum condition attached to a mean-reversion
        card. An exit that voted alongside the entry would relabel the form it belongs to."""
        assert ruleforms.classify("close > sma(150) and rsi(12) < 40", "rsi(12) > 60") is (
            Discipline.MEAN_REVERSION
        )
        assert ruleforms.classify("volume > 0", "rsi(12) > 60") is Discipline.MOMENTUM

    @pytest.mark.parametrize("entry", ["", "   ", "close >", "not a rule at all"])
    def test_unrecognisable_text_is_none_never_a_guess(self, entry: str) -> None:
        """`None` is what `_rules_card` turns into `ProposalRejected`. A default category here would put
        an invented label on a card, which is the defect this module exists to remove."""
        assert ruleforms.classify(entry, "") is None

    def test_a_rule_that_parses_but_names_nothing_is_none(self) -> None:
        assert ruleforms.classify("volume > 1000000", "") is None


# ---------------------------------------------------------------------------
# The vocabulary in models.py and the renderers here must not drift
# ---------------------------------------------------------------------------


def test_renderers_cover_exactly_the_declared_vocabulary() -> None:
    """`RULE_SHAPES` lives in `app.evolution.models` so `app.evolution.genome` can draw from it without
    importing the grammar. `ruleforms` re-checks the two agree at import; this is the same assertion in
    the suite, so the failure is a named test rather than an import error somewhere downstream."""
    assert set(ruleforms.RENDERERS) == set(RULE_SHAPES)
    assert LEGACY_RULE_SHAPE in RULE_SHAPES


def test_render_refuses_an_unknown_shape() -> None:
    with pytest.raises(KeyError):
        ruleforms.render("bollinger-squeeze", fast=12, slow=26, regime_ma=150)  # type: ignore[arg-type]

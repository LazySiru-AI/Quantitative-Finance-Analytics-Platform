"""Tests for `strategy-program/tools/round38.py`'s pre-registered field.

`strategy-program` is not a legal Python package name (the hyphen), so `round38.py` is loaded by file
path here -- the identical precedent `tests/test_contributions.py` already sets for the same reason.

Every test pins one claim `ROUND-38-PLAN.md` makes about the field, so the plan cannot drift away
from the cards it pre-registers without something going red:

* `TestFieldShape` -- seven cards, unique ids, every one `Purpose.SAVINGS`, sleeve weights an exact
  partition of one, the identical base allocation and band on every card including the control.
* `TestControlIsAControl` -- `r38-control` carries `rules == ()`. This is the round's whole
  measurement axis (treatment MINUS control); a control that quietly acquired a rule would make every
  margin in the round meaningless while every other assertion here still passed.
* `TestRulesAreWellFormed` -- every `condition` parses through the real grammar, every `on_symbol` is
  one of that card's own sleeves (which `AllocationCard` also validates, asserted here because it is
  a claim of the plan and not only an invariant of the model), and no rule in this field uses
  `shift_expr` -- but `parse_ranking` is exercised on any that ever does, so adding one cannot slip
  past unvalidated.
* `TestMacroTerms` -- the six macro/price conditions are exactly the ones the plan names, the real
  yield is formed as nominal MINUS breakeven and not the other way round, and the price placebo
  carries no macro term at all.
* `TestBudget` -- every card is inside PROTOCOL.md section 3 rule 3's ten free numbers.
* `TestTaxableDisjointness` -- no sleeve ticker intersects the live roth union, recomputed from the
  card library rather than from a pasted list.
* `TestDeterminism` -- `build()` is a pure function: two calls produce byte-identical JSON.
* `TestOnDiskRoundTrip` -- the committed cards under `data/rounds/r38-2026-09/cards/` re-validate
  through `AllocationCard.model_validate_json` and equal what `build()` produces today. This is what
  catches a hand edit to a frozen card, which pre-registration exists to prevent.

Fast by construction: no bar store, no macro pin, no engine run. `grammar.parse` needs neither, and
`guards.check` -- which does need a pin -- is exercised by the tool's own `--smoke` path instead.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "round38", str(_REPO / "strategy-program" / "tools" / "round38.py")
)
assert _spec is not None and _spec.loader is not None
round38 = importlib.util.module_from_spec(_spec)
sys.modules["round38"] = round38
_spec.loader.exec_module(round38)

from app.rules import grammar  # noqa: E402
from app.tournament.allocation import AllocationCard  # noqa: E402
from app.tournament.purposes import Purpose  # noqa: E402

EXPECTED_CARDS = 7

EXPECTED_CONDITIONS = {
    "r38-control": None,
    "r38-realyield-hi-1": "macro(DGS10) - macro(T10YIE) > 1.0",
    "r38-realyield-hi-2": "macro(DGS10) - macro(T10YIE) > 2.0",
    "r38-realyield-lo-1": "macro(DGS10) - macro(T10YIE) < 1.0",
    "r38-nominal-hi-4": "macro(DGS10) > 4.0",
    "r38-breakeven-lo-2": "macro(T10YIE) < 2.0",
    "r38-price-placebo": "close < sma(200)",
}


@pytest.fixture(scope="module")
def cards() -> list[AllocationCard]:
    return round38.build()


class TestFieldShape:
    def test_card_count(self, cards: list[AllocationCard]) -> None:
        assert len(cards) == EXPECTED_CARDS

    def test_agent_ids_are_unique_and_expected(self, cards: list[AllocationCard]) -> None:
        ids = [card.agent_id for card in cards]
        assert len(set(ids)) == len(ids)
        assert set(ids) == set(EXPECTED_CONDITIONS)

    def test_every_card_is_a_savings_card(self, cards: list[AllocationCard]) -> None:
        assert {card.purpose for card in cards} == {Purpose.SAVINGS}

    def test_sleeve_weights_sum_to_exactly_one(self, cards: list[AllocationCard]) -> None:
        for card in cards:
            total = sum((sleeve.target_weight for sleeve in card.sleeves), Decimal(0))
            assert total == Decimal(1), f"{card.agent_id} sums to {total}"

    def test_base_allocation_and_band_are_identical_across_the_field(
        self, cards: list[AllocationCard]
    ) -> None:
        """The round varies the tilt condition and nothing else -- PROTOCOL.md section 7."""
        expected = tuple((symbol, Decimal(weight)) for symbol, weight in round38.SLEEVES)
        for card in cards:
            assert tuple((s.symbol, s.target_weight) for s in card.sleeves) == expected
            assert card.band_pct == round38.BAND

    def test_validates_as_an_allocation_card(self, cards: list[AllocationCard]) -> None:
        for card in cards:
            assert AllocationCard.model_validate(card.model_dump()) == card


class TestControlIsAControl:
    def test_control_has_no_rules(self, cards: list[AllocationCard]) -> None:
        control = next(c for c in cards if c.agent_id == "r38-control")
        assert control.rules == ()

    def test_every_other_card_has_exactly_one_rule(self, cards: list[AllocationCard]) -> None:
        for card in cards:
            if card.agent_id == "r38-control":
                continue
            assert len(card.rules) == 1, f"{card.agent_id} has {len(card.rules)} rules"


class TestRulesAreWellFormed:
    def test_every_condition_parses(self, cards: list[AllocationCard]) -> None:
        for card in cards:
            for rule in card.rules:
                grammar.parse(rule.condition)

    def test_every_shift_expr_parses_as_a_ranking_key(self, cards: list[AllocationCard]) -> None:
        seen = 0
        for card in cards:
            for rule in card.rules:
                if rule.shift_expr is not None:
                    grammar.parse_ranking(rule.shift_expr)
                    seen += 1
        # This field is entirely constant-shift, and that is a claim of the plan, not an accident.
        assert seen == 0

    def test_every_rule_uses_a_constant_shift_of_ten_points(
        self, cards: list[AllocationCard]
    ) -> None:
        for card in cards:
            for rule in card.rules:
                assert rule.shift_pct == round38.SHIFT
                assert rule.shift_expr is None

    def test_the_shift_exceeds_the_band(self) -> None:
        """A shift inside the band could be absorbed and never trade -- a tilt that never fires."""
        assert round38.SHIFT > round38.BAND

    def test_on_symbol_is_one_of_the_cards_own_sleeves(self, cards: list[AllocationCard]) -> None:
        for card in cards:
            symbols = {sleeve.symbol for sleeve in card.sleeves}
            for rule in card.rules:
                assert rule.on_symbol in symbols
                assert rule.from_symbol in symbols
                assert rule.to_symbol in symbols

    def test_every_rule_reads_the_session_axis_off_spy(self, cards: list[AllocationCard]) -> None:
        for card in cards:
            for rule in card.rules:
                assert rule.on_symbol == round38.ON_SYMBOL == "SPY"


class TestMacroTerms:
    def test_conditions_are_exactly_the_pre_registered_ones(
        self, cards: list[AllocationCard]
    ) -> None:
        actual = {
            card.agent_id: (card.rules[0].condition if card.rules else None) for card in cards
        }
        assert actual == EXPECTED_CONDITIONS

    def test_real_yield_is_nominal_minus_breakeven(self) -> None:
        """Sign matters: breakeven minus nominal is a different quantity with the opposite sign."""
        assert round38.REAL_YIELD == "macro(DGS10) - macro(T10YIE)"
        rendered = grammar.render(grammar.parse(f"{round38.REAL_YIELD} > 1.0"))
        assert rendered == "(macro(DGS10) - macro(T10YIE)) > 1"

    def test_the_placebo_carries_no_macro_term(self, cards: list[AllocationCard]) -> None:
        placebo = next(c for c in cards if c.agent_id == "r38-price-placebo")
        assert "macro(" not in placebo.rules[0].condition

    def test_every_other_treatment_carries_a_macro_term(self, cards: list[AllocationCard]) -> None:
        for card in cards:
            if card.agent_id in {"r38-control", "r38-price-placebo"}:
                continue
            assert "macro(" in card.rules[0].condition


class TestBudget:
    def test_every_card_is_inside_the_ten_free_number_budget(
        self, cards: list[AllocationCard]
    ) -> None:
        for card in cards:
            count = round38.free_numbers(card)
            assert count <= 10, f"{card.agent_id} uses {count} free numbers"

    def test_the_counts_are_the_ones_the_plan_reports(self, cards: list[AllocationCard]) -> None:
        counts = {card.agent_id: round38.free_numbers(card) for card in cards}
        assert counts["r38-control"] == 5
        assert all(counts[k] == 7 for k in counts if k != "r38-control")


class TestTaxableDisjointness:
    def test_no_sleeve_is_claimed_by_a_live_roth_card(self, cards: list[AllocationCard]) -> None:
        assert round38.check_taxable_disjointness(cards) == []

    def test_the_roth_union_is_recomputed_and_non_empty(self) -> None:
        """A silently empty union would make the check above pass vacuously."""
        assert len(round38.roth_union()) > 0


class TestDeterminism:
    def test_build_is_byte_identical_across_calls(self) -> None:
        first = [c.model_dump_json(indent=2) for c in round38.build()]
        second = [c.model_dump_json(indent=2) for c in round38.build()]
        assert first == second


class TestOnDiskRoundTrip:
    def test_every_card_round_trips_and_matches_build(self, cards: list[AllocationCard]) -> None:
        for card in cards:
            path = round38.OUT / f"{card.agent_id}.json"
            assert path.exists(), f"{path} was never written; run round38.py --write"
            loaded = AllocationCard.model_validate_json(path.read_text(encoding="utf-8"))
            assert loaded == card

    def test_the_directory_holds_exactly_the_field(self, cards: list[AllocationCard]) -> None:
        on_disk = {p.stem for p in round38.OUT.glob("*.json")}
        assert on_disk == {card.agent_id for card in cards}

    def test_the_on_disk_purpose_is_savings_in_the_json_itself(self) -> None:
        """Read as raw JSON, not through the model, so a wrong default cannot supply the answer."""
        for path in round38.OUT.glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert payload["purpose"] == "savings", path.name

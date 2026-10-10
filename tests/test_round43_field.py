"""Tests for `strategy-program/tools/round43.py`'s pre-registered field.

`strategy-program` is not a legal Python package name (the hyphen), so `round43.py` (and
`round43_run.py`) are loaded by file path here -- the identical precedent `test_round38_field.py`
already sets for the same reason.

Every test pins one claim `ROUND-43-PLAN.md` makes about the field, so the plan cannot drift away
from the cards it pre-registers without something going red:

* `TestFieldShape` -- six cards, unique ids, every one `Purpose.SAVINGS`, sleeve weights an exact
  partition of one, the identical base allocation and band on every card including the control.
* `TestControlIsAControl` -- `r43-control` carries `rules == ()`. This is the round's whole
  measurement axis (treatment MINUS control); a control that quietly acquired a rule would make every
  margin in the round meaningless while every other assertion here still passed.
* `TestRulesAreWellFormed` -- every `condition` parses through the real grammar, every `on_symbol` /
  `from_symbol` / `to_symbol` is one of that card's own sleeves, and every rule uses a constant
  `shift_pct` of 0.10 (never `shift_expr`).
* `TestSixConditions` -- the six agent ids, conditions, on_symbols, from_symbols and to_symbols are
  exactly the ones the plan names, and no rule anywhere in this field carries a `macro(...)` term
  (this round is price-only, unlike round 38).
* `TestBudget` -- every card is inside PROTOCOL.md section 3 rule 3's ten free numbers.
* `TestTaxableDisjointness` -- no sleeve ticker intersects the live roth union, recomputed from the
  card library rather than from a pasted list.
* `TestDeterminism` -- `build()` is a pure function: two calls produce byte-identical JSON.
* `TestOnDiskRoundTrip` -- the committed cards under `data/rounds/r43-2026-09/cards/` re-validate
  through `AllocationCard.model_validate_json` and equal what `build()` produces today.
* `TestRunHarnessConstants` -- `round43_run.py` (imported by path) points at the r43 cards directory
  and control id, so the harness cannot silently score the wrong round's field.

Fast by construction: no bar store, no engine run for the field tests. `support_table` (which does
need the bar store) is exercised only by the tool's own dry-run path, not by these tests.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]


def _load(name: str, relpath: str):
    spec = importlib.util.spec_from_file_location(name, str(_REPO / relpath))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


round43 = _load("round43", "strategy-program/tools/round43.py")
round43_run = _load("round43_run", "strategy-program/tools/round43_run.py")

from app.rules import grammar  # noqa: E402
from app.tournament.allocation import AllocationCard  # noqa: E402
from app.tournament.purposes import Purpose  # noqa: E402

EXPECTED_CARDS = 6

#: `(condition, on_symbol, from_symbol, to_symbol)`, or `None` for the control.
EXPECTED_RULES: dict[str, tuple[str, str, str, str] | None] = {
    "r43-control": None,
    "r43-agg-trend-bil": ("close < sma(200)", "AGG", "AGG", "BIL"),
    "r43-agg-trend-gld": ("close < sma(200)", "AGG", "AGG", "GLD"),
    "r43-agg-trend-bil-sma100": ("close < sma(100)", "AGG", "AGG", "BIL"),
    "r43-gld-trend": ("close > sma(200)", "GLD", "AGG", "GLD"),
    "r43-price-placebo-spy": ("close < sma(200)", "SPY", "SPY", "BIL"),
}


@pytest.fixture(scope="module")
def cards() -> list[AllocationCard]:
    return round43.build()


class TestFieldShape:
    def test_card_count(self, cards: list[AllocationCard]) -> None:
        assert len(cards) == EXPECTED_CARDS

    def test_agent_ids_are_unique_and_expected(self, cards: list[AllocationCard]) -> None:
        ids = [card.agent_id for card in cards]
        assert len(set(ids)) == len(ids)
        assert set(ids) == set(EXPECTED_RULES)

    def test_every_card_is_a_savings_card(self, cards: list[AllocationCard]) -> None:
        assert {card.purpose for card in cards} == {Purpose.SAVINGS}

    def test_sleeve_weights_sum_to_exactly_one(self, cards: list[AllocationCard]) -> None:
        for card in cards:
            total = sum((sleeve.target_weight for sleeve in card.sleeves), Decimal(0))
            assert total == Decimal(1), f"{card.agent_id} sums to {total}"

    def test_base_allocation_and_band_are_identical_across_the_field(
        self, cards: list[AllocationCard]
    ) -> None:
        """The round varies which sleeve's bars a rule reads and nothing else -- PROTOCOL.md section 7."""
        expected = tuple((symbol, Decimal(weight)) for symbol, weight in round43.SLEEVES)
        for card in cards:
            assert tuple((s.symbol, s.target_weight) for s in card.sleeves) == expected
            assert card.band_pct == round43.BAND

    def test_base_allocation_matches_round_38s_own_figures(self, cards: list[AllocationCard]) -> None:
        """This round reuses round 38's base allocation unmodified -- ROUND-43-PLAN.md section 4b."""
        expected = (
            ("SPY", Decimal("0.30")),
            ("AGG", Decimal("0.50")),
            ("GLD", Decimal("0.10")),
            ("BIL", Decimal("0.10")),
        )
        for card in cards:
            assert tuple((s.symbol, s.target_weight) for s in card.sleeves) == expected
        assert Decimal("0.05") == round43.BAND

    def test_validates_as_an_allocation_card(self, cards: list[AllocationCard]) -> None:
        for card in cards:
            assert AllocationCard.model_validate(card.model_dump()) == card


class TestControlIsAControl:
    def test_control_has_no_rules(self, cards: list[AllocationCard]) -> None:
        control = next(c for c in cards if c.agent_id == "r43-control")
        assert control.rules == ()

    def test_every_other_card_has_exactly_one_rule(self, cards: list[AllocationCard]) -> None:
        for card in cards:
            if card.agent_id == "r43-control":
                continue
            assert len(card.rules) == 1, f"{card.agent_id} has {len(card.rules)} rules"


class TestRulesAreWellFormed:
    def test_every_condition_parses(self, cards: list[AllocationCard]) -> None:
        for card in cards:
            for rule in card.rules:
                grammar.parse(rule.condition)

    def test_every_rule_uses_a_constant_shift_of_ten_points(
        self, cards: list[AllocationCard]
    ) -> None:
        for card in cards:
            for rule in card.rules:
                assert rule.shift_pct == round43.SHIFT == Decimal("0.10")
                assert rule.shift_expr is None

    def test_the_shift_exceeds_the_band(self) -> None:
        """A shift inside the band could be absorbed and never trade -- a tilt that never fires."""
        assert round43.SHIFT > round43.BAND

    def test_on_symbol_from_symbol_to_symbol_are_the_cards_own_sleeves(
        self, cards: list[AllocationCard]
    ) -> None:
        for card in cards:
            symbols = {sleeve.symbol for sleeve in card.sleeves}
            for rule in card.rules:
                assert rule.on_symbol in symbols
                assert rule.from_symbol in symbols
                assert rule.to_symbol in symbols


class TestSixConditions:
    def test_conditions_and_symbols_are_exactly_the_pre_registered_ones(
        self, cards: list[AllocationCard]
    ) -> None:
        actual: dict[str, tuple[str, str, str, str] | None] = {}
        for card in cards:
            if not card.rules:
                actual[card.agent_id] = None
                continue
            rule = card.rules[0]
            actual[card.agent_id] = (rule.condition, rule.on_symbol, rule.from_symbol, rule.to_symbol)
        assert actual == EXPECTED_RULES

    def test_the_primary_treatment_reads_agg_into_bil(self, cards: list[AllocationCard]) -> None:
        primary = next(c for c in cards if c.agent_id == "r43-agg-trend-bil")
        rule = primary.rules[0]
        assert rule.condition == "close < sma(200)"
        assert (rule.on_symbol, rule.from_symbol, rule.to_symbol) == ("AGG", "AGG", "BIL")

    def test_the_placebo_reproduces_round_38s_placebo_verbatim(
        self, cards: list[AllocationCard]
    ) -> None:
        """Same condition, on_symbol, from_symbol, to_symbol and shift as `r38-price-placebo`."""
        placebo = next(c for c in cards if c.agent_id == "r43-price-placebo-spy")
        rule = placebo.rules[0]
        assert rule.condition == "close < sma(200)"
        assert (rule.on_symbol, rule.from_symbol, rule.to_symbol) == ("SPY", "SPY", "BIL")
        assert rule.shift_pct == Decimal("0.10")

    def test_no_condition_anywhere_carries_a_macro_term(self, cards: list[AllocationCard]) -> None:
        """This round is price-only -- unlike round 38, no card here reads a FRED series."""
        for card in cards:
            for rule in card.rules:
                assert "macro(" not in rule.condition, f"{card.agent_id} carries a macro term"

    def test_the_sma100_sensitivity_card_differs_only_in_the_indicator_period(
        self, cards: list[AllocationCard]
    ) -> None:
        primary = next(c for c in cards if c.agent_id == "r43-agg-trend-bil").rules[0]
        sensitivity = next(c for c in cards if c.agent_id == "r43-agg-trend-bil-sma100").rules[0]
        assert primary.condition == "close < sma(200)"
        assert sensitivity.condition == "close < sma(100)"
        assert (primary.on_symbol, primary.from_symbol, primary.to_symbol) == (
            sensitivity.on_symbol, sensitivity.from_symbol, sensitivity.to_symbol,
        )

    def test_the_gld_destination_cards_share_the_agg_trend_condition(
        self, cards: list[AllocationCard]
    ) -> None:
        bil_dest = next(c for c in cards if c.agent_id == "r43-agg-trend-bil").rules[0]
        gld_dest = next(c for c in cards if c.agent_id == "r43-agg-trend-gld").rules[0]
        assert bil_dest.condition == gld_dest.condition == "close < sma(200)"
        assert bil_dest.on_symbol == gld_dest.on_symbol == "AGG"
        assert bil_dest.to_symbol == "BIL"
        assert gld_dest.to_symbol == "GLD"


class TestBudget:
    def test_every_card_is_inside_the_ten_free_number_budget(
        self, cards: list[AllocationCard]
    ) -> None:
        for card in cards:
            count = round43.free_numbers(card)
            assert count <= 10, f"{card.agent_id} uses {count} free numbers"

    def test_the_counts_are_the_ones_the_plan_reports(self, cards: list[AllocationCard]) -> None:
        counts = {card.agent_id: round43.free_numbers(card) for card in cards}
        assert counts["r43-control"] == 5
        assert all(counts[k] == 7 for k in counts if k != "r43-control")


class TestTaxableDisjointness:
    def test_no_sleeve_is_claimed_by_a_live_roth_card(self, cards: list[AllocationCard]) -> None:
        assert round43.check_taxable_disjointness(cards) == []

    def test_the_roth_union_is_recomputed_and_non_empty(self) -> None:
        """A silently empty union would make the check above pass vacuously."""
        assert len(round43.roth_union()) > 0


class TestDeterminism:
    def test_build_is_byte_identical_across_calls(self) -> None:
        first = [c.model_dump_json(indent=2) for c in round43.build()]
        second = [c.model_dump_json(indent=2) for c in round43.build()]
        assert first == second


class TestOnDiskRoundTrip:
    def test_every_card_round_trips_and_matches_build(self, cards: list[AllocationCard]) -> None:
        for card in cards:
            path = round43.OUT / f"{card.agent_id}.json"
            assert path.exists(), f"{path} was never written; run round43.py --write"
            loaded = AllocationCard.model_validate_json(path.read_text(encoding="utf-8"))
            assert loaded == card

    def test_the_directory_holds_exactly_the_field(self, cards: list[AllocationCard]) -> None:
        on_disk = {p.stem for p in round43.OUT.glob("*.json")}
        assert on_disk == {card.agent_id for card in cards}

    def test_the_on_disk_purpose_is_savings_in_the_json_itself(self) -> None:
        """Read as raw JSON, not through the model, so a wrong default cannot supply the answer."""
        for path in round43.OUT.glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert payload["purpose"] == "savings", path.name


class TestRunHarnessConstants:
    """`round43_run.py`'s constants must point at round 43's own cards, not round 38's or any other."""

    def test_cards_dir_points_at_round_43(self) -> None:
        assert round43_run.CARDS_DIR == round43.OUT
        assert round43_run.CARDS_DIR.as_posix().endswith("data/rounds/r43-2026-09/cards")

    def test_control_id_matches_the_field(self) -> None:
        assert round43_run.CONTROL_ID == "r43-control"

    def test_primary_and_placebo_ids_are_in_the_field(self) -> None:
        assert round43_run.PRIMARY_ID == "r43-agg-trend-bil"
        assert round43_run.PLACEBO_ID == "r43-price-placebo-spy"
        assert round43_run.PRIMARY_ID in EXPECTED_RULES
        assert round43_run.PLACEBO_ID in EXPECTED_RULES

    def test_no_macro_pin_env_var_is_set_by_this_module(self) -> None:
        """Unlike round38_run.py, this harness must never SET INVDASH_MACRO_PIN -- the field is
        price-only. round38_run.py sets the pin via `os.environ.setdefault("INVDASH_MACRO_PIN", ...)`
        at import time; this module must contain no such call (the name may still appear in prose
        explaining its absence, which is why this checks for the `os.environ` call shape, not the
        bare string)."""
        import inspect

        source = inspect.getsource(round43_run)
        assert "os.environ" not in source
        assert "import os" not in source

    def test_hindsight_tags_are_the_two_2022_bear_windows(self) -> None:
        assert round43_run.HINDSIGHT_TAGS == ("b6m-2", "b1y-1")
        assert set(round43_run.HINDSIGHT_TAGS) <= set(round43_run.BEAR_TAGS)

    def test_smoke_tag_is_a_short_window(self) -> None:
        assert round43_run.SMOKE_TAG == "h1y-6"

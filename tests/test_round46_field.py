"""Tests for `strategy-program/tools/round46.py`'s pre-registered field.

`strategy-program` is not a legal Python package name (the hyphen), so `round46.py` (and
`round46_run.py`) are loaded by file path here -- the identical precedent `test_round43_field.py`
already sets for the same reason.

Every test pins one claim `ROUND-46-PLAN.md` makes about the field, so the plan cannot drift away
from the cards it pre-registers without something going red:

* `TestFieldShape` -- seven cards, unique ids, every one `Purpose.SAVINGS`, sleeve weights an exact
  partition of one, the identical base allocation and band on every card including the control.
* `TestControlIsAControl` -- `r46-control` carries `rules == ()`. This is the round's whole
  measurement axis (treatment MINUS control); a control that quietly acquired a rule would make every
  margin in the round meaningless while every other assertion here still passed.
* `TestRulesAreWellFormed` -- every `condition` parses through the real grammar, every `on_symbol` /
  `from_symbol` / `to_symbol` is one of that card's own sleeves, and every rule uses a constant
  `shift_pct` of 0.10 (never `shift_expr`).
* `TestSevenCards` -- every card's rules (order-sensitive) are exactly the ones the plan names, and no
  rule anywhere in this field carries a `macro(...)` term (this round is price-only, like round 43).
* `TestR43Drift` -- `r46-spy-derisk`'s and `r46-agg-derisk`'s rules equal `r43-price-placebo-spy`'s
  and `r43-agg-trend-bil`'s, read live off `data/rounds/r43-2026-09/cards/`, per
  `ROUND-46-PLAN.md` section 3's reuse requirement.
* `TestBudget` -- every card's free-number count matches what the plan discloses; the single-rule
  cards clear PROTOCOL.md section 3 rule 3's budget of ten, and the two- and three-rule stacked cards
  are documented as exceeding it by construction (see `round46.py`'s module docstring) rather than
  silently passing or silently failing.
* `TestTaxableDisjointness` -- no sleeve ticker intersects the live roth union, recomputed from the
  card library rather than from a pasted list.
* `TestDeterminism` -- `build()` is a pure function: two calls produce byte-identical JSON.
* `TestOnDiskRoundTrip` -- the committed cards under `data/rounds/r46-2026-09/cards/` re-validate
  through `AllocationCard.model_validate_json` and equal what `build()` produces today. Skipped if the
  field has not been written yet (`round46.py --write`).
* `TestRunHarnessConstants` -- `round46_run.py` (imported by path) points at the r46 cards directory
  and control id, so the harness cannot silently score the wrong round's field.

Fast by construction: no bar store, no engine run for the field tests. `support_table` and
`overlap_fraction` (which need the bar store) are exercised only by the tool's own dry-run path, not
by these tests.
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


round46 = _load("round46", "strategy-program/tools/round46.py")
round46_run = _load("round46_run", "strategy-program/tools/round46_run.py")

from app.rules import grammar  # noqa: E402
from app.tournament.allocation import AllocationCard  # noqa: E402
from app.tournament.purposes import Purpose  # noqa: E402

EXPECTED_CARDS = 7

#: `(condition, on_symbol, from_symbol, to_symbol)` tuples in order, or `()` for the control.
EXPECTED_RULES: dict[str, tuple[tuple[str, str, str, str], ...]] = {
    "r46-control": (),
    "r46-spy-derisk": (("close < sma(200)", "SPY", "SPY", "BIL"),),
    "r46-agg-derisk": (("close < sma(200)", "AGG", "AGG", "BIL"),),
    "r46-both": (
        ("close < sma(200)", "SPY", "SPY", "BIL"),
        ("close < sma(200)", "AGG", "AGG", "BIL"),
    ),
    "r46-both-gld": (
        ("close < sma(200)", "SPY", "SPY", "BIL"),
        ("close < sma(200)", "AGG", "AGG", "BIL"),
        ("close > sma(200)", "GLD", "AGG", "GLD"),
    ),
    "r46-trim-high": (("close > sma(200) * 1.15", "SPY", "SPY", "BIL"),),
    "r46-both-trim": (
        ("close < sma(200)", "SPY", "SPY", "BIL"),
        ("close < sma(200)", "AGG", "AGG", "BIL"),
        ("close > sma(200) * 1.15", "SPY", "SPY", "BIL"),
    ),
}

#: Free-number counts the plan discloses (`round46.free_numbers`, identical method to round43's/
#: round38's). Only the single-rule cards (control, spy-derisk, agg-derisk, trim-high) clear
#: PROTOCOL.md section 3 rule 3's budget of ten; the stacked cards exceed it by construction.
EXPECTED_FREE_NUMBERS: dict[str, int] = {
    "r46-control": 5,
    "r46-spy-derisk": 7,
    "r46-agg-derisk": 7,
    "r46-both": 9,
    "r46-both-gld": 11,
    "r46-trim-high": 8,
    "r46-both-trim": 12,
}

#: Cards whose free-number count exceeds PROTOCOL.md's ten-number budget -- disclosed, not refused,
#: per `round46.py`'s module docstring.
OVER_BUDGET_IDS = frozenset({"r46-both-gld", "r46-both-trim"})


@pytest.fixture(scope="module")
def cards() -> list[AllocationCard]:
    return round46.build()


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
        """The round varies which rules a card carries and nothing else -- PROTOCOL.md section 7."""
        expected = tuple((symbol, Decimal(weight)) for symbol, weight in round46.SLEEVES)
        for card in cards:
            assert tuple((s.symbol, s.target_weight) for s in card.sleeves) == expected
            assert card.band_pct == round46.BAND

    def test_base_allocation_matches_round_38_and_round_43s_own_figures(
        self, cards: list[AllocationCard]
    ) -> None:
        expected = (
            ("SPY", Decimal("0.30")),
            ("AGG", Decimal("0.50")),
            ("GLD", Decimal("0.10")),
            ("BIL", Decimal("0.10")),
        )
        for card in cards:
            assert tuple((s.symbol, s.target_weight) for s in card.sleeves) == expected
        assert Decimal("0.05") == round46.BAND

    def test_validates_as_an_allocation_card(self, cards: list[AllocationCard]) -> None:
        for card in cards:
            assert AllocationCard.model_validate(card.model_dump()) == card


class TestControlIsAControl:
    def test_control_has_no_rules(self, cards: list[AllocationCard]) -> None:
        control = next(c for c in cards if c.agent_id == "r46-control")
        assert control.rules == ()

    def test_every_other_card_has_at_least_one_rule(self, cards: list[AllocationCard]) -> None:
        for card in cards:
            if card.agent_id == "r46-control":
                continue
            assert len(card.rules) >= 1, f"{card.agent_id} has no rules"


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
                assert rule.shift_pct == round46.SHIFT == Decimal("0.10")
                assert rule.shift_expr is None

    def test_the_shift_exceeds_the_band(self) -> None:
        """A shift inside the band could be absorbed and never trade -- a tilt that never fires."""
        assert round46.SHIFT > round46.BAND

    def test_on_symbol_from_symbol_to_symbol_are_the_cards_own_sleeves(
        self, cards: list[AllocationCard]
    ) -> None:
        for card in cards:
            symbols = {sleeve.symbol for sleeve in card.sleeves}
            for rule in card.rules:
                assert rule.on_symbol in symbols
                assert rule.from_symbol in symbols
                assert rule.to_symbol in symbols


class TestSevenCards:
    def test_rules_are_exactly_the_pre_registered_ones_in_order(
        self, cards: list[AllocationCard]
    ) -> None:
        actual: dict[str, tuple[tuple[str, str, str, str], ...]] = {}
        for card in cards:
            actual[card.agent_id] = tuple(
                (rule.condition, rule.on_symbol, rule.from_symbol, rule.to_symbol)
                for rule in card.rules
            )
        assert actual == EXPECTED_RULES

    def test_no_condition_anywhere_carries_a_macro_term(self, cards: list[AllocationCard]) -> None:
        """This round is price-only -- like round 43, unlike round 38."""
        for card in cards:
            for rule in card.rules:
                assert "macro(" not in rule.condition, f"{card.agent_id} carries a macro term"

    def test_both_carries_exactly_the_spy_and_agg_derisk_rules(
        self, cards: list[AllocationCard]
    ) -> None:
        both = next(c for c in cards if c.agent_id == "r46-both")
        assert len(both.rules) == 2
        assert (both.rules[0].on_symbol, both.rules[0].to_symbol) == ("SPY", "BIL")
        assert (both.rules[1].on_symbol, both.rules[1].to_symbol) == ("AGG", "BIL")

    def test_both_gld_adds_exactly_the_gld_destination_rule_on_top_of_both(
        self, cards: list[AllocationCard]
    ) -> None:
        both = next(c for c in cards if c.agent_id == "r46-both")
        both_gld = next(c for c in cards if c.agent_id == "r46-both-gld")
        assert both_gld.rules[:2] == both.rules
        assert len(both_gld.rules) == 3
        third = both_gld.rules[2]
        assert (third.condition, third.on_symbol, third.from_symbol, third.to_symbol) == (
            "close > sma(200)", "GLD", "AGG", "GLD",
        )

    def test_both_trim_adds_exactly_the_trim_rule_on_top_of_both(
        self, cards: list[AllocationCard]
    ) -> None:
        both = next(c for c in cards if c.agent_id == "r46-both")
        both_trim = next(c for c in cards if c.agent_id == "r46-both-trim")
        assert both_trim.rules[:2] == both.rules
        assert len(both_trim.rules) == 3
        third = both_trim.rules[2]
        assert (third.condition, third.on_symbol, third.from_symbol, third.to_symbol) == (
            "close > sma(200) * 1.15", "SPY", "SPY", "BIL",
        )

    def test_trim_high_threshold_is_wall_street_ajaes_own_figure(
        self, cards: list[AllocationCard]
    ) -> None:
        trim = next(c for c in cards if c.agent_id == "r46-trim-high")
        rule = trim.rules[0]
        assert rule.condition == "close > sma(200) * 1.15"
        assert (rule.on_symbol, rule.from_symbol, rule.to_symbol) == ("SPY", "SPY", "BIL")


class TestR43Drift:
    """`ROUND-46-PLAN.md` section 3: `r46-spy-derisk` and `r46-agg-derisk` reproduce round 43's
    placebo and primary treatment verbatim. Asserted two ways: against the hard-coded pin in
    `round46.py`, and (skipped if r43's field is absent) against r43's own on-disk cards directly, so
    a hand-edit to either module's constants cannot silently drift from the round it claims to reuse.
    """

    def test_spy_derisk_matches_the_hardcoded_r43_placebo_pin(
        self, cards: list[AllocationCard]
    ) -> None:
        spy = next(c for c in cards if c.agent_id == "r46-spy-derisk")
        rule = spy.rules[0]
        assert (rule.condition, rule.on_symbol, rule.from_symbol, rule.to_symbol) == round46.RULE_SPY_DERISK

    def test_agg_derisk_matches_the_hardcoded_r43_primary_pin(
        self, cards: list[AllocationCard]
    ) -> None:
        agg = next(c for c in cards if c.agent_id == "r46-agg-derisk")
        rule = agg.rules[0]
        assert (rule.condition, rule.on_symbol, rule.from_symbol, rule.to_symbol) == round46.RULE_AGG_DERISK

    def test_no_drift_against_the_live_r43_cards_on_disk(self, cards: list[AllocationCard]) -> None:
        if not round46._R43_SPY_PLACEBO.exists() or not round46._R43_AGG_PRIMARY.exists():
            pytest.skip("r43 field not on disk in this checkout")
        assert round46.check_r43_drift() == []

    def test_check_r43_drift_reports_a_condition_mismatch(self, tmp_path, monkeypatch) -> None:
        """`check_r43_drift` actually compares fields, rather than vacuously passing. Exercised
        against a throwaway copy under `tmp_path` via monkeypatching the module's path constants --
        never against the real, shared `data/rounds/r43-2026-09/cards/` files, which belong to a
        frozen prior round and must not be touched even transiently."""
        if not round46._R43_SPY_PLACEBO.exists():
            pytest.skip("r43 field not on disk in this checkout")
        placebo = AllocationCard.model_validate_json(
            round46._R43_SPY_PLACEBO.read_text(encoding="utf-8")
        )
        mutated = placebo.model_copy(
            update={
                "rules": (
                    placebo.rules[0].model_copy(update={"condition": "close > sma(200)"}),
                )
            }
        )
        fake_placebo = tmp_path / "r43-price-placebo-spy.json"
        fake_placebo.write_text(mutated.model_dump_json(indent=2), encoding="utf-8")
        monkeypatch.setattr(round46, "_R43_SPY_PLACEBO", fake_placebo)

        problems = round46.check_r43_drift()
        assert problems, "a mutated condition must be reported as drift"
        assert any("r46-spy-derisk" in p for p in problems)

    def test_check_r43_drift_reports_a_missing_source_file(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(round46, "_R43_AGG_PRIMARY", tmp_path / "does-not-exist.json")
        problems = round46.check_r43_drift()
        assert any("r46-agg-derisk" in p and "does not exist" in p for p in problems)


class TestBudget:
    def test_the_counts_are_the_ones_the_plan_reports(self, cards: list[AllocationCard]) -> None:
        counts = {card.agent_id: round46.free_numbers(card) for card in cards}
        assert counts == EXPECTED_FREE_NUMBERS

    def test_single_rule_cards_clear_the_ten_number_budget(
        self, cards: list[AllocationCard]
    ) -> None:
        for card in cards:
            if card.agent_id in OVER_BUDGET_IDS:
                continue
            count = round46.free_numbers(card)
            assert count <= 10, f"{card.agent_id} uses {count} free numbers, expected <=10"

    def test_stacked_cards_exceed_the_budget_by_construction_and_it_is_disclosed(
        self, cards: list[AllocationCard]
    ) -> None:
        """PROTOCOL.md section 3 rule 3's ten-number budget was never measured against a card
        carrying more than one rule (round 38 and round 43 had none). This round's whole point is to
        test whether two or three already-individually-cleared rules stack, so exceeding the budget
        here is expected and documented, not silently passed off as compliant."""
        for card in cards:
            if card.agent_id not in OVER_BUDGET_IDS:
                continue
            count = round46.free_numbers(card)
            assert count > 10, f"{card.agent_id} was expected to exceed the budget but counted {count}"


class TestTaxableDisjointness:
    def test_no_sleeve_is_claimed_by_a_live_roth_card(self, cards: list[AllocationCard]) -> None:
        assert round46.check_taxable_disjointness(cards) == []

    def test_the_roth_union_is_recomputed_and_non_empty(self) -> None:
        """A silently empty union would make the check above pass vacuously."""
        assert len(round46.roth_union()) > 0


class TestDeterminism:
    def test_build_is_byte_identical_across_calls(self) -> None:
        first = [c.model_dump_json(indent=2) for c in round46.build()]
        second = [c.model_dump_json(indent=2) for c in round46.build()]
        assert first == second


class TestOnDiskRoundTrip:
    def test_every_card_round_trips_and_matches_build(self, cards: list[AllocationCard]) -> None:
        for card in cards:
            path = round46.OUT / f"{card.agent_id}.json"
            if not path.exists():
                pytest.skip(f"{path} was never written; run round46.py --write")
            loaded = AllocationCard.model_validate_json(path.read_text(encoding="utf-8"))
            assert loaded == card

    def test_the_directory_holds_exactly_the_field(self, cards: list[AllocationCard]) -> None:
        if not round46.OUT.exists():
            pytest.skip(f"{round46.OUT} was never written; run round46.py --write")
        on_disk = {p.stem for p in round46.OUT.glob("*.json")}
        assert on_disk == {card.agent_id for card in cards}

    def test_the_on_disk_purpose_is_savings_in_the_json_itself(self) -> None:
        """Read as raw JSON, not through the model, so a wrong default cannot supply the answer."""
        if not round46.OUT.exists():
            pytest.skip(f"{round46.OUT} was never written; run round46.py --write")
        for path in round46.OUT.glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert payload["purpose"] == "savings", path.name


class TestRunHarnessConstants:
    """`round46_run.py`'s constants must point at round 46's own cards, not round 43's or any other."""

    def test_cards_dir_points_at_round_46(self) -> None:
        assert round46_run.CARDS_DIR == round46.OUT
        assert round46_run.CARDS_DIR.as_posix().endswith("data/rounds/r46-2026-09/cards")

    def test_control_id_matches_the_field(self) -> None:
        assert round46_run.CONTROL_ID == "r46-control"

    def test_the_named_ids_are_all_in_the_field(self) -> None:
        for attr in ("SPY_ID", "AGG_ID", "BOTH_ID", "BOTH_GLD_ID", "TRIM_ID", "BOTH_TRIM_ID"):
            aid = getattr(round46_run, attr)
            assert aid in EXPECTED_RULES, f"{attr} = {aid!r} is not in this round's field"
        assert round46_run.SPY_ID == "r46-spy-derisk"
        assert round46_run.AGG_ID == "r46-agg-derisk"
        assert round46_run.BOTH_ID == "r46-both"
        assert round46_run.BOTH_GLD_ID == "r46-both-gld"
        assert round46_run.TRIM_ID == "r46-trim-high"
        assert round46_run.BOTH_TRIM_ID == "r46-both-trim"

    def test_no_macro_pin_env_var_is_set_by_this_module(self) -> None:
        """This harness must never SET INVDASH_MACRO_PIN -- the field is price-only. round38_run.py
        sets the pin via `os.environ.setdefault("INVDASH_MACRO_PIN", ...)` at import time; this
        module must contain no such call (the name may still appear in prose explaining its absence,
        which is why this checks for the `os.environ` call shape, not the bare string)."""
        import inspect

        source = inspect.getsource(round46_run)
        assert "os.environ" not in source
        assert "import os" not in source

    def test_hindsight_tags_are_the_two_2022_bear_windows(self) -> None:
        assert round46_run.HINDSIGHT_TAGS == ("b6m-2", "b1y-1")
        assert set(round46_run.HINDSIGHT_TAGS) <= set(round46_run.BEAR_TAGS)

    def test_smoke_tag_is_a_short_window(self) -> None:
        assert round46_run.SMOKE_TAG == "h1y-6"

    def test_additivity_tolerance_matches_the_plans_half_point(self) -> None:
        assert round46_run.ADDITIVITY_TOLERANCE_PP == 0.5

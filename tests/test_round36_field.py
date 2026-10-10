"""Tests for `strategy-program/tools/round36.py`'s ordering field -- round 36's ten frozen cards.

`strategy-program` is not a legal Python package name (the hyphen), so `round36.py` is loaded by file
path here -- the identical precedent `tests/test_contributions.py`, `strategy-program/tools/
roth_voltarget.py` and `strategy-program/tools/savings_family.py` already set for the same reason.

Each test pins one claim `strategy-program/ROUND-36-PLAN.md` makes about the field. The round varies
exactly one thing -- which qualifying name takes a scarce slot -- so most of these assert that
*nothing else* varies, which is the only reason a spread between two cells could be attributed to the
chooser at all:

* `TestFieldShape` -- ten cards, the pre-registered `r36-<ordering>-k<slots>` ids, and one fixed rule,
  stop, hold cap and design cutoff across every one of them.
* `TestUniverseIsOnePinnedSet` -- every card's universe is a permutation of the pinned tuple, and the
  reversed cells are *exactly* `tuple(reversed(UNIVERSE))`. If a ticker were ever fat-fingered into
  one arm, the round's cheapest control would silently become a universe comparison instead of an
  ordering one.
* `TestRothDisjointness` -- no ticker intersects any `savings`/`trading` card in the live library, and
  `find_disjointness_violations` reports nothing for the new cards against it. This is the binding
  constraint (Rev. Rul. 2008-5, via `app.tournament.purposes`), not a nicety.
* `TestExpressionsParse` -- entry and exit parse as conditions, every non-`None` `rank_by` parses as a
  *number*, and the strongest/weakest pair are exact string negations of each other.
* `TestParameterBudget` -- every card is inside `PROTOCOL.md` §3's ten-free-number budget, and maximum
  capital at risk is equal across the two slot arms.
* `TestDeterminism` -- `build()` returns the identical field on every call.
* `TestOnDiskFieldRoundTrips` -- the committed JSON under `data/rounds/r36-2026-09/cards/` validates
  back through `StrategyCard.model_validate_json` and equals `build()` field for field. A frozen field
  that no longer matches its generator is not a frozen field (`PROTOCOL.md` §2).

Fast and store-free: nothing here opens the bar store or runs a backtest.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app.rules import grammar
from app.tournament.models import DESIGN_THROUGH, StrategyCard
from app.tournament.purposes import Purpose, find_disjointness_violations

_REPO = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "round36", str(_REPO / "strategy-program" / "tools" / "round36.py")
)
assert _spec is not None and _spec.loader is not None
round36 = importlib.util.module_from_spec(_spec)
sys.modules["round36"] = round36
_spec.loader.exec_module(round36)


EXPECTED_AGENT_IDS = (
    "r36-canonical-k2",
    "r36-canonical-k4",
    "r36-reversed-k2",
    "r36-reversed-k4",
    "r36-strong-k2",
    "r36-strong-k4",
    "r36-weak-k2",
    "r36-weak-k4",
    "r36-volunits-k2",
    "r36-volunits-k4",
)


@pytest.fixture(scope="module")
def cards() -> list[StrategyCard]:
    return round36.build()


class TestFieldShape:
    def test_ten_cells(self, cards: list[StrategyCard]) -> None:
        assert len(cards) == 10
        assert len(round36.ORDERINGS) * len(round36.SLOTS) == 10

    def test_agent_ids_are_the_pre_registered_ones(self, cards: list[StrategyCard]) -> None:
        assert sorted(c.agent_id for c in cards) == sorted(EXPECTED_AGENT_IDS)

    def test_every_card_is_roth_purpose(self, cards: list[StrategyCard]) -> None:
        assert {c.purpose for c in cards} == {Purpose.ROTH}

    def test_one_rule_across_the_whole_field(self, cards: list[StrategyCard]) -> None:
        """Entry, exit, stop, target, hold cap and cutoff are identical in all ten cells -- the only
        reason a difference between two cells can be attributed to the ordering."""
        assert {c.entry for c in cards} == {round36.ENTRY}
        assert {c.exit for c in cards} == {round36.EXIT}
        assert {c.stop_loss_pct for c in cards} == {round36.STOP_LOSS_PCT}
        assert {c.take_profit_pct for c in cards} == {None}
        assert {c.max_hold_days for c in cards} == {round36.MAX_HOLD_DAYS}
        assert {c.designed_through for c in cards} == {DESIGN_THROUGH}

    def test_slot_caps_are_two_and_four(self, cards: list[StrategyCard]) -> None:
        assert sorted({c.max_positions for c in cards}) == [2, 4]

    def test_every_card_states_a_falsification(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            assert card.falsification


class TestUniverseIsOnePinnedSet:
    def test_pinned_tuple_is_the_eight_industry_names(self) -> None:
        assert round36.UNIVERSE == ("XME", "XRT", "XHB", "XSD", "XOP", "XBI", "ITA", "VNQ")

    def test_every_universe_is_a_permutation_of_the_pinned_set(
        self, cards: list[StrategyCard]
    ) -> None:
        for card in cards:
            assert sorted(card.universe) == sorted(round36.UNIVERSE), card.agent_id
            assert len(set(card.universe)) == len(round36.UNIVERSE), card.agent_id

    def test_reversed_cells_are_exactly_the_reverse(self, cards: list[StrategyCard]) -> None:
        expected = tuple(reversed(round36.UNIVERSE))
        reversed_cards = [c for c in cards if c.agent_id.startswith("r36-reversed-")]
        assert len(reversed_cards) == 2
        for card in reversed_cards:
            assert card.universe == expected, card.agent_id

    def test_every_other_cell_is_the_canonical_order(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            if card.agent_id.startswith("r36-reversed-"):
                continue
            assert card.universe == round36.UNIVERSE, card.agent_id

    def test_reversed_helper_is_derived_not_retyped(self) -> None:
        """The reversed arm must be the same *set*, and be built from the canonical tuple."""
        assert round36.reversed_universe() == tuple(reversed(round36.UNIVERSE))
        assert set(round36.reversed_universe()) == set(round36.UNIVERSE)
        assert round36.reversed_universe() != round36.UNIVERSE


class TestRothDisjointness:
    def test_no_ticker_is_held_by_a_savings_or_trading_card(self) -> None:
        taxable = round36.taxable_symbols(round36.library_cards())
        assert taxable, "the library reported no savings/trading tickers at all -- check the loader"
        assert set(round36.UNIVERSE) & taxable == set()

    def test_find_disjointness_violations_reports_nothing(
        self, cards: list[StrategyCard]
    ) -> None:
        violations = round36.disjointness_violations(cards)
        assert violations == (), [v.message for v in violations]

    def test_the_check_is_non_vacuous(self, cards: list[StrategyCard]) -> None:
        """A ticker deliberately taken from a taxable card must be caught, so a green result above is
        evidence the check ran rather than evidence it found nothing to compare."""
        library = round36.library_cards()
        taxable = sorted(round36.taxable_symbols(library))
        poisoned = cards[0].model_copy(
            update={"agent_id": "r36-poisoned", "universe": (taxable[0], *round36.UNIVERSE[1:])}
        )
        violations = find_disjointness_violations([*library, poisoned])
        assert any(v.symbol == taxable[0] for v in violations)


class TestExpressionsParse:
    def test_entry_and_exit_are_conditions(self) -> None:
        grammar.parse(round36.ENTRY)
        grammar.parse(round36.EXIT)

    def test_every_rank_by_parses_as_a_number(self, cards: list[StrategyCard]) -> None:
        ranked = [c for c in cards if c.rank_by is not None]
        assert len(ranked) == 6
        for card in ranked:
            assert card.rank_by is not None
            grammar.parse_ranking(card.rank_by)

    def test_unranked_cells_leave_rank_by_none(self, cards: list[StrategyCard]) -> None:
        unranked = {c.agent_id for c in cards if c.rank_by is None}
        assert unranked == {
            "r36-canonical-k2",
            "r36-canonical-k4",
            "r36-reversed-k2",
            "r36-reversed-k4",
        }

    def test_strongest_and_weakest_are_exact_string_negations(self) -> None:
        assert f"0 - {round36.STRONGEST}" == round36.WEAKEST
        strong = {c.rank_by for c in round36.build() if c.agent_id.startswith("r36-strong-")}
        weak = {c.rank_by for c in round36.build() if c.agent_id.startswith("r36-weak-")}
        assert strong == {round36.STRONGEST}
        assert weak == {round36.WEAKEST}

    def test_a_condition_is_refused_as_a_ranking_key(self) -> None:
        """Pins the direction of the check: `rank_by` is a number, not a condition, so the entry rule
        handed to `parse_ranking` must raise rather than quietly become a ranking key."""
        with pytest.raises(grammar.RuleSyntaxError):
            grammar.parse_ranking(round36.ENTRY)


class TestParameterBudget:
    def test_every_card_is_inside_the_ten_free_number_budget(
        self, cards: list[StrategyCard]
    ) -> None:
        for card in cards:
            ordering = card.agent_id.split("-")[1]
            assert round36.free_number_count(ordering) <= 10, card.agent_id

    def test_max_capital_at_risk_is_equal_across_the_slot_arms(
        self, cards: list[StrategyCard]
    ) -> None:
        assert {c.position_pct * c.max_positions for c in cards} == {
            cards[0].position_pct * cards[0].max_positions
        }


class TestDeterminism:
    def test_build_is_deterministic(self) -> None:
        first = round36.build()
        second = round36.build()
        assert [c.model_dump_json() for c in first] == [c.model_dump_json() for c in second]


class TestOnDiskFieldRoundTrips:
    def test_every_card_on_disk_validates_and_matches_build(
        self, cards: list[StrategyCard]
    ) -> None:
        out = round36.OUT
        assert out.is_dir(), f"the frozen field is missing from {out}"
        paths = sorted(out.glob("*.json"))
        assert len(paths) == len(cards)

        on_disk = {}
        for path in paths:
            card = StrategyCard.model_validate_json(path.read_text(encoding="utf-8"))
            assert path.stem == card.agent_id
            on_disk[card.agent_id] = card

        for card in cards:
            assert on_disk[card.agent_id].model_dump_json() == card.model_dump_json()

    def test_purpose_and_rank_by_survive_serialisation(self) -> None:
        """`purpose` and `rank_by` are the two fields this round turns on, and both are recent
        additions to the card model -- read them straight out of the JSON, not through the model, so a
        default silently filling one in could not hide it."""
        for path in sorted(round36.OUT.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert payload["purpose"] == "roth", path.name
            assert "rank_by" in payload, path.name
            if path.stem.startswith(("r36-canonical-", "r36-reversed-")):
                assert payload["rank_by"] is None, path.name
            else:
                assert isinstance(payload["rank_by"], str) and payload["rank_by"], path.name

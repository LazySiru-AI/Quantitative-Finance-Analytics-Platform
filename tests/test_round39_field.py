"""Tests for `strategy-program/tools/round39.py` -- round 39's style/factor tilt field.

`strategy-program` is not a legal Python package name (the hyphen), so `round39.py` is loaded by
file path here -- the identical precedent `tests/test_contributions.py`,
`tests/test_round35_field.py` and `strategy-program/tools/roth_voltarget.py` already set for the same
reason.

Every test here is fast and touches **no bar store**: the round's expensive claims (window
eligibility, guard causality) are settled by `strategy-program/tools/windows.py` and
`disjoint_field.py`, which need DuckDB. What this module pins is everything that can be wrong
*before* a single bar is read, and in particular the invariant this round could break with real
consequences:

* `TestFieldShape` -- eight cards, four style slices x two arms, with the pre-registered agent ids,
  the same capital budget everywhere, and no brackets anywhere.
* `TestRothInvariant` -- every card is `Purpose.ROTH`, every universe is a subset of the pinned pool,
  no ticker intersects any `savings`- or `trading`-purpose card in the live library (strategy,
  allocation and ladder tiers alike), and `find_disjointness_violations` reports nothing naming one
  of this round's cards. This is the Rev. Rul. 2008-5 boundary -- an IRA replacement purchase
  *destroys* a wash-sale loss rather than deferring it -- and it is the reason this file exists.
* `TestSubstantialIdentityHoldout` -- `IAU` is in the pinned pool and is traded by nothing, and the
  taxable book really does still hold `GLD`. If `GLD` ever leaves the taxable book the hold-out's
  stated reason is stale and the plan needs an amendment, not a silent edit.
* `TestExpressionsParse` -- every `entry` and `exit` parses with `app.rules.grammar.parse` and every
  non-`None` `rank_by` with `parse_ranking`, so a syntax error is a red test rather than a card the
  runner walks past mid-round (`PROTOCOL.md` section 8). Also pins that the one rule comes from
  `app.evolution.ruleforms` rather than a second, drifting copy typed into the tool.
* `TestControlCards` -- each slice's passive control really is passive: an always-true entry, a
  never-true exit, no brackets, and a slot for every name in its slice. If any of that drifts, every
  comparison round 39 draws is void -- both the within-slice rule margin and the between-slice style
  spread, which is the round's actual question.
* `TestParameterBudget` -- no card spends more than PROTOCOL section 3's ten free numbers, and the
  field's actual maximum is five.
* `TestDeterminism` -- `build()` called twice returns field-identical cards. A generated field that
  moved between the dry run and the `--write` would mean the frozen cards are not the ones whose
  properties were checked.
* `TestOnDiskCardsRoundTrip` -- the JSON actually written under `data/rounds/r39-2026-09/cards/`
  re-validates through `StrategyCard.model_validate_json` and matches `build()` field for field.
  Skipped when the directory does not exist, so the suite stays green on a checkout where the field
  has not been authored yet.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from app.rules import grammar
from app.tournament.models import DESIGN_THROUGH, StrategyCard
from app.tournament.purposes import Purpose, find_disjointness_violations

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "strategy-program" / "tools" / "round39.py"


def _load_round39():
    spec = importlib.util.spec_from_file_location("round39_tool", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["round39_tool"] = module
    spec.loader.exec_module(module)
    return module


round39 = _load_round39()

#: The eight cells, pre-registered. Written out rather than derived from `SLICES` so that a change to
#: the slice map breaks this list loudly instead of quietly redefining what the round is.
EXPECTED_AGENT_IDS = [
    "r39-core-ma",
    "r39-core-passive",
    "r39-full-ma",
    "r39-full-passive",
    "r39-growth-ma",
    "r39-growth-passive",
    "r39-value-ma",
    "r39-value-passive",
]


@pytest.fixture(scope="module")
def cards() -> list[StrategyCard]:
    return round39.build()


class TestFieldShape:
    def test_eight_cells(self, cards: list[StrategyCard]) -> None:
        """Four style slices x two arms (rule-driven tilt, passive control).

        Pinned as a number because the field size *is* the multiple-comparison denominator: every
        cell run enters the Benjamini-Hochberg correction (`PROTOCOL.md` section 3 rule 8), so a
        ninth cell appearing quietly would change what any q-value in this round means.
        """
        assert len(cards) == 8

    def test_agent_ids_are_the_pre_registered_set(self, cards: list[StrategyCard]) -> None:
        assert sorted(card.agent_id for card in cards) == EXPECTED_AGENT_IDS

    def test_the_slices_are_the_pre_registered_ones(self) -> None:
        assert round39.SLICES == {
            "value": ("VTV", "RSP", "MDY"),
            "growth": ("SPYG", "IBB"),
            "core": ("VTI", "TIP"),
            "full": ("VTV", "SPYG", "RSP", "MDY", "VTI", "IBB", "TIP"),
        }

    def test_every_cell_targets_the_same_capital_budget(self, cards: list[StrategyCard]) -> None:
        """`position_pct * max_positions == 0.84` everywhere, tilt arm and control arm alike, across
        slices of three, two and seven names.

        This is what makes a cross-slice comparison a question about *style* rather than about how
        much money is in the market, and what makes each control a like-for-like baseline rather than
        a differently-sized book. `PROTOCOL.md` section 4 flags any card whose exposure differs from
        the field median by more than 2x; holding the budget fixed is how this field stays clear of
        that flag by construction instead of by luck.
        """
        for card in cards:
            assert card.position_pct * card.max_positions == Decimal("0.84"), card.agent_id

    def test_every_card_has_a_slot_for_every_name(self, cards: list[StrategyCard]) -> None:
        """No slot contention anywhere in this field, which is why `rank_by` is unset on every card
        and why the `PROTOCOL.md` section 7 ordering artifact cannot operate in this round at all."""
        for card in cards:
            assert card.max_positions == len(card.universe), card.agent_id
            assert card.rank_by is None, card.agent_id

    def test_no_card_carries_a_bracket(self, cards: list[StrategyCard]) -> None:
        """A stop the control cannot have would make every `tilt - control` margin a joint
        measurement of the rule *plus* the stop. `PROTOCOL.md` section 7's one-decision rule is why
        both arms carry none -- see `ROUND-39-PLAN.md` section 3c."""
        for card in cards:
            assert card.stop_loss_pct is None, card.agent_id
            assert card.take_profit_pct is None, card.agent_id
            assert card.max_hold_days is None, card.agent_id

    def test_design_cutoff(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            assert card.designed_through == DESIGN_THROUGH
            assert card.desk_only is False
            assert card.reference_only is False

    def test_every_card_states_a_falsification_condition(
        self, cards: list[StrategyCard]
    ) -> None:
        for card in cards:
            assert card.falsification, card.agent_id

    def test_every_tilt_card_names_its_failure_regime(self, cards: list[StrategyCard]) -> None:
        """`PROTOCOL.md` section 3 rule 5: the regime a card hates, named before it trades, and
        carried in the card itself so the per-card reporter (section 2, phase 6) reads the same
        pre-registration the scorer does."""
        for card in cards:
            if card.agent_id.endswith("-ma"):
                slice_name = card.agent_id.removeprefix("r39-").removesuffix("-ma")
                _what, failure_regime = round39.SLICE_PROSE[slice_name]
                assert failure_regime in card.falsification, card.agent_id


class TestRothInvariant:
    """The Rev. Rul. 2008-5 boundary. An IRA replacement purchase destroys a wash-sale loss outright
    rather than deferring it, so a ticker shared between a roth card and a taxable one is not an
    untidiness -- it is a permanently lost deduction."""

    def test_every_card_is_roth(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            assert card.purpose is Purpose.ROTH, card.agent_id

    def test_the_pinned_pool_is_unchanged(self) -> None:
        assert round39.UNIVERSE == ("VTV", "SPYG", "RSP", "MDY", "VTI", "IBB", "TIP", "IAU")

    def test_every_universe_is_a_subset_of_the_pinned_pool(
        self, cards: list[StrategyCard]
    ) -> None:
        for card in cards:
            assert set(card.universe) <= set(round39.UNIVERSE), card.agent_id
            assert card.universe, card.agent_id

    def test_the_slices_cover_every_traded_name(self, cards: list[StrategyCard]) -> None:
        held = {symbol for card in cards for symbol in card.universe}
        assert held == set(round39.TRADED)
        assert set(round39.TRADED) == set(round39.UNIVERSE) - set(
            round39.EXCLUDED_SUBSTANTIAL_IDENTITY
        )

    def test_no_ticker_is_claimed_by_the_taxable_book(self) -> None:
        taxable, _others = round39.claimed_symbols()
        assert taxable, "the live library reported no taxable tickers at all -- the check is vacuous"
        assert set(round39.TRADED) & taxable == set()
        assert set(round39.UNIVERSE) & taxable == set()

    def test_find_disjointness_violations_reports_nothing(
        self, cards: list[StrategyCard]
    ) -> None:
        """The real check, run through the programme's own function rather than a set intersection
        rewritten here. Only the library's non-roth half is passed alongside this round's cards, so a
        pre-existing roth-vs-taxable violation elsewhere in the library cannot be attributed to round
        39 -- and cannot mask one either, since every roth card in the comparison is ours."""
        _taxable, others = round39.claimed_symbols()
        assert others, "no savings/trading cards found -- the check would pass vacuously"
        violations = find_disjointness_violations([*cards, *others])
        ours = {card.agent_id for card in cards}
        assert [v.message for v in violations if v.roth_agent_id in ours] == []


class TestSubstantialIdentityHoldout:
    """`IAU` is in the pinned pool and traded by nothing. See `ROUND-39-PLAN.md` section 2b."""

    def test_iau_is_held_out(self, cards: list[StrategyCard]) -> None:
        assert round39.EXCLUDED_SUBSTANTIAL_IDENTITY == ("IAU",)
        assert "IAU" in round39.UNIVERSE
        assert "IAU" not in round39.TRADED
        for card in cards:
            assert "IAU" not in card.universe, card.agent_id

    def test_the_taxable_book_still_holds_gld(self) -> None:
        """The hold-out's whole stated reason is that the taxable book holds `GLD`, physical gold
        against `IAU`'s physical gold. If `GLD` ever leaves the taxable book that reason is stale and
        the plan needs an amendment rather than a silent edit -- so this asserts the premise instead
        of trusting it."""
        taxable, _others = round39.claimed_symbols()
        assert "GLD" in taxable


class TestExpressionsParse:
    def test_entry_and_exit_parse(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            assert grammar.parse(card.entry) is not None, card.agent_id
            assert grammar.parse(card.exit) is not None, card.agent_id

    def test_no_card_sets_a_ranking_key(self, cards: list[StrategyCard]) -> None:
        """With a slot for every name there is nothing to rank. Any card that grew a `rank_by` would
        have grown slot contention with it, which this round deliberately does not have -- and the
        parse is asserted anyway, so a future edit that adds one is still checked."""
        ranked = [card for card in cards if card.rank_by is not None]
        assert ranked == []
        for card in ranked:  # pragma: no cover -- empty today, guards a future edit
            assert grammar.parse_ranking(card.rank_by) is not None, card.agent_id

    def test_the_one_rule_comes_from_ruleforms(self, cards: list[StrategyCard]) -> None:
        """Rendered by the evolution loop's own module, so this round holds the form constant *as the
        loop actually emits it* rather than as a second, drifting copy typed into the tool."""
        from app.evolution import ruleforms

        entry, exit_rule = ruleforms.render(
            "ma-crossover", fast=round39.FAST, slow=round39.SLOW, regime_ma=round39.REGIME
        )
        assert (round39.FAST, round39.SLOW, round39.REGIME) == (10, 30, 200)
        tilts = [card for card in cards if card.agent_id.endswith("-ma")]
        assert len(tilts) == 4
        for card in tilts:
            assert (card.entry, card.exit) == (entry, exit_rule), card.agent_id
            assert card.discipline == ruleforms.classify(entry, exit_rule), card.agent_id


class TestControlCards:
    """The within-slice passive baselines. Everything the round concludes is a comparison against
    these cards -- the rule margin within a slice and the style spread between slices -- so their
    shape is pinned rather than trusted."""

    @pytest.fixture
    def controls(self, cards: list[StrategyCard]) -> list[StrategyCard]:
        found = [card for card in cards if card.agent_id.endswith("-passive")]
        assert len(found) == 4
        return found

    def test_entry_is_always_true_and_exit_never_fires(
        self, controls: list[StrategyCard]
    ) -> None:
        for card in controls:
            assert card.entry == "close > 0", card.agent_id
            assert card.exit == "close < 0", card.agent_id

    def test_nothing_can_close_the_position_early(self, controls: list[StrategyCard]) -> None:
        for card in controls:
            assert card.stop_loss_pct is None, card.agent_id
            assert card.take_profit_pct is None, card.agent_id
            assert card.max_hold_days is None, card.agent_id

    def test_each_control_holds_its_whole_slice(self, controls: list[StrategyCard]) -> None:
        for card in controls:
            slice_name = card.agent_id.removeprefix("r39-").removesuffix("-passive")
            assert card.universe == round39.SLICES[slice_name], card.agent_id
            assert card.max_positions == len(card.universe), card.agent_id

    def test_the_full_control_holds_every_traded_name(
        self, controls: list[StrategyCard]
    ) -> None:
        """The brief's "one control holding all the names" card. It holds seven, not eight: `IAU` is
        held out of the whole round (`ROUND-39-PLAN.md` section 2b)."""
        card = next(c for c in controls if c.agent_id == "r39-full-passive")
        assert card.universe == round39.TRADED
        assert card.max_positions == len(round39.TRADED) == 7

    def test_each_tilt_cell_has_a_matching_control(self, cards: list[StrategyCard]) -> None:
        """`tilt - control` is only an attribution to the *rule* if the two differ in exactly one
        thing (`PROTOCOL.md` section 7). Same names, same slots, same size, same absent brackets."""
        by_id = {card.agent_id: card for card in cards}
        for slice_name in round39.SLICES:
            tilt = by_id[f"r39-{slice_name}-ma"]
            control = by_id[f"r39-{slice_name}-passive"]
            assert tilt.universe == control.universe
            assert tilt.max_positions == control.max_positions
            assert tilt.position_pct == control.position_pct
            assert (tilt.entry, tilt.exit) != (control.entry, control.exit)


class TestParameterBudget:
    def test_no_card_exceeds_ten_free_numbers(self, cards: list[StrategyCard]) -> None:
        """`PROTOCOL.md` section 3 rule 3: ten free numbers per card, counted across entry, exit, the
        two brackets, the hold cap, slot count and position size."""
        for card in cards:
            assert round39.free_numbers(card) <= 10, (
                f"{card.agent_id} spends {round39.free_numbers(card)}"
            )

    def test_the_fields_actual_maximum_is_five(self, cards: list[StrategyCard]) -> None:
        """Reported rather than merely allowed. A tilt cell spends 5 (`{200, 10, 30}` plus the slot
        count and the position size) and a control spends 3 (`{0}` plus the same two), so any later
        edit that adds a number to this field breaks a test rather than a margin."""
        assert max(round39.free_numbers(card) for card in cards) == 5
        for card in cards:
            expected = 5 if card.agent_id.endswith("-ma") else 3
            assert round39.free_numbers(card) == expected, card.agent_id


class TestDeterminism:
    def test_build_is_deterministic(self) -> None:
        first = round39.build()
        second = round39.build()
        assert [c.model_dump_json() for c in first] == [c.model_dump_json() for c in second]

    def test_order_is_stable(self) -> None:
        assert [c.agent_id for c in round39.build()] == [c.agent_id for c in round39.build()]


class TestOnDiskCardsRoundTrip:
    def test_written_cards_match_build(self, cards: list[StrategyCard]) -> None:
        out = round39.OUT
        if not out.is_dir():
            pytest.skip(f"{out} does not exist -- run round39.py --write to author the field")
        paths = sorted(out.glob("*.json"))
        assert len(paths) == len(cards)
        on_disk = {
            path.stem: StrategyCard.model_validate_json(path.read_text(encoding="utf-8"))
            for path in paths
        }
        for card in cards:
            assert card.agent_id in on_disk, card.agent_id
            assert on_disk[card.agent_id].model_dump_json() == card.model_dump_json()

    def test_purpose_serialises_as_roth(self) -> None:
        out = round39.OUT
        if not out.is_dir():
            pytest.skip(f"{out} does not exist -- run round39.py --write to author the field")
        for path in sorted(out.glob("*.json")):
            assert '"purpose": "roth"' in path.read_text(encoding="utf-8"), path.name

"""Tests for `strategy-program/tools/round35.py` -- round 35's country-rotation field.

`strategy-program` is not a legal Python package name (the hyphen), so `round35.py` is loaded by
file path here -- the identical precedent `tests/test_contributions.py`,
`strategy-program/tools/roth_voltarget.py` and `strategy-program/tools/savings_family.py` already
set for the same reason.

Every test here is fast and touches **no bar store**: the round's expensive claims (window
eligibility, guard causality) are settled by `strategy-program/tools/windows.py` and by the runner,
which need DuckDB. What this module pins is everything that can be wrong *before* a single bar is
read, and in particular the one invariant this round could break with real consequences:

* `TestFieldShape` -- nine cards, the eight rotation cells plus one control, with the pre-registered
  agent-id pattern and no duplicates.
* `TestRothInvariant` -- every card is `Purpose.ROTH`, every universe is the pinned tuple, no ticker
  intersects any `savings`- or `trading`-purpose card in the live library (strategy, allocation and
  ladder tiers alike), and `find_disjointness_violations` reports nothing when this round's cards are
  put in front of the library's non-roth half. This is the Rev. Rul. 2008-5 boundary -- an IRA
  replacement purchase *destroys* a wash-sale loss rather than deferring it -- and it is the reason
  this file exists at all.
* `TestExpressionsParse` -- every `entry` and `exit` parses with `app.rules.grammar.parse` and every
  non-`None` `rank_by` with `parse_ranking`, so a syntax error is a red test rather than a card the
  runner walks past mid-round (`PROTOCOL.md` section 8).
* `TestControlCard` -- the passive control really is passive: an always-true entry, a never-true
  exit, no brackets, and all eight slots. If any of that drifts, every comparison round 35 draws
  against it is void, and the round's only defence against the SPY-benchmark confound goes with it.
* `TestParameterBudget` -- no card spends more than PROTOCOL section 3's ten free numbers.
* `TestDeterminism` -- `build()` called twice returns field-identical cards. A generated field that
  moved between the dry run and the `--write` would mean the frozen cards are not the ones whose
  properties were checked.
* `TestOnDiskCardsRoundTrip` -- the JSON actually written under `data/rounds/r35-2026-09/cards/`
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
TOOL = REPO / "strategy-program" / "tools" / "round35.py"


def _load_round35():
    spec = importlib.util.spec_from_file_location("round35_tool", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["round35_tool"] = module
    spec.loader.exec_module(module)
    return module


round35 = _load_round35()


@pytest.fixture(scope="module")
def cards() -> list[StrategyCard]:
    return round35.build()


class TestFieldShape:
    def test_nine_cells(self, cards: list[StrategyCard]) -> None:
        """Eight rotation cells (2 forms x 2 slot caps x 2 fill orders) plus one passive control.

        Pinned as a number because the field size *is* the multiple-comparison denominator: every
        cell run enters the Benjamini-Hochberg correction (`PROTOCOL.md` section 3 rule 8), so a
        tenth cell appearing quietly would change what any q-value in this round means.
        """
        assert len(cards) == 9

    def test_agent_ids_are_the_pre_registered_set(self, cards: list[StrategyCard]) -> None:
        assert sorted(card.agent_id for card in cards) == [
            "r35-absolute-2-order",
            "r35-absolute-2-rank",
            "r35-absolute-4-order",
            "r35-absolute-4-rank",
            "r35-macross-2-order",
            "r35-macross-2-rank",
            "r35-macross-4-order",
            "r35-macross-4-rank",
            "r35-passive-8-order",
        ]

    def test_every_cell_targets_the_same_capital_budget(self, cards: list[StrategyCard]) -> None:
        """`position_pct * max_positions == 0.88` everywhere, control included.

        This is what makes the slot-cap factor a question about *concentration* rather than about
        how much money is in the market, and what makes the control a like-for-like baseline rather
        than a differently-sized book. `PROTOCOL.md` section 4 flags any card whose exposure differs
        from the field median by more than 2x; holding the budget fixed is how this field stays
        clear of that flag by construction instead of by luck.
        """
        for card in cards:
            assert card.position_pct * card.max_positions == Decimal("0.88"), card.agent_id

    def test_brackets_are_identical_across_every_rotation_cell(
        self, cards: list[StrategyCard]
    ) -> None:
        """Brackets belong to neither form's definition, so they are held fixed -- otherwise a
        difference between the two forms could not be attributed to the form."""
        rotation = [c for c in cards if not c.agent_id.startswith("r35-passive")]
        assert len(rotation) == 8
        for card in rotation:
            assert card.stop_loss_pct == Decimal("0.10"), card.agent_id
            assert card.take_profit_pct is None, card.agent_id
            assert card.max_hold_days == 150, card.agent_id

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


class TestRothInvariant:
    """The Rev. Rul. 2008-5 boundary. An IRA replacement purchase destroys a wash-sale loss outright
    rather than deferring it, so a ticker shared between a roth card and a taxable one is not an
    untidiness -- it is a permanently lost deduction."""

    def test_every_card_is_roth(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            assert card.purpose is Purpose.ROTH, card.agent_id

    def test_every_universe_is_the_pinned_tuple(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            assert card.universe == round35.UNIVERSE, card.agent_id
        assert round35.UNIVERSE == ("EWJ", "EWG", "EWU", "EWC", "EWY", "ILF", "EFA", "VWO")

    def test_no_ticker_is_claimed_by_the_taxable_book(self) -> None:
        taxable, _others = round35.claimed_symbols()
        assert taxable, "the live library reported no taxable tickers at all -- the check is vacuous"
        assert set(round35.UNIVERSE) & taxable == set()

    def test_the_excluded_names_really_are_taxable_claimed(self) -> None:
        """`EEM`, `EWZ`, `FXI` and `INDA` belong in a country-rotation universe on the merits and are
        out on the invariant alone. If they ever stop being taxable-claimed, that exclusion is stale
        and the universe should be revisited -- by an amendment to the plan, not silently."""
        taxable, _others = round35.claimed_symbols()
        assert set(round35.EXCLUDED_TAXABLE_CLAIMED) <= taxable

    def test_find_disjointness_violations_reports_nothing(
        self, cards: list[StrategyCard]
    ) -> None:
        """The real check, run through the programme's own function rather than a set intersection
        rewritten here. Only the library's non-roth half is passed alongside this round's cards, so
        a pre-existing roth-vs-taxable violation elsewhere in the library cannot be attributed to
        round 35 -- and cannot mask one either, since every roth card in the comparison is ours."""
        _taxable, others = round35.claimed_symbols()
        assert others, "no savings/trading cards found -- the check would pass vacuously"
        assert find_disjointness_violations([*cards, *others]) == ()


class TestExpressionsParse:
    def test_entry_and_exit_parse(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            assert grammar.parse(card.entry) is not None, card.agent_id
            assert grammar.parse(card.exit) is not None, card.agent_id

    def test_ranking_keys_parse(self, cards: list[StrategyCard]) -> None:
        ranked = [card for card in cards if card.rank_by is not None]
        assert len(ranked) == 4, "four cells were pre-registered with a stated chooser"
        for card in ranked:
            assert card.rank_by == "close / sma(200)"
            assert grammar.parse_ranking(card.rank_by) is not None, card.agent_id

    def test_the_absolute_form_is_c20s_filter_verbatim(self, cards: list[StrategyCard]) -> None:
        """Transplanted, not re-authored. A re-tuned version of c20's filter would answer a
        different question from the one this round pre-registered."""
        card = next(c for c in cards if c.agent_id == "r35-absolute-2-order")
        assert card.entry == "close > sma(100) and rsi(14) > 50 and rsi(14) < 75"
        assert card.exit == "close < sma(100) or rsi(14) < 40"

    def test_the_crossover_form_comes_from_ruleforms(self, cards: list[StrategyCard]) -> None:
        """Rendered by the evolution loop's own module, so this round compares the form as the loop
        actually emits it rather than a second, drifting copy typed into the tool."""
        from app.evolution import ruleforms

        entry, exit_rule = ruleforms.render("ma-crossover", fast=10, slow=30, regime_ma=200)
        card = next(c for c in cards if c.agent_id == "r35-macross-4-rank")
        assert (card.entry, card.exit) == (entry, exit_rule)


class TestControlCard:
    """The within-universe passive baseline. Everything the round concludes is a comparison against
    this card, so its shape is pinned rather than trusted."""

    @pytest.fixture
    def control(self, cards: list[StrategyCard]) -> StrategyCard:
        return next(c for c in cards if c.agent_id == "r35-passive-8-order")

    def test_entry_is_always_true_and_exit_never_fires(self, control: StrategyCard) -> None:
        assert control.entry == "close > 0"
        assert control.exit == "close < 0"

    def test_nothing_can_close_the_position_early(self, control: StrategyCard) -> None:
        assert control.stop_loss_pct is None
        assert control.take_profit_pct is None
        assert control.max_hold_days is None

    def test_it_holds_the_whole_universe(self, control: StrategyCard) -> None:
        assert control.max_positions == len(round35.UNIVERSE) == 8
        assert control.rank_by is None, "with a slot for every name there is nothing to rank"


class TestParameterBudget:
    def test_no_card_exceeds_ten_free_numbers(self, cards: list[StrategyCard]) -> None:
        """`PROTOCOL.md` section 3 rule 3: ten free numbers per card, counted across entry, exit, the
        two brackets, the hold cap, slot count and position size."""
        for card in cards:
            assert round35.free_numbers(card) <= 10, (
                f"{card.agent_id} spends {round35.free_numbers(card)}"
            )

    def test_the_ranked_absolute_cells_sit_exactly_at_the_budget(
        self, cards: list[StrategyCard]
    ) -> None:
        """Reported rather than merely allowed: `r35-absolute-*-rank` spends all ten, so any future
        edit that adds a number to those cells breaks the constitution rather than the margin."""
        card = next(c for c in cards if c.agent_id == "r35-absolute-4-rank")
        assert round35.free_numbers(card) == 10


class TestDeterminism:
    def test_build_is_deterministic(self) -> None:
        first = round35.build()
        second = round35.build()
        assert [c.model_dump_json() for c in first] == [c.model_dump_json() for c in second]

    def test_order_is_stable(self) -> None:
        assert [c.agent_id for c in round35.build()] == [
            c.agent_id for c in round35.build()
        ]


class TestOnDiskCardsRoundTrip:
    def test_written_cards_match_build(self, cards: list[StrategyCard]) -> None:
        out = round35.OUT
        if not out.is_dir():
            pytest.skip(f"{out} does not exist -- run round35.py --write to author the field")
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
        out = round35.OUT
        if not out.is_dir():
            pytest.skip(f"{out} does not exist -- run round35.py --write to author the field")
        for path in sorted(out.glob("*.json")):
            assert '"purpose": "roth"' in path.read_text(encoding="utf-8"), path.name

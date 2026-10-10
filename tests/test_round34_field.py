"""Tests for `strategy-program/tools/round34.py`'s pre-registered round-34 field.

`strategy-program` is not a legal Python package name (the hyphen), so `round34.py` is loaded by file
path here -- the identical precedent `tests/test_contributions.py`,
`strategy-program/tools/roth_voltarget.py` and `strategy-program/tools/savings_family.py` already set
for the same reason.

Each test pins one claim `strategy-program/ROUND-34-PLAN.md` makes about the field:

* `TestFieldShape` -- 16 cards, one per (form, regime arm), with the agent-id pattern the plan's §2
  states and no cell silently skipped.
* `TestPurposeAndUniverse` -- every card is `Purpose.ROTH` and every universe is the pinned tuple,
  byte for byte and in order. The tuple is pinned because round 36 reuses it (§2b); a test that only
  checked set equality would let the order drift and take the tie-break ordering with it.
* `TestDisjointFromTaxableResearch` -- §3's binding constraint, three ways: no ticker intersects the
  taxable roster computed from the live library, `find_disjointness_violations` reports nothing
  against that library, and the tool's own `--write` refusal path actually fires when a taxable
  ticker is planted in the field (so the guard is non-vacuous rather than merely never triggered).
* `TestRulesParse` -- every `entry` and `exit` parses with `app.rules.grammar.parse`, and the
  regime-off arm really has had the `close > sma(200)` conjunct removed from its entry rather than
  approximated.
* `TestDeterminism` -- two `build()` calls produce identical model dumps, which is what §9 claims and
  what makes the frozen cards reproducible from the tool.
* `TestWrittenCardsRoundTrip` -- if `--write` has been run, every file on disk round-trips through
  `StrategyCard.model_validate_json` and matches what `build()` produces today. Skipped rather than
  failed when the directory is absent, because authoring the field is a separate, deliberate step.
* `TestParameterBudget` -- `PROTOCOL.md` §3 rule 3's ten-free-numbers budget, counted the strict way
  (every numeric literal in entry, exit, brackets, hold cap, slot count and position size), so the
  plan's "7 free, at most 9 counting every literal" claim is checked rather than asserted.

None of these touches the bar store: the field is authored from `app.evolution.ruleforms` and checked
against the library JSON, both of which are pure reads of code and files. Window eligibility is a
question about the store and belongs to `strategy-program/tools/windows.py`, which the round's
definition-of-done runs separately.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

from app.evolution.models import RULE_SHAPES
from app.rules import grammar
from app.tournament.models import DESIGN_THROUGH, StrategyCard
from app.tournament.purposes import Purpose, find_disjointness_violations

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "strategy-program" / "tools" / "round34.py"


def _load_tool():
    """`round34.py` as a module, loaded by file path (see this module's docstring)."""
    spec = importlib.util.spec_from_file_location("round34", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["round34"] = module
    spec.loader.exec_module(module)
    return module


round34 = _load_tool()


@pytest.fixture(scope="module")
def cards() -> list[StrategyCard]:
    built, skipped = round34.build()
    assert skipped == [], f"no cell should be skipped, got: {skipped}"
    return built


@pytest.fixture(scope="module")
def library():
    return round34.library_purposed_cards()


class TestFieldShape:
    def test_sixteen_cells(self, cards: list[StrategyCard]) -> None:
        assert len(cards) == 16
        assert len(RULE_SHAPES) == 8

    def test_one_card_per_form_and_regime_arm(self, cards: list[StrategyCard]) -> None:
        expected = {f"r34-{shape}-{arm}" for shape in RULE_SHAPES for arm in ("on", "off")}
        assert {card.agent_id for card in cards} == expected

    def test_agent_ids_are_unique(self, cards: list[StrategyCard]) -> None:
        ids = [card.agent_id for card in cards]
        assert len(set(ids)) == len(ids)

    def test_fixed_parameters_are_actually_fixed(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            assert card.max_positions == round34.MAX_POSITIONS == 4
            assert card.position_pct == round34.POSITION_PCT
            assert card.stop_loss_pct == round34.BRACKET["stop_loss_pct"]
            assert card.take_profit_pct is None
            assert card.max_hold_days == round34.BRACKET["max_hold_days"]
            assert card.designed_through == DESIGN_THROUGH
            assert card.rank_by is None

    def test_every_card_states_a_falsification(self, cards: list[StrategyCard]) -> None:
        # PROTOCOL.md section 3 rule 5: the failure regime is named before the card trades.
        for card in cards:
            assert card.falsification
            assert re.search(r"`(chop|gfc|covid|bear)-?\w*`", card.falsification), (
                f"{card.agent_id} names no window in its failure regime"
            )


class TestPurposeAndUniverse:
    def test_every_card_is_roth(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            assert card.purpose is Purpose.ROTH

    def test_purpose_serialises_as_roth(self, cards: list[StrategyCard]) -> None:
        # The JSON key the frozen cards carry, which is what every downstream loader reads.
        assert '"purpose": "roth"' in cards[0].model_dump_json(indent=2)

    def test_universe_is_the_pinned_tuple(self, cards: list[StrategyCard]) -> None:
        pinned = ("XME", "XRT", "XHB", "XSD", "XOP", "XBI", "ITA", "VNQ")
        assert tuple(round34.UNIVERSE) == pinned
        for card in cards:
            # Order, not just membership: round 36 reuses this tuple, and with `rank_by` unset the
            # write order is the slot tie-break (ROUND-34-PLAN.md section 2c).
            assert card.universe == pinned

    def test_ibb_is_excluded_and_the_reason_is_recorded(self) -> None:
        assert "IBB" in round34.EXCLUDED_FOR_DUPLICATION
        assert "IBB" not in round34.UNIVERSE
        assert "XBI" in round34.UNIVERSE


class TestDisjointFromTaxableResearch:
    def test_no_ticker_intersects_the_taxable_roster(self, cards, library) -> None:
        taxable = round34.taxable_symbols(library)
        assert taxable, "the library should hold at least one savings/trading card"
        for card in cards:
            assert not (set(card.universe) & taxable), (
                f"{card.agent_id} intersects the taxable book: "
                f"{sorted(set(card.universe) & taxable)}"
            )

    def test_find_disjointness_violations_reports_nothing_for_this_round(
        self, cards, library
    ) -> None:
        mine, _pre_existing = round34.check_disjointness(cards, library)
        assert mine == (), [violation.message for violation in mine]

        # And the same thing again through the library function directly, not through the tool's
        # wrapper -- so a bug in `check_disjointness`'s own filtering cannot make this test pass.
        mine_ids = {card.agent_id for card in cards}
        direct = find_disjointness_violations([*library, *cards])
        assert [v.message for v in direct if v.roth_agent_id in mine_ids] == []

    def test_the_check_covers_allocation_and_ladder_tiers(self, library) -> None:
        # `load_library()` reads four tiers and misses `allocation/` and `ladder/`, which is where
        # SCHD/SGOV/AGG/BIL/QLD/IEF live. If this ever regresses to `load_library()` alone the
        # invariant silently weakens, so pin that those symbols are in the roster being checked.
        taxable = round34.taxable_symbols(library)
        assert {"SCHD", "SGOV"} <= taxable

    def test_the_guard_is_non_vacuous(self, library) -> None:
        # Plant a taxable ticker in a roth card and confirm the check fires. Without this, all the
        # test above proves is that `find_disjointness_violations` was called, not that it can fail.
        taxable = sorted(round34.taxable_symbols(library))
        planted = StrategyCard(
            agent_id="r34-planted-violation",
            display_name="planted",
            discipline="trend",
            purpose=Purpose.ROTH,
            thesis="A deliberately invalid card, used only to prove the disjointness guard fires.",
            universe=(taxable[0],),
            entry="close > sma(200)",
            exit="close < sma(200)",
            max_positions=1,
            position_pct="0.10",
            designed_through=DESIGN_THROUGH,
        )
        mine, _ = round34.check_disjointness([planted], library)
        assert mine, "planting a taxable ticker in a roth card produced no violation"
        assert mine[0].symbol == taxable[0]


class TestRulesParse:
    def test_every_entry_and_exit_parses(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            grammar.parse(card.entry)
            grammar.parse(card.exit)

    def test_regime_arms_differ_by_exactly_the_conjunct(self, cards: list[StrategyCard]) -> None:
        by_id = {card.agent_id: card for card in cards}
        for shape in RULE_SHAPES:
            on = by_id[f"r34-{shape}-on"]
            off = by_id[f"r34-{shape}-off"]
            assert round34.REGIME_CLAUSE in on.entry
            assert round34.REGIME_CLAUSE not in off.entry
            # Same form, so the exit is untouched by the factor -- including `vol-compression`'s,
            # which names sma(200) itself. See `strip_regime`'s docstring.
            assert on.exit == off.exit
            assert round34.strip_regime(on.entry) == off.entry


class TestDeterminism:
    def test_two_builds_are_identical(self) -> None:
        first, first_skipped = round34.build()
        second, second_skipped = round34.build()
        assert first_skipped == second_skipped
        assert [card.model_dump_json() for card in first] == [
            card.model_dump_json() for card in second
        ]

    def test_build_order_is_stable(self) -> None:
        first, _ = round34.build()
        second, _ = round34.build()
        assert [card.agent_id for card in first] == [card.agent_id for card in second]


class TestWrittenCardsRoundTrip:
    def test_files_on_disk_match_the_tool(self, cards: list[StrategyCard]) -> None:
        out = round34.OUT
        if not out.is_dir():
            pytest.skip(f"{out} does not exist -- run round34.py --write to author the field")
        paths = sorted(out.glob("*.json"))
        assert len(paths) == len(cards)
        on_disk = {
            path.stem: StrategyCard.model_validate_json(path.read_text(encoding="utf-8"))
            for path in paths
        }
        for card in cards:
            assert card.agent_id in on_disk, f"{card.agent_id}.json is missing from {out}"
            assert on_disk[card.agent_id].model_dump_json() == card.model_dump_json()


class TestParameterBudget:
    #: Every numeric literal in a rule, including the structural constants `ruleforms.py` freezes.
    #: The strict count, so the plan's claim is checked at its own most conservative reading.
    _NUMBER = re.compile(r"\d+(?:\.\d+)?")

    def test_at_most_ten_free_numbers_per_card(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            literals = set(self._NUMBER.findall(card.entry)) | set(
                self._NUMBER.findall(card.exit)
            )
            # Brackets, hold cap, slot count and position size, per PROTOCOL.md section 3 rule 3.
            sized = {
                str(card.stop_loss_pct),
                str(card.max_hold_days),
                str(card.max_positions),
                str(card.position_pct),
            }
            assert len(literals | sized) <= 10, (
                f"{card.agent_id} spends {len(literals | sized)} numbers: "
                f"{sorted(literals | sized)}"
            )

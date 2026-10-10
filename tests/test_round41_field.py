"""Tests for `strategy-program/tools/round41.py`'s pre-registered confirmation-stacking field.

`strategy-program` is not a legal Python package name (the hyphen), so `round41.py` is loaded by file
path here -- the identical precedent `tests/test_round34_field.py` and `tests/test_contributions.py`
already set for the same reason.

This round was briefed and authored as round 38; a concurrent session held that number for a macro
allocation round, so it moved to the next free one. See `round41.py`'s module docstring.

Each test pins one claim `strategy-program/ROUND-41-PLAN.md` makes about the field:

* `TestFieldShape` -- six cards, one per confirmation-gate arm, agent ids as the plan's §2 table
  states, every card `purpose = trading` with a stated falsification.
* `TestBaseIsC18` -- §2a's binding claim: entry base, exit, both brackets, hold cap, slots, sizing,
  `rank_by`, `purpose` and the universe **including its order** are `c18-meanrev`'s, and the
  build-time drift check that enforces it is non-vacuous.
* `TestGateAlgebra` -- §2b/§2c: each arm's entry is exactly the base with its gate ANDed on; the two
  half-arms are the *literal* conjuncts of `divergence(10)`; the three divergence arms differ only in
  the lookback; the identifier that selects the RSI-at-swing **low** output is
  `rsi_at_swing_low(period, lookback)` and resolves through the real registry rather than merely
  parsing.
* `TestRulesParse` -- every `entry` and `exit` parses with `app.rules.grammar.parse`.
* `TestDisjointFromTheRothBook` -- §3, three ways: no ticker intersects the Roth roster computed from
  the live library, `find_disjointness_violations` reports nothing against that library, and the
  refusal path actually fires when a Roth ticker is planted in the field.
* `TestParameterBudget` -- `PROTOCOL.md` §3 rule 3's ten-free-numbers budget, counted both the tool's
  way (choices) and the strict way (every numeric literal), so §2d's claim is checked not asserted.
* `TestDeterminism` -- two `build()` calls produce identical model dumps, which is what §11 claims and
  what makes the frozen cards reproducible from the tool.
* `TestWrittenCardsRoundTrip` -- if `--write` has been run, every file on disk round-trips through
  `StrategyCard.model_validate_json` and matches what `build()` produces today.

None of these touches the bar store: the field is authored from literals and checked against library
JSON. The guard rehearsal and the signal-density table are store reads and belong to the tool's own
dry run, which the round's definition-of-done runs separately -- a test that hit the store would make
this file fail on a fresh checkout for a reason that has nothing to do with the field.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from app.rules import grammar
from app.rules.nodes import Comparison, IndicatorRef
from app.tournament.models import DESIGN_THROUGH, Discipline, StrategyCard
from app.tournament.purposes import Purpose, find_disjointness_violations

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "strategy-program" / "tools" / "round41.py"


def _load_tool():
    """`round41.py` as a module, loaded by file path (see this module's docstring)."""
    spec = importlib.util.spec_from_file_location("round41", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["round41"] = module
    spec.loader.exec_module(module)
    return module


round41 = _load_tool()

#: The six arms the plan's §2 table names, in the order it lists them.
EXPECTED_IDS = (
    "r41-control",
    "r41-struct-lb10",
    "r41-mom-lb10",
    "r41-div-lb5",
    "r41-div-lb10",
    "r41-div-lb20",
)


@pytest.fixture(scope="module")
def cards() -> list[StrategyCard]:
    return round41.build()


@pytest.fixture(scope="module")
def by_id(cards: list[StrategyCard]) -> dict[str, StrategyCard]:
    return {card.agent_id: card for card in cards}


@pytest.fixture(scope="module")
def library():
    return round41.library_cards()


class TestFieldShape:
    def test_six_cells_in_the_plans_order(self, cards: list[StrategyCard]) -> None:
        assert len(cards) == 6
        assert tuple(card.agent_id for card in cards) == EXPECTED_IDS

    def test_agent_ids_are_unique(self, cards: list[StrategyCard]) -> None:
        ids = [card.agent_id for card in cards]
        assert len(set(ids)) == len(ids)

    def test_every_card_is_a_trading_card(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            assert card.purpose is Purpose.TRADING
        assert '"purpose": "trading"' in cards[0].model_dump_json(indent=2)

    def test_every_card_is_mean_reversion(self, cards: list[StrategyCard]) -> None:
        # The gate does not change the school the base rule works in.
        for card in cards:
            assert card.discipline is Discipline.MEAN_REVERSION

    def test_the_hold_cap_respects_the_trading_mandate(self, cards: list[StrategyCard]) -> None:
        # The round brief's ceiling, and far inside `Purpose.TRADING`'s nine-month horizon.
        for card in cards:
            assert card.max_hold_days is not None
            assert card.max_hold_days <= 150

    def test_every_card_states_a_falsification(self, cards: list[StrategyCard]) -> None:
        # PROTOCOL.md section 3 rule 5: the failure regime is named before the card trades.
        for card in cards:
            assert card.falsification
            assert "`bear-2022`" in card.falsification and "`gfc`" in card.falsification

    def test_only_the_control_carries_the_reproduction_falsification(
        self, by_id: dict[str, StrategyCard]
    ) -> None:
        control = by_id["r41-control"]
        assert "c18-meanrev" in (control.falsification or "")
        for agent_id in EXPECTED_IDS[1:]:
            assert "21.2pp" in (by_id[agent_id].falsification or "")


class TestBaseIsC18:
    def test_the_build_time_identity_check_passes(self) -> None:
        assert round41.check_base_matches_c18() == []

    def test_the_identity_check_is_non_vacuous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Without this, all the test above proves is that the function was called, not that it can
        # fail. Move the stop by one basis point and the check must name that field.
        monkeypatch.setattr(round41, "STOP_LOSS_PCT", Decimal("0.0801"))
        diffs = round41.check_base_matches_c18()
        assert diffs and any(diff.startswith("stop_loss_pct:") for diff in diffs)

    def test_every_card_carries_c18s_fixed_fields(self, cards: list[StrategyCard]) -> None:
        c18 = round41.c18()
        for card in cards:
            assert card.exit == c18.exit
            assert card.stop_loss_pct == c18.stop_loss_pct
            assert card.take_profit_pct is None
            assert c18.take_profit_pct is None
            assert card.max_hold_days == c18.max_hold_days
            assert card.max_positions == c18.max_positions
            assert card.position_pct == c18.position_pct
            assert card.rank_by is None
            assert c18.rank_by is None
            assert card.designed_through == DESIGN_THROUGH

    def test_the_universe_is_c18s_in_c18s_order(self, cards: list[StrategyCard]) -> None:
        c18 = round41.c18()
        pinned = ("JNJ", "MRK", "PG", "KO", "PEP", "CL", "XOM", "CVX", "MMM", "WMT")
        assert pinned == round41.UNIVERSE
        assert c18.universe == pinned
        for card in cards:
            # Order, not just membership: `rank_by` is unset, so the write order is the slot
            # tie-break, and PROTOCOL.md section 7 prices that at sigma = 21.2 points.
            assert card.universe == pinned

    def test_the_control_entry_is_c18s_entry_verbatim(
        self, by_id: dict[str, StrategyCard]
    ) -> None:
        assert by_id["r41-control"].entry == round41.c18().entry


class TestGateAlgebra:
    def test_each_entry_is_the_base_with_its_gate_anded_on(
        self, by_id: dict[str, StrategyCard]
    ) -> None:
        for slug, gate, _label in round41.ARMS:
            card = by_id[f"r41-{slug}"]
            expected = (
                round41.BASE_ENTRY if gate is None else f"{round41.BASE_ENTRY} and {gate}"
            )
            assert card.entry == expected

    def test_only_the_control_has_no_gate(self) -> None:
        gateless = [slug for slug, gate, _label in round41.ARMS if gate is None]
        assert gateless == ["control"]

    def test_the_halves_are_the_literal_conjuncts_of_the_divergence(self) -> None:
        # ROUND-41-PLAN.md section 2c: "does the divergence beat both of its halves" is only a
        # decomposition if the halves really are its conjuncts, character for character.
        lb = round41.HEADLINE_LOOKBACK
        divergence = round41.divergence(lb)
        assert divergence == f"{round41.structure_half(lb)} and {round41.momentum_half(lb)}"
        gates = {slug: gate for slug, gate, _label in round41.ARMS}
        assert gates["struct-lb10"] == round41.structure_half(lb)
        assert gates["mom-lb10"] == round41.momentum_half(lb)
        assert gates["div-lb10"] == divergence

    def test_the_three_divergence_arms_differ_only_in_the_lookback(self) -> None:
        gates = {slug: gate for slug, gate, _label in round41.ARMS}
        for lookback in (5, 10, 20):
            assert gates[f"div-lb{lookback}"] == round41.divergence(lookback)

    def test_the_rsi_at_swing_identifier_selects_the_low_output(self) -> None:
        # The one identifier this round had to verify rather than assume: `rsi_at_swing_low` must
        # resolve to the registered `rsi_at_swing` indicator's `low` output, not to some other
        # indicator and not to a parse that merely happens to succeed.
        tree = grammar.parse(round41.momentum_half(round41.HEADLINE_LOOKBACK))
        assert isinstance(tree, Comparison)
        right = tree.right
        assert isinstance(right, IndicatorRef)
        assert right.name == "rsi_at_swing"
        assert right.output == "low"
        assert right.args == (float(round41.GATE_RSI_PERIOD), float(round41.HEADLINE_LOOKBACK))

    def test_swing_low_resolves_to_the_swing_indicators_low_output(self) -> None:
        tree = grammar.parse(round41.structure_half(round41.HEADLINE_LOOKBACK))
        assert isinstance(tree, Comparison)
        right = tree.right
        assert isinstance(right, IndicatorRef)
        assert right.name == "swing"
        assert right.output == "low"

    def test_both_halves_of_a_divergence_reference_the_same_pivot(self) -> None:
        # `app.indicators.swing`: the companion series is anchored to the *price* pivot, so the two
        # halves only refer to the same instant if they carry the same lookback. A mismatch here
        # would make the expression mean something other than divergence while still parsing.
        for lookback in (5, 10, 20):
            found = re.findall(
                r"swing(?:_low)?\((?:\d+,\s*)?(\d+)\)", round41.divergence(lookback)
            )
            assert found == [str(lookback), str(lookback)]


class TestRulesParse:
    def test_every_entry_and_exit_parses(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            grammar.parse(card.entry)
            grammar.parse(card.exit)

    def test_the_tools_own_parse_rehearsal_covers_every_arm(self) -> None:
        notes = round41.parse_rehearsal()
        assert len(notes) == len(round41.ARMS) + 1  # every entry, plus the shared exit
        for slug, _gate, _label in round41.ARMS:
            assert any(note.startswith(f"{slug}: ") for note in notes)


class TestDisjointFromTheRothBook:
    def test_no_ticker_intersects_the_roth_roster(self, cards, library) -> None:
        roth = round41.roth_symbols(library)
        assert roth, "the library should hold at least one roth card"
        for card in cards:
            assert not (set(card.universe) & roth), (
                f"{card.agent_id} intersects the roth book: {sorted(set(card.universe) & roth)}"
            )

    def test_find_disjointness_violations_reports_nothing_for_this_round(
        self, cards, library
    ) -> None:
        mine, _pre_existing = round41.check_disjointness(cards, library)
        assert mine == (), [violation.message for violation in mine]

        # And again through the library function directly, so a bug in `check_disjointness`'s own
        # filtering cannot be what makes this pass.
        mine_ids = {card.agent_id for card in cards}
        direct = find_disjointness_violations([*library, *cards])
        assert [v.message for v in direct if v.other_agent_id in mine_ids] == []

    def test_the_check_covers_the_allocation_and_ladder_tiers(self, library) -> None:
        # `load_library()` reads four tiers and misses `allocation/` and `ladder/`. Those tiers are
        # taxable-side for this round rather than roth-side, so pin the roster size rather than two
        # tickers: if the walk ever regresses to `load_library()` alone, this count drops.
        four_tiers = [card for tier in round41.load_library().values() for card in tier]
        assert len(library) > len(four_tiers)

    def test_the_guard_is_non_vacuous(self, library) -> None:
        # Plant a roth ticker in one of this round's (trading-purpose) cards and confirm the check
        # fires from the taxable side, which is the direction this round runs in.
        roth = sorted(round41.roth_symbols(library))
        planted = StrategyCard(
            agent_id="r41-planted-violation",
            display_name="planted",
            discipline=Discipline.MEAN_REVERSION,
            purpose=Purpose.TRADING,
            thesis="A deliberately invalid card, used only to prove the disjointness guard fires.",
            universe=(roth[0],),
            entry="close > sma(200)",
            exit="close < sma(200)",
            max_positions=1,
            position_pct="0.10",
            designed_through=DESIGN_THROUGH,
        )
        mine, _ = round41.check_disjointness([planted], library)
        assert mine, "planting a roth ticker in a trading card produced no violation"
        assert mine[0].symbol == roth[0]
        assert mine[0].other_agent_id == "r41-planted-violation"


class TestParameterBudget:
    #: Every numeric literal in a rule. The strict count, so §2d's claim is checked at its own most
    #: conservative reading rather than only at the tool's "count decisions" reading.
    _NUMBER = re.compile(r"\d+(?:\.\d+)?")

    def test_the_tools_own_count_is_at_most_ten(self) -> None:
        for _slug, gate, _label in round41.ARMS:
            assert round41.free_number_count(gate) <= 10

    def test_the_counts_match_the_plans_table(self) -> None:
        expected = {
            "control": 8,
            "struct-lb10": 9,
            "mom-lb10": 10,
            "div-lb5": 10,
            "div-lb10": 10,
            "div-lb20": 10,
        }
        for slug, gate, _label in round41.ARMS:
            assert round41.free_number_count(gate) == expected[slug], slug

    def test_at_most_ten_free_numbers_per_card_counted_strictly(
        self, cards: list[StrategyCard]
    ) -> None:
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


class TestDeterminism:
    def test_two_builds_are_identical(self) -> None:
        first = round41.build()
        second = round41.build()
        assert [card.model_dump_json() for card in first] == [
            card.model_dump_json() for card in second
        ]

    def test_build_order_is_stable(self) -> None:
        assert [card.agent_id for card in round41.build()] == [
            card.agent_id for card in round41.build()
        ]


class TestWrittenCardsRoundTrip:
    def test_files_on_disk_match_the_tool(self, cards: list[StrategyCard]) -> None:
        out = round41.OUT
        if not out.is_dir():
            pytest.skip(f"{out} does not exist -- run round41.py --write to author the field")
        paths = sorted(out.glob("*.json"))
        assert len(paths) == len(cards)
        on_disk = {
            path.stem: StrategyCard.model_validate_json(path.read_text(encoding="utf-8"))
            for path in paths
        }
        for card in cards:
            assert card.agent_id in on_disk, f"{card.agent_id}.json is missing from {out}"
            assert on_disk[card.agent_id].model_dump_json() == card.model_dump_json()

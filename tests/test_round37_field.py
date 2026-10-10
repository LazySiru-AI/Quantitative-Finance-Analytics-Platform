"""Tests for `strategy-program/tools/round37.py`'s pre-registered round-37 field.

`strategy-program` is not a legal Python package name (the hyphen), so `round37.py` is loaded by file
path here -- the identical precedent `tests/test_round34_field.py`, `tests/test_contributions.py` and
`strategy-program/tools/savings_family.py` already set for the same reason.

Each test pins one claim `strategy-program/ROUND-37-PLAN.md` makes about the field:

* `TestFieldShape` -- 12 cards, one per (entry structure, exit, regime arm), with the agent-id
  pattern the plan's §2 states, and the fixed parameters actually fixed.
* `TestMandate` -- the 150-session hold cap really does sit inside the nine-month `trading` mandate
  (`PurposeSpec.horizon_months_max`), which is the constraint that made this round pick 150 over
  round 17's 180. A comment saying so would rot; this does not.
* `TestEntryStructure` -- the three entry structures are what the round says they are: `double` names
  both bands, `outer` only the 20/2 band, `inner` only the 4/4 band, and the regime arms differ by
  exactly the `close > sma(200)` prefix and nothing else.
* `TestUniverse` -- the pinned tuple equals `app.evolution.universe._TAXABLE_GROWTH` byte for byte
  and in order. §2b's whole argument is that the author did not choose this universe; a test that
  only checked membership would let it drift into one the author did choose, and with `rank_by` unset
  the write order is also the slot tie-break.
* `TestDisjointFromTheRothBook` -- §3's binding constraint, and specifically the *direction* of it.
  These are `trading` cards, so they appear in a `DisjointnessViolation` as `other_agent_id`; round
  34's filter on `roth_agent_id` copied into this round would pass on any field whatsoever. One test
  plants a Roth ticker to prove the guard fires, and one asserts the wrong-direction filter would
  have been vacuous, so the bug cannot be reintroduced quietly.
* `TestRulesParse` -- every `entry` and `exit` parses with `app.rules.grammar.parse`.
* `TestNoCellReproducesAFrozenDesign` -- §5's pre-registered claim that this field contains no
  built-in reproduction check, which is *why* the plan pre-registers an external one. Checked against
  the frozen cards of rounds 17, 18 and 34 rather than asserted in prose.
* `TestDeterminism` -- two `build()` calls produce identical model dumps, which is what §9 claims and
  what makes the frozen cards reproducible from the tool.
* `TestWrittenCardsRoundTrip` -- if `--write` has been run, every file on disk round-trips through
  `StrategyCard.model_validate_json` and matches what `build()` produces today. Skipped rather than
  failed when the directory is absent, because authoring the field is a separate, deliberate step.
* `TestParameterBudget` -- `PROTOCOL.md` §3 rule 3's ten-free-numbers budget, counted the strict way
  (every numeric literal in entry, exit, brackets, hold cap, slot count and position size).

None of these touches the bar store: the field is authored from literals and checked against the
library JSON, both pure reads of code and files. Window eligibility is a question about the store and
belongs to `strategy-program/tools/windows.py`, which the round's definition-of-done runs separately.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

from app.evolution.universe import _TAXABLE_GROWTH
from app.indicators.volatility import BB_SPEC
from app.rules import grammar
from app.rules.grammar import RuleSyntaxError
from app.tournament.models import DESIGN_THROUGH, Discipline, StrategyCard
from app.tournament.purposes import Purpose, find_disjointness_violations, purpose_spec

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "strategy-program" / "tools" / "round37.py"

#: The frozen fields this round's cells are claimed (plan §5) not to reproduce.
FROZEN_ROUNDS = (
    REPO / "data" / "rounds" / "r17-2026-08" / "cards",
    REPO / "data" / "rounds" / "r18-2026-08" / "cards",
    REPO / "data" / "rounds" / "r34-2026-09" / "cards",
)


def _load_tool():
    """`round37.py` as a module, loaded by file path (see this module's docstring)."""
    spec = importlib.util.spec_from_file_location("round37", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["round37"] = module
    spec.loader.exec_module(module)
    return module


round37 = _load_tool()


@pytest.fixture(scope="module")
def cards() -> list[StrategyCard]:
    return round37.build()


@pytest.fixture(scope="module")
def library():
    return round37.library_purposed_cards()


class TestFieldShape:
    def test_twelve_cells(self, cards: list[StrategyCard]) -> None:
        assert len(cards) == 12
        assert len(round37.ENTRIES) == 3
        assert len(round37.EXITS) == 2
        assert round37.REGIME_ARMS == ("on", "off")

    def test_one_card_per_factorial_combination(self, cards: list[StrategyCard]) -> None:
        expected = {
            f"r37-{structure}-{exit_name}-{arm}"
            for structure in round37.ENTRIES
            for exit_name in round37.EXITS
            for arm in round37.REGIME_ARMS
        }
        assert {card.agent_id for card in cards} == expected

    def test_agent_ids_are_unique(self, cards: list[StrategyCard]) -> None:
        ids = [card.agent_id for card in cards]
        assert len(set(ids)) == len(ids)

    def test_fixed_parameters_are_actually_fixed(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            assert card.purpose is Purpose.TRADING
            assert card.discipline is Discipline.BREAKOUT
            assert card.max_positions == round37.MAX_POSITIONS == 4
            assert card.position_pct == round37.POSITION_PCT
            assert card.stop_loss_pct == round37.BRACKET["stop_loss_pct"]
            assert card.take_profit_pct is None
            assert card.max_hold_days == round37.BRACKET["max_hold_days"]
            assert card.designed_through == DESIGN_THROUGH
            assert card.rank_by is None

    def test_purpose_serialises_as_trading(self, cards: list[StrategyCard]) -> None:
        # The JSON key the frozen cards carry, which is what every downstream loader reads.
        assert '"purpose": "trading"' in cards[0].model_dump_json(indent=2)

    def test_every_card_states_a_falsification_naming_a_window(
        self, cards: list[StrategyCard]
    ) -> None:
        # PROTOCOL.md section 3 rule 5: the failure regime is named before the card trades.
        for card in cards:
            assert card.falsification
            assert re.search(r"`(chop|gfc|covid|bear|bull)-?\w*`", card.falsification), (
                f"{card.agent_id} names no window in its failure regime"
            )

    def test_every_thesis_states_the_intraday_limit(self, cards: list[StrategyCard]) -> None:
        # The hypothesis is lifted from an intraday system and this round runs daily bars. That
        # caveat is load-bearing enough that a reader must meet it on the card itself, not only in
        # the plan -- see ROUND-37-PLAN.md section 7.
        for card in cards:
            assert "INTRADAY" in card.thesis
            assert "creator-e" in card.thesis


class TestMandate:
    def test_hold_cap_is_inside_the_trading_mandate(self, cards: list[StrategyCard]) -> None:
        # `max_hold_days` counts sessions (app.tournament.runner._decide_exit). ~21 sessions a month,
        # so 150 sessions is ~7.1 calendar months against a nine-month bound. Round 24 found 180
        # sessions (~8.6 months) breached the six-month bound in force at the time; this round does
        # not want to be the card that forces the bound to move again.
        spec = purpose_spec(Purpose.TRADING)
        assert spec.horizon_months_max == 9
        for card in cards:
            assert card.max_hold_days is not None
            assert card.max_hold_days <= 150
            assert card.max_hold_days / 21 < spec.horizon_months_max


class TestEntryStructure:
    def test_double_names_both_bands(self, cards: list[StrategyCard]) -> None:
        double = [c for c in cards if c.agent_id.startswith("r37-double-")]
        assert len(double) == 4
        for card in double:
            assert "bb_mid(20, 2)" in card.entry
            assert "bb_upper(4, 4)" in card.entry

    def test_outer_names_only_the_slow_band(self, cards: list[StrategyCard]) -> None:
        for card in [c for c in cards if c.agent_id.startswith("r37-outer-")]:
            assert "bb_upper(20, 2)" in card.entry
            assert "(4, 4)" not in card.entry

    def test_inner_names_only_the_fast_band(self, cards: list[StrategyCard]) -> None:
        for card in [c for c in cards if c.agent_id.startswith("r37-inner-")]:
            assert "bb_upper(4, 4)" in card.entry
            assert "(20, 2)" not in card.entry

    def test_regime_arms_differ_by_exactly_the_prefix(self, cards: list[StrategyCard]) -> None:
        by_id = {card.agent_id: card for card in cards}
        for structure in round37.ENTRIES:
            for exit_name in round37.EXITS:
                on = by_id[f"r37-{structure}-{exit_name}-on"]
                off = by_id[f"r37-{structure}-{exit_name}-off"]
                assert on.entry == f"{round37.REGIME_CLAUSE} and {off.entry}"
                assert round37.REGIME_CLAUSE not in off.entry
                # Same cell otherwise: the factor changes the entry and nothing else.
                assert on.exit == off.exit
                assert on.universe == off.universe

    def test_the_two_exits_are_the_two_bands(self, cards: list[StrategyCard]) -> None:
        exits = {card.exit for card in cards}
        assert exits == {"close crosses_below bb_mid(20, 2)", "close < bb_lower(4, 4)"}

    def test_band_constants_are_the_personas_own(self) -> None:
        # Quoted from data/vault/influencers/creator-e/notes/-VIDEOID001.md, not searched
        # over. If these ever change, the round is no longer testing the claim it says it is.
        assert (round37.OUTER_PERIOD, round37.OUTER_SIGMA) == (20, 2)
        assert (round37.INNER_PERIOD, round37.INNER_SIGMA) == (4, 4)


class TestUniverse:
    def test_universe_is_the_evolution_loops_taxable_growth_pool(
        self, cards: list[StrategyCard]
    ) -> None:
        pinned = (
            "NVDA", "TSM", "MU", "AMD", "QCOM", "MSFT",
            "GOOGL", "AMZN", "NFLX", "ORCL", "INTC", "TXN",
        )
        assert list(round37.UNIVERSE) == list(pinned)
        # Order, not just membership -- `rank_by` is unset, so the write order is the slot
        # tie-break (ROUND-37-PLAN.md section 2c), and the whole claim of section 2b is that this
        # is the loop's pool rather than one the author assembled.
        assert tuple(_TAXABLE_GROWTH) == pinned
        for card in cards:
            assert card.universe == pinned

    def test_universe_is_within_the_model_limit(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            assert 1 <= len(card.universe) <= 12


class TestDisjointFromTheRothBook:
    def test_no_ticker_intersects_the_roth_roster(self, cards, library) -> None:
        roth = round37.roth_symbols(library)
        assert roth, "the library should hold at least one roth card"
        for card in cards:
            assert not (set(card.universe) & roth), (
                f"{card.agent_id} intersects the Roth book: {sorted(set(card.universe) & roth)}"
            )

    def test_find_disjointness_violations_reports_nothing_for_this_round(
        self, cards, library
    ) -> None:
        mine, _pre_existing = round37.check_disjointness(cards, library)
        assert mine == (), [violation.message for violation in mine]

        # And again through the library function directly, not through the tool's wrapper, so a bug
        # in `check_disjointness`'s own filtering cannot make this test pass.
        mine_ids = {card.agent_id for card in cards}
        direct = find_disjointness_violations([*library, *cards])
        assert [v.message for v in direct if v.other_agent_id in mine_ids] == []

    def test_the_check_covers_allocation_and_ladder_tiers(self, library) -> None:
        # `load_library()` reads four tiers and misses `allocation/` and `ladder/`. Those tiers hold
        # purposed cards on both sides of the wall, so dropping them would weaken this check
        # silently. Pin that the walk produced more cards than the four StrategyCard tiers alone.
        from app.tournament.results import load_library

        four_tiers = sum(len(tier) for tier in load_library().values())
        assert len(library) >= four_tiers

    def test_the_guard_is_non_vacuous(self, library) -> None:
        # Plant a Roth ticker in a trading card and confirm the check fires. Without this, all the
        # test above proves is that `find_disjointness_violations` was called, not that it can fail.
        roth = sorted(round37.roth_symbols(library))
        planted = StrategyCard(
            agent_id="r37-planted-violation",
            display_name="planted",
            discipline=Discipline.BREAKOUT,
            purpose=Purpose.TRADING,
            thesis="A deliberately invalid card, used only to prove the disjointness guard fires.",
            universe=(roth[0],),
            entry="close > sma(200)",
            exit="close < sma(200)",
            max_positions=1,
            position_pct="0.10",
            designed_through=DESIGN_THROUGH,
        )
        mine, _ = round37.check_disjointness([planted], library)
        assert mine, "planting a Roth ticker in a trading card produced no violation"
        assert mine[0].symbol == roth[0]
        assert mine[0].other_agent_id == "r37-planted-violation"

    def test_round_34s_filter_direction_would_have_been_vacuous_here(self, library) -> None:
        # The failure this round is most exposed to: `round34.check_disjointness` filters on
        # `roth_agent_id`, which is correct for a field of Roth cards and matches NOTHING for a
        # field of trading cards. Copied verbatim it would report a clean field however badly the
        # field collided. This test pins that the two directions genuinely differ, so the wrong one
        # cannot be reintroduced by a copy-paste and go unnoticed.
        roth = sorted(round37.roth_symbols(library))
        planted = StrategyCard(
            agent_id="r37-planted-violation",
            display_name="planted",
            discipline=Discipline.BREAKOUT,
            purpose=Purpose.TRADING,
            thesis="A deliberately invalid card, used only to prove the filter direction matters.",
            universe=(roth[0],),
            entry="close > sma(200)",
            exit="close < sma(200)",
            max_positions=1,
            position_pct="0.10",
            designed_through=DESIGN_THROUGH,
        )
        violations = find_disjointness_violations([*library, planted])
        wrong_direction = [v for v in violations if v.roth_agent_id == planted.agent_id]
        right_direction = [v for v in violations if v.other_agent_id == planted.agent_id]
        assert wrong_direction == []
        assert right_direction


class TestRulesParse:
    def test_every_entry_and_exit_parses(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            grammar.parse(card.entry)
            grammar.parse(card.exit)

    def test_module_level_rule_literals_are_validated_at_import(self) -> None:
        # `_validated` is the reason a misspelled indicator is an import-time failure rather than a
        # card that validates structurally and dies in the seventh window of a four-hour round.
        with pytest.raises(RuleSyntaxError):
            round37._validated("close crosses_above bb_uppr(4, 4)")

    def test_parse_alone_would_not_have_caught_a_bad_arity_or_range(self) -> None:
        # Measured, not assumed, and it is why `_check_band_params` exists: `grammar.parse` accepts
        # a one-argument `bb_upper`, a three-argument one, and a period of 1 that
        # `app.indicators.volatility.BB_SPEC` rejects. Parse-time validation covers the indicator
        # name and the expression shape, not the argument count or the argument ranges.
        for lenient in (
            "close crosses_above bb_upper(4)",
            "close crosses_above bb_upper(4, 4, 4)",
            "close crosses_above bb_upper(1, 4)",
        ):
            grammar.parse(lenient)

    def test_band_constants_are_inside_the_indicator_specs_own_bounds(self) -> None:
        period_spec, stddev_spec = BB_SPEC.params
        for period, stddev in (
            (round37.OUTER_PERIOD, round37.OUTER_SIGMA),
            (round37.INNER_PERIOD, round37.INNER_SIGMA),
        ):
            assert period_spec.minimum <= period <= period_spec.maximum
            assert stddev_spec.minimum <= stddev <= stddev_spec.maximum


class TestNoCellReproducesAFrozenDesign:
    def test_no_entry_exit_pair_matches_a_frozen_round_card(
        self, cards: list[StrategyCard]
    ) -> None:
        # ROUND-37-PLAN.md section 5 pre-registers that this field contains NO built-in reproduction
        # check -- which is why it pre-registers an external one instead. That is a checkable claim
        # about the frozen fields on disk, so it is checked rather than asserted.
        frozen: set[tuple[str, str, tuple[str, ...]]] = set()
        for cards_dir in FROZEN_ROUNDS:
            if not cards_dir.is_dir():
                continue
            for path in sorted(cards_dir.glob("*.json")):
                blob = json.loads(path.read_text(encoding="utf-8"))
                frozen.add((blob["entry"], blob["exit"], tuple(blob["universe"])))
        assert frozen, "no frozen round cards found -- this test would pass vacuously"
        for card in cards:
            key = (card.entry, card.exit, tuple(card.universe))
            assert key not in frozen, (
                f"{card.agent_id} reproduces a frozen design; the plan's section 5 says none does"
            )


class TestDeterminism:
    def test_two_builds_are_identical(self) -> None:
        first = round37.build()
        second = round37.build()
        assert [card.model_dump_json() for card in first] == [
            card.model_dump_json() for card in second
        ]

    def test_build_order_is_stable(self) -> None:
        assert [card.agent_id for card in round37.build()] == [
            card.agent_id for card in round37.build()
        ]


class TestWrittenCardsRoundTrip:
    def test_files_on_disk_match_the_tool(self, cards: list[StrategyCard]) -> None:
        out = round37.OUT
        if not out.is_dir():
            pytest.skip(f"{out} does not exist -- run round37.py --write to author the field")
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
    #: Every numeric literal in a rule. The strict count, so the plan's claim is checked at its own
    #: most conservative reading.
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

    def test_the_plans_stated_count_of_nine_choices_is_right(self) -> None:
        # The plan's section 2c counts nine *choices* rather than nine distinct literals: outer
        # period, outer sigma, inner period, inner sigma, regime period, stop, hold cap, slot count,
        # position size. The strict-literal count above is lower because 4 appears as both the inner
        # band's period/sigma and the slot count. Both readings are reported in the plan; this pins
        # the one a reader is most likely to recompute.
        choices = (
            round37.OUTER_PERIOD,
            round37.OUTER_SIGMA,
            round37.INNER_PERIOD,
            round37.INNER_SIGMA,
            round37.REGIME_MA,
            round37.BRACKET["stop_loss_pct"],
            round37.BRACKET["max_hold_days"],
            round37.MAX_POSITIONS,
            round37.POSITION_PCT,
        )
        assert len(choices) == 9 <= 10

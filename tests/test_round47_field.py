"""Tests for `strategy-program/tools/round47.py` -- round 47's dip/trim/dip-trim field on three of
round 44's baskets.

`strategy-program` is not a legal Python package name (the hyphen), so `round47.py` is loaded by file
path here -- the same precedent `tests/test_round44_field.py` set.

Every test here is fast and touches **no bar store** except `TestSupportTable`, which is the round's
one expensive, real-data claim (the reachability probe `ROUND-47-PLAN.md` section 3a pins). What this
module pins otherwise is everything that can be wrong *before* a single bar is read, and in particular
the invariants this round could break with real consequences:

* `TestFieldShape` -- twelve cards, three baskets x four arms, with the pre-registered agent ids, the
  same slot count and position size everywhere, and no brackets anywhere.
* `TestRothInvariant` -- every card is `Purpose.ROTH`, no ticker intersects any `savings`- or
  `trading`-purpose card in the live library (all six tiers), and `find_disjointness_violations`
  reports nothing naming one of this round's cards. This is the Rev. Rul. 2008-5 boundary -- an IRA
  replacement purchase *destroys* a wash-sale loss rather than deferring it.
* `TestBasketsDisjointFromEachOther` -- the three baskets partition the twelve traded names with no
  ticker repeated across baskets.
* `TestExpressionsParse` -- every `entry` and `exit` parses with `app.rules.grammar.parse`, and no card
  sets a `rank_by` (there is a slot for every name, so there is nothing to rank).
* `TestR44Drift` -- the `passive` and `trim` arms are round 44's control and trim expressions,
  verbatim, and match the on-disk r44 cards for `power`, `defense` and `control` field for field
  (entry, exit, slots, size, universe) -- `check_r44_drift()` reports no problems.
* `TestArms` -- `dip`'s entry is the pullback-inside-an-uptrend conjunction and its exit is the
  never-true passive exit (accumulate, then hold); `dip-trim` shares `dip`'s entry and `trim`'s exit;
  each basket's four cards match each other in everything except entry/exit
  (`PROTOCOL.md` section 7's one-decision rule, applied pairwise against the passive reference).
* `TestParameterBudget` -- no card spends more than `PROTOCOL.md` section 3's ten free numbers, and the
  field's actual maximum is five.
* `TestDeterminism` -- `build()` called twice returns field-identical cards.
* `TestSupportTable` -- `support_table()` reports a nonzero `dip_fires` and `trim_fires` count for
  every one of the twelve traded names (the field's own refusal-to-write condition). Needs the bar
  store; skipped if it cannot be opened.
* `TestOnDiskCardsRoundTrip` -- the JSON actually written under `data/rounds/r47-2026-09/cards/`
  re-validates through `StrategyCard.model_validate_json` and matches `build()` field for field.
  Skipped when the directory does not exist, so the suite stays green on a checkout where the field has
  not been authored yet.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from app.rules import grammar
from app.tournament.models import DESIGN_THROUGH, Discipline, StrategyCard
from app.tournament.purposes import Purpose, find_disjointness_violations

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "strategy-program" / "tools" / "round47.py"


def _load_round47():
    spec = importlib.util.spec_from_file_location("round47_tool", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["round47_tool"] = module
    spec.loader.exec_module(module)
    return module


round47 = _load_round47()

#: The twelve cells, pre-registered. Written out rather than derived from `BASKETS`/`ARMS` so that a
#: change to either map breaks this list loudly instead of quietly redefining what the round is.
EXPECTED_AGENT_IDS = sorted(
    [
        "r47-power-passive",
        "r47-power-dip",
        "r47-power-trim",
        "r47-power-dip-trim",
        "r47-defense-passive",
        "r47-defense-dip",
        "r47-defense-trim",
        "r47-defense-dip-trim",
        "r47-control-passive",
        "r47-control-dip",
        "r47-control-trim",
        "r47-control-dip-trim",
    ]
)


@pytest.fixture(scope="module")
def cards() -> list[StrategyCard]:
    return round47.build()


class TestFieldShape:
    def test_twelve_cells(self, cards: list[StrategyCard]) -> None:
        """Three baskets x four arms. The field size *is* the multiple-comparison denominator: every
        cell run enters the Benjamini-Hochberg correction (`PROTOCOL.md` section 3 rule 8)."""
        assert len(cards) == 12

    def test_agent_ids_are_the_pre_registered_set(self, cards: list[StrategyCard]) -> None:
        assert sorted(card.agent_id for card in cards) == EXPECTED_AGENT_IDS

    def test_the_baskets_are_the_pre_registered_ones(self) -> None:
        assert round47.BASKETS == {
            "power": ("NEE", "DUK", "SO", "CCJ"),
            "defense": ("LMT", "NOC", "GD", "RTX"),
            "control": ("VTV", "SPYG", "RSP", "MDY"),
        }

    def test_every_card_holds_a_slot_for_every_name(self, cards: list[StrategyCard]) -> None:
        """No slot contention anywhere in this field: every basket has exactly four names and every
        card carries `max_positions == 4`, so `rank_by` is unset on every card."""
        for card in cards:
            assert card.max_positions == 4 == round47.MAX_POSITIONS, card.agent_id
            assert len(card.universe) == 4, card.agent_id
            assert card.rank_by is None, card.agent_id

    def test_every_card_deploys_the_same_position_size(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            assert card.position_pct == Decimal("0.25"), card.agent_id
            assert card.position_pct * card.max_positions == Decimal("1.00"), card.agent_id

    def test_no_card_carries_a_bracket(self, cards: list[StrategyCard]) -> None:
        """A stop the passive arm cannot have would make an arm-vs-passive contrast a joint
        measurement of the rule *plus* the stop. `PROTOCOL.md` section 7's one-decision rule is why
        every arm carries none."""
        for card in cards:
            assert card.stop_loss_pct is None, card.agent_id
            assert card.take_profit_pct is None, card.agent_id
            assert card.max_hold_days is None, card.agent_id

    def test_design_cutoff(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            assert card.designed_through == DESIGN_THROUGH
            assert card.desk_only is False
            assert card.reference_only is False

    def test_every_card_states_a_falsification_condition(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            assert card.falsification, card.agent_id

    def test_discipline_labels(self, cards: list[StrategyCard]) -> None:
        """passive: forced TREND (r44 precedent). trim: r44's genuine RISK_MANAGED fit, reused.
        dip / dip-trim: a genuine (not forced) `classify()` result of TREND -- both share the same
        entry, and `classify()` reads the entry first."""
        for card in cards:
            if card.agent_id.endswith("-trim") and not card.agent_id.endswith("-dip-trim"):
                assert card.discipline == Discipline.RISK_MANAGED, card.agent_id
            else:
                assert card.discipline == Discipline.TREND, card.agent_id


class TestRothInvariant:
    """The Rev. Rul. 2008-5 boundary. An IRA replacement purchase destroys a wash-sale loss outright
    rather than deferring it, so a ticker shared between a roth card and a taxable one is not an
    untidiness -- it is a permanently lost deduction."""

    def test_every_card_is_roth(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            assert card.purpose is Purpose.ROTH, card.agent_id

    def test_no_ticker_is_claimed_by_the_taxable_book(self) -> None:
        taxable, _others = round47.claimed_symbols()
        assert taxable, "the live library reported no taxable tickers at all -- the check is vacuous"
        assert set(round47.TRADED) & taxable == set()

    def test_find_disjointness_violations_reports_nothing(self, cards: list[StrategyCard]) -> None:
        """The real check, run through the programme's own function rather than a set intersection
        rewritten here. Only the library's non-roth half is passed alongside this round's cards, so a
        pre-existing roth-vs-taxable violation elsewhere in the library cannot be attributed to round
        47 -- and cannot mask one either, since every roth card in the comparison is ours."""
        _taxable, others = round47.claimed_symbols()
        assert others, "no savings/trading cards found -- the check would pass vacuously"
        violations = find_disjointness_violations([*cards, *others])
        ours = {card.agent_id for card in cards}
        assert [v.message for v in violations if v.roth_agent_id in ours] == []


class TestBasketsDisjointFromEachOther:
    def test_twelve_distinct_names(self) -> None:
        all_names = [sym for names in round47.BASKETS.values() for sym in names]
        assert len(all_names) == 12
        assert len(set(all_names)) == 12, "a ticker repeats across baskets"

    def test_traded_matches_the_baskets(self) -> None:
        assert set(round47.TRADED) == {
            sym for names in round47.BASKETS.values() for sym in names
        }
        assert len(round47.TRADED) == 12

    def test_card_universe_matches_its_basket(self, cards: list[StrategyCard]) -> None:
        by_id = {card.agent_id: card for card in cards}
        for basket, names in round47.BASKETS.items():
            for arm in round47.ARM_ORDER:
                card = by_id[f"r47-{basket}-{arm}"]
                assert card.universe == names, card.agent_id


class TestExpressionsParse:
    def test_entry_and_exit_parse(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            assert grammar.parse(card.entry) is not None, card.agent_id
            assert grammar.parse(card.exit) is not None, card.agent_id

    def test_no_card_sets_a_ranking_key(self, cards: list[StrategyCard]) -> None:
        assert [card for card in cards if card.rank_by is not None] == []


class TestR44Drift:
    """`power`, `defense` and `control` and the `passive`/`trim` arm expressions are round 44's,
    reused verbatim -- not re-typed on trust. Skipped if round 44's cards are not on disk (a checkout
    that has not run round 44), the same tolerance `TestOnDiskCardsRoundTrip` gives an absent round 47
    directory."""

    def test_no_drift_reported(self) -> None:
        if not round47._R44_CARDS.is_dir():
            pytest.skip(f"{round47._R44_CARDS} does not exist -- round 44 has not been authored")
        assert round47.check_r44_drift() == []

    def test_passive_arm_matches_round44_expressions(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            if card.agent_id.endswith("-passive"):
                assert card.entry == "close > 0" == round47.PASSIVE_ENTRY, card.agent_id
                assert card.exit == "close < 0" == round47.PASSIVE_EXIT, card.agent_id

    def test_trim_arm_matches_round44_expressions(self, cards: list[StrategyCard]) -> None:
        assert Decimal("1.15") == round47.TRIM_THRESHOLD
        for card in cards:
            if card.agent_id.endswith("-trim") and not card.agent_id.endswith("-dip-trim"):
                assert card.entry == "close < sma(200) * 1.15" == round47.TRIM_ENTRY, card.agent_id
                assert card.exit == "close > sma(200) * 1.15" == round47.TRIM_EXIT, card.agent_id


class TestArms:
    """dip and dip-trim differ from passive/trim only in entry/exit; every card in a basket shares
    universe/slots/size and no brackets (`PROTOCOL.md` section 7's one-decision rule)."""

    def test_dip_entry_is_the_pullback_conjunction(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            if card.agent_id.endswith("-dip") and not card.agent_id.endswith("-dip-trim"):
                assert card.entry == "close < sma(50) and close > sma(200)" == round47.DIP_ENTRY
                assert card.exit == "close < 0" == round47.DIP_EXIT

    def test_dip_never_exits_by_rule(self) -> None:
        """`DIP_EXIT` is the structurally-never-true passive exit -- the mechanism for 'accumulate,
        then hold', not a placeholder."""
        assert round47.DIP_EXIT == round47.PASSIVE_EXIT == "close < 0"

    def test_dip_trim_combines_dip_entry_and_trim_exit(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            if card.agent_id.endswith("-dip-trim"):
                assert card.entry == round47.DIP_ENTRY == "close < sma(50) and close > sma(200)"
                assert card.exit == round47.TRIM_EXIT == "close > sma(200) * 1.15"

    def test_each_basket_has_four_matching_cards(self, cards: list[StrategyCard]) -> None:
        by_id = {card.agent_id: card for card in cards}
        for basket in round47.BASKETS:
            arms = {arm: by_id[f"r47-{basket}-{arm}"] for arm in round47.ARM_ORDER}
            reference = arms["passive"]
            for arm, card in arms.items():
                assert card.universe == reference.universe, card.agent_id
                assert card.max_positions == reference.max_positions, card.agent_id
                assert card.position_pct == reference.position_pct, card.agent_id
                assert card.stop_loss_pct is None, card.agent_id
                assert card.take_profit_pct is None, card.agent_id
                assert card.max_hold_days is None, card.agent_id
                if arm != "passive":
                    assert (card.entry, card.exit) != (reference.entry, reference.exit), card.agent_id


class TestParameterBudget:
    def test_no_card_exceeds_ten_free_numbers(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            assert round47.free_numbers(card) <= 10, (
                f"{card.agent_id} spends {round47.free_numbers(card)}"
            )

    def test_the_fields_actual_maximum_is_five(self, cards: list[StrategyCard]) -> None:
        """passive spends 3 (`{0}` plus slot count and position size), trim spends 4
        (`{200, 1.15}` plus the same two), dip and dip-trim spend 5 (`{50, 200}` or `{50, 200, 1.15}`
        plus the same two) -- any later edit that adds a number to this field breaks a test rather
        than a margin."""
        assert max(round47.free_numbers(c) for c in cards) == 5
        expected = {"passive": 3, "dip": 5, "trim": 4, "dip-trim": 5}
        for card in cards:
            arm = card.agent_id.split("-", 2)[2]
            assert round47.free_numbers(card) == expected[arm], card.agent_id


class TestDeterminism:
    def test_build_is_deterministic(self) -> None:
        first = round47.build()
        second = round47.build()
        assert [c.model_dump_json() for c in first] == [c.model_dump_json() for c in second]

    def test_order_is_stable(self) -> None:
        assert [c.agent_id for c in round47.build()] == [c.agent_id for c in round47.build()]


class TestSupportTable:
    """The reachability probe `ROUND-47-PLAN.md` section 3a pins: every one of the twelve traded names
    must fire at least once on both the dip entry and the trim exit, or the round refuses to write.
    Needs the bar store; skipped if it cannot be opened (mirrors `windows.py`'s own tolerance for a
    locked/absent store in a CI environment)."""

    @pytest.fixture(scope="class")
    @classmethod
    def table(cls):
        from app.config import get_settings

        try:
            table = round47.support_table(get_settings())
        except Exception as exc:  # pragma: no cover -- environment-dependent
            pytest.skip(f"could not open the bar store: {exc}")
        # A checkout without the bar history yields an all-empty table: skip rather than fail.
        if all(
            row.get("first_bar") is None or all(row.get(k, 0) == 0 for k in ("dip_fires", "trim_fires"))
            for row in table.values()
        ):
            pytest.skip("bar store has no history for the traded names")
        return table

    def test_every_traded_name_is_present(self, table) -> None:
        assert set(table) == set(round47.TRADED)

    def test_no_name_has_zero_dip_fires(self, table) -> None:
        zero = [s for s, row in table.items() if row["dip_fires"] == 0]
        assert zero == [], f"structurally unreachable dip entry for: {zero}"

    def test_no_name_has_zero_trim_fires(self, table) -> None:
        zero = [s for s, row in table.items() if row["trim_fires"] == 0]
        assert zero == [], f"structurally unreachable trim exit for: {zero}"

    def test_every_first_bar_precedes_gfc(self, table) -> None:
        import datetime as dt

        gfc_start = dt.date(2007, 10, 9)
        late = [s for s, row in table.items() if row["first_bar"] is None or row["first_bar"] >= gfc_start]
        assert late == [], f"first bar too late for the gfc window: {late}"


class TestOnDiskCardsRoundTrip:
    def test_written_cards_match_build(self, cards: list[StrategyCard]) -> None:
        out = round47.OUT
        if not out.is_dir():
            pytest.skip(f"{out} does not exist -- run round47.py --write to author the field")
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
        out = round47.OUT
        if not out.is_dir():
            pytest.skip(f"{out} does not exist -- run round47.py --write to author the field")
        for path in sorted(out.glob("*.json")):
            assert '"purpose": "roth"' in path.read_text(encoding="utf-8"), path.name

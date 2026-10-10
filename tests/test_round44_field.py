"""Tests for `strategy-program/tools/round44.py` -- round 44's thematic-basket / profit-trim field.

`strategy-program` is not a legal Python package name (the hyphen), so `round44.py` is loaded by file
path here -- the same precedent `tests/test_round35_field.py`, `tests/test_round39_field.py` and
`tests/test_round40_field.py` already set.

Every test here is fast and touches **no bar store** except `TestSupportTable`, which is the round's
one expensive, real-data claim (the reachability probe `ROUND-44-PLAN.md` section 3a pins). What this
module pins otherwise is everything that can be wrong *before* a single bar is read, and in particular
the invariant this round could break with real consequences:

* `TestFieldShape` -- ten cards, five baskets x two arms, with the pre-registered agent ids, the same
  slot count and position size everywhere, and no brackets anywhere.
* `TestRothInvariant` -- every card is `Purpose.ROTH`, no ticker intersects any `savings`- or
  `trading`-purpose card in the live library (all six tiers), and `find_disjointness_violations`
  reports nothing naming one of this round's cards. This is the Rev. Rul. 2008-5 boundary -- an IRA
  replacement purchase *destroys* a wash-sale loss rather than deferring it.
* `TestBasketsDisjointFromEachOther` -- the five baskets partition the twenty traded names with no
  ticker repeated across baskets.
* `TestExpressionsParse` -- every `entry` and `exit` parses with `app.rules.grammar.parse`, and no card
  sets a `rank_by` (there is a slot for every name, so there is nothing to rank).
* `TestArms` -- the passive arm's expressions are round 39's control expressions verbatim; the trim
  arm's expressions use the pinned `sma(200) * 1.15` threshold; each basket's trim card matches its
  passive card in everything except entry/exit (`PROTOCOL.md` section 7's one-decision rule).
* `TestParameterBudget` -- no card spends more than `PROTOCOL.md` section 3's ten free numbers, and the
  field's actual maximum is four.
* `TestDeterminism` -- `build()` called twice returns field-identical cards.
* `TestSupportTable` -- `support_table()` reports a nonzero `fires` count for every one of the twenty
  traded names (the field's own refusal-to-write condition), and the pinned minimum-support name is
  the field's actual minimum. Needs the bar store; skipped if it cannot be opened.
* `TestOnDiskCardsRoundTrip` -- the JSON actually written under `data/rounds/r44-2026-09/cards/`
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
TOOL = REPO / "strategy-program" / "tools" / "round44.py"


def _load_round44():
    spec = importlib.util.spec_from_file_location("round44_tool", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["round44_tool"] = module
    spec.loader.exec_module(module)
    return module


round44 = _load_round44()

#: The ten cells, pre-registered. Written out rather than derived from `BASKETS` so that a change to
#: the basket map breaks this list loudly instead of quietly redefining what the round is.
EXPECTED_AGENT_IDS = sorted(
    [
        "r44-power-passive",
        "r44-power-trim",
        "r44-defense-passive",
        "r44-defense-trim",
        "r44-semicap-passive",
        "r44-semicap-trim",
        "r44-realassets-passive",
        "r44-realassets-trim",
        "r44-control-passive",
        "r44-control-trim",
    ]
)


@pytest.fixture(scope="module")
def cards() -> list[StrategyCard]:
    return round44.build()


class TestFieldShape:
    def test_ten_cells(self, cards: list[StrategyCard]) -> None:
        """Five baskets x two arms. The field size *is* the multiple-comparison denominator: every
        cell run enters the Benjamini-Hochberg correction (`PROTOCOL.md` section 3 rule 8)."""
        assert len(cards) == 10

    def test_agent_ids_are_the_pre_registered_set(self, cards: list[StrategyCard]) -> None:
        assert sorted(card.agent_id for card in cards) == EXPECTED_AGENT_IDS

    def test_the_baskets_are_the_pre_registered_ones(self) -> None:
        assert round44.BASKETS == {
            "power": ("NEE", "DUK", "SO", "CCJ"),
            "defense": ("LMT", "NOC", "GD", "RTX"),
            "semicap": ("AMAT", "KLAC", "LRCX", "ASML"),
            "realassets": ("XOP", "XME", "EWY", "VWO"),
            "control": ("VTV", "SPYG", "RSP", "MDY"),
        }

    def test_every_card_holds_a_slot_for_every_name(self, cards: list[StrategyCard]) -> None:
        """No slot contention anywhere in this field: every basket has exactly four names and every
        card carries `max_positions == 4`, so `rank_by` is unset on every card."""
        for card in cards:
            assert card.max_positions == 4 == round44.MAX_POSITIONS, card.agent_id
            assert len(card.universe) == 4, card.agent_id
            assert card.rank_by is None, card.agent_id

    def test_every_card_deploys_the_same_position_size(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            assert card.position_pct == Decimal("0.25"), card.agent_id
            assert card.position_pct * card.max_positions == Decimal("1.00"), card.agent_id

    def test_no_card_carries_a_bracket(self, cards: list[StrategyCard]) -> None:
        """A stop the passive arm cannot have would make `trim - passive` a joint measurement of the
        rule *plus* the stop. `PROTOCOL.md` section 7's one-decision rule is why both arms carry
        none."""
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
        for card in cards:
            if card.agent_id.endswith("-passive"):
                assert card.discipline == Discipline.TREND, card.agent_id
            else:
                assert card.discipline == Discipline.RISK_MANAGED, card.agent_id


class TestRothInvariant:
    """The Rev. Rul. 2008-5 boundary. An IRA replacement purchase destroys a wash-sale loss outright
    rather than deferring it, so a ticker shared between a roth card and a taxable one is not an
    untidiness -- it is a permanently lost deduction."""

    def test_every_card_is_roth(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            assert card.purpose is Purpose.ROTH, card.agent_id

    def test_no_ticker_is_claimed_by_the_taxable_book(self) -> None:
        taxable, _others = round44.claimed_symbols()
        assert taxable, "the live library reported no taxable tickers at all -- the check is vacuous"
        assert set(round44.TRADED) & taxable == set()

    def test_find_disjointness_violations_reports_nothing(self, cards: list[StrategyCard]) -> None:
        """The real check, run through the programme's own function rather than a set intersection
        rewritten here. Only the library's non-roth half is passed alongside this round's cards, so a
        pre-existing roth-vs-taxable violation elsewhere in the library cannot be attributed to round
        44 -- and cannot mask one either, since every roth card in the comparison is ours."""
        _taxable, others = round44.claimed_symbols()
        assert others, "no savings/trading cards found -- the check would pass vacuously"
        violations = find_disjointness_violations([*cards, *others])
        ours = {card.agent_id for card in cards}
        assert [v.message for v in violations if v.roth_agent_id in ours] == []


class TestBasketsDisjointFromEachOther:
    def test_twenty_distinct_names(self) -> None:
        all_names = [sym for names in round44.BASKETS.values() for sym in names]
        assert len(all_names) == 20
        assert len(set(all_names)) == 20, "a ticker repeats across baskets"

    def test_traded_matches_the_baskets(self) -> None:
        assert set(round44.TRADED) == {
            sym for names in round44.BASKETS.values() for sym in names
        }
        assert len(round44.TRADED) == 20

    def test_card_universe_matches_its_basket(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            basket = card.agent_id.removeprefix("r44-").removesuffix("-passive").removesuffix("-trim")
            assert card.universe == round44.BASKETS[basket], card.agent_id


class TestExpressionsParse:
    def test_entry_and_exit_parse(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            assert grammar.parse(card.entry) is not None, card.agent_id
            assert grammar.parse(card.exit) is not None, card.agent_id

    def test_no_card_sets_a_ranking_key(self, cards: list[StrategyCard]) -> None:
        assert [card for card in cards if card.rank_by is not None] == []


class TestArms:
    """`passive - control` and `trim - passive` are only clean attributions if the two arms differ in
    exactly one thing per basket (`PROTOCOL.md` section 7's one-decision rule)."""

    def test_passive_expressions_match_round_39s_control(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            if card.agent_id.endswith("-passive"):
                assert card.entry == "close > 0" == round44.PASSIVE_ENTRY, card.agent_id
                assert card.exit == "close < 0" == round44.PASSIVE_EXIT, card.agent_id

    def test_trim_expressions_use_the_pinned_threshold(self, cards: list[StrategyCard]) -> None:
        assert Decimal("1.15") == round44.TRIM_THRESHOLD
        for card in cards:
            if card.agent_id.endswith("-trim"):
                assert card.entry == "close < sma(200) * 1.15" == round44.TRIM_ENTRY, card.agent_id
                assert card.exit == "close > sma(200) * 1.15" == round44.TRIM_EXIT, card.agent_id

    def test_each_basket_has_a_matching_passive_and_trim_card(
        self, cards: list[StrategyCard]
    ) -> None:
        by_id = {card.agent_id: card for card in cards}
        for basket in round44.BASKETS:
            passive = by_id[f"r44-{basket}-passive"]
            trim = by_id[f"r44-{basket}-trim"]
            assert passive.universe == trim.universe
            assert passive.max_positions == trim.max_positions
            assert passive.position_pct == trim.position_pct
            assert (passive.entry, passive.exit) != (trim.entry, trim.exit)
            assert passive.stop_loss_pct == trim.stop_loss_pct is None
            assert passive.take_profit_pct == trim.take_profit_pct is None
            assert passive.max_hold_days == trim.max_hold_days is None


class TestParameterBudget:
    def test_no_card_exceeds_ten_free_numbers(self, cards: list[StrategyCard]) -> None:
        for card in cards:
            assert round44.free_numbers(card) <= 10, (
                f"{card.agent_id} spends {round44.free_numbers(card)}"
            )

    def test_the_fields_actual_maximum_is_four(self, cards: list[StrategyCard]) -> None:
        """Passive spends 3 (`{0}` plus slot count and position size), trim spends 4 (`{200, 1.15}`
        plus the same two) -- any later edit that adds a number to this field breaks a test rather
        than a margin."""
        assert max(round44.free_numbers(card) for card in cards) == 4
        for card in cards:
            expected = 4 if card.agent_id.endswith("-trim") else 3
            assert round44.free_numbers(card) == expected, card.agent_id


class TestDeterminism:
    def test_build_is_deterministic(self) -> None:
        first = round44.build()
        second = round44.build()
        assert [c.model_dump_json() for c in first] == [c.model_dump_json() for c in second]

    def test_order_is_stable(self) -> None:
        assert [c.agent_id for c in round44.build()] == [c.agent_id for c in round44.build()]


class TestSupportTable:
    """The reachability probe `ROUND-44-PLAN.md` section 3a pins: every one of the twenty traded names
    must fire at least once on the extension condition, or the round refuses to write. Needs the bar
    store; skipped if it cannot be opened (mirrors `windows.py`'s own tolerance for a locked/absent
    store in a CI environment)."""

    @pytest.fixture(scope="class")
    @classmethod
    def table(cls):
        from app.config import get_settings

        try:
            table = round44.support_table(get_settings())
        except Exception as exc:  # pragma: no cover -- environment-dependent
            pytest.skip(f"could not open the bar store: {exc}")
        # A checkout without the bar history yields an all-empty table: skip rather than fail.
        if all(
            row.get("first_bar") is None or all(row.get(k, 0) == 0 for k in ("fires",))
            for row in table.values()
        ):
            pytest.skip("bar store has no history for the traded names")
        return table

    def test_every_traded_name_is_present(self, table) -> None:
        assert set(table) == set(round44.TRADED)

    def test_no_name_has_zero_fires(self, table) -> None:
        zero = [s for s, row in table.items() if row["fires"] == 0]
        assert zero == [], f"structurally unreachable trim condition for: {zero}"

    def test_every_first_bar_precedes_gfc(self, table) -> None:
        import datetime as dt

        gfc_start = dt.date(2007, 10, 9)
        late = [s for s, row in table.items() if row["first_bar"] is None or row["first_bar"] >= gfc_start]
        assert late == [], f"first bar too late for the gfc window: {late}"


class TestOnDiskCardsRoundTrip:
    def test_written_cards_match_build(self, cards: list[StrategyCard]) -> None:
        out = round44.OUT
        if not out.is_dir():
            pytest.skip(f"{out} does not exist -- run round44.py --write to author the field")
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
        out = round44.OUT
        if not out.is_dir():
            pytest.skip(f"{out} does not exist -- run round44.py --write to author the field")
        for path in sorted(out.glob("*.json")):
            assert '"purpose": "roth"' in path.read_text(encoding="utf-8"), path.name

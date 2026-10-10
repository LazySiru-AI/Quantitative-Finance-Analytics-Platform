"""Pins Round 40's pre-registered field (`strategy-program/tools/round40.py`).

`strategy-program` is not a legal Python package name (the hyphen), so `round40.py` is loaded by file
path here -- the identical precedent `tests/test_contributions.py` sets for the same reason.

These tests are **fast and touch no bar store**: the reachability gate that measures firings against the
store runs inside the tool at `--write`, deliberately not in the suite (`pytest` cannot see the store on
a fresh checkout and must not depend on it). What is pinned here is the *field's shape and construction*:
the card count, the purpose, that every rule parses, the roth disjointness, the by-construction identity
of each arm's entry, the free-number budget, determinism, and on-disk round-trip.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from app.rules import grammar
from app.tournament.models import DESIGN_THROUGH, StrategyCard
from app.tournament.purposes import Purpose

_spec = importlib.util.spec_from_file_location(
    "round40",
    str(Path(__file__).resolve().parents[1] / "strategy-program" / "tools" / "round40.py"),
)
assert _spec is not None and _spec.loader is not None
round40 = importlib.util.module_from_spec(_spec)
sys.modules["round40"] = round40
_spec.loader.exec_module(round40)


#: The live roth union (21 tickers) is recomputed from disk by the tool; hardcoded here only so the test
#: needs no library read. `test_roth_union_matches_tool` (below) is skipped rather than asserted against
#: the live library, because the suite must not depend on library state a concurrent session may edit.
_EXPECTED_ROTH = frozenset(
    {
        "AAPL", "ADBE", "AMAT", "BND", "CRM", "CSCO", "IGV", "INTU", "ITA", "KLAC", "LRCX",
        "SSO", "VIG", "VNQ", "VUG", "XBI", "XHB", "XME", "XOP", "XRT", "XSD",
    }
)


@pytest.fixture(scope="module")
def cards() -> list[StrategyCard]:
    return round40.build()


def test_card_count(cards: list[StrategyCard]) -> None:
    # 4 arms x 2 slot caps.
    assert len(cards) == 8
    assert len(round40.ARMS) == 4
    assert set(round40.SLOT_CAPS) == {3, 6}


def test_all_cards_are_trading(cards: list[StrategyCard]) -> None:
    assert all(card.purpose is Purpose.TRADING for card in cards)


def test_all_cards_designed_through_cutoff(cards: list[StrategyCard]) -> None:
    assert all(card.designed_through == DESIGN_THROUGH for card in cards)


def test_entry_and_exit_parse(cards: list[StrategyCard]) -> None:
    for card in cards:
        grammar.parse(card.entry)
        grammar.parse(card.exit)


def test_rank_by_is_unset(cards: list[StrategyCard]) -> None:
    # rank_by held identical (unset) across every cell -- the only axis that varies is the conjunct.
    assert all(card.rank_by is None for card in cards)


def test_no_ticker_intersects_roth_union(cards: list[StrategyCard]) -> None:
    for card in cards:
        assert not (set(card.universe) & _EXPECTED_ROTH), card.agent_id


def test_control_entry_is_exactly_the_base(cards: list[StrategyCard]) -> None:
    controls = [c for c in cards if c.agent_id.startswith("r40-none-")]
    assert len(controls) == 2
    for card in controls:
        assert card.entry == round40.BASE_ENTRY


def test_treatment_entries_are_base_plus_conjunct_by_construction(cards: list[StrategyCard]) -> None:
    # Assert by construction from BASE_ENTRY + " and " + conjunct -- never by retyping the full string.
    for arm, (conjunct, _kind) in round40.ARMS.items():
        if conjunct is None:
            continue
        expected = f"{round40.BASE_ENTRY} and {conjunct}"
        arm_cards = [c for c in cards if c.agent_id.startswith(f"r40-{arm}-")]
        assert len(arm_cards) == 2, arm
        for card in arm_cards:
            assert card.entry == expected, card.agent_id
            assert card.entry.startswith(round40.BASE_ENTRY + " and ")


def test_exit_is_fixed_across_all_cards(cards: list[StrategyCard]) -> None:
    assert {card.exit for card in cards} == {round40.EXIT}


def test_position_pct_matches_slot_cap(cards: list[StrategyCard]) -> None:
    for card in cards:
        assert card.position_pct == round40.SLOT_CAPS[card.max_positions]
        # Gross commitment is comparable (~0.75) across the two caps.
        assert card.position_pct * card.max_positions <= round40.Decimal("1.001")


def test_free_number_budget(cards: list[StrategyCard]) -> None:
    for card in cards:
        assert round40.free_numbers(card) <= 10, card.agent_id


def test_build_is_deterministic() -> None:
    a = round40.build()
    b = round40.build()
    assert [c.model_dump_json() for c in a] == [c.model_dump_json() for c in b]


def test_entry_for_construction() -> None:
    assert round40.entry_for(None) == round40.BASE_ENTRY
    assert round40.entry_for("x > 1") == f"{round40.BASE_ENTRY} and x > 1"


def test_on_disk_cards_round_trip() -> None:
    """If the field has been written, every on-disk card re-validates through StrategyCard."""
    out = round40.OUT
    if not out.is_dir():
        pytest.skip("field not written yet (run round40.py --write)")
    paths = sorted(out.glob("*.json"))
    assert len(paths) == 8
    for path in paths:
        card = StrategyCard.model_validate_json(path.read_text(encoding="utf-8"))
        grammar.parse(card.entry)
        grammar.parse(card.exit)

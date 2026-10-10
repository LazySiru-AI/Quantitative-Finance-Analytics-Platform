"""Pins Round 42's pre-registered field (`strategy-program/tools/round42.py`).

`strategy-program` is not a legal Python package name (the hyphen), so `round42.py` is loaded by file
path here -- the identical precedent `tests/test_contributions.py` and `tests/test_round40_field.py`
set for the same reason.

These tests are **fast and touch no bar store**: the reachability gate that measures firings against
the store runs inside the tool at `--write`, deliberately not in the suite (`pytest` cannot see the
store on a fresh checkout and must not depend on it). What is pinned here is the *field's shape and
construction*: the card count, the purpose, that every rule parses, the roth disjointness, the pinned
literal entry/exit text for every arm, the fixed brackets, the free-number budget, determinism, and the
on-disk round-trip.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from app.rules import grammar
from app.tournament.models import DESIGN_THROUGH, StrategyCard
from app.tournament.purposes import Purpose

_spec = importlib.util.spec_from_file_location(
    "round42",
    str(Path(__file__).resolve().parents[1] / "strategy-program" / "tools" / "round42.py"),
)
assert _spec is not None and _spec.loader is not None
round42 = importlib.util.module_from_spec(_spec)
sys.modules["round42"] = round42
_spec.loader.exec_module(round42)


#: The live roth union (21 tickers) is recomputed from disk by the tool; hardcoded here only so the
#: test needs no library read -- the identical set `test_round40_field.py` hardcodes, and for the same
#: reason: the suite must not depend on library state a concurrent session may edit.
_EXPECTED_ROTH = frozenset(
    {
        "AAPL", "ADBE", "AMAT", "BND", "CRM", "CSCO", "IGV", "INTU", "ITA", "KLAC", "LRCX",
        "SSO", "VIG", "VNQ", "VUG", "XBI", "XHB", "XME", "XOP", "XRT", "XSD",
    }
)

#: The pinned literal entry text for every arm, exactly as `ROUND-42-PLAN.md` names it.
_EXPECTED_ENTRY = {
    "r42-reclaim-control": "close crosses_above swing_low(20)",
    "r42-reclaim-wick": "low < swing_low(20) and close > swing_low(20)",
    "r42-reclaim-wick-body": (
        "low < swing_low(20) and close > swing_low(20) and (close - open) > 0.5 * (high - low)"
    ),
    "r42-breakout-control": "close crosses_above swing_high(20)",
    "r42-breakout-q25": (
        "close crosses_above swing_high(20) + 0.25 * (swing_high(20) - swing_low(20))"
    ),
}

_RECLAIM_EXIT = "close crosses_below swing_low(20)"
_BREAKOUT_EXIT = "close crosses_below ema(20)"


@pytest.fixture(scope="module")
def cards() -> list[StrategyCard]:
    return round42.build()


@pytest.fixture(scope="module")
def by_id(cards: list[StrategyCard]) -> dict[str, StrategyCard]:
    return {c.agent_id: c for c in cards}


def test_card_count(cards: list[StrategyCard]) -> None:
    # family A (reclaim): 3 arms; family B (breakout): 2 arms.
    assert len(cards) == 5
    assert set(round42.FAMILIES) == {"reclaim", "breakout"}
    assert len(round42.FAMILIES["reclaim"]["arms"]) == 3
    assert len(round42.FAMILIES["breakout"]["arms"]) == 2


def test_agent_ids_match_pinned_names(by_id: dict[str, StrategyCard]) -> None:
    assert set(by_id) == set(_EXPECTED_ENTRY)


def test_all_cards_are_trading(cards: list[StrategyCard]) -> None:
    assert all(card.purpose is Purpose.TRADING for card in cards)


def test_all_cards_designed_through_cutoff(cards: list[StrategyCard]) -> None:
    assert all(card.designed_through == DESIGN_THROUGH for card in cards)


def test_entry_and_exit_parse(cards: list[StrategyCard]) -> None:
    for card in cards:
        grammar.parse(card.entry)
        grammar.parse(card.exit)


def test_rank_by_is_unset(cards: list[StrategyCard]) -> None:
    assert all(card.rank_by is None for card in cards)


def test_no_ticker_intersects_roth_union(cards: list[StrategyCard]) -> None:
    for card in cards:
        assert not (set(card.universe) & _EXPECTED_ROTH), card.agent_id


def test_universe_is_taxable_growth_verbatim(cards: list[StrategyCard]) -> None:
    expected = (
        "NVDA", "TSM", "MU", "AMD", "QCOM", "MSFT", "GOOGL", "AMZN", "NFLX", "ORCL", "INTC", "TXN",
    )
    for card in cards:
        assert card.universe == expected, card.agent_id


def test_entries_match_pinned_literal_text(by_id: dict[str, StrategyCard]) -> None:
    for agent_id, expected_entry in _EXPECTED_ENTRY.items():
        assert by_id[agent_id].entry == expected_entry, agent_id


def test_control_entries_are_the_pinned_control_text(by_id: dict[str, StrategyCard]) -> None:
    assert by_id["r42-reclaim-control"].entry == "close crosses_above swing_low(20)"
    assert by_id["r42-breakout-control"].entry == "close crosses_above swing_high(20)"


def test_exit_is_fixed_per_family(by_id: dict[str, StrategyCard]) -> None:
    reclaim_ids = ("r42-reclaim-control", "r42-reclaim-wick", "r42-reclaim-wick-body")
    breakout_ids = ("r42-breakout-control", "r42-breakout-q25")
    assert {by_id[a].exit for a in reclaim_ids} == {_RECLAIM_EXIT}
    assert {by_id[a].exit for a in breakout_ids} == {_BREAKOUT_EXIT}
    # the two exits differ -- a family's exit is not shared with the other family.
    assert _RECLAIM_EXIT != _BREAKOUT_EXIT


def test_disciplines_match_family(by_id: dict[str, StrategyCard]) -> None:
    from app.tournament.models import Discipline

    for agent_id in ("r42-reclaim-control", "r42-reclaim-wick", "r42-reclaim-wick-body"):
        assert by_id[agent_id].discipline is Discipline.MEAN_REVERSION, agent_id
    for agent_id in ("r42-breakout-control", "r42-breakout-q25"):
        assert by_id[agent_id].discipline is Discipline.BREAKOUT, agent_id


def test_brackets_fixed_across_every_card(cards: list[StrategyCard]) -> None:
    for card in cards:
        assert card.stop_loss_pct == Decimal("0.12"), card.agent_id
        assert card.take_profit_pct is None, card.agent_id
        assert card.max_hold_days == 150, card.agent_id
        assert card.max_positions == 3, card.agent_id
        assert card.position_pct == Decimal("0.25"), card.agent_id


def test_source_persona_left_none(cards: list[StrategyCard]) -> None:
    # Reserved for promoted persona drafts; this round names the persona in `thesis` instead.
    assert all(card.source_persona is None for card in cards)


def test_free_number_budget(cards: list[StrategyCard]) -> None:
    for card in cards:
        assert round42.free_numbers(card) <= 10, card.agent_id


def test_free_number_counts_match_pinned_table(by_id: dict[str, StrategyCard]) -> None:
    expected = {
        "r42-reclaim-control": 5,
        "r42-reclaim-wick": 5,
        "r42-reclaim-wick-body": 6,
        "r42-breakout-control": 5,
        "r42-breakout-q25": 6,
    }
    for agent_id, want in expected.items():
        assert round42.free_numbers(by_id[agent_id]) == want, agent_id


def test_build_is_deterministic() -> None:
    a = round42.build()
    b = round42.build()
    assert [c.model_dump_json() for c in a] == [c.model_dump_json() for c in b]


def test_on_disk_cards_round_trip() -> None:
    """If the field has been written, every on-disk card re-validates through StrategyCard."""
    out = round42.OUT
    if not out.is_dir():
        pytest.skip("field not written yet (run round42.py --write)")
    paths = sorted(out.glob("*.json"))
    assert len(paths) == 5
    for path in paths:
        card = StrategyCard.model_validate_json(path.read_text(encoding="utf-8"))
        grammar.parse(card.entry)
        grammar.parse(card.exit)

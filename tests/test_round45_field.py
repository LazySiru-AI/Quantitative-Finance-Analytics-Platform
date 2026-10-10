"""Pins Round 45's pre-registered field (`strategy-program/tools/round45.py`).

`strategy-program` is not a legal Python package name (the hyphen), so `round45.py` is loaded by file
path here -- the identical precedent `tests/test_round40_field.py` and `tests/test_round42_field.py`
set for the same reason.

These tests are **fast and touch no bar store**: the reachability gate that measures firings against
the store runs inside the tool at `--write`, deliberately not in the suite (`pytest` cannot see the
store on a fresh checkout and must not depend on it). What is pinned here is the *field's shape and
construction*: the card count, the purpose, that every rule parses, the roth disjointness, that every
arm is built from its base by exactly the one substitution `ROUND-45-PLAN.md` names (never a second,
hand-typed copy), the fixed per-base brackets, the free-number budget, determinism, and the on-disk
round-trip. `check_drift()` (which reads the library card and the two vault drafts from disk) IS
exercised here -- those are small, checked-in JSON files, not the bar store, so it is cheap and the
suite must not silently drift from them.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from app.rules import grammar
from app.tournament.models import DESIGN_THROUGH, Discipline, StrategyCard
from app.tournament.purposes import Purpose

_spec = importlib.util.spec_from_file_location(
    "round45",
    str(Path(__file__).resolve().parents[1] / "strategy-program" / "tools" / "round45.py"),
)
assert _spec is not None and _spec.loader is not None
round45 = importlib.util.module_from_spec(_spec)
sys.modules["round45"] = round45
_spec.loader.exec_module(round45)


#: The live roth union (21 tickers) is recomputed from disk by the tool; hardcoded here only so the
#: test needs no library read -- the identical set `test_round40_field.py` / `test_round42_field.py`
#: hardcode, and for the same reason: the suite must not depend on library state a concurrent session
#: may edit.
_EXPECTED_ROTH = frozenset(
    {
        "AAPL", "ADBE", "AMAT", "BND", "CRM", "CSCO", "IGV", "INTU", "ITA", "KLAC", "LRCX",
        "SSO", "VIG", "VNQ", "VUG", "XBI", "XHB", "XME", "XOP", "XRT", "XSD",
    }
)

_UNIVERSE = ("NVDA", "TSM", "MU", "AMD", "QCOM", "MSFT", "GOOGL", "AMZN", "NFLX", "ORCL", "INTC", "TXN")

#: Every agent_id the round must build: 5 arms on kim and wsaj, 4 on bee (no trend100).
_EXPECTED_IDS = {
    "r45-kim-base", "r45-kim-trend100", "r45-kim-rr5", "r45-kim-risk1pct", "r45-kim-trim115",
    "r45-bee-base", "r45-bee-rr5", "r45-bee-risk1pct", "r45-bee-trim115",
    "r45-wsaj-base", "r45-wsaj-trend100", "r45-wsaj-rr5", "r45-wsaj-risk1pct", "r45-wsaj-trim115",
}

_BASE_ENTRY = {
    "kim": "close crosses_above bb_mid(20, 2) and rsi(14) > rsi_at_swing_high(14, 10)",
    "bee": "close > sma(100) and ema(12) crosses_above ema(50)",
    "wsaj": "close > sma(200) and close < bb_lower(26, 2)",
}
_BASE_EXIT = {
    "kim": "close crosses_below bb_mid(20, 2)",
    "bee": "ema(12) crosses_below ema(50)",
    "wsaj": "close crosses_above bb_mid(26, 2)",
}
_BASE_STOP = {"kim": Decimal("0.12"), "bee": Decimal("0.08"), "wsaj": Decimal("0.12")}
_BASE_TP = {"kim": None, "bee": Decimal("0.16"), "wsaj": None}
_BASE_HOLD = {"kim": 150, "bee": 30, "wsaj": 150}
_BASE_SLOTS = {"kim": 6, "bee": 5, "wsaj": 4}
_BASE_POSITION_PCT = {"kim": Decimal("0.125"), "bee": Decimal("0.15"), "wsaj": Decimal("0.20")}
_BASE_DISCIPLINE = {
    "kim": Discipline.MOMENTUM, "bee": Discipline.TREND, "wsaj": Discipline.MEAN_REVERSION,
}


@pytest.fixture(scope="module")
def cards() -> list[StrategyCard]:
    return round45.build()


@pytest.fixture(scope="module")
def by_id(cards: list[StrategyCard]) -> dict[str, StrategyCard]:
    return {c.agent_id: c for c in cards}


def test_card_count(cards: list[StrategyCard]) -> None:
    assert len(cards) == 14


def test_agent_ids_match_pinned_names(by_id: dict[str, StrategyCard]) -> None:
    assert set(by_id) == _EXPECTED_IDS


def test_bee_has_no_trend100_cell(by_id: dict[str, StrategyCard]) -> None:
    assert "r45-bee-trend100" not in by_id
    assert "trend100" not in round45.arms_for("bee")
    assert "trend100" in round45.arms_for("kim")
    assert "trend100" in round45.arms_for("wsaj")


def test_all_cards_are_trading(cards: list[StrategyCard]) -> None:
    assert all(card.purpose is Purpose.TRADING for card in cards)


def test_all_cards_designed_through_cutoff(cards: list[StrategyCard]) -> None:
    assert all(card.designed_through == DESIGN_THROUGH for card in cards)


def test_rank_by_is_unset(cards: list[StrategyCard]) -> None:
    assert all(card.rank_by is None for card in cards)


def test_entry_and_exit_parse(cards: list[StrategyCard]) -> None:
    for card in cards:
        grammar.parse(card.entry)
        grammar.parse(card.exit)


def test_universe_is_taxable_growth_verbatim(cards: list[StrategyCard]) -> None:
    for card in cards:
        assert card.universe == _UNIVERSE, card.agent_id


def test_no_ticker_intersects_roth_union(cards: list[StrategyCard]) -> None:
    for card in cards:
        assert not (set(card.universe) & _EXPECTED_ROTH), card.agent_id


def test_discipline_matches_base(by_id: dict[str, StrategyCard]) -> None:
    for base_key, discipline in _BASE_DISCIPLINE.items():
        for arm in round45.arms_for(base_key):
            assert by_id[f"r45-{base_key}-{arm}"].discipline is discipline, f"{base_key}-{arm}"


# ---------------------------------------------------------------------------
# Base cells equal the pinned base field.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("base_key", ["kim", "bee", "wsaj"])
def test_base_cell_matches_pinned_field(by_id: dict[str, StrategyCard], base_key: str) -> None:
    card = by_id[f"r45-{base_key}-base"]
    assert card.entry == _BASE_ENTRY[base_key]
    assert card.exit == _BASE_EXIT[base_key]
    assert card.stop_loss_pct == _BASE_STOP[base_key]
    assert card.take_profit_pct == _BASE_TP[base_key]
    assert card.max_hold_days == _BASE_HOLD[base_key]
    assert card.max_positions == _BASE_SLOTS[base_key]
    assert card.position_pct == _BASE_POSITION_PCT[base_key]


# ---------------------------------------------------------------------------
# Construction-by-composition: every arm is built from its base by exactly the one substitution
# ROUND-45-PLAN.md names, never a second hand-typed copy.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("base_key", ["kim", "wsaj"])
def test_trend100_is_base_entry_plus_sma100_conjunct(by_id: dict[str, StrategyCard], base_key: str) -> None:
    base = by_id[f"r45-{base_key}-base"]
    arm = by_id[f"r45-{base_key}-trend100"]
    assert arm.entry == base.entry + " and close > sma(100)"
    # nothing else changed
    assert arm.exit == base.exit
    assert arm.stop_loss_pct == base.stop_loss_pct
    assert arm.take_profit_pct == base.take_profit_pct
    assert arm.max_hold_days == base.max_hold_days
    assert arm.max_positions == base.max_positions
    assert arm.position_pct == base.position_pct


@pytest.mark.parametrize("base_key", ["kim", "bee", "wsaj"])
def test_rr5_take_profit_is_5x_stop_nothing_else_changed(
    by_id: dict[str, StrategyCard], base_key: str
) -> None:
    base = by_id[f"r45-{base_key}-base"]
    arm = by_id[f"r45-{base_key}-rr5"]
    assert arm.take_profit_pct == Decimal("5") * base.stop_loss_pct
    assert arm.entry == base.entry
    assert arm.exit == base.exit
    assert arm.stop_loss_pct == base.stop_loss_pct
    assert arm.max_hold_days == base.max_hold_days
    assert arm.max_positions == base.max_positions
    assert arm.position_pct == base.position_pct


def test_rr5_pinned_take_profit_values(by_id: dict[str, StrategyCard]) -> None:
    assert by_id["r45-kim-rr5"].take_profit_pct == Decimal("0.60")
    assert by_id["r45-bee-rr5"].take_profit_pct == Decimal("0.40")
    assert by_id["r45-wsaj-rr5"].take_profit_pct == Decimal("0.60")


@pytest.mark.parametrize("base_key", ["kim", "bee", "wsaj"])
def test_risk1pct_position_pct_is_001_over_stop_nothing_else_changed(
    by_id: dict[str, StrategyCard], base_key: str
) -> None:
    base = by_id[f"r45-{base_key}-base"]
    arm = by_id[f"r45-{base_key}-risk1pct"]
    expected = (Decimal("0.01") / base.stop_loss_pct).quantize(Decimal("0.001"))
    assert arm.position_pct == expected
    assert arm.max_positions == base.max_positions  # slots unchanged
    assert arm.entry == base.entry
    assert arm.exit == base.exit
    assert arm.stop_loss_pct == base.stop_loss_pct
    assert arm.take_profit_pct == base.take_profit_pct
    assert arm.max_hold_days == base.max_hold_days


def test_risk1pct_pinned_position_pct_values(by_id: dict[str, StrategyCard]) -> None:
    assert by_id["r45-kim-risk1pct"].position_pct == Decimal("0.083")
    assert by_id["r45-bee-risk1pct"].position_pct == Decimal("0.125")
    assert by_id["r45-wsaj-risk1pct"].position_pct == Decimal("0.083")


@pytest.mark.parametrize("base_key", ["kim", "bee", "wsaj"])
def test_trim115_exit_is_base_exit_plus_sma200_clause_nothing_else_changed(
    by_id: dict[str, StrategyCard], base_key: str
) -> None:
    base = by_id[f"r45-{base_key}-base"]
    arm = by_id[f"r45-{base_key}-trim115"]
    assert arm.exit == base.exit + " or close > sma(200) * 1.15"
    assert arm.entry == base.entry
    assert arm.stop_loss_pct == base.stop_loss_pct
    assert arm.take_profit_pct == base.take_profit_pct
    assert arm.max_hold_days == base.max_hold_days
    assert arm.max_positions == base.max_positions
    assert arm.position_pct == base.position_pct


def test_wsaj_hold_cap_disclosed_deviation_from_draft(by_id: dict[str, StrategyCard]) -> None:
    # The draft says 252; round 45 pins 150 (capped to the 9-month trading mandate). Not a drift bug.
    assert by_id["r45-wsaj-base"].max_hold_days == 150


# ---------------------------------------------------------------------------
# Drift asserts against the library card and the two vault drafts.
# ---------------------------------------------------------------------------

def test_no_drift_against_library_card_and_vault_drafts() -> None:
    drafts = [round45.REPO / spec["drift_source"] for key, spec in round45.BASES.items() if key != "kim"]
    if not all(path.is_file() for path in drafts):
        pytest.skip("personal vault drafts are not present in this checkout")
    problems = round45.check_drift()
    assert problems == [], problems


# ---------------------------------------------------------------------------
# Parameter budget.
# ---------------------------------------------------------------------------

def test_free_number_budget(cards: list[StrategyCard]) -> None:
    for card in cards:
        assert round45.free_numbers(card) <= 10, card.agent_id


def test_free_number_counts_match_pinned_table(by_id: dict[str, StrategyCard]) -> None:
    expected = {
        "r45-kim-base": 8, "r45-kim-trend100": 9, "r45-kim-rr5": 9, "r45-kim-risk1pct": 8,
        "r45-kim-trim115": 10,
        "r45-bee-base": 8, "r45-bee-rr5": 8, "r45-bee-risk1pct": 8, "r45-bee-trim115": 10,
        "r45-wsaj-base": 7, "r45-wsaj-trend100": 8, "r45-wsaj-rr5": 8, "r45-wsaj-risk1pct": 7,
        "r45-wsaj-trim115": 8,
    }
    for agent_id, want in expected.items():
        assert round45.free_numbers(by_id[agent_id]) == want, agent_id


# ---------------------------------------------------------------------------
# Determinism and on-disk round trip.
# ---------------------------------------------------------------------------

def test_build_is_deterministic() -> None:
    a = round45.build()
    b = round45.build()
    assert [c.model_dump_json() for c in a] == [c.model_dump_json() for c in b]


def test_on_disk_cards_round_trip() -> None:
    """If the field has been written, every on-disk card re-validates through StrategyCard."""
    out = round45.OUT
    if not out.is_dir():
        pytest.skip("field not written yet (run round45.py --write)")
    paths = sorted(out.glob("*.json"))
    assert len(paths) == 14
    for path in paths:
        card = StrategyCard.model_validate_json(path.read_text(encoding="utf-8"))
        grammar.parse(card.entry)
        grammar.parse(card.exit)

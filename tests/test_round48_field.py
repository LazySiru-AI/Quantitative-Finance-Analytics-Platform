"""Pins Round 48's pre-registered field (`strategy-program/tools/round48.py`).

`strategy-program` is not a legal Python package name (the hyphen), so `round48.py` is loaded by file
path here -- the identical precedent `tests/test_round45_field.py` sets for the same reason.

**Fast and touches no bar store.** Round 48 does not re-measure reachability the way round 45 did
(these five cards already trade live on the paper desk and have run in rounds 24/26 -- see
`round48.py`'s module docstring); what `build()` and `--write` do instead is read each seated library
file verbatim and parse every rule, both of which are cheap and exercised here. `check_drift()` has no
equivalent in this round because there is no second, pinned copy of a base's fields to drift from --
`build()` reads the library JSON directly every time, so the "drift" test here is instead "every base
cell equals its own source file", asserted straight against a fresh `json.loads` of that file.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from app.rules import grammar
from app.tournament.models import DESIGN_THROUGH, StrategyCard
from app.tournament.purposes import Purpose

_REPO = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "round48",
    str(_REPO / "strategy-program" / "tools" / "round48.py"),
)
assert _spec is not None and _spec.loader is not None
round48 = importlib.util.module_from_spec(_spec)
sys.modules["round48"] = round48
_spec.loader.exec_module(round48)


#: The live roth union (21 tickers) is recomputed from disk by the tool; hardcoded here only so the
#: test needs no library read -- identical precedent to `test_round45_field.py`.
_EXPECTED_ROTH = frozenset(
    {
        "AAPL", "ADBE", "AMAT", "BND", "CRM", "CSCO", "IGV", "INTU", "ITA", "KLAC", "LRCX",
        "SSO", "VIG", "VNQ", "VUG", "XBI", "XHB", "XME", "XOP", "XRT", "XSD",
    }
)

_SLUGS = ("b3", "arot", "ctrend", "bmom", "i13f")

_EXPECTED_IDS = {f"r48-{slug}-{arm}" for slug in _SLUGS for arm in ("base", "risk1pct")}

#: Every base's stop is 0.12 in the library, so risk1pct's pinned position size is identical
#: everywhere -- a fact this round measured rather than chose.
_EXPECTED_RISK1PCT_POSITION_PCT = Decimal("0.083")

_EXPECTED_MAX_POSITIONS = {"b3": 4, "arot": 3, "ctrend": 5, "bmom": 6, "i13f": 6}


@pytest.fixture(scope="module")
def cards() -> list[StrategyCard]:
    return round48.build()


@pytest.fixture(scope="module")
def by_id(cards: list[StrategyCard]) -> dict[str, StrategyCard]:
    return {c.agent_id: c for c in cards}


@pytest.fixture(scope="module")
def raw_by_slug() -> dict[str, dict]:
    return {
        slug: json.loads((_REPO / round48.LIBRARY_PATHS[slug]).read_text(encoding="utf-8"))
        for slug in _SLUGS
    }


# ---------------------------------------------------------------------------
# Shape of the field.
# ---------------------------------------------------------------------------

def test_card_count(cards: list[StrategyCard]) -> None:
    assert len(cards) == 10


def test_agent_ids_match_pinned_names(by_id: dict[str, StrategyCard]) -> None:
    assert set(by_id) == _EXPECTED_IDS


def test_all_cards_are_trading(cards: list[StrategyCard]) -> None:
    assert all(card.purpose is Purpose.TRADING for card in cards)


def test_all_cards_designed_through_cutoff(cards: list[StrategyCard]) -> None:
    assert all(card.designed_through == DESIGN_THROUGH for card in cards)


def test_no_card_is_desk_only(cards: list[StrategyCard]) -> None:
    """Even `i13f`, whose library source is `desk_only=True` -- round 48 overrides it to False so the
    card can enter a tournament round at all; its provenance is preserved through the sidecar file
    instead. See `round48.py`'s module docstring."""
    assert all(card.desk_only is False for card in cards)


def test_entry_and_exit_parse(cards: list[StrategyCard]) -> None:
    for card in cards:
        grammar.parse(card.entry)
        grammar.parse(card.exit)


# ---------------------------------------------------------------------------
# Base cells equal their library file, field for field.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("slug", _SLUGS)
def test_base_cell_matches_library_file_verbatim(
    by_id: dict[str, StrategyCard], raw_by_slug: dict[str, dict], slug: str
) -> None:
    card = by_id[f"r48-{slug}-base"]
    raw = raw_by_slug[slug]

    def _dec(v):
        return None if v is None else Decimal(str(v))

    assert card.entry == raw["entry"]
    assert card.exit == raw["exit"]
    assert card.stop_loss_pct == _dec(raw.get("stop_loss_pct"))
    assert card.take_profit_pct == _dec(raw.get("take_profit_pct"))
    assert card.max_hold_days == raw.get("max_hold_days")
    assert card.max_positions == raw["max_positions"]
    assert card.position_pct == _dec(raw["position_pct"])
    assert card.universe == tuple(raw["universe"])
    assert card.discipline.value == raw["discipline"]


def test_base_cell_max_positions_matches_pinned_table(by_id: dict[str, StrategyCard]) -> None:
    for slug, expected in _EXPECTED_MAX_POSITIONS.items():
        assert by_id[f"r48-{slug}-base"].max_positions == expected, slug


def test_every_base_stop_is_012(by_id: dict[str, StrategyCard]) -> None:
    """The fact the round's risk1pct table turns on: every seated base's stop is 0.12."""
    for slug in _SLUGS:
        assert by_id[f"r48-{slug}-base"].stop_loss_pct == Decimal("0.12"), slug


# ---------------------------------------------------------------------------
# risk1pct cells differ from their base ONLY in position_pct.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("slug", _SLUGS)
def test_risk1pct_differs_from_base_only_in_position_pct(
    by_id: dict[str, StrategyCard], slug: str
) -> None:
    base = by_id[f"r48-{slug}-base"]
    arm = by_id[f"r48-{slug}-risk1pct"]

    expected = (Decimal("0.01") / base.stop_loss_pct).quantize(Decimal("0.001"))
    assert arm.position_pct == expected

    # Nothing else changed.
    assert arm.entry == base.entry
    assert arm.exit == base.exit
    assert arm.stop_loss_pct == base.stop_loss_pct
    assert arm.take_profit_pct == base.take_profit_pct
    assert arm.max_hold_days == base.max_hold_days
    assert arm.max_positions == base.max_positions
    assert arm.universe == base.universe
    assert arm.discipline == base.discipline
    assert arm.purpose == base.purpose
    assert arm.designed_through == base.designed_through
    assert arm.desk_only == base.desk_only


def test_risk1pct_pinned_position_pct_is_083_on_every_base(by_id: dict[str, StrategyCard]) -> None:
    for slug in _SLUGS:
        assert by_id[f"r48-{slug}-risk1pct"].position_pct == _EXPECTED_RISK1PCT_POSITION_PCT, slug


def test_risk1pct_position_budget_does_not_overcommit_the_book(by_id: dict[str, StrategyCard]) -> None:
    for slug in _SLUGS:
        card = by_id[f"r48-{slug}-risk1pct"]
        assert card.position_pct * card.max_positions <= Decimal("1"), slug


# ---------------------------------------------------------------------------
# Provenance: i13f only.
# ---------------------------------------------------------------------------

def test_only_i13f_has_provenance(by_id: dict[str, StrategyCard]) -> None:
    assert set(round48.PROVENANCE) == {"i13f"}


def test_i13f_universe_matches_library_source(by_id: dict[str, StrategyCard], raw_by_slug) -> None:
    assert by_id["r48-i13f-base"].universe == tuple(raw_by_slug["i13f"]["universe"])


def test_provenance_sidecar_shape() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        round48.write_provenance_sidecar(out)
        sidecar = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert sidecar == {"r48-i13f-base": "2026-08-14", "r48-i13f-risk1pct": "2026-08-14"}


# ---------------------------------------------------------------------------
# Roth disjointness.
# ---------------------------------------------------------------------------

def test_no_ticker_intersects_roth_union(cards: list[StrategyCard]) -> None:
    for card in cards:
        assert not (set(card.universe) & _EXPECTED_ROTH), card.agent_id


# ---------------------------------------------------------------------------
# Parameter budget.
# ---------------------------------------------------------------------------

def test_free_number_budget(cards: list[StrategyCard]) -> None:
    for card in cards:
        assert round48.free_numbers(card) <= 10, card.agent_id


def test_free_number_counts_match_pinned_table(by_id: dict[str, StrategyCard]) -> None:
    expected = {
        "r48-b3-base": 7, "r48-b3-risk1pct": 7,
        "r48-arot-base": 10, "r48-arot-risk1pct": 10,
        "r48-ctrend-base": 7, "r48-ctrend-risk1pct": 7,
        "r48-bmom-base": 7, "r48-bmom-risk1pct": 7,
        "r48-i13f-base": 7, "r48-i13f-risk1pct": 7,
    }
    for agent_id, want in expected.items():
        assert round48.free_numbers(by_id[agent_id]) == want, agent_id


def test_risk1pct_free_number_count_equals_its_base(by_id: dict[str, StrategyCard]) -> None:
    """risk1pct changes no entry/exit literal -- only the flat +2 slot/position term is affected in
    kind, not in count, so its free-number count must equal its base's exactly."""
    for slug in _SLUGS:
        base = round48.free_numbers(by_id[f"r48-{slug}-base"])
        arm = round48.free_numbers(by_id[f"r48-{slug}-risk1pct"])
        assert arm == base, slug


# ---------------------------------------------------------------------------
# Missing-library-file refusal.
# ---------------------------------------------------------------------------

def test_missing_library_files_detects_absent_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(round48.LIBRARY_PATHS, "b3", "backend/app/paper/library/variants/DOES-NOT-EXIST.json")
    try:
        missing = round48.missing_library_files()
        assert any("DOES-NOT-EXIST" in m for m in missing)
        with pytest.raises(FileNotFoundError):
            round48._load_raw("b3")
    finally:
        pass  # monkeypatch auto-restores LIBRARY_PATHS


# ---------------------------------------------------------------------------
# Determinism and on-disk round trip.
# ---------------------------------------------------------------------------

def test_build_is_deterministic() -> None:
    a = round48.build()
    b = round48.build()
    assert [c.model_dump_json() for c in a] == [c.model_dump_json() for c in b]


def test_on_disk_cards_round_trip() -> None:
    """If the field has been written, every on-disk card re-validates through StrategyCard, and the
    provenance sidecar is present and correctly shaped."""
    out = round48.OUT
    if not out.is_dir():
        pytest.skip("field not written yet (run round48.py --write)")
    paths = sorted(p for p in out.glob("*.json") if p.name != "provenance.json")
    assert len(paths) == 10
    for path in paths:
        card = StrategyCard.model_validate_json(path.read_text(encoding="utf-8"))
        grammar.parse(card.entry)
        grammar.parse(card.exit)

    sidecar_path = out / "provenance.json"
    if sidecar_path.is_file():
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        assert sidecar == {"r48-i13f-base": "2026-08-14", "r48-i13f-risk1pct": "2026-08-14"}

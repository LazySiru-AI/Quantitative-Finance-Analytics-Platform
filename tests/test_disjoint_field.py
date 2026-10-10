"""Tests for `strategy-program/tools/disjoint_field.py`.

`strategy-program` is not a legal Python package name (the hyphen), so `disjoint_field.py` is loaded
by file path here -- the identical precedent `tests/test_contributions.py` already set for
`strategy-program/tools/contributions.py`.

Fast, synthetic-card tests only: every card is built with `StrategyCard(...).model_dump_json()` so it
always validates, and written under `tmp_path`. Checks 1 (purpose) and 2 (ticker disjointness) need no
bar store at all; `--library-root` is always pointed at a synthetic, isolated directory (never the real
`backend/app/paper/library`) so these tests cannot be broken by another session editing the real
library concurrently, and cannot depend on what tickers the real library happens to hold today. Check 3
(window eligibility) is exercised only through `--skip-eligibility`'s exit-code behaviour -- these
tests never open the bar store.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from app.tournament.models import DESIGN_THROUGH, StrategyCard
from app.tournament.purposes import Purpose

_spec = importlib.util.spec_from_file_location(
    "disjoint_field",
    str(Path(__file__).resolve().parents[1] / "strategy-program" / "tools" / "disjoint_field.py"),
)
assert _spec is not None and _spec.loader is not None
disjoint_field = importlib.util.module_from_spec(_spec)
sys.modules["disjoint_field"] = disjoint_field
_spec.loader.exec_module(disjoint_field)


def make_card(
    agent_id: str,
    universe: tuple[str, ...],
    *,
    purpose: Purpose = Purpose.ROTH,
) -> StrategyCard:
    """A minimal, always-valid `StrategyCard` for a synthetic test fixture.

    `entry`/`exit` are placeholder strings, not real rule-DSL -- `StrategyCard`'s own validators never
    parse `entry`/`exit` at construction time (only `rank_by`, which this factory leaves `None`), so
    these need not be grammar-legal to build a valid card. They would need to be if a test ever ran the
    eligibility check for real, which none here do (`--skip-eligibility` throughout).
    """
    return StrategyCard(
        agent_id=agent_id,
        display_name=agent_id,
        discipline="trend",
        purpose=purpose,
        thesis=f"synthetic test fixture for {agent_id}",
        universe=universe,
        entry="close > 0",
        exit="close < 0",
        max_positions=2,
        position_pct=Decimal("0.3"),
        designed_through=DESIGN_THROUGH,
    )


def write_card(directory: Path, card: StrategyCard) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{card.agent_id}.json"
    path.write_text(card.model_dump_json(), encoding="utf-8")
    return path


def make_empty_library(tmp_path: Path, name: str = "empty-library") -> Path:
    """A library root with none of `TIERS`' four directories -- `load_library` treats a missing tier
    directory as an empty tier (see that function's own docstring), so this is a legitimate "no taxable
    cards exist" library, not a malformed one.
    """
    root = tmp_path / name
    root.mkdir()
    return root


def make_library_with_trading_card(tmp_path: Path, symbol: str) -> Path:
    """A synthetic library root holding exactly one `candidates/`-tier `trading`-purpose card, trading
    `symbol`. Isolated in its own `tmp_path` subdirectory so it never collides with `make_empty_library`
    or any other fixture in the same test.
    """
    root = tmp_path / "synthetic-library"
    card = make_card("synth-trading-1", (symbol,), purpose=Purpose.TRADING)
    write_card(root / "candidates", card)
    return root


# ---------------------------------------------------------------------------
# Check 1 + check 2: a clean Roth card against an empty taxable library
# ---------------------------------------------------------------------------


class TestCleanRothCardPasses:
    def test_checks_1_and_2_pass(self, tmp_path: Path) -> None:
        cards_dir = tmp_path / "field"
        write_card(cards_dir, make_card("roth-clean", ("XME", "XRT")))
        library_root = make_empty_library(tmp_path)

        rc = disjoint_field.main(
            [
                "--cards",
                str(cards_dir),
                "--skip-eligibility",
                "--library-root",
                str(library_root),
            ]
        )

        assert rc == 0

    def test_output_says_ok(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        cards_dir = tmp_path / "field"
        write_card(cards_dir, make_card("roth-clean", ("XME", "XRT")))
        library_root = make_empty_library(tmp_path)

        rc = disjoint_field.main(
            [
                "--cards",
                str(cards_dir),
                "--skip-eligibility",
                "--library-root",
                str(library_root),
            ]
        )

        out = capsys.readouterr().out
        assert rc == 0
        assert "OK" in out
        assert "FAIL" not in out


# ---------------------------------------------------------------------------
# Check 1: a non-roth card in the field
# ---------------------------------------------------------------------------


class TestNonRothCardFailsCheck1:
    def test_trading_card_in_field_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cards_dir = tmp_path / "field"
        write_card(cards_dir, make_card("field-trading", ("XME",), purpose=Purpose.TRADING))
        library_root = make_empty_library(tmp_path)

        rc = disjoint_field.main(
            [
                "--cards",
                str(cards_dir),
                "--skip-eligibility",
                "--library-root",
                str(library_root),
            ]
        )

        out = capsys.readouterr().out
        assert rc == 1
        assert "FAIL" in out
        assert "field-trading" in out
        assert "purpose=" in out

    def test_check_purpose_function_lists_the_offender_directly(self, tmp_path: Path) -> None:
        cards_dir = tmp_path / "field"
        path = write_card(cards_dir, make_card("field-trading", ("XME",), purpose=Purpose.TRADING))
        field = disjoint_field.load_field([cards_dir])

        offenders = disjoint_field.check_purpose(field)

        assert len(offenders) == 1
        assert "field-trading" in offenders[0]
        assert "trading" in offenders[0]
        assert path.exists()


# ---------------------------------------------------------------------------
# Check 2: a roth card colliding with a taxable library card
# ---------------------------------------------------------------------------


class TestTaxableOverlapFailsCheck2:
    def test_shared_ticker_is_named(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        cards_dir = tmp_path / "field"
        write_card(cards_dir, make_card("roth-colliding", ("ZQXW", "XME")))
        library_root = make_library_with_trading_card(tmp_path, "ZQXW")

        rc = disjoint_field.main(
            [
                "--cards",
                str(cards_dir),
                "--skip-eligibility",
                "--library-root",
                str(library_root),
            ]
        )

        out = capsys.readouterr().out
        assert rc == 1
        assert "FAIL" in out
        assert "ZQXW" in out
        assert "roth-colliding" in out
        # XME did not collide and must not be reported as if it had.
        assert "'XME'" not in out

    def test_both_independent_checks_agree(self, tmp_path: Path) -> None:
        cards_dir = tmp_path / "field"
        write_card(cards_dir, make_card("roth-colliding", ("ZQXW",)))
        library_root = make_library_with_trading_card(tmp_path, "ZQXW")

        field = disjoint_field.load_field([cards_dir])
        from app.tournament.results import load_library

        library = load_library(library_root)
        taxable = disjoint_field.taxable_ticker_set(library)

        direct = disjoint_field.check_taxable_overlap(field, taxable)
        violations = disjoint_field.run_disjointness_violations(field, library)

        assert len(direct) == 1
        assert "ZQXW" in direct[0]
        assert len(violations) == 1
        assert violations[0].symbol == "ZQXW"
        assert violations[0].roth_agent_id == "roth-colliding"
        assert violations[0].other_agent_id == "synth-trading-1"
        assert violations[0].other_purpose is Purpose.TRADING

    def test_savings_purpose_card_also_collides(self, tmp_path: Path) -> None:
        """The taxable set is built from both `savings` and `trading` cards, not `trading` alone."""
        cards_dir = tmp_path / "field"
        write_card(cards_dir, make_card("roth-colliding", ("ZQXW",)))
        library_root = tmp_path / "savings-library"
        write_card(
            library_root / "base",
            make_card("synth-savings-1", ("ZQXW",), purpose=Purpose.SAVINGS),
        )

        rc = disjoint_field.main(
            [
                "--cards",
                str(cards_dir),
                "--skip-eligibility",
                "--library-root",
                str(library_root),
            ]
        )

        assert rc == 1


# ---------------------------------------------------------------------------
# CLI exit-code contract
# ---------------------------------------------------------------------------


class TestMainReturnCode:
    def test_returns_zero_on_a_clean_field(self, tmp_path: Path) -> None:
        cards_dir = tmp_path / "field"
        write_card(cards_dir, make_card("ok-1", ("XHB",)))
        library_root = make_empty_library(tmp_path)

        rc = disjoint_field.main(
            [
                "--cards",
                str(cards_dir),
                "--skip-eligibility",
                "--library-root",
                str(library_root),
            ]
        )

        assert rc == 0

    def test_returns_one_when_both_checks_fail(self, tmp_path: Path) -> None:
        cards_dir = tmp_path / "field"
        write_card(cards_dir, make_card("bad-1", ("ZQXW",), purpose=Purpose.TRADING))
        library_root = make_library_with_trading_card(tmp_path, "ZQXW")

        rc = disjoint_field.main(
            [
                "--cards",
                str(cards_dir),
                "--skip-eligibility",
                "--library-root",
                str(library_root),
            ]
        )

        assert rc == 1

    def test_returns_one_on_empty_cards_directory(self, tmp_path: Path) -> None:
        cards_dir = tmp_path / "field"
        cards_dir.mkdir()
        library_root = make_empty_library(tmp_path)

        rc = disjoint_field.main(
            [
                "--cards",
                str(cards_dir),
                "--skip-eligibility",
                "--library-root",
                str(library_root),
            ]
        )

        assert rc == 1

    def test_returns_one_on_a_malformed_card_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cards_dir = tmp_path / "field"
        cards_dir.mkdir()
        (cards_dir / "broken.json").write_text("{not valid json", encoding="utf-8")
        library_root = make_empty_library(tmp_path)

        rc = disjoint_field.main(
            [
                "--cards",
                str(cards_dir),
                "--skip-eligibility",
                "--library-root",
                str(library_root),
            ]
        )

        out = capsys.readouterr().out
        assert rc == 1
        assert "FAIL" in out
        assert "broken.json" in out

    def test_provenance_sidecar_is_not_loaded_as_a_card(self, tmp_path: Path) -> None:
        """`provenance.json` (windows.py's sidecar) sits legitimately in a cards directory and must be
        skipped, not loaded as a malformed `StrategyCard`."""
        cards_dir = tmp_path / "field"
        write_card(cards_dir, make_card("ok-1", ("XHB",)))
        (cards_dir / "provenance.json").write_text("{}", encoding="utf-8")
        library_root = make_empty_library(tmp_path)

        rc = disjoint_field.main(
            [
                "--cards",
                str(cards_dir),
                "--skip-eligibility",
                "--library-root",
                str(library_root),
            ]
        )

        assert rc == 0

    def test_two_cards_directories_are_both_read(self, tmp_path: Path) -> None:
        dir_a = tmp_path / "field-a"
        dir_b = tmp_path / "field-b"
        write_card(dir_a, make_card("ok-a", ("XHB",)))
        write_card(dir_b, make_card("ok-b", ("XRT",)))
        library_root = make_empty_library(tmp_path)

        field = disjoint_field.load_field([dir_a, dir_b])

        assert {card.agent_id for _path, card in field} == {"ok-a", "ok-b"}

        rc = disjoint_field.main(
            [
                "--cards",
                str(dir_a),
                "--cards",
                str(dir_b),
                "--skip-eligibility",
                "--library-root",
                str(library_root),
            ]
        )
        assert rc == 0


# ---------------------------------------------------------------------------
# designed_through pinned to DESIGN_THROUGH, per the CLI brief
# ---------------------------------------------------------------------------


def test_fixture_cards_are_designed_through_the_real_cutoff() -> None:
    card = make_card("pin-check", ("XHB",))
    assert card.designed_through == DESIGN_THROUGH
    assert isinstance(DESIGN_THROUGH, dt.date)


# ---------------------------------------------------------------------------
# The taxable set covers the allocation/ladder tiers `load_library` does not walk
# ---------------------------------------------------------------------------


class TestAllocationAndLadderTiersAreCovered:
    """`load_purposed_library` must see a taxable ticker that exists *only* in `allocation/` or
    `ladder/` -- as of 2026-09-08 that is where AGG, BIL, QLD, SCHD and SGOV live -- because a set
    built from `load_library` alone is quietly short by exactly those five.
    """

    REAL_ALLOCATION_CARD = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "app"
        / "paper"
        / "library"
        / "allocation"
        / "qld-schd-sgov.json"
    )

    def test_allocation_tier_ticker_is_in_the_taxable_set(self, tmp_path: Path) -> None:
        if not self.REAL_ALLOCATION_CARD.is_file():
            pytest.skip("the committed allocation card this test copies is not present")
        root = tmp_path / "six-tier-library"
        (root / "allocation").mkdir(parents=True)
        (root / "allocation" / "qld-schd-sgov.json").write_text(
            self.REAL_ALLOCATION_CARD.read_text(encoding="utf-8"), encoding="utf-8"
        )

        library = disjoint_field.load_purposed_library(root)
        taxable = disjoint_field.taxable_ticker_set(library)

        assert "allocation" in library and "ladder" in library
        assert len(library["allocation"]) == 1
        assert {"QLD", "SCHD", "SGOV"} <= taxable.keys()
        # ...and a Roth field card naming one of them is caught by BOTH halves of check 2.
        field_dir = tmp_path / "field"
        write_card(field_dir, make_card("collides-with-allocation", ("SGOV", "XHB")))
        field = disjoint_field.load_field([field_dir])
        direct = disjoint_field.check_taxable_overlap(field, taxable)
        via_purposes = disjoint_field.run_disjointness_violations(field, library)
        assert len(direct) == 1 and "SGOV" in direct[0]
        assert [v.roth_agent_id for v in via_purposes] == ["collides-with-allocation"]

    def test_missing_extra_tiers_are_empty_not_errors(self, tmp_path: Path) -> None:
        library = disjoint_field.load_purposed_library(make_empty_library(tmp_path))
        assert library["allocation"] == [] and library["ladder"] == []

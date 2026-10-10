"""Tests for wiring `build_leaderboard` onto `ScoredRun` -- the fix for the 422
`/api/competition/rounds/r15-2026-08/leaderboard` returned before this change.

`app.tournament.results.load_round_results` validates every run file as an `AgentResult`
(`extra="forbid"`), which rejects an `AllocationResult`'s or `LadderResult`'s `"card"` payload
outright -- round 15's three trading cards (`qqq-ief-gld-atr-tilt`, `qqq-ief-gld-static`,
`ladder-qld-schd`) are two allocation cards and one ladder card, so the leaderboard endpoint 422'd
for that round specifically. `build_leaderboard` now reads `load_round_scored_runs` instead, which
already parses all three run-file shapes (`ScoredRun`, added in an earlier task -- see
`tests/test_results_scored_run.py`).

Four things this file exists to prove, each tied to a specific hazard in the task brief:

1. **The 422 is gone.** `TestR15LeaderboardIsNoLongerA422` hits the real, committed r15 round and
   gets a populated 200 back.
2. **`ExposureBasisError` is never swallowed into a numeric fallback.** No allocation or ladder row's
   per-window cell carries an `adjusted_excess` -- it is `null` on the wire, not a number computed
   against an exposure figure (`capital_exposure` denominated in invested value over current equity)
   that `adjusted_excess`'s formula does not mean what it assumes.
3. **`rank_by="excess-per-exposure"` is refused for an all-invested-value field**, rather than
   answered with a ratio whose denominator sits near a constant `1.0` and has stopped discriminating
   between strategies. r15 is entirely invested-value, so this is exercised directly against real
   data, no synthetic fixture required.
4. **A field mixing both exposure bases is never ranked as one table.** No committed round mixes them
   today, so `TestMixedBasisField` builds one: `build_leaderboard` must rank only the larger group and
   name the smaller group's excluded agent ids in `unscored_reason`, never blend the two orderings
   into one column and never drop a card silently.

A fifth thing, `r1`-`r14`'s leaderboard must be byte-identical to what it was before this change, is
proved separately by `TestR14LeaderboardIsUnchanged` below: the expected bodies were captured from the
real endpoint *before* `build_leaderboard` was touched (a `TestClient` run against the pre-change
code, saved as canonical JSON and hashed with sha256) and are pinned here as literals, so a future
change to the ranking arithmetic -- for either exposure basis -- will fail this test loudly rather
than silently drift.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import competition as competition_api
from app.tournament import results
from app.tournament.allocation import AllocationCard, AllocationResult, Sleeve
from app.tournament.models import AgentResult, Discipline, StrategyCard

# ---------------------------------------------------------------------------
# App + fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(competition_api.router)
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _canonical_json_sha256(body: object) -> str:
    canon = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canon).hexdigest()


# ---------------------------------------------------------------------------
# 1-3. Real r15 data: the 422 is gone, adjusted_excess is never faked, and
# excess-per-exposure is refused for an all-invested-value field
# ---------------------------------------------------------------------------

_R15_ROOT = Path("data") / "rounds" / "r15-2026-08"


@pytest.mark.skipif(not _R15_ROOT.is_dir(), reason="data/rounds/r15-2026-08 not present")
class TestR15LeaderboardIsNoLongerA422:
    def test_default_leaderboard_returns_200_with_three_rows(self, client: TestClient) -> None:
        response = client.get("/api/competition/rounds/r15-2026-08/leaderboard")
        assert response.status_code == 200
        body = response.json()
        assert len(body["rows"]) == 3
        assert {r["agent_id"] for r in body["rows"]} == {
            "qqq-ief-gld-atr-tilt",
            "qqq-ief-gld-static",
            "ladder-qld-schd",
        }
        assert body["unscored_reason"] is None

    def test_scoring_basis_names_the_invested_value_basis(self, client: TestClient) -> None:
        response = client.get("/api/competition/rounds/r15-2026-08/leaderboard")
        assert response.json()["scoring_basis"] == "excess"

    def test_no_row_carries_an_adjusted_excess_anywhere(self, client: TestClient) -> None:
        """The trap: a reader checking `if adjusted_excess is not None` must never find a number
        here for an invested-value card -- `ExposureBasisError` is raised inside
        `results._scored_run_to_cell`'s basis check, not caught and papered over with `None` produced
        by some other path that also happens to look like `None`."""
        response = client.get("/api/competition/rounds/r15-2026-08/leaderboard")
        body = response.json()
        assert body["rows"], "expected r15's three trading cards"
        checked_cells = 0
        for row in body["rows"]:
            for window, cell in row["per_window"].items():
                assert cell["adjusted_excess"] is None, (row["agent_id"], window)
                checked_cells += 1
        assert checked_cells > 0

    def test_excess_still_populates_every_cell(self, client: TestClient) -> None:
        """Losing `adjusted_excess` must not take plain `excess` down with it -- `excess` carries no
        claim about capital at risk, so nothing about the basis mismatch corrupts it."""
        response = client.get("/api/competition/rounds/r15-2026-08/leaderboard")
        body = response.json()
        for row in body["rows"]:
            for cell in row["per_window"].values():
                assert cell["excess"] is not None

    def test_excess_per_exposure_is_refused_for_an_all_invested_value_round(
        self, client: TestClient
    ) -> None:
        response = client.get(
            "/api/competition/rounds/r15-2026-08/leaderboard?rank_by=excess-per-exposure"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["rows"] == []
        assert body["unscored_reason"] is not None
        assert "excess-per-exposure" in body["unscored_reason"]
        assert "invested-value" in body["unscored_reason"]

    @pytest.mark.parametrize("rank_by", ["median", "worst", "hit-rate"])
    def test_the_other_three_rank_by_choices_still_work(
        self, client: TestClient, rank_by: str
    ) -> None:
        response = client.get(
            f"/api/competition/rounds/r15-2026-08/leaderboard?rank_by={rank_by}"
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["rows"]) == 3
        assert [r["rank"] for r in body["rows"]] == [1, 2, 3]


# ---------------------------------------------------------------------------
# 4. r14 (and r5) are byte-identical to before this change
# ---------------------------------------------------------------------------

_R14_ROOT = Path("data") / "rounds" / "r14-2026-08"
_R5_ROOT = Path("data") / "rounds" / "r5-2026-08"

# Captured via a `TestClient` run against `build_leaderboard` *before* it was wired onto
# `ScoredRun` (i.e. while it still called `load_round_results`), one hash per `rank_by` choice --
# see this file's own module docstring for exactly how. `r5-2026-08` is included too even though the
# task only requires r14, because its 405-run-file results tree is the one the task's own
# performance numbers (254ms / 356ms) are measured against, so pinning its output is the same proof
# applied to the larger tree.
_PRE_CHANGE_SHA256 = {
    ("r14-2026-08", "median"): "40012be6555d6bc3e7e0f1803b03d8cc23bc92f0c77ecb232e426e4234819198",
    ("r14-2026-08", "worst"): "5afb9a77d1e02085b4c5ff6d0b009270f533d4a5526d84f4cae96c465aeb05cc",
    ("r14-2026-08", "hit-rate"): "8af0add0df3db5029753b809424cb3ea6b25e564272376e84e71d9eb3bbf8ee3",
    ("r14-2026-08", "excess-per-exposure"): (
        "ecd7eeec46b83b6acdea028f379713ee5032a070b5b1477a4f7daa7a3874ba59"
    ),
    ("r5-2026-08", "median"): "5f5d67d82b8f87955691513eaa79b30c370504b35cc1b5c67a42c56e9729efe2",
    ("r5-2026-08", "worst"): "cfdf64b090e34b70a7c9086ade4bf7ff913db3465b1044115ec80d118db915da",
    ("r5-2026-08", "hit-rate"): "ff9580e6d4321edcbb8ff28e7b06a83dff4485959879fd195d4692bb6b06050f",
    ("r5-2026-08", "excess-per-exposure"): (
        "0cc503f335ba558e51160421e2fb0cf117446916728912da0154cd5f2a51ea7e"
    ),
}


class TestR14LeaderboardIsUnchanged:
    """The regression that matters most: r14 (and r5) are entirely `entry-notional`, and this task
    must not move a single figure they already reported."""

    @pytest.mark.skipif(not _R14_ROOT.is_dir(), reason="data/rounds/r14-2026-08 not present")
    @pytest.mark.parametrize("rank_by", ["median", "worst", "hit-rate", "excess-per-exposure"])
    def test_r14_leaderboard_matches_the_pre_change_capture(
        self, client: TestClient, rank_by: str
    ) -> None:
        response = client.get(
            f"/api/competition/rounds/r14-2026-08/leaderboard?rank_by={rank_by}"
        )
        assert response.status_code == 200
        assert _canonical_json_sha256(response.json()) == _PRE_CHANGE_SHA256[
            ("r14-2026-08", rank_by)
        ]

    @pytest.mark.skipif(not _R5_ROOT.is_dir(), reason="data/rounds/r5-2026-08 not present")
    @pytest.mark.parametrize("rank_by", ["median", "worst", "hit-rate", "excess-per-exposure"])
    def test_r5_leaderboard_matches_the_pre_change_capture(
        self, client: TestClient, rank_by: str
    ) -> None:
        """r5 holds the 405-run-file tree the task's own latency figures are measured against."""
        response = client.get(
            f"/api/competition/rounds/r5-2026-08/leaderboard?rank_by={rank_by}"
        )
        assert response.status_code == 200
        assert _canonical_json_sha256(response.json()) == _PRE_CHANGE_SHA256[
            ("r5-2026-08", rank_by)
        ]


# ---------------------------------------------------------------------------
# 5. A field mixing both exposure bases is never ranked as one table
# ---------------------------------------------------------------------------


def _stock_picking_run(agent_id: str) -> AgentResult:
    return AgentResult(
        card=StrategyCard(
            agent_id=agent_id,
            display_name=f"{agent_id} card",
            discipline=Discipline.MOMENTUM,
            thesis="Momentum persists for several sessions after a volume-confirmed breakout.",
            universe=("AAPL",),
            entry="close > sma(20)",
            exit="close < sma(20)",
            max_positions=4,
            position_pct=Decimal("0.25"),
            designed_through=dt.date(2026, 2, 10),
        ),
        sessions=100,
        starting_equity=Decimal("10000.00"),
        ending_equity=Decimal("11000.00"),
        total_return=Decimal("0.10"),
        max_drawdown=Decimal("0.05"),
        capital_exposure=0.4,
        exposure=0.8,
        benchmark_return=Decimal("0.05"),
    )


def _allocation_run(agent_id: str) -> AllocationResult:
    return AllocationResult(
        card=AllocationCard(
            agent_id=agent_id,
            display_name=f"{agent_id} card",
            thesis="A constant-weight two-sleeve book rebalanced back to target on drift.",
            sleeves=(
                Sleeve(symbol="QLD", target_weight=Decimal("0.60")),
                Sleeve(symbol="SCHD", target_weight=Decimal("0.40")),
            ),
            band_pct=Decimal("0.05"),
            designed_through=dt.date(2026, 2, 10),
        ),
        sessions=100,
        starting_equity=Decimal("10000.00"),
        ending_equity=Decimal("12000.00"),
        total_return=Decimal("0.20"),
        max_drawdown=Decimal("0.10"),
        capital_exposure=0.97,
        exposure=1.0,
        benchmark_return=Decimal("0.05"),
    )


def _write_run(runs_dir: Path, agent_id: str, run: AgentResult | AllocationResult) -> None:
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"r1-{agent_id}.json").write_text(run.model_dump_json(), encoding="utf-8")


class TestMixedBasisField:
    """No committed round mixes `entry-notional` and `invested-value` cards for the same purpose
    today -- this builds the case synthetically to pin the policy `build_leaderboard` chose (point 3
    of the task brief): rank only the larger group, name the smaller group's agent ids in
    `unscored_reason`, and never blend the two orderings into one ranked column.
    """

    def test_entry_notional_majority_excludes_the_invested_value_minority(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client: TestClient
    ) -> None:
        runs_dir = tmp_path / "r-mixed-a" / "results" / "gfc" / "runs"
        _write_run(runs_dir, "picker-1", _stock_picking_run("picker-1"))
        _write_run(runs_dir, "picker-2", _stock_picking_run("picker-2"))
        _write_run(runs_dir, "alloc-1", _allocation_run("alloc-1"))
        monkeypatch.setattr(results, "ROUNDS_ROOT", tmp_path)

        response = client.get("/api/competition/rounds/r-mixed-a/leaderboard")
        assert response.status_code == 200
        body = response.json()

        assert {r["agent_id"] for r in body["rows"]} == {"picker-1", "picker-2"}
        assert body["scoring_basis"] == "adjusted_excess"
        assert body["unscored_reason"] is not None
        assert "alloc-1" in body["unscored_reason"]
        assert "invested-value" in body["unscored_reason"]
        # Ranks are still dense over the ranked field, not the whole round.
        assert [r["rank"] for r in body["rows"]] == [1, 2]
        # The excluded card never appears carrying an adjusted_excess either -- it is simply not on
        # this table at all, not present-but-defanged.
        assert "alloc-1" not in {r["agent_id"] for r in body["rows"]}

    def test_invested_value_majority_excludes_the_entry_notional_minority(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client: TestClient
    ) -> None:
        """The mirror image, proving dominance follows the larger group's actual count rather than
        always defaulting to `entry-notional`."""
        runs_dir = tmp_path / "r-mixed-b" / "results" / "gfc" / "runs"
        _write_run(runs_dir, "alloc-1", _allocation_run("alloc-1"))
        _write_run(runs_dir, "alloc-2", _allocation_run("alloc-2"))
        _write_run(runs_dir, "picker-1", _stock_picking_run("picker-1"))
        monkeypatch.setattr(results, "ROUNDS_ROOT", tmp_path)

        response = client.get("/api/competition/rounds/r-mixed-b/leaderboard")
        assert response.status_code == 200
        body = response.json()

        assert {r["agent_id"] for r in body["rows"]} == {"alloc-1", "alloc-2"}
        assert body["scoring_basis"] == "excess"
        assert body["unscored_reason"] is not None
        assert "picker-1" in body["unscored_reason"]
        assert "entry-notional" in body["unscored_reason"]
        for row in body["rows"]:
            for cell in row["per_window"].values():
                assert cell["adjusted_excess"] is None

    def test_a_tie_breaks_toward_entry_notional(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client: TestClient
    ) -> None:
        """One card of each basis: the tie-break documented on `build_leaderboard` prefers
        `entry-notional`, the basis every round before r15 already expects a homogeneous field to
        be."""
        runs_dir = tmp_path / "r-mixed-c" / "results" / "gfc" / "runs"
        _write_run(runs_dir, "picker-1", _stock_picking_run("picker-1"))
        _write_run(runs_dir, "alloc-1", _allocation_run("alloc-1"))
        monkeypatch.setattr(results, "ROUNDS_ROOT", tmp_path)

        response = client.get("/api/competition/rounds/r-mixed-c/leaderboard")
        assert response.status_code == 200
        body = response.json()

        assert {r["agent_id"] for r in body["rows"]} == {"picker-1"}
        assert body["scoring_basis"] == "adjusted_excess"

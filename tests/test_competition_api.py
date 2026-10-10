"""Integration tests for the strategy-competition HTTP API (`app.api.competition`).

`app.main` does not wire this router yet -- another agent's job once every phase module lands (see
`tests/test_macro_api.py`'s module docstring for the identical situation with `app.api.macro`) -- so
the `app` fixture below builds its own minimal `FastAPI` app around `competition.router`.

Two kinds of assertion live in this file, deliberately kept apart (see the task brief):

* **File-handling assertions** (a `provenance.json` sidecar must never be loaded as a card; an
  unknown round or agent id must 404) run against a `tmp_path` fixture built fresh by each test, via
  `monkeypatch.setattr(results, "LIBRARY_ROOT" | "ROUNDS_ROOT", ...)`. `app.tournament.results`
  reads those two names from its own module namespace on every call (never captures them at
  `def`-time), so patching the attribute is sufficient -- no need to pass an explicit override
  parameter through the router.
* **Numeric assertions** (ranking order, the exactness invariant) run against the real committed
  round data, because the numbers under test are properties of that specific data rather than
  something a synthetic fixture could stand in for without re-asserting the code under test.

  One assertion used to live here and no longer does: the D1 `total_return` defect was pinned to
  round 1's `A1-alpha-order` in `covid`, whose file carried a known-wrong figure. D4's fix restated
  every round, so that file now carries a correct one and the fixture is gone. The property is still
  tested -- `TestTotalReturnIsRecomputedFromEquity` now plants the wrong value deliberately. Worth
  knowing before pinning a new assertion to historical data: these files are re-runnable, and a
  restatement will take the fixture with it.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import competition as competition_api
from app.tournament import jobs, results
from app.tournament.purposes import PURPOSE_SPECS, Purpose

# ---------------------------------------------------------------------------
# App + fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    """A bare app around just the competition router -- see the module docstring."""
    fastapi_app = FastAPI()
    fastapi_app.include_router(competition_api.router)
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# A real card, minimal but valid, for building synthetic library fixtures.
_SAMPLE_CARD = {
    "agent_id": "z-sample",
    "display_name": "Sample synthetic card",
    "discipline": "momentum",
    "thesis": "A synthetic card used only to exercise file-handling behaviour, not a real strategy.",
    "universe": ["AAPL"],
    "entry": "close > sma(50)",
    "exit": "close < sma(50)",
    "stop_loss_pct": "0.10",
    "take_profit_pct": None,
    "max_hold_days": 90,
    "max_positions": 1,
    "position_pct": "0.50",
    "designed_through": "2026-02-13",
}


def _write_card(path: Path, agent_id: str) -> None:
    payload = dict(_SAMPLE_CARD, agent_id=agent_id, display_name=f"{agent_id} card")
    path.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# /api/competition/library
# ---------------------------------------------------------------------------


class TestLibraryEndpoint:
    def test_real_library_returns_four_tiers_in_order(self, client: TestClient) -> None:
        """Against the real, committed `strategy-program/library/` tree (no monkeypatch): the four
        tiers always come back in this fixed order, whatever cards happen to currently sit in each
        (the library is edited concurrently by other work in this program -- see
        `app.tournament.results.load_library`'s docstring -- so this test does not assert on which
        specific cards are present, only on the tier shape)."""
        response = client.get("/api/competition/library")
        assert response.status_code == 200
        body = response.json()
        tiers = body["tiers"]
        assert [t["tier"] for t in tiers] == ["base", "variants", "candidates", "retired"]
        assert [t["label"] for t in tiers] == ["Base", "Variants", "Candidates", "Retired"]
        # `base` and `candidates` are known non-empty in the committed library.
        base = next(t for t in tiers if t["tier"] == "base")
        candidates = next(t for t in tiers if t["tier"] == "candidates")
        assert len(base["cards"]) > 0
        assert len(candidates["cards"]) > 0
        card = base["cards"][0]
        assert set(card) == {
            "agent_id",
            "display_name",
            "discipline",
            "universe",
            "entry",
            "exit",
            "stop_loss_pct",
            "take_profit_pct",
            "max_hold_days",
            "max_positions",
            "position_pct",
            "designed_through",
            "thesis",
        }

    def test_empty_tier_still_present(self, client: TestClient) -> None:
        """`variants` (or any tier with zero cards) is still returned as an entry with `cards: []`,
        never omitted -- the frontend needs all four tiers to render four columns."""
        response = client.get("/api/competition/library")
        tiers = {t["tier"]: t for t in response.json()["tiers"]}
        assert set(tiers) == {"base", "variants", "candidates", "retired"}
        for tier in tiers.values():
            assert isinstance(tier["cards"], list)

    def test_provenance_json_sidecar_is_never_loaded_as_a_card(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A `provenance.json` sitting beside real cards in a tier directory must be skipped, not
        loaded as a (badly malformed) `StrategyCard` -- see `backend/app/tournament/__main__.py`'s
        `_NOT_CARDS`, which this module duplicates for the identical reason."""
        library_root = tmp_path / "library"
        base_dir = library_root / "base"
        base_dir.mkdir(parents=True)
        _write_card(base_dir / "X-one.json", "X-one")
        _write_card(base_dir / "X-two.json", "X-two")
        # A provenance sidecar shaped nothing like a StrategyCard -- if this were loaded as a card,
        # StrategyCard's `extra="forbid"` would raise a wall of validation errors.
        (base_dir / "provenance.json").write_text(
            json.dumps({"X-one": "2025-11-14"}), encoding="utf-8"
        )
        for tier, _label in results.TIERS:
            if tier != "base":
                (library_root / tier).mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(results, "LIBRARY_ROOT", library_root)

        response = client.get("/api/competition/library")

        assert response.status_code == 200
        base = next(t for t in response.json()["tiers"] if t["tier"] == "base")
        agent_ids = {c["agent_id"] for c in base["cards"]}
        assert agent_ids == {"X-one", "X-two"}
        assert len(base["cards"]) == 2


# ---------------------------------------------------------------------------
# /api/competition/rounds
# ---------------------------------------------------------------------------


class TestRoundsEndpoint:
    def test_lists_the_real_rounds_with_correct_window_sets(self, client: TestClient) -> None:
        """The committed rounds are listed correctly, and newest-first.

        Deliberately asserts the known rounds are **present**, not that they are the only ones.
        The previous version pinned `set(by_id) == {"r1-2026-08", "r2-2026-08"}`, which made
        *running a competition* — the thing this whole subsystem exists to do — fail the suite. A
        test that breaks on normal use of the feature it covers is testing the wrong property; it
        was caught the first time a round was actually run through the new job path.

        The ordering assertion is likewise generalised: newest-first over whatever rounds exist,
        rather than one hardcoded pair.

        It used to read ``assert listed == sorted(listed, reverse=True)`` -- a plain *string* sort,
        which pinned a live defect rather than the intended contract. Round ids sort as text, so
        ``"r9-2026-08" > "r13-2026-08"``, and round 9 was presented to the page as the newest round.
        Round 9 has no ``results/`` directory, so the leaderboard endpoint answers 404 for it, and
        the Competition tab -- which seeded its round picker from the first entry -- opened onto that
        404 and rendered nothing at all. The ordering is now numeric by
        :func:`app.tournament.results.round_sequence`, and this assertion is written against that
        function rather than against ``sorted``'s default so the two cannot drift apart again.
        """
        response = client.get("/api/competition/rounds")
        assert response.status_code == 200
        body = response.json()
        by_id = {r["round_id"]: r for r in body["rounds"]}
        assert {"r1-2026-08", "r2-2026-08"} <= set(by_id)

        # Newest-first by round *number* descending, over however many rounds are on disk.
        listed = [r["round_id"] for r in body["rounds"]]
        assert listed == sorted(listed, key=lambda rid: (results.round_sequence(rid), rid), reverse=True)

        # And specifically the pair the old string sort got wrong, when both are present.
        if {"r9-2026-08", "r13-2026-08"} <= set(by_id):
            assert listed.index("r13-2026-08") < listed.index("r9-2026-08")

        # `has_results` must agree with whether the leaderboard endpoint can actually answer: a round
        # advertised as having results but 404-ing is the exact combination that blanked the page.
        for summary in body["rounds"]:
            leaderboard = client.get(
                f"/api/competition/rounds/{summary['round_id']}/leaderboard?rank_by=median"
            )
            if summary["has_results"]:
                assert leaderboard.status_code == 200, summary["round_id"]
            else:
                assert leaderboard.status_code == 404, summary["round_id"]

        r1 = by_id["r1-2026-08"]
        assert set(r1["windows"]) == {"covid", "bear-2022", "bull-2024", "recent", "gfc", "13f-legal"}
        assert r1["has_report"] is True
        assert r1["has_brief"] is True
        assert r1["agents"] > 0

        r2 = by_id["r2-2026-08"]
        assert set(r2["windows"]) == {
            "q4-2018",
            "covid",
            "bear-2022",
            "chop-2015",
            "chop-2011",
            "bull-2024",
            "recent",
            "gfc",
            "13f-legal",
        }
        assert r2["has_report"] is True
        assert r2["has_brief"] is True
        # 26 distinct agent_id values across every window of r2-2026-08 (verified directly against
        # the committed run files while writing this test).
        assert r2["agents"] == 26

    def test_unknown_rounds_root_yields_empty_list_not_an_error(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(results, "ROUNDS_ROOT", tmp_path / "does-not-exist")
        response = client.get("/api/competition/rounds")
        assert response.status_code == 200
        assert response.json()["rounds"] == []


# ---------------------------------------------------------------------------
# /api/competition/windows
# ---------------------------------------------------------------------------


class TestWindowsEndpoint:
    """`/api/competition/windows` must source its catalogue from `app.tournament.jobs.WINDOWS` /
    `MAIN_WINDOWS` -- the constant `POST /api/competition/jobs` actually validates a launch request
    against -- rather than keeping a fourth copy of the window matrix (`strategy-program/tools/
    windows.py` is the original; `strategy-program/tools/score.py` and `app.tournament.jobs` each
    already duplicate pieces of it, by necessity -- see both modules' docstrings on why the hyphenated
    `strategy-program/` directory name rules out an import)."""

    def test_never_empty_even_with_no_rounds(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unlike `/rounds`, which can legitimately return `[]` on a fresh install, `/windows`
        answers from the round runner's own static matrix and must have something to offer a launch
        form before a single round has ever been run."""
        monkeypatch.setattr(results, "ROUNDS_ROOT", tmp_path / "does-not-exist")
        response = client.get("/api/competition/windows")
        assert response.status_code == 200
        assert response.json()["windows"]

    def test_every_jobs_window_appears_exactly_once(self, client: TestClient) -> None:
        response = client.get("/api/competition/windows")
        assert response.status_code == 200
        names = [w["window"] for w in response.json()["windows"]]
        assert len(names) == len(set(names)), "duplicate window in the catalogue"
        assert set(names) == set(jobs.WINDOWS)

    def test_13f_legal_is_the_only_non_main_entry(self, client: TestClient) -> None:
        """`main` means *comparable*, not *belongs to round 2's matrix*.

        The second assertion here used to be `main == set(jobs.MAIN_WINDOWS)`, which held only while
        `MAIN_WINDOWS` happened to be every window but one. Round 4 added six regimes to a separate
        matrix and that assertion started demanding the run form mark all six non-main -- which would
        have dimmed them and captioned them as provenance-constrained, a claim that is simply false
        about `oil-2014` or `banks-2023`. They are ordinary regime windows; they are just not round
        2's.

        So the property is pinned where it actually lives: exactly the windows in
        `jobs.PROVENANCE_CONSTRAINED_WINDOWS` are non-main, and every window belongs to some named
        matrix.
        """
        response = client.get("/api/competition/windows")
        by_name = {w["window"]: w for w in response.json()["windows"]}

        non_main = {name for name, w in by_name.items() if not w["main"]}
        assert non_main == set(jobs.PROVENANCE_CONSTRAINED_WINDOWS) == {"13f-legal"}

        assert set(by_name) == set(jobs.WINDOWS), "every known window must be offered"
        assert {w["matrix"] for w in by_name.values()} <= {
            "r2",
            "r4",
            "r5-ladder",
            "r5-bear",
            "special",
        }
        assert by_name["13f-legal"]["matrix"] == "special"
        for tag in jobs.R4_MAIN_WINDOWS:
            assert by_name[tag]["matrix"] == "r4"
            assert by_name[tag]["main"] is True
        for tag in jobs.MAIN_WINDOWS:
            assert by_name[tag]["matrix"] == "r2"
        for tag in jobs.R5_LADDER_WINDOWS:
            assert by_name[tag]["matrix"] == "r5-ladder"
            assert by_name[tag]["main"] is True
        for tag in jobs.R5_BEAR_WINDOWS:
            assert by_name[tag]["matrix"] == "r5-bear"
            assert by_name[tag]["main"] is True

    def test_dates_and_labels_match_jobs_windows_exactly(self, client: TestClient) -> None:
        response = client.get("/api/competition/windows")
        by_name = {w["window"]: w for w in response.json()["windows"]}
        for tag, (start, end, label) in jobs.WINDOWS.items():
            entry = by_name[tag]
            assert entry["start"] == start.isoformat()
            assert entry["end"] == end.isoformat()
            assert entry["label"] == label

    def test_comparable_windows_first_grouped_by_matrix_and_chronological_within_each(
        self, client: TestClient
    ) -> None:
        """Comparable regimes first, grouped by matrix, chronological inside each group.

        The grouping is deliberate rather than incidental. A single global chronology would
        interleave round 2's eight regimes with round 4's six -- `recovery-2009` landing between
        `gfc` and `chop-2011` -- and a person picking regimes for a run would have no way to see
        which matrix they were assembling. Grouped, the list reads as "round 2's set, then round
        4's, then the one window that is not comparable with either".
        """
        entries = client.get("/api/competition/windows").json()["windows"]

        main_flags = [e["main"] for e in entries]
        # Once the flag flips to False it never flips back.
        assert main_flags == sorted(main_flags, reverse=True)

        # Matrix groups are contiguous, and each is internally chronological. The ladder is required
        # to precede the bear arm within round 5 -- a plain lexical sort would put "r5-bear" before
        # "r5-ladder" (see `app.api.competition.windows`'s `_MATRIX_ORDER` comment), so this order is
        # itself part of what is under test, not an assumption borrowed from string sorting.
        matrix_order = ["r2", "r4", "r5-ladder", "r5-bear", "special"]
        matrices = [e["matrix"] for e in entries]
        assert matrices == sorted(matrices, key=matrix_order.index)
        for matrix in matrix_order:
            starts = [e["start"] for e in entries if e["matrix"] == matrix]
            assert starts == sorted(starts), f"{matrix} group is not chronological"

    def test_catalogue_is_a_superset_of_every_window_named_in_rounds(
        self, client: TestClient
    ) -> None:
        """A round whose window the catalogue does not know about would be a real inconsistency --
        the round runner and the completed-round data must agree on what a 'window' is."""
        catalogue = {w["window"] for w in client.get("/api/competition/windows").json()["windows"]}
        rounds_response = client.get("/api/competition/rounds").json()
        windows_in_rounds: set[str] = set()
        for round_summary in rounds_response["rounds"]:
            windows_in_rounds.update(round_summary["windows"])
        assert windows_in_rounds, "expected at least one real round with windows to check against"
        assert windows_in_rounds <= catalogue


class TestRound5WindowsInCatalogue:
    """Round 5 registered a 27-window horizon ladder (21 ladder windows + 6 bear-supplement windows)
    rather than another handful of named regimes -- see `jobs.WINDOWS`'s round-5 comment and
    `WindowCatalogEntry.horizon`'s docstring. These tests pin the two properties that distinguish a
    round-5 window from every earlier one: it carries a real `horizon` and it groups under
    `"r5-ladder"`/`"r5-bear"`, never `"r2"`/`"r4"`/`"special"`.
    """

    def test_every_round5_tag_present_with_correct_matrix_and_horizon(
        self, client: TestClient
    ) -> None:
        by_name = {
            w["window"]: w for w in client.get("/api/competition/windows").json()["windows"]
        }
        for tag in jobs.R5_LADDER_WINDOWS:
            assert tag in by_name, f"{tag} missing from the catalogue"
            assert by_name[tag]["matrix"] == "r5-ladder"
            assert by_name[tag]["horizon"] == jobs.R5_HORIZON[tag]
        for tag in jobs.R5_BEAR_WINDOWS:
            assert tag in by_name, f"{tag} missing from the catalogue"
            assert by_name[tag]["matrix"] == "r5-bear"
            assert by_name[tag]["horizon"] == jobs.R5_HORIZON[tag]

    def test_all_27_round5_windows_are_main_and_carry_a_horizon(
        self, client: TestClient
    ) -> None:
        """Round 5's windows are ordinary, comparable regimes -- nothing about a horizon-ladder slot
        makes a card ineligible for it -- so every one of the 27 must be `main=True`, and every one
        must carry a non-`None` `horizon` since a ladder window's length is the entire point of it
        (see `WindowCatalogEntry.horizon`'s docstring)."""
        by_name = {
            w["window"]: w for w in client.get("/api/competition/windows").json()["windows"]
        }
        round5_tags = set(jobs.R5_LADDER_WINDOWS) | set(jobs.R5_BEAR_WINDOWS)
        assert len(round5_tags) == 27
        for tag in round5_tags:
            assert by_name[tag]["main"] is True, tag
            assert by_name[tag]["horizon"] is not None, tag
            assert by_name[tag]["horizon"] in {"6m", "1y", "3y", "5y", "10y"}, tag

    def test_horizon_is_none_for_every_pre_round5_window(self, client: TestClient) -> None:
        """A named regime window (e.g. `covid`, `oil-2014`) has an incidental length but was not
        *designed* to a horizon the way a round-5 ladder slot was -- `horizon` is `None` for all of
        them, per `WindowCatalogEntry.horizon`'s docstring."""
        by_name = {
            w["window"]: w for w in client.get("/api/competition/windows").json()["windows"]
        }
        round5_tags = set(jobs.R5_LADDER_WINDOWS) | set(jobs.R5_BEAR_WINDOWS)
        for tag, entry in by_name.items():
            if tag not in round5_tags:
                assert entry["horizon"] is None, tag


# ---------------------------------------------------------------------------
# /api/competition/rounds/{round_id}/leaderboard
# ---------------------------------------------------------------------------


class TestLeaderboardEndpoint:
    def test_unknown_round_id_is_404(self, client: TestClient) -> None:
        response = client.get("/api/competition/rounds/r99-nope/leaderboard")
        assert response.status_code == 404

    def test_unknown_rank_by_is_422_not_a_silent_default(self, client: TestClient) -> None:
        response = client.get(
            "/api/competition/rounds/r2-2026-08/leaderboard?rank_by=not-a-real-criterion"
        )
        assert response.status_code == 422

    def test_default_rank_by_is_median(self, client: TestClient) -> None:
        response = client.get("/api/competition/rounds/r2-2026-08/leaderboard")
        assert response.status_code == 200
        assert response.json()["rank_by"] == "median"

    @pytest.mark.parametrize("rank_by", ["median", "worst", "hit-rate", "excess-per-exposure"])
    def test_rows_are_sorted_by_the_requested_key_descending(
        self, client: TestClient, rank_by: str
    ) -> None:
        field_by_rank = {
            "median": "median_excess",
            "worst": "worst_excess",
            "hit-rate": "hit_rate",
            # No row-level field for excess-per-exposure; verified by rank continuity instead below.
        }
        response = client.get(f"/api/competition/rounds/r2-2026-08/leaderboard?rank_by={rank_by}")
        assert response.status_code == 200
        body = response.json()
        rows = body["rows"]
        assert rows, "expected at least one row from the real r2-2026-08 data"

        # `rank` is always 1..N with no gaps, continuing across the eligible/ineligible boundary.
        assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))

        eligible_rows = [r for r in rows if r["eligible"]]
        ineligible_rows = [r for r in rows if not r["eligible"]]
        # Every eligible row sorts before every ineligible row.
        assert rows[: len(eligible_rows)] == eligible_rows
        assert rows[len(eligible_rows) :] == ineligible_rows
        assert eligible_rows, "the real r2-2026-08 field has at least one eligible card"

        field = field_by_rank.get(rank_by)
        if field is not None:
            values = [
                Decimal(r[field]) if isinstance(r[field], str) else r[field]
                for r in eligible_rows
                if r[field] is not None
            ]
            assert values == sorted(values, reverse=True)

    def test_ineligible_row_is_reported_not_hidden(self, client: TestClient) -> None:
        """A card that ran fewer than 5 of the 8 main windows still appears, with its real numbers,
        ranked after every eligible row -- see `MIN_ELIGIBLE_MAIN_WINDOWS`."""
        response = client.get("/api/competition/rounds/r2-2026-08/leaderboard")
        rows = response.json()["rows"]
        ineligible = [r for r in rows if not r["eligible"]]
        assert ineligible, "expected at least one ineligible card in the real r2-2026-08 field"
        for row in ineligible:
            assert row["windows_run"] < results.MIN_ELIGIBLE_MAIN_WINDOWS
            # Still a real, populated row -- not a stub.
            assert row["agent_id"]
            assert isinstance(row["per_window"], dict)

    def test_13f_legal_window_is_provenance_constrained_and_excluded_from_aggregates(
        self, client: TestClient
    ) -> None:
        response = client.get("/api/competition/rounds/r2-2026-08/leaderboard")
        body = response.json()

        window_13f = next(w for w in body["windows"] if w["window"] == "13f-legal")
        assert window_13f["provenance_constrained"] is True
        other_windows = [w for w in body["windows"] if w["window"] != "13f-legal"]
        assert all(w["provenance_constrained"] is False for w in other_windows)

        # c06-13f-momentum ran 13f-legal plus 6 of the 8 main windows in r2-2026-08 (q4-2018, covid,
        # bear-2022, chop-2015, bull-2024, recent -- verified directly against the committed run
        # files: chop-2011 and gfc are missing). windows_run must count only the 6 main windows, and
        # its per_window must still carry the 13f-legal cell for display.
        row = next(r for r in body["rows"] if r["agent_id"] == "c06-13f-momentum")
        assert row["windows_run"] == 6
        assert "13f-legal" in row["per_window"]
        assert set(row["per_window"]) == {
            "q4-2018",
            "covid",
            "bear-2022",
            "chop-2015",
            "bull-2024",
            "recent",
            "13f-legal",
        }

        # total_trades must exclude 13f-legal's trades: sum of the 6 counted cells' `trades`, not
        # all 7 cells'.
        counted_trades = sum(
            cell["trades"] for tag, cell in row["per_window"].items() if tag != "13f-legal"
        )
        all_trades = sum(cell["trades"] for cell in row["per_window"].values())
        assert row["total_trades"] == counted_trades
        assert counted_trades < all_trades, (
            "13f-legal must have contributed at least one trade of its own for this to be a "
            "meaningful check"
        )


# ---------------------------------------------------------------------------
# /api/competition/rounds/{round_id}/agents/{agent_id}
# ---------------------------------------------------------------------------


class TestAgentDetailEndpoint:
    def test_unknown_round_id_is_404(self, client: TestClient) -> None:
        response = client.get("/api/competition/rounds/r99-nope/agents/B-momentum")
        assert response.status_code == 404

    def test_unknown_agent_id_is_404(self, client: TestClient) -> None:
        response = client.get(
            "/api/competition/rounds/r2-2026-08/agents/not-a-real-agent-id"
        )
        assert response.status_code == 404

    def test_happy_path_shape(self, client: TestClient) -> None:
        response = client.get("/api/competition/rounds/r2-2026-08/agents/c07-chop")
        assert response.status_code == 200
        body = response.json()
        assert body["agent_id"] == "c07-chop"
        assert body["round_id"] == "r2-2026-08"
        assert body["card"]["agent_id"] == "c07-chop"
        assert len(body["windows"]) > 0
        window = body["windows"][0]
        assert set(window) == {
            "window",
            "sessions",
            "starting_equity",
            "ending_equity",
            "total_return",
            "benchmark_return",
            "excess",
            "adjusted_excess",
            "capital_exposure",
            "max_drawdown",
            "win_rate",
            "profit_factor",
            "unrealised_share",
            "top3_share_of_gross_wins",
            "return_without_top3_winners",
            "rejections",
            "trades",
        }
        if window["trades"]:
            trade = window["trades"][0]
            assert set(trade) == {
                "symbol",
                "entry_date",
                "exit_date",
                "entry_price",
                "exit_price",
                "quantity",
                "bars_held",
                "exit_reason",
                "return_pct",
                "pnl",
                "contribution",
                "unrealised",
            }

    def test_trades_within_a_window_are_sorted_by_absolute_contribution_descending(
        self, client: TestClient
    ) -> None:
        response = client.get("/api/competition/rounds/r2-2026-08/agents/c07-chop")
        body = response.json()
        for window in body["windows"]:
            contributions = [abs(Decimal(t["contribution"])) for t in window["trades"]]
            assert contributions == sorted(contributions, reverse=True), window["window"]

    def test_contribution_exactness_invariant(self, client: TestClient) -> None:
        """`sum(contribution)` over a window's trades must equal that window's `total_return`
        exactly, per `strategy-program/tools/attribution.py`'s guarantee that the trade log is
        complete: every dollar of `ending_equity - starting_equity` is accounted for by exactly one
        trade's `pnl`, so `pnl / starting_equity` summed across all trades reproduces
        `total_return` with no residual left over to apportion.

        **Tolerance:** `Decimal("0.00001")` (1e-5) in return-fraction terms. On this data's ~$10,000
        starting-equity books that is one tenth of a cent -- an order of magnitude looser than the
        one-cent-scale rounding actually observed on real data (a real window in this exact data set,
        c07-chop / chop-2011 in r2-2026-08, differs by `Decimal("0.000001")`, i.e. one cent on a
        $10,000 book, from the underlying per-trade `pnl` figures already being rounded to the cent
        before this arithmetic ever runs) while still being tight enough that a genuine apportionment
        bug -- as opposed to cent rounding -- would fail it.
        """
        tolerance = Decimal("0.00001")
        response = client.get("/api/competition/rounds/r2-2026-08/agents/c07-chop")
        body = response.json()
        checked_any_trade = False
        for window in body["windows"]:
            total_return = Decimal(window["total_return"])
            contribution_sum = sum(
                (Decimal(t["contribution"]) for t in window["trades"]), Decimal(0)
            )
            if window["trades"]:
                checked_any_trade = True
            assert abs(contribution_sum - total_return) <= tolerance, (
                window["window"],
                contribution_sum,
                total_return,
            )
        assert checked_any_trade, "expected at least one window with trades to check"

    def test_unrealised_trade_is_flagged_and_separated(self, client: TestClient) -> None:
        """c07-chop's gfc window (r2-2026-08) is known -- from reading the committed run file
        while writing this test -- to end with an `open_at_end` position (an unrealised mark, not
        money taken); its `unrealised_share` must be nonzero and at least one trade must carry
        `unrealised: True`."""
        response = client.get("/api/competition/rounds/r2-2026-08/agents/c07-chop")
        assert response.status_code == 200
        body = response.json()
        gfc = next(w for w in body["windows"] if w["window"] == "gfc")
        unrealised_trades = [t for t in gfc["trades"] if t["unrealised"]]
        assert unrealised_trades
        for trade in unrealised_trades:
            assert trade["exit_reason"] == "open_at_end"
            assert trade["exit_date"] is None
        assert Decimal(gfc["unrealised_share"]) != 0

    def test_card_comes_from_the_run_file_not_the_current_library(
        self, client: TestClient
    ) -> None:
        """`card` must be the embedded `StrategyCard` from the run file the round actually traded,
        not whatever the library currently holds for the same `agent_id` -- checked here by
        confirming the returned card's `agent_id` and `universe` match what is actually embedded in
        one of the round's own run files, independent of the current library layout (which other
        concurrent work in this program is actively editing -- see the module docstrings)."""
        raw = json.loads(
            (
                Path(results.ROUNDS_ROOT)
                / "r2-2026-08"
                / "results"
                / "gfc"
                / "runs"
            ).glob("*-c07-chop.json").__next__().read_text(encoding="utf-8")
        )
        response = client.get("/api/competition/rounds/r2-2026-08/agents/c07-chop")
        card = response.json()["card"]
        assert card["agent_id"] == raw["card"]["agent_id"]
        assert card["universe"] == raw["card"]["universe"]
        assert card["thesis"] == raw["card"]["thesis"]

    def test_unknown_agent_with_temp_round_directory_is_404(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client: TestClient
    ) -> None:
        """File-handling case: an otherwise well-formed round directory (a `results/` tree exists)
        that simply never ran the requested agent must 404, not 500 or return an empty body."""
        round_dir = tmp_path / "rounds" / "r9-synthetic"
        runs_dir = round_dir / "results" / "gfc" / "runs"
        runs_dir.mkdir(parents=True)
        monkeypatch.setattr(results, "ROUNDS_ROOT", tmp_path / "rounds")

        response = client.get("/api/competition/rounds/r9-synthetic/agents/nobody-ran-this")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# D1 -- total_return must be recomputed from equity, never trusted from the field
# ---------------------------------------------------------------------------


class TestTotalReturnIsRecomputedFromEquity:
    def test_a_wrong_total_return_on_the_file_is_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client: TestClient
    ) -> None:
        """`total_return` on a run file must never be trusted; the figure comes from equity.

        `strategy-program/DEFECTS.md` D1: the engine once wrote `total_return` rebased to the first
        session's close rather than to starting equity, which flipped the sign for any card that
        filled on session one. Round 1's `A1-alpha-order` in `covid` was the worked example --
        **-0.972%** on the file against a true **+1.099%** -- and this test used to read that very
        file.

        It cannot any more, and the reason is worth recording. D4's fix restated all three rounds,
        re-running every card through the current engine, so round 1's files are no longer the
        artifact D1 produced -- they carry correct `total_return` values now. The old fixture guarded
        itself against exactly that (*"if the underlying file ever changes, this test should fail
        loudly here rather than silently pass for the wrong reason"*) and duly failed the moment the
        restatement landed, which is the behaviour one wants from a test pinned to real data.

        The property is unchanged and still worth pinning, so the defect is now planted deliberately
        instead of borrowed from history: a synthetic round with a `total_return` that disagrees with
        its own equity, and an assertion that the endpoint reports the equity-derived figure.
        """
        source = (
            Path(results.ROUNDS_ROOT) / "r1-2026-08" / "results" / "covid" / "runs"
            / "r1-A1-alpha-order.json"
        )
        raw = json.loads(source.read_text(encoding="utf-8"))

        # A value no equity ratio could produce, so a pass cannot be a coincidence.
        raw["total_return"] = "-0.5"

        runs_dir = tmp_path / "rounds" / "r9-synthetic" / "results" / "covid" / "runs"
        runs_dir.mkdir(parents=True)
        (runs_dir / "r1-A1-alpha-order.json").write_text(json.dumps(raw), encoding="utf-8")
        monkeypatch.setattr(results, "ROUNDS_ROOT", tmp_path / "rounds")

        response = client.get("/api/competition/rounds/r9-synthetic/agents/A1-alpha-order")
        assert response.status_code == 200
        covid = next(w for w in response.json()["windows"] if w["window"] == "covid")

        true_return = Decimal(raw["ending_equity"]) / Decimal(raw["starting_equity"]) - 1
        assert Decimal(covid["total_return"]) == pytest.approx(true_return, abs=1e-9)
        assert Decimal(covid["total_return"]) != Decimal("-0.5")

    def test_leaderboard_cell_agrees_with_the_same_recomputed_figure(
        self, client: TestClient
    ) -> None:
        """The leaderboard's per-window cell for the same (agent, window) must show the identical
        recomputed `total_return` the agent-detail endpoint shows -- the two endpoints must not
        disagree about which number is the true one."""
        response = client.get("/api/competition/rounds/r1-2026-08/leaderboard")
        body = response.json()
        row = next(r for r in body["rows"] if r["agent_id"] == "A1-alpha-order")
        cell = row["per_window"]["covid"]
        assert Decimal(cell["total_return"]) == pytest.approx(Decimal("0.01099"), abs=Decimal("0.0001"))
        assert Decimal(cell["total_return"]) > 0


class TestPurposesEndpoint:
    """`/purposes` is a catalogue read, like `/windows`: a client renders three books from data
    rather than from three hardcoded assumptions about what they are and how they are scored."""

    def test_lists_all_three_read_from_the_specs(self, client: TestClient) -> None:
        body = client.get("/api/competition/purposes").json()
        by_purpose = {p["purpose"]: p for p in body["purposes"]}

        assert set(by_purpose) == {p.value for p in Purpose}
        for purpose, spec in PURPOSE_SPECS.items():
            got = by_purpose[purpose.value]
            assert got["funding_shape"] == spec.funding_shape.value
            assert got["benchmark"] == spec.benchmark
            assert got["symbols_must_be_disjoint"] == spec.symbols_must_be_disjoint

    def test_an_unbounded_horizon_is_null_not_a_stand_in_number(self, client: TestClient) -> None:
        """The trading horizon is deliberately unstated. A large number pretending to be a bound
        would be worse than leaving it open, so the wire has to be able to say "unstated"."""
        body = client.get("/api/competition/purposes").json()
        trading = next(p for p in body["purposes"] if p["purpose"] == "trading")
        assert trading["horizon_years_max"] is None

    def test_the_two_contribution_funded_purposes_are_not_scored_on_excess(
        self, client: TestClient
    ) -> None:
        """An IRR and an `adjusted_excess` are different quantities; ranking them together is a
        category error, not a rounding one. The basis is on the wire so a renderer cannot put one
        under the other's column heading."""
        body = client.get("/api/competition/purposes").json()
        basis = {p["purpose"]: p["scoring_basis"] for p in body["purposes"]}

        # All three read `adjusted_excess` since 2026-08-29. `savings` and `roth` were `"irr+cagr"`
        # while they were contribution-funded; the owner made all three lump sums, and for a single
        # inflow money-weighted IRR and time-weighted CAGR are the same number by construction --
        # there is no longer a pair to report. See `app.tournament.results.SCORING_BASIS`.
        assert basis["trading"] == basis["savings"] == basis["roth"] == "adjusted_excess"


class TestLeaderboardPurposeFilter:
    def test_default_is_trading_and_matches_the_unfiltered_shape(self, client: TestClient) -> None:
        """Every card in every committed round is a trading card, so the default response is what
        this endpoint returned before purposes existed."""
        default = client.get("/api/competition/rounds/r2-2026-08/leaderboard").json()
        explicit = client.get(
            "/api/competition/rounds/r2-2026-08/leaderboard?purpose=trading"
        ).json()

        assert default["purpose"] == "trading"
        assert default["rows"] == explicit["rows"]
        assert default["rows"], "r2 must have trading rows or this proves nothing"

    def test_a_purpose_with_no_cards_is_empty_and_says_why(self, client: TestClient) -> None:
        """An empty board has two very different causes -- measured and bad, versus never measured --
        and a reader acts differently on each."""
        body = client.get("/api/competition/rounds/r2-2026-08/leaderboard?purpose=roth").json()

        assert body["rows"] == []
        assert body["unscored_reason"] is not None
        # It must name the cause, not restate the emptiness.
        assert "No round has run" in body["unscored_reason"]
        assert body["scoring_basis"] == "adjusted_excess"

    def test_a_populated_board_carries_no_unscored_reason(self, client: TestClient) -> None:
        body = client.get("/api/competition/rounds/r2-2026-08/leaderboard?purpose=trading").json()
        assert body["rows"]
        assert body["unscored_reason"] is None

    def test_unknown_purpose_is_422_not_a_silent_default(self, client: TestClient) -> None:
        """Same contract `rank_by` already has: a mistyped value should be visible, not silently
        answered with the default purpose's table."""
        response = client.get("/api/competition/rounds/r2-2026-08/leaderboard?purpose=nonsense")
        assert response.status_code == 422
        assert "nonsense" in response.json()["detail"]

    def test_ranks_are_dense_within_the_filtered_field(self, client: TestClient) -> None:
        """The filter is applied before ranking. Ranking the whole field and hiding rows afterwards
        would leave the survivors holding ranks that count competitors the caller cannot see."""
        rows = client.get(
            "/api/competition/rounds/r2-2026-08/leaderboard?purpose=trading"
        ).json()["rows"]
        assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))

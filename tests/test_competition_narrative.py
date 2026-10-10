"""Integration tests for the round-narrative HTTP API (`app.api.competition_narrative`) and its
loading layer (`app.tournament.narrative`).

`app.main` does not wire this router -- another agent's job -- so, same as
`tests/test_competition_api.py` and `tests/test_competition_findings.py`, the fixture below builds its
own minimal `FastAPI` app around just this module's router. Every test runs against a synthetic
`tmp_path` tree, never against the real `data/rounds/` or `strategy-program/`: `app.tournament.results`,
`app.tournament.findings` and `app.tournament.narrative` all read their root paths from their own
module namespace on every call (never captured at `def`-time), so `monkeypatch.setattr` on those names
is enough.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import competition_narrative as narrative_api
from app.tournament import findings, narrative

# ---------------------------------------------------------------------------
# App + fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(narrative_api.router)
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _patch_roots(
    monkeypatch: pytest.MonkeyPatch,
    rounds_root: Path,
    strategy_root: Path | None = None,
    defects_path: Path | None = None,
) -> None:
    monkeypatch.setattr(narrative, "ROUNDS_ROOT", rounds_root)
    if strategy_root is not None:
        monkeypatch.setattr(narrative, "STRATEGY_ROOT", strategy_root)
    monkeypatch.setattr(findings, "DEFECTS_PATH", defects_path or (rounds_root / "DEFECTS-none.md"))


_NARRATIVE_FIXTURE = {
    "round_id": "r9-2026-08",
    "title": "Round 9 - naming the chooser",
    "focus": "Does adding a ranking key reduce arbitrary slot selection?",
    "headline": "Yes: the spread across orderings collapsed once ranking was named.",
    "outcome": "Paragraph one of the outcome.\n\nParagraph two of the outcome, with more detail.",
    "seated": ["A1-alpha", "B3-beta"],
    "owner_override": "Owner reseated B3 despite a borderline gate, citing regime coverage.",
    "carries_forward": ["Settle the distinctness rule before round 10."],
    "sources": ["data/rounds/r9-2026-08/REPORT.md"],
}


# ---------------------------------------------------------------------------
# /rounds/{round_id}/narrative
# ---------------------------------------------------------------------------


class TestRoundNarrativeHappyPath:
    def test_round_trips_every_field(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rounds_root = tmp_path / "rounds"
        round_dir = rounds_root / "r9-2026-08"
        round_dir.mkdir(parents=True)
        (round_dir / "NARRATIVE.json").write_text(
            json.dumps(_NARRATIVE_FIXTURE), encoding="utf-8"
        )
        _patch_roots(monkeypatch, rounds_root)

        resp = client.get("/api/competition/rounds/r9-2026-08/narrative")

        assert resp.status_code == 200
        assert resp.json() == _NARRATIVE_FIXTURE


class TestRoundNarrativeMissingFile:
    def test_round_exists_but_no_narrative_is_404_with_distinct_detail(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rounds_root = tmp_path / "rounds"
        round_dir = rounds_root / "r9-2026-08"
        round_dir.mkdir(parents=True)
        (round_dir / "REPORT.md").write_text("# Round 9\n\nSome report.\n", encoding="utf-8")
        _patch_roots(monkeypatch, rounds_root)

        resp = client.get("/api/competition/rounds/r9-2026-08/narrative")

        assert resp.status_code == 404
        no_narrative_detail = resp.json()["detail"]
        assert "narrative" in no_narrative_detail.lower()

        unknown_resp = client.get("/api/competition/rounds/nosuchround/narrative")
        assert unknown_resp.status_code == 404
        unknown_detail = unknown_resp.json()["detail"]

        # The two 404s must be distinguishable -- a caller needs to tell "round exists, nothing
        # written" from "round does not exist at all".
        assert unknown_detail != no_narrative_detail


class TestRoundNarrativeUnknownRound:
    def test_unknown_round_id_is_404(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rounds_root = tmp_path / "rounds"
        rounds_root.mkdir()
        _patch_roots(monkeypatch, rounds_root)

        resp = client.get("/api/competition/rounds/r99-2026-08/narrative")

        assert resp.status_code == 404
        assert "no such round" in resp.json()["detail"].lower()


class TestRoundNarrativeMalformed:
    def test_extra_key_is_rejected_not_silently_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`extra="forbid"` bites at the module level: a `NARRATIVE.json` with an unexpected key
        raises a clear `MalformedNarrativeError`, not a bare, hard-to-read `pydantic.ValidationError`,
        and never silently drops or accepts the extra field."""
        rounds_root = tmp_path / "rounds"
        round_dir = rounds_root / "r9-2026-08"
        round_dir.mkdir(parents=True)
        bad_payload = dict(_NARRATIVE_FIXTURE, unexpected_field="should not be accepted")
        (round_dir / "NARRATIVE.json").write_text(json.dumps(bad_payload), encoding="utf-8")

        with pytest.raises(narrative.MalformedNarrativeError) as excinfo:
            narrative.load_narrative("r9-2026-08", rounds_root=rounds_root)

        assert "r9-2026-08" in str(excinfo.value)

    def test_malformed_file_is_a_clear_error_via_the_api(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rounds_root = tmp_path / "rounds"
        round_dir = rounds_root / "r9-2026-08"
        round_dir.mkdir(parents=True)
        (round_dir / "NARRATIVE.json").write_text("{not valid json", encoding="utf-8")
        _patch_roots(monkeypatch, rounds_root)

        resp = client.get("/api/competition/rounds/r9-2026-08/narrative")

        assert resp.status_code == 422
        assert "malformed" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# next_round_id ordering -- r9 and r14 both exist -> r15, not r10
# ---------------------------------------------------------------------------


class TestNextRoundIdOrdering:
    def test_r9_and_r14_present_gives_r15_not_r10(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """This repo has a real defect history of `r9` sorting after `r13` under a plain string
        sort -- pin the integer ordering here so a regression to string comparison is caught."""
        rounds_root = tmp_path / "rounds"
        (rounds_root / "r9-2026-08").mkdir(parents=True)
        (rounds_root / "r14-2026-08").mkdir(parents=True)
        monkeypatch.setattr(narrative, "ROUNDS_ROOT", rounds_root)

        # `next_round_id` reads its own clock, so this brackets the call rather than reading the
        # clock a second time afterwards and assuming the two agree. They disagree exactly when
        # midnight ends a month between the two reads -- rare, but the same defect that made
        # tests/test_tax_api.py fail for real on 2026-08-26, and rare failures are the expensive
        # kind because they surface as an unrelated red build weeks later.
        before = dt.date.today()
        result = narrative.next_round_id(rounds_root=rounds_root)
        after = dt.date.today()

        assert result in {f"r15-{d.year:04d}-{d.month:02d}" for d in (before, after)}

    def test_no_rounds_at_all_gives_r1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rounds_root = tmp_path / "rounds"
        rounds_root.mkdir()
        monkeypatch.setattr(narrative, "ROUNDS_ROOT", rounds_root)

        # Bracketed for the month-boundary reason given in the test above.
        before = dt.date.today()
        result = narrative.next_round_id(rounds_root=rounds_root)
        after = dt.date.today()

        assert result in {f"r1-{d.year:04d}-{d.month:02d}" for d in (before, after)}


# ---------------------------------------------------------------------------
# /next-round
# ---------------------------------------------------------------------------


class TestNextRoundNoPlan:
    def test_no_plan_file_sets_pre_registered_false_and_a_blocker(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rounds_root = tmp_path / "rounds"
        (rounds_root / "r9-2026-08").mkdir(parents=True)
        strategy_root = tmp_path / "strategy-program"
        strategy_root.mkdir()
        _patch_roots(monkeypatch, rounds_root, strategy_root)

        resp = client.get("/api/competition/next-round")

        assert resp.status_code == 200
        body = resp.json()
        assert body["pre_registered"] is False
        assert body["plan_path"] is None
        assert body["focus"] is None
        assert any("plan" in b.lower() for b in body["blockers"])


class TestNextRoundWithPlan:
    def test_plan_file_present_sets_pre_registered_true_and_extracts_focus(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rounds_root = tmp_path / "rounds"
        (rounds_root / "r9-2026-08").mkdir(parents=True)
        strategy_root = tmp_path / "strategy-program"
        strategy_root.mkdir()
        _patch_roots(monkeypatch, rounds_root, strategy_root)

        next_id = narrative.next_round_id(rounds_root=rounds_root)
        n = next_id.split("-", 1)[0][1:]
        plan_text = (
            "# Round 10 - the next question\n\n"
            "**Not investment advice.** Simulated books on a paper account, not a recommendation.\n\n"
            "This round asks whether the ranking key generalises beyond round 9's fixture.\n\n"
            "## 1. Background\n\nMore detail here.\n"
        )
        (strategy_root / f"ROUND-{n}-PLAN.md").write_text(plan_text, encoding="utf-8")

        resp = client.get("/api/competition/next-round")

        assert resp.status_code == 200
        body = resp.json()
        assert body["pre_registered"] is True
        assert body["plan_path"] == f"strategy-program/ROUND-{n}-PLAN.md"
        assert body["focus"] == (
            "This round asks whether the ranking key generalises beyond round 9's fixture."
        )
        assert not any("plan file committed" in b.lower() for b in body["blockers"])


class TestNextRoundNoPreviousRound:
    def test_no_previous_round_is_a_blocker(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rounds_root = tmp_path / "rounds"
        rounds_root.mkdir()
        strategy_root = tmp_path / "strategy-program"
        strategy_root.mkdir()
        _patch_roots(monkeypatch, rounds_root, strategy_root)

        resp = client.get("/api/competition/next-round")

        assert resp.status_code == 200
        body = resp.json()
        assert body["previous_round_id"] is None
        assert body["next_round_id"].startswith("r1-")
        assert body["carries_forward"] == []
        assert body["authored_carries_forward"] == []
        assert any("previous round" in b.lower() for b in body["blockers"])


_SELECTION_FIXTURE = """# Round 9 -- fixture

## 1. Seats

Seat B3 is seated by the rule. A closed and ordinary decision.

## 2. Distinctness, unresolved

This distinctness question remains unresolved and needs settling next round.
"""


class TestNextRoundCarriesForwardHeuristic:
    def test_only_carries_forward_true_findings_are_included(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rounds_root = tmp_path / "rounds"
        round_dir = rounds_root / "r9-2026-08"
        round_dir.mkdir(parents=True)
        (round_dir / "SELECTION.md").write_text(_SELECTION_FIXTURE, encoding="utf-8")
        strategy_root = tmp_path / "strategy-program"
        strategy_root.mkdir()
        _patch_roots(monkeypatch, rounds_root, strategy_root)

        resp = client.get("/api/competition/next-round")

        assert resp.status_code == 200
        body = resp.json()
        titles = {f["title"] for f in body["carries_forward"]}
        assert "Distinctness, unresolved" in titles
        assert "Seats" not in titles
        for entry in body["carries_forward"]:
            assert entry["carries_forward"] is True


class TestNextRoundAuthoredCarriesForward:
    def test_comes_from_previous_round_narrative(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rounds_root = tmp_path / "rounds"
        round_dir = rounds_root / "r9-2026-08"
        round_dir.mkdir(parents=True)
        (round_dir / "NARRATIVE.json").write_text(
            json.dumps(_NARRATIVE_FIXTURE), encoding="utf-8"
        )
        strategy_root = tmp_path / "strategy-program"
        strategy_root.mkdir()
        _patch_roots(monkeypatch, rounds_root, strategy_root)

        resp = client.get("/api/competition/next-round")

        assert resp.status_code == 200
        body = resp.json()
        assert body["authored_carries_forward"] == _NARRATIVE_FIXTURE["carries_forward"]

    def test_empty_when_previous_round_has_no_narrative(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rounds_root = tmp_path / "rounds"
        round_dir = rounds_root / "r9-2026-08"
        round_dir.mkdir(parents=True)
        (round_dir / "REPORT.md").write_text("# Round 9\n\nNo narrative authored.\n", encoding="utf-8")
        strategy_root = tmp_path / "strategy-program"
        strategy_root.mkdir()
        _patch_roots(monkeypatch, rounds_root, strategy_root)

        resp = client.get("/api/competition/next-round")

        assert resp.status_code == 200
        body = resp.json()
        assert body["authored_carries_forward"] == []

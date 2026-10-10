"""Integration tests for the round-findings HTTP API (`app.api.competition_findings`) and its
parsing layer (`app.tournament.findings`).

`app.main` wires this router in, but the fixture below builds its own minimal `FastAPI` app around
`competition_findings.router` -- same reasoning as `tests/test_competition_api.py`'s own module
docstring: no need to boot the whole application to exercise one router.

Every test here runs against synthetic markdown built fresh on `tmp_path`, never against the real
`data/rounds/` or `strategy-program/DEFECTS.md` -- this file is about the *parser's* behaviour
(section splitting, `kind`/`carries_forward` derivation, the 404/200 boundary), which a tmp fixture
pins far more precisely than real, still-evolving round documents could. `app.tournament.findings`
reads `ROUNDS_ROOT`/`DEFECTS_PATH` from its own module namespace on every call (never captures them
at `def`-time), so `monkeypatch.setattr` on those two names is enough -- no need to route an explicit
override parameter through the HTTP layer.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import competition_findings as findings_api
from app.tournament import findings

# ---------------------------------------------------------------------------
# App + fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(findings_api.router)
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _patch_roots(monkeypatch: pytest.MonkeyPatch, rounds_root: Path, defects_path: Path) -> None:
    monkeypatch.setattr(findings, "ROUNDS_ROOT", rounds_root)
    monkeypatch.setattr(findings, "DEFECTS_PATH", defects_path)


# ---------------------------------------------------------------------------
# Unknown round -> 404
# ---------------------------------------------------------------------------


class TestUnknownRound:
    def test_no_directory_is_404(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rounds_root = tmp_path / "rounds"
        rounds_root.mkdir()
        _patch_roots(monkeypatch, rounds_root, tmp_path / "DEFECTS.md")

        resp = client.get("/api/competition/rounds/nosuchround/findings")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# A round dir that exists but wrote nothing parseable -> 200, empty lists
# ---------------------------------------------------------------------------


class TestRoundWithNoMarkdown:
    def test_only_machine_output_returns_200_empty(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A round directory holding only `run.txt` (machine output, explicitly out of scope) is a
        200 with every list empty -- not a 404. This is the case the wire contract calls out
        specifically: an empty `findings` with the round genuinely existing."""
        rounds_root = tmp_path / "rounds"
        round_dir = rounds_root / "r9-2026-08"
        round_dir.mkdir(parents=True)
        (round_dir / "run.txt").write_text("machine output, not markdown\n", encoding="utf-8")
        # DEFECTS.md does not exist at this path either -- nothing anywhere to parse.
        _patch_roots(monkeypatch, rounds_root, tmp_path / "DEFECTS.md")

        resp = client.get("/api/competition/rounds/r9-2026-08/findings")

        assert resp.status_code == 200
        assert resp.json() == {
            "round_id": "r9-2026-08",
            "findings": [],
            "follow_ups": [],
            "sources": [],
        }

    def test_present_but_empty_file_is_not_a_source(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A `SELECTION.md` that exists but holds no `## ` heading at all (e.g. just a title line)
        contributes no entries and is not listed in `sources` -- `sources` names files this response
        actually drew an entry from, not every file it opened."""
        rounds_root = tmp_path / "rounds"
        round_dir = rounds_root / "r9-2026-08"
        round_dir.mkdir(parents=True)
        (round_dir / "SELECTION.md").write_text(
            "# Round 9 -- nothing written yet\n\nJust a placeholder.\n", encoding="utf-8"
        )
        _patch_roots(monkeypatch, rounds_root, tmp_path / "DEFECTS.md")

        resp = client.get("/api/competition/rounds/r9-2026-08/findings")

        assert resp.status_code == 200
        body = resp.json()
        assert body["findings"] == []
        assert body["sources"] == []


# ---------------------------------------------------------------------------
# DEFECTS.md: FIXED -> carries_forward False, otherwise True; wrong round excluded
# ---------------------------------------------------------------------------

_DEFECTS_FIXTURE = """# Defects found by the program

## D1 -- fixed defect, found in this round

**Found:** round 7, 2026-08-20, by an agent testing the fixture.
**Status:** **FIXED** between rounds 7 and 8. Worked around in `score.py` in the meantime.
**Severity:** material.

Body text describing D1's reproduction.

---

## D2 -- open defect, found in this round

**Found:** 2026-08-21, during round 7's integration -- the label and the round mention are not
adjacent, on purpose, to exercise the same drift `D6` shows in the real file.
**Status:** not addressed yet; deferred to a later round.

Body text describing D2, which is still open.

---

## D3 -- irrelevant defect, found in a different round

**Found:** round 3, 2026-08-15, by someone else entirely.
**Status:** **FIXED**.

Not relevant to round 7 and must not appear in its findings.
"""


class TestDefectsStatus:
    def test_fixed_false_unfixed_true_wrong_round_excluded(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rounds_root = tmp_path / "rounds"
        round_dir = rounds_root / "r7-2026-08"
        round_dir.mkdir(parents=True)
        defects_path = tmp_path / "DEFECTS.md"
        defects_path.write_text(_DEFECTS_FIXTURE, encoding="utf-8")
        _patch_roots(monkeypatch, rounds_root, defects_path)

        resp = client.get("/api/competition/rounds/r7-2026-08/findings")

        assert resp.status_code == 200
        body = resp.json()
        assert body["sources"] == ["DEFECTS.md"]

        by_title = {f["title"]: f for f in body["findings"]}
        # D3 was found in round 3, not round 7, and must not show up here at all.
        assert set(by_title) == {
            "D1 -- fixed defect, found in this round",
            "D2 -- open defect, found in this round",
        }
        assert by_title["D1 -- fixed defect, found in this round"]["carries_forward"] is False
        assert by_title["D2 -- open defect, found in this round"]["carries_forward"] is True
        for entry in body["findings"]:
            assert entry["kind"] == "defect"
            assert entry["round_id"] == "r7-2026-08"


# ---------------------------------------------------------------------------
# follow_ups is a filtered view of findings (subset invariant), and kind is
# independent of carries_forward
# ---------------------------------------------------------------------------

_SELECTION_FIXTURE = """# Round 9 -- fixture

## 1. Seats

Seat B3 is seated by the rule. A closed and ordinary decision.

## 2. Distinctness, unresolved

This distinctness question remains unresolved and needs settling next round.

## For whoever runs round 10

Do X. Do Y.
"""

_REPORT_FIXTURE = """# Round 9 report -- fixture

## 1. What we found

Card X performed well across every window measured.

## 2. What changes for round 10

Card Y needs a second look before it is trusted.
"""


class TestFollowUpsSubsetInvariant:
    def test_every_follow_up_id_is_in_findings(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rounds_root = tmp_path / "rounds"
        round_dir = rounds_root / "r9-2026-08"
        round_dir.mkdir(parents=True)
        (round_dir / "SELECTION.md").write_text(_SELECTION_FIXTURE, encoding="utf-8")
        (round_dir / "REPORT.md").write_text(_REPORT_FIXTURE, encoding="utf-8")
        # No DEFECTS.md at this path -- keeps this test about the round files alone.
        _patch_roots(monkeypatch, rounds_root, tmp_path / "DEFECTS.md")

        resp = client.get("/api/competition/rounds/r9-2026-08/findings")

        assert resp.status_code == 200
        body = resp.json()

        finding_ids = {f["id"] for f in body["findings"]}
        follow_up_ids = {f["id"] for f in body["follow_ups"]}
        assert follow_up_ids, "fixture is designed to produce at least one open item"
        assert follow_up_ids <= finding_ids

        # Every follow_up entry, wherever it came from, is byte-identical to its findings copy.
        by_id = {f["id"]: f for f in body["findings"]}
        for entry in body["follow_ups"]:
            assert entry == by_id[entry["id"]]

        assert set(body["sources"]) == {"SELECTION.md", "REPORT.md"}

    def test_selection_sections_are_always_decision_kind(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every SELECTION.md section is `kind == "decision"`, including the one whose heading
        addresses a future round -- SELECTION.md exists only to record the seating decision, so its
        forward-looking section is still part of that decision's record, not a `"follow-up"`."""
        rounds_root = tmp_path / "rounds"
        round_dir = rounds_root / "r9-2026-08"
        round_dir.mkdir(parents=True)
        (round_dir / "SELECTION.md").write_text(_SELECTION_FIXTURE, encoding="utf-8")
        _patch_roots(monkeypatch, rounds_root, tmp_path / "DEFECTS.md")

        resp = client.get("/api/competition/rounds/r9-2026-08/findings")

        body = resp.json()
        assert body["findings"], "fixture must produce entries"
        assert all(f["kind"] == "decision" for f in body["findings"])

        # Section 2's open-item language flips carries_forward True independent of kind.
        by_id = {f["id"]: f for f in body["findings"]}
        assert by_id["r9-selection-2"]["carries_forward"] is True
        assert by_id["r9-selection-1"]["carries_forward"] is False

    def test_report_follow_up_heading_gets_follow_up_kind(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`kind` and `carries_forward` are independent judgements: `REPORT.md`'s "What changes for
        round 10" section is classified `kind == "follow-up"` by its heading alone, even though its
        body uses none of `OPEN_ITEM_KEYWORDS` and so `carries_forward` reads `False` for it -- kind
        does not force the flag, and the flag does not force the kind."""
        rounds_root = tmp_path / "rounds"
        round_dir = rounds_root / "r9-2026-08"
        round_dir.mkdir(parents=True)
        (round_dir / "REPORT.md").write_text(_REPORT_FIXTURE, encoding="utf-8")
        _patch_roots(monkeypatch, rounds_root, tmp_path / "DEFECTS.md")

        resp = client.get("/api/competition/rounds/r9-2026-08/findings")

        body = resp.json()
        by_id = {f["id"]: f for f in body["findings"]}
        assert by_id["r9-report-1"]["kind"] == "finding"
        followup_entry = by_id["r9-report-2"]
        assert followup_entry["kind"] == "follow-up"
        assert followup_entry["carries_forward"] is False
        assert followup_entry["id"] not in {f["id"] for f in body["follow_ups"]}

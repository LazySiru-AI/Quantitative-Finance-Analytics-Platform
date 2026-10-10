"""Integration tests for the competition-jobs HTTP API (`app.api.competition_jobs`) and its business
logic (`app.tournament.jobs`).

`app.main` does not wire this router yet -- see `tests/test_macro_api.py`'s module docstring for why
that is normal at this stage and does not block testing the router in isolation: the `app` fixture
below builds its own minimal `FastAPI` app around `competition_jobs.router`.

**No test here runs a real round.** `app.tournament.jobs.run_card` is monkeypatched with a fast fake
that returns a synthetic `AgentResult` immediately (or after a short, deterministic sleep, for the
handful of tests that need the background worker to still be alive when the next assertion runs).
Every test also monkeypatches the job registry's output root to a `tmp_path` via
`jobs.reset_registry(output_root=...)` -- the injectable root the job system exists to support for
exactly this reason -- so nothing here ever writes into the real `strategy-program/rounds/`.

Card resolution goes through the *real* `strategy-program/library/` -- `B-momentum` (base) and
`C-trend` (candidates) are real, already-committed cards, and reading their JSON is cheap and has no
side effect. Only `run_card` itself (the part that would take minutes to hours) is faked.

Polling is bounded everywhere: `_poll_until` sleeps in short increments up to a fixed timeout and
fails with a clear message rather than hanging if a job never reaches the expected state.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import re
import sys
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import competition_jobs
from app.tournament import jobs
from app.tournament.models import AgentResult, StrategyCard

_REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Fake `run_card` -- the only thing standing between these tests and a real, hours-long round
# ---------------------------------------------------------------------------


def _fake_result(card: StrategyCard) -> AgentResult:
    return AgentResult(
        card=card,
        sessions=10,
        starting_equity=Decimal("10000.00"),
        ending_equity=Decimal("10500.00"),
        total_return=Decimal("0.05"),
        max_drawdown=Decimal("-0.02"),
        trades=(),
        benchmark_return=Decimal("0.02"),
        capital_exposure=0.4,
    )


def _make_fake_run_card(
    *, delay: float = 0.0, fail_agents: frozenset[str] = frozenset()
) -> Callable[..., AgentResult]:
    """A `run_card` replacement: sleeps `delay` seconds (so the worker thread stays observably alive
    long enough for a test to act while it runs), then either raises (for any `agent_id` in
    `fail_agents`, exercising the per-card-failure path) or returns a fixed, fast `AgentResult`."""

    def fake(
        card: StrategyCard,
        *,
        settings: object,
        mandate: object,
        start: dt.date,
        end: dt.date,
    ) -> AgentResult:
        if delay:
            time.sleep(delay)
        if card.agent_id in fail_agents:
            raise RuntimeError(f"synthetic failure for {card.agent_id}")
        return _fake_result(card)

    return fake


def _poll_until(
    fetch: Callable[[], Any],
    predicate: Callable[[Any], bool],
    *,
    timeout: float = 5.0,
    interval: float = 0.05,
) -> Any:
    """Poll `fetch()` until `predicate` is true, sleeping `interval` seconds between tries.

    Fails with a clear message (including the last observed value) rather than hanging, so a broken
    worker shows up as a fast, readable test failure instead of a stuck test run.
    """
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fetch()
        if predicate(last):
            return last
        time.sleep(interval)
    pytest.fail(f"timed out after {timeout}s waiting for condition; last observed value: {last!r}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    """A bare app around just the competition-jobs router -- see the module docstring for why this
    does not import `app.main`."""
    fastapi_app = FastAPI()
    fastapi_app.include_router(competition_jobs.router)
    return fastapi_app


@pytest.fixture
def client(app: FastAPI, tmp_path: Path) -> TestClient:
    """A client with a fresh, isolated job registry writing under `tmp_path` rather than the real
    `strategy-program/rounds/`."""
    jobs.reset_registry(output_root=tmp_path)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_registry_after_every_test() -> None:
    """Belt and braces: whatever a test leaves behind (a still-sleeping fake `run_card` in a daemon
    thread, a populated registry) must not leak into the next test's assertions. The `client` fixture
    already resets before each test that uses it; this also resets afterward, and covers the direct
    `jobs.start_job` calls that do not go through `client` at all."""
    yield
    jobs.reset_registry()


# ---------------------------------------------------------------------------
# 1. Happy path: POST -> 202, poll GET -> succeeded
# ---------------------------------------------------------------------------


class TestCreateAndPoll:
    def test_post_returns_202_and_polling_reaches_succeeded(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(jobs, "run_card", _make_fake_run_card())

        response = client.post(
            "/api/competition/jobs",
            json={"round_id": "r-happy", "cards": ["B-momentum", "C-trend"], "windows": ["covid"]},
        )

        assert response.status_code == 202
        body = response.json()
        assert body["status"] in ("queued", "running")
        assert body["round_id"] == "r-happy"
        assert body["total_runs"] == 2
        job_id = body["job_id"]
        assert job_id

        final = _poll_until(
            lambda: client.get(f"/api/competition/jobs/{job_id}").json(),
            lambda s: s["status"] in ("succeeded", "failed", "cancelled"),
        )

        assert final["status"] == "succeeded"
        assert final["completed_runs"] == final["total_runs"] == 2
        assert final["failed_runs"] == 0
        assert final["error"] is None
        assert len(final["results"]) == 2
        assert final["current"] is None
        assert final["finished_at"] is not None
        # Money crosses the wire as a string, never a JSON number.
        assert isinstance(final["results"][0]["total_return"], str)
        assert final["log"], "the reconciliation line should have been appended to the log"

    def test_get_unknown_job_id_is_404(self, client: TestClient) -> None:
        response = client.get("/api/competition/jobs/not-a-real-job-id")
        assert response.status_code == 404

    def test_list_jobs_includes_the_created_job_newest_first(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(jobs, "run_card", _make_fake_run_card())

        response = client.post(
            "/api/competition/jobs",
            json={"round_id": "r-list", "cards": ["B-momentum"], "windows": ["covid"]},
        )
        job_id = response.json()["job_id"]

        _poll_until(
            lambda: client.get(f"/api/competition/jobs/{job_id}").json(),
            lambda s: s["status"] in ("succeeded", "failed", "cancelled"),
        )

        listed = client.get("/api/competition/jobs").json()
        assert listed["jobs"][0]["job_id"] == job_id


# ---------------------------------------------------------------------------
# 2. One round at a time
# ---------------------------------------------------------------------------


class TestConcurrencyLock:
    def test_second_post_while_one_is_running_is_409_naming_the_live_job(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A real sleep so the first job is unambiguously still "running" when the second POST fires.
        monkeypatch.setattr(jobs, "run_card", _make_fake_run_card(delay=0.3))

        first = client.post(
            "/api/competition/jobs",
            json={"round_id": "r-first", "cards": ["B-momentum"], "windows": ["covid"]},
        )
        assert first.status_code == 202
        first_job_id = first.json()["job_id"]

        second = client.post(
            "/api/competition/jobs",
            json={"round_id": "r-second", "cards": ["C-trend"], "windows": ["covid"]},
        )

        assert second.status_code == 409
        assert first_job_id in second.json()["detail"]

        # Drain the first job so its daemon thread does not outlive the test in a confusing way.
        _poll_until(
            lambda: client.get(f"/api/competition/jobs/{first_job_id}").json(),
            lambda s: s["status"] in ("succeeded", "failed", "cancelled"),
        )


# ---------------------------------------------------------------------------
# 3. Validation: unknown card/window, bad round_id, round already populated
# ---------------------------------------------------------------------------


class TestValidation:
    def test_unknown_card_is_422_naming_it(self, client: TestClient) -> None:
        response = client.post(
            "/api/competition/jobs",
            json={"round_id": "r-bad-card", "cards": ["not-a-real-card"], "windows": ["covid"]},
        )
        assert response.status_code == 422
        assert "not-a-real-card" in response.json()["detail"]

    def test_unknown_window_is_422_naming_it(self, client: TestClient) -> None:
        response = client.post(
            "/api/competition/jobs",
            json={"round_id": "r-bad-window", "cards": ["B-momentum"], "windows": ["not-a-window"]},
        )
        assert response.status_code == 422
        assert "not-a-window" in response.json()["detail"]

    @pytest.mark.parametrize(
        "bad_round_id",
        ["Has-Upper-Case", "-leading-hyphen", "has spaces", ""],
    )
    def test_malformed_round_id_is_422(self, client: TestClient, bad_round_id: str) -> None:
        response = client.post(
            "/api/competition/jobs",
            json={"round_id": bad_round_id, "cards": ["B-momentum"], "windows": ["covid"]},
        )
        assert response.status_code == 422, bad_round_id

    def test_round_with_existing_run_files_is_409(self, client: TestClient, tmp_path: Path) -> None:
        existing = tmp_path / "r-taken" / "results" / "covid" / "runs"
        existing.mkdir(parents=True)
        (existing / "r1-B-momentum.json").write_text("{}", encoding="utf-8")

        response = client.post(
            "/api/competition/jobs",
            json={"round_id": "r-taken", "cards": ["B-momentum"], "windows": ["covid"]},
        )

        assert response.status_code == 409
        assert "r-taken" in response.json()["detail"]

    def test_unknown_tier_is_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/competition/jobs",
            json={"round_id": "r-bad-tier", "tier": "not-a-tier"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# 4. A per-card failure is recorded and walked past
# ---------------------------------------------------------------------------


class TestPartialFailure:
    def test_one_failing_card_is_recorded_failed_while_the_job_still_succeeds(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(jobs, "run_card", _make_fake_run_card(fail_agents=frozenset({"C-trend"})))

        response = client.post(
            "/api/competition/jobs",
            json={"round_id": "r-partial", "cards": ["B-momentum", "C-trend"], "windows": ["covid"]},
        )
        job_id = response.json()["job_id"]

        final = _poll_until(
            lambda: client.get(f"/api/competition/jobs/{job_id}").json(),
            lambda s: s["status"] in ("succeeded", "failed", "cancelled"),
        )

        assert final["status"] == "succeeded"
        assert final["completed_runs"] == 1
        assert final["failed_runs"] == 1
        assert final["error"] is None, "a single card's failure must not become a job-level error"

        by_agent = {r["agent_id"]: r for r in final["results"]}
        assert by_agent["B-momentum"]["status"] == "ok"
        assert by_agent["C-trend"]["status"] == "failed"
        assert "synthetic failure" in by_agent["C-trend"]["error"]


# ---------------------------------------------------------------------------
# 5. Cancellation
# ---------------------------------------------------------------------------


class TestCancellation:
    def test_delete_cancels_and_remaining_runs_are_not_executed(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(jobs, "run_card", _make_fake_run_card(delay=0.3))

        response = client.post(
            "/api/competition/jobs",
            json={
                "round_id": "r-cancel",
                "cards": ["B-momentum", "C-trend"],
                "windows": ["covid", "bear-2022"],
            },
        )
        assert response.json()["total_runs"] == 4
        job_id = response.json()["job_id"]

        cancel_response = client.delete(f"/api/competition/jobs/{job_id}")
        assert cancel_response.status_code == 200

        final = _poll_until(
            lambda: client.get(f"/api/competition/jobs/{job_id}").json(),
            lambda s: s["status"] in ("succeeded", "failed", "cancelled"),
            timeout=5.0,
        )

        assert final["status"] == "cancelled"
        assert final["completed_runs"] + final["failed_runs"] < final["total_runs"]

    def test_delete_unknown_job_is_404(self, client: TestClient) -> None:
        response = client.delete("/api/competition/jobs/not-a-real-job-id")
        assert response.status_code == 404

    def test_delete_an_already_finished_job_is_409(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(jobs, "run_card", _make_fake_run_card())

        response = client.post(
            "/api/competition/jobs",
            json={"round_id": "r-finished", "cards": ["B-momentum"], "windows": ["covid"]},
        )
        job_id = response.json()["job_id"]
        _poll_until(
            lambda: client.get(f"/api/competition/jobs/{job_id}").json(),
            lambda s: s["status"] in ("succeeded", "failed", "cancelled"),
        )

        second_delete = client.delete(f"/api/competition/jobs/{job_id}")
        assert second_delete.status_code == 409


# ---------------------------------------------------------------------------
# 6. Run files: correct path, and round-trip through AgentResult.model_validate_json
# ---------------------------------------------------------------------------


class TestRunFileRoundTrip:
    def test_run_files_land_at_the_documented_path_and_round_trip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        jobs.reset_registry(output_root=tmp_path)
        monkeypatch.setattr(jobs, "run_card", _make_fake_run_card())

        accepted = jobs.start_job(
            jobs.JobCreateRequest(round_id="rt-check", cards=["B-momentum"], windows=["covid"]),
            output_root=tmp_path,
        )

        final = _poll_until(
            lambda: jobs.get_job(accepted.job_id),
            lambda s: s.status in ("succeeded", "failed", "cancelled"),
        )
        assert final.status == "succeeded"

        run_path = tmp_path / "rt-check" / "results" / "covid" / "runs" / "r1-B-momentum.json"
        assert run_path.is_file(), f"expected a run file at {run_path}"

        loaded = AgentResult.model_validate_json(run_path.read_text(encoding="utf-8"))
        assert loaded.card.agent_id == "B-momentum"
        assert loaded.total_return == Decimal("0.05")


# ---------------------------------------------------------------------------
# 7. Window-constant drift check against strategy-program/tools/windows.py
# ---------------------------------------------------------------------------


class TestWindowConstantDrift:
    """`app.tournament.jobs.WINDOWS` is a hand-copied duplicate of `strategy-program/tools/
    windows.py`'s `WINDOWS` dict -- that module cannot be imported (`strategy-program` is not a legal
    Python package name), so the only way to keep the two in step is to parse the source text of the
    real file and compare it against the copy. This is a genuine text parse of the *actual* source
    file on disk, not a hardcoded re-statement of its contents: editing either file without updating
    the other fails this test.
    """

    _ENTRY_PATTERN = re.compile(
        r'"([a-z0-9-]+)":\s*'
        r"\(dt\.date\((\d+),\s*(\d+),\s*(\d+)\),\s*"
        r'dt\.date\((\d+),\s*(\d+),\s*(\d+)\),\s*"([^"]*)"\)'
    )

    def test_windows_source_file_still_exists_where_expected(self) -> None:
        path = _REPO_ROOT / "strategy-program" / "tools" / "windows.py"
        assert path.is_file(), (
            "strategy-program/tools/windows.py has moved or been renamed -- the drift check below "
            "cannot do its job if it cannot find the source of truth"
        )

    def test_jobs_windows_matches_the_source_of_truth_file(self) -> None:
        source = (_REPO_ROOT / "strategy-program" / "tools" / "windows.py").read_text(encoding="utf-8")
        matches = self._ENTRY_PATTERN.findall(source)

        assert matches, (
            "the text parser found zero window entries in windows.py -- either the parser is broken "
            "or the file's WINDOWS dict has changed shape enough to need a new pattern here; either "
            "way this must fail loudly rather than silently pass with an empty comparison"
        )

        parsed: dict[str, tuple[dt.date, dt.date, str]] = {}
        for tag, y1, m1, d1, y2, m2, d2, regime in matches:
            parsed[tag] = (
                dt.date(int(y1), int(m1), int(d1)),
                dt.date(int(y2), int(m2), int(d2)),
                regime,
            )

        assert parsed == jobs.WINDOWS, (
            "app.tournament.jobs.WINDOWS has drifted from strategy-program/tools/windows.py -- "
            "update the copy in jobs.py to match"
        )

    def test_main_windows_and_gate_constant_match_the_source_module(self) -> None:
        # `MAIN_WINDOWS` is the eight round-2/3 regimes only -- everything else in `WINDOWS` (the
        # 13F special case, round 4's six new regimes, and now round 5's 27-window horizon ladder)
        # is deliberately outside it. See `jobs.MAIN_WINDOWS`'s own comment for why this is no longer
        # "everything except 13f-legal" now that round 4's and round 5's windows share the same dict.
        #
        # This used to pin `len(jobs.WINDOWS) == 15` -- a magic number that round 5's 27 additional
        # windows would simply have broken without saying anything useful about what changed. The
        # real invariant is structural: `WINDOWS` is exactly the union of every named matrix this
        # module knows about, with no window belonging to more than one and none left over. Pinned
        # this way, adding a round-6 matrix later would fail this test only if the new windows were
        # *not* added to one of the named constants below -- which is the actual defect this test
        # exists to catch.
        assert set(jobs.WINDOWS) - set(jobs.MAIN_WINDOWS) == (
            {"13f-legal"}
            | set(jobs.R4_MAIN_WINDOWS)
            | set(jobs.R5_LADDER_WINDOWS)
            | set(jobs.R5_BEAR_WINDOWS)
            | set(jobs.R11_LIVE_WINDOWS)
            | set(jobs.R22_CURVE_WINDOWS)
        )
        named_matrices = (
            set(jobs.MAIN_WINDOWS)
            | {"13f-legal"}
            | set(jobs.R4_MAIN_WINDOWS)
            | set(jobs.R5_LADDER_WINDOWS)
            | set(jobs.R5_BEAR_WINDOWS)
            | set(jobs.R11_LIVE_WINDOWS)
            | set(jobs.R22_CURVE_WINDOWS)
        )
        assert named_matrices == set(jobs.WINDOWS), "every WINDOWS tag must belong to a named matrix"
        assert len(jobs.WINDOWS) == (
            len(jobs.MAIN_WINDOWS)
            + 1
            + len(jobs.R4_MAIN_WINDOWS)
            + len(jobs.R5_LADDER_WINDOWS)
            + len(jobs.R5_BEAR_WINDOWS)
            + len(jobs.R11_LIVE_WINDOWS)
            + len(jobs.R22_CURVE_WINDOWS)
        ), (
            "a tag counted in two matrices at once (or missing from all of them) would still pass "
            "the set-equality check above by accident of set arithmetic; the length check catches that"
        )
        assert len(jobs.R22_CURVE_WINDOWS) == 3
        assert len(jobs.R5_LADDER_WINDOWS) == 21
        assert len(jobs.R5_BEAR_WINDOWS) == 6
        assert jobs.MIN_ELIGIBLE_MAIN_WINDOWS == 5
        assert jobs.MIN_ELIGIBLE_R5_PER_HORIZON == 2


# ---------------------------------------------------------------------------
# 8. Round 5's 27-window horizon ladder -- anti-drift guard against the committed source of truth
# ---------------------------------------------------------------------------


class TestRound5WindowsAgainstSourceOfTruth:
    """`data/rounds/r5-2026-08/windows.json` is the contract round 5 was built from -- both
    `app.tournament.jobs.WINDOWS` and `strategy-program/tools/windows.py`'s `WINDOWS` are hand
    transcriptions of it, and a transcription error (a fat-fingered digit in a date, a horizon copied
    to the wrong tag) would not show up any other way: nothing re-derives these dates from the JSON at
    runtime, so a wrong date just sits there looking plausible until scored results come out wrong.
    This is that check, run directly against the real committed file.
    """

    def _load_source_json(self) -> dict[str, Any]:
        path = _REPO_ROOT / "data" / "rounds" / "r5-2026-08" / "windows.json"
        assert path.is_file(), f"expected the round-5 source of truth at {path}"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_ladder_and_bear_dates_and_horizons_match_the_source_file_exactly(self) -> None:
        source = self._load_source_json()
        arms = source["arms"]
        assert len(arms["ladder"]) == 21
        assert len(arms["bear"]) == 6

        for entry in arms["ladder"] + arms["bear"]:
            tag = entry["tag"]
            expected_start = dt.date.fromisoformat(entry["start"])
            expected_end = dt.date.fromisoformat(entry["end"])

            assert tag in jobs.WINDOWS, f"{tag} from windows.json is missing from jobs.WINDOWS"
            start, end, label = jobs.WINDOWS[tag]
            assert (start, end) == (expected_start, expected_end), tag
            assert label == entry["label"], tag

            assert tag in jobs.R5_HORIZON, f"{tag} missing from jobs.R5_HORIZON"
            assert jobs.R5_HORIZON[tag] == entry["horizon"], tag

        ladder_tags = {entry["tag"] for entry in arms["ladder"]}
        bear_tags = {entry["tag"] for entry in arms["bear"]}
        assert set(jobs.R5_LADDER_WINDOWS) == ladder_tags
        assert set(jobs.R5_BEAR_WINDOWS) == bear_tags
        assert ladder_tags.isdisjoint(bear_tags)


# ---------------------------------------------------------------------------
# 9. strategy-program/tools/windows.py and app.tournament.jobs must agree on round 5
# ---------------------------------------------------------------------------


class TestWindowsToolAgreesWithJobsOnRound5:
    """`strategy-program/tools/windows.py` and `app.tournament.jobs` deliberately duplicate the same
    window table (see both modules' comments on why one cannot import the other), and round 5 added
    27 more tags to keep in step by hand. `TestWindowConstantDrift` above already guards `WINDOWS`
    itself via a text parse; this guards the round-5-specific dicts (`R5_LADDER_WINDOWS`,
    `R5_BEAR_WINDOWS`, `R5_HORIZON`) the same way `tests/test_portfolio_tool.py` loads
    `strategy-program/tools/portfolio.py` -- by file path via `importlib.util.spec_from_file_location`,
    since `strategy-program` is not a legal Python package name.
    """

    @pytest.fixture(scope="module")
    def windows_tool(self) -> ModuleType:
        path = _REPO_ROOT / "strategy-program" / "tools" / "windows.py"
        spec = importlib.util.spec_from_file_location("strategy_program_tools_windows", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def test_ladder_windows_agree(self, windows_tool: ModuleType) -> None:
        assert windows_tool.R5_LADDER_WINDOWS == jobs.R5_LADDER_WINDOWS

    def test_bear_windows_agree(self, windows_tool: ModuleType) -> None:
        assert windows_tool.R5_BEAR_WINDOWS == jobs.R5_BEAR_WINDOWS

    def test_horizon_map_agrees(self, windows_tool: ModuleType) -> None:
        assert windows_tool.R5_HORIZON == jobs.R5_HORIZON

    def test_gate_constant_agrees(self, windows_tool: ModuleType) -> None:
        assert windows_tool.MIN_ELIGIBLE_R5_PER_HORIZON == jobs.MIN_ELIGIBLE_R5_PER_HORIZON

    def test_every_round5_tag_is_covered_by_both_files(self, windows_tool: ModuleType) -> None:
        tool_tags = set(windows_tool.R5_LADDER_WINDOWS) | set(windows_tool.R5_BEAR_WINDOWS)
        jobs_tags = set(jobs.R5_LADDER_WINDOWS) | set(jobs.R5_BEAR_WINDOWS)
        assert len(tool_tags) == 27
        assert tool_tags == jobs_tags


# ---------------------------------------------------------------------------
# 10. Regression guard: round 5's arrival must not have touched rounds 2-4's published constants
# ---------------------------------------------------------------------------


class TestRound2AndRound4ConstantsUntouchedByRound5:
    """Rounds 2, 3 and 4 published results scored against `MAIN_WINDOWS`/`R4_MAIN_WINDOWS` and their
    gates -- those must stay reproducible forever, which means adding round 5 must not have changed a
    single date, label or tag among them, let alone the gate constants. Pinned as literal, hand-typed
    dicts (not derived from `jobs.WINDOWS` the way the module's own constants are) so this test would
    catch an edit to the *source* dict entries too, not only to which subset gets selected out of it.
    """

    def test_main_windows_is_byte_identical_to_its_published_values(self) -> None:
        assert {
            "q4-2018": (dt.date(2018, 9, 21), dt.date(2018, 12, 24), "sharp quarter-long selloff"),
            "covid": (dt.date(2020, 2, 19), dt.date(2020, 6, 30), "COVID crash and snapback"),
            "bear-2022": (dt.date(2022, 1, 3), dt.date(2022, 10, 12), "rate-driven bear"),
            "chop-2015": (dt.date(2015, 4, 7), dt.date(2016, 4, 15), "sideways"),
            "chop-2011": (dt.date(2011, 5, 26), dt.date(2012, 6, 6), "sideways, higher volatility"),
            "bull-2024": (dt.date(2024, 8, 21), dt.date(2025, 8, 20), "bull"),
            "recent": (dt.date(2025, 8, 21), dt.date(2026, 8, 18), "recent bull"),
            "gfc": (dt.date(2007, 10, 9), dt.date(2009, 3, 9), "GFC bear"),
        } == jobs.MAIN_WINDOWS
        assert jobs.MIN_ELIGIBLE_MAIN_WINDOWS == 5

    def test_r4_main_windows_is_byte_identical_to_its_published_values(self) -> None:
        assert {
            "oil-2014": (dt.date(2014, 6, 20), dt.date(2015, 2, 11), "oil collapse and dollar surge"),
            "volmageddon-2018": (dt.date(2018, 1, 26), dt.date(2018, 4, 2), "volatility shock"),
            "taper-2013": (dt.date(2013, 5, 22), dt.date(2013, 9, 5), "rate shock, taper tantrum"),
            "recovery-2009": (
                dt.date(2009, 3, 10),
                dt.date(2010, 4, 23),
                "post-crisis recovery rally",
            ),
            "inflation-2021": (
                dt.date(2021, 1, 4),
                dt.date(2021, 12, 31),
                "inflation onset and rotation",
            ),
            "banks-2023": (dt.date(2023, 3, 1), dt.date(2023, 5, 31), "regional banking crisis"),
        } == jobs.R4_MAIN_WINDOWS
        assert jobs.MIN_ELIGIBLE_R4_WINDOWS == 4

    def test_provenance_constrained_windows_still_names_only_13f_legal(self) -> None:
        assert frozenset({"13f-legal"}) == jobs.PROVENANCE_CONSTRAINED_WINDOWS

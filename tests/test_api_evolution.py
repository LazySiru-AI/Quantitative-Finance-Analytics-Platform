"""HTTP-layer tests for `app.api.evolution`.

Mirrors `tests/test_competition_jobs.py`'s split with `app.tournament.jobs`: this file only exercises
the thin adapter (status codes, error mapping, response shapes) via FastAPI's `TestClient`.
`app.evolution.loop`'s own behaviour -- retries, the failure-isolation guarantee, elites carried
forward, the stop sequence -- is covered directly in `tests/test_evolution_loop.py` instead, with the
supervisor called as a plain Python function.

**Two things are monkeypatched on every request, not one.** `app.evolution.loop.start_loop` reaches
for `get_settings()` and `default_collaborators()` whenever the HTTP layer omits them -- which it
always does, since the wire contract (`POST /api/competition/loop` with just a `LoopConfig` body) has
no way to inject either. Left unpatched, a POST here would try to import the (concurrently-written,
not-yet-necessarily-complete) sibling packages and would write real files under the repository's own
`data/`. The `client` fixture patches both `app.evolution.loop.get_settings` (to a `tmp_path`-backed
`Settings`) and `app.evolution.loop.default_collaborators` (to a small set of fast, deterministic
fakes) before building the `TestClient`.
"""

from __future__ import annotations

import datetime as dt
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import evolution
from app.config import Settings
from app.evolution import loop as loop_module
from app.evolution.loop import Collaborators
from app.evolution.models import Finding, GenerationOutcome, Genome, LoopConfig, Standing, loop_root
from app.tournament.purposes import Purpose

# ---------------------------------------------------------------------------
# A minimal, self-contained fake collaborator set -- this file does not import
# tests/test_evolution_loop.py's fakes, matching how test_competition_jobs.py defines its own fakes
# rather than sharing a module with another test file.
# ---------------------------------------------------------------------------


def _make_genome(*, generation: int, index: int, purpose: Purpose) -> Genome:
    return Genome(
        genome_id=f"g{generation:03d}-api{index:02d}",
        generation=generation,
        origin="founder",
        shape="rules",
        purpose=purpose,
        universe=("SPY", "QQQ"),
        traits={},
        seed=index,
        notes="api test candidate",
    )


def _propose(
    *,
    generation: int,
    purpose: Purpose,
    config: Any,
    rng: Any,
    elites: tuple[Genome, ...] = (),
    news_symbols: tuple[str, ...] = (),
) -> tuple[Genome, ...]:
    return tuple(_make_genome(generation=generation, index=i, purpose=purpose) for i in range(config.population))


def _write_cards(genomes: tuple[Genome, ...], *, settings: Settings) -> dict[str, Path]:
    return {}


def _card_for(genome: Genome) -> object:
    return SimpleNamespace(agent_id=genome.genome_id)


def _run_generation(*, round_id, cards, windows, settings, cancel, log, output_root, max_workers=1) -> Any:
    return SimpleNamespace(
        round_id=round_id,
        job_id="job",
        status="succeeded",
        windows=windows,
        completed_runs=len(cards) * len(windows),
        failed_runs=0,
        errors=(),
    )


def _read_standings(
    *, round_id, purpose, genomes, config, settings, selection_windows, holdout_windows, rounds_root=None
) -> tuple[Standing, ...]:
    # `genomes` is `dict[genome_id, Genome]` -- the real (landed) `feedback.read_standings` takes a
    # `Mapping[str, Genome]`, not a plain sequence, so this iterates `.values()` rather than the dict
    # itself (which would yield genome ids, not `Genome` objects).
    return tuple(
        Standing(
            genome_id=genome.genome_id,
            agent_id=genome.genome_id,
            display_name=genome.genome_id,
            rank=i + 1,
            eligible=True,
            windows_run=1,
            median_excess=None,
            worst_excess=None,
            hit_rate=None,
            total_trades=0,
        )
        for i, genome in enumerate(genomes.values())
    )


def _derive_findings(standings, *, config, purpose, selection_windows, holdout_windows, genomes) -> tuple[Finding, ...]:
    return ()


def _select_elites(standings, genomes, *, config) -> tuple[Genome, ...]:
    return ()


def _ledger_entries_for(standings, *, round_id, purpose, generation, selection_windows, settings) -> tuple[Any, ...]:
    return ()


def _evaluate_promotions(
    *, standings, genomes, history, config, generation, selection_windows, settings
) -> tuple[Any, ...]:
    return ()


def _trending_symbols(*, purpose: Purpose, settings: Settings, limit: int = 8) -> tuple[str, ...]:
    return ()


class _FakeLedger:
    def record(self, entries: Any) -> None:
        pass

    def distinct_candidates(self) -> int:
        return 0

    def q_values(self) -> dict[str, float]:
        return {}


def _open_ledger(settings: Settings) -> _FakeLedger:
    return _FakeLedger()


def _fake_collaborators() -> Collaborators:
    return Collaborators(
        propose=_propose,
        write_cards=_write_cards,
        card_for=_card_for,
        run_generation=_run_generation,
        read_standings=_read_standings,
        derive_findings=_derive_findings,
        select_elites=_select_elites,
        ledger_entries_for=_ledger_entries_for,
        evaluate_promotions=_evaluate_promotions,
        trending_symbols=_trending_symbols,
        open_ledger=_open_ledger,
    )


def _poll_until(fetch: Any, predicate: Any, *, timeout: float = 5.0, interval: float = 0.02) -> Any:
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
    """A bare app around just the evolution router -- `app.main` is not exercised here, the same
    reasoning `tests/test_competition_jobs.py` gives for its own `app` fixture."""
    fastapi_app = FastAPI()
    fastapi_app.include_router(evolution.router)
    return fastapi_app


@pytest.fixture
def client(app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    fake_settings = Settings(data_dir=tmp_path / "data", rounds_dir=tmp_path / "data" / "rounds")
    monkeypatch.setattr(loop_module, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(loop_module, "default_collaborators", _fake_collaborators)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_loop_after_every_test() -> None:
    yield
    loop_module.reset()


# ---------------------------------------------------------------------------
# GET before anything has ever started -> 404
# ---------------------------------------------------------------------------


class TestGetBeforeAnyLoopStarted:
    def test_returns_404(self, client: TestClient) -> None:
        response = client.get("/api/competition/loop")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE before anything has ever started -> 409
# ---------------------------------------------------------------------------


class TestDeleteBeforeAnyLoopStarted:
    def test_returns_409(self, client: TestClient) -> None:
        response = client.delete("/api/competition/loop")
        assert response.status_code == 409


# ---------------------------------------------------------------------------
# History never 404s
# ---------------------------------------------------------------------------


class TestHistoryBeforeAnyLoopStarted:
    def test_returns_empty_list_not_404(self, client: TestClient) -> None:
        response = client.get("/api/competition/loop/history")
        assert response.status_code == 200
        assert response.json() == {"generations": []}


# ---------------------------------------------------------------------------
# POST -> 202, poll GET -> 200 stopped, history reflects it
# ---------------------------------------------------------------------------


class TestStartAndPoll:
    def test_post_returns_202_and_polling_reaches_stopped(self, client: TestClient) -> None:
        response = client.post(
            "/api/competition/loop",
            json={
                "purposes": ["trading"],
                "population": 2,
                "windows": ["w1"],
                "holdout_windows": [],
                "max_generations": 2,
                "use_news": False,
            },
        )
        assert response.status_code == 202
        body = response.json()
        assert body["state"] == "running"
        loop_id = body["loop_id"]

        final = _poll_until(
            lambda: client.get("/api/competition/loop").json(),
            lambda b: b.get("state") in ("stopped", "failed"),
        )
        assert final["state"] == "stopped"
        assert final["error"] is None
        assert final["loop_id"] == loop_id
        assert final["completed_generations"] == 2
        # Not just "the loop kept moving" -- each generation must actually have succeeded, not merely
        # been recorded as `status="failed"` and walked past (a failed generation still advances
        # `completed_generations`, by design, so that counter alone cannot catch a collaborator that
        # is silently broken end to end).
        assert all(outcome["status"] == "succeeded" for outcome in final["history"])

        history = client.get("/api/competition/loop/history", params={"limit": 1}).json()
        assert len(history["generations"]) == 1
        assert history["generations"][0]["generation"] == 2
        assert history["generations"][0]["status"] == "succeeded"

    def test_empty_body_is_accepted_and_uses_loopconfig_defaults(self, client: TestClient) -> None:
        response = client.post("/api/competition/loop", json={})
        assert response.status_code == 202
        # Asserted against the imported default rather than a literal: this test's subject is "an
        # empty body is filled in from `LoopConfig`", not "the default happens to be N". Pinning the
        # number here made a deliberate change to the default (6 -> 10, so the Benjamini-Hochberg
        # correction in `app.evolution.ledger` has a less threadbare field to work over) look like a
        # regression in the API layer, which is the one thing this test is not about.
        assert response.json()["config"]["population"] == LoopConfig().population

        # Stop immediately rather than letting the default `max_generations=None` loop spin freely --
        # cooldown_seconds also defaults to 0, so left alone this would iterate as fast as the fakes
        # allow until something stops it.
        stop = client.delete("/api/competition/loop")
        assert stop.status_code == 200
        _poll_until(
            lambda: client.get("/api/competition/loop").json(),
            lambda b: b.get("state") in ("stopped", "failed"),
        )


# ---------------------------------------------------------------------------
# Second POST while running -> 409 naming the running loop
# ---------------------------------------------------------------------------


class TestStartTwiceReturns409:
    def test_second_post_returns_409_naming_the_running_loop(self, client: TestClient) -> None:
        first = client.post(
            "/api/competition/loop",
            json={
                "purposes": ["trading"],
                "population": 2,
                "windows": ["w1"],
                "max_generations": None,
                "cooldown_seconds": 0.05,
                "use_news": False,
            },
        )
        assert first.status_code == 202
        loop_id = first.json()["loop_id"]

        second = client.post("/api/competition/loop", json={})
        assert second.status_code == 409
        assert loop_id in second.json()["detail"]

        stop = client.delete("/api/competition/loop")
        assert stop.status_code == 200
        _poll_until(
            lambda: client.get("/api/competition/loop").json(),
            lambda b: b.get("state") in ("stopped", "failed"),
        )


# ---------------------------------------------------------------------------
# DELETE stops a running loop; a second DELETE (after it is terminal) -> 409
# ---------------------------------------------------------------------------


class TestStopThenNotRunning:
    def test_delete_after_natural_completion_returns_409(self, client: TestClient) -> None:
        started = client.post(
            "/api/competition/loop",
            json={
                "purposes": ["trading"],
                "population": 2,
                "windows": ["w1"],
                "max_generations": 1,
                "use_news": False,
            },
        )
        assert started.status_code == 202

        _poll_until(
            lambda: client.get("/api/competition/loop").json(),
            lambda b: b.get("state") in ("stopped", "failed"),
        )

        response = client.delete("/api/competition/loop")
        assert response.status_code == 409

    def test_delete_on_a_running_loop_returns_200_with_stopping_or_stopped_state(
        self, client: TestClient
    ) -> None:
        started = client.post(
            "/api/competition/loop",
            json={
                "purposes": ["trading"],
                "population": 2,
                "windows": ["w1"],
                "max_generations": None,
                "cooldown_seconds": 0.05,
                "use_news": False,
            },
        )
        assert started.status_code == 202

        response = client.delete("/api/competition/loop")
        assert response.status_code == 200
        assert response.json()["state"] in ("stopping", "stopped")

        _poll_until(
            lambda: client.get("/api/competition/loop").json(),
            lambda b: b.get("state") in ("stopped", "failed"),
        )


# ---------------------------------------------------------------------------
# Malformed body -> 422
# ---------------------------------------------------------------------------


class TestInvalidBodyReturns422:
    def test_population_out_of_range_is_422(self, client: TestClient) -> None:
        response = client.post("/api/competition/loop", json={"population": 999})
        assert response.status_code == 422

    def test_unknown_field_is_422(self, client: TestClient) -> None:
        # `LoopConfig` is `extra="forbid"` (see `app.evolution.models._Frozen`), so a typo'd field
        # name is a validation error, not a silently-ignored key.
        response = client.post("/api/competition/loop", json={"popuation": 6})
        assert response.status_code == 422


class TestUnreachablePromotionCeilingReturns400:
    """A well-formed body whose *combination* of legal fields can never be satisfied.

    `422` is FastAPI's answer for a field that is individually invalid; this is not that. Every field
    here passes its own validator, and what is wrong -- a promotion overlap ceiling below what the
    configured window pool can produce -- is only visible against `MAIN_WINDOWS` and
    `MIN_ELIGIBLE_MAIN_WINDOWS`, which the request model cannot see. Getting a `500` for it would be
    the worst outcome: the caller would read "server error" for a config the server understood
    perfectly well and was right to refuse.
    """

    def test_a_ceiling_below_the_achievable_floor_is_400_naming_the_floor(
        self, client: TestClient
    ) -> None:
        response = client.post("/api/competition/loop", json={"promotion_max_shared_windows": 2})
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "always share at least 4 window(s)" in detail
        assert "Raise the ceiling to 4 or more" in detail

    def test_the_refusal_leaves_no_loop_registered(self, client: TestClient) -> None:
        """The guard runs before the singleton lock, so a refused start must not make the *next*
        legitimate start a 409."""
        client.post("/api/competition/loop", json={"promotion_max_shared_windows": 0})
        assert client.get("/api/competition/loop").status_code == 404

    def test_a_reachable_ceiling_is_accepted(self, client: TestClient) -> None:
        response = client.post(
            "/api/competition/loop",
            json={"promotion_max_shared_windows": 4, "max_generations": 1},
        )
        assert response.status_code == 202
        assert response.json()["config"]["promotion_max_shared_windows"] == 4


# ---------------------------------------------------------------------------
# GET /generations, GET /generations/{n}, GET /failure-streaks
#
# These three read `app.evolution.history` -- disk, not `LoopStatus` -- so no loop needs to have
# started for them to answer, and the `client` fixture's `tmp_path`-backed `Settings` is exactly what
# `loop_module.get_settings()` (the same accessor `POST`/`GET`/`DELETE` above already rely on) hands to
# `app.evolution.history` too. Generation directories are written directly onto disk here rather than
# through a real loop run -- `app.evolution.history`'s own test suite
# (`tests/test_evolution_history.py`) already covers the reader and its statistics in depth; this
# section only has to prove the HTTP layer wires query params, status codes and the response envelope
# correctly.
# ---------------------------------------------------------------------------


def _write_outcome(settings: Settings, generation: int, outcome: GenerationOutcome, *, plan: str | None = "# plan\n") -> None:
    gen_dir = loop_root(settings) / f"gen{generation:04d}"
    gen_dir.mkdir(parents=True, exist_ok=True)
    (gen_dir / "OUTCOME.json").write_text(outcome.model_dump_json(indent=2), encoding="utf-8")
    if plan is not None:
        (gen_dir / "PLAN.md").write_text(plan, encoding="utf-8")


def _outcome(generation: int, *, status: str = "succeeded", error: str | None = None) -> GenerationOutcome:
    started = dt.datetime(2026, 8, 1, tzinfo=dt.UTC) + dt.timedelta(minutes=generation)
    return GenerationOutcome(
        generation=generation,
        round_id=f"r1-auto-gen{generation:04d}",
        purpose=Purpose.TRADING,
        status=status,
        started_at=started,
        finished_at=started + dt.timedelta(seconds=10),
        windows=("chop-2015",),
        holdout_windows=(),
        genome_ids=(f"g{generation:03d}-a",),
        standings=(),
        findings=(),
        error=error,
    )


class TestGenerationsList:
    def test_empty_tree_returns_empty_not_404(self, client: TestClient) -> None:
        response = client.get("/api/competition/loop/generations")
        assert response.status_code == 200
        body = response.json()
        assert body == {"total": 0, "returned": 0, "offset": 0, "unreadable": 0, "generations": []}

    def test_pagination_and_newest_first(self, client: TestClient, tmp_path: Path) -> None:
        fake_settings = Settings(data_dir=tmp_path / "data", rounds_dir=tmp_path / "data" / "rounds")
        for gen in range(1, 4):
            _write_outcome(fake_settings, gen, _outcome(gen))

        response = client.get("/api/competition/loop/generations", params={"limit": 2})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        assert body["returned"] == 2
        assert [g["generation"] for g in body["generations"]] == [3, 2]

    def test_unreadable_zero_byte_outcome_is_counted_and_excluded(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        fake_settings = Settings(data_dir=tmp_path / "data", rounds_dir=tmp_path / "data" / "rounds")
        gen_dir = loop_root(fake_settings) / "gen0001"
        gen_dir.mkdir(parents=True)
        (gen_dir / "OUTCOME.json").write_text("", encoding="utf-8")

        response = client.get("/api/competition/loop/generations")
        body = response.json()
        assert body["total"] == 0
        assert body["unreadable"] == 1
        assert body["generations"] == []

    def test_limit_out_of_range_is_422(self, client: TestClient) -> None:
        response = client.get("/api/competition/loop/generations", params={"limit": 0})
        assert response.status_code == 422
        response = client.get("/api/competition/loop/generations", params={"limit": 201})
        assert response.status_code == 422

    def test_negative_offset_is_422(self, client: TestClient) -> None:
        response = client.get("/api/competition/loop/generations", params={"offset": -1})
        assert response.status_code == 422


class TestGenerationDetail:
    def test_404_for_missing_generation(self, client: TestClient) -> None:
        response = client.get("/api/competition/loop/generations/42")
        assert response.status_code == 404

    def test_returns_outcome_plan_and_null_review(self, client: TestClient, tmp_path: Path) -> None:
        fake_settings = Settings(data_dir=tmp_path / "data", rounds_dir=tmp_path / "data" / "rounds")
        _write_outcome(fake_settings, 5, _outcome(5), plan="# Generation 5 plan\n")

        response = client.get("/api/competition/loop/generations/5")
        assert response.status_code == 200
        body = response.json()
        assert body["outcome"]["generation"] == 5
        assert body["plan_markdown"] == "# Generation 5 plan\n"
        assert body["review"] is None

    def test_plan_markdown_is_null_when_plan_md_absent(self, client: TestClient, tmp_path: Path) -> None:
        fake_settings = Settings(data_dir=tmp_path / "data", rounds_dir=tmp_path / "data" / "rounds")
        _write_outcome(fake_settings, 6, _outcome(6), plan=None)

        response = client.get("/api/competition/loop/generations/6")
        assert response.status_code == 200
        assert response.json()["plan_markdown"] is None


class TestFailureStreaks:
    def test_empty_tree_returns_empty_streaks(self, client: TestClient) -> None:
        response = client.get("/api/competition/loop/failure-streaks")
        assert response.status_code == 200
        assert response.json() == {"streaks": []}

    def test_collapses_consecutive_identical_failures(self, client: TestClient, tmp_path: Path) -> None:
        fake_settings = Settings(data_dir=tmp_path / "data", rounds_dir=tmp_path / "data" / "rounds")
        for gen in range(1, 4):
            _write_outcome(fake_settings, gen, _outcome(gen, status="failed", error="OSError: read-only"))

        response = client.get("/api/competition/loop/failure-streaks")
        assert response.status_code == 200
        streaks = response.json()["streaks"]
        assert len(streaks) == 1
        assert streaks[0] == {
            "first_generation": 1,
            "last_generation": 3,
            "count": 3,
            "error": "OSError: read-only",
            "started_at": "2026-08-01T00:01:00Z",
            "finished_at": "2026-08-01T00:03:10Z",
            "purposes": ["trading"],
        }

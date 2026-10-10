"""Unit tests for `app.evolution.loop`, the endless supervisor thread.

**No test here calls a real sibling module.** At the time this file was written, five packages under
`app.evolution` (`proposer`, `execute`, `feedback`, `ledger`, `promotion`, `news_signal`) were being
written concurrently by other workers and did not necessarily exist yet. Every test builds its own
`app.evolution.loop.Collaborators` out of fast, deterministic fakes instead -- the whole reason that
dataclass exists. `app.evolution.models` (`LoopConfig`, `Standing`, `Genome`, ...) is this package's
already-settled contract and is used directly, never faked.

**Every fake `run_generation` asserts `PLAN.md` already exists** before it does anything else -- see
`_assert_plan_exists`. This is deliberately embedded in the shared fake rather than checked once in a
dedicated test, so every scenario below (the happy path, the retry path, the failure path) proves the
same ordering: the plan is written before the first card of its generation ever runs.

**Round ids are how a fake finds "its own" generation number.** `app.evolution.loop._mint_round_id`
appends `-g{generation:04d}` to every round id it mints specifically so a collaborator that only
receives `round_id` (not `generation` directly, per the frozen `execute.run_generation` signature) can
still recover which generation it is running for -- `_generation_from_round_id` below undoes that.

**Timing.** Every fake either returns immediately or blocks on the same `threading.Event` the
supervisor passes in as `cancel`, so a test only ever waits as long as `_poll_until`'s interval, not a
fixed sleep. The whole file should run in well under a second.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import re
import time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.agents.models import AgentBudget, AgentDisabled, AgentUnavailable, BudgetExhausted
from app.config import Settings
from app.evolution import loop as loop_module
from app.evolution.loop import Collaborators, GenerationDirectoryCollision
from app.evolution.models import (
    Finding,
    GenerationOutcome,
    Genome,
    LoopAlreadyRunning,
    LoopConfig,
    LoopNotRunning,
    Standing,
    loop_root,
)
from app.tournament.jobs import JobAlreadyRunning
from app.tournament.purposes import Purpose

# ---------------------------------------------------------------------------
# Small builders
# ---------------------------------------------------------------------------


def _make_genome(
    *,
    generation: int,
    index: int,
    purpose: Purpose,
    shape: str = "rules",
    parents: tuple[str, ...] = (),
) -> Genome:
    return Genome(
        genome_id=f"g{generation:03d}-{shape[:1]}fake{index:02d}",
        generation=generation,
        parents=parents,
        origin="founder" if not parents else "mutation",
        shape=shape,  # type: ignore[arg-type]
        purpose=purpose,
        universe=("SPY", "QQQ"),
        traits={"lookback": 20 + index},
        seed=index,
        notes=f"synthetic candidate {index} for generation {generation}",
    )


def _make_standing(genome: Genome, *, rank: int, median_excess: Decimal) -> Standing:
    return Standing(
        genome_id=genome.genome_id,
        agent_id=genome.genome_id,
        display_name=genome.genome_id,
        rank=rank,
        eligible=True,
        windows_run=1,
        median_excess=median_excess,
        worst_excess=median_excess,
        hit_rate=0.6,
        total_trades=12,
    )


_ROUND_GEN_SUFFIX = re.compile(r"-g(\d{4})$")


def _generation_from_round_id(round_id: str) -> int:
    match = _ROUND_GEN_SUFFIX.search(round_id)
    assert match is not None, f"round_id {round_id!r} carries no -gNNNN suffix"
    return int(match.group(1))


def _assert_plan_exists(settings: Settings, round_id: str) -> None:
    """The load-bearing assertion for requirement (f): `PLAN.md` must already be on disk the moment
    `run_generation` is entered, not merely by the time the generation finishes."""
    generation = _generation_from_round_id(round_id)
    plan_path = loop_root(settings) / f"gen{generation:04d}" / "PLAN.md"
    assert plan_path.exists(), (
        f"PLAN.md missing for generation {generation} before run_generation ran: {plan_path}"
    )


def _fake_execution_report(
    *, round_id: str, windows: tuple[str, ...], cards: list[object], status: str = "succeeded"
) -> SimpleNamespace:
    return SimpleNamespace(
        round_id=round_id,
        job_id=f"job-{round_id}",
        status=status,
        windows=windows,
        completed_runs=len(cards) * len(windows),
        failed_runs=0,
        errors=(),
    )


# ---------------------------------------------------------------------------
# Fake ledger
# ---------------------------------------------------------------------------


class _FakeLedger:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    def record(self, entries: Any) -> None:
        for entry in entries:
            self._seen.add(entry.genome_id)

    def distinct_candidates(self) -> int:
        return len(self._seen)

    def q_values(self) -> dict[str, float]:
        return {}


def _open_ledger(ledger: _FakeLedger) -> Any:
    def open_ledger(settings: Settings) -> _FakeLedger:
        return ledger

    return open_ledger


# ---------------------------------------------------------------------------
# The rest of the collaborators: shared, simple fakes
# ---------------------------------------------------------------------------


def _propose_factory(calls: list[dict[str, Any]]) -> Any:
    def propose(
        *,
        generation: int,
        purpose: Purpose,
        config: LoopConfig,
        rng: Any,
        shape: str = "rules",
        elites: tuple[Genome, ...] = (),
        news_symbols: tuple[str, ...] = (),
    ) -> tuple[Genome, ...]:
        # `shape` mirrors `proposer.propose_generation`'s own (concurrently-landed) signature -- see
        # `app.evolution.loop._execute_generation`'s `_accepts_kwarg(..., "shape")` check, which is
        # what lets this fake accepting it (and an older fake that does not) both keep working. Every
        # genome this fake returns carries the *requested* shape, exactly like the real proposer's
        # own lane-homogeneity guarantee (see `app.evolution.models.CardShape`'s docstring).
        calls.append({"generation": generation, "purpose": purpose, "shape": shape, "elites": elites})
        parents = tuple(genome.genome_id for genome in elites)
        return tuple(
            _make_genome(generation=generation, index=i, purpose=purpose, shape=shape, parents=parents)
            for i in range(config.population)
        )

    return propose


def _write_cards(genomes: tuple[Genome, ...], *, settings: Settings) -> dict[str, Path]:
    return {genome.genome_id: Path(f"fake/{genome.genome_id}.json") for genome in genomes}


def _write_cards_raising(genomes: tuple[Genome, ...], *, settings: Settings) -> dict[str, Path]:
    """Mirrors the real 1,644-failure incident's own failure point: `write_cards` itself raising
    (there, an `OSError` on a read-only mount). Asserts `PLAN.md` already exists for this generation
    *before* raising -- the load-bearing check for requirement (d): a generation whose card-writing
    fails must still leave a pre-registration record on disk, which is only true if `PLAN.md` is
    written before this call, not after it.

    `genomes[0].generation` recovers the generation number without needing a `round_id` (this fake
    receives only `genomes` and `settings`, per `Collaborators.write_cards`'s real signature) --
    every genome `_propose_factory` mints below carries the `generation` it was proposed for.
    """
    generation = genomes[0].generation
    plan_path = loop_root(settings) / f"gen{generation:04d}" / "PLAN.md"
    assert plan_path.exists(), (
        f"PLAN.md missing for generation {generation} before write_cards raised: {plan_path}"
    )
    raise OSError(30, "Read-only file system")


def _card_for(genome: Genome) -> object:
    return SimpleNamespace(agent_id=genome.genome_id)


def _read_standings_factory(calls: list[dict[str, Any]]) -> Any:
    def read_standings(
        *,
        round_id: str,
        purpose: Purpose,
        genomes: dict[str, Genome],
        config: LoopConfig,
        settings: Settings,
        selection_windows: tuple[str, ...],
        holdout_windows: tuple[str, ...],
        rounds_root: Path | None = None,
        holdout_round_id: str | None = None,
    ) -> tuple[Standing, ...]:
        calls.append(
            {"round_id": round_id, "rounds_root": rounds_root, "holdout_round_id": holdout_round_id}
        )
        return tuple(
            _make_standing(genome, rank=i + 1, median_excess=Decimal(str(30 - i)))
            for i, genome in enumerate(genomes.values())
        )

    return read_standings


def _derive_findings(
    standings: tuple[Standing, ...],
    *,
    config: LoopConfig,
    purpose: Purpose,
    selection_windows: tuple[str, ...],
    holdout_windows: tuple[str, ...],
    genomes: dict[str, Genome],
) -> tuple[Finding, ...]:
    return ()


def _select_elites(
    standings: tuple[Standing, ...], genomes: dict[str, Genome], *, config: LoopConfig
) -> tuple[Genome, ...]:
    # `genomes` is already keyed by `genome_id` -- exactly the mapping the real (landed)
    # `feedback.select_elites` takes -- so no rebuilding is needed, just a lookup.
    ranked = sorted(standings, key=lambda s: s.median_excess or Decimal("-Infinity"), reverse=True)
    return tuple(genomes[standing.genome_id] for standing in ranked[: config.elite_count])


def _ledger_entries_for(
    standings: tuple[Standing, ...],
    *,
    round_id: str,
    purpose: Purpose,
    generation: int,
    selection_windows: tuple[str, ...],
    settings: Settings,
    rounds_root: Path | None = None,
) -> tuple[Any, ...]:
    return tuple(SimpleNamespace(genome_id=standing.genome_id) for standing in standings)


def _evaluate_promotions(
    *,
    standings: tuple[Standing, ...],
    genomes: dict[str, Genome],
    history: tuple[Any, ...],
    config: LoopConfig,
    generation: int,
    selection_windows: tuple[str, ...],
    settings: Settings,
) -> tuple[Any, ...]:
    return ()


def _trending_symbols(*, purpose: Purpose, settings: Settings, limit: int = 8) -> tuple[str, ...]:
    return ()


def _build_collaborators(
    run_generation: Any,
    *,
    propose_calls: list[dict[str, Any]] | None = None,
    read_standings_calls: list[dict[str, Any]] | None = None,
    ledger: _FakeLedger | None = None,
) -> Collaborators:
    return Collaborators(
        propose=_propose_factory(propose_calls if propose_calls is not None else []),
        write_cards=_write_cards,
        card_for=_card_for,
        run_generation=run_generation,
        read_standings=_read_standings_factory(read_standings_calls if read_standings_calls is not None else []),
        derive_findings=_derive_findings,
        select_elites=_select_elites,
        ledger_entries_for=_ledger_entries_for,
        evaluate_promotions=_evaluate_promotions,
        trending_symbols=_trending_symbols,
        open_ledger=_open_ledger(ledger if ledger is not None else _FakeLedger()),
    )


# ---------------------------------------------------------------------------
# Scenario-specific `run_generation` fakes
# ---------------------------------------------------------------------------


def _succeeding_run_generation(calls: list[dict[str, Any]]) -> Any:
    def run_generation(*, round_id, cards, windows, settings, cancel, log, output_root, max_workers=1):
        _assert_plan_exists(settings, round_id)
        calls.append({"round_id": round_id, "output_root": output_root})
        return _fake_execution_report(round_id=round_id, windows=windows, cards=cards)

    return run_generation


def _raising_once_run_generation(calls: list[dict[str, Any]]) -> Any:
    """Raises a plain `RuntimeError` -- not `JobAlreadyRunning` -- on generation 1 only."""

    def run_generation(*, round_id, cards, windows, settings, cancel, log, output_root, max_workers=1):
        _assert_plan_exists(settings, round_id)
        generation = _generation_from_round_id(round_id)
        calls.append({"round_id": round_id, "generation": generation})
        if generation == 1:
            raise RuntimeError("synthetic failure in generation 1")
        return _fake_execution_report(round_id=round_id, windows=windows, cards=cards)

    return run_generation


def _busy_once_run_generation(calls: list[dict[str, Any]]) -> Any:
    """Raises `JobAlreadyRunning` on a generation's first attempt, then succeeds on its retry."""
    attempts: dict[int, int] = {}

    def run_generation(*, round_id, cards, windows, settings, cancel, log, output_root, max_workers=1):
        _assert_plan_exists(settings, round_id)
        generation = _generation_from_round_id(round_id)
        attempts[generation] = attempts.get(generation, 0) + 1
        calls.append({"round_id": round_id, "generation": generation, "attempt": attempts[generation]})
        if attempts[generation] == 1:
            raise JobAlreadyRunning("manual-job-123")
        return _fake_execution_report(round_id=round_id, windows=windows, cards=cards)

    return run_generation


def _sequenced_status_run_generation(
    calls: list[dict[str, Any]],
    statuses: dict[int, str],
    *,
    error_text: str = "synthetic read-only filesystem error",
) -> Any:
    """A `run_generation` fake whose report `status` for generation `N` is `statuses.get(N,
    "succeeded")` -- lets a test script an exact sequence of failed/succeeded/cancelled generations to
    drive `_run`'s consecutive-failure circuit breaker without needing a real collaborator to actually
    fail. Every generation this reports as `"failed"` carries the *same* `error_text`, mirroring the
    real 1,644-failure incident's identical repeated error across every failure.
    """

    def run_generation(*, round_id, cards, windows, settings, cancel, log, output_root, max_workers=1):
        _assert_plan_exists(settings, round_id)
        generation = _generation_from_round_id(round_id)
        calls.append({"round_id": round_id, "generation": generation})
        status = statuses.get(generation, "succeeded")
        report = _fake_execution_report(round_id=round_id, windows=windows, cards=cards, status=status)
        if status == "failed":
            report.errors = (error_text,)
        return report

    return run_generation


def _blocking_run_generation(calls: list[dict[str, Any]], captured: dict[str, Any]) -> Any:
    """Blocks until `cancel` is set (or a 5s safety deadline), then reports `cancelled`/`succeeded`
    accordingly. `captured["cancel_event"]` lets a test assert the exact object it later calls
    `stop_loop()` against was the one this fake actually received."""

    def run_generation(*, round_id, cards, windows, settings, cancel, log, output_root, max_workers=1):
        _assert_plan_exists(settings, round_id)
        captured["cancel_event"] = cancel
        calls.append({"round_id": round_id})
        deadline = time.monotonic() + 5.0
        while not cancel.is_set() and time.monotonic() < deadline:
            time.sleep(0.005)
        status = "cancelled" if cancel.is_set() else "succeeded"
        return _fake_execution_report(round_id=round_id, windows=windows, cards=cards, status=status)

    return run_generation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Every path this loop can reach redirected under `tmp_path` -- nothing here ever touches the
    real repository's `data/`."""
    return Settings(data_dir=tmp_path / "data", rounds_dir=tmp_path / "data" / "rounds")


@pytest.fixture(autouse=True)
def _reset_loop_after_every_test() -> None:
    """Belt and braces, matching `tests/test_competition_jobs.py`'s identical fixture for
    `app.tournament.jobs`: whatever a test leaves behind (a running daemon thread against a fake that
    blocks on `cancel`) must not leak into the next test's assertions."""
    yield
    loop_module.reset()


def _poll_until(
    fetch: Any,
    predicate: Any,
    *,
    timeout: float = 5.0,
    interval: float = 0.01,
) -> Any:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fetch()
        if predicate(last):
            return last
        time.sleep(interval)
    pytest.fail(f"timed out after {timeout}s waiting for condition; last observed value: {last!r}")


def _default_config(**overrides: Any) -> LoopConfig:
    base = {
        "purposes": (Purpose.TRADING,),
        "population": 2,
        "elite_count": 1,
        "windows": ("w1", "w2"),
        "holdout_windows": (),
        "max_generations": 2,
        "cooldown_seconds": 0.0,
        "use_news": False,
    }
    base.update(overrides)
    return LoopConfig(**base)


# ---------------------------------------------------------------------------
# (a) Two-generation run: two outcomes, elites carried forward within a lane
# ---------------------------------------------------------------------------
#
# With `_default_config`'s single purpose, `_lanes_for` yields exactly two lanes -- (TRADING,
# "rules") and (TRADING, "allocation") -- and generation `N` works `lanes[(N - 1) % 2]`. Generation 1
# and generation 3 therefore share a lane (generation 3 is that lane's *second* appearance);
# generation 2 is a different lane's *first* appearance and must start with no elites of its own,
# never generation 1's. Three generations, not two, is the smallest run that can show a lane's elites
# actually carrying forward across its own recurrence.


class TestTwoGenerationRun:
    def test_a_lanes_second_appearance_receives_its_own_first_appearances_elites(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        run_calls: list[dict[str, Any]] = []
        propose_calls: list[dict[str, Any]] = []
        collaborators = _build_collaborators(_succeeding_run_generation(run_calls), propose_calls=propose_calls)
        config = _default_config(max_generations=3)

        status = loop_module.start_loop(
            config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
        )
        assert status.state == "running"

        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))
        assert final is not None
        assert final.state == "stopped"
        assert final.error is None
        assert final.completed_generations == 3
        assert len(final.history) == 3
        # newest first
        assert [outcome.generation for outcome in final.history] == [3, 2, 1]
        assert all(outcome.status == "succeeded" for outcome in final.history)

        assert len(propose_calls) == 3
        assert propose_calls[0]["shape"] == "rules"
        assert propose_calls[0]["elites"] == ()

        assert propose_calls[1]["shape"] == "allocation"
        assert propose_calls[1]["elites"] == (), "a lane's first appearance must start with no elites"

        assert propose_calls[2]["shape"] == "rules"
        gen3_elite_ids = {genome.genome_id for genome in propose_calls[2]["elites"]}
        assert gen3_elite_ids, "generation 3 revisits generation 1's lane and should receive its elites"
        gen1_outcome = next(outcome for outcome in final.history if outcome.generation == 1)
        assert gen3_elite_ids.issubset(set(gen1_outcome.genome_ids))

        assert run_calls[0]["output_root"] == tmp_path / "rounds"


# ---------------------------------------------------------------------------
# (a2) Elites never cross lanes: each lane's second appearance receives only its own first
# appearance's elites, never another lane's.
# ---------------------------------------------------------------------------


class TestElitesDoNotCrossLanes:
    def test_each_lanes_elites_come_only_from_its_own_earlier_appearance(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        run_calls: list[dict[str, Any]] = []
        propose_calls: list[dict[str, Any]] = []
        collaborators = _build_collaborators(_succeeding_run_generation(run_calls), propose_calls=propose_calls)
        # Four generations over the two-lane, single-purpose config: gen1=(rules, occ0),
        # gen2=(allocation, occ0), gen3=(rules, occ1), gen4=(allocation, occ1).
        config = _default_config(max_generations=4)

        loop_module.start_loop(
            config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
        )
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final is not None
        assert final.state == "stopped"
        assert len(propose_calls) == 4
        assert [call["shape"] for call in propose_calls] == ["rules", "allocation", "rules", "allocation"]

        by_generation = {outcome.generation: outcome for outcome in final.history}
        gen1_ids = set(by_generation[1].genome_ids)
        gen2_ids = set(by_generation[2].genome_ids)

        gen3_elite_ids = {genome.genome_id for genome in propose_calls[2]["elites"]}
        gen4_elite_ids = {genome.genome_id for genome in propose_calls[3]["elites"]}

        assert gen3_elite_ids, "generation 3 (rules, 2nd appearance) should receive generation 1's elites"
        assert gen3_elite_ids.issubset(gen1_ids)
        assert not (gen3_elite_ids & gen2_ids), "generation 3's elites must not include an allocation-lane genome"

        assert gen4_elite_ids, "generation 4 (allocation, 2nd appearance) should receive generation 2's elites"
        assert gen4_elite_ids.issubset(gen2_ids)
        assert not (gen4_elite_ids & gen1_ids), "generation 4's elites must not include a rules-lane genome"


# ---------------------------------------------------------------------------
# (b) Stop mid-loop: running -> stopping -> stopped, cancel event reaches run_generation
# ---------------------------------------------------------------------------


class TestStopMidLoop:
    def test_stop_transitions_through_stopping_and_cancel_reaches_run_generation(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        run_calls: list[dict[str, Any]] = []
        captured: dict[str, Any] = {}
        collaborators = _build_collaborators(_blocking_run_generation(run_calls, captured))
        config = _default_config(population=2, windows=("w1",), max_generations=None)

        status = loop_module.start_loop(
            config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
        )
        assert status.state == "running"

        _poll_until(lambda: captured.get("cancel_event"), lambda event: event is not None)

        stopping = loop_module.stop_loop()
        assert stopping.state == "stopping"

        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))
        assert final is not None
        assert final.state == "stopped"
        assert captured["cancel_event"].is_set()
        assert len(final.history) == 1
        assert final.history[0].status == "cancelled"


# ---------------------------------------------------------------------------
# (c) A collaborator raising in generation 1 records a failed outcome; generation 2 still runs
# ---------------------------------------------------------------------------


class TestGenerationFailureIsIsolated:
    def test_failing_generation_records_failed_outcome_and_loop_continues(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        run_calls: list[dict[str, Any]] = []
        collaborators = _build_collaborators(_raising_once_run_generation(run_calls))
        config = _default_config(max_generations=2)

        loop_module.start_loop(config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds")
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final is not None
        assert final.state == "stopped", "the supervisor itself must survive a single generation's failure"
        assert final.error is None
        assert final.completed_generations == 2
        assert len(final.history) == 2

        assert final.history[1].generation == 1
        assert final.history[1].status == "failed"
        assert final.history[1].error is not None
        assert "synthetic failure" in final.history[1].error

        assert final.history[0].generation == 2
        assert final.history[0].status == "succeeded"


# ---------------------------------------------------------------------------
# (d) JobAlreadyRunning causes a retry rather than a failure
# ---------------------------------------------------------------------------


class TestEngineBusyRetries:
    def test_job_already_running_causes_retry_not_failure(self, settings: Settings, tmp_path: Path) -> None:
        run_calls: list[dict[str, Any]] = []
        collaborators = _build_collaborators(_busy_once_run_generation(run_calls))
        config = _default_config(max_generations=1)

        loop_module.start_loop(config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds")
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final is not None
        assert final.state == "stopped"
        assert final.completed_generations == 1
        assert len(final.history) == 1
        assert final.history[0].status == "succeeded"
        assert len(run_calls) == 2, "the first call should have raised JobAlreadyRunning, the second succeeded"
        assert any("engine busy" in line for line in final.log)


# ---------------------------------------------------------------------------
# (e) start_loop twice raises LoopAlreadyRunning
# ---------------------------------------------------------------------------


class TestStartTwiceRejected:
    def test_start_loop_twice_raises_loop_already_running(self, settings: Settings, tmp_path: Path) -> None:
        captured: dict[str, Any] = {}
        collaborators = _build_collaborators(_blocking_run_generation([], captured))
        config = _default_config(windows=("w1",), max_generations=None)

        first = loop_module.start_loop(
            config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
        )
        assert first.state == "running"

        with pytest.raises(LoopAlreadyRunning) as excinfo:
            loop_module.start_loop(
                config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
            )
        assert excinfo.value.loop_id == first.loop_id

        loop_module.stop_loop()
        _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))


# ---------------------------------------------------------------------------
# (f) PLAN.md exists before run_generation is called
# ---------------------------------------------------------------------------


class TestPlanFileWrittenBeforeRunGeneration:
    def test_plan_md_exists_and_is_readable_before_run_generation_executes(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        checked: dict[str, Any] = {}

        def run_generation(*, round_id, cards, windows, settings, cancel, log, output_root, max_workers=1):
            generation = _generation_from_round_id(round_id)
            plan_path = loop_root(settings) / f"gen{generation:04d}" / "PLAN.md"
            checked["plan_existed"] = plan_path.exists()
            checked["plan_text"] = plan_path.read_text(encoding="utf-8") if plan_path.exists() else ""
            return _fake_execution_report(round_id=round_id, windows=windows, cards=cards)

        collaborators = _build_collaborators(run_generation)
        config = _default_config(max_generations=1)

        loop_module.start_loop(config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds")
        _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert checked.get("plan_existed") is True
        assert "Round id" in checked["plan_text"]
        assert "Candidates" in checked["plan_text"]
        assert "trading" in checked["plan_text"]


# ---------------------------------------------------------------------------
# (g partial, HTTP is in tests/test_api_evolution.py) -- idle-state error paths
# ---------------------------------------------------------------------------


class TestIdleStateErrors:
    def test_get_status_returns_none_before_any_loop_started(self) -> None:
        assert loop_module.get_status() is None

    def test_stop_loop_raises_loop_not_running_when_idle(self) -> None:
        with pytest.raises(LoopNotRunning):
            loop_module.stop_loop()


# ---------------------------------------------------------------------------
# `read_standings` receives the loop's own rounds root -- the manager's cash-constraint-adjacent
# correction: auto-generated rounds live under `loop_rounds_root`, not `settings.rounds_dir`, and
# `read_standings` has to be told that explicitly.
# ---------------------------------------------------------------------------


class TestReadStandingsReceivesLoopsOwnRoundsRoot:
    def test_rounds_root_kwarg_is_the_loops_own_output_root_when_the_collaborator_accepts_it(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        read_standings_calls: list[dict[str, Any]] = []
        run_calls: list[dict[str, Any]] = []
        output_root = tmp_path / "rounds"
        collaborators = _build_collaborators(
            _succeeding_run_generation(run_calls), read_standings_calls=read_standings_calls
        )
        config = _default_config(max_generations=1)

        loop_module.start_loop(config, settings=settings, collaborators=collaborators, output_root=output_root)
        _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert len(read_standings_calls) == 1
        assert read_standings_calls[0]["rounds_root"] == output_root

    def test_loop_still_works_when_the_collaborator_lacks_a_rounds_root_parameter(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        def read_standings(
            *, round_id, purpose, genomes, config, settings, selection_windows, holdout_windows
        ) -> tuple[Standing, ...]:
            # `genomes` is `dict[genome_id, Genome]` -- no `rounds_root` parameter here at all, which
            # is exactly the case this test exercises.
            return tuple(
                _make_standing(genome, rank=i + 1, median_excess=Decimal("1"))
                for i, genome in enumerate(genomes.values())
            )

        run_calls: list[dict[str, Any]] = []
        collaborators = Collaborators(
            propose=_propose_factory([]),
            write_cards=_write_cards,
            card_for=_card_for,
            run_generation=_succeeding_run_generation(run_calls),
            read_standings=read_standings,
            derive_findings=_derive_findings,
            select_elites=_select_elites,
            ledger_entries_for=_ledger_entries_for,
            evaluate_promotions=_evaluate_promotions,
            trending_symbols=_trending_symbols,
            open_ledger=_open_ledger(_FakeLedger()),
        )
        config = _default_config(max_generations=1)

        loop_module.start_loop(config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds")
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final is not None
        assert final.state == "stopped"
        assert final.history[0].status == "succeeded"


# ---------------------------------------------------------------------------
# Minted round ids stay unique across fast generations, and match the shared pattern
# ---------------------------------------------------------------------------


class TestMintedRoundIds:
    def test_round_ids_are_unique_and_well_formed_across_generations(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        run_calls: list[dict[str, Any]] = []
        collaborators = _build_collaborators(_succeeding_run_generation(run_calls))
        config = _default_config(max_generations=3, population=2)

        loop_module.start_loop(config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds")
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final is not None
        round_ids = [outcome.round_id for outcome in final.history]
        assert len(round_ids) == len(set(round_ids)), f"round ids collided: {round_ids}"
        for round_id in round_ids:
            assert re.match(r"^[a-z0-9][a-z0-9-]{0,63}$", round_id)


# ---------------------------------------------------------------------------
# DEFECT 1 fix: selection and holdout windows run into two SEPARATE round directories, so
# `app.tournament.results.build_leaderboard` (which has no window filter of its own) never ranks a
# holdout window into the selection median. A real run before this fix measured `windows_run=6` over
# a 5-window selection set -- the holdout window counted right along with the rest.
# ---------------------------------------------------------------------------


def _holdout_recording_run_generation(calls: list[dict[str, Any]]) -> Any:
    """Records every `run_generation` call's `round_id` and `windows`, and asserts `PLAN.md` exists
    before either the selection or the holdout call -- `_assert_plan_exists` only understands a
    `-gNNNN`-suffixed id, so a holdout id (`-gNNNN-holdout`) is stripped back to its selection id
    first."""

    def run_generation(*, round_id, cards, windows, settings, cancel, log, output_root, max_workers=1):
        base_round_id = round_id[: -len("-holdout")] if round_id.endswith("-holdout") else round_id
        _assert_plan_exists(settings, base_round_id)
        calls.append({"round_id": round_id, "windows": tuple(windows)})
        return _fake_execution_report(round_id=round_id, windows=windows, cards=cards)

    return run_generation


class TestHoldoutRunsIntoASeparateRoundDirectory:
    def test_selection_and_holdout_use_two_different_round_ids_and_holdout_id_is_derived(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        run_calls: list[dict[str, Any]] = []
        collaborators = _build_collaborators(_holdout_recording_run_generation(run_calls))
        config = _default_config(
            windows=("w1", "w2", "w3", "w4", "w5"),
            holdout_windows=("w6",),
            max_generations=1,
        )

        loop_module.start_loop(config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds")
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final is not None
        assert final.state == "stopped"
        assert final.history[0].status == "succeeded"
        assert len(run_calls) == 2, "selection and holdout must each be their own run_generation call"

        selection_call, holdout_call = run_calls[0], run_calls[1]
        assert selection_call["windows"] == ("w1", "w2", "w3", "w4", "w5")
        assert holdout_call["windows"] == ("w6",)
        assert holdout_call["round_id"] != selection_call["round_id"]
        assert holdout_call["round_id"] == f"{selection_call['round_id']}-holdout"
        assert re.match(r"^[a-z0-9][a-z0-9-]{0,63}$", holdout_call["round_id"])

    def test_generation_outcome_windows_holds_the_selection_set_only_never_the_union(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        run_calls: list[dict[str, Any]] = []
        collaborators = _build_collaborators(_holdout_recording_run_generation(run_calls))
        config = _default_config(
            windows=("w1", "w2", "w3", "w4", "w5"),
            holdout_windows=("w6",),
            max_generations=1,
        )

        loop_module.start_loop(config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds")
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final is not None
        outcome = final.history[0]
        assert set(outcome.windows) == {"w1", "w2", "w3", "w4", "w5"}
        assert "w6" not in outcome.windows, "GenerationOutcome.windows must never include the holdout set"
        assert outcome.holdout_windows == ("w6",)

    def test_no_holdout_run_at_all_when_holdout_windows_is_empty(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        run_calls: list[dict[str, Any]] = []
        collaborators = _build_collaborators(_holdout_recording_run_generation(run_calls))
        config = _default_config(windows=("w1", "w2"), holdout_windows=(), max_generations=1)

        loop_module.start_loop(config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds")
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final is not None
        assert final.state == "stopped"
        assert len(run_calls) == 1, "only the selection run_generation call should happen"
        assert not run_calls[0]["round_id"].endswith("-holdout")

    def test_a_failing_holdout_run_leaves_the_generation_succeeded_with_holdout_medians_none(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        run_calls: list[dict[str, Any]] = []
        read_standings_calls: list[dict[str, Any]] = []

        def run_generation(*, round_id, cards, windows, settings, cancel, log, output_root, max_workers=1):
            base_round_id = round_id[: -len("-holdout")] if round_id.endswith("-holdout") else round_id
            _assert_plan_exists(settings, base_round_id)
            run_calls.append({"round_id": round_id})
            if round_id.endswith("-holdout"):
                raise RuntimeError("synthetic holdout failure")
            return _fake_execution_report(round_id=round_id, windows=windows, cards=cards)

        collaborators = _build_collaborators(run_generation, read_standings_calls=read_standings_calls)
        config = _default_config(
            windows=("w1", "w2", "w3", "w4", "w5"),
            holdout_windows=("w6",),
            max_generations=1,
        )

        loop_module.start_loop(config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds")
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final is not None
        assert final.state == "stopped"
        assert len(final.history) == 1
        assert final.history[0].status == "succeeded", "a failing holdout run must not fail the generation"
        assert any("holdout run failed" in line for line in final.log)

        assert len(run_calls) == 2, "the selection call and the (failing) holdout call both happened"
        assert len(read_standings_calls) == 1
        assert read_standings_calls[0]["holdout_round_id"] is None, (
            "a failed holdout run must not be handed to read_standings -- the resulting "
            "holdout medians must come back None"
        )
        assert all(standing.holdout_median_excess is None for standing in final.history[0].standings)


# ---------------------------------------------------------------------------
# Selection windows rotate per generation by default -- required so
# `evaluate_promotions`'s two-consecutive-generations-on-differing-window-sets rule
# (`PROTOCOL.md` s6a) can ever be satisfied. A loop config with an unrotated, fixed set could search
# forever and promote nothing.
# ---------------------------------------------------------------------------


class TestSelectionWindowsRotatePerGeneration:
    def test_same_lanes_consecutive_appearances_get_different_window_sets_each_at_least_five(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        run_calls: list[dict[str, Any]] = []
        collaborators = _build_collaborators(_succeeding_run_generation(run_calls))
        # `windows` deliberately left empty (not the `_default_config` helper's fixed ("w1", "w2"))
        # so the default rotation path -- MAIN_WINDOWS minus holdout_windows, one window dropped per
        # appearance -- is what actually runs. `holdout_windows` is left at its own default
        # (2 windows), so the rotation pool is MAIN_WINDOWS' 8 windows minus those 2 = 6, and each
        # appearance's selection set is 5 of those 6 -- exactly at MIN_ELIGIBLE_MAIN_WINDOWS.
        #
        # A single purpose means exactly two lanes, so generation 3 is the SAME lane's second
        # appearance as generation 1 (generation 2 is the other lane's first appearance, and is
        # deliberately not compared here -- two *different* lanes sharing a `drop_index` by
        # coincidence would say nothing about whether rotation is broken; only a lane's own
        # consecutive appearances are what `evaluate_promotions`'s two-distinct-window-sets rule
        # actually needs to differ).
        config = LoopConfig(
            purposes=(Purpose.TRADING,),
            population=2,
            elite_count=1,
            max_generations=3,
            cooldown_seconds=0.0,
            use_news=False,
        )

        loop_module.start_loop(
            config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
        )
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final is not None
        assert len(final.history) == 3
        holdout = set(config.holdout_windows)
        by_generation = {outcome.generation: outcome for outcome in final.history}
        gen1_selection = set(by_generation[1].windows) - holdout
        gen3_selection = set(by_generation[3].windows) - holdout

        assert len(gen1_selection) >= 5
        assert len(gen3_selection) >= 5
        assert gen1_selection != gen3_selection, (
            "the same lane's two consecutive appearances must not reuse an identical window set"
        )
        assert gen1_selection & gen3_selection, "consecutive rotated sets should still overlap, not be disjoint"

    def test_explicit_windows_are_honoured_exactly_and_never_rotated(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        run_calls: list[dict[str, Any]] = []
        collaborators = _build_collaborators(_succeeding_run_generation(run_calls))
        config = _default_config(windows=("w1", "w2", "w3", "w4", "w5"), max_generations=2)

        loop_module.start_loop(
            config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
        )
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final is not None
        gen1_selection = set(final.history[1].windows) - set(config.holdout_windows)
        gen2_selection = set(final.history[0].windows) - set(config.holdout_windows)
        assert gen1_selection == set(config.windows)
        assert gen2_selection == set(config.windows)


# ---------------------------------------------------------------------------
# `ledger_entries_for` must receive the same `rounds_root` as `read_standings` -- both read run files
# out of the loop's own disposable rounds tree (`loop_rounds_root`), never `settings.rounds_dir`. A
# fake collaborator set is the only thing that can catch this: the real `feedback.ledger_entries_for`
# defaults `rounds_root` to `settings.rounds_dir` when the argument is omitted, so a dropped kwarg
# does not raise -- it just silently reads the wrong directory, finds no run files, and reports
# closed_trades=0 for every candidate forever. See the manager's note: this is the single most
# important mechanism in this feature, and it failing silently is the worst available outcome.
# ---------------------------------------------------------------------------


class TestLedgerEntriesForReceivesTheSameRoundsRootAsReadStandings:
    def test_rounds_root_matches_between_the_two_calls(self, settings: Settings, tmp_path: Path) -> None:
        recorded: dict[str, Any] = {}

        def read_standings(
            *, round_id, purpose, genomes, config, settings, selection_windows, holdout_windows, rounds_root=None
        ) -> tuple[Standing, ...]:
            recorded["read_standings_rounds_root"] = rounds_root
            return tuple(
                _make_standing(genome, rank=i + 1, median_excess=Decimal("1"))
                for i, genome in enumerate(genomes.values())
            )

        def ledger_entries_for(
            standings, *, round_id, purpose, generation, selection_windows, settings, rounds_root=None
        ) -> tuple[Any, ...]:
            recorded["ledger_entries_for_rounds_root"] = rounds_root
            return tuple(SimpleNamespace(genome_id=standing.genome_id) for standing in standings)

        run_calls: list[dict[str, Any]] = []
        output_root = tmp_path / "rounds"
        collaborators = Collaborators(
            propose=_propose_factory([]),
            write_cards=_write_cards,
            card_for=_card_for,
            run_generation=_succeeding_run_generation(run_calls),
            read_standings=read_standings,
            derive_findings=_derive_findings,
            select_elites=_select_elites,
            ledger_entries_for=ledger_entries_for,
            evaluate_promotions=_evaluate_promotions,
            trending_symbols=_trending_symbols,
            open_ledger=_open_ledger(_FakeLedger()),
        )
        config = _default_config(max_generations=1)

        loop_module.start_loop(config, settings=settings, collaborators=collaborators, output_root=output_root)
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final is not None
        assert final.state == "stopped"
        assert recorded.get("read_standings_rounds_root") == output_root
        assert recorded.get("ledger_entries_for_rounds_root") == output_root
        assert recorded["read_standings_rounds_root"] == recorded["ledger_entries_for_rounds_root"]


# ---------------------------------------------------------------------------
# `field_window_medians` (optional): when a collaborator set provides it, its result is threaded
# through to `derive_findings` as `window_medians` -- the per-window breakdown the `kind="regime"`
# finding needs. When absent (`None`, the `Collaborators` field's own default), the loop must not
# call it and `derive_findings` must still run without a `window_medians` kwarg at all.
# ---------------------------------------------------------------------------


class TestFieldWindowMediansEnrichment:
    def test_window_medians_from_field_window_medians_reaches_derive_findings(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        sentinel_medians = {"w1": Decimal("1.5"), "w2": Decimal("-0.5")}
        field_window_medians_calls: list[dict[str, Any]] = []
        derive_findings_calls: list[dict[str, Any]] = []

        def field_window_medians(
            round_id: str, *, purpose, genomes, windows, settings, rounds_root=None
        ) -> dict[str, Decimal]:
            field_window_medians_calls.append(
                {"round_id": round_id, "windows": windows, "rounds_root": rounds_root}
            )
            return sentinel_medians

        def derive_findings(
            standings, *, config, purpose, selection_windows, holdout_windows, genomes, window_medians=None
        ) -> tuple[Finding, ...]:
            derive_findings_calls.append({"window_medians": window_medians})
            return ()

        run_calls: list[dict[str, Any]] = []
        output_root = tmp_path / "rounds"
        collaborators = Collaborators(
            propose=_propose_factory([]),
            write_cards=_write_cards,
            card_for=_card_for,
            run_generation=_succeeding_run_generation(run_calls),
            read_standings=_read_standings_factory([]),
            derive_findings=derive_findings,
            select_elites=_select_elites,
            ledger_entries_for=_ledger_entries_for,
            evaluate_promotions=_evaluate_promotions,
            trending_symbols=_trending_symbols,
            open_ledger=_open_ledger(_FakeLedger()),
            field_window_medians=field_window_medians,
        )
        config = _default_config(max_generations=1)

        loop_module.start_loop(config, settings=settings, collaborators=collaborators, output_root=output_root)
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final is not None
        assert final.state == "stopped"
        assert len(field_window_medians_calls) == 1
        assert field_window_medians_calls[0]["rounds_root"] == output_root
        assert len(derive_findings_calls) == 1
        assert derive_findings_calls[0]["window_medians"] == sentinel_medians

    def test_absent_field_window_medians_is_never_called_and_derive_findings_still_runs(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        derive_findings_calls: list[dict[str, Any]] = []

        def derive_findings(
            standings, *, config, purpose, selection_windows, holdout_windows, genomes
        ) -> tuple[Finding, ...]:
            # Deliberately no `window_medians` parameter at all -- an older collaborator set must
            # still work when `Collaborators.field_window_medians` is left at its `None` default.
            derive_findings_calls.append({"called": True})
            return ()

        run_calls: list[dict[str, Any]] = []
        collaborators = Collaborators(
            propose=_propose_factory([]),
            write_cards=_write_cards,
            card_for=_card_for,
            run_generation=_succeeding_run_generation(run_calls),
            read_standings=_read_standings_factory([]),
            derive_findings=derive_findings,
            select_elites=_select_elites,
            ledger_entries_for=_ledger_entries_for,
            evaluate_promotions=_evaluate_promotions,
            trending_symbols=_trending_symbols,
            open_ledger=_open_ledger(_FakeLedger()),
            # field_window_medians omitted -- defaults to None
        )
        config = _default_config(max_generations=1)

        loop_module.start_loop(config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds")
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final is not None
        assert final.state == "stopped"
        assert len(derive_findings_calls) == 1


# ---------------------------------------------------------------------------
# Agent designer fallback wiring -- Collaborators.design_generation and _propose_genomes
#
# app.agents.designer is another worker's concurrently-written module and is never imported here;
# every scenario below wires a small fake directly into Collaborators.design_generation instead,
# exactly like every other collaborator in this file. The one behaviour under test throughout is the
# module docstring's central claim: an agent failure of any kind degrades to `propose` for that one
# generation and never fails or stalls the loop.
# ---------------------------------------------------------------------------


def _full_collaborators(
    *,
    design_generation: Any = None,
    propose_calls: list[dict[str, Any]] | None = None,
    run_calls: list[dict[str, Any]] | None = None,
) -> Collaborators:
    """Every collaborator wired to a fast, deterministic fake, plus an optional design_generation --
    the smallest full set that can actually run a generation end to end."""
    return Collaborators(
        propose=_propose_factory(propose_calls if propose_calls is not None else []),
        write_cards=_write_cards,
        card_for=_card_for,
        run_generation=_succeeding_run_generation(run_calls if run_calls is not None else []),
        read_standings=_read_standings_factory([]),
        derive_findings=_derive_findings,
        select_elites=_select_elites,
        ledger_entries_for=_ledger_entries_for,
        evaluate_promotions=_evaluate_promotions,
        trending_symbols=_trending_symbols,
        open_ledger=_open_ledger(_FakeLedger()),
        design_generation=design_generation,
    )


def _run_one_generation(
    settings: Settings, tmp_path: Path, collaborators: Collaborators, **config_overrides: Any
) -> Any:
    config = _default_config(max_generations=1, use_agent=True, **config_overrides)
    loop_module.start_loop(
        config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
    )
    return _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))


class TestAgentDesignerFallback:
    """(e) Three separate failure modes, each proven to fall back to the deterministic proposer and
    still complete the generation successfully -- not merely "the loop didn't crash", but "the
    generation the loop ran is the deterministic one", checked via propose_calls."""

    def test_falls_back_to_deterministic_proposer_on_agent_unavailable(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        design_calls: list[dict[str, Any]] = []

        def design_generation(**kwargs: Any) -> Any:
            design_calls.append(kwargs)
            raise AgentUnavailable("no credentials found")

        propose_calls: list[dict[str, Any]] = []
        collaborators = _full_collaborators(design_generation=design_generation, propose_calls=propose_calls)

        final = _run_one_generation(settings, tmp_path, collaborators)

        assert final.state == "stopped"
        assert final.error is None
        assert final.completed_generations == 1
        assert final.history[0].status == "succeeded"
        assert len(design_calls) == 1, "the agent path must actually have been attempted"
        assert len(propose_calls) == 1, "a failed agent call must fall back to the deterministic proposer"
        assert any("agent unavailable" in line for line in final.log)

    def test_falls_back_to_deterministic_proposer_on_budget_exhausted(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        design_calls: list[dict[str, Any]] = []

        def design_generation(**kwargs: Any) -> Any:
            design_calls.append(kwargs)
            raise BudgetExhausted(Decimal("10.00"), Decimal("10.00"))

        propose_calls: list[dict[str, Any]] = []
        collaborators = _full_collaborators(design_generation=design_generation, propose_calls=propose_calls)

        final = _run_one_generation(settings, tmp_path, collaborators, agent_budget_usd=Decimal("10.00"))

        assert final.state == "stopped"
        assert final.error is None
        assert final.completed_generations == 1
        assert final.history[0].status == "succeeded"
        assert len(design_calls) == 1
        assert len(propose_calls) == 1
        assert any("budget exhausted" in line for line in final.log)

    def test_falls_back_to_deterministic_proposer_on_arbitrary_exception(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        design_calls: list[dict[str, Any]] = []

        def design_generation(**kwargs: Any) -> Any:
            design_calls.append(kwargs)
            raise RuntimeError("a bug in a concurrently-written module")

        propose_calls: list[dict[str, Any]] = []
        collaborators = _full_collaborators(design_generation=design_generation, propose_calls=propose_calls)

        final = _run_one_generation(settings, tmp_path, collaborators)

        assert final.state == "stopped"
        assert final.error is None
        assert final.completed_generations == 1
        assert final.history[0].status == "succeeded"
        assert len(design_calls) == 1
        assert len(propose_calls) == 1
        assert any("agent designer failed" in line for line in final.log)
        assert any("RuntimeError" in line for line in final.log)

    def test_agent_disabled_falls_back_to_deterministic_proposer(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        """Not one of the three exceptions the DoD names explicitly, but the fourth documented
        failure mode (AgentDisabled) gets exactly the same treatment -- proven here for completeness
        since it costs nothing extra to check."""

        def design_generation(**kwargs: Any) -> Any:
            raise AgentDisabled("agent turned off mid-run")

        propose_calls: list[dict[str, Any]] = []
        collaborators = _full_collaborators(design_generation=design_generation, propose_calls=propose_calls)

        final = _run_one_generation(settings, tmp_path, collaborators)

        assert final.state == "stopped"
        assert final.history[0].status == "succeeded"
        assert len(propose_calls) == 1


class TestUseAgentFalseNeverCallsDesigner:
    """(f) LoopConfig.use_agent=False (the default) must never call design_generation, even when a
    real one is wired into Collaborators -- turning the agent off has to be a hard gate at the call
    site, not merely "the agent usually declines"."""

    def test_use_agent_false_never_calls_the_wired_designer(self, settings: Settings, tmp_path: Path) -> None:
        design_calls: list[dict[str, Any]] = []

        def design_generation(**kwargs: Any) -> Any:
            design_calls.append(kwargs)
            raise AssertionError("design_generation must never be called when use_agent=False")

        propose_calls: list[dict[str, Any]] = []
        collaborators = _full_collaborators(design_generation=design_generation, propose_calls=propose_calls)

        config = _default_config(max_generations=1, use_agent=False)
        loop_module.start_loop(
            config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
        )
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final.state == "stopped"
        assert final.history[0].status == "succeeded"
        assert design_calls == []
        assert len(propose_calls) == 1


class TestAgentShortSlateToppedUp:
    """(g) When the agent proposes fewer candidates than LoopConfig.population, the deterministic
    proposer fills the remainder so the generation still runs a full population."""

    def test_short_agent_slate_is_topped_up_to_population(self, settings: Settings, tmp_path: Path) -> None:
        def design_generation(
            *,
            generation: int,
            purpose: Purpose,
            shape: str,
            config: LoopConfig,
            settings: Settings,
            budget: AgentBudget,
            findings: tuple[Any, ...] = (),
            standings: tuple[Any, ...] = (),
            previous_cards: tuple[Any, ...] = (),
            focus_symbols: tuple[str, ...] = (),
            avoid_symbols: tuple[str, ...] = (),
        ) -> Any:
            # One genome, deliberately fewer than _default_config's population=2.
            genome = _make_genome(generation=generation, index=99, purpose=purpose, shape=shape)
            new_budget = AgentBudget(cap_usd=budget.cap_usd, spent_usd=Decimal("0.25"), calls=budget.calls + 1)
            return (genome,), None, new_budget

        propose_calls: list[dict[str, Any]] = []
        collaborators = _full_collaborators(design_generation=design_generation, propose_calls=propose_calls)

        final = _run_one_generation(settings, tmp_path, collaborators)

        assert final.state == "stopped"
        assert final.history[0].status == "succeeded"
        # The deterministic proposer was invoked to fill the shortfall...
        assert len(propose_calls) == 1
        # ...and the generation actually ran a full population, not just the agent's one genome.
        assert len(final.history[0].genome_ids) == 2
        assert any("topped up to 2" in line for line in final.log)


class TestAgentBudgetTracking:
    """The running AgentBudget lives on the loop's own state and carries across generations, and an
    exhausted budget is logged once, not every generation."""

    def test_budget_persists_across_generations_and_exhaustion_logs_once(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        seen_budgets: list[Decimal] = []

        def design_generation(
            *,
            generation: int,
            purpose: Purpose,
            shape: str,
            config: LoopConfig,
            settings: Settings,
            budget: AgentBudget,
            findings: tuple[Any, ...] = (),
            standings: tuple[Any, ...] = (),
            previous_cards: tuple[Any, ...] = (),
            focus_symbols: tuple[str, ...] = (),
            avoid_symbols: tuple[str, ...] = (),
        ) -> Any:
            seen_budgets.append(budget.spent_usd)
            genomes = tuple(
                _make_genome(generation=generation, index=i, purpose=purpose, shape=shape)
                for i in range(config.population)
            )
            # Every call spends the full cap at once, so the very next call already sees it exhausted.
            new_budget = AgentBudget(cap_usd=budget.cap_usd, spent_usd=budget.cap_usd, calls=budget.calls + 1)
            return genomes, None, new_budget

        propose_calls: list[dict[str, Any]] = []
        collaborators = _full_collaborators(design_generation=design_generation, propose_calls=propose_calls)
        config = _default_config(max_generations=4, use_agent=True, agent_budget_usd=Decimal("5.00"))

        loop_module.start_loop(
            config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
        )
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final.state == "stopped"
        assert final.completed_generations == 4
        # Generation 1 sees a fresh budget (0 spent) and exhausts it; every generation after that
        # finds it already exhausted and never calls the agent again.
        assert seen_budgets == [Decimal("0")]
        exhausted_lines = [line for line in final.log if "agent budget exhausted" in line]
        assert len(exhausted_lines) == 1, f"expected exactly one exhaustion log line, got: {exhausted_lines}"
        # Every generation still ran a full population -- generation 1 from the agent, the rest from
        # the deterministic proposer once the budget was gone.
        assert all(len(outcome.genome_ids) == config.population for outcome in final.history)


# ---------------------------------------------------------------------------
# `max_workers` actually reaches the executor
# ---------------------------------------------------------------------------


class TestMaxWorkersReachesRunGeneration:
    """The regression guard for a config field that existed, was settable from the UI, and did nothing.

    `execute.run_generation` defaults `max_workers` to 1, so a supervisor that forgets to pass it
    produces a loop that runs every generation serially while the panel shows the user's chosen worker
    count. Nothing errors, nothing logs, and the only symptom is that the run is slower than it should
    be -- which is indistinguishable from the machine being busy. Measured on a real 30-run generation,
    the difference the missing keyword hides is 68.4s against 25.0s.

    Both call sites are checked. The holdout run is a second, separate `run_generation` call, and an
    early version of this wiring passed `max_workers` to the selection run only.
    """

    def test_both_the_selection_and_holdout_calls_receive_the_configured_max_workers(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        seen: list[dict[str, Any]] = []

        def run_generation(
            *, round_id, cards, windows, settings, cancel, log, output_root, max_workers=1
        ):
            seen.append({"round_id": round_id, "max_workers": max_workers})
            return _fake_execution_report(round_id=round_id, windows=windows, cards=cards)

        collaborators = _build_collaborators(run_generation)
        config = _default_config(
            max_generations=1,
            max_workers=5,
            holdout_windows=("covid",),
        )
        loop_module.start_loop(
            config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
        )
        _poll_until(lambda: loop_module.get_status(), lambda s: s.state == "stopped")

        assert len(seen) == 2, f"expected a selection and a holdout call, got {seen}"
        assert {call["max_workers"] for call in seen} == {5}, seen
        assert any(call["round_id"].endswith("-holdout") for call in seen), seen


# ---------------------------------------------------------------------------
# Consecutive-failure circuit breaker -- see `loop_module._MAX_CONSECUTIVE_FAILURES`'s own docstring
# for the production incident this exists to catch: a loop left running in Docker produced 1,673
# generations, 1,644 of them failing with the identical `OSError` writing a generated card to a
# read-only mount. The tests below script exact sequences of failed/succeeded/cancelled generations
# via `_sequenced_status_run_generation` to prove the breaker trips on an unbroken run of failures,
# resets on any success, and ignores cancellations, without needing a real collaborator to fail.
# ---------------------------------------------------------------------------


class TestConsecutiveFailureCircuitBreaker:
    def test_five_consecutive_failures_stop_the_loop_with_failed_state_and_named_cause(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        run_calls: list[dict[str, Any]] = []
        statuses = {1: "failed", 2: "failed", 3: "failed", 4: "failed", 5: "failed"}
        collaborators = _build_collaborators(
            _sequenced_status_run_generation(run_calls, statuses, error_text="disk full: read-only mount")
        )
        # `max_generations` set well above the breaker's own threshold so a passing test proves the
        # breaker stopped the loop -- not `max_generations` coincidentally doing it instead.
        config = _default_config(max_generations=20)

        loop_module.start_loop(
            config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
        )
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state == "failed")

        assert final.state == "failed"
        assert final.completed_generations == 5, "the breaker must stop before a 6th generation starts"
        assert len(run_calls) == 5
        assert final.error is not None
        assert "5" in final.error, f"error should name the streak length: {final.error!r}"
        assert "disk full: read-only mount" in final.error, (
            f"error should name the repeated cause: {final.error!r}"
        )
        assert all(outcome.status == "failed" for outcome in final.history)
        assert any("loop" in line and "FAILED" in line for line in final.log)

    def test_four_failures_then_a_success_resets_the_counter_and_the_loop_keeps_running(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        # 4 failures, a success (must reset the streak), then one more failure. If the breaker counted
        # *total* failures instead of a *consecutive* streak, generation 6's failure would be this
        # run's 5th failed generation overall and would incorrectly trip it -- it must not, because
        # only one failure has happened since the generation-5 success reset the count.
        run_calls: list[dict[str, Any]] = []
        statuses = {1: "failed", 2: "failed", 3: "failed", 4: "failed", 6: "failed"}
        collaborators = _build_collaborators(_sequenced_status_run_generation(run_calls, statuses))
        config = _default_config(max_generations=6)

        loop_module.start_loop(
            config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
        )
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final.state == "stopped", "a success between two short failure streaks must reset the breaker"
        assert final.error is None
        assert final.completed_generations == 6
        assert [outcome.status for outcome in reversed(final.history)] == [
            "failed",
            "failed",
            "failed",
            "failed",
            "succeeded",
            "failed",
        ]

    def test_cancelled_generation_does_not_count_toward_the_breaker(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        # 4 failures, a cancellation, then a 5th failure. A cancellation must neither reset the streak
        # (which would leave the loop running past generation 6) nor count as a failure of its own
        # (which would trip the breaker a generation early, at generation 5). The correct outcome is
        # that generation 6's failure is the streak's *5th* consecutive failure -- the cancellation
        # simply does not move the counter -- and the breaker trips there.
        run_calls: list[dict[str, Any]] = []
        statuses = {1: "failed", 2: "failed", 3: "failed", 4: "failed", 5: "cancelled", 6: "failed"}
        collaborators = _build_collaborators(_sequenced_status_run_generation(run_calls, statuses))
        config = _default_config(max_generations=20)

        loop_module.start_loop(
            config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
        )
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state == "failed")

        assert final.state == "failed"
        assert final.completed_generations == 6, "the breaker must trip on generation 6, not stall or trip early"
        assert [outcome.status for outcome in reversed(final.history)] == [
            "failed",
            "failed",
            "failed",
            "failed",
            "cancelled",
            "failed",
        ]


# ---------------------------------------------------------------------------
# `PLAN.md` survives a `write_cards` failure -- requirement (d). This is the module docstring's own
# "Pre-registration, mechanised" incident: `write_cards`, not `run_generation`, is where the real loop
# actually failed 1,644 times, and `PLAN.md` used to be written *after* that call.
# ---------------------------------------------------------------------------


class TestPlanSurvivesCardWritingFailure:
    def test_write_cards_raising_still_leaves_plan_md_on_disk(self, settings: Settings, tmp_path: Path) -> None:
        collaborators = _build_collaborators(_succeeding_run_generation([]))
        collaborators = dataclasses.replace(collaborators, write_cards=_write_cards_raising)
        config = _default_config(max_generations=1)

        loop_module.start_loop(
            config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
        )
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final is not None
        assert final.state == "stopped", "a single failed generation must not kill the loop"
        assert len(final.history) == 1
        assert final.history[0].status == "failed"
        assert final.history[0].error is not None
        assert "Read-only file system" in final.history[0].error

        # The assertion inside `_write_cards_raising` already proved the file existed *before* the
        # raise (from inside the failing fake, per requirement (d)); this re-checks it from the
        # outside, after the loop has finished, to prove the raise did not somehow remove it either.
        plan_path = loop_root(settings) / "gen0001" / "PLAN.md"
        assert plan_path.exists(), (
            "PLAN.md must survive a write_cards failure -- it is written before write_cards runs"
        )


# ---------------------------------------------------------------------------
# The failure log line names the generation number and the phase it failed in -- requirement (e) and
# requirement (3) ("make the failure legible"). `_raising_once_run_generation` raises a plain
# `RuntimeError` from inside `run_generation`, which by generation 1 is called with `loop.phase ==
# "running"` (set just before the retry loop that calls it).
# ---------------------------------------------------------------------------


class TestFailureLogNamesGenerationAndPhase:
    def test_failure_log_line_names_the_generation_number_and_phase(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        run_calls: list[dict[str, Any]] = []
        collaborators = _build_collaborators(_raising_once_run_generation(run_calls))
        config = _default_config(max_generations=2)

        loop_module.start_loop(
            config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
        )
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final is not None
        failure_lines = [line for line in final.log if line.startswith("gen 1: FAILED")]
        assert len(failure_lines) == 1, f"expected exactly one gen-1 failure log line, got: {final.log}"
        assert "phase" in failure_lines[0], failure_lines[0]
        assert "'running'" in failure_lines[0], failure_lines[0]
        assert "synthetic failure in generation 1" in failure_lines[0], failure_lines[0]


# ---------------------------------------------------------------------------
# Reviewer wiring -- Collaborators.review_generation, LoopConfig.use_reviewer, and the feed-forward
# into the next generation of the same lane (config amendments, elite carve-outs, review direction).
#
# app.agents.reviewer and app.agents.review_models are another worker's concurrently-written packages
# and are never imported here; every scenario below wires a small local fake directly into
# Collaborators.review_generation instead, exactly like every other collaborator in this file (and
# exactly like TestAgentDesignerFallback does for design_generation). The fake review objects below
# duck-type app.agents.review_models.GenerationReview/ReviewDirection/CandidateNote/ProposedAmendment
# closely enough for app.evolution.loop._run_review to use them -- including a model_dump_json method,
# since _run_review writes the review straight to gen{N:04d}/REVIEW.json with it.
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class _FakeReviewDirection:
    headline: str = "a synthetic review"
    hypotheses: tuple[str, ...] = ()
    focus_symbols: tuple[str, ...] = ()
    avoid_symbols: tuple[str, ...] = ()
    emphasise_disciplines: tuple[str, ...] = ()
    retire_disciplines: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True, slots=True)
class _FakeCandidateNote:
    genome_id: str
    note: str
    keep: bool


@dataclasses.dataclass(frozen=True, slots=True)
class _FakeProposedAmendment:
    field: str
    value: Any
    reason: str = "synthetic amendment reason"


@dataclasses.dataclass(frozen=True, slots=True)
class _FakeGenerationReview:
    """Duck-types `app.agents.review_models.GenerationReview` closely enough for `_run_review`: every
    attribute it reads (`verdict`, `direction`, `per_candidate`, `amendments`) is present, plus a
    `model_dump_json` method so the REVIEW.json write (`review.model_dump_json(indent=2)`) works
    without a real pydantic model."""

    generation: int
    purpose: Purpose
    shape: str | None
    verdict: str
    post_mortem: str
    per_candidate: tuple[_FakeCandidateNote, ...]
    direction: _FakeReviewDirection
    amendments: tuple[_FakeProposedAmendment, ...]

    def model_dump_json(self, indent: int | None = None) -> str:
        def _convert(value: Any) -> Any:
            if dataclasses.is_dataclass(value) and not isinstance(value, type):
                return {f.name: _convert(getattr(value, f.name)) for f in dataclasses.fields(value)}
            if isinstance(value, tuple):
                return [_convert(item) for item in value]
            if isinstance(value, Purpose):
                return value.value
            return value

        return json.dumps(_convert(self), indent=indent, default=str)


def _review_generation_factory(
    calls: list[dict[str, Any]],
    *,
    verdict: str = "promising",
    headline: str = "a synthetic review",
    per_candidate_from_outcome: Any = None,
    amendments: tuple[_FakeProposedAmendment, ...] = (),
    focus_symbols: tuple[str, ...] = (),
    avoid_symbols: tuple[str, ...] = (),
) -> Any:
    """Builds a `review_generation` fake. `per_candidate_from_outcome`, when given, is called with the
    generation's own `outcome` and must return `tuple[_FakeCandidateNote, ...]` -- letting a test build
    notes that reference this generation's *actual* `genome_ids` rather than guessing them."""

    def review_generation(
        *,
        outcome: Any,
        config: LoopConfig,
        settings: Settings,
        budget: AgentBudget,
        genomes: tuple[Genome, ...] = (),
        history: tuple[Any, ...] = (),
    ) -> tuple[_FakeGenerationReview, AgentBudget]:
        calls.append({"outcome": outcome, "config": config, "genomes": genomes, "history": history})
        per_candidate = per_candidate_from_outcome(outcome) if per_candidate_from_outcome is not None else ()
        review = _FakeGenerationReview(
            generation=outcome.generation,
            purpose=outcome.purpose,
            shape=None,
            verdict=verdict,
            post_mortem="synthetic post-mortem, written after the generation was scored",
            per_candidate=per_candidate,
            direction=_FakeReviewDirection(
                headline=headline, focus_symbols=focus_symbols, avoid_symbols=avoid_symbols
            ),
            amendments=amendments,
        )
        new_budget = AgentBudget(
            cap_usd=budget.cap_usd, spent_usd=budget.spent_usd + Decimal("0.10"), calls=budget.calls + 1
        )
        return review, new_budget

    return review_generation


class TestUseReviewerFalseNeverCallsReviewer:
    """LoopConfig.use_reviewer=False (the default) must never call review_generation, even when a real
    one is wired into Collaborators -- mirroring TestUseAgentFalseNeverCallsDesigner's proof for the
    designer."""

    def test_use_reviewer_false_never_calls_the_wired_reviewer(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        review_calls: list[dict[str, Any]] = []

        def review_generation(**kwargs: Any) -> Any:
            review_calls.append(kwargs)
            raise AssertionError("review_generation must never be called when use_reviewer=False")

        collaborators = _build_collaborators(_succeeding_run_generation([]))
        collaborators = dataclasses.replace(collaborators, review_generation=review_generation)
        config = _default_config(max_generations=1, use_reviewer=False)

        loop_module.start_loop(
            config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
        )
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final.state == "stopped"
        assert final.history[0].status == "succeeded"
        assert review_calls == []
        assert final.latest_review_headline is None
        assert final.latest_review_verdict is None
        assert not (loop_root(settings) / "gen0001" / "REVIEW.json").exists()


class TestReviewerCalledAndReviewWritten:
    """With LoopConfig.use_reviewer=True and a review_generation collaborator wired, the review is
    called exactly once per generation and gen{N:04d}/REVIEW.json is written. Also covers the
    amendment path end to end: a review that proposes one applies-cleanly amendment is reflected on
    `LoopStatus.amendments_applied` and in `data/loop/amendments.jsonl`."""

    def test_review_called_once_and_review_json_written(self, settings: Settings, tmp_path: Path) -> None:
        review_calls: list[dict[str, Any]] = []
        collaborators = _build_collaborators(_succeeding_run_generation([]))
        collaborators = dataclasses.replace(
            collaborators,
            review_generation=_review_generation_factory(
                review_calls,
                verdict="promising",
                headline="clean sweep this generation",
                amendments=(_FakeProposedAmendment(field="elite_count", value=3),),
            ),
        )
        config = _default_config(max_generations=1, use_reviewer=True)

        loop_module.start_loop(
            config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
        )
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final.state == "stopped"
        assert final.history[0].status == "succeeded"
        assert len(review_calls) == 1
        assert final.latest_review_verdict == "promising"
        assert final.latest_review_headline == "clean sweep this generation"
        assert any("review --" in line for line in final.log)
        assert any("reviewer amendment applied" in line for line in final.log)

        review_path = loop_root(settings) / "gen0001" / "REVIEW.json"
        assert review_path.is_file()
        payload = json.loads(review_path.read_text(encoding="utf-8"))
        assert payload["verdict"] == "promising"
        assert payload["direction"]["headline"] == "clean sweep this generation"

        assert len(final.amendments_applied) == 1
        assert final.amendments_applied[0].field == "elite_count"
        assert final.amendments_applied[0].applied is True

        amendments_file = loop_root(settings) / "amendments.jsonl"
        assert amendments_file.is_file()
        rows = [json.loads(line) for line in amendments_file.read_text(encoding="utf-8").splitlines() if line]
        assert len(rows) == 1
        assert rows[0]["field"] == "elite_count"
        assert rows[0]["applied"] is True


class TestReviewerFailureDoesNotFailGeneration:
    """A reviewer that raises must not fail the generation it reviewed (the outcome was already
    computed and correct before the reviewer was ever called) and must not move the consecutive-
    failure circuit breaker -- see `_run_review`'s own docstring for why a commentary layer is
    deliberately kept out of `_MAX_CONSECUTIVE_FAILURES`."""

    def test_reviewer_raising_does_not_fail_the_generation_or_trip_the_breaker(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        def review_generation(**kwargs: Any) -> Any:
            raise RuntimeError("synthetic bug in a package written concurrently with this one")

        collaborators = _build_collaborators(_succeeding_run_generation([]))
        collaborators = dataclasses.replace(collaborators, review_generation=review_generation)
        # Three generations, all reviewed (and all failing to be reviewed) -- if a reviewer failure
        # were ever counted as a generation failure, three of them in a row would still sit well under
        # `_MAX_CONSECUTIVE_FAILURES` (5), so this alone would not distinguish the two. The real proof
        # is `outcome.status == "succeeded"` for every one of them, checked below.
        config = _default_config(max_generations=3, use_reviewer=True)

        loop_module.start_loop(
            config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
        )
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final.state == "stopped"
        assert final.error is None
        assert final.completed_generations == 3
        assert all(outcome.status == "succeeded" for outcome in final.history)
        assert any("reviewer failed" in line for line in final.log)
        assert not (loop_root(settings) / "gen0001" / "REVIEW.json").exists()


class TestReviewerEliteCarveOut:
    """A reviewer's `per_candidate[].keep=True` note may ADD a non-elite genome to the next
    generation's breeding population, and must never DROP a genome `select_elites` (the deterministic
    ranking) already chose -- the fix for "only first place is tracked."

    Uses `_default_config`'s own population=2/elite_count=1 and the two-lane rotation
    `TestTwoGenerationRun`'s module comment already documents: with a single purpose, generation 1 and
    generation 3 share a lane, so generation 3's `propose` call is the load-bearing assertion -- its
    `elites` argument is what generation 1's carve-out actually bred forward.
    """

    def test_kept_non_elite_genome_breeds_forward_without_dropping_the_deterministic_elite(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        def keep_the_second_candidate(outcome: Any) -> tuple[_FakeCandidateNote, ...]:
            # `_select_elites` (this file's fake) keeps only the top `elite_count`=1 standing by
            # `median_excess`, which `_read_standings_factory` assigns in `genome_ids` order (index 0
            # gets the highest median) -- so `genome_ids[-1]` is guaranteed *not* to be the
            # deterministic elite. Marking it `keep=True` is the carve-out under test.
            kept_id = outcome.genome_ids[-1]
            return (_FakeCandidateNote(genome_id=kept_id, note="survived the holdout", keep=True),)

        review_calls: list[dict[str, Any]] = []
        propose_calls: list[dict[str, Any]] = []
        collaborators = _build_collaborators(_succeeding_run_generation([]), propose_calls=propose_calls)
        collaborators = dataclasses.replace(
            collaborators,
            review_generation=_review_generation_factory(
                review_calls, per_candidate_from_outcome=keep_the_second_candidate
            ),
        )
        config = _default_config(max_generations=3, use_reviewer=True)

        loop_module.start_loop(
            config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
        )
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final.state == "stopped"
        assert final.completed_generations == 3
        assert len(review_calls) == 3
        assert len(propose_calls) == 3

        gen1_ids = set(final.history[-1].genome_ids)  # history is most-recent-first; gen1 is oldest
        assert len(gen1_ids) == 2

        # Generation 3 is this lane's second appearance -- its `propose` call's `elites` argument is
        # what generation 1's carve-out actually bred forward.
        gen3_propose_elites = {genome.genome_id for genome in propose_calls[2]["elites"]}
        assert gen3_propose_elites == gen1_ids, (
            f"expected both generation 1 genomes (the deterministic elite and the reviewer's kept "
            f"candidate) to breed into generation 3, got {gen3_propose_elites}"
        )


# ---------------------------------------------------------------------------
# DEFECT 2 fix: a fresh loop always started counting generations from `1`, unconditionally, because
# `LoopStatus` (the supervisor's in-memory "what generation are we on") does not survive a restart even
# though `gen{N:04d}/OUTCOME.json` on disk does. A loop restarted against a `loop_root` that already
# held `gen0001`..`gen0028` from an earlier day's run wrote its next generation straight to `gen0001`,
# silently replacing a `succeeded` outcome carrying 10 standings with a new `succeeded` outcome carrying
# 4. `data/loop/` is gitignored, so there was no copy anywhere else -- the original record is simply
# gone. See `loop_module._first_generation_number`'s own docstring for the full incident and
# `loop_module.GenerationDirectoryCollision` for the belt-and-braces check that makes this failure mode
# impossible from a second angle, not merely unlikely.
# ---------------------------------------------------------------------------


def _touch_gen_dirs(root: Path, numbers: list[int]) -> None:
    for number in numbers:
        (root / f"gen{number:04d}").mkdir(parents=True, exist_ok=True)


def _make_outcome(
    *,
    generation: int,
    round_id: str,
    purpose: Purpose = Purpose.TRADING,
    genome_ids: tuple[str, ...] = (),
) -> GenerationOutcome:
    now = dt.datetime.now(dt.UTC)
    return GenerationOutcome(
        generation=generation,
        round_id=round_id,
        purpose=purpose,
        status="succeeded",
        started_at=now,
        finished_at=now,
        windows=("w1",),
        genome_ids=genome_ids,
    )


class TestFirstGenerationNumber:
    """Direct tests of `loop_module._first_generation_number`, the pure directory-scanning function
    `_run` now calls exactly once, before its own first generation, in place of the hard-coded
    `generation_number = 1` that produced the `gen0001`-overwrite incident described above."""

    def test_a_root_that_does_not_exist_yet_starts_at_generation_one(self, tmp_path: Path) -> None:
        root = tmp_path / "loop-not-created-yet"
        assert not root.exists()
        assert loop_module._first_generation_number(root) == 1

    def test_an_empty_root_starts_at_generation_one(self, tmp_path: Path) -> None:
        root = tmp_path / "loop"
        root.mkdir()
        assert loop_module._first_generation_number(root) == 1

    def test_a_tree_holding_gen0001_through_gen0005_starts_at_six(self, tmp_path: Path) -> None:
        root = tmp_path / "loop"
        _touch_gen_dirs(root, list(range(1, 6)))  # gen0001..gen0005
        assert loop_module._first_generation_number(root) == 6

    def test_takes_the_maximum_not_the_count(self, tmp_path: Path) -> None:
        """A stray `gen1673` -- literally the generation count `_MAX_CONSECUTIVE_FAILURES`'s own
        read-only-filesystem incident produced, and a real entry under this codebase's own `loop_root`
        at the time this fix was written -- sitting alongside only 29 other generation directories must
        produce `1674`, not `29`. Counting directories and returning `count + 1` would return `29` and
        walk this exact defect back in, one restart at a time, from `gen0029` up through `gen1673`."""
        root = tmp_path / "loop"
        _touch_gen_dirs(root, [*range(1, 29), 1673])  # gen0001..gen0028, gen1673
        assert loop_module._first_generation_number(root) == 1674

    def test_non_generation_entries_are_skipped_without_raising(self, tmp_path: Path) -> None:
        """`loop_root` also holds `genomes/`, `rounds/`, `news_cache/`, and several loose `.jsonl`/
        `.json` files -- all real, present entries in this codebase's own tree. `genomes/` is the
        load-bearing case: it starts with the same three letters "gen" a generation directory does, so
        a naive `str.removeprefix("gen")` followed by `int(...)` throws `ValueError` on it
        (`int("omes")`). None of these seven entries may crash the scan."""
        root = tmp_path / "loop"
        _touch_gen_dirs(root, list(range(1, 6)))  # gen0001..gen0005
        (root / "genomes").mkdir()
        (root / "rounds").mkdir()
        (root / "news_cache").mkdir()
        (root / "ledger.jsonl").write_text("", encoding="utf-8")
        (root / "promotions.jsonl").write_text("", encoding="utf-8")
        (root / "roster_overlay.json").write_text("{}", encoding="utf-8")
        (root / "amendments.jsonl").write_text("", encoding="utf-8")

        assert loop_module._first_generation_number(root) == 6


class TestGenerationNumberingSurvivesARestart:
    """End-to-end reproductions of the actual incident, through the public `start_loop` entry point
    rather than by calling `_first_generation_number` directly -- proving the offset it computes is
    actually the one `_run` uses to name `gen{N:04d}/PLAN.md` and `gen{N:04d}/OUTCOME.json`."""

    def test_a_one_generation_loop_lands_on_gen0029_and_gen0001_is_left_untouched(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        root = loop_root(settings)
        _touch_gen_dirs(root, list(range(1, 29)))  # gen0001..gen0028, as an earlier day's loop left them
        sentinel = {"round_id": "r16-manual-yesterday", "note": "must survive a restart untouched"}
        (root / "gen0001" / "OUTCOME.json").write_text(json.dumps(sentinel), encoding="utf-8")

        run_calls: list[dict[str, Any]] = []
        collaborators = _build_collaborators(_succeeding_run_generation(run_calls))
        config = _default_config(max_generations=1, population=2)

        loop_module.start_loop(
            config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
        )
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final is not None
        assert final.state == "stopped"
        assert final.history[0].generation == 29
        assert (root / "gen0029" / "PLAN.md").exists()
        assert (root / "gen0029" / "OUTCOME.json").exists()

        # The earlier run's own record is untouched -- byte for byte the sentinel written above, not
        # this generation's outcome.
        assert json.loads((root / "gen0001" / "OUTCOME.json").read_text(encoding="utf-8")) == sentinel

    def test_an_empty_tree_still_starts_at_generation_one(self, settings: Settings, tmp_path: Path) -> None:
        """The fix must not change behaviour for every existing test in this file, all of which run
        against an empty `tmp_path`."""
        collaborators = _build_collaborators(_succeeding_run_generation([]))
        config = _default_config(max_generations=1, population=2)

        loop_module.start_loop(
            config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
        )
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final is not None
        assert final.state == "stopped"
        assert final.history[0].generation == 1
        assert (loop_root(settings) / "gen0001" / "OUTCOME.json").exists()

    def test_numbering_stays_monotonic_when_a_new_gen_dir_appears_mid_run(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        """`_first_generation_number` is computed once, before this loop's first generation -- see its
        own docstring's last section. A `gen0099` directory that appears *during* generation 1 (another
        process, a manual copy) must not make this loop's own generation 2 jump to `gen0100` or collide
        with anything; the offset was already fixed before generation 1 ever ran."""
        root = loop_root(settings)

        def run_generation(*, round_id, cards, windows, settings, cancel, log, output_root, max_workers=1):
            _assert_plan_exists(settings, round_id)
            generation = _generation_from_round_id(round_id)
            if generation == 1:
                # A directory appearing mid-run, after this loop already computed its starting offset.
                (root / "gen0099").mkdir(parents=True, exist_ok=True)
            return _fake_execution_report(round_id=round_id, windows=windows, cards=cards)

        collaborators = _build_collaborators(run_generation)
        config = _default_config(max_generations=2, population=2)

        loop_module.start_loop(
            config, settings=settings, collaborators=collaborators, output_root=tmp_path / "rounds"
        )
        final = _poll_until(loop_module.get_status, lambda s: s is not None and s.state in ("stopped", "failed"))

        assert final is not None
        assert final.state == "stopped"
        generations = sorted(outcome.generation for outcome in final.history)
        assert generations == [1, 2], (
            f"expected this loop's own two generations to land at 1 and 2 regardless of the gen0099 "
            f"directory that appeared mid-run, got {generations}"
        )
        assert (root / "gen0002" / "OUTCOME.json").exists()
        assert not (root / "gen0100").exists()


class TestWriteOutcomeFileRefusesToOverwriteADifferentRound:
    """`_write_outcome_file`'s belt-and-braces check -- see `GenerationDirectoryCollision`'s own
    docstring for why this exists even with `_first_generation_number` computing a correct starting
    offset: two loops, or two processes, racing against the same `loop_root` can still land on the same
    generation number, and only this check makes that failure mode impossible rather than unlikely."""

    def test_a_second_rounds_outcome_for_the_same_generation_is_refused_not_overwritten(
        self, settings: Settings
    ) -> None:
        first = _make_outcome(generation=5, round_id="r1-auto-first-g0005")
        loop_module._write_outcome_file(settings, first)

        second = _make_outcome(generation=5, round_id="r1-auto-second-g0005")
        with pytest.raises(GenerationDirectoryCollision):
            loop_module._write_outcome_file(settings, second)

        on_disk = json.loads((loop_root(settings) / "gen0005" / "OUTCOME.json").read_text(encoding="utf-8"))
        assert on_disk["round_id"] == "r1-auto-first-g0005", (
            "the first round's outcome must survive a refused second write completely untouched"
        )

    def test_rewriting_the_identical_round_id_is_not_a_collision(self, settings: Settings) -> None:
        """Writing the same generation's own outcome twice under the identical `round_id` is not the
        two-different-rounds failure mode this check exists to catch, and must not raise."""
        outcome = _make_outcome(generation=7, round_id="r1-auto-again-g0007")
        loop_module._write_outcome_file(settings, outcome)
        loop_module._write_outcome_file(settings, outcome)  # must not raise

        assert (loop_root(settings) / "gen0007" / "OUTCOME.json").exists()

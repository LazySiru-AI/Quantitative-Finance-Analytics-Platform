"""Unit tests for Vibe Trading: preset loading/DAG validation, the swarm executor, and the service
layer's error mapping.

No test here makes a real model call. `app.vibedesk.runtime.run_grounded` is monkeypatched to a fake
that returns a scripted `GroundedResult`, and `app.agentdesk.evidence.build_pack` is monkeypatched to
skip the real market-data/news/macro providers entirely -- this suite proves the DAG orchestration,
not the data layer, which `tests/test_agentdesk_core.py` already covers on its own.
"""

from __future__ import annotations

import datetime as dt
import threading
from decimal import Decimal

import pytest

from app.agentdesk import evidence
from app.agentdesk.grounding import GroundedResult
from app.agentdesk.models import (
    DeskRun,
    EvidenceItem,
    EvidencePack,
    EvidenceSection,
    GroundingVerdict,
)
from app.agentdesk.store import RunStore
from app.agents.models import AgentBudget, AgentCall, AgentUnavailable
from app.config import Settings
from app.vibedesk import presets, runtime, service
from app.vibedesk.presets import (
    DagError,
    Preset,
    PresetAgent,
    PresetTask,
    PresetVariable,
    list_presets,
    load_preset,
    topological_layers,
    validate_dag,
)
from app.vibedesk.schemas import StartSwarmRequest, WorkerOutput

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _agent(agent_id: str, evidence_sections: tuple[str, ...] = ()) -> PresetAgent:
    return PresetAgent(
        id=agent_id, label=agent_id.title(), blurb="", evidence=evidence_sections, system=f"system for {agent_id}"
    )


def _task(task_id: str, agent_id: str, depends_on: tuple[str, ...] = (), prompt: str = "do {symbol}") -> PresetTask:
    return PresetTask(id=task_id, agent_id=agent_id, depends_on=depends_on, prompt=prompt)


def _preset(name: str, agents: tuple[PresetAgent, ...], tasks: tuple[PresetTask, ...]) -> Preset:
    return Preset(
        name=name,
        label=name.title(),
        blurb="test preset",
        variables=(PresetVariable(name="symbol", label="Symbol", required=True, default=""),),
        agents=agents,
        tasks=tasks,
    )


def _diamond_preset() -> Preset:
    """a -> {b, c} -> d."""
    agents = tuple(_agent(x) for x in ("a", "b", "c", "d"))
    tasks = (
        _task("a", "a"),
        _task("b", "b", depends_on=("a",)),
        _task("c", "c", depends_on=("a",)),
        _task("d", "d", depends_on=("b", "c")),
    )
    return _preset("diamond", agents, tasks)


def _fake_call(role: str) -> AgentCall:
    return AgentCall(
        call_id=f"call-{role}", role="swarm_worker", model="claude-opus-5",
        created_at=dt.datetime.now(dt.UTC), system="s", user="u", raw_response="r",
        cost_usd=Decimal("0.01"),
    )


def _grounded(report: str, summary: str, *, ok: bool = True, degraded: bool = False,
              budget: AgentBudget) -> GroundedResult[WorkerOutput]:
    verdict = GroundingVerdict(ok=ok, degraded=degraded, attempts=1)
    new_budget = AgentBudget(cap_usd=budget.cap_usd, spent_usd=budget.spent_usd + Decimal("0.01"), calls=budget.calls + 1)
    return GroundedResult(
        value=WorkerOutput(report=report, summary=summary),
        verdict=verdict,
        calls=(_fake_call("worker"),),
        budget=new_budget,
    )


def _settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


def _empty_pack(symbol: str = "", sections: object = ()) -> EvidencePack:
    return EvidencePack(symbol=symbol, sections=())


@pytest.fixture(autouse=True)
def _no_real_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test in this module may reach the real market-data/news/macro providers."""
    monkeypatch.setattr(evidence, "build_pack", lambda symbol, as_of, *, settings, sections: _empty_pack(symbol, sections))


class _NoopRegistry:
    """A drop-in for `service.registry()` that accepts a `start` without spawning the worker thread --
    lets a `start_run` test assert on the run it builds (its resolved model, say) without the real DAG
    firing model calls in the background."""

    def start(self, kind: str, run_id: str, target: object) -> None:
        pass


def _stub_load_preset(monkeypatch: pytest.MonkeyPatch, preset: Preset) -> None:
    """`run_swarm` re-resolves its preset by name via `runtime.load_preset` (matching the pinned
    `SwarmConfig` shape, which carries only `preset_name`) -- tests that build a `Preset` in memory
    rather than shipping it as a file under `presets/` stub that lookup instead."""
    monkeypatch.setattr(runtime, "load_preset", lambda name: preset)


def _seed_run(store: RunStore, preset: Preset, *, budget_usd: str = "5.00") -> DeskRun:
    run = DeskRun(
        run_id="run-1",
        kind="vibedesk",
        state="queued",
        created_at=dt.datetime.now(dt.UTC),
        config={"preset": preset.name, "symbol": "AAPL", "question": "", "variables": {}, "model": "claude-opus-5"},
        stages=runtime.build_stage_plan(preset),
        budget=AgentBudget(cap_usd=Decimal(budget_usd)),
    )
    store.save(run)
    return run


# ---------------------------------------------------------------------------
# validate_dag / topological_layers
# ---------------------------------------------------------------------------


class TestValidateDag:
    def test_rejects_unknown_depends_on(self) -> None:
        preset = _preset("bad", (_agent("a"),), (_task("a", "a", depends_on=("ghost",)),))
        with pytest.raises(DagError, match="unknown task"):
            validate_dag(preset)

    def test_rejects_unknown_agent_id(self) -> None:
        preset = _preset("bad", (_agent("a"),), (_task("t", "not-an-agent"),))
        with pytest.raises(DagError, match="unknown agent"):
            validate_dag(preset)

    def test_rejects_duplicate_task_id(self) -> None:
        preset = _preset("bad", (_agent("a"),), (_task("t", "a"), _task("t", "a")))
        with pytest.raises(DagError, match="duplicate task id"):
            validate_dag(preset)

    def test_rejects_a_cycle_without_hanging(self) -> None:
        agents = (_agent("a"), _agent("b"))
        tasks = (_task("a", "a", depends_on=("b",)), _task("b", "b", depends_on=("a",)))
        preset = _preset("cyclic", agents, tasks)
        with pytest.raises(DagError, match="cycle"):
            validate_dag(preset)

    def test_a_valid_diamond_passes(self) -> None:
        validate_dag(_diamond_preset())  # must not raise


class TestTopologicalLayers:
    def test_diamond_groups_into_three_layers(self) -> None:
        layers = topological_layers(_diamond_preset())
        assert len(layers) == 3
        assert [task.id for task in layers[0]] == ["a"]
        assert {task.id for task in layers[1]} == {"b", "c"}
        assert [task.id for task in layers[2]] == ["d"]

    def test_layer_field_matches_position(self) -> None:
        layers = topological_layers(_diamond_preset())
        for index, layer in enumerate(layers):
            for task in layer:
                assert task.layer == index


# ---------------------------------------------------------------------------
# build_stage_plan
# ---------------------------------------------------------------------------


class TestBuildStagePlan:
    def test_seats_layers_and_dependencies_are_correct(self) -> None:
        preset = _diamond_preset()
        stages = runtime.build_stage_plan(preset)
        by_id = {stage.stage_id: stage for stage in stages}

        assert by_id["a"].seat == "a"
        assert by_id["a"].layer == 0
        assert by_id["a"].depends_on == ()
        assert by_id["d"].layer == 2
        assert set(by_id["d"].depends_on) == {"b", "c"}
        assert all(stage.role == "swarm_worker" for stage in stages)
        assert all(stage.state == "pending" for stage in stages)


# ---------------------------------------------------------------------------
# run_swarm
# ---------------------------------------------------------------------------


class TestRunSwarmHappyPath:
    def test_reaches_succeeded_with_final_md(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        preset = _diamond_preset()
        settings = _settings(tmp_path)
        store = RunStore(settings, "vibedesk")
        _seed_run(store, preset)
        _stub_load_preset(monkeypatch, preset)

        def fake_run_grounded(*, role, system, user, output_format, prose_of, pack, settings, budget, model, max_attempts=3):
            return _grounded(f"report for {system}", f"summary for {system}", budget=budget)

        monkeypatch.setattr(runtime, "run_grounded", fake_run_grounded)

        config = runtime.SwarmConfig(
            preset_name=preset.name, symbol="AAPL", question="", variables={}, budget_usd=Decimal("5.00"),
        )
        runtime.run_swarm("run-1", config, settings=settings, cancel=threading.Event())

        final = store.load("run-1")
        assert final is not None
        assert final.state == "succeeded"
        assert final.final_md != ""
        assert "system for d" in final.final_md
        assert all(stage.state == "succeeded" for stage in final.stages)
        assert final.budget.calls == 4
        assert final.degraded is False


class TestRunSwarmBlocking:
    def test_a_failed_upstream_blocks_its_dependent_with_no_call(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        agents = (_agent("a"), _agent("b"))
        tasks = (_task("a", "a"), _task("b", "b", depends_on=("a",)))
        preset = _preset("fails", agents, tasks)
        settings = _settings(tmp_path)
        store = RunStore(settings, "vibedesk")
        _seed_run(store, preset)
        _stub_load_preset(monkeypatch, preset)

        call_count = {"n": 0}

        def fake_run_grounded(*, role, system, user, output_format, prose_of, pack, settings, budget, model, max_attempts=3):
            call_count["n"] += 1
            raise AgentUnavailable("no credential")

        monkeypatch.setattr(runtime, "run_grounded", fake_run_grounded)

        config = runtime.SwarmConfig(
            preset_name=preset.name, symbol="AAPL", question="", variables={}, budget_usd=Decimal("5.00"),
        )
        runtime.run_swarm("run-1", config, settings=settings, cancel=threading.Event())

        final = store.load("run-1")
        assert final is not None
        by_id = {stage.stage_id: stage for stage in final.stages}
        assert by_id["a"].state == "failed"
        assert by_id["b"].state == "blocked"
        assert call_count["n"] == 1  # task b's dependency failed, so b never called run_grounded
        assert final.state == "failed"

    def test_a_degraded_upstream_does_not_block_its_dependent(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        agents = (_agent("a"), _agent("b"))
        tasks = (_task("a", "a"), _task("b", "b", depends_on=("a",)))
        preset = _preset("degrades", agents, tasks)
        settings = _settings(tmp_path)
        store = RunStore(settings, "vibedesk")
        _seed_run(store, preset)
        _stub_load_preset(monkeypatch, preset)

        call_order: list[str] = []

        def fake_run_grounded(*, role, system, user, output_format, prose_of, pack, settings, budget, model, max_attempts=3):
            call_order.append(system)
            first_call = len(call_order) == 1
            return _grounded(
                "report", "summary", ok=not first_call, degraded=first_call, budget=budget,
            )

        monkeypatch.setattr(runtime, "run_grounded", fake_run_grounded)

        config = runtime.SwarmConfig(
            preset_name=preset.name, symbol="AAPL", question="", variables={}, budget_usd=Decimal("5.00"),
        )
        runtime.run_swarm("run-1", config, settings=settings, cancel=threading.Event())

        final = store.load("run-1")
        assert final is not None
        by_id = {stage.stage_id: stage for stage in final.stages}
        assert by_id["a"].state == "degraded"
        assert by_id["b"].state == "succeeded"  # ran despite the degraded upstream
        assert len(call_order) == 2  # b was in fact called
        assert final.degraded is True
        assert final.state == "succeeded"  # no *failed* stage, only a degraded one

    def test_downstream_prompt_receives_the_summary_not_the_report(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        agents = (_agent("a"), _agent("b"))
        tasks = (_task("a", "a"), _task("b", "b", depends_on=("a",), prompt="follow up on {symbol}"))
        preset = _preset("summary-only", agents, tasks)
        settings = _settings(tmp_path)
        store = RunStore(settings, "vibedesk")
        _seed_run(store, preset)
        _stub_load_preset(monkeypatch, preset)

        seen_users: list[str] = []

        def fake_run_grounded(*, role, system, user, output_format, prose_of, pack, settings, budget, model, max_attempts=3):
            seen_users.append(user)
            if system == "system for a":
                return _grounded("THE_FULL_REPORT_TEXT", "THE_SHORT_SUMMARY", budget=budget)
            return _grounded("second report", "second summary", budget=budget)

        monkeypatch.setattr(runtime, "run_grounded", fake_run_grounded)

        config = runtime.SwarmConfig(
            preset_name=preset.name, symbol="AAPL", question="", variables={}, budget_usd=Decimal("5.00"),
        )
        runtime.run_swarm("run-1", config, settings=settings, cancel=threading.Event())

        second_user = seen_users[1]
        assert "THE_SHORT_SUMMARY" in second_user
        assert "THE_FULL_REPORT_TEXT" not in second_user


class TestRunSwarmQuestion:
    """The run-level `question` reaches every stage's turn (or, when blank, changes nothing)."""

    def test_the_run_question_is_injected_into_every_stage_turn(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agents = (_agent("a"), _agent("b"))
        tasks = (_task("a", "a"), _task("b", "b", depends_on=("a",)))
        preset = _preset("with-question", agents, tasks)
        settings = _settings(tmp_path)
        store = RunStore(settings, "vibedesk")
        _seed_run(store, preset)
        _stub_load_preset(monkeypatch, preset)

        seen_users: list[str] = []

        def fake_run_grounded(*, role, system, user, output_format, prose_of, pack, settings, budget, model, max_attempts=3):
            seen_users.append(user)
            return _grounded("report", "summary", budget=budget)

        monkeypatch.setattr(runtime, "run_grounded", fake_run_grounded)

        config = runtime.SwarmConfig(
            preset_name=preset.name, symbol="AAPL",
            question="Is the bitcoin-backed balance sheet a durable edge?",
            variables={}, budget_usd=Decimal("5.00"),
        )
        runtime.run_swarm("run-1", config, settings=settings, cancel=threading.Event())

        assert len(seen_users) == 2  # both the layer-0 agent and its dependent see it
        for user in seen_users:
            assert "The desk's question for this run" in user
            assert "Is the bitcoin-backed balance sheet a durable edge?" in user

    def test_a_blank_question_injects_no_block(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        # The default when the asker leaves the field empty. A whitespace-only value is treated the
        # same -- the `.strip()` guard means the turn is byte-for-byte what it was before this existed.
        agents = (_agent("a"),)
        tasks = (_task("a", "a"),)
        preset = _preset("no-question", agents, tasks)
        settings = _settings(tmp_path)
        store = RunStore(settings, "vibedesk")
        _seed_run(store, preset)
        _stub_load_preset(monkeypatch, preset)

        seen_users: list[str] = []

        def fake_run_grounded(*, role, system, user, output_format, prose_of, pack, settings, budget, model, max_attempts=3):
            seen_users.append(user)
            return _grounded("report", "summary", budget=budget)

        monkeypatch.setattr(runtime, "run_grounded", fake_run_grounded)

        config = runtime.SwarmConfig(
            preset_name=preset.name, symbol="AAPL", question="   ",
            variables={}, budget_usd=Decimal("5.00"),
        )
        runtime.run_swarm("run-1", config, settings=settings, cancel=threading.Event())

        assert len(seen_users) == 1
        assert "The desk's question" not in seen_users[0]


class TestRunSwarmGrounding:
    """A stage is graded against the shared ground truth it was *shown*, not its own narrower sections."""

    def test_a_stage_is_grounded_against_the_union_not_its_own_sections(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A narrow agent (`price` only) sits in a desk whose union is {price, fundamentals}. The
        # ground-truth block injected into its prompt covers the union, so grading it against only
        # `price` would degrade it for citing a balance-sheet figure it was handed -- the risk-officer
        # bug. Grading must use the union pack the stage actually saw.
        agents = (_agent("p", ("price",)), _agent("f", ("fundamentals",)))
        tasks = (_task("p", "p"), _task("f", "f"))
        preset = _preset("mixed-evidence", agents, tasks)
        settings = _settings(tmp_path)
        store = RunStore(settings, "vibedesk")
        _seed_run(store, preset)
        _stub_load_preset(monkeypatch, preset)

        # Override the autouse empty-pack stub with one that encodes which sections it was built from,
        # so the grading pack's provenance is readable back off the object.
        def sectioned_pack(symbol, as_of, *, settings, sections):
            label = ",".join(sorted(sections)) or "none"
            return EvidencePack(
                symbol=symbol,
                sections=(EvidenceSection(title="S", items=(EvidenceItem(key="k", label="sections", value=label),)),),
            )

        monkeypatch.setattr(evidence, "build_pack", sectioned_pack)

        graded_against: dict[str, str] = {}

        def fake_run_grounded(*, role, system, user, output_format, prose_of, pack, settings, budget, model, max_attempts=3):
            graded_against[system] = pack.sections[0].items[0].value
            return _grounded("report", "summary", budget=budget)

        monkeypatch.setattr(runtime, "run_grounded", fake_run_grounded)

        config = runtime.SwarmConfig(
            preset_name=preset.name, symbol="AAPL", question="", variables={}, budget_usd=Decimal("5.00"),
        )
        runtime.run_swarm("run-1", config, settings=settings, cancel=threading.Event())

        # Both stages -- including the price-only agent -- are graded against the {fundamentals, price}
        # union, not the single section each declares.
        assert graded_against["system for p"] == "fundamentals,price"
        assert graded_against["system for f"] == "fundamentals,price"


class TestRunSwarmCancellation:
    def test_cancellation_before_the_first_layer_skips_every_task(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        preset = _diamond_preset()
        settings = _settings(tmp_path)
        store = RunStore(settings, "vibedesk")
        _seed_run(store, preset)
        _stub_load_preset(monkeypatch, preset)

        call_count = {"n": 0}

        def fake_run_grounded(**kwargs):
            call_count["n"] += 1
            raise AssertionError("run_grounded must not be called once cancellation is set")

        monkeypatch.setattr(runtime, "run_grounded", fake_run_grounded)

        cancel_event = threading.Event()
        cancel_event.set()

        config = runtime.SwarmConfig(
            preset_name=preset.name, symbol="AAPL", question="", variables={}, budget_usd=Decimal("5.00"),
        )
        runtime.run_swarm("run-1", config, settings=settings, cancel=cancel_event)

        final = store.load("run-1")
        assert final is not None
        assert final.state == "cancelled"
        assert all(stage.state == "skipped" for stage in final.stages)
        assert call_count["n"] == 0


# ---------------------------------------------------------------------------
# Presets on disk -- both hand-authored ones plus the new risk_committee.json
# ---------------------------------------------------------------------------


class TestShippedPresets:
    def test_all_shipped_presets_load_and_validate(self) -> None:
        all_presets = list_presets()
        names = {preset.name for preset in all_presets}
        # A superset check, not an equality: the Agent Workflow desk ships `followup_review`, and any
        # later preset is a pure-JSON addition that must not have to edit this assertion to land.
        # What this test actually guards is that *every* preset on disk loads and validates, which an
        # equality on a frozen name set stopped doing the moment a fourth file appeared.
        assert {"investment_committee", "technical_analysis_panel", "risk_committee"} <= names
        for preset in all_presets:
            validate_dag(preset)  # must not raise
            layers = topological_layers(preset)
            assert layers  # every preset has at least one layer

    def test_risk_committee_has_the_expected_agents_and_shape(self) -> None:
        preset = load_preset("risk_committee")
        agent_ids = {agent.id for agent in preset.agents}
        assert agent_ids == {"drawdown_analyst", "tail_risk_analyst", "regime_detector", "risk_aggregator"}

        by_id = {task.id: task for task in preset.tasks}
        aggregate = by_id["aggregate"]
        assert aggregate.agent_id == "risk_aggregator"
        assert aggregate.layer == 1
        assert set(aggregate.depends_on) == {"drawdown", "tail_risk", "regime"}
        for task_id in ("drawdown", "tail_risk", "regime"):
            assert by_id[task_id].layer == 0

    def test_unknown_preset_raises_preset_not_found(self) -> None:
        with pytest.raises(presets.PresetNotFound):
            load_preset("does-not-exist")


# ---------------------------------------------------------------------------
# service.py error mapping (no run is ever actually started here)
# ---------------------------------------------------------------------------


class TestServiceValidation:
    def test_start_run_raises_preset_not_found(self, tmp_path) -> None:
        req = StartSwarmRequest(preset="does-not-exist", symbol="AAPL")
        with pytest.raises(presets.PresetNotFound):
            service.start_run(req, settings=_settings(tmp_path))

    def test_start_run_rejects_an_unknown_variable(self, tmp_path) -> None:
        req = StartSwarmRequest(preset="investment_committee", symbol="AAPL", variables={"not_a_real_var": "x"})
        with pytest.raises(service.InvalidPresetVariable):
            service.start_run(req, settings=_settings(tmp_path))

    def test_start_run_rejects_a_missing_required_symbol(self, tmp_path) -> None:
        req = StartSwarmRequest(preset="investment_committee", symbol="")
        with pytest.raises(service.InvalidPresetVariable):
            service.start_run(req, settings=_settings(tmp_path))

    def test_start_run_rejects_a_bad_budget(self, tmp_path) -> None:
        req = StartSwarmRequest(preset="investment_committee", symbol="AAPL", budget_usd="not-a-number")
        with pytest.raises(service.InvalidPresetVariable):
            service.start_run(req, settings=_settings(tmp_path))

    def test_start_run_reports_agent_unavailable_as_503_worthy_error(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.agents import client as agents_client

        monkeypatch.setattr(agents_client, "is_available", lambda: (False, "no credential configured"))
        req = StartSwarmRequest(preset="investment_committee", symbol="AAPL")
        with pytest.raises(service.AgentLayerUnavailable, match="no credential configured"):
            service.start_run(req, settings=_settings(tmp_path))

    def test_start_run_defaults_the_worker_model_to_haiku(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A request that names no model gets the desk default -- Haiku 4.5, the cheapest/fastest tier --
        # and it is echoed back on the run's own config.
        from app.agents import client as agents_client

        monkeypatch.setattr(agents_client, "is_available", lambda: (True, "ok"))
        monkeypatch.setattr(service, "registry", lambda: _NoopRegistry())
        run = service.start_run(
            StartSwarmRequest(preset="investment_committee", symbol="AAPL"), settings=_settings(tmp_path)
        )
        assert run.config["model"] == "claude-haiku-4-5-20251001"
        assert runtime.DESK_DEFAULT_MODEL == "claude-haiku-4-5-20251001"

    def test_start_run_honours_an_explicit_worker_model(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.agents import client as agents_client

        monkeypatch.setattr(agents_client, "is_available", lambda: (True, "ok"))
        monkeypatch.setattr(service, "registry", lambda: _NoopRegistry())
        run = service.start_run(
            StartSwarmRequest(preset="investment_committee", symbol="AAPL", model="claude-opus-5"),
            settings=_settings(tmp_path),
        )
        assert run.config["model"] == "claude-opus-5"

    def test_cancel_run_raises_run_not_found(self, tmp_path) -> None:
        with pytest.raises(service.RunNotFound):
            service.cancel_run("no-such-run", settings=_settings(tmp_path))

    def test_presets_payload_lists_the_shipped_presets(self) -> None:
        payload = service.presets_payload()
        # Superset, not equality -- see `test_all_shipped_presets_load_and_validate` for why a new
        # preset must not have to touch this line.
        assert {"investment_committee", "technical_analysis_panel", "risk_committee"} <= {
            p.name for p in payload.presets
        }

    def test_preset_payload_is_none_for_unknown_name(self) -> None:
        assert service.preset_payload("does-not-exist") is None

    def test_preset_payload_has_agents_tasks_and_variables(self) -> None:
        detail = service.preset_payload("risk_committee")
        assert detail is not None
        assert detail.agent_count == 4
        assert detail.layer_count == 2
        assert len(detail.agents) == 4
        assert len(detail.tasks) == 4
        assert any(v.name == "symbol" for v in detail.variables)


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_vibedesk_router_is_registered_on_the_app() -> None:
    from app.main import app

    paths = app.openapi()["paths"]
    assert any("/api/vibedesk" in path for path in paths)
    assert "/api/vibedesk/presets" in paths
    assert "/api/vibedesk/runs" in paths
    assert "/api/vibedesk/runs/{run_id}" in paths


# ---------------------------------------------------------------------------
# The `live` opt-in -- see docs/AGENT-DESK-CONTRACT.md's `StartSwarmRequest.live`.
#
# As on the sibling desk, the load-bearing test is the first: a non-live run's
# ground truth must be exactly the preset's own declared sections, unchanged.
# ---------------------------------------------------------------------------


class TestLiveOptIn:
    def _preset_with_evidence(self) -> Preset:
        agents = (_agent("a", ("indicators", "price")), _agent("b", ("news",)))
        tasks = (_task("a", "a"), _task("b", "b", depends_on=("a",)))
        return _preset("livey", agents, tasks)

    def test_non_live_ground_truth_is_the_presets_own_sections(self) -> None:
        preset = self._preset_with_evidence()
        # SECTION_KEYS order, not preset authoring order -- unchanged by this feature.
        assert runtime._ground_truth_sections(preset) == ("price", "indicators", "news")
        assert runtime._ground_truth_sections(preset, live=False) == ("price", "indicators", "news")

    def test_live_appends_the_two_live_sections_in_section_keys_order(self) -> None:
        preset = self._preset_with_evidence()
        assert runtime._ground_truth_sections(preset, live=True) == (
            "price",
            "indicators",
            "news",
            "live_quote",
            "intraday",
        )

    def test_a_preset_that_already_declares_a_live_section_is_not_given_it_twice(self) -> None:
        preset = _preset("already", (_agent("a", ("live_quote",)),), (_task("a", "a"),))
        assert runtime._ground_truth_sections(preset, live=True) == ("live_quote", "intraday")

    def test_swarm_config_defaults_live_to_false(self) -> None:
        config = runtime.SwarmConfig(
            preset_name="x", symbol="AAPL", question="", variables={}, budget_usd=Decimal("5.00")
        )
        assert config.live is False

    def test_a_live_run_watches_the_symbol_and_builds_a_live_pack(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.market import livefeed

        preset = self._preset_with_evidence()
        settings = _settings(tmp_path)
        store = RunStore(settings, "vibedesk")
        _seed_run(store, preset)
        _stub_load_preset(monkeypatch, preset)

        watched: list[list[str]] = []
        monkeypatch.setattr(livefeed, "watch", lambda symbols: watched.append(list(symbols)))

        built: list[tuple[str, ...]] = []

        def _recording_build_pack(symbol, as_of, *, settings, sections):
            built.append(tuple(sections))
            return EvidencePack(symbol=symbol, sections=())

        monkeypatch.setattr(evidence, "build_pack", _recording_build_pack)

        def fake_run_grounded(*, role, system, user, output_format, prose_of, pack, settings, budget, model, max_attempts=3):
            return _grounded("report", "summary", budget=budget)

        monkeypatch.setattr(runtime, "run_grounded", fake_run_grounded)

        config = runtime.SwarmConfig(
            preset_name=preset.name,
            symbol="AAPL",
            question="",
            variables={},
            budget_usd=Decimal("5.00"),
            live=True,
        )
        runtime.run_swarm("run-1", config, settings=settings, cancel=threading.Event())

        assert watched == [["AAPL"]]
        assert built == [("price", "indicators", "news", "live_quote", "intraday")]

        final = store.load("run-1")
        assert final is not None
        assert final.state == "succeeded"

    def test_a_non_live_run_never_watches_and_keeps_its_own_sections(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.market import livefeed

        preset = self._preset_with_evidence()
        settings = _settings(tmp_path)
        store = RunStore(settings, "vibedesk")
        _seed_run(store, preset)
        _stub_load_preset(monkeypatch, preset)

        watched: list[list[str]] = []
        monkeypatch.setattr(livefeed, "watch", lambda symbols: watched.append(list(symbols)))

        built: list[tuple[str, ...]] = []

        def _recording_build_pack(symbol, as_of, *, settings, sections):
            built.append(tuple(sections))
            return EvidencePack(symbol=symbol, sections=())

        monkeypatch.setattr(evidence, "build_pack", _recording_build_pack)

        def fake_run_grounded(*, role, system, user, output_format, prose_of, pack, settings, budget, model, max_attempts=3):
            return _grounded("report", "summary", budget=budget)

        monkeypatch.setattr(runtime, "run_grounded", fake_run_grounded)

        config = runtime.SwarmConfig(
            preset_name=preset.name, symbol="AAPL", question="", variables={}, budget_usd=Decimal("5.00")
        )
        runtime.run_swarm("run-1", config, settings=settings, cancel=threading.Event())

        assert watched == []
        assert built == [("price", "indicators", "news")]

    def test_a_failing_watch_does_not_fail_the_run(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.market import livefeed

        preset = _diamond_preset()
        settings = _settings(tmp_path)
        store = RunStore(settings, "vibedesk")
        _seed_run(store, preset)
        _stub_load_preset(monkeypatch, preset)

        def _boom(symbols: object) -> None:
            raise RuntimeError("feed down")

        monkeypatch.setattr(livefeed, "watch", _boom)

        def fake_run_grounded(*, role, system, user, output_format, prose_of, pack, settings, budget, model, max_attempts=3):
            return _grounded("report", "summary", budget=budget)

        monkeypatch.setattr(runtime, "run_grounded", fake_run_grounded)

        config = runtime.SwarmConfig(
            preset_name=preset.name,
            symbol="AAPL",
            question="",
            variables={},
            budget_usd=Decimal("5.00"),
            live=True,
        )
        runtime.run_swarm("run-1", config, settings=settings, cancel=threading.Event())

        final = store.load("run-1")
        assert final is not None
        assert final.state == "succeeded"

    def test_start_run_persists_live_on_the_run_config(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.agents import client as agents_client
        from app.api.vibedesk import StartSwarmBody

        monkeypatch.setattr(agents_client, "is_available", lambda: (True, "ok"))
        monkeypatch.setattr(service, "registry", lambda: _NoopRegistry())

        run = service.start_run(
            StartSwarmBody(preset="investment_committee", symbol="AAPL", live=True),
            settings=_settings(tmp_path),
        )
        assert run.config["live"] is True

    def test_a_body_without_the_field_is_a_non_live_run(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`app.workflow.pipeline._launch_vibe` hands `start_run` a plain `StartSwarmRequest`, which
        carries no `live` field at all -- and is a non-live run, the default."""
        from app.agents import client as agents_client

        monkeypatch.setattr(agents_client, "is_available", lambda: (True, "ok"))
        monkeypatch.setattr(service, "registry", lambda: _NoopRegistry())

        run = service.start_run(
            StartSwarmRequest(preset="investment_committee", symbol="AAPL"), settings=_settings(tmp_path)
        )
        assert run.config["live"] is False

    def test_the_api_body_defaults_live_to_false(self) -> None:
        from app.api.vibedesk import StartSwarmBody

        assert StartSwarmBody(preset="investment_committee", symbol="AAPL").live is False
        assert StartSwarmBody(preset="investment_committee", symbol="AAPL", live=True).live is True

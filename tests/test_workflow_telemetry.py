"""Tests for `backend/app/workflow/telemetry.py` -- `iter_child_runs`/`build_workflow_telemetry`.

Every `DeskRun` this file needs is built directly as a Python object and persisted through the real
`app.agentdesk.store.RunStore.save` -- never through a live workflow run. `AgentCall` archives are
written the same way `tests/test_agentdesk_telemetry.py` does, directly under `agent_calls_dir`.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.agentdesk.models import DeskRun, StageRecord
from app.agentdesk.store import RunStore
from app.agents.models import AgentBudget, AgentCall, agent_calls_dir
from app.config import Settings
from app.workflow.telemetry import build_workflow_telemetry, iter_child_runs

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _write_call(settings: Settings, *, call_id: str, cost_usd: str, input_tokens: int = 10, output_tokens: int = 5) -> None:
    call = AgentCall(
        call_id=call_id, role="market_analyst", model="claude-opus-5",
        created_at=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
        system="sys", user="user", raw_response="resp",
        input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=Decimal(cost_usd),
    )
    directory = agent_calls_dir(settings)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{call_id}.json").write_text(call.model_dump_json(indent=2), encoding="utf-8")


def _child_run(*, run_id: str, kind: str, stage_call_ids: dict[str, tuple[str, ...]]) -> DeskRun:
    stages = tuple(
        StageRecord(stage_id=stage_id, role="market_analyst", label=stage_id, state="succeeded", call_ids=cids)
        for stage_id, cids in stage_call_ids.items()
    )
    return DeskRun(
        run_id=run_id, kind=kind,  # type: ignore[arg-type]
        state="succeeded", created_at=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
        stages=stages, budget=AgentBudget(cap_usd=Decimal("5.00")),
    )


def _workflow_run(
    *, run_id: str, child_runs: dict[str, str], own_stages: tuple[StageRecord, ...] = ()
) -> DeskRun:
    return DeskRun(
        run_id=run_id, kind="workflow", state="succeeded",
        created_at=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
        config={"child_runs": child_runs},
        stages=own_stages, budget=AgentBudget(cap_usd=Decimal("10.00")),
    )


# ---------------------------------------------------------------------------
# iter_child_runs
# ---------------------------------------------------------------------------


class TestIterChildRuns:
    def test_infers_kind_from_stage_id_prefix_and_resolves_both_desks(self, settings: Settings) -> None:
        ta_run = _child_run(run_id="ta-1", kind="tradingagents", stage_call_ids={"market_analyst": ()})
        vibe_run = _child_run(run_id="vibe-1", kind="vibedesk", stage_call_ids={"supporting": ()})
        RunStore(settings, "tradingagents").save(ta_run)
        RunStore(settings, "vibedesk").save(vibe_run)

        wf = _workflow_run(
            run_id="wf-1", child_runs={"research_ABC": "ta-1", "vibe_ABC": "vibe-1"}
        )
        resolved = list(iter_child_runs(wf, settings=settings))
        by_stage = {stage_id: (kind, child.run_id) for stage_id, kind, child in resolved}
        assert by_stage == {
            "research_ABC": ("tradingagents", "ta-1"),
            "vibe_ABC": ("vibedesk", "vibe-1"),
        }

    def test_skips_a_child_id_that_does_not_resolve(self, settings: Settings) -> None:
        wf = _workflow_run(run_id="wf-2", child_runs={"research_ABC": "never-saved"})
        assert list(iter_child_runs(wf, settings=settings)) == []

    def test_ignores_a_stage_id_prefix_it_does_not_recognise(self, settings: Settings) -> None:
        wf = _workflow_run(run_id="wf-3", child_runs={"candidate_scan": "some-id"})
        assert list(iter_child_runs(wf, settings=settings)) == []

    def test_no_child_runs_key_in_config_yields_nothing(self, settings: Settings) -> None:
        wf = DeskRun(
            run_id="wf-4", kind="workflow", state="succeeded",
            created_at=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
            budget=AgentBudget(cap_usd=Decimal("10.00")),
        )
        assert list(iter_child_runs(wf, settings=settings)) == []


# ---------------------------------------------------------------------------
# build_workflow_telemetry
# ---------------------------------------------------------------------------


class TestBuildWorkflowTelemetry:
    def test_reconciles_totals_across_own_stages_and_both_child_desk_kinds(self, settings: Settings) -> None:
        _write_call(settings, call_id="ta-call-1", cost_usd="0.10", input_tokens=100, output_tokens=20)
        _write_call(settings, call_id="ta-call-2", cost_usd="0.05", input_tokens=50, output_tokens=10)
        _write_call(settings, call_id="vibe-call-1", cost_usd="0.30", input_tokens=200, output_tokens=40)

        ta_run = _child_run(
            run_id="ta-1", kind="tradingagents",
            stage_call_ids={"market_analyst": ("ta-call-1", "ta-call-2")},
        )
        vibe_run = _child_run(
            run_id="vibe-1", kind="vibedesk", stage_call_ids={"verdict": ("vibe-call-1",)},
        )
        RunStore(settings, "tradingagents").save(ta_run)
        RunStore(settings, "vibedesk").save(vibe_run)

        own_stage = StageRecord(
            stage_id="regime_call", role="market_analyst", label="Regime", state="succeeded", call_ids=()
        )
        wf = _workflow_run(
            run_id="wf-reconcile",
            child_runs={"research_ABC": "ta-1", "vibe_ABC": "vibe-1"},
            own_stages=(own_stage,),
        )

        result = build_workflow_telemetry(wf, settings=settings)

        assert result.run_id == "wf-reconcile"
        assert len(result.stages) == 1
        assert result.stages[0].stage_id == "regime_call"
        assert result.stages[0].summary.call_count == 0

        assert len(result.children) == 2
        by_stage_id = {c.stage_id: c for c in result.children}

        ta_child = by_stage_id["research_ABC"]
        assert ta_child.kind == "tradingagents"
        assert ta_child.run_id == "ta-1"
        assert ta_child.summary.call_count == 2
        assert ta_child.summary.cost_usd == Decimal("0.15")
        assert ta_child.summary.input_tokens == 150

        vibe_child = by_stage_id["vibe_ABC"]
        assert vibe_child.kind == "vibedesk"
        assert vibe_child.summary.call_count == 1
        assert vibe_child.summary.cost_usd == Decimal("0.30")

        # Run total combines the workflow's own (empty) stages with both children.
        assert result.total.call_count == 3
        assert result.total.cost_usd == Decimal("0.45")
        assert result.total.input_tokens == 350

    def test_a_missing_call_file_in_a_child_stage_is_skipped_not_raised(self, settings: Settings) -> None:
        _write_call(settings, call_id="present-call", cost_usd="0.20", input_tokens=100)
        ta_run = _child_run(
            run_id="ta-2", kind="tradingagents",
            stage_call_ids={"market_analyst": ("present-call", "never-archived")},
        )
        RunStore(settings, "tradingagents").save(ta_run)
        wf = _workflow_run(run_id="wf-missing", child_runs={"research_XYZ": "ta-2"})

        result = build_workflow_telemetry(wf, settings=settings)
        assert len(result.children) == 1
        assert result.children[0].summary.call_count == 1
        assert result.children[0].summary.cost_usd == Decimal("0.20")
        assert result.total.call_count == 1

    def test_an_unresolvable_child_run_is_omitted_entirely_not_an_error(self, settings: Settings) -> None:
        wf = _workflow_run(run_id="wf-unresolvable", child_runs={"research_ZZZ": "does-not-exist"})
        result = build_workflow_telemetry(wf, settings=settings)
        assert result.children == ()
        assert result.total.call_count == 0
        assert result.total.cost_usd == Decimal(0)

    def test_a_run_with_no_stages_and_no_children_summarizes_to_all_zero(self, settings: Settings) -> None:
        wf = DeskRun(
            run_id="wf-empty", kind="workflow", state="queued",
            created_at=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
            budget=AgentBudget(cap_usd=Decimal("10.00")),
        )
        result = build_workflow_telemetry(wf, settings=settings)
        assert result.stages == ()
        assert result.children == ()
        assert result.total.call_count == 0

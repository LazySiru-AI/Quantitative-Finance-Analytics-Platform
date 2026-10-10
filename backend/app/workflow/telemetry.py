"""Per-run / per-stage token and cost telemetry for the Agent Workflow desk.

A workflow run's own `DeskRun.stages` almost never carry `call_ids` themselves -- the deterministic
spine (`regime_call`, `strategy_select`, `candidate_scan`, `followup_questions`, `entry_plan`,
`stage_orders`) never calls a model at all, and even the `research_<SYM>`/`vibe_<SYM>` stages that
launch a child run only copy that child's *cost* onto themselves (`app.workflow.pipeline.
_record_child`), not its call ids. The actual `AgentCall` archive pointers live on the child
`tradingagents`/`vibedesk` `DeskRun`'s own stages. `build_workflow_telemetry` walks both: the
workflow run's own stages (for forward-compatibility, and because it costs nothing extra to include
an always-empty set), and every child run named in `config["child_runs"]`.

`iter_child_runs` is the shared prefix-inference/child-walk this module and `app.workflow.study`
both need: given one workflow `DeskRun`, resolve its `config["child_runs"]` map (`{stage_id:
child_run_id}`, written by `app.workflow.pipeline._persist_child_runs`) into the actual child
`DeskRun`s, inferring each child's `DeskKind` from its stage-id prefix (`research_*` ->
`tradingagents`, `vibe_*` -> `vibedesk`) exactly as `app.workflow.pipeline._stage_research`/
`_stage_vibe` name their stages. A child id that does not resolve to a readable run is skipped, not
raised -- the same "unreadable run, logged and skipped" choice `RunStore.load` itself makes, since
this module answers a report, not a ledger.
"""

from __future__ import annotations

from collections.abc import Iterator

from pydantic import BaseModel, ConfigDict

from app.agentdesk.models import DeskKind, DeskRun
from app.agentdesk.store import RunStore
from app.agentdesk.telemetry import CallCostSummary, summarize_calls
from app.config import Settings

__all__ = [
    "ChildRunTelemetry",
    "StageTelemetry",
    "WorkflowRunTelemetry",
    "build_workflow_telemetry",
    "iter_child_runs",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class StageTelemetry(_Frozen):
    """One stage's call-cost summary -- either one of the workflow run's own stages, or one stage of
    a child `tradingagents`/`vibedesk` run."""

    stage_id: str
    label: str
    summary: CallCostSummary


class ChildRunTelemetry(_Frozen):
    """One child run (a `research_<SYM>` or `vibe_<SYM>` stage's launched `tradingagents`/`vibedesk`
    run) and its per-stage breakdown."""

    stage_id: str
    """The workflow stage that launched this child -- the `config["child_runs"]` key."""

    kind: DeskKind
    run_id: str
    stages: tuple[StageTelemetry, ...]
    summary: CallCostSummary
    """Totals across every stage of this child run."""


class WorkflowRunTelemetry(_Frozen):
    """One workflow run's full telemetry: its own stages, every child run it launched, and the
    combined total across all of them."""

    run_id: str
    stages: tuple[StageTelemetry, ...]
    """The workflow run's own stages -- see the module docstring for why these are ordinarily
    empty-summary entries."""

    children: tuple[ChildRunTelemetry, ...]
    total: CallCostSummary
    """Sum across this run's own stages and every child run's stages -- the run's whole spend."""


def iter_child_runs(run: DeskRun, *, settings: Settings) -> Iterator[tuple[str, DeskKind, DeskRun]]:
    """Yield `(stage_id, kind, child_run)` for every child run named in `run.config["child_runs"]`.

    See the module docstring for the prefix-inference rule and the "unreadable child is skipped"
    contract. A `config` with no `child_runs` map (a run from before this field existed, or one
    that never launched a child) yields nothing.
    """
    child_runs = run.config.get("child_runs")
    if not isinstance(child_runs, dict):
        return
    for stage_id, child_id in child_runs.items():
        if not isinstance(stage_id, str) or not isinstance(child_id, str):
            continue
        kind: DeskKind
        if stage_id.startswith("research_"):
            kind = "tradingagents"
        elif stage_id.startswith("vibe_"):
            kind = "vibedesk"
        else:
            continue
        child = RunStore(settings, kind).load(child_id)
        if child is None:
            continue
        yield stage_id, kind, child


def build_workflow_telemetry(run: DeskRun, *, settings: Settings) -> WorkflowRunTelemetry:
    """Token and cost telemetry for one workflow run: its own stages plus every child run it
    launched, per-stage and per-child, with a combined run total.

    Every `CallCostSummary` here degrades independently on a missing/unreadable `AgentCall` or child
    run (see `summarize_calls` and `iter_child_runs`) -- a report, not a ledger, so one bad file costs
    exactly its own contribution, never the whole response.
    """
    own_stages = tuple(
        StageTelemetry(
            stage_id=stage.stage_id,
            label=stage.label,
            summary=summarize_calls(stage.call_ids, settings=settings),
        )
        for stage in run.stages
    )
    all_call_ids: list[str] = [cid for stage in run.stages for cid in stage.call_ids]

    children: list[ChildRunTelemetry] = []
    for stage_id, kind, child in iter_child_runs(run, settings=settings):
        child_call_ids = [cid for child_stage in child.stages for cid in child_stage.call_ids]
        child_stages = tuple(
            StageTelemetry(
                stage_id=child_stage.stage_id,
                label=child_stage.label,
                summary=summarize_calls(child_stage.call_ids, settings=settings),
            )
            for child_stage in child.stages
        )
        children.append(
            ChildRunTelemetry(
                stage_id=stage_id,
                kind=kind,
                run_id=child.run_id,
                stages=child_stages,
                summary=summarize_calls(child_call_ids, settings=settings),
            )
        )
        all_call_ids.extend(child_call_ids)

    return WorkflowRunTelemetry(
        run_id=run.run_id,
        stages=own_stages,
        children=tuple(children),
        total=summarize_calls(all_call_ids, settings=settings),
    )

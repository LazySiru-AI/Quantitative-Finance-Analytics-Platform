"""The swarm executor: runs a preset's task DAG layer by layer against `app.agentdesk`'s shared
grounding and evidence machinery.

**Why tasks within a layer run sequentially, not on a thread pool.** The brief for this module allows
either, on the condition that budget accounting and blocked-propagation stay correct. `AgentBudget` is
frozen -- every call returns a *new* one -- so running a layer's tasks concurrently would require a
lock scoped around each `run_grounded` call (to snapshot-check-and-commit the budget atomically) or a
pre-sliced per-task sub-cap (which either wastes budget headroom one task did not use, or requires a
second, more complex reconciliation pass afterward). Both are solvable, but neither is *simpler* than
threading one `AgentBudget` through a plain loop, and simplicity is what the brief asks this module to
buy correctness with. Model latency, not CPU, dominates a stage's wall time, so the parallelism this
gives up is real wall-clock time, not correctness headroom -- a trade the brief explicitly sanctions
("parallelism within a layer is a nice-to-have; correctness ... is mandatory").

**The three rules from `app.vibedesk`'s own module docstring, and where each is enforced below.**
Rule 1 (summaries, never full reports, downstream) is enforced in `_build_user_turn`, which reads
`_TaskRecord.summary` and never `.report`/`.output_md`. Rule 2 (blocked is not failed) is enforced in
`_blocking_upstream`, checked before a task is ever handed to `run_grounded`. Rule 3 (ground truth
fetched once, up front) is enforced by `_ground_truth` being computed exactly once per run, before the
first layer, and threaded unchanged into every task's prompt.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from dataclasses import dataclass
from decimal import Decimal

from app.agentdesk import evidence
from app.agentdesk.grounding import run_grounded
from app.agentdesk.models import DeskRun, StageRecord
from app.agentdesk.store import RunStore, with_stage
from app.agents.models import AgentBudget, AgentUnavailable, BudgetExhausted
from app.config import Settings
from app.market import livefeed
from app.vibedesk.presets import Preset, PresetTask, load_preset, topological_layers
from app.vibedesk.schemas import WorkerOutput, worker_prose

__all__ = ["DESK_DEFAULT_MODEL", "SwarmConfig", "build_stage_plan", "run_swarm"]

logger = logging.getLogger(__name__)

#: The default worker model for a Vibe Trading run. A preset desk fires one model call per stage across
#: every layer -- a dozen or more on a full committee -- so the default is the cheapest/fastest tier
#: (Haiku 4.5) unless a run selects otherwise via `StartSwarmRequest.model` (the owner's standing
#: preference for these high-volume runs). Mirrors `app.tradingagents.service`'s own `DESK_DEFAULT_MODEL`,
#: the sibling desk that made the same call for the same reason.
DESK_DEFAULT_MODEL = "claude-haiku-4-5-20251001"

#: Stage states that block a dependent task outright, per rule 2 -- see this module's own docstring
#: and `app.agentdesk.models.StageState`'s. `"skipped"` (a configuration outcome, e.g. cancellation
#: reaching a not-yet-started task) blocks a dependent the same way: nothing ran, so there is no
#: summary to hand downstream.
_BLOCKING_STATES = frozenset({"failed", "blocked", "skipped"})


@dataclass(frozen=True)
class SwarmConfig:
    """One run's parameters, exactly what `app.vibedesk.service.start_run` builds from
    `StartSwarmRequest` before handing the run to the job registry."""

    preset_name: str
    symbol: str
    question: str
    variables: dict[str, str]
    budget_usd: Decimal
    model: str = DESK_DEFAULT_MODEL

    live: bool = False
    """Whether this run's shared ground truth also carries the *current* market.

    Defaulted `False` so a run built the way every caller before this feature built one reads exactly
    the sections its preset declared and nothing else. When `True`, `_ground_truth_sections` appends
    `live_quote` and `intraday` to whatever the preset's agents asked for, so every seat in the desk
    sees the same live figures -- rule 3 (ground truth fetched once, up front, shared by every task)
    applies to the live sections the same as to the stored ones. A live run is not reproducible: the
    pack is a photograph of the tape at the moment the run started."""


@dataclass(frozen=True)
class _TaskRecord:
    """What a finished task leaves behind for its dependents and for the run's own bookkeeping."""

    state: str
    summary: str = ""


def build_stage_plan(preset: Preset) -> tuple[StageRecord, ...]:
    """One `StageRecord` per preset task, seated and layered, all `"pending"` -- the initial stage
    list `app.vibedesk.service.start_run` writes into a fresh `DeskRun` before the worker thread
    starts, so the very first poll already shows every stage the run will ever touch.
    """
    label_by_agent = {agent.id: agent.label for agent in preset.agents}
    layers = topological_layers(preset)
    stages: list[StageRecord] = []
    for layer in layers:
        for task in layer:
            stages.append(
                StageRecord(
                    stage_id=task.id,
                    role="swarm_worker",
                    label=label_by_agent[task.agent_id],
                    seat=task.agent_id,
                    state="pending",
                    layer=task.layer,
                    depends_on=task.depends_on,
                )
            )
    return tuple(stages)


#: What a live run adds to a preset's declared sections. Listed here as a set rather than appended as
#: a literal tuple so `_ground_truth_sections`'s single `SECTION_KEYS` ordering pass still decides the
#: order, and so a preset that already declares one of them is not given it twice.
_LIVE_SECTIONS: frozenset[str] = frozenset({"live_quote", "intraday"})


def _ground_truth_sections(preset: Preset, *, live: bool = False) -> tuple[str, ...]:
    """The union of every agent's declared evidence sections, in `evidence.SECTION_KEYS` order --
    deterministic regardless of preset authoring order, and exactly the set rule 3 requires: the
    shared block injected into every prompt must cover whatever any agent in the desk is entitled to
    see, including a synthesiser agent with no evidence sections of its own.

    A live run adds `live_quote` and `intraday` on top, still ordered by `SECTION_KEYS` (where both
    sit last, deliberately -- see `evidence.SECTION_KEYS`'s own comment), so a live run's sections are
    the preset's own with the two live ones appended and nothing reordered.
    """
    declared = {section for agent in preset.agents for section in agent.evidence}
    if live:
        declared |= _LIVE_SECTIONS
    return tuple(key for key in evidence.SECTION_KEYS if key in declared)


def _blocking_upstream(task: PresetTask, results: dict[str, _TaskRecord]) -> tuple[str, ...]:
    """Every dependency of `task` that is in a blocking state. Empty means `task` may run."""
    return tuple(
        dep for dep in task.depends_on if results.get(dep, _TaskRecord(state="blocked")).state in _BLOCKING_STATES
    )


def _format_vars(config: SwarmConfig, preset: Preset) -> dict[str, str]:
    """Preset variable defaults, overridden by the request's own `variables`, with `symbol` and
    `question` always present -- both existing presets' task prompts reference `{symbol}` directly,
    and a preset need not declare it as a formal `variables` entry for that to work."""
    merged = {variable.name: variable.default for variable in preset.variables}
    merged.update(config.variables)
    merged["symbol"] = config.symbol
    merged["question"] = config.question
    return merged


def _build_user_turn(
    *,
    prompt: str,
    task: PresetTask,
    results: dict[str, _TaskRecord],
    ground_truth_md: str,
    question: str = "",
) -> str:
    """The task's own prompt, the run's `question` (when the asker supplied one), the *summaries*
    (never the reports -- rule 1) of whatever it depends on, and the shared ground-truth block, in
    that order.

    The question is injected here, once, for every stage of every preset -- the same way ground truth
    is -- rather than woven into each preset's task prompts: it is a run-level directive that belongs to
    the whole desk, not to any one role, and centralising it means a new preset gets it for free and
    the empty case (`question == ""`, the default when the asker leaves the field blank) is handled in
    exactly one place instead of in every prompt template. An empty question adds no block at all, so a
    stage's turn is byte-for-byte what it was before this existed when no question is asked.

    The guard on figures inside the question is load-bearing, not decoration: the question is free text
    the asker typed and may name numbers the evidence never contained (\"is it worth $350B?\"), and the
    grounding gate checks the stage's *output*, so an agent that echoed such a number would be degraded
    for it. The line tells the agent what the gate already enforces -- the question is framing, not
    evidence -- so it answers the ask without quoting an ungrounded figure back."""
    parts = [prompt]
    if question.strip():
        parts.append(
            "## The desk's question for this run\n\n"
            f"{question.strip()}\n\n"
            "Address it from your own role. Any figure inside the question is the asker's framing, not "
            "evidence: do not state a number from it unless that same number also appears in the Ground "
            "Truth Evidence below."
        )
    for dep_id in task.depends_on:
        record = results.get(dep_id)
        summary = record.summary if record is not None else ""
        parts.append(f"### Summary from `{dep_id}`\n\n{summary}")
    parts.append("## Ground Truth Evidence\n\n" + ground_truth_md)
    return "\n\n".join(parts)


def run_swarm(run_id: str, config: SwarmConfig, *, settings: Settings, cancel: threading.Event) -> None:
    """The job target: drive one preset's DAG to completion (or cancellation), saving a new `DeskRun`
    snapshot after every stage transition so a poll landing mid-run always sees current progress.

    Assumes `run_id` already has a persisted `DeskRun` (written by `app.vibedesk.service.start_run`)
    whose `stages` match `build_stage_plan(preset)` exactly -- this function only ever transitions
    those stages, it never invents or drops one.
    """
    store = RunStore(settings, "vibedesk")
    run = store.load(run_id)
    if run is None:  # pragma: no cover - defensive; service.start_run always saves before starting
        return

    run = run.model_copy(update={"state": "running"})
    store.save(run)

    preset = load_preset(config.preset_name)
    layers = topological_layers(preset)

    if config.live:
        # Best-effort, exactly as `app.tradingagents.pipeline.run_pipeline` does it: `watch` only asks
        # the keep-warm daemon to hold this symbol open from its next tick, so a failure here (or a
        # daemon that is not running, the default) costs a cold synchronous fetch, not the run.
        try:
            livefeed.watch([config.symbol])
        except Exception:
            logger.warning("vibedesk: could not watch %s for a live run", config.symbol, exc_info=True)

    ground_truth_pack = evidence.build_pack(
        config.symbol, None, settings=settings, sections=_ground_truth_sections(preset, live=config.live)
    )
    ground_truth_md = evidence.render_pack(ground_truth_pack)
    fmt_vars = _format_vars(config, preset)
    agents_by_id = {agent.id: agent for agent in preset.agents}

    results: dict[str, _TaskRecord] = {}
    budget = run.budget
    degraded = False
    any_failed = False

    for layer in layers:
        if cancel.is_set():
            for pending_layer in layers:
                for task in pending_layer:
                    if task.id in results:
                        continue
                    run = with_stage(run, task.id, state="skipped", error="run cancelled")
                    results[task.id] = _TaskRecord(state="skipped")
            run = run.model_copy(
                update={"state": "cancelled", "budget": budget, "completed_at": dt.datetime.now(dt.UTC)}
            )
            store.save(run)
            return

        for task in layer:
            blockers = _blocking_upstream(task, results)
            if blockers:
                detail = ", ".join(blockers)
                run = with_stage(run, task.id, state="blocked", error=f"blocked by upstream: {detail}")
                results[task.id] = _TaskRecord(state="blocked")
                store.save(run)
                continue

            agent = agents_by_id[task.agent_id]
            started_at = dt.datetime.now(dt.UTC)
            run = with_stage(run, task.id, state="running", started_at=started_at)
            store.save(run)

            if budget.exhausted:
                run = with_stage(
                    run, task.id, state="failed", error="agent budget exhausted before this stage ran",
                    completed_at=dt.datetime.now(dt.UTC),
                )
                results[task.id] = _TaskRecord(state="failed")
                any_failed = True
                store.save(run)
                continue

            prompt = task.prompt.format(**fmt_vars)
            user = _build_user_turn(
                prompt=prompt,
                task=task,
                results=results,
                ground_truth_md=ground_truth_md,
                question=config.question,
            )

            try:
                result = run_grounded(
                    role="swarm_worker",
                    system=agent.system,
                    user=user,
                    output_format=WorkerOutput,
                    prose_of=worker_prose,
                    # Ground against the *shared ground truth the agent was actually shown*, not this
                    # agent's own narrower `evidence` sections. `_ground_truth_sections` injects the
                    # union of every agent's evidence into every prompt (so a synthesiser with no
                    # sections of its own still sees data), and a stage cannot fairly be degraded for
                    # citing a figure the prompt handed it under "Ground Truth Evidence". A risk officer
                    # scoped to price+indicators is still shown, and may cite, the balance-sheet figures
                    # the committee's advocates need -- grading it against only its own two sections
                    # rejected it for reading the evidence block it was given.
                    pack=ground_truth_pack,
                    settings=settings,
                    budget=budget,
                    model=config.model,
                )
            except BudgetExhausted as exc:
                # `exc.spent_usd` reflects whatever earlier retry attempts inside this task's own
                # `run_grounded` call already spent before the ceiling was hit -- `call_structured`
                # raises against its own `budget` argument, which by the time of a later attempt is
                # `run_grounded`'s already-updated running total, not the value this task started
                # with. Recovering it here keeps the run's accounted spend accurate even when a task
                # fails partway through its own retry loop.
                budget = AgentBudget(cap_usd=exc.cap_usd, spent_usd=exc.spent_usd, calls=budget.calls)
                run = with_stage(
                    run, task.id, state="failed", error=str(exc), completed_at=dt.datetime.now(dt.UTC)
                )
                results[task.id] = _TaskRecord(state="failed")
                any_failed = True
                run = run.model_copy(update={"budget": budget})
                store.save(run)
                continue
            except AgentUnavailable as exc:
                # No cost was incurred: `call_structured` raises `AgentUnavailable` for every
                # transport/auth failure before a response exists to archive or price -- see its own
                # docstring. Budget is left untouched.
                run = with_stage(
                    run, task.id, state="failed", error=str(exc), completed_at=dt.datetime.now(dt.UTC)
                )
                results[task.id] = _TaskRecord(state="failed")
                any_failed = True
                store.save(run)
                continue

            budget = result.budget
            stage_state = "succeeded" if result.verdict.ok else "degraded"
            if stage_state == "degraded":
                degraded = True
            cost = sum((call.cost_usd for call in result.calls), Decimal(0))
            run = with_stage(
                run,
                task.id,
                state=stage_state,
                completed_at=dt.datetime.now(dt.UTC),
                output_md=result.value.report,
                summary=result.value.summary,
                grounding=result.verdict,
                call_ids=tuple(call.call_id for call in result.calls),
                cost_usd=cost,
            )
            results[task.id] = _TaskRecord(state=stage_state, summary=result.value.summary)
            run = run.model_copy(update={"budget": budget})
            store.save(run)

    final_md = _compose_final_md(layers[-1] if layers else (), run)
    run = run.model_copy(
        update={
            "state": "failed" if any_failed else "succeeded",
            "final_md": final_md,
            "degraded": degraded,
            "budget": budget,
            "completed_at": dt.datetime.now(dt.UTC),
            "error": "one or more stages failed" if any_failed else "",
        }
    )
    store.save(run)


def _compose_final_md(last_layer: tuple[PresetTask, ...], run: DeskRun) -> str:
    """The run's report: the last topological layer's task output(s). A single task's `output_md` is
    used verbatim; more than one is concatenated under a heading per stage so a reader can tell which
    part came from which seat."""
    stages_by_id = {stage.stage_id: stage for stage in run.stages}
    outputs = []
    for task in last_layer:
        stage = stages_by_id.get(task.id)
        if stage is None:
            continue
        if stage.output_md:
            outputs.append((stage.label, stage.output_md))
        elif stage.error:
            outputs.append((stage.label, f"_{stage.state}: {stage.error}_"))

    if not outputs:
        return ""
    if len(outputs) == 1:
        return outputs[0][1]
    return "\n\n".join(f"## {label}\n\n{output_md}" for label, output_md in outputs)

"""Layer C's orchestrator: one manager brief is one `DeskRun` of six fixed stages -- `collect`,
`triage`, `synthesis`, `research_plan`, `commission`, `brief` -- mirroring `app.tradingagents.pipeline`'s
own shape (`build_stage_plan` / a job-registry target that walks `DeskRun.stages` in order, persisting a
new snapshot via `RunStore` + `with_stage` after every transition so a poll landing mid-run always sees a
consistent picture) but with a fixed six-stage sequence rather than a dynamically-sized one, since the
manager's stage list never varies with its config the way TradingAgents' does with analyst selection or
debate-round count.

**Two stages are deterministic, four are grounded.** `collect` reads the application (via
`app.manager.sources.collect`), persists the day's `ManagerSnapshot` (`app.manager.snapshots.save`) and
diffs it against the nearest prior one (`app.manager.rules.diff`) -- no model call, cannot degrade, and
(per the module docstring on `app.manager.sources`) does not raise past its own boundary except for a
disk-write failure, which this module treats as a stage failure like any other. `commission` is a
propose-only no-op in this worker: `research_plan` already wrote the `Commission` proposals, and
executing one (spawning a child `tradingagents`/`vibedesk`/`workflow`/`persona_chat` run) is the owner's
own approval action elsewhere, never something this pipeline does unattended. `triage`, `synthesis` and
`research_plan` are grounded exactly as every other desk stage is: `app.agentdesk.grounding.run_grounded`
checks every numeric token in the model's prose against an `EvidencePack`
(`app.manager.evidence.build_pack`) and releases the stage `"degraded"`, never raises, when the check
still fails after its retries -- carried through onto `DeskRun.degraded` and, at the end, `Brief.degraded`.

**The not-advice guarantee is structural, not just a prompt instruction.** `Synthesis`
(`app.manager.models.Synthesis`) has no field an account instruction could occupy -- see its own
docstring -- so the internal `_SynthesisDraft` this module asks the model to fill has none either; the
system prompt is the second half of the guarantee, forbidding the model from writing one in prose.

**Citations are ours to enforce, never the model's to self-police**, following
`app.personas.ask._filter_citations`'s precedent: every `citations` field a grounded stage returns is a
`ChangeItem.id` copied from the tagged list the model was shown, filtered against the *actual* change set
before anything downstream ever sees it, and translated into the cited change's own already-curated
`source_refs` -- never trusted or re-synthesised from whatever a model claims a source is.

**Spend is bounded on two axes.** `AgentBudget(cap_usd=cfg.cap_usd)` threads through the run exactly as
`app.tradingagents.pipeline` threads its own (`run_grounded` raises `BudgetExhausted` when it would be
exceeded, which fails the stage and blocks everything after it). Independently, `app.agents.spend.LEDGER`
-- the same rolling 24h aggregate ceiling `app.i18n.narrative` and the persona routes check -- is checked
*before* every grounded stage; `SpendCapExceeded` fails the run the same way a mid-call budget exhaustion
does, without ever attempting the call.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agentdesk.evidence import render_pack as render_evidence_pack
from app.agentdesk.grounding import run_grounded
from app.agentdesk.models import DeskRun, EvidencePack, GroundingVerdict, StageRecord, StageState
from app.agentdesk.store import RunStore, with_stage
from app.agents.models import (
    DEFAULT_MODEL,
    AgentBudget,
    AgentRole,
    AgentUnavailable,
    BudgetExhausted,
)
from app.agents.spend import LEDGER, SpendCapExceeded
from app.config import Settings
from app.manager import snapshots
from app.manager.evidence import build_pack
from app.manager.models import (
    MANAGER_STAGES,
    Brief,
    BriefBullet,
    ChangeItem,
    ChangeSet,
    Commission,
    CommissionKind,
    DataHealth,
    ManagerSnapshot,
    Scope,
    Severity,
    SourceRef,
    Synthesis,
    Window,
    manager_dir,
)
from app.manager.rules import diff
from app.manager.sources import collect

__all__ = ["CAVEAT", "ManagerConfig", "build_stage_plan", "latest_brief", "load_brief", "run_manager_brief"]

logger = logging.getLogger(__name__)

#: The fixed, situation-only caveat every `Synthesis` carries -- see `Synthesis.caveat`'s own docstring
#: on `app.manager.models`, which points back here by name.
CAVEAT = (
    "A model's synthesis of this application's own lenses -- descriptive, point-in-time, not investment "
    "advice; the app's own research has found no measured edge."
)

#: Every grounded call in this module archives under `swarm_worker`, matching `app.personas`'s own
#: reasoning (see `app.personas.summarize._ROLE`'s docstring) -- the manager is one more preset-free
#: caller of the shared grounding gate, not a role of its own worth widening `AgentRole` for.
_ROLE: AgentRole = "swarm_worker"

#: Placeholder per-commission budget a proposed (not yet approved) `Commission` carries. This worker
#: never spends it -- `research_plan` only proposes, `commission` passes the proposal through unexecuted
#: -- so the figure is informational for the owner's approval screen, not a cap enforced here.
_DEFAULT_COMMISSION_BUDGET_USD = Decimal("1")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ManagerConfig:
    """One brief's parameters. Deliberately **not** `app.manager.models.ManagerConfig` -- that is the
    wire shape for the tab's landing state (caps, autonomy, autopilot), a different thing entirely; this
    is the plain, internal argument bundle `run_manager_brief` takes, mirroring
    `app.tradingagents.pipeline.PipelineConfig`'s own role for that desk."""

    window: Window
    date: dt.date | None
    scope: Scope
    model: str = DEFAULT_MODEL
    synthesis_model: str = ""
    cap_usd: Decimal = Decimal("3")
    daily_cap_usd: Decimal = Decimal("0")

    @property
    def effective_synthesis_model(self) -> str:
        """`synthesis_model` when set, else the run's own `model` -- so a caller need not repeat itself
        to get one model for every stage."""
        return self.synthesis_model or self.model


# ---------------------------------------------------------------------------
# The stage plan
# ---------------------------------------------------------------------------

_STAGE_LABELS: dict[str, str] = {
    "collect": "Collect",
    "triage": "Triage",
    "synthesis": "Synthesis",
    "research_plan": "Research Plan",
    "commission": "Commission",
    "brief": "Brief",
}


def build_stage_plan() -> tuple[StageRecord, ...]:
    """The six `MANAGER_STAGES`, all `"pending"`, chained collect -> triage -> synthesis ->
    research_plan -> commission -> brief -- one `depends_on` predecessor each, exactly as
    `app.tradingagents.pipeline.build_stage_plan` chains its own strict sequence. `seat` is always
    empty (manager stages are not VibeDesk preset seats); `role` is `swarm_worker` for every stage,
    including the two deterministic ones, so a caller does not need a stage-kind check just to render a
    role label -- `StageRecord.grounding` staying `None` on `collect`/`commission` is what actually
    distinguishes them.
    """
    stages: list[StageRecord] = []
    previous_id: str | None = None
    for layer, stage_id in enumerate(MANAGER_STAGES):
        depends_on = (previous_id,) if previous_id is not None else ()
        stages.append(
            StageRecord(
                stage_id=stage_id,
                role=_ROLE,
                label=_STAGE_LABELS[stage_id],
                seat="",
                layer=layer,
                depends_on=depends_on,
            )
        )
        previous_id = stage_id
    return tuple(stages)


# ---------------------------------------------------------------------------
# Model output shapes -- internal drafts, never the wire models themselves
# ---------------------------------------------------------------------------


class _TriageItem(_Frozen):
    change_id: str
    severity: Severity
    headline: str = Field(max_length=160)


class _TriageDraft(_Frozen):
    items: tuple[_TriageItem, ...] = ()


class _BulletDraft(_Frozen):
    text: str
    citations: tuple[str, ...] = ()


class _SynthesisDraft(_Frozen):
    """What the synthesis stage returns. **No field here can hold an account instruction** -- the
    structural half of the not-advice guarantee `Synthesis` itself documents; the system prompt is the
    other half. Adding any field named toward action (a recommendation, a suggested trade, a rating) to
    this model would break that guarantee at the type level, which is exactly why it must never happen."""

    assessment: tuple[_BulletDraft, ...] = ()
    agreements: tuple[_BulletDraft, ...] = ()
    conflicts: tuple[_BulletDraft, ...] = ()
    risks: tuple[_BulletDraft, ...] = ()
    open_questions: tuple[_BulletDraft, ...] = ()


class _CommissionDraft(_Frozen):
    kind: CommissionKind
    params: dict[str, Any] = Field(default_factory=dict)
    rationale: str
    citations: tuple[str, ...] = ()


class _ResearchPlanDraft(_Frozen):
    commissions: tuple[_CommissionDraft, ...] = Field(default_factory=tuple, max_length=3)


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------

_TRIAGE_SYSTEM = """You are the manager desk's triage stage for a private, single-user investing \
dashboard. You are given a list of changes this application's own rules already detected across its own \
data (the account, tax, paper-trading desks, research, personas, market and more). Your ONLY job is to \
rank each one by how much attention it deserves and write a short headline for it -- you never add a \
fact that is not already in the evidence below, you never speculate about a cause the evidence does not \
show, and you never suggest what the reader should do about any of it.

SEVERITY. For every change_id listed below, assign exactly one of "attention" (worth a look today), \
"notable" (worth knowing, not urgent), or "fyi" (background only). You may keep, raise, or lower the \
severity the deterministic rule already suggested -- use judgment about what is actually material here, \
not just what number crossed a threshold. Every change_id given to you must appear exactly once in your \
answer.

GROUNDING. Every number in your headline must appear in the evidence below, or be a straightforward \
difference or percentage change computed directly from two figures that do. Never estimate, round to a \
plausible figure, or otherwise invent one.

CHANGE_ID. Copy `change_id` verbatim from the "change_id:" tag shown for each change below -- never \
invent one.

HEADLINE. At most 160 characters. Dense and factual; no editorializing about what the reader should do.

Respond with only the fields the schema asks for -- no extra commentary before or after."""

_SYNTHESIS_SYSTEM = """You are the manager desk's synthesis stage for a private, single-user investing \
dashboard. You read the changes detected in this window across this application's own data and write a \
plain situation assessment: what happened, where different parts of the picture agree, where they \
conflict, what the risks are, and what genuinely remains unclear. You are NOT a financial advisor and \
this is NOT investment advice. You never tell the reader what to buy, sell, hold, rebalance, or otherwise \
do with their account, and you never suggest a specific action even indirectly -- no "consider", no "you \
may want to", no implied next step. Describe the situation as it stands; let the reader draw their own \
conclusions. If you find yourself about to write an instruction, stop and rewrite it as a plain \
observation or an open question instead.

GROUNDING. Every number you write must appear in the evidence below, or be a straightforward difference \
or percentage change computed directly from two figures that do. Never estimate or invent one. If the \
evidence genuinely gives you nothing for a section (for example, nothing that reads as a real conflict), \
leave that section's bullets empty rather than manufacturing content to fill it.

CITATIONS. Cite what each bullet drew on in its `citations` field, copied verbatim, using EITHER an \
exact `change_id` from a change's "change_id:" tag, OR the name of a snapshot area it relies on -- the \
lower-case word after "State:" in an EVIDENCE section heading (e.g. account, tax, persona_traders, \
research). Prefer a `change_id` when the bullet is about a specific change; cite the area when the \
bullet is about the current state of that section. Never invent either, and never cite one the bullet \
does not actually rely on.

Respond with only the fields the schema asks for -- no extra commentary before or after."""

_RESEARCH_PLAN_SYSTEM = """You are the manager desk's research-plan stage for a private, single-user \
investing dashboard. Based only on the changes and evidence below, propose between 0 and 3 follow-up \
research commissions the owner could choose to run -- you never execute anything yourself, you never \
tell the reader what to do with their account, and an empty list is a completely acceptable answer when \
nothing below actually warrants further research.

Each commission's `kind` must be exactly one of: "tradingagents" (a single-symbol deep research/decision \
run), "vibedesk" (an open-ended research swarm), "workflow" (a staged regime/research/plan pipeline), or \
"persona_chat" (a question to one of this application's influencer personas). `params` are that tool's \
own free-form request fields (for example a `symbol`) -- keep it minimal and only what the kind actually \
needs. `rationale` states, in your own words, what open question this commission would help answer and \
why it is worth the owner's time and money to run, referencing the evidence.

GROUNDING. Every number in `rationale` must appear in the evidence below, or be a straightforward \
difference or percentage change computed directly from two figures that do.

CITATIONS. Cite what each commission's rationale drew on in its `citations` field, copied verbatim, \
using EITHER an exact `change_id` from a change's tag OR the name of a snapshot area (the word after \
"State:" in an EVIDENCE section heading, e.g. account, personas, research). Never invent either.

Respond with only the fields the schema asks for -- no extra commentary before or after."""


def _render_changes_for_prompt(changes: ChangeSet) -> str:
    """Every `ChangeItem` in `changes`, tagged with its own `change_id` so a stage can cite it back
    verbatim -- the same tagged-block idiom `app.personas.ask._render_note` uses for `note_id`."""
    if not changes.items:
        return "(no changes were detected in this window)"
    blocks = [
        f"change_id: {item.id}\n"
        f"area: {item.area} | rule: {item.rule} | detected severity: {item.severity}\n"
        f"headline: {item.headline}\n"
        f"detail: {item.detail or '(none)'}"
        for item in changes.items
    ]
    return "\n\n".join(blocks)


def _prose_of_triage(draft: _TriageDraft) -> str:
    return "\n".join(item.headline for item in draft.items)


def _prose_of_synthesis(draft: _SynthesisDraft) -> str:
    bullets = (
        *draft.assessment, *draft.agreements, *draft.conflicts, *draft.risks, *draft.open_questions,
    )
    return "\n".join(b.text for b in bullets)


def _prose_of_research_plan(draft: _ResearchPlanDraft) -> str:
    return "\n".join(c.rationale for c in draft.commissions)


# ---------------------------------------------------------------------------
# Citation filtering -- ours to enforce, never the model's to self-police
# ---------------------------------------------------------------------------


def _resolve_citations(
    citations: tuple[str, ...], *, changes: ChangeSet, snapshot: ManagerSnapshot, stage: str,
) -> tuple[SourceRef, ...]:
    """Turn a grounded stage's `citations` into `SourceRef`s, accepting two kinds of id -- never
    repairing an invalid one, mirroring `app.personas.ask._filter_citations`'s drop-don't-repair rule.

    A `ChangeItem.id` resolves to that change's own already-curated `source_refs` (a delta the reader
    can jump to). A snapshot AREA key (`"account"`, `"persona_traders"`, ... -- shown to the model as
    the word after "State:" in the evidence pack) resolves to one `SourceRef(kind="snapshot", ...)`
    naming that section, so a bullet that draws on the current *state* rather than on a diff still
    carries provenance instead of an empty chip. Anything outside both sets is dropped and logged.
    Deduplicated by `(kind, id)`, first-seen order.
    """
    change_by_id = {item.id: item for item in changes.items}
    ok_areas = {section.key for section in snapshot.sections if section.ok}
    seen: dict[tuple[str, str], SourceRef] = {}
    dropped: list[str] = []
    for citation in citations:
        change = change_by_id.get(citation)
        if change is not None:
            for ref in change.source_refs:
                seen[(ref.kind, ref.id)] = ref
        elif citation in ok_areas:
            ref = SourceRef(kind="snapshot", id=citation, label=citation.replace("_", " "))
            seen[(ref.kind, ref.id)] = ref
        else:
            dropped.append(citation)
    if dropped:
        logger.warning(
            "manager pipeline(%s): dropped %d citation(s) outside changes+snapshot areas: %s",
            stage, len(dropped), ", ".join(dropped),
        )
    return tuple(seen.values())


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# One grounded stage: call, grade, persist -- mirrors
# app.tradingagents.pipeline._run_role_stage
# ---------------------------------------------------------------------------


def _run_grounded_stage[T: BaseModel](
    run: DeskRun,
    store: RunStore,
    stage_id: str,
    *,
    system: str,
    user: str,
    pack: EvidencePack,
    output_format: type[T],
    prose_of: Callable[[T], str],
    settings: Settings,
    budget: AgentBudget,
    model: str,
) -> tuple[DeskRun, AgentBudget, T, GroundingVerdict]:
    """Run one grounded stage's call and persist its outcome, in the same two-save shape
    `app.tradingagents.pipeline._run_role_stage` uses: one marking the stage `"running"` (visible to a
    poll mid-call), one recording the result. Raises `BudgetExhausted`/`AgentUnavailable` straight
    through -- this function never marks the stage `"failed"` itself; `run_manager_brief` does, once it
    has the exception's own `spent_usd` for `BudgetExhausted`."""
    run = with_stage(run, stage_id, state="running", started_at=dt.datetime.now(dt.UTC))
    store.save(run)

    result = run_grounded(
        role=_ROLE, system=system, user=user, output_format=output_format, prose_of=prose_of,
        pack=pack, settings=settings, budget=budget, model=model,
    )

    state: StageState = "succeeded" if result.verdict.ok else "degraded"
    cost = sum((call.cost_usd for call in result.calls), Decimal(0))
    run = with_stage(
        run, stage_id, state=state, completed_at=dt.datetime.now(dt.UTC),
        summary=_clip(prose_of(result.value) or "(no prose)", 280),
        output_md=prose_of(result.value),
        grounding=result.verdict, call_ids=tuple(c.call_id for c in result.calls), cost_usd=cost,
    )
    run_update: dict[str, object] = {"budget": result.budget}
    if state == "degraded":
        run_update["degraded"] = True
    run = run.model_copy(update=run_update)
    store.save(run)
    return run, result.budget, result.value, result.verdict


def _mark_stages(run: DeskRun, stage_ids: list[str], *, state: StageState, error: str = "") -> DeskRun:
    for stage_id in stage_ids:
        run = with_stage(run, stage_id, state=state, error=error)
    return run


def _fail_run(
    run: DeskRun, store: RunStore, stage_id: str, error: str, stage_ids: list[str],
    *, budget: AgentBudget | None = None,
) -> None:
    """Mark `stage_id` `"failed"`, every stage after it `"blocked"`, and the run itself `"failed"` --
    the same terminal shape `app.tradingagents.pipeline.run_pipeline` leaves behind on a hard stage
    failure."""
    index = stage_ids.index(stage_id)
    run = with_stage(run, stage_id, state="failed", error=error, completed_at=dt.datetime.now(dt.UTC))
    run = _mark_stages(
        run, stage_ids[index + 1 :], state="blocked",
        error="blocked: an earlier stage in the manager pipeline failed",
    )
    update: dict[str, object] = {
        "state": "failed", "error": error, "completed_at": dt.datetime.now(dt.UTC),
    }
    if budget is not None:
        update["budget"] = budget
    run = run.model_copy(update=update)
    store.save(run)


def _handle_cancel(
    run: DeskRun, store: RunStore, stage_ids: list[str], index: int, cancel: threading.Event,
) -> bool:
    """`True` (after persisting the cancelled run) when `cancel` was set before stage `stage_ids[index]`
    could start -- every stage from `index` onward is marked `"skipped"`, matching
    `app.tradingagents.pipeline.run_pipeline`'s own cancellation handling."""
    if not cancel.is_set():
        return False
    run = _mark_stages(run, stage_ids[index:], state="skipped", error="run cancelled")
    run = run.model_copy(update={"state": "cancelled", "completed_at": dt.datetime.now(dt.UTC)})
    store.save(run)
    return True


# ---------------------------------------------------------------------------
# Stage: collect (deterministic)
# ---------------------------------------------------------------------------


def _stage_collect(
    run: DeskRun, store: RunStore, cfg: ManagerConfig, *, settings: Settings,
) -> tuple[DeskRun, ManagerSnapshot, ChangeSet]:
    """Read the application, persist today's snapshot, and diff it against the nearest prior one. No
    model call; cannot degrade. `"week"` anchors `previous` strictly before `date - 7 days`; every other
    window anchors strictly before `date` itself -- the same rule the brief pins, a simpler cousin of
    `app.manager.service.changes`'s own `"week"` handling (that function additionally falls back to the
    oldest available snapshot when nothing is that old; this stage does not, since a brief with no prior
    snapshot to compare against is itself informative -- a streams-only `ChangeSet` -- rather than
    something to paper over with a closer-than-requested comparison)."""
    run = with_stage(run, "collect", state="running", started_at=dt.datetime.now(dt.UTC))
    store.save(run)

    resolved_date = cfg.date if cfg.date is not None else dt.date.today()
    snap = collect(settings, scope=cfg.scope, as_of=resolved_date)
    snapshots.save(settings, snap)

    anchor = resolved_date - dt.timedelta(days=7) if cfg.window == "week" else resolved_date
    previous = snapshots.latest(settings, cfg.scope, before=anchor)
    prior_snapshot = previous.as_of if previous is not None else None

    changes = diff(snap, previous, window=cfg.window, prior_snapshot=prior_snapshot)

    summary = f"{len(changes.items)} change(s) detected"
    if changes.sections_missing:
        summary += f"; {len(changes.sections_missing)} section(s) missing"
    run = with_stage(
        run, "collect", state="succeeded", completed_at=dt.datetime.now(dt.UTC),
        summary=_clip(summary, 280),
        output_md=f"Collected snapshot as of {snap.as_of} ({cfg.scope}). {summary}.",
    )
    store.save(run)
    return run, snap, changes


# ---------------------------------------------------------------------------
# Stage: triage (grounded)
# ---------------------------------------------------------------------------


def _stage_triage(
    run: DeskRun, store: RunStore, snap: ManagerSnapshot, changes: ChangeSet, cfg: ManagerConfig,
    *, settings: Settings, budget: AgentBudget,
) -> tuple[DeskRun, AgentBudget, ChangeSet, tuple[ChangeItem, ...], GroundingVerdict]:
    """Rank `changes.items` into severity + a headline, merge the (citation-checked) result back onto
    the `ChangeItem`s, and return the merged `ChangeSet` plus the `attention` list -- every `ChangeItem`
    whose *post-merge* severity is `"attention"`. A change_id the model never mentioned (or mentioned
    with an invalid change_id) simply keeps the severity the deterministic rule already gave it."""
    pack = build_pack(snap, changes)
    user = (
        f"CHANGES:\n{_render_changes_for_prompt(changes)}\n\n"
        f"EVIDENCE:\n{render_evidence_pack(pack)}"
    )
    run, budget, draft, verdict = _run_grounded_stage(
        run, store, "triage", system=_TRIAGE_SYSTEM, user=user, pack=pack,
        output_format=_TriageDraft, prose_of=_prose_of_triage,
        settings=settings, budget=budget, model=cfg.model,
    )

    valid_ids = frozenset(item.id for item in changes.items)
    dropped = [t.change_id for t in draft.items if t.change_id not in valid_ids]
    if dropped:
        logger.warning(
            "manager pipeline(triage): dropped %d change_id(s) outside the change set: %s",
            len(dropped), ", ".join(dropped),
        )

    overrides = {t.change_id: t for t in draft.items if t.change_id in valid_ids}
    merged_items = tuple(
        item.model_copy(update={"severity": overrides[item.id].severity, "headline": overrides[item.id].headline})
        if item.id in overrides else item
        for item in changes.items
    )
    merged_changes = changes.model_copy(update={"items": merged_items})
    attention = tuple(item for item in merged_items if item.severity == "attention")

    return run, budget, merged_changes, attention, verdict


# ---------------------------------------------------------------------------
# Stage: synthesis (grounded)
# ---------------------------------------------------------------------------


def _stage_synthesis(
    run: DeskRun, store: RunStore, snap: ManagerSnapshot, changes: ChangeSet, cfg: ManagerConfig,
    *, settings: Settings, budget: AgentBudget,
) -> tuple[DeskRun, AgentBudget, Synthesis, GroundingVerdict]:
    pack = build_pack(snap, changes)
    user = (
        f"CHANGES:\n{_render_changes_for_prompt(changes)}\n\n"
        f"EVIDENCE:\n{render_evidence_pack(pack)}"
    )
    run, budget, draft, verdict = _run_grounded_stage(
        run, store, "synthesis", system=_SYNTHESIS_SYSTEM, user=user, pack=pack,
        output_format=_SynthesisDraft, prose_of=_prose_of_synthesis,
        settings=settings, budget=budget, model=cfg.effective_synthesis_model,
    )

    def _bullets(drafts: tuple[_BulletDraft, ...]) -> tuple[BriefBullet, ...]:
        out: list[BriefBullet] = []
        for b in drafts:
            refs = _resolve_citations(b.citations, changes=changes, snapshot=snap, stage="synthesis")
            out.append(BriefBullet(text=b.text, source_refs=refs))
        return tuple(out)

    synthesis = Synthesis(
        assessment=_bullets(draft.assessment),
        agreements=_bullets(draft.agreements),
        conflicts=_bullets(draft.conflicts),
        risks=_bullets(draft.risks),
        open_questions=_bullets(draft.open_questions),
        caveat=CAVEAT,
    )
    return run, budget, synthesis, verdict


# ---------------------------------------------------------------------------
# Stage: research_plan (grounded)
# ---------------------------------------------------------------------------


def _stage_research_plan(
    run: DeskRun, store: RunStore, snap: ManagerSnapshot, changes: ChangeSet, cfg: ManagerConfig,
    *, settings: Settings, budget: AgentBudget,
) -> tuple[DeskRun, AgentBudget, tuple[Commission, ...], GroundingVerdict]:
    pack = build_pack(snap, changes)
    user = (
        f"CHANGES:\n{_render_changes_for_prompt(changes)}\n\n"
        f"EVIDENCE:\n{render_evidence_pack(pack)}"
    )
    run, budget, draft, verdict = _run_grounded_stage(
        run, store, "research_plan", system=_RESEARCH_PLAN_SYSTEM, user=user, pack=pack,
        output_format=_ResearchPlanDraft, prose_of=_prose_of_research_plan,
        settings=settings, budget=budget, model=cfg.model,
    )

    commissions: list[Commission] = []
    for cdraft in draft.commissions[:3]:
        refs = _resolve_citations(cdraft.citations, changes=changes, snapshot=snap, stage="research_plan")
        commissions.append(
            Commission(
                commission_id=uuid.uuid4().hex,
                kind=cdraft.kind,
                params=dict(cdraft.params),
                rationale=cdraft.rationale,
                budget_usd=str(_DEFAULT_COMMISSION_BUDGET_USD),
                state="proposed",
                source_refs=refs,
            )
        )
    return run, budget, tuple(commissions), verdict


# ---------------------------------------------------------------------------
# Stage: commission (deterministic pass-through -- Phase 1 of this worker is propose-only)
# ---------------------------------------------------------------------------


def _stage_commission(run: DeskRun, store: RunStore, commissions: tuple[Commission, ...]) -> DeskRun:
    """Leave `commissions` exactly as `research_plan` proposed them (`state="proposed"`) -- executing
    one is a later, owner-approved action (the approve endpoint / a commission runner), never something
    this pipeline starts on its own. This stage exists in the run's stage list purely so the run's own
    timeline shows the review point explicitly, matching `MANAGER_STAGES`'s own six-stage shape."""
    run = with_stage(run, "commission", state="running", started_at=dt.datetime.now(dt.UTC))
    store.save(run)

    if commissions:
        note = (
            f"{len(commissions)} commission(s) proposed; execution requires explicit owner approval and "
            "is not started automatically by this run."
        )
    else:
        note = "No research commissions were proposed for this window."

    run = with_stage(
        run, "commission", state="succeeded", completed_at=dt.datetime.now(dt.UTC),
        summary=note, output_md=note,
    )
    store.save(run)
    return run


# ---------------------------------------------------------------------------
# Stage: brief (assembly, no model call)
# ---------------------------------------------------------------------------


def _data_health(snap: ManagerSnapshot) -> DataHealth:
    """Read straight off the `data` section's own `SnapshotSection.items[].text`, which
    `app.manager.sources_research.data_section` always writes as `"<status>: <detail>"` for
    `status in {"stale", "unknown", ...}` -- see that module. Empty when the section is absent or failed
    to collect, never a guess."""
    section = snap.section("data")
    if section is None or not section.ok:
        return DataHealth()
    stale = tuple(item.id for item in section.items if item.text.lower().startswith("stale"))
    unknown = tuple(item.id for item in section.items if item.text.lower().startswith("unknown"))
    return DataHealth(stale=stale, unknown=unknown)


def _aggregate_grounding(verdicts: list[GroundingVerdict]) -> GroundingVerdict:
    """One `GroundingVerdict` standing in for the whole brief's three grounded stages: `ok` only if
    every stage's own check passed, `degraded` if any did not, every issue carried through named, and
    `checked_tokens` summed so the figure means "how much was actually verified across this brief",
    not just the last stage's own count."""
    if not verdicts:
        return GroundingVerdict(ok=True, checked_tokens=0)
    return GroundingVerdict(
        ok=all(v.ok for v in verdicts),
        issues=tuple(issue for v in verdicts for issue in v.issues),
        attempts=sum(v.attempts for v in verdicts),
        degraded=any(v.degraded for v in verdicts),
        checked_tokens=sum(v.checked_tokens for v in verdicts),
    )


def _render_final_md(
    *, cfg: ManagerConfig, snap: ManagerSnapshot, attention: tuple[ChangeItem, ...],
    synthesis: Synthesis, commissions: tuple[Commission, ...], data_health: DataHealth, degraded: bool,
) -> str:
    lines = [f"# Manager brief -- {snap.as_of} ({cfg.scope}, {cfg.window})"]
    if degraded:
        lines.append("\n_Some stages of this brief could not be fully grounded; treat with extra care._")

    lines.append("\n## Attention")
    if attention:
        lines.extend(f"- **[{item.area}]** {item.headline}" for item in attention)
    else:
        lines.append("- Nothing rose to attention this window.")

    def _section(title: str, bullets: tuple[BriefBullet, ...]) -> None:
        lines.append(f"\n## {title}")
        if bullets:
            lines.extend(f"- {b.text}" for b in bullets)
        else:
            lines.append("- (none)")

    _section("Assessment", synthesis.assessment)
    _section("Agreements", synthesis.agreements)
    _section("Conflicts", synthesis.conflicts)
    _section("Risks", synthesis.risks)
    _section("Open questions", synthesis.open_questions)

    lines.append("\n## Proposed research")
    if commissions:
        lines.extend(f"- **{c.kind}**: {c.rationale} (${c.budget_usd}, {c.state})" for c in commissions)
    else:
        lines.append("- None proposed this window.")

    if data_health.stale or data_health.unknown:
        lines.append("\n## Data health")
        if data_health.stale:
            lines.append(f"- Stale: {', '.join(data_health.stale)}")
        if data_health.unknown:
            lines.append(f"- Unknown: {', '.join(data_health.unknown)}")

    lines.append(f"\n---\n{synthesis.caveat or CAVEAT}")
    return "\n".join(lines)


def _stage_brief(
    run: DeskRun, store: RunStore, cfg: ManagerConfig, *, snap: ManagerSnapshot, changes: ChangeSet,
    attention: tuple[ChangeItem, ...], synthesis: Synthesis, commissions: tuple[Commission, ...],
    verdicts: list[GroundingVerdict], settings: Settings,
) -> tuple[DeskRun, Brief]:
    run = with_stage(run, "brief", state="running", started_at=dt.datetime.now(dt.UTC))
    store.save(run)

    data_health = _data_health(snap)
    aggregate = _aggregate_grounding(verdicts)
    degraded = any(v.degraded for v in verdicts)

    final_md = _render_final_md(
        cfg=cfg, snap=snap, attention=attention, synthesis=synthesis, commissions=commissions,
        data_health=data_health, degraded=degraded,
    )

    brief = Brief(
        brief_id=uuid.uuid4().hex,
        run_id=run.run_id,
        scope=cfg.scope,
        window=cfg.window,
        as_of=snap.as_of,
        generated_at=dt.datetime.now(dt.UTC).isoformat(),
        attention=attention,
        changes=changes,
        synthesis=synthesis,
        commissions=commissions,
        data_health=data_health,
        degraded=degraded,
        grounding=aggregate,
        cost_usd=str(run.budget.spent_usd),
        final_md=final_md,
    )
    _save_brief(settings, brief)
    _notify_brief(settings, brief)

    run = with_stage(
        run, "brief", state="succeeded", completed_at=dt.datetime.now(dt.UTC),
        summary=_clip(
            f"Brief {brief.brief_id} assembled: {len(attention)} attention item(s), "
            f"{len(commissions)} commission(s) proposed.",
            280,
        ),
        output_md=final_md,
    )
    run = run.model_copy(update={"config": {**run.config, "brief_id": brief.brief_id}})
    store.save(run)
    return run, brief


def _notify_brief(settings: Settings, brief: Brief) -> None:
    """Announce one finished brief through `app.notify`.

    One event per brief, not one per attention item -- the individual items already went out from the
    snapshot hook (`app.manager.service._notify_changes`), so repeating them here would double every
    notification. This says "the brief exists and here is its shape"; the detail is a taste of the top
    three so the notification is worth reading on a lock screen without opening anything.

    `attention` severity because a brief is the one daily artefact the owner asked to be told about,
    and wrapped so a notify defect can never fail a brief that is already written to disk.
    """
    try:
        from app.notify import emit

        emit(
            settings,
            kind="manager.brief",
            severity="attention",
            headline=f"Manager brief: {len(brief.attention)} attention item(s)",
            detail=_clip(" · ".join(item.headline for item in brief.attention[:3]), 320),
            refs=(brief.brief_id, brief.run_id),
            source="manager:brief",
            dedupe_id=f"manager.brief:{brief.brief_id}",
        )
    except Exception:
        logger.exception("manager: notify hook failed after brief %s; the brief is saved", brief.brief_id)


# ---------------------------------------------------------------------------
# Brief persistence -- data/agentdesk/manager/briefs/<brief_id>.json
# ---------------------------------------------------------------------------


def _briefs_dir(settings: Settings) -> Path:
    return manager_dir(settings) / "briefs"


def _brief_path(settings: Settings, brief_id: str) -> Path:
    """`briefs/<brief_id>.json`, or `ValueError` if that would not sit *directly* in the briefs
    directory.

    The HTTP boundary (`app.api.manager.IdPath`) already refuses ids with separators or dot segments;
    this is the defence-in-depth half, the same shape `app.agentdesk.models.run_dir` and
    `app.manager.chat.ManagerChatStore._thread_path` both use. `resolve()` on both sides so a
    parent-directory segment, a Windows backslash, or a symlinked briefs directory all collapse to a
    real location before the containment check.
    """
    directory = _briefs_dir(settings)
    candidate = (directory / f"{brief_id}.json").resolve()
    if candidate.parent != directory.resolve():
        raise ValueError(f"brief id does not name a brief in this store: {brief_id!r}")
    return candidate


def _save_brief(settings: Settings, brief: Brief) -> Path:
    """Write `brief` atomically -- the same uuid-suffixed-staging-file-then-`os.replace` idiom
    `app.agentdesk.store.RunStore.save` and `app.manager.snapshots.save` both use, so a reader
    (`load_brief`/`latest_brief`, or an HTTP handler built on them) never observes a torn file."""
    directory = _briefs_dir(settings)
    directory.mkdir(parents=True, exist_ok=True)
    path = _brief_path(settings, brief.brief_id)
    staging = directory / f"{path.name}.{uuid.uuid4().hex}.tmp"
    staging.write_text(brief.model_dump_json(indent=2), encoding="utf-8")
    os.replace(staging, path)
    return path


def load_brief(settings: Settings, brief_id: str) -> Brief | None:
    """The brief for `brief_id`, or `None` if it does not exist or cannot be parsed -- the same
    tolerance `RunStore.load` gives a corrupt `run.json`: a direct lookup by id is the caller's only
    answer for the id it asked about, so a corrupt file is reported as "not found" rather than raising.

    An id `_brief_path` rejects is "not found" for the same reason -- it could never have named a
    brief in this store."""
    try:
        path = _brief_path(settings, brief_id)
    except ValueError:
        return None
    if not path.is_file():
        return None
    try:
        return Brief.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("manager pipeline: could not read brief %r: %s", brief_id, exc)
        return None


def latest_brief(settings: Settings) -> Brief | None:
    """The newest brief by `generated_at`, or `None` when none exist yet. A brief file that fails to
    parse is logged and skipped rather than raising -- the same tolerance `RunStore.list_runs` gives one
    bad run file among many good ones."""
    directory = _briefs_dir(settings)
    if not directory.is_dir():
        return None

    briefs: list[Brief] = []
    for entry in directory.iterdir():
        if not entry.is_file() or not entry.name.endswith(".json"):
            continue
        try:
            briefs.append(Brief.model_validate_json(entry.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            logger.warning("manager pipeline: skipping unreadable brief file %s: %s", entry, exc)
            continue

    if not briefs:
        return None
    return max(briefs, key=lambda b: b.generated_at)


# ---------------------------------------------------------------------------
# The job target
# ---------------------------------------------------------------------------


def run_manager_brief(run_id: str, cfg: ManagerConfig, *, settings: Settings, cancel: threading.Event) -> None:
    """Drive one manager brief's six stages to completion, cancellation, or failure -- the job target a
    caller hands to `app.agentdesk.jobs.registry()` under `kind="manager"`, mirroring
    `app.tradingagents.pipeline.run_pipeline`'s own contract exactly.

    Assumes `run_id` already has a persisted `DeskRun` (built with `stages=build_stage_plan()` and a
    starting `budget=AgentBudget(cap_usd=cfg.cap_usd)`, the same responsibility `start_run` carries in
    `app.tradingagents.service`) -- this function only ever transitions those six stages, never invents
    or drops one. Never raises: every failure mode this pipeline can hit (cancellation, a grounding
    stage's `BudgetExhausted`/`AgentUnavailable`, the aggregate spend ceiling, an unexpected exception in
    the deterministic `collect` stage) is caught here and turned into a terminal `DeskRun` state.
    """
    store = RunStore(settings, "manager")
    run = store.load(run_id)
    if run is None:  # pragma: no cover - defensive; the caller always saves before starting the job
        logger.error("manager pipeline: run %r vanished from the store before it could start", run_id)
        return

    run = run.model_copy(update={"state": "running"})
    store.save(run)

    stage_ids = [stage.stage_id for stage in run.stages]

    if _handle_cancel(run, store, stage_ids, 0, cancel):
        return

    try:
        run, snap, changes = _stage_collect(run, store, cfg, settings=settings)
    except Exception as exc:
        logger.exception("manager pipeline: collect stage failed for run %r", run_id)
        _fail_run(run, store, "collect", f"{type(exc).__name__}: {exc}", stage_ids)
        return

    budget = run.budget
    verdicts: list[GroundingVerdict] = []

    if _handle_cancel(run, store, stage_ids, 1, cancel):
        return
    try:
        LEDGER.check(cfg.daily_cap_usd)
    except SpendCapExceeded as exc:
        _fail_run(run, store, "triage", str(exc), stage_ids, budget=budget)
        return
    try:
        run, budget, changes, attention, verdict = _stage_triage(
            run, store, snap, changes, cfg, settings=settings, budget=budget,
        )
    except BudgetExhausted as exc:
        budget = AgentBudget(cap_usd=exc.cap_usd, spent_usd=exc.spent_usd, calls=budget.calls)
        _fail_run(run, store, "triage", str(exc), stage_ids, budget=budget)
        return
    except AgentUnavailable as exc:
        _fail_run(run, store, "triage", str(exc), stage_ids, budget=budget)
        return
    verdicts.append(verdict)

    if _handle_cancel(run, store, stage_ids, 2, cancel):
        return
    try:
        LEDGER.check(cfg.daily_cap_usd)
    except SpendCapExceeded as exc:
        _fail_run(run, store, "synthesis", str(exc), stage_ids, budget=budget)
        return
    try:
        run, budget, synthesis, verdict = _stage_synthesis(
            run, store, snap, changes, cfg, settings=settings, budget=budget,
        )
    except BudgetExhausted as exc:
        budget = AgentBudget(cap_usd=exc.cap_usd, spent_usd=exc.spent_usd, calls=budget.calls)
        _fail_run(run, store, "synthesis", str(exc), stage_ids, budget=budget)
        return
    except AgentUnavailable as exc:
        _fail_run(run, store, "synthesis", str(exc), stage_ids, budget=budget)
        return
    verdicts.append(verdict)

    if _handle_cancel(run, store, stage_ids, 3, cancel):
        return
    try:
        LEDGER.check(cfg.daily_cap_usd)
    except SpendCapExceeded as exc:
        _fail_run(run, store, "research_plan", str(exc), stage_ids, budget=budget)
        return
    try:
        run, budget, commissions, verdict = _stage_research_plan(
            run, store, snap, changes, cfg, settings=settings, budget=budget,
        )
    except BudgetExhausted as exc:
        budget = AgentBudget(cap_usd=exc.cap_usd, spent_usd=exc.spent_usd, calls=budget.calls)
        _fail_run(run, store, "research_plan", str(exc), stage_ids, budget=budget)
        return
    except AgentUnavailable as exc:
        _fail_run(run, store, "research_plan", str(exc), stage_ids, budget=budget)
        return
    verdicts.append(verdict)

    if _handle_cancel(run, store, stage_ids, 4, cancel):
        return
    run = _stage_commission(run, store, commissions)

    if _handle_cancel(run, store, stage_ids, 5, cancel):
        return
    run, brief = _stage_brief(
        run, store, cfg, snap=snap, changes=changes, attention=attention, synthesis=synthesis,
        commissions=commissions, verdicts=verdicts, settings=settings,
    )

    run = run.model_copy(
        update={
            "state": "succeeded",
            "completed_at": dt.datetime.now(dt.UTC),
            "final_md": brief.final_md,
            "degraded": any(v.degraded for v in verdicts),
        }
    )
    store.save(run)

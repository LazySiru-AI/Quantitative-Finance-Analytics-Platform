"""Round 33 Phase B — the repeatable status/decision report.

`docs/AGENT-DESK-CONTRACT.md`'s sibling for Phase A is `strategy-program/tools/round33_bakeoff.py`,
which writes `data/rounds/r33-2026-08/PHASE-A-REPORT.md` on demand. Phase B had no such tool — the
only write-up so far was assembled by hand. This module is that tool's read half: `build_phase_b_report`
computes the floor status and applies `docs/WORKFLOW-UNIVERSE-STUDY-PLAN.md` §6's decision rule
honestly (never skipping past a below-floor window the way a hand-written report might be tempted to),
and `render_markdown` turns the result into the same kind of report a human would have written.
`strategy-program/tools/phase_b_report.py` is the CLI that calls both and writes the files.

**The floor, quoted exactly** (`docs/WORKFLOW-UNIVERSE-STUDY-PLAN.md:236-243`):

    **60 trading sessions and 40 gated candidates**, restricted to the `universe_source == "screen"`
    observation set — the same floor `WORKFLOW-STUDY-PLAN.md` §7 sets, reused rather than re-derived,
    because nothing about routing research spend to a different shortlist changes how many independent
    draws a paired-bootstrap or a binomial discrimination test needs to say anything. **If the floor is
    not reached, the decision rule (§5) is not evaluated at all** — any figure quoted from a
    below-floor window is monitoring, labelled as such, not evidence, exactly as the parent study's §7
    final paragraph states, and this document adopts that sentence rather than paraphrasing it into
    something weaker.

(The doc's own cross-reference reads "(§5)" where the decision rule is actually its own §6 --
"Explicit pre-registered nulls" is §5. Read as a stray internal-link typo, not as a second, different
rule; treated here as pointing at §6, the section actually titled "Decision rule (pre-registered)".)

**The decision rule, quoted exactly** (`docs/WORKFLOW-UNIVERSE-STUDY-PLAN.md:270-291`):

    `full_workflow` / screened is judged **worth its research spend on a dynamic universe**, and earns
    a further pre-registered round, only if **BOTH**:

    (a) `full_workflow` / screened's `adjusted_excess` exceeds `raw_signal` / screened's, paired
    bootstrap `p ≤ 0.10` on daily-return differences (§3.1), **and**
    (b) the discrimination test (§3.1, `m = 1` per §1.2) clears `q ≤ 0.10`.

    - **Neither holds** → dynamic selection did not change what the gate is worth; the mechanism
      finding from the static-universe study stands unmodified by universe choice.
    - **(b) but not (a)** → the gate discriminates on screened names but the screened book is not
      capturing it net of cost or exposure — an execution finding about the screened path
      specifically, not a selection finding.
    - **(a) but not (b)** → most likely exposure luck on a moving shortlist, which §2's second trap
      specifically warns is easier to manufacture here than on a fixed universe; re-run on a fresh
      window before crediting it.

    Reading either arm before the §4 floor is reached is monitoring, not evidence, per §4.

**Why this module cannot just read `WorkflowStudy.discrimination` off `app.workflow.study.build_study`
for condition (b).** `study.py`'s `_discrimination` hardcodes `_GATES = ("ta_gated", "vibe_gated",
"full_workflow")` and always runs `benjamini_hochberg` over all three gates' p-values -- `m = 3`, per
`docs/WORKFLOW-STUDY-PLAN.md` §4's own three-gate design, which this Phase B document explicitly does
*not* inherit (§1.2: "this study evaluates one gate ... m = 1 ... not an oversight to reconcile against
the parent study's m = 3"). Reusing `study.discrimination`'s `full_workflow` row for condition (b) would
silently apply the wrong multiple-comparison correction. `_full_workflow_discrimination_m1` below
recomputes the identical test (same `binomial_p_value`/`stationary_bootstrap_p`-free discrimination
logic `study._discrimination` uses, same screen-only, resolved-and-priced observation filter) with a
one-element `benjamini_hochberg` call instead, purely for the decision rule. The full three-gate,
`m = 3` result is still embedded in `report.study.discrimination` (via `app.workflow.study.build_study`,
called unmodified) so a reader can see both figures and is never left wondering which one governed
`report.verdict` -- the markdown report labels the two explicitly.

**What "gated candidate" means for the floor, and for `gated_candidates_per_gate`.** The doc never
defines the phrase precisely; §1.2 frames Phase B as testing "one gate — `full_workflow`", so this
module reads "gated candidate" as *a screen-mode candidate the necessity-gate chain actually let a gate
rule on* -- i.e. `CandidateObservation.skip_reason is None` (a skipped candidate's `GateDecision`s are
a default refusal manufactured by the skip, per `app.workflow.pipeline._stage_orders`'s own comment
that every candidate gets three `GateDecision`s "kept and hard-skipped alike", not evidence the gate
itself considered). `gated_candidates_per_gate` reports this count per gate name (identical across all
three today, since the skip is a candidate-level, not a gate-level, event -- kept as a per-gate dict
because a future necessity-gate change could make that no longer true, and because
`docs/WORKFLOW-UNIVERSE-STUDY-PLAN.md` §0 recon item 4 is explicit that all three gates are always
logged regardless of which arms are enabled). The floor's own "40 gated candidates" is checked against
`gated_candidates_per_gate["full_workflow"]` specifically, per §1.2's single-gate framing -- this is an
interpretation, not a number the doc states in so many words, and is called out again in the CLI's
printed output and this module's own tests.

**Everything here is read-only.** No book, no candidate log, and no `DeskRun` is written -- this reads
exactly what `app.workflow.candidates`, `app.workflow.study` (itself read-only, see its own module
docstring), and `app.agentdesk.store.RunStore` already persisted.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.backtest.scan import benjamini_hochberg, binomial_p_value
from app.config import Settings
from app.workflow import candidates as candidates_mod
from app.workflow.candidates import CandidateObservation, GateName
from app.workflow.phase_b import (
    PHASE_B_MAX_RESEARCH_SYMBOLS,
    PHASE_B_SCREEN_ENTRY_RULE,
    PHASE_B_SCREEN_TOP_N,
    PHASE_B_SELECTOR_ID,
)
from app.workflow.pipeline import SCREENED_ARMS
from app.workflow.study import GateDiscrimination, WorkflowStudy, build_study

__all__ = [
    "FLOOR_GATED_CANDIDATES",
    "FLOOR_SESSIONS",
    "PhaseBReport",
    "PhaseBVerdict",
    "build_phase_b_report",
    "render_markdown",
]

#: `docs/WORKFLOW-UNIVERSE-STUDY-PLAN.md` §4, quoted in full in the module docstring above. Module
#: constants, not literals inlined at each use, so a test can monkeypatch them down to exercise the
#: floor-met path without needing 60 real sessions of fixture data.
FLOOR_SESSIONS = 60
FLOOR_GATED_CANDIDATES = 40

#: Every gate the observation log carries a ruling for, regardless of which arms a run enabled --
#: `docs/WORKFLOW-UNIVERSE-STUDY-PLAN.md` §0 recon item 4. Same order `app.workflow.study._GATES` uses.
_ALL_GATES: tuple[GateName, ...] = ("ta_gated", "vibe_gated", "full_workflow")

#: The one gate Phase B's decision rule evaluates -- `docs/WORKFLOW-UNIVERSE-STUDY-PLAN.md` §1.2.
_DECISION_GATE: GateName = "full_workflow"

#: A ceiling, not an expectation -- see `app.workflow.study._ALL_RUNS_LIMIT`'s identical reasoning.
_ALL_RUNS_LIMIT = 100_000

_DECISION_THRESHOLD = Decimal("0.10")
_FRACTION_QUANT = Decimal("0.000001")

PhaseBVerdict = Literal[
    "below_floor",
    "gate_not_measurable",
    "positive",
    "null",
    "execution_gap",
    "exposure_luck",
]
"""Closed set this module ever assigns to `PhaseBReport.verdict`. `"below_floor"` always wins
regardless of any p/q-value, per §4. `"gate_not_measurable"` is floor-met but the discrimination test
itself has an empty passed or refused set (§6's rule presumes both exist). `"positive"`/`"null"` are
§6's "BOTH hold"/"neither holds" branches. `"execution_gap"` is §6's "(b) but not (a)" branch and
`"exposure_luck"` is its "(a) but not (b)" branch -- named for what each branch's own prose calls it,
not restated as "(a) but not (b)" because a verdict a reader has to decode against the doc is a worse
verdict than one that says what it means."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PhaseBReport(_Frozen):
    """One Phase B status snapshot: frozen config, accrual counters, floor status, the embedded
    `WorkflowStudy`, and the §6 verdict. See the module docstring for the floor and decision rule this
    applies, quoted verbatim from `docs/WORKFLOW-UNIVERSE-STUDY-PLAN.md`."""

    generated_on: dt.date

    selector_id: str
    screen_top_n: int
    screen_entry_rule: str
    max_research_symbols: int

    sessions_observed: int
    """Distinct `decision_date` among every screen-mode observation, resolved or pending alike."""
    first_session: dt.date | None
    last_session: dt.date | None
    distinct_symbols: int

    observations_total: int
    observations_resolved: int
    """Every screen-mode row with `state == 'resolved'` -- includes `observations_unpriceable`, not
    additional to it."""
    observations_pending: int
    observations_unpriceable: int
    """Subset of `observations_resolved` whose window could not be priced (`unpriceable=True`)."""

    skip_reasons: dict[str, int]
    """`candidates.SKIP_REASONS` -> count, over every screen-mode observation. Zero-filled for every
    reason in that tuple, not only the ones actually seen."""
    verdict_sources: dict[str, int]
    """`{"fresh": n, "cached": n, "mixed": n}` over every `GateDecision` on every screen-mode
    observation (all three gates, all observations -- not filtered to `full_workflow` or to ruled-only
    rows), per the field's own name: where verdicts came from, not which ones counted toward a floor."""
    avoided_cost_usd: Decimal
    """Sum of `CandidateObservation.avoided_cost_usd` over every screen-mode observation."""

    gated_candidates_per_gate: dict[str, int]
    """Per gate name, the count of screen-mode observations with `skip_reason is None` -- see the
    module docstring's "What 'gated candidate' means" section for why this, and not `passed_n +
    refused_n` off `WorkflowStudy.discrimination`, is what this module reports here."""

    resolved_mean_forward_return: Decimal | None
    """Mean `forward_return_pct` over resolved, priced (non-`unpriceable`) screen-mode observations.
    `None` when that set is empty."""
    resolved_hit_rate: Decimal | None
    """Fraction of that same set with `forward_return_pct > 0`. `None` when that set is empty."""

    screen_run_count: int
    """Stored workflow `DeskRun`s whose `config["universe_mode"] == "screen"`."""
    screen_spend_usd: Decimal
    """Summed `AgentBudget.spent_usd` over those same runs."""

    floor_sessions_required: int
    floor_gated_required: int
    floor_met: bool

    study: WorkflowStudy
    """`app.workflow.study.build_study(settings=settings, arms=app.workflow.pipeline.SCREENED_ARMS,
    universe_source="screen")`, unmodified -- includes its own three-gate, `m = 3`
    `discrimination` tuple; see the module docstring for why the verdict below does not use that
    tuple's `full_workflow` row directly."""

    verdict: PhaseBVerdict
    verdict_detail: str
    """One plain-language sentence explaining `verdict`."""


def _empty_skip_reasons() -> dict[str, int]:
    return dict.fromkeys(candidates_mod.SKIP_REASONS, 0)


def _empty_verdict_sources() -> dict[str, int]:
    return {"fresh": 0, "cached": 0, "mixed": 0}


def _empty_gated_per_gate() -> dict[str, int]:
    return dict.fromkeys(_ALL_GATES, 0)


def _full_workflow_discrimination_m1(
    observations: tuple[CandidateObservation, ...],
) -> GateDiscrimination:
    """The §3.1/§1.2 discrimination test for `full_workflow` alone, `m = 1` -- see the module
    docstring's explanation of why `WorkflowStudy.discrimination` (always `m = 3`) is not reused for
    this. `observations` must already be screen-mode, `state == "resolved"`, not `unpriceable`, with a
    `forward_return_pct` -- exactly `app.workflow.study._discrimination`'s own filter, duplicated here
    rather than imported because that function is private to its module."""
    passed: list[float] = []
    refused: list[float] = []
    for obs in observations:
        forward = obs.forward_return_pct
        if forward is None:
            continue
        for decision in obs.gates:
            if decision.gate != _DECISION_GATE:
                continue
            (passed if decision.passed else refused).append(float(forward))

    if passed and refused:
        refused_hit_rate = sum(1 for r in refused if r > 0) / len(refused)
        successes = sum(1 for r in passed if r > 0)
        p_value: float | None = binomial_p_value(successes, len(passed), refused_hit_rate)
    else:
        p_value = None
    (q_value,) = benjamini_hochberg([p_value])  # m = 1: a one-element list, by construction.

    passed_hit = sum(1 for r in passed if r > 0) / len(passed) if passed else None
    refused_hit = sum(1 for r in refused if r > 0) / len(refused) if refused else None
    passed_mean = sum(passed) / len(passed) if passed else None
    refused_mean = sum(refused) / len(refused) if refused else None
    mean_diff = (
        Decimal(str(passed_mean - refused_mean))
        if passed_mean is not None and refused_mean is not None
        else None
    )
    return GateDiscrimination(
        gate=_DECISION_GATE,
        passed_n=len(passed),
        refused_n=len(refused),
        passed_hit_rate=Decimal(str(passed_hit)) if passed_hit is not None else None,
        refused_hit_rate=Decimal(str(refused_hit)) if refused_hit is not None else None,
        passed_mean_forward_return=Decimal(str(passed_mean)) if passed_mean is not None else None,
        refused_mean_forward_return=Decimal(str(refused_mean)) if refused_mean is not None else None,
        mean_diff=mean_diff,
        p_value=Decimal(str(p_value)) if p_value is not None else None,
        q_value=Decimal(str(q_value)) if q_value is not None else None,
    )


def _apply_decision_rule(
    *, floor_met: bool, study: WorkflowStudy, disc_m1: GateDiscrimination
) -> tuple[PhaseBVerdict, str]:
    """§6's decision rule, literally -- see the module docstring for the quoted text. Never evaluated
    below the §4 floor, per that same section."""
    if not floor_met:
        return (
            "below_floor",
            "Below the §4 floor (60 sessions, 40 gated candidates): monitoring, not evidence -- "
            "the decision rule is not evaluated.",
        )

    if disc_m1.q_value is None:
        return (
            "gate_not_measurable",
            "Floor met, but the discrimination test has an empty passed or refused set "
            f"(passed_n={disc_m1.passed_n}, refused_n={disc_m1.refused_n}) and cannot rule -- "
            "condition (b) is untestable, so §6 is not evaluated either way.",
        )

    raw = next((a for a in study.arms if a.arm == "raw_signal"), None)
    fw = next((a for a in study.arms if a.arm == "full_workflow"), None)
    paired = next((p for p in study.paired if p.arm == "full_workflow"), None)

    condition_a = (
        raw is not None
        and fw is not None
        and paired is not None
        and paired.bootstrap_p is not None
        and paired.bootstrap_p <= _DECISION_THRESHOLD
        and fw.adjusted_excess > raw.adjusted_excess
    )
    condition_b = disc_m1.q_value <= _DECISION_THRESHOLD

    p_str = "—" if paired is None or paired.bootstrap_p is None else format(paired.bootstrap_p, "f")
    q_str = format(disc_m1.q_value, "f")

    if condition_a and condition_b:
        return (
            "positive",
            f"Both conditions hold (paired bootstrap p={p_str}, discrimination q={q_str} at m=1): "
            "full_workflow/screened is judged worth its research spend on a dynamic universe and "
            "earns a further pre-registered round.",
        )
    if condition_b and not condition_a:
        return (
            "execution_gap",
            f"Discrimination clears (q={q_str} at m=1) but the paired comparison does not "
            f"(p={p_str}): the gate discriminates on screened names but the screened book is not "
            "capturing it net of cost or exposure -- an execution finding, not a selection finding.",
        )
    if condition_a and not condition_b:
        return (
            "exposure_luck",
            f"The paired comparison clears (p={p_str}) but discrimination does not (q={q_str} at "
            "m=1): most likely exposure luck on a moving shortlist -- re-run on a fresh window "
            "before crediting it.",
        )
    return (
        "null",
        f"Neither condition holds (paired bootstrap p={p_str}, discrimination q={q_str} at m=1): "
        "dynamic selection did not change what the gate is worth; the mechanism finding from the "
        "static-universe study stands unmodified by universe choice.",
    )


def build_phase_b_report(settings: Settings, *, today: dt.date | None = None) -> PhaseBReport:
    """Pure read: no network call, no model call, no write. See the module docstring for the floor
    and decision rule applied, and for why condition (b) is recomputed rather than read off
    `WorkflowStudy.discrimination`."""
    generated_on = today if today is not None else dt.date.today()

    observations = candidates_mod.read_observations(settings=settings, universe_source="screen")

    sessions = sorted({obs.decision_date for obs in observations})
    sessions_observed = len(sessions)
    first_session = sessions[0] if sessions else None
    last_session = sessions[-1] if sessions else None
    distinct_symbols = len({obs.symbol for obs in observations})

    observations_total = len(observations)
    observations_resolved = sum(1 for obs in observations if obs.state == "resolved")
    observations_pending = sum(1 for obs in observations if obs.state == "pending")
    observations_unpriceable = sum(
        1 for obs in observations if obs.state == "resolved" and obs.unpriceable
    )

    skip_reasons = _empty_skip_reasons()
    for obs in observations:
        if obs.skip_reason is not None:
            skip_reasons[obs.skip_reason] = skip_reasons.get(obs.skip_reason, 0) + 1

    verdict_sources = _empty_verdict_sources()
    for obs in observations:
        for decision in obs.gates:
            verdict_sources[decision.verdict_source] += 1

    avoided_cost_usd = sum(
        (obs.avoided_cost_usd for obs in observations), Decimal("0")
    )

    gated_candidates_per_gate = _empty_gated_per_gate()
    ruled_observations = [obs for obs in observations if obs.skip_reason is None]
    for obs in ruled_observations:
        ruled_gates = {decision.gate for decision in obs.gates}
        for gate in _ALL_GATES:
            if gate in ruled_gates:
                gated_candidates_per_gate[gate] += 1

    resolved_priced = [
        obs
        for obs in observations
        if obs.state == "resolved" and not obs.unpriceable and obs.forward_return_pct is not None
    ]
    if resolved_priced:
        forwards = [obs.forward_return_pct for obs in resolved_priced if obs.forward_return_pct is not None]
        resolved_mean_forward_return: Decimal | None = (
            sum(forwards, Decimal("0")) / Decimal(len(forwards))
        ).quantize(_FRACTION_QUANT)
        hits = sum(1 for f in forwards if f > 0)
        resolved_hit_rate: Decimal | None = (
            Decimal(hits) / Decimal(len(forwards))
        ).quantize(_FRACTION_QUANT)
    else:
        resolved_mean_forward_return = None
        resolved_hit_rate = None

    from app.agentdesk.store import RunStore

    workflow_runs = RunStore(settings, "workflow").list_runs(limit=_ALL_RUNS_LIMIT)
    screen_runs = [run for run in workflow_runs if run.config.get("universe_mode") == "screen"]
    screen_run_count = len(screen_runs)
    screen_spend_usd = sum((run.budget.spent_usd for run in screen_runs), Decimal("0"))

    gated_count = gated_candidates_per_gate[_DECISION_GATE]
    floor_met = sessions_observed >= FLOOR_SESSIONS and gated_count >= FLOOR_GATED_CANDIDATES

    study = build_study(settings=settings, arms=SCREENED_ARMS, universe_source="screen")
    disc_m1 = _full_workflow_discrimination_m1(tuple(resolved_priced))
    verdict, verdict_detail = _apply_decision_rule(floor_met=floor_met, study=study, disc_m1=disc_m1)

    return PhaseBReport(
        generated_on=generated_on,
        selector_id=PHASE_B_SELECTOR_ID,
        screen_top_n=PHASE_B_SCREEN_TOP_N,
        screen_entry_rule=PHASE_B_SCREEN_ENTRY_RULE,
        max_research_symbols=PHASE_B_MAX_RESEARCH_SYMBOLS,
        sessions_observed=sessions_observed,
        first_session=first_session,
        last_session=last_session,
        distinct_symbols=distinct_symbols,
        observations_total=observations_total,
        observations_resolved=observations_resolved,
        observations_pending=observations_pending,
        observations_unpriceable=observations_unpriceable,
        skip_reasons=skip_reasons,
        verdict_sources=verdict_sources,
        avoided_cost_usd=avoided_cost_usd,
        gated_candidates_per_gate=gated_candidates_per_gate,
        resolved_mean_forward_return=resolved_mean_forward_return,
        resolved_hit_rate=resolved_hit_rate,
        screen_run_count=screen_run_count,
        screen_spend_usd=screen_spend_usd,
        floor_sessions_required=FLOOR_SESSIONS,
        floor_gated_required=FLOOR_GATED_CANDIDATES,
        floor_met=floor_met,
        study=study,
        verdict=verdict,
        verdict_detail=verdict_detail,
    )


def _pct(x: Decimal | None, *, places: int = 2) -> str:
    if x is None:
        return "—"
    return f"{(x * 100):.{places}f}%"


def _usd(x: Decimal | None) -> str:
    if x is None:
        return "—"
    return f"${format(x, 'f')}"


def _num(x: Decimal | None, *, places: int = 4) -> str:
    if x is None:
        return "—"
    return f"{x:.{places}f}"


def render_markdown(report: PhaseBReport) -> str:
    """A Markdown report: header, floor status, accrual, spend, arm/paired/discrimination tables,
    verdict, and caveats. Deterministic in `report`'s own fields (no wall-clock, no I/O)."""
    lines: list[str] = []

    lines.append(f"# Round 33 Phase B — status report ({report.generated_on.isoformat()})")
    lines.append("")
    lines.append(
        f"Selector `{report.selector_id}`, screen top {report.screen_top_n}, "
        f"entry rule `{report.screen_entry_rule}`, "
        f"max {report.max_research_symbols} researched symbol(s)/session. "
        "Not investment advice."
    )
    lines.append("")

    lines.append("## Floor status")
    lines.append("")
    if not report.floor_met:
        lines.append("> **MONITORING, NOT EVIDENCE** — Phase B has not reached its §4 floor yet.")
        lines.append("")
    lines.append(
        f"- Sessions observed: **{report.sessions_observed}** / {report.floor_sessions_required} required"
    )
    lines.append(
        f"- Gated candidates (`full_workflow`, ruled, not skipped): "
        f"**{report.gated_candidates_per_gate.get('full_workflow', 0)}** / "
        f"{report.floor_gated_required} required"
    )
    lines.append(f"- Floor met: **{report.floor_met}**")
    lines.append("")

    lines.append("## Accrual")
    lines.append("")
    lines.append(
        f"- Observations: **{report.observations_total}** total "
        f"({report.observations_resolved} resolved, {report.observations_pending} pending, "
        f"{report.observations_unpriceable} unpriceable)"
    )
    lines.append(f"- Distinct symbols: **{report.distinct_symbols}**")
    lines.append(
        f"- Sessions: {report.first_session.isoformat() if report.first_session else '—'} .. "
        f"{report.last_session.isoformat() if report.last_session else '—'}"
    )
    lines.append(
        "- Skip reasons: "
        + ", ".join(f"{k}={v}" for k, v in report.skip_reasons.items())
    )
    lines.append(
        "- Verdict sources: "
        + ", ".join(f"{k}={v}" for k, v in report.verdict_sources.items())
    )
    lines.append(f"- Avoided cost (cached verdicts): {_usd(report.avoided_cost_usd)}")
    lines.append(
        "- Gated candidates per gate: "
        + ", ".join(f"{k}={v}" for k, v in report.gated_candidates_per_gate.items())
    )
    lines.append(
        f"- Resolved mean forward return: {_pct(report.resolved_mean_forward_return)}  |  "
        f"Resolved hit rate: {_pct(report.resolved_hit_rate)}"
    )
    lines.append("")

    lines.append("## Spend")
    lines.append("")
    lines.append(f"- Screen-mode workflow runs: **{report.screen_run_count}**")
    lines.append(f"- Screen-mode spend: {_usd(report.screen_spend_usd)}")
    lines.append("")

    lines.append("## Arm metrics (screen books)")
    lines.append("")
    lines.append(
        "| arm | total_return | adjusted_excess | exposure | realized_vol | win_rate | trades | "
        "net_adjusted_excess | research_cost |"
    )
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for row in report.study.arms:
        lines.append(
            f"| {row.arm} | {_pct(row.total_return)} | {_pct(row.adjusted_excess)} | "
            f"{_pct(row.exposure)} | {_pct(row.realized_vol)} | {_pct(row.win_rate)} | "
            f"{row.trades} | {_pct(row.net_adjusted_excess)} | {_usd(row.research_cost_usd)} |"
        )
    lines.append("")

    lines.append("## Paired comparison (vs raw_signal/screened)")
    lines.append("")
    lines.append("| arm | mean_daily_diff | bootstrap_p |")
    lines.append("|---|--:|--:|")
    for pc in report.study.paired:
        lines.append(f"| {pc.arm} | {_pct(pc.mean_daily_diff, places=4)} | {_num(pc.bootstrap_p, places=4)} |")
    lines.append("")

    lines.append("## Discrimination")
    lines.append("")
    lines.append(
        "`WorkflowStudy.discrimination` below is the three-gate, **m = 3** result "
        "(`app.workflow.study` reused unmodified, per `docs/WORKFLOW-STUDY-PLAN.md` §4's design). "
        "The §6 decision rule for Phase B uses a separate, one-gate **m = 1** recomputation on "
        "`full_workflow` alone, per `docs/WORKFLOW-UNIVERSE-STUDY-PLAN.md` §1.2 -- shown on its own "
        "row below, not in this table."
    )
    lines.append("")
    lines.append("| gate | passed_n | refused_n | passed_hit | refused_hit | mean_diff | p_value | q_value |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|")
    for gd in report.study.discrimination:
        lines.append(
            f"| {gd.gate} (m=3) | {gd.passed_n} | {gd.refused_n} | {_pct(gd.passed_hit_rate)} | "
            f"{_pct(gd.refused_hit_rate)} | {_pct(gd.mean_diff, places=4)} | "
            f"{_num(gd.p_value, places=4)} | {_num(gd.q_value, places=4)} |"
        )
    lines.append("")

    lines.append("## Verdict")
    lines.append("")
    lines.append(f"**{report.verdict}**")
    lines.append("")
    lines.append(report.verdict_detail)
    lines.append("")

    lines.append("## Caveats")
    lines.append("")
    lines.append(
        "- Backfilled observations were research-starved: candidates seeded outside a live Phase B "
        "step never had a child run launched against them, so their gate rulings are defaults, not "
        "judgements, and should not be read as the gate having considered them."
    )
    lines.append(
        "- Heavy symbol overlap means the effective independent sample can be far below the row "
        f"count: this window has {report.distinct_symbols} distinct symbol(s) against "
        f"{report.observations_total} observation(s) -- when the former is small relative to the "
        "latter, treat the discrimination test's n as an upper bound on independent information, "
        "not a literal count of independent draws."
    )
    lines.append(
        "- Card-mode books and candidates are excluded entirely from every figure above: this report "
        "covers `universe_source == \"screen\"` only, per `docs/WORKFLOW-UNIVERSE-STUDY-PLAN.md` §7's "
        "guardrail that the two cohorts are not comparable session-for-session."
    )
    lines.append("")

    return "\n".join(lines)

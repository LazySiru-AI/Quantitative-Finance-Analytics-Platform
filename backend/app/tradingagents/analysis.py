"""Risk-panel attribution: whether the risk panel ever changes the desk's call.

**The question this can answer, and the one it deliberately cannot.** `AnalystReport` carries only
`report_md` and a one-sentence `takeaway` -- the analysts emit no structured rating, so "did the
bull/bear debate flip the analysts' read" is not answerable from anything stored; answering it would
need a controlled ablation (run the same evidence with and without the debate and compare), not a
proxy classifier invented after the fact to squeeze a number out of free text. What *is* stored, and
therefore answerable at zero model cost: `app.tradingagents.schemas.ResearchPlan.recommendation`, the
research manager's call made after the debate but *before* the trader and risk panel ever see the
name, versus `DeskRun.final_rating`, the portfolio manager's call made *after* the risk panel has
argued over the trader's proposal. The gap between those two -- both already persisted, neither
requiring a new call -- is the risk panel's own attribution.

**Why this reads `DeskRun`s the caller already has, not the store itself.** Mirrors
`app.workflow.analysis`'s split for the same reason: `app.agentdesk.store.RunStore.list_runs` is the
one place that walks `data/agentdesk/tradingagents/runs/` and tolerates an unreadable run file by
skipping it (see that module's own docstring); re-deriving that walk here would duplicate its
corruption handling. A caller loads runs with `RunStore(settings, "tradingagents").list_runs(...)`
and hands the sequence here, which makes the arithmetic testable against synthetic `DeskRun`s with no
temp directory or real store involved.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.agentdesk.models import DeskRun
from app.tradingagents.schemas import RATING_5TIER, parse_recommendation

__all__ = ["RatingComparison", "RatingFlipRate", "rating_flip_rate"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


Direction = Literal["upgraded", "downgraded", "unchanged"]
"""`upgraded`: the risk panel moved the call to a more bullish tier than the research manager's own
(e.g. Hold -> Buy). `downgraded`: the opposite, a more bearish tier (e.g. Buy -> Hold). `unchanged`:
the portfolio manager's rating matches the research manager's recommendation exactly."""


class RatingComparison(_Frozen):
    """One run's pre-risk-panel call against its post-risk-panel one."""

    run_id: str
    pre_risk_recommendation: str
    """The research manager's `ResearchPlan.recommendation`, read back via `parse_recommendation`."""

    post_risk_rating: str
    """`DeskRun.final_rating` -- the portfolio manager's rating, after the risk panel."""

    flipped: bool
    direction: Direction


class RatingFlipRate(_Frozen):
    """How often the risk panel changed the desk's call, over every run where both the pre- and
    post-risk-panel calls are present in the stored record."""

    total: int
    """Runs counted -- those with both a `research_manager` stage carrying rendered output and a
    non-empty `final_rating`. A run that failed before the portfolio manager stage, or before the
    research manager stage, contributes nothing to comparable here: there is no post-risk-panel call
    to compare in the first case, and no pre-risk-panel one in the second."""

    flipped: int
    flip_rate: float | None
    """`flipped / total`. `None` when `total` is zero, for the same reason
    `app.workflow.analysis.GateConcordance.agreement_rate` is `None` there rather than `0.0`."""

    upgraded: int
    downgraded: int
    unchanged: int
    comparisons: tuple[RatingComparison, ...]
    """Every counted run's own comparison, for a caller that wants the per-run detail rather than
    only the aggregate -- with `total` this small in the current record, the detail is most of the
    signal."""


_RANK: dict[str, int] = {tier: index for index, tier in enumerate(RATING_5TIER)}
"""Index into `RATING_5TIER`, which is ordered most-bullish (`Buy`, index 0) to most-bearish
(`Sell`, index 4) -- see that tuple's own docstring. A lower index after the risk panel than before it
is a more bullish call, i.e. an upgrade."""


def _direction(pre: str, post: str) -> Direction:
    if pre == post:
        return "unchanged"
    return "upgraded" if _RANK[post] < _RANK[pre] else "downgraded"


def rating_flip_rate(runs: Sequence[DeskRun]) -> RatingFlipRate:
    """How often the risk panel changed the call, over `runs`.

    A run is counted only when both halves of the comparison are actually present: a `research_manager`
    stage whose `output_md` is non-empty (that stage ran and rendered a plan -- `parse_recommendation`
    on an empty string would silently default to `"Hold"` and manufacture a comparison from nothing),
    and a non-empty `DeskRun.final_rating` (the run reached the portfolio manager and succeeded far
    enough to have one). Every other run -- failed before either stage, cancelled, still running -- is
    skipped rather than padded with a default, the same discipline
    `app.workflow.candidates.GateDecision.was_explicit` protects on the sibling log: a run that never
    reached a stage is not evidence that the stage would have agreed.
    """
    comparisons: list[RatingComparison] = []
    for run in runs:
        if not run.final_rating:
            continue
        stage = next((s for s in run.stages if s.stage_id == "research_manager"), None)
        if stage is None or not stage.output_md:
            continue
        pre = parse_recommendation(stage.output_md)
        post = run.final_rating
        comparisons.append(
            RatingComparison(
                run_id=run.run_id,
                pre_risk_recommendation=pre,
                post_risk_rating=post,
                flipped=pre != post,
                direction=_direction(pre, post),
            )
        )

    total = len(comparisons)
    flipped = sum(1 for c in comparisons if c.flipped)
    upgraded = sum(1 for c in comparisons if c.direction == "upgraded")
    downgraded = sum(1 for c in comparisons if c.direction == "downgraded")
    unchanged = total - flipped
    flip_rate = flipped / total if total else None
    return RatingFlipRate(
        total=total,
        flipped=flipped,
        flip_rate=flip_rate,
        upgraded=upgraded,
        downgraded=downgraded,
        unchanged=unchanged,
        comparisons=tuple(comparisons),
    )

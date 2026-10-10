"""Unit tests for `app.tradingagents.analysis.rating_flip_rate` and
`app.tradingagents.schemas.parse_recommendation`.

`parse_recommendation`'s primary-path tests round-trip through `render_research_plan` itself rather
than a hand-written sentence -- asserting the regex against invented prose would still pass if
`render_research_plan`'s actual literal drifted out from under it (see
`docs/notes/grounding-gate-false-rejections.md`'s own lesson about probing validators with real
caller output, not rules-in-isolation). Only the deliberately-degenerate fallback/default cases below
are hand-written, since there is no renderer output to round-trip for "the text carries no
recommendation at all."
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.agentdesk.models import DeskRun, StageRecord
from app.agents.models import AgentBudget
from app.tradingagents import schemas
from app.tradingagents.analysis import rating_flip_rate
from app.tradingagents.schemas import (
    RATING_5TIER,
    ResearchPlan,
    parse_recommendation,
    render_research_plan,
)

# ---------------------------------------------------------------------------
# parse_recommendation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tier", RATING_5TIER)
def test_round_trips_every_tier_through_render_research_plan(tier: str) -> None:
    plan = ResearchPlan(recommendation=tier, rationale="rationale text", strategic_actions="actions text")  # type: ignore[arg-type]
    rendered = render_research_plan(plan)
    assert parse_recommendation(rendered) == tier


def test_the_rendered_prefix_is_the_literal_two_asterisk_recommendation_line() -> None:
    """Pins the exact literal `rating_flip_rate`'s caller (and this module's own docstring) names,
    so a future edit to `render_research_plan` that changes this prefix breaks this test rather than
    silently drifting past `parse_recommendation`'s fallback path."""
    plan = ResearchPlan(recommendation="Overweight", rationale="r", strategic_actions="a")
    rendered = render_research_plan(plan)
    assert rendered.startswith("**Recommendation: Overweight**\n\n")


def test_falls_back_to_the_first_rating_word_with_no_recommendation_line() -> None:
    assert parse_recommendation("The desk leans toward a Sell here given the setup.") == "Sell"


def test_defaults_to_hold_with_no_recognizable_word() -> None:
    assert parse_recommendation("This text carries no recognizable tier at all.") == "Hold"


def test_is_case_insensitive_and_canonicalizes() -> None:
    assert parse_recommendation("recommendation: underweight") == "Underweight"


def test_does_not_touch_parse_ratings_own_line_format() -> None:
    """`parse_recommendation` must not accidentally match the portfolio manager's `rating: X` line
    format -- the two functions read two different stages' output and must not be interchangeable by
    accident."""
    assert parse_recommendation("rating: Buy\n\nsome thesis") == "Buy"  # falls back to the word pass
    assert schemas.parse_rating("**Recommendation: Sell**\n\nsome rationale") == "Sell"  # same, other way


# ---------------------------------------------------------------------------
# rating_flip_rate
# ---------------------------------------------------------------------------


def _budget() -> AgentBudget:
    return AgentBudget(cap_usd=Decimal("5.00"))


def _stage(stage_id: str, *, output_md: str = "") -> StageRecord:
    return StageRecord(stage_id=stage_id, role="research_manager", label="Research Manager", output_md=output_md)


def _run(
    run_id: str,
    *,
    final_rating: str = "",
    research_manager_output: str | None = None,
    extra_stages: tuple[StageRecord, ...] = (),
) -> DeskRun:
    stages: tuple[StageRecord, ...] = extra_stages
    if research_manager_output is not None:
        stages = (*stages, _stage("research_manager", output_md=research_manager_output))
    return DeskRun(
        run_id=run_id,
        kind="tradingagents",
        state="succeeded" if final_rating else "failed",
        created_at=dt.datetime.now(dt.UTC),
        stages=stages,
        final_rating=final_rating,
        budget=_budget(),
    )


def _rendered(tier: str) -> str:
    return render_research_plan(ResearchPlan(recommendation=tier, rationale="r", strategic_actions="a"))  # type: ignore[arg-type]


def test_unchanged_run_counts_as_unchanged_not_flipped() -> None:
    run = _run("r1", final_rating="Buy", research_manager_output=_rendered("Buy"))
    result = rating_flip_rate([run])

    assert result.total == 1
    assert result.flipped == 0
    assert result.unchanged == 1
    assert result.flip_rate == pytest.approx(0.0)
    assert result.comparisons[0].direction == "unchanged"


def test_a_more_bearish_final_rating_is_a_downgrade() -> None:
    """Research manager said Buy; the risk panel talked the portfolio manager down to Hold."""
    run = _run("r1", final_rating="Hold", research_manager_output=_rendered("Buy"))
    result = rating_flip_rate([run])

    assert result.total == 1
    assert result.flipped == 1
    assert result.downgraded == 1
    assert result.upgraded == 0
    assert result.comparisons[0].direction == "downgraded"
    assert result.comparisons[0].pre_risk_recommendation == "Buy"
    assert result.comparisons[0].post_risk_rating == "Hold"


def test_a_more_bullish_final_rating_is_an_upgrade() -> None:
    """Research manager said Hold; the risk panel ended up more convicted, Buy."""
    run = _run("r1", final_rating="Buy", research_manager_output=_rendered("Hold"))
    result = rating_flip_rate([run])

    assert result.total == 1
    assert result.flipped == 1
    assert result.upgraded == 1
    assert result.downgraded == 0
    assert result.comparisons[0].direction == "upgraded"


def test_a_run_with_no_final_rating_is_excluded() -> None:
    """A run that never reached (or never succeeded past) the portfolio manager has no post-risk-panel
    call to compare -- it must not be padded into the table with a fabricated default."""
    run = _run("r1", final_rating="", research_manager_output=_rendered("Buy"))
    result = rating_flip_rate([run])
    assert result.total == 0
    assert result.flip_rate is None


def test_a_run_with_no_research_manager_stage_is_excluded() -> None:
    """A run that failed before the research manager stage has no pre-risk-panel call to compare."""
    run = _run("r1", final_rating="Buy", research_manager_output=None)
    result = rating_flip_rate([run])
    assert result.total == 0


def test_a_research_manager_stage_with_empty_output_is_excluded() -> None:
    """A `research_manager` stage present in the plan but never actually run (still pending/blocked)
    has empty `output_md` -- must not default-parse to a spurious `Hold` comparison."""
    run = _run(
        "r1",
        final_rating="Buy",
        extra_stages=(_stage("research_manager", output_md=""),),
    )
    result = rating_flip_rate([run])
    assert result.total == 0


def test_aggregate_counts_and_rate_over_a_mixed_batch() -> None:
    runs = [
        _run("unchanged", final_rating="Hold", research_manager_output=_rendered("Hold")),
        _run("downgrade", final_rating="Hold", research_manager_output=_rendered("Buy")),
        _run("upgrade", final_rating="Overweight", research_manager_output=_rendered("Hold")),
        _run("excluded-no-rating", final_rating="", research_manager_output=_rendered("Buy")),
    ]

    result = rating_flip_rate(runs)

    assert result.total == 3
    assert result.flipped == 2
    assert result.unchanged == 1
    assert result.upgraded == 1
    assert result.downgraded == 1
    assert result.flip_rate == pytest.approx(2 / 3)

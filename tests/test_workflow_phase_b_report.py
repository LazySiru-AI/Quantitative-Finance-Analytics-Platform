"""Tests for `app.workflow.phase_b_report` -- the Round 33 Phase B status/decision report.

Every `CandidateObservation` and `DeskRun` this file needs is built directly and persisted through
the real `app.workflow.candidates.append_observations` / `app.agentdesk.store.RunStore.save`, never
through a live workflow run -- the same convention `tests/test_workflow_study.py` uses for the
neighbouring study module. `build_phase_b_report` itself performs no model call and no network call.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

from app.agentdesk.models import DeskRun
from app.agentdesk.store import RunStore
from app.agents.models import AgentBudget
from app.config import Settings
from app.workflow import candidates as candidates_mod
from app.workflow import phase_b_report as report_mod
from app.workflow.candidates import CandidateObservation, GateDecision
from app.workflow.phase_b_report import PhaseBReport, build_phase_b_report, render_markdown

_TODAY = dt.date(2026, 9, 1)


def _obs(
    *,
    obs_id: str,
    symbol: str,
    decision_date: dt.date,
    universe_source: str = "screen",
    state: str = "pending",
    forward_return_pct: str | None = None,
    unpriceable: bool = False,
    skip_reason: str | None = None,
    gates: tuple[GateDecision, ...] = (),
    avoided_cost_usd: str = "0",
) -> CandidateObservation:
    return CandidateObservation(
        obs_id=obs_id,
        run_id="run-1",
        symbol=symbol,
        decision_date=decision_date,
        agent_card_id="card-1",
        state=state,  # type: ignore[arg-type]
        forward_return_pct=Decimal(forward_return_pct) if forward_return_pct is not None else None,
        unpriceable=unpriceable,
        universe_source=universe_source,  # type: ignore[arg-type]
        skip_reason=skip_reason,
        gates=gates,
        avoided_cost_usd=Decimal(avoided_cost_usd),
    )


def _fresh_gates(*, passed: bool = True) -> tuple[GateDecision, ...]:
    return (
        GateDecision(gate="ta_gated", passed=passed, verdict_source="fresh"),
        GateDecision(gate="vibe_gated", passed=passed, verdict_source="fresh"),
        GateDecision(gate="full_workflow", passed=passed, verdict_source="fresh"),
    )


_SECTION_HEADERS = (
    "## Floor status",
    "## Accrual",
    "## Spend",
    "## Arm metrics (screen books)",
    "## Paired comparison (vs raw_signal/screened)",
    "## Discrimination",
    "## Verdict",
    "## Caveats",
)


def test_empty_tree_is_below_floor_with_zero_counters(settings: Settings) -> None:
    report = build_phase_b_report(settings, today=_TODAY)

    assert report.verdict == "below_floor"
    assert report.floor_met is False
    assert report.sessions_observed == 0
    assert report.first_session is None
    assert report.last_session is None
    assert report.distinct_symbols == 0
    assert report.observations_total == 0
    assert report.observations_resolved == 0
    assert report.observations_pending == 0
    assert report.observations_unpriceable == 0
    assert all(v == 0 for v in report.skip_reasons.values())
    assert all(v == 0 for v in report.verdict_sources.values())
    assert report.avoided_cost_usd == Decimal("0")
    assert all(v == 0 for v in report.gated_candidates_per_gate.values())
    assert report.resolved_mean_forward_return is None
    assert report.resolved_hit_rate is None
    assert report.screen_run_count == 0
    assert report.screen_spend_usd == Decimal("0")

    markdown = render_markdown(report)
    assert "MONITORING, NOT EVIDENCE" in markdown
    for header in _SECTION_HEADERS:
        assert header in markdown, header


def _seed_mixed_observations(settings: Settings) -> None:
    day1, day2, day3, day4, day5 = (
        dt.date(2026, 6, 1),
        dt.date(2026, 6, 2),
        dt.date(2026, 6, 3),
        dt.date(2026, 6, 4),
        dt.date(2026, 6, 5),
    )

    obs_a = _obs(
        obs_id="a", symbol="AAA", decision_date=day1, state="resolved",
        forward_return_pct="0.05", gates=_fresh_gates(passed=True),
    )
    # B: resolved with a forward return, and its full_workflow ruling came from a cached verdict --
    # exercises verdict_sources' "cached" bucket and avoided_cost_usd in the same row.
    obs_b = _obs(
        obs_id="b", symbol="BBB", decision_date=day2, state="resolved",
        forward_return_pct="-0.02",
        gates=(
            GateDecision(gate="ta_gated", passed=True, verdict_source="fresh"),
            GateDecision(gate="vibe_gated", passed=True, verdict_source="fresh"),
            GateDecision(gate="full_workflow", passed=False, verdict_source="cached"),
        ),
        avoided_cost_usd="2.50",
    )
    obs_c = _obs(
        obs_id="c", symbol="CCC", decision_date=day3, state="pending",
        gates=_fresh_gates(passed=True),
    )
    # D: the necessity-gate chain skipped it before any gate actually ruled -- must not count toward
    # gated_candidates_per_gate even though it still carries three (defaulted) GateDecisions.
    obs_d = _obs(
        obs_id="d", symbol="DDD", decision_date=day4, state="pending",
        skip_reason="budget_exhausted", gates=_fresh_gates(passed=False),
    )
    obs_e = _obs(
        obs_id="e", symbol="EEE", decision_date=day5, state="resolved",
        unpriceable=True, gates=_fresh_gates(passed=True),
    )
    # A card-mode row: must be excluded from every counter above.
    obs_card = _obs(
        obs_id="z", symbol="ZZZ", decision_date=day1, universe_source="card",
        state="resolved", forward_return_pct="0.99", gates=_fresh_gates(passed=True),
    )

    candidates_mod.append_observations(
        [obs_a, obs_b, obs_c, obs_d, obs_e, obs_card], settings=settings
    )


def test_mixed_observations_score_correctly_and_exclude_card_rows(settings: Settings) -> None:
    _seed_mixed_observations(settings)

    report = build_phase_b_report(settings, today=_TODAY)

    assert report.sessions_observed == 5
    assert report.first_session == dt.date(2026, 6, 1)
    assert report.last_session == dt.date(2026, 6, 5)
    assert report.distinct_symbols == 5  # AAA/BBB/CCC/DDD/EEE only -- ZZZ (card) excluded
    assert report.observations_total == 5
    assert report.observations_resolved == 3  # A, B, E
    assert report.observations_pending == 2  # C, D
    assert report.observations_unpriceable == 1  # E

    assert report.skip_reasons["budget_exhausted"] == 1
    assert sum(report.skip_reasons.values()) == 1

    # 5 observations x 3 gates each = 15 GateDecisions; exactly B's full_workflow is cached.
    assert report.verdict_sources == {"fresh": 14, "cached": 1, "mixed": 0}

    assert report.avoided_cost_usd == Decimal("2.50")

    # Ruled (skip_reason is None): A, B, C, E -- D is excluded from every gate's count.
    assert report.gated_candidates_per_gate == {
        "ta_gated": 4, "vibe_gated": 4, "full_workflow": 4,
    }

    # Only A and B are resolved, priced, and not unpriceable.
    assert report.resolved_mean_forward_return == Decimal("0.015")
    assert report.resolved_hit_rate == Decimal("0.5")

    # Below the real 60-session / 40-candidate floor.
    assert report.floor_met is False
    assert report.verdict == "below_floor"


def test_screen_run_count_and_spend_ignore_card_mode_runs(settings: Settings) -> None:
    store = RunStore(settings, "workflow")
    screen_run = DeskRun(
        run_id="screen-1", kind="workflow", state="succeeded",
        created_at=dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.UTC),
        config={"universe_mode": "screen"}, stages=(),
        budget=AgentBudget(cap_usd=Decimal("16"), spent_usd=Decimal("3.25")),
    )
    card_run = DeskRun(
        run_id="card-1", kind="workflow", state="succeeded",
        created_at=dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.UTC),
        config={"universe_mode": "card"}, stages=(),
        budget=AgentBudget(cap_usd=Decimal("16"), spent_usd=Decimal("9.00")),
    )
    store.save(screen_run)
    store.save(card_run)

    report = build_phase_b_report(settings, today=_TODAY)

    assert report.screen_run_count == 1
    assert report.screen_spend_usd == Decimal("3.25")


def test_floor_met_case_is_not_below_floor(settings: Settings, monkeypatch) -> None:
    monkeypatch.setattr(report_mod, "FLOOR_SESSIONS", 2)
    monkeypatch.setattr(report_mod, "FLOOR_GATED_CANDIDATES", 2)
    _seed_mixed_observations(settings)

    report = build_phase_b_report(settings, today=_TODAY)

    assert report.floor_sessions_required == 2
    assert report.floor_gated_required == 2
    assert report.floor_met is True
    assert report.verdict != "below_floor"
    # full_workflow ruled A (passed) and B (refused), both priced -- the m=1 discrimination test is
    # computable, so the untestable-gate branch must not fire either.
    assert report.verdict != "gate_not_measurable"


def test_render_markdown_is_deterministic_and_json_round_trips(settings: Settings) -> None:
    _seed_mixed_observations(settings)
    report = build_phase_b_report(settings, today=_TODAY)

    assert render_markdown(report) == render_markdown(report)

    payload = report.model_dump(mode="json")
    # Round-trips through real JSON (not just the Python dict) -- catches anything that dumps to a
    # non-JSON-native type (Decimal, date) without a mode="json" encoder.
    reloaded = PhaseBReport.model_validate(json.loads(json.dumps(payload)))
    assert reloaded == report

"""Smoke tests for `tools/compare_prompts.py`: argument parsing, the dry-run path (zero model calls),
and the invariance-comparison logic against synthetic before/after `SideResult` objects.

No test here makes a real model call, and no test starts a real `tradingagents` or `vibedesk` run --
`run_one_side` is exercised only far enough to prove it fails fast (before touching either child
service) when its telemetry prerequisite is unavailable. `main`'s dry-run path is proven to never
reach `run_one_side` at all, by monkeypatching it to raise if called.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest

import tools.compare_prompts as cp
from app.config import Settings

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def test_parse_args_dry_run_defaults() -> None:
    args = cp.parse_args(["--trade-date", "2026-06-15"])
    assert args.symbol == "AAPL"
    assert args.trade_date == dt.date(2026, 6, 15)
    assert args.baseline_ref == "HEAD"
    assert args.live is False
    assert args.budget_usd is None
    assert args.min_checked_token_ratio == pytest.approx(0.5)


def test_parse_args_requires_trade_date() -> None:
    with pytest.raises(SystemExit):
        cp.parse_args(["--symbol", "AAPL"])


def test_parse_args_rejects_bad_date() -> None:
    with pytest.raises(SystemExit):
        cp.parse_args(["--trade-date", "not-a-date"])


def test_parse_args_live_requires_budget() -> None:
    with pytest.raises(SystemExit):
        cp.parse_args(["--trade-date", "2026-06-15", "--live"])


def test_parse_args_budget_without_live_rejected() -> None:
    with pytest.raises(SystemExit):
        cp.parse_args(["--trade-date", "2026-06-15", "--budget-usd", "4.00"])


def test_parse_args_live_with_budget_ok() -> None:
    args = cp.parse_args(["--trade-date", "2026-06-15", "--live", "--budget-usd", "8.00"])
    assert args.live is True
    assert args.budget_usd == Decimal("8.00")


def test_parse_args_rejects_nonpositive_budget() -> None:
    with pytest.raises(SystemExit):
        cp.parse_args(["--trade-date", "2026-06-15", "--live", "--budget-usd", "0"])
    with pytest.raises(SystemExit):
        cp.parse_args(["--trade-date", "2026-06-15", "--live", "--budget-usd", "-1"])


# ---------------------------------------------------------------------------
# The dry-run plan
# ---------------------------------------------------------------------------


def test_build_plan_dry_run_makes_no_calls_claim() -> None:
    args = cp.parse_args(["--symbol", "MSFT", "--trade-date", "2026-06-15", "--baseline-ref", "abc123"])
    plan = cp.build_plan(args)
    assert plan["mode"] == "dry_run"
    assert plan["will_make_model_calls"] is False
    assert plan["fixture"]["symbol"] == "MSFT"
    assert plan["fixture"]["trade_date"] == "2026-06-15"
    assert plan["baseline_selection_mechanism"] == "git-ref"
    assert plan["baseline_ref"] == "abc123"
    assert len(plan["sides"]) == 2
    assert {side["label"] for side in plan["sides"]} == {"baseline", "candidate"}
    assert plan["budget_usd_total"] is None


def test_build_plan_live_splits_budget_four_ways() -> None:
    args = cp.parse_args(
        ["--trade-date", "2026-06-15", "--live", "--budget-usd", "8.00"]
    )
    plan = cp.build_plan(args)
    assert plan["mode"] == "live"
    assert plan["will_make_model_calls"] is True
    assert plan["budget_usd_total"] == "8.00"
    assert plan["budget_usd_per_child_run"] == "2.0000"


def test_main_dry_run_never_calls_run_one_side(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("run_one_side must never be called in dry-run mode")

    monkeypatch.setattr(cp, "run_one_side", _boom)
    exit_code = cp.main(["--trade-date", "2026-06-15"])
    assert exit_code == 0

    out = capsys.readouterr().out
    plan = json.loads(out)
    assert plan["mode"] == "dry_run"
    assert plan["will_make_model_calls"] is False


# ---------------------------------------------------------------------------
# Comparison logic -- synthetic before/after SideResults
# ---------------------------------------------------------------------------


def _grounding(stage_id: str, *, ok: bool = True, attempts: int = 1, checked_tokens: int = 10) -> cp.StageGrounding:
    return cp.StageGrounding(stage_id=stage_id, ok=ok, attempts=attempts, checked_tokens=checked_tokens)


def _side(
    label: str,
    *,
    ta_final_rating: str = "Buy",
    ta_state: str = "succeeded",
    vibe_verdict: str = "SUPPORT",
    vibe_explicit: bool = True,
    ta_grounding: tuple[cp.StageGrounding, ...] = (),
    vibe_grounding: tuple[cp.StageGrounding, ...] = (),
    output_tokens: int = 1000,
) -> cp.SideResult:
    return cp.SideResult(
        label=label,
        symbol="AAPL",
        trade_date=dt.date(2026, 6, 15),
        ta_run_id=f"ta-{label}",
        ta_state=ta_state,
        ta_final_rating=ta_final_rating,
        ta_final_md="rating: " + ta_final_rating,
        ta_stage_grounding=ta_grounding or (_grounding("portfolio_manager", checked_tokens=50),),
        ta_fields={"final_rating": ta_final_rating},
        vibe_run_id=f"vibe-{label}",
        vibe_state="succeeded",
        vibe_verdict=vibe_verdict,  # type: ignore[arg-type]
        vibe_verdict_explicit=vibe_explicit,
        vibe_final_md=f"VERDICT: {vibe_verdict}",
        vibe_stage_grounding=vibe_grounding or (_grounding("verdict", checked_tokens=20),),
        vibe_fields={"verdict": vibe_verdict},
        call_count=7,
        input_tokens=500,
        output_tokens=output_tokens,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
        cost_usd=Decimal("1.23"),
    )


def test_compare_sides_identical_passes() -> None:
    baseline = _side("baseline")
    candidate = _side("candidate")
    report = cp.compare_sides(baseline, candidate)
    assert report.passed is True
    assert report.issues == ()
    # All four arms must agree between two identical sides.
    for base_pass, cand_pass in report.arm_results.values():
        assert base_pass == cand_pass


def test_compare_sides_fails_on_changed_rating() -> None:
    """The required FAIL case: a compressed prompt that changed the portfolio manager's rating must
    be caught, not waved through."""
    baseline = _side("baseline", ta_final_rating="Buy")
    candidate = _side("candidate", ta_final_rating="Hold")
    report = cp.compare_sides(baseline, candidate)
    assert report.passed is False
    assert any("final_rating changed" in issue for issue in report.issues)


def test_compare_sides_fails_on_changed_verdict() -> None:
    baseline = _side("baseline", vibe_verdict="SUPPORT")
    candidate = _side("candidate", vibe_verdict="REFUTE")
    report = cp.compare_sides(baseline, candidate)
    assert report.passed is False
    assert any("VERDICT changed" in issue for issue in report.issues)


def test_compare_sides_fails_on_arm_gate_divergence_without_rating_change() -> None:
    """Same TA rating string on both sides, but the candidate's TA stage did not actually succeed --
    `ta_gated`/`full_workflow` must flip even though `final_rating` text matches."""
    baseline = _side("baseline", ta_final_rating="Buy", ta_state="succeeded")
    candidate = _side("candidate", ta_final_rating="Buy", ta_state="degraded")
    report = cp.compare_sides(baseline, candidate)
    assert report.passed is False
    assert any("ta_gated" in issue for issue in report.issues)
    assert report.arm_results["ta_gated"] == (True, False)


def test_compare_sides_fails_on_grounding_regression() -> None:
    baseline = _side("baseline")
    candidate = _side(
        "candidate",
        vibe_grounding=(_grounding("verdict", ok=False, checked_tokens=20),),
    )
    report = cp.compare_sides(baseline, candidate)
    assert report.passed is False
    assert any("ungrounded/degraded" in issue for issue in report.issues)


def test_compare_sides_fails_on_new_grounding_retries() -> None:
    baseline = _side("baseline", ta_grounding=(_grounding("portfolio_manager", attempts=1, checked_tokens=50),))
    candidate = _side("candidate", ta_grounding=(_grounding("portfolio_manager", attempts=3, checked_tokens=50),))
    report = cp.compare_sides(baseline, candidate)
    assert report.passed is False
    assert any("more grounding retries" in issue for issue in report.issues)


def test_compare_sides_fails_on_checked_token_collapse() -> None:
    baseline = _side(
        "baseline",
        ta_grounding=(_grounding("portfolio_manager", checked_tokens=100),),
        vibe_grounding=(_grounding("verdict", checked_tokens=100),),
    )
    candidate = _side(
        "candidate",
        ta_grounding=(_grounding("portfolio_manager", checked_tokens=5),),
        vibe_grounding=(_grounding("verdict", checked_tokens=5),),
    )
    report = cp.compare_sides(baseline, candidate, min_checked_token_ratio=0.5)
    assert report.passed is False
    assert any("checked_tokens collapsed" in issue for issue in report.issues)


def test_compare_sides_allows_rounding_below_ratio_but_above_floor() -> None:
    baseline = _side(
        "baseline",
        ta_grounding=(_grounding("portfolio_manager", checked_tokens=100),),
        vibe_grounding=(_grounding("verdict", checked_tokens=100),),
    )
    candidate = _side(
        "candidate",
        ta_grounding=(_grounding("portfolio_manager", checked_tokens=60),),
        vibe_grounding=(_grounding("verdict", checked_tokens=60),),
    )
    report = cp.compare_sides(baseline, candidate, min_checked_token_ratio=0.5)
    assert report.passed is True


def test_compare_sides_field_dump_has_both_sides() -> None:
    baseline = _side("baseline")
    candidate = _side("candidate")
    report = cp.compare_sides(baseline, candidate)
    assert "ta.final_rating" in report.field_dump
    base_val, cand_val = report.field_dump["ta.final_rating"]
    assert base_val == "Buy"
    assert cand_val == "Buy"


def test_compare_sides_token_delta_reports_savings() -> None:
    baseline = _side("baseline", output_tokens=1000)
    candidate = _side("candidate", output_tokens=250)
    report = cp.compare_sides(baseline, candidate)
    assert report.token_delta["output_tokens_saved"] == 750
    assert report.token_delta["output_tokens_saved_pct"] == pytest.approx(75.0)


def test_render_report_contains_pass_fail_and_fixture(capsys: pytest.CaptureFixture[str]) -> None:
    baseline = _side("baseline")
    candidate = _side("candidate", ta_final_rating="Hold")
    report = cp.compare_sides(baseline, candidate)
    text = cp.render_report(report, baseline, candidate)
    assert "FAIL" in text
    assert "AAPL" in text
    assert "2026-06-15" in text


# ---------------------------------------------------------------------------
# Baseline loading from git (read-only; this repo's own history)
# ---------------------------------------------------------------------------


def test_load_baseline_prompts_from_head_has_system_for_role() -> None:
    module = cp.load_baseline_prompts("HEAD")
    assert hasattr(module, "SYSTEM_FOR_ROLE")
    assert "portfolio_manager" in module.SYSTEM_FOR_ROLE


def test_load_baseline_prompts_bad_ref_raises() -> None:
    with pytest.raises(cp.BaselineLoadError):
        cp.load_baseline_prompts("this-ref-does-not-exist-anywhere")


def test_load_baseline_preset_from_head_parses_json() -> None:
    """`followup_review.json` is being actively developed by another agent alongside this one (see
    the task brief's concurrency note) and may not be committed at HEAD yet in a given checkout --
    that is a fact about this repository's git history, not a defect in `load_baseline_preset`, so
    this test skips rather than fails when the path is not yet in history."""
    try:
        data = cp.load_baseline_preset("HEAD")
    except cp.BaselineLoadError as exc:
        pytest.skip(f"followup_review.json not committed at HEAD yet: {exc}")
    assert data["name"] == "followup_review"
    assert "agents" in data


# ---------------------------------------------------------------------------
# Evidence determinism
# ---------------------------------------------------------------------------


def test_evidence_fingerprint_is_stable_for_same_inputs(settings: Settings) -> None:
    fp1 = cp.evidence_fingerprint("AAPL", dt.date(2026, 6, 15), settings=settings)
    fp2 = cp.evidence_fingerprint("AAPL", dt.date(2026, 6, 15), settings=settings)
    assert fp1 == fp2
    assert len(fp1) == 64  # sha256 hex digest


# ---------------------------------------------------------------------------
# run_one_side's telemetry guard -- fails fast, before any child service call
# ---------------------------------------------------------------------------


def test_run_one_side_raises_without_making_calls_when_telemetry_missing(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    monkeypatch.setattr(cp, "agent_telemetry", None)

    def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("no child desk service may be called when telemetry is unavailable")

    monkeypatch.setattr(cp.ta_service, "start_run", _boom)
    monkeypatch.setattr(cp.vibe_service, "start_run", _boom)

    args = cp.parse_args(["--trade-date", "2026-06-15", "--live", "--budget-usd", "4.00"])
    with pytest.raises(cp.LiveExecutionUnavailable):
        cp.run_one_side(
            "candidate", args, settings=settings,
            prompts_module=None, preset_data=None,
            per_child_budget_usd=Decimal("1.00"),
        )


# ---------------------------------------------------------------------------
# Telemetry integration -- skips cleanly if app.agentdesk.telemetry is not yet present
# ---------------------------------------------------------------------------


def test_telemetry_summarize_calls_empty_list_is_zero() -> None:
    """Exercises the real pinned API (`CallCostSummary`, `summarize_calls`) this harness depends on.
    Skips rather than fails if `app.agentdesk.telemetry` has not landed yet -- see the module docstring
    of `tools/compare_prompts.py` for why the import there is soft."""
    telemetry = pytest.importorskip("app.agentdesk.telemetry")
    settings = Settings(data_dir=Path("."))
    summary = telemetry.summarize_calls([], settings=settings)
    assert summary.call_count == 0
    assert summary.input_tokens == 0
    assert summary.cost_usd == Decimal(0)


def test_telemetry_available_flag_matches_import() -> None:
    try:
        import app.agentdesk.telemetry  # noqa: F401
    except ImportError:
        assert cp.TELEMETRY_AVAILABLE is False
    else:
        assert cp.TELEMETRY_AVAILABLE is True

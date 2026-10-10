"""Unit tests for `app.workflow.analysis.gate_concordance` -- the TA-vs-Vibe contingency table.

Pure arithmetic over a synthetic `CandidateObservation` list; no settings fixture or disk I/O
involved, matching the module's own read/compute split (see its docstring).
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.workflow.analysis import gate_concordance
from app.workflow.candidates import CandidateObservation, GateDecision


def _observation(
    symbol: str,
    *,
    ta_passed: bool | None,
    vibe_passed: bool | None,
    ta_detail: str = "Buy",
    vibe_detail: str = "SUPPORT",
) -> CandidateObservation:
    gates = []
    if ta_passed is not None:
        gates.append(GateDecision(gate="ta_gated", passed=ta_passed, detail=ta_detail))
    if vibe_passed is not None:
        gates.append(GateDecision(gate="vibe_gated", passed=vibe_passed, detail=vibe_detail))
    # full_workflow is the AND of the other two -- included on every row exactly as
    # `app.workflow.pipeline._stage_orders` always attaches it, to prove `gate_concordance`
    # ignores it rather than accidentally reading it as a third opinion.
    full = bool(ta_passed) and bool(vibe_passed)
    gates.append(GateDecision(gate="full_workflow", passed=full, detail="n/a"))
    return CandidateObservation(
        obs_id=f"obs-{symbol}",
        run_id="run-1",
        symbol=symbol,
        decision_date=dt.date(2026, 8, 3),
        agent_card_id="B-momentum",
        gates=tuple(gates),
    )


def test_empty_log_reports_zero_total_and_no_rate() -> None:
    result = gate_concordance([])
    assert result.total == 0
    assert result.agreement_rate is None
    assert result.disagreement_count == 0


def test_contingency_table_and_agreement_rate_over_all_four_cells() -> None:
    """One candidate in each of the 2x2 cells: both pass, TA-only, Vibe-only, neither.

    Agreement (both_pass + neither) = 2 of 4 -> agreement_rate 0.5; disagreement (ta_only +
    vibe_only) = 2. Distinct enough values that the test cannot pass by a swapped column/row.
    """
    observations = [
        _observation("AAA", ta_passed=True, vibe_passed=True),
        _observation("BBB", ta_passed=True, vibe_passed=False),
        _observation("CCC", ta_passed=False, vibe_passed=True),
        _observation("DDD", ta_passed=False, vibe_passed=False),
    ]

    result = gate_concordance(observations)

    assert result.total == 4
    assert result.both_pass == 1
    assert result.ta_only == 1
    assert result.vibe_only == 1
    assert result.neither == 1
    assert result.disagreement_count == 2
    assert result.agreement_rate == pytest.approx(0.5)


def test_full_agreement_yields_rate_one_and_zero_disagreement() -> None:
    observations = [
        _observation("AAA", ta_passed=True, vibe_passed=True),
        _observation("BBB", ta_passed=False, vibe_passed=False),
        _observation("CCC", ta_passed=True, vibe_passed=True),
    ]

    result = gate_concordance(observations)

    assert result.total == 3
    assert result.disagreement_count == 0
    assert result.agreement_rate == pytest.approx(1.0)


def test_a_candidate_missing_one_gates_ruling_is_excluded_not_counted_as_a_refusal() -> None:
    """A candidate that only ever got a TA ruling (the `vibe_gated` arm was disabled for that run)
    must not be silently treated as a Vibe refusal -- it is excluded from the table entirely, the
    same way `app.workflow.candidates.GateDecision.was_explicit` distinguishes an abstention from a
    judgement on the sibling log.
    """
    observations = [
        _observation("AAA", ta_passed=True, vibe_passed=None),
        _observation("BBB", ta_passed=True, vibe_passed=True),
    ]

    result = gate_concordance(observations)

    assert result.total == 1
    assert result.both_pass == 1
    assert result.ta_only == 0

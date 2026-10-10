"""Tests for the Agent Workflow effectiveness study (`backend/app/workflow/study.py`).

Every `BookState` and `CandidateObservation` this file needs is built directly as a Python object and
persisted through the real `app.workflow.book.save_book` / `app.workflow.candidates.append_observations`
-- never through a live workflow run, and never over the network. `build_study` itself performs no
model calls; the only stored bars this file writes are SPY's, for the benchmark return.

The telemetry-extension tests below (`research_*_tokens`, `grounding_retry_rate`/
`grounding_retry_waste_usd`) additionally persist real `DeskRun` objects through
`app.agentdesk.store.RunStore` and real `AgentCall` archives under `agent_calls_dir`, the same
convention `tests/test_workflow_telemetry.py` and `tests/test_agentdesk_telemetry.py` use, since
those fields are computed by walking the workflow/child run store rather than the book/candidate log.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pandas as pd
import pytest

from app.agentdesk.models import DeskRun, GroundingVerdict, StageRecord
from app.agentdesk.store import RunStore
from app.agents.models import AgentBudget, AgentCall, agent_calls_dir
from app.config import Settings
from app.db import duck
from app.market.models import BAR_COLUMNS, Interval
from app.workflow import book as book_mod
from app.workflow import candidates as candidates_mod
from app.workflow import study
from app.workflow.book_models import BookState, EquityPoint, WorkflowFillRecord, WorkflowOrderRecord

# ---------------------------------------------------------------------------
# Builders -- local to this file; see tests/test_workflow_book.py's own module docstring for why
# each test file keeps its own copy rather than sharing one.
# ---------------------------------------------------------------------------


def _weekdays(anchor: dt.date, count: int) -> list[dt.date]:
    dates: list[dt.date] = []
    day = anchor
    while len(dates) < count:
        if day.weekday() < 5:
            dates.append(day)
        day += dt.timedelta(days=1)
    return dates


def _write_bars(settings: Settings, symbol: str, prices: dict[dt.date, float]) -> None:
    """One flat (open == close) daily bar per date -- the study only ever reads `close` for the
    benchmark window, so a single price per day is enough."""
    dates = sorted(prices)
    closes = [prices[d] for d in dates]
    frame = pd.DataFrame(
        {
            "ts": pd.Series(
                [dt.datetime.combine(d, dt.time.min, tzinfo=dt.UTC) for d in dates],
                dtype="datetime64[us, UTC]",
            ),
            "open": closes,
            "high": [c + 5.0 for c in closes],
            "low": [c - 5.0 for c in closes],
            "close": closes,
            "adj_close": closes,
            "volume": [1_000_000] * len(dates),
        },
        columns=list(BAR_COLUMNS),
    )
    with duck.connect() as conn:
        duck.write_bars(conn, settings.bars_dir, symbol, Interval.DAY, frame)


def _filled_order(
    *,
    order_id: str,
    arm: str,
    symbol: str,
    side: str,
    fill_date: dt.date,
    price: str,
    qty: str,
    price_source: str = "stored_open",
    created_by_run_id: str = "run-1",
) -> WorkflowOrderRecord:
    fill = WorkflowFillRecord(
        price=Decimal(price),
        price_source=price_source,  # type: ignore[arg-type]
        qty=Decimal(qty),
        slippage=Decimal("0"),
        fees=Decimal("0"),
        reference_open=Decimal(price),
        filled_at=dt.datetime.combine(fill_date, dt.time(9, 30), tzinfo=dt.UTC),
    )
    return WorkflowOrderRecord(
        order_id=order_id,
        arm=arm,  # type: ignore[arg-type]
        agent_card_id="card-1",
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        notional=Decimal(price) * Decimal(qty),
        decision_date=fill_date - dt.timedelta(days=1),
        fill_date=fill_date,
        status="filled",
        thesis="a study test thesis",
        invalidation="a study test invalidation",
        created_by_run_id=created_by_run_id,
        fill=fill,
    )


def _book(
    *, arm: str, equity_by_date: dict[dt.date, str], orders: tuple[WorkflowOrderRecord, ...]
) -> BookState:
    return BookState(
        arm=arm,  # type: ignore[arg-type]
        current_card_id="card-1",
        card_adopted_date=min(equity_by_date),
        starting_cash=study.STARTING_CASH,
        broker_state={},
        orders=orders,
        equity_curve=tuple(
            EquityPoint(date=d, equity=Decimal(v)) for d, v in sorted(equity_by_date.items())
        ),
        as_of=max(equity_by_date),
    )


def _candidate(
    *,
    obs_id: str,
    symbol: str,
    gate: str,
    passed: bool,
    forward_return_pct: str,
    was_explicit: bool = True,
    decision_date: dt.date = dt.date(2026, 5, 1),
) -> candidates_mod.CandidateObservation:
    return candidates_mod.CandidateObservation(
        obs_id=obs_id,
        run_id="run-1",
        symbol=symbol,
        decision_date=decision_date,
        agent_card_id="card-1",
        regime="risk_on",
        entry_rank=1,
        gates=(
            candidates_mod.GateDecision(
                gate=gate, passed=passed, detail="", was_explicit=was_explicit  # type: ignore[arg-type]
            ),
        ),
        state="resolved",
        horizon_days=candidates_mod.HOLDING_DAYS,
        forward_return_pct=Decimal(forward_return_pct),
        benchmark_return_pct=Decimal("0"),
        alpha_return_pct=Decimal(forward_return_pct),
        resolved_at=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
        unpriceable=False,
    )


def _write_call(settings: Settings, *, call_id: str, cost_usd: str, input_tokens: int = 0, output_tokens: int = 0) -> None:
    call = AgentCall(
        call_id=call_id, role="market_analyst", model="claude-opus-5",
        created_at=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
        system="sys", user="user", raw_response="resp",
        input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=Decimal(cost_usd),
    )
    directory = agent_calls_dir(settings)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{call_id}.json").write_text(call.model_dump_json(indent=2), encoding="utf-8")


def _child_desk_run(
    *, run_id: str, kind: str, stages: tuple[StageRecord, ...]
) -> DeskRun:
    return DeskRun(
        run_id=run_id, kind=kind,  # type: ignore[arg-type]
        state="succeeded", created_at=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
        stages=stages, budget=AgentBudget(cap_usd=Decimal("5.00")),
    )


def _workflow_desk_run(
    *, run_id: str, child_runs: dict[str, str], own_stages: tuple[StageRecord, ...] = ()
) -> DeskRun:
    return DeskRun(
        run_id=run_id, kind="workflow", state="succeeded",
        created_at=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
        config={"child_runs": child_runs},
        stages=own_stages, budget=AgentBudget(cap_usd=Decimal("10.00")),
    )


# ---------------------------------------------------------------------------
# 1. adjusted_excess -- exposure correction flips the ranking vs raw total_return
# ---------------------------------------------------------------------------


class TestAdjustedExcessAppliesTheExposureCorrection:
    def test_a_low_exposure_lower_return_arm_outranks_raw_once_corrected(self, settings: Settings) -> None:
        dates = _weekdays(dt.date(2026, 5, 4), 5)  # 5 trading sessions
        d1, d2, d3, d4, d5 = dates

        # SPY: +20% over the window (100 -> 120), first/last close is all `_window_return` reads.
        _write_bars(settings, "SPY", {d1: 100.0, d2: 105.0, d3: 110.0, d4: 115.0, d5: 120.0})

        # raw_signal: 100000 -> 115000 (+15%), invested every one of the 5 sessions (one buy on d1,
        # never sold) -> exposure == 1.0 after the D1-style undilute correction.
        raw_orders = (
            _filled_order(
                order_id="raw-0", arm="raw_signal", symbol="RAW", side="buy",
                fill_date=d1, price="50", qty="100",
            ),
        )
        raw_equity = {
            d1: "103000", d2: "106000", d3: "109000", d4: "112000", d5: "115000",
        }
        raw_book = _book(arm="raw_signal", equity_by_date=raw_equity, orders=raw_orders)
        book_mod.save_book(settings, raw_book)

        # ta_gated: 100000 -> 110000 (+10%), invested on exactly 1 of the 5 sessions (buy d1, sell
        # d2) -> exposure == 0.2 after undiluting.
        ta_orders = (
            _filled_order(
                order_id="ta-0", arm="ta_gated", symbol="TAG", side="buy",
                fill_date=d1, price="50", qty="100",
            ),
            _filled_order(
                order_id="ta-1", arm="ta_gated", symbol="TAG", side="sell",
                fill_date=d2, price="55", qty="100",
            ),
        )
        ta_equity = {
            d1: "102000", d2: "105000", d3: "107000", d4: "109000", d5: "110000",
        }
        ta_book = _book(arm="ta_gated", equity_by_date=ta_equity, orders=ta_orders)
        book_mod.save_book(settings, ta_book)

        result = study.build_study(settings=settings, arms=("raw_signal", "ta_gated"))

        assert result.benchmark_return == Decimal("0.2")
        by_arm = {row.arm: row for row in result.arms}

        raw_row = by_arm["raw_signal"]
        ta_row = by_arm["ta_gated"]

        assert raw_row.total_return == pytest.approx(Decimal("0.15"))
        assert raw_row.exposure == pytest.approx(Decimal("1.0"))
        assert raw_row.adjusted_excess == pytest.approx(Decimal("0.15") - Decimal("1.0") * Decimal("0.2"))

        assert ta_row.total_return == pytest.approx(Decimal("0.10"))
        assert ta_row.exposure == pytest.approx(Decimal("0.2"))
        assert ta_row.adjusted_excess == pytest.approx(Decimal("0.10") - Decimal("0.2") * Decimal("0.2"))

        # Raw total_return alone ranks raw_signal above ta_gated ...
        assert raw_row.total_return > ta_row.total_return
        # ... but the exposure-corrected primary metric reverses that ranking -- proving the
        # correction is not a cosmetic extra field, it actually changes which arm looks better.
        assert ta_row.adjusted_excess > raw_row.adjusted_excess
        assert raw_row.adjusted_excess < 0
        assert ta_row.adjusted_excess > 0

        # win_rate: raw never closed a trade (still open) -> None; ta_gated closed one winner.
        assert raw_row.win_rate is None
        assert ta_row.win_rate == pytest.approx(1.0)

        # research_cost_usd degrades to zero with no DeskRun on disk to attribute cost to.
        assert raw_row.research_cost_usd == Decimal(0)
        assert ta_row.research_cost_usd == Decimal(0)
        assert ta_row.net_adjusted_excess == ta_row.adjusted_excess

        paired = {p.arm: p for p in result.paired}
        assert "ta_gated" in paired
        # 5 common trading days -- enough for `stationary_bootstrap_p`'s own floor (>= 3) to return
        # a real value rather than `None`.
        assert paired["ta_gated"].bootstrap_p is not None


# ---------------------------------------------------------------------------
# 2. build_study degrades gracefully for an arm that has never run
# ---------------------------------------------------------------------------


class TestNeverRunArmDegradesToZero:
    def test_a_fresh_unwritten_book_scores_as_all_zero_not_an_error(self, settings: Settings) -> None:
        result = study.build_study(settings=settings, arms=("raw_signal", "vibe_gated", "full_workflow"))
        assert result.window is None
        assert result.benchmark_return is None
        for row in result.arms:
            assert row.total_return == Decimal(0)
            assert row.trades == 0
            assert row.research_cost_usd == Decimal(0)
        # raw_signal loaded as a fresh, empty book (`{}` daily returns, not `None`), so `paired` still
        # gets an entry per treated arm -- each one degenerate (no common trading days at all).
        assert {p.arm for p in result.paired} == {"vibe_gated", "full_workflow"}
        for p in result.paired:
            assert p.mean_daily_diff == Decimal(0)
            assert p.bootstrap_p is None


# ---------------------------------------------------------------------------
# 3. The discrimination test separates a gate that passes winners from one that passes losers
# ---------------------------------------------------------------------------


class TestDiscriminationTestSeparatesGoodFromBadGates:
    def test_ta_gated_passes_winners_vibe_gated_passes_losers(self, settings: Settings) -> None:
        rows = []
        # ta_gated: passing correlates with a positive forward return (a good gate).
        for i in range(5):
            rows.append(
                _candidate(obs_id=f"ta-pass-win-{i}", symbol="AAA", gate="ta_gated", passed=True, forward_return_pct="0.05")
            )
        rows.append(
            _candidate(obs_id="ta-pass-lose-0", symbol="AAA", gate="ta_gated", passed=True, forward_return_pct="-0.02")
        )
        for i in range(1):
            rows.append(
                _candidate(obs_id=f"ta-refuse-win-{i}", symbol="AAA", gate="ta_gated", passed=False, forward_return_pct="0.05")
            )
        for i in range(5):
            rows.append(
                _candidate(obs_id=f"ta-refuse-lose-{i}", symbol="AAA", gate="ta_gated", passed=False, forward_return_pct="-0.02")
            )

        # vibe_gated: the mirror image -- passing correlates with a negative forward return (a bad
        # gate that refuses the very candidates that go on to win).
        for i in range(1):
            rows.append(
                _candidate(
                    obs_id=f"vibe-pass-win-{i}", symbol="BBB", gate="vibe_gated", passed=True,
                    forward_return_pct="0.05", was_explicit=(i % 3 != 0),
                )
            )
        for i in range(5):
            rows.append(
                _candidate(
                    obs_id=f"vibe-pass-lose-{i}", symbol="BBB", gate="vibe_gated", passed=True,
                    forward_return_pct="-0.02", was_explicit=(i % 3 != 0),
                )
            )
        for i in range(5):
            rows.append(
                _candidate(
                    obs_id=f"vibe-refuse-win-{i}", symbol="BBB", gate="vibe_gated", passed=False,
                    forward_return_pct="0.05", was_explicit=(i % 3 != 0),
                )
            )
        rows.append(
            _candidate(
                obs_id="vibe-refuse-lose-0", symbol="BBB", gate="vibe_gated", passed=False,
                forward_return_pct="-0.02", was_explicit=True,
            )
        )

        candidates_mod.append_observations(rows, settings=settings)

        result = study.build_study(settings=settings, arms=("raw_signal",))
        by_gate = {row.gate: row for row in result.discrimination}

        assert set(by_gate) == {"ta_gated", "vibe_gated", "full_workflow"}

        ta = by_gate["ta_gated"]
        assert ta.passed_n == 6
        assert ta.refused_n == 6
        assert ta.mean_diff is not None and ta.mean_diff > 0
        assert ta.passed_hit_rate is not None and ta.refused_hit_rate is not None
        assert ta.passed_hit_rate > ta.refused_hit_rate
        assert ta.p_value is not None
        assert ta.q_value is not None

        vibe = by_gate["vibe_gated"]
        assert vibe.passed_n == 6
        assert vibe.refused_n == 6
        assert vibe.mean_diff is not None and vibe.mean_diff < 0
        assert vibe.passed_hit_rate is not None and vibe.refused_hit_rate is not None
        assert vibe.passed_hit_rate < vibe.refused_hit_rate
        assert vibe.p_value is not None

        # full_workflow never appeared in the candidate log -- untestable, but keeps its BH slot.
        full = by_gate["full_workflow"]
        assert full.passed_n == 0
        assert full.refused_n == 0
        assert full.p_value is None
        assert full.q_value is None

        # vibe_verdict_compliance: 12 vibe_gated decisions total. `was_explicit=(i % 3 != 0)` over the
        # two 5-row groups gives 3 explicit each (i=1,2,4); the 1-row "pass-win" group's i=0 is
        # False; the 1-row "refuse-lose" is hardcoded True. Explicit total: 0 + 3 + 3 + 1 = 7 of 12.
        assert result.vibe_verdict_compliance == pytest.approx(Decimal("7") / Decimal("12"))


# ---------------------------------------------------------------------------
# 4. vibe_verdict_compliance in isolation
# ---------------------------------------------------------------------------


class TestVibeVerdictCompliance:
    def test_counts_explicit_versus_defaulted_separately_from_pass_fail(self, settings: Settings) -> None:
        rows = [
            _candidate(obs_id="v0", symbol="AAA", gate="vibe_gated", passed=True, forward_return_pct="0.01", was_explicit=True),
            _candidate(obs_id="v1", symbol="AAA", gate="vibe_gated", passed=False, forward_return_pct="0.01", was_explicit=True),
            _candidate(obs_id="v2", symbol="AAA", gate="vibe_gated", passed=False, forward_return_pct="0.01", was_explicit=False),
            # A ta_gated decision on the same observation must not count toward vibe compliance.
            _candidate(obs_id="v3", symbol="AAA", gate="ta_gated", passed=True, forward_return_pct="0.01", was_explicit=False),
        ]
        candidates_mod.append_observations(rows, settings=settings)

        result = study.build_study(settings=settings, arms=("raw_signal",))
        assert result.vibe_verdict_compliance == pytest.approx(Decimal("2") / Decimal("3"))

    def test_none_when_the_candidate_log_has_no_vibe_gated_decisions_at_all(self, settings: Settings) -> None:
        result = study.build_study(settings=settings, arms=("raw_signal",))
        assert result.vibe_verdict_compliance is None


# ---------------------------------------------------------------------------
# 5. research_*_tokens -- the shared child-walk bills tradingagents vs vibedesk children correctly
# ---------------------------------------------------------------------------


class TestResearchTokenTelemetryWalksBothChildDeskKinds:
    def test_ta_gated_bills_only_tradingagents_children_full_workflow_bills_both(self, settings: Settings) -> None:
        _write_call(settings, call_id="ta-call-1", cost_usd="0.10", input_tokens=100, output_tokens=20)
        _write_call(settings, call_id="ta-call-2", cost_usd="0.05", input_tokens=50, output_tokens=10)
        _write_call(settings, call_id="vibe-call-1", cost_usd="0.30", input_tokens=200, output_tokens=40)

        ta_child = _child_desk_run(
            run_id="ta-child-1", kind="tradingagents",
            stages=(
                StageRecord(
                    stage_id="market_analyst", role="market_analyst", label="Market Analyst",
                    state="succeeded", call_ids=("ta-call-1", "ta-call-2"),
                ),
            ),
        )
        vibe_child = _child_desk_run(
            run_id="vibe-child-1", kind="vibedesk",
            stages=(
                StageRecord(
                    stage_id="verdict", role="market_analyst", label="Verdict",
                    state="succeeded", call_ids=("vibe-call-1",),
                ),
            ),
        )
        RunStore(settings, "tradingagents").save(ta_child)
        RunStore(settings, "vibedesk").save(vibe_child)

        workflow_run = _workflow_desk_run(
            run_id="run-1", child_runs={"research_TAG": "ta-child-1", "vibe_TAG": "vibe-child-1"},
        )
        RunStore(settings, "workflow").save(workflow_run)

        d1 = dt.date(2026, 5, 4)
        ta_orders = (
            _filled_order(
                order_id="ta-0", arm="ta_gated", symbol="TAG", side="buy",
                fill_date=d1, price="50", qty="10", created_by_run_id="run-1",
            ),
        )
        ta_book = _book(arm="ta_gated", equity_by_date={d1: "100500"}, orders=ta_orders)
        book_mod.save_book(settings, ta_book)

        full_orders = (
            _filled_order(
                order_id="full-0", arm="full_workflow", symbol="TAG", side="buy",
                fill_date=d1, price="50", qty="10", created_by_run_id="run-1",
            ),
        )
        full_book = _book(arm="full_workflow", equity_by_date={d1: "100500"}, orders=full_orders)
        book_mod.save_book(settings, full_book)

        result = study.build_study(settings=settings, arms=("raw_signal", "ta_gated", "full_workflow"))
        by_arm = {row.arm: row for row in result.arms}

        # ta_gated wants only `tradingagents` children -- the vibedesk child's call is not billed to it.
        ta_row = by_arm["ta_gated"]
        assert ta_row.research_cost_usd == Decimal("0.15")
        assert ta_row.research_input_tokens == 150
        assert ta_row.research_output_tokens == 30
        assert ta_row.research_cache_read_tokens == 0
        assert ta_row.research_cache_creation_tokens == 0
        assert ta_row.net_adjusted_excess == ta_row.adjusted_excess - (Decimal("0.15") / study.STARTING_CASH)

        # full_workflow wants both `tradingagents` and `vibedesk` children -- everything is billed.
        full_row = by_arm["full_workflow"]
        assert full_row.research_cost_usd == Decimal("0.45")
        assert full_row.research_input_tokens == 350
        assert full_row.research_output_tokens == 70

        # raw_signal never gates on either child kind -- zero regardless of what the workflow run did.
        raw_row = by_arm["raw_signal"]
        assert raw_row.research_cost_usd == Decimal(0)
        assert raw_row.research_input_tokens == 0


# ---------------------------------------------------------------------------
# 6. grounding_retry_rate / grounding_retry_waste_usd
# ---------------------------------------------------------------------------


class TestGroundingRetryTelemetry:
    def test_rate_and_waste_across_stored_workflow_runs_and_their_children(self, settings: Settings) -> None:
        # A workflow-own stage retried once: 2 calls, the first (0.10) wasted, the second (0.07) kept.
        _write_call(settings, call_id="own-retry-1", cost_usd="0.10")
        _write_call(settings, call_id="own-retry-2", cost_usd="0.07")
        # A workflow-own stage that was graded but never retried -- counts in the denominator, not
        # the numerator, and contributes nothing to the waste sum.
        _write_call(settings, call_id="own-clean-1", cost_usd="0.02")

        retried_own_stage = StageRecord(
            stage_id="followup_questions", role="market_analyst", label="Followup",
            state="succeeded", call_ids=("own-retry-1", "own-retry-2"),
            grounding=GroundingVerdict(ok=True, attempts=2),
        )
        clean_own_stage = StageRecord(
            stage_id="entry_plan", role="market_analyst", label="Entry Plan",
            state="succeeded", call_ids=("own-clean-1",),
            grounding=GroundingVerdict(ok=True, attempts=1),
        )
        # A deterministic spine stage -- `grounding=None` -- must be excluded from both the numerator
        # and the denominator, not counted as a clean pass.
        deterministic_stage = StageRecord(
            stage_id="regime_call", role="market_analyst", label="Regime",
            state="succeeded", call_ids=(),
        )

        # A CHILD run's stage retried twice: 3 calls, the first two (0.20 + 0.15) wasted, the third
        # (0.05) kept -- proving the walk reaches into children, not only the workflow run's own stages.
        _write_call(settings, call_id="child-retry-1", cost_usd="0.20")
        _write_call(settings, call_id="child-retry-2", cost_usd="0.15")
        _write_call(settings, call_id="child-retry-3", cost_usd="0.05")
        child_retried_stage = StageRecord(
            stage_id="verdict", role="market_analyst", label="Verdict",
            state="succeeded", call_ids=("child-retry-1", "child-retry-2", "child-retry-3"),
            grounding=GroundingVerdict(ok=True, attempts=3),
        )
        child_run = _child_desk_run(run_id="vibe-retry-1", kind="vibedesk", stages=(child_retried_stage,))
        RunStore(settings, "vibedesk").save(child_run)

        workflow_run = _workflow_desk_run(
            run_id="wf-retry-1",
            child_runs={"vibe_XYZ": "vibe-retry-1"},
            own_stages=(retried_own_stage, clean_own_stage, deterministic_stage),
        )
        RunStore(settings, "workflow").save(workflow_run)

        result = study.build_study(settings=settings, arms=("raw_signal",))

        # 3 graded stages total (retried_own_stage, clean_own_stage, child_retried_stage);
        # deterministic_stage (grounding=None) is not one of them. 2 of the 3 were retried.
        assert result.grounding_retry_rate == pytest.approx(Decimal("2") / Decimal("3"))
        # waste = all-but-last of each retried stage's call_ids: 0.10 (own) + 0.20 + 0.15 (child) = 0.45
        assert result.grounding_retry_waste_usd == Decimal("0.45")

    def test_none_when_no_stored_workflow_run_has_a_graded_stage(self, settings: Settings) -> None:
        result = study.build_study(settings=settings, arms=("raw_signal",))
        assert result.grounding_retry_rate is None
        assert result.grounding_retry_waste_usd == Decimal(0)

    def test_a_missing_call_file_behind_a_retried_stage_is_skipped_not_raised(self, settings: Settings) -> None:
        """`grounding_retry_waste_usd` sums via `summarize_calls`, which tolerates a missing/unreadable
        `AgentCall` archive -- see `tests/test_agentdesk_telemetry.py`. Here the wasted (all-but-last)
        call id was never archived; the waste sum degrades to zero for that stage rather than raising."""
        retried_stage = StageRecord(
            stage_id="followup_questions", role="market_analyst", label="Followup",
            state="succeeded", call_ids=("never-archived", "also-never-archived"),
            grounding=GroundingVerdict(ok=True, attempts=2),
        )
        workflow_run = _workflow_desk_run(
            run_id="wf-missing-call", child_runs={}, own_stages=(retried_stage,)
        )
        RunStore(settings, "workflow").save(workflow_run)

        result = study.build_study(settings=settings, arms=("raw_signal",))
        assert result.grounding_retry_rate == Decimal("1")
        assert result.grounding_retry_waste_usd == Decimal(0)


# ---------------------------------------------------------------------------
# 7. universe_source -- build_study can score the screened books separately from the card ones
# ---------------------------------------------------------------------------


class TestUniverseSourceScoping:
    def test_default_universe_source_is_card(self, settings: Settings) -> None:
        result = study.build_study(settings=settings, arms=("raw_signal",))
        assert result.arms[0].universe_source == "card"

    def test_build_study_screen_mode_loads_the_screen_book_not_the_card_one(
        self, settings: Settings
    ) -> None:
        d1 = dt.date(2026, 5, 4)
        _write_bars(settings, "SPY", {d1: 100.0})

        card_orders = (
            _filled_order(
                order_id="card-0", arm="raw_signal", symbol="CARD", side="buy",
                fill_date=d1, price="10", qty="100",
            ),
        )
        card_book = _book(arm="raw_signal", equity_by_date={d1: "101000"}, orders=card_orders)
        book_mod.save_book(settings, card_book)

        screen_book = book_mod.load_book(
            settings, "raw_signal", starting_cash=study.STARTING_CASH, card_id="card-1",
            card_adopted_date=d1, universe_source="screen",
        )
        screen_orders = (
            _filled_order(
                order_id="screen-0", arm="raw_signal", symbol="SCREEN", side="buy",
                fill_date=d1, price="20", qty="100",
            ),
        )
        screen_book = screen_book.model_copy(
            update={
                "orders": screen_orders,
                "equity_curve": (EquityPoint(date=d1, equity=Decimal("98000")),),
            }
        )
        book_mod.save_book(settings, screen_book)

        card_result = study.build_study(settings=settings, arms=("raw_signal",))
        screen_result = study.build_study(
            settings=settings, arms=("raw_signal",), universe_source="screen"
        )

        card_row = card_result.arms[0]
        screen_row = screen_result.arms[0]
        assert card_row.universe_source == "card"
        assert screen_row.universe_source == "screen"
        # the two books carry different equity curves -- proving screen mode really read the
        # screen-path book, not a copy of (or fallback to) the card one.
        assert card_row.total_return != screen_row.total_return
        assert card_row.trades == 1
        assert screen_row.trades == 1

    def test_build_study_screen_mode_filters_the_candidate_log_by_universe_source(
        self, settings: Settings
    ) -> None:
        card_row = _candidate(
            obs_id="card-cand", symbol="AAA", gate="ta_gated", passed=True,
            forward_return_pct="0.05",
        )
        screen_row = _candidate(
            obs_id="screen-cand", symbol="BBB", gate="ta_gated", passed=False,
            forward_return_pct="-0.02",
        ).model_copy(update={"universe_source": "screen"})
        candidates_mod.append_observations([card_row, screen_row], settings=settings)

        card_result = study.build_study(settings=settings, arms=("raw_signal",))
        screen_result = study.build_study(
            settings=settings, arms=("raw_signal",), universe_source="screen"
        )

        card_ta = {row.gate: row for row in card_result.discrimination}["ta_gated"]
        screen_ta = {row.gate: row for row in screen_result.discrimination}["ta_gated"]
        assert card_ta.passed_n == 1
        assert card_ta.refused_n == 0
        assert screen_ta.passed_n == 0
        assert screen_ta.refused_n == 1

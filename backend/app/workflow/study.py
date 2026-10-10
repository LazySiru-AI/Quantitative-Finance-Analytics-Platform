"""The Agent Workflow effectiveness study -- `docs/WORKFLOW-STUDY-PLAN.md`, scored.

**What this module answers, and what it deliberately does not.** `build_study` scores the four
persisted per-arm books (`app.workflow.book`) against the shared candidate-observation log
(`app.workflow.candidates`) and reports exactly the figures the pre-registration promised: the
exposure-corrected primary metric (§2-3), the paired bootstrap comparison against the `raw_signal`
null (§5, "Reuse these verbatim"), and the discrimination test (§4) -- the one instrument in the
whole study with real statistical power, because it counts candidates rather than days. It does not
decide whether the workflow is "effective" -- §7's decision rule is a judgement call for a human
reading this output against the pre-registered threshold, not a boolean this module computes and
hides behind.

**Wire shape vs `docs/AGENT-DESK-CONTRACT.md`.** The contract's `WorkflowStudy`/`ArmMetrics` are the
frontend's pinned names, and every field they name is reproduced here verbatim (same name, same
`arm`/`total_return`/`max_drawdown`/`realized_vol`/`win_rate`/`exposure`/`adjusted_excess`/`trades`/
`live_fill_fraction`, same `benchmark`/`benchmark_return`/`window`/`arms`/`paired`/
`vibe_verdict_compliance`/`note`). What the contract's snapshot does *not* carry -- `excess_per_
exposure`, `research_cost_usd`, `net_adjusted_excess`, `research_input_tokens`/`research_output_
tokens`/`research_cache_read_tokens`/`research_cache_creation_tokens` on `ArmMetrics`, and the §4
discrimination test's per-gate results plus `grounding_retry_rate`/`grounding_retry_waste_usd` on
`WorkflowStudy` -- is required by `docs/WORKFLOW-STUDY-PLAN.md` §3-4 (the token fields) or is this
study's own telemetry extension (the grounding-retry fields; see `docs/AGENT-DESK-CONTRACT.md`'s
"Telemetry" subsection) and is added here as extra fields alongside the contract's own. A caller that
only reads the contract's named fields sees exactly the contract; a caller that reads this study's
full output sees the pre-registered one plus telemetry. See this package's own test suite and the
accompanying report for why the two documents disagree and which one governs which field.

**Everything here is read-only.** No book, no candidate log and no `DeskRun` is written by this
module -- it only reads what `app.workflow.book`, `app.workflow.candidates` and `app.agentdesk.store`
already persisted, and reads stored bars for the benchmark return exactly as `app.workflow.candidates`
does for a candidate's own forward return.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict

from app.agentdesk.models import DeskRun, StageRecord
from app.agentdesk.store import RunStore
from app.agentdesk.telemetry import CallCostSummary, summarize_calls
from app.backtest import metrics as metrics_mod
from app.backtest.models import BARS_PER_YEAR, ExitReason
from app.backtest.models import Trade as MetricsTrade
from app.backtest.scan import benjamini_hochberg, binomial_p_value
from app.config import Settings
from app.discovery.stats import stationary_bootstrap_p
from app.market import store as market_store
from app.market.models import Interval
from app.paper.marketdata import AsOfMarket, UnpricedSymbol
from app.workflow import book as book_mod
from app.workflow import candidates as candidates_mod
from app.workflow.analysis import GateConcordance, gate_concordance
from app.workflow.book_models import BookState, WorkflowArm, WorkflowOrderRecord
from app.workflow.candidates import BENCHMARK_SYMBOL, GateName
from app.workflow.pipeline import ALL_ARMS, STARTING_CASH
from app.workflow.telemetry import iter_child_runs

__all__ = [
    "ArmMetrics",
    "GateDiscrimination",
    "PairedComparison",
    "StudyWindow",
    "WorkflowStudy",
    "build_study",
]

#: The three gates the discrimination test evaluates -- fixed, per `docs/WORKFLOW-STUDY-PLAN.md` §4
#: ("Three gates tested -> m = 3 in the BH denominator"). Computed regardless of which `arms` a
#: caller asked `build_study` for: the candidate log is written once per workflow run, for every
#: gate, independent of which per-arm books the caller happens to want metrics on.
_GATES: tuple[GateName, ...] = ("ta_gated", "vibe_gated", "full_workflow")

_QUANT6 = Decimal("0.000001")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class StudyWindow(_Frozen):
    start: dt.date
    end: dt.date


class ArmMetrics(_Frozen):
    """One arm's scored result. Field order and names through `live_fill_fraction` match
    `docs/AGENT-DESK-CONTRACT.md`'s `ArmMetrics` exactly; every field after it is this study's own
    extension -- see the module docstring."""

    arm: WorkflowArm
    universe_source: Literal["card", "screen"] = "card"
    """Which universe the book behind this row was loaded from -- see `app.workflow.book_models.
    BookState.universe_source`. Set from `build_study`'s own `universe_source` argument, uniformly
    across every arm in one call; a study never mixes card-mode and screen-mode rows in the same
    `arms` tuple, so this is one value per call, carried per-row purely so a caller diffing two
    `WorkflowStudy` results (one card, one screen) can tell them apart without also threading the
    call's own argument through separately."""
    total_return: Decimal
    max_drawdown: Decimal
    realized_vol: Decimal
    """Non-annualised daily-return standard deviation -- never `StrategyMetrics.volatility`, which is
    annualised and `None` under a year regardless. See `docs/WORKFLOW-STUDY-PLAN.md` §3."""
    win_rate: Decimal | None
    exposure: Decimal
    adjusted_excess: Decimal
    """`total_return - exposure * benchmark_return` -- the study's primary metric (§2-3). Prices the
    time this arm spent in cash at the benchmark rather than at zero, which is what stops a gate that
    merely trades less from mechanically outscoring one that trades more."""
    trades: int
    live_fill_fraction: Decimal
    """Share of this arm's filled orders priced from a live quote rather than a stored open."""

    excess_per_exposure: Decimal | None
    """`adjusted_excess / exposure`. Reported alongside `adjusted_excess`, never in place of it --
    `docs/WORKFLOW-STUDY-PLAN.md` §2 notes `adjusted_excess` still correlates with exposure, so
    neither figure is read alone. `None` when `exposure` is zero (nothing to divide by)."""
    research_cost_usd: Decimal
    """Model-call spend attributed to this arm: zero for `raw_signal` (no gate, nothing to run), and
    the summed `AgentCall.cost_usd` of every call behind every Trading-Agents/Vibe child run driving
    this arm's staged orders otherwise. See `_research_call_summary`."""
    net_adjusted_excess: Decimal
    """`adjusted_excess` less `research_cost_usd` expressed as a fraction of `STARTING_CASH` -- the
    figure `docs/WORKFLOW-STUDY-PLAN.md` §3 says an arm must clear, not merely `adjusted_excess`
    gross, to have "beaten" the raw signal."""

    research_input_tokens: int
    research_output_tokens: int
    research_cache_read_tokens: int
    research_cache_creation_tokens: int
    """Token totals over the same call set `research_cost_usd` sums -- telemetry, not a §3/§4
    pre-registered figure. See `docs/AGENT-DESK-CONTRACT.md`'s "Telemetry" subsection and
    `app.agentdesk.telemetry.CallCostSummary`."""


class PairedComparison(_Frozen):
    """One treated arm against `raw_signal`, paired by date -- `docs/WORKFLOW-STUDY-PLAN.md` §5."""

    arm: WorkflowArm
    universe_source: Literal["card", "screen"] = "card"
    """Same field, same reasoning as `ArmMetrics.universe_source` -- set uniformly from
    `build_study`'s own argument."""
    mean_daily_diff: Decimal
    bootstrap_p: Decimal | None
    """`app.discovery.stats.stationary_bootstrap_p` on the paired daily-return differences. `None`
    when fewer than three common trading dates exist between the two arms (that function's own
    floor) -- not a zero, and not a claim of significance either way."""


class GateDiscrimination(_Frozen):
    """One gate's §4 result: does its pass/fail predict a candidate's realised forward return."""

    gate: GateName
    passed_n: int
    refused_n: int
    passed_hit_rate: Decimal | None
    refused_hit_rate: Decimal | None
    passed_mean_forward_return: Decimal | None
    refused_mean_forward_return: Decimal | None
    mean_diff: Decimal | None
    """`passed_mean_forward_return - refused_mean_forward_return`. Descriptive; the formal statistic
    is `p_value`/`q_value` below, per the brief's "reuse these verbatim" pairing of
    `binomial_p_value`/`benjamini_hochberg` for this test."""
    p_value: Decimal | None
    """`binomial_p_value(passed successes, passed_n, p_null=refused_hit_rate)` -- whether the passed
    set's hit rate differs from the refused set's own observed hit rate. `None` when either set is
    empty (an untestable gate keeps its slot in `q_value`'s BH ranking regardless -- see
    `benjamini_hochberg`'s own docstring)."""
    q_value: Decimal | None
    """Benjamini-Hochberg adjusted `p_value`, `m = 3` across `_GATES`."""


class WorkflowStudy(_Frozen):
    """`docs/AGENT-DESK-CONTRACT.md`'s `WorkflowStudy`, plus `discrimination`, the two grounding-
    retry telemetry fields, and `gate_concordance` -- see the module docstring for exactly which
    fields are the contract's and which are this study's extension."""

    benchmark: str
    benchmark_return: Decimal | None
    window: StudyWindow | None
    arms: tuple[ArmMetrics, ...]
    paired: tuple[PairedComparison, ...]
    discrimination: tuple[GateDiscrimination, ...]
    vibe_verdict_compliance: Decimal | None
    note: str

    grounding_retry_rate: Decimal | None
    """Share of every graded stage -- across every stored workflow run's own stages and every one of
    their TA/Vibe children's stages alike -- whose `GroundingVerdict.attempts > 1`, i.e. was corrected
    at least once before being released or degraded. A stage the grounding gate never ran on (every
    deterministic spine stage; `StageRecord.grounding is None`) is excluded from both the numerator
    and the denominator, not counted as a non-retry. `None` when no stored workflow run has a single
    graded stage yet. Telemetry, not a §3/§4 pre-registered figure -- see `docs/AGENT-DESK-CONTRACT.md`'s
    "Telemetry" subsection."""
    grounding_retry_waste_usd: Decimal
    """Summed `AgentCall.cost_usd` of every call before the last one, across every retried stage
    counted in `grounding_retry_rate`'s numerator -- money spent on an attempt the grounding gate
    rejected, that a first-try pass would not have cost. Zero, not `None`, when nothing was retried
    (unlike the rate, a sum over an empty set is unambiguously zero)."""

    gate_concordance: GateConcordance
    """TA-vs-Vibe agreement over every candidate carrying a ruling from both gates -- see
    `app.workflow.analysis.gate_concordance`. A study extension, not a §3/§4 pre-registered figure:
    it asks whether the two gates land on the same verdict, which is a plain count over the candidate
    log, distinct from `discrimination`'s statistical question of whether a gate predicts forward
    return."""


class _StudyLot:
    """One symbol's open position while walking a book's filled orders in `fill_date` order --
    average cost, mirroring `app.workflow.replay._OpenLot` for the identical reason (no lot id on a
    `WorkflowOrderRecord`, and a second buy before a sell is the uncommon case this still has to
    handle, not the common one). Kept as this module's own small class rather than importing
    `replay._OpenLot`: that name is private to its module."""

    __slots__ = ("entry_date", "entry_price", "quantity")

    def __init__(self, *, entry_price: Decimal, entry_date: dt.date, quantity: Decimal) -> None:
        self.entry_price = entry_price
        self.entry_date = entry_date
        self.quantity = quantity


def _window_return(symbol: str, start: dt.date, end: dt.date, *, settings: Settings) -> Decimal | None:
    """Buy-and-hold return over `[start, end]` off stored daily closes -- a deliberate copy of
    `app.workflow.candidates._window_return`'s body, for the same reason that function's own
    docstring gives for copying rather than importing `app.tradingagents.memory._realized_return`:
    the source is private to its module, and this package was told not to invent a second convention,
    not to reach through one module's privacy to reuse it."""
    frame = market_store.read_frame(symbol, Interval.DAY, settings=settings)
    if frame is None or frame.empty:
        return None
    inside = frame[(frame["ts"].dt.date >= start) & (frame["ts"].dt.date <= end)]
    if len(inside) < 2:
        return None
    first = Decimal(str(inside["close"].iloc[0]))
    last = Decimal(str(inside["close"].iloc[-1]))
    if first <= 0:
        return None
    return last / first - 1


def _in_position_series(orders: Sequence[WorkflowOrderRecord], dates: Sequence[dt.date]) -> np.ndarray:
    """One flag per date in `dates` (already ascending): was this arm holding any position, as of
    that date's close, given every order's own `fill_date` and filled quantity."""
    changes: dict[dt.date, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for order in orders:
        if order.status != "filled" or order.fill is None:
            continue
        sign = Decimal(1) if order.side == "buy" else Decimal(-1)
        changes[order.fill_date][order.symbol] += sign * order.fill.qty

    change_dates = sorted(changes)
    positions: dict[str, Decimal] = defaultdict(Decimal)
    flags: list[bool] = []
    idx = 0
    for on in dates:
        while idx < len(change_dates) and change_dates[idx] <= on:
            for symbol, delta in changes[change_dates[idx]].items():
                positions[symbol] += delta
            idx += 1
        flags.append(any(q > 0 for q in positions.values()))
    return np.array(flags, dtype=np.bool_)


def _trades_from_orders(
    orders: Sequence[WorkflowOrderRecord], *, settings: Settings, last_date: dt.date | None
) -> tuple[MetricsTrade, ...]:
    """Reconstruct `Trade` objects from a book's filled orders, average-cost per symbol, in
    `fill_date` order -- see `_StudyLot`'s docstring. `bars_held` is calendar days between
    `fill_date`s, not a trading-session count (this module has no `SessionCalendar` for the book's
    whole history); `metrics.compute` never reads it, so this is cosmetic, not load-bearing."""
    filled = sorted(
        (o for o in orders if o.status == "filled" and o.fill is not None),
        key=lambda o: (o.fill_date, o.order_id),
    )
    lots: dict[str, _StudyLot] = {}
    trades: list[MetricsTrade] = []

    for order in filled:
        fill = order.fill
        assert fill is not None
        lot = lots.get(order.symbol)
        if order.side == "buy":
            if lot is None:
                lots[order.symbol] = _StudyLot(
                    entry_price=fill.price, entry_date=order.fill_date, quantity=fill.qty
                )
            else:
                total_quantity = lot.quantity + fill.qty
                if total_quantity > 0:
                    lot.entry_price = (
                        lot.entry_price * lot.quantity + fill.price * fill.qty
                    ) / total_quantity
                lot.quantity = total_quantity
            continue

        if lot is None or lot.quantity <= 0:
            continue
        sold = min(fill.qty, lot.quantity)
        return_pct = float((fill.price - lot.entry_price) / lot.entry_price) if lot.entry_price != 0 else 0.0
        trades.append(
            MetricsTrade(
                entry_date=lot.entry_date,
                entry_price=float(lot.entry_price),
                exit_date=order.fill_date,
                exit_price=float(fill.price),
                exit_reason=ExitReason.SIGNAL,
                bars_held=(order.fill_date - lot.entry_date).days,
                return_pct=return_pct,
                open_at_end=False,
            )
        )
        remaining = lot.quantity - sold
        if remaining <= 0:
            del lots[order.symbol]
        else:
            lot.quantity = remaining

    if last_date is not None and lots:
        market = AsOfMarket(as_of=last_date, settings=settings)
        for symbol, lot in lots.items():
            if lot.quantity <= 0:
                continue
            try:
                mark_price = market.close(symbol)
            except UnpricedSymbol:
                mark_price = lot.entry_price
            return_pct = (
                float((mark_price - lot.entry_price) / lot.entry_price) if lot.entry_price != 0 else 0.0
            )
            trades.append(
                MetricsTrade(
                    entry_date=lot.entry_date,
                    entry_price=float(lot.entry_price),
                    exit_date=last_date,
                    exit_price=float(mark_price),
                    exit_reason=ExitReason.END_OF_DATA,
                    bars_held=(last_date - lot.entry_date).days,
                    return_pct=return_pct,
                    open_at_end=True,
                )
            )
    return tuple(trades)


_EMPTY_CALL_SUMMARY = CallCostSummary(
    call_count=0, input_tokens=0, output_tokens=0,
    cache_read_input_tokens=0, cache_creation_input_tokens=0, cost_usd=Decimal(0),
)


def _research_call_summary(book: BookState, *, settings: Settings) -> CallCostSummary:
    """Model-call spend AND token totals behind `book`'s staged orders -- see `ArmMetrics.
    research_cost_usd` and its sibling `research_input_tokens`/`research_output_tokens`/
    `research_cache_read_tokens`/`research_cache_creation_tokens` fields.

    `raw_signal` is always empty: it stages every candidate with no gate, and `app.workflow.pipeline`'s
    own docstring is explicit that the orchestrator's spine (`regime_call`, `strategy_select`,
    `candidate_scan`, ...) is deterministic and free -- the only stages that spend are the per-symbol
    `research_<SYM>`/`vibe_<SYM>` children, and `raw_signal` never gates on either.

    For a gated arm: every distinct `created_by_run_id` on this book's orders names a workflow
    `DeskRun`; `app.workflow.telemetry.iter_child_runs` resolves that run's `config["child_runs"]`
    into its TA/Vibe children (the same prefix-inference/child-walk `app.workflow.telemetry.
    build_workflow_telemetry` uses -- this function is the other caller it was written for, so the
    logic is not duplicated between the study and the telemetry endpoint). `ta_gated`/`full_workflow`
    bill `tradingagents` children; `vibe_gated`/`full_workflow` bill `vibedesk` children. A child (or
    the workflow run itself) that cannot be read degrades to contributing zero rather than raising --
    this feeds a report, not a ledger, and the same "unreadable run, logged and skipped" choice
    `RunStore.load` itself already makes.
    """
    if book.arm == "raw_signal":
        return _EMPTY_CALL_SUMMARY

    wants_research = book.arm in ("ta_gated", "full_workflow")
    wants_vibe = book.arm in ("vibe_gated", "full_workflow")
    workflow_run_ids = {order.created_by_run_id for order in book.orders}
    if not workflow_run_ids:
        return _EMPTY_CALL_SUMMARY

    workflow_store = RunStore(settings, "workflow")
    seen: set[str] = set()
    call_ids: list[str] = []
    for run_id in workflow_run_ids:
        run = workflow_store.load(run_id)
        if run is None:
            continue
        for _stage_id, kind, child in iter_child_runs(run, settings=settings):
            if kind == "tradingagents" and not wants_research:
                continue
            if kind == "vibedesk" and not wants_vibe:
                continue
            seen_key = f"{kind}:{child.run_id}"
            if seen_key in seen:
                continue
            seen.add(seen_key)
            call_ids.extend(cid for stage in child.stages for cid in stage.call_ids)
    if not call_ids:
        return _EMPTY_CALL_SUMMARY
    return summarize_calls(call_ids, settings=settings)


def _live_fill_fraction(book: BookState) -> Decimal:
    filled = [o for o in book.orders if o.status == "filled" and o.fill is not None]
    if not filled:
        return Decimal(0)
    live = sum(1 for o in filled if o.fill is not None and o.fill.price_source == "live_quote")
    return (Decimal(live) / Decimal(len(filled))).quantize(_QUANT6)


def _arm_daily_returns(book: BookState) -> dict[dt.date, Decimal]:
    """`{date: daily return}` for every priced equity-curve point in `book`, the first entry being
    the return from `STARTING_CASH` to the first priced point -- the same "prepend the starting
    anchor" convention `app.tournament.runner.run_card` and `app.workflow.replay.run_decision_log`
    both use, so a study day and a tournament session mean the same thing when compared."""
    priced = sorted(
        ((p.date, p.equity) for p in book.equity_curve if p.equity is not None), key=lambda pair: pair[0]
    )
    if not priced:
        return {}
    prior = STARTING_CASH
    out: dict[dt.date, Decimal] = {}
    for on, equity in priced:
        out[on] = (equity / prior - 1) if prior != 0 else Decimal(0)
        prior = equity
    return out


def _score_arm(
    arm: WorkflowArm,
    book: BookState,
    *,
    settings: Settings,
    benchmark_return: Decimal | None,
    universe_source: Literal["card", "screen"] = "card",
) -> tuple[ArmMetrics, dict[dt.date, Decimal]]:
    returns_by_date = _arm_daily_returns(book)
    dates = sorted(returns_by_date)

    if dates:
        priced_equity = {p.date: p.equity for p in book.equity_curve if p.equity is not None}
        equity_decimal = [STARTING_CASH, *(priced_equity[d] for d in dates)]
        in_position_array = np.array(
            [False, *_in_position_series(book.orders, dates).tolist()], dtype=np.bool_
        )
    else:
        equity_decimal = [STARTING_CASH]
        in_position_array = np.array([False], dtype=np.bool_)

    equity_array = np.array([float(e / STARTING_CASH) for e in equity_decimal], dtype=np.float64)
    trades = _trades_from_orders(book.orders, settings=settings, last_date=dates[-1] if dates else None)

    strategy_metrics = metrics_mod.compute(
        equity_array,
        in_position=in_position_array,
        trades=trades,
        bars_per_year=BARS_PER_YEAR[Interval.DAY],
        annualisable=False,
    )
    strategy_metrics = strategy_metrics.model_copy(
        update={"exposure": _undilute_exposure(strategy_metrics.exposure, len(dates))}
    )

    total_return = Decimal(str(strategy_metrics.total_return)) if strategy_metrics.total_return is not None else Decimal(0)
    max_drawdown = Decimal(str(strategy_metrics.max_drawdown)) if strategy_metrics.max_drawdown is not None else Decimal(0)
    exposure = Decimal(str(strategy_metrics.exposure)) if strategy_metrics.exposure is not None else Decimal(0)
    win_rate = Decimal(str(strategy_metrics.win_rate)) if strategy_metrics.win_rate is not None else None

    bench = benchmark_return if benchmark_return is not None else Decimal(0)
    adjusted_excess = total_return - exposure * bench
    excess_per_exposure = (adjusted_excess / exposure) if exposure != 0 else None

    research_summary = _research_call_summary(book, settings=settings)
    research_cost_usd = research_summary.cost_usd
    net_adjusted_excess = adjusted_excess - (research_cost_usd / STARTING_CASH)

    arm_metrics = ArmMetrics(
        arm=arm,
        universe_source=universe_source,
        total_return=total_return,
        max_drawdown=max_drawdown,
        realized_vol=_realized_vol(equity_decimal),
        win_rate=win_rate,
        exposure=exposure,
        adjusted_excess=adjusted_excess,
        trades=strategy_metrics.trades,
        live_fill_fraction=_live_fill_fraction(book),
        excess_per_exposure=excess_per_exposure,
        research_cost_usd=research_cost_usd,
        net_adjusted_excess=net_adjusted_excess,
        research_input_tokens=research_summary.input_tokens,
        research_output_tokens=research_summary.output_tokens,
        research_cache_read_tokens=research_summary.cache_read_input_tokens,
        research_cache_creation_tokens=research_summary.cache_creation_input_tokens,
    )
    return arm_metrics, returns_by_date


def _undilute_exposure(exposure: float | None, sessions: int) -> float | None:
    """A deliberate copy of `app.tournament.runner._undilute_exposure` / `app.workflow.replay.
    _undilute_exposure`'s body -- see either's own docstring for why the prepended `STARTING_CASH`
    anchor point dilutes `metrics.compute`'s raw `mean(in_position)` and must be rescaled back out."""
    if exposure is None or sessions <= 0:
        return exposure
    return exposure * (sessions + 1) / sessions


def _realized_vol(equity_decimal: Sequence[Decimal]) -> Decimal:
    """Non-annualised standard deviation of the curve's own pct-changes -- `numpy.std`'s population
    (`ddof=0`) default, matching the brief's "numpy std of the equity-curve pct-changes" literally.
    `Decimal(0)` (not `None`; `ArmMetrics.realized_vol` is not optional) below two returns, where a
    standard deviation is not meaningfully defined."""
    if len(equity_decimal) < 3:
        return Decimal(0)
    returns = [
        float(equity_decimal[i] / equity_decimal[i - 1] - 1) if equity_decimal[i - 1] != 0 else 0.0
        for i in range(1, len(equity_decimal))
    ]
    return Decimal(str(float(np.std(np.array(returns, dtype=np.float64)))))


def _paired_comparison(
    arm: WorkflowArm,
    arm_returns: dict[dt.date, Decimal],
    raw_returns: dict[dt.date, Decimal],
    *,
    universe_source: Literal["card", "screen"] = "card",
) -> PairedComparison:
    common = sorted(set(arm_returns) & set(raw_returns))
    diffs = [float(arm_returns[d] - raw_returns[d]) for d in common]
    if not diffs:
        return PairedComparison(
            arm=arm, universe_source=universe_source, mean_daily_diff=Decimal(0), bootstrap_p=None
        )
    mean_diff = Decimal(str(sum(diffs) / len(diffs)))
    p = stationary_bootstrap_p(diffs, block=3.0, seed=0)
    return PairedComparison(
        arm=arm,
        universe_source=universe_source,
        mean_daily_diff=mean_diff,
        bootstrap_p=Decimal(str(p)) if p is not None else None,
    )


def _discrimination(
    *, settings: Settings, universe_source: Literal["card", "screen"] = "card"
) -> tuple[GateDiscrimination, ...]:
    observations = [
        obs
        for obs in candidates_mod.read_observations(
            settings=settings, state="resolved", universe_source=universe_source
        )
        if not obs.unpriceable and obs.forward_return_pct is not None
    ]

    per_gate: list[tuple[list[float], list[float]]] = []
    for gate in _GATES:
        passed: list[float] = []
        refused: list[float] = []
        for obs in observations:
            forward = obs.forward_return_pct
            assert forward is not None
            for decision in obs.gates:
                if decision.gate != gate:
                    continue
                (passed if decision.passed else refused).append(float(forward))
        per_gate.append((passed, refused))

    p_values: list[float | None] = []
    for passed, refused in per_gate:
        if passed and refused:
            refused_hit_rate = sum(1 for r in refused if r > 0) / len(refused)
            successes = sum(1 for r in passed if r > 0)
            p_values.append(binomial_p_value(successes, len(passed), refused_hit_rate))
        else:
            p_values.append(None)
    q_values = benjamini_hochberg(p_values)

    results: list[GateDiscrimination] = []
    for gate, (passed, refused), p_value, q_value in zip(_GATES, per_gate, p_values, q_values, strict=True):
        passed_hit = sum(1 for r in passed if r > 0) / len(passed) if passed else None
        refused_hit = sum(1 for r in refused if r > 0) / len(refused) if refused else None
        passed_mean = sum(passed) / len(passed) if passed else None
        refused_mean = sum(refused) / len(refused) if refused else None
        mean_diff = (
            Decimal(str(passed_mean - refused_mean)) if passed_mean is not None and refused_mean is not None else None
        )
        results.append(
            GateDiscrimination(
                gate=gate,
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
        )
    return tuple(results)


def _vibe_verdict_compliance(
    *, settings: Settings, universe_source: Literal["card", "screen"] = "card"
) -> Decimal | None:
    observations = candidates_mod.read_observations(settings=settings, universe_source=universe_source)
    total = 0
    explicit = 0
    for obs in observations:
        for decision in obs.gates:
            if decision.gate != "vibe_gated":
                continue
            total += 1
            if decision.was_explicit:
                explicit += 1
    if total == 0:
        return None
    return (Decimal(explicit) / Decimal(total)).quantize(_QUANT6)


def _study_window(books: dict[WorkflowArm, BookState]) -> StudyWindow | None:
    dates = [p.date for book in books.values() for p in book.equity_curve if p.equity is not None]
    if not dates:
        return None
    return StudyWindow(start=min(dates), end=max(dates))


#: A ceiling, not an expectation -- `RunStore.list_runs`' own default is 25 (a page for the UI); the
#: grounding-retry telemetry below wants every stored workflow run ever written, not a page of them,
#: so it passes a limit high enough that no real deployment's run count reaches it.
_ALL_RUNS_LIMIT = 100_000


def _iter_graded_stages(workflow_runs: Sequence[DeskRun], *, settings: Settings) -> list[StageRecord]:
    """Every `StageRecord` with a `GroundingVerdict` attached -- a workflow run's own stages plus
    every one of their TA/Vibe children's stages, across every run in `workflow_runs`. Deterministic
    spine stages (`StageRecord.grounding is None`) are never yielded -- see
    `WorkflowStudy.grounding_retry_rate`'s own docstring for why they are excluded rather than
    counted as non-retries."""
    stages: list[StageRecord] = []
    for run in workflow_runs:
        stages.extend(stage for stage in run.stages if stage.grounding is not None)
        for _stage_id, _kind, child in iter_child_runs(run, settings=settings):
            stages.extend(stage for stage in child.stages if stage.grounding is not None)
    return stages


def _grounding_retry_stats(
    workflow_runs: Sequence[DeskRun], *, settings: Settings
) -> tuple[Decimal | None, Decimal]:
    """`(grounding_retry_rate, grounding_retry_waste_usd)` -- see `WorkflowStudy`'s own docstrings for
    each. Walks every stored workflow run's own stages and every child run they launched, via
    `_iter_graded_stages`."""
    graded = _iter_graded_stages(workflow_runs, settings=settings)
    if not graded:
        return None, Decimal(0)

    retried = [stage for stage in graded if stage.grounding is not None and stage.grounding.attempts > 1]
    rate = (Decimal(len(retried)) / Decimal(len(graded))).quantize(_QUANT6)

    waste = Decimal(0)
    for stage in retried:
        wasted_call_ids = stage.call_ids[:-1]  # every attempt but the last (accepted) one
        waste += summarize_calls(wasted_call_ids, settings=settings).cost_usd
    return rate, waste


def build_study(
    *,
    settings: Settings,
    arms: tuple[WorkflowArm, ...] = ALL_ARMS,
    universe_source: Literal["card", "screen"] = "card",
) -> WorkflowStudy:
    """Score every requested arm's persisted book against the candidate-observation log.

    Reads `app.workflow.book.load_book` for each of `arms` (a book that has never run yet loads as a
    fresh, empty one -- `load_book`'s own contract -- and scores as all-zero rather than raising, the
    same "monitoring, not evidence, below the minimums" framing `docs/WORKFLOW-STUDY-PLAN.md` §7
    gives an under-powered window). The discrimination test (`_discrimination`) and
    `vibe_verdict_compliance` are computed from the candidate log independent of `arms` -- see `_GATES`
    -- but not independent of `universe_source`: both are filtered to the same `universe_source` this
    call requested, so a screen-mode study never has its discrimination test or Vibe-compliance figure
    contaminated by card-mode candidates, and vice versa.
    `grounding_retry_rate`/`grounding_retry_waste_usd` are likewise independent of `arms`: they walk
    every stored workflow run (`RunStore(settings, "workflow").list_runs`) and every child it
    launched, not only the runs behind the requested arms' books -- and are the one telemetry pair
    this function does not filter by `universe_source`, since a stored `DeskRun`'s own stages do not
    carry that field at all (see `app.agentdesk.models.StageRecord`); reconciling that is out of this
    change's scope.

    `universe_source`, default `"card"`, selects which of the two books at each requested arm to load
    (threaded to `load_book`) and which candidate-log rows feed the discrimination test and Vibe
    compliance (threaded to `read_observations` via `_discrimination`/`_vibe_verdict_compliance`).
    Every existing caller omits it and reproduces today's behaviour byte-for-byte: every pre-existing
    book and candidate row defaults to `universe_source="card"`, so a default-argument call sees
    exactly what it saw before this parameter existed.

    `arms` must include `"raw_signal"` for `paired` to have anything to compare against; a caller that
    omits it gets an empty `paired` tuple rather than a `KeyError`.
    """
    books = {
        arm: book_mod.load_book(
            settings, arm, starting_cash=STARTING_CASH, card_id="", universe_source=universe_source
        )
        for arm in arms
    }
    window = _study_window(books)
    benchmark_return = (
        _window_return(BENCHMARK_SYMBOL, window.start, window.end, settings=settings)
        if window is not None
        else None
    )

    arm_metrics: list[ArmMetrics] = []
    returns_by_arm: dict[WorkflowArm, dict[dt.date, Decimal]] = {}
    for arm in arms:
        metrics_row, returns = _score_arm(
            arm,
            books[arm],
            settings=settings,
            benchmark_return=benchmark_return,
            universe_source=universe_source,
        )
        arm_metrics.append(metrics_row)
        returns_by_arm[arm] = returns

    paired: list[PairedComparison] = []
    raw_returns = returns_by_arm.get("raw_signal")
    if raw_returns is not None:
        for arm in arms:
            if arm == "raw_signal":
                continue
            paired.append(
                _paired_comparison(
                    arm, returns_by_arm[arm], raw_returns, universe_source=universe_source
                )
            )

    discrimination = _discrimination(settings=settings, universe_source=universe_source)
    compliance = _vibe_verdict_compliance(settings=settings, universe_source=universe_source)
    concordance = gate_concordance(
        candidates_mod.read_observations(settings=settings, universe_source=universe_source)
    )

    workflow_runs = RunStore(settings, "workflow").list_runs(limit=_ALL_RUNS_LIMIT)
    grounding_retry_rate, grounding_retry_waste_usd = _grounding_retry_stats(
        workflow_runs, settings=settings
    )

    live_mix_bits = ", ".join(
        f"{row.arm}={row.live_fill_fraction}" for row in arm_metrics if row.trades > 0
    )
    note = (
        "Directional study, not a promotion decision (docs/WORKFLOW-STUDY-PLAN.md): a few months of "
        "daily decisions on a small universe is under-powered for the equity-curve comparison, and "
        "the gates are model draws, not deterministic like raw_signal -- one run is one sample from a "
        "distribution this study cannot characterise. Live-quote fill share by arm"
        + (f": {live_mix_bits}." if live_mix_bits else " is undefined (no fills yet).")
    )

    return WorkflowStudy(
        benchmark=BENCHMARK_SYMBOL,
        benchmark_return=benchmark_return,
        window=window,
        arms=tuple(arm_metrics),
        paired=tuple(paired),
        discrimination=discrimination,
        vibe_verdict_compliance=compliance,
        note=note,
        grounding_retry_rate=grounding_retry_rate,
        grounding_retry_waste_usd=grounding_retry_waste_usd,
        gate_concordance=concordance,
    )

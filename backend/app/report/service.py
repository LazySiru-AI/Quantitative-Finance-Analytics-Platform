"""Assembles a whole report: engines in, facts out, verified prose over the top.

The composition layer for Phase 8, following :mod:`app.backtest.service` and
:mod:`app.rules.service`. It owns three things that only exist at this seam.

**No engine failure empties the report.** Each of the four -- profile, drawdown, decision table,
strategy -- is called defensively. One that raises contributes no facts and leaves a warning, and
the sections that would have cited it stop building. A report of three sections and a stated reason
for the fourth is a useful document; a 500 is not.

**Prose that fails verification is dropped, never repaired.** A section whose draft does not ground
arrives with ``narrative=None`` and a warning naming the violations. There is deliberately no
fallback sentence: substituting a generic one would hide the fact that the intended sentence could
not be supported, which is the only interesting thing about the failure.

**Bars are read once.** Every engine here works from a single
:func:`app.market.store.ensure_series` call, the same entry point the chart, the decision table and
the workbench use -- so a report describes exactly the bars a chart for the same symbol would draw.
"""

from __future__ import annotations

import datetime as dt
from typing import Protocol

import pandas as pd

from app.backtest.models import (
    Costs,
    DrawdownBasis,
    DrawdownProfile,
    EquityPoint,
    GuardReport,
    StrategyMetrics,
    StrategyResult,
    StrategySpec,
    Trade,
)
from app.config import Settings
from app.db.duck import Interval
from app.market import store
from app.market.models import BarSeries, MarketWarning, Profile, Quote
from app.market.registry import ProviderRegistry
from app.report import narrative as narrative_module
from app.report.builder import DEFAULT_REPORT_BASIS, build_bundle
from app.report.models import (
    FactBundle,
    RenderedNarrative,
    Report,
    ReportSection,
)
from app.rules.models import DecisionTable

__all__ = ["build_report", "build_strategy_result"]


# ---------------------------------------------------------------------------
# Injectable collaborators
# ---------------------------------------------------------------------------


class BacktestService(Protocol):
    def build_drawdown_profile(
        self,
        cfg: Settings,
        symbol: str,
        interval: Interval,
        *,
        basis: DrawdownBasis = ...,
        top: int = ...,
        registry: ProviderRegistry | None = ...,
    ) -> DrawdownProfile: ...


class RulesService(Protocol):
    def build_decision_table(
        self,
        cfg: Settings,
        symbol: str,
        interval: Interval,
        *,
        registry: ProviderRegistry | None = ...,
    ) -> DecisionTable: ...


class Strategy(Protocol):
    """`app.backtest.strategy`'s entry point. Optional -- a report without a strategy section is a
    complete report, since a strategy is something the user asks for rather than a property of the
    instrument.

    The return tuple is spelled out rather than left as `object`: an untyped return propagates into
    every name it is unpacked into, and the resulting `StrategyResult` would be assembled from six
    values mypy cannot check against the model's fields -- which is exactly where a metrics/buy-hold
    transposition would hide.
    """

    def backtest(
        self,
        bars: pd.DataFrame,
        spec: StrategySpec,
        *,
        interval: Interval,
        costs: Costs,
        risk_free_rate: float,
    ) -> tuple[
        StrategyMetrics, StrategyMetrics, list[Trade], list[EquityPoint], float | None, int
    ]: ...


class Guards(Protocol):
    def check(self, expression: str, bars: pd.DataFrame, *, interval: Interval) -> GuardReport: ...


def _default_backtest() -> BacktestService:
    from app.backtest import service

    return service


def _default_rules() -> RulesService:
    from app.rules import service

    return service


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------


def _bars_frame(series: BarSeries) -> pd.DataFrame:
    """Identical construction to `app.rules.service._bars_frame`. See its docstring for why every
    price column is an explicit float64."""
    return pd.DataFrame(
        {
            "ts": pd.Series([b.ts for b in series.bars], dtype="datetime64[ns, UTC]"),
            **{
                column: pd.Series([getattr(b, column) for b in series.bars], dtype="float64")
                for column in ("open", "high", "low", "close", "adj_close", "volume")
            },
        }
    )


def _profile_and_quote(
    symbol: str, registry: ProviderRegistry | None, warnings: list[MarketWarning]
) -> tuple[Profile | None, Quote | None]:
    """Best-effort identity. A provider outage must cost the report its company name, not its
    statistics -- the numbers come from stored bars and do not need the network."""
    reg = registry
    profile: Profile | None = None
    quote: Quote | None = None
    if reg is None:
        return None, None
    try:
        profile = reg.get_profile(symbol)
    except Exception as exc:
        warnings.append(
            MarketWarning(kind="profile_unavailable", message=f"{symbol}: no profile ({exc})")
        )
    try:
        quote = reg.get_quote(symbol)
    except Exception as exc:
        warnings.append(
            MarketWarning(kind="quote_unavailable", message=f"{symbol}: no live quote ({exc})")
        )
    return profile, quote


def _sections(bundle: FactBundle) -> list[ReportSection]:
    """One section per default narrator, each verified independently.

    A section that fails verification keeps its place in the report carrying its violations. Dropping
    it would leave a document whose table of contents silently changes with the data.
    """
    sections: list[ReportSection] = []
    for section_id, narrator in narrative_module.DEFAULT_NARRATORS.items():
        title = narrative_module.SECTION_TITLES.get(section_id, section_id.title())
        draft = narrator(bundle)
        outcome = narrative_module.compose(draft, bundle)

        if isinstance(outcome, RenderedNarrative):
            sections.append(
                ReportSection(
                    section_id=section_id,
                    title=title,
                    narrative=outcome,
                    fact_ids=list(outcome.grounding.cited),
                    warnings=[],
                )
            )
            continue

        reasons = "; ".join(f"{v.kind.value}: {v.detail}" for v in outcome.violations[:3])
        sections.append(
            ReportSection(
                section_id=section_id,
                title=title,
                narrative=None,
                fact_ids=[],
                warnings=[
                    MarketWarning(
                        kind="ungrounded_narrative",
                        message=(
                            f"{title}: prose withheld because it did not ground against the "
                            f"computed facts ({reasons})"
                        ),
                    )
                ],
            )
        )
    return sections


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_report(
    cfg: Settings,
    symbol: str,
    interval: Interval,
    *,
    basis: DrawdownBasis = DEFAULT_REPORT_BASIS,
    top_drawdowns: int = 10,
    registry: ProviderRegistry | None = None,
    strategy: StrategyResult | None = None,
    backtest: BacktestService | None = None,
    rules: RulesService | None = None,
) -> Report:
    """One per-holding report.

    ``strategy`` is passed in rather than computed here: a strategy is a question the user asked,
    with its own entry and exit rules, not a property of the instrument. A report without one is
    complete.
    """
    backtest_mod = backtest or _default_backtest()
    rules_mod = rules or _default_rules()
    upper = symbol.upper()
    warnings: list[MarketWarning] = []

    series = store.ensure_series(upper, interval, registry=registry, settings=cfg)
    warnings.extend(series.warnings)
    bars = _bars_frame(series)
    first_bar = bars["ts"].min().date() if not bars.empty else None
    last_bar = bars["ts"].max().date() if not bars.empty else None

    profile, quote = _profile_and_quote(upper, registry, warnings)

    drawdown: DrawdownProfile | None = None
    try:
        drawdown = backtest_mod.build_drawdown_profile(
            cfg, upper, interval, basis=basis, top=top_drawdowns, registry=registry
        )
    except Exception as exc:
        warnings.append(
            MarketWarning(
                kind="engine_failed",
                message=f"{upper}: the drawdown profile could not be computed ({exc})",
            )
        )

    decisions: DecisionTable | None = None
    try:
        decisions = rules_mod.build_decision_table(cfg, upper, interval, registry=registry)
    except Exception as exc:
        warnings.append(
            MarketWarning(
                kind="engine_failed",
                message=f"{upper}: the decision table could not be computed ({exc})",
            )
        )

    bundle = build_bundle(
        upper,
        interval,
        profile=profile,
        quote=quote,
        drawdown=drawdown,
        decisions=decisions,
        strategy=strategy,
        bars=len(bars),
        first_bar=first_bar,
        last_bar=last_bar,
        warnings=[],
    )

    if bars.empty:
        warnings.append(
            MarketWarning(
                kind="short_history",
                message=(
                    f"{upper} {interval.value}: no stored bars -- this report is empty until data "
                    "is synced for this symbol and interval"
                ),
            )
        )

    return Report(
        symbol=upper,
        interval=interval,
        generated_at=dt.datetime.now(dt.UTC),
        profile=profile,
        quote=quote,
        bundle=bundle,
        sections=_sections(bundle),
        drawdown=drawdown,
        decisions=decisions,
        strategy=strategy,
        run_id=strategy.run_id if strategy is not None else None,
        warnings=warnings,
    )


def build_strategy_result(
    cfg: Settings,
    symbol: str,
    interval: Interval,
    spec: StrategySpec,
    *,
    costs: Costs | None = None,
    risk_free_rate: float = 0.0,
    registry: ProviderRegistry | None = None,
    strategy: Strategy | None = None,
    guards: Guards | None = None,
    runcards: object | None = None,
) -> StrategyResult:
    """Run one entry/exit backtest, guarded and recorded.

    The guard runs on **both** the entry and the exit expression before any equity curve is built,
    and a failure produces a result carrying the report and no metrics -- the same rule the workbench
    follows. An exit rule that peeks at the future is exactly as dangerous as an entry rule that
    does, and it is the one people forget to check.
    """
    from app.backtest import guards as guards_default
    from app.backtest import runcard as runcard_default
    from app.backtest import strategy as strategy_default
    from app.backtest.models import GuardStatus

    strategy_mod = strategy or strategy_default
    guards_mod = guards or guards_default
    runcards_mod = runcards or runcard_default
    upper = symbol.upper()
    cost_model = costs or Costs()
    warnings: list[MarketWarning] = []

    series = store.ensure_series(upper, interval, registry=registry, settings=cfg)
    warnings.extend(series.warnings)
    bars = _bars_frame(series)
    first_bar = bars["ts"].min().date() if not bars.empty else None
    last_bar = bars["ts"].max().date() if not bars.empty else None

    def empty(guard: GuardReport) -> StrategyResult:
        return StrategyResult(
            symbol=upper,
            interval=interval,
            generated_at=dt.datetime.now(dt.UTC),
            spec=spec,
            costs=cost_model,
            guard=guard,
            metrics=StrategyMetrics(),
            buy_hold=StrategyMetrics(),
            bars=len(bars),
            first_bar=first_bar,
            last_bar=last_bar,
            warnings=warnings,
        )

    if bars.empty:
        warnings.append(
            MarketWarning(
                kind="short_history",
                message=f"{upper} {interval.value}: no stored bars to backtest against",
            )
        )
        return empty(GuardReport(status=GuardStatus.UNVERIFIED, expression=spec.entry))

    # Both expressions, not just the entry.
    reports: list[GuardReport] = []
    for expression in (spec.entry, spec.exit):
        if not expression:
            continue
        try:
            report = guards_mod.check(expression, bars, interval=interval)
        except Exception as exc:
            report = GuardReport(status=GuardStatus.FAILED, expression=expression, findings=[])
            warnings.append(
                MarketWarning(kind="guard_failed", message=f"{expression}: guard errored ({exc})")
            )
        reports.append(report)

    failed = next((r for r in reports if r.status is not GuardStatus.PASSED), None)
    if failed is not None:
        warnings.append(
            MarketWarning(
                kind="guard_failed",
                message=(
                    f"{upper}: the lookahead guard did not pass for {failed.expression!r}, so no "
                    "metrics were computed"
                ),
            )
        )
        return empty(failed)

    combined = reports[0] if reports else GuardReport(status=GuardStatus.UNVERIFIED)

    try:
        metrics, buy_hold, trades, curve, cost_drag, open_trades = strategy_mod.backtest(
            bars, spec, interval=interval, costs=cost_model, risk_free_rate=risk_free_rate
        )
    except ValueError:
        # A malformed spec -- no exit and no horizon -- is the caller's error, not a server fault,
        # so it propagates to the API layer which turns it into a 422 rather than being swallowed
        # into a warning on an empty result that looks like the backtest simply found nothing.
        raise
    except Exception as exc:
        warnings.append(
            MarketWarning(
                kind="study_failed", message=f"{upper}: the backtest could not be run ({exc})"
            )
        )
        return empty(combined)

    result = StrategyResult(
        symbol=upper,
        interval=interval,
        generated_at=dt.datetime.now(dt.UTC),
        spec=spec,
        costs=cost_model,
        guard=combined,
        metrics=metrics,
        buy_hold=buy_hold,
        cost_drag=cost_drag,
        equity_curve=curve,
        trades=trades,
        open_trades=open_trades,
        bars=len(bars),
        first_bar=first_bar,
        last_bar=last_bar,
        warnings=warnings,
    )

    try:
        card = runcards_mod.make(  # type: ignore[attr-defined]
            "strategy",
            symbol=upper,
            interval=interval,
            params={
                "entry": spec.entry,
                "exit": spec.exit,
                "max_holding_bars": spec.max_holding_bars,
                "stop_loss_pct": spec.stop_loss_pct,
                "slippage_bps": cost_model.slippage_bps,
                "commission_per_trade": cost_model.commission_per_trade,
                "notional": cost_model.notional,
                "risk_free_rate": risk_free_rate,
            },
            bars=bars,
            results={"trades": metrics.trades, "total_return": metrics.total_return},
        )
        runcards_mod.write(card, settings=cfg)  # type: ignore[attr-defined]
    except Exception as exc:
        warnings.append(
            MarketWarning(
                kind="runcard_failed",
                message=(
                    f"{upper}: the backtest completed but its run card could not be written "
                    f"({exc}); this result is not reproducible from the audit trail"
                ),
            )
        )
        return result.model_copy(update={"warnings": warnings})

    return result.model_copy(update={"run_id": card.run_id, "warnings": warnings})

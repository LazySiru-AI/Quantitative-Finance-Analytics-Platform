"""Assembles the workbench's four studies: bars in, a guarded and recorded result out.

The composition layer for Phase 7, in the same spirit as :mod:`app.rules.service` composes the
grammar, the evaluator and the evidence statistics into a decision table. It owns no mathematics of
its own. What it owns is the four things that only exist at this seam.

**Bars are read exactly once per study.** Every builder calls
:func:`app.market.store.ensure_series` a single time -- the same entry point ``/api/market/bars``
and the decision table use, so a study sees exactly the bars a chart for the same symbol and
interval would -- and hands the resulting frame to every arm. Twelve conditions cost one store read.

**The guard runs before the statistics, and a failed guard means no statistics.** Not a warning
next to the numbers: no numbers. :attr:`~app.backtest.models.GuardStatus.UNVERIFIED` is treated as a
failure for the reason its own docstring gives -- a study that skipped verification must be visibly
different from one that passed, and the reassuring default is the dangerous one. A rejected arm
still appears in the output carrying its :class:`~app.backtest.models.GuardReport`, because a table
the user reads as "every condition I asked for" must not silently shrink.

**One bad condition must not empty the study**, the same rule
:func:`app.rules.service.build_decision_table` follows for one bad rule.

**Recording is best-effort; measuring is not.** A study that computed correctly must not fail
because its audit file could not be written. :func:`_record` degrades a run-card failure to a
warning and leaves ``run_id`` unset, so the result is visibly un-recorded rather than silently
lost -- or, worse, a 500 on a correct answer.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Protocol

import pandas as pd

from app.backtest.models import (
    STUDY_HORIZONS,
    ArmDelta,
    ConditionArm,
    DrawdownBasis,
    DrawdownEpisode,
    DrawdownProfile,
    EventStudy,
    GuardReport,
    GuardStatus,
    HorizonStats,
    IndicatorProfile,
    ReverseConditioning,
    RunCard,
    ScanResult,
)
from app.config import Settings
from app.db.duck import Interval
from app.market import store
from app.market.models import BarSeries, MarketWarning
from app.market.registry import ProviderRegistry
from app.rules.evaluate import IndicatorCache
from app.rules.models import Entry

__all__ = [
    "DEFAULT_REVERSE_INDICATORS",
    "build_drawdown_profile",
    "build_event_study",
    "build_reverse_conditioning",
    "build_scan",
]

#: What reverse conditioning profiles when the caller names nothing.
#:
#: Every registry indicator that is defined on daily bars, at its default configuration. Chosen to
#: be *broad* rather than clever: the whole point of reverse conditioning is to let the data suggest
#: conditions the user would not have thought to ask for, and a curated shortlist would smuggle the
#: author's priors into an operation whose only justification is that it has none.
DEFAULT_REVERSE_INDICATORS: tuple[str, ...] = (
    "sma:20",
    "sma:50",
    "ema:20",
    "ema:50",
    "rsi:14",
    "atr:14",
    "macd:12,26,9",
    "bb:20,2",
)


# ---------------------------------------------------------------------------
# Injectable collaborators
# ---------------------------------------------------------------------------
#
# Same Protocol + lazy-default shape as `app.rules.service`, and for the same two reasons: it lets
# the API layer and the tests substitute fakes without patching module globals, and it keeps this
# module importable independently of the siblings it composes.


class Drawdown(Protocol):
    def profile(
        self, bars: pd.DataFrame, *, basis: DrawdownBasis, top: int
    ) -> tuple[list[DrawdownEpisode], DrawdownEpisode | None, int]: ...


class Events(Protocol):
    def event_study(
        self,
        bars: pd.DataFrame,
        conditions: Sequence[str],
        *,
        interval: Interval,
        horizons: Sequence[int],
        entry: Entry,
        indicator_cache: IndicatorCache | None = None,
    ) -> tuple[list[ConditionArm], list[ArmDelta]]: ...

    def reverse_conditioning(
        self,
        bars: pd.DataFrame,
        indicators: Sequence[str],
        *,
        interval: Interval,
        horizon: int,
        quantile: float,
        lookback: int,
        entry: Entry,
    ) -> tuple[list[dt.date], int, int, list[IndicatorProfile]]: ...


class Guards(Protocol):
    def check(self, expression: str, bars: pd.DataFrame, *, interval: Interval) -> GuardReport: ...


class Evaluate(Protocol):
    """The per-entry seam `scan` calls back into. Structurally identical to
    `app.backtest.scan.Evaluate`, restated here so this module's Protocol does not require importing
    the sibling it is trying to stay decoupled from -- including `indicator_cache`, which must match
    `app.backtest.scan.Evaluate`'s own parameter exactly: `scan()`'s `evaluate` argument is typed
    against *that* module's `Evaluate`, and parameters are checked contravariantly, so letting the two
    drift apart (even by one optional keyword-only parameter) would make this module's `Scan` protocol
    -- see below -- structurally incompatible with the real `app.backtest.scan.scan` function.
    """

    def __call__(
        self,
        expression: str,
        horizon: int,
        *,
        indicator_cache: IndicatorCache | None = None,
    ) -> tuple[GuardReport, HorizonStats | None]: ...


class Scan(Protocol):
    def scan(
        self,
        symbol: str,
        interval: Interval,
        expressions: Sequence[str],
        horizons: Sequence[int],
        *,
        evaluate: Evaluate,
        entry: Entry = ...,
        alpha: float = ...,
        bars: int = ...,
        first_bar: dt.date | None = ...,
        last_bar: dt.date | None = ...,
        warnings: Sequence[MarketWarning] | None = ...,
        indicator_cache: IndicatorCache | None = ...,
    ) -> ScanResult: ...


class RunCards(Protocol):
    def make(
        self,
        kind: str,
        *,
        symbol: str,
        interval: Interval,
        params: dict[str, object],
        bars: pd.DataFrame,
        results: dict[str, object],
    ) -> RunCard: ...

    def write(self, card: RunCard, *, settings: Settings | None = None) -> object: ...


def _default_drawdown() -> Drawdown:
    from app.backtest import drawdown

    return drawdown


def _default_events() -> Events:
    from app.backtest import events

    return events


def _default_guards() -> Guards:
    from app.backtest import guards

    return guards


def _default_scan() -> Scan:
    from app.backtest import scan

    return scan


def _default_runcards() -> RunCards:
    from app.backtest import runcard

    return runcard


# ---------------------------------------------------------------------------
# Shared plumbing
# ---------------------------------------------------------------------------


def _bars_frame(series: BarSeries) -> pd.DataFrame:
    """The OHLCV frame every study expects, built once per study.

    Identical construction to `app.rules.service._bars_frame`: `ts` as tz-aware UTC and every price
    column an explicit `float64`, so a `None` volume on a halted session cannot leave the column
    `object`-dtyped and silently change the behaviour of every downstream rolling and ewm call.
    """
    return pd.DataFrame(
        {
            "ts": pd.Series([b.ts for b in series.bars], dtype="datetime64[ns, UTC]"),
            **{
                column: pd.Series([getattr(b, column) for b in series.bars], dtype="float64")
                for column in ("open", "high", "low", "close", "adj_close", "volume")
            },
        }
    )


def _load(
    cfg: Settings, symbol: str, interval: Interval, registry: ProviderRegistry | None
) -> tuple[pd.DataFrame, list[MarketWarning]]:
    """Read bars once and return them with any provenance warnings the store attached.

    A `ProviderError` is deliberately not caught -- a confirmed-missing symbol or every provider
    down with nothing stored is a real error the API layer maps to a status, exactly as
    `app.rules.service.build_decision_table` leaves it to propagate.
    """
    series = store.ensure_series(symbol, interval, registry=registry, settings=cfg)
    return _bars_frame(series), list(series.warnings)


def _empty_warning(symbol: str, interval: Interval) -> MarketWarning:
    return MarketWarning(
        kind="short_history",
        message=(
            f"{symbol} {interval.value}: no stored bars -- this study is empty until data is "
            "synced for this symbol and interval"
        ),
    )


def _record(
    kind: str,
    *,
    symbol: str,
    interval: Interval,
    params: dict[str, object],
    bars: pd.DataFrame,
    results: dict[str, object],
    warnings: list[MarketWarning],
    cfg: Settings,
    runcards: RunCards,
) -> str | None:
    """Write a run card, degrading any failure to a warning. See the module docstring.

    Returns the ``run_id`` on success and ``None`` on failure, so the caller renders a visibly
    un-recorded result rather than one carrying an id that points at nothing.
    """
    try:
        card = runcards.make(
            kind,
            symbol=symbol,
            interval=interval,
            params=params,
            bars=bars,
            results=results,
        )
        runcards.write(card, settings=cfg)
    except Exception as exc:
        warnings.append(
            MarketWarning(
                kind="runcard_failed",
                message=(
                    f"{symbol}: the study completed but its run card could not be written "
                    f"({type(exc).__name__}: {exc}); this result is not reproducible from the "
                    "audit trail"
                ),
            )
        )
        return None
    return card.run_id


def _span(bars: pd.DataFrame) -> tuple[dt.date | None, dt.date | None]:
    if bars.empty:
        return None, None
    return bars["ts"].min().date(), bars["ts"].max().date()


def _rejected_arm(expression: str, guard: GuardReport) -> ConditionArm:
    """An arm whose guard did not pass: present, explained, and carrying no numbers."""
    return ConditionArm(
        label=expression,
        expression=expression,
        guard=guard,
        stats=[],
        trigger_dates=[],
        triggers=0,
        evaluable_bars=0,
        warnings=[
            MarketWarning(
                kind="guard_failed",
                message=(
                    f"{expression}: the lookahead guard did not pass, so no statistics were "
                    "computed for this condition"
                ),
            )
        ],
    )


def _guard_all(
    expressions: Sequence[str], bars: pd.DataFrame, *, interval: Interval, guards: Guards
) -> dict[str, GuardReport]:
    """Guard every expression once, keyed by expression text.

    A guard that itself raises becomes a FAILED report rather than escaping: the module's job is to
    refuse, and a refusal that arrives as a traceback is one the caller can accidentally swallow.
    """
    reports: dict[str, GuardReport] = {}
    for expression in expressions:
        if expression in reports:
            continue
        try:
            reports[expression] = guards.check(expression, bars, interval=interval)
        except Exception as exc:
            reports[expression] = GuardReport(
                status=GuardStatus.FAILED,
                expression=expression,
                findings=[],
            )
            del exc
    return reports


# ---------------------------------------------------------------------------
# Drawdown
# ---------------------------------------------------------------------------


def build_drawdown_profile(
    cfg: Settings,
    symbol: str,
    interval: Interval,
    *,
    basis: DrawdownBasis = DrawdownBasis.CLOSE,
    top: int = 10,
    registry: ProviderRegistry | None = None,
    drawdown: Drawdown | None = None,
) -> DrawdownProfile:
    """Every material drawdown for one instrument, deepest first.

    The one study with no guard and no run card: it tests no hypothesis, so there is nothing for a
    lookahead check to be about and nothing whose reproducibility is in question beyond the bars
    themselves. See :class:`~app.backtest.models.DrawdownProfile`.
    """
    drawdown_mod = drawdown or _default_drawdown()
    upper = symbol.upper()
    bars, warnings = _load(cfg, upper, interval, registry)
    first_bar, last_bar = _span(bars)

    if bars.empty:
        warnings.append(_empty_warning(upper, interval))
        episodes: list[DrawdownEpisode] = []
        current: DrawdownEpisode | None = None
        considered = 0
    else:
        episodes, current, considered = drawdown_mod.profile(bars, basis=basis, top=top)

    return DrawdownProfile(
        symbol=upper,
        interval=interval,
        basis=basis,
        generated_at=dt.datetime.now(dt.UTC),
        bars=len(bars),
        first_bar=first_bar,
        last_bar=last_bar,
        episodes=episodes,
        episodes_considered=considered,
        current=current,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Event study
# ---------------------------------------------------------------------------


def build_event_study(
    cfg: Settings,
    symbol: str,
    interval: Interval,
    conditions: Sequence[str],
    *,
    horizons: Sequence[int] = STUDY_HORIZONS,
    entry: Entry = Entry.NEXT_OPEN,
    registry: ProviderRegistry | None = None,
    events: Events | None = None,
    guards: Guards | None = None,
    runcards: RunCards | None = None,
) -> EventStudy:
    """One or more conditions measured forward against a shared baseline.

    Conditions whose guard does not pass are replaced by a rejected arm and are **not** passed to
    the event-study maths at all -- see the module docstring. If every condition is rejected, the
    study comes back with rejected arms and no deltas rather than an error, because "none of what
    you asked for could be verified" is a result.
    """
    events_mod = events or _default_events()
    guards_mod = guards or _default_guards()
    runcards_mod = runcards or _default_runcards()
    upper = symbol.upper()
    horizon_list = list(horizons)

    bars, warnings = _load(cfg, upper, interval, registry)
    first_bar, last_bar = _span(bars)
    generated_at = dt.datetime.now(dt.UTC)

    if bars.empty:
        warnings.append(_empty_warning(upper, interval))
        return EventStudy(
            symbol=upper,
            interval=interval,
            generated_at=generated_at,
            entry=entry,
            horizons=horizon_list,
            bars=0,
            first_bar=None,
            last_bar=None,
            arms=[],
            deltas=[],
            run_id=None,
            warnings=warnings,
        )

    reports = _guard_all(conditions, bars, interval=interval, guards=guards_mod)
    cleared = [c for c in conditions if reports[c].ok]

    arms: list[ConditionArm] = []
    deltas: list[ArmDelta] = []
    if cleared:
        # One `IndicatorCache` for this single `event_study` call, matching `build_scan`'s reasoning:
        # every arm in `cleared` is evaluated against the same `bars` frame `event_study` was handed,
        # so two catalog conditions that both reference the same indicator (`rsi_oversold` and
        # `rsi_overbought`, both wanting `rsi:14`) compute it once between them rather than once each.
        try:
            computed, deltas = events_mod.event_study(
                bars,
                cleared,
                interval=interval,
                horizons=horizon_list,
                entry=entry,
                indicator_cache=IndicatorCache(),
            )
        except Exception as exc:
            warnings.append(
                MarketWarning(
                    kind="study_failed",
                    message=f"{upper}: the event study could not be computed ({exc})",
                )
            )
            computed, deltas = [], []
        by_expression = {arm.expression: arm for arm in computed}
    else:
        by_expression = {}

    for condition in conditions:
        report = reports[condition]
        arm = by_expression.get(condition)
        if arm is None:
            arms.append(_rejected_arm(condition, report))
        else:
            arms.append(arm.model_copy(update={"guard": report}))

    run_id = _record(
        "event_study",
        symbol=upper,
        interval=interval,
        params={
            "conditions": list(conditions),
            "horizons": horizon_list,
            "entry": entry.value,
        },
        bars=bars,
        results={"arms": len(arms), "cleared": len(cleared)},
        warnings=warnings,
        cfg=cfg,
        runcards=runcards_mod,
    )

    return EventStudy(
        symbol=upper,
        interval=interval,
        generated_at=generated_at,
        entry=entry,
        horizons=horizon_list,
        bars=len(bars),
        first_bar=first_bar,
        last_bar=last_bar,
        arms=arms,
        deltas=deltas,
        run_id=run_id,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Reverse conditioning
# ---------------------------------------------------------------------------


def build_reverse_conditioning(
    cfg: Settings,
    symbol: str,
    interval: Interval,
    *,
    horizon: int = 20,
    quantile: float = 0.9,
    lookback: int = 0,
    indicators: Sequence[str] = (),
    entry: Entry = Entry.NEXT_OPEN,
    registry: ProviderRegistry | None = None,
    events: Events | None = None,
    runcards: RunCards | None = None,
) -> ReverseConditioning:
    """What the indicators were doing before the biggest moves. **Exploratory output.**

    No guard runs here, and that is deliberate rather than an omission: there is no hypothesis to
    guard. The moves are selected on their own forward return, so the operation is a description of
    the sample by construction -- which is exactly why
    :class:`~app.backtest.models.ReverseConditioning` carries no hit rate, p-value or q-value for a
    guard to protect. A candidate read off this table becomes a claim only when it is tested as a
    declared trial in a scan, and *that* is guarded.
    """
    events_mod = events or _default_events()
    runcards_mod = runcards or _default_runcards()
    upper = symbol.upper()
    specs = list(indicators) if indicators else list(DEFAULT_REVERSE_INDICATORS)

    bars, warnings = _load(cfg, upper, interval, registry)
    generated_at = dt.datetime.now(dt.UTC)

    selected_dates: list[dt.date] = []
    selected_count = 0
    independent_count = 0
    profiles: list[IndicatorProfile] = []

    if bars.empty:
        warnings.append(_empty_warning(upper, interval))
    else:
        try:
            selected_dates, selected_count, independent_count, profiles = (
                events_mod.reverse_conditioning(
                    bars,
                    specs,
                    interval=interval,
                    horizon=horizon,
                    quantile=quantile,
                    lookback=lookback,
                    entry=entry,
                )
            )
        except Exception as exc:
            warnings.append(
                MarketWarning(
                    kind="study_failed",
                    message=f"{upper}: reverse conditioning could not be computed ({exc})",
                )
            )

    run_id = (
        None
        if bars.empty
        else _record(
            "reverse",
            symbol=upper,
            interval=interval,
            params={
                "horizon": horizon,
                "quantile": quantile,
                "lookback": lookback,
                "indicators": specs,
                "entry": entry.value,
            },
            bars=bars,
            results={"selected": selected_count, "independent": independent_count},
            warnings=warnings,
            cfg=cfg,
            runcards=runcards_mod,
        )
    )

    return ReverseConditioning(
        symbol=upper,
        interval=interval,
        generated_at=generated_at,
        horizon=horizon,
        quantile=quantile,
        lookback=lookback,
        selected_dates=selected_dates,
        selected_count=selected_count,
        independent_selected_count=independent_count,
        profiles=profiles,
        exploratory=True,
        run_id=run_id,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


def build_scan(
    cfg: Settings,
    symbol: str,
    interval: Interval,
    expressions: Sequence[str],
    *,
    horizons: Sequence[int] = STUDY_HORIZONS,
    entry: Entry = Entry.NEXT_OPEN,
    alpha: float = 0.10,
    registry: ProviderRegistry | None = None,
    events: Events | None = None,
    guards: Guards | None = None,
    scan: Scan | None = None,
    runcards: RunCards | None = None,
) -> ScanResult:
    """Every expression against every horizon, corrected across the whole set.

    The evaluation seam handed to :func:`app.backtest.scan.scan` guards first and computes second,
    so a rejected expression consumes its trials without contributing statistics. That is the
    honest accounting: the condition *was* tested, it just could not be trusted, and removing it
    from the denominator would flatter every other entry's q-value.

    A single :class:`~app.rules.evaluate.IndicatorCache` is built for this call and threaded through
    every evaluation it performs -- see the ``indicator_cache`` local below for why that is sound and
    :func:`app.backtest.events.event_study` for where it is actually spent. A scan built around one
    shared indicator (``rsi:14`` across thirty expressions) computes it once for the whole call
    rather than once per expression.
    """
    events_mod = events or _default_events()
    guards_mod = guards or _default_guards()
    scan_mod = scan or _default_scan()
    runcards_mod = runcards or _default_runcards()
    upper = symbol.upper()
    horizon_list = list(horizons)

    bars, warnings = _load(cfg, upper, interval, registry)
    first_bar, last_bar = _span(bars)

    if bars.empty:
        warnings.append(_empty_warning(upper, interval))

    reports = (
        {}
        if bars.empty
        else _guard_all(expressions, bars, interval=interval, guards=guards_mod)
    )
    # One evaluation per expression, reused across every horizon: `event_study` computes all
    # horizons in a single pass, so calling it per (expression, horizon) pair would recompute the
    # same signal `len(horizons)` times for no additional information.
    cache: dict[str, dict[int, HorizonStats]] = {}
    # A request-scoped `IndicatorCache`, threaded all the way through `scan_mod.scan` and into
    # `events_mod.event_study` via the closure below -- see `app.rules.evaluate`'s module docstring
    # for the design. Every call this cache reaches shares the identical `bars` object built once
    # above by `_load`: `scan_mod.scan` calls `evaluate(expression, horizon, indicator_cache=...)`
    # for every (expression, horizon) pair, and the closure below calls `events_mod.event_study`
    # against that same `bars` frame -- one call per distinct expression, memoised across horizons in
    # `cache`. A single `IndicatorCache` spanning every one of those calls is therefore correct by
    # `IndicatorCache`'s own precondition (one cache, one bar frame), and its fingerprint guard is
    # what would catch it if that ever stopped being true. Built unconditionally -- `Events` and
    # `Scan` both declare this parameter in their Protocols (see above), so any injected collaborator
    # is guaranteed to accept it structurally; `mypy --strict` over the Protocol is what enforces
    # that, not a runtime check -- see `app.rules.service`'s `Evaluator` docstring for the same
    # reasoning applied one layer down.
    indicator_cache = IndicatorCache()

    def evaluate(
        expression: str, horizon: int, *, indicator_cache: IndicatorCache | None = None
    ) -> tuple[GuardReport, HorizonStats | None]:
        report = reports.get(expression) or GuardReport(
            status=GuardStatus.FAILED, expression=expression, findings=[]
        )
        if not report.ok or bars.empty:
            return report, None
        if expression not in cache:
            arms, _ = events_mod.event_study(
                bars,
                [expression],
                interval=interval,
                horizons=horizon_list,
                entry=entry,
                indicator_cache=indicator_cache,
            )
            cache[expression] = {s.horizon: s for s in arms[0].stats} if arms else {}
        return report, cache[expression].get(horizon)

    result = scan_mod.scan(
        upper,
        interval,
        expressions,
        horizon_list,
        evaluate=evaluate,
        indicator_cache=indicator_cache,
        entry=entry,
        alpha=alpha,
        bars=len(bars),
        first_bar=first_bar,
        last_bar=last_bar,
        warnings=warnings,
    )

    if bars.empty:
        return result

    run_id = _record(
        "scan",
        symbol=upper,
        interval=interval,
        params={
            "expressions": list(expressions),
            "horizons": horizon_list,
            "entry": entry.value,
            "alpha": alpha,
        },
        bars=bars,
        results={"trials": result.trials, "discoveries": result.discoveries},
        warnings=warnings,
        cfg=cfg,
        runcards=runcards_mod,
    )
    return result.model_copy(update={"run_id": run_id, "warnings": warnings})

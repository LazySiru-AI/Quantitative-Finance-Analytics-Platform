"""Computation core for the multi-timeframe rule-accuracy study.

Answers, for one rule at one interval on one symbol (or pooled across a sector/the universe): when
this rule fired, did price go the way it implied, more often than it does anyway? See
`docs/research/timeframes/04-accuracy-methodology.md` for the reasoning and
`docs/research/timeframes/06-interface-contract.md` section 3 for the frozen signatures this module
implements.

**Reused rather than reimplemented, and why:**

- `app.backtest.forward.forward_returns` -- the one lookahead-proven forward-return implementation
  in this codebase (`NEXT_OPEN`: entry at bar `t+1`'s open, exit at bar `t+horizon`'s close). Never
  reimplemented here; a second copy is exactly how a decision table and a research sweep end up
  reporting different numbers for the same question.
- `app.backtest.forward.hit_rate` -- `mean(returns > 0)`, `None` on an empty sample. Reused wherever
  a plain win-rate over an already-masked array is needed.
- `app.backtest.forward.independent_mask` -- the greedy non-overlap scan, called here on rising-edge
  *episode* positions (see `app.timeframes.stats.rising_edges`) rather than raw triggered-bar
  positions, which is the one behavioural change this module makes on top of what `evidence.py`
  already does (see the module docstring on `app.rules.evidence` and section 3 of the methodology
  doc for why raw-bar counting is not reused for the point estimate).
- `app.rules.grammar.parse` / `app.rules.evaluate.evaluate` -- the rule DSL parser and evaluator,
  unchanged. `app.rules.evaluate.IndicatorCache` is used exactly as designed: one instance per
  `(symbol, interval)` bar frame, shared across every rule and horizon evaluated against it, so an
  indicator referenced by two catalogued rules (`rsi:14` appears in both `rsi_oversold` and
  `rsi_overbought`) is computed once, not once per rule.
- `app.rules.evidence.compute_evidence` is deliberately **not** called. Its point estimate
  (`Evidence.hit_rate`) is computed over every raw triggered bar; this module's point estimate is
  computed over rising-edge episodes only (§3 of the methodology doc: "400 consecutive firing bars
  under one persistent condition is one opportunity observed 400 times, not 400"). Calling
  `compute_evidence` and then discarding its `hit_rate` while keeping only its horizon plumbing would
  cost the same forward-return computation twice for no benefit; `forward_returns` is called
  directly instead.
- `app.indicators.registry` -- indicator resolution and computation for `signal_trace`'s chart
  series, via the same `request`/`compute` pair `evaluate.py` already uses internally.

This package never imports `app.backtest.strategy`, `app.backtest.metrics`, or `BARS_PER_YEAR` --
see the package docstring in `app/timeframes/__init__.py` for why staying off the annualization path
is the point, not an oversight.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

import numpy as np
import pandas as pd

from app.backtest.forward import forward_returns, independent_mask
from app.config import Settings, get_settings
from app.db.duck import Interval
from app.indicators import registry as indicator_registry
from app.market.models import Bar
from app.market.store import read_frame
from app.rules import catalog as rule_catalog
from app.rules import grammar
from app.rules.evaluate import IndicatorCache, RuleEvaluationError, evaluate, required_specs
from app.rules.grammar import RuleSyntaxError
from app.rules.models import HORIZONS, Entry, Rule
from app.rules.nodes import BoolExpr
from app.timeframes.models import (
    DEFAULT_COST_BPS,
    FDR_ALPHA,
    MIN_INDEPENDENT,
    IndicatorSeries,
    Regime,
    RuleAccuracyCell,
    Scope,
    SignalTrace,
    interval_minutes,
    sector_of,
)
from app.timeframes.stats import benjamini_hochberg, lift_ci, rising_edges, two_proportion_p

__all__ = ["aggregate", "compute_cells", "signal_trace"]

#: Trailing-return window for regime classification (methodology doc §8): never shorter than the
#: longest forward horizon being measured, so a bar's regime label at trigger time is never itself a
#: function of data the forward return also depends on.
_REGIME_WINDOW: Final[int] = max(HORIZONS)

#: A pair with fewer bars than this cannot support even the shortest horizon's forward return.
_MIN_BARS_FOR_A_PAIR: Final[int] = 2

#: The only entry convention this module measures -- see `app.rules.evidence`'s module docstring for
#: why `SAME_CLOSE` is a research-only upper bound, never an estimate of a tradeable result.
_ENTRY: Final[Entry] = Entry.NEXT_OPEN

#: Confidence level for `lift_ci`/`wilson_interval`, deliberately distinct from `FDR_ALPHA`: this one
#: governs a single cell's own interval width (conventional 95%), `FDR_ALPHA` governs the
#: multiple-comparison threshold applied once across the whole returned grid. Conflating the two
#: would make the interval width silently depend on how many other cells happened to be requested in
#: the same call.
_CI_ALPHA: Final[float] = 0.05

#: Below this many stored bars a cell's warmup/regime slicing is thin enough to be worth a warning
#: even before the sufficiency gate has a chance to say so on its own.
_SHORT_HISTORY_BARS: Final[int] = 250

_ALL_REGIMES: Final[tuple[str, ...]] = ("all", "rising", "falling")


@dataclass(frozen=True, slots=True)
class _RawStats:
    """Everything one `RuleAccuracyCell`'s numbers are built from, kept as raw counts and arrays.

    Never as pre-averaged rates -- that is precisely what lets :func:`aggregate` *pool* several of
    these (sum the counts, concatenate the return arrays) instead of averaging already-computed
    rates across them, which is the Simpson's-paradox trap the interface contract calls out by name.
    """

    n_raw: int
    n_episodes: int
    n_independent: int
    trigger_returns: np.ndarray
    """Forward returns of the surviving *independent* (non-overlapping) episodes only -- the sample
    `hit_rate` and `median_return` are drawn from, not `n_raw` and not `n_episodes` alone."""
    baseline_returns: np.ndarray
    """Forward returns of every evaluable bar in the identical window -- `base_rate`'s sample."""
    n_base_effective: int
    """A conservative *independent-equivalent* sample size for the baseline, used only for the CI
    and p-value (never for the `base_rate` point estimate itself, which uses the full evaluable
    count via `baseline_returns.size`): `n_evaluable_bars // horizon_bars`, an upper bound on how
    many truly non-overlapping horizon-length windows the baseline slice could contain. Without this
    shrinkage, `lift_ci`/`two_proportion_p` would treat thousands of heavily overlapping bars as
    that many independent draws and report an interval far narrower than the data supports."""
    first_bar: dt.datetime
    last_bar: dt.datetime


def _select_rules(rule_ids: Sequence[str] | None) -> list[Rule]:
    if rule_ids is None:
        return rule_catalog.catalog()
    rules: list[Rule] = []
    for rule_id in rule_ids:
        rule = rule_catalog.get(rule_id)
        if rule is not None:
            rules.append(rule)
    return rules


def _bars_for_pair(symbol: str, interval: Interval, settings: Settings) -> pd.DataFrame | None:
    """Stored bars for `(symbol, interval)`, or `None` if there are not enough to compute anything.

    `read_frame` -- the project's own stored-bar read path, never raw parquet -- resamples `1w` from
    daily on read and never talks to a network provider; this module is pure computation over
    whatever is already on disk, exactly like the package docstring promises.
    """
    bars = read_frame(symbol, interval, settings=settings)
    if len(bars) < _MIN_BARS_FOR_A_PAIR:
        return None
    return bars


def _pair_warnings(interval: Interval, bars: pd.DataFrame) -> tuple[str, ...]:
    warnings: list[str] = []
    if interval.is_intraday:
        warnings.append(
            "intraday rolling windows silently span the overnight gap -- a lookback window on the "
            "first bars of a session blends in closes from the prior session"
        )
    if interval is Interval.FOUR_HOUR:
        warnings.append(
            "4h bars alternate 4h/2.5h session durations -- forward windows measured in bars are "
            "not equal-length in calendar time"
        )
    if len(bars) < _SHORT_HISTORY_BARS:
        warnings.append(f"short history: only {len(bars)} bars stored for this symbol/interval")
    return tuple(warnings)


def _signal_for_rule(
    rule: Rule, bars: pd.DataFrame, interval: Interval, cache: IndicatorCache
) -> pd.Series | None:
    """The rule's truth series against `bars`, or `None` if it cannot be evaluated here.

    `None` covers two distinct, both non-fatal cases: the rule is declared not to apply to this
    interval (`Rule.intervals`, e.g. the VWAP-reclaim rule on daily bars), or parsing/evaluation
    itself fails (`RuleSyntaxError`/`RuleEvaluationError`) -- which should not happen for the fixed
    catalog this module reads from, but a corrupted or future catalog entry must degrade this one
    rule for this one pair rather than aborting the whole sweep.
    """
    if rule.intervals and interval not in rule.intervals:
        return None
    try:
        node = grammar.parse(rule.expression)
        return evaluate(node, bars, interval=interval, indicator_cache=cache)
    except (RuleSyntaxError, RuleEvaluationError):
        return None


def _regime_arrays(bars: pd.DataFrame) -> dict[str, np.ndarray]:
    """Boolean `rising`/`falling` masks, one entry per bar position in `bars`.

    A bar's regime is its own trailing `_REGIME_WINDOW`-bar return, classified `rising` if positive
    and `falling` otherwise (methodology doc §8: two buckets, not three -- a third needs an
    additional, arbitrary volatility threshold and tends to push at least one bucket below the
    sufficiency gate anyway). The first `_REGIME_WINDOW` bars of the series have no trailing window
    and are `False` in both masks -- excluded from both regime buckets, not folded into either.
    """
    closes = bars["close"].to_numpy(dtype=float)
    n = closes.size
    trailing = np.full(n, np.nan, dtype=float)
    if n > _REGIME_WINDOW:
        trailing[_REGIME_WINDOW:] = closes[_REGIME_WINDOW:] / closes[:-_REGIME_WINDOW] - 1.0
    has_regime = ~np.isnan(trailing)
    return {
        "rising": has_regime & (trailing > 0),
        "falling": has_regime & (trailing <= 0),
    }


def _raw_stats_for(
    bars: pd.DataFrame,
    signal: pd.Series,
    *,
    horizon: int,
    regime: str,
    regime_arrays: dict[str, np.ndarray] | None,
) -> _RawStats:
    """The raw counts and return arrays one `(rule, interval, symbol, horizon, regime)` cell needs.

    `hit_rate`'s sample is the *independent* (rising-edge, non-overlapping) episodes only --
    `n_raw`/`n_episodes` are still computed and returned (the "how often is this condition true"
    question `evidence.py`'s own docstring insists stays answerable) but do not feed the point
    estimate. `base_rate`'s sample is every evaluable bar in the identical window, exactly per the
    contract -- no independence filtering there, since it never claims to be a set of independent
    trials, only "what normally happens here".
    """
    returns = forward_returns(bars, horizon=horizon, entry=_ENTRY)
    known_mask = signal.notna().to_numpy(dtype=bool)
    true_mask = signal.fillna(False).to_numpy(dtype=bool)
    evaluable = known_mask & ~np.isnan(returns)

    if regime != "all":
        assert regime_arrays is not None
        evaluable = evaluable & regime_arrays[regime]

    edges = rising_edges(signal).to_numpy(dtype=bool)
    episode_mask = edges & evaluable
    episode_positions = np.flatnonzero(episode_mask)

    triggered = evaluable & true_mask
    n_raw = int(triggered.sum())
    n_episodes = int(episode_positions.size)

    survivors = independent_mask(episode_positions, horizon)
    indep_positions = episode_positions[survivors]
    n_independent = int(indep_positions.size)

    trigger_returns = returns[indep_positions]

    baseline_positions = np.flatnonzero(evaluable)
    baseline_returns = returns[baseline_positions]
    n_base = int(baseline_positions.size)
    n_base_effective = max(1, n_base // horizon) if n_base > 0 else 0

    ts = bars["ts"]
    first_bar = ts.iloc[0].to_pydatetime()
    last_bar = ts.iloc[-1].to_pydatetime()

    return _RawStats(
        n_raw=n_raw,
        n_episodes=n_episodes,
        n_independent=n_independent,
        trigger_returns=trigger_returns,
        baseline_returns=baseline_returns,
        n_base_effective=n_base_effective,
        first_bar=first_bar,
        last_bar=last_bar,
    )


def _pool_raw_stats(raws: Sequence[_RawStats]) -> _RawStats:
    """Sum counts and concatenate return arrays -- pooling, never averaging per-member rates.

    This is what makes a rule like `ema_golden_cross` measurable at all: it fails the
    `n_independent >= MIN_INDEPENDENT` gate for every single symbol (~10-12 episodes each, verified),
    so no individual member's `RuleAccuracyCell` ever carries a `hit_rate` to average. Pooling
    instead sums every member's `n_independent` (and every other count) *before* the gate is
    evaluated once on the total, and concatenates the underlying per-episode/per-bar return arrays so
    the pooled `hit_rate`/`median_return` are computed from the true combined sample -- not
    reconstructed from numbers that were nulled out by an individual member's own insufficiency.
    """
    return _RawStats(
        n_raw=sum(r.n_raw for r in raws),
        n_episodes=sum(r.n_episodes for r in raws),
        n_independent=sum(r.n_independent for r in raws),
        trigger_returns=np.concatenate([r.trigger_returns for r in raws]),
        baseline_returns=np.concatenate([r.baseline_returns for r in raws]),
        n_base_effective=sum(r.n_base_effective for r in raws),
        first_bar=min(r.first_bar for r in raws),
        last_bar=max(r.last_bar for r in raws),
    )


#: Static bars-to-calendar-time bucket ladder (methodology doc §5): a grouping/label lookup only,
#: never used to compute a number. Ceilings are in nominal calendar minutes
#: (`app.timeframes.models.interval_minutes`); a horizon's label is the first bucket it fits under.
_HORIZON_BUCKETS: Final[tuple[tuple[int, str], ...]] = (
    (15, "~15 minutes"),
    (120, "~2 hours"),
    (390, "~1 day"),
    (1_950, "~1 week"),
    (7_800, "~1 month"),
    (23_400, "~1 quarter"),
)


def _horizon_label(horizon_minutes: int) -> str:
    for ceiling, label in _HORIZON_BUCKETS:
        if horizon_minutes <= ceiling:
            return label
    return "~6+ months"


def _cell_kwargs_from_raw(
    raw: _RawStats,
    *,
    rule_id: str,
    interval: Interval,
    scope: Scope,
    scope_key: str,
    horizon_bars: int,
    regime: str,
    cost_bps: float,
    warnings: tuple[str, ...],
) -> dict[str, Any]:
    """Every `RuleAccuracyCell` field except `q_value` (filled in once, across the whole grid, by
    `_finalize`) as a plain dict -- not a constructed `RuleAccuracyCell` -- so BH can run before the
    (frozen, validated) model is built exactly once per cell.
    """
    sufficient = raw.n_independent >= MIN_INDEPENDENT
    horizon_mins = horizon_bars * interval_minutes(interval)

    kwargs: dict[str, Any] = dict(
        rule_id=rule_id,
        interval=interval,
        scope=scope,
        scope_key=scope_key,
        horizon_bars=horizon_bars,
        horizon_minutes=horizon_mins,
        horizon_label=_horizon_label(horizon_mins),
        n_raw=raw.n_raw,
        n_episodes=raw.n_episodes,
        n_independent=raw.n_independent,
        sufficient=sufficient,
        cost_bps_assumed=cost_bps,
        regime=regime,
        first_bar=raw.first_bar,
        last_bar=raw.last_bar,
        warnings=warnings,
        p_value=None,
    )
    if not sufficient:
        return kwargs

    n_rule = int(raw.trigger_returns.size)
    hits_rule = int(np.sum(raw.trigger_returns > 0))
    hit_rate = hits_rule / n_rule

    n_base = int(raw.baseline_returns.size)
    hits_base = int(np.sum(raw.baseline_returns > 0))
    base_rate = hits_base / n_base

    n_base_effective = raw.n_base_effective
    hits_base_effective = round(base_rate * n_base_effective)

    lift = hit_rate - base_rate
    ci = lift_ci(hits_rule, n_rule, hits_base_effective, n_base_effective, alpha=_CI_ALPHA)
    p_value = two_proportion_p(hits_rule, n_rule, hits_base_effective, n_base_effective)

    median_return = float(np.median(raw.trigger_returns))
    baseline_median_return = float(np.median(raw.baseline_returns))

    # Cost-adjusted edge: haircut every triggered episode's return by the assumed round-trip cost,
    # then recompute the *win probability* on that net-of-cost sample and subtract the (uncosted)
    # baseline -- see the module docstring for why this, not a return-scale figure, is the exact
    # quantity asked for. The baseline is deliberately left uncosted: it represents "what the market
    # does anyway", no trade is placed to observe it, so no round-trip friction applies to it.
    cost_frac = cost_bps / 10_000
    net_returns = raw.trigger_returns - cost_frac
    cost_adjusted_hit_rate = float(np.mean(net_returns > 0))
    cost_adjusted_edge = cost_adjusted_hit_rate - base_rate

    kwargs.update(
        hit_rate=hit_rate,
        base_rate=base_rate,
        lift=lift,
        lift_ci_low=ci[0] if ci is not None else None,
        lift_ci_high=ci[1] if ci is not None else None,
        median_return=median_return,
        baseline_median_return=baseline_median_return,
        p_value=p_value,
        cost_adjusted_edge=cost_adjusted_edge,
    )
    return kwargs


def _finalize(kwargs_list: list[dict[str, Any]]) -> list[RuleAccuracyCell]:
    """Run Benjamini-Hochberg once over the whole grid, then build every (frozen, validated)
    `RuleAccuracyCell` in one pass. Cells are immutable by design (`ConfigDict(frozen=True)`) --
    building each one exactly once, with `q_value` already known, is simpler and safer than
    constructing twice and patching, and it means the model's own invariant validator runs on the
    real, final field values every time, not on a placeholder that is later mutated around it.
    """
    p_values = [kwargs["p_value"] for kwargs in kwargs_list]
    q_values = benjamini_hochberg(p_values, FDR_ALPHA)
    return [
        RuleAccuracyCell(**{**kwargs, "q_value": q})
        for kwargs, q in zip(kwargs_list, q_values, strict=True)
    ]


def compute_cells(
    *,
    symbols: Sequence[str],
    intervals: Sequence[Interval],
    rule_ids: Sequence[str] | None = None,
    horizons: Sequence[int] = HORIZONS,
    cost_bps: float = DEFAULT_COST_BPS,
    regimes: bool = False,
    settings: Settings,
) -> list[RuleAccuracyCell]:
    """One `RuleAccuracyCell` per `(symbol, interval, rule, horizon[, regime])` combination.

    The unit of work is the `(symbol, interval)` pair, per the interface contract's performance
    requirement: bars are read once, one `IndicatorCache` is built, and every rule and every horizon
    for that pair is evaluated against the same cache before moving to the next pair -- an indicator
    shared by two rules (`rsi:14` in both `rsi_oversold` and `rsi_overbought`) is computed once per
    pair, not once per rule.

    `q_value` (Benjamini-Hochberg) is computed exactly once, across every cell this call returns,
    after every cell's own sufficiency gate has already been applied -- never per-symbol, never
    per-pair.
    """
    rules = _select_rules(rule_ids)
    regime_list: tuple[str, ...] = _ALL_REGIMES if regimes else ("all",)

    kwargs_list: list[dict[str, Any]] = []
    for symbol in symbols:
        for interval in intervals:
            bars = _bars_for_pair(symbol, interval, settings)
            if bars is None:
                continue
            pair_warnings = _pair_warnings(interval, bars)
            cache = IndicatorCache()
            regime_arrays = _regime_arrays(bars) if regimes else None

            for rule in rules:
                signal = _signal_for_rule(rule, bars, interval, cache)
                if signal is None:
                    continue
                for horizon in horizons:
                    for regime in regime_list:
                        raw = _raw_stats_for(
                            bars,
                            signal,
                            horizon=horizon,
                            regime=regime,
                            regime_arrays=regime_arrays,
                        )
                        kwargs_list.append(
                            _cell_kwargs_from_raw(
                                raw,
                                rule_id=rule.rule_id,
                                interval=interval,
                                scope="symbol",
                                scope_key=symbol,
                                horizon_bars=horizon,
                                regime=regime,
                                cost_bps=cost_bps,
                                warnings=pair_warnings,
                            )
                        )
    return _finalize(kwargs_list)


def aggregate(
    cells: Sequence[RuleAccuracyCell],
    *,
    to: Literal["sector", "universe"],
) -> list[RuleAccuracyCell]:
    """Pool several symbol-scope cells into one sector- or universe-scope cell per group.

    **Pools the underlying counts; never averages the per-symbol rates** -- averaging `hit_rate`
    across symbols with unequal sample sizes is the Simpson's-paradox trap that makes a rare rule
    look decisive (methodology doc §7b). Concretely: cells are grouped by
    `(rule_id, interval, horizon_bars, regime[, sector])`, and for each group this recomputes each
    member's raw per-episode/per-bar arithmetic from stored bars (see the note below on *why*),
    pools it with :func:`_pool_raw_stats` (sum the counts, concatenate the return arrays), gates
    *once* on the pooled `n_independent`, and only then derives `hit_rate`/`base_rate`/`lift`/CI/`p`
    from the pooled totals -- identical arithmetic to a single symbol cell, just fed a pooled sample.

    **Why this recomputes from bars rather than reading `hit_rate` back off the input `cells`.** The
    frozen `RuleAccuracyCell` schema nulls every statistic on a cell that fails its own individual
    sufficiency gate (`sufficient=False` implies `hit_rate is None`, enforced by the model's own
    validator) -- and the contract's own motivating case, `ema_golden_cross`, fails that per-symbol
    gate on *every* symbol (~10-12 episodes each, verified). If this function pooled only the
    non-null `hit_rate` values already sitting on the input cells, it would have zero contributors
    for exactly the rule the contract says must become measurable once pooled. Recomputing each
    member's raw counts and returns directly (via the same `_raw_stats_for` helper `compute_cells`
    uses) is the only way to reach the real, un-gated per-symbol numbers that pooling needs -- see
    report item (h) for this being flagged as an interface-contract gap rather than a design choice
    made for its own sake. `Settings` is not a parameter of this frozen signature, so
    `app.config.get_settings()` is used for the bar reads.

    Sector membership comes from `sector_of()`; a symbol absent from the research universe (and
    therefore from any declared sector) is silently excluded from a `to="sector"` aggregation rather
    than raising, since only `RESEARCH_UNIVERSE` members carry a sector label at all. BH is re-run
    over the aggregated grid returned by this call, independently of whatever `q_value`s the input
    per-symbol cells carried.
    """
    settings = get_settings()
    candidates = [c for c in cells if c.scope == "symbol"]

    # The sector slot is `None` in universe mode rather than absent. `to` is fixed for the whole
    # call, so every key built below already had the same arity; spelling the empty slot makes
    # that a type instead of an invariant a reader has to reconstruct, and groups identically.
    groups: dict[tuple[str, Interval, int, Regime, str | None], list[RuleAccuracyCell]] = {}
    # Declared rather than inferred: without this, `key`'s type comes from whichever branch below
    # assigns it first, and the other branch -- plus the `for key, ...` loop further down, which
    # reuses the name -- are then measured against that accident.
    key: tuple[str, Interval, int, Regime, str | None]
    for cell in candidates:
        if to == "sector":
            sector = sector_of(cell.scope_key)
            if sector is None:
                continue
            key = (cell.rule_id, cell.interval, cell.horizon_bars, cell.regime, sector)
        else:
            key = (cell.rule_id, cell.interval, cell.horizon_bars, cell.regime, None)
        groups.setdefault(key, []).append(cell)

    # Per-(symbol, interval) caches so a group spanning several horizons/regimes for the same rule
    # (or several rules sharing a pair) reads bars and builds the indicator cache only once each --
    # mirroring compute_cells' own "load once per pair" performance contract, even though this
    # function's frozen signature does not require it.
    bars_cache: dict[tuple[str, Interval], pd.DataFrame | None] = {}
    indicator_caches: dict[tuple[str, Interval], IndicatorCache] = {}
    regime_arrays_cache: dict[tuple[str, Interval], dict[str, np.ndarray]] = {}
    signal_cache: dict[tuple[str, Interval, str], pd.Series | None] = {}

    kwargs_list: list[dict[str, Any]] = []
    for key, group in groups.items():
        rule_id, interval, horizon_bars, regime = key[0], key[1], key[2], key[3]
        sector = key[4]
        rule = rule_catalog.get(rule_id)
        if rule is None:
            continue

        raws: list[_RawStats] = []
        member_warnings: list[str] = []
        for cell in group:
            symbol = cell.scope_key
            pair_key = (symbol, interval)
            if pair_key not in bars_cache:
                pair_bars = _bars_for_pair(symbol, interval, settings)
                bars_cache[pair_key] = pair_bars
                if pair_bars is not None:
                    indicator_caches[pair_key] = IndicatorCache()
                    if regime != "all":
                        regime_arrays_cache[pair_key] = _regime_arrays(pair_bars)
            pair_bars = bars_cache[pair_key]
            if pair_bars is None:
                continue

            signal_key = (symbol, interval, rule_id)
            if signal_key not in signal_cache:
                signal_cache[signal_key] = _signal_for_rule(
                    rule, pair_bars, interval, indicator_caches[pair_key]
                )
            signal = signal_cache[signal_key]
            if signal is None:
                continue

            raw = _raw_stats_for(
                pair_bars,
                signal,
                horizon=horizon_bars,
                regime=regime,
                regime_arrays=regime_arrays_cache.get(pair_key),
            )
            raws.append(raw)
            member_warnings.extend(cell.warnings)

        if not raws:
            continue

        pooled = _pool_raw_stats(raws)
        # `sector is None` is exactly `to != "sector"` by the key's construction above, and it
        # is the form that narrows: mypy cannot correlate two separate `to == "sector"` tests.
        scope_key = sector if sector is not None else "ALL"
        deduped_warnings = tuple(dict.fromkeys(member_warnings))
        kwargs_list.append(
            _cell_kwargs_from_raw(
                pooled,
                rule_id=rule_id,
                interval=interval,
                scope=to,
                scope_key=scope_key,
                horizon_bars=horizon_bars,
                regime=regime,
                cost_bps=group[0].cost_bps_assumed,
                warnings=deduped_warnings,
            )
        )

    return _finalize(kwargs_list)


def _frame_to_bar_list(bars: pd.DataFrame) -> list[Bar]:
    result: list[Bar] = []
    for row in bars.itertuples(index=False):
        adj_close = getattr(row, "adj_close", None)
        volume = getattr(row, "volume", None)
        result.append(
            Bar(
                ts=row.ts.to_pydatetime(),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                adj_close=None if adj_close is None or pd.isna(adj_close) else float(adj_close),
                volume=None if volume is None or pd.isna(volume) else int(volume),
                partial=False,
            )
        )
    return result


def _build_indicator_series(
    node: BoolExpr, bars: pd.DataFrame, interval: Interval
) -> list[IndicatorSeries]:
    """One `IndicatorSeries` per distinct indicator computation the rule's parsed tree references.

    Introspects the AST via `app.rules.evaluate.required_specs`, which walks the tree exactly once
    (deduplicated by `(name, args)`, in first-encountered order -- `bb_upper(20,2)` and
    `bb_lower(20,2)` share one spec string, `"bb:20,2"`, since they are one underlying computation
    with two output columns) rather than re-deriving indicator references locally, so this cannot
    drift from what `evaluate()` itself resolves.
    """
    series: list[IndicatorSeries] = []
    for spec_text in required_specs(node):
        request = indicator_registry.request(spec_text, interval=interval)
        computed = indicator_registry.compute(bars, [request])
        columns: dict[str, list[float | None]] = {}
        for column in request.columns:
            values = computed[column].to_numpy(dtype=float)
            columns[column] = [None if np.isnan(v) else float(v) for v in values]
        warmup = request.spec.warmup(request.params)
        series.append(
            IndicatorSeries(
                key=request.key,
                name=request.spec.name,
                title=request.spec.title,
                pane=request.spec.pane.value,
                columns=columns,
                warmup=warmup,
            )
        )
    return series


def signal_trace(
    *,
    symbol: str,
    interval: Interval,
    rule_id: str,
    settings: Settings,
) -> SignalTrace:
    """Everything the drill-down chart needs for one rule on one symbol at one interval.

    `fired_at` carries rising edges only, ascending -- the identical de-duplication `compute_cells`
    applies, so the markers a chart draws match the `n_episodes` the accuracy table reports for the
    same cell (see `RuleAccuracyCell`'s own docstring on this point).
    """
    rule = rule_catalog.get(rule_id)
    if rule is None:
        raise ValueError(f"unknown rule_id: {rule_id!r}")
    if rule.intervals and interval not in rule.intervals:
        raise ValueError(f"rule {rule_id!r} is not defined on interval {interval.value!r}")

    bars = read_frame(symbol, interval, settings=settings)
    if bars.empty:
        raise ValueError(f"no stored bars for {symbol} at interval {interval.value!r}")

    node = grammar.parse(rule.expression)
    cache = IndicatorCache()
    try:
        signal = evaluate(node, bars, interval=interval, indicator_cache=cache)
    except RuleEvaluationError as exc:
        raise ValueError(str(exc)) from exc

    edges = rising_edges(signal).to_numpy(dtype=bool)
    ts = bars["ts"]
    fired_at = [ts.iloc[int(i)].to_pydatetime() for i in np.flatnonzero(edges)]

    notna_positions = np.flatnonzero(signal.notna().to_numpy())
    warmup_until = (
        ts.iloc[int(notna_positions[0])].to_pydatetime() if notna_positions.size else None
    )

    indicators = _build_indicator_series(node, bars, interval)

    return SignalTrace(
        symbol=symbol,
        interval=interval,
        rule_id=rule_id,
        expression=rule.expression,
        bars=_frame_to_bar_list(bars),
        indicators=indicators,
        fired_at=fired_at,
        warmup_until=warmup_until,
    )

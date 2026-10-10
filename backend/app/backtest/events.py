"""Event study (confirmatory) and reverse conditioning (exploratory) over the backtest workbench.

**One forward-return implementation, reused.** Every hit rate, median and distribution here comes
from :mod:`app.backtest.forward` -- :func:`~app.backtest.forward.forward_returns`,
:func:`~app.backtest.forward.hit_rate`, :func:`~app.backtest.forward.describe` and
:func:`~app.backtest.forward.independent_count`/:func:`~app.backtest.forward.independent_mask`.
This module contributes no return arithmetic of its own; a second implementation that drifted from
that one is the exact failure the module split was meant to prevent (see that module's docstring).

**The baseline is the same evaluable bars as the trigger, per arm, per horizon.** Each
:class:`~app.backtest.models.ConditionArm` carries its own baseline, computed over exactly the bars
that *arm's* condition had a truth value on and that horizon's forward window could be measured
over -- never over the whole series unconditionally. Two arms with different indicator warmups
therefore have different baselines, which is correct: a condition that only starts producing a
truth value on bar 200 cannot be judged against bars 0-199 it never saw. See
:func:`app.rules.evidence.compute_evidence`, the Phase 6 sibling this mirrors exactly for a single
condition.

**``pd.NA`` is not ``False``.** A condition's warmup bars -- and any gap in its inputs -- are
dropped from both the trigger set and the baseline denominator, the same way
:mod:`app.rules.evidence` handles it. Folding an unknown truth value into "did not fire" would pad
the baseline with bars the condition was never asked about.

**``trigger_dates`` outlives ``sample_size``.** A condition firing eleven bars before the end of the
series has no complete forward window at horizon 20 -- it is excluded from every
:class:`~app.backtest.models.HorizonStats.sample_size` -- but it still happened, and
:attr:`~app.backtest.models.ConditionArm.trigger_dates` records every bar the condition was true on,
independent of horizon, so a chart overlay can still mark it.

**``ArmDelta`` compares samples, not just rates.** A narrower second arm can show a large hit-rate
gain purely because its remaining sample is tiny and lucky; :func:`event_study` always reports
:attr:`~app.backtest.models.ArmDelta.sample_size_delta` and
:attr:`~app.backtest.models.ArmDelta.independent_sample_size_delta` alongside the rate deltas so
that shrinkage cannot hide behind an improving number.

**Reverse conditioning describes the sample it was read off of.** :func:`reverse_conditioning`
selects the top tail of forward returns and profiles what indicators were doing beforehand -- a
fishing expedition by construction, and this module carries no p-value or hit rate for it, matching
:class:`~app.backtest.models.ReverseConditioning`. Two things keep the description honest instead of
flattering: :attr:`~app.backtest.models.IndicatorProfile.separation` is ``None``, not an infinite
number, when the unconditional sample has no spread to measure a shift against (a constant
indicator); and :attr:`~app.backtest.models.ReverseConditioning.independent_selected_count` reports
the non-overlapping count alongside the raw one, because a single explosive run produces many
consecutive top-decile bars that are one episode, not many.

**Collaborators are injectable**, matching :mod:`app.rules.service`: :class:`Grammar`,
:class:`Evaluator` and :class:`IndicatorRegistry` default to the real modules, imported lazily
inside :func:`_default_grammar`/:func:`_default_evaluator`/:func:`_default_registry` so this module
stays importable independent of when its collaborators are ready, and so callers -- including this
module's own tests -- can substitute fakes. Assembling the outer
:class:`~app.backtest.models.EventStudy`/:class:`~app.backtest.models.ReverseConditioning` objects,
and running the lookahead guard, is not this module's job: it returns the pieces those models need
beyond what the caller already knows (symbol, interval, ``generated_at``, ...).

**`event_study` accepts a caller-owned `IndicatorCache`, forwarded to every condition it evaluates.**
See :func:`event_study`'s docstring for the precondition (one cache, one bar frame) and
:func:`app.backtest.service.build_scan` for the caller that actually threads one through.
`reverse_conditioning` needs no equivalent: it never calls :class:`Evaluator` at all, and already
computes every indicator it profiles in one batched :meth:`IndicatorRegistry.compute` call rather
than once per expression -- there is no repeated computation here for an `IndicatorCache` to remove.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Protocol

import numpy as np
import pandas as pd

from app.backtest.forward import describe, forward_returns, hit_rate, independent_count
from app.backtest.models import (
    STUDY_HORIZONS,
    ArmDelta,
    ConditionArm,
    Distribution,
    HorizonStats,
    IndicatorProfile,
)
from app.db.duck import Interval
from app.indicators.base import IndicatorRequest
from app.rules.evaluate import IndicatorCache
from app.rules.models import Entry
from app.rules.nodes import BoolExpr

__all__ = ["Evaluator", "Grammar", "IndicatorRegistry", "event_study", "reverse_conditioning"]


# ---------------------------------------------------------------------------
# Injectable collaborators -- see the module docstring
# ---------------------------------------------------------------------------


class Grammar(Protocol):
    """The subset of `app.rules.grammar` this module calls."""

    def parse(self, expression: str) -> BoolExpr: ...


class Evaluator(Protocol):
    """The subset of `app.rules.evaluate` this module calls.

    `indicator_cache` is optional and keyword-only for the same reason `app.rules.service.Evaluator`
    makes it optional: an `Evaluator` written before this parameter existed must not be broken by a
    caller that passes it. `event_study` forwards whatever it was given (including `None`)
    unconditionally -- see `event_study`'s and `_build_arm`'s docstrings.
    """

    def evaluate(
        self,
        node: BoolExpr,
        bars: pd.DataFrame,
        *,
        interval: Interval,
        indicator_cache: IndicatorCache | None = None,
        macro: pd.DataFrame | None = None,
    ) -> pd.Series: ...


class IndicatorRegistry(Protocol):
    """The subset of `app.indicators.registry` this module calls."""

    def request(self, spec_text: str, *, interval: Interval | None = None) -> IndicatorRequest: ...

    def compute(
        self, bars: pd.DataFrame, requests: Sequence[IndicatorRequest]
    ) -> pd.DataFrame: ...


def _default_grammar() -> Grammar:
    from app.rules import grammar

    return grammar


def _default_evaluator() -> Evaluator:
    from app.rules import evaluate

    return evaluate


def _default_registry() -> IndicatorRegistry:
    from app.indicators import registry

    return registry


# ---------------------------------------------------------------------------
# Event study
# ---------------------------------------------------------------------------


def event_study(
    bars: pd.DataFrame,
    conditions: Sequence[str],
    *,
    interval: Interval,
    horizons: Sequence[int] = STUDY_HORIZONS,
    entry: Entry = Entry.NEXT_OPEN,
    grammar: Grammar | None = None,
    evaluator: Evaluator | None = None,
    indicator_cache: IndicatorCache | None = None,
) -> tuple[list[ConditionArm], list[ArmDelta]]:
    """Evaluate every condition in ``conditions`` against ``bars``, arm 0 as the base.

    Returns the arms (each with its own per-horizon stats, computed against its own baseline -- see
    the module docstring) and the deltas of every later arm against arm 0, flattened as
    ``(arm_index - 1) * len(horizons) + horizon_index`` to match
    :attr:`~app.backtest.models.EventStudy.deltas`. Empty when ``len(conditions) == 1``.

    ``conditions`` must be non-empty: arm 0 is the base every delta is measured against, so a study
    with none is not a study.

    ``indicator_cache`` is optional, keyword-only, and forwarded unchanged to every
    :meth:`Evaluator.evaluate` call this makes -- one per condition, all against this same ``bars``
    frame. That is exactly the precondition :class:`~app.rules.evaluate.IndicatorCache` requires
    (one cache, one bar frame): every condition in one ``event_study`` call is evaluated against the
    identical ``bars`` object, so two conditions that both reference ``rsi:14`` (or a caller's
    successive ``event_study`` calls sharing one cache across conditions, as
    :func:`app.backtest.service.build_scan` does across expressions) compute it once between them
    rather than once each. Passing ``None`` (the default) reproduces the uncached call every existing
    caller already makes.
    """
    if not conditions:
        raise ValueError("event_study requires at least one condition (arm 0 is the base)")

    grammar_mod = grammar or _default_grammar()
    evaluator_mod = evaluator or _default_evaluator()
    horizon_list = list(horizons)

    arms = [
        _build_arm(
            expression,
            bars,
            horizons=horizon_list,
            entry=entry,
            interval=interval,
            grammar=grammar_mod,
            evaluator=evaluator_mod,
            indicator_cache=indicator_cache,
        )
        for expression in conditions
    ]
    deltas = _build_deltas(arms, horizon_list)
    return arms, deltas


def _build_arm(
    expression: str,
    bars: pd.DataFrame,
    *,
    horizons: Sequence[int],
    entry: Entry,
    interval: Interval,
    grammar: Grammar,
    evaluator: Evaluator,
    indicator_cache: IndicatorCache | None = None,
) -> ConditionArm:
    node = grammar.parse(expression)
    # `None` for every rule that names no macro series -- see `app.rules.macro_binding.bind_for_bars`.
    from app.rules import macro_binding

    macro = macro_binding.bind_for_bars(node, bars)
    # Only forwarded when non-None, so a price-only rule's call is unchanged and an `Evaluator`
    # written against the older signature keeps working. See `app.backtest.strategy._fired`.
    extra = {"macro": macro} if macro is not None else {}
    signal = evaluator.evaluate(
        node, bars, interval=interval, indicator_cache=indicator_cache, **extra
    )

    # `pd.NA` is not `False` -- see the module docstring. `known_mask` is the truth-value-exists
    # mask; `true_mask` is only meaningful where `known_mask` holds, and every consumer below
    # intersects the two rather than trusting `true_mask` alone.
    known_mask = signal.notna().to_numpy(dtype=bool)
    true_mask = signal.fillna(False).to_numpy(dtype=bool)

    fired_positions = np.flatnonzero(known_mask & true_mask)
    dates = bars["ts"].dt.date
    trigger_dates = [dates.iloc[int(pos)] for pos in fired_positions]

    stats = [
        _horizon_stats(bars, known_mask, true_mask, horizon=horizon, entry=entry)
        for horizon in horizons
    ]

    return ConditionArm(
        label=expression,
        expression=expression,
        stats=stats,
        trigger_dates=trigger_dates,
        triggers=int(fired_positions.size),
        evaluable_bars=int(known_mask.sum()),
    )


def _horizon_stats(
    bars: pd.DataFrame,
    known_mask: np.ndarray,
    true_mask: np.ndarray,
    *,
    horizon: int,
    entry: Entry,
) -> HorizonStats:
    returns = forward_returns(bars, horizon=horizon, entry=entry)

    # The baseline denominator: evaluable bars whose forward window is also complete. Same
    # restriction applied to triggers and to the baseline, per the module docstring.
    evaluable = known_mask & ~np.isnan(returns)
    triggered = evaluable & true_mask

    baseline_sample = returns[evaluable]
    trigger_sample = returns[triggered]
    trigger_positions = np.flatnonzero(triggered)

    return HorizonStats(
        horizon=horizon,
        entry=entry,
        hit_rate=hit_rate(trigger_sample),
        baseline_hit_rate=hit_rate(baseline_sample),
        distribution=describe(trigger_sample),
        baseline_distribution=describe(baseline_sample),
        sample_size=int(trigger_positions.size),
        independent_sample_size=independent_count(trigger_positions, horizon),
        baseline_sample_size=int(baseline_sample.size),
    )


def _build_deltas(arms: list[ConditionArm], horizons: Sequence[int]) -> list[ArmDelta]:
    if len(arms) < 2:
        return []

    base_stats = arms[0].stats
    deltas: list[ArmDelta] = []
    for arm in arms[1:]:
        for base, stat in zip(base_stats, arm.stats, strict=True):
            hit_rate_delta = (
                None
                if stat.hit_rate is None or base.hit_rate is None
                else stat.hit_rate - base.hit_rate
            )
            median_delta = (
                None
                if stat.distribution.median is None or base.distribution.median is None
                else stat.distribution.median - base.distribution.median
            )
            deltas.append(
                ArmDelta(
                    horizon=stat.horizon,
                    hit_rate_delta=hit_rate_delta,
                    median_delta=median_delta,
                    sample_size_delta=stat.sample_size - base.sample_size,
                    independent_sample_size_delta=(
                        stat.independent_sample_size - base.independent_sample_size
                    ),
                )
            )
    return deltas


# ---------------------------------------------------------------------------
# Reverse conditioning
# ---------------------------------------------------------------------------


def reverse_conditioning(
    bars: pd.DataFrame,
    indicators: Sequence[str],
    *,
    interval: Interval,
    horizon: int,
    quantile: float = 0.9,
    lookback: int = 0,
    entry: Entry = Entry.NEXT_OPEN,
    registry: IndicatorRegistry | None = None,
) -> tuple[list[dt.date], int, int, list[IndicatorProfile]]:
    """Profile ``indicators`` in the ``lookback`` bars before the top ``(1 - quantile)`` tail of
    forward returns at ``horizon``.

    Returns ``(selected_dates, selected_count, independent_selected_count, profiles)`` -- the pieces
    :class:`~app.backtest.models.ReverseConditioning` needs beyond what the caller already knows.
    ``profiles`` is sorted by ``abs(separation)`` descending, unmeasurable (``None``) last. See the
    module docstring for why this carries no hit rate or p-value.
    """
    if not 0.0 <= quantile < 1.0:
        raise ValueError(f"quantile must be in [0, 1), got {quantile}")
    if lookback < 0:
        raise ValueError(f"lookback must be >= 0, got {lookback}")

    registry_mod = registry or _default_registry()

    returns = forward_returns(bars, horizon=horizon, entry=entry)
    valid = ~np.isnan(returns)
    selected_positions: np.ndarray
    if not valid.any():
        selected_positions = np.array([], dtype=np.int64)
    else:
        threshold = np.percentile(returns[valid], quantile * 100)
        selected_positions = np.flatnonzero(valid & (returns >= threshold))

    dates = bars["ts"].dt.date
    selected_dates = [dates.iloc[int(pos)] for pos in selected_positions]
    selected_count = int(selected_positions.size)
    independent_selected_count = independent_count(selected_positions, horizon)

    requests = [registry_mod.request(spec, interval=interval) for spec in indicators]
    indicator_frame = registry_mod.compute(bars, requests)

    profiles = [
        _profile_column(
            spec,
            column,
            indicator_frame[column].to_numpy(dtype="float64"),
            selected_positions,
            lookback,
        )
        for spec, req in zip(indicators, requests, strict=True)
        for column in req.columns
    ]
    profiles.sort(key=_profile_sort_key)

    return selected_dates, selected_count, independent_selected_count, profiles


def _profile_column(
    spec: str,
    column: str,
    values: np.ndarray,
    selected_positions: np.ndarray,
    lookback: int,
) -> IndicatorProfile:
    """One indicator column's :class:`~app.backtest.models.IndicatorProfile`.

    ``values`` is masked to finite entries before either distribution is built -- the same
    "callers pre-mask" contract :func:`~app.backtest.forward.describe` documents -- so an
    indicator's own warmup ``NaN``\\ s never enter either sample.
    """
    baseline_sample = values[np.isfinite(values)]

    selected_values: list[float] = []
    for pos in selected_positions:
        start = max(0, int(pos) - lookback)
        window = values[start : int(pos) + 1]
        selected_values.extend(window[np.isfinite(window)].tolist())
    selected_sample = np.asarray(selected_values, dtype="float64")

    selected_dist = describe(selected_sample)
    baseline_dist = describe(baseline_sample)

    return IndicatorProfile(
        spec=spec,
        column=column,
        selected=selected_dist,
        baseline=baseline_dist,
        separation=_separation(selected_dist, baseline_dist),
    )


def _separation(selected: Distribution, baseline: Distribution) -> float | None:
    """``(selected.median - baseline.median) / baseline_iqr``, ``None`` when either median is
    unmeasurable or the baseline has no spread to express a shift against -- see
    :attr:`~app.backtest.models.IndicatorProfile.separation`'s docstring.
    """
    if (
        selected.median is None
        or baseline.median is None
        or baseline.p25 is None
        or baseline.p75 is None
    ):
        return None
    iqr = baseline.p75 - baseline.p25
    if iqr == 0:
        return None
    return (selected.median - baseline.median) / iqr


def _profile_sort_key(profile: IndicatorProfile) -> tuple[bool, float]:
    if profile.separation is None:
        return (True, 0.0)
    return (False, -abs(profile.separation))

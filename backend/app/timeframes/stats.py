"""Statistical primitives for the multi-timeframe rule-accuracy study.

Each function here is independently testable against a known, hand-computable answer -- see
`tests/test_timeframes_service.py` -- and each is deliberately small: `service.py` composes these
into a `RuleAccuracyCell`, but the arithmetic that can be wrong lives here, not there.

**What is reused rather than reimplemented.** `app.backtest.forward.independent_count` /
`independent_mask` already perform the correct greedy non-overlap scan (interval scheduling on
equal-length windows) and are already tested and used by `app.rules.evidence`.
:func:`independent_count` below is a thin, documented delegation to that function -- not a rewrite
-- because two implementations of the same scan agreeing today is not a property anyone could
maintain; see that function's docstring for the reuse decision spelled out.

**What is new.** `app.rules.evidence` counts every *raw* triggered bar as one observation
(`Evidence.sample_size`); nothing in this codebase already deduplicates a persistent condition into
one observation per episode. :func:`rising_edges` is that new primitive. Likewise nothing existing
computes a confidence interval or a p-value for a *hit rate* (only `app.discovery.stats`'s
stationary bootstrap, built for a different overlap shape -- monthly rebalance decisions at an
annual horizon -- and not reused here; see :func:`lift_ci`'s docstring for why a normal-approximation
approach was chosen instead for this grid). :func:`wilson_interval`, :func:`lift_ci`,
:func:`two_proportion_p` and :func:`benjamini_hochberg` are all written fresh for this module.
"""

from __future__ import annotations

from collections.abc import Sequence
from statistics import NormalDist
from typing import Final

import numpy as np
import pandas as pd

from app.backtest.forward import independent_count as _forward_independent_count

__all__ = [
    "benjamini_hochberg",
    "independent_count",
    "lift_ci",
    "rising_edges",
    "two_proportion_p",
    "wilson_interval",
]

#: Standard normal distribution, used for both the inverse-CDF (`wilson_interval`'s z-score) and the
#: CDF (`two_proportion_p`'s two-sided tail). Python's stdlib `statistics.NormalDist` gives both
#: without pulling in scipy for two closed-form lookups.
_NORMAL: Final[NormalDist] = NormalDist()


def rising_edges(fired: pd.Series) -> pd.Series:
    """A boolean Series, `fired`'s index, `True` only at the first bar of each `True` run.

    A "fire" is the first `True` after a bar that was not `True` -- `fired[t] is True and
    (t == 0 or fired[t-1] is not True)`. 400 consecutive `True` bars under one persistent condition
    is one episode observed 400 times, not 400 independent opportunities to trade; see
    `app.rules.models.HORIZONS`'s own "opportunities to trade" framing, which this generalizes from
    "how many bars" to "how many times did the condition actually turn on".

    `pd.NA` is not `True` and therefore never marks an edge itself, but an `NA -> True` transition
    *is* one: unknown (indicator warmup, a data gap) is a different state from "the condition held
    and is still holding", so `.fillna(False)` is safe here specifically because what matters is only
    whether the *previous* bar was `True` -- an unknown previous bar is, by construction, "not True",
    which is exactly what should make a `True` bar following it count as a fresh edge.

    Handles an empty Series, an all-`False` (or all-`NA`) series (no edges), and an all-`True` series
    (exactly one edge, at position 0) uniformly -- no special-casing.
    """
    true_mask = fired.fillna(False).to_numpy(dtype=bool)
    if true_mask.size == 0:
        return pd.Series(true_mask, index=fired.index, dtype=bool)
    prev_true = np.empty_like(true_mask)
    prev_true[0] = False
    prev_true[1:] = true_mask[:-1]
    edges = true_mask & ~prev_true
    return pd.Series(edges, index=fired.index, dtype=bool)


def independent_count(positions: np.ndarray, horizon_bars: int) -> int:
    """Count of non-overlapping positions after a greedy interval-scheduling scan.

    **Reused, not reimplemented.** This delegates directly to
    `app.backtest.forward.independent_count`, which already runs the correct greedy-earliest scan
    (optimal for equal-length interval scheduling, already tested, already used to grade
    `Evidence.significance`). The only difference in how this module calls it: `service.py` passes
    *rising-edge episode positions* (see :func:`rising_edges`), never raw triggered-bar positions --
    two episodes three bars apart under a 20-bar horizon still share seventeen bars of the same
    forward path and must not both survive this scan, which is exactly what running it on the
    deduplicated episode positions (rather than every triggered bar) guarantees.
    """
    return _forward_independent_count(positions, horizon_bars)


def wilson_interval(hits: int, n: int, alpha: float = 0.05) -> tuple[float, float] | None:
    """Wilson score interval for a single proportion, `(1 - alpha)` confidence.

    Correct exactly where the textbook normal approximation (`phat +/- z*sqrt(phat(1-phat)/n)`)
    breaks down: a proportion near 0 or 1 -- which is common here, since an insufficient or
    barely-sufficient cell can easily show `hit_rate` at or near an extreme -- can produce a naive
    interval that overshoots `[0, 1]` or (at `phat` exactly 0 or 1) collapses to a single point that
    claims perfect certainty from a handful of observations. Wilson's interval inverts the normal
    approximation to the score test instead of the estimate itself, which keeps it inside `[0, 1]`
    and keeps it wide at small `n` even when `phat` is 0 or 1.

    `None` for `n <= 0` -- there is nothing to compute a proportion's uncertainty over.
    """
    if n <= 0:
        return None
    z = _NORMAL.inv_cdf(1 - alpha / 2)
    phat = hits / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (phat + z2 / (2 * n)) / denom
    margin = z * ((phat * (1 - phat) / n + z2 / (4 * n * n)) ** 0.5) / denom
    lo = max(0.0, center - margin)
    hi = min(1.0, center + margin)
    return (lo, hi)


def lift_ci(
    hits_rule: int,
    n_rule: int,
    hits_base: int,
    n_base_effective: int,
    *,
    alpha: float = 0.05,
) -> tuple[float, float] | None:
    """Confidence interval for `hit_rate - base_rate`, Newcombe's (1998) hybrid-score method.

    Built directly from two single-proportion Wilson intervals (see :func:`wilson_interval`) rather
    than a pooled-variance Wald approximation on the difference: if `(l1, u1)` is the Wilson interval
    for the rule's proportion and `(l2, u2)` for the baseline's, the interval for their difference is

        (p1 - p2) - sqrt((p1 - l1)^2 + (u2 - p2)^2)  ..  (p1 - p2) + sqrt((u1 - p1)^2 + (p2 - l2)^2)

    This stays well-behaved exactly where a naive difference-of-proportions formula breaks down (a
    proportion pinned near 0 or 1), because it inherits that good behaviour from `wilson_interval`
    rather than needing its own special-casing.

    **The independence caveat, stated plainly, because it is the honest limitation of this
    function.** Every derivation of a two-proportion confidence interval -- Newcombe's included --
    assumes the two proportions come from independent samples. Here they provably do not: the rule's
    fired bars are, by construction, a *subset* of the baseline's evaluable bars in the identical
    window (`base_rate` is computed over every evaluable bar, triggered or not). This function does
    not model that dependence -- it is a conservative approximation, not an exact solution, and two
    things push the approximation error in the direction of a *too-wide* rather than a too-narrow
    interval (the safer direction to be wrong in for a screening tool):

    1. Treating a nested subset and its superset as independent overstates the true variance of their
       difference relative to a nested design's actual (positively correlated) sampling covariance --
       independence is the pessimistic assumption here, not the optimistic one.
    2. `n_base_effective` -- not the raw evaluable-bar count -- is the caller's responsibility to
       supply already shrunk to account for serial correlation among overlapping forward-return
       windows in the baseline (`service.py`'s `n_base_effective = n_base_evaluable_bars //
       horizon_bars`, a conservative upper bound on how many truly non-overlapping horizon-length
       windows the baseline slice could contain). Passing the raw bar count instead would make the
       baseline side of this interval implausibly narrow, since adjacent evaluable bars share almost
       all of the same forward-return window.

    `hits_base` must already be expressed in the same `n_base_effective` units (i.e.
    `round(base_rate * n_base_effective)`), not the raw baseline hit count -- see `service.py`'s
    caller for exactly that conversion.

    `None` if either sample is empty.
    """
    if n_rule <= 0 or n_base_effective <= 0:
        return None
    p_rule = hits_rule / n_rule
    p_base = hits_base / n_base_effective
    wilson_rule = wilson_interval(hits_rule, n_rule, alpha)
    wilson_base = wilson_interval(hits_base, n_base_effective, alpha)
    if wilson_rule is None or wilson_base is None:
        return None
    l1, u1 = wilson_rule
    l2, u2 = wilson_base
    diff = p_rule - p_base
    lower = diff - ((p_rule - l1) ** 2 + (u2 - p_base) ** 2) ** 0.5
    upper = diff + ((u1 - p_rule) ** 2 + (p_base - l2) ** 2) ** 0.5
    return (max(-1.0, lower), min(1.0, upper))


def two_proportion_p(
    hits_rule: int,
    n_rule: int,
    hits_base: int,
    n_base_effective: int,
) -> float | None:
    """Two-sided p-value for `hit_rate` vs `base_rate`, pooled-proportion z-test.

    Takes the identical `(hits, n)` shape and the identical `n_base_effective` convention as
    :func:`lift_ci` -- see that function's docstring for the nested-sample independence caveat,
    which applies here without change: this is the same conservative approximation, not an exact
    test, and for the same reason.

    `None` if either sample is empty. `1.0` (not raising, not `None`) if both proportions are
    identical and the pooled variance is degenerate (both samples all-hit or all-miss) -- two equal
    extreme proportions are not "no data", they are "no detectable difference".
    """
    if n_rule <= 0 or n_base_effective <= 0:
        return None
    p_rule = hits_rule / n_rule
    p_base = hits_base / n_base_effective
    pooled = (hits_rule + hits_base) / (n_rule + n_base_effective)
    se = (pooled * (1 - pooled) * (1 / n_rule + 1 / n_base_effective)) ** 0.5
    if se == 0:
        return 1.0 if p_rule == p_base else 0.0
    z = (p_rule - p_base) / se
    return 2 * (1 - _NORMAL.cdf(abs(z)))


def benjamini_hochberg(p_values: Sequence[float | None], alpha: float) -> list[float | None]:
    """Benjamini-Hochberg q-values, same length and order as `p_values`.

    `None` entries (cells the sufficiency gate already rejected, which never had a p-value to begin
    with) pass through as `None` at their original position and are excluded from the family size
    `m` -- an insufficient cell was never a hypothesis test, so it must not dilute the correction
    applied to the ones that were.

    Ties share the correct q-value regardless of which order a stable sort happens to place them in:
    the standard step-up procedure (sort ascending, `q_(i) = min_{j >= i}(p_(j) * m / j)`, then take a
    running minimum from the largest rank down so q-values are monotone non-decreasing in p) gives
    every tied p-value the same final q-value by construction, since they occupy adjacent ranks and
    the running-minimum pass equalises across a tie's ranks either way.

    `alpha` does not change which q-value a p-value receives -- the BH q-value is alpha-independent
    by definition, it is only the threshold a *caller* later compares q against (the contract's
    `discovery = sufficient and q_value <= alpha`). It is accepted as a parameter here to keep this
    function's signature self-documenting about which family-wise rate the caller intends to defend,
    and so a future caller wanting an alpha-conditioned variant has a natural place to add it without
    changing every call site.
    """
    n = len(p_values)
    result: list[float | None] = [None] * n
    indexed = [(i, p) for i, p in enumerate(p_values) if p is not None]
    if not indexed:
        return result

    m = len(indexed)
    indexed.sort(key=lambda item: item[1])
    q_at_rank: list[float] = [0.0] * m
    running_min = 1.0
    for rank in range(m, 0, -1):
        _, p = indexed[rank - 1]
        candidate = p * m / rank
        running_min = min(running_min, candidate)
        q_at_rank[rank - 1] = min(1.0, running_min)

    # `strict=True` is free here -- `q_at_rank` is built as `[0.0] * m` from `m = len(indexed)`
    # a dozen lines up, so the two can only ever diverge if that construction changes.
    for (original_index, _), q in zip(indexed, q_at_rank, strict=True):
        result[original_index] = q
    return result

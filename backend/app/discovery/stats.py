"""Statistics for grading a selector, and specifically for getting more out of 23 years than one bit each.

**The problem this module exists to solve.** `strategy-program/DISCOVERY.md` §4 reported a 65.2% hit
rate over 23 annual trials at ``p = 0.210``, and observed that reaching ``p < 0.05`` at that hit rate
needs roughly 45 non-overlapping trials while only about 23 years of sector-ETF history exist. That
observation was correct about the *test* and wrong to leave standing as a fact about the data. A hit
rate reduces one decision date -- a full cross-section of twenty ranked candidates and twenty realized
returns -- to a single bit: did the top three beat the average. Twenty-three bits is not much evidence,
and it is nowhere near all the evidence that was collected.

**The information coefficient uses the whole cross-section.** At each date, correlate the scores the
selector assigned across *every* candidate against what those candidates went on to do
(:func:`information_coefficient`). A selector with no skill produces rho scattered around zero; one
with skill produces rho positive on average. Each date now contributes a continuous measurement built
from roughly twenty paired observations rather than one bit, and the aggregate is a t-test on the mean
(:func:`ic_summary`) rather than a binomial on a count. This is the standard construction in exactly
this setting, and it is not a way of making a weak result look strong: it can just as easily reveal
that the hit rate was carried by two lucky years, which is a thing the binomial cannot see at all.

**Overlapping horizons need a bootstrap, not a t-table.** Once decision dates are spaced monthly with
annual horizons -- the way to get more dates out of the same history -- consecutive observations share
eleven months of the same returns and are strongly serially dependent. A textbook t-statistic on such
a series has an effective sample size far below its nominal one and will report significance that is
not there. :func:`stationary_bootstrap_p` resamples in blocks of random geometric length (Politis and
Romano, 1994), which preserves that dependence structure inside each resample and therefore prices it
into the p-value instead of ignoring it. Deterministic given `seed`, so a published number can be
reproduced exactly.

**`spearman_rho` and `_rank` are ported from `strategy-program/tools/window_redundancy.py`, not
imported.** The same relationship `app.tournament.jobs` documents for its window matrix: the backend
does not import the offline research tooling, and `strategy-program` is not an importable package name
in any case. The two implementations must stay behaviourally identical; the tie convention below is
the load-bearing part and is tested directly.
"""

from __future__ import annotations

import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = [
    "ICSummary",
    "ic_summary",
    "information_coefficient",
    "spearman_rho",
    "stationary_bootstrap_p",
]


def _rank(values: Sequence[float]) -> list[float]:
    """1-indexed ascending ranks, ties sharing the average rank they span.

    ``[10, 20, 20, 30]`` ranks as ``[1, 2.5, 2.5, 4]``. This is the mid-rank convention Spearman's rho
    is defined against; assigning ranks in encounter order instead biases rho whenever a tie exists.
    Ties are not hypothetical here -- two candidates can post identical rounded scores, and a rank key
    that returns a constant for a flat series produces many.
    """
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    n = len(order)
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + 1 + j + 1) / 2
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def spearman_rho(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Spearman rank correlation of two equal-length paired series.

    Computed as Pearson on the rank-transformed series, which is exactly equivalent to the textbook
    formula once ties are present and simpler to get right than the ``1 - 6*sum(d^2)/(n(n^2-1))``
    shortcut, whose tie correction is a separate term that shortcut omits.

    `None` when either series has zero variance -- correlation is undefined there, not zero, and
    returning 0.0 would quietly average a non-measurement in with real ones.
    """
    n = len(xs)
    if n == 0 or len(ys) != n:
        raise ValueError(f"xs and ys must be the same nonzero length, got {len(xs)} and {len(ys)}")
    rx = _rank(xs)
    ry = _rank(ys)
    sx = statistics.pstdev(rx)
    sy = statistics.pstdev(ry)
    if sx == 0 or sy == 0:
        return None
    mean_x = statistics.fmean(rx)
    mean_y = statistics.fmean(ry)
    covariance = sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry, strict=True)) / n
    return covariance / (sx * sy)


#: Below this many paired candidates, one date's cross-section is refused rather than reported.
#:
#: With four candidates a single rank swap moves rho by roughly 0.4, which swamps any effect being
#: looked for -- `window_redundancy.py` refuses small-n Spearman for the same reason and says so at
#: length. Eight is the point at which one swap costs under 0.1.
MIN_CROSS_SECTION = 8


def information_coefficient(
    scores: Sequence[float], forward_returns: Sequence[float], *, minimum: int = MIN_CROSS_SECTION
) -> float | None:
    """Rank correlation between what the selector predicted and what happened, on one date.

    This is the per-date measurement the whole module is built around. `None` when the cross-section
    is smaller than `minimum` or has no variance -- an unmeasurable date, kept distinct from a date
    measured at zero, because averaging the two together is how a thin early window silently drags an
    aggregate toward the null.
    """
    if len(scores) != len(forward_returns):
        raise ValueError(
            f"scores and forward_returns must pair up, got {len(scores)} and {len(forward_returns)}"
        )
    if len(scores) < minimum:
        return None
    return spearman_rho(scores, forward_returns)


@dataclass(frozen=True, slots=True)
class ICSummary:
    """The aggregate of a series of per-date information coefficients."""

    n: int
    """Dates that produced a measurable IC. Not the number of decision dates -- see
    `information_coefficient`'s `None` case."""
    mean: float
    stdev: float
    t_stat: float
    """`mean / (stdev / sqrt(n))`. Honest only when the per-date ICs are close to independent, which
    means non-overlapping horizons. With overlapping horizons read `bootstrap_p` instead and treat
    this as descriptive."""
    hit_rate: float
    """Fraction of dates with IC > 0. A distribution-free sanity check on `mean`: a mean carried by
    two extreme dates shows up here as a hit rate near one half."""
    bootstrap_p: float | None = None
    """Two-sided p-value from :func:`stationary_bootstrap_p`, or `None` if not requested."""


def ic_summary(
    ics: Sequence[float | None], *, bootstrap: bool = False, block: float = 3.0, seed: int = 0
) -> ICSummary | None:
    """Aggregate per-date ICs. `None` if fewer than two dates were measurable.

    `bootstrap=True` prices in serial dependence between overlapping dates; leave it off for annual
    dates with annual horizons, where the t-statistic is already close to honest.
    """
    values = [ic for ic in ics if ic is not None]
    if len(values) < 2:
        return None
    mean = statistics.fmean(values)
    stdev = statistics.stdev(values)
    n = len(values)
    t_stat = 0.0 if stdev == 0 else mean / (stdev / (n**0.5))
    return ICSummary(
        n=n,
        mean=mean,
        stdev=stdev,
        t_stat=t_stat,
        hit_rate=sum(1 for v in values if v > 0) / n,
        bootstrap_p=stationary_bootstrap_p(values, block=block, seed=seed) if bootstrap else None,
    )


def stationary_bootstrap_p(
    series: Sequence[float], *, block: float = 3.0, seed: int = 0, draws: int = 10_000
) -> float | None:
    """Two-sided p-value for `mean(series) == 0` under serial dependence.

    **How it works, and why blocks.** An ordinary bootstrap resamples individual observations, which
    destroys the serial correlation that overlapping horizons create and therefore reports the same
    false confidence a t-test would. The stationary bootstrap (Politis and Romano, 1994) instead walks
    the series, continuing to the next observation with probability ``1 - 1/block`` and jumping to a
    fresh random position otherwise, so each resample is built from runs whose expected length is
    `block`. Dependence up to roughly that length survives into the resample and is priced into the
    spread of the resampled means.

    `block` should be about the number of consecutive observations that share data. Monthly decision
    dates with twelve-month horizons overlap eleven-twelfths, so a block near 12 is right there;
    annual dates with annual horizons barely overlap and 3 is ample.

    The null is imposed by centring: the sampling distribution of the mean is estimated from the data
    as-is, then compared against zero by asking how often a resampled mean deviates from the observed
    mean by at least as much as the observed mean deviates from zero. Returns `None` for a series too
    short to resample meaningfully.
    """
    values = list(series)
    n = len(values)
    if n < 3:
        return None
    observed = statistics.fmean(values)
    rng = random.Random(seed)
    jump = 1.0 / max(block, 1.0)

    extreme = 0
    for _ in range(draws):
        index = rng.randrange(n)
        total = 0.0
        for _ in range(n):
            total += values[index]
            index = rng.randrange(n) if rng.random() < jump else (index + 1) % n
        if abs(total / n - observed) >= abs(observed):
            extreme += 1
    return extreme / draws

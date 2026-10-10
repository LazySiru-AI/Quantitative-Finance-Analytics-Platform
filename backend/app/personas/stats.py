"""Confidence intervals for the persona feature's rates and means, so a reader never sees a bare
number over an unstated sample size.

Every hit-rate and mean this feature reports (`PersonaScorecard.hit_rate`, `HorizonStat.hit_rate`/
`mean_return_pct`, `BenchmarkedHorizon.excess_pct`, ...) is computed over a small, single-window
sample -- a persona with six scored calls and one with a hundred and ninety-two both produce a
`float`, and a bare `float` cannot tell those apart. `StatEstimate` (see `app.personas.models`) is the
wire shape that carries `n` alongside the point value and an interval; this module is the only place
that interval is computed, so every caller gets the same discipline rather than each reinventing it.

Two families, one for each shape of statistic this feature has:

- `wilson_interval` / `proportion` -- a proportion (a hit-rate: successes out of `n` directional calls).
- `bootstrap_mean` -- a mean (an average return, in percent, over `n` calls or horizon returns).

Neither ever raises on an empty or zero-`n` input. A caller here is almost always folding a scorecard
that legitimately has no directional calls yet, and an exception there would turn "no calls scored"
into a 500 instead of the honest `StatEstimate(n=0, ...)` the rest of the feature already renders for
that case (`PersonaScorecard.hit_rate is None`, etc.).

No I/O, no scipy dependency: `wilson_interval`'s z-score comes from `_norm_ppf`, a self-contained
rational approximation of the standard normal's inverse CDF (Acklam's algorithm, ~1.15e-9 absolute
error) -- scipy is not a repo dependency, and pulling it in for one closed-form constant would be a
heavier dependency than the four polynomials below.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from app.personas.models import StatEstimate

__all__ = ["bootstrap_mean", "proportion", "wilson_interval"]

# --- inverse standard normal CDF (Acklam's rational approximation) ---------

_A = (
    -3.969683028665376e01,
    2.209460984245205e02,
    -2.759285104469687e02,
    1.383577518672690e02,
    -3.066479806614716e01,
    2.506628277459239e00,
)
_B = (
    -5.447609879822406e01,
    1.615858368580409e02,
    -1.556989798598866e02,
    6.680131188771972e01,
    -1.328068155288572e01,
)
_C = (
    -7.784894002430293e-03,
    -3.223964580411365e-01,
    -2.400758277161838e00,
    -2.549732539343734e00,
    4.374664141464968e00,
    2.938163982698783e00,
)
_D = (
    7.784695709041462e-03,
    3.224671290700398e-01,
    2.445134137142996e00,
    3.754408661907416e00,
)

_P_LOW = 0.02425


def _norm_ppf(p: float) -> float:
    """The value `z` such that `Phi(z) == p`, for the standard normal `Phi`.

    `p` must be strictly inside `(0, 1)` -- callers here always pass `(1 + confidence) / 2` for a
    `confidence` in `(0, 1)`, which is strictly inside `(0.5, 1)`. Not exposed on the module's `__all__`:
    it exists only to give `wilson_interval` a z-score without a scipy dependency.
    """
    if p <= 0.0 or p >= 1.0:
        raise ValueError("_norm_ppf domain is the open interval (0, 1)")

    if p < _P_LOW:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / (
            (((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0
        )
    if p <= 1.0 - _P_LOW:
        q = p - 0.5
        r = q * q
        return (
            (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5])
            * q
            / (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1.0)
        )
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / (
        (((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0
    )


def wilson_interval(successes: int, n: int, *, confidence: float = 0.90) -> StatEstimate:
    """Wilson score interval for a proportion (`successes` out of `n`).

    Preferred over the naive `p_hat +/- z*se` (Wald) interval for exactly the sample sizes this
    feature actually has: Wald can produce bounds outside `[0, 1]` or a zero-width interval at
    `p_hat` in `{0, 1}`, both of which happen routinely at n<10. Wilson inverts the normal
    approximation to the binomial test instead of the point estimate's own standard error, which
    keeps it well-behaved at small `n` and exactly where this feature needs it most.

    `z = _norm_ppf((1 + confidence) / 2)` -- the two-sided z for `confidence` coverage (0.90 -> the
    5th/95th percentile z, ~1.645). Formula (with `p_hat = successes / n`):

        denom  = 1 + z**2 / n
        center = (p_hat + z**2 / (2*n)) / denom
        margin = (z / denom) * sqrt(p_hat*(1-p_hat)/n + z**2/(4*n**2))
        low, high = center - margin, center + margin   # then clamped to [0, 1]

    `n == 0` -> `StatEstimate(n=0, point=None, low=None, high=None, method="wilson")`: a rate over
    zero calls is undefined, not zero -- the same discipline `PersonaScorecard.hit_rate` already
    applies. Never raises on `successes == 0` or `successes == n`; both are ordinary proportions.
    """
    if n == 0:
        return StatEstimate(n=0, point=None, low=None, high=None, confidence=confidence, method="wilson")

    p_hat = successes / n
    z = _norm_ppf((1.0 + confidence) / 2.0)
    z2 = z * z

    denom = 1.0 + z2 / n
    center = (p_hat + z2 / (2.0 * n)) / denom
    margin = (z / denom) * math.sqrt(p_hat * (1.0 - p_hat) / n + z2 / (4.0 * n * n))

    low = max(0.0, center - margin)
    high = min(1.0, center + margin)

    return StatEstimate(n=n, point=p_hat, low=low, high=high, confidence=confidence, method="wilson")


def bootstrap_mean(
    samples: Sequence[float], *, confidence: float = 0.90, n_boot: int = 2000, seed: int = 0
) -> StatEstimate:
    """Percentile bootstrap confidence interval for the mean of `samples`.

    Resamples `samples` with replacement `n_boot` times (each resample the same size as `samples`),
    takes the mean of each resample, and reports the `(1-confidence)/2` and `(1+confidence)/2`
    percentiles of that distribution as `low`/`high` (0.90 -> the 5th/95th percentiles). Chosen over a
    closed-form (t-interval) CI because the return distributions this module feeds off of (per-call
    percent returns) are not assumed normal or even symmetric, and the bootstrap makes no such
    assumption.

    Deterministic by construction: the resampling draws come from `np.random.default_rng(seed)`,
    never the module-global RNG state, so two calls with the same `samples`/`seed` always produce
    bit-identical `low`/`high` -- required because this estimate is rendered on a card, and a card
    that changed its own confidence interval on every reload would be worse than none at all.

    `samples` empty -> `StatEstimate(n=0, point=None, low=None, high=None, method="bootstrap")`, the
    same undefined-not-zero discipline as `wilson_interval`. A single sample -> `point == low == high
    == that value`: with one element every resample is that same element repeated, so the bootstrap
    distribution is a point mass and the degenerate interval is the mathematically correct answer,
    not a special case papered over -- returned directly rather than run through the RNG so the result
    is exact rather than merely converged.
    """
    n = len(samples)
    if n == 0:
        return StatEstimate(
            n=0, point=None, low=None, high=None, confidence=confidence, method="bootstrap"
        )

    arr = np.asarray(samples, dtype=float)
    point = float(arr.mean())

    if n == 1:
        return StatEstimate(
            n=1, point=point, low=point, high=point, confidence=confidence, method="bootstrap"
        )

    rng = np.random.default_rng(seed)
    resample_idx = rng.integers(0, n, size=(n_boot, n))
    boot_means = arr[resample_idx].mean(axis=1)

    lower_pct = (1.0 - confidence) / 2.0 * 100.0
    upper_pct = (1.0 + confidence) / 2.0 * 100.0
    low, high = np.percentile(boot_means, [lower_pct, upper_pct])

    return StatEstimate(
        n=n, point=point, low=float(low), high=float(high), confidence=confidence, method="bootstrap"
    )


def proportion(successes: int, n: int, *, confidence: float = 0.90) -> StatEstimate:
    """Thin alias to `wilson_interval`, so a caller scoring a hit-rate reads `proportion(hits, n)`
    rather than reaching for a name that describes the method rather than the thing being measured."""
    return wilson_interval(successes, n, confidence=confidence)

"""Tests for `app.personas.stats` -- the confidence-interval helpers behind every `StatEstimate` this
feature reports. See that module's docstring for the discipline under test: `n == 0` never raises and
never fabricates a point value, and `bootstrap_mean` must be exactly reproducible for a given seed."""

from __future__ import annotations

import pytest

from app.personas.stats import bootstrap_mean, proportion, wilson_interval

# ---------------------------------------------------------------------------
# wilson_interval / proportion
# ---------------------------------------------------------------------------


def test_wilson_8_of_10_at_90_percent() -> None:
    est = wilson_interval(8, 10, confidence=0.90)

    assert est.n == 10
    assert est.method == "wilson"
    assert est.confidence == pytest.approx(0.90)
    assert est.point == pytest.approx(0.8)
    assert est.low is not None
    assert est.high is not None
    assert 0.45 < est.low < 0.98
    assert 0.45 < est.high < 0.98
    assert est.low < est.point < est.high


def test_wilson_zero_n_is_all_none() -> None:
    est = wilson_interval(0, 0, confidence=0.90)

    assert est.n == 0
    assert est.point is None
    assert est.low is None
    assert est.high is None
    assert est.method == "wilson"


def test_wilson_bounds_are_clamped_to_unit_interval() -> None:
    # p_hat == 1.0 (all successes) at small n pushes the naive interval above 1 -- must be clamped.
    est = wilson_interval(5, 5, confidence=0.90)
    assert est.low is not None and est.high is not None
    assert 0.0 <= est.low <= 1.0
    assert 0.0 <= est.high <= 1.0

    # p_hat == 0.0 (all failures) pushes the naive interval below 0 -- must be clamped.
    est_zero = wilson_interval(0, 5, confidence=0.90)
    assert est_zero.low is not None and est_zero.high is not None
    assert 0.0 <= est_zero.low <= 1.0
    assert 0.0 <= est_zero.high <= 1.0
    assert est_zero.point == pytest.approx(0.0)


def test_wilson_n_reported_correctly() -> None:
    est = wilson_interval(3, 192, confidence=0.90)
    assert est.n == 192
    assert est.point == pytest.approx(3 / 192)


def test_proportion_is_an_alias_for_wilson_interval() -> None:
    a = wilson_interval(8, 10, confidence=0.90)
    b = proportion(8, 10, confidence=0.90)
    assert a.n == b.n
    assert a.point == pytest.approx(b.point)
    assert a.low == pytest.approx(b.low)
    assert a.high == pytest.approx(b.high)
    assert a.method == b.method == "wilson"


# ---------------------------------------------------------------------------
# bootstrap_mean
# ---------------------------------------------------------------------------


def test_bootstrap_mean_empty_is_all_none() -> None:
    est = bootstrap_mean([], confidence=0.90)

    assert est.n == 0
    assert est.point is None
    assert est.low is None
    assert est.high is None
    assert est.method == "bootstrap"


def test_bootstrap_mean_single_sample_is_degenerate() -> None:
    est = bootstrap_mean([4.5], confidence=0.90)

    assert est.n == 1
    assert est.point == pytest.approx(4.5)
    assert est.low == pytest.approx(4.5)
    assert est.high == pytest.approx(4.5)
    assert est.method == "bootstrap"


def test_bootstrap_mean_constant_list_has_zero_width_interval() -> None:
    est = bootstrap_mean([3.0, 3.0, 3.0, 3.0], confidence=0.90, seed=0)

    assert est.point == pytest.approx(3.0)
    assert est.low == pytest.approx(3.0)
    assert est.high == pytest.approx(3.0)


def test_bootstrap_mean_ci_contains_sample_mean() -> None:
    samples = [1.0, 2.0, -3.0, 4.5, 0.5, -1.0, 6.0, 2.5]
    est = bootstrap_mean(samples, confidence=0.90, seed=0)

    assert est.n == len(samples)
    sample_mean = sum(samples) / len(samples)
    assert est.point == pytest.approx(sample_mean)
    assert est.low is not None and est.high is not None
    assert est.low <= est.point <= est.high


def test_bootstrap_mean_is_reproducible_for_same_seed() -> None:
    samples = [1.0, -2.0, 3.5, 0.0, 7.0, -4.0, 2.2]

    a = bootstrap_mean(samples, confidence=0.90, seed=42)
    b = bootstrap_mean(samples, confidence=0.90, seed=42)

    assert a.low == b.low
    assert a.high == b.high
    assert a.point == b.point


def test_bootstrap_mean_different_seeds_can_differ() -> None:
    samples = [1.0, -2.0, 3.5, 0.0, 7.0, -4.0, 2.2, 5.0, -1.5]

    a = bootstrap_mean(samples, confidence=0.90, seed=0)
    b = bootstrap_mean(samples, confidence=0.90, seed=1)

    # Same point estimate (deterministic mean), but the CI bounds are allowed to differ by seed --
    # this is a sanity check that seed actually drives the resampling, not a hard guarantee.
    assert a.point == pytest.approx(b.point)


def test_bootstrap_mean_n_reported_correctly() -> None:
    samples = [1.0] * 50
    est = bootstrap_mean(samples, confidence=0.90, seed=0)
    assert est.n == 50


def test_norm_ppf_known_z_values() -> None:
    """Regression for the collapsed-CI bug: the central-branch inverse-normal must return the real
    z-scores, not a near-zero value. A wrong polynomial here silently degenerates every Wilson
    interval to zero width (the loose 'inside a wide range' assertions did not catch that)."""
    from app.personas.stats import _norm_ppf

    assert _norm_ppf(0.95) == pytest.approx(1.6448536, abs=1e-4)
    assert _norm_ppf(0.975) == pytest.approx(1.9599640, abs=1e-4)
    assert _norm_ppf(0.5) == pytest.approx(0.0, abs=1e-9)


def test_wilson_widths_are_substantial_and_shrink_with_n() -> None:
    """A Wilson 90% interval must have real width and get WIDER as n shrinks -- the whole reason the CI
    exists. Asserts magnitudes, not just membership in a wide band."""
    from app.personas.stats import wilson_interval

    big = wilson_interval(46, 123)
    small = wilson_interval(2, 6)
    assert big.low == pytest.approx(0.306, abs=0.02)
    assert big.high == pytest.approx(0.448, abs=0.02)
    assert (big.high - big.low) > 0.10
    assert (small.high - small.low) > (big.high - big.low)  # smaller n -> wider

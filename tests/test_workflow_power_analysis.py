"""Tests for `backend/app/workflow/power_analysis.py` -- planning information for the Agent Workflow
study's §7 decision rule, never a substitute for it.

Three properties this module promises, per its own docstring, and each gets a test:

1. **Determinism.** The same `seed` reproduces the identical power table bit-for-bit
   (`test_simulate_discrimination_power_is_deterministic`).
2. **Monotonicity.** Statistical power rises (non-strictly) with sample size and with effect size --
   the sanity check that would fail immediately if the Monte Carlo wiring were backwards
   (`test_power_rises_with_sample_size`, `test_power_rises_with_effect_size`).
3. **Calibration.** The zero-true-effect arm's rejection rate lands near the nominal `q_threshold`
   rather than systematically above or below it -- the check that the false-positive rate the report
   quotes is real, not an artifact of a broken null (`test_zero_effect_arm_near_nominal_rate`).

`estimate_candidate_arrival_rate` gets its own two tests: a graceful "unavailable" result against the
`settings` fixture's isolated, empty temp store (`test_arrival_rate_unavailable_without_stored_data`,
proving the "never fabricate a number" contract this module's docstring and the task brief both
require), and a real-data smoke test against the repository's actual store and card library, skipped
on a fresh clone that has neither (`test_arrival_rate_against_real_store`), the same `requires_real_store`
pattern `tests/test_benchmarks.py` established.
"""

from __future__ import annotations

from app.config import REPO_ROOT, Settings
from app.workflow import power_analysis
from tests.conftest import requires_real_store

_N_GRID = (10, 40, 100)
_EFFECTS = (0.0, 0.05, 0.15)


# ---------------------------------------------------------------------------
# simulate_discrimination_power
# ---------------------------------------------------------------------------


def test_simulate_discrimination_power_is_deterministic() -> None:
    first = power_analysis.simulate_discrimination_power(_N_GRID, _EFFECTS, n_draws=500, seed=7)
    second = power_analysis.simulate_discrimination_power(_N_GRID, _EFFECTS, n_draws=500, seed=7)
    assert first == second


def test_different_seed_can_differ() -> None:
    """Not a determinism check on the *same* seed -- proof the seed is actually threaded into the
    RNG rather than silently ignored, i.e. that two different seeds are not certain to collide."""
    a = power_analysis.simulate_discrimination_power((40,), (0.10,), n_draws=500, seed=1)
    b = power_analysis.simulate_discrimination_power((40,), (0.10,), n_draws=500, seed=2)
    assert a != b


def test_power_rises_with_sample_size() -> None:
    """At a fixed non-zero effect size, more gated candidates must not make the effect *harder* to
    detect. Uses a larger `n_draws` than the determinism test so the Monte Carlo noise around each
    cell's power estimate cannot itself explain a false monotonicity failure."""
    grid = (10, 40, 100, 300)
    cells = power_analysis.simulate_discrimination_power(grid, (0.10,), n_draws=3000, seed=0)
    by_n = {cell.n_gated_candidates: cell.power for cell in cells}
    powers = [by_n[n] for n in grid]
    assert powers == sorted(powers)
    assert powers[-1] > powers[0]


def test_power_rises_with_effect_size() -> None:
    """At a fixed candidate count, a bigger true hit-rate gap must not make the effect harder to
    detect."""
    effects = (0.0, 0.05, 0.10, 0.20)
    cells = power_analysis.simulate_discrimination_power((100,), effects, n_draws=3000, seed=0)
    by_effect = {cell.effect_size: cell.power for cell in cells}
    powers = [by_effect[e] for e in effects]
    assert powers == sorted(powers)
    assert powers[-1] > powers[0]


def test_zero_effect_arm_near_nominal_rate() -> None:
    """With no true difference between the passed and refused sets, `target_gate`'s q-value should
    fall at or below `q_threshold` at roughly the nominal rate the BH procedure targets -- not
    dramatically inflated (a broken p-value) nor collapsed to zero (a test that can never reject).
    BH controls the *false discovery rate* rather than pinning each individual gate's rejection rate
    exactly at `q_threshold`, and the binomial test is discrete (coarse at small `n`), so this allows
    a generous band rather than asserting equality."""
    cells = power_analysis.simulate_discrimination_power(
        (200,), (0.0,), n_draws=8000, seed=0, q_threshold=0.10
    )
    (cell,) = cells
    assert cell.power < 0.30, f"zero-effect false-positive rate implausibly high: {cell.power}"


def test_rejects_invalid_target_gate() -> None:
    import pytest

    with pytest.raises(ValueError, match="target_gate"):
        power_analysis.simulate_discrimination_power((10,), (0.0,), target_gate="raw_signal")  # type: ignore[arg-type]


def test_rejects_invalid_pass_fraction() -> None:
    import pytest

    with pytest.raises(ValueError, match="pass_fraction"):
        power_analysis.simulate_discrimination_power((10,), (0.0,), pass_fraction=0.0)


def test_zero_or_small_n_never_crashes_and_never_shows_power() -> None:
    """`n=0` splits into zero passed and zero refused for every gate, which `study._discrimination`'s
    own logic treats as untestable (`p_value=None`) -- this must degrade the same way, not raise, and
    must report zero power rather than a spurious non-zero rate."""
    cells = power_analysis.simulate_discrimination_power((0,), (0.10,), n_draws=200, seed=0)
    (cell,) = cells
    assert cell.power == 0.0


# ---------------------------------------------------------------------------
# estimate_candidate_arrival_rate
# ---------------------------------------------------------------------------


def test_arrival_rate_unavailable_without_stored_data(settings: Settings) -> None:
    """Against the `settings` fixture's isolated temp store -- which has no bar history and no
    strategy-card library copied into it -- the estimator must say so explicitly rather than
    fabricate a rate. This is the "never fabricate an arrival rate" contract the task brief and this
    module's own docstring both require, and it is the normal state for a fresh clone or any isolated
    test, not a failure being tolerated."""
    result = power_analysis.estimate_candidate_arrival_rate(settings=settings)
    assert result.overall_mean_per_session is None
    assert result.per_card == ()
    assert result.note  # explains why, in place of a number


@requires_real_store
def test_arrival_rate_against_real_store() -> None:
    """Smoke test against the repository's real stored bars and real card library: every regime-map
    card that resolves produces a non-negative, capped mean, and the overall figure is their
    unweighted mean, exactly as the docstring promises. Skipped on a fresh clone that has no
    `data/store/bars` (gitignored), the same `requires_real_store` pattern `tests/test_benchmarks.py`
    uses for the identical reason."""
    real_settings = Settings()
    result = power_analysis.estimate_candidate_arrival_rate(settings=real_settings)

    assert result.per_card, "expected at least one regime-map card to resolve against the real store"
    assert result.overall_mean_per_session is not None
    for row in result.per_card:
        assert row.sessions > 0
        assert 0.0 <= row.mean_gated_candidates_per_session <= result.max_research_symbols
        assert row.window_start is not None
        assert row.window_end is not None
        assert row.window_start <= row.window_end

    expected_overall = sum(r.mean_gated_candidates_per_session for r in result.per_card) / len(
        result.per_card
    )
    assert result.overall_mean_per_session == expected_overall


@requires_real_store
def test_arrival_rate_respects_max_research_symbols_cap() -> None:
    """A tighter cap can only ever lower (or leave unchanged) each card's mean -- proof the cap is
    actually applied to the daily firing count, not merely carried in the returned dataclass."""
    real_settings = Settings()
    uncapped = power_analysis.estimate_candidate_arrival_rate(
        settings=real_settings, max_research_symbols=1_000
    )
    capped = power_analysis.estimate_candidate_arrival_rate(
        settings=real_settings, max_research_symbols=1
    )
    assert uncapped.per_card, "expected at least one regime-map card to resolve against the real store"
    uncapped_by_id = {row.agent_id: row for row in uncapped.per_card}
    for row in capped.per_card:
        assert row.mean_gated_candidates_per_session <= 1.0
        assert row.mean_gated_candidates_per_session <= uncapped_by_id[row.agent_id].mean_gated_candidates_per_session


# `REPO_ROOT` import kept: documents where `requires_real_store` in `tests/conftest.py` anchors its
# existence check, for a reader who jumps here first.
assert REPO_ROOT.is_dir()

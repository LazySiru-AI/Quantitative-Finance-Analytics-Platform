"""Tests for :mod:`app.backtest.scan`.

Styled like :mod:`tests.test_rule_evidence`: fixtures are built by hand rather than by running the
still-in-flight :mod:`app.backtest.events`, and every :class:`~app.backtest.models.HorizonStats` used
here is fabricated directly so the numbers behind each assertion are visible in the test itself.

Where a number is checked against an external, independently-verified source (the five hand-checked
binomial values, and the Benjamini-Hochberg 1995 paper's own worked example), the assertion is an
exact literal rather than a tolerance -- a wrong constant should fail loudly. The noise-simulation
tests (1-3) are necessarily seeded-random with a documented bound rather than an exact count; each
states what "near zero" and "materially higher" mean and why the bound is generous rather than tuned
to just barely pass.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Callable

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from app.backtest.models import GuardReport, GuardStatus, HorizonStats, ScanEntry, ScanResult
from app.backtest.scan import benjamini_hochberg, binomial_p_value, scan
from app.db.duck import Interval
from app.indicators import registry as indicator_registry
from app.rules.evaluate import IndicatorCache
from app.rules.evaluate import evaluate as rules_evaluate
from app.rules.models import Entry
from app.rules.nodes import CompareOp, Comparison, IndicatorRef, Literal

_EvalTable = dict[str, tuple[GuardReport, HorizonStats | None]]

PASSED = GuardReport(status=GuardStatus.PASSED, expression="x")
FAILED = GuardReport(status=GuardStatus.FAILED, expression="x")

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _stats(
    *,
    hit_rate: float | None,
    baseline_hit_rate: float | None,
    independent_sample_size: int,
    sample_size: int | None = None,
    horizon: int = 5,
) -> HorizonStats:
    """A minimal, hand-built `HorizonStats` -- no real evaluation, just the fields
    `scan()`'s p-value computation reads: `hit_rate`, `baseline_hit_rate`, `independent_sample_size`.
    `sample_size` defaults to a larger, overlapping-window count so tests that don't care about it
    still look like a plausible real result (independent count never exceeds the raw count)."""
    return HorizonStats(
        horizon=horizon,
        entry=Entry.NEXT_OPEN,
        hit_rate=hit_rate,
        baseline_hit_rate=baseline_hit_rate,
        sample_size=sample_size if sample_size is not None else independent_sample_size * 3,
        independent_sample_size=independent_sample_size,
        baseline_sample_size=independent_sample_size * 3,
    )


def _make_evaluator(
    table: _EvalTable,
) -> Callable[[str, int], tuple[GuardReport, HorizonStats | None]]:
    """Builds an `Evaluate` callable from a `{expression: (guard, stats)}` table, ignoring
    `horizon` (every test here uses a single horizon per expression)."""

    def _evaluate(expression: str, horizon: int) -> tuple[GuardReport, HorizonStats | None]:
        return table[expression]

    return _evaluate


# ---------------------------------------------------------------------------
# 0. Old math.comb-based implementation vs the new log-space implementation
# ---------------------------------------------------------------------------


def _old_binomial_p_value(successes: int, trials: int, p_null: float) -> float:
    """The pre-fix implementation of `binomial_p_value`, reproduced here as an oracle -- it is not
    imported from production because it no longer exists there. Only safe for `(successes, trials,
    p_null)` small enough that `math.comb(trials, successes)` fits in a float once multiplied by
    `p_null**successes`; that ceiling is exactly the bug this module was fixed for, so this helper
    must not be "improved" to also handle the overflow case -- its entire value here is being the
    unmodified old arithmetic to diff the new implementation against."""
    if trials == 0:
        return 1.0
    if p_null == 0.0:
        return 0.0 if successes > 0 else 1.0
    if p_null == 1.0:
        return 0.0 if successes < trials else 1.0

    def pmf(k: int) -> float:
        return math.comb(trials, k) * (p_null**k) * ((1.0 - p_null) ** (trials - k))

    observed = pmf(successes)
    threshold = observed * (1.0 + 1e-7)
    total = sum(pmf(k) for k in range(trials + 1) if pmf(k) <= threshold)
    return min(total, 1.0)


class TestBinomialPValueAgreesWithOldImplementation:
    """The new log-space implementation (`math.lgamma`) must reproduce the old `math.comb`-based one
    to tight float tolerance everywhere the old one did not overflow -- a spread of small and medium
    `(successes, trials, p_null)`, including asymmetric `p_null`, `successes` below and above the
    mean, `successes` exactly at the mode, and the degenerate `p_null in {0.0, 1.0}` and `trials ==
    0` cases. This matters more than the overflow fix itself: a rewrite that silently shifted
    p-values would be far worse than the crash it replaces, because nothing would visibly break.
    """

    @pytest.mark.parametrize(
        ("successes", "trials", "p_null"),
        [
            # Hand-verified table values (n=10 or less), re-checked against the old arithmetic too.
            (9, 10, 0.5),
            (10, 10, 0.5),
            (5, 10, 0.5),
            (3, 10, 0.5),
            (0, 5, 0.5),
            (7, 10, 0.7),  # k == n*p exactly: the observed outcome is the mode.
            # Degenerate p_null and trials.
            (0, 0, 0.5),
            (0, 10, 0.0),
            (1, 10, 0.0),
            (10, 10, 1.0),
            (9, 10, 1.0),
            # Asymmetric p_null, successes below and above n*p_null (=20).
            (30, 100, 0.2),
            (10, 100, 0.2),
            (20, 100, 0.2),
            # Medium n, symmetric p_null, both sides of the mean.
            (400, 1000, 0.5),
            (600, 1000, 0.5),
            (500, 1000, 0.5),
            # Small n, near the boundary.
            (1, 50, 0.5),
            (49, 50, 0.5),
            (25, 50, 0.5),
            (0, 1, 0.5),
            (1, 1, 0.5),
            # No n=3000 case belongs here, and the reason is worth recording because it is an easy
            # mistake to repeat: it is tempting to argue that a small `k` is safe because
            # `C(3000, 10)` is nowhere near `C(3000, 1500)`. That is true of the *observed* term and
            # irrelevant, because the two-sided sum walks every `k` in `0..trials` and therefore
            # evaluates `C(3000, 1500)` regardless of where `successes` sits. The old implementation
            # cannot evaluate *any* n=3000 case, so there is no old value for a new one to agree
            # with. Large-`n` behaviour is pinned by `TestBinomialPValueAtLargeN` instead.
        ],
    )
    def test_matches_old_math_comb_implementation(
        self, successes: int, trials: int, p_null: float
    ) -> None:
        old = _old_binomial_p_value(successes, trials, p_null)
        new = binomial_p_value(successes, trials, p_null)
        assert new == pytest.approx(old, abs=1e-9)


class TestBinomialPValueAtLargeN:
    """The sample sizes that used to crash.

    `math.comb(3000, 1500)` has over 900 digits and raises `OverflowError` on conversion to float,
    and the two-sided sum evaluates it for *every* input at that `trials`, whatever `successes` is.
    These are not synthetic sizes: `close > sma(200)` at horizon 1 over ~6,300 sessions of daily
    history produces independent-sample counts in exactly this range, so before the log-space
    rewrite an ordinary catalogue rule on an ordinary ticker took the whole scan down with it.
    """

    @pytest.mark.parametrize(
        ("successes", "trials", "p_null"),
        [
            (1560, 3000, 0.5),
            (2340, 4500, 0.55),
            (3200, 6000, 0.53),
            (3000, 6000, 0.5),  # exactly at the mean: the least extreme outcome there is.
            (0, 3000, 0.5),  # both endpoints, where the coefficient term is 1 but p**k underflows.
            (3000, 3000, 0.5),
        ],
    )
    def test_returns_a_finite_probability_instead_of_raising(
        self, successes: int, trials: int, p_null: float
    ) -> None:
        value = binomial_p_value(successes, trials, p_null)
        assert math.isfinite(value)
        assert 0.0 <= value <= 1.0

    def test_the_mean_outcome_is_the_least_surprising_one(self) -> None:
        """A sanity check the old implementation could never run at this size: the outcome at the
        mean must carry the largest possible p-value, and a wildly extreme one must be tiny."""
        at_mean = binomial_p_value(3000, 6000, 0.5)
        far_out = binomial_p_value(3600, 6000, 0.5)
        assert at_mean == pytest.approx(1.0, abs=1e-9)
        assert far_out < 1e-30

    def test_p_value_does_not_increase_as_the_outcome_moves_from_the_mean(self) -> None:
        """Monotonicity. Walking `successes` away from `n * p_null` may only make the result less
        likely, never more -- a rewrite that broke the tail-selection logic would show up here even
        if every individual pmf term were still correct."""
        trials, p_null = 4000, 0.5
        values = [binomial_p_value(k, trials, p_null) for k in range(2000, 2401, 50)]
        assert values == sorted(values, reverse=True), values


# ---------------------------------------------------------------------------
# 1. Exact binomial p-value -- hand-verified literals
# ---------------------------------------------------------------------------


class TestBinomialPValue:
    @pytest.mark.parametrize(
        ("successes", "trials", "p_null", "expected"),
        [
            (9, 10, 0.5, 0.021484375),
            (10, 10, 0.5, 0.001953125),
            (5, 10, 0.5, 1.0),
            (3, 10, 0.5, 0.34375),
            (0, 5, 0.5, 0.0625),
            (7, 10, 0.7, 1.0),  # k == n*p exactly: the observed outcome is the mode.
        ],
    )
    def test_hand_verified_values(
        self, successes: int, trials: int, p_null: float, expected: float
    ) -> None:
        assert binomial_p_value(successes, trials, p_null) == pytest.approx(expected, abs=1e-12)

    def test_zero_trials_is_certain(self) -> None:
        assert binomial_p_value(0, 0, 0.5) == 1.0

    def test_p_null_zero_degenerate(self) -> None:
        assert binomial_p_value(0, 10, 0.0) == 1.0
        assert binomial_p_value(1, 10, 0.0) == 0.0

    def test_p_null_one_degenerate(self) -> None:
        assert binomial_p_value(10, 10, 1.0) == 1.0
        assert binomial_p_value(9, 10, 1.0) == 0.0

    def test_successes_exceeding_trials_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot exceed"):
            binomial_p_value(11, 10, 0.5)

    def test_negative_inputs_raise(self) -> None:
        with pytest.raises(ValueError):
            binomial_p_value(-1, 10, 0.5)

    def test_p_null_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError):
            binomial_p_value(1, 10, 1.5)


# ---------------------------------------------------------------------------
# 2. Benjamini-Hochberg -- the 1995 paper's own worked example
# ---------------------------------------------------------------------------


class TestBenjaminiHochberg:
    #: Needleman et al. p-values, Table 1 of Benjamini & Hochberg (1995).
    PAPER_P = [
        0.0001, 0.0004, 0.0019, 0.0095, 0.0201, 0.0278, 0.0298, 0.0344,
        0.0459, 0.3240, 0.4262, 0.5719, 0.6528, 0.7590, 1.000,
    ]

    def test_paper_example_yields_four_discoveries_at_alpha_05(self) -> None:
        q = benjamini_hochberg(self.PAPER_P)
        assert all(v is not None for v in q)
        discoveries = sum(1 for v in q if v is not None and v <= 0.05)
        # The published result: BH flags the first four (smallest) p-values; Bonferroni (p * m)
        # would flag only three (0.0001, 0.0004, 0.0019 -- 0.0095 * 15 = 0.1425 > 0.05).
        assert discoveries == 4
        bonferroni = sum(1 for p in self.PAPER_P if p * len(self.PAPER_P) <= 0.05)
        assert bonferroni == 3
        assert discoveries > bonferroni

    def test_paper_example_first_four_q_values(self) -> None:
        q = benjamini_hochberg(self.PAPER_P)
        expected = [0.00150, 0.00300, 0.00950, 0.03562]
        for value, target in zip(q[:4], expected, strict=True):
            assert value == pytest.approx(target, abs=5e-6)

    def test_empty_input(self) -> None:
        assert benjamini_hochberg([]) == []

    def test_all_none(self) -> None:
        assert benjamini_hochberg([None, None, None]) == [None, None, None]

    def test_preserves_input_order(self) -> None:
        # Deliberately not pre-sorted; output must align positionally with input, not with rank.
        p = [0.04, 0.001, 0.03, None, 0.02]
        q = benjamini_hochberg(p)
        assert q[3] is None
        # The smallest p-value (index 1) should not have a larger q-value than a bigger p-value
        # (index 0) elsewhere in the list -- order of *output* tracks order of *input*.
        assert q[1] is not None and q[0] is not None
        assert q[1] <= q[0]

    def test_monotonicity_q_nondecreasing_in_p_order(self) -> None:
        rng = np.random.default_rng(99)
        p: list[float | None] = list(rng.uniform(0, 1, size=200))
        p[50] = None
        p[120] = None
        q = benjamini_hochberg(p)
        pairs = sorted(
            (
                (pv, qv)
                for pv, qv in zip(p, q, strict=True)
                if pv is not None and qv is not None
            ),
            key=lambda pair: pair[0],
        )
        q_in_p_order = [qv for _, qv in pairs]
        assert q_in_p_order == sorted(q_in_p_order)

    def test_none_still_counts_toward_m(self) -> None:
        """The behaviour the module docstring promises: an untestable entry consumed a trial, so
        adding more of them enlarges `m` and must not make the testable entries' q-values smaller.
        Five identical testable p-values, once alone and once padded with twenty `None`s."""
        testable: list[float | None] = [0.01, 0.02, 0.02, 0.03, 0.04]
        q_small_m = benjamini_hochberg(testable)
        q_large_m = benjamini_hochberg(testable + [None] * 20)[: len(testable)]
        pairs = list(zip(q_small_m, q_large_m, strict=True))
        strictly_larger = False
        for small, large in pairs:
            assert small is not None and large is not None
            assert large >= small
            if large > small:
                strictly_larger = True
        assert strictly_larger


# ---------------------------------------------------------------------------
# 3. scan() -- noise stays quiet, correction matters, real effect survives
# ---------------------------------------------------------------------------


class TestScanNoiseControl:
    """The heart of the module: prove the correction does what it is for.

    50 synthetic conditions, each with `independent_sample_size=60` and a hit rate drawn from
    `Binomial(60, 0.5)` (the same 0.5 as their own `baseline_hit_rate`) -- so every single one is a
    true null by construction, and any discovery among them is, by definition, a false one.
    Fixed seed 7 (of `np.random.default_rng`) was picked by scanning seeds 0-19 for one that
    demonstrates both required properties at once (several raw discoveries, corrected count near
    zero) rather than the very quietest seed available -- see the two tests below for what "near
    zero" and "materially higher" mean numerically.
    """

    N_CONDITIONS = 50
    N_INDEPENDENT = 60
    P_NULL = 0.5

    def _build_scan(self, alpha: float = 0.10) -> ScanResult:
        rng = np.random.default_rng(7)
        draws = rng.binomial(self.N_INDEPENDENT, self.P_NULL, size=self.N_CONDITIONS)
        table: dict[str, tuple[GuardReport, HorizonStats | None]] = {}
        expressions = []
        for i, successes in enumerate(draws):
            expr = f"noise_{i}"
            expressions.append(expr)
            hit_rate = float(successes) / self.N_INDEPENDENT
            stats = _stats(
                hit_rate=hit_rate,
                baseline_hit_rate=self.P_NULL,
                independent_sample_size=self.N_INDEPENDENT,
            )
            table[expr] = (PASSED, stats)

        return scan(
            "SPY",
            Interval.DAY,
            expressions,
            [5],
            evaluate=_make_evaluator(table),
            alpha=alpha,
        )

    def test_pure_noise_stays_quiet(self) -> None:
        """Measured: 0 discoveries out of 50 true nulls at alpha=0.10 with this seed. "Near zero"
        is defined generously here as at most 3 (6% of the 50 conditions) -- comfortably above the
        measured 0, but nowhere near the 5 raw (uncorrected) discoveries the next test shows the
        same data produces, so the bound cannot be satisfied by a correction that isn't working."""
        result = self._build_scan()
        assert result.trials == self.N_CONDITIONS
        assert result.discoveries <= 3
        assert result.discoveries == sum(1 for e in result.entries if e.discovery)

    def test_uncorrected_would_flag_materially_more(self) -> None:
        """Same 50 conditions: counting raw `p_value <= 0.05` (what a scan with no multiple-testing
        correction would report) against counting `q_value <= 0.05`. Measured: 5 raw vs 0 corrected
        -- the correction changes the answer, which is the entire point of the module."""
        result = self._build_scan()
        raw_discoveries = sum(1 for e in result.entries if e.p_value is not None and e.p_value <= 0.05)
        q_discoveries = sum(1 for e in result.entries if e.q_value is not None and e.q_value <= 0.05)
        assert raw_discoveries == 5
        assert q_discoveries == 0
        assert raw_discoveries > q_discoveries + 2  # "materially higher", not a one-off difference


class TestScanRealEffectSurvives:
    def test_strong_effect_survives_correction_among_49_nulls(self) -> None:
        """One condition with a large, well-sampled edge (75% hit rate against a 50% baseline over
        200 independent triggers) mixed into 49 true nulls at the same baseline. Its own p-value is
        astronomically small, so however the 49 nulls' p-values happen to fall, it is always ranked
        first and its q-value is `p * 50 / 1`, which stays far below alpha. The correction is not
        supposed to bury a real, well-powered effect -- only the noise."""
        rng = np.random.default_rng(3)
        table: dict[str, tuple[GuardReport, HorizonStats | None]] = {}
        expressions = ["strong_effect"]
        table["strong_effect"] = (
            PASSED,
            _stats(hit_rate=0.75, baseline_hit_rate=0.5, independent_sample_size=200),
        )
        draws = rng.binomial(60, 0.5, size=49)
        for i, successes in enumerate(draws):
            expr = f"null_{i}"
            expressions.append(expr)
            table[expr] = (
                PASSED,
                _stats(
                    hit_rate=float(successes) / 60,
                    baseline_hit_rate=0.5,
                    independent_sample_size=60,
                ),
            )

        result = scan(
            "QQQ", Interval.DAY, expressions, [10], evaluate=_make_evaluator(table), alpha=0.10
        )

        assert result.trials == 50
        [strong] = [e for e in result.entries if e.expression == "strong_effect"]
        assert strong.p_value is not None and strong.p_value < 1e-10
        assert strong.q_value is not None and strong.q_value <= 0.10
        assert strong.discovery is True


# ---------------------------------------------------------------------------
# 4. Guard failures, missing stats, and zero independent sample all consume a trial
# ---------------------------------------------------------------------------


class TestARaiseCostsOneEntryNotTheTable:
    """The structural half of the overflow bug, which outlived the arithmetic half.

    `scan()` has always wrapped `evaluate(...)` in a `try`/`except` whose comment reads *"one bad
    rule must not empty the table"*. But the p-value computation used to sit on the line
    immediately **after** that block closed, so when `binomial_p_value` raised `OverflowError` it
    propagated out of `scan()` and destroyed every entry -- exactly what the comment forbids, one
    line below the comment. Fixing only the arithmetic would have left the hazard armed for the
    next exception type, so the p-value call moved inside the `try`.

    This test drives that path with a `HorizonStats` whose `baseline_hit_rate` is out of range,
    which makes `binomial_p_value` raise without relying on the specific overflow that has now been
    fixed -- so it keeps testing the containment rather than quietly passing forever.
    """

    def test_a_p_value_raise_leaves_the_other_entries_intact(self) -> None:
        table: dict[str, tuple[GuardReport, HorizonStats | None]] = {
            "poisonous": (
                PASSED,
                _stats(hit_rate=0.6, baseline_hit_rate=42.0, independent_sample_size=50),
            ),
            "fine_a": (
                PASSED,
                _stats(hit_rate=0.9, baseline_hit_rate=0.5, independent_sample_size=40),
            ),
            "fine_b": (
                PASSED,
                _stats(hit_rate=0.8, baseline_hit_rate=0.5, independent_sample_size=40),
            ),
        }
        result = scan(
            "IWM", Interval.DAY, list(table.keys()), [5], evaluate=_make_evaluator(table)
        )

        # The whole point: three expressions in, three entries out, and the trial count intact.
        assert result.trials == 3
        assert len(result.entries) == 3

        by_expr = {e.expression: e for e in result.entries}
        poisoned = by_expr["poisonous"]
        assert poisoned.p_value is None
        assert poisoned.q_value is None
        assert poisoned.discovery is False
        # Folded into the existing untestable state rather than a new one.
        assert poisoned.guard.status is GuardStatus.FAILED
        assert by_expr["fine_a"].p_value is not None
        assert by_expr["fine_b"].p_value is not None


class TestScanUntestableEntries:
    def test_guard_failure_and_missing_stats_and_zero_independent_sample_are_all_untestable(
        self,
    ) -> None:
        table: dict[str, tuple[GuardReport, HorizonStats | None]] = {
            "guard_failed": (FAILED, None),
            "no_stats": (PASSED, None),
            "zero_independent": (
                PASSED,
                _stats(hit_rate=0.6, baseline_hit_rate=0.5, independent_sample_size=0),
            ),
            "testable": (
                PASSED,
                _stats(hit_rate=0.9, baseline_hit_rate=0.5, independent_sample_size=40),
            ),
        }
        result = scan(
            "IWM",
            Interval.DAY,
            list(table.keys()),
            [5],
            evaluate=_make_evaluator(table),
        )

        assert result.trials == 4
        by_expr = {e.expression: e for e in result.entries}
        for expr in ("guard_failed", "no_stats", "zero_independent"):
            entry = by_expr[expr]
            assert entry.p_value is None
            assert entry.q_value is None
            assert entry.discovery is False
        assert by_expr["testable"].p_value is not None

    def test_none_p_value_still_counts_toward_m_through_full_scan(self) -> None:
        """The behaviour promised in `benjamini_hochberg`'s docstring, proven end-to-end through
        `scan()`: two scans identical in their testable entries, differing only in how many
        untestable (guard-failed) entries are also present. The testable entries' q-values must be
        larger (weaker) in the scan carrying more untestable trials."""
        testable_stats: _EvalTable = {
            f"testable_{i}": (
                PASSED,
                _stats(hit_rate=hr, baseline_hit_rate=0.5, independent_sample_size=60),
            )
            for i, hr in enumerate([0.75, 0.72, 0.70, 0.68, 0.66])
        }

        small_table = dict(testable_stats)
        result_small = scan(
            "AAA", Interval.DAY, list(small_table.keys()), [5], evaluate=_make_evaluator(small_table)
        )

        large_table = dict(testable_stats)
        for i in range(20):
            large_table[f"untestable_{i}"] = (FAILED, None)
        result_large = scan(
            "AAA", Interval.DAY, list(large_table.keys()), [5], evaluate=_make_evaluator(large_table)
        )

        assert result_small.trials == 5
        assert result_large.trials == 25

        small_by_expr = {e.expression: e for e in result_small.entries}
        large_by_expr = {e.expression: e for e in result_large.entries}
        for expr in testable_stats:
            small_q = small_by_expr[expr].q_value
            large_q = large_by_expr[expr].q_value
            assert small_q is not None and large_q is not None
            assert large_q >= small_q
        assert any(
            large_by_expr[expr].q_value > small_by_expr[expr].q_value  # type: ignore[operator]
            for expr in testable_stats
        )


# ---------------------------------------------------------------------------
# 5. trials cannot be gamed -- ScanResult's own validator
# ---------------------------------------------------------------------------


class TestTrialsCannotBeGamed:
    def test_filtering_entries_after_the_fact_raises(self) -> None:
        """Pinning `ScanResult`'s validator: a caller reporting `trials=6` while only including the
        `entries` it wants to show must not be able to construct the model at all."""
        entries = [
            ScanEntry(label=f"e{i}", expression=f"e{i}", horizon=5, guard=PASSED)
            for i in range(6)
        ]
        # Filter down to the "interesting" three, as a caller trying to hide the rest would.
        filtered = entries[:3]
        with pytest.raises(ValidationError, match="trials"):
            ScanResult(
                symbol="SPY",
                interval=Interval.DAY,
                generated_at=dt.datetime.now(dt.UTC),
                trials=6,
                entries=filtered,
                discoveries=0,
            )

    def test_correct_trial_count_constructs(self) -> None:
        entries = [
            ScanEntry(label=f"e{i}", expression=f"e{i}", horizon=5, guard=PASSED)
            for i in range(3)
        ]
        result = ScanResult(
            symbol="SPY",
            interval=Interval.DAY,
            generated_at=dt.datetime.now(dt.UTC),
            trials=3,
            entries=entries,
            discoveries=0,
        )
        assert result.trials == 3

    def test_discoveries_count_must_match_flagged_entries(self) -> None:
        entries = [
            ScanEntry(label=f"e{i}", expression=f"e{i}", horizon=5, guard=PASSED)
            for i in range(3)
        ]
        with pytest.raises(ValidationError, match="discoveries"):
            ScanResult(
                symbol="SPY",
                interval=Interval.DAY,
                generated_at=dt.datetime.now(dt.UTC),
                trials=3,
                entries=entries,
                discoveries=1,
            )


# ---------------------------------------------------------------------------
# 6. indicator_cache -- scan() threads a caller-supplied cache through `evaluate`
# ---------------------------------------------------------------------------


def _bars(n: int = 20) -> pd.DataFrame:
    """Minimal real bars, just enough for `rsi:14` to settle. Used only by the tests below, which
    hand `scan()` an `Evaluate` that calls the *real* `app.rules.evaluate.evaluate` -- everywhere
    else in this file fabricates `HorizonStats` directly (see the module docstring) because proving
    accounting and correction needs no real indicator maths, but proving the cache `scan()` forwards
    actually reaches indicator computation does."""
    start = dt.datetime(2026, 1, 2, tzinfo=dt.UTC)
    ts = pd.to_datetime([start + dt.timedelta(days=i) for i in range(n)], utc=True)
    close = [100.0 + i * 0.5 for i in range(n)]
    return pd.DataFrame(
        {
            "ts": ts,
            "open": close,
            "high": [c + 0.5 for c in close],
            "low": [c - 0.5 for c in close],
            "close": close,
            "adj_close": close,
            "volume": [1_000.0] * n,
        }
    )


class TestScanIndicatorCacheForwarding:
    """`scan()` never computes an indicator itself -- it only ever calls the injected `Evaluate` --
    so it cannot *perform* the cross-tree sharing `app.rules.evaluate.IndicatorCache` provides (see
    `tests/test_rule_evaluate.py::TestIndicatorCache` for that). What it must do is carry a
    caller-supplied cache through every call it makes, proven here by handing it an `Evaluate` that
    calls the real `app.rules.evaluate.evaluate` and counting real `indicator_registry.compute`
    calls -- the same technique `test_rule_evaluate.py` uses, one layer further out."""

    _RSI14 = IndicatorRef(name="rsi", args=(14.0,))
    _OVERSOLD = Comparison(_RSI14, CompareOp.LT, Literal(30.0))
    _OVERBOUGHT = Comparison(_RSI14, CompareOp.GT, Literal(70.0))

    def _make_real_evaluator(
        self, bars: pd.DataFrame
    ) -> Callable[..., tuple[GuardReport, HorizonStats | None]]:
        """An `Evaluate` standing in for a cache-aware `app.backtest.service.build_scan`: it maps
        `expression` to a prebuilt tree and runs it through the real evaluator, forwarding whatever
        `indicator_cache` `scan()` gave it (which is `None` unless `scan()` was itself given one)."""
        trees = {"oversold": self._OVERSOLD, "overbought": self._OVERBOUGHT}
        stats = _stats(hit_rate=0.5, baseline_hit_rate=0.5, independent_sample_size=10)

        def _evaluate(
            expression: str, horizon: int, *, indicator_cache: IndicatorCache | None = None
        ) -> tuple[GuardReport, HorizonStats | None]:
            rules_evaluate(
                trees[expression], bars, interval=Interval.DAY, indicator_cache=indicator_cache
            )
            return PASSED, stats

        return _evaluate

    def test_a_supplied_indicator_cache_is_forwarded_and_shares_computation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`oversold` (`rsi:14 < 30`) and `overbought` (`rsi:14 > 70`) both want `rsi:14`. Handing
        `scan()` one `IndicatorCache` for the whole run must mean the real computation happens once
        across both expressions, counted directly via a spy on `indicator_registry.compute`."""
        bars = _bars()
        calls: list[int] = []
        original_compute = indicator_registry.compute

        def spy(bars_arg: pd.DataFrame, requests: list) -> pd.DataFrame:  # type: ignore[type-arg]
            calls.append(len(requests))
            return original_compute(bars_arg, requests)

        monkeypatch.setattr(indicator_registry, "compute", spy)

        result = scan(
            "SPY",
            Interval.DAY,
            ["oversold", "overbought"],
            [5],
            evaluate=self._make_real_evaluator(bars),
            indicator_cache=IndicatorCache(),
        )

        assert result.trials == 2
        # One `compute` call total: the second expression's `rsi:14` was already in the cache
        # `scan()` forwarded from the first.
        assert calls == [1]

    def test_without_a_supplied_cache_the_same_two_expressions_compute_it_twice(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The baseline this fix changes: `scan()` called exactly as it always has (no
        `indicator_cache=`) forwards nothing, so the two expressions' shared `rsi:14` is computed
        once per expression rather than once for the whole scan."""
        bars = _bars()
        calls: list[int] = []
        original_compute = indicator_registry.compute

        def spy(bars_arg: pd.DataFrame, requests: list) -> pd.DataFrame:  # type: ignore[type-arg]
            calls.append(len(requests))
            return original_compute(bars_arg, requests)

        monkeypatch.setattr(indicator_registry, "compute", spy)

        result = scan(
            "SPY",
            Interval.DAY,
            ["oversold", "overbought"],
            [5],
            evaluate=self._make_real_evaluator(bars),
        )

        assert result.trials == 2
        assert calls == [1, 1]

    def test_default_none_makes_the_exact_pre_cache_two_argument_call(self) -> None:
        """Backward compatibility, pinned directly: an `Evaluate` that accepts only the two
        positional arguments every caller of `scan()` used before this parameter existed --
        including today's real `app.backtest.service.build_scan` closure -- must still work when the
        caller does not pass `indicator_cache=` to `scan()`. A callable with no room for an extra
        keyword argument would raise `TypeError` the moment one was forwarded, so this passing is
        itself proof that nothing extra was forwarded."""

        def strict_two_arg_evaluate(
            expression: str, horizon: int
        ) -> tuple[GuardReport, HorizonStats | None]:
            return PASSED, _stats(hit_rate=0.6, baseline_hit_rate=0.5, independent_sample_size=10)

        result = scan(
            "SPY",
            Interval.DAY,
            ["a", "b"],
            [5],
            evaluate=strict_two_arg_evaluate,  # type: ignore[arg-type]
        )
        assert result.trials == 2

"""Event studies and reverse conditioning.

Most of these are falsification tests: they build a situation whose honest answer is "nothing here"
and demand the code say so. A study that only reports edges when edges exist is untested -- the
failure mode that matters is a study that reports an edge when there is none, and the only way to
catch it is to construct the none.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.backtest import events
from app.backtest.models import STUDY_HORIZONS
from app.db.duck import Interval
from app.rules.evaluate import IndicatorCache, IndicatorCacheError
from app.rules.models import Entry


def _frame(close: np.ndarray, *, open_: np.ndarray | None = None) -> pd.DataFrame:
    n = len(close)
    o = close if open_ is None else open_
    return pd.DataFrame(
        {
            "ts": pd.date_range("2015-01-01", periods=n, freq="D", tz="UTC"),
            "open": o,
            "high": np.maximum(close, o) + 0.5,
            "low": np.minimum(close, o) - 0.5,
            "close": close,
            "adj_close": close,
            "volume": np.full(n, 1e6),
        }
    )


def _walk(n: int = 800, *, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 + rng.normal(0.0, 1.0, size=n).cumsum()
    return _frame(np.maximum(close, 5.0))


class _FixedGrammar:
    """Parses nothing; the evaluator below ignores the tree entirely."""

    def parse(self, expression: str) -> object:
        return expression


class _SignalEvaluator:
    """Returns a caller-supplied signal, so a test can pin the trigger pattern exactly rather than
    reverse-engineering one out of an indicator."""

    def __init__(self, signals: dict[str, pd.Series]) -> None:
        self._signals = signals

    def evaluate(
        self,
        node: object,
        bars: pd.DataFrame,
        *,
        interval: Interval,
        indicator_cache: IndicatorCache | None = None,
    ) -> pd.Series:
        return self._signals[str(node)]


def _study(bars: pd.DataFrame, signals: dict[str, pd.Series], horizons=(5, 20)):  # type: ignore[no-untyped-def]
    return events.event_study(
        bars,
        list(signals),
        interval=Interval.DAY,
        horizons=list(horizons),
        entry=Entry.NEXT_OPEN,
        grammar=_FixedGrammar(),
        evaluator=_SignalEvaluator(signals),
    )


class TestBaselineIsTheSameSample:
    """The baseline must be measured over exactly the bars the triggers were drawn from. Nothing
    else in the module can be trusted if this is wrong, and a wrong baseline is invisible -- it just
    makes every edge come out flattering."""

    def test_a_rule_that_fires_on_every_evaluable_bar_has_exactly_zero_edge(self) -> None:
        """The sharpest baseline test there is: a condition that *is* the baseline must measure as
        the baseline, to the last floating-point bit. Any discrepancy means the two samples were
        built differently."""
        bars = _walk()
        always = pd.Series([True] * len(bars), dtype="boolean")
        arms, _ = _study(bars, {"always": always})

        for stats in arms[0].stats:
            assert stats.hit_rate == stats.baseline_hit_rate
            assert stats.edge == 0.0
            assert stats.distribution.median == stats.baseline_distribution.median

    def test_a_random_signal_measures_no_meaningful_edge(self) -> None:
        """A condition carrying no information must not look informative."""
        bars = _walk(1200, seed=3)
        rng = np.random.default_rng(99)
        fires = pd.Series(rng.random(len(bars)) < 0.25, dtype="boolean")
        arms, _ = _study(bars, {"random": fires}, horizons=(5,))

        stats = arms[0].stats[0]
        assert stats.sample_size > 200
        # ~250 independent-ish draws puts the standard error of a proportion near 3 points; 8 is a
        # generous multiple of that and still far below any edge worth acting on.
        assert stats.edge is not None
        assert abs(stats.edge) < 0.08, stats.edge

    def test_unknown_bars_are_excluded_from_the_baseline_not_counted_as_quiet(self) -> None:
        """Through an indicator's warmup a rule has no truth value. Folding that into `False` pads
        the baseline with bars the rule was never asked about -- constructed here so the two answers
        differ enormously: the unknown region falls, the evaluable region rises."""
        n = 200
        close = np.concatenate([np.linspace(200.0, 100.0, 100), np.linspace(100.0, 200.0, n - 100)])
        bars = _frame(close)
        signal = pd.Series([pd.NA] * 100 + [True] * (n - 100), dtype="boolean")
        arms, _ = _study(bars, {"late": signal}, horizons=(5,))

        stats = arms[0].stats[0]
        # Only the rising half is evaluable, so the baseline is 1.0. Had the falling half been
        # counted as quiet bars it would sit near 0.5.
        assert stats.baseline_hit_rate == 1.0
        assert stats.hit_rate == 1.0
        assert stats.edge == 0.0
        assert arms[0].evaluable_bars < n


class TestLookahead:
    """The signal bar is not tradeable. This is the commonest way a backtest invents an edge, and it
    is invisible in the output -- the numbers simply come out better."""

    def test_a_move_confined_to_the_signal_bar_is_worth_nothing_at_next_open(self) -> None:
        n = 60
        close = np.full(n, 100.0)
        open_ = np.full(n, 100.0)
        # Bar 30 spikes 10% and closes there; bar 31 opens back at 100. A same-close entry captures
        # the spike it could never have bought; a next-open entry correctly captures nothing.
        close[30] = 110.0
        bars = _frame(close, open_=open_)
        signal = pd.Series([i == 30 for i in range(n)], dtype="boolean")

        next_open, _ = events.event_study(
            bars, ["s"], interval=Interval.DAY, horizons=[5], entry=Entry.NEXT_OPEN,
            grammar=_FixedGrammar(), evaluator=_SignalEvaluator({"s": signal}),
        )
        same_close, _ = events.event_study(
            bars, ["s"], interval=Interval.DAY, horizons=[5], entry=Entry.SAME_CLOSE,
            grammar=_FixedGrammar(), evaluator=_SignalEvaluator({"s": signal}),
        )

        assert next_open[0].stats[0].distribution.median == 0.0
        # close[34]/close[30] - 1 = 100/110 - 1
        assert same_close[0].stats[0].distribution.median == pytest.approx(100 / 110 - 1)
        assert same_close[0].stats[0].distribution.median < -0.09


class TestIndependence:
    """Overlapping forward windows are not independent observations."""

    def test_a_hundred_consecutive_triggers_collapse(self) -> None:
        """Greedy non-overlapping scan over positions 0..99 at horizon 20 accepts 0, 20, 40, 60, 80
        -- five, not a hundred."""
        bars = _walk(400)
        signal = pd.Series([i < 100 for i in range(len(bars))], dtype="boolean")
        arms, _ = _study(bars, {"burst": signal}, horizons=(20,))

        stats = arms[0].stats[0]
        assert stats.sample_size == 100
        assert stats.independent_sample_size == 5

    def test_at_horizon_one_every_trigger_is_independent(self) -> None:
        bars = _walk(400)
        signal = pd.Series([i < 100 for i in range(len(bars))], dtype="boolean")
        arms, _ = _study(bars, {"burst": signal}, horizons=(1,))
        assert arms[0].stats[0].independent_sample_size == 100


class TestWindowsAreExcludedNotTruncated:
    def test_triggers_too_close_to_the_end_are_dropped_from_the_sample_but_kept_as_dates(
        self,
    ) -> None:
        """They happened -- a chart overlay must mark them -- but they have no 20-bar future, and
        measuring one over the 3 bars available would mix horizons inside one statistic."""
        bars = _walk(100)
        signal = pd.Series([i in (10, 97, 98) for i in range(len(bars))], dtype="boolean")
        arms, _ = _study(bars, {"late": signal}, horizons=(20,))

        assert arms[0].triggers == 3
        assert len(arms[0].trigger_dates) == 3
        assert arms[0].stats[0].sample_size == 1


class TestArmDeltas:
    """A narrowing condition changes two things at once, and a delta that shows only the hit rate
    invites reading a shrinking sample as an improvement."""

    def test_a_narrowing_arm_reports_both_the_rate_change_and_the_sample_loss(self) -> None:
        bars = _walk(600)
        broad = pd.Series([i % 2 == 0 for i in range(len(bars))], dtype="boolean")
        narrow = pd.Series([i % 20 == 0 for i in range(len(bars))], dtype="boolean")
        arms, deltas = _study(bars, {"broad": broad, "narrow": narrow}, horizons=(5, 20))

        assert len(arms) == 2
        assert len(deltas) == 2  # one non-base arm x two horizons
        for delta in deltas:
            assert delta.sample_size_delta < 0
            assert delta.independent_sample_size_delta <= 0

    def test_a_single_arm_study_has_no_deltas(self) -> None:
        bars = _walk(200)
        only = pd.Series([True] * len(bars), dtype="boolean")
        arms, deltas = _study(bars, {"only": only})
        assert len(arms) == 1
        assert deltas == []

    def test_deltas_are_flattened_in_the_documented_order(self) -> None:
        bars = _walk(400)
        signals = {
            "a": pd.Series([True] * len(bars), dtype="boolean"),
            "b": pd.Series([i % 3 == 0 for i in range(len(bars))], dtype="boolean"),
            "c": pd.Series([i % 7 == 0 for i in range(len(bars))], dtype="boolean"),
        }
        horizons = (5, 20)
        _, deltas = _study(bars, signals, horizons=horizons)

        assert len(deltas) == 2 * len(horizons)
        for arm_index in (1, 2):
            for h_index, horizon in enumerate(horizons):
                flat = (arm_index - 1) * len(horizons) + h_index
                assert deltas[flat].horizon == horizon


class TestEmptyAndDegenerate:
    def test_no_conditions_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least one condition"):
            events.event_study(_walk(50), [], interval=Interval.DAY, horizons=[5], entry=Entry.NEXT_OPEN)

    def test_a_rule_that_never_fires_reports_nothing_rather_than_zero(self) -> None:
        bars = _walk(200)
        never = pd.Series([False] * len(bars), dtype="boolean")
        arms, _ = _study(bars, {"never": never}, horizons=(5,))

        stats = arms[0].stats[0]
        assert arms[0].triggers == 0
        assert stats.hit_rate is None
        assert stats.edge is None
        assert stats.baseline_hit_rate is not None

    def test_an_all_unknown_rule_has_no_baseline_either(self) -> None:
        bars = _walk(200)
        unknown = pd.Series([pd.NA] * len(bars), dtype="boolean")
        arms, _ = _study(bars, {"unknown": unknown}, horizons=(5,))
        assert arms[0].stats[0].baseline_hit_rate is None


class TestReverseConditioning:
    def test_clustered_moves_are_reported_as_far_fewer_independent_episodes(self) -> None:
        """One explosive run makes the top decile consecutive. The raw count would claim dozens of
        distinct episodes where there is essentially one."""
        n = 400
        close = np.full(n, 100.0)
        close[200:260] = np.linspace(100.0, 300.0, 60)
        close[260:] = 300.0
        bars = _frame(close)

        _, selected, independent, _ = events.reverse_conditioning(
            bars, ["rsi:14"], interval=Interval.DAY, horizon=20, quantile=0.9, lookback=0
        )
        assert selected > 20
        assert independent < selected / 3

    def test_a_constant_indicator_reports_no_separation_rather_than_infinity(self) -> None:
        """Dividing a median shift by a zero IQR would report an infinite separation for an
        indicator that never moved -- the most confident possible answer about the least
        informative possible input."""
        bars = _walk(400)
        constant = pd.Series(np.full(len(bars), 5.0))

        class _Request:
            key = "flat"
            columns = ("flat",)

        class _ConstantRegistry:
            def request(self, spec_text: str, *, interval: Interval | None = None) -> object:
                return _Request()

            def compute(self, bars: pd.DataFrame, requests) -> pd.DataFrame:  # type: ignore[no-untyped-def]
                return pd.DataFrame({"flat": constant}, index=bars.index)

        _, _, _, profiles = events.reverse_conditioning(
            bars, ["flat"], interval=Interval.DAY, horizon=20, quantile=0.9,
            lookback=0, registry=_ConstantRegistry(),
        )
        assert profiles
        assert profiles[0].separation is None

    def test_profiles_sort_by_absolute_separation_with_unmeasurable_last(self) -> None:
        bars = _walk(800, seed=21)
        _, _, _, profiles = events.reverse_conditioning(
            bars, ["rsi:14", "atr:14", "sma:20"], interval=Interval.DAY,
            horizon=20, quantile=0.9, lookback=2,
        )
        measured = [p.separation for p in profiles if p.separation is not None]
        assert measured == sorted(measured, key=lambda v: -abs(v))
        unmeasured_first = next(
            (i for i, p in enumerate(profiles) if p.separation is None), len(profiles)
        )
        assert all(p.separation is None for p in profiles[unmeasured_first:])

    def test_it_carries_no_hit_rate_or_p_value(self) -> None:
        """Structural, not stylistic: a field holding one would eventually be rendered, and there is
        nothing for it to mean against a hypothesis derived from the same sample."""
        from app.backtest.models import IndicatorProfile, ReverseConditioning

        for model in (ReverseConditioning, IndicatorProfile):
            fields = set(model.model_fields)
            assert not fields & {"hit_rate", "p_value", "q_value", "significance", "discovery"}


class TestHorizons:
    def test_the_study_horizons_include_ten(self) -> None:
        """The workbench reports 10 where the decision table does not. Pinned because the two tuples
        are deliberately separate -- a change to the summary table must not silently change what a
        stored run card means."""
        from app.rules.models import HORIZONS

        assert STUDY_HORIZONS == (1, 5, 10, 20, 60)
        assert 10 in STUDY_HORIZONS
        assert 10 not in HORIZONS

    def test_stats_come_back_in_the_requested_order(self) -> None:
        bars = _walk(400)
        signal = pd.Series([i % 5 == 0 for i in range(len(bars))], dtype="boolean")
        arms, _ = _study(bars, {"s": signal}, horizons=(20, 1, 5))
        assert [s.horizon for s in arms[0].stats] == [20, 1, 5]


class TestIndicatorCache:
    """`event_study` accepts a caller-owned `IndicatorCache` and forwards it to every arm's
    `evaluator.evaluate` call -- see `event_study`'s docstring. These use the *real*
    `app.rules.evaluate`/`app.indicators.registry` collaborators, not `_SignalEvaluator`, because the
    property under test -- sharing one indicator computation across conditions -- belongs to that
    evaluator, only threaded through by this module."""

    def test_conditions_sharing_an_indicator_compute_it_once_with_a_shared_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.indicators import registry as indicator_registry

        bars = _walk(300)
        calls = {"n": 0}
        real_compute = indicator_registry.compute

        def counting_compute(bars_arg, requests):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            return real_compute(bars_arg, requests)

        monkeypatch.setattr(indicator_registry, "compute", counting_compute)

        cache = IndicatorCache()
        events.event_study(
            bars,
            ["rsi(14) < 30", "rsi(14) > 70"],
            interval=Interval.DAY,
            horizons=[5],
            indicator_cache=cache,
        )
        assert calls["n"] == 1  # one rsi:14 request, shared by both conditions

        calls["n"] = 0
        events.event_study(
            bars, ["rsi(14) < 30", "rsi(14) > 70"], interval=Interval.DAY, horizons=[5]
        )
        assert calls["n"] == 2  # no cache: each condition recomputes rsi:14 for itself

    def test_indicator_cache_error_still_fires_on_a_different_bars_frame(self) -> None:
        """The correctness guard this cache depends on must survive threading it through
        `event_study`: reusing one cache across two different bar frames must raise rather than
        silently serve the first frame's indicator values to the second."""
        cache = IndicatorCache()
        first = _walk(200)
        second = _walk(150)

        events.event_study(
            first, ["rsi(14) < 30"], interval=Interval.DAY, horizons=[5], indicator_cache=cache
        )
        with pytest.raises(IndicatorCacheError):
            events.event_study(
                second, ["rsi(14) < 30"], interval=Interval.DAY, horizons=[5], indicator_cache=cache
            )

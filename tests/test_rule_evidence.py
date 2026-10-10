"""Tests for :mod:`app.rules.evidence`.

Every fixture in here builds its own ``signal`` by hand as an explicit nullable-``"boolean"``
:class:`pandas.Series` -- never by running :mod:`app.rules.grammar` or :mod:`app.rules.evaluate`,
which other agents are writing in parallel and which this module must not depend on to be tested.

Where a number can be worked out by hand (the lookahead test, the overlap test, the warmup test,
the horizon-shrink test), the test asserts that exact number rather than a loose bound -- a wrong
constant in the implementation should fail loudly, not slip through a generous tolerance. The one
exception is the no-information-rule test, whose signal is a random subset of bars: there the
assertion is necessarily a tolerance, chosen well above what the fixture actually produces (see the
docstring on that test).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

import numpy as np
import pandas as pd
import pytest

from app.rules.evidence import compute_evidence, rule_state
from app.rules.models import HORIZONS, Entry, RuleState, Significance, TriState

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _bars(
    close: Sequence[float],
    *,
    opens: Sequence[float] | None = None,
    start: dt.datetime = dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
    step: dt.timedelta = dt.timedelta(days=1),
) -> pd.DataFrame:
    """A minimal daily bar frame: ``ts`` tz-aware UTC, a plain positional index, BAR_COLUMNS.

    ``open`` defaults to ``close`` (no gaps) unless a test needs the two to diverge -- the
    lookahead test in particular relies on being able to hold ``open`` flat while ``close`` spikes
    on exactly one bar.
    """
    n = len(close)
    open_v = list(opens) if opens is not None else list(close)
    ts = pd.to_datetime([start + step * i for i in range(n)], utc=True)
    return pd.DataFrame(
        {
            "ts": ts,
            "open": open_v,
            "high": [c + 0.5 for c in close],
            "low": [c - 0.5 for c in close],
            "close": list(close),
            "adj_close": list(close),
            "volume": [1_000] * n,
        }
    )


def _signal(values: Sequence[bool | None], index: pd.Index) -> pd.Series:
    """A nullable-``"boolean"`` series with ``None`` mapped to ``pd.NA`` -- the unknown state."""
    return pd.Series(values, index=index, dtype="boolean")


def _empty_bars() -> pd.DataFrame:
    return _bars([])


# ---------------------------------------------------------------------------
# 1. The signal bar is not tradeable
# ---------------------------------------------------------------------------


class TestLookaheadConvention:
    """A rule evaluated on bar ``t`` cannot transact at ``t``'s own close -- that price was only
    known once the session settled. ``SAME_CLOSE`` exists precisely to show how much of a rule's
    apparent edge comes from pretending otherwise."""

    def test_same_bar_spike_is_invisible_to_next_open_but_not_same_close(self) -> None:
        # The entire move is bar 50's own candle: open 100 -> close 110. Every other open and
        # close in the series, including bar 50's own open and bar 51's open, stays at 100 -- the
        # spike does not persist and nothing "happens" on any other bar.
        n = 100
        spike = 50
        close = [100.0] * n
        close[spike] = 110.0
        opens = [100.0] * n
        bars = _bars(close, opens=opens)
        signal = _signal([i == spike for i in range(n)], bars.index)

        [next_open] = compute_evidence(signal, bars, horizons=[5], entry=Entry.NEXT_OPEN)
        [same_close] = compute_evidence(signal, bars, horizons=[5], entry=Entry.SAME_CLOSE)

        assert next_open.sample_size == 1
        assert same_close.sample_size == 1

        # NEXT_OPEN enters at open[51] = 100 (never touches the spike) and exits at close[55] =
        # 100 (flat): the honest forward return is exactly zero.
        assert next_open.median_return == pytest.approx(0.0, abs=1e-9)
        assert next_open.baseline_median_return == pytest.approx(0.0, abs=1e-9)

        # SAME_CLOSE enters at close[50] = 110 -- the very price the spike produced -- and exits
        # at close[54] = 100 (flat): a large, entirely fabricated loss that only exists because
        # the "entry" was backdated to a price that had already happened.
        assert same_close.median_return == pytest.approx(-1 / 11, abs=1e-9)
        assert same_close.baseline_median_return == pytest.approx(0.0, abs=1e-9)

        # The gap between "what the trigger did" and "what a random bar does" is the honest
        # measure of edge here (hit_rate is degenerate with a single trigger: 0 or 1, no shading).
        next_open_edge = next_open.median_return - next_open.baseline_median_return  # type: ignore[operator]
        same_close_edge = same_close.median_return - same_close.baseline_median_return  # type: ignore[operator]
        assert abs(next_open_edge) < 1e-9, "NEXT_OPEN must show no edge from a same-bar-only move"
        assert abs(same_close_edge) > 0.05, "SAME_CLOSE must reveal the lookahead as a large edge"


# ---------------------------------------------------------------------------
# 2. A hit rate without its base rate is not evidence
# ---------------------------------------------------------------------------


class TestBaseline:
    def test_random_signal_shows_no_edge_over_its_baseline(self) -> None:
        """A rule that fires on a random 30% of bars carries no information. Its hit rate must
        land close to the baseline hit rate over the same sample, and the coarse significance
        verdict must never call that noise "suggestive".

        The price path and the trigger mask are drawn from two independent, fixed-seed generators
        so the result is deterministic. With these seeds the measured |edge| comes out near 1.5
        percentage points (see the exploratory run this test was derived from) -- the 0.1 bound
        below is generous headroom above that, not a value tuned to just barely pass.
        """
        n = 400
        price_rng = np.random.default_rng(42)
        step_returns = price_rng.normal(0, 0.01, size=n)
        close = 100.0 * np.cumprod(1.0 + step_returns)
        bars = _bars(list(close))

        signal_rng = np.random.default_rng(7)
        trigger_mask = signal_rng.random(n) < 0.3
        signal = _signal(list(trigger_mask), bars.index)

        [evidence] = compute_evidence(signal, bars, horizons=[20], entry=Entry.NEXT_OPEN)

        assert evidence.hit_rate is not None
        assert evidence.baseline_hit_rate is not None
        assert evidence.edge is not None
        assert abs(evidence.edge) < 0.1
        assert evidence.significance is not Significance.SUGGESTIVE

    def test_baseline_covers_every_evaluable_bar_not_just_non_triggers(self) -> None:
        """The baseline is measured over *every* evaluable bar, triggers included -- not only the
        bars the rule declined to fire on. A rule that always fires therefore has an identical
        baseline and trigger sample, and zero edge by construction."""
        n = 80
        close = [100.0 + 0.3 * i for i in range(n)]
        bars = _bars(close)
        signal = _signal([True] * n, bars.index)

        [evidence] = compute_evidence(signal, bars, horizons=[5], entry=Entry.NEXT_OPEN)

        assert evidence.hit_rate == evidence.baseline_hit_rate
        assert evidence.median_return == evidence.baseline_median_return
        assert evidence.edge == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 3. Overlapping windows are not independent observations
# ---------------------------------------------------------------------------


class TestIndependence:
    def test_consecutive_triggers_collapse_to_a_handful_of_independent_ones(self) -> None:
        """100 consecutive triggers under a 20-bar horizon share almost all of their forward
        windows. The raw trigger count must not be mistaken for evidence strength -- only the
        greedy non-overlapping count is."""
        n = 101
        bars = _bars([100.0] * n)
        # Bars 0..99 fire; bar 100 exists only to give trigger 80 (the last one whose 20-bar
        # NEXT_OPEN window fits) somewhere to land.
        signal = _signal([i < 100 for i in range(n)], bars.index)

        [evidence] = compute_evidence(signal, bars, horizons=[20], entry=Entry.NEXT_OPEN)

        # Triggers 0..80 have a complete NEXT_OPEN window (entry t+1, exit t+20 <= 100); 81..99
        # do not.
        assert evidence.sample_size == 81
        # Greedy scan from 0, skipping 20 bars after each accepted trigger: 0, 20, 40, 60, 80.
        assert evidence.independent_sample_size == 5
        assert evidence.significance is Significance.INSUFFICIENT


# ---------------------------------------------------------------------------
# 4. UNKNOWN is not FALSE
# ---------------------------------------------------------------------------


class TestUnknownExclusion:
    def test_warmup_window_is_dropped_from_baseline_not_counted_as_quiet(self) -> None:
        """If an indicator's 200-bar warmup were folded into ``False`` instead of excluded, those
        200 bars would pad the baseline denominator as "quiet, no-gain" days. Here they are
        anything but quiet -- price rises every single bar through the warmup -- so if the bug
        were present the baseline hit rate would come out near 0.78 (roughly 195 fabricated hits
        out of 250 baseline rows). Excluding them correctly leaves a baseline computed purely over
        the flat, known-state region, where the honest hit rate is exactly zero.
        """
        warmup = 200
        known = 60
        # Strictly rising through the (excluded) warmup, then a flat plateau through the known
        # region -- so any leakage of the warmup rows into the baseline is unmistakable.
        close = [100.0 + i for i in range(warmup)] + [300.0] * known
        bars = _bars(close)

        values: list[bool | None] = [None] * warmup + [False] * known
        trigger_bars = (210, 220, 230, 240, 250)
        for idx in trigger_bars:
            values[idx] = True
        signal = _signal(values, bars.index)

        [evidence] = compute_evidence(signal, bars, horizons=[5], entry=Entry.NEXT_OPEN)

        assert evidence.sample_size == len(trigger_bars)
        assert evidence.baseline_hit_rate == pytest.approx(0.0, abs=1e-9)
        assert evidence.baseline_median_return == pytest.approx(0.0, abs=1e-9)
        assert evidence.hit_rate == pytest.approx(0.0, abs=1e-9)

    def test_all_unknown_signal_yields_no_measurable_evidence(self) -> None:
        n = 50
        bars = _bars([100.0 + i * 0.1 for i in range(n)])
        signal = _signal([None] * n, bars.index)

        [evidence] = compute_evidence(signal, bars, horizons=[5], entry=Entry.NEXT_OPEN)

        assert evidence.sample_size == 0
        assert evidence.hit_rate is None
        assert evidence.baseline_hit_rate is None
        assert evidence.median_return is None
        assert evidence.baseline_median_return is None
        assert evidence.edge is None
        assert evidence.significance is Significance.INSUFFICIENT


# ---------------------------------------------------------------------------
# Incomplete windows: excluded, never truncated
# ---------------------------------------------------------------------------


class TestIncompleteWindows:
    def test_sample_size_shrinks_as_horizon_grows(self) -> None:
        n = 100
        bars = _bars([100.0] * n)
        signal = _signal([True] * n, bars.index)

        evidence = compute_evidence(
            signal, bars, horizons=[1, 5, 20, 60], entry=Entry.NEXT_OPEN
        )
        sizes = [e.sample_size for e in evidence]

        # NEXT_OPEN: valid triggers are t <= n - 1 - horizon, i.e. exactly n - horizon of them.
        assert sizes == [99, 95, 80, 40]
        assert sizes == sorted(sizes, reverse=True)

    def test_horizon_longer_than_series_yields_no_sample(self) -> None:
        n = 10
        bars = _bars([100.0] * n)
        signal = _signal([True] * n, bars.index)

        [evidence] = compute_evidence(signal, bars, horizons=[60], entry=Entry.NEXT_OPEN)

        assert evidence.sample_size == 0
        assert evidence.hit_rate is None
        assert evidence.significance is Significance.INSUFFICIENT


# ---------------------------------------------------------------------------
# Boundary and degenerate inputs
# ---------------------------------------------------------------------------


class TestBoundaries:
    def test_empty_bars(self) -> None:
        bars = _empty_bars()
        signal = _signal([], bars.index)

        evidence = compute_evidence(signal, bars)

        assert len(evidence) == len(HORIZONS)
        for e in evidence:
            assert e.sample_size == 0
            assert e.independent_sample_size == 0
            assert e.hit_rate is None
            assert e.baseline_hit_rate is None
            assert e.significance is Significance.INSUFFICIENT

        state = rule_state(signal, bars)
        assert state == RuleState(
            state=TriState.UNKNOWN,
            as_of=None,
            last_trigger=None,
            bars_since_trigger=None,
            triggers_in_history=0,
        )

    def test_signal_never_fires(self) -> None:
        n = 60
        bars = _bars([100.0 + i * 0.2 for i in range(n)])
        signal = _signal([False] * n, bars.index)

        [evidence] = compute_evidence(signal, bars, horizons=[5], entry=Entry.NEXT_OPEN)
        assert evidence.sample_size == 0
        assert evidence.hit_rate is None
        assert evidence.median_return is None
        # The baseline is still measurable -- "never fires" is not "unmeasurable".
        assert evidence.baseline_hit_rate is not None

        state = rule_state(signal, bars)
        assert state.state is TriState.FALSE
        assert state.last_trigger is None
        assert state.bars_since_trigger is None
        assert state.triggers_in_history == 0

    def test_single_trigger_on_final_bar_has_no_next_open_window(self) -> None:
        """A trigger on the very last bar has no future at all under NEXT_OPEN: bar t+1 does not
        exist. SAME_CLOSE with horizon=1 is the one degenerate case where entry and exit coincide
        on that same last bar, so it alone yields a (trivially zero) sample."""
        n = 30
        bars = _bars([100.0] * n)
        signal = _signal([i == n - 1 for i in range(n)], bars.index)

        next_open = compute_evidence(signal, bars, horizons=[1, 5, 20], entry=Entry.NEXT_OPEN)
        assert [e.sample_size for e in next_open] == [0, 0, 0]

        same_close = compute_evidence(signal, bars, horizons=[1, 5], entry=Entry.SAME_CLOSE)
        assert same_close[0].sample_size == 1
        assert same_close[0].median_return == pytest.approx(0.0, abs=1e-9)
        assert same_close[1].sample_size == 0

    def test_zero_or_negative_entry_price_is_dropped_not_infinite(self) -> None:
        n = 20
        close = [100.0] * n
        opens = [100.0] * n
        opens[10] = 0.0  # a bad print: the NEXT_OPEN entry for trigger t=9 is unusable
        bars = _bars(close, opens=opens)
        signal = _signal([i == 9 for i in range(n)], bars.index)

        [evidence] = compute_evidence(signal, bars, horizons=[5], entry=Entry.NEXT_OPEN)

        assert evidence.sample_size == 0
        assert evidence.hit_rate is None
        assert evidence.median_return is None


# ---------------------------------------------------------------------------
# Alignment
# ---------------------------------------------------------------------------


class TestAlignment:
    def test_mismatched_index_raises_in_compute_evidence(self) -> None:
        bars = _bars([100.0, 101.0, 102.0, 103.0, 104.0])
        misaligned = pd.Series(
            [True, False, True, False, True],
            index=pd.RangeIndex(1, 6),
            dtype="boolean",
        )

        with pytest.raises(ValueError, match="index"):
            compute_evidence(misaligned, bars)

    def test_mismatched_index_raises_in_rule_state(self) -> None:
        bars = _bars([100.0, 101.0, 102.0])
        misaligned = pd.Series(
            [True, False, True], index=pd.RangeIndex(1, 4), dtype="boolean"
        )

        with pytest.raises(ValueError, match="index"):
            rule_state(misaligned, bars)

    def test_non_boolean_dtype_raises(self) -> None:
        bars = _bars([100.0, 101.0, 102.0])
        plain = pd.Series([True, False, True], index=bars.index)  # dtype: object/bool, not nullable

        with pytest.raises(TypeError, match="boolean"):
            compute_evidence(plain, bars)


# ---------------------------------------------------------------------------
# rule_state
# ---------------------------------------------------------------------------


class TestRuleState:
    def test_reports_current_state_and_last_trigger(self) -> None:
        n = 20
        bars = _bars([100.0 + i for i in range(n)])
        values: list[bool | None] = [False] * n
        values[5] = True
        values[12] = True
        values[-1] = False
        signal = _signal(values, bars.index)

        state = rule_state(signal, bars)

        assert state.state is TriState.FALSE
        assert state.as_of == bars["ts"].iloc[-1].date()
        assert state.last_trigger == bars["ts"].iloc[12].date()
        assert state.bars_since_trigger == (n - 1) - 12
        assert state.triggers_in_history == 2

    def test_current_bar_true_and_unknown(self) -> None:
        bars = _bars([100.0, 101.0, 102.0])
        signal_true = _signal([False, False, True], bars.index)
        assert rule_state(signal_true, bars).state is TriState.TRUE

        signal_unknown = _signal([False, False, None], bars.index)
        state_unknown = rule_state(signal_unknown, bars)
        assert state_unknown.state is TriState.UNKNOWN
        # A prior trigger is still visible even though the *current* state is unknown.
        signal_unknown_after_trigger = _signal([True, False, None], bars.index)
        state2 = rule_state(signal_unknown_after_trigger, bars)
        assert state2.state is TriState.UNKNOWN
        assert state2.last_trigger == bars["ts"].iloc[0].date()
        assert state2.bars_since_trigger == 2

    def test_never_triggered_last_trigger_is_none_not_a_stale_date(self) -> None:
        bars = _bars([100.0, 101.0, 102.0])
        signal = _signal([False, False, False], bars.index)

        state = rule_state(signal, bars)

        assert state.last_trigger is None
        assert state.bars_since_trigger is None
        assert state.triggers_in_history == 0

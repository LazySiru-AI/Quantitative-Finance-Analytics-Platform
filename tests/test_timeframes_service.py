"""Tests for :mod:`app.timeframes.stats` and :mod:`app.timeframes.service`.

The implementation (`backend/app/timeframes/{stats,service,models}.py`) already exists and is
verified working against real stored bars (see the module docstrings there); this file is the test
suite that was missing.

Every correctness test below builds its own bars/signal by hand -- either as an explicit
`pd.Series` (for the pure `stats.py` functions) or as a synthetic bar frame with a throwaway rule
expression (for `service.py`'s `compute_cells`/`aggregate`/`signal_trace`) -- so the exact answer
is known before the code runs, never inferred from what the code happens to produce. `read_frame`
is intercepted at `app.timeframes.service.read_frame` (the name that module imported directly, so
patching `app.market.store.read_frame` would not reach it) and `app.rules.catalog.get` is patched to
serve one extra throwaway rule alongside the real 11, so a test can invent a rule whose truth value
is fully under the test's control (`volume > 1500`, a raw price-field comparison with no indicator
warmup) without depending on the real catalog or on stored data.

The one exception is the `TestIntegrationRealData` class at the bottom, which deliberately reads the
real stored QQQ bars and skips cleanly if that data is absent.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

import numpy as np
import pandas as pd
import pytest

import app.rules.catalog as rule_catalog
import app.timeframes.service as service
from app.config import REPO_ROOT, get_settings
from app.db.duck import Interval
from app.rules.models import Rule
from app.timeframes.models import MIN_INDEPENDENT, RuleAccuracyCell, sector_of
from app.timeframes.stats import (
    benjamini_hochberg,
    independent_count,
    lift_ci,
    rising_edges,
    two_proportion_p,
    wilson_interval,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _bars(
    n: int,
    *,
    trigger_at: Sequence[int] = (),
    up_at: Sequence[int] = (),
    down_at: Sequence[int] = (),
    close_vals: Sequence[float] | None = None,
    start: dt.datetime = dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
    step: dt.timedelta = dt.timedelta(days=1),
) -> pd.DataFrame:
    """A minimal bar frame: flat at 100 (or `close_vals`) everywhere except where told otherwise.

    `trigger_at` bumps `volume` to 2000 (>1500) at those positions -- the throwaway rule this file
    uses is `"volume > 1500"`, deliberately independent of `open`/`close` so a test can control
    "when does the rule fire" and "what happens next" separately. `up_at`/`down_at` set that bar's
    own `close` to exactly `open + 1` / `open - 1`, which is what determines the *forward return* a
    horizon=1 trigger one bar earlier sees (see the module docstring on `forward_returns`: at
    horizon=1, `entry_idx == exit_idx == t + 1`, i.e. the return is bar `t+1`'s own candle).
    """
    ts = pd.to_datetime([start + step * i for i in range(n)], utc=True)
    if close_vals is not None:
        open_ = list(close_vals)
        close = list(close_vals)
    else:
        open_ = [100.0] * n
        close = [100.0] * n
    volume = [1000] * n
    for i in trigger_at:
        volume[i] = 2000
    for i in up_at:
        close[i] = open_[i] + 1.0
    for i in down_at:
        close[i] = open_[i] - 1.0
    return pd.DataFrame(
        {
            "ts": ts,
            "open": open_,
            "high": [c + 0.5 for c in close],
            "low": [c - 0.5 for c in close],
            "close": close,
            "adj_close": close,
            "volume": volume,
        }
    )


def _signal(values: Sequence[bool | None]) -> pd.Series:
    """A nullable `"boolean"` series with `None` mapped to `pd.NA` -- the unknown state."""
    return pd.Series(values, dtype="boolean")


_VOLUME_RULE_ID = "test_volume_trigger"
_VOLUME_RULE = Rule(rule_id=_VOLUME_RULE_ID, name="test volume trigger", expression="volume > 1500")


@pytest.fixture
def patch_bars(monkeypatch: pytest.MonkeyPatch):
    """Registers synthetic per-symbol bar frames, intercepted at the exact name `service.py` calls.

    `service.py` does `from app.market.store import read_frame`, a direct name import -- patching
    `app.market.store.read_frame` would leave that already-bound name in `service`'s own namespace
    untouched. Patching `service.read_frame` itself is the only interception point that actually
    reaches `_bars_for_pair` (used by both `compute_cells` and `aggregate`) and `signal_trace`.
    """
    store: dict[str, pd.DataFrame] = {}

    def fake_read_frame(symbol, interval, start=None, end=None, limit=None, settings=None):
        try:
            return store[symbol]
        except KeyError:
            raise AssertionError(f"no synthetic bars registered for symbol {symbol!r}") from None

    monkeypatch.setattr(service, "read_frame", fake_read_frame)

    def register(symbol: str, bars: pd.DataFrame) -> None:
        store[symbol] = bars

    return register


@pytest.fixture
def patch_rule(monkeypatch: pytest.MonkeyPatch):
    """Serves one extra throwaway `Rule` from `rule_catalog.get`, falling back to the real catalog
    for every other id -- so a test can invent a rule with a fully controlled truth value without
    disturbing (or depending on) the real 11-rule catalog."""
    extra: dict[str, Rule] = {}
    original_get = rule_catalog.get

    def fake_get(rule_id: str):
        if rule_id in extra:
            return extra[rule_id]
        return original_get(rule_id)

    monkeypatch.setattr(rule_catalog, "get", fake_get)

    def register(rule: Rule) -> None:
        extra[rule.rule_id] = rule

    return register


@pytest.fixture
def volume_rule(patch_rule) -> str:
    """The default throwaway rule (`"volume > 1500"`) registered and ready to use by id."""
    patch_rule(_VOLUME_RULE)
    return _VOLUME_RULE_ID


def _assert_cell_invariants(cell: RuleAccuracyCell) -> None:
    """The invariants `06-interface-contract.md` §2 requires of every cell -- already enforced by
    the model's own validator at construction time, re-asserted explicitly here as a regression
    guard independent of that validator."""
    assert cell.n_independent <= cell.n_episodes <= cell.n_raw
    assert cell.sufficient == (cell.n_independent >= MIN_INDEPENDENT)
    gated = (
        cell.hit_rate,
        cell.base_rate,
        cell.lift,
        cell.lift_ci_low,
        cell.lift_ci_high,
        cell.p_value,
        cell.q_value,
        cell.cost_adjusted_edge,
    )
    if not cell.sufficient:
        assert all(v is None for v in gated)
    if cell.hit_rate is not None and cell.base_rate is not None and cell.lift is not None:
        assert cell.lift == pytest.approx(cell.hit_rate - cell.base_rate, abs=1e-9)
    assert cell.warnings is not None


# ---------------------------------------------------------------------------
# 1. rising_edges
# ---------------------------------------------------------------------------


class TestRisingEdges:
    def test_400_consecutive_true_bars_is_exactly_one_episode(self) -> None:
        """The headline case: 400 consecutive firing bars under one persistent condition is one
        opportunity observed 400 times, not 400."""
        signal = _signal([True] * 400)
        edges = rising_edges(signal)

        assert int(edges.sum()) == 1
        assert bool(edges.iloc[0])
        assert not edges.iloc[1:].any()

    def test_na_to_true_is_an_edge(self) -> None:
        signal = _signal([None, None, True, True])
        edges = rising_edges(signal)
        assert edges.tolist() == [False, False, True, False]

    def test_false_to_true_is_an_edge(self) -> None:
        signal = _signal([False, True, False, True])
        edges = rising_edges(signal)
        assert edges.tolist() == [False, True, False, True]

    def test_true_to_true_is_not_an_edge(self) -> None:
        signal = _signal([True, True, True])
        edges = rising_edges(signal)
        assert edges.tolist() == [True, False, False]

    def test_all_false_has_no_edges(self) -> None:
        signal = _signal([False] * 10)
        edges = rising_edges(signal)
        assert not edges.any()

    def test_all_na_has_no_edges(self) -> None:
        signal = _signal([None] * 10)
        edges = rising_edges(signal)
        assert not edges.any()

    def test_all_true_has_exactly_one_edge_at_position_zero(self) -> None:
        signal = _signal([True] * 25)
        edges = rising_edges(signal)
        assert int(edges.sum()) == 1
        assert bool(edges.iloc[0])

    def test_empty_series(self) -> None:
        signal = _signal([])
        edges = rising_edges(signal)
        assert len(edges) == 0
        assert edges.dtype == bool

    def test_preserves_index(self) -> None:
        idx = pd.RangeIndex(5, 10)
        signal = pd.Series([False, True, True, False, True], index=idx, dtype="boolean")
        edges = rising_edges(signal)
        assert list(edges.index) == list(idx)


# ---------------------------------------------------------------------------
# 2. independent_count
# ---------------------------------------------------------------------------


class TestIndependentCount:
    def test_known_overlap_pattern_hand_computed(self) -> None:
        """Greedy scan from 0 with horizon=5: accept 0 (next_allowed=5); skip 3 (<5); accept 10
        (next_allowed=15); skip 11, 12 (<15); accept 30. Three survivors."""
        positions = np.array([0, 3, 10, 11, 12, 30])
        assert independent_count(positions, horizon_bars=5) == 3

    def test_episodes_closer_than_horizon_do_not_both_count(self) -> None:
        positions = np.array([0, 4])
        assert independent_count(positions, horizon_bars=5) == 1

    def test_episodes_exactly_horizon_apart_both_count(self) -> None:
        positions = np.array([0, 5])
        assert independent_count(positions, horizon_bars=5) == 2

    def test_empty_positions(self) -> None:
        assert independent_count(np.array([], dtype=int), horizon_bars=20) == 0

    def test_single_position(self) -> None:
        assert independent_count(np.array([7]), horizon_bars=20) == 1


# ---------------------------------------------------------------------------
# 3. wilson_interval
# ---------------------------------------------------------------------------


class TestWilsonInterval:
    def test_matches_published_value_50_of_100(self) -> None:
        """The textbook illustration of the Wilson interval (phat=0.5, n=100, 95%): approximately
        (0.404, 0.596) -- independently recomputed from the closed-form Wilson formula rather than
        by calling this module, to cross-check the implementation against the formula itself."""
        lo, hi = wilson_interval(50, 100)
        assert lo == pytest.approx(0.4038, abs=1e-4)
        assert hi == pytest.approx(0.5962, abs=1e-4)

    def test_matches_published_value_8_of_20(self) -> None:
        """A commonly-cited textbook example: 8/20 successes, 95% Wilson interval approximately
        (0.219, 0.613)."""
        lo, hi = wilson_interval(8, 20)
        assert lo == pytest.approx(0.2188, abs=1e-4)
        assert hi == pytest.approx(0.6134, abs=1e-4)

    def test_hits_zero_stays_within_0_1(self) -> None:
        """The normal approximation would collapse to a single point (or go negative) at phat=0;
        Wilson must not."""
        lo, hi = wilson_interval(0, 50)
        assert lo == pytest.approx(0.0, abs=1e-9)
        assert 0.0 <= hi <= 1.0
        assert hi == pytest.approx(0.0713, abs=1e-4)

    def test_hits_equals_n_stays_within_0_1(self) -> None:
        """The mirror case: phat=1 must not report a naive point interval either."""
        lo, hi = wilson_interval(50, 50)
        assert hi == pytest.approx(1.0, abs=1e-9)
        assert 0.0 <= lo <= 1.0
        assert lo == pytest.approx(0.9286, abs=1e-4)

    def test_n_zero_or_negative_returns_none(self) -> None:
        assert wilson_interval(0, 0) is None
        assert wilson_interval(0, -1) is None


# ---------------------------------------------------------------------------
# 4. benjamini_hochberg
# ---------------------------------------------------------------------------


class TestBenjaminiHochberg:
    def test_hand_computed_example_all_q_equal(self) -> None:
        """p = [0.01, 0.02, 0.03, 0.04, 0.05], m=5: q_(i) = p_(i) * 5 / i for every rank happens to
        equal exactly 0.05 for all five -- a clean, fully hand-computable case."""
        q = benjamini_hochberg([0.01, 0.02, 0.03, 0.04, 0.05], alpha=0.05)
        assert q == [pytest.approx(0.05, abs=1e-9)] * 5

    def test_ties_none_passthrough_and_unsorted_order(self) -> None:
        """Unsorted input, a tie (two p=0.01's), and a `None` (an insufficient cell that never had
        a p-value) mixed in. Hand-computed: sorted family is
        [(2,0.01),(3,0.01),(5,0.04),(0,0.20),(4,0.50)], m=5, running-min step-up from rank 5 down
        gives q = [0.5, 0.25, 0.0667, 0.025, 0.025] at ranks [5,4,3,2,1] -- mapped back to original
        positions: index0->0.25, index2->0.025, index3->0.025, index4->0.5, index5->0.0667,
        index1 (was None) stays None.
        """
        pvals = [0.20, None, 0.01, 0.01, 0.50, 0.04]
        q = benjamini_hochberg(pvals, alpha=0.10)

        assert q[1] is None
        assert q[0] == pytest.approx(0.25, abs=1e-6)
        assert q[2] == pytest.approx(0.025, abs=1e-6)
        assert q[3] == pytest.approx(0.025, abs=1e-6)
        assert q[4] == pytest.approx(0.50, abs=1e-6)
        assert q[5] == pytest.approx(0.0667, abs=1e-3)
        # Ties share the same q-value regardless of input order.
        assert q[2] == q[3]

    def test_order_preserving_same_length_and_position_as_input(self) -> None:
        pvals = [0.30, 0.01, None, 0.10]
        q = benjamini_hochberg(pvals, alpha=0.10)
        assert len(q) == len(pvals)
        assert q[2] is None

    def test_monotone_non_decreasing_in_p_value(self) -> None:
        pvals = [0.20, 0.01, 0.01, 0.50, 0.04]
        q = benjamini_hochberg(pvals, alpha=0.10)
        pairs = sorted(zip(pvals, q, strict=True), key=lambda pair: pair[0])
        q_in_p_order = [item[1] for item in pairs]
        assert q_in_p_order == sorted(q_in_p_order)

    def test_never_returns_q_less_than_p(self) -> None:
        pvals = [0.20, None, 0.01, 0.01, 0.50, 0.04]
        q = benjamini_hochberg(pvals, alpha=0.10)
        for p, qi in zip(pvals, q, strict=True):
            if p is not None:
                assert qi >= p - 1e-9

    def test_empty_input(self) -> None:
        assert benjamini_hochberg([], alpha=0.10) == []

    def test_all_none_input(self) -> None:
        assert benjamini_hochberg([None, None, None], alpha=0.10) == [None, None, None]


# ---------------------------------------------------------------------------
# 5. two_proportion_p
# ---------------------------------------------------------------------------


class TestTwoProportionP:
    def test_identical_proportions_gives_high_p(self) -> None:
        p = two_proportion_p(500, 1000, 500, 1000)
        assert p == pytest.approx(1.0, abs=1e-9)

    def test_wildly_different_proportions_with_large_n_gives_small_p(self) -> None:
        p = two_proportion_p(900, 1000, 100, 1000)
        assert p is not None
        assert p < 1e-6

    def test_empty_sample_returns_none(self) -> None:
        assert two_proportion_p(0, 0, 5, 10) is None
        assert two_proportion_p(5, 10, 0, 0) is None

    def test_degenerate_equal_extreme_proportions_returns_one_not_none(self) -> None:
        """Both samples all-hit (or both all-miss): pooled variance is zero, but two equal extreme
        proportions is 'no detectable difference', not 'no data' -- must return 1.0, not None or
        NaN."""
        p = two_proportion_p(10, 10, 20, 20)
        assert p == 1.0


# ---------------------------------------------------------------------------
# 6. lift_ci
# ---------------------------------------------------------------------------


class TestLiftCI:
    def test_brackets_the_point_estimate(self) -> None:
        hits_rule, n_rule = 60, 100
        hits_base, n_base = 50, 100
        lift = hits_rule / n_rule - hits_base / n_base
        ci = lift_ci(hits_rule, n_rule, hits_base, n_base)
        assert ci is not None
        lo, hi = ci
        assert lo <= lift <= hi

    def test_widens_as_n_shrinks(self) -> None:
        """Identical proportions (60% vs 50%), one pair measured at n=10 and the same pair at
        n=1000: the small-sample interval must be markedly wider."""
        small = lift_ci(6, 10, 5, 10)
        large = lift_ci(600, 1000, 500, 1000)
        assert small is not None
        assert large is not None
        small_width = small[1] - small[0]
        large_width = large[1] - large[0]
        assert small_width > large_width
        # Not just "wider" -- an order of magnitude wider, so this is a real discriminating check.
        assert small_width > large_width * 3

    def test_empty_sample_returns_none(self) -> None:
        assert lift_ci(0, 0, 5, 10) is None
        assert lift_ci(5, 10, 0, 0) is None


# ---------------------------------------------------------------------------
# 7. compute_cells on synthetic bars -- exact hit rate / base rate / lift
# ---------------------------------------------------------------------------


class TestComputeCellsSyntheticTruth:
    def test_exact_hit_rate_base_rate_and_lift(self, patch_bars, volume_rule) -> None:
        """25 isolated single-bar triggers (`volume > 1500`), spaced 4 bars apart -- far enough
        apart that horizon=1's non-overlap scan keeps all 25 as independent. Each trigger's
        horizon=1 forward return is exactly the *next* bar's own candle (see `_bars`'s docstring):
        15 of the 25 are set to a +1% up candle (hits), 10 to a flat/negative outcome (misses).

        Hand-computed: n_rule = 25, hits_rule = 15 -> hit_rate = 0.6 exactly.
        Every evaluable baseline bar is one of the 100 positions t=0..99 (bar 100 has no horizon=1
        window); of those, only the 25 outcome bars (positions 1,5,...,97) have a nonzero return,
        and 15 of those 25 are positive -> base_rate = 15/100 = 0.15 exactly.
        lift = 0.6 - 0.15 = 0.45 exactly.
        """
        n = 101
        trig = list(range(0, 100, 4))
        assert len(trig) == 25
        outcomes = [t + 1 for t in trig]
        up_outcomes = outcomes[:15]
        down_outcomes = outcomes[15:]
        bars = _bars(n, trigger_at=trig, up_at=up_outcomes, down_at=down_outcomes)
        patch_bars("SYN", bars)

        [cell] = service.compute_cells(
            symbols=["SYN"],
            intervals=[Interval.DAY],
            rule_ids=[volume_rule],
            horizons=[1],
            settings=get_settings(),
        )

        assert cell.n_raw == 25
        assert cell.n_episodes == 25
        assert cell.n_independent == 25
        assert cell.sufficient is True
        assert cell.hit_rate == pytest.approx(0.6, abs=1e-9)
        assert cell.base_rate == pytest.approx(0.15, abs=1e-9)
        assert cell.lift == pytest.approx(0.45, abs=1e-9)
        assert cell.median_return == pytest.approx(0.01, abs=1e-9)
        assert cell.baseline_median_return == pytest.approx(0.0, abs=1e-9)
        _assert_cell_invariants(cell)


# ---------------------------------------------------------------------------
# 8. The sufficiency gate
# ---------------------------------------------------------------------------


class TestSufficiencyGate:
    def test_below_min_independent_carries_none_everywhere_and_does_not_raise(
        self, patch_bars, volume_rule
    ) -> None:
        """5 isolated, well-separated triggers -- comfortably below MIN_INDEPENDENT=20. The cell
        must come back with `sufficient=False` and `None` in every statistic, and the call itself
        must not raise (the model's own validator would reject an insufficient cell carrying a
        number, so a non-raising result already proves the gate held -- this asserts the specific
        shape besides)."""
        n = 20
        trig = [0, 3, 6, 9, 12]
        outcomes = [t + 1 for t in trig]
        bars = _bars(n, trigger_at=trig, up_at=outcomes)
        patch_bars("FEWTRIG", bars)

        [cell] = service.compute_cells(
            symbols=["FEWTRIG"],
            intervals=[Interval.DAY],
            rule_ids=[volume_rule],
            horizons=[1],
            settings=get_settings(),
        )

        assert cell.n_independent == 5
        assert cell.n_independent < MIN_INDEPENDENT
        assert cell.sufficient is False
        for field in (
            "hit_rate",
            "base_rate",
            "lift",
            "lift_ci_low",
            "lift_ci_high",
            "median_return",
            "baseline_median_return",
            "p_value",
            "q_value",
            "cost_adjusted_edge",
        ):
            assert getattr(cell, field) is None, f"{field} should be None on an insufficient cell"


# ---------------------------------------------------------------------------
# 9 & 10. aggregate: pools counts (Simpson's-paradox guard), sector/universe scoping
# ---------------------------------------------------------------------------


def _stub_symbol_cell(rule_id: str, symbol: str) -> RuleAccuracyCell:
    """A minimal, individually-insufficient symbol-scope cell -- `aggregate` only reads its
    grouping keys (`rule_id`, `interval`, `horizon_bars`, `regime`, `scope_key`) and a couple of
    passthrough fields (`cost_bps_assumed`, `warnings`); it recomputes every real number itself
    from stored bars (see `aggregate`'s own docstring on why). `sufficient=False` here is what lets
    every gated field stay `None`, which the model's validator requires."""
    now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    return RuleAccuracyCell(
        rule_id=rule_id,
        interval=Interval.DAY,
        scope="symbol",
        scope_key=symbol,
        horizon_bars=1,
        horizon_minutes=390,
        horizon_label="~1 day",
        n_raw=0,
        n_episodes=0,
        n_independent=0,
        sufficient=False,
        regime="all",
        first_bar=now,
        last_bar=now,
        warnings=(),
    )


class TestAggregatePoolsCountsNotRates:
    def test_pooled_hit_rate_differs_sharply_from_the_mean_of_per_symbol_rates(
        self, patch_bars, volume_rule
    ) -> None:
        """The Simpson's-paradox guard, made numerically unmissable.

        Symbol A: 5 independent episodes, ALL hits -> per-symbol hit_rate = 1.0.
        Symbol B: 45 independent episodes, 9 hits -> per-symbol hit_rate = 0.2.

        A naive average-of-rates would report (1.0 + 0.2) / 2 = 0.6. Pooling the underlying counts
        (5 hits + 9 hits) / (5 + 45 episodes) = 14 / 50 = 0.28 instead -- 0.32 away from the naive
        average, which is the whole point: the rare-but-perfect symbol must not be allowed to drag
        the pooled number toward its own tiny sample.
        """
        n_a = 20
        trig_a = [0, 3, 6, 9, 12]
        out_a = [t + 1 for t in trig_a]
        bars_a = _bars(n_a, trigger_at=trig_a, up_at=out_a)  # 5/5 hits

        n_b = 140
        trig_b = list(range(0, 3 * 45, 3))
        assert len(trig_b) == 45
        out_b = [t + 1 for t in trig_b]
        up_b = out_b[:9]
        down_b = out_b[9:]
        bars_b = _bars(n_b, trigger_at=trig_b, up_at=up_b, down_at=down_b)  # 9/45 hits

        patch_bars("SIMPA", bars_a)
        patch_bars("SIMPB", bars_b)

        cells_in = [
            _stub_symbol_cell(volume_rule, "SIMPA"),
            _stub_symbol_cell(volume_rule, "SIMPB"),
        ]
        [pooled] = service.aggregate(cells_in, to="universe")

        naive_mean_of_rates = (1.0 + (9 / 45)) / 2  # 0.6
        assert pooled.n_independent == 50
        assert pooled.sufficient is True
        assert pooled.hit_rate == pytest.approx(14 / 50, abs=1e-9)
        assert pooled.hit_rate == pytest.approx(0.28, abs=1e-9)
        assert abs(pooled.hit_rate - naive_mean_of_rates) > 0.2
        _assert_cell_invariants(pooled)

    def test_aggregate_to_sector_uses_sector_of_and_excludes_non_universe_symbols(
        self, patch_bars, volume_rule
    ) -> None:
        """AAPL and MSFT are both 'Technology' in RESEARCH_UNIVERSE; a symbol absent from the
        universe entirely (no sector label at all) must be silently excluded from a sector rollup,
        not raise and not contribute its episodes to the pooled count."""
        assert sector_of("AAPL") == "Technology"
        assert sector_of("MSFT") == "Technology"
        assert sector_of("ZZZZNOTINUNIVERSE") is None

        n = 20
        trig = [0, 3, 6, 9, 12]
        out = [t + 1 for t in trig]
        bars_aapl = _bars(n, trigger_at=trig, up_at=out)  # 5 episodes
        bars_msft = _bars(n, trigger_at=trig, down_at=out)  # 5 episodes
        bars_outside = _bars(n, trigger_at=trig, up_at=out)  # must be excluded

        patch_bars("AAPL", bars_aapl)
        patch_bars("MSFT", bars_msft)
        patch_bars("ZZZZNOTINUNIVERSE", bars_outside)

        cells_in = [
            _stub_symbol_cell(volume_rule, "AAPL"),
            _stub_symbol_cell(volume_rule, "MSFT"),
            _stub_symbol_cell(volume_rule, "ZZZZNOTINUNIVERSE"),
        ]
        [sector_cell] = service.aggregate(cells_in, to="sector")

        assert sector_cell.scope == "sector"
        assert sector_cell.scope_key == "Technology"
        # 5 (AAPL) + 5 (MSFT) = 10 -- the excluded symbol's 5 episodes must not be in this total.
        assert sector_cell.n_independent == 10
        _assert_cell_invariants(sector_cell)

    def test_aggregate_to_universe_covers_symbols_outside_the_research_universe(
        self, patch_bars, volume_rule
    ) -> None:
        """Unlike `to="sector"`, `to="universe"` has no sector-membership requirement -- any
        symbol-scope cell handed in is pooled."""
        assert sector_of("NOTINUNIVERSEEITHER") is None

        n = 20
        trig = [0, 3, 6, 9, 12]
        out = [t + 1 for t in trig]
        bars = _bars(n, trigger_at=trig, up_at=out)
        patch_bars("NOTINUNIVERSEEITHER", bars)

        [pooled] = service.aggregate(
            [_stub_symbol_cell(volume_rule, "NOTINUNIVERSEEITHER")], to="universe"
        )
        assert pooled.n_independent == 5
        assert pooled.scope == "universe"
        assert pooled.scope_key == "ALL"


# ---------------------------------------------------------------------------
# 11. signal_trace
# ---------------------------------------------------------------------------


_SMA_RULE_ID = "test_sma_rule"
_SMA_RULE = Rule(rule_id=_SMA_RULE_ID, name="test sma rule", expression="close > sma(5)")


class TestSignalTrace:
    def test_fired_at_is_rising_edges_only_and_ascending(self, patch_bars, patch_rule) -> None:
        """close is flat at 100 for 10 bars, steps up to 105 for 5 bars, then down to 95 for 5.
        `close > sma(5)` (warmup=4) turns True once at the step-up (bar index 10) and stays True
        for a few bars before the rolling average catches up -- exactly one rising edge, not one
        marker per True bar."""
        patch_rule(_SMA_RULE)
        close = [100.0] * 10 + [105.0] * 5 + [95.0] * 5
        bars = _bars(20, close_vals=close)
        patch_bars("SYN", bars)

        trace = service.signal_trace(
            symbol="SYN", interval=Interval.DAY, rule_id=_SMA_RULE_ID, settings=get_settings()
        )

        assert len(trace.fired_at) == 1
        assert trace.fired_at == sorted(trace.fired_at)
        assert trace.fired_at[0] == bars["ts"].iloc[10].to_pydatetime()

    def test_warmup_until_is_the_first_bar_the_signal_is_known_on(
        self, patch_bars, patch_rule
    ) -> None:
        patch_rule(_SMA_RULE)
        close = [100.0 + i for i in range(20)]
        bars = _bars(20, close_vals=close)
        patch_bars("SYN", bars)

        trace = service.signal_trace(
            symbol="SYN", interval=Interval.DAY, rule_id=_SMA_RULE_ID, settings=get_settings()
        )

        # sma(5) has warmup = period - 1 = 4 -> the first known bar is index 4.
        assert trace.warmup_until == bars["ts"].iloc[4].to_pydatetime()

    def test_indicators_relate_to_the_rules_expression(self, patch_bars, patch_rule) -> None:
        patch_rule(_SMA_RULE)
        close = [100.0 + i for i in range(20)]
        bars = _bars(20, close_vals=close)
        patch_bars("SYN", bars)

        trace = service.signal_trace(
            symbol="SYN", interval=Interval.DAY, rule_id=_SMA_RULE_ID, settings=get_settings()
        )

        assert len(trace.indicators) == 1
        [series] = trace.indicators
        assert series.name == "sma"
        assert "sma_5" in series.columns
        assert series.warmup == 4
        assert trace.expression == "close > sma(5)"


# ---------------------------------------------------------------------------
# 12. Integration against real stored bars -- skip cleanly if the data is absent
# ---------------------------------------------------------------------------

_QQQ_HOURLY_PARQUET = REPO_ROOT / "data" / "store" / "bars" / "interval=1h" / "symbol=QQQ" / "bars.parquet"
requires_real_qqq_hourly = pytest.mark.skipif(
    not _QQQ_HOURLY_PARQUET.exists(),
    reason="real stored QQQ 1h bars not present (data/ is gitignored)",
)


class TestIntegrationRealData:
    @requires_real_qqq_hourly
    def test_compute_cells_on_real_qqq_hourly_bars_is_well_formed(self) -> None:
        cells = service.compute_cells(
            symbols=["QQQ"], intervals=[Interval.HOUR], settings=get_settings()
        )
        assert len(cells) > 0
        assert any(cell.sufficient for cell in cells)
        for cell in cells:
            _assert_cell_invariants(cell)

    @requires_real_qqq_hourly
    def test_every_cell_satisfies_model_invariants(self) -> None:
        cells = service.compute_cells(
            symbols=["QQQ"], intervals=[Interval.HOUR], settings=get_settings()
        )
        for cell in cells:
            # RuleAccuracyCell is frozen and already validated at construction; this loop is a
            # belt-and-suspenders re-check of the exact invariants the interface contract names.
            assert cell.n_independent <= cell.n_episodes <= cell.n_raw
            if not cell.sufficient:
                assert cell.hit_rate is None
                assert cell.lift is None
            assert isinstance(cell.warnings, tuple)

    def test_interval_with_no_stored_data_degrades_gracefully_not_raise(self) -> None:
        """A symbol/interval pair absent from the store entirely must come back as an empty result
        (the pair is silently skipped by `_bars_for_pair` returning `None`), never a raised
        exception -- this does not depend on any real data being present, so it is not skipped."""
        cells = service.compute_cells(
            symbols=["ZZZZ_NO_SUCH_SYMBOL_ANYWHERE"],
            intervals=[Interval.DAY],
            settings=get_settings(),
        )
        assert cells == []

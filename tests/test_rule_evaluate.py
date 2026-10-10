"""Tests for the rule evaluator (:mod:`app.rules.evaluate`).

Trees are built by constructing :mod:`app.rules.nodes` dataclasses directly, never by parsing a rule
string -- the grammar module is written by another agent in parallel and these tests must not depend
on it existing or being correct.

Every numeric assertion is checked against a value worked out independently of the module under
test (a hand-picked series where the answer is obvious, or an assertion about the *shape* of the
result -- NA vs. True vs. False -- rather than feeding the module's own output back through itself).
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence

import pandas as pd
import pytest

from app.indicators import registry as indicator_registry
from app.market.models import BAR_COLUMNS, Interval
from app.rules.evaluate import (
    IndicatorCache,
    IndicatorCacheError,
    RuleEvaluationError,
    evaluate,
    evaluate_num,
    required_specs,
)
from app.rules.nodes import (
    Arith,
    ArithOp,
    BoolExpr,
    BoolOp,
    BoolOpKind,
    CompareOp,
    Comparison,
    Cross,
    CrossDir,
    IndicatorRef,
    Literal,
    Not,
    PriceField,
    PriceRef,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _bars(
    *,
    close: Sequence[float],
    open_: Sequence[float] | None = None,
    high: Sequence[float] | None = None,
    low: Sequence[float] | None = None,
    volume: Sequence[float | None] | None = None,
    start: dt.datetime = dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
    step: dt.timedelta = dt.timedelta(days=1),
) -> pd.DataFrame:
    """A minimal bar frame with real UTC timestamps and a default RangeIndex."""
    n = len(close)
    open_v = list(open_) if open_ is not None else list(close)
    high_v = list(high) if high is not None else [c + 0.5 for c in close]
    low_v = list(low) if low is not None else [c - 0.5 for c in close]
    volume_v = list(volume) if volume is not None else [1_000.0] * n
    ts = pd.to_datetime([start + step * i for i in range(n)], utc=True)
    return pd.DataFrame(
        {
            "ts": ts,
            "open": open_v,
            "high": high_v,
            "low": low_v,
            "close": close,
            "adj_close": close,
            "volume": volume_v,
        }
    )


def _empty_bars() -> pd.DataFrame:
    return pd.DataFrame(columns=list(BAR_COLUMNS))


def _is_na(value: object) -> bool:
    return bool(pd.isna(value))


_CLOSE = PriceRef(PriceField.CLOSE)
_OPEN = PriceRef(PriceField.OPEN)
_VOLUME = PriceRef(PriceField.VOLUME)


# ---------------------------------------------------------------------------
# Kleene logic: the six cases the module's docstring calls out explicitly
# ---------------------------------------------------------------------------


class TestKleeneLogic:
    """Each of the six truth-table cases the task calls out, driven through `evaluate`.

    Two independent comparisons on the same bars: `unknown` is always NA (its input, `close`, is
    NaN on every row here), `known` is true on row 0 and false on row 1. Combining them exercises
    `NA and True`, `NA and False`, `NA or True`, `NA or False` from just two bars, plus `not NA`.
    """

    _bars = _bars(close=[float("nan"), float("nan")], open_=[1.0, -1.0])
    _unknown = Comparison(_CLOSE, CompareOp.GT, Literal(0.0))
    _known = Comparison(_OPEN, CompareOp.GT, Literal(0.0))

    def _eval(self, node: BoolExpr) -> pd.Series:
        return evaluate(node, self._bars, interval=Interval.DAY)

    def test_unknown_itself_is_na_not_false(self) -> None:
        result = self._eval(self._unknown)
        assert result.dtype == "boolean"
        assert _is_na(result.iloc[0])
        assert _is_na(result.iloc[1])

    def test_known_is_true_then_false(self) -> None:
        result = self._eval(self._known)
        assert result.iloc[0]
        assert not result.iloc[1]

    def test_na_and_true_is_na(self) -> None:
        result = self._eval(BoolOp(BoolOpKind.AND, (self._unknown, self._known)))
        assert _is_na(result.iloc[0])  # known=True on row 0

    def test_na_and_false_is_false(self) -> None:
        """The denominator-inflation footgun: NA must not survive when the other side is false."""
        result = self._eval(BoolOp(BoolOpKind.AND, (self._unknown, self._known)))
        assert not result.iloc[1]  # known=False on row 1

    def test_na_or_true_is_true(self) -> None:
        result = self._eval(BoolOp(BoolOpKind.OR, (self._unknown, self._known)))
        assert result.iloc[0]  # known=True on row 0

    def test_na_or_false_is_na(self) -> None:
        result = self._eval(BoolOp(BoolOpKind.OR, (self._unknown, self._known)))
        assert _is_na(result.iloc[1])  # known=False on row 1

    def test_not_na_is_na(self) -> None:
        result = self._eval(Not(self._unknown))
        assert _is_na(result.iloc[0])
        assert _is_na(result.iloc[1])

    def test_comparison_with_nan_operand_is_na_never_false(self) -> None:
        """The crux requirement: `NaN < 30` must not silently become `False`."""
        bars = _bars(close=[10.0, float("nan"), 50.0])
        node = Comparison(_CLOSE, CompareOp.LT, Literal(30.0))
        result = evaluate(node, bars, interval=Interval.DAY)
        assert result.iloc[0]
        assert _is_na(result.iloc[1])
        assert not result.iloc[2]


# ---------------------------------------------------------------------------
# Cross: transition-only, never a negative shift
# ---------------------------------------------------------------------------


class TestCross:
    """`a crosses_above b` fires only on the transition bar; the first bar is always NA."""

    def test_crosses_above_fires_once_on_the_transition_bar(self) -> None:
        # left goes below -> below -> above -> above; right is flat.
        bars = _bars(close=[5.0, 8.0, 15.0, 20.0], open_=[10.0, 10.0, 10.0, 10.0])
        node = Cross(_CLOSE, CrossDir.ABOVE, _OPEN)
        result = evaluate(node, bars, interval=Interval.DAY)

        assert _is_na(result.iloc[0]), "first bar has no predecessor -- must be NA, not False"
        assert not result.iloc[1]  # still below, no cross
        assert result.iloc[2]  # the transition bar
        # This is the bar a `.shift(-1)` bug would get wrong: a naive negative shift would compare
        # against bar 4 (which does not exist) rather than bar 2, producing NA here instead of the
        # correct definite False.
        assert not result.iloc[3], "already above -- must not repeat the earlier cross"

    def test_crosses_below_is_the_mirror_image(self) -> None:
        bars = _bars(close=[20.0, 15.0, 8.0, 5.0], open_=[10.0, 10.0, 10.0, 10.0])
        node = Cross(_CLOSE, CrossDir.BELOW, _OPEN)
        result = evaluate(node, bars, interval=Interval.DAY)

        assert _is_na(result.iloc[0])
        assert not result.iloc[1]  # still above
        assert result.iloc[2]  # transition
        assert not result.iloc[3]  # already below, no repeat

    def test_never_true_for_the_duration_of_a_trend(self) -> None:
        """A long trend must fire exactly once, not for every bar it remains above."""
        # index0: 5 < 10 (below). index1: 10 == 10 (not strictly above -- no cross yet).
        # index2: 11 > 10 -- the one transition. index3..10: stays above, must not repeat.
        bars = _bars(close=[5.0] + [10.0 + i for i in range(10)], open_=[10.0] * 11)
        node = Cross(_CLOSE, CrossDir.ABOVE, _OPEN)
        result = evaluate(node, bars, interval=Interval.DAY)
        true_positions = [i for i, v in enumerate(result) if not _is_na(v) and bool(v)]
        assert true_positions == [2]

    def test_single_bar_is_na(self) -> None:
        bars = _bars(close=[15.0], open_=[10.0])
        node = Cross(_CLOSE, CrossDir.ABOVE, _OPEN)
        result = evaluate(node, bars, interval=Interval.DAY)
        assert len(result) == 1
        assert _is_na(result.iloc[0])

    def test_gap_in_history_propagates_as_na_not_false(self) -> None:
        """A NaN mid-series (not the structural first-bar case) still yields NA via masking."""
        bars = _bars(close=[5.0, float("nan"), 15.0, 20.0], open_=[10.0, 10.0, 10.0, 10.0])
        node = Cross(_CLOSE, CrossDir.ABOVE, _OPEN)
        result = evaluate(node, bars, interval=Interval.DAY)
        assert _is_na(result.iloc[0])  # first bar
        assert _is_na(result.iloc[1])  # close itself missing
        assert _is_na(result.iloc[2]), "previous bar's close was missing -- unknown, not False"
        assert not result.iloc[3]  # already above by bar 2 (whatever it was), no new cross


# ---------------------------------------------------------------------------
# No lookahead: table-driven truncation property
# ---------------------------------------------------------------------------


def _lookahead_bars(n: int = 40) -> pd.DataFrame:
    close = [100 + 5 * math.sin(i / 4) + 0.2 * i for i in range(n)]
    open_ = [c - 0.3 for c in close]
    close[22] = float("nan")  # a gap mid-series, so truncation is exercised across a hole too
    return _bars(close=close, open_=open_)


_RSI14 = IndicatorRef(name="rsi", args=(14.0,))
_BB_UPPER = IndicatorRef(name="bb", args=(20.0, 2.0), output="upper")
_BB_LOWER = IndicatorRef(name="bb", args=(20.0, 2.0), output="lower")

_LOOKAHEAD_RULES: list[tuple[str, BoolExpr]] = [
    ("lt", Comparison(_CLOSE, CompareOp.LT, Literal(100.0))),
    ("lte", Comparison(_CLOSE, CompareOp.LTE, Literal(100.0))),
    ("gt", Comparison(_CLOSE, CompareOp.GT, Literal(100.0))),
    ("gte", Comparison(_CLOSE, CompareOp.GTE, Literal(100.0))),
    ("eq", Comparison(_RSI14, CompareOp.EQ, Literal(50.0))),
    ("neq", Comparison(_RSI14, CompareOp.NEQ, Literal(50.0))),
    ("cross_above", Cross(_CLOSE, CrossDir.ABOVE, _OPEN)),
    ("cross_below", Cross(_CLOSE, CrossDir.BELOW, _OPEN)),
    ("arith_div", Comparison(Arith(_CLOSE, ArithOp.DIV, _OPEN), CompareOp.GT, Literal(1.0))),
    ("arith_sub_bb", Comparison(Arith(_BB_UPPER, ArithOp.SUB, _BB_LOWER), CompareOp.GT, Literal(0.0))),
    ("not", Not(Comparison(_RSI14, CompareOp.LT, Literal(30.0)))),
    (
        "and",
        BoolOp(
            BoolOpKind.AND,
            (
                Comparison(_CLOSE, CompareOp.GT, Literal(90.0)),
                Comparison(_RSI14, CompareOp.LT, Literal(70.0)),
            ),
        ),
    ),
    (
        "or",
        BoolOp(
            BoolOpKind.OR,
            (
                Comparison(_CLOSE, CompareOp.LT, Literal(10.0)),
                Cross(_RSI14, CrossDir.ABOVE, Literal(50.0)),
            ),
        ),
    ),
]

_CHECKPOINTS = [0, 1, 2, 5, 13, 14, 19, 22, 25, 39]


@pytest.mark.parametrize("name,node", _LOOKAHEAD_RULES, ids=[r[0] for r in _LOOKAHEAD_RULES])
def test_no_lookahead(name: str, node: BoolExpr) -> None:
    """A rule's value at bar `t` may depend only on bars `<= t`.

    Evaluated once on the full series and once on the series truncated at each checkpoint `k`; the
    values at every bar `<= k` must be identical between the two runs. This single property, applied
    across every operator, catches an entire class of bugs (a stray `.shift(-1)`, a centred rolling
    window, an indicator that peeks past its own input) without needing a bug-specific test for each.
    """
    bars = _lookahead_bars()
    full = evaluate(node, bars, interval=Interval.DAY)

    for k in _CHECKPOINTS:
        truncated_bars = bars.iloc[: k + 1]
        truncated = evaluate(node, truncated_bars, interval=Interval.DAY)
        for i in range(k + 1):
            full_val = full.iloc[i]
            trunc_val = truncated.iloc[i]
            if _is_na(full_val):
                assert _is_na(trunc_val), f"{name}: bar {i} (checkpoint {k}) NA in full, not truncated"
            else:
                assert not _is_na(trunc_val), f"{name}: bar {i} (checkpoint {k}) NA in truncated, not full"
                assert full_val == trunc_val, f"{name}: bar {i} (checkpoint {k}) differs: {full_val} vs {trunc_val}"


# ---------------------------------------------------------------------------
# Arithmetic: division by zero must yield NA, not inf
# ---------------------------------------------------------------------------


class TestArith:
    def test_division_by_zero_is_na_not_inf(self) -> None:
        """`inf` compares as an ordinary number and would silently satisfy `> anything`."""
        bars = _bars(close=[1.0] * 4, volume=[2.0, 0.0, -0.0, 5.0])
        node = Comparison(
            Arith(Literal(1.0), ArithOp.DIV, _VOLUME), CompareOp.GT, Literal(-1_000_000.0)
        )
        result = evaluate(node, bars, interval=Interval.DAY)
        assert result.iloc[0]
        assert _is_na(result.iloc[1]), "1/0 must not surface as a comparable inf"
        assert _is_na(result.iloc[2]), "1/-0.0 must not surface as a comparable -inf"
        assert result.iloc[3]

    def test_division_by_nan_is_na(self) -> None:
        bars = _bars(close=[1.0, 1.0], volume=[float("nan"), 2.0])
        node = Comparison(Arith(_CLOSE, ArithOp.DIV, _VOLUME), CompareOp.GT, Literal(-1.0))
        result = evaluate(node, bars, interval=Interval.DAY)
        assert _is_na(result.iloc[0])
        assert result.iloc[1]

    def test_add_sub_mul_are_ordinary_arithmetic(self) -> None:
        bars = _bars(close=[10.0, 20.0])
        add = Comparison(Arith(_CLOSE, ArithOp.ADD, Literal(5.0)), CompareOp.EQ, Literal(15.0))
        sub = Comparison(Arith(_CLOSE, ArithOp.SUB, Literal(5.0)), CompareOp.EQ, Literal(5.0))
        mul = Comparison(Arith(_CLOSE, ArithOp.MUL, Literal(2.0)), CompareOp.EQ, Literal(20.0))
        assert evaluate(add, bars, interval=Interval.DAY).iloc[0]
        assert evaluate(sub, bars, interval=Interval.DAY).iloc[0]
        assert evaluate(mul, bars, interval=Interval.DAY).iloc[0]

    def test_bb_band_width_computed_from_two_outputs_of_one_indicator(self) -> None:
        """`bb_upper(20,2) - bb_lower(20,2)`: exercises both an `Arith` and multi-output resolution."""
        closes = [100 + 5 * math.sin(i / 3) for i in range(30)]
        bars = _bars(close=closes)
        node = Comparison(Arith(_BB_UPPER, ArithOp.SUB, _BB_LOWER), CompareOp.GT, Literal(0.0))
        result = evaluate(node, bars, interval=Interval.DAY)
        assert result.iloc[:19].isna().all()  # bb warmup: period - 1 == 19
        assert result.iloc[19:].eq(True).all()  # band width is always positive once settled


# ---------------------------------------------------------------------------
# Warmup and gaps
# ---------------------------------------------------------------------------


class TestWarmupAndGaps:
    def test_indicator_warmup_is_na_not_false(self) -> None:
        closes = [100 + i * 0.3 for i in range(20)]
        bars = _bars(close=closes)
        node = Comparison(_RSI14, CompareOp.LT, Literal(30.0))
        result = evaluate(node, bars, interval=Interval.DAY)
        assert result.iloc[:14].isna().all(), "rsi(14)'s warmup is 14 bars"
        assert not result.iloc[14:].isna().any()

    def test_nan_hole_mid_series_is_na_only_there(self) -> None:
        closes = [10.0, 20.0, 30.0, float("nan"), 50.0, 60.0]
        bars = _bars(close=closes)
        node = Comparison(_CLOSE, CompareOp.GT, Literal(25.0))
        result = evaluate(node, bars, interval=Interval.DAY)
        expected = [False, False, True, None, True, True]
        for got, want in zip(result, expected, strict=True):
            if want is None:
                assert _is_na(got)
            else:
                assert got == want


# ---------------------------------------------------------------------------
# Indicator resolution: registry only, never hand-formatted column names
# ---------------------------------------------------------------------------


class TestIndicatorResolution:
    def test_unknown_indicator_raises_rule_evaluation_error(self) -> None:
        bars = _bars(close=[1.0, 2.0])
        node = Comparison(IndicatorRef(name="not_a_real_indicator", args=()), CompareOp.GT, Literal(0.0))
        with pytest.raises(RuleEvaluationError, match="unknown indicator"):
            evaluate(node, bars, interval=Interval.DAY)

    def test_bad_params_raises_rule_evaluation_error(self) -> None:
        bars = _bars(close=[1.0, 2.0])
        node = Comparison(IndicatorRef(name="rsi", args=(0.0,)), CompareOp.GT, Literal(0.0))
        with pytest.raises(RuleEvaluationError, match="below the minimum"):
            evaluate(node, bars, interval=Interval.DAY)

    def test_vwap_on_daily_raises_rule_evaluation_error(self) -> None:
        """VWAP is only defined on 5m/1h; the registry's own refusal must surface, not a garbage series."""
        bars = _bars(close=[1.0, 2.0])
        node = Comparison(IndicatorRef(name="vwap", args=()), CompareOp.GT, Literal(0.0))
        with pytest.raises(RuleEvaluationError, match="not defined on 1d"):
            evaluate(node, bars, interval=Interval.DAY)

    def test_vwap_on_5m_does_not_raise(self) -> None:
        bars = _bars(
            close=[1.0, 2.0, 3.0],
            start=dt.datetime(2026, 1, 2, 14, 30, tzinfo=dt.UTC),
            step=dt.timedelta(minutes=5),
        )
        node = Comparison(IndicatorRef(name="vwap", args=()), CompareOp.GT, Literal(0.0))
        result = evaluate(node, bars, interval=Interval.FIVE_MIN)
        assert result.dtype == "boolean"

    def test_required_specs_deduplicated_and_stable_order(self) -> None:
        node = BoolOp(
            BoolOpKind.AND,
            (
                Comparison(_BB_UPPER, CompareOp.GT, Literal(0.0)),
                Comparison(_RSI14, CompareOp.LT, Literal(70.0)),
                Comparison(_BB_LOWER, CompareOp.GT, Literal(0.0)),  # same bb config, different output
            ),
        )
        assert required_specs(node) == ["bb:20,2", "rsi:14"]

    def test_distinct_indicator_computed_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`bb_upper(20,2) - bb_lower(20,2)` must trigger exactly one `bb` computation."""
        calls: list[int] = []
        original_compute = indicator_registry.compute

        def spy(bars: pd.DataFrame, requests: list) -> pd.DataFrame:
            calls.append(len(requests))
            return original_compute(bars, requests)

        monkeypatch.setattr(indicator_registry, "compute", spy)

        closes = [100 + 5 * math.sin(i / 3) for i in range(30)]
        bars = _bars(close=closes)
        node = BoolOp(
            BoolOpKind.AND,
            (
                Comparison(_BB_UPPER, CompareOp.GT, Literal(0.0)),
                Comparison(_BB_LOWER, CompareOp.GT, Literal(0.0)),
                Comparison(_RSI14, CompareOp.LT, Literal(90.0)),
            ),
        )
        evaluate(node, bars, interval=Interval.DAY)

        assert calls == [2]  # one `bb` request, one `rsi` request -- not three


# ---------------------------------------------------------------------------
# IndicatorCache: sharing a computed indicator across *different* rule trees
# ---------------------------------------------------------------------------


class TestIndicatorCache:
    """`IndicatorCache`: the caller-owned cache that shares an indicator computation across
    different rule trees -- what `TestIndicatorResolution.test_distinct_indicator_computed_once`
    already proves *within* one tree, extended across two `evaluate()` calls."""

    def test_shared_cache_computes_a_common_indicator_once_across_two_different_trees(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The motivating case from the phase-6 report: `rsi_oversold` (`rsi:14 < 30`) and
        `rsi_overbought` (`rsi:14 > 70`) are different trees -- they would never share
        `app.rules.service`'s `signal_cache`, which is keyed by rendered text -- but both want
        `rsi:14` computed against the same bars. Sharing one `IndicatorCache` across their two
        `evaluate()` calls must mean the real computation (`indicator_registry.compute`) runs once
        total, not once per tree. Counted directly, not inferred from timing."""
        calls: list[int] = []
        original_compute = indicator_registry.compute

        def spy(bars: pd.DataFrame, requests: list) -> pd.DataFrame:
            calls.append(len(requests))
            return original_compute(bars, requests)

        monkeypatch.setattr(indicator_registry, "compute", spy)

        closes = [100 + i * 0.5 for i in range(20)]
        bars = _bars(close=closes)
        oversold = Comparison(_RSI14, CompareOp.LT, Literal(30.0))
        overbought = Comparison(_RSI14, CompareOp.GT, Literal(70.0))
        cache = IndicatorCache()

        evaluate(oversold, bars, interval=Interval.DAY, indicator_cache=cache)
        evaluate(overbought, bars, interval=Interval.DAY, indicator_cache=cache)

        # One `compute` call total: the first `evaluate()` computed `rsi:14` and cached it, the
        # second found it already there and computed nothing.
        assert calls == [1]

    def test_without_a_shared_cache_the_same_two_trees_compute_it_twice(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The baseline the fix changes: with no cache (the default, still exactly the old
        behaviour), the same two trees against the same bars really do compute `rsi:14` twice."""
        calls: list[int] = []
        original_compute = indicator_registry.compute

        def spy(bars: pd.DataFrame, requests: list) -> pd.DataFrame:
            calls.append(len(requests))
            return original_compute(bars, requests)

        monkeypatch.setattr(indicator_registry, "compute", spy)

        closes = [100 + i * 0.5 for i in range(20)]
        bars = _bars(close=closes)
        oversold = Comparison(_RSI14, CompareOp.LT, Literal(30.0))
        overbought = Comparison(_RSI14, CompareOp.GT, Literal(70.0))

        evaluate(oversold, bars, interval=Interval.DAY)
        evaluate(overbought, bars, interval=Interval.DAY)

        assert calls == [1, 1]  # two separate computations, one per call -- no sharing at all

    def test_default_none_path_is_bit_identical_to_a_fresh_cache(self) -> None:
        """`indicator_cache=None` (the default) and a freshly-constructed, never-reused
        `IndicatorCache` must produce exactly the same signal on the same bars -- the cache changes
        how the answer is computed, never what it is."""
        closes = [100 + 5 * math.sin(i / 3) for i in range(30)]
        bars = _bars(close=closes)
        node = BoolOp(
            BoolOpKind.AND,
            (
                Comparison(_BB_UPPER, CompareOp.GT, Literal(0.0)),
                Comparison(_BB_LOWER, CompareOp.GT, Literal(0.0)),
                Comparison(_RSI14, CompareOp.LT, Literal(90.0)),
            ),
        )
        uncached = evaluate(node, bars, interval=Interval.DAY)
        cached = evaluate(node, bars, interval=Interval.DAY, indicator_cache=IndicatorCache())
        assert uncached.equals(cached)

    def test_reusing_a_cache_against_different_bars_raises(self) -> None:
        """The correctness hazard this cache exists to guard against: bars swapped out from under a
        reused cache must raise rather than silently returning the first bar frame's `rsi:14`."""
        bars_a = _bars(close=[100 + i * 0.5 for i in range(20)])
        bars_b = _bars(close=[200 + i * 0.3 for i in range(25)])
        node = Comparison(_RSI14, CompareOp.LT, Literal(30.0))
        cache = IndicatorCache()

        evaluate(node, bars_a, interval=Interval.DAY, indicator_cache=cache)
        with pytest.raises(IndicatorCacheError, match="different bar frame"):
            evaluate(node, bars_b, interval=Interval.DAY, indicator_cache=cache)

    def test_reusing_a_cache_against_bars_of_equal_length_but_different_dates_raises(self) -> None:
        """Length alone would not catch a same-sized, differently-dated frame -- the fingerprint also
        carries the first and last timestamp, so this is still caught."""
        bars_a = _bars(close=[100 + i * 0.5 for i in range(20)])
        bars_b = _bars(
            close=[100 + i * 0.5 for i in range(20)],
            start=dt.datetime(2030, 1, 2, tzinfo=dt.UTC),
        )
        node = Comparison(_RSI14, CompareOp.LT, Literal(30.0))
        cache = IndicatorCache()

        evaluate(node, bars_a, interval=Interval.DAY, indicator_cache=cache)
        with pytest.raises(IndicatorCacheError, match="different bar frame"):
            evaluate(node, bars_b, interval=Interval.DAY, indicator_cache=cache)

    def test_same_cache_reused_against_the_same_bars_repeatedly_does_not_raise(self) -> None:
        """The guard binds on first use and then only ever compares equal -- it must not become
        stricter than "the same bars" (e.g. by accident of object identity)."""
        bars = _bars(close=[100 + i * 0.5 for i in range(20)])
        node = Comparison(_RSI14, CompareOp.LT, Literal(30.0))
        cache = IndicatorCache()

        first = evaluate(node, bars, interval=Interval.DAY, indicator_cache=cache)
        second = evaluate(node, bars.copy(), interval=Interval.DAY, indicator_cache=cache)
        assert first.equals(second)


# ---------------------------------------------------------------------------
# Empty, tiny, and index-alignment cases
# ---------------------------------------------------------------------------


class TestEmptyAndTinyInputs:
    def test_empty_frame_returns_empty_series_without_raising(self) -> None:
        bars = _empty_bars()
        node = Comparison(_RSI14, CompareOp.LT, Literal(30.0))
        result = evaluate(node, bars, interval=Interval.DAY)
        assert len(result) == 0
        assert result.dtype == "boolean"
        assert result.index.equals(bars.index)

    def test_single_bar_returns_na_for_warmup_indicator(self) -> None:
        bars = _bars(close=[100.0])
        node = Comparison(_RSI14, CompareOp.LT, Literal(30.0))
        result = evaluate(node, bars, interval=Interval.DAY)
        assert len(result) == 1
        assert _is_na(result.iloc[0])

    def test_fewer_bars_than_warmup_is_all_na(self) -> None:
        bars = _bars(close=[100.0, 101.0, 102.0])  # rsi(14) needs 14
        node = Comparison(_RSI14, CompareOp.LT, Literal(30.0))
        result = evaluate(node, bars, interval=Interval.DAY)
        assert result.isna().all()

    def test_index_alignment_exact(self) -> None:
        bars = _bars(close=[1.0, 2.0, 3.0, 4.0, 5.0])
        node = BoolOp(
            BoolOpKind.OR,
            (Comparison(_CLOSE, CompareOp.GT, Literal(3.0)), Cross(_CLOSE, CrossDir.ABOVE, _OPEN)),
        )
        result = evaluate(node, bars, interval=Interval.DAY)
        assert result.index.equals(bars.index)


# ---------------------------------------------------------------------------
# Every node type is reachable
# ---------------------------------------------------------------------------


class TestNodeTypeCoverage:
    def test_boolop_and_with_three_operands(self) -> None:
        bars = _bars(close=[50.0])
        node = BoolOp(
            BoolOpKind.AND,
            (
                Comparison(_CLOSE, CompareOp.GT, Literal(0.0)),
                Comparison(_CLOSE, CompareOp.LT, Literal(100.0)),
                Comparison(_CLOSE, CompareOp.NEQ, Literal(999.0)),
            ),
        )
        result = evaluate(node, bars, interval=Interval.DAY)
        assert result.iloc[0]

    def test_boolop_or_with_three_operands_short_circuits_to_true(self) -> None:
        bars = _bars(close=[50.0])
        node = BoolOp(
            BoolOpKind.OR,
            (
                Comparison(_CLOSE, CompareOp.LT, Literal(0.0)),
                Comparison(_CLOSE, CompareOp.GT, Literal(1000.0)),
                Comparison(_CLOSE, CompareOp.EQ, Literal(50.0)),
            ),
        )
        result = evaluate(node, bars, interval=Interval.DAY)
        assert result.iloc[0]

    def test_all_compare_ops(self) -> None:
        bars = _bars(close=[50.0])
        ops_and_expected = [
            (CompareOp.LT, 60.0, True),
            (CompareOp.LTE, 50.0, True),
            (CompareOp.GT, 40.0, True),
            (CompareOp.GTE, 50.0, True),
            (CompareOp.EQ, 50.0, True),
            (CompareOp.NEQ, 50.0, False),
        ]
        for op, threshold, expected in ops_and_expected:
            node = Comparison(_CLOSE, op, Literal(threshold))
            result = evaluate(node, bars, interval=Interval.DAY)
            assert bool(result.iloc[0]) is expected, f"{op}"

    def test_literal_and_price_ref(self) -> None:
        bars = _bars(close=[42.0])
        node = Comparison(_CLOSE, CompareOp.EQ, Literal(42.0))
        result = evaluate(node, bars, interval=Interval.DAY)
        assert result.iloc[0]

    def test_not(self) -> None:
        bars = _bars(close=[42.0])
        node = Not(Comparison(_CLOSE, CompareOp.EQ, Literal(42.0)))
        result = evaluate(node, bars, interval=Interval.DAY)
        assert not result.iloc[0]


# ---------------------------------------------------------------------------
# `evaluate_num` -- the numeric half, used for cross-sectional ranking keys
# ---------------------------------------------------------------------------


class TestEvaluateNum:
    """The magnitude walker `evaluate` shares every resolution step with.

    Its caller (`app.tournament.runner._build_rank_table`) sorts one symbol's value against another
    symbol's, so the two properties that matter here are the dtype -- plain ``float64``, since a
    magnitude has no third truth value to represent -- and that an undefined value stays ``NaN``
    rather than becoming a number that would sort.
    """

    def test_a_price_field_is_returned_as_float64(self) -> None:
        bars = _bars(close=[10.0, 20.0, 30.0])
        result = evaluate_num(PriceRef(field=PriceField.CLOSE), bars, interval=Interval.DAY)
        assert result.dtype == "float64"
        assert list(result) == [10.0, 20.0, 30.0]

    def test_arithmetic_composes_the_same_way_it_does_inside_a_rule(self) -> None:
        bars = _bars(close=[10.0, 20.0])
        node = Arith(
            left=PriceRef(field=PriceField.CLOSE), op=ArithOp.MUL, right=Literal(value=2.0)
        )
        assert list(evaluate_num(node, bars, interval=Interval.DAY)) == [20.0, 40.0]

    def test_an_indicator_still_in_warmup_is_nan_not_zero(self) -> None:
        # The distinction the ranking caller depends on: zero would sort as the weakest name, while
        # NaN means "no value", which `_RankTable.value` turns into `None` and sorts behind instead.
        bars = _bars(close=[float(i) for i in range(1, 11)])
        node = IndicatorRef(name="sma", args=(5.0,), output=None)
        result = evaluate_num(node, bars, interval=Interval.DAY)
        assert result.iloc[:4].isna().all()
        assert not result.iloc[4:].isna().any()

    def test_a_zero_divisor_is_nan_not_inf(self) -> None:
        # Same guarantee `_eval_num` already gives inside a rule, asserted through this entry point
        # because `inf` would sort as the strongest name rather than as undefined.
        bars = _bars(close=[10.0, 20.0])
        node = Arith(
            left=PriceRef(field=PriceField.CLOSE), op=ArithOp.DIV, right=Literal(value=0.0)
        )
        assert evaluate_num(node, bars, interval=Interval.DAY).isna().all()

    def test_an_unknown_indicator_raises_the_shared_evaluation_error(self) -> None:
        bars = _bars(close=[1.0, 2.0])
        node = IndicatorRef(name="nope", args=(), output=None)
        with pytest.raises(RuleEvaluationError):
            evaluate_num(node, bars, interval=Interval.DAY)

    def test_empty_bars_give_an_empty_series_rather_than_raising(self) -> None:
        result = evaluate_num(
            PriceRef(field=PriceField.CLOSE), _empty_bars(), interval=Interval.DAY
        )
        assert len(result) == 0

    def test_the_cache_is_shared_with_the_boolean_walker(self) -> None:
        # One `IndicatorCache` across both entry points: a card evaluating `rsi(14)` as its entry
        # rule and ranking on the same `rsi(14)` should compute it once, not twice.
        bars = _bars(close=[float(i) for i in range(1, 41)])
        cache = IndicatorCache()
        rule = Comparison(
            left=IndicatorRef(name="rsi", args=(14.0,), output=None),
            op=CompareOp.GT,
            right=Literal(value=0.0),
        )
        key = IndicatorRef(name="rsi", args=(14.0,), output=None)
        evaluate(rule, bars, interval=Interval.DAY, indicator_cache=cache)
        ranked = evaluate_num(key, bars, interval=Interval.DAY, indicator_cache=cache)
        direct = evaluate_num(key, bars, interval=Interval.DAY)
        pd.testing.assert_series_equal(ranked, direct)

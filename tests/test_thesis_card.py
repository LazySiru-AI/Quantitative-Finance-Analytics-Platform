"""The strategy-card layer: `app.thesis.strategycard` and `app.thesis.debate`.

Every card, whatever its verdict, must carry the numbers that produced that verdict -- see
`app.thesis.models.StrategyCard`'s own docstring, "a system that only renders winners is a system
whose output is selected on the outcome." `TestCardIsProducedForEveryVerdict` is the direct test of
that.

`TestWashSales` is the most valuable class in this file: it is the one figure a standalone backtester
structurally cannot produce, and it is a computed fact here, not a claim.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from app.backtest import strategy as backtest_strategy
from app.backtest.models import (
    Costs,
    Distribution,
    ExitReason,
    StrategyMetrics,
    StrategyResult,
    StrategySpec,
    Trade,
)
from app.config import Settings
from app.db.duck import Interval
from app.report import narrative
from app.report.models import NarrativeDraft
from app.thesis import debate as debate_module
from app.thesis import preregister, strategycard
from app.thesis.models import (
    Direction,
    Evidence,
    LedgerStats,
    TaxRateBasis,
    Thesis,
    ThesisRecord,
    ThesisStatus,
    Verdict,
)

# ---------------------------------------------------------------------------------------------
# Fakes -- mirrors tests/test_strategy.py's `_FixedGrammar`/`_SignalEvaluator`: a test pins the
# exact trigger pattern rather than reverse-engineering one from a real indicator.
# ---------------------------------------------------------------------------------------------


class _FixedGrammar:
    """Parses nothing; every evaluator below ignores the parsed tree entirely."""

    def parse(self, expression: str) -> object:
        return expression


class _PeriodicEvaluator:
    """Fires every `period`-th bar, sized to whatever `bars` it is asked to evaluate -- a
    deterministic stand-in for a real indicator rule when a test does not care exactly which bars
    trigger, only that evaluation completes without depending on `app.rules`."""

    def __init__(self, period: int = 7) -> None:
        self._period = period

    def evaluate(self, node: object, bars: pd.DataFrame, *, interval: Interval) -> pd.Series:
        n = len(bars)
        fired = np.array([i % self._period == 0 for i in range(n)], dtype=bool)
        return pd.Series(fired, dtype="boolean")


class _PinnedEvaluator:
    """Fires exactly where `fired` says. `bars` must be the same length as `fired` -- used where a
    test hand-verifies the resulting statistics, unlike `_PeriodicEvaluator`."""

    def __init__(self, fired: np.ndarray) -> None:
        self._fired = fired

    def evaluate(self, node: object, bars: pd.DataFrame, *, interval: Interval) -> pd.Series:
        assert len(bars) == self._fired.size, "fixture bug: fired array does not match bars length"
        return pd.Series(self._fired, dtype="boolean")


class _SignalEvaluator:
    """Returns a caller-supplied signal keyed by expression text, exactly as
    tests/test_strategy.py's helper of the same name does -- used only where a real
    `app.backtest.strategy.backtest()` trade sequence needs to be pinned by hand."""

    def __init__(self, signals: dict[str, pd.Series]) -> None:
        self._signals = signals

    def evaluate(self, node: object, bars: pd.DataFrame, *, interval: Interval) -> pd.Series:
        return self._signals[str(node)]


# ---------------------------------------------------------------------------------------------
# Bars builders
# ---------------------------------------------------------------------------------------------


def _bars(n: int, *, seed: int = 1, start: str = "2010-01-01") -> pd.DataFrame:
    """An ordinary random walk -- adequate wherever a test does not care about the specific price
    path, only that one exists. Mirrors tests/test_thesis_loop.py's `_random_walk`."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0, 1.0, size=n)
    close = 100.0 * np.exp(np.cumsum(steps) * 0.01)
    open_ = close * (1.0 + rng.normal(0.0, 0.001, size=n))
    return pd.DataFrame(
        {
            "ts": pd.date_range(start, periods=n, freq="D", tz="UTC"),
            "open": open_,
            "high": np.maximum(close, open_) * 1.005,
            "low": np.minimum(close, open_) * 0.995,
            "close": close,
            "adj_close": close,
            "volume": np.full(n, 1e6),
        }
    )


def _bars_from_returns(r: np.ndarray, *, start: str = "2010-01-01") -> pd.DataFrame:
    """Builds OHLC bars where ``r[i]`` is *exactly* bar ``i``'s close-to-close return: ``open[i]`` is
    pinned to ``close[i - 1]`` (no gap), so both the close-to-close return `app.thesis.strategycard`'s
    regime volatility computation reads and the open-to-close return a horizon-1 forward return reads
    are the identical, caller-chosen number. ``r[0]`` is unused (bar 0 has no prior close)."""
    n = r.size
    close = np.empty(n, dtype=float)
    close[0] = 100.0
    for i in range(1, n):
        close[i] = close[i - 1] * (1.0 + r[i])
    open_ = np.empty(n, dtype=float)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    return pd.DataFrame(
        {
            "ts": pd.date_range(start, periods=n, freq="D", tz="UTC"),
            "open": open_,
            "high": np.maximum(open_, close) * 1.001,
            "low": np.minimum(open_, close) * 0.999,
            "close": close,
            "adj_close": close,
            "volume": np.full(n, 1e6),
        }
    )


# ---------------------------------------------------------------------------------------------
# Thesis / record builders
# ---------------------------------------------------------------------------------------------


def _thesis(**overrides: object) -> Thesis:
    base: dict[str, object] = {
        "symbol": "TEST",
        "interval": Interval.DAY,
        "hypothesis": "A fixed rule fires and forward returns beat baseline.",
        "entry": "fixed_entry",
        "horizon": 5,
        "direction": Direction.UP,
        "falsifies_if": "the hit rate after the rule does not exceed the unconditional rate",
    }
    base.update(overrides)
    return Thesis(**base)  # type: ignore[arg-type]


def _record(thesis: Thesis, verdict: Verdict, *, status: ThesisStatus = ThesisStatus.IN_SAMPLE_TESTED) -> ThesisRecord:
    registered = preregister.register(thesis)
    return registered.model_copy(update={"status": status, "verdict": verdict})


# ---------------------------------------------------------------------------------------------
# A card is produced for every verdict, carrying its evidence
# ---------------------------------------------------------------------------------------------


class TestCardIsProducedForEveryVerdict:
    """`StrategyCard`'s own docstring: a rejected or inconclusive thesis gets a card carrying the
    numbers that killed it, not a gap where a card would have been."""

    @pytest.mark.parametrize("verdict", [Verdict.SURVIVED, Verdict.REJECTED, Verdict.INCONCLUSIVE])
    def test_a_card_is_built_and_carries_its_evidence(self, verdict: Verdict) -> None:
        thesis = _thesis(symbol="CARD")
        record = _record(thesis, verdict)
        bars = _bars(120, seed=1)
        evidence = Evidence(
            horizon=5, hit_rate=0.55, baseline_hit_rate=0.50, sample_size=40, independent_sample_size=32,
            p_value=0.2, q_value=0.3,
        )

        card = strategycard.build_card(
            thesis,
            record,
            bars=bars,
            evidence=evidence,
            grammar=_FixedGrammar(),
            evaluator=_PeriodicEvaluator(),
        )

        assert card.verdict is verdict
        assert card.in_sample == evidence
        assert card.thesis == thesis
        assert card.thesis_hash == record.thesis_hash
        # The numbers that killed a rejected/inconclusive thesis are still populated -- not only
        # for a survivor.
        assert isinstance(card.expected_return, Distribution)
        assert isinstance(card.baseline_return, Distribution)
        assert card.tax is not None
        assert card.tax.unavailable_reason is not None  # no strategy_result was supplied
        assert card.bundle is not None
        assert card.bundle.get("thesis.verdict") is not None
        assert card.bundle.facts["thesis.verdict"].value == verdict.value

    def test_holdout_evidence_is_carried_when_supplied(self) -> None:
        thesis = _thesis(symbol="CARDH")
        record = _record(thesis, Verdict.SURVIVED, status=ThesisStatus.HOLDOUT_TESTED)
        bars = _bars(120, seed=2)
        evidence = Evidence(horizon=5, hit_rate=0.6, baseline_hit_rate=0.5, sample_size=40, independent_sample_size=32)
        holdout_evidence = Evidence(horizon=5, hit_rate=0.58, baseline_hit_rate=0.5, sample_size=20, independent_sample_size=15, p_value=0.03)

        card = strategycard.build_card(
            thesis, record, bars=bars, evidence=evidence, holdout_evidence=holdout_evidence,
            grammar=_FixedGrammar(), evaluator=_PeriodicEvaluator(),
        )

        assert card.holdout == holdout_evidence
        # Prefers the holdout distribution when it has observations -- see build_card's docstring.
        assert card.expected_return == holdout_evidence.distribution

    def test_a_card_refuses_to_build_for_a_verdictless_record(self) -> None:
        thesis = _thesis(symbol="CARDV")
        record = preregister.register(thesis)  # REGISTERED, no verdict yet
        with pytest.raises(ValueError, match="no verdict"):
            strategycard.build_card(
                thesis, record, bars=_bars(50, seed=3), evidence=Evidence(horizon=5),
                grammar=_FixedGrammar(), evaluator=_PeriodicEvaluator(),
            )

    def test_a_card_refuses_a_thesis_that_does_not_match_the_record(self) -> None:
        thesis = _thesis(symbol="CARDX")
        record = _record(thesis, Verdict.REJECTED)
        reworded = thesis.model_copy(update={"hypothesis": "a different claim"})
        with pytest.raises(ValueError, match="does not match"):
            strategycard.build_card(
                reworded, record, bars=_bars(50, seed=4), evidence=Evidence(horizon=5),
                grammar=_FixedGrammar(), evaluator=_PeriodicEvaluator(),
            )


# ---------------------------------------------------------------------------------------------
# expected_return / baseline_return are distributions, never bare floats
# ---------------------------------------------------------------------------------------------


class TestDistributionsNotPointEstimates:
    def test_both_fields_are_distribution_objects(self) -> None:
        thesis = _thesis(symbol="DIST")
        record = _record(thesis, Verdict.INCONCLUSIVE)
        bars = _bars(120, seed=5)
        evidence = Evidence(horizon=5, hit_rate=0.5, baseline_hit_rate=0.5, sample_size=10, independent_sample_size=8)

        card = strategycard.build_card(
            thesis, record, bars=bars, evidence=evidence,
            grammar=_FixedGrammar(), evaluator=_PeriodicEvaluator(),
        )

        assert isinstance(card.expected_return, Distribution)
        assert isinstance(card.baseline_return, Distribution)
        # Populated: `_PeriodicEvaluator` fires plenty of times over 120 bars, so the baseline
        # distribution (all evaluable bars, not just triggers) has a real sample.
        assert card.baseline_return.count > 0
        assert card.baseline_return.median is not None


# ---------------------------------------------------------------------------------------------
# triggers_per_year, hand-computed
# ---------------------------------------------------------------------------------------------


class TestTriggersPerYear:
    def test_matches_a_hand_computed_value(self) -> None:
        """`triggers_per_year` is `(evidence.sample_size + holdout_evidence.sample_size) /
        (len(bars) / 252)` for a daily thesis -- independent of the entry rule's actual firing
        pattern, since it consumes the already-measured trigger counts rather than re-evaluating the
        rule. 504 bars is exactly two years at 252 bars/year; 30 + 10 = 40 triggers over two years is
        20.0 a year."""
        thesis = _thesis(symbol="FREQ")
        record = _record(thesis, Verdict.SURVIVED, status=ThesisStatus.HOLDOUT_TESTED)
        bars = _bars(504, seed=6)
        evidence = Evidence(horizon=5, hit_rate=0.55, baseline_hit_rate=0.5, sample_size=30, independent_sample_size=25)
        holdout_evidence = Evidence(horizon=5, hit_rate=0.55, baseline_hit_rate=0.5, sample_size=10, independent_sample_size=9)

        card = strategycard.build_card(
            thesis, record, bars=bars, evidence=evidence, holdout_evidence=holdout_evidence,
            grammar=_FixedGrammar(), evaluator=_PeriodicEvaluator(),
        )

        assert card.triggers_per_year == pytest.approx(20.0)

    def test_in_sample_only_when_there_is_no_holdout(self) -> None:
        thesis = _thesis(symbol="FREQ2")
        record = _record(thesis, Verdict.INCONCLUSIVE)
        bars = _bars(252, seed=7)  # exactly one year
        evidence = Evidence(horizon=5, hit_rate=0.5, baseline_hit_rate=0.5, sample_size=14, independent_sample_size=10)

        card = strategycard.build_card(
            thesis, record, bars=bars, evidence=evidence,
            grammar=_FixedGrammar(), evaluator=_PeriodicEvaluator(),
        )

        assert card.triggers_per_year == pytest.approx(14.0)


# ---------------------------------------------------------------------------------------------
# Holding period median / IQR, hand-checked against a pinned trade sequence
# ---------------------------------------------------------------------------------------------


class TestHoldingPeriodStats:
    def test_median_and_iqr_match_hand_computed_percentiles(self) -> None:
        """Four round trips, pinned to hold exactly 2, 4, 6 and 8 bars -- see
        tests/test_strategy.py's `TestOneTradeHandComputed` for the entry/exit fill convention this
        relies on (entry flagged at index t fills at t+1's open; a SIGNAL exit flagged at index t'
        fills at t'+1's open, so `bars_held = t' - t`).

        Hand computation for `numpy.percentile`'s linear interpolation over the sorted sample
        ``[2, 4, 6, 8]``:

        * median (50th percentile): midpoint of the two middle values, ``(4 + 6) / 2 = 5.0``.
        * 25th percentile: rank ``0.25 * (4 - 1) = 0.75`` -> interpolate index 0 (2) and index 1 (4):
          ``2 + 0.75 * (4 - 2) = 3.5``.
        * 75th percentile: rank ``0.75 * 3 = 2.25`` -> interpolate index 2 (6) and index 3 (8):
          ``6 + 0.25 * (8 - 6) = 6.5``.
        """
        n = 46
        entry_idx = [2, 10, 20, 32]
        exit_idx = [4, 14, 26, 40]  # holds: 2, 4, 6, 8
        entry = pd.Series([i in entry_idx for i in range(n)], dtype="boolean")
        exit_ = pd.Series([i in exit_idx for i in range(n)], dtype="boolean")

        close = 100.0 + np.arange(n, dtype=float)
        bars = pd.DataFrame(
            {
                "ts": pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC"),
                "open": close.copy(),
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "adj_close": close,
                "volume": np.full(n, 1e6),
            }
        )
        spec = StrategySpec(entry="entry", exit="exit")
        metrics, buy_hold, trades, equity_curve, cost_drag, open_trades = backtest_strategy.backtest(
            bars, spec, interval=Interval.DAY, costs=Costs(slippage_bps=0.0),
            grammar=_FixedGrammar(), evaluator=_SignalEvaluator({"entry": entry, "exit": exit_}),
        )
        assert sorted(t.bars_held for t in trades) == [2, 4, 6, 8]

        strategy_result = StrategyResult(
            symbol="HOLD", interval=Interval.DAY, generated_at=dt.datetime.now(dt.UTC),
            spec=spec, costs=Costs(slippage_bps=0.0), metrics=metrics, buy_hold=buy_hold,
            cost_drag=cost_drag, equity_curve=equity_curve, trades=trades, open_trades=open_trades,
        )

        thesis = _thesis(symbol="HOLD")
        record = _record(thesis, Verdict.SURVIVED, status=ThesisStatus.HOLDOUT_TESTED)
        evidence = Evidence(horizon=5, hit_rate=0.5, baseline_hit_rate=0.5, sample_size=10, independent_sample_size=8)

        card = strategycard.build_card(
            thesis, record, bars=_bars(120, seed=8), evidence=evidence, strategy_result=strategy_result,
            grammar=_FixedGrammar(), evaluator=_PeriodicEvaluator(),
        )

        assert card.holding_period_median == pytest.approx(5.0)
        assert card.holding_period_iqr is not None
        assert card.holding_period_iqr[0] == pytest.approx(3.5)
        assert card.holding_period_iqr[1] == pytest.approx(6.5)
        assert card.worst_trade == pytest.approx(min(t.return_pct for t in trades))


# ---------------------------------------------------------------------------------------------
# The unlevered-comparison guard
# ---------------------------------------------------------------------------------------------


class TestUnleveredComparison:
    def test_a_leveraged_symbol_gets_a_nested_comparison_with_no_further_nesting(self) -> None:
        thesis = _thesis(symbol="SOXL")
        record = _record(thesis, Verdict.INCONCLUSIVE)
        evidence = Evidence(horizon=5, hit_rate=0.5, baseline_hit_rate=0.5, sample_size=10, independent_sample_size=8)

        card = strategycard.build_card(
            thesis, record, bars=_bars(200, seed=9), evidence=evidence, unlevered_bars=_bars(200, seed=10),
            grammar=_FixedGrammar(), evaluator=_PeriodicEvaluator(),
        )

        assert card.unlevered_comparison is not None
        assert card.unlevered_comparison.symbol == "SOXX"
        assert card.unlevered_comparison.unlevered_comparison is None
        assert not any(w.kind in ("leveraged_no_equivalent", "unlevered_bars_missing") for w in card.warnings)

    def test_a_leveraged_symbol_with_no_equivalent_gets_the_warning_not_a_comparison(self) -> None:
        thesis = _thesis(symbol="MUU")
        record = _record(thesis, Verdict.REJECTED)
        evidence = Evidence(horizon=5, hit_rate=0.4, baseline_hit_rate=0.5, sample_size=10, independent_sample_size=8)

        card = strategycard.build_card(
            thesis, record, bars=_bars(200, seed=11), evidence=evidence,
            grammar=_FixedGrammar(), evaluator=_PeriodicEvaluator(),
        )

        assert card.unlevered_comparison is None
        warning = next(w for w in card.warnings if w.kind == "leveraged_no_equivalent")
        assert "no unlevered equivalent" in warning.message

    def test_an_ordinary_symbol_gets_neither(self) -> None:
        thesis = _thesis(symbol="QQQ")
        record = _record(thesis, Verdict.SURVIVED, status=ThesisStatus.HOLDOUT_TESTED)
        evidence = Evidence(horizon=5, hit_rate=0.6, baseline_hit_rate=0.5, sample_size=40, independent_sample_size=32)

        card = strategycard.build_card(
            thesis, record, bars=_bars(200, seed=12), evidence=evidence,
            grammar=_FixedGrammar(), evaluator=_PeriodicEvaluator(),
        )

        assert card.unlevered_comparison is None
        assert not any(
            w.kind in ("leveraged_no_equivalent", "unlevered_bars_missing") for w in card.warnings
        )


# ---------------------------------------------------------------------------------------------
# Regime slices: an effect present only in the high-volatility half
# ---------------------------------------------------------------------------------------------


class TestRegimeSlices:
    """Builds a series where every fixed trigger in the calm first half has an exactly 50/50
    outcome (no edge) and every fixed trigger in the choppy second half wins outright (edge). The
    volatility split is `app.thesis.strategycard`'s own -- rolling 20-bar realised volatility split
    at its median -- and is expected to recover close to the calm/choppy boundary because the choppy
    half's day-to-day moves are ten times larger by construction.
    """

    @staticmethod
    def _regime_series(n: int = 500, split: int = 250) -> tuple[np.ndarray, np.ndarray]:
        r = np.zeros(n, dtype=float)
        fired = np.zeros(n, dtype=bool)
        for t in range(0, n - 1):
            if t % 5 == 0:
                fired[t] = True
            i = t + 1  # forward_returns[t] at horizon=1 equals r[i], bar i's own close-to-close move
            if t < split:
                if t % 5 == 0:
                    r[i] = 0.002 if (t // 5) % 2 == 0 else -0.002  # alternating: exactly 50/50
                else:
                    r[i] = 0.0015 if i % 2 == 0 else -0.0015
            else:
                if t % 5 == 0:
                    r[i] = 0.05  # deterministic win
                else:
                    r[i] = 0.02 if i % 2 == 0 else -0.02
        return r, fired

    def test_the_slices_show_the_effect_only_on_the_high_volatility_side(self) -> None:
        r, fired = self._regime_series()
        bars = _bars_from_returns(r)
        thesis = _thesis(symbol="REGIME", horizon=1)
        record = _record(thesis, Verdict.INCONCLUSIVE)
        evidence = Evidence(horizon=1)

        card = strategycard.build_card(
            thesis, record, bars=bars, evidence=evidence,
            grammar=_FixedGrammar(), evaluator=_PinnedEvaluator(fired),
        )

        by_label = {s.label: s for s in card.regimes}
        high = by_label["high_volatility"]
        low = by_label["low_volatility"]
        assert high.evidence is not None and high.bars > 100
        assert low.evidence is not None and low.bars > 100

        assert high.evidence.edge is not None
        assert high.evidence.edge > 0.3, f"expected a strong edge in the high-vol half, got {high.evidence.edge}"
        assert low.evidence.edge is not None
        assert abs(low.evidence.edge) < 0.15, f"expected ~no edge in the low-vol half, got {low.evidence.edge}"

        assert any(w.kind == "conditional_edge" for w in card.warnings), (
            "an edge present on only one side of the volatility split must be labelled conditional"
        )


# ---------------------------------------------------------------------------------------------
# Tax impact: wash sales are the headline test
# ---------------------------------------------------------------------------------------------


def _trade(entry_date: dt.date, entry_price: float, exit_date: dt.date, exit_price: float, *, bars_held: int = 5) -> Trade:
    return Trade(
        entry_date=entry_date, entry_price=entry_price, exit_date=exit_date, exit_price=exit_price,
        exit_reason=ExitReason.SIGNAL, bars_held=bars_held, return_pct=exit_price / entry_price - 1.0,
        open_at_end=False,
    )


def _strategy_result(trades: list[Trade], *, total_return: float | None = None) -> StrategyResult:
    return StrategyResult(
        symbol="TAX", interval=Interval.DAY, generated_at=dt.datetime.now(dt.UTC),
        spec=StrategySpec(entry="e", exit="x"), costs=Costs(),
        metrics=StrategyMetrics(total_return=total_return), trades=trades,
    )


class TestWashSales:
    """The most valuable test in this file: the strategy's own re-entry after a losing exit must
    trigger IRC section 1091 against itself, computed by the real `app.tax.washsale` engine against a
    synthetic ledger built from the trade sequence alone."""

    def test_a_loss_followed_by_a_reentry_within_thirty_days_triggers_a_wash_sale(self) -> None:
        trades = [
            _trade(dt.date(2024, 1, 2), 100.0, dt.date(2024, 1, 10), 90.0),  # loss
            _trade(dt.date(2024, 1, 20), 91.0, dt.date(2024, 2, 1), 100.0),  # re-entry 10 days later
        ]
        impact = strategycard.build_tax_impact("TAX", _strategy_result(trades, total_return=-0.01))

        assert impact.unavailable_reason is None
        assert impact.wash_sales_triggered >= 1

    def test_a_reentry_after_thirty_one_days_does_not_trigger_a_wash_sale(self) -> None:
        trades = [
            _trade(dt.date(2024, 3, 1), 100.0, dt.date(2024, 3, 10), 90.0),  # loss
            _trade(dt.date(2024, 4, 10), 91.0, dt.date(2024, 4, 20), 100.0),  # 31 days later
        ]
        impact = strategycard.build_tax_impact("TAX", _strategy_result(trades, total_return=0.0))

        assert impact.unavailable_reason is None
        assert impact.wash_sales_triggered == 0


class TestHoldingTermBoundary:
    """`app.tax.gains.classify_term`'s own rule, exercised through the synthetic ledger: exactly one
    year held is short-term; one year and a day is long-term."""

    def test_exactly_365_days_is_short_term(self) -> None:
        trades = [_trade(dt.date(2023, 1, 10), 100.0, dt.date(2024, 1, 10), 110.0)]
        impact = strategycard.build_tax_impact("TERM", _strategy_result(trades, total_return=0.10))

        assert impact.unavailable_reason is None
        assert impact.short_term_gains is not None and impact.short_term_gains > 0
        assert impact.long_term_gains == pytest.approx(0.0)

    def test_366_days_is_long_term(self) -> None:
        trades = [_trade(dt.date(2023, 1, 10), 100.0, dt.date(2024, 1, 11), 110.0)]
        impact = strategycard.build_tax_impact("TERM", _strategy_result(trades, total_return=0.10))

        assert impact.unavailable_reason is None
        assert impact.long_term_gains is not None and impact.long_term_gains > 0
        assert impact.short_term_gains == pytest.approx(0.0)


class TestTaxImpactUnavailable:
    """Absent-with-a-reason beats absent: no backtest and no closed trade both return an explanatory
    `unavailable_reason`, never fabricated zeros."""

    def test_no_strategy_result_is_unavailable(self) -> None:
        impact = strategycard.build_tax_impact("NONE", None)

        assert impact.unavailable_reason is not None
        assert impact.gross_return is None
        assert impact.short_term_gains is None
        assert impact.wash_sales_triggered == 0

    def test_no_closed_trades_is_unavailable(self) -> None:
        still_open = Trade(
            entry_date=dt.date(2024, 1, 1), entry_price=100.0, exit_date=dt.date(2024, 1, 1),
            exit_price=100.0, exit_reason=ExitReason.END_OF_DATA, bars_held=0, return_pct=0.0,
            open_at_end=True,
        )
        impact = strategycard.build_tax_impact("OPEN", _strategy_result([still_open]))

        assert impact.unavailable_reason is not None

    def test_ira_exposure_is_always_unknown_with_a_synthetic_ledger(self) -> None:
        """This module has no access to the user's real accounts under `data/`; see
        `build_tax_impact`'s docstring for why `ira_exposure` cannot honestly be anything but
        `None` (unknown, not checked) here -- `False` would be a positive claim of no IRA exposure
        this module has no basis for."""
        trades = [_trade(dt.date(2024, 1, 2), 100.0, dt.date(2024, 2, 1), 110.0)]
        impact = strategycard.build_tax_impact("IRA", _strategy_result(trades, total_return=0.10))

        assert impact.ira_exposure is None


class TestTaxRateConfiguration:
    """`app.config.Settings.ordinary_income_tax_rate` / `long_term_capital_gains_tax_rate` let a
    user supply their own marginal rates; unset, `build_tax_impact` falls back to the top federal
    statutory brackets as a directional upper bound. `TaxImpact.rate_basis` must always say which
    of the two happened, because the same float means something different under each."""

    #: One short-term trade, entry 100 -> exit 120: a clean 20% gain on 100 of basis, no wash sale
    #: (single trade, no re-entry) and no long-term gain, so the after-tax drag is entirely a
    #: function of the short-term rate and is easy to hand-compute for the assertions below.
    _TRADES = [_trade(dt.date(2024, 1, 2), 100.0, dt.date(2024, 2, 1), 120.0)]

    def test_a_configured_rate_reaches_the_computed_drag(self) -> None:
        cfg = Settings(ordinary_income_tax_rate=0.10, long_term_capital_gains_tax_rate=0.15)
        impact = strategycard.build_tax_impact(
            "RATE", _strategy_result(self._TRADES, total_return=0.15), settings=cfg
        )

        assert impact.rate_basis is TaxRateBasis.USER_CONFIGURED
        assert impact.short_term_rate_applied == pytest.approx(0.10)
        assert impact.long_term_rate_applied == pytest.approx(0.15)
        # tax owed = 20 (gain) * 0.10 = 2, on a basis of 100 -> 2% drag
        assert impact.after_tax_return == pytest.approx(0.15 - 0.02)

    def test_unset_rates_fall_back_to_the_statutory_basis(self) -> None:
        cfg = Settings(ordinary_income_tax_rate=None, long_term_capital_gains_tax_rate=None)
        impact = strategycard.build_tax_impact(
            "RATE", _strategy_result(self._TRADES, total_return=0.15), settings=cfg
        )

        assert impact.rate_basis is TaxRateBasis.STATUTORY_UPPER_BOUND
        assert impact.short_term_rate_applied == pytest.approx(strategycard.SHORT_TERM_TAX_RATE)
        assert impact.long_term_rate_applied == pytest.approx(strategycard.LONG_TERM_TAX_RATE)
        # tax owed = 20 (gain) * 0.37 = 7.4, on a basis of 100 -> 7.4% drag
        assert impact.after_tax_return == pytest.approx(0.15 - 0.074)

    def test_only_one_rate_configured_still_falls_back_to_the_statutory_basis(self) -> None:
        """`rate_basis` is `USER_CONFIGURED` only when *both* rates came from the user -- a partial
        configuration is still, in part, an assumed statutory figure and must be labelled as such
        rather than as fully computed."""
        cfg = Settings(ordinary_income_tax_rate=0.10, long_term_capital_gains_tax_rate=None)
        impact = strategycard.build_tax_impact(
            "RATE", _strategy_result(self._TRADES, total_return=0.15), settings=cfg
        )

        assert impact.rate_basis is TaxRateBasis.STATUTORY_UPPER_BOUND
        assert impact.short_term_rate_applied == pytest.approx(0.10)
        assert impact.long_term_rate_applied == pytest.approx(strategycard.LONG_TERM_TAX_RATE)

    def test_an_out_of_range_configured_rate_is_rejected(self) -> None:
        """The one realistic misconfiguration is typing the bracket as a percentage (``37``) rather
        than the fraction the field expects (``0.37``); accepting it would silently multiply the
        modelled tax drag by a hundred."""
        with pytest.raises(ValueError, match=r"fraction between 0\.0 and 1\.0"):
            Settings(ordinary_income_tax_rate=37)

        with pytest.raises(ValueError, match=r"fraction between 0\.0 and 1\.0"):
            Settings(long_term_capital_gains_tax_rate=-0.05)


# ---------------------------------------------------------------------------------------------
# The debate: every prose string must pass narrative.verify against the card's own bundle
# ---------------------------------------------------------------------------------------------


class TestDebate:
    @staticmethod
    def _full_card() -> object:
        thesis = _thesis(symbol="DEBATE")
        record = _record(thesis, Verdict.SURVIVED, status=ThesisStatus.HOLDOUT_TESTED)
        evidence = Evidence(
            horizon=5, hit_rate=0.62, baseline_hit_rate=0.50, sample_size=60, independent_sample_size=42,
            p_value=0.01, q_value=0.05,
            distribution=Distribution(
                count=42, mean=0.01, median=0.015, stdev=0.02,
                p05=-0.03, p25=-0.005, p75=0.03, p95=0.05, minimum=-0.06, maximum=0.08,
            ),
        )
        holdout_evidence = Evidence(
            horizon=5, hit_rate=0.58, baseline_hit_rate=0.5, sample_size=20, independent_sample_size=17,
            p_value=0.02,
            distribution=Distribution(
                count=17, mean=0.009, median=0.012, stdev=0.018,
                p05=-0.025, p25=-0.004, p75=0.028, p95=0.045, minimum=-0.05, maximum=0.07,
            ),
        )
        ledger_stats = LedgerStats(symbol="DEBATE", total_trials=12, survived=1, rejected=7, inconclusive=4)

        n = 46
        entry_idx = [2, 10, 20, 32]
        exit_idx = [4, 14, 26, 40]
        entry = pd.Series([i in entry_idx for i in range(n)], dtype="boolean")
        exit_ = pd.Series([i in exit_idx for i in range(n)], dtype="boolean")
        close = 100.0 + np.arange(n, dtype=float)
        trade_bars = pd.DataFrame(
            {
                "ts": pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC"),
                "open": close.copy(), "high": close + 1.0, "low": close - 1.0,
                "close": close, "adj_close": close, "volume": np.full(n, 1e6),
            }
        )
        spec = StrategySpec(entry="entry", exit="exit")
        metrics, buy_hold, trades, equity_curve, cost_drag, open_trades = backtest_strategy.backtest(
            trade_bars, spec, interval=Interval.DAY, costs=Costs(slippage_bps=5.0),
            grammar=_FixedGrammar(), evaluator=_SignalEvaluator({"entry": entry, "exit": exit_}),
        )
        strategy_result = StrategyResult(
            symbol="DEBATE", interval=Interval.DAY, generated_at=dt.datetime.now(dt.UTC),
            spec=spec, costs=Costs(slippage_bps=5.0), metrics=metrics, buy_hold=buy_hold,
            cost_drag=cost_drag, equity_curve=equity_curve, trades=trades, open_trades=open_trades,
        )

        return strategycard.build_card(
            thesis, record, bars=_bars(300, seed=20), evidence=evidence, holdout_evidence=holdout_evidence,
            ledger_stats=ledger_stats, strategy_result=strategy_result,
            grammar=_FixedGrammar(), evaluator=_PeriodicEvaluator(),
        )

    def test_every_emitted_point_passes_narrative_verify(self) -> None:
        card = self._full_card()
        debate = debate_module.build_debate(card)

        assert debate.bull, "expected at least one bull point on a well-populated survived card"
        assert debate.bear, "expected at least one bear point on a well-populated survived card"

        for point in (*debate.bull, *debate.bear):
            report = narrative.verify(NarrativeDraft(text=point.text, source="test"), card.bundle)
            assert report.grounded, (point.text, report.violations)

    def test_the_bear_case_names_the_worst_five_percent_outcome(self) -> None:
        card = self._full_card()
        debate = debate_module.build_debate(card)

        assert any("distribution's tail" in p.text for p in debate.bear)
        assert any("expected_return.p05" in p.fact_ids for p in debate.bear)

    def test_an_empty_bundle_produces_an_empty_debate(self) -> None:
        thesis = _thesis(symbol="EMPTYDEBATE")
        record = _record(thesis, Verdict.INCONCLUSIVE)
        card = strategycard.build_card(
            thesis, record, bars=_bars(50, seed=21), evidence=Evidence(horizon=5),
            grammar=_FixedGrammar(), evaluator=_PeriodicEvaluator(),
        )
        card_without_bundle = card.model_copy(update={"bundle": None})

        debate = debate_module.build_debate(card_without_bundle)

        assert debate.bull == ()
        assert debate.bear == ()

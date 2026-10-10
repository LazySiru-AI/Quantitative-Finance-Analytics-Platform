"""Tests for `app.tournament.weightfn`: the bridge from a frozen `AllocationCard`/`LadderCard` to a
`contributions.simulate`-shaped `WeightFn`.

Follows `tests/test_allocation_card.py`'s and `tests/test_ladder_card.py`'s own conventions --
synthetic bars written into the temp store via the `settings` fixture where the engine's own
machinery (`allocation._build_signal_table`, `ladder._confirmed`) needs to be run for comparison;
plain closes lists everywhere else, since that is this bridge's whole reason for existing.

Each test class pins one claim this bridge's own docstring makes:

* `TestUnsupportedConditions` -- a tilt condition this bridge cannot honestly answer from closes
  alone (anything but `close`, any indicator needing `high`/`low`/`volume`) raises
  `UnsupportedConditionError` at `card_weight_fn` construction time, not silently scores as
  always-false.
* `TestAllocationWeightFnMatchesEngine` -- the allocation bridge's target weights are not merely
  hand-checked in isolation; they are compared directly against `allocation._build_signal_table` /
  `allocation._target_weights` -- the engine's own functions -- run against the identical synthetic
  bars, so a divergence here would be a divergence from the engine itself, not from this test's own
  arithmetic.
* `TestConfirmedMatchesEngine` -- `weightfn._ladder_confirmed` (closes-only) is compared directly
  against `ladder._confirmed` (bars-only) on the same underlying prices, proving the reimplementation
  this module's docstring describes is exact, not merely plausible.
* `TestLadderStateMachineMatchesReferenceScenarios` -- the ladder bridge's per-session leveraged-weight
  trajectory is hand-computed against the same price paths `tests/test_ladder_card.py` already used to
  pin the engine's own confirmation gate, gap-through, once-per-cycle arming and recovery lifecycle,
  so this is a second, independent check of the same rules rather than a new set of assertions no one
  has verified.
* `TestNoLookahead` -- corrupting every close after the session being decided must not change the
  weight returned for it, for both card shapes.
* `TestLadderExcludesSignalSymbol` -- the signal symbol is priced but never appears as a key in the
  returned weight dict.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pandas as pd
import pytest

from app.db import duck
from app.market.models import BAR_COLUMNS, Interval
from app.rules import grammar
from app.tournament import allocation, ladder, weightfn
from app.tournament.allocation import AllocationCard, Sleeve, TiltRule
from app.tournament.ladder import LadderCard, Rung
from app.tournament.models import DESIGN_THROUGH
from app.tournament.weightfn import UnsupportedConditionError, card_weight_fn

# ---------------------------------------------------------------------------
# Fixtures -- duplicated small helpers, per this suite's own established convention (see
# tests/test_allocation_card.py's own module docstring on why every file keeps its own copy).
# ---------------------------------------------------------------------------


def _weekdays(anchor: dt.date, count: int) -> list[dt.date]:
    dates: list[dt.date] = []
    day = anchor
    while len(dates) < count:
        if day.weekday() < 5:
            dates.append(day)
        day += dt.timedelta(days=1)
    return dates


def _write_bars(settings, symbol: str, closes: list[float], dates: list[dt.date]) -> None:
    frame = pd.DataFrame(
        {
            "ts": pd.Series(
                [dt.datetime.combine(d, dt.time.min, tzinfo=dt.UTC) for d in dates],
                dtype="datetime64[us, UTC]",
            ),
            "open": closes,
            "high": [c + 5.0 for c in closes],
            "low": [c - 5.0 for c in closes],
            "close": closes,
            "adj_close": closes,
            "volume": [1_000_000] * len(dates),
        },
        columns=list(BAR_COLUMNS),
    )
    with duck.connect() as conn:
        duck.write_bars(conn, settings.bars_dir, symbol, Interval.DAY, frame)


def _alloc_card(**overrides: object) -> AllocationCard:
    fields: dict[str, object] = {
        "agent_id": "alloc-1",
        "display_name": "Allocation One",
        "thesis": "a test thesis, written before the trading window ran",
        "sleeves": (
            Sleeve(symbol="A", target_weight=Decimal("0.4")),
            Sleeve(symbol="B", target_weight=Decimal("0.35")),
            Sleeve(symbol="C", target_weight=Decimal("0.25")),
        ),
        "band_pct": Decimal("0.05"),
        "rules": (
            TiltRule(
                condition="close < sma(5)",
                on_symbol="A",
                from_symbol="B",
                to_symbol="A",
                shift_pct=Decimal("0.08"),
            ),
        ),
        "designed_through": DESIGN_THROUGH,
    }
    fields.update(overrides)
    return AllocationCard(**fields)  # type: ignore[arg-type]


def _ladder_card(**overrides: object) -> LadderCard:
    fields: dict[str, object] = {
        "agent_id": "ladder-test",
        "display_name": "Ladder Test",
        "thesis": "a test thesis, written before the trading window ran",
        "signal_symbol": "SPY",
        "defensive_symbol": "SCHD",
        "bond_symbol": "IEF",
        "leveraged_symbol": "QLD",
        "base_defensive_weight": Decimal("0.60"),
        "base_bond_weight": Decimal("0.40"),
        "rungs": (
            Rung(drawdown=Decimal("-0.10"), leveraged_weight=Decimal("0.20")),
            Rung(drawdown=Decimal("-0.20"), leveraged_weight=Decimal("0.60")),
            Rung(drawdown=Decimal("-0.30"), leveraged_weight=Decimal("0.80")),
        ),
        "confirm_ma": 3,
        "ath_haircut": Decimal("0.5"),
        "recovery_gain": Decimal("0.10"),
        "recovery_sessions": 3,
        "designed_through": DESIGN_THROUGH,
    }
    fields.update(overrides)
    return LadderCard(**fields)  # type: ignore[arg-type]


def _ladder_trajectory(card: LadderCard, spy_closes: list[float]) -> list[float]:
    """Every session's leveraged-sleeve target weight, in order, from a fresh `WeightFn`."""
    closes = {
        "SPY": spy_closes,
        "SCHD": [50.0] * len(spy_closes),
        "IEF": [100.0] * len(spy_closes),
        "QLD": [40.0] * len(spy_closes),
    }
    weight_fn = card_weight_fn(card)
    return [weight_fn(i, closes)[card.leveraged_symbol] for i in range(len(spy_closes))]


# ---------------------------------------------------------------------------
# A condition this bridge cannot answer from closes alone raises, loudly, at construction time
# ---------------------------------------------------------------------------


class TestUnsupportedConditions:
    def test_a_price_field_other_than_close_raises(self) -> None:
        card = _alloc_card(
            rules=(
                TiltRule(
                    condition="volume > 0",
                    on_symbol="A",
                    from_symbol="B",
                    to_symbol="A",
                    shift_pct=Decimal("0.08"),
                ),
            )
        )
        with pytest.raises(UnsupportedConditionError, match="'volume'"):
            card_weight_fn(card)

    def test_atr_raises_because_it_needs_high_and_low(self) -> None:
        """The task brief's own example: `atr(14) > close * 0.018` needs high/low, which
        `contributions.simulate` never supplies."""
        card = _alloc_card(
            rules=(
                TiltRule(
                    condition="atr(14) > close * 0.018",
                    on_symbol="A",
                    from_symbol="B",
                    to_symbol="A",
                    shift_pct=Decimal("0.08"),
                ),
            )
        )
        with pytest.raises(UnsupportedConditionError, match="'atr'"):
            card_weight_fn(card)

    def test_vwap_raises_because_it_needs_high_low_and_volume(self) -> None:
        card = _alloc_card(
            rules=(
                TiltRule(
                    condition="close > vwap(session)",
                    on_symbol="A",
                    from_symbol="B",
                    to_symbol="A",
                    shift_pct=Decimal("0.08"),
                ),
            )
        )
        with pytest.raises(UnsupportedConditionError, match="'vwap'"):
            card_weight_fn(card)

    def test_the_two_conditions_the_real_qld_schd_sgov_card_uses_both_construct_cleanly(self) -> None:
        """`close < sma(150)` and `close > bb_upper(20,2)` -- the two conditions the only allocation
        card in the library today actually uses -- must not raise."""
        card = _alloc_card(
            rules=(
                TiltRule(
                    condition="close < sma(150)",
                    on_symbol="A",
                    from_symbol="B",
                    to_symbol="A",
                    shift_pct=Decimal("0.08"),
                ),
                TiltRule(
                    condition="close > bb_upper(20,2)",
                    on_symbol="A",
                    from_symbol="A",
                    to_symbol="C",
                    shift_pct=Decimal("0.08"),
                ),
            )
        )
        card_weight_fn(card)  # must not raise

    def test_an_unparseable_condition_raises_unsupported_not_a_bare_syntax_error(self) -> None:
        """A malformed condition should still surface through this bridge's own exception type, not
        leak `app.rules.grammar.RuleSyntaxError` past this module's boundary uncaught."""
        card = _alloc_card(
            rules=(
                TiltRule(
                    condition="close << 5",  # not a real operator
                    on_symbol="A",
                    from_symbol="B",
                    to_symbol="A",
                    shift_pct=Decimal("0.08"),
                ),
            )
        )
        with pytest.raises(UnsupportedConditionError):
            card_weight_fn(card)


# ---------------------------------------------------------------------------
# The allocation bridge matches the engine's own functions, not just hand-checked arithmetic
# ---------------------------------------------------------------------------


class TestAllocationWeightFnMatchesEngine:
    def test_a_firing_rule_matches_build_signal_table_and_target_weights(self, settings) -> None:
        """Ten sessions of A flat at 100, dropping to 80 on the last one -- `sma(5)` on that last
        session is `mean(100,100,100,100,80) = 96`, and `80 < 96` fires. Computed two independent
        ways: through this bridge from a bare closes list, and through the engine's own
        `_build_signal_table` + `_target_weights` against synthetic bars for the same prices. Both
        must agree exactly."""
        card = _alloc_card()
        dates = _weekdays(dt.date(2026, 1, 5), 10)
        closes_a = [100.0] * 9 + [80.0]
        decided_on = dates[-1]

        # -- the bridge, from closes alone --------------------------------------------------------
        closes = {"A": closes_a, "B": [100.0] * 10, "C": [100.0] * 10}
        weight_fn = card_weight_fn(card)
        bridge_weights = weight_fn(9, closes)

        # -- the engine, from stored bars --------------------------------------------------------
        _write_bars(settings, "A", closes_a, dates)
        tree = grammar.parse(card.rules[0].condition)
        table = allocation._build_signal_table(tree, ("A",), settings=settings, through=decided_on)
        engine_weights = allocation._target_weights(card, [table], [None], decided_on)

        assert bridge_weights == {k: float(v) for k, v in engine_weights.items()}
        assert bridge_weights == {"A": pytest.approx(0.48), "B": pytest.approx(0.27), "C": 0.25}

    def test_a_rule_that_does_not_fire_leaves_base_weights_untouched(self, settings) -> None:
        card = _alloc_card()
        dates = _weekdays(dt.date(2026, 1, 5), 10)
        closes_a = [100.0] * 10  # flat -- close is never below its own sma(5)
        decided_on = dates[-1]

        closes = {"A": closes_a, "B": [100.0] * 10, "C": [100.0] * 10}
        weight_fn = card_weight_fn(card)
        bridge_weights = weight_fn(9, closes)

        _write_bars(settings, "A", closes_a, dates)
        tree = grammar.parse(card.rules[0].condition)
        table = allocation._build_signal_table(tree, ("A",), settings=settings, through=decided_on)
        engine_weights = allocation._target_weights(card, [table], [None], decided_on)

        assert bridge_weights == {k: float(v) for k, v in engine_weights.items()}
        assert bridge_weights == {"A": 0.4, "B": 0.35, "C": 0.25}

    def test_two_rules_apply_in_order_against_each_others_output(self) -> None:
        """The second rule reads the first rule's *output*, not the base weight -- see
        `TiltRule`'s own docstring. Mirrors `test_allocation_card.py::TestTiltRuleFiring`'s identical
        scenario, through the bridge instead of a manufactured `_SignalTable`."""
        card = _alloc_card(
            rules=(
                TiltRule(
                    condition="close < sma(5)",
                    on_symbol="A",
                    from_symbol="B",
                    to_symbol="A",
                    shift_pct=Decimal("0.08"),
                ),
                TiltRule(
                    condition="close < sma(5)",
                    on_symbol="A",
                    from_symbol="B",
                    to_symbol="C",
                    shift_pct=Decimal("0.30"),  # more than B has left after the first rule (0.27)
                ),
            )
        )
        closes_a = [100.0] * 9 + [80.0]  # fires both rules on the last session
        closes = {"A": closes_a, "B": [100.0] * 10, "C": [100.0] * 10}
        weight_fn = card_weight_fn(card)

        weights = weight_fn(9, closes)

        assert weights["A"] == pytest.approx(0.48)  # 0.4 + 0.08, from the first rule only
        assert weights["B"] == pytest.approx(0.0)  # 0.35 - 0.08 - 0.27(clamped), never negative
        assert weights["C"] == pytest.approx(0.52)  # 0.25 + 0.27 (all B had left, not the full 0.30)
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_a_shift_larger_than_the_source_sleeve_is_clamped_not_negative(self) -> None:
        card = _alloc_card(
            sleeves=(
                Sleeve(symbol="A", target_weight=Decimal("0.9")),
                Sleeve(symbol="B", target_weight=Decimal("0.1")),
            ),
            rules=(
                TiltRule(
                    condition="close < sma(5)",
                    on_symbol="A",
                    from_symbol="B",
                    to_symbol="A",
                    shift_pct=Decimal("0.5"),  # larger than B's own 0.1 target
                ),
            ),
        )
        closes_a = [100.0] * 9 + [80.0]
        closes = {"A": closes_a, "B": [100.0] * 10}
        weight_fn = card_weight_fn(card)

        weights = weight_fn(9, closes)

        assert weights["B"] == 0.0  # clamped, never negative
        assert weights["A"] == 1.0
        assert sum(weights.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# _ladder_confirmed matches ladder._confirmed exactly, proven rather than assumed
# ---------------------------------------------------------------------------


class TestConfirmedMatchesEngine:
    def test_confirmed_true_case_matches(self, settings) -> None:
        card = _ladder_card(confirm_ma=3)
        dates = _weekdays(dt.date(2026, 1, 5), 3)
        closes = [86.0, 88.0, 90.0]  # avg = 88; 90 > 88
        _write_bars(settings, "SPY", closes, dates)
        from app.paper.marketdata import AsOfMarket

        market = AsOfMarket(as_of=dates[-1], settings=settings)

        assert ladder._confirmed(card, market) is True
        assert weightfn._ladder_confirmed(card.confirm_ma, closes) is True

    def test_confirmed_false_case_matches(self, settings) -> None:
        card = _ladder_card(confirm_ma=3)
        dates = _weekdays(dt.date(2026, 1, 5), 3)
        closes = [100.0, 100.0, 86.0]  # avg = 95.33; 86 < 95.33
        _write_bars(settings, "SPY", closes, dates)
        from app.paper.marketdata import AsOfMarket

        market = AsOfMarket(as_of=dates[-1], settings=settings)

        assert ladder._confirmed(card, market) is False
        assert weightfn._ladder_confirmed(card.confirm_ma, closes) is False

    def test_not_enough_history_matches(self, settings) -> None:
        card = _ladder_card(confirm_ma=3)
        dates = _weekdays(dt.date(2026, 1, 5), 2)
        closes = [100.0, 100.0]
        _write_bars(settings, "SPY", closes, dates)
        from app.paper.marketdata import AsOfMarket

        market = AsOfMarket(as_of=dates[-1], settings=settings)

        assert ladder._confirmed(card, market) is False
        assert weightfn._ladder_confirmed(card.confirm_ma, closes) is False


# ---------------------------------------------------------------------------
# The ladder bridge's state machine matches the same price paths test_ladder_card.py already pinned
# ---------------------------------------------------------------------------


class TestLadderStateMachineMatchesReferenceScenarios:
    def test_confirmation_gates_the_fire(self) -> None:
        """Mirrors `test_ladder_card.py::TestConfirmationGatesTheFire` -- a breach with no confirmed
        bounce produces no trade; the same breach confirmed one session later fires."""
        card = _ladder_card()
        trajectory = _ladder_trajectory(card, [100.0, 100.0, 86.0, 88.0, 90.0, 90.0])
        assert trajectory == [0.0, 0.0, 0.0, 0.0, 0.20, 0.20]

    def test_gap_through_skips_straight_to_the_deepest_breached_rung(self) -> None:
        """Mirrors `test_ladder_card.py::TestGapThrough` -- a confirmed breach past the second
        rung's depth fires straight to 60%, the first rung's 20% never having armed."""
        card = _ladder_card()
        trajectory = _ladder_trajectory(card, [100.0, 100.0, 90.0, 76.0, 78.0, 80.0, 80.0])
        assert trajectory == [0.0, 0.0, 0.0, 0.0, 0.0, 0.60, 0.60]

    def test_once_per_cycle_arming_suppresses_a_chop_around_the_same_band(self) -> None:
        """Mirrors `test_ladder_card.py::TestOncePerCycleArming` -- once armed, chopping back into
        and out of the same drawdown band produces no further transition."""
        card = _ladder_card()
        trajectory = _ladder_trajectory(card, [100.0, 100.0, 86.0, 88.0, 90.0, 94.0, 88.0, 88.0])
        assert trajectory == [0.0, 0.0, 0.0, 0.0, 0.20, 0.20, 0.20, 0.20]

    def test_a_new_high_halves_then_a_further_gain_fully_exits(self) -> None:
        """Mirrors `test_ladder_card.py::TestNewHighHalvesThenFullyExits` -- fires at 20%, a new high
        halves it to 10%, a further new high with no qualifying gain does nothing, and a session 10%
        above the cycle's own starting high fully exits and re-arms."""
        card = _ladder_card()
        trajectory = _ladder_trajectory(
            card, [100.0, 100.0, 86.0, 88.0, 90.0, 92.0, 101.0, 108.0, 111.0, 111.0]
        )
        assert trajectory == [0.0, 0.0, 0.0, 0.0, 0.20, 0.20, 0.10, 0.10, 0.0, 0.0]

    def test_recovery_timeout_exits_even_without_the_gain_target(self) -> None:
        """Mirrors `test_ladder_card.py::TestRecoveryTimeoutAlsoExits` -- halved at the new high,
        then `recovery_sessions` later exits anyway despite never reaching the gain target."""
        card = _ladder_card(recovery_sessions=3)
        trajectory = _ladder_trajectory(
            card, [100.0, 100.0, 86.0, 88.0, 90.0, 92.0, 101.0, 101.0, 101.0, 101.0, 101.0]
        )
        assert trajectory == [0.0, 0.0, 0.0, 0.0, 0.20, 0.20, 0.10, 0.10, 0.10, 0.0, 0.0]

    def test_a_monotonic_decline_that_never_confirms_never_arms(self) -> None:
        """Mirrors `test_ladder_card.py::TestNeverConfirmedNeverFires` -- the single most important
        rule (see `ladder.py`'s own module docstring): strictly falling every session never confirms,
        so the ladder never leverages up however deep the drawdown gets."""
        card = _ladder_card()
        trajectory = _ladder_trajectory(card, [100.0, 100.0, 94.0, 88.0, 82.0, 75.0])
        assert trajectory == [0.0] * 6

    def test_sleeve_targets_sum_to_one_at_every_session(self) -> None:
        card = _ladder_card()
        closes = {
            "SPY": [100.0, 100.0, 86.0, 88.0, 90.0, 90.0],
            "SCHD": [50.0] * 6,
            "IEF": [100.0] * 6,
            "QLD": [40.0] * 6,
        }
        weight_fn = card_weight_fn(card)
        for i in range(6):
            weights = weight_fn(i, closes)
            assert sum(weights.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# A LadderCard's signal_symbol is priced but never traded
# ---------------------------------------------------------------------------


class TestLadderExcludesSignalSymbol:
    def test_signal_symbol_never_appears_as_a_key(self) -> None:
        card = _ladder_card()
        closes = {
            "SPY": [100.0, 100.0, 86.0, 88.0, 90.0, 90.0],
            "SCHD": [50.0] * 6,
            "IEF": [100.0] * 6,
            "QLD": [40.0] * 6,
        }
        weight_fn = card_weight_fn(card)
        for i in range(6):
            assert "SPY" not in weight_fn(i, closes)


# ---------------------------------------------------------------------------
# No lookahead: a weight for session i must not change if every close after i is corrupted
# ---------------------------------------------------------------------------


class TestNoLookahead:
    def test_allocation_weight_is_unaffected_by_corrupting_future_closes(self) -> None:
        card = _alloc_card()
        closes_a = [100.0] * 9 + [80.0] + [100.0] * 5  # session 9 fires; sessions 10-14 exist too
        closes = {"A": closes_a, "B": [100.0] * 15, "C": [100.0] * 15}
        weight_fn = card_weight_fn(card)

        honest = weight_fn(9, closes)

        corrupted = {
            "A": closes_a[:10] + [1e9] * 5,
            "B": [100.0] * 10 + [1e9] * 5,
            "C": [100.0] * 10 + [1e9] * 5,
        }
        assert weight_fn(9, corrupted) == honest

    def test_ladder_weight_is_unaffected_by_corrupting_future_closes(self) -> None:
        """The ladder bridge is stateful (see `weightfn._ladder_weight_fn`'s own docstring), so this
        cannot replay the same closure twice at the same `i` -- two *independent* `WeightFn` instances
        are stepped through identical sessions `0..i`, one fed closes that are corrupted only after
        `i`, and their outputs at `i` must still agree."""
        card = _ladder_card()
        honest_spy = [100.0, 100.0, 86.0, 88.0, 90.0, 90.0, 92.0, 95.0]
        corrupted_spy = [*honest_spy[:6], 1.0, 999.0]  # sessions 0-5 identical, 6-7 corrupted
        decide_at = 5

        def build(spy_closes: list[float]) -> tuple[weightfn.WeightFn, dict[str, list[float]]]:
            closes = {
                "SPY": spy_closes,
                "SCHD": [50.0] * len(spy_closes),
                "IEF": [100.0] * len(spy_closes),
                "QLD": [40.0] * len(spy_closes),
            }
            return card_weight_fn(card), closes

        fn_honest, closes_honest = build(honest_spy)
        fn_corrupted, closes_corrupted = build(corrupted_spy)

        result_honest = None
        result_corrupted = None
        for i in range(decide_at + 1):
            result_honest = fn_honest(i, closes_honest)
            result_corrupted = fn_corrupted(i, closes_corrupted)

        assert result_honest == result_corrupted


class TestShiftExprMatchesEngine:
    """A continuously-sized tilt must be computed identically by the bridge and the engine.

    This matters more than the equivalent test for a *condition*. A condition the bridge got wrong
    fires on the wrong days and shows up as a different trade list; a magnitude it got wrong keeps
    every trade date identical and moves only the sizes. Nothing downstream would notice.
    """

    @staticmethod
    def _expr_card(expr: str) -> AllocationCard:
        return AllocationCard(
            agent_id="w-expr",
            display_name="continuously sized tilt",
            thesis="A test card whose tilt is sized by an expression rather than a constant. " * 3,
            sleeves=(
                Sleeve(symbol="A", target_weight=Decimal("0.4")),
                Sleeve(symbol="B", target_weight=Decimal("0.6")),
            ),
            band_pct=Decimal("0.05"),
            rules=(
                TiltRule(
                    condition="close > 0",
                    on_symbol="A",
                    from_symbol="B",
                    to_symbol="A",
                    shift_expr=expr,
                ),
            ),
            designed_through=DESIGN_THROUGH,
        )

    def test_the_bridge_and_the_engine_agree_on_a_computed_shift(self, settings) -> None:
        """`close / 1000` on a last close of 120 is a shift of 0.12: A 0.4 -> 0.52, B 0.6 -> 0.48."""
        card = self._expr_card("close / 1000")
        dates = _weekdays(dt.date(2026, 1, 5), 10)
        closes_a = [100.0] * 9 + [120.0]
        decided_on = dates[-1]

        bridge = card_weight_fn(card)(9, {"A": closes_a, "B": [100.0] * 10})

        _write_bars(settings, "A", closes_a, dates)
        cond = grammar.parse(card.rules[0].condition)
        mag = grammar.parse_ranking(card.rules[0].shift_expr)
        table = allocation._build_signal_table(cond, ("A",), settings=settings, through=decided_on)
        mag_table = allocation._build_rank_table(mag, ("A",), settings=settings, through=decided_on)
        engine = allocation._target_weights(card, [table], [mag_table], decided_on)

        assert bridge == {k: float(v) for k, v in engine.items()}
        assert bridge == {"A": pytest.approx(0.52), "B": pytest.approx(0.48)}

    def test_a_shift_expr_the_bridge_cannot_compute_is_refused_loudly(self) -> None:
        """`atr` needs `high`/`low`, which `contributions.simulate` never supplies. The bridge must
        say so at construction rather than quietly reproducing something other than the engine --
        and `0.4 * atr(20) / close` is the *obvious* volatility-sizing form, so this is the first
        expression a real card would reach for."""
        card = self._expr_card("0.4 * atr(20) / close")
        with pytest.raises(UnsupportedConditionError, match="atr"):
            card_weight_fn(card)

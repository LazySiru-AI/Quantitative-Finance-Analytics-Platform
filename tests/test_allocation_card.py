"""Tests for `app.tournament.allocation`: the continuously-rebalanced multi-sleeve card shape.

Follows `tests/test_tournament_runner.py`'s own convention -- synthetic bars written into the temp
store via the `settings` fixture, every price engineered so a specific event (an initial rebalance,
a drift that stays inside the band, a drift that breaches it, a tilt rule firing) happens on a known
session with hand-checked arithmetic, rather than asserting against whatever the code under test
happens to produce.

Each test pins one defect this module's design has to avoid:

* `TestWeightsMustSumToOne` -- a card whose sleeve weights do not sum to exactly `1` must be
  *rejected*, not silently renormalised into a different strategy the analyst never wrote (see
  `AllocationCard._weights_are_a_complete_partition`'s own docstring for the concrete slip a silent
  renormalisation would paper over).
* `TestBandSuppressesChurn` -- the entire reason `band_pct` exists (see `AllocationCard.band_pct`'s
  docstring) is that a mock broker charges slippage and floors whole shares on every fill, so a drift
  small enough to be measurement noise must not turn into an order at all. Pinned twice: once as a
  direct, order-free unit test of `allocation._rebalance_moves` (so "the band suppresses a given
  amount of drift" is checkable without a session loop), and once end to end through
  `run_allocation`, where a drift that stays inside the band across the whole run must leave the
  book's `trades` exactly as long as its sleeve count (only the closing "still held" trades) -- no
  interim `"rebalance_trim"` at all.
* `TestBandBreachTradesBackTowardTarget` -- the opposite side of the same mechanism: a drift that
  *does* exceed the band must produce an order that shrinks it, sized and priced by hand.
* `TestTiltRuleFiring` -- a firing rule must move weight between exactly the two sleeves it names,
  by exactly `shift_pct`, and the sum of every sleeve's target must stay exactly `1` no matter how
  many rules fire (see `TiltRule`'s own docstring on why the shift is clamped and why order matters).
* `TestAllocationResultShape` -- `run_allocation` cannot return
  `app.tournament.models.AgentResult` at all (see `allocation.py`'s own module docstring for exactly
  why: pydantic rejects a differently-shaped `BaseModel` for a field typed to a specific one), so this
  class pins that the substitute, `AllocationResult`, still carries every field the tournament's own
  scorers read by plain attribute access.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pandas as pd
import pytest
from pydantic import ValidationError

from app.db import duck
from app.indicators import registry as indicator_registry
from app.indicators.base import IndicatorSpec, Pane, ParamKind, ParamSpec
from app.market.models import BAR_COLUMNS, Interval
from app.paper.marketdata import AsOfMarket, Session
from app.paper.paperbroker import Mandate
from app.rules import grammar as rule_grammar
from app.tournament import allocation
from app.tournament.allocation import AllocationCard, AllocationResult, Sleeve, TiltRule
from app.tournament.models import DESIGN_THROUGH

# ---------------------------------------------------------------------------
# Fixtures shared by every test in this file -- lifted from tests/test_tournament_runner.py's own
# helpers of the same name, which this file does not import (that module has no `__init__.py`-backed
# package surface to import small test helpers from; every test file in this suite that needs them
# defines its own copy, e.g. tests/test_paperdesk.py's `_write_bars`).
# ---------------------------------------------------------------------------


def _weekdays(anchor: dt.date, count: int) -> list[dt.date]:
    """`count` weekdays starting at `anchor` (included if itself a weekday)."""
    dates: list[dt.date] = []
    day = anchor
    while len(dates) < count:
        if day.weekday() < 5:
            dates.append(day)
        day += dt.timedelta(days=1)
    return dates


def _write_bars(settings, symbol: str, prices: dict[dt.date, tuple[float, float]]) -> None:
    """Write one daily bar per `(open, close)` in `prices`. `high`/`low` bracket the two generously --
    nothing in this module ever reads a bar's high/low, only its open and close (see
    `AsOfMarket.close`/`.open_on`), so their exact values are inert here."""
    dates = sorted(prices)
    opens = [prices[d][0] for d in dates]
    closes = [prices[d][1] for d in dates]
    frame = pd.DataFrame(
        {
            "ts": pd.Series(
                [dt.datetime.combine(d, dt.time.min, tzinfo=dt.UTC) for d in dates],
                dtype="datetime64[us, UTC]",
            ),
            "open": opens,
            "high": [max(o, c) + 5.0 for o, c in zip(opens, closes, strict=True)],
            "low": [min(o, c) - 5.0 for o, c in zip(opens, closes, strict=True)],
            "close": closes,
            "adj_close": closes,
            "volume": [1_000_000] * len(dates),
        },
        columns=list(BAR_COLUMNS),
    )
    with duck.connect() as conn:
        duck.write_bars(conn, settings.bars_dir, symbol, Interval.DAY, frame)


def _flat(dates: list[dt.date], price: float) -> dict[dt.date, tuple[float, float]]:
    return dict.fromkeys(dates, (price, price))


def _mandate(**overrides: object) -> Mandate:
    """Every friction zeroed out by default, so the arithmetic in every hand-checked test below is
    exact -- the same convention `test_tournament_runner.py::_mandate` uses, for the same reason."""
    fields: dict[str, object] = {
        "persona_id": "test-agent",
        "display_name": "Test Agent",
        "account_id": "acct-1",
        "account_label": "Test Account",
        "starting_cash": Decimal("10000.00"),
        "allow_fractional_shares": False,
        "max_positions": 10,
        "max_single_name_weight": Decimal("1.00"),
        "min_clip_notional": Decimal("1.00"),
        "min_cash": Decimal("0.00"),
        "settlement_days": 1,
        "slippage_bps": Decimal("0"),
        "commission_per_trade": Decimal("0"),
        "sec_fee_rate": Decimal("0"),
        "taf_per_share": Decimal("0"),
        "taf_cap": Decimal("0"),
    }
    fields.update(overrides)
    return Mandate(**fields)  # type: ignore[arg-type]


def _card(**overrides: object) -> AllocationCard:
    fields: dict[str, object] = {
        "agent_id": "alloc-1",
        "display_name": "Allocation One",
        "thesis": "a test thesis, written before the trading window ran",
        "sleeves": (
            Sleeve(symbol="A", target_weight=Decimal("0.5")),
            Sleeve(symbol="B", target_weight=Decimal("0.5")),
        ),
        "band_pct": Decimal("0.05"),
        "rules": (),
        "designed_through": DESIGN_THROUGH,
    }
    fields.update(overrides)
    return AllocationCard(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Weights must sum to exactly one -- never silently normalised
# ---------------------------------------------------------------------------


class TestWeightsMustSumToOne:
    def test_weights_summing_to_less_than_one_are_rejected(self) -> None:
        """0.5 + 0.3 = 0.8, ten points of the book unaccounted for. If this silently renormalised to
        (0.625, 0.375) the card that actually ran would not be the card the analyst wrote -- see
        `AllocationCard._weights_are_a_complete_partition`'s own docstring for this exact scenario."""
        with pytest.raises(ValueError, match="sum to"):
            _card(
                sleeves=(
                    Sleeve(symbol="A", target_weight=Decimal("0.5")),
                    Sleeve(symbol="B", target_weight=Decimal("0.3")),
                )
            )

    def test_weights_summing_to_more_than_one_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="sum to"):
            _card(
                sleeves=(
                    Sleeve(symbol="A", target_weight=Decimal("0.6")),
                    Sleeve(symbol="B", target_weight=Decimal("0.6")),
                )
            )

    def test_exact_decimal_sum_is_accepted(self) -> None:
        """The positive control: three weights that sum to exactly `1` via `Decimal` arithmetic (no
        binary-float rounding to excuse) construct without complaint."""
        card = _card(
            sleeves=(
                Sleeve(symbol="A", target_weight=Decimal("0.35")),
                Sleeve(symbol="B", target_weight=Decimal("0.40")),
                Sleeve(symbol="C", target_weight=Decimal("0.25")),
            )
        )
        assert card.universe == ("A", "B", "C")

    def test_rules_must_reference_a_sleeve_on_the_same_card(self) -> None:
        """A rule naming a symbol the card does not hold would be reallocating the book against a
        signal, or into a sleeve, nothing here is priced against."""
        with pytest.raises(ValueError, match="not one of this card's sleeves"):
            _card(
                rules=(
                    TiltRule(
                        condition="close > 0",
                        on_symbol="ZZZZ",
                        from_symbol="A",
                        to_symbol="B",
                        shift_pct=Decimal("0.1"),
                    ),
                )
            )

    def test_a_rule_cannot_shift_a_sleeve_into_itself(self) -> None:
        with pytest.raises(ValueError, match="changes nothing"):
            TiltRule(
                condition="close > 0",
                on_symbol="A",
                from_symbol="A",
                to_symbol="A",
                shift_pct=Decimal("0.1"),
            )


# ---------------------------------------------------------------------------
# _rebalance_moves -- the band, in isolation, with no broker and no session loop
# ---------------------------------------------------------------------------


class TestRebalanceMovesIsolated:
    """Direct tests of `allocation._rebalance_moves`: given a session's already-computed targets,
    actual weights and equity, does the band gate correctly -- with no `PaperBroker`, no fills, no
    rounding to blur the boundary. `TestBandSuppressesChurn` below repeats the same question end to
    end through `run_allocation`; this class is the version that could not possibly pass for the
    wrong reason (e.g. an order that was submitted but happened to round down to zero shares)."""

    def test_drift_inside_the_band_produces_no_moves(self) -> None:
        card = _card(band_pct=Decimal("0.05"))
        targets = {"A": Decimal("0.5"), "B": Decimal("0.5")}
        actual = {"A": Decimal("0.53"), "B": Decimal("0.47")}  # 3 points off, band is 5

        sells, buys = allocation._rebalance_moves(card, targets, actual, Decimal("10000"))

        assert sells == []
        assert buys == []

    def test_drift_exactly_at_the_band_boundary_is_not_a_breach(self) -> None:
        """The comparison is `>`, not `>=` -- see `_rebalance_moves`'s own loop (`if abs(actual -
        target) <= card.band_pct: continue`) -- so drift *equal* to the band is still inside it."""
        card = _card(band_pct=Decimal("0.05"))
        targets = {"A": Decimal("0.5"), "B": Decimal("0.5")}
        actual = {"A": Decimal("0.55"), "B": Decimal("0.45")}

        sells, buys = allocation._rebalance_moves(card, targets, actual, Decimal("10000"))

        assert sells == []
        assert buys == []

    def test_drift_past_the_band_produces_a_sell_and_a_buy(self) -> None:
        card = _card(band_pct=Decimal("0.05"))
        targets = {"A": Decimal("0.5"), "B": Decimal("0.5")}
        actual = {"A": Decimal("0.6"), "B": Decimal("0.4")}  # 10 points off, band is 5
        equity = Decimal("10000")

        sells, buys = allocation._rebalance_moves(card, targets, actual, equity)

        assert [s[0] for s in sells] == ["A"]
        assert sells[0][1] == (Decimal("0.5") - Decimal("0.6")) * equity  # -1000: trim A
        assert [b[0] for b in buys] == ["B"]
        assert buys[0][1] == (Decimal("0.5") - Decimal("0.4")) * equity  # +1000: top up B


# ---------------------------------------------------------------------------
# End to end: the band suppresses churn through a full run
# ---------------------------------------------------------------------------


class TestBandSuppressesChurn:
    def test_small_drift_produces_only_the_initial_fill_and_no_interim_trims(self, settings) -> None:
        """Two sleeves, initially bought at session 1, then a small (0.75-point) drift that stays
        inside a 5-point band for the rest of the run. `result.trades` must be exactly two entries
        (both `"open_at_end"`, one per sleeve) -- proof that no rebalancing order was ever submitted
        after the initial fill, not merely that none happened to round to zero shares.
        """
        dates = _weekdays(dt.date(2026, 1, 5), 8)
        lead_in, trade_dates = dates[:5], dates[5:]
        d1, d2, d3 = trade_dates

        _write_bars(settings, "SPY", _flat(dates, 100.0))
        _write_bars(
            settings,
            "A",
            {**_flat(lead_in, 100.0), d1: (100.0, 100.0), d2: (100.0, 103.0), d3: (103.0, 103.0)},
        )
        _write_bars(settings, "B", _flat(dates, 100.0))

        mandate = _mandate()
        card = _card(band_pct=Decimal("0.05"))

        result = allocation.run_allocation(
            card, settings=settings, mandate=mandate, start=d1, end=d3
        )

        assert result.rejections == ()
        assert len(result.trades) == 2
        assert {t.exit_reason for t in result.trades} == {"open_at_end"}

        # Hand-checked: both sleeves bought 50 shares at 100 on d1 (0.5 * 10000 / 100). By d3's
        # close, A has drifted to 103 while B stayed at 100 -- weight_A = 50*103 / (50*103+50*100)
        # = 5150/10150 ~= 0.5074, 0.74 points off a 0.5 target, comfortably inside the 5-point band.
        by_symbol = {t.symbol: t for t in result.trades}
        assert by_symbol["A"].quantity == Decimal("50")
        assert by_symbol["B"].quantity == Decimal("50")
        assert result.starting_equity == Decimal("10000.00")
        assert result.ending_equity == Decimal("10150.00")  # 50*103 + 50*100


# ---------------------------------------------------------------------------
# End to end: a band breach trades a sleeve back toward its target
# ---------------------------------------------------------------------------


class TestBandBreachTradesBackTowardTarget:
    def test_an_overweight_sleeve_is_trimmed_and_an_underweight_one_topped_up(self, settings) -> None:
        """A's price runs from 100 to 150 while B stays flat, pushing A's weight to 0.6 (10 points
        over a 0.5 target, past the 5-point band) by the session-3 decision. That session must
        produce exactly one `"rebalance_trim"` sell of A (trimming it back toward target) and fold an
        equal-and-opposite top-up into B -- both orders filling in the same session, sells before
        buys, so the sell's freed cash funds the buy (see `run_allocation`'s own docstring on why
        sells are submitted first).
        """
        dates = _weekdays(dt.date(2026, 1, 5), 8)
        lead_in, trade_dates = dates[:5], dates[5:]
        d1, d2, d3 = trade_dates

        _write_bars(settings, "SPY", _flat(dates, 100.0))
        _write_bars(
            settings,
            "A",
            {**_flat(lead_in, 100.0), d1: (100.0, 100.0), d2: (100.0, 150.0), d3: (150.0, 150.0)},
        )
        _write_bars(settings, "B", _flat(dates, 100.0))

        # `settlement_days=0`, not this file's usual default of 1: `PaperBroker._apply` marks a
        # sell's proceeds unsettled until `settlement_days` business days after the fill (see its own
        # docstring on preventing a cash-account good-faith violation), so with the default of 1 the
        # same-session buy below would be rejected for insufficient *settled* cash even though total
        # cash is sufficient -- an authentic broker constraint, just not the one this test is about.
        # Settling instantly isolates the rebalancing arithmetic this test actually exists to check.
        mandate = _mandate(settlement_days=0)
        card = _card(band_pct=Decimal("0.05"))

        result = allocation.run_allocation(
            card, settings=settings, mandate=mandate, start=d1, end=d3
        )

        assert result.rejections == ()

        trims = [t for t in result.trades if t.exit_reason == "rebalance_trim"]
        assert len(trims) == 1
        trim = trims[0]
        assert trim.symbol == "A"
        # Decision equity at d3 (marked off d2's close): 50*150 + 50*100 = 12500. Target 0.5 ->
        # desired value 6250, actual value 7500 -> sell notional 1250 at A's decision close (150) ->
        # floor(1250/150) = 8 shares.
        assert trim.quantity == Decimal("8")
        # pnl = (fill_price - avg_cost) * qty = (150 - 100) * 8 = 400, no fees in this mandate.
        assert trim.pnl == Decimal("400.00")
        assert trim.return_pct == Decimal("400.00") / (Decimal("100") * Decimal("8"))

        # B's mirror image: 1250 / 100 = 12 shares bought, using cash the A trim just freed.
        opens = [t for t in result.trades if t.symbol == "B"]
        assert len(opens) == 1
        assert opens[0].quantity == Decimal("62")  # 50 initial + 12 topped up
        assert opens[0].exit_reason == "open_at_end"

        assert result.ending_equity == Decimal("12500.00")  # 42*150 + 62*100, unchanged by the trade


# ---------------------------------------------------------------------------
# A tilt rule firing shifts target weight between exactly the two sleeves it names
# ---------------------------------------------------------------------------


class TestTiltRuleFiring:
    def test_firing_rule_shifts_weight_and_the_sum_stays_one(self) -> None:
        card = _card(
            sleeves=(
                Sleeve(symbol="A", target_weight=Decimal("0.4")),
                Sleeve(symbol="B", target_weight=Decimal("0.35")),
                Sleeve(symbol="C", target_weight=Decimal("0.25")),
            ),
            rules=(
                TiltRule(
                    condition="close < sma(5)",
                    on_symbol="A",
                    from_symbol="B",
                    to_symbol="A",
                    shift_pct=Decimal("0.08"),
                ),
            ),
        )
        firing_table = allocation._SignalTable({"A": pd.Series([True], index=[dt.date(2026, 1, 10)])})

        weights = allocation._target_weights(card, [firing_table], [None], dt.date(2026, 1, 10))

        assert weights == {
            "A": Decimal("0.48"),  # 0.4 + 0.08
            "B": Decimal("0.27"),  # 0.35 - 0.08
            "C": Decimal("0.25"),  # untouched
        }
        assert sum(weights.values()) == Decimal("1")

    def test_a_rule_that_does_not_fire_leaves_the_base_weights_untouched(self) -> None:
        card = _card(
            rules=(
                TiltRule(
                    condition="close < sma(5)",
                    on_symbol="A",
                    from_symbol="B",
                    to_symbol="A",
                    shift_pct=Decimal("0.08"),
                ),
            )
        )
        not_firing_table = allocation._SignalTable(
            {"A": pd.Series([False], index=[dt.date(2026, 1, 10)])}
        )

        weights = allocation._target_weights(card, [not_firing_table], [None], dt.date(2026, 1, 10))

        assert weights == {"A": Decimal("0.5"), "B": Decimal("0.5")}

    def test_a_shift_larger_than_the_source_sleeve_is_clamped_not_negative(self) -> None:
        """`shift_pct` is capped at `1` by `TiltRule`'s own validator, but nothing stops a card from
        naming a `from_symbol` whose *current* target (after earlier rules already trimmed it) is
        smaller than this rule's own `shift_pct`. `_target_weights` clamps via
        `min(rule.shift_pct, weights[rule.from_symbol])` rather than letting a sleeve's target go
        negative, which sum-preservation depends on (see `_target_weights`'s own docstring)."""
        card = _card(
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
        firing_table = allocation._SignalTable({"A": pd.Series([True], index=[dt.date(2026, 1, 10)])})

        weights = allocation._target_weights(card, [firing_table], [None], dt.date(2026, 1, 10))

        assert weights["B"] == Decimal("0")  # clamped, never negative
        assert weights["A"] == Decimal("1.0")
        assert sum(weights.values()) == Decimal("1.0")

    def test_two_rules_apply_in_order_against_each_others_output(self) -> None:
        """The second rule reads `weights["B"]` as the *first* rule left it (0.35 - 0.08 = 0.27), not
        the card's original 0.35 -- see `TiltRule`'s own docstring on why rules are not independent,
        simultaneous claims against the base weights."""
        card = _card(
            sleeves=(
                Sleeve(symbol="A", target_weight=Decimal("0.4")),
                Sleeve(symbol="B", target_weight=Decimal("0.35")),
                Sleeve(symbol="C", target_weight=Decimal("0.25")),
            ),
            rules=(
                TiltRule(
                    condition="close < sma(5)",
                    on_symbol="A",
                    from_symbol="B",
                    to_symbol="A",
                    shift_pct=Decimal("0.08"),
                ),
                TiltRule(
                    condition="close > bb_upper(20,2)",
                    on_symbol="A",
                    from_symbol="B",
                    to_symbol="C",
                    shift_pct=Decimal("0.30"),  # more than B has left after the first rule (0.27)
                ),
            ),
        )
        both_fire = allocation._SignalTable({"A": pd.Series([True], index=[dt.date(2026, 1, 10)])})

        weights = allocation._target_weights(card, [both_fire, both_fire], [None, None], dt.date(2026, 1, 10))

        assert weights["A"] == Decimal("0.48")  # 0.4 + 0.08, from the first rule only
        assert weights["B"] == Decimal("0")  # 0.35 - 0.08 - 0.27(clamped), never negative
        assert weights["C"] == Decimal("0.52")  # 0.25 + 0.27 (all B had left, not the full 0.30)
        assert sum(weights.values()) == Decimal("1.0")


# ---------------------------------------------------------------------------
# The lookahead guard is wired into this module's decision path too, not only runner.py's
# ---------------------------------------------------------------------------


class TestNoLookahead:
    def test_require_decision_market_is_reused_from_runner(self, settings) -> None:
        """`run_allocation` calls `runner._require_decision_market` directly (see the module
        docstring's "what is reused" section) rather than a second copy of the same assertion --
        pinned here so a future refactor that quietly forks the two cannot drift apart unnoticed."""
        session = Session(index=5, date=dt.date(2026, 3, 10), decided_on=dt.date(2026, 3, 9))
        same_day = AsOfMarket(as_of=session.date, settings=settings)

        with pytest.raises(allocation.LookaheadError):
            allocation._require_decision_market(same_day, session)


# ---------------------------------------------------------------------------
# AllocationResult carries every field the tournament's scorers read
# ---------------------------------------------------------------------------


class TestAllocationResultShape:
    """`run_allocation` cannot return `app.tournament.models.AgentResult` (see `allocation.py`'s own
    module docstring for why `card: StrategyCard` makes that impossible without modifying
    `models.py`), so this pins that its substitute, `AllocationResult`, still carries every field
    `app.tournament.scoring` and `strategy-program/tools/score.py` read off a result by plain
    attribute access -- checked directly against both files' source, not assumed."""

    def test_result_has_every_field_the_scorers_read(self, settings) -> None:
        dates = _weekdays(dt.date(2026, 1, 5), 8)
        trade_dates = dates[5:]
        d1, d3 = trade_dates[0], trade_dates[-1]

        _write_bars(settings, "SPY", _flat(dates, 100.0))
        _write_bars(settings, "A", _flat(dates, 100.0))
        _write_bars(settings, "B", _flat(dates, 100.0))

        mandate = _mandate()
        card = _card()

        result = allocation.run_allocation(
            card, settings=settings, mandate=mandate, start=d1, end=d3
        )

        assert isinstance(result, AllocationResult)
        assert result.card is card
        assert result.card.agent_id == "alloc-1"
        assert result.card.display_name == "Allocation One"

        assert result.sessions == 3
        assert result.starting_equity == Decimal("10000.00")
        assert result.ending_equity == Decimal("10000.00")  # perfectly flat prices throughout
        assert result.max_drawdown is not None
        assert result.capital_exposure is not None
        assert result.capital_exposure == pytest.approx(1.0, abs=0.01)  # fully invested, flat book
        assert result.benchmark_return == Decimal("0")  # SPY flat too
        assert isinstance(result.trades, tuple)
        assert len(result.trades) == 2  # one open_at_end per sleeve, nothing ever traded again
        assert result.rejections == ()


class TestBuyWithoutSellIsUnfundable:
    """`strategy-program/DEFECTS.md` D8 — a band breach can emit a buy with nothing sold to fund it.

    `_rebalance_moves` applies the band to each sleeve independently. That is symmetric per sleeve and
    asymmetric in aggregate: the overweight offsetting a breaching underweight can be **spread across
    several sleeves that are each inside the band**, so a buy is emitted and no sell is. The engine
    then submits an order it cannot pay for, the rejection leaves the sleeve underweight, and the same
    order is resubmitted every session — 59 rejections across 59 distinct sessions on the real
    `qld-schd-sgov` card, with the book never rebalancing again.

    **Every other test in this file uses two sleeves, which is why this ships.** With two sleeves the
    deviations are always equal and opposite — if A is five points under, B is five points over — so a
    buy always has a matching sell and the asymmetry cannot occur. It needs three or more.
    """

    #: Three sleeves at the real `qld-schd-sgov` weights. The module-level `_card` builder is
    #: two-sleeve, which is precisely the shape that cannot express this defect.
    def _card(self):
        return _card(
            sleeves=(
                Sleeve(symbol="QLD", target_weight=Decimal("0.43")),
                Sleeve(symbol="SCHD", target_weight=Decimal("0.32")),
                Sleeve(symbol="SGOV", target_weight=Decimal("0.25")),
            ),
            band_pct=Decimal("0.05"),
        )

    def test_the_breaching_buy_is_funded_by_the_non_breaching_overweights(self) -> None:
        """The D8 state, after the fix: QLD breaches on the underweight side and the two sleeves that
        are *inside* the band fund it, pro-rata to how overweight each is.

        Before the fix this returned one buy and zero sells; the engine then submitted $4,469.75
        against $73.69 of cash and re-submitted it every session for the rest of the run."""
        card = self._card()
        targets = {"QLD": Decimal("0.43"), "SCHD": Decimal("0.32"), "SGOV": Decimal("0.25")}
        actual = {"QLD": Decimal("0.3781"), "SCHD": Decimal("0.3320"), "SGOV": Decimal("0.2890")}

        sells, buys = allocation._rebalance_moves(card, targets, actual, Decimal("86548"))

        assert len(buys) == 1, "QLD breaches the band on the underweight side"
        assert {s for s, _d, _t in sells} == {"SCHD", "SGOV"}, (
            "both non-breaching overweights fund it -- neither crosses the band alone, which is "
            "exactly the case the old per-sleeve rule could not see"
        )
        by_symbol = {s: -d for s, d, _t in sells}
        # Pro-rata: SGOV is +0.0390 overweight against SCHD's +0.0120, so it contributes more.
        assert by_symbol["SGOV"] > by_symbol["SCHD"]
        ratio = by_symbol["SGOV"] / by_symbol["SCHD"]
        assert Decimal("3.1") < ratio < Decimal("3.4"), f"expected ~0.0390/0.0120 = 3.25, got {ratio}"

    def test_a_donor_is_never_sold_past_its_own_target(self) -> None:
        """Funding one breach must not create the next one. A donor is capped at its own overweight,
        so it can be brought back to target but never pushed under it."""
        card = self._card()
        targets = {"QLD": Decimal("0.43"), "SCHD": Decimal("0.32"), "SGOV": Decimal("0.25")}
        actual = {"QLD": Decimal("0.2000"), "SCHD": Decimal("0.3300"), "SGOV": Decimal("0.4700")}
        equity = Decimal("100000")

        sells, _buys = allocation._rebalance_moves(card, targets, actual, equity)

        for symbol, delta, _t in sells:
            overweight = (actual[symbol] - targets[symbol]) * equity
            assert -delta <= overweight + Decimal("0.01"), (
                f"{symbol} sold {-delta} against an overweight of only {overweight}"
            )

    def test_cash_is_spent_before_anything_is_sold(self) -> None:
        """A buy the account can already afford must not trigger a sale -- that would be turnover, and
        slippage, bought for nothing."""
        card = self._card()
        targets = {"QLD": Decimal("0.43"), "SCHD": Decimal("0.32"), "SGOV": Decimal("0.25")}
        actual = {"QLD": Decimal("0.3781"), "SCHD": Decimal("0.3320"), "SGOV": Decimal("0.2890")}

        sells, buys = allocation._rebalance_moves(
            card, targets, actual, Decimal("86548"), Decimal("100000")
        )

        assert len(buys) == 1
        assert sells == [], "the buy is fully covered by cash, so nothing should be sold"

    def test_the_same_underweight_is_fundable_when_the_offset_sits_on_one_sleeve(self) -> None:
        """The control that makes the mechanism unambiguous: identical card, identical underweight,
        only the *distribution* of the offsetting overweight changed."""
        card = self._card()
        targets = {"QLD": Decimal("0.43"), "SCHD": Decimal("0.32"), "SGOV": Decimal("0.25")}
        actual = {"QLD": Decimal("0.3781"), "SCHD": Decimal("0.3719"), "SGOV": Decimal("0.2500")}

        sells, buys = allocation._rebalance_moves(card, targets, actual, Decimal("86548"))

        assert len(buys) == 1
        assert len(sells) == 1, "the whole offset now sits on SCHD, which does cross the band"

    def test_a_breaching_buy_is_always_funded_by_some_sell(self) -> None:
        """The intended behaviour. Carried an `xfail(strict=True)` from the D8 write-up until the fix
        landed, which is what made the fix's arrival unambiguous rather than a matter of reading a
        diff.

        Whether a rebalance can happen must not depend on how the offsetting overweight happens to be
        distributed across sleeves -- that is invisible to any individual sleeve's band, and it decides
        whether the book rebalances at all.
        """
        card = self._card()
        targets = {"QLD": Decimal("0.43"), "SCHD": Decimal("0.32"), "SGOV": Decimal("0.25")}
        actual = {"QLD": Decimal("0.3781"), "SCHD": Decimal("0.3320"), "SGOV": Decimal("0.2890")}

        sells, buys = allocation._rebalance_moves(card, targets, actual, Decimal("86548"))

        assert buys, "QLD breaches and must be bought back toward target"
        assert sells, "and something must be sold to pay for it"


class TestContinuousShiftSizing:
    """`TiltRule.shift_expr` -- the change that makes a *continuously sized* tilt expressible.

    Until 2026-08-30 a rule could only say "move eight points when this is true"; the size of the
    move could not depend on how true it was. `ALLOCATION-FAMILY.md` measured the two strategies that
    need that -- continuous vol-targeting and inverse-vol risk parity -- in a bespoke harness and
    recorded that neither is expressible as an `AllocationCard`, with inverse-vol posting the
    family's shallowest drawdown anywhere (-17.6% against a static blend's -33.7%).
    `00-EVERYTHING-TESTED.md` ranks it the programme's #2 outstanding change.
    """

    @staticmethod
    def _expr_card(expr: str) -> AllocationCard:
        return _card(
            sleeves=(
                Sleeve(symbol="A", target_weight=Decimal("0.4")),
                Sleeve(symbol="B", target_weight=Decimal("0.6")),
            ),
            rules=(
                TiltRule(
                    condition="close > 0",
                    on_symbol="A",
                    from_symbol="B",
                    to_symbol="A",
                    shift_expr=expr,
                ),
            ),
        )

    @staticmethod
    def _tables(value: float | None) -> tuple[list[object], list[object]]:
        on = dt.date(2026, 1, 10)
        signal = allocation._SignalTable({"A": pd.Series([True], index=[on])})
        mag = allocation._RankTable({"A": pd.Series([value], index=[on], dtype="float64")})
        return [signal], [mag]

    def test_the_shift_size_comes_from_the_expression(self) -> None:
        """The whole point: two different magnitudes, same rule, different weights."""
        card = self._expr_card("close / 100")
        on = dt.date(2026, 1, 10)

        sig, mag = self._tables(0.05)
        small = allocation._target_weights(card, sig, mag, on)
        sig, mag = self._tables(0.25)
        large = allocation._target_weights(card, sig, mag, on)

        assert small == {"A": Decimal("0.45"), "B": Decimal("0.55")}
        assert large == {"A": Decimal("0.65"), "B": Decimal("0.35")}
        assert sum(small.values()) == sum(large.values()) == Decimal("1")

    def test_an_undefined_magnitude_does_not_fire(self) -> None:
        """Warmup, a missing bar, or a `NaN` -- the rule sits out rather than shifting zero or
        raising. Distinct from `shift=0` only in intent; asserted so the two paths stay one
        behaviour."""
        card = self._expr_card("close / 100")
        sig, mag = self._tables(None)
        assert allocation._target_weights(card, sig, mag, dt.date(2026, 1, 10)) == {
            "A": Decimal("0.4"), "B": Decimal("0.6")
        }

    def test_a_negative_magnitude_does_not_reverse_the_rule(self) -> None:
        """`from_symbol` and `to_symbol` are fixed by the rule, so honouring a negative shift would
        silently invert a card's stated direction. Moving weight the other way is a *second* rule
        with the symbols swapped, which a reader can see."""
        card = self._expr_card("0 - close")
        sig, mag = self._tables(-0.30)
        assert allocation._target_weights(card, sig, mag, dt.date(2026, 1, 10)) == {
            "A": Decimal("0.4"), "B": Decimal("0.6")
        }

    def test_a_magnitude_above_one_is_clamped_and_the_sum_still_holds(self) -> None:
        card = self._expr_card("close")
        sig, mag = self._tables(7.5)
        weights = allocation._target_weights(card, sig, mag, dt.date(2026, 1, 10))
        # Clamped to 1, then to B's available 0.6 by the same `min()` a constant shift passes.
        assert weights == {"A": Decimal("1.0"), "B": Decimal("0.0")}
        assert sum(weights.values()) == Decimal("1")

    def test_the_float_to_decimal_conversion_does_not_leak_binary_error(self) -> None:
        """`Decimal(0.1)` is 0.1000000000000000055511151231257827. Every weight here is an exact
        `Decimal` whose sum must equal `Decimal(1)` on the nose, so the conversion goes through
        `str()` -- otherwise the partition invariant depends on how an indicator happened to round."""
        card = self._expr_card("close / 10")
        sig, mag = self._tables(0.1)
        weights = allocation._target_weights(card, sig, mag, dt.date(2026, 1, 10))
        assert weights == {"A": Decimal("0.5"), "B": Decimal("0.5")}
        assert sum(weights.values()) == Decimal("1")


class TestShiftValidation:
    @staticmethod
    def _rule(**over: object) -> dict[str, object]:
        base = {"condition": "close > 0", "on_symbol": "A", "from_symbol": "B", "to_symbol": "A"}
        return {**base, **over}

    def test_neither_shift_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="exactly one of shift_pct or shift_expr"):
            TiltRule(**self._rule())

    def test_both_shifts_are_refused(self) -> None:
        """Both would need a precedence rule, and any precedence rule makes one of the two a value
        the card states and the engine ignores -- present, plausible and unread."""
        with pytest.raises(ValidationError, match="exactly one of shift_pct or shift_expr"):
            TiltRule(**self._rule(shift_pct=Decimal("0.08"), shift_expr="close / 100"))

    def test_a_blank_expression_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="shift_expr is blank"):
            TiltRule(**self._rule(shift_expr="   "))

    def test_a_constant_shift_still_validates_exactly_as_before(self) -> None:
        rule = TiltRule(**self._rule(shift_pct=Decimal("0.08")))
        assert rule.shift_pct == Decimal("0.08")
        assert rule.shift_expr is None


class TestShiftExprIsGuarded:
    """The safety argument for `shift_expr` existing at all.

    A non-causal *magnitude* sizes today's position from tomorrow's data. That is lookahead in the
    sizing step rather than the entry step, and it is harder to notice precisely because the
    condition beside it stays clean -- a reader auditing the rule sees a perfectly ordinary
    `close < sma(5)` and no reason to look further. A guard that only ever passed here would be
    indistinguishable from no guard.
    """

    @staticmethod
    def _register_peeking(monkeypatch: pytest.MonkeyPatch) -> None:
        """A deliberately non-causal indicator, patched onto both registry bindings.

        Two patches, not one: `app.rules.grammar` holds its own module-scope reference to
        `registry.get`, so patching only the registry leaves the parser rejecting the name before the
        guard ever sees the tree -- which makes the guard look like it caught something it never saw.
        `tests/test_guards.py` learned this the hard way and says so.
        """

        def peeking(bars: pd.DataFrame, /, **params: object) -> pd.DataFrame:
            period = int(params["period"])  # type: ignore[call-overload]
            return pd.DataFrame({f"peek_{period}": bars["close"].shift(-3)}, index=bars.index)

        spec = IndicatorSpec(
            name="peek",
            title="peek",
            fn=peeking,
            params=(ParamSpec(name="period", kind=ParamKind.INT, default=10, minimum=1),),
            pane=Pane.OSCILLATOR,
            warmup=lambda p: int(p["period"]),
        )
        real_get = indicator_registry.get

        def patched(n: str) -> IndicatorSpec | None:
            return spec if n == "peek" else real_get(n)

        monkeypatch.setattr(indicator_registry, "get", patched)
        monkeypatch.setattr(rule_grammar, "_get_indicator_spec", patched)

    def test_a_non_causal_shift_expr_is_refused(
        self, settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._register_peeking(monkeypatch)
        dates = _weekdays(dt.date(2025, 1, 6), 300)
        _write_bars(settings, "A", _flat(dates, 100.0))
        card = _card(
            sleeves=(
                Sleeve(symbol="A", target_weight=Decimal("0.5")),
                Sleeve(symbol="B", target_weight=Decimal("0.5")),
            ),
            rules=(
                TiltRule(
                    condition="close > 0",          # impeccably causal
                    on_symbol="A",
                    from_symbol="B",
                    to_symbol="A",
                    shift_expr="peek(10) / 1000",   # reads three bars into the future
                ),
            ),
        )

        with pytest.raises(allocation.GuardFailed) as excinfo:
            allocation._guard_allocation_card(
                card, settings=settings, first_decided_on=dates[-1]
            )

        # The finding must name the *magnitude*, not the condition -- a reader told only that "the
        # card failed the guard" would go looking at a rule that is fine.
        assert "shift_expr" in str(excinfo.value)

    def test_a_causal_shift_expr_passes_and_is_parsed(self, settings) -> None:
        """The other direction, so the test above is known to be catching something rather than
        rejecting everything."""
        dates = _weekdays(dt.date(2025, 1, 6), 300)
        _write_bars(settings, "A", _flat(dates, 100.0))
        card = _card(
            sleeves=(
                Sleeve(symbol="A", target_weight=Decimal("0.5")),
                Sleeve(symbol="B", target_weight=Decimal("0.5")),
            ),
            rules=(
                TiltRule(
                    condition="close > 0",
                    on_symbol="A",
                    from_symbol="B",
                    to_symbol="A",
                    shift_expr="close / 10000",
                ),
            ),
        )

        trees = allocation._guard_allocation_card(
            card, settings=settings, first_decided_on=dates[-1]
        )

        assert len(trees) == 1
        condition_tree, magnitude_tree = trees[0]
        assert condition_tree is not None
        assert magnitude_tree is not None, "a shift_expr rule must come back with a parsed magnitude"

    def test_a_constant_shift_rule_gets_no_magnitude_tree(self, settings) -> None:
        dates = _weekdays(dt.date(2025, 1, 6), 300)
        _write_bars(settings, "A", _flat(dates, 100.0))
        card = _card(
            sleeves=(
                Sleeve(symbol="A", target_weight=Decimal("0.5")),
                Sleeve(symbol="B", target_weight=Decimal("0.5")),
            ),
            rules=(
                TiltRule(
                    condition="close > 0",
                    on_symbol="A",
                    from_symbol="B",
                    to_symbol="A",
                    shift_pct=Decimal("0.1"),
                ),
            ),
        )

        _condition, magnitude = allocation._guard_allocation_card(
            card, settings=settings, first_decided_on=dates[-1]
        )[0]

        assert magnitude is None, "a constant-shift card must not pay for a magnitude table"

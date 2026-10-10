"""Tests for `app.tournament.ladder`: the drawdown-ladder card shape.

Follows `tests/test_allocation_card.py`'s own convention -- synthetic bars written into the temp
store via the `settings` fixture, every price engineered so a specific event (the initial
allocation, a confirmed rung fire, a gap-through, a new-high haircut, a full recovery exit) happens
on a known session with hand-checked arithmetic. `confirm_ma` and `recovery_sessions` are shrunk to
3 in every test card (the real library card uses 50/60) purely so a whole scenario fits in a dozen
synthetic trading days instead of needing months of bars -- the state machine's logic does not care
about the magnitude of either constant, only that history is long enough to fill the window, which
`_confirmed`'s own docstring already establishes for any bounded `confirm_ma`.

**How a scenario's price list maps onto sessions -- read this before touching any of the numbers
below.** Every scenario states SPY's *decided_on* close for a run of consecutive sessions as a plain
list `[p0, p1, ..., pK]`. Session `i` (1-indexed) is decided on `p(i-1)` and dated `p(i)` -- the
one-session lag every decision path in this repository observes (`_require_decision_market`) -- so a
list of `K + 1` prices produces exactly `K` tradeable sessions, whose *decided_on* values are
`p0 .. p(K-1)` in order (the very last list entry, `pK`, is never read as a decision input at all; it
exists only because the last session's own trading *date* needs a stored SPY bar to exist). See
`_spy_path` below, which is the one place this mapping is implemented and the one place a future
scenario should get the arithmetic from rather than re-deriving it.

Every synthetic scenario also holds SCHD/IEF/QLD perfectly flat throughout (see `_write_sleeve_bars`)
specifically so the dollar amount of every rebalance is exactly the state machine's own weight change
times a constant $10,000 equity, with no compounding or rounding noise to obscure the arithmetic.

Each test class pins one rule from the card's own specification (see `ladder.py`'s module docstring
for the full list):

* `TestCardValidation` -- the model's own guardrails: base weights must sum to one, rungs must be
  declared shallowest-first with strictly deepening drawdown and strictly increasing leveraged
  weight, and the three sleeve symbols must be pairwise distinct.
* `TestWeightFor` / `TestSleeveTargets` / `TestConfirmed` -- direct, session-loop-free tests of the
  three pure functions the state machine is built from.
* `TestInitialAllocation` -- the first session establishes the base 60/40 state from an empty book,
  even though the leveraged weight itself has not changed (there is nothing to compare it against).
* `TestConfirmationGatesTheFire` -- pins the single most important rule: a breach with no confirmed
  bounce produces no trade at all, and the identical price path with one more confirmed session does.
* `TestNeverConfirmedNeverFires` -- a monotonic decline that never closes above its own short average
  never opens a leveraged position, however deep the drawdown gets.
* `TestGapThrough` -- a drawdown that reaches the second rung's depth before it is ever confirmed
  fires straight to the second rung's weight, never having armed the first.
* `TestOncePerCycleArming` -- once a rung has fired, revisiting the identical drawdown band produces
  no second trade.
* `TestNewHighHalvesThenFullyExits` -- the full recovery lifecycle: a new all-time high halves the
  leveraged sleeve immediately, a second new high with no further transition does nothing, and a
  third session's close 10% above the cycle's own starting high fully exits and re-arms.
* `TestRecoveryTimeoutAlsoExits` -- the other half of the same rule: if the gain target is never
  reached, `recovery_sessions` after the halving session exits anyway.
* `TestNoLookahead` -- `_require_decision_market` is reused from `runner.py`, not reimplemented.
* `TestLadderResultShape` -- `LadderResult` is not `AllocationResult` or `AgentResult` (see
  `ladder.py`'s own module docstring), but still carries every field a caller of a "second card
  shape" result already knows how to read.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pandas as pd
import pytest

from app.db import duck
from app.market.models import BAR_COLUMNS, Interval
from app.paper.marketdata import AsOfMarket, Session
from app.paper.paperbroker import Mandate
from app.tournament import ladder
from app.tournament.ladder import LadderCard, LadderResult, Rung
from app.tournament.models import DESIGN_THROUGH

# ---------------------------------------------------------------------------
# Fixtures -- duplicated small helpers, per this suite's own established convention (see
# `tests/test_allocation_card.py`'s own module docstring on why every file keeps its own copy).
# ---------------------------------------------------------------------------


def _weekdays(anchor: dt.date, count: int) -> list[dt.date]:
    dates: list[dt.date] = []
    day = anchor
    while len(dates) < count:
        if day.weekday() < 5:
            dates.append(day)
        day += dt.timedelta(days=1)
    return dates


def _write_bars(settings, symbol: str, prices: dict[dt.date, tuple[float, float]]) -> None:
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
    """Every friction zeroed out, matching `test_allocation_card.py::_mandate`'s own convention.
    `settlement_days` defaults to instant (0) here rather than that file's default of 1, because every
    end-to-end scenario below relies on a same-session sell (e.g. trimming IEF) funding a same-session
    buy (e.g. topping up QLD) -- see `test_allocation_card.py::TestBandBreachTradesBackTowardTarget`
    for the identical reasoning."""
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
        "settlement_days": 0,
        "slippage_bps": Decimal("0"),
        "commission_per_trade": Decimal("0"),
        "sec_fee_rate": Decimal("0"),
        "taf_per_share": Decimal("0"),
        "taf_cap": Decimal("0"),
    }
    fields.update(overrides)
    return Mandate(**fields)  # type: ignore[arg-type]


def _card(**overrides: object) -> LadderCard:
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


def _write_sleeve_bars(settings, dates: list[dt.date]) -> None:
    """SCHD/IEF/QLD held perfectly flat across every scenario -- round numbers chosen so every
    rebalance below divides out to a whole share count with nothing left to hand-wave."""
    _write_bars(settings, "SCHD", _flat(dates, 50.0))
    _write_bars(settings, "IEF", _flat(dates, 100.0))
    _write_bars(settings, "QLD", _flat(dates, 40.0))


def _spy_path(settings, prices: list[float]) -> list[dt.date]:
    """Write `prices` (`p0..pK`) as SPY's own *decided_on* sequence and return the resulting *session*
    dates -- see this module's own docstring for exactly how a `K + 1`-length price list maps onto
    `K` sessions. Five extra flat lead-in days precede `p0` so `_confirmed`'s own history requirement
    (at least `confirm_ma` prior bars) is satisfied from the very first session onward."""
    dates = _weekdays(dt.date(2026, 1, 5), 5 + len(prices))
    lead_in, price_dates = dates[:5], dates[5:]
    assert len(price_dates) == len(prices)
    _write_bars(
        settings,
        "SPY",
        {**_flat(lead_in, 100.0), **{d: (p, p) for d, p in zip(price_dates, prices, strict=True)}},
    )
    _write_sleeve_bars(settings, dates)
    return price_dates[1:]  # p0 is only ever a decided_on, never a session's own date


# ---------------------------------------------------------------------------
# Card validation
# ---------------------------------------------------------------------------


class TestCardValidation:
    def test_base_weights_must_sum_to_one(self) -> None:
        with pytest.raises(ValueError, match="not 1"):
            _card(base_defensive_weight=Decimal("0.55"), base_bond_weight=Decimal("0.40"))

    def test_rungs_must_be_declared_shallowest_first(self) -> None:
        with pytest.raises(ValueError, match="not deeper than"):
            _card(
                rungs=(
                    Rung(drawdown=Decimal("-0.20"), leveraged_weight=Decimal("0.60")),
                    Rung(drawdown=Decimal("-0.10"), leveraged_weight=Decimal("0.20")),
                )
            )

    def test_rungs_must_strictly_increase_leveraged_weight_with_depth(self) -> None:
        with pytest.raises(ValueError, match="does not exceed"):
            _card(
                rungs=(
                    Rung(drawdown=Decimal("-0.10"), leveraged_weight=Decimal("0.60")),
                    Rung(drawdown=Decimal("-0.20"), leveraged_weight=Decimal("0.20")),
                )
            )

    def test_symbols_must_be_pairwise_distinct(self) -> None:
        with pytest.raises(ValueError, match="distinct"):
            _card(defensive_symbol="QLD")

    def test_rung_drawdown_must_be_negative(self) -> None:
        with pytest.raises(ValueError, match="negative fraction"):
            Rung(drawdown=Decimal("0.10"), leveraged_weight=Decimal("0.20"))

    def test_designed_through_cannot_see_the_trading_window(self) -> None:
        with pytest.raises(ValueError, match="design cutoff"):
            _card(designed_through=DESIGN_THROUGH + dt.timedelta(days=1))


# ---------------------------------------------------------------------------
# _weight_for -- the deepest breached rung, gap-through included
# ---------------------------------------------------------------------------


class TestWeightFor:
    def test_no_breach_is_zero(self) -> None:
        card = _card()
        assert ladder._weight_for(card.rungs, Decimal("-0.05")) == Decimal(0)

    def test_shallow_breach_picks_the_first_rung(self) -> None:
        card = _card()
        assert ladder._weight_for(card.rungs, Decimal("-0.12")) == Decimal("0.20")

    def test_a_deep_breach_picks_the_deepest_rung_reached_not_the_first(self) -> None:
        """The gap-through case in isolation: a drawdown that reaches the second rung's depth in one
        step returns that rung's weight directly, never the first rung's."""
        card = _card()
        assert ladder._weight_for(card.rungs, Decimal("-0.25")) == Decimal("0.60")

    def test_exactly_at_a_threshold_breaches_it(self) -> None:
        card = _card()
        assert ladder._weight_for(card.rungs, Decimal("-0.10")) == Decimal("0.20")


# ---------------------------------------------------------------------------
# _sleeve_targets -- QLD funded from IEF first, then SCHD
# ---------------------------------------------------------------------------


class TestSleeveTargets:
    def test_zero_leveraged_weight_is_the_base_state(self) -> None:
        card = _card()
        targets = ladder._sleeve_targets(card, Decimal(0))
        assert targets == {"QLD": Decimal(0), "IEF": Decimal("0.40"), "SCHD": Decimal("0.60")}

    def test_leveraged_weight_within_the_bond_sleeves_capacity_draws_only_from_ief(self) -> None:
        card = _card()
        targets = ladder._sleeve_targets(card, Decimal("0.20"))
        assert targets == {"QLD": Decimal("0.20"), "IEF": Decimal("0.20"), "SCHD": Decimal("0.60")}
        assert sum(targets.values()) == Decimal("1")

    def test_leveraged_weight_beyond_the_bond_sleeve_drains_it_then_draws_from_defensive(
        self,
    ) -> None:
        card = _card()
        targets = ladder._sleeve_targets(card, Decimal("0.60"))
        assert targets == {"QLD": Decimal("0.60"), "IEF": Decimal(0), "SCHD": Decimal("0.40")}
        assert sum(targets.values()) == Decimal("1")

    def test_the_deepest_rung_still_sums_to_one(self) -> None:
        card = _card()
        targets = ladder._sleeve_targets(card, Decimal("0.80"))
        assert targets == {"QLD": Decimal("0.80"), "IEF": Decimal(0), "SCHD": Decimal("0.20")}
        assert sum(targets.values()) == Decimal("1")


# ---------------------------------------------------------------------------
# _confirmed -- the bounce gate
# ---------------------------------------------------------------------------


class TestConfirmed:
    def test_not_enough_history_is_unconfirmed(self, settings) -> None:
        card = _card(confirm_ma=3)
        dates = _weekdays(dt.date(2026, 1, 5), 2)  # fewer than confirm_ma bars exist at all
        _write_bars(settings, "SPY", _flat(dates, 100.0))
        market = AsOfMarket(as_of=dates[-1], settings=settings)
        assert ladder._confirmed(card, market) is False

    def test_a_close_above_its_own_short_average_is_confirmed(self, settings) -> None:
        card = _card(confirm_ma=3)
        dates = _weekdays(dt.date(2026, 1, 5), 3)
        _write_bars(
            settings, "SPY", {dates[0]: (86, 86), dates[1]: (88, 88), dates[2]: (90, 90)}
        )
        market = AsOfMarket(as_of=dates[-1], settings=settings)
        # avg(86, 88, 90) = 88; 90 > 88.
        assert ladder._confirmed(card, market) is True

    def test_a_still_falling_close_is_not_confirmed(self, settings) -> None:
        card = _card(confirm_ma=3)
        dates = _weekdays(dt.date(2026, 1, 5), 3)
        _write_bars(
            settings, "SPY", {dates[0]: (100, 100), dates[1]: (100, 100), dates[2]: (86, 86)}
        )
        market = AsOfMarket(as_of=dates[-1], settings=settings)
        # avg(100, 100, 86) = 95.33; 86 < 95.33.
        assert ladder._confirmed(card, market) is False


# ---------------------------------------------------------------------------
# End to end: the very first session establishes the base state from an empty book
# ---------------------------------------------------------------------------


class TestInitialAllocation:
    def test_first_session_buys_the_base_sixty_forty_split_with_no_leverage(self, settings) -> None:
        trade_dates = _spy_path(settings, [100.0, 100.0, 100.0, 100.0])

        mandate = _mandate()
        card = _card()

        result = ladder.run_ladder_card(
            card, settings=settings, mandate=mandate, start=trade_dates[0], end=trade_dates[-1]
        )

        assert result.rejections == ()
        by_symbol = {t.symbol: t for t in result.trades}
        # $10,000 * 0.60 / $50 = 120 SCHD shares; $10,000 * 0.40 / $100 = 40 IEF shares; no QLD at all.
        assert by_symbol["SCHD"].quantity == Decimal("120")
        assert by_symbol["IEF"].quantity == Decimal("40")
        assert "QLD" not in by_symbol
        assert {t.exit_reason for t in result.trades} == {"open_at_end"}
        assert result.ending_equity == Decimal("10000.00")  # flat prices, no leverage ever taken


# ---------------------------------------------------------------------------
# End to end: confirmation gates the fire -- the single most important rule
# ---------------------------------------------------------------------------


class TestConfirmationGatesTheFire:
    def test_a_breach_with_no_confirmed_bounce_yet_produces_no_leveraged_trade(
        self, settings
    ) -> None:
        """decided_on values seen: 100, 100, 86, 88 -- drawdown has already reached -12% (past the
        -10% rung) but the close has never yet exceeded its own trailing 3-average, so no QLD trade
        has happened at all."""
        trade_dates = _spy_path(settings, [100.0, 100.0, 86.0, 88.0, 90.0])
        mandate = _mandate()
        card = _card()

        result = ladder.run_ladder_card(
            card, settings=settings, mandate=mandate, start=trade_dates[0], end=trade_dates[-1]
        )

        by_symbol = {t.symbol: t for t in result.trades}
        assert "QLD" not in by_symbol
        assert by_symbol["IEF"].quantity == Decimal("40")  # never drawn down

    def test_the_next_session_confirmed_bounce_fires_the_rung(self, settings) -> None:
        """One more session: the same -10% breach (avg(86, 88, 90) = 88; 90 > 88) is now confirmed,
        and the rung fires -- 20% QLD, funded entirely from IEF (IEF has 0.40 of capacity, the rung
        only needs 0.20)."""
        trade_dates = _spy_path(settings, [100.0, 100.0, 86.0, 88.0, 90.0, 90.0])
        mandate = _mandate()
        card = _card()

        result = ladder.run_ladder_card(
            card, settings=settings, mandate=mandate, start=trade_dates[0], end=trade_dates[-1]
        )

        rebalance_trims = [t for t in result.trades if t.exit_reason == "rebalance_trim"]
        assert {t.symbol for t in rebalance_trims} == {"IEF"}
        assert rebalance_trims[0].quantity == Decimal("20")  # 40 - 20 remaining = 0.20 * 10000 / 100

        opens = {t.symbol: t for t in result.trades if t.exit_reason == "open_at_end"}
        assert opens["QLD"].quantity == Decimal("50")  # 0.20 * 10000 / 40
        assert opens["IEF"].quantity == Decimal("20")  # 40 - 20
        assert opens["SCHD"].quantity == Decimal("120")  # untouched throughout


# ---------------------------------------------------------------------------
# End to end: never confirmed, never fires -- however deep the drawdown gets
# ---------------------------------------------------------------------------


class TestNeverConfirmedNeverFires:
    def test_a_monotonic_decline_past_every_rung_opens_no_leveraged_position(self, settings) -> None:
        """Strictly falling every session: each close is below its own trailing average by
        construction, so `_confirmed` is false at every step even once the drawdown has passed all
        three rungs' depths. This is the rule the task brief names as the single most important one:
        without it, the reference backtest reaches 80% leverage at the very bottom of a crash."""
        trade_dates = _spy_path(settings, [100.0, 100.0, 94.0, 88.0, 82.0, 75.0])
        mandate = _mandate()
        card = _card()

        result = ladder.run_ladder_card(
            card, settings=settings, mandate=mandate, start=trade_dates[0], end=trade_dates[-1]
        )

        by_symbol = {t.symbol: t for t in result.trades}
        assert "QLD" not in by_symbol
        assert by_symbol["IEF"].quantity == Decimal("40")
        assert by_symbol["SCHD"].quantity == Decimal("120")


# ---------------------------------------------------------------------------
# End to end: gap-through -- a deep, confirmed breach with no shallower rung ever having fired
# ---------------------------------------------------------------------------


class TestGapThrough:
    def test_a_confirmed_breach_past_the_second_rungs_depth_fires_straight_to_it(
        self, settings
    ) -> None:
        """Drawdown passes through the first rung's own -10% band while still falling (never
        confirmed there), bottoms out past the second rung's -20% depth, and is only confirmed once
        it has ticked back up to exactly -20% (avg(76, 78, 80) = 78; 80 > 78) -- so the ladder jumps
        directly from 0% to 60% leveraged, the first rung's 20% never having been the armed depth at
        any point."""
        trade_dates = _spy_path(settings, [100.0, 100.0, 90.0, 76.0, 78.0, 80.0, 80.0])
        mandate = _mandate()
        card = _card()

        result = ladder.run_ladder_card(
            card, settings=settings, mandate=mandate, start=trade_dates[0], end=trade_dates[-1]
        )

        trims = {t.symbol: t for t in result.trades if t.exit_reason == "rebalance_trim"}
        opens = {t.symbol: t for t in result.trades if t.exit_reason == "open_at_end"}
        # Funding the 60% rung: IEF's whole 0.40 capacity is drained first, and SCHD gives up the
        # remaining 0.20 the second rung needs beyond what IEF alone can fund.
        assert set(trims) == {"IEF", "SCHD"}
        assert trims["IEF"].quantity == Decimal("40")  # fully drained
        assert trims["SCHD"].quantity == Decimal("40")  # 120 -> 80, i.e. 0.60 -> 0.40 of the book

        assert opens["QLD"].quantity == Decimal("150")  # 0.60 * 10000 / 40
        assert opens["SCHD"].quantity == Decimal("80")
        assert "IEF" not in opens  # fully closed, not carried open at the window's end


# ---------------------------------------------------------------------------
# End to end: once armed, a rung does not refire on the same or a shallower re-breach
# ---------------------------------------------------------------------------


class TestOncePerCycleArming:
    def test_revisiting_the_same_drawdown_band_after_firing_produces_no_second_trade(
        self, settings
    ) -> None:
        """Fires the first rung exactly as in `TestConfirmationGatesTheFire`, then chops back into
        (-6%) and out to (-12%) of the same band with no new high in between -- `armed_depth` (0.20)
        is never exceeded by either re-visit, so neither produces a trade."""
        trade_dates = _spy_path(
            settings, [100.0, 100.0, 86.0, 88.0, 90.0, 94.0, 88.0, 88.0]
        )
        mandate = _mandate()
        card = _card()

        result = ladder.run_ladder_card(
            card, settings=settings, mandate=mandate, start=trade_dates[0], end=trade_dates[-1]
        )

        rebalance_trims = [t for t in result.trades if t.exit_reason == "rebalance_trim"]
        # Exactly one rebalancing event (the original fire's IEF trim) across the whole window -- the
        # chop back into and out of the same band produced nothing further.
        assert len(rebalance_trims) == 1
        assert rebalance_trims[0].symbol == "IEF"
        opens = {t.symbol: t for t in result.trades if t.exit_reason == "open_at_end"}
        assert opens["QLD"].quantity == Decimal("50")  # unchanged since the original fire


# ---------------------------------------------------------------------------
# End to end: the full recovery lifecycle -- halve on a new high, exit at +10% above the cycle high
# ---------------------------------------------------------------------------


class TestNewHighHalvesThenFullyExits:
    def test_a_new_high_halves_and_a_further_ten_percent_gain_fully_exits_and_rearms(
        self, settings
    ) -> None:
        """Fires the first rung as before (`cycle_peak` becomes 100). Drifts without a new high
        (no trade), then a new all-time high (101) halves QLD (0.20 -> 0.10) the same session. A
        further new high (108) is not yet 10% above the cycle's own starting high (110) and not yet
        `recovery_sessions` (3) after the halving session -- no trade. The next new high (111) clears
        110 -- full exit, re-arm."""
        trade_dates = _spy_path(
            settings,
            [100.0, 100.0, 86.0, 88.0, 90.0, 92.0, 101.0, 108.0, 111.0, 111.0],
        )
        mandate = _mandate()
        card = _card()

        result = ladder.run_ladder_card(
            card, settings=settings, mandate=mandate, start=trade_dates[0], end=trade_dates[-1]
        )

        rebalance_trims = [t for t in result.trades if t.exit_reason == "rebalance_trim"]
        trimmed_symbols = [t.symbol for t in rebalance_trims]
        # Four rebalancing legs across the whole lifecycle: IEF trimmed to fund the fire, QLD trimmed
        # to fund the halving, then QLD trimmed again (fully) on the exit, with IEF topped back up.
        assert trimmed_symbols.count("QLD") == 2  # halved once, then closed out entirely
        assert trimmed_symbols.count("IEF") == 1  # only ever trimmed once, to fund the original fire

        # Back to the exact base state at the end: no QLD held, IEF and SCHD restored to their
        # original share counts (flat prices throughout, so nothing has compounded away).
        opens = {t.symbol: t for t in result.trades if t.exit_reason == "open_at_end"}
        assert opens["IEF"].quantity == Decimal("40")
        assert opens["SCHD"].quantity == Decimal("120")
        assert "QLD" not in opens  # fully closed, not carried open at the window's end


# ---------------------------------------------------------------------------
# End to end: recovery via the session timeout, when the gain target is never reached
# ---------------------------------------------------------------------------


class TestRecoveryTimeoutAlsoExits:
    def test_no_new_gain_but_recovery_sessions_elapsed_exits_anyway(self, settings) -> None:
        """Fires as before, then a new high (101) halves QLD. The next three sessions sit flat at
        101 (never a new high again, never reaching 110) -- `recovery_sessions=3` after the halving
        session exits anyway, exactly the rule this card's `recovery_sessions` field exists to
        express."""
        trade_dates = _spy_path(
            settings,
            [100.0, 100.0, 86.0, 88.0, 90.0, 92.0, 101.0, 101.0, 101.0, 101.0, 101.0],
        )
        mandate = _mandate()
        card = _card(recovery_sessions=3)

        result = ladder.run_ladder_card(
            card, settings=settings, mandate=mandate, start=trade_dates[0], end=trade_dates[-1]
        )

        opens = {t.symbol: t for t in result.trades if t.exit_reason == "open_at_end"}
        assert "QLD" not in opens  # closed out by the timeout, not left open
        assert opens["IEF"].quantity == Decimal("40")
        assert opens["SCHD"].quantity == Decimal("120")


# ---------------------------------------------------------------------------
# The lookahead guard is wired into this module's decision path too
# ---------------------------------------------------------------------------


class TestNoLookahead:
    def test_require_decision_market_is_reused_from_runner(self, settings) -> None:
        session = Session(index=5, date=dt.date(2026, 3, 10), decided_on=dt.date(2026, 3, 9))
        same_day = AsOfMarket(as_of=session.date, settings=settings)

        with pytest.raises(ladder.LookaheadError):
            ladder._require_decision_market(same_day, session)


# ---------------------------------------------------------------------------
# LadderResult carries every field a "second card shape" result's callers already read
# ---------------------------------------------------------------------------


class TestLadderResultShape:
    def test_result_has_every_field_the_desk_reads(self, settings) -> None:
        trade_dates = _spy_path(settings, [100.0, 100.0, 100.0, 100.0])
        mandate = _mandate()
        card = _card()

        result = ladder.run_ladder_card(
            card, settings=settings, mandate=mandate, start=trade_dates[0], end=trade_dates[-1]
        )

        assert isinstance(result, LadderResult)
        assert result.card is card
        assert result.card.agent_id == "ladder-test"
        assert result.sessions == 3
        assert result.starting_equity == Decimal("10000.00")
        assert result.ending_equity == Decimal("10000.00")
        assert result.max_drawdown is not None
        assert result.capital_exposure is not None
        assert result.capital_exposure == pytest.approx(1.0, abs=0.01)
        assert isinstance(result.trades, tuple)
        assert result.rejections == ()

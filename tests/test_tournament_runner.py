"""`app.tournament.runner.run_card` against synthetic bars written into the temp store.

No network, no real ledger, no real bar store -- every symbol used below (including ``SPY``, the
tournament's benchmark) is written by `_write_bars` into the `settings` fixture's temporary
`bars_dir`. Prices are engineered per test so a specific event (an entry, a stop, a target, a time
stop, a rejection) happens on a specific, known session, which is what makes assertions like "the
fill used the next session's open, not the decision close" checkable at all.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pandas as pd
import pytest

from app.db import duck
from app.market.models import BAR_COLUMNS, Interval
from app.rules import grammar as rule_grammar
from app.tournament import runner
from app.tournament.models import DESIGN_THROUGH, Discipline, StrategyCard
from uat.harness.marketdata import AsOfMarket, Session
from uat.harness.paperbroker import Mandate

# ---------------------------------------------------------------------------
# Fixtures shared by every test in this file
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
    every bracket decision this runner makes is deliberately based on the close, never the
    high/low (see `runner`'s module docstring), so their exact values are inert here."""
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


def _card(**overrides: object) -> StrategyCard:
    fields: dict[str, object] = {
        "agent_id": "agent-1",
        "display_name": "Agent One",
        "discipline": Discipline.TREND,
        "thesis": "a test thesis, written before the trading window ran",
        "universe": ("TEST",),
        "entry": "close > 0",
        "exit": "",
        "max_hold_days": 50,
        "max_positions": 1,
        "position_pct": Decimal("1.0"),
        "designed_through": DESIGN_THROUGH,
    }
    fields.update(overrides)
    return StrategyCard(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# A card that never triggers
# ---------------------------------------------------------------------------


class TestNeverTriggers:
    def test_zero_trades_and_a_flat_equity_curve(self, settings) -> None:
        dates = _weekdays(dt.date(2026, 1, 5), 15)
        trade_dates = dates[5:]
        _write_bars(settings, "SPY", _flat(dates, 100.0))
        _write_bars(settings, "TEST", _flat(dates, 100.0))

        mandate = _mandate()
        card = _card(entry="close > 999999", universe=("TEST",))

        result = runner.run_card(
            card, settings=settings, mandate=mandate, start=trade_dates[0], end=trade_dates[-1]
        )

        assert result.trades == ()
        assert result.rejections == ()
        assert result.sessions == len(trade_dates)
        assert result.starting_equity == mandate.starting_cash
        assert result.ending_equity == mandate.starting_cash
        assert result.total_return == Decimal("0.0")


# ---------------------------------------------------------------------------
# A card that enters and exits: fill boundary
# ---------------------------------------------------------------------------


class TestEntryAndExitFillBoundary:
    def test_entry_and_exit_fill_at_the_next_open_not_the_decision_close(self, settings) -> None:
        dates = _weekdays(dt.date(2026, 1, 5), 8)
        lead_in, trade_dates = dates[:5], dates[5:]
        d1, d2, d3 = trade_dates

        spy_prices = _flat(dates, 100.0)
        test_prices: dict[dt.date, tuple[float, float]] = {
            **_flat(lead_in[:-1], 50.0),
            lead_in[-1]: (50.0, 101.0),  # decided_on for d1: close 101 > 100 -> entry fires
            d1: (105.0, 102.0),  # fill uses this open (105), not the 101 close that triggered it
            d2: (100.0, 80.0),  # decided_on for d3: close 80 < 90 -> exit fires
            d3: (70.0, 70.0),  # fill uses this open (70), not the 80 close that triggered it
        }
        _write_bars(settings, "SPY", spy_prices)
        _write_bars(settings, "TEST2", test_prices)

        mandate = _mandate()
        card = _card(
            universe=("TEST2",),
            entry="close > 100",
            exit="close < 90",
            position_pct=Decimal("0.5"),
            max_positions=1,
        )

        result = runner.run_card(card, settings=settings, mandate=mandate, start=d1, end=d3)

        assert result.rejections == ()
        assert len(result.trades) == 1
        trade = result.trades[0]

        assert trade.entry_date == d1
        assert trade.entry_price == Decimal("105.00")  # d1's open, not lead_in[-1]'s 101 close
        assert trade.entry_price != Decimal("101.00")

        assert trade.exit_reason == "rule"
        assert trade.exit_date == d3
        assert trade.exit_price == Decimal("70.00")  # d3's open, not d2's 80 close
        assert trade.exit_price != Decimal("80.00")

        assert trade.quantity == Decimal("49")  # floor(0.5 * 10000 / 101), sized off the decision
        # close, not the fill price
        assert trade.pnl == Decimal("-1715.00")
        assert trade.return_pct == Decimal("-1715.00") / (Decimal("105.00") * Decimal("49"))


# ---------------------------------------------------------------------------
# Stop, target and time stop each fire and are labelled distinctly
# ---------------------------------------------------------------------------


class TestExitReasonsAreDistinct:
    def test_stop_target_and_time_each_fire_with_their_own_label(self, settings) -> None:
        dates = _weekdays(dt.date(2026, 1, 5), 9)
        lead_in, trade_dates = dates[:5], dates[5:]
        d1, d2, d3, d4 = trade_dates

        spy_prices = _flat(dates, 100.0)
        stop_prices = {
            **_flat(lead_in, 100.0),
            d1: (100.0, 85.0),  # stop level = 100*0.9 = 90; d1 close 85 breaches it
            d2: (84.0, 84.0),
            d3: (84.0, 84.0),
            d4: (84.0, 84.0),
        }
        target_prices = {
            **_flat(lead_in, 100.0),
            d1: (100.0, 115.0),  # target level = 100*1.10 = 110; d1 close 115 clears it
            d2: (116.0, 116.0),
            d3: (116.0, 116.0),
            d4: (116.0, 116.0),
        }
        time_prices = {
            **_flat(lead_in, 100.0),
            d1: (100.0, 100.0),
            d2: (100.0, 100.0),
            d3: (
                100.0,
                100.0,
            ),  # held = index(d4) - index(d1) = 3 == max_hold_days at d4's decision
            d4: (99.0, 99.0),
        }
        _write_bars(settings, "SPY", spy_prices)
        _write_bars(settings, "STOPX", stop_prices)
        _write_bars(settings, "TARGETX", target_prices)
        _write_bars(settings, "TIMEX", time_prices)

        mandate = _mandate()
        card = _card(
            universe=("STOPX", "TARGETX", "TIMEX"),
            entry="close > 0",
            exit="",
            stop_loss_pct=Decimal("0.10"),
            take_profit_pct=Decimal("0.10"),
            max_hold_days=3,
            max_positions=3,
            position_pct=Decimal("0.3"),
        )

        result = runner.run_card(card, settings=settings, mandate=mandate, start=d1, end=d4)

        by_symbol_reason = {(t.symbol, t.exit_reason): t for t in result.trades}

        stop_trade = by_symbol_reason[("STOPX", "stop")]
        assert stop_trade.exit_date == d2
        assert stop_trade.exit_price == Decimal("84.00")

        target_trade = by_symbol_reason[("TARGETX", "target")]
        assert target_trade.exit_date == d2
        assert target_trade.exit_price == Decimal("116.00")

        time_trade = by_symbol_reason[("TIMEX", "time")]
        assert time_trade.exit_date == d4
        assert time_trade.exit_price == Decimal("99.00")


# ---------------------------------------------------------------------------
# max_positions (the card's own cap, distinct from the mandate's)
# ---------------------------------------------------------------------------


class TestMaxPositions:
    def test_the_cards_own_cap_is_respected(self, settings) -> None:
        dates = _weekdays(dt.date(2026, 1, 5), 6)
        d1 = dates[5]

        _write_bars(settings, "SPY", _flat(dates, 100.0))
        for symbol in ("A", "B", "C"):
            _write_bars(settings, symbol, _flat(dates, 100.0))

        mandate = _mandate(max_positions=5)  # generous at the mandate level -- the cap under test
        # is the card's own, evaluated before any order ever reaches the broker.
        card = _card(
            universe=("A", "B", "C"),
            entry="close > 0",
            max_positions=1,
            position_pct=Decimal("0.2"),
        )

        result = runner.run_card(card, settings=settings, mandate=mandate, start=d1, end=d1)

        assert {t.symbol for t in result.trades} == {"A"}  # first in universe order
        assert result.rejections == ()  # B and C were never submitted at all, not rejected


# ---------------------------------------------------------------------------
# A genuine broker rejection is recorded, not swallowed
# ---------------------------------------------------------------------------


class TestBrokerRejectionRecorded:
    def test_a_rejected_order_is_recorded_and_produces_no_trade(self, settings) -> None:
        dates = _weekdays(dt.date(2026, 1, 5), 6)
        d1 = dates[5]

        _write_bars(settings, "SPY", _flat(dates, 100.0))
        _write_bars(settings, "TEST", _flat(dates, 100.0))

        # min_clip_notional set above any gross this order could ever reach, so the broker's own
        # `_check_buy` refuses it -- this is a rejection the runner must record, not paper over.
        mandate = _mandate(min_clip_notional=Decimal("1000000.00"))
        card = _card(universe=("TEST",), entry="close > 0", position_pct=Decimal("0.5"))

        result = runner.run_card(card, settings=settings, mandate=mandate, start=d1, end=d1)

        assert result.trades == ()
        assert "min_clip" in result.rejections


# ---------------------------------------------------------------------------
# The guard runs once, up front, and a failing card raises rather than running unguarded
# ---------------------------------------------------------------------------


class TestGuardFailure:
    def test_a_card_whose_expression_fails_the_guard_raises(self, settings) -> None:
        dates = _weekdays(dt.date(2026, 1, 5), 6)  # far too few bars for a 20-period SMA's
        # causality window (see `app.backtest.guards._MIN_BARS_FOR_CAUSALITY`)
        d1 = dates[5]

        _write_bars(settings, "SPY", _flat(dates, 100.0))
        _write_bars(settings, "TEST", _flat(dates, 100.0))

        mandate = _mandate()
        card = _card(universe=("TEST",), entry="close > sma(20)")

        with pytest.raises(runner.GuardFailed):
            runner.run_card(card, settings=settings, mandate=mandate, start=d1, end=d1)


# ---------------------------------------------------------------------------
# No lookahead: the decision path is never handed a market whose as_of is on or after the session
# ---------------------------------------------------------------------------


class TestNoLookahead:
    def test_require_decision_market_rejects_same_day_and_later(self, settings) -> None:
        session = Session(index=5, date=dt.date(2026, 3, 10), decided_on=dt.date(2026, 3, 9))

        same_day = AsOfMarket(as_of=session.date, settings=settings)
        with pytest.raises(runner.LookaheadError):
            runner._require_decision_market(same_day, session)

        after = AsOfMarket(as_of=session.date + dt.timedelta(days=1), settings=settings)
        with pytest.raises(runner.LookaheadError):
            runner._require_decision_market(after, session)

        correctly_prior = AsOfMarket(as_of=session.decided_on, settings=settings)
        runner._require_decision_market(correctly_prior, session)  # must not raise

    def test_entry_evaluation_refuses_a_same_day_market(self, settings) -> None:
        """`_rule_fires` -- the function that actually decides whether an entry or a rule-exit fires
        -- is wired to the same assertion, not just the standalone helper above."""
        session = Session(index=1, date=dt.date(2026, 3, 10), decided_on=dt.date(2026, 3, 9))
        same_day_market = AsOfMarket(as_of=session.date, settings=settings)
        tree = rule_grammar.parse("close > 0")

        with pytest.raises(runner.LookaheadError):
            runner._rule_fires(tree, "TEST", market=same_day_market, session=session)

    def test_bracket_evaluation_refuses_a_same_day_market(self, settings) -> None:
        session = Session(index=1, date=dt.date(2026, 3, 10), decided_on=dt.date(2026, 3, 9))
        same_day_market = AsOfMarket(as_of=session.date, settings=settings)
        card = _card(stop_loss_pct=Decimal("0.1"))
        lot = runner._OpenLot(
            entry_price=Decimal("100"),
            entry_date=dt.date(2026, 3, 3),
            entry_session_index=1,
            quantity=Decimal("10"),
            entry_fees=Decimal("0"),
        )

        with pytest.raises(runner.LookaheadError):
            runner._bracket_reason(card, "TEST", lot, market=same_day_market, session=session)


# ---------------------------------------------------------------------------
# D1 -- total_return must be rebased to starting_equity, not to the first session's close
# (DEFECTS.md D1). A card that fills on session one is the case the old formula got wrong: dividing
# every point of the curve by the constant `starting_equity` cancels out of `equity[-1] / equity[0]`,
# so `total_return` came out rebased to `equity_curve[0]` -- the first session's own close -- instead.
# ---------------------------------------------------------------------------


class TestTotalReturnRebasing:
    def test_total_return_is_measured_against_starting_equity_not_the_first_close(
        self, settings
    ) -> None:
        """A single-session run whose fill moves equity away from `starting_equity` on session one.

        Before D1's fix, `equity_curve` has exactly one point here, so the buggy formula divided
        that one point by itself and reported `total_return == 0.0` no matter what actually
        happened -- indistinguishable from a card that never traded at all. This is exactly the gap
        `tests/test_tournament_runner.py::TestNeverTriggers` could not see, because a zero-trade
        card's true and buggy answers coincide at zero.
        """
        dates = _weekdays(dt.date(2026, 1, 5), 6)
        lead_in, trade_dates = dates[:5], dates[5:]
        d1 = trade_dates[0]

        _write_bars(settings, "SPY", _flat(dates, 100.0))
        _write_bars(
            settings,
            "FILLDAY1",
            {**_flat(lead_in, 100.0), d1: (95.0, 105.0)},  # decision close 100 -> entry fires;
            # fills at d1's open (95), then marks at d1's own close (105) -- both different from
            # starting_equity, which is exactly the case the old rebasing hid.
        )

        mandate = _mandate()
        card = _card(
            universe=("FILLDAY1",),
            entry="close > 0",
            position_pct=Decimal("1.0"),
            max_positions=1,
        )

        result = runner.run_card(card, settings=settings, mandate=mandate, start=d1, end=d1)

        assert result.sessions == 1
        assert len(result.trades) == 1  # still open at end -- one unrealised trade
        # quantity = floor(1.0 * 10000 / 100) = 100 filled at open 95 -> cost 9500, cash left 500;
        # marked at close 105 -> equity = 500 + 100*105 = 11000.
        assert result.ending_equity == Decimal("11000.00")
        assert result.starting_equity == Decimal("10000.00")

        # The exact contract from DEFECTS.md D1: total_return must equal
        # ending_equity / starting_equity - 1, to Decimal precision allowing for the float
        # round-trip through `app.backtest.metrics.compute`. Reproducing that same round-trip here
        # (rather than hand-rounding to "0.1") is what makes this comparison exact rather than
        # approximate.
        implied_ratio = float(result.ending_equity / result.starting_equity)
        expected_total_return = Decimal(str(implied_ratio - 1.0))
        assert result.total_return == expected_total_return
        # Concrete sanity check on this fixture's magnitude (not exact equality -- the float
        # round-trip through `compute()` makes `implied_ratio - 1.0` land at
        # 0.10000000000000009, not a clean 0.1; `expected_total_return` above already captures
        # that precisely).
        assert result.total_return == pytest.approx(Decimal("0.1"), abs=Decimal("1e-9"))

        # The old, buggy formula rebased to equity_curve[0] (== ending_equity here, since there is
        # only one session), which cancels to exactly 0.0 -- the sign of the defect, not a rounding
        # difference. This assertion is the one that distinguishes the fix from the bug: it fails
        # under the unfixed code, which reports `Decimal("0.0")` for this exact fixture.
        assert result.total_return != Decimal("0.0")


# ---------------------------------------------------------------------------
# D2 -- capital_exposure measures capital at risk, not merely session presence (DEFECTS.md D2).
# `exposure` (session presence) and `capital_exposure` (capital-weighted) must diverge sharply for a
# card that holds a small slice of the book continuously, and must agree on the zero-trade case.
# ---------------------------------------------------------------------------


class TestCapitalExposure:
    def test_capital_exposure_is_far_below_session_exposure_for_a_thin_continuous_holding(
        self, settings
    ) -> None:
        """A four-slot card that only ever fills one slot, and holds it every session.

        `exposure` (session presence) should read near 1.0 -- a position was open almost every
        session. `capital_exposure` should read near 1/4 -- only a quarter of the book was ever
        actually deployed. Conflating the two is exactly DEFECTS.md D2's reproduction
        (`c04-riskmanaged`'s 97% session exposure against a 44% capital-weighted reality).
        """
        dates = _weekdays(dt.date(2026, 1, 5), 25)
        trade_dates = dates[5:]

        _write_bars(settings, "SPY", _flat(dates, 100.0))
        _write_bars(settings, "SLOT1", _flat(dates, 100.0))  # flat: no stop/target ever fires,

        mandate = _mandate()
        card = _card(
            universe=("SLOT1",),
            entry="close > 0",
            exit="",
            max_hold_days=252,  # far beyond this window -- never times out
            max_positions=4,  # four slots on the card...
            position_pct=Decimal("0.25"),  # ...but only one symbol in the universe ever fills one
        )

        result = runner.run_card(
            card, settings=settings, mandate=mandate, start=trade_dates[0], end=trade_dates[-1]
        )

        assert result.sessions == len(trade_dates)
        assert len(result.trades) == 1  # one lot, opened once, held to the end
        assert result.exposure is not None
        assert result.capital_exposure is not None

        # Flat prices at 100 make the arithmetic exact: quantity = floor(0.25*10000/100) = 25,
        # entry notional 2500 every session, over starting equity 10000 -> 0.25 every session.
        assert result.capital_exposure == pytest.approx(0.25, abs=1e-9)

        # Session presence: the lot opens on the very first trading session and is never closed,
        # so every session after the D1 fix's prepended pre-trade point has a position open.
        assert result.exposure == pytest.approx(1.0, abs=0.05)

        # `exposure` is a fraction *of trading sessions*, so multiplying it back by `sessions` must
        # recover a whole number -- the count of sessions that held something. This pins the
        # denominator, which the tolerance above is too loose to catch. Fixing D1 required prepending
        # an alignment point to `in_position`, and that point silently entered `mean(in_position)`'s
        # denominator, turning a card held on every one of 250 sessions into 250/251. It is rescaled
        # back out in `runner._undilute_exposure`; if that ever regresses, this assertion fails while
        # the one above still passes.
        held_sessions = result.exposure * result.sessions
        assert held_sessions == pytest.approx(round(held_sessions), abs=1e-6)

        # The pin DEFECTS.md D2 exists for: the two must disagree, and disagree by a lot.
        assert result.capital_exposure < result.exposure - 0.5

    def test_capital_exposure_is_zero_for_a_card_that_never_trades(self, settings) -> None:
        """Consistency with `exposure`'s own zero-trade behaviour: both report `0.0`, not `None`,
        because `compute()` only returns `None` for an empty equity array, and `SessionCalendar`
        never yields zero sessions -- there is always a session denominator to average over, it is
        just averaging zeroes."""
        dates = _weekdays(dt.date(2026, 1, 5), 15)
        trade_dates = dates[5:]
        _write_bars(settings, "SPY", _flat(dates, 100.0))
        _write_bars(settings, "NOFILL", _flat(dates, 100.0))

        mandate = _mandate()
        card = _card(entry="close > 999999", universe=("NOFILL",))

        result = runner.run_card(
            card, settings=settings, mandate=mandate, start=trade_dates[0], end=trade_dates[-1]
        )

        assert result.trades == ()
        assert result.exposure == 0.0
        assert result.capital_exposure == 0.0

class TestSignalTableMatchesPerSessionEvaluation:
    """The equivalence `_SignalTable` rests on, pinned so it cannot rot quietly.

    The table evaluates a rule once across a run and indexes it per session, in place of
    re-evaluating it on every session. That holds only because both paths read the *same* frame --
    every stored bar up to the decision date -- and because the indicators are causal, which
    `app.backtest.guards.check` verifies per card.

    An earlier version of the table read a different (longer) frame than `_rule_fires` did, and the
    two disagreed: `ema` and Wilder `rsi` carry a seed decaying from wherever their frame began, and
    a ~1.8e-5 difference flipped one crossing across 246 committed runs. That is `DEFECTS.md` D4, and
    it is why this test exists rather than a comment asserting the two are obviously the same.
    """

    def test_table_and_per_session_agree_on_every_session(self, settings) -> None:
        dates = _weekdays(dt.date(2024, 1, 1), 120)
        # Deliberately seed-sensitive: two recursive averages that actually cross, plus a recursive
        # oscillator. A windowed-only expression would pass this test vacuously.
        tree = rule_grammar.parse("ema(5) crosses_above ema(20) and rsi(14) < 70 and close > sma(30)")

        _write_bars(
            settings,
            "TEST",
            {
                d: (100.0 + (i % 17) - (i % 5) * 2.0, 100.0 + (i % 19) - (i % 7) * 2.5)
                for i, d in enumerate(dates)
            },
        )

        table = runner._build_signal_table(
            tree, ("TEST",), settings=settings, through=dates[-1]
        )

        compared = fired = 0
        for i in range(31, len(dates)):
            # A session is decided on the previous session's close and traded on its own.
            session = Session(index=i, date=dates[i], decided_on=dates[i - 1])
            market = AsOfMarket(as_of=dates[i - 1], settings=settings)
            per_session = runner._rule_fires(tree, "TEST", market=market, session=session)
            assert table.fires("TEST", dates[i - 1]) == per_session, (
                f"table disagrees with per-session evaluation on {dates[i - 1]}"
            )
            compared += 1
            fired += bool(per_session)

        assert compared >= 25, "too few sessions compared for this to mean anything"
        assert fired > 0, "the rule never fired, so agreement here proves nothing"

    def test_an_unknown_symbol_or_date_is_false_not_an_error(self, settings) -> None:
        """Same contract as `_rule_fires`: an unknown truth value cannot open or close a position."""
        table = runner._SignalTable({})
        assert table.fires("NOPE", dt.date(2026, 3, 9)) is False


# ---------------------------------------------------------------------------
# Ranked entry selection -- which of the qualifying names takes a scarce slot
# ---------------------------------------------------------------------------


class TestOrderedEntryCandidates:
    """`runner._ordered_entry_candidates` in isolation, where the sort can be stated exactly.

    Driven through a hand-built `_RankTable` rather than through bars, because the properties under
    test are about the *ordering* -- stability, where an unknown key goes -- and building them out of
    real price history would make each case depend on an indicator's warmup as well.
    """

    UNIVERSE = ("A", "B", "C", "D")

    @staticmethod
    def _table(values: dict[str, float | None], on: dt.date) -> runner._RankTable:
        import numpy as np

        return runner._RankTable(
            {
                symbol: pd.Series([np.nan if v is None else v], index=pd.Index([on]))
                for symbol, v in values.items()
            }
        )

    def test_an_unranked_card_gets_universe_order_unchanged(self) -> None:
        # The reproducibility guarantee every frozen card depends on: no ranking key means the
        # identical order the runner walked before this feature existed.
        empty = runner._RankTable({})
        assert (
            runner._ordered_entry_candidates(self.UNIVERSE, empty, on=dt.date(2026, 1, 5))
            == self.UNIVERSE
        )

    def test_highest_key_comes_first(self) -> None:
        on = dt.date(2026, 1, 5)
        table = self._table({"A": 1.0, "B": 3.0, "C": 2.0, "D": 0.5}, on)
        assert runner._ordered_entry_candidates(self.UNIVERSE, table, on=on) == ("B", "C", "A", "D")

    def test_a_tie_keeps_universe_order(self) -> None:
        # Two names with an identical key must resolve the way they always did, not by an accident
        # of how the sort happens to treat equal elements.
        on = dt.date(2026, 1, 5)
        table = self._table({"A": 1.0, "B": 2.0, "C": 2.0, "D": 1.0}, on)
        assert runner._ordered_entry_candidates(self.UNIVERSE, table, on=on) == ("B", "C", "A", "D")

    def test_a_symbol_with_no_key_sorts_behind_every_ranked_one(self) -> None:
        # NaN is "this run cannot say", not "ranks lowest" -- and two unknowns keep universe order
        # between themselves rather than landing wherever the sort drops them.
        on = dt.date(2026, 1, 5)
        table = self._table({"A": None, "B": -5.0, "C": None, "D": 1.0}, on)
        assert runner._ordered_entry_candidates(self.UNIVERSE, table, on=on) == ("D", "B", "A", "C")

    def test_a_negative_key_inverts_the_order(self) -> None:
        # The documented way to ask for the weakest name, since there is no direction field.
        on = dt.date(2026, 1, 5)
        table = self._table({"A": -1.0, "B": -3.0, "C": -2.0, "D": -0.5}, on)
        assert runner._ordered_entry_candidates(self.UNIVERSE, table, on=on) == ("D", "A", "C", "B")


class TestRankedSelectionEndToEnd:
    """The same three-name, one-slot contention `TestMaxPositions` sets up, with and without a key.

    That test asserts `A` is bought "first in universe order" -- the arbitrary tiebreak this feature
    exists to replace. These two run the identical setup and assert the two different answers.
    """

    @staticmethod
    def _rising(dates: list[dt.date], start: float, step: float) -> dict[dt.date, tuple[float, float]]:
        return {d: (start + step * i, start + step * i) for i, d in enumerate(dates)}

    def test_without_a_key_the_first_name_in_the_array_wins(self, settings) -> None:
        dates = _weekdays(dt.date(2025, 10, 1), 60)  # enough history for sma(5)'s causality window
        d1 = dates[59]
        _write_bars(settings, "SPY", _flat(dates, 100.0))
        _write_bars(settings, "A", self._rising(dates, 100.0, 0.1))
        _write_bars(settings, "B", self._rising(dates, 100.0, 0.5))
        _write_bars(settings, "C", self._rising(dates, 100.0, 2.0))

        card = _card(
            universe=("A", "B", "C"), entry="close > 0", max_positions=1, position_pct=Decimal("0.2")
        )
        result = runner.run_card(
            card, settings=settings, mandate=_mandate(max_positions=5), start=d1, end=d1
        )
        assert {t.symbol for t in result.trades} == {"A"}

    def test_with_a_key_the_strongest_name_wins_instead(self, settings) -> None:
        dates = _weekdays(dt.date(2025, 10, 1), 60)  # same fixture as the control above
        d1 = dates[59]
        _write_bars(settings, "SPY", _flat(dates, 100.0))
        # C is furthest above its own 5-day average, A is barely above it. Same qualifying set --
        # `close > 0` is true for all three -- so the only thing choosing between them is the key.
        _write_bars(settings, "A", self._rising(dates, 100.0, 0.1))
        _write_bars(settings, "B", self._rising(dates, 100.0, 0.5))
        _write_bars(settings, "C", self._rising(dates, 100.0, 2.0))

        card = _card(
            universe=("A", "B", "C"),
            entry="close > 0",
            max_positions=1,
            position_pct=Decimal("0.2"),
            rank_by="close / sma(5)",
        )
        result = runner.run_card(
            card, settings=settings, mandate=_mandate(max_positions=5), start=d1, end=d1
        )
        assert {t.symbol for t in result.trades} == {"C"}

    def test_an_unguardable_ranking_key_is_refused_exactly_as_a_rule_is(self, settings) -> None:
        # Same construction as `TestGuardFailure` -- far too few bars for a 20-period SMA's
        # causality window -- but with the offending expression in `rank_by` while `entry` is
        # clean. Without the guard reaching the key, this card would run: the entry rule passes,
        # and the un-causal expression would only ever show up in *which* name got the slot.
        dates = _weekdays(dt.date(2026, 1, 5), 6)
        d1 = dates[5]
        _write_bars(settings, "SPY", _flat(dates, 100.0))
        _write_bars(settings, "A", _flat(dates, 100.0))

        card = _card(universe=("A",), entry="close > 0", rank_by="close / sma(20)")
        with pytest.raises(runner.GuardFailed) as excinfo:
            runner.run_card(card, settings=settings, mandate=_mandate(), start=d1, end=d1)
        assert excinfo.value.field == "rank_by"


class TestRankByValidation:
    """`StrategyCard.rank_by` is checked at load, not on the session it first has to break a tie.

    The runner walks past a failed card by design (`PROTOCOL.md` §8), so a key that only blows up
    mid-run would produce a quietly short round rather than a loud failure -- and only on whichever
    window first put more qualifying names in front of the card than it had slots.
    """

    def test_it_is_optional_and_defaults_to_none(self) -> None:
        assert _card().rank_by is None

    @pytest.mark.parametrize(
        "expression", ["close / sma(200)", "rsi(14)", "(close - sma(50)) / atr(14)", "0 - rsi(14)"]
    )
    def test_a_numeric_key_is_accepted(self, expression: str) -> None:
        assert _card(rank_by=expression).rank_by == expression

    def test_a_condition_is_rejected_with_an_actionable_message(self) -> None:
        with pytest.raises(ValueError, match="not a ranking key"):
            _card(rank_by="close > sma(50)")

    def test_an_empty_string_is_rejected_rather_than_read_as_unset(self) -> None:
        # `""` and `None` would otherwise mean the same thing while looking like a deliberate choice.
        with pytest.raises(ValueError, match="Leave it unset"):
            _card(rank_by="   ")

    def test_a_malformed_expression_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="not a ranking key"):
            _card(rank_by="sma(")

    def test_every_frozen_library_card_still_loads(self) -> None:
        """The reproducibility guarantee, asserted against the real library rather than a fixture.

        Adding a field to a frozen model is exactly the kind of change that invalidates a stored
        card. `StrategyCard` is `extra="forbid"`, so this would also catch the reverse mistake --
        a card in the library carrying a field the model does not know about.
        """
        import json
        import re
        from pathlib import Path

        library = Path(__file__).resolve().parents[1] / "backend" / "app" / "paper" / "library"
        cards = sorted(library.rglob("*.json"))
        assert cards, f"no library cards found under {library}"

        # Machine-proposed cards are exempt from the `rank_by` rule -- and are identified by their
        # own id, not by which directory they are sitting in.
        #
        # `app.evolution.models.genome_id_for` mints `g{generation:03d}-{12 hex}`, and that id *is*
        # the card's `agent_id`. Keying on it holds wherever the file lives, which matters because
        # `app.evolution.promotion` copies a card out of `generated/` into `candidates/` when it
        # clears the gate twice -- an earlier version of this exemption excluded the `generated/`
        # directory instead and broke the first time a card was actually promoted.
        #
        # The rule itself is unchanged for every hand-authored card: `rank_by is None` exists for
        # cards "frozen before that field existed", whose published numbers were produced by
        # universe-order fills. A card the loop designed in 2026-08 is not one of those, and setting
        # `rank_by` is the better choice for it anyway -- leaving it unset exposes a card to the
        # 53.9-point ordering spread `strategy-program/PROTOCOL.md` section 7 measured.
        # `{3,}`, not `{3}`: `genome_id_for` formats the generation with `:03d`, which pads *up to*
        # three digits and then simply keeps counting -- so generation 1679 mints `g1679-...` and an
        # exact-three-digit pattern stops matching the first time a loop runs past generation 999.
        # It did: this test went red on `g1679-12eaf5c6bd56.json` with the misleading complaint that
        # a card "frozen before that field existed" had set `rank_by`, about a card designed the day
        # before. Every one of the 25 promoted cards on the shelf is four-digit but one.
        machine_proposed = re.compile(r"^g\d{3,}-[0-9a-f]{12}$")

        loaded = 0
        exempt = 0
        for path in cards:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if "entry" not in payload:
                continue  # allocation / ladder cards are a different model -- see their own tests
            card = StrategyCard.model_validate(payload)
            if machine_proposed.match(card.agent_id):
                exempt += 1
                continue
            assert card.rank_by is None, (
                f"{path.name} sets rank_by; every card frozen before that field existed must "
                "leave it unset, since its published numbers were produced by universe-order fills"
            )
            loaded += 1
        # `loaded` counts the hand-authored cards the rule actually applies to. It must stay positive
        # even on a machine where the loop has promoted several cards, or this test would silently
        # become a no-op the day the library was all machine-proposed.
        assert loaded > 0, f"no hand-authored cards found ({exempt} machine-proposed ones skipped)"

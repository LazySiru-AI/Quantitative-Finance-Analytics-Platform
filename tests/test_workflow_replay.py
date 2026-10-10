"""Tests for the decision-log replay engine (`backend/app/workflow/replay.py`).

**Never hits the real network or the real bar store.** Every bar this file needs is written directly
into a temp-rooted DuckDB/Parquet store, mirroring `tests/test_workflow_book.py`'s own `_write_bar`
helper and `tests/test_tournament_runner.py`'s `_write_bars`/`_card` helpers -- this repo's
established pattern for a paper-broker/tournament-runner test fixture. Neither shared helper is
imported across test files (each file keeps its own small copy, per this repo's established
convention -- see `tests/test_workflow_book.py`'s own module docstring for the same choice), so this
file keeps its own.
"""

from __future__ import annotations

import datetime as dt
import math
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from app.config import Settings
from app.db import duck
from app.market.models import BAR_COLUMNS, Interval
from app.paper.marketdata import SessionCalendar
from app.paper.paperbroker import Mandate
from app.tournament import runner
from app.tournament.models import DESIGN_THROUGH, Discipline, StrategyCard
from app.workflow import replay
from app.workflow.book_models import WorkflowOrderRecord

# ---------------------------------------------------------------------------
# Builders -- local to this file; see the module docstring.
# ---------------------------------------------------------------------------


def _weekdays(anchor: dt.date, count: int) -> list[dt.date]:
    dates: list[dt.date] = []
    day = anchor
    while len(dates) < count:
        if day.weekday() < 5:
            dates.append(day)
        day += dt.timedelta(days=1)
    return dates


def _write_bars(settings: Settings, symbol: str, prices: dict[dt.date, tuple[float, float]]) -> None:
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
        "persona_id": "replay-test",
        "display_name": "Replay Test",
        "account_id": "replay-acct",
        "account_label": "Replay Test Account",
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
        "universe": ("WF",),
        "entry": "close > 0",
        "exit": "",
        "max_hold_days": 50,
        "max_positions": 1,
        "position_pct": Decimal("1.0"),
        "designed_through": DESIGN_THROUGH,
    }
    fields.update(overrides)
    return StrategyCard(**fields)  # type: ignore[arg-type]


def _order(
    *,
    order_id: str,
    symbol: str,
    side: str,
    notional: str,
    decision_date: dt.date,
    fill_date: dt.date,
) -> WorkflowOrderRecord:
    return WorkflowOrderRecord(
        order_id=order_id,
        arm="raw_signal",
        agent_card_id="card-1",
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        notional=Decimal(notional),
        decision_date=decision_date,
        fill_date=fill_date,
        status="pending",
        thesis="a replay test thesis",
        invalidation="a replay test invalidation",
        created_by_run_id="run-1",
    )


# ---------------------------------------------------------------------------
# 1. Hand-built order list -> expected equity and non-annualised realized_vol
# ---------------------------------------------------------------------------


class TestHandBuiltReplay:
    def test_equity_curve_and_realized_vol_match_hand_computed_values(self, settings: Settings) -> None:
        dates = _weekdays(dt.date(2026, 1, 5), 5)
        lead_in, trade_dates = dates[:2], dates[2:]
        d1, d2, d3 = trade_dates

        _write_bars(settings, "SPY", _flat(dates, 100.0))
        _write_bars(
            settings,
            "AAA",
            {
                **_flat(lead_in, 50.0),
                d1: (51.0, 55.0),
                d2: (55.0, 58.0),
                d3: (58.0, 60.0),
            },
        )

        mandate = _mandate()
        calendar = SessionCalendar(start=d1, end=d3, settings=settings)
        order = _order(
            order_id="wf-0",
            symbol="AAA",
            side="buy",
            notional="1000.00",
            decision_date=lead_in[-1],
            fill_date=d1,
        )

        result = replay.run_decision_log(
            [order], settings=settings, calendar=calendar, mandate=mandate, starting_cash=mandate.starting_cash
        )

        # 1000 / 50.00 decision close -> 20 whole shares, filled at d1's 51.00 open (no slippage).
        # cash after fill: 10000 - 20*51 = 8980.
        starting_cash = Decimal("10000")
        expected_equity = [
            Decimal("8980") + Decimal("20") * Decimal("55"),  # 10080
            Decimal("8980") + Decimal("20") * Decimal("58"),  # 10140
            Decimal("8980") + Decimal("20") * Decimal("60"),  # 10180
        ]
        assert [p.equity for p in result.equity_curve] == expected_equity

        expected_returns = []
        prior = starting_cash
        for e in expected_equity:
            expected_returns.append(e / prior - 1)
            prior = e
        assert result.daily_returns == tuple(expected_returns)

        expected_total_return = float(expected_equity[-1] / starting_cash - 1)
        assert result.metrics.total_return is not None
        assert math.isclose(result.metrics.total_return, expected_total_return, rel_tol=1e-9)

        # Monotonically increasing equity -> no drawdown.
        assert result.metrics.max_drawdown == pytest.approx(0.0, abs=1e-12)

        expected_vol = float(np.std(np.array([float(r) for r in expected_returns], dtype=np.float64)))
        assert math.isclose(float(result.realized_vol), expected_vol, rel_tol=1e-9)

        # Held the whole window, never sold -> exactly one open-at-end trade, no closed trades.
        assert result.metrics.trades == 1
        assert result.metrics.win_rate is None
        # Exposure: invested on every one of the 3 real sessions.
        assert result.metrics.exposure == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 2. An unpriceable order is skipped, not raised
# ---------------------------------------------------------------------------


class TestUnpriceableOrderIsSkipped:
    def test_a_symbol_with_no_stored_close_never_reaches_the_broker(self, settings: Settings) -> None:
        dates = _weekdays(dt.date(2026, 2, 2), 4)
        lead_in, trade_dates = dates[:1], dates[1:]
        d1, _d2, d3 = trade_dates
        _write_bars(settings, "SPY", _flat(dates, 100.0))
        # "ZZZ" never gets a single stored bar.

        mandate = _mandate()
        calendar = SessionCalendar(start=d1, end=d3, settings=settings)
        order = _order(
            order_id="wf-1",
            symbol="ZZZ",
            side="buy",
            notional="500.00",
            decision_date=lead_in[-1],
            fill_date=d1,
        )

        result = replay.run_decision_log(
            [order], settings=settings, calendar=calendar, mandate=mandate, starting_cash=mandate.starting_cash
        )

        assert result.metrics.trades == 0
        assert [p.equity for p in result.equity_curve] == [mandate.starting_cash] * 3
        assert result.metrics.total_return == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 3. A closed round trip produces a real win_rate
# ---------------------------------------------------------------------------


class TestRoundTripTrade:
    def test_a_buy_then_sell_produces_one_closed_winning_trade(self, settings: Settings) -> None:
        dates = _weekdays(dt.date(2026, 3, 2), 5)
        lead_in, trade_dates = dates[:2], dates[2:]
        d1, d2, d3 = trade_dates
        _write_bars(settings, "SPY", _flat(dates, 100.0))
        _write_bars(
            settings,
            "BBB",
            {
                **_flat(lead_in, 20.0),
                d1: (20.0, 21.0),
                d2: (21.0, 25.0),  # decision close for the sell (staged against d2)
                d3: (25.0, 25.0),
            },
        )

        mandate = _mandate()
        calendar = SessionCalendar(start=d1, end=d3, settings=settings)
        buy = _order(
            order_id="wf-2",
            symbol="BBB",
            side="buy",
            notional="2000.00",
            decision_date=lead_in[-1],
            fill_date=d1,
        )
        # Buy sizes to 2000.00 / 20.00 (lead_in close) = 100 shares. The sell is sized to the same
        # 100 shares against its own decision close (d1's 21.00): 100 * 21.00 = 2100.00, so it closes
        # the whole lot rather than leaving a remainder or asking for more than is held.
        sell = _order(
            order_id="wf-3",
            symbol="BBB",
            side="sell",
            notional="2100.00",
            decision_date=d1,
            fill_date=d2,
        )

        result = replay.run_decision_log(
            [buy, sell],
            settings=settings,
            calendar=calendar,
            mandate=mandate,
            starting_cash=mandate.starting_cash,
        )

        assert result.metrics.trades == 1
        assert result.metrics.win_rate == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 4. Engine-honesty control (docs/WORKFLOW-STUDY-PLAN.md §5)
# ---------------------------------------------------------------------------


class TestEngineHonestyControl:
    """`run_decision_log` and `app.tournament.runner.run_card` must agree on the raw arm's own
    decisions, replayed on a shared window.

    **What this covers.** A single strategy card (`entry="close > 0"`, no exit, no stop/target/time
    stop) fires on the very first session and is held to the end of a short synthetic window --
    `run_card`'s own `RealisedTrade` for that position (its entry price and quantity) is used to build
    the *exact same* order as a `WorkflowOrderRecord` (`notional = quantity * entry_price`, so
    `run_decision_log`'s own notional-to-quantity sizing recovers the identical share count), and both
    engines are then asked to score it over the identical `[start, end]` window against the identical
    `Mandate` and the identical stored bars. Their ending equity and their `total_return`/
    `max_drawdown` (both derived by the one shared `app.backtest.metrics.compute`) must match exactly.

    **What this does not cover.** Multi-session exit chains (stop/target/time-stop precedence),
    rank-based candidate selection under contention for scarce `max_positions` slots, partial fills,
    rejections, and a real multi-year window with real market data are all `run_card` behaviour this
    test never exercises -- a full parity claim across all of those would need a much larger fixture
    (or a property-based one) than a unit test affords. What is verified here is the one seam
    `docs/WORKFLOW-STUDY-PLAN.md` §5 actually asks for: that resubmitting the raw arm's own recorded
    decision through this module's broker-driving loop reproduces `run_card`'s own fill and mark for
    that decision, not some other, silently-different number.
    """

    def test_a_single_buy_and_hold_decision_scores_identically_through_both_engines(
        self, settings: Settings
    ) -> None:
        dates = _weekdays(dt.date(2026, 4, 6), 6)
        lead_in, trade_dates = dates[:3], dates[3:]
        d1, d2, d3 = trade_dates

        _write_bars(settings, "SPY", _flat(dates, 100.0))
        # d1's open (52.00) gaps *down* from the decision close (55.00) that both engines size
        # against, deliberately -- an overnight gap *up* would size the position off the lower
        # decision close and then have to pay the higher open price, which can exceed the mandate's
        # cash and get the very first entry attempt rejected (a real, separately interesting case,
        # but not the one this control is isolating: see this class's own docstring on scope).
        _write_bars(
            settings,
            "WF",
            {
                **_flat(lead_in, 55.0),
                d1: (52.0, 60.0),
                d2: (60.0, 62.0),
                d3: (62.0, 65.0),
            },
        )

        mandate = _mandate(starting_cash=Decimal("10000.00"))
        card = _card()

        card_result = runner.run_card(card, settings=settings, mandate=mandate, start=d1, end=d3)
        assert len(card_result.trades) == 1
        trade = card_result.trades[0]
        assert trade.exit_date is None  # still open at the end -- the scenario this control needs

        # Reproduce run_card's own decision as a WorkflowOrderRecord. `run_card` sizes a position at
        # `card.position_pct * mandate.starting_cash` against the *decision-date close* (never the
        # fill price -- see `run_card`'s own "Position sizing" docstring section), and
        # `run_decision_log`'s `_quantity_for_notional` divides by that same decision-date close, so
        # handing it the identical dollar notional recovers `trade.quantity` exactly. Sizing this off
        # `trade.entry_price` instead (the *fill* price, which includes the overnight gap from 50.00
        # to 52.00) would silently ask for a different share count than `run_card` actually bought --
        # the mistake this control exists to catch.
        record_notional = card.position_pct * mandate.starting_cash
        record = _order(
            order_id="honesty-0",
            symbol="WF",
            side="buy",
            notional=str(record_notional),
            decision_date=lead_in[-1],
            fill_date=d1,
        )

        calendar = SessionCalendar(start=d1, end=d3, settings=settings)
        replay_result = replay.run_decision_log(
            [record],
            settings=settings,
            calendar=calendar,
            mandate=mandate,
            starting_cash=mandate.starting_cash,
        )

        assert replay_result.equity_curve[-1].equity == card_result.ending_equity
        assert replay_result.metrics.total_return is not None
        assert math.isclose(
            replay_result.metrics.total_return, float(card_result.total_return), rel_tol=1e-9
        )
        assert math.isclose(
            replay_result.metrics.max_drawdown or 0.0, float(card_result.max_drawdown), rel_tol=1e-9, abs_tol=1e-12
        )

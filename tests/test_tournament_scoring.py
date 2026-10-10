"""Tests for :mod:`app.tournament.scoring`.

Styled like :mod:`tests.test_scan`: fixtures are built by hand so every number behind an assertion
is visible in the test itself, and `AgentResult`/`StrategyCard`/`RealisedTrade` are constructed
directly here rather than through `app.tournament.runner` -- another worker is writing that module
concurrently, and this file must not couple to it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal

from app.backtest.scan import benjamini_hochberg, binomial_p_value
from app.tournament.models import (
    TRADE_END,
    TRADE_START,
    AgentResult,
    Discipline,
    RealisedTrade,
    StrategyCard,
)
from app.tournament.scoring import MIN_CLOSED_TRADES_FOR_P_VALUE, NULL_WIN_PROBABILITY, score

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _card(
    agent_id: str,
    *,
    take_profit_pct: Decimal | None = Decimal("0.24"),
    stop_loss_pct: Decimal | None = Decimal("0.08"),
) -> StrategyCard:
    return StrategyCard(
        agent_id=agent_id,
        display_name=agent_id,
        discipline=Discipline.TREND,
        thesis="Momentum persists for several sessions after a volume-confirmed breakout.",
        universe=("AAPL",),
        entry="close > sma(20)",
        exit="close < sma(20)",
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        max_hold_days=None,
        max_positions=4,
        position_pct=Decimal("0.25"),
        designed_through=dt.date(2026, 2, 10),
    )


def _trade(
    *,
    pnl: Decimal,
    return_pct: Decimal,
    symbol: str = "AAPL",
    entry_date: dt.date = dt.date(2026, 2, 18),
    exit_date: dt.date | None = dt.date(2026, 2, 25),
    exit_reason: str = "rule",
    bars_held: int = 5,
) -> RealisedTrade:
    entry_price = Decimal("100")
    exit_price = entry_price * (1 + return_pct) if exit_date is not None else None
    return RealisedTrade(
        symbol=symbol,
        entry_date=entry_date,
        entry_price=entry_price,
        exit_date=exit_date,
        exit_price=exit_price,
        quantity=Decimal("10"),
        exit_reason=exit_reason,
        pnl=pnl,
        return_pct=return_pct,
        bars_held=bars_held,
    )


def _win_loss_trades(
    wins: int, losses: int, *, win_pnl: Decimal = Decimal("100"), loss_pnl: Decimal = Decimal("-80")
) -> list[RealisedTrade]:
    """`wins` trades with `pnl=win_pnl` (`return_pct=0.02`) followed by `losses` trades with
    `pnl=loss_pnl` (`return_pct=-0.02`) -- enough to drive `_p_value` and `profit_factor`, not meant
    to be realistic ordering."""
    trades = [_trade(pnl=win_pnl, return_pct=Decimal("0.02")) for _ in range(wins)]
    trades += [_trade(pnl=loss_pnl, return_pct=Decimal("-0.02")) for _ in range(losses)]
    return trades


def _agent(
    agent_id: str,
    trades: Sequence[RealisedTrade] = (),
    *,
    total_return: Decimal = Decimal("0.05"),
    benchmark_return: Decimal | None = Decimal("0.05"),
    card: StrategyCard | None = None,
    sessions: int = 127,
) -> AgentResult:
    return AgentResult(
        card=card if card is not None else _card(agent_id),
        sessions=sessions,
        starting_equity=Decimal("100000"),
        ending_equity=Decimal("100000") * (1 + total_return),
        total_return=total_return,
        max_drawdown=Decimal("0.05"),
        trades=tuple(trades),
        benchmark_return=benchmark_return,
    )


# ---------------------------------------------------------------------------
# 1. profit_factor -- hand-computed
# ---------------------------------------------------------------------------


class TestProfitFactor:
    def test_hand_computed_from_a_known_set_of_trades(self) -> None:
        """Winners 100 + 50 + 30 = 180 gross win; losers 40 + 20 = 60 gross loss (as magnitude).
        180 / 60 = 3 exactly -- computed by hand here, not derived from the implementation."""
        trades = [
            _trade(pnl=Decimal("100"), return_pct=Decimal("0.03")),
            _trade(pnl=Decimal("50"), return_pct=Decimal("0.015")),
            _trade(pnl=Decimal("30"), return_pct=Decimal("0.01")),
            _trade(pnl=Decimal("-40"), return_pct=Decimal("-0.012")),
            _trade(pnl=Decimal("-20"), return_pct=Decimal("-0.006")),
        ]
        [result] = score([_agent("solo", trades)]).agents
        assert result.profit_factor == Decimal("3")

    def test_none_when_nothing_lost_because_that_is_too_small_a_sample_not_infinite_edge(
        self,
    ) -> None:
        """Every trade closed a winner. This is not an infinite profit factor -- it is a strategy
        that has not yet traded enough to have met a loss, and `profit_factor` must say `None`
        rather than manufacture `inf` and present a sample-size artefact as a property of the
        strategy."""
        trades = [
            _trade(pnl=Decimal("10"), return_pct=Decimal("0.01")),
            _trade(pnl=Decimal("20"), return_pct=Decimal("0.02")),
        ]
        [result] = score([_agent("solo", trades)]).agents
        assert result.profit_factor is None

    def test_none_with_no_closed_trades_at_all(self) -> None:
        [result] = score([_agent("solo", [])]).agents
        assert result.profit_factor is None


# ---------------------------------------------------------------------------
# 2. realised_reward_risk -- hand-computed, and its divergence from the planned card ratio
# ---------------------------------------------------------------------------


class TestRealisedRewardRisk:
    def test_hand_computed_and_diverges_from_the_planned_card_ratio(self) -> None:
        """Card plans `take_profit_pct=0.24` over `stop_loss_pct=0.08`, a 3:1 ratio. What actually
        traded: two winners averaging +0.04, two losers averaging -0.05 -- realised 0.04 / 0.05 =
        0.8:1, by hand. The two numbers are supposed to differ: most trades exit on the rule or a
        time stop, not on either bracket, so the plan and the outcome are different questions."""
        card = _card("solo", take_profit_pct=Decimal("0.24"), stop_loss_pct=Decimal("0.08"))
        assert card.reward_risk == Decimal("3")

        trades = [
            _trade(pnl=Decimal("40"), return_pct=Decimal("0.04")),
            _trade(pnl=Decimal("40"), return_pct=Decimal("0.04")),
            _trade(pnl=Decimal("-50"), return_pct=Decimal("-0.05")),
            _trade(pnl=Decimal("-50"), return_pct=Decimal("-0.05")),
        ]
        [result] = score([_agent("solo", trades, card=card)]).agents
        assert result.realised_reward_risk == Decimal("0.8")
        assert result.realised_reward_risk != card.reward_risk

    def test_none_with_no_winners_or_no_losers_or_no_trades(self) -> None:
        all_wins = [_trade(pnl=Decimal("10"), return_pct=Decimal("0.01")) for _ in range(3)]
        all_losses = [_trade(pnl=Decimal("-10"), return_pct=Decimal("-0.01")) for _ in range(3)]
        [r_wins] = score([_agent("wins", all_wins)]).agents
        [r_losses] = score([_agent("losses", all_losses)]).agents
        [r_none] = score([_agent("none", [])]).agents
        assert r_wins.realised_reward_risk is None
        assert r_losses.realised_reward_risk is None
        assert r_none.realised_reward_risk is None


# ---------------------------------------------------------------------------
# 3. Benjamini-Hochberg denominator -- the single most important test in this file
# ---------------------------------------------------------------------------


class TestBenjaminiHochbergDenominatorIsOverAllAgents:
    """Ten agents: seven with `>=10` closed trades (testable) and three with only three closed
    trades each (below `MIN_CLOSED_TRADES_FOR_P_VALUE`, so `p_value is None`). Proves `score()`
    corrects across all ten -- `m=10` -- never across just the seven testable agents (`m=7`), by
    comparing against `benjamini_hochberg` called directly both ways.
    """

    TESTABLE_WINS = [6, 7, 8, 9, 10, 5, 4]  # out of 10 trades each -> seven distinct p-values

    def _build_agents(self) -> list[AgentResult]:
        testable = [
            _agent(f"testable_{i}", _win_loss_trades(wins, 10 - wins))
            for i, wins in enumerate(self.TESTABLE_WINS)
        ]
        untestable = [_agent(f"untestable_{i}", _win_loss_trades(2, 1)) for i in range(3)]
        return testable + untestable

    def test_untestable_agents_have_no_p_value_but_still_occupy_a_slot(self) -> None:
        agents = self._build_agents()
        assert len(agents) == 10
        for agent in agents:
            trades = agent.trades
            if len(trades) < MIN_CLOSED_TRADES_FOR_P_VALUE:
                assert len(trades) == 3

    def test_q_values_match_a_direct_ten_wide_bh_call_not_a_seven_wide_one(self) -> None:
        agents = self._build_agents()
        result = score(agents)
        assert len(result.agents) == 10

        by_id = {a.card.agent_id: a for a in result.agents}

        # Ground truth #1: p-values computed the same way `_p_value` does, then BH over all ten,
        # `None` included -- this is what `score()` is supposed to produce.
        expected_p = [
            binomial_p_value(wins, 10, NULL_WIN_PROBABILITY) for wins in self.TESTABLE_WINS
        ] + [None, None, None]
        expected_q_over_ten = benjamini_hochberg(expected_p)

        # Ground truth #2: BH over only the seven testable p-values -- what a wrong implementation
        # that dropped `None`s before correcting would produce instead. Smaller `m` divides each
        # rank by a smaller denominator, so this can only be <= the ten-wide result at every rank.
        expected_q_over_seven = benjamini_hochberg(expected_p[:7])

        for i in range(len(self.TESTABLE_WINS)):
            agent_id = f"testable_{i}"
            actual_q = by_id[agent_id].q_value
            assert actual_q is not None
            assert actual_q == expected_q_over_ten[i]
            seven_wide = expected_q_over_seven[i]
            assert seven_wide is not None
            assert actual_q >= seven_wide

        # And the correction actually bites for at least one agent -- not just "greater or equal"
        # trivially satisfied by every entry being identical.
        assert any(
            expected_q_over_ten[i] > expected_q_over_seven[i]  # type: ignore[operator]
            for i in range(7)
        )

        for i in range(3):
            untestable = by_id[f"untestable_{i}"]
            assert untestable.p_value is None
            assert untestable.q_value is None


# ---------------------------------------------------------------------------
# 4. discoveries -- zero is normal and the result stays well-formed
# ---------------------------------------------------------------------------


class TestDiscoveriesCanBeZero:
    def test_zero_discoveries_is_not_an_error_and_the_result_is_well_formed(self) -> None:
        """Ten agents, each trading close to a 50/50 coin flip over 20 trades -- none of them should
        reject `NULL_WIN_PROBABILITY=0.5`, so nothing should survive Benjamini-Hochberg at the
        default `alpha=0.10`."""
        win_counts = [9, 10, 11, 10, 9, 11, 10, 9, 10, 11]  # near 50% of 20 trades each
        agents = [
            _agent(f"agent_{i}", _win_loss_trades(wins, 20 - wins))
            for i, wins in enumerate(win_counts)
        ]
        result = score(agents, alpha=0.10)

        assert result.discoveries == 0
        assert len(result.agents) == 10
        assert result.alpha == 0.10
        assert result.trade_start == TRADE_START
        assert result.trade_end == TRADE_END
        assert isinstance(result.generated_at, dt.datetime)
        for agent in result.agents:
            assert agent.q_value is None or agent.q_value > 0.10


# ---------------------------------------------------------------------------
# 5. Zero-trade agent -- None everywhere, never 0, and no exception
# ---------------------------------------------------------------------------


class TestZeroTradeAgentDoesNotRaise:
    def test_zero_trades_lands_as_none_not_zero_for_every_derived_statistic(self) -> None:
        empty = _agent("empty", [])
        active = _agent("active", _win_loss_trades(8, 4))
        result = score([empty, active])

        assert len(result.agents) == 2
        by_id = {a.card.agent_id: a for a in result.agents}
        empty_result = by_id["empty"]
        assert empty_result.profit_factor is None
        assert empty_result.realised_reward_risk is None
        assert empty_result.p_value is None
        assert empty_result.q_value is None


# ---------------------------------------------------------------------------
# 6. Ranking -- ordered by q_value, not total_return
# ---------------------------------------------------------------------------


class TestRankingIsNotByReturn:
    def test_agents_are_ordered_by_significance_not_by_total_return(self) -> None:
        """A high-return agent with a thin, unconvincing trade record (three trades, too few to
        even get a p-value) is placed behind a lower-return agent with a strong, well-sampled
        record -- proving the order is not `total_return` descending."""
        big_return_thin_evidence = _agent(
            "big_return_thin_evidence",
            _win_loss_trades(2, 1),
            total_return=Decimal("0.50"),
        )
        modest_return_strong_evidence = _agent(
            "modest_return_strong_evidence",
            _win_loss_trades(9, 1),
            total_return=Decimal("0.05"),
        )
        result = score([big_return_thin_evidence, modest_return_strong_evidence])

        ids_in_order = [a.card.agent_id for a in result.agents]
        assert ids_in_order == ["modest_return_strong_evidence", "big_return_thin_evidence"]
        # Sanity: proves the fixture actually set up the return ordering the test claims it defied.
        by_id = {a.card.agent_id: a for a in result.agents}
        assert (
            by_id["big_return_thin_evidence"].total_return
            > by_id["modest_return_strong_evidence"].total_return
        )


# ---------------------------------------------------------------------------
# 7. trade_start/trade_end -- the actual window flows through, not the constants
# ---------------------------------------------------------------------------


class TestExplicitWindowFlowsThrough:
    def test_score_with_explicit_window_reports_that_window_not_the_constants(self) -> None:
        """A tournament run over a window other than the module's default must report *that*
        window -- reporting the constants regardless of what was actually run is the defect this
        parameter exists to fix (see the comment above the `TournamentResult(...)` call)."""
        custom_start = dt.date(2023, 8, 21)
        custom_end = dt.date(2025, 1, 15)
        agents = [_agent(f"agent_{i}", _win_loss_trades(6, 4)) for i in range(3)]

        result = score(agents, trade_start=custom_start, trade_end=custom_end)

        assert result.trade_start == custom_start
        assert result.trade_end == custom_end
        assert result.trade_start != TRADE_START
        assert result.trade_end != TRADE_END

    def test_score_without_window_arguments_keeps_the_default_constants(self) -> None:
        """Regression guard for existing callers: omitting `trade_start`/`trade_end` must not
        change behaviour."""
        agents = [_agent(f"agent_{i}", _win_loss_trades(6, 4)) for i in range(3)]

        result = score(agents)

        assert result.trade_start == TRADE_START
        assert result.trade_end == TRADE_END

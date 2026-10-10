"""Every fact in the bundle carries the date of the thing it describes -- or, honestly, none.

`app.report.builder._fact` has always accepted an `as_of` parameter; until now no call site passed
it, so `Fact.as_of` was `None` on all 39 facts regardless of whether the underlying engine actually
knew a date. See `uat/feedback/BACKLOG.md` R13.

The properties under test are not "some as_of is set somewhere" -- that would pass even if every
fact were stamped with the same wrong date. They pin the *grouping*: a price-derived fact carries
the bar (or quote) date it was computed from, a fact tied to a specific historical event carries
that event's date rather than the window's last bar, and a fact with no observation date anywhere
in the builder's inputs -- an instrument's identity, a rule's own parameters -- stays `None` rather
than being defaulted to today or to the window.
"""

from __future__ import annotations

import datetime as dt

from app.backtest.models import (
    Costs,
    DrawdownBasis,
    DrawdownEpisode,
    DrawdownProfile,
    GuardReport,
    GuardStatus,
    StrategyMetrics,
    StrategyResult,
    StrategySpec,
)
from app.db.duck import Interval
from app.market.models import Profile, Quote
from app.report.builder import build_bundle
from app.rules.models import (
    DecisionRow,
    DecisionTable,
    Entry,
    Evidence,
    Rule,
    RuleState,
    Significance,
    TriState,
)


def _drawdown_profile(
    *, live_episode: bool = False, symbol: str = "TEST"
) -> DrawdownProfile:
    if live_episode:
        episode = DrawdownEpisode(
            peak_date=dt.date(2020, 3, 1),
            peak_value=120.0,
            trough_date=dt.date(2020, 6, 1),
            trough_value=60.0,
            depth=-0.5,
            bars_to_trough=60,
            bars_underwater=170,
            still_underwater=True,
            depth_now=-0.05,
            last_value=114.0,
            last_value_date=dt.date(2020, 10, 26),
        )
        current = episode
    else:
        episode = DrawdownEpisode(
            peak_date=dt.date(2020, 3, 1),
            peak_value=120.0,
            trough_date=dt.date(2020, 6, 1),
            trough_value=60.0,
            depth=-0.5,
            bars_to_trough=60,
            recovery_date=dt.date(2021, 1, 4),
            bars_to_recovery=210,
            bars_underwater=210,
            still_underwater=False,
        )
        current = None
    return DrawdownProfile(
        symbol=symbol,
        interval=Interval.DAY,
        basis=DrawdownBasis.CLOSE,
        generated_at=dt.datetime.now(dt.UTC),
        bars=300,
        first_bar=dt.date(2020, 1, 1),
        last_bar=dt.date(2020, 10, 26),
        episodes=[episode],
        episodes_considered=4,
        current=current,
    )


def _decision_table(symbol: str = "TEST") -> DecisionTable:
    rule = Rule(rule_id="above_sma20", name="Above SMA20", expression="close > sma(20)")
    evidence = Evidence(
        horizon=20,
        entry=Entry.NEXT_OPEN,
        hit_rate=0.62,
        baseline_hit_rate=0.51,
        median_return=0.01,
        baseline_median_return=0.004,
        sample_size=40,
        independent_sample_size=6,
        significance=Significance.SUGGESTIVE,
    )
    row = DecisionRow(
        rule=rule,
        state=RuleState(state=TriState.TRUE, as_of=dt.date(2020, 10, 26)),
        evidence=[evidence],
    )
    return DecisionTable(
        symbol=symbol,
        interval=Interval.DAY,
        generated_at=dt.datetime.now(dt.UTC),
        bars_evaluated=300,
        first_bar=dt.date(2020, 1, 1),
        last_bar=dt.date(2020, 10, 26),
        rows=[row],
    )


def _strategy_result(symbol: str = "TEST") -> StrategyResult:
    return StrategyResult(
        symbol=symbol,
        interval=Interval.DAY,
        generated_at=dt.datetime.now(dt.UTC),
        spec=StrategySpec(entry="close > sma(20)", max_holding_bars=10),
        costs=Costs(),
        guard=GuardReport(status=GuardStatus.PASSED, expression="close > sma(20)"),
        metrics=StrategyMetrics(
            total_return=0.12,
            cagr=0.08,
            max_drawdown=-0.15,
            exposure=0.4,
            sharpe=0.9,
            win_rate=0.55,
            trades=10,
        ),
        buy_hold=StrategyMetrics(total_return=0.20, cagr=0.10, max_drawdown=-0.30),
        cost_drag=-0.01,
        bars=300,
        first_bar=dt.date(2020, 1, 1),
        last_bar=dt.date(2020, 10, 26),
    )


class TestPriceDerivedFactsCarryTheirBarDate:
    """The headline case: a figure computed from a specific observation is dated to it."""

    def test_quote_price_is_dated_to_the_quote_timestamp(self) -> None:
        quote = Quote(
            symbol="TEST",
            price=101.5,
            ts=dt.datetime(2020, 10, 26, 20, 0, tzinfo=dt.UTC),
            change_pct=1.2,
        )
        bundle = build_bundle("TEST", Interval.DAY, quote=quote)
        assert bundle.facts["quote.price"].as_of == dt.date(2020, 10, 26)
        assert bundle.facts["quote.change_pct"].as_of == dt.date(2020, 10, 26)

    def test_strategy_metrics_are_dated_to_the_backtest_last_bar(self) -> None:
        bundle = build_bundle("TEST", Interval.DAY, strategy=_strategy_result())
        assert bundle.facts["strategy.total_return"].as_of == dt.date(2020, 10, 26)
        assert bundle.facts["strategy.max_drawdown"].as_of == dt.date(2020, 10, 26)
        assert bundle.facts["strategy.trades"].as_of == dt.date(2020, 10, 26)

    def test_drawdown_max_depth_is_dated_to_the_trough_not_the_window(self) -> None:
        """The depth was true at the trough; it stopped being true the moment price moved off it,
        so it must not carry the window's last bar as if it were still the current reading."""
        bundle = build_bundle("TEST", Interval.DAY, drawdown=_drawdown_profile())
        fact = bundle.facts["drawdown.max_depth"]
        assert fact.as_of == dt.date(2020, 6, 1)  # the episode's trough_date
        assert fact.as_of != dt.date(2020, 10, 26)  # not the profile's last_bar

    def test_current_depth_and_current_episode_worst_carry_different_dates(self) -> None:
        """These two facts were the site of the original bug this codebase already fixed once --
        conflating "worst point of the episode" with "the live gap right now". The same distinction
        must hold for their as_of: one is dated to today's print, the other to when the episode's
        low actually happened."""
        bundle = build_bundle(
            "TEST", Interval.DAY, drawdown=_drawdown_profile(live_episode=True)
        )
        current_depth = bundle.facts["drawdown.current_depth"]
        current_worst = bundle.facts["drawdown.current_episode_worst"]
        assert current_depth.as_of == dt.date(2020, 10, 26)  # last_value_date
        assert current_worst.as_of == dt.date(2020, 6, 1)  # the live episode's trough_date
        assert current_depth.as_of != current_worst.as_of

    def test_rule_evidence_is_dated_to_the_table_last_bar(self) -> None:
        bundle = build_bundle("TEST", Interval.DAY, decisions=_decision_table())
        assert bundle.facts["rules.best_edge"].as_of == dt.date(2020, 10, 26)
        assert bundle.facts["rules.total"].as_of == dt.date(2020, 10, 26)

    def test_sample_bars_is_dated_to_the_last_bar(self) -> None:
        bundle = build_bundle(
            "TEST",
            Interval.DAY,
            bars=300,
            first_bar=dt.date(2020, 1, 1),
            last_bar=dt.date(2020, 10, 26),
        )
        assert bundle.facts["sample.bars"].as_of == dt.date(2020, 10, 26)


class TestFactsWithNoObservationDateStayNone:
    """A fact whose builder inputs carry no date must not be given a fabricated one -- a single
    `as_of=today` on every fact would assert provenance that is false."""

    def test_instrument_identity_has_no_as_of(self) -> None:
        """Profile carries no fetch timestamp in the builder's inputs (unlike Coverage.fetched_at,
        which is not threaded into build_bundle), so there is nothing honest to date it with."""
        profile = Profile(symbol="TEST", name="Test Corp", exchange="NASDAQ", currency="USD")
        bundle = build_bundle("TEST", Interval.DAY, profile=profile)
        assert bundle.facts["instrument.name"].as_of is None
        assert bundle.facts["instrument.exchange"].as_of is None
        assert bundle.facts["instrument.currency"].as_of is None

    def test_rule_parameters_have_no_as_of(self) -> None:
        """The rule's name, expression, and horizon are parameters of the rule definition -- they
        do not change with the calendar, only with the rule itself."""
        bundle = build_bundle("TEST", Interval.DAY, decisions=_decision_table())
        assert bundle.facts["rules.best_rule"].as_of is None
        assert bundle.facts["rules.best_expression"].as_of is None
        assert bundle.facts["rules.best_horizon"].as_of is None

    def test_strategy_entry_rule_has_no_as_of(self) -> None:
        bundle = build_bundle("TEST", Interval.DAY, strategy=_strategy_result())
        assert bundle.facts["strategy.entry"].as_of is None

    def test_date_valued_facts_do_not_restate_themselves_as_as_of(self) -> None:
        """`sample.first_bar`'s value already is the date; giving it an as_of would only repeat the
        same string in two different types."""
        bundle = build_bundle(
            "TEST",
            Interval.DAY,
            bars=300,
            first_bar=dt.date(2020, 1, 1),
            last_bar=dt.date(2020, 10, 26),
            drawdown=_drawdown_profile(),
        )
        assert bundle.facts["sample.first_bar"].as_of is None
        assert bundle.facts["sample.last_bar"].as_of is None
        assert bundle.facts["drawdown.peak_date"].as_of is None
        assert bundle.facts["drawdown.trough_date"].as_of is None


class TestUnderwaterFactsFollowRecoveryState:
    """`bars_underwater`/`still_underwater` are final once an episode recovers, and still moving
    every session while it stays open -- the as_of must track which is true."""

    def test_recovered_episode_is_dated_to_its_recovery(self) -> None:
        bundle = build_bundle("TEST", Interval.DAY, drawdown=_drawdown_profile(live_episode=False))
        assert bundle.facts["drawdown.still_underwater"].as_of == dt.date(2021, 1, 4)
        assert bundle.facts["drawdown.bars_underwater"].as_of == dt.date(2021, 1, 4)
        assert bundle.facts["drawdown.bars_to_recovery"].as_of == dt.date(2021, 1, 4)

    def test_live_episode_is_dated_to_the_window_last_bar(self) -> None:
        bundle = build_bundle("TEST", Interval.DAY, drawdown=_drawdown_profile(live_episode=True))
        assert bundle.facts["drawdown.still_underwater"].as_of == dt.date(2020, 10, 26)
        assert bundle.facts["drawdown.bars_underwater"].as_of == dt.date(2020, 10, 26)
        assert "drawdown.bars_to_recovery" not in bundle.facts

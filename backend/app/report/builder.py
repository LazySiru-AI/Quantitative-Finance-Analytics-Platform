"""Assembles the fact bundle: every figure a report is allowed to say, with its provenance.

This module computes nothing. It calls the Phase 4-7 engines and transcribes their output into
:class:`~app.report.models.Fact` objects, because a report that recomputed a statistic would be a
second implementation of it -- and two implementations of the same number is the seam
:mod:`app.backtest.forward` exists to have removed. If a figure is not available from an engine, it
is not in the bundle, and therefore cannot appear in the prose.

**The bundle is the report's entire vocabulary of numbers.** That is what makes a missing engine
visible: when the drawdown study fails, the drawdown facts are absent, the drawdown sentence fails
to build, and the section says so. The alternative -- prose that reads the same whether or not the
data arrived -- is the failure this whole arrangement is arranged against.

**Every fact carries a source string naming the engine and the window.** Not decoration: a reader
who doubts a number has to be able to find out where it came from without reading the code, and a
figure whose origin cannot be stated is one nobody should have put in a report.

**Parameters are facts too.** The ``50`` in a 50/200 crossover is emitted as
``rules.best_rule`` text rather than left for the prose to type, because
:mod:`app.report.narrative` refuses bare numerals and that refusal is only tenable if the builder
supplies everything the prose legitimately needs. The strictness pushes the decision about what a
report may claim into this file, in advance, which is where it belongs.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from app.backtest.models import (
    DrawdownBasis,
    DrawdownProfile,
    StrategyResult,
)
from app.db.duck import Interval
from app.market.models import MarketWarning, Profile, Quote
from app.market.news_models import TickerNewsPanel
from app.report.models import Fact, FactBundle, FactKind
from app.report.news_facts import news_facts
from app.rules.models import DecisionTable, Significance

__all__ = ["build_bundle"]


def _fact(
    fact_id: str,
    label: str,
    value: float | str | None,
    kind: FactKind,
    source: str,
    *,
    unit: str = "",
    as_of: dt.date | None = None,
) -> Fact:
    return Fact(
        id=fact_id, label=label, value=value, kind=kind, unit=unit, source=source, as_of=as_of
    )


def _window(symbol: str, interval: Interval, first: dt.date | None, last: dt.date | None) -> str:
    span = f"{first}..{last}" if first and last else "no bars"
    return f"{symbol} {interval.value} {span}"


def _instrument_facts(
    symbol: str, profile: Profile | None, quote: Quote | None
) -> list[Fact]:
    facts = [
        _fact("instrument.symbol", "Symbol", symbol, FactKind.TEXT, "store/symbol"),
    ]
    if profile is not None:
        source = f"market_profile/{profile.source.value}"
        facts.append(
            # Falls back to the symbol rather than to None: the overview sentence needs a name, and
            # "SOXL (SOXL) is covered here" is a worse sentence than a missing one but a far better
            # outcome than a report that silently drops its own first line for a symbol whose
            # provider had no long name.
            _fact("instrument.name", "Name", profile.name or symbol, FactKind.TEXT, source)
        )
        if profile.exchange:
            facts.append(_fact("instrument.exchange", "Exchange", profile.exchange, FactKind.TEXT, source))
        if profile.instrument_type:
            facts.append(
                _fact("instrument.type", "Type", profile.instrument_type, FactKind.TEXT, source)
            )
        facts.append(_fact("instrument.currency", "Currency", profile.currency, FactKind.TEXT, source))
    else:
        facts.append(_fact("instrument.name", "Name", symbol, FactKind.TEXT, "store/symbol"))

    # `profile` carries identity attributes -- name, exchange, currency -- with no fetch timestamp
    # of its own in this module's inputs (unlike `Coverage.fetched_at`, which is not threaded into
    # the builder). There is nothing honest to date them with, so `instrument.*` facts above keep
    # as_of=None rather than being stamped with an unrelated date. `quote`, by contrast, carries its
    # own timestamp -- it is a snapshot, not an identity -- so its facts are dated to it.
    if quote is not None and quote.price is not None:
        quote_date = quote.ts.date()
        facts.append(
            _fact(
                "quote.price",
                "Last price",
                quote.price,
                FactKind.CURRENCY,
                "market_quote/yahoo",
                as_of=quote_date,
            )
        )
        if quote.change_pct is not None:
            facts.append(
                _fact(
                    "quote.change_pct",
                    "Change",
                    quote.change_pct / 100.0,
                    FactKind.SIGNED_PERCENT,
                    "market_quote/yahoo",
                    as_of=quote_date,
                )
            )
    return facts


def _drawdown_facts(profile: DrawdownProfile) -> list[Fact]:
    source = f"drawdown/{profile.basis.value}/{_window(profile.symbol, profile.interval, profile.first_bar, profile.last_bar)}"
    # `basis` and `episodes` describe the whole study rather than a single excursion -- there is no
    # finer date than "computed over bars through the last one the store held", so both are dated to
    # `profile.last_bar` rather than left bare or given a per-episode date they don't carry.
    facts = [
        _fact(
            "drawdown.basis",
            "Drawdown basis",
            profile.basis.value.replace("_", " "),
            FactKind.TEXT,
            source,
            as_of=profile.last_bar,
        ),
        _fact(
            "drawdown.episodes",
            "Drawdown episodes",
            profile.episodes_considered,
            FactKind.COUNT,
            source,
            as_of=profile.last_bar,
        ),
    ]
    if not profile.episodes:
        return facts

    deepest = profile.episodes[0]
    # Every label below says *deepest episode*, and that is not verbosity. These describe the single
    # worst decline in the whole history; `drawdown.current_*` below describes today. Rendered in one
    # flat table they sat two rows apart, and a UAT persona read "Still underwater: no" beside
    # "Current drawdown: -15.6%" on a position they held. Both were true -- of different episodes --
    # and nothing on the page said which was which, so the page contradicted itself in front of
    # someone deciding whether to add to the name. A fact whose label does not say what it is about
    # is worse here than a fact that is missing, because the reader has no reason to go looking.
    # `bars_underwater`/`still_underwater` are fixed once an episode recovers -- dated to
    # `recovery_date`, the last day either quantity could still change -- and keep moving every
    # session while the episode is live, so a still-open episode is dated to the window's last bar
    # instead. Using the same rule twice (here and on `current_depth` below) is deliberate: the same
    # question -- "as of when is this count final" -- has the same answer both times.
    underwater_as_of = profile.last_bar if deepest.still_underwater else deepest.recovery_date
    facts += [
        _fact(
            "drawdown.max_depth",
            "Deepest drawdown",
            deepest.depth,
            FactKind.PERCENT,
            source,
            # The peak-to-trough depth is a fact about the trough: it stopped being true the moment
            # the price moved off that low, so it is dated there rather than to `profile.last_bar`.
            as_of=deepest.trough_date,
        ),
        # `peak_date`/`trough_date` are themselves dates -- stamping an as_of on a date-valued fact
        # would only restate its own value, so these two keep as_of=None.
        _fact("drawdown.peak_date", "Deepest episode peak", deepest.peak_date.isoformat(), FactKind.DATE, source),
        _fact("drawdown.trough_date", "Deepest episode trough", deepest.trough_date.isoformat(), FactKind.DATE, source),
        _fact(
            "drawdown.bars_to_trough",
            "Deepest episode bars to trough",
            deepest.bars_to_trough,
            FactKind.COUNT,
            source,
            as_of=deepest.trough_date,
        ),
        # A boolean rendered as a token rather than as True/False: it is cited by prose, and
        # "the decline has not recovered (True)" is not a sentence.
        _fact(
            "drawdown.still_underwater",
            "Deepest episode still underwater",
            "yes" if deepest.still_underwater else "no",
            FactKind.TEXT,
            source,
            as_of=underwater_as_of,
        ),
        _fact(
            "drawdown.bars_underwater",
            "Deepest episode bars underwater",
            deepest.bars_underwater,
            FactKind.COUNT,
            source,
            as_of=underwater_as_of,
        ),
    ]
    if deepest.bars_to_recovery is not None:
        facts.append(
            _fact(
                "drawdown.bars_to_recovery",
                "Deepest episode bars to recovery",
                deepest.bars_to_recovery,
                FactKind.COUNT,
                source,
                # Only emitted once recovered (see the guard above), so recovery_date is never None
                # here.
                as_of=deepest.recovery_date,
            )
        )
    if profile.current is not None:
        # `drawdown.current_depth` keeps its id -- a fact id is a citation key, and prose already
        # written against it must keep resolving -- but it now carries the figure its label always
        # promised: peak to the latest print, not peak to the ongoing episode's worst bar. On XLE it
        # read -15.6% against a live gap of -1.04%, and a UAT persona holding the name caught it by
        # checking the headline against the quote at the top of the same page.
        #
        # The worst point is still reported, under a label that says so. Both are worth having: one
        # answers "how much risk am I carrying now", the other "how bad has this episode been".
        current_depth = (
            profile.current.depth_now if profile.current.depth_now is not None else profile.current.depth
        )
        facts += [
            _fact(
                "drawdown.current_depth",
                "Current drawdown",
                current_depth,
                FactKind.PERCENT,
                source,
                # Same date the `current_depth_as_of` sibling fact below states in prose form -- the
                # latest valid print the gap was measured from.
                as_of=profile.current.last_value_date,
            ),
            _fact(
                "drawdown.current_episode_worst",
                "Current episode worst",
                profile.current.depth,
                FactKind.PERCENT,
                source,
                # The worst point *of the still-open episode*, dated to when it happened -- the
                # episode's own trough_date -- not to today, which `current_depth` above already
                # covers. Conflating the two dates is exactly the bug `current_depth`'s docstring
                # describes for the value itself.
                as_of=profile.current.trough_date,
            ),
            # A date-valued fact; see the `peak_date`/`trough_date` comment above.
            _fact(
                "drawdown.current_peak_date",
                "Current drawdown peak",
                profile.current.peak_date.isoformat(),
                FactKind.DATE,
                source,
            ),
        ]
        if profile.current.last_value_date is not None:
            # Every figure carries an as-of. Normally the series' last bar; different only when the
            # final prints are missing, which is exactly when a reader needs to be told.
            facts.append(
                _fact(
                    "drawdown.current_depth_as_of",
                    "Current drawdown as of",
                    profile.current.last_value_date.isoformat(),
                    FactKind.DATE,
                    source,
                )
            )
    return facts


def _rule_facts(table: DecisionTable) -> list[Fact]:
    source = f"decision_table/{_window(table.symbol, table.interval, table.first_bar, table.last_bar)}"
    firing = sum(1 for row in table.rows if row.state.state.value == "true")
    # Evidence here is pooled across the whole sample rather than tied to one trigger date, so the
    # finest-grained honest as_of any of these counts and statistics can carry is the window's last
    # bar -- the date through which the table was computed.
    facts = [
        _fact("rules.total", "Rules evaluated", len(table.rows), FactKind.COUNT, source, as_of=table.last_bar),
        _fact("rules.firing", "Rules firing", firing, FactKind.COUNT, source, as_of=table.last_bar),
    ]

    # "All insufficient" is emitted as a fact so the narrative can state it. It is one of the more
    # important sentences the report can produce and it is a *negative* result -- which is exactly
    # the kind a system that only models positive findings would have no way to say.
    evaluated = [e for row in table.rows for e in row.evidence]
    if evaluated:
        all_insufficient = all(e.significance is Significance.INSUFFICIENT for e in evaluated)
        facts.append(
            _fact(
                "rules.all_insufficient",
                "All rules insufficient",
                "yes" if all_insufficient else "no",
                FactKind.TEXT,
                source,
                as_of=table.last_bar,
            )
        )

    # Selected by magnitude, which systematically favours the smallest sample -- see
    # `narrative.draft_evidence`'s docstring. The significance verdict is emitted alongside so the
    # sentence that cites the edge is forced to cite what the project actually thinks of it.
    best_row = None
    best_evidence = None
    for row in table.rows:
        for evidence in row.evidence:
            if evidence.edge is None:
                continue
            if best_evidence is None or abs(evidence.edge) > abs(best_evidence.edge or 0.0):
                best_row, best_evidence = row, evidence

    if best_row is not None and best_evidence is not None and best_evidence.edge is not None:
        facts += [
            # `best_rule`, `best_expression`, `best_horizon` name the rule and the horizon it was
            # measured over -- parameters of the rule definition, not observations. They don't
            # change with the calendar, only with the rule itself, so they carry no as_of.
            _fact("rules.best_rule", "Rule with the largest edge", best_row.rule.name, FactKind.TEXT, source),
            _fact("rules.best_expression", "Expression", best_row.rule.expression, FactKind.TEXT, source),
            _fact("rules.best_horizon", "Horizon (bars)", best_evidence.horizon, FactKind.COUNT, source),
            _fact(
                "rules.best_edge",
                "Hit rate vs baseline",
                best_evidence.edge,
                FactKind.SIGNED_PERCENT,
                source,
                as_of=table.last_bar,
            ),
            _fact(
                "rules.best_independent_n",
                "Independent observations",
                best_evidence.independent_sample_size,
                FactKind.COUNT,
                source,
                as_of=table.last_bar,
            ),
            _fact(
                "rules.best_significance",
                "Evidence grade",
                # The enum's own token, spelled for prose. `INSUFFICIENT` reads as a verdict rather
                # than as a missing value, which is what it is.
                best_evidence.significance.value,
                FactKind.TEXT,
                source,
                as_of=table.last_bar,
            ),
        ]
        if best_evidence.baseline_hit_rate is not None:
            facts.append(
                _fact(
                    "rules.best_baseline",
                    "Baseline hit rate",
                    best_evidence.baseline_hit_rate,
                    FactKind.PERCENT,
                    source,
                    as_of=table.last_bar,
                )
            )
    return facts


def _strategy_facts(result: StrategyResult) -> list[Fact]:
    source = f"strategy/{_window(result.symbol, result.interval, result.first_bar, result.last_bar)}"
    facts = [
        # A parameter -- the DSL text of the entry rule -- not a measurement, so no as_of.
        _fact("strategy.entry", "Entry rule", result.spec.entry, FactKind.TEXT, source),
        _fact(
            "strategy.trades", "Trades opened", result.metrics.trades, FactKind.COUNT, source,
            as_of=result.last_bar,
        ),
    ]
    pairs: Sequence[tuple[str, str, float | None, FactKind]] = (
        ("strategy.total_return", "Strategy return", result.metrics.total_return, FactKind.SIGNED_PERCENT),
        ("strategy.cagr", "Strategy CAGR", result.metrics.cagr, FactKind.SIGNED_PERCENT),
        ("strategy.max_drawdown", "Strategy max drawdown", result.metrics.max_drawdown, FactKind.PERCENT),
        ("strategy.exposure", "Time in market", result.metrics.exposure, FactKind.PERCENT),
        ("strategy.sharpe", "Sharpe", result.metrics.sharpe, FactKind.RATIO),
        ("strategy.win_rate", "Win rate (closed trades)", result.metrics.win_rate, FactKind.PERCENT),
        # Buy-and-hold is emitted with the same kinds so the two can be shown side by side without
        # the prose or the UI having to know they are comparable -- they are comparable because they
        # were computed over the identical window by the same code.
        ("buy_hold.total_return", "Buy-and-hold return", result.buy_hold.total_return, FactKind.SIGNED_PERCENT),
        ("buy_hold.cagr", "Buy-and-hold CAGR", result.buy_hold.cagr, FactKind.SIGNED_PERCENT),
        ("buy_hold.max_drawdown", "Buy-and-hold max drawdown", result.buy_hold.max_drawdown, FactKind.PERCENT),
        ("strategy.cost_drag", "Cost drag", result.cost_drag, FactKind.SIGNED_PERCENT),
    )
    # Every one of these is a summary statistic over the equity curve as a whole -- `max_drawdown`,
    # for instance, carries no trough date of its own the way `DrawdownProfile`'s episodes do -- so
    # `result.last_bar`, the date the whole backtest is computed through, is the finest honest as_of
    # available for any of them.
    for fact_id, label, value, kind in pairs:
        if value is not None:
            facts.append(_fact(fact_id, label, value, kind, source, as_of=result.last_bar))

    if result.metrics.total_return is not None and result.buy_hold.total_return is not None:
        facts.append(
            _fact(
                "strategy.excess_return",
                "Excess over buy-and-hold",
                result.metrics.total_return - result.buy_hold.total_return,
                FactKind.SIGNED_PERCENT,
                source,
                as_of=result.last_bar,
            )
        )
    return facts


def build_bundle(
    symbol: str,
    interval: Interval,
    *,
    profile: Profile | None = None,
    quote: Quote | None = None,
    drawdown: DrawdownProfile | None = None,
    decisions: DecisionTable | None = None,
    strategy: StrategyResult | None = None,
    news: TickerNewsPanel | None = None,
    bars: int = 0,
    first_bar: dt.date | None = None,
    last_bar: dt.date | None = None,
    warnings: Sequence[MarketWarning] | None = None,
) -> FactBundle:
    """Transcribe every engine's output into one bundle of citable facts.

    Each engine is optional. A missing one contributes no facts, which is what makes its absence
    visible downstream: the sentences that would have cited it do not build, and the section reports
    that rather than rendering prose that reads identically either way.
    """
    upper = symbol.upper()
    sample_source = _window(upper, interval, first_bar, last_bar)

    # "Sessions" is only true on daily bars. A report built at `1h` counted hourly bars and labelled
    # them sessions, so 3,400 bars of history read as 3,400 trading days rather than roughly 485 --
    # a seven-fold overstatement of the sample behind every statistic below it, on the one figure a
    # reader uses to decide whether to believe the rest.
    unit_label = "Sessions" if interval is Interval.DAY else f"{interval.value} bars"
    edge_label = "session" if interval is Interval.DAY else "bar"

    facts: list[Fact] = [
        # A count of bars through `last_bar` -- the same rule as everywhere else in this module: no
        # per-bar date exists for a whole-sample count, so it is dated to the window's last bar.
        _fact("sample.bars", unit_label, bars, FactKind.COUNT, f"store/{sample_source}", as_of=last_bar),
    ]
    if first_bar is not None:
        facts.append(
            # The value is itself the date, so an as_of would only restate it -- see the same
            # reasoning for `drawdown.peak_date`/`drawdown.trough_date` above.
            _fact(
                "sample.first_bar",
                f"First {edge_label}",
                first_bar.isoformat(),
                FactKind.DATE,
                f"store/{sample_source}",
            )
        )
    if last_bar is not None:
        facts.append(
            _fact(
                "sample.last_bar",
                f"Last {edge_label}",
                last_bar.isoformat(),
                FactKind.DATE,
                f"store/{sample_source}",
            )
        )

    facts += _instrument_facts(upper, profile, quote)
    if drawdown is not None:
        facts += _drawdown_facts(drawdown)
    if decisions is not None:
        facts += _rule_facts(decisions)
    if strategy is not None:
        facts += _strategy_facts(strategy)
    if news is not None:
        # `news_facts` returns every id it knows, with `value=None` for the ones it could not
        # measure, rather than omitting them -- which is why this merges the whole mapping instead
        # of filtering it. An absent fact and a `None`-valued fact produce very different reports:
        # `narrative._sentence` drops a sentence whose required facts are missing, so omission reads
        # as though the question was never asked, while `None` renders as an em dash and says
        # plainly that it could not be measured. See `app.report.news_facts`'s module docstring.
        facts += list(news_facts(news).values())

    # Later entries win on a duplicate id. Not expected -- the id namespaces are disjoint by prefix --
    # but a dict comprehension silently dropping one would be a fact vanishing from a report, so the
    # collision is made explicit as a warning rather than left to be noticed by its absence.
    collected: dict[str, Fact] = {}
    collisions: list[str] = []
    for fact in facts:
        if fact.id in collected:
            collisions.append(fact.id)
        collected[fact.id] = fact

    bundle_warnings = list(warnings or [])
    if collisions:
        bundle_warnings.append(
            MarketWarning(
                kind="fact_collision",
                message=(
                    f"{upper}: duplicate fact id(s) {sorted(set(collisions))}; the later value won "
                    "and the earlier one is not citable"
                ),
            )
        )

    return FactBundle(
        symbol=upper,
        interval=interval,
        generated_at=dt.datetime.now(dt.UTC),
        facts=collected,
        warnings=bundle_warnings,
    )


#: Basis the report's drawdown section is built on when the caller does not choose.
#:
#: Close, matching the most commonly quoted convention. Named here rather than defaulted inline
#: because the number changes materially with the basis -- 90.5% against 91.6% on SOXL -- and a
#: default that lives in three places drifts.
DEFAULT_REPORT_BASIS: DrawdownBasis = DrawdownBasis.CLOSE

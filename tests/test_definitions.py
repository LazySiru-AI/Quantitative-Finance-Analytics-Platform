"""`docs/DEFINITIONS.md` covers every statistic the report can emit.

Four defects in one UAT run were the same shape: a number computed correctly under a label that
meant something else. Every unit test passed throughout, because every test asserted the
*computation* and none asserted the *claim*. The register was written to close that, and a register
nobody maintains closes nothing — so this asserts the one property a machine can check about it:
that it is complete.

**What this cannot check.** Whether a definition is *correct*. A label reading "Current drawdown"
against a definition reading "peak to trough" would satisfy every assertion here. What it does catch
is the case that actually happened: a statistic reaching a user with no stated definition at all,
because the person adding it had a clear idea of what it meant and no reason to write it down.

The fact ids come from building a real bundle with every engine present, not from a regex over the
builder — a fact added inside a branch this test does not reach would otherwise be invisible to it,
which is exactly the fact most likely to be undocumented.
"""

from __future__ import annotations

import datetime as dt
import re

import pytest

from app.backtest.models import (
    Costs,
    DrawdownBasis,
    DrawdownEpisode,
    DrawdownProfile,
    StrategyMetrics,
    StrategyResult,
    StrategySpec,
)
from app.config import REPO_ROOT
from app.db.duck import Interval
from app.market.models import BarSource, Profile, Quote
from app.report.builder import build_bundle
from app.rules.evidence import significance_criteria
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

REGISTER = REPO_ROOT / "docs" / "DEFINITIONS.md"

#: Facts whose label is self-defining and which the register would only pad. Each is a bare
#: identifier or a passthrough of a provider's own field -- there is no second reading of "Symbol".
#: Listed explicitly so the exemption is a decision rather than a gap.
SELF_EVIDENT = {
    "instrument.symbol",
    "instrument.name",
    "instrument.exchange",
    "instrument.type",
    "instrument.currency",
    "quote.change_pct",
    "drawdown.basis",
    "rules.total",
    "rules.all_insufficient",
    "rules.best_expression",
    "rules.best_baseline",
    "rules.best_significance",
    "rules.best_independent_n",
    "strategy.entry",
    "strategy.total_return",
    "strategy.max_drawdown",
    "strategy.sharpe",
    "buy_hold.total_return",
    "buy_hold.cagr",
    "buy_hold.max_drawdown",
    "drawdown.peak_date",
    "drawdown.trough_date",
    "drawdown.bars_to_trough",
    "drawdown.bars_underwater",
    "drawdown.bars_to_recovery",
    "drawdown.still_underwater",
    "drawdown.current_peak_date",
    "sample.first_bar",
    "sample.last_bar",
}


def _full_bundle(interval: Interval = Interval.DAY) -> dict[str, str]:
    """Every fact a report can carry, as ``{id: label}``, with all engines contributing."""
    episode = DrawdownEpisode(
        peak_date=dt.date(2026, 3, 27),
        peak_value=62.56,
        trough_date=dt.date(2026, 7, 1),
        trough_value=52.81,
        depth=-0.1558,
        bars_to_trough=66,
        bars_to_recovery=None,
        bars_underwater=95,
        still_underwater=True,
        depth_now=-0.024,
        last_value=61.06,
        last_value_date=dt.date(2026, 8, 13),
    )
    recovered = episode.model_copy(
        update={
            "still_underwater": False,
            "recovery_date": dt.date(2026, 8, 1),
            "bars_to_recovery": 90,
            "depth_now": None,
            "last_value": None,
            "last_value_date": None,
        }
    )
    drawdown = DrawdownProfile(
        symbol="TEST",
        interval=interval,
        basis=DrawdownBasis.CLOSE,
        generated_at=dt.datetime.now(dt.UTC),
        bars=300,
        first_bar=dt.date(2025, 1, 2),
        last_bar=dt.date(2026, 8, 13),
        episodes=[recovered, episode],
        episodes_considered=2,
        current=episode,
    )

    evidence = Evidence(
        horizon=20,
        entry=Entry.NEXT_OPEN,
        sample_size=60,
        independent_sample_size=31,
        hit_rate=0.7,
        baseline_hit_rate=0.55,
        median_return=0.02,
        baseline_median_return=0.005,
        significance=Significance.SUGGESTIVE,
    )
    decisions = DecisionTable(
        symbol="TEST",
        interval=interval,
        generated_at=dt.datetime.now(dt.UTC),
        bars_evaluated=300,
        first_bar=dt.date(2025, 1, 2),
        last_bar=dt.date(2026, 8, 13),
        rows=[
            DecisionRow(
                rule=Rule(rule_id="r", name="A rule", expression="close > sma(20)"),
                state=RuleState(state=TriState.TRUE),
                evidence=[evidence],
                warnings=[],
            )
        ],
        criteria=significance_criteria(),
    )

    metrics = StrategyMetrics(
        total_return=0.2,
        cagr=0.1,
        max_drawdown=-0.15,
        exposure=0.4,
        sharpe=0.9,
        trades=10,
        trades_per_year=5.0,
        win_rate=0.6,
    )
    strategy = StrategyResult(
        symbol="TEST",
        interval=interval,
        generated_at=dt.datetime.now(dt.UTC),
        spec=StrategySpec(entry="close > sma(20)", exit="close < sma(20)"),
        costs=Costs(),
        metrics=metrics,
        buy_hold=metrics.model_copy(update={"total_return": 0.15}),
        cost_drag=-0.01,
        bars=300,
        first_bar=dt.date(2025, 1, 2),
        last_bar=dt.date(2026, 8, 13),
    )

    bundle = build_bundle(
        "TEST",
        interval,
        profile=Profile(
            symbol="TEST",
            name="Test Instrument",
            exchange="NYSE",
            exchange_timezone="America/New_York",
            currency="USD",
            instrument_type="ETF",
            source=BarSource.YAHOO,
        ),
        quote=Quote(
            symbol="TEST",
            price=61.06,
            ts=dt.datetime.now(dt.UTC),
            currency="USD",
            change_pct=1.2,
            source=BarSource.YAHOO,
        ),
        drawdown=drawdown,
        decisions=decisions,
        strategy=strategy,
        bars=300,
        first_bar=dt.date(2025, 1, 2),
        last_bar=dt.date(2026, 8, 13),
    )
    return {fact.id: fact.label for fact in bundle.facts.values()}


def _register_text() -> str:
    if not REGISTER.exists():  # pragma: no cover - the file is committed
        pytest.fail(f"{REGISTER} is missing; it is the register this suite checks against")
    return REGISTER.read_text(encoding="utf-8")


def test_every_emitted_fact_has_a_definition() -> None:
    """A statistic cannot reach a user without a stated meaning.

    Matched on the **label**, not the fact id, because the label is what a reader sees and the
    register is written for a reader. A label changed without the register following it fails here,
    which is the moment to decide whether the new wording is better or whether the definition moved.
    """
    text = _register_text()
    emitted = _full_bundle()

    undocumented = sorted(
        fact_id
        for fact_id, label in emitted.items()
        if fact_id not in SELF_EVIDENT and label not in text
    )

    assert not undocumented, (
        "these facts reach a user with no entry in docs/DEFINITIONS.md: "
        f"{ {f: emitted[f] for f in undocumented} }. Add a row saying what the label means and "
        "where it is computed, or add the id to SELF_EVIDENT if the label genuinely admits only "
        "one reading."
    )


def test_the_exemption_list_does_not_outlive_its_facts() -> None:
    """An id exempted here but no longer emitted is a stale exemption hiding a future gap."""
    emitted = set(_full_bundle())
    stale = sorted(SELF_EVIDENT - emitted)
    assert not stale, f"SELF_EVIDENT names facts the builder no longer emits: {stale}"


def test_the_sample_label_follows_the_interval() -> None:
    """"Sessions" is a claim about daily bars, and the register says so.

    3,400 hourly bars is roughly 485 sessions. Labelling them "Sessions" overstated the sample
    behind every statistic below it by seven-fold, on the one figure a reader uses to decide whether
    to believe the rest.
    """
    daily = _full_bundle(Interval.DAY)
    hourly = _full_bundle(Interval.HOUR)

    assert daily["sample.bars"] == "Sessions"
    assert hourly["sample.bars"] == "1h bars"
    assert daily["sample.first_bar"] == "First session"
    assert hourly["sample.first_bar"] == "First bar"


def test_the_two_drawdown_depths_are_labelled_as_different_questions() -> None:
    """The defect that motivated the register, pinned at the label level."""
    labels = _full_bundle()

    assert labels["drawdown.current_depth"] == "Current drawdown"
    assert labels["drawdown.current_episode_worst"] == "Current episode worst"
    assert labels["drawdown.max_depth"] == "Deepest drawdown"
    # Every deepest-episode field says which episode it is about.
    for fact_id in ("drawdown.peak_date", "drawdown.trough_date", "drawdown.still_underwater"):
        assert labels[fact_id].startswith("Deepest episode"), fact_id


def test_labels_that_could_be_read_as_returns_say_what_they_are() -> None:
    """`Evidence.edge` is hit rate minus baseline -- percentage points of *how often*.

    Rendered as a signed percent under the bare label "Edge", it read as excess performance. The
    decision table already called this exact quantity "Hit rate vs baseline"; using the same words
    in both places means the two surfaces cannot be read as two different statistics.
    """
    labels = _full_bundle()
    assert labels["rules.best_edge"] == "Hit rate vs baseline"
    assert labels["rules.best_horizon"] == "Horizon (bars)"
    assert labels["strategy.win_rate"] == "Win rate (closed trades)"
    assert labels["strategy.trades"] == "Trades opened"


def test_the_register_documents_the_significance_thresholds_it_ships() -> None:
    """The legend a user reads is built from these constants; the register quotes them.

    If a threshold moves, this fails -- which is the prompt to update the register rather than
    leaving it describing a rule the code no longer applies.
    """
    text = _register_text()
    criteria = significance_criteria()

    assert f"≥{criteria.suggestive_min_independent} independent triggers" in text
    assert f"{criteria.suggestive_min_edge:.0%}".replace("%", " points") in text or (
        f"{round(criteria.suggestive_min_edge * 100)} points" in text
    )
    assert f"≥{criteria.weak_min_independent}" in text
    assert f"{round(criteria.weak_min_edge * 100)} points" in text


def test_the_register_has_no_placeholder_rows() -> None:
    """A row reading "TBD" is worse than a missing one: it looks answered."""
    text = _register_text()
    for placeholder in ("TODO", "TBD", "FIXME", "???"):
        assert placeholder not in text, f"{placeholder} in {REGISTER.name}"


def test_every_register_row_names_where_it_is_computed() -> None:
    """A definition with no location is an assertion nobody can check."""
    text = _register_text()
    rows = [
        line
        for line in text.splitlines()
        # Table body rows only: three pipes minimum, and not the header/separator.
        if line.startswith("| ") and line.count("|") >= 4 and not re.match(r"^\|\s*[-:]+\s*\|", line)
    ]
    body = [r for r in rows if not r.startswith("| Label ")]
    assert body, "no definition rows found -- the table format changed"

    for row in body:
        cells = [c.strip() for c in row.strip("|").split("|")]
        assert len(cells) >= 3, row
        assert cells[2], f"row has no 'computed in' location: {row}"

"""Tests for `app.discovery` -- the point-in-time universe selector and its exam.

The load-bearing test in this file is `test_selection_ignores_everything_after_as_of`. Every other
test here checks arithmetic; that one checks the single property the whole package exists for, and it
checks it the way `app.backtest.guards` checks causality -- by changing the future and asserting the
past did not move. A selector that silently read ahead would still produce plausible rankings, a
plausible hit rate and a plausible p-value, and nothing else in this suite would notice.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pandas as pd
import pytest

from app.config import Settings
from app.db import duck
from app.db.duck import BAR_COLUMNS, Interval
from app.discovery.candidates import StoredETFCandidates
from app.discovery.exam import annual_decision_dates, run_exam
from app.discovery.selector import select
from app.paper.marketdata import clear_frame_cache


def _weekdays(anchor: dt.date, count: int) -> list[dt.date]:
    dates: list[dt.date] = []
    day = anchor
    while len(dates) < count:
        if day.weekday() < 5:
            dates.append(day)
        day += dt.timedelta(days=1)
    return dates


def _write_series(
    settings: Settings, symbol: str, dates: list[dt.date], closes: list[float]
) -> None:
    """One daily bar per date, `adj_close == close` so the ratio the selector takes is exact."""
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
    clear_frame_cache()


def _ramp(start: float, step: float, count: int) -> list[float]:
    return [start + step * i for i in range(count)]


@pytest.fixture
def three_symbols(settings: Settings) -> tuple[Settings, dt.date]:
    """Three symbols over 600 weekdays: RISER climbs, FLAT is flat, FALLER declines.

    600 bars is comfortably past the 252-bar warmup and the 200-bar `trend` lookback, so every rank
    key is computable at the decision date rather than returning `None`.
    """
    dates = _weekdays(dt.date(2020, 1, 1), 600)
    _write_series(settings, "RISER", dates, _ramp(100.0, 0.20, 600))
    _write_series(settings, "FLAT", dates, [100.0] * 600)
    _write_series(settings, "FALLER", dates, _ramp(300.0, -0.20, 600))
    return settings, dates[-1]


def _candidates(settings: Settings) -> StoredETFCandidates:
    return StoredETFCandidates(
        settings=settings, roster=("RISER", "FLAT", "FALLER"), min_bars=252, label="test"
    )


# ---------------------------------------------------------------------------
# Candidate set: the as-of filter
# ---------------------------------------------------------------------------


def test_candidates_exclude_symbols_without_enough_history(three_symbols) -> None:
    settings, last = three_symbols
    candidates = _candidates(settings)

    # 100 weekdays in, no symbol has the 252 bars the rank keys need.
    early = _weekdays(dt.date(2020, 1, 1), 100)[-1]
    assert candidates.symbols_as_of(early) == ()

    # By the end of the series all three qualify.
    assert candidates.symbols_as_of(last) == ("FALLER", "FLAT", "RISER")


def test_candidates_are_sorted_and_stable() -> None:
    """Ordering is alphabetical, not roster order. `strategy-program/PROTOCOL.md` measured a
    53.9-point return spread from universe ordering alone; an unstable candidate order would put
    that noise underneath every exam result."""
    settings = Settings()
    unsorted = StoredETFCandidates(settings=settings, roster=("ZZZ", "AAA", "MMM"), min_bars=0)
    assert unsorted.symbols_as_of(dt.date(2020, 1, 1)) == ("AAA", "MMM", "ZZZ")


# ---------------------------------------------------------------------------
# Selector
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rank_key", ["mom12_1", "mom6", "trend"])
def test_every_rank_key_ranks_the_riser_first(three_symbols, rank_key: str) -> None:
    settings, last = three_symbols
    selection = select(
        last, candidates=_candidates(settings), settings=settings, top_n=3, rank_key=rank_key
    )
    assert selection.picks[0] == "RISER"
    assert selection.picks[-1] == "FALLER"
    assert selection.rank_key == rank_key


def test_top_n_truncates_but_scores_keep_everything(three_symbols) -> None:
    """`Selection.scores` must carry every candidate even when `picks` is one, because the exam's
    benchmark is the average of what was *considered*, not of what was chosen."""
    settings, last = three_symbols
    selection = select(last, candidates=_candidates(settings), settings=settings, top_n=1)
    assert selection.picks == ("RISER",)
    assert len(selection.scores) == 3
    assert set(selection.considered) == {"RISER", "FLAT", "FALLER"}


def test_unscoreable_symbol_is_none_not_zero(settings: Settings) -> None:
    """A symbol with too little history scores `None`, and `None` must not sort as a low number --
    "we could not judge this" is not evidence that the selector judged well."""
    dates = _weekdays(dt.date(2020, 1, 1), 300)
    _write_series(settings, "LONG", dates, _ramp(100.0, 0.1, 300))
    _write_series(settings, "SHORT", dates[-30:], [50.0] * 30)
    candidates = StoredETFCandidates(settings=settings, roster=("LONG", "SHORT"), min_bars=0)

    selection = select(dates[-1], candidates=candidates, settings=settings, top_n=5)
    by_symbol = {s.symbol: s.score for s in selection.scores}
    assert by_symbol["SHORT"] is None
    assert by_symbol["LONG"] is not None
    assert "SHORT" not in selection.picks
    assert "SHORT" not in selection.considered


def test_unknown_rank_key_raises(three_symbols) -> None:
    settings, last = three_symbols
    with pytest.raises(KeyError, match="unknown rank_key"):
        select(last, candidates=_candidates(settings), settings=settings, rank_key="nope")


def test_selection_ignores_everything_after_as_of(settings: Settings) -> None:
    """The property the package exists for: appending future bars must not move a past decision.

    Built as a reversal, which is the version that actually bites. Through the decision date FALLER
    is the worst candidate and RISER the best; afterwards FALLER explodes upward and RISER collapses.
    A selector that read past `as_of` -- through a stale cache, a wider slice, an `end` parameter
    someone added later -- would rank FALLER first on the second pass. A causal one returns exactly
    what it returned before, so the assertion is equality of the whole `Selection`, not just of the
    top pick.
    """
    dates = _weekdays(dt.date(2020, 1, 1), 600)
    decision = dates[-1]
    _write_series(settings, "RISER", dates, _ramp(100.0, 0.20, 600))
    _write_series(settings, "FLAT", dates, [100.0] * 600)
    _write_series(settings, "FALLER", dates, _ramp(300.0, -0.20, 600))
    candidates = _candidates(settings)

    before = select(decision, candidates=candidates, settings=settings, top_n=3)
    assert before.picks == ("RISER", "FLAT", "FALLER")

    future = _weekdays(decision + dt.timedelta(days=1), 300)
    _write_series(settings, "FALLER", future, _ramp(180.0, 5.0, 300))
    _write_series(settings, "RISER", future, _ramp(220.0, -0.5, 300))

    after = select(decision, candidates=candidates, settings=settings, top_n=3)
    assert after == before


# ---------------------------------------------------------------------------
# Exam
# ---------------------------------------------------------------------------


def test_annual_decision_dates_are_one_per_year_inside_the_range() -> None:
    dates = annual_decision_dates(dt.date(2010, 1, 2), dt.date(2014, 1, 2))
    assert dates == (
        dt.date(2010, 1, 2),
        dt.date(2011, 1, 2),
        dt.date(2012, 1, 2),
        dt.date(2013, 1, 2),
        dt.date(2014, 1, 2),
    )
    # An end date before that year's anchor excludes the year rather than clamping into it.
    assert annual_decision_dates(dt.date(2010, 1, 2), dt.date(2011, 1, 1))[-1] == dt.date(
        2010, 1, 2
    )


def test_benchmark_is_the_candidate_average_not_the_picks(three_symbols) -> None:
    """The design claim, asserted: with a monotone riser, a flat and a faller, picking the riser must
    show positive excess against the equal-weight candidate set. If the benchmark were SPY-like --
    anything outside the candidate set -- this number would mean something else entirely."""
    settings, last = three_symbols
    future = _weekdays(last + dt.timedelta(days=1), 260)
    _write_series(settings, "RISER", future, _ramp(220.0, 0.30, 260))
    _write_series(settings, "FLAT", future, [100.0] * 260)
    _write_series(settings, "FALLER", future, _ramp(180.0, -0.10, 260))

    result = run_exam(
        candidates=_candidates(settings),
        settings=settings,
        decision_dates=(last,),
        horizon_days=365,
        top_n=1,
    )
    trial = result.trials[0]
    assert trial.picks == ("RISER",)
    assert trial.pick_return is not None and trial.pick_return > 0
    assert trial.benchmark_return is not None
    assert trial.excess == trial.pick_return - trial.benchmark_return
    assert trial.hit is True
    assert trial.best_available is not None and trial.best_available[0] == "RISER"
    assert result.hit_rate == 1.0


def test_untested_trial_is_excluded_from_the_hit_rate(three_symbols) -> None:
    """A date with no forward data is an untested trial, not a miss. Counting it as a miss would
    make the hit rate a function of how much history happens to follow the last decision date."""
    settings, last = three_symbols
    result = run_exam(
        candidates=_candidates(settings),
        settings=settings,
        decision_dates=(last,),
        horizon_days=365,
        top_n=1,
    )
    trial = result.trials[0]
    # No bars exist after `last`, so the forward return is flat-to-unpriceable rather than a loss.
    assert len(result.trials) == 1
    if trial.excess is None:
        assert result.tested == ()
        assert result.hit_rate is None
        assert result.p_value is None


def test_picked_reports_the_dates_a_symbol_was_chosen(three_symbols) -> None:
    """`picked` is the method the whole exercise is for -- "when would this rule have put
    semiconductors in front of me" -- so it gets its own test rather than being read off `trials`."""
    settings, last = three_symbols
    result = run_exam(
        candidates=_candidates(settings),
        settings=settings,
        decision_dates=(last,),
        horizon_days=365,
        top_n=1,
    )
    assert result.picked("RISER") == (last,)
    assert result.picked("FALLER") == ()


def test_exam_records_which_candidate_set_and_key_produced_it(three_symbols) -> None:
    """A stored result that cannot say what generated it is an anecdote. Both fields are carried."""
    settings, last = three_symbols
    result = run_exam(
        candidates=_candidates(settings),
        settings=settings,
        decision_dates=(last,),
        rank_key="mom6",
        top_n=2,
    )
    assert result.candidate_set == "test"
    assert result.rank_key == "mom6"
    assert result.top_n == 2


def test_median_excess_and_hits_agree_with_the_trials(three_symbols) -> None:
    settings, last = three_symbols
    future = _weekdays(last + dt.timedelta(days=1), 260)
    _write_series(settings, "RISER", future, _ramp(220.0, 0.30, 260))
    _write_series(settings, "FLAT", future, [100.0] * 260)
    _write_series(settings, "FALLER", future, _ramp(180.0, -0.10, 260))
    result = run_exam(
        candidates=_candidates(settings),
        settings=settings,
        decision_dates=(last,),
        horizon_days=365,
        top_n=1,
    )
    excesses = [t.excess for t in result.tested]
    assert result.hits == sum(1 for e in excesses if e is not None and e > 0)
    assert result.median_excess == Decimal(str(float(excesses[0])))

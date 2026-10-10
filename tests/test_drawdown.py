"""Tests for :mod:`app.backtest.drawdown`.

Every fixture here builds its own bar frame in memory -- BAR_COLUMNS plus ``ts`` as tz-aware UTC --
never touching ``data/`` or any store/provider machinery.

Where the expected peak/trough/recovery/depth can be worked out by inspection, the assertion is
that exact literal (or a formula obviously derived from the fixture's own numbers, e.g.
``90 / 105 - 1``), never a value obtained by calling :func:`profile` a second time and comparing
against itself. A wrong constant in the implementation must fail loudly here, not slip past a loose
bound.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

import pandas as pd
import pytest

from app.backtest.drawdown import profile
from app.backtest.models import DrawdownBasis, DrawdownEpisode

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _bars(
    close: Sequence[float | None],
    *,
    high: Sequence[float | None] | None = None,
    low: Sequence[float | None] | None = None,
    adj_close: Sequence[float | None] | None = None,
    start: dt.date = dt.date(2026, 1, 2),
) -> pd.DataFrame:
    """A minimal daily bar frame: ``ts`` tz-aware UTC, one calendar day per bar, a plain positional
    index. ``None`` in any price sequence becomes ``NaN`` -- the "gap in the tape" this module has
    to not fabricate a peak or a trough from. ``high``/``low``/``adj_close`` default to a fixed
    +/-0.5 offset from ``close`` (or ``close`` itself for ``adj_close``) when a test does not care
    about them.
    """
    n = len(close)
    ts = pd.to_datetime(
        [dt.datetime.combine(start, dt.time(), tzinfo=dt.UTC) + dt.timedelta(days=i) for i in range(n)],
        utc=True,
    )

    def _floats(values: Sequence[float | None]) -> list[float]:
        return [float("nan") if v is None else float(v) for v in values]

    close_v = _floats(close)
    high_v = _floats(high) if high is not None else [c + 0.5 for c in close_v]
    low_v = _floats(low) if low is not None else [c - 0.5 for c in close_v]
    adj_v = _floats(adj_close) if adj_close is not None else list(close_v)

    return pd.DataFrame(
        {
            "ts": ts,
            "open": close_v,
            "high": high_v,
            "low": low_v,
            "close": close_v,
            "adj_close": adj_v,
            "volume": [1_000] * n,
        }
    )


def _date(i: int, start: dt.date = dt.date(2026, 1, 2)) -> dt.date:
    return start + dt.timedelta(days=i)


# ---------------------------------------------------------------------------
# Hand-built series: every field pinned by inspection
# ---------------------------------------------------------------------------


class TestHandBuiltEpisodes:
    """A twelve-bar close series with two distinct crashes, each fully recovered.

    close: 100 105 102 98 90 95 99 106 103 101 108 110  (index 0..11)

    By inspection: bar 1 (105) is a record high; bars 2-6 are underwater with a trough of 90 at
    bar 4; bar 7 (106) is both a new record and the recovery of episode 1. Bars 8-9 are underwater
    again with a trough of 101 at bar 9; bar 10 (108) recovers episode 2 and bar 11 (110) extends
    the record with nothing left underwater.
    """

    CLOSE = [100, 105, 102, 98, 90, 95, 99, 106, 103, 101, 108, 110]

    def test_every_field_of_both_episodes(self) -> None:
        bars = _bars(self.CLOSE)

        episodes, current, considered = profile(bars, basis=DrawdownBasis.CLOSE, top=10)

        assert considered == 2
        assert current is None  # bar 11 closes at a new high: nothing is underwater
        assert len(episodes) == 2

        # Deepest first: episode 1 (peak 105 -> trough 90, -14.29%) is deeper than episode 2
        # (peak 106 -> trough 101, -4.72%).
        ep1, ep2 = episodes

        # depth = trough / peak - 1, computed the same way the implementation computes it, over
        # the exact peak/trough values pinned above by inspection.
        assert ep1 == DrawdownEpisode(
            peak_date=_date(1),
            peak_value=105.0,
            trough_date=_date(4),
            trough_value=90.0,
            depth=90 / 105 - 1,
            bars_to_trough=3,
            recovery_date=_date(7),
            bars_to_recovery=6,
            bars_underwater=6,
            still_underwater=False,
        )
        assert ep2 == DrawdownEpisode(
            peak_date=_date(7),
            peak_value=106.0,
            trough_date=_date(9),
            trough_value=101.0,
            depth=101 / 106 - 1,
            bars_to_trough=2,
            recovery_date=_date(10),
            bars_to_recovery=3,
            bars_underwater=3,
            still_underwater=False,
        )
        assert ep1.depth < ep2.depth  # ep1 is the deeper (more negative) episode


# ---------------------------------------------------------------------------
# Basis comparison
# ---------------------------------------------------------------------------


class TestBasisComparison:
    """The same six bars, read under all three bases, must disagree in a specific direction:
    INTRADAY (high vs low) is the deepest, CLOSE is next, and ADJ_CLOSE -- adjusted to soften the
    dip -- is the shallowest."""

    CLOSE = [100, 110, 90, 95, 105, 112]
    ADJ_CLOSE = [100, 110, 95, 97, 106, 112]  # trough softened: 95 instead of 90
    HIGH = [100.5, 112, 91, 96, 106, 113]  # peak higher: 112 instead of 110
    LOW = [99.5, 109, 85, 94, 104, 111]  # trough lower: 85 instead of 90

    def _frame(self) -> pd.DataFrame:
        return _bars(self.CLOSE, high=self.HIGH, low=self.LOW, adj_close=self.ADJ_CLOSE)

    def test_bases_disagree_and_intraday_is_deepest(self) -> None:
        bars = self._frame()

        [close_ep], _, _ = profile(bars, basis=DrawdownBasis.CLOSE, top=10)
        [adj_ep], _, _ = profile(bars, basis=DrawdownBasis.ADJ_CLOSE, top=10)
        [intraday_ep], _, _ = profile(bars, basis=DrawdownBasis.INTRADAY, top=10)

        assert close_ep.depth == pytest.approx(90 / 110 - 1, abs=1e-12)
        assert adj_ep.depth == pytest.approx(95 / 110 - 1, abs=1e-12)
        assert intraday_ep.depth == pytest.approx(85 / 112 - 1, abs=1e-12)

        # All three land on the same peak/recovery bars (1 and 5) by construction; only the depth
        # differs, and it differs in the direction the basis docstrings promise.
        assert intraday_ep.depth < close_ep.depth < adj_ep.depth


# ---------------------------------------------------------------------------
# A series that never falls
# ---------------------------------------------------------------------------


class TestMonotonicSeries:
    def test_strictly_rising_series_has_zero_episodes_not_one_of_depth_zero(self) -> None:
        close = [100.0 + i for i in range(15)]
        bars = _bars(close)

        episodes, current, considered = profile(bars, basis=DrawdownBasis.CLOSE, top=10)

        assert episodes == []
        assert current is None
        assert considered == 0


# ---------------------------------------------------------------------------
# Still underwater at the end of the series
# ---------------------------------------------------------------------------


class TestStillUnderwater:
    def test_tail_underwater_reports_current_with_no_recovery(self) -> None:
        # 100 -> 110 (peak) -> 90 (trough) -> 95 -> 98 (last bar, still below 110)
        close = [100, 110, 90, 95, 98]
        bars = _bars(close)

        episodes, current, considered = profile(bars, basis=DrawdownBasis.CLOSE, top=10)

        assert considered == 1
        assert current is not None
        assert current.recovery_date is None
        assert current.bars_to_recovery is None
        assert current.still_underwater is True
        assert current.peak_date == _date(1)
        assert current.peak_value == 110.0
        assert current.trough_date == _date(2)
        assert current.trough_value == 90.0
        assert current.depth == pytest.approx(90 / 110 - 1, abs=1e-12)
        assert current.bars_to_trough == 1
        # Peak (bar 1) to the last stored bar (bar 4): a lower bound, per still_underwater.
        assert current.bars_underwater == 3

        # The live drawdown is also the only entry, so it must appear in the top-N list too.
        assert episodes == [current]

    def test_depth_is_the_trough_and_depth_now_is_the_latest_bar(self) -> None:
        """The two questions a live episode answers, and they are not the same question.

        `depth` is peak-to-trough -- how bad it got. `depth_now` is peak-to-latest -- where it is
        today. Reporting the first under a "current drawdown" label put -15.6% on the Report page
        for XLE while the live gap from its peak was -1.04%, and -16.0% on XLK against -4.13%. A UAT
        persona holding both names caught it by checking the headline against the quote at the top
        of the same page; nothing in the arithmetic was wrong, only what it was called.
        """
        # Peak 110, trough 90 (-18.2%), then a retrace to 108 that leaves it 1.8% down.
        close = [100, 110, 90, 95, 108]
        _episodes, current, _considered = profile(bars=_bars(close), basis=DrawdownBasis.CLOSE)

        assert current is not None
        assert current.depth == pytest.approx(90 / 110 - 1, abs=1e-12)
        assert current.depth_now == pytest.approx(108 / 110 - 1, abs=1e-12)
        assert current.depth_now is not None and current.depth_now > current.depth
        assert current.last_value == 108.0
        assert current.last_value_date == _date(4)

    def test_a_recovered_episode_has_no_current_depth(self) -> None:
        """`None`, not `0.0`.

        A recovered episode ended; it does not have a position today. Zero would say it is sitting
        exactly at its peak right now, which is a claim about a different bar than the one that
        closed the episode.
        """
        close = [100, 110, 90, 115]
        episodes, current, _considered = profile(bars=_bars(close), basis=DrawdownBasis.CLOSE)

        assert current is None
        assert len(episodes) == 1
        assert episodes[0].still_underwater is False
        assert episodes[0].depth_now is None
        assert episodes[0].last_value is None
        assert episodes[0].last_value_date is None

    def test_depth_now_uses_the_last_valid_print_and_dates_it_honestly(self) -> None:
        """A missing final print must not silently become a price.

        The module's standing rule is that a gap never participates in a figure. So `depth_now`
        falls back to the last real observation and `last_value_date` says which bar that was --
        rather than reading a NaN as a price, or dating a stale figure as though it were today's.
        """
        close = [100, 110, 90, 95, 108, None]
        _episodes, current, _considered = profile(bars=_bars(close), basis=DrawdownBasis.CLOSE)

        assert current is not None
        assert current.depth_now == pytest.approx(108 / 110 - 1, abs=1e-12)
        assert current.last_value_date == _date(4), "dated to the last real print, not the NaN bar"

    def test_a_live_episode_still_at_its_low_reports_the_same_figure_twice(self) -> None:
        """The case where the old behaviour was accidentally right, pinned so it stays right."""
        close = [100, 110, 90]
        _episodes, current, _considered = profile(bars=_bars(close), basis=DrawdownBasis.CLOSE)

        assert current is not None
        assert current.depth == pytest.approx(current.depth_now, abs=1e-12)

    def test_intraday_measures_now_on_the_high_the_recovery_test_uses(self) -> None:
        """Which column answers "where is it now" for INTRADAY, where peak and trough differ.

        The peak column (``high``) -- the same one the recovery test uses, so the question is asked
        with the measure that would actually end the episode. Answering on ``low`` would report the
        latest bar's worst excursion as the current position, a different and more alarming claim
        than the one the label makes.
        """
        close = [100, 110, 90, 106]
        high = [101, 112, 91, 107]
        low = [99, 108, 88, 104]
        _episodes, current, _considered = profile(
            bars=_bars(close, high=high, low=low), basis=DrawdownBasis.INTRADAY
        )

        assert current is not None
        # Peak is the high of bar 1 (112); the trough is the low of bar 2 (88).
        assert current.peak_value == 112.0
        assert current.trough_value == 88.0
        assert current.depth == pytest.approx(88 / 112 - 1, abs=1e-12)
        # "Now" is the last bar's high (107), not its low (104).
        assert current.last_value == 107.0
        assert current.depth_now == pytest.approx(107 / 112 - 1, abs=1e-12)


# ---------------------------------------------------------------------------
# Two crashes must not merge into one episode
# ---------------------------------------------------------------------------


class TestTwoCrashesDoNotMerge:
    def test_two_crashes_with_full_recovery_between_are_two_episodes(self) -> None:
        # Reuses the twelve-bar fixture: a full recovery to a new high sits between the two
        # crashes (bar 7), so they must not be reported as one merged decline from the first
        # peak straight through to the second trough.
        bars = _bars(TestHandBuiltEpisodes.CLOSE)

        episodes, current, considered = profile(bars, basis=DrawdownBasis.CLOSE, top=10)

        assert considered == 2
        assert len(episodes) == 2
        assert current is None

        # Distinct peaks, distinct troughs -- not one episode spanning both crashes.
        assert episodes[0].peak_date != episodes[1].peak_date
        assert episodes[0].trough_date != episodes[1].trough_date
        assert episodes[0].trough_value == 90.0
        assert episodes[1].trough_value == 101.0

        # Deepest first.
        assert episodes[0].depth < episodes[1].depth


# ---------------------------------------------------------------------------
# top-N truncation vs the true total
# ---------------------------------------------------------------------------


class TestTopTruncation:
    def test_top_1_truncates_but_considered_keeps_the_true_count(self) -> None:
        bars = _bars(TestHandBuiltEpisodes.CLOSE)

        episodes, _, considered = profile(bars, basis=DrawdownBasis.CLOSE, top=1)

        assert considered == 2
        assert len(episodes) == 1
        # The one kept is the deeper of the two (peak 105 -> trough 90).
        assert episodes[0].peak_value == 105.0
        assert episodes[0].trough_value == 90.0


# ---------------------------------------------------------------------------
# V-bottom: trough and recovery on the same bar
# ---------------------------------------------------------------------------


class TestVBottomSameBar:
    def test_intraday_recovery_on_trough_bar_has_positive_nonzero_duration(self) -> None:
        # high: 100 110 105 112 -- bar 1 is the record (110); bar 2 (105) goes underwater; bar 3's
        # high (112) recovers past the peak *and* its low (80) is deeper than bar 2's low (95) --
        # a single-bar round trip.
        high = [100, 110, 105, 112]
        low = [99, 109, 95, 80]
        close = [100, 110, 105, 112]  # not the basis under test; kept finite and harmless
        bars = _bars(close, high=high, low=low)

        episodes, current, considered = profile(bars, basis=DrawdownBasis.INTRADAY, top=10)

        assert considered == 1
        assert current is None  # bar 3 recovers, nothing left underwater
        [ep] = episodes

        assert ep.peak_date == _date(1)
        assert ep.peak_value == 110.0
        # The trough is bar 3's low (80), not bar 2's (95): the deeper dip on the recovery bar
        # itself must still be picked up.
        assert ep.trough_date == _date(3)
        assert ep.trough_value == 80.0
        assert ep.recovery_date == _date(3)
        assert ep.depth == pytest.approx(80 / 110 - 1, abs=1e-12)

        # Trough and recovery share a bar, but the duration from peak is still one full bar, not
        # zero and not negative.
        assert ep.bars_to_trough == 2
        assert ep.bars_to_recovery == 2
        assert ep.bars_underwater == 2
        assert ep.bars_to_trough > 0
        assert ep.bars_to_recovery > 0


# ---------------------------------------------------------------------------
# A gap must not fabricate a peak or a trough
# ---------------------------------------------------------------------------


class TestNaNMidSeries:
    def test_nan_bar_is_skipped_not_treated_as_a_record_or_a_trough(self) -> None:
        # close: 100 105 NaN 90 110 -- the NaN sits between the record (105) and the eventual
        # trough (90). If it were forward-filled as 105 it would look like a second tie at the
        # peak; if treated as 0/None-as-zero it would look like a (much deeper, fabricated)
        # trough. Correctly masked, the episode is unaffected: peak at bar 1, trough at bar 3.
        close = [100.0, 105.0, None, 90.0, 110.0]
        bars = _bars(close)

        episodes, current, considered = profile(bars, basis=DrawdownBasis.CLOSE, top=10)

        assert considered == 1
        assert current is None
        [ep] = episodes
        assert ep.peak_date == _date(1)
        assert ep.peak_value == 105.0
        assert ep.trough_date == _date(3)
        assert ep.trough_value == 90.0
        assert ep.recovery_date == _date(4)
        assert ep.depth == pytest.approx(90 / 105 - 1, abs=1e-12)


# ---------------------------------------------------------------------------
# Boundaries and degenerate inputs
# ---------------------------------------------------------------------------


class TestBoundaries:
    def test_empty_frame(self) -> None:
        bars = _bars([])

        episodes, current, considered = profile(bars, basis=DrawdownBasis.CLOSE, top=10)

        assert episodes == []
        assert current is None
        assert considered == 0

    def test_single_bar_frame(self) -> None:
        bars = _bars([100.0])

        episodes, current, considered = profile(bars, basis=DrawdownBasis.CLOSE, top=10)

        assert episodes == []
        assert current is None
        assert considered == 0

    def test_all_nan_close(self) -> None:
        bars = _bars([None, None, None, None])

        episodes, current, considered = profile(bars, basis=DrawdownBasis.CLOSE, top=10)

        assert episodes == []
        assert current is None
        assert considered == 0

    def test_top_zero_still_reports_the_true_count(self) -> None:
        bars = _bars(TestHandBuiltEpisodes.CLOSE)

        episodes, current, considered = profile(bars, basis=DrawdownBasis.CLOSE, top=0)

        assert episodes == []
        assert current is None
        assert considered == 2

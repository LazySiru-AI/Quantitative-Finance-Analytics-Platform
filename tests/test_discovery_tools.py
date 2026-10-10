"""Tests for the statistics, clustering and cost tools `app.discovery.exam` grades with.

Split from `tests/test_discovery.py` because these three modules are pure functions over supplied
numbers -- none of them touches a candidate set or an exam -- and testing them against hand-computed
values rather than against a fixture store is what makes them worth trusting when they contradict the
hit rate, which is exactly what they were added to be able to do.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pandas as pd
import pytest

from app.config import Settings
from app.db import duck
from app.db.duck import BAR_COLUMNS, Interval
from app.discovery.clusters import collapse_to_one_per_group, correlation_groups
from app.discovery.costs import apply_costs, turnover
from app.discovery.stats import (
    ic_summary,
    information_coefficient,
    spearman_rho,
    stationary_bootstrap_p,
)
from app.paper.marketdata import clear_frame_cache

# ---------------------------------------------------------------------------
# stats: spearman
# ---------------------------------------------------------------------------


def test_spearman_is_one_for_a_monotone_pair() -> None:
    assert spearman_rho([1.0, 2.0, 3.0, 4.0], [10.0, 20.0, 30.0, 40.0]) == pytest.approx(1.0)


def test_spearman_is_minus_one_for_a_reversal() -> None:
    assert spearman_rho([1.0, 2.0, 3.0, 4.0], [40.0, 30.0, 20.0, 10.0]) == pytest.approx(-1.0)


def test_spearman_uses_mid_ranks_for_ties() -> None:
    """`[10, 20, 20, 30]` must rank `[1, 2.5, 2.5, 4]`. Assigning ties in encounter order instead
    would make rho depend on input ordering, which is the bug this convention exists to prevent."""
    tied = [10.0, 20.0, 20.0, 30.0]
    forward = spearman_rho(tied, [1.0, 2.0, 3.0, 4.0])
    swapped = spearman_rho([10.0, 20.0, 20.0, 30.0], [1.0, 3.0, 2.0, 4.0])
    assert forward == pytest.approx(swapped)


def test_spearman_is_none_when_a_series_is_constant() -> None:
    """Undefined, not zero. Returning 0.0 would average a non-measurement in with real ones."""
    assert spearman_rho([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None


def test_spearman_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="same nonzero length"):
        spearman_rho([1.0, 2.0], [1.0])


# ---------------------------------------------------------------------------
# stats: information coefficient
# ---------------------------------------------------------------------------


def test_ic_refuses_a_cross_section_below_the_minimum() -> None:
    """Four candidates is too few -- one rank swap moves rho by ~0.4, which swamps any real effect."""
    assert information_coefficient([1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0]) is None


def test_ic_is_computed_once_the_cross_section_is_wide_enough() -> None:
    scores = [float(i) for i in range(10)]
    assert information_coefficient(scores, scores) == pytest.approx(1.0)
    assert information_coefficient(scores, list(reversed(scores))) == pytest.approx(-1.0)


def test_ic_summary_skips_unmeasurable_dates_without_counting_them() -> None:
    """`None` dates must not drag the mean toward zero -- `n` counts what was measured."""
    summary = ic_summary([0.4, None, 0.2, None])
    assert summary is not None
    assert summary.n == 2
    assert summary.mean == pytest.approx(0.3)
    assert summary.hit_rate == 1.0


def test_ic_summary_needs_two_measurable_dates() -> None:
    assert ic_summary([0.5]) is None
    assert ic_summary([None, None]) is None


def test_ic_summary_hit_rate_exposes_a_mean_carried_by_outliers() -> None:
    """The check the mean cannot do on its own: a positive mean with a coin-flip sign rate is two
    lucky dates, not skill."""
    summary = ic_summary([0.9, -0.05, 0.85, -0.05])
    assert summary is not None
    assert summary.mean > 0.35
    assert summary.hit_rate == 0.5


# ---------------------------------------------------------------------------
# stats: bootstrap
# ---------------------------------------------------------------------------


def test_bootstrap_is_deterministic_for_a_seed() -> None:
    series = [0.1, -0.2, 0.3, 0.05, -0.1, 0.25, 0.0, 0.15]
    assert stationary_bootstrap_p(series, seed=3, draws=500) == stationary_bootstrap_p(
        series, seed=3, draws=500
    )


def test_bootstrap_reports_a_strong_mean_as_unlikely_under_the_null() -> None:
    strong = [0.5, 0.55, 0.6, 0.52, 0.58, 0.51, 0.49, 0.53, 0.57, 0.54]
    p = stationary_bootstrap_p(strong, seed=1, draws=2000)
    assert p is not None and p < 0.05


def test_bootstrap_reports_a_zero_mean_series_as_unremarkable() -> None:
    noise = [0.2, -0.2, 0.15, -0.15, 0.1, -0.1, 0.05, -0.05, 0.0, 0.0]
    p = stationary_bootstrap_p(noise, seed=1, draws=2000)
    assert p is not None and p > 0.5


def test_bootstrap_refuses_a_series_too_short_to_resample() -> None:
    assert stationary_bootstrap_p([0.1, 0.2]) is None


def test_larger_blocks_widen_the_null_and_weaken_significance() -> None:
    """The whole reason the block bootstrap exists: pricing in dependence must make a p-value
    *less* impressive, never more. A block of 1 is an ordinary iid bootstrap."""
    series = [0.3, 0.31, 0.29, 0.32, 0.28, 0.30, 0.33, 0.27, 0.31, 0.29, 0.30, 0.32]
    tight = stationary_bootstrap_p(series, block=1.0, seed=5, draws=3000)
    loose = stationary_bootstrap_p(series, block=8.0, seed=5, draws=3000)
    assert tight is not None and loose is not None
    assert loose >= tight


# ---------------------------------------------------------------------------
# costs
# ---------------------------------------------------------------------------


def test_turnover_from_cash_is_a_full_entry() -> None:
    assert turnover((), ("A", "B")) == Decimal(1)


def test_turnover_is_zero_when_the_book_is_unchanged() -> None:
    """The property that makes annual costs realistic: `mom12_1` re-picks the same fund in
    consecutive years constantly, and charging those a round trip would invent trades."""
    assert turnover(("A", "B", "C"), ("A", "B", "C")) == Decimal(0)


def test_turnover_prices_one_swap_in_three() -> None:
    """One name out, one in, three equal weights: `sum|dw| = 2/3`."""
    assert turnover(("A", "B", "C"), ("A", "B", "D")) == pytest.approx(Decimal(2) / Decimal(3))


def test_costs_charge_the_first_decision_and_then_only_changes() -> None:
    series = apply_costs([("A", "B"), ("A", "B"), ("A", "C")], cost_bps=Decimal("10"))
    assert series.turnovers[0] == Decimal(1)
    assert series.turnovers[1] == Decimal(0)
    assert series.turnovers[2] == Decimal(1)
    assert series.costs[1] == Decimal(0)
    assert series.costs[0] == Decimal("10") / Decimal(10_000)


def test_cost_scales_with_the_rate() -> None:
    cheap = apply_costs([("A",), ("B",)], cost_bps=Decimal("10")).total_cost
    dear = apply_costs([("A",), ("B",)], cost_bps=Decimal("25")).total_cost
    assert dear == cheap * Decimal("2.5")


# ---------------------------------------------------------------------------
# clusters
# ---------------------------------------------------------------------------


def _weekdays(anchor: dt.date, count: int) -> list[dt.date]:
    dates: list[dt.date] = []
    day = anchor
    while len(dates) < count:
        if day.weekday() < 5:
            dates.append(day)
        day += dt.timedelta(days=1)
    return dates


def _write(settings: Settings, symbol: str, dates: list[dt.date], closes: list[float]) -> None:
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


def test_correlation_groups_merge_twins_and_leave_others_alone(settings: Settings) -> None:
    """TWIN_A and TWIN_B share a return path exactly; OTHER alternates against it. The partition must
    be `(("OTHER",), ("TWIN_A", "TWIN_B"))` -- a full partition, every symbol present exactly once."""
    dates = _weekdays(dt.date(2020, 1, 1), 300)
    wiggle = [100.0 + (3.0 if i % 2 else -3.0) + i * 0.05 for i in range(300)]
    _write(settings, "TWIN_A", dates, wiggle)
    _write(settings, "TWIN_B", dates, [w * 2.0 for w in wiggle])
    _write(
        settings, "OTHER", dates, [100.0 + (-3.0 if i % 2 else 3.0) + i * 0.05 for i in range(300)]
    )

    groups = correlation_groups(("TWIN_A", "TWIN_B", "OTHER"), dates[-1], settings=settings)
    assert groups == (("OTHER",), ("TWIN_A", "TWIN_B"))
    assert sorted(s for g in groups for s in g) == ["OTHER", "TWIN_A", "TWIN_B"]


def test_uncomputable_correlation_leaves_symbols_apart(settings: Settings) -> None:
    """A symbol too short to correlate must stay its own group. Merging on absent evidence would
    silently delete a candidate the data cannot actually vouch for."""
    dates = _weekdays(dt.date(2020, 1, 1), 300)
    _write(settings, "LONG", dates, [100.0 + i * 0.1 for i in range(300)])
    _write(settings, "TINY", dates[-5:], [50.0, 51.0, 52.0, 51.0, 50.0])

    groups = correlation_groups(("LONG", "TINY"), dates[-1], settings=settings)
    assert groups == (("LONG",), ("TINY",))


def test_collapse_keeps_the_best_ranked_member_of_each_group() -> None:
    """The selector's own preference decides which twin represents the group -- this module never
    imposes one."""
    groups = (("SMH", "SOXX"), ("XLK",))
    assert collapse_to_one_per_group(("SOXX", "SMH", "XLK"), groups) == ("SOXX", "XLK")
    assert collapse_to_one_per_group(("SMH", "SOXX", "XLK"), groups) == ("SMH", "XLK")


def test_collapse_passes_through_symbols_no_group_mentions() -> None:
    assert collapse_to_one_per_group(("A", "B"), (("C", "D"),)) == ("A", "B")

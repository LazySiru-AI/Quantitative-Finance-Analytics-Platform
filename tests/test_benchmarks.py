"""Tests for `app.paperdesk.benchmarks`, the standalone blended-benchmark pricer.

Four things this module promises, per its own docstring, and each gets a test:

1. Weights that do not sum to 1 are rejected, and the error names the actual sum
   (`test_weight_error_names_the_actual_sum`).
2. A 100%-single-symbol blend is *the same number* as the existing single-symbol path
   (`app.paperdesk.desk._buy_and_hold`'s convention: full stored history, filtered to the window,
   priced close-to-close) -- proven against the real, gitignored bar store rather than synthetic
   bars, because the whole point is to catch a real disagreement, not a disagreement this test's own
   fixture data happened not to expose (`test_single_leg_blend_matches_buy_and_hold`).
3. A leg whose stored history does not reach the window's start is reported as an explicit failure,
   never silently priced from whenever its data happens to begin
   (`test_leg_with_insufficient_history_is_reported_not_silently_shortened`).
4. The chosen rebalancing behaviour (daily, back to target weights -- see the module docstring's
   Decision 2) actually happens, proven by engineering two legs whose prices diverge and showing the
   blended result matches the daily-rebalanced arithmetic and *not* the buy-once-and-drift
   alternative, which would produce a different number from the same prices
   (`test_blend_rebalances_daily_not_buy_and_hold`).

Tests 2 and 3 use the real `data/store/bars` (skipped on a fresh clone that has none), the same
`requires_real_store` pattern `tests/test_marketdata_cache.py` already established, because both are
making a claim about this application's actual stored history (SPY since 1993, AGG since 2003) that
synthetic bars cannot stand in for. Tests 1 and 4 use the `settings` fixture's temporary store (from
`tests/conftest.py`) with bars written directly via `duck.write_bars`, the same pattern
`tests/test_tournament_runner.py` and `tests/test_marketdata_cache.py` use for engineered prices.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pandas as pd
import pytest

from app.config import REPO_ROOT, Settings
from app.db import duck
from app.market.models import BAR_COLUMNS, Interval
from app.paperdesk.benchmarks import (
    REGISTRY,
    Blend,
    InsufficientHistory,
    Leg,
    WeightError,
    price_blend,
)

_REAL_BARS_DIR = REPO_ROOT / "data" / "store" / "bars"
requires_real_store = pytest.mark.skipif(
    not _REAL_BARS_DIR.exists(),
    reason="real bar store not present (data/store is gitignored; not on a fresh clone)",
)


def _bar(ts: dt.datetime, price: float) -> dict[str, object]:
    return {
        "ts": ts,
        "open": price,
        "high": price,
        "low": price,
        "close": price,
        "adj_close": price,
        "volume": 1_000_000,
    }


def _write_daily_bars(settings: Settings, symbol: str, rows: list[dict[str, object]]) -> None:
    """Write `rows` as `symbol`'s daily bars into `settings.bars_dir` -- same pattern
    `tests/test_marketdata_cache.py`'s `_write_daily_bars` uses."""
    frame = pd.DataFrame(rows, columns=list(BAR_COLUMNS))
    with duck.connect() as conn:
        duck.write_bars(conn, settings.bars_dir, symbol, Interval.DAY, frame)


# ---------------------------------------------------------------------------
# 1. Weight validation
# ---------------------------------------------------------------------------


def test_weight_error_names_the_actual_sum() -> None:
    """Legs summing to 1.10, not 1, are rejected at construction, and the message carries the real
    sum -- not a generic "invalid weights" -- so whoever wrote the weights can see their own typo."""
    with pytest.raises(WeightError) as excinfo:
        Blend(
            name="broken",
            label="broken blend",
            legs=(Leg(symbol="SPY", weight=Decimal("0.60")), Leg(symbol="AGG", weight=Decimal("0.50"))),
        )
    assert excinfo.value.name == "broken"
    assert excinfo.value.total == Decimal("1.10")
    assert "1.10" in str(excinfo.value)
    assert "not 1" in str(excinfo.value)


def test_weight_error_also_catches_under_one() -> None:
    """The same check catches a basket that sums under 1, not just over -- both are equally not a
    valid allocation."""
    with pytest.raises(WeightError) as excinfo:
        Blend(
            name="under",
            label="under-allocated",
            legs=(Leg(symbol="SPY", weight=Decimal("0.30")), Leg(symbol="AGG", weight=Decimal("0.30"))),
        )
    assert excinfo.value.total == Decimal("0.60")


def test_registry_blend_is_actually_valid() -> None:
    """The shipped `60-40-spy-agg` registry entry itself passes the same validation every caller's
    own blend would be held to -- if this ever failed, the registry would be shipping a broken
    default."""
    blend = REGISTRY["60-40-spy-agg"]
    assert sum((leg.weight for leg in blend.legs), Decimal(0)) == Decimal(1)
    assert {leg.symbol for leg in blend.legs} == {"SPY", "AGG"}


def test_registry_has_qqq_single_leg_blend() -> None:
    """The registry carries a `"qqq"` entry, structurally identical to `"spy"`: a single QQQ leg at
    weight exactly 1. Round 5 found QQQ compounded at +18.56%/yr against SPY's +12.14%/yr over the
    trailing decade (`data/rounds/r5-2026-08/REPORT.md` section 3), which roughly halved every card's
    reported edge when measured against SPY alone -- this is the second yardstick that lets a round
    report a candidate against both."""
    blend = REGISTRY["qqq"]
    assert blend.label == "QQQ"
    assert len(blend.legs) == 1
    assert blend.legs[0].symbol == "QQQ"
    assert blend.legs[0].weight == Decimal("1")


# ---------------------------------------------------------------------------
# 2. Comparability -- the test this module exists to pass
# ---------------------------------------------------------------------------


@requires_real_store
def test_single_leg_blend_matches_buy_and_hold() -> None:
    """A blend with one leg at 100% weight must return *exactly* what `desk.py`'s own single-symbol
    convention (`_buy_and_hold`: full stored history, filtered to the window, `last close / first
    close - 1`) produces over the same window -- the property that makes a blended benchmark
    comparable to the single-symbol benchmarks this desk already renders. Computed here by hand,
    against the real store, rather than importing `_buy_and_hold` itself, so this test does not
    merely check that two calls to the same function agree with each other.
    """
    real_settings = Settings()
    start, end = dt.date(2015, 1, 2), dt.date(2020, 12, 31)

    with duck.connect() as conn:
        frame = duck.read_bars(conn, real_settings.bars_dir, "SPY", duck.Interval.DAY)
    frame = frame.copy()
    frame["ts"] = frame["ts"].dt.tz_convert("UTC")
    inside = frame[(frame["ts"].dt.date >= start) & (frame["ts"].dt.date <= end)]
    assert len(inside) > 2, "fixture assumption: the real store has SPY history across this window"
    first_close = Decimal(str(inside["close"].iloc[0]))
    last_close = Decimal(str(inside["close"].iloc[-1]))
    buy_and_hold_return = last_close / first_close - 1

    spy_only = Blend(name="spy-only", label="SPY", legs=(Leg(symbol="SPY", weight=Decimal(1)),))
    blended_return = price_blend(spy_only, start=start, end=end, settings=real_settings)

    assert blended_return == buy_and_hold_return


@requires_real_store
def test_single_leg_blend_matches_buy_and_hold_over_full_history() -> None:
    """The same equality holds across SPY's entire stored history (1993 to date), not just a short
    window -- proof that widening the internal precision (see the module docstring) actually removes
    the rounding drift a naive daily-compounding loop would otherwise accumulate over thousands of
    sessions, rather than merely hiding it in a window too short to expose it."""
    real_settings = Settings()

    with duck.connect() as conn:
        frame = duck.read_bars(conn, real_settings.bars_dir, "SPY", duck.Interval.DAY)
    frame = frame.copy()
    frame["ts"] = frame["ts"].dt.tz_convert("UTC")
    # The window is SPY's own earliest-to-latest stored range, not assumed dates -- `price_blend`
    # requires a leg's history to reach back to the window's start *and* forward to its end (see
    # `InsufficientHistory`), and hardcoding dates outside what the store actually holds would fail
    # that check rather than exercise the comparability this test is for.
    start, end = frame["ts"].iloc[0].date(), frame["ts"].iloc[-1].date()
    inside = frame[(frame["ts"].dt.date >= start) & (frame["ts"].dt.date <= end)]
    assert len(inside) > 1000, "fixture assumption: SPY has thousands of stored sessions"
    first_close = Decimal(str(inside["close"].iloc[0]))
    last_close = Decimal(str(inside["close"].iloc[-1]))
    buy_and_hold_return = last_close / first_close - 1

    spy_only = Blend(name="spy-only", label="SPY", legs=(Leg(symbol="SPY", weight=Decimal(1)),))
    blended_return = price_blend(spy_only, start=start, end=end, settings=real_settings)

    assert blended_return == buy_and_hold_return


@requires_real_store
def test_single_leg_qqq_blend_matches_buy_and_hold() -> None:
    """The same comparability property `test_single_leg_blend_matches_buy_and_hold` proves for SPY,
    proven for QQQ: a blend with one QQQ leg at 100% weight must return *exactly* what `desk.py`'s own
    single-symbol convention (`_buy_and_hold`) produces over the same window. This is the test that
    actually proves the `"qqq"` registry entry is what it claims to be, not merely that it is present
    in a dict -- computed here by hand against the real store, not by calling `price_blend` twice."""
    real_settings = Settings()
    start, end = dt.date(2015, 1, 2), dt.date(2020, 12, 31)

    with duck.connect() as conn:
        frame = duck.read_bars(conn, real_settings.bars_dir, "QQQ", duck.Interval.DAY)
    frame = frame.copy()
    frame["ts"] = frame["ts"].dt.tz_convert("UTC")
    inside = frame[(frame["ts"].dt.date >= start) & (frame["ts"].dt.date <= end)]
    assert len(inside) > 2, "fixture assumption: the real store has QQQ history across this window"
    first_close = Decimal(str(inside["close"].iloc[0]))
    last_close = Decimal(str(inside["close"].iloc[-1]))
    buy_and_hold_return = last_close / first_close - 1

    qqq_only = Blend(name="qqq-only", label="QQQ", legs=(Leg(symbol="QQQ", weight=Decimal(1)),))
    blended_return = price_blend(qqq_only, start=start, end=end, settings=real_settings)

    assert blended_return == buy_and_hold_return


@requires_real_store
def test_registry_qqq_blend_prices_sanely_over_a_real_window() -> None:
    """`price_blend` on the shipped `"qqq"` registry entry, over a real window, returns a sane
    `Decimal` -- not `None`, not a raise -- proving the registry entry (not a hand-built `Blend`) is
    actually priceable end to end."""
    real_settings = Settings()
    result = price_blend(
        REGISTRY["qqq"],
        start=dt.date(2015, 1, 2),
        end=dt.date(2020, 12, 31),
        settings=real_settings,
    )
    assert result is not None
    assert isinstance(result, Decimal)
    # Sanity bound, not a precise assertion -- QQQ neither lost everything nor 100x'd across this
    # six-year window.
    assert Decimal("-1") < result < Decimal("10")


@requires_real_store
def test_qqq_window_before_stored_history_raises_insufficient_history() -> None:
    """QQQ's real stored history starts 1999-03-10. Asking for the `"qqq"` blend from 1998 -- a window
    before any QQQ bar exists -- must raise `InsufficientHistory` naming QQQ and its actual start date,
    never silently reprice from whenever the data happens to begin."""
    real_settings = Settings()

    with pytest.raises(InsufficientHistory) as excinfo:
        price_blend(
            REGISTRY["qqq"],
            start=dt.date(1998, 1, 1),
            end=dt.date(2010, 1, 1),
            settings=real_settings,
        )

    assert excinfo.value.symbol == "QQQ"
    assert excinfo.value.blend_name == "qqq"
    assert "1999-03-10" in str(excinfo.value)
    assert "1998-01-01" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 3. Insufficient history -- reported, not silently shortened
# ---------------------------------------------------------------------------


@requires_real_store
def test_leg_with_insufficient_history_is_reported_not_silently_shortened() -> None:
    """AGG's real stored history starts 2003-09-29. Asking for the registry's 60/40 SPY/AGG blend
    from 1998 -- a window SPY alone could price -- must raise `InsufficientHistory` naming AGG and
    its actual start date, not quietly price the basket from 2003 or drop AGG and price 100% SPY.
    Both of those alternatives would look like an ordinary successful result to a caller who only
    checks whether a number came back, which is exactly what the module docstring's Decision 3
    refuses to allow.
    """
    real_settings = Settings()

    with pytest.raises(InsufficientHistory) as excinfo:
        price_blend(
            REGISTRY["60-40-spy-agg"],
            start=dt.date(1998, 1, 1),
            end=dt.date(2020, 1, 1),
            settings=real_settings,
        )

    assert excinfo.value.symbol == "AGG"
    assert excinfo.value.blend_name == "60-40-spy-agg"
    assert "2003-09-29" in str(excinfo.value)
    assert "1998-01-01" in str(excinfo.value)


@requires_real_store
def test_leg_with_full_history_on_both_sides_prices_cleanly() -> None:
    """The contrapositive of the insufficient-history test: a window entirely inside both legs'
    stored ranges prices without raising, proving the check above is about actual coverage, not a
    blanket refusal."""
    real_settings = Settings()
    result = price_blend(
        REGISTRY["60-40-spy-agg"],
        start=dt.date(2015, 1, 2),
        end=dt.date(2020, 12, 31),
        settings=real_settings,
    )
    assert result is not None
    assert isinstance(result, Decimal)


# ---------------------------------------------------------------------------
# 4. Rebalancing actually happens
# ---------------------------------------------------------------------------


def test_blend_rebalances_daily_not_buy_and_hold(settings: Settings) -> None:
    """Two synthetic legs, `UP` and `DOWN`, engineered so their prices diverge sharply on day 1 and
    then move again on day 2 -- exactly the scenario where "rebalance daily" and "buy once and hold"
    produce two different numbers from the *same* three prices, which is the only way to prove which
    one this module actually does rather than merely which one its docstring claims.

    Day 0 -> 1: UP doubles (+100%), DOWN halves (-50%).
    Day 1 -> 2: UP rises another 10%, DOWN is flat.

    Daily-rebalanced 50/50 (what this module implements): each day's blended return is the *equal-
    weighted average of that day's own two leg returns*, compounded --
        day1 = 0.5*(+100%) + 0.5*(-50%) = +25%
        day2 = 0.5*(+10%)  + 0.5*(0%)   = +5%
        total = 1.25 * 1.05 - 1 = 31.25%

    Buy-once-and-hold 50/50 (the alternative this module deliberately does *not* implement): $50 into
    each leg on day 0, shares held fixed --
        day0 value: 50 + 50 = 100
        day2 value: 50*(2 * 1.10) + 50*(0.50) = 110 + 25 = 135
        total = 135/100 - 1 = 35%

    31.25% and 35% are different numbers computed from the same three prices; asserting the blended
    result equals the first and not the second is what proves daily rebalancing, not mere blending,
    is what ran.
    """
    day0 = dt.datetime(2024, 1, 2, tzinfo=dt.UTC)
    day1 = dt.datetime(2024, 1, 3, tzinfo=dt.UTC)
    day2 = dt.datetime(2024, 1, 4, tzinfo=dt.UTC)

    _write_daily_bars(
        settings,
        "UP",
        [_bar(day0, 100.0), _bar(day1, 200.0), _bar(day2, 220.0)],
    )
    _write_daily_bars(
        settings,
        "DOWN",
        [_bar(day0, 100.0), _bar(day1, 50.0), _bar(day2, 50.0)],
    )

    blend = Blend(
        name="up-down-5050",
        label="synthetic 50/50",
        legs=(Leg(symbol="UP", weight=Decimal("0.5")), Leg(symbol="DOWN", weight=Decimal("0.5"))),
    )
    result = price_blend(blend, start=dt.date(2024, 1, 2), end=dt.date(2024, 1, 4), settings=settings)

    assert result == Decimal("0.3125")
    buy_and_hold_alternative = Decimal("0.35")
    assert result != buy_and_hold_alternative


def test_blend_of_one_leg_ignores_the_other_legs_weight_entirely(settings: Settings) -> None:
    """Sanity check on the rebalancing arithmetic itself, independent of the real store: a 100%/0%
    blend (weights still summing to 1) must track the 100%-weight leg's own daily-compounded return
    exactly, ignoring the zero-weight leg's price path completely."""
    day0 = dt.datetime(2024, 1, 2, tzinfo=dt.UTC)
    day1 = dt.datetime(2024, 1, 3, tzinfo=dt.UTC)
    day2 = dt.datetime(2024, 1, 4, tzinfo=dt.UTC)

    _write_daily_bars(settings, "ONLY", [_bar(day0, 100.0), _bar(day1, 110.0), _bar(day2, 121.0)])
    _write_daily_bars(settings, "IGNORED", [_bar(day0, 100.0), _bar(day1, 10.0), _bar(day2, 1.0)])

    blend = Blend(
        name="all-in",
        label="100% ONLY",
        legs=(Leg(symbol="ONLY", weight=Decimal(1)), Leg(symbol="IGNORED", weight=Decimal(0))),
    )
    result = price_blend(blend, start=dt.date(2024, 1, 2), end=dt.date(2024, 1, 4), settings=settings)

    assert result == Decimal("0.21")


# ---------------------------------------------------------------------------
# Window too short -- the honest "unknown", not an error
# ---------------------------------------------------------------------------


def test_window_with_fewer_than_two_sessions_is_unpriceable_not_an_error(settings: Settings) -> None:
    """A window narrow enough to contain only one stored session cannot produce a return -- reported
    as `None` (the same "unknown, not a fabricated zero" convention `_buy_and_hold` uses), not raised,
    because the data itself is fine; the request is just too narrow to yield a return."""
    only_day = dt.datetime(2024, 1, 2, tzinfo=dt.UTC)
    _write_daily_bars(settings, "SPY", [_bar(only_day, 100.0)])
    _write_daily_bars(settings, "AGG", [_bar(only_day, 100.0)])

    blend = Blend(
        name="60-40",
        label="60/40",
        legs=(Leg(symbol="SPY", weight=Decimal("0.6")), Leg(symbol="AGG", weight=Decimal("0.4"))),
    )
    result = price_blend(blend, start=dt.date(2024, 1, 2), end=dt.date(2024, 1, 2), settings=settings)

    assert result is None

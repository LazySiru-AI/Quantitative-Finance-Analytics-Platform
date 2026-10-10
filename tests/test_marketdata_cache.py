"""Tests for the process-wide frame cache in `uat.harness.marketdata`.

`AsOfMarket` used to re-read a symbol's parquet file from `app.market.store` on every single
`.history()` / `.close()` / `.open_on()` call. A tournament card walks hundreds of sessions per
symbol, so that was the dominant cost of the whole backtest loop. `_full_frame` fixes that by
reading a symbol's whole stored history once per process and caching it; every subsequent read
slices the cached frame instead of touching the parquet file again.

That cache sits directly underneath the one property this module exists to guarantee: a caller can
never see a bar later than its own `as_of`. The tests below are ordered to prove, in turn, that (1)
caching changes nothing about what a single read returns, (2) the as-of clamp still holds even when
an *earlier* `AsOfMarket` reads a symbol *after* a *later* one has already warmed the cache for it --
the specific failure mode a cache keyed on the wrong thing would produce, (3) a caller mutating a
returned frame cannot corrupt what the next caller sees, (4) a rewritten parquet file is picked up
without a process restart, and (5) repeated reads across many sessions actually hit the underlying
store exactly once.

Tests 1-2 use the real, gitignored `data/store/bars` (skipped on a fresh clone that has none) because
the whole point of test 2 is to catch a regression against real, non-synthetic history. Tests 3-5 use
the `settings` fixture's temporary store (from `tests/conftest.py`), writing known bars directly with
`duck.write_bars`, the same pattern `tests/test_tournament_runner.py` uses.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pandas as pd
import pytest

from app.config import REPO_ROOT, Settings
from app.db import duck
from app.market import store
from app.market.models import BAR_COLUMNS, Interval
from uat.harness.marketdata import AsOfMarket, clear_frame_cache

_REAL_BARS_DIR = REPO_ROOT / "data" / "store" / "bars"
requires_real_store = pytest.mark.skipif(
    not _REAL_BARS_DIR.exists(),
    reason="real bar store not present (data/store is gitignored; not on a fresh clone)",
)
_REAL_SYMBOL = "AAPL"


@pytest.fixture(autouse=True)
def _clean_frame_cache():
    """Every test starts and ends with an empty cache -- one test's cached frame must never leak
    into the next, whether that next test uses a different temp store (a different `bars_dir`, which
    the cache key already accounts for) or the same one with different data."""
    clear_frame_cache()
    yield
    clear_frame_cache()


def _bar(ts: dt.datetime, price: float, volume: int = 1_000_000) -> dict[str, object]:
    return {
        "ts": ts,
        "open": price,
        "high": price + 1.0,
        "low": price - 1.0,
        "close": price,
        "adj_close": price,
        "volume": volume,
    }


def _write_daily_bars(settings: Settings, symbol: str, rows: list[dict[str, object]]) -> None:
    """Write `rows` as `symbol`'s daily bars into `settings.bars_dir`, same pattern as
    `tests/test_tournament_runner.py`'s `_write_bars`."""
    frame = pd.DataFrame(rows, columns=list(BAR_COLUMNS))
    with duck.connect() as conn:
        duck.write_bars(conn, settings.bars_dir, symbol, Interval.DAY, frame)


def _dates(anchor: dt.date, count: int) -> list[dt.date]:
    return [anchor + dt.timedelta(days=n) for n in range(count)]


# ---------------------------------------------------------------------------
# 1. Behaviour preservation
# ---------------------------------------------------------------------------


@requires_real_store
def test_history_matches_the_uncached_baseline() -> None:
    """`AsOfMarket.history` through the cache must return exactly what the old, uncached
    `store.read_frame` call returned -- same rows, same dtypes, same column order, same index."""
    real_settings = Settings()
    as_of = dt.date(2025, 6, 2)
    lookback_days = 400

    baseline = store.read_frame(
        _REAL_SYMBOL,
        Interval.DAY,
        start=as_of - dt.timedelta(days=lookback_days),
        end=as_of,
        settings=real_settings,
    )
    assert not baseline.empty, "fixture assumption: the real store has AAPL history around this date"

    market = AsOfMarket(as_of=as_of, settings=real_settings)
    cached = market.history(_REAL_SYMBOL, lookback_days=lookback_days)

    pd.testing.assert_frame_equal(cached, baseline)


# ---------------------------------------------------------------------------
# 2. No lookahead leak across instances -- the important one
# ---------------------------------------------------------------------------


@requires_real_store
def test_no_lookahead_leak_across_instances() -> None:
    """Warm the cache from a *later* `as_of`, then read the same symbol from an *earlier* one.

    A cache keyed on the wrong thing (e.g. including `as_of` in a way that lets a wider slice get
    reused, or caching the already-sliced frame instead of the full one) would let the earlier
    instance see the later instance's rows. This is exactly the failure `AsOfMarket`'s module
    docstring says must be structurally impossible.
    """
    real_settings = Settings()
    late_as_of = dt.date(2026, 6, 1)
    early_as_of = dt.date(2024, 3, 15)

    late_market = AsOfMarket(as_of=late_as_of, settings=real_settings)
    warmed = late_market.history(_REAL_SYMBOL)
    assert not warmed.empty
    assert (warmed["ts"] <= pd.Timestamp(late_as_of, tz="UTC")).all()

    early_market = AsOfMarket(as_of=early_as_of, settings=real_settings)
    result = early_market.history(_REAL_SYMBOL)

    assert not result.empty, "fixture assumption: the real store has AAPL history around this date"
    assert (result["ts"] <= pd.Timestamp(early_as_of, tz="UTC")).all(), (
        "the earlier AsOfMarket must never see a row later than its own as_of, even though the "
        "later instance already warmed the process-wide cache for this symbol"
    )


# ---------------------------------------------------------------------------
# 3. Mutation safety
# ---------------------------------------------------------------------------


def test_mutating_a_returned_frame_does_not_corrupt_the_cache(settings: Settings) -> None:
    symbol = "MUTA"
    dates = _dates(dt.date(2026, 1, 5), 6)
    _write_daily_bars(
        settings, symbol, [_bar(dt.datetime.combine(d, dt.time.min, tzinfo=dt.UTC), 100.0 + i) for i, d in enumerate(dates)]
    )

    as_of = dates[-1]
    market = AsOfMarket(as_of=as_of, settings=settings)

    first = market.history(symbol)
    original_closes = first["close"].copy()

    # Mutate the frame the caller was handed -- exactly the pattern the module docstring warns
    # about (a strategy computing something in place against the frame it was given).
    first["close"] = -1.0
    first.iloc[0, first.columns.get_loc("open")] = -1.0

    second = market.history(symbol)

    pd.testing.assert_series_equal(
        second["close"].reset_index(drop=True), original_closes.reset_index(drop=True)
    )
    assert (second["close"] != -1.0).all()
    assert second["open"].iloc[0] != -1.0


# ---------------------------------------------------------------------------
# 4. Invalidation on rewrite
# ---------------------------------------------------------------------------


def test_rewriting_the_parquet_file_invalidates_the_cache(settings: Settings) -> None:
    symbol = "STALE"
    dates = _dates(dt.date(2026, 2, 2), 4)
    as_of = dates[-1]

    _write_daily_bars(
        settings, symbol, [_bar(dt.datetime.combine(d, dt.time.min, tzinfo=dt.UTC), 10.0 + i) for i, d in enumerate(dates)]
    )
    market_before = AsOfMarket(as_of=as_of, settings=settings)
    before = market_before.close(symbol)
    assert before == Decimal("13.0000")  # 10.0 + index 3 (the last of the 4 written rows)

    # Rewrite with different prices at the same timestamps -- `duck.write_bars` merges on `ts` and
    # the incoming row wins a collision, so this simulates a real background sync landing while the
    # process still holds a cached frame for this symbol.
    _write_daily_bars(
        settings, symbol, [_bar(dt.datetime.combine(d, dt.time.min, tzinfo=dt.UTC), 900.0 + i) for i, d in enumerate(dates)]
    )

    market_after = AsOfMarket(as_of=as_of, settings=settings)
    after = market_after.close(symbol)

    assert after == Decimal("903.0000")
    assert after != before


# ---------------------------------------------------------------------------
# 5. The underlying store is read exactly once
# ---------------------------------------------------------------------------


def test_many_sessions_produce_one_underlying_read(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    symbol = "ONECALL"
    dates = _dates(dt.date(2026, 3, 2), 30)
    _write_daily_bars(
        settings, symbol, [_bar(dt.datetime.combine(d, dt.time.min, tzinfo=dt.UTC), 50.0 + i) for i, d in enumerate(dates)]
    )

    read_calls: list[tuple[object, ...]] = []
    real_read_frame = store.read_frame

    def counting_read_frame(*args: object, **kwargs: object) -> pd.DataFrame:
        read_calls.append(args)
        return real_read_frame(*args, **kwargs)

    monkeypatch.setattr(store, "read_frame", counting_read_frame)

    # 20 "sessions", each a fresh AsOfMarket at its own as_of -- exactly how uat.harness.run and
    # app.tournament.runner use this class, one instance per session (see AsOfMarket's own
    # docstring: "construct one per session and throw it away").
    for d in dates[5:25]:
        market = AsOfMarket(as_of=d, settings=settings)
        frame = market.history(symbol)
        assert not frame.empty

    assert len(read_calls) == 1, (
        f"expected exactly one underlying store.read_frame call for {len(dates[5:25])} sessions "
        f"of one symbol, got {len(read_calls)}"
    )

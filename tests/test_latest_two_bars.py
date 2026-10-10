"""Tests for `app.market.store.latest_two_bars`: the day-over-day batched price read.

Reuses the same fake-provider/registry machinery as `TestLatestBars` in `tests/test_market_store.py`
-- a hand-written `BarProvider` wrapped in a real `ProviderRegistry`, with `settings` (from
`tests/conftest.py`) redirecting all storage into `tmp_path`. No test here touches the network, and
none of it duplicates `latest_bars`'s own staleness/sync/dedup coverage -- that is exhaustively
covered in `TestLatestBars` already, and `latest_two_bars` shares the very same `_latest_frames`
helper, so this file only exercises what is genuinely new: returning two bars instead of one.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from app.config import Settings
from app.db.duck import BAR_COLUMNS, Interval
from app.market import store
from app.market.providers.base import ProviderUnavailable
from app.market.registry import ProviderRegistry


def _bar(ts: dt.datetime, price: float, volume: int = 1000) -> dict[str, object]:
    return {
        "ts": ts,
        "open": price,
        "high": price + 0.5,
        "low": price - 0.5,
        "close": price,
        "adj_close": price,
        "volume": volume,
    }


def _daily_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=list(BAR_COLUMNS))


def _day(n: int) -> dt.datetime:
    return dt.datetime(2026, 1, n, tzinfo=dt.UTC)


class MultiSymbolFakeProvider:
    """Identical to the fixture of the same name in `tests/test_market_store.py`: a `BarProvider`
    that serves different data per symbol and can be told to fail for one symbol only."""

    def __init__(self, name: str = "yahoo") -> None:
        self.name = name
        self.supported_intervals = frozenset({Interval.DAY, Interval.HOUR, Interval.FIVE_MIN})
        self.frames: dict[str, pd.DataFrame] = {}
        self.fail_with: dict[str, Exception] = {}
        self.calls: list[str] = []

    def fetch_bars(
        self, symbol: str, interval: Interval, *, start: dt.date | None = None, end: dt.date | None = None
    ) -> pd.DataFrame:
        self.calls.append(symbol)
        if symbol in self.fail_with:
            raise self.fail_with.pop(symbol)
        frame = self.frames.get(symbol, _daily_frame([]))
        if start is None:
            return frame
        cutoff = pd.Timestamp(start, tz="UTC")
        return frame[frame["ts"] >= cutoff].reset_index(drop=True)


class TestLatestTwoBars:
    def test_two_stored_bars_returns_both_newest_first(self, settings: Settings) -> None:
        provider = MultiSymbolFakeProvider()
        provider.frames["AAA"] = _daily_frame([_bar(_day(5), 1.0), _bar(_day(6), 1.5)])
        registry = ProviderRegistry(bar_providers=(provider,))

        result = store.latest_two_bars(["AAA"], Interval.DAY, registry=registry, settings=settings)

        latest, previous = result["AAA"]
        assert latest.close == 1.5
        assert latest.ts == _day(6)
        assert previous is not None
        assert previous.close == 1.0
        assert previous.ts == _day(5)

    def test_a_single_stored_bar_returns_it_with_none_as_the_previous(
        self, settings: Settings
    ) -> None:
        provider = MultiSymbolFakeProvider()
        provider.frames["AAA"] = _daily_frame([_bar(_day(5), 1.0)])
        registry = ProviderRegistry(bar_providers=(provider,))

        result = store.latest_two_bars(["AAA"], Interval.DAY, registry=registry, settings=settings)

        latest, previous = result["AAA"]
        assert latest.close == 1.0
        assert previous is None

    def test_an_unpriceable_symbol_is_absent_from_the_dict(self, settings: Settings) -> None:
        provider = MultiSymbolFakeProvider()
        provider.fail_with["ZZZZ"] = ProviderUnavailable("no such data", provider="yahoo")
        registry = ProviderRegistry(bar_providers=(provider,))

        result = store.latest_two_bars(["ZZZZ"], Interval.DAY, registry=registry, settings=settings)

        assert result == {}

    def test_three_or_more_stored_bars_still_returns_only_the_latest_two(
        self, settings: Settings
    ) -> None:
        provider = MultiSymbolFakeProvider()
        provider.frames["AAA"] = _daily_frame(
            [_bar(_day(d), float(d)) for d in range(5, 10)]  # 5..9
        )
        registry = ProviderRegistry(bar_providers=(provider,))

        result = store.latest_two_bars(["AAA"], Interval.DAY, registry=registry, settings=settings)

        latest, previous = result["AAA"]
        assert latest.ts == _day(9)
        assert previous is not None
        assert previous.ts == _day(8)

    def test_batches_multiple_symbols_like_latest_bars_does(self, settings: Settings) -> None:
        provider = MultiSymbolFakeProvider()
        provider.frames["AAA"] = _daily_frame([_bar(_day(5), 1.0), _bar(_day(6), 2.0)])
        provider.frames["BBB"] = _daily_frame([_bar(_day(5), 10.0)])
        registry = ProviderRegistry(bar_providers=(provider,))

        result = store.latest_two_bars(
            ["AAA", "BBB"], Interval.DAY, registry=registry, settings=settings
        )

        assert set(result) == {"AAA", "BBB"}
        assert result["AAA"][0].close == 2.0
        assert result["AAA"][1] is not None
        assert result["BBB"][0].close == 10.0
        assert result["BBB"][1] is None

    def test_empty_symbol_list_returns_an_empty_dict(self, settings: Settings) -> None:
        provider = MultiSymbolFakeProvider()
        registry = ProviderRegistry(bar_providers=(provider,))

        assert store.latest_two_bars([], Interval.DAY, registry=registry, settings=settings) == {}


class TestLatestBarsUnchanged:
    """Proves the refactor into `_latest_frames` left `latest_bars` itself behaving identically for
    the same input -- a regression check on the factoring, not new coverage of `latest_bars`'s own
    logic (that lives in `TestLatestBars` in `tests/test_market_store.py`)."""

    def test_latest_bars_still_returns_exactly_one_bar_per_symbol(
        self, settings: Settings
    ) -> None:
        provider = MultiSymbolFakeProvider()
        provider.frames["AAA"] = _daily_frame([_bar(_day(5), 1.0), _bar(_day(6), 2.0)])
        registry = ProviderRegistry(bar_providers=(provider,))

        result = store.latest_bars(["AAA"], Interval.DAY, registry=registry, settings=settings)

        assert set(result) == {"AAA"}
        assert result["AAA"].close == 2.0
        assert result["AAA"].ts == _day(6)

    def test_latest_bars_and_latest_two_bars_agree_on_the_most_recent_bar(
        self, settings: Settings
    ) -> None:
        provider = MultiSymbolFakeProvider()
        provider.frames["AAA"] = _daily_frame([_bar(_day(d), float(d)) for d in range(5, 9)])
        registry = ProviderRegistry(bar_providers=(provider,))

        one = store.latest_bars(["AAA"], Interval.DAY, registry=registry, settings=settings)
        two = store.latest_two_bars(["AAA"], Interval.DAY, registry=registry, settings=settings)

        assert one["AAA"].close == two["AAA"][0].close
        assert one["AAA"].ts == two["AAA"][0].ts

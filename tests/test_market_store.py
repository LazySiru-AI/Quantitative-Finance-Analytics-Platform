"""Tests for the bar store: incremental sync, weekly resampling, limits, and the stale-data
fallback that keeps a chart rendering when a provider is down but the store already has bars.

Every test drives `app.market.store` through a hand-written fake `BarProvider` wrapped in a real
`ProviderRegistry` -- no network, and the `settings` fixture (from `tests/conftest.py`) redirects
all storage into `tmp_path` so no test can touch the user's real store.
"""

from __future__ import annotations

import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import pytest

from app.config import Settings
from app.db import duck
from app.db.duck import BAR_COLUMNS, Interval
from app.market import store
from app.market.models import BarSource
from app.market.providers.base import ProviderUnavailable
from app.market.registry import ProviderRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


class FakeBarProvider:
    """A `BarProvider` that serves rows from `frame`, filtered to `ts >= start` like a real one.

    `fail_with`, when set, is raised on the *next* call only and then cleared, so a test can make a
    single sync fail and confirm the store falls back to what it already has.
    """

    def __init__(self, name: str = "yahoo", *, frame: pd.DataFrame | None = None) -> None:
        self.name = name
        self.supported_intervals = frozenset({Interval.DAY, Interval.HOUR, Interval.FIVE_MIN})
        self.frame = frame if frame is not None else _daily_frame([])
        self.fail_with: Exception | None = None
        self.requested_starts: list[dt.date | None] = []

    def fetch_bars(
        self, symbol: str, interval: Interval, *, start: dt.date | None = None, end: dt.date | None = None
    ) -> pd.DataFrame:
        self.requested_starts.append(start)
        if self.fail_with is not None:
            exc, self.fail_with = self.fail_with, None
            raise exc
        if start is None:
            return self.frame
        cutoff = pd.Timestamp(start, tz="UTC")
        return self.frame[self.frame["ts"] >= cutoff].reset_index(drop=True)


def _registry(provider: FakeBarProvider) -> ProviderRegistry:
    return ProviderRegistry(bar_providers=(provider,))


# ---------------------------------------------------------------------------
# Incremental sync
# ---------------------------------------------------------------------------


class TestIncrementalSync:
    def test_first_sync_fetches_from_the_beginning_and_writes_every_row(self, settings: Settings) -> None:
        rows = [_bar(_day(d), float(d)) for d in range(5, 10)]
        provider = FakeBarProvider(frame=_daily_frame(rows))

        outcome = store.sync_bars("QQQ", Interval.DAY, registry=_registry(provider), settings=settings)

        assert provider.requested_starts == [None]
        assert outcome.rows_written == 5
        assert outcome.coverage.rows == 5
        assert outcome.source == BarSource.YAHOO

    def test_incremental_sync_requests_the_overlap_window(self, settings: Settings) -> None:
        rows = [_bar(_day(d), float(d)) for d in range(5, 10)]  # last stored session: Jan 9
        provider = FakeBarProvider(frame=_daily_frame(rows))
        registry = _registry(provider)
        store.sync_bars("QQQ", Interval.DAY, registry=registry, settings=settings)

        store.sync_bars("QQQ", Interval.DAY, registry=registry, settings=settings)

        # 3-session overlap for daily bars: Jan 9 - 3 days = Jan 6.
        assert provider.requested_starts[-1] == dt.date(2026, 1, 6)

    def test_incremental_sync_applies_a_correction_without_duplicating_rows(self, settings: Settings) -> None:
        rows = [_bar(_day(d), float(d)) for d in range(5, 10)]
        provider = FakeBarProvider(frame=_daily_frame(rows))
        registry = _registry(provider)
        store.sync_bars("QQQ", Interval.DAY, registry=registry, settings=settings)

        # The provider now serves a corrected close for Jan 9 plus one new session, Jan 10.
        corrected = [*rows[:-1], dict(rows[-1], close=999.0, adj_close=999.0), _bar(_day(10), 10.0)]
        provider.frame = _daily_frame(corrected)

        outcome = store.sync_bars("QQQ", Interval.DAY, registry=registry, settings=settings)

        assert outcome.coverage.rows == 6  # Jan 5-10, no duplicate Jan 9
        frame = store.read_frame("QQQ", Interval.DAY, settings=settings)
        assert len(frame) == 6
        jan_9 = frame[frame["ts"] == pd.Timestamp(_day(9))]
        assert jan_9["close"].iloc[0] == 999.0

    def test_weekly_sync_redirects_to_daily_and_warns(self, settings: Settings) -> None:
        rows = [_bar(_day(d), float(d)) for d in range(5, 10)]
        provider = FakeBarProvider(frame=_daily_frame(rows))

        outcome = store.sync_bars("QQQ", Interval.WEEK, registry=_registry(provider), settings=settings)

        assert outcome.interval == Interval.WEEK
        assert outcome.rows_written == 5  # the underlying daily sync's row count
        assert any("1d" in w.message for w in outcome.warnings)
        # Nothing was ever fetched at the WEEK interval -- the provider only ever saw DAY requests.
        assert provider.requested_starts == [None]


# ---------------------------------------------------------------------------
# Weekly resampling
# ---------------------------------------------------------------------------


class TestWeeklyResampling:
    def test_holiday_shortened_week_aggregates_ohlcv_from_the_first_session_present(
        self, settings: Settings
    ) -> None:
        # Week of Jan 19, 2026 (ISO week 4): Jan 19 is a Monday holiday and never trades, so the
        # week's sessions actually stored are Jan 20-23.
        rows = [
            _bar(_day(12), 100.0, volume=1000),  # ISO week 3
            _bar(_day(13), 101.0, volume=1000),  # ISO week 3
            _bar(_day(20), 102.0, volume=2000),  # ISO week 4, first session present
            _bar(_day(21), 108.0, volume=1500),  # ISO week 4, week high
            _bar(_day(22), 95.0, volume=1200),  # ISO week 4, week low
            _bar(_day(23), 105.0, volume=1300),  # ISO week 4, last session
        ]
        provider = FakeBarProvider(frame=_daily_frame(rows))
        store.sync_bars("QQQ", Interval.DAY, registry=_registry(provider), settings=settings)

        series = store.read_series("QQQ", Interval.WEEK, settings=settings)

        assert series.source == BarSource.DERIVED
        by_date = {b.ts.date(): b for b in series.bars}
        assert set(by_date) == {dt.date(2026, 1, 12), dt.date(2026, 1, 20)}

        week4 = by_date[dt.date(2026, 1, 20)]
        assert week4.ts == _day(20)  # ts is the first session present, never a synthetic Monday
        assert week4.open == 102.0  # first bar's open
        assert week4.close == 105.0  # last bar's close
        assert week4.high == 108.5  # max high across the group (108.0 bar's high)
        assert week4.low == 94.5  # min low across the group (95.0 bar's low)
        assert week4.volume == 2000 + 1500 + 1200 + 1300


class TestWeeklyResamplingInProgressWeek:
    """A week still being synced must not be returned as a settled bar that later mutates.

    `_resample_weekly` takes `today` explicitly so these tests are deterministic regardless of the
    real wall-clock date -- the same pattern `clamp_start` already uses for its `today` parameter.
    """

    #: ISO week 3 of 2026: Monday Jan 12 through Sunday Jan 18.
    _MON, _TUE, _WED, _THU, _FRI = (_day(12), _day(13), _day(14), _day(15), _day(16))

    def test_mid_week_read_excludes_the_still_forming_week(self) -> None:
        # Only Mon-Wed synced so far; "today" is Wednesday, the same ISO week -- the week cannot be
        # settled yet because Thu/Fri sessions have not happened.
        daily = _daily_frame([_bar(self._MON, 100.0), _bar(self._TUE, 101.0), _bar(self._WED, 102.0)])

        weekly = store._resample_weekly(daily, today=dt.date(2026, 1, 14))

        assert weekly.empty

    def test_reading_again_after_more_sessions_land_does_not_change_the_earlier_read(self) -> None:
        """The exact bug reported: Mon-Wed produced `close=90.0` (say); syncing Thursday and
        re-reading silently produced a *different* value for what was supposedly the same, already-
        returned bar. With the fix, the in-progress week is absent from both reads -- nothing that
        was ever handed to a caller as settled data changes on a later read."""
        mon_to_wed = _daily_frame(
            [_bar(self._MON, 100.0), _bar(self._TUE, 101.0), _bar(self._WED, 102.0)]
        )
        first_read = store._resample_weekly(mon_to_wed, today=dt.date(2026, 1, 14))

        mon_to_thu = _daily_frame(
            [
                _bar(self._MON, 100.0),
                _bar(self._TUE, 101.0),
                _bar(self._WED, 102.0),
                _bar(self._THU, 130.0, volume=5000),  # would have moved close/high/volume
            ]
        )
        second_read = store._resample_weekly(mon_to_thu, today=dt.date(2026, 1, 15))

        assert first_read.empty
        assert second_read.empty  # still Thursday, same ISO week: still not settled

    def test_week_appears_once_real_time_has_moved_into_the_next_iso_week(self) -> None:
        daily = _daily_frame(
            [
                _bar(self._MON, 100.0),
                _bar(self._TUE, 101.0),
                _bar(self._WED, 102.0),
                _bar(self._THU, 103.0),
                _bar(self._FRI, 104.0),
            ]
        )

        weekly = store._resample_weekly(daily, today=dt.date(2026, 1, 19))  # the following Monday

        assert len(weekly) == 1
        assert weekly.iloc[0]["close"] == 104.0

    def test_a_prior_week_is_unaffected_by_the_current_week_being_in_progress(self) -> None:
        """Only the trailing group is ever excluded -- a fully-elapsed earlier week must still be
        returned even while the latest one is still being synced."""
        daily = _daily_frame(
            [
                _bar(self._MON, 100.0),  # ISO week 3, complete
                _bar(self._FRI, 104.0),  # ISO week 3, complete
                _bar(_day(19), 110.0),  # ISO week 4 Monday, still forming
                _bar(_day(20), 111.0),  # ISO week 4 Tuesday, still forming
            ]
        )

        weekly = store._resample_weekly(daily, today=dt.date(2026, 1, 20))

        assert len(weekly) == 1
        assert weekly.iloc[0]["ts"] == pd.Timestamp(self._MON)

    def test_sync_bars_and_read_series_end_to_end_never_mutate_an_already_returned_week(
        self, settings: Settings
    ) -> None:
        """Same story as the unit-level tests above, but driven through the real `sync_bars` /
        `read_series` entry points a caller actually uses, against *this real* calendar week rather
        than a fixed one -- `_resample_weekly`'s `today` defaults to the real clock along this path,
        so the fixed January 2026 fixture dates used elsewhere in this class would not exercise the
        in-progress-week gate at all once the suite is run after that week has long passed.
        """
        real_today = dt.datetime.now(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        this_monday = real_today - dt.timedelta(days=real_today.weekday())

        provider = FakeBarProvider(
            frame=_daily_frame(
                [
                    _bar(this_monday, 100.0),
                    _bar(this_monday + dt.timedelta(days=1), 101.0),
                    _bar(this_monday + dt.timedelta(days=2), 102.0),
                ]
            )
        )
        registry = _registry(provider)
        store.sync_bars("QQQ", Interval.DAY, registry=registry, settings=settings)
        first = store.read_series("QQQ", Interval.WEEK, settings=settings)

        provider.frame = _daily_frame(
            [
                _bar(this_monday, 100.0),
                _bar(this_monday + dt.timedelta(days=1), 101.0),
                _bar(this_monday + dt.timedelta(days=2), 102.0),
                _bar(this_monday + dt.timedelta(days=3), 130.0, volume=5000),
            ]
        )
        store.sync_bars("QQQ", Interval.DAY, registry=registry, settings=settings)
        second = store.read_series("QQQ", Interval.WEEK, settings=settings)

        # The still-forming current week must be absent from both reads -- never present with one
        # set of values on the first read and a different set on the second.
        this_week = this_monday.date()
        first_this_week = [b for b in first.bars if b.ts.date() == this_week]
        second_this_week = [b for b in second.bars if b.ts.date() == this_week]
        assert first_this_week == []
        assert second_this_week == []


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


class TestReadLimit:
    def test_limit_keeps_the_most_recent_bars_not_the_earliest(self, settings: Settings) -> None:
        rows = [_bar(_day(d), float(d)) for d in range(1, 11)]
        provider = FakeBarProvider(frame=_daily_frame(rows))
        store.sync_bars("QQQ", Interval.DAY, registry=_registry(provider), settings=settings)

        series = store.read_series("QQQ", Interval.DAY, limit=3, settings=settings)

        assert [b.ts.day for b in series.bars] == [8, 9, 10]


# ---------------------------------------------------------------------------
# Stale fallback
# ---------------------------------------------------------------------------


class TestStaleFallback:
    def test_provider_down_with_a_populated_store_returns_stored_bars_with_a_stale_warning(
        self, settings: Settings
    ) -> None:
        rows = [_bar(_day(5), 1.0)]
        provider = FakeBarProvider(frame=_daily_frame(rows))
        registry = _registry(provider)
        store.sync_bars("QQQ", Interval.DAY, registry=registry, settings=settings)

        provider.fail_with = ProviderUnavailable("yahoo is down", provider="yahoo")

        series = store.ensure_series("QQQ", Interval.DAY, refresh=True, registry=registry, settings=settings)

        assert len(series.bars) == 1
        assert any(w.kind == "stale" for w in series.warnings)

    def test_provider_down_with_an_empty_store_raises(self, settings: Settings) -> None:
        provider = FakeBarProvider()
        provider.fail_with = ProviderUnavailable("yahoo is down", provider="yahoo")
        registry = _registry(provider)

        with pytest.raises(ProviderUnavailable):
            store.ensure_series("ZZZZ", Interval.DAY, registry=registry, settings=settings)

    def test_ensure_series_syncs_an_empty_store_and_returns_fresh_bars(self, settings: Settings) -> None:
        rows = [_bar(_day(d), float(d)) for d in range(5, 8)]
        provider = FakeBarProvider(frame=_daily_frame(rows))

        series = store.ensure_series("QQQ", Interval.DAY, registry=_registry(provider), settings=settings)

        assert len(series.bars) == 3
        assert provider.requested_starts == [None]

    def test_ensure_series_does_not_resync_a_fresh_store(self, settings: Settings) -> None:
        # Freshness is judged against wall-clock time, so unlike the other tests here this one needs
        # a bar dated close to "now" rather than a fixed 2026-01 fixture date.
        today = dt.datetime.now(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        rows = [_bar(today - dt.timedelta(days=d), float(d)) for d in range(2, -1, -1)]
        provider = FakeBarProvider(frame=_daily_frame(rows))
        registry = _registry(provider)
        store.sync_bars("QQQ", Interval.DAY, registry=registry, settings=settings)
        provider.requested_starts.clear()

        # A daily bar synced moments ago is not stale by the one-day threshold, so this must not
        # trigger another provider call.
        store.ensure_series("QQQ", Interval.DAY, registry=registry, settings=settings)

        assert provider.requested_starts == []


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


class TestCoverage:
    def test_coverage_reports_rows_span_and_fetch_time(self, settings: Settings) -> None:
        rows = [_bar(_day(d), float(d)) for d in range(5, 10)]
        provider = FakeBarProvider(frame=_daily_frame(rows))
        store.sync_bars("QQQ", Interval.DAY, registry=_registry(provider), settings=settings)

        cov = store.coverage("QQQ", Interval.DAY, settings=settings)

        assert cov.rows == 5
        assert cov.first_ts == _day(5)
        assert cov.last_ts == _day(9)
        assert cov.fetched_at is not None

    def test_coverage_on_an_empty_store_is_zero_rows_with_no_dates(self, settings: Settings) -> None:
        cov = store.coverage("NEWSYMBOL", Interval.DAY, settings=settings)

        assert cov.rows == 0
        assert cov.first_ts is None
        assert cov.last_ts is None
        assert cov.fetched_at is None


# ---------------------------------------------------------------------------
# `_write_meta` concurrency
# ---------------------------------------------------------------------------


class TestWriteMetaConcurrency:
    def test_concurrent_writers_to_the_same_symbol_and_interval_never_crash(
        self, settings: Settings
    ) -> None:
        """The exact race reported: two threads syncing the same symbol+interval both staged the
        meta sidecar through the identical fixed path `bars.meta.json.tmp`, and Windows refused to
        rename one thread's staging file over the other's in-flight one --
        `PermissionError: [WinError 5] Access is denied`. 8 threads x 30 rounds reproduced 94 crashes,
        every one of them *after* the bars themselves had already been written successfully, so a
        request that had actually succeeded still came back as a 500.

        Giving the staging file a uuid-suffixed name alone is *not* sufficient -- verified directly
        while building this fix: it still raced 90/240 times, because the collision is really on
        `staging.replace(path)`'s shared *destination*, not the staging name. `_write_meta` also
        serialises per meta path (`_meta_write_lock`), matching `app.db.duck._write_lock`'s solution
        to the identical problem one layer down; that is what this test actually proves closed.

        This drives `_write_meta` directly rather than the full `sync_bars` (which also touches
        DuckDB) to isolate the exact function the race lived in, at the same 8x30 scale as the
        original repro. It asserts the behaviour that matters -- no exception, no warning, and a
        readable sidecar with a real `fetched_at` afterwards -- not merely "nothing raised."
        """
        threads, rounds = 8, 30
        errors: list[BaseException] = []

        def hammer(_: int) -> None:
            for _ in range(rounds):
                try:
                    warning = store._write_meta(
                        settings.bars_dir, "QQQ", Interval.FIVE_MIN, source=BarSource.YAHOO
                    )
                    # A genuine filesystem failure would come back as a warning, not an exception --
                    # but on a healthy tmp_path filesystem this should never fire either.
                    if warning is not None:
                        errors.append(AssertionError(warning.message))
                except BaseException as exc:
                    errors.append(exc)

        with ThreadPoolExecutor(max_workers=threads) as pool:
            list(pool.map(hammer, range(threads)))

        assert errors == [], f"{len(errors)} failures across {threads}x{rounds}: {errors[:3]}"

        # The sidecar is left in a valid, readable state -- last writer wins, which is fine since
        # every writer in this test wrote the same symbol/interval/source.
        meta = store._read_meta(settings.bars_dir, "QQQ", Interval.FIVE_MIN)
        assert meta is not None
        assert store._meta_fetched_at(meta) is not None


# ---------------------------------------------------------------------------
# Non-US exchange timezone staleness
# ---------------------------------------------------------------------------


class TestExchangeTimezoneStaleness:
    """`_is_stale` / `_plausible_trading_window` used to convert "now" to America/New_York no matter
    what was actually being asked about. A Tokyo-listed symbol's real intraday session (09:00-15:00
    JST) falls at 19:00-01:00 the previous day in New York -- entirely outside the old hardcoded
    04:00-20:00 ET window -- so the gate silently reported "not worth checking" for the whole real
    trading session, no matter how stale the stored data actually was.
    """

    #: 2026-01-08T02:00Z: 21:00 the previous evening in New York (outside 04:00-20:00 ET) but 11:00
    #: the same morning in Tokyo (well inside 04:00-20:00 JST). One instant, two different answers.
    _TOKYO_SESSION_MOMENT = dt.datetime(2026, 1, 8, 2, 0, tzinfo=dt.UTC)

    def test_default_us_timezone_says_this_moment_is_outside_any_trading_window(self) -> None:
        assert not store._plausible_trading_window(Interval.FIVE_MIN, now=self._TOKYO_SESSION_MOMENT)

    def test_the_instruments_own_exchange_timezone_says_the_same_moment_is_mid_session(self) -> None:
        assert store._plausible_trading_window(
            Interval.FIVE_MIN, now=self._TOKYO_SESSION_MOMENT, exchange_tz="Asia/Tokyo"
        )

    def test_is_stale_resyncs_a_stale_tokyo_symbol_during_its_own_session(self) -> None:
        fetched_at = self._TOKYO_SESSION_MOMENT - dt.timedelta(hours=6)  # 6h > 15min 5m threshold
        has_rows = True  # only staleness is under test

        # Without a known exchange timezone (the pre-fix behaviour), the gate wrongly says this
        # moment is outside any plausible session and refuses to even check staleness.
        assert not store._is_stale(
            has_rows, Interval.FIVE_MIN, fetched_at=fetched_at, now=self._TOKYO_SESSION_MOMENT
        )

        # With the symbol's real exchange timezone, the same moment is correctly mid-session, and six
        # hours is well past the five-minute interval's fifteen-minute staleness threshold.
        assert store._is_stale(
            has_rows,
            Interval.FIVE_MIN,
            fetched_at=fetched_at,
            exchange_tz="Asia/Tokyo",
            now=self._TOKYO_SESSION_MOMENT,
        )

    def test_unrecognised_timezone_name_falls_back_to_the_default_rather_than_raising(self) -> None:
        # A corrupted sidecar or a provider-reported string `zoneinfo` cannot resolve must degrade
        # the staleness check, not the request.
        assert store._plausible_trading_window(
            Interval.FIVE_MIN, now=self._TOKYO_SESSION_MOMENT, exchange_tz="Not/AZone"
        ) == store._plausible_trading_window(Interval.FIVE_MIN, now=self._TOKYO_SESSION_MOMENT)

    def test_meta_round_trips_the_exchange_timezone_through_sync_bars(self, settings: Settings) -> None:
        """End-to-end: a provider that reports `frame.attrs["exchange_timezone"]` (as
        `YahooProvider.fetch_bars` does) gets that value threaded through `sync_bars` into the meta
        sidecar, and `ensure_series` reads it back out via `_meta_exchange_tz`."""
        frame = _daily_frame([_bar(_day(5), 1.0)])
        frame.attrs["exchange_timezone"] = "Asia/Tokyo"
        provider = FakeBarProvider(frame=frame)

        store.sync_bars("7203.T", Interval.DAY, registry=_registry(provider), settings=settings)

        meta = store._read_meta(settings.bars_dir, "7203.T", Interval.DAY)
        assert store._meta_exchange_tz(meta) == "Asia/Tokyo"


# ---------------------------------------------------------------------------
# `latest_bars`: the batched price-lookup entry point
# ---------------------------------------------------------------------------


class MultiSymbolFakeProvider:
    """A `BarProvider` that serves different data per symbol, and can be told to fail for one symbol
    only. `FakeBarProvider` above always answers with the same `self.frame` regardless of which
    symbol was asked, and its `fail_with` is instance-wide -- neither can exercise a batch call across
    several symbols where only one of them needs to behave differently from the rest.
    """

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


def _force_stale(settings: Settings, symbol: str, interval: Interval) -> None:
    """Rewrite a symbol's meta sidecar so its `fetched_at` is old enough to trip `_is_stale`, without
    going through `_write_meta` (which always stamps the *current* time)."""
    path = store._meta_path(settings.bars_dir, symbol, interval)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["fetched_at"] = (dt.datetime.now(dt.UTC) - dt.timedelta(days=5)).isoformat()
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestLatestBars:
    def test_matches_per_symbol_ensure_series(self, settings: Settings) -> None:
        """The batched call must agree with the single-symbol entry point it replaces in
        `app.api.portfolio`, symbol by symbol."""
        provider = MultiSymbolFakeProvider()
        provider.frames["AAA"] = _daily_frame([_bar(_day(d), float(d)) for d in range(5, 9)])
        provider.frames["BBB"] = _daily_frame([_bar(_day(d), float(d) * 10) for d in range(5, 9)])
        registry = ProviderRegistry(bar_providers=(provider,))

        expected = {
            symbol: store.ensure_series(symbol, Interval.DAY, registry=registry, settings=settings).bars[-1]
            for symbol in ("AAA", "BBB")
        }

        result = store.latest_bars(["AAA", "BBB"], Interval.DAY, registry=registry, settings=settings)

        assert set(result) == {"AAA", "BBB"}
        for symbol, bar in expected.items():
            assert result[symbol].close == bar.close
            assert result[symbol].ts == bar.ts

    def test_an_unstored_symbol_the_provider_refuses_is_simply_absent(self, settings: Settings) -> None:
        """No stored bars and the provider refuses too -- `ensure_series` would raise for this symbol;
        the batch must not, and every other symbol must still come back priced."""
        provider = MultiSymbolFakeProvider()
        provider.frames["AAA"] = _daily_frame([_bar(_day(5), 1.0)])
        provider.fail_with["ZZZZ"] = ProviderUnavailable("no such data", provider="yahoo")
        registry = ProviderRegistry(bar_providers=(provider,))

        result = store.latest_bars(["AAA", "ZZZZ"], Interval.DAY, registry=registry, settings=settings)

        assert set(result) == {"AAA"}

    def test_provider_failure_on_one_symbol_does_not_block_the_others(self, settings: Settings) -> None:
        """The exact batch-isolation guarantee this exists for: one bad symbol must never blank the
        rest of the portfolio."""
        provider = MultiSymbolFakeProvider()
        provider.frames["AAA"] = _daily_frame([_bar(_day(5), 1.0)])
        provider.frames["BBB"] = _daily_frame([_bar(_day(5), 2.0)])
        provider.frames["CCC"] = _daily_frame([_bar(_day(5), 3.0)])
        provider.fail_with["BBB"] = ProviderUnavailable("yahoo is down for BBB", provider="yahoo")
        registry = ProviderRegistry(bar_providers=(provider,))

        result = store.latest_bars(
            ["AAA", "BBB", "CCC"], Interval.DAY, registry=registry, settings=settings
        )

        # BBB has never been synced before, so it has nothing to fall back to and is simply absent --
        # but AAA and CCC still price.
        assert set(result) == {"AAA", "CCC"}

    def test_a_symbol_with_a_failed_refresh_still_returns_its_last_stored_bar(
        self, settings: Settings
    ) -> None:
        """Mirrors `ensure_series`'s own stale-fallback behaviour: a symbol that already has stored
        bars and whose refresh then fails must still come back with the stale bar, not drop out."""
        provider = MultiSymbolFakeProvider()
        provider.frames["AAA"] = _daily_frame([_bar(_day(5), 1.0)])
        registry = ProviderRegistry(bar_providers=(provider,))
        store.sync_bars("AAA", Interval.DAY, registry=registry, settings=settings)
        _force_stale(settings, "AAA", Interval.DAY)
        provider.fail_with["AAA"] = ProviderUnavailable("yahoo is down", provider="yahoo")

        result = store.latest_bars(["AAA"], Interval.DAY, registry=registry, settings=settings)

        assert "AAA" in result
        assert result["AAA"].close == 1.0

    def test_a_stale_symbol_syncs_exactly_once_and_a_fresh_one_does_not(self, settings: Settings) -> None:
        provider = MultiSymbolFakeProvider()
        provider.frames["STALE"] = _daily_frame([_bar(_day(5), 1.0)])
        provider.frames["FRESH"] = _daily_frame([_bar(_day(5), 2.0)])
        registry = ProviderRegistry(bar_providers=(provider,))
        store.sync_bars("STALE", Interval.DAY, registry=registry, settings=settings)
        store.sync_bars("FRESH", Interval.DAY, registry=registry, settings=settings)
        _force_stale(settings, "STALE", Interval.DAY)
        provider.calls.clear()
        # A later frame so a re-sync is externally observable in the returned close, not just in the
        # call count.
        provider.frames["STALE"] = _daily_frame(
            [_bar(_day(5), 1.0), _bar(_day(6), 1.5)]
        )

        result = store.latest_bars(["STALE", "FRESH"], Interval.DAY, registry=registry, settings=settings)

        assert provider.calls == ["STALE"]  # exactly one sync, and only for the stale symbol
        assert result["STALE"].close == 1.5  # picked up the re-synced data
        assert result["FRESH"].close == 2.0  # untouched

    def test_deduplicates_a_symbol_held_in_several_accounts(self, settings: Settings) -> None:
        """A symbol appearing twice in the input list (held in two accounts) must be synced and
        scanned once, not twice."""
        provider = MultiSymbolFakeProvider()
        provider.frames["AAA"] = _daily_frame([_bar(_day(5), 1.0)])
        registry = ProviderRegistry(bar_providers=(provider,))

        result = store.latest_bars(["AAA", "aaa", "AAA"], Interval.DAY, registry=registry, settings=settings)

        assert set(result) == {"AAA"}
        assert provider.calls == ["AAA"]

    def test_empty_symbol_list_returns_an_empty_dict(self, settings: Settings) -> None:
        provider = MultiSymbolFakeProvider()
        registry = ProviderRegistry(bar_providers=(provider,))

        assert store.latest_bars([], Interval.DAY, registry=registry, settings=settings) == {}


# ---------------------------------------------------------------------------
# D3: `read_frame` must not collide with a concurrent connection on the store
# ---------------------------------------------------------------------------


class TestReadFrameConcurrency:
    """Regression coverage for `strategy-program/DEFECTS.md` D3: `read_frame` used to open
    `analytics.duckdb` read-write even though it only reads. In production that collided with a
    second *process* also touching the file, raising `duckdb.IOException: ... being used by
    another process`; DuckDB permits any number of concurrent readers but only one writer.

    `test_read_frame_succeeds_while_another_connection_holds_the_store_read_only` reproduces the
    same class of failure in a single process rather than spawning a second one: DuckDB will not
    open a second connection to one database file with a different `read_only` configuration than
    a connection it already has open, and raises immediately rather than silently sharing state.
    That is a `duckdb.ConnectionException`, not the `IOException` production hit -- a genuinely
    separate OS process racing for the file's lock is a different code path -- but it is triggered
    by exactly the same root cause (`read_frame` opening a second, differently-configured
    connection to a file another connection already holds) and needs no subprocess machinery to
    prove.

    Confirmed directly: reverting `read_frame` to `duck.connect(cfg.analytics_path)` (the pre-fix
    code -- read-write, no `read_only=True`) makes that test fail with exactly that
    `ConnectionException`. The fix -- routing pure reads through an in-memory connection instead of
    the physical file at all, see `read_frame`'s comment -- makes it pass, because there is no
    longer a second connection to the physical file for DuckDB to object to.
    """

    def test_read_frame_succeeds_while_another_connection_holds_the_store_read_only(
        self, settings: Settings
    ) -> None:
        """The tournament runner's exact failure mode: a card calls `read_frame` while another
        process (a research script, another card, a DSL probe -- see D3's reproduction notes) has
        the physical store open. That other connection is opened `read_only=True` here, which is
        the documented concurrent-safe mode -- so if `read_frame` still collides with it, the bug
        is entirely on `read_frame`'s side, not a reasonable assumption about the other party.
        """
        rows = [_bar(_day(d), float(d)) for d in range(5, 8)]
        provider = FakeBarProvider(frame=_daily_frame(rows))
        store.sync_bars("QQQ", Interval.DAY, registry=_registry(provider), settings=settings)

        with duck.connect(settings.analytics_path, read_only=True):
            frame = store.read_frame("QQQ", Interval.DAY, settings=settings)

        assert len(frame) == 3

    def test_read_frame_succeeds_before_the_store_has_ever_been_written(
        self, settings: Settings
    ) -> None:
        """The other edge case the fix has to get right, not just avoid crashing on: the pre-fix
        code opened `analytics.duckdb` read-write, and DuckDB auto-creates a missing database file
        in that mode -- so a plain read against a never-synced symbol had the side effect of
        creating an on-disk store that nothing had asked for. A naive `read_only=True` flip trades
        that for the opposite failure (DuckDB cannot open a nonexistent database `read_only`, so
        this would raise instead). `read_frame` must not depend on `analytics.duckdb` existing,
        and must not bring it into existence as a side effect of reading either -- see
        `read_frame`'s comment for why an in-memory connection avoids both failure modes."""
        assert not settings.analytics_path.exists()

        frame = store.read_frame("NEWSYMBOL", Interval.DAY, settings=settings)

        assert frame.empty
        assert not settings.analytics_path.exists()

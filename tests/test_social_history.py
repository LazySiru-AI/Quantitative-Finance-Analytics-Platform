"""Tests for the social-sentiment snapshot store (`app.market.social_history`).

Offline and deterministic throughout: every test drives a temporary SQLite file via `tmp_path`, and
every timestamp is an explicit fixed instant rather than the real clock, so dedupe-bucket boundaries
are exact rather than racy.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import time as _time

import pytest

from app.config import Settings
from app.market import social_history as sh
from app.market.news_models import SocialSnapshot, SocialSummary
from app.market.providers.base import ProviderUnavailable
from app.market.registry import ProviderRegistry


def _snapshot(
    *,
    symbol: str = "AAPL",
    source: str = "stocktwits",
    as_of: dt.datetime,
    window_start: dt.datetime | None = None,
    bullish: int = 3,
    bearish: int = 3,
    neutral: int = 14,
) -> SocialSnapshot:
    return SocialSnapshot(
        symbol=symbol,
        source=source,
        as_of=as_of,
        window_start=window_start,
        bullish=bullish,
        bearish=bearish,
        neutral=neutral,
    )


@pytest.fixture
def conn(tmp_path) -> sqlite3.Connection:
    """A migrated, temporary store -- never the user's real database."""
    path = tmp_path / "social_history.sqlite"
    with sh.connect(path) as connection:
        yield connection


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_counts_round_trip_intact(self, conn):
        as_of = dt.datetime(2026, 8, 1, 12, 0, tzinfo=dt.UTC)
        snap = _snapshot(as_of=as_of, bullish=6, bearish=0, neutral=14)

        result = sh.record_snapshot(conn, snap, now=as_of)
        assert result.inserted is True

        history = sh.read_range(conn, "AAPL")
        assert len(history.rows) == 1
        stored = history.rows[0].snapshot
        assert stored.bullish == 6
        assert stored.bearish == 0
        assert stored.neutral == 14
        assert stored.total == 20
        assert stored.labelled == 6
        assert stored.symbol == "AAPL"
        assert stored.source == "stocktwits"
        assert stored.as_of == as_of

    def test_symbol_is_normalised_to_upper_case(self, conn):
        as_of = dt.datetime(2026, 8, 1, 12, 0, tzinfo=dt.UTC)
        snap = _snapshot(symbol="aapl", as_of=as_of)
        sh.record_snapshot(conn, snap, now=as_of)

        history = sh.read_range(conn, "aapl")
        assert history.symbol == "AAPL"
        assert len(history.rows) == 1

    def test_window_start_round_trips_when_present_and_absent(self, conn):
        as_of = dt.datetime(2026, 8, 1, 12, 0, tzinfo=dt.UTC)
        window_start = dt.datetime(2026, 8, 1, 6, 0, tzinfo=dt.UTC)
        with_window = _snapshot(symbol="AAPL", as_of=as_of, window_start=window_start)
        without_window = _snapshot(symbol="MSFT", as_of=as_of, window_start=None)

        sh.record_snapshot(conn, with_window, now=as_of)
        sh.record_snapshot(conn, without_window, now=as_of)

        aapl = sh.read_range(conn, "AAPL").rows[0].snapshot
        msft = sh.read_range(conn, "MSFT").rows[0].snapshot
        assert aapl.window_start == window_start
        assert msft.window_start is None

    def test_provenance_columns_are_distinct(self, conn):
        """`observed_at` (the provider's clock) and `recorded_at` (this store's clock) are tracked
        separately, per the module's rule 3 -- a backtest needs to know when information was
        available, not when this process happened to persist it."""
        as_of = dt.datetime(2026, 8, 1, 12, 0, tzinfo=dt.UTC)
        recorded_at = dt.datetime(2026, 8, 1, 12, 0, 3, tzinfo=dt.UTC)  # a few seconds later
        snap = _snapshot(as_of=as_of)

        sh.record_snapshot(conn, snap, now=recorded_at)

        row = sh.read_range(conn, "AAPL").rows[0]
        assert row.snapshot.as_of == as_of
        assert row.recorded_at == recorded_at
        assert row.recorded_at != row.snapshot.as_of


# ---------------------------------------------------------------------------
# Ratios derived on read, never stored
# ---------------------------------------------------------------------------


class TestNoStoredRatio:
    def test_schema_has_no_ratio_or_score_column(self, conn):
        """The load-bearing requirement: this table stores counts and nothing that looks like a
        conclusion. A `ratio`/`score` column here is exactly the defect `SocialSnapshot` was shaped
        to prevent, reintroduced one layer down in the store."""
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(social_snapshot)")}
        assert "bullish" in columns
        assert "bearish" in columns
        assert "neutral" in columns
        assert not any("ratio" in c or "score" in c for c in columns)

    def test_ratio_is_computed_at_read_time_from_stored_counts(self, conn):
        as_of = dt.datetime(2026, 8, 1, 12, 0, tzinfo=dt.UTC)
        # 100% bullish over a thin denominator -- the exact "true, useless, misleading" shape named
        # in the plan: 6 of 20 messages labelled, all of them bullish.
        snap = _snapshot(as_of=as_of, bullish=6, bearish=0, neutral=14)
        sh.record_snapshot(conn, snap, now=as_of)

        stored = sh.read_range(conn, "AAPL").rows[0].snapshot
        summary = SocialSummary.of(stored)
        assert summary.bull_ratio == 1.0
        assert summary.labelled_share == pytest.approx(6 / 20)


# ---------------------------------------------------------------------------
# Dedupe
# ---------------------------------------------------------------------------


class TestDedupe:
    def test_two_writes_in_the_same_minute_collapse_to_one_row(self, conn):
        base = dt.datetime(2026, 8, 1, 12, 0, 0, tzinfo=dt.UTC)
        first_tick = base
        second_tick = base + dt.timedelta(seconds=30)  # same minute bucket
        snap_a = _snapshot(as_of=first_tick, bullish=3, bearish=1, neutral=10)
        snap_b = _snapshot(as_of=second_tick, bullish=9, bearish=9, neutral=9)  # different content

        first = sh.record_snapshot(conn, snap_a, now=first_tick)
        second = sh.record_snapshot(conn, snap_b, now=second_tick)

        assert first.inserted is True
        assert second.inserted is False
        assert second.row_id == first.row_id

        history = sh.read_range(conn, "AAPL")
        assert len(history.rows) == 1
        # The row that survived is the first write, untouched -- append-only means the second write
        # was discarded outright rather than merged or used to overwrite the first.
        assert history.rows[0].snapshot.bullish == 3

    def test_writes_a_minute_apart_are_both_kept(self, conn):
        base = dt.datetime(2026, 8, 1, 12, 0, 0, tzinfo=dt.UTC)
        later = base + dt.timedelta(minutes=1)
        sh.record_snapshot(conn, _snapshot(as_of=base), now=base)
        result = sh.record_snapshot(conn, _snapshot(as_of=later), now=later)

        assert result.inserted is True
        assert len(sh.read_range(conn, "AAPL").rows) == 2

    def test_dedupe_is_scoped_per_symbol_and_source(self, conn):
        """Two different symbols (or two different providers for the same symbol) writing in the
        same minute must not collide with each other's dedupe bucket."""
        at = dt.datetime(2026, 8, 1, 12, 0, 0, tzinfo=dt.UTC)
        r1 = sh.record_snapshot(conn, _snapshot(symbol="AAPL", source="stocktwits", as_of=at), now=at)
        r2 = sh.record_snapshot(conn, _snapshot(symbol="MSFT", source="stocktwits", as_of=at), now=at)
        r3 = sh.record_snapshot(conn, _snapshot(symbol="AAPL", source="reddit", as_of=at), now=at)

        assert r1.inserted and r2.inserted and r3.inserted
        assert len({r1.row_id, r2.row_id, r3.row_id}) == 3


# ---------------------------------------------------------------------------
# Range queries
# ---------------------------------------------------------------------------


class TestRangeQueries:
    def test_range_query_returns_rows_ordered_oldest_to_newest(self, conn):
        t1 = dt.datetime(2026, 8, 1, 12, 0, tzinfo=dt.UTC)
        t2 = t1 + dt.timedelta(minutes=5)
        t3 = t1 + dt.timedelta(minutes=10)
        # Written out of order, to prove the read orders by `observed_at` and not insertion order.
        sh.record_snapshot(conn, _snapshot(as_of=t3, bullish=3), now=t3)
        sh.record_snapshot(conn, _snapshot(as_of=t1, bullish=1), now=t1)
        sh.record_snapshot(conn, _snapshot(as_of=t2, bullish=2), now=t2)

        history = sh.read_range(conn, "AAPL")
        observed = [row.snapshot.as_of for row in history.rows]
        assert observed == [t1, t2, t3]
        assert [row.snapshot.bullish for row in history.rows] == [1, 2, 3]

    def test_range_query_filters_by_start_and_end(self, conn):
        t1 = dt.datetime(2026, 8, 1, 12, 0, tzinfo=dt.UTC)
        t2 = t1 + dt.timedelta(minutes=5)
        t3 = t1 + dt.timedelta(minutes=10)
        for t in (t1, t2, t3):
            sh.record_snapshot(conn, _snapshot(as_of=t), now=t)

        history = sh.read_range(conn, "AAPL", start=t2, end=t2)
        assert len(history.rows) == 1
        assert history.rows[0].snapshot.as_of == t2

    def test_range_query_can_scope_to_one_source(self, conn):
        at = dt.datetime(2026, 8, 1, 12, 0, tzinfo=dt.UTC)
        sh.record_snapshot(conn, _snapshot(source="stocktwits", as_of=at), now=at)
        sh.record_snapshot(conn, _snapshot(source="reddit", as_of=at + dt.timedelta(minutes=1)), now=at + dt.timedelta(minutes=1))

        both = sh.read_range(conn, "AAPL")
        assert len(both.rows) == 2

        just_reddit = sh.read_range(conn, "AAPL", source="reddit")
        assert len(just_reddit.rows) == 1
        assert just_reddit.rows[0].snapshot.source == "reddit"

    def test_empty_store_returns_no_rows_and_no_coverage_start(self, conn):
        history = sh.read_range(conn, "AAPL")
        assert history.rows == ()
        assert history.coverage_start is None
        assert history.requested_start_before_coverage is False


# ---------------------------------------------------------------------------
# Coverage honesty: never imply history before the store began
# ---------------------------------------------------------------------------


class TestCoverageHonesty:
    def test_query_starting_before_the_earliest_row_reveals_the_gap(self, conn):
        earliest = dt.datetime(2026, 8, 1, 12, 0, tzinfo=dt.UTC)
        sh.record_snapshot(conn, _snapshot(as_of=earliest), now=earliest)

        requested_start = earliest - dt.timedelta(days=365)  # long before the store began
        history = sh.read_range(conn, "AAPL", start=requested_start)

        # The rows are still returned honestly (there is exactly one, and it is in range)...
        assert len(history.rows) == 1
        # ...but the range makes the coverage gap visible rather than letting the caller assume a
        # year of history exists just because the query didn't error or come back empty.
        assert history.coverage_start == earliest
        assert history.requested_start == requested_start
        assert history.requested_start_before_coverage is True

    def test_query_starting_after_coverage_begins_shows_no_gap(self, conn):
        earliest = dt.datetime(2026, 8, 1, 12, 0, tzinfo=dt.UTC)
        sh.record_snapshot(conn, _snapshot(as_of=earliest), now=earliest)

        history = sh.read_range(conn, "AAPL", start=earliest + dt.timedelta(minutes=1))
        assert history.requested_start_before_coverage is False

    def test_coverage_start_is_independent_of_the_requested_window(self, conn):
        """`coverage_start` answers relative to what the store holds, not relative to `start` -- a
        caller must be able to tell the store began earlier even when their own query starts later."""
        earliest = dt.datetime(2026, 8, 1, 12, 0, tzinfo=dt.UTC)
        later = earliest + dt.timedelta(days=1)
        sh.record_snapshot(conn, _snapshot(as_of=earliest), now=earliest)
        sh.record_snapshot(conn, _snapshot(as_of=later), now=later)

        history = sh.read_range(conn, "AAPL", start=later)
        assert len(history.rows) == 1  # only the later row is in range...
        assert history.coverage_start == earliest  # ...but coverage says the store goes back further


# ---------------------------------------------------------------------------
# Timezone discipline
# ---------------------------------------------------------------------------


class TestTimezoneDiscipline:
    def test_naive_now_is_rejected(self, conn):
        as_of = dt.datetime(2026, 8, 1, 12, 0, tzinfo=dt.UTC)
        with pytest.raises(ValueError, match="timezone-aware"):
            sh.record_snapshot(conn, _snapshot(as_of=as_of), now=dt.datetime(2026, 8, 1, 12, 0))

    def test_naive_range_bound_is_rejected(self, conn):
        with pytest.raises(ValueError, match="timezone-aware"):
            sh.read_range(conn, "AAPL", start=dt.datetime(2026, 8, 1))


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


class TestMigration:
    def test_migrate_is_safe_to_run_twice(self, tmp_path):
        path = tmp_path / "twice.sqlite"
        with sh.connect(path) as connection:
            version_first = sh.migrate(connection)
            version_second = sh.migrate(connection)
        assert version_first == sh.SCHEMA_VERSION
        assert version_second == sh.SCHEMA_VERSION

    def test_reopening_an_existing_store_preserves_rows(self, tmp_path):
        path = tmp_path / "reopen.sqlite"
        as_of = dt.datetime(2026, 8, 1, 12, 0, tzinfo=dt.UTC)
        with sh.connect(path) as connection:
            sh.record_snapshot(connection, _snapshot(as_of=as_of), now=as_of)

        with sh.connect(path) as connection:
            history = sh.read_range(connection, "AAPL")
        assert len(history.rows) == 1


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


class _FakeSocialProvider:
    """A minimal `SocialProvider`: one snapshot per symbol, or a raised `ProviderUnavailable` for
    symbols named in `fails`. Enough to drive `run_scheduler_pass` deterministically -- no network,
    no real StockTwits/Reddit client anywhere in this class."""

    def __init__(self, *, as_of: dt.datetime, fails: frozenset[str] = frozenset()) -> None:
        self.as_of = as_of
        self.fails = fails
        self.calls: list[str] = []

    def fetch_social(self, symbol: str, *, limit: int = 30) -> SocialSnapshot:
        self.calls.append(symbol)
        if symbol in self.fails:
            raise ProviderUnavailable(f"{symbol} is down", provider="fake")
        return _snapshot(symbol=symbol, as_of=self.as_of)


def _scheduler_settings(tmp_path, **overrides) -> Settings:
    """A `Settings` instance rooted at `tmp_path`, constructed directly rather than through
    `get_settings()` -- every test below calls `run_scheduler_pass`/`start_scheduler` with this
    passed explicitly, so there is no global cache or env var to manage. `TestLifespanWiring` below
    is the exception: it drives the real `app.main.lifespan`, which always calls `get_settings()`
    itself, so those two tests use the env var + cache-clear dance instead (mirroring
    `tests/conftest.py`'s `settings` fixture, which this file's scope fence does not include)."""
    return Settings(store_dir=tmp_path / "store", **overrides)


class TestSchedulerPass:
    """`run_scheduler_pass` -- one tick's worth of fetch-and-record, without any thread involved."""

    def test_writes_a_row_per_symbol_the_provider_serves(self, tmp_path):
        as_of = dt.datetime(2026, 8, 1, 12, 0, tzinfo=dt.UTC)
        provider = _FakeSocialProvider(as_of=as_of)
        registry = ProviderRegistry(social_providers=(provider,))
        cfg = _scheduler_settings(tmp_path)

        written, failed = sh.run_scheduler_pass(cfg, registry, ("AAPL", "MSFT"), delay_seconds=0.0)

        assert (written, failed) == (2, 0)
        with sh.connect(sh.default_db_path(cfg)) as conn:
            assert len(sh.read_range(conn, "AAPL").rows) == 1
            assert len(sh.read_range(conn, "MSFT").rows) == 1

    def test_a_failing_symbol_does_not_stop_the_pass(self, tmp_path):
        """A provider raising for one symbol must not propagate out of `run_scheduler_pass`, and the
        remaining symbols must still be attempted -- see the DoD's test (b)."""
        as_of = dt.datetime(2026, 8, 1, 12, 0, tzinfo=dt.UTC)
        provider = _FakeSocialProvider(as_of=as_of, fails=frozenset({"MSFT"}))
        registry = ProviderRegistry(social_providers=(provider,))
        cfg = _scheduler_settings(tmp_path)

        written, failed = sh.run_scheduler_pass(
            cfg, registry, ("AAPL", "MSFT", "GOOG"), delay_seconds=0.0
        )

        assert (written, failed) == (2, 1)
        # every symbol was attempted -- the MSFT failure did not end the pass early
        assert provider.calls == ["AAPL", "MSFT", "GOOG"]
        with sh.connect(sh.default_db_path(cfg)) as conn:
            assert len(sh.read_range(conn, "AAPL").rows) == 1
            assert len(sh.read_range(conn, "MSFT").rows) == 0
            assert len(sh.read_range(conn, "GOOG").rows) == 1

    def test_no_social_provider_configured_is_a_quiet_no_op(self, tmp_path):
        registry = ProviderRegistry()  # no social providers registered at all
        cfg = _scheduler_settings(tmp_path)

        written, failed = sh.run_scheduler_pass(cfg, registry, ("AAPL",), delay_seconds=0.0)

        assert (written, failed) == (0, 0)


class _RecordingThread:
    """Stands in for `threading.Thread` inside `TestStartScheduler`: records the constructor
    arguments instead of running anything, so `start_scheduler` can be asserted against without
    spinning a real thread or letting `_scheduler_loop` construct a real `default_registry` (which
    would build a real HTTP client). `monkeypatch.setattr` restores the real `threading.Thread`
    after each test regardless of outcome."""

    instances: list[_RecordingThread] = []

    def __init__(self, *, target, args, name, daemon) -> None:
        self.target = target
        self.args = args
        self.name = name
        self.daemon = daemon
        self.started = False
        _RecordingThread.instances.append(self)

    def start(self) -> None:
        self.started = True


class TestStartScheduler:
    """`start_scheduler` -- the daemon-thread starter itself, per the DoD's tests (c)/(d)."""

    def test_interval_hours_is_honoured_as_seconds_on_the_loop(self, tmp_path, monkeypatch):
        _RecordingThread.instances = []
        monkeypatch.setattr(sh.threading, "Thread", _RecordingThread)
        cfg = _scheduler_settings(tmp_path, social_snapshot_interval_hours=3.5)

        stop_event = sh.start_scheduler(cfg)

        assert stop_event is not None
        assert len(_RecordingThread.instances) == 1
        started = _RecordingThread.instances[0]
        assert started.started is True
        assert started.name == "social-snapshot-scheduler"
        assert started.daemon is True
        assert started.target is sh._scheduler_loop
        settings_arg, interval_seconds, event_arg, symbols_arg = started.args
        assert settings_arg is cfg
        assert interval_seconds == pytest.approx(3.5 * 3600.0)
        assert event_arg is stop_event
        assert symbols_arg == sh._DEFAULT_SYMBOLS

    def test_a_different_interval_produces_a_different_seconds_value(self, tmp_path, monkeypatch):
        """Not just "some number came through" -- the specific value set on `Settings` is the one
        the loop receives, distinguishing this from a test that would pass against a hard-coded
        default just as easily."""
        _RecordingThread.instances = []
        monkeypatch.setattr(sh.threading, "Thread", _RecordingThread)
        cfg = _scheduler_settings(tmp_path, social_snapshot_interval_hours=1.0)

        sh.start_scheduler(cfg)

        _, interval_seconds, _, _ = _RecordingThread.instances[0].args
        assert interval_seconds == pytest.approx(3600.0)
        assert interval_seconds != pytest.approx(3.5 * 3600.0)

    def test_non_positive_interval_starts_no_thread(self, tmp_path, monkeypatch):
        _RecordingThread.instances = []
        monkeypatch.setattr(sh.threading, "Thread", _RecordingThread)
        cfg = _scheduler_settings(tmp_path, social_snapshot_interval_hours=0.0)

        result = sh.start_scheduler(cfg)

        assert result is None
        assert _RecordingThread.instances == []


class TestLifespanWiring:
    """The two facts that live at `app.main.lifespan`, not inside this module: whether
    `start_scheduler` is even called, and whether calling it can block startup. Drives the real
    FastAPI `lifespan` through `TestClient`, the same pattern
    `tests/test_market_refresh.py::test_lifespan_leaves_the_sweep_untouched_by_default` uses for the
    sibling `refresh_on_startup` gate.
    """

    def test_disabled_the_scheduler_is_never_started(self, tmp_path, monkeypatch):
        """DoD test (c): with the flag off, `app.main.lifespan` never calls `start_scheduler`.

        **The flag is forced off here rather than inherited, and that is the point of the test.** An
        earlier version asserted `settings.social_snapshot_scheduler_enabled is False` on the shared
        `settings` fixture, reasoning that nothing sets the variable so `Settings`' own `False`
        default would hold. That is untrue the moment anyone turns the scheduler on the way it is
        meant to be turned on: `pydantic-settings` reads the repository's gitignored `.env` itself,
        so adding `INVDASH_SOCIAL_SNAPSHOT_SCHEDULER_ENABLED=1` there -- exactly what starting the
        Phase D-social clock requires -- made this test fail on that developer's machine and pass
        everywhere else.

        A test whose result depends on a file that is deliberately untracked is not testing the
        application, it is testing the checkout. Setting the variable explicitly (mirroring
        `test_enabled_startup_still_returns_promptly` below, which sets it to `"1"`) pins the
        condition this test actually cares about and makes it independent of local configuration.
        """
        from starlette.testclient import TestClient

        from app.config import get_settings
        from app.main import app
        from app.market import social_history

        for name, value in {
            "INVDASH_REPO_ROOT": tmp_path,
            "INVDASH_DATA_DIR": tmp_path / "data",
            "INVDASH_STORE_DIR": tmp_path / "store",
            "INVDASH_CACHE_DIR": tmp_path / "cache",
            "INVDASH_REFRESH_ON_STARTUP": "0",
            "INVDASH_SOCIAL_SNAPSHOT_SCHEDULER_ENABLED": "0",
        }.items():
            monkeypatch.setenv(name, str(value))
        get_settings.cache_clear()
        get_settings().ensure_dirs()

        assert get_settings().social_snapshot_scheduler_enabled is False
        calls: list[object] = []
        monkeypatch.setattr(social_history, "start_scheduler", lambda cfg=None: calls.append(cfg))

        try:
            with TestClient(app):
                pass
        finally:
            get_settings.cache_clear()

        assert calls == []

    def test_the_flag_defaults_to_false_in_the_model_itself(self) -> None:
        """The default belongs to `Settings`, and is asserted without touching the environment.

        Split out from the test above so the two claims stay separate: "the model's default is off"
        is a fact about the class and is checked by constructing it directly, while "off means the
        scheduler never starts" is a fact about `lifespan` and is checked by driving it. Conflating
        them is what let a local `.env` break a test about wiring.
        """
        from app.config import Settings

        assert Settings.model_fields["social_snapshot_scheduler_enabled"].default is False

    def test_enabled_startup_still_returns_promptly(self, tmp_path, monkeypatch):
        """DoD test (e): "assert the lifespan returns promptly with the recorder stubbed." Turns the
        flag *on* (unlike the test above) and stubs `start_scheduler` to stand in for "the
        recorder" -- proving `lifespan` itself never waits on it, which is what a caller that forgot
        to stub it would be relying on in production too, since `start_scheduler` only ever spends
        microseconds constructing a thread before returning (see that function's own docstring).
        """
        from starlette.testclient import TestClient

        from app.config import get_settings
        from app.main import app
        from app.market import social_history

        for name, value in {
            "INVDASH_REPO_ROOT": tmp_path,
            "INVDASH_DATA_DIR": tmp_path / "data",
            "INVDASH_STORE_DIR": tmp_path / "store",
            "INVDASH_CACHE_DIR": tmp_path / "cache",
            "INVDASH_REFRESH_ON_STARTUP": "0",
            "INVDASH_SOCIAL_SNAPSHOT_SCHEDULER_ENABLED": "1",
        }.items():
            monkeypatch.setenv(name, str(value))
        get_settings.cache_clear()
        get_settings().ensure_dirs()

        started: list[object] = []
        monkeypatch.setattr(
            social_history, "start_scheduler", lambda cfg=None: started.append(cfg)
        )

        try:
            begin = _time.perf_counter()
            with TestClient(app):
                pass
            elapsed = _time.perf_counter() - begin
        finally:
            get_settings.cache_clear()

        assert started  # the enabled flag really did reach the call site in `lifespan`
        assert elapsed < 5.0, f"lifespan took {elapsed:.2f}s with the recorder stubbed"

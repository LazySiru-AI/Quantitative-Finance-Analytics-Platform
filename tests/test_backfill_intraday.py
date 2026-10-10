"""Tests for `tools.backfill_intraday`.

Every test mocks `app.market.store.sync_bars` / `store.coverage` directly (the same module object
the tool imports and calls) rather than touching the real store or the network. `tools/
backfill_intraday.py`'s whole job is orchestration -- walk pairs, retry, don't abort on failure,
report -- and none of that needs a real parquet file or a real HTTP call to exercise.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

import pytest

from app.db.duck import Interval
from app.market import store
from app.market.models import BarSource, Coverage, MarketWarning
from app.market.providers.base import ProviderUnavailable, RateLimited, SymbolNotFound
from app.timeframes import RESEARCH_UNIVERSE
from tools import backfill_intraday as tool


def _coverage(interval: Interval, rows: int, *, first: dt.datetime | None = None,
              last: dt.datetime | None = None, symbol: str = "X") -> Coverage:
    return Coverage(symbol=symbol, interval=interval, rows=rows, first_ts=first, last_ts=last,
                     fetched_at=None)


def _outcome(symbol: str, interval: Interval, rows: int, *, first: dt.datetime | None = None,
             last: dt.datetime | None = None,
             warnings: tuple[MarketWarning, ...] = ()) -> store.SyncOutcome:
    return store.SyncOutcome(
        symbol=symbol,
        interval=interval,
        source=BarSource.YAHOO,
        rows_written=rows,
        coverage=_coverage(interval, rows, first=first, last=last, symbol=symbol),
        warnings=list(warnings),
    )


_T0 = dt.datetime(2026, 6, 1, tzinfo=dt.UTC)
_T1 = dt.datetime(2026, 8, 1, tzinfo=dt.UTC)


class _NoSleep:
    """A fake `time.sleep` that records calls instead of actually blocking a test."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def _log_collector() -> tuple[list[str], Callable[[str], None]]:
    lines: list[str] = []
    return lines, lines.append


# ---------------------------------------------------------------------------
# The frozen universe and interval defaults
# ---------------------------------------------------------------------------


def test_default_symbols_matches_research_universe_exactly() -> None:
    assert tuple(symbol for symbol, _sector in RESEARCH_UNIVERSE) == tool.DEFAULT_SYMBOLS
    assert len(tool.DEFAULT_SYMBOLS) == 20


def test_default_intervals_excludes_week_but_covers_every_other_interval() -> None:
    assert Interval.WEEK not in tool.DEFAULT_INTERVALS
    assert set(tool.DEFAULT_INTERVALS) == set(Interval) - {Interval.WEEK}
    assert len(tool.DEFAULT_INTERVALS) == 6


# ---------------------------------------------------------------------------
# 1w is skipped, explicitly, and never reaches sync_bars
# ---------------------------------------------------------------------------


def test_week_interval_is_skipped_and_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Interval]] = []

    def fake_sync_bars(symbol: str, interval: Interval, **kwargs: object) -> store.SyncOutcome:
        calls.append((symbol, interval))
        return _outcome(symbol, interval, rows=10, first=_T0, last=_T1)

    monkeypatch.setattr(store, "sync_bars", fake_sync_bars)
    monkeypatch.setattr(store, "coverage", lambda symbol, interval, **kw: _coverage(interval, 0))

    lines, log = _log_collector()
    results = tool.run_backfill(
        ["SPY"], [Interval.FIVE_MIN, Interval.WEEK],
        registry=object(), settings=object(), log=log, sleep=_NoSleep(),
    )

    assert calls == [("SPY", Interval.FIVE_MIN)]  # sync_bars was never asked for 1w

    week_result = next(r for r in results if r.interval is Interval.WEEK)
    assert week_result.status == "skipped"
    assert "derived" in week_result.detail

    assert any("1w" in line and "SKIPPED" in line and "derived" in line for line in lines)


# ---------------------------------------------------------------------------
# One failing pair does not abort the run, and shows up in the summary with a non-zero exit code
# ---------------------------------------------------------------------------


def test_failing_symbol_does_not_abort_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_sync_bars(symbol: str, interval: Interval, **kwargs: object) -> store.SyncOutcome:
        if symbol == "BAD":
            raise ProviderUnavailable("upstream 503", provider="yahoo")
        return _outcome(symbol, interval, rows=10, first=_T0, last=_T1)

    monkeypatch.setattr(store, "sync_bars", fake_sync_bars)
    monkeypatch.setattr(store, "coverage", lambda symbol, interval, **kw: _coverage(interval, 0))

    lines, log = _log_collector()
    results = tool.run_backfill(
        ["GOOD", "BAD"], [Interval.FIVE_MIN],
        registry=object(), settings=object(), log=log, sleep=_NoSleep(),
    )

    # both pairs were attempted -- the failure did not stop the walk
    assert {r.symbol for r in results} == {"GOOD", "BAD"}

    good = next(r for r in results if r.symbol == "GOOD")
    bad = next(r for r in results if r.symbol == "BAD")
    assert good.status == "ok"
    assert bad.status == "failed"
    assert "ProviderUnavailable" in bad.detail

    exit_code = tool.print_summary(results, log=log)
    assert exit_code == 1
    assert any("BAD" in line and "5m" in line for line in lines if "FAILURES" not in line)
    assert any("FAILURES" in line for line in lines)


def test_all_pairs_succeeding_gives_zero_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        store, "sync_bars",
        lambda symbol, interval, **kw: _outcome(symbol, interval, rows=10, first=_T0, last=_T1),
    )
    monkeypatch.setattr(store, "coverage", lambda symbol, interval, **kw: _coverage(interval, 0))

    _, log = _log_collector()
    results = tool.run_backfill(
        ["SPY", "QQQ"], [Interval.FIVE_MIN],
        registry=object(), settings=object(), log=log, sleep=_NoSleep(),
    )
    assert tool.print_summary(results, log=log) == 0


# ---------------------------------------------------------------------------
# --dry-run performs no writes
# ---------------------------------------------------------------------------


def test_dry_run_never_calls_sync_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    sync_calls: list[tuple[str, Interval]] = []

    def fake_sync_bars(symbol: str, interval: Interval, **kwargs: object) -> store.SyncOutcome:
        sync_calls.append((symbol, interval))
        raise AssertionError("sync_bars must not be called in --dry-run")

    coverage_calls: list[tuple[str, Interval]] = []

    def fake_coverage(symbol: str, interval: Interval, **kwargs: object) -> Coverage:
        coverage_calls.append((symbol, interval))
        return _coverage(interval, rows=42, first=_T0, last=_T1, symbol=symbol)

    monkeypatch.setattr(store, "sync_bars", fake_sync_bars)
    monkeypatch.setattr(store, "coverage", fake_coverage)

    _, log = _log_collector()
    results = tool.run_backfill(
        ["SPY", "QQQ"], [Interval.FIVE_MIN, Interval.FIFTEEN_MIN],
        dry_run=True, registry=object(), settings=object(), log=log, sleep=_NoSleep(),
    )

    assert sync_calls == []  # no writes attempted at all
    assert len(coverage_calls) == 4  # read-only coverage check still happens, for the report
    assert all(r.status == "ok" for r in results)
    assert all(r.bars_added == 0 for r in results)
    assert all(r.bars_before == r.bars_after == 42 for r in results)


# ---------------------------------------------------------------------------
# Rate limiting triggers a backoff-and-retry, not a dropped pair
# ---------------------------------------------------------------------------


def test_rate_limit_is_retried_not_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[int] = []

    def fake_sync_bars(symbol: str, interval: Interval, **kwargs: object) -> store.SyncOutcome:
        attempts.append(1)
        if len(attempts) == 1:
            raise RateLimited("slow down", provider="yahoo", retry_after=1.5)
        return _outcome(symbol, interval, rows=10, first=_T0, last=_T1)

    monkeypatch.setattr(store, "sync_bars", fake_sync_bars)
    monkeypatch.setattr(store, "coverage", lambda symbol, interval, **kw: _coverage(interval, 0))

    sleeper = _NoSleep()
    lines, log = _log_collector()
    results = tool.run_backfill(
        ["SPY"], [Interval.FIVE_MIN],
        registry=object(), settings=object(), log=log, sleep=sleeper, delay=0.0,
        max_retries=3,
    )

    assert len(attempts) == 2  # first attempt rate-limited, second attempt succeeded
    assert 1.5 in sleeper.calls  # the provider-supplied retry_after was honoured
    result = results[0]
    assert result.status == "ok"  # the pair was NOT dropped/marked failed
    assert result.attempts == 2
    assert any("rate limited" in line.lower() for line in lines)


def test_rate_limit_exhausting_retries_is_recorded_as_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_sync_bars(symbol: str, interval: Interval, **kwargs: object) -> store.SyncOutcome:
        raise RateLimited("still slow", provider="yahoo", retry_after=0.1)

    monkeypatch.setattr(store, "sync_bars", fake_sync_bars)
    monkeypatch.setattr(store, "coverage", lambda symbol, interval, **kw: _coverage(interval, 0))

    _, log = _log_collector()
    results = tool.run_backfill(
        ["SPY"], [Interval.FIVE_MIN],
        registry=object(), settings=object(), log=log, sleep=_NoSleep(), delay=0.0,
        max_retries=2,
    )

    result = results[0]
    assert result.status == "failed"
    assert "RateLimited" in result.detail


# ---------------------------------------------------------------------------
# SymbolNotFound is terminal for that symbol -- it does not get retried, and remaining
# intervals for the same symbol are skipped rather than re-asking the same dead question.
# ---------------------------------------------------------------------------


def test_symbol_not_found_skips_remaining_intervals_for_that_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Interval]] = []

    def fake_sync_bars(symbol: str, interval: Interval, **kwargs: object) -> store.SyncOutcome:
        calls.append((symbol, interval))
        if symbol == "DEADTICKER":
            raise SymbolNotFound("no such ticker", provider="yahoo")
        return _outcome(symbol, interval, rows=10, first=_T0, last=_T1)

    monkeypatch.setattr(store, "sync_bars", fake_sync_bars)
    monkeypatch.setattr(store, "coverage", lambda symbol, interval, **kw: _coverage(interval, 0))

    _, log = _log_collector()
    results = tool.run_backfill(
        ["DEADTICKER"], [Interval.FIVE_MIN, Interval.FIFTEEN_MIN, Interval.THIRTY_MIN],
        registry=object(), settings=object(), log=log, sleep=_NoSleep(),
    )

    # sync_bars was only ever asked once for the dead symbol -- the other two intervals were
    # skipped locally, not re-asked and re-rejected.
    assert calls == [("DEADTICKER", Interval.FIVE_MIN)]

    statuses = {r.interval: r.status for r in results}
    assert statuses[Interval.FIVE_MIN] == "failed"
    assert statuses[Interval.FIFTEEN_MIN] == "skipped"
    assert statuses[Interval.THIRTY_MIN] == "skipped"


# ---------------------------------------------------------------------------
# main() wiring: exit code propagates end to end
# ---------------------------------------------------------------------------


def test_main_returns_nonzero_when_a_pair_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_sync_bars(symbol: str, interval: Interval, **kwargs: object) -> store.SyncOutcome:
        raise ProviderUnavailable("down", provider="yahoo")

    monkeypatch.setattr(store, "sync_bars", fake_sync_bars)
    monkeypatch.setattr(store, "coverage", lambda symbol, interval, **kw: _coverage(interval, 0))
    monkeypatch.setattr(tool.time, "sleep", lambda seconds: None)

    exit_code = tool.main(["--symbols", "SPY", "--intervals", "5m", "--delay", "0"])
    assert exit_code == 1


def test_main_dry_run_returns_zero_and_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_sync_bars(symbol: str, interval: Interval, **kwargs: object) -> store.SyncOutcome:
        raise AssertionError("must not be called in --dry-run")

    monkeypatch.setattr(store, "sync_bars", fake_sync_bars)
    monkeypatch.setattr(store, "coverage", lambda symbol, interval, **kw: _coverage(interval, 5))

    exit_code = tool.main(
        ["--symbols", "SPY,QQQ", "--intervals", "5m,15m", "--dry-run", "--delay", "0"]
    )
    assert exit_code == 0

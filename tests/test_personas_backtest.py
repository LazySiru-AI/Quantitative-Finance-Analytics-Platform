"""Tests for `app.personas.backtest.run_backtest` -- see `docs/INFLUENCER-CONTRACT.md`, "Phase 4b --
persona backtest lens (pinned)", for the semantics under test. Every test replaces
`backtest.score_calls` with a canned `PersonaScorecard` (hand-built `CallScore`s) and
`backtest.ensure_series` with a fake SPY series, so the suite never touches the network, a real bar
store, or the scoring module's own logic -- this module's only job is the benchmark comparison, and
that is what these tests isolate.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

import pytest

from app.config import Settings
from app.db.duck import Interval
from app.market.models import Bar, BarSeries, BarSource
from app.market.providers.base import ProviderUnavailable
from app.personas import backtest
from app.personas.models import (
    CallScore,
    DigestWarning,
    HorizonReturn,
    PersonaScorecard,
)

UTC = dt.UTC
NOW = dt.datetime(2026, 3, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _bar(day: dt.date, close: float) -> Bar:
    return Bar(
        ts=dt.datetime(day.year, day.month, day.day, tzinfo=UTC),
        open=close,
        high=close,
        low=close,
        close=close,
    )


def _spy_series(bars: Sequence[Bar]) -> BarSeries:
    return BarSeries(symbol="SPY", interval=Interval.DAY, source=BarSource.STORE, bars=list(bars))


def _horizon(days: int, return_pct: float | None, *, complete: bool) -> HorizonReturn:
    return HorizonReturn(days=days, return_pct=return_pct, complete=complete)


def _call(
    *,
    symbol: str = "AAA",
    stance: str = "bullish",
    note_id: str = "n1",
    said_on: dt.datetime = dt.datetime(2026, 1, 5, tzinfo=UTC),
    entry_date: dt.datetime | None = dt.datetime(2026, 1, 5, tzinfo=UTC),
    horizons: Sequence[HorizonReturn] = (),
) -> CallScore:
    return CallScore(
        symbol=symbol,
        stance=stance,  # type: ignore[arg-type]
        note_id=note_id,
        said_on=said_on,
        entry_date=entry_date,
        entry_price=100.0 if entry_date is not None else None,
        latest_date=said_on,
        latest_price=100.0 if entry_date is not None else None,
        return_pct=0.0 if entry_date is not None else None,
        basis="close" if entry_date is not None else None,
        outcome="played_out" if entry_date is not None else "pending",
        horizons=tuple(horizons),
    )


def _card(calls: Sequence[CallScore], warnings: Sequence[DigestWarning] = ()) -> PersonaScorecard:
    return PersonaScorecard(
        persona="p",
        as_of=NOW,
        scored_calls=tuple(calls),
        warnings=tuple(warnings),
    )


def _patch_score_calls(monkeypatch: pytest.MonkeyPatch, card: PersonaScorecard) -> None:
    def _fake(
        *, persona_slug: str, notes: object, settings: Settings, now: dt.datetime | None = None
    ) -> PersonaScorecard:
        return card

    monkeypatch.setattr(backtest, "score_calls", _fake)


class _FakeEnsureSeries:
    """Records every call and answers with a fixed `BarSeries` or raises a fixed `Exception`."""

    def __init__(self, answer: BarSeries | Exception) -> None:
        self.answer = answer
        self.calls: list[tuple[str, dt.date | None]] = []

    def __call__(
        self,
        symbol: str,
        interval: Interval,
        *,
        start: dt.date | None = None,
        end: dt.date | None = None,
        settings: Settings | None = None,
        **_: object,
    ) -> BarSeries:
        self.calls.append((symbol, start))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _patch_ensure_series(
    monkeypatch: pytest.MonkeyPatch, answer: BarSeries | Exception
) -> _FakeEnsureSeries:
    fake = _FakeEnsureSeries(answer)
    monkeypatch.setattr(backtest, "ensure_series", fake)
    return fake


#: A six-bar SPY series, entry at index 0 (2026-01-05), covering a complete 5-day horizon
#: (index 5, 2026-01-12) but nothing at 20 or 60 days out.
_SPY_5D_UP = _spy_series(
    [
        _bar(dt.date(2026, 1, 5), 400.0),  # entry, index 0
        _bar(dt.date(2026, 1, 6), 402.0),
        _bar(dt.date(2026, 1, 7), 404.0),
        _bar(dt.date(2026, 1, 8), 406.0),
        _bar(dt.date(2026, 1, 9), 408.0),
        _bar(dt.date(2026, 1, 12), 420.0),  # index 5 -> +5.0% from 400.0
    ]
)

_SPY_5D_DOWN = _spy_series(
    [
        _bar(dt.date(2026, 1, 5), 400.0),  # entry, index 0
        _bar(dt.date(2026, 1, 6), 398.0),
        _bar(dt.date(2026, 1, 7), 396.0),
        _bar(dt.date(2026, 1, 8), 394.0),
        _bar(dt.date(2026, 1, 9), 392.0),
        _bar(dt.date(2026, 1, 12), 388.0),  # index 5 -> -3.0% from 400.0
    ]
)


# ---------------------------------------------------------------------------
# Basic module surface
# ---------------------------------------------------------------------------


def test_benchmark_constant_and_caveat_are_honest_strings() -> None:
    assert backtest.BENCHMARK == "SPY"
    assert "SPY" in backtest._CAVEAT
    assert "not" in backtest._CAVEAT.lower()  # disclaims skill/advice/prediction in some form


# ---------------------------------------------------------------------------
# Bullish call beats SPY -- positive excess
# ---------------------------------------------------------------------------


class TestBullishBeatsBenchmark:
    def test_positive_excess_and_win(self, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
        call = _call(
            stance="bullish",
            horizons=[
                _horizon(5, 20.0, complete=True),
                _horizon(20, None, complete=False),
                _horizon(60, None, complete=False),
            ],
        )
        _patch_score_calls(monkeypatch, _card([call]))
        _patch_ensure_series(monkeypatch, _SPY_5D_UP)

        result = backtest.run_backtest(persona_slug="p", notes=[], settings=settings, now=NOW)

        assert result.persona == "p"
        assert result.as_of == NOW
        assert result.benchmark == "SPY"
        assert result.call_count == 1
        assert result.caveat == backtest._CAVEAT

        by_days = {h.days: h for h in result.horizons}
        assert [h.days for h in result.horizons] == [5, 20, 60]

        five = by_days[5]
        assert five.n == 1
        assert five.mean_return_pct == pytest.approx(20.0)
        assert five.mean_benchmark_pct == pytest.approx(5.0)
        assert five.excess_pct == pytest.approx(15.0)
        assert five.win_rate_vs_benchmark == pytest.approx(1.0)

        # Horizons the call never completed have no qualifying data -- undefined, not zero.
        for days in (20, 60):
            stat = by_days[days]
            assert stat.n == 0
            assert stat.mean_return_pct is None
            assert stat.mean_benchmark_pct is None
            assert stat.excess_pct is None
            assert stat.win_rate_vs_benchmark is None


# ---------------------------------------------------------------------------
# Bearish call -- signed return is the negation of the raw symbol move
# ---------------------------------------------------------------------------


class TestBearishSignedReturn:
    def test_bearish_call_signed_and_beats_benchmark(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The symbol itself fell 15% (a good outcome for a bearish call); signed return is +15.0.
        call = _call(
            stance="bearish",
            horizons=[_horizon(5, -15.0, complete=True), _horizon(20, None, complete=False), _horizon(60, None, complete=False)],
        )
        _patch_score_calls(monkeypatch, _card([call]))
        _patch_ensure_series(monkeypatch, _SPY_5D_DOWN)  # SPY -3.0% over the same window

        result = backtest.run_backtest(persona_slug="p", notes=[], settings=settings, now=NOW)

        five = next(h for h in result.horizons if h.days == 5)
        assert five.n == 1
        assert five.mean_return_pct == pytest.approx(15.0)  # signed: -(-15.0)
        assert five.mean_benchmark_pct == pytest.approx(-3.0)
        assert five.excess_pct == pytest.approx(18.0)
        assert five.win_rate_vs_benchmark == pytest.approx(1.0)  # 15.0 > -3.0


# ---------------------------------------------------------------------------
# Benchmark window unavailable -> excluded from that horizon, warned, never zero
# ---------------------------------------------------------------------------


class TestBenchmarkWindowUnavailable:
    def test_excluded_from_horizon_and_warns(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The call's OWN 60-day horizon is complete (priced), but the fetched SPY series only
        # stretches 5 sessions past entry -- no SPY bar exists 60 sessions out.
        call = _call(
            stance="bullish",
            horizons=[
                _horizon(5, 20.0, complete=True),
                _horizon(20, 25.0, complete=True),
                _horizon(60, 30.0, complete=True),
            ],
        )
        _patch_score_calls(monkeypatch, _card([call]))
        _patch_ensure_series(monkeypatch, _SPY_5D_UP)  # only 6 bars -- 20d and 60d windows absent

        result = backtest.run_backtest(persona_slug="p", notes=[], settings=settings, now=NOW)

        by_days = {h.days: h for h in result.horizons}
        assert by_days[5].n == 1  # this one had a benchmark window
        assert by_days[20].n == 0
        assert by_days[20].mean_return_pct is None
        assert by_days[60].n == 0
        assert by_days[60].mean_return_pct is None

        assert any(
            w.source == "SPY" and "20-day" in w.reason for w in result.warnings
        )
        assert any(
            w.source == "SPY" and "60-day" in w.reason for w in result.warnings
        )
        # Never counted as a zero return: n stays 0, not 1 with a fabricated 0.0.
        assert by_days[20].excess_pct is None
        assert by_days[60].excess_pct is None

    def test_warning_dedupes_across_multiple_calls_at_same_horizon(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        call_a = _call(
            symbol="AAA", note_id="n1", horizons=[_horizon(60, 30.0, complete=True)]
        )
        call_b = _call(
            symbol="BBB", note_id="n2", horizons=[_horizon(60, 10.0, complete=True)]
        )
        _patch_score_calls(monkeypatch, _card([call_a, call_b]))
        _patch_ensure_series(monkeypatch, _SPY_5D_UP)

        result = backtest.run_backtest(persona_slug="p", notes=[], settings=settings, now=NOW)

        sixty_warnings = [w for w in result.warnings if w.source == "SPY" and "60-day" in w.reason]
        assert len(sixty_warnings) == 1  # deduped, not one per excluded call


# ---------------------------------------------------------------------------
# n == 0 -> every stat field is None, never 0.0
# ---------------------------------------------------------------------------


class TestNZeroIsNoneNotZero:
    def test_no_directional_calls_skips_spy_fetch_entirely(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Only a not_directional (neutral) call and a pending (no entry_date) call -- neither is
        # benchmarkable, so this must not even fetch SPY.
        neutral_call = _call(stance="neutral", horizons=())
        pending_call = _call(stance="bullish", entry_date=None, horizons=())
        _patch_score_calls(monkeypatch, _card([neutral_call, pending_call]))
        fake = _patch_ensure_series(monkeypatch, _SPY_5D_UP)

        result = backtest.run_backtest(persona_slug="p", notes=[], settings=settings, now=NOW)

        assert result.call_count == 0
        assert [h.days for h in result.horizons] == [5, 20, 60]
        for h in result.horizons:
            assert h.n == 0
            assert h.mean_return_pct is None
            assert h.mean_benchmark_pct is None
            assert h.excess_pct is None
            assert h.win_rate_vs_benchmark is None
        assert fake.calls == []  # no network/store call made

    def test_directional_call_with_no_complete_horizon_yields_none_stats(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Directional and priced (so SPY IS fetched, and call_count == 1), but every horizon is
        # still incomplete -- nothing qualifies for any aggregate.
        call = _call(
            stance="bullish",
            horizons=[
                _horizon(5, None, complete=False),
                _horizon(20, None, complete=False),
                _horizon(60, None, complete=False),
            ],
        )
        _patch_score_calls(monkeypatch, _card([call]))
        fake = _patch_ensure_series(monkeypatch, _SPY_5D_UP)

        result = backtest.run_backtest(persona_slug="p", notes=[], settings=settings, now=NOW)

        assert result.call_count == 1
        assert fake.calls  # SPY was fetched -- there was a directional, priced call
        for h in result.horizons:
            assert h.n == 0
            assert h.mean_return_pct is None
            assert h.win_rate_vs_benchmark is None


# ---------------------------------------------------------------------------
# SPY unfetchable -> every horizon empty, one warning, never a 5xx
# ---------------------------------------------------------------------------


class TestSpyUnfetchable:
    def test_provider_error_yields_empty_horizons_and_warning(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        call = _call(stance="bullish", horizons=[_horizon(5, 20.0, complete=True)])
        _patch_score_calls(monkeypatch, _card([call]))
        _patch_ensure_series(monkeypatch, ProviderUnavailable("network down", provider="yahoo"))

        result = backtest.run_backtest(persona_slug="p", notes=[], settings=settings, now=NOW)

        assert result.call_count == 1
        assert [h.days for h in result.horizons] == [5, 20, 60]
        for h in result.horizons:
            assert h.n == 0
            assert h.mean_return_pct is None
            assert h.mean_benchmark_pct is None
            assert h.excess_pct is None
            assert h.win_rate_vs_benchmark is None
        assert any(w.source == "SPY" for w in result.warnings)

    def test_empty_series_yields_empty_horizons_and_warning(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        call = _call(stance="bullish", horizons=[_horizon(5, 20.0, complete=True)])
        _patch_score_calls(monkeypatch, _card([call]))
        _patch_ensure_series(monkeypatch, _spy_series([]))

        result = backtest.run_backtest(persona_slug="p", notes=[], settings=settings, now=NOW)

        for h in result.horizons:
            assert h.n == 0
        assert any(w.source == "SPY" for w in result.warnings)

    def test_never_raises(self, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
        """The contract's always-200 rule: a provider failure must degrade, never propagate."""
        call = _call(stance="bullish", horizons=[_horizon(5, 20.0, complete=True)])
        _patch_score_calls(monkeypatch, _card([call]))
        _patch_ensure_series(monkeypatch, ProviderUnavailable("boom", provider="yahoo"))

        # Simply not raising is the assertion.
        backtest.run_backtest(persona_slug="p", notes=[], settings=settings, now=NOW)


# ---------------------------------------------------------------------------
# win_rate_vs_benchmark computation
# ---------------------------------------------------------------------------


class TestWinRate:
    def test_win_rate_is_fraction_beating_own_window_benchmark(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Three directional calls at the 5-day horizon: two beat SPY's +5.0%, one does not.
        winner_a = _call(symbol="AAA", note_id="n1", stance="bullish", horizons=[_horizon(5, 20.0, complete=True)])
        winner_b = _call(symbol="BBB", note_id="n2", stance="bullish", horizons=[_horizon(5, 10.0, complete=True)])
        loser = _call(symbol="CCC", note_id="n3", stance="bullish", horizons=[_horizon(5, 1.0, complete=True)])
        _patch_score_calls(monkeypatch, _card([winner_a, winner_b, loser]))
        _patch_ensure_series(monkeypatch, _SPY_5D_UP)  # SPY +5.0% over the same window

        result = backtest.run_backtest(persona_slug="p", notes=[], settings=settings, now=NOW)

        five = next(h for h in result.horizons if h.days == 5)
        assert five.n == 3
        assert five.win_rate_vs_benchmark == pytest.approx(2 / 3)
        assert five.mean_return_pct == pytest.approx((20.0 + 10.0 + 1.0) / 3)
        assert five.mean_benchmark_pct == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# call_count vs. per-horizon n
# ---------------------------------------------------------------------------


class TestCallCount:
    def test_call_count_is_every_directional_priced_call_not_sum_of_horizon_n(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        complete = _call(symbol="AAA", note_id="n1", horizons=[_horizon(5, 20.0, complete=True)])
        incomplete = _call(symbol="BBB", note_id="n2", horizons=[_horizon(5, None, complete=False)])
        _patch_score_calls(monkeypatch, _card([complete, incomplete]))
        _patch_ensure_series(monkeypatch, _SPY_5D_UP)

        result = backtest.run_backtest(persona_slug="p", notes=[], settings=settings, now=NOW)

        assert result.call_count == 2  # both directional and priced
        five = next(h for h in result.horizons if h.days == 5)
        assert five.n == 1  # only the completed one qualifies for the aggregate

    def test_not_directional_and_pending_excluded_from_call_count(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        neutral = _call(stance="neutral", horizons=())
        unclear = _call(stance="unclear", horizons=())
        pending = _call(stance="bearish", entry_date=None, horizons=())
        _patch_score_calls(monkeypatch, _card([neutral, unclear, pending]))
        _patch_ensure_series(monkeypatch, _SPY_5D_UP)

        result = backtest.run_backtest(persona_slug="p", notes=[], settings=settings, now=NOW)

        assert result.call_count == 0


# ---------------------------------------------------------------------------
# Warnings forwarded from score_calls
# ---------------------------------------------------------------------------


class TestWarningForwarding:
    def test_scoring_warnings_are_folded_into_backtest_warnings(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scoring_warning = DigestWarning(source="ZZZ", reason="no market data available")
        _patch_score_calls(monkeypatch, _card([], warnings=[scoring_warning]))
        _patch_ensure_series(monkeypatch, _SPY_5D_UP)

        result = backtest.run_backtest(persona_slug="p", notes=[], settings=settings, now=NOW)

        assert scoring_warning in result.warnings


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


class TestEnvelope:
    def test_default_now_defaults_to_current_time(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_score_calls(monkeypatch, _card([]))
        _patch_ensure_series(monkeypatch, _SPY_5D_UP)
        before = dt.datetime.now(UTC)

        result = backtest.run_backtest(persona_slug="p", notes=[], settings=settings)

        after = dt.datetime.now(UTC)
        assert before <= result.as_of <= after

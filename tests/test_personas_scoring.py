"""Tests for `app.personas.scoring.score_calls` -- see `docs/INFLUENCER-CONTRACT.md`, "Phase 3a --
call scoring (pinned)", for the semantics under test. Every test replaces `scoring.ensure_series`
with a fake so the suite never touches the network or a real bar store; `app.market.store.ensure_series`
is imported *by name* into `app.personas.scoring`'s namespace specifically so that patch point exists
(see that module's own import comment).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

import pytest

from app.config import Settings
from app.db.duck import Interval
from app.market.models import Bar, BarSeries, BarSource
from app.market.providers.base import ProviderUnavailable
from app.personas import scoring
from app.personas.models import EpisodicNote, TickerMention

UTC = dt.UTC


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _bar(day: dt.date, close: float, *, adj_close: float | None = None) -> Bar:
    return Bar(
        ts=dt.datetime(day.year, day.month, day.day, tzinfo=UTC),
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=adj_close,
    )


def _series(symbol: str, bars: Sequence[Bar]) -> BarSeries:
    return BarSeries(symbol=symbol, interval=Interval.DAY, source=BarSource.STORE, bars=list(bars))


def _note(
    *,
    note_id: str = "n1",
    published: dt.datetime | None,
    mentions: Sequence[TickerMention] = (),
    persona: str = "testpersona",
) -> EpisodicNote:
    return EpisodicNote(
        note_id=note_id,
        persona=persona,
        source_id="yt:UCXXXXXXXXXXXXXXXXXXXXXX",
        published=published,
        ingested_at=dt.datetime(2026, 1, 1, tzinfo=UTC),
        url=f"https://www.youtube.com/watch?v={note_id}",
        title="A title",
        kind="video_transcript",
        transcript_source="auto",
        lang="en",
        summary="a summary",
        themes=(),
        quotes=(),
        mentions=tuple(mentions),
        path=f"notes/{note_id}.md",
        degraded=False,
    )


def _mention(symbol: str, stance: str, reasoning: str = "because") -> TickerMention:
    return TickerMention(symbol=symbol, stance=stance, reasoning=reasoning)  # type: ignore[arg-type]


class _FakeEnsureSeries:
    """Records every call and answers from a fixed map: `BarSeries` to return, or an `Exception`
    instance to raise. Standing in for `app.market.store.ensure_series` in every test below."""

    def __init__(self, answers: dict[str, BarSeries | Exception]) -> None:
        self.answers = answers
        self.calls: list[str] = []

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
        self.calls.append(symbol)
        answer = self.answers[symbol]
        if isinstance(answer, Exception):
            raise answer
        return answer


def _patch(monkeypatch: pytest.MonkeyPatch, answers: dict[str, BarSeries | Exception]) -> _FakeEnsureSeries:
    fake = _FakeEnsureSeries(answers)
    monkeypatch.setattr(scoring, "ensure_series", fake)
    return fake


NOW = dt.datetime(2026, 2, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------


class TestOutcomes:
    def test_played_out_bullish_up(self, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
        bars = [_bar(dt.date(2026, 1, 5), 100.0), _bar(dt.date(2026, 1, 10), 110.0)]
        _patch(monkeypatch, {"AAA": _series("AAA", bars)})
        note = _note(published=dt.datetime(2026, 1, 5, tzinfo=UTC), mentions=[_mention("AAA", "bullish")])

        card = scoring.score_calls(persona_slug="p", notes=[note], settings=settings, now=NOW)

        assert len(card.scored_calls) == 1
        call = card.scored_calls[0]
        assert call.outcome == "played_out"
        assert call.return_pct == pytest.approx(10.0)
        assert call.entry_price == 100.0
        assert call.latest_price == 110.0
        assert card.played_out == 1
        assert card.directional_count == 1
        assert card.hit_rate == pytest.approx(1.0)

    def test_played_out_bearish_down(self, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
        bars = [_bar(dt.date(2026, 1, 5), 100.0), _bar(dt.date(2026, 1, 10), 90.0)]
        _patch(monkeypatch, {"BBB": _series("BBB", bars)})
        note = _note(published=dt.datetime(2026, 1, 5, tzinfo=UTC), mentions=[_mention("BBB", "bearish")])

        card = scoring.score_calls(persona_slug="p", notes=[note], settings=settings, now=NOW)

        call = card.scored_calls[0]
        assert call.outcome == "played_out"
        assert call.return_pct == pytest.approx(-10.0)

    def test_went_against_bullish_down(self, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
        bars = [_bar(dt.date(2026, 1, 5), 100.0), _bar(dt.date(2026, 1, 10), 90.0)]
        _patch(monkeypatch, {"CCC": _series("CCC", bars)})
        note = _note(published=dt.datetime(2026, 1, 5, tzinfo=UTC), mentions=[_mention("CCC", "bullish")])

        card = scoring.score_calls(persona_slug="p", notes=[note], settings=settings, now=NOW)

        assert card.scored_calls[0].outcome == "went_against"

    def test_went_against_bearish_up(self, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
        bars = [_bar(dt.date(2026, 1, 5), 100.0), _bar(dt.date(2026, 1, 10), 110.0)]
        _patch(monkeypatch, {"DDD": _series("DDD", bars)})
        note = _note(published=dt.datetime(2026, 1, 5, tzinfo=UTC), mentions=[_mention("DDD", "bearish")])

        card = scoring.score_calls(persona_slug="p", notes=[note], settings=settings, now=NOW)

        assert card.scored_calls[0].outcome == "went_against"

    def test_flat_band_boundary(self, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
        """`|return_pct| < 2.0` is flat; exactly `2.0` is not -- the band is a half-open interval."""
        just_under = [_bar(dt.date(2026, 1, 5), 100.0), _bar(dt.date(2026, 1, 10), 101.9)]
        exactly_at = [_bar(dt.date(2026, 1, 5), 100.0), _bar(dt.date(2026, 1, 10), 102.0)]
        _patch(monkeypatch, {"EEE": _series("EEE", just_under), "FFF": _series("FFF", exactly_at)})
        notes = [
            _note(
                note_id="n_flat", published=dt.datetime(2026, 1, 5, tzinfo=UTC),
                mentions=[_mention("EEE", "bullish")],
            ),
            _note(
                note_id="n_not_flat", published=dt.datetime(2026, 1, 5, tzinfo=UTC),
                mentions=[_mention("FFF", "bullish")],
            ),
        ]

        card = scoring.score_calls(persona_slug="p", notes=notes, settings=settings, now=NOW)

        by_symbol = {c.symbol: c for c in card.scored_calls}
        assert by_symbol["EEE"].outcome == "flat"
        assert by_symbol["FFF"].outcome == "played_out"

    def test_not_directional_still_fills_context(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bars = [_bar(dt.date(2026, 1, 5), 100.0), _bar(dt.date(2026, 1, 10), 110.0)]
        _patch(monkeypatch, {"GGG": _series("GGG", bars)})
        note = _note(published=dt.datetime(2026, 1, 5, tzinfo=UTC), mentions=[_mention("GGG", "unclear")])

        card = scoring.score_calls(persona_slug="p", notes=[note], settings=settings, now=NOW)

        call = card.scored_calls[0]
        assert call.outcome == "not_directional"
        # Still filled for context, per the contract -- not None.
        assert call.entry_price == 100.0
        assert call.latest_price == 110.0
        assert call.return_pct == pytest.approx(10.0)
        # Excluded from the hit-rate denominator.
        assert card.directional_count == 0
        assert card.hit_rate is None

    def test_pending_when_statement_after_last_bar(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bars = [_bar(dt.date(2026, 1, 2), 100.0), _bar(dt.date(2026, 1, 5), 105.0)]
        _patch(monkeypatch, {"HHH": _series("HHH", bars)})
        note = _note(published=dt.datetime(2026, 1, 10, tzinfo=UTC), mentions=[_mention("HHH", "bullish")])

        card = scoring.score_calls(persona_slug="p", notes=[note], settings=settings, now=NOW)

        call = card.scored_calls[0]
        assert call.outcome == "pending"
        assert call.entry_date is None
        assert call.entry_price is None
        assert call.latest_date is None
        assert call.latest_price is None
        assert call.return_pct is None
        assert call.basis is None
        assert card.directional_count == 0

    def test_no_data_when_provider_unavailable(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, {"III": ProviderUnavailable("network down", provider="yahoo")})
        note = _note(published=dt.datetime(2026, 1, 5, tzinfo=UTC), mentions=[_mention("III", "bullish")])

        card = scoring.score_calls(persona_slug="p", notes=[note], settings=settings, now=NOW)

        call = card.scored_calls[0]
        assert call.outcome == "no_data"
        assert call.entry_price is None
        assert call.return_pct is None
        assert any(w.source == "III" for w in card.warnings)

    def test_no_data_when_series_empty(self, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, {"JJJ": _series("JJJ", [])})
        note = _note(published=dt.datetime(2026, 1, 5, tzinfo=UTC), mentions=[_mention("JJJ", "bearish")])

        card = scoring.score_calls(persona_slug="p", notes=[note], settings=settings, now=NOW)

        call = card.scored_calls[0]
        assert call.outcome == "no_data"
        assert call.entry_price is None
        assert any(w.source == "JJJ" for w in card.warnings)


# ---------------------------------------------------------------------------
# The no-look-ahead entry rule
# ---------------------------------------------------------------------------


class TestEntryRule:
    def test_entry_is_first_bar_at_or_after_date_not_prior(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A Saturday upload must price against the following Monday's close, never Friday's --
        proving the rule looks forward for the first eligible bar rather than backward to the
        nearest one."""
        friday = dt.date(2026, 1, 2)
        monday = dt.date(2026, 1, 5)
        tuesday = dt.date(2026, 1, 6)
        bars = [_bar(friday, 100.0), _bar(monday, 200.0), _bar(tuesday, 210.0)]
        _patch(monkeypatch, {"KKK": _series("KKK", bars)})
        saturday = dt.date(2026, 1, 3)
        note = _note(
            published=dt.datetime(saturday.year, saturday.month, saturday.day, tzinfo=UTC),
            mentions=[_mention("KKK", "bullish")],
        )

        card = scoring.score_calls(persona_slug="p", notes=[note], settings=settings, now=NOW)

        call = card.scored_calls[0]
        assert call.entry_date is not None
        assert call.entry_date.date() == monday
        assert call.entry_price == 200.0  # not Friday's 100.0

    def test_one_fetch_per_symbol_across_multiple_notes(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bars = [_bar(dt.date(2026, 1, 2), 100.0), _bar(dt.date(2026, 1, 10), 105.0)]
        fake = _patch(monkeypatch, {"LLL": _series("LLL", bars)})
        notes = [
            _note(
                note_id="n1", published=dt.datetime(2026, 1, 3, tzinfo=UTC),
                mentions=[_mention("LLL", "bullish")],
            ),
            _note(
                note_id="n2", published=dt.datetime(2026, 1, 4, tzinfo=UTC),
                mentions=[_mention("LLL", "bearish")],
            ),
            _note(
                note_id="n3", published=dt.datetime(2026, 1, 5, tzinfo=UTC),
                mentions=[_mention("LLL", "unclear")],
            ),
        ]

        card = scoring.score_calls(persona_slug="p", notes=notes, settings=settings, now=NOW)

        assert fake.calls == ["LLL"]  # exactly one fetch despite three notes/calls on the symbol
        assert len(card.scored_calls) == 3


# ---------------------------------------------------------------------------
# Basis selection
# ---------------------------------------------------------------------------


class TestBasis:
    def test_uses_adjusted_when_both_endpoints_have_it(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bars = [
            _bar(dt.date(2026, 1, 5), 100.0, adj_close=90.0),
            _bar(dt.date(2026, 1, 10), 110.0, adj_close=99.0),
        ]
        _patch(monkeypatch, {"MMM": _series("MMM", bars)})
        note = _note(published=dt.datetime(2026, 1, 5, tzinfo=UTC), mentions=[_mention("MMM", "bullish")])

        card = scoring.score_calls(persona_slug="p", notes=[note], settings=settings, now=NOW)

        call = card.scored_calls[0]
        assert call.basis == "adjusted"
        assert call.entry_price == 90.0
        assert call.latest_price == 99.0
        assert call.return_pct == pytest.approx(10.0)

    def test_falls_back_to_close_when_either_endpoint_lacks_adjusted(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bars = [
            _bar(dt.date(2026, 1, 5), 100.0, adj_close=90.0),
            _bar(dt.date(2026, 1, 10), 110.0, adj_close=None),  # latest bar lacks adj_close
        ]
        _patch(monkeypatch, {"NNN": _series("NNN", bars)})
        note = _note(published=dt.datetime(2026, 1, 5, tzinfo=UTC), mentions=[_mention("NNN", "bullish")])

        card = scoring.score_calls(persona_slug="p", notes=[note], settings=settings, now=NOW)

        call = card.scored_calls[0]
        assert call.basis == "close"
        assert call.entry_price == 100.0
        assert call.latest_price == 110.0


# ---------------------------------------------------------------------------
# Null published -> warning, never guessed
# ---------------------------------------------------------------------------


class TestNullPublished:
    def test_warns_and_skips_when_published_is_none(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, {})  # ensure_series must never even be called
        note = _note(published=None, mentions=[_mention("OOO", "bullish")])

        card = scoring.score_calls(persona_slug="p", notes=[note], settings=settings, now=NOW)

        assert card.scored_calls == ()
        assert len(card.warnings) == 1
        assert card.warnings[0].source == "OOO"
        assert card.warnings[0].reason == "no published date"

    def test_dedups_repeated_warning_across_notes(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, {})
        notes = [
            _note(note_id="n1", published=None, mentions=[_mention("PPP", "bullish")]),
            _note(note_id="n2", published=None, mentions=[_mention("PPP", "bearish")]),
        ]

        card = scoring.score_calls(persona_slug="p", notes=notes, settings=settings, now=NOW)

        assert len(card.warnings) == 1
        assert card.warnings[0].source == "PPP"


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------


class TestAggregates:
    def test_hit_rate_none_when_zero_directional_calls(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bars = [_bar(dt.date(2026, 1, 2), 100.0), _bar(dt.date(2026, 1, 10), 105.0)]
        _patch(monkeypatch, {"QQQ": _series("QQQ", bars)})
        # Only a not_directional call and a pending call -- neither counts toward the denominator.
        notes = [
            _note(
                note_id="n1", published=dt.datetime(2026, 1, 3, tzinfo=UTC),
                mentions=[_mention("QQQ", "neutral")],
            ),
            _note(
                note_id="n2", published=dt.datetime(2026, 1, 20, tzinfo=UTC),
                mentions=[_mention("QQQ", "bullish")],
            ),
        ]

        card = scoring.score_calls(persona_slug="p", notes=notes, settings=settings, now=NOW)

        assert card.directional_count == 0
        assert card.played_out == 0
        assert card.hit_rate is None
        assert card.median_return_pct is None

    def test_median_return_is_signed_by_stance(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Three directional, priced calls with known signed returns: 10, -20 (bearish, so signed
        # +20), and 5 -- median of [10, 20, 5] sorted [5, 10, 20] is 10.
        bars_a = [_bar(dt.date(2026, 1, 5), 100.0), _bar(dt.date(2026, 1, 10), 110.0)]  # bullish +10
        bars_b = [_bar(dt.date(2026, 1, 5), 100.0), _bar(dt.date(2026, 1, 10), 80.0)]  # bearish -20 -> +20 signed
        bars_c = [_bar(dt.date(2026, 1, 5), 100.0), _bar(dt.date(2026, 1, 10), 105.0)]  # bullish +5
        _patch(
            monkeypatch,
            {"RRR": _series("RRR", bars_a), "SSS": _series("SSS", bars_b), "TTT": _series("TTT", bars_c)},
        )
        notes = [
            _note(
                note_id="n1", published=dt.datetime(2026, 1, 5, tzinfo=UTC),
                mentions=[_mention("RRR", "bullish")],
            ),
            _note(
                note_id="n2", published=dt.datetime(2026, 1, 5, tzinfo=UTC),
                mentions=[_mention("SSS", "bearish")],
            ),
            _note(
                note_id="n3", published=dt.datetime(2026, 1, 5, tzinfo=UTC),
                mentions=[_mention("TTT", "bullish")],
            ),
        ]

        card = scoring.score_calls(persona_slug="p", notes=notes, settings=settings, now=NOW)

        assert card.directional_count == 3
        assert card.median_return_pct == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


class TestHorizons:
    """Phase 3b -- fixed horizons (5/20/60 trading days after entry). See
    `docs/INFLUENCER-CONTRACT.md`, "Fixed-horizon scoring", for the semantics under test."""

    def test_complete_5d_horizon_bullish_played_out(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Entry is the first bar (index 0); the 5th bar after it (index 5) is the 5-day horizon bar.
        # 20 and 60 days out do not exist yet in this 6-bar series -- incomplete.
        bars = [
            _bar(dt.date(2026, 1, 5), 100.0),   # entry, index 0
            _bar(dt.date(2026, 1, 6), 101.0),
            _bar(dt.date(2026, 1, 7), 102.0),
            _bar(dt.date(2026, 1, 8), 103.0),
            _bar(dt.date(2026, 1, 9), 104.0),
            _bar(dt.date(2026, 1, 12), 120.0),  # index 5 -> the 5-day horizon bar
        ]
        _patch(monkeypatch, {"VVV": _series("VVV", bars)})
        note = _note(published=dt.datetime(2026, 1, 5, tzinfo=UTC), mentions=[_mention("VVV", "bullish")])

        card = scoring.score_calls(persona_slug="p", notes=[note], settings=settings, now=NOW)

        call = card.scored_calls[0]
        assert [h.days for h in call.horizons] == list(scoring.DEFAULT_HORIZONS)
        by_days = {h.days: h for h in call.horizons}
        assert by_days[5].complete is True
        assert by_days[5].return_pct == pytest.approx(20.0)
        assert by_days[20].complete is False
        assert by_days[20].return_pct is None
        assert by_days[60].complete is False
        assert by_days[60].return_pct is None

    def test_incomplete_horizon_near_end_of_series(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Entry near the end of the stored series -- fewer than 5 bars exist after it, so even the
        shortest horizon is incomplete. Never extrapolated."""
        bars = [
            _bar(dt.date(2026, 1, 5), 100.0),  # entry, index 0
            _bar(dt.date(2026, 1, 6), 101.0),
            _bar(dt.date(2026, 1, 7), 102.0),
        ]
        _patch(monkeypatch, {"WWW": _series("WWW", bars)})
        note = _note(published=dt.datetime(2026, 1, 5, tzinfo=UTC), mentions=[_mention("WWW", "bullish")])

        card = scoring.score_calls(persona_slug="p", notes=[note], settings=settings, now=NOW)

        call = card.scored_calls[0]
        assert len(call.horizons) == 3
        for horizon in call.horizons:
            assert horizon.complete is False
            assert horizon.return_pct is None

    def test_horizons_empty_for_pending_and_no_data(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bars = [_bar(dt.date(2026, 1, 2), 100.0), _bar(dt.date(2026, 1, 5), 105.0)]
        _patch(
            monkeypatch,
            {
                "XXX": _series("XXX", bars),  # pending: said_on after the last bar
                "YYY": _series("YYY", []),    # no_data: empty series
            },
        )
        notes = [
            _note(
                note_id="n_pending", published=dt.datetime(2026, 1, 10, tzinfo=UTC),
                mentions=[_mention("XXX", "bullish")],
            ),
            _note(
                note_id="n_no_data", published=dt.datetime(2026, 1, 5, tzinfo=UTC),
                mentions=[_mention("YYY", "bearish")],
            ),
        ]

        card = scoring.score_calls(persona_slug="p", notes=notes, settings=settings, now=NOW)

        by_symbol = {c.symbol: c for c in card.scored_calls}
        assert by_symbol["XXX"].outcome == "pending"
        assert by_symbol["XXX"].horizons == ()
        assert by_symbol["YYY"].outcome == "no_data"
        assert by_symbol["YYY"].horizons == ()

    def test_horizon_stats_hit_rate_and_median_signed(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Three symbols, each priced so their 5-day horizon is complete (6 bars, entry at index 0):
        # ZZ1 bullish +20 (played_out), ZZ2 bearish -20 -> signed +20 (played_out),
        # ZZ3 bullish -20 (went_against). Signed returns at day 5: [20, 20, -20] -> median 20.0.
        # None of these series has 20 or 60 bars after entry, so those horizons stay directional_count 0.
        def _mk(prices: Sequence[float]) -> list[Bar]:
            days = [dt.date(2026, 1, d) for d in (5, 6, 7, 8, 9, 12)]
            return [_bar(d, p) for d, p in zip(days, prices, strict=True)]

        _patch(
            monkeypatch,
            {
                "ZZ1": _series("ZZ1", _mk([100.0, 101.0, 102.0, 103.0, 104.0, 120.0])),  # +20
                "ZZ2": _series("ZZ2", _mk([100.0, 99.0, 98.0, 97.0, 96.0, 80.0])),        # -20
                "ZZ3": _series("ZZ3", _mk([100.0, 99.0, 98.0, 97.0, 96.0, 80.0])),        # -20
            },
        )
        notes = [
            _note(
                note_id="n1", published=dt.datetime(2026, 1, 5, tzinfo=UTC),
                mentions=[_mention("ZZ1", "bullish")],
            ),
            _note(
                note_id="n2", published=dt.datetime(2026, 1, 5, tzinfo=UTC),
                mentions=[_mention("ZZ2", "bearish")],
            ),
            _note(
                note_id="n3", published=dt.datetime(2026, 1, 5, tzinfo=UTC),
                mentions=[_mention("ZZ3", "bullish")],
            ),
        ]

        card = scoring.score_calls(persona_slug="p", notes=notes, settings=settings, now=NOW)

        stats_by_days = {s.days: s for s in card.horizon_stats}
        assert [s.days for s in card.horizon_stats] == list(scoring.DEFAULT_HORIZONS)

        five = stats_by_days[5]
        assert five.directional_count == 3
        assert five.played_out == 2  # ZZ1 and ZZ2; ZZ3 went against
        assert five.hit_rate == pytest.approx(2 / 3)
        assert five.median_return_pct == pytest.approx(20.0)

        # No series has bars 20/60 sessions past entry -- zero complete directional calls there.
        twenty = stats_by_days[20]
        assert twenty.directional_count == 0
        assert twenty.played_out == 0
        assert twenty.hit_rate is None
        assert twenty.median_return_pct is None
        sixty = stats_by_days[60]
        assert sixty.directional_count == 0
        assert sixty.hit_rate is None
        assert sixty.median_return_pct is None

    def test_horizon_stats_excludes_not_directional(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bars = [
            _bar(dt.date(2026, 1, 5), 100.0),
            _bar(dt.date(2026, 1, 6), 101.0),
            _bar(dt.date(2026, 1, 7), 102.0),
            _bar(dt.date(2026, 1, 8), 103.0),
            _bar(dt.date(2026, 1, 9), 104.0),
            _bar(dt.date(2026, 1, 12), 120.0),
        ]
        _patch(monkeypatch, {"AB1": _series("AB1", bars)})
        note = _note(published=dt.datetime(2026, 1, 5, tzinfo=UTC), mentions=[_mention("AB1", "neutral")])

        card = scoring.score_calls(persona_slug="p", notes=[note], settings=settings, now=NOW)

        five = next(s for s in card.horizon_stats if s.days == 5)
        assert five.directional_count == 0
        assert five.hit_rate is None
        assert five.median_return_pct is None

    def test_custom_horizons_parameter(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`horizons` is overridable -- callers are not stuck with the module default."""
        bars = [
            _bar(dt.date(2026, 1, 5), 100.0),
            _bar(dt.date(2026, 1, 6), 101.0),
            _bar(dt.date(2026, 1, 7), 110.0),
        ]
        _patch(monkeypatch, {"AC1": _series("AC1", bars)})
        note = _note(published=dt.datetime(2026, 1, 5, tzinfo=UTC), mentions=[_mention("AC1", "bullish")])

        card = scoring.score_calls(
            persona_slug="p", notes=[note], settings=settings, now=NOW, horizons=(2,)
        )

        call = card.scored_calls[0]
        assert [h.days for h in call.horizons] == [2]
        assert call.horizons[0].complete is True
        assert call.horizons[0].return_pct == pytest.approx(10.0)
        assert [s.days for s in card.horizon_stats] == [2]


class TestEnvelope:
    def test_empty_notes_yields_empty_scorecard(self, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, {})

        card = scoring.score_calls(persona_slug="nobody", notes=[], settings=settings, now=NOW)

        assert card.persona == "nobody"
        assert card.as_of == NOW
        assert card.scored_calls == ()
        assert card.directional_count == 0
        assert card.played_out == 0
        assert card.hit_rate is None
        assert card.median_return_pct is None
        assert card.warnings == ()
        # A zero-directional scorecard reports its hit-rate CI as the honest n=0 estimate, not None
        # papered over as a special case -- consistent with `hit_rate` itself being None.
        assert card.hit_rate_ci is not None
        assert card.hit_rate_ci.n == 0
        assert card.hit_rate_ci.point is None

    def test_scored_calls_ordered_newest_said_on_first(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bars_u = [_bar(dt.date(2026, 1, 1), 100.0), _bar(dt.date(2026, 1, 20), 100.0)]
        _patch(monkeypatch, {"UUU": _series("UUU", bars_u)})
        notes = [
            _note(
                note_id="old", published=dt.datetime(2026, 1, 2, tzinfo=UTC),
                mentions=[_mention("UUU", "neutral")],
            ),
            _note(
                note_id="new", published=dt.datetime(2026, 1, 10, tzinfo=UTC),
                mentions=[_mention("UUU", "neutral")],
            ),
        ]

        card = scoring.score_calls(persona_slug="p", notes=notes, settings=settings, now=NOW)

        assert [c.note_id for c in card.scored_calls] == ["new", "old"]

    def test_default_now_defaults_to_current_time(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, {})
        before = dt.datetime.now(UTC)

        card = scoring.score_calls(persona_slug="p", notes=[], settings=settings)

        after = dt.datetime.now(UTC)
        assert before <= card.as_of <= after


# ---------------------------------------------------------------------------
# Confidence intervals -- `PersonaScorecard.hit_rate_ci` and `HorizonStat.{mean_return_pct,
# hit_rate_ci, return_ci}`. Purely additive: none of these change the point values asserted above.
# ---------------------------------------------------------------------------


class TestConfidenceIntervals:
    def test_top_level_hit_rate_ci_matches_point_and_n(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bars_a = [_bar(dt.date(2026, 1, 5), 100.0), _bar(dt.date(2026, 1, 10), 110.0)]  # bullish +10, hit
        bars_b = [_bar(dt.date(2026, 1, 5), 100.0), _bar(dt.date(2026, 1, 10), 90.0)]  # bullish -10, miss
        _patch(monkeypatch, {"CI1": _series("CI1", bars_a), "CI2": _series("CI2", bars_b)})
        notes = [
            _note(
                note_id="n1", published=dt.datetime(2026, 1, 5, tzinfo=UTC),
                mentions=[_mention("CI1", "bullish")],
            ),
            _note(
                note_id="n2", published=dt.datetime(2026, 1, 5, tzinfo=UTC),
                mentions=[_mention("CI2", "bullish")],
            ),
        ]

        card = scoring.score_calls(persona_slug="p", notes=notes, settings=settings, now=NOW)

        assert card.directional_count == 2
        assert card.hit_rate == pytest.approx(0.5)
        assert card.hit_rate_ci is not None
        assert card.hit_rate_ci.method == "wilson"
        assert card.hit_rate_ci.n == card.directional_count
        assert card.hit_rate_ci.point == pytest.approx(card.hit_rate)
        # A 90% Wilson interval must bracket its own point estimate.
        assert card.hit_rate_ci.low is not None and card.hit_rate_ci.high is not None
        assert card.hit_rate_ci.low <= card.hit_rate_ci.point <= card.hit_rate_ci.high

    def test_horizon_mean_return_and_return_ci_populated(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Reuse the 5-day-horizon fixture shape: entry at index 0, horizon bar at index 5.
        def _mk(prices: Sequence[float]) -> list[Bar]:
            days = [dt.date(2026, 1, d) for d in (5, 6, 7, 8, 9, 12)]
            return [_bar(d, p) for d, p in zip(days, prices, strict=True)]

        _patch(
            monkeypatch,
            {
                "CI3": _series("CI3", _mk([100.0, 101.0, 102.0, 103.0, 104.0, 120.0])),  # +20
                "CI4": _series("CI4", _mk([100.0, 99.0, 98.0, 97.0, 96.0, 80.0])),  # -20
            },
        )
        notes = [
            _note(
                note_id="n1", published=dt.datetime(2026, 1, 5, tzinfo=UTC),
                mentions=[_mention("CI3", "bullish")],
            ),
            _note(
                note_id="n2", published=dt.datetime(2026, 1, 5, tzinfo=UTC),
                mentions=[_mention("CI4", "bearish")],  # signed return +20 too
            ),
        ]

        card = scoring.score_calls(persona_slug="p", notes=notes, settings=settings, now=NOW)

        five = next(s for s in card.horizon_stats if s.days == 5)
        assert five.directional_count == 2
        assert five.mean_return_pct == pytest.approx(20.0)
        assert five.hit_rate_ci is not None
        assert five.hit_rate_ci.method == "wilson"
        assert five.hit_rate_ci.n == five.directional_count
        assert five.hit_rate_ci.point == pytest.approx(five.hit_rate)
        assert five.return_ci is not None
        assert five.return_ci.method == "bootstrap"
        assert five.return_ci.n == five.directional_count
        assert five.return_ci.point == pytest.approx(five.mean_return_pct)
        assert five.return_ci.low is not None and five.return_ci.high is not None
        assert five.return_ci.low <= five.return_ci.point <= five.return_ci.high

    def test_zero_directional_horizon_ci_is_n_zero_not_crash(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bars = [
            _bar(dt.date(2026, 1, 5), 100.0),
            _bar(dt.date(2026, 1, 6), 101.0),
            _bar(dt.date(2026, 1, 7), 102.0),
            _bar(dt.date(2026, 1, 8), 103.0),
            _bar(dt.date(2026, 1, 9), 104.0),
            _bar(dt.date(2026, 1, 12), 120.0),
        ]
        _patch(monkeypatch, {"CI5": _series("CI5", bars)})
        note = _note(published=dt.datetime(2026, 1, 5, tzinfo=UTC), mentions=[_mention("CI5", "neutral")])

        card = scoring.score_calls(persona_slug="p", notes=[note], settings=settings, now=NOW)

        five = next(s for s in card.horizon_stats if s.days == 5)
        assert five.directional_count == 0
        assert five.mean_return_pct is None
        assert five.hit_rate_ci is not None
        assert five.hit_rate_ci.n == 0
        assert five.hit_rate_ci.point is None
        assert five.return_ci is not None
        assert five.return_ci.n == 0
        assert five.return_ci.point is None

    def test_zero_directional_scorecard_hit_rate_ci_none_or_n_zero(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Per the model's own discipline, a scorecard with no directional calls reports its hit-rate
        CI either as `None` or as the honest n=0 estimate -- never a fabricated point value."""
        _patch(monkeypatch, {})
        note = _note(published=None, mentions=[_mention("CI6", "bullish")])

        card = scoring.score_calls(persona_slug="p", notes=[note], settings=settings, now=NOW)

        assert card.directional_count == 0
        assert card.hit_rate is None
        if card.hit_rate_ci is not None:
            assert card.hit_rate_ci.n == 0
            assert card.hit_rate_ci.point is None

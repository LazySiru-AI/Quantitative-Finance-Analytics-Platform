"""Unit tests for `app.personas.retrieval.select_notes` -- the bilingual lexical (tf-idf) ranker.

Every `EpisodicNote` here is built inline with a deterministic `_note` helper (adapted from
`tests/test_personas_ask.py`'s own `_note`), never read from the live vault, so results do not depend
on what has actually been ingested.
"""

from __future__ import annotations

import datetime as dt

from app.personas.models import (
    EpisodicNote,
    PersonaProfile,
    ProfileClaim,
    RegimeView,
    TickerMention,
)
from app.personas.retrieval import DEFAULT_CAP, select_notes

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _note(
    note_id: str,
    *,
    persona: str = "creator-a",
    published: dt.datetime | None = None,
    ingested_at: dt.datetime | None = None,
    title: str | None = "A video",
    summary: str = "A summary.",
    themes: tuple[str, ...] = (),
    quotes: tuple[str, ...] = (),
    mentions: tuple[TickerMention, ...] = (),
) -> EpisodicNote:
    return EpisodicNote(
        note_id=note_id,
        persona=persona,
        source_id="yt:UC1",
        published=published,
        ingested_at=ingested_at or dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        url=f"https://example.com/{note_id}",
        title=title,
        kind="video_transcript",
        transcript_source="auto",
        lang="en",
        summary=summary,
        themes=themes,
        quotes=quotes,
        mentions=mentions,
        path=f"notes/{note_id}.md",
        degraded=False,
    )


def _mention(symbol: str, reasoning: str = "reasoning") -> TickerMention:
    return TickerMention(symbol=symbol, stance="bullish", reasoning=reasoning)


def _profile(**overrides: object) -> PersonaProfile:
    fields: dict[str, object] = dict(
        persona="creator-a",
        version=1,
        consolidated_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        note_count=3,
        summary="Trades momentum names.",
        beliefs=(),
        playbook=(),
        methodology=(),
        vocabulary=(),
        path="profile.md",
    )
    fields.update(overrides)
    return PersonaProfile(**fields)  # type: ignore[arg-type]


def _ts(day: int) -> dt.datetime:
    return dt.datetime(2026, 1, day, tzinfo=dt.UTC)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmpty:
    def test_no_notes_returns_empty_tuple(self) -> None:
        assert select_notes((), "anything", symbol=None, profile=None) == ()


class TestEnglishRelevance:
    def test_bollinger_notes_rank_in_top_three(self) -> None:
        bollinger_a = _note(
            "bb-1",
            published=_ts(1),
            summary="I use Bollinger bands to time entries on breakouts.",
            themes=("bollinger bands", "breakout timing"),
        )
        bollinger_b = _note(
            "bb-2",
            published=_ts(2),
            summary="Reviewing my Bollinger band settings and how I read the bands on daily charts.",
            themes=("bollinger bands",),
        )
        macro_1 = _note("macro-1", published=_ts(3), summary="The Fed held rates steady this week.")
        macro_2 = _note("macro-2", published=_ts(4), summary="Unemployment data came in soft today.")
        macro_3 = _note("macro-3", published=_ts(5), summary="Oil prices dropped on supply news.")

        notes = (bollinger_a, bollinger_b, macro_1, macro_2, macro_3)
        result = select_notes(
            notes, "which bollinger bands do you use", symbol=None, profile=None, cap=3
        )
        top_ids = {n.note_id for n in result[:3]}
        assert {"bb-1", "bb-2"} <= top_ids


class TestKoreanRelevance:
    def test_bigram_overlap_ranks_korean_notes_in_top_three(self) -> None:
        bollinger_a = _note(
            "kbb-1",
            published=_ts(1),
            summary="이번엔 볼린저 밴드를 활용한 진입 전략을 설명합니다.",
            themes=("볼린저 밴드",),
        )
        bollinger_b = _note(
            "kbb-2",
            published=_ts(2),
            summary="볼린저 밴드 설정을 어떻게 바꾸었는지 공유해드립니다.",
            themes=("볼린저 밴드",),
        )
        macro_1 = _note("kmacro-1", published=_ts(3), summary="오늘 금리 동결 소식입니다.")
        macro_2 = _note("kmacro-2", published=_ts(4), summary="실업률 지표가 발표되었습니다.")
        macro_3 = _note("kmacro-3", published=_ts(5), summary="유가 하락 소식입니다.")

        notes = (bollinger_a, bollinger_b, macro_1, macro_2, macro_3)
        result = select_notes(
            notes, "볼린저 밴드 전략", symbol=None, profile=None, cap=3
        )
        top_ids = {n.note_id for n in result[:3]}
        assert {"kbb-1", "kbb-2"} <= top_ids


class TestTenYearYieldProbe:
    def test_yield_notes_outrank_unrelated_notes(self) -> None:
        yield_a = _note(
            "yield-1",
            published=_ts(1),
            summary="How I read the 10-year yield when it moves fast.",
            themes=("10-year yield",),
        )
        yield_b = _note(
            "yield-2",
            published=_ts(2),
            summary="국채 금리 가 오를 때 내 포지션을 어떻게 바꾸는지 설명합니다.",
            themes=("국채 금리",),
        )
        unrelated_1 = _note("u1", published=_ts(3), summary="Earnings season picks for semis.")
        unrelated_2 = _note("u2", published=_ts(4), summary="A new coffee shop I visited today.")

        notes = (yield_a, yield_b, unrelated_1, unrelated_2)
        result = select_notes(
            notes, "how do you read the 10-year yield", symbol=None, profile=None
        )
        # yield_a shares real lexical overlap; it must rank above both unrelated notes.
        ranked_ids = [n.note_id for n in result]
        assert ranked_ids.index("yield-1") < ranked_ids.index("u1")
        assert ranked_ids.index("yield-1") < ranked_ids.index("u2")


class TestSymbolBoost:
    def test_symbol_match_ranks_first_despite_lower_lexical_overlap(self) -> None:
        nvda_note = _note(
            "nvda-1",
            published=_ts(1),
            summary="Quick update, nothing major.",
            mentions=(_mention("NVDA", "Bullish on NVDA into earnings."),),
        )
        lexical_note = _note(
            "lex-1",
            published=_ts(2),
            summary="Bullish momentum bullish setup bullish breakout bullish trend bullish stock.",
        )

        result = select_notes(
            (nvda_note, lexical_note), "bullish momentum setup", symbol="NVDA", profile=None
        )
        assert result[0].note_id == "nvda-1"


class TestProfileCitationBoost:
    def test_cited_note_ranks_above_equally_scored_uncited_note(self) -> None:
        cited = _note(
            "cited-1",
            published=_ts(1),
            summary="Discussion of trading tools generally.",
        )
        uncited = _note(
            "uncited-1",
            published=_ts(1),
            summary="Discussion of trading tools generally.",
        )
        profile = _profile(
            methodology=(
                ProfileClaim(text="Uses RSI and moving averages as core indicators.", citations=("cited-1",)),
            ),
        )

        result = select_notes(
            (cited, uncited),
            "what indicators do you use",
            symbol=None,
            profile=profile,
        )
        assert result[0].note_id == "cited-1"

    def test_regime_citation_boost(self) -> None:
        cited = _note("regime-cited", published=_ts(1), summary="Some notes about the market.")
        uncited = _note("regime-uncited", published=_ts(1), summary="Some notes about the market.")
        profile = _profile(
            regime=RegimeView(
                risk="off",
                summary="Risk off given rate uncertainty.",
                citations=("regime-cited",),
                has_signal=True,
            ),
        )

        result = select_notes(
            (cited, uncited),
            "what is your current risk posture",
            symbol=None,
            profile=profile,
        )
        assert result[0].note_id == "regime-cited"


class TestUninformativeQuestionFallsBackToRecency:
    def test_falls_back_to_recency(self) -> None:
        older = _note("old", published=_ts(1), summary="Some content here.")
        newer = _note("new", published=_ts(5), summary="Some other content here.")
        result = select_notes((older, newer), "and then?", symbol=None, profile=None)
        assert result[0].note_id == "new"
        assert result[1].note_id == "old"

    def test_empty_question_falls_back_to_recency(self) -> None:
        older = _note("old2", published=_ts(1), summary="Text.")
        newer = _note("new2", published=_ts(5), summary="Text.")
        result = select_notes((older, newer), "", symbol=None, profile=None)
        assert result[0].note_id == "new2"


class TestCharBudget:
    def test_stops_before_exceeding_budget_but_returns_at_least_one(self) -> None:
        huge = _note("huge", published=_ts(1), summary="x" * 100)
        second = _note("second", published=_ts(2), summary="y" * 100)
        result = select_notes(
            (huge, second), "and then?", symbol=None, profile=None, char_budget=10
        )
        assert len(result) == 1

    def test_multiple_notes_fit_within_budget(self) -> None:
        a = _note("a", published=_ts(1), summary="x" * 10)
        b = _note("b", published=_ts(2), summary="y" * 10)
        c = _note("c", published=_ts(3), summary="z" * 10)
        result = select_notes(
            (a, b, c), "and then?", symbol=None, profile=None, char_budget=25
        )
        # newest-first recency fallback: c (10) + b (10) = 20 <= 25, + a would be 30 > 25
        assert [n.note_id for n in result] == ["c", "b"]


class TestCap:
    def test_cap_is_never_exceeded(self) -> None:
        notes = tuple(
            _note(f"n{i}", published=_ts(i + 1), summary="text") for i in range(DEFAULT_CAP + 10)
        )
        result = select_notes(notes, "and then?", symbol=None, profile=None)
        assert len(result) <= DEFAULT_CAP

    def test_explicit_cap_respected(self) -> None:
        notes = tuple(_note(f"m{i}", published=_ts(i + 1), summary="text") for i in range(10))
        result = select_notes(notes, "and then?", symbol=None, profile=None, cap=3)
        assert len(result) <= 3


class TestNeverRaises:
    def test_note_with_all_empty_text_is_allowed(self) -> None:
        blank = _note("blank", title=None, summary="", themes=(), quotes=(), mentions=())
        result = select_notes((blank,), "anything at all", symbol=None, profile=None)
        assert result == (blank,)

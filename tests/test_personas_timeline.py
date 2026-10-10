"""Tests for `app.personas.timeline.build_timeline` -- see `docs/INFLUENCER-CONTRACT.md`,
"Chronological view (new)" under "Phase 3b", for the semantics under test. `build_timeline` is pure
(no I/O, no model call), so every test here builds `EpisodicNote`s in memory and asserts on the
returned `PersonaTimeline` directly -- no network, no fixtures, no patching.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from app.personas.models import EpisodicNote, TickerMention
from app.personas.timeline import build_timeline

UTC = dt.UTC


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _note(
    *,
    note_id: str = "n1",
    published: dt.datetime | None,
    ingested_at: dt.datetime = dt.datetime(2026, 1, 1, tzinfo=UTC),
    mentions: Sequence[TickerMention] = (),
    persona: str = "testpersona",
    title: str | None = "A title",
    summary: str = "a summary",
    themes: Sequence[str] = (),
) -> EpisodicNote:
    return EpisodicNote(
        note_id=note_id,
        persona=persona,
        source_id="yt:UCXXXXXXXXXXXXXXXXXXXXXX",
        published=published,
        ingested_at=ingested_at,
        url=f"https://www.youtube.com/watch?v={note_id}",
        title=title,
        kind="video_transcript",
        transcript_source="auto",
        lang="en",
        summary=summary,
        themes=tuple(themes),
        quotes=(),
        mentions=tuple(mentions),
        path=f"notes/{note_id}.md",
        degraded=False,
    )


def _mention(symbol: str, stance: str, reasoning: str = "because") -> TickerMention:
    return TickerMention(symbol=symbol, stance=stance, reasoning=reasoning)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# entries
# ---------------------------------------------------------------------------


def test_empty_notes_yields_empty_timeline() -> None:
    result = build_timeline(persona_slug="testpersona", notes=())
    assert result.persona == "testpersona"
    assert result.entries == ()
    assert result.stance_timelines == ()


def test_entries_are_newest_first_by_published() -> None:
    old = _note(note_id="n-old", published=dt.datetime(2026, 1, 1, tzinfo=UTC))
    mid = _note(note_id="n-mid", published=dt.datetime(2026, 2, 1, tzinfo=UTC))
    new = _note(note_id="n-new", published=dt.datetime(2026, 3, 1, tzinfo=UTC))

    result = build_timeline(persona_slug="p", notes=[old, new, mid])

    assert [e.note_id for e in result.entries] == ["n-new", "n-mid", "n-old"]


def test_entry_carries_note_fields_and_dedupes_symbols_in_mention_order() -> None:
    note = _note(
        note_id="n1",
        published=dt.datetime(2026, 1, 5, tzinfo=UTC),
        title="Semis update",
        summary="talked about chips",
        themes=("semis", "rates"),
        mentions=[
            _mention("NVDA", "bullish"),
            _mention("AMD", "bearish"),
            _mention("NVDA", "bullish"),  # repeat -- must not duplicate in symbols
        ],
    )

    result = build_timeline(persona_slug="p", notes=[note])

    assert len(result.entries) == 1
    entry = result.entries[0]
    assert entry.note_id == "n1"
    assert entry.published == dt.datetime(2026, 1, 5, tzinfo=UTC)
    assert entry.title == "Semis update"
    assert entry.summary == "talked about chips"
    assert entry.themes == ("semis", "rates")
    assert entry.symbols == ("NVDA", "AMD")
    assert entry.url == note.url


def test_note_with_no_published_date_orders_by_ingested_at_and_is_not_dropped() -> None:
    dated = _note(
        note_id="n-dated",
        published=dt.datetime(2026, 1, 10, tzinfo=UTC),
        ingested_at=dt.datetime(2026, 1, 11, tzinfo=UTC),
    )
    # No published date (upstream could not tell us), but ingested well after `dated` -- it should
    # sort newer than `dated` using ingested_at, and its own `published` must stay None on the entry.
    undated = _note(
        note_id="n-undated",
        published=None,
        ingested_at=dt.datetime(2026, 1, 20, tzinfo=UTC),
    )

    result = build_timeline(persona_slug="p", notes=[dated, undated])

    assert [e.note_id for e in result.entries] == ["n-undated", "n-dated"]
    undated_entry = result.entries[0]
    assert undated_entry.published is None  # never fabricated


def test_tied_timestamps_break_ties_on_descending_note_id_deterministically() -> None:
    same_ts = dt.datetime(2026, 1, 1, tzinfo=UTC)
    a = _note(note_id="a", published=same_ts)
    b = _note(note_id="b", published=same_ts)

    result1 = build_timeline(persona_slug="p", notes=[a, b])
    result2 = build_timeline(persona_slug="p", notes=[b, a])

    assert [e.note_id for e in result1.entries] == ["b", "a"]
    assert [e.note_id for e in result1.entries] == [e.note_id for e in result2.entries]


# ---------------------------------------------------------------------------
# stance_timelines
# ---------------------------------------------------------------------------


def test_stance_timeline_points_are_oldest_first() -> None:
    n1 = _note(
        note_id="n1",
        published=dt.datetime(2026, 1, 1, tzinfo=UTC),
        mentions=[_mention("NVDA", "bullish", "early call")],
    )
    n2 = _note(
        note_id="n2",
        published=dt.datetime(2026, 3, 1, tzinfo=UTC),
        mentions=[_mention("NVDA", "bearish", "changed mind")],
    )

    result = build_timeline(persona_slug="p", notes=[n2, n1])  # fed newest-first on purpose

    timeline = next(t for t in result.stance_timelines if t.symbol == "NVDA")
    assert [p.note_id for p in timeline.points] == ["n1", "n2"]
    assert [p.stance for p in timeline.points] == ["bullish", "bearish"]
    assert timeline.points[0].said_on == dt.datetime(2026, 1, 1, tzinfo=UTC)
    assert timeline.points[0].reasoning == "early call"


def test_changed_stance_symbol_sorts_ahead_of_unchanged_symbol_with_more_mentions() -> None:
    # AAPL never changes stance but is mentioned 3 times; NVDA changes stance across only 2 mentions.
    # NVDA must still sort first because "changed" outranks mention count.
    notes = [
        _note(
            note_id="n1",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[_mention("AAPL", "bullish"), _mention("NVDA", "bullish")],
        ),
        _note(
            note_id="n2",
            published=dt.datetime(2026, 2, 1, tzinfo=UTC),
            mentions=[_mention("AAPL", "bullish"), _mention("NVDA", "bearish")],
        ),
        _note(
            note_id="n3",
            published=dt.datetime(2026, 3, 1, tzinfo=UTC),
            mentions=[_mention("AAPL", "bullish")],
        ),
    ]

    result = build_timeline(persona_slug="p", notes=notes)

    symbols_in_order = [t.symbol for t in result.stance_timelines]
    assert symbols_in_order == ["NVDA", "AAPL"]
    assert len(result.stance_timelines[0].points) == 2  # NVDA
    assert len(result.stance_timelines[1].points) == 3  # AAPL


def test_stance_timeline_symbol_ties_break_alphabetically() -> None:
    note = _note(
        note_id="n1",
        published=dt.datetime(2026, 1, 1, tzinfo=UTC),
        mentions=[_mention("TSLA", "neutral"), _mention("AAPL", "neutral")],
    )

    result = build_timeline(persona_slug="p", notes=[note])

    # Both unchanged, both 1 mention -- alphabetical tiebreak.
    assert [t.symbol for t in result.stance_timelines] == ["AAPL", "TSLA"]


def test_mention_count_breaks_ties_within_the_same_changed_group() -> None:
    notes = [
        _note(
            note_id="n1",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[_mention("A", "bullish"), _mention("B", "bullish")],
        ),
        _note(
            note_id="n2",
            published=dt.datetime(2026, 2, 1, tzinfo=UTC),
            mentions=[_mention("A", "bearish"), _mention("B", "bearish")],
        ),
        _note(
            note_id="n3",
            published=dt.datetime(2026, 3, 1, tzinfo=UTC),
            mentions=[_mention("A", "neutral")],
        ),
    ]
    # Both A and B flip stance; A has 3 mentions, B has 2 -- A must sort first.

    result = build_timeline(persona_slug="p", notes=notes)

    assert [t.symbol for t in result.stance_timelines] == ["A", "B"]

"""Tests for `app.personas.watchlist.build_watchlist`/`with_instruments` -- Phase 7b of
`docs/INFLUENCER-CONTRACT.md`. All in-memory: no network, no model, no bar fetch. `_note`/`_mention`/
`_persona` mirror `tests/test_personas_paperbook.py`'s builders (same field shapes, same defaults)
since both modules build the identical `EpisodicNote`/`TickerMention`/`Persona` wire models.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from datetime import UTC

from app.personas.models import EpisodicNote, Persona, TickerMention
from app.personas.watchlist import build_watchlist, with_instruments

_DEFAULT_INGESTED_AT = dt.datetime(2026, 1, 1, tzinfo=UTC)


def _note(
    *,
    note_id: str = "n1",
    published: dt.datetime | None,
    mentions: Sequence[TickerMention] = (),
    persona: str = "testpersona",
    ingested_at: dt.datetime = _DEFAULT_INGESTED_AT,
) -> EpisodicNote:
    return EpisodicNote(
        note_id=note_id,
        persona=persona,
        source_id="yt:UCXXXXXXXXXXXXXXXXXXXXXX",
        published=published,
        ingested_at=ingested_at,
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


def _persona(*, slug: str = "testpersona", display_name: str = "Test Persona") -> Persona:
    return Persona(
        slug=slug,
        display_name=display_name,
        sources=(),
        note_count=0,
        tickers=(),
        profile_version=0,
        consolidated_at=None,
        created_at=dt.datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_empty_personas_yield_empty_entries() -> None:
    watchlist = build_watchlist(personas=())
    assert watchlist.entries == ()
    assert watchlist.caveat != ""


def test_persona_with_no_notes_yields_empty_entries() -> None:
    watchlist = build_watchlist(personas=[(_persona(), [])])
    assert watchlist.entries == ()


def test_two_personas_bullish_on_same_symbol() -> None:
    alice = _persona(slug="alice")
    bob = _persona(slug="bob")
    alice_notes = [
        _note(
            note_id="a1",
            published=dt.datetime(2026, 1, 5, tzinfo=UTC),
            mentions=[_mention("AAPL", "bullish", "strong iphone cycle")],
        )
    ]
    bob_notes = [
        _note(
            note_id="b1",
            persona="bob",
            published=dt.datetime(2026, 1, 6, tzinfo=UTC),
            mentions=[_mention("AAPL", "bullish", "services growth")],
        )
    ]
    watchlist = build_watchlist(personas=[(alice, alice_notes), (bob, bob_notes)])
    assert len(watchlist.entries) == 1
    entry = watchlist.entries[0]
    assert entry.symbol == "AAPL"
    assert entry.bullish_count == 2
    assert entry.bearish_count == 0
    assert entry.personas == ("alice", "bob")


def test_flipped_to_bearish_is_excluded() -> None:
    persona = _persona()
    notes = [
        _note(
            note_id="n1",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[_mention("TSLA", "bullish", "early call")],
        ),
        _note(
            note_id="n2",
            published=dt.datetime(2026, 1, 10, tzinfo=UTC),
            mentions=[_mention("TSLA", "bearish", "changed my mind")],
        ),
    ]
    watchlist = build_watchlist(personas=[(persona, notes)])
    assert watchlist.entries == ()


def test_bearish_only_symbol_excluded_even_with_other_bearish_backers() -> None:
    alice = _persona(slug="alice")
    bob = _persona(slug="bob")
    alice_notes = [
        _note(
            note_id="a1",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[_mention("NFLX", "bearish", "valuation too high")],
        )
    ]
    bob_notes = [
        _note(
            note_id="b1",
            persona="bob",
            published=dt.datetime(2026, 1, 2, tzinfo=UTC),
            mentions=[_mention("NFLX", "bearish", "subscriber slowdown")],
        )
    ]
    watchlist = build_watchlist(personas=[(alice, alice_notes), (bob, bob_notes)])
    assert watchlist.entries == ()


def test_ranking_by_count_then_symbol() -> None:
    alice = _persona(slug="alice")
    bob = _persona(slug="bob")
    carol = _persona(slug="carol")
    # MSFT backed by alice + bob (count 2); AAPL backed by alice only (count 1);
    # ZZZZ backed by alice + bob + carol (count 3).
    alice_notes = [
        _note(
            note_id="a1",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[
                _mention("MSFT", "bullish"),
                _mention("AAPL", "bullish"),
                _mention("ZZZZ", "bullish"),
            ],
        )
    ]
    bob_notes = [
        _note(
            note_id="b1",
            persona="bob",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[_mention("MSFT", "bullish"), _mention("ZZZZ", "bullish")],
        )
    ]
    carol_notes = [
        _note(
            note_id="c1",
            persona="carol",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[_mention("ZZZZ", "bullish")],
        )
    ]
    watchlist = build_watchlist(
        personas=[(alice, alice_notes), (bob, bob_notes), (carol, carol_notes)]
    )
    symbols_in_order = [entry.symbol for entry in watchlist.entries]
    assert symbols_in_order == ["ZZZZ", "MSFT", "AAPL"]
    assert watchlist.entries[0].bullish_count == 3
    assert watchlist.entries[1].bullish_count == 2
    assert watchlist.entries[2].bullish_count == 1


def test_ranking_tiebreak_by_symbol_ascending() -> None:
    persona = _persona()
    notes = [
        _note(
            note_id="n1",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[_mention("BBBB", "bullish"), _mention("AAAA", "bullish")],
        )
    ]
    watchlist = build_watchlist(personas=[(persona, notes)])
    assert [entry.symbol for entry in watchlist.entries] == ["AAAA", "BBBB"]


def test_latest_reasoning_comes_from_most_recent_bullish_note() -> None:
    alice = _persona(slug="alice")
    bob = _persona(slug="bob")
    alice_notes = [
        _note(
            note_id="a1",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[_mention("AAPL", "bullish", "old reason")],
        )
    ]
    bob_notes = [
        _note(
            note_id="b1",
            persona="bob",
            published=dt.datetime(2026, 2, 1, tzinfo=UTC),
            mentions=[_mention("AAPL", "bullish", "newest reason")],
        )
    ]
    watchlist = build_watchlist(personas=[(alice, alice_notes), (bob, bob_notes)])
    assert watchlist.entries[0].latest_reasoning == "newest reason"


def test_as_of_is_newest_bullish_backing_date() -> None:
    alice = _persona(slug="alice")
    bob = _persona(slug="bob")
    older = dt.datetime(2026, 1, 1, tzinfo=UTC)
    newer = dt.datetime(2026, 3, 1, tzinfo=UTC)
    alice_notes = [_note(note_id="a1", published=older, mentions=[_mention("AAPL", "bullish")])]
    bob_notes = [
        _note(note_id="b1", persona="bob", published=newer, mentions=[_mention("AAPL", "bullish")])
    ]
    watchlist = build_watchlist(personas=[(alice, alice_notes), (bob, bob_notes)])
    assert watchlist.entries[0].as_of == newer


def test_watchlist_as_of_defaults_to_now_utc_when_not_given() -> None:
    before = dt.datetime.now(UTC)
    watchlist = build_watchlist(personas=())
    after = dt.datetime.now(UTC)
    assert before <= watchlist.as_of <= after


def test_watchlist_as_of_uses_provided_now() -> None:
    fixed = dt.datetime(2026, 6, 1, tzinfo=UTC)
    watchlist = build_watchlist(personas=(), now=fixed)
    assert watchlist.as_of == fixed


def test_no_reasoning_note_yields_empty_latest_reasoning() -> None:
    persona = _persona()
    notes = [
        _note(
            note_id="n1",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[_mention("AAPL", "bullish", reasoning="")],
        )
    ]
    watchlist = build_watchlist(personas=[(persona, notes)])
    assert watchlist.entries[0].latest_reasoning == ""


def test_equity_symbol_reports_equity_instrument() -> None:
    persona = _persona()
    notes = [
        _note(
            note_id="n1",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[_mention("AAPL", "bullish")],
        )
    ]
    watchlist = build_watchlist(personas=[(persona, notes)])
    assert watchlist.entries[0].instrument == "equity"


def test_futures_symbol_reports_future_instrument() -> None:
    persona = _persona()
    notes = [
        _note(
            note_id="n1",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[_mention("GC", "bullish")],
        )
    ]
    watchlist = build_watchlist(personas=[(persona, notes)])
    assert watchlist.entries[0].symbol == "GC"
    assert watchlist.entries[0].instrument == "future"


def test_with_instruments_is_idempotent() -> None:
    persona = _persona()
    notes = [
        _note(
            note_id="n1",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[_mention("GC", "bullish"), _mention("AAPL", "bullish")],
        )
    ]
    watchlist = build_watchlist(personas=[(persona, notes)])
    twice = with_instruments(with_instruments(watchlist))
    assert twice == with_instruments(watchlist)
    assert {entry.symbol: entry.instrument for entry in twice.entries} == {
        "GC": "future",
        "AAPL": "equity",
    }

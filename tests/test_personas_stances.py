"""Tests for `app.personas.stances` -- the point-in-time "who is bullish" primitive that
`app.personas.watchlist.build_watchlist` does not provide (it always answers "as of the latest
note", never "as of a past date"). `_note`/`_mention`/`_persona` mirror
`tests/test_personas_watchlist.py`'s builders (same field shapes, same defaults) since both modules
build the identical `EpisodicNote`/`TickerMention`/`Persona` wire models.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from datetime import UTC

from app.personas.models import EpisodicNote, Persona, TickerMention
from app.personas.stances import bullish_as_of, consensus_as_of, said_on
from app.personas.watchlist import build_watchlist

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


# --- said_on -----------------------------------------------------------------


def test_said_on_prefers_published() -> None:
    note = _note(published=dt.datetime(2026, 2, 1, tzinfo=UTC))
    assert said_on(note) == dt.datetime(2026, 2, 1, tzinfo=UTC)


def test_said_on_falls_back_to_ingested_at() -> None:
    note = _note(published=None, ingested_at=dt.datetime(2026, 3, 1, tzinfo=UTC))
    assert said_on(note) == dt.datetime(2026, 3, 1, tzinfo=UTC)


# --- bullish_as_of -------------------------------------------------------------


def test_bullish_as_of_none_includes_every_note() -> None:
    notes = [
        _note(
            note_id="n1",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[_mention("AAPL", "bullish")],
        )
    ]
    assert bullish_as_of(notes) == ("AAPL",)


def test_flip_from_bullish_to_bearish_key_scenario() -> None:
    """The key correctness test: an early bullish note and a later bearish note on the same symbol.
    A cutoff before the late note must still see the persona as bullish; a cutoff after (or on) it
    must not."""
    early_bullish = dt.datetime(2026, 1, 1, tzinfo=UTC)
    late_bearish = dt.datetime(2026, 1, 10, tzinfo=UTC)
    notes = [
        _note(note_id="n1", published=early_bullish, mentions=[_mention("TSLA", "bullish")]),
        _note(note_id="n2", published=late_bearish, mentions=[_mention("TSLA", "bearish")]),
    ]

    before_flip = dt.datetime(2026, 1, 5, tzinfo=UTC)
    assert bullish_as_of(notes, before_flip) == ("TSLA",)

    after_flip = dt.datetime(2026, 1, 15, tzinfo=UTC)
    assert bullish_as_of(notes, after_flip) == ()


def test_note_after_as_of_never_influences_output() -> None:
    """A note said strictly after `as_of` must not affect the result at all -- not the stance, not
    even as a tiebreak. Here the only note naming MSFT is after the cutoff, so MSFT must not appear
    as bullish (nor as anything else)."""
    notes = [
        _note(
            note_id="n1",
            published=dt.datetime(2026, 6, 1, tzinfo=UTC),
            mentions=[_mention("MSFT", "bullish")],
        )
    ]
    cutoff = dt.datetime(2026, 3, 1, tzinfo=UTC)
    assert bullish_as_of(notes, cutoff) == ()


def test_date_cutoff_is_inclusive_of_that_whole_day() -> None:
    """A `dt.date` cutoff is end-of-day UTC, so a note said_on that same calendar day is included."""
    same_day_note = dt.datetime(2026, 3, 1, 18, 30, tzinfo=UTC)
    notes = [_note(note_id="n1", published=same_day_note, mentions=[_mention("NVDA", "bullish")])]
    assert bullish_as_of(notes, dt.date(2026, 3, 1)) == ("NVDA",)
    # The day before must NOT include it.
    assert bullish_as_of(notes, dt.date(2026, 2, 28)) == ()


def test_bullish_as_of_sorted_ascending() -> None:
    notes = [
        _note(
            note_id="n1",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[_mention("ZZZZ", "bullish"), _mention("AAAA", "bullish")],
        )
    ]
    assert bullish_as_of(notes) == ("AAAA", "ZZZZ")


def test_bearish_and_neutral_and_unclear_excluded() -> None:
    notes = [
        _note(
            note_id="n1",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[
                _mention("AAA", "bearish"),
                _mention("BBB", "neutral"),
                _mention("CCC", "unclear"),
                _mention("DDD", "bullish"),
            ],
        )
    ]
    assert bullish_as_of(notes) == ("DDD",)


# --- consensus_as_of -----------------------------------------------------------


def test_consensus_as_of_none_matches_build_watchlist_exactly() -> None:
    """`as_of=None` must reproduce `build_watchlist`'s current behaviour byte-for-byte: same
    entries, same order, same counts, same as_of."""
    alice = _persona(slug="alice")
    bob = _persona(slug="bob")
    carol = _persona(slug="carol")
    alice_notes = [
        _note(
            note_id="a1",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[
                _mention("MSFT", "bullish", "alice on msft"),
                _mention("AAPL", "bullish", "alice on aapl"),
                _mention("ZZZZ", "bullish", "alice on zzzz"),
            ],
        ),
        _note(
            note_id="a2",
            persona="alice",
            published=dt.datetime(2026, 1, 20, tzinfo=UTC),
            mentions=[_mention("TSLA", "bearish", "alice reversed")],
        ),
    ]
    bob_notes = [
        _note(
            note_id="b1",
            persona="bob",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[_mention("MSFT", "bullish", "bob on msft"), _mention("ZZZZ", "bullish")],
        )
    ]
    carol_notes = [
        _note(
            note_id="c1",
            persona="carol",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[_mention("ZZZZ", "bullish", "carol on zzzz")],
        )
    ]
    personas = [(alice, alice_notes), (bob, bob_notes), (carol, carol_notes)]
    fixed_now = dt.datetime(2026, 6, 1, tzinfo=UTC)

    expected = build_watchlist(personas=personas, now=fixed_now)
    actual = consensus_as_of(personas, as_of=None, now=fixed_now)

    assert actual == expected


def test_consensus_as_of_excludes_stance_from_note_after_cutoff() -> None:
    """A persona's bullish stance published after `as_of` must not count toward the consensus as of
    that date."""
    alice = _persona(slug="alice")
    notes = [
        _note(
            note_id="a1",
            published=dt.datetime(2026, 6, 1, tzinfo=UTC),
            mentions=[_mention("AAPL", "bullish")],
        )
    ]
    watchlist = consensus_as_of([(alice, notes)], as_of=dt.datetime(2026, 3, 1, tzinfo=UTC))
    assert watchlist.entries == ()


def test_consensus_as_of_flip_changes_backers_before_and_after() -> None:
    """Two personas: alice bullish early and never flips; bob bullish early then flips bearish
    later. Before bob's flip both back AAPL (count 2); after, only alice does (count 1)."""
    alice = _persona(slug="alice")
    bob = _persona(slug="bob")
    alice_notes = [
        _note(
            note_id="a1",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[_mention("AAPL", "bullish", "alice reason")],
        )
    ]
    bob_notes = [
        _note(
            note_id="b1",
            persona="bob",
            published=dt.datetime(2026, 1, 2, tzinfo=UTC),
            mentions=[_mention("AAPL", "bullish", "bob early")],
        ),
        _note(
            note_id="b2",
            persona="bob",
            published=dt.datetime(2026, 2, 1, tzinfo=UTC),
            mentions=[_mention("AAPL", "bearish", "bob flipped")],
        ),
    ]
    personas = [(alice, alice_notes), (bob, bob_notes)]

    before_flip = consensus_as_of(personas, as_of=dt.datetime(2026, 1, 15, tzinfo=UTC))
    assert len(before_flip.entries) == 1
    assert before_flip.entries[0].bullish_count == 2
    assert before_flip.entries[0].personas == ("alice", "bob")
    assert before_flip.entries[0].bearish_count == 0

    after_flip = consensus_as_of(personas, as_of=dt.datetime(2026, 3, 1, tzinfo=UTC))
    assert len(after_flip.entries) == 1
    assert after_flip.entries[0].bullish_count == 1
    assert after_flip.entries[0].personas == ("alice",)
    assert after_flip.entries[0].bearish_count == 1


def test_consensus_as_of_ranking_matches_build_watchlist_convention() -> None:
    alice = _persona(slug="alice")
    bob = _persona(slug="bob")
    notes_a = [
        _note(
            note_id="a1",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[_mention("BBBB", "bullish"), _mention("AAAA", "bullish")],
        )
    ]
    notes_b = [
        _note(
            note_id="b1",
            persona="bob",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[_mention("BBBB", "bullish")],
        )
    ]
    watchlist = consensus_as_of([(alice, notes_a), (bob, notes_b)], as_of=dt.date(2026, 6, 1))
    assert [entry.symbol for entry in watchlist.entries] == ["BBBB", "AAAA"]


def test_consensus_as_of_watchlist_as_of_resolves_date_cutoff_to_end_of_day() -> None:
    watchlist = consensus_as_of([], as_of=dt.date(2026, 4, 15))
    assert watchlist.as_of == dt.datetime(2026, 4, 15, 23, 59, 59, 999999, tzinfo=UTC)


def test_consensus_as_of_watchlist_as_of_uses_datetime_cutoff_verbatim() -> None:
    cutoff = dt.datetime(2026, 4, 15, 9, 30, tzinfo=UTC)
    watchlist = consensus_as_of([], as_of=cutoff)
    assert watchlist.as_of == cutoff


def test_consensus_as_of_none_defaults_as_of_to_now_param() -> None:
    fixed_now = dt.datetime(2026, 7, 1, tzinfo=UTC)
    watchlist = consensus_as_of([], as_of=None, now=fixed_now)
    assert watchlist.as_of == fixed_now


def test_consensus_as_of_none_defaults_as_of_to_utcnow_when_no_now_given() -> None:
    before = dt.datetime.now(UTC)
    watchlist = consensus_as_of([], as_of=None)
    after = dt.datetime.now(UTC)
    assert before <= watchlist.as_of <= after


def test_consensus_as_of_instrument_left_at_default() -> None:
    alice = _persona(slug="alice")
    notes = [
        _note(
            note_id="a1",
            published=dt.datetime(2026, 1, 1, tzinfo=UTC),
            mentions=[_mention("AAPL", "bullish")],
        )
    ]
    watchlist = consensus_as_of([(alice, notes)])
    assert watchlist.entries[0].instrument == "equity"


def test_consensus_as_of_caveat_is_set() -> None:
    watchlist = consensus_as_of([])
    assert watchlist.caveat != ""

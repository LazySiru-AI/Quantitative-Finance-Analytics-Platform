"""Folds a persona's episodic notes into a `PersonaTimeline`: the notes as a dated story, plus how
the persona's stance on each symbol it ever named evolved over time. See
`docs/INFLUENCER-CONTRACT.md`, "Chronological view (new)" under "Phase 3b", for the exact wire
contract this module implements -- the semantics below restate it, they do not vary it.

**Pure and synchronous, by design.** `build_timeline` does no I/O and makes no model call; it only
reshapes the `EpisodicNote`s its caller already loaded. That mirrors `app.personas.scoring.score_calls`
(also a pure fold over stored notes, just against market bars instead of against nothing) and keeps the
timeline endpoint cheap and deterministic -- the same notes always produce the same timeline, with no
network hiccup or model call able to change the answer between two requests.

**Why `published` falls back to `ingested_at` for ordering, twice over.** `EpisodicNote.published` is
`None` whenever the upstream genuinely could not tell us when the influencer posted (see that field's
own docstring -- a flat YouTube channel listing carries no upload date at all). A timeline cannot simply
drop those notes: an influencer who talked about a stock is still evidence of their view even if the
exact publish date is unknown, and silently excluding it would understate both the entry list and the
stance evolution for whatever symbols it mentions. So both the `entries` ordering and each
`StanceTimeline`'s `said_on` fall back to `ingested_at` -- the one timestamp every note always has,
since it is stamped by our own ingest pipeline rather than read from upstream metadata. This is an
ordering/said-on fallback only: `TimelineEntry.published` itself is carried through unchanged (still
`None` when the note has no publish date), because faking a publish date would be exactly the kind of
fabrication `EpisodicNote.published`'s own docstring warns against.

**Why "changed stance" sorts first.** A symbol the persona has only ever called bullish is a flat line
-- there is nothing to read into its evolution. A symbol that flipped bullish-to-bearish (or drifted
through neutral) is the entire reason a *timeline* view exists rather than just the latest stance; it
is the one a reader most wants surfaced without scrolling. So `stance_timelines` puts every symbol whose
set of distinct stances across its points has size > 1 ahead of every symbol that never changed, then
orders each group by descending mention count (more evidence first), then alphabetically by symbol so
two personas fed the same notes always produce the same list -- ties are never left to fold/insertion
order, which is not guaranteed stable across the fold performed here.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from app.personas.models import (
    EpisodicNote,
    PersonaTimeline,
    StancePoint,
    StanceTimeline,
    TimelineEntry,
)

__all__ = ["build_timeline"]


def _order_key(note: EpisodicNote) -> datetime:
    """The timestamp used to place a note in time: `published` when the upstream told us, else
    `ingested_at`. See the module docstring for why this fallback exists and why it never invents a
    `published` value on the note itself."""
    return note.published if note.published is not None else note.ingested_at


def build_timeline(*, persona_slug: str, notes: Sequence[EpisodicNote]) -> PersonaTimeline:
    """Fold `notes` into a `PersonaTimeline` for `persona_slug`.

    `entries` is one `TimelineEntry` per note, newest first by `_order_key`; ties (identical
    timestamps) break on descending `note_id` so the newest-first order stays deterministic without
    depending on the caller's input order. A note's `symbols` are the distinct symbols its mentions
    named, in the order they were first mentioned within that note.

    `stance_timelines` has one `StanceTimeline` per symbol the persona ever mentioned across `notes`,
    each `points` sorted oldest-first by `said_on` (ties break on ascending `note_id`) so it reads as
    a forward-in-time story. The list itself is ordered per the module docstring: changed-stance
    symbols first, then by descending mention count, then alphabetically by symbol.

    Empty `notes` yields `PersonaTimeline(persona=persona_slug, entries=(), stance_timelines=())`.
    """
    if not notes:
        return PersonaTimeline(persona=persona_slug, entries=(), stance_timelines=())

    # Pair each entry with its source note's sort timestamp before sorting, rather than looking the
    # note back up by note_id afterwards -- note_id is not asserted unique here (that guarantee lives
    # upstream, in the vault writer), so a lookup could silently pick the wrong note if it ever were.
    dated_entries = [(_order_key(note), _build_entry(note)) for note in notes]
    entries = tuple(
        entry
        for _, entry in sorted(dated_entries, key=lambda pair: (pair[0], pair[1].note_id), reverse=True)
    )

    points_by_symbol: dict[str, list[StancePoint]] = {}
    for note in notes:
        said_on = _order_key(note)
        seen_symbols: set[str] = set()
        for mention in note.mentions:
            if mention.symbol in seen_symbols:
                # A note can name the same symbol in more than one TickerMention (e.g. two distinct
                # remarks about it); the timeline records one stance point per note per symbol, not
                # per mention, so a repeat within a single note does not duplicate a point at the same
                # said_on. The first mention's stance/reasoning wins, matching the order symbols
                # appear in TimelineEntry.symbols for the same note.
                continue
            seen_symbols.add(mention.symbol)
            points_by_symbol.setdefault(mention.symbol, []).append(
                StancePoint(
                    note_id=note.note_id,
                    said_on=said_on,
                    stance=mention.stance,
                    reasoning=mention.reasoning,
                )
            )

    stance_timelines = tuple(
        sorted(
            (
                StanceTimeline(
                    symbol=symbol,
                    points=tuple(
                        sorted(points, key=lambda p: (p.said_on, p.note_id))
                    ),
                )
                for symbol, points in points_by_symbol.items()
            ),
            key=_stance_timeline_sort_key,
        )
    )

    return PersonaTimeline(persona=persona_slug, entries=entries, stance_timelines=stance_timelines)


def _build_entry(note: EpisodicNote) -> TimelineEntry:
    symbols: list[str] = []
    seen: set[str] = set()
    for mention in note.mentions:
        if mention.symbol not in seen:
            seen.add(mention.symbol)
            symbols.append(mention.symbol)
    return TimelineEntry(
        note_id=note.note_id,
        published=note.published,
        title=note.title,
        summary=note.summary,
        themes=note.themes,
        symbols=tuple(symbols),
        url=note.url,
    )


def _stance_timeline_sort_key(timeline: StanceTimeline) -> tuple[bool, int, str]:
    """Changed-stance symbols first (`not changed` sorts False < True), then by descending mention
    count, then alphabetically by symbol -- see the module docstring for why "changed" is the
    headline signal a timeline exists to surface."""
    changed = len({point.stance for point in timeline.points}) > 1
    return (not changed, -len(timeline.points), timeline.symbol)

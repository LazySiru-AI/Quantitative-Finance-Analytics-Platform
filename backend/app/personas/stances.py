"""Point-in-time "who is bullish" -- the primitive `app.personas.watchlist.build_watchlist` lacks.

**Why this exists.** `build_watchlist` answers "who is CURRENTLY bullish", where "currently" always
means "as of the latest note in the notes it was handed". That is exactly right for the live
`/api/personas/watchlist` route, and exactly wrong for anything that looks backward over a past
window: a backtest that wants "what would the watchlist have said on 2026-03-01" must not let a note
published on 2026-06-01 leak into that answer. Using today's stances for a past window is precisely
the bug that produced a fake +20% backtest -- the influencer consensus signal was, invisibly, a
look-ahead. This module makes the cutoff explicit and mandatory to reason about (never implicit in
"pass in fewer notes and hope").

**Semantics mirror `watchlist.py` exactly**, with one addition: every stance computation only
considers notes whose `said_on` is `<= as_of` (or every note, when `as_of` is `None` -- which
reproduces `build_watchlist`'s existing behaviour byte-for-byte, since it applies no cutoff at all).
"Latest-stance-wins per symbol" is unchanged: given the notes visible as of the cutoff, a persona's
current view on a symbol is still the mention on the note with the latest `said_on` that names it.
Ties resolve to whichever is encountered last in the input sequence, matching
`watchlist._latest_stance_per_symbol`'s tiebreak.

**Dating a call**: `said_on = note.published or note.ingested_at`, identical fallback to
`watchlist._said_on` / `paperbook._said_on` -- `ingested_at` is never `None`, so every note can be
placed on a timeline even when `published` could not be recovered.

**A `dt.date` cutoff is end-of-day UTC** (`23:59:59.999999` that day), so a note said on that same
calendar day counts -- the cutoff is inclusive of the whole day, not just its first instant. A
`dt.datetime` cutoff is used exactly as given (the caller is assumed to have already picked the
instant they mean); `None` means no cutoff at all.

**Pure and synchronous.** No I/O, no network, no model call -- same discipline as `watchlist.py`.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from app.personas.models import (
    EpisodicNote,
    InfluencerWatchlist,
    Persona,
    Stance,
    WatchlistEntry,
)

_CAVEAT: str = (
    "A reference list of what the followed influencers are currently bullish on -- descriptive, "
    "not a recommendation or a buy list."
)


@dataclass(frozen=True)
class _CurrentStance:
    """One persona's latest-dated stance on one symbol, among the notes visible as of the cutoff --
    the note with the latest `said_on` (not exceeding the cutoff) that names the symbol, regardless
    of stance. Carries the backing `reasoning` (from the mention itself) so a bullish stance can
    surface its own supporting reason without a second pass over the notes."""

    stance: Stance
    said_on: dt.datetime
    reasoning: str


def said_on(note: EpisodicNote) -> dt.datetime:
    """`note.published` when the upstream could date it, else `note.ingested_at` -- identical
    fallback to `watchlist._said_on` / `paperbook._said_on`; see those modules' docstrings for why
    `ingested_at` (never `None`) is a defensible tiebreak for "the latest mention" even though it is
    never treated as an entry/publication date anywhere else."""
    return note.published or note.ingested_at


def _resolve_cutoff(as_of: dt.date | dt.datetime | None) -> dt.datetime | None:
    """`None` stays `None` (no cutoff -- every note is visible). A `dt.datetime` is used as-is. A
    bare `dt.date` becomes that day's last instant in UTC, so a note said on that same calendar day
    is included. Checked in this order because `dt.datetime` is itself a subclass of `dt.date`."""
    if as_of is None:
        return None
    if isinstance(as_of, dt.datetime):
        return as_of
    return dt.datetime.combine(as_of, dt.time.max, tzinfo=dt.UTC)


def _current_stances_as_of(
    notes: Sequence[EpisodicNote], cutoff: dt.datetime | None
) -> dict[str, _CurrentStance]:
    """One `_CurrentStance` per symbol ever mentioned across the notes visible as of `cutoff` (all
    of `notes` when `cutoff` is `None`). Mirrors `watchlist._latest_stance_per_symbol`, with notes
    whose `said_on` is after the cutoff excluded before the latest-stance-wins fold runs -- such a
    note must never influence the result, not even by losing a tiebreak."""
    latest: dict[str, _CurrentStance] = {}
    for note in notes:
        when = said_on(note)
        if cutoff is not None and when > cutoff:
            continue
        for mention in note.mentions:
            current = latest.get(mention.symbol)
            if current is None or when >= current.said_on:
                latest[mention.symbol] = _CurrentStance(
                    stance=mention.stance,
                    said_on=when,
                    reasoning=mention.reasoning,
                )
    return latest


def bullish_as_of(
    notes: Sequence[EpisodicNote], as_of: dt.date | dt.datetime | None = None
) -> tuple[str, ...]:
    """Latest-stance-wins over `notes` with `said_on <= as_of` (all notes when `as_of` is `None`);
    returns the symbols whose latest stance as of that moment is `"bullish"`, sorted ascending. A
    note said after `as_of` never influences the result."""
    cutoff = _resolve_cutoff(as_of)
    current = _current_stances_as_of(notes, cutoff)
    return tuple(sorted(symbol for symbol, stance in current.items() if stance.stance == "bullish"))


@dataclass(frozen=True)
class _Backer:
    """One persona's current-bullish (as of the cutoff) backing of one symbol, carrying just enough
    to build the entry's `personas`/`latest_reasoning`/`as_of` fields once every persona has been
    folded in."""

    slug: str
    said_on: dt.datetime
    reasoning: str


def consensus_as_of(
    personas: Sequence[tuple[Persona, Sequence[EpisodicNote]]],
    *,
    as_of: dt.date | dt.datetime | None = None,
    now: dt.datetime | None = None,
) -> InfluencerWatchlist:
    """Point-in-time `InfluencerWatchlist`: the cross-persona consensus as it would have read as of
    `as_of` (or, when `as_of` is `None`, the same "as of the latest available note" behaviour as
    `watchlist.build_watchlist` -- byte-identical entries, order, and counts).

    For each `(persona, notes)` pair, `_current_stances_as_of` finds that persona's latest-dated
    stance -- among notes with `said_on <= as_of` only -- on every symbol it mentioned by then. A
    symbol whose as-of stance is `"bullish"` adds the persona to the symbol's bullish backers
    (`bearish_count` similarly tallies personas whose as-of stance is `"bearish"`); `"neutral"`/
    `"unclear"` count toward neither. Only symbols with at least one as-of bullish backer become
    `WatchlistEntry` rows. `entries` are sorted by `bullish_count` descending, then `symbol`
    ascending, matching `build_watchlist`. `WatchlistEntry.instrument` is left at its default
    (`"equity"`) -- the caller sets it, same contract as `build_watchlist`.

    `watchlist.as_of` is the resolved cutoff (`as_of` itself if a `datetime`, or its end-of-day UTC
    if a `date`) when `as_of` is given, else `now` (or `datetime.now(UTC)` when `now` is also
    omitted) -- so the field always states the moment the snapshot is taken as of, never a stand-in.
    """
    cutoff = _resolve_cutoff(as_of)
    bullish_backers: dict[str, list[_Backer]] = {}
    bearish_counts: dict[str, int] = {}

    for persona, notes in personas:
        for symbol, current in _current_stances_as_of(notes, cutoff).items():
            if current.stance == "bullish":
                bullish_backers.setdefault(symbol, []).append(
                    _Backer(slug=persona.slug, said_on=current.said_on, reasoning=current.reasoning)
                )
            elif current.stance == "bearish":
                bearish_counts[symbol] = bearish_counts.get(symbol, 0) + 1

    entries = [
        WatchlistEntry(
            symbol=symbol,
            bullish_count=len(backers),
            bearish_count=bearish_counts.get(symbol, 0),
            personas=tuple(sorted(backer.slug for backer in backers)),
            latest_reasoning=max(backers, key=lambda backer: backer.said_on).reasoning,
            as_of=max(backer.said_on for backer in backers),
        )
        for symbol, backers in bullish_backers.items()
    ]
    entries.sort(key=lambda entry: (-entry.bullish_count, entry.symbol))

    return InfluencerWatchlist(
        as_of=cutoff if cutoff is not None else (now or dt.datetime.now(dt.UTC)),
        entries=tuple(entries),
        caveat=_CAVEAT,
    )

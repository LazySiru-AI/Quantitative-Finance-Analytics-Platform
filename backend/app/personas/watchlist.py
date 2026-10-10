"""Cross-persona consensus watchlist -- Phase 7b of `docs/INFLUENCER-CONTRACT.md`.

**The question this module answers:** across every followed persona, which symbols is at least ONE
of them CURRENTLY bullish on, and how many back each? It is a descriptive reference the strategy
layer can seed `focus_symbols`/`candidates` from (`app.agents.scout`/`designer` already accept
those), or the owner can read -- never a buy list, never a recommendation. See
`docs/INFLUENCER-CONTRACT.md`, "Phase 7 -- cross-pollination (pinned)", section "7b -- influencer
consensus watchlist", for the exact wire contract this module implements; the semantics below
restate it, they do not vary it.

**This module is a thin wrapper over `app.personas.stances.consensus_as_of`.** That module is the
one place "latest-stance-wins, per persona per symbol" (see its docstring) and the point-in-time
cutoff logic live; `build_watchlist` is just `consensus_as_of` called with `as_of=None` (the
"as of the latest available note" behaviour, byte-identical to this module's own former inline
implementation) plus one addition of its own: stamping each entry's real `instrument` kind via
`app.personas.instruments.classify`, so the UI can flag a "bullish" future or index as something a
reader cannot trade through an ordinary equities broker as-is.

**Pure and synchronous.** No I/O, no network, no model call, no bar fetch -- the caller (the
`/api/personas/watchlist` route, per the contract) loads every persona's notes and passes them in;
this function only aggregates what it is given.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from app.personas import instruments, stances
from app.personas.models import EpisodicNote, InfluencerWatchlist, Persona


def with_instruments(watchlist: InfluencerWatchlist) -> InfluencerWatchlist:
    """`watchlist` with every entry's `instrument` set to `instruments.classify(entry.symbol)`.

    Rebuilds each `WatchlistEntry` via `model_copy` (the models are frozen) rather than mutating in
    place. Idempotent: `classify` is a deterministic, symbol-only function, so re-running this over
    its own output reclassifies every entry to the exact same kind and produces an equal watchlist.
    """
    return watchlist.model_copy(
        update={
            "entries": tuple(
                entry.model_copy(update={"instrument": instruments.classify(entry.symbol)})
                for entry in watchlist.entries
            )
        }
    )


def build_watchlist(
    *,
    personas: Sequence[tuple[Persona, Sequence[EpisodicNote]]],
    now: dt.datetime | None = None,
) -> InfluencerWatchlist:
    """Aggregate every persona's current stances into the cross-persona consensus watchlist.

    Delegates the aggregation itself to `stances.consensus_as_of(personas, as_of=None, now=now)` --
    "current" here means "as of the latest note each persona was handed", i.e. no point-in-time
    cutoff -- then stamps each entry's `instrument` via `with_instruments`. See `consensus_as_of`'s
    docstring for the full latest-stance-wins/ranking semantics (unchanged from this module's former
    inline implementation): `entries` sorted by `bullish_count` descending then `symbol` ascending,
    a symbol needs at least one current-bullish backer to appear, and empty `personas` yields an
    empty `entries` tuple.
    """
    return with_instruments(stances.consensus_as_of(personas, as_of=None, now=now))

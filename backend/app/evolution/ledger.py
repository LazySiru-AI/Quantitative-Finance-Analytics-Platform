"""The loop's memory of every hypothesis it has ever tested.

A generation's leaderboard answers "how did this generation's six candidates compare to each
other." It cannot answer the question that actually matters to a search that never stops: "how
surprised should I be that *any* candidate, ever proposed, looked this good." The second question's
denominator is every candidate the loop has run across its whole life, not the six sitting in front
of it right now -- a searcher that corrects its multiple-comparison arithmetic *within* one
generation and then reports the winner has corrected for nothing, because the generation boundary is
not a boundary the search itself respects (the same genome can be, and is, re-proposed in a later
generation -- see `app.evolution.models.genome_id_for`'s own docstring on why a genome's id is
content-addressed rather than sequential).

`Ledger` is that whole-life record: an append-only JSONL file at `loop_root(settings) /
"ledger.jsonl"`, one `LedgerEntry` per line, one line per (genome, generation) the loop actually
scored. `Ledger.q_values` is what makes the record useful rather than merely historical -- it reruns
Benjamini-Hochberg over the ledger's entire p-value column every time it is called, so a candidate
recorded in generation 3 gets a *different* q-value once generation 40 has added its own entries to
the denominator. That property -- an old entry's q-value changing as the search continues -- is not a
bug to guard against; it is the entire reason this module exists instead of a per-generation q-value
already being enough. `tests/test_evolution_feedback.py`'s ledger tests assert it directly.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.backtest.scan import benjamini_hochberg
from app.config import Settings
from app.evolution.models import content_digest, loop_root

__all__ = ["Ledger", "LedgerEntry"]


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One (genome, generation) the loop actually scored -- one line in the ledger file.

    Deliberately flatter than `app.evolution.models.Standing`: a `Standing` is a leaderboard row,
    read fresh from `app.tournament.results` every time a generation is inspected, and carries fields
    (`rank`, `windows_run`, `hit_rate`, `q_value`) that are properties of *that generation's* board.
    A `LedgerEntry` is what survives past the generation it was recorded in -- enough to recompute a
    whole-history q-value and to answer "has this genome been tried before," and nothing that only
    makes sense next to five other cards from the same round.
    """

    genome_id: str
    generation: int
    purpose: str
    round_id: str
    windows: tuple[str, ...]
    """The selection windows this entry's numbers were measured over. Never includes a holdout
    window -- see `app.evolution.feedback.ledger_entries_for`."""

    median_excess: Decimal | None
    holdout_median_excess: Decimal | None
    closed_trades: int
    wins: int
    p_value: float | None
    """`None` below `app.tournament.scoring.MIN_CLOSED_TRADES_FOR_P_VALUE` closed trades -- the
    ledger still records the entry (it occupies a seat in `distinct_candidates()`), it simply
    contributes no evidence to `q_values()` beyond holding open a slot in `m`, exactly as
    `app.backtest.scan.benjamini_hochberg`'s own docstring requires of an untestable trial."""

    recorded_at: dt.datetime


def _entry_to_json(entry: LedgerEntry) -> dict[str, Any]:
    """`LedgerEntry` -> a JSON-safe `dict`. `Decimal` and `datetime` have no native JSON
    representation, so both are written as strings and reconstructed by :func:`_entry_from_json`
    below; every other field is already a JSON primitive."""
    return {
        "genome_id": entry.genome_id,
        "generation": entry.generation,
        "purpose": entry.purpose,
        "round_id": entry.round_id,
        "windows": list(entry.windows),
        "median_excess": None if entry.median_excess is None else str(entry.median_excess),
        "holdout_median_excess": (
            None if entry.holdout_median_excess is None else str(entry.holdout_median_excess)
        ),
        "closed_trades": entry.closed_trades,
        "wins": entry.wins,
        "p_value": entry.p_value,
        "recorded_at": entry.recorded_at.isoformat(),
    }


def _entry_from_json(payload: dict[str, Any]) -> LedgerEntry:
    return LedgerEntry(
        genome_id=payload["genome_id"],
        generation=payload["generation"],
        purpose=payload["purpose"],
        round_id=payload["round_id"],
        windows=tuple(payload["windows"]),
        median_excess=(
            None if payload["median_excess"] is None else Decimal(payload["median_excess"])
        ),
        holdout_median_excess=(
            None
            if payload["holdout_median_excess"] is None
            else Decimal(payload["holdout_median_excess"])
        ),
        closed_trades=payload["closed_trades"],
        wins=payload["wins"],
        p_value=payload["p_value"],
        recorded_at=dt.datetime.fromisoformat(payload["recorded_at"]),
    )


class Ledger:
    """Append-only, JSONL on disk at `loop_root(settings) / "ledger.jsonl"`.

    Every write is one `json.dumps` call plus a newline, flushed immediately (:meth:`record`) --
    never a read-modify-write of the whole file, so two supervisor generations cannot race each
    other into a lost update the way a "load the list, append, write the list back" implementation
    would. Every read tolerates a truncated final line (:meth:`entries`): a process killed mid-write
    leaves at most one partial JSON object at the end of the file, and a loop that is killed and
    restarted must not find its own history unreadable because of the entry it never finished
    writing.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    @classmethod
    def open(cls, settings: Settings) -> Ledger:
        """The one ledger for this `settings.data_dir` -- there is exactly one per loop root, never
        one per generation or per purpose, because the whole point of this file is a denominator
        that spans every generation and every purpose the loop has ever searched."""
        return cls(loop_root(settings) / "ledger.jsonl")

    def record(self, entries: Iterable[LedgerEntry]) -> None:
        """Append `entries` to the ledger file, one JSON object per line, flushing after each write.

        A no-op for an empty `entries` -- so a caller can pass `ledger_entries_for(...)`'s result
        straight through without a length check of its own, and so an empty generation never creates
        (or touches the mtime of) a ledger file that does not otherwise need to exist yet.
        """
        entries = tuple(entries)
        if not entries:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.is_file() and self._path.stat().st_size > 0:
            # If a previous writer died mid-line, the file's last byte is not a newline. Terminate
            # that dangling fragment before appending -- otherwise this call's own first entry would
            # be concatenated directly onto the truncated tail, corrupting *this* write too, not just
            # the one that crashed. `entries()` still tolerates the (now newline-terminated) partial
            # line as its own line, exactly as it would have if this call had never happened.
            with self._path.open("rb") as probe:
                probe.seek(-1, 2)
                if probe.read(1) != b"\n":
                    with self._path.open("a", encoding="utf-8") as mend:
                        mend.write("\n")
        with self._path.open("a", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(_entry_to_json(entry), sort_keys=True))
                handle.write("\n")
                handle.flush()

    def entries(self) -> tuple[LedgerEntry, ...]:
        """Every entry ever recorded, oldest first (the file's own append order).

        An entry whose `p_value` is `None` is returned exactly like any other -- never dropped -- so
        a caller can see the full shape of what the loop has tried, including the candidates that
        took too few trades to test. Only the *last* line of the file is ever treated as possibly
        truncated: a line before it that fails to parse is a real defect (disk corruption, a manual
        edit gone wrong) and is raised, not silently swallowed, because silently dropping a *middle*
        entry would corrupt `q_values()`'s `m` without leaving any trace that it had done so.
        """
        if not self._path.is_file():
            return ()
        lines = [line for line in self._path.read_text(encoding="utf-8").split("\n") if line.strip()]
        out: list[LedgerEntry] = []
        last_index = len(lines) - 1
        for index, line in enumerate(lines):
            try:
                payload = json.loads(line)
                out.append(_entry_from_json(payload))
            except (json.JSONDecodeError, KeyError, ValueError):
                if index == last_index:
                    # A process killed mid-`record()` leaves at most one incomplete trailing line --
                    # this is that case, not corruption, so it is dropped rather than raised. See
                    # this method's own docstring.
                    break
                raise
        return tuple(out)

    def distinct_candidates(self) -> int:
        """How many *distinct* genomes the ledger has ever recorded -- the multiple-comparison
        denominator `app.evolution.models.LoopStatus.candidates_tested` reports, and the count
        :meth:`q_values` uses for `m`. Deliberately `len({content_digest(genome_id), ...})`, not
        `len(entries())` and not `len({genome_id, ...})` either: `genome_id_for`'s own docstring is
        explicit that content-addressing exists so "the ledger's correction denominator can count
        distinct hypotheses rather than distinct runs" -- a genome the loop rediscovers in a later
        generation is one hypothesis re-measured, not a second one.

        **Counting distinct `genome_id`s does not, on its own, achieve that.** `genome_id_for` mints
        `g{generation}-{digest}`, and only a candidate *carried forward as an elite* keeps its original
        id across generations -- one independently re-proposed from scratch (the search rediscovering
        the same content on its own, not breeding it forward) mints a *new* id at the new generation
        with the *same* digest. Measured on this repo's own ledger: 47 of 1,701 distinct card contents
        have been minted under more than one id (`content_digest`'s own docstring). Grouping by
        `content_digest` is what makes a rediscovered strategy count once, whichever id it happens to
        be wearing when it was scored.
        """
        return len({content_digest(entry.genome_id) for entry in self.entries()})

    def q_values(self) -> dict[str, float]:
        """Benjamini-Hochberg q-value per genome id ever recorded, computed across the *whole* ledger
        -- but corrected over distinct **content**, not distinct ids, and merged back onto every id
        that content was ever minted under.

        **What `m` is, and why it differs from `app.tournament.scoring.score`'s own convention.**
        `app.backtest.scan.benjamini_hochberg` (used unmodified below -- see this module's own
        docstring) always sets `m = len(p_values)`, and `app.tournament.scoring.score` calls it with
        one entry per agent that ran *in that round*, because a round's agents are already distinct
        by construction (ten different cards, ten different `agent_id`s). This ledger cannot make
        that assumption: the same underlying strategy can appear under more than one `genome_id`
        across generations -- an elite carried forward keeps its original id, but a candidate the
        search *rediscovers* from scratch mints a fresh id at the new generation over identical
        content (see :meth:`distinct_candidates`) -- and `genome_id_for`'s docstring is explicit that
        content-addressing exists so a rediscovered genome is recognised as one hypothesis, not
        counted twice. Feeding every *entry* into `benjamini_hochberg` (one row per genome per
        generation) would therefore inflate `m` by the number of repeat measurements, and grouping by
        the full `genome_id` rather than `content_digest` inflates it the same way for exactly the
        re-minted-content case this docstring already names -- precisely the "correction over 8 when
        16 were run" failure `strategy-program/PROTOCOL.md` §3.8 describes. So `m` here is
        :meth:`distinct_candidates`: one p-value per distinct `content_digest`, taken from that
        content's *most recently recorded* entry under any id (the ledger's own append order makes
        "most recent" well defined) when it has more than one.

        **The result is still keyed by `genome_id`, not by digest.** A caller (`app.evolution.loop`)
        looks up a q-value by the exact `genome_id` on the `Standing` it is annotating, which may be
        any id the shared content was ever minted under -- so every `genome_id` that has ever shared a
        digest is given that digest group's one q-value here, merging the standings rather than
        dropping any of them.

        Returns only genomes with a defined q-value -- a genome whose content-group's (most recent)
        `p_value` is `None` is not a key in the result, mirroring `Standing.q_value`'s own "`None`
        when the card took too few closed trades to test" contract; a caller checking
        `genome_id in q_values()` gets a clean answer rather than having to also check the value for
        `None`.

        Recomputed from scratch on every call, over the entries on disk at call time -- there is no
        cached table to invalidate. This is deliberately cheap to get wrong the *other* way (a stale
        cache that under-counts `m`), so the correct-by-construction approach is the one taken:
        `entries()` is already O(ledger size) to read, and `benjamini_hochberg` is O(m log m), which
        is not a cost worth avoiding at the scale a candidate-per-generation search reaches before a
        human stops it.
        """
        latest_by_digest: dict[str, LedgerEntry] = {}
        ids_by_digest: dict[str, set[str]] = {}
        for entry in self.entries():  # oldest first, so the last write per digest wins below
            digest = content_digest(entry.genome_id)
            latest_by_digest[digest] = entry
            ids_by_digest.setdefault(digest, set()).add(entry.genome_id)

        digests = sorted(latest_by_digest)  # deterministic order; benjamini_hochberg is order-agnostic
        p_values = [latest_by_digest[digest].p_value for digest in digests]
        q_by_digest = benjamini_hochberg(p_values)

        result: dict[str, float] = {}
        for digest, q in zip(digests, q_by_digest, strict=True):
            if q is None:
                continue
            for genome_id in ids_by_digest[digest]:
                result[genome_id] = q
        return result

    def best(self) -> LedgerEntry | None:
        """The entry with the highest `median_excess` ever recorded, or `None` when nothing measurable
        has been recorded yet (an empty ledger, or every entry's `median_excess` is `None`).

        Ties broken by ledger order -- `max` is stable and `entries()` is oldest-first, so the
        earliest-recorded of two entries sharing the same `median_excess` wins. That is an arbitrary
        but deterministic rule, chosen over an explicit `genome_id` tiebreak because two entries
        genuinely tying on `median_excess` to full `Decimal` precision is itself vanishingly unlikely
        outside a test fixture -- see `tests/test_evolution_feedback.py`.
        """
        measured = [entry for entry in self.entries() if entry.median_excess is not None]
        if not measured:
            return None
        def _median(entry: LedgerEntry) -> Decimal:
            # `measured` already filtered out the `None`s; this narrows for the type checker
            # without an `assert`, which would be a runtime cost on a hot-ish path for a fact
            # the comprehension above already guarantees.
            return entry.median_excess if entry.median_excess is not None else Decimal(0)

        return max(measured, key=_median)

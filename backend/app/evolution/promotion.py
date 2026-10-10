"""Promotion: the gate that decides a machine-proposed strategy has earned a seat, and the mechanism
that seats it on the paper trading desk.

`strategy-program/PROTOCOL.md` section 6 governs how the *human* programme's library evolves: a card
reaches `candidates/` only by clearing the regime gate and posting a positive median, and it reaches
`base/` only by doing that again in a **second** round on **windows the first round did not have** --
section 6(a) is explicit that re-scoring a frozen card on an already-seen window recomputes the same
number rather than sampling a new one (`A-rotation` returned +95.2786% twice, to four decimal places,
on the same 47 trades). This module mechanises that rule for the autonomous loop's own candidates.

**This module promotes into `candidates/`, never into `base/`.** `base/` is the human programme's
standing field, and section 6's `base/` bar is itself a *second*, differently-evidenced clearance on
top of the one this module enforces (candidates/ -> base/ is its own two-consecutive-rounds gate, run
against a card that is already sitting in `candidates/`). A searcher that wrote straight into `base/`
on two of its own generations would be applying the `candidates/` -> `base/` rule to evidence gathered
under different conditions (its own generations, not human-designed rounds) than section 6 describes,
and would collapse a two-stage human process into one machine-run stage. Landing in `candidates/` is
already the loop's own two-consecutive-generations bar (see :func:`evaluate_promotions`); a further,
separate clearance is left for whatever process next promotes a `candidates/` card to `base/`, exactly
as it would for a human-authored one.

**The other failure mode this loop is built to manufacture, and the one guarded against hardest, is a
card that is excellent in-sample and quietly terrible the moment the market falls.** A search that is
free to explore has every incentive to find a candidate that curve-fits the selection windows; a
holdout regime it never saw during selection is the one number in the whole pipeline that catches
that. :func:`clears_gate` treats a negative holdout median as disqualifying regardless of how good the
selection median is -- see that function's own docstring for the ``None`` case, which is a real
weakening of the gate, not a neutral default.

**Ordering-noise floor.** `strategy-program/PROTOCOL.md` section 7 measured a 53.9-point spread (sigma
= 21.2 points) from re-running one identical card under twelve `universe` orderings. `NOISE_FLOOR_PP`
(`app.evolution.models`) is `LoopConfig.promotion_margin_pp`'s default for exactly this reason: a
margin smaller than that floor is not evidence of anything, and this module never promotes a genome
whose margin does not clear it.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from app.config import Settings
from app.evolution.models import (
    GenerationOutcome,
    Genome,
    LoopConfig,
    PendingSeat,
    PromotionRecord,
    Standing,
    content_digest,
    generated_tier_dir,
    loop_root,
    pending_seats_path,
    roster_overlay_path,
)
from app.tournament.allocation import AllocationCard
from app.tournament.ladder import LadderCard
from app.tournament.models import StrategyCard
from app.tournament.purposes import Purpose, find_disjointness_violations
from app.tournament.results import load_library

__all__ = [
    "PendingSeatAlreadyDecided",
    "PendingSeatIllegalTransition",
    "PendingSeatNotFound",
    "clears_gate",
    "evaluate_promotions",
    "gate_median_excess",
    "load_promotions",
    "migrate_seated_to_pending",
    "read_overlay",
    "read_pending_seats",
    "reject_pending_seat",
    "repair_pending_seats",
    "request_seat",
    "retire_pending_seat",
    "seat_on_desk",
    "seat_pending_seat",
    "shelve_pending_seat",
]

logger = logging.getLogger(__name__)

#: The library subdirectory holding `AllocationCard` JSON, searched by content rather than filename --
#: duplicated from `app.paperdesk.desk._ALLOCATION_TIER` rather than imported. That name is private to
#: its module (leading underscore), and `app.tournament.purposes`'s own docstring gives the standing
#: reason this codebase already uses for that choice: two literal strings duplicated on purpose cost
#: nothing, while importing another package's private name would tie this module's disjointness check
#: to an implementation detail of a package this change does not own and is explicitly scoped not to
#: modify.
_ALLOCATION_TIER = "allocation"

#: The library subdirectory holding `LadderCard` JSON, searched by content -- see `_ALLOCATION_TIER`
#: above for why this is a duplicated literal rather than an import of `app.paperdesk.desk._LADDER_TIER`.
_LADDER_TIER = "ladder"

#: Where a candidate genome's card lands. Never `base/` -- see this module's own docstring.
_CANDIDATES_TIER = "candidates"

#: Append-only ledger of every promotion this loop has ever made, one JSON object per line.
_PROMOTIONS_FILENAME = "promotions.jsonl"

#: Serializes every read-modify-write of `pending_seats.json` within this process.
#:
#: `request_seat` runs on the evolution loop's own supervisor thread; `_transition` (and therefore
#: `shelve_pending_seat`/`reject_pending_seat`/`seat_pending_seat`/`retire_pending_seat`) runs on
#: FastAPI's threadpool, one call per HTTP request, driven by `app.api.evolution`'s seat-decision
#: endpoints. Both do read -> modify -> `_write_pending_seats` with no coordination between them, and
#: the tmp-then-`os.replace` write in `_write_pending_seats` protects a concurrent *reader* against a
#: half-written file, not a second concurrent *writer* against having its own read go stale before it
#: writes back. A real interleaving: the loop's supervisor thread files a new seat request for a
#: genome that just cleared the gate at the same moment a person clicks "shelve" on an unrelated row
#: in the browser; both read the queue, both compute a new list from their own stale read, and
#: whichever writes second silently discards the other's change -- either the new seat request never
#: appears, or the shelve decision is overwritten back to `"pending"` with nothing on screen to say so.
#: A plain (non-reentrant) `Lock` would deadlock the moment any locked function is called from inside
#: another locked section on the same thread, so this is an `RLock`.
_PENDING_SEATS_LOCK = threading.RLock()

#: Serializes every read-modify-write of `roster_overlay.json` within this process, for the same
#: reason `_PENDING_SEATS_LOCK` exists: `seat_on_desk` (called from `seat_pending_seat`, itself called
#: from the FastAPI threadpool) and `_write_overlay` (called from `migrate_seated_to_pending`, which
#: can run from either the supervisor thread or a request handler) both do read -> modify -> write with
#: no coordination. Two concurrent seat approvals, or an approval racing a migration, can drop a seat
#: from the overlay while the pending-seats queue row already says `"seated"` -- the card never
#: actually appears on the paper desk and nothing on screen explains why. `RLock` for the same
#: reentrancy reason as above: `migrate_seated_to_pending` holds this lock for its whole read-decide-
#: write span (see its own docstring) while `_write_overlay` re-acquires it internally.
_ROSTER_OVERLAY_LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def gate_median_excess(standing: Standing) -> Decimal | None:
    """The one selection-side median :func:`clears_gate` and `app.evolution.feedback._gate_finding`
    must both act on: `standing.median_adjusted_excess` when it is populated, `standing.median_excess`
    otherwise.

    **Extracted so the gate and the panel cannot silently drift apart again.** They already had: this
    function's logic used to live only inside `clears_gate`, while `_gate_finding` counted margin-
    clearers on raw `median_excess` alone. `clears_gate`'s own docstring already states the
    requirement in words ("the two must agree or the panel will report a candidate as having cleared a
    bar that this function then refuses") -- this is that agreement enforced in code, by having both
    callers import the same function rather than restate the same preference twice. See
    `clears_gate`'s docstring for *why* the adjusted figure is preferred at all.
    """
    return (
        standing.median_adjusted_excess
        if standing.median_adjusted_excess is not None
        else standing.median_excess
    )


def clears_gate(standing: Standing, *, config: LoopConfig) -> bool:
    """Whether one candidate's standing, in isolation, clears this generation's promotion gate.

    All of the following must hold:

    * ``standing.eligible`` -- the card ran enough windows for its median to mean anything
      (`app.tournament.results`'s own eligibility rule, copied onto the standing rather than
      recomputed here).
    * ``standing.median_excess``, **converted to percentage points**, is not `None` and is strictly
      greater than ``config.promotion_margin_pp`` -- the ordering-noise floor by default
      (`NOISE_FLOOR_PP`), so a margin inside the floor this programme already measured is never
      treated as a result.

      The ``* 100`` is load-bearing and was missing here at first. ``median_excess`` arrives from
      `app.tournament.results.LeaderboardRowData` as a **fraction** (round 15's top card posted
      ``0.0675939...``, meaning +6.76 points), while ``promotion_margin_pp`` is named for, and holds,
      percentage points (``21.2``). Comparing the two raw asks for a median excess of +2120 points,
      which nothing will ever post -- so the gate was not merely mis-tuned, it was closed, and closed
      in the way that shows no symptom: the loop would have searched forever, reported standings that
      looked entirely reasonable, and silently never promoted anything. `app.evolution.feedback`'s
      own gate finding does the same conversion, and the two must agree or the panel will report a
      candidate as having cleared a bar that this function then refuses.
    * ``standing.total_trades > 0`` -- a card that never traded cannot have "beaten" anything; a
      positive median over zero trades is not a real number, it is an artifact of how the aggregate
      was computed.
    * the holdout does not contradict the selection number. ``standing.holdout_median_excess`` is
      either `None` or **not negative**.

    **`None` is accepted, and that is a real weakening of the gate, not a neutral default.** A `None`
    holdout means either no holdout was configured (`LoopConfig.holdout_windows` empty) or the card ran
    none of it -- in both cases this function has no evidence the card fails on an unseen regime, but
    it also has none that it survives one. Treating `None` as passing lets a misconfigured or
    holdout-less loop keep promoting; the caller is responsible for setting `holdout_windows` if it
    wants this check to mean anything. What this function will never do, under any configuration, is
    let a **negative** holdout number pass -- a card whose selection median is excellent and whose
    holdout median is negative is exactly the failure mode this whole loop is most likely to
    manufacture (a search free to explore has every incentive to curve-fit the windows it can see), and
    no margin on the selection side buys that back.
    """
    if not standing.eligible:
        return False

    # **The exposure-corrected median is preferred, and falling back to the uncorrected one is a
    # real weakening rather than an equivalent path.** `median_excess` is
    # `strategy_return - benchmark_return`, measured at Pearson r = -0.978 against a window's own
    # median benchmark across 749 runs -- so on the uncorrected figure a card is largely being scored
    # on which way the market went. `median_adjusted_excess` subtracts
    # `capital_exposure * benchmark_return` and asks `PROTOCOL.md` section 4's actual question:
    # whether the rules beat being invested the same fraction of the time. `None` means the standing
    # predates this correction (every generation on disk before it landed) or the run files lacked a
    # `capital_exposure`; the gate still works in that case, on the weaker number, rather than
    # refusing to promote anything from an older round.
    median = gate_median_excess(standing)
    if median is None or median * 100 <= config.promotion_margin_pp:
        return False
    if standing.total_trades <= 0:
        return False

    # Same preference on the holdout side, and it matters more here than on the selection side. With
    # an all-drawdown holdout the uncorrected clause was nearly free -- 86.8% of candidate-windows
    # posted a non-negative excess, because a falling benchmark hands one out. The corrected figure,
    # against a holdout that now pairs a drawdown with a rally
    # (`LoopConfig.holdout_windows`), is the version of this check that can actually fail.
    holdout = (
        standing.holdout_median_adjusted_excess
        if standing.holdout_median_adjusted_excess is not None
        else standing.holdout_median_excess
    )
    return holdout is None or holdout >= 0


# ---------------------------------------------------------------------------
# Consecutive-generation evidence
# ---------------------------------------------------------------------------


def _counts_as_new_evidence(
    candidate: frozenset[str],
    counted: Sequence[frozenset[str]],
    *,
    ceiling: int | None,
) -> bool:
    """Whether `candidate` is a piece of evidence the sets in `counted` do not already contain.

    With `ceiling` `None` this is `PROTOCOL.md` section 6(a) unchanged: any set that is not *identical*
    to one already counted is new. With an integer it is the stricter reading
    `LoopConfig.promotion_max_shared_windows` documents -- the candidate must overlap **every**
    counted set by at most `ceiling` windows.

    Compared against every counted set rather than only the newest, because the sets are evidence about
    one card and evidence is pairwise: a third set that reproduces the first is not made independent by
    happening to differ from the second.
    """
    if ceiling is None:
        return candidate not in counted
    return all(len(candidate & already) <= ceiling for already in counted)


def _max_shared_windows(window_sets: Sequence[frozenset[str]]) -> int:
    """The largest overlap between any two of `window_sets`, or 0 when there are fewer than two.

    Reported in every promotion's `reason` so a reader is told how much two "distinct" window sets
    actually had in common. Under the shipped defaults this is 4 of 5 on every promotion, which is the
    number `docs/research/loop/01-what-the-search-found.md` point 2 had to reconstruct by hand from the
    ledger because nothing recorded it.
    """
    return max(
        (len(a & b) for i, a in enumerate(window_sets) for b in window_sets[i + 1 :]),
        default=0,
    )


def _consecutive_evidence(
    *,
    genome_id: str,
    current_generation: int,
    current_windows: Sequence[str],
    history: Sequence[GenerationOutcome],
    config: LoopConfig,
) -> tuple[tuple[int, ...], tuple[tuple[str, ...], ...]] | None:
    """Walk `history` backwards from `current_generation` and decide whether `genome_id` has earned
    `config.promotion_consecutive` **distinct** pieces of evidence, per `PROTOCOL.md` section 6(a).

    The walk starts at the current generation (which the caller has already confirmed clears the gate)
    and steps backward through `history` in descending generation order. For each prior generation:

    * if `genome_id` has no `Standing` there at all, it simply did not run that generation (the loop
      cycles purposes round-robin, so a genome only appears in generations of its own purpose) -- that
      is not evidence either way, so the walk continues past it without breaking the streak;
    * if `genome_id` has a `Standing` there that does **not** clear the gate, that is an explicit
      negative result and the streak ends;
    * if it has a `Standing` there that **does** clear the gate, that generation is added to the
      streak, and its window set is added to the evidence tally *only if* it differs, as a set, from
      every window set already collected -- an identical window set recomputes the same number
      (section 6(a)'s `A-rotation` example) and is not a second piece of evidence.

    **Matched by `content_digest(genome_id)`, not the full `genome_id`.** A candidate carried forward
    as an elite keeps its original `genome_id` across generations, so matching the full id already
    finds that case. It does not find the other one: `genome_id_for`'s own docstring records that a
    candidate the search *rediscovers from scratch* -- proposed independently a second time rather
    than bred forward -- mints a brand new id at the new generation over identical content. Matching
    on the full id then sees two unrelated candidates, each of which can independently accumulate its
    own `config.promotion_consecutive` streak and get promoted -- double-promoting one strategy under
    two ids. Matched on `content_digest`, a `Standing` recorded under either id counts as evidence for
    the other, which also keeps this walk in step with :func:`evaluate_promotions`'s `already_promoted`
    guard, keyed the same way for the same reason.

    **`config.promotion_max_shared_windows` tightens "differs" into "differs by enough".** Left
    `None` -- the shipped default -- the paragraph above is the whole rule, and one window in five is
    enough to count. That is weaker than it reads: `app.evolution.loop._resolve_selection_windows`
    drops exactly one window from a six-window pool per appearance, so every pair of a lane's
    consecutive sets shares four of five *by construction*, and every promotion this loop has ever
    made was two 80%-shared measurements of the same thing
    (`docs/research/loop/01-what-the-search-found.md` point 2). Set to an integer, a candidate set is
    counted only when its overlap with **every** already-counted set is at most that many windows --
    every set, not merely the most recent one, because evidence sets are compared pairwise and a third
    set that duplicates the first is no more informative for being distant from the second.

    The walk stops as soon as `config.promotion_consecutive` distinct window sets have been collected,
    or as soon as the streak breaks. Returns `None` when the streak never reaches that many distinct
    window sets; otherwise returns `(generations, window_sets)`, oldest first, covering every
    generation in the streak (including any whose window set duplicated an earlier one -- they still
    happened and are part of the record, they just did not move the evidence count).
    """
    ceiling = config.promotion_max_shared_windows
    target_digest = content_digest(genome_id)
    generations: list[int] = [current_generation]
    window_sets: list[frozenset[str]] = [frozenset(current_windows)]
    counted: list[frozenset[str]] = [window_sets[0]]

    for outcome in sorted(history, key=lambda o: o.generation, reverse=True):
        if outcome.generation >= current_generation:
            continue
        standing = next(
            (s for s in outcome.standings if content_digest(s.genome_id) == target_digest), None
        )
        if standing is None:
            continue  # did not run this generation -- not evidence either way, keep walking
        if not clears_gate(standing, config=config):
            break  # an explicit negative result ends the streak
        generations.append(outcome.generation)
        ws = frozenset(outcome.windows)
        window_sets.append(ws)
        if _counts_as_new_evidence(ws, counted, ceiling=ceiling):
            counted.append(ws)
        if len(counted) >= config.promotion_consecutive:
            break

    if len(counted) < config.promotion_consecutive:
        return None
    ordered_generations = tuple(reversed(generations))
    ordered_window_sets = tuple(tuple(sorted(ws)) for ws in reversed(window_sets))
    return ordered_generations, ordered_window_sets


# ---------------------------------------------------------------------------
# Roth disjointness, re-checked at the point of promotion
# ---------------------------------------------------------------------------


def _library_cards(settings: Settings) -> list[StrategyCard | AllocationCard | LadderCard]:
    """Every card currently on the shelf: `base`/`variants`/`candidates`/`retired` (via
    `app.tournament.results.load_library`, which only reads `StrategyCard` JSON) plus every card under
    `library/allocation/` and `library/ladder/`, which `load_library` does not walk at all -- those two
    tiers are searched by the `agent_id` field *inside* each file, the same content-addressed lookup
    `app.paperdesk.desk._find_card` uses, because a card there is not named after its agent id on disk.

    A malformed neighbour in either of those two directories is skipped, not raised on -- the same
    tolerance `_find_card` applies, and for the same reason: exactly one file is expected to matter in
    most of these directories today, and a corrupt sibling must not take the whole disjointness check
    down with it.
    """
    cards: list[StrategyCard | AllocationCard | LadderCard] = []
    for tier_cards in load_library(settings.library_dir).values():
        cards.extend(tier_cards)

    for tier_name, model in ((_ALLOCATION_TIER, AllocationCard), (_LADDER_TIER, LadderCard)):
        tier_dir = settings.library_dir / tier_name
        if not tier_dir.is_dir():
            continue
        for path in sorted(tier_dir.glob("*.json")):
            try:
                cards.append(model.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValidationError):
                logger.warning("promotion: skipping unreadable library card %s", path)
                continue
    return cards


def _disjointness_reason(
    candidate_card: StrategyCard | AllocationCard, *, settings: Settings
) -> str | None:
    """`None` if promoting `candidate_card` introduces no Roth/taxable ticker overlap; otherwise one
    sentence naming the collision.

    Runs `find_disjointness_violations` (`app.tournament.purposes`) over the whole existing library
    plus `candidate_card`, then keeps only the violations that actually name `candidate_card` -- a
    pre-existing violation between two library cards that have nothing to do with this promotion is a
    defect for someone else to fix, not a reason to refuse this one. A Roth candidate that shares a
    ticker with a taxable card, or a taxable candidate that shares one with the seated Roth ladder, is a
    tax defect either way: Rev. Rul. 2008-5 disallows a loss replaced inside an IRA with no basis
    adjustment anywhere (see `app.tax.washsale`'s own docstring), which is strictly worse for the
    taxpayer than an ordinary wash sale and is not something any margin on the scoring side justifies.
    """
    library_cards = _library_cards(settings)
    violations = find_disjointness_violations([*library_cards, candidate_card])
    own = [
        v for v in violations if candidate_card.agent_id in (v.roth_agent_id, v.other_agent_id)
    ]
    if not own:
        return None
    return "; ".join(v.message for v in own)


# ---------------------------------------------------------------------------
# The roster overlay
# ---------------------------------------------------------------------------


def read_overlay(settings: Settings) -> dict[str, tuple[str, ...]]:
    """Read `roster_overlay_path(settings)` into `{"trading": (...), "savings": (...), "roth": (...)}`.

    Never raises. A missing file is the normal, expected state (no genome has ever been seated) and
    returns every purpose mapped to an empty tuple. A file that is not valid JSON, not a JSON object,
    or whose ``"seats"`` value is not an object of purpose-keyed string lists is logged and treated the
    same as a missing file -- **for the whole file**, not a best-effort partial read, because a
    half-parsed overlay is a worse failure mode than an empty one: it would silently drop whichever
    purpose's seats happened to be on the wrong side of the malformed part. `app.paperdesk.desk.rosters`
    is the caller this matters most for; a malformed overlay must never turn into an exception that
    takes the whole paper desk page down over one bad line -- see that function's own comment.
    """
    empty: dict[str, tuple[str, ...]] = {p.value: () for p in Purpose}
    path = roster_overlay_path(settings)
    if not path.is_file():
        return empty
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("promotion: roster overlay at %s is unreadable: %s", path, exc)
        return empty
    if not isinstance(payload, dict):
        logger.warning("promotion: roster overlay at %s is not a JSON object", path)
        return empty
    seats = payload.get("seats")
    if not isinstance(seats, dict):
        logger.warning("promotion: roster overlay at %s has no 'seats' object", path)
        return empty

    out = dict(empty)
    for purpose in Purpose:
        raw = seats.get(purpose.value, [])
        if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
            out[purpose.value] = tuple(raw)
        else:
            logger.warning(
                "promotion: roster overlay at %s has a malformed %r entry, treating it as empty",
                path,
                purpose.value,
            )
    return out


def seat_on_desk(agent_id: str, purpose: Purpose, *, settings: Settings) -> bool:
    """Add `agent_id` to the roster overlay's seats for `purpose`, additively, and return `True`.

    Idempotent: if `agent_id` is already present for `purpose`, this is a no-op that still returns
    `True` -- calling it twice for the same promotion must not seat the same card twice or corrupt the
    file. The hand-authored roster tuples in `app.paperdesk.desk` (`AGENT_IDS`, `SAVINGS_AGENT_IDS`,
    `ROTH_AGENT_IDS`) are never read or written here; this only ever touches the overlay file, which
    `app.paperdesk.desk.rosters` appends on top of them at request time.

    Written atomically: the whole new payload is written to a temp file beside the target and then
    `Path.replace`d over it, so a desk request that reads the overlay mid-write always sees either the
    complete old file or the complete new one, never a half-written one. `Path.replace` is atomic on
    both POSIX and Windows (unlike a plain rename on Windows, which refuses to overwrite).

    **The whole read-modify-write is under `_ROSTER_OVERLAY_LOCK`, not only the write.** Two concurrent
    seat approvals (or an approval racing `migrate_seated_to_pending`) each doing their own
    unsynchronized `read_overlay` -> compute -> write can drop one seat: both read the same old overlay,
    both compute their own new version from that stale read, and whichever writes second silently
    discards the other's addition -- the queue row says `"seated"` but the card never actually reaches
    the desk, and nothing on screen explains why. The atomic temp-then-replace above protects a
    concurrent *reader* from a half-written file; it does nothing for two concurrent *writers*, which is
    what the lock is for.
    """
    with _ROSTER_OVERLAY_LOCK:
        path = roster_overlay_path(settings)
        current = read_overlay(settings)
        existing = current.get(purpose.value, ())
        if agent_id not in existing:
            current = {**current, purpose.value: (*existing, agent_id)}

        payload = {
            "version": 1,
            "seats": {p.value: list(current.get(p.value, ())) for p in Purpose},
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
        return True


# ---------------------------------------------------------------------------
# The promotions ledger
# ---------------------------------------------------------------------------


def _promotions_path(settings: Settings) -> Path:
    return loop_root(settings) / _PROMOTIONS_FILENAME


def load_promotions(settings: Settings) -> tuple[PromotionRecord, ...]:
    """Read every `PromotionRecord` ever appended to `loop_root(settings)/promotions.jsonl`.

    Tolerant of a truncated last line: the file is appended to one record at a time by
    :func:`evaluate_promotions`, and a process killed mid-write leaves a final line that is not valid
    JSON. That line -- and only that line -- is skipped rather than raising, the same tolerance
    `app.tournament.jobs` applies to its own run files for the same reason (a crash writing entry N
    must not make entries 1 through N-1 unreadable). A missing file returns an empty tuple; it means no
    genome has ever been promoted, not an error.
    """
    path = _promotions_path(settings)
    if not path.is_file():
        return ()
    records: list[PromotionRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("promotion: skipping unparseable line in %s", path)
            continue
        try:
            records.append(PromotionRecord.model_validate(payload))
        except ValidationError:
            logger.warning("promotion: skipping invalid record in %s", path)
            continue
    return tuple(records)


def _append_promotion(record: PromotionRecord, *, settings: Settings) -> None:
    """Append one `PromotionRecord` as a single JSON line. Append-only: a promotion, once recorded, is
    never rewritten or removed by this module -- see :func:`load_promotions` for the reader's own
    tolerance of a crash mid-append."""
    path = _promotions_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(record.model_dump_json())
        fh.write("\n")
    _notify_promotion(record, settings=settings)


def _promotion_tier(record: PromotionRecord) -> str:
    """The library tier a promoted card landed in -- the directory `library_path` names.

    `PromotionRecord` carries no `tier`/`target` field of its own; the tier is a fact about *where*
    the card was written (`library/candidates/...`, `library/generated/...`), which `library_path`
    already records. Deriving it here rather than adding a field keeps the record's schema -- which
    every row ever written to `promotions.jsonl` conforms to -- unchanged.
    """
    parent = PurePosixPath(record.library_path.replace("\\", "/")).parent.name
    return parent or "the library"


def _notify_promotion(record: PromotionRecord, *, settings: Settings) -> None:
    """Announce one promotion through `app.notify`, after the record is durably on disk.

    `notable`, not `attention`: a promotion is a research result the owner will want to read today,
    but it asks nothing of them right now -- and it explicitly does *not* mean the card is trading.
    Since the two-stage seat pipeline landed (see `SeatStatus`), promotion files a `PendingSeat` and
    `seated` is `False` for every newly promoted card, so the detail says which of the two happened
    rather than letting "promoted" be read as "seated".

    Wrapped, like every other hook: the promotion is already written, and a notify defect must not
    turn a recorded promotion into a raised exception inside the gate.
    """
    try:
        from app.notify import emit

        seat = "already seated" if record.seated else "awaiting a seat decision"
        emit(
            settings,
            kind="research.promotion",
            severity="notable",
            headline=f"Promoted {record.genome_id} to {_promotion_tier(record)}",
            detail=f"{record.purpose} · {seat} · {record.reason}",
            refs=(f"genome:{record.genome_id}",),
            source="evolution.promotion",
            dedupe_id=f"research.promotion:{record.genome_id}:{record.promoted_at.isoformat()}",
        )
    except Exception:
        logger.exception(
            "promotion: notify hook failed for %s; the promotion itself is recorded",
            record.genome_id,
        )


# ---------------------------------------------------------------------------
# The gate, end to end
# ---------------------------------------------------------------------------


def _relative_library_path(path: Path, *, settings: Settings) -> str:
    """`path`, relative to the repo root when possible -- for `PromotionRecord.library_path`, which is
    documented as "relative to the repo root". Falls back to the absolute path when `path` is not
    actually under `settings.repo_root` (a test pointed `library_dir` somewhere else entirely), since a
    field that is supposed to be a relative path is still more useful as an absolute one than as a
    `ValueError`."""
    try:
        return str(path.relative_to(settings.repo_root))
    except ValueError:
        return str(path)


def evaluate_promotions(
    *,
    standings: Sequence[Standing],
    genomes: Mapping[str, Genome],
    history: Sequence[GenerationOutcome],
    config: LoopConfig,
    generation: int,
    selection_windows: Sequence[str],
    settings: Settings,
) -> tuple[PromotionRecord, ...]:
    """Promote every genome in `standings` that has earned it, and return the records created.

    For each `Standing`, in the order given:

    1. Skip it if its **content** is already promoted -- `load_promotions` names every promoted
       record's `genome_id`, and this is matched by `content_digest`, not the raw id: a candidate the
       search rediscovers from scratch mints a new `genome_id` over identical content
       (`genome_id_for`'s own docstring), so matching on the full id would let a re-proposed identical
       card sail past this guard as though it were a fresh hypothesis. Idempotence therefore means both
       "calling this twice for the same generation never promotes the same genome twice" *and*
       "promoting one genome's content never promotes a differently-idd genome with the same content."
       A second, in-call check catches the two-standings-in-one-generation-share-content case too (see
       below).
    2. Skip it if it does not clear this generation's gate (:func:`clears_gate`).
    3. Skip it if it has not accumulated `config.promotion_consecutive` distinct pieces of evidence
       across consecutive generations (:func:`_consecutive_evidence`) -- `PROTOCOL.md` section 6's
       two-consecutive-rounds-on-differing-windows rule.
    4. Re-check Roth/taxable ticker disjointness against the *current* library plus this candidate
       (:func:`_disjointness_reason`) -- checked here, immediately before writing, rather than trusted
       from whenever the genome was proposed, because the library can have changed underneath the loop
       since then. A violation refuses the promotion outright: no record is created, no file is
       written, no seat is taken, and the reason is logged. No margin justifies a Roth card acquiring a
       ticker a taxable card already holds -- see :func:`_disjointness_reason`'s own docstring.
    5. Copy `generated_tier_dir(settings)/{genome_id}.json` into `settings.library_dir /
       "candidates" / "{genome_id}.json"` -- never into `base/`, see this module's own docstring.
    6. If `config.seat_on_paper_desk`, add the genome's `agent_id` to the roster overlay
       (:func:`seat_on_desk`) under its `Purpose`.
    7. Build the `PromotionRecord`, append it to the promotions ledger, and include it in the return
       value.

    A genome named in `standings` but missing from `genomes`, or whose card is missing from
    `generated_tier_dir`, is skipped with a logged reason rather than raising -- both indicate a defect
    somewhere upstream in the loop (a genome that was scored but never proposed, or proposed and then
    lost), and a defect in one genome's bookkeeping must not stop every other genome in the same
    generation from being considered.
    """
    already_promoted_digests = {
        content_digest(record.genome_id) for record in load_promotions(settings)
    }
    promoted: list[PromotionRecord] = []

    for standing in standings:
        genome_id = standing.genome_id
        digest = content_digest(genome_id)

        if digest in already_promoted_digests:
            continue

        if not clears_gate(standing, config=config):
            continue

        evidence = _consecutive_evidence(
            genome_id=genome_id,
            current_generation=generation,
            current_windows=selection_windows,
            history=history,
            config=config,
        )
        if evidence is None:
            logger.info(
                "promotion: %s cleared generation %d's gate but has not accumulated %d "
                "consecutive generations of distinct-window evidence yet",
                genome_id,
                generation,
                config.promotion_consecutive,
            )
            continue
        generations, window_sets = evidence

        genome = genomes.get(genome_id)
        if genome is None:
            logger.warning(
                "promotion: %s cleared the gate but has no Genome in the supplied mapping, skipping",
                genome_id,
            )
            continue

        source_path = generated_tier_dir(settings) / f"{genome_id}.json"
        if not source_path.is_file():
            logger.warning(
                "promotion: %s cleared the gate but its card is missing at %s, skipping",
                genome_id,
                source_path,
            )
            continue

        card_model = AllocationCard if genome.shape == "allocation" else StrategyCard
        try:
            candidate_card = card_model.model_validate_json(
                source_path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError) as exc:
            logger.warning(
                "promotion: %s's card at %s failed to validate, skipping: %s",
                genome_id,
                source_path,
                exc,
            )
            continue

        violation_reason = _disjointness_reason(candidate_card, settings=settings)
        if violation_reason is not None:
            logger.warning(
                "promotion: refusing to promote %s, it would violate Roth disjointness: %s",
                genome_id,
                violation_reason,
            )
            continue

        dest_path = settings.library_dir / _CANDIDATES_TIER / f"{genome_id}.json"
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = dest_path.with_name(f"{dest_path.name}.tmp-{os.getpid()}")
        tmp_path.write_bytes(source_path.read_bytes())
        tmp_path.replace(dest_path)

        # **A promotion no longer seats anything; it asks.** `config.seat_on_paper_desk` is a
        # property of the whole run, chosen before any candidate existed, so it could never be a
        # judgement about *this* card -- and left on, it seated 25 cards nobody looked at. It now
        # means "may this loop file seat requests at all"; reaching the desk needs a person to make
        # two separate decisions, through `shelve_pending_seat` and then `seat_pending_seat`. See
        # `app.evolution.models.pending_seats_path` and `PendingSeat`'s own docstring for why the
        # decision is split in two.
        #
        # `seated` stays truthful for the `PromotionRecord`: it is `True` only when this genome's
        # seat was *already* granted on an earlier promotion, never because this one ran.
        seated = candidate_card.agent_id in read_overlay(settings).get(genome.purpose.value, ())

        # `median_excess` is a *fraction*; `promotion_margin_pp` is in percentage points. That is the
        # same mismatch `clears_gate` above converts for (see its own note on the `* 100`), and this
        # string was reporting the raw fraction under a `pp` label -- so every record written so far
        # reads "median excess 0.305pp > 21.2pp margin", which states that a card cleared a gate it
        # visibly fails. The comparison was always right; only the sentence describing it was wrong.
        # Converted here rather than at the field so the record keeps the fraction it is typed as.
        median_excess_pp = standing.median_excess * 100 if standing.median_excess is not None else None
        # **The overlap is stated, not left to be reconstructed.** "N distinct window sets" is true
        # and, on its own, flattering: under the shipped rotation two consecutive sets share four of
        # five windows every time, so "2 distinct window sets" has been describing two 80%-shared
        # measurements since the first promotion. The figure is cheap to compute and impossible to
        # recover from `promotions.jsonl` once it is not written, which is what made
        # `docs/research/loop/01-what-the-search-found.md` point 2 an archaeology exercise.
        shared = _max_shared_windows([frozenset(ws) for ws in window_sets])
        ceiling_clause = (
            f", within the {config.promotion_max_shared_windows}-window overlap ceiling"
            if config.promotion_max_shared_windows is not None
            else " (no overlap ceiling set)"
        )
        reason = (
            f"cleared generation {generation}'s gate (median excess "
            f"{median_excess_pp:.2f}pp > {config.promotion_margin_pp}pp margin) with "
            f"{len(set(window_sets))} distinct window sets across generations {generations}, "
            f"sharing at most {shared} window(s){ceiling_clause}, "
            f"meeting the {config.promotion_consecutive}-generation requirement"
        )

        record = PromotionRecord(
            genome_id=genome_id,
            agent_id=candidate_card.agent_id,
            purpose=genome.purpose,
            promoted_at=dt.datetime.now(dt.UTC),
            generations=generations,
            window_sets=window_sets,
            # `clears_gate` above already refused a `None` median, so this cannot be one here;
            # the fallback exists to satisfy the type checker without an `assert` in a path that
            # writes a promotion record.
            median_excess=standing.median_excess if standing.median_excess is not None
            else Decimal(0),
            holdout_median_excess=standing.holdout_median_excess,
            q_value=standing.q_value,
            library_path=_relative_library_path(dest_path, settings=settings),
            seated=seated,
            reason=reason,
        )
        _append_promotion(record, settings=settings)
        promoted.append(record)
        # Recorded immediately, not only re-read from disk on the next call: two standings in this
        # same `standings` sequence can share a `content_digest` (a rediscovered genome scored again
        # in the very generation that promotes its first appearance), and the second one must see the
        # first one's promotion without this function being called twice.
        already_promoted_digests.add(digest)

        # File the seat request after the promotion record, so a queue row can never name a promotion
        # that was not itself recorded. `request_seat` is idempotent and will not re-open a genome a
        # person already rejected -- see its docstring.
        if config.seat_on_paper_desk and not seated:
            request_seat(
                PendingSeat(
                    genome_id=genome_id,
                    agent_id=candidate_card.agent_id,
                    purpose=genome.purpose,
                    requested_at=record.promoted_at,
                    generations=generations,
                    window_sets=window_sets,
                    median_excess=record.median_excess,
                    holdout_median_excess=record.holdout_median_excess,
                    q_value=record.q_value,
                    library_path=record.library_path,
                    reason=record.reason,
                ),
                settings=settings,
            )

    return tuple(promoted)


# ---------------------------------------------------------------------------
# The seat approval queue
# ---------------------------------------------------------------------------


class PendingSeatNotFound(LookupError):
    """No seat request exists for this `genome_id`."""

    def __init__(self, genome_id: str) -> None:
        super().__init__(f"no seat request for genome {genome_id}")
        self.genome_id = genome_id


class PendingSeatIllegalTransition(ValueError):
    """A decision was requested that the seat request's current `SeatStatus` does not permit.

    Raised rather than silently re-deciding, or silently skipping a stage. `PendingSeat` describes the
    full legality table: `shelve`/`reject` are legal only from `"pending"`, `seat`/`retire` are legal
    only from `"shelved"`, and nothing is legal from any of the four decided states. Every one of
    those refusals -- re-deciding an already-decided row, or trying to skip straight from `"pending"`
    to `"seated"` without a person ever shelving it first -- raises this same exception, because both
    are the same failure: a transition the state machine does not recognise from where the row
    actually is.

    The message always names the current status and the one status that transition is legal *from*,
    grouped with its sibling transition (`"g1859-... is 'seated'; only 'pending' may be shelved or
    rejected"`) -- see `_transition`'s own docstring for how that grouping is built.
    """

    def __init__(self, genome_id: str, status: str, required_from: str) -> None:
        verbs = _TRANSITIONS_FROM.get(required_from, ())
        verb_text = " or ".join(verbs) if verbs else "nothing further"
        super().__init__(f"{genome_id} is '{status}'; only '{required_from}' may be {verb_text}")
        self.genome_id = genome_id
        self.status = status
        self.required_from = required_from


#: `PendingSeatAlreadyDecided` is kept as the exact same exception class, not a subclass, so any
#: existing `except PendingSeatAlreadyDecided` -- this module's own tests included -- still catches
#: every illegal transition, not only the "already decided" subset of them. Splitting the queue into
#: five states (see `SeatStatus`) turned "already decided" into one special case of a broader rule
#: ("this genome's current status does not admit the transition asked for"), and there is nothing an
#: alias catching the narrower name needs that the general one does not already cover -- an alias
#: keeps the old import working rather than requiring every caller to learn the new, more accurate
#: name on the same release that renamed the functions around it.
PendingSeatAlreadyDecided = PendingSeatIllegalTransition


def read_pending_seats(settings: Settings) -> tuple[PendingSeat, ...]:
    """Every seat request ever filed, newest first, decided ones included.

    Best-effort in the same shape and for the same reason as :func:`read_overlay`: this feeds a page
    render and an approval screen, and a malformed queue must degrade to "nothing to approve" with a
    log line rather than raise through a request handler. A single unparseable row is dropped on its
    own rather than discarding the whole file -- one bad record must not hide every other pending
    approval, which would silently un-gate nothing but would silently *hide* work waiting on a person.
    """
    path = pending_seats_path(settings)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ()
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("promotion: pending seats at %s are unreadable: %s", path, exc)
        return ()
    if not isinstance(raw, dict) or not isinstance(raw.get("requests"), list):
        logger.warning("promotion: pending seats at %s has no 'requests' list", path)
        return ()
    seats: list[PendingSeat] = []
    for row in raw["requests"]:
        try:
            seats.append(PendingSeat.model_validate(row))
        except ValidationError as exc:
            logger.warning("promotion: dropping a malformed pending seat row: %s", exc)
    seats.sort(key=lambda s: s.requested_at, reverse=True)
    return tuple(seats)


def _write_pending_seats(seats: Sequence[PendingSeat], *, settings: Settings) -> None:
    """Atomically replace the queue file. Same temp-file-then-`Path.replace` dance, and the same
    reason, as :func:`seat_on_desk`: an approval screen reading mid-write must see the whole old file
    or the whole new one.

    Callers are responsible for holding `_PENDING_SEATS_LOCK` across their own read-modify-write span
    -- this function only writes, it does not itself decide "the whole old file or the whole new one"
    is safe against a second concurrent writer, only against a concurrent reader. `os.getpid()` alone
    in the temp filename is not enough either: `request_seat` (the loop's supervisor thread) and
    `_transition` (a FastAPI threadpool thread) can both call this within the same process, and two
    threads racing to the identical `.tmp-{pid}` path can have one thread's write clobbered by the
    other's before either gets to `Path.replace` -- so the temp name also carries `threading.get_ident()`.
    """
    path = pending_seats_path(settings)
    payload = {
        "version": 1,
        "requests": [json.loads(s.model_dump_json()) for s in seats],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def request_seat(seat: PendingSeat, *, settings: Settings) -> PendingSeat:
    """File a seat request, and return the row that is now authoritative for this genome.

    **Idempotent, and it never re-opens a decision.** If a row already exists for `seat.genome_id`
    it is returned unchanged, whatever its status -- `"shelved"`, `"seated"`, `"rejected"` and
    `"retired"` all count as decided, and every one of them refuses re-filing exactly alike. A genome
    that clears the gate again after any of the four must not quietly become pending a second time --
    that would let a loop wear a reviewer down by re-asking, which is the one failure mode an approval
    queue attached to a tireless searcher has to be built against. Moving a decided card is a
    deliberate human act (through `shelve_pending_seat`/`seat_pending_seat`/`reject_pending_seat`/
    `retire_pending_seat`), not something the loop can trigger by running longer.

    **Idempotent on the card, not merely on the id, and the distinction is the whole point.** Matching
    `genome_id` alone leaves the guard above trivially bypassable, because `genome_id_for` puts the
    generation in the prefix and hashes only the content: the same card rediscovered at a later
    generation arrives with a *different* id and sails past an id check. That is not hypothetical --
    a browser pass over the live queue found **25 requests holding 22 distinct strategies**, three
    pairs being byte-identical cards whose rows agreed on every field including the generations that
    promoted them. A person clicking approve on both would have double-weighted one strategy on the
    desk with nothing on screen to tell them apart.

    It also reopens the rejection hole by the back door: reject `g1809-<digest>` and the loop only has
    to rediscover the same traits to file `g1817-<digest>` and ask again. Matching on
    :func:`~app.evolution.models.content_digest` closes both, and closes them for a *rejected* row
    too, which is the case that matters most.

    **The whole read-decide-write span runs under `_PENDING_SEATS_LOCK`.** This is called from the
    evolution loop's own supervisor thread every time a generation promotes a candidate; `_transition`
    (below) is called from FastAPI's threadpool, one call per shelve/reject/seat/retire request. Both
    do read `read_pending_seats` -> decide -> `_write_pending_seats` with no coordination otherwise, so
    a seat request filed by the loop at the same moment a person decides an unrelated row can lose
    whichever writes second -- either the new request never appears, or the human decision reverts to
    `"pending"`. The lock makes this whole function one atomic step against every other call into this
    module that touches `pending_seats.json`.
    """
    with _PENDING_SEATS_LOCK:
        existing = read_pending_seats(settings)
        digest = content_digest(seat.genome_id)
        for row in existing:
            if row.genome_id == seat.genome_id or content_digest(row.genome_id) == digest:
                if row.genome_id != seat.genome_id:
                    logger.info(
                        "promotion: %s is the same card as the already-filed %s (content %s); "
                        "not filing a second request",
                        seat.genome_id,
                        row.genome_id,
                        digest,
                    )
                return row
        updated = (*existing, seat)
        _write_pending_seats(updated, settings=settings)
        logger.info(
            "promotion: filed a seat request for %s (%s), awaiting approval",
            seat.genome_id,
            seat.purpose.value,
        )
        return seat


@dataclass(frozen=True)
class SeatRepair:
    """What :func:`repair_pending_seats` changed, so a migration can be reported rather than assumed."""

    collapsed: tuple[tuple[str, str], ...] = ()
    """`(dropped_genome_id, kept_genome_id)` for each duplicate row removed."""
    relabelled: tuple[str, ...] = ()
    """Genome ids whose `reason` carried a fraction under a `pp` label and now reads in points."""

    @property
    def changed(self) -> bool:
        return bool(self.collapsed or self.relabelled)


#: `median excess <number>pp` inside a promotion reason. Anchored on the surrounding words rather
#: than on a bare number so it cannot match the margin on the other side of the comparison.
_REASON_MEDIAN_PP = re.compile(r"(median excess )([0-9]*\.?[0-9]+)(pp\b)")


def _repair_reason(reason: str, median_excess: Decimal) -> str | None:
    """The reason string with its median expressed in percentage points, or ``None`` to leave it be.

    **Only rewrites what it can prove is the known bug.** `clears_gate` compares a *fraction* against
    a margin in *percentage points* and converts for it; the sentence describing that comparison did
    not, so every record written before the fix reads "median excess 0.2572...pp > 21.2pp margin" --
    a card visibly failing the gate it just passed, printed directly beneath a correct "+25.72%" in
    the approvals UI.

    The guard is that the number in the string must equal `median_excess`, the stored authoritative
    field, as a fraction. Anything else -- a reason already in points, a hand-edited note, a different
    sentence entirely -- is returned as ``None`` and left alone. This corrects a unit label a bug
    emitted; it does not rewrite anybody's account of a decision.
    """
    match = _REASON_MEDIAN_PP.search(reason)
    if match is None:
        return None
    try:
        printed = Decimal(match.group(2))
    except ArithmeticError:
        return None
    if printed != median_excess:
        return None
    corrected = f"{median_excess * 100:.2f}"
    return reason[: match.start(2)] + corrected + reason[match.end(2) :]


def repair_pending_seats(settings: Settings) -> SeatRepair:
    """Collapse duplicate cards in the queue and correct reason strings the units bug mislabelled.

    A one-time migration over `data/loop/pending_seats.json`, which is tracked, so running it once and
    committing the result repairs every checkout. Both halves are conservative:

    * **Collapsing** keeps one row per :func:`~app.evolution.models.content_digest`. A row a person
      has already decided always wins over a pending one -- a decision is the only thing in this file
      that cannot be recreated -- and otherwise the earliest `requested_at` wins, since that is the id
      the evidence was first accumulated under. Never merges two rows' contents; it drops the
      redundant row whole.
    * **Relabelling** touches only the reason strings whose printed median matches the row's own
      `median_excess`. See :func:`_repair_reason`.

    Returns what it did. Writes nothing when there is nothing to change, so it is safe to re-run.

    Runs under `_PENDING_SEATS_LOCK`, same as :func:`request_seat` and :func:`_transition`: this reads
    the whole queue, decides what to drop, and writes the result back, and that whole span must not
    interleave with a seat request being filed or a decision being made mid-repair.
    """
    with _PENDING_SEATS_LOCK:
        seats = read_pending_seats(settings)
        if not seats:
            return SeatRepair()

        # Decided first, then oldest first: `min` over this key picks the row to keep.
        def keep_rank(seat: PendingSeat) -> tuple[int, dt.datetime]:
            return (0 if seat.status != "pending" else 1, seat.requested_at)

        by_digest: dict[str, list[PendingSeat]] = {}
        for seat in seats:
            by_digest.setdefault(content_digest(seat.genome_id), []).append(seat)

        collapsed: list[tuple[str, str]] = []
        relabelled: list[str] = []
        kept: list[PendingSeat] = []

        for group in by_digest.values():
            winner = min(group, key=keep_rank)
            for loser in group:
                if loser.genome_id != winner.genome_id:
                    collapsed.append((loser.genome_id, winner.genome_id))
            fixed = _repair_reason(winner.reason, winner.median_excess)
            if fixed is not None:
                winner = winner.model_copy(update={"reason": fixed})
                relabelled.append(winner.genome_id)
            kept.append(winner)

        repair = SeatRepair(collapsed=tuple(collapsed), relabelled=tuple(relabelled))
        if repair.changed:
            _write_pending_seats(tuple(kept), settings=settings)
            for dropped, keeper in collapsed:
                logger.info(
                    "promotion: dropped duplicate seat request %s -- same card as %s", dropped, keeper
                )
            if relabelled:
                logger.info(
                    "promotion: corrected the units label on %d promotion reason(s)", len(relabelled)
                )
        return repair


#: The legality table `PendingSeatIllegalTransition` and `_transition` share, keyed by the status a
#: caller is asking to move *to*. `shelve`/`reject` (stage 1) are legal only out of `"pending"`;
#: `seat`/`retire` (stage 2) are legal only out of `"shelved"`. There is deliberately no entry that
#: leads back to `"pending"` -- nothing un-decides a row, it only ever moves forward one stage.
_REQUIRED_FROM: dict[str, str] = {
    "shelved": "pending",
    "rejected": "pending",
    "seated": "shelved",
    "retired": "shelved",
}

#: The inverse grouping, for the error message: every status reachable from a given `SeatStatus`,
#: named the way a person asked for it ("shelved", not "shelve"). Two entries -- `"pending"` can
#: become `"shelved"` or `"rejected"`; `"shelved"` can become `"seated"` or `"retired"` -- because
#: those are the only two non-terminal states in the whole machine (see `SeatStatus`'s own docstring
#: for the diagram).
_TRANSITIONS_FROM: dict[str, tuple[str, ...]] = {
    "pending": ("shelved", "rejected"),
    "shelved": ("seated", "retired"),
}


def _transition(
    genome_id: str,
    to: str,
    *,
    note: str,
    settings: Settings,
) -> PendingSeat:
    """The one place that moves a `PendingSeat` between `SeatStatus` values, and the sole owner of the
    legality table every public transition function (`shelve_pending_seat`, `reject_pending_seat`,
    `seat_pending_seat`, `retire_pending_seat`) defers to.

    `to` must be reachable from the row's current status per `_REQUIRED_FROM` -- `"shelved"`/
    `"rejected"` only from `"pending"`, `"seated"`/`"retired"` only from `"shelved"` -- or this raises
    `PendingSeatIllegalTransition` with a message naming the current status and the one status `to`
    is legal from, grouped with its stage-sibling (e.g. asking for `seated` while the row is still
    `"pending"` reports "only 'shelved' may be seated or retired", because both of stage 2's
    transitions share the same precondition). `PendingSeatNotFound` when no row exists for
    `genome_id` at all -- checked first, since a status comparison needs a row to compare.

    Writes `decided_at`/`decided_note` fresh on every call, not only the first: a card can be decided
    on twice (shelved, then seated), and the second decision's note is what a reader wants to see
    beside the row after both have happened. The first decision is not lost -- it is still the reason
    the row could reach `"shelved"` at all, which the legality table itself enforces -- it is just not
    kept as a *second* pair of fields, the same way `PendingSeat` never grew a `stage_one_note`
    alongside `decided_note` for this change.

    **Runs under `_PENDING_SEATS_LOCK`, the same lock `request_seat` holds for its own read-decide-
    write span.** This is called from FastAPI's threadpool -- one call per shelve/reject/seat/retire
    HTTP request -- so two decisions on different rows, or a decision racing the loop's own
    `request_seat`, must not interleave their reads and writes of the same queue file.
    """
    with _PENDING_SEATS_LOCK:
        seats = read_pending_seats(settings)
        match = next((s for s in seats if s.genome_id == genome_id), None)
        if match is None:
            raise PendingSeatNotFound(genome_id)

        required_from = _REQUIRED_FROM[to]
        if match.status != required_from:
            raise PendingSeatIllegalTransition(genome_id, match.status, required_from)

        decided = match.model_copy(
            update={
                "status": to,
                "decided_at": dt.datetime.now(dt.UTC),
                "decided_note": note,
            }
        )
        _write_pending_seats(
            tuple(decided if s.genome_id == genome_id else s for s in seats), settings=settings
        )
        return decided


def shelve_pending_seat(genome_id: str, *, note: str = "", settings: Settings) -> PendingSeat:
    """Stage 1, yes: accept the card onto the review shelf.

    Legal only from `"pending"` -- `PendingSeatIllegalTransition` otherwise. Writes no file but the
    queue itself: the card is kept, named and observable, but it places no orders and does not join
    the paper desk. See `PendingSeat`'s own docstring for why this is a separate, smaller commitment
    than `seat_pending_seat`.
    """
    decided = _transition(genome_id, "shelved", note=note, settings=settings)
    logger.info("promotion: %s shelved for review, not seated", genome_id)
    return decided


def reject_pending_seat(genome_id: str, *, note: str = "", settings: Settings) -> PendingSeat:
    """Stage 1, no: decline the card permanently.

    Legal only from `"pending"` -- `PendingSeatIllegalTransition` otherwise. The overlay is not
    touched, so the card never reaches the desk, and `request_seat` will not re-open this row no
    matter how many times the same genome clears the gate again.
    """
    decided = _transition(genome_id, "rejected", note=note, settings=settings)
    logger.info("promotion: %s rejected, not seated", genome_id)
    return decided


def seat_pending_seat(genome_id: str, *, note: str = "", settings: Settings) -> PendingSeat:
    """Stage 2, yes: seat a shelved card on the paper desk.

    Legal only from `"shelved"` -- `PendingSeatIllegalTransition` otherwise, which is what stops a
    caller from skipping straight from `"pending"` to `"seated"` without the review-shelf decision
    ever having happened. This is the **only** transition function that calls `seat_on_desk`, and
    therefore the only one that writes `roster_overlay.json` -- see
    `TestSeatOnDeskHasOneCaller` in `tests/test_evolution_seating.py`, which parses this module's own
    source to prove it structurally rather than trusting a comment.

    **The queue is written before the overlay, deliberately.** If `seat_on_desk` fails, the request is
    already recorded as seated and the overlay is not -- a state a person can see and retry. The other
    order would seat a card whose decision was never recorded, which is the outcome this whole gate
    exists to make impossible.
    """
    decided = _transition(genome_id, "seated", note=note, settings=settings)
    seat_on_desk(decided.agent_id, decided.purpose, settings=settings)
    logger.info("promotion: %s seated on the %s desk", genome_id, decided.purpose.value)
    return decided


def retire_pending_seat(genome_id: str, *, note: str = "", settings: Settings) -> PendingSeat:
    """Stage 2, no: take a shelved card off the shelf without ever seating it.

    Legal only from `"shelved"` -- `PendingSeatIllegalTransition` otherwise. The overlay is not
    touched (a retired card was never on the desk to begin with, since only `seat_pending_seat`
    writes it), and this is final: `request_seat` treats `"retired"` as decided exactly like
    `"rejected"`.
    """
    decided = _transition(genome_id, "retired", note=note, settings=settings)
    logger.info("promotion: %s retired from the shelf, was never seated", genome_id)
    return decided


def _write_overlay(seats: Mapping[str, Sequence[str]], *, settings: Settings) -> None:
    """Replace the roster overlay wholesale. :func:`seat_on_desk` only ever *adds*; this is the one
    place that can remove, and it exists for :func:`migrate_seated_to_pending`. Same atomic
    temp-then-`Path.replace` write, for the same reason: a desk request reading mid-write must see one
    complete file or the other.

    Runs under `_ROSTER_OVERLAY_LOCK`, same as :func:`seat_on_desk` -- `_ROSTER_OVERLAY_LOCK` is
    reentrant, so `migrate_seated_to_pending` holding it across its own read-decide-write span and then
    calling this function is safe, not a deadlock."""
    with _ROSTER_OVERLAY_LOCK:
        path = roster_overlay_path(settings)
        payload = {
            "version": 1,
            "seats": {p.value: list(seats.get(p.value, ())) for p in Purpose},
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)


def migrate_seated_to_pending(*, settings: Settings) -> tuple[PendingSeat, ...]:
    """Move cards the loop seated *before* the approval gate existed into the queue as pending, and
    take them off the desk.

    **Why this exists rather than grandfathering them.** By the time approval was added, the loop had
    already seated 25 cards (18 roth, 7 trading) that no person had looked at -- the exact situation
    the gate was built to prevent, sitting in the desk it protects. Leaving them would have meant the
    gate applied only to cards promoted after an arbitrary date, which is not a rule anyone could
    state later without checking a commit timestamp.

    Each migrated card keeps its real evidence: the `PromotionRecord` that seated it supplies the
    generations, window sets, median, holdout median and q-value, so an approver sees exactly what the
    loop saw. A seat with no promotion record is still migrated, with an explicit `reason` saying its
    evidence could not be found -- an unexplained seat is the *most* important one for a person to
    look at, so it must not be the one case that silently stays on the desk.

    **Idempotent, and it never overrides a decision.** An `agent_id` that already has a queue row is
    left alone and stays off the desk unless that row is approved -- so running this twice does not
    resurrect a rejection, and re-running after a partial failure finishes the job rather than
    starting a second one.

    **The whole migration runs under `_ROSTER_OVERLAY_LOCK`.** Reading the overlay, filing requests for
    every seat found in it, and clearing it are one logical step -- a seat approval or another migration
    landing in the middle would let this function read a snapshot of the overlay that a concurrent
    writer then partially overwrites before this function's own final `_write_overlay` clears it,
    dropping whichever seat the concurrent writer added. `request_seat` (called per candidate below)
    takes `_PENDING_SEATS_LOCK` internally, a different lock, so nesting it inside this function's own
    `_ROSTER_OVERLAY_LOCK` cannot deadlock against `seat_pending_seat` (which acquires the two locks
    sequentially, never nested, in the same PENDING-then-OVERLAY order).
    """
    with _ROSTER_OVERLAY_LOCK:
        overlay = read_overlay(settings)
        if not any(overlay.get(p.value) for p in Purpose):
            return ()

        by_agent = {record.agent_id: record for record in load_promotions(settings)}
        already = {row.genome_id for row in read_pending_seats(settings)}

        created: list[PendingSeat] = []
        now = dt.datetime.now(dt.UTC)
        for purpose in Purpose:
            for agent_id in overlay.get(purpose.value, ()):
                if agent_id in already:
                    continue
                record = by_agent.get(agent_id)
                if record is not None:
                    seat = PendingSeat(
                        genome_id=record.genome_id,
                        agent_id=record.agent_id,
                        purpose=record.purpose,
                        requested_at=record.promoted_at,
                        generations=record.generations,
                        window_sets=record.window_sets,
                        median_excess=record.median_excess,
                        holdout_median_excess=record.holdout_median_excess,
                        q_value=record.q_value,
                        library_path=record.library_path,
                        reason=(
                            f"seated automatically before approval was required; {record.reason}"
                        ),
                    )
                else:
                    seat = PendingSeat(
                        genome_id=agent_id,
                        agent_id=agent_id,
                        purpose=purpose,
                        requested_at=now,
                        generations=(),
                        window_sets=(),
                        median_excess=Decimal(0),
                        holdout_median_excess=None,
                        q_value=None,
                        library_path="",
                        reason=(
                            "seated automatically before approval was required, and no promotion "
                            "record for it could be found -- approve only if you can account for it "
                            "another way"
                        ),
                    )
                created.append(request_seat(seat, settings=settings))

        # Clear the desk only after every request is safely filed. The other order can leave a card
        # un-seated with nothing recorded asking for it back.
        _write_overlay({p.value: () for p in Purpose}, settings=settings)
        logger.info(
            "promotion: migrated %d automatically-seated card(s) into the approval queue", len(created)
        )
        return tuple(created)

"""The supervisor thread that drives an endless generation -> run -> score -> promote loop.

**Why this module exists at all.** Every other module in `app.evolution` answers "what does one
generation do" (`proposer` breeds it, `execute` runs it, `feedback` scores it, `promotion` gates it).
None of them answers "who calls those in order, forever, and reacts when one of them fails or the
engine is busy" -- that is this module's entire job, and it does nothing else. It holds no scoring
logic, no proposing logic, no promotion rule: every one of those is reached through an injected
`Collaborators` callable, never imported and called directly by name, so this module's own tests never
need the real (and, at the time this was written, not-yet-written) sibling packages.

**Why an in-process daemon thread, not a subprocess, exactly like `app.tournament.jobs`.**
`app.tournament.jobs`'s module docstring recounts `strategy-program/DEFECTS.md` D3: a round launched
detached from a shell script had no completion signal, was killed by name rather than by its own
cancellation path, and a second run then fought the zombie for the bar store -- 135 card-runs, zero
results, recorded as ordinary failures. This module is that same lesson applied one layer up: a loop
that runs *generations* of rounds is even longer-lived than a single round, so the case for an
in-process thread with a `threading.Event` a caller can actually set (rather than a process a caller
can only guess at) is stronger here, not weaker.

**Why at most one loop, process-wide, mirroring `jobs._Registry`.** The loop's own generations already
serialise through `app.tournament.jobs`'s single engine slot (see below), but a second *loop* started
alongside the first would mint its own round ids, its own genomes, and its own ledger entries that the
first loop's history knows nothing about -- two supervisors is not "twice the search", it is two
sources of truth for one ledger. `start_loop` raises `LoopAlreadyRunning` for the same reason
`jobs.start_job` raises `JobAlreadyRunning`, and for the same underlying host constraint (16 GB
physical, and `app.tournament.jobs`'s own module docstring on what two contended readers of the DuckDB
bar store actually do).

**`JobAlreadyRunning` is "wait", not "fail".** The engine's single execution slot belongs to
`app.tournament.jobs`, not to this loop -- a person can launch an ordinary round by hand at any time,
and when they do, this loop's own call into `run_generation` (which eventually reaches
`jobs.start_job`) raises `jobs.JobAlreadyRunning`. Treating that as a failed generation would turn
routine, expected contention into a stream of spurious `GenerationOutcome(status="failed")` records
that say nothing true about the *candidates* -- they never ran at all. The supervisor instead logs the
wait, sleeps briefly (checking the stop event so a stop during a wait is still responsive), and retries
the identical generation, indefinitely, until the slot frees up or the loop is stopped.

**A failing generation must not kill the loop -- but an unbroken run of them must.** Every exception a
collaborator raises during one generation's proposing/running/scoring/promoting is caught, recorded on
that generation's own `GenerationOutcome` as `status="failed"`, logged, and walked past -- exactly the
same shape as `jobs._worker`'s per-card failure handling, one level up. That rule is correct for a
single bad generation and was, for a long time, applied without qualification. A loop left running in
Docker then produced 1,673 generations, 1,644 of them failing with the identical `OSError` writing a
generated card to a read-only mount -- the same class of failure, forever, because nothing about
retrying the *next* generation could ever fix a read-only filesystem. `_run` now tracks *consecutive*
failures across generations (any success resets the count to zero; a `"cancelled"` generation counts as
neither a failure nor a success and leaves the count untouched) and, once `_MAX_CONSECUTIVE_FAILURES`
is reached, stops the loop itself -- `LoopStatus.state = "failed"`, with `LoopStatus.error` naming the
repeated cause and the count. This is the *only* new way a single generation's outcome can end the
loop; an exception that escapes the outer `while` loop itself (for instance, a ledger that cannot be
opened at all) still sets `LoopStatus.state = "failed"` exactly as before, and a single bad generation,
or a handful of intermittent ones separated by successes, still never does.

**Pre-registration, mechanised.** `strategy-program/ROUND-16-PLAN.md` (and every plan before it) is
written *before* the round it describes exists, precisely so a reader can check the round's own
predictions against what actually happened rather than trust a retrospective narrative. A loop that
mints a hundred generations a day cannot get a hand-written plan document for each one, so
`gen{N:04d}/PLAN.md` is this module's mechanised stand-in: written the moment the candidate list is
known -- immediately after proposing, *before* `write_cards` persists a single card to disk and before
the first card of the generation runs -- naming the round id, the purpose, the window split and every
candidate's genome and thesis. `tests/test_evolution_loop.py` asserts this ordering from *inside* a
fake `run_generation` (the only way to prove the file existed before that call, not merely before the
generation finished) and, separately, from inside a fake `write_cards` that raises: a production
incident (see `_MAX_CONSECUTIVE_FAILURES`) showed `write_cards` itself failing with a read-only
filesystem 411 times, and a plan written only *after* that call would have left every one of those
generations with no pre-registration record at all -- exactly the failure a plan is supposed to make
legible. Nothing this generation's plan needs (round id, purpose, windows, config, every genome's
universe and notes) depends on `write_cards` or `run_generation` having happened, so the plan is
written whole, in one step, rather than split into a proposed-first/run-later two-part document.

**No persistence across a restart**, matching `app.tournament.jobs.JobList`'s own note on the same
point. The loop's *history* (genomes, plans, outcomes, the ledger) is written to disk under
`app.evolution.models.loop_root` as it happens and survives a restart; the *supervisor's own live
status* -- which generation is in flight, the bounded log, the process-wide "is one running" lock --
does not, and a restarted process finds no loop running until `POST /api/competition/loop` starts one.

**A fresh loop starts counting generations from one past whatever `loop_root` already holds, never
from `1` unconditionally -- see `_first_generation_number` for the full mechanism.** The paragraph
above is exactly why this has to be true: the supervisor's live status resets to nothing on every
restart, but `gen{N:04d}/OUTCOME.json` -- this generation's full, permanent record, per
`_write_outcome_file`'s own docstring -- does not. A tree already holding `gen0001`..`gen0028` from an
earlier day's loop, restarted for what was meant to be one further generation, once wrote that
generation straight to `gen0001` -- silently replacing a `succeeded` outcome carrying 10 standings with
a new `succeeded` outcome carrying 4. Because `data/loop/` is gitignored deliberately (see "Auto-
generated rounds" below), there was no copy anywhere else; the original record was simply gone, and a
longer restarted run would have overwritten `gen0002`, `gen0003`, and so on right behind it, one
generation at a time. `_write_outcome_file` additionally now refuses, raising
`GenerationDirectoryCollision` rather than overwriting, if a `gen{N:04d}/OUTCOME.json` already on disk
carries a *different* `round_id` than the one it is about to write -- belt and braces against the same
failure mode from a second angle (two loops, or two processes, sharing one `loop_root`) even when the
starting-offset computation above is somehow bypassed or beaten to the directory first.

**Auto-generated rounds live under `loop_root`, never under `data/rounds/`.** `data/rounds/` is
git-tracked *deliberately* -- `.gitignore` names it explicitly as the one exception, because it is the
human programme's permanent, committed record, and `app.tournament.results.list_rounds` reads it to
populate the Competition page's round selector. A loop minting a fresh round directory every
generation, forever, would both bloat that commit history and flood that selector with runs no person
asked for. `loop_rounds_root` (`loop_root(settings) / "rounds"`) is a sibling tree instead: disposable
working output that lives beside the loop's own genomes and ledger, not the programme's committed
record. `next_round_sequence` is still consulted against the *real* `settings.rounds_dir`, so a minted
`round_id`'s ordinal keeps ordering on the same axis as the human programme's rounds (a loop started
after round 16 mints `r17-...`) -- only where the round's files land differs.

**Selection windows rotate by default; see `_resolve_selection_windows` for the full reasoning.** In
short: `evaluate_promotions` only counts two generations as independent evidence when they ran on
differing window sets, so a supervisor using one fixed set forever could search endlessly and promote
nothing. Each of a lane's appearances therefore drops one window from the default pool,
deterministically, unless `config.windows` was set explicitly -- in which case it is honoured exactly
and never rotated, which means promotions can never accumulate evidence purely from generations run
under that one config.

**Incumbents can reappear.** `proposer.propose_generation` may return a previous generation's elite
genomes unchanged (same `genome_id`, same original `generation` field) alongside newly bred offspring,
specifically so the same candidate can run again on a *different* window set and accumulate the second
piece of promotion evidence the paragraph above describes. This module never assumes every genome in a
generation's `genomes` tuple carries `generation == <the current generation number>`, and the same
tuple -- incumbents included -- is what gets passed to `read_standings`, `derive_findings` and
`evaluate_promotions`, unfiltered.

**Lanes: the supervisor cycles every generation through a `(purpose, shape)` pair, not through purpose
alone.** `app.tournament.results.build_leaderboard` ranks only the larger of an `"entry-notional"`
(`"rules"`) and an `"invested-value"` (`"allocation"`) group when a field mixes the two shapes --
everything in the smaller group is silently left out of the board (`unscored_reason`), which is
exactly what proposing both shapes into one generation produced: 4 proposed, 12 runs, 0 failures, only
2 ranked. `_lanes_for(config)` is every `(purpose, shape)` pair for `purpose in config.purposes` and
`shape in ("rules", "allocation")`, and generation `N` (one-indexed) works
`lanes[(N - 1) % len(lanes)]` -- a fixed round-robin, so a lane recurs exactly every `len(lanes)`
generations. **Elites are kept per lane, in `_run`'s `elites_by_lane` dict keyed by `(purpose,
shape)`, not one pool shared across every generation.** A pool shared across lanes would hand an
allocation generation a `"rules"`-shaped elite (or vice versa) to breed from -- `Genome.shape` is
fixed at proposal time and a crossover cannot silently reshape a parent, so those elites would either
be wasted or, worse, quietly bred as if they were founders of the wrong shape. Each lane's history is
its own lineage: it only ever sees its own prior elites, and `_resolve_selection_windows`'s
`lane_occurrence` parameter (not the absolute generation number) is what keeps a lane's own
*consecutive* appearances on differing window sets even though other lanes' generations now run
between them -- see that function's own docstring.
"""

from __future__ import annotations

import datetime as dt
import inspect
import json
import random
import re
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from app.agents.models import (
    AgentBudget,
    AgentDisabled,
    AgentProposal,
    AgentUnavailable,
    BudgetExhausted,
)
from app.config import Settings, get_settings
from app.evolution import digest
from app.evolution.amend import apply_amendments
from app.evolution.goal_directives import goal_directive_notes
from app.evolution.models import (
    AmendmentRecord,
    CardShape,
    Finding,
    GenerationOutcome,
    Genome,
    LoopAlreadyRunning,
    LoopConfig,
    LoopNotRunning,
    LoopPhase,
    LoopState,
    LoopStatus,
    PromotionRecord,
    Standing,
    UnreachablePromotionCeiling,
    generation_review_path,
    loop_root,
    next_round_sequence,
)
from app.tournament.jobs import MAIN_WINDOWS, MIN_ELIGIBLE_MAIN_WINDOWS, JobAlreadyRunning
from app.tournament.purposes import Purpose

if TYPE_CHECKING:
    # `app.agents.review_models` is a sibling package being written concurrently with this fix and may
    # not exist yet -- the same situation `app.agents.designer` was in when this module first imported
    # `AgentProposal`/`AgentBudget` unconditionally (both are stable, dependency-light type modules, not
    # the heavier `app.agents.designer`/`app.agents.reviewer` themselves, which is why those two are
    # guarded in `default_collaborators` instead). Nothing below needs `GenerationReview` to be a real
    # class at runtime: `_run_review` only reads attributes off whatever `Collaborators.review_generation`
    # returns, exactly like every other collaborator call in this module, so this import is guarded to
    # type-checking only.
    from app.agents.review_models import GenerationReview

__all__ = [
    "Collaborators",
    "GenerationDirectoryCollision",
    "default_collaborators",
    "get_status",
    "loop_rounds_root",
    "reset",
    "start_loop",
    "stop_loop",
]

#: Bounded log, matching `app.tournament.jobs._LOG_MAXLEN` exactly -- the same rationale: a caller
#: polling `GET /api/competition/loop` gets the tail of the supervisor's own narration, not an
#: unbounded memory leak from a loop that is meant to run forever.
_LOG_MAXLEN = 200

#: Bounded in-memory generation history. The full history is never lost -- every generation's
#: `GenerationOutcome` is also written to `gen{N:04d}/OUTCOME.json` under `loop_root` -- this cap only
#: bounds what a single `LoopStatus` snapshot carries in memory for a loop that may run for days.
_HISTORY_MAXLEN = 20

#: How long the supervisor waits before retrying a generation whose engine call raised
#: `JobAlreadyRunning`. Short and interruptible (checked against the stop event in slices, never a bare
#: `time.sleep`) so a stop request during a wait is still responsive, and short enough that this
#: module's own tests -- which exercise the retry path directly -- stay well under a second.
_ENGINE_BUSY_RETRY_SECONDS = 0.05

_MAX_CONSECUTIVE_FAILURES = 5
"""How many *consecutive* failed generations the supervisor tolerates before it stops itself.

**The evidence this number is traceable to.** A loop left running in Docker produced 1,673
generations: 27 succeeded, 1 was cancelled, and 1,644 failed -- 411 times each across several genome
ids -- with the identical `OSError: [Errno 30] Read-only file system` writing a generated card under
`/app/backend/app/paper/library/generated/`. That is the incident the module docstring's "A failing
generation must not kill the loop" section describes: the per-generation catch-and-continue rule is
correct in isolation (a transient failure should not stop a search that is otherwise working) and was
wrong in aggregate, because nothing about moving on to the *next* generation could ever repair a
read-only mount. Five is deliberately nowhere near 1,644: large enough that an ordinary run of bad luck
(a flaky network call, one malformed candidate) does not trip it, small enough that a systemic fault --
the kind this incident actually was -- halts the loop within a handful of generations instead of
burning CPU for the rest of the process's life and producing nothing.

**Any success resets the count to zero.** The breaker exists to catch an *unbroken* run of identical
failure, not to penalise a loop that fails occasionally but keeps finding successes in between -- see
`_run` for where the reset happens. A `"cancelled"` generation (the engine was stopped mid-run) is
neither a failure nor a success and does not move the count in either direction: the candidates never
ran to completion, so a cancellation says nothing about whether they work.

**A module constant, not a `LoopConfig` field.** `models.py` is owned by a different worker while this
fix lands, and a config field is not obviously the right shape anyway -- a fixed, evidence-derived
tripwire that a caller cannot accidentally configure away is safer than a per-run knob for a value this
module docstring can point at a specific incident to justify. `_run` is the only reader.
"""

_MAX_REVIEWER_KEPT_ELITES = 3
"""How many genomes a reviewer's own `per_candidate[].keep=True` notes may add to a lane's elite set,
on top of whatever `feedback.select_elites` (the deterministic ranking) already chose.

**This is the fix for "only first place is tracked."** `select_elites` keeps only the top
`LoopConfig.elite_count` standings by `median_excess` -- a candidate that placed 6th and still cleared
the holdout has no way to breed forward under that rule alone, however the reviewer reads its numbers.
`_run_review` lets the reviewer add such a candidate, but never lets it *remove* one `select_elites`
already picked -- see that function's own docstring for why the deterministic ranking has to stay the
one part of this a reader can reproduce without trusting a model's judgement.

**A small, fixed bound, not `LoopConfig.elite_count` again.** `elite_count`'s own floor is 1, so
reusing it here would let a one-elite lane's breeding population double from a single review's say-so.
3 is deliberately small relative to `LoopConfig.population`'s own floor of 2 candidates -- a review's
additions stay a minority of any lane's next generation, never a replacement for the deterministic
elites they sit beside. A module constant, not a `LoopConfig` field, for the same reason
`_MAX_CONSECUTIVE_FAILURES` is one: a fixed, evidence-shaped tripwire a caller cannot configure away.
"""

_SHAPES: tuple[CardShape, ...] = ("rules", "allocation")
"""Every card shape a lane can breed, in a fixed order so `_lanes_for`'s output is reproducible
across processes -- see that function's own docstring for why a lane must be shape-homogeneous."""

_ROUND_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
"""Copied from `app.tournament.jobs._ROUND_ID_PATTERN`, not imported -- that name is private to its
own module. A minted `r{N}-auto-{timestamp}` id is always lowercase digits, hyphens and the literal
`"auto"`, so this can only fail if `next_round_sequence` or the timestamp format ever changes shape;
the check exists so that failure is a loud `ValueError` naming the bad id rather than a card silently
written under a round directory `app.tournament.jobs` would itself refuse to accept."""

_GEN_DIR_PATTERN = re.compile(r"^gen(\d+)$")
"""Matches exactly a generation directory's name (`gen0001`, `gen1673`, ...) and nothing else that
`loop_root` also holds -- see `_first_generation_number`'s own docstring for the incident this exists
to prevent. Anchored and digits-only deliberately: `genomes/` (a real sibling of every `gen{N:04d}/`
directory under `loop_root`, holding the loop's genome archive) starts with the same three letters
"gen" a generation directory does. `str.removeprefix("gen")` on `"genomes"` leaves `"omes"`, and
`int("omes")` raises `ValueError` -- a naive scan built that way crashes the loop at startup on the
one directory that is guaranteed to already exist. `_GEN_DIR_PATTERN.fullmatch("genomes")` simply
returns `None` (the fourth character is `"o"`, not a digit or end-of-string) so the entry is skipped
like any other non-generation directory, no `try`/`except` required."""


class GenerationDirectoryCollision(RuntimeError):
    """Raised by `_write_outcome_file` when `gen{N:04d}/OUTCOME.json` already exists on disk for a
    *different* `round_id` than the one about to be written.

    **Why this lives here and not on `LoopAlreadyRunning`'s side of the ledger.** `models.py` already
    guards against two *loops* running at once (`start_loop` raises `LoopAlreadyRunning` -- see the
    module docstring's "at most one loop, process-wide" section), which is `models.py`'s call to make
    and is owned by a different worker while this fix lands. That guard is a purely in-process lock,
    though, and says nothing about two *processes* -- a second server instance, a loop restarted
    against a data directory another one is still writing to -- sharing one `loop_root` on disk. This
    exception is `_write_outcome_file`'s own belt-and-braces check for exactly that case: even with
    `_first_generation_number` computing a correct starting offset (see that function's own docstring),
    a second writer choosing its own, independently-computed starting offset against the same tree can
    still land on a generation number the first writer already claimed. Refusing to overwrite and
    raising loudly turns that collision into a failed loop (`_run`'s outer `except Exception` catches
    this exactly like any other supervisor-killing failure) instead of a second silent data-loss
    incident on top of the one `_first_generation_number` was written to fix.
    """


def _first_generation_number(root: Path) -> int:
    """The generation number a fresh loop must start counting from: one past the highest
    `gen<digits>` directory already on disk under `root` (normally `loop_root(settings)`), or `1`
    when `root` does not exist or holds no such directory.

    **The incident this function exists to fix.** Before it existed, `_run` always began a fresh loop
    at `generation_number = 1`, unconditionally -- correct the very first time a loop is ever started
    against a given `loop_root`, and silently wrong every time after, because `LoopStatus` (the
    supervisor's in-memory "what generation are we on") does not survive a process restart (see the
    module docstring's "No persistence across a restart" section) while `gen{N:04d}/OUTCOME.json` on
    disk does. A tree already holding `gen0001`..`gen0028` from an earlier day's loop, restarted the
    next day for what was meant to be one more generation, wrote that generation straight to `gen0001`
    -- overwriting a `succeeded` outcome carrying 10 standings with a new `succeeded` outcome carrying
    4. `data/loop/` is gitignored *deliberately* (see the module docstring's "Auto-generated rounds"
    section, and `_write_outcome_file`'s own docstring calling this file "this generation's full,
    permanent record"), so there was no copy anywhere else to recover the original from -- it is simply
    gone. A longer restarted run would not have stopped at `gen0001`: it would have walked forward
    through `gen0002`, `gen0003`, and so on, overwriting one earlier generation's permanent record per
    generation it ran. `_run` now calls this function exactly once, before its first generation, in
    place of the hard-coded `1` that produced that incident.

    **Takes the maximum directory number, never the count of directories.** A stray `gen1673` --
    literally the generation count `_MAX_CONSECUTIVE_FAILURES`'s own read-only-filesystem incident
    produced, and a real, present entry under this codebase's own `loop_root` at the time of writing --
    can sit alongside only 29 other generation directories (`gen0001`..`gen0028`, say). Returning
    `(number of gen directories found) + 1` would return 29 and walk this same defect right back in,
    one restart at a time, from `gen0029` up to `gen1673`. Only `max(numbers found) + 1` is safe.

    **Skips anything that is not exactly `gen<digits>`, rather than raising.** See `_GEN_DIR_PATTERN`'s
    own docstring for `genomes/` specifically -- the one entry under `loop_root` guaranteed to look
    like a generation directory's name-prefix and not be one. `rounds/`, `news_cache/`, `ledger.jsonl`,
    `promotions.jsonl`, `roster_overlay.json` and `amendments.jsonl` are the rest of `loop_root`'s real,
    non-generation contents; every one of them must leave a fresh loop able to start, not crash it
    before its first generation even runs -- a loop that cannot start because its own working tree
    holds the files it is documented to hold would be a worse defect than silent overwriting.

    **Computed once, by `_run`, before its own first generation -- see that function for the call
    site.** A directory appearing under `root` *during* the run this number is used for (another
    process, a manual copy) must not change where this loop's own next generation lands; recomputing
    per generation would let exactly that happen, and would also make a single loop's own generation
    numbers non-monotonic if such a directory's number happened to be lower than one already claimed.
    """
    highest = 0
    if not root.exists():
        return 1
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        match = _GEN_DIR_PATTERN.fullmatch(entry.name)
        if match is None:
            continue
        highest = max(highest, int(match.group(1)))
    return highest + 1


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def loop_rounds_root(settings: Settings) -> Path:
    """`loop_root(settings) / "rounds"` -- where the supervisor writes its own auto-generated rounds.

    Deliberately not `settings.rounds_dir`; see the module docstring's "Auto-generated rounds" section
    for why the two must never be the same directory. This is `start_loop`'s default `output_root`;
    an explicit `output_root` argument (what this module's own tests pass) still overrides it.
    """
    return loop_root(settings) / "rounds"


def _accepts_kwarg(func: Callable[..., object], name: str) -> bool:
    """Whether calling `func` with keyword argument `name` is safe, judged by introspection rather
    than by calling it and catching `TypeError`.

    Exists for exactly one call site: `feedback.read_standings` was specified to this module's author
    without a `rounds_root` parameter, but the loop's rounds live under `loop_rounds_root`, not
    `settings.rounds_dir`, so `read_standings` needs to be told where to look if it is going to find
    them. Rather than guess at a signature another, concurrently-written module may or may not have
    grown, this checks first and calls accordingly -- a real function or a test fake that does not
    accept the parameter is called exactly as it was before; one that does accept it (or takes
    `**kwargs`) is told the loop's own root. `inspect.signature` failing outright (some C builtins)
    is treated as "assume yes" so the call is attempted and any real mismatch fails loudly there
    instead of silently here.
    """
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return True
    parameters = signature.parameters.values()
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters):
        return True
    return name in signature.parameters


# ---------------------------------------------------------------------------
# Collaborators -- everything the supervisor calls out to, injected
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Collaborators:
    """Every module the supervisor calls out to, injectable so the loop can be tested without them.

    Five sibling packages under `app.evolution` (`proposer`, `execute`, `feedback`, `ledger`,
    `promotion`, `news_signal`) were being written concurrently with this module and did not
    necessarily exist yet at the time it was written. Rather than import any of them at module scope
    -- which would make importing `app.evolution.loop` itself fail while a sibling was mid-edit -- the
    supervisor never names them directly. `default_collaborators` is the only place their real
    implementations are wired in, and it does so lazily, at call time. Every test in
    `tests/test_evolution_loop.py` builds its own `Collaborators` out of fakes instead.
    """

    propose: Callable[..., tuple[Genome, ...]]
    write_cards: Callable[..., dict[str, Path]]
    card_for: Callable[[Genome], object]
    run_generation: Callable[..., object]
    read_standings: Callable[..., tuple[Standing, ...]]
    derive_findings: Callable[..., tuple[Finding, ...]]
    select_elites: Callable[..., tuple[Genome, ...]]
    ledger_entries_for: Callable[..., tuple[object, ...]]
    evaluate_promotions: Callable[..., tuple[PromotionRecord, ...]]
    trending_symbols: Callable[..., tuple[str, ...]]
    open_ledger: Callable[[Settings], object]

    load_seen_genomes: Callable[[Settings], Mapping[str, Genome]] | None = None
    """Optional. `proposer.load_seen_genomes` -- every card already proposed, keyed by content
    digest, so `propose` can recognise a rediscovery instead of minting a second id for it. `None`
    (or a `propose` that does not accept `seen`) leaves the older behaviour exactly as it was, which
    is what keeps the test fakes in `tests/test_evolution_loop.py` working unchanged."""

    field_window_medians: Callable[..., Mapping[str, Decimal]] | None = None
    """Optional. `feedback.field_window_medians` -- a per-window median-excess breakdown across a
    round's whole field -- is what lets `derive_findings`'s `kind="regime"` finding name *which*
    window the field did worst in; `Standing` deliberately carries no per-window detail (see that
    model's own docstring), so without this the regime finding degrades to a permanent "no data"
    sentence. Defaulted to `None`, and only a late addition to this dataclass, so that neither an
    older test double nor a `default_collaborators()` built before `feedback` grew this function has
    to change -- `_execute_generation` calls it only when it is not `None`, and treats its failure as
    non-fatal enrichment (logged, generation still succeeds with `window_medians=None`) rather than as
    a reason to fail the whole generation the way a `run_generation`/`read_standings` failure would.
    """

    design_generation: (
        Callable[..., tuple[tuple[Genome, ...], AgentProposal, AgentBudget]] | None
    ) = None
    """Optional. `app.agents.designer.design_generation` -- the Claude-backed alternative to `propose`.
    See `app.agents.models`'s module docstring for what it is allowed to do (phase 1 only, no number
    it emits is a measurement) and why calling it can never be load-bearing.

    Defaulted to `None` for the same reason `field_window_medians` is: an older test double, and a
    `default_collaborators()` built before `app.agents.designer` existed, both keep working unmodified.
    `_execute_generation` only ever attempts it when `LoopConfig.use_agent` is set *and* this is not
    `None` -- with `use_agent=False` (the default) it is never called even when wired, so turning the
    agent off costs nothing but the deterministic proposer's own runtime, exactly as documented on
    `LoopConfig.use_agent`.

    Every one of `AgentUnavailable`, `BudgetExhausted`, `AgentDisabled`, and any other exception this
    raises is caught by `_propose_genomes` and turned into a fall-back call to `propose` for that one
    generation -- never a failed generation, never a stalled loop. See that function's own docstring
    for the exact fallback sequence and for why the running `AgentBudget` lives on `_Loop` rather than
    being threaded back through `Collaborators` itself (a `Callable` field cannot carry mutable state
    between calls; `_Loop.agent_budget` can).
    """

    review_generation: (
        Callable[..., tuple[GenerationReview, AgentBudget]] | None
    ) = None
    """Optional. `app.agents.reviewer.review_generation` -- the model-written review of a generation
    that has already been scored, and the source of the `ProposedAmendment`s
    `app.evolution.amend.apply_amendments` folds into that same lane's *next* generation.

    Defaulted to `None` for exactly the reason `design_generation` is: an older test double, and a
    `default_collaborators()` built before `app.agents.reviewer` existed, both keep working unmodified.
    `_run_review` only ever attempts it when `LoopConfig.use_reviewer` is set *and* this is not `None`
    -- with `use_reviewer=False` (the default) it is never called even when wired, so turning the
    reviewer off costs nothing but `_run_review`'s own no-op check, exactly as documented on
    `LoopConfig.use_reviewer`.

    Every exception this raises -- `AgentUnavailable`, `BudgetExhausted`, or anything else -- is caught
    by `_run_review` and turned into "no review this generation": never a failed generation (the
    generation's own `GenerationOutcome` was already computed before `_run_review` is ever called), and
    deliberately never counted by `_run`'s consecutive-failure circuit breaker -- see `_run_review`'s
    own docstring for why a commentary layer must not be able to stop a search that is otherwise
    working. The running `AgentBudget` lives on `_Loop`, shared with `design_generation` -- one cap
    for the whole run, not one per collaborator -- for the same reason `design_generation`'s own
    docstring gives for why it cannot live on `Collaborators` itself.
    """


def default_collaborators() -> Collaborators:
    """The real sibling modules, wired together. Imported here, at call time, and nowhere else.

    Calling this before every sibling package exists raises `ModuleNotFoundError` -- which is the
    correct behaviour for a loop actually being started, and is why `start_loop` does not call this
    itself unless the caller withheld an explicit `collaborators`. It is never called by this module's
    own test suite.
    """
    from app.evolution import execute, feedback, news_signal, promotion, proposer
    from app.evolution import ledger as ledger_module

    # `app.agents.designer` is a sibling package being written concurrently with this fix and may not
    # exist yet -- unlike the five `app.evolution` siblings above, whose absence this function is
    # documented to fail loudly on, a missing agent designer is exactly the degrade-not-fail case
    # `LoopConfig.use_agent`'s own docstring describes: the loop must still start and run on its
    # deterministic proposer. So this one import is caught, not left to propagate.
    try:
        from app.agents import designer as designer_module
    except ModuleNotFoundError:
        design_generation = None
    else:
        design_generation = designer_module.design_generation

    # `app.agents.reviewer` is a second sibling package, also written concurrently with this fix and
    # also not guaranteed to exist yet -- guarded exactly like `app.agents.designer` just above, and
    # independently: one landing before the other must not block either from being wired in.
    try:
        from app.agents import reviewer as reviewer_module
    except ModuleNotFoundError:
        review_generation = None
    else:
        review_generation = reviewer_module.review_generation

    return Collaborators(
        propose=proposer.propose_generation,
        load_seen_genomes=proposer.load_seen_genomes,
        write_cards=proposer.write_cards,
        card_for=proposer.card_for,
        run_generation=execute.run_generation,
        read_standings=feedback.read_standings,
        derive_findings=feedback.derive_findings,
        select_elites=feedback.select_elites,
        ledger_entries_for=feedback.ledger_entries_for,
        evaluate_promotions=promotion.evaluate_promotions,
        trending_symbols=news_signal.trending_symbols,
        open_ledger=ledger_module.Ledger.open,
        field_window_medians=feedback.field_window_medians,
        design_generation=design_generation,
        review_generation=review_generation,
    )


# ---------------------------------------------------------------------------
# Mutable state for one loop, guarded by its own lock -- mirrors `jobs._Job` exactly
# ---------------------------------------------------------------------------


class _Loop:
    """One supervisor's mutable state, guarded by its own lock.

    Every field below is written by (at most) one worker thread and read by any number of concurrent
    HTTP requests polling `GET`. The lock exists so a reader never observes a torn update, the same
    contract `app.tournament.jobs._Job` has, and for the same reason -- see that class's docstring.
    """

    def __init__(
        self,
        *,
        config: LoopConfig,
        settings: Settings,
        collaborators: Collaborators,
        output_root: Path | None,
    ) -> None:
        self.loop_id = uuid.uuid4().hex
        self.config = config
        self.settings = settings
        self.collaborators = collaborators
        self.output_root = output_root

        self.state: LoopState = "running"
        self.phase: LoopPhase = "idle"
        # `self.generation` is the absolute, on-disk generation number -- the same number
        # `_first_generation_number` seeds `_run`'s local `generation_number` from, which after a
        # restart against a non-empty `loop_root` is *not* 1 (see that function's own docstring).
        # `self.completed_generations` is deliberately a different axis: how many generations *this*
        # loop run has itself completed, always starting at 0 regardless of where numbering resumed --
        # it is what `LoopConfig.max_generations` is compared against (see `_run`), and a restarted
        # loop asked for "3 more generations" must stop after 3 regardless of whether it started at
        # generation 1 or generation 1674. The two fields are deliberately not kept equal; a caller
        # rendering `LoopStatus` wants both -- "where are we in the permanent record" from `generation`,
        # "how much has this run itself done" from `completed_generations`.
        self.generation = 0
        self.completed_generations = 0
        self.candidates_tested = 0
        self.started_at: dt.datetime | None = None
        self.updated_at: dt.datetime | None = None
        self.stopped_at: dt.datetime | None = None
        self.current_round_id: str | None = None
        self.current_job_id: str | None = None
        self.current_purpose: Purpose | None = None
        self.best: Standing | None = None
        self.promotions: tuple[PromotionRecord, ...] = ()
        self.history: deque[GenerationOutcome] = deque(maxlen=_HISTORY_MAXLEN)
        self.log: deque[str] = deque(maxlen=_LOG_MAXLEN)
        self.error: str | None = None

        # The consecutive-failure circuit breaker's own state -- see `_MAX_CONSECUTIVE_FAILURES`'s
        # docstring for the incident this exists to catch and `_run` for where both fields are read
        # and written. `consecutive_failures` counts an unbroken run of `status="failed"` generations
        # only: any `"succeeded"` generation resets it to zero, and a `"cancelled"` one leaves it
        # untouched (see `_run`). `last_failure_error` always holds the most recent failed
        # generation's `GenerationOutcome.error`, independent of the streak length, so the message
        # written to `LoopStatus.error` when the breaker trips can name the repeated cause even though
        # only the count, not the text, is what actually trips it.
        self.consecutive_failures = 0
        self.last_failure_error: str | None = None

        # The reviewer's own state, mirrored on the loop for `LoopStatus` -- see `LoopStatus.
        # latest_review_headline`/`latest_review_verdict`/`amendments_applied`'s own docstrings. The
        # full `GenerationReview` is never held here; it is written once, to `gen{N:04d}/REVIEW.json`,
        # and this is only enough for the panel to show that a review happened and roughly what it said.
        self.latest_review_headline: str | None = None
        self.latest_review_verdict: str | None = None
        self.amendments_applied: tuple[AmendmentRecord, ...] = ()

        # The running agent spend, carried across every generation of this loop run -- not reset per
        # generation, because `LoopConfig.agent_budget_usd` is a cap on the *whole run*, not on one
        # generation's call. `None` only ever transiently, before the first `_propose_genomes` call
        # sets it from `config.agent_budget_usd`; see that function's docstring for why it is seeded
        # lazily rather than here, where `config` is already in hand.
        self.agent_budget: AgentBudget | None = None
        # Set the first time `self.agent_budget.exhausted` is observed true, so the loop logs that
        # fact once and then falls silently back to the deterministic proposer for the rest of the
        # run -- a log line every generation for a condition that, once true, stays true for the life
        # of the loop would just be noise.
        self.agent_budget_exhausted_logged = False

        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None

    def append_log(self, line: str) -> None:
        with self.lock:
            self.log.append(line)

    def snapshot(self) -> LoopStatus:
        with self.lock:
            return LoopStatus(
                loop_id=self.loop_id,
                state=self.state,
                phase=self.phase,
                config=self.config,
                generation=self.generation,
                completed_generations=self.completed_generations,
                candidates_tested=self.candidates_tested,
                started_at=self.started_at,
                updated_at=self.updated_at,
                stopped_at=self.stopped_at,
                current_round_id=self.current_round_id,
                current_job_id=self.current_job_id,
                current_purpose=self.current_purpose,
                best=self.best,
                promotions=self.promotions,
                history=tuple(self.history),
                log=tuple(self.log),
                error=self.error,
                latest_review_headline=self.latest_review_headline,
                latest_review_verdict=self.latest_review_verdict,
                amendments_applied=self.amendments_applied,
            )


def _set_phase(loop: _Loop, phase: LoopPhase) -> None:
    with loop.lock:
        loop.phase = phase
        loop.updated_at = _utcnow()


def _sleep_checking_stop(loop: _Loop, seconds: float, *, interval: float = 0.02) -> None:
    """Sleep up to `seconds`, in slices, returning early the moment `loop.stop_event` is set.

    Never a bare `time.sleep(seconds)` -- a stop requested during a cooldown or an engine-busy wait
    must take effect at the next slice boundary, not only after the full wait elapses. Never a bare
    `while not loop.stop_event.is_set(): pass` either -- that would be exactly the spinning-without-a-
    sleep this module's own review gate exists to catch.
    """
    deadline = time.monotonic() + max(seconds, 0.0)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or loop.stop_event.is_set():
            return
        time.sleep(min(interval, remaining))


def _resolve_selection_windows(config: LoopConfig, *, lane_occurrence: int) -> tuple[str, ...]:
    """This lane's selection windows for its `lane_occurrence`-th appearance -- rotated by default,
    fixed when the caller was explicit.

    **Why rotation exists at all.** `app.evolution.promotion.evaluate_promotions` requires the same
    `genome_id` to clear the gate in `config.promotion_consecutive` generations *on window sets that
    differ* -- `PROTOCOL.md` section 6a is explicit that a repeated window set is not a second piece
    of evidence, because re-running an already-frozen, deterministic card on a window it has already
    run recomputes the same number rather than sampling anything new (`A-rotation` returned an
    identical +95.2786% twice under exactly this mistake). A supervisor that used one fixed selection
    set every generation could search forever and promote nothing: every incumbent's repeat runs would
    all land on the same set, and `evaluate_promotions` would correctly refuse to count any of them
    twice.

    **`lane_occurrence`, not the absolute generation number.** The supervisor now cycles every
    generation through a `(purpose, shape)` lane (see the module docstring's "Lanes" section), so two
    *consecutive generations* are almost always two *different* lanes -- `evaluate_promotions`,
    though, only ever compares generations within the same lineage, i.e. within the same lane. Keying
    the rotation off the absolute generation number would let two different lanes land on the same
    `drop_index` by coincidence and, worse, would let the *same* lane repeat a `drop_index` on its
    second appearance whenever `len(lanes)` divides the pool size evenly (four lanes, an eight-window
    pool: every lane's `generation_number % 8` repeats every second visit). `lane_occurrence` --
    "how many times has *this* lane been worked before, 0 for its first appearance" -- increments by
    exactly one every time the lane recurs, so `drop_index` always advances by one step too and two
    consecutive appearances of one lane can never coincide as long as the pool holds more than one
    window.

    **The default (`config.windows` empty): rotate.** The pool is `MAIN_WINDOWS` minus
    `config.holdout_windows`, and each of this lane's appearances drops exactly one pool window,
    chosen by `lane_occurrence % len(pool)`. Two consecutive appearances of the same lane then share
    every window but one -- a real, different `frozenset`, which is what `evaluate_promotions`
    compares -- while staying at or above `MIN_ELIGIBLE_MAIN_WINDOWS` (5) as long as the pool itself
    has at least 6 windows (true for every `holdout_windows` value this package ships as a default: 8
    main windows minus a 2-window holdout leaves a 6-window pool, dropping one lands exactly on the
    floor). A pool at or under that floor cannot drop a window without falling under it, so it is
    returned whole, unrotated, every time -- see the explicit-windows case below for what that costs.

    **When `config.windows` is explicit: honoured exactly, never rotated.** An explicit choice is an
    instruction, not a default this function is free to override. The cost is real and is on the
    caller: every generation started with the same explicit `windows` will use that identical set, so
    no candidate bred under it can ever accumulate two distinct pieces of promotion evidence from
    generations run under this one `LoopConfig` -- the loop will keep searching and scoring, but
    `evaluate_promotions` will never promote anything, unless a later `start_loop` call changes
    `windows` between runs.

    Either way, the holdout set itself never rotates -- it is fixed for the life of the loop, in
    `config.holdout_windows`; a rotating holdout would not be a holdout.
    """
    holdout = set(config.holdout_windows)

    if config.windows:
        return tuple(config.windows)

    pool = tuple(window for window in MAIN_WINDOWS if window not in holdout)
    if len(pool) <= MIN_ELIGIBLE_MAIN_WINDOWS:
        return pool

    drop_index = lane_occurrence % len(pool)
    return tuple(window for index, window in enumerate(pool) if index != drop_index)


def achievable_shared_windows(config: LoopConfig) -> tuple[int, str]:
    """The smallest overlap two of this config's selection sets can ever have, and why.

    The companion to `_resolve_selection_windows`: that function decides what each generation runs,
    this one reads the same three branches and reports the floor they impose, so
    `LoopConfig.promotion_max_shared_windows` can be refused at `start_loop` rather than discovered by
    a `promotions.jsonl` that stays empty. Returns `(floor, detail)`; `detail` is a clause naming the
    branch, for the exception message.

    The three branches, in the same order the resolver takes them:

    * **explicit `config.windows`** -- honoured exactly and never rotated, so every generation runs the
      identical set and two sets always share all of it. The floor is the set's own size, and no
      ceiling below that can ever be met while this `LoopConfig` is the one running.
    * **a pool at or under `MIN_ELIGIBLE_MAIN_WINDOWS`** -- returned whole, unrotated, for the same
      reason: dropping a window would put the generation under the eligibility floor. Same conclusion.
    * **the rotating default** -- sets are the pool minus one window, chosen by `lane_occurrence`, so
      two *different* sets differ in exactly two windows and share `len(pool) - 2`.

    That last figure is the one that matters in practice: eight main windows minus a two-window
    holdout is a six-window pool, so the floor is **4**, and 4 of 5 shared is what every promotion this
    loop has made was actually built on.
    """
    if config.windows:
        size = len(set(config.windows))
        return size, f"`windows` is set explicitly to {size} window(s) and is never rotated"

    holdout = set(config.holdout_windows)
    pool = tuple(window for window in MAIN_WINDOWS if window not in holdout)
    if len(pool) <= MIN_ELIGIBLE_MAIN_WINDOWS:
        return len(pool), (
            f"the selection pool is {len(pool)} window(s), at or under MIN_ELIGIBLE_MAIN_WINDOWS "
            f"({MIN_ELIGIBLE_MAIN_WINDOWS}), so it is returned whole and never rotated"
        )
    return len(pool) - 2, (
        f"the selection pool is {len(pool)} window(s) and each generation drops exactly one"
    )


def _mint_round_id(real_rounds_root: Path, generation_number: int) -> str:
    """`r{N}-auto-{timestamp}-g{generation:04d}`, `N` one past the highest `r<N>` ordinal already in
    `real_rounds_root`.

    `real_rounds_root` must be the *human programme's* `settings.rounds_dir`, never the loop's own
    `loop_rounds_root` -- the two are different trees (see the module docstring), and sequencing
    against the loop's own tree would make every generation within one loop run mint the same `N`
    (the loop's rounds directory does not contain the human programme's rounds, so it never advances
    the ordinal on its own). Consulting the real tree keeps a minted id ordered on the same axis as
    the human programme's rounds -- a loop started after round 16 mints `r17-...` -- even though the
    round it names is written elsewhere.

    The `g{generation:04d}` suffix is what actually guarantees uniqueness: `N` is normally constant
    for an entire loop run (the real tree does not grow while an auto loop runs) and the timestamp
    alone only has one-second resolution, which a fast generation under stubbed collaborators can
    easily beat. Appending the (always-advancing) generation number makes every id this loop mints
    unique by construction, without needing to check the filesystem for a collision and retry.

    Lower-cased and checked against `_ROUND_ID_PATTERN` before being returned -- see that pattern's
    own docstring for why this can only fail defensively.
    """
    sequence = next_round_sequence(real_rounds_root)
    timestamp = _utcnow().strftime("%Y%m%d-%H%M%S")
    round_id = f"r{sequence}-auto-{timestamp}-g{generation_number:04d}".lower()
    if not _ROUND_ID_PATTERN.match(round_id):
        raise ValueError(
            f"minted round_id {round_id!r} does not match ^[a-z0-9][a-z0-9-]{{0,63}}$ -- "
            "this indicates next_round_sequence or the timestamp format changed shape"
        )
    return round_id


def _mint_holdout_round_id(round_id: str) -> str:
    """`{round_id}-holdout` -- the sibling round directory the holdout windows run into.

    **Why a second directory, not a second window set in the same round.** `app.tournament.results.
    build_leaderboard` has no window filter: every run file under a round's `results/` tree, selection
    or holdout alike, is ranked into the one board it returns. Writing the holdout windows into
    `round_id` alongside the selection windows therefore put the holdout inside the very median it
    exists to check -- a real run measured `windows_run=6` over a 5-window selection set, the holdout
    window counted right along with the rest. Two round directories keep `build_leaderboard` correct
    and untouched: it never sees a window it should not have, on either side.

    Suffixing rather than re-minting keeps the pairing obvious on disk (`gen0007-...` sits next to
    `gen0007-...-holdout`) and guarantees the holdout id is unique exactly when the selection id is,
    with no separate uniqueness argument required.

    Checked against `_ROUND_ID_PATTERN` for the same reason `_mint_round_id` checks its own result:
    the pattern's `{0,63}` repetition cap after the mandatory first character means `match` already
    enforces the 64-character ceiling `app.tournament.jobs._ROUND_ID_PATTERN` imposes, so appending
    `"-holdout"` to an already-long id fails loudly here rather than writing a round `app.tournament.
    jobs` would itself refuse.
    """
    holdout_round_id = f"{round_id}-holdout"
    if not _ROUND_ID_PATTERN.match(holdout_round_id):
        raise ValueError(
            f"minted holdout round_id {holdout_round_id!r} does not match "
            "^[a-z0-9][a-z0-9-]{0,63}$ -- likely too long once '-holdout' was appended"
        )
    return holdout_round_id


def _lanes_for(config: LoopConfig) -> tuple[tuple[Purpose, CardShape], ...]:
    """Every `(purpose, shape)` pair this loop breeds, in the fixed order generations cycle through.

    `app.tournament.results.build_leaderboard` ranks only the larger of an `"entry-notional"`
    (`"rules"`) and an `"invested-value"` (`"allocation"`) group when a field mixes the two --
    everything in the smaller group is silently unranked (`unscored_reason`), which is exactly what a
    generation that proposed both shapes at once produced: 4 proposed, 12 runs, 0 failures, 2 ranked.
    A lane is therefore shape-homogeneous by construction: every genome `_execute_generation` proposes
    for one lane shares that lane's `shape`, so a generation's own field is never mixed. `_SHAPES`'s
    fixed `("rules", "allocation")` order (not set iteration, which is unordered across processes)
    is what makes `lanes[(generation_number - 1) % len(lanes)]` a stable, reproducible sequence.
    """
    return tuple((purpose, shape) for purpose in config.purposes for shape in _SHAPES)


def _write_plan_file(
    settings: Settings,
    *,
    generation: int,
    round_id: str,
    purpose: Purpose,
    genomes: Sequence[Genome],
    selection_windows: Sequence[str],
    holdout_windows: Sequence[str],
    config: LoopConfig,
    holdout_round_id: str | None = None,
) -> Path:
    """`gen{N:04d}/PLAN.md`: this generation's pre-registration, written before its first card runs.

    The mechanised stand-in for `strategy-program/ROUND-N-PLAN.md` -- see this module's docstring for
    why a plan document has to exist per generation and why it has to be written before `write_cards`
    persists any card and before `run_generation` is called, not after either. Every candidate's
    genome, universe and notes (its thesis, written before the run) are recorded, along with the fixed
    gate the next generation's promotion check will apply.

    **`config.goal` is recorded verbatim, alongside `focus_symbols`/`avoid_symbols`/`rank_by`, in this
    same pre-registration block -- before any run exists, exactly like everything else here.** See
    `LoopConfig.goal`'s own docstring for why that split matters: the goal is prose nobody's model
    reads, written down so a run can later be read against the question it was started to answer;
    `focus_symbols`/`avoid_symbols`/`rank_by` are the machine-readable half that
    `app.evolution.proposer.propose_generation` actually enforces. An empty `goal` is written as
    `"(no goal was stated)"` rather than the section being omitted -- that absence is itself
    information a reader of this file should not have to infer from a missing heading.

    **A goal that names a setting it cannot change gets that written down too.**
    `app.evolution.goal_directives.goal_directive_notes` reads the goal looking for text shaped like a
    config directive (`purposes=[...]`, `focus=NVDA,AMD`, "ranked by hit rate") that this generation's
    own config does not carry, and each one it finds becomes a bullet under its own heading, naming
    what the run is actually using instead. `gen1873`/`gen1877` are why: both quote
    `purposes=['trading', 'roth', 'saving']` in this very section, both ran the default lanes, and
    nothing in either file marked the gap -- or that `saving` was never a legal purpose. This does not
    make `goal` steer anything (see that module's own docstring, and `LoopPanel.tsx`'s): the notes are
    written for a reader, the config is untouched, and a goal that contradicts its config still runs.
    """
    gen_dir = loop_root(settings) / f"gen{generation:04d}"
    gen_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# Generation {generation} plan",
        "",
        f"**Round id:** `{round_id}`",
        f"**Purpose:** {purpose.value}",
        f"**Selection windows:** {', '.join(selection_windows) or '(none)'}",
        f"**Holdout windows:** {', '.join(holdout_windows) or '(none)'}",
        f"**Holdout round id:** {f'`{holdout_round_id}`' if holdout_round_id else '(none)'}",
        "",
        "## What this generation is for",
        "",
        f"**Goal:** {config.goal if config.goal else '(no goal was stated)'}",
        f"**Focus symbols:** {', '.join(config.focus_symbols) if config.focus_symbols else '(none)'}",
        f"**Avoid symbols:** {', '.join(config.avoid_symbols) if config.avoid_symbols else '(none)'}",
        f"**Rank by:** {config.rank_by}",
        "",
    ]
    directive_notes = goal_directive_notes(config)
    if directive_notes:
        lines.extend(
            [
                "**The goal names settings the goal field cannot change:**",
                "",
                *directive_notes,
                "",
            ]
        )
    lines.extend(
        [
            "`goal` is recorded verbatim and does not steer the search -- no model reads it. "
            "`focus_symbols`/`avoid_symbols`/`rank_by` are the machine-readable half of the same "
            "intent, and are what `app.evolution.proposer.propose_generation` actually enforces on "
            "every candidate below (see `LoopConfig.goal`'s own docstring).",
            "",
            "## Candidates",
            "",
        ]
    )
    for genome in genomes:
        lines.append(
            f"- `{genome.genome_id}` ({genome.origin}, {genome.shape}, parents="
            f"{list(genome.parents) or 'none'}) -- {genome.notes or 'no notes recorded'}"
        )
        lines.append(f"  - universe: {', '.join(genome.universe)}")
        lines.append(f"  - traits: {json.dumps(genome.traits, sort_keys=True, default=str)}")
    lines.extend(
        [
            "",
            "## What the gate will check",
            "",
            "Each candidate above is compared against `LoopConfig.promotion_margin_pp` = "
            f"{config.promotion_margin_pp} on selection-window median excess, and must clear it in "
            "`LoopConfig.promotion_consecutive` consecutive generations on differing window sets "
            "before `app.evolution.promotion.evaluate_promotions` promotes it. The holdout windows "
            "listed above are reported per candidate but never consulted by selection itself.",
            "",
        ]
    )
    path = gen_dir / "PLAN.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_outcome_file(settings: Settings, outcome: GenerationOutcome) -> Path:
    """`gen{N:04d}/OUTCOME.json`: this generation's full, permanent record.

    Written after `PLAN.md`, and unconditionally with respect to *this generation's own* status -- a
    failed generation's outcome (status, error, whatever genome ids were minted) is exactly as much a
    part of the record as a succeeded one's. It is not unconditional with respect to what is already on
    disk: see the refusal below.

    **Refuses to overwrite a different round's record.** `_first_generation_number` is what normally
    keeps two writes from ever targeting the same `gen{N:04d}/OUTCOME.json` for two different rounds
    (see the module docstring's matching section for the incident both of these exist to prevent), but
    it runs once, at the start of one loop's `_run`, and says nothing about a second loop or a second
    process racing it against the same `loop_root`. If `path` already exists and its own `round_id`
    does not match `outcome.round_id`, this is that collision actually happening, not a hypothetical
    one -- silently overwriting here would destroy the earlier round's permanent record exactly as the
    original defect did, just by a different route. Raising `GenerationDirectoryCollision` instead
    turns it into a failed loop (caught by `_run`'s outer `except Exception`, exactly like a ledger that
    cannot be opened) rather than a second silent loss on top of the first. A missing or unparsable
    existing file is treated as "no conflicting record" -- this check only ever blocks a write it can
    positively show collides, never one it merely cannot rule out.
    """
    gen_dir = loop_root(settings) / f"gen{outcome.generation:04d}"
    gen_dir.mkdir(parents=True, exist_ok=True)
    path = gen_dir / "OUTCOME.json"
    if path.exists():
        try:
            existing_round_id = json.loads(path.read_text(encoding="utf-8")).get("round_id")
        except (OSError, ValueError):
            existing_round_id = None
        if existing_round_id is not None and existing_round_id != outcome.round_id:
            raise GenerationDirectoryCollision(
                f"{path} already holds an outcome for round_id={existing_round_id!r}; refusing to "
                f"overwrite it with round_id={outcome.round_id!r}'s outcome -- see "
                "GenerationDirectoryCollision's own docstring"
            )
    path.write_text(outcome.model_dump_json(indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# One generation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _GenerationResult:
    """What one call to `_execute_generation` produced.

    `outcome is None` means the supervisor was stopped before this generation produced anything worth
    recording (mid-wait for a busy engine, before `run_generation` ever returned) -- the caller must
    not append a `GenerationOutcome` for that case, and must not advance its generation counter.
    """

    outcome: GenerationOutcome | None
    elites: tuple[Genome, ...]
    promotions: tuple[PromotionRecord, ...]

    next_config: LoopConfig | None = None
    """This lane's `LoopConfig` for its *next* appearance, with every amendment a review applied this
    generation folded in -- `None` when no review ran (reviewer off, not wired, this generation did not
    succeed, or the review itself failed/was refused entirely), which `_run` reads as "this lane's
    config is unchanged." Never set on any path but the succeeded one -- see `_run_review`'s own
    docstring for why nothing here is retroactive."""

    review_focus_symbols: tuple[str, ...] = ()
    review_avoid_symbols: tuple[str, ...] = ()
    """`GenerationReview.direction.focus_symbols`/`avoid_symbols` from this generation's review, if one
    ran -- threaded into `_propose_genomes` for this lane's *next* generation as the per-generation
    `focus_symbols`/`avoid_symbols` `design_generation` receives (unioned there with `LoopConfig.
    focus_symbols`/`avoid_symbols`, never replacing them). Empty when no review ran, exactly like
    `next_config is None` above -- the two are always set together, by `_run_review`."""


def _log_budget_exhausted_once(loop: _Loop) -> None:
    """Log that the agent budget is exhausted, exactly once per loop run.

    Called every time `_propose_genomes` finds the running budget spent -- which, once true, stays
    true for the rest of the run (nothing ever adds to a cap) -- so without the guard this would be a
    log line every single generation from here on. `loop.agent_budget_exhausted_logged` is the guard;
    checked and set under `loop.lock` so two overlapping calls (there is only ever one supervisor
    thread, but the check-then-set has to be atomic against a concurrent `GET` reading the flag mid
    snapshot regardless) can never both log.
    """
    with loop.lock:
        if loop.agent_budget_exhausted_logged:
            return
        loop.agent_budget_exhausted_logged = True
    loop.append_log(
        "agent budget exhausted -- falling back to the deterministic proposer for the rest of this "
        "loop run"
    )


def _top_up_with_deterministic(
    loop: _Loop,
    generation_number: int,
    agent_genomes: tuple[Genome, ...],
    propose_kwargs: dict[str, object],
    *,
    config: LoopConfig,
) -> tuple[Genome, ...]:
    """Fill an agent-designed slate out to `LoopConfig.population` using the deterministic proposer,
    when the agent returned fewer candidates than the loop wants to run this generation.

    The agent is free to propose fewer than `config.population` genomes -- nothing in
    `app.agents.designer`'s contract requires it to fill a quota, and a smaller, more deliberate slate
    is a legitimate answer. But `_execute_generation` runs exactly the genomes it is handed as one
    round, and a generation running fewer candidates than configured would quietly shrink the search
    without anyone asking for that. So a short agent slate is topped up with `propose`'s own
    full-population output, filtered to drop any `genome_id` the agent already produced (the two
    proposers mint ids independently and are vanishingly unlikely to collide, but a duplicate id would
    corrupt `genomes_by_id` downstream if one ever did) and truncated to exactly the shortfall.

    `config` is this *lane's* current effective config (see `_execute_generation`'s own docstring on
    why that is not always `loop.config`), not read off `loop` directly -- a reviewer's amendment to
    `population` must take effect for this same top-up, not only for `propose_kwargs["config"]`.
    """
    if len(agent_genomes) >= config.population:
        return agent_genomes

    deterministic = loop.collaborators.propose(**propose_kwargs)
    already_used = {genome.genome_id for genome in agent_genomes}
    filler = [genome for genome in deterministic if genome.genome_id not in already_used]
    shortfall = config.population - len(agent_genomes)
    topped_up = agent_genomes + tuple(filler[:shortfall])

    loop.append_log(
        f"gen {generation_number}: agent proposed {len(agent_genomes)} genome(s), topped up to "
        f"{len(topped_up)} with the deterministic proposer"
    )
    return topped_up


def _propose_genomes(
    loop: _Loop,
    *,
    generation_number: int,
    purpose: Purpose,
    shape: CardShape,
    elites: tuple[Genome, ...],
    propose_kwargs: dict[str, object],
    previous_outcome: GenerationOutcome | None,
    config: LoopConfig,
    review_focus_symbols: tuple[str, ...] = (),
    review_avoid_symbols: tuple[str, ...] = (),
) -> tuple[Genome, ...]:
    """This generation's candidate genomes: agent-designed when `LoopConfig.use_agent` is on and a
    designer is wired, the seeded deterministic proposer otherwise -- and *always* the deterministic
    proposer on any failure of the agent path, which is this function's whole reason to exist.

    **This is the single most important function in this module's agent wiring.** Every one of
    `AgentUnavailable` (no credentials, `anthropic` not installed), `BudgetExhausted` (the run's spend
    ceiling reached), `AgentDisabled`, and any other exception the designer raises -- a timeout, a
    malformed response, a bug in a package written concurrently with this one -- is caught here and
    turned into a logged fallback to `loop.collaborators.propose` for this one generation. Nothing
    above this function ever sees an agent failure; from `_execute_generation`'s point of view, this
    always just returns genomes.

    **The running `AgentBudget` lives on `loop.agent_budget`, not on `Collaborators`.** A `Callable`
    field is stateless between calls, but spend has to accumulate across every generation of one loop
    run (`LoopConfig.agent_budget_usd` caps the whole run, not one call) -- so this function reads
    `loop.agent_budget`, seeding it from `config.agent_budget_usd` on the very first call, passes it
    into `design_generation`, and writes back whatever budget the call reports spent. A `BudgetExhausted`
    raised by the designer still carries its own `spent_usd`/`cap_usd`, which is folded back in the
    same way so the tracked budget reflects the exhausting call even though that call itself failed.

    `findings`/`standings` come from `previous_outcome` -- this same lane's last *succeeded*
    generation, exactly the object `derive_findings` itself compares against (see `_execute_
    generation`'s own docstring) -- and are empty on a lane's first appearance. `previous_cards` is
    `elites`: the closest thing this module tracks to "what was proposed last time for this lane", and
    what the deterministic proposer itself breeds from in the non-agent path.

    `config` is this lane's current effective `LoopConfig` -- see `_execute_generation`'s own docstring
    on why that can differ from `loop.config` once a reviewer has amended it. `review_focus_symbols`/
    `review_avoid_symbols` are the previous review's `GenerationReview.direction.focus_symbols`/
    `avoid_symbols` for this same lane (empty when no review has run yet); passed to `design_generation`
    unioned with `config.focus_symbols`/`avoid_symbols` rather than in place of them, because
    `design_generation`'s own contract already unions whatever it is given with the config's fields --
    passing the union up front just means a reviewer's softer, non-validated suggestion reaches the
    designer the same generation it was made, without needing its own amendment.
    """
    if not (config.use_agent and loop.collaborators.design_generation is not None):
        return loop.collaborators.propose(**propose_kwargs)

    with loop.lock:
        if loop.agent_budget is None:
            loop.agent_budget = AgentBudget(cap_usd=config.agent_budget_usd)
        budget = loop.agent_budget

    if budget.exhausted:
        _log_budget_exhausted_once(loop)
        return loop.collaborators.propose(**propose_kwargs)

    try:
        genomes, _proposal, new_budget = loop.collaborators.design_generation(
            generation=generation_number,
            purpose=purpose,
            shape=shape,
            config=config,
            settings=loop.settings,
            budget=budget,
            findings=previous_outcome.findings if previous_outcome is not None else (),
            standings=previous_outcome.standings if previous_outcome is not None else (),
            previous_cards=elites,
            focus_symbols=(*config.focus_symbols, *review_focus_symbols),
            avoid_symbols=(*config.avoid_symbols, *review_avoid_symbols),
        )
    except AgentUnavailable as exc:
        loop.append_log(
            f"gen {generation_number}: agent unavailable ({exc}), falling back to the deterministic "
            "proposer"
        )
        return loop.collaborators.propose(**propose_kwargs)
    except BudgetExhausted as exc:
        with loop.lock:
            loop.agent_budget = AgentBudget(
                cap_usd=exc.cap_usd, spent_usd=exc.spent_usd, calls=budget.calls
            )
        _log_budget_exhausted_once(loop)
        return loop.collaborators.propose(**propose_kwargs)
    except AgentDisabled as exc:
        loop.append_log(
            f"gen {generation_number}: agent disabled ({exc}), using the deterministic proposer"
        )
        return loop.collaborators.propose(**propose_kwargs)
    except Exception as exc:  # a designer bug must not stall or fail the loop -- see docstring above
        loop.append_log(
            f"gen {generation_number}: agent designer failed ({type(exc).__name__}: {exc}), falling "
            "back to the deterministic proposer"
        )
        return loop.collaborators.propose(**propose_kwargs)

    with loop.lock:
        loop.agent_budget = new_budget
    loop.append_log(
        f"gen {generation_number}: agent designed {len(genomes)} genome(s) "
        f"(${new_budget.spent_usd} of ${new_budget.cap_usd} spent)"
    )
    if new_budget.exhausted:
        _log_budget_exhausted_once(loop)

    return _top_up_with_deterministic(loop, generation_number, genomes, propose_kwargs, config=config)


@dataclass(frozen=True, slots=True)
class _ReviewOutcome:
    """What one call to `_run_review` produced, when a review actually ran.

    `_execute_generation` folds this into its own return value: `keep_genome_ids` augments the
    deterministic elite set (see `_augment_elites_with_kept_candidates`), `next_config` becomes this
    lane's `LoopConfig` for its next appearance, and `focus_symbols`/`avoid_symbols` are threaded into
    that same next generation's `_propose_genomes` call. Nothing here is retroactive -- see
    `_run_review`'s own docstring.
    """

    keep_genome_ids: tuple[str, ...]
    next_config: LoopConfig
    focus_symbols: tuple[str, ...]
    avoid_symbols: tuple[str, ...]


def _augment_elites_with_kept_candidates(
    elites: tuple[Genome, ...],
    genomes_by_id: Mapping[str, Genome],
    keep_genome_ids: Sequence[str],
) -> tuple[Genome, ...]:
    """`elites`, plus every genome named in `keep_genome_ids` that is not already present -- never the
    reverse.

    **This is the fix for "only first place is tracked."** `feedback.select_elites` keeps only the top
    `LoopConfig.elite_count` standings by `median_excess`; a 6th-place candidate that still cleared the
    holdout has no path to breed forward under that rule alone, however the reviewer reads its numbers.
    A reviewer's `per_candidate[].keep=True` note lets such a candidate in -- appended, never inserted
    in place of a deterministic pick, and never able to displace one. The deterministic ranking stays
    the reproducible part of this search regardless of what any review concludes: a reader who trusts
    only `feedback.select_elites`'s own arithmetic can still reconstruct that half of `elites` exactly;
    only the tail beyond it depends on a model's judgement, and it is visibly additive, never a
    replacement.

    `keep_genome_ids` is expected to already be bounded (`_run_review` truncates to
    `_MAX_REVIEWER_KEPT_ELITES`) and filtered to genomes that actually ran this generation; the
    `genome_id in genomes_by_id` check here is a second, cheap guard against a stale or malformed id
    rather than the only one.
    """
    existing = {genome.genome_id for genome in elites}
    additions = tuple(
        genomes_by_id[genome_id]
        for genome_id in keep_genome_ids
        if genome_id not in existing and genome_id in genomes_by_id
    )
    return (*elites, *additions)


def _run_review(
    loop: _Loop,
    *,
    generation_number: int,
    purpose: Purpose,
    config: LoopConfig,
    outcome: GenerationOutcome,
    genomes: tuple[Genome, ...],
    lane_history: tuple[GenerationOutcome, ...],
) -> _ReviewOutcome | None:
    """Ask the reviewer about this just-scored generation, and fold its verdict into the *next*
    generation of this same lane. Returns `None` whenever there is nothing to fold in -- the reviewer
    is off, not wired, its budget is spent, or the call itself failed -- in which case
    `_execute_generation` proceeds exactly as it did before this function existed.

    **Never load-bearing, mirroring `_propose_genomes`'s contract for the designer.** `outcome` is
    already a complete, correctly-scored `GenerationOutcome` by the time this function is ever called
    (see `_execute_generation`'s call site, after promotions have been evaluated) -- every exception
    the reviewer raises, `AgentUnavailable`/`BudgetExhausted`/anything else, is caught here, logged, and
    turned into `None`. Nothing about a review failing may change or discard the outcome that already
    exists.

    **Deliberately not counted by `_run`'s consecutive-failure circuit breaker.** `_MAX_CONSECUTIVE_
    FAILURES` exists to catch a systemic fault in the *search* -- proposing, running, scoring -- on the
    theory that nothing about trying the next generation could repair it (see that constant's own
    docstring for the incident this is traceable to). A reviewer that fails run after run is not
    evidence the search itself is broken: the generations it is reviewing may be succeeding perfectly
    well, and halting a working search because a commentary layer keeps failing would be strictly worse
    than the reviewer simply having nothing to say. So a review's failure is logged and walked past,
    here, and never reaches `_run`'s `outcome.status` at all -- there is no status for "review failed,"
    only for the generation itself.

    **The running `AgentBudget` is shared with the designer**, via `loop.agent_budget` -- one cap for
    the whole run (`LoopConfig.agent_budget_usd`), not one per collaborator. Seeded here on first use
    exactly like `_propose_genomes` seeds it, so whichever of the two collaborators is called first in
    a given run is the one that sees a fresh budget.

    `lane_history` is this same lane's own prior *succeeded* `GenerationOutcome`s, oldest first -- see
    `app.agents.reviewer.review_generation`'s own docstring, which asks for exactly that shape and
    explicitly not "the generation immediately prior" in a loop that interleaves lanes. `_run` tracks
    it per lane (`history_by_lane`), the same way it already tracks `elites_by_lane` and
    `last_outcome_by_lane`; it is not `loop.history`, which is every lane's outcomes mixed together,
    most-recent-first, and exists for a different reader (`evaluate_promotions`, which keys off
    `genome_id` rather than lane and so does not need this filtering).
    """
    if not (config.use_reviewer and loop.collaborators.review_generation is not None):
        return None

    with loop.lock:
        if loop.agent_budget is None:
            loop.agent_budget = AgentBudget(cap_usd=config.agent_budget_usd)
        budget = loop.agent_budget

    if budget.exhausted:
        _log_budget_exhausted_once(loop)
        return None

    try:
        review, new_budget = loop.collaborators.review_generation(
            outcome=outcome,
            config=config,
            settings=loop.settings,
            budget=budget,
            genomes=genomes,
            history=lane_history,
        )
    except BudgetExhausted as exc:
        with loop.lock:
            loop.agent_budget = AgentBudget(
                cap_usd=exc.cap_usd, spent_usd=exc.spent_usd, calls=budget.calls
            )
        _log_budget_exhausted_once(loop)
        return None
    except Exception as exc:  # a reviewer failure must never touch an already-scored generation
        loop.append_log(
            f"gen {generation_number}: reviewer failed ({type(exc).__name__}: {exc}), continuing "
            "without a review"
        )
        return None

    with loop.lock:
        loop.agent_budget = new_budget
    if new_budget.exhausted:
        _log_budget_exhausted_once(loop)

    try:
        review_path = generation_review_path(loop.settings, generation_number)
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_path.write_text(review.model_dump_json(indent=2), encoding="utf-8")

        amendment_outcome = apply_amendments(
            config=config,
            amendments=review.amendments,
            generation=generation_number,
            purpose=purpose,
            settings=loop.settings,
        )
    except Exception as exc:  # writing REVIEW.json or applying amendments must not fail the generation
        loop.append_log(
            f"gen {generation_number}: reviewer succeeded but recording it failed "
            f"({type(exc).__name__}: {exc}), continuing without acting on this review"
        )
        return None

    for record in amendment_outcome.applied:
        loop.append_log(
            f"gen {generation_number}: reviewer amendment applied -- {record.field}: "
            f"{record.old_value!r} -> {record.new_value!r} ({record.reason})"
        )
    for refusal in amendment_outcome.refused:
        loop.append_log(
            f"gen {generation_number}: reviewer amendment refused -- {refusal.field}="
            f"{refusal.value!r}: {refusal.reason}"
        )

    genomes_by_id = {genome.genome_id: genome for genome in genomes}
    # `per_candidate[].keep` may only ADD to the deterministic elite set -- see
    # `_augment_elites_with_kept_candidates`'s own docstring for why a model may never remove one.
    # Bounded to `_MAX_REVIEWER_KEPT_ELITES` so one enthusiastic review cannot grow a lane's breeding
    # population without bound.
    keep_ids = tuple(
        note.genome_id for note in review.per_candidate if note.keep and note.genome_id in genomes_by_id
    )[:_MAX_REVIEWER_KEPT_ELITES]

    with loop.lock:
        # `headline` lives on `GenerationReview.direction` (`ReviewDirection`), not on the review
        # itself -- `verdict`/`post_mortem`/`per_candidate`/`amendments` are the top-level fields.
        loop.latest_review_headline = review.direction.headline
        loop.latest_review_verdict = review.verdict
        loop.amendments_applied = (*loop.amendments_applied, *amendment_outcome.applied)

    loop.append_log(f"gen {generation_number}: review -- {review.verdict}: {review.direction.headline}")

    return _ReviewOutcome(
        keep_genome_ids=keep_ids,
        next_config=amendment_outcome.config,
        focus_symbols=review.direction.focus_symbols,
        avoid_symbols=review.direction.avoid_symbols,
    )


def _execute_generation(
    loop: _Loop,
    generation_number: int,
    purpose: Purpose,
    shape: CardShape,
    elites: tuple[Genome, ...],
    lane_occurrence: int,
    ledger: object,
    previous_outcome: GenerationOutcome | None,
    *,
    config: LoopConfig,
    review_focus_symbols: tuple[str, ...] = (),
    review_avoid_symbols: tuple[str, ...] = (),
    lane_history: tuple[GenerationOutcome, ...] = (),
) -> _GenerationResult:
    """One full iteration: propose, plan, run (selection, then holdout), score, promote. See the
    module docstring for the step order this follows and why a failure here never escapes to the
    caller.

    `previous_outcome` is this same lane's (`(purpose, shape)` pair's) most recently *succeeded*
    `GenerationOutcome`, or `None` on a lane's first appearance -- `_run` tracks one per lane in
    `last_outcome_by_lane` and looks it up before calling this function, the same way it already
    tracks `elites_by_lane`. Threaded into `derive_findings` as `previous_generation` so the
    `kind="gate"` goal finding (see `app.evolution.feedback._goal_finding`) can compare this
    generation's `config.rank_by` quantity against the *same lane*'s own last measurement rather than
    whatever generation happened to run immediately before it -- lanes interleave, so "the previous
    generation" and "the previous generation in this lane" are almost never the same generation.

    **`config` is this lane's own current effective config, not always `loop.config`.** `_run` tracks
    one `LoopConfig` per lane in `configs_by_lane`, exactly like `elites_by_lane` and
    `last_outcome_by_lane`, defaulting to `loop.config` for a lane no review has ever amended. Every
    read of "the config" inside this function and the functions it calls (`_propose_genomes`,
    `_top_up_with_deterministic`, `_write_plan_file`, `read_standings`, `derive_findings`,
    `evaluate_promotions`, `select_elites`) uses this parameter, never `loop.config` directly, so a
    reviewer's amendment to one lane can never leak into another lane's generations or retroactively
    change one already run -- see `app.evolution.amend`'s own module docstring on why amendments only
    ever take effect for a lane's *next* generation. `review_focus_symbols`/`review_avoid_symbols` are
    the analogous per-lane carry-forward for the softer, non-validated half of a review's direction --
    see `_propose_genomes`'s own docstring.

    **Selection and holdout run into two separate round directories.** `app.tournament.results.
    build_leaderboard` has no window filter -- every run file under a round's `results/` tree is
    ranked into the one board it returns, selection and holdout windows alike. Running both window
    sets into the same `round_id` therefore put the holdout inside the selection median it exists to
    check (a real run measured `windows_run=6` over a 5-window selection set). `round_id` receives
    only `selection_windows`; `holdout_round_id` (`_mint_holdout_round_id(round_id)`) receives only
    `holdout_windows`, run afterwards, serially -- the engine holds a single process-wide slot (see
    `app.evolution.execute`'s own docstring on `external_round_slot`), so the two calls never overlap.
    A failing holdout run does not fail the generation: it is caught, logged, and the generation still
    succeeds with `Standing.holdout_median_excess` left `None` for every candidate.
    """
    started_at = _utcnow()
    selection_windows = _resolve_selection_windows(config, lane_occurrence=lane_occurrence)
    holdout_windows = config.holdout_windows
    round_id = f"gen{generation_number:04d}-unminted"  # overwritten below; kept as a safe fallback

    with loop.lock:
        loop.generation = generation_number
        loop.current_purpose = purpose
        loop.current_round_id = None
        loop.current_job_id = None

    _set_phase(loop, "proposing")

    news_symbols: tuple[str, ...] = ()
    if config.use_news:
        try:
            news_symbols = loop.collaborators.trending_symbols(purpose=purpose, settings=loop.settings)
        except Exception as exc:  # non-fatal by design -- see module docstring on news bias
            loop.append_log(
                f"gen {generation_number}: trending_symbols failed ({type(exc).__name__}: {exc}), "
                "continuing without news bias"
            )

    try:
        round_id = _mint_round_id(loop.settings.rounds_dir, generation_number)
        with loop.lock:
            loop.current_round_id = round_id

        rng = random.Random(config.seed + generation_number)
        propose_kwargs: dict[str, object] = {
            "generation": generation_number,
            "purpose": purpose,
            "config": config,
            "rng": rng,
            "elites": elites,
            "news_symbols": news_symbols,
        }
        # `shape` is a late addition to `proposer.propose_generation`'s signature, written
        # concurrently with this module -- `_accepts_kwarg` lets an older collaborator (real or a
        # test fake) that does not yet take it keep working exactly as before, matching the same
        # defensive pattern already used below for `rounds_root`/`window_medians`.
        if _accepts_kwarg(loop.collaborators.propose, "shape"):
            propose_kwargs["shape"] = shape
        # `seen` is the loop's memory of every card it has already proposed, keyed by content --
        # without it a draw that lands on traits already tried mints a *new* id (the generation is in
        # the prefix; only the content is hashed) and the same card becomes two candidates. That is
        # the failure `app.evolution.models.genome_id_for`'s own docstring calls load-bearing: the
        # promotion gate accumulates evidence by matching `genome_id`, so a re-minted card reads as
        # two that each cleared once, and the ledger's correction denominator counts hypotheses that
        # were never newly proposed. Measured before this landed: 47 of 1,701 distinct contents had
        # been minted under more than one id.
        #
        # Guarded by `_accepts_kwarg` for the same reason `shape` above is -- a test fake, or a
        # `proposer` predating this, is called exactly as it was. Rebuilt each generation rather than
        # cached on the loop so a genome written by another process is seen; the index reads
        # filenames only and costs ~16ms over 1,800 genomes.
        if _accepts_kwarg(loop.collaborators.propose, "seen"):
            load_seen = loop.collaborators.load_seen_genomes
            if load_seen is not None:
                propose_kwargs["seen"] = load_seen(loop.settings)
        genomes = _propose_genomes(
            loop,
            generation_number=generation_number,
            purpose=purpose,
            shape=shape,
            elites=elites,
            propose_kwargs=propose_kwargs,
            previous_outcome=previous_outcome,
            config=config,
            review_focus_symbols=review_focus_symbols,
            review_avoid_symbols=review_avoid_symbols,
        )

        holdout_round_id: str | None = _mint_holdout_round_id(round_id) if holdout_windows else None

        # PLAN.md, written now -- before `write_cards` and before `run_generation` -- and not one
        # step later. See the module docstring's "Pre-registration, mechanised" section: the
        # production incident `_MAX_CONSECUTIVE_FAILURES` documents failed 1,644 times inside
        # `write_cards` itself (a read-only filesystem writing a generated card's JSON), and a plan
        # written only after that call would have left every one of those generations with no
        # pre-registration record at all. Everything this needs -- round id, purpose, the window
        # split, `config`, and every genome's id/universe/notes -- comes from `_propose_genomes`
        # above and `_mint_holdout_round_id` just before it; neither `write_cards` nor
        # `run_generation` contributes anything this file records, so there is no reason to defer
        # any part of it and no need for a two-part write.
        _write_plan_file(
            loop.settings,
            generation=generation_number,
            round_id=round_id,
            purpose=purpose,
            genomes=genomes,
            selection_windows=selection_windows,
            holdout_windows=holdout_windows,
            config=config,
            holdout_round_id=holdout_round_id,
        )

        loop.collaborators.write_cards(genomes, settings=loop.settings)
        cards = [loop.collaborators.card_for(genome) for genome in genomes]

        _set_phase(loop, "running")

        report = None
        while True:
            if loop.stop_event.is_set():
                loop.append_log(f"gen {generation_number}: stopped before the engine accepted it")
                return _GenerationResult(outcome=None, elites=elites, promotions=())
            try:
                report = loop.collaborators.run_generation(
                    round_id=round_id,
                    cards=cards,
                    windows=selection_windows,
                    settings=loop.settings,
                    cancel=loop.stop_event,
                    log=loop.append_log,
                    output_root=loop.output_root,
                    # Without this the whole parallel path is dead code: `execute.run_generation`
                    # defaults `max_workers` to 1, so a config field the user can set from the loop
                    # panel would silently change nothing and every generation would run serially
                    # while appearing to be configured otherwise. Threads were measured at 0.97x
                    # here (the GIL) and processes at 2.74x on a real 30-run generation, so this one
                    # keyword is the entire speedup.
                    max_workers=config.max_workers,
                )
                break
            except JobAlreadyRunning as exc:
                loop.append_log(
                    f"gen {generation_number}: engine busy ({exc}), waiting to retry the same generation"
                )
                _sleep_checking_stop(loop, _ENGINE_BUSY_RETRY_SECONDS)

        with loop.lock:
            loop.current_job_id = getattr(report, "job_id", None)

        genome_ids = tuple(genome.genome_id for genome in genomes)

        if getattr(report, "status", None) == "failed":
            finished_at = _utcnow()
            with loop.lock:
                failed_phase = loop.phase
            errors = getattr(report, "errors", ())
            error = "; ".join(errors) if errors else "run_generation reported status=failed"
            loop.append_log(f"gen {generation_number}: FAILED in phase {failed_phase!r}: {error}")
            outcome = GenerationOutcome(
                generation=generation_number,
                round_id=round_id,
                purpose=purpose,
                job_id=getattr(report, "job_id", None),
                status="failed",
                started_at=started_at,
                finished_at=finished_at,
                windows=tuple(selection_windows),
                holdout_windows=holdout_windows,
                genome_ids=genome_ids,
                error=error,
            )
            return _GenerationResult(outcome=outcome, elites=elites, promotions=())

        if getattr(report, "status", None) == "cancelled":
            finished_at = _utcnow()
            loop.append_log(
                f"gen {generation_number}: cancelled "
                f"({getattr(report, 'completed_runs', '?')} run(s) completed before the stop)"
            )
            outcome = GenerationOutcome(
                generation=generation_number,
                round_id=round_id,
                purpose=purpose,
                job_id=getattr(report, "job_id", None),
                status="cancelled",
                started_at=started_at,
                finished_at=finished_at,
                windows=tuple(selection_windows),
                holdout_windows=holdout_windows,
                genome_ids=genome_ids,
            )
            return _GenerationResult(outcome=outcome, elites=elites, promotions=())

        # Holdout, only now that selection has actually succeeded -- see this function's own
        # docstring. Runs into `holdout_round_id`, never `round_id`, and any failure here (an
        # exception from `run_generation`, or a non-"succeeded" `ExecutionReport.status`) is caught
        # and logged rather than raised: it degrades `Standing.holdout_median_excess` to `None` for
        # this generation, it does not fail the generation itself. `JobAlreadyRunning` is retried
        # exactly like the selection run above -- the engine's single slot is a routine, expected
        # source of contention, not a holdout failure.
        holdout_available = False
        if holdout_round_id is not None:
            while True:
                if loop.stop_event.is_set():
                    loop.append_log(
                        f"gen {generation_number}: holdout skipped -- stopped before the engine "
                        "accepted it"
                    )
                    break
                try:
                    holdout_report = loop.collaborators.run_generation(
                        round_id=holdout_round_id,
                        cards=cards,
                        windows=holdout_windows,
                        settings=loop.settings,
                        cancel=loop.stop_event,
                        log=loop.append_log,
                        output_root=loop.output_root,
                        max_workers=config.max_workers,
                    )
                except JobAlreadyRunning as exc:
                    loop.append_log(
                        f"gen {generation_number}: engine busy for the holdout run ({exc}), "
                        "waiting to retry"
                    )
                    _sleep_checking_stop(loop, _ENGINE_BUSY_RETRY_SECONDS)
                    continue
                except Exception as exc:
                    loop.append_log(
                        f"gen {generation_number}: holdout run failed "
                        f"({type(exc).__name__}: {exc}), continuing with holdout medians of None"
                    )
                    break
                if getattr(holdout_report, "status", None) == "succeeded":
                    holdout_available = True
                else:
                    loop.append_log(
                        f"gen {generation_number}: holdout run reported "
                        f"status={getattr(holdout_report, 'status', None)!r}, continuing with "
                        "holdout medians of None"
                    )
                break

        effective_holdout_round_id = holdout_round_id if holdout_available else None

        # `read_standings`/`derive_findings`/`select_elites`/`evaluate_promotions` all key their
        # `genomes` argument by `genome_id` rather than take the plain sequence `card_for`/
        # `write_cards` above use -- confirmed against the real (now-landed) sibling modules, which
        # type it `Mapping[str, Genome]` in every one of the four. Built once here, from the same
        # `genomes` tuple everything else in this function uses, so an incumbent genome (see the
        # module docstring's "Incumbents can reappear" paragraph) is keyed by its own original
        # `genome_id` exactly like a freshly-bred one.
        genomes_by_id: dict[str, Genome] = {genome.genome_id: genome for genome in genomes}

        _set_phase(loop, "scoring")
        read_standings_kwargs: dict[str, object] = {
            "round_id": round_id,
            "purpose": purpose,
            "genomes": genomes_by_id,
            "config": config,
            "settings": loop.settings,
            "selection_windows": selection_windows,
            "holdout_windows": holdout_windows,
        }
        # The loop's rounds live under `loop.output_root` (`loop_rounds_root`, not
        # `settings.rounds_dir`) -- see the module docstring. `read_standings` needs that root to find
        # what this generation just ran; `_accepts_kwarg` checks whether the injected collaborator
        # (real or fake) actually takes it before passing it, since the parameter was still being
        # decided concurrently in the sibling module that owns `feedback.py`.
        if _accepts_kwarg(loop.collaborators.read_standings, "rounds_root"):
            read_standings_kwargs["rounds_root"] = loop.output_root
        # `holdout_round_id` is a late addition to `feedback.read_standings`'s signature, written
        # concurrently with this fix -- `_accepts_kwarg` again lets an older collaborator keep working
        # unmodified. `effective_holdout_round_id` is `None` both when there is no holdout configured
        # at all and when the holdout run itself failed (see the paragraph above): either way,
        # `read_standings` falls back to its own no-holdout-round-given behaviour and every
        # `Standing.holdout_median_excess` in this generation comes back `None`.
        if _accepts_kwarg(loop.collaborators.read_standings, "holdout_round_id"):
            read_standings_kwargs["holdout_round_id"] = effective_holdout_round_id
        standings = loop.collaborators.read_standings(**read_standings_kwargs)

        # The per-window median-excess breakdown `derive_findings`'s `kind="regime"` finding needs to
        # name which window the field did worst in -- see `Collaborators.field_window_medians`'s own
        # docstring for why this is optional and why its failure is non-fatal enrichment rather than a
        # generation-failing one. `selection_windows` only, never the holdout set --
        # `feedback.field_window_medians`'s own docstring is explicit that a caller passes selection
        # windows here, because this finding exists to describe the selection field, not the holdout.
        window_medians: Mapping[str, Decimal] | None = None
        if loop.collaborators.field_window_medians is not None:
            field_window_medians_kwargs: dict[str, object] = {
                "purpose": purpose,
                "genomes": genomes_by_id,
                "windows": selection_windows,
                "settings": loop.settings,
            }
            if _accepts_kwarg(loop.collaborators.field_window_medians, "rounds_root"):
                field_window_medians_kwargs["rounds_root"] = loop.output_root
            try:
                window_medians = loop.collaborators.field_window_medians(round_id, **field_window_medians_kwargs)
            except Exception as exc:
                loop.append_log(
                    f"gen {generation_number}: field_window_medians failed ({type(exc).__name__}: {exc}), "
                    "the regime finding will degrade to no data"
                )
                window_medians = None

        derive_findings_kwargs: dict[str, object] = {
            "config": config,
            "purpose": purpose,
            "selection_windows": selection_windows,
            "holdout_windows": holdout_windows,
            "genomes": genomes_by_id,
        }
        if window_medians is not None and _accepts_kwarg(loop.collaborators.derive_findings, "window_medians"):
            derive_findings_kwargs["window_medians"] = window_medians
        # `previous_generation` is a late addition to `feedback.derive_findings`'s signature, written
        # concurrently with this fix -- `_accepts_kwarg` lets an older collaborator (real or a test
        # fake) that does not yet take it keep working exactly as before, matching the same defensive
        # pattern already used above for `shape`/`rounds_root`/`holdout_round_id`/`window_medians`.
        if _accepts_kwarg(loop.collaborators.derive_findings, "previous_generation"):
            derive_findings_kwargs["previous_generation"] = previous_outcome
        findings = loop.collaborators.derive_findings(standings, **derive_findings_kwargs)
        ledger_entries_kwargs: dict[str, object] = {
            "round_id": round_id,
            "purpose": purpose,
            "generation": generation_number,
            "selection_windows": selection_windows,
            "settings": loop.settings,
        }
        # Same reasoning as `read_standings_kwargs` above: `ledger_entries_for` also grew an optional
        # `rounds_root` parameter in the landed `feedback` module.
        if _accepts_kwarg(loop.collaborators.ledger_entries_for, "rounds_root"):
            ledger_entries_kwargs["rounds_root"] = loop.output_root
        entries = loop.collaborators.ledger_entries_for(standings, **ledger_entries_kwargs)
        ledger.record(entries)  # type: ignore[attr-defined]
        q_values: dict[str, float] = ledger.q_values()  # type: ignore[attr-defined]
        standings = tuple(
            standing.model_copy(update={"q_value": q_values.get(standing.genome_id, standing.q_value)})
            for standing in standings
        )

        _set_phase(loop, "promoting")
        promotions = loop.collaborators.evaluate_promotions(
            standings=standings,
            genomes=genomes_by_id,
            history=tuple(loop.history),
            config=config,
            generation=generation_number,
            selection_windows=selection_windows,
            settings=loop.settings,
        )

        new_elites = loop.collaborators.select_elites(standings, genomes_by_id, config=config)

        finished_at = _utcnow()
        promoted_ids = tuple(record.genome_id for record in promotions)
        outcome = GenerationOutcome(
            generation=generation_number,
            round_id=round_id,
            purpose=purpose,
            job_id=getattr(report, "job_id", None),
            status="succeeded",
            started_at=started_at,
            finished_at=finished_at,
            windows=tuple(selection_windows),
            holdout_windows=holdout_windows,
            genome_ids=genome_ids,
            standings=standings,
            findings=findings,
            promoted=promoted_ids,
        )
        loop.append_log(
            f"gen {generation_number}: succeeded -- {len(genomes)} genome(s), "
            f"{len(promotions)} promoted"
        )

        # The review is asked for only now that `outcome` is complete and correct -- see
        # `_run_review`'s own docstring for why nothing about a failed or absent review may change
        # anything computed above this point. Wrapped in its own `try/except` as belt and braces on
        # top of `_run_review`'s internal one: nothing between here and `_GenerationResult` below may
        # ever turn a succeeded generation into a failed one.
        next_config: LoopConfig | None = None
        next_review_focus_symbols: tuple[str, ...] = ()
        next_review_avoid_symbols: tuple[str, ...] = ()
        try:
            review_outcome = _run_review(
                loop,
                generation_number=generation_number,
                purpose=purpose,
                config=config,
                outcome=outcome,
                genomes=genomes,
                lane_history=lane_history,
            )
        except Exception as exc:
            loop.append_log(
                f"gen {generation_number}: reviewer wiring failed ({type(exc).__name__}: {exc}), "
                "continuing without a review"
            )
            review_outcome = None

        if review_outcome is not None:
            new_elites = _augment_elites_with_kept_candidates(
                new_elites, genomes_by_id, review_outcome.keep_genome_ids
            )
            next_config = review_outcome.next_config
            next_review_focus_symbols = review_outcome.focus_symbols
            next_review_avoid_symbols = review_outcome.avoid_symbols

        return _GenerationResult(
            outcome=outcome,
            elites=new_elites,
            promotions=promotions,
            next_config=next_config,
            review_focus_symbols=next_review_focus_symbols,
            review_avoid_symbols=next_review_avoid_symbols,
        )

    except Exception as exc:  # a single generation's failure must not kill the loop
        finished_at = _utcnow()
        with loop.lock:
            failed_phase = loop.phase
        error = f"{type(exc).__name__}: {exc}"
        loop.append_log(f"gen {generation_number}: FAILED in phase {failed_phase!r}: {error}")
        outcome = GenerationOutcome(
            generation=generation_number,
            round_id=round_id,
            purpose=purpose,
            job_id=None,
            status="failed",
            started_at=started_at,
            finished_at=finished_at,
            windows=tuple(selection_windows),
            holdout_windows=holdout_windows,
            genome_ids=(),
            error=error,
        )
        return _GenerationResult(outcome=outcome, elites=elites, promotions=())


# ---------------------------------------------------------------------------
# The supervisor loop itself
# ---------------------------------------------------------------------------


def _update_best(loop: _Loop, outcome: GenerationOutcome) -> None:
    for standing in outcome.standings:
        if standing.median_excess is None:
            continue
        if (
            loop.best is None
            or loop.best.median_excess is None
            or standing.median_excess > loop.best.median_excess
        ):
            loop.best = standing


def _run(loop: _Loop) -> None:
    """The supervisor thread's entry point. See the module docstring for the per-generation order and
    for why only an exception escaping this whole function marks the loop `"failed"`."""
    with loop.lock:
        loop.started_at = _utcnow()
        loop.updated_at = loop.started_at
    loop.append_log(f"loop {loop.loop_id} started: purposes={[p.value for p in loop.config.purposes]}")

    try:
        ledger = loop.collaborators.open_ledger(loop.settings)
    except Exception as exc:
        with loop.lock:
            loop.state = "failed"
            loop.error = f"failed to open ledger: {type(exc).__name__}: {exc}"
            loop.stopped_at = _utcnow()
            loop.updated_at = loop.stopped_at
        loop.append_log(f"loop {loop.loop_id} FAILED to open ledger: {loop.error}")
        return

    lanes = _lanes_for(loop.config)
    # Elites keyed by lane, not one shared pool -- see the module docstring's "Lanes" section. A
    # `(purpose, shape)` pair that has not yet been worked has no elites, hence `dict.get(lane, ())`
    # below rather than a `defaultdict` (which would materialise an entry, and therefore a key in
    # `elites_by_lane`, for a lane merely *looked up*, not yet *run* -- a distinction worth keeping
    # exact since nothing else reads this dict).
    elites_by_lane: dict[tuple[Purpose, CardShape], tuple[Genome, ...]] = {}
    # How many times each lane has already been worked, 0 for its first appearance -- threaded into
    # `_resolve_selection_windows` as `lane_occurrence` so consecutive appearances of the *same* lane
    # rotate to a different window set even though `generation_number` itself advances by
    # `len(lanes)` between them. See `_resolve_selection_windows`'s own docstring.
    lane_occurrences: dict[tuple[Purpose, CardShape], int] = {}
    # This lane's most recently *succeeded* `GenerationOutcome`, keyed the same way `elites_by_lane`
    # is -- see `_execute_generation`'s own docstring on why `derive_findings`'s goal-comparison needs
    # this lane's own history rather than whatever generation happened to run immediately before it.
    # Updated only on `status == "succeeded"` below, so a failed generation (no standings to compare
    # against) does not overwrite the last generation that actually measured something.
    last_outcome_by_lane: dict[tuple[Purpose, CardShape], GenerationOutcome] = {}
    # This lane's current effective `LoopConfig` -- `loop.config` (the config `start_loop` was called
    # with) until a review amends it, from then on the amended config, forever, for this lane only.
    # `dict.get(lane, loop.config)` below is what makes a lane no review has ever touched behave
    # exactly as it did before `LoopConfig.use_reviewer` existed. See `_execute_generation`'s own
    # docstring on why every collaborator call inside it reads this instead of `loop.config` directly.
    configs_by_lane: dict[tuple[Purpose, CardShape], LoopConfig] = {}
    # This lane's most recent review's `direction.focus_symbols`/`avoid_symbols` -- the softer,
    # non-validated half of a review, threaded into the next `design_generation` call for the same
    # lane (see `_propose_genomes`'s own docstring). Set only alongside `configs_by_lane[lane]`, by the
    # same `result.next_config is not None` check below, so the two are always in step: either a
    # review ran and both update together, or neither does.
    direction_by_lane: dict[tuple[Purpose, CardShape], tuple[tuple[str, ...], tuple[str, ...]]] = {}
    # This lane's own succeeded `GenerationOutcome`s, oldest first, bounded the same way `loop.history`
    # is (`_HISTORY_MAXLEN`) -- `app.agents.reviewer.review_generation`'s own docstring asks for
    # exactly this shape for its `history` parameter, and explicitly not "the generation immediately
    # prior": lanes interleave, so `loop.history` (every lane mixed together, most-recent-first) is the
    # wrong object to hand it. Appended to, never `appendleft`-ed, so the deque is naturally oldest-
    # first with no reversal needed at the read site (`_run_review`, via `lane_history` below).
    history_by_lane: dict[tuple[Purpose, CardShape], deque[GenerationOutcome]] = {}
    # Computed once, here, before this loop's first generation -- never per generation. See
    # `_first_generation_number`'s own docstring for the incident this replaces (a restarted loop
    # silently overwriting an earlier run's `gen0001`..) and for why recomputing on every iteration
    # would let a directory that appears mid-run make this loop's own numbering jump or collide with
    # itself instead of staying monotonic for the life of the run.
    generation_number = _first_generation_number(loop_root(loop.settings))

    try:
        while True:
            if loop.stop_event.is_set():
                break
            if (
                loop.config.max_generations is not None
                and loop.completed_generations >= loop.config.max_generations
            ):
                break

            lane = lanes[(generation_number - 1) % len(lanes)]
            purpose, shape = lane
            lane_elites = elites_by_lane.get(lane, ())
            lane_occurrence = lane_occurrences.get(lane, 0)
            previous_outcome = last_outcome_by_lane.get(lane)
            lane_config = configs_by_lane.get(lane, loop.config)
            lane_focus_symbols, lane_avoid_symbols = direction_by_lane.get(lane, ((), ()))
            lane_history = tuple(history_by_lane.get(lane, ()))
            result = _execute_generation(
                loop,
                generation_number,
                purpose,
                shape,
                lane_elites,
                lane_occurrence,
                ledger,
                previous_outcome,
                config=lane_config,
                review_focus_symbols=lane_focus_symbols,
                review_avoid_symbols=lane_avoid_symbols,
                lane_history=lane_history,
            )

            if result.outcome is None:
                break  # stopped mid-generation; nothing to record, nothing to advance

            outcome = result.outcome
            elites_by_lane[lane] = result.elites
            lane_occurrences[lane] = lane_occurrence + 1
            if outcome.status == "succeeded":
                last_outcome_by_lane[lane] = outcome
                history_by_lane.setdefault(lane, deque(maxlen=_HISTORY_MAXLEN)).append(outcome)
            if result.next_config is not None:
                configs_by_lane[lane] = result.next_config
                direction_by_lane[lane] = (result.review_focus_symbols, result.review_avoid_symbols)

            # Consecutive-failure circuit breaker -- see `_MAX_CONSECUTIVE_FAILURES`'s own docstring
            # for the incident this exists to catch. `"succeeded"` resets the streak (an intermittent
            # failure must not accumulate toward the trip), `"failed"` extends it, and `"cancelled"`
            # -- the engine was stopped mid-run, so the candidates never ran to completion and this
            # says nothing about whether they work -- does neither: it is simply skipped.
            breaker_tripped = False
            with loop.lock:
                if outcome.status == "failed":
                    loop.consecutive_failures += 1
                    loop.last_failure_error = outcome.error
                    breaker_tripped = loop.consecutive_failures >= _MAX_CONSECUTIVE_FAILURES
                elif outcome.status == "succeeded":
                    loop.consecutive_failures = 0
                    loop.last_failure_error = None

            try:
                candidates_tested = ledger.distinct_candidates()  # type: ignore[attr-defined]
            except Exception:
                candidates_tested = loop.candidates_tested

            with loop.lock:
                loop.history.appendleft(outcome)
                loop.completed_generations += 1
                loop.candidates_tested = candidates_tested
                if result.promotions:
                    loop.promotions = (*loop.promotions, *result.promotions)
                loop.updated_at = _utcnow()
            _update_best(loop, outcome)

            _write_outcome_file(loop.settings, outcome)

            # The generation's plain-language digest, written straight after its outcome file and
            # from that file rather than from `outcome` in memory -- so the digest can only ever
            # describe what actually landed on disk. `write_digest` handles every status
            # (`succeeded`/`failed`/`cancelled`) and degrades to an "unreadable" digest instead of
            # raising, but it is still wrapped: a supervisor that has just recorded a good outcome
            # must not die on the *narration* of it. See `app.evolution.digest`.
            try:
                digest.write_digest(outcome.generation, settings=loop.settings)
            except Exception as exc:  # pragma: no cover -- narration must never fail a generation
                # `loop.append_log`, not a module logger: this module has no logger, and the loop's
                # own log is the surface a reader actually sees (`GET /api/competition/loop` returns
                # its last 200 lines). A failure to narrate belongs where the narration would have
                # been looked for.
                loop.append_log(
                    f"generation {outcome.generation}: OUTCOME.json is recorded, but DIGEST.md could "
                    f"not be written ({type(exc).__name__}: {exc})"
                )

            if breaker_tripped:
                # This generation's own outcome/history/log entry is already recorded above -- the
                # breaker stops the *next* generation from starting, it does not retroactively erase
                # the streak that tripped it. `state="failed"` (not "stopped") is deliberate: this is
                # not the loop reaching a normal end condition (`max_generations`, an explicit stop
                # request), it is the supervisor concluding, from the evidence of
                # `_MAX_CONSECUTIVE_FAILURES` identical failures in a row, that continuing would not
                # produce anything -- exactly the 1,644-failure incident `_MAX_CONSECUTIVE_FAILURES`
                # documents, caught early instead of run to exhaustion.
                with loop.lock:
                    loop.state = "failed"
                    loop.phase = "idle"
                    loop.error = (
                        f"stopped after {loop.consecutive_failures} consecutive failed generations -- "
                        f"repeated error: {loop.last_failure_error}"
                    )
                    loop.stopped_at = _utcnow()
                    loop.updated_at = loop.stopped_at
                loop.append_log(f"loop {loop.loop_id} FAILED: {loop.error}")
                return

            generation_number += 1

            if loop.stop_event.is_set():
                break
            if (
                loop.config.max_generations is not None
                and loop.completed_generations >= loop.config.max_generations
            ):
                break

            if loop.config.cooldown_seconds > 0:
                _set_phase(loop, "cooldown")
                _sleep_checking_stop(loop, loop.config.cooldown_seconds)

        with loop.lock:
            loop.phase = "idle"
            loop.state = "stopped"
            loop.stopped_at = _utcnow()
            loop.updated_at = loop.stopped_at
        loop.append_log(f"loop {loop.loop_id} stopped")

    except Exception as exc:  # only a supervisor-killing failure reaches here
        with loop.lock:
            loop.state = "failed"
            loop.phase = "idle"
            loop.error = f"{type(exc).__name__}: {exc}"
            loop.stopped_at = _utcnow()
            loop.updated_at = loop.stopped_at
        loop.append_log(f"loop {loop.loop_id} FAILED: {loop.error}")


# ---------------------------------------------------------------------------
# Public API -- a process-wide singleton, mirroring `jobs._Registry`'s "one at a time" contract
# ---------------------------------------------------------------------------

_singleton_lock = threading.Lock()
_current_loop: _Loop | None = None


def start_loop(
    config: LoopConfig,
    *,
    settings: Settings | None = None,
    collaborators: Collaborators | None = None,
    output_root: Path | None = None,
) -> LoopStatus:
    """Check the one thing `LoopConfig` cannot check itself, launch the supervisor thread, return at once.

    `LoopConfig` validates every field it can see. The exception is
    `promotion_max_shared_windows`, whose reachability depends on `MAIN_WINDOWS` and
    `MIN_ELIGIBLE_MAIN_WINDOWS` rather than on the config alone -- a ceiling below
    `achievable_shared_windows` is raised as `UnreachablePromotionCeiling` here, before any loop is
    registered or any thread starts, because a promotion gate nothing can clear is indistinguishable
    from a loop that has simply not found anything yet.

    Raises `LoopAlreadyRunning` when a loop is already `"running"`/`"stopping"` -- the atomic
    check-and-set happens under `_singleton_lock`, the same shape as `jobs._Registry.register`.
    `settings` and `collaborators` default to the real application settings and the real sibling
    modules (via `default_collaborators`, imported lazily) when omitted; tests always pass both
    explicitly so nothing here ever touches real data or a real backtest.
    """
    global _current_loop

    # Checked here rather than on `LoopConfig` itself: the answer depends on `MAIN_WINDOWS` and
    # `MIN_ELIGIBLE_MAIN_WINDOWS`, which live in `app.tournament.jobs`, and a model in `models.py`
    # reaching into the tournament package to validate a field would invert the dependency this
    # package is arranged around. It runs before the singleton lock and before the thread, so a
    # refused config leaves no registered loop behind.
    ceiling = config.promotion_max_shared_windows
    if ceiling is not None:
        achievable, detail = achievable_shared_windows(config)
        if ceiling < achievable:
            raise UnreachablePromotionCeiling(ceiling=ceiling, achievable=achievable, detail=detail)

    resolved_settings = settings if settings is not None else get_settings()
    resolved_collaborators = collaborators if collaborators is not None else default_collaborators()
    # `output_root` defaults to the loop's own disposable rounds tree, never `settings.rounds_dir` --
    # see the module docstring's "Auto-generated rounds" section. An explicit `output_root` (what
    # this module's own tests always pass, pointed at `tmp_path`) still overrides it.
    resolved_output_root = output_root if output_root is not None else loop_rounds_root(resolved_settings)

    with _singleton_lock:
        if _current_loop is not None and _current_loop.state in ("running", "stopping"):
            raise LoopAlreadyRunning(_current_loop.loop_id)
        loop = _Loop(
            config=config,
            settings=resolved_settings,
            collaborators=resolved_collaborators,
            output_root=resolved_output_root,
        )
        _current_loop = loop

    # `loop.state` is set to "running" in `_Loop.__init__` and nothing has had a chance to change it
    # yet -- the snapshot returned below is a statement of fact, not an optimistic guess, exactly as
    # `jobs.start_job`'s own comment on this same ordering explains for its `JobAccepted` response.
    assert loop.state == "running", f"a loop is {loop.state!r} before its worker has started"

    thread = threading.Thread(target=_run, args=(loop,), daemon=True, name=f"evolution-loop-{loop.loop_id}")
    loop.thread = thread
    thread.start()

    return loop.snapshot()


def get_status() -> LoopStatus | None:
    """The current (or most recently finished) loop's snapshot, or `None` if none has ever started in
    this process -- the caller (`app.api.evolution`) turns `None` into a `404`."""
    with _singleton_lock:
        loop = _current_loop
    return loop.snapshot() if loop is not None else None


def stop_loop() -> LoopStatus:
    """Request a stop and return immediately with the loop's state at the moment of the request.

    Sets `state` to `"stopping"` and the loop's `threading.Event` under the loop's own lock, then
    returns -- the worker notices at the next generation boundary (or, mid-generation, at the next
    engine-busy retry or cooldown slice) and eventually reaches `"stopped"`; poll `GET` for that.
    Raises `LoopNotRunning` when no loop exists yet, or the existing one has already reached a
    terminal state (`"stopped"`/`"failed"`).
    """
    with _singleton_lock:
        loop = _current_loop
    if loop is None:
        raise LoopNotRunning()
    with loop.lock:
        if loop.state not in ("running", "stopping"):
            raise LoopNotRunning()
        loop.state = "stopping"
        loop.updated_at = _utcnow()
    loop.stop_event.set()
    loop.append_log("stop requested")
    return loop.snapshot()


def reset() -> None:
    """Testing hook, mirroring `app.tournament.jobs.reset_registry`: drop the tracked loop so one
    test's singleton can never leak into the next. Also signals the dropped loop's stop event so any
    daemon thread still running against it (a slow fake that has not yet noticed a prior stop) winds
    down rather than continuing to mutate an object nothing references any more."""
    global _current_loop
    with _singleton_lock:
        loop = _current_loop
        _current_loop = None
    if loop is not None:
        loop.stop_event.set()

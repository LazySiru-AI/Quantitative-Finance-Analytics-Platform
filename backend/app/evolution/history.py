"""Every generation the endless loop has ever run, read from disk, with field-wide statistics.

**The defect this module closes.** `GET /api/competition/loop/history` -- see `app.api.evolution` --
answers from `LoopStatus.history`, a `deque` capped at 20 and held only in the running process's
memory. Restart the process (a deploy, a crash, a `docker compose restart`) and the deque is gone, even
though `app.evolution.loop._write_outcome_file` has been writing every `GenerationOutcome`, permanently,
to `gen{N:04d}/OUTCOME.json` under `app.evolution.models.loop_root` the whole time. Measured against
this repository's own `data/loop/` tree: 30 generation directories exist, and `/history` -- capped at
20 -- cannot show the oldest 10 of them no matter what `limit` a caller passes, because they were never
in memory to begin with. A loop that has run 1,673 generations (the number this module was designed
against -- see the caching section below) would lose 1,653 of them the same way.

**The second defect this module closes is about what gets shown, not how much.** `LoopStatus.best` is
one `Standing` -- first place, across the loop's whole run -- and `app.evolution.feedback.derive_findings`
kind`="winner"` is rank 1 within one generation. Both answer "who won"; neither answers "how did the
*field* do". A searcher generation is ten-odd candidates measured on the same axes (selection median,
worst-case, hit rate, holdout median, trade count, q-value), and a field that is tightly clustered says
something different from one with a fat left tail even when the two have an identical winner. This
module's `GenerationSummary.field` is a `StatSummary` (min/p25/median/p75/max/mean) per axis, over every
candidate that produced a number on that axis -- the distribution the owner asked for, not just its max.

**Read from disk, never from `LoopStatus`.** No import of `app.evolution.loop`'s in-memory state
anywhere in this module. An empty or absent `loop_root` yields an empty list, exactly like
`app.api.evolution.get_history`'s own documented rule -- there is no reason a generations UI should 404
just because no loop happens to be running in this process right now.

**A generation directory can be in one of five states, and this module was written by looking at real
examples of all five before designing anything** (`succeeded`, `failed`, `cancelled`, a directory whose
`OUTCOME.json` is syntactically malformed, and a directory whose `OUTCOME.json` is zero bytes -- the
last one is a real file on disk, `data/loop/gen1673/OUTCOME.json`, left behind by a process that died
mid-`write_text`). The last two are folded into one bucket, `unreadable`, reported as a count rather than
raised as an exception -- see :func:`_parse_outcome`. A directory whose `OUTCOME.json` does not exist yet
(the generation currently being worked on, mid-run, having written only `PLAN.md` so far -- see
`app.evolution.loop._write_plan_file` vs `_write_outcome_file`'s ordering) is counted the same way: there
is nothing wrong with that directory, it simply has nothing to report yet, and the cache below picks it
up correctly the moment `OUTCOME.json` is written.

**A generation with zero standings (every candidate in it failed) reports `field` entries of `null`, not
zero.** `app.evolution.feedback.derive_findings` already encodes the same principle for findings (`if not
standings: return ()`); a `StatSummary` of `0.0` would be read as "the field scored zero", which is a
false claim about a generation that produced no measurement at all. See :func:`_stat_summary`.

**Caching: keyed on each generation directory's own `(mtime_ns, entry_count)`, checked, and shown to
work.** The obvious wrong design is a single cache key on `loop_root` itself -- but that misses the one
directory that keeps changing without the *root's* own mtime moving: the generation currently being
worked on. Its directory is created (bumping the root's mtime and entry count) when `_write_plan_file`
calls `gen_dir.mkdir()`, and its `OUTCOME.json` is added to that *already-existing* directory later by
`_write_outcome_file` -- a write that changes the generation directory's own `(mtime, entry_count)` but
not the root's, since no new *root* entry was created. A root-only cache would therefore keep serving a
stale "still running, no outcome yet" view of that generation for as long as the loop takes to start the
*next* one. `REVIEW.json` makes this worse, not better: it is written by a parallel review worker (see
this module's own note on that file below), which can land on *any* historical generation's directory at
any time, not just the newest -- so freshness cannot be scoped to "only check the newest directory"
either. The design here instead re-derives `(mtime_ns, entry_count)` for *every* generation directory on
every call (`os.scandir` on a directory with at most three entries -- `PLAN.md`, `OUTCOME.json`,
`REVIEW.json` -- costs nothing) and only re-reads a directory's files when that signature has changed
since the last call. This is exactly the shape `app.tournament.results._AGENT_ID_CACHE` already uses for
run files one level down (see that module's own docstring); the same argument for why "the parse of an
unchanged file is wasted work every request" applies here per-directory instead of per-file.

A directory's own mtime advances when an entry is added to or removed from it, on both NTFS and POSIX,
and *not* when an existing file already listed in that directory is rewritten in place -- so this
signature would miss a same-named file being overwritten without ever being deleted first. That case does
not occur on this tree: `_write_plan_file` and `_write_outcome_file` each write their file exactly once
per generation number (a generation number is never reused -- see `app.evolution.models.genome_id_for`'s
own note on why re-running a candidate never re-mints its id, which is the same "never overwrite, only
append" discipline applied one level up), and nothing about the review worker's contract promises
otherwise either, so every real write this tree produces is an add, which the signature does catch.

**Measured cold-path cost.** This repository's live `data/loop/` tree holds 30 generation directories
today (`gen0001`-`gen0028`, plus `gen1673`), not the 1,673 this module was designed against -- see this
module's own test suite for how that was measured and reported as a finding rather than assumed. To get
a real number at the scale this was built for, `list_generations` was run cold (empty cache, freshly
created files) against a synthetic 1,673-directory tree built to the same
27-succeeded/1,644-failed/1-cancelled/1-unreadable mix this task described:
**cold list of the whole tree: ~36s** on this machine, and a repeat call two calls later with nothing
changed on disk: **~0.6s both times** -- a ~60x reduction, `cProfile` confirmed the entire cold-path cost
sits in `_io.open()` itself (14.3s of a 16.6s profiled run, 5,019 opens across `OUTCOME.json`/`PLAN.md`/
`REVIEW.json`) rather than in this module's own parsing or aggregation logic, and the warm call performs
zero of those opens -- only the `os.scandir` + `Path.stat` signature check survives, which is exactly what
this module's cache is designed to skip past. **This number is almost certainly inflated by this specific
Windows sandbox's per-file-open overhead** (2.8ms/open measured, consistent with antivirus real-time
scanning intercepting each freshly created file's first read -- see this module's own test for the exact
script) rather than a property of NTFS or of this code; the ratio between cold and warm, not the absolute
36s, is the number this design should be judged on. See
`tests/test_evolution_history.py::test_measured_cost_against_synthetic_1673_tree` for the exact script
these numbers came from, run via `.venv/Scripts/python.exe -m pytest tests/test_evolution_history.py -k
measured_cost -s` to reproduce them.

**Why `review` is `dict[str, Any] | None`, untyped, forever.** `REVIEW.json` is written by a different,
concurrently-developed worker (a parallel session's job, per this task's own brief) and this package does
not know its schema, is not the right place to define it, and must not import `app.agents` to find out --
`app.evolution.loop.default_collaborators` already keeps that import out of the loop's own machinery for
a documented reason (an agents-package failure must never be able to break the deterministic proposer
path), and coupling the *read* side to `app.agents` for a schema would reintroduce exactly the dependency
that was kept out of the *write* side. Reading it as an opaque JSON object and passing it through
untouched is therefore not a shortcut, it is the only choice that keeps this package's boundary where the
rest of `app.evolution` already draws it.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from app.config import Settings
from app.evolution import digest
from app.evolution.models import Finding, GenerationOutcome, Standing, loop_root
from app.tournament.purposes import Purpose

__all__ = [
    "FailureStreak",
    "FailureStreaksResponse",
    "FieldStats",
    "GateStats",
    "GenerationDetail",
    "GenerationSummary",
    "GenerationsListResponse",
    "LeaderSummary",
    "StatSummary",
    "failure_streaks",
    "get_generation",
    "list_generations",
]


class _Frozen(BaseModel):
    """`frozen=True, extra="forbid"`, matching this task's response-model requirement -- but,
    deliberately, *not* `app.evolution.models._Frozen`'s additional `str_strip_whitespace=True`.
    That config option is right for `models.py`'s short identifier fields (`genome_id`, `agent_id`) and
    wrong here: `GenerationDetail.plan_markdown` carries `PLAN.md`'s full text verbatim, and a stripped
    trailing newline is a silently corrupted "verbatim" (a real one-line diff a test in this module's
    own suite caught by asserting the exact file text round-trips unchanged)."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# StatSummary -- one metric's distribution across one generation's field
# ---------------------------------------------------------------------------


class StatSummary(_Frozen):
    """The distribution of one metric across every candidate in a generation that produced a value for
    it. `n` is that count, always -- a reader must be able to tell "5 candidates, tightly clustered"
    from "1 candidate, so every other field trivially equals it" without a second lookup.

    **Quantile method, fixed and documented here because nothing enforces it at the call site:**
    `statistics.quantiles(sorted(values), n=4, method="inclusive")` -- linear interpolation between the
    two closest ranks, inclusive of both endpoints (this is R's type 7 / Excel's `PERCENTILE.INC`, the
    most common convention and the stdlib's own default `method` value). Checked against
    `statistics.median` for three sample sizes (a 4-tie, an odd 5, and an odd 3) before relying on it:
    the method's own middle cut-point equals `statistics.median` exactly in all three, so `median` here
    never disagrees with a caller that computes `statistics.median` directly over the same values.
    `numpy` is deliberately not imported -- the task this module was built against forbids it, and the
    stdlib function already does the job over `Decimal` inputs without going through `float` at all.
    """

    n: int
    min: Decimal
    p25: Decimal
    median: Decimal
    p75: Decimal
    max: Decimal
    mean: Decimal


def _stat_summary(values: Sequence[Decimal]) -> StatSummary | None:
    """`None` for an empty `values` -- never a `StatSummary` of zeros. See this module's own docstring
    for why that distinction is load-bearing for a generation with no standings."""
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mean = statistics.mean(ordered)
    if n == 1:
        only = ordered[0]
        return StatSummary(n=1, min=only, p25=only, median=only, p75=only, max=only, mean=mean)
    p25, median, p75 = statistics.quantiles(ordered, n=4, method="inclusive")
    return StatSummary(n=n, min=ordered[0], p25=p25, median=median, p75=p75, max=ordered[-1], mean=mean)


# ---------------------------------------------------------------------------
# GenerationSummary and its nested shapes
# ---------------------------------------------------------------------------


class FieldStats(_Frozen):
    """One generation's whole field, on every axis `Standing` carries. Each member is independently
    `None` when no candidate in the generation produced a value for that axis -- a card that ran too
    few windows to get a `median_excess` still contributes to `total_trades` if it took any, and the
    two `None`s are not the same claim.
    """

    median_excess: StatSummary | None
    worst_excess: StatSummary | None
    hit_rate: StatSummary | None
    holdout_median: StatSummary | None
    holdout_gap_pp: StatSummary | None
    total_trades: StatSummary | None
    q_value: StatSummary | None


class GateStats(_Frozen):
    """Copied from this generation's own `kind="gate"` `Finding` (`app.evolution.feedback._gate_finding`),
    never recomputed -- the same "copy, never recompute" discipline `read_standings`'s own docstring
    states for `Standing`. `app.evolution.feedback._goal_finding` also emits `kind="gate"` (see its own
    docstring for why it was given that kind despite measuring something else); this reads only the
    finding whose `evidence` carries a `"margin_pp"` key, which `_goal_finding`'s evidence never has, to
    tell the two apart. `cleared=0, eligible=0, margin_pp=None` when no such finding exists at all -- a
    generation with zero standings never gets one (`derive_findings` returns `()` for empty standings),
    and that triple is a true statement in that case: zero candidates cleared a gate none of them ran.
    """

    cleared: int
    eligible: int
    margin_pp: Decimal | None


class LeaderSummary(_Frozen):
    """This generation's rank-1 eligible standing -- the one number the surface this module replaces
    used to show as the *whole* answer. Kept here too, deliberately, because "who's ahead" is still a
    real question; it is just no longer the only one this API can answer.
    """

    genome_id: str
    display_name: str
    rank: int
    median_excess: Decimal | None
    holdout_median_excess: Decimal | None


class GenerationSummary(_Frozen):
    """One `gen{N:04d}/OUTCOME.json`, reduced to what a generations list needs to render one row.

    `ranked` is `len(standings)` -- how many of this generation's `candidates` (`len(genome_ids)`) got a
    leaderboard row at all. `eligible` is how many of those rows carry `Standing.eligible = True` (the
    leaderboard's own ranking-eligibility bar). `gate.eligible` is a *different*, usually-close-but-not-
    identical count: eligible rows that also have a non-`None` `median_excess`, which is the denominator
    `app.evolution.feedback._gate_finding` actually used when it computed `gate.cleared`. The two exist
    at different layers for different questions and are both reported rather than collapsed into one.
    """

    generation: int
    round_id: str
    purpose: Purpose
    status: Literal["succeeded", "failed", "cancelled"]
    started_at: dt.datetime
    finished_at: dt.datetime
    duration_seconds: float
    windows: tuple[str, ...]
    holdout_windows: tuple[str, ...]
    candidates: int
    ranked: int
    eligible: int
    error: str | None
    field: FieldStats
    gate: GateStats
    promoted: tuple[str, ...]
    leader: LeaderSummary | None
    findings_by_kind: dict[str, int]
    has_review: bool


class GenerationsListResponse(_Frozen):
    """`GET /api/competition/loop/generations`'s body. `total` reflects `purpose`/`status`/
    `succeeded_only` filtering; `unreadable` does not -- an unreadable directory has no known purpose or
    status to filter on, so it is counted once, globally, regardless of what the caller filtered for.
    """

    total: int
    returned: int
    offset: int
    unreadable: int
    generations: tuple[GenerationSummary, ...]


class GenerationDetail(_Frozen):
    """`GET /api/competition/loop/generations/{generation}`'s body. `outcome` is the existing
    `GenerationOutcome` model, verbatim -- every standing, every finding, nothing summarised away.
    """

    outcome: GenerationOutcome
    plan_markdown: str | None
    review: dict[str, Any] | None

    digest_markdown: str | None
    """`gen{N:04d}/DIGEST.md` -- the generation's plain-language record: what ran, what changed since
    the previous generation *in the same lane*, what it found, what it promoted, and what the next
    generation in that lane will try. Written by `app.evolution.digest` straight after `OUTCOME.json`,
    and backfilled over every historical generation, so `None` here means the file is genuinely absent
    rather than that the feature is new. `PLAN.md` says what a generation intended to do and
    `OUTCOME.json` holds its numbers; this is the only surface that says what it *taught*."""


class FailureStreak(_Frozen):
    """One run of consecutive, identically-failing generations, collapsed to a single row. On this
    task's own dataset (1,644 `failed` generations sharing one `OSError` message) this turns a
    generations list nobody could scroll through into a handful of rows -- see :func:`failure_streaks`.
    """

    first_generation: int
    last_generation: int
    count: int
    error: str
    started_at: dt.datetime
    finished_at: dt.datetime

    purposes: tuple[str, ...]
    """Every distinct purpose the streak's generations span, sorted and deduplicated -- never used to
    split the streak itself. `app.evolution.loop` cycles one purpose per generation round-robin
    (`LoopConfig.purposes`), so a run of *consecutive generation numbers* can and does cross lanes; a
    streak is still defined purely by "same status, same error text, consecutive generation number"
    (unchanged from this function's original rule), and this field only reports which lanes that run
    of generations happened to touch. A one-element tuple is the common case a purpose filter in a UI
    is built to act on -- see this module's own test suite for both shapes.
    """


class FailureStreaksResponse(_Frozen):
    streaks: tuple[FailureStreak, ...]


# ---------------------------------------------------------------------------
# Disk reading + the per-directory cache
# ---------------------------------------------------------------------------

_GEN_DIR_RE = re.compile(r"^gen(\d+)$")


def _list_generation_dirs(root: Path) -> list[tuple[int, Path]]:
    """`[(generation, dir_path), ...]` for every `gen<digits>` child of `root`, newest generation
    first. `[]` for a missing `root` -- an empty tree is not an error, matching
    `app.api.evolution.get_history`'s own rule that no loop having run yet is never a 404.
    """
    if not root.is_dir():
        return []
    found: list[tuple[int, Path]] = []
    with os.scandir(root) as it:
        for entry in it:
            if not entry.is_dir():
                continue
            match = _GEN_DIR_RE.match(entry.name)
            if match is not None:
                found.append((int(match.group(1)), Path(entry.path)))
    found.sort(key=lambda pair: pair[0], reverse=True)
    return found


def _dir_signature(path: Path) -> tuple[int, int] | None:
    """`(mtime_ns, entry_count)` of `path`, or `None` if it is missing / not a directory. See this
    module's own docstring for why this pair, and not `loop_root`'s own signature, is the right
    invalidation key."""
    try:
        with os.scandir(path) as it:
            entries = list(it)
    except OSError:
        return None
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return None
    return (mtime_ns, len(entries))


def _parse_outcome(path: Path) -> GenerationOutcome | None:
    """`None` for anything this function cannot turn into a `GenerationOutcome`: a missing file (the
    generation has not finished yet), a zero-byte file (a process died mid-`write_text` -- the real case
    on this tree is `data/loop/gen1673/OUTCOME.json`), malformed JSON, or JSON that parses but does not
    match the schema. Every one of those is a fact about the file, never a reason to 500 a list
    endpoint -- the caller counts a `None` here toward `unreadable` and moves on."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    try:
        return GenerationOutcome.model_validate(data)
    except ValidationError:
        return None


def _read_plan(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _read_review(path: Path) -> dict[str, Any] | None:
    """Raw passthrough -- see this module's own docstring for why this is deliberately untyped.
    `None` for a missing file, an empty file, malformed JSON, or JSON whose top level is not an object
    (a list or scalar would fail `dict[str, Any]` validation downstream anyway); never raised."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


@dataclass
class _CachedGeneration:
    signature: tuple[int, int]
    outcome: GenerationOutcome | None
    plan_markdown: str | None
    review: dict[str, Any] | None

    @property
    def unreadable(self) -> bool:
        return self.outcome is None

    @property
    def has_review(self) -> bool:
        return self.review is not None


#: `{loop_root: {generation: _CachedGeneration}}`. Keyed by the resolved `loop_root` path (not by
#: `Settings` itself, which is not hashable in a way that would be meaningful here) so that two
#: different `Settings` -- production and a test's `tmp_path` -- never share or clobber each other's
#: entries. Unbounded across distinct roots, exactly like `app.tournament.results._AGENT_ID_CACHE`: in
#: a real process `loop_root(settings)` is the same path on every call, so this dict holds one entry in
#: practice; a test suite constructing many short-lived `tmp_path` roots adds one small entry each,
#: which is not a concern for a process that exits when the suite does.
_CACHE: dict[Path, dict[int, _CachedGeneration]] = {}


def _read_generation(gen_dir: Path, generation: int, *, cache: dict[int, _CachedGeneration]) -> _CachedGeneration | None:
    signature = _dir_signature(gen_dir)
    if signature is None:
        cache.pop(generation, None)
        return None
    cached = cache.get(generation)
    if cached is not None and cached.signature == signature:
        return cached
    entry = _CachedGeneration(
        signature=signature,
        outcome=_parse_outcome(gen_dir / "OUTCOME.json"),
        plan_markdown=_read_plan(gen_dir / "PLAN.md"),
        review=_read_review(gen_dir / "REVIEW.json"),
    )
    cache[generation] = entry
    return entry


def _generation_cache(root: Path) -> dict[int, _CachedGeneration]:
    """The cache dict for `root`, created empty on first use. Pruning of generation numbers no longer
    present on disk happens in `list_generations` (the one caller that already enumerates every
    directory on the tree per call, so the check is free there); `get_generation` and
    `failure_streaks` do not prune, since neither scans the full tree looking for removals on its own."""
    return _CACHE.setdefault(root, {})


# ---------------------------------------------------------------------------
# Field statistics + gate/leader extraction from one outcome
# ---------------------------------------------------------------------------


def _decimal_values(values: Iterable[Decimal | None]) -> list[Decimal]:
    return [v for v in values if v is not None]


def _field_stats(standings: Sequence[Standing]) -> FieldStats:
    gaps: list[Decimal] = []
    for standing in standings:
        if standing.median_excess is not None and standing.holdout_median_excess is not None:
            gaps.append((standing.median_excess - standing.holdout_median_excess) * 100)
    return FieldStats(
        median_excess=_stat_summary(_decimal_values(s.median_excess for s in standings)),
        worst_excess=_stat_summary(_decimal_values(s.worst_excess for s in standings)),
        hit_rate=_stat_summary([Decimal(str(s.hit_rate)) for s in standings if s.hit_rate is not None]),
        holdout_median=_stat_summary(_decimal_values(s.holdout_median_excess for s in standings)),
        holdout_gap_pp=_stat_summary(gaps),
        total_trades=_stat_summary([Decimal(s.total_trades) for s in standings]),
        q_value=_stat_summary([Decimal(str(s.q_value)) for s in standings if s.q_value is not None]),
    )


def _gate_stats(findings: Sequence[Finding]) -> GateStats:
    for finding in findings:
        if finding.kind != "gate" or "margin_pp" not in finding.evidence:
            continue
        evidence = finding.evidence
        try:
            cleared = int(evidence.get("cleared", 0))
            eligible = int(evidence.get("eligible", 0))
        except (TypeError, ValueError):
            continue
        margin_raw = evidence.get("margin_pp")
        margin: Decimal | None
        if margin_raw is None:
            margin = None
        else:
            try:
                margin = Decimal(str(margin_raw))
            except InvalidOperation:
                margin = None
        return GateStats(cleared=cleared, eligible=eligible, margin_pp=margin)
    return GateStats(cleared=0, eligible=0, margin_pp=None)


def _leader(standings: Sequence[Standing]) -> LeaderSummary | None:
    """Rank-1 among eligible standings, matching `app.evolution.feedback._winner`'s own rule
    exactly (tie-break on `genome_id`) without importing that private helper across the package
    boundary `feedback.py`'s own docstring draws."""
    eligible = [s for s in standings if s.eligible]
    if not eligible:
        return None
    winner = min(eligible, key=lambda s: (s.rank, s.genome_id))
    return LeaderSummary(
        genome_id=winner.genome_id,
        display_name=winner.display_name,
        rank=winner.rank,
        median_excess=winner.median_excess,
        holdout_median_excess=winner.holdout_median_excess,
    )


def _summarize(outcome: GenerationOutcome, *, has_review: bool) -> GenerationSummary:
    findings_by_kind: dict[str, int] = {}
    for finding in outcome.findings:
        findings_by_kind[finding.kind] = findings_by_kind.get(finding.kind, 0) + 1
    return GenerationSummary(
        generation=outcome.generation,
        round_id=outcome.round_id,
        purpose=outcome.purpose,
        status=outcome.status,
        started_at=outcome.started_at,
        finished_at=outcome.finished_at,
        duration_seconds=(outcome.finished_at - outcome.started_at).total_seconds(),
        windows=outcome.windows,
        holdout_windows=outcome.holdout_windows,
        candidates=len(outcome.genome_ids),
        ranked=len(outcome.standings),
        eligible=sum(1 for s in outcome.standings if s.eligible),
        error=outcome.error,
        field=_field_stats(outcome.standings),
        gate=_gate_stats(outcome.findings),
        promoted=outcome.promoted,
        leader=_leader(outcome.standings),
        findings_by_kind=findings_by_kind,
        has_review=has_review,
    )


# ---------------------------------------------------------------------------
# Public reader functions -- what `app.api.evolution` calls
# ---------------------------------------------------------------------------


def list_generations(
    settings: Settings,
    *,
    limit: int = 50,
    offset: int = 0,
    purpose: str | None = None,
    status: str | None = None,
    succeeded_only: bool = False,
) -> tuple[list[GenerationSummary], int, int]:
    """`(page, total, unreadable)`, newest generation first.

    `total` is the count of *readable* generation directories matching `purpose`/`status`/
    `succeeded_only` -- the size of the list `offset`/`limit` page into, not the size of the directory
    tree. `unreadable` is a separate, unfiltered count (see `GenerationsListResponse`'s own docstring
    for why an unreadable directory cannot be evaluated against a filter it has no parsed data for).
    `limit`/`offset` are clamped to their documented floors here too, defensively, since this function
    is called directly by this module's own tests as well as by the HTTP layer that already enforces
    the `1..200`/`>=0` bounds via `fastapi.Query`.
    """
    limit = max(1, limit)
    offset = max(0, offset)
    root = loop_root(settings)
    dirs = _list_generation_dirs(root)
    cache = _generation_cache(root)
    current = {generation for generation, _ in dirs}
    for stale in set(cache) - current:
        del cache[stale]

    unreadable = 0
    matching: list[GenerationSummary] = []
    for generation, gen_dir in dirs:
        entry = _read_generation(gen_dir, generation, cache=cache)
        if entry is None or entry.unreadable or entry.outcome is None:
            unreadable += 1
            continue
        outcome = entry.outcome
        if purpose is not None and str(outcome.purpose) != purpose:
            continue
        if status is not None and outcome.status != status:
            continue
        if succeeded_only and outcome.status != "succeeded":
            continue
        matching.append(_summarize(outcome, has_review=entry.has_review))

    total = len(matching)
    page = matching[offset : offset + limit]
    return page, total, unreadable


def get_generation(settings: Settings, generation: int) -> GenerationDetail | None:
    """`None` when `generation`'s directory does not exist, or exists but its `OUTCOME.json` cannot be
    read -- both read as "not found" at this layer; `app.api.evolution` turns that into the endpoint's
    documented `404`. `plan_markdown` is `None` when `PLAN.md` is absent (should not happen once
    `OUTCOME.json` exists, since `_write_plan_file` runs first, but this function does not assume the
    write order held for every historical directory and reports what it actually finds).
    """
    root = loop_root(settings)
    gen_dir = root / f"gen{generation:04d}"
    cache = _generation_cache(root)
    entry = _read_generation(gen_dir, generation, cache=cache)
    if entry is None or entry.outcome is None:
        return None
    try:
        digest_markdown: str | None = digest.digest_path(settings, generation).read_text(encoding="utf-8")
    except OSError:
        # Absent or unreadable is "no digest", never an error: the same tolerance `plan_markdown`
        # gets above, and for the same reason -- a missing narration must not hide a real outcome.
        digest_markdown = None
    return GenerationDetail(
        outcome=entry.outcome,
        plan_markdown=entry.plan_markdown,
        review=entry.review,
        digest_markdown=digest_markdown,
    )


def failure_streaks(settings: Settings) -> tuple[FailureStreak, ...]:
    """Consecutive (by generation number, not merely by list position) `status="failed"` generations
    sharing the identical `error` string, collapsed into one `FailureStreak` each -- newest first.

    A streak breaks on any of three things: a different `error` string, a non-`"failed"` status in
    between (`succeeded`, `cancelled`, or an unreadable directory -- the last of these cannot be
    confirmed to share the streak's error, so it ends the streak rather than being assumed to match),
    or a gap in generation numbers (a directory missing from disk entirely). On this task's own
    dataset -- 1,644 `failed` generations, all one `OSError` string, run back to back -- this is what
    turns that count into a handful of rows a UI can actually render.
    """
    root = loop_root(settings)
    dirs = _list_generation_dirs(root)
    cache = _generation_cache(root)

    streaks: list[FailureStreak] = []
    current: list[GenerationOutcome] = []

    def _flush() -> None:
        if not current:
            return
        streaks.append(
            FailureStreak(
                first_generation=current[-1].generation,
                last_generation=current[0].generation,
                count=len(current),
                error=current[0].error or "",
                started_at=min(o.started_at for o in current),
                finished_at=max(o.finished_at for o in current),
                purposes=tuple(sorted({str(o.purpose) for o in current})),
            )
        )
        current.clear()

    for generation, gen_dir in dirs:
        entry = _read_generation(gen_dir, generation, cache=cache)
        outcome = entry.outcome if entry is not None else None
        is_failed = outcome is not None and outcome.status == "failed"
        if not is_failed:
            _flush()
            continue
        assert outcome is not None  # narrowed by is_failed
        continues = (
            current
            and outcome.error == current[-1].error
            and generation == current[-1].generation - 1
        )
        if not continues:
            _flush()
        current.append(outcome)
    _flush()
    return tuple(streaks)

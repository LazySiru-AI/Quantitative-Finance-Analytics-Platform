"""The per-generation digest and the rolling journal: what a generation taught, in a form a person
(or the next generation) can act on without re-deriving it.

**The gap this closes.** `gen{N:04d}/PLAN.md` says what was *about* to run and `OUTCOME.json` holds
the numbers it produced; neither says what changed since the last generation in the same lane, which
findings are still open, or what the next generation should try. The owner's own words: "each step it
runs, if manager can summarize previous generation and what's next on the findings set or status
log." This module is that summary -- one Markdown file per generation
(:func:`write_digest` -> `gen{N:04d}/DIGEST.md`), and a rolling append of all of them
(:func:`rebuild_journal` -> `JOURNAL.md`).

**Deterministic, not generated -- the same discipline `app.evolution.feedback` applies to findings.**
:func:`render_digest` is a pure function of its arguments: no wall-clock read, no randomness, no model
call, and every sentence it writes traces to a field already on `GenerationOutcome`, `PLAN.md`'s own
text, or the loop's ledger. Two calls with identical arguments produce byte-identical Markdown. See
`app.evolution.feedback`'s own module docstring for why a finding has to be a measurement rather than
an opinion for anyone downstream to trust it -- this module holds the same line for the sentence that
sits *above* the findings: no adjective here ("promising", "strong") that is not itself a copied or
directly-derived number.

**"Previous generation" means the previous generation in the same lane, not the previous directory on
disk.** The loop cycles `LoopConfig.purposes` round-robin, so `gen1858` (trading) sits on disk between
`gen1855` (roth) and `gen1859` (roth) -- comparing 1859 against 1858 would difference two unrelated
purposes' fields against each other. `app.evolution.feedback._goal_finding` already computed the right
answer once, per generation, and recorded it in that generation's own `kind="gate"` finding whose
evidence carries a `"goal"` key (see :func:`_goal_finding_evidence`): `"previous_generation"` there is
this same lane's own prior generation, copied here rather than recomputed -- the same "copy, never
recompute" rule `app.evolution.feedback.read_standings` states for its own numbers.

**The gap is handled explicitly, not by silently differencing across it.** `gen0001`..`gen0028` and
`gen1673`..`gen1877` are the only generation directories that exist; `gen0029`..`gen1672` were never
written at all (`app.evolution.models.generated_tier_dir`'s own docstring records why: 1,644
consecutive `OSError: [Errno 30] Read-only file system` failures from a generated-card path that
resolved inside a read-only container image layer, fixed before generation 1673 ran). A generation
whose own recorded "previous generation" sits on the far side of a run of missing directories gets a
digest that says so plainly instead of computing a field-median delta across 1,644 generations of
nothing. See :func:`_missing_between` and :func:`_gap_note`.

**Unreadable and incomplete directories still get a digest.** `gen1673/OUTCOME.json` is a real,
zero-byte file (a process that died mid-`write_text`); `gen1849/OUTCOME.json` does not exist at all
(only `PLAN.md` was written before whatever ran next overwrote the generation counter). Both are
"unreadable" here, in the same sense `app.evolution.history._parse_outcome` already uses that word --
a fact about the file, reported plainly, never a reason to omit the generation from the journal or to
guess at numbers it does not have. See :func:`_read_outcome`.
"""

from __future__ import annotations

import bisect
import itertools
import json
import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import ValidationError

from app.config import Settings
from app.evolution.models import Finding, GenerationOutcome, Standing, loop_root

__all__ = [
    "CaveatStats",
    "FieldSnapshot",
    "JournalEntry",
    "caveat_stats",
    "digest_path",
    "existing_generation_numbers",
    "journal_path",
    "read_journal_entries",
    "rebuild_journal",
    "render_digest",
    "write_digest",
]

_GEN_DIR_RE = re.compile(r"^gen(\d+)$")
_EM_DASH = "—"

#: Where the documented gap begins and how many generation numbers it spans -- `gen0029`..`gen1672`,
#: none of which ever got a directory. Used only to decide whether :func:`_gap_note` may cite the
#: specific, already-documented cause (a read-only library path); any other gap this module ever
#: meets (a synthetic one in a test, or a future one this repository has not had yet) gets the
#: generic "N generations have no directory on disk" sentence and no invented cause.
_KNOWN_GAP_PREVIOUS = 28
_KNOWN_GAP_COUNT = 1644


# ---------------------------------------------------------------------------
# On-disk path conventions
# ---------------------------------------------------------------------------


def digest_path(settings: Settings, generation: int) -> Path:
    """`gen{N:04d}/DIGEST.md`, written beside that generation's `PLAN.md` and `OUTCOME.json`."""
    return loop_root(settings) / f"gen{generation:04d}" / "DIGEST.md"


def journal_path(settings: Settings) -> Path:
    """`data/loop/JOURNAL.md` -- every digest, oldest first, rebuilt from scratch by
    :func:`rebuild_journal`."""
    return loop_root(settings) / "JOURNAL.md"


def existing_generation_numbers(root: Path) -> list[int]:
    """Every `gen<digits>` directory under `root`, ascending. `[]` for a missing or empty `root` --
    matching `app.evolution.history._list_generation_dirs`'s own "an absent tree is not an error"
    rule, just sorted the other way (this module reads oldest-first; that one reads newest-first)."""
    if not root.is_dir():
        return []
    found: list[int] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        match = _GEN_DIR_RE.match(child.name)
        if match is not None:
            found.append(int(match.group(1)))
    found.sort()
    return found


# ---------------------------------------------------------------------------
# Reading a generation directory
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _OutcomeRead:
    outcome: GenerationOutcome | None
    reason: str | None
    """Why `outcome` is `None`. Always `None` when `outcome` is not, and always a fixed, specific
    sentence otherwise -- never a bare exception repr, so two unreadable files that failed for the
    same reason describe themselves identically."""


def _read_outcome(path: Path) -> _OutcomeRead:
    """The same four-way "why can't this be read" classification
    `app.evolution.history._parse_outcome` makes, with the reason kept (that function only counts
    toward `unreadable`; this one has to explain itself in prose)."""
    if not path.exists():
        return _OutcomeRead(None, "`OUTCOME.json` does not exist")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return _OutcomeRead(None, f"`OUTCOME.json` could not be read ({exc})")
    if not raw.strip():
        return _OutcomeRead(None, "`OUTCOME.json` is present but empty (0 bytes)")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _OutcomeRead(None, "`OUTCOME.json` is not valid JSON")
    try:
        return _OutcomeRead(GenerationOutcome.model_validate(data), None)
    except ValidationError:
        return _OutcomeRead(None, "`OUTCOME.json` does not match the expected schema")


def _read_text_or_none(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Field snapshot -- derived context, never a copy of another module's aggregate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldSnapshot:
    """One generation's field, reduced to the one number this digest needs: the median selection
    excess across every standing that has one. This is *derived* context (the house rule in
    `SPEC.md`'s "House rules" section: "Derived context (percentiles, field medians) is fine and must
    say what set it was computed over") -- `median_excess` here is `statistics.median` over this
    generation's own `Standing.median_excess` values, computed fresh each time from data this module
    already has, never a number copied from `app.evolution.history.FieldStats` (that module is not on
    this workstream's file list and this digest's one field median does not need its full
    five-number summary).
    """

    n: int
    median_excess: Decimal | None
    """`None`, never `0`, when no standing in the generation has a measured `median_excess` -- the
    "null is never zero" house rule applies to a derived number exactly as much as a stored one."""


def _field_snapshot(standings: Sequence[Standing]) -> FieldSnapshot:
    values = [s.median_excess for s in standings if s.median_excess is not None]
    if not values:
        return FieldSnapshot(n=0, median_excess=None)
    return FieldSnapshot(n=len(values), median_excess=statistics.median(values))


# ---------------------------------------------------------------------------
# The standing caveat -- read from the ledger, never hardcoded
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CaveatStats:
    """The whole ledger's holdout-positive fraction, computed from `data/loop/ledger.jsonl` --
    `SPEC.md`'s own "94.3%" figure, reproduced here from data rather than hardcoded so a ledger that
    keeps growing after this module ships keeps telling the truth.

    **Denominator is rows with a measured `holdout_median_excess`, not every ledger row.** A row
    ledgered before a holdout figure was computed for it (or that never ran the holdout windows) has
    nothing to say about whether holdout discriminates; counting it in the denominator with an
    implicit "not positive" would understate the fraction against a question it was never asked.
    Measured against this repository's own frozen ledger: 2,374 rows, 2,364 with a holdout figure,
    2,230 of those positive -- 94.331...%, which rounds to the SPEC's own 94.3%.
    """

    positive: int
    total: int
    """Rows with a non-`None` `holdout_median_excess` -- the fraction's denominator."""

    candidates_ever_run: int
    """Every row in the ledger, regardless of whether it has a holdout figure -- `SPEC.md`'s
    "2,374 candidates ever run", reported alongside the fraction so a reader can see the denominator
    the fraction did *not* use."""

    @property
    def positive_fraction(self) -> Decimal | None:
        """`None` only when `total` is zero -- an empty or holdout-free ledger has nothing to report
        a fraction over, and `None` here renders as an em dash downstream, never `0.0%`."""
        if self.total == 0:
            return None
        return Decimal(self.positive) / Decimal(self.total)


#: `{ledger_path: (signature, CaveatStats)}`, the same per-process, mtime-and-size-keyed cache
#: shape `app.evolution.dossier._LEDGER_CACHE` already uses for its own read of this identical file
#: (`_cached_ledger`/`_ledger_signature` there) -- matched deliberately rather than invented afresh,
#: since `write_digest` now reads this cache from inside the loop's own supervisor thread, once per
#: generation (`app.evolution.loop._run`, immediately after `_write_outcome_file`), and the ledger
#: this reads is the same monotonically-growing `ledger.jsonl` (~1MB / 2,374 rows and climbing) that
#: module already learned was too expensive to re-parse on every call. `tools/backfill_digests.py`
#: additionally computes `CaveatStats` once itself and passes it to every `write_digest` call in a
#: run, so this cache mainly protects the live per-generation path and any caller that does not
#: already do its own hoisting.
#:
#: Keyed on `Path` rather than on `Settings` (which is not usefully hashable for this purpose) --
#: the identical reasoning `app.evolution.history._CACHE` and `app.evolution.dossier._CARD_CACHE`
#: both give for their own module-level caches: a real process has exactly one `ledger.jsonl` path in
#: practice, and a test suite constructing many short-lived `tmp_path` roots adds one small entry
#: each, which does not matter for a process that exits when the suite does.
_CAVEAT_CACHE: dict[Path, tuple[tuple[int, int] | None, CaveatStats]] = {}


def _ledger_signature(path: Path) -> tuple[int, int] | None:
    """`(mtime_ns, size)`, or `None` when `path` cannot be stat'd (missing, or a transient race).

    `None` is a distinct sentinel, never `(0, 0)` -- collapsing "no file" onto a real-looking tuple
    would risk exactly the poisoning a cache like this must not do: if some future filesystem or test
    fixture ever produced a genuine zero-byte file with an epoch mtime, `(0, 0)` would falsely read as
    a cache hit against a *previous* "missing file" entry. `None` cannot collide with any real
    `os.stat_result`, so a cached "missing" entry is invalidated the moment the file actually appears,
    unconditionally.
    """
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _read_ledger_text(path: Path) -> str | None:
    """The one place this module reads `ledger.jsonl` off disk -- factored out from
    :func:`caveat_stats` so a test can count or patch exactly this call without also having to fake
    the cache-signature machinery around it. `None` for a missing or unreadable file."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _parse_ledger_text(raw: str) -> CaveatStats:
    """Pure reduction of `ledger.jsonl`'s raw text to :class:`CaveatStats` -- no I/O, so
    :func:`caveat_stats` can call this only on a genuine cache miss. A line that is not valid JSON, or
    whose `holdout_median_excess` is not a decimal-parseable value, is skipped rather than aborting
    the whole read, matching `app.evolution.promotion.read_pending_seats`'s "one bad row must not
    hide every other one" rule -- deliberately more tolerant than `app.evolution.ledger.Ledger.entries`
    (which raises on a malformed *non-trailing* line), because this reader runs inside the loop's own
    supervisor thread on every generation and must never be the reason a digest write throws.
    """
    candidates_ever_run = 0
    total = 0
    positive = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        candidates_ever_run += 1
        holdout = row.get("holdout_median_excess")
        if holdout is None:
            continue
        try:
            value = Decimal(str(holdout))
        except InvalidOperation:
            continue
        total += 1
        if value > 0:
            positive += 1
    return CaveatStats(positive=positive, total=total, candidates_ever_run=candidates_ever_run)


def caveat_stats(settings: Settings) -> CaveatStats:
    """`data/loop/ledger.jsonl`, reduced to :class:`CaveatStats`, cached per-process on the file's
    own `(mtime_ns, size)` -- a second call with the file unchanged returns the cached value without
    reading or parsing the file again (:data:`_CAVEAT_CACHE`, matching
    `app.evolution.dossier`'s own ledger cache discipline; see that constant's docstring for why).

    A missing ledger degrades to `CaveatStats(0, 0, 0)` -- `positive_fraction` then reads `None` --
    rather than raising: every digest still has to be writable even before a single ledger row
    exists (the very first generation of a fresh loop). That empty result **is** cached, keyed on the
    `None` signature :func:`_ledger_signature` returns for a missing file -- safe to cache because
    `None` can never collide with a real file's signature (see that function's own docstring), so the
    moment a real `ledger.jsonl` appears this cache entry is invalidated unconditionally, never
    reused past the point the file it describes stopped being true.
    """
    path = loop_root(settings) / "ledger.jsonl"
    signature = _ledger_signature(path)
    cached = _CAVEAT_CACHE.get(path)
    if cached is not None and cached[0] == signature:
        return cached[1]

    raw = _read_ledger_text(path)
    if raw is None:
        empty = CaveatStats(positive=0, total=0, candidates_ever_run=0)
        if signature is None:
            # A genuinely missing file -- safe to cache (see `_ledger_signature`'s own docstring on
            # why `None` cannot collide with a real file's signature later).
            _CAVEAT_CACHE[path] = (signature, empty)
        # `signature` was a real `(mtime_ns, size)` but the read itself still failed (a transient
        # race -- the file existed a moment ago and does not now, or briefly could not be opened).
        # Deliberately NOT cached: caching an empty result under a signature that might have
        # described real, readable content is exactly the poisoning this cache must not do, and the
        # cost of re-attempting the read on the next call is one more `read_text` of a file this
        # branch already knows is in a bad state right now.
        return empty

    stats = _parse_ledger_text(raw)
    _CAVEAT_CACHE[path] = (signature, stats)
    return stats


def _format_caveat_pct(caveat: CaveatStats) -> str:
    fraction = caveat.positive_fraction
    if fraction is None:
        return _EM_DASH
    return f"{fraction * 100:.1f}"


# ---------------------------------------------------------------------------
# Small, local formatting helpers -- no shared "_pp" import: `app.evolution.feedback._pp` is
# private, and this module's own formatting needs (plain vs signed, em dash for None) differ enough
# from that function's one call site to be worth stating fresh rather than reaching across the
# package boundary `feedback.py`'s own docstring draws for a private helper.
# ---------------------------------------------------------------------------


def _format_pct(value: Decimal | None) -> str:
    if value is None:
        return _EM_DASH
    return f"{value * 100:.2f}%"


def _format_signed_pp(value: Decimal | None) -> str:
    if value is None:
        return _EM_DASH
    return f"{value:+.2f}pp"


#: Matches a bare decimal literal with 10 or more digits after the point, not already followed by
#: `pp` or `%` -- see :func:`_humanise_figures` for why this specific shape and no other. Measured
#: directly rather than merely reasoned about: `_parameter_findings`' `.6g`-formatted trait means can
#: reach 7-8 digits after the point for a small trait value (`0.0641667` -- 6 significant figures of a
#: value under 0.1 -- is a real example this module's own first draft of this regex, at a 7-digit
#: threshold, wrongly turned into `+6.42%`); every real measured-excess figure in this codebase's own
#: ledger carries 20-30 digits from the `Decimal` arithmetic chain that produced it. 10 sits with
#: comfortable margin on both sides of that gap.
_LONG_DECIMAL_RE = re.compile(r"(?<![\w.])(-?\d+\.\d{10,})(?!\d)(?!pp)(?!%)")


def _humanise_figures(text: str) -> str:
    """Render a copy of `text` with every bare, high-precision decimal fraction rewritten as a
    signed percentage to two places -- `0.2465181788788578626915809364` becomes `+24.65%`,
    `-0.1169003367454490237061650321` becomes `-11.69%`.

    **This is a presentation transform, not a rewrite of the record.** `Finding.summary` is the
    measurement -- `app.evolution.feedback`'s own module docstring is why that text must never be
    edited: "two passes over the same standings produce the same findings", and a finding a person
    can trust as a measurement has to be the same string every time, on disk, forever. Nothing this
    function touches ever reaches disk: `write_digest` calls it only when composing the Markdown
    string it writes to `DIGEST.md`, never when writing `OUTCOME.json`, and `OUTCOME.json` already
    exists (written by `app.evolution.loop._write_outcome_file`) before this function is ever called.
    Calling this on a `Finding.summary` and discarding the result changes nothing about the finding;
    only the digest's own copy of the sentence is different.

    **Before:**
    `"g1859-fd7c2c196f35's holdout median (0.1487857552623824866024516738) is consistent with its
    selection median (0.2465181788788578626915809364): drop = 9.77pp against a 21.2pp margin."`

    **After:**
    `"g1859-fd7c2c196f35's holdout median (+14.88%) is consistent with its selection median
    (+24.65%): drop = 9.77pp against a 21.2pp margin."`

    Note what did *not* change: `9.77pp` and `21.2pp` (already-formatted percentage-point figures,
    excluded by the trailing `pp` the regex refuses to match past) and every word, id and window name
    in the sentence -- only the two bare numerals' presentation changed.

    **Why "10 or more digits after the point" and not, say, "any decimal".** Every high-precision
    figure this module actually needs to humanise (`median_excess`, `holdout_median_excess`,
    `worst_excess` -- anything that traces back to `Decimal` arithmetic over price data) carries 20-30
    digits of precision in this codebase, as `_pp`'s own docstring in `app.evolution.feedback`
    documents for the identical fault this function fixes one layer up. A trait mean like `0.196` (3
    digits), a q-value like `0.0049` (4 digits), a margin like `21.2` (1 digit) or an already-rendered
    `9.77pp` all sit far under the threshold and are left exactly as they were -- verified in this
    module's own test suite against exactly those examples, not merely asserted in this docstring.

    **A lower threshold was tried first and measurably wrong.** `app.evolution.history.StatSummary`'s
    own `mean` field (`statistics.fmean`, rendered at 6 significant figures by `_parameter_findings`)
    can reach 7-8 digits after the point for a trait value under about 0.1 -- `0.0641667` (a real
    `band_pct` field mean) is exactly 7 digits, and this function's first draft, threshold set at 7,
    silently turned it into `+6.42%` in this module's own smoke test before that test's assertions
    caught it. 10 sits with comfortable margin above anything `.6g` formatting of this codebase's own
    trait ranges (`stop_loss_pct`, `position_pct`, `band_pct` and friends, roughly 0.02-0.99) can
    produce, and equally comfortably below the 20-30 digits every real measured-excess figure carries.
    """
    def _replace(match: re.Match[str]) -> str:
        try:
            value = Decimal(match.group(1))
        except InvalidOperation:  # pragma: no cover -- the regex only matches valid decimal syntax
            return match.group(0)
        return f"{value * 100:+.2f}%"

    return _LONG_DECIMAL_RE.sub(_replace, text)


# ---------------------------------------------------------------------------
# Reading the previous generation in the same lane
# ---------------------------------------------------------------------------


def _goal_finding(outcome: GenerationOutcome) -> Finding | None:
    """The one `kind="gate"` finding `app.evolution.feedback._goal_finding` emits, told apart from
    the ordinary gate finding (also `kind="gate"`, `app.evolution.feedback._gate_finding`) by the
    `"goal"` evidence key the ordinary one never carries -- the same discriminator
    `app.evolution.history._gate_stats` already uses, in reverse (that function looks for
    `"margin_pp"`, which only the ordinary gate finding has; this looks for the key only the goal
    finding has, which is equivalent and reads more directly for this module's purpose)."""
    for finding in outcome.findings:
        if finding.kind == "gate" and "goal" in finding.evidence:
            return finding
    return None


def _previous_generation_number(outcome: GenerationOutcome) -> int | None:
    """This lane's own previous generation, copied from the goal finding's own
    `"previous_generation"` evidence -- never recomputed by scanning generation numbers, which would
    have no way to tell "no earlier generation in this lane" apart from "the earlier generation
    directory happens to not exist". `None` when there is no goal finding (an empty-`standings`
    generation has no findings at all -- `derive_findings` returns `()`) or when the goal finding
    itself has no previous generation to report (this lane's first measured generation, or the
    in-process `history_by_lane` that tracks this having been reset by a restart -- see
    `app.evolution.loop._run`'s own per-lane state, which does not persist across a process restart)."""
    goal = _goal_finding(outcome)
    if goal is None:
        return None
    raw = goal.evidence.get("previous_generation")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _missing_between(existing: Sequence[int], lo_exclusive: int, hi_exclusive: int) -> int:
    """How many generation numbers strictly between `lo_exclusive` and `hi_exclusive` have **no**
    directory in `existing` (a sorted list of generation numbers actually on disk). `0` for two
    generations with every number between them present, exactly like `gen1855`..`gen1859` (three
    intervening generations, all on disk, all a different lane -- this counts directories, not
    lanes). `existing` is searched with `bisect` rather than a Python-level range scan so this stays
    cheap even when `hi_exclusive - lo_exclusive` is 1,645, as it is for the one gap this
    repository's own tree has ever had.
    """
    if hi_exclusive <= lo_exclusive + 1:
        return 0
    lo_idx = bisect.bisect_right(existing, lo_exclusive)
    hi_idx = bisect.bisect_left(existing, hi_exclusive)
    present = hi_idx - lo_idx
    span = hi_exclusive - lo_exclusive - 1
    return span - present


def _nearest_previous_directory(existing: Sequence[int], generation: int) -> int | None:
    """The highest generation number in `existing` strictly less than `generation` -- used only for
    the *unreadable* case, where there is no `OUTCOME.json` to read a lane-aware
    `"previous_generation"` from, so the best this module can honestly say is "the nearest earlier
    generation directory on disk", lane unknown. `None` when `generation` is the first directory on
    the whole tree."""
    idx = bisect.bisect_left(existing, generation)
    if idx == 0:
        return None
    return existing[idx - 1]


def _gap_note(previous_generation: int, gap_count: int) -> str | None:
    """The documented cause of the one gap this repository has had, cited only when the numbers
    actually match it -- never asserted for a gap this module cannot verify the cause of. See this
    module's own docstring for why the cause is not inferred from data (there is none: every
    directory in `gen0029`..`gen1672` is simply absent, not present-and-failed) and is instead cited
    from `app.evolution.models.generated_tier_dir`'s own docstring, the permanent record of it.
    """
    if previous_generation == _KNOWN_GAP_PREVIOUS and gap_count == _KNOWN_GAP_COUNT:
        return (
            "This is the documented gap: no generation directory exists for gen0029 through "
            "gen1672. `app.evolution.models.generated_tier_dir`'s own docstring records the cause -- "
            "1,644 consecutive `OSError: [Errno 30] Read-only file system` failures writing a "
            "generated card into a path that resolved inside a read-only container image layer, "
            "fixed before generation 1673 ran."
        )
    return None


def _next_generation_for(
    root: Path, existing: Sequence[int], generation: int
) -> int | None:
    """The next generation, in this same lane, that this repository actually ran -- found by reading
    forward through every later generation's own `OUTCOME.json` until one names `generation` as its
    own `"previous_generation"` (:func:`_previous_generation_number`, the same lane-aware field
    :func:`_next_generation_for`'s caller already trusts for "previous"), or `None` if none does.

    **Never `generation + 1`.** The loop cycles `LoopConfig.purposes` round-robin, so the very next
    *directory* after a roth generation is usually a different purpose's -- `gen1860` sits between
    `gen1859` (roth) and whatever roth generation comes after it (`gen1863`, on this repository's own
    tree), and asserting `1860` as "what generation 1860 will try" would name a lane this generation
    cannot know anything about.

    **`None` is the honest, common answer for a digest written live.** `write_digest` is called right
    after `_write_outcome_file` writes *this* generation's own record (see this workstream's report to
    the orchestrator for the exact call site), which means `generation` is the newest directory on
    disk at that moment -- there is no later generation for this function to find yet, so it correctly
    returns `None` and the digest says so rather than guessing. Backfilling an already-complete tree is
    the case where a later generation *does* exist and this returns it -- `tools/backfill_digests.py`
    runs after every generation up to the present has already finished.

    **Cheap in the common case, and still linear-but-bounded even when it is not.** `later` (every
    number in `existing` greater than `generation`) is empty for the live-write case described above,
    so this function performs zero file reads before returning `None`. When it is not empty (a
    backfill, or a digest re-rendered for an old generation), this scans forward and returns on the
    first match -- and because the loop cycles a small, fixed set of purposes, the next same-lane
    generation is almost always within a handful of directories, not the whole remaining tree.
    """
    for candidate in existing:
        if candidate <= generation:
            continue
        result = _read_outcome(root / f"gen{candidate:04d}" / "OUTCOME.json")
        if result.outcome is None:
            continue
        if _previous_generation_number(result.outcome) == generation:
            return candidate
    return None


def _earlier_same_purpose_generation_exists(
    root: Path, existing: Sequence[int], generation: int, purpose: str
) -> bool:
    """`True` when some generation numbered below `generation` on disk already ran `purpose` --
    the signal :func:`write_digest` uses to tell a lane's genuine first generation apart from a
    generation that merely has no *recorded* predecessor because the loop restarted and its
    in-process `history_by_lane` (`app.evolution.loop._run`'s own per-lane state) does not survive
    that restart. A lane's true first generation has no earlier same-purpose directory at all, so this
    correctly returns `False` for it; a lane that has run before but lost track of its own history
    across a restart does have one, so this correctly returns `True` and :func:`_what_changed` can
    say so instead of letting "first measured generation in this lane" read as "this lane started
    here" when it did not.

    Scans backward from `generation - 1` and stops at the first same-purpose match -- one file read
    per generation checked, unavoidable since purpose is a property of `OUTCOME.json`'s own content,
    not of the generation number. Only called when `_previous_generation_number` has already returned
    `None` for `generation` (see :func:`write_digest`), which is the rare case (once per lane's true
    start, and once per restart) rather than the common per-generation path.
    """
    for candidate in reversed(existing):
        if candidate >= generation:
            continue
        result = _read_outcome(root / f"gen{candidate:04d}" / "OUTCOME.json")
        if result.outcome is not None and str(result.outcome.purpose) == purpose:
            return True
    return False


# ---------------------------------------------------------------------------
# PLAN.md reading -- the origin breakdown `OUTCOME.json` does not carry
# ---------------------------------------------------------------------------

_CANDIDATE_LINE_RE = re.compile(r"^- `[^`]+` \((?P<origin>[a-z]+), (?P<shape>[a-z]+), parents=")


def _origin_counts(plan_markdown: str) -> dict[str, int]:
    """`{origin: count}` from `PLAN.md`'s own `## Candidates` bullet lines
    (`app.evolution.loop._write_plan_file`'s exact format: `` - `{genome_id}` ({origin}, {shape},
    parents=...) -- {notes}``). `{}` when no candidate line matches -- an absent or reformatted
    `PLAN.md` degrades this one clause of "What ran", never the rest of the digest.
    """
    counts: dict[str, int] = {}
    for line in plan_markdown.splitlines():
        match = _CANDIDATE_LINE_RE.match(line)
        if match is None:
            continue
        origin = match.group("origin")
        counts[origin] = counts.get(origin, 0) + 1
    return counts


def _format_origin_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "origin breakdown not recorded"
    parts = [f"{n} {origin}" for origin, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Findings -> bullets, and which findings are "open questions"
# ---------------------------------------------------------------------------


def _kind_label(kind: str) -> str:
    return kind.replace("_", " ").capitalize()


def _is_open_question(finding: Finding) -> bool:
    """A fixed, mechanical rule for "this finding is not settled yet" -- never a judgement call made
    while rendering. Three cases, each read directly off a finding's own evidence rather than
    inferred from its prose:

    * `kind="failure"` -- a candidate that did not run to a measurable result is unresolved by
      construction; there is nothing to carry forward except the fact that it happened.
    * `kind="holdout"` with `evidence["contradicts"] is True` -- the winner's holdout median
      disagreed with its selection median (a sign flip, or a drop past the promotion margin); that
      disagreement is exactly the kind of thing the next generation should keep testing for.
    * `kind="gate"` (the goal-finding variant, `"goal"` in evidence) with
      `evidence["direction"] == "worsened from"` -- the stated goal's own tracked number moved the
      wrong way since the last generation in this lane.

    Every other finding (`winner`, `universe`, `parameter`, `regime`, an ordinary `gate` reading, or a
    goal finding that improved or sat within the noise floor) is settled: it reports what happened,
    not a question still open.
    """
    if finding.kind == "failure":
        return True
    if finding.kind == "holdout":
        return finding.evidence.get("contradicts") is True
    if finding.kind == "gate" and "goal" in finding.evidence:
        return finding.evidence.get("direction") == "worsened from"
    return False


def _winner(standings: Sequence[Standing]) -> Standing | None:
    """Rank-1 among eligible standings -- the same rule `app.evolution.feedback._winner` and
    `app.evolution.history._leader` both already apply, restated here rather than imported since both
    of those are private to packages this workstream does not own the write access to extend."""
    eligible = [s for s in standings if s.eligible]
    if not eligible:
        return None
    return min(eligible, key=lambda s: (s.rank, s.genome_id))


# ---------------------------------------------------------------------------
# render_digest -- pure, deterministic, no I/O
# ---------------------------------------------------------------------------


def render_digest(
    outcome: GenerationOutcome,
    *,
    previous_outcome: GenerationOutcome | None,
    previous_generation: int | None,
    previous_gap: int | None,
    previous_unreadable_reason: str | None,
    previous_lane_reset: bool = False,
    next_generation: int | None,
    plan_markdown: str | None,
    field_stats: FieldSnapshot,
    caveat: CaveatStats,
) -> str:
    """The Markdown body for one *readable* generation -- `outcome.status` may still be `"failed"` or
    `"cancelled"`, but `outcome` itself parsed. See :func:`write_digest` for the sibling case (the
    directory's `OUTCOME.json` could not be read at all) and for how every argument here is produced.

    **Pure and deterministic.** No argument here is read from disk by this function, no clock is
    read, nothing is random -- every sentence is a fixed transformation of the arguments, so calling
    this twice with identical arguments returns identical strings. This is the same contract
    `app.evolution.feedback.derive_findings` states for itself, one layer up: a finding a person
    trusts and a digest a person trusts are trusted for the same reason. `_humanise_figures` (applied
    to every finding sentence quoted below) does not break this: it is a fixed function of its input
    string, so it is exactly as deterministic as the rest of this function.

    Callers pass exactly one of, for the "what changed" section: `previous_outcome` set (a normal
    comparison), `previous_gap` set (`previous_generation` is known but a run of missing directories
    separates it from `outcome.generation`), `previous_unreadable_reason` set (`previous_generation`
    is known, no gap, but that generation's own `OUTCOME.json` could not be read), or `previous_generation`
    itself `None` (this lane's first measured generation *on record* -- `previous_lane_reset` then
    says whether that is because the lane genuinely started here, `False`, or because an earlier
    same-purpose generation exists on disk despite there being no recorded link to it, `True` --
    see :func:`_earlier_same_purpose_generation_exists`). :func:`write_digest` is the one caller and
    enforces this; `render_digest` itself does not validate it, trusting its own module's caller the
    same way `app.evolution.feedback.derive_findings` trusts `window_medians` to already be
    `field_window_medians`' own output.

    `next_generation` is this lane's actual next generation, `None` when it has not run yet (or has
    not been backfilled) -- see :func:`_next_generation_for`. Never `outcome.generation + 1`: that
    directory is usually a different purpose's lane entirely.
    """
    purpose_label = str(outcome.purpose).capitalize()
    timestamp = outcome.finished_at.strftime("%Y-%m-%d %H:%MZ")

    lines: list[str] = [
        f"## Generation {outcome.generation} · {purpose_label} · {outcome.status} · {timestamp}",
        "",
        f"**What ran.** {_what_ran(outcome, plan_markdown)}",
        "",
        f"**What changed since generation "
        f"{previous_generation if previous_generation is not None else '(none)'}.** "
        f"{_what_changed(outcome, previous_outcome=previous_outcome, previous_generation=previous_generation, previous_gap=previous_gap, previous_unreadable_reason=previous_unreadable_reason, previous_lane_reset=previous_lane_reset, field_stats=field_stats)}",
        "",
        "**What it found.**",
    ]
    lines.extend(_what_it_found(outcome))
    lines.append("")
    lines.append(f"**What it promoted.** {_what_it_promoted(outcome)}")
    lines.append("")
    next_heading = (
        f"What generation {next_generation} will try"
        if next_generation is not None
        else "What the next generation in this lane will try"
    )
    lines.append(f"**{next_heading}.** {_what_next(outcome)}")
    lines.append("")
    lines.append(f"**Standing caveat.** {_standing_caveat_sentence(caveat)}")
    lines.append("")
    return "\n".join(lines)


def _standing_caveat_sentence(caveat: CaveatStats) -> str:
    """The one paragraph every digest ends with, in either shape this module ever renders it in --
    factored out so `render_digest` and `_render_unreadable_digest` cannot drift into two different
    wordings of the same fact."""
    pct = _format_caveat_pct(caveat)
    if pct == _EM_DASH:
        return (
            "No ledger rows carry a measured holdout figure yet, so the field-wide "
            "holdout-positive fraction cannot be computed; this generation's holdout figures are "
            "not, on their own, evidence of an edge regardless."
        )
    return (
        f"{pct}% of all {caveat.candidates_ever_run} candidates ever run post a positive holdout "
        f"median (of the {caveat.total} with a measured holdout figure); this generation's holdout "
        "figures are not, on their own, evidence of an edge."
    )


def _what_ran(outcome: GenerationOutcome, plan_markdown: str | None) -> str:
    candidates = len(outcome.genome_ids)
    windows = ", ".join(outcome.windows) if outcome.windows else "no selection windows"
    holdout = ", ".join(outcome.holdout_windows) if outcome.holdout_windows else "none"
    if plan_markdown is not None:
        origin_clause = f" ({_format_origin_counts(_origin_counts(plan_markdown))})"
    else:
        origin_clause = " (`PLAN.md` is absent; origin breakdown not available)"
    sentence = f"{candidates} card(s){origin_clause} over {windows}, with {holdout} held out."
    if outcome.status == "failed":
        sentence += f" This generation failed: {outcome.error or 'no error was recorded'}."
    elif outcome.status == "cancelled":
        sentence += f" This generation was cancelled before scoring completed: {outcome.error or 'no error was recorded'}."
    return sentence


def _what_changed(
    outcome: GenerationOutcome,
    *,
    previous_outcome: GenerationOutcome | None,
    previous_generation: int | None,
    previous_gap: int | None,
    previous_unreadable_reason: str | None,
    previous_lane_reset: bool,
    field_stats: FieldSnapshot,
) -> str:
    if previous_generation is None:
        if previous_lane_reset:
            return (
                "This generation has no recorded previous generation in this lane, but an earlier "
                f"{outcome.purpose!s} generation exists on disk -- the loop's in-process "
                "per-lane history does not survive a restart (`app.evolution.loop._run`'s own "
                "`history_by_lane`), so this reads as this lane's first measured generation without "
                "actually being the purpose's first ever run. There is nothing to compare against "
                "regardless, since the link to whatever came before was lost at the restart."
            )
        return (
            "This is this lane's first measured generation on record; there is no earlier "
            "same-purpose generation to compare against."
        )
    if previous_gap is not None and previous_gap > 0:
        sentence = (
            f"Generation {previous_generation} is the nearest earlier generation recorded in this "
            f"lane, but {previous_gap} generation(s) between them have no directory on disk at all, "
            "so there is nothing to difference against."
        )
        note = _gap_note(previous_generation, previous_gap)
        if note is not None:
            sentence += f" {note}"
        return sentence
    if previous_unreadable_reason is not None:
        return (
            f"Generation {previous_generation} is this lane's previous generation, but its own "
            f"{previous_unreadable_reason}, so there is nothing to compare against."
        )
    if previous_outcome is None:
        # previous_generation was known but write_digest could not locate its directory at all
        # (removed from disk, or the number it named never existed) -- reported the same way as an
        # unreadable file, since a reader cannot tell "empty" from "gone" apart from this sentence.
        return (
            f"Generation {previous_generation} is this lane's previous generation, but no directory "
            "for it exists on disk, so there is nothing to compare against."
        )

    previous_field = _field_snapshot(previous_outcome.standings)
    if field_stats.median_excess is not None and previous_field.median_excess is not None:
        delta_pp = (field_stats.median_excess - previous_field.median_excess) * 100
        median_clause = (
            f"Field median excess {_format_pct(previous_field.median_excess)} -> "
            f"{_format_pct(field_stats.median_excess)} ({_format_signed_pp(delta_pp)})."
        )
    else:
        median_clause = (
            f"Field median excess: {_format_pct(previous_field.median_excess)} -> "
            f"{_format_pct(field_stats.median_excess)} (not fully measured on both sides)."
        )

    shared = set(previous_outcome.genome_ids) & set(outcome.genome_ids)
    carry_clause = (
        f"{len(shared)} of the previous generation's {len(previous_outcome.genome_ids)} "
        "candidate(s) carried forward into this field."
    )

    old_windows = set(previous_outcome.windows)
    new_windows = set(outcome.windows)
    added = sorted(new_windows - old_windows)
    removed = sorted(old_windows - new_windows)
    if not added and not removed:
        window_clause = "The selection window set is unchanged."
    elif added and removed:
        window_clause = f"The window set rotated {', '.join(removed)} out for {', '.join(added)}."
    elif added:
        window_clause = f"The window set added {', '.join(added)}."
    else:
        window_clause = f"The window set dropped {', '.join(removed)}."

    return f"{median_clause} {carry_clause} {window_clause}"


def _what_it_found(outcome: GenerationOutcome) -> list[str]:
    if not outcome.findings:
        if outcome.status != "succeeded":
            reason = f"this generation {outcome.status} before any candidate could be scored"
        else:
            reason = "no candidate produced a leaderboard row"
        return [f"No findings were derived for this generation ({reason})."]
    return [f"- **{_kind_label(f.kind)}.** {_humanise_figures(f.summary)}" for f in outcome.findings]


def _what_it_promoted(outcome: GenerationOutcome) -> str:
    if not outcome.promoted:
        return "No candidate cleared the promotion gate this generation."
    return (
        f"{len(outcome.promoted)} candidate(s) cleared the promotion gate this generation: "
        f"{', '.join(outcome.promoted)}."
    )


def _what_next(outcome: GenerationOutcome) -> str:
    winner = _winner(outcome.standings)
    open_questions = [_humanise_figures(f.summary) for f in outcome.findings if _is_open_question(f)]
    open_clause = (
        "Open questions carried forward: " + " ".join(open_questions)
        if open_questions
        else "No open questions were carried forward from this generation."
    )
    if winner is None:
        return (
            "No eligible candidate this generation to seed the next generation in this lane from. "
            + open_clause
        )
    gate_summary = next(
        (
            f.summary
            for f in outcome.findings
            if f.kind == "gate" and "goal" not in f.evidence
        ),
        None,
    )
    lead_clause = (
        f"{winner.display_name} ({winner.genome_id}) led this field with median excess "
        f"{_format_pct(winner.median_excess)} and is available to breed forward."
    )
    if gate_summary is not None:
        lead_clause += f" {_humanise_figures(gate_summary)}"
    return f"{lead_clause} {open_clause}"


# ---------------------------------------------------------------------------
# The unreadable case -- no GenerationOutcome exists to build a normal digest from
# ---------------------------------------------------------------------------


def _render_unreadable_digest(
    generation: int,
    *,
    reason: str,
    plan_markdown: str | None,
    nearest_previous: int | None,
    gap: int | None,
    next_generation: int | None,
    caveat: CaveatStats,
) -> str:
    purpose_label = "(purpose unknown)"
    if plan_markdown is not None:
        match = re.search(r"^\*\*Purpose:\*\*\s*(\S+)", plan_markdown, re.MULTILINE)
        if match is not None:
            purpose_label = match.group(1).capitalize()

    lines: list[str] = [
        f"## Generation {generation} · {purpose_label} · unreadable · (no timestamp available)",
        "",
    ]

    what_ran = f"This generation's {reason}."
    if plan_markdown is not None:
        candidate_count = sum(
            1 for line in plan_markdown.splitlines() if _CANDIDATE_LINE_RE.match(line)
        )
        what_ran += (
            f" `PLAN.md` records {candidate_count} candidate(s) were planned "
            f"({_format_origin_counts(_origin_counts(plan_markdown))})."
        )
    else:
        what_ran += " No `PLAN.md` exists for this generation either, so no record of what it ran survives on disk."

    if nearest_previous is None:
        what_ran += " No earlier generation directory exists on disk."
    elif gap:
        note = _gap_note(nearest_previous, gap)
        what_ran += (
            f" The nearest earlier generation directory on disk is gen{nearest_previous:04d}, "
            f"{gap} generation(s) before this one with no directory on disk at all."
        )
        if note is not None:
            what_ran += f" {note}"
    else:
        what_ran += f" The previous generation directory on disk is gen{nearest_previous:04d}."

    lines.append(f"**What ran.** {what_ran}")
    lines.append("")
    lines.append(
        "**What changed since generation "
        f"{nearest_previous if nearest_previous is not None else '(none)'}.** "
        "Not applicable: this generation's own outcome could not be read, so there is no measured "
        "result for it to be differenced against anything."
    )
    lines.append("")
    lines.append("**What it found.**")
    lines.append("No findings: this generation's outcome could not be read.")
    lines.append("")
    lines.append("**What it promoted.** Nothing: this generation's outcome could not be read.")
    lines.append("")
    next_heading = (
        f"What generation {next_generation} will try"
        if next_generation is not None
        else "What the next generation in this lane will try"
    )
    lines.append(
        f"**{next_heading}.** Unknown: with no readable outcome for generation {generation}, "
        "there is nothing here to seed the next generation's plan from."
    )
    lines.append("")
    lines.append(f"**Standing caveat.** {_standing_caveat_sentence(caveat)}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# write_digest -- the one function that touches disk on the write side
# ---------------------------------------------------------------------------


def write_digest(
    generation: int,
    *,
    settings: Settings,
    caveat: CaveatStats | None = None,
    dry_run: bool = False,
) -> tuple[str, bool]:
    """Render `gen{N:04d}/DIGEST.md` for one generation and, unless `dry_run`, write it.

    Returns `(markdown, changed)`. `changed` is `True` when the rendered Markdown differs from what
    is currently on disk at `digest_path(settings, generation)` (or when nothing is on disk yet) --
    the idempotency signal `tools/backfill_digests.py` reports against, computed identically whether
    or not this call actually writes. A second call over unchanged inputs (unchanged `OUTCOME.json`,
    `PLAN.md`, and ledger) therefore reports `changed=False` and, under `--apply`, writes nothing --
    `render_digest`'s own purity is what makes that comparison meaningful rather than a coincidence.

    `caveat`, when omitted, is read fresh from `data/loop/ledger.jsonl` for this one call
    (:func:`caveat_stats`) -- fine for a single generation, wasteful for a 233-generation backfill,
    which is why `tools/backfill_digests.py` computes it once and passes it to every call instead.
    """
    root = loop_root(settings)
    gen_dir = root / f"gen{generation:04d}"
    resolved_caveat = caveat if caveat is not None else caveat_stats(settings)

    outcome_read = _read_outcome(gen_dir / "OUTCOME.json")
    plan_markdown = _read_text_or_none(gen_dir / "PLAN.md")
    existing = existing_generation_numbers(root)

    next_generation = _next_generation_for(root, existing, generation)

    if outcome_read.outcome is None:
        nearest_previous = _nearest_previous_directory(existing, generation)
        gap = (
            _missing_between(existing, nearest_previous, generation)
            if nearest_previous is not None
            else None
        )
        markdown = _render_unreadable_digest(
            generation,
            reason=outcome_read.reason or "`OUTCOME.json` could not be read",
            plan_markdown=plan_markdown,
            nearest_previous=nearest_previous,
            gap=gap,
            next_generation=next_generation,
            caveat=resolved_caveat,
        )
    else:
        outcome = outcome_read.outcome
        previous_generation = _previous_generation_number(outcome)
        previous_outcome: GenerationOutcome | None = None
        previous_gap: int | None = None
        previous_unreadable_reason: str | None = None
        previous_lane_reset = False

        if previous_generation is not None:
            gap = _missing_between(existing, previous_generation, generation)
            if gap > 0:
                previous_gap = gap
            else:
                prev_read = _read_outcome(root / f"gen{previous_generation:04d}" / "OUTCOME.json")
                previous_outcome = prev_read.outcome
                previous_unreadable_reason = prev_read.reason
        else:
            previous_lane_reset = _earlier_same_purpose_generation_exists(
                root, existing, generation, str(outcome.purpose)
            )

        field_stats = _field_snapshot(outcome.standings)
        markdown = render_digest(
            outcome,
            previous_outcome=previous_outcome,
            previous_generation=previous_generation,
            previous_gap=previous_gap,
            previous_unreadable_reason=previous_unreadable_reason,
            previous_lane_reset=previous_lane_reset,
            next_generation=next_generation,
            plan_markdown=plan_markdown,
            field_stats=field_stats,
            caveat=resolved_caveat,
        )

    path = gen_dir / "DIGEST.md"
    existing_text = _read_text_or_none(path)
    changed = existing_text != markdown
    if not dry_run and changed:
        gen_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
    return markdown, changed


# ---------------------------------------------------------------------------
# rebuild_journal -- assembled from DIGEST.md files already on disk
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JournalEntry:
    generation: int
    markdown: str


def _read_digest(root: Path, generation: int) -> str | None:
    return _read_text_or_none(root / f"gen{generation:04d}" / "DIGEST.md")


def rebuild_journal(*, settings: Settings) -> Path:
    """Rewrite `data/loop/JOURNAL.md` from scratch, oldest generation first, out of every
    `gen{N:04d}/DIGEST.md` already on disk -- this function reads digests, it does not write them
    (call :func:`write_digest` first, per generation, for that; `tools/backfill_digests.py` does both
    in the right order).

    **Idempotent**: run twice with nothing changed on disk, the header's counts and every digest's
    text are identical both times, so the file's bytes are identical too. Rewriting from scratch
    rather than appending is deliberate -- an append-only journal cannot self-correct a digest that
    was re-rendered after a bug fix, and this journal has no other reason to exist than to be an
    accurate, current concatenation of what is on disk right now.
    """
    root = loop_root(settings)
    existing = existing_generation_numbers(root)

    readable = 0
    unreadable_generations: list[tuple[int, str]] = []
    status_counts: dict[str, int] = {}
    for generation in existing:
        result = _read_outcome(root / f"gen{generation:04d}" / "OUTCOME.json")
        if result.outcome is None:
            unreadable_generations.append((generation, result.reason or "unreadable"))
            continue
        readable += 1
        status_counts[result.outcome.status] = status_counts.get(result.outcome.status, 0) + 1

    gaps: list[tuple[int, int, int]] = []  # (previous, next, missing_count)
    for prev_gen, next_gen in itertools.pairwise(existing):
        if next_gen - prev_gen > 1:
            gaps.append((prev_gen, next_gen, next_gen - prev_gen - 1))

    header: list[str] = [
        "# Evolution loop journal",
        "",
        "Rebuilt from every `gen{N:04d}/DIGEST.md` on disk, oldest generation first. This file is "
        "regenerated wholesale by `app.evolution.digest.rebuild_journal` -- do not hand-edit it, "
        "edits will be overwritten on the next rebuild.",
        "",
        f"- Generation directories on disk: {len(existing)}",
        f"- Readable outcomes: {readable} "
        f"({', '.join(f'{count} {status}' for status, count in sorted(status_counts.items())) or 'none'})",
        f"- Unreadable `OUTCOME.json`: {len(unreadable_generations)}"
        + (
            " (" + ", ".join(f"gen{g:04d}: {reason}" for g, reason in unreadable_generations) + ")"
            if unreadable_generations
            else ""
        ),
    ]
    if gaps:
        for prev_gen, next_gen, missing in gaps:
            note = _gap_note(prev_gen, missing)
            gap_line = (
                f"- Gap: gen{prev_gen:04d} -> gen{next_gen:04d}, {missing} generation(s) with no "
                "directory on disk at all."
            )
            if note is not None:
                gap_line += f" {note}"
            header.append(gap_line)
    else:
        header.append("- No gap in generation numbering.")
    header.append("")
    header.append("---")
    header.append("")

    body_parts: list[str] = []
    for generation in existing:
        digest = _read_digest(root, generation)
        if digest is None:
            digest = (
                f"## Generation {generation}\n\nNo `DIGEST.md` exists for this generation -- run "
                "`tools/backfill_digests.py --apply` to write it.\n"
            )
        body_parts.append(digest.rstrip("\n"))

    text = "\n".join(header) + "\n" + "\n\n---\n\n".join(body_parts) + "\n"
    path = journal_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def read_journal_entries(
    settings: Settings, *, limit: int, offset: int
) -> tuple[list[JournalEntry], int]:
    """`(page, total)` of every generation with a `DIGEST.md` on disk, **newest first** -- the shape
    `GET /api/competition/loop/journal` returns. Newest-first here, deliberately the opposite of
    `JOURNAL.md`'s own oldest-first ordering on disk: `JOURNAL.md` is meant to be read top-to-bottom
    as a history, while this is a paginated API a caller polls for "what's new", the same convention
    `app.evolution.history.list_generations` already uses for `GET /generations`.

    Reads `gen{N:04d}/DIGEST.md` files directly rather than parsing `JOURNAL.md` back apart --
    parsing Markdown headers to recover entry boundaries would be fragile and `JOURNAL.md` is not the
    source of truth for any one digest's text, it is a concatenation of the same files this function
    reads. `[]`/`total=0` for an absent or empty `loop_root` -- never a 404, matching
    `app.evolution.history.list_generations`'s own "no loop has run yet" rule.
    """
    root = loop_root(settings)
    existing = existing_generation_numbers(root)
    with_digest = [g for g in existing if (root / f"gen{g:04d}" / "DIGEST.md").is_file()]
    with_digest.sort(reverse=True)

    total = len(with_digest)
    limit = max(1, limit)
    offset = max(0, offset)
    page_numbers = with_digest[offset : offset + limit]

    entries: list[JournalEntry] = []
    for generation in page_numbers:
        text = _read_digest(root, generation)
        if text is not None:
            entries.append(JournalEntry(generation=generation, markdown=text))
    return entries, total

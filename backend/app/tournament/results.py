"""Online reader for completed strategy-tournament rounds and the strategy library.

This module answers three questions over data already written to disk under ``data/rounds/`` (round
records) and inside the ``app.paper`` package (the strategy library): which cards exist
(:func:`load_library`), which rounds have been run and
what windows each covers (:func:`list_rounds`), and how every card that ran in a round actually did,
both as a leaderboard (:func:`build_leaderboard`) and as a per-trade drill-down for one agent
(:func:`build_agent_detail`).

**It is an online reader, not a re-derivation.** The metrics computed here mirror two offline tools
that already exist and are the source of truth for the arithmetic:

* ``strategy-program/tools/score.py`` -- ``corrected_return``, ``capital_exposure`` (with its
  trade-log reconstruction fallback), ``excess``, ``adjusted_excess`` and the eligibility gate
  (``MIN_ELIGIBLE_MAIN_WINDOWS``) are all the same computations that module makes, kept in sync by
  inspection rather than by import: ``strategy-program/tools/`` is not inside a legal Python package
  (the hyphen in the directory name), so it can only be run by file path, never imported from
  ``backend/app``. The same is true of every constant this module duplicates from it
  (``MAIN_WINDOWS``, ``MIN_ELIGIBLE_MAIN_WINDOWS``, ``MIN_EXPOSURE_FOR_RATIO``) -- see ``score.py``'s
  own module docstring for why it duplicates ``strategy-program/tools/windows.py`` for the identical
  reason.
* ``strategy-program/tools/attribution.py`` -- the per-trade ``contribution = pnl / starting_equity``
  decomposition, the unrealised-mark split on ``exit_reason == "open_at_end"``, and the top-N-winners
  concentration figures (``top3_share_of_gross_wins`` / ``return_without_top3_winners``) reproduce
  ``TradeContribution`` / ``WindowAttribution`` from that module.

**One deliberate divergence from ``score.py``: this API ranks on plain ``excess``, not
``adjusted_excess``.** The HTTP contract (fixed by the API's consumer) calls for
``median_excess``/``worst_excess``/``hit_rate`` computed from ``excess = total_return -
benchmark_return`` -- not the exposure-corrected ``adjusted_excess`` that ``score.py`` ranks its own
primary table on. Both figures are computed and returned per window (see ``WindowMetrics``) so a
reader can see the correction; only the row-level aggregates use the simpler, uncorrected figure, per
the contract this module implements. ``rank_by="excess-per-exposure"`` follows the same substitution:
it divides ``excess`` by ``capital_exposure`` (not ``adjusted_excess`` by ``capital_exposure``, as
``score.py``'s ``excess_per_exposure`` does), floored at the same ``MIN_EXPOSURE_FOR_RATIO`` for the
same reason (see that constant's docstring). ``score.py``'s fifth ranking choice, ``"borda"``, has no
equivalent here -- the contract enumerates only four (see :data:`RANK_BY_CHOICES`).

**A real-data surprise worth recording.** The run-file naming scheme documented as
``results/<window>/runs/<round-tag>-<agent_id>.json`` suggests the ``<round-tag>`` prefix identifies
which competition round (``r1-2026-08`` vs ``r2-2026-08``) a file belongs to. On disk it does not:
every run file under *both* round directories is prefixed ``r1-`` (it reflects which cards
subdirectory the tournament runner drew from when the file was produced, an orthogonal and
now-vestigial distinction -- see ``backend/app/tournament/__main__.py``'s ``_cards``). Loading here
therefore never filters by that prefix; every ``*.json`` under a round's own
``results/<window>/runs/`` is that round's data, keyed by the card's *embedded* ``agent_id``
(``result.card.agent_id``), never by parsing the filename -- the same rule ``score.py.load_results``
already follows for exactly this reason.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import statistics
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from app.config import get_settings
from app.tournament.allocation import AllocationResult
from app.tournament.ladder import LadderResult
from app.tournament.models import AgentResult, RealisedTrade, StrategyCard
from app.tournament.purposes import Purpose

__all__ = [
    "MAIN_WINDOWS",
    "MIN_ELIGIBLE_MAIN_WINDOWS",
    "MIN_EXPOSURE_FOR_RATIO",
    "PROVENANCE_WINDOW",
    "RANK_BY_CHOICES",
    "TIERS",
    "AgentDetailData",
    "AgentNotFoundError",
    "ExposureBasisError",
    "LeaderboardCellData",
    "LeaderboardData",
    "LeaderboardRowData",
    "RoundNotFoundError",
    "RoundSummaryData",
    "ScoredRun",
    "TradeContribution",
    "UnrecognisedCardShapeError",
    "WindowFacts",
    "WindowMetrics",
    "build_agent_detail",
    "build_leaderboard",
    "list_rounds",
    "load_library",
    "load_round_scored_runs",
    "load_scored_run_file",
    "parse_scored_run",
    "round_sequence",
]

#: Root of the round-record tree. Rounds are the research record this program produces --
#: `app.tournament.jobs` writes them, this module only reads them -- and now live under the data
#: directory (`app.config.Settings.rounds_dir`, default `data/rounds/`, overridable via
#: `INVDASH_ROUNDS_DIR`) rather than inside `strategy-program/`, since they are generated output that
#: grows, not fixed configuration that ships. A plain module-level default plus an explicit override
#: parameter on every loader function is still enough, and the override is what lets tests point at a
#: `tmp_path` fixture instead.
ROUNDS_ROOT: Path = get_settings().rounds_dir

#: The strategy card library, however, ships *inside* `app.paper` (`backend/app/paper/library/`) --
#: it is application data the served API reads, not a research artifact -- so its default now comes
#: from `app.config.get_settings().library_dir` (overridable via `INVDASH_LIBRARY_DIR`) rather than
#: from anywhere under `strategy-program/`. The explicit `library_root` override parameter on
#: `load_library` below is unchanged; only where the *default* points has moved.
LIBRARY_ROOT: Path = get_settings().library_dir

#: JSON files that legitimately sit in a cards directory without being a card. Duplicated from
#: `backend/app/tournament/__main__.py`'s `_NOT_CARDS` (that module is outside this program's scope
#: fence) rather than imported, for the same "a card directory's sidecar is not a card" reason -- see
#: `_NOT_CARDS`'s docstring there. `StrategyCard` forbids extra fields, so loading one as a card would
#: raise a wall of validation errors that bury the actual cause and would take a whole tier listing
#: down with it.
_NOT_CARDS = frozenset({"provenance.json"})

#: Tiers always returned by `/api/competition/library`, in this fixed order, even when a tier is
#: empty -- e.g. `variants` has never held a card in this program's history, but the frontend still
#: needs a stable four-tuple to render four columns.
TIERS: tuple[tuple[str, str], ...] = (
    ("base", "Base"),
    ("variants", "Variants"),
    ("candidates", "Candidates"),
    ("retired", "Retired"),
)

#: The eight ranked round-2 regimes, duplicated from `strategy-program/tools/tools/windows.py`'s
#: `MAIN_WINDOWS` (via `score.py`'s own duplicate, `MAIN_WINDOW_TAGS`) rather than imported -- see this
#: module's docstring. Order matches `strategy-program/WINDOWS.md`'s presentation order, cheapest-first.
MAIN_WINDOWS: tuple[str, ...] = (
    "q4-2018",
    "covid",
    "bear-2022",
    "chop-2015",
    "chop-2011",
    "bull-2024",
    "recent",
    "gfc",
)

#: The 13F-provenance-constrained special window. Always reported (its `per_window` entry is never
#: dropped), never counted in a ranking aggregate -- see the module docstring and
#: `strategy-program/tools/windows.py`'s own docstring on why a basket only knowable from a later
#: filing cannot be scored against windows that predate it.
PROVENANCE_WINDOW = "13f-legal"

#: Below this many actually-run *main* windows (i.e. excluding :data:`PROVENANCE_WINDOW`), a card's
#: aggregate is reported but not ranked -- duplicated from
#: `strategy-program/tools/windows.py`'s `MIN_ELIGIBLE_MAIN_WINDOWS` (round 2's gate; round 1's was 3
#: of 5 against a five-window matrix) for the same "can't import across the hyphenated directory"
#: reason `score.py` already documents.
MIN_ELIGIBLE_MAIN_WINDOWS = 5

#: Floor below which `excess-per-exposure` refuses to divide -- duplicated from `score.py`'s
#: `MIN_EXPOSURE_FOR_RATIO` (see that constant's docstring for why a near-zero denominator is refused
#: rather than divided by). Applied here to plain `excess`, not `adjusted_excess` -- see the module
#: docstring's divergence note.
MIN_EXPOSURE_FOR_RATIO = Decimal("0.05")

#: `rank_by` choices for `/api/competition/rounds/{round_id}/leaderboard`. A subset of `score.py`'s
#: `RANK_BY_CHOICES` -- the API contract this module implements enumerates exactly these four and has
#: no equivalent of `score.py`'s fifth choice, `"borda"` (the dominance/Pareto view), so it is
#: intentionally not offered here. Spelling matches `score.py`'s exactly (hyphenated, not
#: underscored) since that is what a caller who has read `score.py` will expect.
RANK_BY_CHOICES: tuple[str, ...] = ("median", "worst", "hit-rate", "excess-per-exposure")

#: Accepted `purpose` values, read from the enum rather than restated, so this module cannot drift
#: out of agreement with `app.tournament.purposes` about how many purposes exist.
_PURPOSE_VALUES: frozenset[str] = frozenset(p.value for p in Purpose)

#: What each purpose's leaderboard is actually ranked on.
#:
#: What each purpose's leaderboard reports as its ranking quantity.
#:
#: **All three are `adjusted_excess` since 2026-08-29, and the change is forced rather than chosen.**
#: `savings` and `roth` previously read `"irr+cagr"`, because
#: `strategy-program/THREE-PURPOSES-PLAN.md` section 7 requires both a money-weighted IRR and a
#: time-weighted CAGR to be reported for a contribution-funded book -- "because quoting only the
#: flattering one is the easiest mistake available here" -- and section 2 measures the gap between
#: them at 8.4 points on one strategy in one window (QLD 2006-2011: IRR 10.70% against CAGR 2.29%).
#:
#: On 2026-08-29 the owner removed every ongoing contribution from all three purposes, so all three
#: are now single lump sums (`app.tournament.purposes.PURPOSE_SPECS`). **For a single inflow and a
#: single terminal value, money-weighted IRR and time-weighted CAGR are the same number by
#: construction** -- the 8.4-point gap section 2 measures is produced entirely by *when the money
#: arrived*, and a lump sum has no arrival schedule to produce it. There is no longer any divergence
#: for the pair to report, so continuing to label these books `"irr+cagr"` would promise a reader two
#: distinct quantities that are now arithmetically identical.
#:
#: **This was a label, not a computation, and no behaviour is being removed.** Nothing in this module
#: ever branched on the string `"irr+cagr"` to compute an IRR: it is substituted into
#: `unscored_reason` text (below) and returned as `LeaderboardData.scoring_basis` (see
#: `app.api.competition`). The contribution harness that does compute IRR lives in
#: `strategy-program/tools/contributions.py` and was never wired to this path.
#:
#: **What this does not settle: `savings` needs a drawdown-first gate that a single return column
#: cannot express.** Its mandate since 2026-08-29 is explicitly return-subordinate-to-safety, and
#: ranking it on `adjusted_excess` alone would seat the highest-returning candidate regardless of
#: drawdown. See `strategy-program/ACCOUNT-DEPLOYMENT-PLAN.md` section 7 item 1; that gate is not
#: built here.
SCORING_BASIS: dict[str, str] = {
    Purpose.TRADING.value: "adjusted_excess",
    Purpose.SAVINGS.value: "adjusted_excess",
    Purpose.ROTH.value: "adjusted_excess",
}


class RoundNotFoundError(Exception):
    """No `results/` directory exists under `ROUNDS_ROOT / round_id`."""

    def __init__(self, round_id: str) -> None:
        self.round_id = round_id
        super().__init__(f"no such round: {round_id!r}")


class AgentNotFoundError(Exception):
    """`agent_id` has no run file in any window of `round_id`."""

    def __init__(self, round_id: str, agent_id: str) -> None:
        self.round_id = round_id
        self.agent_id = agent_id
        super().__init__(f"agent {agent_id!r} did not run in round {round_id!r}")


class AgentShapeUnsupportedError(Exception):
    """`agent_id` ran in `round_id`, but its card is a shape the agent-detail view cannot render.

    **Not a 404, and the difference is the whole point.** "This card did not run" and "this card ran
    and I cannot show you it" are different facts about the round, and reporting the second as the
    first would quietly deny that an allocation or ladder candidate was ever measured -- in a round
    whose entire purpose was to measure them for the first time.

    `build_agent_detail` reads a run file as an `AgentResult`, whose `card` is a `StrategyCard`;
    allocation and ladder run files carry an `AllocationCard`/`LadderCard` and validate against
    neither. `load_round_scored_runs` is the loader that reads all three, which is why the
    *leaderboard* ranks round 15 perfectly well while its Agent tab could not open a single card.
    """

    def __init__(self, round_id: str, agent_id: str, shape: CardShape) -> None:
        self.round_id = round_id
        self.agent_id = agent_id
        self.shape = shape
        super().__init__(
            f"agent {agent_id!r} in round {round_id!r} is a {shape!r} card; the per-agent trade view "
            "reads stock-picking cards only, because an allocation or ladder card holds sleeve "
            "weights and rebalances rather than the entry/exit trades this view is built to show"
        )


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------


def load_library(library_root: Path | None = None) -> dict[str, list[StrategyCard]]:
    """Every `StrategyCard` under each of :data:`TIERS`' directories, keyed by tier name.

    Every tier key is always present (possibly `[]`) so a caller does not need to guess whether an
    empty tier means "no cards" or "directory does not exist yet" -- both render the same empty list.
    Cards directories are globbed fresh on every call, never cached and never assuming a fixed file
    list: the library is edited concurrently by other work in this program (see this module's brief),
    so a hardcoded manifest would silently miss or misplace a card moved between tiers mid-session.
    """
    root = library_root if library_root is not None else LIBRARY_ROOT
    out: dict[str, list[StrategyCard]] = {}
    for tier, _label in TIERS:
        tier_dir = root / tier
        cards: list[StrategyCard] = []
        if tier_dir.is_dir():
            for path in sorted(tier_dir.glob("*.json")):
                if path.name in _NOT_CARDS:
                    continue
                cards.append(StrategyCard.model_validate_json(path.read_text(encoding="utf-8")))
        out[tier] = cards
    return out


# ---------------------------------------------------------------------------
# Rounds
# ---------------------------------------------------------------------------


#: Matches the leading `r<N>` ordinal a round id is expected to start with (`"r11-2026-08"` ->
#: `"11"`). Used by :func:`round_sequence`, not to validate a round id -- see that function.
_ROUND_SEQUENCE_RE = re.compile(r"^r(\d+)")

#: Marks the live out-of-sample matrix's first sub-window in a round's results tree. This is `list_
#: rounds`'s own copy of `app.api.competition_selection._LIVE_MATRIX_MARKER` -- deliberately not
#: imported (that name is private to its module) -- and the two must be kept in step: both express
#: the same fact, that a round with no `results/live-1` directory has nothing to rank and no
#: selection to report.
_LIVE_MATRIX_MARKER = "live-1"


def round_sequence(round_id: str) -> int:
    """The integer ordinal embedded in a round id (`"r11-2026-08"` -> `11`), or `-1` for anything
    that does not start with `r<digits>`.

    Exists because sorting round ids as plain strings is a live defect: as strings, `"r9-2026-08" >
    "r13-2026-08"`, so a lexicographic `sorted(..., reverse=True)` presented round 9 as the newest
    round and buried rounds 10-13 in the middle of the list -- this function is what `list_round_ids`
    now sorts by instead. A directory name that does not match `r<digits>...` returns the sentinel
    `-1` rather than raising, so a stray directory under the rounds root cannot 500 the endpoint; it
    simply sorts last.
    """
    match = _ROUND_SEQUENCE_RE.match(round_id)
    if match is None:
        return -1
    return int(match.group(1))


@dataclass(frozen=True, slots=True)
class RoundSummaryData:
    """One row of `/api/competition/rounds`."""

    round_id: str
    label: str
    windows: tuple[str, ...]
    agents: int
    has_report: bool
    has_brief: bool
    has_results: bool
    has_selection: bool
    sequence: int


def _discover_windows(results_dir: Path) -> list[str]:
    """Every window this round has a `runs/` folder for, main windows first in their canonical
    order (see :data:`MAIN_WINDOWS`), then :data:`PROVENANCE_WINDOW` if present, then anything else
    alphabetically -- mirrors `score.py`'s `_discover_window_tags` ordering rationale: a reader
    following `strategy-program/WINDOWS.md` sees the same left-to-right order here.

    Scanned with `os.scandir` rather than `Path.iterdir`: `DirEntry.is_dir()` is answered by the
    directory entry already in hand, so the only stat left per candidate is the `runs/` probe -- on
    the 14 rounds on disk that is ~70 stats per call instead of the ~240 the pathlib form cost, which
    `/rounds` pays once per round on every request.
    """
    try:
        entries = list(os.scandir(results_dir))
    except OSError:
        # A missing or unreadable `results/` is "no windows", exactly as the `Path.is_dir()` guard
        # this replaced already reported it: a round with no results yet is a normal state.
        return []
    found = {
        e.name for e in entries if e.is_dir() and os.path.isdir(os.path.join(e.path, "runs"))
    }
    ordered = [tag for tag in MAIN_WINDOWS if tag in found]
    if PROVENANCE_WINDOW in found:
        ordered.append(PROVENANCE_WINDOW)
    ordered += sorted(found - set(MAIN_WINDOWS) - {PROVENANCE_WINDOW})
    return ordered


def _round_label(round_id: str, rounds_root: Path | None = None) -> str:
    """Prefers the round's hand-authored ``NARRATIVE.json`` title (e.g. ``"Round 14 - naming the
    chooser"``) when one exists and parses. Every real title already opens with ``"Round <N>"`` (see
    `app.tournament.narrative.RoundNarrative.title`'s docstring example, and every title actually on
    disk under `data/rounds/*/NARRATIVE.json` at the time of writing) -- the ordinal is not
    re-prefixed here, since the authored title already identifies the round and re-prefixing would
    just duplicate the number.

    Falls back to the old ``"r2 — Aug 2026"`` date-derived label -- computed below exactly as
    before -- in the two cases that must never break the round list, which is read on every page
    load:

    * no ``NARRATIVE.json`` exists for this round yet (:func:`app.tournament.narrative.load_narrative`
      returns `None` -- the normal, expected state for a round nobody has written up).
    * ``NARRATIVE.json`` exists but fails to parse (`MalformedNarrativeError`) -- a real defect, but
      caught narrowly (only this one exception type, not a bare `except Exception`) so that a broken
      narrative file degrades one round's label rather than 500ing `/api/competition/rounds` for
      every round in the list.

    Falls back to ``round_id`` verbatim for anything that does not parse as ``<tag>-<YYYY>-<MM>``
    either -- a label is cosmetic, and a round whose directory name does not fit the pattern still
    deserves to be listed rather than raise.

    Imports `app.tournament.narrative` locally rather than at module level: `narrative.py` itself
    imports `list_round_ids`/`round_sequence` from *this* module, so a top-level import here would be
    circular.
    """
    from app.tournament import narrative  # local import: avoids a circular import, see above

    try:
        parsed = narrative.load_narrative(round_id, rounds_root=rounds_root)
    except narrative.MalformedNarrativeError:
        parsed = None
    if parsed is not None:
        return parsed.title

    parts = round_id.split("-")
    if len(parts) >= 3:
        tag, year, month = parts[0], parts[1], parts[2]
        try:
            month_name = dt.date(int(year), int(month), 1).strftime("%b")
        except ValueError:
            return round_id
        return f"{tag} — {month_name} {year}"
    return round_id


#: Memoises one run file's `card.agent_id` so `/rounds` re-reads only what changed on disk, keyed by
#: `{runs directory: {filename: (st_mtime_ns, st_size, agent_id)}}`.
#:
#: This is the one place in this module that does not re-read the world on every call, so it is
#: worth being exact about which written rule it does and does not touch. The "never cached" rule
#: this module states in prose is :func:`load_library`'s ("globbed fresh on every call, never
#: cached"), restated at `app.api.competition.library`; both are about the *cards* directories and
#: both still hold -- `load_library` is untouched and still globs and parses every card on every
#: request. No rule was ever written down for the rounds tree, and the module docstring above says
#: nothing about caching at all (its "online reader, not a re-derivation" paragraph is about this
#: module's arithmetic mirroring `score.py`, a different subject entirely). So what follows is the
#: argument this cache has to make on its own, not a docstring being quoted.
#:
#: The reason a rounds cache is dangerous is real even unwritten: a round's results tree is written
#: *while* the API is being read -- `app.tournament.jobs` drops a run file into
#: `results/<window>/runs/` as each card finishes -- so any snapshot of "which agents ran" would
#: drift from disk mid-round. That danger is in caching a *conclusion*. What is cached here is one
#: file's parse, invalidated by that same file's own `(mtime_ns, size)`. A new run file parses for
#: the first time, a deleted run file drops out of the round's count on the very next call, and a
#: rewritten one re-parses -- the count `/rounds` reports is the count a full re-read would report.
#: `tests/test_competition_round_listing_cache.py::TestFreshness` mutates the tree between two
#: `list_rounds` calls for each of those cases, so this paragraph is checkable rather than asserted.
#:
#: The one case `(mtime_ns, size)` cannot distinguish is a rewrite landing inside the filesystem's
#: timestamp resolution at an identical byte length. That case cannot change this function's answer:
#: `app.tournament.jobs` names each run file `f"{_TAG}-{card.agent_id}.json"` (see `jobs.py`), so a
#: file rewritten under its own name still holds the same `card.agent_id` -- the only field cached
#: here. Note the direction of that argument: the filename is evidence about what a *rewrite* can
#: change, not a substitute for reading the file. The agent id is still taken from the content on
#: every first read, never parsed out of the name -- see the module docstring's real-data note on
#: why the filename's `r1-` prefix identifies nothing. (That note is genuinely in the module
#: docstring; measured against the tree at the time of writing, stripping a leading `r\d+-` from all
#: 1051 run files reproduces the embedded `card.agent_id` every time -- which is exactly why it is
#: tempting, and why counting from filenames was still not done.)
#:
#: Keyed per directory rather than per file path so that the entry for a deleted run file is evicted
#: by the same rebuild that notices it is gone (the inner dict is replaced wholesale on every scan),
#: rather than accumulating forever. Left deliberately lock-free: two threads racing the same
#: directory (sync endpoints run in a threadpool) both parse and one overwrites the other with the
#: identical mapping, which costs a redundant read and cannot produce a wrong answer.
_AGENT_ID_CACHE: dict[str, dict[str, tuple[int, int, str]]] = {}


def _agent_ids_in_runs_dir(runs_dir: Path) -> set[str]:
    """Distinct `card.agent_id` values across every run file in `runs_dir`.

    Reads just the `card.agent_id` field via `json.loads` rather than the full
    `AgentResult.model_validate_json` -- counting agents for `/rounds` does not need the trades or
    metrics, and a round can hold hundreds of run files across its windows.

    The parse of each file is memoised against that file's own `(st_mtime_ns, st_size)` in
    :data:`_AGENT_ID_CACHE` -- see there for what that does and does not cost in freshness, and for
    which of this module's written "never cached" rules it leaves standing (all of them: they are
    about the card library, not the rounds tree). The measured reason: `list_rounds` reached 1051 run
    files across the 14 rounds on disk, ~370ms of `json.loads` on every page load, against ~8ms for
    the directory scan that now serves the repeat call.

    Uses `os.scandir` rather than `Path.glob` because the `(mtime_ns, size)` key is carried by the
    directory entry itself: `DirEntry.stat()` on an already-listed entry costs no extra syscall on
    either platform this runs on (measured at ~1ms across all 1051 files), so the cache key is
    effectively free next to the listing it rides along with. `entry.name.endswith(".json")` matches
    `glob("*.json")`'s POSIX behaviour, and `is_file()` skips a directory that happens to be named
    `*.json` -- which the old `glob` would have handed to `read_text` to raise on.

    A malformed or non-run `*.json` file still raises (`JSONDecodeError` / `KeyError`) exactly as
    before: this function counts what the runner wrote, and a file in `runs/` that is not a run
    result is a defect worth surfacing rather than silently counting as zero agents.
    """
    try:
        entries = list(os.scandir(runs_dir))
    except OSError:
        # Exactly what the `Path.is_dir()` guard this replaced already swallowed: a missing `runs/`
        # directory (the normal state for a round nobody has run yet), a non-directory in its place,
        # or an unreadable one all mean "no agents counted here", never a 500 on the round list.
        _AGENT_ID_CACHE.pop(str(runs_dir), None)
        return set()

    cached = _AGENT_ID_CACHE.get(str(runs_dir), {})
    fresh: dict[str, tuple[int, int, str]] = {}
    ids: set[str] = set()
    for entry in entries:
        if not entry.name.endswith(".json") or not entry.is_file():
            continue
        stat = entry.stat()
        key = (stat.st_mtime_ns, stat.st_size)
        hit = cached.get(entry.name)
        if hit is not None and (hit[0], hit[1]) == key:
            agent_id = hit[2]
        else:
            data = json.loads(Path(entry.path).read_text(encoding="utf-8"))
            agent_id = data["card"]["agent_id"]
        fresh[entry.name] = (key[0], key[1], agent_id)
        ids.add(agent_id)

    _AGENT_ID_CACHE[str(runs_dir)] = fresh
    return ids


def list_round_ids(rounds_root: Path | None = None) -> list[str]:
    """Every round directory under `rounds_root`, newest-first by round *number* descending.

    Sorted by `(round_sequence(name), name)` descending -- see :func:`round_sequence`'s docstring for
    why sorting the directory names themselves (plain string comparison) is wrong: it puts `r9` above
    `r13`. The `name` tiebreaker only matters for directories `round_sequence` cannot parse (it
    returns `-1` for all of them), so those still sort in a stable, deterministic order relative to
    each other rather than an arbitrary one.
    """
    root = rounds_root if rounds_root is not None else ROUNDS_ROOT
    if not root.is_dir():
        return []
    names = [p.name for p in root.iterdir() if p.is_dir()]
    return sorted(names, key=lambda name: (round_sequence(name), name), reverse=True)


def list_rounds(rounds_root: Path | None = None) -> list[RoundSummaryData]:
    """`/api/competition/rounds`'s data: every round, its window set, and its agent count.

    `has_results` and `has_selection` exist so a caller (the frontend seeds its selected round from
    the first entry here) can tell apart a round that has something to render from one that does not,
    rather than defaulting onto a round whose leaderboard endpoint will 404 -- see
    `build_leaderboard`/`load_round_results`'s `RoundNotFoundError`.
    """
    root = rounds_root if rounds_root is not None else ROUNDS_ROOT
    out: list[RoundSummaryData] = []
    for round_id in list_round_ids(root):
        round_dir = root / round_id
        results_dir = round_dir / "results"
        windows = _discover_windows(results_dir)
        agent_ids: set[str] = set()
        for window in windows:
            agent_ids |= _agent_ids_in_runs_dir(results_dir / window / "runs")
        out.append(
            RoundSummaryData(
                round_id=round_id,
                label=_round_label(round_id, root),
                windows=tuple(windows),
                agents=len(agent_ids),
                has_report=(round_dir / "REPORT.md").is_file(),
                has_brief=(round_dir / "BRIEF.md").is_file(),
                has_results=results_dir.is_dir() and len(windows) > 0,
                has_selection=(results_dir / _LIVE_MATRIX_MARKER).is_dir(),
                sequence=round_sequence(round_id),
            )
        )
    return out


def load_round_results(
    round_id: str, rounds_root: Path | None = None
) -> dict[str, dict[str, AgentResult]]:
    """``{window: {agent_id: AgentResult}}`` for every run file under this round's results tree.

    Keyed by the *content* `card.agent_id`, never the filename -- see the module docstring's
    real-data note on why the filename's round-tag prefix cannot be trusted to identify which round a
    file belongs to (it doesn't; every file under both committed rounds is prefixed ``r1-``). Every
    ``*.json`` found under a round's own ``results/<window>/runs/`` directory is that round's data by
    construction of which directory it was loaded from, with no filename filtering at all.

    Raises :class:`RoundNotFoundError` when `round_id` has no `results/` directory.
    """
    root = rounds_root if rounds_root is not None else ROUNDS_ROOT
    results_dir = root / round_id / "results"
    if not results_dir.is_dir():
        raise RoundNotFoundError(round_id)
    windows = _discover_windows(results_dir)
    out: dict[str, dict[str, AgentResult]] = {}
    for window in windows:
        runs_dir = results_dir / window / "runs"
        agents: dict[str, AgentResult] = {}
        for path in sorted(runs_dir.glob("*.json")):
            result = AgentResult.model_validate_json(path.read_text(encoding="utf-8"))
            agents[result.card.agent_id] = result
        out[window] = agents
    return out


# ---------------------------------------------------------------------------
# Metrics -- see the module docstring for the score.py / attribution.py correspondence
# ---------------------------------------------------------------------------


def corrected_return(result: AgentResult) -> Decimal:
    """`ending_equity / starting_equity - 1` -- never `result.total_return`.

    See `strategy-program/DEFECTS.md` D1: round-1 files have `total_return` rebased to the first
    session's close rather than to starting equity, and this ratio is the value that is correct
    under both the old and the fixed engine (the same reasoning `score.py.corrected_return` and
    `attribution.py.attribute_window` both already apply).
    """
    return result.ending_equity / result.starting_equity - Decimal(1)


def _capital_exposure(result: AgentResult) -> tuple[float | None, bool]:
    """``(capital_exposure, reconstructed)``.

    Prefers the engine's own `AgentResult.capital_exposure` (`reconstructed=False`). Falls back to
    the trade-log reconstruction `Σ(quantity * entry_price * bars_held) / (sessions *
    starting_equity)` -- exactly `score.py.capital_exposure`'s formula -- when the engine figure is
    `None` (round-1 files predate the field). `(None, True)` when even the reconstruction has nothing
    to measure from (no trades, or a zero denominator) -- unmeasurable, not zero, same as
    `score.py`'s own `None` return in that case.
    """
    if result.capital_exposure is not None:
        return result.capital_exposure, False
    if not result.trades or result.sessions <= 0 or result.starting_equity <= 0:
        return None, True
    invested = sum(
        (t.quantity * t.entry_price * t.bars_held for t in result.trades), Decimal(0)
    )
    value = invested / (Decimal(result.sessions) * result.starting_equity)
    return float(value), True


def excess(result: AgentResult) -> Decimal | None:
    """`corrected_return - benchmark_return`. `None` when the benchmark is unknown."""
    if result.benchmark_return is None:
        return None
    return corrected_return(result) - result.benchmark_return


def _adjusted_excess(result: AgentResult) -> Decimal | None:
    """`corrected_return - capital_exposure * benchmark_return`, using `capital_exposure` (never
    `exposure`) per `strategy-program/DEFECTS.md` D2. Falls back to the session-presence `exposure`
    only when the card took no trades at all (where the two figures coincide at zero anyway),
    matching `score.py.adjusted_excess`. `None` when the benchmark is unknown or no exposure figure
    of any kind is available.
    """
    if result.benchmark_return is None:
        return None
    value, _reconstructed = _capital_exposure(result)
    if value is None:
        if result.exposure is None:
            return None
        value = result.exposure
    return corrected_return(result) - Decimal(str(value)) * result.benchmark_return


# ---------------------------------------------------------------------------
# ScoredRun -- a normalised view across the three card shapes this program can produce
# ---------------------------------------------------------------------------
#
# `AgentResult` (a `StrategyCard`'s result), `AllocationResult` (an `AllocationCard`'s) and
# `LadderResult` (a `LadderCard`'s) are field-for-field identical except for the type of `card` --
# see `AllocationResult`'s and `LadderResult`'s own docstrings for why that one field forces three
# separate pydantic models rather than one shared base. `AgentResult.model_validate_json` therefore
# rejects an allocation or ladder run file's `"card"` payload outright, and `isinstance` between any
# two of the three is always `False`. Round 15's candidates are allocation and ladder cards; nothing
# above this section can read one.
#
# The reason this is a new section rather than a small patch to `load_round_results` is
# `capital_exposure`. It carries a different meaning in each result type:
#
# * `AgentResult.capital_exposure` -- entry notional (each lot's dollar size at the moment it was
#   opened, never marked to market) summed over open lots, over `starting_equity`, averaged across
#   sessions. See that field's own docstring.
# * `AllocationResult.capital_exposure` / `LadderResult.capital_exposure` -- invested value over
#   *current* equity, at each session's own close, averaged across sessions. See
#   `AllocationResult.capital_exposure`'s own docstring for why the `AgentResult` denominator
#   (`starting_equity`) would not measure exposure at all here: a fully-invested sleeve book that
#   compounds from $10,000 to $25,000 would report `capital_exposure ~= 1.75` under that convention,
#   "a number shaped like a fraction that is not one". What this section's authors verified instead
#   sits near `1.0` for a continuously-invested book, by construction.
#
# `_adjusted_excess` above feeds `capital_exposure` into `corrected_return - capital_exposure *
# benchmark_return`. Feeding an allocation or ladder book's ~1.0 into that formula would not produce
# a slightly-off `adjusted_excess` -- it would produce a different metric wearing the same name, and
# it would rank a fully-invested ETF blend against a 30%-exposed stock picker as though the
# comparison meant something.
#
# There is also a second, easier-to-miss trap in the *fallback* `_adjusted_excess` already takes
# above: when `capital_exposure` is `None`, it substitutes `result.exposure` -- session presence,
# fraction of sessions with any position open at all, not capital at risk (`DEFECTS.md` D2). That
# fallback is safe for a `StrategyCard` run because its docstring's own justification holds: it only
# fires when the card took no trades at all, where `exposure` and `capital_exposure` coincide at
# zero anyway. That justification is specific to a `StrategyCard`'s all-or-nothing position sizing
# and does not hold for an allocation or ladder book -- every sleeve is open every session there, so
# `exposure` sits near `1.0`, not `0`, regardless of whether `capital_exposure` happens to be
# populated. A reader that refuses `adjusted_excess` only when it distrusts `capital_exposure` would
# still walk straight around that refusal via `exposure` and return a confident, wrong number.
#
# So the gate below is not "is `capital_exposure` present and small enough to trust" -- it is
# `exposure_basis`, decided once, from the card *shape*, before either field is ever consulted. A
# `ScoredRun` whose `exposure_basis` is not `"entry-notional"` has no path to an `adjusted_excess` at
# all: :meth:`ScoredRun.adjusted_excess` raises before it reads `capital_exposure` or `exposure`, not
# after finding one of them unusable.

ExposureBasis = Literal["entry-notional", "invested-value"]
"""What `capital_exposure` is denominated against for a given card shape -- see the section comment
above. `"entry-notional"` is the only basis `adjusted_excess` is defined for."""

CardShape = Literal["stock-picking", "allocation", "ladder"]
"""Which of the three run-file shapes a `"card"` payload matched -- see :func:`_card_shape`."""

#: `StrategyCard`'s own required fields that neither `AllocationCard` nor `LadderCard` carries.
#: `entry`/`exit`/`universe` are the ones this module's docstring already leans on to describe a
#: `StrategyCard` ("in-or-out", "per instrument"); `max_positions`/`position_pct` are included too
#: so a payload missing one of the first three for some future reason still matches on the others.
_STOCK_PICKING_CARD_MARKERS = frozenset(
    {"entry", "exit", "universe", "max_positions", "position_pct"}
)

#: `AllocationCard`'s own required fields, absent from both other shapes -- see
#: `app.tournament.allocation.AllocationCard`.
_ALLOCATION_CARD_MARKERS = frozenset({"sleeves", "band_pct"})

#: `LadderCard`'s own required fields, absent from both other shapes -- see
#: `app.tournament.ladder.LadderCard`.
_LADDER_CARD_MARKERS = frozenset(
    {
        "rungs",
        "signal_symbol",
        "defensive_symbol",
        "bond_symbol",
        "leveraged_symbol",
        "base_defensive_weight",
        "base_bond_weight",
    }
)

_EXPOSURE_BASIS_FOR_SHAPE: dict[CardShape, ExposureBasis] = {
    "stock-picking": "entry-notional",
    "allocation": "invested-value",
    "ladder": "invested-value",
}


class UnrecognisedCardShapeError(Exception):
    """A run file's `"card"` payload matches none of the three known card shapes.

    Raised with the payload's own keys, sorted, so the message names what was actually found rather
    than only what was expected.
    """

    def __init__(self, card_keys: tuple[str, ...]) -> None:
        self.card_keys = card_keys
        super().__init__(
            f"card payload with keys {sorted(card_keys)!r} matches none of the three known card "
            "shapes: stock-picking (StrategyCard: entry/exit/universe/...), allocation "
            "(AllocationCard: sleeves/band_pct) or ladder (LadderCard: rungs/signal_symbol/...). "
            "Dispatch is on the payload's own keys, never the filename or which round directory it "
            "was found under -- see this module's docstring's real-data note on why a run file's "
            "name cannot be trusted to identify anything about its contents."
        )


class ExposureBasisError(Exception):
    """:meth:`ScoredRun.adjusted_excess` was called on a run whose `exposure_basis` is not
    `"entry-notional"`.

    Raised, never a fallback value and never a silent `None` indistinguishable from "benchmark
    unknown" -- see this section's own comment above for why a `None` here would be exactly as
    dangerous as a wrong number: a caller checking `if adjusted is not None` would treat the absence
    of a raise as permission to keep going.
    """

    def __init__(self, agent_id: str, exposure_basis: ExposureBasis) -> None:
        self.agent_id = agent_id
        self.exposure_basis = exposure_basis
        super().__init__(
            f"{agent_id!r}: adjusted_excess is undefined for exposure_basis={exposure_basis!r}. "
            "adjusted_excess = corrected_return - capital_exposure * benchmark_return assumes "
            "capital_exposure is entry notional over starting_equity (AgentResult's convention); "
            "this run's capital_exposure is invested value over equity at each session's own close "
            "(AllocationResult's / LadderResult's convention), which sits near 1.0 for a "
            "continuously-invested book regardless of the strategy. Feeding it into the formula "
            "would not produce a slightly-off adjusted_excess, it would produce a different metric "
            "wearing the same name. Score this run on .excess instead."
        )


def _card_shape(card_payload: dict[str, object]) -> CardShape:
    """Which of the three known card shapes `card_payload` (the raw, still-`dict` `"card"` value of
    a run file) matches, decided from its own keys alone.

    Never told the filename, the window, or which round directory the file was found under -- see
    the module docstring's real-data note on why the filename's leading `r<N>-` prefix identifies
    nothing (every committed run file under every round is prefixed `r1-` regardless of which round
    produced it) and `_agent_ids_in_runs_dir`'s docstring for the same rule applied to `agent_id`.
    The same discipline applies here to the shape itself: a run file could in principle be misnamed
    or moved, and the payload is still the only thing that says what it is.
    """
    keys = frozenset(card_payload)
    if keys >= _LADDER_CARD_MARKERS:
        return "ladder"
    if keys >= _ALLOCATION_CARD_MARKERS:
        return "allocation"
    if keys >= _STOCK_PICKING_CARD_MARKERS:
        return "stock-picking"
    raise UnrecognisedCardShapeError(tuple(sorted(keys)))


@dataclass(frozen=True, slots=True)
class ScoredRun:
    """One run file -- a `StrategyCard`'s, an `AllocationCard`'s or a `LadderCard`'s -- normalised
    to a single shape, carrying an explicit :data:`ExposureBasis` so a caller cannot mistake one card
    shape's `capital_exposure` for another's.

    Built by :func:`parse_scored_run`, never constructed by hand outside this module: the invariant
    this whole section exists for -- that `adjusted_excess` is unreachable on a non-`"entry-notional"`
    run -- depends on `exposure_basis` and the private `_adjusted_excess_value` staying in agreement,
    which only :func:`parse_scored_run` is responsible for keeping true.
    """

    window: str
    card_shape: CardShape
    exposure_basis: ExposureBasis
    agent_id: str
    display_name: str
    discipline: str
    """`str(StrategyCard.discipline)` for a stock-picking run -- the analyst's stated school
    (`"momentum"`, `"trend"`, ...). Neither `AllocationCard` nor `LadderCard` carries a `discipline`
    field at all (see `app.tournament.models.Discipline`'s own docstring: it exists to tell ten
    variations on one stock-picking idea apart from ten independent ones, a question that does not
    apply to a fixed-sleeve or ladder book), so an allocation or ladder run reports its own
    `card_shape` here instead (`"allocation"` / `"ladder"`) -- still a real, displayable label, and
    one that cannot collide with any `Discipline` value."""
    purpose: str
    sessions: int
    starting_equity: Decimal
    ending_equity: Decimal
    corrected_return: Decimal
    benchmark_return: Decimal | None
    excess: Decimal | None
    """`corrected_return - benchmark_return`. Defined for every basis -- unlike `adjusted_excess`,
    plain `excess` makes no claim about how much capital was at risk, so there is nothing here that
    an allocation or ladder book's `capital_exposure` convention could corrupt."""
    capital_exposure: float | None
    """Reported for every run as a plain, informational figure -- **never** read by anything in this
    module except :func:`parse_scored_run` itself, and only for a `"entry-notional"` run building
    `adjusted_excess`. A caller displaying this column for a mixed set of runs must also display
    `exposure_basis`, the same discipline `LeaderboardData.scoring_basis` already imposes on
    `median_excess` -- a number is not self-describing."""
    capital_exposure_reconstructed: bool
    """Whether `capital_exposure` came from the engine's own field or the trade-log reconstruction
    `_capital_exposure` falls back to. **Only ever `True` for an `"entry-notional"` run.** The
    reconstruction formula (`Σ(quantity * entry_price * bars_held) / (sessions * starting_equity)`)
    assumes entry notional over *starting* equity, the same assumption that makes `adjusted_excess`
    meaningless for an allocation or ladder book (see this section's own comment block) -- so an
    invested-value run whose engine `capital_exposure` is `None` is reported as `capital_exposure=
    None, capital_exposure_reconstructed=False` (unmeasurable) rather than silently reconstructed
    against a denominator that would not measure exposure at all for that book."""
    max_drawdown: Decimal
    """The engine's own `max_drawdown`, copied verbatim -- identically defined and identically
    computed (`app.backtest.metrics.compute`) for all three card shapes, so unlike `capital_exposure`
    this field needs no basis gate at all."""
    trades: int

    _adjusted_excess_value: Decimal | None = field(default=None, repr=False, compare=False)
    """Precomputed only for a `"entry-notional"` run (see :func:`parse_scored_run`), by calling the
    exact same `_adjusted_excess` this module's `compute_window`/`build_leaderboard` path already
    calls -- not a reimplementation that could drift from it. Left at its default `None` for every
    other basis and never read in that case: :meth:`adjusted_excess` raises before it would matter.
    Private and excluded from `repr`/equality so a caller cannot reach the number by inspecting the
    dataclass instead of calling the gated method -- the field is an implementation detail of the
    method below, not a second public API for the same value."""

    def adjusted_excess(self) -> Decimal | None:
        """`corrected_return - capital_exposure * benchmark_return`, exactly as
        `results._adjusted_excess` computes it for a `"entry-notional"` run today.

        Raises :class:`ExposureBasisError` -- unconditionally, before `capital_exposure` or
        `exposure` is ever consulted -- when `exposure_basis != "entry-notional"`. `None`, not a
        raise, only once the basis has already been confirmed right and the benchmark itself is
        unknown -- the ordinary "we don't have this number yet" case every other metric in this
        module already reports as `None`.
        """
        if self.exposure_basis != "entry-notional":
            raise ExposureBasisError(self.agent_id, self.exposure_basis)
        return self._adjusted_excess_value


def _invested_value_metrics(
    result: AllocationResult | LadderResult,
) -> tuple[Decimal, Decimal | None]:
    """`(corrected_return, excess)` for an allocation or ladder result -- the identical two-line
    arithmetic `corrected_return`/`excess` apply to an `AgentResult`, restated here rather than
    widening those functions' parameter type to a three-way union.

    Kept as a separate, narrowly-typed function -- rather than broadening `corrected_return`/`excess`
    above to accept `AgentResult | AllocationResult | LadderResult` -- so that nothing about this
    section's addition changes what those two functions are declared to accept, and so this
    function's own name says outright which basis it is for. `adjusted_excess` has no equivalent
    here on purpose: see this section's comment block for why.
    """
    corrected = result.ending_equity / result.starting_equity - Decimal(1)
    if result.benchmark_return is None:
        return corrected, None
    return corrected, corrected - result.benchmark_return


def parse_scored_run(raw: str, *, window: str) -> ScoredRun:
    """Parse one run file's raw JSON text into a :class:`ScoredRun`, dispatching on the `"card"`
    payload's own shape (:func:`_card_shape`) -- never on a filename, which the caller does not even
    supply here.

    Raises :class:`UnrecognisedCardShapeError` when the payload matches none of the three known card
    shapes, and whatever `pydantic.ValidationError` the matched model itself raises when the rest of
    the payload does not validate against it -- a malformed run file is a defect worth surfacing, not
    swallowing, the same stance `load_round_results` already takes on a malformed `AgentResult` file.

    Parses `raw` exactly once, with the stdlib `json.loads` this function needs anyway to look at the
    `"card"` payload's own keys before picking a model. The matched pydantic model then validates
    from that already-parsed `dict` (`model_validate`), not by re-parsing `raw` a second time
    (`model_validate_json`) -- on a round with hundreds of run files, letting a second JSON parser
    walk the same bytes a first one already did is exactly the redundant-cost shape this module's own
    `_agent_ids_in_runs_dir` docstring warns against, restated one call-path down.
    """
    payload = json.loads(raw)
    card_payload = payload.get("card")
    if not isinstance(card_payload, dict):
        raise UnrecognisedCardShapeError(())
    shape = _card_shape(card_payload)
    basis = _EXPOSURE_BASIS_FOR_SHAPE[shape]

    if shape == "stock-picking":
        agent_result = AgentResult.model_validate(payload)
        corrected = corrected_return(agent_result)
        excess_value = excess(agent_result)
        adjusted = _adjusted_excess(agent_result)
        capital_exposure_value, reconstructed = _capital_exposure(agent_result)
        return ScoredRun(
            window=window,
            card_shape=shape,
            exposure_basis=basis,
            agent_id=agent_result.card.agent_id,
            display_name=agent_result.card.display_name,
            discipline=str(agent_result.card.discipline),
            purpose=str(agent_result.card.purpose),
            sessions=agent_result.sessions,
            starting_equity=agent_result.starting_equity,
            ending_equity=agent_result.ending_equity,
            corrected_return=corrected,
            benchmark_return=agent_result.benchmark_return,
            excess=excess_value,
            capital_exposure=capital_exposure_value,
            capital_exposure_reconstructed=reconstructed,
            max_drawdown=agent_result.max_drawdown,
            trades=len(agent_result.trades),
            _adjusted_excess_value=adjusted,
        )

    allocation_or_ladder: AllocationResult | LadderResult
    if shape == "allocation":
        allocation_or_ladder = AllocationResult.model_validate(payload)
    else:
        allocation_or_ladder = LadderResult.model_validate(payload)

    corrected, excess_value = _invested_value_metrics(allocation_or_ladder)
    return ScoredRun(
        window=window,
        card_shape=shape,
        exposure_basis=basis,
        agent_id=allocation_or_ladder.card.agent_id,
        display_name=allocation_or_ladder.card.display_name,
        # No `discipline` field exists on `AllocationCard`/`LadderCard` -- see `ScoredRun.discipline`'s
        # own docstring for why the shape itself is the next best label.
        discipline=shape,
        purpose=str(allocation_or_ladder.card.purpose),
        sessions=allocation_or_ladder.sessions,
        starting_equity=allocation_or_ladder.starting_equity,
        ending_equity=allocation_or_ladder.ending_equity,
        corrected_return=corrected,
        benchmark_return=allocation_or_ladder.benchmark_return,
        excess=excess_value,
        capital_exposure=allocation_or_ladder.capital_exposure,
        # Never reconstructed -- see `ScoredRun.capital_exposure_reconstructed`'s own docstring: the
        # trade-log reconstruction formula assumes an entry-notional-over-starting-equity basis that
        # does not hold for an invested-value book, so a `None` engine figure stays `None` here rather
        # than being filled in against a denominator that would not measure exposure at all.
        capital_exposure_reconstructed=False,
        max_drawdown=allocation_or_ladder.max_drawdown,
        trades=len(allocation_or_ladder.trades),
        # _adjusted_excess_value left at its default `None` -- deliberately never computed for this
        # basis. See this section's own comment block and `ExposureBasisError` for why.
    )


def load_scored_run_file(path: Path, *, window: str) -> ScoredRun:
    """:func:`parse_scored_run` for a run file already on disk."""
    return parse_scored_run(path.read_text(encoding="utf-8"), window=window)


def load_round_scored_runs(
    round_id: str, rounds_root: Path | None = None
) -> dict[str, dict[str, ScoredRun]]:
    """``{window: {agent_id: ScoredRun}}`` for every run file under this round's results tree --
    `load_round_results`'s counterpart for a round that may hold allocation and ladder candidates as
    well as stock-picking ones, which `load_round_results` cannot read at all (see this section's own
    comment block).

    `load_round_results` is untouched and still backs `build_leaderboard`/`build_agent_detail`
    exactly as before -- this is an additional reader, not a replacement, so a round scored purely on
    the stock-picking regime-window matrix keeps reading exactly the way it already does.

    Not memoised. `_AGENT_ID_CACHE` above deliberately stores only `(mtime_ns, size, agent_id)` --
    sound because `agent_id` cannot change under a stable filename (`app.tournament.jobs` names each
    file after it), and unsound for anything a rerun could rewrite in place at the same byte length,
    which a computed score is. Holding a full `ScoredRun` per file in a module-level dict would also
    trade a bounded, per-request cost for an unbounded one that only grows as rounds accumulate --
    see this function's own docstring test file for the measured per-call cost this was weighed
    against.
    """
    root = rounds_root if rounds_root is not None else ROUNDS_ROOT
    results_dir = root / round_id / "results"
    if not results_dir.is_dir():
        raise RoundNotFoundError(round_id)
    windows = _discover_windows(results_dir)
    out: dict[str, dict[str, ScoredRun]] = {}
    for window in windows:
        runs_dir = results_dir / window / "runs"
        agents: dict[str, ScoredRun] = {}
        for path in sorted(runs_dir.glob("*.json")):
            run = load_scored_run_file(path, window=window)
            agents[run.agent_id] = run
        out[window] = agents
    return out


@dataclass(frozen=True, slots=True)
class TradeContribution:
    """One trade's exact share of its card's return in one window -- see
    `strategy-program/tools/attribution.py`'s `TradeContribution`, which this reproduces."""

    trade: RealisedTrade
    contribution: Decimal
    """`pnl / starting_equity`, signed. Summing every trade's contribution reproduces
    `corrected_return` exactly -- the trade log is complete and nothing here is apportioned."""

    unrealised: bool
    """`True` when `trade.exit_reason == "open_at_end"`: a mark against the last session's close,
    not money taken."""


def _attribute_trades(result: AgentResult) -> list[TradeContribution]:
    """Every trade in `result`, as a :class:`TradeContribution`, sorted by `abs(contribution)`
    descending -- the order `attribution.py.attribute_window` uses and the order the agent-detail
    endpoint's contract requires."""
    starting = result.starting_equity
    contributions = [
        TradeContribution(
            trade=t,
            contribution=t.pnl / starting,
            unrealised=t.exit_reason == "open_at_end",
        )
        for t in result.trades
    ]
    contributions.sort(key=lambda c: abs(c.contribution), reverse=True)
    return contributions


@dataclass(frozen=True, slots=True)
class WindowMetrics:
    """Everything computed for one (agent, window) pair -- the superset the leaderboard's per-window
    cell and the agent-detail endpoint's per-window section are both drawn from."""

    window: str
    sessions: int
    starting_equity: Decimal
    ending_equity: Decimal
    total_return: Decimal
    benchmark_return: Decimal | None
    excess: Decimal | None
    adjusted_excess: Decimal | None
    capital_exposure: float | None
    capital_exposure_reconstructed: bool
    max_drawdown: Decimal
    win_rate: float | None
    profit_factor: Decimal | None
    trades: int
    unrealised_share: Decimal
    top3_share_of_gross_wins: float | None
    return_without_top3_winners: Decimal
    rejections: tuple[str, ...]
    contributions: tuple[TradeContribution, ...]


def compute_window(result: AgentResult, window: str) -> WindowMetrics:
    """Reduce one `AgentResult` to the figures both competition endpoints report for that window."""
    total_return = corrected_return(result)
    capital_exposure_value, reconstructed = _capital_exposure(result)
    excess_value = excess(result)
    adjusted = _adjusted_excess(result)

    contributions = tuple(_attribute_trades(result))
    winners = [c for c in contributions if c.contribution > 0]
    gross_win = sum((c.contribution for c in winners), Decimal(0))
    top3 = sum((c.contribution for c in winners[:3]), Decimal(0))
    top3_share = None if gross_win == 0 else float(top3 / gross_win)
    unrealised_share = sum(
        (c.contribution for c in contributions if c.unrealised), Decimal(0)
    )

    return WindowMetrics(
        window=window,
        sessions=result.sessions,
        starting_equity=result.starting_equity,
        ending_equity=result.ending_equity,
        total_return=total_return,
        benchmark_return=result.benchmark_return,
        excess=excess_value,
        adjusted_excess=adjusted,
        capital_exposure=capital_exposure_value,
        capital_exposure_reconstructed=reconstructed,
        max_drawdown=result.max_drawdown,
        win_rate=result.win_rate,
        profit_factor=result.profit_factor,
        trades=len(result.trades),
        unrealised_share=unrealised_share,
        top3_share_of_gross_wins=top3_share,
        return_without_top3_winners=total_return - top3,
        rejections=result.rejections,
        contributions=contributions,
    )


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WindowFacts:
    """What every card in a window shares -- reported once per window, not once per row.

    `benchmark_return` is asserted equal across every card that ran in the window (see
    `_shared_benchmark_return`) rather than averaged: SPY's buy-and-hold return over a shared session
    range cannot legitimately differ between two cards run over the same window, so a disagreement is
    a data-integrity problem worth failing loudly on, not a number to blend away.
    """

    window: str
    sessions: int
    #: `None` when no card in the window carried one. `AgentResult.benchmark_return` is itself
    #: optional, so a window in which every card lacks it shares that absence rather than a
    #: number -- previously this field claimed `Decimal` and stored the `None` anyway.
    benchmark_return: Decimal | None
    provenance_constrained: bool


def _shared_window_fact[T](values: set[T], window: str, field_name: str) -> T:
    if len(values) > 1:
        raise ValueError(
            f"window {window!r} has disagreeing {field_name} values across cards: {sorted(values, key=str)} "
            "-- every card in a window shares one benchmark and one session count, so this is a data "
            "problem to surface, not to average"
        )
    return next(iter(values))


@dataclass(frozen=True, slots=True)
class LeaderboardCellData:
    """One (agent, window) cell as the leaderboard renders it -- a slimmer view than
    :class:`WindowMetrics` (no per-trade attribution; `app.tournament.results.build_agent_detail` is
    the drill-down for that), and unlike `WindowMetrics` built directly from a :class:`ScoredRun`
    rather than from a raw `AgentResult`, so it exists for every card shape the leaderboard can now
    rank, not only a `StrategyCard`'s.

    `adjusted_excess` is `None` for an `"invested-value"` run, always -- never computed, never
    substituted -- see :meth:`ScoredRun.adjusted_excess` and `ExposureBasisError` for why asking is
    refused rather than answered with a number that would not mean what its name says.
    """

    total_return: Decimal
    benchmark_return: Decimal | None
    excess: Decimal | None
    adjusted_excess: Decimal | None
    capital_exposure: float | None
    capital_exposure_reconstructed: bool
    max_drawdown: Decimal
    trades: int
    sessions: int


def _scored_run_to_cell(run: ScoredRun) -> LeaderboardCellData:
    """:class:`ScoredRun` -> :class:`LeaderboardCellData`, gating `adjusted_excess` on
    `exposure_basis` -- the one place in the leaderboard path that would otherwise be tempted to call
    :meth:`ScoredRun.adjusted_excess` unconditionally and let `ExposureBasisError` bubble up as a 500
    for every invested-value row. Checking `exposure_basis` here instead of catching the error is
    deliberate: a `try/except ExposureBasisError: adjusted = None` reads the same on the page but
    would silently swallow a *real* defect too (e.g. a future basis this module does not know about
    yet), where the explicit check fails loudly on anything but the one case it names.
    """
    adjusted = run.adjusted_excess() if run.exposure_basis == "entry-notional" else None
    return LeaderboardCellData(
        total_return=run.corrected_return,
        benchmark_return=run.benchmark_return,
        excess=run.excess,
        adjusted_excess=adjusted,
        capital_exposure=run.capital_exposure,
        capital_exposure_reconstructed=run.capital_exposure_reconstructed,
        max_drawdown=run.max_drawdown,
        trades=run.trades,
        sessions=run.sessions,
    )


@dataclass(frozen=True, slots=True)
class LeaderboardRowData:
    rank: int
    agent_id: str
    display_name: str
    discipline: str
    windows_run: int
    eligible: bool
    median_excess: Decimal | None
    worst_excess: Decimal | None
    hit_rate: float | None
    mean_capital_exposure: float | None
    total_trades: int
    per_window: dict[str, LeaderboardCellData]


@dataclass(frozen=True, slots=True)
class LeaderboardData:
    round_id: str
    rank_by: str
    windows: tuple[WindowFacts, ...]
    rows: tuple[LeaderboardRowData, ...]
    purpose: str
    """Which purpose's book this leaderboard ranks -- see `app.tournament.purposes.Purpose`."""
    scoring_basis: str
    """The quantity `rows` is actually ranked on, named on the response so a client cannot render one
    basis under another's column heading. Decided from the data every `rows` entry actually carries
    (each row's `ScoredRun.exposure_basis`), never assumed from the requested `purpose` -- a `trading`
    round can hold either an `"entry-notional"` (stock-picking) or an `"invested-value"` (allocation /
    ladder) field, and the two are not ranked on the same quantity (see :func:`build_leaderboard`'s
    own docstring on how a round holding both is handled).

    `"adjusted_excess"` for a `trading` field scored on the `"entry-notional"` basis (every round
    before r15, and still the default when `trading` has no rows at all to decide from). `"excess"`
    for a `trading` field scored on `"invested-value"` -- `adjusted_excess` has no meaning there (see
    `ExposureBasisError`), so the next best featured figure is the one quantity every basis defines,
    plain `excess`. `"irr+cagr"` for the two contribution-funded purposes, unrelated to either
    exposure basis: `data/rounds/r12-2026-08/ROTH-CANDIDATES.md` states plainly that an IRR and an
    `adjusted_excess` are different quantities and that ranking them together is a category error
    rather than a rounding one. A single column that silently changes meaning is exactly how that
    error gets made.
    """
    unscored_reason: str | None = None
    """Why the board is not fully scored, when it is not.

    `None` whenever every eligible card produced a rank. Otherwise names one of three causes, and a
    reader is expected to act differently on each:

    * **No cards at all for this purpose** (`rows` is empty): "these strategies have never been
      measured", not "these strategies failed". Every committed round before r15 scores `trading`
      cards only, so this is the normal state for `savings`/`roth`.
    * **`rank_by="excess-per-exposure"` requested against an invested-value field** (`rows` is empty):
      refused, not answered with a number -- see :func:`build_leaderboard`'s own docstring, point 4.
      An invested-value book's `capital_exposure` sits near `1.0` by construction (every sleeve is
      open every session), so dividing `excess` by it is nearly a no-op; the column would still be
      named `excess-per-exposure` while no longer measuring what that name promises.
    * **A mixed-basis field** (`rows` is *non-empty*): one round held both an `"entry-notional"` and
      an `"invested-value"` card for the same purpose. `rows` still ranks the larger group (see
      :func:`build_leaderboard`'s docstring, point 3) and `unscored_reason` names which agent ids were
      excluded and why -- the one case where this field is set even though `rows` has rows, because a
      table that reported nothing here would look complete when a real card was quietly left off it.
    """


def _agent_exposure_basis(
    agent_id: str, windows_order: list[str], by_window: dict[str, dict[str, ScoredRun]]
) -> ExposureBasis:
    """Which basis `agent_id`'s card was scored on, read off its own `ScoredRun.exposure_basis` --
    the same value in every window it ran, since a card's shape (and therefore its basis) cannot
    change mid-round; only which windows it happened to run in can. Raises `ValueError` if that ever
    disagrees across windows, the same "surface it, do not average it" stance
    :func:`_shared_window_fact` already takes for a window's own shared facts -- this is the one
    place `build_leaderboard` decides which basis a row belongs to, so a silent pick between two
    disagreeing answers would be exactly the wrong place to guess.
    """
    bases = {
        by_window[w][agent_id].exposure_basis for w in windows_order if agent_id in by_window[w]
    }
    if len(bases) > 1:
        raise ValueError(
            f"agent {agent_id!r} has disagreeing exposure_basis values across windows: "
            f"{sorted(bases)} -- a card's shape (and therefore its exposure basis) cannot "
            "legitimately change between windows within one round, so this is a data problem to "
            "surface, not to average"
        )
    return next(iter(bases))


@dataclass(frozen=True, slots=True)
class _RowAccumulator:
    agent_id: str
    display_name: str
    discipline: str
    per_window: dict[str, LeaderboardCellData]
    windows_run: int
    eligible: bool
    median_excess: Decimal | None
    worst_excess: Decimal | None
    hit_rate: float | None
    mean_capital_exposure: float | None
    total_trades: int
    median_excess_per_exposure: Decimal | None


def build_leaderboard(
    round_id: str,
    rank_by: str = "median",
    rounds_root: Path | None = None,
    purpose: str = "trading",
) -> LeaderboardData:
    """`/api/competition/rounds/{round_id}/leaderboard`'s data.

    Reads :func:`load_round_scored_runs`, not `load_round_results` -- the one loader that can parse
    all three run-file shapes this program produces (stock-picking, allocation, ladder; see
    `ScoredRun`'s own section of this module). A purely stock-picking round (every committed round
    before r15) reads exactly as it always has: every `ScoredRun` it produces has
    `exposure_basis="entry-notional"`, so none of the three decisions below ever engages for it, and
    the only change is internal (`ScoredRun` in place of `AgentResult` on the way to the same
    numbers).

    Ranks on plain `excess`, never `adjusted_excess`, for an `"entry-notional"` field exactly as
    before -- see the module docstring's divergence note. For an `"invested-value"` field (an
    allocation or ladder book), ranking on `adjusted_excess` is not a choice at all:
    `ScoredRun.adjusted_excess` raises `ExposureBasisError` rather than answer, because that book's
    `capital_exposure` is invested value over current equity, not entry notional over starting
    equity, and feeding it into `adjusted_excess`'s formula would silently produce a different metric
    wearing the same name (see `ExposureBasisError`'s own docstring). So an invested-value field is
    ranked on plain `excess` too -- the one quantity both bases define -- and
    `LeaderboardData.scoring_basis` says `"excess"` rather than `"adjusted_excess"` so a reader is not
    misled about which figure earned the rank.

    **Three decisions this function makes that a purely entry-notional round never exercises, each
    worth recording because nothing forced them -- a different, equally defensible choice was
    available at every one:**

    1. **A field mixing both bases is never ranked as one table.** A rank is a position within a
       field, and `"entry-notional"` and `"invested-value"` are not the same field: an allocation
       book's `excess` and a stock-picker's `excess` are computed from the same formula
       (`corrected_return - benchmark_return`) but say nothing about how much capital either one put
       at risk to earn it, so a single ranked column blending both would present two different
       orderings as though they were one. Rather than split the response into two tables (a bigger
       contract change for a case no committed round has ever produced) or refuse the whole board
       (hiding every row over a problem confined to the minority), this function ranks only the
       larger group -- ties broken toward `"entry-notional"`, the basis every round before r15 and
       every existing test already expects a homogeneous field to be -- and reports the smaller
       group's agent ids in `unscored_reason`, never silently dropping them. See
       :func:`_agent_exposure_basis`.
    2. **`rank_by="excess-per-exposure"` is refused outright for an invested-value field**, rather
       than computed against an exposure figure that has stopped discriminating between strategies.
       An allocation or ladder book keeps every sleeve open every session by construction, so its
       `capital_exposure` sits close to `1.0` for the life of the run regardless of the strategy --
       dividing `excess` by a number that is always approximately `1` is approximately a no-op, and a
       column still labelled `excess-per-exposure` would no longer measure what that name promises.
       `rows` comes back empty with `unscored_reason` naming the refusal, the same "empty means
       something specific" contract an unscored purpose already uses, rather than publishing a ratio
       whose denominator carries no information.
    3. **`scoring_basis` is decided from the rows actually produced, never from the requested
       `purpose`.** `SCORING_BASIS[purpose]` (`"adjusted_excess"` for every `trading` round to date)
       used to be handed back unconditionally; that stopped being safe the day a `trading` round could
       hold an invested-value card, so this function now reads back which basis the data itself
       carries and reports that instead. `SCORING_BASIS[purpose]` remains what `savings`/`roth` report
       (neither exposure basis applies to an IRR/CAGR board -- see `LeaderboardData.scoring_basis`'s
       own docstring) and what a `trading` round with no rows at all falls back to, for lack of any
       data to decide from.

    :data:`PROVENANCE_WINDOW` (`"13f-legal"`) is excluded from every aggregate (`windows_run`,
    `eligible`, `median_excess`, `worst_excess`, `hit_rate`, `mean_capital_exposure`, `total_trades`)
    but its `per_window` cell is still populated for every agent that ran it, so a caller can display
    it greyed rather than lose it.

    Raises `ValueError` when `rank_by` is not one of :data:`RANK_BY_CHOICES` -- the API layer turns
    this into a 422. Raises :class:`RoundNotFoundError` when `round_id` does not exist.
    """
    if rank_by not in RANK_BY_CHOICES:
        raise ValueError(f"rank_by must be one of {RANK_BY_CHOICES}, got {rank_by!r}")
    if purpose not in _PURPOSE_VALUES:
        raise ValueError(f"purpose must be one of {sorted(_PURPOSE_VALUES)}, got {purpose!r}")

    by_window = load_round_scored_runs(round_id, rounds_root)
    windows_order = list(by_window)

    window_facts: list[WindowFacts] = []
    for window in windows_order:
        agents = by_window[window]
        if not agents:
            continue
        benchmark_return = _shared_window_fact(
            {a.benchmark_return for a in agents.values()}, window, "benchmark_return"
        )
        sessions = _shared_window_fact(
            {a.sessions for a in agents.values()}, window, "sessions"
        )
        window_facts.append(
            WindowFacts(
                window=window,
                sessions=sessions,
                benchmark_return=benchmark_return,
                provenance_constrained=(window == PROVENANCE_WINDOW),
            )
        )

    # Filter to the requested purpose *before* ranking, not after: a rank is a position within a
    # field, so ranking the whole field and then hiding rows would leave the survivors holding ranks
    # that count competitors the reader cannot see.
    #
    # A round result file predating the `purpose` field validates with the model default, `trading`,
    # which is what every card in every committed round actually is -- so this filter changes nothing
    # about how the existing rounds read.
    agent_ids_all = sorted(
        {
            aid
            for agents in by_window.values()
            for aid, run in agents.items()
            if run.purpose == purpose
        }
    )

    # Decision 1 (see the docstring above): a field never ranks two exposure bases as one table.
    agent_basis: dict[str, ExposureBasis] = {
        aid: _agent_exposure_basis(aid, windows_order, by_window) for aid in agent_ids_all
    }
    basis_counts = Counter(agent_basis.values())
    dominant_basis: ExposureBasis | None
    excluded_agent_ids: list[str]
    if len(basis_counts) <= 1:
        dominant_basis = next(iter(basis_counts), None)
        excluded_agent_ids = []
    else:
        # A named function rather than a lambda: `dominant_basis` is already `... | None` from
        # the branch above, and mypy uses the assignment target as inference context for
        # `max`, which pushed that `None` into the lambda's parameter and made the
        # `basis_counts[...]` lookup unsound. An explicit parameter type breaks that chain.
        def _basis_rank(basis: ExposureBasis) -> tuple[int, bool]:
            return (basis_counts[basis], basis == "entry-notional")

        # Bound to its own non-optional local first: `dominant_basis` is `... | None` from the
        # branch above, and mypy takes the assignment target as `max`'s inference context, so
        # assigning straight into it pushes `None` back into the key function's parameter.
        ranked: ExposureBasis = max(basis_counts, key=_basis_rank)
        dominant_basis = ranked
        excluded_agent_ids = sorted(
            aid for aid in agent_ids_all if agent_basis[aid] != dominant_basis
        )
    agent_ids = [aid for aid in agent_ids_all if agent_basis.get(aid) == dominant_basis]

    # Decision 2: refuse, rather than answer with a ratio whose denominator carries no information.
    exposure_ratio_refused = rank_by == "excess-per-exposure" and dominant_basis == "invested-value"

    row_data: tuple[LeaderboardRowData, ...] = ()
    if agent_ids and not exposure_ratio_refused:
        rows: list[_RowAccumulator] = []
        for agent_id in agent_ids:
            per_window: dict[str, LeaderboardCellData] = {}
            display_name = agent_id
            discipline = ""
            for window in windows_order:
                run = by_window[window].get(agent_id)
                if run is None:
                    continue
                cell = _scored_run_to_cell(run)
                per_window[window] = cell
                if display_name == agent_id:
                    display_name = run.display_name
                    discipline = run.discipline

            counted = [c for w, c in per_window.items() if w != PROVENANCE_WINDOW]
            windows_run = len(counted)
            eligible = windows_run >= MIN_ELIGIBLE_MAIN_WINDOWS

            excess_values = [c.excess for c in counted if c.excess is not None]
            median_excess = statistics.median(excess_values) if excess_values else None
            worst_excess = min(excess_values) if excess_values else None
            hit_rate = (
                sum(1 for v in excess_values if v > 0) / len(excess_values)
                if excess_values
                else None
            )

            exposures = [c.capital_exposure for c in counted if c.capital_exposure is not None]
            mean_capital_exposure = statistics.fmean(exposures) if exposures else None

            total_trades = sum(c.trades for c in counted)

            ratio_values = [
                c.excess / Decimal(str(c.capital_exposure))
                for c in counted
                if c.excess is not None
                and c.capital_exposure is not None
                and Decimal(str(c.capital_exposure)) >= MIN_EXPOSURE_FOR_RATIO
            ]
            median_excess_per_exposure = statistics.median(ratio_values) if ratio_values else None

            rows.append(
                _RowAccumulator(
                    agent_id=agent_id,
                    display_name=display_name,
                    discipline=discipline,
                    per_window=per_window,
                    windows_run=windows_run,
                    eligible=eligible,
                    median_excess=median_excess,
                    worst_excess=worst_excess,
                    hit_rate=hit_rate,
                    mean_capital_exposure=mean_capital_exposure,
                    total_trades=total_trades,
                    median_excess_per_exposure=median_excess_per_exposure,
                )
            )

        # The four rankers return different types (`Decimal`, `float`, and `None` for a cell
        # with no value), and the sort below only ever sees the non-`None` subset because the
        # comprehension filters first. `Any` is what that heterogeneity honestly is; the point
        # of the annotation is that these lambdas stop being *untyped* functions.
        key_fn: Callable[[_RowAccumulator], Any] = {
            "median": lambda r: r.median_excess,
            "worst": lambda r: r.worst_excess,
            "hit-rate": lambda r: r.hit_rate,
            "excess-per-exposure": lambda r: r.median_excess_per_exposure,
        }[rank_by]

        eligible_rows = [r for r in rows if r.eligible]
        ineligible_rows = [r for r in rows if not r.eligible]

        with_value = sorted(
            (r for r in eligible_rows if key_fn(r) is not None), key=key_fn, reverse=True
        )
        without_value = sorted(
            (r for r in eligible_rows if key_fn(r) is None), key=lambda r: r.agent_id
        )
        ordered = with_value + without_value + sorted(ineligible_rows, key=lambda r: r.agent_id)

        row_data = tuple(
            LeaderboardRowData(
                rank=rank,
                agent_id=r.agent_id,
                display_name=r.display_name,
                discipline=r.discipline,
                windows_run=r.windows_run,
                eligible=r.eligible,
                median_excess=r.median_excess,
                worst_excess=r.worst_excess,
                hit_rate=r.hit_rate,
                mean_capital_exposure=r.mean_capital_exposure,
                total_trades=r.total_trades,
                per_window=r.per_window,
            )
            for rank, r in enumerate(ordered, start=1)
        )

    # Named whenever something real is not being shown -- see `LeaderboardData.unscored_reason`'s own
    # docstring for the three causes and why a reader should act differently on each.
    unscored_reason: str | None = None
    if not agent_ids_all:
        if purpose == Purpose.TRADING.value:
            unscored_reason = f"No {purpose} cards produced results in round {round_id}."
        else:
            unscored_reason = (
                f"No round has run any {purpose}-purpose card yet, so there is nothing to rank here. "
                f"This is an absence of measurement, not a poor result. {purpose} is scored on "
                f"{SCORING_BASIS[purpose]}, which the regime-window matrix this board reads does not "
                "compute -- see strategy-program/THREE-PURPOSES-PLAN.md section 7."
            )
    elif exposure_ratio_refused:
        unscored_reason = (
            "rank_by='excess-per-exposure' is refused here: every scored "
            f"{purpose} card in round {round_id} is on the invested-value exposure basis (an "
            "allocation or ladder book keeps every sleeve open every session, so its "
            "capital_exposure sits near 1.0 for the life of the run regardless of the strategy). "
            "Dividing excess by a near-constant denominator would not measure what this column's "
            "name promises. Use rank_by='median', 'worst' or 'hit-rate' instead -- all three rank "
            "on plain excess, which is defined for this basis."
        )
    elif excluded_agent_ids:
        excluded_basis = "invested-value" if dominant_basis == "entry-notional" else "entry-notional"
        unscored_reason = (
            f"{len(excluded_agent_ids)} {purpose} card(s) on the {excluded_basis} exposure basis "
            "were excluded from this table so its ranks stay one ordering, not two different "
            f"orderings printed in one column: {', '.join(excluded_agent_ids)}. This board ranks "
            f"the {dominant_basis} field ({len(agent_ids)} card(s)); the excluded card(s) need a "
            "separate request once this API offers a split view."
        )

    if purpose == Purpose.TRADING.value:
        if dominant_basis == "entry-notional":
            scoring_basis = "adjusted_excess"
        elif dominant_basis == "invested-value":
            scoring_basis = "excess"
        else:
            scoring_basis = SCORING_BASIS[purpose]
    else:
        scoring_basis = SCORING_BASIS[purpose]

    return LeaderboardData(
        round_id=round_id,
        rank_by=rank_by,
        windows=tuple(window_facts),
        rows=row_data,
        purpose=purpose,
        scoring_basis=scoring_basis,
        unscored_reason=unscored_reason,
    )


# ---------------------------------------------------------------------------
# Agent detail
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgentDetailData:
    round_id: str
    agent_id: str
    display_name: str
    card: StrategyCard
    windows: tuple[WindowMetrics, ...]


def _round_results_for_detail(
    round_id: str, rounds_root: Path | None = None
) -> tuple[dict[str, dict[str, AgentResult]], dict[str, CardShape]]:
    """``({window: {agent_id: AgentResult}}, {agent_id: shape})`` -- every stock-picking run file in
    the round, plus a record of every run file that was skipped and what shape it actually was.

    **Why this exists rather than a call to `load_round_results`.** That function validates *every*
    file in the round as an `AgentResult`, so a single allocation or ladder run file raises and the
    request dies -- taking the round's stock-picking cards down with it. Measured on `r15-2026-08`:
    one `ladder-qld-schd` run file made the agent-detail endpoint return `500` for **all three** of
    the round's cards, including the two that parse perfectly well. The round's leaderboard was
    unaffected the whole time, because `build_leaderboard` reads `load_round_scored_runs`, which
    understands all three shapes -- so the failure looked like a per-card data problem rather than a
    reader that cannot see two thirds of the round.

    Shape is decided by :func:`_card_shape` from the payload's own keys -- the same detector
    :func:`parse_scored_run` dispatches on. A second, independently-written detector here would be
    two answers to "what shape is this file" that can drift apart, which is the thing that detector's
    own docstring exists to prevent.

    A file that is neither readable as an `AgentResult` nor recognisable as one of the three known
    shapes still raises. That is a malformed file, not a shape this view has not caught up with, and
    it is worth surfacing rather than swallowing -- the same stance `load_round_results` takes.
    """
    root = rounds_root if rounds_root is not None else ROUNDS_ROOT
    results_dir = root / round_id / "results"
    if not results_dir.is_dir():
        raise RoundNotFoundError(round_id)

    out: dict[str, dict[str, AgentResult]] = {}
    other_shapes: dict[str, CardShape] = {}
    for window in _discover_windows(results_dir):
        runs_dir = results_dir / window / "runs"
        agents: dict[str, AgentResult] = {}
        for path in sorted(runs_dir.glob("*.json")):
            raw = path.read_text(encoding="utf-8")
            card_payload = json.loads(raw).get("card")
            if not isinstance(card_payload, dict):
                raise UnrecognisedCardShapeError(())
            shape = _card_shape(card_payload)
            if shape != "stock-picking":
                agent_id = card_payload.get("agent_id")
                if isinstance(agent_id, str):
                    other_shapes[agent_id] = shape
                continue
            result = AgentResult.model_validate_json(raw)
            agents[result.card.agent_id] = result
        out[window] = agents
    return out, other_shapes


def build_agent_detail(
    round_id: str, agent_id: str, rounds_root: Path | None = None
) -> AgentDetailData:
    """`/api/competition/rounds/{round_id}/agents/{agent_id}`'s data.

    `card` comes from the run file's own embedded `StrategyCard` (the first window found, in
    :func:`_discover_windows` order) -- **not** from the current library -- so a round's report
    always reflects the card as it actually ran, even if the library's copy of it has since changed.

    Raises :class:`RoundNotFoundError` when `round_id` does not exist,
    :class:`AgentNotFoundError` when `agent_id` has no run file in any of `round_id`'s windows, and
    :class:`AgentShapeUnsupportedError` when it has one whose card is an allocation or ladder shape
    this view cannot render -- which is a different fact from either of the other two and is reported
    as its own.
    """
    by_window, other_shapes = _round_results_for_detail(round_id, rounds_root)
    windows_order = list(by_window)

    windows: list[WindowMetrics] = []
    card: StrategyCard | None = None
    display_name = agent_id
    for window in windows_order:
        result = by_window[window].get(agent_id)
        if result is None:
            continue
        if card is None:
            card = result.card
            display_name = result.card.display_name
        windows.append(compute_window(result, window))

    if card is None:
        # Order matters: an agent that ran in a shape this view cannot read must never be reported
        # as one that did not run. See `AgentShapeUnsupportedError`.
        if agent_id in other_shapes:
            raise AgentShapeUnsupportedError(round_id, agent_id, other_shapes[agent_id])
        raise AgentNotFoundError(round_id, agent_id)

    return AgentDetailData(
        round_id=round_id,
        agent_id=agent_id,
        display_name=display_name,
        card=card,
        windows=tuple(windows),
    )

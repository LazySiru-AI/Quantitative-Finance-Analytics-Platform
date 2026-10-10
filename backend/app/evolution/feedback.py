"""Leaderboard -> findings -> the next generation's seed population.

This module is the loop's after-action review. It never runs a card and never computes a return; it
only reads what `app.tournament.results` already computed for a round and turns that into three
things a supervisor can act on without itself having an opinion:

* :func:`read_standings` -- copies `app.tournament.results.build_leaderboard`'s own numbers into
  `app.evolution.models.Standing`, plus a holdout figure computed the same way but from windows
  selection never saw. Never recomputes a metric the leaderboard already owns -- see that function's
  own docstring for why "copy, never recompute" is load-bearing, not a style preference.
* :func:`derive_findings` -- fixed, deterministic rules over a set of standings, never a model and
  never prose generation. Two passes over the same standings produce the same findings, which is what
  lets a finding be trusted as a measurement rather than read as an opinion.
* :func:`select_elites` -- which candidates breed into the next generation, and which requires no
  more expertise than `median_excess` and a tie-break the caller cannot second-guess.
* :func:`ledger_entries_for` -- turns a generation's standings into `app.evolution.ledger.LedgerEntry`
  rows, reading real closed-trade counts off the round's own run files so the ledger's binomial test
  has an honest denominator.

**Why `derive_findings` cannot see per-window numbers.** `Standing` deliberately carries only the
leaderboard's own aggregate columns (median, worst, hit rate) -- see its own docstring. That is
correct for every finding except `kind="regime"`, which by definition needs to compare windows against
each other. Rather than widen `Standing` (out of this module's scope -- `models.py` is owned
elsewhere) or give `derive_findings` a `Settings`/`round_id` it would use to read the round tree a
second time (which would make two calls able to disagree about what "the same standings" saw),
:func:`field_window_medians` is a second, explicit reader a caller can run once per generation and
pass into `derive_findings` as `window_medians`. Omitted, the regime finding still fires -- it just
says plainly that it has nothing to name a window with, rather than silently disappearing from the
tuple `derive_findings` returns.
"""

from __future__ import annotations

import datetime as dt
import json
import statistics
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.backtest.scan import binomial_p_value
from app.config import Settings
from app.evolution.ledger import LedgerEntry
from app.evolution.models import Finding, GenerationOutcome, Genome, LoopConfig, Standing
from app.evolution.promotion import gate_median_excess
from app.tournament.purposes import Purpose
from app.tournament.results import build_leaderboard, load_round_scored_runs
from app.tournament.scoring import MIN_CLOSED_TRADES_FOR_P_VALUE, NULL_WIN_PROBABILITY

__all__ = [
    "derive_findings",
    "field_window_medians",
    "ledger_entries_for",
    "read_standings",
    "select_elites",
]

_NUMERIC_TYPES = (int, float, Decimal)

#: Below this many candidates in a generation, an elite-mean-vs-field-mean comparison is noise, not
#: signal -- four is the smallest sample where "the elites skew one way" is more likely to reflect
#: something about the trait than about which two of two candidates happened to be called elite.
_MIN_CANDIDATES_FOR_PARAMETER_FINDING = 4


# ---------------------------------------------------------------------------
# read_standings
# ---------------------------------------------------------------------------


def _holdout_medians(
    rounds_root: Path,
    round_id: str,
    windows: Sequence[str],
    genomes: Mapping[str, Genome],
    purpose: Purpose,
) -> dict[str, Decimal]:
    """Median `excess` per agent, over `windows` only -- `Standing.holdout_median_excess`'s source.

    Reads `load_round_scored_runs` directly rather than `build_leaderboard`: the leaderboard's own
    aggregation is exactly what must *not* run over a holdout window (its eligibility gate, its
    ranking, its `unscored_reason` bookkeeping all exist to serve the selection board), so this
    function reimplements only the one statistic it needs -- a per-agent median of `ScoredRun.excess`
    -- rather than asking the leaderboard to compute one over a window set it was never meant to see.
    """
    if not windows:
        return {}
    by_window = load_round_scored_runs(round_id, rounds_root)
    per_agent: dict[str, list[Decimal]] = {}
    for window in windows:
        for agent_id, run in by_window.get(window, {}).items():
            if agent_id not in genomes or run.purpose != str(purpose) or run.excess is None:
                continue
            per_agent.setdefault(agent_id, []).append(run.excess)
    return {agent_id: statistics.median(values) for agent_id, values in per_agent.items()}


def _adjusted_value(run: object) -> Decimal | None:
    """`corrected_return - capital_exposure * benchmark_return` for one run, or `None`.

    **Why this is computed here rather than through `ScoredRun.adjusted_excess`.** That method raises
    `ExposureBasisError` for any run whose `exposure_basis` is not `"entry-notional"`, which excludes
    every allocation card -- and the loop breeds allocation cards in their own lanes, so going through
    it would leave half the search uncorrected. The refusal is not arbitrary and is worth restating
    before working around it: `results.py` gates on the card *shape* rather than on whether
    `capital_exposure` looks usable, precisely because a reader that gated on the data would still
    reach a confident wrong number through the `exposure` fallback (session presence, which sits near
    1.0 for an allocation book whose every sleeve is open every session -- `DEFECTS.md` D2).

    So this function addresses that hazard head-on instead of inheriting the blanket refusal: it reads
    `capital_exposure` **only**, and returns `None` when it is absent. It never touches `exposure`.
    Measured across 824 runs, `capital_exposure` is populated on every one of them -- 404/404 for
    `invested-value` (range 0.815-0.997) and 420/420 for `entry-notional` (range 0.000-0.629) -- so
    the `None` branch is a guard against a future gap, not a routine path.

    **The two bases are never compared with each other.** A rules card's 0.19 and an allocation card's
    0.95 mean different things, and averaging or ranking across them would be meaningless. That does
    not arise here: `build_leaderboard` already refuses to rank a field mixing the two bases, and
    `EVOLUTION-LOOP.md` section 1 makes every generation a single lane of a single card shape for
    exactly that reason. The correction is therefore always applied within one basis.

    **What it buys.** `excess` alone is very nearly a function of which way the market went (measured
    r = -0.978 between a window's median benchmark and its median excess). Subtracting
    `capital_exposure * benchmark_return` asks the question `PROTOCOL.md` section 4 wrote it for:
    whether the *rules* beat being invested the same fraction of the time. In `gfc` a card holding 19%
    of capital and losing 29.69% posts `excess = +26.53%` against a -56.23% benchmark, and
    `adjusted = -19.01%` -- the first says it beat the market, the second says it did worse than a
    passive position of its own size, and the second is the true one.
    """
    benchmark = getattr(run, "benchmark_return", None)
    exposure = getattr(run, "capital_exposure", None)
    corrected = getattr(run, "corrected_return", None)
    if benchmark is None or exposure is None or corrected is None:
        return None
    # `capital_exposure` is a `float` on `ScoredRun` while `benchmark_return`/`corrected_return` are
    # `Decimal`, and `float * Decimal` is a `TypeError` rather than a coercion. Converted through
    # `str` rather than `Decimal(float)` so the value is the decimal the float *displays* as, not the
    # binary expansion behind it -- the same reason every other Decimal boundary in this codebase
    # goes through a string.
    exposure_dec = exposure if isinstance(exposure, Decimal) else Decimal(str(exposure))
    # Annotated rather than returned straight through: `benchmark` reaches here as `Any`, so a
    # bare return asserts this function's `-> Decimal | None` without anything checking it.
    adjusted: Decimal = corrected - exposure_dec * benchmark
    return adjusted


def _adjusted_medians(
    rounds_root: Path,
    round_id: str,
    windows: Sequence[str],
    genomes: Mapping[str, Genome],
    purpose: Purpose,
) -> dict[str, Decimal]:
    """Median exposure-adjusted excess per agent over `windows` -- the same shape as
    :func:`_holdout_medians`, and computed the same way, over :func:`_adjusted_value`."""
    if not windows:
        return {}
    by_window = load_round_scored_runs(round_id, rounds_root)
    per_agent: dict[str, list[Decimal]] = {}
    for window in windows:
        for agent_id, run in by_window.get(window, {}).items():
            if agent_id not in genomes or run.purpose != str(purpose):
                continue
            value = _adjusted_value(run)
            if value is not None:
                per_agent.setdefault(agent_id, []).append(value)
    return {agent_id: statistics.median(v) for agent_id, v in per_agent.items()}


def read_standings(
    *,
    round_id: str,
    purpose: Purpose,
    genomes: Mapping[str, Genome],
    config: LoopConfig,
    settings: Settings,
    selection_windows: Sequence[str],
    holdout_windows: Sequence[str],
    rounds_root: Path | None = None,
    holdout_round_id: str | None = None,
) -> tuple[Standing, ...]:
    """The loop's view of one round: `app.tournament.results.build_leaderboard`'s own rows, copied
    into `Standing`, plus a holdout figure the board never saw.

    `rounds_root` defaults to `settings.rounds_dir` (the human programme's committed, git-tracked
    round history) but a running loop writes its own generations under `loop_root(settings) /
    "rounds"` instead -- `data/rounds/` cannot hold one directory per generation of an endless search.
    Passing `rounds_root` explicitly is what lets a caller (or a test) point this function at either
    tree without this module hardcoding which one a given call means.

    A row whose `agent_id` is not a key of `genomes` is skipped, not raised on -- a round can hold a
    human-authored card that happens to share the round with this generation's candidates, and that
    card has no genome for this loop to reason about breeding from.

    `RoundNotFoundError` (from `build_leaderboard`) propagates unchanged: this function does not
    decide what an absent round means, the supervisor does.

    **`holdout_round_id`, when given, names a *separate* round directory that holds only the holdout
    windows' run files -- `app.evolution.loop` mints one alongside `round_id` specifically so
    `build_leaderboard`'s eligibility/ranking machinery never sees a field mixing windows selection
    chose with windows it did not (see that module's own defect writeup: `build_leaderboard` has no
    window filter, so a holdout run written into the *same* round as selection was silently ranked
    alongside it, putting the holdout inside the very median it exists to check). When given, the
    holdout figure is `build_leaderboard(holdout_round_id, ...)`'s own `median_excess`, copied exactly
    like the selection figure -- "copy the leaderboard's numbers, never recompute them" now holds for
    both. `None` (the default) keeps this function's original behaviour: a holdout figure recomputed
    directly from `round_id`'s own run files over `holdout_windows`, for callers that still run
    selection and holdout windows into one round.

    **Holdout windows that also appear in `selection_windows` are dropped from the holdout
    computation, not double-counted -- only when `holdout_round_id` is not given.** `LoopConfig` does
    not forbid the two sequences overlapping; if a caller's configuration does overlap them, treating
    a selection window as a holdout window too would let selection quietly influence the number that
    exists specifically to check it, so selection wins the conflict and the overlapping window
    contributes to neither `Standing`'s rank nor its holdout figure being conflated with the other.
    This exclusion does not apply when `holdout_round_id` is given: that round holds only the windows
    it was actually run on, decided by the caller before this function is ever called.
    """
    root = rounds_root if rounds_root is not None else settings.rounds_dir
    board = build_leaderboard(round_id, rank_by=config.rank_by, rounds_root=root, purpose=str(purpose))

    if holdout_round_id is not None:
        holdout_board = build_leaderboard(
            holdout_round_id, rank_by=config.rank_by, rounds_root=root, purpose=str(purpose)
        )
        holdout_medians = {
            row.agent_id: row.median_excess
            for row in holdout_board.rows
            if row.agent_id in genomes and row.median_excess is not None
        }
    else:
        holdout_only = tuple(w for w in holdout_windows if w not in selection_windows)
        holdout_medians = _holdout_medians(root, round_id, holdout_only, genomes, purpose)

    # The exposure-corrected figures, alongside the uncorrected ones rather than replacing them --
    # every generation already on disk was scored on plain `excess`, and PROTOCOL.md section 2's
    # integrity rule forbids restating a finished round's numbers under a metric it was not run on.
    adjusted_medians = _adjusted_medians(root, round_id, tuple(selection_windows), genomes, purpose)
    adjusted_holdout = _adjusted_medians(
        root,
        holdout_round_id if holdout_round_id is not None else round_id,
        tuple(holdout_windows)
        if holdout_round_id is not None
        else tuple(w for w in holdout_windows if w not in selection_windows),
        genomes,
        purpose,
    )

    standings: list[Standing] = []
    for row in board.rows:
        genome = genomes.get(row.agent_id)
        if genome is None:
            continue
        standings.append(
            Standing(
                genome_id=genome.genome_id,
                agent_id=row.agent_id,
                display_name=row.display_name,
                rank=row.rank,
                eligible=row.eligible,
                windows_run=row.windows_run,
                median_excess=row.median_excess,
                worst_excess=row.worst_excess,
                hit_rate=row.hit_rate,
                total_trades=row.total_trades,
                holdout_median_excess=holdout_medians.get(row.agent_id),
                median_adjusted_excess=adjusted_medians.get(row.agent_id),
                holdout_median_adjusted_excess=adjusted_holdout.get(row.agent_id),
            )
        )
    return tuple(standings)


def field_window_medians(
    round_id: str,
    *,
    purpose: Purpose,
    genomes: Mapping[str, Genome],
    windows: Sequence[str],
    settings: Settings,
    rounds_root: Path | None = None,
) -> dict[str, Decimal]:
    """Median `excess` across every genome in `genomes` that ran, per window in `windows`.

    Feeds `derive_findings`'s `window_medians` parameter -- see this module's own docstring for why
    that has to be a second reader rather than data folded into `Standing`. Callers pass
    `selection_windows` here, never `holdout_windows`: this function has no opinion about which is
    which, so the caller's choice of `windows` is what keeps a holdout regime out of a finding whose
    entire job is to describe the selection field.
    """
    root = rounds_root if rounds_root is not None else settings.rounds_dir
    by_window = load_round_scored_runs(round_id, root)
    out: dict[str, Decimal] = {}
    for window in windows:
        values = [
            run.excess
            for agent_id, run in by_window.get(window, {}).items()
            if agent_id in genomes and run.purpose == str(purpose) and run.excess is not None
        ]
        if values:
            out[window] = statistics.median(values)
    return out


# ---------------------------------------------------------------------------
# select_elites
# ---------------------------------------------------------------------------


def select_elites(
    standings: Sequence[Standing], genomes: Mapping[str, Genome], *, config: LoopConfig
) -> tuple[Genome, ...]:
    """The top `config.elite_count` standings by `median_excess`, among eligible standings only.

    Ties broken by `worst_excess` (descending -- the generalisation test, `PROTOCOL.md` §4's own
    tiebreak) then `genome_id` (ascending), so the order is fully determined by the data and never by
    dict or set iteration order. Ineligible standings never enter the comparison at all: an
    ineligible card's `median_excess` was measured over too few windows to mean what a full-field
    median means, so ranking it alongside eligible cards -- even at the bottom -- would still be
    treating an incomparable number as comparable. If fewer than `elite_count` standings are
    eligible, this returns fewer than `elite_count` genomes; it never pads the difference with an
    ineligible one.
    """
    eligible = [s for s in standings if s.eligible and s.median_excess is not None]

    def _key(standing: Standing) -> tuple[Decimal, Decimal, str]:
        worst = standing.worst_excess if standing.worst_excess is not None else Decimal("-Infinity")
        assert standing.median_excess is not None  # filtered above
        return (-standing.median_excess, -worst, standing.genome_id)

    ordered = sorted(eligible, key=_key)
    chosen = ordered[: config.elite_count]
    return tuple(genomes[s.genome_id] for s in chosen if s.genome_id in genomes)


# ---------------------------------------------------------------------------
# derive_findings
# ---------------------------------------------------------------------------


def _signs_differ(a: Decimal, b: Decimal) -> bool:
    """`True` only when `a` and `b` are strictly on opposite sides of zero. Zero itself is not "a
    sign" to flip against -- a candidate landing at exactly breakeven on either side has not
    demonstrated a reversal, it has demonstrated nothing."""
    if a == 0 or b == 0:
        return False
    return (a > 0) != (b > 0)


def _winner(standings: Sequence[Standing]) -> Standing | None:
    eligible = [s for s in standings if s.eligible]
    if not eligible:
        return None
    return min(eligible, key=lambda s: (s.rank, s.genome_id))


def _pp(value: Decimal | None) -> str:
    """A median excess as a human-readable figure in percentage points.

    Every excess in this module is stored as a *fraction* and every margin it is compared against --
    `LoopConfig.promotion_margin_pp`, `NOISE_FLOOR_PP` -- is in percentage points. Findings are prose
    a person reads, and interpolating the raw `Decimal` printed 29 significant digits of an unlabelled
    fraction: "led the field with median excess 0.07894444217223358327652806180". Beside it, in the
    same sentence, `drop_pp` was already being converted and labelled correctly, so one summary
    carried both conventions at once.

    This is the same units mismatch that made `clears_gate` compare a fraction against a margin in
    points, and that printed a promotion reason describing a card failing the gate it had just
    passed. It is a *display* fault in all three places -- no stored figure was ever wrong -- which
    is exactly why it survived: the numbers the loop acts on never went through here.

    `evidence` dictionaries keep `str(value)` at full precision on purpose; this is only for the
    sentence.
    """
    if value is None:
        return "not measured"
    return f"{value * 100:+.2f}pp"


def _winner_finding(winner: Standing) -> Finding:
    return Finding(
        kind="winner",
        summary=(
            f"{winner.display_name} ({winner.agent_id}) led the field with median excess "
            f"{_pp(winner.median_excess)}."
        ),
        evidence={
            "genome_id": winner.genome_id,
            "agent_id": winner.agent_id,
            "rank": winner.rank,
            "median_excess": None if winner.median_excess is None else str(winner.median_excess),
            "holdout_median_excess": (
                None
                if winner.holdout_median_excess is None
                else str(winner.holdout_median_excess)
            ),
        },
    )


def _failure_findings(standings: Sequence[Standing]) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    for standing in sorted(standings, key=lambda s: s.genome_id):
        reasons: list[str] = []
        if not standing.eligible:
            reasons.append(
                f"ran {standing.windows_run} eligible-counted window(s), below the eligibility floor"
            )
        if standing.total_trades == 0:
            reasons.append("took zero trades")
        if not reasons:
            continue
        findings.append(
            Finding(
                kind="failure",
                summary=f"{standing.display_name} ({standing.agent_id}): {'; '.join(reasons)}.",
                evidence={
                    "genome_id": standing.genome_id,
                    "agent_id": standing.agent_id,
                    "windows_run": standing.windows_run,
                    "total_trades": standing.total_trades,
                    "eligible": standing.eligible,
                },
            )
        )
    return tuple(findings)


def _holdout_finding(winner: Standing, config: LoopConfig) -> Finding:
    median = winner.median_excess
    holdout = winner.holdout_median_excess
    if median is None or holdout is None:
        return Finding(
            kind="holdout",
            summary=(
                f"No holdout comparison is available for {winner.agent_id}: its selection or "
                "holdout median excess was not measured."
            ),
            evidence={
                "genome_id": winner.genome_id,
                "median_excess": None if median is None else str(median),
                "holdout_median_excess": None if holdout is None else str(holdout),
            },
        )

    drop_pp = (median - holdout) * 100
    sign_flip = _signs_differ(median, holdout)
    contradicts = sign_flip or drop_pp > config.promotion_margin_pp
    summary = (
        f"{winner.agent_id}'s holdout median ({_pp(holdout)}) "
        f"{'contradicts' if contradicts else 'is consistent with'} its selection median "
        f"({_pp(median)}): "
        f"drop = {drop_pp:.2f}pp against a {config.promotion_margin_pp}pp margin"
        f"{' with a sign flip' if sign_flip else ''}."
    )
    return Finding(
        kind="holdout",
        summary=summary,
        evidence={
            "genome_id": winner.genome_id,
            "median_excess": str(median),
            "holdout_median_excess": str(holdout),
            "drop_pp": str(drop_pp),
            "sign_flip": sign_flip,
            "contradicts": contradicts,
        },
    )


def _gate_finding(standings: Sequence[Standing], config: LoopConfig) -> Finding:
    # `gate_median_excess`, not `s.median_excess` -- this must select the same figure
    # `app.evolution.promotion.clears_gate` compares against the margin (the exposure-adjusted median
    # when it is populated, the uncorrected one otherwise), imported from that module rather than
    # reimplemented, so the two cannot drift apart again. They used to: this used to count clearers on
    # raw `median_excess` alone while `clears_gate` preferred the adjusted figure, so a candidate could
    # be reported here as having cleared a bar `clears_gate` then refused -- see `clears_gate`'s own
    # docstring, which already states "the two must agree or the panel will report a candidate as
    # having cleared a bar that this function then refuses."
    eligible = [s for s in standings if s.eligible and gate_median_excess(s) is not None]
    # `> `, not `>=`: `app.evolution.promotion.clears_gate` is strictly greater than the margin,
    # and a candidate sitting exactly on it must not be counted here as having cleared a bar that
    # promotion will then refuse. The `is not None` is redundant at runtime (the comprehension
    # above already filtered) and present so the type checker can see the same thing.
    cleared = [
        s
        for s in eligible
        if (median := gate_median_excess(s)) is not None and median * 100 > config.promotion_margin_pp
    ]
    summary = (
        f"{len(cleared)} of {len(eligible)} eligible candidate(s) cleared the "
        f"{config.promotion_margin_pp}pp promotion margin this generation."
    )
    return Finding(
        kind="gate",
        summary=summary,
        evidence={
            "cleared": len(cleared),
            "eligible": len(eligible),
            "margin_pp": str(config.promotion_margin_pp),
            "cleared_genome_ids": tuple(sorted(s.genome_id for s in cleared)),
        },
    )


def _universe_finding(
    standings: Sequence[Standing], genomes: Mapping[str, Genome], elites: Sequence[Genome]
) -> Finding:
    elite_ids = {genome.genome_id for genome in elites}
    elite_universe: set[str] = set()
    also_ran_universe: set[str] = set()
    for standing in standings:
        genome = genomes.get(standing.genome_id)
        if genome is None:
            continue
        bucket = elite_universe if genome.genome_id in elite_ids else also_ran_universe
        bucket |= set(genome.universe)

    elite_only = tuple(sorted(elite_universe - also_ran_universe))
    also_ran_only = tuple(sorted(also_ran_universe - elite_universe))
    return Finding(
        kind="universe",
        summary=(
            f"{len(elite_only)} ticker(s) appear only in elite universes and "
            f"{len(also_ran_only)} only in also-ran universes."
        ),
        evidence={"elite_only": elite_only, "also_ran_only": also_ran_only},
    )


def _numeric_trait_values(genomes: Sequence[Genome], trait: str) -> list[float] | None:
    """`[float(g.traits[trait]) for g in genomes]`, or `None` if `trait` is missing from any genome
    or is not a numeric value (`bool` excluded -- it is a `int` subclass but not a free parameter's
    numeric value) on any of them."""
    values: list[float] = []
    for genome in genomes:
        value = genome.traits.get(trait)
        if isinstance(value, bool) or not isinstance(value, _NUMERIC_TYPES):
            return None
        values.append(float(value))
    return values


def _parameter_findings(
    standings: Sequence[Standing], genomes: Mapping[str, Genome], elites: Sequence[Genome]
) -> tuple[Finding, ...]:
    generation_genomes = [genomes[s.genome_id] for s in standings if s.genome_id in genomes]

    if len(generation_genomes) < _MIN_CANDIDATES_FOR_PARAMETER_FINDING:
        return (
            Finding(
                kind="parameter",
                summary=(
                    f"Only {len(generation_genomes)} candidate(s) ran this generation, below the "
                    f"{_MIN_CANDIDATES_FOR_PARAMETER_FINDING}-candidate floor an elite-vs-field "
                    "comparison needs to be more than noise; no per-trait number is reported."
                ),
                evidence={"candidates": len(generation_genomes)},
            ),
        )

    common_traits = (
        set.intersection(*(set(g.traits) for g in generation_genomes)) if generation_genomes else set()
    )
    elite_ids = {genome.genome_id for genome in elites}
    elite_genomes = [g for g in generation_genomes if g.genome_id in elite_ids]

    findings: list[Finding] = []
    for trait in sorted(common_traits):
        field_values = _numeric_trait_values(generation_genomes, trait)
        if field_values is None:
            continue
        field_mean = statistics.fmean(field_values)
        evidence: dict[str, object] = {
            "trait": trait,
            "field_mean": field_mean,
            "field_n": len(field_values),
        }
        elite_values = _numeric_trait_values(elite_genomes, trait) if elite_genomes else None
        if elite_values:
            elite_mean = statistics.fmean(elite_values)
            evidence["elite_mean"] = elite_mean
            evidence["elite_n"] = len(elite_values)
            summary = (
                f"Trait {trait!r}: elite mean {elite_mean:.6g} vs field mean {field_mean:.6g} "
                f"across {len(field_values)} candidate(s)."
            )
        else:
            summary = (
                f"Trait {trait!r}: field mean {field_mean:.6g} across {len(field_values)} "
                "candidate(s); no eligible elite to compare against."
            )
        findings.append(Finding(kind="parameter", summary=summary, evidence=evidence))

    if not findings:
        findings.append(
            Finding(
                kind="parameter",
                summary="No trait is both numeric and present in every candidate this generation.",
                evidence={"candidates": len(generation_genomes)},
            )
        )
    return tuple(findings)


def _regime_finding(
    window_medians: Mapping[str, Decimal] | None, selection_windows: Sequence[str]
) -> Finding:
    if not window_medians:
        return Finding(
            kind="regime",
            summary=(
                "No per-window field data was supplied to this call, so the worst regime cannot be "
                "named. Call app.evolution.feedback.field_window_medians and pass its result as "
                "derive_findings(window_medians=...) to enable this finding."
            ),
            evidence={},
        )
    relevant = {w: m for w, m in window_medians.items() if w in selection_windows}
    if not relevant:
        return Finding(
            kind="regime",
            summary="None of the supplied window medians overlap this generation's selection windows.",
            evidence={},
        )
    worst_window = min(relevant, key=lambda w: (relevant[w], w))
    return Finding(
        kind="regime",
        summary=(
            f"The field's worst median excess this generation was in {worst_window!r} "
            f"({relevant[worst_window]})."
        ),
        evidence={
            "worst_window": worst_window,
            "worst_median_excess": str(relevant[worst_window]),
            "by_window": {w: str(v) for w, v in sorted(relevant.items())},
        },
    )


def _rank_by_value(standing: Standing, rank_by: str) -> Decimal | float | None:
    """The one number `rank_by` actually names on `standing`, as far as `Standing` can say it.

    `Standing` carries three of `app.tournament.results.RANK_BY_CHOICES`' four aggregates by name
    (`"median"` -> `median_excess`, `"worst"` -> `worst_excess`, `"hit-rate"` -> `hit_rate`) -- it does
    not carry a fourth, `"excess-per-exposure"`, at all (see `Standing`'s own docstring: it copies only
    the leaderboard's own aggregate columns, and that one is not among them). Rather than report
    nothing for that one choice, this falls back to `median_excess`, the one figure every rank_by mode
    still carries regardless of what it ranks by -- an approximation, not the exact quantity, and
    `_goal_finding` names `rank_by` in its own evidence so a reader can see which case this was.
    """
    if rank_by == "median":
        return standing.median_excess
    if rank_by == "worst":
        return standing.worst_excess
    if rank_by == "hit-rate":
        return standing.hit_rate
    return standing.median_excess


def _goal_finding(
    standings: Sequence[Standing],
    genomes: Mapping[str, Genome],
    elites: Sequence[Genome],
    config: LoopConfig,
    previous_generation: GenerationOutcome | None,
) -> Finding:
    """Reports on `config.goal` the only way a deterministic loop honestly can.

    Not by claiming the goal was "achieved" -- no model reads `goal`'s prose, and neither does this
    function; see `LoopConfig.goal`'s own docstring for why that claim would be dishonest regardless of
    how good the numbers look. Instead: the one number `config.rank_by` names for this generation's
    best eligible candidate (`_rank_by_value`), compared against the *same lane*'s previous generation
    (`previous_generation`, threaded in by `app.evolution.loop._run`'s per-lane `last_outcome_by_lane`
    -- lanes interleave, so "the previous generation" and "the previous generation in this lane" are
    almost never the same one), against `config.promotion_margin_pp` as the noise floor -- the same
    number `PROTOCOL.md` s7 measured ordering noise against, reused here rather than a second,
    invented threshold. Also reports whether `config.focus_symbols` -- the machine-readable half of
    the same stated intent -- actually shows up in this generation's own elite universes, since a goal
    about "semis" that produced elites holding none of the requested tickers is worth surfacing
    however the numbers moved.

    **Emitted as `kind="gate"`.** `FindingKind` (`app.evolution.models`, fixed and not editable by this
    change) has no member named for "how the stated objective moved between generations", and among
    the seven it does have, `"gate"` is the closest fit: it already means "did a generation-level
    number clear or fail to clear a margin", which is exactly this finding's shape -- just measured
    against the previous generation's own number instead of a fixed constant. `"winner"` was
    considered and rejected: it already reports this generation's best candidate on its own, unrelated
    terms (rank and holdout), and a second, differently-shaped finding also called `"winner"` would
    leave a reader unable to tell the two apart by `kind` alone.
    """
    evidence: dict[str, Any] = {
        "goal": config.goal,
        "focus_symbols": list(config.focus_symbols),
        "rank_by": config.rank_by,
    }
    goal_clause = f'the stated goal ("{config.goal}")' if config.goal else "no stated goal"

    elite_universe: set[str] = set()
    for genome in elites:
        elite_universe |= set(genome.universe)
    evidence["focus_symbols_in_elite_universes"] = sorted(
        symbol for symbol in config.focus_symbols if symbol in elite_universe
    )
    evidence["focus_symbols_missing_from_elite_universes"] = sorted(
        symbol for symbol in config.focus_symbols if symbol not in elite_universe
    )

    winner = _winner(standings)
    if winner is None:
        evidence["current_value"] = None
        return Finding(
            kind="gate",
            summary=(
                f"No eligible candidate this generation to measure against {goal_clause}; "
                f"{config.rank_by!r} is unmeasured."
            ),
            evidence=evidence,
        )

    current_value = _rank_by_value(winner, config.rank_by)
    evidence["current_genome_id"] = winner.genome_id
    evidence["current_value"] = None if current_value is None else str(current_value)

    if previous_generation is None:
        return Finding(
            kind="gate",
            summary=(
                f"This lane's first measured generation for {goal_clause}: {config.rank_by!r} = "
                f"{current_value}, with no prior generation in this lane yet to compare against."
            ),
            evidence=evidence,
        )

    evidence["previous_generation"] = previous_generation.generation
    previous_winner = _winner(previous_generation.standings)
    previous_value = None if previous_winner is None else _rank_by_value(previous_winner, config.rank_by)
    evidence["previous_genome_id"] = None if previous_winner is None else previous_winner.genome_id
    evidence["previous_value"] = None if previous_value is None else str(previous_value)

    if current_value is None or previous_value is None:
        return Finding(
            kind="gate",
            summary=(
                f"{goal_clause}: {config.rank_by!r} cannot be compared between this generation and "
                f"generation {previous_generation.generation} in this lane -- one side has no "
                "measured eligible candidate."
            ),
            evidence=evidence,
        )

    delta_pp = (Decimal(str(current_value)) - Decimal(str(previous_value))) * 100
    evidence["delta_pp"] = str(delta_pp)
    if abs(delta_pp) <= config.promotion_margin_pp:
        direction = "is within the noise floor of"
    elif delta_pp > 0:
        direction = "improved over"
    else:
        direction = "worsened from"
    evidence["direction"] = direction

    return Finding(
        kind="gate",
        summary=(
            f"{goal_clause}: {config.rank_by!r} = {current_value} this generation {direction} "
            f"{previous_value} in generation {previous_generation.generation} (same lane), a "
            f"{delta_pp:.2f}pp move against a {config.promotion_margin_pp}pp noise floor -- a "
            "measured direction, not a claim the goal was achieved."
        ),
        evidence=evidence,
    )


def derive_findings(
    standings: Sequence[Standing],
    *,
    config: LoopConfig,
    purpose: Purpose,
    selection_windows: Sequence[str],
    holdout_windows: Sequence[str],
    genomes: Mapping[str, Genome],
    window_medians: Mapping[str, Decimal] | None = None,
    previous_generation: GenerationOutcome | None = None,
) -> tuple[Finding, ...]:
    """Fixed, deterministic rules over `standings` -- no model, no prose generation. Two calls with
    identical arguments return identical findings, because every step below is a pure function of its
    inputs: sorted iteration wherever order could otherwise depend on dict or set hashing, and no
    randomness or wall-clock read anywhere in this function or the helpers it calls.

    `purpose` and `holdout_windows` are accepted for a stable, self-documenting call signature (a
    caller assembling this call already has both in hand from the same generation) even though only
    `selection_windows` is read directly here -- `holdout_windows`' influence already happened, inside
    `read_standings`, by the time `Standing.holdout_median_excess` reached this function.

    `window_medians` is optional and, when supplied, should be `field_window_medians`' result over
    the same `selection_windows` -- see this module's own docstring for why `Standing` cannot carry
    that data itself. Its absence degrades exactly one finding (`kind="regime"`); every other kind is
    unaffected.

    `previous_generation` is optional -- a trailing keyword with a `None` default, so an existing
    caller built before this parameter was added keeps working unmodified -- and should be this same
    lane's own most recently succeeded `GenerationOutcome`, never merely the generation immediately
    prior (see `app.evolution.loop._execute_generation`'s own docstring on why the two are usually
    different generations once a loop cycles through more than one lane). Its absence degrades exactly
    one finding (`kind="gate"`'s goal-comparison variant, appended last): the finding still fires, it
    just reports that this lane has nothing yet to compare against.

    Returns `()` for an empty `standings` -- a generation with nothing to report has nothing to say,
    and an empty tuple is a caller's cue to skip rather than misread a placeholder as a real finding.
    """
    if not standings:
        return ()

    findings: list[Finding] = []

    winner = _winner(standings)
    if winner is not None:
        findings.append(_winner_finding(winner))
        findings.append(_holdout_finding(winner, config))

    findings.extend(_failure_findings(standings))
    findings.append(_gate_finding(standings, config))

    elites = select_elites(standings, genomes, config=config)
    findings.append(_universe_finding(standings, genomes, elites))
    findings.extend(_parameter_findings(standings, genomes, elites))
    findings.append(_regime_finding(window_medians, selection_windows))
    findings.append(_goal_finding(standings, genomes, elites, config, previous_generation))

    return tuple(findings)


# ---------------------------------------------------------------------------
# ledger_entries_for
# ---------------------------------------------------------------------------


def _trade_counts(
    rounds_root: Path, round_id: str, agent_id: str, windows: Sequence[str]
) -> tuple[int, int]:
    """`(closed_trades, wins)` for `agent_id`, summed across `windows`' run files.

    Reads each window's raw run-file JSON directly rather than through `load_round_scored_runs`
    (`ScoredRun.trades` is only a count -- the win/loss record a binomial test needs is not on it) or
    `load_round_results` (parses `StrategyCard`-shaped payloads only; an allocation-shaped candidate's
    run file would raise). Every one of the three card shapes this loop can produce shares the same
    `RealisedTrade` schema for its `"trades"` list (`app.tournament.results`' own `ScoredRun` section
    documents this: the three result types are "field-for-field identical except for the type of
    card"), so reading `payload["trades"]` and `payload["card"]["agent_id"]` needs no shape dispatch
    at all -- the one field this function's caller does not know (and does not need to) is the card's
    shape.

    A `"win"` is `pnl > 0`, strictly, matching `app.tournament.scoring._p_value`'s own convention (a
    breakeven trade is not a win). One run file is expected per `(agent_id, window)`; the loop stops
    scanning a window's `runs/` directory as soon as it finds that agent's file.
    """
    closed = 0
    wins = 0
    for window in windows:
        runs_dir = rounds_root / round_id / "results" / window / "runs"
        if not runs_dir.is_dir():
            continue
        for path in sorted(runs_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("card", {}).get("agent_id") != agent_id:
                continue
            trades = payload.get("trades", [])
            closed += len(trades)
            wins += sum(1 for trade in trades if Decimal(str(trade["pnl"])) > 0)
            break
    return closed, wins


def ledger_entries_for(
    standings: Sequence[Standing],
    *,
    round_id: str,
    purpose: Purpose,
    generation: int,
    selection_windows: Sequence[str],
    settings: Settings,
    rounds_root: Path | None = None,
) -> tuple[LedgerEntry, ...]:
    """One `LedgerEntry` per standing, ready for `app.evolution.ledger.Ledger.record`.

    `closed_trades`/`wins` are read from the round's own run files (:func:`_trade_counts`), never
    approximated from `Standing.hit_rate` (a *per-window* win rate -- the fraction of windows with
    positive excess -- which answers a different question from "what fraction of individual trades
    were winners" and cannot substitute for it). `p_value` is computed with the exact function
    `app.tournament.scoring` uses (`app.backtest.scan.binomial_p_value`, imported unmodified) against
    that module's own `NULL_WIN_PROBABILITY` and `MIN_CLOSED_TRADES_FOR_P_VALUE` floor -- `None` below
    the floor, exactly as `app.tournament.scoring._p_value` reports it, so a card ledgered here and a
    card scored by a human round's tournament are held to the identical bar.

    `rounds_root` defaults to `settings.rounds_dir`, overridable for the same reason
    :func:`read_standings` accepts it -- a running loop's own generations live under
    `loop_root(settings) / "rounds"`, not the human programme's committed tree.
    """
    root = rounds_root if rounds_root is not None else settings.rounds_dir
    recorded_at = dt.datetime.now(dt.UTC)
    windows = tuple(selection_windows)

    entries: list[LedgerEntry] = []
    for standing in standings:
        closed, wins = _trade_counts(root, round_id, standing.agent_id, windows)
        p_value = (
            binomial_p_value(wins, closed, NULL_WIN_PROBABILITY)
            if closed >= MIN_CLOSED_TRADES_FOR_P_VALUE
            else None
        )
        entries.append(
            LedgerEntry(
                genome_id=standing.genome_id,
                generation=generation,
                purpose=str(purpose),
                round_id=round_id,
                windows=windows,
                median_excess=standing.median_excess,
                holdout_median_excess=standing.holdout_median_excess,
                closed_trades=closed,
                wins=wins,
                p_value=p_value,
                recorded_at=recorded_at,
            )
        )
    return tuple(entries)

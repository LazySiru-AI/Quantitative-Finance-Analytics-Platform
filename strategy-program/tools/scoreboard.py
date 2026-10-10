"""Every candidate strategy against every window it ran, in one machine-readable scoreboard.

Twelve rounds have run across five window matrices, and no single artifact shows a strategy's whole
record -- every existing document (``REPORT.md``, ``SELECTION.md``, a round's own ``scorecard.json``)
covers one round against one matrix. This module reads every stored run file under
``data/rounds/*/results/`` and assembles the union: one cell per ``(round, window, agent_id)`` that
was actually run, plus a per-strategy, per-matrix roll-up, plus the benchmark's own performance as
rows in the same table -- not just a column beside each card.

    cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/scoreboard.py

Run as a plain script, not ``-m`` -- ``strategy-program`` is not a legal Python package name (the
hyphen). Writes ``data/rounds/SCOREBOARD.json`` (the contract) and ``data/rounds/SCOREBOARD.txt`` (a
readable dump).

**This module reads stored JSON only.** It never imports ``app.tournament.runner`` and never opens
the bar store -- see ``strategy-program/DEFECTS.md`` D3: a concurrent reader against the single
DuckDB file can corrupt a live run silently, and nothing here has any reason to be live.

**Which rounds have results.** Rounds 1-5 and 11 ran tournaments and have a ``results/`` tree.
Rounds 6-10, 12 and 13 are *selection* rounds that scored over those frozen matrices without running
anything new -- they have no ``results/`` directory at all, and their absence is not an error, just
nothing to discover.

**Three correctness rules, inherited from `score.py` and DEFECTS.md, applied without exception here:**

* **Never read `AgentResult.total_return`** (D1) -- every return in this module's output is
  `score.corrected_return`.
* **Never read `AgentResult.exposure`** (D2) -- every exposure figure is `score.capital_exposure`.
* **`r11`'s cells are recovered by differencing cumulative runs, not read per-window** (D5). Each run
  file under ``r11-2026-08/results/<tag>/runs/`` is a *cumulative* tournament from the live period's
  start through that tag's boundary, not an independent sub-window -- reading it as if it were one
  would silently reset a card's book at every boundary (D5's reproduction: a card fully invested
  throughout reports two entire sub-windows at 0% exposure and zero trades). `round11.live_cells`
  already implements the fix; it is imported and called, not rewritten, for the metric it is
  responsible for (`adjusted_excess`). The sibling fields this scoreboard also reports per cell
  (`corrected_return`, `benchmark_return`, `capital_exposure`, `sessions`, `trades`) are recovered
  here by the same documented differencing formulas, and a self-check asserts the two computations of
  `adjusted_excess` (`round11.live_cells`'s and this module's) agree on every cell.

**`results-independent-INVALID/` is excluded entirely.** Those are round 11's discarded first
instrument -- six *independent* sub-window tournaments, each starting from a flat book, which biased
the whole field toward high-turnover cards (DEFECTS.md D5). They are not read, not counted, and not
included in any total; see `EXCLUDED_TREES` and the ``exclusions`` key in the written JSON.

**The benchmark anchor.** Every ``benchmark_return`` in this file's output is the trading engine's own
figure: SPY bought and held over exactly the sessions a card's run actually traded
(`AgentResult.benchmark_return`). A bar-store recomputation of the same calendar period gives a
different number -- rounds 8-12 all had to disclose which anchor produced a given figure, and the gap
runs up to roughly 0.12 annualized points. This module never recomputes a benchmark from the bar store
(doing so would mean touching the store at all, which the D3 prohibition above already rules out); it
only ever reports the engine's own figure, and says so explicitly in the JSON's ``benchmark_anchor``
key rather than leaving a reader to assume it.

**Annualizing.** Round 5's 27 windows range from 6 months to 10 years -- comparing raw
`adjusted_excess` across its rungs compares different units. Every cell in this module's output
carries both the raw, whole-window figure and, where the window's length makes it meaningful,
`score.annualized_adjusted_excess` (and its two components). Round 11's six sub-windows are all the
same length (21-22 sessions) and round 11's own tooling deliberately does not annualize them (see
`round11.live_cells`'s docstring: annualizing a three-week window "multiplies every figure by twelve
for no gain in comparability") -- this module follows that precedent and reports `None` for round 11's
annualized fields rather than inventing a number nothing else in the programme reports.
"""

from __future__ import annotations

import json
import statistics
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_TOOLS_DIR))

import round10  # noqa: E402
import round11  # noqa: E402
import score  # noqa: E402

from app.tournament.models import AgentResult  # noqa: E402

__all__ = [
    "ROUND_MATRICES",
    "ROUND_TAG_ON_DISK",
    "build_cell",
    "load_round_cells",
    "main",
    "r11_diff_cells",
]

_REPO_ROOT = _TOOLS_DIR.parent.parent
ROUNDS_ROOT = _REPO_ROOT / "data" / "rounds"
OUTPUT_JSON = ROUNDS_ROOT / "SCOREBOARD.json"
OUTPUT_TXT = ROUNDS_ROOT / "SCOREBOARD.txt"

#: Every run file in this programme is named ``r1-<agent_id>.json`` regardless of which round wrote
#: it -- confirmed by inspecting one run file from each of the six results trees below. `score.py`'s
#: own `_discover_round_tag` would reach the same answer per round; it is hard-coded here because it
#: is one constant true across the whole programme, not six separate auto-detections.
ROUND_TAG_ON_DISK = "r1"

#: `strategy-program/DEFECTS.md` D5: round 11's first instrument cut the live period into six
#: *independent* tournaments, each resetting the book at every boundary. The output is kept on disk
#: as evidence but excluded from every count and every cell in this scoreboard.
EXCLUDED_TREES: tuple[str, ...] = ("r11-2026-08/results-independent-INVALID",)

#: Round 1's own gate, transcribed from `score.MIN_RANKED_MAIN_WINDOWS`'s docstring ("round 1's was 3
#: of 5") -- `score.py` never defines a `Matrix` for round 1 because round 1 predates the multi-matrix
#: refactor (round 4 was the first to need a second one). The five main regime windows below are
#: exactly what round 1's own `results/` tree has, less the special-case `13f-legal` provenance
#: window (a sixth directory, included in every cell but not in this matrix's roll-up gate, the same
#: way `score._discover_window_tags` treats `13f-legal` as an extra column for round 2).
R1_MATRIX = score.Matrix("r1", ("bear-2022", "bull-2024", "covid", "gfc", "recent"), 3)

#: Which `score.Matrix` each results tree is scored against. Round 3 reused round 2's eight regime
#: windows for a wider card universe (`data/rounds/r3-2026-08/results/` has exactly
#: `score.MAIN_WINDOW_TAGS`, no more, no less) rather than defining its own -- see `score.R2_MATRIX`.
ROUND_MATRICES: dict[str, score.Matrix] = {
    "r1-2026-08": R1_MATRIX,
    "r2-2026-08": score.R2_MATRIX,
    "r3-2026-08": score.R2_MATRIX,
    "r4-2026-08": score.R4_MATRIX,
    "r5-2026-08": score.R5_MATRIX,
    "r11-2026-08": score.R11_MATRIX,
}

#: Rounds 6-10, 12 and 13 ran no tournament -- confirmed by `ls data/rounds/*/` having no `results/`
#: subdirectory for any of them. Listed here, not discovered, so a reader of this file sees the
#: negative claim stated rather than inferred from an empty loop.
NO_TOURNAMENT_ROUNDS: tuple[str, ...] = (
    "r6-2026-08",
    "r7-2026-08",
    "r8-2026-08",
    "r9-2026-08",
    "r10-2026-08",
    "r12-2026-08",
    "r13-2026-08",
)

BENCHMARK_ANCHOR_NOTE = (
    "benchmark_return is the trading engine's own figure: SPY bought and held over exactly the "
    "sessions a card's run actually traded (AgentResult.benchmark_return). A bar-store "
    "recomputation of the same calendar period gives a different number -- rounds 8-12 all had to "
    "disclose which anchor produced a given figure, and the gap runs up to roughly 0.12 annualized "
    "points. This scoreboard never recomputes a benchmark from the bar store; it only reports the "
    "engine's own figure."
)


def _num(value: Decimal | float | int | None) -> float | int | None:
    """`Decimal`/`float`/`int`/`None` -> a JSON-safe number, never a string. `Decimal` round-trips
    through `float` -- acceptable here because every consumer of this file is a report, not a further
    computation that needs exact arithmetic; `score.py` itself keeps `Decimal` internally and only
    stringifies at its own JSON boundary for the same reason."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def build_cell(round_dir: str, window: str, in_matrix: bool, result: AgentResult) -> dict[str, Any]:
    """One ``(round, window, agent_id)`` row, built entirely from `score.py`'s vetted accessors --
    never from `result.total_return` or `result.exposure` directly (DEFECTS.md D1, D2)."""
    return {
        "round": round_dir,
        "window": window,
        "in_matrix": in_matrix,
        "agent_id": result.card.agent_id,
        "display_name": result.card.display_name,
        "discipline": str(result.card.discipline),
        "sessions": result.sessions,
        "trades": len(result.trades),
        "corrected_return": _num(score.corrected_return(result)),
        "benchmark_return": _num(result.benchmark_return),
        "excess": _num(score.excess(result)),
        "adjusted_excess": _num(score.adjusted_excess(result)),
        "capital_exposure": _num(score.capital_exposure(result)),
        "max_drawdown": _num(result.max_drawdown),
        "realised_pnl": _num(score.realised_pnl(result)),
        "window_years": _num(score.window_years(result)),
        "annualized_return": _num(score.annualized_return(result)),
        "annualized_benchmark": _num(score.annualized_benchmark(result)),
        "annualized_adjusted_excess": _num(score.annualized_adjusted_excess(result)),
    }


def _discover_window_tags(results_root: Path) -> list[str]:
    """Every subdirectory of ``results_root`` with a ``runs/`` folder, sorted -- deliberately not
    `score._discover_window_tags`, which orders main tags first and needs a `Matrix` to do it; this
    scoreboard wants every window discovered regardless of which matrix it belongs to, so a card run
    outside the round's core gate (round 1's ``13f-legal``) still gets a cell."""
    if not results_root.is_dir():
        return []
    return sorted(p.name for p in results_root.iterdir() if p.is_dir() and (p / "runs").is_dir())


def _load_agent_results(
    runs_dir: Path,
) -> tuple[dict[str, AgentResult], list[tuple[str, str]]]:
    """Every run file in ``runs_dir``, individually guarded -- one malformed file is recorded and
    skipped rather than aborting the whole scoreboard, unlike `score.load_results`, which is correct
    for its own use (scoring one round's already-reconciled tree) but too strict for a tool sweeping
    every round's tree at once, including ones this module has never read before.

    Returns ``({agent_id: AgentResult}, [(path, reason), ...])``.
    """
    agents: dict[str, AgentResult] = {}
    skipped: list[tuple[str, str]] = []
    if not runs_dir.is_dir():
        return agents, skipped
    for path in sorted(runs_dir.glob(f"{ROUND_TAG_ON_DISK}-*.json")):
        try:
            result = AgentResult.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:  # reported via `skipped`, not swallowed
            skipped.append((str(path), f"{type(exc).__name__}: {exc}"))
            continue
        agents[result.card.agent_id] = result
    return agents, skipped


def r11_diff_cells(
    r11_results: Path,
) -> tuple[dict[str, dict[str, dict[str, Any]]], list[str]]:
    """``{agent_id: {live_tag: cell}}`` for round 11, recovered by differencing the cumulative runs
    -- see the module docstring's D5 paragraph.

    Each ``cell`` carries the same shape `build_cell` would, less `display_name`/`discipline` (added
    by the caller) and `max_drawdown`/annualized fields, which are not recoverable by differencing --
    `max_drawdown` is path-dependent over the *whole* cumulative equity curve, not a level or a sum a
    later run's figure minus an earlier one's would isolate to one sub-period, and the sub-windows are
    deliberately not annualized (`round11.live_cells`'s own docstring: same reasoning followed here).

    ``adjusted_excess`` for each cell comes from `round11.live_cells` itself -- imported and called,
    not recomputed -- with a self-check against this function's own differencing of the same inputs;
    a disagreement raises rather than silently reports one of the two.

    Returns ``(cells, incomplete_agents)`` where ``incomplete_agents`` lists every `round10.FIELD`
    agent missing at least one of the six sub-windows -- `round11.live_cells` silently excludes such a
    card entirely (its own comment: "a shortfall is a lost card, not a coverage rule"), and this
    scoreboard surfaces that omission by name instead of leaving a reader to notice a missing row.
    """
    canonical = round11.live_cells()
    by_window = score.load_results(r11_results, ROUND_TAG_ON_DISK, list(score.R11_LIVE_TAGS))

    out: dict[str, dict[str, dict[str, Any]]] = {}
    incomplete: list[str] = []
    for agent_id in sorted(round10.FIELD):
        runs = [by_window.get(tag, {}).get(agent_id) for tag in score.R11_LIVE_TAGS]
        if any(r is None for r in runs):
            incomplete.append(agent_id)
            continue

        prev_equity = runs[0].starting_equity
        prev_bench = Decimal(0)
        prev_notional = Decimal(0)
        prev_sessions = 0
        prev_trades = 0
        for tag, r in zip(score.R11_LIVE_TAGS, runs, strict=True):
            d_sessions = r.sessions - prev_sessions
            if d_sessions <= 0 or prev_equity <= 0:
                break
            ret = r.ending_equity / prev_equity - 1
            bench = (1 + r.benchmark_return) / (1 + prev_bench) - 1
            notional = Decimal(str(r.capital_exposure)) * Decimal(r.sessions) * runs[0].starting_equity
            exposure = (notional - prev_notional) / (Decimal(d_sessions) * prev_equity)
            d_trades = len(r.trades) - prev_trades
            adjusted = ret - exposure * bench

            want = canonical.get(agent_id, {}).get(tag)
            if want is not None and abs(want - adjusted) > Decimal("1e-9"):
                raise AssertionError(
                    f"r11_diff_cells disagrees with round11.live_cells for {agent_id}/{tag}: "
                    f"{adjusted} vs {want}"
                )

            out.setdefault(agent_id, {})[tag] = {
                "sessions": d_sessions,
                "trades": d_trades,
                "corrected_return": _num(ret),
                "benchmark_return": _num(bench),
                "excess": _num(ret - bench),
                "adjusted_excess": _num(want if want is not None else adjusted),
                "capital_exposure": _num(exposure),
                "max_drawdown": None,
                "realised_pnl": None,
                "window_years": None,
                "annualized_return": None,
                "annualized_benchmark": None,
                "annualized_adjusted_excess": None,
            }
            prev_equity, prev_bench = r.ending_equity, r.benchmark_return
            prev_notional, prev_sessions, prev_trades = notional, r.sessions, len(r.trades)
    return out, incomplete


def _card_score_rollup(cs: score.CardScore, matrix: score.Matrix) -> dict[str, Any]:
    """`CardScore` -> the roll-up fields the scoreboard's contract promises, plus round 5's
    per-horizon annualized breakdown when the matrix has one (`Matrix.min_ranked_per_horizon`)."""
    out: dict[str, Any] = {
        "matrix": matrix.name,
        "ranked": cs.ranked,
        "n_windows_run": cs.n_windows_run,
        "n_windows_eligible": cs.n_windows_eligible,
        "median_adjusted_excess": _num(cs.median_adjusted_excess),
        "worst_adjusted_excess": _num(cs.worst_adjusted_excess),
        "best_adjusted_excess": _num(cs.best_adjusted_excess),
        "hit_rate": cs.hit_rate,
        "iqr": _num(cs.iqr),
        "total_trades": cs.total_trades,
        "mean_exposure": cs.mean_exposure,
        "worst_drawdown": _num(cs.worst_drawdown),
        "total_realised_pnl": _num(cs.total_realised_pnl),
        "median_excess_per_exposure": _num(cs.median_excess_per_exposure),
        "incommensurable_exposure": cs.incommensurable_exposure,
        "notes": list(cs.notes),
    }
    if matrix.min_ranked_per_horizon is not None:
        out["median_adjusted_excess_note"] = (
            "unannualized median across windows of very different length (6 months to 10 years) -- "
            "not comparable across rungs; see per_horizon_ladder/per_horizon_bear for the "
            "annualized, horizon-matched roll-up this matrix should actually be read from."
        )
        out["per_horizon_ladder"] = {
            h: {
                "n_windows": hs.n_windows,
                "gate_cleared": hs.gate_cleared,
                "median_annualized_adjusted_excess": _num(hs.median_annualized_adjusted_excess),
                "worst_annualized_adjusted_excess": _num(hs.worst_annualized_adjusted_excess),
                "hit_rate": hs.hit_rate,
            }
            for h, hs in cs.per_horizon_ladder.items()
        }
        out["per_horizon_bear"] = {
            h: {
                "n_windows": hs.n_windows,
                "gate_cleared": hs.gate_cleared,
                "median_annualized_adjusted_excess": _num(hs.median_annualized_adjusted_excess),
                "worst_annualized_adjusted_excess": _num(hs.worst_annualized_adjusted_excess),
                "hit_rate": hs.hit_rate,
            }
            for h, hs in cs.per_horizon_bear.items()
        }
    return out


def load_round_cells(round_dir: str) -> dict[str, Any]:
    """Every cell, every benchmark row, and every strategy's roll-up for one round's results tree.

    Rounds 1-5 go through `score.score_round` for the roll-up (reused, not reimplemented) and this
    module's own `build_cell` for the raw per-cell figures, because `score.WindowCell` does not carry
    `benchmark_return`, `capital_exposure`, `sessions` or `max_drawdown` -- it was built for a
    markdown table, not this contract. Round 11 is entirely separate (`r11_diff_cells`); see the
    module docstring's D5 paragraph for why its raw per-window `AgentResult` cannot be used directly.
    """
    results_root = ROUNDS_ROOT / round_dir / "results"
    matrix = ROUND_MATRICES[round_dir]

    if round_dir == "r11-2026-08":
        diffed, incomplete = r11_diff_cells(results_root)
        # Also load display_name/discipline once per agent, from the raw (cumulative) run files --
        # those fields don't change across sub-windows, and there's no reason to duplicate the
        # differencing machinery just to read a label.
        raw_by_window, skipped = _load_agent_results(results_root / score.R11_LIVE_TAGS[0] / "runs")
        cells: list[dict[str, Any]] = []
        for agent_id, per_tag in diffed.items():
            label = raw_by_window.get(agent_id)
            display_name = label.card.display_name if label else None
            discipline = str(label.card.discipline) if label else None
            for tag, cell in per_tag.items():
                cells.append(
                    {
                        "round": round_dir,
                        "window": tag,
                        "in_matrix": True,
                        "agent_id": agent_id,
                        "display_name": display_name,
                        "discipline": discipline,
                        **cell,
                    }
                )

        strategies: dict[str, Any] = {}
        for agent_id, per_tag in diffed.items():
            values = [c["adjusted_excess"] for c in per_tag.values() if c["adjusted_excess"] is not None]
            hits = sum(1 for v in values if v > 0)
            strategies[agent_id] = {
                "matrix": matrix.name,
                "ranked": len(per_tag) >= matrix.min_ranked,
                "n_windows_run": len(per_tag),
                "n_windows_eligible": len(score.R11_LIVE_TAGS),
                "median_adjusted_excess": statistics.median(values) if values else None,
                "worst_adjusted_excess": min(values) if values else None,
                "best_adjusted_excess": max(values) if values else None,
                "hit_rate": (hits / len(values)) if values else None,
                "total_trades": sum(c["trades"] for c in per_tag.values()),
                "notes": (
                    ["differenced from cumulative sub-window runs (DEFECTS.md D5); not annualized"]
                ),
            }
        for agent_id in incomplete:
            strategies[agent_id] = {
                "matrix": matrix.name,
                "ranked": False,
                "n_windows_run": 0,
                "n_windows_eligible": len(score.R11_LIVE_TAGS),
                "median_adjusted_excess": None,
                "worst_adjusted_excess": None,
                "best_adjusted_excess": None,
                "hit_rate": None,
                "total_trades": None,
                "notes": ["missing at least one of the six live sub-windows; excluded by round11.live_cells"],
            }

        benchmark_rows = []
        for tag in score.R11_LIVE_TAGS:
            # Every agent's differenced benchmark for a given tag is identical (same window, same
            # SPY figure); take it from whichever ranked agent has it.
            bench = next(
                (per_tag[tag]["benchmark_return"] for per_tag in diffed.values() if tag in per_tag),
                None,
            )
            sessions = next(
                (per_tag[tag]["sessions"] for per_tag in diffed.values() if tag in per_tag), None
            )
            benchmark_rows.append(
                {
                    "round": round_dir,
                    "window": tag,
                    "benchmark_return": bench,
                    "annualized_benchmark": None,
                    "sessions": sessions,
                    "window_years": None,
                    "note": "differenced from cumulative runs (DEFECTS.md D5), same as every card's cell",
                }
            )

        return {
            "window_tags": list(score.R11_LIVE_TAGS),
            "cells": cells,
            "strategies": strategies,
            "benchmark_rows": benchmark_rows,
            "skipped": [{"path": p, "reason": r} for p, r in skipped],
            "incomplete_agents": incomplete,
        }

    # Rounds 1-5.
    window_tags = _discover_window_tags(results_root)
    by_window: dict[str, dict[str, AgentResult]] = {}
    skipped = []
    for tag in window_tags:
        agents, tag_skipped = _load_agent_results(results_root / tag / "runs")
        by_window[tag] = agents
        skipped.extend(tag_skipped)

    cells = []
    for tag in window_tags:
        in_matrix = tag in matrix.tags
        for result in by_window[tag].values():
            cells.append(build_cell(round_dir, tag, in_matrix, result))

    eligibility_path = None
    for candidate in (results_root / "eligibility.json", ROUNDS_ROOT / round_dir / "eligibility.json"):
        if candidate.is_file():
            eligibility_path = candidate
            break
    eligibility = score._load_eligibility(eligibility_path) or None

    ranked, unranked, _ = score.score_round(
        results_root,
        ROUND_TAG_ON_DISK,
        eligibility=eligibility,
        window_tags=window_tags,
        matrix=matrix,
    )
    strategies = {cs.agent_id: _card_score_rollup(cs, matrix) for cs in (*ranked, *unranked)}

    benchmark_rows = []
    for tag in window_tags:
        agents = by_window[tag]
        if not agents:
            continue
        sample = next(iter(agents.values()))
        benchmark_rows.append(
            {
                "round": round_dir,
                "window": tag,
                "benchmark_return": _num(sample.benchmark_return),
                "annualized_benchmark": _num(score.annualized_benchmark(sample)),
                "sessions": sample.sessions,
                "window_years": _num(score.window_years(sample)),
                "note": BENCHMARK_ANCHOR_NOTE,
            }
        )

    return {
        "window_tags": window_tags,
        "cells": cells,
        "strategies": strategies,
        "benchmark_rows": benchmark_rows,
        "skipped": [{"path": p, "reason": r} for p, r in skipped],
        "incomplete_agents": [],
    }


def _matrix_meta(round_dir: str, matrix: score.Matrix) -> dict[str, Any]:
    out: dict[str, Any] = {
        "round": round_dir,
        "matrix_name": matrix.name,
        "tags": list(matrix.tags),
        "min_ranked": matrix.min_ranked,
    }
    if matrix.min_ranked_per_horizon is not None:
        out["min_ranked_per_horizon"] = matrix.min_ranked_per_horizon
        out["horizon_order"] = list(score.HORIZON_ORDER)
        out["ladder_tags"] = list(score.R5_LADDER_TAGS)
        out["bear_tags"] = list(score.R5_BEAR_TAGS)
    return out


def build_scoreboard() -> dict[str, Any]:
    matrices: dict[str, Any] = {}
    all_cells: list[dict[str, Any]] = []
    all_benchmark_rows: list[dict[str, Any]] = []
    strategies: dict[str, Any] = {}
    skipped: list[dict[str, Any]] = []
    incomplete_by_round: dict[str, list[str]] = {}

    for round_dir in ROUND_MATRICES:
        matrix = ROUND_MATRICES[round_dir]
        matrices[round_dir] = _matrix_meta(round_dir, matrix)

        data = load_round_cells(round_dir)
        matrices[round_dir]["window_tags_on_disk"] = data["window_tags"]
        all_cells.extend(data["cells"])
        all_benchmark_rows.extend(data["benchmark_rows"])
        skipped.extend({"round": round_dir, **s} for s in data["skipped"])
        if data["incomplete_agents"]:
            incomplete_by_round[round_dir] = data["incomplete_agents"]

        for agent_id, rollup in data["strategies"].items():
            entry = strategies.setdefault(agent_id, {"agent_id": agent_id, "display_name": None, "matrices": {}})
            entry["matrices"][round_dir] = rollup

    # Backfill display_name from any cell that has one (roll-ups don't all carry it).
    for cell in all_cells:
        entry = strategies.get(cell["agent_id"])
        if entry is not None and entry["display_name"] is None and cell["display_name"]:
            entry["display_name"] = cell["display_name"]

    return {
        "generated_by": "strategy-program/tools/scoreboard.py",
        "benchmark_anchor": BENCHMARK_ANCHOR_NOTE,
        "exclusions": [
            {
                "path": tree,
                "reason": (
                    "DEFECTS.md D5 -- round 11's discarded first instrument: six independent "
                    "sub-window tournaments, each resetting the book at every boundary. Kept on "
                    "disk as evidence, excluded from every count and cell here."
                ),
            }
            for tree in EXCLUDED_TREES
        ],
        "no_tournament_rounds": {
            r: "selection round scored over a frozen matrix; no results/ tree to read"
            for r in NO_TOURNAMENT_ROUNDS
        },
        "matrices": matrices,
        "cells": all_cells,
        "benchmark_rows": all_benchmark_rows,
        "strategies": strategies,
        "skipped": skipped,
        "incomplete_agents_by_round": incomplete_by_round,
        "totals": {
            "cells": len(all_cells),
            "distinct_strategies": len(strategies),
            "distinct_rounds": len(ROUND_MATRICES),
            "skipped": len(skipped),
        },
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:+.2f}%"


def render_txt(board: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("SCOREBOARD -- every candidate strategy against every window it ran")
    lines.append("=" * 78)
    lines.append("")
    lines.append(board["benchmark_anchor"])
    lines.append("")
    lines.append(
        f"totals: {board['totals']['cells']} cells, "
        f"{board['totals']['distinct_strategies']} distinct strategies, "
        f"{board['totals']['distinct_rounds']} rounds with results, "
        f"{board['totals']['skipped']} skipped"
    )
    if board["exclusions"]:
        lines.append("excluded: " + ", ".join(e["path"] for e in board["exclusions"]))
    lines.append("no-tournament rounds: " + ", ".join(sorted(board["no_tournament_rounds"])))
    lines.append("")

    cells_by_round_window: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for c in board["cells"]:
        cells_by_round_window.setdefault((c["round"], c["window"]), {})[c["agent_id"]] = c

    for round_dir, meta in board["matrices"].items():
        window_tags = meta["window_tags_on_disk"]
        if not window_tags:
            continue
        lines.append("-" * 78)
        lines.append(f"{round_dir}  (matrix: {meta['matrix_name']}, gate {meta['min_ranked']})")
        lines.append("-" * 78)

        bench_by_window = {
            b["window"]: b["benchmark_return"]
            for b in board["benchmark_rows"]
            if b["round"] == round_dir
        }
        header = f"{'agent_id':26}" + "".join(f"{t:>13}" for t in window_tags) + f"{'median':>13}"
        lines.append(header)
        lines.append(f"{'SPY (benchmark)':26}" + "".join(
            f"{_pct(bench_by_window.get(t)):>13}" for t in window_tags
        ) + f"{'':>13}")

        agent_ids = sorted(
            {aid for w in window_tags for aid in cells_by_round_window.get((round_dir, w), {})}
        )
        for agent_id in agent_ids:
            row_vals = []
            for tag in window_tags:
                cell = cells_by_round_window.get((round_dir, tag), {}).get(agent_id)
                row_vals.append(cell["adjusted_excess"] if cell else None)
            rollup = board["strategies"].get(agent_id, {}).get("matrices", {}).get(round_dir, {})
            median = rollup.get("median_adjusted_excess")
            lines.append(
                f"{agent_id:26}" + "".join(f"{_pct(v):>13}" for v in row_vals) + f"{_pct(median):>13}"
            )
        lines.append("")

    if board["skipped"]:
        lines.append("-" * 78)
        lines.append("SKIPPED (unreadable) FILES")
        lines.append("-" * 78)
        for s in board["skipped"]:
            lines.append(f"  {s['round']}: {s['path']} -- {s['reason']}")
        lines.append("")

    if board["incomplete_agents_by_round"]:
        lines.append("-" * 78)
        lines.append("INCOMPLETE (missing at least one sub-window)")
        lines.append("-" * 78)
        for round_dir, agents in board["incomplete_agents_by_round"].items():
            lines.append(f"  {round_dir}: {', '.join(agents)}")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    board = build_scoreboard()

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(board, indent=2), encoding="utf-8")
    OUTPUT_TXT.write_text(render_txt(board), encoding="utf-8")

    print(f"cells: {board['totals']['cells']}")
    print(f"distinct strategies: {board['totals']['distinct_strategies']}")
    print(f"rounds with results: {board['totals']['distinct_rounds']}")
    print(f"skipped: {board['totals']['skipped']}")
    for s in board["skipped"]:
        print(f"  SKIPPED {s['round']}: {s['path']} -- {s['reason']}")
    for round_dir, agents in board["incomplete_agents_by_round"].items():
        print(f"  INCOMPLETE {round_dir}: {', '.join(agents)}")
    print(f"wrote {OUTPUT_JSON}")
    print(f"wrote {OUTPUT_TXT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

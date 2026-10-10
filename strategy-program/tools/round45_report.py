"""Verdict tables for round 45 -- persona method cards x cross-persona enhancements -- from its
scorecard.

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round45_report.py

`ROUND-45-PLAN.md` (and `strategy-program/MIX-AND-MATCH-PLAN.md` section 3) pre-registered a decision
rule and a set of predictions before any card ran. This module computes exactly the quantities that
rule names -- each enhancement's marginal (the mean over its bases of arm-minus-own-base median
adjusted excess), a Benjamini-Hochberg pass whose denominator is every one of the round's 14 cells
with each arm contrasted against its OWN base (base cells carry p=None but still count toward m), the
take-profit exit-reason tally for the three `rr5` cells read straight from the run files, and the
exposure/trades table -- and prints them as markdown so `data/rounds/r45-2026-09/REPORT.md` (written
separately, NOT by this tool) quotes numbers this code produced rather than numbers a hand
transcribed. It writes the same content to `data/rounds/r45-2026-09/analysis.json`.

**Why this imports `round34_36_report.py` by file path.** `strategy-program` is not a legal Python
package name (the hyphen), so that module -- which already carries `load_scorecard`, `load_run`,
`cells_of`, `contrast`, `table` and `per_window_table` -- is loaded the same way `round42_report.py`
does: `importlib.util.spec_from_file_location`. Nothing here re-derives what that module already
computes correctly.

**Why this round's BH pass is NOT `round34_36_report.bh_against_reference`.** That helper contrasts
every cell against ONE shared reference. Round 45 has THREE bases (`kim`, `bee`, `creator-b`), and the
plan's decision rule contrasts each arm against its OWN base, not a single reference cell across the
whole round. `bh_m14` below builds the 14 p-values in that shape (`None` for the three base cells,
a per-base contrast p-value for each of the eleven arm cells) and calls
`app.backtest.scan.benjamini_hochberg` on the resulting list of 14 directly, so `m` is exactly the
round's own cell count.

**Not investment advice.** Every figure is a backtest on price-only bars, no dividends. Nothing in
this round is promotable (`trading` purpose, PROTOCOL.md r21 amendment) -- report only. This round is
trading, not hindsight-bounded reporting: every vault draft's corpus has `published = null`, so no
window here is disclosed as pre- or post-dating either persona's claim; see `ROUND-45-PLAN.md`
section 6 for what that costs.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from typing import Any

from app.backtest.scan import benjamini_hochberg

REPO = pathlib.Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "round34_36_report",
    str(pathlib.Path(__file__).resolve().parent / "round34_36_report.py"),
)
assert _spec is not None and _spec.loader is not None
_r34 = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("round34_36_report", _r34)
_spec.loader.exec_module(_r34)

load_scorecard = _r34.load_scorecard
load_run = _r34.load_run
cells_of = _r34.cells_of
contrast = _r34.contrast
table = _r34.table
per_window_table = _r34.per_window_table
FLOOR_PP = _r34.FLOOR_PP
MAIN_WINDOWS = _r34.MAIN_WINDOWS
pp = _r34.pp
fmt = _r34.fmt

ROUND = 45
SCORECARD_PATH = REPO / "data" / "rounds" / f"r{ROUND}-2026-09" / "scorecard.json"
ANALYSIS_PATH = REPO / "data" / "rounds" / f"r{ROUND}-2026-09" / "analysis.json"

#: base -> (base agent_id, {enhancement: arm agent_id}, persona label). The pinned round-45 field --
#: matches `strategy-program/tools/round45.py::BASES` and `arms_for`, restated here (not imported)
#: exactly as `round42_report.py` restates round 42's field rather than importing its authoring tool.
BASES: dict[str, tuple[str, dict[str, str], str]] = {
    "kim": (
        "r45-kim-base",
        {
            "trend100": "r45-kim-trend100",
            "rr5": "r45-kim-rr5",
            "risk1pct": "r45-kim-risk1pct",
            "trim115": "r45-kim-trim115",
        },
        "Creator E (creator-e)",
    ),
    "bee": (
        "r45-bee-base",
        {
            "rr5": "r45-bee-rr5",
            "risk1pct": "r45-bee-risk1pct",
            "trim115": "r45-bee-trim115",
        },
        "Creator C (creator-c)",
    ),
    "wsaj": (
        "r45-wsaj-base",
        {
            "trend100": "r45-wsaj-trend100",
            "rr5": "r45-wsaj-rr5",
            "risk1pct": "r45-wsaj-risk1pct",
            "trim115": "r45-wsaj-trim115",
        },
        "Creator B (wsaj)",
    ),
}

ENHANCEMENTS = ("trend100", "rr5", "risk1pct", "trim115")
ENHANCEMENT_PERSONA = {
    "trend100": "Creator C (creator-c)",
    "rr5": "Creator B (wsaj)",
    "risk1pct": "Creator E (creator-e)",
    "trim115": "Creator B (wsaj)",
}

#: The 14 cells in a fixed order: base first, then its arms, per base. Used to build the m=14 BH pass
#: in a stable, round-trippable order.
ALL_CELL_IDS: list[str] = []
for _base_key, (_base_id, _arms, _persona) in BASES.items():
    ALL_CELL_IDS.append(_base_id)
    ALL_CELL_IDS.extend(_arms.values())

RR5_IDS = [arms["rr5"] for _base_id, arms, _persona in BASES.values()]


def load_round45_scorecard() -> dict[str, Any]:
    return json.loads(SCORECARD_PATH.read_text(encoding="utf-8"))


def per_base_contrasts(cells: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """arm-minus-OWN-base contrast for every one of the 11 arm cells, keyed by arm agent_id."""
    out: dict[str, dict[str, Any]] = {}
    for base_id, arms, _persona in BASES.values():
        if base_id not in cells:
            continue
        for arm_id in arms.values():
            if arm_id not in cells:
                continue
            out[arm_id] = contrast(cells[arm_id], cells[base_id])
    return out


def enhancement_marginals(contrasts: dict[str, dict[str, Any]]) -> dict[str, float | None]:
    """marginal[e] = mean over the bases that carry enhancement `e` of (arm median - base median).

    `trend100` is carried by `kim` and `creator-b` only (2 bases); the other three enhancements are
    carried by all three bases. Matches this round's own pinned decision rule
    (`ROUND-45-PLAN.md`/`MIX-AND-MATCH-PLAN.md` section 3).
    """
    out: dict[str, float | None] = {}
    for enhancement in ENHANCEMENTS:
        diffs = []
        for _base_id, arms, _persona in BASES.values():
            arm_id = arms.get(enhancement)
            if arm_id is None or arm_id not in contrasts:
                continue
            d = contrasts[arm_id]["median_diff"]
            if d is not None:
                diffs.append(d)
        out[enhancement] = (sum(diffs) / len(diffs)) if diffs else None
    return out


def bh_m14(cells: dict[str, Any]) -> list[dict[str, Any]]:
    """BH over all 14 cells (m=14), each arm contrasted with its OWN base; base cells carry p=None
    but still occupy a seat in `m`, per `app.backtest.scan.benjamini_hochberg`'s own rule and this
    round's pre-registered decision rule.
    """
    rows: list[dict[str, Any]] = []
    ps: list[float | None] = []
    base_of: dict[str, str] = {}
    for base_id, arms, _persona in BASES.values():
        for arm_id in arms.values():
            base_of[arm_id] = base_id

    for cell_id in ALL_CELL_IDS:
        if cell_id not in cells:
            rows.append({"cell": cell_id, "base": None, "p": None})
            ps.append(None)
            continue
        base_id = base_of.get(cell_id)
        if base_id is None:
            # a base cell, contrasted with itself.
            rows.append({"cell": cell_id, "base": cell_id, "median_diff": 0.0, "p": None})
            ps.append(None)
        else:
            c = contrast(cells[cell_id], cells[base_id])
            rows.append({"cell": cell_id, "base": base_id, "median_diff": c["median_diff"], "p": c["p_signflip"]})
            ps.append(c["p_signflip"])

    qs = benjamini_hochberg(ps)
    for row, q in zip(rows, qs, strict=True):
        row["q"] = q
    return rows


def rr5_target_exit_counts() -> dict[str, dict[str, Any]]:
    """For each `rr5` cell, tally `exit_reason == "target"` across every trade in every main window's
    run file -- the pre-registered check on whether the 5:1 bracket ever actually binds.
    """
    out: dict[str, dict[str, Any]] = {}
    for agent_id in RR5_IDS:
        target = 0
        total = 0
        missing_windows: list[str] = []
        for window in MAIN_WINDOWS:
            run = load_run(ROUND, window, agent_id)
            if run is None:
                missing_windows.append(window)
                continue
            for trade in run.get("trades") or []:
                total += 1
                if trade.get("exit_reason") == "target":
                    target += 1
        fraction = (target / total) if total else None
        out[agent_id] = {
            "target_exits": target,
            "total_exits": total,
            "fraction_target": fraction,
            "missing_windows": missing_windows,
        }
    return out


def report(card: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    cells = cells_of(card)
    out: dict[str, Any] = {"round": ROUND, "n_cells": len(cells)}
    md = [
        "# Round 45 -- computed verdict tables",
        "",
        "**Not investment advice.** Price-only bars, no dividends. Nothing in this round is "
        "promotable (`trading` purpose, PROTOCOL.md r21 amendment) -- report only. Every vault draft "
        "behind `bee` and `wsaj` has `published = null`; hindsight against this round's eight windows "
        "is unbounded -- see ROUND-45-PLAN.md section 6.",
        "",
    ]
    md += ["## Cells", "", table(cells), ""]
    md += ["## Per-window adjusted excess", "", per_window_table(cells, sorted(cells)), ""]

    # ------------------------------------------------------------------
    # Per-base arm-minus-own-base contrasts.
    # ------------------------------------------------------------------
    contrasts = per_base_contrasts(cells)
    out["arm_minus_base"] = {
        arm_id: c for arm_id, c in contrasts.items()
    }
    md += ["## Arm minus OWN base (PLAN decision rule input)", ""]
    md += [
        "| base | enhancement | whose component | arm median | base median | arm - base | "
        "windows arm>base | p (sign-flip) | clears 21.2pp floor? |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for base_key, (base_id, arms, persona) in BASES.items():
        if base_id not in cells:
            continue
        for enhancement, arm_id in arms.items():
            if arm_id not in contrasts:
                continue
            c = contrasts[arm_id]
            clears = (c["median_diff"] or 0) * 100 > FLOOR_PP
            md.append(
                f"| {base_key} ({persona}) | `{enhancement}` | {ENHANCEMENT_PERSONA[enhancement]} | "
                f"{pp(cells[arm_id].median)} | {pp(cells[base_id].median)} | {pp(c['median_diff'])} | "
                f"{c['windows_a_gt_b']}/{c['n_windows']} | {fmt(c['p_signflip'])} | "
                f"{'YES' if clears else 'no'} |"
            )
    md.append("")

    # ------------------------------------------------------------------
    # Enhancement marginals -- the decision rule's other half.
    # ------------------------------------------------------------------
    marginals = enhancement_marginals(contrasts)
    out["enhancement_marginals"] = marginals
    md += ["## Enhancement marginals (mean over its bases of arm-minus-own-base median)", ""]
    md += ["| enhancement | whose component | bases | marginal | clears 21.2pp floor? |",
           "|---|---|---|---|---|"]
    bases_by_enh = {
        e: [bk for bk in BASES if e in BASES[bk][1]] for e in ENHANCEMENTS
    }
    for e in ENHANCEMENTS:
        m = marginals[e]
        clears = (m or 0) * 100 > FLOOR_PP
        md.append(
            f"| `{e}` | {ENHANCEMENT_PERSONA[e]} | {', '.join(bases_by_enh[e])} | {pp(m)} | "
            f"{'YES' if clears else 'no'} |"
        )
    md.append("")

    # ------------------------------------------------------------------
    # BH over all 14 cells (m=14), each arm vs its own base.
    # ------------------------------------------------------------------
    bh = bh_m14(cells)
    out["bh_m14"] = bh
    q_by_cell = {r["cell"]: r["q"] for r in bh}
    min_q = min((r["q"] for r in bh if r["q"] is not None), default=None)
    out["min_q"] = min_q
    md += ["## BH over all 14 cells (m=14) -- each arm contrasted with its OWN base", ""]
    md += ["| cell | base | median diff | p (sign-flip) | q (BH, m=14) |", "|---|---|---|---|---|"]
    for r in bh:
        md.append(
            f"| `{r['cell']}` | {r['base'] or '--'} | {pp(r.get('median_diff'))} | "
            f"{fmt(r.get('p'))} | {fmt(r.get('q'))} |"
        )
    md.append("")
    md.append(f"Minimum q over the field: **{min_q:.4f}**" if min_q is not None else "No q computed.")
    md.append("")

    # ------------------------------------------------------------------
    # Enhancement verdict: marginal > floor AND every one of its arm cells has q<0.10.
    # ------------------------------------------------------------------
    verdicts: dict[str, dict[str, Any]] = {}
    md += ["## Verdict per enhancement (PLAN decision rule: marginal > 21.2pp AND every arm cell "
           "q<0.10)", ""]
    for e in ENHANCEMENTS:
        m = marginals[e]
        clears_marginal = (m or 0) * 100 > FLOOR_PP
        arm_ids = [BASES[bk][1][e] for bk in bases_by_enh[e]]
        qs = [q_by_cell.get(a) for a in arm_ids]
        all_survive_bh = all(q is not None and q < 0.10 for q in qs)
        earns = clears_marginal and all_survive_bh
        verdicts[e] = {
            "marginal": m, "clears_marginal_floor": clears_marginal, "arm_qs": dict(zip(arm_ids, qs, strict=True)),
            "all_survive_bh": all_survive_bh, "earns": earns,
        }
        md.append(
            f"- `{e}`: marginal {pp(m)} ({'clears' if clears_marginal else 'inside'} the {FLOOR_PP}pp "
            f"floor); arm q-values {[fmt(q) for q in qs]} ({'all' if all_survive_bh else 'not all'} "
            f"< 0.10) -> **{'EARNS SOMETHING' if earns else 'NULL'}**."
        )
    out["verdicts"] = verdicts
    any_earns = any(v["earns"] for v in verdicts.values())
    md += ["", f"**Any enhancement earns something by the pre-registered rule: "
           f"{'YES' if any_earns else 'NO (null on all four)'}**.", ""]

    # ------------------------------------------------------------------
    # rr5 take-profit exit tally -- from the run files, not the scorecard.
    # ------------------------------------------------------------------
    rr5_counts = rr5_target_exit_counts()
    out["rr5_target_exit_counts"] = rr5_counts
    md += ["## `rr5` take-profit exit tally (from run files' trade logs, across the 8 main windows)", ""]
    md += ["| cell | target exits | total exits | fraction target | < 10% (pre-registered)? |",
           "|---|---|---|---|---|"]
    for agent_id, row in rr5_counts.items():
        frac = row["fraction_target"]
        under_10 = frac is not None and frac < 0.10
        frac_txt = "n/a" if frac is None else f"{frac:.1%}"
        md.append(
            f"| `{agent_id}` | {row['target_exits']} | {row['total_exits']} | {frac_txt} | "
            f"{'YES' if under_10 else 'no'} |"
        )
    md.append("")

    # ------------------------------------------------------------------
    # Trade counts and exposure per cell.
    # ------------------------------------------------------------------
    trades = {a: cells[a].trades for a in sorted(cells)}
    exposure = {a: cells[a].exposure for a in sorted(cells)}
    out["trades"] = trades
    out["exposure"] = exposure
    md += ["## Trade counts and mean exposure per cell", "", "| cell | trades | mean exposure | "
           "adjusted excess per unit exposure |", "|---|---|---|---|"]
    for a in sorted(cells):
        exp = exposure[a]
        med = cells[a].median
        per_unit = (med / exp) if (exp is not None and exp not in (0, None) and med is not None) else None
        md.append(
            f"| `{a}` | {trades[a]} | {'' if exp is None else f'{exp:.3f}'} | "
            f"{'' if per_unit is None else pp(per_unit)} |"
        )
    md.append("")

    # ------------------------------------------------------------------
    # Predictions (ROUND-45-PLAN.md section 5 / MIX-AND-MATCH-PLAN.md section 3).
    # ------------------------------------------------------------------
    md += ["## Predictions (PLAN)", ""]

    # (1) null for all four
    p1 = not any_earns
    md.append(f"1. Null for all four enhancements: **{'HELD' if p1 else 'REFUTED'}**.")

    # (2) trend100 cuts trades vs base on both bases it applies to (kim, creator-b)
    trend100_cuts = {}
    for bk in ("kim", "wsaj"):
        base_id, arms, _p = BASES[bk]
        arm_id = arms["trend100"]
        if base_id in cells and arm_id in cells:
            trend100_cuts[bk] = cells[arm_id].trades < cells[base_id].trades
    p2 = trend100_cuts and all(trend100_cuts.values())
    out["pred_trend100_cuts_trades"] = trend100_cuts
    md.append(f"2. `trend100` cuts trades vs base on kim and wsaj: **{'HELD' if p2 else 'NOT CONFIRMED / REFUTED'}** "
              f"({trend100_cuts}).")

    # (3) rr5 near-identical to base; <10% of exits are targets
    rr5_under_10 = {a: (row["fraction_target"] is not None and row["fraction_target"] < 0.10)
                     for a, row in rr5_counts.items()}
    p3 = all(rr5_under_10.values())
    out["pred_rr5_under_10pct_target_exits"] = rr5_under_10
    md.append(f"3. Fewer than 10% of `rr5` exits are the take-profit target: "
              f"**{'HELD' if p3 else 'NOT CONFIRMED / REFUTED'}** ({rr5_under_10}).")

    # (4) risk1pct lowers mean exposure and raises adjusted excess per unit exposure, no sign change
    p4_rows = {}
    for bk, (base_id, arms, _p) in BASES.items():
        arm_id = arms.get("risk1pct")
        if arm_id is None or base_id not in cells or arm_id not in cells:
            continue
        base_c, arm_c = cells[base_id], cells[arm_id]
        exp_lower = (arm_c.exposure is not None and base_c.exposure is not None
                     and arm_c.exposure < base_c.exposure)
        base_per_unit = (base_c.median / base_c.exposure) if base_c.exposure else None
        arm_per_unit = (arm_c.median / arm_c.exposure) if arm_c.exposure else None
        per_unit_higher = (base_per_unit is not None and arm_per_unit is not None
                            and arm_per_unit > base_per_unit)
        sign_matches = sum(
            1 for t in MAIN_WINDOWS
            if base_c.win[t] is not None and arm_c.win[t] is not None
            and (base_c.win[t] > 0) == (arm_c.win[t] > 0)
        )
        n_compared = sum(
            1 for t in MAIN_WINDOWS if base_c.win[t] is not None and arm_c.win[t] is not None
        )
        p4_rows[bk] = {
            "exposure_lower": exp_lower, "adjusted_excess_per_unit_higher": per_unit_higher,
            "sign_matches": f"{sign_matches}/{n_compared}",
        }
    out["pred_risk1pct"] = p4_rows
    md.append(f"4. `risk1pct` lowers mean exposure and raises adjusted excess per unit exposure "
              f"without flipping the per-window sign pattern: {p4_rows}.")

    # (5) trim115 lowers exposure and loses to base in bull-2024 and recent
    p5_rows = {}
    for bk, (base_id, arms, _p) in BASES.items():
        arm_id = arms.get("trim115")
        if arm_id is None or base_id not in cells or arm_id not in cells:
            continue
        base_c, arm_c = cells[base_id], cells[arm_id]
        exp_lower = (arm_c.exposure is not None and base_c.exposure is not None
                     and arm_c.exposure < base_c.exposure)
        loses_bull2024 = (
            base_c.win.get("bull-2024") is not None and arm_c.win.get("bull-2024") is not None
            and arm_c.win["bull-2024"] < base_c.win["bull-2024"]
        )
        loses_recent = (
            base_c.win.get("recent") is not None and arm_c.win.get("recent") is not None
            and arm_c.win["recent"] < base_c.win["recent"]
        )
        p5_rows[bk] = {
            "exposure_lower": exp_lower, "loses_bull_2024": loses_bull2024, "loses_recent": loses_recent,
        }
    out["pred_trim115"] = p5_rows
    p5 = all(row["exposure_lower"] and row["loses_bull_2024"] and row["loses_recent"]
             for row in p5_rows.values()) if p5_rows else False
    md.append(f"5. `trim115` lowers exposure and loses to base in bull-2024 and recent: "
              f"**{'HELD' if p5 else 'NOT CONFIRMED / REFUTED'}** ({p5_rows}).")

    md += ["", "Nothing in this round is promotable regardless of outcome (`trading` purpose, "
           "PROTOCOL.md r21 amendment) -- these are measurement results only. Not investment advice.", ""]

    return "\n".join(md), out


def main(argv: list[str] | None = None) -> int:
    if not SCORECARD_PATH.is_file():
        print(f"no scorecard at {SCORECARD_PATH.relative_to(REPO).as_posix()} -- round 45 has not "
              "been run yet. This tool is importable/unit-testable on a fake scorecard dict without "
              "one.")
        return 1
    card = load_round45_scorecard()
    md, out = report(card)
    print(md)
    ANALYSIS_PATH.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\n(wrote {ANALYSIS_PATH.relative_to(REPO).as_posix()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

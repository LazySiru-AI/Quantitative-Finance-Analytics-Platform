"""Verdict tables for round 44 -- thematic baskets held passively vs a passive control, and a
profit-trim rule vs holding the basket -- from `data/rounds/r44-2026-09/scorecard.json`.

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round44_report.py

`ROUND-44-PLAN.md` pre-registered a decision rule and a set of predictions before any card ran. This
module computes exactly the quantities that rule names -- the basket-minus-control contrast, the
trim-minus-passive contrast per basket, the same two contrasts restricted to the six windows ending by
2022-10 (the hindsight-safe subset) and to the two 2024-26 windows alone, exposure and trade counts,
and a Benjamini-Hochberg pass whose denominator is every cell this round runs -- and prints them as
markdown so `REPORT.md` quotes numbers this code produced. It writes the same content to
`data/rounds/r44-2026-09/analysis.json`.

**Reuses `round34_36_report.py`'s machinery rather than re-deriving it.** `strategy-program/tools/` is
not inside a legal Python package (the hyphen), so that module is loaded by file path, exactly the way
`round44.py` loads no such thing but this file needs `load_scorecard`, `cells_of`, `contrast`,
`bh_against_reference`, `table`, `per_window_table`, `FLOOR_PP` and `MAIN_WINDOWS` -- the shared,
already-tested statistics rather than a second, drifting copy of the same sign-flip permutation test.
`round34_36_report.py` is imported, never edited, per this round's stated scope.

**Statistics, stated plainly** (inherited from the imported module, restated here because a reader of
this file's output should not have to open another one to know what a number means). A pairwise
contrast between two cells is the vector of their eight paired per-window `adjusted_excess`
differences; its p-value is an exact two-sided sign-flip permutation test on the mean paired
difference (2^8 = 256 sign assignments enumerated). The "six fair windows" and "two hindsight windows"
medians below are the median of the *paired* per-window differences restricted to that window subset,
not a re-scored median-of-medians -- consistent with how `ROUND-44-PLAN.md` section 5 prediction 3
states the fair test.

**Not investment advice.** Every figure here is a backtest on price-only bars against a benchmark
`ROUND-44-PLAN.md` section 4 already flags as a poor fit for four of the five baskets.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import statistics
import sys
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[2]

# Load round34_36_report.py by file path -- shared, not edited (this round's scope excludes it).
_spec = importlib.util.spec_from_file_location(
    "round34_36_report", REPO / "strategy-program" / "tools" / "round34_36_report.py"
)
assert _spec is not None and _spec.loader is not None
_r3436 = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("round34_36_report", _r3436)
_spec.loader.exec_module(_r3436)

load_scorecard = _r3436.load_scorecard
cells_of = _r3436.cells_of
contrast = _r3436.contrast
bh_against_reference = _r3436.bh_against_reference
table = _r3436.table
per_window_table = _r3436.per_window_table
FLOOR_PP = _r3436.FLOOR_PP
MAIN_WINDOWS = _r3436.MAIN_WINDOWS
pp = _r3436.pp
fmt = _r3436.fmt
load_run = _r3436.load_run

ROUND = 44
BASKETS = ("power", "defense", "semicap", "realassets", "control")
THEMED_BASKETS = ("power", "defense", "semicap", "realassets")
CONTROL = "control"

#: The hindsight split `ROUND-44-PLAN.md` section 5 prediction 3 pre-registers: every note in the
#: persona corpus has `published = null`, so `bull-2024` and `recent` are in-sample to the hypothesis.
FAIR_WINDOWS = ("gfc", "chop-2011", "chop-2015", "q4-2018", "covid", "bear-2022")
HINDSIGHT_WINDOWS = ("bull-2024", "recent")
assert set(FAIR_WINDOWS) | set(HINDSIGHT_WINDOWS) == set(MAIN_WINDOWS)


def _paired_median(a, b, windows: tuple[str, ...]) -> float | None:
    """Median of the paired per-window `adjusted_excess` differences `a - b`, restricted to `windows`.

    This is the quantity `ROUND-44-PLAN.md` section 5 prediction 3 asks for: not a re-scored median
    of each cell's own (differently-windowed) median, but the median of the *matched* per-window gaps
    on exactly the window subset named -- so the six-window and two-window figures are directly
    comparable to each other and to the eight-window figure.
    """
    diffs = [a.win[t] - b.win[t] for t in windows if a.win[t] is not None and b.win[t] is not None]
    if not diffs:
        return None
    return statistics.median(diffs)


def load_report() -> tuple[str, dict[str, Any]]:
    card = load_scorecard(ROUND)
    cells = cells_of(card)
    out: dict[str, Any] = {"round": ROUND, "n_cells": len(cells)}
    md = [
        "# Round 44 -- computed verdict tables",
        "",
        "Not investment advice. See `strategy-program/ROUND-44-PLAN.md` for the pre-registration.",
        "",
    ]
    md += ["## Cells (ranked on median adjusted excess vs SPY)", "", table(cells), ""]
    md += ["## Per-window adjusted excess", "", per_window_table(cells, sorted(cells)), ""]

    # -----------------------------------------------------------------
    # Question 1: BASKET -- does the theme beat the control, held passively?
    # -----------------------------------------------------------------
    md += [
        "## Question 1 (BASKET): basket-passive minus control-passive",
        "",
        "| basket | basket median | control median | 8-window median diff | 6 fair windows "
        "(gfc..bear-2022) | 2 hindsight windows (bull-2024, recent) | windows basket>control | "
        "p (sign-flip) | clears floor+q<0.10? |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    basket_vs_control: dict[str, Any] = {}
    for basket in THEMED_BASKETS:
        b_id, c_id = f"r44-{basket}-passive", f"r44-{CONTROL}-passive"
        if b_id not in cells or c_id not in cells:
            continue
        b, c = cells[b_id], cells[c_id]
        contr = contrast(b, c)
        fair = _paired_median(b, c, FAIR_WINDOWS)
        hindsight = _paired_median(b, c, HINDSIGHT_WINDOWS)
        basket_vs_control[basket] = {
            "contrast": contr, "fair_median_diff": fair, "hindsight_median_diff": hindsight,
        }
        md.append(
            f"| {basket} | {pp(b.median)} | {pp(c.median)} | {pp(contr['median_diff'])} | "
            f"{pp(fair)} | {pp(hindsight)} | {contr['windows_a_gt_b']}/{contr['n_windows']} | "
            f"{fmt(contr['p_signflip'])} | "
            f"{'YES' if (contr['median_diff'] or 0) * 100 > FLOOR_PP else 'no'} |"
        )
    out["basket_vs_control"] = basket_vs_control

    # -----------------------------------------------------------------
    # Question 2: RULE -- does trim beat holding the basket passively?
    # -----------------------------------------------------------------
    md += [
        "",
        "## Question 2 (RULE): trim minus passive, per basket",
        "",
        "| basket | trim median | passive median | 8-window median diff | 6 fair windows | "
        "2 hindsight windows | windows trim>passive | p (sign-flip) | mean exposure trim vs passive "
        "| trades trim vs passive | clears floor+q<0.10? |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    trim_vs_passive: dict[str, Any] = {}
    for basket in BASKETS:
        t_id, p_id = f"r44-{basket}-trim", f"r44-{basket}-passive"
        if t_id not in cells or p_id not in cells:
            continue
        t, p = cells[t_id], cells[p_id]
        contr = contrast(t, p)
        fair = _paired_median(t, p, FAIR_WINDOWS)
        hindsight = _paired_median(t, p, HINDSIGHT_WINDOWS)
        trim_vs_passive[basket] = {
            "contrast": contr, "fair_median_diff": fair, "hindsight_median_diff": hindsight,
            "mean_exposure_trim": t.exposure, "mean_exposure_passive": p.exposure,
            "trades_trim": t.trades, "trades_passive": p.trades,
        }
        exp_txt = (
            f"{t.exposure:.3f} vs {p.exposure:.3f}"
            if t.exposure is not None and p.exposure is not None
            else "n/a"
        )
        md.append(
            f"| {basket} | {pp(t.median)} | {pp(p.median)} | {pp(contr['median_diff'])} | "
            f"{pp(fair)} | {pp(hindsight)} | {contr['windows_a_gt_b']}/{contr['n_windows']} | "
            f"{fmt(contr['p_signflip'])} | {exp_txt} | {t.trades} vs {p.trades} | "
            f"{'YES' if (contr['median_diff'] or 0) * 100 > FLOOR_PP else 'no'} |"
        )
    out["trim_vs_passive"] = trim_vs_passive

    # -----------------------------------------------------------------
    # Benjamini-Hochberg over all 10 cells against the control-passive reference
    # -----------------------------------------------------------------
    bh = bh_against_reference(cells, f"r44-{CONTROL}-passive")
    out["bh"] = bh
    min_q = min((r["q"] for r in bh if r["q"] is not None), default=None)
    out["min_q"] = min_q
    md += [
        "",
        f"## BH over all {len(cells)} cells (m={len(cells)}) against `r44-{CONTROL}-passive`",
        "",
        "| cell | median diff vs control-passive | p (sign-flip) | q (BH) |",
        "|---|---|---|---|",
    ]
    for r in sorted(bh, key=lambda r: -(r["median_diff"] or 0)):
        md.append(f"| `{r['cell']}` | {pp(r['median_diff'])} | {fmt(r['p'])} | {fmt(r['q'])} |")
    md += ["", f"Minimum q over the field: **{min_q:.4f}**" if min_q is not None else "", ""]

    # -----------------------------------------------------------------
    # Exposure prediction (plan section 5 #4): trim exposure falls most in semicap, least in power
    # -----------------------------------------------------------------
    trim_exposure = {
        b: trim_vs_passive[b]["mean_exposure_trim"]
        for b in BASKETS
        if b in trim_vs_passive and trim_vs_passive[b]["mean_exposure_trim"] is not None
    }
    out["trim_exposure_by_basket"] = trim_exposure
    if trim_exposure:
        most_reduced = min(trim_exposure, key=lambda b: trim_exposure[b])
        least_reduced = max(trim_exposure, key=lambda b: trim_exposure[b])
        out["exposure_prediction"] = {
            "predicted_most_reduced": "semicap", "predicted_least_reduced": "power",
            "actual_most_reduced": most_reduced, "actual_least_reduced": least_reduced,
        }
        md += [
            "## Exposure prediction (PLAN section 5 #4): trim falls most in semicap, least in power",
            "",
            "| basket | mean trim exposure |",
            "|---|---|",
        ]
        for b in sorted(trim_exposure, key=lambda b: trim_exposure[b]):
            md.append(f"| {b} | {trim_exposure[b]:.3f} |")
        md += [
            "",
            f"Lowest trim exposure: **{most_reduced}** (predicted semicap); highest: "
            f"**{least_reduced}** (predicted power) -- "
            f"{'HELD' if most_reduced == 'semicap' and least_reduced == 'power' else 'not exactly as predicted'}.",
            "",
        ]

    # -----------------------------------------------------------------
    # Trend-window prediction (plan section 5 #5/#6)
    # -----------------------------------------------------------------
    trend_rows = []
    for basket in BASKETS:
        t_id, p_id = f"r44-{basket}-trim", f"r44-{basket}-passive"
        if t_id not in cells or p_id not in cells:
            continue
        t, p = cells[t_id], cells[p_id]
        row = {"basket": basket}
        for win in ("bull-2024", "recent", "bear-2022", "gfc"):
            if t.win[win] is not None and p.win[win] is not None:
                row[win] = t.win[win] - p.win[win]
        trend_rows.append(row)
    out["trim_minus_passive_by_regime_window"] = trend_rows
    md += [
        "## Trend/crisis-window check (PLAN section 5 #5/#6): trim minus passive in named windows",
        "",
        "| basket | bull-2024 | recent | bear-2022 | gfc |",
        "|---|---|---|---|---|",
    ]
    for row in trend_rows:
        md.append(
            f"| {row['basket']} | {pp(row.get('bull-2024'))} | {pp(row.get('recent'))} | "
            f"{pp(row.get('bear-2022'))} | {pp(row.get('gfc'))} |"
        )
    trend_neg = all(
        (row.get("bull-2024") or 0) < 0 and (row.get("recent") or 0) < 0 for row in trend_rows
    )
    md += [
        "",
        f"Trim underperforms passive in BOTH bull-2024 and recent, every basket: "
        f"**{'HELD' if trend_neg else 'REFUTED'}**.",
        "",
    ]

    # -----------------------------------------------------------------
    # Verdict
    # -----------------------------------------------------------------
    basket_edge = any(
        (row["contrast"]["median_diff"] or 0) * 100 > FLOOR_PP for row in basket_vs_control.values()
    )
    trim_edge = any(
        (row["contrast"]["median_diff"] or 0) * 100 > FLOOR_PP for row in trim_vs_passive.values()
    )
    out["basket_edge_any_cell"] = basket_edge
    out["trim_edge_any_cell"] = trim_edge
    md += [
        "## Verdict (PLAN section 4 decision rule)",
        "",
        f"- Any basket beats control by >21.2pp (before the BH check): "
        f"**{'YES' if basket_edge else 'NO (null)'}**.",
        f"- Any trim arm beats its own passive by >21.2pp (before the BH check): "
        f"**{'YES' if trim_edge else 'NO (null)'}**.",
        "- Minimum BH q over all 10 cells: "
        + (f"**{min_q:.4f}**" if min_q is not None else "n/a")
        + " (nothing survives q<0.10 unless this is below it).",
        "",
        "**A basket or trim edge requires BOTH the >21.2pp margin AND BH q<0.10 (PLAN section 4). "
        "Nothing is promoted from this round regardless of outcome -- it is a pre-registered "
        "measurement study.**",
        "",
    ]

    return "\n".join(md), out


def main(argv: list[str] | None = None) -> int:
    md, out = load_report()
    print(md)
    dest = REPO / "data" / "rounds" / f"r{ROUND}-2026-09" / "analysis.json"
    dest.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\n(wrote {dest.relative_to(REPO).as_posix()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

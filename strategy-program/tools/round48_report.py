"""Verdict tables for round 48 -- does Creator E's 1%-risk sizing do to EVERY seated trading card
what round 45 found it did to his own? -- from its scorecard.

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round48_report.py

`ROUND-48-PLAN.md` pre-registered a decision rule and a set of predictions before any card ran. This
module computes exactly the quantities that rule names -- the resizing's marginal (the mean over the
five bases of risk1pct-minus-own-base median adjusted excess), a Benjamini-Hochberg pass whose
denominator is every one of the round's 10 cells with each risk1pct cell contrasted against its OWN
base (base cells carry p=None but still count toward m=10), the worst-window / IQR / exposure /
excess-per-exposure / sign-pattern comparisons the plan's predictions name, and a dollar-P&L table --
and prints them as markdown so `data/rounds/r48-2026-09/REPORT.md` (written separately, NOT by this
tool) quotes numbers this code produced rather than numbers a hand transcribed. It writes the same
content to `data/rounds/r48-2026-09/analysis.json`.

**Why this imports `round34_36_report.py` by file path.** `strategy-program` is not a legal Python
package name (the hyphen), so that module -- which already carries `load_scorecard`, `load_run`,
`cells_of`, `contrast`, `table` and `per_window_table` -- is loaded the same way `round45_report.py`
does: `importlib.util.spec_from_file_location`. Nothing here re-derives what that module already
computes correctly.

**Why this round's BH pass is NOT `round34_36_report.bh_against_reference`.** That helper contrasts
every cell against ONE shared reference. Round 48 has FIVE bases, each with its own risk1pct cell
contrasted against its own base -- `bh_m10` below builds the 10 p-values in that shape (`None` for the
five base cells, a per-base contrast p-value for each of the five risk1pct cells) and calls
`app.backtest.scan.benjamini_hochberg` on the resulting list of 10 directly, exactly as
`round45_report.bh_m14` does for its own, differently-shaped field.

**PROTOCOL.md section 4's small-book caveat, made currency-visible.** A smaller book structurally
cannot have as deep a worst window as a larger one -- resizing toward 1% risk per trade shrinks the
book on four of the five bases here, so a shallower worst-window percentage is expected on its own
terms, not necessarily evidence of anything else. `dollar_worst_window_table` below prints the SAME
worst window's realised P&L in dollars, read from the run files' trade logs, beside the scorecard's own
`total_realised_pnl` for the whole 8-window matrix, so the size effect this round measures is visible
in currency and not only in percentage points.

**Not investment advice.** Every figure is a backtest on price-only bars, no dividends. Nothing in
this round is promotable (`trading` purpose, PROTOCOL.md r21 amendment) -- report only. A decision to
resize a seated card for real is the owner's, about risk; this round measures what that decision would
have cost and bought, it does not make it.
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

ROUND = 48
SCORECARD_PATH = REPO / "data" / "rounds" / f"r{ROUND}-2026-09" / "scorecard.json"
ANALYSIS_PATH = REPO / "data" / "rounds" / f"r{ROUND}-2026-09" / "analysis.json"

#: slug -> (base agent_id, risk1pct agent_id). The pinned round-48 field -- matches
#: `strategy-program/tools/round48.py::LIBRARY_PATHS`/`ARMS`, restated here (not imported) exactly as
#: `round45_report.py` restates round 45's field rather than importing its authoring tool.
BASES: dict[str, tuple[str, str]] = {
    "b3": ("r48-b3-base", "r48-b3-risk1pct"),
    "arot": ("r48-arot-base", "r48-arot-risk1pct"),
    "ctrend": ("r48-ctrend-base", "r48-ctrend-risk1pct"),
    "bmom": ("r48-bmom-base", "r48-bmom-risk1pct"),
    "i13f": ("r48-i13f-base", "r48-i13f-risk1pct"),
}

#: Slugs whose base carries 13F point-in-time provenance -- see `round48.py::PROVENANCE`. Their cells
#: are expected UNRANKED on every main window starting before the filing date (2026-08-14), which is
#: every main window in `MAIN_WINDOWS` -- reported, not interpreted (prediction 7).
PROVENANCE_SLUGS = ("i13f",)

#: The 10 cells in a fixed order: base then risk1pct, per slug. Used to build the m=10 BH pass in a
#: stable, round-trippable order.
ALL_CELL_IDS: list[str] = [cell_id for pair in BASES.values() for cell_id in pair]


def load_round48_scorecard() -> dict[str, Any]:
    return json.loads(SCORECARD_PATH.read_text(encoding="utf-8"))


def per_base_contrasts(cells: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """risk1pct-minus-OWN-base contrast for every one of the 5 risk1pct cells, keyed by slug."""
    out: dict[str, dict[str, Any]] = {}
    for slug, (base_id, arm_id) in BASES.items():
        if base_id not in cells or arm_id not in cells:
            continue
        out[slug] = contrast(cells[arm_id], cells[base_id])
    return out


def marginal(contrasts: dict[str, dict[str, Any]]) -> float | None:
    """The mean over the five bases of (risk1pct median - base median). This round's decision-rule
    quantity (ROUND-48-PLAN.md section 4)."""
    diffs = [c["median_diff"] for c in contrasts.values() if c["median_diff"] is not None]
    return (sum(diffs) / len(diffs)) if diffs else None


def bh_m10(cells: dict[str, Any]) -> list[dict[str, Any]]:
    """BH over all 10 cells (m=10), each risk1pct cell contrasted with its OWN base; base cells carry
    p=None but still occupy a seat in `m`, per `app.backtest.scan.benjamini_hochberg`'s own rule and
    this round's pre-registered decision rule."""
    rows: list[dict[str, Any]] = []
    ps: list[float | None] = []
    base_of: dict[str, str] = {base_id: base_id for base_id, _arm_id in BASES.values()}
    arm_to_base = {arm_id: base_id for base_id, arm_id in BASES.values()}

    for cell_id in ALL_CELL_IDS:
        if cell_id not in cells:
            rows.append({"cell": cell_id, "base": None, "p": None})
            ps.append(None)
            continue
        if cell_id in base_of:
            rows.append({"cell": cell_id, "base": cell_id, "median_diff": 0.0, "p": None})
            ps.append(None)
            continue
        base_id = arm_to_base[cell_id]
        if base_id not in cells:
            rows.append({"cell": cell_id, "base": base_id, "p": None})
            ps.append(None)
            continue
        c = contrast(cells[cell_id], cells[base_id])
        rows.append({"cell": cell_id, "base": base_id, "median_diff": c["median_diff"], "p": c["p_signflip"]})
        ps.append(c["p_signflip"])

    qs = benjamini_hochberg(ps)
    for row, q in zip(rows, qs, strict=True):
        row["q"] = q
    return rows


def dollar_worst_window_table(cells: dict[str, Any], card: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Per cell: the same worst window `Cell.worst` names, but its realised P&L in DOLLARS, read from
    that window's run file trade log -- plus the scorecard's own `total_realised_pnl` across the whole
    8-window matrix, for context. PROTOCOL.md section 4: a smaller book's shallower worst window in
    PERCENTAGE POINTS is a size effect; this table makes the same comparison in currency so the size
    effect is visible rather than assumed."""
    rows_by_id = {r["agent_id"]: r for r in list(card.get("ranked") or []) + list(card.get("unranked") or [])}
    out: dict[str, dict[str, Any]] = {}
    for agent_id, cell in cells.items():
        row = rows_by_id.get(agent_id, {})
        total_pnl = row.get("total_realised_pnl")

        worst_tag = None
        if cell.worst is not None:
            for tag in MAIN_WINDOWS:
                w = cell.win.get(tag)
                if w is not None and abs(w - cell.worst) < 1e-9:
                    worst_tag = tag
                    break

        worst_pnl = None
        if worst_tag is not None:
            run = load_run(ROUND, worst_tag, agent_id)
            if run is not None:
                trades = run.get("trades") or []
                worst_pnl = sum(float(t["pnl"]) for t in trades)

        out[agent_id] = {
            "worst_window": worst_tag,
            "worst_window_pnl_usd": worst_pnl,
            "total_realised_pnl_usd": total_pnl,
        }
    return out


def report(card: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    cells = cells_of(card)
    out: dict[str, Any] = {"round": ROUND, "n_cells": len(cells)}
    md = [
        "# Round 48 -- computed verdict tables",
        "",
        "**Not investment advice.** Price-only bars, no dividends. Nothing in this round is "
        "promotable (`trading` purpose, PROTOCOL.md r21 amendment) -- report only. A decision to "
        "resize a seated card for real is the owner's, about risk; this round measures what that "
        "decision would have cost and bought.",
        "",
    ]
    md += ["## Cells", "", table(cells), ""]
    md += ["## Per-window adjusted excess", "", per_window_table(cells, sorted(cells)), ""]

    # ------------------------------------------------------------------
    # Per-base risk1pct-minus-own-base contrasts (the base->risk1pct sizing table).
    # ------------------------------------------------------------------
    contrasts = per_base_contrasts(cells)
    out["risk1pct_minus_base"] = contrasts
    md += ["## risk1pct minus OWN base -- the sizing table (PLAN decision rule input)", ""]
    md += [
        "| base | base median | risk1pct median | arm - base | worst: base -> risk1pct | IQR: base -> "
        "risk1pct | exposure: base -> risk1pct | windows arm>base | p (sign-flip) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for slug, (base_id, arm_id) in BASES.items():
        if base_id not in cells or arm_id not in cells:
            md.append(f"| {slug} | -- | -- | -- | -- | -- | -- | -- | -- |")
            continue
        c = contrasts.get(slug, {})
        base_c, arm_c = cells[base_id], cells[arm_id]
        md.append(
            f"| {slug} | {pp(base_c.median)} | {pp(arm_c.median)} | {pp(c.get('median_diff'))} | "
            f"{pp(base_c.worst)} -> {pp(arm_c.worst)} | {pp(base_c.iqr)} -> {pp(arm_c.iqr)} | "
            f"{'' if base_c.exposure is None else f'{base_c.exposure:.3f}'} -> "
            f"{'' if arm_c.exposure is None else f'{arm_c.exposure:.3f}'} | "
            f"{c.get('windows_a_gt_b')}/{c.get('n_windows')} | {fmt(c.get('p_signflip'))} |"
        )
    md.append("")

    # ------------------------------------------------------------------
    # Marginal -- the decision rule's other half.
    # ------------------------------------------------------------------
    m = marginal(contrasts)
    out["marginal"] = m
    clears_marginal = (m or 0) * 100 > FLOOR_PP
    md += ["## Marginal (mean over the 5 bases of risk1pct-minus-own-base median)", "",
           f"**{pp(m)}** -- {'clears' if clears_marginal else 'inside'} the {FLOOR_PP}pp floor.", ""]

    # ------------------------------------------------------------------
    # BH over all 10 cells (m=10), each risk1pct vs its own base.
    # ------------------------------------------------------------------
    bh = bh_m10(cells)
    out["bh_m10"] = bh
    q_by_cell = {r["cell"]: r["q"] for r in bh}
    min_q = min((r["q"] for r in bh if r["q"] is not None), default=None)
    out["min_q"] = min_q
    md += ["## BH over all 10 cells (m=10) -- each risk1pct cell contrasted with its OWN base", ""]
    md += ["| cell | base | median diff | p (sign-flip) | q (BH, m=10) |", "|---|---|---|---|---|"]
    for r in bh:
        md.append(
            f"| `{r['cell']}` | {r['base'] or '--'} | {pp(r.get('median_diff'))} | "
            f"{fmt(r.get('p'))} | {fmt(r.get('q'))} |"
        )
    md.append("")
    md.append(f"Minimum q over the field: **{min_q:.4f}**" if min_q is not None else "No q computed.")
    md.append("")

    # ------------------------------------------------------------------
    # Verdict: marginal > floor AND every risk1pct cell has q<0.10.
    # ------------------------------------------------------------------
    arm_ids = [arm_id for _base_id, arm_id in BASES.values()]
    qs = [q_by_cell.get(a) for a in arm_ids]
    all_survive_bh = all(q is not None and q < 0.10 for q in qs)
    earns = clears_marginal and all_survive_bh
    out["verdict"] = {
        "marginal": m, "clears_marginal_floor": clears_marginal, "arm_qs": dict(zip(arm_ids, qs, strict=True)),
        "all_survive_bh": all_survive_bh, "earns": earns,
    }
    md += ["## Verdict (PLAN decision rule: marginal > 21.2pp AND every risk1pct cell q<0.10)", "",
           f"marginal {pp(m)} ({'clears' if clears_marginal else 'inside'} the {FLOOR_PP}pp floor); "
           f"arm q-values {[fmt(q) for q in qs]} ({'all' if all_survive_bh else 'not all'} < 0.10) -> "
           f"**{'EARNS SOMETHING' if earns else 'NULL'}**.", ""]

    # ------------------------------------------------------------------
    # Dollar worst-window table (PLAN prediction 8 / PROTOCOL.md section 4).
    # ------------------------------------------------------------------
    dollars = dollar_worst_window_table(cells, card)
    out["dollar_worst_window"] = dollars
    md += ["## Worst window in dollars of realised P&L (PROTOCOL.md section 4 caveat, made currency-"
           "visible)", "",
           "| cell | worst window (adj. excess) | worst-window P&L (run file, USD) | "
           "total realised P&L (scorecard, USD) |", "|---|---|---|---|"]
    for a in sorted(dollars):
        row = dollars[a]
        wp = row["worst_window_pnl_usd"]
        tp = row["total_realised_pnl_usd"]
        md.append(
            f"| `{a}` | {row['worst_window'] or 'n/a'} | "
            f"{'n/a' if wp is None else f'${wp:,.2f}'} | "
            f"{'n/a' if tp is None else f'${float(tp):,.2f}'} |"
        )
    md.append("")

    # ------------------------------------------------------------------
    # Predictions (ROUND-48-PLAN.md section 4).
    # ------------------------------------------------------------------
    md += ["## Predictions (PLAN)", ""]

    # (1) null on the median marginal
    p1 = m is not None and abs(m) * 100 < 5
    md.append(f"1. Null on the median marginal (|marginal| < 5pp): **{'HELD' if p1 else 'NOT CONFIRMED / REFUTED'}** ({pp(m)}).")

    # (2) worst window shallower (less negative) on >= 4 of 5 bases
    worst_shallower = {}
    for slug, (base_id, arm_id) in BASES.items():
        if base_id in cells and arm_id in cells:
            b, a = cells[base_id].worst, cells[arm_id].worst
            if b is not None and a is not None:
                worst_shallower[slug] = a > b
    n_shallower = sum(1 for v in worst_shallower.values() if v)
    p2 = n_shallower >= 4
    out["pred_worst_shallower"] = worst_shallower
    md.append(f"2. Worst window shallower on >= 4 of 5 bases: **{'HELD' if p2 else 'NOT CONFIRMED / REFUTED'}** "
              f"({n_shallower}/5; {worst_shallower}).")

    # (3) IQR narrower on >= 4 of 5 bases
    iqr_narrower = {}
    for slug, (base_id, arm_id) in BASES.items():
        if base_id in cells and arm_id in cells:
            b, a = cells[base_id].iqr, cells[arm_id].iqr
            if b is not None and a is not None:
                iqr_narrower[slug] = a < b
    n_narrower = sum(1 for v in iqr_narrower.values() if v)
    p3 = n_narrower >= 4
    out["pred_iqr_narrower"] = iqr_narrower
    md.append(f"3. IQR narrower on >= 4 of 5 bases: **{'HELD' if p3 else 'NOT CONFIRMED / REFUTED'}** "
              f"({n_narrower}/5; {iqr_narrower}).")

    # (4) mean exposure lower on 5 of 5 bases
    exp_lower = {}
    for slug, (base_id, arm_id) in BASES.items():
        if base_id in cells and arm_id in cells:
            b, a = cells[base_id].exposure, cells[arm_id].exposure
            if b is not None and a is not None:
                exp_lower[slug] = a < b
    n_exp_lower = sum(1 for v in exp_lower.values() if v)
    p4 = n_exp_lower == 5 and len(exp_lower) == 5
    out["pred_exposure_lower"] = exp_lower
    md.append(f"4. Mean exposure lower on 5 of 5 bases: **{'HELD' if p4 else 'NOT CONFIRMED / REFUTED'}** "
              f"({n_exp_lower}/5; {exp_lower}).")

    # (5) per-window sign pattern identical on >= 7 of 8 windows for every base
    sign_matches = {}
    for slug, (base_id, arm_id) in BASES.items():
        if base_id not in cells or arm_id not in cells:
            continue
        base_c, arm_c = cells[base_id], cells[arm_id]
        matches = sum(
            1 for t in MAIN_WINDOWS
            if base_c.win[t] is not None and arm_c.win[t] is not None
            and (base_c.win[t] > 0) == (arm_c.win[t] > 0)
        )
        n_compared = sum(1 for t in MAIN_WINDOWS if base_c.win[t] is not None and arm_c.win[t] is not None)
        sign_matches[slug] = f"{matches}/{n_compared}"
    p5 = all(
        int(v.split("/")[0]) >= 7 for v in sign_matches.values() if int(v.split("/")[1]) > 0
    ) if sign_matches else False
    out["pred_sign_pattern"] = sign_matches
    md.append(f"5. Per-window sign pattern identical on >= 7 of 8 windows for every base: "
              f"**{'HELD' if p5 else 'NOT CONFIRMED / REFUTED'}** ({sign_matches}).")

    # (6) adjusted excess per unit exposure within +/-3pp of base on every base
    per_unit_close = {}
    for slug, (base_id, arm_id) in BASES.items():
        if base_id not in cells or arm_id not in cells:
            continue
        base_c, arm_c = cells[base_id], cells[arm_id]
        base_pu = (base_c.median / base_c.exposure) if base_c.exposure else None
        arm_pu = (arm_c.median / arm_c.exposure) if arm_c.exposure else None
        if base_pu is not None and arm_pu is not None:
            diff_pp = (arm_pu - base_pu) * 100
            per_unit_close[slug] = {"base_per_unit": base_pu, "arm_per_unit": arm_pu, "diff_pp": diff_pp,
                                     "within_3pp": abs(diff_pp) <= 3}
    p6 = bool(per_unit_close) and all(v["within_3pp"] for v in per_unit_close.values())
    out["pred_excess_per_exposure"] = per_unit_close
    md.append(f"6. Adjusted excess per unit exposure within +/-3pp of base on every base (sizing is "
              f"not alpha): **{'HELD' if p6 else 'NOT CONFIRMED / REFUTED'}** "
              f"({ {k: pp(v['diff_pp']/100) for k, v in per_unit_close.items()} }).")

    # (7) i13f cells UNRANKED by provenance on the main windows -- reported, not interpreted.
    i13f_status = {}
    for slug in PROVENANCE_SLUGS:
        base_id, arm_id = BASES[slug]
        for agent_id in (base_id, arm_id):
            if agent_id in cells:
                i13f_status[agent_id] = {"ranked": cells[agent_id].ranked, "n_windows_run": cells[agent_id].n_run}
    p7 = bool(i13f_status) and all(not v["ranked"] for v in i13f_status.values())
    out["pred_i13f_unranked"] = i13f_status
    md.append(f"7. `i13f` cells UNRANKED by provenance on the main windows (reported, not interpreted): "
              f"**{'HELD' if p7 else 'NOT CONFIRMED / REFUTED'}** ({i13f_status}).")

    # (8) PROTOCOL.md section 4 caveat -- covered by the dollar table above.
    md.append("8. PROTOCOL.md section 4's small-book caveat: see the dollar worst-window table above -- "
              "a shallower worst window in percentage points is a size effect on a book that shrank; "
              "the dollar figures beside it are the plain outcome, not adjusted for that.")

    md += ["", "Nothing in this round is promotable regardless of outcome (`trading` purpose, "
           "PROTOCOL.md r21 amendment) -- these are measurement results only. A decision to resize a "
           "seated card for real is the owner's, about risk; this round measures what that decision "
           "would have cost and bought. Not investment advice.", ""]

    return "\n".join(md), out


def main(argv: list[str] | None = None) -> int:
    if not SCORECARD_PATH.is_file():
        print(f"no scorecard at {SCORECARD_PATH.relative_to(REPO).as_posix()} -- round 48 has not "
              "been run yet. This tool is importable/unit-testable on a fake scorecard dict without "
              "one.")
        return 1
    card = load_round48_scorecard()
    md, out = report(card)
    print(md)
    ANALYSIS_PATH.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\n(wrote {ANALYSIS_PATH.relative_to(REPO).as_posix()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

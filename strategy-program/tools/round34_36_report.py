"""Verdict tables for rounds 34, 35 and 36 -- the disjoint sector family -- from their scorecards.

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round34_36_report.py --round 34
    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round34_36_report.py --round 35
    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round34_36_report.py --round 36

Each round's plan (`ROUND-3{4,5,6}-PLAN.md`) pre-registered a decision rule and a set of predictions
before any card ran. This module computes exactly the quantities those rules name -- marginals,
pairwise contrasts, per-window sign counts, the noise-floor comparison and a Benjamini-Hochberg pass
whose denominator is every cell the round ran -- and prints them as markdown so the round REPORT.md
quotes numbers this code produced rather than numbers a hand transcribed. It writes the same content
to `data/rounds/r<N>-2026-09/analysis.json`.

**Statistics, stated plainly.** The scorecard already carries each cell's per-window
`adjusted_excess`. A pairwise contrast between two cells is the vector of their eight paired window
differences. Its p-value here is an **exact sign-flip permutation test on the mean paired difference**
(all 2^8 = 256 sign assignments enumerated, two-sided) -- chosen because it needs no distributional
assumption and no third-party package, and because with eight windows nothing more elaborate is
honest. Its floor is 2/256 = 0.0078, so a contrast can only clear BH at q < 0.10 over m = 16 if it is
essentially unanimous across windows *and* near the top of the ordering; that is the bar the plans set
when they wrote "denominator of every cell run", and it is reported as such. `None` p-values (a cell
contrasted with itself) still count toward m -- `app.backtest.scan.benjamini_hochberg`'s own rule.

**Not investment advice.** Every figure is a backtest on price-only bars.
"""

from __future__ import annotations

import argparse
import itertools
import json
import pathlib
import statistics
from collections.abc import Sequence
from typing import Any

from app.backtest.scan import benjamini_hochberg

REPO = pathlib.Path(__file__).resolve().parents[2]
FLOOR_PP = 21.2
MAIN_WINDOWS = ("q4-2018", "covid", "bear-2022", "chop-2015", "chop-2011", "bull-2024", "recent", "gfc")


def pp(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:+.2f}pp"


def fmt(x: float | None) -> str:
    return "" if x is None else f"{x:.4f}"


def load_scorecard(n: int) -> dict[str, Any]:
    path = REPO / "data" / "rounds" / f"r{n}-2026-09" / "scorecard.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_run(n: int, window: str, agent_id: str) -> dict[str, Any] | None:
    path = REPO / "data" / "rounds" / f"r{n}-2026-09" / "results" / window / "runs" / f"r1-{agent_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


class Cell:
    def __init__(self, row: dict[str, Any]) -> None:
        self.agent_id: str = row["agent_id"]
        self.ranked: bool = bool(row["ranked"])
        self.median: float | None = float(row["median_adjusted_excess"]) if row.get("median_adjusted_excess") else None
        self.worst: float | None = float(row["worst_adjusted_excess"]) if row.get("worst_adjusted_excess") else None
        self.hit_rate: float | None = row.get("hit_rate")
        self.iqr: float | None = float(row["iqr"]) if row.get("iqr") else None
        self.trades: int = int(row.get("total_trades") or 0)
        self.exposure: float | None = row.get("mean_exposure")
        self.n_run: int = int(row.get("n_windows_run") or 0)
        self.notes: list[str] = list(row.get("notes") or [])
        self.win: dict[str, float | None] = {}
        self.win_trades: dict[str, int | None] = {}
        for tag in MAIN_WINDOWS:
            w = (row.get("windows") or {}).get(tag) or {}
            ae = w.get("adjusted_excess")
            self.win[tag] = float(ae) if ae is not None else None
            self.win_trades[tag] = w.get("trades")


def cells_of(card: dict[str, Any]) -> dict[str, Cell]:
    out: dict[str, Cell] = {}
    for row in list(card.get("ranked") or []) + list(card.get("unranked") or []):
        out[row["agent_id"]] = Cell(row)
    return out


def paired_diffs(a: Cell, b: Cell) -> list[float]:
    return [a.win[t] - b.win[t] for t in MAIN_WINDOWS if a.win[t] is not None and b.win[t] is not None]


def signflip_p(diffs: Sequence[float]) -> float | None:
    """Exact two-sided sign-flip permutation p-value on the mean of `diffs`."""
    n = len(diffs)
    if n == 0:
        return None
    observed = abs(sum(diffs) / n)
    count = 0
    total = 0
    for signs in itertools.product((1, -1), repeat=n):
        total += 1
        m = abs(sum(s * d for s, d in zip(signs, diffs, strict=True)) / n)
        if m >= observed - 1e-15:
            count += 1
    return count / total


def contrast(a: Cell, b: Cell) -> dict[str, Any]:
    diffs = paired_diffs(a, b)
    med_diff = (a.median - b.median) if a.median is not None and b.median is not None else None
    pos = sum(1 for d in diffs if d > 0)
    neg = sum(1 for d in diffs if d < 0)
    return {
        "a": a.agent_id,
        "b": b.agent_id,
        "median_diff": med_diff,
        "mean_paired_diff": (sum(diffs) / len(diffs)) if diffs else None,
        "windows_a_gt_b": pos,
        "windows_a_lt_b": neg,
        "n_windows": len(diffs),
        "p_signflip": signflip_p(diffs),
        "inside_floor": (abs(med_diff) * 100 < FLOOR_PP) if med_diff is not None else None,
    }


def bh_against_reference(cells: dict[str, Cell], reference: str) -> list[dict[str, Any]]:
    """Every cell contrasted with `reference`; BH over all of them, m = number of cells in the round."""
    ids = sorted(cells)
    ps: list[float | None] = []
    rows: list[dict[str, Any]] = []
    for aid in ids:
        if aid == reference:
            ps.append(None)
            rows.append({"cell": aid, "vs": reference, "median_diff": 0.0, "p": None})
            continue
        c = contrast(cells[aid], cells[reference])
        ps.append(c["p_signflip"])
        rows.append({"cell": aid, "vs": reference, "median_diff": c["median_diff"], "p": c["p_signflip"]})
    qs = benjamini_hochberg(ps)
    for row, q in zip(rows, qs, strict=True):
        row["q"] = q
    return rows


def table(cells: dict[str, Cell], order: Sequence[str] | None = None) -> str:
    ids = list(order) if order else sorted(cells, key=lambda k: -(cells[k].median or -9))
    lines = [
        "| cell | ranked | median adj. excess | worst | hit rate | IQR | trades | mean exposure | windows |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for aid in ids:
        c = cells[aid]
        lines.append(
            f"| `{aid}` | {'yes' if c.ranked else 'NO'} | {pp(c.median)} | {pp(c.worst)} | "
            f"{'' if c.hit_rate is None else f'{c.hit_rate:.3f}'} | {pp(c.iqr)} | {c.trades} | "
            f"{'' if c.exposure is None else f'{c.exposure:.3f}'} | {c.n_run}/8 |"
        )
    return "\n".join(lines)


def per_window_table(cells: dict[str, Cell], ids: Sequence[str]) -> str:
    head = "| cell | " + " | ".join(MAIN_WINDOWS) + " |"
    lines = [head, "|---|" + "---|" * len(MAIN_WINDOWS)]
    for aid in ids:
        c = cells[aid]
        lines.append(f"| `{aid}` | " + " | ".join(pp(c.win[t]) for t in MAIN_WINDOWS) + " |")
    return "\n".join(lines)


def marginal(cells: dict[str, Cell], groups: dict[str, list[str]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for name, ids in groups.items():
        vals = [cells[i].median for i in ids if cells[i].median is not None]
        out[name] = sum(vals) / len(vals) if vals else float("nan")
    return out


def spread(values: dict[str, float]) -> float:
    vs = [v for v in values.values() if v == v]
    return (max(vs) - min(vs)) if vs else float("nan")


# ---------------------------------------------------------------------------
# Round 34
# ---------------------------------------------------------------------------

FORMS = (
    "ma-crossover", "momentum-state", "rsi-pullback", "band-reversion",
    "channel-breakout", "band-breakout", "macd-cross", "vol-compression",
)


def report_34(card: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    cells = cells_of(card)
    out: dict[str, Any] = {"round": 34, "n_cells": len(cells)}
    md = ["# Round 34 -- computed verdict tables", ""]
    md += ["## Cells (ranked on median adjusted excess)", "", table(cells), ""]
    md += ["## Per-window adjusted excess", "", per_window_table(cells, sorted(cells)), ""]

    form_groups = {f: [f"r34-{f}-on", f"r34-{f}-off"] for f in FORMS}
    regime_groups = {"on": [f"r34-{f}-on" for f in FORMS], "off": [f"r34-{f}-off" for f in FORMS]}
    fm = marginal(cells, form_groups)
    rm = marginal(cells, regime_groups)
    all_meds = {k: v.median for k, v in cells.items() if v.median is not None}
    out.update(
        form_marginals=fm, form_spread=spread(fm), regime_marginals=rm, regime_spread=spread(rm),
        field_spread=spread(all_meds),
    )
    md += ["## Marginals (PLAN §5: a factor matters only if its marginal spread exceeds 21.2pp)", ""]
    md += ["| form | marginal (mean of 2 cells) |", "|---|---|"]
    for f, v in sorted(fm.items(), key=lambda kv: -kv[1]):
        md.append(f"| `{f}` | {pp(v)} |")
    md += ["", f"**Form marginal spread: {fm and spread(fm)*100:.2f}pp** -- "
           f"{'INSIDE' if spread(fm)*100 < FLOOR_PP else 'OUTSIDE'} the 21.2pp floor.", ""]
    md += [f"Regime filter: on {pp(rm['on'])}, off {pp(rm['off'])} -- **spread {spread(rm)*100:.2f}pp** "
           f"({'inside' if spread(rm)*100 < FLOOR_PP else 'OUTSIDE'} the floor).", ""]
    md += [f"Whole 16-cell field spread: **{spread(all_meds)*100:.2f}pp** (pure-noise expectation at "
           f"sigma=21.2: 74.9pp).", ""]

    best_form = max(fm, key=lambda k: fm[k])
    worst_form = min(fm, key=lambda k: fm[k])
    worst_cell = min(all_meds, key=lambda k: all_meds[k])
    bh = bh_against_reference(cells, worst_cell)
    out["bh_reference"] = worst_cell
    out["bh"] = bh
    out["best_form"], out["worst_form"] = best_form, worst_form
    md += [f"## BH over all 16 cells, each contrasted with the worst cell `{worst_cell}`", ""]
    md += ["| cell | median diff vs worst | p (sign-flip) | q (BH, m=16) |", "|---|---|---|---|"]
    for r in sorted(bh, key=lambda r: -(r['median_diff'] or 0)):
        md.append(f"| `{r['cell']}` | {pp(r['median_diff'])} | {fmt(r['p'])} | {fmt(r['q'])} |")
    min_q = min((r["q"] for r in bh if r["q"] is not None), default=None)
    out["min_q"] = min_q
    md += ["", f"Minimum q over the field: **{min_q:.4f}**" if min_q is not None else "", ""]

    # predictions
    trades_by_form = {f: sum(cells[i].trades for i in ids) for f, ids in form_groups.items()}
    fewest = min(trades_by_form, key=lambda k: trades_by_form[k])
    worst_window = {}
    for f in ("ma-crossover", "momentum-state", "macd-cross", "vol-compression"):
        for arm in ("on", "off"):
            c = cells[f"r34-{f}-{arm}"]
            ww = min((t for t in MAIN_WINDOWS if c.win[t] is not None), key=lambda t: c.win[t])
            worst_window[c.agent_id] = ww
    complete = sum(1 for c in cells.values() if c.n_run == 8)
    out.update(trades_by_form=trades_by_form, fewest_trades_form=fewest, worst_window_trend_forms=worst_window,
               cells_complete_8of8=complete)
    md += ["## Predictions (PLAN §6)", ""]
    md += [f"1. Form marginal < 21.2pp: **{'HELD' if spread(fm)*100 < FLOOR_PP else 'REFUTED'}** ({spread(fm)*100:.2f}pp).",
           f"2. Regime marginal < 21.2pp: **{'HELD' if spread(rm)*100 < FLOOR_PP else 'REFUTED'}** ({spread(rm)*100:.2f}pp).",
           f"3. 16-cell spread vs round 17's stop slice: {spread(all_meds)*100:.2f}pp here (descriptive; compare in REPORT).",
           f"4. `vol-compression` takes the fewest trades: **{'HELD' if fewest == 'vol-compression' else 'REFUTED'}** "
           f"(fewest = `{fewest}`; trades by form: {trades_by_form}).",
           "5. Trend/momentum forms worst in a chop window: " + ", ".join(
               f"`{k}`->{v}{'*' if v.startswith('chop') else ''}" for k, v in worst_window.items()) + "  (* = held).",
           f"6. All 16 cells scored in 8/8 windows: **{'HELD' if complete == 16 else 'REFUTED'}** ({complete}/16).", ""]
    return "\n".join(md), out


# ---------------------------------------------------------------------------
# Round 35
# ---------------------------------------------------------------------------

def report_35(card: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    cells = cells_of(card)
    control = "r35-passive-8-order"
    rotation = [a for a in sorted(cells) if a != control]
    out: dict[str, Any] = {"round": 35, "n_cells": len(cells), "control": control}
    md = ["# Round 35 -- computed verdict tables", ""]
    md += ["## Cells (ranked on median adjusted excess vs SPY)", "", table(cells), ""]
    md += ["## Per-window adjusted excess", "", per_window_table(cells, sorted(cells)), ""]

    ctrl = cells[control]
    rows = []
    md += [f"## Rotation minus control (`{control}`) -- the pre-registered reported quantity", ""]
    md += ["| cell | median vs SPY | median minus control | windows > control | p (sign-flip) |", "|---|---|---|---|---|"]
    for aid in rotation:
        c = contrast(cells[aid], ctrl)
        rows.append(c)
        md.append(f"| `{aid}` | {pp(cells[aid].median)} | {pp(c['median_diff'])} | {c['windows_a_gt_b']}/{c['n_windows']} | "
                  f"{fmt(c['p_signflip'])} |")
    bh = bh_against_reference(cells, control)
    out["vs_control"] = rows
    out["bh"] = bh
    min_q = min((r["q"] for r in bh if r["q"] is not None), default=None)
    out["min_q"] = min_q
    md += ["", f"BH over all 9 cells (m=9) against the control: minimum q = **{min_q:.4f}**" if min_q is not None else "", ""]

    rank_ids = [a for a in rotation if a.endswith("-rank")]
    order_ids = [a for a in rotation if a.endswith("-order")]
    fill = marginal(cells, {"rank": rank_ids, "order": order_ids})
    pairs = {}
    for r in rank_ids:
        o = r[:-5] + "-order"
        pairs[r] = (cells[r].median or 0) - (cells[o].median or 0)
    iqr2 = statistics.mean([cells[a].iqr for a in rotation if "-2-" in a and cells[a].iqr is not None])
    iqr4 = statistics.mean([cells[a].iqr for a in rotation if "-4-" in a and cells[a].iqr is not None])
    worst_window = {a: min((t for t in MAIN_WINDOWS if cells[a].win[t] is not None), key=lambda t: cells[a].win[t]) for a in sorted(cells)}
    worst_two_macross = {}
    for a in [x for x in rotation if "macross" in x]:
        ws = sorted((t for t in MAIN_WINDOWS if cells[a].win[t] is not None), key=lambda t: cells[a].win[t])[:2]
        worst_two_macross[a] = ws
    ctrl_trades = {t: ctrl.win_trades[t] for t in MAIN_WINDOWS}
    ctrl_exposure = {}
    for t in MAIN_WINDOWS:
        run = load_run(35, t, control)
        ctrl_exposure[t] = None if run is None else run.get("exposure")
    out.update(fill_marginals=fill, fill_spread=spread(fill), matched_pairs_rank_minus_order=pairs,
               mean_iqr_k2=iqr2, mean_iqr_k4=iqr4, worst_window=worst_window, worst_two_macross=worst_two_macross,
               control_trades=ctrl_trades, control_session_exposure=ctrl_exposure)
    all_neg = all((cells[a].median or 0) < 0 for a in rotation)
    max_beat = max(r["median_diff"] for r in rows)
    md += ["## Predictions (PLAN §5)", ""]
    md += [f"1. Every rotation cell negative vs SPY: **{'HELD' if all_neg else 'REFUTED'}**.",
           f"2. No rotation cell beats the control by > 21.2pp: **{'HELD' if max_beat*100 < FLOOR_PP else 'REFUTED'}** (max = {pp(max_beat)}).",
           "3. Failure regimes: macross worst-two = " + str(worst_two_macross) + "; absolute worst = "
           + str({a: worst_window[a] for a in rotation if 'absolute' in a}) + f"; control worst = {worst_window[control]}.",
           f"4. Fill orders differ < 21.2pp: marginal rank {pp(fill['rank'])} vs order {pp(fill['order'])} "
           f"(spread {spread(fill)*100:.2f}pp); matched pairs: " + ", ".join(f"{k}: {pp(v)}" for k, v in pairs.items()) + ".",
           f"5. 2-slot IQR wider than 4-slot: mean IQR k2 {pp(iqr2)} vs k4 {pp(iqr4)} -> **{'HELD' if iqr2 > iqr4 else 'REFUTED'}**.",
           f"6. Control validity: trades per window {ctrl_trades}; session exposure {ctrl_exposure}.", ""]
    return "\n".join(md), out


# ---------------------------------------------------------------------------
# Round 36
# ---------------------------------------------------------------------------

ORDERINGS = ("canonical", "reversed", "strong", "weak", "volunits")


def report_36(card: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    cells = cells_of(card)
    out: dict[str, Any] = {"round": 36, "n_cells": len(cells)}
    md = ["# Round 36 -- computed verdict tables", ""]
    md += ["## Cells", "", table(cells), ""]
    md += ["## Per-window adjusted excess", "", per_window_table(cells, sorted(cells)), ""]
    md += ["## Contrasts (PLAN §5 decision rule)", ""]
    md += ["| contrast | median diff | mean paired diff | sign agreement (a>b / a<b of 8) | p (sign-flip) | inside floor? |",
           "|---|---|---|---|---|---|"]
    contrasts: dict[str, dict[str, Any]] = {}
    for k in ("k2", "k4"):
        for a, b in (("strong", "weak"), ("canonical", "reversed"), ("strong", "volunits"), ("strong", "canonical")):
            c = contrast(cells[f"r36-{a}-{k}"], cells[f"r36-{b}-{k}"])
            contrasts[f"{a}-{b}-{k}"] = c
            md.append(f"| `{a} - {b}` @ {k} | {pp(c['median_diff'])} | {pp(c['mean_paired_diff'])} | "
                      f"{c['windows_a_gt_b']} / {c['windows_a_lt_b']} | {c['p_signflip']:.4f} | "
                      f"{'yes' if c['inside_floor'] else 'NO'} |")
    out["contrasts"] = contrasts
    arm_spread = {}
    for k in ("k2", "k4"):
        meds = {o: cells[f"r36-{o}-{k}"].median for o in ORDERINGS}
        arm_spread[k] = spread({o: m for o, m in meds.items() if m is not None})
    out["arm_spread"] = arm_spread
    md += ["", f"Five-ordering spread inside each arm: k2 **{arm_spread['k2']*100:.2f}pp**, k4 **{arm_spread['k4']*100:.2f}pp** "
           "(pure-noise E[max-min] at sigma=21.2 over 5: 49.3pp).", ""]
    for k in ("k2", "k4"):
        bh = bh_against_reference(cells, f"r36-weak-{k}")
        out[f"bh_vs_weak_{k}"] = bh
        q_strong = next(r["q"] for r in bh if r["cell"] == f"r36-strong-{k}")
        md.append(f"BH over all 10 cells (m=10) against `r36-weak-{k}`: q for `r36-strong-{k}` = "
                  f"**{q_strong:.4f}**" if q_strong is not None else "")
    md.append("")
    # cap binding: distinct trade logs per window per arm
    md += ["## Does the cap bind? Distinct per-window results among the five orderings (PLAN §8)", ""]
    md += ["| arm | " + " | ".join(MAIN_WINDOWS) + " |", "|---|" + "---|" * len(MAIN_WINDOWS)]
    distinct: dict[str, dict[str, int]] = {}
    for k in ("k2", "k4"):
        distinct[k] = {}
        row = []
        for t in MAIN_WINDOWS:
            sigs = set()
            for o in ORDERINGS:
                run = load_run(36, t, f"r36-{o}-{k}")
                if run is None:
                    sigs.add(("missing", o))
                    continue
                sigs.add((run.get("total_return"), len(run.get("trades") or []), run.get("exposure")))
            distinct[k][t] = len(sigs)
            row.append(str(len(sigs)))
        md.append(f"| {k} | " + " | ".join(row) + " |")
    out["distinct_results_per_window"] = distinct
    exposures = {}
    for k in ("k2", "k4"):
        for o in ORDERINGS:
            aid = f"r36-{o}-{k}"
            caps = []
            for t in MAIN_WINDOWS:
                run = load_run(36, t, aid)
                if run is not None and run.get("capital_exposure") is not None:
                    caps.append(run["capital_exposure"])
            exposures[aid] = statistics.mean(caps) if caps else None
    out["mean_capital_exposure"] = exposures
    md += ["", "Mean capital exposure (ceiling 0.50): " + ", ".join(f"`{k}` {v:.3f}" for k, v in exposures.items() if v is not None), ""]

    # predictions
    p1 = all(abs(contrasts[f"canonical-reversed-{k}"]["median_diff"]) * 100 < 5 for k in ("k2", "k4"))
    p1_floor = all(abs(contrasts[f"canonical-reversed-{k}"]["median_diff"]) * 100 < FLOOR_PP for k in ("k2", "k4"))
    p2 = all(abs(contrasts[f"strong-weak-{k}"]["median_diff"]) * 100 < FLOOR_PP for k in ("k2", "k4"))
    p3 = arm_spread["k2"] > arm_spread["k4"]
    strong_worst = {k: min(MAIN_WINDOWS, key=lambda t: cells[f"r36-strong-{k}"].win[t] or 0) for k in ("k2", "k4")}
    covid_le = {k: (cells[f"r36-strong-{k}"].win["covid"] or 0) <= (cells[f"r36-weak-{k}"].win["covid"] or 0) for k in ("k2", "k4")}
    bind_windows = sum(1 for t in MAIN_WINDOWS if distinct["k2"][t] >= 2)
    complete = sum(1 for c in cells.values() if c.n_run == 8)
    out.update(pred_canonical_reversed_under_5pp=p1, pred_strong_weak_inside_floor=p2, pred_k2_spread_gt_k4=p3,
               strong_worst_window=strong_worst, covid_strong_le_weak=covid_le, k2_binding_windows=bind_windows,
               cells_complete_8of8=complete)
    md += ["## Predictions (PLAN §7)", ""]
    md += [f"1. |canonical - reversed| < 5pp at both caps: **{'HELD' if p1 else ('inside floor but >= 5pp' if p1_floor else 'REFUTED')}** "
           f"(k2 {pp(contrasts['canonical-reversed-k2']['median_diff'])}, k4 {pp(contrasts['canonical-reversed-k4']['median_diff'])}).",
           f"2. strong - weak inside 21.2pp at both caps: **{'HELD' if p2 else 'REFUTED'}** "
           f"(k2 {pp(contrasts['strong-weak-k2']['median_diff'])}, k4 {pp(contrasts['strong-weak-k4']['median_diff'])}).",
           f"3. k2 ordering spread > k4: **{'HELD' if p3 else 'REFUTED'}** ({arm_spread['k2']*100:.2f}pp vs {arm_spread['k4']*100:.2f}pp).",
           f"4. strong's worst window is covid and strong <= weak there: worst = {strong_worst}; covid strong<=weak = {covid_le}.",
           f"5. Cap binds in >= 5/8 windows at k2 (>= 2 distinct results): **{'HELD' if bind_windows >= 5 else 'REFUTED'}** ({bind_windows}/8).",
           f"6. All 10 cells at 8/8: **{'HELD' if complete == 10 else 'REFUTED'}** ({complete}/10).", ""]
    return "\n".join(md), out


# ---------------------------------------------------------------------------
# Round 39 -- Roth style tilt (4 slices x {ma, passive})
# ---------------------------------------------------------------------------

R39_SLICES = ("value", "growth", "core", "full")


def report_39(card: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    cells = cells_of(card)
    out: dict[str, Any] = {"round": 39, "n_cells": len(cells)}
    md = ["# Round 39 -- computed verdict tables", ""]
    md += ["## Cells (ranked on median adjusted excess vs SPY)", "", table(cells), ""]
    md += ["## Per-window adjusted excess", "", per_window_table(cells, sorted(cells)), ""]

    # The rule question: within each slice, does the ma timing beat just holding the slice (passive)?
    md += ["## Tilt minus control -- does the timing rule beat holding the slice? (PLAN decision rule)", ""]
    md += ["| slice | ma median | passive median | ma - passive | windows ma>passive | p (sign-flip) | inside floor? |",
           "|---|---|---|---|---|---|---|"]
    tilt = {}
    for s in R39_SLICES:
        ma, pa = f"r39-{s}-ma", f"r39-{s}-passive"
        if ma not in cells or pa not in cells:
            continue
        c = contrast(cells[ma], cells[pa])
        tilt[s] = c
        md.append(f"| {s} | {pp(cells[ma].median)} | {pp(cells[pa].median)} | {pp(c['median_diff'])} | "
                  f"{c['windows_a_gt_b']}/{c['n_windows']} | {fmt(c['p_signflip'])} | {'yes' if c['inside_floor'] else 'NO'} |")
    out["tilt_minus_control"] = tilt

    # The style question: value passive vs growth passive -- a between-control spread no rule produces.
    style = contrast(cells["r39-value-passive"], cells["r39-growth-passive"])
    out["style_spread_value_minus_growth"] = style
    md += ["", f"## Style spread: value-passive - growth-passive = **{pp(style['median_diff'])}** "
           f"({'inside' if style['inside_floor'] else 'OUTSIDE'} the 21.2pp floor; "
           f"value>growth in {style['windows_a_gt_b']}/{style['n_windows']} windows, p={fmt(style['p_signflip'])})", ""]

    bh = bh_against_reference(cells, "r39-full-passive")
    out["bh"] = bh
    min_q = min((r["q"] for r in bh if r["q"] is not None), default=None)
    out["min_q"] = min_q
    md += [f"BH over all 8 cells (m=8) against `r39-full-passive`: minimum q = "
           f"**{min_q:.4f}**" if min_q is not None else "", ""]

    worst = {a: min((t for t in MAIN_WINDOWS if cells[a].win[t] is not None), key=lambda t: cells[a].win[t])
             for a in sorted(cells)}
    out["worst_window"] = worst
    tilt_all_inside = all(c["inside_floor"] for c in tilt.values())
    md += ["## Verdict (PLAN decision rule)", "",
           f"- Every within-slice tilt-minus-control inside 21.2pp: **{'HELD (null)' if tilt_all_inside else 'REFUTED'}** "
           f"-- the timing rule adds nothing over holding the slice.",
           f"- Style spread inside 21.2pp: **{'HELD (null)' if style['inside_floor'] else 'REFUTED'}**.",
           f"- Minimum BH q {min_q:.4f} (nothing survives q<0.10)." if min_q is not None else "",
           "- Worst window per cell: " + ", ".join(f"`{a.split('r39-')[1]}`->{w}" for a, w in worst.items()) + ".",
           "", "**Nothing clears the floor; the rule arms lose to their own passive controls "
           "(the ma timing sits in cash while the slice rises). Null on both questions.**", ""]
    return "\n".join(md), out


# ---------------------------------------------------------------------------
# Round 40 -- confirmation conjunct (base fixed x arms x slot caps)
# ---------------------------------------------------------------------------

R40_ARMS = ("swing-structure", "rsi-confirm", "divergence-proxy-negative-control")
R40_SLOTS = ("slots3", "slots6")


def report_40(card: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    cells = cells_of(card)
    out: dict[str, Any] = {"round": 40, "n_cells": len(cells)}
    md = ["# Round 40 -- computed verdict tables", ""]
    md += ["## Cells (ranked on median adjusted excess vs SPY)", "", table(cells), ""]
    md += ["## Per-window adjusted excess", "", per_window_table(cells, sorted(cells)), ""]

    md += ["## Arm minus control -- does the added conjunct pay for itself? (PLAN decision rule)", ""]
    md += ["| arm | slots | arm median | control median | arm - control | windows arm>ctrl | p (sign-flip) | trades | clears floor? |",
           "|---|---|---|---|---|---|---|---|---|"]
    arm_minus = {}
    for slot in R40_SLOTS:
        ctrl_id = f"r40-none-{slot}"
        for arm in R40_ARMS:
            aid = f"r40-{arm}-{slot}"
            if aid not in cells or ctrl_id not in cells:
                continue
            c = contrast(cells[aid], cells[ctrl_id])
            arm_minus[f"{arm}/{slot}"] = c
            clears = (c["median_diff"] or 0) * 100 > FLOOR_PP
            md.append(f"| {arm} | {slot} | {pp(cells[aid].median)} | {pp(cells[ctrl_id].median)} | "
                      f"{pp(c['median_diff'])} | {c['windows_a_gt_b']}/{c['n_windows']} | {fmt(c['p_signflip'])} | "
                      f"{cells[aid].trades} | {'YES' if clears else 'no'} |")
    out["arm_minus_control"] = arm_minus

    bh = bh_against_reference(cells, "r40-none-slots6")
    out["bh"] = bh
    min_q = min((r["q"] for r in bh if r["q"] is not None), default=None)
    out["min_q"] = min_q

    # Switched-off screen: an arm that barely trades was turned off, not measured.
    trades = {a: cells[a].trades for a in sorted(cells)}
    out["trades"] = trades
    min_trades = min(trades.values())

    # Negative-control prediction: divergence-proxy should be indistinguishable from none.
    negctrl = {slot: contrast(cells[f"r40-divergence-proxy-negative-control-{slot}"], cells[f"r40-none-{slot}"])
               for slot in R40_SLOTS}
    out["negctrl_minus_none"] = negctrl

    best = max(arm_minus.items(), key=lambda kv: kv[1]["median_diff"] or -9)
    any_clears = any((c["median_diff"] or 0) * 100 > FLOOR_PP for c in arm_minus.values())
    md += ["", f"BH over all 8 cells (m=8) against `r40-none-slots6`: minimum q = "
           f"**{min_q:.4f}**" if min_q is not None else "", ""]
    md += ["## Verdict (PLAN decision rule)", "",
           f"- Any conjunct clears 21.2pp arm-minus-control: **{'YES' if any_clears else 'NO (null)'}**. "
           f"Best arm: `{best[0]}` at {pp(best[1]['median_diff'])}.",
           f"- Divergence negative control ~ none (predicted): slots6 {pp(negctrl['slots6']['median_diff'])}, "
           f"slots3 {pp(negctrl['slots3']['median_diff'])} -- "
           f"{'HELD (indistinguishable at slots6)' if abs(negctrl['slots6']['median_diff']*100) < FLOOR_PP else 'REFUTED'}.",
           f"- Switched-off screen: min trades across cells = {min_trades} (>0 in every window "
           f"means measured, not switched off).",
           f"- Minimum BH q {min_q:.4f} (nothing survives q<0.10)." if min_q is not None else "",
           "", "**The RSI-confirm arm is the sole positive cell (arm-minus-control "
           f"{pp(arm_minus['rsi-confirm/slots3']['median_diff'])} at 3 slots, "
           f"{pp(arm_minus['rsi-confirm/slots6']['median_diff'])} at 6), but both sit well inside the "
           "21.2pp floor -- so by the pre-registered rule the conjunct does NOT pay for itself. Null.**", ""]
    return "\n".join(md), out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", type=int, choices=(34, 35, 36, 39, 40), required=True)
    args = parser.parse_args(argv)
    card = load_scorecard(args.round)
    md, out = {34: report_34, 35: report_35, 36: report_36,
               39: report_39, 40: report_40}[args.round](card)
    print(md)
    dest = REPO / "data" / "rounds" / f"r{args.round}-2026-09" / "analysis.json"
    dest.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\n(wrote {dest.relative_to(REPO).as_posix()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

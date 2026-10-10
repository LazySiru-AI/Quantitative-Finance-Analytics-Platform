"""Verdict tables for round 47 -- dip / trim / dip-trim arms against round 44's passive control, on
three of round 44's baskets -- from `data/rounds/r47-2026-09/scorecard.json`.

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round47_report.py

`ROUND-47-PLAN.md` pre-registered a decision rule and a set of predictions before any card ran. This
module computes exactly the quantities that rule names -- arm-minus-passive per basket, the same
contrast restricted to the six fair windows and the two hindsight windows, `dip-trim` against the
better of its two component arms, a days-to-first-entry table for the two dip-entry arms built from the
run files (not the scorecard, which does not carry per-trade dates), and a Benjamini-Hochberg pass
whose denominator is every cell this round runs -- and prints them as markdown so `REPORT.md` (written
separately, outside this tool's scope) quotes numbers this code produced. It writes the same content to
`data/rounds/r47-2026-09/analysis.json`.

**Reuses `round34_36_report.py`'s machinery rather than re-deriving it**, exactly the way
`round44_report.py` does: `strategy-program/tools/` is not inside a legal Python package (the hyphen),
so both `round34_36_report.py` and `windows.py` are loaded by file path for `load_scorecard`, `cells_of`,
`contrast`, `bh_against_reference`, `table`, `per_window_table`, `FLOOR_PP`, `MAIN_WINDOWS` and the
window date ranges. Neither is edited, per this round's stated scope.

**Statistics, stated plainly** (inherited from the imported module, restated here because a reader of
this file's output should not have to open another one to know what a number means). A pairwise
contrast between two cells is the vector of their eight paired per-window `adjusted_excess`
differences; its p-value is an exact two-sided sign-flip permutation test on the mean paired difference
(2^8 = 256 sign assignments enumerated). The "six fair windows" and "two hindsight windows" medians
below are the median of the *paired* per-window differences restricted to that window subset, not a
re-scored median-of-medians -- the same convention `round44_report.py` uses, consistent with how
`ROUND-44-PLAN.md` section 5 prediction 3 states the fair test and how `ROUND-47-PLAN.md` reuses it.

**Exits 1, with a plain message, if the scorecard is absent** -- this file computes verdict tables from
a run this round's authoring step (`round47.py`) does not itself perform (this session's brief
explicitly excludes running `run_round.sh`/`score.py`), so a missing scorecard is the expected state
immediately after authoring and must fail loudly rather than print an empty report.

**Not investment advice.** Every figure here is a backtest on price-only bars against a benchmark round
44 already flagged as a poor fit for `power` and `defense`.
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

# Load windows.py by file path for the eight main windows' start dates (days-to-first-entry needs the
# window start; nothing else in this file needs windows.py, so it is loaded, not imported as a package
# -- `strategy-program` is not one).
_wspec = importlib.util.spec_from_file_location(
    "round47_windows", REPO / "strategy-program" / "tools" / "windows.py"
)
assert _wspec is not None and _wspec.loader is not None
_windows = importlib.util.module_from_spec(_wspec)
sys.modules.setdefault("round47_windows", _windows)
_wspec.loader.exec_module(_windows)

WINDOW_START: dict[str, Any] = {tag: _windows.WINDOWS[tag][0] for tag in MAIN_WINDOWS}

ROUND = 47
BASKETS = ("power", "defense", "control")
ARMS = ("passive", "dip", "trim", "dip-trim")
NON_PASSIVE_ARMS = ("dip", "trim", "dip-trim")
DIP_ARMS = ("dip", "dip-trim")  # both share DIP_ENTRY -- both are "dip cells" for the entry-delay read
CONTROL = "control"

#: The hindsight split, reused verbatim from round 44 (`ROUND-44-PLAN.md` section 5 prediction 3;
#: `ROUND-47-PLAN.md` section 5 restates it for this round's field): every note in the persona corpus
#: has `published = null`, so `bull-2024` and `recent` are in-sample to the hypothesis.
FAIR_WINDOWS = ("gfc", "chop-2011", "chop-2015", "q4-2018", "covid", "bear-2022")
HINDSIGHT_WINDOWS = ("bull-2024", "recent")
assert set(FAIR_WINDOWS) | set(HINDSIGHT_WINDOWS) == set(MAIN_WINDOWS)


def _paired_median(a, b, windows: tuple[str, ...]) -> float | None:
    """Median of the paired per-window `adjusted_excess` differences `a - b`, restricted to `windows`.
    Identical convention to `round44_report.py::_paired_median`."""
    diffs = [a.win[t] - b.win[t] for t in windows if a.win[t] is not None and b.win[t] is not None]
    if not diffs:
        return None
    return statistics.median(diffs)


def _load_run(round_n: int, window: str, agent_id: str) -> dict[str, Any] | None:
    path = REPO / "data" / "rounds" / f"r{round_n}-2026-09" / "results" / window / "runs" / f"r1-{agent_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _days_to_first_entry(agent_id: str) -> dict[str, int | None]:
    """For one dip-entry cell: per main window, the first trade's `entry_date` minus the window's own
    start date, in calendar days. `None` when the run file is absent or the card took zero trades in
    that window -- reported as such, not treated as zero (zero would claim "entered on day zero", which
    a no-trade window does not support)."""
    out: dict[str, int | None] = {}
    for window in MAIN_WINDOWS:
        run = _load_run(ROUND, window, agent_id)
        if run is None or not run.get("trades"):
            out[window] = None
            continue
        import datetime as dt

        first_entry = dt.date.fromisoformat(run["trades"][0]["entry_date"])
        out[window] = (first_entry - WINDOW_START[window]).days
    return out


def load_report() -> tuple[str, dict[str, Any]]:
    card = load_scorecard(ROUND)
    cells = cells_of(card)
    out: dict[str, Any] = {"round": ROUND, "n_cells": len(cells)}
    md = [
        "# Round 47 -- computed verdict tables",
        "",
        "Not investment advice. See `strategy-program/ROUND-47-PLAN.md` for the pre-registration.",
        "",
    ]
    md += ["## Cells (ranked on median adjusted excess vs SPY)", "", table(cells), ""]
    md += ["## Per-window adjusted excess", "", per_window_table(cells, sorted(cells)), ""]

    # -----------------------------------------------------------------
    # Arm minus passive, within basket -- the round's one decision axis
    # -----------------------------------------------------------------
    md += [
        "## Arm minus passive, within basket",
        "",
        "| basket | arm | arm median | passive median | 8-window median diff | 6 fair windows "
        "(gfc..bear-2022) | 2 hindsight windows (bull-2024, recent) | windows arm>passive | "
        "p (sign-flip) | mean exposure arm vs passive | trades arm vs passive | clears floor "
        "(21.2pp)? |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    arm_vs_passive: dict[str, dict[str, Any]] = {}
    for basket in BASKETS:
        p_id = f"r47-{basket}-passive"
        if p_id not in cells:
            continue
        p = cells[p_id]
        arm_vs_passive[basket] = {}
        for arm in NON_PASSIVE_ARMS:
            a_id = f"r47-{basket}-{arm}"
            if a_id not in cells:
                continue
            a = cells[a_id]
            contr = contrast(a, p)
            fair = _paired_median(a, p, FAIR_WINDOWS)
            hindsight = _paired_median(a, p, HINDSIGHT_WINDOWS)
            arm_vs_passive[basket][arm] = {
                "contrast": contr, "fair_median_diff": fair, "hindsight_median_diff": hindsight,
                "mean_exposure_arm": a.exposure, "mean_exposure_passive": p.exposure,
                "trades_arm": a.trades, "trades_passive": p.trades,
            }
            exp_txt = (
                f"{a.exposure:.3f} vs {p.exposure:.3f}"
                if a.exposure is not None and p.exposure is not None
                else "n/a"
            )
            md.append(
                f"| {basket} | {arm} | {pp(a.median)} | {pp(p.median)} | {pp(contr['median_diff'])} | "
                f"{pp(fair)} | {pp(hindsight)} | {contr['windows_a_gt_b']}/{contr['n_windows']} | "
                f"{fmt(contr['p_signflip'])} | {exp_txt} | {a.trades} vs {p.trades} | "
                f"{'YES' if (contr['median_diff'] or 0) * 100 > FLOOR_PP else 'no'} |"
            )
    out["arm_vs_passive"] = arm_vs_passive

    # -----------------------------------------------------------------
    # dip-trim vs the better of its two component arms (plan prediction 4/5)
    # -----------------------------------------------------------------
    md += [
        "",
        "## dip-trim minus max(dip, trim), per basket",
        "",
        "| basket | dip median | trim median | dip-trim median | max(dip, trim) | dip-trim minus max "
        "| dip-trim <= max? |",
        "|---|---|---|---|---|---|---|",
    ]
    combo: dict[str, Any] = {}
    combo_le_count = 0
    combo_n = 0
    for basket in BASKETS:
        ids = {arm: f"r47-{basket}-{arm}" for arm in ("dip", "trim", "dip-trim")}
        if not all(i in cells for i in ids.values()):
            continue
        dip_m = cells[ids["dip"]].median
        trim_m = cells[ids["trim"]].median
        dt_m = cells[ids["dip-trim"]].median
        if dip_m is None or trim_m is None or dt_m is None:
            continue
        best = max(dip_m, trim_m)
        diff = dt_m - best
        le = diff <= 0
        combo_n += 1
        combo_le_count += 1 if le else 0
        combo[basket] = {
            "dip_median": dip_m, "trim_median": trim_m, "dip_trim_median": dt_m,
            "max_dip_trim": best, "dip_trim_minus_max": diff, "dip_trim_le_max": le,
        }
        md.append(
            f"| {basket} | {pp(dip_m)} | {pp(trim_m)} | {pp(dt_m)} | {pp(best)} | {pp(diff)} | "
            f"{'YES' if le else 'no'} |"
        )
    out["dip_trim_vs_max_component"] = combo
    out["dip_trim_le_max_in_n_of_3"] = combo_le_count
    md += [
        "",
        f"`dip-trim <= max(dip, trim)` in **{combo_le_count} of {combo_n}** baskets -- predicted in "
        f"at least 2 of 3: **{'HELD' if combo_le_count >= 2 else 'REFUTED'}**.",
        "",
    ]

    # -----------------------------------------------------------------
    # Days-to-first-entry, both dip-entry arms, per window (plan prediction 2)
    # -----------------------------------------------------------------
    md += [
        "## Days-to-first-entry, dip-entry cells (dip, dip-trim), per window",
        "",
        "First trade's `entry_date` minus the window's own start date, from the run files "
        f"(`data/rounds/r{ROUND}-2026-09/results/<window>/runs/r1-<agent_id>.json`). `--` = no trade "
        "in that window.",
        "",
        "| cell | " + " | ".join(MAIN_WINDOWS) + " |",
        "|---|" + "---|" * len(MAIN_WINDOWS),
    ]
    days_to_first_entry: dict[str, dict[str, int | None]] = {}
    for basket in BASKETS:
        for arm in DIP_ARMS:
            agent_id = f"r47-{basket}-{arm}"
            days = _days_to_first_entry(agent_id)
            days_to_first_entry[agent_id] = days
            md.append(
                f"| `{agent_id}` | "
                + " | ".join("--" if days[w] is None else str(days[w]) for w in MAIN_WINDOWS)
                + " |"
            )
    out["days_to_first_entry"] = days_to_first_entry
    md.append("")

    # -----------------------------------------------------------------
    # Trim: bull-2024 (predicted to lose) vs recent (not predicted, reported both ways) -- plan pred. 4
    # -----------------------------------------------------------------
    md += [
        "## Trim minus passive, bull-2024 vs recent, per basket (plan prediction 4)",
        "",
        "Round 44 found the trim arm loses to its own passive control in `bull-2024` in every basket "
        "but *won* in `recent` for `power` and `defense`. This round pre-registers both windows "
        "separately for the same three arms and predicts only `bull-2024` (a loss); `recent` is "
        "reported without a directional prediction.",
        "",
        "| basket | trim minus passive, bull-2024 | trim minus passive, recent | bull-2024 loss "
        "predicted, held? |",
        "|---|---|---|---|",
    ]
    trim_regime: dict[str, Any] = {}
    for basket in BASKETS:
        t_id, p_id = f"r47-{basket}-trim", f"r47-{basket}-passive"
        if t_id not in cells or p_id not in cells:
            continue
        t, p = cells[t_id], cells[p_id]
        bull = (
            t.win["bull-2024"] - p.win["bull-2024"]
            if t.win["bull-2024"] is not None and p.win["bull-2024"] is not None
            else None
        )
        recent = (
            t.win["recent"] - p.win["recent"]
            if t.win["recent"] is not None and p.win["recent"] is not None
            else None
        )
        trim_regime[basket] = {"bull_2024": bull, "recent": recent}
        held = bull is not None and bull < 0
        md.append(
            f"| {basket} | {pp(bull)} | {pp(recent)} | "
            f"{'n/a' if bull is None else ('YES' if held else 'no')} |"
        )
    out["trim_minus_passive_bull_vs_recent"] = trim_regime

    # -----------------------------------------------------------------
    # Benjamini-Hochberg over all 12 cells against the control-passive reference
    # -----------------------------------------------------------------
    bh = bh_against_reference(cells, f"r47-{CONTROL}-passive")
    out["bh"] = bh
    min_q = min((r["q"] for r in bh if r["q"] is not None), default=None)
    out["min_q"] = min_q
    md += [
        "",
        f"## BH over all {len(cells)} cells (m={len(cells)}) against `r47-{CONTROL}-passive`",
        "",
        "| cell | median diff vs control-passive | p (sign-flip) | q (BH) |",
        "|---|---|---|---|",
    ]
    for r in sorted(bh, key=lambda r: -(r["median_diff"] or 0)):
        md.append(f"| `{r['cell']}` | {pp(r['median_diff'])} | {fmt(r['p'])} | {fmt(r['q'])} |")
    md += ["", f"Minimum q over the field: **{min_q:.4f}**" if min_q is not None else "", ""]

    # -----------------------------------------------------------------
    # Verdict
    # -----------------------------------------------------------------
    any_edge = any(
        (row["contrast"]["median_diff"] or 0) * 100 > FLOOR_PP
        for basket_rows in arm_vs_passive.values()
        for row in basket_rows.values()
    )
    out["any_arm_edge_before_bh"] = any_edge
    out["clears_decision_rule"] = bool(any_edge and min_q is not None and min_q < 0.10)
    md += [
        "## Verdict (PLAN section 4 decision rule: arm - passive > 21.2pp AND BH q<0.10, m=12)",
        "",
        f"- Any arm beats its own basket's passive by >21.2pp (before the BH check): "
        f"**{'YES' if any_edge else 'NO (null)'}**.",
        "- Minimum BH q over all 12 cells (against `r47-control-passive`): "
        + (f"**{min_q:.4f}**" if min_q is not None else "n/a")
        + " (nothing survives q<0.10 unless this is below it).",
        f"- Decision rule cleared by at least one cell: "
        f"**{'YES' if out['clears_decision_rule'] else 'NO (null)'}**.",
        "",
        "**Nothing is promoted from this round regardless of outcome -- it is a pre-registered "
        "measurement study (PLAN section 4).**",
        "",
    ]

    return "\n".join(md), out


def main(argv: list[str] | None = None) -> int:
    try:
        md, out = load_report()
    except FileNotFoundError as exc:
        print(
            f"round 47 has no scorecard yet ({exc}) -- this tool computes verdict tables from "
            f"data/rounds/r{ROUND}-2026-09/scorecard.json, which is written by score.py after "
            "run_round.sh has run every card. Author and run the round first; this report does not "
            "run backtests itself.",
            file=sys.stderr,
        )
        return 1
    print(md)
    dest = REPO / "data" / "rounds" / f"r{ROUND}-2026-09" / "analysis.json"
    dest.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\n(wrote {dest.relative_to(REPO).as_posix()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

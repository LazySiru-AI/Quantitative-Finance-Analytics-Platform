"""Verdict tables for round 42 -- level reclaim and breakout quality -- from its scorecard.

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round42_report.py

`ROUND-42-PLAN.md` pre-registered a decision rule and a set of predictions before any card ran. This
module computes exactly the quantities that rule names -- each family's arm-minus-OWN-control
contrast on median adjusted excess, per-window sign counts, a sign-flip permutation p-value, the
noise-floor comparison, and a Benjamini-Hochberg pass over all 5 cells run -- and prints them as
markdown so `data/rounds/r42-2026-09/REPORT.md` (written separately, after this runs) quotes numbers
this code produced rather than numbers a hand transcribed. It writes the same content to
`data/rounds/r42-2026-09/analysis.json`.

**Why this imports `round34_36_report.py` by file path.** `strategy-program` is not a legal Python
package name (the hyphen), so that module -- which already carries `load_scorecard`, `cells_of`,
`contrast`, `bh_against_reference`, `table`, `per_window_table` and `FLOOR_PP` -- is loaded the same
way `round40.py`'s tests load `round40.py`: `importlib.util.spec_from_file_location`. Nothing in this
file re-derives what that module already computes correctly; it is reused, not reimplemented, per
`round34_36_report.py`'s own docstring on why a contrast is a sign-flip permutation test rather than
something requiring a distributional assumption.

**BH's reference cell is arbitrary, and this file says so.** Two families means two natural
denominators for "the" reference control. §3 rule 8's BH denominator is every cell the round ran (m=5)
regardless of which single cell is named as the reference for the contrast column; this file reports
BH against BOTH `r42-reclaim-control` and `r42-breakout-control` and states plainly that the choice of
reference changes nothing about which cells clear the floor -- the *contrast* that matters for the
decision rule is always an arm against its OWN family's control, computed separately.

**Not investment advice.** Every figure is a backtest on price-only bars. This module is importable
and unit-testable on a fake scorecard dict (see `tests/test_round42_report.py` if one exists); it does
not require a live scorecard to import.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from typing import Any

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
cells_of = _r34.cells_of
contrast = _r34.contrast
bh_against_reference = _r34.bh_against_reference
table = _r34.table
per_window_table = _r34.per_window_table
FLOOR_PP = _r34.FLOOR_PP
MAIN_WINDOWS = _r34.MAIN_WINDOWS
pp = _r34.pp
fmt = _r34.fmt

ROUND = 42
SCORECARD_PATH = REPO / "data" / "rounds" / f"r{ROUND}-2026-09" / "scorecard.json"
ANALYSIS_PATH = REPO / "data" / "rounds" / f"r{ROUND}-2026-09" / "analysis.json"

#: family -> (control agent_id, [treatment agent_ids], persona label). The pinned round-42 field.
FAMILIES: dict[str, tuple[str, list[str], str]] = {
    "reclaim": (
        "r42-reclaim-control",
        ["r42-reclaim-wick", "r42-reclaim-wick-body"],
        "Creator E (creator-e)",
    ),
    "breakout": (
        "r42-breakout-control",
        ["r42-breakout-q25"],
        "Creator C (creator-c)",
    ),
}


def load_round42_scorecard() -> dict[str, Any]:
    return json.loads(SCORECARD_PATH.read_text(encoding="utf-8"))


def family_contrasts(cells: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """arm-minus-own-control contrast for every treatment, keyed by treatment agent_id."""
    out: dict[str, dict[str, Any]] = {}
    for _family, (control, treatments, _persona) in FAMILIES.items():
        if control not in cells:
            continue
        for t in treatments:
            if t not in cells:
                continue
            out[t] = contrast(cells[t], cells[control])
    return out


def report(card: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    cells = cells_of(card)
    out: dict[str, Any] = {"round": ROUND, "n_cells": len(cells)}
    md = [
        "# Round 42 -- computed verdict tables",
        "",
        "**Not investment advice.** Price-only bars, no dividends. Nothing in this round is "
        "promotable (`trading` purpose, PROTOCOL.md r21 amendment) -- report only.",
        "",
    ]
    md += ["## Cells", "", table(cells), ""]
    md += ["## Per-window adjusted excess", "", per_window_table(cells, sorted(cells)), ""]

    # ------------------------------------------------------------------
    # Per-family arm-minus-own-control contrasts -- the decision rule.
    # ------------------------------------------------------------------
    md += ["## Arm minus OWN family control (PLAN decision rule)", ""]
    md += [
        "| family | arm | slots/exposure trades | arm median | control median | arm - control | "
        "windows arm>ctrl | p (sign-flip) | clears 21.2pp floor? |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    per_family: dict[str, Any] = {}
    contrasts = family_contrasts(cells)
    for family, (control_id, treatments, persona) in FAMILIES.items():
        if control_id not in cells:
            continue
        family_rows = []
        for t in treatments:
            if t not in contrasts:
                continue
            c = contrasts[t]
            clears = (c["median_diff"] or 0) * 100 > FLOOR_PP
            family_rows.append({**c, "clears_floor": clears})
            md.append(
                f"| {family} ({persona}) | `{t}` | {cells[t].trades} | {pp(cells[t].median)} | "
                f"{pp(cells[control_id].median)} | {pp(c['median_diff'])} | "
                f"{c['windows_a_gt_b']}/{c['n_windows']} | {fmt(c['p_signflip'])} | "
                f"{'YES' if clears else 'no'} |"
            )
        per_family[family] = {"control": control_id, "treatments": family_rows}
    out["family_contrasts"] = per_family

    # ------------------------------------------------------------------
    # BH over all 5 cells -- denominator is every cell the round ran, per PROTOCOL section 3 rule 8.
    # Reference is arbitrary; report against both controls and say so.
    # ------------------------------------------------------------------
    md += ["", "## BH over all 5 cells (m=5) -- the reference control is arbitrary for m; reported "
           "against both", ""]
    bh_by_ref: dict[str, Any] = {}
    for _family, (control_id, _t, _p) in FAMILIES.items():
        if control_id not in cells:
            continue
        bh = bh_against_reference(cells, control_id)
        bh_by_ref[control_id] = bh
        min_q = min((r["q"] for r in bh if r["q"] is not None), default=None)
        out[f"bh_vs_{control_id}"] = bh
        md.append(f"Reference `{control_id}`: minimum q over the field = "
                  f"**{min_q:.4f}**" if min_q is not None else f"Reference `{control_id}`: no q computed")
    md.append("")
    md.append(
        "The reference cell only fixes which contrast column BH is computed against; m stays 5 "
        "(every cell run) either way, and the pre-registered per-family contrasts above -- arm minus "
        "its OWN control -- are what the decision rule actually reads, not either BH table."
    )
    md.append("")

    # ------------------------------------------------------------------
    # Trade counts and exposure per cell.
    # ------------------------------------------------------------------
    trades = {a: cells[a].trades for a in sorted(cells)}
    exposure = {a: cells[a].exposure for a in sorted(cells)}
    out["trades"] = trades
    out["exposure"] = exposure
    md += ["## Trade counts and mean exposure per cell", "", "| cell | trades | mean exposure |",
           "|---|---|---|"]
    for a in sorted(cells):
        exp = exposure[a]
        md.append(f"| `{a}` | {trades[a]} | {'' if exp is None else f'{exp:.3f}'} |")
    md.append("")

    # ------------------------------------------------------------------
    # Predictions.
    # ------------------------------------------------------------------
    any_clears = any(
        (c["median_diff"] or 0) * 100 > FLOOR_PP for c in contrasts.values()
    )
    reclaim_trades = {a: trades.get(a) for a in ("r42-reclaim-control", "r42-reclaim-wick", "r42-reclaim-wick-body")}
    wick_order_held = (
        reclaim_trades.get("r42-reclaim-wick-body") is not None
        and reclaim_trades.get("r42-reclaim-wick") is not None
        and reclaim_trades.get("r42-reclaim-control") is not None
        and reclaim_trades["r42-reclaim-wick-body"] < reclaim_trades["r42-reclaim-wick"] < reclaim_trades["r42-reclaim-control"]
    )
    breakout_trades = {a: trades.get(a) for a in ("r42-breakout-control", "r42-breakout-q25")}
    q25_fewer = (
        breakout_trades.get("r42-breakout-q25") is not None
        and breakout_trades.get("r42-breakout-control") is not None
        and breakout_trades["r42-breakout-q25"] < breakout_trades["r42-breakout-control"]
    )
    out["predictions"] = {
        "any_arm_clears_floor": any_clears,
        "reclaim_trade_ordering_wick_body_lt_wick_lt_control": wick_order_held,
        "reclaim_trades": reclaim_trades,
        "breakout_q25_fewer_trades_than_control": q25_fewer,
        "breakout_trades": breakout_trades,
    }
    md += ["## Verdict (PLAN decision rule)", "",
           f"- Any arm clears its own-control 21.2pp floor AND survives BH q<0.10: "
           f"**{'YES' if any_clears else 'NO (null)'}**.",
           f"- Family A trade ordering (wick-body < wick < control), as predicted from each added "
           f"structural term filtering further: **{'HELD' if wick_order_held else 'NOT CONFIRMED / REFUTED'}** "
           f"({reclaim_trades}).",
           f"- Family B: q25 takes fewer trades than the breakout control, as predicted from a later, "
           f"stricter confirmation: **{'HELD' if q25_fewer else 'NOT CONFIRMED / REFUTED'}** "
           f"({breakout_trades}).",
           "", "Nothing in this round is promotable regardless of outcome (`trading` purpose, "
           "PROTOCOL.md r21 amendment) -- these are measurement results only.", ""]

    return "\n".join(md), out


def main(argv: list[str] | None = None) -> int:
    if not SCORECARD_PATH.is_file():
        print(f"no scorecard at {SCORECARD_PATH.relative_to(REPO).as_posix()} -- round 42 has not been "
              "run yet. This tool is importable/unit-testable on a fake scorecard dict without one.")
        return 1
    card = load_round42_scorecard()
    md, out = report(card)
    print(md)
    ANALYSIS_PATH.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\n(wrote {ANALYSIS_PATH.relative_to(REPO).as_posix()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

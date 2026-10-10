"""Round 24, scored: does the trading book's ranking survive the trading book's own mandate?

Pre-registered in `strategy-program/ROUND-24-PLAN.md`; cards frozen at commit `9dcd283` before the
first run. Differencing is `round11.live_cells` unchanged -- the same cumulative-run recovery, on
this round's own results root -- so a live median here means what a live median meant in round 11.

    cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round24.py
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent))

import score

R24_RESULTS = Path("data/rounds/r24-2026-08/results")
FIELD = (
    "A-rotation",
    "B3-concentrated",
    "B3-concentrated-cap126",
    "B-momentum",
    "B-momentum-cap126",
    "C-trend",
)
PAIRS = (("B3-concentrated", "B3-concentrated-cap126"), ("B-momentum", "B-momentum-cap126"))
NOISE_FLOOR_PP = Decimal("21.2")


def live_cells() -> dict[str, dict[str, Decimal]]:
    """`round11.live_cells`, verbatim in method, over this round's field and results root."""
    by_window = score.load_results(R24_RESULTS, "r1", list(score.R11_LIVE_TAGS))
    out: dict[str, dict[str, Decimal]] = {}
    for agent_id in FIELD:
        runs = [by_window[tag].get(agent_id) for tag in score.R11_LIVE_TAGS]
        if any(r is None for r in runs):
            continue
        prev_equity = runs[0].starting_equity
        prev_bench = Decimal(0)
        prev_notional = Decimal(0)
        prev_sessions = 0
        for tag, r in zip(score.R11_LIVE_TAGS, runs, strict=True):
            d_sessions = r.sessions - prev_sessions
            if d_sessions <= 0 or prev_equity <= 0:
                break
            ret = r.ending_equity / prev_equity - 1
            bench = (1 + r.benchmark_return) / (1 + prev_bench) - 1
            notional = Decimal(str(r.capital_exposure)) * Decimal(r.sessions) * runs[0].starting_equity
            exposure = (notional - prev_notional) / (Decimal(d_sessions) * prev_equity)
            out.setdefault(agent_id, {})[tag] = ret - exposure * bench
            prev_equity, prev_bench = r.ending_equity, r.benchmark_return
            prev_notional, prev_sessions = notional, r.sessions
    return out


def totals() -> dict[str, dict[str, object]]:
    """Whole-window figures from the final cumulative run (2026-02-17 -> 2026-08-18)."""
    final = score.load_results(R24_RESULTS, "r1", ["live-6"])["live-6"]
    out: dict[str, dict[str, object]] = {}
    for a in FIELD:
        r = final.get(a)
        if r is None:
            continue
        closed = [t for t in r.trades if getattr(t, "exit_date", None) is not None]
        reasons: dict[str, int] = {}
        for t in closed:
            reasons[str(getattr(t, "exit_reason", "?"))] = reasons.get(str(getattr(t, "exit_reason", "?")), 0) + 1
        out[a] = {
            "return": r.total_return,
            "ending_equity": r.ending_equity,
            "trades": len(r.trades),
            "closed": len(closed),
            "exit_reasons": reasons,
            "max_drawdown": r.max_drawdown,
            "capital_exposure": r.capital_exposure,
        }
    return out


def main() -> int:
    cells = live_cells()
    tot = totals()

    print("== Round 24 live matrix -- adjusted excess per sub-period ==\n")
    print("{:<26} {:>8} {:>8} {:>8} {:>8} {:>8} {:>8} {:>9} {:>6}".format(
        "card", *score.R11_LIVE_TAGS, "median", "hits"))
    meds: dict[str, Decimal] = {}
    for a in FIELD:
        c = cells.get(a)
        if not c:
            print(f"{a:<26}  (incomplete)")
            continue
        vals = [c[t] for t in score.R11_LIVE_TAGS]
        m = Decimal(str(median(vals)))
        meds[a] = m
        hits = sum(1 for v in vals if v > 0)
        # `float(...)` throughout rather than formatting the `Decimal` directly: `%f` coerced to
        # float, and `Decimal.__format__` rounds in decimal context instead, which can differ in the
        # last printed digit. Keeping the coercion keeps this output identical to what it was.
        cols = " ".join(f"{float(v * 100):+7.2f}%" for v in vals)
        print(f"{a:<26} {cols} {float(m * 100):+8.2f}% {hits:5d}/6")

    print("\n== Whole window 2026-02-17 -> 2026-08-18 ==\n")
    print(f"{'card':<26} {'return':>9} {'trades':>8} {'closed':>8} {'maxDD':>9} {'capExp':>10}  "
          f"{'exit reasons'}")
    for a in FIELD:
        t = tot.get(a)
        if not t:
            continue
        reasons = t["exit_reasons"] or "{}"
        print(f"{a:<26} {float(t['return']) * 100:+8.2f}% {t['trades']:8d} {t['closed']:8d} "
              f"{float(t['max_drawdown']) * 100:+8.2f}% "
              f"{float(t['capital_exposure']) * 100:9.1f}%  {reasons}")

    print("\n== Prediction 1: both -cap126 variants post a LOWER live median than their base ==")
    print("   (the card author's own claim: capping costs roughly two thirds of the return)\n")
    for base, var in PAIRS:
        if base not in meds or var not in meds:
            print(f"   {base:<24} incomplete")
            continue
        delta = (meds[var] - meds[base]) * 100
        verdict = "HELD" if delta < 0 else "REFUTED"
        inside = "inside" if abs(delta) < NOISE_FLOOR_PP else "OUTSIDE"
        print(f"   {base:<24} base {float(meds[base] * 100):+7.2f}%  "
              f"cap126 {float(meds[var] * 100):+7.2f}%  delta {float(delta):+7.2f}pp  "
              f"-> {verdict}  ({inside} the {NOISE_FLOOR_PP}pp floor)")

    print("\n== Prediction 2: the cap BINDS -- variants take time-stop exits their bases do not ==\n")
    inert = True
    for base, var in PAIRS:
        b, v = tot.get(base), tot.get(var)
        if not b or not v:
            continue
        bt, vt = b["exit_reasons"].get("time", 0), v["exit_reasons"].get("time", 0)
        same = (b["trades"] == v["trades"] and b["exit_reasons"] == v["exit_reasons"])
        if not same:
            inert = False
        binds = "IDENTICAL (inert)" if same else "DIFFERS (binds)"
        print(f"   {base:<24} base: {b['trades']:d} trades {b['exit_reasons']} | "
              f"cap126: {v['trades']:d} trades {v['exit_reasons']}  -> {binds}")
        print(f"       time-stop exits: base {bt:d}, cap126 {vt:d}")
    print("\n   ROUND VERDICT: %s" % ("INERT -- the cap changed nothing in this window, round found nothing"
                                       if inert else "the cap binds; deltas above are a real measurement"))

    out = {
        "cells": {a: {t: str(v) for t, v in c.items()} for a, c in cells.items()},
        "medians": {a: str(m) for a, m in meds.items()},
        "totals": {a: {k: (str(v) if isinstance(v, Decimal) else v) for k, v in t.items()} for a, t in tot.items()},
        "inert": inert,
    }
    Path("data/rounds/r24-2026-08/scorecard.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("\nwrote data/rounds/r24-2026-08/scorecard.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

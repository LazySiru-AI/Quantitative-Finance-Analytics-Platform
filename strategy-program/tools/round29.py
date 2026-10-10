"""Round 29: cross-sectional information on a diversified, low-correlation universe -- the fair test.

    PYTHONIOENCODING=utf-8 PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round29.py

`ROUND-29-PLAN.md` is the pre-registration this executes. Read it first.

Round 28 found no cross-sectional rank information on the concentrated tech/semiconductor universes,
and flagged that a concentrated universe is the worst case for selection. This repeats the identical
measurement on ten single names, one per GICS sector, whose measured pairwise correlation (0.393) is
roughly half the seated universes' -- a genuine low-correlation universe with real dispersion to rank.

**The IC machinery is imported from round28, unchanged**, so the two rounds are directly comparable and
there is exactly one definition of the rank IC, the signals and the bootstrap. Only the universe and
the (already non-overlapping) window construction differ, the latter per round 28's Amendment 1.

**Not investment advice.**
"""

from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import round28 as R28

REPO = pathlib.Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "rounds" / "r29-2026-08"

#: One liquid large-cap per GICS sector, longest history in the store. Balanced panel from LIN's
#: 1992-06-16 first bar. See ROUND-29-PLAN.md section 2.
DIVERSIFIED = ("MSFT", "JPM", "XOM", "JNJ", "PG", "CAT", "MCD", "NEE", "DIS", "LIN")
START = "1992-06-16"


def main() -> int:
    bars = {s: R28._load(s) for s in DIVERSIFIED}
    rng = np.random.default_rng(R28.SEED)

    start_dt = np.datetime64(START, "D")
    ref_dates = bars[DIVERSIFIED[0]][0]
    cal = ref_dates[ref_dates >= start_dt]
    pos = {s: {d: i for i, d in enumerate(bars[s][0])} for s in DIVERSIFIED}

    cells: list[dict] = []
    for sig in R28.SIGNALS:
        for h in R28.HORIZONS:
            # Non-overlapping from the start: rebalance at the horizon (round 28 Amendment 1).
            rebal_dates = cal[::h]
            per_date = []
            for d in rebal_dates:
                svals, fwd = [], []
                for s in DIVERSIFIED:
                    p = pos[s].get(d)
                    if p is None:
                        continue
                    _, close, sma = bars[s]
                    if p + h >= len(close):
                        continue
                    v = R28._signal(sig, close, sma, p)
                    if v is None:
                        continue
                    svals.append(v)
                    fwd.append(close[p + h] / close[p] - 1)
                if len(svals) < 5:
                    continue
                fwd_arr = np.array(fwd)
                ic = R28._spearman(np.array(svals), fwd_arr - fwd_arr.mean())
                if ic is not None:
                    per_date.append(ic)
            per_date = np.array(per_date)
            mean_ic = float(np.mean(per_date)) if len(per_date) else float("nan")
            p = R28._block_bootstrap_p(per_date, rng) if len(per_date) >= R28.BLOCK else float("nan")
            cells.append({
                "signal": sig, "horizon": h, "mean_ic": mean_ic,
                "n_dates": len(per_date), "p_value": p,
            })

    valid = [c for c in cells if not np.isnan(c["p_value"])]
    qs = R28._benjamini_hochberg([c["p_value"] for c in valid])
    for c, q in zip(valid, qs, strict=True):
        c["q_value"] = q
    for c in cells:
        c.setdefault("q_value", float("nan"))
    survivors = [c for c in cells if not np.isnan(c["q_value"]) and c["q_value"] < 0.10]

    print(f"{'signal':12s} {'h':>3s} {'mean_IC':>9s} {'n':>4s} {'p':>7s} {'q':>7s}")
    for c in sorted(cells, key=lambda x: (x["signal"], x["horizon"])):
        star = " *" if c in survivors else ""
        print(f"{c['signal']:12s} {c['horizon']:3d} {c['mean_ic']:+9.4f} "
              f"{c['n_dates']:4d} {c['p_value']:7.3f} {c['q_value']:7.3f}{star}")

    mean_abs = np.mean([abs(c["mean_ic"]) for c in cells if not np.isnan(c["mean_ic"])])
    print(f"\nmean |IC| (this round): {mean_abs:.4f}   [round 28: U12 0.0418, U9 0.0517]")
    print("mean |IC| by signal:")
    for sig in R28.SIGNALS:
        vals = [abs(c["mean_ic"]) for c in cells if c["signal"] == sig and not np.isnan(c["mean_ic"])]
        print(f"  {sig:12s} {np.mean(vals):+.4f}")
    print(f"\nsurvivors at q<0.10: {len(survivors)}")
    for c in survivors:
        print(f"  {c['signal']} h={c['horizon']}  IC={c['mean_ic']:+.4f} q={c['q_value']:.3f}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ic.json").write_text(json.dumps({
        "universe": list(DIVERSIFIED), "start": START, "cells": cells,
        "survivors": len(survivors), "mean_abs_ic": float(mean_abs),
        "seed": R28.SEED, "boot": R28.BOOT, "block": R28.BLOCK,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {(OUT / 'ic.json').relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Round 31: the monthly inflation indices, the last untested macro series.

    PYTHONIOENCODING=utf-8 PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round31.py

`ROUND-31-PLAN.md` is the pre-registration this executes. Read it first.

Closes the macro line. Six of seven FRED series are measured and empty (curve as a card, rounds
22/23/25; rate/oil/breakeven as statistics, round 30). This measures the three monthly inflation
indices -- PCEPI, PCEPILFE, CPILFESL -- the same way round 30 measured the daily series: a
regime-conditional forward-return spread on SPY and QQQ, before any card.

Two things are specific to monthly inflation and load-bearing:

1. **Release lag.** Inflation for reference month M is published ~six weeks later. This applies the
   identical 45-day shift `app.rules.macro_binding.RELEASE_LAG` uses, so a state is usable only from
   `reference_date + 45d` and carries forward -- mirroring what a card would see. As-of joining on the
   reference date would be a six-week lookahead.
2. **Non-stationarity.** A price index has no usable level, so each index is differenced to
   year-over-year inflation first, and the two states are built on that.

Bootstrap and BH are imported from round28, spread and residualization from round30 -- one definition
of each, shared with the rounds this is compared against.

**Not investment advice.**
"""

from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import round28 as R28
import round30 as R30

REPO = pathlib.Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "rounds" / "r31-2026-08"
PIN = REPO / "data" / "rounds" / "r21-2026-08" / "macro-pin.json"

SEED = 31                                     #: fixed; never the clock (plan section 6)
SERIES = ("PCEPI", "PCEPILFE", "CPILFESL")    #: the three monthly inflation indices
TRANSFORMS = ("level", "accel")               #: plan section 3b
TARGETS = ("SPY", "QQQ")
HORIZONS = (21, 63)
RELEASE_LAG = np.timedelta64(45, "D")         #: mirrors macro_binding.RELEASE_LAG for these three
YOY = 12                                       #: months, for the year-over-year inflation rate
REGIME = 60                                    #: months, trailing-mean window for the level transform
ACCEL = 3                                      #: months, change window for the accel transform


def _load_index(series_id: str):
    """Sorted (reference_dates[datetime64[D]], values[float]) for one monthly pin series."""
    d = json.loads(PIN.read_text(encoding="utf-8"))
    pts = d["series"][series_id]["points"]
    rows = sorted(((p["date"], p["value"]) for p in pts if p.get("value") is not None),
                  key=lambda r: r[0])
    dates = np.array([np.datetime64(r[0], "D") for r in rows], dtype="datetime64[D]")
    vals = np.array([float(r[1]) for r in rows], dtype=float)
    return dates, vals


def _inflation_states(dates: np.ndarray, vals: np.ndarray):
    """Eligibility dates and {-1,0,+1} states for `level` and `accel`, built on YoY inflation.

    Every state is stamped with `reference_date + 45d` -- the day it became knowable -- and is 0
    (undefined) until its own history requirement is met.
    """
    n = len(vals)
    elig = dates + RELEASE_LAG
    yoy = np.full(n, np.nan)
    for k in range(YOY, n):
        yoy[k] = vals[k] / vals[k - YOY] - 1.0
    level = np.zeros(n)
    accel = np.zeros(n)
    for k in range(YOY + REGIME - 1, n):
        level[k] = np.sign(yoy[k] - np.mean(yoy[k - REGIME + 1: k + 1]))
    for k in range(YOY + ACCEL, n):
        accel[k] = np.sign(yoy[k] - yoy[k - ACCEL])
    return elig, {"level": level, "accel": accel}


def main() -> int:
    rng = np.random.default_rng(SEED)
    bars = {t: R28._load(t) for t in TARGETS}
    macro = {}
    for s in SERIES:
        d, v = _load_index(s)
        elig, states = _inflation_states(d, v)
        macro[s] = {"elig": elig, **states}

    cells: list[dict] = []
    for s in SERIES:
        elig = macro[s]["elig"]
        for tf in TRANSFORMS:
            st_series = macro[s][tf]
            for tgt in TARGETS:
                tdates, close, _ = bars[tgt]
                for h in HORIZONS:
                    states, fwds, moms = [], [], []
                    for i in range(252, len(close) - h, h):
                        d = tdates[i]
                        k = int(np.searchsorted(elig, d, side="right")) - 1  # last release <= d
                        if k < 0:
                            continue
                        stt = st_series[k]
                        if stt == 0:
                            continue
                        states.append(stt)
                        fwds.append(close[i + h] / close[i] - 1)
                        moms.append(close[i - 21] / close[i - 252] - 1)
                    states = np.array(states)
                    fwds = np.array(fwds)
                    moms = np.array(moms)
                    n = len(states)
                    if n < 2 * R28.BLOCK or (states > 0).sum() == 0 or (states < 0).sum() == 0:
                        cells.append({"series": s, "transform": tf, "target": tgt, "horizon": h,
                                      "n": int(n), "spread": float("nan"), "p_value": float("nan"),
                                      "spread_res": float("nan"), "p_res": float("nan")})
                        continue
                    spread = R30._spread(states, fwds)
                    g = states * (fwds - fwds.mean())
                    p = R28._block_bootstrap_p(g, rng)

                    fwd_res = R30._residualize_on_momentum(fwds, moms)
                    spread_res = R30._spread(states, fwd_res)
                    g_res = states * (fwd_res - fwd_res.mean())
                    p_res = R28._block_bootstrap_p(g_res, rng)

                    cells.append({"series": s, "transform": tf, "target": tgt, "horizon": h,
                                  "n": int(n), "n_hi": int((states > 0).sum()),
                                  "n_lo": int((states < 0).sum()),
                                  "spread": spread, "p_value": p,
                                  "spread_res": spread_res, "p_res": p_res})

    valid = [c for c in cells if not np.isnan(c["p_value"])]
    qs = R28._benjamini_hochberg([c["p_value"] for c in valid])
    for c, q in zip(valid, qs, strict=True):
        c["q_value"] = q
    for c in cells:
        c.setdefault("q_value", float("nan"))

    def _orthogonal(c: dict) -> bool:
        if np.isnan(c["q_value"]) or c["q_value"] >= 0.10:
            return False
        if np.sign(c["spread_res"]) != np.sign(c["spread"]):
            return False
        return abs(c["spread_res"]) >= 0.5 * abs(c["spread"])

    survivors = [c for c in cells if _orthogonal(c)]
    bh_only = [c for c in cells if not np.isnan(c["q_value"]) and c["q_value"] < 0.10]

    hdr = f"{'series':10s} {'tf':6s} {'tgt':4s} {'h':>3s} {'n':>4s} {'spread':>9s} {'p':>6s} {'q':>6s} {'sprd_res':>9s} {'p_res':>6s}"
    print(hdr)
    print("-" * len(hdr))
    for c in sorted(cells, key=lambda x: (x["series"], x["transform"], x["target"], x["horizon"])):
        mark = " <<" if c in survivors else (" *" if c in bh_only else "")
        print(f"{c['series']:10s} {c['transform']:6s} {c['target']:4s} {c['horizon']:3d} "
              f"{c['n']:4d} {c['spread']:+9.4f} {c['p_value']:6.3f} {c['q_value']:6.3f} "
              f"{c['spread_res']:+9.4f} {c['p_res']:6.3f}{mark}")

    print(f"\nBH survivors (q<0.10): {len(bh_only)}")
    print(f"orthogonal survivors (q<0.10 AND keep sign + >=half spread after residualization): {len(survivors)}")
    for c in survivors:
        print(f"  {c['series']} {c['transform']} {c['target']} h={c['horizon']}  "
              f"spread {c['spread']:+.4f} -> res {c['spread_res']:+.4f} (q={c['q_value']:.3f})")

    print("\nmean |spread| by transform (prediction 2 -- level should exceed accel):")
    for tf in TRANSFORMS:
        vals = [abs(c["spread"]) for c in cells if c["transform"] == tf and not np.isnan(c["spread"])]
        print(f"  {tf:6s} {np.mean(vals):+.4f}")
    print("mean |spread| by series (prediction 3 -- core should exceed headline PCEPI):")
    for s in SERIES:
        vals = [abs(c["spread"]) for c in cells if c["series"] == s and not np.isnan(c["spread"])]
        print(f"  {s:10s} {np.mean(vals):+.4f}")
    print("\nlevel transform, SPY vs QQQ (prediction 1):")
    for c in cells:
        if c["transform"] == "level":
            print(f"  {c['series']:10s} {c['target']} h={c['horizon']}: raw {c['spread']:+.4f}  residual {c['spread_res']:+.4f}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "spreads.json").write_text(json.dumps({
        "series": list(SERIES), "targets": list(TARGETS), "transforms": list(TRANSFORMS),
        "horizons": list(HORIZONS), "seed": SEED, "release_lag_days": 45,
        "boot": R28.BOOT, "block": R28.BLOCK, "cells": cells,
        "bh_survivors": len(bh_only), "orthogonal_survivors": len(survivors),
    }, indent=2, default=lambda o: None) + "\n", encoding="utf-8")
    print(f"\nwrote {(OUT / 'spreads.json').relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Round 30: do the untouched daily macro series carry forward-return information price does not?

    PYTHONIOENCODING=utf-8 PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round30.py

`ROUND-30-PLAN.md` is the pre-registration this executes. Read it first.

Only T10Y2Y (the curve) has ever been tested through the macro DSL -- null 3-of-3 across rounds 22/23/25.
This measures the three daily untouched series -- DGS10, DCOILWTICO, T10YIE -- as regime-conditional
forward returns on SPY and QQQ, with an orthogonality-to-price control on every cell. The question is
not "does the macro state coincide with returns" but "does it add anything trailing price momentum does
not already carry."

The bootstrap and BH machinery is imported from round28, unchanged, so the significance test is exactly
the one rounds 28-29 used and there is one definition of it. Windows are non-overlapping from the start
(round 28 Amendment 1). Macro states are built on each series' own timeline and as-of joined to the
equity rebalance date -- the most recent released observation on or before d, no lookahead.

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
OUT = REPO / "data" / "rounds" / "r30-2026-08"
PIN = REPO / "data" / "rounds" / "r21-2026-08" / "macro-pin.json"

SEED = 30                                   #: fixed; never the clock (plan section 6)
SERIES = ("DGS10", "DCOILWTICO", "T10YIE")  #: the three daily, directly-expressible untouched series
TRANSFORMS = ("level", "roc")               #: plan section 3a
TARGETS = ("SPY", "QQQ")                    #: plan section 3b
HORIZONS = (21, 63)                         #: plan section 3c
LOOKBACK = 20                               #: roc lookback, same as round 25
TREND = 252                                 #: level trailing-mean window, in macro observations


def _load_macro(series_id: str):
    """Sorted (dates[datetime64[D]], values[float]) for one pin series, Nones dropped."""
    d = json.loads(PIN.read_text(encoding="utf-8"))
    pts = d["series"][series_id]["points"]
    rows = [(p["date"], p["value"]) for p in pts if p.get("value") is not None]
    rows.sort(key=lambda r: r[0])
    dates = np.array([np.datetime64(r[0], "D") for r in rows], dtype="datetime64[D]")
    vals = np.array([float(r[1]) for r in rows], dtype=float)
    return dates, vals


def _macro_state(vals: np.ndarray, transform: str) -> np.ndarray:
    """State in {-1, 0, +1} at each macro index; 0 (undefined) where history is insufficient."""
    n = len(vals)
    state = np.zeros(n, dtype=float)
    if transform == "level":
        for k in range(TREND - 1, n):
            mean = float(np.mean(vals[k - TREND + 1: k + 1]))
            state[k] = np.sign(vals[k] - mean)
    elif transform == "roc":
        for k in range(LOOKBACK, n):
            state[k] = np.sign(vals[k] - vals[k - LOOKBACK])
    else:
        raise ValueError(transform)
    return state


def _spread(state: np.ndarray, fwd: np.ndarray) -> float:
    hi, lo = fwd[state > 0], fwd[state < 0]
    if len(hi) == 0 or len(lo) == 0:
        return float("nan")
    return float(np.mean(hi) - np.mean(lo))


def _residualize_on_momentum(fwd: np.ndarray, mom: np.ndarray) -> np.ndarray:
    """Subtract the within-tercile mean forward return (terciles of trailing 12-1 momentum)."""
    res = fwd.copy()
    order = np.argsort(mom)
    for chunk in np.array_split(order, 3):
        if len(chunk):
            res[chunk] = fwd[chunk] - float(np.mean(fwd[chunk]))
    return res


def main() -> int:
    rng = np.random.default_rng(SEED)
    bars = {t: R28._load(t) for t in TARGETS}          # (dates, close, sma) per target
    macro = {}
    for s in SERIES:
        md, mv = _load_macro(s)
        macro[s] = {"dates": md, "vals": mv,
                    "level": _macro_state(mv, "level"),
                    "roc": _macro_state(mv, "roc")}

    cells: list[dict] = []
    for s in SERIES:
        md = macro[s]["dates"]
        for tf in TRANSFORMS:
            st_series = macro[s][tf]
            for tgt in TARGETS:
                tdates, close, _ = bars[tgt]
                for h in HORIZONS:
                    states, fwds, moms = [], [], []
                    for i in range(252, len(close) - h, h):     # non-overlapping; 252 for momentum
                        d = tdates[i]
                        k = int(np.searchsorted(md, d, side="right")) - 1   # last macro obs <= d
                        if k < 0:
                            continue
                        stt = st_series[k]
                        if stt == 0:                            # state undefined here
                            continue
                        states.append(stt)
                        fwds.append(close[i + h] / close[i] - 1)
                        moms.append(close[i - 21] / close[i - 252] - 1)
                    states = np.array(states)
                    fwds = np.array(fwds)
                    moms = np.array(moms)
                    n = len(states)
                    if n < 2 * R28.BLOCK or len(fwds[states > 0]) == 0 or len(fwds[states < 0]) == 0:
                        cells.append({"series": s, "transform": tf, "target": tgt, "horizon": h,
                                      "n": n, "spread": float("nan"), "p_value": float("nan"),
                                      "spread_res": float("nan"), "p_res": float("nan")})
                        continue
                    spread = _spread(states, fwds)
                    g = states * (fwds - fwds.mean())
                    p = R28._block_bootstrap_p(g, rng)

                    fwd_res = _residualize_on_momentum(fwds, moms)
                    spread_res = _spread(states, fwd_res)
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

    hdr = f"{'series':11s} {'tf':6s} {'tgt':4s} {'h':>3s} {'n':>4s} {'spread':>9s} {'p':>6s} {'q':>6s} {'sprd_res':>9s} {'p_res':>6s}"
    print(hdr)
    print("-" * len(hdr))
    for c in sorted(cells, key=lambda x: (x["series"], x["transform"], x["target"], x["horizon"])):
        mark = " <<" if c in survivors else (" *" if c in bh_only else "")
        sp = c["spread"]
        print(f"{c['series']:11s} {c['transform']:6s} {c['target']:4s} {c['horizon']:3d} "
              f"{c['n']:4d} {sp:+9.4f} {c['p_value']:6.3f} {c['q_value']:6.3f} "
              f"{c['spread_res']:+9.4f} {c['p_res']:6.3f}{mark}")

    print(f"\nBH survivors (q<0.10): {len(bh_only)}")
    print(f"orthogonal survivors (q<0.10 AND keep sign + >=half spread after residualization): {len(survivors)}")
    for c in survivors:
        print(f"  {c['series']} {c['transform']} {c['target']} h={c['horizon']}  "
              f"spread {c['spread']:+.4f} -> res {c['spread_res']:+.4f} (q={c['q_value']:.3f})")

    print("\nmean |spread| by series (prediction 3):")
    for s in SERIES:
        vals = [abs(c["spread"]) for c in cells if c["series"] == s and not np.isnan(c["spread"])]
        print(f"  {s:11s} {np.mean(vals):+.4f}")

    print("\nDGS10 roc SPY-vs-QQQ (prediction 1) and raw-vs-residual (prediction 2):")
    for c in cells:
        if c["series"] == "DGS10" and c["transform"] == "roc":
            print(f"  {c['target']} h={c['horizon']}: raw {c['spread']:+.4f}  residual {c['spread_res']:+.4f}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "spreads.json").write_text(json.dumps({
        "series": list(SERIES), "targets": list(TARGETS), "transforms": list(TRANSFORMS),
        "horizons": list(HORIZONS), "seed": SEED, "boot": R28.BOOT, "block": R28.BLOCK,
        "cells": cells, "bh_survivors": len(bh_only), "orthogonal_survivors": len(survivors),
    }, indent=2, default=lambda o: None) + "\n", encoding="utf-8")
    print(f"\nwrote {(OUT / 'spreads.json').relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

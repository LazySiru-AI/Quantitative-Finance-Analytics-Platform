"""Round 32: the dedicated inflation-level round -- out-of-sample and confound-controlled.

    PYTHONIOENCODING=utf-8 PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round32.py

`ROUND-32-PLAN.md` is the pre-registration this executes. Read it first.

Round 31's near-miss -- core CPI YoY above its trailing 60-month mean precedes lower forward equity --
gets a single-hypothesis test. The point is NOT to re-run the cell without the /24 BH tax (that is
arithmetic, reported as Test 0 and excluded from the decision). The point is three tests the grid never
ran: a 1970-2026 regime-breadth test whose 1970-1992 half is out-of-sample to round 31's selection; a
rate-level confound control; and an exploitability check against the prevailing yield.

Machinery is imported unchanged (bootstrap/BH from round28, spread and tercile-residualization from
round30, inflation YoY + release binding from round31). No new statistical definition.

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
import round31 as R31

REPO = pathlib.Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "rounds" / "r32-2026-08"

SEED = 32
H = 63                                     #: quarterly, fixed -- round 31's headline horizon
SPLIT = np.datetime64("1993-01-01", "D")   #: 1970-1992 is out-of-sample to round 31's 1993-2026 selection
DGS10_LAG = np.timedelta64(1, "D")         #: macro_binding.RELEASE_LAG[DGS10]

#: Every store symbol with a continuous daily history from 1970-01-01 (mechanical, non-cherry-picked).
COHORT = ("AEP", "BA", "CAT", "CNP", "CVX", "DIS", "DTE", "ED", "GD", "GE", "HON", "HPQ", "IBM",
          "IP", "JNJ", "KO", "KR", "LMT", "MCD", "MMM", "MO", "MRK", "MSI", "PG", "RTX", "XOM")


def _boot_p(state, fwd, rng):
    g = state * (fwd - fwd.mean())
    return R28._block_bootstrap_p(g, rng)


def main() -> int:
    rng = np.random.default_rng(SEED)

    # Inflation level state (CPILFESL), release-bound, YoY -- exactly round 31's construction.
    cdates, cvals = R31._load_index("CPILFESL")
    celig, cstates = R31._inflation_states(cdates, cvals)
    clevel = cstates["level"]

    # DGS10 rate level, release-bound, for the confound control and the cash floor.
    ddates, dvals = R30._load_macro("DGS10")
    delig = ddates + DGS10_LAG

    def infl_state(d):
        k = int(np.searchsorted(celig, d, side="right")) - 1
        return clevel[k] if k >= 0 else 0.0

    def rate_level(d):
        k = int(np.searchsorted(delig, d, side="right")) - 1
        return dvals[k] if k >= 0 else np.nan

    # ---- Test 0: baseline, the exact round-31 cell on SPY (mechanical, not decision-relevant) ----
    sdates, sclose, _ = R28._load("SPY")
    S, F = [], []
    for i in range(252, len(sclose) - H, H):
        st = infl_state(sdates[i])
        if st == 0:
            continue
        S.append(st)
        F.append(sclose[i + H] / sclose[i] - 1)
    S, F = np.array(S), np.array(F)
    t0 = {"n": len(S), "spread": R30._spread(S, F), "p": _boot_p(S, F, rng)}

    # ---- The 26-name equal-weight portfolio, 1970-2026 ----
    bars = {s: R28._load(s) for s in COHORT}
    pos = {s: {d: i for i, d in enumerate(bars[s][0])} for s in COHORT}
    ref = bars[COHORT[0]][0]

    dates_all, state_all, fwd_all, rate_all = [], [], [], []
    for i in range(252, len(ref) - H, H):
        d = ref[i]
        st = infl_state(d)
        if st == 0:
            continue
        rets = []
        for s in COHORT:
            p = pos[s].get(d)
            if p is None or p + H >= len(bars[s][1]):
                continue
            c = bars[s][1]
            rets.append(c[p + H] / c[p] - 1)
        if len(rets) < len(COHORT) // 2:
            continue
        dates_all.append(d)
        state_all.append(st)
        fwd_all.append(float(np.mean(rets)))
        rate_all.append(rate_level(d))

    dates_all = np.array(dates_all)
    state_all = np.array(state_all)
    fwd_all = np.array(fwd_all)
    rate_all = np.array(rate_all)

    def summ(mask, label, do_boot=True):
        st, fw = state_all[mask], fwd_all[mask]
        nh, nl = int((st > 0).sum()), int((st < 0).sum())
        if nh == 0 or nl == 0:
            return {"label": label, "n": int(mask.sum()), "n_hot": nh, "n_cool": nl,
                    "hot": float("nan"), "cool": float("nan"), "spread": float("nan"), "p": float("nan")}
        hot, cool = float(fw[st > 0].mean()), float(fw[st < 0].mean())
        p = _boot_p(st, fw, rng) if do_boot and min(nh, nl) >= R28.BLOCK else float("nan")
        return {"label": label, "n": int(mask.sum()), "n_hot": nh, "n_cool": nl,
                "hot": hot, "cool": cool, "spread": hot - cool, "p": p}

    full = summ(np.ones(len(dates_all), bool), "1970-2026 full")
    oos = summ(dates_all < SPLIT, "1970-1992 OOS")
    ins = summ(dates_all >= SPLIT, "1993-2026 in-sample")

    # ---- Test 2: rate-level confound. Residualize fwd within terciles of the contemporaneous rate. ----
    valid = ~np.isnan(rate_all)
    fwd_res = fwd_all.copy()
    order = np.argsort(np.where(valid, rate_all, np.inf))
    order = order[valid[order]]
    for chunk in np.array_split(order, 3):
        if len(chunk):
            fwd_res[chunk] = fwd_all[chunk] - float(np.mean(fwd_all[chunk]))
    st_v, fr_v = state_all[valid], fwd_res[valid]
    rate_ctrl = {
        "n": int(valid.sum()),
        "spread_raw": R30._spread(state_all[valid], fwd_all[valid]),
        "spread_rate_residual": R30._spread(st_v, fr_v),
        "p_rate_residual": _boot_p(st_v, fr_v, rng),
    }

    # ---- Test 3: exploitability vs the DGS10 cash floor (yield in %, scaled to the horizon) ----
    floor = rate_all / 100.0 * (H / 252.0)
    hotmask = (state_all > 0) & valid
    coolmask = (state_all < 0) & valid
    exploit = {
        "hot_fwd": float(fwd_all[hotmask].mean()),
        "hot_cash_floor": float(floor[hotmask].mean()),
        "hot_excess_over_cash": float((fwd_all[hotmask] - floor[hotmask]).mean()),
        "cool_fwd": float(fwd_all[coolmask].mean()),
        "cool_cash_floor": float(floor[coolmask].mean()),
        "cool_excess_over_cash": float((fwd_all[coolmask] - floor[coolmask]).mean()),
    }

    # ---------------- report ----------------
    print("=== Test 0: baseline, exact round-31 cell (SPY, mechanical, NOT decision-relevant) ===")
    print(f"  n={t0['n']}  spread={t0['spread']:+.4f}  p={t0['p']:.4f}  "
          f"(round 31 reported p=0.009 with q=0.139 under the 24-cell tax)")

    print("\n=== Test 1: regime breadth on the 26-name 1970 portfolio (DECISIVE) ===")
    for r in (full, oos, ins):
        print(f"  {r['label']:20s} n={r['n']:3d} (hot {r['n_hot']:2d}/cool {r['n_cool']:2d})  "
              f"hot={r['hot']:+.4f} cool={r['cool']:+.4f}  spread={r['spread']:+.4f}  p={r['p']:.4f}")

    print("\n=== Test 2: rate-level confound (is it inflation, or the rate level?) ===")
    print(f"  raw spread           = {rate_ctrl['spread_raw']:+.4f}")
    print(f"  rate-residual spread = {rate_ctrl['spread_rate_residual']:+.4f}  "
          f"p={rate_ctrl['p_rate_residual']:.4f}")

    print("\n=== Test 3: exploitability vs DGS10 cash floor (10Y proxy) ===")
    print(f"  HOT : fwd={exploit['hot_fwd']:+.4f}  floor={exploit['hot_cash_floor']:+.4f}  "
          f"excess_over_cash={exploit['hot_excess_over_cash']:+.4f}")
    print(f"  COOL: fwd={exploit['cool_fwd']:+.4f}  floor={exploit['cool_cash_floor']:+.4f}  "
          f"excess_over_cash={exploit['cool_excess_over_cash']:+.4f}")

    # ---------------- verdict against the pre-registered decision rule ----------------
    oos_holds = (not np.isnan(oos["spread"])) and oos["spread"] < 0
    rate_survives = (np.sign(rate_ctrl["spread_rate_residual"]) == np.sign(rate_ctrl["spread_raw"])
                     and abs(rate_ctrl["spread_rate_residual"]) >= 0.5 * abs(rate_ctrl["spread_raw"]))
    print("\n=== verdict (pre-registered rule: card candidate iff OOS sign holds AND survives rate control) ===")
    print(f"  OOS 1970-1992 sign holds (negative): {oos_holds}  (spread {oos['spread']:+.4f})")
    print(f"  survives rate-level control:         {rate_survives}  "
          f"({rate_ctrl['spread_raw']:+.4f} -> {rate_ctrl['spread_rate_residual']:+.4f})")
    print(f"  --> CARD CANDIDATE: {oos_holds and rate_survives}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps({
        "seed": SEED, "horizon": H, "cohort": list(COHORT), "split": "1993-01-01",
        "test0_baseline_spy": t0, "test1_full": full, "test1_oos": oos, "test1_insample": ins,
        "test2_rate_control": rate_ctrl, "test3_exploitability": exploit,
        "oos_sign_holds": bool(oos_holds), "survives_rate_control": bool(rate_survives),
        "card_candidate": bool(oos_holds and rate_survives),
    }, indent=2, default=lambda o: None) + "\n", encoding="utf-8")
    print(f"\nwrote {(OUT / 'results.json').relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Round 28: is there any cross-sectional information to exploit on the seated equity universes?

    PYTHONIOENCODING=utf-8 PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round28.py

`ROUND-28-PLAN.md` is the pre-registration this executes. Read it first.

Every blocked cross-symbol strategy -- relative strength, pairs, inverse-vol parity -- depends on one
precondition: that a name's past cross-sectional rank predicts its future cross-sectional rank. This
measures that directly, as a rank information coefficient, on the two single-name universes the seated
cards trade. No card, no engine, no backtest.

The Discovery module already answered this on ETF baskets (IC -0.0073, q=0.186). This closes the gap
it left -- single names -- across five signals and two horizons, with a block bootstrap and
Benjamini-Hochberg over all twenty cells (plan sections 3-4).

Determinism note: `Math.random`-style entropy is avoided. The block bootstrap is seeded from a fixed
integer so the p-values reproduce exactly on re-run; the seed is a constant, not the clock.

**Not investment advice.**
"""

from __future__ import annotations

import json
import pathlib

import duckdb
import numpy as np

from app.indicators.registry import compute, request

REPO = pathlib.Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "rounds" / "r28-2026-08"

U12 = ("NVDA", "AMD", "AVGO", "MU", "MRVL", "TSM", "META", "MSFT", "GOOGL", "NOW", "AMZN", "NFLX")
U9 = ("MU", "INTC", "AMD", "TSM", "SOXX", "NVDA", "AVGO", "QCOM", "MRVL")
UNIVERSES = {"U12": (U12, "2012-06-28"), "U9": (U9, "2009-08-05")}

SIGNALS = ("mom_12_1", "mom_6", "vol_60", "reversal_1m", "dist_sma200")
HORIZONS = (21, 63)
REBAL = 21          #: sessions between cross-sections
BOOT = 2000         #: bootstrap resamples
BLOCK = 12          #: block length in rebalance dates (~12 months)
SEED = 28           #: fixed, so p-values reproduce; never the clock (plan determinism note)


def _load(sym: str):
    con = duckdb.connect(":memory:")
    df = con.execute(
        "select ts, open, high, low, close, volume from "
        f"read_parquet('data/store/bars/interval=1d/symbol={sym}/bars.parquet') order by ts"
    ).df().set_index("ts")
    ind = compute(df, [request("sma:200")])
    sma_col = next(c for c in ind.columns if c.lower().startswith("sma"))
    j = df.join(ind)
    # Coerce to a plain datetime64[D] array so date comparisons and dict lookups are type-stable
    # (the DuckDB timestamp comes back as pandas Timestamps otherwise, which will not compare to
    # np.datetime64). Day resolution is safe: these are daily bars, one per session.
    dates = np.asarray(j.index.values, dtype="datetime64[D]")
    return dates, j["close"].to_numpy(), j[sma_col].to_numpy()  # type: ignore[return-value]


def _signal(name: str, close: np.ndarray, sma: np.ndarray, t: int) -> float | None:
    """One name's signal value at bar index `t`, or None if history is insufficient."""
    if name == "mom_12_1":
        return close[t - 21] / close[t - 252] - 1 if t >= 252 else None
    if name == "mom_6":
        return close[t] / close[t - 126] - 1 if t >= 126 else None
    if name == "vol_60":
        if t < 60:
            return None
        r = close[t - 59 : t + 1] / close[t - 60 : t] - 1
        return float(np.std(r))
    if name == "reversal_1m":
        return close[t] / close[t - 21] - 1 if t >= 21 else None
    if name == "dist_sma200":
        return close[t] / sma[t] - 1 if not np.isnan(sma[t]) else None
    raise ValueError(name)


def _spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    """Spearman rank correlation, or None if degenerate (all-equal ranks)."""
    if len(a) < 3:
        return None
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def _block_bootstrap_p(per_date_ic: np.ndarray, rng: np.random.Generator) -> float:
    """Two-sided p-value that mean IC = 0, via a stationary block bootstrap over dates."""
    n = len(per_date_ic)
    obs = float(np.mean(per_date_ic))
    centred = per_date_ic - obs                       # resample under H0: mean 0
    n_blocks = int(np.ceil(n / BLOCK)) + 1
    count = 0
    for _ in range(BOOT):
        starts = rng.integers(0, n, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + BLOCK) % n for s in starts])[:n]
        if abs(float(np.mean(centred[idx]))) >= abs(obs):
            count += 1
    return (count + 1) / (BOOT + 1)


def _benjamini_hochberg(pvals: list[float]) -> list[float]:
    """BH-adjusted q-values, same convention as app.backtest.scan."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [0.0] * m
    prev = 1.0
    for rank, i in enumerate(reversed(order), start=1):
        k = m - rank + 1
        val = min(prev, pvals[i] * m / k)
        q[i] = val
        prev = val
    return q


def main() -> int:
    bars = {}
    for names, _ in UNIVERSES.values():
        for s in names:
            if s not in bars:
                bars[s] = _load(s)

    rng = np.random.default_rng(SEED)
    cells: list[dict] = []
    for uname, (names, start) in UNIVERSES.items():
        start_dt = np.datetime64(start, "D")
        # A common calendar: the intersection would drop holidays unevenly, so use the first name's
        # sessions on or after `start` and require every name to have a bar on that date.
        ref_dates = bars[names[0]][0]
        cal = ref_dates[ref_dates >= start_dt]
        # index of each date within each name's own array
        pos = {s: {d: i for i, d in enumerate(bars[s][0])} for s in names}

        for sig in SIGNALS:
            for h in HORIZONS:
                # Amendment 1: rebalance at the horizon so forward windows never overlap. For h=21
                # this is identical to the original REBAL=21; for h=63 it drops the 3:1 overlap that
                # inflated the pre-registered run's one survivor (plan section 7).
                rebal_dates = cal[::h]
                per_date = []
                for d in rebal_dates:
                    svals, fwd = [], []
                    for s in names:
                        p = pos[s].get(d)
                        if p is None:
                            continue
                        _, close, sma = bars[s]
                        if p + h >= len(close):
                            continue
                        v = _signal(sig, close, sma, p)
                        if v is None:
                            continue
                        svals.append(v)
                        fwd.append(close[p + h] / close[p] - 1)
                    if len(svals) < 5:
                        continue
                    fwd_arr = np.array(fwd)
                    demeaned = fwd_arr - fwd_arr.mean()          # relative return (plan 3c)
                    ic = _spearman(np.array(svals), demeaned)
                    if ic is not None:
                        per_date.append(ic)
                per_date = np.array(per_date)
                mean_ic = float(np.mean(per_date)) if len(per_date) else float("nan")
                p = _block_bootstrap_p(per_date, rng) if len(per_date) >= BLOCK else float("nan")
                cells.append({
                    "universe": uname, "signal": sig, "horizon": h,
                    "mean_ic": mean_ic, "n_dates": len(per_date), "p_value": p,
                })

    valid = [c for c in cells if not np.isnan(c["p_value"])]
    qs = _benjamini_hochberg([c["p_value"] for c in valid])
    for c, q in zip(valid, qs, strict=True):
        c["q_value"] = q
    for c in cells:
        c.setdefault("q_value", float("nan"))

    survivors = [c for c in cells if not np.isnan(c["q_value"]) and c["q_value"] < 0.10]

    print(f"{'universe':9s} {'signal':12s} {'h':>3s} {'mean_IC':>9s} {'n':>4s} {'p':>7s} {'q':>7s}")
    for c in sorted(cells, key=lambda x: (x["universe"], x["signal"], x["horizon"])):
        star = " *" if c in survivors else ""
        print(f"{c['universe']:9s} {c['signal']:12s} {c['horizon']:3d} "
              f"{c['mean_ic']:+9.4f} {c['n_dates']:4d} {c['p_value']:7.3f} {c['q_value']:7.3f}{star}")

    # Per-signal mean |IC| across universes/horizons, and the U12-vs-U9 comparison (predictions 2, 5).
    print("\nmean |IC| by signal:")
    for sig in SIGNALS:
        vals = [abs(c["mean_ic"]) for c in cells if c["signal"] == sig and not np.isnan(c["mean_ic"])]
        print(f"  {sig:12s} {np.mean(vals):+.4f}")
    for u in ("U12", "U9"):
        vals = [abs(c["mean_ic"]) for c in cells if c["universe"] == u and not np.isnan(c["mean_ic"])]
        print(f"  mean |IC| {u}: {np.mean(vals):.4f}")

    print(f"\nsurvivors at q<0.10: {len(survivors)}")
    for c in survivors:
        print(f"  {c['universe']} {c['signal']} h={c['horizon']}  IC={c['mean_ic']:+.4f} q={c['q_value']:.3f}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ic.json").write_text(json.dumps({"cells": cells, "survivors": len(survivors),
                                             "seed": SEED, "boot": BOOT, "block": BLOCK},
                                            indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {(OUT / 'ic.json').relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

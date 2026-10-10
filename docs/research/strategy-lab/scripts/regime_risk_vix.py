"""regime-risk stream: VIX-conditioned forward returns (note p.11, "[Macro] Fear & Greed / VIX based
investment strategies").

**Why this is not a DSL family.** The rule DSL evaluates one symbol's own frame at a time (BRIEF.md
section 4); "buy SPY when VIX > 30" needs a second symbol's series joined in by date, which the
grammar has no operator for. Done here directly in pandas, per BRIEF.md's explicit instruction for
this stream. `^VIX` is read via `quantlab.bars_frame("^VIX")` and is used **only** as a signal joined
onto each primary symbol's own bars by date -- never backtested as an instrument (BRIEF.md section 2).

**Every statistic reused from the app, not reimplemented.** The forward-return sample, the
non-overlapping/independent count, and the hit rate all come from `app.backtest.forward` -- the exact
same functions `app.backtest.events.event_study` calls internally for a DSL condition. The only new
work this module does is building the trigger mask (VIX > threshold on date *t*, joined to symbol
*t*), which the DSL cannot express; the statistics behind it are the app's own.

**Thresholds declared before anything is computed**, per BRIEF.md's explicit instruction:

- `vix_gt_20` -- the conventional "elevated" line (VIX's long-run median sits in the high teens; 20
  is the round-number level widely cited as "elevated" market stress).
- `vix_gt_30` -- the conventional "high fear / crisis" line (VIX > 30 historically brackets 2008,
  2020, and a handful of shorter spikes).
- `vix_gt_p80` -- a distribution-relative threshold: the VIX's own 80th percentile computed over its
  **full cached history** (1993-2026). This is explicitly an in-sample, non-real-time-computable
  threshold (a trader on any given day could not know the full-history 80th percentile without
  seeing the future) -- flagged here and again in the report's "what this cannot tell you" section,
  not silently used as if it were tradable.

Horizon is declared once, at 20 trading days (~1 month), matching this stream's other horizon
choices. Direction is declared 'up' for all three: the hypothesis under test is the contrarian
"elevated fear precedes better-than-baseline forward returns" reading implied by a VIX/Fear&Greed
"buy the fear" strategy -- an edge running the other way is a rejection of that reading, not merely
inconclusive.

**Lookahead.** Not a DSL expression, so no `guards.check` status applies (BRIEF.md's guard-status
requirement is scoped to DSL expressions). Checked manually instead: the trigger for day *t* uses
`^VIX`'s close on day *t* (settled, known) joined to the same calendar date in the symbol's frame, and
the forward return is measured from day *t+1*'s open (`Entry.NEXT_OPEN`, the same convention every
other module in this study uses) -- so nothing later than the trigger day's own close is used to
decide the trigger. The one exception is `vix_gt_p80`'s threshold *value* itself, which is computed
over the full history including dates after any given trigger -- see the caveat above.

Declared family: 3 thresholds x 5 primary symbols = 15 tests, one BH ledger.

Run from docs/research/strategy-lab/:
    ../../../.venv/Scripts/python.exe scripts/regime_risk_vix.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, "lib")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from quantlab import bars_frame, write  # noqa: E402

from app.backtest import scan as scan_mod  # noqa: E402
from app.backtest.forward import forward_returns, hit_rate, independent_count  # noqa: E402
from app.rules.models import Entry  # noqa: E402

PRIMARY = ["SPY", "QQQ", "IWM", "XLK", "XLV"]
HORIZON = 20
DIRECTION = "up"


def _dates(bars: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(bars["ts"]).dt.tz_localize(None).dt.normalize()


def build_thresholds(vix_bars: pd.DataFrame) -> list[dict]:
    vix_close = vix_bars["close"].dropna()
    p80 = float(np.percentile(vix_close.to_numpy(), 80))
    return [
        dict(key="vix_gt_20", label="VIX > 20 (elevated)", value=20.0, in_sample=False),
        dict(key="vix_gt_30", label="VIX > 30 (high fear / crisis)", value=30.0, in_sample=False),
        dict(
            key="vix_gt_p80",
            label=f"VIX > its own full-history 80th pct ({p80:.2f})",
            value=p80,
            in_sample=True,
        ),
    ]


def run_symbol_threshold(bars: pd.DataFrame, vix_aligned: pd.Series, threshold: dict) -> dict:
    """One (symbol, threshold) cell: forward-return hit rate on days VIX > threshold vs the same
    symbol's own unconditional baseline at the same horizon, both from `app.backtest.forward`."""
    fr = forward_returns(bars, horizon=HORIZON, entry=Entry.NEXT_OPEN)
    evaluable = ~np.isnan(fr)
    baseline_sample = fr[evaluable]
    baseline_hit = hit_rate(baseline_sample)

    trigger_mask = evaluable & (vix_aligned.to_numpy() > threshold["value"])
    trigger_positions = np.flatnonzero(trigger_mask)
    arm_sample = fr[trigger_mask]
    hit = hit_rate(arm_sample)
    n_raw = int(trigger_mask.sum())
    n_indep = independent_count(trigger_positions, HORIZON)

    edge = None if hit is None or baseline_hit is None else hit - baseline_hit
    p_value = None
    if hit is not None and baseline_hit is not None and n_indep > 0:
        successes = max(0, min(n_indep, round(hit * n_indep)))
        p_value = scan_mod.binomial_p_value(successes, n_indep, baseline_hit)

    return {
        "threshold_key": threshold["key"],
        "threshold_label": threshold["label"],
        "threshold_value": threshold["value"],
        "in_sample_threshold": threshold["in_sample"],
        "horizon": HORIZON,
        "direction": DIRECTION,
        "hit_rate": hit,
        "baseline": baseline_hit,
        "edge": edge,
        "n_raw": n_raw,
        "n_independent": n_indep,
        "p_value": p_value,
        "mean_forward_return_arm": float(np.nanmean(arm_sample)) if arm_sample.size else None,
        "mean_forward_return_baseline": float(np.nanmean(baseline_sample)) if baseline_sample.size else None,
    }


def verdict_for(row: dict) -> str:
    edge, p, n = row["edge"], row.get("q_value"), row["n_independent"]
    if edge is None or p is None:
        return "untestable"
    wrong_way = edge < 0  # direction == "up" for every cell in this family
    if wrong_way:
        return "rejected"
    if n < 30:
        return "underpowered"
    return "survived" if p <= 0.10 else "inconclusive"


def main() -> None:
    vix_bars = bars_frame("^VIX")
    vix_dates = _dates(vix_bars)
    vix_by_date = pd.Series(vix_bars["close"].to_numpy(), index=vix_dates)

    thresholds = build_thresholds(vix_bars)
    print("=== regime-risk VIX family: thresholds declared before running ===")
    for t in thresholds:
        print(f"  {t['key']:12s} {t['label']}  in_sample={t['in_sample']}")

    all_rows = []
    per_symbol = {}
    for symbol in PRIMARY:
        bars = bars_frame(symbol)
        sym_dates = _dates(bars)
        # Align VIX close onto the symbol's own calendar: forward-filled from the most recent VIX
        # close on/before this symbol's bar date, since VIX and equity ETFs occasionally miss
        # different holidays. A date with no VIX observation at all (before VIX's own coverage start)
        # produces NaN, which fails the `> threshold` comparison and simply is not a trigger day --
        # not treated as an extreme reading, matching the app's own "absent, not extreme" convention
        # in `fear_greed.py`.
        vix_aligned = vix_by_date.reindex(sym_dates, method="ffill")
        vix_aligned.index = bars.index

        rows = []
        for threshold in thresholds:
            row = run_symbol_threshold(bars, vix_aligned, threshold)
            row["symbol"] = symbol
            rows.append(row)
            all_rows.append(row)
        per_symbol[symbol] = {
            "coverage": {"bars": len(bars), "first": str(bars["ts"].min().date()),
                         "last": str(bars["ts"].max().date())},
            "rows": rows,
        }

    print(f"\n=== {len(all_rows)} tests ({len(thresholds)} thresholds x {len(PRIMARY)} symbols), "
          "one BH ledger ===")
    p_values = [r["p_value"] for r in all_rows]
    q_values = scan_mod.benjamini_hochberg(p_values)
    for row, q in zip(all_rows, q_values, strict=True):
        row["q_value"] = q
        row["verdict"] = verdict_for(row)
    # per_symbol[*]["rows"] holds the same dict objects as all_rows, so the q_value/verdict update
    # above is already visible there too -- no separate fold-back needed (contrast
    # regime_risk_seasonality.py, which copies rows into a flat list and does need one).

    for row in all_rows:
        e = "n/a" if row["edge"] is None else f"{row['edge']:+.4f}"
        print(
            f"  {row['symbol']:6s} {row['threshold_key']:12s} edge={e} hit={row['hit_rate']} "
            f"base={row['baseline']:.4f} n_raw={row['n_raw']:5d} n_ind={row['n_independent']:4d} "
            f"p={row['p_value']:.4f} q={row['q_value']:.4f} verdict={row['verdict']}"
        )

    survivors = [r for r in all_rows if r["verdict"] == "survived"]
    print(f"\n{len(survivors)} survivor(s) at q<=0.10")

    result = {
        "family": "regime-risk-vix",
        "screen_alpha": 0.10,
        "small_sample_threshold": 30,
        "horizon": HORIZON,
        "direction": DIRECTION,
        "thresholds_declared": thresholds,
        "symbols_declared": PRIMARY,
        "family_size": len(all_rows),
        "cells": all_rows,
        "survivors": survivors,
        "per_symbol": per_symbol,
    }
    write(result, "regime_risk_vix")
    print("\n=== regime_risk_vix.py complete ===")


if __name__ == "__main__":
    main()

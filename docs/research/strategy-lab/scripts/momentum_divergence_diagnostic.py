"""momentum stream: descriptive, non-DSL divergence diagnostic (note p.6, contents item 1b).

**This is not part of the corrected `momentum` family and carries no p-value.** The rule DSL
(`docs/research/strategy-lab/lib/quantlab.py`, section 4 of BRIEF.md) has no lookback-extremum
operator, so "price makes a lower low while MACD makes a higher low" cannot be written as a DSL
expression and cannot go through `app.backtest.events.event_study` or the guarded rule engine at
all. Faking it with a crossover (e.g. treating a MACD signal-line cross as a divergence) would be
silently substituting a different, better-understood signal and calling it by the note's name --
the brief explicitly says not to do that.

What this script does instead: computes MACD directly with `app.indicators.trend.macd` (the same
function the app itself uses, so the indicator values match production exactly) on the production
bars cache via `quantlab.bars_frame`, then finds local price extrema with plain pandas/numpy --
outside `app.backtest` entirely, no guard check, no event_study, no BH correction. A "naive
divergence" is flagged between two consecutive swing lows (bullish) or two consecutive swing highs
(bearish) where price and MACD disagree on direction. Forward returns following each flagged bar are
reported as descriptive statistics only: counts, rates, mean/median, compared to the unconditional
forward-return distribution over the same window. No hypothesis test, no baseline in the
`event_study` sense, no q-value -- these numbers describe what a naive definition would have flagged
historically, nothing more, and must not be read as a screened finding.

Run from docs/research/strategy-lab/:
    ../../../.venv/Scripts/python.exe scripts/momentum_divergence_diagnostic.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "lib")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from quantlab import LAB, bars_frame  # noqa: E402

# docs/research/strategy-lab/scripts/momentum_divergence_diagnostic.py -> scripts -> strategy-lab ->
# research -> docs -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT / "backend"))
from app.indicators.trend import macd as macd_indicator  # noqa: E402

PRIMARY = ["SPY", "QQQ", "IWM", "XLK", "XLV"]
SWING_ORDER = 5          # a bar is a swing low/high if it is the extreme within +/- this many bars
FORWARD_HORIZON = 10      # trading days forward, matched to the primary family's declared horizon


def find_swings(values: np.ndarray, order: int, mode: str) -> list[int]:
    """Indices of strict local extrema: `values[i]` is the unique min/max within `[i-order, i+order]`."""
    n = len(values)
    idxs = []
    for i in range(order, n - order):
        window = values[i - order : i + order + 1]
        target = window.min() if mode == "min" else window.max()
        if values[i] == target and (window == target).sum() == 1:
            idxs.append(i)
    return idxs


def diagnose(symbol: str) -> dict:
    bars = bars_frame(symbol)
    close = bars["close"].to_numpy()
    mdf = macd_indicator(bars, fast=12, slow=26, signal=9)
    macd_col = [c for c in mdf.columns if c.endswith("_macd")][0]
    macd_line = mdf[macd_col].to_numpy()

    valid = ~np.isnan(macd_line)
    first_valid = int(np.argmax(valid)) if valid.any() else len(macd_line)

    lows = [i for i in find_swings(close, SWING_ORDER, "min") if i >= first_valid and not np.isnan(macd_line[i])]
    highs = [i for i in find_swings(close, SWING_ORDER, "max") if i >= first_valid and not np.isnan(macd_line[i])]

    n = len(bars)

    def forward_return(i: int, h: int) -> float | None:
        j = i + h
        if j >= n:
            return None
        return (close[j] - close[i]) / close[i]

    # unconditional baseline: forward return from every evaluable bar
    all_fwd = [
        forward_return(i, FORWARD_HORIZON)
        for i in range(first_valid, n - FORWARD_HORIZON)
    ]
    all_fwd = [x for x in all_fwd if x is not None]

    bullish_events = []
    for a, b in zip(lows, lows[1:]):
        if close[b] < close[a] and macd_line[b] > macd_line[a]:
            fwd = forward_return(b, FORWARD_HORIZON)
            bullish_events.append(
                {
                    "prior_low_idx": a,
                    "prior_low_date": str(bars["ts"].iloc[a].date()),
                    "low_idx": b,
                    "low_date": str(bars["ts"].iloc[b].date()),
                    "price_change": float((close[b] - close[a]) / close[a]),
                    "macd_change": float(macd_line[b] - macd_line[a]),
                    f"forward_return_{FORWARD_HORIZON}d": fwd,
                }
            )

    bearish_events = []
    for a, b in zip(highs, highs[1:]):
        if close[b] > close[a] and macd_line[b] < macd_line[a]:
            fwd = forward_return(b, FORWARD_HORIZON)
            bearish_events.append(
                {
                    "prior_high_idx": a,
                    "prior_high_date": str(bars["ts"].iloc[a].date()),
                    "high_idx": b,
                    "high_date": str(bars["ts"].iloc[b].date()),
                    "price_change": float((close[b] - close[a]) / close[a]),
                    "macd_change": float(macd_line[b] - macd_line[a]),
                    f"forward_return_{FORWARD_HORIZON}d": fwd,
                }
            )

    years = n / 252.0

    def summarize(events: list[dict]) -> dict:
        fwds = [e[f"forward_return_{FORWARD_HORIZON}d"] for e in events if e[f"forward_return_{FORWARD_HORIZON}d"] is not None]
        return {
            "count": len(events),
            "per_year": len(events) / years,
            "mean_forward_return": float(np.mean(fwds)) if fwds else None,
            "median_forward_return": float(np.median(fwds)) if fwds else None,
            "share_positive_forward": float(np.mean([f > 0 for f in fwds])) if fwds else None,
        }

    return {
        "symbol": symbol,
        "bars": n,
        "years": round(years, 1),
        "swing_lows_found": len(lows),
        "swing_highs_found": len(highs),
        "unconditional_baseline": {
            "n": len(all_fwd),
            "mean_forward_return": float(np.mean(all_fwd)) if all_fwd else None,
            "median_forward_return": float(np.median(all_fwd)) if all_fwd else None,
            "share_positive_forward": float(np.mean([f > 0 for f in all_fwd])) if all_fwd else None,
        },
        "naive_bullish_divergence": summarize(bullish_events),
        "naive_bearish_divergence": summarize(bearish_events),
        "bullish_events_detail": bullish_events,
        "bearish_events_detail": bearish_events,
    }


if __name__ == "__main__":
    result = {
        "descriptive_only": True,
        "guarded_rule_engine": False,
        "p_value": None,
        "note": (
            "Naive divergence diagnostic outside app.backtest entirely. Swing points are the strict "
            "local extreme within +/-5 bars; a 'divergence' is flagged between two consecutive swing "
            "lows (bullish) or highs (bearish) where price and MACD(12,26,9) disagree on direction. "
            "Forward return is measured from the second swing point's close, matched to the primary "
            "family's 10-bar horizon. This is a plain pandas/numpy computation on the bars frame, not "
            "a DSL expression, not run through event_study, not BH-corrected, and not a finding of "
            "this study -- it exists only to answer 'how often would a naive definition have fired, "
            "and what followed', as the brief requests."
        ),
        "swing_order": SWING_ORDER,
        "forward_horizon": FORWARD_HORIZON,
        "symbols": {},
    }
    for sym in PRIMARY:
        print(f"=== {sym} ===")
        d = diagnose(sym)
        result["symbols"][sym] = d
        print(
            f"  bullish: n={d['naive_bullish_divergence']['count']} "
            f"({d['naive_bullish_divergence']['per_year']:.2f}/yr) "
            f"mean_fwd={d['naive_bullish_divergence']['mean_forward_return']}"
        )
        print(
            f"  bearish: n={d['naive_bearish_divergence']['count']} "
            f"({d['naive_bearish_divergence']['per_year']:.2f}/yr) "
            f"mean_fwd={d['naive_bearish_divergence']['mean_forward_return']}"
        )
        print(f"  unconditional baseline mean_fwd={d['unconditional_baseline']['mean_forward_return']}")

    out = LAB / "data" / "momentum_divergence_diagnostic.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {out}")

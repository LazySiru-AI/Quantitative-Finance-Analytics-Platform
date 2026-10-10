"""regime-risk stream: ATR position sizing and stop distance (note p.2 risk leg: "ATR based position
sizing", "max drawdown cap"; note p.7: "How much does this asset normally move each day? More
volatile assets => smaller positions", ATR(14) for stop distance and volatility targeting).

**Why position sizing itself cannot be backtested through the engine.** `app.backtest.strategy`'s
module docstring is explicit: the engine is long-only, all-in on every entry, no pyramiding, and
`Costs.notional` is a unit converter for a flat per-trade commission, not a sizing decision -- "bars
carry prices, not share counts, and position sizing is deliberately out of scope." There is no
`position_size_pct` or `risk_per_trade` field on `StrategySpec` to vary. So "ATR-based position
sizing" as literally described in the note cannot be run through `app.backtest.strategy.backtest`,
full stop -- see BRIEF.md's own instruction on this point.

**What the engine *can* answer, and does, in Part 1 below.** `StrategySpec.stop_loss_pct` exists, and
a stop distance is the one ATR-derived risk parameter the engine actually prices (against the bar's
own `low`, with slippage re-run for `cost_drag`, exactly like every other strategy in this study). So
Part 1 runs the *same* entry/exit through the real engine at a fixed % stop and at 1x/2x/3x that
symbol's own typical ATR(14)-implied stop distance, and reports the mechanics (return, drawdown,
trades, stop-exit share) side by side. This is a mechanics comparison, not a hit-rate hypothesis: the
stop does not change the entry signal's forward hit rate (the event-study arm is keyed on the entry
expression alone), so these cells carry **no p-value and are not added to any BH ledger** -- exactly
the same reasoning `run_family`'s own `windows` argument uses for regime-window slices.

**Part 2 is explicitly outside the engine.** ATR-*proportional* daily position sizing applied to a
simple always-in position, computed directly in pandas: no `StrategySpec`, no fills, no lookahead
guard (there is no rule-DSL expression here to guard), and **no p-value** -- this is a descriptive
simulation of what a size-inversely-to-ATR discipline would have done to volatility and drawdown, nnot
a test of any pre-registered hypothesis, and BRIEF.md asks for it to be labelled as such.

Shared entry/exit for Part 1: `close > sma(200)` / `close < sma(200)`, the same expression trend-ma's
`regime_filter_standalone` already ran with no stop (see `data/trend_ma_primary.json`) -- reused here
as the "no stop" row rather than re-run, and then re-run locally too as a consistency check (should
match trend-ma's numbers on this same universe and window).

Run from docs/research/strategy-lab/:
    ../../../.venv/Scripts/python.exe scripts/regime_risk_atr_stops.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, "lib")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from quantlab import Idea, bars_frame, strategy_backtest, write  # noqa: E402

from app.indicators.volatility import atr as atr_indicator  # noqa: E402

PRIMARY = ["SPY", "QQQ", "IWM", "XLK", "XLV"]
ATR_PERIOD = 14
FIXED_STOPS = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
ATR_MULTIPLES = [1, 2, 3]

# ---------------------------------------------------------------------------
# Part 1: ATR-as-%-of-price calibration, and fixed vs ATR-implied stop mechanics through the engine.
# ---------------------------------------------------------------------------

SHARED_ENTRY = "close > sma(200)"
SHARED_EXIT = "close < sma(200)"


def atr_pct_series(bars: pd.DataFrame) -> pd.Series:
    """`atr(14) / close`, using the app's own Wilder-smoothed ATR (`app.indicators.volatility.atr`),
    not a reimplementation -- see that module's docstring for why Wilder smoothing (not a plain
    rolling mean of true range) is the definition this app's `atr(14)` DSL indicator computes."""
    atr_df = atr_indicator(bars, period=ATR_PERIOD)
    col = atr_df.columns[0]
    return (atr_df[col] / bars["close"]).astype(float)


def atr_calibration(symbol: str, bars: pd.DataFrame) -> dict:
    pct = atr_pct_series(bars).dropna()
    median_pct = float(pct.median())
    row = {
        "symbol": symbol,
        "n_obs": int(len(pct)),
        "atr_pct_median": median_pct,
        "atr_pct_p25": float(pct.quantile(0.25)),
        "atr_pct_p75": float(pct.quantile(0.75)),
        "atr_pct_min": float(pct.min()),
        "atr_pct_max": float(pct.max()),
        "atr_pct_last_252d_median": float(pct.tail(252).median()) if len(pct) >= 252 else None,
    }
    for k in ATR_MULTIPLES:
        row[f"atr_{k}x_typical_stop_pct"] = median_pct * k
    return row


def mechanics_row(bars: pd.DataFrame, *, stop_label: str, stop_source: str, stop_pct: float | None) -> dict:
    idea = Idea(
        key=f"atr_stop_probe_{stop_label}",
        entry=SHARED_ENTRY,
        exit=SHARED_EXIT,
        horizon=20,
        direction="up",
        stop_loss_pct=stop_pct,
        rationale="mechanics-only stop-distance probe, not part of any BH ledger",
    )
    bt = strategy_backtest(bars, idea)
    if bt is None:
        return {"stop_label": stop_label, "stop_source": stop_source, "stop_pct": stop_pct, "error": "no result"}
    exit_counts = bt["exit_reason_counts"]
    total_closed = bt["closed_trades"] or 1
    return {
        "stop_label": stop_label,
        "stop_source": stop_source,
        "stop_pct": stop_pct,
        "total_return": bt["strategy"]["total_return"],
        "cagr": bt["strategy"]["cagr"],
        "sharpe": bt["strategy"]["sharpe"],
        "max_drawdown": bt["strategy"]["max_drawdown"],
        "exposure": bt["strategy"]["exposure"],
        "trades_closed": bt["closed_trades"],
        "win_rate": bt["strategy"]["win_rate"],
        "cost_drag": bt["cost_drag"],
        "worst_trade": bt["worst_trade"],
        "avg_bars_held": bt["avg_bars_held"],
        "stop_exit_share": exit_counts.get("stop", 0) / total_closed,
        "signal_exit_share": exit_counts.get("signal", 0) / total_closed,
        "buy_hold_total_return": bt["buy_hold"]["total_return"],
        "buy_hold_max_drawdown": bt["buy_hold"]["max_drawdown"],
    }


def run_part1(symbol: str, bars: pd.DataFrame, calib: dict) -> list[dict]:
    rows = []
    rows.append(mechanics_row(bars, stop_label="no_stop", stop_source="none", stop_pct=None))
    for pct in FIXED_STOPS:
        rows.append(mechanics_row(bars, stop_label=f"fixed_{int(pct * 100)}pct", stop_source="fixed", stop_pct=pct))
    for k in ATR_MULTIPLES:
        pct = calib[f"atr_{k}x_typical_stop_pct"]
        rows.append(
            mechanics_row(bars, stop_label=f"atr_{k}x_typical", stop_source="atr_typical", stop_pct=pct)
        )
    for r in rows:
        r["symbol"] = symbol
    return rows


# ---------------------------------------------------------------------------
# Part 2: descriptive ATR-proportional sizing simulation, entirely outside the engine, no p-value.
# ---------------------------------------------------------------------------

SIZING_CAP = 3.0  # position weight capped at 3x average exposure -- a near-zero ATR day must not
# produce an unbounded weight; this cap is a modelling choice, stated explicitly rather than hidden.


def atr_proportional_simulation(symbol: str, bars: pd.DataFrame) -> dict:
    close = bars["close"].astype(float)
    daily_ret = close.pct_change()
    pct = atr_pct_series(bars)

    # Size using YESTERDAY's ATR% (shift(1)) -- today's position is sized on information known
    # before today's return is realised, avoiding lookahead in this descriptive simulation.
    inv_atr = 1.0 / pct.shift(1)
    inv_atr = inv_atr.replace([np.inf, -np.inf], np.nan)
    valid = inv_atr.notna() & daily_ret.notna()

    # Scale k so the mean weight over the valid sample equals 1.0 -- same average exposure as
    # buy-and-hold, so what's being compared is volatility/drawdown shape, not leverage.
    k = 1.0 / inv_atr[valid].mean()
    weight = (k * inv_atr).clip(lower=0.0, upper=SIZING_CAP)

    bh_ret = daily_ret[valid]
    atr_ret = (weight * daily_ret)[valid]

    def ann_vol(r: pd.Series) -> float:
        return float(r.std(ddof=1) * np.sqrt(252))

    def max_dd(r: pd.Series) -> float:
        eq = (1.0 + r.fillna(0.0)).cumprod()
        peak = eq.cummax()
        return float((eq / peak - 1.0).min())

    def total_return(r: pd.Series) -> float:
        return float((1.0 + r.fillna(0.0)).prod() - 1.0)

    def sharpe(r: pd.Series) -> float | None:
        sd = r.std(ddof=1)
        if sd == 0 or np.isnan(sd):
            return None
        return float(r.mean() / sd * np.sqrt(252))

    return {
        "symbol": symbol,
        "n_days": int(valid.sum()),
        "sizing_k": float(k),
        "sizing_cap": SIZING_CAP,
        "mean_weight": float(weight[valid].mean()),
        "weight_p05": float(weight[valid].quantile(0.05)),
        "weight_p95": float(weight[valid].quantile(0.95)),
        "buy_hold": {
            "total_return": total_return(bh_ret),
            "annualised_vol": ann_vol(bh_ret),
            "max_drawdown": max_dd(bh_ret),
            "sharpe": sharpe(bh_ret),
        },
        "atr_proportional": {
            "total_return": total_return(atr_ret),
            "annualised_vol": ann_vol(atr_ret),
            "max_drawdown": max_dd(atr_ret),
            "sharpe": sharpe(atr_ret),
        },
    }


def main() -> None:
    print("=== Part 1: ATR calibration + fixed-vs-ATR-implied stop mechanics (engine, no p-value) ===")
    calibrations = {}
    part1_rows = []
    for symbol in PRIMARY:
        bars = bars_frame(symbol)
        calib = atr_calibration(symbol, bars)
        calibrations[symbol] = calib
        print(
            f"  {symbol:6s} atr14_pct median={calib['atr_pct_median']:.4f} "
            f"(p25={calib['atr_pct_p25']:.4f} p75={calib['atr_pct_p75']:.4f})  "
            f"1x={calib['atr_1x_typical_stop_pct']:.4f} 2x={calib['atr_2x_typical_stop_pct']:.4f} "
            f"3x={calib['atr_3x_typical_stop_pct']:.4f}"
        )
        rows = run_part1(symbol, bars, calib)
        part1_rows.extend(rows)
        for r in rows:
            print(
                f"    {r['stop_label']:18s} src={r['stop_source']:12s} "
                f"stop={r['stop_pct']!s:>8} tr={r['total_return']:.3f} dd={r['max_drawdown']:.3f} "
                f"trades={r['trades_closed']:3d} stop_exit%={r['stop_exit_share']:.2f} "
                f"cost_drag={r['cost_drag']:.3f}"
            )

    print("\n=== Part 2: descriptive ATR-proportional sizing simulation (pandas only, no p-value) ===")
    part2_rows = []
    for symbol in PRIMARY:
        bars = bars_frame(symbol)
        sim = atr_proportional_simulation(symbol, bars)
        part2_rows.append(sim)
        print(
            f"  {symbol:6s} mean_w={sim['mean_weight']:.3f} "
            f"BH: tr={sim['buy_hold']['total_return']:.3f} vol={sim['buy_hold']['annualised_vol']:.3f} "
            f"dd={sim['buy_hold']['max_drawdown']:.3f} sharpe={sim['buy_hold']['sharpe']}  |  "
            f"ATR-sized: tr={sim['atr_proportional']['total_return']:.3f} "
            f"vol={sim['atr_proportional']['annualised_vol']:.3f} "
            f"dd={sim['atr_proportional']['max_drawdown']:.3f} "
            f"sharpe={sim['atr_proportional']['sharpe']}"
        )

    result = {
        "note": "Part 1 is mechanics-only (no p-value, not part of any BH ledger) -- see module "
        "docstring. Part 2 is a descriptive simulation entirely outside app.backtest.strategy -- no "
        "p-value, no hypothesis test.",
        "atr_period": ATR_PERIOD,
        "fixed_stops_tested": FIXED_STOPS,
        "atr_multiples_tested": ATR_MULTIPLES,
        "shared_entry": SHARED_ENTRY,
        "shared_exit": SHARED_EXIT,
        "calibrations": calibrations,
        "part1_stop_mechanics": part1_rows,
        "sizing_cap": SIZING_CAP,
        "part2_atr_proportional_sizing": part2_rows,
    }
    write(result, "regime_risk_atr_stops")
    print("\n=== regime_risk_atr_stops.py complete ===")


if __name__ == "__main__":
    main()

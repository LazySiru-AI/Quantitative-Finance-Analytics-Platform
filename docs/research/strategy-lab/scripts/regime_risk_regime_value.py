"""regime-risk stream: does the close > sma(200) regime filter earn its keep? (note p.2: "trade only
when broader market context is favorable", "price > 200MA = positive long term trend").

**Coordination, stated once.** The trend-ma stream already ran `close > sma(200)` / exit
`close < sma(200)` as `regime_filter_standalone` in its own 9-idea/45-test family
(`data/trend_ma_primary.json`) -- their hit-rate/q-value verdict is cited from there, not re-derived
here. BRIEF.md asks this stream to approach the same filter "from the regime side (time spent in each
regime, transition counts, drawdown avoided) rather than duplicating their crossover tests" -- that is
exactly what this script computes, plus a loss-streak read on the trade ledger that neither stream's
event-study numbers surface on their own.

**No p-values in this script.** Time-in-regime, transition counts and drawdown-avoided are
descriptive facts about one realised price path, not hypothesis tests with a null to reject -- the
same status `quantlab.drawdown_profile` already carries ("descriptive... no baseline needed"). The
only inferential number reused here is trend-ma's own, cited verbatim.

**Method.**

1. *Time in regime / transitions*: the regime state (`close > sma(200)`) is evaluated once per bar
   directly from `bars['close']` and a 200-bar simple rolling mean -- a plain pandas computation, not
   a DSL condition, so there is no lookahead guard to report (BRIEF.md's guard-status requirement is
   scoped to DSL expressions); the rolling mean at bar *t* uses only bars up to and including *t*, and
   a transition is only ever read off *already-elapsed* state changes, so this carries the same
   no-lookahead property the DSL's own `sma(200) `always has. A transition is one favorable-to-
   unfavorable or unfavorable-to-favorable flip; consecutive same-state bars are one regime episode,
   not one transition per bar.
2. *Drawdown avoided*: the cumulative buy-and-hold return path is split into the days classified
   "favorable" vs "unfavorable" by the same regime state, one bar behind (a regime known at close of
   day *t-1* would gate day *t*'s exposure decision) -- the cumulative return contributed by
   unfavorable-regime days alone is what an investor exposed only during the favorable regime would
   have avoided (or missed, if that contribution was positive).
3. *Loss-streak / worst-trade read*: pulls the trade ledger directly from
   `app.backtest.strategy.backtest` for the regime-gated long (same expression as trend-ma's idea,
   run locally to get the `Trade` list, which `run_family`'s JSON output does not carry) and reports
   the longest consecutive run of losing closed trades and the single worst trade, addressing note
   p.2's "no single trade or loss streak can significantly damage the whole portfolio" directly.

Run from docs/research/strategy-lab/:
    ../../../.venv/Scripts/python.exe scripts/regime_risk_regime_value.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "lib")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from quantlab import LAB, bars_frame, write  # noqa: E402

from app.backtest import strategy as strategy_mod  # noqa: E402
from app.backtest.models import Costs, StrategySpec  # noqa: E402
from app.db.duck import Interval  # noqa: E402

PRIMARY = ["SPY", "QQQ", "IWM", "XLK", "XLV"]
SMA_WINDOW = 200


def regime_state(bars: pd.DataFrame) -> pd.Series:
    """`True` where close > sma(200), `NaN`-safe: bars inside the SMA warmup are `pd.NA`, matching
    the DSL's own "warmup is not a truth value" convention (see app.backtest.events docstring)."""
    sma = bars["close"].rolling(SMA_WINDOW, min_periods=SMA_WINDOW).mean()
    state = (bars["close"] > sma).astype("boolean")  # nullable boolean dtype, so pd.NA assigns cleanly
    state[sma.isna()] = pd.NA
    return state


def time_in_regime_and_transitions(state: pd.Series) -> dict:
    evaluable = state.dropna()
    n = len(evaluable)
    if n == 0:
        return {"error": "no evaluable bars"}
    favorable_bars = int(evaluable.sum())
    unfavorable_bars = n - favorable_bars

    bool_state = evaluable.astype(bool).to_numpy()
    transitions = int(np.sum(bool_state[1:] != bool_state[:-1]))

    # Episode lengths: run-length of consecutive identical states.
    change_points = np.flatnonzero(bool_state[1:] != bool_state[:-1]) + 1
    boundaries = np.concatenate(([0], change_points, [n]))
    episode_lengths = np.diff(boundaries)
    episode_states = bool_state[boundaries[:-1]]
    favorable_episode_lengths = episode_lengths[episode_states]
    unfavorable_episode_lengths = episode_lengths[~episode_states]

    return {
        "evaluable_bars": n,
        "favorable_bars": favorable_bars,
        "unfavorable_bars": unfavorable_bars,
        "favorable_pct": favorable_bars / n,
        "unfavorable_pct": unfavorable_bars / n,
        "transitions": transitions,
        "n_episodes": len(episode_lengths),
        "n_favorable_episodes": int(episode_states.sum()),
        "n_unfavorable_episodes": int((~episode_states).sum()),
        "favorable_episode_median_len": float(np.median(favorable_episode_lengths))
        if len(favorable_episode_lengths) else None,
        "unfavorable_episode_median_len": float(np.median(unfavorable_episode_lengths))
        if len(unfavorable_episode_lengths) else None,
        "favorable_episode_max_len": int(favorable_episode_lengths.max())
        if len(favorable_episode_lengths) else None,
        "unfavorable_episode_max_len": int(unfavorable_episode_lengths.max())
        if len(unfavorable_episode_lengths) else None,
    }


def drawdown_avoided(bars: pd.DataFrame, state: pd.Series) -> dict:
    """Cumulative buy-and-hold return decomposed into the contribution from favorable- vs
    unfavorable-regime days, regime known one bar in arrears (state at close of t-1 gates day t)."""
    close = bars["close"].astype(float)
    daily_ret = close.pct_change()
    gate = state.shift(1)  # yesterday's close decided today's regime membership
    valid = gate.notna() & daily_ret.notna()

    fav_mask = valid & (gate.astype("boolean") == True)  # noqa: E712
    unfav_mask = valid & (gate.astype("boolean") == False)  # noqa: E712

    def compounded(mask: pd.Series) -> float:
        rets = daily_ret[mask]
        if len(rets) == 0:
            return 0.0
        return float((1.0 + rets).prod() - 1.0)

    total_bh = float((1.0 + daily_ret[valid]).prod() - 1.0)
    fav_contribution = compounded(fav_mask)
    unfav_contribution = compounded(unfav_mask)

    # A "stay favorable-only" equity curve: earn the daily return only on favorable-gated days,
    # flat (0%) otherwise -- the mechanical, no-cost version of "exit when the regime turns
    # unfavorable, get back in when it turns favorable again" that ignores trading frictions
    # entirely (contrast with the actual costed strategy backtest in regime_risk_dsl.py /
    # trend-ma's regime_filter_standalone, which prices the same idea with real fills and slippage).
    favorable_only_ret = daily_ret[valid].where(fav_mask[valid], 0.0)
    favorable_only_total = float((1.0 + favorable_only_ret).prod() - 1.0)

    def max_dd(rets: pd.Series) -> float:
        eq = (1.0 + rets.fillna(0.0)).cumprod()
        peak = eq.cummax()
        return float((eq / peak - 1.0).min())

    return {
        "n_days": int(valid.sum()),
        "buy_hold_total_return": total_bh,
        "buy_hold_max_drawdown": max_dd(daily_ret[valid]),
        "favorable_days_contribution": fav_contribution,
        "unfavorable_days_contribution": unfav_contribution,
        "frictionless_favorable_only_total_return": favorable_only_total,
        "frictionless_favorable_only_max_drawdown": max_dd(favorable_only_ret),
        "note": "favorable_only figures are frictionless (no slippage, no re-entry cost) and "
        "therefore an UPPER bound on what a real regime-gated strategy could achieve -- the costed "
        "version with real fills is trend-ma's regime_filter_standalone / this stream's own DSL "
        "family windows, not this number.",
    }


def loss_streak_and_worst_trade(bars: pd.DataFrame) -> dict:
    spec = StrategySpec(entry="close > sma(200)", exit="close < sma(200)")
    m, bh, trades, equity, cost_drag, open_trades = strategy_mod.backtest(
        bars, spec, interval=Interval.DAY, costs=Costs()
    )
    closed = [t for t in trades if not t.open_at_end]
    returns = [t.return_pct for t in closed]

    longest_loss_streak = 0
    current = 0
    for r in returns:
        if r <= 0:
            current += 1
            longest_loss_streak = max(longest_loss_streak, current)
        else:
            current = 0

    worst = min(closed, key=lambda t: t.return_pct) if closed else None
    best = max(closed, key=lambda t: t.return_pct) if closed else None

    return {
        "closed_trades": len(closed),
        "open_trades_at_end": open_trades,
        "longest_consecutive_losing_streak": longest_loss_streak,
        "worst_trade_return_pct": worst.return_pct if worst else None,
        "worst_trade_dates": f"{worst.entry_date} -> {worst.exit_date}" if worst else None,
        "best_trade_return_pct": best.return_pct if best else None,
        "avg_loss_pct": float(np.mean([r for r in returns if r <= 0])) if any(r <= 0 for r in returns) else None,
        "avg_win_pct": float(np.mean([r for r in returns if r > 0])) if any(r > 0 for r in returns) else None,
        "max_drawdown_strategy": m.max_drawdown,
        "max_drawdown_buy_hold": bh.max_drawdown,
    }


def load_trend_ma_citation() -> dict | None:
    path = LAB / "data" / "trend_ma_primary.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    cells = {c["symbol"]: c for c in d["cells"] if c["idea"] == "regime_filter_standalone"}
    return {
        "source_file": "data/trend_ma_primary.json",
        "idea": "regime_filter_standalone",
        "family_size_their_ledger": d["family_size"],
        "cells": cells,
    }


def main() -> None:
    trend_ma_citation = load_trend_ma_citation()
    if trend_ma_citation is None:
        print("WARNING: data/trend_ma_primary.json not found -- run trend_ma.py first for the "
              "hit-rate citation. Continuing with descriptive-only output.")

    per_symbol = {}
    for symbol in PRIMARY:
        bars = bars_frame(symbol)
        state = regime_state(bars)
        tir = time_in_regime_and_transitions(state)
        dd = drawdown_avoided(bars, state)
        ls = loss_streak_and_worst_trade(bars)
        per_symbol[symbol] = {
            "time_in_regime": tir,
            "drawdown_avoided": dd,
            "loss_streak": ls,
            "trend_ma_citation": trend_ma_citation["cells"].get(symbol) if trend_ma_citation else None,
        }
        print(f"\n=== {symbol} ===")
        print(f"  favorable={tir['favorable_pct']:.1%} unfavorable={tir['unfavorable_pct']:.1%} "
              f"transitions={tir['transitions']} episodes={tir['n_episodes']} "
              f"(fav median len={tir['favorable_episode_median_len']}, "
              f"unfav median len={tir['unfavorable_episode_median_len']})")
        print(f"  BH total={dd['buy_hold_total_return']:.3f} BH maxDD={dd['buy_hold_max_drawdown']:.3f}  "
              f"favorable-days contribution={dd['favorable_days_contribution']:+.3f}  "
              f"unfavorable-days contribution={dd['unfavorable_days_contribution']:+.3f}")
        print(f"  frictionless favorable-only: total={dd['frictionless_favorable_only_total_return']:.3f} "
              f"maxDD={dd['frictionless_favorable_only_max_drawdown']:.3f}")
        print(f"  longest losing streak={ls['longest_consecutive_losing_streak']} trades, "
              f"worst trade={ls['worst_trade_return_pct']:.3f} ({ls['worst_trade_dates']}), "
              f"strategy maxDD={ls['max_drawdown_strategy']:.3f} vs BH maxDD={ls['max_drawdown_buy_hold']:.3f}")
        if trend_ma_citation:
            c = trend_ma_citation["cells"].get(symbol)
            print(f"  [cited] trend-ma regime_filter_standalone: edge={c['edge']:+.4f} "
                  f"n_indep={c['n_independent']} q={c['q_value']:.4f} verdict={c['verdict']}")

    result = {
        "sma_window": SMA_WINDOW,
        "note": "Descriptive only -- no p-values in this file. The one inferential number (hit-rate "
        "edge/q-value for close > sma(200)) is cited from trend-ma's own family, not re-derived here.",
        "trend_ma_citation": trend_ma_citation,
        "per_symbol": per_symbol,
    }
    write(result, "regime_risk_regime_value")
    print("\n=== regime_risk_regime_value.py complete ===")


if __name__ == "__main__":
    main()

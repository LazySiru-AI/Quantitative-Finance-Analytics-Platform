"""Corrected regime-window mechanics for every stream, replacing the ones `quantlab.slice_window`
produced.

**The defect, and it is the orchestrator's.** `quantlab.slice_window` hands the backtest engine a
bare slice of bars, so every indicator is recomputed from bar 0 *of the slice*. Its docstring called
this deliberate -- "a regime window must be a self-contained backtest, not a view onto indicators
seeded by data the window excludes" -- which sounds principled and is wrong in consequence. An
`sma(200)` rule inside a 253-bar 2022 window is blind for the first 200 of those bars: it is not
being tested on 2022, it is being tested on the last two months of 2022 with the rest thrown away.

The QA reviewer measured it rather than arguing it. SPY was genuinely below its 200-day SMA for
**84.9%** of 2022 (from Jan 21). The window-sliced recomputation only detects that from Oct 18
onward -- **19.5%** -- and 0.195 is exactly the `exposure` figure sitting in the stream JSON. In the
GFC window the same mechanism pins exposure at exactly 43.7% (155 of 355 bars) no matter what the
market actually did. Every regime table in this study inherited it, and so did the coordinator's own
"41 cells never traded" decomposition of the GFC backfill.

**The fix.** Seed the indicators, then measure only the window:

1. Run the backtest over `[first - WARMUP_BARS, last]`, so every indicator is fully warm by the time
   the window opens -- exactly as it would have been for someone actually trading that period, who
   did not have their moving averages deleted on New Year's Day.
2. Keep only the equity points inside `[first, last]`, and renormalise so the window opens at 1.0.
3. Keep only trades *entered* inside the window, so the trade count and win rate describe the window
   and not the run-up to it.
4. Recompute metrics from those, via the app's own `app.backtest.metrics.compute`.

A position opened during warmup and still held at window start is deliberately excluded from the
trade list but its mark-to-market still moves the equity curve -- which is correct, and is why
`exposure` here can exceed the fraction of trades that started inside the window.

**What this does and does not change.** No p-value, q-value, or verdict anywhere in the study moves:
regime windows are descriptive strategy mechanics, excluded from every correction family by design,
and the primary statistics were always computed on full unsliced history. What changes is every
regime narrative, and the GFC never-traded count in particular.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAB / "lib"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from quantlab import Idea, bars_frame  # noqa: E402

from app.backtest import metrics as metrics_mod  # noqa: E402
from app.backtest import strategy as strategy_mod  # noqa: E402
from app.backtest.models import BARS_PER_YEAR, Costs, StrategySpec  # noqa: E402
from app.db.duck import Interval  # noqa: E402

#: Long enough to warm every indicator any stream declared. The deepest is `sma(200)`/`ema(200)`;
#: an EMA is never formally "done" warming, so 400 bars is chosen to put the residual seed error far
#: below the price differences these rules compare, not because 400 is a magic number.
WARMUP_BARS = 400

PRIMARY = ["SPY", "QQQ", "IWM", "XLK", "XLV"]

WINDOWS = [
    ("dotcom_2000_2002", "2000-01-01", "2002-12-31"),
    ("bull_2003_2007", "2003-01-01", "2007-10-31"),
    ("gfc_2007_2009", "2007-11-01", "2009-03-31"),
    ("qe_bull_2009_2019", "2009-04-01", "2019-12-31"),
    ("covid_2020_2021", "2020-01-01", "2021-12-31"),
    ("bear_2022", "2022-01-01", "2022-12-31"),
    ("recent_2023_now", "2023-01-01", None),
]

IDEA_FIELDS = set(Idea.__dataclass_fields__)


def warm_slice(bars: pd.DataFrame, first: str, last: str | None) -> tuple[pd.DataFrame, int]:
    """Bars from `WARMUP_BARS` before `first` through `last`, plus the index where the window opens.

    Returns `(frame, window_start_index)`. If there is not enough history before `first` to warm up
    fully, the frame starts at bar 0 and the caller is told how many warmup bars it actually got, so
    a partially-warmed window is visible rather than silently equivalent to a fully-warmed one.
    """
    if last is not None:
        bars = bars[bars["ts"] <= pd.Timestamp(last, tz="UTC")]
    start_mask = bars["ts"] >= pd.Timestamp(first, tz="UTC")
    if not start_mask.any():
        return bars.iloc[0:0].reset_index(drop=True), 0
    first_pos = int(np.argmax(start_mask.to_numpy()))
    lead = max(0, first_pos - WARMUP_BARS)
    frame = bars.iloc[lead:].reset_index(drop=True)
    return frame, first_pos - lead


def run_window(bars: pd.DataFrame, idea: Idea, first: str, last: str | None) -> dict | None:
    if idea.exit is None and idea.max_holding_bars is None:
        return None
    frame, start = warm_slice(bars, first, last)
    window_len = len(frame) - start
    if window_len < 60:
        return {"skipped": f"only {window_len} bars inside the window"}

    spec = StrategySpec(
        entry=idea.entry,
        exit=idea.exit,
        max_holding_bars=idea.max_holding_bars,
        stop_loss_pct=idea.stop_loss_pct,
    )
    costs = Costs()
    m, bh, trades, equity, cost_drag, _ = strategy_mod.backtest(
        frame, spec, interval=Interval.DAY, costs=costs
    )

    eq = np.array([p.equity for p in equity], dtype=float)[start:]
    bh_eq = np.array([p.buy_hold for p in equity], dtype=float)[start:]
    in_pos = np.array([p.in_position for p in equity], dtype=bool)[start:]
    if eq.size == 0 or eq[0] == 0 or bh_eq[0] == 0:
        return {"skipped": "degenerate equity at window open"}
    eq = eq / eq[0]
    bh_eq = bh_eq / bh_eq[0]

    window_first_date = frame["ts"].iloc[start].date()
    in_window = [t for t in trades if t.entry_date >= window_first_date]
    carried_in = len(trades) - len([t for t in trades if t.entry_date < window_first_date]) != len(trades)

    bars_per_year = BARS_PER_YEAR[Interval.DAY]
    wm = metrics_mod.compute(
        eq, in_position=in_pos, trades=in_window, bars_per_year=bars_per_year, risk_free_rate=0.0
    )
    wbh = metrics_mod.compute(
        bh_eq,
        in_position=np.ones(bh_eq.size, dtype=bool),
        trades=[],
        bars_per_year=bars_per_year,
        risk_free_rate=0.0,
    )
    closed = [t for t in in_window if not t.open_at_end]
    return {
        "warmup_bars_available": start,
        "fully_warmed": start >= WARMUP_BARS,
        "window_bars": int(eq.size),
        "strategy": {
            "total_return": wm.total_return,
            "cagr": wm.cagr,
            "sharpe": wm.sharpe,
            "max_drawdown": wm.max_drawdown,
            "exposure": wm.exposure,
            "trades": wm.trades,
            "win_rate": wm.win_rate,
        },
        "buy_hold": {
            "total_return": wbh.total_return,
            "cagr": wbh.cagr,
            "sharpe": wbh.sharpe,
            "max_drawdown": wbh.max_drawdown,
        },
        "trades_entered_in_window": len(in_window),
        "closed_trades_in_window": len(closed),
        "position_carried_into_window": carried_in,
        "cost_drag_full_frame": cost_drag,
        "beats_buy_hold_total_return": (
            None
            if wm.total_return is None or wbh.total_return is None
            else wm.total_return > wbh.total_return
        ),
        "never_traded": len(in_window) == 0,
    }


def main() -> None:
    bars_by_symbol = {s: bars_frame(s) for s in PRIMARY}
    out: dict = {}

    for path in sorted((LAB / "data").glob("*_primary.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        stream = payload.get("family", path.stem)
        declared = payload.get("ideas_declared", [])
        print(f"\n=== {stream}: {len(declared)} ideas x {len(PRIMARY)} symbols x {len(WINDOWS)} windows")
        stream_out: dict = {}
        for raw in declared:
            idea = Idea(**{k: v for k, v in raw.items() if k in IDEA_FIELDS})
            per_window: dict = {}
            for label, first, last in WINDOWS:
                per_symbol = {}
                for symbol in PRIMARY:
                    try:
                        r = run_window(bars_by_symbol[symbol], idea, first, last)
                    except Exception as exc:
                        r = {"error": f"{type(exc).__name__}: {exc}"}
                    per_symbol[symbol] = r if r is not None else {"skipped": "no exit and no cap"}
                per_window[label] = per_symbol
            stream_out[idea.key] = per_window
        out[stream] = stream_out

    # The comparison that motivated this script: never-traded counts, corrected vs the old slice.
    print("\n--- never-traded cells per window, with warmup seeded ---")
    totals: dict[str, list[int]] = {}
    for label, _, _ in WINDOWS:
        never = total = 0
        for stream, ideas in out.items():
            for key, windows in ideas.items():
                for symbol, r in windows[label].items():
                    if not isinstance(r, dict) or "strategy" not in r:
                        continue
                    total += 1
                    if r["never_traded"]:
                        never += 1
        totals[label] = [never, total]
        print(f"  {label:<20} never_traded={never:<4} of {total}")

    gfc = totals.get("gfc_2007_2009")
    if gfc:
        print(
            f"\nGFC window: {gfc[0]} of {gfc[1]} cells never traded once indicators are seeded "
            f"(the uncorrected slice reported 41 of 150)."
        )

    payload = {
        "warmup_bars": WARMUP_BARS,
        "windows": [{"label": w[0], "first": w[1], "last": w[2]} for w in WINDOWS],
        "symbols": PRIMARY,
        "never_traded_by_window": totals,
        "note": (
            "Descriptive strategy mechanics only -- no p-values. Supersedes the `windows` block in "
            "every *_primary.json and data/gfc_backfill.json, which were produced by "
            "quantlab.slice_window without indicator warmup. No statistical result in this study "
            "depends on either version."
        ),
        "streams": out,
    }
    path = LAB / "data" / "regime_windows_corrected.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()

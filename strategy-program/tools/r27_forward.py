"""Round 27 section 2c: `C-trend`'s stated reason for excluding five names, measured directly.

The thesis says: "the same golden-cross setup on this universe's smaller, more speculative names
(IREN, OKLO, APLD, BE, KORU) produced negative average 60-day forward returns after the signal
fired -- those names were excluded from the universe below specifically because the measured data
showed the entries do not sustain here, not because of a prior."

`strategy-program/ROUND-27-PLAN.md` section 2c pins the definition this tool executes, unchanged:

* A **signal** is a session where `close > sma(200)` AND `ema(20)` crosses above `ema(50)` (crosses
  = was `<=` on the prior session and is `>` on this one). This is `C-trend`'s own entry rule --
  not a re-derivation of it.
* The **forward return** is `close[t+60] / close[t] - 1`, where `t+60` is 60 *sessions* later, not
  60 calendar days. A signal within 60 bars of the end of a name's history has no forward return to
  measure; it is dropped and counted rather than silently omitted.

Measured on the five excluded names, **and on `C-trend`'s nine included names as a control**
(`NVDA AVGO TSM ORCL SOXX NFLX MU META QCOM`). "These names do not sustain the signal *here*" is a
comparative claim about this universe, not an absolute one about the five names in isolation -- a
bare negative mean on five names, with no measurement of how the kept names behave under the same
signal and the same arithmetic, would not establish it. Both groups are therefore measured
identically: same indicator calls, same crossing test, same 60-session horizon, same drop rule.

The five excluded names are recent listings (see each name's first-bar date in the output and in
the written JSON), so their signal counts are small relative to the nine-name control's longer
history; that asymmetry is reported, not smoothed over.

This tool draws no conclusion about whether the exclusion was justified. It reports the arithmetic
the thesis's own sentence is answerable by, nothing more.

    PYTHONIOENCODING=utf-8 PYTHONPATH="backend;." ./.venv/Scripts/python.exe strategy-program/tools/r27_forward.py

**Not investment advice.**
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import duckdb
import pandas as pd

from app.indicators.registry import compute, request

REPO = Path(__file__).resolve().parents[2]

OUT = REPO / "data" / "rounds" / "r27-2026-08"

#: Plan section 2c: the five names `C-trend`'s thesis says were excluded because the measured data
#: showed the entries do not sustain here.
EXCLUDED = ["IREN", "OKLO", "APLD", "BE", "KORU"]

#: Plan section 2c's control: `C-trend`'s nine included names, run through the identical
#: measurement so the excluded group's figures have something to be compared against.
INCLUDED = ["NVDA", "AVGO", "TSM", "ORCL", "SOXX", "NFLX", "MU", "META", "QCOM"]

#: Sessions, not calendar days -- plan section 2c is explicit that this is a bar-count horizon.
HORIZON = 60

BARS_TEMPLATE = "data/store/bars/interval=1d/symbol={symbol}/bars.parquet"


def load_bars(symbol: str) -> pd.DataFrame:
    """One symbol's full daily history, exactly the pattern the plan's brief pins."""
    con = duckdb.connect(":memory:")
    path = (REPO / BARS_TEMPLATE.format(symbol=symbol)).as_posix()
    return con.execute(
        f"select ts, open, high, low, close, volume from read_parquet('{path}') order by ts"
    ).df().set_index("ts")


def signal_forward_returns(symbol: str) -> tuple[list[float], int, pd.Timestamp]:
    """`C-trend`'s entry signal on `symbol`'s full history, each fired signal's forward return.

    Returns ``(returns, dropped_count, first_bar_date)``. A signal is a session where
    ``close > sma(200)`` and ``ema(20)`` crosses above ``ema(50)`` -- was ``<=`` the prior session,
    is ``>`` this one. Signals with fewer than `HORIZON` subsequent bars are dropped and counted
    rather than omitted silently, per plan section 2c.
    """
    bars = load_bars(symbol)
    first_bar_date = bars.index[0]

    # The registry, not a hand-rolled EMA/SMA -- so this reads the same numbers the card's own
    # entry rule reads, not a re-derivation that could quietly diverge from it.
    ind = compute(bars, [request("sma:200"), request("ema:20"), request("ema:50")])
    joined = bars.join(ind)

    sma_col = next(c for c in ind.columns if c.startswith("sma_200"))
    ema20_col = next(c for c in ind.columns if c.startswith("ema_20") and "ema_200" not in c)
    ema50_col = next(c for c in ind.columns if c.startswith("ema_50"))

    above_trend = joined["close"] > joined[sma_col]
    ema20, ema50 = joined[ema20_col], joined[ema50_col]
    crossed_up = (ema20.shift(1) <= ema50.shift(1)) & (ema20 > ema50)

    signal_mask = (above_trend & crossed_up).fillna(False)
    signal_positions = [i for i, fired in enumerate(signal_mask) if fired]

    close = joined["close"].to_numpy()
    n = len(close)
    returns: list[float] = []
    dropped = 0
    for i in signal_positions:
        j = i + HORIZON
        if j >= n:
            dropped += 1
            continue
        returns.append(close[j] / close[i] - 1)

    return returns, dropped, first_bar_date


def summarize(symbols: list[str]) -> dict[str, dict]:
    """Per-name mean/median/count/dropped/first-bar-date, for one group of symbols."""
    out: dict[str, dict] = {}
    for sym in symbols:
        returns, dropped, first_bar = signal_forward_returns(sym)
        out[sym] = {
            "first_bar_date": str(first_bar.date()),
            "signal_count": len(returns),
            "dropped_count": dropped,
            "mean_forward_return_pct": statistics.fmean(returns) * 100 if returns else None,
            "median_forward_return_pct": statistics.median(returns) * 100 if returns else None,
            "_returns": returns,  # pooled below, stripped before writing per-name output
        }
    return out


def pooled(group: dict[str, dict]) -> dict:
    """The group's pooled mean/median: every usable signal from every name, one distribution.

    Pooled, not an average of per-name means -- so a name with many signals is not weighted the
    same as a name with one, which an average-of-means would do.
    """
    all_returns = [r for name in group.values() for r in name["_returns"]]
    return {
        "signal_count": len(all_returns),
        "mean_forward_return_pct": statistics.fmean(all_returns) * 100 if all_returns else None,
        "median_forward_return_pct": statistics.median(all_returns) * 100 if all_returns else None,
    }


def print_table(title: str, group: dict[str, dict]) -> None:
    print(f"\n{title}")
    print(f"  {'symbol':8s} {'first bar':11s} {'signals':>8s} {'dropped':>8s} {'mean %':>10s} {'median %':>10s}")
    for sym, row in group.items():
        mean_s = f"{row['mean_forward_return_pct']:+.2f}" if row["mean_forward_return_pct"] is not None else "n/a"
        med_s = f"{row['median_forward_return_pct']:+.2f}" if row["median_forward_return_pct"] is not None else "n/a"
        print(
            f"  {sym:8s} {row['first_bar_date']:11s} {row['signal_count']:8d} {row['dropped_count']:8d} "
            f"{mean_s:>10s} {med_s:>10s}"
        )


def main() -> int:
    print(f"signal: close > sma(200) and ema(20) crosses above ema(50)  |  horizon: {HORIZON} sessions")

    excluded = summarize(EXCLUDED)
    included = summarize(INCLUDED)

    print_table("EXCLUDED (C-trend's five, per name)", excluded)
    print_table("INCLUDED (C-trend's nine, control, per name)", included)

    excluded_pooled = pooled(excluded)
    included_pooled = pooled(included)

    print("\nPOOLED")
    for label, p in (("excluded (5)", excluded_pooled), ("included (9, control)", included_pooled)):
        mean_s = f"{p['mean_forward_return_pct']:+.2f}" if p["mean_forward_return_pct"] is not None else "n/a"
        med_s = f"{p['median_forward_return_pct']:+.2f}" if p["median_forward_return_pct"] is not None else "n/a"
        print(f"  {label:24s} signals={p['signal_count']:4d}  mean={mean_s:>8s}%  median={med_s:>8s}%")

    if excluded_pooled["mean_forward_return_pct"] is not None and included_pooled["mean_forward_return_pct"] is not None:
        gap = included_pooled["mean_forward_return_pct"] - excluded_pooled["mean_forward_return_pct"]
        print(f"\n  gap (included mean - excluded mean): {gap:+.2f}pp")

    # Strip the pooled-only `_returns` field before writing per-name output -- it exists to feed
    # `pooled()`, not as a reported figure.
    def _public(group: dict[str, dict]) -> dict[str, dict]:
        return {sym: {k: v for k, v in row.items() if k != "_returns"} for sym, row in group.items()}

    payload = {
        "signal_definition": "close > sma(200) and ema(20) crosses above ema(50)",
        "horizon_sessions": HORIZON,
        "excluded": {"names": _public(excluded), "pooled": excluded_pooled},
        "included_control": {"names": _public(included), "pooled": included_pooled},
    }

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "forward.json"
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {out_path.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

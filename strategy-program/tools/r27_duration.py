"""Round 27, section 2b: how long does the move actually last after a momentum entry fires.

    PYTHONIOENCODING=utf-8 PYTHONPATH="backend;." ./.venv/Scripts/python.exe strategy-program/tools/r27_duration.py

`ROUND-27-PLAN.md` section 2b is the pre-registration this executes. Read it first.

`B3-concentrated` and `B-momentum` share a byte-identical thesis: once ``close > sma(200)`` is
already established and ``ema(20)`` crosses above ``ema(50)``, "the resulting move has a median
duration of roughly 3-4 weeks and stretches past two months at the 75th percentile (NVDA's longest
such run reached 256 sessions, MSFT's 169, TSM's 189)." This measures that statistic directly, on
the twelve names of the shared universe, using the cards' own entry and `C-trend`'s own exit -- not
a backtest of either card, a re-measurement of the sentence itself.

**Definitions, pinned by the plan and not varied here:**

* A **signal** is a session where ``close > sma(200)`` AND ``ema(20)`` crosses above ``ema(50)`` --
  "crosses" means the prior session had ``ema(20) <= ema(50)`` and this one has ``ema(20) >
  ema(50)``. Both conditions must hold on the *same* session; a close that rises above sma(200) a
  few sessions after the cross, with no new cross, is not a second signal.
* The **move** runs from the signal session to the first later session where ``ema(20)`` crosses
  back below ``ema(50)`` (the mirror-image event). Duration is the number of **sessions** between
  the two, not calendar days.
* A move with no such later session -- still open at the last available bar -- is **censored**.
  It is counted and reported, but **excluded from the median and 75th percentile**, not truncated
  to the last bar. Truncating would silently convert an open, currently-winning move into a short
  one and drag the statistic down exactly where the thesis's claim is strongest (its longest named
  runs are precisely the kind of move likeliest to still be open); excluding it is the only way to
  measure "duration of a *completed* move" without smuggling in that bias.

Because moves are defined by consecutive cross-above / cross-below pairs, they cannot overlap: the
next cross-above cannot fire until the current move has ended (`ema(20)` has to be back at or below
`ema(50)` for a new "crosses above" event to exist at all). No dedup logic is needed for that reason.

The plan also asks for the same statistics restricted to signals firing after `DESIGN_THROUGH`
(2026-02-13), reported separately. That split is explicitly **not an out-of-sample test** (plan
section 4) -- six months of history yields few completed moves per name, and no verdict is drawn
from it alone; it is reported for completeness and labeled small-sample.

**Not investment advice.**
"""

from __future__ import annotations

import bisect
import datetime as dt
import json
import pathlib

import duckdb
import numpy as np
import pandas as pd

from app.indicators.registry import compute, request

REPO = pathlib.Path(__file__).resolve().parents[2]

OUT = REPO / "data" / "rounds" / "r27-2026-08"

#: Plan section 2b. The twelve names of the shared universe.
TICKERS = ["NVDA", "AMD", "AVGO", "MU", "MRVL", "TSM", "META", "MSFT", "GOOGL", "NOW", "AMZN", "NFLX"]

#: Plan section 2b / section 4. The cutoff the thesis's own design-window history predates.
DESIGN_THROUGH = dt.date(2026, 2, 13)

#: Plan section 2b's reference points, computed once from the claim's own words so the read of the
#: measured figures against them is arithmetic, not a judgment call.
REFERENCE_SESSIONS = {
    "three_to_four_weeks_low": 15,
    "three_to_four_weeks_high": 20,
    "past_two_months_min": 42,
}

#: The thesis's own named maxima, quoted verbatim in the plan, for the per-name comparison table.
THESIS_NAMED_MAX = {"NVDA": 256, "MSFT": 169, "TSM": 189}


def load_bars(symbol: str) -> pd.DataFrame:
    """OHLCV bars for `symbol`, oldest first, indexed by session timestamp."""
    con = duckdb.connect(":memory:")
    path = f"data/store/bars/interval=1d/symbol={symbol}/bars.parquet"
    return (
        con.execute(f"select ts, open, high, low, close, volume from read_parquet('{path}') order by ts")
        .df()
        .set_index("ts")
    )


def signal_and_exit_masks(joined: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Boolean masks over `joined`'s full index: entry signal, and the mirror-image exit cross.

    Computed over the *whole* series, sma(200)'s warmup included, rather than trimming leading NaN
    rows first: the ``close > sma(200)`` comparison is already False/NaN-safe through warmup (NaN
    compares False), so a warmup-era cross-up simply never qualifies as a signal, and no row needs
    to be dropped to get that for free.
    """
    ema20, ema50 = joined["ema_20"], joined["ema_50"]
    prev20, prev50 = ema20.shift(1), ema50.shift(1)
    cross_up = (prev20 <= prev50) & (ema20 > ema50)
    cross_down = (prev20 > prev50) & (ema20 <= ema50)
    signal = cross_up & (joined["close"] > joined["sma_200"])
    return signal.fillna(False), cross_down.fillna(False)


def moves_for_symbol(symbol: str) -> list[dict]:
    """One record per signal fired by `symbol`: its date, duration in sessions, and censor flag."""
    df = load_bars(symbol)
    ind = compute(df, [request("sma:200"), request("ema:20"), request("ema:50")])
    joined = df.join(ind)

    signal, cross_down = signal_and_exit_masks(joined)
    down_positions = [i for i, v in enumerate(cross_down.to_numpy()) if v]
    last_pos = len(joined) - 1

    records = []
    for i, is_signal in enumerate(signal.to_numpy()):
        if not is_signal:
            continue
        # First cross-down strictly after the signal session (bisect_right(i) skips i itself, which
        # cannot be a cross-down anyway since it is a cross-up).
        k = bisect.bisect_right(down_positions, i)
        censored = k >= len(down_positions)
        exit_pos = last_pos if censored else down_positions[k]
        records.append(
            {
                "symbol": symbol,
                "signal_date": joined.index[i].date().isoformat(),
                "duration_sessions": exit_pos - i,
                "censored": censored,
            }
        )
    return records


def summarize(records: list[dict]) -> dict:
    """Pooled median / 75th percentile / completed / censored counts for one set of move records.

    Percentiles are computed over completed moves only -- see the module docstring for why a
    censored move is excluded rather than truncated to its still-running duration.
    """
    completed = [r["duration_sessions"] for r in records if not r["censored"]]
    n_censored = sum(1 for r in records if r["censored"])
    return {
        "n_signals": len(records),
        "n_completed": len(completed),
        "n_censored": n_censored,
        "median_sessions": float(np.median(completed)) if completed else None,
        "p75_sessions": float(np.percentile(completed, 75)) if completed else None,
    }


def per_name_summary(records_by_symbol: dict[str, list[dict]]) -> dict[str, dict]:
    """Per-symbol signal/completed/censored counts and the maximum *completed* duration."""
    out = {}
    for symbol, recs in records_by_symbol.items():
        completed = [r["duration_sessions"] for r in recs if not r["censored"]]
        n_censored = sum(1 for r in recs if r["censored"])
        out[symbol] = {
            "n_signals": len(recs),
            "n_completed": len(completed),
            "n_censored": n_censored,
            "max_completed_sessions": max(completed) if completed else None,
            "median_completed_sessions": float(np.median(completed)) if completed else None,
            "thesis_named_max": THESIS_NAMED_MAX.get(symbol),
        }
    return out


def print_summary_block(title: str, stats: dict) -> None:
    print(f"\n{title}")
    median = "n/a" if stats["median_sessions"] is None else f"{stats['median_sessions']:.1f}"
    p75 = "n/a" if stats["p75_sessions"] is None else f"{stats['p75_sessions']:.1f}"
    print(
        f"  n_signals {stats['n_signals']:4d}   n_completed {stats['n_completed']:4d}   "
        f"n_censored {stats['n_censored']:3d}   median {median:>6s}   p75 {p75:>6s}"
    )


def print_per_name_table(title: str, per_name: dict[str, dict]) -> None:
    print(f"\n{title}")
    print(f"  {'symbol':7s} {'signals':>7s} {'complete':>8s} {'censored':>8s} {'max':>6s} {'median':>7s} {'thesis_max':>10s}")
    for symbol in TICKERS:
        s = per_name.get(symbol)
        if s is None:
            continue
        max_s = "n/a" if s["max_completed_sessions"] is None else str(s["max_completed_sessions"])
        med_s = "n/a" if s["median_completed_sessions"] is None else f"{s['median_completed_sessions']:.1f}"
        thesis = "" if s["thesis_named_max"] is None else str(s["thesis_named_max"])
        print(
            f"  {symbol:7s} {s['n_signals']:7d} {s['n_completed']:8d} {s['n_censored']:8d} "
            f"{max_s:>6s} {med_s:>7s} {thesis:>10s}"
        )


def main() -> int:
    print(f"Round 27 section 2b: move duration after the momentum entry, {len(TICKERS)} names")
    print(f"tickers: {' '.join(TICKERS)}")
    print(f"DESIGN_THROUGH: {DESIGN_THROUGH.isoformat()} (post-cutoff split is small-sample, not out-of-sample -- plan section 4)")

    records_by_symbol: dict[str, list[dict]] = {}
    for symbol in TICKERS:
        records_by_symbol[symbol] = moves_for_symbol(symbol)

    all_records = [r for recs in records_by_symbol.values() for r in recs]
    post_cutoff_by_symbol = {
        symbol: [r for r in recs if dt.date.fromisoformat(r["signal_date"]) > DESIGN_THROUGH]
        for symbol, recs in records_by_symbol.items()
    }
    post_cutoff_records = [r for recs in post_cutoff_by_symbol.values() for r in recs]

    pooled = summarize(all_records)
    pooled_post_cutoff = summarize(post_cutoff_records)
    per_name = per_name_summary(records_by_symbol)
    per_name_post_cutoff = per_name_summary(post_cutoff_by_symbol)

    print_summary_block("pooled, full available history", pooled)
    print(
        f"  reference: 3-4 weeks = {REFERENCE_SESSIONS['three_to_four_weeks_low']}-"
        f"{REFERENCE_SESSIONS['three_to_four_weeks_high']} sessions; "
        f"past two months = >={REFERENCE_SESSIONS['past_two_months_min']} sessions"
    )
    print_per_name_table("per-name, full available history (thesis_max is NVDA/MSFT/TSM's named figure)", per_name)

    print_summary_block(
        f"pooled, signals after {DESIGN_THROUGH.isoformat()} only -- SMALL SAMPLE, not an out-of-sample test",
        pooled_post_cutoff,
    )
    print_per_name_table(f"per-name, signals after {DESIGN_THROUGH.isoformat()} only -- SMALL SAMPLE", per_name_post_cutoff)

    payload = {
        "claim": (
            "once close > sma(200) is already established and ema(20) crosses above ema(50) ... the "
            "resulting move has a median duration of roughly 3-4 weeks and stretches past two months "
            "at the 75th percentile (NVDA's longest such run reached 256 sessions, MSFT's 169, TSM's "
            "189)."
        ),
        "source": "strategy-program/ROUND-27-PLAN.md section 2b",
        "tickers": TICKERS,
        "design_through": DESIGN_THROUGH.isoformat(),
        "reference_points_sessions": REFERENCE_SESSIONS,
        "thesis_named_max": THESIS_NAMED_MAX,
        "pooled": pooled,
        "pooled_post_design_through": {
            "note": "small-sample split, not an out-of-sample test -- plan section 4",
            **pooled_post_cutoff,
        },
        "per_name": per_name,
        "per_name_post_design_through": per_name_post_cutoff,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "duration.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {(OUT / 'duration.json').relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Round 27 -- `A-rotation`'s pairwise correlation claim, measured directly.

`A-rotation`'s thesis states:

    "I measured pairwise daily-return correlation across these 9 names over the trailing ~253
    sessions through 2026-02-13: mean 0.589, range 0.286 (INTC vs AVGO) to 0.824 (SOXX vs TSM)."

This is not a backtest. It is the same statistic the thesis cites -- Pearson correlation of daily
simple returns (`close.pct_change()`), computed pairwise across the nine names
(`MU INTC AMD TSM SOXX NVDA AVGO QCOM MRVL`, 36 pairs), on sessions where both names of the pair have
bars -- measured across `R2_MATRIX`'s eight fixed windows instead of the thesis's single trailing
year. Definition pinned in `strategy-program/ROUND-27-PLAN.md` section 2a; nothing here varies it.

A pair with fewer than 20 overlapping sessions in a window is skipped rather than forced through a
near-empty sample; every skip is counted and reported, not silently dropped.

    PYTHONIOENCODING=utf-8 PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/r27_correlation.py

**Not investment advice.**
"""

from __future__ import annotations

import itertools
import json
import pathlib
import statistics

import duckdb
import pandas as pd

REPO = pathlib.Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "rounds" / "r27-2026-08"

#: `A-rotation`'s nine names, plan section 2a. Order fixed here so `itertools.combinations` produces
#: a stable, reproducible pairing.
TICKERS = ["MU", "INTC", "AMD", "TSM", "SOXX", "NVDA", "AVGO", "QCOM", "MRVL"]
PAIRS = list(itertools.combinations(TICKERS, 2))  # 9 choose 2 = 36, per plan section 2a

#: The eight `R2_MATRIX` regime windows, duplicated here rather than imported -- same reasoning as
#: `score.py`'s own copy of them: the tools/ tree is not an importable package, so a shared import
#: would trade eight literal strings for a sys.path hack.
WINDOWS = [
    ("q4-2018", "2018-09-21", "2018-12-24"),
    ("covid", "2020-02-19", "2020-06-30"),
    ("bear-2022", "2022-01-03", "2022-10-12"),
    ("chop-2015", "2015-04-07", "2016-04-15"),
    ("chop-2011", "2011-05-26", "2012-06-06"),
    ("bull-2024", "2024-08-21", "2025-08-20"),
    ("recent", "2025-08-21", "2026-08-18"),
    ("gfc", "2007-10-09", "2009-03-09"),
]

#: Plan section 2a: "skip pairs where either name has fewer than 20 overlapping sessions". Below this
#: a Pearson r is noise, not a measurement.
MIN_OVERLAP = 20

#: Plan-facing figures, quoted in the docstring above, kept as constants so the comparison at the end
#: of the run is arithmetic against a named value rather than a number retyped from memory.
THESIS_MEAN = 0.589
THESIS_MIN, THESIS_MIN_PAIR = 0.286, "INTC-AVGO"
THESIS_MAX, THESIS_MAX_PAIR = 0.824, "SOXX-TSM"

BAR_PATH = REPO / "data" / "store" / "bars" / "interval=1d" / "symbol={sym}" / "bars.parquet"


def load_closes() -> dict[str, pd.Series]:
    """Daily close, indexed by `ts`, one series per ticker -- the reading pattern this round was
    briefed with. A fresh in-memory connection avoids sharing DuckDB state across the nine reads."""
    con = duckdb.connect(":memory:")
    closes: dict[str, pd.Series] = {}
    for sym in TICKERS:
        path = str(BAR_PATH).format(sym=sym).replace("\\", "/")
        df = con.execute(f"select ts, close from read_parquet('{path}') order by ts").df()
        closes[sym] = df.set_index("ts")["close"]
    return closes


def pair_stat(
    returns: dict[str, pd.Series], a: str, b: str, start: str, end: str
) -> tuple[int, float | None]:
    """Overlapping session count and Pearson r for one pair within one window.

    `.loc[start:end]` is inclusive on both ends (pandas partial-string indexing on a DatetimeIndex),
    matching the windows' own inclusive start/end. `dropna()` after the inner concat is what makes
    this "sessions where both names have bars" rather than "sessions where either does" -- a NaN
    return (the very first bar of a series, or a missing bar) drops that row from the pair entirely.
    """
    joined = pd.concat(
        [returns[a].loc[start:end].rename("a"), returns[b].loc[start:end].rename("b")],
        axis=1,
        join="inner",
    ).dropna()
    n = len(joined)
    if n < MIN_OVERLAP:
        return n, None
    return n, float(joined["a"].corr(joined["b"]))


def window_result(
    closes: dict[str, pd.Series], returns: dict[str, pd.Series], tag: str, start: str, end: str
) -> dict:
    """All 36 pairwise correlations for one window, plus the window's own session calendar.

    `sessions` is the union of trading dates across all nine names within the window -- the size of
    the calendar a fully-covered pair would overlap on -- not a per-pair figure, since the 36 pairs
    do not all share the same overlap count once a name is missing part of the window.
    """
    calendar: pd.DatetimeIndex = pd.DatetimeIndex([])
    for sym in TICKERS:
        calendar = calendar.union(closes[sym].loc[start:end].index)

    rows = []
    for a, b in PAIRS:
        n, corr = pair_stat(returns, a, b, start, end)
        rows.append({"pair": f"{a}-{b}", "sessions": n, "corr": corr, "used": corr is not None})

    used = [r for r in rows if r["used"]]
    if used:
        corrs = [r["corr"] for r in used]
        lo = min(used, key=lambda r: r["corr"])
        hi = max(used, key=lambda r: r["corr"])
        mean_c, min_c, max_c = statistics.fmean(corrs), lo["corr"], hi["corr"]
        min_pair, max_pair = lo["pair"], hi["pair"]
    else:
        mean_c = min_c = max_c = None
        min_pair = max_pair = None

    return {
        "start": start,
        "end": end,
        "sessions": len(calendar),
        "pairs_total": len(PAIRS),
        "pairs_used": len(used),
        "mean": mean_c,
        "min": min_c,
        "min_pair": min_pair,
        "max": max_c,
        "max_pair": max_pair,
        "pairs": rows,
    }


def render_table(results: dict[str, dict]) -> None:
    print(f"{'window':10s} {'dates':23s} {'sessions':>8s} {'used':>6s} "
          f"{'mean':>7s} {'min':>7s} {'min pair':12s} {'max':>7s} {'max pair':12s}")
    for tag, r in results.items():
        dates = f"{r['start']} -> {r['end']}"
        if r["mean"] is None:
            print(f"{tag:10s} {dates:23s} {r['sessions']:8d} {r['pairs_used']:>3d}/{r['pairs_total']:<2d}"
                  f"  {'--':>7s} {'--':>7s} {'--':12s} {'--':>7s} {'--':12s}")
            continue
        print(
            f"{tag:10s} {dates:23s} {r['sessions']:8d} {r['pairs_used']:>3d}/{r['pairs_total']:<2d}"
            f"  {r['mean']:7.3f} {r['min']:7.3f} {r['min_pair']:12s}"
            f" {r['max']:7.3f} {r['max_pair']:12s}"
        )
    print()

    for tag, r in results.items():
        skipped = [p for p in r["pairs"] if not p["used"]]
        if skipped:
            names = ", ".join(f"{p['pair']} (n={p['sessions']})" for p in skipped)
            print(f"{tag}: {len(skipped)}/{r['pairs_total']} pairs skipped (n < {MIN_OVERLAP}): {names}")
    print()


def render_thesis_comparison(results: dict[str, dict]) -> None:
    print(f"thesis claim: mean {THESIS_MEAN:.3f}, range {THESIS_MIN:.3f} ({THESIS_MIN_PAIR}) "
          f"to {THESIS_MAX:.3f} ({THESIS_MAX_PAIR})")
    print("(higher/lower stated as measured-minus-thesis; no verdict drawn here)\n")
    for tag, r in results.items():
        if r["mean"] is None:
            print(f"  {tag:10s} no usable pairs in this window")
            continue
        d_mean = r["mean"] - THESIS_MEAN
        d_min = r["min"] - THESIS_MIN
        d_max = r["max"] - THESIS_MAX
        print(
            f"  {tag:10s} mean {r['mean']:7.3f} ({d_mean:+.3f})   "
            f"min {r['min']:7.3f} ({d_min:+.3f})   max {r['max']:7.3f} ({d_max:+.3f})"
        )


def main() -> int:
    closes = load_closes()
    returns = {sym: s.pct_change() for sym, s in closes.items()}

    results: dict[str, dict] = {}
    for tag, start, end in WINDOWS:
        results[tag] = window_result(closes, returns, tag, start, end)

    render_table(results)
    render_thesis_comparison(results)

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "correlation.json"
    out_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {out_path.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

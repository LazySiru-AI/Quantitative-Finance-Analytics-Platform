"""regime-risk stream: seasonality (note p.10, verbatim: "Year round historical stock movement trend
analysis -- March-April Bull and May-October Bear").

Not expressible in the rule DSL -- BRIEF.md section 4 lists no date/month operator. Tested directly
against the bars frame in pandas, per BRIEF.md's explicit instruction for this stream. This module
reuses the app's own statistical primitives (`app.backtest.scan.binomial_p_value`,
`app.backtest.scan.benjamini_hochberg`) for every p-value and correction -- see quantlab.py's
docstring: "this module adds no statistics of its own." What pandas *does* do here, because the app
has no calendar-bucket construct, is build the return samples themselves.

**Method.** For each symbol, resample daily bars to the last available close of each calendar month
(`resample("ME").last()`, which lands on the last real trading day of the month, not a fixed
calendar date -- robust to holidays and weekends the same way the app's own `_nearest_on_or_before`
is). A calendar-month return is `month_close / prior_month_close - 1`; a composite N-month bucket's
return is `bucket_end_close / bucket_start_close - 1`, using the same monthly close series. Every
occurrence (one per year) is *inherently* non-overlapping -- a March-April return in 2019 shares no
trading days with the same bucket in 2020 -- so `n_independent` here is literally the number of years
of coverage, not a windowing computation; this is the "~30 observations, not 630 days" point BRIEF.md
warns about, made concrete.

**Two baselines, matched by construction, not by horizon length.** A single calendar month is
compared against the pooled hit rate of *all twelve* calendar months for that symbol (the literal
"all-months baseline"). A composite N-month bucket (N=2 or N=6) is compared against the pooled hit
rate of *all possible* overlapping N-month rolling windows for that symbol (every one of the twelve
possible start months, computed via `pct_change(N)` on the monthly close series) -- because comparing
a 6-month bucket's hit rate against a 1-month baseline would confound "is this specific 6 months
special" with "6-month holding periods are usually positive regardless of timing", and those are
different questions. The rolling baseline does not need independence -- it is the null the arm is
tested against, not itself a claim with a sample-size floor.

**The declared family, stated before any result is read**: 12 individual calendar months + 3
composite buckets (Mar-Apr, the note's literal bull claim; May-Oct, the note's literal bear claim,
which is also the classic "Sell in May" bear leg; Nov-Apr, the classic "Best Six Months" complement,
included specifically to answer BRIEF.md's "does Sell-in-May show up in this universe at all")
= 15 buckets x 5 primary symbols = 75 tests, one Benjamini-Hochberg ledger.

**Direction is only checked for the 3 composite claims**, which are genuine pre-registered directional
hypotheses from the note (Mar-Apr up, May-Oct down) or from well-known market folklore stated in
BRIEF.md (Nov-Apr up). The 12 individual months carry no directional prior from the note or from this
script -- they are reported as plain two-sided discoveries (q <= 0.10) or non-discoveries, the same
epistemic status `horizon_sweep` gives an exploratory table, and the report will not read "the best
month" off this list as if it were the finding; it explicitly is not.

Run from docs/research/strategy-lab/:
    ../../../.venv/Scripts/python.exe scripts/regime_risk_seasonality.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, "lib")

import pandas as pd  # noqa: E402
from quantlab import bars_frame, write  # noqa: E402

from app.backtest import scan as scan_mod  # noqa: E402

PRIMARY = ["SPY", "QQQ", "IWM", "XLK", "XLV"]

MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

# Composite buckets: (key, start_month(1-12) EXCLUSIVE anchor .. described below, end_month,
# length_in_months, direction, note_source). A bucket is defined by (anchor_month_before_start,
# end_month): the return runs from the close at the end of `anchor_month_before_start` to the close
# at the end of `end_month`. Declared before anything is run.
COMPOSITE_BUCKETS = [
    # Mar-Apr: from end-of-Feb close to end-of-Apr close. Length 2 months.
    dict(key="mar_apr_bull", anchor_month=2, end_month=4, length=2, direction="up",
         source="note p.10 verbatim: 'March-April Bull'"),
    # May-Oct: from end-of-Apr close to end-of-Oct close. Length 6 months.
    dict(key="may_oct_bear", anchor_month=4, end_month=10, length=6, direction="down",
         source="note p.10 verbatim: 'May-October Bear'; also the classic 'Sell in May' bear leg"),
    # Nov-Apr (spans year boundary): from end-of-Oct close to end-of-Apr close of the FOLLOWING year.
    # Length 6 months. Included to test the "Sell in May" folklore's complement directly, per
    # BRIEF.md's instruction to check whether that pattern shows up in this universe at all.
    dict(key="nov_apr_best_six", anchor_month=10, end_month=4, length=6, direction="up",
         source="classic 'Best Six Months' / Halloween-indicator complement to Sell-in-May "
         "(not from the note; tested because BRIEF.md asks whether Sell-in-May shows up at all)"),
]

N_BUCKETS_PER_SYMBOL = 12 + len(COMPOSITE_BUCKETS)
assert N_BUCKETS_PER_SYMBOL == 15


def monthly_close_series(bars: pd.DataFrame) -> pd.Series:
    """Last available close per calendar month, indexed by month-end Timestamp.

    `resample("ME")` (month-end) lands on the last real trading day at or before each calendar
    month's end -- it does not require a bar to exist on the 28th/30th/31st itself.
    """
    df = bars[["ts", "close"]].dropna().copy()
    df["ts"] = pd.to_datetime(df["ts"]).dt.tz_localize(None)
    df = df.set_index("ts").sort_index()
    monthly = df["close"].resample("ME").last().dropna()
    return monthly


def _hit_p_q_row(hit: float | None, baseline: float | None, n: int) -> dict:
    if hit is None or baseline is None or n <= 0:
        return {"hit_rate": hit, "baseline": baseline, "edge": None, "n_independent": n, "p_value": None}
    edge = hit - baseline
    successes = max(0, min(n, round(hit * n)))
    p = scan_mod.binomial_p_value(successes, n, baseline)
    return {"hit_rate": hit, "baseline": baseline, "edge": edge, "n_independent": n, "p_value": p}


def single_month_bucket(monthly: pd.Series, month: int) -> dict:
    """One calendar month's return sample: `close[month] / close[month-1] - 1` for every year."""
    all_returns = monthly.pct_change().dropna()
    month_returns = all_returns[all_returns.index.month == month]
    baseline_hit = None
    if len(all_returns) > 0:
        baseline_hit = float((all_returns > 0).mean())
    hit = float((month_returns > 0).mean()) if len(month_returns) > 0 else None
    row = _hit_p_q_row(hit, baseline_hit, len(month_returns))
    row.update(
        {
            "bucket": MONTH_NAMES[month - 1],
            "bucket_type": "single_month",
            "length_months": 1,
            "mean_return": float(month_returns.mean()) if len(month_returns) else None,
            "median_return": float(month_returns.median()) if len(month_returns) else None,
            "years": [int(y) for y in month_returns.index.year],
        }
    )
    return row


def composite_bucket(monthly: pd.Series, spec: dict) -> dict:
    """One composite N-month bucket's return sample, one observation per year the bucket is fully
    covered, plus the length-matched rolling baseline (all possible N-month windows, overlapping)."""
    anchor, end, length = spec["anchor_month"], spec["end_month"], spec["length"]
    spans_year = end <= anchor  # e.g. Oct(10) -> Apr(4): the bucket crosses into the next year

    rows = []
    years_present = sorted(set(monthly.index.year))
    for y in years_present:
        anchor_ts = pd.Timestamp(year=y, month=anchor, day=1) + pd.offsets.MonthEnd(0)
        end_year = y + 1 if spans_year else y
        end_ts = pd.Timestamp(year=end_year, month=end, day=1) + pd.offsets.MonthEnd(0)
        if anchor_ts not in monthly.index or end_ts not in monthly.index:
            continue
        start_price = monthly.loc[anchor_ts]
        end_price = monthly.loc[end_ts]
        if start_price <= 0:
            continue
        ret = end_price / start_price - 1.0
        rows.append({"label_year": int(y), "return": float(ret)})

    returns = pd.Series([r["return"] for r in rows], dtype=float)
    hit = float((returns > 0).mean()) if len(returns) else None

    # Length-matched rolling baseline: every possible overlapping N-month window across the symbol's
    # full monthly-close history.
    rolling = monthly.pct_change(length).dropna()
    baseline_hit = float((rolling > 0).mean()) if len(rolling) else None

    row = _hit_p_q_row(hit, baseline_hit, len(returns))
    row.update(
        {
            "bucket": spec["key"],
            "bucket_type": "composite",
            "length_months": length,
            "direction": spec["direction"],
            "source": spec["source"],
            "mean_return": float(returns.mean()) if len(returns) else None,
            "median_return": float(returns.median()) if len(returns) else None,
            "rolling_baseline_n_overlapping": int(len(rolling)),
            "years": [r["label_year"] for r in rows],
        }
    )
    return row


def verdict_for(row: dict, *, directional: bool) -> str:
    """Mirrors quantlab._verdict's logic (direction-checked, n<30 underpowered, q<=0.10 survives),
    reimplemented here rather than imported because quantlab._verdict is a private helper scoped to
    the Idea/event-study machinery and this module's rows are not `Idea` cells. The screening
    threshold (0.10) and small-sample floor (30) are pulled from quantlab/app constants, not
    reinvented."""
    edge, q, n = row.get("edge"), row.get("q_value"), row.get("n_independent", 0)
    if edge is None or q is None:
        return "untestable"
    if directional:
        direction = row["direction"]
        wrong_way = (direction == "up" and edge < 0) or (direction == "down" and edge > 0)
        if wrong_way:
            return "rejected"
    if n < 30:
        return "underpowered"
    if directional:
        return "survived" if q <= 0.10 else "inconclusive"
    # Non-directional (the 12 individual months): "discovery" framing, matching horizon_sweep.
    return "discovery" if q <= 0.10 else "no_discovery"


def run_symbol(symbol: str) -> dict:
    bars = bars_frame(symbol)
    monthly = monthly_close_series(bars)
    rows = []
    for m in range(1, 13):
        rows.append(single_month_bucket(monthly, m))
    for spec in COMPOSITE_BUCKETS:
        rows.append(composite_bucket(monthly, spec))
    assert len(rows) == N_BUCKETS_PER_SYMBOL
    return {
        "symbol": symbol,
        "n_months_available": int(len(monthly)),
        "coverage_first": str(monthly.index.min().date()) if len(monthly) else None,
        "coverage_last": str(monthly.index.max().date()) if len(monthly) else None,
        "rows": rows,
    }


def main() -> None:
    per_symbol = {}
    all_rows = []  # flat list in a fixed order, for the single BH ledger
    for symbol in PRIMARY:
        result = run_symbol(symbol)
        per_symbol[symbol] = result
        for row in result["rows"]:
            flat = dict(row)
            flat["symbol"] = symbol
            all_rows.append(flat)

    print(f"=== regime-risk seasonality family: {N_BUCKETS_PER_SYMBOL} buckets x {len(PRIMARY)} "
          f"symbols = {len(all_rows)} tests, one BH ledger ===")
    assert len(all_rows) == N_BUCKETS_PER_SYMBOL * len(PRIMARY)

    p_values = [r["p_value"] for r in all_rows]
    q_values = scan_mod.benjamini_hochberg(p_values)
    for row, q in zip(all_rows, q_values, strict=True):
        row["q_value"] = q
        directional = row["bucket_type"] == "composite"
        row["verdict"] = verdict_for(row, directional=directional)

    # Fold q_value/verdict back into per_symbol rows (same dict objects would be nicer, but the flat
    # list above copied them -- re-key by (symbol, bucket) instead).
    by_key = {(r["symbol"], r["bucket"]): r for r in all_rows}
    for symbol, result in per_symbol.items():
        for row in result["rows"]:
            src = by_key[(symbol, row["bucket"])]
            row["q_value"] = src["q_value"]
            row["verdict"] = src["verdict"]

    discoveries = [r for r in all_rows if r["verdict"] in ("survived", "discovery")]
    print(f"{len(discoveries)} of {len(all_rows)} at q<=0.10 (mixing directional 'survived' and "
          f"exploratory 'discovery' -- see report for which is which)")
    for d in discoveries:
        print(f"  {d['symbol']:6s} {d['bucket']:16s} edge={d['edge']:+.4f} n={d['n_independent']:3d} "
              f"q={d['q_value']:.4f} verdict={d['verdict']}")

    # Headline: the note's two literal claims + the Sell-in-May complement, every symbol.
    print("\n--- Note's claims, all 5 symbols ---")
    for bucket_key in ("mar_apr_bull", "may_oct_bear", "nov_apr_best_six"):
        print(f"\n{bucket_key}:")
        for symbol in PRIMARY:
            row = by_key[(symbol, bucket_key)]
            print(
                f"  {symbol:6s} edge={row['edge']:+.4f} hit={row['hit_rate']:.3f} "
                f"base={row['baseline']:.3f} n={row['n_independent']:3d} p={row['p_value']:.4f} "
                f"q={row['q_value']:.4f} verdict={row['verdict']}"
            )

    result = {
        "family": "regime-risk-seasonality",
        "screen_alpha": 0.10,
        "small_sample_threshold": 30,
        "buckets_declared": N_BUCKETS_PER_SYMBOL,
        "symbols_declared": PRIMARY,
        "family_size": len(all_rows),
        "composite_bucket_specs": COMPOSITE_BUCKETS,
        "cells": all_rows,
        "per_symbol": per_symbol,
    }
    write(result, "regime_risk_seasonality")
    print("\n=== regime_risk_seasonality.py complete ===")


if __name__ == "__main__":
    main()

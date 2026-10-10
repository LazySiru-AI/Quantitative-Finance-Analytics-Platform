"""Supplementary, EXPLORATORY cross-horizon scan for QQQ, SOXX, IGV -- same purpose as script 03, but
routes around a confirmed defect in app.backtest.scan.binomial_p_value (see BUG note below) that
crashes app.backtest.scan.scan outright on any (rule, horizon) pair whose independent_sample_size is
large (~>2000): math.comb(n, k) for n in the thousands produces a Python int with hundreds to
thousands of decimal digits, and multiplying it by a float (`p_null**k`) raises
`OverflowError: int too large to convert to float` inside app.backtest.scan.binomial_p_value's pmf().
That line is OUTSIDE the try/except in app.backtest.scan.scan(), so it is not caught per-entry --
it kills the entire scan (every rule, every horizon) for that ticker, not just the offending entry.

Confirmed trigger in this codebase: 'close > sma(200)' (momentum_persistence) at horizon=1 on QQQ
(n_indep=4896), SOXX (n_indep=4129) and IGV (n_indep=4561) -- a condition that is true on roughly
70% of trading days, scanned at the shortest horizon over a 20+ year history, is independent (no
window overlap at horizon=1) on almost every trigger.

This script therefore calls app.backtest.events.event_study and app.backtest.guards.check directly
(exactly what app.backtest.scan.scan's evaluate() closure does internally), then calls
app.backtest.scan.binomial_p_value itself, wrapped in a try/except OverflowError so ONE untestable
(rule, horizon) pair is marked untestable (p=None, matching the documented behaviour for every other
untestable case: guard failure, zero sample, etc.) rather than losing the whole scan. Benjamini-Hochberg
correction is then applied with app.backtest.scan.benjamini_hochberg (unmodified, and itself immune --
verified separately, it does no comb() arithmetic) over the full 25-trial family per ticker, with the
overflowed entry correctly still occupying a slot (m stays 25) exactly as an untestable entry should.

No app code is modified. This is the same public engine functions app.backtest.scan.scan calls
internally (binomial_p_value, benjamini_hochberg), driven directly because the module's own call site
cannot survive this input.
"""
import json
import sys
from pathlib import Path

# docs/research/scripts/03_horizon_scan.py -> docs/research/scripts -> docs/research -> docs -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "backend"))

import pandas as pd

from app.backtest import events as events_mod
from app.backtest import guards as guards_mod
from app.backtest.models import STUDY_HORIZONS, GuardStatus
from app.backtest.scan import benjamini_hochberg, binomial_p_value
from app.config import Settings
from app.db.duck import Interval
from app.market import store
from app.thesis.author import CATALOGUE

PROD_CFG = Settings()
SCRATCH = Path(r"C:\Users\<user>\AppData\Local\Temp\claude\C--Users--user--repos-Investing-dashboard\d14d649b-1473-460a-a2ee-2b45be6dcb6f\scratchpad")

RULES = [(t.key, t.entry) for t in CATALOGUE if not t.leveraged_only]


def bars_frame(symbol: str) -> pd.DataFrame:
    series = store.ensure_series(symbol, Interval.DAY, settings=PROD_CFG)
    return pd.DataFrame(
        {
            "ts": pd.Series([b.ts for b in series.bars], dtype="datetime64[ns, UTC]"),
            **{
                column: pd.Series([getattr(b, column) for b in series.bars], dtype="float64")
                for column in ("open", "high", "low", "close", "adj_close", "volume")
            },
        }
    )


def safe_p_value(guard_ok: bool, stats) -> tuple[float | None, str]:
    if not guard_ok or stats is None:
        return None, "guard_failed_or_no_stats"
    if stats.independent_sample_size <= 0:
        return None, "no_independent_sample"
    if stats.baseline_hit_rate is None or stats.hit_rate is None:
        return None, "no_hit_rate"
    successes = round(stats.hit_rate * stats.independent_sample_size)
    successes = max(0, min(successes, stats.independent_sample_size))
    try:
        p = binomial_p_value(successes, stats.independent_sample_size, stats.baseline_hit_rate)
        return p, "ok"
    except OverflowError as exc:
        return None, f"OVERFLOW (engine bug, see script docstring): {exc}"


def run_ticker(symbol: str) -> dict:
    bars = bars_frame(symbol)
    rows = []
    p_values: list[float | None] = []
    for key, expr in RULES:
        guard = guards_mod.check(expr, bars, interval=Interval.DAY)
        arms, _ = events_mod.event_study(bars, [expr], interval=Interval.DAY, horizons=list(STUDY_HORIZONS))
        arm = arms[0]
        for s in arm.stats:
            p, note = safe_p_value(guard.status == GuardStatus.PASSED, s)
            rows.append({"rule": key, "expression": expr, "horizon": s.horizon, "stats": s, "p_value": p, "note": note})
            p_values.append(p)

    q_values = benjamini_hochberg(p_values)
    for row, q in zip(rows, q_values, strict=True):
        row["q_value"] = q
        row["discovery"] = q is not None and q <= 0.10

    print(f"\n=== {symbol} horizon scan (safe) === trials={len(rows)} discoveries={sum(r['discovery'] for r in rows)}")
    for r in rows:
        s = r["stats"]
        print(
            f"  {r['rule']:24s} h={r['horizon']:>2} hit={s.hit_rate!s:>20} base={s.baseline_hit_rate!s:>20} "
            f"edge={s.edge!s:>21} n={s.sample_size:>5} n_indep={s.independent_sample_size:>5} "
            f"p={r['p_value']!s:>8} q={r['q_value']!s:>8} disc={r['discovery']} note={r['note']}"
        )

    return {
        "symbol": symbol,
        "trials": len(rows),
        "discoveries": sum(r["discovery"] for r in rows),
        "rows": [
            {
                "rule": r["rule"],
                "expression": r["expression"],
                "horizon": r["horizon"],
                "hit_rate": r["stats"].hit_rate,
                "baseline_hit_rate": r["stats"].baseline_hit_rate,
                "edge": r["stats"].edge,
                "sample_size": r["stats"].sample_size,
                "independent_sample_size": r["stats"].independent_sample_size,
                "p_value": r["p_value"],
                "q_value": r["q_value"],
                "discovery": r["discovery"],
                "note": r["note"],
            }
            for r in rows
        ],
    }


all_out = {}
for sym in ["QQQ", "SOXX", "IGV"]:
    all_out[sym] = run_ticker(sym)

(SCRATCH / "horizon_scan_results.json").write_text(json.dumps(all_out, indent=2, default=str), encoding="utf-8")
print("\nDone.")

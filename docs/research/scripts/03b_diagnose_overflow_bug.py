"""Correct diagnostic: attach the real guard (app.backtest.guards.check) before calling
_entry_p_value, matching exactly what app.backtest.scan.scan's production evaluate() closure does
(app.backtest.service.build_scan). Identifies every (symbol, rule, horizon) pair whose
independent_sample_size is large enough to overflow app.backtest.scan.binomial_p_value.
"""
import sys
from pathlib import Path

# docs/research/scripts/03b_diagnose_overflow_bug.py -> docs/research/scripts -> docs/research -> docs -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "backend"))

import pandas as pd

from app.backtest import events as events_mod
from app.backtest import guards as guards_mod
from app.backtest.models import STUDY_HORIZONS
from app.backtest.scan import _entry_p_value
from app.config import Settings
from app.db.duck import Interval
from app.market import store
from app.thesis.author import CATALOGUE

PROD_CFG = Settings()
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


failures = []
for symbol in ["QQQ", "SOXX", "IGV"]:
    bars = bars_frame(symbol)
    for key, expr in RULES:
        guard = guards_mod.check(expr, bars, interval=Interval.DAY)
        arms, _ = events_mod.event_study(bars, [expr], interval=Interval.DAY, horizons=list(STUDY_HORIZONS))
        arm = arms[0]
        for s in arm.stats:
            try:
                p = _entry_p_value(guard, s)
                status = f"p={p}"
            except OverflowError as exc:
                p = None
                status = f"OVERFLOW: {exc}"
                failures.append((symbol, key, s.horizon, s.independent_sample_size))
            print(f"{symbol:5s} {key:24s} h={s.horizon:>2} guard={guard.status.value:10s} n_indep={s.independent_sample_size:>5} -> {status}")

print("\n--- overflow summary ---")
for f in failures:
    print(f)

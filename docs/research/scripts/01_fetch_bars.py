"""Fetch/confirm bar coverage for the five instruments, using the app's normal market-data path
(store.ensure_series against the production data/store/bars cache -- permitted per the task's hard
rule 1: this is the app working normally, not touching brokerage data).

Prints bar counts and date ranges only. Writes nothing outside data/store/bars.
"""
import sys
from pathlib import Path

# docs/research/scripts/01_fetch_bars.py -> docs/research/scripts -> docs/research -> docs -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from app.config import Settings
from app.db.duck import Interval
from app.market import store

cfg = Settings()  # production store_dir -- bars only, read-only from our side (may sync if stale)

tickers = ["QQQ", "SOXX", "IGV", "DRAM", "FONO"]

for t in tickers:
    try:
        series = store.ensure_series(t, Interval.DAY, settings=cfg)
        n = len(series.bars)
        if n:
            first = series.bars[0].ts
            last = series.bars[-1].ts
            print(f"{t}: {n} bars, {first.date()} -> {last.date()}")
        else:
            print(f"{t}: 0 bars")
        if series.warnings:
            for w in series.warnings:
                print(f"   warning: {w.kind}: {w.message}")
    except Exception as exc:
        print(f"{t}: EXCEPTION {type(exc).__name__}: {exc}")

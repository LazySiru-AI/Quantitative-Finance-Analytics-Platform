"""Run app.thesis.loop.run -- the primary guarded instrument -- for QQQ, SOXX, IGV, DRAM, FONO.

Isolation: every run uses a fresh temp directory as Settings.store_dir, so the thesis ledger and
holdout state land in store/thesis.sqlite under a TEMP directory, never under the production
data/store. Bars are supplied directly (bars=frame) so loop.run never calls store.ensure_series
against the production store either -- the only touch of data/store/bars anywhere in this research
was the earlier read-only fetch/cache-fill via store.ensure_series(default settings), which is
market-data, not brokerage data (permitted).

Bars themselves are read from the production data/store/bars cache (already synced by script 01)
using store.ensure_series with DEFAULT settings -- read-only from our side, exactly the same call the
UI's chart endpoint makes -- and then handed to loop.run as an injected frame.
"""
import json
import sys
import tempfile
from pathlib import Path

# docs/research/scripts/02_thesis_loop.py -> docs/research/scripts -> docs/research -> docs -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "backend"))

import pandas as pd

from app.config import Settings
from app.db.duck import Interval
from app.market import store
from app.thesis import loop as loop_mod
from app.thesis.models import DEFAULT_ITERATION_BUDGET

PROD_CFG = Settings()  # default store_dir -- for reading bars only


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
    ), series


def run_ticker(symbol: str) -> dict:
    tmpdir = tempfile.mkdtemp(prefix=f"thesis_isolated_{symbol}_")
    tmp_cfg = Settings(store_dir=Path(tmpdir))
    print(f"=== {symbol} === isolated store: {tmpdir}")

    try:
        frame, series = bars_frame(symbol)
    except Exception as exc:
        print(f"{symbol}: bars fetch raised {type(exc).__name__}: {exc}")
        return {"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"}

    result = loop_mod.run(
        symbol,
        interval=Interval.DAY,
        budget=DEFAULT_ITERATION_BUDGET,
        settings=tmp_cfg,
        bars=frame,
    )

    out_path = Path(tmpdir) / f"{symbol}_loop_result.json"
    out_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    # also copy into scratchpad for convenience
    scratch_copy = Path(r"C:\Users\<user>\AppData\Local\Temp\claude\C--Users--user--repos-Investing-dashboard\d14d649b-1473-460a-a2ee-2b45be6dcb6f\scratchpad") / f"{symbol}_loop_result.json"
    scratch_copy.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    print(f"{symbol}: outcome={result.outcome.value} iterations_used={result.iterations_used}/{result.budget}")
    print(f"{symbol}: bars in frame = {len(frame)}, first={frame['ts'].min()}, last={frame['ts'].max()}")
    if result.holdout:
        print(f"{symbol}: holdout split_date={result.holdout.split_date} status={result.holdout.status.value} attempts={result.holdout.attempts}")
    for w in result.warnings:
        print(f"{symbol}: WARNING [{w.kind}] {w.message}")
    for rec in result.records:
        ev = rec.in_sample
        ho = rec.holdout
        print(
            f"  - {rec.thesis.hypothesis[:70]!r} entry={rec.thesis.entry!r} horizon={rec.thesis.horizon} "
            f"status={rec.status.value} verdict={rec.verdict.value if rec.verdict else None}"
        )
        if ev:
            print(
                f"      in-sample: hit={ev.hit_rate} baseline={ev.baseline_hit_rate} edge={ev.edge} "
                f"n={ev.sample_size} n_indep={ev.independent_sample_size} p={ev.p_value} q={ev.q_value} "
                f"trials_at_eval={ev.trials_at_evaluation}"
            )
        if ho:
            print(
                f"      holdout:   hit={ho.hit_rate} baseline={ho.baseline_hit_rate} edge={ho.edge} "
                f"n={ho.sample_size} n_indep={ho.independent_sample_size} p={ho.p_value} q={ho.q_value}"
            )
    print()
    return {
        "symbol": symbol,
        "outcome": result.outcome.value,
        "iterations_used": result.iterations_used,
        "budget": result.budget,
        "holdout": result.holdout.model_dump(mode="json") if result.holdout else None,
        "warnings": [w.model_dump(mode="json") for w in result.warnings],
        "records": [r.model_dump(mode="json") for r in result.records],
        "tmpdir": tmpdir,
    }


all_out = {}
for sym in ["QQQ", "SOXX", "IGV"]:
    all_out[sym] = run_ticker(sym)

# DRAM: only 89 bars, expect HOLDOUT_UNAVAILABLE
all_out["DRAM"] = run_ticker("DRAM")

# FONO: no chart data at all; capture the refusal from loop.run itself, with bars=None so it goes
# through store.ensure_series (default settings, read path) exactly as the app would.
print("=== FONO ===")
tmpdir = tempfile.mkdtemp(prefix="thesis_isolated_FONO_")
tmp_cfg = Settings(store_dir=Path(tmpdir))
try:
    result = loop_mod.run("FONO", interval=Interval.DAY, budget=DEFAULT_ITERATION_BUDGET, settings=tmp_cfg)
    print("FONO: unexpectedly succeeded:", result.outcome.value)
    all_out["FONO"] = {"symbol": "FONO", "outcome": result.outcome.value}
except Exception as exc:
    print(f"FONO: loop.run raised {type(exc).__name__}: {exc}")
    all_out["FONO"] = {"symbol": "FONO", "error": f"{type(exc).__name__}: {exc}"}

Path(r"C:\Users\<user>\AppData\Local\Temp\claude\C--Users--user--repos-Investing-dashboard\d14d649b-1473-460a-a2ee-2b45be6dcb6f\scratchpad\all_loop_results.json").write_text(
    json.dumps(all_out, indent=2, default=str), encoding="utf-8"
)
print("Done.")

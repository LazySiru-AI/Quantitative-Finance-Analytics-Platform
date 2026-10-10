"""Strategy backtest (app.backtest.strategy.backtest) for every catalogue template, on the FULL
available history of QQQ, SOXX, IGV -- entry/exit mechanics, win/loss distribution, drawdown, and
cost drag, always against buy-and-hold on the identical window. Uses default Costs() (5bps slippage
each way, $0 commission, $10,000 notional) -- the app's documented non-zero default.

Also runs app.backtest.drawdown.profile (close basis, top 5) per ticker as purely descriptive
buy-and-hold drawdown context -- no hypothesis, no baseline needed for that one (see its own
docstring).

No app code modified. No store writes (bars supplied as an in-memory frame).
"""
import json
import sys
from pathlib import Path

# docs/research/scripts/04_strategy_backtest.py -> docs/research/scripts -> docs/research -> docs -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "backend"))

import pandas as pd

from app.backtest import drawdown as drawdown_mod
from app.backtest import strategy as strategy_mod
from app.backtest.models import Costs, DrawdownBasis, ExitReason, StrategySpec
from app.config import Settings
from app.db.duck import Interval
from app.market import store
from app.thesis.author import CATALOGUE

PROD_CFG = Settings()
SCRATCH = Path(r"C:\Users\<user>\AppData\Local\Temp\claude\C--Users--user--repos-Investing-dashboard\d14d649b-1473-460a-a2ee-2b45be6dcb6f\scratchpad")

TEMPLATES = [t for t in CATALOGUE if not t.leveraged_only]


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


def metrics_dict(m) -> dict:
    return {
        "total_return": m.total_return,
        "cagr": m.cagr,
        "volatility": m.volatility,
        "sharpe": m.sharpe,
        "sortino": m.sortino,
        "max_drawdown": m.max_drawdown,
        "exposure": m.exposure,
        "trades": m.trades,
        "trades_per_year": m.trades_per_year,
        "win_rate": m.win_rate,
    }


def run_ticker(symbol: str) -> dict:
    bars = bars_frame(symbol)
    out_templates = {}
    for t in TEMPLATES:
        if t.exit is None and t.max_holding_bars is None:
            print(f"{symbol}/{t.key}: SKIPPED -- no exit and no max_holding_bars (backtest() would raise)")
            continue
        spec = StrategySpec(
            entry=t.entry,
            exit=t.exit,
            max_holding_bars=t.max_holding_bars,
            stop_loss_pct=t.stop_loss_pct,
        )
        costs = Costs()
        m, bh, trades, equity, cost_drag, open_trades = strategy_mod.backtest(
            bars, spec, interval=Interval.DAY, costs=costs
        )
        closed = [tr for tr in trades if not tr.open_at_end]
        wins = [tr for tr in closed if tr.return_pct > 0]
        losses = [tr for tr in closed if tr.return_pct <= 0]
        exit_reason_counts = {r.value: sum(1 for tr in closed if tr.exit_reason == r) for r in ExitReason}
        worst = min((tr.return_pct for tr in closed), default=None)
        best = max((tr.return_pct for tr in closed), default=None)

        print(f"\n--- {symbol} / {t.key} ---")
        print(f"  entry={spec.entry!r} exit={spec.exit!r} max_holding_bars={spec.max_holding_bars} stop_loss_pct={spec.stop_loss_pct}")
        print(f"  costs: slippage_bps={costs.slippage_bps} commission_per_trade={costs.commission_per_trade} notional={costs.notional}")
        print(f"  strategy: total_return={m.total_return} cagr={m.cagr} sharpe={m.sharpe} max_dd={m.max_drawdown} exposure={m.exposure} trades={m.trades} trades/yr={m.trades_per_year} win_rate={m.win_rate}")
        print(f"  buy&hold: total_return={bh.total_return} cagr={bh.cagr} sharpe={bh.sharpe} max_dd={bh.max_drawdown}")
        print(f"  cost_drag={cost_drag} open_trades={open_trades} closed_trades={len(closed)} wins={len(wins)} losses={len(losses)} best={best} worst={worst}")
        print(f"  exit_reason_counts={exit_reason_counts}")

        out_templates[t.key] = {
            "entry": spec.entry,
            "exit": spec.exit,
            "max_holding_bars": spec.max_holding_bars,
            "stop_loss_pct": spec.stop_loss_pct,
            "costs": {"slippage_bps": costs.slippage_bps, "commission_per_trade": costs.commission_per_trade, "notional": costs.notional},
            "strategy_metrics": metrics_dict(m),
            "buy_hold_metrics": metrics_dict(bh),
            "cost_drag": cost_drag,
            "open_trades": open_trades,
            "closed_trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "best_trade": best,
            "worst_trade": worst,
            "exit_reason_counts": exit_reason_counts,
            "first_bar": str(bars["ts"].min()),
            "last_bar": str(bars["ts"].max()),
            "bars": len(bars),
        }

    episodes, current, considered = drawdown_mod.profile(bars, basis=DrawdownBasis.CLOSE, top=5)
    print(f"\n--- {symbol} buy&hold drawdown (close basis) --- episodes_considered={considered}")
    for e in episodes:
        print(f"  peak={e.peak_date} trough={e.trough_date} depth={e.depth:.3f} bars_to_trough={e.bars_to_trough} recovery={e.recovery_date} still_underwater={e.still_underwater}")
    if current:
        print(f"  CURRENT: peak={current.peak_date} depth={current.depth:.3f} bars_underwater={current.bars_underwater} still_underwater={current.still_underwater}")

    return {
        "symbol": symbol,
        "templates": out_templates,
        "drawdown_episodes": [
            {
                "peak_date": str(e.peak_date), "trough_date": str(e.trough_date), "depth": e.depth,
                "bars_to_trough": e.bars_to_trough, "recovery_date": str(e.recovery_date) if e.recovery_date else None,
                "still_underwater": e.still_underwater,
            }
            for e in episodes
        ],
        "drawdown_current": (
            {"peak_date": str(current.peak_date), "depth": current.depth, "bars_underwater": current.bars_underwater}
            if current else None
        ),
        "drawdown_episodes_considered": considered,
    }


all_out = {}
for sym in ["QQQ", "SOXX", "IGV"]:
    all_out[sym] = run_ticker(sym)

(SCRATCH / "strategy_backtest_results.json").write_text(json.dumps(all_out, indent=2, default=str), encoding="utf-8")
print("\nDone.")

"""Macro stream, Part A: a dated, quantified snapshot of market conditions as of 2026-08-11.

Two kinds of number come out of this script:

1. **The app's own macro panel** (`app.market.macro.build_snapshot` / `load_fear_greed`): 10Y yield,
   2s10s spread, WTI/Brent, dollar index, gold, TLT, CNN Fear & Greed. These are read verbatim from
   the application's own composition layer -- this script adds no arithmetic of its own here, it just
   asks for the snapshot and records what came back, including which tiles degraded and why.

2. **Market internals computed here, directly from cached bars** (`quantlab.bars_frame`), because the
   app has no "distance from 200-day SMA" or "sector dispersion" endpoint. Every number in this half
   is produced by plain pandas arithmetic against the same production bar cache the ticker page reads
   -- `app.market.store.ensure_series` -- so the methodology is fully inline below rather than hidden
   in application code:

   - **Distance from SMA(200)/SMA(50)**: `(close / sma - 1) * 100`, computed on the *unadjusted*
     `close` column (SMAs are a price-trend construct, not a total-return one).
   - **1/3/6/12-month total return**: `adj_close[t] / adj_close[t-N] - 1`, `N` in trading days
     (21/63/126/252) as a standard approximation of calendar months. `adj_close` is used here
     (dividends included) because "total return" is the term the brief asks for.
   - **Drawdown from trailing 52-week high**: `close[t] / max(close[t-251:t+1]) - 1`, on unadjusted
     `close` -- the conventional "off its 52-week high" framing quoted in price terms, not total
     return.
   - **Realised 20-day volatility**: stdev of the trailing 20 daily log returns of `close`,
     annualised by `sqrt(252)`, reported as a percent.
   - **Sector dispersion**: best 3-month total return minus worst 3-month total return across the
     eleven sector SPDRs.
   - **VIX percentile**: the latest ^VIX close's percentile rank within its own trailing history
     (full cached history, and separately the trailing ~1y and ~5y windows, since "percentile of what
     window" changes the read).

Every symbol's actual last bar date is recorded and printed. The brief flags that SPY's cache lagged
other symbols in an earlier check (2026-08-07 vs 2026-08-10 for most) -- this script does not assume
that has since resolved; it re-checks and reports per symbol every run.

Run from `docs/research/strategy-lab/`:
    ../../../.venv/Scripts/python.exe scripts/macro_snapshot.py
"""

from __future__ import annotations

import datetime as dt
import math
import sys

sys.path.insert(0, "lib")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from quantlab import write  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db.duck import Interval  # noqa: E402
from app.market import store  # noqa: E402
from app.market.macro import build_snapshot, load_fear_greed, load_series  # noqa: E402
from app.market.macro_models import MacroSnapshot  # noqa: E402

CFG = Settings()


def bars_frame(symbol: str) -> pd.DataFrame:
    """Daily bars for `symbol`, forced through a fresh sync (`refresh=True`).

    `quantlab.bars_frame` uses the store's default staleness gate (`refresh=False`), which triggers
    on `fetched_at` age, not on how old the newest *bar* is -- see `app.market.store._is_stale`'s
    docstring: it is measured against the last fetch time so a chart opened on a closed market
    doesn't hammer the provider, and that is the right default for a chart. It is the wrong default
    for this script: an initial run found several symbols (SPY, IWM, all eleven sector SPDRs, TLT,
    GLD) sitting on a 2026-08-07 last bar under the default gate while QQQ, ^VIX and DX-Y.NYB were
    already at 2026-08-10 -- the store's last sync had simply happened recently enough on the former
    group to skip a re-check, not because 08-07 was actually the newest available data. Forcing
    `refresh=True` here asks the provider directly, every run, so "last bar date" in this script's
    output means "the newest bar the provider will currently serve," not "the newest bar this cache
    happened to already have." `sync_bars`'s own `ProviderUnavailable` fallback (serve stored data
    with a warning, only raise if nothing is stored at all) still applies underneath this.
    """
    series = store.ensure_series(symbol, Interval.DAY, refresh=True, settings=CFG)
    return pd.DataFrame(
        {
            "ts": pd.Series([b.ts for b in series.bars], dtype="datetime64[ns, UTC]"),
            **{
                column: pd.Series([getattr(b, column) for b in series.bars], dtype="float64")
                for column in ("open", "high", "low", "close", "adj_close", "volume")
            },
        }
    ), list(series.warnings)

# The internals table: SPY/QQQ/IWM plus the eleven sector SPDRs. XLRE is included even though it is
# not in the study's fixed "primary" or "replication" backtest universes (BRIEF.md section 2) --
# this is Part A market-internals measurement, not a backtest, and the brief explicitly asks for
# "SPY/QQQ/IWM and all eleven sector ETFs".
BROAD = ["SPY", "QQQ", "IWM"]
SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLU", "XLI", "XLB", "XLC", "XLRE"]
INTERNALS_UNIVERSE = BROAD + SECTORS

# Extra series read as signals only (never as tradable instruments -- BRIEF.md section 2).
SIGNAL_SYMBOLS = ["TLT", "GLD", "^VIX", "DX-Y.NYB"]

TRADING_DAYS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}


def _log_returns(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift(1))


def _pct(x: float) -> float:
    return round(x * 100.0, 3)


def symbol_internals(symbol: str) -> dict:
    """One row of the internals table for `symbol`. Raises whatever `bars_frame` raises -- a missing
    or empty series is a finding to report, not to swallow."""
    df, sync_warnings = bars_frame(symbol)
    if df.empty:
        return {"symbol": symbol, "error": "no bars in cache"}

    df = df.sort_values("ts").reset_index(drop=True)
    close = df["close"]
    adj_close = df["adj_close"]
    last_date = df["ts"].iloc[-1].date().isoformat()
    last_close = float(close.iloc[-1])
    n = len(df)

    row: dict = {
        "symbol": symbol,
        "last_bar_date": last_date,
        "n_bars": n,
        "last_close": round(last_close, 4),
        "sync_warnings": [w.message for w in sync_warnings],
    }

    # Distance from SMA(200) / SMA(50), price-basis.
    for window, key in ((200, "sma200"), (50, "sma50")):
        if n >= window:
            sma = float(close.tail(window).mean())
            row[f"dist_from_{key}_pct"] = _pct(last_close / sma - 1.0)
            row[f"{key}"] = round(sma, 4)
        else:
            row[f"dist_from_{key}_pct"] = None
            row[f"{key}"] = None
            row.setdefault("warnings", []).append(
                f"only {n} bars in cache, cannot compute SMA({window})"
            )

    # Total returns over trading-day-approximated horizons, adjusted-close basis.
    for label, td in TRADING_DAYS.items():
        if n > td:
            base = float(adj_close.iloc[-1 - td])
            cur = float(adj_close.iloc[-1])
            row[f"return_{label}_pct"] = _pct(cur / base - 1.0) if base else None
        else:
            row[f"return_{label}_pct"] = None
            row.setdefault("warnings", []).append(
                f"only {n} bars in cache, cannot compute {label} return ({td} trading days needed)"
            )

    # Drawdown from trailing 52-week (252 trading day) high, price-basis.
    window_252 = close.tail(min(n, 252))
    high_252 = float(window_252.max())
    row["trailing_52w_high"] = round(high_252, 4)
    row["drawdown_from_52w_high_pct"] = _pct(last_close / high_252 - 1.0)
    if n < 252:
        row.setdefault("warnings", []).append(
            f"only {n} bars in cache, 52-week high computed over the full available {n}-bar history, "
            "not a true 252-session window"
        )

    # Realised 20-day volatility, annualised, price-basis.
    if n >= 21:
        logret = _log_returns(close).tail(20)
        vol_daily = float(logret.std(ddof=1))
        row["realised_vol_20d_annualised_pct"] = _pct(vol_daily * math.sqrt(252))
    else:
        row["realised_vol_20d_annualised_pct"] = None
        row.setdefault("warnings", []).append(f"only {n} bars in cache, cannot compute 20-day vol")

    return row


def vix_percentile() -> dict:
    """Where the latest ^VIX close sits in its own trailing distribution, full-history and over the
    trailing ~1y / ~5y windows. A percentile is only as meaningful as the window it's taken over, so
    all three are reported rather than picking one silently."""
    df, _sync_warnings = bars_frame("^VIX")
    df = df.sort_values("ts").reset_index(drop=True)
    if df.empty:
        return {"error": "no ^VIX bars in cache"}
    close = df["close"].dropna()
    last_date = df["ts"].iloc[-1].date().isoformat()
    last = float(close.iloc[-1])

    out = {
        "last_bar_date": last_date,
        "last_close": round(last, 4),
        "n_bars_full_history": int(len(close)),
    }
    for label, window in (("full_history", None), ("trailing_1y", 252), ("trailing_5y", 1260)):
        series = close if window is None else close.tail(window)
        if len(series) < 30:
            out[f"percentile_{label}"] = None
            out.setdefault("warnings", []).append(
                f"{label}: only {len(series)} observations, below the 30-obs floor this study "
                "treats as underpowered elsewhere"
            )
            continue
        pct_rank = float((series <= last).sum()) / float(len(series)) * 100.0
        out[f"percentile_{label}"] = round(pct_rank, 2)
        out[f"n_{label}"] = int(len(series))
    return out


def sector_dispersion(internals: list[dict]) -> dict:
    """Best minus worst 3-month total return among the eleven sector SPDRs -- a rotation indicator,
    not a ranking of any sector as a buy or sell."""
    by_symbol = {row["symbol"]: row for row in internals if row["symbol"] in SECTORS}
    rets = {
        sym: row["return_3m_pct"]
        for sym, row in by_symbol.items()
        if row.get("return_3m_pct") is not None
    }
    if not rets:
        return {"error": "no sector 3-month returns available"}
    best_sym = max(rets, key=lambda s: rets[s])
    worst_sym = min(rets, key=lambda s: rets[s])
    return {
        "best_sector": best_sym,
        "best_3m_return_pct": rets[best_sym],
        "worst_sector": worst_sym,
        "worst_3m_return_pct": rets[worst_sym],
        "dispersion_pct_pts": round(rets[best_sym] - rets[worst_sym], 3),
        "n_sectors": len(rets),
    }


def macro_tile_dict(snapshot: MacroSnapshot) -> dict:
    """Reduce the app's `MacroSnapshot` to plain JSON for our own file, preserving provenance and
    warnings rather than just the headline value -- a tile that fell back to a Yahoo proxy or came
    back empty is itself a finding."""

    def tile_row(t):
        return {
            "key": t.key,
            "label": t.label,
            "value": t.value,
            "unit": t.unit.value,
            "as_of": t.as_of.isoformat() if t.as_of else None,
            "source": t.source.value,
            "change": {
                "mode": t.change.mode.value,
                "day": t.change.day,
                "week": t.change.week,
                "month": t.change.month,
                "ytd": t.change.ytd,
            },
            "warnings": [w.message for w in t.warnings],
        }

    def mover_row(m):
        return {
            "symbol": m.symbol,
            "label": m.label,
            "price": m.price,
            "as_of": m.as_of.isoformat() if m.as_of else None,
            "source": m.source.value,
            "change": {
                "mode": m.change.mode.value,
                "day": m.change.day,
                "week": m.change.week,
                "month": m.change.month,
                "ytd": m.change.ytd,
            },
            "warnings": [w.message for w in m.warnings],
        }

    fg = snapshot.fear_greed
    fg_row = None
    if fg is not None:
        fg_row = {
            "score": fg.score,
            "rating": fg.rating.value,
            "source": fg.source.value,
            "as_of": fg.as_of.isoformat(),
            "previous_close": fg.previous_close,
            "previous_week": fg.previous_week,
            "previous_month": fg.previous_month,
            "previous_year": fg.previous_year,
            "n_history_points": len(fg.history),
            "history_span": (
                {
                    "first": fg.history[0].date.isoformat(),
                    "last": fg.history[-1].date.isoformat(),
                }
                if fg.history
                else None
            ),
            "components": [
                {
                    "key": c.key,
                    "label": c.label,
                    "raw_value": c.raw_value,
                    "rating": c.rating.value if c.rating else None,
                    "as_of": c.as_of.isoformat() if c.as_of else None,
                }
                for c in fg.components
            ],
            "warnings": [w.message for w in fg.warnings],
        }

    return {
        "generated_at": snapshot.generated_at.isoformat(),
        "rates": [tile_row(t) for t in snapshot.rates],
        "oil": [tile_row(t) for t in snapshot.oil],
        "fear_greed": fg_row,
        "movers": [mover_row(m) for m in snapshot.movers],
        "warnings": [w.message for w in snapshot.warnings],
    }


def main() -> None:
    print("Building app macro snapshot (build_snapshot, refresh=True)...")
    snapshot = build_snapshot(CFG, refresh=True)
    macro_panel = macro_tile_dict(snapshot)

    print("Loading CNN Fear & Greed directly too (load_fear_greed) for comparison...")
    try:
        fg_direct = load_fear_greed(CFG)
        fg_direct_row = {
            "score": fg_direct.score,
            "rating": fg_direct.rating.value,
            "source": fg_direct.source.value,
            "as_of": fg_direct.as_of.isoformat(),
        }
    except Exception as exc:  # noqa: BLE001 -- report whatever the app raised, verbatim
        fg_direct_row = {"error": f"{type(exc).__name__}: {exc}"}

    print(f"Computing internals for {INTERNALS_UNIVERSE}...")
    internals = []
    for sym in INTERNALS_UNIVERSE:
        try:
            internals.append(symbol_internals(sym))
        except Exception as exc:  # noqa: BLE001
            internals.append({"symbol": sym, "error": f"{type(exc).__name__}: {exc}"})

    print("Computing TLT/GLD internals (signals, not part of the sector/broad table but useful)...")
    signal_internals = []
    for sym in SIGNAL_SYMBOLS:
        try:
            signal_internals.append(symbol_internals(sym))
        except Exception as exc:  # noqa: BLE001
            signal_internals.append({"symbol": sym, "error": f"{type(exc).__name__}: {exc}"})

    print(
        "Cross-checking WTI/Brent/10Y against their Yahoo proxies directly "
        "(FRED's DGS10 and oil series can lag by several days) ..."
    )
    oil_proxy = {}
    for sid in ("CL=F", "BZ=F", "^TNX"):
        try:
            series = load_series(CFG, sid, refresh=True)
            latest = series.latest
            oil_proxy[sid] = {
                "title": series.title,
                "as_of": latest.date.isoformat() if latest else None,
                "value": latest.value if latest else None,
            }
        except Exception as exc:  # noqa: BLE001
            oil_proxy[sid] = {"error": f"{type(exc).__name__}: {exc}"}

    print("VIX percentile...")
    vix_row = vix_percentile()

    print("Sector dispersion...")
    dispersion = sector_dispersion(internals)

    result = {
        "run_date": "2026-08-11",
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "app_macro_panel": macro_panel,
        "fear_greed_direct_call": fg_direct_row,
        "internals": internals,
        "signal_internals": signal_internals,
        "vix_percentile": vix_row,
        "sector_dispersion": dispersion,
        "yahoo_proxy_crosscheck": oil_proxy,
    }

    write(result, "macro_snapshot")

    # Also print a compact human-readable summary to stdout for the terminal record.
    print("\n--- Last bar date per symbol ---")
    for row in internals + signal_internals:
        print(f"  {row.get('symbol'):10s} last_bar={row.get('last_bar_date', row.get('error'))}")

    print("\n--- Internals headline ---")
    for row in internals:
        if "error" in row and "dist_from_sma200_pct" not in row:
            print(f"  {row['symbol']:6s} ERROR: {row['error']}")
            continue
        print(
            f"  {row['symbol']:6s} 200MA={row.get('dist_from_sma200_pct')!s:>8}%  "
            f"50MA={row.get('dist_from_sma50_pct')!s:>8}%  "
            f"DD52w={row.get('drawdown_from_52w_high_pct')!s:>8}%  "
            f"vol20d={row.get('realised_vol_20d_annualised_pct')!s:>8}%"
        )

    print("\n--- VIX percentile ---")
    print(vix_row)
    print("\n--- Sector dispersion ---")
    print(dispersion)
    print("\n--- Yahoo-proxy crosscheck (WTI/Brent/10Y) ---")
    print(oil_proxy)


if __name__ == "__main__":
    main()

"""Universe characterisation study -- stream `universe`, run 2026-08-11.

Answers "what is worth researching right now, for short-term swing and for long-term holding" the
only way this study is allowed to: by *measuring* a broad candidate universe, never by recommending
one. See `docs/research/strategy-lab/BRIEF.md` and this stream's assignment for the full brief.

This script does not run the pre-registered thesis/BH machinery (`run_family`) -- there is no
hypothesis here, no p-value, no correction family. It reuses the harness only for what it is built
to give consistently: bars from the production cache (`quantlab.bars_frame`), the app's own
buy-and-hold mechanics (`quantlab.strategy_backtest`, via a dummy always-in-market idea, to reuse
`app.backtest.strategy._buy_hold` and `app.backtest.metrics.compute` rather than reimplementing
CAGR/vol/Sharpe/max-DD by hand), and the app's own drawdown episode finder
(`quantlab.drawdown_profile` -> `app.backtest.drawdown.profile`). ATR uses the identical function the
rule DSL's `atr(14)` calls (`app.indicators.volatility.atr`). Everything this script computes that the
app does not already provide (variance ratio, autocorrelation, realised vol, correlation matrix,
leveraged-decay comparison) is plain pandas/numpy on top of those bars, described in the docstrings
below so a reader can audit the exact method.

Read-only with respect to money and the ledger: no run cards are written, `thesis.sqlite` and
`ledger.sqlite` are never opened. Fetching a symbol for the first time writes to the shared bar cache
(`data/store/bars`) via `app.market.store.ensure_series` -- that is the app working normally.
"""

from __future__ import annotations

import datetime as dt
import sys

sys.path.insert(0, "lib")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from quantlab import Idea, bars_frame, drawdown_profile, slice_window, strategy_backtest, write  # noqa: E402

from app.indicators.volatility import atr as atr_indicator  # noqa: E402
from app.thesis import instruments as instruments_mod  # noqa: E402

TODAY = dt.date(2026, 8, 11)

# ---------------------------------------------------------------------------
# Part A -- candidate universe, declared before any fetch
# ---------------------------------------------------------------------------

# Every symbol below is declared with its category and a one-line reason *before* fetching, per the
# brief's requirement for anything outside the primary/replication universe in BRIEF.md section 2.
# This script is a separate stream (`universe`) from the hypothesis-testing streams and does not
# touch their declared families.

CANDIDATES: dict[str, dict[str, str]] = {
    "core": {
        "SPY": "broad large-cap, S&P 500, cap-weighted",
        "VOO": "broad large-cap, S&P 500, cap-weighted, Vanguard share class of the same index as SPY",
        "VTI": "total US market, cap-weighted, broader than the S&P 500 alone",
        "QQQ": "large-cap growth, Nasdaq-100, cap-weighted",
        "QQQM": "large-cap growth, Nasdaq-100, cap-weighted -- lower-fee share class of QQQ, named in note p.11",
        "IWM": "small cap, Russell 2000",
        "DIA": "large-cap, Dow 30, price-weighted (mechanically different from the cap-weighted funds above)",
        "RSP": "S&P 500 equal-weight -- same constituents as SPY, different weighting scheme",
    },
    "sectors": {
        "XLK": "SPDR technology sector",
        "XLF": "SPDR financial sector",
        "XLE": "SPDR energy sector",
        "XLV": "SPDR healthcare sector",
        "XLY": "SPDR consumer discretionary sector",
        "XLP": "SPDR consumer staples sector",
        "XLU": "SPDR utilities sector",
        "XLI": "SPDR industrials sector",
        "XLB": "SPDR materials sector",
        "XLC": "SPDR communication services sector",
        "XLRE": "SPDR real estate sector",
    },
    "themes": {
        "SOXX": "semiconductors -- note p.11's own named list",
        "SMH": "semiconductors -- larger, more mega-cap-concentrated alternative to SOXX",
        "IGV": "software",
        "XBI": "biotech, equal-weighted (mechanically distinct from cap-weighted sector funds)",
        "ITA": "defense/aerospace",
        "ARKK": "actively-managed disruptive-growth theme, structurally different turnover/concentration profile",
    },
    "factor_defensive": {
        "USMV": "minimum-volatility factor",
        "SPLV": "low-volatility factor",
        "VIG": "dividend growth factor",
        "SCHD": "dividend yield/quality factor",
        "QUAL": "quality factor",
        "MTUM": "momentum factor",
        "VLUE": "value factor",
    },
    "non_equity": {
        "TLT": "long-duration US Treasuries",
        "IEF": "intermediate-duration US Treasuries",
        "SHY": "short-duration US Treasuries",
        "GLD": "gold",
        "SLV": "silver",
        "DBC": "broad commodities",
        "BIL": "1-3 month T-bill, cash proxy",
        "VEA": "developed-market ex-US equity",
        "VWO": "emerging-market equity",
        "EFA": "developed-market ex-US equity, MSCI EAFE (older, more liquid alternative to VEA)",
        "BND": "broad US bond market, cap-weighted aggregate",
        "AGG": "broad US bond market, cap-weighted aggregate -- near-duplicate of BND by construction, kept to test that claim measurably",
    },
    "leveraged": {
        "QLD": "2x QQQ daily-reset -- note p.11's own named leveraged pick",
        "TQQQ": "3x QQQ daily-reset",
        "SOXL": "3x SOXX daily-reset",
        "SSO": "2x SPY daily-reset",
        "UPRO": "3x SPY daily-reset",
    },
    "singles": {
        # Selection rule, declared before fetching: the largest US-listed companies by well-known
        # mega-cap index membership (QQQ/SPY top holdings) as of this run date, by the analyst's own
        # general knowledge of index composition -- not fetched or verified against a live holdings
        # file. NVDA and AMZN were already cached; AAPL, MSFT, GOOGL, META and TSLA are added to give
        # the single-stock category more than two points, still modest. This selection is explicitly
        # a look at *today's* largest survivors -- see Part C.
        "NVDA": "mega-cap, cached",
        "AMZN": "mega-cap, cached",
        "AAPL": "mega-cap, added -- top index-weight name",
        "MSFT": "mega-cap, added -- top index-weight name",
        "GOOGL": "mega-cap, added -- top index-weight name",
        "META": "mega-cap, added -- top index-weight name",
        "TSLA": "mega-cap, added -- top index-weight name, notably higher-volatility than the other five",
    },
}

ALL_SYMBOLS: list[tuple[str, str, str]] = [
    (sym, cat, why) for cat, syms in CANDIDATES.items() for sym, why in syms.items()
]

MIN_BARS_FOR_STUDY = 1000  # brief's stated floor for supporting this study's holdout math at all
MIN_BARS_FOR_ANY_STAT = 260  # under ~1 trading year, even descriptive stats are not meaningful

TRAILING_3Y_START = (TODAY - dt.timedelta(days=3 * 365)).isoformat()
TRAILING_10Y_START = (TODAY - dt.timedelta(days=10 * 365)).isoformat()

DECAY_WINDOWS = [
    ("trailing_1y", (TODAY - dt.timedelta(days=365)).isoformat(), None),
    ("trailing_3y", TRAILING_3Y_START, None),
    ("trailing_5y", (TODAY - dt.timedelta(days=5 * 365)).isoformat(), None),
    ("since_inception", None, None),
]

LEVERAGED_MAP: dict[str, tuple[str, float]] = {
    "QLD": ("QQQ", 2.0),
    "TQQQ": ("QQQ", 3.0),
    "SOXL": ("SOXX", 3.0),
    "SSO": ("SPY", 2.0),
    "UPRO": ("SPY", 3.0),
}


# ---------------------------------------------------------------------------
# Helpers -- everything the app does not already provide, documented inline
# ---------------------------------------------------------------------------


def buy_hold_metrics(bars: pd.DataFrame) -> dict | None:
    """CAGR/vol/Sharpe/max-DD for a frictionless buy-and-hold over `bars`' exact window.

    Reuses `app.backtest.strategy._buy_hold` + `app.backtest.metrics.compute` via
    `quantlab.strategy_backtest`, rather than reimplementing those formulas. The dummy idea's entry
    ("close > 0", always true) and exit ("close < 0", never true) only exist to satisfy
    `StrategySpec`'s requirement of an exit or holding cap; the `strategy` half of the result is
    discarded, only `buy_hold` is used, and it is computed independently of the idea by the app.
    """
    if len(bars) < 2:
        return None
    idea = Idea(key="_bh_probe", entry="close > 0", exit="close < 0", horizon=1, direction="up")
    bt = strategy_backtest(bars, idea)
    return bt["buy_hold"] if bt else None


def pct_days_above_sma200(bars: pd.DataFrame) -> float | None:
    """Fraction of bars (after the 200-bar warmup) whose close is above the 200-day SMA."""
    close = bars["close"]
    sma200 = close.rolling(200, min_periods=200).mean()
    valid = sma200.notna()
    if valid.sum() == 0:
        return None
    return float((close[valid] > sma200[valid]).mean())


def atr_pct_series(bars: pd.DataFrame) -> pd.Series:
    """`atr(14) / close`, the identical ATR the rule DSL computes (`app.indicators.volatility.atr`)."""
    atr14 = atr_indicator(bars, period=14)["atr_14"]
    return atr14 / bars["close"]


def daily_log_returns(bars: pd.DataFrame) -> pd.Series:
    close = bars["close"]
    return np.log(close / close.shift(1)).dropna()


def realised_vol_20d(returns: pd.Series) -> pd.Series:
    """Rolling 20-trading-day annualised realised volatility of daily log returns."""
    return returns.rolling(20, min_periods=20).std(ddof=1) * np.sqrt(252)


def variance_ratio(returns: pd.Series, k: int) -> tuple[float | None, int]:
    """Var(k-day return) / (k * Var(1-day return)), on **non-overlapping** k-day blocks.

    Non-overlapping blocks are used deliberately over the more common overlapping-window estimator:
    overlapping k-day sums are themselves autocorrelated by construction (each pair of adjacent
    windows shares k-1 of k observations), which biases the variance-ratio statistic toward 1 and
    requires the Lo-MacKinlay heteroskedasticity-robust correction to interpret correctly. This
    script reports no p-value for the ratio -- it is a descriptive number, not a test -- and a plain
    non-overlapping block variance avoids the overlap bias at the cost of fewer blocks. Returns
    `(ratio, n_blocks)`; `n_blocks < 10` should be read as unreliable and is flagged as such in the
    output.
    """
    n = len(returns)
    n_blocks = n // k
    if n_blocks < 2:
        return None, n_blocks
    values = returns.to_numpy(dtype=float)[: n_blocks * k].reshape(n_blocks, k)
    block_sums = values.sum(axis=1)
    var_k = block_sums.var(ddof=1)
    var_1 = returns.var(ddof=1)
    if var_1 == 0 or np.isnan(var_1):
        return None, n_blocks
    return float(var_k / (k * var_1)), n_blocks


def long_horizon_character(symbol: str, bars: pd.DataFrame) -> dict:
    bh_full = buy_hold_metrics(bars)
    sub10 = slice_window(bars, first=TRAILING_10Y_START, last=None)
    bh_10y = buy_hold_metrics(sub10) if len(sub10) >= MIN_BARS_FOR_ANY_STAT else None
    dd = drawdown_profile(bars, top=5)
    worst = dd["episodes"][0] if dd["episodes"] else None
    recovery_days = None
    if worst and worst["recovery_date"]:
        recovery_days = (
            dt.date.fromisoformat(worst["recovery_date"]) - dt.date.fromisoformat(worst["trough_date"])
        ).days
    return {
        "cagr_full": bh_full["cagr"] if bh_full else None,
        "cagr_10y": bh_10y["cagr"] if bh_10y else None,
        "vol_full": bh_full["volatility"] if bh_full else None,
        "sharpe_full": bh_full["sharpe"] if bh_full else None,
        "max_dd_full": bh_full["max_drawdown"] if bh_full else None,
        "worst_episode": worst,
        "worst_episode_recovery_days": recovery_days,
        "current_drawdown": dd["current"],
        "pct_days_above_sma200": pct_days_above_sma200(bars),
        "bars_in_10y_slice": len(sub10),
    }


def swing_character(symbol: str, bars: pd.DataFrame) -> dict:
    atr_pct = atr_pct_series(bars)
    rets_full = daily_log_returns(bars)
    rv20_full = realised_vol_20d(rets_full)

    sub3y = slice_window(bars, first=TRAILING_3Y_START, last=None)
    rets_3y = daily_log_returns(sub3y) if len(sub3y) >= MIN_BARS_FOR_ANY_STAT else pd.Series(dtype=float)
    rv20_3y = realised_vol_20d(rets_3y) if len(rets_3y) else pd.Series(dtype=float)
    atr_pct_3y = atr_pct.tail(len(sub3y)) if len(sub3y) else pd.Series(dtype=float)

    vr5_full, vr5_full_n = variance_ratio(rets_full, 5)
    vr20_full, vr20_full_n = variance_ratio(rets_full, 20)
    vr5_3y, vr5_3y_n = variance_ratio(rets_3y, 5) if len(rets_3y) else (None, 0)
    vr20_3y, vr20_3y_n = variance_ratio(rets_3y, 20) if len(rets_3y) else (None, 0)

    return {
        "atr_pct_mean_full": float(atr_pct.dropna().mean()) if atr_pct.dropna().size else None,
        "atr_pct_mean_3y": float(atr_pct_3y.dropna().mean()) if atr_pct_3y.dropna().size else None,
        "realised_vol_20d_mean_full": float(rv20_full.dropna().mean()) if rv20_full.dropna().size else None,
        "realised_vol_20d_mean_3y": float(rv20_3y.dropna().mean()) if rv20_3y.dropna().size else None,
        "avg_abs_daily_move_full": float(rets_full.abs().mean()) if len(rets_full) else None,
        "avg_abs_daily_move_3y": float(rets_3y.abs().mean()) if len(rets_3y) else None,
        "autocorr_1d_full": float(rets_full.autocorr(lag=1)) if len(rets_full) > 2 else None,
        "autocorr_1d_3y": float(rets_3y.autocorr(lag=1)) if len(rets_3y) > 2 else None,
        "variance_ratio_5_full": vr5_full,
        "variance_ratio_5_full_nblocks": vr5_full_n,
        "variance_ratio_20_full": vr20_full,
        "variance_ratio_20_full_nblocks": vr20_full_n,
        "variance_ratio_5_3y": vr5_3y,
        "variance_ratio_5_3y_nblocks": vr5_3y_n,
        "variance_ratio_20_3y": vr20_3y,
        "variance_ratio_20_3y_nblocks": vr20_3y_n,
        "n_bars_3y_slice": len(sub3y),
    }


def total_return_over(bars: pd.DataFrame, first: str | None, last: str | None) -> tuple[float | None, str | None, str | None, int]:
    """Simple total return (last close / first close - 1) over a window, plus the dates actually used
    (a fund that IPO'd inside the requested window uses its own first bar, not the requested date)."""
    sub = slice_window(bars, first, last)
    if len(sub) < 2:
        return None, None, None, len(sub)
    first_close = float(sub["close"].iloc[0])
    last_close = float(sub["close"].iloc[-1])
    return (last_close / first_close - 1.0), str(sub["ts"].iloc[0].date()), str(sub["ts"].iloc[-1].date()), len(sub)


def leveraged_decay(symbol: str, bars: pd.DataFrame, underlying_bars: pd.DataFrame | None, factor: float) -> dict:
    """Realised leveraged-fund return vs `factor x` the underlying's, over the identical calendar
    window, for several windows plus the leveraged fund's own worst drawdown episode. A daily-reset
    product's multi-day return is path-dependent, so this gap is the measurable footprint of that --
    not an estimate, a direct comparison against the app's own bars for both instruments."""
    result: dict = {"factor": factor, "underlying": None, "windows": {}}
    if underlying_bars is None:
        return result
    result["underlying"] = True

    for label, first, last in DECAY_WINDOWS:
        lev_ret, lev_first, lev_last, lev_n = total_return_over(bars, first, last)
        if lev_ret is None:
            result["windows"][label] = {"skipped": f"only {lev_n} bars in window"}
            continue
        # Use the leveraged fund's *actual* realised window (lev_first..lev_last) to query the
        # underlying, so a fund that IPO'd after `first` is compared over dates it actually traded.
        und_ret, und_first, und_last, und_n = total_return_over(underlying_bars, lev_first, lev_last)
        if und_ret is None:
            result["windows"][label] = {"skipped": f"underlying has only {und_n} bars in the matched window"}
            continue
        result["windows"][label] = {
            "start": lev_first,
            "end": lev_last,
            "leveraged_return": lev_ret,
            "underlying_return": und_ret,
            "k_times_underlying": factor * und_ret,
            "gap_vs_k_times_underlying": lev_ret - factor * und_ret,
        }

    dd = drawdown_profile(bars, top=1)
    if dd["episodes"]:
        ep = dd["episodes"][0]
        lev_ret, lev_first, lev_last, lev_n = total_return_over(bars, ep["peak_date"], ep["trough_date"])
        und_ret, und_first, und_last, und_n = total_return_over(underlying_bars, ep["peak_date"], ep["trough_date"])
        result["worst_drawdown_episode"] = {
            "peak_date": ep["peak_date"],
            "trough_date": ep["trough_date"],
            "leveraged_depth_close_to_close": lev_ret,
            "leveraged_profile_depth": ep["depth"],
            "underlying_return_same_dates": und_ret,
            "k_times_underlying": (factor * und_ret) if und_ret is not None else None,
            "gap_vs_k_times_underlying": (lev_ret - factor * und_ret) if (lev_ret is not None and und_ret is not None) else None,
        }
    else:
        result["worst_drawdown_episode"] = None
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    resolved: dict[str, pd.DataFrame] = {}
    coverage: dict[str, dict] = {}
    refused: dict[str, dict] = {}

    print(f"=== Part A: fetching {len(ALL_SYMBOLS)} candidates ===")
    for sym, cat, why in ALL_SYMBOLS:
        try:
            bars = bars_frame(sym)
        except Exception as exc:
            refused[sym] = {"category": cat, "reason": why, "error": f"{type(exc).__name__}: {exc}"}
            print(f"{sym:<6} [{cat}] REFUSED -- {type(exc).__name__}: {exc}")
            continue
        if len(bars) == 0:
            refused[sym] = {"category": cat, "reason": why, "error": "no bars"}
            print(f"{sym:<6} [{cat}] REFUSED -- no bars")
            continue
        resolved[sym] = bars
        coverage[sym] = {
            "category": cat,
            "reason": why,
            "bars": len(bars),
            "first": str(bars["ts"].min().date()),
            "last": str(bars["ts"].max().date()),
            "below_study_floor": len(bars) < MIN_BARS_FOR_STUDY,
        }
        flag = " *** UNDER 1000 BARS ***" if len(bars) < MIN_BARS_FOR_STUDY else ""
        print(f"{sym:<6} [{cat}] {len(bars):>5} bars  {coverage[sym]['first']} -> {coverage[sym]['last']}{flag}")

    print(f"\n=== Part B: characterisation for {len(resolved)} resolved symbols ===")
    long_char: dict[str, dict] = {}
    swing_char: dict[str, dict] = {}
    for sym, bars in resolved.items():
        if len(bars) < MIN_BARS_FOR_ANY_STAT:
            print(f"{sym}: only {len(bars)} bars -- below {MIN_BARS_FOR_ANY_STAT}, skipping characterisation")
            continue
        long_char[sym] = long_horizon_character(sym, bars)
        swing_char[sym] = swing_character(sym, bars)
        print(f"{sym}: characterised")

    print("\n=== Correlation matrix, trailing 3y daily log returns ===")
    ret_frames = {}
    for sym, bars in resolved.items():
        sub = slice_window(bars, first=TRAILING_3Y_START, last=None)
        if len(sub) < MIN_BARS_FOR_ANY_STAT:
            continue
        r = daily_log_returns(sub)
        r.index = sub["ts"].iloc[1:].dt.date.values
        ret_frames[sym] = r
    ret_df = pd.DataFrame(ret_frames)
    corr = ret_df.corr(min_periods=200)
    print(f"correlation matrix: {corr.shape[0]} symbols, {ret_df.shape[0]} calendar rows before pairwise dropna")

    # Near-duplicate pairs: |corr| > 0.90, excluding self-pairs, each pair once.
    near_dupes = []
    cols = list(corr.columns)
    for i, a in enumerate(cols):
        for b in cols[i + 1 :]:
            c = corr.loc[a, b]
            if pd.notna(c) and abs(c) > 0.90:
                near_dupes.append({"a": a, "b": b, "corr": float(c)})
    near_dupes.sort(key=lambda d: -abs(d["corr"]))
    print(f"{len(near_dupes)} pairs with |corr| > 0.90 (trailing 3y)")
    for d in near_dupes[:25]:
        print(f"  {d['a']:<6} {d['b']:<6} {d['corr']:+.3f}")

    print("\n=== Part C: leveraged-decay quantification ===")
    decay: dict[str, dict] = {}
    for sym, (underlying_sym, factor) in LEVERAGED_MAP.items():
        if sym not in resolved:
            decay[sym] = {"skipped": "symbol not resolved"}
            continue
        underlying_bars = resolved.get(underlying_sym)
        decay[sym] = leveraged_decay(sym, resolved[sym], underlying_bars, factor)
        decay[sym]["in_app_registry"] = instruments_mod.lookup(sym) is not None
        decay[sym]["app_registry_underlying"] = instruments_mod.unlevered_for(sym)
        w = decay[sym]["windows"].get("trailing_3y", {})
        gap = w.get("gap_vs_k_times_underlying")
        print(
            f"{sym} ({factor}x {underlying_sym}) trailing_3y gap vs {factor}x underlying: "
            f"{'n/a' if gap is None else f'{gap:+.3f}'}  in_app_registry={decay[sym]['in_app_registry']}"
        )

    result = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "today": TODAY.isoformat(),
        "candidates_declared": CANDIDATES,
        "min_bars_for_study": MIN_BARS_FOR_STUDY,
        "min_bars_for_any_stat": MIN_BARS_FOR_ANY_STAT,
        "coverage": coverage,
        "refused": refused,
        "long_horizon_character": long_char,
        "swing_character": swing_char,
        "correlation_matrix_3y": corr.round(4).to_dict(),
        "correlation_n_rows": int(ret_df.shape[0]),
        "near_duplicate_pairs_3y": near_dupes,
        "leveraged_decay": decay,
    }
    write(result, "universe")

    print(f"\nresolved: {len(resolved)}   refused: {len(refused)}   total candidates: {len(ALL_SYMBOLS)}")


if __name__ == "__main__":
    main()

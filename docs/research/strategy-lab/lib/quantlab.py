"""Shared harness for the 2026-08-11 strategy-lab study. One implementation of the mechanics, so
five analysts working in parallel cannot each invent a subtly different notion of "hit rate",
"baseline", or "vs buy-and-hold".

**This module adds no statistics of its own.** Every number it reports comes out of the application:
`app.backtest.events.event_study` (hit rate, baseline, independent sample), `app.backtest.scan`
(exact binomial p, Benjamini-Hochberg), `app.backtest.guards.check` (lookahead proof),
`app.backtest.strategy.backtest` (fills, frictions, buy-and-hold), `app.backtest.drawdown.profile`.
It is glue and bookkeeping. If a number here disagrees with the app, the app is right.

**The correction family is declared before anything runs.** `run_family` takes the complete list of
ideas and the complete list of symbols up front, and Benjamini-Hochberg is applied across
`len(ideas) x len(symbols)` primary tests -- one test per idea per symbol, at that idea's own
pre-declared horizon. Adding an idea after seeing a result means re-running the whole family with a
larger `m`; there is no way to sneak one in, because nothing is corrected until every cell is
computed.

**The all-horizon table is a separate, separately-corrected family**, and it is exploratory. Testing
one rule at five horizons and reporting the best is the search this whole package exists to catch;
`horizon_sweep` exists only to answer "what did the other horizons show" and its q-values live in
their own ledger.

**Read-only with respect to production state.** Bars come from `app.market.store.ensure_series`
against the production cache -- the same call the chart endpoint makes. Nothing here writes a run
card, touches `thesis.sqlite`, or spends a ticker's one out-of-sample holdout look. Analysts who
want the pre-registered thesis loop must construct their own isolated `Settings(store_dir=<temp>)`;
this module deliberately gives them no shortcut for doing it against production.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Sequence

# docs/research/strategy-lab/lib/quantlab.py -> lib -> strategy-lab -> research -> docs -> <repo root>
REPO = Path(__file__).resolve().parents[4]
if str(REPO / "backend") not in sys.path:
    sys.path.insert(0, str(REPO / "backend"))

import pandas as pd  # noqa: E402

from app.backtest import drawdown as drawdown_mod  # noqa: E402
from app.backtest import events as events_mod  # noqa: E402
from app.backtest import guards as guards_mod  # noqa: E402
from app.backtest import scan as scan_mod  # noqa: E402
from app.backtest import strategy as strategy_mod  # noqa: E402
from app.backtest.models import (  # noqa: E402
    SMALL_SAMPLE_THRESHOLD,
    STUDY_HORIZONS,
    Costs,
    DrawdownBasis,
    Entry,
    ExitReason,
    GuardStatus,
    StrategySpec,
)
from app.config import Settings  # noqa: E402
from app.db.duck import Interval  # noqa: E402
from app.market import store  # noqa: E402

__all__ = [
    "Idea",
    "LAB",
    "SCREEN_ALPHA",
    "bars_frame",
    "drawdown_profile",
    "horizon_sweep",
    "run_family",
    "slice_window",
    "strategy_backtest",
    "write",
]

LAB = REPO / "docs" / "research" / "strategy-lab"
PROD = Settings()

#: The screening bar for a corrected q-value. Matches `app.thesis.loop`'s own screen.
SCREEN_ALPHA = 0.10

Direction = Literal["up", "down"]


@dataclass(frozen=True)
class Idea:
    """One pre-registered hypothesis. Every field except `key`/`rationale`/`falsifies_if` feeds the
    machinery; those three exist so the report can say what was claimed, not just what was measured.

    `horizon` is the *one* forward horizon this idea is judged at. `direction` is checked as well as
    magnitude: an edge that runs the wrong way is `rejected`, not `inconclusive` -- the same
    distinction `app.thesis.loop` draws.
    """

    key: str
    entry: str
    horizon: int
    direction: Direction = "up"
    exit: str | None = None
    max_holding_bars: int | None = None
    stop_loss_pct: float | None = None
    rationale: str = ""
    falsifies_if: str = ""
    #: Free-text pointer back to the source note section this encodes, e.g. "p.4 Ideal Entry setup".
    source: str = ""


# ---------------------------------------------------------------------------
# Bars
# ---------------------------------------------------------------------------


def bars_frame(symbol: str, interval: Interval = Interval.DAY) -> pd.DataFrame:
    """Daily bars for `symbol` from the production cache, as the frame every app function wants.

    Raises whatever the provider registry raises -- `SymbolNotFoundWithContext` for a ticker with no
    chart data is a finding to report verbatim, not an error to swallow.
    """
    series = store.ensure_series(symbol, interval, settings=PROD)
    return pd.DataFrame(
        {
            "ts": pd.Series([b.ts for b in series.bars], dtype="datetime64[ns, UTC]"),
            **{
                column: pd.Series([getattr(b, column) for b in series.bars], dtype="float64")
                for column in ("open", "high", "low", "close", "adj_close", "volume")
            },
        }
    )


def slice_window(bars: pd.DataFrame, first: str | None = None, last: str | None = None) -> pd.DataFrame:
    """`bars` restricted to `[first, last]` (ISO dates, inclusive), index reset.

    **DEFECT -- do not use this for regime windows. Use `meta/regime_windows_corrected.py`.**

    This function hands the engine a bare slice, so every indicator is recomputed from bar 0 *of the
    slice*. The original docstring called that deliberate -- "a regime window must be a
    self-contained backtest, not a view onto indicators seeded by data the window excludes" -- which
    sounds principled and is wrong in consequence: an `sma(200)` rule inside a 253-bar window is
    blind for the first 200 of those bars, so it is not tested on that window at all, only on its
    tail.

    Measured, not argued: SPY was genuinely below its 200-day SMA for **84.9%** of 2022 (from
    Jan 21); the sliced recomputation sees it only from Oct 18, **19.5%** -- and 0.195 is exactly the
    `exposure` this harness recorded. In the 2007-09 window the same mechanism pinned exposure at
    43.7% (155 of 355 bars) regardless of the actual regime, and inflated the study's "never traded"
    count from a true 18 cells to 41.

    Found by the QA reviewer, after four streams had already shipped regime tables built on it.
    Every one of those tables is superseded by `data/regime_windows_corrected.json`, which seeds
    `WARMUP_BARS` of history before the window opens, then measures only the window.

    No p-value, q-value or verdict in this study is affected: regime windows are descriptive
    mechanics, excluded from every correction family by design, and the primary statistics were
    always computed on full unsliced history. Kept here, unfixed, because the shipped stream JSONs
    were produced by this exact code and silently changing it would leave those files unexplainable.
    """
    out = bars
    if first is not None:
        out = out[out["ts"] >= pd.Timestamp(first, tz="UTC")]
    if last is not None:
        out = out[out["ts"] <= pd.Timestamp(last, tz="UTC")]
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------


def guard(expression: str, bars: pd.DataFrame, interval: Interval = Interval.DAY) -> dict[str, Any]:
    """Lookahead proof for one expression. `UNVERIFIED` is a failure, not a shrug."""
    report = guards_mod.check(expression, bars, interval=interval)
    return {
        "status": report.status.value,
        "passed": report.status is GuardStatus.PASSED,
        "findings": [f.detail for f in report.findings],
    }


# ---------------------------------------------------------------------------
# Event statistics
# ---------------------------------------------------------------------------


def _stats_at(arm, horizon: int) -> Any:
    for s in arm.stats:
        if s.horizon == horizon:
            return s
    return None


def _p_value(hit: float | None, baseline: float | None, n_indep: int) -> float | None:
    """Exact two-sided binomial p for `hit` over `n_indep` independent windows against `baseline`.

    The `round(rate * n)` reconstruction is the app's own convention (`app.thesis.loop`), used here
    for the same reason: `event_study` reports a rate and a count, not a raw success count.
    """
    if hit is None or baseline is None or n_indep <= 0:
        return None
    successes = int(round(hit * n_indep))
    successes = max(0, min(successes, n_indep))
    return scan_mod.binomial_p_value(successes, n_indep, baseline)


def _verdict(edge: float | None, q: float | None, n_indep: int, direction: Direction) -> str:
    """`survived` | `rejected` | `inconclusive` | `underpowered` | `untestable`.

    Direction is checked before significance: an edge pointing the wrong way is a rejection of the
    hypothesis as written, regardless of how large it is.
    """
    if edge is None or q is None:
        return "untestable"
    wrong_way = (direction == "up" and edge < 0) or (direction == "down" and edge > 0)
    if wrong_way:
        return "rejected"
    if n_indep < SMALL_SAMPLE_THRESHOLD:
        return "underpowered"
    return "survived" if q <= SCREEN_ALPHA else "inconclusive"


# ---------------------------------------------------------------------------
# Strategy backtest
# ---------------------------------------------------------------------------


def _metrics_dict(m) -> dict[str, Any]:
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


def strategy_backtest(
    bars: pd.DataFrame,
    idea: Idea,
    *,
    interval: Interval = Interval.DAY,
    costs: Costs | None = None,
) -> dict[str, Any] | None:
    """`app.backtest.strategy.backtest` for `idea`, against buy-and-hold on the identical window.

    Returns `None` (with a `skipped` reason folded in by the caller) when the idea declares neither
    an exit nor a holding cap -- the engine raises there, on purpose, because such a "strategy" is
    buy-and-hold with worse fills.
    """
    if idea.exit is None and idea.max_holding_bars is None:
        return None
    costs = costs or Costs()
    spec = StrategySpec(
        entry=idea.entry,
        exit=idea.exit,
        max_holding_bars=idea.max_holding_bars,
        stop_loss_pct=idea.stop_loss_pct,
    )
    m, bh, trades, equity, cost_drag, open_trades = strategy_mod.backtest(
        bars, spec, interval=interval, costs=costs
    )
    closed = [t for t in trades if not t.open_at_end]
    returns = [t.return_pct for t in closed]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = sum(losses) / len(losses) if losses else None
    profit_factor = (
        (sum(wins) / abs(sum(losses))) if wins and losses and sum(losses) != 0 else None
    )
    return {
        "spec": {
            "entry": spec.entry,
            "exit": spec.exit,
            "max_holding_bars": spec.max_holding_bars,
            "stop_loss_pct": spec.stop_loss_pct,
        },
        "costs": {
            "slippage_bps": costs.slippage_bps,
            "commission_per_trade": costs.commission_per_trade,
            "notional": costs.notional,
        },
        "strategy": _metrics_dict(m),
        "buy_hold": _metrics_dict(bh),
        "beats_buy_hold_total_return": (
            None
            if m.total_return is None or bh.total_return is None
            else m.total_return > bh.total_return
        ),
        "beats_buy_hold_sharpe": (
            None if m.sharpe is None or bh.sharpe is None else m.sharpe > bh.sharpe
        ),
        "cost_drag": cost_drag,
        "closed_trades": len(closed),
        "open_trades": open_trades,
        "wins": len(wins),
        "losses": len(losses),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "best_trade": max(returns, default=None),
        "worst_trade": min(returns, default=None),
        "avg_bars_held": (sum(t.bars_held for t in closed) / len(closed)) if closed else None,
        "exit_reason_counts": {
            r.value: sum(1 for t in closed if t.exit_reason == r) for r in ExitReason
        },
        "final_equity": equity[-1].equity if equity else None,
        "final_buy_hold": equity[-1].buy_hold if equity else None,
    }


def drawdown_profile(bars: pd.DataFrame, top: int = 5) -> dict[str, Any]:
    """Descriptive buy-and-hold drawdown context. No hypothesis, so no baseline and no correction."""
    episodes, current, considered = drawdown_mod.profile(bars, basis=DrawdownBasis.CLOSE, top=top)
    return {
        "episodes": [
            {
                "peak_date": str(e.peak_date),
                "trough_date": str(e.trough_date),
                "depth": e.depth,
                "bars_to_trough": e.bars_to_trough,
                "recovery_date": str(e.recovery_date) if e.recovery_date else None,
                "still_underwater": e.still_underwater,
            }
            for e in episodes
        ],
        "current": (
            {
                "peak_date": str(current.peak_date),
                "depth": current.depth,
                "bars_underwater": current.bars_underwater,
            }
            if current
            else None
        ),
        "episodes_considered": considered,
    }


# ---------------------------------------------------------------------------
# The family runner
# ---------------------------------------------------------------------------


def run_family(
    ideas: Sequence[Idea],
    symbols: Sequence[str],
    *,
    family: str,
    interval: Interval = Interval.DAY,
    costs: Costs | None = None,
    windows: Sequence[tuple[str, str | None, str | None]] = (),
    verbose: bool = True,
) -> dict[str, Any]:
    """Run the complete pre-declared family and Benjamini-Hochberg it as one ledger.

    `windows` is an optional list of `(label, first_iso, last_iso)` regime slices. Window results are
    **strategy mechanics only** -- deliberately no p-values, because slicing the same history five
    ways and testing each slice multiplies the family by five for no new information. Windows answer
    "was the aggregate dragged around by one episode", which is a description, not a test.

    Returns the full result dict; also usable via `write(result, name)`.
    """
    costs = costs or Costs()
    started = dt.datetime.now(dt.UTC)

    cells: list[dict[str, Any]] = []
    per_symbol: dict[str, Any] = {}

    for symbol in symbols:
        try:
            bars = bars_frame(symbol, interval)
        except Exception as exc:  # a data-existence refusal is a finding, reported verbatim
            per_symbol[symbol] = {"error": f"{type(exc).__name__}: {exc}"}
            if verbose:
                print(f"{symbol}: DATA REFUSAL -- {type(exc).__name__}: {exc}")
            continue

        if len(bars) == 0:
            per_symbol[symbol] = {"error": "no bars"}
            continue

        coverage = {
            "bars": len(bars),
            "first": str(bars["ts"].min().date()),
            "last": str(bars["ts"].max().date()),
        }
        if verbose:
            print(f"\n=== {symbol}: {coverage['bars']} bars, {coverage['first']} -> {coverage['last']}")

        arms, _ = events_mod.event_study(
            bars,
            [i.entry for i in ideas],
            interval=interval,
            horizons=tuple(sorted({i.horizon for i in ideas} | set(STUDY_HORIZONS))),
            entry=Entry.NEXT_OPEN,
        )
        by_expr = {a.expression: a for a in arms}

        sym_ideas: dict[str, Any] = {}
        for idea in ideas:
            arm = by_expr.get(idea.entry)
            g_entry = guard(idea.entry, bars, interval)
            g_exit = guard(idea.exit, bars, interval) if idea.exit else None
            st = _stats_at(arm, idea.horizon) if arm else None

            hit = st.hit_rate if st else None
            base = st.baseline_hit_rate if st else None
            n_raw = st.sample_size if st else 0
            n_indep = st.independent_sample_size if st else 0
            edge = None if hit is None or base is None else hit - base
            p = _p_value(hit, base, n_indep)

            cell = {
                "symbol": symbol,
                "idea": idea.key,
                "horizon": idea.horizon,
                "direction": idea.direction,
                "hit_rate": hit,
                "baseline": base,
                "edge": edge,
                "n_raw": n_raw,
                "n_independent": n_indep,
                "p_value": p,
                "triggers": arm.triggers if arm else 0,
                "evaluable_bars": arm.evaluable_bars if arm else 0,
                "guard_entry": g_entry,
                "guard_exit": g_exit,
                "median_forward": st.distribution.median if st and st.distribution else None,
                "baseline_median_forward": (
                    st.baseline_distribution.median if st and st.baseline_distribution else None
                ),
            }
            cells.append(cell)

            bt = strategy_backtest(bars, idea, interval=interval, costs=costs)
            window_results = {}
            for label, first, last in windows:
                sub = slice_window(bars, first, last)
                if len(sub) < 250:
                    window_results[label] = {"skipped": f"only {len(sub)} bars"}
                    continue
                window_results[label] = strategy_backtest(sub, idea, interval=interval, costs=costs) or {
                    "skipped": "no exit and no max_holding_bars"
                }

            sym_ideas[idea.key] = {
                "declared": asdict(idea),
                "event": cell,
                "strategy": bt if bt is not None else {"skipped": "no exit and no max_holding_bars"},
                "windows": window_results,
            }
            if verbose:
                e = "n/a" if edge is None else f"{edge:+.3f}"
                pp = "n/a" if p is None else f"{p:.4f}"
                bhline = ""
                if bt:
                    bhline = (
                        f" | strat tr={bt['strategy']['total_return']:.3f}"
                        f" bh={bt['buy_hold']['total_return']:.3f}"
                        f" sharpe={bt['strategy']['sharpe']} dd={bt['strategy']['max_drawdown']}"
                    )
                print(
                    f"  {idea.key:<28} h={idea.horizon:<3} edge={e} n_ind={n_indep:<5} p={pp}"
                    f" guard={g_entry['status']}{bhline}"
                )

        per_symbol[symbol] = {
            "coverage": coverage,
            "ideas": sym_ideas,
            "buy_hold_drawdown": drawdown_profile(bars),
        }

    # --- one Benjamini-Hochberg ledger across the whole declared family -------------------
    q_values = scan_mod.benjamini_hochberg([c["p_value"] for c in cells])
    for cell, q in zip(cells, q_values, strict=True):
        cell["q_value"] = q
        idea = next(i for i in ideas if i.key == cell["idea"])
        cell["verdict"] = _verdict(cell["edge"], q, cell["n_independent"], idea.direction)
        sym = per_symbol.get(cell["symbol"], {})
        if "ideas" in sym:
            sym["ideas"][cell["idea"]]["event"] = cell

    survivors = [c for c in cells if c["verdict"] == "survived"]
    if verbose:
        print(
            f"\n### family '{family}': {len(cells)} primary tests "
            f"({len(ideas)} ideas x {len(symbols)} symbols), BH alpha={SCREEN_ALPHA} -> "
            f"{len(survivors)} survivor(s)"
        )
        for s in survivors:
            print(f"    SURVIVED: {s['symbol']}/{s['idea']} edge={s['edge']:+.3f} q={s['q_value']:.4f}")

    return {
        "family": family,
        "generated_at": started.isoformat(),
        "interval": interval.value,
        "screen_alpha": SCREEN_ALPHA,
        "small_sample_threshold": SMALL_SAMPLE_THRESHOLD,
        "costs": {
            "slippage_bps": costs.slippage_bps,
            "commission_per_trade": costs.commission_per_trade,
            "notional": costs.notional,
        },
        "family_size": len(cells),
        "ideas_declared": [asdict(i) for i in ideas],
        "symbols_declared": list(symbols),
        "windows_declared": [list(w) for w in windows],
        "cells": cells,
        "survivors": survivors,
        "per_symbol": per_symbol,
    }


def horizon_sweep(
    expressions: Sequence[str],
    symbols: Sequence[str],
    *,
    family: str,
    horizons: Sequence[int] = STUDY_HORIZONS,
    interval: Interval = Interval.DAY,
    verbose: bool = True,
) -> dict[str, Any]:
    """Exploratory: every expression at every horizon, corrected in its own separate BH ledger.

    Descriptive only. Reading the best horizon off this table and reporting it as a finding is the
    exact error the primary family's single pre-declared horizon exists to prevent.
    """
    cells: list[dict[str, Any]] = []
    for symbol in symbols:
        try:
            bars = bars_frame(symbol, interval)
        except Exception as exc:
            cells.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})
            continue
        arms, _ = events_mod.event_study(
            bars, list(expressions), interval=interval, horizons=tuple(horizons), entry=Entry.NEXT_OPEN
        )
        for arm in arms:
            for h in horizons:
                st = _stats_at(arm, h)
                hit = st.hit_rate if st else None
                base = st.baseline_hit_rate if st else None
                n = st.independent_sample_size if st else 0
                cells.append(
                    {
                        "symbol": symbol,
                        "expression": arm.expression,
                        "horizon": h,
                        "hit_rate": hit,
                        "baseline": base,
                        "edge": None if hit is None or base is None else hit - base,
                        "n_independent": n,
                        "p_value": _p_value(hit, base, n),
                    }
                )
    q = scan_mod.benjamini_hochberg([c.get("p_value") for c in cells])
    for c, qq in zip(cells, q, strict=True):
        c["q_value"] = qq
    discoveries = [c for c in cells if c.get("q_value") is not None and c["q_value"] <= SCREEN_ALPHA]
    if verbose:
        print(
            f"\n### exploratory sweep '{family}': {len(cells)} trials, "
            f"{len(discoveries)} at q<={SCREEN_ALPHA}"
        )
    return {
        "family": family,
        "exploratory": True,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "horizons": list(horizons),
        "expressions": list(expressions),
        "symbols": list(symbols),
        "family_size": len(cells),
        "cells": cells,
        "discoveries": discoveries,
    }


def write(result: dict[str, Any], name: str) -> Path:
    """Dump `result` to `docs/research/strategy-lab/data/<name>.json` and return the path."""
    path = LAB / "data" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"wrote {path}")
    return path

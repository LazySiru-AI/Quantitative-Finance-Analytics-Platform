"""The eight frozen Round 33 ticker-selection entrants, and the Phase A selector framework.

**What this module is.** `strategy-program/ROUND-33-PLAN.md` §3 pre-registers eight deterministic,
$0 selectors that compete to point the Agent Workflow desk's paid research spend at a shortlist
instead of a static, hand-authored `card.universe`. §0 recon correction 1 records that none of this
existed before this round: `app.discovery.selector.select` is stateless and unconditional (one
`rank_key`, one `top_n`, no regime input, no hysteresis), so six of the eight entrants need net-new
gate/rank/hysteresis logic layered on top of it. This module is that layer.

**The one public entry point.** :func:`select_for_workflow` takes a selector id, a decision date, a
regime label, and yesterday's shortlist, and returns today's frozen shortlist. It is a pure function:
given the same stored bars and the same `prior_picks`, it returns the same answer every time (see
`ROUND-33-PLAN.md` §9 -- "this round's in-sample and held-out numbers are each one measurement, taken
once"). Nothing here reads past `as_of`; every price read routes through
:class:`~app.paper.marketdata.AsOfMarket`, exactly the guarantee `app.discovery.selector` already
gives and this module inherits by using it directly rather than re-deriving its own bar access.

**Regime label is an input, never a computation.** The four labels
(`risk_on_trend`, `risk_off`, `choppy_neutral`, `high_vol_stress`) come from whatever the caller's
own `app.workflow.regime.classify()` (or, for a historical replay, `ROUND-33-PLAN.md` §5's frozen
reconstruction) decided *before* calling this module. Nothing here imports that classifier or reads
macro/CNN data -- doing so here would make this module's own tests depend on a live or reconstructed
signal that has nothing to do with what a selector does with a label once it is handed one.

**Statelessness, and the one place it is deliberately approximate.** `prior_picks` -- yesterday's
shortlist, and nothing more -- is the *only* state this module carries across decision dates; there
is no module-level mutable state (`Stateful WeightFn closures leak across windows` is exactly the
failure mode this design avoids). For five of the six non-control entrants that is sufficient: a
"held" set plus a fresh recomputation from `as_of` is all their frozen rules need. `breakout_atr`'s
10-trading-session cooldown is the one exception -- see :func:`_recent_gate_pass_within`'s docstring
for the honest limitation that follows from only ever being handed one prior day's shortlist.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Final

import pandas as pd

from app.config import Settings
from app.discovery.candidates import CandidateSet, sector_candidates, theme_candidates
from app.discovery.selector import _series, _trend, select
from app.indicators.momentum import rsi as rsi_indicator
from app.indicators.volatility import atr as atr_indicator
from app.indicators.volatility import bollinger
from app.market.models import Interval
from app.paper.marketdata import AsOfMarket
from app.rules.catalog import catalog as rule_catalog
from app.rules.evaluate import RuleEvaluationError, evaluate
from app.rules.grammar import parse as parse_rule

__all__ = ["SELECTOR_IDS", "select_for_workflow"]

#: The eight frozen entrants, `ROUND-33-PLAN.md` §3/§8. Order matches the plan's own tie-break
#: sequence (§7) so a caller that needs that ordering does not have to re-derive it.
SELECTOR_IDS: tuple[str, ...] = (
    "mom12_1_hysteresis",
    "breakout_atr",
    "meanrev_rsi",
    "trend_sticky",
    "signal_density",
    "divers_mom6",
    "control_card_universe",
    "control_week_rotation",
)

#: The closed set of regime labels this module accepts -- `app.workflow.regime.RegimeLabel`,
#: restated here (not imported) so this package never depends on `app.workflow` at all. Verified
#: closed: no fifth label exists anywhere in the codebase (`ROUND-33-PLAN.md` §4).
_REGIME_LABELS: Final[tuple[str, ...]] = (
    "risk_on_trend",
    "risk_off",
    "choppy_neutral",
    "high_vol_stress",
)


# ---------------------------------------------------------------------------
# Candidate-pool wiring -- ROUND-33-PLAN.md §4
# ---------------------------------------------------------------------------


def _pool_for(selector_id: str, regime_label: str, *, settings: Settings) -> CandidateSet | None:
    """The candidate pool for entrants 1-5, per the §4 table.

    Every one of `mom12_1_hysteresis`, `breakout_atr`, `meanrev_rsi`, `trend_sticky` and
    `signal_density` shares the identical rule: theme roster in `risk_on_trend`, sector roster in
    every defensive label. `meanrev_rsi` additionally switches off entirely (`None`, meaning "no
    pool, empty shortlist") in `risk_on_trend` -- §3 entrant 3 is explicit that this is a hard off
    switch, not a deprioritisation. `divers_mom6` and the two controls do not go through this
    function at all; their pool wiring is fixed and entrant-specific (§3 entrants 6-8).
    """
    if regime_label not in _REGIME_LABELS:
        raise ValueError(f"unknown regime_label {regime_label!r}; known labels are {_REGIME_LABELS}")
    if selector_id == "meanrev_rsi" and regime_label == "risk_on_trend":
        return None
    return theme_candidates(settings) if regime_label == "risk_on_trend" else sector_candidates(settings)


def _full_rank_order(
    as_of: dt.date, pool: CandidateSet | None, settings: Settings, *, rank_key: str, collapse: bool
) -> tuple[str, ...]:
    """Every scoreable, (optionally) collapsed candidate in `pool`, best-ranked first.

    `select()`'s own `top_n` only truncates its `picks`; asking for `top_n=len(symbols)` -- the
    largest a rank order could possibly be -- is what turns that truncation into "give me the whole
    order back", without this module re-deriving `select()`'s scoring or its collapse logic.
    """
    if pool is None:
        return ()
    symbols = pool.symbols_as_of(as_of)
    if not symbols:
        return ()
    selection = select(
        as_of,
        candidates=pool,
        settings=settings,
        rank_key=rank_key,
        top_n=len(symbols),
        collapse=collapse,
    )
    return selection.picks


def _spy_above_sma200(as_of: dt.date, settings: Settings) -> bool:
    """`close(SPY) > SMA(200)(SPY)` at `as_of` -- entrant 1's `risk_off` confirmation, §3.

    "The market" in §3's `risk_off` row is read as the broad market benchmark the rest of this
    programme already uses for exactly this kind of trend confirmation (`app.workflow.regime`'s own
    `spy_trend` signal), not the candidate being ranked. `ROUND-33-PLAN.md` does not spell out which
    reading it means; this is the interpretation this module ships, recorded here rather than left
    implicit -- see the report accompanying this change for the alternative that was rejected.
    """
    market = AsOfMarket(as_of=as_of, settings=settings)
    trend = _trend(_series(market, "SPY"))
    return trend is not None and trend > 0.0


# ---------------------------------------------------------------------------
# Entrant 1 -- mom12_1_hysteresis
# ---------------------------------------------------------------------------


def _mom12_1_top_n(regime_label: str, *, as_of: dt.date, settings: Settings) -> int:
    if regime_label == "risk_on_trend":
        return 3
    if regime_label == "choppy_neutral":
        return 2
    if regime_label == "risk_off":
        return 1 if _spy_above_sma200(as_of, settings) else 0
    return 0  # high_vol_stress


def _select_mom12_1_hysteresis(
    as_of: dt.date,
    regime_label: str,
    settings: Settings,
    prior_picks: tuple[str, ...],
    *,
    top_n_override: int | None = None,
) -> tuple[str, ...]:
    pool = _pool_for("mom12_1_hysteresis", regime_label, settings=settings)
    full = _full_rank_order(as_of, pool, settings, rank_key="mom12_1", collapse=True)
    if not full:
        return ()
    rank_of = {symbol: i + 1 for i, symbol in enumerate(full)}

    # Frozen per-regime top_n unless the caller widens it (a LIVE operational override -- Phase A's
    # bake-off never passes one, so its graded results are unchanged). The regime *gating* is preserved:
    # a regime the frozen selector sits out (top_n 0 -- high_vol_stress, and risk_off below SMA200)
    # stays sat out even under an override; the override only widens the regimes it already trades.
    base = _mom12_1_top_n(regime_label, as_of=as_of, settings=settings)
    top_n = base if base == 0 else (top_n_override if top_n_override is not None else base)

    # Hysteresis bands scale with top_n so the sticky-incumbent / clear-challenger character is
    # preserved at any width. At the frozen top_n=3 these are exactly 5 and 2 (the original constants),
    # so an un-widened call is byte-for-byte the frozen selector.
    exit_band = top_n + 2
    entry_band = max(1, top_n - 1)

    if not prior_picks:
        # Rule 5: no incumbents yet, no entry-band gate to fill against.
        return full[:top_n]

    # Rules 2-3: keep anything still ranked within the exit band, regardless of today's top_n.
    held = [s for s in prior_picks if rank_of.get(s) is not None and rank_of[s] <= exit_band]
    held_set = set(held)

    # Rule 4: fill any slot top_n leaves empty with the best not-held challenger inside the entry band.
    fill_n = max(0, top_n - len(held))
    if fill_n:
        fresh = [s for s in full if s not in held_set and rank_of[s] <= entry_band]
        held.extend(fresh[:fill_n])

    return tuple(sorted(held, key=lambda s: rank_of[s]))


# ---------------------------------------------------------------------------
# Entrant 2 -- breakout_atr
# ---------------------------------------------------------------------------

_BREAKOUT_TOP_N: Final[dict[str, int]] = {
    "high_vol_stress": 3,
    "choppy_neutral": 3,
    "risk_on_trend": 1,
    "risk_off": 0,
}
_BREAKOUT_COOLDOWN_SESSIONS: Final[int] = 10


def _breakout_metrics(bars: pd.DataFrame) -> tuple[bool, float | None]:
    """`(passes_gate, atr_expansion_ratio)` on the last bar of `bars`.

    `bars` must already be clamped to some `as_of` (a caller-sliced prefix of an `AsOfMarket` frame
    is fine, and is exactly what :func:`_recent_gate_pass_within` passes) -- nothing here reads past
    the last row it is given.
    """
    close = bars["close"].astype("float64").reset_index(drop=True)
    if len(close) < 252 or float(close.iloc[-252:].max()) <= 0.0:
        return False, None
    last_close = float(close.iloc[-1])
    rolling_max = float(close.iloc[-252:].max())
    near_high = (last_close / rolling_max - 1.0) >= -0.02

    atr_col = atr_indicator(bars, period=14).iloc[:, 0].reset_index(drop=True)
    atr_mean60 = atr_col.rolling(60, min_periods=60).mean()
    last_atr = atr_col.iloc[-1] if len(atr_col) else float("nan")
    last_mean = atr_mean60.iloc[-1] if len(atr_mean60) else float("nan")
    if pd.isna(last_atr) or pd.isna(last_mean) or last_mean == 0.0:
        return False, None
    expansion = float(last_atr / last_mean - 1.0)
    return bool(near_high and expansion >= 0.25), expansion


def _recent_gate_pass_within(bars: pd.DataFrame, *, lookback: int) -> bool:
    """Did `breakout_atr`'s gate pass on any of the last `lookback` sessions in `bars`?

    **The honest limitation this function exists to contain.** §3 entrant 2's cooldown is a true
    state machine: once a symbol is added, hold it for exactly 10 sessions *regardless of the gate*,
    then re-evaluate; once dropped, refuse re-entry for 10 sessions *regardless of the gate*. The
    pinned interface's only cross-call memory is `prior_picks` -- yesterday's shortlist, one day deep
    -- which cannot recover an exact entry date or a drop date on its own.

    What *is* recoverable from `as_of` and the stored bars alone, with no dependency on `prior_picks`
    beyond "was this symbol held yesterday": whether the gate passed recently. This function re-runs
    :func:`_breakout_metrics` over each of the trailing `lookback` sessions already present in `bars`
    (each restricted to its own prefix -- still strictly point-in-time, since `bars` itself never
    extends past the caller's `as_of`) and reports whether any of them passed. `select_for_workflow`
    uses that as a proxy for "still within its post-entry cooldown": a held symbol whose gate passed
    within the window keeps its slot without being re-gated today.

    **What this does not do:** it does not enforce the drop-side lockout at all (a symbol dropped
    yesterday is free to re-enter today if it re-passes the gate), and it can extend a hold past 10
    true sessions if the gate happens to re-pass partway through the window, or shorten it if the
    gate's qualifying pass was earlier than 10 sessions ago and has not recurred. Both are named
    exactly here rather than left to be discovered by a caller trusting the docstring's headline
    claim. A driver that threads real per-symbol cooldown counters across calls (not just
    `prior_picks`) would remove this gap entirely; see the bake-off driver's own module docstring for
    why that driver does not attempt to be that caller either.
    """
    if bars.empty:
        return False
    bars = bars.reset_index(drop=True)
    window = bars.tail(lookback)
    for position in window.index:
        prefix = bars.iloc[: position + 1]
        passes, _ = _breakout_metrics(prefix)
        if passes:
            return True
    return False


def _select_breakout_atr(
    as_of: dt.date, regime_label: str, settings: Settings, prior_picks: tuple[str, ...]
) -> tuple[str, ...]:
    pool = _pool_for("breakout_atr", regime_label, settings=settings)
    symbols = pool.symbols_as_of(as_of) if pool is not None else ()
    if not symbols:
        return ()
    top_n = _BREAKOUT_TOP_N[regime_label]

    market = AsOfMarket(as_of=as_of, settings=settings)
    bars_by_symbol = {s: market.history(s, lookback_days=None).reset_index(drop=True) for s in symbols}
    gate = {s: _breakout_metrics(bars_by_symbol[s]) for s in symbols}

    held: list[str] = []
    for symbol in prior_picks:
        if symbol not in symbols:
            continue
        passes, _ = gate[symbol]
        if passes or _recent_gate_pass_within(bars_by_symbol[symbol], lookback=_BREAKOUT_COOLDOWN_SESSIONS):
            held.append(symbol)
    held_set = set(held)

    remaining = max(0, top_n - len(held))
    if remaining:
        gated = [s for s in symbols if s not in held_set and gate[s][0]]
        ranked = sorted(gated, key=lambda s: (-(gate[s][1] or 0.0), s))
        held.extend(ranked[:remaining])

    def _neg_score(s: str) -> float:
        value = gate[s][1]
        return -(value if value is not None else -999.0)

    return tuple(sorted(held, key=lambda s: (_neg_score(s), s)))


# ---------------------------------------------------------------------------
# Entrant 3 -- meanrev_rsi
# ---------------------------------------------------------------------------

_MEANREV_TOP_N: Final[dict[str, int]] = {"risk_off": 2, "high_vol_stress": 2, "choppy_neutral": 1}
_MEANREV_GATE_RSI: Final[float] = 35.0
_MEANREV_EXIT_RSI: Final[float] = 50.0


def _meanrev_metrics(bars: pd.DataFrame) -> tuple[float | None, float | None]:
    """`(rsi_14, bollinger_lower_proximity)` on the last bar, or `(None, None)` if unscoreable."""
    if bars.empty:
        return None, None
    bars = bars.reset_index(drop=True)
    rsi_col = rsi_indicator(bars, period=14).iloc[:, 0]
    bb = bollinger(bars, period=20, stddev=2.0)
    lower_col = next(c for c in bb.columns if c.endswith("_lower"))
    close = bars["close"].astype("float64")

    last_rsi = rsi_col.iloc[-1] if len(rsi_col) else float("nan")
    last_close = close.iloc[-1] if len(close) else float("nan")
    last_lower = bb[lower_col].iloc[-1] if len(bb) else float("nan")

    rsi_val = None if pd.isna(last_rsi) else float(last_rsi)
    proximity = (
        None
        if pd.isna(last_lower) or pd.isna(last_close) or last_lower == 0.0
        else float((last_close - last_lower) / last_lower)
    )
    return rsi_val, proximity


def _select_meanrev_rsi(
    as_of: dt.date, regime_label: str, settings: Settings, prior_picks: tuple[str, ...]
) -> tuple[str, ...]:
    if regime_label == "risk_on_trend":
        # Switched off entirely -- §3 entrant 3, unconditional, not merely deprioritised.
        return ()
    top_n = _MEANREV_TOP_N[regime_label]
    pool = _pool_for("meanrev_rsi", regime_label, settings=settings)
    symbols = pool.symbols_as_of(as_of) if pool is not None else ()
    if not symbols:
        return ()

    market = AsOfMarket(as_of=as_of, settings=settings)
    metrics = {s: _meanrev_metrics(market.history(s, lookback_days=None)) for s in symbols}

    held = [
        s
        for s in prior_picks
        if s in symbols and (rsi_v := metrics[s][0]) is not None and rsi_v <= _MEANREV_EXIT_RSI
    ]
    held_set = set(held)

    remaining = max(0, top_n - len(held))
    if remaining:
        gated = [
            s
            for s in symbols
            if s not in held_set and (rsi_v := metrics[s][0]) is not None and rsi_v < _MEANREV_GATE_RSI
        ]
        ranked = sorted(
            gated,
            key=lambda s: (
                metrics[s][0],
                metrics[s][1] if metrics[s][1] is not None else float("inf"),
                s,
            ),
        )
        held.extend(ranked[:remaining])

    return tuple(sorted(held, key=lambda s: (metrics[s][0] if metrics[s][0] is not None else 999.0, s)))


# ---------------------------------------------------------------------------
# Entrant 4 -- trend_sticky
# ---------------------------------------------------------------------------

_TREND_STICKY_SLOTS: Final[int] = 2
_TREND_STICKY_EXIT_RANK: Final[dict[str, int]] = {"high_vol_stress": 8}
_TREND_STICKY_DEFAULT_EXIT_RANK: Final[int] = 6


def _select_trend_sticky(
    as_of: dt.date, regime_label: str, settings: Settings, prior_picks: tuple[str, ...]
) -> tuple[str, ...]:
    pool = _pool_for("trend_sticky", regime_label, settings=settings)
    full = _full_rank_order(as_of, pool, settings, rank_key="trend", collapse=False)
    if not full:
        return ()
    rank_of = {symbol: i + 1 for i, symbol in enumerate(full)}
    exit_rank = _TREND_STICKY_EXIT_RANK.get(regime_label, _TREND_STICKY_DEFAULT_EXIT_RANK)

    market = AsOfMarket(as_of=as_of, settings=settings)
    below_sma200 = {}
    for symbol in rank_of:
        trend = _trend(_series(market, symbol))
        below_sma200[symbol] = trend is None or trend <= 0.0

    held = [
        s
        for s in prior_picks
        if s in rank_of and not below_sma200[s] and rank_of[s] <= exit_rank
    ]

    # "Enter at rank 1 only" -- only the day's rank-1 name can newly join, and only into a slot
    # left empty by an exit; a vacated slot is never backfilled from rank 2-8.
    if len(held) < _TREND_STICKY_SLOTS:
        top = full[0]
        if top not in held:
            held.append(top)

    return tuple(sorted(held, key=lambda s: rank_of[s]))


# ---------------------------------------------------------------------------
# Entrant 5 -- signal_density
# ---------------------------------------------------------------------------

_SIGNAL_DENSITY_TOP_N: Final[int] = 2
_SIGNAL_DENSITY_GATE: Final[int] = 3
_SIGNAL_DENSITY_BUMP: Final[int] = 5

_BULLISH_RULES: Final[frozenset[str]] = frozenset(
    {"rsi_oversold", "bb_lower_touch", "ema_golden_cross", "macd_bullish_flip", "price_above_sma200"}
)
_BEARISH_RULES: Final[frozenset[str]] = frozenset(
    {"rsi_overbought", "bb_upper_touch", "ema_death_cross", "macd_bearish_flip"}
)
_EXCLUDED_RULES: Final[frozenset[str]] = frozenset({"vwap_reclaim"})
_DEFENSIVE_SUBSET_RULES: Final[frozenset[str]] = frozenset(
    {"rsi_oversold", "rsi_overbought", "bb_lower_touch", "bb_upper_touch", "bb_squeeze", "atr_range_expansion"}
)


def _lean_sign(rule_id: str) -> int:
    if rule_id in _BULLISH_RULES:
        return 1
    if rule_id in _BEARISH_RULES:
        return -1
    return 0


def _density_metrics(bars: pd.DataFrame, *, defensive: bool) -> tuple[int, int]:
    """`(density, net_lean)` on the last bar of `bars`, over the 11-rule catalog (or the 6-rule
    defensive subset -- §3 entrant 5)."""
    if bars.empty:
        return 0, 0
    rules = [r for r in rule_catalog() if r.rule_id not in _EXCLUDED_RULES]
    if defensive:
        rules = [r for r in rules if r.rule_id in _DEFENSIVE_SUBSET_RULES]

    density = 0
    net_lean = 0
    for rule in rules:
        try:
            fired = evaluate(parse_rule(rule.expression), bars, interval=Interval.DAY)
        except RuleEvaluationError:
            continue
        if fired.empty:
            continue
        value = fired.iloc[-1]
        if pd.notna(value) and bool(value):
            density += 1
            net_lean += _lean_sign(rule.rule_id)
    return density, net_lean


def _select_signal_density(
    as_of: dt.date, regime_label: str, settings: Settings, prior_picks: tuple[str, ...]
) -> tuple[str, ...]:
    pool = _pool_for("signal_density", regime_label, settings=settings)
    symbols = pool.symbols_as_of(as_of) if pool is not None else ()
    if not symbols:
        return ()
    defensive = regime_label in {"risk_off", "high_vol_stress"}

    market = AsOfMarket(as_of=as_of, settings=settings)
    metrics = {
        s: _density_metrics(market.history(s, lookback_days=None), defensive=defensive) for s in symbols
    }

    held = [s for s in prior_picks if s in symbols and metrics[s][0] >= _SIGNAL_DENSITY_GATE]
    held_set = set(held)

    challengers = sorted(
        (s for s in symbols if s not in held_set and metrics[s][0] >= _SIGNAL_DENSITY_GATE),
        key=lambda s: (-metrics[s][0], -abs(metrics[s][1]), s),
    )

    for challenger in challengers:
        if len(held) < _SIGNAL_DENSITY_TOP_N:
            held.append(challenger)
            held_set.add(challenger)
            continue
        if metrics[challenger][0] < _SIGNAL_DENSITY_BUMP:
            continue
        weakest = min(held, key=lambda s: (metrics[s][0], abs(metrics[s][1]), s))
        weak_score = (metrics[weakest][0], abs(metrics[weakest][1]))
        challenger_score = (metrics[challenger][0], abs(metrics[challenger][1]))
        if challenger_score > weak_score:
            held.remove(weakest)
            held.append(challenger)
            held_set = set(held)

    return tuple(sorted(held, key=lambda s: (-metrics[s][0], -abs(metrics[s][1]), s)))


# ---------------------------------------------------------------------------
# Entrant 6 -- divers_mom6
# ---------------------------------------------------------------------------


def _select_divers_mom6(
    as_of: dt.date, _regime_label: str, settings: Settings, _prior_picks: tuple[str, ...]
) -> tuple[str, ...]:
    """Theme roster, `mom6`, top 3, collapsed -- in every regime. No hysteresis, no held state."""
    pool = theme_candidates(settings)
    if not pool.symbols_as_of(as_of):
        return ()
    selection = select(as_of, candidates=pool, settings=settings, rank_key="mom6", top_n=3, collapse=True)
    return selection.picks


# ---------------------------------------------------------------------------
# Entrant 8 -- control_week_rotation (entrant 7, control_card_universe, is handled by the dispatcher
# directly -- it reads nothing but `card_universe`).
# ---------------------------------------------------------------------------


def _select_control_week_rotation(
    as_of: dt.date, _regime_label: str, settings: Settings, _prior_picks: tuple[str, ...]
) -> tuple[str, ...]:
    pool = sector_candidates(settings)
    symbols = pool.symbols_as_of(as_of)
    if not symbols:
        return ()
    n = len(symbols)
    offset = as_of.isocalendar()[1] % n
    end = offset + 3
    if end <= n:
        return symbols[offset:end]
    return symbols[offset:] + symbols[: end - n]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_SelectorFn = Callable[[dt.date, str, Settings, tuple[str, ...]], tuple[str, ...]]

_DISPATCH: Final[dict[str, _SelectorFn]] = {
    "mom12_1_hysteresis": _select_mom12_1_hysteresis,
    "breakout_atr": _select_breakout_atr,
    "meanrev_rsi": _select_meanrev_rsi,
    "trend_sticky": _select_trend_sticky,
    "signal_density": _select_signal_density,
    "divers_mom6": _select_divers_mom6,
    "control_week_rotation": _select_control_week_rotation,
}


def select_for_workflow(
    selector_id: str,
    *,
    as_of: dt.date,
    regime_label: str,
    settings: Settings,
    prior_picks: tuple[str, ...] = (),
    card_universe: tuple[str, ...] = (),
    top_n_override: int | None = None,
) -> tuple[str, ...]:
    """Return today's frozen shortlist for `selector_id` -- `ROUND-33-PLAN.md` §3.

    Deterministic and point-in-time: every price read goes through
    :class:`~app.paper.marketdata.AsOfMarket` pinned to `as_of`, and calling this twice with the same
    stored bars and the same arguments returns byte-identical output (§9). `prior_picks` is the only
    cross-call memory -- see the module docstring for the one place (`breakout_atr`'s cooldown) where
    that is not quite enough to reproduce the frozen state machine exactly, and what this module does
    instead.

    `top_n_override` is a LIVE operational widening of the shortlist size, currently honoured only by
    `mom12_1_hysteresis` (the Round-33-promoted selector): it widens the regimes that selector already
    trades to `top_n_override` picks, with the hysteresis bands scaling to match, while leaving the
    regimes it deliberately sits out untouched. `None` (the default, and everything the Phase A bake-off
    ever passes) reproduces the frozen per-regime top_n exactly, so graded results are unaffected. Other
    selectors ignore it -- widening them would need their own band/gate retuning and is out of scope.
    """
    if selector_id not in SELECTOR_IDS:
        raise ValueError(f"unknown selector_id {selector_id!r}; known ids are {SELECTOR_IDS}")
    if regime_label not in _REGIME_LABELS:
        raise ValueError(f"unknown regime_label {regime_label!r}; known labels are {_REGIME_LABELS}")

    if selector_id == "control_card_universe":
        # Verbatim, unconditionally -- §3 entrant 7 reads no price history and no regime input.
        return tuple(card_universe)

    if selector_id == "mom12_1_hysteresis":
        return _select_mom12_1_hysteresis(
            as_of, regime_label, settings, prior_picks, top_n_override=top_n_override
        )

    return _DISPATCH[selector_id](as_of, regime_label, settings, prior_picks)

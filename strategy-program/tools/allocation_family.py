"""A fourth card shape's worth of candidates: a whole-market core, sleeves spread across asset
classes, and volatility awareness -- backtested standalone, in the same register as
`strategy-program/tools/drawdown_ladder.py` and `strategy-program/tools/roth_voltarget.py`.

Why this family, and not another QLD/SCHD variant
---------------------------------------------------
Rounds 10-12 all name the same complaint: eight cards clear the backtest floor and six of them are
variants of two base cards (the QLD/SCHD/IEF drawdown ladder and the QLD/SCHD/SGOV buy-low/trim-high
allocator). Both of those trade a leveraged sleeve against a defensive one. Nothing in the roster asks
a different question: *pick an ETF that covers the whole market as a core, distribute between assets
around it, and take account of volatility* -- no leverage anywhere in the sentence. The four variants
below are that question, answered four different ways: a static baseline, a discrete threshold tilt
that is directly expressible as an `app.tournament.allocation.AllocationCard`, and two continuously
vol-responsive designs that are not (see this module's own report, `ALLOCATION-FAMILY.md`, section
"what AllocationCard cannot express").

**No sleeve in this family is leveraged.** QLD, TQQQ and every other 2x/3x fund in the bar store are
deliberately absent. That is the single most direct way to avoid the "leverage trap" `ROTH-VOLTARGET.md`
already documented once -- a strategy that only outperforms because it holds more of a leveraged sleeve
is not demonstrating anything about allocation, timing, or volatility awareness, it is demonstrating
that leverage did well in the period tested. Every result below is therefore a smaller number than the
QLD-based families' -- reported as the honest cost of that choice, not hidden.

Why a standalone backtester rather than `app.tournament.allocation.run_allocation`
------------------------------------------------------------------------------------
`run_allocation` is the real execution path this family is aimed at, and its `AllocationCard`/
`TiltRule` shape is what section 2 below designs against. But driving it directly here would mean
constructing a `Settings`/`Mandate`/`PaperBroker` for every one of sixteen strategy x window
combinations, which is exactly the kind of `app.tournament`-adjacent machinery the task brief asks this
module to stay clear of (see `strategy-program/DEFECTS.md` D3 on why concurrent access to the single
DuckDB bar store is dangerous, and why `drawdown_ladder.py` and `roth_voltarget.py` both already made
this same choice rather than importing `run_ladder_card`/`run_allocation`). Bars are read once, up
front, through `app.db.duck.read_bars` against an in-memory connection -- the same read path
`app.market.store`'s pure reads use (see `duck.connect`'s own docstring on why `database=None` is the
"a read path has no business creating [a file]" mode) -- and every strategy below is then a plain
Python function over an in-memory price array, exactly as `contributions.py` and `roth_voltarget.py`
already established for the two prior "second/third card shape" families.

**A stateless tilt, on purpose, in variant 2.** `AllocationCard.rules` recomputes every session's target
weights from `sleeves`' declared base weights plus whichever `TiltRule`s fire *that session* (see
`app.tournament.allocation._target_weights`) -- there is no persistent "armed" flag anywhere in that
model, unlike `LadderCard`'s `armed_depth`/`recovery_sessions` state machine. `make_atr_tilt` below is
written to match that exactly: it shifts weight away from the base allocation only while its own
condition is true this session, and reverts automatically the session the condition stops being true,
because the "next" target is always computed fresh from `base`, never carried forward from yesterday's
shifted weights. This is a real, load-bearing design constraint, not an implementation shortcut -- see
`ALLOCATION-FAMILY.md`'s report on what it costs (a threshold sitting near a chop zone re-fires every
session it is crossed, with no per-cycle "arm once" the ladder's rungs get for free).

Run as a plain script, not ``-m`` -- ``strategy-program`` is not a legal Python package name (the
hyphen):

    cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/allocation_family.py

Every window below is in-sample: no price bar used here postdates 2026-08-21 (the bar store's own
latest stored session at the time this was written), and every number is a description of what already
happened, not a forecast.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from app.config import get_settings
from app.db import duck

#: Sessions per year, matching every other backtest tool in this programme
#: (`drawdown_ladder.py`, `contributions.py`, `roth_voltarget.py`).
TRADING_DAYS = 252

#: The bar store's own latest common trading session across every symbol this module touches, as of
#: this module's own last run (verified against the live store, not assumed -- BIL's own latest
#: stored session, 2026-08-11, is the true binding constraint for any window that includes it; the
#: date filter below is generous on purpose and the actual intersection in `load_frames` is what
#: decides each window's real end date).
END = dt.date(2026, 8, 21)

STARTING_EQUITY = 10_000.0
#: Charged on every dollar traded, one way -- the same convention and the same rate
#: `drawdown_ladder.py` and `roth_voltarget.py`/`contributions.py` use, for the identical reason
#: their own docstrings give: an ETF's stored close is already net of its own expense ratio, so the
#: only real, un-modelled cost of running one of these strategies is the cost of the rebalance trades
#: themselves.
SLIPPAGE_BPS = 5.0
#: Rebalance only past this much drift from target, exactly `AllocationCard.band_pct`'s own purpose
#: (see that class's docstring) -- a daily reset to an exact target would manufacture turnover out of
#: ordinary day-to-day price noise between dissimilar instruments, not signal.
BAND_PCT = 0.05


# ---------------------------------------------------------------------------
# Bars, read once via app.db.duck directly (not app.paper.marketdata, not app.tournament.runner)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SymbolFrame:
    """One symbol's aligned close/high/low over a window's common sessions."""

    close: tuple[float, ...]
    high: tuple[float, ...]
    low: tuple[float, ...]


Frames = Mapping[str, SymbolFrame]
#: A strategy: given the session index and every symbol's aligned bars, return target weights.
#: Weights should sum to at most 1; anything short is held as uninvested cash.
WeightFn = Callable[[int, Frames], dict[str, float]]


def load_frames(
    symbols: Sequence[str], start: dt.date, end: dt.date = END
) -> tuple[list[dt.date], dict[str, SymbolFrame]]:
    """Aligned close/high/low for every symbol over their common sessions, intersected rather than
    forward-filled -- a synthetic bar on a day a fund did not trade would let the backtest rebalance
    at a price nobody could actually have got, the same reasoning `drawdown_ladder.load_closes` and
    `roth_voltarget.load_closes` already state for their own, close-only versions of this function.
    """
    settings = get_settings()
    raw = {}
    with duck.connect() as conn:
        for symbol in symbols:
            frame = duck.read_bars(conn, settings.bars_dir, symbol, duck.Interval.DAY, start=start, end=end)
            if frame.empty:
                raise SystemExit(f"no bars stored for {symbol}")
            raw[symbol] = frame

    per_symbol: dict[str, dict[dt.date, tuple[float, float, float]]] = {}
    for symbol, frame in raw.items():
        per_symbol[symbol] = {
            d: (float(c), float(h), float(low))
            for d, c, h, low in zip(
                frame["ts"].dt.date, frame["close"], frame["high"], frame["low"], strict=True
            )
        }

    common = sorted(set.intersection(*(set(v) for v in per_symbol.values())))
    if len(common) < TRADING_DAYS:
        raise SystemExit(
            f"only {len(common)} common sessions for {sorted(symbols)} in {start}..{end} -- "
            "check the narrowest symbol's first bar before widening the window"
        )

    frames: dict[str, SymbolFrame] = {}
    for symbol, idx in per_symbol.items():
        frames[symbol] = SymbolFrame(
            close=tuple(idx[d][0] for d in common),
            high=tuple(idx[d][1] for d in common),
            low=tuple(idx[d][2] for d in common),
        )
    return common, frames


# ---------------------------------------------------------------------------
# The one shared primitive each vol-aware strategy is built from
# ---------------------------------------------------------------------------


def realized_vol(frame: SymbolFrame, i: int, lookback: int) -> float | None:
    """Annualised realised volatility of daily simple returns over `lookback` sessions ending at and
    including session `i`, or `None` before enough history exists. Never reads past `i` -- the one
    place this module touches raw prices by index, matching `roth_voltarget.realized_vol` exactly
    (kept local rather than imported so this file has no dependency on another module's shape)."""
    if i < lookback:
        return None
    window = frame.close[i - lookback : i + 1]
    rets = [window[j] / window[j - 1] - 1 for j in range(1, len(window))]
    if len(rets) < 2:
        return None
    return statistics.pstdev(rets) * TRADING_DAYS**0.5


def atr_pct(frame: SymbolFrame, i: int, lookback: int) -> float | None:
    """Average true range over `lookback` sessions ending at and including session `i`, as a fraction
    of that session's own close.

    A simple equal-weight rolling mean of true range, **not** Wilder's recursive smoothing that this
    repository's own `atr(14)` indicator (`app.indicators.volatility.ATR_SPEC`) computes -- stated
    here rather than silently assumed identical, because variant 2 below is designed to be directly
    re-expressible as an `AllocationCard` `TiltRule` condition (`atr(14) > close * threshold`, the same
    shape the existing `qld-schd-sgov.json` card already uses for `bb_upper`), and a card author
    reproducing this rule against the real engine would get the engine's Wilder-smoothed ATR, which
    tracks a slightly different (smoother, slower-reacting) series than this rolling-mean proxy. The
    threshold chosen below (see `ATR_ENTER_PCT`) was calibrated against *this* module's own rolling-mean
    ATR, not the engine's.

    **Measured 2026-08-30, and the divergence is real but small.** `strategy-program/tools/savings_gap.py`
    holds this harness fixed and swaps only the ATR definition, feeding in the engine's own `atr()`
    output rather than a reimplementation of Wilder smoothing. Over PRIMARY the two fire variant 2's
    tilt on 505 and 474 of 3,730 sessions and **agree on only 75.1% of them** -- so the concern stated
    above is not hypothetical -- yet the book's max drawdown moves 0.1pp (-19.9% -> -19.8%) and its MAR
    not at all. The tilt's benefit comes from being defensive across high-volatility stretches rather
    than from precise entry timing, which is why a quarter of the firing sessions can differ without
    the aggregate following. Re-calibration is therefore no longer listed as unfinished work; see
    `ALLOCATION-FAMILY.md`'s "Does the desk reproduce these numbers?" for the full four-arm result.
    """
    if i < lookback:
        return None
    trs = []
    for j in range(i - lookback + 1, i + 1):
        true_range = max(
            frame.high[j] - frame.low[j],
            abs(frame.high[j] - frame.close[j - 1]),
            abs(frame.low[j] - frame.close[j - 1]),
        )
        trs.append(true_range)
    return (sum(trs) / len(trs)) / frame.close[i]


# ---------------------------------------------------------------------------
# The four variants
# ---------------------------------------------------------------------------


def make_buy_hold(symbol: str) -> WeightFn:
    return lambda i, frames: {symbol: 1.0}


def make_static_blend(weights: Mapping[str, float]) -> WeightFn:
    """Variant 1 -- Static Core-Satellite. A fixed target weight every session, no volatility
    awareness at all. The control: everything variants 2-4 add is measured against this."""
    return lambda i, frames: dict(weights)


def make_atr_tilt(
    base: Mapping[str, float],
    signal_symbol: str,
    lookback: int,
    enter_pct: float,
    shift_pct: float,
    moves: Sequence[tuple[str, str]],
) -> WeightFn:
    """Variant 2 -- ATR-Tilt Core-Satellite. Base weights exactly as variant 1; while
    `signal_symbol`'s own rolling-mean ATR%(`lookback`) is above `enter_pct`, shift `shift_pct` of the
    whole book along each `(from_symbol, to_symbol)` pair in `moves`, in order.

    **Stateless by construction** -- see this module's own docstring's "a stateless tilt, on purpose"
    section. `weights = dict(base)` is rebuilt from the declared base every single session; there is no
    persistent "tripped" flag the way `roth_voltarget.make_circuit_breaker` keeps one (that module's
    own hysteresis -- a *lower* exit threshold, separate from the entry one -- has no equivalent here,
    because `AllocationCard.TiltRule` has nothing to hang state on). This is the one variant of the four
    designed to be a faithful, directly re-implementable `AllocationCard`: each `(condition, on_symbol,
    from_symbol, to_symbol, shift_pct)` tuple below is one `TiltRule`, evaluated the identical way
    `_target_weights` evaluates every session -- see `backend/app/paper/library/allocation/`'s new card
    file for the literal JSON.
    """

    def weight_fn(i: int, frames: Frames) -> dict[str, float]:
        weights = dict(base)
        vol = atr_pct(frames[signal_symbol], i, lookback)
        if vol is not None and vol > enter_pct:
            for from_symbol, to_symbol in moves:
                shift = min(shift_pct, weights[from_symbol])
                weights[from_symbol] -= shift
                weights[to_symbol] += shift
        return weights

    return weight_fn


def make_vol_target_core(
    core: str, bond: str, gold: str, target_vol: float, lookback: int, cap: float = 1.0
) -> WeightFn:
    """Variant 3 -- Continuous Vol-Target Core. `core`'s weight is
    `min(cap, target_vol / realized_vol(core))`; the residual is split a fixed 50/50 between `bond` and
    `gold`, unlike variant 4's continuously-recomputed split. **Not expressible as an `AllocationCard`**
    -- see `ALLOCATION-FAMILY.md`'s "what AllocationCard cannot express" section: this is a continuous
    function of a real number (realized volatility), and `TiltRule.shift_pct` is a fixed `Decimal`
    declared once on the card, not a formula.

    Before `lookback` sessions of history exist, `core` gets zero weight -- a short, unavoidable
    warm-up rather than a guess dressed up as a signal, matching `roth_voltarget.make_vol_target`'s own
    convention.
    """

    def weight_fn(i: int, frames: Frames) -> dict[str, float]:
        vol = realized_vol(frames[core], i, lookback)
        core_w = 0.0 if not vol else min(cap, target_vol / vol)
        residual = 1.0 - core_w
        return {core: core_w, bond: residual * 0.5, gold: residual * 0.5}

    return weight_fn


def make_inverse_vol(symbols: Sequence[str], lookback: int) -> WeightFn:
    """Variant 4 -- Continuous Inverse-Volatility Risk Parity. `weight_i = (1/vol_i) / sum(1/vol_j)`
    among whichever of `symbols` already has `lookback` sessions of history -- no declared "core"
    weight at all; every sleeve's share is set purely by its own realised risk relative to the others,
    recomputed every session. **Also not expressible as an `AllocationCard`**, for the identical reason
    variant 3 is not (see that factory's own docstring) -- the two are kept as separate variants because
    they answer a genuinely different question: variant 3 asks "how much of the whole-market core should
    we hold", treating the rest as a fixed-ratio residual; variant 4 asks "how should every sleeve's
    share respond to its own risk", with no sleeve privileged as "the core" at all.

    If none of `symbols` has enough history yet, everything is parked in the last symbol in the list --
    callers pass the least volatile sleeve last for exactly this reason, matching
    `roth_voltarget.make_inverse_vol`'s own convention.
    """

    def weight_fn(i: int, frames: Frames) -> dict[str, float]:
        vols = {s: realized_vol(frames[s], i, lookback) for s in symbols}
        available = {s: v for s, v in vols.items() if v}
        if not available:
            return {symbols[-1]: 1.0}
        inv = {s: 1.0 / v for s, v in available.items()}
        total = sum(inv.values())
        return {s: w / total for s, w in inv.items()}

    return weight_fn


# ---------------------------------------------------------------------------
# The backtest: lump sum, band-rebalanced, slippage-costed -- the same shape
# `drawdown_ladder.run_ladder`/`run_static` use, generalised to N sleeves via a band instead of a
# state-transition trigger (closer to `AllocationCard`'s own `band_pct` mechanism, since that -- not
# the ladder's state machine -- is the engine this family targets).
# ---------------------------------------------------------------------------


@dataclass
class Result:
    dates: list[dt.date] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)
    weights: list[dict[str, float]] = field(default_factory=list)
    rebalances: int = 0
    turnover: float = 0.0
    cost_paid: float = 0.0

    @property
    def total_return(self) -> float:
        return self.equity[-1] / self.equity[0] - 1

    @property
    def years(self) -> float:
        return len(self.equity) / TRADING_DAYS

    @property
    def cagr(self) -> float:
        return (self.equity[-1] / self.equity[0]) ** (1 / self.years) - 1

    @property
    def max_drawdown(self) -> float:
        peak, worst = self.equity[0], 0.0
        for v in self.equity:
            peak = max(peak, v)
            worst = min(worst, v / peak - 1)
        return worst

    @property
    def volatility(self) -> float:
        rets = [self.equity[i] / self.equity[i - 1] - 1 for i in range(1, len(self.equity))]
        return statistics.pstdev(rets) * TRADING_DAYS**0.5 if len(rets) > 1 else 0.0

    @property
    def mar(self) -> float:
        return self.cagr / abs(self.max_drawdown) if self.max_drawdown else 0.0


def simulate(
    dates: Sequence[dt.date],
    frames: Frames,
    weight_fn: WeightFn,
    *,
    starting_equity: float = STARTING_EQUITY,
    band_pct: float = BAND_PCT,
    slippage_bps: float = SLIPPAGE_BPS,
) -> Result:
    """Run `weight_fn` lump sum against `frames`, rebalancing only when a sleeve's actual weight
    drifts more than `band_pct` from `weight_fn`'s own target that session. The very first session
    always trades (every holding starts at zero, so drift from any nonzero target already exceeds the
    band), matching every other harness in this programme.
    """
    symbols = list(frames)
    result = Result()
    holdings = dict.fromkeys(symbols, 0.0)
    cash = starting_equity

    for i, day in enumerate(dates):
        if i > 0:
            for s in symbols:
                holdings[s] *= frames[s].close[i] / frames[s].close[i - 1]

        equity = sum(holdings.values()) + cash
        targets = weight_fn(i, frames)
        total_target = sum(targets.values())
        if total_target > 1.0 + 1e-9:
            raise ValueError(f"weights sum to {total_target:.4f} > 1 at session {i} ({day})")

        desired = {s: targets.get(s, 0.0) * equity for s in symbols}
        drift = {s: desired[s] - holdings[s] for s in symbols}
        if any(abs(drift[s]) > band_pct * equity for s in symbols):
            for s in symbols:
                move = desired[s] - holdings[s]
                if abs(move) < 1e-9:
                    continue
                cost = abs(move) * slippage_bps / 10_000
                holdings[s] += move
                cash -= move + cost
                result.turnover += abs(move)
                result.cost_paid += cost
            result.rebalances += 1

        result.dates.append(day)
        result.equity.append(sum(holdings.values()) + cash)
        result.weights.append({s: (holdings[s] / equity if equity else 0.0) for s in symbols})

    return result


def summarise(name: str, r: Result) -> str:
    return (
        f"{name:38} ${r.equity[-1]:>11,.0f}  {r.total_return * 100:>7.1f}%  "
        f"{r.cagr * 100:>6.2f}%  {r.max_drawdown * 100:>7.1f}%  {r.volatility * 100:>6.1f}%  "
        f"{r.mar:>5.2f}  {r.rebalances:>5d}"
    )


HEADER = (
    f"{'':38} {'final':>12}  {'total':>7}  {'CAGR':>6}  {'maxDD':>7}  {'vol':>6}  {'MAR':>5}  {'rebal':>5}"
)


# ---------------------------------------------------------------------------
# Severe drawdown periods, reported separately from the headline window -- the brief's own
# requirement, and the same principle `roth_voltarget.WINDOWS` and `drawdown_ladder.py`'s crisis
# comparison already establish: a strategy tested only on a bull run has not been tested.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Period:
    label: str
    start: dt.date
    end: dt.date


SEVERE_PERIODS = (
    Period("2008 GFC (2007-10-09 .. 2009-03-09)", dt.date(2007, 10, 9), dt.date(2009, 3, 9)),
    Period("2020 COVID crash (2020-02-19 .. 2020-03-23)", dt.date(2020, 2, 19), dt.date(2020, 3, 23)),
    Period("2022 bear market (2022-01-03 .. 2022-10-13)", dt.date(2022, 1, 3), dt.date(2022, 10, 13)),
)


def slice_metrics(dates: Sequence[dt.date], equity: Sequence[float], period: Period) -> tuple[float, float] | None:
    """Total return and max drawdown of `equity` restricted to `period`, with the drawdown's own peak
    reset at the slice's *first* value -- this measures how the run performed *during* the period, not
    how far underwater it already was walking in from before. `None` if `period` falls entirely outside
    the dates actually backtested (the window's own history does not reach that far back or forward).
    """
    idx = [i for i, d in enumerate(dates) if period.start <= d <= period.end]
    if not idx:
        return None
    sl = equity[idx[0] : idx[-1] + 1]
    peak, worst = sl[0], 0.0
    for v in sl:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return sl[-1] / sl[0] - 1, worst


# ---------------------------------------------------------------------------
# Windows and strategy builders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Window:
    label: str
    symbols: tuple[str, ...]
    start: dt.date
    end: dt.date = END


#: Variants 1 and 2 (core-satellite): SPY, SCHD, AGG, GLD, BIL, plus QQQ purely as a second
#: buy-and-hold benchmark. Bound by SCHD's own first stored session, 2011-10-20 (verified against the
#: live store; see `strategy-program/tools/allocation_family.py`'s own header comment).
WINDOW_PRIMARY = Window(
    "PRIMARY 2011-2026 (native SCHD, no leverage anywhere)",
    ("SPY", "SCHD", "AGG", "GLD", "BIL", "QQQ"),
    dt.date(2011, 10, 20),
)

#: The same core-satellite shape, run through the 2008 crisis -- SCHD did not exist yet, so SPY stands
#: in for it (the base weight SCHD would have carried is folded into SPY's), the same substitution
#: `ROTH-VOLTARGET.md` already used and marked as a real, non-free substitution rather than a free one.
#: Bound by BIL's own first stored session, 2007-05-30.
WINDOW_CRISIS = Window(
    "CRISIS 2007-2011 (SPY proxy for SCHD*)",
    ("SPY", "AGG", "GLD", "BIL", "QQQ"),
    dt.date(2007, 5, 30),
    dt.date(2011, 10, 19),
)

#: Variants 3 and 4 (continuous vol-aware): SPY / IEF / GLD, no SCHD anywhere, so the window reaches
#: back to GLD's own first stored session, 2004-11-18 -- deep enough to include 2008 natively, with no
#: substitution needed.
WINDOW_VOL_AWARE = Window(
    "FULL 2004-2026 (SPY/IEF/GLD, no SCHD, no leverage)",
    ("SPY", "IEF", "GLD", "QQQ"),
    dt.date(2004, 11, 18),
)

BASE_PRIMARY: dict[str, float] = {"SPY": 0.40, "SCHD": 0.20, "AGG": 0.20, "GLD": 0.10, "BIL": 0.10}
BASE_CRISIS: dict[str, float] = {"SPY": 0.60, "AGG": 0.20, "GLD": 0.10, "BIL": 0.10}

#: ATR(14)-of-close threshold for variant 2, calibrated against SPY's own rolling-mean ATR% history
#: (this module's `atr_pct`, not the engine's Wilder-smoothed indicator -- see that function's own
#: docstring): the empirical distribution has a median of ~1.17%, a 75th percentile of ~1.67%, an 80th
#: of ~1.83%. 1.8% sits at "unusually volatile even for SPY" -- comparable in spirit to
#: `roth_voltarget.BREAKER_ENTER_VOL`'s own choice of a high historical percentile for QLD, restated
#: here for an unlevered index because SPY's own volatility distribution is a different, much narrower
#: one than a 2x fund's.
ATR_ENTER_PCT = 0.018
ATR_SHIFT_PCT = 0.05

#: Vol targets tested for variant 3, chosen the same way `roth_voltarget.VOL_TARGETS` chose its own:
#: from SPY's own realized-volatility distribution (20-session lookback) rather than round numbers
#: picked blind -- median ~13.1%, 75th percentile ~18.7%, 90th ~25.7%. 12% sits near the median, 16%
#: a little above the 75th, 20% near the 90th -- a control, the same role `roth_voltarget.py`'s own
#: 20% target plays, to make the leverage-like trap (see `ALLOCATION-FAMILY.md`) visible rather than
#: hidden.
VOL_TARGETS = (0.12, 0.16, 0.20)
LOOKBACKS = (20, 60)


def build_core_satellite_strategies(base: Mapping[str, float]) -> list[tuple[str, WeightFn]]:
    moves = (
        [("SPY", "BIL"), ("SCHD", "GLD")] if "SCHD" in base else [("SPY", "BIL"), ("SPY", "GLD")]
    )
    return [
        ("SPY buy & hold", make_buy_hold("SPY")),
        ("QQQ buy & hold", make_buy_hold("QQQ")),
        ("1. static core-satellite", make_static_blend(base)),
        (
            "2. ATR-tilt core-satellite",
            make_atr_tilt(base, "SPY", 14, ATR_ENTER_PCT, ATR_SHIFT_PCT, moves),
        ),
    ]


def build_vol_aware_strategies() -> list[tuple[str, WeightFn]]:
    strategies: list[tuple[str, WeightFn]] = [
        ("SPY buy & hold", make_buy_hold("SPY")),
        ("QQQ buy & hold", make_buy_hold("QQQ")),
        ("static 60/20/20 SPY/IEF/GLD", make_static_blend({"SPY": 0.60, "IEF": 0.20, "GLD": 0.20})),
    ]
    for target in VOL_TARGETS:
        for lb in LOOKBACKS:
            strategies.append((
                f"3. vol-target {int(target * 100)}% core (lb{lb})",
                make_vol_target_core("SPY", "IEF", "GLD", target, lb),
            ))
    for lb in LOOKBACKS:
        strategies.append((
            f"4. inverse-vol risk parity (lb{lb})",
            make_inverse_vol(["SPY", "IEF", "GLD"], lb),
        ))
    return strategies


def _run_window(window: Window, strategies: list[tuple[str, WeightFn]]) -> None:
    dates, frames = load_frames(window.symbols, window.start, window.end)
    years = len(dates) / TRADING_DAYS
    print(f"\n=== {window.label} ===")
    print(f"window {dates[0]} .. {dates[-1]}  ({len(dates)} sessions, {years:.2f}y)")
    print(f"slippage {SLIPPAGE_BPS:.0f}bp one-way, {BAND_PCT * 100:.0f}% drift band, "
          f"${STARTING_EQUITY:,.0f} lump sum\n")
    print(HEADER)
    run: list[tuple[str, Result]] = []
    for name, weight_fn in strategies:
        result = simulate(dates, frames, weight_fn)
        print(summarise(name, result))
        run.append((name, result))

    print("\n  -- severe drawdown periods (return / max drawdown within the slice only) --")
    for period in SEVERE_PERIODS:
        rows = []
        for name, result in run:
            metrics = slice_metrics(result.dates, result.equity, period)
            if metrics is not None:
                rows.append((name, metrics))
        if not rows:
            continue
        print(f"\n  {period.label}")
        for name, (ret, dd) in rows:
            print(f"    {name:38} return {ret * 100:>7.1f}%   max drawdown {dd * 100:>7.1f}%")


def main(argv: list[str] | None = None) -> int:
    del argv  # no CLI surface -- every window and every variant runs every time, on purpose

    _run_window(WINDOW_PRIMARY, build_core_satellite_strategies(BASE_PRIMARY))
    _run_window(WINDOW_CRISIS, build_core_satellite_strategies(BASE_CRISIS))
    _run_window(WINDOW_VOL_AWARE, build_vol_aware_strategies())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

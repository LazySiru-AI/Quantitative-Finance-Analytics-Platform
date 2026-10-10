"""A savings-purpose strategy family: $20,000 seed, $1,000/month (and, as a fork, $500/month), held
10-20 years -- scored on the funding shape this account actually has, not on the lump-sum basis the
tournament uses. Companion report: `strategy-program/SAVINGS-FAMILY.md`.

Why this needed its own simulator, not `contributions.simulate`
-----------------------------------------------------------------
`strategy-program/tools/contributions.py` is this program's existing contribution-funded harness, and
its own module docstring is the reason to reach for it first: everything about sequence risk inverting
under funded contributions, and the need to report both money-weighted IRR and time-weighted CAGR,
applies here exactly as it does to the Roth families that already used it. But that module was built
for a **different funding shape** -- $7,500 once a year -- and two things about its `simulate()` block
reuse outright rather than accepting a different set of keyword arguments:

1. **`contribution_dates()` is hardcoded inside `simulate()`, not injectable.** `simulate` calls
   `contrib_at = set(contribution_dates(dates))` itself; there is no parameter that accepts a caller-
   supplied schedule or a different granularity function. Monthly contributions need a monthly version
   of that function, and there is no seam in `simulate`'s signature to hand one in.
2. **There is no seed / opening-balance parameter anywhere in `simulate`.** The account modelled there
   opens at zero and receives its first contribution on day one; this purpose's account opens with
   $20,000 already in it, a structurally different starting condition `simulate` has no argument for.

Both are properties of the *simulation loop*, not of the *result*. `ContributionResult` itself --
`irr`, `time_weighted_cagr`, `max_drawdown`, `volatility`, `mar` -- is written generically over
whatever `dates`/`equity`/`contributed`/`flows` it is handed; nothing in those properties assumes
annual spacing or a zero opening balance. So this module does not re-derive the metrics: it imports
`contributions.py` by file path (`strategy-program` is not a legal Python package name, the hyphen --
matching `roth_voltarget.py`'s own precedent for exactly this reason) to reuse `ContributionResult`,
`Cashflow`, `summarise` and `HEADER` unmodified, and writes one new function, `simulate_savings`, that
is `contributions.simulate`'s own loop with two lines changed: a monthly contribution schedule
(`contribution_dates_monthly`, this module's own function) in place of the annual one, and the seed
added alongside day zero's first monthly contribution instead of no seed at all. Every rebalancing,
drift-band, slippage and contribution-directed-rebalancing line is copied unchanged from
`contributions.simulate`, because none of that logic is what needed to differ.

`contributions.py` itself is not modified anywhere -- not one line -- per this task's scope fence.

The funding shape, precisely
-----------------------------
$20,000 seed plus the first month's contribution both land on the account's opening session (day
zero); every subsequent calendar month contributes on its own first session, mirroring
`contribution_dates`'s "first session of the period" convention with the period changed from a year to
a month. Two monthly rates are modelled throughout, $1,000 and $500, because the brief is explicit that
the rate is not settled and the contribution stream can dominate the terminal balance at a 10-year
horizon -- both are reported for every variant, not the flattering one alone.

No leverage anywhere in this family
--------------------------------------
QLD, TQQQ and every other 2x/3x fund in the bar store are deliberately absent from every variant below,
for the identical reason `strategy-program/ALLOCATION-FAMILY.md` gives for its own four variants: a
strategy that only outperforms the benchmark by holding more of a leveraged sleeve is not demonstrating
anything about allocation, diversification or timing -- it is demonstrating that leverage did well over
the period tested. This purpose is a savings mandate, not a trading one, and the brief's own "known
trap" applies with full force: more equity is not a better strategy, it is more risk, and every result
below that beats a benchmark by holding more equity says so in its own verdict.

The lookback-activation check (round 12's own finding, applied here)
------------------------------------------------------------------------
Round 12 found that 10 of 21 tournament ladder windows were shorter than a long-lookback strategy's own
signal period, so the rule never activated and the book silently held its fallback sleeve the entire
time -- a table that looked like a result and measured nothing. Two of this family's four variants use
no lookback at all (the static core and the horizon glidepath are pure functions of declared weights
and elapsed time, respectively, and are live from session zero). The one variant that does use a
lookback, the volatility-trimmed core, uses a 60-session (~1 quarter) trailing-volatility window,
checked once a month rather than daily -- and every window this module reports it on is at least 5,700
sessions long (see `WINDOW_CORE` below), roughly 95x the lookback itself. The signal has room to
activate for effectively the entire backtest, not just its tail; this was checked against each window's
actual session count printed at run time, not assumed.

Run as a plain script, not ``-m`` -- ``strategy-program`` is not a legal Python package name:

    cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/savings_family.py

Every window below is in-sample: no price bar used here postdates this module's own last run, and every
number is a description of what already happened, not a forecast.
"""

from __future__ import annotations

import datetime as dt
import functools
import importlib.util
import statistics
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.db import duck

# `contributions.py` lives under a hyphenated directory, which is not a legal Python package name, so
# it is loaded by file path -- matching `roth_voltarget.py`'s own precedent for the identical reason.
# This gives access to `ContributionResult`, `Cashflow`, `summarise` and `HEADER` without re-deriving
# any of the money-weighted-IRR / time-weighted-CAGR / contribution-adjusted-drawdown machinery those
# already implement generically (see this module's own docstring for exactly what could and could not
# be reused from `simulate` itself).
_spec = importlib.util.spec_from_file_location(
    "contributions", str(Path(__file__).with_name("contributions.py"))
)
contrib = importlib.util.module_from_spec(_spec)
sys.modules["contributions"] = contrib
_spec.loader.exec_module(contrib)

#: Sessions per year, matching `contributions.py` and every other backtest tool in this programme.
TRADING_DAYS = 252

#: The seed this purpose's account opens with, per the brief. A module constant, not a default
#: argument to sweep -- it is a fact about the account, the same reasoning
#: `contributions.ANNUAL_CONTRIBUTION` gives for its own constant.
SEED = 20_000.0

#: Both monthly contribution rates the brief requires reported side by side, because the owner has not
#: settled on one and a strategy that ranks first at one rate may not rank first at the other.
CONTRIBUTION_RATES = (1_000.0, 500.0)

SLIPPAGE_BPS = 5.0
BAND_PCT = 0.05

#: A strategy: given the session index and every symbol's aligned closes, return target weights.
#: Matches `contributions.WeightFn` exactly; redeclared locally so this module's factories can be
#: annotated without reaching into a module that was loaded at runtime rather than imported normally.
WeightFn = Callable[[int, Mapping[str, Sequence[float]]], dict[str, float]]


# ---------------------------------------------------------------------------
# Bars -- read directly via app.db.duck, never through app.tournament's runner (DEFECTS.md D3: the bar
# store is a single DuckDB file and a concurrent tournament run would corrupt results silently; a plain
# read through `duck.read_bars` carries none of that risk).
# ---------------------------------------------------------------------------


def load_closes(
    symbols: Sequence[str], start: dt.date, end: dt.date
) -> tuple[list[dt.date], dict[str, list[float]]]:
    """Aligned closes for every symbol over their common sessions, intersected rather than
    forward-filled: a synthetic bar on a day a fund did not trade would let the backtest rebalance at a
    price nobody could actually have got. Matches `allocation_family.load_frames` and
    `roth_voltarget.load_closes`'s own convention.
    """
    settings = get_settings()
    frames: dict[str, dict[dt.date, float]] = {}
    with duck.connect() as conn:
        for symbol in symbols:
            frame = duck.read_bars(conn, settings.bars_dir, symbol, duck.Interval.DAY, start=start, end=end)
            if frame.empty:
                raise SystemExit(f"no bars stored for {symbol}")
            frames[symbol] = dict(zip(frame["ts"].dt.date, (float(c) for c in frame["close"]), strict=True))

    common = sorted(set.intersection(*(set(f) for f in frames.values())))
    dates = [d for d in common if start <= d <= end]
    if len(dates) < TRADING_DAYS:
        raise SystemExit(
            f"only {len(dates)} common sessions for {sorted(symbols)} in {start}..{end} -- "
            "check the narrowest symbol's first bar before widening the window"
        )
    return dates, {s: [frames[s][d] for d in dates] for s in symbols}


# ---------------------------------------------------------------------------
# The monthly, seeded simulator. See this module's own docstring for exactly why `contributions.
# simulate` could not be called with different keyword arguments and had to be copied and adapted
# instead -- the contribution schedule is hardcoded inside `simulate`, not a parameter, and there is
# no seed argument at all.
# ---------------------------------------------------------------------------


def contribution_dates_monthly(dates: Sequence[dt.date]) -> list[int]:
    """The first session of each calendar month, plus the first session overall -- the monthly analog
    of `contributions.contribution_dates`'s "first session of each calendar year, plus the first
    session overall", with the period changed from a year to a month and nothing else.
    """
    out = [0]
    for i in range(1, len(dates)):
        if (dates[i].year, dates[i].month) != (dates[i - 1].year, dates[i - 1].month):
            out.append(i)
    return out


def simulate_savings(
    dates: Sequence[dt.date],
    closes: Mapping[str, Sequence[float]],
    weight_fn: WeightFn,
    *,
    seed: float,
    monthly_contribution: float,
    band_pct: float = BAND_PCT,
    slippage_bps: float = SLIPPAGE_BPS,
    use_contributions_to_rebalance: bool = True,
) -> contrib.ContributionResult:
    """`contributions.simulate`'s own loop, with the contribution schedule and the opening balance
    changed and nothing else -- every rebalancing, drift-band, slippage and contribution-directed-
    rebalancing line below is copied unchanged from that function. `seed` and the first month's
    contribution both land on session zero as one combined cashflow; every later month contributes
    `monthly_contribution` alone on its own first session (`contribution_dates_monthly`, above).
    """
    symbols = list(closes)
    result = contrib.ContributionResult()
    contrib_at = set(contribution_dates_monthly(dates))

    holdings = dict.fromkeys(symbols, 0.0)  # dollars per sleeve
    cash = 0.0
    contributed = 0.0

    for i, day in enumerate(dates):
        if i > 0:
            for s in symbols:
                holdings[s] *= closes[s][i] / closes[s][i - 1]

        if i in contrib_at:
            amount = monthly_contribution + (seed if i == 0 else 0.0)
            cash += amount
            contributed += amount
            result.flows.append(contrib.Cashflow(day, amount))

        equity = sum(holdings.values()) + cash
        targets = weight_fn(i, closes)
        total_target = sum(targets.values())
        if total_target > 1.0 + 1e-9:
            raise ValueError(f"weights sum to {total_target:.4f} > 1 at session {i} ({day})")

        desired = {s: targets.get(s, 0.0) * equity for s in symbols}
        drift = {s: desired[s] - holdings[s] for s in symbols}

        # Spend new cash on the underweight sleeves first: a buy funded by a deposit pays slippage
        # once, where a buy funded by a sale pays it twice. Identical to `contributions.simulate`.
        if use_contributions_to_rebalance and cash > 0:
            wanted = {s: d for s, d in drift.items() if d > 0}
            need = sum(wanted.values())
            if need > 0:
                spend = min(cash, need)
                for s, d in wanted.items():
                    take = spend * (d / need)
                    holdings[s] += take
                    cash -= take
                    result.turnover += take
                    cost = take * slippage_bps / 10_000
                    holdings[s] -= cost
                    result.cost_paid += cost
                result.contribution_buys += 1
                drift = {s: desired[s] - holdings[s] for s in symbols}

        breach = any(abs(drift[s]) > band_pct * equity for s in symbols)
        if breach:
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
        result.contributed.append(contributed)
        result.weights.append({s: (holdings[s] / equity if equity else 0.0) for s in symbols})

    return result


# ---------------------------------------------------------------------------
# The four variants
# ---------------------------------------------------------------------------


def realized_vol(prices: Sequence[float], i: int, lookback: int) -> float | None:
    """Annualised realised volatility of daily simple returns over the `lookback` sessions ending at
    and including session `i`, or `None` before enough history exists. Never reads past `i` -- matches
    `roth_voltarget.realized_vol` / `allocation_family.realized_vol` exactly, kept local so this file
    has no runtime dependency on another module's shape.
    """
    if i < lookback:
        return None
    window = prices[i - lookback : i + 1]
    rets = [window[j] / window[j - 1] - 1 for j in range(1, len(window))]
    if len(rets) < 2:
        return None
    return statistics.pstdev(rets) * TRADING_DAYS**0.5


def make_buy_hold(symbol: str) -> WeightFn:
    return lambda i, closes: {symbol: 1.0}


def make_static_blend(weights: Mapping[str, float]) -> WeightFn:
    """Variant 1 / the benchmark shape -- a fixed target weight every session, no signal anywhere.
    The harness's own 5% drift band paces the trades, exactly as it does for every strategy in this
    family, so "static" and "responsive" variants are compared under the identical rebalancing rule.
    """
    return lambda i, closes: dict(weights)


def make_glidepath(
    equity_symbol: str,
    bond_symbol: str,
    start_equity: float,
    end_equity: float,
    glide_years: float,
) -> WeightFn:
    """Variant 3 -- Horizon Glidepath. `equity_symbol`'s weight starts at `start_equity` on session
    zero and falls **linearly with elapsed time**, in fractional years since inception, to
    `end_equity` at `glide_years` and no further; the residual is held in `bond_symbol`. This is a pure
    function of the session index divided by `TRADING_DAYS` -- **no price history and no lookback of
    any kind** -- so it is live and de-risking from day one regardless of how long the tested window
    is, unlike every vol- or momentum-based strategy in this programme's other families. That is a
    deliberate design property for a savings mandate: a horizon-based de-risking rule cannot fail to
    activate the way a long-lookback signal can (see this module's own docstring on round 12's
    finding), because it never waits on anything.
    """

    def weight_fn(i: int, closes: Mapping[str, Sequence[float]]) -> dict[str, float]:
        years_elapsed = i / TRADING_DAYS
        frac = min(1.0, years_elapsed / glide_years)
        equity_w = start_equity + (end_equity - start_equity) * frac
        return {equity_symbol: equity_w, bond_symbol: 1.0 - equity_w}

    return weight_fn


def make_vol_trim(
    base: Mapping[str, float],
    vol_symbol: str,
    cut_symbol: str,
    add_symbol: str,
    lookback: int,
    enter_vol: float,
    exit_vol: float,
    cut_pct: float,
    check_at: frozenset[int],
) -> WeightFn:
    """Variant 4 -- Volatility-Trimmed Core. Hold `base` normally. Checked **once a month** (the first
    session of each calendar month, not daily) -- the identical "evaluate the slow leg on its own
    natural cadence, not the daily grid" reasoning `ROTH-MOMENTUM.md` gives for its own momentum leg,
    applied here for the same "a savings strategy that needs constant attention is the wrong shape for
    the purpose" reason the brief states directly. While `vol_symbol`'s trailing `lookback`-session
    realised volatility is at or above `enter_vol` on a check date, cut `cut_pct` of the book from
    `cut_symbol` into `add_symbol`; restore the base weights only once volatility has fallen back to at
    or below `exit_vol`, a strictly lower threshold. `enter_vol == exit_vol` would let a volatility
    reading oscillating around one line flip the trim on and off every month it crosses -- the same
    hysteresis reasoning `roth_voltarget.make_circuit_breaker` and `drawdown_ladder.py`'s per-cycle
    arming both already use. The trimmed weight is **held between monthly checks**, not recomputed
    daily, which is what keeps this a low-touch, once-a-month rule rather than a continuously-responsive
    one -- a deliberate simplicity choice for this purpose, not an oversight. `check_at` is the set of
    session indices that count as "the first session of a calendar month" for the window actually being
    run -- computed once by the caller (`contribution_dates_monthly` over that window's own `dates`) and
    passed in, rather than recomputed from `closes` alone, since a plain price array carries no dates.
    """
    state = {"trimmed": False}

    def weight_fn(i: int, closes: Mapping[str, Sequence[float]]) -> dict[str, float]:
        if i in check_at:
            vol = realized_vol(closes[vol_symbol], i, lookback)
            if vol is not None:
                if not state["trimmed"] and vol >= enter_vol:
                    state["trimmed"] = True
                elif state["trimmed"] and vol <= exit_vol:
                    state["trimmed"] = False
        if not state["trimmed"]:
            return dict(base)
        weights = dict(base)
        shift = min(cut_pct, weights[cut_symbol])
        weights[cut_symbol] -= shift
        weights[add_symbol] = weights.get(add_symbol, 0.0) + shift
        return weights

    return weight_fn


# ---------------------------------------------------------------------------
# Windows -- the longest span each variant's symbols jointly support, per the brief's own requirement
# to report the span actually got rather than default to a short one.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Window:
    label: str
    symbols: tuple[str, ...]
    start: dt.date
    end: dt.date


#: SPY/AGG is the pair this whole family's simplest variants and both benchmarks share. Bound by AGG's
#: own first stored session (2003-09-29, verified against the live store) -- SPY alone reaches back to
#: 1993, but AGG is the binding constraint for every strategy that touches it. Reaches the 2008 crash
#: natively (2003 predates it by nearly five years) and covers close to 23 years, comfortably past the
#: mandate's own 10-20 year upper bound.
WINDOW_CORE = Window("CORE (SPY/AGG)", ("SPY", "AGG"), dt.date(2003, 9, 29), dt.date(2026, 8, 19))

#: SPY/AGG/GLD, SPY standing in for SCHD (SCHD does not exist yet) -- bound by GLD's own first stored
#: session, 2004-11-18. The longest window the diversified variant can run without SCHD.
WINDOW_DIV_FULL = Window(
    "DIVERSIFIED-FULL (SPY*/AGG/GLD, SPY proxy for SCHD)",
    ("SPY", "AGG", "GLD"),
    dt.date(2004, 11, 18),
    dt.date(2026, 8, 19),
)

#: SPY/SCHD/AGG/GLD, native SCHD -- bound by SCHD's own first stored session, 2011-10-20. Does not
#: reach the 2008 crash; the FULL window above exists specifically because this one cannot.
WINDOW_DIV_PRIMARY = Window(
    "DIVERSIFIED-PRIMARY (SPY/SCHD/AGG/GLD, native SCHD)",
    ("SPY", "SCHD", "AGG", "GLD"),
    dt.date(2011, 10, 20),
    dt.date(2026, 8, 19),
)

#: The 2008 crash, reported as its own slice per the brief -- identical dates to
#: `ALLOCATION-FAMILY.md`'s and `allocation_family.py`'s own GFC period, so the two documents' 2008
#: numbers are read on the same calendar span.
GFC_START = dt.date(2007, 10, 9)
GFC_END = dt.date(2009, 3, 9)

#: Volatility-trim thresholds, calibrated from SPY's own trailing-volatility distribution rather than
#: picked blind -- `ALLOCATION-FAMILY.md` found SPY's own 20-session realised-vol median ~13.1%, 75th
#: percentile ~18.7% (see that module's `VOL_TARGETS` comment). This variant uses a 60-session (~1
#: quarter) lookback for a steadier, once-a-month-checked signal; `enter_vol=18%` sits near SPY's own
#: 75th percentile ("unusually volatile for the broad market"), `exit_vol=13%` sits back near the
#: median, giving the hysteresis gap `make_vol_trim`'s own docstring explains the need for.
VOL_TRIM_ENTER = 0.18
VOL_TRIM_EXIT = 0.13
VOL_TRIM_LOOKBACK = 60
VOL_TRIM_CUT_PCT = 0.20


def build_core_strategies(dates: Sequence[dt.date]) -> list[tuple[str, WeightFn]]:
    check_at = frozenset(contribution_dates_monthly(dates))
    return [
        ("benchmark: SPY buy & hold", make_buy_hold("SPY")),
        ("benchmark: static 60/40 SPY/AGG", make_static_blend({"SPY": 0.60, "AGG": 0.40})),
        ("1. broad-market core 80/20 SPY/AGG", make_static_blend({"SPY": 0.80, "AGG": 0.20})),
        (
            "3. horizon glidepath 90->60 SPY/AGG (20y)",
            make_glidepath("SPY", "AGG", 0.90, 0.60, 20.0),
        ),
        (
            "4. vol-trimmed core 70/30 SPY/AGG",
            make_vol_trim(
                {"SPY": 0.70, "AGG": 0.30}, "SPY", "SPY", "AGG",
                VOL_TRIM_LOOKBACK, VOL_TRIM_ENTER, VOL_TRIM_EXIT, VOL_TRIM_CUT_PCT, check_at,
            ),
        ),
    ]


def build_diversified_strategies(
    base: Mapping[str, float], dates: Sequence[dt.date]
) -> list[tuple[str, WeightFn]]:
    del dates  # variant 2 has no lookback and needs no per-window check-date set; kept for a uniform
    # `build_strategies(dates)` signature across `_run_window`'s callers.
    return [
        ("benchmark: SPY buy & hold", make_buy_hold("SPY")),
        ("benchmark: static 60/40 SPY/AGG", make_static_blend({"SPY": 0.60, "AGG": 0.40})),
        ("2. diversified multi-asset core", make_static_blend(base)),
    ]


#: Variant 2's own weights. PRIMARY (native SCHD): SPY 35% / SCHD 20% / AGG 30% / GLD 15%. FULL (SPY
#: proxy for SCHD, marked `*`): SCHD's 20 points folded into SPY -- SPY 55% / AGG 30% / GLD 15% -- the
#: same fold-in convention `ROTH-MOMENTUM.md` and `ALLOCATION-FAMILY.md` both already use for a sleeve
#: that does not exist yet in the earlier window.
DIVERSIFIED_PRIMARY_WEIGHTS: dict[str, float] = {"SPY": 0.35, "SCHD": 0.20, "AGG": 0.30, "GLD": 0.15}
DIVERSIFIED_FULL_WEIGHTS: dict[str, float] = {"SPY": 0.55, "AGG": 0.30, "GLD": 0.15}


# ---------------------------------------------------------------------------
# 2008 slice metrics -- raw balance return/drawdown within the slice, peak reset at the slice's own
# first value (matches `allocation_family.slice_metrics`'s convention). Not contribution-adjusted: by
# late 2007 every variant's balance is already the $20,000 seed plus four-plus years of compounding and
# monthly contributions, against which the handful of $500-$1,000 deposits landing inside a 17-month
# slice are a small fraction -- stated here rather than left implicit.
# ---------------------------------------------------------------------------


def slice_metrics(
    dates: Sequence[dt.date], equity: Sequence[float], start: dt.date, end: dt.date
) -> tuple[float, float] | None:
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    if not idx:
        return None
    sl = equity[idx[0] : idx[-1] + 1]
    peak, worst = sl[0], 0.0
    for v in sl:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return sl[-1] / sl[0] - 1, worst


# ---------------------------------------------------------------------------
# Cost-of-turnover line, matching `roth_voltarget._cost_line` exactly.
# ---------------------------------------------------------------------------


def _cost_line(name: str, r: contrib.ContributionResult) -> str:
    turns = r.turnover / r.total_contributed if r.total_contributed else 0.0
    cost_bps_of_final = (r.cost_paid / r.final_balance * 10_000) if r.final_balance else 0.0
    return (
        f"{name:38} turnover {turns:>6.2f}x paid-in   "
        f"cost paid ${r.cost_paid:>9,.0f}  ({cost_bps_of_final:>6.1f}bp of final balance)"
    )


def _run_window(
    window: Window,
    build_strategies: Callable[[Sequence[dt.date]], list[tuple[str, WeightFn]]],
    monthly_contribution: float,
    gfc: bool,
) -> None:
    dates, closes = load_closes(window.symbols, window.start, window.end)
    strategies = build_strategies(dates)
    years = len(dates) / TRADING_DAYS
    print(f"\n=== {window.label} ===")
    print(f"window {dates[0]} .. {dates[-1]}  ({len(dates)} sessions, {years:.2f}y)\n")
    print(contrib.HEADER)
    run: list[tuple[str, contrib.ContributionResult]] = []
    for name, weight_fn in strategies:
        result = simulate_savings(
            dates, closes, weight_fn, seed=SEED, monthly_contribution=monthly_contribution
        )
        print(contrib.summarise(name, result))
        run.append((name, result))

    print("\n  -- cost of turnover (5bp slippage, charged on every dollar traded) --")
    for name, result in run:
        print("  " + _cost_line(name, result))

    if gfc:
        print(f"\n  -- 2008 GFC slice ({GFC_START} .. {GFC_END}), raw balance return/drawdown --")
        for name, result in run:
            metrics = slice_metrics(result.dates, result.equity, GFC_START, GFC_END)
            if metrics is None:
                print(f"    {name:38} window does not reach the GFC slice")
                continue
            ret, dd = metrics
            print(f"    {name:38} return {ret * 100:>7.1f}%   max drawdown {dd * 100:>7.1f}%")


def main(argv: list[str] | None = None) -> int:
    del argv  # no CLI surface -- every window, every variant and both contribution rates run every time

    for rate in CONTRIBUTION_RATES:
        print(f"\n{'#' * 88}\n# monthly contribution ${rate:,.0f}  (seed ${SEED:,.0f})\n{'#' * 88}")
        _run_window(WINDOW_CORE, build_core_strategies, rate, gfc=True)
        _run_window(
            WINDOW_DIV_FULL,
            functools.partial(build_diversified_strategies, DIVERSIFIED_FULL_WEIGHTS),
            rate,
            gfc=True,
        )
        _run_window(
            WINDOW_DIV_PRIMARY,
            functools.partial(build_diversified_strategies, DIVERSIFIED_PRIMARY_WEIGHTS),
            rate,
            gfc=False,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

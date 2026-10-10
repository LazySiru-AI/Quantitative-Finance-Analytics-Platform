"""Volatility-scaled and risk-budgeted allocation strategies for a Roth IRA, backtested through the
contribution-funded simulator in `strategy-program/tools/contributions.py`.

Why this family, and not another rotation ladder
-------------------------------------------------
`strategy-program/tools/drawdown_ladder.py` found a concrete failure: a ladder that adds leverage on
the way down, arms once per drawdown cycle, and delevers only on a fresh all-time high, rode its
deepest QLD weight through the back half of the 2008 decline and posted a contribution-adjusted
-72.7% drawdown for it (`strategy-program/DRAWDOWN-LADDER.md`). What that strategy actually lacked
was not a smarter trigger price -- it was any notion of *how much is too much to hold right now*.
Every strategy below answers that question from the market's own realised volatility instead of from
price level or drawdown depth, because volatility is a leading indicator where drawdown is a lagging
one: in 2008 the VIX had already cleared 30 while SPY was still less than -20% off its high. A
volatility-scaled sleeve starts delevering while a drawdown-triggered ladder is still arming its
first rung.

1. **Vol targeting** (`make_vol_target`) scales a single leveraged sleeve so its own realised
   volatility tracks a constant. This is the ladder's decision variable inverted and made continuous:
   leverage falls automatically as volatility rises, rather than falling in fixed steps after price
   has fallen a fixed amount.
2. **Inverse-volatility weighting** (`make_inverse_vol`) spreads three sleeves in proportion to
   1/volatility, rebalanced whenever drift exceeds the harness's band. A sleeve that gets riskier
   cedes weight to the others continuously, with no rule anyone had to write about *when* to act.
3. **A volatility circuit-breaker** (`make_circuit_breaker`) is the cheap, discrete version of (1):
   held on a static blend, cutting the leveraged sleeve to zero above a threshold and restoring it
   only once volatility has fallen back through a *lower* threshold -- the same arm/re-arm hysteresis
   `drawdown_ladder.py` needed to stop April-2025-shaped chop from round-tripping the book.
4. **A risk-budgeted core** (`make_risk_budgeted_core`), this programme's own synthesis of (1) and
   (2): size the leveraged sleeve by realised-vol targeting, and split whatever is left between an
   income-equity sleeve and a duration sleeve by *their* inverse volatility, instead of parking all
   of it in one bond fund at a fixed split. 2022 is the year this distinction pays for itself -- SCHD
   and IEF did not get risky at the same time or by the same amount, and a fixed 30/30 static blend
   has no way to notice.

Estimation window is a real knob, not a footnote: a lookback short enough to react to a regime change
is also short enough to be mostly noise, and a lookback long enough to be stable reacts to a crash
after most of the damage is done. Every strategy here is run at two lookbacks -- 20 sessions (~1
month) and 60 sessions (~1 quarter) -- and the sensitivity between them is reported alongside the
headline numbers rather than picked once and hidden.

Run as a plain script, not ``-m`` -- ``strategy-program`` is not a legal Python package name (the
hyphen), so it is invoked by file path with `backend` and the repo root already on ``PYTHONPATH``:

    cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/roth_voltarget.py

Every window below is in-sample: none of the price history used here postdates 2026-02-13, and every
number in this module is a description of what already happened, not a forecast.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import statistics
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from app.config import get_settings
from app.paper.marketdata import _full_frame

# `contributions.py` lives under a hyphenated directory, which is not a legal Python package name,
# so it is loaded by file path rather than imported normally. This gives access to `simulate`,
# `ContributionResult`, `summarise`, `HEADER` and the two constants below without re-implementing any
# of the contribution/rebalance/slippage machinery this module deliberately shares with every other
# strategy in the programme.
_spec = importlib.util.spec_from_file_location(
    "contributions", __file__.replace("roth_voltarget.py", "contributions.py")
)
contrib = importlib.util.module_from_spec(_spec)
sys.modules["contributions"] = contrib
_spec.loader.exec_module(contrib)

#: Sessions per year, matching `contributions.py`, `score.py`, `windows.py` and `drawdown_ladder.py`.
_TRADING_DAYS = 252

#: A strategy: given the session index and every symbol's aligned closes, return target weights.
#: Matches `contributions.WeightFn` exactly; redeclared locally so this module's factories can be
#: annotated without reaching into a module that was loaded at runtime rather than imported.
WeightFn = Callable[[int, Mapping[str, Sequence[float]]], dict[str, float]]


def realized_vol(prices: Sequence[float], i: int, lookback: int) -> float | None:
    """Annualised realised volatility of daily simple returns over the `lookback` sessions ending at
    and including session `i`, or `None` before enough history exists to compute one.

    `simulate()` hands every `weight_fn` the *entire* price array for its own convenience, not a
    slice truncated at `i` -- see the `WeightFn` note in `contributions.py`. That makes it possible to
    write a strategy that silently peeks at tomorrow's close by indexing past `i`. This function is
    the one place in the module that touches raw prices by index, and it never reads past `i`, which
    is what keeps every strategy built on top of it honest by construction rather than by discipline.
    """
    if i < lookback:
        return None
    window = prices[i - lookback : i + 1]
    rets = [window[j] / window[j - 1] - 1 for j in range(1, len(window))]
    if len(rets) < 2:
        return None
    return statistics.pstdev(rets) * _TRADING_DAYS**0.5


def make_buy_hold(symbol: str) -> WeightFn:
    return lambda i, closes: {symbol: 1.0}


def make_static_blend(weights: dict[str, float]) -> WeightFn:
    """A fixed target weight every session. No calendar logic lives here: the harness's own 5%
    drift band (`contributions.simulate`'s `band_pct`) is what actually paces the trades, exactly as
    it does for every other strategy in this module, so "static" and "vol-scaled" strategies are
    compared under the same rebalancing rule rather than one being flattered by a looser one. For a
    blend this calm the two are close in practice: a 60/40 SCHD/IEF book rarely drifts 5% within a
    single year on its own, so band-triggered and calendar-triggered rebalancing land in almost the
    same place -- but "almost the same" is a claim worth stating rather than assuming.
    """
    return lambda i, closes: dict(weights)


def make_vol_target(
    risk_symbol: str, safe_symbol: str, target_vol: float, lookback: int, cap: float = 1.0
) -> WeightFn:
    """Scale `risk_symbol` so its own trailing realised volatility tracks `target_vol`; park the
    residual in `safe_symbol`. `cap` stops the weight exceeding 1.0 -- there is no margin in a Roth
    IRA, so "target vol says lever up further" has nowhere to go once the book is 100% in the risk
    sleeve, and the honest response is to cap the weight rather than pretend the leverage exists.

    Before `lookback` sessions of history exist, `risk_symbol` gets zero weight and `safe_symbol`
    gets all of it -- a short, unavoidable warm-up rather than a guess dressed up as a signal.
    """

    def weight_fn(i: int, closes: Mapping[str, Sequence[float]]) -> dict[str, float]:
        vol = realized_vol(closes[risk_symbol], i, lookback)
        risk_w = 0.0 if not vol else min(cap, target_vol / vol)
        return {risk_symbol: risk_w, safe_symbol: 1.0 - risk_w}

    return weight_fn


def make_inverse_vol(symbols: Sequence[str], lookback: int) -> WeightFn:
    """Weight each symbol in proportion to 1/(its own trailing realised volatility), among whichever
    symbols already have `lookback` sessions of history. A symbol still warming up gets zero weight
    rather than an assumed one -- it is excluded from the split, not silently given an average share.

    If none of the symbols have enough history yet (only possible in the first `lookback` sessions
    of the whole backtest), everything is parked in the last symbol in the list -- callers pass the
    safest sleeve last for exactly this reason.
    """

    def weight_fn(i: int, closes: Mapping[str, Sequence[float]]) -> dict[str, float]:
        vols = {s: realized_vol(closes[s], i, lookback) for s in symbols}
        available = {s: v for s, v in vols.items() if v}
        if not available:
            return {symbols[-1]: 1.0}
        inv = {s: 1.0 / v for s, v in available.items()}
        total = sum(inv.values())
        return {s: w / total for s, w in inv.items()}

    return weight_fn


def make_circuit_breaker(
    base: Mapping[str, float],
    vol_symbol: str,
    cut_symbol: str,
    lookback: int,
    enter_vol: float,
    exit_vol: float,
) -> WeightFn:
    """Hold `base` normally. While `vol_symbol`'s trailing realised volatility is at or above
    `enter_vol`, cut `cut_symbol` to zero and redistribute its weight across the remaining sleeves in
    their existing relative proportion. Restore `base` only once volatility has fallen back to at or
    below `exit_vol` -- a strictly lower threshold, on purpose. `enter_vol == exit_vol` would let a
    volatility reading oscillating around one line flip the switch every time it crosses, which is
    the identical failure mode `drawdown_ladder.py`'s per-cycle arming exists to prevent, just
    measured in volatility instead of price.

    `enter_vol=0.45` and `exit_vol=0.30` are this module's defaults, chosen from QLD's own trailing
    realised-volatility distribution over its full 2006-2026 history: the median is ~33% annualised,
    the 75th percentile ~45-46%, the 90th ~61%. `enter_vol` sits at the boundary of "unusually
    volatile even for QLD" rather than at a round number picked without looking; `exit_vol` sits back
    at the median, so the breaker resets only once the elevated regime has genuinely passed rather
    than merely dipped.
    """
    others = [s for s in base if s != cut_symbol]
    other_total = sum(base[s] for s in others)
    state = {"tripped": False}

    def weight_fn(i: int, closes: Mapping[str, Sequence[float]]) -> dict[str, float]:
        vol = realized_vol(closes[vol_symbol], i, lookback)
        if vol is not None:
            if not state["tripped"] and vol >= enter_vol:
                state["tripped"] = True
            elif state["tripped"] and vol <= exit_vol:
                state["tripped"] = False
        if not state["tripped"]:
            return dict(base)
        freed = base[cut_symbol]
        return {s: base[s] + freed * (base[s] / other_total) for s in others}

    return weight_fn


def make_risk_budgeted_core(
    risk_symbol: str,
    income_symbol: str,
    duration_symbol: str,
    target_vol: float,
    lookback: int,
    cap: float = 1.0,
) -> WeightFn:
    """This module's own strategy: vol-target `risk_symbol` exactly as `make_vol_target` does, then
    split whatever is left between `income_symbol` and `duration_symbol` by *their* inverse
    volatility rather than a fixed ratio.

    The static baselines in this file hold a fixed split of the defensive sleeves (e.g. 30% SCHD /
    30% IEF) regardless of which one is actually behaving defensively this year. 2022 is the case
    that argues against that: SCHD (equity beta) and IEF (rate duration) both drew down, but not
    together and not by the same amount at the same time, and a fixed split has no mechanism to lean
    away from whichever one is currently the riskier of the two. Reusing `make_inverse_vol`'s logic
    on the residual, instead of inventing a second mechanism, means the "which defensive sleeve"
    question is answered by the same rule as the "how much leverage" question -- realised volatility,
    not a belief about which asset class is safer in general.

    Before `lookback` sessions of history exist for `income_symbol` or `duration_symbol`, whichever
    of the two lacks a volatility estimate gets zero weight; if both lack one, the residual is simply
    left as uninvested cash for that short warm-up rather than guessed at.
    """

    def weight_fn(i: int, closes: Mapping[str, Sequence[float]]) -> dict[str, float]:
        risk_vol = realized_vol(closes[risk_symbol], i, lookback)
        risk_w = 0.0 if not risk_vol else min(cap, target_vol / risk_vol)
        residual = 1.0 - risk_w

        income_vol = realized_vol(closes[income_symbol], i, lookback)
        duration_vol = realized_vol(closes[duration_symbol], i, lookback)
        if income_vol and duration_vol:
            inv_income, inv_duration = 1.0 / income_vol, 1.0 / duration_vol
            total = inv_income + inv_duration
            income_w = residual * inv_income / total
            duration_w = residual * inv_duration / total
        elif duration_vol:
            income_w, duration_w = 0.0, residual
        elif income_vol:
            income_w, duration_w = residual, 0.0
        else:
            income_w, duration_w = 0.0, 0.0

        return {risk_symbol: risk_w, income_symbol: income_w, duration_symbol: duration_w}

    return weight_fn


def load_closes(
    symbols: Sequence[str], start: dt.date, end: dt.date
) -> tuple[list[dt.date], dict[str, list[float]]]:
    """Aligned closes for every symbol over their common sessions, intersected rather than
    forward-filled: a synthetic bar on a day a fund did not trade would let the backtest rebalance at
    a price nobody could actually have got. Matches `drawdown_ladder.load_closes` exactly, but is
    kept local to this module rather than imported so this file has no dependency on another agent's
    file changing shape while both are being worked on in this repository at once.
    """
    settings = get_settings()
    frames = {}
    for symbol in symbols:
        frame = _full_frame(symbol, settings=settings)
        if frame.empty:
            raise SystemExit(f"no bars stored for {symbol}")
        frames[symbol] = {d: float(c) for d, c in zip(frame["ts"].dt.date, frame["close"], strict=True)}

    common = sorted(set.intersection(*(set(f) for f in frames.values())))
    dates = [d for d in common if start <= d <= end]
    if len(dates) < _TRADING_DAYS:
        raise SystemExit(
            f"only {len(dates)} common sessions for {', '.join(symbols)} in {start}..{end} -- "
            "check the narrowest symbol's first bar before widening the window"
        )
    return dates, {s: [frames[s][d] for d in dates] for s in symbols}


@dataclass(frozen=True)
class Window:
    """One backtest window. `income_symbol` is the sleeve standing in for a quality/dividend equity
    tilt (SCHD where it existed, SPY where it did not) -- `income_is_proxy` says which."""

    label: str
    start: dt.date
    end: dt.date
    income_symbol: str
    income_is_proxy: bool

    @property
    def symbols(self) -> list[str]:
        return sorted({"QLD", "IEF", "SPY", self.income_symbol})


#: SCHD's first stored session is 2011-10-20 (verified against the live store, not assumed), and it
#: binds every strategy that uses SCHD as its income sleeve. That single fact is why this module runs
#: three windows instead of one:
WINDOWS = (
    # The window that matters most, per this programme's own rules of evidence: the 2008 crash and
    # the 2011 European-debt-crisis flash drawdown, both before SCHD existed. SPY stands in for the
    # income sleeve here -- a real substitution, not a free one: SPY carries none of SCHD's quality/
    # dividend tilt, so any strategy result in this window that leans on the "income" sleeve is a
    # result about a diversified-equity substitute, not about SCHD, and is reported as such.
    Window("CRISIS  2006-2011 (SCHD does not exist yet -- SPY proxy)",
           dt.date(2006, 6, 21), dt.date(2011, 10, 19), "SPY", True),
    # The native window: every symbol used exactly as intended, bound only by SCHD's own start.
    Window("PRIMARY 2011-2026 (native SCHD)",
           dt.date(2011, 10, 20), dt.date(2026, 8, 21), "SCHD", False),
    # The longest window any of these symbols support, at the cost of the same SPY substitution as
    # CRISIS applied for the entire span rather than just the pre-2011 slice. This is the window that
    # answers "the primary test over the longest window your symbols allow" from the brief; PRIMARY
    # is the longest window that uses SCHD *natively*, and the two together are what "longest window"
    # actually means once the substitution is made explicit instead of silently picking one.
    Window("FULL    2006-2026 (SPY proxy throughout)",
           dt.date(2006, 6, 21), dt.date(2026, 8, 21), "SPY", True),
)

#: Two lookbacks, tested for every vol-aware strategy: 20 sessions (~1 trading month) is fast enough
#: to react to a regime change within weeks, and noisy enough to churn on nothing in a calm market.
#: 60 sessions (~1 trading quarter) is stable enough to filter that noise, and slow enough to still be
#: holding a stale weight three months into a new regime. Reporting both, for every strategy, is the
#: sensitivity check the brief asks for -- picking one silently would hide exactly the tradeoff this
#: paragraph describes.
LOOKBACKS = (20, 60)

#: Vol targets tested for `make_vol_target` and `make_risk_budgeted_core`. 12% and 15% are the values
#: the brief itself suggests. 20% is added deliberately as a control: a strategy that only wins by
#: sitting at a higher vol target is winning by holding more QLD, i.e. more leverage, in a period
#: (2010-2026 and later) where QLD simply did well -- see the "leverage trap" note in the report.
VOL_TARGETS = (0.12, 0.15, 0.20)

#: Circuit-breaker hysteresis band -- see `make_circuit_breaker`'s docstring for where these numbers
#: come from (QLD's own trailing-volatility percentiles, not round numbers picked blind).
BREAKER_ENTER_VOL = 0.45
BREAKER_EXIT_VOL = 0.30


def _subset(closes: Mapping[str, Sequence[float]], keys: Sequence[str]) -> dict[str, list[float]]:
    """The exact symbols a given strategy touches, and no others. `contributions.simulate` treats
    whatever dict it is handed as the entire tradable universe -- passing it a superset would let a
    weight for a symbol outside that universe evaporate into unaccounted cash instead of raising,
    which is a bug worth never writing rather than one worth debugging later.
    """
    return {k: list(closes[k]) for k in keys}


def build_strategies(window: Window) -> list[tuple[str, list[str], WeightFn]]:
    """Every strategy and baseline for one window, as (name, required symbols, weight_fn). The
    income sleeve is `window.income_symbol` throughout, so the same strategy code runs unmodified in
    every window; only the label carries the substitution note.
    """
    inc = window.income_symbol
    tag = "*" if window.income_is_proxy else ""
    inc_label = f"{inc}{tag}"

    strategies: list[tuple[str, list[str], WeightFn]] = [
        ("QLD buy & hold", ["QLD"], make_buy_hold("QLD")),
        ("SPY buy & hold", ["SPY"], make_buy_hold("SPY")),
        (f"static 60/40 {inc_label}/IEF", [inc, "IEF"],
         make_static_blend({inc: 0.60, "IEF": 0.40})),
        (f"static 40/30/30 QLD/{inc_label}/IEF", ["QLD", inc, "IEF"],
         make_static_blend({"QLD": 0.40, inc: 0.30, "IEF": 0.30})),
    ]

    for target in VOL_TARGETS:
        for lb in LOOKBACKS:
            strategies.append((
                f"voltarget {int(target * 100)}% QLD/IEF (lb{lb})",
                ["QLD", "IEF"],
                make_vol_target("QLD", "IEF", target, lb),
            ))

    for lb in LOOKBACKS:
        strategies.append((
            f"inverse-vol (lb{lb})",
            ["QLD", inc, "IEF"],
            make_inverse_vol(["QLD", inc, "IEF"], lb),
        ))

    # Names below are deliberately terse -- `contributions.summarise` pads to a 32-char field
    # and does not truncate, so a longer name pushes every numeric column out of alignment with
    # the header. The symbols and blend (always QLD/{income sleeve}/IEF, always the 40/30/30
    # weights) are constant across every row of a given family within a window and are stated
    # once in the surrounding text instead of repeated in a name that has to fit 32 characters.
    for lb in LOOKBACKS:
        strategies.append((
            f"circuit-breaker (lb{lb})",
            ["QLD", inc, "IEF"],
            make_circuit_breaker(
                {"QLD": 0.40, inc: 0.30, "IEF": 0.30}, "QLD", "QLD", lb,
                BREAKER_ENTER_VOL, BREAKER_EXIT_VOL,
            ),
        ))

    for lb in LOOKBACKS:
        strategies.append((
            f"risk-budgeted core (lb{lb})",
            ["QLD", inc, "IEF"],
            make_risk_budgeted_core("QLD", inc, "IEF", 0.12, lb),
        ))

    return strategies


#: `contributions.summarise` reports return and drawdown but not what was paid to get there. The
#: brief is explicit that this is the question vol targeting cannot be let skip: "volatility
#: targeting trades a lot, so measure the cost rather than assuming it." `_cost_line` is a second,
#: narrower table -- turnover as a multiple of what was ever contributed (a book that trades 3x its
#: own contributed capital in a decade is not the same claim as one that trades 0.3x), and slippage
#: cost as a fraction of the final balance, which is the number that actually answers "did the churn
#: eat the edge".
def _cost_line(name: str, r: contrib.ContributionResult) -> str:
    turns = r.turnover / r.total_contributed if r.total_contributed else 0.0
    cost_bps_of_final = (r.cost_paid / r.final_balance * 10_000) if r.final_balance else 0.0
    return (
        f"{name:32} turnover {turns:>6.2f}x paid-in   "
        f"cost paid ${r.cost_paid:>9,.0f}  ({cost_bps_of_final:>6.1f}bp of final balance)"
    )


def main(argv: list[str] | None = None) -> int:
    del argv  # no CLI surface -- every window and lookback runs every time, on purpose (see report)

    for window in WINDOWS:
        dates, closes = load_closes(window.symbols, window.start, window.end)
        years = len(dates) / _TRADING_DAYS
        print(f"\n=== {window.label} ===")
        print(f"window {dates[0]} .. {dates[-1]}  ({len(dates)} sessions, {years:.2f}y)\n")
        print(contrib.HEADER)
        run: list[tuple[str, contrib.ContributionResult]] = []
        for name, needed, weight_fn in build_strategies(window):
            result = contrib.simulate(dates, _subset(closes, needed), weight_fn)
            print(contrib.summarise(name, result))
            run.append((name, result))

        print("\n  -- cost of turnover (5bp slippage, charged by the harness on every dollar traded) --")
        for name, result in run:
            print("  " + _cost_line(name, result))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

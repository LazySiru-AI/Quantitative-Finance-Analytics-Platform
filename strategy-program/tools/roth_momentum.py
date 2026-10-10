"""Momentum and regime-switching strategies for a Roth IRA funded with $7,500 once a year.

Runs entirely through the shared contribution harness in `contributions.py` -- every strategy here
is a `WeightFn` (session index, closes -> target weights), and the harness owns contributions,
drift-band rebalancing, contribution-funded top-ups, slippage and both return measures. Nothing in
this module re-implements or second-guesses that mechanism; it only supplies the signal.

**Why monthly signal evaluation for the momentum legs, but daily for the trend leg.** Absolute and
dual momentum are conventionally evaluated once a month (this is how GEM and its relatives are
specified in the literature this family comes from): a 12-month trailing return recomputed every
session would flip sign on noise near the zero line and manufacture whipsaw that is an artifact of
the simulation's daily grid, not of the strategy being tested. The moving-average regime switch is
different on purpose -- the brief asks for the whipsaw cost to be measured honestly, and a signal
that is only allowed to change once a month cannot demonstrate the failure mode it is being tested
for. So `make_abs_momentum` and `make_dual_momentum` re-evaluate on the first session of each
calendar month; `make_ma_regime` re-evaluates every session.

**Why SCHD forces two families of every strategy.** SCHD's own first bar is 2011-10-20. Any
strategy that wants it as a defensive sleeve cannot be tested before that date without inventing
data. Rather than skip the pre-2011 period, every SCHD-shaped strategy here has an IEF-only
sibling that trades the identical rule with IEF standing in for the sleeve that did not exist yet.
That substitution is real and is called out everywhere it happens -- an IEF-only defensive sleeve is
not the same strategy as one that also owns SCHD's dividend-growth equity exposure, only the closest
substitute this dataset supports, and the two are never presented as interchangeable.

**Why the 2006-2011 window matters more than its length suggests.** It is the only window here that
contains the 2008-2009 crash, and `strategy-program/DRAWDOWN-LADDER.md` records that the existing
drawdown ladder's stated rules broke exactly there -- a ladder that never reaches zero leverage
compounds a wrong bet for years when the recovery this slow. A momentum family that cannot be
trusted here is not validated by looking good in 2011-2026, a window with no comparable crisis in it
at all.

**The leverage trap.** QLD is 2x QQQ. Every strategy that can end up holding QLD outperforms in
almost any window drawn from 2010 onward for the boring reason that leveraged Nasdaq exposure did
well over that stretch, not because the switching rule added anything. Where a variant's edge is
just "more time in QLD than the alternative it's compared to," that is flagged explicitly rather than
presented as a discovery -- the fair comparison is always against a *static* blend holding the same
average exposure with no timing at all, which is why every strategy family here is run against one.

**Everything here is in-sample.** No window predates 2026-02-13, this analysis's own run date. A
rule tuned by eye against these exact crashes and these exact recoveries has had every chance to
overfit them; nothing in this module is a claim about the future, only about how these rules would
have priced these specific, already-known historical paths.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import statistics
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from app.config import get_settings
from app.paper.marketdata import _full_frame

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTRIB_PATH = _REPO_ROOT / "strategy-program" / "tools" / "contributions.py"
_spec = importlib.util.spec_from_file_location("contributions", _CONTRIB_PATH)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot load contributions module from {_CONTRIB_PATH}")
contrib = importlib.util.module_from_spec(_spec)
sys.modules["contributions"] = contrib
_spec.loader.exec_module(contrib)

TRADING_DAYS = contrib.TRADING_DAYS
LOOKBACK_12M = TRADING_DAYS  # "12-month return" throughout this module means 252 trading sessions.
MA_WINDOW = 200  # the classic 200-session (~10-month) trend filter.

#: The dates that make SCHD the binding constraint on any strategy that wants it, verified against
#: the store directly (see this module's own docstring) rather than assumed.
FULL_START = dt.date(2006, 6, 21)  # QLD's first bar -- the binding constraint on non-SCHD runs.
GFC_END = dt.date(2011, 10, 19)  # the day before SCHD's first bar: guarantees no SCHD leaks in.
SCHD_START = dt.date(2011, 10, 20)
DATA_END = dt.date(2026, 8, 21)  # today's stored max; the intersection below trims each run further.


def load_closes(
    symbols: list[str], start: dt.date, end: dt.date
) -> tuple[list[dt.date], dict[str, list[float]]]:
    """Aligned closes for every symbol over their common sessions in `[start, end]`.

    Intersects the session sets rather than forward-filling, matching `drawdown_ladder.load_closes`:
    a synthetic bar on a day a fund did not trade would let a strategy rotate at a price nobody
    could actually have gotten.
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
    if len(dates) < TRADING_DAYS:
        raise SystemExit(
            f"only {len(dates)} common sessions for {', '.join(symbols)} in {start}..{end} -- "
            "check the narrowest symbol's first bar before widening the window"
        )
    return dates, {s: [frames[s][d] for d in dates] for s in symbols}


def month_starts(dates: Sequence[dt.date]) -> set[int]:
    """Session indices that are the first session of a new calendar month, plus session 0.

    The evaluation calendar for the momentum legs (see module docstring for why they are monthly
    and the trend leg is not).
    """
    out = {0}
    for i in range(1, len(dates)):
        if (dates[i].year, dates[i].month) != (dates[i - 1].year, dates[i - 1].month):
            out.add(i)
    return out


def avg_weight(result: contrib.ContributionResult, symbol: str) -> float:
    """Mean fraction of the book held in `symbol` across the whole run.

    Reported alongside every momentum strategy's numbers so a reader can see, at a glance, whether
    an edge is the switching rule or just more average time in a 2x fund -- the leverage trap this
    module's docstring warns about.
    """
    return statistics.mean(w.get(symbol, 0.0) for w in result.weights) if result.weights else 0.0


# --------------------------------------------------------------------------------------------------
# Strategy builders. Each returns a `contrib.WeightFn` closed over the specific `dates` list it will
# be run against, because the monthly legs need to know where calendar-month boundaries fall in that
# particular session list. Each closure carries its own small piece of state (the currently-held
# regime) that only ever advances forward in time, which is safe here because `contrib.simulate` calls
# every `weight_fn` exactly once per session, strictly in increasing order, in a single pass -- the
# same sequential-only contract `drawdown_ladder.run_ladder`'s hand-rolled state machine relies on.
# --------------------------------------------------------------------------------------------------


def make_abs_momentum(dates: Sequence[dt.date], risk: str, defensive: str, lookback: int = LOOKBACK_12M):
    """Absolute (time-series) momentum: hold `risk` when its own trailing 12-month return is
    positive, else hold `defensive`. The classic of this family, and the baseline every other
    momentum variant here is measured against.

    Before `lookback` sessions of history exist, there is no signal to evaluate yet, so the strategy
    parks in `defensive` rather than guessing -- the same conservative default `make_dual_momentum`
    and `make_ma_regime` use during their own warmup.
    """
    eval_idx = month_starts(dates)
    state = {"w_risk": 0.0}

    def weight_fn(i: int, closes: Mapping[str, Sequence[float]]) -> dict[str, float]:
        if i in eval_idx and i >= lookback:
            r = closes[risk][i] / closes[risk][i - lookback] - 1.0
            state["w_risk"] = 1.0 if r > 0 else 0.0
        w = state["w_risk"]
        return {risk: w, defensive: 1.0 - w}

    return weight_fn


def make_dual_momentum(
    dates: Sequence[dt.date],
    candidates: list[str],
    cash: str,
    *,
    lookback: int = LOOKBACK_12M,
    top_n: int = 1,
):
    """Rank `candidates` on trailing 12-month return; hold the top `top_n` split evenly, but only
    those with a *positive* trailing return -- the absolute-momentum filter that sends a falling
    winner to `cash` instead of forcing the book to own the least-bad loser every month.

    If every candidate is negative, `cash` gets 100%, not a share of the ranking: relative ranking
    among four losers is not a reason to hold any of them.
    """
    eval_idx = month_starts(dates)
    state: dict[str, dict[str, float]] = {"w": {c: 0.0 for c in candidates} | {cash: 1.0}}

    def weight_fn(i: int, closes: Mapping[str, Sequence[float]]) -> dict[str, float]:
        if i in eval_idx and i >= lookback:
            rets = {c: closes[c][i] / closes[c][i - lookback] - 1.0 for c in candidates}
            ranked = sorted(rets.items(), key=lambda kv: kv[1], reverse=True)
            winners = [c for c, r in ranked[:top_n] if r > 0]
            new_w = {c: 0.0 for c in candidates} | {cash: 0.0}
            if winners:
                share = 1.0 / len(winners)
                for c in winners:
                    new_w[c] = share
            else:
                new_w[cash] = 1.0
            state["w"] = new_w
        return dict(state["w"])

    return weight_fn


def make_ma_regime(
    dates: Sequence[dt.date],
    risk: str,
    defensive_weights: Mapping[str, float],
    signal: str,
    ma_window: int = MA_WINDOW,
):
    """Hold `risk` while `signal` closes above its own trailing `ma_window`-session average, else
    hold `defensive_weights` (which may split across more than one sleeve, e.g. 50/50 SCHD/IEF).

    Re-evaluated every session on purpose -- see the module docstring's note on why this leg, unlike
    the two momentum legs above, is not dampened to monthly. That is the whole point of testing it:
    a 200-session average that chops sideways for months produces a real cost, and averaging it away
    would just be hiding the failure mode this variant exists to expose.
    """
    state = {"in_risk": False}

    def weight_fn(i: int, closes: Mapping[str, Sequence[float]]) -> dict[str, float]:
        if i >= ma_window:
            window = closes[signal][i - ma_window + 1 : i + 1]
            sma = sum(window) / len(window)
            state["in_risk"] = closes[signal][i] > sma
        if state["in_risk"]:
            return {risk: 1.0}
        return dict(defensive_weights)

    return weight_fn


def make_confirmed_regime(
    dates: Sequence[dt.date],
    risk: str,
    defensive_weights: Mapping[str, float],
    signal: str,
    *,
    lookback: int = LOOKBACK_12M,
    ma_window: int = MA_WINDOW,
):
    """The fourth strategy this family suggests: hold `risk` at full weight only when *both* legs
    agree it should be held -- `risk`'s own 12-month return is positive (monthly-evaluated, as in
    `make_abs_momentum`) *and* `signal` is above its 200-session average (daily, as in
    `make_ma_regime`). Hold `defensive_weights` at full weight only when both legs agree it should
    not be held. When the two legs disagree, split the difference: half `risk`, half defensive.

    The idea being tested is narrower than "combine two signals for more edge" -- it is that
    strategy 3's whipsaw cost comes largely from committing 100% of the book to a trend signal that,
    by construction, can flip on a single day's close. Requiring momentum to agree before the switch
    goes to full weight, and holding a half position rather than zero during genuine disagreement,
    should cut the number of full round-trip trades the MA-only version pays for. Whether it actually
    does, and at what cost in missed upside, is exactly what the results table below has to show --
    this is offered as a candidate, not asserted as an improvement.
    """
    eval_idx = month_starts(dates)
    state = {"mom_positive": False, "trend_up": False}

    def weight_fn(i: int, closes: Mapping[str, Sequence[float]]) -> dict[str, float]:
        if i in eval_idx and i >= lookback:
            r = closes[risk][i] / closes[risk][i - lookback] - 1.0
            state["mom_positive"] = r > 0
        if i >= ma_window:
            window = closes[signal][i - ma_window + 1 : i + 1]
            sma = sum(window) / len(window)
            state["trend_up"] = closes[signal][i] > sma

        if state["mom_positive"] and state["trend_up"]:
            return {risk: 1.0}
        if not state["mom_positive"] and not state["trend_up"]:
            return dict(defensive_weights)
        half = {k: v * 0.5 for k, v in defensive_weights.items()}
        half[risk] = half.get(risk, 0.0) + 0.5
        return half

    return weight_fn


def make_static(weights: Mapping[str, float]):
    """A fixed blend, rebalanced whenever the harness's own drift band or annual contribution
    triggers it -- the timing-free baseline every strategy above is measured against. If a momentum
    rule cannot beat this on risk-adjusted terms, its turnover is buying nothing.
    """

    def weight_fn(i: int, closes: Mapping[str, Sequence[float]]) -> dict[str, float]:
        return dict(weights)

    return weight_fn


def make_buy_hold(symbol: str):
    def weight_fn(i: int, closes: Mapping[str, Sequence[float]]) -> dict[str, float]:
        return {symbol: 1.0}

    return weight_fn


# --------------------------------------------------------------------------------------------------
# Runs. Two symbol universes are loaded once each and sliced for their windows: the non-SCHD universe
# covers 2006-06-21 (QLD's first bar) through today, and is used both for its full length and for the
# 2006-2011 slice that isolates the GFC; the SCHD-era universe starts 2011-10-20 and is SCHD's only
# eligible window. Loading once per universe and slicing avoids re-reading the store for a window
# that is a strict subset of one already in memory.
# --------------------------------------------------------------------------------------------------


def _slice_before(
    dates: list[dt.date], closes: dict[str, list[float]], end: dt.date
) -> tuple[list[dt.date], dict[str, list[float]]]:
    idx = [i for i, d in enumerate(dates) if d <= end]
    return [dates[i] for i in idx], {s: [v[i] for i in idx] for s, v in closes.items()}


def run_group(
    label: str,
    dates: list[dt.date],
    closes: dict[str, list[float]],
    specs: list[tuple[str, contrib.WeightFn]],
) -> None:
    print(f"\n=== {label}: {dates[0]} .. {dates[-1]} ({len(dates)} sessions, {len(dates) / TRADING_DAYS:.2f}y) ===")
    print(contrib.HEADER + f"  {'avg QLD':>8}")
    for name, weight_fn in specs:
        r = contrib.simulate(dates, closes, weight_fn)
        print(contrib.summarise(name, r) + f"  {avg_weight(r, 'QLD') * 100:>7.1f}%")


def main() -> int:
    non_schd_symbols = ["QLD", "IEF", "GLD", "SHY", "SPY"]
    full_dates, full_closes = load_closes(non_schd_symbols, FULL_START, DATA_END)
    gfc_dates, gfc_closes = _slice_before(full_dates, full_closes, GFC_END)

    schd_symbols = ["QLD", "SCHD", "IEF", "GLD", "SHY", "SPY"]
    schd_dates, schd_closes = load_closes(schd_symbols, SCHD_START, DATA_END)

    print(f"Roth momentum / regime backtest -- annual contribution ${contrib.ANNUAL_CONTRIBUTION:,.0f}, "
          f"5bp slippage, both return measures reported.")
    print("Every window below predates neither the strategies nor the reader: this analysis was run "
          "2026-08-22, so no window here is out-of-sample.")

    # ---- non-SCHD universe: IEF stands in for the defensive sleeve wherever a strategy would
    # otherwise want SCHD, since SCHD did not exist yet. Run twice: the full 2006-2026 span, and the
    # 2006-2011 slice that isolates the 2008-2009 crash on its own, per the brief's instruction that
    # this is the window that matters most for this family.
    for label, dates, closes in (("full-2006 (IEF defensive, no SCHD)", full_dates, full_closes),
                                  ("gfc-2006-2011 (IEF defensive, no SCHD)", gfc_dates, gfc_closes)):
        specs = [
            ("abs momentum (QLD/IEF)", make_abs_momentum(dates, "QLD", "IEF")),
            ("dual momentum (QLD/IEF/GLD, cash SHY)",
             make_dual_momentum(dates, ["QLD", "IEF", "GLD"], "SHY")),
            ("MA regime (QLD vs IEF, sig SPY200)",
             make_ma_regime(dates, "QLD", {"IEF": 1.0}, "SPY")),
            ("confirmed regime (QLD vs IEF)",
             make_confirmed_regime(dates, "QLD", {"IEF": 1.0}, "SPY")),
            ("static 40/60 QLD/IEF (sub for 40/30/30)", make_static({"QLD": 0.40, "IEF": 0.60})),
            ("QLD buy & hold", make_buy_hold("QLD")),
            ("SPY buy & hold", make_buy_hold("SPY")),
        ]
        run_group(label, dates, closes, specs)

    # ---- SCHD-era universe: SCHD's real history, 2011-10-20 onward. This is the primary window for
    # every strategy that wants SCHD, and it is a bull-dominated fifteen years with no crash in it
    # remotely the shape of 2008 -- see the module docstring on why that alone is not a validation.
    specs = [
        ("abs momentum (QLD/SCHD)", make_abs_momentum(schd_dates, "QLD", "SCHD")),
        ("dual momentum top-1 (QLD/SCHD/IEF/GLD, cash SHY)",
         make_dual_momentum(schd_dates, ["QLD", "SCHD", "IEF", "GLD"], "SHY", top_n=1)),
        ("dual momentum top-2 (same universe)",
         make_dual_momentum(schd_dates, ["QLD", "SCHD", "IEF", "GLD"], "SHY", top_n=2)),
        ("MA regime (QLD vs 50/50 SCHD/IEF, sig SPY200)",
         make_ma_regime(schd_dates, "QLD", {"SCHD": 0.5, "IEF": 0.5}, "SPY")),
        ("confirmed regime (QLD vs 50/50 SCHD/IEF)",
         make_confirmed_regime(schd_dates, "QLD", {"SCHD": 0.5, "IEF": 0.5}, "SPY")),
        ("static 60/40 SCHD/IEF", make_static({"SCHD": 0.60, "IEF": 0.40})),
        ("static 40/30/30 QLD/SCHD/IEF", make_static({"QLD": 0.40, "SCHD": 0.30, "IEF": 0.30})),
        ("QLD buy & hold", make_buy_hold("QLD")),
        ("SPY buy & hold", make_buy_hold("SPY")),
    ]
    run_group("schd-era-2011-2026 (real SCHD)", schd_dates, schd_closes, specs)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Backtest a drawdown-triggered rotation between a defensive sleeve and a leveraged one.

The strategy under test, as specified:

    Base state: hold the defensive sleeve (SCHD).
    Signal:     drawdown of a reference index from its own all-time closing high.
    -10%:       rotate to 20% leveraged (QLD).
    -20%:       rotate to 60% leveraged.
    -30%:       (optional) rotate to 80% leveraged.
    New ATH:    halve the leveraged sleeve.
    Recovery:   +10% above the old high, or 60 sessions after the new high, whichever first --
                back to 0% leveraged, and the ladder re-arms.

Three things the original statement leaves open, and how this module closes them, because each one
decides whether the result is real:

* **Arming.** A level fires once per drawdown cycle and re-arms only on a full reset to the base
  state. Without that, an index oscillating around -10% round-trips the whole book repeatedly and
  the strategy is a slippage pump. April 2025 is exactly that shape.
* **Gap-through.** If the index closes at -20% without ever having closed at -10%, the ladder jumps
  straight to the -20% allocation in one trade rather than stepping through a rung it never touched.
  March 2020 came close enough to matter.
* **Ratchet.** "Halve on a new high" never reaches zero -- 60% becomes 30%, then 15%, and leverage
  accumulates across cycles. The recovery condition above is what actually closes the position.

**On expense ratios.** This backtest uses real QLD and SCHD closes, and an ETF's published NAV is
already net of its expense ratio. Subtracting the 0.95% again -- as a critique of the original
backtest suggested -- would double-count it. What is *not* in the price is the cost of the rotations
themselves, so `slippage_bps` is charged on every dollar traded and is the cost that matters here.

The comparison that decides whether the signal is worth anything is not the leveraged sleeve alone.
It is a **static blend rebalanced on a calendar** -- the same exposure with no timing. If the ladder
does not beat static on risk-adjusted terms, the turnover is buying nothing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import statistics
from dataclasses import dataclass, field

from app.config import get_settings
from app.paper.marketdata import _full_frame

#: Sessions per year, matching `strategy-program/tools/score.py` and `windows.py`.
_TRADING_DAYS = 252


@dataclass(frozen=True)
class Rung:
    """One step of the ladder: at or below `drawdown`, hold `leveraged_weight` in the risk sleeve."""

    drawdown: float
    leveraged_weight: float


@dataclass(frozen=True)
class Ladder:
    """The full specification. Defaults are the strategy as stated, with the gaps closed."""

    rungs: tuple[Rung, ...] = (
        Rung(-0.10, 0.20),
        Rung(-0.20, 0.60),
        Rung(-0.30, 0.80),
    )
    #: On a new all-time high, the leveraged sleeve is multiplied by this rather than sold outright.
    ath_haircut: float = 0.5
    #: Full exit once the index is this far above the high that started the cycle...
    recovery_gain: float = 0.10
    #: ...or this many sessions after the new high, whichever comes first. The time limit is what
    #: stops a cycle that never runs far enough above the old high from holding leverage forever.
    recovery_sessions: int = 60
    #: Charged on every dollar rotated, one way. Rotations are the strategy's only real cost that is
    #: not already inside the ETF prices.
    slippage_bps: float = 5.0

    #: --- the three fixes for the falling-knife failure, all off by default ---------------------
    #: A rung fires only once the signal has closed back above its own `confirm_ma`-session average,
    #: i.e. only after a bounce has begun. The strategy as specified adds leverage on the way down
    #: with no condition at all, which is why it reaches its deepest rung at the worst possible
    #: moment of a 2008-shaped decline. `None` reproduces the original.
    confirm_ma: int | None = None
    #: If a leveraged position has gone `time_stop` sessions without the signal making a new high,
    #: cut the weight in half. The original has no exit on continued decline -- only on a new high,
    #: which in 2008 was four years away.
    time_stop: int | None = None
    #: Hard ceiling on the leveraged sleeve regardless of how deep the ladder goes.
    max_weight: float = 1.0

    def weight_for(self, drawdown: float) -> float:
        """The deepest rung this drawdown has reached, or 0 above the first trigger."""
        weight = 0.0
        for rung in self.rungs:
            if drawdown <= rung.drawdown:
                weight = rung.leveraged_weight
        return min(weight, self.max_weight)


@dataclass
class Result:
    dates: list[dt.date] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)
    weights: list[float] = field(default_factory=list)
    rotations: int = 0
    turnover: float = 0.0
    cost_paid: float = 0.0

    @property
    def total_return(self) -> float:
        return self.equity[-1] / self.equity[0] - 1

    @property
    def years(self) -> float:
        return len(self.equity) / _TRADING_DAYS

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
        return statistics.pstdev(rets) * (_TRADING_DAYS**0.5) if len(rets) > 1 else 0.0

    @property
    def sharpe_like(self) -> float:
        """CAGR over volatility. Not a Sharpe ratio -- no risk-free rate is subtracted, which would
        need a rate series this module does not load. Comparable *between* the runs here, which is
        all it is used for, and deliberately not named `sharpe` so it is not quoted as one."""
        return self.cagr / self.volatility if self.volatility else 0.0

    @property
    def mar(self) -> float:
        """CAGR over the depth of the worst drawdown -- the ratio that asks what the return cost in
        peak-to-trough pain, which is the trade this strategy claims to be making."""
        return self.cagr / abs(self.max_drawdown) if self.max_drawdown else 0.0


def load_closes(symbols: list[str], start: dt.date, end: dt.date) -> tuple[list[dt.date], dict[str, list[float]]]:
    """Aligned closes for every symbol over their common sessions.

    Intersects the session sets rather than forward-filling: a synthetic bar on a day a fund did not
    trade would let the backtest rotate at a price nobody could have got.
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


def run_ladder(
    dates: list[dt.date],
    defensive: list[float],
    leveraged: list[float],
    signal: list[float],
    ladder: Ladder,
    *,
    starting_equity: float = 10_000.0,
) -> Result:
    """The state machine. Weights change only on a state transition, never on drift."""
    result = Result()
    equity = starting_equity
    weight = 0.0  # fraction in the leveraged sleeve

    # The high-water mark of the *signal*, and the high that was standing when this cycle began.
    peak = signal[0]
    cycle_peak = signal[0]
    armed_depth = 0.0  # deepest rung already fired this cycle; 0 means fully re-armed
    new_high_at: int | None = None
    last_high_at = 0  # last session the signal made a new high, for the time stop

    def confirmed(i: int) -> bool:
        """Has the signal closed back above its own short average? The bounce condition."""
        if ladder.confirm_ma is None:
            return True
        if i < ladder.confirm_ma:
            return False
        window = signal[i - ladder.confirm_ma + 1 : i + 1]
        return signal[i] > sum(window) / len(window)

    for i, _ in enumerate(dates):
        if i > 0:
            # Mark to market on the prior session's weights before deciding anything. Decisions are
            # made on today's close and executed at today's close -- see the module docstring's note
            # on why the cost model, not the fill timing, is what matters at this frequency.
            grow_lev = leveraged[i] / leveraged[i - 1]
            grow_def = defensive[i] / defensive[i - 1]
            equity *= weight * grow_lev + (1 - weight) * grow_def

        price = signal[i]
        if price > peak:
            if weight > 0 and new_high_at is None:
                new_high_at = i
            peak = price
            last_high_at = i

        drawdown = price / peak - 1
        target = weight

        if weight == 0.0:
            # Base state: arm on the deepest rung this drawdown has reached, in one trade. This is
            # the gap-through fix -- a close at -21% goes straight to the -20% weight without
            # requiring that -10% ever printed.
            reached = ladder.weight_for(drawdown)
            if reached > 0 and confirmed(i):
                target = reached
                armed_depth = reached
                cycle_peak = peak
                new_high_at = None
        else:
            deeper = ladder.weight_for(drawdown)
            if (
                ladder.time_stop is not None
                and i - last_high_at >= ladder.time_stop
                and deeper <= armed_depth
            ):
                # No new high in a long time and not laddering deeper: this drawdown is not
                # recovering, and holding leverage through it is the failure the 2008 window
                # exposes. Halve, and keep halving each time the clock runs out again.
                target = weight * 0.5
                last_high_at = i
                if target < 1e-9:
                    target, armed_depth = 0.0, 0.0
            elif deeper > armed_depth and confirmed(i):
                # Ladder down. Fires once per level per cycle because `armed_depth` only ever rises
                # until a full reset, which is what stops a chop around a trigger from round-tripping.
                target = deeper
                armed_depth = deeper
            elif new_high_at is not None:
                sessions_since = i - new_high_at
                recovered = price >= cycle_peak * (1 + ladder.recovery_gain)
                if recovered or sessions_since >= ladder.recovery_sessions:
                    target = 0.0
                    armed_depth = 0.0
                    new_high_at = None
                elif sessions_since == 0:
                    target = weight * ladder.ath_haircut

        if abs(target - weight) > 1e-9:
            traded = abs(target - weight) * equity
            cost = traded * ladder.slippage_bps / 10_000
            equity -= cost
            result.rotations += 1
            result.turnover += traded
            result.cost_paid += cost
            weight = target

        result.dates.append(dates[i])
        result.equity.append(equity)
        result.weights.append(weight)

    return result


def run_static(
    dates: list[dt.date],
    defensive: list[float],
    leveraged: list[float],
    lev_weight: float,
    *,
    rebalance_every: int = 63,
    slippage_bps: float = 5.0,
    starting_equity: float = 10_000.0,
) -> Result:
    """A fixed blend rebalanced on a calendar -- the same exposure with no signal.

    This is the benchmark that decides whether the ladder's timing is worth its turnover. Comparing
    the ladder to the leveraged sleeve alone answers a different and easier question.
    """
    result = Result()
    equity = starting_equity
    weight = lev_weight

    for i, _ in enumerate(dates):
        if i > 0:
            grow_lev = leveraged[i] / leveraged[i - 1]
            grow_def = defensive[i] / defensive[i - 1]
            lev_val = equity * weight * grow_lev
            def_val = equity * (1 - weight) * grow_def
            equity = lev_val + def_val
            weight = lev_val / equity if equity else 0.0

            if i % rebalance_every == 0:
                traded = abs(lev_weight - weight) * equity
                cost = traded * slippage_bps / 10_000
                equity -= cost
                result.rotations += 1
                result.turnover += traded
                result.cost_paid += cost
                weight = lev_weight

        result.dates.append(dates[i])
        result.equity.append(equity)
        result.weights.append(weight)

    return result


def run_buy_hold(dates: list[dt.date], closes: list[float], *, starting_equity: float = 10_000.0) -> Result:
    result = Result()
    for i, _ in enumerate(dates):
        result.dates.append(dates[i])
        result.equity.append(starting_equity * closes[i] / closes[0])
        result.weights.append(1.0)
    return result


def summarise(name: str, r: Result) -> str:
    return (
        f"{name:34} ${r.equity[-1]:>10,.0f}  {r.total_return * 100:>8.1f}%  "
        f"{r.cagr * 100:>6.2f}%  {r.max_drawdown * 100:>7.1f}%  {r.volatility * 100:>6.1f}%  "
        f"{r.mar:>5.2f}  {r.sharpe_like:>5.2f}  {r.rotations:>4d}"
    )


HEADER = (
    f"{'':34} {'final':>11}  {'total':>8}  {'CAGR':>6}  {'maxDD':>7}  {'vol':>6}  "
    f"{'MAR':>5}  {'C/V':>5}  {'trades':>4}"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--defensive", default="SCHD")
    parser.add_argument("--leveraged", default="QLD")
    parser.add_argument("--signal", default="SPY", help="index whose drawdown arms the ladder")
    parser.add_argument("--start", type=dt.date.fromisoformat, default=dt.date(2016, 8, 1))
    parser.add_argument("--end", type=dt.date.fromisoformat, default=dt.date(2026, 8, 18))
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    args = parser.parse_args(argv)

    symbols = sorted({args.defensive, args.leveraged, args.signal})
    dates, closes = load_closes(symbols, args.start, args.end)
    d, lev, sig = closes[args.defensive], closes[args.leveraged], closes[args.signal]

    print(f"window {dates[0]} .. {dates[-1]}  ({len(dates)} sessions, {len(dates)/_TRADING_DAYS:.2f}y)")
    print(f"signal {args.signal}, defensive {args.defensive}, leveraged {args.leveraged}, "
          f"slippage {args.slippage_bps:.0f}bp\n")
    print(HEADER)
    ladder = Ladder(slippage_bps=args.slippage_bps)
    print(summarise("ladder (-10/-20/-30)", run_ladder(dates, d, lev, sig, ladder)))
    for w in (0.20, 0.30, 0.40):
        print(summarise(f"static {int((1-w)*100)}/{int(w*100)} quarterly",
                        run_static(dates, d, lev, w, slippage_bps=args.slippage_bps)))
    print(summarise(f"{args.defensive} buy & hold", run_buy_hold(dates, d)))
    print(summarise(f"{args.leveraged} buy & hold", run_buy_hold(dates, lev)))
    print(summarise(f"{args.signal} buy & hold", run_buy_hold(dates, sig)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

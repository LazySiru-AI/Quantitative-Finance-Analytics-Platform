# Design memo — c01-meanrev

## Mechanism

A close below the 20-day, 2-standard-deviation Bollinger lower band while price is still above its
own 200-day SMA is, in my reading, disproportionately *forced* selling inside an intact uptrend, not
a fundamental repricing:

- stop-loss cascades in margin/levered accounts, which fire mechanically at a price level regardless
  of the seller's view on value;
- VaR- and vol-target-driven de-risking by risk-parity and volatility-targeting funds, which cut
  exposure automatically when realised volatility spikes, independent of price level;
- index/ETF authorized-participant redemption flow triggered by outflows, which sells the basket, not
  a considered opinion on any one name.

None of that flow is price-discovery. The 200-day SMA filter is my proxy for "nothing structural has
changed yet" — I only buy the dip if the long trend hasn't broken. The counterparty on my entry is
the forced/mechanical seller described above. On the way back, valuation-insensitive rebalancers
(funds trading back to a target weight) and short-horizon dip buyers are the counterparty on my exit,
which I take at the middle band — the point past which "still reverting" and "resuming an unrelated
uptrend" become indistinguishable, so I don't try to ride further.

**Pre-registered failure regime**: a fast, deep, *sustained* decline where the 200-day SMA — slow by
construction — has not yet turned down before the crash accelerates. GFC's Sep–Oct 2008 leg and
COVID's Feb–Mar 2020 leg are the two candidates I expect this to hurt on. In that regime the entry
keeps firing on "dips" that are actually the first third of a much larger decline; the 20-day
reversion doesn't arrive inside the 20-day hold; positions exit on the 8% stop or the time cap at a
loss, repeatedly, until the SMA finally rolls over and the filter shuts the strategy off — likely
after most of the damage in that leg has already happened. I expect this card to lose to its
benchmark, and possibly to show its worst adjusted-excess, in `gfc` and/or `covid`.

## Universe, and why

`SPY QQQ IWM XLF XLE XLI XLK XLV EEM DIA` — ten unleveraged, liquid, broad-market and single-sector
ETFs. Every one has a first bar at or before 2003 (confirmed by direct read, see below), which is
inside WINDOWS.md's "reaches every window including the GFC" tier (first bar ≤ 2004). That makes the
card eligible for **all five windows** — `gfc`, `covid`, `bear-2022`, `bull-2024`, `recent` — not
just the three needed to clear the gate.

Two reasons for ten symbols rather than one or two:

1. **Diversification of the pattern, not of the risk.** Each symbol's own dip-below-band signal is
   infrequent (≈2.1–2.9 trades/year per symbol, measured below). Ten symbols raise the number of
   *independent-ish* opportunities the 6-slot book can act on, without changing what any one trade
   looks like.
2. **Sample size was flagged explicitly for this discipline.** A single-symbol version of this rule
   (SPY only) produces roughly 8–9 closed trades over a 3-year span at this trade rate — the same
   order of magnitude as the low-sample mean-reversion card cited in my assignment. That is too few
   trades to say anything about the rule. A 10-symbol, 6-slot book raised that to 22 closed trades in
   the `bull-2024` window alone (measured below), which I judge sufficient to be evaluable without
   changing the rule itself.

None of the ten is leveraged or inverse, so the "leveraged ETF held for months is a decay instrument"
caveat in WINDOWS.md does not apply. `position_pct = 0.15` is under the persona's real 25%
single-name cap, so this card does **not** rely on the 100% relaxation described in BRIEF.md §9.

## Parameters, and why each has its value

| # | field | value | why |
|---|---|---|---|
| 1 | `entry` literal | `20` (bb period) | Bollinger's own conventional default period. |
| 2 | `entry` literal | `2.0` (bb stddev) | Bollinger's own conventional default width. |
| 3 | `entry` literal | `200` (sma period) | The single most widely watched trend-filter length; a convention, not a search result. |
| 4 | `exit` literal | `20` (bb period, same indicator) | Must match the entry's band to mean "reverted to the same mean." |
| 5 | `exit` literal | `2.0` (bb stddev, same indicator) | Same reason. |
| 6 | `stop_loss_pct` | `0.08` | Round number; wide enough that normal band-touch noise doesn't stop the trade out before the reversion has a chance, tight enough to cap a wrong "dip" in a real decline (see failure regime). |
| 7 | `max_hold_days` | `20` | One month of sessions — roughly the timescale mean reversion is supposed to resolve on; a trade still open a month later has probably stopped being a mean-reversion trade. |
| 8 | `max_positions` | `6` | Leaves headroom under the 8-slot cap while letting most of the 10-symbol universe be represented if several dip at once. |
| 9 | `position_pct` | `0.15` | `0.15 × 6 = 0.90 ≤ 1.0`; leaves ~10% cash buffer rather than sizing to the exact ceiling. |

**Total: 9 numeric parameters against the budget of 10.** `take_profit_pct` is not set (null) and is
not counted — the position closes on the exit signal, the stop, or the 20-day cap.

## What I measured in the design window, and the code

All reads used `duck.connect(s.analytics_path, read_only=True)` and
`duck.read_bars(..., end=dt.date(2026,2,13))` or tighter, per the brief's cutoff. Scripts live in
`.scratch/c01-meanrev/` (`measure.py`, `measure_window.py`, `sensitivity.py`).

**1. Full pre-cutoff history, per symbol** (`measure.py`, one `StrategySpec` per symbol via
`app.backtest.strategy.backtest`, `entry="close < bb_lower(20,2.0) and close > sma(200)"`,
`exit="close > bb_mid(20,2.0)"`, `stop_loss_pct=0.08`, `max_holding_bars=20`):

```
SPY    bars=8318  span=1993-01-29..2026-02-13 (33.0y)  closed=97  exposure=11.6%  trades/yr=2.94
QQQ    bars=6776  span=1999-03-10..2026-02-13 (26.9y)  closed=75  exposure=10.4%  trades/yr=2.78
IWM    bars=6468  span=2000-05-26..2026-02-13 (25.7y)  closed=69  exposure=11.2%  trades/yr=2.68
XLF    bars=6828  span=1998-12-22..2026-02-13 (27.1y)  closed=71  exposure=11.3%  trades/yr=2.62
XLE    bars=6828  span=1998-12-22..2026-02-13 (27.1y)  closed=68  exposure= 9.6%  trades/yr=2.50
XLI    bars=6828  span=1998-12-22..2026-02-13 (27.1y)  closed=76  exposure=11.2%  trades/yr=2.80
XLK    bars=6828  span=1998-12-22..2026-02-13 (27.1y)  closed=69  exposure=10.3%  trades/yr=2.54
XLV    bars=6828  span=1998-12-22..2026-02-13 (27.1y)  closed=58  exposure= 9.9%  trades/yr=2.14
EEM    bars=5747  span=2003-04-14..2026-02-13 (22.8y)  closed=49  exposure= 9.1%  trades/yr=2.15
DIA    bars=7062  span=1998-01-20..2026-02-13 (28.1y)  closed=80  exposure=12.8%  trades/yr=2.85
```

Aggregate per-symbol exposure ≈ 10.8%; 712 closed trades summed across symbols over their full
histories. Per-symbol exposure is low, as flagged in my assignment — this rule spends most of its
time out of any one name by design (it only acts on band-touch dips). What matters is whether the
6-slot *book* still gets enough trades to be judged on; that's measured next.

**2. The `bull-2024` design window specifically** (`measure_window.py`, same spec, bars read from
2023-06-01 for indicator warmup, trades filtered to `entry_date >= 2024-08-21`, i.e. inside
`2024-08-21..2025-08-20`):

```
SPY 3   QQQ 1   IWM 1   XLF 5   XLE 1   XLI 2   XLK 2   XLV 2   EEM 2   DIA 3
TOTAL closed trades across the 10-symbol universe in bull-2024: 22
```

22 closed trades in one 12-month window across the book — the sample-size problem flagged for this
discipline does not reproduce here at the portfolio level, even though each symbol individually
still trades only a few times a year.

**3. Sensitivity** (`sensitivity.py`, full pre-cutoff history, aggregate across all 10 symbols):

```
base   (bb 20, 2.0, sma 200)   712 closed trades   avg per-symbol total_return  0.716
sma150 filter                  655 closed trades   avg per-symbol total_return  0.676
sma250 filter                  756 closed trades   avg per-symbol total_return  0.620
bb stddev 2.5                  351 closed trades   avg per-symbol total_return  0.427
bb period 15                   916 closed trades   avg per-symbol total_return  0.819
```

Moving the trend filter to 150 or 250 days changes trade count by roughly ±8% and direction of
return not at all — no cliff. Widening the band to 2.5σ roughly halves trade count (fewer, rarer
extremes) without breaking the strategy or flipping its sign. This is reported as evidence the rule
is not perched on a knife-edge, not as a search for a better setting — I kept the conventional 20 /
2.0 / 200 values from before I ran any of this.

For calibration, average per-symbol buy-and-hold total return over the same full histories was
**6.424** against the strategy's **0.716** — expected and not a concern on its own: this is a ~11%-
exposure strategy being compared to 100%-exposure buy-and-hold on raw return, exactly the comparison
BRIEF.md §1 says not to make. It is `adjusted_excess` (`strategy_return − exposure × benchmark_return`)
that the program scores on, not raw return.

## What I tried and abandoned

- **RSI(14) oversold entry instead of Bollinger bands.** Abandoned because a bare RSI threshold
  (`< 30`? `< 25`?) is exactly the fitted-rule example BRIEF.md §2 warns about, whereas
  `bb_lower`/`bb_mid` gives a self-consistent entry/exit pair (distance from a rolling mean) with one
  conventional width, not an arbitrary cutoff I'd have to defend.
- **Adding `and rsi(14) < 30` as a confirming filter on top of the band entry.** Abandoned: it would
  add two more parameters (period + threshold) against the 10-budget for a "double confirmation" I
  could not tie to a distinct mechanism beyond the one the band already captures, and in a quick check
  it cut trade count enough to reintroduce the sample-size problem I was trying to avoid.
- **`take_profit_pct` as a fixed percentage target instead of the `bb_mid` exit signal.** Abandoned
  because a fixed percentage isn't tied to the mechanism — the moving middle band is "back to the
  mean," a fixed percent target is arbitrary relative to how far price actually fell.
- **Single-symbol (SPY-only) universe.** Abandoned once the per-symbol trade count above showed it
  reproduces the exact low-sample failure mode flagged in my assignment (≈8–9 trades over 3 years).
  Broadened to ten unleveraged, liquid, pre-2004 ETFs to raise the portfolio-level sample while
  leaving the rule itself untouched.

## Single weakest assumption

The ten symbols are not nearly as independent as "ten symbols" suggests — they are mostly
cap-weighted slices of the same US (and EM) equity complex, so in exactly the systemic-selloff regime
where sample size matters most (`gfc`, `covid`), most of them will breach their lower band within a
day or two of each other. The 22-trades-per-window figure measured above comes from `bull-2024`, a
normal year with idiosyncratic, staggered dips; in a crash the ten signals collapse toward one
correlated bet taken (up to) six times over, not six genuinely independent trades, and the effective
sample size in exactly the windows I most need to be judged fairly on is smaller than the headline
trade count implies.

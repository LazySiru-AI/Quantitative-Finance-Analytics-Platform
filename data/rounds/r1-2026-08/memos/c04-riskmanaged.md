# c04-riskmanaged — All-Weather Trend Sleeve

## Mechanism

The rule holds an asset while `close > sma(200)` and exits when `close < sma(200)`, applied
independently and identically to four exposures: US equities (`SPY`), international developed
equities (`EFA`), long Treasuries (`TLT`), and gold (`GLD`).

A 200-day moving average is a slow proxy for whether the marginal buyer still controls the tape.
Below it, the pattern that repeats across decades is forced, non-price-sensitive selling: pensions
and mandate-bound funds de-risking after a sustained decline, and levered holders forced out by
drawdown, keep supplying stock (or bonds) into a market that has already fallen for months. Staying
out while price is below its own 200-day average avoids selling into that flow and only re-enters
once buyers have plausibly re-established control on a monthly-to-quarterly timescale — this is a
structural liquidity/flow argument, not a claim that the average itself has predictive power.

The reason this is a **risk-managed** design rather than a plain trend card is that the filter is
applied to four exposures that do not trend together. In a rate-driven equity bear, the flight-to-
quality bid that keeps bonds and gold trending up is a countercyclical buyer this book can ride while
equities are excluded — so exposure during an equity bear does not collapse to zero, it *rotates*,
and the return in that rotated sleeve is still coming from a real trending asset, not from cash.

## Universe and eligibility

`SPY`, `EFA`, `TLT`, `GLD` — all four have a first bar at or before 2004 per `WINDOWS.md`'s top
tier ("reaches every window including the GFC"). Guard-checked below with no failures.

**Eligible for all five windows: `gfc`, `covid`, `bear-2022`, `bull-2024`, `recent`.**

Why these four and not more: I started from the idea that a risk-managed sleeve should hold assets
whose crisis behavior actually differs, not just different tickers in the same asset class. I
measured pairwise daily-return correlation over the full overlapping history (code and output below)
and found `SPY`/`EFA` at 0.86 (effectively one "growth equity" bloc) and `IEF`/`TLT` at 0.91
(effectively one "duration" bloc). I dropped `IEF` because `TLT` captures the same rates exposure
with more convexity and adding both was consuming a slot for ~0.91-correlated redundancy rather than
diversification. `GLD` was the one exposure with low correlation to everything else (0.05–0.20) and
is the cleanest true diversifier in the set. I kept `EFA` alongside `SPY` despite the 0.86
correlation because it still carries a different central-bank/currency regime, and four symbols at
`position_pct = 0.25` lets the constraint `position_pct * max_positions <= 1.001` bind exactly at
1.00 with no wasted headroom.

## Parameters — count against budget of 10

| # | parameter | value | why |
|---|---|---|---|
| 1 | `entry` literal | `sma(200)` → `200` | Most widely watched trend convention; not searched. |
| 2 | `exit` literal | `sma(200)` → `200` | Mirrors the entry filter — one trend definition, not two. |
| 3 | `stop_loss_pct` | `0.12` | Backstop against a fast shock (e.g. COVID) that a 200-day average is too slow to react to before real damage is done. Chosen from the assets' known volatility (SPY/EFA/GLD/TLT all sit in the ~13–18% annualized-vol range), not fitted: a 12% adverse move against previous close requires an unusual run of down days for these instruments outside a genuine crash. |
| 4 | `max_positions` | `4` | One slot per exposure; all four are always eligible to be held simultaneously. |
| 5 | `position_pct` | `0.25` | `4 × 0.25 = 1.00`, satisfying the `<= 1.001` constraint with equal weighting and no cash left idle by design when every leg is trending. |

**Total: 5 numbers chosen, against a budget of 10.** No `take_profit_pct`, no `max_hold_days` — the
exit condition (`close < sma(200)`) is the only planned close; the point of a trend sleeve is to stay
in a winning trend rather than cap it with a time or profit target, and the stop is the only override.

## What I measured in the design window (code and actual numbers)

Script: `.scratch/c04-riskmanaged/research_exposure.py`. Every read used
`duck.connect(s.analytics_path, read_only=True)`, bounded by `end=dt.date(2026,2,13)`. I deliberately
queried only `gfc`, `covid`, `bear-2022`, and `bull-2024` — never `recent`, since that window extends
past the 2026-02-13 cutoff and querying it would be looking ahead of what BRIEF.md §4 permits.

**Full-history exposure to each symbol's own sma(200) filter** (fraction of sessions held):

```
SPY: first_bar=1993-01-29  exposure(sma200)=0.747
EFA: first_bar=2001-08-27  exposure(sma200)=0.660
IEF: first_bar=2002-07-30  exposure(sma200)=0.526   (measured, then dropped from universe)
TLT: first_bar=2002-07-30  exposure(sma200)=0.498
GLD: first_bar=2004-11-18  exposure(sma200)=0.688
```

**Per-window exposure** (fraction of sessions each leg was held, within that window):

```
             SPY     EFA     TLT     GLD
gfc         0.087   0.143   0.843   0.716
covid       0.333   0.075   1.000   0.968
bear-2022   0.179   0.010   0.000   0.495
bull-2024   0.832   0.756   0.172   1.000
```

**Blended portfolio exposure** (`0.25 × sum of the four legs' per-window exposure above`):

```
gfc:        ~0.45   (equities correctly excluded; bonds+gold in an uptrend supply the exposure)
covid:      ~0.59   (bonds+gold near-fully held through the crash and snapback)
bear-2022:  ~0.17   (the honest low-exposure case: 2022 was a simultaneous equity+bond bear —
                     the filter correctly went nearly flat because nearly nothing was trending up)
bull-2024:  ~0.69   (equities and gold carry a high-exposure bull year; bonds chopped, so TLT lagged)
```

This is the number the brief asked me to be honest about. The sleeve is **not** a 90%-cash rule
wearing a defensive costume: in `gfc` and `covid` its ~45–59% average exposure is concentrated in
legs that were themselves trending up (Treasuries and gold), so the strategy should show real
positive or flat performance in those windows rather than a flat line produced by inactivity. The
one window where exposure genuinely collapses toward zero (`bear-2022`, ~17%) is the one window
where that is the correct answer — bonds and equities fell together, so there was very little to be
exposed to, and I say so here rather than let a flat 2022 curve be read as free skill.

**Correlation matrix** (daily returns, full overlapping history):

```
      SPY   EFA   IEF   TLT   GLD
SPY  1.00  0.86 -0.30 -0.31  0.05
EFA  0.86  1.00 -0.26 -0.28  0.17
IEF -0.30 -0.26  1.00  0.91  0.20
TLT -0.31 -0.28  0.91  1.00  0.16
GLD  0.05  0.17  0.20  0.16  1.00
```

This drove the universe decision above: `SPY`/`EFA` and `IEF`/`TLT` are each near-redundant pairs;
`GLD` is the one genuine outlier, and `SPY`/`TLT` and `EFA`/`TLT` carry the mild negative correlation
that is the textbook equity/duration hedge (which is exactly what broke down in 2022, hence that
window's low blended exposure).

## Sensitivity check

I compared full-history exposure using `sma(150)`, `sma(200)`, and `sma(250)` in place of the entry
period, without changing anything else, to confirm `200` is not a fragile choice:

```
SPY: exposure(sma150)=0.735  exposure(sma200)=0.747  exposure(sma250)=0.759
EFA: exposure(sma150)=0.645  exposure(sma200)=0.660  exposure(sma250)=0.660
IEF: exposure(sma150)=0.533  exposure(sma200)=0.526  exposure(sma250)=0.515
TLT: exposure(sma150)=0.514  exposure(sma200)=0.498  exposure(sma250)=0.479
GLD: exposure(sma150)=0.676  exposure(sma200)=0.688  exposure(sma250)=0.691
```

Exposure moves by at most ~2 points per symbol across a 150→250 range around 200. The rule is not
sitting on a cliff at exactly 200; I did not search this range for a better number and picked the
conventional one (`200`) per BRIEF.md §2's guidance to prefer conventional periods.

## What I tried and abandoned

- **Five-symbol universe including `IEF`.** Dropped after the correlation check showed `IEF`/`TLT`
  at 0.91 — it was consuming a slot for redundancy, not diversification, and would have forced
  `position_pct` down to 0.20 with no offsetting benefit.
- **A `crosses_above sma(200)` / `crosses_below sma(200)` entry/exit pair instead of the plain
  inequality.** I considered this to get a discrete signal rather than a persistent state. I
  abandoned it because after a stop-out inside an uptrend (price still above sma(200) but the
  position was stopped), a cross-based entry would leave the sleeve sidelined until the next fresh
  cross, potentially for a long time, whereas the plain inequality re-enters as soon as the position
  is flat and the trend condition still holds — which matches the mechanism (stay exposed to
  in-control-buyer conditions) rather than adding path-dependence.
- **A tighter stop (e.g. 0.08).** BRIEF.md §9 notes a prior card's worst trade lost 19.9% against a
  12% stop because stops are checked against the previous close, not the intraday low. Going tighter
  than 0.12 would mean routine daily volatility in a legitimately-trending asset triggers stop-outs
  that the mechanism doesn't intend to catch; I kept 0.12 as a shock backstop, not a volatility filter.

## Assumptions I am relying on

- `position_pct` (0.25) does not exceed the persona's normal 25% single-name cap, so I am not relying
  on the round's 100% relaxation described in BRIEF.md §9.
- None of the four symbols are leveraged/inverse instruments, so the decay-instrument caveat in
  `WINDOWS.md` does not apply here.

## Pre-registered failure regime

Stated in the thesis field, repeated here per §12: **a sideways, choppy, low-trend market** — the
filter whipsaws (repeated stop-outs and re-entries) against a benchmark that is simply not moving,
producing a string of small losses with no offsetting trend capture. Secondarily, **a simultaneous
multi-asset-class bear** (equities and bonds falling together, as in 2022) removes most of the book
to cash-like exposure at once; the ~17% blended exposure measured for `bear-2022` above is the
concrete number for that case.

## Single weakest assumption

That the four legs' historical decorrelation (particularly the negative `SPY`/`TLT` correlation that
supplied most of the "rotate, don't go to cash" story in `gfc` and `covid`) holds going forward —
`bear-2022`'s measured numbers already show it breaking down in exactly the way that would hurt most,
and the design has no mechanism to detect or adapt to a regime shift in that correlation, only to
each asset's own price trend after the fact.

## Guard output (verbatim)

Command run exactly as specified in BRIEF.md §11:

```
card OK: c04-riskmanaged | planned RRR: None | slots: 4
guard: all symbols checked
```

No `GUARD ...` lines were printed for any symbol/label combination, i.e. the guard passed for
`entry` and `exit` on all four universe symbols (`SPY`, `EFA`, `TLT`, `GLD`).

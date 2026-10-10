# c05-trend — Cross-Asset 200dma Trend

## Mechanism

The rule is: go long a symbol when its close crosses above its own 200-day simple moving average,
exit when it crosses back below. This is applied identically and independently to three symbols —
`SPY`, `TLT`, `GLD` — with no cross-sectional comparison between them (the engine cannot express one
anyway).

Why this should work, stated as a mechanism rather than a restatement of the rule: the 200-day
moving average is one of the few technical levels that is genuinely watched by a large, identifiable
population — managed-futures CTAs, trend-following mutual funds, and a large population of
technically-oriented discretionary traders all use variants of it as a regime filter. A break of it
is therefore not a random walk event; it triggers correlated, mechanical follow-on flow from that
population, which is what sustains a move for longer than a single day's information would justify.
The counterparty supplying the other side of the trade is a population that is structurally slow or
reluctant to move: index and retirement-account flows that buy and sell on a schedule unrelated to
price level, and holders exhibiting the disposition effect — reluctant to realize a loss — who stay
in a position past the point a trend-follower has already exited. That reluctance is what cushions
the trend-follower's fills on the way down and lets a nascent uptrend build before the slow money
chases it on the way up.

The cross-asset element is the second half of the thesis, and it is the thing this round asks me
specifically to test: applying the *same* rule to three assets whose price drivers are structurally
different (US equity risk premium, long-duration interest-rate risk, and a non-yielding hard asset
with its own supply/demand book) means the three trend signals are not forced to turn on and off
together. This is not a hedge — there is no offsetting logic, and the engine has no mechanism for
one — it is three independently-triggered bets whose bad years are, empirically, not the same years.

## Universe, and why

**Universe: `SPY`, `TLT`, `GLD`.** All three have first bars ≤ 2004 (`SPY` 1993-01-29, `TLT`
2002-07-30, `GLD` 2004-11-18), so all three clear the 200-bar SMA warmup plus the guard's 40-bar
buffer well before the `gfc` window opens (2007-10-09) — **this universe is eligible for all five
windows: `gfc`, `covid`, `bear-2022`, `bull-2024`, `recent`.**

The brief's own note — that the eleven US sector ETFs measured a mean pairwise correlation of 0.581,
i.e., the same trade in eleven costumes — is a caution about *assuming* breadth of tickers means
diversification. I did not want to repeat that mistake with country ETFs instead of sector ETFs, so
before picking the universe I measured correlations myself, read-only, against a fifteen-symbol
candidate set (all cross-asset categories available in the ≤2004 tier, plus a few from the
2005–2009 tier for context) over two windows through the 2026-02-13 cutoff: the full available
history per symbol, and the trailing five years. Code is in `.scratch/c05-trend/measure.py`.

Full-history correlation to `SPY` (daily returns, since each symbol's first bar, through cutoff):

| symbol | full-history corr to SPY | 5y corr to SPY | annualized vol (5y) |
|---|---|---|---|
| EFA (intl developed) | 0.865 | 0.797 | 16.3% |
| EEM (emerging mkts)  | 0.810 | 0.670 | 18.4% |
| FXI (China)           | 0.669 | 0.396 | 31.9% |
| DVY (dividend equity) | 0.870 | 0.738 | 15.7% |
| XLU (utilities)       | 0.610 | 0.467 | 17.2% |
| XLP (staples)         | 0.677 | 0.526 | 13.1% |
| XLE (energy)          | 0.658 | 0.449 | 26.4% |
| LQD (IG credit)       | 0.159 | 0.361 | 8.7%  |
| AGG (agg bond)        | -0.011 | 0.197 | 6.1% |
| **TLT (long treasury)** | **-0.310** | 0.065 | 16.0% |
| **IEF (interm. treasury)** | **-0.302** | 0.071 | 7.7% |
| SHY (short treasury)  | -0.225 | 0.078 | 2.1%  |
| TIP (inflation-linked) | -0.099 | 0.188 | 6.5%  |
| **GLD (gold)**         | **0.054** | 0.121 | 17.0% |

The finding generalizes exactly the way the brief's caution implies: **every equity-flavored ETF I
measured — international developed, emerging markets, single-country, dividend-tilt, and every
sector I checked — correlates 0.4 to 0.87 with SPY over full history.** International equity is not
a diversifier against a US equity trend book; it is the same trade in a different currency, just as
sector-vs-sector was the same trade in different costumes. The only categories that measured
genuinely low or negative correlation to SPY were **rates** (`TLT`/`IEF` at roughly -0.30 full-history,
`SHY`/`TIP` less negative but still negative) and **gold** (0.054 full-history, 0.121 over 5 years).

I dropped `IEF` in favor of `TLT` alone — the two are 0.91–0.97 correlated with each other across
every window I measured, so holding both is not two bets, it is one rates bet with extra slots
consumed. I dropped `AGG`/`LQD`/`TIP`/`SHY` for the same reason of redundancy with `TLT`, or because
their volatility is low enough (`SHY` 2.1% annualized) that a 200dma cross rule has little signal to
work with. That leaves the minimal set that is not redundant with itself: one equity-beta sleeve,
one rates sleeve, one hard-asset sleeve.

One number worth flagging against a caution I was given but did not independently reproduce: an
earlier analyst in this project reported `GLD` annualized volatility of 24.9%. My own 5-year
measurement through this cutoff gives 17.0%. I did not chase down the discrepancy (different window
length, most likely — gold was calmer in stretches of the last five years than in the period the
earlier figure presumably covered) but I am reporting both numbers rather than silently preferring
mine, because a stop sized against 17% will be tighter, relative to the asset's real tail risk, than
one sized against 24.9%.

## Parameters, against the budget of 10

| source | value | count |
|---|---|---|
| `entry`: `close crosses_above sma(200)` | `200` | 1 |
| `exit`: `close crosses_below sma(200)` | `200` | 1 |
| `stop_loss_pct` | `0.12` | 1 |
| `take_profit_pct` | `null` | 0 |
| `max_hold_days` | `null` | 0 |
| `max_positions` | `3` | 1 |
| `position_pct` | `0.33` | 1 |

**Total: 5 of 10.** (The two `200`s are the same conceptual parameter, the SMA period, appearing
once in `entry` and once in `exit` because the DSL requires the exit to name its own indicator call
— I counted both occurrences rather than deduplicating, to be conservative against the budget.)

`sma(200)` is the standard convention, not a search result — I did not test alternative periods for
performance and pick a winner (see Sensitivity below; the only thing I tested is that it is *not*
fragile, not that some other value is better). `max_positions=3` and `position_pct=0.33` follow
directly from having exactly three symbols in the universe and wanting each to be able to hold a
full, equal-weighted slot independently: `0.33 * 3 = 0.99 <= 1.001`, satisfying the sizing validator
with headroom rather than running up against it. `stop_loss_pct=0.12` is a backstop against the
documented fact that stops are checked against the previous close, not the intraday low, so a stop
will be violated by more than its stated size in a fast move — I picked 12% because it is the exact
figure named in the brief as the stop size behind a trade that lost 19.9%, so I am choosing it with
that failure mode already priced in as a known possibility, not a surprise. No `take_profit_pct` and
no `max_hold_days`: a trend-following book that caps its winners or forces an exit on a timer is
fighting its own thesis — the position should be held for exactly as long as the trend persists,
which is what the exit rule already measures.

## What I measured, and the code I ran

Both scripts below were run read-only (`duck.connect(path, read_only=True)`) and bounded to
`end=dt.date(2026,2,13)`.

- `.scratch/c05-trend/measure.py` — correlation and volatility table above, over full history and
  trailing 5 years, for the 15-symbol candidate set.
- `.scratch/c05-trend/sensitivity.py` — crossing-frequency sensitivity, below.

I did **not** run a backtest and did not compute a return figure for this design. The tournament's
own framing (§9 of the brief, and the runner holding an exclusive write lock during a competition
round) makes clear that trading this card is done by machinery I do not control; a return number I
computed myself in the design window would be exactly the in-sample fitting signal the brief asks me
not to chase, and the ρ = 0.162 finding is the argument for why it wouldn't have told me anything
about the blind result anyway.

## Sensitivity check

The one thing I did check is whether `sma(200)` is a fragile choice — whether a small change in the
period collapses the signal, the way a fitted parameter would. I counted upward crossings of `close`
over `sma(period)` for `period ∈ {190, 200, 210}`, across each symbol's full history through cutoff:

```
SPY sma(190): 113 upward crossings over 8318 bars (1993-01-29 - 2026-02-13)
SPY sma(200): 111 upward crossings over 8318 bars (1993-01-29 - 2026-02-13)
SPY sma(210): 104 upward crossings over 8318 bars (1993-01-29 - 2026-02-13)

TLT sma(190): 119 upward crossings over 5925 bars (2002-07-30 - 2026-02-13)
TLT sma(200): 118 upward crossings over 5925 bars (2002-07-30 - 2026-02-13)
TLT sma(210): 115 upward crossings over 5925 bars (2002-07-30 - 2026-02-13)

GLD sma(190): 81 upward crossings over 5343 bars (2004-11-18 - 2026-02-13)
GLD sma(200): 80 upward crossings over 5343 bars (2004-11-18 - 2026-02-13)
GLD sma(210): 73 upward crossings over 5343 bars (2004-11-18 - 2026-02-13)
```

Crossing counts move smoothly and by single digits across a ±10-day change in the averaging period,
for all three symbols — no cliff, no period where the signal count jumps or collapses. This is
frequency, not performance — I deliberately did not compute which period would have produced a
better return, because that is the grid search the brief prohibits. The check only shows that 200
is not a knife-edge choice among its neighbors; it is not evidence that 200 is optimal, and I am not
claiming it is.

## What I tried and abandoned

- **A faster confirmation layer** (`close > sma(50) and sma(50) > sma(200)`) to reduce whipsaw. I
  dropped it because it adds a second numeric literal pair for a benefit I cannot demonstrate without
  running the exact backtest-and-compare the brief prohibits, and because the single 200dma cross is
  the more defensible, more widely-recognized convention of the two.
- **A fourth sleeve in commodities** (`DBC`, `USO`, `SLV`, `CPER`, `GDX` etc.) to broaden the hard-asset
  exposure beyond gold alone. All of these have first bars in 2005–2009, which would have pulled the
  whole universe out of `gfc` eligibility (a fixed universe is fixed for every symbol) for a benefit —
  a second hard-asset trend line — that is unclear given `GDX` in particular carries equity-mine-operator
  risk on top of the metal price. Not worth the eligibility cost.
- **International equity as a fourth sleeve**, before I had measured anything. The correlation table
  above is exactly why I did not do this — `EFA`/`EEM`/`FXI` are 0.4–0.87 correlated with `SPY`, which
  would have repeated the sector-ETF mistake the brief warns about, just with country tickers instead
  of sector tickers.
- **A tighter stop (8%)** matching a more conventional single-name equity stop. I widened it to 12%
  because two of the three symbols in this universe are lower-beta than a single equity name (`TLT`
  16% vol, and `GLD` 17% by my own measurement though an earlier analyst's figure for `GLD` was
  24.9% — see above), and a stop sized for a fast single stock would be too tight for a slower-moving
  rates or gold trend, converting normal chop into stop-outs before the trend rule itself would exit.

## Pre-registered failure regime

**COVID (`covid` window): fast crash-and-snapback.** A 200-day moving average reacts on the order of
weeks, and the window brief itself describes `covid` as "the fastest bear on record, followed by the
fastest recovery" that "punishes slow exits and slow re-entries in the same window." That is
precisely what this rule is: `close crosses_below sma(200)` will confirm the crash only after most of
the initial drop has already happened, and `close crosses_above sma(200)` will confirm the recovery
only after much of the snapback has already happened. I expect this window to be this card's worst
result, and I expect it to be worst specifically because the rule is slow, not because the underlying
assets are individually wrong.

`bear-2022` — the grinding, rate-driven bear the window notes describe as "the regime most trend
rules claim to handle" — is the window I expect this design to defend best, on the same logic run in
reverse: a slow decline gives a slow signal time to confirm and get out before most of the damage,
and `TLT`'s own rate-driven decline in that period should trigger a `TLT` exit on the same rule
without needing any special-casing.

## Weakest assumption

The single fixed `stop_loss_pct=0.12` and single fixed `position_pct=0.33` are applied identically to
`SPY`, `TLT`, and `GLD` despite each having a different volatility character (roughly 16–17%
annualized on my own five-year measurement, though `GLD`'s volatility over a different, unmeasured
window has been reported elsewhere as considerably higher at 24.9%) — the brief itself names this as
a known failure mode for a universe with mismatched volatility, and even though my three assets are
closer to each other in vol than the 15%-vs-60% example given, they are not identical, and I have no
mechanism available (per-symbol volatility-scaled sizing is explicitly not expressible in this DSL)
to size the stop or the position to the asset actually held.

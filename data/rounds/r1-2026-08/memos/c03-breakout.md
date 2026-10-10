# c03-breakout -- design memo

## Mechanism

The entry is: **`close crosses_above swing_high(20) and close > sma(200)`**.

`swing_high(20)` is a confirmed local high -- the price of the most recent bar that was the maximum
of the 41 bars centred on it, published 20 bars after it forms (see `backend/app/indicators/swing.py`).
That is a real, causal definition of "the top of the range this symbol has been consolidating under,"
not a naive rolling maximum. When close crosses above it, two groups are forced to act, not just one:

- **Short sellers** who sold into the old resistance are now underwater on a level that just failed;
  covering is not optional past some pain threshold, and their buying is price-triggered, not
  opinion-driven.
- **Systematic trend and breakout systems** (N-day-high rules are a standard, well-documented
  component of CTA and managed-futures flow) generate a fresh buy signal on the identical event.

Both flows are mechanical rather than discretionary, which is the reason a genuine range breakout
tends to keep moving for a while instead of immediately reverting -- the buying pressure is a rule
firing on a threshold, not a considered opinion that can flip on the next tick.

`close > sma(200)` restricts entries to names already in a primary uptrend. A local-high break inside
a primary downtrend is disproportionately a bear-market rally failing at the level it should fail at,
not a fresh trend starting; the filter is there to remove exactly that case.

The exit, **`close crosses_below swing_low(10)`**, is the same idea run in reverse and at roughly
half the lookback: once price breaks a confirmed recent higher-low structure, the up-move that the
entry paid for is over. Half the lookback of the entry pivot is deliberate -- structure typically
breaks down faster than it builds up (declines are sharper than advances), so a slower, entry-grade
lookback would give back more open profit before confirming the trend has failed.

## On the swing-high confirmation lag, specifically

The brief's note is right that `swing_high(lookback)` publishes a pivot `lookback` bars after it forms,
so the reference is always at least that stale. I measured what this costs and what it buys, over the
full pre-cutoff history (1998-12-22 through 2026-02-13) of the nine sector SPDRs below:

```
symbol  confirmed_crosses  naive_20d_high_crosses
XLB     169                389
XLE     143                369
XLF     139                368
XLI     147                409
XLK     136                474
XLP     150                400
XLU     130                346
XLV     127                375
XLY     130                422
totals  1271               3552
```
(code: `.scratch/c03-breakout/explore.py`; naive reference is `high.rolling(20).max().shift(1)`,
i.e. the prior 20 days' highest high excluding today, so it is a fair same-timing comparison, not a
lookahead one.)

The confirmed swing high fires **2.8x less often** than a naive rolling 20-day-high cross. That is
the confirmation lag doing exactly what it is supposed to do: a naive N-day high is beaten by almost
every fresh push higher inside an uptrend, which is not a breakout, it's continuation noise. The
confirmed pivot requires the old high to have actually held as a local maximum for 20 real bars before
counting it as resistance, which suppresses most of that noise at the cost of entering later on the
genuine breakouts. **I judge this helps more than it hurts** for a swing-hold breakout system like
this one (multi-week to multi-month intended holding period, not a scalp) -- fewer, more selective
entries is the right trade for a strategy that is going to be evaluated on `adjusted_excess` and
penalised for excess exposure that does not add over benchmark, not the right trade for someone trying
to catch the first tick of every move. A day-trading breakout system would want the naive version and
would be right to; this one does not.

## Universe, and why

**`XLK XLF XLE XLI XLY XLP XLV XLU XLB`** -- the nine SPDR sector ETFs.

Reasoning:
- All nine have a first bar in 1998-12-22, comfortably inside the "reaches every window including the
  GFC" tier of `WINDOWS.md` (first bar <= 2004). That makes the card **eligible for all five windows**:
  `gfc`, `covid`, `bear-2022`, `bull-2024`, `recent`.
- They are the same asset class (US equity sector funds) with broadly comparable volatility, so one
  fixed `stop_loss_pct` and one fixed `position_pct` fit all nine reasonably -- the brief's warning
  about mixing a 15%-vol ETF with a 60%-vol single name does not apply here.
- Nine largely non-overlapping sectors give the breakout rule multiple, partially independent shots
  at finding a genuine sector-level range break in any given regime, without the idiosyncratic,
  single-name risk (earnings gaps, etc.) of picking nine individual stocks.
- None are leveraged/inverse instruments, so there is no daily-rebalancing decay to worry about over
  a multi-month hold.

I did not pick individual high-beta breakout names (e.g. semiconductor or momentum single stocks)
precisely because that would have concentrated the universe in the kind of names that only reach
`bull-2024`/`recent`, or that would need a much wider stop than a defensive sector -- exactly the
trap `WINDOWS.md` describes as tying universe choice to generalisation.

## Parameters -- 6 against a budget of 10

| # | field | value | why |
|---|---|---|---|
| 1 | `swing_high` lookback | 20 | ~1 trading month either side; a round, conventional consolidation length. Signal count moves smoothly with it (1435 / 1271 / 1188 crosses at lookback 15 / 20 / 25 across the universe, full history) -- not a knife-edge choice. |
| 2 | `sma` period | 200 | The single most conventional long-term trend filter in technical analysis; thousands of participants actually watch the 200-day. |
| 3 | `swing_low` lookback | 10 | Half the entry lookback, deliberately -- structure breaks down faster than it builds (declines are sharper than advances), so a faster exit-side pivot avoids giving back an outsized share of open profit waiting for a 20-bar-grade confirmation on the way down. |
| 4 | `stop_loss_pct` | 0.10 | Wider than the reflexive 8%, because the brief documents a stop evaluated on the prior close landing worse than intended (one prior card lost 19.9% against a 12% stop) -- 10% is sized to survive a single adverse gap without being so wide it stops out only after the thesis is obviously already dead. |
| 5 | `max_positions` | 4 | Concentrated enough that a handful of genuine sector breakouts matter, diversified enough that one bad breakout is a quarter of the book, not the whole book. |
| 6 | `position_pct` | 0.20 | `0.20 x 4 = 0.80` -- comfortably clears the `<= 1.001` validator with room to spare, and stays under 0.25 per position so the card does **not** rely on this round's relaxed 100% single-name cap; it would pass under the persona's normal 25% cap too. |

`take_profit_pct` and `max_hold_days` are both left `null`. This is a choice, not an omission: the
whole thesis of a breakout rule is that mechanical, non-discretionary buying can carry a move further
than a discretionary target would guess, so capping it with an arbitrary take-profit or time stop
would fight the mechanism the strategy is built on. The structural exit (`swing_low(10)` break) plus
the hard `stop_loss_pct` are the two ways a position closes; that satisfies the "something must close
the position" validator on their own, and adding a third closing condition purely to have one would
have been an extra unjustified parameter against the budget.

## What I measured in the design window, and the code

All of the following used data only through 2026-02-13, via `duck.connect(..., read_only=True)`,
against the full pre-cutoff history back to each symbol's first bar (1998-12-22 for all nine).
Scripts live in `.scratch/c03-breakout/explore.py` plus two inline snippets described below (I did
not save every throwaway snippet, but reproduced the numbers below directly from the commands run).

**1. Signal frequency and forward return, `explore.py`:**

```
symbol  first_bar  n_bars  confirmed_crosses  naive_crosses  entries_after_trend_filter  mean_fwd20_after_entry  n_entry_samples
XLB     1998-12-22 6828    169                389            166                         0.0045                  166
XLE     1998-12-22 6828    143                369            121                         0.0052                  121
XLF     1998-12-22 6828    139                368            136                         0.0015                  136
XLI     1998-12-22 6828    147                409            145                         0.0083                  145
XLK     1998-12-22 6828    136                474            124                          0.0146                 123
XLP     1998-12-22 6828    150                400            145                         -0.0002                 145
XLU     1998-12-22 6828    130                346            122                         -0.0061                 122
XLV     1998-12-22 6828    127                375            119                          0.0041                 119
XLY     1998-12-22 6828    130                422            127                          0.0074                 125
totals: confirmed_crosses=1271 naive_crosses=3552 entries_after_trend_filter=1205
```

Takeaways: ~130-170 confirmed breakout events per symbol over ~27 years (roughly 5-6/year/symbol,
plausible for a monthly-consolidation-scale breakout definition); the `sma(200)` filter removes only
~5% of confirmed crosses (1271 -> 1205), so it is a light, occasional filter, not doing most of the
work -- most confirmed breakouts already occur in established uptrends, which is the expected
overlap between "broke a confirmed high" and "above the 200-day," not a coincidence. Mean forward
20-session return after entry is small and mostly positive (0.0015 to 0.0146) except for the two
defensive sectors, XLU (-0.0061) and XLP (-0.0002) -- consistent with defensive sectors trending less
and being poorer breakout candidates generically, which is a real observation, not something I used
to change the universe (I kept them in for the diversification and eligibility reasons above).

**2. Entry-signal count by regime window** (diagnostic only -- I did not use this to tune anything,
only to ground the pre-registered failure regime below in an actual count rather than a guess):

```
gfc        entry signals: 35 / trading-days-in-window x9 symbols: 3204
covid      entry signals: 12 / trading-days-in-window x9 symbols: 837
bear-2022  entry signals: 19 / trading-days-in-window x9 symbols: 1764
bull-2024  entry signals: 42 / trading-days-in-window x9 symbols: 2250
```

The rule is not silent during bear windows -- it fires 35 times across the ~17-month GFC window and
19 times across bear-2022. That is expected: nine sectors do not top or bottom in lockstep (energy
kept making highs into mid-2008 while financials were already collapsing), so some sector-level
breakouts occur even while the broad market is in a primary bear. It is also the reason I expect those
windows to be the weak ones -- see failure regime below.

**3. Sensitivity check on the `swing_high` lookback (15 / 20 / 25), signal-count only, not a
performance grid search:**

```
lookback 15  total_crosses 1435  after_trend_filter 1304
lookback 20  total_crosses 1271  after_trend_filter 1205
lookback 25  total_crosses 1188  after_trend_filter 1143
```

Signal count moves smoothly and monotonically (~13% across a +/-5 change either side of 20), with no
cliff or knife-edge. I did not run this at more settings and did not use it to pick a "better" number
-- I used it only to confirm 20 is not a fragile, overfit choice before locking it. The rule survives.

## What I tried and abandoned

I considered adding a volume confirmation (e.g. requiring above-average volume on the breakout bar),
which is the textbook second leg of a real breakout thesis ("the move happened on conviction, not
drift"). The DSL's price fields include `volume` bare, so `volume > sma(volume, 20)`-style expressions
are not directly expressible (`sma`/`ema`/etc. take a period against the implicit price series in this
grammar, not an arbitrary named field) and I did not want to spend more of the parameter budget or
grammar-risk chasing a variant I could not first verify against the guard in the time available. I
dropped it rather than submit an unverified expression. The rule as submitted is close-only, which is
a real limitation -- see weakest assumption below.

I also considered `rsi_at_swing_high`/divergence-style entries (buy strength, avoid the case where a
new high forms on weakening momentum), but that is a mean-reversion-adjacent overlay on top of a
breakout thesis and would have muddied what discipline this card actually represents, on top of
costing 2 more parameters for a period and a second lookback. Left it out.

## Pre-registered failure regime

**`bear-2022`, and secondarily `gfc`.** Both are grinding, broad declines rather than a single sharp
event, and the measured entry-signal counts above show the rule is *not* silent in either (35 in gfc,
19 in bear-2022) because sector tops are staggered, not simultaneous. I expect the entries that do fire
in those windows to be sector-level relief rallies or late-cycle sector strength that ultimately gets
overrun once the broader decline catches up to that sector too -- stopped out at -10% (worse in
practice, since the stop checks the prior close, not the intraday low, per the brief's execution
section) after a brief false start. `covid` is a secondary concern for a different reason: the
`sma(200)` filter is slow by construction, so I expect the strategy to miss the sharpest part of the
V-shaped recovery and enter late, after much of the snapback already happened -- underperforming
buy-and-hold on `exposure`-adjusted terms in that window specifically, even if it is not a losing
window outright.

## Weakest assumption

The single fixed `stop_loss_pct=0.10` and `position_pct=0.20` are applied identically to all nine
sectors, but sector realised volatility is not actually uniform (XLU/XLP historically run meaningfully
calmer than XLK/XLE) -- the stop is somewhat too tight for the volatile sectors' normal noise and
somewhat too loose for the calm ones, and there is no way to express per-symbol volatility scaling in
this DSL, so this is a real, unresolved compromise rather than something I checked and found fine.

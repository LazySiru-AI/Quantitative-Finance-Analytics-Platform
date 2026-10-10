# c12-meanrev-wide — Blue-Chip RSI Reversion, Wide Sector Book

## 1. Mechanism, and who is on the other side

A 14-day RSI reading below 30 while price still sits above its 150-day SMA is a short-horizon,
largely non-fundamental air-pocket in a name whose intermediate trend has not broken. In a single
mature blue-chip stock (as opposed to a diversified ETF) that pocket is typically produced by:
single-name news overreaction (a guidance cut, a downgrade, a headline lawsuit), index and
closet-indexer rebalancing flow that is price-insensitive by construction, and short-horizon
momentum/CTA selling that unwinds once the news cycle passes. None of that flow is pricing the
underlying business.

The counterparty I am trading against is that seller. The counterparty I am trading *to*, on exit,
is whoever buys once sentiment normalizes: these are mature, high-float, heavily-covered large
caps with active buyback programs, so there is a latent, valuation-aware bid (corporate buybacks,
value-tilted funds, short-term dip buyers) that reliably shows up once the panic-driven flow
clears — well before the move could be mistaken for the start of a new trend leg, which is why the
exit is pulled at RSI 55 (mean-reverted, not over-extended) rather than waiting for overbought.

## 2. Universe selection — not index-derived

These twelve were **not** chosen by taking the largest current S&P/Nasdaq constituents. I
deliberately excluded the current mega-cap growth/momentum names (AAPL, MSFT, NVDA, AMZN, GOOG,
META, TSLA) because those names spend long stretches trending rather than mean-reverting — a
20-30% pullback in a secular-growth compounder is frequently the *start* of a re-rating, not a
panic that clears in three weeks, which works against this thesis rather than for it.

Selection criteria, applied by hand:
- **History depth**: every name has continuous daily data from at least 1990 (most from 1970-1983),
  which is what lets this card be eligible in all 8 scoring windows including `gfc`, rather than
  being gated by `universe_knowable_from`.
- **Liquidity**: all twelve are large-float, heavily-traded names where a 12-15% total book
  allocation does not move the tape, which matters because this strategy trades frequently on
  short-horizon noise.
- **Sector spread, "mature" character**: energy (XOM), financials (JPM), healthcare (JNJ, PFE,
  MRK), staples (PG, KO, WMT), retail (HD), legacy tech/telecom (INTC, CSCO, VZ) — cyclical or
  slow-growth businesses whose stock prices oscillate around a valuation anchor rather than
  compounding on a secular narrative. That range-bound character is the actual selection argument,
  and it is a judgment call, not a screen I ran and reported after the fact.

I did not optimize this list against any backtest; it was fixed before I measured anything below.

## 3. What I measured through 2026-02-13

Using the repo's own rule parser/evaluator (`app.rules.grammar.parse` + `app.rules.evaluate.evaluate`)
against each symbol's full stored history up to the design cutoff — the same code path the
tournament runner uses, so this is not a hand-rolled reimplementation — I found every day the entry
condition (`rsi(14) < 30 and close > sma(150)`) fired (deduping consecutive signal days to one
entry per cluster), simulated an exit at the first day `rsi(14) > 55` within 20 sessions, else a
15-session time exit, and priced entry/exit off the following day's close (a rough proxy for the
broker's next-open fill).

Across the 12 names, full history to 2026-02-13:
- **116 signals**, mean forward return **+2.32%**, median **+3.52%**, **hit rate 73.3%**, mean
  holding **~12 sessions**.
- Per-symbol means all positive except INTC (-1.2%, n=11) and KO (+0.2%, n=11) — no single name
  is carrying the average.
- Breaking the same signals down by the round's actual regime windows: `bear-2022` (n=1,
  +0.5%), `chop-2011` (n=1, +3.3%), `chop-2015` (n=1, +3.5%), `q4-2018` (n=2, +1.6%) were all
  flat-to-positive. `gfc` (n=1, **-5.1%**, the single signal in that window a loser) and `covid`
  (n=4, mean **-9.65%**, hit rate 25%) were the two clear negative clusters. Small per-window
  counts are expected — a 12-name single-stock universe throws far fewer simultaneous signals than
  a broad-ETF book — and I'm reporting them as directional context, not as a claim of statistical
  significance in any one window.

## 4. Parameters and justification

- `rsi(14)` — standard Wilder period; not tuned, it's the default in every implementation and in
  `c01-meanrev`'s sibling grammar, so there is no hidden search here.
- `< 30` — conventional oversold threshold; the round below (25) or above (35) were not tried
  against this data, this is the textbook line.
- `sma(150)` — deliberately shorter than the round's other mean-reversion card's 200-day filter,
  because single stocks re-rate and roll over faster than diversified ETFs; 150 sessions is
  roughly 7 months, long enough to filter out names in an actual downtrend, short enough to react
  before a single-stock decline is fully underway.
- `rsi(14) > 55` exit — a modest recovery threshold, not neutral-50 (too early, gives back the
  edge) and not overbought-70 (waits too long, risks holding into the next leg down); 55 is the
  same "reverted but not extended" logic as the entry's mirror-image.
- `stop_loss_pct = 0.07` — tighter than `c01`'s 8% because single names gap on earnings and
  headlines in ways a sector ETF does not; a hard 7% cap limits single-name event risk.
- `max_hold_days = 15` — shorter than `c01`'s 20-day cap for the same reason: idiosyncratic
  single-stock risk (an earnings print, litigation news) accumulates the longer a position sits
  unresolved, so I cut the leash shorter here.
- `max_positions = 6`, `position_pct = 0.15` (0.90 total commitment) — six concurrent slots across
  twelve names caps single-cluster concentration (see Section 5) while leaving a 10% cash buffer;
  sized to match the round's other mean-reversion entry so the comparison isn't confounded by book
  size.

## 5. What would falsify this

If, over the trading window, this card's losses are **not** concentrated in a systemic, market-wide
drawdown but instead accrue steadily and idiosyncratically across many unrelated single-name
events, the "forced/reflexive seller, buyback-supported recovery" mechanism is wrong — the losses
would instead say these are fundamentally-justified drops in slow-growth names that this trend
filter is too slow to distinguish from real deterioration. Similarly, if hit rate collapses well
below the ~73% measured historically while median return also turns negative in calm, range-bound
windows (`chop-2011`, `chop-2015` analogues), the "buyback bid" story is not doing the work I
think it is.

## 6. Predicted worst window

**`covid`** is my predicted worst window, by a clear margin over `gfc`. In my own measured history,
`covid` produced 4 signals at a mean **-9.65%** with a 25% hit rate — the clearest case in the
data of the pre-registered failure mode: a systemic, correlated, extremely fast decline where the
150-day SMA has not turned down yet when the entry fires, so multiple names in the book signal
"buy the dip" simultaneously right as the market enters its steepest leg down, and several likely
hit the 7% stop within days rather than reverting within the 15-day hold. I expect this window to
show a meaningfully negative excess return, plausibly in the -10% to -20% range relative to SPY's
own covid-window path, concentrated in a handful of sessions rather than spread across the window.
`gfc` is my second-most-likely bad window (my single historical signal there also lost, -5.1%,
though on a sample of one I would not lean on that number alone) — its decline was slower than
COVID's, which should give the 150-day filter more chance to shut new entries off partway through,
so I'd expect it to be less bad than `covid` but still a probable underperformer.

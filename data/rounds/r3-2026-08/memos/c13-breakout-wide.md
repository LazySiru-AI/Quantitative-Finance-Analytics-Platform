# c13-breakout-wide -- Six-Sector Breakout Wide

## 1. Mechanism, and who is on the other side

A confirmed swing-high breakout (`close crosses_above swing_high(20)`) marks the point where a
stock trades above a pivot high that took at least 20 sessions to confirm as a real local top --
not a rolling max, a *pivot*: `swing_high(20)` only prints once 20 bars on each side of a local
high are lower than it, and the value is held forward until the next confirmed pivot. Trading
through that level means the standing supply that rejected price there before has now been
absorbed, and the marginal buyer above it faces less overhead resistance than existed a session
earlier. The `close > sma(200)` filter restricts entries to names whose year-long supply/demand
balance already favors buyers, so the breakout is read as continuation, not a reversal bet on a
stock that has been going nowhere.

The counterparty is not a rational actor re-pricing the breakout itself. It is either (a) a
momentum-agnostic seller -- an index-fund rebalancer, a tax-loss seller, an investor exiting for
reasons that have nothing to do with the chart -- who supplied the shares that just cleared, or
(b) a trend-following short who is stopped out as the level breaks and whose covering adds to the
move. Neither is pricing the pivot; if enough capital chases the same signal that gap should close,
which is the falsifiable claim in section 5.

Because fills happen at the next session's open, not the breakout's own close, this card
structurally gives up the first gap: a clean gap-and-go breakout is bought after the gap, not
before it, which understates real-world breakout returns and is a known cost of this design, not
an oversight.

## 2. Universe -- and whether it is index-derived

**Not index-derived.** I did not open `data/universe/index-constituents.json` to build this list
and did not select "the largest members" of anything. The selection argument is liquidity,
multi-decade history, and sector spread:

- **Liquidity**: every name is among the most heavily traded stocks in its sector, so the
  next-open fill assumption behind this whole card (see section 1) is least distorted by the
  strategy's own footprint.
- **History depth**: every symbol has priced data back to at least 1999 in this store (checked
  through 2026-02-13, see section 3), which is what lets the card be evaluated in all eight
  regime windows, including `gfc`, rather than being unranked below five.
- **Sector spread**: two names each from six sectors with different cyclical drivers --
  semiconductors (NVDA, INTC), e-commerce/big-box retail (AMZN, HD), heavy industrial equipment
  (CAT, DE), energy services (XOM, SLB), money-center banking (JPM, GS), managed
  care/pharma (UNH, LLY) -- chosen so a result is a statement about the breakout mechanism and
  not about one sector's beta riding along in twelve costumes.

**Honest limitation, stated plainly.** This is still a fixed list of twelve names that exist and
trade today. Any static universe built from "liquid, multi-decade survivors" carries an echo of
the same survivorship problem the index-constituents trap describes, even without touching that
file: a stock has to have survived to 2026 to be checkable against 2026-02-13 data at all. I have
not solved that; I have only avoided the specific, worse version of it (mechanically taking
today's index membership and running it over a period, like `gfc`, when half that membership did
not exist in its current form). The gate in this round is triggered by the latter, not by the
former, and the difference is real: none of these twelve was added to any index because it
survived a crisis its era-mates did not -- they are simply large, liquid, long-listed operating
companies, several of which (INTC, XOM, CAT, DE) traded through the 1970s-80s oil shocks and S&Ls
crisis without existential threat, unlike the metaphor case (Lehman, Bear Stearns, WaMu, GM).

## 3. What I measured through 2026-02-13

Pulled daily bars for all twelve tickers from the store, `end=2026-02-13`, and computed (no
window-scanning, no scoring against `gfc`/`covid`/etc. -- these are unconditional full-history and
trailing-5-year statistics):

| Symbol | History starts | Ann. vol | Avg daily H-L range | % days close > sma(200) |
|---|---|---|---|---|
| NVDA | 1999-01-22 | 59.5% | 4.24% | 69% |
| INTC | 1980-03-17 | 40.9% | 2.95% | 57% |
| AMZN | 1997-05-15 | 55.3% | 3.69% | 66% |
| HD   | 1981-09-22 | 36.0% | 2.44% | 70% |
| CAT  | 1970-01-02 | 30.0% | 2.22% | 60% |
| DE   | 1972-06-01 | 31.5% | 2.41% | 63% |
| XOM  | 1970-01-02 | 23.9% | 1.82% | 64% |
| SLB  | 1981-12-31 | 36.1% | 2.77% | 54% |
| JPM  | 1980-03-17 | 35.1% | 2.44% | 62% |
| GS   | 1999-05-04 | 36.1% | 2.56% | 59% |
| UNH  | 1984-10-17 | 39.8% | 2.85% | 69% |
| LLY  | 1972-06-01 | 27.6% | 2.05% | 62% |

Mean pairwise daily-return correlation over the trailing 5 years (through 2026-02-13): **0.284**.
That is the number that supports "sector spread" in section 2 -- a single-sector or
cross-sector-ETF breakout basket (see `c11-breakout`'s own 0.58 figure for nine same-beta sector
ETFs) runs meaningfully hotter than this.

As a frequency sanity check (not a backtest, and not the actual `swing_high` definition -- a
simple rolling-20-day-high proxy, which is *more frequent* than a confirmed pivot since it resets
every time price makes any new high rather than waiting for a confirmed local top): 30-40 such
proxy signals per symbol per year historically. The real `swing_high(20)` signal is rarer than
this by construction, because it requires the prior high to have stood as a genuine pivot for 20
sessions on each side before it can be crossed.

The 54-70% range of "days spent above the 200-day average" is itself a symptom of the section 2
limitation: any stock that reached 2026 with decades of history spent most of that history in an
uptrend, more or less by definition of having survived and grown. This is disclosed, not hidden --
it is the same mechanism as the gfc-window caution in section 1's fill-cost note.

## 4. Every parameter, and why

- **`swing_high(20)` / entry lookback = 20** -- matches the only precedent already in the
  candidate library (`c11-breakout`) rather than being chosen freshly against this card's own
  universe, specifically to avoid tuning a lookback to these twelve names' history.
- **`swing_low(10)` / exit lookback = 10** -- half the entry lookback. A breakout system that
  exits on the same lookback it enters on gives back most of a false breakout before admitting it
  was one; a shorter exit lookback is the standard Donchian-style asymmetry (wide entry
  conviction, tight protective exit) and needs no window-fitting to justify -- it is a structural
  choice, not a fitted number.
- **`sma(200)`** -- the standard long-term trend reference; chosen because it is the one every
  other trend/breakout discussion in this codebase (see `c11-breakout`) already uses, again to
  avoid introducing a new number this round's data could have been used to pick.
- **`stop_loss_pct = 0.12`** -- wider than `c11-breakout`'s 0.10 because this universe's average
  daily range (2.2%-4.2%, table above) is measurably wider than a cross-asset ETF basket; a 10%
  stop on a 4%-range name gets clipped by ordinary noise inside a still-valid trend.
- **`max_hold_days = 150`** -- a backstop only. The exit rule and stop are expected to close
  nearly every trade; this exists so a position cannot be held indefinitely if neither fires
  (a requirement of `StrategyCard` itself, not a performance lever).
- **`max_positions = 6`, `position_pct = 0.15`** -- commits 90% of the book at full six-position
  deployment, leaving a 10% buffer rather than sizing to exactly 100%, since breakout fills happen
  at the next open and a fully committed book has no slack if several signals land the same
  session.

No parameter here was chosen by measuring this card's own historical return; every number is
either copied from the existing library entry (20, 200, 10% stop as a baseline before widening for
volatility) or set by a structural argument (half-lookback exit, sizing buffer) stated above.

## 5. What would falsify the thesis

If the post-breakout excess return is concentrated in the fill session and decays to roughly zero
by the second or third session after entry, that says the "absorbed supply" effect is priced
before this card can act on it (next-open fill), and the mechanism does not survive the one-day
lag the broker imposes. If the win rate is at or below 50% *and* the average winner is not larger
than the average loser (i.e., no edge in either frequency or payoff), the thesis has no
mechanism-level support -- it would mean the counterparty side (section 1) is not systematically
underpriced. And if the six sectors show no dispersion in outcome -- if they all win or all lose
together at a level implied by 0.284 correlation being wrong -- that specifically falsifies the
"sector spread separates mechanism from beta" argument in section 2, not just the strategy.

## 6. Predicted worst window

**`chop-2011`**, not `gfc`. The `sma(200)` filter is a structural absence, not skill: during a
fast, deep drawdown it stops new entries once price falls under its 200-day average and lets
existing positions exit via the `swing_low(10)` rule, so `gfc` should look more like "sat out most
of the real damage" than "took the loss." A sideways, range-bound, headline-driven market like
2011 is the opposite case: price repeatedly prints confirmed 20-day pivots, breaks them, gets
stopped at 12% or exits at `swing_low(10)` for a small loss, and re-enters on the next fakeout,
with the trend filter doing nothing to help because the index itself oscillated around its own
200-day average that year. I expect `chop-2011` to show the lowest hit rate of the eight windows
(whipsaw is a hit-rate problem, not a payoff problem) and a negative excess return versus SPY on
the order of -8% to -12%, driven by trade count roughly double the average across other windows
rather than by any single catastrophic loss.

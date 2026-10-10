# c18-meanrev — Defensive Snapback (Staples, Healthcare & Energy)

## 1. Mechanism, and who is on the other side

Entry: `rsi(2) < 10 and close > sma(200)`. Exit: `close > sma(5)` (backstopped by an 8% stop and a
10-session time stop).

RSI(2) below 10 is an extreme-percentile reading — the stock has closed lower on 2 of the last 2
sessions by enough that almost the entire recent range is downside. Requiring `close > sma(200)`
restricts that reading to names whose long-term trend has not broken: the entry fires on a sharp
1-3 day dislocation inside an intact uptrend, not on the early stage of a real breakdown.

The trade's counterparty is short-horizon, price-insensitive selling: stop-loss triggers, single-name
margin calls, an index or basket rebalance flow, an overreaction to a headline in a name whose
underlying demand (toothpaste, painkillers, gasoline) did not change in 48 hours. None of that flow
carries a revised fundamental view. The exit — back above the 5-day SMA — sells into the snapback
while it is fresh, rather than waiting for a slower reversion the position may not reach before the
name's next real move.

This is deliberately a faster, stricter version of the retired `c01-meanrev` mechanism (which used
`close < bb_lower(20,2)`, a much looser trigger, and exited at the 20-day mid-band). `c01` posted only
+0.4% median adjusted excess and was dominated — the diagnosis in
`backend/app/paper/library/retired/README.md` is that near-zero, dominated cards accumulate for a
reason, and a wider or slower version of the same idea is not automatically better. This card instead
narrows the trigger (RSI(2), not a 20-day band) and shortens the target (5-day SMA and a 10-day time
stop, not a 20-day hold to the mid-band), on the theory that the edge in a genuine short-horizon
dislocation decays fast and a card built to wait it out is paying opportunity cost for nothing.

## 2. Why these names, and whether the selection is index-derived

**Not index-derived.** The universe is JNJ, MRK, PG, KO, PEP, CL, XOM, CVX, MMM, WMT — chosen on
three criteria that have nothing to do with today's S&P/Nasdaq membership list:

- **Length of listed history.** All ten have stored daily bars from 1970-1973 (verified through the
  design cutoff; see §3), which comfortably clears every one of round 4's six windows, including the
  two that most cards will fail — `recovery-2009` (needs `sma(200)` computable well before
  2009-03-10) and `taper-2013`. This was a deliberate answer to the round-3 finding that `G-volatility`
  was retired unrankable at only 3-of-8 windows for exactly this reason.
- **Low index-membership dependence.** Every one of these ten has been a large, liquid, continuously
  traded stock since long before there was a "current constituent list" to select from — they are not
  on this card because they happened to survive into the 2026 index, they are on it because they were
  investable, liquid names in every one of the six target windows and for decades before them.
- **Sector concentration away from the incumbents.** Staples (PG, KO, PEP, CL, WMT), healthcare (JNJ,
  MRK), energy (XOM, CVX), and one industrial (MMM) — chosen specifically to avoid overlap with
  `B-momentum`/`C-trend`'s AI/semiconductor names and to hold low-beta, demand-inelastic businesses
  whose short-term price dislocations are more plausibly technical (forced selling) than fundamental
  (a real repricing), which is the mechanism this card depends on.

I did not use the round's supplied "513 current constituents" list to build this universe, and I am
not claiming a liquidity argument for names that happen to be large index members today — the
argument above is the actual selection logic, stated in full.

## 3. What I measured through 2026-02-13

Using the store's `rsi:2` and `sma:200`/`sma:5` indicators exactly as the DSL would evaluate them,
computed on each name's full history through the design cutoff (not restricted to any trading
window):

| ticker | bars | entry frequency | fwd 5-day return, on signal | fwd 5-day return, unconditional |
|---|---|---|---|---|
| JNJ | 14,151 | 6.01% | +0.42% | +0.23% |
| MRK | 14,151 | 6.13% | +0.66% | +0.22% |
| PG | 14,151 | 5.91% | +0.58% | +0.20% |
| KO | 14,151 | 5.91% | +0.42% | +0.21% |
| PEP | 13,539 | 6.42% | +0.49% | +0.23% |
| CL | 13,310 | 6.06% | +0.34% | +0.20% |
| XOM | 14,151 | 5.09% | +0.56% | +0.20% |
| CVX | 14,151 | 5.72% | +0.44% | +0.21% |
| MMM | 14,151 | 5.45% | +0.31% | +0.17% |
| WMT | 13,479 | 6.32% | +0.70% | +0.41% |

The entry fires on roughly **5-6.4% of trading days per name** — call it about one signal per name
every 16-20 sessions — and every name shows the signalled 5-day forward return running at
**1.5-2.5x the unconditional 5-day forward return**. This is close-to-close, not the actual
next-open fill (see §6), and it is descriptive statistics over the full 1970-2026 history, not a scan
of any trading window — I did not look at 2009, 2013, 2014, 2018, 2021, or 2023 specifically.

**Expected capital exposure.** With 10 names each firing ~6% of days, expect frequent overlap during
genuine broad selloffs (all ten are large-cap and share market beta even if their idiosyncratic
drivers differ), which is when this card should actually be invested — unlike `c12-meanrev-wide`,
retired for averaging 2% exposure across eight windows on a single crisis trade. I expect this card
to run meaningfully higher than that: with `max_positions=6` and signals clustering in drawdowns, I
expect **mean capital exposure in the 0.25-0.40 range** across the six windows, higher in the highest
-volatility ones (`volmageddon-2018`, `oil-2014` for the energy names, `banks-2023`) and lower in a
calm grind like `inflation-2021` where RSI(2) rarely reaches single digits.

## 4. Every parameter, and why

- **`rsi(2) < 10`** — period 2 is the standard short-horizon extreme-reading setup (Connors-style);
  threshold 10 is a conventional "deeply oversold" cut, not tuned against any target window. One
  parameter, one threshold.
- **`close > sma(200)`** — the trend filter, identical to `c01-meanrev`'s, kept because it is the
  cheapest available proxy for "nothing structural has changed" and because reusing a value already
  used elsewhere in the library is one fewer number invented for this card.
- **`close > sma(5)`** exit — the fastest conventional moving-average exit; chosen to be materially
  faster than `c01`'s `bb_mid(20,2)` exit, consistent with the shorter, stricter entry.
- **`stop_loss_pct = 0.08`** — same 8% used by `c01-meanrev`; a short-horizon reversion trade that is
  down 8% has not reverted and the entry thesis (a 1-3 day dislocation) has been falsified for that
  trade.
- **`max_hold_days = 10`** — roughly 2x the typical signal-to-signal spacing; long enough for a normal
  snapback, short enough to stop a stalled position from sitting through a longer decline waiting on
  an exit condition that may not arrive.
- **`max_positions = 6`, `position_pct = 0.15`** (90% max committed) — six of ten names is enough
  slots to actually capture a clustered, market-wide dislocation (the failure mode `c12` fell into
  was too few slots ever filling), while still leaving two names' worth of headroom so the book is not
  permanently at its cap the moment a third or fourth signal arrives mid-drawdown.

## 5. What would falsify the thesis

A sustained decline in which `close > sma(200)` stays true late into the decline (the 200-day average
is slow by construction) while the actual trend has already broken — the entry keeps firing on
"dips" that are really the first third of a much larger leg down, the 5-day-SMA exit and 10-day time
stop do not arrive, and the position exits on the 8% stop repeatedly until the 200-day average finally
rolls over and shuts the entry off. If median adjusted excess is negative and the worst window is
materially worse than the stop-loss-implied floor (roughly `-0.08 x mean_exposure`), the mechanism has
failed, not just underperformed.

## 6. Predictions (scored)

- **Worst window: `volmageddon-2018`.** It is short (45 sessions), violent, and fast — vol-shock
  moves that overwhelm a 200-day trend filter built for slower declines happen in days, not weeks,
  which is exactly the failure mode in §5. I expect a modest negative adjusted excess there, on the
  order of -3% to -8%, not a crisis-scale loss, because the window is short enough that the 200-day
  filter should still mostly hold and the 8% stop caps individual trade damage.
- **Correlation to `B-momentum`: low, roughly 0.10-0.25.** Raw daily-return correlation between this
  basket and NVDA/AMD since 2015 measures 0.25-0.28 (0.49 against MSFT, the more market-like name in
  that book) — but `B-momentum` only holds when its trend filter is already long and rising, while this
  card only enters on short-term weakness; strategy-level (not raw price) correlation should run below
  the raw name-level correlation because the two books tend to be positioned oppositely at the moments
  each is most active. I do not expect it near zero or negative, because both are still long-only
  equity books riding the same broad market beta most of the time.
- **Fill-delay cost.** Entry fills at the next session's open, one day after the RSI(2) close that
  triggered it. Measured close-to-close, the signalled 5-day forward return is roughly 2x the
  unconditional 5-day return (§3) — call the raw signal edge on the order of 20-40bp over 5 days. A
  single overnight gap captures a meaningful share of a short reversion's total move (this is a 1-3 day
  dislocation, not a multi-week one), so I expect the next-open fill to cost **roughly a third to half
  of the raw signalled edge** before slippage — the primary reason this card is designed around a
  large, frequently-firing universe and a fast exit rather than a small number of high-conviction
  trades, and why I am not predicting a large median.

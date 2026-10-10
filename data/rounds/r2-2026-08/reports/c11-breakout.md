# c11-breakout -- Cross-Asset Breakout -- round 2 report

Agent: `c11-breakout` | Discipline: `breakout` | Eligible: 8/8 main windows (gate cleared with
maximum margin; see `results/eligibility.json`)

## 1. What the card is

Universe `SPY TLT GLD LQD` -- broad US equity, long Treasury duration, gold, and investment-grade
credit, four assets chosen for differing macro drivers rather than four expressions of the same
equity-beta trade. Entry is `close crosses_above swing_high(20) and close > sma(200)`: a confirmed
20-day breakout, gated to an established uptrend so the rule does not buy a dead-cat bounce inside a
larger downtrend. Exit is the symmetric `close crosses_below swing_low(20)`, backstopped by a 10%
stop and a 120-session time cap. `max_positions = 4 = len(universe)`, so every qualifying signal is
always filled and the universe-ordering artifact `WINDOWS.md` documents (up to 12.5 points in a
single window) cannot bind on this card at all -- a genuine structural fix, not a tuning choice.
Parameter count: 7 of 10, three slots of headroom left unused.

The thesis is order-book supply exhaustion at a prior pivot, argued to be asset-class-agnostic. The
card was commissioned specifically to test that claim against round 1's `c03-breakout`, which ran the
identical breakout-plus-trend-filter discipline on nine US sector ETFs later measured at ~0.58 mean
pairwise correlation -- nine costumes on one bet. c11 measures **0.129** mean off-diagonal correlation
(raw) / 0.233 (mean absolute) across its four assets, weakest link `TLT`-`LQD` at 0.572 (both carry
rate duration), every other pair under 0.16 in magnitude.

**Verification.** `total_return` matches `ending_equity / starting_equity - 1` exactly in all eight of
this card's run files, and `capital_exposure` is present and distinct from `exposure` (session
occupancy) throughout, consistent with the round-wide fix. Figures below are computed directly from
`results/<window>/runs/r1-c11-breakout.json`, each window's own full-precision `benchmark_return` --
not the two-decimal figures in the brief -- so some cells differ from the headline numbers by a few
hundredths of a point.

## 2. Eight-window results

| window | trades | return | benchmark | excess | adj. excess | capital exp. | session exp. | max DD | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| q4-2018   | 2 |  -0.91% | -20.05% | +19.13% |  **-0.35%** |  2.81% | 12.31% | -1.22% |   0.00% |
| covid     | 3 |  +2.88% |  -8.71% | +11.59% |  **+5.13%** | 25.85% | 83.87% | -3.08% |   0.00% |
| bear-2022 | 1 |  -1.25% | -25.14% | +23.89% |  **+1.73%** | 11.88% | 48.98% | -3.72% |   0.00% |
| chop-2015 | 6 |  -1.95% |  -0.04% |  -1.91% |  **-1.94%** | 17.98% | 41.15% | -3.95% |   0.00% |
| chop-2011 | 6 |  +6.73% |  -0.05% |  +6.77% |  **+6.75%** | 48.87% | 84.62% | -3.96% |  33.33% |
| bull-2024 | 6 |  +0.08% | +14.00% | -13.92% |  **-4.70%** | 34.14% | 80.40% | -3.77% |  50.00% |
| recent    | 5 | +11.90% | +20.62% |  -8.72% |  **+2.29%** | 46.58% | 93.17% | -4.65% |  75.00% |
| gfc       | 8 |  -4.92% | -56.23% | +51.31% | **+17.37%** | 39.63% | 95.23% | -7.51% |  33.33% |

Sorted, adjusted excess: gfc +17.37, chop-2011 +6.75, covid +5.13, recent +2.29, bear-2022 +1.73,
q4-2018 -0.35, chop-2015 -1.94, bull-2024 -4.70. **Median +2.01%** (average of bear-2022 and recent,
the two middle values). **Worst window: bull-2024, -4.70%.** Hit rate 5/8 (62.5%), positive in gfc,
chop-2011, covid, recent, bear-2022.

## 3. Like-for-like: universe philosophy against `c03-breakout`

`c03-breakout` (round 1, "Sector Confirmed-Range Breakout") runs the same discipline -- a confirmed
swing-high breakout gated by `sma(200)` -- on a nine-symbol US sector-ETF universe. Both cards are
8/8 eligible, so the comparison uses the identical eight windows for both:

| window | c03-breakout adj. excess | c11-breakout adj. excess |
|---|---:|---:|
| q4-2018   |  +4.00% |  -0.35% |
| covid     |  -4.55% |  +5.13% |
| bear-2022 |  +0.07% |  +1.73% |
| chop-2015 |  -6.03% |  -1.94% |
| chop-2011 |  -1.35% |  +6.75% |
| bull-2024 |  -6.25% |  -4.70% |
| recent    |  -8.32% |  +2.29% |
| gfc       |  -1.71% | +17.37% |
| **median** | **-3.13%** | **+2.01%** |
| **worst**   | **-8.32%** | **-4.70%** |

Same discipline, same trend filter, same exit -- one universe change, ~5.1 points of median
adjusted excess and 3.6 points of worst-window improvement. c11 beats c03 in six of the eight
windows. This is the cleanest attributable result in the round: nothing else about the rule changed.

**A caveat on "best of any challenger."** Against the full round-2 field of newly designed cards,
`c07-chop` posts a nominally higher raw median (+2.72%, verified against its own report), driven by
an outsized bear-2022 print (+12.00%) on a mean-reversion book. But c07's worst window is covid at
-15.57% -- more than three times deeper than c11's worst (-4.70%, bull-2024) -- and the two cards
have the same 5/8 hit rate. On the round's other two ranking axes (worst window, spread) c11 is the
stronger, more consistent profile; on raw median alone it is second, not first, among challengers.
The like-for-like margin over c03 above is the claim that survives scrutiny cleanly.

## 4. Does low return correlation mean independent trade timing?

The memo's own weakest-assumption flag: correlation of daily returns is not the same thing as
uncorrelated entry timing, since a shared macro shock could synchronise breakout signals across all
four assets even while their unconditional returns rarely move together. Checked directly against
the 37 trade entries across all eight windows (gaps measured between consecutive entry dates,
regardless of symbol):

- **29 gaps between consecutive entries**, of which **10 (34%) land within 20 calendar days** of the
  previous entry, and the other 19 are spread from 21 days to 199 days apart.
- The clustering is not random noise -- it concentrates at identifiable macro turning points: `TLT`,
  `GLD` and `LQD` all entered within 21 days of each other in July-August 2011 (the US
  debt-ceiling downgrade and the European sovereign-debt flare that also drove `chop-2011`'s result,
  see §6 of `analysis/chop.md`); `SPY` and `GLD` entered on the *same session* (2015-05-18) at the
  start of `chop-2015`; `GLD`, `TLT` and `LQD` clustered within a 15-day window opening
  `bull-2024` (2024-08-26 to 2024-09-20); and `SPY`, `TLT` and `LQD` clustered within 33 days opening
  `gfc` (2007-10-10 to 2007-11-27).
- Against that, a majority of gaps are wide: 65, 75, 150, 98, 165, 112, 199, 84, 109, 111, 181, 139
  days, several exceeding half a window's length.

**Verdict: the caution was directionally right but the effect is partial, not total.** Roughly a
third of this book's entries cluster around shared macro turning points -- exactly the mechanism the
memo worried about -- while the remaining two-thirds spread out across weeks to months, including
within the same windows that show clustering at their open. The realised diversification is
therefore real but weaker than the 0.13 static return-correlation figure alone would suggest: on
several of this card's best windows (chop-2011, gfc, the opening of bull-2024), three of the four
assets did enter together rather than independently, and the book's positive results in those windows
partly reflect a shared macro read arriving at the same time across assets, not four fully
independent bets landing by coincidence.

## 5. Pre-registered worst window vs actual

Memo: *"Named window I expect to lose in: `chop-2011`... I expect `chop-2011` to be worse than
`chop-2015` specifically because it carries higher realised volatility at the same near-zero drift...
I expect it to be the rule actively trading and actively losing to whipsaw."*

**The prediction was wrong, and not narrowly.** `chop-2011` was this card's **second-best window**
(+6.75% adjusted excess, behind only gfc), not its worst -- the actual worst was `bull-2024` at
-4.70%, a window the memo never named as a risk. The card's own account of the mechanism was half
right and half backwards: `chop-2011` did see the book "actively trading" (6 trades, all four
symbols represented, the highest capital exposure of any window at 48.87%), but it was not "actively
losing to whipsaw" -- `TLT` alone returned +25.32% on a 120-day time-capped hold entered 2011-07-11,
riding the flight-to-duration move through the debt-ceiling crisis and European sovereign stress that
the memo's own correlation caveat (§4 above) flagged as a clustering risk, not a return driver. The
higher-volatility chop window rewarded the trend filter rather than whipsawing it, because 2011's
volatility was directional-in-bursts (sharp risk-off legs that a 20-day breakout can catch), not
pure noise around a flat line the way the memo modeled it.

`bull-2024`, the actual worst window, lost for the reason the memo's own trade-off section
anticipated in a different context: three of the four assets are not the trade in a strong,
single-direction bull year, and diluted the book's participation (0.08% raw return against a +14.00%
benchmark) -- this is the cost of diversification the memo said it expected to pay in strong bull
windows, just not flagged as the specific worst one.

## 6. Exit-reason distribution and the stop-loss gap

| window | rule | stop | time | open at end | trades |
|---|---:|---:|---:|---:|---:|
| q4-2018   | 1 | 0 | 0 | 1 | 2 |
| covid     | 0 | 1 | 0 | 2 | 3 |
| bear-2022 | 1 | 0 | 0 | 0 | 1 |
| chop-2015 | 3 | 0 | 0 | 3 | 6 |
| chop-2011 | 2 | 0 | 1 | 3 | 6 |
| bull-2024 | 2 | 1 | 1 | 2 | 6 |
| recent    | 1 | 0 | 3 | 1 | 5 |
| gfc       | 2 | 1 | 3 | 2 | 8 |
| **total** | **12** | **3** | **8** | **14** | **37** |

Rule exits (a confirmed `swing_low` breakdown) are the largest single category at 32%, ahead of stops
(8%) and the time cap (22%); the remaining 38% are positions still open at each window's close --
consistent with a trend-following exit that lets winners run rather than capping them, and with a
4-slot book whose signals are infrequent (0.5-1.2 trades per symbol per window on average).

**Every stopped-out trade against the nominal 10% stop** (evaluated against the previous close,
filled at next open):

| window | symbol | entry | exit | nominal | realised | gap vs nominal |
|---|---|---|---|---:|---:|---:|
| covid     | SPY | 2020-03-03 | 2020-03-10 | -10.00% |  -8.12% | **+1.88pp (better)** |
| bull-2024 | TLT | 2024-09-10 | 2024-11-14 | -10.00% |  -9.42% | **+0.58pp (better)** |
| gfc       | SPY | 2007-10-10 | 2008-01-09 | -10.00% | -10.96% | **-0.96pp (worse)** |

All three of this card's stop-outs realised within about a point of the nominal 10% -- two slightly
better (the market gapped back toward the entry level between the trigger session and the next open),
one slightly worse. **None resembles the round-1 finding cited in the brief** (a 10% stop realising
-22.81%, an 8% stop realising -18.22%): the average gap here is +0.5pp in the card's favour, and the
worst single gap is under 1 point. This is a materially better stop-execution outcome than the
brief's own worked examples, on a small sample (n=3) -- worth flagging as a genuine difference, not
generalising past three trades.

## 7. Verdict and promotion recommendation

The universe-diversification thesis is confirmed on its central, cleanest test: identical discipline,
identical exit and stop, one universe swap from nine correlated sector ETFs to four
macro-differentiated assets, and the median adjusted excess moves from -3.13% to +2.01% while the
worst window improves from -8.32% to -4.70% (§3). `max_positions = len(universe)` genuinely
eliminates the fill-order artifact rather than merely asserting it does.

Two qualifications temper the result. First, the pre-registered failure regime was wrong in
direction as well as magnitude (§5) -- the card's author correctly anticipated a whipsaw cost from
directionless markets in the abstract, but the two live chop windows split (chop-2015 -1.94%,
chop-2011 +6.75%), and the wrong one was named. Second, the diversification the correlation matrix
promises is only partly realised at the trade-timing level (§4): roughly a third of entries cluster
around shared macro turning points, meaning some of the book's best results (chop-2011, the opening
of gfc and bull-2024) reflect a shared macro read landing at the same time across assets rather than
four independent bets. Trade counts are also thin in several windows (1 trade in bear-2022, 2 in
q4-2018), so the per-window figures at the extremes rest on small samples.

**Median adjusted excess is positive (+2.01%) and the card clears the gate at 8/8.** Per
`PROTOCOL.md` §6, that satisfies `challenger -> candidates/` this round. Promotion to `base/`
requires a positive median in **two consecutive rounds on window sets that differ**, and this is
this card's first round -- there is no prior round to pair it with. Recommendation: **promote to
`candidates/`**, not `base/`, pending a second round's confirmation on new windows. The clearest risk
to that confirmation is the timing-clustering finding in §4: if a round-3 window contains another
sharp macro turning point, the book may again move together rather than diversify, which the static
correlation matrix alone would not have warned against.

## 8. Attribution: what moved the number

Source: `analysis/attribution.md` / `results/attribution.json`
(`strategy-program/tools/attribution.py`). Contribution is exact -- `pnl / starting_equity` per
trade, summing to the card's own scored return. Trade counts are small throughout (1-8 per window),
and every trade in every window is listed below, not only the material (>=1%) subset.

### `bear-2022` -- the round's cleanest attribution lesson

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| GLD | 2022-02-15 | 2022-07-06 | 96 | rule | -5.17% | -125 | -1.25% |

**This window's entire +23.89% excess comes from a single trade.** One `GLD` position, entered
2022-02-15 and held 96 sessions to a rule exit, lost money outright (-5.17%, -$125) -- there is no
winner to attribute here, no second trade, nothing else in the book. Capital exposure across the
window was 11.88%. **This is absence, not defence.** The card beat SPY by 23.89 points not because
it hedged the bear market well, but because it was barely in it: one losing position, held most of
the window's 196 sessions, while the other three universe members (`SPY`, `TLT`, `LQD`) never
produced a qualifying breakout at all. Contrast this directly with `gfc` below, where the same card
held 39.63% of the book (more than three times the capital) across 8 trades in multiple assets and
still beat the benchmark by 51.31 points -- that result rests on genuine participation across a
mixed, partly-losing book, not on staying out of the way.

### `gfc` -- the contrast

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| TLT | 2008-08-26 | 2009-02-18 | 120 | time | +12.76% | +312 | +3.12% |
| LQD | 2009-01-12 | _open_ | 38 | **open_at_end** | -11.45% | -281 | -2.81% |
| SPY | 2007-10-10 | 2008-01-09 | 62 | stop | -10.96% | -257 | -2.57% |
| GLD | 2008-07-02 | 2008-08-11 | 27 | rule | -8.57% | -206 | -2.06% |
| GLD | 2008-01-03 | 2008-06-25 | 120 | time | +2.92% | +72 | +0.72% |
| GLD | 2009-02-12 | _open_ | 16 | **open_at_end** | -2.71% | -68 | -0.68% |
| LQD | 2007-11-27 | 2008-03-12 | 72 | rule | -2.54% | -62 | -0.62% |
| TLT | 2007-11-12 | 2008-05-06 | 120 | time | -0.09% | -2 | -0.02% |

Eight trades across all four universe members, 39.63% capital exposure, 95.23% session exposure --
this card was in the market for nearly the entire window. Only 2 of the 8 trades made money (`TLT`,
Aug 2008-Feb 2009, catching the real flight-to-duration move that ran to the 120-session time cap;
`GLD`, a smaller early-2008 gold leg). The other six lost, including a still-open `LQD` position
(-2.81%, a genuine unrealised **loss**, not a gain -- **-3.49% of this window's return is an
unrealised mark, and it is negative**, working against the card, not for it). `SPY` itself was
stopped out near the top of the market (-10.96%, slightly worse than the nominal 10%). Net: -4.92%
raw, but +51.31 points of excess against SPY's -56.23% -- a real, mixed, partly-losing book that
still came out far ahead of the benchmark because the benchmark fell so much further. The 3 largest
winners (there are only 2) supply 100% of gross winning P&L; without them the card would have
returned **-8.76%**.

### `bull-2024`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| GLD | 2024-08-26 | 2025-02-19 | 120 | time | +15.82% | +370 | +3.70% |
| TLT | 2024-09-10 | 2024-11-14 | 47 | stop | -9.42% | -235 | -2.35% |
| TLT | 2025-04-07 | 2025-05-22 | 32 | rule | -9.19% | -220 | -2.20% |
| SPY | 2025-06-30 | _open_ | 36 | **open_at_end** | +3.31% | +82 | +0.82% |
| SPY | 2024-09-20 | 2025-03-07 | 114 | rule | +0.44% | +10 | +0.10% |
| LQD | 2025-08-05 | _open_ | 11 | **open_at_end** | +0.07% | +2 | +0.02% |

One `GLD` trend trade, held the full 120-session time cap, supplies +3.70 of the window's +0.08% --
without it the card would have lost roughly -3.6%. Two `TLT` losses largely offset it (one a genuine
stop-out). This is the card's worst window on adjusted excess (-4.70%): three of the four assets
simply were not the trade in a smooth, single-direction equity rally, diluting participation.

### `chop-2011`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| TLT | 2011-07-11 | 2011-12-29 | 120 | time | +25.32% | +632 | +6.32% |
| SPY | 2012-01-13 | _open_ | 99 | **open_at_end** | +2.54% | +62 | +0.62% |
| LQD | 2011-08-01 | 2011-11-28 | 83 | rule | -1.99% | -49 | -0.49% |
| TLT | 2012-05-18 | _open_ | 12 | **open_at_end** | +1.39% | +34 | +0.34% |
| GLD | 2011-07-14 | 2011-12-15 | 108 | rule | -0.15% | -4 | -0.04% |
| LQD | 2012-01-27 | _open_ | 90 | **open_at_end** | -0.14% | -3 | -0.03% |

One `TLT` position, entered 2011-07-11 and held the full 120-session cap through the US
debt-ceiling downgrade and European sovereign flare, supplies +6.32 of the window's +6.73% return --
nearly the entire result. As §5 already notes, this is the window the memo predicted would be its
worst (expecting whipsaw); instead the trend filter caught a real, sustained flight-to-duration move.

### `chop-2015`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| GLD | 2015-10-15 | 2015-11-09 | 17 | rule | -7.97% | -189 | -1.89% |
| GLD | 2015-05-18 | 2015-06-08 | 14 | rule | -4.68% | -116 | -1.16% |
| TLT | 2016-01-21 | _open_ | 59 | **open_at_end** | +3.84% | +93 | +0.93% |
| LQD | 2016-03-09 | _open_ | 26 | **open_at_end** | +3.73% | +90 | +0.90% |
| SPY | 2015-05-18 | 2015-06-30 | 30 | rule | -2.45% | -57 | -0.57% |
| GLD | 2016-02-11 | _open_ | 44 | **open_at_end** | -0.62% | -15 | -0.15% |

Two closed `GLD` losses dominate the downside; two still-open positions (`TLT`, `LQD`) are this
window's only winners, and **+1.68% of the -1.95% return is an unrealised gain** partly offsetting the
realised loss. Without the winners the card would have returned -3.78%.

### `covid`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| GLD | 2020-03-18 | _open_ | 72 | **open_at_end** | +18.02% | +434 | +4.34% |
| SPY | 2020-03-03 | 2020-03-10 | 5 | stop | -8.12% | -201 | -2.01% |
| LQD | 2020-06-01 | _open_ | 21 | **open_at_end** | +2.30% | +55 | +0.55% |

Only 3 trades. The `GLD` position, entered as the crash bottomed and still open at the window's
close, supplies +4.34 of the +2.88% return -- **+4.89% of the return is unrealised**, more than the
entire result -- while `SPY`'s stop-out (-8.12% against a nominal -10%, i.e. a *favourable* gap) is
the only realised loss.

### `q4-2018`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| SPY | 2018-10-17 | 2018-10-25 | 6 | rule | -4.75% | -107 | -1.07% |
| GLD | 2018-12-21 | _open_ | 1 | **open_at_end** | +0.65% | +15 | +0.15% |

Only 2 trades in the entire window -- one closed `SPY` loss, one `GLD` position opened the day
before the window ends and marked at a small gain. Capital exposure was 2.81%, the lowest of any
window this card ran: like bear-2022, this is a case of minimal participation producing a favourable
excess (+19.13%) mostly because SPY itself fell -20.05%, not because the card found much to do.

### `recent`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| GLD | 2025-09-02 | 2026-02-24 | 120 | time | +46.38% | +1,042 | +10.42% |
| SPY | 2026-04-16 | _open_ | 85 | **open_at_end** | +9.42% | +198 | +1.98% |
| SPY | 2025-12-26 | 2026-03-23 | 58 | rule | -4.81% | -100 | -1.00% |
| LQD | 2025-08-21 | 2026-02-12 | 120 | time | +1.20% | +29 | +0.29% |
| TLT | 2025-09-08 | 2026-03-02 | 120 | time | +0.82% | +20 | +0.20% |

One `GLD` position, held the full 120-session time cap, supplies +10.42 of the +11.90% return --
the single largest individual contribution to any window this card ran, in dollar and percentage
terms alike. Without it the card would have returned roughly +1.5%.

## 9. Concentration and unrealised marks

| window | top-3 share of gross wins | return w/o top-3 winners | unrealised share |
|---|---:|---:|---:|
| bear-2022 | n/a (no winners) | -1.25% | -- |
| bull-2024 | 100% | -4.53% | +0.83% |
| chop-2011 | 100% | -0.56% | +0.93% |
| chop-2015 | 100% | -3.78% | +1.68% |
| covid | 100% | -2.01% | +4.89% |
| gfc | 100% | -8.76% | -3.49% |
| q4-2018 | 100% | -1.07% | +0.15% |
| recent | 98% | -0.79% | +1.98% |

Every window but `bear-2022` (which has no winner at all) shows 98-100% concentration in its top 3
winners, and in six of the eight windows this card ran on 1-6 trades total -- a structurally thin
book where "top 3" routinely means "every winner it had." Four of the eight windows have their
positive-or-least-bad result carried by exactly one long-held trade run to its time cap (`chop-2011`'s
TLT, `bull-2024`'s GLD, `recent`'s GLD, and `gfc`'s TLT alongside a smaller GLD leg) -- consistent
with a genuinely trend-following exit that lets a winner run rather than a broad edge across many
small trades. Unrealised marks cut both ways here, unlike the other four cards in this batch: `gfc`
carries a **negative** unrealised share (-3.49%, an open LQD loss), and covid's positive result is
**more than entirely** an unrealised GLD mark (+4.89% against a total of +2.88%). The two windows the
brief singles out for contrast -- `bear-2022` (single trade, 11.88% capital exposure, a loss, no
winner) and `gfc` (eight trades, 39.63% capital exposure, mixed realised and unrealised, two real
winners) -- sit at opposite ends of this card's actual range of engagement, and the excess figures
alone (+23.89% and +51.31% respectively) do not distinguish between them without this trade-level
view.

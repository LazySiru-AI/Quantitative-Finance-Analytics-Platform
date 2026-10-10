# c03-breakout — competition report

`c03-breakout`, "Sector Confirmed-Range Breakout" (discipline: `breakout`), ranked **18th of 18** —
last — on median `adjusted_excess` (**−4.60%**), negative in four of its five windows, and its one
positive window was not the one its own memo predicted would be the problem.

## 1. What the card was

Entry: `close crosses_above swing_high(20) and close > sma(200)`. Exit: `close crosses_below
swing_low(10)`, plus a `stop_loss_pct = 0.10` backstop. Universe: the nine sector SPDRs (`XLK XLF XLE
XLI XLY XLP XLV XLU XLB`), up to four held at once at `position_pct = 0.20` each. Six parameters
against the budget of ten.

The thesis is a two-sided forced-flow mechanism: a close breaking a *confirmed* swing high (a pivot
that had to hold as the local maximum for 20 bars before counting, not a naive rolling high) forces
short sellers underwater on a level that just failed to cover, and triggers systematic N-day-high
breakout systems — both non-discretionary, price-triggered flows rather than opinions that can
reverse on the next tick. The `sma(200)` filter restricts entries to sectors already in a primary
uptrend, on the reasoning that a local-high break inside a primary downtrend is disproportionately a
failing bear-market rally rather than a fresh trend.

## 2. Results across all five windows

| window | trades | corrected return | benchmark | excess | adj. excess | capital exposure | session exposure | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gfc | 11 | −13.90% | −56.23% | +42.33% | **−1.71%** | 21.68% | 48.60% | −14.29% | 9.09% |
| covid | 7 | −5.76% | −8.71% | +2.96% | **−4.60%** | 13.28% | 23.66% | −8.17% | 0.00% |
| bear-2022 | 9 | −8.35% | −25.14% | +16.79% | **+0.07%** | 33.49% | 73.98% | −10.94% | 11.11% |
| bull-2024 | 11 | +1.82% | +14.00% | −12.18% | **−6.21%** | 57.37% | 98.80% | −10.04% | 71.43% |
| recent | 13 | +3.43% | +20.62% | −17.18% | **−8.25%** | 56.70% | 100.00% | −4.35% | 44.44% |

Same corrected-return and capital-exposure methodology as the D1/D2 workarounds in DEFECTS.md.
**Median −4.60%, IQR 4.50 points, hit rate 20% (1 of 5 windows positive).**

## 3. Pre-registered failure regime versus outcome — and a reversal worth naming plainly

The memo's pre-registration:

> "`bear-2022`, and secondarily `gfc`. ... I expect the entries that do fire in those windows to be
> sector-level relief rallies or late-cycle sector strength that ultimately gets overrun once the
> broader decline catches up to that sector too — stopped out at −10% (worse in practice ...) after a
> brief false start. `covid` is a secondary concern for a different reason: the `sma(200)` filter is
> slow by construction, so I expect the strategy to miss the sharpest part of the V-shaped recovery
> and enter late ... underperforming buy-and-hold on `exposure`-adjusted terms in that window
> specifically, **even if it is not a losing window outright**."

**Wrong, on its own named regime.** `bear-2022` is not the card's worst window — it is the card's
*only* positive one (+0.07% adjusted excess, effectively flat: 9 trades at 33.49% capital exposure
produced a −8.35% return against an implied capital-scaled benchmark loss of about −8.42%, i.e. the
card tracked its own exposure almost exactly rather than either defending or losing to it). `gfc`, the
named secondary case, was mildly negative (−1.71%) — closer to right, but still the second-best window
of the five, not the second-worst. `covid` was flagged as a *concern* but explicitly "not a losing
window outright" — it was: −5.76% corrected return, a 0% win rate across 7 trades, and the field's
second-worst adjusted excess (−4.60%, which is also the card's median).

**The two actual worst windows — `bull-2024` (−6.21%) and `recent` (−8.25%) — are not named in the
pre-registration at all.** These are the two windows that overlap the design period, both strong,
one-directional bull markets. The card was capital-heavy in both (57.37%, 56.70% — its two highest
exposures of any window) and won most of its trades in both (71.43%, 44.44% win rate) — and still lost
badly on an exposure-adjusted basis, because the wins it captured were small relative to what a full
capital-scaled allocation to the benchmark would have returned over the same period. This is the
opposite failure mode from the one the memo prepared for: not "entries fire into a dying rally and get
stopped out," but "entries fire, mostly win, and still leave most of the trend's return on the table
because the exit and re-entry cadence caps how much of a clean one-directional move the rule actually
captures."

**Scorecard: missed on the named primary case, directionally missed on the secondary
(underperformance predicted, outright loss delivered), and silent on the two windows that actually
hurt most.**

## 4. Trade-level detail

**Exit-reason distribution, per window:**

| window | rule | stop | open_at_end |
|---|---:|---:|---:|
| gfc | 9 | 2 | 0 |
| covid | 3 | 1 | 3 |
| bear-2022 | 6 | 3 | 0 |
| bull-2024 | 6 | 1 | 4 |
| recent | 9 | 0 | 4 |

**Best and worst trades:**

| window | best | worst |
|---|---|---|
| gfc | XLE, 2008-04-15→2008-07-08, +2.60% (rule) | XLP, 2008-08-13→2008-10-08, −15.45% (stop) |
| covid | XLK, 2020-06-11→open at end, +2.08% | XLU, 2020-06-09→2020-06-26, −10.66% (stop) |
| bear-2022 | XLE, 2022-01-07→2022-06-24, +18.19% (rule) | XLV, 2022-04-11→2022-05-10, −10.40% (stop) |
| bull-2024 | XLU, 2025-05-07→open at end, +7.15% | XLF, 2025-01-31→2025-04-07, −17.43% (stop) |
| recent | XLK, 2026-04-16→2026-07-29, +13.21% (rule) | XLF, 2025-12-12→2026-02-24, −8.65% (rule) |

**Every stopped-out trade against nominal `stop_loss_pct = 0.10`** (stops are checked against the
*previous close*, per BRIEF.md §9, not the intraday low):

| window | symbol | dates | realized return | nominal | gap vs. nominal |
|---|---|---|---:|---:|---:|
| gfc | XLE | 2007-12-24→2008-01-17 | −9.45% | −10.00% | +0.55 pts (better) |
| gfc | XLP | 2008-08-13→2008-10-08 | −15.45% | −10.00% | **−5.45 pts (worse)** |
| covid | XLU | 2020-06-09→2020-06-26 | −10.66% | −10.00% | −0.66 pts (worse) |
| bear-2022 | XLF | 2022-01-10→2022-03-02 | −9.80% | −10.00% | +0.20 pts (better) |
| bear-2022 | XLV | 2022-04-11→2022-05-10 | −10.40% | −10.00% | −0.40 pts (worse) |
| bear-2022 | XLP | 2022-04-08→2022-05-20 | −9.83% | −10.00% | +0.17 pts (better) |
| bull-2024 | XLF | 2025-01-31→2025-04-07 | **−17.43%** | −10.00% | **−7.43 pts (worse)** |

Seven stops fired across the five windows, none in `recent`. Four of the seven filled worse than
nominal, three filled slightly better. The average gap across all seven is about **−1.86 points**
(worse than nominal), pulled almost entirely by two outliers — the gfc XLP stop (−5.45 pts, during the
Aug–Oct 2008 TARP-period dislocation) and the bull-2024 XLF stop (−7.43 pts, more than 1.7x the
intended risk on a single trade, in an otherwise-calm bull window with no obvious systemic shock
attached). The ordinary stops, away from those two, cluster within about half a point of nominal in
either direction — the mechanism costs little in a calm market and a great deal in the specific weeks
where a name gaps hard against the position.

## 5. Defended versus abstained

The card was never truly idle: capital exposure ranges from 13.28% (covid) to 57.37% (bull-2024) —
a real range of engagement, not a flat low-conviction number. But engagement did not translate to
defense in any but one window. In `gfc` and `covid` it was moderately-to-lightly deployed and lost
outright relative to its own capital-scaled benchmark. In `bear-2022` it was the most heavily deployed
of the three adverse windows (33.49%) and came out flat — tracking, not defending. In `bull-2024` and
`recent` — its two highest-exposure windows — it was fully engaged and still gave back 6–8 points
against a passive allocation of the same capital, the largest per-window shortfalls in the card's
record. There is no window in this report where c03 can be credibly described as having defended
capital it deployed; the closest it comes is the near-exact tracking in `bear-2022`.

**On the nine-sector universe and correlation.** An earlier study measured the mean pairwise
correlation across these nine SPDRs at 0.581 — close to one systematic bet dressed in nine tickers
rather than nine independent shots at a genuine sector-level breakout. This card's results are
consistent with that reading: win rates swing from 0% (covid) to 71.43% (bull-2024) *by window*, not
by symbol within a window, which is the signature of a book moving together with the broader market
regime rather than nine sectors offering partially independent outcomes. If the sectors were behaving
as nine meaningfully separate bets, a bad regime for one sector's breakout thesis would be more likely
to be offset by a good one for another; instead, every window here reads as uniformly good or
uniformly poor across whichever positions happened to be open, which is what a 0.58-correlated
universe predicts and does not indicate the diversification the memo's parameter table implicitly
credited the universe with providing.

## 6. Verdict

Last of 18 on the metric the program considers correct, negative in four of five windows, and — more
tellingly than the rank itself — wrong about which regime would hurt it. The memo's stop-out mechanics
prediction was accurate in isolation (stops did land worse than nominal, most sharply so in exactly
the kind of dislocation the memo anticipated), but the higher-level forecast — bear markets as the
danger, sector staggering as the reason — inverted: the named worst-case window (`bear-2022`) was the
only one that didn't lose, and the two windows that did the most damage (`bull-2024`, `recent`) were
never on the list, because a breakout-with-trend-filter design was not expected to underperform a
strong, clean bull market it was, on paper, built to participate in. That the card's most heavily
capitalized windows are also its worst two is the opposite of what a defensible breakout thesis should
produce, and the near-uniform correlation across its nine "independent" sectors is a plausible
mechanism for why: this reads much closer to one systematic trend bet, taken through nine tickers,
than to nine separable ones.

**Recommendation: retire.** The card is not merely unlucky on a single metric; it inverted its own
pre-registered failure analysis, gave back the most capital in the windows it should have been best
positioned to capture, and its universe construction does not appear to deliver the diversification
its parameter budget implicitly assumed.

**Most valuable variant to test next round:** lengthen the exit lookback to match the entry
(`swing_low(20)` instead of `swing_low(10)`), directly targeting the mechanism most likely responsible
for the bull-2024/recent underperformance — a fast, half-lookback exit that is well-motivated for
capping downside on a failing breakout but which also caps upside early in exactly the clean,
one-directional trends this discipline should be built to ride. This is a single-parameter change,
inside the existing budget, that tests the specific and now-evidenced failure mode rather than the one
the original memo (incorrectly) expected.

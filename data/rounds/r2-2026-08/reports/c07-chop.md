# c07-chop -- Sector Oversold Reversion -- round 2 report

Agent: `c07-chop` | Discipline: `mean-reversion` | Eligible: 8/8 main windows (gate cleared with
maximum margin; see `results/eligibility.json`)

## 1. What the card is

Nine sector SPDRs (`XLF XLK XLU XLP XLV XLI XLE XLB XLY`), entered when `rsi(14) < 30 and close <
bb_lower(20,2)` -- momentum exhaustion and a statistically stretched price agreeing in the same
session -- and exited on `close crosses_above sma(20)`, backstopped by a 7% stop and a 15-session
time cap. The thesis is that sector ETF moves are disproportionately liquidity-provision and
rebalancing flow rather than fundamental repricing, so an oversold reading is more likely reflexive
selling that clears than the start of a new fundamental trend. Parameter count: 9 of 10 (one slot
of headroom left unused), all four entry literals and the exit literal reused directly from
established conventions (Wilder RSI, Bollinger's own 20/2 default) rather than searched.

**Verification.** `total_return` was checked against `ending_equity / starting_equity - 1` across
all 170 run files in `results/*/runs/*.json` (not just this card's eight) and matches exactly in
every file; `capital_exposure` is present and populated on every `AgentResult`. The defects
`WINDOWS.md`/`PROTOCOL.md` describe as fixed between rounds (`DEFECTS.md` D1/D2) are not visible in
this data -- both fields behave as documented. All figures below are computed directly from the
eight `results/<window>/runs/r1-c07-chop.json` files and each window's own `tournament.json`
`benchmark_return` (carried to full precision, not the two-decimal figures quoted in the brief),
which is why some cells differ from the headline table by a few hundredths of a point.

## 2. Eight-window results

| window | trades | return | benchmark | excess | adj. excess | capital exp. | session exp. | max DD | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| q4-2018   | 10 |  -6.52% | -20.05% | +13.53% |  **-1.84%** | 23.33% | 46.15% |  -8.05% | 50.00% |
| covid     | 13 | -16.66% |  -8.71% |  -7.95% | **-15.57%** | 12.53% | 26.88% | -22.51% | 15.38% |
| bear-2022 | 15 |  +7.91% | -25.14% | +33.05% | **+12.00%** | 16.27% | 37.76% |  -2.35% | 84.62% |
| chop-2015 | 17 |  +6.00% |  -0.04% |  +6.03% |  **+6.00%** | 14.26% | 31.92% |  -4.48% | 70.59% |
| chop-2011 | 16 |  +1.93% |  -0.05% |  +1.97% |  **+1.93%** | 12.78% | 28.46% |  -7.63% | 61.54% |
| bull-2024 | 13 |  +6.86% | +14.00% |  -7.14% |  **+5.32%** | 10.97% | 24.40% |  -3.60% | 84.62% |
| recent    |  4 |  +0.55% | +20.62% | -20.06% |  **-0.20%** |  3.66% | 11.65% |  -2.03% | 50.00% |
| gfc       | 40 |  -8.04% | -56.23% | +48.19% |  **+3.52%** | 20.55% | 46.07% | -25.59% | 47.37% |

Median adjusted excess **+2.72%** (average of the two middle values, chop-2011 and gfc; the brief's
own headline table gives +2.69%, same figure to within the benchmark-rounding note above). Worst
window **covid, -15.57%**. Hit rate **5 of 8 (62.5%)**, positive in bear-2022, chop-2015,
chop-2011, bull-2024, gfc.

The two windows this card exists for are both positive and clean: chop-2015 +6.00%, chop-2011
+1.93%, with 70.6% and 61.5% win rates and no exit forced by the 15-day cap dominating either book
(9 of 17 and 7 of 16 exits are the rule exit, not the stop or the clock). That is the mandate
delivered on.

## 3. Pre-registered worst window vs actual

Memo, §6: *"Predicted worst window: covid... this card's entry structurally cannot distinguish
'oversold, about to revert' from 'oversold, about to keep falling,' and a fast, single-direction
crash is exactly the case where that distinction matters most... `q4-2018` -- also a sharp selloff
-- is not expected to be nearly as bad... the difference in this card's expected performance
between the two selloffs is the speed and depth of the drawdown, not its direction."*

**Actual worst window: covid, -15.57% adjusted excess.** The prediction is correct, and by a wide
margin -- the next-worst window (q4-2018, -1.84%) is 13.7 points better. The finer claim also
holds up: q4-2018, a slower and shallower selloff over the same rule, cost the card only -1.84%,
while covid's faster, deeper break cost -15.57%. Both are down-move windows; only speed and depth of
drawdown separate their outcomes, exactly as pre-registered. This is a pre-registration the round-1
matrix (which had no fast-crash-vs-slow-selloff pair to test against) could not have scored on this
axis at all.

## 4. Checking the memo's own claim against the outcome

The memo's design-window measurement (§4) reported that the mean-reversion edge, measured as
*average trade return*, was larger in bear-2022 (+2.83%) and bull-2024 (+3.82%) than in either chop
window (chop-2015 +2.42%, chop-2011 +0.93%) -- and located the card's real failure mode as crash
*speed*, not directionlessness, since covid (fast crash) failed badly while q4-2018 (slow selloff)
did not.

**The scored outcome partially confirms this and partially complicates it.** On *adjusted excess*
(not average trade return -- a different unit, since it folds in exposure and the window's own
benchmark). bear-2022 is unambiguously the strongest of the four at +12.00%, more than double
chop-2015's +6.00% and six times chop-2011's +1.93% -- this half of the claim holds cleanly: the
edge is not chop-only, and a grinding bear rewards it more than either sideways window did. bull-2024
is where the claim gets a qualified reading: at +5.32% it clears chop-2011 (+1.93%) comfortably, as
the memo's trade-level numbers implied it should, but it narrowly trails chop-2015 (+6.00%) in the
scored result even though its design-window average trade (+3.82%) was larger than chop-2015's
(+2.42%). Average trade return and adjusted excess are not the same quantity -- trade count (13 vs
17), capital exposure (10.97% vs 14.26%) and the window's own benchmark all enter the second figure
and none of them enter the first -- so this is not a contradiction of the memo's measurement, but it
is a place where the ranking it predicted between two specific windows did not survive translation
into the scored metric.

The crash-speed diagnosis itself holds up cleanly and is the more important of the two claims: the
two chop windows are both mildly-to-solidly positive (+6.00%, +1.93%), so directionlessness was
never the failure mode: the failure is concentrated entirely in covid, the one window where the
underlying move was both large and fast. That is exactly what the memo staked its pre-registration
on, and it is exactly what happened.

## 5. Exit-reason distribution and the stop-loss gap

| window | rule | stop | time | open at end | trades |
|---|---:|---:|---:|---:|---:|
| q4-2018   |  2 |  2 | 2 | 4 | 10 |
| covid     |  2 | 11 | 0 | 0 | 13 |
| bear-2022 | 10 |  0 | 3 | 2 | 15 |
| chop-2015 |  9 |  1 | 7 | 0 | 17 |
| chop-2011 |  7 |  3 | 3 | 3 | 16 |
| bull-2024 | 10 |  1 | 2 | 0 | 13 |
| recent    |  3 |  0 | 1 | 0 |  4 |
| gfc       | 16 | 18 | 4 | 2 | 40 |

Covid and gfc are the stop-dominated windows -- 11 of 13 and 18 of 40 exits, respectively -- exactly
where the memo said the mechanism would be forced out rather than complete on its own schedule.

**Stop realised vs nominal 7%, across all 36 stop-outs (previous-close evaluation, next-open
fill):**

| window | stop-outs | avg. gap vs nominal | worst single gap |
|---|---:|---:|---:|
| q4-2018   |  2 | +1.06pp | XLB, +1.93pp (-8.93% realised) |
| covid     | 11 | +2.64pp | XLE/XLI, +8.00pp (-15.00% realised, twice) |
| chop-2015 |  1 | +2.69pp | XLB, +2.69pp (-9.69% realised) |
| chop-2011 |  3 | +2.37pp | XLF, +2.52pp (-9.52% realised) |
| bull-2024 |  1 | -0.92pp | XLY, -0.92pp (-6.08% realised -- better than nominal) |
| gfc       | 18 | +2.52pp | XLU, +7.35pp (-14.35% realised, 2008-10-07) |

Overall: 36 stop-outs average **2.37 percentage points worse** than the nominal 7% (i.e. average
realised loss on a stopped trade is roughly -9.4%, not -7%), consistent with the round-1 finding
that a previous-close stop realises materially worse than its nominal size. The gap is not
symmetric or small: it ranges from -3.86pp (one covid trade, XLB, that recovered before the next
open and closed at only -3.14%) to +8.00pp (two covid trades, XLE and XLI, that gapped straight
through the stop and kept falling to the next open). Both the worst gaps and the highest stop-out
rate occur in the same window, covid, which is the same window that was pre-registered and that
turned out worst -- the stop's own execution slippage is part of why covid is as bad as it is, not
a separate story from the pre-registration.

## 6. Defended, or merely absent?

Judged on capital exposure, this card was **engaged, not absent, in its worst window.** Capital
exposure in covid was 12.53% -- lower than its q4-2018 (23.33%) or gfc (20.55%) figures, but far
from zero, and its session exposure (26.88%) shows it was in the market on over a quarter of covid's
93 sessions. Round 1's finding that some cards scored well in covid purely by being unable to enter
mid-crash does not apply here in the direction that would help this card: the opposite happened.
This card's entry condition (`rsi(14)<30 and close<bb_lower(20,2)`) is *satisfied* by a crashing
market -- it fires repeatedly during the fall, which is exactly the design's stated risk -- and it
paid for that with an 85% stop-out rate (11 of 13 trades) and a -16.66% window return. This is a
card that traded through its own worst regime and lost money doing it, which the memo predicted in
mechanism (§1: "the entry buys directly into a crash that keeps crashing") before it happened in
result.

In its best windows the pattern is different: capital exposure stays modest throughout (11-23%
across all eight windows, never approaching the theoretical 80% ceiling of 4 slots at 20%), which
reflects infrequent signals rather than a deliberate defensive stance -- the card simply does not
find nine sectors simultaneously oversold very often outside a broad selloff.

## 7. Verdict and promotion recommendation

The card did what it was built to do in the two windows that motivated it (chop-2015 +6.00%,
chop-2011 +1.93%, both clean, rule-driven exits) and its own pre-registered failure landed exactly
where predicted, with the finer speed-vs-direction distinction it offered also holding up against
the scored data. Its weakest point is not the chop mandate but the sector-correlation assumption
disclosed in the memo's §7: nine SPDRs behaving as independent draws breaks down precisely in
systemic stress (covid, gfc), which is also where the card's stop-outs cluster.

**Median adjusted excess is positive (+2.72%) and the card clears the gate at 8/8.** Per
`PROTOCOL.md` §6, that satisfies `challenger -> candidates/` this round. Promotion to `base/`
requires a positive median in **two consecutive rounds on window sets that differ**, and this is
this card's first round under this design -- there is no prior round to pair it with. Recommendation:
**promote to `candidates/`**, not `base/`, pending a second round's confirmation. The single largest
risk to that confirmation is covid-style fast-crash exposure recurring in whatever new window round
3 adds; nothing in this round's data suggests the sector-correlation weakness has been addressed,
only measured.

## 8. Attribution: what moved the number

Source: `analysis/attribution.md` / `results/attribution.json`, generated by
`strategy-program/tools/attribution.py`. Contribution is exact, not modelled -- each trade's
`pnl / starting_equity` sums to the card's own scored return in every window below; only trades
moving at least 1% of the book are tabulated individually (the tool's own materiality cutoff), and
where a window's material trades don't account for the whole return, that gap is the aggregate of
many sub-1% trades, noted in prose.

### `bear-2022`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| XLY | 2022-05-12 | 2022-05-31 | 12 | rule | +7.52% | +145 | +1.45% |
| XLK | 2022-01-24 | 2022-02-02 | 7 | rule | +7.12% | +135 | +1.35% |
| XLY | 2022-01-24 | 2022-02-09 | 12 | rule | +6.84% | +133 | +1.33% |
| XLV | 2022-06-15 | 2022-06-27 | 7 | rule | +6.50% | +126 | +1.26% |
| XLB | 2022-09-26 | 2022-10-05 | 7 | rule | +5.53% | +109 | +1.09% |

No single sector dominates: five different SPDRs (`XLY` twice, `XLK`, `XLV`, `XLB`) each contribute
roughly 1.1-1.5 points on ordinary rule exits scattered across the year, catching real
oversold-then-reversion moves in a genuinely bearish tape. The 3 largest winners supply 42% of gross
winning P&L; strip them and the card still returns **+3.77%** on the other 12 trades -- this window's
edge is broad-based, not a lucky trade.

### `bull-2024`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| XLF | 2025-04-07 | 2025-04-24 | 12 | rule | +10.89% | +210 | +2.10% |
| XLI | 2025-04-07 | 2025-04-24 | 12 | rule | +9.91% | +182 | +1.82% |
| XLB | 2024-12-16 | 2025-01-08 | 15 | time | -6.04% | -118 | -1.18% |
| XLY | 2025-02-28 | 2025-03-12 | 8 | stop | -6.08% | -116 | -1.16% |
| XLK | 2025-04-04 | 2025-04-24 | 13 | rule | +5.63% | +107 | +1.07% |

`XLF` and `XLI`, entered the same session (2025-04-07) and exited the same session (2025-04-24) --
both catching the same April 2025 snapback -- together supply +3.92 of the window's +6.86%, more
than half its gross winning P&L (54%). Without the 3 largest winners the card still clears **+1.87%**,
so the window is not entirely those two trades, but they are its clearest single driver.

### `chop-2011`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| XLB | 2011-10-04 | 2011-10-11 | 5 | rule | +13.86% | +273 | +2.73% |
| XLI | 2011-08-03 | 2011-08-09 | 4 | stop | -10.21% | -204 | -2.04% |
| XLF | 2011-08-05 | 2011-08-09 | 2 | stop | -9.52% | -192 | -1.92% |
| XLV | 2011-08-02 | 2011-08-09 | 5 | stop | -8.37% | -165 | -1.65% |
| XLF | 2011-08-11 | 2011-08-30 | 13 | rule | +6.76% | +137 | +1.37% |
| XLE | 2011-09-26 | 2011-10-11 | 11 | rule | +6.56% | +132 | +1.32% |
| XLP | 2011-08-11 | 2011-08-24 | 9 | rule | +5.78% | +115 | +1.15% |

One trade -- `XLB`, Oct 4-11 -- is bigger on its own (+2.73%) than the window's entire +1.93% result.
It follows a cluster of three stop-outs within a week of each other in early August 2011 (`XLI`,
`XLF`, `XLV`, all around the US sovereign-downgrade/European flare), which the rule then recovered
from via three further winners later in August and September. The 3 largest winners supply 62% of
gross winning P&L, but without them the card would have **lost -3.49%** in this window -- the
positive headline rests on a small number of trades net of a mixed, largely breakeven book.

### `chop-2015`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| XLB | 2016-01-08 | 2016-01-20 | 7 | stop | -9.69% | -194 | -1.94% |
| XLK | 2015-08-24 | 2015-09-14 | 14 | rule | +9.67% | +181 | +1.81% |
| XLB | 2015-09-29 | 2015-10-06 | 5 | rule | +8.98% | +179 | +1.79% |
| XLV | 2015-09-29 | 2015-10-13 | 10 | rule | +5.87% | +117 | +1.17% |
| XLF | 2016-02-12 | 2016-02-18 | 3 | rule | +5.13% | +105 | +1.05% |

Broader-based than chop-2011: four rule-exit winners supply 48% of gross winning P&L, and without
them the card still clears **+1.22%** on its other 13 trades -- this window's edge does not hinge on
any one position the way chop-2011's does.

### `covid`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| XLU | 2020-03-24 | 2020-03-31 | 5 | rule | +22.66% | +471 | +4.71% |
| XLE | 2020-03-10 | 2020-03-12 | 2 | stop | -15.00% | -322 | -3.22% |
| XLI | 2020-02-26 | 2020-03-09 | 8 | stop | -15.00% | -294 | -2.94% |
| XLU | 2020-03-17 | 2020-03-23 | 4 | stop | -10.41% | -214 | -2.14% |
| XLI | 2020-03-17 | 2020-03-23 | 4 | stop | -10.42% | -207 | -2.07% |
| XLE | 2020-02-25 | 2020-02-27 | 2 | stop | -10.04% | -200 | -2.00% |
| XLI | 2020-03-10 | 2020-03-13 | 3 | stop | -9.21% | -188 | -1.88% |
| XLV | 2020-02-26 | 2020-03-13 | 12 | stop | -9.25% | -181 | -1.81% |
| XLF | 2020-03-10 | 2020-03-13 | 3 | stop | -8.34% | -173 | -1.73% |
| XLF | 2020-02-26 | 2020-03-02 | 3 | stop | -8.05% | -161 | -1.61% |
| XLF | 2020-03-13 | 2020-03-17 | 2 | stop | -7.17% | -154 | -1.54% |
| XLB | 2020-03-17 | 2020-03-24 | 5 | stop | -3.14% | -63 | -0.63% |
| XLP | 2020-02-27 | 2020-03-05 | 5 | rule | +1.06% | +21 | +0.21% |

This is the window §3/§5 already flag as the pre-registered failure, and the trade log shows the
mechanism directly: the card's oversold-and-below-band entry kept firing on sectors that had further
to fall, and 11 of 13 trades (85%) were stopped out. The single profitable trade, `XLU` (Mar 24-31,
+22.66%), caught the initial post-bottom bounce and alone contributes more to the card's return
(+4.71 points) than any other single trade in this window, winning or losing. Only two trades were
ever winners (`XLU`, `XLP`); the 3 largest winners (there are only 2) supply 100% of gross winning
P&L, and without them the card would have lost **-21.57%** rather than -16.66%. The stop overshoot
compounds the damage precisely where §5 quantifies it: the two -15.00% exits (`XLE`, `XLI`) alone
account for -6.16 points of the window's -16.66% return -- more than a third of the total loss --
purely from a nominal 7% stop realising more than double its size on a gap-down market. This is entry
buying directly into a crash, not stop mechanics failing independently of it: both are visible in the
same 13-trade log.

### `gfc`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| XLF | 2008-11-21 | 2008-12-08 | 10 | rule | +35.54% | +744 | +7.44% |
| XLY | 2008-11-21 | 2008-11-28 | 4 | rule | +21.85% | +442 | +4.42% |
| XLF | 2008-07-15 | 2008-07-18 | 3 | rule | +18.78% | +370 | +3.70% |
| XLF | 2009-01-21 | 2009-02-09 | 13 | rule | +15.22% | +322 | +3.22% |
| XLP | 2008-10-13 | 2008-10-27 | 10 | stop | -13.28% | -285 | -2.85% |
| XLU | 2008-10-07 | 2008-10-10 | 3 | stop | -14.35% | -285 | -2.85% |
| XLV | 2008-10-09 | 2008-10-10 | 1 | stop | -12.88% | -260 | -2.60% |
| XLI | 2008-10-03 | 2008-10-08 | 3 | stop | -12.24% | -244 | -2.44% |
| XLE | 2008-09-10 | 2008-09-22 | 8 | rule | +11.16% | +225 | +2.25% |
| XLB | 2008-10-06 | 2008-10-08 | 2 | stop | -10.98% | -214 | -2.14% |
| XLK | 2008-09-18 | 2008-10-06 | 12 | stop | -9.93% | -200 | -2.00% |

(15 further material trades omitted here for length; full 40-row list is in `analysis/attribution.md`
under `c07-chop` / `gfc`.)

The largest single trade -- `XLF`, entered 2008-11-21 into the immediate post-Citigroup-bailout
relief -- returned +35.54% and alone supplies +7.44 points of the card's -8.04% return. It and the
next two winners (`XLY`, `XLF` again) are all similarly-timed entries into the November
2008-February 2009 bounce. Set against them, the crash-buying flaw recurs exactly as in covid: 18 of
40 trades were stopped out (§5), and several of the largest losses cluster within days of each other
in the first two weeks of October 2008 (`XLP`, `XLU`, `XLV`, `XLI`), the collapse's sharpest leg. The
3 largest winners supply 52% of gross winning P&L; without them the card returns **-23.59%** rather
than -8.04% -- most of this window's +48.19% raw outperformance against SPY's -56.23% sits in three
trades that caught a short, sharp relief rally inside a much longer bear market, not in a defensive
posture sustained throughout.

### `q4-2018`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| XLE | 2018-12-19 | _open_ | 3 | **open_at_end** | -10.06% | -202 | -2.02% |
| XLB | 2018-10-10 | 2018-10-25 | 11 | stop | -8.93% | -177 | -1.77% |
| XLI | 2018-10-11 | 2018-10-25 | 10 | stop | -7.18% | -140 | -1.40% |
| XLP | 2018-12-20 | _open_ | 2 | **open_at_end** | -6.11% | -120 | -1.20% |
| XLF | 2018-10-25 | 2018-11-06 | 8 | rule | +5.51% | +111 | +1.11% |
| XLI | 2018-12-21 | _open_ | 1 | **open_at_end** | -5.19% | -102 | -1.02% |

A slower, shallower selloff than covid, and the trade log confirms it: only 2 of 9 trades were
stopped (against 11 of 13 in covid), and three of the six material trades are simply still open when
the window ends -- `XLE`, `XLP`, `XLI`, all entered in the final two weeks of December 2018 and
marked at a loss against the close. **-4.98% of the card's -6.52% return is an unrealised mark**, not
money actually lost; without it the realised result is closer to -1.5%. The only winner (`XLF`,
Oct 25-Nov 6, +5.51%) is a single ordinary rule exit into a bounce.

### `recent`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| XLK | 2026-03-31 | 2026-04-07 | 4 | rule | +5.33% | +103 | +1.03% |

This card's quietest window by trade count -- 4 trades across 249 sessions on only 3.66% capital
exposure. With SPY up +20.62% over the same stretch, the near-flat +0.55% result is a card that found
almost nothing to do, not one that lost ground fighting the tape: the broad-market oversold-and-below-
band entry rarely fires in a grinding bull market, consistent with the low signal frequency §6
describes across the whole matrix.

## 9. Concentration and unrealised marks

| window | top-3 share of gross wins | return w/o top-3 winners | unrealised share |
|---|---:|---:|---:|
| bear-2022 | 42% | +3.77% | -0.63% |
| bull-2024 | 54% | +1.87% | -- |
| chop-2011 | 62% | -3.49% | -0.37% |
| chop-2015 | 48% | +1.22% | -- |
| covid | 100% | -21.57% | -- |
| gfc | 52% | -23.59% | -2.12% |
| q4-2018 | 100% | -8.51% | -4.98% |
| recent | 100% | -0.81% | -- |

Concentration varies sharply and for different reasons window to window. chop-2011 and covid sit at
opposite extremes of what "concentrated" means in practice: chop-2011's 62% figure sounds moderate,
but the result still flips to a **loss** (-3.49%) without its top 3 winners, because the other 13
trades net out slightly negative on their own -- concentration there is masking a mixed book, not a
uniformly profitable one. Covid and recent both show "100%" simply because they had two or fewer
winning trades in total, not because one position dominated many others; in q4-2018, 100% concentration
sits alongside the largest unrealised share in the table (-4.98% of -6.52%, i.e. most of that window's
loss is a paper mark against three still-open positions, not money actually lost). Unrealised marks
never prop up a *positive* result for this card: every window that finished ahead (bear-2022,
bull-2024, chop-2011, chop-2015) had its winners fully realised by the window's close -- the only
windows carrying a material unrealised component (q4-2018, gfc, both -2% to -5%) are negative windows
where the mark makes the realised loss look slightly worse than the headline, not better. The
promotion case in §7 does not rest on any open mark.

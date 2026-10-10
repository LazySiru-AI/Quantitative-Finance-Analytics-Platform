# The same 26 strategies over three years

`RESULTS.md` scored 26 strategies over 127 blind sessions. This re-runs the identical cards,
unmodified, over **751 sessions from 2023-08-21 to 2026-08-18** — the last three years — through the
same broker, the same fills, and the same single-name cap.

**Benchmark: SPY buy-and-hold over the same 751 sessions, +75.40%.**

Two benchmark numbers appear in this repo and they are not interchangeable. `+75.40%` is what the
runner computes: bought at the first session's open, sold at the last session's close, **price only,
no dividends** — the identical convention every strategy here gets, which is what makes the
comparison like for like. A real buy-and-hold investor with dividends reinvested made **+81.32%**
(see `results/regime-2023-2026.md`). The strategies do not receive dividends either, so the
real-world bar is the higher one and every margin below is flattered by roughly six points.

## Read this before the table

**Most of this window is in-sample.** Every card declares `designed_through: 2026-02-13`. Of the 751
sessions, about 630 fall before that cutoff — data the analysts were allowed to study, and did. Only
the final 127 sessions were ever blind, and those are the window `RESULTS.md` already reported. So a
three-year number here is **mostly a measure of fit**, not a second out-of-sample test. It answers
"do these rules describe the recent past?" and not "do these rules work?"

That limitation is now printed on every PDF in `results/3yr/pdf/`, replacing the out-of-sample claim
that would otherwise be false for this window.

## What happened

Every card over all three windows. **Bold means it beat SPY over that window**, so a row's bold
count is how many of the three it won. Sorted by the three-year column.

| | agent | trades | in-sample (624) | blind (127) | full 3yr (751) | max DD | exposure |
|---|---|---|---|---|---|---|---|
| — | **SPY benchmark** | — | **+55.81%** | **+12.84%** | **+75.40%** | — | 100% |
| r1 | a07-rotation | 124 | **+104.85%** | **+40.71%** | **+145.08%** | −15.01% | 90.3% |
| r1 | a03-momentum | 41 | **+87.72%** | **+31.97%** | **+119.30%** | −16.31% | 98.4% |
| r1 | a01-trend | 42 | **+90.10%** | +1.87% | **+91.66%** | −10.66% | 85.8% |
| r1 | a05-volatility | 174 | +45.02% | **+19.20%** | +64.10% | −12.23% | 70.2% |
| r2 | a01-trend | 37 | **+60.05%** | −3.14% | +59.14% | −7.75% | 95.5% |
| r2 | a03-momentum | 25 | +38.03% | +6.40% | +45.29% | −10.36% | 96.9% |
| r1 | a11-13f-conviction | 227 | +34.73% | +2.19% | +37.71% | −11.96% | 90.1% |
| r2 | a12-13f-newbuys | 131 | +38.54% | −0.40% | +36.56% | −7.75% | 97.9% |
| r2 | a07-rotation | 88 | +36.18% | +1.48% | +35.29% | −5.67% | 93.9% |
| r1 | a09-fastrev | 128 | +11.00% | **+22.84%** | +33.86% | −19.25% | 28.0% |
| r1 | a13-13f-crowding | 227 | +30.41% | −2.12% | +28.35% | −18.70% | 96.0% |
| r2 | a10-asymmetric | 147 | +20.93% | −0.64% | +20.88% | −11.62% | 80.4% |
| r2 | a11-13f-conviction | 99 | +15.57% | +5.21% | +20.14% | −3.09% | 97.2% |
| r1 | a06-riskmanaged | 34 | +16.54% | −0.45% | +16.09% | −4.26% | 51.4% |
| r2 | a09-fastrev | 168 | +10.06% | +2.96% | +13.16% | −6.01% | 33.0% |
| r1 | a02-meanrev | 8 | +7.13% | +1.76% | +8.89% | −2.06% | 11.9% |
| r2 | a13-13f-crowding | 79 | −4.07% | +10.50% | +7.01% | −11.78% | 88.7% |
| r1 | a04-breakout | 29 | −2.42% | +9.14% | +6.26% | −8.83% | 36.5% |
| r2 | a02-meanrev | 9 | +5.04% | +0.35% | +3.67% | −3.46% | 10.4% |
| r2 | a06-riskmanaged | 47 | +3.01% | −0.40% | +2.48% | −6.76% | 65.2% |
| r1 | a08-slowtrend | 0 | +0.00% | +0.00% | +0.00% | 0.00% | 0.0% |
| r2 | a08-slowtrend | 0 | +0.00% | +0.00% | +0.00% | 0.00% | 0.0% |
| r2 | a05-volatility | 160 | −2.80% | +1.22% | −2.23% | −9.80% | 60.6% |
| r2 | a04-breakout | 103 | −0.61% | −0.63% | −4.12% | −10.51% | 76.7% |

Two cards are absent because they cannot run over a window starting 2023-08-21 —
`a12-13f-newbuys` r1 and `a10-asymmetric` r1. Both have results over their own legal windows,
below.

**Three of 24 beat the benchmark over the full three years, four in-sample, four blind — and only
two in all three: `a07-rotation` and `a03-momentum`.** Both are round one, and they are the only
rows above with three bold cells.

The in-sample column is the one to read sceptically. It covers the 624 sessions each analyst was
allowed to study before submitting, so a card that fails to beat SPY *there* failed on data it had
already seen. **Twenty of 24 lost to the benchmark on their own design window**, 13 returned under
+20% against +55.81%, and four were outright negative (`a04-breakout` in both rounds,
`a05-volatility` r2, `a13-13f-crowding` r2).

That is worth sitting with, because it is the opposite of the failure everyone expects. The usual
worry about a designed-then-tested strategy is that it looks brilliant in-sample and collapses out
of it. These mostly did not manage the first half.

## The three windows, and the finding that matters most

The same 24 cards were run over three windows: the **in-sample** portion the analysts designed on,
the **blind** 127 sessions of the original tournament, and the **full** three years. These are three
independent runs, each starting flat with fresh capital — not an additive decomposition. (For
buy-and-hold that distinction is immaterial: 1.5581 × 1.1284 = +75.82% against +75.40% measured
directly. For a strategy holding positions across the seam it is not, which is why no product of
sub-window returns appears below.)

| window | sessions | SPY |
|---|---|---|
| in-sample 2023-08-21 → 2026-02-13 | 624 | +55.81% |
| blind 2026-02-17 → 2026-08-18 | 127 | +12.84% |
| full 2023-08-21 → 2026-08-18 | 751 | +75.40% |

**Rank correlation between in-sample return and blind return: Spearman ρ = 0.162.**

That is the headline of this document. How a strategy performed on the data its author was allowed
to study told you **almost nothing** about how it performed on data nobody had seen. Four cards
inverted outright:

| card | in-sample | blind | full |
|---|---|---|---|
| `a09-fastrev` r1 | **+11.00%** (−45 vs bench) | **+22.84%** (+10) | +33.86% (−41) |
| `a01-trend` r1 | **+90.10%** (+34) | **+1.87%** (−11) | +91.66% (+16) |
| `a04-breakout` r1 | −2.42% | +9.14% | +6.26% |
| `a13-13f-crowding` r2 | −4.07% | +10.50% | +7.01% |

`a09-fastrev` is the sharpest case. It was the single strategy the multiple-testing correction
flagged in the favourable direction, and it **lost to the benchmark by 45 points on its own design
data** before beating it by 10 in the blind window. A strategy that underperforms in-sample and
outperforms out-of-sample is not an overfit; it is a coin that landed well once.

**Only two of 24 beat the benchmark in all three windows: `a07-rotation` and `a03-momentum`,
both round one.** Everything else won at most two.

| beat benchmark in… | n | which |
|---|---|---|
| in-sample | 4 | `a07-rotation`, `a01-trend` r1, `a03-momentum`, `a01-trend` r2 |
| blind | 4 | `a07-rotation`, `a03-momentum`, `a09-fastrev`, `a05-volatility` |
| full three years | 3 | `a07-rotation`, `a03-momentum`, `a01-trend` r1 |
| **all three** | **2** | **`a07-rotation`, `a03-momentum`** |

## The two cards that needed a shorter window

| card | blocking symbol | first bar | earliest legal start |
|---|---|---|---|
| `a12-13f-newbuys` (r1) | SNDK | 2025-02-13 | 2025-12-04 |
| `a10-asymmetric` (r1) | NBIS | 2024-10-21 | 2025-01-07 |

Both hold a symbol that did not trade for much of the window. The lookahead guard refuses to certify
`sma(200)` against zero bars — it reports "causality could not be demonstrated" rather than passing
on no evidence — so both raise rather than run over three years. `a12-13f-newbuys` was the
tournament's **second-best** strategy at +33.81%.

No substitute card was run. Dropping SNDK would produce a number, but for a different strategy from
the one submitted. Instead each was run **exactly as written over the longest window its own
universe permits**:

| card | window | sessions | trades | return | benchmark | max DD | exposure |
|---|---|---|---|---|---|---|---|
| `a12-13f-newbuys` r1 | 2025-12-04 → 2026-08-18 | 176 | 30 | **+56.93%** | +11.99% | −12.66% | 98.9% |
| `a10-asymmetric` r1 | 2025-01-07 → 2026-08-18 | 404 | 115 | **+59.53%** | +28.46% | −22.98% | 79.0% |

Both beat their own window's benchmark — `a12` by 45 points, `a10` by 31. Each window has its own
SPY return; neither may be compared against the three-year +75.40%.

**`a12-13f-newbuys`'s window is the most out-of-sample result in this project.** Its 176 sessions
begin 2025-12-04 and the design cutoff is 2026-02-13, so only about 49 sessions are in-sample and
**roughly 72% of the run is blind** — a far higher out-of-sample fraction than the three-year runs,
where it is 17%. Its 22% win rate against a +56.93% return is the asymmetric payoff its thesis
described. This is the single most interesting result in the tournament, and it exists only because
the card was run over a window it could legally occupy rather than being dropped.

`a10-asymmetric`'s window is the reverse — about 69% in-sample — and carries the deepest drawdown
measured anywhere in this project at −22.98%.

## The ranking barely survived

Rank correlation between the six-month and three-year returns, across the 24 cards with both:
**Spearman ρ = 0.39** (Pearson 0.73, inflated by two large winners at both horizons). Note this
overstates the agreement, because the three-year window *contains* the six-month one. The clean
comparison — in-sample against blind, two windows sharing no sessions — is **ρ = 0.162**.

A tournament that ranked 26 strategies on 127 sessions retained only a weak ordering over three
years. Concretely:

* `a01-trend` placed **13th of 26** over six months at +1.87% — and is **third** over three years at
  +91.66%, one of only three to beat the benchmark.
* `a09-fastrev` was the single strategy flagged favourably by the correction — 95% win rate, +22.84%,
  a −1.85% drawdown. Over three years it returns +33.86% against +75.40%, **41 points behind**, with
  a **−19.25%** drawdown and a 70% win rate. The −1.85% figure was a property of 127 sessions, not of
  the strategy.
* `a05-volatility` beat the benchmark over six months (+19.20% vs +12.84%) and lost over three
  (+64.10% vs +75.40%).

## Exposure explains more than edge

In a window where SPY rose 75% and closed above its 200-day average in 91.6% of sessions, the
dominant variable is simply how much of the time a strategy was invested.

| | Spearman ρ with return |
|---|---|
| exposure vs 3-year return | **0.648** |
| exposure vs 6-month return | 0.186 |

| exposure band | n | mean 3-year return |
|---|---|---|
| ≥ 85% | 11 | **+56.87%** |
| < 40% | 7 | **+9.41%** |

`a09-fastrev` was in the market 28.0% of the time; `a02-meanrev` 11.9%; `a08-slowtrend` 0.0%. None
of them could have kept up, and their shortfall is not evidence their rules are wrong — it is
evidence that cash was the losing asset for three years. The correct reading of a −41 point
shortfall on 28% exposure is *"this strategy was not trying to be a market substitute"*, not
*"this strategy failed."*

The converse also holds, and limits how much credit the winners get. `a03-momentum` was invested
98.4% of the time and returned +119.30%; being fully invested alone would have returned +75.40%. The
rules added roughly 44 points over three years. `a07-rotation` at 90.3% exposure added roughly 70.

**`a08-slowtrend` has now taken zero trades in every window tested.** Its `ema(300)` gate has never
opened, on either universe, over six months or three years.

## The statistics are worse here, not better

The run reports **14 discoveries of 24 at α=0.10**. That number should not be read as fourteen
working strategies.

The test is a two-sided binomial against a fair coin, so it flags win rates far *below* 50% exactly
as strongly as those above. `a12-13f-newbuys` (r2) has q = 0.0000 on a **24%** win rate.
`a11-13f-conviction` (r1) has q = 0.0000 on **34%**. Both are "discoveries" of being reliably
unlike a coin flip in the losing direction. Meanwhile `a03-momentum` — second-best by return, +44
points of genuine excess — has **q = 1.0000**, because its win rate is 49% and a coin flip is
exactly what a 49% win rate looks like.

Trade counts rose roughly six-fold with the longer window, which sharpens the binomial test and
produces more rejections of the null. It does not produce more evidence of skill. **As in
`RESULTS.md`, these q-values cannot be read as evidence of skill** — they test a claim about win
rates that is close to unrelated to beating the market.

## Round one still beats round two

Ten of the 24 pairs let round one and round two be compared directly on the same rules:

| agent | r1 | r2 |
|---|---|---|
| a07-rotation | +145.08% | +35.29% |
| a03-momentum | +119.30% | +45.29% |
| a01-trend | +91.66% | +59.14% |
| a05-volatility | +64.10% | −2.23% |
| a09-fastrev | +33.86% | +13.16% |
| a13-13f-crowding | +28.35% | +7.01% |
| a06-riskmanaged | +16.09% | +2.48% |
| a02-meanrev | +8.89% | +3.67% |
| a04-breakout | +6.26% | −4.12% |
| a11-13f-conviction | +37.71% | +20.14% |

**Round one wins all ten.** The concentrated semiconductor universe beat the diversified one over
three years as decisively as it did over six months — but note what the window was: SOXX returned
**+228.88%** over it, against SPY's +81.32%. This is not a finding that concentration is better. It
is a finding that *this particular concentration* was correct for *this particular window*, which
the analysts could see when they picked it, because most of the window was already behind them.

The round-two books did buy something real for the gap: `a01-trend` r2 gave up 32 points of return
and took a −7.75% drawdown instead of −10.66%; `a11-13f-conviction` r2 gave up 17 points for a
−3.09% drawdown instead of −11.96%. Insurance, again unclaimed, in a window with no accident.

## The 13F cards: three-year numbers that mean nothing

`a11`, `a12` and `a13` chose their universes from specific 13F filings, named with filing dates in
their own theses:

| card | universe knowable from |
|---|---|
| `a11-13f-conviction` | 2025-11-14 |
| `a12-13f-newbuys` | 2025-11-14 |
| `a13-13f-crowding` | **2026-02-13** |

A backtest starting 2023-08-21 trades a basket **selected using documents that did not exist for the
first two years of the window.** This is not ordinary in-sample reuse; it is a portfolio chosen with
knowledge of which names would work.

The lookahead guard passes them anyway, and that is a limitation of the guard, not a clearance: it
checks whether an indicator is causal on symbols already chosen. It has no way to know when the
*basket* became knowable. **`a11-13f-conviction`'s +37.71% and `a13-13f-crowding`'s +28.35% over
three years should be read as unmeasured, not as results** — and both lost to the benchmark by wide
margins even with that advantage.

## What this does not show

* **Not an out-of-sample test.** About 630 of 751 sessions are in-sample. This measures fit.
* **One regime, again.** Three years is longer than six months and is still a single continuous bull
  market: no down calendar segment, deepest SPY drawdown −18.76%, every drawdown recovered inside the
  window. The regimes these strategies were designed to fear still have not occurred.
* **A selected universe, twice over.** Round one's 43 tickers were chosen because the user already
  traded them, in a window where the semiconductor complex tripled.
* **Simulated fills.** Next-session open with deterministic adverse slippage; stops evaluated against
  the previous close.
* **The single-name cap is still raised to 1.0**, as in `RESULTS.md`, so concentrated cards run as
  written. Drawdowns should be read in that light.

None of this is advice, and none of these strategies has been shown to work.

## Artifacts

* `results/3yr/runs/` — 24 full runs over 751 sessions, every trade and rejection
* `results/3yr/pdf/r1/`, `pdf/r2/` — 24 per-agent PDF reports, window-correct
* `results/3yr/tournament.json` — scored across all 24, 751 sessions
* `results/insample/runs/` — the same 24 cards over the 624 in-sample sessions
* `results/insample/pdf/r1/`, `pdf/r2/` — 24 in-sample PDF reports
* `results/insample/tournament.json` — scored across all 24, 624 sessions
* `results/legalwindow/a12/`, `legalwindow/a10/` — the two cards over their longest legal windows
* `results/regime-2023-2026.md` — what the market did over the same window

Benjamini-Hochberg is applied once across all 24 in each scored set. The in-sample runs were
executed as three parallel shards; each shard's own `tournament.json` would have corrected against a
denominator of 8, so those were discarded and the set re-scored as one before anything here was
written.

# The chop windows -- round 2 analysis

Round 1 ran two bears, one crash, a sharp quarter-long selloff and two bulls, and no directionless
regime at all -- yet several analysts pre-registered whipsaw as the thing they feared most, a
prediction the matrix had no way to score. Round 2 added two: `chop-2015` (2015-04-07 to 2016-04-15,
260 sessions, SPY -0.04%, 16.6% annualised vol) and `chop-2011` (2011-05-26 to 2012-06-06, 260
sessions, SPY -0.05%, 22.9% vol). Both were found by scanning thirty years of SPY for windows that go
nowhere while moving constantly, not corrections relabelled as chop.

23 cards ran `chop-2015`. Only 15 could run `chop-2011`: the five `A`-family and five `B`-family
semiconductor/mega-cap variants, `C-trend`, and `H-trend-diversified` are all locked out by `NOW`,
`META` or `INDA`'s 2012-and-later first bars; `c06-13f-momentum` is separately blocked from every
main window (chop-2011 included) by its 13F provenance rule -- its 2025-11-14 filing date postdates
every window in the matrix, so its chop-2015 number below is published for reference only and is
**unranked**, per `PROTOCOL.md` §3.7.

All figures are `total_return - capital_exposure * benchmark_return`, computed directly from each
card's `results/<window>/runs/*.json` at full precision, not the two-decimal benchmark figures quoted
in the brief.

## 1. Full results

### `chop-2015` (23 cards, sorted by adjusted excess)

| agent | discipline | trades | return | adj. excess | capital exp. | session exp. | max DD | win rate |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| B-momentum          | momentum       | 22 | +24.58% | **+24.60%** | 56.33% | 99.23% | -12.17% | 23.53% |
| B4-tight-stop        | momentum       | 22 | +24.58% | **+24.60%** | 56.28% | 99.23% | -12.17% | 23.53% |
| B3-concentrated      | momentum       | 19 | +23.26% | **+23.29%** | 65.44% | 99.23% | -14.57% | 20.00% |
| B2-hold-90           | momentum       | 27 | +17.57% | **+17.58%** | 46.37% | 99.23% |  -9.92% | 23.81% |
| c06-13f-momentum*    | momentum       | 70 | +11.51% | **+11.53%** | 54.90% | 89.62% | -10.94% | 27.94% |
| C-trend              | trend          | 17 | +11.00% | **+11.02%** | 40.24% | 95.38% | -13.29% | 15.38% |
| B1-with-target       | momentum       | 26 | +10.03% | **+10.05%** | 41.21% | 96.92% | -10.77% | 23.81% |
| H-trend-diversified  | trend          |  4 |  +7.54% |  **+7.54%** |  5.69% | 23.08% |  -2.32% |  0.00% |
| c07-chop             | mean-reversion | 17 |  +6.00% |  **+6.00%** | 14.26% | 31.92% |  -4.48% | 70.59% |
| A3-no-target         | pairs-rotation | 30 |  +3.68% |  **+3.70%** | 51.97% | 81.15% | -19.46% | 25.93% |
| c09-convex           | volatility     | 13 |  -1.23% |  **-1.22%** |  8.46% | 48.08% |  -3.17% | 25.00% |
| c11-breakout         | breakout       |  6 |  -1.95% |  **-1.94%** | 17.98% | 41.15% |  -3.95% |  0.00% |
| c01-meanrev          | mean-reversion | 15 |  -2.19% |  **-2.19%** |  9.91% | 36.15% |  -4.85% | 60.00% |
| c05-trend            | trend          | 15 |  -2.47% |  **-2.46%** | 23.25% | 52.31% |  -6.92% |  0.00% |
| c02-volatility       | volatility     |  9 |  -3.77% |  **-3.76%** | 36.93% | 66.92% |  -6.71% | 33.33% |
| c04-riskmanaged      | risk-managed   | 21 |  -3.98% |  **-3.96%** | 35.66% | 76.54% |  -8.67% |  0.00% |
| A1-alpha-order       | pairs-rotation | 33 |  -4.87% |  **-4.85%** | 48.51% | 81.15% | -21.73% | 23.33% |
| c08-generalist       | trend          | 14 |  -5.64% |  **-5.63%** | 37.01% | 73.08% |  -8.64% |  0.00% |
| c03-breakout         | breakout       | 12 |  -6.04% |  **-6.03%** | 37.17% | 77.69% |  -9.49% |  0.00% |
| c10-momentum         | momentum       | 27 |  -6.90% |  **-6.90%** | 10.63% | 24.62% |  -7.66% |  8.33% |
| A-rotation           | pairs-rotation | 33 |  -7.18% |  **-7.16%** | 48.78% | 81.15% | -19.46% | 20.00% |
| A4-tight-stop        | pairs-rotation | 33 |  -7.30% |  **-7.28%** | 48.94% | 81.15% | -19.46% | 20.00% |
| A2-cash-headroom     | pairs-rotation | 44 |  -9.27% |  **-9.25%** | 47.83% | 81.15% | -17.55% | 22.50% |

\* `c06-13f-momentum` fails the provenance gate on every main window (universe knowable only from
2025-11-14). Its number is published above for reference, per `PROTOCOL.md`'s "unranked, not last"
rule, and excluded from every median/hit-rate calculation in this document.

### `chop-2011` (15 cards, sorted by adjusted excess)

| agent | discipline | trades | return | adj. excess | capital exp. | session exp. | max DD | win rate |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| c11-breakout    | breakout       |  6 |  +6.73% | **+6.75%** | 48.87% |  84.62% | -3.96% | 33.33% |
| c05-trend       | trend          | 18 |  +4.44% | **+4.46%** | 49.33% |  95.77% | -6.02% | 37.50% |
| c09-convex      | volatility     |  9 |  +3.75% | **+3.75%** |  9.39% |  55.38% | -1.79% | 62.50% |
| c08-generalist  | trend          | 14 |  +2.68% | **+2.72%** | 80.97% | 100.00% | -4.93% | 18.18% |
| c10-momentum    | momentum       | 22 |  +2.61% | **+2.62%** | 23.18% |  42.69% | -5.31% | 31.82% |
| c07-chop        | mean-reversion | 16 |  +1.93% | **+1.93%** | 12.78% |  28.46% | -7.63% | 61.54% |
| c04-riskmanaged | risk-managed   | 25 |  -0.22% | **-0.20%** | 60.21% | 100.00% | -6.25% | 30.43% |
| c02-volatility  | volatility     |  6 |  -0.36% | **-0.35%** | 25.08% |  38.08% | -4.65% | 66.67% |
| c03-breakout    | breakout       |  9 |  -1.37% | **-1.35%** | 45.72% |  85.00% | -6.52% | 50.00% |
| c01-meanrev     | mean-reversion | 30 |  -5.17% | **-5.17%** | 16.27% |  30.77% | -7.30% | 56.00% |
| A1-alpha-order  | pairs-rotation | 27 | -13.56% | **-13.54%** | 44.47% |  77.31% | -26.52% | 14.81% |
| A2-cash-headroom| pairs-rotation | 34 | -16.80% | **-16.78%** | 45.24% |  78.46% | -23.94% | 14.71% |
| A3-no-target    | pairs-rotation | 25 | -16.90% | **-16.88%** | 44.85% |  77.69% | -24.85% | 12.00% |
| A-rotation      | pairs-rotation | 26 | -17.03% | **-17.01%** | 44.68% |  77.69% | -24.85% | 15.38% |
| A4-tight-stop   | pairs-rotation | 27 | -19.12% | **-19.10%** | 44.44% |  76.92% | -26.92% | 14.81% |

## 2. Which disciplines survived, and which did not

By discipline, median adjusted excess (cards with n=1 are single data points, not medians):

| discipline | chop-2015 median (n) | chop-2011 median (n) |
|---|---:|---:|
| momentum       | +17.58% (7) | +2.62% (1) |
| trend          |  +2.54% (4) | +3.59% (2) |
| mean-reversion |  +1.91% (2) | -1.62% (2) |
| breakout       |  -3.99% (2) | +2.70% (2) |
| volatility     |  -2.49% (2) | +1.70% (2) |
| risk-managed   |  -3.96% (1) | -0.20% (1) |
| pairs-rotation |  -7.16% (5) | **-16.88% (5)** |

**Only one discipline failed cleanly in both windows: `pairs-rotation`** -- the five `A`-family
semiconductor-rotation variants. Four of five posted negative adjusted excess in `chop-2015`
(median -7.16%) and **all five** were negative in `chop-2011`, uniformly and by a wide margin (median
-16.88%, worst -19.10%). This is the one case in the matrix where a discipline, not an individual
card, failed both draws of the sideways regime consistently. See §4 for why.

Every other discipline **split** across the two windows, sometimes sharply, and the split does not
track discipline labels cleanly:

- **Momentum** looks like the best discipline in `chop-2015` (four of five `B`-family variants
  above +17%, `B-momentum`/`B4-tight-stop` at +24.60%) but that is one 12-symbol mega-cap/semis
  universe running four brackets of the same rule. The other momentum card in the field,
  `c10-momentum` (an 8-symbol sector/QQQ universe), lost -6.90% in the same window -- worse than
  every trend, breakout or volatility card except the sector-only breakout. Momentum-as-a-label
  predicts almost nothing here; momentum-with-this-specific-universe does.
- **Trend** splits within itself too: `C-trend` (+11.02%) and `H-trend-diversified` (+7.54%,
  cross-asset) both won `chop-2015` comfortably, while `c05-trend` (-2.46%) and `c08-generalist`
  (-5.63%, the worst trend card) both lost it, on the same broad discipline label.
- **Breakout** is the only discipline besides pairs-rotation with a full sign flip between windows
  as a pair: `c03-breakout` lost both (-6.03%, -1.35%) and `c11-breakout` lost `chop-2015` (-1.94%)
  but won `chop-2011` decisively (+6.75%) -- see `reports/c11-breakout.md` §5 for why the win came
  from a flight-to-duration trade riding through the window rather than from surviving whipsaw.

**Sign flips, card by card, across the 15 that ran both windows:**

| agent | chop-2015 | chop-2011 | delta | flips sign |
|---|---:|---:|---:|---|
| A3-no-target     |  +3.70% | -16.88% | 20.58 | yes |
| A4-tight-stop     |  -7.28% | -19.10% | 11.82 | no |
| A-rotation        |  -7.16% | -17.01% |  9.85 | no |
| c10-momentum      |  -6.90% |  +2.62% |  9.52 | **yes** |
| c11-breakout      |  -1.94% |  +6.75% |  8.69 | **yes** |
| A1-alpha-order    |  -4.85% | -13.54% |  8.69 | no |
| c08-generalist    |  -5.63% |  +2.72% |  8.35 | **yes** |
| A2-cash-headroom  |  -9.25% | -16.78% |  7.53 | no |
| c05-trend         |  -2.46% |  +4.46% |  6.92 | **yes** |
| c09-convex        |  -1.22% |  +3.75% |  4.98 | **yes** |
| c03-breakout      |  -6.03% |  -1.35% |  4.68 | no |
| c07-chop          |  +6.00% |  +1.93% |  4.07 | no |
| c04-riskmanaged   |  -3.96% |  -0.20% |  3.77 | no |
| c02-volatility    |  -3.76% |  -0.35% |  3.41 | no |
| c01-meanrev       |  -2.19% |  -5.17% |  2.98 | no |

**6 of 15 cards (40%) flip sign** between the two windows carrying the same regime label, `c10-momentum`
being the sharpest labelled example the brief itself asks about (-6.90% against +2.62%, a 9.5-point
swing). A discipline -- or a card -- that reverses sign across two draws of its own supposed regime
has not demonstrated resistance to chop or vulnerability to it; it has demonstrated that this
particular pair of 260-session windows produced different price paths for its particular universe.
This is the empirical seed of §5's argument.

## 3. Were the analysts who feared chop right?

Five memos across both rounds name whipsaw or sideways chop explicitly as an expected failure mode
or, in one case, explicitly predict it will *not* be one. Scored against the actual two windows:

| analyst (round) | what was said | chop-2015 actual | chop-2011 actual | verdict |
|---|---|---:|---:|---|
| `c04-riskmanaged` (r1) | *"a sideways, choppy, low-trend market -- the filter whipsaws... producing a string of small losses"* -- named first in the matrix, before either chop window existed | -3.96% (this card's **actual worst window of all eight**) | -0.20% (mildly negative) | **hit** -- both negative, and chop-2015 really was its single worst result |
| `c06-13f-momentum` (r1) | *"a prolonged sideways chop in these names... producing a string of small losses through the stop"* | +11.53% (unranked, provenance-blocked, but one of this card's **best** results of the windows it can run) | not eligible | **miss** |
| `c08-generalist` (r2) | named `bull-2024` its worst, flagged `chop-2015` a *"close second"* at a design-window estimate of -5.00% | -5.63% (matches the estimate closely, and turned out to be the **actual worst window**, ahead of `bull-2024` at -3.59%) | +2.72% (positive; not named as feared) | **hit** on the specific fear stated |
| `c09-convex` (r2) | predicted `chop-2015` a modest real cost (~-1.09%, "premium... in ordinary windows") and explicitly excluded `chop-2011` from that bucket, arguing its 2011 flight-to-quality episode should make it a **win**, not a cost | -1.22% (matches -1.09% estimate closely) | +3.75% (matches its own +4.07% design-window estimate closely) | **hit, both halves** -- the most precise prediction in the set |
| `c07-chop` (r2) | purpose-built for chop; implicitly predicted it would **not** lose here, naming `covid` its actual feared window instead | +6.00% | +1.93% | **hit** -- both positive, and its actual worst window was covid (-15.57%) exactly as named |

Counting discrete window-level calls (c04 makes two implicit calls, one per window; c09 makes two
explicit calls; c06, c08 and c07 make one explicit call each toward the window they discuss): **7 of
8 discrete predictions were directionally correct (87.5%).** The one clean miss, `c06-13f-momentum`,
predicted chop would produce "a string of small losses" from repeated false starts and instead
produced this card's second-best result among the windows it can legally run -- though that number
carries the separate caveat that it is provenance-unranked.

The strongest pattern in this small sample: **analysts who reasoned about the specific mechanism of
their own entry rule against chop (`c09-convex`, `c07-chop`) scored better than the one who reasoned
about chop as a generic label** (`c06-13f-momentum`, whose entry is a 20-day price cross that the
memo itself worried would fire on noise -- a reasonable mechanism-level worry that the actual
12-name mega-cap/semis universe simply did not experience in this specific 260-session draw).

## 4. The A-family: a concentrated semiconductor rotation book

`A-rotation`, `A1-alpha-order`, `A2-cash-headroom`, `A3-no-target` and `A4-tight-stop` all trade the
same nine-symbol universe (`MU INTC AMD TSM SOXX NVDA AVGO QCOM MRVL`) with the same pairs-rotation
discipline, varying only bracket, sizing or fill order. Their adjusted excess:

| window | range across the 5 variants |
|---|---|
| `chop-2015` | -4.85% to -9.25% (`A3-no-target` a +3.70% outlier -- see below) |
| `q4-2018`   | -8.46% to -11.55% |
| `chop-2011` | -13.54% to -19.10% |
| `recent`    | **+58.09% to +149.49%** |

Roughly -7% to -9% adjusted excess in `chop-2015`, -8.5% to -11.6% in `q4-2018`, and materially worse
still in `chop-2011` -- the family's one uniformly bad discipline result from §2 -- set beside
+58 to +149 points in `recent`, the single largest adjusted-excess figures anywhere in this dataset.
`A3-no-target`'s `chop-2015` result (+3.70%, the family's only positive print in that window) is not
a contradiction: its take-profit-free exit let a single NVDA position that entered 2015-08-28 run to
+35.05% by 2016-01-07, an outsized single trade the other four variants' profit-taking rules would
likely have capped -- a design difference, not evidence the discipline handles chop.

**What the pair implies.** This is a concentrated single-theme book (nine names, one sector, mostly
the same 2020s AI/semiconductor demand story) riding an extraordinary, still-live secular re-rating
in the trailing twelve months. The `recent` numbers are real trades against a real +20.62% benchmark,
not a modelling artifact -- but they are also the one window in the matrix that overlaps the theme's
own live, ongoing boom, and the family loses in every other regime type tested here except a
narrow positive pocket in the family's absolute best q4-2018 print (none: all five are negative
there too). A book whose entire positive case rests on one still-running secular trend, and that
loses money in a sharp selloff, a grinding bear, and **both** sideways windows, is a bet on that
trend continuing, not a demonstrated all-weather edge. The size of the `recent` number should not be
read as evidence against that -- if anything, a book this concentrated producing +58 to +149 points
in the one window that overlaps its own thesis, and double-digit losses everywhere else including a
uniform sweep of both chop windows, is close to the textbook definition of a concentrated,
regime-dependent bet rather than a diversified edge.

## 5. Is chop a distinct regime, or a slow-entry penalty?

This is the question worth answering honestly even where the honest answer is uncomfortable, and the
data points toward the uncomfortable one.

**First, the "slow entry" hypothesis does not hold up cleanly on its own.** If chop simply punished
slow trend-confirmation entries (`sma(100)`/`sma(200)` filters) and rewarded fast mean-reversion or
momentum entries, the discipline table in §2 should split along exactly that line. It does not:
`B-momentum`'s family (a fast momentum entry) posted the single best `chop-2015` results in the
entire field (+24.60%), while `A-rotation`'s family (an equally fast `rsi(14)`-based entry, same
universe class) posted some of the worst (-7.16% to -9.25%, and uniformly worse still in
`chop-2011`). Two "slow" trend cards (`C-trend`, `H-trend-diversified`) won `chop-2015` comfortably;
two others (`c05-trend`, `c08-generalist`) lost it. Entry speed is not the variable doing the work.

**Second, and more tellingly: the two windows sharing the "chop" label do not agree with each other
as strongly as each agrees with a *different*, already-tested regime.** Computing the cross-card
correlation of adjusted excess between window pairs (Spearman rank correlation, over every card
eligible for both windows in the pair):

| window pair | n cards | Spearman ρ |
|---|---:|---:|
| `chop-2015` vs `chop-2011` | 15 | **0.461** |
| `chop-2015` vs `covid`     | 23 | **0.610** |
| `chop-2011` vs `bear-2022` | 15 | **0.732** |
| `chop-2011` vs `bull-2024` | 15 | -0.521 |
| `chop-2015` vs `bear-2022` | 23 | 0.042 |
| `chop-2015` vs `bull-2024` | 23 | 0.347 |
| `chop-2015` vs `q4-2018`   | 23 | 0.066 |
| `chop-2015` vs `recent`    | 23 | -0.085 |
| `chop-2011` vs `gfc`       | 10 | 0.455 |

`chop-2015` correlates with `covid` (ρ = 0.610) more strongly than with its own sibling `chop-2011`
(ρ = 0.461). `chop-2011` correlates with `bear-2022` (ρ = 0.732) far more strongly than `chop-2015`
correlates with `chop-2011`. In plain terms: **which cards do well in `chop-2011` is better
predicted by which cards do well in the grinding 2022 bear than by which cards do well in the other
sideways window.** If "directionless" were a coherent, distinct axis that the matrix newly captured,
the two windows built to represent it should agree with each other more than either agrees with an
unrelated regime. Here the opposite is true for `chop-2011`, and only marginally true for
`chop-2015`.

**Third, a card built specifically to trade chop measured its own edge as larger elsewhere.**
`c07-chop`'s memo reports average trade return of +2.83% in `bear-2022` and +3.82% in `bull-2024`,
against +2.42% in `chop-2015` and +0.93% in `chop-2011` -- its mean-reversion edge is *not* largest
in either window it was built for. Its own report (`reports/c07-chop.md` §4) confirms this survives
translation to adjusted excess too: `bear-2022` (+12.00%) more than doubles `chop-2015` (+6.00%) and
is six times `chop-2011` (+1.93%). The card that exists because of the chop mandate found its best
regime was a grinding bear, not either sideways window.

**Conclusion.** The two chop windows do not behave as one coherent "directionless" regime axis
sitting apart from the other six. `chop-2011` in particular looks substantially like a re-measurement
of grinding-bear sensitivity that `bear-2022` already tests (ρ = 0.732, the strongest cross-window
correlation found anywhere in this analysis apart from a window against itself); `chop-2015` sits
closer to `covid`-type sensitivity than to its own sibling. Combined with the 40% sign-flip rate in
§2 and the absence of any clean entry-speed split, the more defensible reading is that **round 2's
"directionless" label mostly re-packaged variance the matrix already had, under a name that implies
more novelty than the correlation structure supports** -- not that whipsaw is a fiction (the
pairs-rotation family in §4 shows a real, repeatable discipline-level failure across both windows),
but that treating `chop-2015` and `chop-2011` as two independent samples of the same new regime
overstates what they add on top of `bear-2022`, `covid` and the rest of the existing matrix. A future
round's marginal value would come less from adding a third chop window than from asking why
`chop-2011` and `bear-2022` measure the same thing under different names.

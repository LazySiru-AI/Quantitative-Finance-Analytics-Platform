# Round 6 — selection: four cards for the paper desk

**Not investment advice.** These are simulated books on a paper account, selected to be informative
to watch. I am not a licensed financial adviser and nothing here is a recommendation about real
capital.

Round 6 is a selection round. It reads rounds 2, 4 and 5 plus the live paper desk, and picks four
cards to run forward. The rule was pre-registered in `strategy-program/ROUND-6-PLAN.md`; §6 of that
file records the two amendments made before this execution and why.

---

## The result

| slot | card | why it won |
|---|---|---|
| core | **`B-momentum`** | best worst-rank across three matrices (3 / 2 / 2); positive at 5y and 10y against **both** benchmarks |
| second engine | **`A-rotation`** | passes both gates; ρ = +0.497 to the core, the lowest of any other Gate-A survivor |
| diversifier | **`c07-chop`** | ρ = +0.169 to the core and **−0.283** to `A-rotation` — the least correlated card in the field |
| declared hedge | **`c14-riskmanaged-wide`** | the only hedge candidate clearing both the correlation cap and the exposure floor |

**Dropped from the current desk: `C-trend`.**

**If one card is wanted as a single reference, it is `B-momentum`** — see §5, including how much smaller
its edge is than four rounds of leaderboards implied.

---

## 1. Gate A — must earn its keep at long horizon, against both benchmarks

The desk holds forward indefinitely, so the criterion is the **5-year and 10-year rungs**, not the
short windows rounds 1–4 were scored on. Round 5 showed the field's best annualized figure falls from
+31.6% at one year to +7.6% at ten; a card selected on a 1-year number is selected on the rung where
the noise is largest.

A card must post a **positive median annualized adjusted excess at both 5y and 10y against both SPY
and QQQ.** The QQQ requirement is round 5 §3's finding made binding: these are AI and semiconductor
books, and beating a broad-market index while losing to the index that holds the same kind of company
is not an edge.

| card | 5y SPY | 5y QQQ | 10y SPY | 10y QQQ | |
|---|---|---|---|---|---|
| `B-momentum` | +14.79% | **+9.29%** | +7.59% | **+3.92%** | pass |
| `B4-tight-stop` | +15.04% | +7.79% | +7.14% | +3.51% | pass |
| `B2-hold-90` | +12.98% | +8.39% | +7.56% | +4.60% | pass |
| `A-rotation` | +10.40% | +3.39% | +5.28% | **+0.63%** | pass |
| `B3-concentrated` | +8.25% | +7.33% | +5.78% | +1.90% | pass |
| `C-trend` | +7.42% | +2.53% | +4.46% | +1.28% | pass |
| `H-trend-diversified` | +4.86% | +1.89% | +3.35% | +1.32% | pass |
| `c07-chop` | +3.27% | +2.65% | +0.85% | +0.27% | pass |
| `c19-volatility` | +2.84% | +1.87% | −1.75% | −2.56% | **fail** |
| `c09-convex` | −0.50% | −1.38% | −0.46% | −0.98% | fail |
| `c18-meanrev` | −1.04% | −2.65% | −0.88% | −1.77% | fail |
| `c21-uncorrelated` | −2.41% | −4.15% | −1.40% | −3.09% | fail |
| `c14-riskmanaged-wide` | −2.79% | −5.35% | −1.78% | −3.25% | fail |
| `c11-breakout` | −4.01% | −7.28% | −2.39% | −4.90% | fail |
| `c20-rotation` | −4.31% | −7.14% | −3.77% | −6.12% | fail |

Eight survivors. The hedge slot is **exempt** from Gate A by design — a hedge is expected to lose in a
rising market, and the ladder is 19-of-21 rising.

## 2. Gate B — no two cards on the desk above ρ = +0.70

This is the amendment the live desk forced. The current roster runs `B-momentum` **and** `C-trend`,
and across matrices they correlate at **ρ = +0.909**. They are two versions of one trade, and the
live account shows exactly that: −5.21% and −7.24% over the same 55 sessions, both holding NVDA, AVGO
and TSM into the same rotation.

Correlation is taken as the **maximum** across round 4's matrix, round 5's ladder and round 5's bear
arm — the worst figure, not the friendliest, because round 4 proved a correlation from one matrix is
not a property of the pair.

Among Gate A's eight, nearly every pair is over the cap. The exceptions:

| pair | max ρ |
|---|---|
| `B-momentum` / `c07-chop` | **+0.169** |
| `B-momentum` / `A-rotation` | **+0.497** |
| `A-rotation` / `c07-chop` | **−0.283** |
| `B2-hold-90` / `H-trend-diversified` | +0.672 |

`{B-momentum, A-rotation, c07-chop}` is the largest mutually-under-cap set drawn from Gate A, and it
contains the Gate-A leader. That fixes it.

Rule 4.5 (one card per base family) removes `B2`, `B3`, `B4` once `B-momentum` is seated — and round
5 §2.2 makes that moot anyway: the three variants sit within **0.45 points of each other at ten
years**, so the choice among them is unmeasurable at the desk's horizon.

## 3. The hedge slot, and the card the rule excluded

Hedge candidates, ranked by **swing** — bear-arm median minus ladder median, the cleanest evidence a
card actually behaves differently when the market falls:

| card | swing | max ρ to core | bear exposure | bear trades | verdict |
|---|---|---|---|---|---|
| `c20-rotation` | **+14.79 pts** | **+0.917** | 36.95% | 116 | **excluded — over cap** |
| `c18-meanrev` | +4.86 | +0.918 | 13.11% | 258 | excluded — over cap |
| **`c14-riskmanaged-wide`** | **+4.78** | **+0.599** | 20.06% | 52 | **selected** |
| `c11-breakout` | +4.38 | +0.826 | 28.14% | 25 | excluded — over cap |
| `c21-uncorrelated` | +3.72 | +0.907 | 22.16% | 56 | excluded — over cap |
| `c09-convex` | +2.79 | +0.905 | 7.70% | 42 | excluded — over cap |
| `c19-volatility` | −9.04 | +0.984 | 18.38% | 112 | excluded — wrong sign |

**`c20-rotation` has by far the strongest hedge signature in the programme** — last of fifteen at
every ladder horizon and first in the bear arm, a +14.8-point swing, three times the next card's. It
is excluded on a single number: ρ = +0.917 to `B-momentum` on round 4's six-window matrix, computed
on raw per-window returns.

That number is suspect for the exact reason round 5 documented — raw correlation across windows of
differing length mostly measures scale, and on the annualized bear arm the same pair reads **−0.591**.
The rule takes the maximum, so it excludes the card.

**I applied the rule rather than rewriting it.** `ROUND-6-PLAN.md`'s opening paragraph says a
selection rule edited after seeing what it selects is not a rule, and this is the case it was written
for. `c20-rotation` is flagged for round 7 as the leading candidate to replace `c14` if the
correlation cap is re-specified on annualized figures only.

## 4. The book check

Equal-weight, every matrix, against the incumbent roster and against the best single card:

| matrix | selected worst | median | incumbent worst | median | `B-momentum` alone worst | median |
|---|---|---|---|---|---|---|
| r2 (8 regime windows) | −5.14% | +2.22% | −3.66% | +5.47% | −5.15% | +12.16% |
| r4 (6 regime windows) | −4.85% | +1.32% | −6.59% | +1.06% | **+0.04%** | +5.82% |
| r5 ladder (21 windows) | −5.09% | **+6.06%** | −5.21% | +4.11% | −15.54% | +10.17% |
| r5 bear (6 windows) | −5.75% | +0.78% | −5.94% | +2.19% | −10.64% | +5.59% |

**Veto count: 1** — the book's worst window is worse than `B-momentum` alone only on r4, and the veto
fires at more than one. **The selection stands.**

The book beats the incumbent roster on worst-window in three of four matrices and on ladder median.
It gives up a great deal of median against holding `B-momentum` alone (+6.06% vs +10.17% on the
ladder) in exchange for cutting the worst window by a third to two-thirds. That is the trade a
four-card desk *is*, and it should not be reported as free.

## 5. If one card is wanted: `B-momentum`

| | |
|---|---|
| rank on r2 / r4 / r5-ladder | 3 / 2 / 2 — **best worst-rank in the field** |
| 5-year annualized adjusted excess | +14.79% vs SPY, **+9.29% vs QQQ** |
| 10-year | +7.59% vs SPY, **+3.92% vs QQQ** |
| mean capital exposure | 41.87% |
| live, 55 sessions from 2026-06-01 | **−5.21%** |

It is the only card that is never worse than third on any matrix, and one of two that stay positive
at ten years against a Nasdaq-100 hurdle. Every one of the following is also true:

- **The honest expectation is roughly +4% a year over QQQ, not the +14.8% the 5-year SPY figure
  shows.** Round 5's two corrections — annualize, and use the benchmark that holds the same kind of
  company — cut the headline by more than two thirds each time they were applied.
- **Its universe was chosen in 2026 and run from 2013.** NVDA, AVGO, TSM, MSFT. The programme's
  survivorship gate does not fire on thesis-picked baskets, only mechanically index-derived ones, and
  over a decade that distinction is much weaker than it looks. The long-rung figures are upper bounds.
- **The only out-of-sample evidence available runs against it.** See §6.

## 6. The live desk, which is the only out-of-sample evidence and contradicts everything above

The paper desk is the **only** evidence in this programme from after the 2026-02-13 design cutoff.
Ten cards were run over the same 55 sessions, 2026-06-01 to 2026-08-18, during which SPY returned
**+1.17%** and QQQ **−3.40%**:

| card | live | trades | holdings now | r5 ladder rank | r5 5y+10y rank |
|---|---|---|---|---|---|
| `c18-meanrev` | **+2.44%** | 19 | CL, MMM | 8 | 8 |
| `c09-convex` | +0.16% | 1 | GLD | 7 | 6 |
| `c07-chop` | 0.00% | **0** | *all cash* | 5 | 5 |
| `c14-riskmanaged-wide` | 0.00% | **0** | *all cash* | 9 | 9 |
| `c19-volatility` | −0.14% | 1 | *all cash* | 6 | 7 |
| `H-trend-diversified` | −2.25% | 2 | DBC, NVDA, GDX | 4 | 4 |
| `B-momentum` | −5.21% | 2 | MSFT, AMZN, NVDA, AVGO, TSM | **2** | **1** |
| `c20-rotation` | −5.96% | 21 | XLV, XLP, DBC | 10 | 10 |
| `C-trend` | −7.24% | 2 | NVDA, AVGO, TSM, SOXX | 3 | 3 |
| `A-rotation` | **−12.77%** | 10 | NVDA, AVGO, TSM (99%) | **1** | 2 |

**Spearman rank correlation between round 5's ladder ranking and the live ranking: −0.539.**
Against the 5y+10y rungs specifically: **−0.467**. Both negative. The backtests ordered this field
roughly *backwards* over the only period no analyst could have studied.

The card that won round 5's 6-month and 1-year rungs by a wide margin, `A-rotation`, is **last live at
−12.77%**. The card that finished 8th of 10 on the ladder, `c18-meanrev`, is the **only one making
money**.

**This does not overturn the backtests, and it must not be read as doing so.** It is 55 sessions,
n = 10, and one rotation out of semiconductors drives most of it — AVGO −17.4%, SOXX −7.1%, TSM
−5.1% while SPY rose. A single regime can invert any ranking, which is round 4's finding restated.
What it does establish is that **nothing in rounds 1–5 has yet been confirmed forward**, and the
first 55 sessions of trying went the wrong way.

### 6.1 Two selected cards do not trade at all

`c07-chop` and `c14-riskmanaged-wide` have taken **zero trades in 55 live sessions** and hold 100%
cash. Both cleared round 6's exposure floor on the *historical* bear arm (12.65% and 20.06% mean
exposure; 87 and 52 trades). Round 4 diagnosed `c14`'s mechanism: its entries need `close > sma(150)`
on TLT / IEF / GLD / LQD, which fired on TLT in 4 of 56 sessions and on nothing else.

**This is a defect in this round's rule, and it is recorded rather than patched:** the exposure floor
is measured on historical windows, and a card can clear it while being inert in the regime it is
about to be run in. On this evidence the selected desk runs two active cards and two cash
placeholders.

### 6.2 The correlation cap missed a holdings overlap

Gate B cleared `B-momentum` and `A-rotation` at ρ = +0.497 — comfortably under the +0.70 cap. Live,
`A-rotation` holds **NVDA, AVGO and TSM at 99% of its book**, and those three names are 44.6% of
`B-momentum`'s. The two cards the rule seated as decorrelated are, right now, largely the same bet.

Gate B correlates per-window *returns*. It never looks at *holdings*. Two books can hold identical
names and still show a modest return correlation across historical windows if their entry timing
differs — and then converge completely in a regime where both are fully invested in the same trade.

### 6.3 Pre-registered for round 7

Written now, before round 7 has any data, so it is a rule and not a description:

1. **A liveness gate.** A desk card must be shown to have traded in the 60 sessions before selection.
   `c07-chop`, `c14-riskmanaged-wide` and `c19-volatility` fail it today.
2. **A holdings-overlap cap**, alongside the return-correlation cap. No two desk cards may share more
   than 25% of book weight in the same symbols at selection time.
3. **Re-specify the correlation cap on annualized figures only.** `c20-rotation` was excluded on a
   raw round-4 correlation of +0.917 where the annualized bear-arm figure for the same pair is
   **−0.591**; round 5 §5 gives specific reason to distrust the former.
4. **Score the live desk as its own matrix** once it has ~250 sessions, and weight it above any
   backtest matrix, because it is the only one that is out of sample.

## 7. What this selection is not evidence of

- **Not out-of-sample.** Every matrix it reads ends on or before 2026-02-13. The desk is what turns
  this into a forward test, and that test is 55 sessions old and currently negative.
- **A robust rule on thin evidence is still thin.** Four cards from fifteen, on four matrices drawn
  from one era, with a ten-year rung that is effectively one sample.
- **The desk's result will be one path.** However these four perform, that is one realisation, not a
  distribution. This sentence exists to be quoted back when someone reads it as a verdict.
- **Nothing here is a claim about what anyone should own.**

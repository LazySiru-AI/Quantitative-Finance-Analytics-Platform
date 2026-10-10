# Round 27 — the last three thesis claims, measured as the theses state them

Pre-registered 2026-08-30, before any measurement in this round exists. **Not investment advice.**

---

## 1. What remains, and why none of it needs a backtest

Round 26 measured four of the seated cards' claims and established one as unaskable on the regime
matrix. `00-EVERYTHING-TESTED.md` recommendation 9 names what is left. Read literally, **every one of
them is a statistic about bars and signals, not about a book** — so each is measured directly, the way
its thesis states it, rather than inferred from a card's return.

That is the point of this round's design: a backtest of these claims would answer a *different*
question and let a portfolio effect stand in for the claim. Measuring the stated statistic is both
cheaper and more faithful.

| claim | card | stated as |
|---|---|---|
| pairwise correlation | `A-rotation` | "mean 0.589, range 0.286 (INTC vs AVGO) to 0.824 (SOXX vs TSM)" |
| move duration | `B3-concentrated` / `B-momentum` | "median duration of roughly 3-4 weeks … past two months at the 75th percentile (NVDA 256 sessions, MSFT 169, TSM 189)" |
| the excluded names | `C-trend` | five names "produced negative average 60-day forward returns after the signal fired" |

**Round 26 declared the third unaskable, and this round does not overturn that** — it answers a
different question. Round 26 asked whether *a card holding those names* underperforms on the regime
matrix, which their 2022 start dates make unanswerable. This asks the statistic the thesis actually
cites, which needs only the names' own history. The unaskable finding stands for the backtest form.

## 2. Definitions, fixed before any number exists

Each is pinned here because a measurement of this kind is decided by its definition, and three
independent measurements of "move duration" would otherwise produce three different answers.

### 2a. Pairwise correlation (`A-rotation`)

Pearson correlation of **daily simple returns**, computed pairwise across the nine names
(`MU INTC AMD TSM SOXX NVDA AVGO QCOM MRVL`), within each of `R2_MATRIX`'s eight windows, on sessions
where both names have bars. Report **mean, min and max** of the 36 pairs per window, and name the
min and max pair. The thesis's figures come from "the trailing ~253 sessions through 2026-02-13".

### 2b. Move duration (`B3-concentrated` / `B-momentum`)

A **signal** is a session where `close > sma(200)` and `ema(20)` crosses above `ema(50)` — the card's
own entry, unchanged. The **move** runs from that session until `ema(20)` crosses back below
`ema(50)`, which is `C-trend`'s exit and the natural reading of "the resulting move"; a move still
open at the last bar is recorded as **censored** and excluded from the median rather than truncated,
because truncating it would bias the statistic downward exactly where the thesis's claim is strongest.

Measured over the twelve names of the shared universe
(`NVDA AMD AVGO MU MRVL TSM META MSFT GOOGL NOW AMZN NFLX`). Report median and 75th percentile in
**sessions**, the per-name maximum, and the count of censored moves.

**Reference points, so the verdict is not a judgment call:** "roughly 3-4 weeks" is **15–20 sessions**
and "past two months" is **≥42 sessions**. The thesis's named maxima are NVDA 256, MSFT 169, TSM 189.

**This is a re-measurement on a wider sample, not an out-of-sample test, and must be reported as
such.** The thesis says "on the design-window history of these 12 names", and most available history
predates `DESIGN_THROUGH` (2026-02-13). Sessions after that cutoff are reported separately, but six
months yields few completed moves and no verdict will be claimed from that split alone.

### 2c. The excluded names' forward returns (`C-trend`)

A **signal** is a session where `C-trend`'s entry fires — `close > sma(200)` and `ema(20)` crosses
above `ema(50)`. The **forward return** is `close[t+60] / close[t] − 1`, in **sessions**, not calendar
days; signals with fewer than 60 subsequent bars are dropped and counted.

Measured on the five excluded names (`IREN OKLO APLD BE KORU`) **and on C-trend's nine included names
as a control**, because "these names do not sustain the signal" is a comparative claim and a bare
negative mean on five names would not establish it. Report mean, median and count per name, and the
pooled figure for each group.

## 3. Falsifiable predictions

1. **Correlation is *higher* out of sample than the thesis's 0.589**, in at least 5 of 8 windows.
   The thesis measured a trailing year that included a semiconductor drawdown; correlation among
   same-sector names rises in stress, and five of the eight windows are stressed regimes.
2. **The move-duration median is below the thesis's 15–20 session band.** Round 26 measured
   `C-trend`'s winners at a median 82 sessions and losers at 12, against claimed 118 and 16 — every
   duration figure in that family has come in below its claim so far.
3. **The 75th percentile clears 42 sessions**, as the thesis says. Predicting 2 and 3 together is
   deliberate: a right-skewed distribution can miss on the median and hold at the tail, and that
   combination is what "the edge is concentrated in a minority of large winners" would look like if
   it were true.
4. **The five excluded names' pooled mean 60-session forward return is negative**, as the thesis
   claims. This is the round's one prediction that the card's author would make.
5. **But the nine included names' pooled mean is not materially higher** — the gap between the two
   groups is under 10 percentage points. If the exclusion were doing real work the gap should be
   large; the honest prior on this programme's record is that it is not.

## 4. What this round cannot settle

- **Nothing about the cards' returns.** These are signal statistics. A claim surviving here does not
  make its card good, and a claim failing here does not make its card bad.
- **2b is not an out-of-sample test** (§2b), and no verdict will be drawn from the post-cutoff split.
- **2c does not overturn round 26's "unaskable"** (§1) — it answers the stated statistic, not the
  backtest question.
- **Nothing is promotable, and nothing here demotes a card.** The trading purpose has no promotion
  rule.

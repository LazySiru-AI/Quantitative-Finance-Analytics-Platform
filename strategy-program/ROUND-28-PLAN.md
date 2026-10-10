# Round 28 — is there any cross-sectional information to exploit at all?

Pre-registered 2026-08-30, before any measurement in this round exists. **Not investment advice.**

This is the first round of a new line: **cross-symbol constructions**, the class the card engine
forecloses (`00-EVERYTHING-TESTED.md` §3a). It is deliberately an *analysis*, not a build.

---

## 1. Why this is the right first question, and why it comes before any engine change

The report's §3a records that the engine cannot express relative strength, pairs, dispersion,
inverse-vol parity or any cross-symbol overlay — "a rule is evaluated per symbol against that symbol's
own bars." Building that capability is a real engine change. Recommendation 10 named it as one of the
two honest paths forward.

**But every one of those blocked strategies depends on the same precondition: that a name's past
cross-sectional rank carries information about its future cross-sectional rank.** If it does not, the
engine change would unlock a class that has nothing in it, and the build is wasted. If it does, the
build is justified *and this round names which signal justifies it*. So the measurement comes first.

**There is one prior data point, and it is discouraging.** The Discovery module measured exactly this
kind of ranking skill — `mom12_1`, `mom6`, `trend` keys, top-3 selection — and got IC = −0.0073
(bootstrap p = 0.892), zero of six discoveries after Benjamini-Hochberg. **But it ran on ETF
sector/theme baskets, on annual and monthly rebalance dates, never on single-name equities.** This
round closes that gap: the same question, on the single-name equity universes the seated cards
actually trade, across five signals and two horizons, measured directly as a rank information
coefficient — no card, no engine, no backtest.

## 2. A caveat that is load-bearing, stated before any number

Round 27 measured the nine-semiconductor universe's pairwise daily-return correlation at **0.46–0.83**,
mean above 0.59 in six of eight regimes. **A highly correlated universe has little cross-sectional
dispersion to exploit** — when names move together, their relative ranking is mostly noise. So these
universes are, a priori, close to the *worst* case for cross-sectional selection.

That cuts a specific way. **A null here does not kill cross-sectional strategies in general** — only on
these concentrated universes. But those are the universes the seated cards trade, so a null is still
decision-relevant: it says the engine change is not justified *for the book that exists*. A broader,
less-correlated universe is a distinct question and a candidate for the next round, not this one.

## 3. The measurement

### 3a. Universes (balanced panels, from the common start date)

- **U12** — the twelve `B3-concentrated` / `B-momentum` names
  (`NVDA AMD AVGO MU MRVL TSM META MSFT GOOGL NOW AMZN NFLX`), from **2012-06-28** (NOW's first bar),
  the earliest date all twelve have bars. ~14 years.
- **U9** — the nine `A-rotation` / `C-trend` semiconductor names
  (`MU INTC AMD TSM SOXX NVDA AVGO QCOM MRVL`), from **2009-08-05** (AVGO's first bar). ~17 years.

### 3b. Signals (cross-sectional, ranked across the universe at each rebalance date `t`)

Five, chosen to span the standard cross-sectional effects, fixed before any result:

| signal | definition | expected sign of IC |
|---|---|---|
| `mom_12_1` | `close[t−21] / close[t−252] − 1` (12-month, skip last month) | + (momentum) |
| `mom_6` | `close[t] / close[t−126] − 1` | + (momentum) |
| `vol_60` | stdev of daily returns over the last 60 sessions | **−** (low-vol anomaly) |
| `reversal_1m` | `close[t] / close[t−21] − 1` | **−** (short-term reversal) |
| `dist_sma200` | `close[t] / sma(200)[t] − 1` | + (trend) |

`sma` is the engine's own indicator (`app.indicators.registry`), not hand-rolled.

### 3c. Forward return, de-meaned

At each rebalance date `t`, the forward return of name `i` is `close[i, t+h] / close[i, t] − 1`, then
**cross-sectionally de-meaned** by subtracting that date's universe-mean forward return. This isolates
*relative* performance — the only thing a cross-symbol strategy can capture — and removes the market
beta every name shares.

### 3d. Rank information coefficient

For each `(universe, signal, horizon)` cell: at each rebalance date, the **Spearman rank correlation**
between the signal's cross-sectional ranks and the de-meaned forward returns' ranks. The cell's IC is
the **mean across rebalance dates**. Rebalance every **21 sessions** (monthly, non-overlapping enough
to blunt autocorrelation). Horizons `h ∈ {21, 63}` sessions.

### 3e. Significance, corrected

Per cell, a **stationary block bootstrap over rebalance dates** (block = 12 months = 12 rebalances,
2000 resamples) gives a two-sided p-value for `mean IC = 0` — the same construction Discovery used.
Then **Benjamini-Hochberg** across all **20 cells** (2 universes × 5 signals × 2 horizons), because
twenty comparisons need twenty-comparison arithmetic. A cell "survives" at **q < 0.10**.

## 4. Falsifiable predictions

1. **Momentum ICs (`mom_12_1`, `mom_6`) are indistinguishable from zero**, as Discovery found on ETFs.
   Single names will not rescue what the sector baskets could not show.
2. **`vol_60` has the largest mean `|IC|` of the five signals.** The low-volatility anomaly is the most
   robust cross-sectional effect in the literature, so if anything here carries information it is this.
3. **`reversal_1m`'s IC is negative at `h = 21`** — high last-month return predicts low forward
   relative return. A sign prediction, not a magnitude one.
4. **Zero cells survive Benjamini-Hochberg at q < 0.10.** The honest prior, given both Discovery's null
   and §2's correlation caveat. This is the round's central claim.
5. **Mean `|IC|` is higher on U12 than on U9.** U9 is more homogeneous (all semiconductors, the
   higher-correlation universe of round 27), so it has less genuine relative structure to rank. If
   this is wrong — if the tighter universe ranks better — that is itself informative about where any
   cross-sectional edge would live.

## 5. The decision rule, fixed here

- **If zero cells survive (prediction 4 holds):** cross-sectional rank carries no measurable
  information on the seated universes. The blocked engine change is **not justified by measured edge**
  for the book that exists, and recommendation 10's "author a genuinely new hypothesis" should turn to
  a *different* input (a non-curve macro series, or a less-correlated universe) rather than to building
  cross-symbol machinery for these names. Stated as the round's recommendation.
- **If any cell survives:** that specific signal carries cross-sectional information the per-symbol
  engine cannot exploit. The engine change is justified **for that signal**, and the next round
  pre-registers building and testing it. Name the signal, the universe and the horizon.

A surviving cell is a licence to build, not a strategy: the IC is a ranking statistic, not a return,
and would still have to survive costs, capacity and the 21.2pp floor as an actual book.

## 6. What this round cannot settle

- **Only these two universes**, and both are concentrated (§2). A null does not generalise to
  broad-market cross-sectional selection.
- **Rank IC, not return.** A non-zero IC is a precondition for a cross-symbol edge, not proof of one.
- **Five signals, two horizons, monthly rebalance.** A different signal, horizon or frequency is
  untouched.
- **Nothing is promotable, and nothing here is a card.**

---

## 7. Amendment 1 — the h=63 cells overlap, and overlap inflates significance

**Recorded 2026-08-30, after the pre-registered run (§3-5) produced exactly one survivor — `U9
reversal_1m h=63`, IC +0.085, q=0.010 — and before the re-measurement below. No verdict already
stated is withdrawn by fiat; it is re-measured.**

The survivor was stress-tested three ways before this amendment was written:

| test | mean IC | bootstrap p |
|---|---:|---:|
| as run (rebalance 21, h 63) | +0.0846 | 0.0002 |
| different seed / block (6, 24) | +0.0846 | 0.0002–0.0010 |
| phase-shifted +10 sessions | +0.0640 | 0.0135 |
| **non-overlapping (rebalance 63, h 63)** | **+0.0174** | **0.686** |

**The p-value is robust to the bootstrap's own parameters and fragile to the window construction.**
With h=63 and a 21-session rebalance, consecutive cross-sections share 42 of 63 forward-window
sessions, so the per-date IC series carries a moving-average autocorrelation the block bootstrap does
not fully remove — the effective sample is ~n/3, not n. Rebalancing every 63 sessions so no two
forward windows overlap leaves 68 genuinely independent cross-sections, and the effect vanishes
(+0.017, p=0.69). **The survivor is an artifact of overlapping windows in this round's own design.**

**The correction, and why it is not outcome-selection.** It re-measures **every** h=63 cell — both
universes, all five signals — at a 63-session rebalance so forward windows never overlap, not just the
one cell that survived. The h=21 cells are already overlap-free (horizon equals rebalance) and are
unchanged. The direction is committed in advance and can only reduce significance: a non-overlapping
sample is smaller and its bootstrap cannot manufacture the autocorrelation that inflated the survivor.
This is the same class of symmetric methodological fix as round 23's Amendment 3, applied before the
re-run rather than chosen from its result.

**Expected outcome, stated before the re-run:** the survivor falls inside, and **zero cells survive
Benjamini-Hochberg at q < 0.10** across the corrected set — prediction 4, as originally written. If a
cell still survives the non-overlapping test, that is a real finding and §5's build-licence rule
applies to it; the expectation is that none does.

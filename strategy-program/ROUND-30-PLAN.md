# Round 30 — do the untouched macro series carry forward-return information that price does not?

Pre-registered 2026-08-30, before any measurement in this round exists. **Not investment advice.**

This opens a new line: **non-price inputs** (`00-EVERYTHING-TESTED.md` recommendation 11). The
cross-symbol line closed in rounds 28-29 — its one survivor was the beta premium, not an alpha. The
remaining genuinely-new frontier is the macro series the desk can read but has never used. Like rounds
28-29 this is deliberately an *analysis*, not a build.

---

## 1. Why this question, and why it comes before any card

Seven FRED series are reachable through the `macro(SERIES)` DSL. **Exactly one has ever been tested:**
`T10Y2Y`, the 2s10s curve, as an entry gate (round 22), a sizing term (round 23) and a rate of change
(round 25) — null 3-of-3 each time. Six series have never been touched:

- **daily, directly expressible:** `DGS10` (10Y Treasury yield level, 1962-), `DCOILWTICO` (WTI crude
  oil, 1986-), `T10YIE` (10Y breakeven inflation, 2003-)
- **monthly, non-stationary (need the round-23/25 substitution trick):** `PCEPI`, `PCEPILFE`,
  `CPILFESL`

This round measures the **three daily series**. The monthly inflation indices are a distinct, more
expensive question (a level index is non-stationary and must be differenced via the in-process pin swap
rounds 23/25 use) and are deferred to a follow-up conditioned on this round's outcome.

**Unlike the cross-symbol line, the engine is not blocked here** — a `macro()` card is buildable today,
and rounds 21-25 built them. So the measure-before-build discipline is a *choice*, made because rounds
21-25 already show that building a macro card and backtesting it is how nulls get manufactured: the
honest first question is whether the series carries any forward-return information *at all*, measured as
a pure statistic, before a card is seated.

## 2. The load-bearing caveat: orthogonality to price, stated before any number

A macro series is only worth an engine input **if it carries information the price series does not
already contain.** Rates, oil and breakeven inflation all co-move contemporaneously with equities;
much of any raw "rates fell, market rose" spread is simply the price signal wearing a macro mask. A
signal that only works because it proxies trailing price momentum adds nothing a price-only card cannot
already do.

So every cell in this round is measured **twice**: once raw, and once after residualizing the target's
forward return on its own trailing price momentum. The gap between the two *is* the orthogonal
information content. This control is pre-registered for all cells, not applied selectively to survivors.

## 3. The measurement

### 3a. Series and causal state transforms

Each daily series is reduced to a binary **state** on each date `d`, by two transforms fixed before any
result. Both are causal — every term is on or before `d`.

| transform | definition | state |
|---|---|---|
| `level` | `sign( macro(d) - mean(macro over trailing 252 sessions) )` | +1 above trend / -1 below |
| `roc`   | `sign( macro(d) - macro(d - 20) )` | +1 rising / -1 falling |

These are the two shapes rounds 22-25 applied to the curve — level as a gate, 20-session change as a
rate of change (the same `LOOKBACK = 20`). Applying them to the three untouched series is the direct
extension. The macro value on `d` is the most recent released observation on or before `d` (the pin
carries release dates; no lookahead).

### 3b. Targets

- **SPY** (broad market, 1993-) — the general question.
- **QQQ** (growth / long-duration, 1999-) — should be *more* rate-sensitive than SPY if the rate
  hypothesis is real. The SPY-vs-QQQ contrast is itself a pre-registered prediction (§4.1).

### 3c. Horizons and sampling

Horizons **21 and 63 sessions**. Rebalance dates are sampled **non-overlapping at the horizon**
(`cal[::h]`) from the start — round 28's Amendment 1 baked in, so forward-return windows never overlap
and the block bootstrap is not fed autocorrelated returns.

### 3d. Grid and statistic

3 series x 2 transforms x 2 targets x 2 horizons = **24 cells.**

For each cell, over the non-overlapping rebalance dates with a valid state and a valid `h`-session
forward return:

- **spread** = `mean(fwd | state=+1) - mean(fwd | state=-1)` — the headline effect size.
- **significance:** define per-date `g(d) = state(d) * (fwd(d) - grand_mean_fwd)`; the sign of
  `mean(g)` matches the spread and `mean(g)=0` under "state carries no information." Test it with the
  **same stationary block bootstrap as rounds 28-29** (`_block_bootstrap_p`, `BLOCK` in rebalance-date
  units, 2000 resamples), which preserves the multi-year autocorrelation of macro regimes — a plain
  label shuffle would treat trending states as independent and overstate significance.
- **BH correction** across all 24 cells (`_benjamini_hochberg`); survivor threshold **q < 0.10**,
  identical to rounds 28-29.

### 3e. The orthogonality control (§2), run on every cell

Compute the target's trailing 12-1 momentum (`close[d-21]/close[d-252] - 1`) at each rebalance date,
bucket dates into terciles of it, subtract the within-tercile mean forward return to residualize, and
recompute both the spread and the bootstrap p on the **residualized** forward returns. Report raw and
price-residualized side by side.

## 4. Predictions (falsifiable, fixed before the run)

1. **`DGS10` `roc` (rising rates) gives a negative spread on QQQ, more negative than on SPY.** Growth
   is longer-duration; a rising discount rate should hurt it more. *Refuted if* the QQQ spread is
   non-negative, or not more negative than SPY's.
2. **The `DGS10` spreads shrink toward zero after price-residualization.** Rate and equity moves are
   contemporaneously correlated, so most raw spread should be the price signal in disguise. *Refuted
   if* the residualized spread keeps its sign and at least half its raw magnitude (which would be the
   exciting outcome — genuine orthogonal information).
3. **`DCOILWTICO` carries no clean equity sign; it has the smallest mean |spread| of the three
   series.** Oil's equity link is sector-mixed (hurts consumers, helps energy). *Refuted if* oil is the
   strongest series.
4. **Net survivors — cells that clear q < 0.10 AND keep sign + at least half their spread after
   residualization — is 0.** Twenty-nine rounds of nulls, and the curve (a cleaner macro-equity signal
   than the rate level) was null 3x. *Refuted by* any such surviving cell.

## 5. Decision rule (pre-registered)

- A cell that **clears BH q < 0.10 AND retains its sign and >= half its spread after
  price-residualization** is a macro signal carrying orthogonal forward-return information. Because the
  `macro()` DSL is not blocked, the response is to **pre-register a card round** testing it as a
  tradeable rule (gate or tilt), exactly as rounds 22-23 did for the curve.
- A cell that **clears BH but collapses under residualization** is a price signal wearing a macro mask
  — **no card**; a price-only rule already captures it.
- **Nothing surviving** -> the three daily untouched series carry no orthogonal forward-return
  information for equity indices, and the macro frontier narrows to the monthly inflation indices,
  which are a harder and lower-prior follow-up.

## 6. Determinism and honesty about scope

- `SEED = 30`, fixed; never the clock. All dates come from the pin and the bar store. Non-overlapping
  horizon sampling and the block bootstrap are in from the first run — round 28's overlap defect is
  designed out, not patched.
- **What this cannot settle:** the binary sign-split discards magnitude; only two transforms and two
  targets; the orthogonality control is one axis (12-1 momentum of the target), not all price
  information; equity-index targets, not the seated single names (QQQ stands in as the growth proxy);
  and daily series only — the monthly inflation indices are untested here.
- Rank/return statistic only. **No card, no engine, no backtest, nothing promotable.**

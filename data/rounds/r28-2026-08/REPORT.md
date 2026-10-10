# Round 28 — no cross-sectional edge on the seated universes, and an artifact caught on the way

Run 2026-08-30 against `ROUND-28-PLAN.md` (`bb4424d`), Amendment 1 at `f6209cd`, both committed before
the measurements they govern. **Not investment advice.** This is a rank-statistic analysis; no card, no
engine, no backtest, nothing promotable.

---

## 1. The question and the answer

Every cross-symbol strategy the engine forecloses — relative strength, pairs, inverse-vol parity —
needs one thing to be true first: a name's past cross-sectional rank must predict its future
cross-sectional rank. This measured that directly, as a rank information coefficient, across five
signals, two horizons and the two single-name equity universes the seated cards trade.

**Zero of twenty cells survive Benjamini-Hochberg at q < 0.10.** The lowest q anywhere is 0.215. On
these universes, cross-sectional rank carries no measurable information — the same answer the Discovery
module got on ETF baskets (IC −0.0073, q=0.186), now confirmed on single names.

## 2. The run produced one survivor, and it was an artifact of this round's own design

The pre-registered run (§3–5) returned exactly one survivor: **`U9 reversal_1m h=63`, IC +0.085,
q=0.010**, refuting prediction 4. A result that shape — one cell in twenty, refuting the honest prior —
is exactly the kind this programme's record says to distrust, so it was stress-tested before anything
was concluded:

| test | mean IC | bootstrap p |
|---|---:|---:|
| as run (rebalance 21, h 63) | +0.0846 | 0.0002 |
| bootstrap seed 99, blocks 6 and 24 | +0.0846 | 0.0002–0.0010 |
| rebalance phase shifted +10 sessions | +0.0640 | 0.0135 |
| **non-overlapping (rebalance 63, h 63)** | **+0.0174** | **0.686** |

**The p-value was robust to the bootstrap's own parameters and fragile to the window construction.**
With a 63-session horizon and a 21-session rebalance, consecutive cross-sections share 42 of 63
forward-window sessions; the resulting autocorrelation in the per-date IC series is not fully removed
by a block bootstrap, so the effective sample was ~n/3, not n. Removing the overlap — rebalancing every
63 sessions so no two forward windows share a session — left 68 independent cross-sections and the
effect vanished.

**This is the same failure shape as round 23's null point-mass:** a measurement construction that
manufactures significance, invisible until stressed. It was recorded as Amendment 1 *before* the
correction ran, with the expected outcome (the survivor falls inside, zero cells survive) committed in
advance.

## 3. The corrected result — every h=63 cell re-measured non-overlapping

| universe | signal | h | mean IC | n | p | q |
|---|---|---:|---:|---:|---:|---:|
| U9 | dist_sma200 | 21 | +0.0687 | 204 | 0.011 | 0.215 |
| U12 | vol_60 | 63 | +0.0899 | 56 | 0.021 | 0.215 |
| U9 | mom_6 | 21 | +0.0584 | 204 | 0.053 | 0.350 |
| U9 | mom_12_1 | 21 | +0.0511 | 204 | 0.070 | 0.350 |
| U12 | vol_60 | 21 | +0.0479 | 169 | 0.100 | 0.368 |
| … | (all other 15 cells) | | | | ≥0.11 | ≥0.37 |
| **U9** | **reversal_1m** | **63** | **+0.0174** | **68** | **0.630** | **0.663** |

The two lowest-q cells (`dist_sma200` on the semis at a month, `vol_60` on the mega-caps at a quarter)
both land at q = 0.215 — the nearest thing to a signal, and it fails. **Zero survivors.**

## 4. Predictions: 1, 2, 4 held; 3 and 5 refuted

1. **Momentum ICs indistinguishable from zero — HELD.** `mom_12_1` and `mom_6` reach q ≥ 0.35
   everywhere. Single names did not rescue what the ETF baskets could not show.
2. **`vol_60` has the largest mean |IC| — HELD, barely.** 0.0615, just above `dist_sma200`'s 0.0603.
   The low-vol anomaly is the strongest of the five, and still not significant.
3. **`reversal_1m` negative at h=21 — REFUTED.** It is +0.0001 (U12) and +0.0432 (U9): the classic
   one-month reversal is *absent* on these names, if anything a weak positive continuation. This is a
   real if minor finding — the reversal effect the literature documents on broad universes does not
   appear on a tight semiconductor/mega-cap set.
4. **Zero cells survive — HELD**, after Amendment 1. The central claim, and it held only because the
   artifact in §2 was caught; the raw run would have falsely refuted it.
5. **Mean |IC| higher on U12 than U9 — REFUTED.** U9 (0.0517) edges U12 (0.0418). The tighter,
   higher-correlation semiconductor universe ranks marginally *better*, not worse — the opposite of the
   dispersion argument I predicted from. Both are tiny and neither is significant, so the reversal is
   weak evidence, but it points against the intuition that a more homogeneous universe has less to
   rank.

## 5. The decision, per the pre-registered rule (§5)

**Zero cells survive, so the blocked cross-symbol engine change is not justified by measured edge on
the universes the seated cards trade.** Building relative-strength / ranking machinery for these names
would unlock a capability with nothing measurable to capture. Recommendation 10's "author a genuinely
new hypothesis" should turn to a *different* input, not to cross-symbol machinery for this book.

**With one caveat the plan fixed in advance (§2), and it is the honest next step.** These universes are
concentrated — round 27 put their pairwise correlation at 0.46–0.83 — so they are close to the worst
case for cross-sectional selection, and this null is specifically about the concentrated book, not
cross-sectional selection in general. **A broader, less-correlated universe is the fair test**, and it
is the natural next round: if even a diversified universe shows null IC, the engine change is dead
everywhere relevant; if it shows signal, the change is justified but only for a universe this desk does
not currently trade.

## 6. What this round cannot settle

- **Two concentrated universes only** (§2). The null does not generalise to broad-market selection.
- **Rank IC, not return** — a non-zero IC would have been a precondition for an edge, not proof of one.
- **The overlap lesson generalises**: any future IC or event-study round with a horizon longer than its
  rebalance interval inflates significance the same way, and must rebalance at the horizon or correct
  for the overlap explicitly.
- **Nothing is promotable, and nothing here is a card.**

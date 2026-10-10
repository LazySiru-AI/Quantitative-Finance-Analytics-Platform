# Round 34 — report: the null replicates on industries, and they disperse *less*, not more

Run 2026-09-09 01:32–01:36 (local), eight main windows, 16 cards, serial, zero `FAILED` lines in any
window log. Pre-registration: `strategy-program/ROUND-34-PLAN.md` (2026-09-08). Computed tables:
`ANALYSIS.md` in this directory, produced by `strategy-program/tools/round34_36_report.py --round 34`
and mirrored in `analysis.json`. Scorecard: `scorecard.json` (`score.py --pin-store`).

**Not investment advice.** Price-only bars, no dividends, SPY benchmark, a synthetic paper book.

---

## 0. The instrument check ran first, and it reproduces to the digit

The plan (§5) pre-registered an *external* reproduction check because no cell of this round reproduces
a round-17 design. Before any round-34 card ran, the frozen `r17-ma-crossover-on-stop` (and its
`-stop-tp` sibling, which the `--only` substring also selects) was re-run against the current store:
`repro-r17/`. Every one of the eight per-window `adjusted_excess` figures matches round 17's committed
scorecard exactly — median +0.17pp, 155 trades, `bull-2024` −13.16pp, `gfc` +1.22pp, all to the last
digit. The instrument has not moved between rounds 17 and 34. The comparisons below are legitimate.

## 1. Result — every marginal inside the floor, again

| factor | spread | verdict |
|---|---|---|
| form (8 levels, each the mean of its regime on/off pair) | **4.21pp** | inside 21.2pp floor |
| regime filter (`close > sma(200)` on vs off) | **0.88pp** | inside |
| whole 16-cell field, max − min of cell medians | **6.40pp** | inside (pure-noise expectation at σ = 21.2: 74.9pp) |

Form ordering, for the record: `ma-crossover` −0.22pp, `momentum-state` −1.37pp, `macd-cross` −1.88pp,
`channel-breakout` −1.90pp, `band-reversion` −1.99pp, `band-breakout` −2.90pp, `rsi-pullback` −3.43pp,
`vol-compression` −4.44pp. Every form marginal is negative. The best single cell is
`r34-ma-crossover-on` at +1.24pp median (hit rate 5 of 8, worst window −9.95pp); the worst is
`r34-band-breakout-on` at −5.17pp.

**Decision rule (§5), applied:** "form matters on industries" required a form-marginal spread above
21.2pp **and** the best-vs-worst contrast surviving BH at q < 0.10 over all 16 cells. Neither half
holds. The spread is 4.21pp. Contrasting every cell with the worst cell by an exact sign-flip
permutation test over the eight paired window differences and correcting over all sixteen, the
minimum q in the field is **0.81**. **The null is the result: round 17's finding replicates out of
sample on a disjoint universe.**

## 2. The premise this round was built on is refuted — industries disperse *less* at the strategy level

Prediction 3 — descriptive, excluded from the decision rule, and the reason this universe was chosen —
said the 16-cell spread here would *exceed* round 17's exactly-comparable slice (its 8 forms × 2 regime
arms at the `stop` bracket). Round 17's slice spans **9.47pp**; this field spans **6.40pp**. The
strategy-level dispersion went the other way. Industries certainly disperse more than sectors at the
*price* level, but the eight rule forms compress that into an even narrower band of outcomes than they
did on nine sector SPDRs. The honest reading is that the forms are the bottleneck, not the universe:
the same eight rules produce the same near-zero result whatever mechanically-defined ETF basket they
are handed. That is a stronger statement of round 17's null than round 17 could make alone.

## 3. Predictions, beside their outcomes (§6)

| # | prediction | outcome |
|---|---|---|
| 1 | form marginal < 21.2pp | **held** — 4.21pp |
| 2 | regime marginal < 21.2pp | **held** — 0.88pp; on −1.82pp vs off −2.71pp. The `close > sma(200)` convention is unpaid-for on a second universe |
| 3 | 16-cell spread exceeds round 17's `stop` slice (descriptive) | **refuted** — 6.40pp vs 9.47pp, see §2 |
| 4 | `vol-compression` takes the fewest trades | **refuted** — `channel-breakout` takes fewest (159 across both arms); `vol-compression` 234, fourth-fewest. The 2% ATR gate opens more often than expected on these baskets; it is the exit's 5% expansion condition that keeps its exposure moderate (32–38%) |
| 5 | trend/momentum forms post their worst window in `chop-2011`/`chop-2015` | **mixed** — held for both `momentum-state` cells (`chop-2011`) and `vol-compression-on` (`chop-2015`); refuted for both `ma-crossover` cells, `macd-cross-on` and `vol-compression-off` (`bull-2024`) and `macd-cross-off` (`gfc`). `bull-2024` — an ordinary good year with a −19% intra-year drawdown — was the failure regime for the fast crossovers, not the sideways markets |
| 6 | all 16 cells scored in 8 of 8 windows | **held** — 128 of 128 runs, zero `FAILED` |

## 4. What is worth more than the headline

1. **`bull-2024` is where every fast-crossover cell lost most.** Seven of sixteen cells post their worst
   window there, not in the two chop windows the constitution names as the trend-follower's enemy.
   The regime filter did not help: `ma-crossover-on` lost −9.95pp there, `-off` −9.13pp. A year that
   ends +14% for SPY with a −19% air pocket in the middle whipsaws a 10/30 crossover on industry
   baskets as badly as a flat year does. The failure-regime vocabulary this programme uses should add
   "V-shaped correction inside an up-year" beside "sideways".
2. **The regime filter cuts exposure, not loss.** On average the `on` arm holds 26% of capital and the
   `off` arm 41%, for a 0.88pp difference in median. On this universe the 200-day filter is a position
   sizer that happens to be spelled as an entry condition.
3. **Two cells are positive and neither is a finding.** `ma-crossover-on` (+1.24pp) and `macd-cross-on`
   (+0.80pp) clear the regime gate with a positive median — the letter of `PROTOCOL.md` §6's
   challenger → `candidates/` line. Both sit inside the floor by a factor of seventeen, both fail BH
   (q = 0.81), and this plan pre-registered that nothing is promoted from a measurement study. They are
   reported here so that the round's best cell is on the record, not so that anyone reads it as an edge.

## 5. What this round cannot settle (unchanged from the plan, §7)

Fund-level survivorship of the eight ETFs (all pre-2007, mechanically defined, but survivors);
price-only bars (hardest on `VNQ`, whose return is substantially distributions); SPY as the benchmark
for a Roth book of equal-weight industry baskets; and the ordering-noise floor, which round 36 measures
directly on this same universe. Ticker disjointness from every taxable card is established
(`disjoint_field.py`: 0 hits); §1091 substantial identity is not, and is not claimed.

## 6. Disposition

- **Nothing promoted by this round's own rule** (§5: measurement study; §6(b): no margin here clears the
  floor). **On 2026-09-09, after this report's numbers existed, the owner directed that
  `r34-ma-crossover-on` be promoted to `candidates/` regardless.** That is recorded in `PROTOCOL.md` §9
  as a directed promotion, the way `C-trend`'s was: the card satisfies the letter of the challenger →
  `candidates/` line (gate cleared, positive median) and fails condition (b) (margin inside the floor).
  Its presence in the library is the owner's decision, not this round's finding, and this section is
  the record that says so. The library copy is verbatim; the frozen card here is unchanged.
- Round 17's null now stands on two disjoint universes. The evolution loop's single-template history
  cost, on this evidence, at most ~4pp of median across the eight forms — and `ma-crossover`, the form it
  ran for 1,915 generations, is the best marginal here.
- Files: `cards/` (frozen field), `results/<window>/runs/`, `results/*.log`, `scorecard.json`,
  `ANALYSIS.md`, `analysis.json`, `repro-r17/` (the instrument check).

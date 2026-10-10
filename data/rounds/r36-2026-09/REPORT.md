# Round 36 — report: `rank_by` carries no slot-level information here, and ordering noise on this universe is ~2pp

Run 2026-09-09 01:39–01:43 (local), eight main windows, 10 cards, serial, zero `FAILED` lines in any
window log. Pre-registration: `strategy-program/ROUND-36-PLAN.md` (2026-09-08). Computed tables:
`ANALYSIS.md` in this directory, produced by `strategy-program/tools/round34_36_report.py --round 36`
and mirrored in `analysis.json`. Scorecard: `scorecard.json` (`score.py --pin-store`). The family's
instrument check (`data/rounds/r34-2026-09/repro-r17/`) reproduced round 17 to the digit minutes before.

**Not investment advice.** Price-only bars, no dividends, SPY benchmark, a synthetic paper book.

---

## 1. The precondition held — the cap bound in every window

Plan §8 said the round measures nothing unless the slot cap actually binds. It did. In the k=2 arm all
five orderings produced **five distinct results in eight of eight windows**; in the k=4 arm, three to
five distinct results per window (3, 3, 4, 5, 5, 5, 5, 4). Every ordering had work to do, every window,
and the round's contrasts are therefore real contrasts and not five copies of one number.

## 2. Result — every contrast inside the floor, by an order of magnitude

| contrast (median adjusted excess) | k=2 | k=4 | sign agreement | verdict |
|---|---|---|---|---|
| strongest-first − weakest-first | **+1.22pp** | **+1.01pp** | 5 of 8 windows at both caps | inside 21.2pp floor |
| canonical − reversed order (ordering noise, magnitude) | 0.13pp | 0.26pp | 4 / 4 at both | inside |
| strong − vol-units spelling | −0.82pp | −0.60pp | | inside |
| five-ordering spread within the arm | **2.04pp** | **1.60pp** | | pure-noise expectation at σ = 21.2: 49.3pp |
| BH q for strong vs weak, m = 10 | 0.40 | 0.52 | | nothing survives |

**Decision rule (§5), applied:** `rank_by` carries information only if strong − weak exceeds 21.2pp,
with the same sign in ≥ 5 of 8 windows, surviving BH over all ten cells. The sign condition is met
(5 of 8, both caps) and nothing else is: the difference is +1.2pp and +1.0pp, and q is 0.40 and 0.52.
**Inside the floor, in those words.** Relative strength does not decide the slot on this universe.

## 3. The number this round exists to produce — ordering noise on a third universe

`canonical − reversed`, identical rule, identical names, identical sizing, opposite written order:
**0.13pp at k=2, 0.26pp at k=4**, and the whole five-ordering spread is 2.04pp / 1.60pp. Round 17
measured ~1pp on nine sector SPDRs (shuffled-ordering replication); the programme's 21.2pp floor came
from twelve concentrated semiconductor names. This is the third datapoint and it sits with round 17,
not with the floor. Per the plan (§5), **this round does not lower its own bar** — it is a datapoint a
future round may set a floor from, and the floor stays 21.2pp for every margin reported here.

The one place ordering mattered at all is `recent` in the k=2 arm: `canonical` −17.50pp, `weak`
−14.78pp, `volunits` −16.50pp against `reversed` −4.37pp and `strong` −6.34pp — a 13pp spread in a single
window, from which two names take the two slots. It is one window, it is inside the single-contrast
95th percentile (58.7pp), and it is absorbed to a 0.13pp median difference across the eight.

## 4. Predictions, beside their outcomes (§7)

| # | prediction | outcome |
|---|---|---|
| 1 | \|canonical − reversed\| < 5pp at both caps | **held** — 0.13pp, 0.26pp |
| 2 | strong − weak inside 21.2pp at both caps | **held** — +1.22pp, +1.01pp |
| 3 | k=2 ordering spread > k=4 | **held** — 2.04pp vs 1.60pp, by a little |
| 4 | `strong`'s worst window is `covid`, and strong ≤ weak there | **half refuted** — strong ≤ weak in `covid` holds at both caps (−0.23 vs +1.55pp; +1.24 vs +1.88pp), but `strong`'s worst window is `gfc` at both caps (−9.03pp, −3.83pp), not `covid`. In `covid` the c20 filter barely qualified anything (every cell within ±2pp), so the reversal never got to punish the leader |
| 5 | cap binds in ≥ 5 of 8 windows at k=2 | **held** — 8 of 8 |
| 6 | all ten cells at 8 of 8 | **held** — 80 of 80 runs |

## 5. What is worth more than the headline

1. **k=4 is a better book than k=2 on this rule, and it is not close.** Every k=4 cell has a worst
   window between −3.83pp and −5.55pp; every k=2 cell between −9.03pp and −24.17pp. Concentration into
   two industry baskets at 25% each is where the drawdowns live (`weak-k2` −24.17pp in `gfc`,
   `canonical-k2` −21.29pp). The plan pre-registered that slot count and position size move together in
   this design, so this is a statement about the *book*, not about ordering — but it is the largest
   effect in the round by a wide margin, and it is the same lesson round 35's IQR result taught.
2. **`volunits-k4` is the family's only other positive cell** (+0.36pp median, worst −4.58pp), beside
   round 34's `ma-crossover-on` (+1.24pp) and `macd-cross-on` (+0.80pp). It is 0.60pp from `strong-k4`,
   which is the "spelling" contrast the plan said should be inside the floor if relative strength is
   real and would be suspicious if it were not. It is inside. Nothing here is a finding.
3. **Same rule, same exposure, whatever the order.** Mean capital exposure is 0.340 for all five k=2
   cells and 0.277–0.279 for all five k=4 cells. `rank_by` changes *which* names are held, never how
   much is held — which is exactly what the docstring promises and what makes the contrasts clean.

## 6. What this round cannot settle (unchanged from the plan, §11)

Roster survivorship, price-only bars, SPY as a Roth benchmark, the confounded slot-count/size factor,
and the fact that this round measured ordering on one rule (c20's) and one universe — a third datapoint
for the floor, not a replacement for it. Ticker disjointness is established; §1091 substantial identity
is not, and is not claimed.

## 7. Disposition

- **Nothing promoted by this round's own rule** (plan §5: measurement study; §6(b): every margin inside
  the floor).
- `c20-rotation`'s "arbitrary-but-reasoned tiebreak" caveat now has a measured answer on an eight-name
  industry universe: the tiebreak is worth about a point of median either way.
- Files: `cards/`, `results/<window>/runs/`, `results/*.log`, `scorecard.json`, `ANALYSIS.md`,
  `analysis.json`.

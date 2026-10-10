# Round 48 -- computed verdict tables

**Not investment advice.** Price-only bars, no dividends. Nothing in this round is promotable (`trading` purpose, PROTOCOL.md r21 amendment) -- report only. A decision to resize a seated card for real is the owner's, about risk; this round measures what that decision would have cost and bought.

## Cells

| cell | ranked | median adj. excess | worst | hit rate | IQR | trades | mean exposure | windows |
|---|---|---|---|---|---|---|---|---|
| `r48-i13f-base` | NO | +34.40pp | +34.40pp | 1.000 | n/a | 55 | 0.541 | 1/8 |
| `r48-i13f-risk1pct` | NO | +21.87pp | +21.87pp | 1.000 | n/a | 42 | 0.288 | 1/8 |
| `r48-b3-base` | yes | +13.89pp | -7.75pp | 0.667 | +25.66pp | 56 | 0.385 | 6/8 |
| `r48-bmom-base` | yes | +12.16pp | -5.15pp | 0.667 | +21.42pp | 70 | 0.349 | 6/8 |
| `r48-bmom-risk1pct` | yes | +6.94pp | -2.80pp | 0.667 | +11.27pp | 65 | 0.185 | 6/8 |
| `r48-b3-risk1pct` | yes | +6.66pp | -2.80pp | 0.667 | +8.97pp | 52 | 0.143 | 6/8 |
| `r48-ctrend-base` | yes | +5.03pp | -7.26pp | 0.500 | +19.17pp | 59 | 0.281 | 6/8 |
| `r48-ctrend-risk1pct` | yes | +2.35pp | -2.71pp | 0.500 | +8.93pp | 57 | 0.126 | 6/8 |
| `r48-arot-risk1pct` | yes | -1.59pp | -7.92pp | 0.429 | +7.05pp | 215 | 0.149 | 7/8 |
| `r48-arot-base` | yes | -7.16pp | -27.41pp | 0.429 | +16.13pp | 189 | 0.488 | 7/8 |

## Per-window adjusted excess

| cell | q4-2018 | covid | bear-2022 | chop-2015 | chop-2011 | bull-2024 | recent | gfc |
|---|---|---|---|---|---|---|---|---|
| `r48-arot-base` | -8.76pp | +4.94pp | -27.41pp | -7.16pp | -17.01pp | +1.56pp | +80.25pp | n/a |
| `r48-arot-risk1pct` | -3.63pp | +2.59pp | -7.92pp | -1.59pp | -4.78pp | +3.09pp | +19.84pp | n/a |
| `r48-b3-base` | -1.18pp | +26.76pp | -7.75pp | +23.29pp | n/a | +4.50pp | +31.52pp | n/a |
| `r48-b3-risk1pct` | -0.45pp | +10.11pp | -2.80pp | +8.77pp | n/a | +4.55pp | +10.34pp | n/a |
| `r48-bmom-base` | -0.79pp | +27.70pp | -5.15pp | +24.60pp | n/a | +7.40pp | +16.91pp | n/a |
| `r48-bmom-risk1pct` | -0.45pp | +15.27pp | -2.80pp | +13.59pp | n/a | +5.46pp | +8.42pp | n/a |
| `r48-ctrend-base` | -0.97pp | +19.80pp | -5.82pp | +11.02pp | n/a | +15.75pp | -7.26pp | n/a |
| `r48-ctrend-risk1pct` | -0.43pp | +9.18pp | -2.71pp | +5.14pp | n/a | +7.51pp | -2.55pp | n/a |
| `r48-i13f-base` | n/a | n/a | n/a | n/a | n/a | n/a | +34.40pp | n/a |
| `r48-i13f-risk1pct` | n/a | n/a | n/a | n/a | n/a | n/a | +21.87pp | n/a |

## risk1pct minus OWN base -- the sizing table (PLAN decision rule input)

| base | base median | risk1pct median | arm - base | worst: base -> risk1pct | IQR: base -> risk1pct | exposure: base -> risk1pct | windows arm>base | p (sign-flip) |
|---|---|---|---|---|---|---|---|---|
| b3 | +13.89pp | +6.66pp | -7.23pp | -7.75pp -> -2.80pp | +25.66pp -> +8.97pp | 0.385 -> 0.143 | 3/6 | 0.2500 |
| arot | -7.16pp | -1.59pp | +5.57pp | -27.41pp -> -7.92pp | +16.13pp -> +7.05pp | 0.488 -> 0.149 | 5/7 | 0.9688 |
| ctrend | +5.03pp | +2.35pp | -2.67pp | -7.26pp -> -2.71pp | +19.17pp -> +8.93pp | 0.281 -> 0.126 | 3/6 | 0.3438 |
| bmom | +12.16pp | +6.94pp | -5.21pp | -5.15pp -> -2.80pp | +21.42pp -> +11.27pp | 0.349 -> 0.185 | 2/6 | 0.1875 |
| i13f | +34.40pp | +21.87pp | -12.53pp | +34.40pp -> +21.87pp | n/a -> n/a | 0.541 -> 0.288 | 0/1 | 1.0000 |

## Marginal (mean over the 5 bases of risk1pct-minus-own-base median)

**-4.42pp** -- inside the 21.2pp floor.

## BH over all 10 cells (m=10) -- each risk1pct cell contrasted with its OWN base

| cell | base | median diff | p (sign-flip) | q (BH, m=10) |
|---|---|---|---|---|
| `r48-b3-base` | r48-b3-base | +0.00pp |  |  |
| `r48-b3-risk1pct` | r48-b3-base | -7.23pp | 0.2500 | 1.0000 |
| `r48-arot-base` | r48-arot-base | +0.00pp |  |  |
| `r48-arot-risk1pct` | r48-arot-base | +5.57pp | 0.9688 | 1.0000 |
| `r48-ctrend-base` | r48-ctrend-base | +0.00pp |  |  |
| `r48-ctrend-risk1pct` | r48-ctrend-base | -2.67pp | 0.3438 | 1.0000 |
| `r48-bmom-base` | r48-bmom-base | +0.00pp |  |  |
| `r48-bmom-risk1pct` | r48-bmom-base | -5.21pp | 0.1875 | 1.0000 |
| `r48-i13f-base` | r48-i13f-base | +0.00pp |  |  |
| `r48-i13f-risk1pct` | r48-i13f-base | -12.53pp | 1.0000 | 1.0000 |

Minimum q over the field: **1.0000**

## Verdict (PLAN decision rule: marginal > 21.2pp AND every risk1pct cell q<0.10)

marginal -4.42pp (inside the 21.2pp floor); arm q-values ['1.0000', '1.0000', '1.0000', '1.0000', '1.0000'] (not all < 0.10) -> **NULL**.

## Worst window in dollars of realised P&L (PROTOCOL.md section 4 caveat, made currency-visible)

| cell | worst window (adj. excess) | worst-window P&L (run file, USD) | total realised P&L (scorecard, USD) |
|---|---|---|---|
| `r48-arot-base` | bear-2022 | $-3,327.46 | $3,321.91 |
| `r48-arot-risk1pct` | bear-2022 | $-991.40 | $816.47 |
| `r48-b3-base` | bear-2022 | $-1,016.53 | $8,620.19 |
| `r48-b3-risk1pct` | bear-2022 | $-369.45 | $3,374.59 |
| `r48-bmom-base` | bear-2022 | $-676.81 | $7,933.08 |
| `r48-bmom-risk1pct` | bear-2022 | $-369.45 | $4,359.98 |
| `r48-ctrend-base` | recent | $-223.64 | $3,860.83 |
| `r48-ctrend-risk1pct` | bear-2022 | $-323.36 | $1,857.47 |
| `r48-i13f-base` | recent | $4,555.32 | $4,555.32 |
| `r48-i13f-risk1pct` | recent | $2,781.41 | $2,781.41 |

## Predictions (PLAN)

1. Null on the median marginal (|marginal| < 5pp): **HELD** (-4.42pp).
2. Worst window shallower on >= 4 of 5 bases: **HELD** (4/5; {'b3': True, 'arot': True, 'ctrend': True, 'bmom': True, 'i13f': False}).
3. IQR narrower on >= 4 of 5 bases: **HELD** (4/5; {'b3': True, 'arot': True, 'ctrend': True, 'bmom': True}).
4. Mean exposure lower on 5 of 5 bases: **HELD** (5/5; {'b3': True, 'arot': True, 'ctrend': True, 'bmom': True, 'i13f': True}).
5. Per-window sign pattern identical on >= 7 of 8 windows for every base: **NOT CONFIRMED / REFUTED** ({'b3': '6/6', 'arot': '7/7', 'ctrend': '6/6', 'bmom': '6/6', 'i13f': '1/1'}).
6. Adjusted excess per unit exposure within +/-3pp of base on every base (sizing is not alpha): **NOT CONFIRMED / REFUTED** ({'b3': '+10.45pp', 'arot': '+3.97pp', 'ctrend': '+0.76pp', 'bmom': '+2.67pp', 'i13f': '+12.27pp'}).
7. `i13f` cells UNRANKED by provenance on the main windows (reported, not interpreted): **HELD** ({'r48-i13f-base': {'ranked': False, 'n_windows_run': 1}, 'r48-i13f-risk1pct': {'ranked': False, 'n_windows_run': 1}}).
8. PROTOCOL.md section 4's small-book caveat: see the dollar worst-window table above -- a shallower worst window in percentage points is a size effect on a book that shrank; the dollar figures beside it are the plain outcome, not adjusted for that.

Nothing in this round is promotable regardless of outcome (`trading` purpose, PROTOCOL.md r21 amendment) -- these are measurement results only. A decision to resize a seated card for real is the owner's, about risk; this round measures what that decision would have cost and bought. Not investment advice.


(wrote data/rounds/r48-2026-09/analysis.json)

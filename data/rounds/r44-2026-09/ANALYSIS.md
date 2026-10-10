# Round 44 -- computed verdict tables

Not investment advice. See `strategy-program/ROUND-44-PLAN.md` for the pre-registration.

## Cells (ranked on median adjusted excess vs SPY)

| cell | ranked | median adj. excess | worst | hit rate | IQR | trades | mean exposure | windows |
|---|---|---|---|---|---|---|---|---|
| `r44-power-trim` | yes | +9.16pp | -7.92pp | 0.875 | +16.22pp | 78 | 0.902 | 8/8 |
| `r44-power-passive` | yes | +6.79pp | -9.29pp | 0.750 | +11.86pp | 32 | 0.990 | 8/8 |
| `r44-defense-trim` | yes | -0.13pp | -13.26pp | 0.500 | +11.90pp | 85 | 0.870 | 8/8 |
| `r44-defense-passive` | yes | -0.89pp | -13.26pp | 0.500 | +11.79pp | 32 | 0.956 | 8/8 |
| `r44-semicap-trim` | yes | -1.09pp | -19.86pp | 0.500 | +16.20pp | 66 | 0.794 | 8/8 |
| `r44-control-passive` | yes | -1.22pp | -3.22pp | 0.250 | +2.72pp | 32 | 0.965 | 8/8 |
| `r44-control-trim` | yes | -1.22pp | -3.57pp | 0.250 | +2.95pp | 42 | 0.963 | 8/8 |
| `r44-semicap-passive` | yes | -1.45pp | -22.39pp | 0.500 | +18.47pp | 32 | 0.975 | 8/8 |
| `r44-realassets-trim` | yes | -4.62pp | -22.09pp | 0.250 | +13.24pp | 87 | 0.865 | 8/8 |
| `r44-realassets-passive` | yes | -5.35pp | -23.53pp | 0.250 | +13.25pp | 32 | 0.987 | 8/8 |

## Per-window adjusted excess

| cell | q4-2018 | covid | bear-2022 | chop-2015 | chop-2011 | bull-2024 | recent | gfc |
|---|---|---|---|---|---|---|---|---|
| `r44-control-passive` | -0.90pp | -3.11pp | +2.30pp | -1.54pp | -2.78pp | -3.22pp | +1.36pp | -0.65pp |
| `r44-control-trim` | -0.90pp | -3.11pp | +2.30pp | -1.54pp | -2.78pp | -3.57pp | +3.33pp | -0.65pp |
| `r44-defense-passive` | -6.91pp | -13.26pp | +34.10pp | +5.92pp | -6.77pp | -4.30pp | +4.67pp | +2.53pp |
| `r44-defense-trim` | -6.91pp | -13.26pp | +36.70pp | +5.89pp | -4.44pp | -5.47pp | +6.61pp | +4.18pp |
| `r44-power-passive` | +22.49pp | -3.63pp | +12.21pp | +2.41pp | +6.10pp | +7.48pp | -9.29pp | +14.41pp |
| `r44-power-trim` | +23.78pp | +1.87pp | +18.89pp | +2.41pp | +11.53pp | +6.78pp | -7.92pp | +18.36pp |
| `r44-realassets-passive` | -3.90pp | -7.74pp | +20.55pp | -19.39pp | -23.53pp | -3.39pp | +42.28pp | -6.80pp |
| `r44-realassets-trim` | -3.90pp | -7.74pp | +12.55pp | -20.34pp | -22.09pp | -5.33pp | +12.04pp | -0.89pp |
| `r44-semicap-passive` | -2.95pp | +12.51pp | -22.39pp | +8.18pp | +0.04pp | -17.13pp | +152.63pp | -6.57pp |
| `r44-semicap-trim` | -2.95pp | +23.11pp | -19.86pp | +5.99pp | +0.76pp | -16.22pp | +18.03pp | -4.19pp |

## Question 1 (BASKET): basket-passive minus control-passive

| basket | basket median | control median | 8-window median diff | 6 fair windows (gfc..bear-2022) | 2 hindsight windows (bull-2024, recent) | windows basket>control | p (sign-flip) | clears floor+q<0.10? |
|---|---|---|---|---|---|---|---|---|
| power | +6.79pp | -1.22pp | +8.01pp | +9.40pp | +0.03pp | 6/8 | 0.0859 | no |
| defense | -0.89pp | -1.22pp | +0.33pp | -0.40pp | +1.12pp | 4/8 | 0.6797 | no |
| semicap | -1.45pp | -1.22pp | -0.23pp | +0.39pp | +68.68pp | 4/8 | 0.6875 | no |
| realassets | -5.35pp | -1.22pp | -4.13pp | -5.39pp | +20.38pp | 2/8 | 0.9688 | no |

## Question 2 (RULE): trim minus passive, per basket

| basket | trim median | passive median | 8-window median diff | 6 fair windows | 2 hindsight windows | windows trim>passive | p (sign-flip) | mean exposure trim vs passive | trades trim vs passive | clears floor+q<0.10? |
|---|---|---|---|---|---|---|---|---|---|---|
| power | +9.16pp | +6.79pp | +2.36pp | +4.69pp | +0.33pp | 6/8 | 0.0312 | 0.902 vs 0.990 | 78 vs 32 | no |
| defense | -0.13pp | -0.89pp | +0.76pp | +0.83pp | +0.38pp | 4/8 | 0.1250 | 0.870 vs 0.956 | 85 vs 32 | no |
| semicap | -1.09pp | -1.45pp | +0.36pp | +1.55pp | -66.85pp | 5/8 | 0.9375 | 0.794 vs 0.975 | 66 vs 32 | no |
| realassets | -4.62pp | -5.35pp | +0.73pp | +0.00pp | -16.09pp | 2/8 | 0.3438 | 0.865 vs 0.987 | 87 vs 32 | no |
| control | -1.22pp | -1.22pp | +0.00pp | +0.00pp | +0.81pp | 1/8 | 1.0000 | 0.963 vs 0.965 | 42 vs 32 | no |

## BH over all 10 cells (m=10) against `r44-control-passive`

| cell | median diff vs control-passive | p (sign-flip) | q (BH) |
|---|---|---|---|
| `r44-power-trim` | +10.37pp | 0.0391 | 0.3906 |
| `r44-power-passive` | +8.01pp | 0.0859 | 0.4297 |
| `r44-defense-trim` | +1.09pp | 0.5703 | 1.0000 |
| `r44-defense-passive` | +0.33pp | 0.6797 | 1.0000 |
| `r44-semicap-trim` | +0.12pp | 0.7578 | 1.0000 |
| `r44-control-passive` | +0.00pp |  |  |
| `r44-control-trim` | +0.00pp | 1.0000 | 1.0000 |
| `r44-semicap-passive` | -0.23pp | 0.6875 | 1.0000 |
| `r44-realassets-trim` | -3.40pp | 0.4219 | 1.0000 |
| `r44-realassets-passive` | -4.13pp | 0.9688 | 1.0000 |

Minimum q over the field: **0.3906**

## Exposure prediction (PLAN section 5 #4): trim falls most in semicap, least in power

| basket | mean trim exposure |
|---|---|
| semicap | 0.794 |
| realassets | 0.865 |
| defense | 0.870 |
| power | 0.902 |
| control | 0.963 |

Lowest trim exposure: **semicap** (predicted semicap); highest: **control** (predicted power) -- not exactly as predicted.

## Trend/crisis-window check (PLAN section 5 #5/#6): trim minus passive in named windows

| basket | bull-2024 | recent | bear-2022 | gfc |
|---|---|---|---|---|
| power | -0.70pp | +1.37pp | +6.67pp | +3.96pp |
| defense | -1.17pp | +1.94pp | +2.60pp | +1.65pp |
| semicap | +0.91pp | -134.61pp | +2.53pp | +2.38pp |
| realassets | -1.94pp | -30.24pp | -8.00pp | +5.91pp |
| control | -0.35pp | +1.97pp | +0.00pp | +0.00pp |

Trim underperforms passive in BOTH bull-2024 and recent, every basket: **REFUTED**.

## Verdict (PLAN section 4 decision rule)

- Any basket beats control by >21.2pp (before the BH check): **NO (null)**.
- Any trim arm beats its own passive by >21.2pp (before the BH check): **NO (null)**.
- Minimum BH q over all 10 cells: **0.3906** (nothing survives q<0.10 unless this is below it).

**A basket or trim edge requires BOTH the >21.2pp margin AND BH q<0.10 (PLAN section 4). Nothing is promoted from this round regardless of outcome -- it is a pre-registered measurement study.**


(wrote data/rounds/r44-2026-09/analysis.json)

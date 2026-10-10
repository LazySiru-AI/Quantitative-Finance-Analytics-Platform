# Round 47 -- computed verdict tables

Not investment advice. See `strategy-program/ROUND-47-PLAN.md` for the pre-registration.

## Cells (ranked on median adjusted excess vs SPY)

| cell | ranked | median adj. excess | worst | hit rate | IQR | trades | mean exposure | windows |
|---|---|---|---|---|---|---|---|---|
| `r47-power-trim` | yes | +9.16pp | -7.92pp | 0.875 | +16.22pp | 78 | 0.902 | 8/8 |
| `r47-power-passive` | yes | +6.79pp | -9.29pp | 0.750 | +11.86pp | 32 | 0.990 | 8/8 |
| `r47-power-dip-trim` | yes | +6.71pp | -4.21pp | 0.625 | +12.47pp | 86 | 0.693 | 8/8 |
| `r47-power-dip` | yes | +5.85pp | -5.82pp | 0.625 | +12.02pp | 31 | 0.767 | 8/8 |
| `r47-defense-trim` | yes | -0.13pp | -13.26pp | 0.500 | +11.90pp | 85 | 0.870 | 8/8 |
| `r47-control-dip-trim` | yes | -0.64pp | -2.48pp | 0.250 | +2.03pp | 33 | 0.856 | 8/8 |
| `r47-defense-dip-trim` | yes | -0.81pp | -8.14pp | 0.500 | +8.83pp | 69 | 0.680 | 8/8 |
| `r47-defense-passive` | yes | -0.89pp | -13.26pp | 0.500 | +11.79pp | 32 | 0.956 | 8/8 |
| `r47-control-dip` | yes | -1.10pp | -2.48pp | 0.250 | +1.91pp | 31 | 0.860 | 8/8 |
| `r47-control-passive` | yes | -1.22pp | -3.22pp | 0.250 | +2.72pp | 32 | 0.965 | 8/8 |
| `r47-control-trim` | yes | -1.22pp | -3.57pp | 0.250 | +2.95pp | 42 | 0.963 | 8/8 |
| `r47-defense-dip` | yes | -1.44pp | -8.14pp | 0.375 | +11.01pp | 28 | 0.751 | 8/8 |

## Per-window adjusted excess

| cell | q4-2018 | covid | bear-2022 | chop-2015 | chop-2011 | bull-2024 | recent | gfc |
|---|---|---|---|---|---|---|---|---|
| `r47-control-dip` | -1.38pp | -0.09pp | +3.58pp | -1.05pp | -2.48pp | -1.41pp | +2.33pp | -1.14pp |
| `r47-control-dip-trim` | -1.38pp | -0.09pp | +3.58pp | -1.05pp | -2.48pp | -0.22pp | +3.96pp | -1.14pp |
| `r47-control-passive` | -0.90pp | -3.11pp | +2.30pp | -1.54pp | -2.78pp | -3.22pp | +1.36pp | -0.65pp |
| `r47-control-trim` | -0.90pp | -3.11pp | +2.30pp | -1.54pp | -2.78pp | -3.57pp | +3.33pp | -0.65pp |
| `r47-defense-dip` | -2.10pp | -8.14pp | +21.40pp | +6.25pp | -6.14pp | -4.28pp | +6.34pp | -0.77pp |
| `r47-defense-dip-trim` | -2.10pp | -8.14pp | +22.79pp | +6.16pp | -3.77pp | -4.98pp | +4.29pp | +0.49pp |
| `r47-defense-passive` | -6.91pp | -13.26pp | +34.10pp | +5.92pp | -6.77pp | -4.30pp | +4.67pp | +2.53pp |
| `r47-defense-trim` | -6.91pp | -13.26pp | +36.70pp | +5.89pp | -4.44pp | -5.47pp | +6.61pp | +4.18pp |
| `r47-power-dip` | +12.73pp | -2.04pp | +10.17pp | +7.17pp | +11.89pp | -1.21pp | -5.82pp | +4.52pp |
| `r47-power-dip-trim` | +12.70pp | -0.26pp | +12.39pp | +7.17pp | +11.89pp | -4.21pp | -1.07pp | +6.24pp |
| `r47-power-passive` | +22.49pp | -3.63pp | +12.21pp | +2.41pp | +6.10pp | +7.48pp | -9.29pp | +14.41pp |
| `r47-power-trim` | +23.78pp | +1.87pp | +18.89pp | +2.41pp | +11.53pp | +6.78pp | -7.92pp | +18.36pp |

## Arm minus passive, within basket

| basket | arm | arm median | passive median | 8-window median diff | 6 fair windows (gfc..bear-2022) | 2 hindsight windows (bull-2024, recent) | windows arm>passive | p (sign-flip) | mean exposure arm vs passive | trades arm vs passive | clears floor (21.2pp)? |
|---|---|---|---|---|---|---|---|---|---|---|---|
| power | dip | +5.85pp | +6.79pp | -0.94pp | -0.23pp | -2.61pp | 4/8 | 0.4531 | 0.767 vs 0.990 | 31 vs 32 | no |
| power | trim | +9.16pp | +6.79pp | +2.36pp | +4.69pp | +0.33pp | 6/8 | 0.0312 | 0.902 vs 0.990 | 78 vs 32 | no |
| power | dip-trim | +6.71pp | +6.79pp | -0.08pp | +1.78pp | -1.73pp | 5/8 | 0.7500 | 0.693 vs 0.990 | 86 vs 32 | no |
| defense | dip | -1.44pp | -0.89pp | -0.55pp | +0.48pp | +0.85pp | 6/8 | 0.8750 | 0.751 vs 0.956 | 28 vs 32 | no |
| defense | trim | -0.13pp | -0.89pp | +0.76pp | +0.83pp | +0.38pp | 4/8 | 0.1250 | 0.870 vs 0.956 | 85 vs 32 | no |
| defense | dip-trim | -0.81pp | -0.89pp | +0.08pp | +1.62pp | -0.53pp | 4/8 | 0.9453 | 0.680 vs 0.956 | 69 vs 32 | no |
| control | dip | -1.10pp | -1.22pp | +0.12pp | +0.39pp | +1.40pp | 6/8 | 0.0781 | 0.860 vs 0.965 | 31 vs 32 | no |
| control | trim | -1.22pp | -1.22pp | +0.00pp | +0.00pp | +0.81pp | 1/8 | 1.0000 | 0.963 vs 0.965 | 42 vs 32 | no |
| control | dip-trim | -0.64pp | -1.22pp | +0.58pp | +0.39pp | +2.80pp | 6/8 | 0.0781 | 0.856 vs 0.965 | 33 vs 32 | no |

## dip-trim minus max(dip, trim), per basket

| basket | dip median | trim median | dip-trim median | max(dip, trim) | dip-trim minus max | dip-trim <= max? |
|---|---|---|---|---|---|---|
| power | +5.85pp | +9.16pp | +6.71pp | +9.16pp | -2.45pp | YES |
| defense | -1.44pp | -0.13pp | -0.81pp | -0.13pp | -0.68pp | YES |
| control | -1.10pp | -1.22pp | -0.64pp | -1.10pp | +0.46pp | no |

`dip-trim <= max(dip, trim)` in **2 of 3** baskets -- predicted in at least 2 of 3: **HELD**.

## Days-to-first-entry, dip-entry cells (dip, dip-trim), per window

First trade's `entry_date` minus the window's own start date, from the run files (`data/rounds/r47-2026-09/results/<window>/runs/r1-<agent_id>.json`). `--` = no trade in that window.

| cell | q4-2018 | covid | bear-2022 | chop-2015 | chop-2011 | bull-2024 | recent | gfc |
|---|---|---|---|---|---|---|---|---|
| `r47-power-dip` | 0 | 8 | 0 | 0 | 8 | 47 | 0 | 8 |
| `r47-power-dip-trim` | 38 | 9 | 0 | 0 | 8 | 48 | 0 | 13 |
| `r47-defense-dip` | 19 | 0 | 0 | 0 | 0 | 7 | 20 | 13 |
| `r47-defense-dip-trim` | 19 | 0 | 0 | 8 | 12 | 63 | 20 | 45 |
| `r47-control-dip` | 6 | 6 | 3 | 0 | 0 | 14 | 53 | 22 |
| `r47-control-dip-trim` | 6 | 6 | 3 | 0 | 0 | 14 | 85 | 22 |

## Trim minus passive, bull-2024 vs recent, per basket (plan prediction 4)

Round 44 found the trim arm loses to its own passive control in `bull-2024` in every basket but *won* in `recent` for `power` and `defense`. This round pre-registers both windows separately for the same three arms and predicts only `bull-2024` (a loss); `recent` is reported without a directional prediction.

| basket | trim minus passive, bull-2024 | trim minus passive, recent | bull-2024 loss predicted, held? |
|---|---|---|---|
| power | -0.70pp | +1.37pp | YES |
| defense | -1.17pp | +1.94pp | YES |
| control | -0.35pp | +1.97pp | YES |

## BH over all 12 cells (m=12) against `r47-control-passive`

| cell | median diff vs control-passive | p (sign-flip) | q (BH) |
|---|---|---|---|
| `r47-power-trim` | +10.37pp | 0.0391 | 0.1719 |
| `r47-power-passive` | +8.01pp | 0.0859 | 0.1719 |
| `r47-power-dip-trim` | +7.93pp | 0.0391 | 0.1719 |
| `r47-power-dip` | +7.06pp | 0.0547 | 0.1719 |
| `r47-defense-trim` | +1.09pp | 0.5703 | 0.7604 |
| `r47-control-dip-trim` | +0.58pp | 0.0781 | 0.1719 |
| `r47-defense-dip-trim` | +0.41pp | 0.4062 | 0.6797 |
| `r47-defense-passive` | +0.33pp | 0.6797 | 0.8156 |
| `r47-control-dip` | +0.12pp | 0.0781 | 0.1719 |
| `r47-control-passive` | +0.00pp |  |  |
| `r47-control-trim` | +0.00pp | 1.0000 | 1.0000 |
| `r47-defense-dip` | -0.22pp | 0.4531 | 0.6797 |

Minimum q over the field: **0.1719**

## Verdict (PLAN section 4 decision rule: arm - passive > 21.2pp AND BH q<0.10, m=12)

- Any arm beats its own basket's passive by >21.2pp (before the BH check): **NO (null)**.
- Minimum BH q over all 12 cells (against `r47-control-passive`): **0.1719** (nothing survives q<0.10 unless this is below it).
- Decision rule cleared by at least one cell: **NO (null)**.

**Nothing is promoted from this round regardless of outcome -- it is a pre-registered measurement study (PLAN section 4).**


(wrote data/rounds/r47-2026-09/analysis.json)

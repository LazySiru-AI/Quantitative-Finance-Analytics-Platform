# Round 36 -- computed verdict tables

## Cells

| cell | ranked | median adj. excess | worst | hit rate | IQR | trades | mean exposure | windows |
|---|---|---|---|---|---|---|---|---|
| `r36-volunits-k4` | yes | +0.36pp | -4.58pp | 0.500 | +3.39pp | 229 | 0.278 | 8/8 |
| `r36-strong-k4` | yes | -0.24pp | -3.83pp | 0.375 | +3.43pp | 229 | 0.279 | 8/8 |
| `r36-reversed-k4` | yes | -0.88pp | -4.58pp | 0.250 | +2.68pp | 237 | 0.277 | 8/8 |
| `r36-canonical-k4` | yes | -1.14pp | -4.27pp | 0.250 | +3.36pp | 236 | 0.278 | 8/8 |
| `r36-weak-k4` | yes | -1.24pp | -5.55pp | 0.375 | +5.12pp | 244 | 0.277 | 8/8 |
| `r36-volunits-k2` | yes | -1.36pp | -16.50pp | 0.250 | +5.63pp | 134 | 0.340 | 8/8 |
| `r36-canonical-k2` | yes | -1.88pp | -21.29pp | 0.250 | +7.45pp | 143 | 0.340 | 8/8 |
| `r36-reversed-k2` | yes | -2.01pp | -9.61pp | 0.250 | +4.39pp | 136 | 0.340 | 8/8 |
| `r36-strong-k2` | yes | -2.18pp | -9.03pp | 0.125 | +3.58pp | 132 | 0.340 | 8/8 |
| `r36-weak-k2` | yes | -3.40pp | -24.17pp | 0.250 | +7.54pp | 153 | 0.339 | 8/8 |

## Per-window adjusted excess

| cell | q4-2018 | covid | bear-2022 | chop-2015 | chop-2011 | bull-2024 | recent | gfc |
|---|---|---|---|---|---|---|---|---|
| `r36-canonical-k2` | -2.34pp | +0.96pp | +13.49pp | -4.28pp | -1.41pp | -0.51pp | -17.50pp | -21.29pp |
| `r36-canonical-k4` | -0.55pp | +1.63pp | +3.54pp | -1.73pp | -3.17pp | -0.36pp | -3.38pp | -4.27pp |
| `r36-reversed-k2` | -0.30pp | +0.29pp | +9.12pp | -2.08pp | -5.06pp | -1.94pp | -4.37pp | -9.61pp |
| `r36-reversed-k4` | -0.28pp | +1.24pp | +3.65pp | -2.03pp | -3.75pp | -0.12pp | -1.47pp | -4.58pp |
| `r36-strong-k2` | -0.85pp | -0.23pp | +10.81pp | -1.02pp | -3.58pp | -3.33pp | -6.34pp | -9.03pp |
| `r36-strong-k4` | -0.27pp | +1.24pp | +3.39pp | -2.47pp | -3.32pp | +0.58pp | -0.20pp | -3.83pp |
| `r36-volunits-k2` | -0.89pp | +0.14pp | +9.34pp | -0.96pp | -3.97pp | -1.76pp | -16.50pp | -13.14pp |
| `r36-volunits-k4` | -0.27pp | +1.24pp | +3.61pp | -1.42pp | -4.06pp | +1.51pp | +1.00pp | -4.58pp |
| `r36-weak-k2` | -1.46pp | +1.55pp | +13.34pp | -3.73pp | -6.06pp | -3.07pp | -14.78pp | -24.17pp |
| `r36-weak-k4` | -0.28pp | +1.88pp | +3.65pp | -2.21pp | -4.23pp | +0.29pp | -5.55pp | -5.07pp |

## Contrasts (PLAN §5 decision rule)

| contrast | median diff | mean paired diff | sign agreement (a>b / a<b of 8) | p (sign-flip) | inside floor? |
|---|---|---|---|---|---|
| `strong - weak` @ k2 | +1.22pp | +3.10pp | 5 / 3 | 0.1953 | yes |
| `canonical - reversed` @ k2 | +0.13pp | -2.37pp | 4 / 4 | 0.4062 | yes |
| `strong - volunits` @ k2 | -0.82pp | +1.77pp | 5 / 3 | 0.2891 | yes |
| `strong - canonical` @ k2 | -0.30pp | +2.41pp | 4 / 4 | 0.3828 | yes |
| `strong - weak` @ k4 | +1.01pp | +0.83pp | 5 / 3 | 0.2109 | yes |
| `canonical - reversed` @ k4 | -0.26pp | -0.12pp | 4 / 4 | 0.8594 | yes |
| `strong - volunits` @ k4 | -0.60pp | -0.24pp | 2 / 4 | 0.4062 | yes |
| `strong - canonical` @ k4 | +0.90pp | +0.43pp | 4 / 4 | 0.4453 | yes |

Five-ordering spread inside each arm: k2 **2.04pp**, k4 **1.60pp** (pure-noise E[max-min] at sigma=21.2 over 5: 49.3pp).

BH over all 10 cells (m=10) against `r36-weak-k2`: q for `r36-strong-k2` = **0.4018**
BH over all 10 cells (m=10) against `r36-weak-k4`: q for `r36-strong-k4` = **0.5208**

## Does the cap bind? Distinct per-window results among the five orderings (PLAN §8)

| arm | q4-2018 | covid | bear-2022 | chop-2015 | chop-2011 | bull-2024 | recent | gfc |
|---|---|---|---|---|---|---|---|---|
| k2 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 |
| k4 | 3 | 3 | 4 | 5 | 5 | 5 | 5 | 4 |

Mean capital exposure (ceiling 0.50): `r36-canonical-k2` 0.340, `r36-reversed-k2` 0.340, `r36-strong-k2` 0.340, `r36-weak-k2` 0.339, `r36-volunits-k2` 0.340, `r36-canonical-k4` 0.278, `r36-reversed-k4` 0.277, `r36-strong-k4` 0.279, `r36-weak-k4` 0.277, `r36-volunits-k4` 0.278

## Predictions (PLAN §7)

1. |canonical - reversed| < 5pp at both caps: **HELD** (k2 +0.13pp, k4 -0.26pp).
2. strong - weak inside 21.2pp at both caps: **HELD** (k2 +1.22pp, k4 +1.01pp).
3. k2 ordering spread > k4: **HELD** (2.04pp vs 1.60pp).
4. strong's worst window is covid and strong <= weak there: worst = {'k2': 'gfc', 'k4': 'gfc'}; covid strong<=weak = {'k2': True, 'k4': True}.
5. Cap binds in >= 5/8 windows at k2 (>= 2 distinct results): **HELD** (8/8).
6. All 10 cells at 8/8: **HELD** (10/10).



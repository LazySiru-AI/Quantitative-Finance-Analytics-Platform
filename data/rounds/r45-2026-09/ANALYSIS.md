# Round 45 -- computed verdict tables

**Not investment advice.** Price-only bars, no dividends. Nothing in this round is promotable (`trading` purpose, PROTOCOL.md r21 amendment) -- report only. Every vault draft behind `bee` and `creator-b` has `published = null`; hindsight against this round's eight windows is unbounded -- see ROUND-45-PLAN.md section 6.

## Cells

| cell | ranked | median adj. excess | worst | hit rate | IQR | trades | mean exposure | windows |
|---|---|---|---|---|---|---|---|---|
| `r45-kim-base` | yes | +4.01pp | -17.21pp | 0.750 | +8.26pp | 202 | 0.126 | 8/8 |
| `r45-kim-rr5` | yes | +4.01pp | -17.21pp | 0.750 | +7.65pp | 202 | 0.121 | 8/8 |
| `r45-bee-rr5` | yes | +3.02pp | -8.88pp | 0.500 | +15.84pp | 160 | 0.237 | 8/8 |
| `r45-kim-trim115` | yes | +2.88pp | -17.21pp | 0.625 | +7.40pp | 202 | 0.095 | 8/8 |
| `r45-kim-risk1pct` | yes | +2.66pp | -11.41pp | 0.750 | +5.70pp | 200 | 0.082 | 8/8 |
| `r45-bee-base` | yes | +2.38pp | -8.90pp | 0.625 | +11.12pp | 164 | 0.212 | 8/8 |
| `r45-bee-trim115` | yes | +2.09pp | -9.70pp | 0.625 | +7.85pp | 173 | 0.178 | 8/8 |
| `r45-bee-risk1pct` | yes | +1.79pp | -7.25pp | 0.625 | +9.16pp | 164 | 0.173 | 8/8 |
| `r45-kim-trend100` | yes | +0.04pp | -3.94pp | 0.500 | +3.45pp | 63 | 0.046 | 8/8 |
| `r45-wsaj-trim115` | yes | -0.60pp | -13.95pp | 0.375 | +6.37pp | 158 | 0.145 | 8/8 |
| `r45-wsaj-risk1pct` | yes | -0.79pp | -5.69pp | 0.250 | +2.85pp | 115 | 0.070 | 8/8 |
| `r45-wsaj-trend100` | yes | -0.83pp | -8.52pp | 0.500 | +7.91pp | 71 | 0.112 | 8/8 |
| `r45-wsaj-base` | yes | -2.07pp | -13.66pp | 0.375 | +5.67pp | 114 | 0.172 | 8/8 |
| `r45-wsaj-rr5` | yes | -2.07pp | -13.66pp | 0.375 | +5.67pp | 114 | 0.172 | 8/8 |

## Per-window adjusted excess

| cell | q4-2018 | covid | bear-2022 | chop-2015 | chop-2011 | bull-2024 | recent | gfc |
|---|---|---|---|---|---|---|---|---|
| `r45-bee-base` | -0.49pp | +15.18pp | -8.88pp | +7.79pp | +10.76pp | -8.90pp | +1.71pp | +3.06pp |
| `r45-bee-risk1pct` | -0.42pp | +12.38pp | -7.25pp | +6.39pp | +8.94pp | -7.25pp | +1.01pp | +2.57pp |
| `r45-bee-rr5` | -0.49pp | +17.90pp | -8.88pp | +6.29pp | +12.92pp | -8.42pp | +14.70pp | -0.26pp |
| `r45-bee-trim115` | -0.49pp | +6.27pp | -5.47pp | +3.39pp | +8.19pp | -9.70pp | +0.79pp | +6.06pp |
| `r45-kim-base` | -3.58pp | +4.38pp | +1.31pp | +3.65pp | +9.90pp | +7.84pp | +22.38pp | -17.21pp |
| `r45-kim-risk1pct` | -2.35pp | +2.90pp | +0.85pp | +2.41pp | +6.56pp | +5.48pp | +14.73pp | -11.41pp |
| `r45-kim-rr5` | -3.58pp | +4.38pp | +1.31pp | +3.65pp | +10.02pp | +6.98pp | +17.10pp | -17.21pp |
| `r45-kim-trend100` | +0.00pp | +4.38pp | -0.32pp | +0.08pp | +1.96pp | -2.59pp | +10.76pp | -3.94pp |
| `r45-kim-trim115` | -3.58pp | +2.39pp | +3.37pp | -0.39pp | +10.85pp | +4.67pp | +12.20pp | -17.21pp |
| `r45-wsaj-base` | +0.46pp | -3.29pp | -1.23pp | -2.90pp | -13.66pp | +6.76pp | +15.41pp | -4.67pp |
| `r45-wsaj-risk1pct` | -0.00pp | -3.02pp | -0.34pp | -1.23pp | -5.69pp | +2.80pp | +5.08pp | -1.86pp |
| `r45-wsaj-rr5` | +0.46pp | -3.29pp | -1.23pp | -2.90pp | -13.66pp | +6.76pp | +15.41pp | -4.67pp |
| `r45-wsaj-trend100` | -8.52pp | -5.02pp | +2.62pp | -4.30pp | -4.28pp | +3.08pp | +16.24pp | +4.46pp |
| `r45-wsaj-trim115` | +2.80pp | -0.94pp | -1.81pp | -0.26pp | -13.95pp | +5.55pp | +12.62pp | -6.12pp |

## Arm minus OWN base (PLAN decision rule input)

| base | enhancement | whose component | arm median | base median | arm - base | windows arm>base | p (sign-flip) | clears 21.2pp floor? |
|---|---|---|---|---|---|---|---|---|
| kim (Creator E (creator-e)) | `trend100` | Creator C (creator-c) | +0.04pp | +4.01pp | -3.97pp | 2/8 | 0.5000 | no |
| kim (Creator E (creator-e)) | `rr5` | Creator B (creator-b) | +4.01pp | +4.01pp | +0.00pp | 1/8 | 0.5000 | no |
| kim (Creator E (creator-e)) | `risk1pct` | Creator E (creator-e) | +2.66pp | +4.01pp | -1.35pp | 2/8 | 0.4141 | no |
| kim (Creator E (creator-e)) | `trim115` | Creator B (creator-b) | +2.88pp | +4.01pp | -1.13pp | 2/8 | 0.1719 | no |
| bee (Creator C (creator-c)) | `rr5` | Creator B (creator-b) | +3.02pp | +2.38pp | +0.63pp | 4/8 | 0.4688 | no |
| bee (Creator C (creator-c)) | `risk1pct` | Creator E (creator-e) | +1.79pp | +2.38pp | -0.59pp | 3/8 | 0.3984 | no |
| bee (Creator C (creator-c)) | `trim115` | Creator B (creator-b) | +2.09pp | +2.38pp | -0.29pp | 2/8 | 0.3750 | no |
| creator-b (Creator B (creator-b)) | `trend100` | Creator C (creator-c) | -0.83pp | -2.07pp | +1.24pp | 4/8 | 0.7266 | no |
| creator-b (Creator B (creator-b)) | `rr5` | Creator B (creator-b) | -2.07pp | -2.07pp | +0.00pp | 0/8 | 1.0000 | no |
| creator-b (Creator B (creator-b)) | `risk1pct` | Creator E (creator-e) | -0.79pp | -2.07pp | +1.28pp | 5/8 | 0.9453 | no |
| creator-b (Creator B (creator-b)) | `trim115` | Creator B (creator-b) | -0.60pp | -2.07pp | +1.47pp | 3/8 | 0.8516 | no |

## Enhancement marginals (mean over its bases of arm-minus-own-base median)

| enhancement | whose component | bases | marginal | clears 21.2pp floor? |
|---|---|---|---|---|
| `trend100` | Creator C (creator-c) | kim, creator-b | -1.37pp | no |
| `rr5` | Creator B (creator-b) | kim, bee, creator-b | +0.21pp | no |
| `risk1pct` | Creator E (creator-e) | kim, bee, creator-b | -0.22pp | no |
| `trim115` | Creator B (creator-b) | kim, bee, creator-b | +0.01pp | no |

## BH over all 14 cells (m=14) -- each arm contrasted with its OWN base

| cell | base | median diff | p (sign-flip) | q (BH, m=14) |
|---|---|---|---|---|
| `r45-kim-base` | r45-kim-base | +0.00pp |  |  |
| `r45-kim-trend100` | r45-kim-base | -3.97pp | 0.5000 | 1.0000 |
| `r45-kim-rr5` | r45-kim-base | +0.00pp | 0.5000 | 1.0000 |
| `r45-kim-risk1pct` | r45-kim-base | -1.35pp | 0.4141 | 1.0000 |
| `r45-kim-trim115` | r45-kim-base | -1.13pp | 0.1719 | 1.0000 |
| `r45-bee-base` | r45-bee-base | +0.00pp |  |  |
| `r45-bee-rr5` | r45-bee-base | +0.63pp | 0.4688 | 1.0000 |
| `r45-bee-risk1pct` | r45-bee-base | -0.59pp | 0.3984 | 1.0000 |
| `r45-bee-trim115` | r45-bee-base | -0.29pp | 0.3750 | 1.0000 |
| `r45-wsaj-base` | r45-wsaj-base | +0.00pp |  |  |
| `r45-wsaj-trend100` | r45-wsaj-base | +1.24pp | 0.7266 | 1.0000 |
| `r45-wsaj-rr5` | r45-wsaj-base | +0.00pp | 1.0000 | 1.0000 |
| `r45-wsaj-risk1pct` | r45-wsaj-base | +1.28pp | 0.9453 | 1.0000 |
| `r45-wsaj-trim115` | r45-wsaj-base | +1.47pp | 0.8516 | 1.0000 |

Minimum q over the field: **1.0000**

## Verdict per enhancement (PLAN decision rule: marginal > 21.2pp AND every arm cell q<0.10)

- `trend100`: marginal -1.37pp (inside the 21.2pp floor); arm q-values ['1.0000', '1.0000'] (not all < 0.10) -> **NULL**.
- `rr5`: marginal +0.21pp (inside the 21.2pp floor); arm q-values ['1.0000', '1.0000', '1.0000'] (not all < 0.10) -> **NULL**.
- `risk1pct`: marginal -0.22pp (inside the 21.2pp floor); arm q-values ['1.0000', '1.0000', '1.0000'] (not all < 0.10) -> **NULL**.
- `trim115`: marginal +0.01pp (inside the 21.2pp floor); arm q-values ['1.0000', '1.0000', '1.0000'] (not all < 0.10) -> **NULL**.

**Any enhancement earns something by the pre-registered rule: NO (null on all four)**.

## `rr5` take-profit exit tally (from run files' trade logs, across the 8 main windows)

| cell | target exits | total exits | fraction target | < 10% (pre-registered)? |
|---|---|---|---|---|
| `r45-kim-rr5` | 4 | 202 | 2.0% | YES |
| `r45-bee-rr5` | 4 | 160 | 2.5% | YES |
| `r45-wsaj-rr5` | 0 | 114 | 0.0% | YES |

## Trade counts and mean exposure per cell

| cell | trades | mean exposure | adjusted excess per unit exposure |
|---|---|---|---|
| `r45-bee-base` | 164 | 0.212 | +11.26pp |
| `r45-bee-risk1pct` | 164 | 0.173 | +10.36pp |
| `r45-bee-rr5` | 160 | 0.237 | +12.75pp |
| `r45-bee-trim115` | 173 | 0.178 | +11.74pp |
| `r45-kim-base` | 202 | 0.126 | +31.81pp |
| `r45-kim-risk1pct` | 200 | 0.082 | +32.33pp |
| `r45-kim-rr5` | 202 | 0.121 | +33.24pp |
| `r45-kim-trend100` | 63 | 0.046 | +0.92pp |
| `r45-kim-trim115` | 202 | 0.095 | +30.20pp |
| `r45-wsaj-base` | 114 | 0.172 | -12.03pp |
| `r45-wsaj-risk1pct` | 115 | 0.070 | -11.24pp |
| `r45-wsaj-rr5` | 114 | 0.172 | -12.03pp |
| `r45-wsaj-trend100` | 71 | 0.112 | -7.43pp |
| `r45-wsaj-trim115` | 158 | 0.145 | -4.14pp |

## Predictions (PLAN)

1. Null for all four enhancements: **HELD**.
2. `trend100` cuts trades vs base on kim and creator-b: **HELD** ({'kim': True, 'creator-b': True}).
3. Fewer than 10% of `rr5` exits are the take-profit target: **HELD** ({'r45-kim-rr5': True, 'r45-bee-rr5': True, 'r45-wsaj-rr5': True}).
4. `risk1pct` lowers mean exposure and raises adjusted excess per unit exposure without flipping the per-window sign pattern: {'kim': {'exposure_lower': True, 'adjusted_excess_per_unit_higher': True, 'sign_matches': '8/8'}, 'bee': {'exposure_lower': True, 'adjusted_excess_per_unit_higher': False, 'sign_matches': '8/8'}, 'creator-b': {'exposure_lower': True, 'adjusted_excess_per_unit_higher': True, 'sign_matches': '7/8'}}.
5. `trim115` lowers exposure and loses to base in bull-2024 and recent: **HELD** ({'kim': {'exposure_lower': True, 'loses_bull_2024': True, 'loses_recent': True}, 'bee': {'exposure_lower': True, 'loses_bull_2024': True, 'loses_recent': True}, 'creator-b': {'exposure_lower': True, 'loses_bull_2024': True, 'loses_recent': True}}).

Nothing in this round is promotable regardless of outcome (`trading` purpose, PROTOCOL.md r21 amendment) -- these are measurement results only. Not investment advice.


(wrote data/rounds/r45-2026-09/analysis.json)

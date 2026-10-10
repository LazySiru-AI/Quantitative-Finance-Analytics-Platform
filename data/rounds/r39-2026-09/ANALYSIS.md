# Round 39 -- computed verdict tables

## Cells (ranked on median adjusted excess vs SPY)

| cell | ranked | median adj. excess | worst | hit rate | IQR | trades | mean exposure | windows |
|---|---|---|---|---|---|---|---|---|
| `r39-growth-passive` | yes | +3.16pp | -6.34pp | 0.500 | +14.90pp | 16 | 0.834 | 8/8 |
| `r39-core-passive` | yes | +2.79pp | -9.64pp | 0.625 | +7.52pp | 16 | 0.826 | 8/8 |
| `r39-full-passive` | yes | +1.24pp | -5.70pp | 0.750 | +2.23pp | 56 | 0.799 | 8/8 |
| `r39-core-ma` | yes | -0.66pp | -4.56pp | 0.250 | +4.05pp | 32 | 0.180 | 8/8 |
| `r39-full-ma` | yes | -1.04pp | -4.53pp | 0.125 | +3.41pp | 99 | 0.142 | 8/8 |
| `r39-value-ma` | yes | -1.34pp | -8.07pp | 0.000 | +2.08pp | 36 | 0.124 | 8/8 |
| `r39-growth-ma` | yes | -2.20pp | -5.12pp | 0.125 | +3.06pp | 31 | 0.166 | 8/8 |
| `r39-value-passive` | yes | -2.27pp | -5.87pp | 0.250 | +3.97pp | 24 | 0.815 | 8/8 |

## Per-window adjusted excess

| cell | q4-2018 | covid | bear-2022 | chop-2015 | chop-2011 | bull-2024 | recent | gfc |
|---|---|---|---|---|---|---|---|---|
| `r39-core-ma` | +0.00pp | +3.44pp | +0.00pp | -2.84pp | -1.32pp | -4.56pp | -4.24pp | +5.98pp |
| `r39-core-passive` | +7.27pp | +4.97pp | +2.60pp | -0.80pp | +2.98pp | -5.48pp | -9.64pp | +21.55pp |
| `r39-full-ma` | -0.37pp | +3.76pp | -0.06pp | -1.72pp | -4.53pp | -4.00pp | -3.31pp | -0.08pp |
| `r39-full-passive` | +0.90pp | +2.14pp | +2.27pp | -2.94pp | +1.41pp | -5.70pp | +1.07pp | +8.46pp |
| `r39-growth-ma` | -0.00pp | +10.25pp | +0.00pp | -1.56pp | -2.85pp | -3.06pp | -5.12pp | -3.09pp |
| `r39-growth-passive` | -2.55pp | +11.39pp | -1.60pp | -6.34pp | +7.92pp | -5.63pp | +12.15pp | +12.43pp |
| `r39-value-ma` | -0.83pp | +0.00pp | -0.15pp | -1.33pp | -8.07pp | -5.15pp | -1.35pp | -1.94pp |
| `r39-value-passive` | -0.77pp | -5.66pp | +4.82pp | -2.48pp | -3.92pp | -5.87pp | +0.80pp | -2.06pp |

## Tilt minus control -- does the timing rule beat holding the slice? (PLAN decision rule)

| slice | ma median | passive median | ma - passive | windows ma>passive | p (sign-flip) | inside floor? |
|---|---|---|---|---|---|---|
| value | -1.34pp | -2.27pp | +0.93pp | 4/8 | 0.7422 | yes |
| growth | -2.20pp | +3.16pp | -5.36pp | 4/8 | 0.2500 | yes |
| core | -0.66pp | +2.79pp | -3.45pp | 2/8 | 0.1562 | yes |
| full | -1.04pp | +1.24pp | -2.28pp | 3/8 | 0.1562 | yes |

## Style spread: value-passive - growth-passive = **-5.43pp** (inside the 21.2pp floor; value>growth in 3/8 windows, p=0.1406)

BH over all 8 cells (m=8) against `r39-full-passive`: minimum q = **0.3281**

## Verdict (PLAN decision rule)

- Every within-slice tilt-minus-control inside 21.2pp: **HELD (null)** -- the timing rule adds nothing over holding the slice.
- Style spread inside 21.2pp: **HELD (null)**.
- Minimum BH q 0.3281 (nothing survives q<0.10).
- Worst window per cell: `core-ma`->bull-2024, `core-passive`->recent, `full-ma`->chop-2011, `full-passive`->bull-2024, `growth-ma`->recent, `growth-passive`->chop-2015, `value-ma`->chop-2011, `value-passive`->bull-2024.

**Nothing clears the floor; the rule arms lose to their own passive controls (the ma timing sits in cash while the slice rises). Null on both questions.**



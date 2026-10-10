# Round 35 -- computed verdict tables

## Cells (ranked on median adjusted excess vs SPY)

| cell | ranked | median adj. excess | worst | hit rate | IQR | trades | mean exposure | windows |
|---|---|---|---|---|---|---|---|---|
| `r35-macross-4-rank` | yes | -2.21pp | -9.87pp | 0.250 | +7.57pp | 80 | 0.175 | 8/8 |
| `r35-passive-8-order` | yes | -2.28pp | -15.58pp | 0.375 | +7.47pp | 64 | 0.862 | 8/8 |
| `r35-absolute-4-order` | yes | -2.38pp | -16.98pp | 0.375 | +7.19pp | 204 | 0.392 | 8/8 |
| `r35-macross-4-order` | yes | -2.86pp | -9.87pp | 0.125 | +6.44pp | 80 | 0.174 | 8/8 |
| `r35-absolute-4-rank` | yes | -3.51pp | -17.77pp | 0.375 | +7.35pp | 194 | 0.393 | 8/8 |
| `r35-macross-2-order` | yes | -4.60pp | -11.54pp | 0.125 | +8.13pp | 55 | 0.221 | 8/8 |
| `r35-macross-2-rank` | yes | -4.60pp | -11.54pp | 0.250 | +9.46pp | 56 | 0.222 | 8/8 |
| `r35-absolute-2-order` | yes | -6.28pp | -17.96pp | 0.125 | +5.73pp | 117 | 0.442 | 8/8 |
| `r35-absolute-2-rank` | yes | -7.82pp | -17.83pp | 0.250 | +11.86pp | 109 | 0.442 | 8/8 |

## Per-window adjusted excess

| cell | q4-2018 | covid | bear-2022 | chop-2015 | chop-2011 | bull-2024 | recent | gfc |
|---|---|---|---|---|---|---|---|---|
| `r35-absolute-2-order` | -1.90pp | +0.04pp | -11.72pp | -10.31pp | -17.96pp | -5.95pp | -6.40pp | -6.15pp |
| `r35-absolute-2-rank` | -1.84pp | +0.04pp | -11.78pp | -11.06pp | -17.60pp | -4.59pp | +15.54pp | -17.83pp |
| `r35-absolute-4-order` | +1.36pp | +0.51pp | -6.35pp | -3.23pp | -16.98pp | -6.85pp | +8.37pp | -1.54pp |
| `r35-absolute-4-rank` | +1.36pp | +0.51pp | -6.35pp | -2.30pp | -17.77pp | -7.47pp | +7.32pp | -4.72pp |
| `r35-macross-2-order` | +0.25pp | +0.00pp | -11.54pp | -5.92pp | -10.86pp | -9.06pp | -1.83pp | -3.29pp |
| `r35-macross-2-rank` | +0.25pp | +0.00pp | -11.54pp | -5.92pp | -10.41pp | -9.06pp | +1.99pp | -3.29pp |
| `r35-macross-4-order` | +0.13pp | +0.00pp | -7.43pp | -2.95pp | -9.87pp | -7.87pp | -2.78pp | -1.47pp |
| `r35-macross-4-rank` | +0.13pp | +0.00pp | -7.43pp | -2.95pp | -9.87pp | -7.87pp | +2.47pp | -1.47pp |
| `r35-passive-8-order` | +4.07pp | -4.46pp | +0.24pp | -11.37pp | -15.58pp | -0.10pp | +11.42pp | -4.57pp |

## Rotation minus control (`r35-passive-8-order`) -- the pre-registered reported quantity

| cell | median vs SPY | median minus control | windows > control | p (sign-flip) |
|---|---|---|---|---|
| `r35-absolute-2-order` | -6.28pp | -3.99pp | 2/8 | 0.0781 |
| `r35-absolute-2-rank` | -7.82pp | -5.54pp | 3/8 | 0.1875 |
| `r35-absolute-4-order` | -2.38pp | -0.10pp | 3/8 | 0.7812 |
| `r35-absolute-4-rank` | -3.51pp | -1.23pp | 2/8 | 0.5781 |
| `r35-macross-2-order` | -4.60pp | -2.32pp | 4/8 | 0.3516 |
| `r35-macross-2-rank` | -4.60pp | -2.32pp | 4/8 | 0.4219 |
| `r35-macross-4-order` | -2.86pp | -0.58pp | 4/8 | 0.6016 |
| `r35-macross-4-rank` | -2.21pp | +0.08pp | 4/8 | 0.7344 |

BH over all 9 cells (m=9) against the control: minimum q = **0.7031**

## Predictions (PLAN §5)

1. Every rotation cell negative vs SPY: **HELD**.
2. No rotation cell beats the control by > 21.2pp: **HELD** (max = +0.08pp).
3. Failure regimes: macross worst-two = {'r35-macross-2-order': ['bear-2022', 'chop-2011'], 'r35-macross-2-rank': ['bear-2022', 'chop-2011'], 'r35-macross-4-order': ['chop-2011', 'bull-2024'], 'r35-macross-4-rank': ['chop-2011', 'bull-2024']}; absolute worst = {'r35-absolute-2-order': 'chop-2011', 'r35-absolute-2-rank': 'gfc', 'r35-absolute-4-order': 'chop-2011', 'r35-absolute-4-rank': 'chop-2011'}; control worst = chop-2011.
4. Fill orders differ < 21.2pp: marginal rank -4.54pp vs order -4.03pp (spread 0.50pp); matched pairs: r35-absolute-2-rank: -1.55pp, r35-absolute-4-rank: -1.13pp, r35-macross-2-rank: +0.00pp, r35-macross-4-rank: +0.65pp.
5. 2-slot IQR wider than 4-slot: mean IQR k2 +8.80pp vs k4 +7.14pp -> **HELD**.
6. Control validity: trades per window {'q4-2018': 8, 'covid': 8, 'bear-2022': 8, 'chop-2015': 8, 'chop-2011': 8, 'bull-2024': 8, 'recent': 8, 'gfc': 8}; session exposure {'q4-2018': 1.0, 'covid': 1.0, 'bear-2022': 1.0, 'chop-2015': 1.0, 'chop-2011': 1.0, 'bull-2024': 1.0, 'recent': 1.0, 'gfc': 1.0}.



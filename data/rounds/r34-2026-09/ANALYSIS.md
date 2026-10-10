# Round 34 -- computed verdict tables

## Cells (ranked on median adjusted excess)

| cell | ranked | median adj. excess | worst | hit rate | IQR | trades | mean exposure | windows |
|---|---|---|---|---|---|---|---|---|
| `r34-ma-crossover-on` | yes | +1.24pp | -9.95pp | 0.625 | +12.89pp | 101 | 0.238 | 8/8 |
| `r34-macd-cross-on` | yes | +0.80pp | -9.69pp | 0.500 | +5.94pp | 239 | 0.207 | 8/8 |
| `r34-momentum-state-on` | yes | -0.02pp | -18.86pp | 0.500 | +8.65pp | 165 | 0.426 | 8/8 |
| `r34-band-breakout-off` | yes | -0.63pp | -10.73pp | 0.500 | +10.63pp | 149 | 0.298 | 8/8 |
| `r34-channel-breakout-off` | yes | -1.31pp | -9.73pp | 0.375 | +10.71pp | 88 | 0.435 | 8/8 |
| `r34-band-reversion-off` | yes | -1.57pp | -8.51pp | 0.500 | +10.32pp | 209 | 0.345 | 8/8 |
| `r34-ma-crossover-off` | yes | -1.69pp | -9.13pp | 0.250 | +5.41pp | 167 | 0.404 | 8/8 |
| `r34-band-reversion-on` | yes | -2.40pp | -6.15pp | 0.250 | +2.56pp | 70 | 0.126 | 8/8 |
| `r34-channel-breakout-on` | yes | -2.49pp | -10.71pp | 0.375 | +5.78pp | 71 | 0.320 | 8/8 |
| `r34-momentum-state-off` | yes | -2.71pp | -10.46pp | 0.250 | +5.72pp | 194 | 0.495 | 8/8 |
| `r34-rsi-pullback-on` | yes | -2.73pp | -9.37pp | 0.250 | +3.18pp | 129 | 0.244 | 8/8 |
| `r34-vol-compression-on` | yes | -3.81pp | -10.83pp | 0.125 | +7.42pp | 111 | 0.320 | 8/8 |
| `r34-rsi-pullback-off` | yes | -4.13pp | -24.04pp | 0.250 | +13.60pp | 258 | 0.511 | 8/8 |
| `r34-macd-cross-off` | yes | -4.55pp | -12.48pp | 0.250 | +7.15pp | 371 | 0.443 | 8/8 |
| `r34-vol-compression-off` | yes | -5.06pp | -10.19pp | 0.125 | +7.46pp | 123 | 0.381 | 8/8 |
| `r34-band-breakout-on` | yes | -5.17pp | -11.54pp | 0.250 | +5.58pp | 125 | 0.232 | 8/8 |

## Per-window adjusted excess

| cell | q4-2018 | covid | bear-2022 | chop-2015 | chop-2011 | bull-2024 | recent | gfc |
|---|---|---|---|---|---|---|---|---|
| `r34-band-breakout-off` | -2.39pp | +9.49pp | +2.06pp | +1.12pp | -6.03pp | -10.73pp | +9.31pp | -8.95pp |
| `r34-band-breakout-on` | -0.90pp | +3.21pp | -5.09pp | -5.25pp | -5.61pp | -11.54pp | +9.31pp | -5.39pp |
| `r34-band-reversion-off` | -8.51pp | -4.44pp | +7.60pp | -3.76pp | +6.30pp | +0.61pp | +6.59pp | -3.78pp |
| `r34-band-reversion-on` | -1.98pp | -2.77pp | -3.42pp | -2.04pp | -6.15pp | +1.89pp | +4.54pp | -4.02pp |
| `r34-channel-breakout-off` | -4.74pp | +9.99pp | -2.02pp | -0.59pp | +5.32pp | -5.26pp | +7.43pp | -9.73pp |
| `r34-channel-breakout-on` | -1.54pp | +1.00pp | +2.17pp | -6.43pp | -3.43pp | -10.71pp | +7.43pp | -3.84pp |
| `r34-ma-crossover-off` | -0.78pp | +19.06pp | +8.56pp | -1.30pp | -2.07pp | -9.13pp | -2.89pp | -6.78pp |
| `r34-ma-crossover-on` | +1.25pp | +6.09pp | +9.73pp | -8.28pp | -6.84pp | -9.95pp | +1.22pp | +5.55pp |
| `r34-macd-cross-off` | +5.58pp | +26.33pp | -0.17pp | -4.14pp | -4.96pp | -5.14pp | -8.12pp | -12.48pp |
| `r34-macd-cross-on` | -0.09pp | +1.68pp | +7.26pp | -5.65pp | -2.89pp | -9.69pp | +3.08pp | +2.12pp |
| `r34-momentum-state-off` | -1.42pp | +12.99pp | +3.37pp | -4.00pp | -10.46pp | -5.63pp | -0.31pp | -4.94pp |
| `r34-momentum-state-on` | +0.62pp | +5.47pp | -0.07pp | -9.74pp | -18.86pp | -6.55pp | +0.02pp | +3.38pp |
| `r34-rsi-pullback-off` | -2.97pp | -5.29pp | -0.86pp | -20.18pp | -9.62pp | +7.95pp | +10.34pp | -24.04pp |
| `r34-rsi-pullback-on` | -2.89pp | -9.37pp | -1.57pp | -2.93pp | -6.97pp | -2.57pp | +5.71pp | +1.66pp |
| `r34-vol-compression-off` | -4.61pp | -8.91pp | -5.51pp | -9.33pp | +2.56pp | -10.19pp | -1.51pp | -1.56pp |
| `r34-vol-compression-on` | -1.96pp | -8.67pp | -5.09pp | -10.83pp | -0.36pp | -9.91pp | -2.54pp | +0.26pp |

## Marginals (PLAN §5: a factor matters only if its marginal spread exceeds 21.2pp)

| form | marginal (mean of 2 cells) |
|---|---|
| `ma-crossover` | -0.22pp |
| `momentum-state` | -1.37pp |
| `macd-cross` | -1.88pp |
| `channel-breakout` | -1.90pp |
| `band-reversion` | -1.99pp |
| `band-breakout` | -2.90pp |
| `rsi-pullback` | -3.43pp |
| `vol-compression` | -4.44pp |

**Form marginal spread: 4.21pp** -- INSIDE the 21.2pp floor.

Regime filter: on -1.82pp, off -2.71pp -- **spread 0.88pp** (inside the floor).

Whole 16-cell field spread: **6.40pp** (pure-noise expectation at sigma=21.2: 74.9pp).

## BH over all 16 cells, each contrasted with the worst cell `r34-band-breakout-on`

| cell | median diff vs worst | p (sign-flip) | q (BH, m=16) |
|---|---|---|---|
| `r34-ma-crossover-on` | +6.40pp | 0.3516 | 0.8125 |
| `r34-macd-cross-on` | +5.96pp | 0.3203 | 0.8125 |
| `r34-momentum-state-on` | +5.14pp | 0.8516 | 0.9583 |
| `r34-band-breakout-off` | +4.53pp | 0.2188 | 0.8125 |
| `r34-channel-breakout-off` | +3.86pp | 0.2031 | 0.8125 |
| `r34-band-reversion-off` | +3.60pp | 0.3906 | 0.8125 |
| `r34-ma-crossover-off` | +3.48pp | 0.2734 | 0.8125 |
| `r34-band-reversion-on` | +2.77pp | 0.7500 | 0.9231 |
| `r34-channel-breakout-on` | +2.68pp | 0.6250 | 0.8333 |
| `r34-momentum-state-off` | +2.46pp | 0.5312 | 0.8333 |
| `r34-rsi-pullback-on` | +2.44pp | 0.8984 | 0.9583 |
| `r34-vol-compression-on` | +1.35pp | 0.4062 | 0.8125 |
| `r34-rsi-pullback-off` | +1.04pp | 0.5078 | 0.8333 |
| `r34-macd-cross-off` | +0.62pp | 0.5859 | 0.8333 |
| `r34-vol-compression-off` | +0.11pp | 0.3828 | 0.8125 |
| `r34-band-breakout-on` | +0.00pp |  |  |

Minimum q over the field: **0.8125**

## Predictions (PLAN §6)

1. Form marginal < 21.2pp: **HELD** (4.21pp).
2. Regime marginal < 21.2pp: **HELD** (0.88pp).
3. 16-cell spread vs round 17's stop slice: 6.40pp here (descriptive; compare in REPORT).
4. `vol-compression` takes the fewest trades: **REFUTED** (fewest = `channel-breakout`; trades by form: {'ma-crossover': 268, 'momentum-state': 359, 'rsi-pullback': 387, 'band-reversion': 279, 'channel-breakout': 159, 'band-breakout': 274, 'macd-cross': 610, 'vol-compression': 234}).
5. Trend/momentum forms worst in a chop window: `r34-ma-crossover-on`->bull-2024, `r34-ma-crossover-off`->bull-2024, `r34-momentum-state-on`->chop-2011*, `r34-momentum-state-off`->chop-2011*, `r34-macd-cross-on`->bull-2024, `r34-macd-cross-off`->gfc, `r34-vol-compression-on`->chop-2015*, `r34-vol-compression-off`->bull-2024  (* = held).
6. All 16 cells scored in 8/8 windows: **HELD** (16/16).



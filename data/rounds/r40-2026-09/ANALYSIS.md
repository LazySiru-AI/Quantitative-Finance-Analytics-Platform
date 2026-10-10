# Round 40 -- computed verdict tables

## Cells (ranked on median adjusted excess vs SPY)

| cell | ranked | median adj. excess | worst | hit rate | IQR | trades | mean exposure | windows |
|---|---|---|---|---|---|---|---|---|
| `r40-rsi-confirm-slots3` | yes | +5.65pp | -30.73pp | 0.750 | +12.08pp | 171 | 0.213 | 8/8 |
| `r40-rsi-confirm-slots6` | yes | +4.01pp | -17.21pp | 0.750 | +8.26pp | 202 | 0.126 | 8/8 |
| `r40-none-slots6` | yes | -0.81pp | -23.72pp | 0.500 | +23.42pp | 834 | 0.436 | 8/8 |
| `r40-divergence-proxy-negative-control-slots6` | yes | -0.85pp | -25.16pp | 0.500 | +23.31pp | 819 | 0.429 | 8/8 |
| `r40-swing-structure-slots6` | yes | -1.83pp | -5.82pp | 0.000 | +1.08pp | 99 | 0.040 | 8/8 |
| `r40-none-slots3` | yes | -2.18pp | -47.71pp | 0.375 | +26.51pp | 456 | 0.480 | 8/8 |
| `r40-swing-structure-slots3` | yes | -3.67pp | -12.36pp | 0.000 | +2.92pp | 94 | 0.081 | 8/8 |
| `r40-divergence-proxy-negative-control-slots3` | yes | -5.80pp | -45.31pp | 0.375 | +26.55pp | 463 | 0.477 | 8/8 |

## Per-window adjusted excess

| cell | q4-2018 | covid | bear-2022 | chop-2015 | chop-2011 | bull-2024 | recent | gfc |
|---|---|---|---|---|---|---|---|---|
| `r40-divergence-proxy-negative-control-slots3` | -4.05pp | +13.08pp | -23.42pp | +16.18pp | -9.12pp | -7.55pp | +43.84pp | -45.31pp |
| `r40-divergence-proxy-negative-control-slots6` | -10.14pp | +13.18pp | -16.38pp | +11.09pp | -5.59pp | +3.89pp | +43.05pp | -25.16pp |
| `r40-none-slots3` | -4.29pp | +13.08pp | -23.40pp | +18.42pp | -8.33pp | -0.06pp | +53.12pp | -47.71pp |
| `r40-none-slots6` | -9.51pp | +15.28pp | -18.04pp | +10.61pp | -5.08pp | +3.45pp | +46.17pp | -23.72pp |
| `r40-rsi-confirm-slots3` | -5.54pp | +8.83pp | +2.55pp | +8.75pp | +17.13pp | +0.28pp | +29.37pp | -30.73pp |
| `r40-rsi-confirm-slots6` | -3.58pp | +4.38pp | +1.31pp | +3.65pp | +9.90pp | +7.84pp | +22.38pp | -17.21pp |
| `r40-swing-structure-slots3` | -1.47pp | -3.67pp | -0.68pp | -3.81pp | -5.33pp | -0.17pp | -12.36pp | -3.68pp |
| `r40-swing-structure-slots6` | -0.74pp | -1.82pp | -0.34pp | -1.90pp | -2.92pp | -1.19pp | -5.82pp | -1.84pp |

## Arm minus control -- does the added conjunct pay for itself? (PLAN decision rule)

| arm | slots | arm median | control median | arm - control | windows arm>ctrl | p (sign-flip) | trades | clears floor? |
|---|---|---|---|---|---|---|---|---|
| swing-structure | slots3 | -3.67pp | -2.18pp | -1.50pp | 4/8 | 0.8047 | 94 | no |
| rsi-confirm | slots3 | +5.65pp | -2.18pp | +7.82pp | 4/8 | 0.5547 | 171 | no |
| divergence-proxy-negative-control | slots3 | -5.80pp | -2.18pp | -3.63pp | 2/8 | 0.2344 | 463 | no |
| swing-structure | slots6 | -1.83pp | -0.81pp | -1.02pp | 4/8 | 0.6719 | 99 | no |
| rsi-confirm | slots6 | +4.01pp | -0.81pp | +4.82pp | 5/8 | 0.8359 | 202 | no |
| divergence-proxy-negative-control | slots6 | -0.85pp | -0.81pp | -0.04pp | 3/8 | 0.2734 | 819 | no |

BH over all 8 cells (m=8) against `r40-none-slots6`: minimum q = **0.9554**

## Verdict (PLAN decision rule)

- Any conjunct clears 21.2pp arm-minus-control: **NO (null)**. Best arm: `rsi-confirm/slots3` at +7.82pp.
- Divergence negative control ~ none (predicted): slots6 -0.04pp, slots3 -3.63pp -- HELD (indistinguishable at slots6).
- Switched-off screen: min trades across cells = 94 (>0 in every window means measured, not switched off).
- Minimum BH q 0.9554 (nothing survives q<0.10).

**The RSI-confirm arm is the sole positive cell (arm-minus-control +7.82pp at 3 slots, +4.82pp at 6), but both sit well inside the 21.2pp floor -- so by the pre-registered rule the conjunct does NOT pay for itself. Null.**



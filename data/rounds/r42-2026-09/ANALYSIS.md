# Round 42 -- computed verdict tables

**Not investment advice.** Price-only bars, no dividends. Nothing in this round is promotable (`trading` purpose, PROTOCOL.md r21 amendment) -- report only.

## Cells

| cell | ranked | median adj. excess | worst | hit rate | IQR | trades | mean exposure | windows |
|---|---|---|---|---|---|---|---|---|
| `r42-reclaim-control` | yes | +3.55pp | -26.05pp | 0.625 | +24.18pp | 179 | 0.494 | 8/8 |
| `r42-reclaim-wick` | yes | +1.85pp | -22.85pp | 0.625 | +12.09pp | 218 | 0.514 | 8/8 |
| `r42-breakout-q25` | yes | +0.11pp | -16.17pp | 0.500 | +8.93pp | 123 | 0.255 | 8/8 |
| `r42-breakout-control` | yes | -0.89pp | -26.05pp | 0.375 | +12.00pp | 145 | 0.283 | 8/8 |
| `r42-reclaim-wick-body` | yes | -2.33pp | -25.75pp | 0.375 | +16.05pp | 140 | 0.336 | 8/8 |

## Per-window adjusted excess

| cell | q4-2018 | covid | bear-2022 | chop-2015 | chop-2011 | bull-2024 | recent | gfc |
|---|---|---|---|---|---|---|---|---|
| `r42-breakout-control` | -1.51pp | +7.66pp | -0.28pp | +8.78pp | -4.93pp | -3.77pp | +67.13pp | -26.05pp |
| `r42-breakout-q25` | +1.37pp | +7.37pp | -2.29pp | +2.85pp | -12.91pp | -1.16pp | +41.72pp | -16.17pp |
| `r42-reclaim-control` | +0.90pp | +30.64pp | -26.05pp | +15.06pp | +6.20pp | -8.30pp | +27.40pp | -5.28pp |
| `r42-reclaim-wick` | +1.89pp | +43.77pp | -22.85pp | +1.81pp | +3.43pp | -4.86pp | +11.95pp | -11.54pp |
| `r42-reclaim-wick-body` | -2.12pp | +19.81pp | -25.75pp | -8.01pp | -2.53pp | -5.33pp | +26.83pp | +6.80pp |

## Arm minus OWN family control (PLAN decision rule)

| family | arm | slots/exposure trades | arm median | control median | arm - control | windows arm>ctrl | p (sign-flip) | clears 21.2pp floor? |
|---|---|---|---|---|---|---|---|---|
| reclaim (Creator E (creator-e)) | `r42-reclaim-wick` | 218 | +1.85pp | +3.55pp | -1.70pp | 4/8 | 0.5547 | no |
| reclaim (Creator E (creator-e)) | `r42-reclaim-wick-body` | 140 | -2.33pp | +3.55pp | -5.87pp | 3/8 | 0.3906 | no |
| breakout (Creator C (creator-c)) | `r42-breakout-q25` | 123 | +0.11pp | -0.89pp | +1.00pp | 3/8 | 0.4766 | no |

## BH over all 5 cells (m=5) -- the reference control is arbitrary for m; reported against both

Reference `r42-reclaim-control`: minimum q over the field = **1.0000**
Reference `r42-breakout-control`: minimum q over the field = **1.0000**

The reference cell only fixes which contrast column BH is computed against; m stays 5 (every cell run) either way, and the pre-registered per-family contrasts above -- arm minus its OWN control -- are what the decision rule actually reads, not either BH table.

## Trade counts and mean exposure per cell

| cell | trades | mean exposure |
|---|---|---|
| `r42-breakout-control` | 145 | 0.283 |
| `r42-breakout-q25` | 123 | 0.255 |
| `r42-reclaim-control` | 179 | 0.494 |
| `r42-reclaim-wick` | 218 | 0.514 |
| `r42-reclaim-wick-body` | 140 | 0.336 |

## Verdict (PLAN decision rule)

- Any arm clears its own-control 21.2pp floor AND survives BH q<0.10: **NO (null)**.
- Family A trade ordering (wick-body < wick < control), as predicted from each added structural term filtering further: **NOT CONFIRMED / REFUTED** ({'r42-reclaim-control': 179, 'r42-reclaim-wick': 218, 'r42-reclaim-wick-body': 140}).
- Family B: q25 takes fewer trades than the breakout control, as predicted from a later, stricter confirmation: **HELD** ({'r42-breakout-control': 145, 'r42-breakout-q25': 123}).

Nothing in this round is promotable regardless of outcome (`trading` purpose, PROTOCOL.md r21 amendment) -- these are measurement results only.


(wrote data/rounds/r42-2026-09/analysis.json)

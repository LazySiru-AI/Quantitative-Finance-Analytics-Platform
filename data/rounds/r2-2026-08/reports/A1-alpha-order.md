# A1-alpha-order — Original Alphabetical Order — round 2 report

Agent: `A1-alpha-order` | Discipline: `pairs-rotation` | Library status: `variants/` | Eligible: 7/8
main windows (same `gfc` block as the rest of the A family). Clears the regime gate.

## 1. What the card is, and what it isolates

Identical to `A-rotation` in every rule, parameter and universe member: same nine names, same
`close > sma(50) and 55 < rsi(14) < 80` entry, same exit, same 12% stop / 20% target, same 3 slots at
30%. The **only** difference is the order the nine symbols are written in the universe array —
`A-rotation` orders by trailing 12-month return through the design cutoff
(`MU INTC AMD TSM SOXX NVDA AVGO QCOM MRVL`); this card restores the alphabetical order the card was
originally submitted in (`AMD AVGO INTC MRVL MU NVDA QCOM SOXX TSM`). The broker consults that order
only on sessions where more than three of the nine names qualify at once (median 4 of 9 qualify per
session, per the card's own design measurement), so the tiebreak binds often enough to matter.

**This is a control, not a hypothesis.** It tests no economic idea. Whatever gap it shows against
`A-rotation` is, by construction, pure fill-order reshuffling — nothing else differs — and it exists
to calibrate how much of every other A-variant comparison is signal versus noise.

## 2. Versus SPY, every window

| window | sessions | card | SPY | excess | adj. excess | cap. exp | max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `q4-2018` | 65 | **-15.94%** | -20.05% | +4.10% | **-8.53%** | 37.0% | -16.93% |
| `covid` | 93 | **+1.10%** | -8.71% | +9.81% | **+5.53%** | 50.9% | -18.07% |
| `bear-2022` | 196 | **-35.65%** | -25.14% | -10.51% | **-29.97%** | 22.6% | -36.83% |
| `chop-2015` | 260 | **-4.87%** | -0.04% | -4.83% | **-4.85%** | 48.5% | -21.73% |
| `chop-2011` | 260 | **-13.56%** | -0.05% | -13.51% | **-13.54%** | 44.5% | -26.52% |
| `bull-2024` | 250 | **+23.30%** | +14.00% | +9.30% | **+13.91%** | 67.1% | -23.82% |
| `recent` | 249 | **+82.61%** | +20.62% | +61.99% | **+67.77%** | 72.0% | -15.97% |

Median adjusted excess **−4.85%** across all seven windows (sorted: −29.97, −13.54, −8.53, **−4.85**,
+5.53, +13.91, +67.77). Six-window common set (dropping `chop-2011`): **+0.34%**, matching
`scorecard-common6.json` exactly. Worst window `bear-2022` (−29.97% — the single worst adjusted
excess posted by any A-family card in either round). Hit rate 3 of 7.

### The noise-floor measurement — this round's version

Every one of this card's numbers above differs from `A-rotation`'s only because of fill order. That
makes the gap between the two cards, window by window, a direct empirical measurement of ordering
noise rather than a finding about strategy quality:

| window | A1 adj. excess | A-rotation adj. excess | gap (A1 − base) |
|---|---:|---:|---:|
| `q4-2018` | -8.53% | -8.76% | +0.23pp |
| `covid` | +5.53% | +4.94% | +0.59pp |
| `bear-2022` | -29.97% | -27.41% | -2.56pp |
| `chop-2015` | -4.85% | -7.16% | +2.31pp |
| `chop-2011` | -13.54% | -17.01% | +3.47pp |
| `bull-2024` | +13.91% | +1.56% | +12.35pp |
| `recent` | +67.77% | +80.25% | -12.48pp |

The gap ranges from **+0.23 to +12.35 points**, flips sign four times across seven windows, and shows
no relationship to regime — the two largest swings are in `bull-2024` and `recent`, not the crisis
windows. This reproduces round 1's finding almost exactly (round 1, four windows: 0.59 to 12.48 points)
and stays comfortably inside `library/README.md`'s pre-registered three-year estimate of the ordering
band (53.9-point spread, σ = 21.2). **Two rounds and eleven window-comparisons now put the observed
ordering-noise ceiling at 12.48 points** — real, but well under the conservative ~20-point floor this
program uses. On the three windows round 1 could not test (`q4-2018`, `chop-2015`, `chop-2011`), the
gap is smaller still: +0.23, +2.31, +3.47 points. Ordering noise, measured twice now, stays modest —
but every other A-variant comparison must still be read against the ~20-point floor, not this round's
narrower observed range, because a wider sample could still surface a bigger swing.

## 3. Concentration

| window | top-3 share of gross winning P&L | return without top 3 |
|---|---:|---:|
| `bear-2022` | 100% | -37.19% |
| `q4-2018` | n/a — no material winners | — |
| `covid` | 82% | -13.84% |
| `chop-2015` | 73% | -21.61% |
| `chop-2011` | 91% | -29.46% |
| `bull-2024` | 36% | -1.70% |
| `recent` | 21% | +53.05% |

Same shape as `A-rotation`: concentrated in five of seven windows, broad only in `recent`. Because
this card differs from the base only in fill order, its concentration pattern is best read as the same
underlying correlation risk (0.589 mean pairwise) rather than a distinct finding.

## 4. Realised versus marked

Open-at-end exposure is small throughout: `bull-2024` (−0.16%), `covid` (+7.50%), `chop-2015`
(+2.27%), `q4-2018` (−1.22%), `recent` (−3.50%). `bear-2022` and `chop-2011` carry no open positions.
None of these marks changes a window's sign.

## 5. Verdict

As a control, this card did its job again: it reproduced the submitted card's logic exactly and showed
that fill order alone moves adjusted excess by up to 12.35 points across this round's seven windows —
consistent with, and this round narrower than, the pre-registered ~20-point floor. That is this card's
real output, not a return figure to be ranked on its own terms.

**No promotion or demotion action applies.** `A1-alpha-order` is not a different strategy competing to
replace `A-rotation`; `PROTOCOL.md` §7 exists precisely to make this kind of calibration possible, and
reading its numbers as evidence that alphabetical order beats or loses to relative-strength order would
be the mistake the control exists to prevent. For the record: this card's own seven-window median
(−4.85%) and six-window median (+0.34%) are both, by construction, noise relative to `A-rotation`'s
(−7.16% / −2.80%) — the ~2.3 to ~2.8-point difference in either pairing is well inside the floor.
**Recommendation: keep re-running unchanged alongside `A-rotation`** so the noise-floor estimate keeps
accumulating independent window-draws rather than resting on any single round.

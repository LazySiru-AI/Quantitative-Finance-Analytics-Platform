# A4-tight-stop — 8% Stop — round 2 report

Agent: `A4-tight-stop` | Discipline: `pairs-rotation` | Library status: `variants/` | Eligible: 7/8
main windows (same `gfc` block as the rest of the A family). Clears the regime gate.

## 1. What the card is, and the single decision it isolates

Identical to `A-rotation` except the stop-loss tightens from 12% to 8%; the 20% take-profit, 3-slot
30% sizing, universe and order all stay unchanged.

**The question it was written to answer:** `A-rotation`'s worst trade lost 19.9% against a nominal
12% stop, because stops in this engine evaluate against the previous close rather than the intraday
low, so a stop-out fills later and worse than an intraday check implies. Does tightening the stop to
8% actually protect capital, or does it just harvest ordinary volatility that would otherwise have
recovered, without meaningfully improving the worst-case fill?

## 2. Versus SPY, every window

| window | sessions | card | SPY | excess | adj. excess | cap. exp | max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `q4-2018` | 65 | **-15.39%** | -20.05% | +4.66% | **-8.46%** | 34.6% | -16.84% |
| `covid` | 93 | **-1.07%** | -8.71% | +7.64% | **+3.37%** | 51.0% | -19.37% |
| `bear-2022` | 196 | **-33.61%** | -25.14% | -8.47% | **-27.82%** | 23.0% | -34.88% |
| `chop-2015` | 260 | **-7.30%** | -0.04% | -7.26% | **-7.28%** | 48.9% | -19.46% |
| `chop-2011` | 260 | **-19.12%** | -0.05% | -19.07% | **-19.10%** | 44.4% | -26.92% |
| `bull-2024` | 250 | **+10.74%** | +14.00% | -3.25% | **+1.56%** | 65.6% | -22.88% |
| `recent` | 249 | **+102.74%** | +20.62% | +82.13% | **+87.85%** | 72.3% | -11.41% |

Median adjusted excess **−7.28%** across all seven windows (sorted: −27.82, −19.10, −8.46, **−7.28**,
+1.56, +3.37, +87.85). Six-window common set: **−2.86%**, matching `scorecard-common6.json`. Worst
window `bear-2022` at −27.82% — the family's worst crisis result. Hit rate 3 of 7.

### `bull-2024` is not merely close to `A-rotation` — it is trade-for-trade identical

Diffing the two cards' logs directly: all 39 trades match on symbol, entry/exit date, entry/exit
price, quantity and P&L. The only difference is `exit_reason` on eight trades — `A-rotation` labels
them `"rule"`, `A4` labels the identical exits `"stop"`. In every one of those eight cases the tighter
8% threshold and the trend-break rule fired at the same session, at the same close — the tighter stop
did not cause an earlier exit anywhere in this window; it only relabelled exits the base card's own
rule would have produced regardless. This is a stronger version of "the margin is inside the noise
band": here, tightening the stop had **zero** effect on realised results despite firing eight times.

### What moved the number elsewhere

**`q4-2018`** — 10 trades, no material winners; AMD stopped at −10.35% ($−310, 9 bars) is the largest
loss, tighter than `A-rotation`'s −14.39% on the same position (see below).

**`covid`** — 13 trades. NVDA (2020-04-07→2020-05-18, target, +26.22%/$813) carries the window; three
winners together are 90% of gross winning P&L, and without them the card returns **−15.04%**. The
tighter stop's cost shows up directly here: AMD, entered 2020-02-19, stopped at 2020-02-24 (3 bars,
−17.00%/−$513) — worse than `A-rotation`'s realised −11.91% on the identical entry, because the 8%
threshold gapped through on the COVID crash open just as badly as the 12% one did, and the position
closed one session earlier with less information.

**`bear-2022`** — 22 trades. Two positions that were rule exits under the 12% stop become stop-outs
under 8% (AVGO −10.68%, MU −10.41%), plus one new stop-out (TSM, 2022-01-18→2022-01-24, 4 bars,
−9.58%/−$275) that the 12% card held four sessions longer before exiting at −8.41% via a slightly
different fill. Net effect: adjusted excess **−27.82%** against `A-rotation`'s −27.41%, a 0.41-point
difference — the tighter stop fires more but barely changes the outcome.

**`chop-2015`** — 33 trades. AMD (+19.99%/$594) and NVDA (+19.27%/$582) carry the window; three
winners are 75% of gross winning P&L, without them the card returns **−24.04%**.

**`chop-2011`** — 27 trades. MU (+20.64%/$627, target) and INTC (+11.45%/$343) are 88% of gross
winning P&L; without them, **−30.32%**. This is the family's worst `chop-2011` result — the tighter
stop's extra firing (MRVL stopped at −9.41% where the 12% card held for a rule exit at −7.27%) adds up
to a 2.09-point shortfall against `A-rotation` in this window.

**`recent`** — 49 trades, the card's best window. INTC (+43.12%/$1,260, target), INTC again
(+28.97%/$866), TSM (+27.44%/$820) are 20% of gross winning P&L; without them the card still returns
**+73.29%**.

## 3. Head-to-head against `A-rotation` — the central evidence for this card's question

| window | A4 adj. excess | A-rotation adj. excess | margin | clears ~20pt floor? |
|---|---:|---:|---:|---|
| `q4-2018` | -8.46% | -8.76% | +0.30pp | No |
| `covid` | +3.37% | +4.94% | -1.57pp | No |
| `bear-2022` | -27.82% | -27.41% | -0.41pp | No |
| `chop-2015` | -7.28% | -7.16% | -0.12pp | No |
| `chop-2011` | -19.10% | -17.01% | -2.09pp | No |
| `bull-2024` | +1.56% | +1.56% | **0.00pp (identical)** | No |
| `recent` | +87.85% | +80.25% | +7.60pp | No |

All seven margins fall inside `A1-alpha-order`'s own empirical noise band (max 12.35 points this
round) — the largest, +7.60 points in `recent`, is smaller than three of `A1`'s seven ordering-only
gaps. Nothing here, on either the round-1 windows or the three new ones, clears the ~20-point floor in
either direction. On the new windows specifically, the margins are the smallest in the family
(+0.30, −0.12, −2.09 points) — if anything, the tighter stop shows even less separation from the base
on genuinely new evidence than it did on round 1's four windows.

**Answer to the pre-registered question, now with seven windows and 123+ trades across two rounds:**
tightening the stop from 12% to 8% still produces no margin large enough to distinguish from ordering
noise, and continues to produce zero effect at all in at least one window despite firing repeatedly.
Where it does differ, the direction is mixed and small (helps in `recent`, `q4-2018`; costs in `covid`,
`bear-2022`, `chop-2011`, `chop-2015`) — consistent with harvesting ordinary volatility rather than
protecting against genuinely worse outcomes. The `covid` AMD trade (−17.00% realised against an 8%
nominal stop, gapping through by nearly 9 points, worse than the identical position's −11.91% under
the 12% stop) is this round's clearest illustration that previous-close evaluation can make a tighter
stop **worse**, not better, in a fast decline: the position exits sooner with no meaningful improvement
in realised loss.

## 4. Concentration

| window | top-3 share of gross winning P&L | return without top 3 |
|---|---:|---:|
| `bear-2022` | 100% | -35.50% |
| `q4-2018` | n/a — no material winners | — |
| `covid` | 90% | -15.04% |
| `chop-2015` | 75% | -24.04% |
| `chop-2011` | 88% | -30.32% |
| `bull-2024` | 40% | -13.59% |
| `recent` | 20% | +73.29% |

Essentially the same concentration profile as `A-rotation` window for window — expected, since the
stop rarely changes which exit occurs (§3's `bull-2024` diff shows this directly).

## 5. Realised versus marked

Open-at-end exposure matches `A-rotation`'s pattern closely: `bull-2024` (+2.29%), `covid` (+6.91%),
`chop-2015` (+2.24%), `q4-2018` (−1.22%), `recent` (−3.50%). None changes a window's sign.
`bear-2022` and `chop-2011` carry no open positions.

## 6. Verdict and promotion recommendation

Round 1 median (four windows) was +2.45%, already below `A-rotation`'s +3.23%. Round 2's full
seven-window median is **−7.28%**, below the base's −7.16%; the three new windows alone give a median
of **−8.46%** (values −8.46%, −7.28%, −19.10%) against the base's −8.76% — a margin of +0.30 points in
this variant's favour, negligible and nowhere near the ~20-point floor. `PROTOCOL.md` §6 requires a
variant to beat its base by a floor-clearing margin on non-overlapping evidence in two consecutive
rounds; this card has never done so in either round.

**Not recommended for promotion to replace `A-rotation`.** Two rounds of evidence now show this
change is close to inert: one window (`bull-2024`) trade-for-trade identical despite the stop firing
eight times, every other margin inside the noise floor, and the one place a difference is unambiguous
(`covid`, AMD) argues against the tighter stop rather than for it. **Recommendation: keep as a
`variants/` line item.** Given two consecutive rounds of essentially flat evidence, round 3 would be
better spent confirming this conclusion holds under one more independent window than expecting a
different verdict to emerge from a parameter change this program has now measured as having almost no
effect.

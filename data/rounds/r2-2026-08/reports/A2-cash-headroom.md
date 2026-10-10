# A2-cash-headroom — 4 Slots at 22% — round 2 report

Agent: `A2-cash-headroom` | Discipline: `pairs-rotation` | Library status: `variants/` | Eligible: 7/8
main windows (same `gfc` block as the rest of the A family). Clears the regime gate.

## 1. What the card is, and the single decision it isolates

Identical to `A-rotation` except position sizing: **4 slots at 22% of equity each, instead of 3 slots
at 30%.** Same universe, same order, same entry/exit rules, same 12% stop and 20% target. Total
committed capital across a full book is 88% either way — the change is only in how many names can be
held at once and how large each position is.

**The question it was written to answer:** `A-rotation` logs a large number of `insufficient_cash`
rejections — qualifying entries it cannot fill because all slots are already occupied. Does widening
the book to a 4th slot relieve that squeeze and let the card capture more of the qualifying signal, or
does spreading the same capital across a 4th name simply dilute conviction?

## 2. Versus SPY, every window

| window | sessions | card | SPY | excess | adj. excess | cap. exp | max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `q4-2018` | 65 | **-17.52%** | -20.05% | +2.53% | **-11.55%** | 29.8% | -18.76% |
| `covid` | 93 | **+6.23%** | -8.71% | +14.94% | **+10.82%** | 52.7% | -16.20% |
| `bear-2022` | 196 | **-28.58%** | -25.14% | -3.44% | **-22.78%** | 23.1% | -29.92% |
| `chop-2015` | 260 | **-9.27%** | -0.04% | -9.23% | **-9.25%** | 47.8% | -17.55% |
| `chop-2011` | 260 | **-16.80%** | -0.05% | -16.75% | **-16.78%** | 45.2% | -23.94% |
| `bull-2024` | 250 | **+20.55%** | +14.00% | +6.55% | **+12.06%** | 60.7% | -23.60% |
| `recent` | 249 | **+72.17%** | +20.62% | +51.55% | **+58.09%** | 68.3% | -11.68% |

Median adjusted excess **−9.25%** across all seven windows (sorted: −22.78, −16.78, **−11.55**, −9.25,
+10.82, +12.06, +58.09 — median is the 4th of 7, −9.25%). Six-window common set: **+0.78%**, matching
`scorecard-common6.json`. Worst window `bear-2022` at −22.78% — the mildest crisis result in the A
family. Hit rate 3 of 7.

### What moved the number

**`q4-2018`** — 12 trades, no material winners; AMD stopped at −14.39% ($−314) and AMD again at
−13.49% ($−290) on a second position are the largest losses. −0.89% of return sits in one open
position.

**`covid`** — 16 trades. MRVL (2020-04-07→2020-05-26, +30.15%/$680, target) and NVDA
(2020-04-07→2020-05-18, +26.22%/$595, target) are the two real winners; together with a third they
are 76% of gross winning P&L, and without them the card returns **−9.12%** rather than +6.23%. +7.08%
of the return sits in open positions at the close.

**`bear-2022`** — 33 trades, the family's most granular book in this window (more slots, more entries
attempted). Top three losses (INTC −11.30%/−$245, AMD −11.00%/−$237, AVGO −10.68%/−$235) still sum to
95% of gross winning P&L when netted against the one real winner (QCOM +5.19%); without the three
largest winners the card returns **−30.20%**.

**`chop-2015`** — 44 trades. AMD (+19.99%/$435) and NVDA (+19.27%/$427) are the two biggest movers;
with MRVL (+16.50%/$366) they are 65% of gross winning P&L, and stripping them leaves **−21.55%**.

**`chop-2011`** — 34 trades. MU (+20.64%/$459, target), TSM (+13.80%/$301, an 71-bar rule exit) and
INTC (+11.45%/$250) are 82% of gross winning P&L; without them the card returns **−26.90%**.

**`bull-2024`** — 49 trades, the most balanced window in the card's set. MRVL (+30.68%/$657), AVGO
(+27.98%/$608) and MRVL again (+23.69%/$509) are only 29% of gross winning P&L — the card still
returns **+2.81%** without them. +0.54% of return sits in one open position.

**`recent`** — 60 trades. INTC (+43.12%/$932, target) is the single largest, followed by INTC again
(+29.46%/$653) and INTC a third time (+28.97%/$634); together 19% of gross winning P&L, the lowest
concentration in the card's set — without them the card still returns **+49.97%**. −3.80% of return
sits in a losing open position.

## 3. Head-to-head against `A-rotation` — the central evidence for this card's question

| window | A2 adj. excess | A-rotation adj. excess | margin | clears ~20pt floor? |
|---|---:|---:|---:|---|
| `q4-2018` | -11.55% | -8.76% | -2.79pp | No |
| `covid` | +10.82% | +4.94% | +5.88pp | No |
| `bear-2022` | -22.78% | -27.41% | +4.63pp | No |
| `chop-2015` | -9.25% | -7.16% | -2.09pp | No |
| `chop-2011` | -16.78% | -17.01% | +0.23pp | No |
| `bull-2024` | +12.06% | +1.56% | +10.50pp | No |
| `recent` | +58.09% | +80.25% | **-22.16pp** | **Yes** |

Six of seven margins sit inside `A1-alpha-order`'s empirical noise band (max 12.35 points this round);
the direction is favourable in four of them (covid, bear-2022, bull-2024, chop-2011) but none is large
enough to call a real difference. On the three windows round 1 never had, the margins are small and
inconsistent in sign (−2.79, +0.23, −2.09) — the cash-headroom question gets no clearer answer from the
new evidence than it got from round 1.

`recent` is the one exception, and it repeats round 1's finding to the point: A2 trails the base card
by **22.16 points**, the same figure round 1 measured on this identical window (the window's trades and
result are unchanged between rounds, so this is not new confirmation — it is the same draw). This is
the round's strongest trending window, and it is where the 4th slot's dilution shows up most clearly:
spreading capital across a fourth name pulls conviction away from the book's strongest names exactly
when concentration would have paid off most. `A3-no-target`'s report shows the same window rewarding a
more concentrated, uncapped approach even harder, which is consistent with this reading.

**Answer to the pre-registered question, now with seven windows instead of four: still regime-
dependent, and this round adds no new floor-clearing evidence either way.** The extra slot brings a
narrower cross-window IQR (see §5) and more trades (mechanically relieving the cash squeeze it was
designed to test — rejections fall in every window relative to `A-rotation`), but the one clean signal
this program has produced about it — a floor-clearing loss in the strongest trend — argues for caution
about the 4th slot in exactly the regime a rotation strategy most wants to win.

## 4. Concentration

| window | top-3 share of gross winning P&L | return without top 3 |
|---|---:|---:|
| `bear-2022` | 95% | -30.20% |
| `q4-2018` | n/a — no material winners | — |
| `covid` | 76% | -9.12% |
| `chop-2015` | 65% | -21.55% |
| `chop-2011` | 82% | -26.90% |
| `bull-2024` | **29%** | +2.81% |
| `recent` | **19%** | +49.97% |

This is the most diversified card in the A family by this measure: `bull-2024` and `recent` both post
the lowest top-3 concentration of any A-variant, and `bull-2024` is the only window across the whole
family where stripping the top three winners still leaves a **positive** return (+2.81%). The extra
slot does buy real breadth in the strongest windows, even though it costs a floor-clearing amount of
raw return in the very best one (`recent`, per §3).

## 5. Realised versus marked

Marks are small throughout: `bull-2024` (+0.54%), `covid` (+7.08%), `chop-2015` (+1.34%), `q4-2018`
(−0.89%), `recent` (−3.80%). None changes a window's sign. `bear-2022` and `chop-2011` carry no open
positions.

## 6. Verdict and promotion recommendation

Round 1 median (four windows) was +11.42% — the family's best-placed card that round. Round 2's full
seven-window median is **−9.25%**, and the three new windows alone give a median of −11.55% (values
−11.55%, −9.25%, −16.78%), negative. Neither round's evidence, taken on its own new-window slice,
clears the ~20-point noise floor against `A-rotation`'s own new-window figures (margin −2.79pp on
`q4-2018`, the only genuinely new-window comparison with meaningful separation, and even that is small).
`PROTOCOL.md` §6 requires a variant to beat its base on median adjusted excess in two consecutive
rounds on non-overlapping evidence, with a margin clearing the noise floor — this round supplies
neither a beat nor a floor-clearing margin.

**Not recommended for promotion to replace `A-rotation`.** The most defensible finding this round adds
is not about promotion at all: the 4th slot narrows concentration in the strongest windows (the family's
lowest top-3 shares, and the only positive without-top-3 result) at the cost of a real, repeated,
floor-clearing shortfall in the single best trending window. That is a specific, useful characterisation
of the trade-off the card's own question asked about — it is not evidence for a library change.
**Recommendation: keep as a `variants/` line item.** Round 3 should specifically look for another
strongly trending window, since that is the one regime this program has produced a clean signal for,
and it argues against the variant.

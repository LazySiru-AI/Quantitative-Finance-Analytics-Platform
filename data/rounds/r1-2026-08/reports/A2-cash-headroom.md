# A2-cash-headroom — 4 Slots at 22%

Rank: **5th of 18** on the round's ranking, the best-placed A-family card. Ranked and eligible in all
four windows this round can run; blocked from `gfc` on the same AVGO-history floor as the rest of the
family (first bar 2009-08-06, later than `gfc` needs).

## 1. What the card is, and the question it isolates

Identical to `A-rotation` except position sizing: 4 slots at 22% of equity each, instead of 3 slots
at 30% each (same universe, same order, same entry/exit rules, same 12% stop and 20% target). Total
committed capital across a full book is 88% either way; the change is in how many names can be held
at once and how large each position is.

**The question it was written to answer:** `A-rotation` logged 74–204 `insufficient_cash` rejections
depending on window — sessions where a qualifying entry could not be filled because all slots were
already occupied. Does widening the book to a 4th slot relieve that squeeze and let the card capture
more of the qualifying signal, or does spreading the same total capital across a 4th name simply
dilute the average conviction of the book?

## 2. Results across the four windows

Corrected metrics per `DEFECTS.md`: `corrected_return = ending_equity / starting_equity − 1`,
`capital_exposure = Σ(quantity × entry_price × bars_held) / (sessions × starting_equity)`,
`adjusted_excess = corrected_return − capital_exposure × benchmark_return`.

| window | trades | corrected return | benchmark | excess | adjusted excess | capital exposure | session exposure | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| covid | 16 | +6.23% | −8.71% | +14.94% | **+10.73%** | 51.73% | 74.19% | −16.20% | 33.33% |
| bear-2022 | 33 | −28.58% | −25.14% | −3.44% | **−22.78%** | 23.07% | 44.90% | −29.92% | 15.15% |
| bull-2024 | 49 | +20.55% | +14.00% | +6.55% | **+12.10%** | 60.33% | 88.80% | −23.60% | 37.78% |
| recent | 60 | +72.17% | +20.62% | +51.55% | **+58.16%** | 67.93% | 95.58% | −11.68% | 48.21% |

Median adjusted excess **+11.42%**, worst **−22.78%** (bear-2022 — this card's least-bad crisis
result of the family), best **+58.16%** (recent — this card's least-extreme best window of the
family), IQR **21.26 points** — narrower than every other A-family card. 158 trades total, the most
of any card in the family. Rejections fall in every window relative to `A-rotation`: 65 vs. 85
(covid), 71 vs. 111 (bear-2022), 29 vs. 74 (bull-2024), 6 vs. 12 (recent) — the extra slot
mechanically relieves the cash squeeze it was written to test.

## 3. Head-to-head against A-rotation

| window | A2 adj. excess | A-rotation adj. excess | margin | clears ~20pt floor? |
|---|---:|---:|---:|---|
| covid | +10.73% | +4.85% | +5.88pp | No |
| bear-2022 | −22.78% | −27.41% | +4.63pp | No |
| bull-2024 | +12.10% | +1.60% | +10.50pp | No |
| recent | +58.16% | +80.32% | **−22.16pp** | **Yes** |

`A1-alpha-order`'s own gap against `A-rotation` (pure ordering artifact, no rule change at all) ranged
0.59–12.48 points across these same four windows. Three of A2's four margins — covid, bear-2022,
bull-2024 — sit inside that band; the direction is consistently favorable (A2 ahead in every one of
those three) but none is large enough to distinguish from reshuffling noise on this round's evidence.

`recent` is different: A2 trails the base card by **22.16 points**, clearing the ~20-point floor.
This is the one window in the round with the strongest, most sustained trend, and it is where the 4th
slot's dilution shows up most clearly — the extra position spreads capital away from the book's
strongest names in exactly the regime where concentration paid off most. `A3-no-target`'s report
shows the same `recent` window rewarding an *un*-capped, more concentrated approach even more
strongly, which is consistent with this reading rather than contradicting it.

**Answer to the pre-registered question: it depends on the regime, and this round can only speak to
one instance of each.** Relieving the cash squeeze produced a materially higher trade count and a
narrower cross-window IQR (21.26 vs. `A-rotation`'s 29.37) — the 4th slot does buy some stability. But
in the one window where concentration would have mattered most, dilution cost real, floor-clearing
performance. A single round cannot separate "4 slots is a genuine improvement in choppier regimes"
from "4 slots got lucky three times and unlucky once" — that requires round 2 on a different window
set.

## 4. Trade-level detail

**Exit-reason distribution per window:**

| window | rule | stop | target | open_at_end |
|---|---:|---:|---:|---:|
| covid | 8 | 2 | 2 | 4 |
| bear-2022 | 33 | — | — | — |
| bull-2024 | 30 | 3 | 12 | 4 |
| recent | 29 | 6 | 21 | 4 |

**Best and worst trades:**

| window | best | worst |
|---|---|---|
| covid | MRVL, 2020-04-07→2020-05-26, target, +30.15% | NVDA, 2020-02-19→2020-02-26, stop, −13.13% |
| bear-2022 | QCOM, 2022-07-14→2022-08-23, rule, +5.19% | INTC, 2022-07-28→2022-07-29, rule, −11.30% |
| bull-2024 | MRVL, 2024-11-15→2024-12-05, target, +30.68% | MU, 2024-12-17→2024-12-19, rule, −18.01% |
| recent | INTC, 2026-04-09→2026-04-27, target, +43.12% | AMD, 2026-01-26→2026-02-05, stop, −21.46% |

**Every stopped-out trade against the nominal 12% stop:**

| window | symbol | entry → exit | realised loss | nominal | gap |
|---|---|---|---:|---:|---:|
| covid | AMD | 2020-02-19 → 2020-02-25 | −11.91% | −12.00% | +0.09pp |
| covid | NVDA | 2020-02-19 → 2020-02-26 | −13.13% | −12.00% | −1.13pp |
| bull-2024 | AVGO | 2024-12-16 → 2025-01-28 | −10.35% | −12.00% | +1.65pp |
| bull-2024 | MU | 2025-01-16 → 2025-01-28 | −11.32% | −12.00% | +0.68pp |
| bull-2024 | INTC | 2025-02-20 → 2025-03-05 | −16.62% | −12.00% | −4.62pp |
| recent | INTC | 2026-01-22 → 2026-01-26 | −18.40% | −12.00% | −6.40pp |
| recent | AMD | 2026-01-26 → 2026-02-05 | −21.46% | −12.00% | **−9.46pp** |
| recent | TSM | 2026-02-25 → 2026-03-09 | −14.09% | −12.00% | −2.09pp |
| recent | MRVL | 2026-06-08 → 2026-06-11 | −9.84% | −12.00% | +2.16pp |
| recent | INTC | 2026-06-22 → 2026-07-06 | −11.99% | −12.00% | +0.01pp |

Ten stop-outs, six worse than nominal. AMD in `recent` is this card's worst fill: −21.46% against a
12% nominal stop, a 9.46-point gap — worse than either `A-rotation`'s or `A1`'s equivalent AMD trade
in the same window, because the smaller 22% position here still bought more shares relative to price
movement in a fast gap-down, so slippage on realised percentage terms tracks price action, not
position size, and this AMD gap was severe across the whole family.

## 5. Fragility

IQR of 21.26 points is the tightest of any A-family card — meaningfully narrower than `A-rotation`'s
29.37 and about the width of a single ordering-artifact swing (A1's own gap ran up to 12.48 points).
That narrowing is real evidence that the 4th slot smooths the book's cross-window behavior somewhat,
though "tightest of a very wide family" is a low bar: 21.26 points is still wider than every
non-A-family card the round produced (see `A-rotation.md` for the family comparison). Worst window
remains `bear-2022` (−22.78%), the least severe of the family's four but still a large loss against a
falling benchmark.

## 6. Verdict

Best-ranked card in the A family this round (5th of 18, median adjusted excess +11.42%), a positive
hit rate of 3 of 4, and the family's narrowest IQR. The one clean, floor-clearing signal from this
round — a 22.16-point shortfall against the base card in `recent` — is a genuine finding about this
specific window's regime, not noise, but it is a single instance and cuts against, rather than for,
promoting this variant on strength alone.

**Recommendation: hold as a `variants/` candidate, not yet a base replacement.** `PROTOCOL.md` §6
requires a variant to beat its base on median adjusted excess in two consecutive rounds before it can
replace it; this round's median (+11.42%) does beat `A-rotation`'s (+3.23%), so round 2 is the test
that decides this. Given the mixed picture — ahead in three windows within noise, behind by a clear
margin in the fourth — round 2 should specifically include another strongly trending window if one is
available, since that is where this round's only unambiguous result went against the variant.

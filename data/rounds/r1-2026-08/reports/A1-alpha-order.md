# A1-alpha-order — Original Alphabetical Order

Rank: **7th of 18** on the round's ranking. Ranked and eligible in all four windows this round can
run; blocked from `gfc` on the same AVGO-history floor as the rest of the A family
(first bar 2009-08-06, later than `gfc` needs).

## 1. What the card is, and the question it isolates

Identical to `A-rotation` in every rule, parameter and universe membership. The **only** change is
the order the nine symbols are written in the `universe` array: `A-rotation` orders by trailing
12-month return through the design cutoff (`MU INTC AMD TSM SOXX NVDA AVGO QCOM MRVL`); this card
restores the order the card was originally submitted in, alphabetical
(`AMD AVGO INTC MRVL MU NVDA QCOM SOXX TSM`). Order matters only because the broker fills entries in
the order the array lists them, and only on sessions where more than three of the nine names qualify
at once — the cap binds often enough (median 4 of 9 qualifying per session) for the tiebreak to
change which three names actually get bought.

**This card is a control, not a hypothesis.** It changes nothing about the strategy's logic; it
exists to answer one question: how much does the raw result move just from reshuffling a fill-order
tiebreak that carries no economic content? Whatever gap this card shows against `A-rotation` is, by
construction, pure ordering artifact — the base card's report uses this gap as the round's empirical
noise floor for judging the other three variants.

## 2. Results across the four windows

Corrected metrics per `DEFECTS.md`: `corrected_return = ending_equity / starting_equity − 1`,
`capital_exposure = Σ(quantity × entry_price × bars_held) / (sessions × starting_equity)`,
`adjusted_excess = corrected_return − capital_exposure × benchmark_return`.

| window | trades | corrected return | benchmark | excess | adjusted excess | capital exposure | session exposure | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| covid | 12 | +1.10% | −8.71% | +9.81% | **+5.45%** | 49.90% | 74.19% | −18.07% | 22.22% |
| bear-2022 | 25 | −35.65% | −25.14% | −10.51% | **−29.97%** | 22.58% | 44.39% | −36.83% | 8.00% |
| bull-2024 | 39 | +23.30% | +14.00% | +9.30% | **+13.96%** | 66.73% | 88.80% | −23.82% | 33.33% |
| recent | 53 | +82.61% | +20.62% | +61.99% | **+67.84%** | 71.63% | 95.58% | −15.97% | 44.00% |

Median adjusted excess **+9.70%**, worst **−29.97%** (bear-2022 — this card's worst window is also
its worst in absolute terms of any A-family card in this round), best **+67.84%** (recent), IQR
**30.84 points**, hit rate 3 of 4. 129 trades total, the most of any A-family card except A2.

**D1 applies here too, and worse than to `A-rotation`.** The runner's raw `total_return` reports
covid as **−0.97%**; the corrected figure is **+1.10%** — the largest sign-flip gap of any card in
`DEFECTS.md`'s reproduction table (+2.07 percentage points). Alphabetical order happens to fill a
name on session one under this design cutoff, which is exactly the condition that triggers the
defect.

## 3. Head-to-head against A-rotation — this *is* the noise-floor measurement

Because nothing but fill order differs, this section does not test a hypothesis about the strategy;
it measures the reshuffling noise that every other variant's comparison must be judged against.

| window | A1 adj. excess | A-rotation adj. excess | margin (A1 − base) |
|---|---:|---:|---:|
| covid | +5.45% | +4.85% | +0.59pp |
| bear-2022 | −29.97% | −27.41% | −2.57pp |
| bull-2024 | +13.96% | +1.60% | +12.35pp |
| recent | +67.84% | +80.32% | −12.48pp |

The margin ranges from **0.59 to 12.48 points**, flips sign twice, and shows no relationship to
regime (the largest gap is in `bull-2024`, not the two crisis windows). This is the direct,
in-round confirmation of `library/README.md`'s twelve-ordering sensitivity study (53.9-point spread,
σ = 21.2 points over three years): reordering an unchanged rule set moves the result by double-digit
points even over a single window, for reasons that have nothing to do with strategy quality.

**Conclusion for the round: treat ~20 points as the operative floor**, consistent with the wider,
pre-registered library estimate rather than this round's narrower four-window sample (which could
itself be an artifact of only four draws). Any A2/A3/A4-vs-base margin under ~20 points has not been
shown to be more than this. By that standard, none of A1's own four margins above would count as a
real difference either, which is the right conclusion for a card that changed nothing but order —
this comparison should show noise, and it does.

## 4. Trade-level detail

**Exit-reason distribution per window:**

| window | rule | stop | target | open_at_end |
|---|---:|---:|---:|---:|
| covid | 6 | 2 | 1 | 3 |
| bear-2022 | 25 | — | — | — |
| bull-2024 | 24 | 2 | 10 | 3 |
| recent | 29 | 4 | 17 | 3 |

**Best and worst trades:**

| window | best | worst |
|---|---|---|
| covid | MRVL, 2020-04-07→2020-05-26, target, +30.15% | NVDA, 2020-02-19→2020-02-26, stop, −13.13% |
| bear-2022 | QCOM, 2022-07-14→2022-08-23, rule, +5.19% | MRVL, 2022-01-03→2022-01-14, rule, −11.61% |
| bull-2024 | MRVL, 2024-11-18→2024-12-05, target, +32.37% | MU, 2024-12-17→2024-12-19, rule, −18.01% |
| recent | INTC, 2026-04-13→2026-04-27, target, +34.43% | AMD, 2026-01-22→2026-02-05, stop, −19.90% |

**Every stopped-out trade against the nominal 12% stop:**

| window | symbol | entry → exit | realised loss | nominal | gap |
|---|---|---|---:|---:|---:|
| covid | AMD | 2020-02-19 → 2020-02-25 | −11.91% | −12.00% | +0.09pp |
| covid | NVDA | 2020-02-19 → 2020-02-26 | −13.13% | −12.00% | −1.13pp |
| bull-2024 | AVGO | 2024-12-16 → 2025-01-28 | −10.35% | −12.00% | +1.65pp |
| bull-2024 | INTC | 2025-02-20 → 2025-03-05 | −16.62% | −12.00% | **−4.62pp** |
| recent | MU | 2025-11-14 → 2025-11-21 | −11.72% | −12.00% | +0.28pp |
| recent | AMD | 2026-01-22 → 2026-02-05 | −19.90% | −12.00% | **−7.90pp** |
| recent | MRVL | 2026-06-08 → 2026-06-11 | −9.84% | −12.00% | +2.16pp |
| recent | INTC | 2026-06-22 → 2026-07-06 | −11.99% | −12.00% | +0.01pp |

Eight stop-outs, four worse than nominal. AMD in `recent` is this card's worst fill: entered
2026-01-22 at $251.88, stopped at $201.76 for a realised **−19.90%** against a 12% nominal stop, a
7.90-point gap — the single largest previous-close slippage measured across the A family this round,
consistent with `library/README.md`'s own reference to "A's worst trade lost 19.9% against a 12%
stop." `bear-2022` had no stop-outs at all in this card, same as in `A-rotation`.

## 5. Fragility

IQR of 30.84 points, marginally wider than `A-rotation`'s 29.37 — consistent with the finding in §3
that reordering alone adds real dispersion on top of whatever the strategy itself contributes. This
card's worst window (bear-2022, −29.97%) is also the single worst result posted by any A-family card
in this round. Because this card differs from `A-rotation` only in fill order, its fragility is best
read as the same correlation-driven concentration risk (0.589 mean pairwise correlation across the
universe) plus an added layer of order-dependent noise, not a distinct risk profile.

## 6. Verdict

As a control, this card did its job: it reproduced the submitted card's logic exactly and showed
that fill-order alone produces a 0.59–12.48 point swing across this round's four windows, well inside
the ~20-point pre-registered noise floor from the library's twelve-ordering study. That is the
report's real output — not a return figure to be ranked, but a calibration for every other variant.

**No promotion or demotion action applies to this card.** `PROTOCOL.md` §7 exists to make exactly
this kind of check possible; A1 is not competing to replace `A-rotation` (it is not even a different
strategy), and its numbers should not be read as evidence that alphabetical order is better or worse
than relative-strength order — reading them that way is precisely the mistake this control is
designed to prevent. **Recommendation: re-run A1 unchanged alongside `A-rotation` in round 2** so the
noise-floor estimate stops being a single four-window draw and starts being a distribution of its
own.

# A4-tight-stop — 8% Stop

Rank: **12th of 18** on the round's ranking. Ranked and eligible in all four windows this round can
run; blocked from `gfc` on the same AVGO-history floor as the rest of the family (first bar
2009-08-06, later than `gfc` needs).

## 1. What the card is, and the question it isolates

Identical to `A-rotation` except the stop-loss tightens from 12% to 8%; the 20% take-profit, 3-slot
sizing at 30%, and universe order all stay unchanged.

**The question it was written to answer:** `A-rotation`'s worst trade lost 19.9% against a nominal
12% stop, because stops in this engine evaluate against the previous close rather than the intraday
low, so a stop-out fills later and worse than an intraday check would imply. Does tightening the stop
to 8% actually protect capital, or does it just harvest noise — cutting positions on ordinary
volatility that would otherwise have recovered, without meaningfully reducing the worst-case fill?

## 2. Results across the four windows

Corrected metrics per `DEFECTS.md`: `corrected_return = ending_equity / starting_equity − 1`,
`capital_exposure = Σ(quantity × entry_price × bars_held) / (sessions × starting_equity)`,
`adjusted_excess = corrected_return − capital_exposure × benchmark_return`.

| window | trades | corrected return | benchmark | excess | adjusted excess | capital exposure | session exposure | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| covid | 13 | −1.07% | −8.71% | +7.64% | **+3.29%** | 50.06% | 73.12% | −19.37% | 30.00% |
| bear-2022 | 22 | −33.61% | −25.14% | −8.47% | **−27.82%** | 23.05% | 43.88% | −34.88% | 13.64% |
| bull-2024 | 39 | +10.74% | +14.00% | −3.26% | **+1.60%** | 65.29% | 88.40% | −22.88% | 27.78% |
| recent | 49 | +102.74% | +20.62% | +82.12% | **+87.91%** | 71.93% | 93.98% | −11.41% | 50.00% |

Median adjusted excess **+2.45%**, worst **−27.82%** (bear-2022, this card's worst-in-family
adjusted excess for that window), best **+87.91%** (recent, this card's best-in-family adjusted
excess for that window), IQR **30.20 points**. 123 trades total.

**`bull-2024` is not merely close to `A-rotation` — it is identical**, confirmed at the trade level
(§3a): the tighter stop changed which label eight exits carry, but not a single fill price, date, or
dollar of P&L in that window.

## 3. Head-to-head against A-rotation — the central evidence for this card's question

| window | A4 adj. excess | A-rotation adj. excess | margin | clears ~20pt floor? |
|---|---:|---:|---:|---|
| covid | +3.29% | +4.85% | −1.56pp | No |
| bear-2022 | −27.82% | −27.41% | −0.41pp | No |
| bull-2024 | +1.60% | +1.60% | **0.00pp (identical)** | No |
| recent | +87.91% | +80.32% | +7.59pp | No |

`A1-alpha-order`'s ordering-artifact gap against `A-rotation` ranged 0.59–12.48 points across these
windows. **All four of A4's margins fall inside that band** — the largest, +7.59 points in `recent`,
is smaller than three of A1's four ordering-only gaps. Nothing here clears the ~20-point floor in
either direction.

### 3a. Verified: A4 and A-rotation are trade-for-trade identical in bull-2024

Directly diffing the two cards' `bull-2024` trade logs: all 39 trades match on symbol, entry/exit
date, entry/exit price, quantity and P&L. The only difference is `exit_reason` on eight trades —
`A-rotation` labels them `"rule"` (trend-break/RSI exit), `A4` labels the identical exits `"stop"`.
In every one of those eight cases the tighter 8% stop and the trend-break rule fired on the same
session, at the same close, for the same position — the tighter threshold did not cause an earlier
exit anywhere in this window; it just relabeled exits the base card's own rule would have produced at
the identical price regardless. This is a stronger and more specific version of "the margin is inside
the noise band": in `bull-2024`, tightening the stop had **zero** effect on realised results.

### 3b. Answer to the pre-registered question

Across all four windows and 123 trades, tightening the stop from 12% to 8% produced no margin large
enough to distinguish from `A1`'s pure-reshuffling noise, and in one window it produced no effect at
all despite firing eight times. The `recent`-window edge (+7.59 points) is directionally consistent
with "a tighter stop helps in a volatile-but-ultimately-trending regime" but is smaller than half of
A1's own ordering gaps in the same window set, so this round cannot support that reading as more than
a plausible story. **This round cannot answer whether a tighter stop helps or just harvests noise —
the evidence is consistent with either, and mostly indistinguishable from a relabeled universe.**

## 4. Trade-level detail

**Exit-reason distribution per window:**

| window | rule | stop | target | open_at_end |
|---|---:|---:|---:|---:|
| covid | 6 | 3 | 1 | 3 |
| bear-2022 | 19 | 3 | — | — |
| bull-2024 | 20 | 8 | 8 | 3 |
| recent | 17 | 10 | 19 | 3 |

Stop-outs rise sharply relative to `A-rotation` in every window (1→3 covid, 0→3 bear-2022, 0→8
bull-2024, 5→10 recent) — the tighter threshold fires far more often, as designed. §3a shows that in
`bull-2024` this additional firing changed nothing about the outcome.

**Best and worst trades:**

| window | best | worst |
|---|---|---|
| covid | NVDA, 2020-04-07→2020-05-18, target, +26.22% | AMD, 2020-02-19→2020-02-24, stop, −17.00% |
| bear-2022 | QCOM, 2022-07-14→2022-08-23, rule, +5.19% | INTC, 2022-07-28→2022-07-29, rule, −11.30% |
| bull-2024 | MRVL, 2024-11-15→2024-12-05, target, +30.68% | MU, 2024-12-17→2024-12-19, rule, −18.01% |
| recent | INTC, 2026-04-09→2026-04-27, target, +43.12% | AMD, 2026-07-23→2026-07-28, stop, −14.36% |

**Every stopped-out trade against the nominal 8% stop** (not 12% — this is the card's whole point):

| window | symbol | entry → exit | realised loss | nominal | gap |
|---|---|---|---:|---:|---:|
| covid | AMD | 2020-02-19 → 2020-02-24 | −17.00% | −8.00% | **−9.00pp** |
| covid | NVDA | 2020-03-05 → 2020-03-10 | −7.37% | −8.00% | +0.63pp |
| covid | NVDA | 2020-03-31 → 2020-04-02 | −8.69% | −8.00% | −0.69pp |
| bear-2022 | AVGO | 2022-01-03 → 2022-01-14 | −10.68% | −8.00% | −2.68pp |
| bear-2022 | MU | 2022-01-03 → 2022-01-21 | −10.41% | −8.00% | −2.41pp |
| bear-2022 | TSM | 2022-01-18 → 2022-01-24 | −9.58% | −8.00% | −1.58pp |
| bull-2024 | MRVL | 2024-09-03 → 2024-09-09 | −9.13% | −8.00% | −1.13pp |
| bull-2024 | MU | 2024-11-08 → 2024-11-14 | −9.77% | −8.00% | −1.77pp |
| bull-2024 | MRVL | 2024-12-06 → 2025-01-28 | −9.07% | −8.00% | −1.07pp |
| bull-2024 | AVGO | 2024-12-20 → 2025-01-28 | −5.70% | −8.00% | +2.30pp |
| bull-2024 | MRVL | 2025-02-07 → 2025-02-10 | −8.02% | −8.00% | −0.02pp |
| bull-2024 | MU | 2025-02-20 → 2025-02-25 | −8.25% | −8.00% | −0.25pp |
| bull-2024 | INTC | 2025-02-25 → 2025-03-05 | −11.98% | −8.00% | **−3.98pp** |
| bull-2024 | MU | 2025-06-27 → 2025-07-18 | −8.80% | −8.00% | −0.80pp |
| recent | MU | 2025-11-11 → 2025-11-19 | −8.72% | −8.00% | −0.72pp |
| recent | TSM | 2026-02-25 → 2026-03-04 | −8.50% | −8.00% | −0.50pp |
| recent | SOXX | 2026-02-26 → 2026-03-04 | −7.31% | −8.00% | +0.69pp |
| recent | MU | 2026-05-27 → 2026-06-08 | −1.92% | −8.00% | +6.08pp |
| recent | MRVL | 2026-06-08 → 2026-06-11 | −9.84% | −8.00% | −1.84pp |
| recent | MU | 2026-06-22 → 2026-06-24 | −9.62% | −8.00% | −1.62pp |
| recent | INTC | 2026-06-22 → 2026-07-02 | −7.42% | −8.00% | +0.58pp |
| recent | MU | 2026-06-24 → 2026-07-06 | −7.05% | −8.00% | +0.95pp |
| recent | MRVL | 2026-06-11 → 2026-07-08 | −13.67% | −8.00% | **−5.67pp** |
| recent | AMD | 2026-07-23 → 2026-07-28 | −14.36% | −8.00% | **−6.36pp** |

24 stop-outs across the four windows, 16 of them worse than the 8% nominal. The worst is the same AMD
in `covid`: entered 2020-02-19 at $58.02, stopped 2020-02-24 at $48.16, a realised **−17.00%** against
an 8% nominal stop — an 8.99-point gap, more than double the nominal threshold itself, on a 3-bar
hold as the COVID crash opened. That single trade shows the tighter stop does not bound the worst
case the way its nominal value implies: previous-close evaluation means a fast-moving gap can blow
through an 8% threshold by nearly as much as it blew through `A-rotation`'s 12% one (that same AMD
position, under the 12% stop, realised −11.91%, a 0.09-point gap). The tighter stop's nominal
protection is real on paper but is exactly the kind of protection previous-close evaluation
undermines in a fast decline — the two card's realised losses on the identical AMD entry (−17.00% vs.
−11.91%) differ by more than the 4-point gap between their nominal thresholds would predict.

## 5. Fragility

IQR of 30.20 points, essentially matching `A-rotation`'s 29.37 and `A1`'s 30.84 — tightening the stop
did not narrow the cross-window spread despite firing roughly three times as often. That is
consistent with §3's finding that the stop change mostly does not bind at the portfolio level in
these windows: it fires more, but (except in `covid`, where it produced this card's single worst
trade) it rarely changes which exit would have happened anyway.

## 6. Verdict

None of this card's four margins against `A-rotation` clear the ~20-point noise floor established by
`A1`'s ordering-only comparison, and one window (`bull-2024`) is trade-for-trade identical to the
base despite the stop firing eight times. The evidence this round does not show the tighter stop
helping or hurting in any window that survives the noise floor, and the one place it produces a
distinctly worse outcome than the looser stop — AMD in `covid`, −17.00% vs. −11.91% on the identical
position — argues if anything for caution about tightening a previous-close-evaluated stop rather
than for its benefit.

**Not recommended for promotion to replace `A-rotation`.** `PROTOCOL.md` §6 requires a variant to
beat its base on median adjusted excess in two consecutive rounds; this round's median (+2.45%) is
below the base's (+3.23%), and even where A4 leads (recent, +7.59pp) the margin does not clear this
round's own noise floor. **Recommendation: keep as a `variants/` line item and re-test unchanged in
round 2**, specifically to see whether the `bull-2024` identical-fills result and the `covid` AMD
slippage pattern are stable — both point toward the tighter stop being close to inert at best and
mildly counterproductive at worst under previous-close evaluation, but one round is not enough to
settle it.

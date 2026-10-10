# A3-no-target — No Take-Profit

Rank: **15th of 18** on the round's ranking, the worst-placed A-family card despite posting this
round's single largest adjusted-excess figure of any card, in any window. Ranked and eligible in all
four windows this round can run; blocked from `gfc` on the same AVGO-history floor as the rest of the
family (first bar 2009-08-06, later than `gfc` needs).

## 1. What the card is, and the question it isolates

Identical to `A-rotation` except the 20% take-profit is removed entirely (`take_profit_pct: null`);
the stop stays at 12%, sizing at 3 slots of 30%, everything else unchanged.

**The question it was written to answer:** the library's `B-momentum` author measured that
take-profits amputate the winners that carry a momentum book. `A-rotation` uses a 20% cap. Does
capping winners at 20% cost this card more than it protects — i.e., is the base card's take-profit a
net drag on a strategy whose entry logic is designed to ride a confirmed uptrend?

## 2. Results across the four windows

Corrected metrics per `DEFECTS.md`: `corrected_return = ending_equity / starting_equity − 1`,
`capital_exposure = Σ(quantity × entry_price × bars_held) / (sessions × starting_equity)`,
`adjusted_excess = corrected_return − capital_exposure × benchmark_return`.

| window | trades | corrected return | benchmark | excess | adjusted excess | capital exposure | session exposure | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| covid | 10 | −2.37% | −8.71% | +6.34% | **+1.30%** | 42.22% | 73.12% | −17.85% | 12.50% |
| bear-2022 | 22 | −33.27% | −25.14% | −8.13% | **−27.41%** | 23.34% | 44.39% | −34.55% | 13.64% |
| bull-2024 | 25 | +5.32% | +14.00% | −8.68% | **−2.88%** | 58.55% | 88.40% | −26.26% | 13.04% |
| recent | 26 | +164.70% | +20.62% | +144.08% | **+149.56%** | 73.42% | 95.58% | −16.25% | 43.48% |

Median adjusted excess **−0.79%**, worst **−27.41%** (bear-2022, identical to `A-rotation` — see §3),
best **+149.56%** (recent — the largest single adjusted-excess figure any A-family card posted this
round, in any window), IQR **47.38 points**, the widest of any A-family card by a large margin. Only
83 trades total, the fewest of the family — capital that is not trimmed at 20% stays tied up in
winners longer, so fewer round-trips complete. Rejections reflect that directly: 204 in covid and
**359 in bull-2024**, both far above `A-rotation`'s 85 and 74 in the same windows — positions the base
card would have closed at target simply keep occupying slots here, blocking new entries.

## 3. Head-to-head against A-rotation

| window | A3 adj. excess | A-rotation adj. excess | margin | clears ~20pt floor? |
|---|---:|---:|---:|---|
| covid | +1.30% | +4.85% | −3.55pp | No |
| bear-2022 | −27.41% | −27.41% | **0.00pp (identical)** | No |
| bull-2024 | −2.88% | +1.60% | −4.48pp | No |
| recent | +149.56% | +80.32% | **+69.24pp** | **Yes** |

`A1-alpha-order`'s ordering-artifact gap against `A-rotation` ranged 0.59–12.48 points across these
windows. Two of A3's four margins — covid and bull-2024 — sit inside that band and are not
distinguishable from noise on this round's evidence; `bear-2022` is not merely inside the band, it is
**exactly zero**, for a specific, verifiable reason (§3a).

`recent` is the exception, and it is not a marginal one: a **69.24-point** margin, more than three
times the ~20-point floor and more than five times A1's largest observed ordering gap. This is the
round's clearest floor-clearing result in either direction, for either A-family variant.

### 3a. Verified: A3 and A-rotation are genuinely identical in bear-2022

Confirmed directly from the trade logs, not inferred from aggregates: `A-rotation`'s and
`A3-no-target`'s `bear-2022` trade lists are **byte-identical** — same 22 trades, same symbols, same
entry/exit dates and prices, same P&L, same ending equity ($6,672.54 from $10,000 starting in both).
Every one of the 22 exits in both logs carries `exit_reason: "rule"` — none is `"target"`. The 20%
take-profit this variant removes **never bound in `bear-2022`** for either card: no position in that
window ever gained 20% before the trend-break exit fired first. Removing an exit condition that never
fires cannot change a result, and it did not. This is the cleanest possible confirmation that the
identical result is mechanical, not coincidental.

### 3b. What `recent` answers about the pre-registered question

`recent` is where the take-profit actually binds for `A-rotation` (19 of 47 exits are `target`), and
removing it is worth 69.24 points there — driven overwhelmingly by one trade: MRVL, entered
2026-03-09 at $87.97, held 83 bars past where a 20% cap would have closed it, and exited via the
trend-break rule on 2026-07-08 at $225.05, a realised **+155.82%** return on that single position
(see §4). In a window with one sufficiently strong, sufficiently sustained trend, the take-profit is
a large, quantifiable drag. In the other three windows — including `bear-2022`, where it structurally
cannot matter, and `covid`/`bull-2024`, where its effect is inside the noise band — removing it is not
shown to help or hurt.

**Answer to the pre-registered question: yes, in the one regime this round could test it in — a
long, undisrupted uptrend — the 20% cap cost far more than it protected. This round cannot say
whether that generalizes**, because the mechanism is a single outsized trade, not a broad pattern
across many capped winners; three of the four windows produced no signal either way, and the one that
did depended on MRVL's trajectory not repeating a familiar shape.

## 4. Trade-level detail

**Exit-reason distribution per window:**

| window | rule | stop | open_at_end |
|---|---:|---:|---:|
| covid | 7 | 1 | 2 |
| bear-2022 | 22 | — | — |
| bull-2024 | 22 | 1 | 2 |
| recent | 23 | — | 3 |

No `target` exits appear in any window for this card, by construction — the take-profit is removed.

**Best and worst trades:**

| window | best | worst |
|---|---|---|
| covid | NVDA, 2020-04-07→open at end, +36.86% | AMD, 2020-02-19→2020-02-25, stop, −11.91% |
| bear-2022 | QCOM, 2022-07-14→2022-08-23, rule, +5.19% | INTC, 2022-07-28→2022-07-29, rule, −11.30% |
| bull-2024 | AVGO, 2025-04-28→open at end, +52.74% | AVGO, 2024-12-18→2025-01-28, stop, −13.20% |
| recent | MRVL, 2026-03-09→2026-07-08, rule, +155.82% | AMD, 2026-07-23→2026-07-28, rule, −14.36% |

The `recent` best trade (MRVL, +155.82%) is the largest single-trade return in the A family this
round by a wide margin, and it is the direct mechanism behind §3b.

**Every stopped-out trade against the nominal 12% stop.** Only two stop-outs occurred in this card
across all four windows — far fewer than any other A-family card, because with no take-profit
trimming winners, fewer positions are open at any given moment to be stopped:

| window | symbol | entry → exit | realised loss | nominal | gap |
|---|---|---|---:|---:|---:|
| covid | AMD | 2020-02-19 → 2020-02-25 | −11.91% | −12.00% | +0.09pp |
| bull-2024 | AVGO | 2024-12-18 → 2025-01-28 | −13.20% | −12.00% | −1.20pp |

Neither is severe by the family's standards (contrast `A-rotation`'s and `A1`'s recent-window
stop-outs, several of which gapped 5–8 points past nominal). `bear-2022` and `recent` had no
stop-outs at all in this card.

## 5. Fragility

IQR of 47.38 points is the widest in the A family — more than four times `A2`'s 21.26 and materially
wider than `A-rotation`'s own 29.37. Removing a cap on winners does not just raise the ceiling, it
widens the whole distribution: with nothing trimming a position early, this card's result in any
given window depends heavily on whether that window happened to contain one exceptional trend (MRVL
in `recent`) or not (every other window). A median of −0.79% sitting between a −27.41% window and a
+149.56% window is close to uninformative on its own; the take-profit's absence converts this already
correlation-driven, concentrated card into an even higher-variance one.

## 6. Verdict

This card posted the round's single largest adjusted-excess result (+149.56%, recent) and its
verified-identical result in `bear-2022` shows the take-profit removal is genuinely inert in that
regime rather than merely untested. But the median (−0.79%) is negative, the hit rate is 2 of 4 (the
worst in the family), and the 47.38-point IQR means the one standout window is doing all the work —
this is the family's clearest illustration of a result that looks decisive in the ranking table and
is actually one trade's outcome away from looking mediocre.

**Not recommended for promotion to replace `A-rotation`.** `PROTOCOL.md` §6 requires beating the base
on median adjusted excess in two consecutive rounds; this round's median is *worse* than the base's
(−0.79% vs. +3.23%), so the condition is not close to being met regardless of the `recent`-window
outlier. **Recommendation: keep as a `variants/` line item and re-test unchanged in round 2**,
specifically because §3a's identical-in-bear-2022 result and §3b's single-trade-driven win in
`recent` are exactly the kind of findings that need a second, independent window set before either
can be trusted as more than this round's particular draw.

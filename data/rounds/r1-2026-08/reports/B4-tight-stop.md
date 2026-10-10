# B4-tight-stop — 8% Stop

Rank: **6th of 18** on the round's ranking. Ranked and eligible in all four windows this round can
run; blocked from `gfc` on the same NOW-history floor as the rest of the B family (first bar
2012-06-29, later than `gfc` needs).

## 1. What the card isolates, and the question it asks

Identical to `B-momentum` in universe, entry, exit, hold cap and position sizing. The **only**
change: the stop tightens from 12% to 8%. `library/README.md` poses the same question asked of the A
family's equivalent variant, `A4-tight-stop`, on a slower book: does a tighter stop help, or does it
just harvest noise — cutting positions on ordinary volatility before the trend has actually broken,
without reducing how badly the fills themselves land?

## 2. Results across the four windows

| window | trades | corrected return | benchmark | excess | adjusted excess | capital exposure | session exposure | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| covid | 6 | +22.93% | −8.71% | +31.64% | **+27.61%** | 53.76% | 69.89% | −4.58% | n/a (no closed trades) |
| bear-2022 | 5 | −5.63% | −25.14% | +19.51% | **−4.05%** | 6.29% | 27.55% | −6.65% | 0.00% |
| bull-2024 | 19 | +14.49% | +14.00% | +0.49% | **+7.21%** | 51.95% | 83.60% | −13.94% | 21.43% |
| recent | 19 | +22.18% | +20.62% | +1.56% | **+15.02%** | 34.71% | 67.87% | −26.88% | 0.00% |

Median adjusted excess **+11.12%**, worst **−4.05%** (bear-2022), best **+27.61%** (covid), IQR
**13.77 points**, hit rate 3 of 4. 49 trades total, two more than the base card — the extra trades are
stop-outs that free slots for re-entries the wider stop's book never generates (see §4).

## 3. Head-to-head against B-momentum, and the noise floor

| window | B4 adj. excess | B-momentum adj. excess | margin (B4 − base) | clears ~20pt floor? |
|---|---:|---:|---:|---:|
| covid | +27.61% | +27.61% | +0.00pp | no |
| bear-2022 | −4.05% | −5.15% | +1.10pp | no |
| bull-2024 | +7.21% | +7.44% | −0.22pp | no |
| recent | +15.02% | +16.98% | −1.96pp | no |

**None of the four window margins clears the ~20-point floor** established by `library/README.md`'s
twelve-ordering sensitivity study (53.9-point spread, σ = 21.2 points) and required by `PROTOCOL.md`
§7 — every margin here sits under 2 points, the tightest clustering around zero of any variant in the
family. The round's median comparison (B4 +11.12% vs base +12.21%, a 1.09-point gap) tells the same
story. On medians, tightening the stop is indistinguishable from doing nothing.

## 4. What the tighter stop actually did: more turnover, not better fills

The stop bound far more often at 8% than at 12%. Total stop-outs across the four windows: **10 for
this card against 4 for `B-momentum`** — more than double, entirely concentrated in `bear-2022`
(2 vs 2, but one session earlier in both cases), `bull-2024` (2 vs 0) and especially `recent` (6 vs
2).

**Every stopped-out trade against its own nominal stop, both cards, all four windows:**

| card | window | symbol | entry → exit | realised loss | nominal | gap |
|---|---|---|---|---:|---:|---:|
| B-momentum (12%) | bear-2022 | MU | 2022-02-11 → 2022-03-08 | −16.56% | −12.00% | −4.56pp |
| B4 (8%) | bear-2022 | MU | 2022-02-11 → 2022-03-07 | −10.53% | −8.00% | −2.53pp |
| B-momentum (12%) | bear-2022 | NVDA | 2022-03-29 → 2022-04-07 | −14.91% | −12.00% | −2.91pp |
| B4 (8%) | bear-2022 | NVDA | 2022-03-29 → 2022-04-06 | −13.20% | −8.00% | **−5.20pp** |
| B4 (8%) | bull-2024 | MRVL | 2024-09-03 → 2024-09-09 | −9.13% | −8.00% | −1.13pp |
| B4 (8%) | bull-2024 | GOOGL | 2024-10-30 → 2024-11-25 | −8.17% | −8.00% | −0.17pp |
| B-momentum (12%) | recent | AMZN | 2025-11-03 → 2025-11-19 | −12.47% | −12.00% | −0.47pp |
| B4 (8%) | recent | AMZN | 2025-11-03 → 2025-11-17 | −8.75% | −8.00% | −0.75pp |
| B-momentum (12%) | recent | AMD | 2026-01-05 → 2026-02-05 | −12.42% | −12.00% | −0.42pp |
| B4 (8%) | recent | AMD | 2026-01-05 → 2026-01-08 | −8.50% | −8.00% | −0.50pp |
| B4 (8%) | recent | NVDA | 2025-12-31 → 2026-02-05 | −7.82% | −8.00% | +0.18pp |
| B4 (8%) | recent | AMD | 2026-01-16 → 2026-02-05 | −13.93% | −8.00% | **−5.93pp** |
| B4 (8%) | recent | NVDA | 2026-02-11 → 2026-03-23 | −7.99% | −8.00% | +0.01pp |
| B4 (8%) | recent | NVDA | 2026-07-16 → 2026-07-30 | −8.05% | −8.00% | −0.05pp |

Average previous-close gap: **2.09 points** on the base card's four 12%-stop fills, **1.61 points**
on this card's ten 8%-stop fills — a smaller *average* gap, but a wider range, including the two
largest single gaps of either stop setting in this entire report: NVDA in `bear-2022` (−5.20pp) and
AMD in `recent` (−5.93pp, a −13.93% realised loss against an 8% nominal stop). **A tighter stop does
not fill more precisely** — the previous-close mechanism gaps past whichever threshold is set, and an
8% threshold is closer to ordinary daily volatility, so the same-sized adverse gap costs a larger
fraction of the position.

`recent` is the clearest case of the tighter stop generating pure churn rather than protection. Where
`B-momentum` holds one AMD position (entered 2026-01-05, stopped 2026-02-05 at −12.42%), this card's
tighter stop closes that same entry on 2026-01-08 at −8.50% — then, with the slot freed, re-enters
AMD on 2026-01-16 and is stopped out again on 2026-02-05 at −13.93%. Two losing trades (combined
notional loss larger than the base card's single −12.42%) where the base card took one. The same
pattern generates a new NVDA entry (2026-02-11, stopped 2026-03-23 at −7.99%) that has no counterpart
in `B-momentum`'s book at all, because the base card's wider stop never freed that slot. None of this
round's extra turnover from the tighter stop produced a winning trade.

## 5. Trade-level detail (remaining)

**Exit-reason distribution per window:**

| window | rule | stop | open_at_end |
|---|---:|---:|---:|
| covid | — | — | 6 |
| bear-2022 | 3 | 2 | — |
| bull-2024 | 12 | 2 | 5 |
| recent | 7 | 6 | 6 |

Six of `recent`'s 19 trades are stop-outs — the highest stop share of any card-window combination in
the B family this round.

**Best and worst trades:**

| window | best | worst |
|---|---|---|
| covid | MRVL, 2020-04-16→open at end, +38.80% (unrealised) | AMD, 2020-04-14→open at end, +0.65% (unrealised) |
| bear-2022 | MSFT, 2022-04-04→2022-04-07, rule, −4.43% | NVDA, 2022-03-29→2022-04-06, stop, −13.20% |
| bull-2024 | AVGO, 2025-05-08→open at end, +39.92% (unrealised) | MRVL, 2024-09-03→2024-09-09, stop, −9.13% |
| recent | MRVL, 2026-03-11→open at end, +130.65% (unrealised) | AMD, 2026-01-16→2026-02-05, stop, −13.93% |

Note this card's worst trades in `bear-2022` and `bull-2024` are both stop-outs where `B-momentum`'s
worst trades in those windows were also its stop-outs (`bear-2022`: MU, not NVDA — the tighter stop
changes *which* trade is worst) — the tighter stop does not simply scale down the base card's losses,
it reorders them.

## 6. Defended or absent

Same structural absence through `covid` as every card in the family: earliest entry 2020-03-30, one
week after SPY's bottom — see `B-momentum`'s report §3; the stop threshold affects exits only and
changes nothing about this. `bear-2022` capital exposure of 6.29% is marginally below the base card's
6.44%, consistent with the tighter stop closing the same two losers slightly earlier — the card is
absent from the drawdown for the same reason as the rest of the family, with the tighter stop
trimming a fraction of a point off an already-small number.

## 7. Verdict

Median adjusted excess +11.12%, the second-lowest in the B family, on the second-narrowest IQR
(13.77 points). Every window margin against `B-momentum` sits under 2 points — the tightest
clustering of any variant, meaning this round supplies unusually clean evidence that the tighter stop
is, at the aggregate level, a wash against the base card.

But §4's trade-level detail says more than the medians do: the tighter stop **more than doubled stop
frequency (10 vs 4)**, produced the two worst previous-close gaps in the report (−5.20pp on NVDA,
−5.93pp on AMD), and generated extra churn trades (a second AMD entry, a new NVDA entry) that were
also losers. None of that shows up as a large adjusted-excess penalty because the position sizes
involved are the same 15% either way and the extra losses are small individually — but it is a real
cost in trade count and fill quality for a change that produced no offsetting benefit this round.

**Recommendation: do not promote to replace `B-momentum` this round; the round-1 evidence leans
mildly negative on the tighter stop rather than neutral.** `PROTOCOL.md` §6's replacement bar (two
consecutive rounds of a beaten base) is not met regardless. Unlike `B2` and `B3`, where the base-card
margin is a clean null, this card's aggregate null sits on top of a trade-level pattern — more
stop-outs, no better fills, added churn — that argues against carrying the change forward without a
second round's confirmation that the `recent`-window stop-out cluster was not itself a one-window
artifact of two names (AMD, NVDA) gapping unusually hard in that period.

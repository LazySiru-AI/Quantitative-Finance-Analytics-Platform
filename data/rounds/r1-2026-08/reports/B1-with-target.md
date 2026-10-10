# B1-with-target — 25% Take-Profit Added

Rank: **8th of 18** on the round's ranking, last of the five B-family cards. Ranked and eligible in
all four windows this round can run; blocked from `gfc` on the same NOW-history floor as the rest of
the B family (first bar 2012-06-29, later than `gfc` needs).

## 1. What the card isolates, and the question it asks

Identical to `B-momentum` in universe, entry, exit, stop, hold cap and position sizing. The **only**
change: a 25% take-profit bracket is added (`take_profit_pct = 0.25`), where the base card has none.

This is the most direct test available in the B family, because it contradicts the base card's own
author on a measured, stated position. The author tested fixed take-profits at design time and found
they cut mean per-signal return from roughly triple the uncapped figure down to 2–9%, concluding that
"this strategy's edge is concentrated in a minority of large winners, which is exactly what a
take-profit would have amputated." `B1` asks, on this round's actual four windows: does a 25% target
in fact amputate B-momentum's winners, or does letting a position run past 25% just as often give
the gain back before the trend-break rule finally exits it?

## 2. Results across the four windows

| window | trades | corrected return | benchmark | excess | adjusted excess | capital exposure | session exposure | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| covid | 8 | +19.51% | −8.71% | +28.22% | **+23.18%** | 42.20% | 69.89% | −4.58% | 100.00% |
| bear-2022 | 5 | −6.77% | −25.14% | +18.37% | **−5.15%** | 6.44% | 27.55% | −7.77% | 0.00% |
| bull-2024 | 20 | +25.26% | +14.00% | +11.26% | **+19.58%** | 40.59% | 80.00% | −6.31% | 38.89% |
| recent | 19 | +2.38% | +20.62% | −18.24% | **−3.02%** | 26.18% | 69.08% | −8.93% | 28.57% |

Median adjusted excess **+8.28%**, worst **−5.15%** (bear-2022), best **+23.18%** (covid), IQR
**24.03 points** — second-widest in the family, behind only `B3-concentrated`'s 26.45 — hit rate 2 of
4 windows positive, the lowest hit rate of any B-family card. 52 trades total, the most of any
B-family card, seven more than the base.
`bear-2022` is byte-identical to `B-momentum`'s row: the target never fired in that window (see §4).

## 3. Head-to-head against B-momentum, and the noise floor

| window | B1 adj. excess | B-momentum adj. excess | margin (B1 − base) | clears ~20pt floor? |
|---|---:|---:|---:|---:|
| covid | +23.18% | +27.61% | −4.43pp | no |
| bear-2022 | −5.15% | −5.15% | +0.00pp | no |
| bull-2024 | +19.58% | +7.44% | +12.14pp | no |
| recent | −3.02% | +16.98% | **−20.00pp** | at the edge |

Three of four margins sit well inside the ~20-point floor `library/README.md`'s twelve-ordering
sensitivity study establishes (53.9-point spread, σ = 21.2 points) and `PROTOCOL.md` §7 requires this
comparison be judged against. The fourth, `recent`, lands at −20.00 points almost exactly on that
floor — not clearly inside it, not clearly beyond it. On the round's median (B1 +8.28% vs base
+12.21%, a 3.93-point gap), B1 trails, but by less than any single window's margin above, which is
itself the tell: a four-window median built from margins this size is not a result that has
demonstrated the take-profit costs return. It has demonstrated that this round cannot settle the
question on medians alone — which is exactly why §4 below looks at the trades directly instead.

## 4. The take-profit question, answered at the trade level

`B1` took 15 target exits across three windows (zero in `bear-2022` — the target never fires in a
window where every trade loses money). Each can be matched to `B-momentum`'s own trade on the same
symbol and entry date, which shares every rule except the target and so shows what would have
happened had the position been allowed to keep running. Fourteen of fifteen matches exist in the
base card's log; one (`MU`, `covid`, entered 2020-06-04) has no base-card counterpart because the
target freed a slot B-momentum's book didn't have free, and is a new trade rather than a foreclosed
one.

**Matches against a `B-momentum` position still open at its window's close** (unrealised, so these
compare a locked-in gain to a paper mark, not to a completed trade):

| window | symbol | entry | B1 target exit | B-mom mark at window close | gap |
|---|---|---|---:|---:|---:|
| covid | NFLX | 2020-03-30 | +24.14% (34 bars) | +25.29% (64 bars, open) | +1.15pp to base |
| covid | NVDA | 2020-04-07 | +26.65% (29 bars) | +36.86% (58 bars, open) | +10.21pp to base |
| covid | MRVL | 2020-04-16 | +27.98% (31 bars) | +38.80% (52 bars, open) | +10.82pp to base |
| covid | AMZN | 2020-04-08 | +30.74% (43 bars) | +36.44% (57 bars, open) | +5.70pp to base |
| bull-2024 | AVGO | 2025-05-08 | +26.29% (19 bars) | +39.92% (71 bars, open) | +13.63pp to base |
| bull-2024 | NVDA | 2025-05-15 | +27.24% (41 bars) | +30.54% (66 bars, open) | +3.30pp to base |
| recent | MRVL | 2026-03-11 | +31.98% (21 bars) | **+130.65%** (110 bars, open) | +98.68pp to base |
| recent | AMD | 2026-04-09 | +29.48% (10 bars) | **+107.78%** (90 bars, open) | +78.30pp to base |

**Matches against a `B-momentum` position that *closed* before the window ended** — the only
apples-to-apples comparisons in this round, because both cards' positions are actually finished:

| window | symbol | entry | B1 target exit | B-mom eventual exit | gap |
|---|---|---|---:|---:|---:|
| bull-2024 | AVGO | 2024-09-13 | +38.87% (65 bars) | rule, 2025-03-07, **+12.48%** (119 bars) | **−26.39pp to base** |
| bull-2024 | TSM | 2024-09-13 | +28.31% (79 bars) | rule, 2025-02-28, **+4.00%** (114 bars) | **−24.32pp to base** |
| bull-2024 | AMZN | 2024-09-18 | +25.43% (86 bars) | rule, 2025-03-11, **+3.89%** (118 bars) | **−21.54pp to base** |
| bull-2024 | NFLX | 2025-04-22 | +27.87% (44 bars) | open at end, +20.69% (83 bars, open) | −7.18pp to base |
| bull-2024 | TSM | 2025-05-15 | +26.91% (43 bars) | open at end, +18.32% (66 bars, open) | −8.59pp to base |
| recent | AVGO | 2026-04-14 | +30.79% (35 bars) | rule, 2026-07-06, **−1.24%** (56 bars) | **−32.03pp to base** |
| recent | TSM | 2026-04-08 | +18.48% (52 bars) | open at end, +11.59% (91 bars, open) | −6.89pp to base |

**On the four positions where both cards' trades were fully realised — `B-momentum` also closed
before window end — the target won all four times**, protecting an average of roughly 26 points that
the uncapped version gave back before its eventual rule exit: AVGO (9/13 bull-2024) target-locked
+38.87% against a base-card eventual close of +12.48%; TSM (9/13) +28.31% against +4.00%; AMZN (9/18)
+25.43% against +3.89%; AVGO (4/14 recent) +30.79% against the base card actually finishing in the
red at −1.24%. In every one of these cases the position kept running past 25% under `B-momentum`'s
rules, and then gave nearly all of it back before the trend-break finally fired.

Against the eight matches where `B-momentum`'s position is still open (unrealised, mark-to-market at
window close, not a completed trade), the picture flips: three show the target ahead anyway (NFLX,
TSM 5/15 bull-2024, TSM 4/8 recent), and five show a large or very large unrealised lead for letting
the position run — the two `recent`-window cases (MRVL +98.68pp, AMD +78.30pp unrealised) are the
largest gaps in either direction in this entire comparison, and they are exactly the "amputated
winner" scenario the author's thesis describes. But they are marks on positions still open as of
2026-08-18, not finished trades — the AVGO and TSM cases directly above show that a position this far
ahead can give back most or all of its gain by the time it actually exits.

**Verdict on the take-profit question.** The trade-level evidence does not settle the author's claim
either way, and it should not be read as doing so. What it shows is more specific and more useful:
every completed, apples-to-apples comparison in this round favoured the target, by an average of
about 26 points, because the uncapped exits that eventually fired did so well after the position had
round-tripped from a much larger paper gain. The cases favouring no target are real but every one of
them is still an open position — a lower bound on what letting it run has cost so far, and, on the
evidence of the closed cases beside it, not a number that should be assumed to hold once those
positions actually exit.

## 5. Trade-level detail (remaining)

**Exit-reason distribution per window:**

| window | rule | stop | target | open_at_end |
|---|---:|---:|---:|---:|
| covid | 1 | — | 4 | 3 |
| bear-2022 | 3 | 2 | — | — |
| bull-2024 | 11 | — | 7 | 2 |
| recent | 8 | 2 | 4 | 5 |

The `bear-2022` distribution is identical to `B-momentum`'s: no target fires in a window where every
position loses money. The `MU` (2020-06-04) and `TSM` (2020-06-05) `covid` trades exist only in this
card's log — target exits earlier in the window freed slots the base card's fully-committed book
never had.

**Best and worst trades:**

| window | best | worst |
|---|---|---|
| covid | AMZN, 2020-04-08→2020-06-10, target, +30.74% | AMD, 2020-04-14→open at end, +0.65% (unrealised) |
| bear-2022 | MSFT, 2022-04-04→2022-04-07, rule, −4.43% | MU, 2022-02-11→2022-03-08, stop, −16.56% |
| bull-2024 | AVGO, 2024-09-13→2024-12-16, target, +38.87% | MRVL, 2024-09-03→2024-09-09, rule, −9.13% |
| recent | MRVL, 2026-03-11→2026-04-10, target, +31.98% | AMZN, 2025-12-29→2026-02-06, rule, −12.70% |

**Every stopped-out trade against the nominal 12% stop** — identical fills to `B-momentum` in both
windows this card was stopped out, because the target only changes winning exits:

| window | symbol | entry → exit | realised loss | nominal | gap |
|---|---|---|---:|---:|---:|
| bear-2022 | MU | 2022-02-11 → 2022-03-08 | −16.56% | −12.00% | −4.56pp |
| bear-2022 | NVDA | 2022-03-29 → 2022-04-07 | −14.91% | −12.00% | −2.91pp |
| recent | AMZN | 2025-11-03 → 2025-11-19 | −12.47% | −12.00% | −0.47pp |
| recent | AMD | 2026-01-05 → 2026-02-05 | −12.42% | −12.00% | −0.42pp |

## 6. Defended or absent

Same structural absence through `covid` as the rest of the family: earliest entry 2020-03-30, one
week after SPY's bottom, for the same trend-confirmation reason set out in `B-momentum`'s report §3 —
this is not specific to the target and this card adds nothing to that finding. In `bear-2022`, this
card is byte-identical to the base card: five trades, zero target exits, 6.44% capital exposure, all
losses. The target added nothing to and subtracted nothing from this card's behaviour in a window
where every signal was wrong before any target could be reached.

## 7. Verdict

Median adjusted excess +8.28%, the lowest of the five B-family cards, on the lowest hit rate (2 of 4)
and the second-widest IQR (24.03 points). Against `B-momentum`, three of four window margins sit well inside
the ~20-point noise floor and the fourth sits almost exactly on it — this round's medians alone do
not show the target costing return, or gaining it.

**Recommendation: retain as a variant under `PROTOCOL.md` §6, do not promote to replace `B-momentum`
this round.** §6 requires a variant to beat its base on median adjusted excess in two consecutive
rounds before it can replace it, and this round's median runs the other way regardless. But this
card is the one variant in the family with a genuinely informative round-1 result rather than a
noise-floor null: §4's trade-level match-up is the strongest evidence produced anywhere in this round
on the base card's own pre-registered claim, and it complicates that claim rather than confirming or
refuting it outright — the target protected real, realised gains in every completed comparison this
round produced, while the two largest counter-examples are still open. Round 2 should re-run this
comparison specifically to let the `recent`-window MRVL and AMD positions resolve, since those two
trades alone currently account for most of the case against the target.

# B3-concentrated — 4 Slots at 22%

Rank: **2nd of 18** on the round's ranking. Ranked and eligible in all four windows this round can
run; blocked from `gfc` on the same NOW-history floor as the rest of the B family (first bar
2012-06-29, later than `gfc` needs).

## 1. What the card isolates, and the question it asks

Identical to `B-momentum` in universe, entry, exit, stop and hold cap. The **only** change: 4
concurrent slots at 22% position sizing each (88% maximum deployed), where the base card runs 6
slots at 15% (90% maximum deployed) — a similar ceiling on total capital, reached through fewer,
larger positions. `library/README.md` frames the question as whether B's edge concentrates in its
best signals or needs breadth to show up.

This card took the fewest trades of any B-family card in every window it ran — 36 total against the
base card's 47 — and the runner logged **zero broker rejections** for either card in any window. The
gap is not visible as explicit turn-aways in the trade log: with only 4 slots, a qualifying signal
that arrives with the book full simply generates no order, rather than an order the broker refuses.
The 11-trade shortfall against `B-momentum` is this card silently passing on signals a 6-slot book
would have taken, not a cash-headroom problem — at 22% × 4, the book never approaches its own
capital ceiling the way a true cash-constrained design would.

## 2. Results across the four windows

| window | trades | corrected return | benchmark | excess | adjusted excess | capital exposure | session exposure | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| covid | 4 | +21.85% | −8.71% | +30.56% | **+26.68%** | 55.46% | 69.89% | −6.03% | n/a (no closed trades) |
| bear-2022 | 5 | −10.17% | −25.14% | +14.97% | **−7.75%** | 9.60% | 27.55% | −11.61% | 0.00% |
| bull-2024 | 15 | +12.52% | +14.00% | −1.47% | **+4.53%** | 57.08% | 83.60% | −15.83% | 25.00% |
| recent | 12 | +40.05% | +20.62% | +19.43% | **+31.59%** | 41.02% | 69.88% | −30.41% | 0.00% |

Median adjusted excess **+15.61%**, worst **−7.75%** (bear-2022 — the worst window of any B-family
card), best **+31.59%** (recent — the best window of any B-family card), IQR **26.45 points**, the
widest in the entire B family — wider than `B1-with-target`'s 24.03, the next-widest. Hit rate 3 of
4. 36 trades total, fewest in the family. This card carries both the single best and (per adjusted excess) among
the worst window results the B family produced this round — concentration cuts both ways, plainly.

## 3. Head-to-head against B-momentum, and the noise floor

| window | B3 adj. excess | B-momentum adj. excess | margin (B3 − base) | clears ~20pt floor? |
|---|---:|---:|---:|---:|
| covid | +26.68% | +27.61% | −0.93pp | no |
| bear-2022 | −7.75% | −5.15% | −2.60pp | no |
| bull-2024 | +4.53% | +7.44% | −2.91pp | no |
| recent | +31.59% | +16.98% | +14.61pp | no |

**None of the four window margins clears the ~20-point floor** established by `library/README.md`'s
twelve-ordering sensitivity study (53.9-point spread, σ = 21.2 points) and required by `PROTOCOL.md`
§7. The round's median comparison (B3 +15.61% vs base +12.21%, a 3.40-point gap) is smaller than any
single-window margin above and well inside the noise band. `recent`'s +14.61-point margin is the
largest of the four and the only one that leans toward a real effect, but at under 15 points it is
still short of the floor by a wide margin — this round cannot distinguish "4×22 concentrates the edge"
from "4×22 happened to hold the two positions that ran hardest in the one window where a handful of
huge winners dominated the book" (see §4).

## 4. Trade-level detail

**Exit-reason distribution per window:**

| window | rule | stop | open_at_end |
|---|---:|---:|---:|
| covid | — | — | 4 |
| bear-2022 | 3 | 2 | — |
| bull-2024 | 12 | — | 3 |
| recent | 6 | 2 | 4 |

**Best and worst trades:**

| window | best | worst |
|---|---|---|
| covid | NVDA, 2020-04-07→open at end, +36.86% (unrealised) | AMD, 2020-04-14→open at end, +0.65% (unrealised) |
| bear-2022 | MSFT, 2022-04-04→2022-04-07, rule, −4.43% | MU, 2022-02-11→2022-03-08, stop, −16.56% |
| bull-2024 | AVGO, 2025-05-08→open at end, +39.92% (unrealised) | MRVL, 2024-09-03→2024-09-09, rule, −9.13% |
| recent | MRVL, 2026-03-11→open at end, +130.65% (unrealised) | AMZN, 2025-12-29→2026-02-06, rule, −12.70% |

`recent`'s +31.59% adjusted excess — this card's best window and the best window any B-family card
posted — is carried by the same two large unrealised positions the base card holds (MRVL +130.65%,
AMD +107.78%, both still open at window close), concentrated across only 4 slots instead of 6.
Narrower breadth means these two winners are a *larger* fraction of this card's book than of
`B-momentum`'s, which is the direct arithmetic of "concentration" — and it is also why this window's
result should be read with the same caveat as the base card's: two open positions, not two completed
trades.

**Every stopped-out trade against the nominal 12% stop.** Fills are the same two crashes as the base
card (MU, NVDA in `bear-2022`; AMZN, AMD in `recent`), with realised losses differing by fractions of
a point from `B-momentum`'s own fills — consistent with the same underlying price path and a slightly
different position-sizing rounding, not a different stop mechanism:

| window | symbol | entry → exit | realised loss | nominal | gap |
|---|---|---|---:|---:|---:|
| bear-2022 | MU | 2022-02-11 → 2022-03-08 | −16.56% | −12.00% | −4.56pp |
| bear-2022 | NVDA | 2022-03-29 → 2022-04-07 | −14.91% | −12.00% | −2.91pp |
| recent | AMZN | 2025-11-03 → 2025-11-19 | −12.47% | −12.00% | −0.47pp |
| recent | AMD | 2026-01-05 → 2026-02-05 | −12.42% | −12.00% | −0.42pp |

## 5. Defended or absent

Same structural absence through `covid` as every card in the family: earliest entry 2020-03-30, one
week after SPY's bottom — see `B-momentum`'s report §3. `bear-2022` is where this card's narrower book
shows its clearest cost: capital exposure of 9.60%, the highest of any B-family card in that window
(base card: 6.44%), because the same five losing trades are sized larger across fewer slots. The
result is this card's worst window by a wide margin (−7.75% adjusted excess, −11.61% max drawdown,
both worse than every other B-family card here) — concentration meant the same wrong signals cost
more capital, not less, when the market was actually falling.

## 6. Verdict

Rank 2nd of 18, median adjusted excess +15.61%, but built from the widest window-to-window range in
the family: best window any B card posted (+31.59%, `recent`) and worst window any B card posted
(−7.75%, `bear-2022`). Against `B-momentum` — the comparison that isolates the one decision this card
actually changed — none of the four window margins clears the ~20-point noise floor, and the
`recent`-window lead that drives the median rests on two unrealised positions this card holds in
larger proportion than the base does.

**Recommendation: do not promote to replace `B-momentum` this round.** `PROTOCOL.md` §6 requires a
variant to beat its base on median adjusted excess in two consecutive rounds; one round exists.
**The concentration question `library/README.md` poses — does the edge concentrate in the best
signals, or does the strategy need breadth — is not answered by this round.** The evidence points
both ways within the same four windows: `recent` looks like concentration paying off, `bear-2022`
looks like concentration amplifying a bad book, and both effects are consistent with nothing more
than "fewer, larger positions have more of each individual trade's outcome in them," which is true of
concentration whether or not the underlying edge is real. Round 2 should track whether this card's
wide dispersion (26.45-point IQR) narrows or widens as more windows accumulate — a persistently wide
IQR would itself be evidence against the "concentrates the edge" reading, since a real edge
concentrated correctly should show up as a *higher* median with comparable, not wider, spread.

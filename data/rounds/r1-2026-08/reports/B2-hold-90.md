# B2-hold-90 — 90-Day Max Hold

Rank: **1st of 18** on the round's ranking — the top result this round produced. Ranked and eligible
in all four windows this round can run; blocked from `gfc` on the same NOW-history floor as the rest
of the B family (first bar 2012-06-29, later than `gfc` needs).

## 1. What the card isolates, and the question it asks

Identical to `B-momentum` in universe, entry, exit, stop and position sizing. The **only** change:
`max_hold_days` is halved from 180 to 90. `library/README.md` frames the question as design-time
context — "ten of B's 41 exits were time-stops" in the author's own design-window backtest — asking
whether the long leash is earning its exposure. **That statistic does not reproduce in this round's
four windows**: `B-momentum` at 180 days took zero time-cap exits in any of them. The 90-day cap in
this card, however, did bind — six times, three in `bull-2024` and three in `recent` — meaning the
question this round can actually answer is narrower than the one posed at design time: not "does the
long leash matter" in the abstract, but "in the specific positions where a 90-day cap forces an exit
that a 180-day cap would not have, what does the extra runway do?"

## 2. Results across the four windows

| window | trades | corrected return | benchmark | excess | adjusted excess | capital exposure | session exposure | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| covid | 6 | +22.93% | −8.71% | +31.64% | **+27.61%** | 53.76% | 69.89% | −4.58% | n/a (no closed trades) |
| bear-2022 | 5 | −6.77% | −25.14% | +18.37% | **−5.15%** | 6.44% | 27.55% | −7.77% | 0.00% |
| bull-2024 | 19 | +27.69% | +14.00% | +13.69% | **+20.59%** | 50.75% | 80.00% | −6.31% | 21.43% |
| recent | 18 | +22.19% | +20.62% | +1.57% | **+15.08%** | 34.48% | 69.88% | −22.08% | 21.43% |

Median adjusted excess **+17.83%**, worst **−5.15%** (bear-2022), best **+27.61%** (covid), IQR
**12.32 points** — the tightest of any B-family card — hit rate 3 of 4. 48 trades total. `covid` and
`bear-2022` rows are identical to `B-momentum`'s: the 90-day cap never binds inside either window
(covid's positions are all still under 90 bars old at window close; bear-2022's five trades all
close within 54 bars, well inside even the 90-day cap).

## 3. Head-to-head against B-momentum, and the noise floor

| window | B2 adj. excess | B-momentum adj. excess | margin (B2 − base) | clears ~20pt floor? |
|---|---:|---:|---:|---:|
| covid | +27.61% | +27.61% | +0.00pp | no |
| bear-2022 | −5.15% | −5.15% | +0.00pp | no |
| bull-2024 | +20.59% | +7.44% | +13.15pp | no |
| recent | +15.08% | +16.98% | −1.90pp | no |

**None of the four window margins clears the ~20-point floor** `library/README.md`'s twelve-ordering
sensitivity study (53.9-point spread, σ = 21.2 points) sets, and which `PROTOCOL.md` §7 requires this
comparison be judged against. The card's rank-1 placement and its median lead over `B-momentum`
(+17.83% vs +12.21%, a 5.62-point gap) look decisive stacked against the round's other 17 cards, but
the margin against its own base — the only comparison that isolates this card's one changed decision
— is smaller than every other card's largest single-window swing in this family, and well inside the
noise this program's own prior work has already measured on an *identical* card reordered twelve
ways. **This is the headline result of this report: B2's rank-1 finish is not evidence that a 90-day
hold cap beats a 180-day one.** It is evidence that this card had a good four-window draw, on top of
a base card that itself had a good four-window draw.

## 4. What the 90-day cap actually did, where it bound

The six time-cap exits are the only trades in this card's log that differ mechanically from
`B-momentum`'s. In `bull-2024`, all three matched the base card's still-open, still-running position
at the point the 90-day cap forced an exit — and in every one of the three, the forced exit locked in
*more* than the base card eventually kept:

| symbol | entry | B2 time-cap exit (90 bars) | B-momentum eventual result | gap |
|---|---|---:|---:|---:|
| AVGO | 2024-09-13 | +46.61% (2025-01-24) | rule, 2025-03-07, +12.48% (119 bars) | **−34.13pp to base** |
| TSM | 2024-09-13 | +31.20% (2025-01-24) | rule, 2025-02-28, +4.00% (114 bars) | **−27.20pp to base** |
| AMZN | 2024-09-18 | +28.07% (2025-01-29) | rule, 2025-03-11, +3.89% (118 bars) | **−24.18pp to base** |

These are the same three positions — same symbols, same entry dates — that `B1-with-target`'s
25%-target exits also locked in ahead of `B-momentum`'s eventual round-trip (see that report's §4).
The 90-day cap and the 25% target arrived at the same conclusion from two different mechanisms in
`bull-2024`: whatever pushed AVGO, TSM and AMZN back down from a large paper gain in this window did
so before either a target or a 90-day clock could be blamed for missing more, and after either one
would already have exited.

In `recent`, the three time-cap exits are less one-sided — the cap simply landed close to where the
window itself ended:

| symbol | entry | B2 time-cap exit (90 bars) | B-momentum's mark at same point | gap |
|---|---|---:|---:|---:|
| MRVL | 2026-03-11 | +119.39% (2026-07-21) | open at end, +130.65% (2026-08-18, 110 bars) | +11.26pp to base (unrealised) |
| TSM | 2026-04-08 | +16.00% (2026-08-17) | open at end, +11.59% (2026-08-18, 91 bars) | −4.41pp to base |
| AMD | 2026-04-09 | +109.03% (2026-08-18) | open at end, +107.78% (2026-08-18, 90 bars) | −1.25pp to base |

For AMD, the 90-day cap and the window's own end essentially coincide, so the two cards' figures are
nearly identical by construction. MRVL is the one case in this window where the extra 20 days of
`B-momentum`'s longer leash shows a further unrealised gain — but as `B-momentum`'s own report notes,
that position is still open at window close and not a completed trade.

## 5. Trade-level detail

**Exit-reason distribution per window:**

| window | rule | stop | time | open_at_end |
|---|---:|---:|---:|---:|
| covid | — | — | — | 6 |
| bear-2022 | 3 | 2 | — | — |
| bull-2024 | 11 | — | 3 | 5 |
| recent | 9 | 2 | 3 | 4 |

**Best and worst trades:**

| window | best | worst |
|---|---|---|
| covid | MRVL, 2020-04-16→open at end, +38.80% (unrealised) | AMD, 2020-04-14→open at end, +0.65% (unrealised) |
| bear-2022 | MSFT, 2022-04-04→2022-04-07, rule, −4.43% | MU, 2022-02-11→2022-03-08, stop, −16.56% |
| bull-2024 | AVGO, 2024-09-13→2025-01-24, time, +46.61% | MRVL, 2024-09-03→2024-09-09, rule, −9.13% |
| recent | MRVL, 2026-03-11→2026-07-21, time, +119.39% | AMZN, 2025-12-29→2026-02-06, rule, −12.70% |

**Every stopped-out trade against the nominal 12% stop** — identical fills to `B-momentum`, since the
hold cap only changes exits that survive to the cap:

| window | symbol | entry → exit | realised loss | nominal | gap |
|---|---|---|---:|---:|---:|
| bear-2022 | MU | 2022-02-11 → 2022-03-08 | −16.56% | −12.00% | −4.56pp |
| bear-2022 | NVDA | 2022-03-29 → 2022-04-07 | −14.91% | −12.00% | −2.91pp |
| recent | AMZN | 2025-11-03 → 2025-11-19 | −12.47% | −12.00% | −0.47pp |
| recent | AMD | 2026-01-05 → 2026-02-05 | −12.42% | −12.00% | −0.42pp |

## 6. Defended or absent

Same structural absence through `covid` as every card in this family, and for the same reason: the
entry rule cannot fire until the trend has already turned, so the earliest entry across the whole B
family — this card included — is 2020-03-30, one week after SPY's bottom. See `B-momentum`'s report
§3 for the full argument; nothing about a shorter hold cap changes it, since the cap only affects
exits, never entries. In `bear-2022`, this card is byte-identical to the base: 6.44% capital exposure
on five losing trades, less wrong than the benchmark because little capital was at risk, not because
anything was avoided.

## 7. Verdict

Rank 1st of 18 this round, median adjusted excess +17.83%, the tightest IQR in the B family (12.32
points) and a 3-of-4 hit rate. Read plainly against the rest of the field, this is the best single
result this round produced. Read against its own base card — the comparison that actually isolates
the one decision this card changed — every window margin sits at or well inside the ~20-point noise
floor, and the card's only real behavioural difference from `B-momentum` (the three `bull-2024`
time-cap exits) happened to land on the same side as `B1-with-target`'s target exits on the identical
three positions, for reasons that have nothing to do with a 90-day clock specifically.

**Recommendation: do not promote to replace `B-momentum` this round.** `PROTOCOL.md` §6 requires a
variant to beat its base on median adjusted excess in two consecutive rounds before replacement, and
one round is one draw regardless of how the rank table reads. **Resist the rank-1 headline as
evidence for the 90-day hypothesis** — the honest statement of this round's result is that halving
the hold cap did not measurably help or hurt against `B-momentum` specifically, even though it beat
every other card in the round. Round 2 should re-run this comparison and pay particular attention to
whether the `bull-2024` AVGO/TSM/AMZN pattern (early exit near a peak, base card gives most of it
back later) repeats — three matches in one window is suggestive but not yet a demonstrated effect.

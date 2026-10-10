# B-momentum — Strategy B, Confirmed Acceleration

Rank: **4th of 18** on the round's ranking (median adjusted excess). Ranked and eligible in all four
windows this round can run. **Blocked from `gfc`**: the universe includes NOW, first bar 2012-06-29,
later than the window needs (`<= 2006-10-27`). This holds for every card in the B family — none of
the five could run `gfc` this round.

## 1. What the card is

One entry condition, applied identically across a 12-name AI/cloud-infrastructure universe
(`NVDA AMD AVGO MU MRVL TSM META MSFT GOOGL NOW AMZN NFLX`): `ema(20) crosses_above ema(50) and
close > sma(200)` — a fresh medium-term acceleration inside an already-standing long-term uptrend,
not a bottom-pick. Exit is a trend break (`close crosses_below sma(200)`), backstopped by a 12%
stop, no take-profit, a 180-day hold cap, 6 concurrent slots at 15% each.

The author's design-time case for the "no take-profit" choice is explicit and measured: testing a
fixed take-profit and a fast EMA exit against simply riding to a stop or trend break, on the same
entry, found that capping gains at 8–30% cut mean per-signal return to 2–9% and a fast exit cut it
further to 3–5% with win rate down to 42–49%, against roughly triple the aggregate return for the
uncapped exit — "this strategy's edge is concentrated in a minority of large winners, which is
exactly what a take-profit would have amputated." Four variants test this and three other decisions
one at a time against this card: `B1-with-target` adds the 25% take-profit back; `B2-hold-90` halves
the hold cap; `B3-concentrated` trades 4 slots at 22% instead of 6 at 15%; `B4-tight-stop` cuts the
stop to 8%. Their reports carry the head-to-head detail against this one.

## 2. Results across the four windows

All figures use the corrected metrics from `DEFECTS.md`: `corrected_return = ending_equity /
starting_equity − 1` (not the runner's `total_return`, which is rebased to the first session's close),
`capital_exposure = Σ(quantity × entry_price × bars_held) / (sessions × starting_equity)` (not the
runner's `exposure`, which only counts sessions holding *something*), and `adjusted_excess =
corrected_return − capital_exposure × benchmark_return`.

| window | trades | corrected return | benchmark | excess | adjusted excess | capital exposure | session exposure | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| covid | 6 | +22.93% | −8.71% | +31.64% | **+27.61%** | 53.76% | 69.89% | −4.58% | n/a (no closed trades) |
| bear-2022 | 5 | −6.77% | −25.14% | +18.37% | **−5.15%** | 6.44% | 27.55% | −7.77% | 0.00% |
| bull-2024 | 19 | +15.20% | +14.00% | +1.21% | **+7.44%** | 55.48% | 83.60% | −15.22% | 21.43% |
| recent | 17 | +24.27% | +20.62% | +3.65% | **+16.98%** | 35.34% | 69.88% | −26.51% | 0.00% |

Median adjusted excess **+12.21%**, worst **−5.15%** (bear-2022), best **+27.61%** (covid), IQR
**15.35 points**, hit rate 3 of 4 windows positive. 47 trades total. Capital exposure runs well below
session exposure in every window — most sharply in `bear-2022` (6.44% capital vs 27.55% session) and
`recent` (35.34% vs 69.88%): the card holds *something* on most sessions it is in the market at all,
but the position sizing (15% per slot, 6 slots) and the frequency of small, short-lived trades mean
the raw session-presence figure overstates capital at risk by 20–30 points, the same D2 pattern the
program's defect log documents elsewhere.

## 3. Covid: crash-avoidance is structural, not a demonstrated defensive call

**No B-family card — this one included — entered a single position before 2020-03-30.** Every one
of this card's six `covid` trades opens on 2020-03-30 or later (NFLX and MSFT/MRVL's shared
2020-04-16 are the latest): `NFLX 2020-03-30, NVDA 2020-04-07, AMZN 2020-04-08, AMD 2020-04-14, MRVL
2020-04-16, MSFT 2020-04-16`. The `covid` window itself runs 2020-02-19 → 2020-06-30 (93 sessions);
SPY's crash bottomed 2020-03-23. The earliest entry here lands one week *after* the bottom, roughly
27 sessions into a 93-session window.

This is not a risk-management outcome. The entry rule is `ema(20) crosses_above ema(50) and close >
sma(200)` — a trend-*confirmation* signal that requires the medium-term average to have already
turned up through the long-term one while price sits above a 200-day average. During a fast crash,
`ema(20)` is falling faster than `ema(50)` and `close` drops below `sma(200)` almost immediately; the
crossing-above condition physically cannot fire until the recovery is already underway. The card was
never asked to decide whether to hold through the crash — the rule made that decision impossible to
reach. The +27.61% adjusted excess this window shows is arithmetic: sitting in cash while the
benchmark fell, then buying six names already in the process of recovering, against a benchmark
(−8.71%) that itself nets a shallow window-end loss because it, unlike this card, was exposed to the
whole drawdown. Capital exposure of 53.76% in this window describes the *recovery-phase* holding,
not a defensive posture through the crash — through the crash itself, this card's capital exposure
was zero.

## 4. Trade-level detail

**Exit-reason distribution per window:**

| window | rule | stop | open_at_end |
|---|---:|---:|---:|
| covid | — | — | 6 |
| bear-2022 | 3 | 2 | — |
| bull-2024 | 14 | — | 5 |
| recent | 9 | 2 | 6 |

No `covid` trade closed inside the window at all — all six were still open at `2020-06-30`, consistent
with entries landing only in the second half of a 93-session window and the 180-day hold cap never
binding that quickly.

**Best and worst trades:**

| window | best | worst |
|---|---|---|
| covid | MRVL, 2020-04-16→open at end, +38.80% (unrealised) | AMD, 2020-04-14→open at end, +0.65% (unrealised) |
| bear-2022 | MSFT, 2022-04-04→2022-04-07, rule, −4.43% | MU, 2022-02-11→2022-03-08, stop, −16.56% |
| bull-2024 | AVGO, 2025-05-08→open at end, +39.92% (unrealised) | MRVL, 2024-09-03→2024-09-09, rule, −9.13% |
| recent | MRVL, 2026-03-11→open at end, +130.65% (unrealised) | AMZN, 2025-12-29→2026-02-06, rule, −12.70% |

Every `bear-2022` trade is a loss — win rate is a real, not a null-substituted, 0.00% that window; all
five signals this card took were wrong. `recent` is starker still: of 11 *closed* trades that window,
all 11 lost money (win rate 0.00% on closed trades), and the window's positive +24.27% corrected
return rests entirely on two still-open positions at window close — MRVL +130.65% (110 bars) and AMD
+107.78% (90 bars). Both are unrealised marks at 2026-08-18, not completed trades; had the window
ended a month earlier or later, this window's headline number could look very different. This is the
single clearest instance in this card's record of the "concentrated in a minority of large winners"
mechanism its own thesis describes — and also the clearest reason not to read the `recent` figure as
a settled result.

**Every stopped-out trade against the nominal 12% stop.** Stops evaluate against the previous close,
not the intraday low, so a realised loss worse than 12% means the fill gapped past the threshold:

| window | symbol | entry → exit | realised loss | nominal | gap |
|---|---|---|---:|---:|---:|
| bear-2022 | MU | 2022-02-11 → 2022-03-08 | −16.56% | −12.00% | **−4.56pp** |
| bear-2022 | NVDA | 2022-03-29 → 2022-04-07 | −14.91% | −12.00% | −2.91pp |
| recent | AMZN | 2025-11-03 → 2025-11-19 | −12.47% | −12.00% | −0.47pp |
| recent | AMD | 2026-01-05 → 2026-02-05 | −12.42% | −12.00% | −0.42pp |

Four stop-outs, all four worse than nominal, averaging a 2.09-point gap. MU in `bear-2022` is the
worst single fill: entered at $91.33, stopped at $76.21 for −16.56% against a 12% nominal stop — a
4.56-point previous-close slippage, on a 16-bar hold. `covid` and `bull-2024` had no stop-outs at all
in this card.

## 5. Defended or absent

Judged on capital exposure and entry dates, this card was **absent, not defended**, through both of
this round's two down-market windows. `covid`: zero capital exposure before 2020-03-30, for the
reason in §3 — the entry rule cannot fire mid-crash, so there was no decision to hold or not hold
through the drawdown itself. `bear-2022`, a grinding rather than a shock decline (SPY −25.14% over
the full window), is more informative: this card *did* take five trades, all losses, for a −6.77%
result against −25.14% for the benchmark — a real +18.37% raw excess, but at only 6.44% capital
exposure. The card was less wrong than the market largely because it deployed a sixteenth of its
book, not because its rules identified anything to avoid; a coin flip taken at that exposure level
would show something similar. The adjusted-excess figure (−5.15%) makes this explicit: correcting for
how little capital was actually at risk, this window is a net negative once measured against the
exposure the card actually carried, not the exposure it could have carried.

## 6. Verdict

Positive median adjusted excess (+12.21%), a 3-of-4 hit rate, full eligibility on this round's four
runnable windows — this result does not trigger `PROTOCOL.md` §6's demotion condition (negative
median in two consecutive rounds). Rank 4th of 18 this round, ahead of every A-family card and two of
its own four variants.

But two qualifications belong beside that number. First, the `covid` result — the largest single
contributor to the median — is a structural artifact of an entry rule that cannot fire during a
crash, not a demonstrated defensive skill; §3 above should travel with any future citation of this
card's crash-window performance. Second, the `recent` result rests on two large unrealised positions
still open at window close; a settled comparison would need those trades to actually exit.

**Recommendation: retain in `library/base/` pending round 2.** No variant has beaten this card on
median adjusted excess in two consecutive rounds (only one round exists), so none is eligible to
replace it yet under §6 — and per each variant's own report, none of this round's four variant
margins against this card clears the ~20-point noise floor `library/README.md` and `PROTOCOL.md` §7
establish, so there is in any case no round-1 evidence that a variant should replace it. The most
useful thing round 2 can do for this card is close out the `recent` window's two open positions and
re-test the `covid` structural-absence finding against a crash window this card's universe can
actually reach earlier in — if one exists.

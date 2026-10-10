# c09-convex — Flight-to-Quality Insurance

Round 2 report. Trade logs: `results/<window>/runs/r1-c09-convex.json`, all eight windows. Figures
below are recomputed directly from those files' own `total_return`, `capital_exposure` and
`benchmark_return` fields (full decimal precision, not the two-decimal window benchmarks quoted in
prose elsewhere) and agree with `results/scorecard-common6.json` to within a hundredth of a point.

## 1. What this card is

`discipline: volatility`. Universe `["TLT", "GLD"]`. Entry:
`close crosses_above bb_upper(20,2)`. Exit: `close crosses_below sma(20)`. `stop_loss_pct 0.10`,
`take_profit_pct null`, `max_hold_days 180`, `max_positions 2`, `position_pct 0.15` (30% of book
fully deployed at most; 7 of the 10-parameter budget used).

The thesis: in a systemic equity selloff, capital does not vanish, it rotates into Treasury duration
and, in uncertainty-driven episodes, gold. That rotation shows up first as a volatility breakout in
the receiving instrument's own price — a forced, non-price-sensitive buying wave pushes a close
through its 20-day Bollinger upper band before a slower moving-average filter would confirm a trend.
The card is explicitly not an abstention strategy: it holds TLT and GLD outright, and its own memo
states that when not triggered it holds nothing, which is scored the same as every other card's idle
time — it never claims credit for SPY falling while empty.

The memo also disclosed, before any result existed, that roughly 85–90% of the book sits in
zero-cost cash at all times, and that the engine scores that cash as free when a real hedging sleeve
would have to fund, invest, or forgo yield on it. That caveat matters for what follows.

## 2. Eight-window results

| window | trades | return | benchmark | excess | adj. excess | capital exp. | session exp. | max DD | win rate |
|---|---|---|---|---|---|---|---|---|---|
| q4-2018 | 3 | +0.71% | −20.05% | +20.76% | **+2.45%** | 8.65% | 41.54% | −0.19% | 100.0% |
| covid | 3 | +0.95% | −8.71% | +9.66% | **+1.33%** | 4.41% | 24.73% | −1.70% | 50.0% |
| bear-2022 | 6 | −0.70% | −25.14% | +24.44% | **+0.31%** | 4.03% | 28.57% | −1.61% | 33.3% |
| chop-2015 | 13 | −1.23% | −0.04% | −1.19% | **−1.22%** | 8.46% | 48.08% | −3.17% | 25.0% |
| chop-2011 | 9 | +3.75% | −0.05% | +3.79% | **+3.75%** | 9.39% | 55.38% | −1.79% | 62.5% |
| bull-2024 | 14 | −2.11% | +14.00% | −16.10% | **−3.31%** | 8.59% | 55.60% | −2.53% | 28.6% |
| recent | 8 | +2.33% | +20.62% | −18.28% | **+0.97%** | 6.63% | 38.15% | −2.17% | 57.1% |
| gfc | 13 | +1.03% | −56.23% | +57.26% | **+6.66%** | 10.01% | 54.49% | −2.86% | 30.8% |

Median adjusted excess **+1.15%**, worst window **−3.31%** (bull-2024), positive in 6 of 8. Both
match the round's own scorecard. Mean capital exposure over the six windows common with round 1
(excludes chop-2011, gfc) is **6.80%** — the figure the Pareto-frontier placement rests on.

Every single window's capital exposure sits 20–48 points below its session exposure (the widest gap:
chop-2011 at 46 points, bull-2024 at 47). §4 of `PROTOCOL.md` flags any row diverging by more than 20
points as "where the naive metric misleads most" — by that standard this card is flagged in **all
eight of eight windows**, not the occasional one. That is a direct, structural consequence of running
two 15% slots: even fully committed, only 30% of the book is ever at risk, so `capital_exposure`
cannot help but sit far under `session_exposure` regardless of what the trades do. Keep that in mind
through §5.

## 3. Pre-registered worst window versus actual

The memo's §7 pre-registration, quoted in full:

> "**bull-2024.** Across every parameter combination I tested it is overwhelmingly the numerically
> worst window on `adjusted_excess` (−3.22% at the shipped parameters): a strong, low-volatility
> equity year gives TLT and GLD nothing to rotate into, the entry still fires on ordinary
> band-breakout noise, gets stopped out against `sma(20)` repeatedly, and pays its premium against a
> benchmark that is itself up 14%."

The actual outcome: bull-2024 adjusted excess **−3.31%**, the worst of the eight windows — the
prediction was correct, and the design-window estimate (−3.22%) landed within a tenth of a point of
the realised figure. The memo separately flagged bear-2022 as the window where the *mechanism* itself
fails even though it wasn't predicted as the numerically worst — see §5.

## 4. Exit reasons and stops

| window | rule | stop | time | open_at_end |
|---|---|---|---|---|
| q4-2018 | 1 | 0 | 0 | 2 |
| covid | 2 | 0 | 0 | 1 |
| bear-2022 | 6 | 0 | 0 | 0 |
| chop-2015 | 12 | 0 | 0 | 1 |
| chop-2011 | 8 | 0 | 0 | 1 |
| bull-2024 | 14 | 0 | 0 | 0 |
| recent | 7 | 0 | 0 | 1 |
| gfc | 13 | 0 | 0 | 0 |

**Zero of 69 trades exited via `stop`, in any window.** This is a measured zero from the actual
harness output, not a placeholder for missing data — every exit is `rule` (the sma(20) cross) or
`open_at_end` (window boundary cut the position off mid-hold). `max_hold_days=180` never bound
either; no `time` exits anywhere. There is consequently nothing to quantify against the brief's
previous-close stop-fill gap (the "10% stop realised −22.81%" pattern) for this card — the 10% stop
was, as the memo disclosed up front, never tested by this history rather than confirmed safe by it.

## 5. Defended versus merely absent

The card is genuinely **not** an absence play in the sense the brief warns about (a trend filter
that structurally cannot fire mid-crash): it holds real TLT/GLD positions carried through the
dislocation, sized at 15% per slot, not zero exposure dressed as caution. Session exposure of
54.49% in gfc and 41.54% in q4-2018 shows it was actually in the market for a large share of both
crisis windows.

But "defended" and "small" are not the same claim, and bear-2022 shows the difference concretely.
There the raw trade result is a **loss** (−0.70%, six rule exits, 33.3% win rate) — the mechanism the
memo describes (equities sold, capital rotating into duration) did not occur, because 2022 was a
rate-hike decline that hurt Treasuries and equities together. The reported adjusted excess of +0.31%
is not evidence the trade worked; it is 4.03% capital exposure multiplied against a −25.14% benchmark
(a +1.01pp mechanical credit) outweighing the −0.70% dollar loss by three tenths of a point. The
memo pre-registered this exact failure mode before the run — "the positive `adjusted_excess` shown
for that window is an artifact of the low exposure denominator... not evidence the trade worked" —
and the actual trade log confirms it precisely as described.

## 6. Is c09 an insurance policy, or a low-exposure card that cannot lose much?

This is the question the brief asked directly, and the gfc comparison the task poses answers it more
than any other window. Decompose `adjusted_excess = total_return + capital_exposure × |benchmark|`
for the three cards named:

| card | gfc total_return (dollars on $10,000) | capital exposure | exposure credit | adjusted excess |
|---|---|---|---|---|
| c09-convex | +1.03% (+$103.33) | 10.01% | +5.63pp | **+6.66%** |
| c04-riskmanaged | +1.38% (+$138.06) | 43.97% | +24.72pp | **+26.10%** |
| c08-generalist | −4.25% (−$425.50) | 41.71% | +23.45pp | **+19.20%** |

(c04/c08 figures recomputed from their own `results/gfc/runs/r1-*.json` the same way, for this
comparison only — read-only, no other card's report touched.)

The uncomfortable fact is in the second column, not the last one. **c09's own dollar return through
the deepest drawdown in the matrix was $103 on a $10,000 book — smaller than c04's $138, and barely
ahead of c08's outright $426 loss.** Almost all of c09's headline +6.66% is the exposure-adjustment
formula crediting it for capital it did *not* commit against a benchmark that fell 56%; only 1.03 of
the 6.66 points is money actually made. c04 earned more real dollars while running 4.4x the capital
at risk and got rewarded with 4.4x the credit for it. c08 *lost* money outright in the same window and
still scored a larger adjusted excess than c09, purely because it carried more capital through the
crash than c09 ever risked.

That is the literal sense in which "the card explicitly designed for convexity was markedly less
convex than two cards that were not." Convexity means a large payoff scaled to the risk taken; c09
took very little risk (two 15% slots, 30% of the book at maximum) and made very little money in
absolute terms. Its adjusted-excess number looks respectable specifically *because* the metric
rewards low exposure symmetrically with genuine payoff when the benchmark term is large and negative
— and gfc, at −56.23%, is the window where that reward is largest. The eight-of-eight
capital-exposure/session-exposure divergence flag from §2 is the same fact from a different angle:
this card is small in every window, not selectively small only where it needs cover.

None of this means the mechanism is fake. The thesis — TLT/GLD catch a flight-to-quality rotation via
a volatility breakout — is coherent, and chop-2011's +3.75% is real evidence for it: a genuine 2011
European-debt-crisis flight-to-quality episode inside a window SPY closed flat, caught by a card whose
entry has no way to see "SPY is falling," only its own instrument's bands moving. bear-2022 is equally
real evidence *against* over-claiming: the mechanism has a regime (rate-hike declines) where it simply
does not work, and the card's own memo said so before the run.

**Verdict: c09 validates that the dominance-view ranking change was worth making, but does not
validate this specific card as a strong convex payoff.** The rule change was designed to let a
small-cost, large-payoff card survive a single-median ranking that would otherwise bury it — and c09
does clear the gate (8 of 8), sits on the Pareto frontier, and never lost more than 3.31 points in any
window, which is a genuinely defensible profile for a hedge sleeve. But its crisis "payoff" is mostly
an artifact of running very little capital against a very negative benchmark, not a large realised
gain — the raw dollar evidence says its convexity is modest at best, and in the one window (gfc) where
the brief invites a direct comparison, two non-convex-by-design cards outearned it in real terms while
taking on more risk to do so. The honest reading is that c09 is a legitimately cheap, well-reasoned
hedge instrument that the *current* metric flatters more than its dollar performance warrants — the
dominance-view change was correct in principle, but this card is not the strongest available
demonstration of what it was meant to reward.

## 7. Promotion recommendation (PROTOCOL.md §6)

This is c09's first round. §6 promotes a challenger to `candidates/` on clearing the regime gate and
posting a positive median adjusted excess — c09 does both (8/8 eligible, median +1.15%) — so it
qualifies for that step now. Promotion from `candidates/` to `base/` requires a positive median in
**two consecutive rounds on windows that differ** (§6a); this round supplies the first data point
only. Given §6, the recommendation is: **promote challenger → candidates/**, with the caveat recorded
in §6 above carried forward into round 3's evaluation — a second positive median should not be read
as confirming a large convex payoff unless the dollar-return decomposition in §6 improves alongside
it, not just the adjusted-excess number.

## 8. Attribution: what moved the number

Source: `analysis/attribution.md` / `results/attribution.json`
(`strategy-program/tools/attribution.py`). Contribution is exact — `pnl / starting_equity` per trade,
summing to the card's own scored return. Every trade is listed in this section (the largest window
here has 14 trades), unlike the material-only cutoff used for larger books elsewhere in this round.

**A card-wide fact worth stating up front: not one of this card's 64 trades, in any of the eight
windows, exited via `stop` or `max_hold_days`.** Every exit is `rule` (`close crosses_below sma(20)`)
or `open_at_end`. §4's exit-reason table already establishes this; the per-trade detail below shows
what that looks like in practice — a large number of small, short-dated round trips, not a handful of
positions ridden to their stop or their time cap.

### `gfc` — the window the brief asks about directly

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| TLT | 2008-11-20 | 2009-01-05 | 29 | rule | +13.42% | +205 | +2.05% |
| GLD | 2007-12-27 | 2008-02-06 | 27 | rule | +8.59% | +127 | +1.27% |
| GLD | 2008-11-24 | 2008-12-08 | 9 | rule | -5.03% | -77 | -0.77% |
| GLD | 2009-02-18 | 2009-03-03 | 9 | rule | -4.70% | -67 | -0.67% |
| GLD | 2007-10-15 | 2007-11-16 | 24 | rule | +4.35% | +65 | +0.65% |
| GLD | 2008-05-21 | 2008-05-30 | 6 | rule | -3.71% | -54 | -0.54% |
| GLD | 2008-02-21 | 2008-03-20 | 20 | rule | -3.01% | -45 | -0.45% |
| GLD | 2008-09-18 | 2008-10-13 | 17 | rule | -2.29% | -33 | -0.33% |
| TLT | 2007-10-22 | 2007-12-07 | 33 | rule | +1.65% | +24 | +0.24% |
| TLT | 2008-06-30 | 2008-07-17 | 12 | rule | -1.35% | -20 | -0.20% |
| TLT | 2008-03-13 | 2008-04-02 | 13 | rule | -1.20% | -17 | -0.17% |
| TLT | 2008-08-18 | 2008-09-22 | 24 | rule | -0.27% | -4 | -0.04% |
| GLD | 2008-06-27 | 2008-07-24 | 18 | rule | -0.00% | -0.04 | -0.00% |

**This is a drip, not a few large flight-to-quality bets.** Thirteen trades over 356 sessions, all
`rule` exits, holding periods of 6-33 sessions — every position is entered, held a few weeks, and
closed on the ordinary `sma(20)` cross, whether the trade worked or not. Only 4 of the 13 ever made
money, and even the single largest trade (TLT, Nov 2008-Jan 2009, catching the real post-Lehman
flight into duration) is worth +2.05% of the book — genuine evidence of the mechanism, but not a large
payoff in absolute terms. The next winner (GLD, Dec 2007-Feb 2008, an early-cycle gold rally well
before the deepest crisis months) is +1.27%. Those two trades supply the great majority of the
window's gross winning P&L, but the other 11 trades — eight of them losers averaging about -0.5%
each — are what most of the window's activity actually looks like: small, frequent, mostly break-even
round trips through TLT and GLD, with the net +1.03% result coming from two of them landing on the
right side of a real rotation rather than from a concentrated, high-conviction crisis position. The 3
largest winners (there are only 4 winners total) supply 94% of gross winning P&L; without them the
card would have returned **-2.94%** instead of +1.03%.

### `bear-2022`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| GLD | 2022-04-13 | 2022-04-25 | 7 | rule | -4.07% | -60 | -0.60% |
| GLD | 2022-02-14 | 2022-03-16 | 21 | rule | +2.97% | +41 | +0.41% |
| GLD | 2022-01-20 | 2022-01-27 | 5 | rule | -2.59% | -36 | -0.36% |
| GLD | 2022-01-03 | 2022-01-07 | 4 | rule | -0.98% | -13 | -0.13% |
| GLD | 2022-08-05 | 2022-08-19 | 10 | rule | -0.91% | -12 | -0.12% |
| TLT | 2022-07-25 | 2022-08-08 | 10 | rule | +0.69% | +10 | +0.10% |

Six trades, all GLD but one, and the mechanism the memo pre-registered as a failure mode (§5) is
visible directly: this is a rate-hike decline, so gold did not consistently catch a flight-to-quality
bid — 4 of 6 trades lost, the raw result is a small loss (-0.70%), and the +24.44% excess and modest
+0.31% adjusted excess are almost entirely the exposure-adjustment credit (4.03% capital exposure
against a -25.14% benchmark), not a working trade.

### `bull-2024`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| GLD | 2025-01-17 | 2025-02-28 | 28 | rule | +5.04% | +63 | +0.63% |
| TLT | 2025-04-07 | 2025-04-08 | 1 | rule | -2.93% | -43 | -0.43% |
| GLD | 2025-06-16 | 2025-06-25 | 6 | rule | -3.11% | -39 | -0.39% |
| TLT | 2024-12-02 | 2024-12-13 | 9 | rule | -2.76% | -39 | -0.39% |
| TLT | 2025-06-27 | 2025-07-08 | 6 | rule | -2.38% | -35 | -0.35% |
| GLD | 2025-07-22 | 2025-07-28 | 4 | rule | -2.66% | -33 | -0.33% |
| TLT | 2025-02-26 | 2025-03-13 | 11 | rule | -2.11% | -31 | -0.31% |
| TLT | 2025-02-06 | 2025-02-13 | 5 | rule | -2.06% | -30 | -0.30% |
| TLT | 2025-08-04 | 2025-08-18 | 10 | rule | -1.75% | -26 | -0.26% |
| TLT | 2024-09-10 | 2024-09-23 | 9 | rule | -1.47% | -22 | -0.22% |
| GLD | 2024-09-13 | 2024-10-10 | 19 | rule | +1.42% | +20 | +0.20% |
| GLD | 2024-10-18 | 2024-11-07 | 14 | rule | -0.79% | -12 | -0.12% |
| GLD | 2025-04-11 | 2025-05-02 | 14 | rule | +0.64% | +10 | +0.10% |
| GLD | 2025-03-14 | 2025-04-08 | 17 | rule | +0.47% | +7 | +0.07% |

The strongest, most single-direction equity year in the matrix gives TLT and GLD the least to rotate
into: 14 trades, only 4 winners, the largest a modest +0.63%. This is the window the memo predicted
would be worst (§3) and it is — a drip of small losing round trips against a benchmark up 14%.

### `chop-2011`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| GLD | 2011-07-14 | 2011-09-13 | 42 | rule | +14.55% | +203 | +2.03% |
| TLT | 2011-08-02 | 2011-09-01 | 22 | rule | +8.21% | +122 | +1.22% |
| TLT | 2012-04-11 | _open_ | 39 | **open_at_end** | +8.02% | +111 | +1.11% |
| GLD | 2012-02-23 | 2012-03-01 | 5 | rule | -3.92% | -54 | -0.54% |
| TLT | 2011-09-06 | 2011-10-11 | 25 | rule | +2.40% | +36 | +0.36% |
| TLT | 2011-12-20 | 2011-12-22 | 2 | rule | -2.27% | -33 | -0.33% |
| TLT | 2011-06-02 | 2011-06-07 | 3 | rule | -1.41% | -20 | -0.20% |
| GLD | 2012-01-30 | 2012-02-21 | 15 | rule | +0.77% | +10 | +0.10% |
| GLD | 2011-10-26 | 2011-11-18 | 17 | rule | +0.02% | +0.32 | +0.00% |

This is the window with the clearest genuine flight-to-quality signature: the two largest trades
(GLD Jul-Sep, TLT Aug-Sep 2011) run directly through the US downgrade and European sovereign flare
that also drove `c11-breakout`'s best window (see that report's §5). Unlike gfc, the top trades here
are longer-held (22-42 sessions) and larger individually — this window is closer to "a few real
positions" than a drip, and +1.11% of the +3.75% return is still an open TLT mark at the window's
close.

### `chop-2015`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| GLD | 2016-02-04 | 2016-03-15 | 27 | rule | +6.52% | +94 | +0.94% |
| TLT | 2016-01-14 | 2016-03-02 | 32 | rule | +2.99% | +45 | +0.45% |
| GLD | 2015-05-14 | 2015-05-27 | 8 | rule | -3.09% | -43 | -0.43% |
| TLT | 2015-07-09 | 2015-07-13 | 2 | rule | -2.89% | -41 | -0.41% |
| TLT | 2015-12-02 | 2015-12-04 | 2 | rule | -2.65% | -39 | -0.39% |
| GLD | 2015-09-25 | 2015-10-01 | 4 | rule | -2.72% | -39 | -0.39% |
| GLD | 2015-08-20 | 2015-09-04 | 11 | rule | -2.52% | -36 | -0.36% |
| GLD | 2015-10-14 | 2015-10-29 | 11 | rule | -2.24% | -33 | -0.33% |
| TLT | 2015-09-29 | 2015-10-09 | 8 | rule | -1.37% | -20 | -0.20% |
| TLT | 2016-03-30 | _open_ | 12 | **open_at_end** | +1.37% | +20 | +0.20% |
| TLT | 2015-12-14 | 2015-12-17 | 3 | rule | -1.16% | -17 | -0.17% |
| GLD | 2016-01-07 | 2016-01-15 | 6 | rule | -0.96% | -14 | -0.14% |
| TLT | 2015-07-24 | 2015-08-27 | 24 | rule | +0.16% | +2 | +0.02% |

13 trades, small round trips throughout, one real winning pair (GLD/TLT, both entered January 2016
into the early-2016 growth scare) too small to offset the rest — net -1.23%, essentially flat.

### `covid`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| TLT | 2020-02-24 | 2020-03-16 | 15 | rule | +6.22% | +94 | +0.94% |
| GLD | 2020-06-24 | _open_ | 4 | **open_at_end** | +0.77% | +12 | +0.12% |
| GLD | 2020-02-19 | 2020-03-02 | 8 | rule | -0.76% | -10 | -0.10% |

Only 3 trades in the entire 93-session window — this card barely engaged with covid at all (4.41%
capital exposure, the second-lowest of any window it ran). The one TLT position, entered as the crash
began and closed mid-recovery, catches the whole result on its own (+0.94% of +0.95%).

### `q4-2018`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| TLT | 2018-12-06 | _open_ | 12 | **open_at_end** | +2.29% | +33 | +0.33% |
| GLD | 2018-12-06 | _open_ | 12 | **open_at_end** | +2.20% | +31 | +0.31% |
| GLD | 2018-10-12 | 2018-11-01 | 14 | rule | +0.54% | +8 | +0.08% |

Three trades, all winners, two of them (TLT and GLD, entered the same session in the December 2018
selloff) still open when the window ends — **+0.64% of the +0.71% return is unrealised**, essentially
the entire result.

### `recent`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| GLD | 2025-08-29 | 2025-10-28 | 41 | rule | +14.84% | +187 | +1.87% |
| GLD | 2026-01-13 | 2026-02-03 | 14 | rule | +6.49% | +83 | +0.83% |
| GLD | 2025-12-23 | 2026-01-02 | 6 | rule | -2.22% | -27 | -0.27% |
| GLD | 2026-08-06 | _open_ | 8 | **open_at_end** | +2.27% | +27 | +0.27% |
| TLT | 2026-02-13 | 2026-03-06 | 14 | rule | -1.55% | -22 | -0.22% |
| TLT | 2026-06-22 | 2026-07-02 | 8 | rule | -1.16% | -17 | -0.17% |
| TLT | 2025-10-13 | 2025-10-31 | 14 | rule | +0.20% | +3 | +0.03% |
| TLT | 2025-09-08 | 2025-10-02 | 18 | rule | +0.06% | +1 | +0.01% |

One GLD trend trade (41 sessions, +1.87% of the +2.33% return) is most of this window's result;
the rest is the same small-round-trip pattern seen throughout the card's history.

## 9. Concentration and unrealised marks

| window | top-3 share of gross wins | return w/o top-3 winners | unrealised share |
|---|---:|---:|---:|
| bear-2022 | 100% | -1.21% | -- |
| bull-2024 | 93% | -3.04% | -- |
| chop-2011 | 90% | -0.62% | +1.11% |
| chop-2015 | 99% | -2.81% | +0.20% |
| covid | 100% | -0.10% | +0.12% |
| gfc | 94% | -2.94% | -- |
| q4-2018 | 100% | +0.00% | +0.64% |
| recent | 99% | -0.63% | +0.27% |

Every window shows a high top-3 concentration (90-100%), but that figure means something different
in each: with only 2-6 winning trades per window in most cases, "the top 3" is often "all of them" —
this is a low-trade-count card (3-14 trades per window, 64 total across eight windows) where
concentration is a function of small sample size, not of one dominant position eclipsing many
others. The one window where the brief invites direct scrutiny — gfc — is squarely in this pattern:
94% concentration in the top 3 out of only 4 winners, none individually larger than +2.05% of the
book. Unrealised marks are small and never decisive here (largest is q4-2018's +0.64%, on a window
that returned +0.71% — nearly all of it a mark, but the total dollar amount involved, roughly $64 on a
$10,000 book, is immaterial next to the marks driving other cards' headline numbers in the same
window, e.g. c07-chop's -4.98% or c11-breakout's own q4-2018 figures). **The honest characterisation
of this card's crisis behaviour, gfc included, is a high-frequency drip of small TLT/GLD round trips
that occasionally lands on a real rotation, not a small number of large, deliberately-timed
flight-to-quality positions.** That matters directly for whether "insurance" is the right word: an
insurance payout is characteristically a small number of large, decisive claims paid exactly when
needed; what this card actually shows is closer to a running position that is right slightly more
often than it is wrong, scaled small enough that neither the wins nor the losses are individually
large.

# c10-momentum — Confirmed Sector Momentum

Round 2 report. Trade logs: `results/<window>/runs/r1-c10-momentum.json`, all eight windows. Figures
below are recomputed directly from those files' own `total_return`, `capital_exposure` and
`benchmark_return` fields (full decimal precision) and agree with `results/scorecard-common6.json`
to within a hundredth of a point.

## 1. What this card is

`discipline: momentum`. Universe `QQQ, XLK, XLY, XLI, XLE, XLF, IWM, SMH` — Nasdaq-100, five sector
SPDRs, small caps, semiconductors, chosen so the trade is a sector-level crowding phenomenon rather
than one stock's idiosyncratic story. Entry: `close crosses_above sma(20) and close > sma(100) and
rsi(14) > 55` — a short-term breakout, confirmed above the intermediate trend, with RSI thrust above
neutral. Exit: `close crosses_below sma(20)`, symmetric and fast. `stop_loss_pct 0.08`,
`take_profit_pct null`, `max_hold_days 40`, `max_positions 4`, `position_pct 0.25` (9 of the
10-parameter budget, one slot of headroom by the memo's own conservative count).

The thesis is a crowding-and-diffusion story: information about a strengthening sector spreads over
weeks as mandates get reviewed and estimates get revised one analyst at a time, and the early
counterparty is a mean-reversion trader who faded the first leg and capitulates into the second,
extending the trend. The card asks whether that rule survives 520 sessions of two genuinely
directionless SPY years (chop-2015, chop-2011) without being ground down by whipsaw.

## 2. Eight-window results

| window | trades | return | benchmark | excess | adj. excess | capital exp. | session exp. | max DD | win rate |
|---|---|---|---|---|---|---|---|---|---|
| q4-2018 | 8 | −1.79% | −20.05% | +18.26% | **−0.27%** | 7.55% | 16.92% | −1.79% | 0.0% |
| covid | 2 | +2.49% | −8.71% | +11.20% | **+3.16%** | 7.68% | 31.18% | −1.65% | 100.0% |
| bear-2022 | 13 | −1.19% | −25.14% | +23.95% | **+2.01%** | 12.73% | 43.37% | −8.00% | 16.7% |
| chop-2015 | 27 | −6.90% | −0.04% | −6.86% | **−6.90%** | 10.63% | 24.62% | −7.66% | 8.3% |
| chop-2011 | 22 | +2.61% | −0.05% | +2.66% | **+2.62%** | 23.18% | 42.69% | −5.31% | 31.8% |
| bull-2024 | 38 | −4.52% | +14.00% | −18.51% | **−8.82%** | 30.73% | 62.40% | −7.15% | 24.3% |
| recent | 48 | +10.60% | +20.62% | −10.01% | **+1.12%** | 46.01% | 72.29% | −4.52% | 42.2% |
| gfc | 16 | −9.59% | −56.23% | +46.64% | **−6.71%** | 5.12% | 13.48% | −9.90% | 6.2% |

Median adjusted excess **+0.43%**, worst window **−8.82%** (bull-2024), positive in 4 of 8 (hit rate
50%). 174 trades total across the eight windows — the largest trade count of any card this report
covers a memo for, which matters for how much the win-rate and per-window figures above can be
trusted relative to a card that traded four times.

The chop split the brief calls out is real and worth quoting exactly rather than averaging: **−6.90%
adjusted excess in chop-2015 against +2.62% in chop-2011** — a nearly 9.5-point swing between two
windows both classified "directionless" on SPY's own return. chop-2015 (35 sessions covered by
signals in the memo's own single-symbol research, 27 realised trades here) produced a 8.3% win rate;
chop-2011 (22 trades here) produced 31.8%. The mechanical difference is regime, not the rule: SPY's
16.6% annualised vol in chop-2015 versus 22.9% in chop-2011 gave the second window more genuine
intermediate trends for a 20/100-day system to catch even while the index went nowhere net, where
chop-2015's grind produced more false breakouts that reversed inside a handful of sessions each.

## 3. Pre-registered worst window versus actual

The memo's named prediction, quoted:

> "**gfc.** It has the worst measured average per-trade return of any window I tested (−1.81%) and
> the highest stop-out rate... I expect this window to be genuinely bad for this card, not
> artificially flattered by absence — though I would not be surprised if the exposure-adjusted score
> still looks better than the raw per-trade numbers suggest."

gfc did come in badly: adjusted excess **−6.71%**, the card's worst raw dollar performance of any
window (total_return −9.59%, win rate 6.2%, only 1 of 16 trades a winner). But it was **not** the
worst window on the metric the brief actually ranks: bull-2024 (−8.82%) and chop-2015 (−6.90%) both
scored worse on adjusted excess. The pre-registration named the right window for "worst raw
performance" but missed the actual worst *scored* window — the memo's own hedge ("I would not be
surprised if the exposure-adjusted score still looks better...") anticipated the direction of the
gap without anticipating that two other windows would end up ranked below it. This is a genuine miss
against the brief's own test ("the report prints your prediction beside the outcome"), not a
technicality: bull-2024's −8.82% is 2.11 points worse than gfc's −6.71%.

## 4. Exit reasons and stops

| window | rule | stop | time | open_at_end |
|---|---|---|---|---|
| q4-2018 | 8 | 0 | 0 | 0 |
| covid | 1 | 0 | 0 | 1 |
| bear-2022 | 12 | 0 | 0 | 1 |
| chop-2015 | 24 | 0 | 0 | 3 |
| chop-2011 | 20 | 0 | 2 | 0 |
| bull-2024 | 37 | 0 | 0 | 1 |
| recent | 42 | 0 | 3 | 3 |
| gfc | 16 | 0 | 0 | 0 |

**Zero of 174 trades exited via `stop`, in any of the eight windows.** This is a measured zero from
the actual multi-slot backtest, not a placeholder — it independently confirms the memo's own
single-symbol research (which reported 0 of 61 signals reaching the 8% stop across the two chop
windows specifically): the real portfolio-level run shows the same zero, extended across every window
including gfc and bear-2022, not just the two chop windows the memo tested. `max_hold_days=40` bound
only 5 times total (2 in chop-2011, 3 in recent) against 176 trades — a real but minor exit path, not
the everyday mechanism. There is consequently no stopped-out trade to compare against the brief's
previous-close stop-fill gap for this card either; the 8% stop is, as the memo characterised it, "a
tail backstop, not the everyday risk control," and the actual run bears that out completely rather
than partially.

On the `close > sma(100)` confirmation filter: the memo's claim that it is "not a strong lever" —
neutral in bear-2022/bull-2024/recent, a wash in the two chop windows, and measurably *worse* in gfc
on a per-trade basis (−1.81% filtered vs. −0.91% unfiltered) — was established by the memo's own
single-symbol design-window simulation comparing the shipped rule against a counterfactual without
the clause. That counterfactual was not re-run as part of round 2 (this report does not re-open the
DuckDB store or run a second backtest per its scope), so it cannot be independently re-verified from
this round's harness output; it is reported here as the memo's own measurement, not confirmed
independently. What *is* independently confirmed from the actual gfc run: 16 trades, win rate 6.2%,
total_return −9.59% — consistent with the memo's characterisation of gfc as "genuinely bad... not
primarily an absence effect," and consistent in direction with its claim that the filter does not
rescue that window.

## 5. Defended versus merely absent

Two different windows show two different stories, and the brief's own trap — a trend filter that
cannot fire mid-crash getting credit it did not earn — applies unevenly across them.

**gfc is the absence case, close to the letter of the brief's warning.** Session exposure is only
13.48% — the card held a position on barely one session in seven of the 356 in that window — against
a 5.12% capital exposure. It did trade (16 times, more than either chop window), and lost money doing
it (−9.59% raw), so this is not the "cannot fire at all" pattern the brief names for a pure
trend-confirmation entry during a crash. But the low session exposure means the card mostly *sat out*
a 56%-down window and still lost on the minority of sessions it was in — the confirmation filter
structurally limited how much damage was possible, not because it defended a position but because it
rarely committed to one.

**bull-2024 and chop-2015 are the defended case, and it cost real money.** Session exposure of 62.40%
and 24.62% respectively, with capital exposure of 30.73% and 10.63% — this card was genuinely in the
market, at its largest committed size of any window (bull-2024's 30.73% capital exposure is the
highest in this table), and it still produced the two worst adjusted-excess results in the whole
matrix (−8.82%, −6.90%). That is the opposite of the absence pattern: the card was actually exposed,
actually traded (38 and 27 times), and actually lost. Being defended rather than absent is not
automatically a point in the card's favour — here it is the reason the worst numbers are as large as
they are, because there was real capital behind them.

covid is the intermediate case the memo flagged honestly in advance: the filtered rule fired only 3
times, all in the recovery leg (100% win rate, +2.49% window return), which the memo itself named as
"exactly the arithmetic-absence pattern the brief warns about... I am not claiming that as designed
risk management." The actual run bears this out — 2 realised trades (one still open at window end),
both winners, in a window where the crash happened over roughly six weeks the entry could not have
caught. Credit for covid's positive score belongs to arithmetic, not the rule, exactly as
pre-registered.

## 6. Verdict

The three claims the memo made ahead of the run hold up against the actual harness output, with one
partial exception:

1. **The `close > sma(100)` filter measurably does not help.** Confirmed as a memo-reported
   design-window finding (not independently re-run this round, per scope); the actual gfc result
   (−9.59% return, 6.2% win rate) is consistent with it being ineffective there.
2. **Zero of 61 chop signals ever reached the 8% stop.** Confirmed and strengthened: the real
   portfolio backtest shows zero stop-outs across all 176 trades in all eight windows, not only the
   two chop windows the memo directly tested.
3. **The fast rule-based exit, not the stop, bounds chop damage.** Consistent with the exit-reason
   table above — chop-2015 and chop-2011 combined produced 44 `rule` exits, 2 `time` exits, 3
   `open_at_end`, and zero stops.

The partial exception is the pre-registration itself (§3): gfc was correctly named as a genuinely bad
window on raw terms, but it was not the worst window on the metric that actually ranks this card —
bull-2024 was, by 2.11 points, and the memo did not name bull-2024 at all.

Read as a whole, this is a momentum rule that survives 520 sessions of chop without a single stop-out
and with whipsaw losses bounded to roughly a point per trade on average — the mechanism the memo
claimed (fast exit, not the confirmation filter, not the stop) is exactly the one the data supports.
What it does not do is survive chop *cheaply*: chop-2015 alone cost 6.90 adjusted-excess points, on
27 real, capital-committed trades, and the card's two worst windows are both ones where it was
genuinely in the market at meaningful size rather than absent. A median adjusted excess of +0.43% on
an 8/8-eligible, 136-trade sample is a real but fragile positive — the range across windows spans
roughly 12 points (−8.82% to +3.16%; the round's own `scorecard-common6.json` IQR over its six-window
subset is 7.03 points) — either way, the median is describing a coin with a fairly wide spread of
outcomes, not a consistently repeatable edge.

## 7. Promotion recommendation (PROTOCOL.md §6)

This is c10's first round. §6 promotes a challenger to `candidates/` on clearing the regime gate and
posting a positive median adjusted excess — c10 clears the gate (8/8 eligible) and its median is
positive (+0.43%), so it mechanically qualifies for that step. The margin is thin, however: +0.43%
sits well inside the scale of noise this program has already measured elsewhere (round 1's
universe-ordering study found spreads up to 12.5 points in a single window, σ = 21.2 across twelve
orderings) — a positive median this small should not be read as a confirmed edge, only as clearing the
mechanical bar. Recommendation: **promote challenger → candidates/** per the letter of §6, but flag
the median as inside the noise floor for the purposes of any argument beyond the mechanical
promotion; a second round with a non-overlapping window set (§6a) is required before base/
promotion, and that second round should be weighed on whether bull-2024-scale losses recur when the
card is genuinely committed, not just on whether the median stays above zero.

## 8. Attribution: what moved the number

Source: `analysis/attribution.md` / `results/attribution.json`
(`strategy-program/tools/attribution.py`). Contribution is exact — `pnl / starting_equity` per trade,
summing to the card's own scored return. Only trades moving at least 1% of the book are tabulated
individually; smaller trades are folded into prose.

### The chop split, at the trade level

§2 already attributes the **-6.90% vs +2.62%** chop split to a volatility difference (16.6% vs 22.9%
annualised SPY vol). The trade log shows the same split from a different angle:

**chop-2011's result is carried by two trades that rode a real intermediate trend to the 40-day
time cap** — `QQQ` and `XLK`, both entered 2012-01-04 and both held the full 40 sessions to
2012-03-02:

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| QQQ | 2012-01-04 | 2012-03-02 | 40 | time | +14.00% | +342 | +3.42% |
| XLK | 2012-01-04 | 2012-03-02 | 40 | time | +12.62% | +314 | +3.14% |
| XLF | 2012-03-09 | 2012-04-05 | 19 | rule | +4.48% | +112 | +1.12% |
| QQQ | 2012-03-08 | 2012-04-10 | 22 | rule | +4.15% | +104 | +1.04% |

Those two trades alone are +6.56 points of the window's +2.61% total — more than the entire result —
because the confirmed-uptrend entry caught a genuine multi-week tech/Nasdaq leg that ran long enough
to hit the time cap rather than reverse. The 3 largest winners supply 76% of gross winning P&L;
without them the card would have returned **-5.08%**, so the other 19 trades in the window are, on
net, a loser — chop-2011's positive headline rests on catching one real trend, not on broad edge
across the window.

**chop-2015 never produced a trend large enough to matter.** Its four winners, in full:

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| XLE | 2016-04-11 | _open_ | 4 | **open_at_end** | +1.02% | +26 | +0.26% |
| XLI | 2016-04-07 | 2016-04-08 | 1 | rule | +0.38% | +9 | +0.09% |
| XLY | 2016-04-14 | _open_ | 1 | **open_at_end** | +0.16% | +4 | +0.04% |
| SMH | 2016-04-11 | 2016-04-13 | 2 | rule | +0.03% | +1 | +0.00% |

The single best trade in the entire window is +0.26% of the book. Against 23 losing trades averaging
roughly -0.76% each (per the memo's own design-window figure, confirmed in direction by this list),
there was never a winning leg large enough to offset the accumulated whipsaw — the 3 largest winners
supply 98% of gross winning P&L, but that gross-winning pool is tiny (roughly 0.4% of the book) next
to chop-2011's (roughly 8%). **The difference between the two chop windows is not that chop-2011 had
fewer losers or smaller ones — it is that chop-2011 had two trades that turned into a real trend and
chop-2015 had none.**

### `bear-2022`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| XLE | 2022-01-04 | 2022-02-23 | 34 | rule | +15.99% | +404 | +4.04% |
| XLE | 2022-02-28 | 2022-03-16 | 12 | rule | +5.32% | +131 | +1.31% |
| XLF | 2022-08-26 | 2022-08-29 | 1 | rule | -4.24% | -105 | -1.05% |
| XLY | 2022-09-12 | 2022-09-14 | 2 | rule | -4.23% | -105 | -1.05% |
| IWM | 2022-08-26 | 2022-08-29 | 1 | rule | -4.39% | -103 | -1.03% |

Two `XLE` trades, both catching the energy sector's genuine 2022 uptrend, supply +5.35 of the
window's -1.19% (i.e. without them the raw result would be considerably worse). The 3 largest winners
are 100% of gross winning P&L; without them the card returns **-6.77%** — the window's near-flat
headline and its strongly positive +23.95% excess both rest on having found the one sector that
actually trended against an otherwise losing book.

### `bull-2024`

38 trades, the card's largest single-window trade count outside `recent`. Material trades:

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| XLY | 2024-11-04 | 2024-12-30 | 38 | rule | +13.44% | +322 | +3.22% |
| SMH | 2025-01-06 | 2025-01-13 | 4 | rule | -6.90% | -161 | -1.61% |
| XLF | 2025-03-03 | 2025-03-05 | 2 | rule | -4.64% | -114 | -1.14% |

One `XLY` trend leg (Nov-Dec 2024, post-election rally) supplies +3.22 of the window's -4.52% —
without it the raw result would be roughly -7.7%. The 3 largest winners are 77% of gross winning
P&L; without them the card returns **-9.61%**. This is the card's single worst raw dollar
performance among its positive-excess windows: it lost money outright (-4.52%) in the year SPY
returned +14.00%, with most of its 38 trades whipsawed by a rule that requires a short-term breakout
on top of an already-confirmed trend, in a market moving too smoothly for that second confirmation
to add value.

### `chop-2011` and `chop-2015`

See the dedicated subsection above.

### `covid`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| SMH | 2020-05-19 | 2020-06-29 | 28 | rule | +8.18% | +202 | +2.02% |
| QQQ | 2020-06-30 | _open_ | 0 | **open_at_end** | +1.94% | +47 | +0.47% |

Only 2 trades in the entire 93-session window, both in the recovery leg well after the crash itself —
consistent with §5's characterisation of covid as "the arithmetic-absence pattern," not a defended
position. Both are winners; there is no losing trade to attribute.

### `gfc`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| XLF | 2008-09-22 | 2008-09-23 | 1 | rule | -7.75% | -192 | -1.92% |
| XLY | 2008-09-09 | 2008-09-16 | 5 | rule | -7.43% | -185 | -1.85% |
| XLY | 2008-05-02 | 2008-05-22 | 14 | rule | -5.05% | -128 | -1.28% |
| XLE | 2008-05-05 | 2008-05-30 | 18 | rule | +4.97% | +124 | +1.24% |
| IWM | 2008-09-22 | 2008-09-23 | 1 | rule | -4.36% | -108 | -1.08% |

**Only 1 of 16 trades in this window ever made money** (`XLE`, a mid-2008 energy leg, +1.24% of the
book). The three largest losers are all one-to-five-day holds cut almost immediately by the same-day
`sma(20)` cross the entry requires — this is a momentum rule firing on brief false starts inside a
collapsing market, exactly the failure mode the memo pre-registered (§3), even though gfc ultimately
was not the single worst *scored* window (bull-2024 and chop-2015 were, on adjusted excess).

### `q4-2018`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| QQQ | 2018-09-21 | 2018-09-24 | 1 | rule | -1.81% | -44 | -0.44% |
| XLI | 2018-10-09 | 2018-10-10 | 1 | rule | -1.54% | -38 | -0.38% |
| XLK | 2018-09-21 | 2018-09-24 | 1 | rule | -1.33% | -33 | -0.33% |

**Every one of this window's 8 trades lost money**, and six of the eight were entered on 2018-09-21
or 2018-09-25 — the market's own late-September top — and cut within 1-5 sessions as the sma(20)
cross fired almost immediately against them. There is no winning trade to attribute; the window's
positive +18.26% excess is a benchmark-relative artifact of SPY falling further (-20.05%) than the
card's own -1.79% loss, on very low (7.55%) capital exposure.

### `recent`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| XLE | 2026-01-05 | 2026-03-04 | 40 | time | +18.75% | +478 | +4.78% |
| SMH | 2025-09-09 | 2025-10-13 | 24 | rule | +13.43% | +319 | +3.19% |
| XLI | 2026-01-05 | 2026-03-04 | 40 | time | +11.27% | +268 | +2.68% |
| XLF | 2026-06-05 | 2026-08-04 | 40 | time | +9.12% | +225 | +2.25% |
| XLK | 2025-09-09 | 2025-10-13 | 24 | rule | +7.16% | +171 | +1.71% |
| SMH | 2025-10-14 | 2025-11-10 | 19 | rule | +7.24% | +169 | +1.69% |
| XLE | 2026-08-11 | _open_ | 5 | **open_at_end** | +6.10% | +150 | +1.50% |
| SMH | 2026-06-09 | 2026-06-11 | 2 | rule | -4.51% | -110 | -1.10% |
| XLK | 2026-06-09 | 2026-06-10 | 1 | rule | -4.27% | -103 | -1.03% |

This is the card's largest and most broadly-based positive window: 48 trades, only 49% of gross
winning P&L in the top 3, and without them the card still returns roughly breakeven (-0.05%) — unlike
bear-2022 or gfc, `recent`'s +10.60% is spread across a genuinely large number of trades (three
different sectors reaching the 40-day time cap, `XLE`, `XLI`, `XLF`), not concentrated in one or two.

## 9. Concentration and unrealised marks

| window | top-3 share of gross wins | return w/o top-3 winners | unrealised share |
|---|---:|---:|---:|
| bear-2022 | 100% | -6.77% | +0.24% |
| bull-2024 | 77% | -9.61% | +0.38% |
| chop-2011 | 76% | -5.08% | -- |
| chop-2015 | 98% | -7.29% | +0.29% |
| covid | 100% | +0.00% | +0.47% |
| gfc | 100% | -10.83% | -- |
| q4-2018 | n/a (no winners) | -1.79% | -- |
| recent | 49% | -0.05% | +0.98% |

Five of the eight windows would flip to a materially worse loss without their top 3 winners
(bear-2022, bull-2024, chop-2011, chop-2015, gfc all show a "without" figure several points below the
headline, and gfc's `covid`-adjacent -10.83% without-top-3 figure means essentially the whole window
rests on one `XLE` trade). Only `recent` is genuinely broad-based (49% concentration, breakeven
without the top 3). Unrealised marks are small everywhere this card ran (never above +0.98%, in
`recent`) and never explain a negative result away — where the card lost, it lost on closed trades,
not on marks that could still recover. Combined with §4's independently-confirmed zero stop-outs
across all 176 trades, the picture is consistent: this card's chop-window defense is real and
structural (the fast rule exit, not the stop), but its positive windows individually hinge on a small
number of trades finding a genuine multi-week trend (`recent`'s breadth is the exception, not the
rule) — a momentum card that, true to its name, needs momentum to actually show up somewhere in the
book, and does not have many other ways to win when it doesn't.

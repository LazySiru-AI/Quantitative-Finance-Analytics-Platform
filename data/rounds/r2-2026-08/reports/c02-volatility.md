# c02-volatility — round 2 report: benchmark comparison and trade attribution

## 1. What the card is

`c02-volatility` is a volatility-squeeze breakout: buy the session after a close above the 20-day,
2-stdev Bollinger upper band, but only when 14-day ATR is still below 50-day ATR — realised
volatility has not yet caught up with the price move. The thesis is dealer/option-writer gamma
hedging: a compressed range accumulates short-gamma positioning on the other side, and a breakout
while that positioning is still in place forces hedging that extends the move. Exit is an 8% stop,
20% target, or 60-day cap (no discretionary exit signal). Universe `SPY QQQ DIA IWM XLF XLE`, 4
slots at 25% each — 9 of 10 parameters spent. Pre-registered failure regime: *`bear-2022`* — "a
grinding, low-realized-vol bear market" where the compression/release setup rarely fires at all — and
a secondary expectation that a fast crash (COVID's opening days) would be missed by construction,
since a gap-through arrives with ATR already elevated, not compressed.

## 2. Versus SPY, all eight windows

| window | sessions | card | SPY | excess | adj. excess | capital exposure | max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `q4-2018` | 65 | −4.53% | −20.05% | **+15.51%** | −1.18% | 16.7% | −4.81% |
| `covid` | 93 | +2.05% | −8.71% | **+10.76%** | +4.53% | 28.4% | −7.98% |
| `bear-2022` | 196 | −6.71% | −25.14% | **+18.43%** | −0.53% | 24.6% | −15.36% |
| `chop-2015` | 260 | −3.77% | −0.04% | **−3.73%** | −3.76% | 36.9% | −6.71% |
| `chop-2011` | 260 | −0.36% | −0.05% | **−0.31%** | −0.35% | 25.1% | −4.65% |
| `bull-2024` | 250 | +1.13% | +14.00% | **−12.87%** | −4.46% | 40.0% | −6.39% |
| `recent` | 249 | +10.47% | +20.62% | **−10.15%** | −1.33% | 57.2% | −4.66% |
| `gfc` | 356 | **−20.78%** | −56.23% | **+35.44%** | **−11.89%** | 15.8% | −21.18% |

`gfc` posted the field's worst adjusted excess of any card this round (§4 of the round report): a
−20.78% raw return, credited only +8.89 points for its 15.8% exposure, nets to −11.89%. It is also the
only window where the card's own worst drawdown (−21.18%) approaches the scale of the benchmark's
(−56.23%) rather than sitting an order of magnitude below it, as it does everywhere else.

## 3. What moved the number — the GFC damage, quantified

10 trades in `gfc`; every material line is a stop-loss.

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |
|---|---|---|---|---|---|---|---|
| XLF | 2008-09-09 | 2008-09-16 | 5 | stop | **−18.22%** | −444 | **−4.44%** |
| QQQ | 2009-02-09 | 2009-02-20 | 8 | stop | −9.40% | −233 | −2.33% |
| IWM | 2008-05-14 | 2008-07-03 | 35 | stop | −9.26% | −232 | −2.32% |
| SPY | 2009-01-05 | 2009-01-15 | 8 | stop | −9.28% | −224 | −2.24% |
| XLE | 2007-12-27 | 2008-01-16 | 13 | stop | −8.91% | −223 | −2.23% |
| DIA | 2009-01-05 | 2009-01-15 | 8 | stop | −8.77% | −213 | −2.13% |
| XLE | 2007-10-16 | 2007-11-13 | 20 | stop | −8.13% | −202 | −2.02% |
| QQQ | 2009-01-05 | 2009-01-21 | 11 | stop | −7.88% | −194 | −1.94% |
| QQQ | 2008-04-21 | 2008-07-16 | 60 | time | −4.93% | −122 | −1.22% |

**The stop nominal is 8%. Verified against all eight stop exits in this window, seven landed within
1.4 points of nominal — a gap of −0.13pp to −1.40pp, consistent with the previous-close-only stop
mechanics the brief documents. One did not: XLF, entered 2008-09-09 and stopped 2008-09-16 — Lehman
week — realised −18.22%, a gap of −10.22 points against the 8% stop, seven to seventy times the size
of every other stop's slippage in the same window.** That single trade is −4.44% of the card's return,
almost exactly a fifth of the entire −20.78% window loss, and by itself turns what would otherwise be
a roughly −16 to −17% window into a −20.78% one. It is also the single largest material loss anywhere
in this card's eight-window record.

The remaining damage is broad rather than concentrated: no other single trade exceeds −2.33% of the
book, and the −7.88% to −9.40% cluster of five further stops (QQQ ×3, SPY, XLE, DIA) shows the squeeze
filter kept firing new entries through the entire Sep 2008–Feb 2009 stretch, each one arriving into a
market whose realised volatility had not yet caught up — precisely the entry condition the memo
describes — and each one getting run over by a market that kept moving anyway. The memo's pre-registered
concern was that `gfc` sits outside this rule's contemplated failure mode (a grinding bear, not a
compression/release regime); the trade log shows a different problem: the rule *did* find compressed-
range setups inside the crash, correctly by its own logic, and they failed anyway because 2008's
volatility regime broke faster and further than an 8% stop was sized for.

**Other windows, briefly:** `q4-2018` (2 trades) is entirely two stops, XLE −9.83% (−2.45%) and
SPY −8.87% (−2.08%), both within 2 points of nominal. `chop-2015` (9 trades) is dominated by two
stops — QQQ −9.32% (−2.31%), XLF −8.06% (−2.01%) — offset by one open GLD-adjacent... no, an open XLE
mark (+7.22%, +1.80%). `bull-2024`'s single material loss is a QQQ stop at −8.16% (−1.76%), essentially
nominal.

## 4. Concentration

| window | top-3 share of gross winning P&L | return without top 3 |
|---|---:|---:|
| `q4-2018` | — (no winners survive to rank) | −4.53% |
| `covid` | 100% | −1.24% |
| `bear-2022` | — | −6.71% |
| `chop-2015` | 98% | −6.54% |
| `chop-2011` | 85% | −3.93% |
| `bull-2024` | 80% | −2.00% |
| `recent` | 80% | −0.45% |
| `gfc` | 100% | −20.87% |

`gfc`'s winners contribute essentially nothing net — removing the top three winners *deepens* the
loss only marginally (−20.78% to −20.87%), confirming the window's story is almost entirely the stop
cluster in §3, not a mix of winners and losers.

## 5. Realised versus marked

Several windows lean on open positions: `bull-2024` +2.40% of return, `chop-2015` +1.80%, `covid`
+2.05% (100% of `covid`'s return — the two trades open at the window's close, QQQ +10.73% and XLF
−4.93%, are the entire book), `recent` +5.25%, `bear-2022` −1.73%. `gfc`'s +35.44% raw excess and
−11.89% adjusted excess are, by contrast, fully realised — no mark props up or depresses that number.

## 6. The new evidence, and what it changes

`gfc` is not new sampled data for this card: the trade log here is byte-identical, trade for trade, to
`r1-2026-08/results/gfc/runs/r1-c02-volatility.json`, including the XLF Lehman-week trade. `covid`,
`bear-2022`, `bull-2024` and `recent` are unchanged recomputations of round 1's own runs. **The only
windows genuinely new to this card are `q4-2018`, `chop-2015` and `chop-2011`** — adjusted excess
−1.18%, −3.76% and −0.35%, median **−1.18%, negative**. The memo's pre-registered worst case
(`bear-2022`, a grinding low-vol bear) was in fact mild (−0.53% adjusted excess) — its named failure
regime did not bite hard; the card's actual worst result, `gfc`, was never in its own risk list at all.

## 7. Verdict

`c02-volatility` posted a negative median adjusted excess in round 1 and, on the three windows that
are genuinely new evidence this round, posts another negative median (−1.18%). It is not in the
library under either `candidates/` or `base/`. The GFC result is its sharpest data point and the most
informative for future design: a squeeze-breakout entry with a static percentage stop found real
setups inside a systemic crisis and was run over regardless, with one trade — entered the week
Lehman failed — gapping ten points past its nominal stop while every other stop that window landed
within a point and a half of nominal. That is evidence about stop mechanics under acute stress, not
evidence the entry logic itself is unsound; the memo's own mechanism (dealer gamma hedging around a
compressed range) is not falsified by a single week's slippage.

**Recommendation: no promotion.** Two consecutive negative medians, and per `PROTOCOL.md` §6 as
amended the second must rest on windows the first round did not use to count as independent
confirmation — it does here (the three new windows are genuinely new draws), so this is real,
non-duplicated evidence against promotion, not one measurement counted twice. Retain as a challenger;
do not retire — 94 total trades across eight windows and a real, mechanism-grounded thesis is not the
zero-trade condition `PROTOCOL.md` §6 retires on. If a variant is tested next round, the GFC evidence
argues for widening the stop or adding a volatility-regime brake (e.g. suspending new entries when
ATR(14) is already elevated in absolute terms, not just relative to ATR(50)) rather than changing the
squeeze-entry logic itself.

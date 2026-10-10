# c03-breakout — round 2 report: benchmark comparison and trade attribution

## 1. What the card is

`c03-breakout` buys a confirmed swing-high break (`close crosses_above swing_high(20)`, a pivot
confirmed only 20 bars after it forms — not a naive rolling high) while `close > sma(200)`, and exits
on a swing-low break (`swing_low(10)`) or a 10% stop. Universe: the nine SPDR US sector ETFs
(`XLK XLF XLE XLI XLY XLP XLV XLU XLB`), 4 slots at 20% each. The memo measured full-history mean
pairwise correlation across the set at roughly 0.58 before submitting — the same caution `c05-trend`'s
and `c11-breakout`'s memos independently raise about sector baskets being one trade in several
costumes. Pre-registered failure regime: **`bear-2022`, and secondarily `gfc`** — both grinding,
broad declines where the memo expected sector-level relief rallies to fire the entry and then get
overrun once the broader decline caught up.

## 2. Versus SPY, all eight windows

| window | sessions | card | SPY | excess | adj. excess | capital exposure | max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `q4-2018` | 65 | −2.60% | −20.05% | **+17.45%** | +4.00% | 32.9% | −3.70% |
| `covid` | 93 | −5.76% | −8.71% | **+2.96%** | −4.55% | 13.9% | −8.17% |
| `bear-2022` | 196 | −8.35% | −25.14% | **+16.79%** | +0.07% | 33.5% | −10.94% |
| `chop-2015` | 260 | −6.04% | −0.04% | **−6.01%** | −6.03% | 37.2% | −9.49% |
| `chop-2011` | 260 | −1.37% | −0.05% | **−1.33%** | −1.35% | 45.7% | −6.52% |
| `bull-2024` | 250 | +1.82% | +14.00% | **−12.18%** | −6.25% | 57.7% | −10.04% |
| `recent` | 249 | +3.43% | +20.62% | **−17.18%** | −8.32% | 57.0% | −4.35% |
| `gfc` | 356 | −13.90% | −56.23% | **+42.33%** | −1.71% | 21.7% | −14.29% |

This card ranked last of the round's five new challengers on median adjusted excess. Every bull
window (`bull-2024`, `recent`) is a clear loss on both raw and adjusted terms; every crisis window
shows large positive raw excess that mostly evaporates once adjusted for the card's own exposure
(`bear-2022` +16.79% raw collapses to +0.07% adjusted).

## 3. What moved the number

**`bear-2022`** — 9 trades. One large winner, XLE (2022-01-07→2022-06-24, 115 bars, rule exit,
+18.19%, +3.65%), against six sector stops clustered in the same six-week span: XLV −10.40% (−2.07%),
XLF −9.80% (−1.95%), XLP −9.83% (−1.93%), XLB −9.47% (−1.90%), XLV (again) −7.14% (−1.34%), XLU
−6.56% (−1.29%), XLU (again) −5.94% (−1.17%). Six sectors stopped out inside overlapping windows —
exactly the memo's pre-registered mechanism (sector relief rallies overrun by the broader decline).

**`gfc`** — 11 trades, all losses bar one relief-rally-style rule exit; the largest is XLP
(2008-08-13→2008-10-08, 39 bars, stop, −15.45%, −3.06%), followed by XLP again (2007-10-23→2008-01-22,
rule, −10.11%, −2.01%), XLE (stop, −9.45%, −1.88%), XLU (rule, −7.79%, −1.57%), XLI (rule, −7.81%,
−1.54%), XLV (rule, −6.41%, −1.26%), XLB (rule, −5.97%, −1.17%). Note most of these close on `rule`
(the structural swing-low exit), not the 10% stop — the sector rallies the memo predicted did fire,
and mostly failed on their own structural exit before reaching the stop.

**`chop-2015`** (worst adjusted-excess window) — 12 trades: XLF −10.84% (rule, −2.15%), XLY −10.07%
(rule, −2.00%), XLY again −5.11% (rule, −1.01%), partly offset by an open XLU mark +6.98% (+1.39%).

**`recent`** (worst raw excess) — 13 trades, a genuinely mixed book: XLK +13.21% (rule, +2.59%) and
XLV +8.90% (rule, +1.74%) as winners against XLF −8.65% (rule, −1.72%) and XLY −6.25% (rule, −1.22%)
as losers, plus two open marks (XLF +7.53%/+1.50%, XLV +5.57%/+1.07%) — the closest this card comes to
broad-based, two-sided trading rather than one dominant leg.

## 4. Concentration

| window | top-3 share of gross winning P&L | return without top 3 |
|---|---:|---:|
| `q4-2018` | 100% | −2.72% |
| `covid` | 100% | −6.16% |
| `bear-2022` | 100% | −12.00% |
| `chop-2015` | 100% | −8.28% |
| `chop-2011` | 88% | −4.77% |
| `bull-2024` | 58% | −1.92% |
| `recent` | 65% | −2.39% |
| `gfc` | 100% | −14.42% |

Four of eight windows show the top three winners producing *all* of the gross winning P&L — the book
is close to a single winning leg propped up against a wall of sector stops in exactly those windows.

## 5. Realised versus marked

`bull-2024` +3.51%, `chop-2015` +2.09%, `q4-2018` −0.36%, `covid` −0.97%, `chop-2011` +0.37%, `recent`
+2.83% of return sit in positions open at the window's close — none large enough to flip a window's
sign on its own, but `bull-2024`'s +1.82% return would be roughly −1.7% without its open marks, worth
flagging given the card's overall weak record in bull windows.

## 6. Correlation verdict, from trade timing rather than the pairwise-return number

The memo's own ~0.58 mean pairwise correlation figure describes co-movement of returns, not whether
individual trades actually behave independently within a window. Checking win rate two ways across
all 84 trades in the eight windows:

**By symbol** (pooled across all windows):

| symbol | wins / trades | win rate |
|---|---|---|
| XLI | 6/8 | 75.0% |
| XLE | 2/5 | 40.0% |
| XLV | 3/7 | 42.9% |
| XLU | 5/13 | 38.5% |
| XLK | 3/8 | 37.5% |
| XLY | 3/10 | 30.0% |
| XLF | 2/7 | 28.6% |
| XLB | 1/4 | 25.0% |
| XLP | 2/14 | 14.3% |

**By window** (pooled across all nine symbols):

| window | wins / trades | win rate |
|---|---|---|
| `bull-2024` | 8/11 | 72.7% |
| `recent` | 7/13 | 53.8% |
| `chop-2011` | 5/9 | 55.6% |
| `chop-2015` | 3/12 | 25.0% |
| `q4-2018` | 1/4 | 25.0% |
| `covid` | 1/7 | 14.3% |
| `bear-2022` | 1/9 | 11.1% |
| `gfc` | 1/11 | 9.1% |

Spread across windows (9.1% to 72.7%, a 63.6-point range, population stdev 22.5 points) is wider than
the spread across symbols (14.3% to 75.0%, a 60.7-point range, population stdev 15.9 points) — and the
symbol range is anchored by XLP's poor 14.3% at one end against a small four-trade XLI sample at the
other, not by a broad symbol-level divide. **The stronger signal is which window it is, not which
symbol is traded**: every symbol did badly together in `gfc`, `bear-2022` and `covid`, and every
symbol did comparatively well together in `bull-2024`. That is the signature the round report names
for `A-rotation`-style baskets — nine tickers expressing one regime bet — and the trade-timing data
here supports the same read for `c03-breakout`'s sector book: the nine SPDRs are not nine independent
opportunities so much as one broad-equity-cycle bet, taken up to four times over.

## 7. The new evidence, and what it changes

`gfc`'s trade log here is byte-identical to `r1-2026-08/results/gfc/runs/r1-c03-breakout.json`, and
`bear-2022`, `bull-2024`, `covid` are unchanged recomputations of round 1's runs; `recent`'s
`total_return` differs from round 1's by about 0.05 percentage points (0.034890 vs 0.034347), a
rounding-scale difference rather than a new draw. **The only windows genuinely new to this card are
`q4-2018`, `chop-2015` and `chop-2011`** — adjusted excess +4.00%, −6.03% and −1.35%, median **−1.35%,
negative**. `q4-2018`'s positive result is notable as the one new window where the card actually beat
its own passive size, but it is one window against two negative ones, and the pre-registered failure
regime (`bear-2022`, secondarily `gfc`) was correctly named — `bear-2022`'s adjusted excess of +0.07%
is close to flat, and `gfc`'s −1.71% is a genuine loss, exactly the shape the memo predicted before
either window ran.

## 8. Verdict

`c03-breakout` ranked last of the round's five challengers on median adjusted excess, and the reason
is visible directly in the trade log rather than only in the summary statistics: the nine-symbol
sector book behaves like one basket-level bet on the broad equity cycle, winning broadly together in
`bull-2024`/`recent` and losing broadly together in every crisis and chop window measured. That is the
same failure mode `c11-breakout` was explicitly commissioned to fix by choosing a genuinely
cross-asset universe (`SPY TLT GLD LQD`, measured at 0.13 mean off-diagonal correlation) instead of a
same-asset-class one — and the round report's clean head-to-head (`REPORT.md` §4) between the two
cards is the controlled version of the same point this report reaches independently from timing data.

**Recommendation: no promotion, and no basis for retirement.** Median adjusted excess is negative in
round 1 and, on the three genuinely new windows this round, negative again (−1.35%) — a real,
non-duplicated second negative result under `PROTOCOL.md` §6 as amended. The card is not in
`library/candidates/` or `base/`; nothing here changes that. It took trades in every window of both
rounds, so it does not meet the zero-trade retirement bar either. If a variant is commissioned, the
evidence here argues for diversifying the universe across asset classes rather than sectors — the
comparison with `c11-breakout` already exists to test exactly that.

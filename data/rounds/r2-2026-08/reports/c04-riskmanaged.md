# c04-riskmanaged — round 2 report: benchmark comparison and trade attribution

## 1. What the card is

`c04-riskmanaged` ("All-Weather Trend Sleeve") holds four independent legs — `SPY`, `EFA`, `TLT`,
`GLD` — each while `close > sma(200)` and exits each when `close < sma(200)`, plus a 12% stop as a
shock backstop. No cross-asset logic, no rebalancing rule; five parameters against the round's budget
of ten. The design thesis is that the four legs' crisis behaviour differs (measured pairwise
correlation `SPY`/`EFA` 0.86, `SPY`/`TLT` −0.31, `GLD`/`SPY` 0.05, full history), so that one leg's
trend break rotates the book toward another still-trending leg rather than collapsing it to cash.
Pre-registered failure regime: a sideways, low-trend market (repeated whipsaw stop-outs against a
benchmark that isn't moving), and secondarily a simultaneous multi-asset bear where equities and bonds
fall together — the memo's own pre-trade estimate for `bear-2022` was "~17%" blended exposure.

## 2. Versus SPY, all eight windows

| window | sessions | card | SPY | excess | adj. excess | capital exposure | max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `q4-2018` | 65 | −2.74% | −20.05% | **+17.30%** | −0.55% | 10.9% | −3.36% |
| `covid` | 93 | −1.32% | −8.71% | **+7.39%** | +3.78% | 58.6% | −8.01% |
| `bear-2022` | 196 | −6.58% | −25.14% | **+18.56%** | −2.44% | 16.5% | −6.58% |
| `chop-2015` | 260 | −3.98% | −0.04% | **−3.94%** | −3.96% | 35.7% | −8.67% |
| `chop-2011` | 260 | −0.22% | −0.05% | **−0.18%** | −0.20% | 60.2% | −6.25% |
| `bull-2024` | 250 | +6.49% | +14.00% | **−7.50%** | −2.63% | 65.2% | −5.58% |
| `recent` | 249 | +12.05% | +20.62% | **−8.57%** | −2.67% | 71.4% | −9.51% |
| `gfc` | 356 | **+1.38%** | −56.23% | **+57.61%** | **+26.10%** | 44.0% | −8.81% |

`gfc`'s +26.10% adjusted excess is the round's best crisis result of any card in the field (§2 of the
round report), on a +1.38% raw return — **+$138 on a $10,000 book** — at 44.0% capital exposure across
28 trades. `bear-2022`'s 16.5% exposure lands almost exactly on the memo's own pre-trade estimate of
"~17%," the one window the memo explicitly flagged as the honest low-exposure case.

## 3. What moved the number — the GFC result, by leg

28 trades. Summing every trade's `pnl / starting_equity` exactly reproduces the +1.38% total return
(`tools/attribution.py`'s guarantee); broken out by leg:

| leg | trades | net contribution |
|---|---:|---:|
| GLD | 8 | **+3.15%** |
| TLT | 9 | **+1.93%** |
| SPY | 5 | −1.54% |
| EFA | 6 | −2.16% |
| **total** | **28** | **+1.38%** |

**The memo's own rotation story is confirmed directly from the trade log, not assumed: gold and
Treasuries earned, equities lost, in a book that stayed 44% deployed rather than idle.** The material
trades show why:

| symbol | entry | exit | bars | exit reason | trade return | P&L | share |
|---|---|---|---|---|---|---|---|
| GLD | 2007-10-09 | 2008-08-06 | 208 | rule | **+19.95%** | +491 | +4.91% |
| TLT | 2008-11-05 | _open_ | 83 | open_at_end | +9.17% | +226 | +2.26% |
| GLD | 2009-01-21 | _open_ | 32 | open_at_end | +7.71% | +188 | +1.88% |
| SPY | 2007-10-09 | 2007-11-08 | 22 | rule | −4.99% | −124 | −1.24% |
| GLD | 2008-10-09 | 2008-10-13 | 2 | rule | −4.31% | −102 | −1.02% |

GLD's 208-bar hold from October 2007 to August 2008 (+19.95%, the single largest trade in the card's
eight-window record) captured most of the gold leg's gain before the position rolled over on the
`sma(200)` exit rule in August 2008 — before Lehman, not through it. TLT's 83-bar open position
(entered 2008-11-05, still open at the window's close) captured the flight-to-duration bid that
followed the crisis, contributing +2.26% on its own. SPY and EFA both lost, consistent with equities
being correctly, if only partially, excluded — the two legs were not fully absent (5 and 6 trades
respectively; equity exposure re-entered on rule-based rallies and got stopped or exited again), which
is why they detract rather than sitting neutrally at zero.

## 4. Zero stops, verified and extended

Round 1 reported zero stop-outs across all 83 trades in five windows for this card. Checked directly
against every trade in all eight round-2 windows:

| window | rule | stop | open_at_end |
|---|---:|---:|---:|
| `q4-2018` | 6 | 0 | 1 |
| `covid` | 7 | 0 | 3 |
| `bear-2022` | 18 | 0 | 0 |
| `chop-2015` | 18 | 0 | 3 |
| `chop-2011` | 23 | 0 | 2 |
| `bull-2024` | 14 | 0 | 3 |
| `recent` | 8 | 0 | 2 |
| `gfc` | 26 | 0 | 2 |
| **total** | **120** | **0** | **16** |

**136 trades across all eight windows, zero stop-outs.** The finding holds and extends: the 53 trades
in the three genuinely new windows (`q4-2018`, `chop-2015`, `chop-2011`) add no stops either. The
12% shock backstop the memo sized "as a shock backstop, not a volatility filter" has still never fired
in this card's history; every close is either the `sma(200)` exit rule or a position open at the
window boundary. The trend rule itself has done all of the risk control observed to date.

## 5. Concentration

| window | top-3 share of gross winning P&L | return without top 3 |
|---|---:|---:|
| `q4-2018` | 100% | −3.35% |
| `covid` | 92% | −7.19% |
| `bear-2022` | 100% | −7.03% |
| `chop-2015` | 100% | −7.93% |
| `chop-2011` | 82% | −7.12% |
| `bull-2024` | 100% | −7.01% |
| `recent` | 89% | −0.04% |
| `gfc` | 87% | −7.67% |

Every window shows the top three winners producing the great majority of gross winning P&L — this is
a small-slot-count (4 positions), low-frequency book, so concentration in the largest few trades is
structural to the design, not a sign of fragility distinct from what the memo already discloses
(five parameters, four always-on legs).

## 6. Realised versus marked

Several windows lean materially on positions still open at the close: `bull-2024` **+13.50%** of its
+6.49% return, `gfc` +4.14% of +1.38%, `recent` +4.94% of +12.05%, `covid` +5.87% of −1.32%,
`chop-2015` +3.95% of −3.98%, `chop-2011` +2.45% of −0.22%. `bull-2024` is the sharpest case: without
its open marks (chiefly the GLD position entered 2024-08-21, +33.02%/+7.66%, still open at the
window's close) the window's realised result would be closer to breakeven than the reported +6.49%
gain. None of these flip a window's sign, but `bull-2024` and, to a lesser extent, `gfc` and `recent`
are leaning on unrealised gains rather than money already taken.

## 7. The new evidence, and what it changes

`covid`, `bear-2022`, `bull-2024` and `recent` are unchanged trade logs from round 1 — same trades,
same dates. `gfc` is the one exception worth flagging precisely: **the 28 trades and their individual
P&L are byte-identical to round 1's run, but the reported `total_return` differs — 0.802998...% in
round 1 versus 1.3806% here.** That is not new sampled evidence; it is `PROTOCOL.md` §9's D1/D2 engine
fix (fixed between rounds, never during one) correcting how `total_return` is computed from the same
trade log, and the same recomputation shifts every one of this card's round-1 windows by a smaller
margin (bear-2022 −6.23% → −6.58%, bull-2024 +6.37% → +6.49%, recent +12.18% → +12.05%, covid −1.50%
→ −1.32%). None of these are draws from new data. **The only windows genuinely new to this card are
`q4-2018`, `chop-2015` and `chop-2011`** — adjusted excess −0.55%, −3.96% and −0.20%, median **−0.55%,
negative**. The card's spectacular `gfc` number is not part of that new-evidence set at all; it is a
recomputation of a window this card already ran.

## 8. Verdict

`c04-riskmanaged`'s round's-best crisis result is real, verified leg by leg, and not an artefact of
inactivity: 44% capital exposure, 28 trades, zero stops, and a trade log that shows Treasuries and
gold earning while equities lost, exactly the rotation story its memo described before any of this
ran. It is also, on `PROTOCOL.md` §6's amended terms, not new evidence — `gfc` is a recomputation, and
the three windows that *are* new (`q4-2018`, `chop-2015`, `chop-2011`) post a negative median. The
card is not currently in `library/candidates/` or `base/`, and posted negative medians in both rounds
— but per `REPORT.md` §1, two negative medians that share windows are one measurement, not two; here,
the new-window median is independently negative, which is a genuine (if modest) second data point
against promotion rather than a restatement of the first.

**Recommendation: no promotion.** The crisis result is worth preserving as the field's clearest
demonstration that `adjusted_excess` rewards exposure in a falling market (Pearson r = +0.797 across
the ten GFC-eligible cards, per `REPORT.md` §2) — a real, mechanism-grounded outcome, not a metric
artefact — but a single already-measured window cannot carry a promotion under the amended rule, and
the genuinely new evidence this round is negative. Retain as a challenger. The most informative next
test, unchanged from round 1's recommendation, remains swapping the 0.86-correlated `EFA` for a
genuinely independent fifth leg to see whether the crisis payoff scales with the number of truly
uncorrelated trending exposures.

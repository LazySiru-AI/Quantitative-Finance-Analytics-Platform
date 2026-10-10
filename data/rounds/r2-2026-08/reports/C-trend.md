# C-trend -- Institutional Flow Trend (r1 promotion) -- round 2 report

Agent: `C-trend` | Discipline: `trend` | Eligible: 6/8 main windows (clears the round-2 five-of-eight
gate; see `results/eligibility.json`)

## 1. What the card is, its claim, and where it can't run

Entry `close > sma(200) and ema(20) crosses_above ema(50)`, exit on the reverse cross, `stop_loss_pct
= 0.12`, `max_hold_days = 120`, five slots at 18% each. Universe: `NVDA AVGO TSM ORCL SOXX NFLX MU
META QCOM`. The thesis is multi-quarter earnings-revision cycles in AI-capex names, priced in by
slower, rule-following capital after early sellers and panic-sellers hand off the rest of the move.

The claim under test, carried from the prior tournament and restated verbatim by round 1: `C-trend`
won in-sample (+90.10%) and over three years (+91.66%) but **lost its blind window (+1.87%)** --
"was the blind loss the outlier, or the truth?"

**Not eligible for `chop-2011` or `gfc`**: `eligibility.json` gives `META first bar 2012-05-18, needs
<= 2010-06-13` for `chop-2011` and `needs <= 2006-10-27` for `gfc`. META's 2012 listing blocks both;
the card clears the gate at 6 of 8 regardless.

## 2. Versus SPY, every eligible window

| window | sessions | card | SPY | excess | adj. excess | cap. exp | max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| q4-2018 | 65 | **-1.84%** | -20.05% | +18.20% | -0.97% | 4.4% | -2.11% |
| covid | 93 | **+15.83%** | -8.71% | +24.55% | +19.72% | 44.6% | -4.88% |
| bear-2022 | 196 | **-6.97%** | -25.14% | +18.17% | -5.82% | 4.6% | -7.60% |
| chop-2015 | 260 | **+11.00%** | -0.04% | +11.04% | +11.02% | 40.2% | -13.29% |
| bull-2024 | 250 | **+22.75%** | +14.00% | +8.76% | +15.75% | 50.1% | -13.33% |
| recent | 249 | **-2.24%** | +20.62% | -22.85% | -7.26% | 24.4% | -17.99% |

Sorted by adjusted excess: recent -7.26%, bear-2022 -5.82%, q4-2018 -0.97%, chop-2015 +11.02%,
bull-2024 +15.75%, covid +19.72%. **Median adjusted excess = average of the two middle values,
q4-2018 and chop-2015: (-0.97 + 11.02)/2 = +5.03%**, matching `scorecard-common6.json` exactly.
**Worst window recent, -7.26%. Hit rate 3 of 6 (50%). IQR 19.17 points.** 60 trades total, 28.0% mean
capital exposure. Ranked **10th of 22** on median adjusted excess (Borda 9.83).

## 3. What moved the number

### bear-2022 (5 trades; only 2 clear the reporting threshold)

| symbol | entry | exit | bars | exit reason | trade return | P&L | share |
|---|---|---|---:|---|---:|---:|---:|
| MU | 2022-02-11 | 2022-03-08 | 16 | stop | -16.56% | -287 | -2.87% |
| NVDA | 2022-03-29 | 2022-04-07 | 7 | stop | -14.91% | -270 | -2.70% |

A five-trade window with no winner large enough to register -- both stops shown lost more than the
card's -6.97% total, meaning the unshown trades were modest net winners. Every realised trade this
round in `bear-2022` is a loss or a wash; the card's positive excess here is a benchmark artifact (SPY
fell further, -25.14%) rather than the strategy doing anything right.

### bull-2024 (15 trades)

| symbol | entry | exit | bars | exit reason | trade return | P&L | share |
|---|---|---|---:|---|---:|---:|---:|
| ORCL | 2025-05-15 | _open_ | 66 | open_at_end | +45.60% | +810 | +8.10% |
| AVGO | 2025-05-08 | _open_ | 71 | open_at_end | +39.92% | +665 | +6.65% |
| NVDA | 2025-05-15 | _open_ | 66 | open_at_end | +30.54% | +534 | +5.34% |
| TSM | 2025-05-15 | _open_ | 66 | open_at_end | +18.32% | +319 | +3.19% |
| NFLX | 2025-04-22 | 2025-08-06 | 73 | rule | +14.62% | +265 | +2.65% |
| MU | 2024-10-17 | 2024-11-18 | 22 | stop | -13.38% | -238 | -2.38% |
| TSM | 2024-09-13 | 2025-02-26 | 112 | rule | +10.83% | +187 | +1.87% |

The three largest winners are **68% of gross winning P&L**; without them the card returns **+2.67%**
instead of +22.75%. All three are `open_at_end` -- entered mid-May 2025 and still running when the
window closes. **+22.97% of the +22.75% total return is unrealised mark**, i.e. the entire headline
result is a paper gain on positions the window happened to catch mid-run.

### chop-2015 (17 trades)

| symbol | entry | exit | bars | exit reason | trade return | P&L | share |
|---|---|---|---:|---|---:|---:|---:|
| NFLX | 2015-04-09 | 2015-09-14 | 109 | rule | +53.64% | +963 | +9.63% |
| META | 2015-06-04 | 2015-11-23 | 120 | time | +30.37% | +524 | +5.24% |
| NVDA | 2016-02-29 | _open_ | 33 | open_at_end | +17.51% | +314 | +3.14% |
| META | 2016-02-02 | 2016-02-09 | 5 | stop | -15.47% | -267 | -2.67% |
| NFLX | 2015-10-09 | 2015-10-19 | 6 | stop | -14.19% | -253 | -2.53% |

Top-3 share **77%**, without them the card returns **-7.01%**. NFLX's 109-bar hold is the single
largest realised trade in this report for the card; the window's other positive contribution (NVDA,
+3.14%) is unrealised.

### covid (7 trades)

Every material line is `open_at_end`: NVDA (2020-04-07, 58 bars, +36.86%, +6.85%), NFLX (2020-03-30,
64 bars, +25.29%, +4.59%), SOXX (+2.06%), META (+2.03%). Top-3 share **81%**; without them the card
returns **+2.32%**. **+16.49% of the +15.83% total is unrealised** -- more than the entire reported
return, meaning the handful of realised trades in this window were net small losers and the whole
positive number is four still-open positions marked at the window boundary.

### q4-2018 (2 trades)

Only one row clears the threshold: ORCL, 2018-12-04 to 2018-12-07, -5.65%, -101, -1.01%. Too thin to
compute a top-3 concentration figure; no material unrealised component recorded for this window.

### recent (14 trades)

| symbol | entry | exit | bars | exit reason | trade return | P&L | share |
|---|---|---|---:|---|---:|---:|---:|
| SOXX | 2026-04-07 | 2026-07-30 | 79 | rule | +43.15% | +740 | +7.40% |
| META | 2026-07-15 | 2026-07-31 | 12 | stop | -18.17% | -241 | -2.41% |
| AVGO | 2026-08-06 | _open_ | 8 | open_at_end | -9.69% | -163 | -1.63% |
| META | 2026-02-02 | 2026-02-19 | 12 | rule | -10.73% | -153 | -1.53% |
| NVDA | 2025-12-31 | 2026-02-06 | 25 | rule | -6.89% | -118 | -1.18% |
| NVDA | 2026-07-16 | 2026-07-29 | 9 | rule | -6.91% | -116 | -1.16% |
| NVDA | 2026-02-11 | 2026-03-06 | 16 | rule | -6.65% | -115 | -1.15% |

Top-3 share **100%** of gross winning P&L (SOXX alone effectively is the winning side); without it the
card returns **-10.51%**. SPY rose +20.62% this window; the card's five NVDA/META losers cost more
than SOXX's one big win recovered, producing the round's worst adjusted excess for this card, -7.26%.
**-2.61% of the return sits in an open, losing AVGO mark** -- a small negative drag from an unresolved
position, not a hidden positive.

## 4. Concentration, summarised

| window | top-3 share of gross wins | return without top-3 |
|---|---:|---:|
| bear-2022 | n/a (too few winners) | n/a |
| bull-2024 | 68% | +2.67% |
| chop-2015 | 77% | -7.01% |
| covid | 81% | +2.32% |
| q4-2018 | n/a | n/a |
| recent | 100% | -10.51% |

Four of six windows swing from a double-digit positive headline to flat-or-negative once the top three
trades are removed. This is a card whose result is concentrated in a small number of large, long-held
positions in every window it wins -- consistent with its own thesis (average winners 4.1x average
losers in the design-window measurement) but meaning the headline number is fragile to any one of
those positions resolving differently.

## 5. Realised versus marked

| window | share of return that is unrealised mark |
|---|---:|
| bull-2024 | **+22.97%** of +22.75% total -- essentially the entire result |
| covid | **+16.49%** of +15.83% total -- more than the entire result |
| chop-2015 | +8.50% of +11.00% total |
| recent | -2.61% (a small negative drag) |
| bear-2022, q4-2018 | none material |

**Flag: in the card's two best windows (`bull-2024`, `covid`), the reported return is not money taken
-- it is a mark on positions still open when the window closed.** `bull-2024`'s +22.75% total return
would have been roughly +2.67% had every position instead been forced closed at the window boundary
(the same figure as "return without the top-3 winners," since those three are exactly the open
positions). This is the ordinary shape of a 120-day-hold trend card measured over a fixed window --
the biggest wins are the ones still running -- but it means the headline comparison against SPY is
sensitive to where the window happens to end, not just to what the strategy did.

## 6. Verdict on the claim, and recommendation

**The blind loss looks like the truth, not the outlier -- but round 2 supplies less genuinely new
evidence than the window count suggests.** Per `PROTOCOL.md` §6(a), a promotion must rest on the
median over windows the *previous* round did not have. Round 1's window set was `{covid, bear-2022,
bull-2024, recent}`; round 2 reruns those four (bit-identical to four decimal places, modulo a ≤0.1pp
shift from the D2 capital-exposure engine fix noted in `REPORT.md` §6) and adds exactly two new draws:
`q4-2018` (-0.97%) and `chop-2015` (+11.02%). Recomputing the same four windows is not a second
observation of them -- it is the same measurement restated, per `REPORT.md` §1.

On the genuinely new evidence, the median is `(-0.97 + 11.02)/2 = +5.03%` -- positive, and it happens
to equal the full six-window median by coincidence of where the two new values fall in the sort order.
But it rests on two windows that disagree sharply (a near-zero loss and a double-digit win), and both
values sit comfortably inside the **±20-point / σ=21.2-point ordering-noise band** `PROTOCOL.md` §6(b)
and §7 require any promotion margin to clear. A median built from two draws that far apart, neither of
which individually clears that floor, has not demonstrated a regime-independent edge.

What the fresh evidence does confirm is the *shape*, not resolve the *question*: `recent` (this
round's closest analog to the original blind window) is again the worst window, at -7.26% adjusted
excess against round 1's -7.21% -- the same underlying trades, not a new confirmation, but consistent
with a card that struggles in whatever regime the original blind period and this round's `recent`
share. `bear-2022`, the other grinding non-crash regime, is also negative (-5.82%). Three of six
windows are negative; the card wins cleanly only in V-shaped snapbacks (`covid`) and clean uptrends
(`bull-2024`, `chop-2015`'s NFLX/META legs), and both of its best wins are mostly unrealised marks
rather than closed trades (§5). The original blind loss reads as a real, recurring regime dependency,
not sampling noise -- but that conclusion rests more on the repeated `recent`/`bear-2022` weakness than
on the two new windows, which split roughly down the middle.

**Recommendation: retain as a candidate; do not promote to `base/`.** The mechanical gate (positive
median, two consecutive rounds, differing window sets) is nominally met, but the amended noise-floor
condition is not: neither new-window value clears the ordering-artifact band on its own, and the
overall margin is thin. Carry `C-trend` into round 3 unchanged. A third data point from a window that
resembles `recent` or `bear-2022` (grinding, late-cycle, or whipsaw) rather than another clean
uptrend or snapback would be the sharpest test of whether the blind-window weakness is structural.

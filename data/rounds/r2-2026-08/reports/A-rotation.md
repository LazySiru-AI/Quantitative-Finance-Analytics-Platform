# A-rotation — Semis Breadth-Capped Rotation — round 2 report

Agent: `A-rotation` | Discipline: `pairs-rotation` | Library status: `base/` | Eligible: 7/8 main
windows (blocked from `gfc` — AVGO's first bar is 2009-08-06, later than the window needs; every
A-family card shares this floor). Clears the regime gate (5/8) with margin to spare.

## 1. What the card is

One absolute condition applied identically across a 9-name cyclical-semiconductor universe (`MU INTC
AMD TSM SOXX NVDA AVGO QCOM MRVL`, ordered by trailing 12-month return through the design cutoff):
`close > sma(50) and 55 < rsi(14) < 80` to enter, `close < sma(50) or rsi(14) < 45` to exit,
backstopped by a 12% stop, a 20% take-profit, a 120-day hold cap, 3 concurrent slots at 30% of equity
each. The engine has no cross-sectional comparison, so "rotation" means only the 3-of-9 cap; when
more than three names qualify on a session the broker fills in the order the universe array is
written — a fixed tiebreak, not a strength ranking. The card's own author measured 0.589 mean pairwise
daily-return correlation across the nine names and called this "a concentrated sector bet dressed as a
3-of-9 rotation, not a diversified basket." That is the frame for everything below.

Four variants isolate one decision each against this card: `A1-alpha-order` (universe reordered
alphabetically — a pure control), `A2-cash-headroom` (4 slots × 22% instead of 3 × 30%),
`A3-no-target` (the 20% take-profit removed), `A4-tight-stop` (stop cut to 8%). This report gives the
base card's own numbers in full; the variants' reports carry their own head-to-head detail against it.

## 2. Versus SPY, every window

| window | sessions | card | SPY | excess | adj. excess | cap. exp | max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `q4-2018` | 65 | **-15.79%** | -20.05% | +4.26% | **-8.76%** | 35.0% | -17.23% |
| `covid` | 93 | **+0.46%** | -8.71% | +9.18% | **+4.94%** | 51.3% | -17.85% |
| `bear-2022` | 196 | **-33.27%** | -25.14% | -8.13% | **-27.41%** | 23.3% | -34.55% |
| `chop-2015` | 260 | **-7.18%** | -0.04% | -7.14% | **-7.16%** | 48.8% | -19.46% |
| `chop-2011` | 260 | **-17.03%** | -0.05% | -16.98% | **-17.01%** | 44.7% | -24.85% |
| `bull-2024` | 250 | **+10.74%** | +14.00% | -3.25% | **+1.56%** | 65.6% | -22.88% |
| `recent` | 249 | **+95.28%** | +20.62% | +74.66% | **+80.25%** | 72.9% | -13.24% |

**Median adjusted excess −7.16%** across all seven eligible windows (sorted: −27.41, −17.01, −8.76,
**−7.16**, +1.56, +4.94, +80.25). Worst window `bear-2022` at −27.41%. Hit rate 3 of 7. On the
six-window set the round uses for cross-family comparison (dropping `chop-2011`, which `B-momentum`
cannot run), median is **−2.80%** — still negative, and this is the figure the round's own
`scorecard-common6.json` reports. Per `REPORT.md` §3: on `recent` alone this card is the best thing in
the program; across eight windows (main matrix, `gfc` excluded by ineligibility) it ranks **20th of
22**. Both statements describe the same card.

### What moved the number, window by window

**`bear-2022`** — 22 trades, fully realised, every exit `rule` (neither the 12% stop nor the 20%
target ever fired — see `A3-no-target`'s report §3a for the verified confirmation). Largest movers:

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |
|---|---|---|---|---|---|---|---|
| INTC | 2022-07-28 | 2022-07-29 | 1 | rule | -11.30% | -335 | -3.35% |
| AMD | 2022-05-31 | 2022-06-13 | 9 | rule | -11.00% | -327 | -3.27% |
| AVGO | 2022-01-03 | 2022-01-14 | 9 | rule | -10.68% | -320 | -3.20% |
| MU | 2022-01-03 | 2022-01-21 | 13 | rule | -10.41% | -313 | -3.13% |

Every material trade in this window is a loser except one (QCOM, +5.19%/+$154). The confirmed
uptrend filter bought into a sector that kept rolling over through the whole window; the trend-break
exit fired repeatedly, at a loss, session after session. This is the mechanism the card's own thesis
warned about: correlated names move together, and 2022 was the semiconductor cycle turning down.

**`q4-2018`** — 9 trades, no winners among the material list at all: AMD stopped out at −14.39%
($−431) after an 11-bar hold, and every remaining position closed for a smaller loss. One position
(AVGO, entered 2018-12-11) was still open at the window's close at −4.02% ($−122, −1.22% of return) —
a mark, not a further realised loss, but not a gain either. The card still beat SPY's −20.05% by 4.26
points of raw excess simply by holding less capital through a slower selloff than the benchmark did,
which the adjusted-excess figure (−8.76%) treats as a lesser achievement than it looks on excess alone.

**`covid`** — 13 trades. NVDA, entered 2020-04-07, hit the 20% target on 2020-05-18 for +26.22%
($813, 8.13% of card return) — the single trade carrying this window. Two more NVDA/TSM/SOXX
positions were still open at the window's close, contributing +6.91% of the card's return as marks.
Strip the top three winners (NVDA above, and two smaller ones) and the card returns **−13.51%** in
this window rather than +0.46% — 90% of gross winning P&L sits in three trades.

**`chop-2015`** — 33 trades. AMD (2015-11-19→2015-12-17, +19.99%/$594) and NVDA
(2015-08-28→2015-10-15, +19.27%/$582) are the two biggest winners; MRVL adds +16.50%/$498. Those
three produce 75% of gross winning P&L; without them the card returns **−23.92%**. A stop-out on AMD
two months earlier (2015-07-06→2015-07-08, −15.86%/−$462) and one on MU (−12.59%/−$378) are the
largest single losses.

**`chop-2011`** — 26 trades. Only two real winners carry the window: MU (2011-12-23→2012-01-20,
+20.64%/$627, target) and INTC (2011-12-28→2012-04-24, +11.45%/$343, an 80-bar hold that rode the exit
rule rather than the target). Those two are 88% of gross winning P&L; without them the card returns
**−28.23%** against a benchmark that itself moved only −0.05%. Every other material trade in this
window is a loss in the 4–8% range.

**`bull-2024`** — 39 trades, the family's most balanced window. Three winners (MRVL +30.68%/$903,
AVGO +27.98%/$810, AMD +24.61%/$720) are 40% of gross winning P&L; without them the card still
returns **−13.59%** — a meaningfully worse but not catastrophic number, because this window has real
breadth on both sides. +2.29% of the return sits in three positions (SOXX, AMD, and part of TSM) still
open at the close.

**`recent`** — 47 trades, the card's best window by a wide margin. The three largest winners (INTC
+43.12%/$1,260 target; INTC +28.97%/$866 target; TSM +27.44%/$820 target) are only **21%** of gross
winning P&L — strip them and the card still returns **+65.82%**. This is the family's most broadly
distributed result: no small number of trades is doing the work. −3.50% of the return sits in
positions open at the close (a losing AVGO mark).

## 3. Concentration, summarised

| window | top-3 share of gross winning P&L | return without top 3 |
|---|---:|---:|
| `bear-2022` | 100% | -35.16% |
| `q4-2018` | n/a — no material winners | — |
| `covid` | 90% | -13.51% |
| `chop-2015` | 75% | -23.92% |
| `chop-2011` | 88% | -28.23% |
| `bull-2024` | 40% | -13.59% |
| `recent` | **21%** | +65.82% |

The card is a different proposition in different regimes. In five of seven windows, three trades (or
fewer, when there are no winners at all) carry 75–100% of the whole gross winning side — this is a
concentrated book whose result is set by a handful of positions, consistent with the 0.589 mean
pairwise correlation its own author flagged. `recent` is the exception: with 47 trades and only 21% of
winning P&L in the top three, that window's result reflects broad participation across the universe
rather than a few outsized bets. A reader should not treat the card's typical behaviour as broad; treat
`recent` as the outlier regime where breadth showed up, not as the norm.

## 4. Realised versus marked

Every window's result is overwhelmingly realised. The only material open-at-end exposure is small:
`bull-2024` (+2.29%), `covid` (+6.91%), `chop-2015` (+2.24%), `q4-2018` (−1.22%), `recent` (−3.50%).
None of these flips a window's sign or materially changes its story — even `covid`'s marks, the
largest at +6.91% of return, sit on top of an already-positive realised base. `bear-2022` and
`chop-2011` carry no open-at-end positions at all; both windows' results are entirely money already
taken (or lost).

## 5. Verdict and promotion recommendation

Round 1 (four windows: covid, bear-2022, bull-2024, recent) gave this card a positive median adjusted
excess of +3.23%. Round 2 adds three windows round 1 never had — `q4-2018`, `chop-2015`,
`chop-2011` — and on those three alone the median is **−8.76%** (values −8.76%, −7.16%, −17.01%),
negative. Per `PROTOCOL.md` §6(a) as amended, a demotion from `base/` requires a negative median in
**two consecutive rounds measured on non-overlapping evidence**. Round 1's result was positive, so this
round's negative new-window median is one data point, not two — the demotion condition is not met.

**Recommendation: retain in `library/base/`.** The case for caution is real and should be stated
plainly: every window round 2 added that round 1 did not have came back negative for this card, and
two of the three (`chop-2011` at −17.01%, `chop-2015` at −7.16%) are not close results. If round 3
also returns a negative median on whatever new window it adds, the demotion condition would then be
met on genuine grounds — this round only establishes the first half of that evidence, not the whole
case.

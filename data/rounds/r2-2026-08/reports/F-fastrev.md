# F-fastrev -- Fast Reversion, Low-Exposure Satellite -- round 2 report

Agent: `F-fastrev` | Discipline: `mean-reversion` | Eligible: 2/8 main windows -- **unranked**, far
below the round-2 five-of-eight gate (see `results/eligibility.json`)

## 1. What the card is, its claim, and why it can run in only two windows

Entry is a short, sharp dislocation: `rsi(3) < 15 and close < bb_lower(10,2)`, exiting on the first
close back above `ema(5)`. `stop_loss_pct = 0.07`, `take_profit_pct = 0.05`, `max_hold_days = 8` -- a
tight, fast-cycling design built on a measured finding (306 dislocations in the design window) that
this kind of air-pocket resolves in a median of 4 sessions. Universe: `AMD MU AVGO QCOM MRVL CRDO NET
SOXX TSM NVDA`. The claim under test is explicit in the card's own framing: "judged as a market
substitute it fails; judged as a satellite sleeve it may not" -- it should be scored against
cash-adjusted terms, not raw benchmark, because it is designed to hold roughly 7% of capital.

**Eligible for `bull-2024` and `recent` only**: `eligibility.json` gives `CRDO first bar 2022-01-27`
as the binding constraint against `q4-2018`, `covid`, `bear-2022`, `chop-2015` and `chop-2011` alike.
CRDO IPO'd in 2022, structurally excluding every regime before it.

**Round 2 added no new window for this card.** As with `E-asymmetric`, no calendar time passed
between rounds (`REPORT.md` §9), so CRDO's first bar has not moved and the eligible set is
`{bull-2024, recent}`, identical to round 1.

## 2. Versus SPY, its two eligible windows

| window | sessions | card | SPY | excess | adj. excess | cap. exp | max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| bull-2024 | 250 | **-7.05%** | +14.00% | -21.04% | -8.06% | 7.3% | -19.94% |
| recent | 249 | **+36.45%** | +20.62% | +15.83% | +34.91% | 7.4% | -4.58% |

Two windows against a five-of-eight (round 2) or three-window (round 1) minimum -- no median, worst,
or hit rate beyond the pair itself. **Both figures are the same measurement round 1 recorded**
(-8.05%/+34.91% then, -8.06%/+34.91% now, the 0.01pp difference being the D2 engine-fix tolerance),
not fresh evidence.

## 3. What moved the number

### bull-2024 (41 trades)

| symbol | entry | exit | bars | exit reason | trade return | P&L | share |
|---|---|---|---:|---|---:|---:|---:|
| MRVL | 2025-03-28 | 2025-04-04 | 5 | stop | -18.56% | -276 | -2.76% |
| AVGO | 2025-03-27 | 2025-04-04 | 6 | stop | -16.68% | -237 | -2.37% |
| CRDO | 2025-02-25 | 2025-02-28 | 3 | stop | -14.45% | -205 | -2.05% |
| MRVL | 2025-04-07 | 2025-04-08 | 1 | target | +14.17% | +202 | +2.02% |
| CRDO | 2025-01-28 | 2025-01-31 | 3 | target | +12.75% | +198 | +1.98% |

Exit-reason split: 9 rule, 18 stop, 12 target, 0 time -- 43.9% of trades resolved at the 7% stop. Top-3
share of gross wins is **33%**; without the three largest winners the card returns **-12.92%** instead
of -7.05%.

### recent (48 trades)

| symbol | entry | exit | bars | exit reason | trade return | P&L | share |
|---|---|---|---:|---|---:|---:|---:|
| CRDO | 2026-02-05 | 2026-02-09 | 2 | target | +18.01% | +259 | +2.59% |
| MU | 2026-07-30 | 2026-07-31 | 1 | target | +15.83% | +251 | +2.51% |
| CRDO | 2026-07-30 | 2026-07-31 | 1 | target | +15.25% | +228 | +2.28% |
| CRDO | 2026-07-17 | 2026-07-21 | 2 | target | +15.85% | +215 | +2.15% |

Exit-reason split: 21 rule, 3 stop, 23 target, 1 time -- only 6.3% of trades resolved at the stop, the
mirror image of `bull-2024`. Top-3 share **18%**; without them the card returns **+29.06%** instead of
+36.45% -- the smallest concentration drop of any window examined in this batch of six cards, i.e.
this window's edge is genuinely broad-based across 48 trades, not carried by a few outsized wins.

## 4. Concentration, and why the benchmark comparison is the wrong lens

| window | top-3 share of gross wins | return without top-3 |
|---|---:|---:|
| bull-2024 | 33% | -12.92% |
| recent | 18% | +29.06% |

`excess` (return against the fully-invested SPY benchmark) swings from -21.04% to +15.83% between the
two windows; `adjusted_excess` (return against a benchmark scaled to actual capital deployed) swings
from -8.06% to +34.91%. Both corrections point the same direction: raw excess punishes this card for
not being invested roughly 93% of the time, which is the design, not a defect. A book running ~7%
capital exposure compared against a 100%-invested SPY is being scored on a question ("did you replace
the index?") it never claimed to answer. Read on capital-adjusted terms, this round is genuinely
mixed: `bull-2024` cost the book about 8 points of capital-adjusted return; `recent` earned nearly 35.
Both are real outcomes of a low-capital, high-turnover satellite sleeve.

## 5. Realised versus marked

`bull-2024` carries **-0.33%** unrealised (a small negative drag); `recent` carries **no** open
position at the window boundary. Both results are almost entirely realised, consistent with the
card's tight `max_hold_days = 8` design -- there is little room for a large mark-to-market component
to accumulate.

## 6. The stop gap

21 of 89 trades (23.6%) resolved at the stop, nominal `stop_loss_pct = 0.07`. Mean realised loss
across all 21 stop-outs: **-9.41%**, a **2.41 percentage point** gap beyond nominal -- the smallest
such gap of any card examined in this program's reports, consistent with the short median hold (most
stops resolve in 1-7 bars, leaving little time for a previous-close-based stop to be overtaken by
further adverse movement before the fill). Worst individual case: MRVL, -18.56% (2025-03-28 to
2025-04-04, 5 bars), more than 2.6x the nominal level.

## 7. Verdict on the claim, and recommendation

**The claim holds, on the same evidence round 1 already supplied.** Judged as a market substitute this
card fails outright (-21.04% raw excess in `bull-2024`); judged as a satellite sleeve against
capital-adjusted terms it is genuinely mixed, not uniformly bad (-8.06% in one window, +34.91% in the
other). Nothing in round 2 changes that reading, because round 2 reran the identical two windows to
within engine-fix tolerance rather than supplying new ones.

**Not rankable, and round 2 changed nothing about that.** Two of eight main windows against a
five-window minimum that has widened since round 1's three-window floor. What would change this: the
same walk-forward mechanism as `E-asymmetric` -- round 3 adds a window measured from further elapsed
time, and since every window after `bear-2022` falls after CRDO's 2022-01-27 first bar, that new
window becomes this card's third eligible one without any change to the card. `bear-2022` itself would
also become reachable if the universe swapped CRDO for a pre-2022 name with a similar fast-reversion
profile, though that changes the universe rather than merely waiting.

**Recommendation: retain as a candidate; do not promote, and do not score it against the field's
benchmark-relative ranking even once it clears the gate.** The median-adjusted-excess key still
implicitly assumes the benchmark comparison is the right one for every card, which §4 above argues it
is not for a card whose entire design point is minimal capital commitment. Carry it forward for a
third window next round, and continue to report the blended-portfolio framing (return per dollar
actually deployed) as the supplementary metric this card needs, since the standard scorecard columns
do not surface it on their own.

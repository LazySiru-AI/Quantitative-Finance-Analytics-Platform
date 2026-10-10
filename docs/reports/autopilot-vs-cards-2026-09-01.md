# Autopilot vs. Cards — Measured Comparison, 2026-09-01

*Compiled 2026-09-01. Covers the Agent Workflow's two paper books (`raw_signal`, `full_workflow`) against
the four seated strategy cards, all re-measured over one shared window on the paper desk's own metric.
Not investment advice.*

---

## Bottom line

**The Autopilot seat itself is not yet measurable.** `full_workflow` — the gated book, the actual
product (regime → screen → research → gate) — returned **+0.00%** because it holds **0 orders**: its
research gate has passed no candidate over this window. This is the same condition the programme's own
study reports elsewhere as `passed_n = 0` for every gate. There is nothing to score.

What *is* measurable is the **ungated null arm**, `raw_signal` — the screened universe with no research
gate at all — and over this window it beat every seated card and both benchmarks: **+6.41%**, against
seated-card returns of −3.96% to −12.10% and SPY/QQQ of −1.24%/−2.24%.

That headline should not survive first contact, and this report exists to take it apart:

1. **It is the null arm, not the Autopilot.** The book that won is defined by the absence of the gate
   the product is built around. The gated arm — the one this feature is actually meant to ship — traded
   nothing.
2. **The gap looks like universe, not skill.** The screened book's holdings are biotech/genomics/airlines/
   oil names in a month biotech ran hard; the seated cards' universes are semis/mega-cap-tech shaped in a
   month semis fell. This is the programme's own recurring finding restated, not a new one: apparent
   edges in this programme have repeatedly turned out to be universe selection, not rule skill.
3. **21 sessions is far inside the noise floor.** The programme's established noise floor is **21.2
   percentage points** (one standard deviation, from re-running one identical card under twelve universe
   orderings). The spread among these seats is roughly 8 to 18 points, over one month — smaller than the
   floor, so it is not evidence of anything.

None of this makes the null arm's result fake — it is a real, measured +6.41% over a real 21-session
window. It just is not evidence that the Autopilot works, because the Autopilot did not trade, and it is
not strong evidence of universe skill either, because it sits inside the noise floor.

---

## The window and what was measured

All seats below are measured over the **same** window, **2026-08-04 to 2026-09-01, 21 trading sessions**,
on the paper desk's own metric. To make this comparison possible, the desk inception was temporarily
moved to the workflow book's own start so every seat shared one window, then restored — this is a
measurement step, not a change to any seat's real trading history.

Mechanical exits (the card's own stop, take-profit, hold cap, and exit rule) were added to the workflow
on 2026-09-01 and are reflected in the numbers below. Before that date the workflow staged buys only,
so any comparison to numbers from before 2026-09-01 is not apples-to-apples with this table.

| Seat | Kind | Return | Excess vs SPY | Max drawdown | Capital exposure | Closed trades | Open holdings |
|---|---|---|---|---|---|---|---|
| Workflow `raw_signal` (screened universe, no research gate — the study's null arm) | autopilot | **+6.41%** | n/a | −2.09% | 0.95 | 1 | 5 |
| Workflow `full_workflow` (the Autopilot seat — regime → screen → research → gate) | autopilot | **+0.00%** | n/a | +0.00% | 0.00 | 0 | 0 |
| B3-concentrated | rules | −5.74% | −4.50% | −6.71% | 0.66 | 1 | 3 |
| A-rotation ("Strategy A — Semis Breadth-Capped Rotation") | rules | −12.10% | −10.86% | −13.31% | 0.57 | 7 | 1 |
| C-trend | rules | −3.96% | −2.72% | −5.31% | 0.38 | 2 | 2 |
| B-momentum ("Strategy B — Confirmed Acceleration") | rules | −5.56% | −4.32% | −5.86% | 0.51 | 1 | 4 |

**Benchmarks over the same window:** SPY **−1.24%**, QQQ **−2.24%**.

Excess vs. SPY is reported as "n/a" for both workflow seats in the source data — not zero, not omitted by
this report, genuinely not computed for those two rows. It is not filled in here.

**Excluded from this table: `I-13f-duquesne-2026q2`.** It is a `desk_only` trading card whose
`designed_through` date is 2026-08-14 — inside this window, which opens 2026-08-04. The desk refuses to
trade a card over a window its own author already had sight of when the card was designed, because
including it would be lookahead. That refusal is correct and this report does not attempt to work around
it or estimate a number in its place.

**A currency caveat, not a returns caveat:** the workflow books start with $100,000; the trading book's
cards start with $60,000. The percentage returns in the table above are directly comparable across seats.
Dollar P&L figures are not, and none are used in this report for that reason.

---

## Point 1 — the seat that won is the seat with no gate

`full_workflow` is the Autopilot: regime detection, universe screening, per-candidate model research, and
only then a gate that allows or blocks an entry. Over this window it opened **0 orders** and closed
**0 trades**, so its return is exactly **+0.00%** and its max drawdown is exactly **+0.00%** — not a
small number, an empty book. Its research gate has passed no candidate in this window. This is the same
underlying condition the programme's own effectiveness study reports as `passed_n = 0` for every gate: no
researched candidate has yet cleared the bar the Autopilot is built to enforce.

`raw_signal` is the same screen, the same universe, run with the gate removed entirely — every signal the
screen produces gets traded. It is explicitly the study's null arm, not a second product. Its **+6.41%**
is a real, measured return on a real 21-session book (0.95 capital exposure, 1 closed trade, 5 open
holdings) — but it is the return of "trade everything the screen finds," which is precisely the behavior
the research gate exists to filter.

So the correct reading is not "the workflow beat the cards." It is: **the gated product has not traded
yet, and the ungated fallback happened to do well this month.** Those are two different claims, and only
the second one has a number attached.

---

## Point 2 — the gap tracks universe, not skill

The `raw_signal` screened book's 5 open positions are **XBI, ARKG, IBB, JETS, USO** — biotech, ARK
genomics, biotech, airlines, oil. Its one closed trade is **JETS, stopped out**. Over this window,
biotech ran hard while semiconductors fell. The seated rules cards' universes are semis/mega-cap-tech
shaped — most visibly `A-rotation`, "Strategy A — Semis Breadth-Capped Rotation," which posted this
window's worst return at −12.10% (−10.86% excess) — while the screened universe that fed `raw_signal`
happened to be biotech shaped.

This is not a new finding invented for this report. It is the programme's own recurring result, restated
in a new instance: apparent outperformance in this system has repeatedly traced back to which universe a
seat happened to hold, not to any skill in its selection or entry rules. Nothing in this window's data
distinguishes "the screen is smarter" from "the screen happened to be pointed at biotech in a month
biotech ran and semis didn't."

---

## Point 3 — 21 sessions is far inside the noise floor

The programme's established noise floor is **21.2 percentage points, one standard deviation**, set by
re-running a single identical card under twelve different universe orderings. Any margin smaller than
21.2pp is not distinguishable from that ordering noise — it is not evidence of a real effect either way.

The spread among the seats measured here is roughly 8 to 18 points, over a 21-session (one-month) window
— inside the 21.2pp floor. A one-month result this size, however directionally clean it looks in the
table above, does not clear the bar this programme has set for itself to call something a real edge.

---

## What would make this measurable

Two gaps have to close before the Autopilot vs. cards question can actually be answered:

- **Gated candidates need to accrue.** The study's own pre-registered floor is **60 sessions and 40
  gated candidates** before its decision rule may even be evaluated. Today `full_workflow` has traded
  zero times in 21 sessions — both thresholds are unmet, and by a wide margin on the candidate count.
- **The window needs to clear the noise floor.** 21 sessions produced an 8-to-18-point spread against a
  21.2-point floor. Whatever the true effect size turns out to be, a longer window is needed before a
  margin like this one can be called anything other than noise.

Until both of those are true, the honest statement is the one at the top of this report: the Autopilot
seat is not yet measurable, the null arm's win this month is real but explained at least as well by
universe as by skill, and none of it clears the programme's own bar for evidence.

---

## Appendix — source

All figures in this report are transcribed from a single verified measurement pass dated 2026-09-01,
covering the paper desk's `raw_signal` and `full_workflow` workflow books and the four seated trading
cards (`B3-concentrated`, `A-rotation`, `C-trend`, `B-momentum`) over 2026-08-04 to 2026-09-01 (21
trading sessions), plus SPY/QQQ benchmarks over the same window. No figure in this report was computed,
recomputed, extrapolated, or annualised — every number above appears exactly as measured.

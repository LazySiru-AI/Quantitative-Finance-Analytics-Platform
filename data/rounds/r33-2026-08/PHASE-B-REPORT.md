# Round 33 Phase B — status report (2026-09-01)

Selector `mom12_1_hysteresis`, screen top 10, entry rule `close > sma(200) and ema(20) > ema(50)`, max 3 researched symbol(s)/session. Not investment advice.

## Floor status

> **MONITORING, NOT EVIDENCE** — Phase B has not reached its §4 floor yet.

- Sessions observed: **21** / 60 required
- Gated candidates (`full_workflow`, ruled, not skipped): **0** / 40 required
- Floor met: **False**

## Accrual

- Observations: **132** total (27 resolved, 105 pending, 0 unpriceable)
- Distinct symbols: **10**
- Sessions: 2026-08-03 .. 2026-08-31
- Skip reasons: weekly_budget_exhausted=0, no_book_capacity=0, tax_wash_sale_blocked=0, correlation_duplicate=0, budget_exhausted=132
- Verdict sources: fresh=396, cached=0, mixed=0
- Avoided cost (cached verdicts): $0
- Gated candidates per gate: ta_gated=0, vibe_gated=0, full_workflow=0
- Resolved mean forward return: 7.84%  |  Resolved hit rate: 88.89%

## Spend

- Screen-mode workflow runs: **2**
- Screen-mode spend: $0

## Arm metrics (screen books)

| arm | total_return | adjusted_excess | exposure | realized_vol | win_rate | trades | net_adjusted_excess | research_cost |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| raw_signal | 5.12% | 4.60% | 95.45% | 1.26% | — | 5 | 4.60% | $0 |
| full_workflow | 0.00% | 0.00% | 0.00% | 0.00% | — | 0 | 0.00% | $0 |

## Paired comparison (vs raw_signal/screened)

| arm | mean_daily_diff | bootstrap_p |
|---|--:|--:|
| full_workflow | -0.2349% | 0.2652 |

## Discrimination

`WorkflowStudy.discrimination` below is the three-gate, **m = 3** result (`app.workflow.study` reused unmodified, per `docs/WORKFLOW-STUDY-PLAN.md` §4's design). The §6 decision rule for Phase B uses a separate, one-gate **m = 1** recomputation on `full_workflow` alone, per `docs/WORKFLOW-UNIVERSE-STUDY-PLAN.md` §1.2 -- shown on its own row below, not in this table.

| gate | passed_n | refused_n | passed_hit | refused_hit | mean_diff | p_value | q_value |
|---|--:|--:|--:|--:|--:|--:|--:|
| ta_gated (m=3) | 0 | 27 | — | 88.89% | — | — | — |
| vibe_gated (m=3) | 0 | 27 | — | 88.89% | — | — | — |
| full_workflow (m=3) | 0 | 27 | — | 88.89% | — | — | — |

## Verdict

**below_floor**

Below the §4 floor (60 sessions, 40 gated candidates): monitoring, not evidence -- the decision rule is not evaluated.

## Caveats

- Backfilled observations were research-starved: candidates seeded outside a live Phase B step never had a child run launched against them, so their gate rulings are defaults, not judgements, and should not be read as the gate having considered them.
- Heavy symbol overlap means the effective independent sample can be far below the row count: this window has 10 distinct symbol(s) against 132 observation(s) -- when the former is small relative to the latter, treat the discrimination test's n as an upper bound on independent information, not a literal count of independent draws.
- Card-mode books and candidates are excluded entirely from every figure above: this report covers `universe_source == "screen"` only, per `docs/WORKFLOW-UNIVERSE-STUDY-PLAN.md` §7's guardrail that the two cohorts are not comparable session-for-session.

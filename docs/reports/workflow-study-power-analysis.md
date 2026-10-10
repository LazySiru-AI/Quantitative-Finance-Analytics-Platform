# Agent Workflow study — power analysis and time-to-bar projection

Generated 2026-08-31, against three existing workflow runs (one real, zero fills) and the real
`data/store/bars` history. Produced by `backend/app/workflow/power_analysis.py`, tested by
`tests/test_workflow_power_analysis.py`.

**This is planning information. It does not alter, relax, or pre-empt
`docs/WORKFLOW-STUDY-PLAN.md` §7's pre-registered decision rule in any way.** The rule is still
evaluated exactly as `app.workflow.study` computes it, once real data clears the bar, and nothing
below substitutes for that. Every number here comes from a Monte Carlo simulation and a historical
signal-firing count, not from any live workflow run's results.

## 1. Question and method

§7 requires **60 trading sessions and 40 gated candidates** before the decision rule is evaluated at
all. As of today, three workflow runs exist and zero orders have filled — nowhere near the bar. Two
questions follow:

**Update, as of 2026-09-01:** the counts above are stale — `data/agentdesk/workflow/runs/` now holds
26 run files, and the card-mode books still show zero filled orders while the screen-mode books
(`book/screen/*.json`) show 5. Separately, Round 33 Phase B (screen mode, with the `screen_entry_rule`
relaxed entry) produced 132 screen-mode candidate observations over 21 backfilled sessions across 10
distinct symbols — well short of the §7 floor's *gated*-candidate count (every backfilled candidate
was research-skipped by design, so the gate's effectiveness is still unmeasurable), but a large jump
in raw candidate-arrival rate from the ~0.1/session this document projects below. See
`docs/reports/EVERYTHING-INVESTIGATED-2026-09-01.md` §4-5 for the full measurement and its caveats.

1. **If the bar is reached, can the §4 discrimination test detect an effect size this programme's own
   record makes plausible?** Answered by `simulate_discrimination_power`, a zero-cost Monte Carlo
   simulation reusing `app.backtest.scan.binomial_p_value` and `.benjamini_hochberg` verbatim — the
   same `m = 3` pipeline `app.workflow.study._discrimination` runs.
2. **At the desk's own historical candidate-arrival rate, when does the bar get crossed?** Answered by
   `estimate_candidate_arrival_rate`, which reads the real stored bar history for every card
   `regime_map.json` can route to and counts how often each card's entry rule would have fired,
   capped at `max_research_symbols` (3) per session — the same cap
   `app.workflow.pipeline._stage_candidate_scan` applies to what actually becomes a gated candidate.

Both are reproducible exactly: the power simulation is deterministic given `seed` (default `0`), and
the arrival-rate figures below are read directly off `data/store/bars`, not fabricated.

## 2. Power curve

Monte Carlo power (fraction of 6,000 simulated draws per cell reaching `full_workflow`'s
Benjamini–Hochberg-adjusted q-value ≤ 0.10, the pre-registered threshold) at `pass_fraction=0.40`,
`baseline_hit_rate=0.50`, `seed=0`. Effect size is the assumed true hit-rate gap between the passed
and refused sets, in percentage points.

| Gated candidates | 0 pp (null) | 2 pp | 5 pp | 10 pp | 15 pp | 20 pp | 30 pp |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10  | 0.116 | 0.116 | 0.110 | 0.119 | 0.136 | 0.155 | 0.193 |
| 20  | 0.118 | 0.124 | 0.130 | 0.143 | 0.176 | 0.227 | 0.378 |
| **40 (the pre-registered bar)** | **0.105** | **0.109** | **0.130** | **0.161** | **0.249** | **0.371** | **0.666** |
| 60  | 0.115 | 0.116 | 0.135 | 0.216 | 0.358 | 0.529 | 0.842 |
| 100 | 0.097 | 0.106 | 0.140 | 0.272 | 0.491 | 0.720 | 0.962 |
| 200 | 0.109 | 0.128 | 0.205 | 0.459 | 0.766 | 0.932 | 0.999 |
| 400 | 0.113 | 0.140 | 0.302 | 0.716 | 0.952 | 0.998 | 1.000 |

Reproduce with:

```python
from app.workflow.power_analysis import simulate_discrimination_power
simulate_discrimination_power(
    (10, 20, 40, 60, 100, 200, 400),
    (0.0, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30),
    n_draws=6000, seed=0,
)
```

**Null calibration.** The 0-pp column — no true difference between passed and refused — lands between
0.097 and 0.140 across every row, close to the nominal `q_threshold = 0.10` rather than systematically
above or below it. That is the false-positive rate the decision rule accepts by design (BH controls
the false discovery rate, not each individual test's rejection rate exactly at the nominal level), and
it is what `test_zero_effect_arm_near_nominal_rate` in the accompanying test file checks stays well
under 0.30.

**Minimum detectable effect at the 40-candidate bar.** Extending the grid at `n = 40`:

| Effect size | 25 pp | 30 pp | 35 pp | 40 pp | 45 pp | 50 pp |
|---:|---:|---:|---:|---:|---:|---:|
| Power | 0.524 | 0.675 | 0.822 | 0.914 | 0.977 | 1.000 |

**At exactly the pre-registered minimum of 40 gated candidates, reaching conventional 80% power
requires a true hit-rate gap of roughly 35 percentage points between the passed and refused sets.**
That is not a realistic effect size for this programme: the base rate this brief was scoped against is
18 consolidated rounds finding no durable edge and 1 positive cell out of 9,480 in a large timeframe
sweep. Against that record, a true effect in the 2–10 pp range is far more plausible than 35 pp, and
the table above shows the test has 10–27% power to detect an effect that size at `n = 40` — barely
above the false-positive floor. **The discrimination test is under-powered at the pre-registered
minimum for any effect size this programme has actually observed**, and stays that way well past
`n = 100`; it only becomes reasonably well powered (power ≳ 0.7) for a 10-pp effect around `n = 400`,
an order of magnitude past the bar.

This is consistent with, and quantifies, `docs/WORKFLOW-STUDY-PLAN.md` §8's own "Power" caveat: "a few
months of daily decisions on a ≤12-ticker universe... can detect a large [edge]... and it can detect
harm" — 35 pp is that "large" edge, and this simulation is the first time a number has been put on it.

## 3. Historical candidate-arrival rate

`estimate_candidate_arrival_rate`, run against the real `data/store/bars` store and the real
`backend/app/paper/library` card files, resolved all 10 cards named in `regime_map.json`:

| Card | Universe | Sessions in history | Mean gated candidates/session (capped at 3) | History window |
|---|---:|---:|---:|---|
| c18-meanrev | 10 | 14,286 | 0.533 | 1970-01-02 .. 2026-08-28 |
| c07-chop | 9 | 6,963 | 0.096 | 1998-12-22 .. 2026-08-28 |
| c19-volatility | 12 | 14,286 | 0.086 | 1970-01-02 .. 2026-08-28 |
| c09-convex | 2 | 6,060 | 0.068 | 2002-07-30 .. 2026-08-28 |
| c21-uncorrelated | 6 | 6,570 | 0.050 | 2000-07-14 .. 2026-08-28 |
| c14-riskmanaged-wide | 4 | 6,060 | 0.042 | 2002-07-30 .. 2026-08-28 |
| B-momentum | 12 | 11,708 | 0.041 | 1980-03-17 .. 2026-08-28 |
| B4-tight-stop | 12 | 11,708 | 0.041 | 1980-03-17 .. 2026-08-28 |
| C-trend | 9 | 10,643 | 0.036 | 1984-06-01 .. 2026-08-28 |
| H-trend-diversified | 7 | 10,643 | 0.020 | 1984-06-01 .. 2026-08-28 |

Unweighted mean across the 10 cards: **0.101 gated candidates/session**. Unweighted median: **0.046**
— the mean is pulled up almost entirely by `c18-meanrev` (0.533, a mean-reversion card whose rule
fires far more often than any other card's); every other card sits at or below 0.10.

**What this figure is, and is not.** Each row is that one card's own entry rule evaluated over its
*own* full stored history, as if it had been the active regime-map card every single session in that
window — it is **not** a replay of the actual regime-gated process, which trades exactly one card per
session (whichever the day's `regime.classify` call selects), and it is **not** conditioned on the
desk actually being run that day. The real workflow has produced three runs total since it existed;
this estimate assumes a run every trading session, which is an assumption about future operating
cadence, not a fact this data can supply. Treat the arrival rate as an order-of-magnitude planning
figure, not a forecast.

Reproduce with:

```python
from app.config import Settings
from app.workflow.power_analysis import estimate_candidate_arrival_rate
estimate_candidate_arrival_rate(settings=Settings())
```

## 4. Projected calendar date to the bar

The 60-trading-session leg of §7's bar is reached quickly under a daily-run assumption — roughly 12
calendar weeks (60 sessions ÷ 5 sessions/week × 7 days) from whenever daily runs begin, around
**2026-11-23** if they began today. It is not the binding constraint.

The 40-gated-candidate leg is: at the two rate estimates above, assuming one workflow run every
trading session starting today (2026-08-31):

| Rate assumption | Sessions to 40 candidates | Calendar time | Projected date |
|---|---:|---:|---|
| Mean (0.101/session, c18-meanrev-driven) | ≈396 sessions | ≈79 weeks (≈1.5 years) | **≈2028-03-06** |
| Median (0.046/session, typical card) | ≈873 sessions | ≈175 weeks (≈3.3 years) | **≈2030-01-03** |

Both dates assume the workflow runs every trading session starting immediately, which the current
operating history (three runs total) does not support — the actual date is later than either figure
if runs stay sporadic, and earlier only if the desk is deliberately run on a strict daily cadence from
now on. Neither figure should be read as a commitment or a forecast of when the study will actually
be evaluable; it is the same order-of-magnitude planning caveat as §3 above.

## 5. Bottom line

- **The discrimination test, at the pre-registered 40-candidate minimum, cannot detect any effect
  size this programme has ever actually observed** (minimum detectable effect for 80% power ≈ 35 pp,
  against a record of 0–1 pp-scale edges in ~9,500 cells tested elsewhere).
- **At the desk's own historical signal-firing rate, the 40-candidate bar is roughly 1.5–3.5 years
  away** under a daily-run assumption that today's operating history (three runs, zero fills) does not
  yet support.
- **Neither of these figures changes §7's decision rule.** The rule stays exactly as pre-registered;
  this report exists so that a figure quoted before the bar is crossed is quoted with its true power
  and true timeline attached, per §7's own "monitoring, not evidence" framing for an under-powered
  window.

## 6. Verification

```
$ .venv/Scripts/python.exe -m pytest tests/test_workflow_power_analysis.py -v
...
11 passed in 25.77s

$ cd backend && ../.venv/Scripts/python.exe -m mypy app/workflow/power_analysis.py
Success: no issues found in 1 source file

$ .venv/Scripts/python.exe -m ruff check backend/app/workflow/power_analysis.py tests/test_workflow_power_analysis.py
All checks passed!
```

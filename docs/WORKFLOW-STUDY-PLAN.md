# Agent Workflow study — does the research change the outcome?

Pre-registered 2026-08-31, before the workflow desk has staged a single order and before any
measurement in this study exists. **Not investment advice.**

The two research desks stop at prose. A Trading Agents run ends in a rating and a Vibe run ends in a
report, and neither has ever been priced. This study is the first time this project asks whether the
research is worth what it costs — in money, in latency, and in the trades it talks the desk out of.

---

## 1. The question, stated so it can fail

**Does gating a strategy's entry signals on model research improve risk-adjusted return versus
taking every signal the strategy fires?**

Four arms trade the same strategy card, from the same regime call, over the same sessions, with the
same mandate and the same starting cash. They see an identical candidate list every day. They
diverge at exactly one point — the gate that decides which candidates become orders:

| Arm | Gate |
|---|---|
| `raw_signal` | none — every candidate is staged |
| `ta_gated` | Trading Agents `final_rating ∈ {Buy, Overweight}` |
| `vibe_gated` | Vibe `VERDICT: SUPPORT` |
| `full_workflow` | the whole chain, including entry-plan sizing and stops |

`raw_signal` is the null. Not a coin flip — `app.tournament.scoring`'s own
`NULL_WIN_PROBABILITY` docstring says plainly that a coin-flip null is not a test of skill against
the market, and that a long-only strategy in a rising benchmark clears it with no edge. The honest
question is not "did the research arm make money" but "did it make more than the same strategy
without it," and the only way to ask that is to run both on the same days.

## 2. The trap this study is built around

**A filter that trades less is not thereby a better filter.** Every gate is a subset of
`raw_signal`. In a rising market, any arm that declines trades will show lower total return and
lower volatility than the raw arm, and *both* of those look like results. They are not results; they
are the mechanical consequence of being invested less of the time.

Two things guard against reading that as skill:

- **Exposure correction.** The primary metric is `adjusted_excess = total_return − exposure ×
  benchmark_return`, the programme's own headline (`strategy-program/tools/score.py`), which prices
  the time an arm spent in cash at the benchmark rather than at zero. `score.py` also carries its
  own caveat — `adjusted_excess` still correlates with exposure (r = +0.797 in one round) — so
  `excess_per_exposure` is reported alongside it and neither is read alone.
- **The discrimination test (§4), which is where the actual power is.** Comparing four equity curves
  over a few months is a low-power instrument, and this study says so in advance rather than
  discovering it at the end.

**A second trap, recorded here because this project has paid for it before.** The raw arm is
deterministic given the card: the same bars produce the same candidate list every time. Re-running
it is not a second draw. The gates are *not* deterministic — a model rating is a sample, and the same
ticker on the same day can rate Buy once and Hold the next. Every reported gate figure is therefore
one draw from a distribution this study does not have the budget to characterise, which is the single
largest caveat on everything below.

## 3. Metrics

Reported per arm, computed by `app.backtest.metrics.compute` — the canonical implementation every
other part of this programme is scored on. Using anything else would make these arms incomparable
with every card in the record, which is the whole point of reusing it.

- `total_return`, `max_drawdown`, `win_rate`, `exposure`, `trades`
- `realized_vol` — **non-annualised** daily-return standard deviation
- `adjusted_excess`, `excess_per_exposure`
- `live_fill_fraction` — the share of fills priced from a live quote rather than a stored open

**Annualised statistics are not reported and must not be quoted.** `metrics.compute` returns `None`
for CAGR, Sharpe, Sortino and annualised volatility under one year of elapsed data, by design. A
months-long study has no business annualising, and the codebase's refusal to do it is a feature this
study accepts rather than works around. "Lower volatility" in the owner's question is answered by
`realized_vol` and `max_drawdown`, not by a Sharpe ratio.

**Research cost is charged to the arm that incurred it.** A workflow run costs $12–20/day in model
calls at default settings. An arm that beats the raw signal by less than its own research bill has
not beaten it. Each arm reports `research_cost_usd` and a `net_adjusted_excess` with that cost
subtracted from the book. This is not a rounding detail: on a $100k book, $15/day compounds to
roughly 3.8% of starting equity a year, which is larger than most edges this programme has ever
measured.

## 4. The discrimination test — the powered instrument

The equity-curve comparison answers the owner's question in its own terms and will almost certainly
be inconclusive on a few months of data. The test that can actually reach significance asks the same
question one level down, where the sample is candidates rather than days:

> Conditional on a candidate firing, does the gate's pass/fail predict its forward return?

For every candidate the raw arm ever staged, record the gate's decision and the realized forward
return at a fixed horizon (**h = 21 sessions**, matching `app.tradingagents.memory`'s
`_HOLDING_DAYS`, so these observations are commensurable with the decision log the TA desk already
keeps). Then compare the passed set against the refused set.

- Statistic: mean forward return of passed minus refused, and the hit-rate difference.
- `binomial_p_value` and `benjamini_hochberg` from `app.backtest.scan` — the canonical pair, reused
  unchanged so the multiple-testing tax is the same one every other round paid.
- Overlapping windows are handled with `app.discovery.stats.stationary_bootstrap_p` (seeded,
  deterministic), because daily candidates at a 21-session horizon overlap heavily and a t-test
  over-rejects on exactly that shape.
- Three gates tested → `m = 3` in the BH denominator. Untestable gates keep their slot rather than
  being dropped, per `scan.py`'s contract.

**A gate that refuses candidates which then outperform is worse than no gate**, and this test is the
only one in the study that can say so cleanly.

## 5. Controls and nulls

- **Engine-honesty control.** Before any arm is scored, the raw arm is replayed through both
  `app.workflow.replay.run_decision_log` and the programme's `app.tournament.runner.run_card` on a
  shared window and must agree. This is `r15_control.py`'s two-path check: prove the new bridge is
  honest before scoring anything through it. It ships as a test, not as a paragraph.
- **Circular-shift null on the gate.** Following `round21_null.py`: shift which candidate-days the
  gate passes, preserving both the pass rate and its run-length structure, 200 replicates. Report the
  treated-only interval as governing — replicates that happen to apply no treatment create a point
  mass at zero that flatters the all-replicate interval.
- **Verdict compliance.** The share of Vibe runs that emitted a parseable `VERDICT:` line. A
  non-compliant run defaults to `INCONCLUSIVE`, which means "no trade"; if compliance is low, the
  `vibe_gated` arm is measuring abstention rather than judgement and must be reported that way.
- **Attribution.** Per-trade `contribution = pnl / starting_equity` (`attribution.py`'s exact,
  non-apportioned method) so the report can say whether a gate changed *which* trades happened or
  merely their size.

## 6. Predictions (falsifiable, fixed before the run)

1. **All three gated arms show lower `exposure` and lower `realized_vol` than `raw_signal`.** This is
   near-mechanical and is therefore *not* evidence of skill; it is stated so that its absence would
   be surprising and would indicate a bug in the gating.
2. **No arm's `adjusted_excess` differs from `raw_signal` at the pre-registered threshold** over the
   first study window. The programme's own record — 18 consolidated rounds finding no durable edge,
   1 positive cell in 9,480 — is the base rate, and nothing about adding a language model to a
   filter changes the prior. *Refuted if* any arm clears §7.
3. **The discrimination test (§4) is the only test that comes near significance**, in either
   direction.
4. **`net_adjusted_excess` is negative for every gated arm** once research cost is charged, even if
   gross is positive. *Refuted if* any arm's edge exceeds its own model bill.

Prediction 2 predicts the study's own null. That is deliberate: a study whose author expects a
positive result is a study that will find one.

## 7. Decision rule (pre-registered)

The chained workflow is judged **effective**, and earns a further pre-registered round on a fresh
window, only if **BOTH**:

(a) `full_workflow`'s `adjusted_excess` exceeds `raw_signal`'s with a paired bootstrap p ≤ 0.10 on
daily return differences, **and**
(b) the §4 discrimination test shows the gate's passed set beating its refused set at q ≤ 0.10.

Both, because either alone has a benign explanation: (a) alone is consistent with the gate having
cut exposure into a falling market by luck, and (b) alone is consistent with a real signal too small
to survive costs and slippage.

- **Neither holds** → the chain is decoration on top of the strategy card, and the honest reporting
  is that the research did not change the outcome.
- **(b) but not (a)** → there is signal in the research that the execution path is not capturing.
  That is an execution finding, not a research finding, and the next round is about sizing.
- **(a) but not (b)** → most likely exposure luck; re-run on a fresh window before believing it.

**A minimum of 60 trading sessions and 40 gated candidates must accumulate before the decision rule
is evaluated at all.** Reading the arms before then is monitoring, not evidence, and any figure
quoted from that period must be labelled as such.

## 8. Determinism and honesty about scope

Fixed seed for every bootstrap. The raw arm is deterministic; the gates are not (§2). Fills follow
the engine's existing rules — decide at close N, fill at open N+1, adverse slippage always against
the book, sell-side fees only.

**What this study cannot settle:**

- **Power.** A few months of daily decisions on a ≤12-ticker universe is a low-power design. This is
  a directional study leaning on its paired structure, and it is not capable of detecting a small
  true edge. It can detect a large one, and it can detect harm.
- **One model draw per decision.** No arm is re-run, so gate variance is unmeasured (§2).
- **Tax realism.** Wash sales are matched only within each arm's own book. Cross-account matching
  against a real brokerage portfolio is invisible *by construction* — the synthetic ledger
  has one account — so a paper-and-real overlap would under-report. There is also no $3,000
  capital-loss limitation, no carryforward, and no IRA permanent disallowance
  (`app.paper.papertax`'s own documented gaps).
- **Fill realism drifts with uptime.** A live-quote fill requires the app to be running near the
  open; a missed morning catches up off the stored open instead. The mix is reported
  (`live_fill_fraction`) rather than assumed away, and an arm whose mix differs materially from the
  others is not cleanly comparable.
- **Regime thresholds are judgements, not fitted values.** They are pre-registered here and changing
  them mid-study invalidates comparability across the window.
- **One card at a time.** The registry serialises workflow runs, so this measures one strategy's
  chain, not the roster's.

Nothing in this study is promotable to a live desk on its own. A positive result buys a second
pre-registered round on a fresh window, and nothing more.

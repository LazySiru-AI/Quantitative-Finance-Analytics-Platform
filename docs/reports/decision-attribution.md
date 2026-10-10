# Decision attribution: gate concordance and risk-panel flip rate

Two zero-model-cost measurements over the Agent Workflow's stored record. Both read data another
stage already wrote -- no new model call is made to produce either number.

Computed 2026-08-31 against the repository's real `data/agentdesk/` store (not a fixture), by loading
`app.config.Settings()` and calling `app.workflow.analysis.gate_concordance` and
`app.tradingagents.analysis.rating_flip_rate` directly. Both current sample sizes are 1. **Neither
number below supports any conclusion.** They are reported as a monitoring baseline -- proof the
measurement pipeline runs end to end and produces a real, correctly-shaped number -- not as evidence
of anything about gate agreement or risk-panel behaviour. Re-run once more workflow and Trading Agents
runs have accumulated.

## 1. Gate concordance: does the TA gate agree with the Vibe gate?

`app.workflow.analysis.gate_concordance` reads every logged candidate observation
(`app.workflow.candidates.read_observations`, the honest record of every candidate scanned and every
gate's ruling on it -- refusals included) and builds the TA-vs-Vibe 2x2 contingency table: how often
both gates passed a candidate, how often only TA passed, how often only Vibe passed, and how often
neither did. `full_workflow` is deliberately excluded from the table -- it is the conjunction of the
other two, so it carries no independent opinion to compare.

**Real result, n = 1:**

| cell | count |
|---|---|
| total candidates (both gates ruled) | 1 |
| both pass | 0 |
| TA only | 0 |
| Vibe only | 0 |
| neither | 1 |
| **agreement rate** | **1.0** (1/1) |
| disagreement count | 0 |

The one logged candidate (AMZN, 2026-08-28) was refused by both gates, so the two agreed on that one
ruling. An agreement rate of 1.0 over a single candidate is not a claim that the two gates will ever
agree again -- it is what one data point looks like. **n is far too small for inference**; the whole
disagreement side of the table (TA-only, Vibe-only) has never yet been observed to have a
denominator, so nothing can currently be said about how often the two gates actually diverge.

## 2. Risk-panel attribution: does the risk panel ever change the desk's decision?

**Why this measures the risk panel and not the bull/bear debate.** `AnalystReport` (the four analyst
stages) carries only `report_md` and a one-sentence `takeaway` -- no structured rating. Whether the
bull/bear debate "flips the analysts" is therefore not answerable from anything stored; answering it
would need a controlled ablation (the same evidence run with and without the debate, compared), not a
proxy classifier invented after the fact to squeeze a rating out of free text. That question is
explicitly out of scope for this measurement.

What *is* stored: `ResearchPlan.recommendation` (the research manager's call, made after the debate
but before the trader and risk panel ever see the name) and `DeskRun.final_rating` (the portfolio
manager's call, made after the risk panel has argued over the trader's proposal). The gap between
those two, both already persisted, is the risk panel's own attribution.

`app.tradingagents.analysis.rating_flip_rate` walks every stored `tradingagents` run
(`RunStore(settings, "tradingagents").list_runs(limit=1000)`), extracts the `research_manager` stage's
recommendation via the new `parse_recommendation`, and compares it against the run's persisted
`final_rating`. A run counts only when both halves are present: a `research_manager` stage with
non-empty rendered output, and a non-empty `final_rating` (i.e. the run actually reached and succeeded
past the portfolio manager). Every other run -- failed early, cancelled, still running -- is excluded
rather than padded with a default.

**Real result:** 10 stored `tradingagents` runs exist in total; only **1** has both halves of the
comparison (8 failed before the portfolio manager stage and carry no `final_rating`; 1 was cancelled).

| run_id | pre-risk (research manager) | post-risk (final_rating) | direction |
|---|---|---|---|
| `7045704d28074c93a6c43a066e374497` | Hold | Hold | unchanged |

| metric | value |
|---|---|
| total comparable runs | 1 |
| flipped | 0 |
| **flip rate** | **0.0** (0/1) |
| upgraded | 0 |
| downgraded | 0 |
| unchanged | 1 |

The one comparable run's risk panel left the call unchanged (Hold -> Hold). **n is far too small for
inference** -- a flip rate of 0.0 over one run says nothing about whether the risk panel changes the
desk's decision in general; it has not yet been observed doing so or not doing so more than once.

## Signature and prefix, for the orchestrator

```python
def parse_recommendation(text: str) -> str: ...
```

Targets the literal prefix `render_research_plan` writes as its first line:

```
**Recommendation: <tier>**
```

(tolerant of the surrounding `**`/`_` markdown emphasis and of a dash instead of a colon, mirroring
`app.workflow.verdict.parse_verdict`'s tolerance for the same reason). Falls back to the first
occurrence of any of the five `RATING_5TIER` words anywhere in the text, then defaults to `"Hold"` --
the same two-pass discipline and the same default `parse_rating` already uses.

## Deviations from the brief

None. Both modules are pure functions of already-read data (`gate_concordance` over a
`Sequence[CandidateObservation]`, `rating_flip_rate` over a `Sequence[DeskRun]`) rather than
settings-reading entry points -- the orchestrator (or this report) is expected to call
`app.workflow.candidates.read_observations` / `RunStore.list_runs` itself and hand the result in. This
was a design choice, not a deviation: it keeps the arithmetic testable against synthetic data with no
temp-directory fixture, and it means neither module re-parses `candidates.jsonl` or walks
`data/agentdesk/tradingagents/runs/` itself -- both re-use the existing readers exactly as instructed.

# Prompt compression comparison

**Status: template.** No live comparison has been run yet. This document is the protocol and an
empty results table; it is filled in by a human running `tools/compare_prompts.py --live` with a
stated budget, not by an agent.

## Why this exists

One real Trading Agents workflow run made 26 opus-5 calls and burned **97,547 output tokens** against
roughly 52 fresh input tokens per call. Output length is the cost driver, not input. A prompt-
compression change to `backend/app/tradingagents/prompts.py` (the fourteen-stage TA pipeline's system
prompts) or `backend/app/vibedesk/presets/followup_review.json` (the two-sided Vibe Trading review) is
only shippable if it provably does not change what the desks decide -- a shorter prompt that also
drops the reasoning that led to a correct call has made the system cheaper and worse.

## The harness

`tools/compare_prompts.py` runs a paired before/after comparison over one fixed `(symbol, trade_date)`
fixture:

- **Baseline side**: the prompts and preset as they existed at a chosen git ref (`--baseline-ref`,
  default `HEAD`), read via `git show <ref>:<path>` and monkeypatched in for the duration of that
  side's run only.
- **Candidate side**: the prompts and preset exactly as they sit in the working tree.

Both sides run the same two desks against the same fixture: the `app.tradingagents.pipeline` 14-stage
run, and the `followup_review` Vibe Trading preset via `app.vibedesk.runtime`.

**Baseline-selection mechanism implemented: `--baseline-ref` (git ref).** The two-prompt-module-path
alternative described in the task brief was not implemented; if a future change needs it (comparing
two uncommitted working copies, say), extend `load_baseline_prompts`/`load_baseline_preset` to accept
an explicit file path as well as a git ref.

**Determinism requirement.** `tools/compare_prompts.py:evidence_fingerprint` hashes the rendered
evidence pack both sides' debate/judge/trader/risk/portfolio stages share, for the fixed
`(symbol, trade_date)`. `main`'s live path computes this once and asserts it is stable before either
side runs a single model call; a `(symbol, trade_date)` pair without enough stored history to be
byte-identical between two builds of the same pack makes the whole comparison meaningless, so the run
aborts loudly (exit code 2) rather than reporting numbers over shifting ground.

## The four invariance conditions ("no information loss")

1. **Identical decisions.** The TA run's `final_rating`, the Vibe run's parsed `VERDICT:` line, and
   the pass/fail outcome of all four `app.workflow.pipeline.ALL_ARMS` gates
   (`raw_signal`, `ta_gated`, `vibe_gated`, `full_workflow`) must match exactly between baseline and
   candidate. Checked by `compare_sides` via `app.workflow.pipeline._passes_gate` itself -- never a
   reimplementation of that logic.
2. **Every decision-bearing field still present and semantically unchanged**, not merely shorter:
   rating, recommendation, entry/stop/sizing, investment thesis, falsification/invalidation text.
   This cannot be automated -- `compare_sides` emits `ComparisonReport.field_dump`, a side-by-side of
   every such field from both sides, for a human to actually read before signing off.
3. **`GroundingVerdict.ok` still true on the candidate side, with no new retries.** A compression
   change that trips the grounding gate is a regression even when the final answer still matches,
   because a retry re-sends the whole evidence pack and erases whatever tokens compression saved.
4. **`checked_tokens` does not collapse toward zero.** A compression change that strips the
   quantitative content out of a stage (rather than the padding around it) would pass condition 1 by
   accident and still be a loss -- the `--min-checked-token-ratio` floor (default `0.5`, i.e. the
   candidate must still cite at least half as many groundable figures as the baseline) catches that.

Conditions 1, 3 and 4 are automated in `compare_sides` and gate the script's exit code. Condition 2 is
never scored automatically; it is a human sign-off against the field dump.

## Running it

**Dry run (default -- zero model calls):**

```
.venv/Scripts/python.exe tools/compare_prompts.py --symbol AAPL --trade-date 2026-06-15 --baseline-ref HEAD
```

Prints the plan (fixture, both sides' prompt/preset sources, budget split, which conditions will be
checked) and exits 0 without touching either child desk service.

**Live (spends real money -- a human decision, never made by an agent):**

```
.venv/Scripts/python.exe tools/compare_prompts.py \
  --symbol AAPL --trade-date 2026-06-15 --baseline-ref HEAD \
  --live --budget-usd 8.00 \
  --out docs/reports/prompt-compression-run-2026-XX-XX.md
```

`--budget-usd` is the whole comparison's cap, split evenly across the two sides' two child desks
(baseline TA, baseline Vibe, candidate TA, candidate Vibe -- one quarter of the total each). Pick a
`--trade-date` with enough stored history that `evidence_fingerprint` is stable; if the run aborts
with an evidence-fingerprint mismatch, that is the harness refusing to report a meaningless comparison,
not a bug to route around.

Exit code: `0` if every automated condition passed, `1` if any of conditions 1/3/4 failed, `2` if the
evidence fingerprint itself was not stable.

## Results

_No live run has been recorded yet. Each completed comparison should append one row below and link its
full report (the file `--out` was pointed at)._

| Date | Symbol | Trade date | Baseline ref | Passed (1/3/4) | Output tokens saved | Cost saved | Full report | Human sign-off on condition 2 |
| ---- | ------ | ---------- | ------------- | --------------- | -------------------- | ----------- | ------------ | ------------------------------ |
| _(none yet)_ | | | | | | | | |

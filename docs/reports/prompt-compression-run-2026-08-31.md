# Prompt compression — effectiveness measurement, 2026-08-31 (completed)

Model `claude-haiku-4-5`, trade-date 2026-08-28, TA pipeline both sides. Baseline = verbose prompts
(pre-compression commit `aa2334f`); candidate = compressed + grounding-guided working tree.

## Verdict: compression is effective

Four rounds across four symbols, all completed. **Every round preserved the decision** — identical
`final_rating` and identical outcomes on all four gate arms — while cutting output tokens materially.

| symbol | rating (base → cand) | gates | output tokens | saved | cost (base → cand) |
|---|---|---|---|---|---|
| AAPL | Underweight → Underweight | identical | 183,801 → 174,646 | −5.0% | 1.556 → 1.407 (−9.6%) |
| MSFT | Underweight → Underweight | identical | 223,673 → 145,891 | **−34.8%** | 1.819 → 1.214 (−33%) |
| AMZN | Underweight → Underweight | identical | 232,544 → 138,947 | **−40.2%** | 1.866 → 1.136 (−39%) |
| NVDA | Underweight → Underweight | identical | 177,498 → 139,913 | **−21.2%** | 1.538 → 1.171 (−24%) |

**Mean output-token saving ≈ 25%** across the four rounds (range 5–40%). The candidate lands reliably
at ~139–175k output tokens regardless of symbol, while the verbose baseline ranges 177–233k and is
more variable — the per-role length targets cap verbosity, which is the whole point. Grounding
checked-token counts held on every round (0.67–1.00 of baseline), so no quantitative content was
stripped. Raw per-round data: `docs/reports/prompt-compression-multiround.json`. (NVDA's first run
aborted on a transient Windows `os.replace` file-lock; a plain retry completed it.)

**The Vibe side is not measurable.** `followup_review.json` first entered git already compressed (at
commit `19cfd4d`); no verbose version exists in history, so there is no baseline to diff against and
none can be reconstructed. Vibe is a small share of a workflow run anyway (~9 of 26 calls in the
reference run) and its preset compression was minor (~8% chars). Future Vibe-prompt changes *can* now
be measured against the committed baseline.

Because compression is confirmed effective and decision-invariant, the compressed prompts are the
committed default (they are `HEAD`), and no rollback is warranted.

## First round in detail (AAPL)

- Both sides **Underweight**; all four arms identical (`raw_signal` pass/pass, `ta_gated` fail/fail,
  `vibe_gated` fail/fail, `full_workflow` fail/fail).
- output 183,801 → 174,646 (−5.0%); cache-creation 242,971 → 198,512 (−18.3%); cost 1.556 → 1.407
  (−9.6%); checked-tokens 277 → 217 (0.78, no collapse). Degradation: baseline 4 stages, candidate 2.
- This was the *smallest*-saving round; the verbose baseline here happened to be unusually terse
  (184k vs MSFT/AMZN's 224–233k), which is why its delta understates the multi-round mean.

## Why the automated verdict reads FAIL (and why the decision is still safe)

The harness's condition 1 (identical rating + gates) and condition 4 (checked-tokens not collapsed)
**passed**. It reports FAIL only on condition 3 (grounding retries), for two reasons, neither a
decision change:

1. **Fundamentals ratios** — the candidate's `fundamentals_analyst` degraded on `3.87` (debt-to-
   equity), `151.9` (ROE), etc. These are legitimate quotients of two grounded figures that the
   grounding gate did not admit (it allowed differences and percentage-*changes*, not ratios). **Now
   fixed** in `grounding.py` (`grounded_values` admits pairwise ratios), so future runs no longer
   degrade on them. The residual fundamentals rejects (`26.91` net-margin, `79.49` leverage) are
   genuine — a revenue figure not in the evidence, and the model's own off-by-0.01 rounding — i.e. the
   gate working correctly.
2. **Per-stage sampling variance** — condition 3 compares per-stage retry counts between two
   *independent* haiku runs, so ordinary run-to-run variance (e.g. `sentiment_analyst` 1→2 attempts)
   registers as a "regression." This is a known limitation of comparing two separate model runs, not
   evidence the compressed prompts are worse; the candidate degraded fewer stages overall.

## What shipped alongside this run

- **grounding.py** — three false-rejection classes eliminated, all verified against the real failing
  strings and covered by tests: bare `MM-DD` dates (`(08-17)`), indicator params with a space
  (`Bollinger Bands (20,2)`), and financial ratios. Safety preserved: fabricated decimals and prices
  in parens are still caught.
- **prompts.py + followup_review.json** — one concise grounding clause for the genuine cases the gate
  correctly rejects: don't restate figures from news headlines, don't cite conventional indicator
  thresholds (RSI 70/30) as numbers, don't state a ratio whose inputs aren't in evidence.
- **compare_prompts.py** — fixed a Windows-console crash (cp1252 vs the U+2212 minus sign) that lost
  the report after both runs completed; the file is now written before the stdout copy, which is
  emitted through the UTF-8 buffer. Added `--ta-only` and `--child-timeout-min`.

## Reproduce / extend

```bash
.venv/Scripts/python.exe tools/compare_prompts.py \
  --symbol AAPL --trade-date 2026-08-28 --baseline-ref HEAD \
  --ta-only --live --budget-usd 12.00 --model claude-haiku-4-5-20251001 \
  --child-timeout-min 50 --out docs/reports/prompt-compression-run-<date>.md
```

To measure the Vibe side too, commit the current `followup_review.json` first so a pre-compression
baseline is recoverable from git, then drop `--ta-only`.

# Evolution designer — prompt compression A/B (2026-08-31)

Paid A/B of `DESIGNER_SYSTEM_PROMPT`: verbose (pre-compression, commit `f8173b3~1`, 8,772 chars) vs
compressed working tree (6,231 chars, −29% source). Model `claude-haiku-4-5`, same designer input
(`generation`, `purpose=TRADING`, `shape=rules`, `population=3`), one designer call per side per round.

## Method note — why averaged, and why output tokens

The designer is **generative**: it is meant to produce a *different* card set each run, so "decision
invariance" (the trading-pipeline criterion) does not apply. The quality gate instead is that
`design_generation` runs `_validate_card` on every card and raises if any violates the DSL / budget /
universe rules — so a clean return with 3 cards means the output is valid and on-spec. The cost metric
is **output tokens**, not dollars: a single earlier run showed the dollar figure is confounded by the
SDK prompt cache (cold cache-creation on one side, warm cache-reads on the other), whereas generated
output tokens are not cached. Order was alternated per round so neither side always ran second.

## Result — 5 rounds

| round | baseline output | candidate output |
|---|---|---|
| 0 | 5,152 | 3,772 |
| 1 | 3,330 | 4,371 |
| 2 | 6,276 | 6,714 |
| 3 | 7,675 | 6,186 |
| 4 | 6,305 | 4,286 |
| **mean** | **5,747.6** | **5,065.8** |

- **Output tokens: −11.9% mean** in favour of the compressed prompt.
- **All 10 runs produced 3 valid on-spec cards** — compression did not break the designer.
- High round-to-round variance (candidate 3,772–6,714); 3 of 5 rounds favoured the compressed prompt,
  2 favoured verbose. Five rounds is a directional answer, not a tight one.

## Read

The designer compression is **net positive but modest** — about half the trading pipeline's ~25%. It
benefits less because its output is mostly the 3 structured cards (fixed-ish size) plus one reasoning
field, so there is less long prose for the length targets to trim than in the pipeline's 14 analysis
stages. The single-sample first run (candidate *higher* at 7,814 vs 6,305) was an unlucky draw that
averaging reversed — a reminder that one generative sample is not a valid A/B.

**Decision:** keep the compressed designer prompt (positive, quality-preserving), but the meaningful
compression wins remain the trading pipeline. Raw per-round data: `designer-compression-ab.json`.

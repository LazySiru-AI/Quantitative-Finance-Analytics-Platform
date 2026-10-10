# The definitions pass

**1756 Python tests pass** (up from 1748), 1 skipped. 36 frontend tests pass. `ruff` clean,
`mypy --strict` clean across 105 source files, `tsc` and `vite build` clean.

The item a UAT persona put at the top of what it would need before routing a real book through this
application: *"a definitions pass on every headline statistic — not just the ones a persona
stumbles on."*

## Why it was the right item

Four defects in run 2 were one shape: **a number computed correctly, under a label that meant
something else.** The persona checked the arithmetic in session 3 and it held to the cent. Every
unit test passed throughout — because every test asserted the *computation* and none asserted the
*claim*.

That class does not surface from testing harder. It surfaces from reading every label against the
code behind it, once, deliberately.

## What the pass found

Five mismatches nobody had reported, in the surfaces a persona had not happened to open.

### The sample size was overstated seven-fold on any non-daily report

`sample.bars` was labelled **"Sessions"** regardless of interval. A report built at `1h` counted
hourly bars and called them sessions:

```
1h  ->  'Sessions'  = 3485      # ~485 actual sessions
```

The one figure a reader uses to decide whether to believe everything below it. Now interval-aware —
`Sessions` on daily, `1h bars` otherwise, with `First bar` / `Last bar` following suit.

### A trade count labelled "closed" that included open trades

`StrategyMetrics.trades` counts every trade the strategy *opened*. It was rendered **"Trades
(closed)"** directly above **"Open at end"**, so the two invited being added — counting the open
trade twice — and it disagreed with the win rate below, which genuinely is over closed trades only.

Now `Trades opened` and `…of which still open`, which says the second is a subset rather than an
addition. The field had no docstring at all; it has one now, stating that it does not share a
denominator with `win_rate`.

### "Edge" was a difference in hit rates, rendered as a signed percent

`Evidence.edge` is hit rate minus baseline hit rate — percentage points of *how often*. Under the
bare label **"Edge"** at `SIGNED_PERCENT`, `+0.12` read as twelve percent of excess return rather
than twelve points more often. The decision table already called this exact quantity **"Hit rate vs
baseline"**; the fact bundle now uses the same words, so the two surfaces cannot be read as two
different statistics.

### A rule name under a label naming a percentage

`rules.best_rule` was labelled **"Largest measured edge"** and carried the rule's *name*. In a fact
table that renders as `Largest measured edge | close > sma(200)`. Now "Rule with the largest edge".

### Two smaller ones

`rules.best_horizon` was **"Horizon"** as a bare count — bars, not days, now said. `strategy.win_rate`
was **"Win rate"**, where the frontend had long said "Win rate (closed trades)"; the bundle matches.

## R2-9, closed by the same pass

The last open finding from run 2: the Scan page names Benjamini–Hochberg while the decision table
graded every rule *insufficient* with no test or threshold beside it — so the grade read as an
opinion rather than a rule a reader could check a row against.

`DecisionTable` now carries a `criteria` block built from the constants in `app.rules.evidence`, and
the table renders a legend from it. **The numbers travel from the backend** rather than being
restated in a component: a legend hard-coded in the UI would be wrong the first time a threshold
moved, which is the same drift this whole exercise is about.

Rendered live:

> *suggestive* — at least 30 independent triggers **and** a hit rate at least 8 points away from the
> baseline. *weak* — at least 8 independent triggers **and** at least 15 points away. *insufficient*
> — everything else. The honest default, and the expected answer for most rules on most instruments.

## What makes it a pass rather than five more fixes

**`docs/DEFINITIONS.md`** — the register. One row per statistic a user reads without drilling in:
what the label claims, what the code computes, and where. Forty-odd rows across sample, drawdown,
rule evidence, strategy, portfolio, cash, tax and macro, plus the six standing rules they encode.

**`tests/test_definitions.py`** (8 cases) — what a machine can check about it:

- every fact the report bundle can emit appears in the register, matched on the **label**, so a
  label changed without the register following it fails;
- the exemption list for genuinely self-defining facts (`Symbol`, `Currency`) contains no stale
  entries, so it cannot quietly become a place to hide new statistics;
- the specific mismatches above stay fixed;
- the register quotes the significance thresholds the code actually ships, so moving one fails here.

The fact ids come from **building a real bundle with every engine present**, not from a regex over
the builder: a fact added inside a branch a regex missed is exactly the fact most likely to be
undocumented. Proven by relabelling `strategy.cost_drag` and watching the suite fail.

**What this cannot check** is whether a definition is *correct* — a label reading "Current drawdown"
against a register entry reading "peak to trough" would satisfy every assertion. It catches the case
that actually happened: a statistic reaching a user with no stated definition at all, because the
person adding it knew what it meant and had no reason to write it down.

## Still open from run 2

**R2-10** — the `derived_build` badge reports a table this application never writes, because every
derived figure is rebuilt per request. "Not built" is permanently true, permanently irrelevant, and
sits next to correct figures. The fix is a decision about whether that table has a future.

**R2-11** — `backtest-event-study-no-technical-indicators`, unverified, carried.

And the persona's remaining three conditions, unchanged: an as-of-correct market feed, ticker search
re-tested outside synthetic clicks (it works — see the harness note in the backlog), and a cycle
against real multi-broker exports rather than the sandbox's clean one.

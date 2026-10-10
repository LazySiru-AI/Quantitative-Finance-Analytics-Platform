# Defect round 1 — the carried-forward backlog, and what attacking it turned up

Not a phase. This round closed the four limitations Phases 5–9 recorded and left, then ran two
adversarial sweeps over the finished code and fixed what they found.

1425 tests pass (up from 1378), 1 skipped — `vwap_reclaim is not defined on daily bars`, pre-existing
and untouched. `ruff` clean, `mypy --strict` clean across 92 source files, frontend typechecks and
builds.

## The theme, stated first

**Every serious defect this round was a claim that outran its code.** A docstring describing a layer
that did not exist. A comment reasoning correctly about a failure and then fixing it at one call site
instead of on the type. A verdict meaning "confirmed out-of-sample" attached to records that were
never tested out-of-sample. A cache constructed, threaded through two layers, and deleted. In every
case the code read as though the work had been done, and the reading is what made it survive review —
including mine.

Three of the five were mine.

## The four carried-forward items

**The 200px sidebar.** Recorded in phase-6, re-measured in phase-8 at 182px and 199px of overflow on
a 375px viewport, never fixed. Below 860px the shell is now a column and the sidebar a horizontal bar
with its own `overflow-x: auto` — the containment pattern `.table-wrap` already used, so wide content
still scrolls in its own box rather than the page body. Verified independently of the worker that
built it: **all 21 measurements zero** (seven routes × 375/768/1280px), and at 1280px the shell still
computes `flex-direction: row` with the sidebar at exactly `200px`, so the desktop target is provably
unchanged rather than apparently unchanged.

**The indicator cache.** `evaluate()` now takes an optional caller-owned `IndicatorCache`.
Request-scoped and caller-owned is what answers the objection `rules/service.py` had recorded: no
global mutable state, so the FastAPI thread-pool hazard that ruled out monkeypatching the registry
does not apply. Measured through the production entry point, three expressions sharing `rsi:14`
compute it **once** where they previously computed it **three** times.

The correctness hazard mattered more than the speedup and was briefed that way: a cache reused across
different bars returns *plausible* wrong numbers into a statistical engine, which is a far worse
defect than the one being fixed. It carries a bars fingerprint and raises rather than serving stale
values.

**The tax rate.** `SHORT_TERM_TAX_RATE = 0.37` was hardcoded with an honest comment and no config
path, so the after-tax figure was a top-bracket upper bound that reached the UI looking like a
computed cost. Rates are now configurable, validated to `[0.0, 1.0]` — a 37-versus-0.37 mixup
multiplies the drag by a hundred — and `TaxImpact` carries the basis and both applied rates, so the
number is self-describing and the UI cannot present an upper bound as the user's own figure.

**`ira_exposure`.** Was `bool = False`. The module comment explained that this package is walled off
from `data/` and cannot know — but `False` is not "I don't know", it is a positive claim that the
user has no IRA exposure. Now tri-state, rendering "not checked".

## What the sweeps found

### A thesis could be reported as confirmed without ever being tested

The most serious finding, and it sits inside the machinery whose entire purpose is refusing to report
findings.

`run` keeps iterating after it finds an in-sample candidate, and `survivor is None` captures only the
first. After the loop, only that one is holdout-tested and only that one record is replaced. Any
later thesis that also cleared the screen kept `verdict = SURVIVED`, `status = IN_SAMPLE_TESTED` and
`holdout = None` — permanently. Reproduced:

```
outcome            : catalogue_exhausted
survivors reported : 4

  dd3f8a3a71  verdict=inconclusive  status=holdout_tested     holdout_tested=True
  c645d4bd44  verdict=survived      status=in_sample_tested   holdout_tested=False
  fe329cb5c2  verdict=survived      status=in_sample_tested   holdout_tested=False
  c15b104b82  verdict=survived      status=in_sample_tested   holdout_tested=False
  c51a0ddbe7  verdict=survived      status=in_sample_tested   holdout_tested=False
```

Two things wrong at once. Four theses reported as survivors on in-sample evidence alone. And the run
outcome and the survivor list **contradict each other** — `catalogue_exhausted` means nothing
survived, while `survivors` returns four. The one thesis that actually spent the holdout was refuted.

Since a ticker gets exactly one holdout evaluation ever, at most one thesis per run can legitimately
reach `SURVIVED`. Later screen-passers are now downgraded to `INCONCLUSIVE` before they are
persisted, with the ledger updated to match so no stale `survived` row outlives the run — the honest
reading, and precisely what `_confirm`'s own docstring says that verdict means. A second instance of
the same shape was found and fixed on the `HoldoutBurned` path.

**And the illegal state is now unconstructable.** `LoopResult` carries two validators: no record may
be `SURVIVED` with no holdout, and `outcome is SURVIVOR_FOUND` if and only if `survivors` is
non-empty. Following `ScanResult`'s trials check — an invariant enforced by the type rather than by
the producer staying correct.

Worth recording: the **first** attempt to reproduce this failed, because the Benjamini–Hochberg
correction downgraded all five forced survivors to `INCONCLUSIVE`. That gate is load-bearing. Worth
recording equally: reaching the state required forcing the screen, so what is proven is the plumbing,
not that real data arrives there. It is plausible that it does — the catalogue's templates are
correlated by construction, so a ticker where a 200-day SMA rule clears the threshold is one where
the 50/200 EMA cross plausibly does too. The guarantee has to hold structurally, not because the
inputs are usually kind.

### An entire feature was built, tested, and unreachable

There is exactly one `LoopResult(...)` construction in the codebase and it hardcodes `cards=[]`.
`POST /run` returned that object directly, and none of the four thesis routes built a card. So
`result.cards` was always empty, `ThesisCard` could never render, and a `survivor_found` run would
have announced *"0 theses survived"* underneath a heading saying one did. `strategycard.py`,
`debate.py`, `ThesisCard.tsx` and 24 passing tests were complete, correct and disconnected.

The wiring goes through a `CardBuilder` Protocol with a lazy default, the same seam the router
already used for `LoopRunner`, so the no-`strategycard`-import boundary is preserved rather than
punched through — that rule exists so tests can hand back a fake `LoopResult` without driving real
bars through real SQLite. A failed card build becomes a warning, not a 500.

**How it survived.** Phase 9's QA found `LoopResult.survivors` filtering `cards` and returning `[]`
on every run. I fixed the property to derive from `records` and wrote in its docstring that *"`cards`
is populated by a later layer than the loop"* — as the explanation for the bug. I never checked that
the later layer existed. It did not, and the router is explicitly forbidden from being it. I fixed
the symptom, documented an assumption as a fact, and the fix hid the cause.

### Annualised risk metrics had no sample floor

`metrics.py` opens by stating that a number a caller could mistake for a stronger claim than the
sample supports is not computed, and `_cagr` honoured it. `_sharpe`, `_sortino` and `_volatility`
required two data points and then multiplied by `sqrt(252)`:

| sample | CAGR | Sharpe |
|---|---|---|
| 6 bars (5 trading days) | `None` | **5.02** |
| 3 bars (2 trading days) | `None` | **11.22** |

All three now share `_cagr`'s one-year gate. One threshold, stated once, applied to every figure
whose units are "per year".

This one also caught a test that would have started passing for the wrong reason: `TestSortinoNoLosses`
ran on 30 bars, and under the new floor it would still have asserted `sortino is None` — because of
the sample gate, not because no bar lost money. The test's name would have kept claiming something
the test no longer checked. Extended to 253 bars, it tests the no-losses branch again.

### A commission could manufacture a profit

`Costs.notional` had no constraint. On a flat series with a $50 commission:

| notional | total return | |
|---|---|---|
| 10,000 | −0.009975 | correct drag |
| 0 | 0.0 | the commission silently vanishes |
| −10,000 | **+0.010025** | a commission manufactures a positive return |

The `gt=0` lived on the API request schema only, with a comment showing the author had reasoned about
this exact failure and fixed it at one call site instead of on the type. The invariant now travels
with the model, and `commission_per_trade` and `slippage_bps` are `ge=0` on the same logic: a
negative cost is an unearned rebate, not a smaller cost.

This is mine. Phase 8 promoted `notional` from a module constant to a declared field *specifically*
so the number would not be invisible to the reader, and shipped it unconstrained.

### The citation contract held where it claims to, and leaked where it did not

The headline claim survived attack: malformed references, unknown fact ids, bare digits smuggled
beside a valid citation, and non-ASCII decimal digits were all refused. Four gaps got through.

The sharpest: `verify()` checks that a fact id *resolves*, never that the prose's caption matches its
meaning, so `"a Sharpe ratio of {{fact:rules.best_edge}}"` verified as grounded and rendered as *"a
Sharpe ratio of 3.6%"* — a real number with an invented meaning. The fix is a rendering change rather
than an attempt to parse prose: untrusted drafts now render the fact's own label beside its value, so
a mislabeled citation contradicts itself where a reader can see it. Digit detection widened from
category `Nd` to `Nd`/`Nl`/`No`, catching Roman numerals, circled digits, fractions and superscripts —
matching the rationale the module already stated. Full-width brace lookalikes, which bypassed both
detectors and reached rendered output, are now folded.

**One was declined deliberately.** Hedges wrapped around a valid reference — "at least
{{fact:x}}", "{{fact:x}} and rising" — still pass. A deny-list catching three phrasings is walked
around with "no less than" or "so far", and a checker that catches a handful of infinite phrasings
manufactures exactly the confidence this module refuses to manufacture. The gap is documented and
pinned with a test asserting the three known hedges still verify, so it is recorded rather than
assumed closed.

### Enum drift, from a Phase 9 fix

`CATALOGUE_EXHAUSTED` was added in Phase 9 as the *fix* for a QA defect — distinguishing "the author
had five ideas" from "nothing survived twelve attempts". The TypeScript union kept four values, with
a comment reading *"All four are reportable outcomes"*, so the most common outcome rendered a blank
headline. `outcomeLabel()` was worse: no `default` branch, so an incomplete union compiled clean and
returned `undefined` at runtime. `tsconfig.json` has `strict: true` but not `noImplicitReturns`,
which is why.

Fixed, and made structurally catchable: `assertNever` guards on all three switches, so the next
backend enum member breaks `tsc` instead of blanking the UI.

## A process note on parallelism

Seven Sonnet workers on file-disjoint shards, Opus orchestrating. Two things are worth recording.

**The sharding had a real bug.** `backtest/scan.py` was fenced to one worker without noticing that
`scan.py` is *injected* into `backtest/service.py` as a Protocol collaborator, so widening its
signature broke a file nobody owned. It surfaced because a different worker refused to claim a clean
`mypy` when it saw a failure outside its own files, and isolated its three files to prove the error
was not its. That refusal is what made the break visible.

**A worker's stated reasoning is worth checking even when its conclusion is right.** The card-wiring
worker justified building survivor-only cards by saying the loop "returns immediately once one
survivor's holdout confirms". It does not — it runs the full catalogue and spends the holdout after
the loop ends. The conclusion was still correct and the guard-2 reasoning was sound. But reading the
loop to check the stated mechanism is what surfaced the four phantom survivors, which was the most
serious finding of the round.

## Also fixed without being asked

`build_event_study` had the same shape as `build_scan` — one `event_study` call over every cleared
condition, no shared cache — and was fixed for consistency. `reverse_conditioning` was checked and
deliberately left alone: it never touches the evaluator seam, handing every indicator spec to a
single batched `registry.compute`, so it already has the compute-once property and a parameter there
would be decoration.

## Still open

- **`POST /api/tax/reconcile` has no frontend consumer.** Not a defect — an endpoint with no UI. The
  only route in the audited surface with zero consumption.
- **The hedged-citation gap**, above: declined on purpose, documented, pinned by test.
- **`report.ts`'s local `Quote` interface** is a loosely-typed hand-rolled subset of the backend
  model, with a nullable `price` where the backend field is required. No wrong rendering was
  constructible from it; noted as a soft spot.
- **No Phase 9 UI artifact.** Phases 7 and 8 each got one; Phase 9's report exists only as markdown.

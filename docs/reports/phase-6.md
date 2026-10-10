# Phase 6 — Rule DSL, catalog and decision table

Commit `98dfc0f`. 1012 tests pass, `ruff` and `mypy --strict` clean across 63 files, frontend
typechecks and builds. Verified live against 6,897 stored QQQ sessions (1999-03-10 → 2026-08-10).

## What shipped

A closed expression language over indicator columns, a catalog of 12 named rules, and a per-ticker
decision table showing what each rule is doing now and what has historically followed it.

```
close < bb_lower(20,2) and rsi(14) < 30
ema(50) crosses_above ema(200)
close crosses_above vwap(2026-01-15)
```

Three endpoints: `GET /api/rules/catalog`, `GET /api/rules/decisions`, and `POST /api/rules/validate`
— the last cheap enough to call on keystrokes, returning `200` with `valid: false` for a malformed
expression, because "no, here is why" is a successful answer to "is this valid yet?".

## The language

**No `eval`, `exec` or `compile` anywhere in the package**, and a test greps the parser's own source
so the guard survives a refactor. A rule is a string the user types and the app stores; handing it to
the interpreter would share an execution context with the process holding the brokerage ledger.
Hand-written tokenizer plus recursive descent; function names resolve against the indicator registry
rather than any Python namespace; recursion depth is capped so 500 nested parens raise a syntax error
rather than `RecursionError`.

**Numeric and boolean expressions are distinct types.** `rsi(14) and close` is a parse error, not a
silently truthy series. A DSL that lets a number stand in for a condition eventually evaluates
`close` as "close != 0" — true on every bar of every instrument ever traded.

**`adj_close` is not referenceable.** It is dividend-adjusted, so its whole history shifts on every
payout: a rule written against it would quietly mean something different tomorrow than today, and a
trigger date recorded last month would no longer reproduce.

**A cross is an edge, not a level.** `a crosses_above b` is true only on the bar the relationship
changed. Written as `a > b` it would be true for the duration of the trend, turning one event into
hundreds of duplicate triggers. On real history the golden cross yields 14 triggers, 14 of them
independent — the shape you expect from a genuine edge.

Adversarial probing rejected all of: type mixing, a bare numeric expression, trailing operators,
`<<`, unknown indicators, `adj_close`, 500 nested parens, empty and whitespace-only input,
`__import__("os").system(...)`, and a `;` statement separator — each with a character position.

## The evidence, and what makes it honest

Four properties are structural rather than advisory, and each has a test that fails if it regresses.

**A hit rate without its base rate is not evidence.** "58% of triggers were followed by a gain" means
nothing until you know the instrument rose on 56% of all bars. Every `Evidence` carries the baseline
over the same sample, and the UI gives the *difference* the emphasis.

**The signal bar is not tradeable.** A rule evaluated on bar `t` uses that bar's close, known only
once the session ended, so forward returns run from the open of `t+1`. This is the commonest way a
backtest invents an edge and it is invisible — the numbers simply come out better. The regression
test constructs a move happening entirely on the signal bar: next-open entry measures exactly `0.0`,
same-close measures `−9.1%`.

**Overlapping windows are not independent observations.** Triggers three bars apart with a 20-bar
horizon share 17 bars of one price path. 100 consecutive triggers collapse to 5 independent ones.
Significance rests on that count, is deliberately coarse, and exposes **no p-value** — these rules are
chosen by a human looking at the same history they are then scored against, and a table of twelve
rules is twelve simultaneous tests with no correction. The FDR accounting that would justify a
sharper claim is Phase 7.

**"Did not trigger" and "could not be evaluated" are different.** Through an indicator's warmup a rule
has no truth value; folding that into `False` pads the denominator with bars it was never given a
chance to fire on. Carried as pandas' nullable boolean with Kleene semantics — `NA and False` is
`False` while `NA and True` is `NA`. Getting the first wrong would have been a silent denominator bug.

### What the falsification tests measured

- A rule firing on **random** bars: edge `0.0149`, verdict `INSUFFICIENT`. A rule with no information
  does not look informative.
- Warmup exclusion: `baseline_hit_rate` comes out exactly `0.0` where miscounting warmup as quiet
  days would have produced `0.78`.
- On 6,897 QQQ sessions **every catalogued rule reports `INSUFFICIENT`**, and `rsi_oversold` shows a
  *negative* edge (−3.6 points at 20 bars) — visible only because the baseline travels with it.

## The contract bug I introduced, found by an agent

`IndicatorRef.args` was typed `tuple[float, ...]`. That cannot hold `vwap`'s anchor — a `session`
token or an ISO date — which is `vwap`'s *only* parameter. The DSL therefore could not reach a
shipped indicator at all, including the arbitrary-date anchor the plan calls for. My own brief used
`vwap(session)` as an example the contract could not express.

The parser agent refused to smuggle a string into the float slot and raised a clear error instead,
which is the right call. Fixed by widening to `float | str`, with a `DATE` token ahead of `NUMBER` so
`2026-01-15` does not lex as arithmetic and quietly evaluate to `2010`. Ordinary subtraction is
unaffected and a date used as a value is refused.

## A layout defect worth recording

The decision table sets `min-width: 900px` inside an `overflow-x: auto` wrapper — correct. But
`.content` is a flex item carrying the default `min-width: auto`, so it refused to shrink below its
content's intrinsic width and the inner scroller never engaged.

Chrome additionally counted the wide `display: table` element in the *document* scroll area despite
correct clipping, giving the page ~790px of horizontal scroll into blank space. `elementFromPoint`
out there returned only `html`, confirming nothing was hidden — the symptom is scrolling into
emptiness rather than lost content, which is exactly why it is easy to miss. Fixed with
`min-width: 0` on the column and `contain: paint` on the wrapper; measured 882px → 91px, the
remainder being pre-existing shell overflow that the 200px fixed sidebar causes on every page.

## Known limitation — since fixed, see `docs/reports/defects-1.md`

Indicator computation is shared across rules that render identically, but not *across different rule
trees*: `rsi:14` is resolved separately for `rsi_oversold` and `rsi_overbought`. `evaluate()`'s fixed
signature has no cache hook, and the alternative — monkeypatching the registry for the request's
duration — is unsafe in sync FastAPI handlers dispatched to a thread pool. Documented in
`service.py`. Not currently a problem at 6,897 bars × 12 rules; worth revisiting if the catalog grows
or the backtest workbench reuses this path.

**Resolved.** `evaluate()` now takes an optional, caller-owned `IndicatorCache`. Request-scoped and
owned by the caller means no global mutable state, which is what answers the thread-pool objection
that ruled out monkeypatching the registry. The workbench did reuse this path, exactly as predicted.

## Carried forward to Phase 7

The decision table deliberately stops short of a significance claim. Phase 7 owns the FDR accounting,
the lookahead guards at scan scale, and the reverse-conditioning machinery — and it should be built
on the corrected RSI/ATR values from Phase 5, not the pre-fix ones.

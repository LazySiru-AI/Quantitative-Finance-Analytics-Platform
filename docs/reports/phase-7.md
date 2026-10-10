# Phase 7 — Backtest workbench

Commit `83d4fb5`. 1162 tests pass (up from 1012), `ruff` and `mypy --strict` clean across 73 files,
frontend typechecks and builds. Verified live against 4,129 stored SOXL sessions and 6,897 QQQ.

## What shipped

Four studies, ordered by how much each can mislead you.

- **Drawdown profile** — every material decline for one instrument, on a declared basis. Purely
  descriptive: no hypothesis, no baseline, nothing to correct for. The only study here that can be
  read at face value.
- **Forward-return event study** — a condition's trigger dates and what followed at +1/+5/+10/+20/+60
  bars, always against the same instrument's unconditional baseline. Conditions compose, and a second
  arm renders a delta.
- **Scan** — many conditions at once, with a visible trial counter and Benjamini–Hochberg correction.
- **Reverse conditioning** — select the biggest forward moves, profile what preceded them.
  Exploratory by construction, and typed so it cannot be rendered as a result.

Five endpoints under `/api/backtest`, and a `Backtest` page whose four panels fetch independently so
one failure degrades a section rather than blanking the page.

## The guard, and the mistake it was one line away from

An indicator is causal exactly when its value at bar `t` does not depend on any bar after `t`. So
compute it on the whole series, recompute on the leading slice `bars[:k]`, and compare every position
before the cut.

**Truncating the tail rather than the head is the entire trick.** My own brief to the build agent
worried at length that recursive indicators — Wilder-smoothed RSI and ATR, EMA, MACD — are causal but
not prefix-invariant, and asked for a defensible tolerance. That worry is only true if you chop the
*head*, which moves the seed. I measured it: an `ema(50)` restarted 100 bars late differs from the
full-series one by **1.83 price points** on QQQ. A head-truncation guard would therefore flag every
recursive indicator in the registry, and the only way to quiet it would be a tolerance wide enough to
hide a genuine violation.

Chopping the tail preserves the seed and asks precisely the question causality is about. Because the
seed is preserved the comparison is **exact** — no tolerance, no epsilon to justify. That was
verified rather than assumed: `sma`, `ema`, `macd`, `rsi`, `bb` and `atr` all reproduce
bit-identically across four cut points on 600 real QQQ sessions.

**Fails closed.** Every AST node type must be on an explicit allowlist by identity; an unrecognised
type is rejected by name. The mechanism that makes this survive a refactor is a test comparing the
allowlist against `nodes.__all__` — add a `Shift` or `Lead` node to the AST without teaching the
guard, and the guard's own suite fails rather than the guard silently permitting a construct nobody
reasoned about.

**Proven to catch things.** Four deliberately non-causal indicators were injected and each was
caught: a centered rolling window, a whole-series `max()` normalisation, a `bfill`, and a forward
shift. Without these the suite would only establish that legitimate rules are not molested, which is
also true of no guard at all.

What it does *not* prove is stated in a finding on every passing report: that the rule is causal over
the bars it was given says nothing about whether those bars are point-in-time. A retroactively
revised close is outside what any AST check can see; the run card's data fingerprint is what makes
that visible.

## Multiple testing

`ScanResult` refuses to construct unless `trials == len(entries)`. Reporting the best six of forty as
six tests is not a convention this codebase asks people to follow — it is unrepresentable. Entries
that could not be evaluated still occupy their trial, because removing them shrinks the denominator
every surviving q-value depends on.

p-values are exact two-sided binomial via `math.comb` — scipy is deliberately absent, so the
statistics are auditable — computed on the **independent** sample size, never the raw count.
Verified against five textbook values. The Benjamini–Hochberg implementation reproduces the original
1995 paper's Table 1: **four rejections where Bonferroni gives three**.

### What the scan measured on real history

12 catalogued expressions × 3 horizons on QQQ: **36 trials, 0 discoveries.** One entry reached raw
`p = 0.0919` — it would clear an uncorrected screen — and came out at `q = 1.0000`.

The SOXL scan is the sharper illustration:

| Expression | h | edge | indep. n | p | q |
|---|---|---|---|---|---|
| `close > bb_upper(20,2)` | 5b | −9.6% | 129 | **0.0410** | **0.704** |
| `ema(50) crosses_above ema(200)` | 20b | **+29.1%** | **8** | 0.1512 | 0.907 |

The first row would have cleared `p ≤ 0.05` on its own. The second is the golden cross showing an
87.5% hit rate against a 58.4% baseline — spectacular, and resting on eight independent
observations, which is why it is flagged small-sample and why its q-value is 0.907.

## The A/B result worth keeping

On QQQ, adding the classic "confirmation" to a lower-band touch:

| Arm | h=1 | h=5 | h=20 | n |
|---|---|---|---|---|
| `close < bb_lower(20,2)` | −0.97 pts | +4.38 pts | +4.34 pts | 342 |
| `… and rsi(14) < 30` | +3.13 pts | +3.28 pts | **−0.77 pts** | 72 |

Adding RSI confirmation makes the setup **worse** at 20 bars — a −5.2 point delta — and costs 79% of
the sample. `ArmDelta` carries the sample-size change alongside the rate change specifically so a
12-point gain bought with 79% of the evidence cannot render as an improvement.

## Reverse conditioning

Typed as a separate class from `EventStudy` rather than a flag on it, carrying **no hit rate, no
p-value, no q-value**. Those numbers have no meaning against a hypothesis read off the same sample,
and a field holding one would eventually be rendered. The UI fences it in its own tinted panel for
the same reason.

On QQQ's top-decile 20-bar moves it found something sensible: MACD signal depressed (separation
−0.434 IQRs), RSI lower (median 47.5 vs 54.9), ATR elevated (+0.150) — big up-moves follow
high-volatility selloffs. And **688 selected bars collapse to 96 independent episodes**, a 7×
overstatement the raw count would have hidden. On SOXL, 411 → 60, a 6.8× overstatement.

## Defects found and fixed

**A docstring that promised what the code did not do.** `scan.py`'s docstring stated it produced an
entry for every pair "including a failed guard or a raised exception". The loop had no `try`, so one
expression raising would have emptied an entire scan — exactly the failure `app.rules.service` was
built to avoid for one bad rule. The trials invariant cannot be kept by a loop that dies partway.

**Validation that disappears under `python -O`.** `runcard.py` validated deserialised run cards with
`assert isinstance(...)` inside a `try` that caught `AssertionError`. `-O` strips assert statements,
so an optimised run would let a malformed or hand-edited card through into the audit trail the module
exists to keep trustworthy. Replaced with explicit checks that name the file and the field.

**An incomplete monkeypatch that made a guard test lie.** `app.rules.grammar` binds
`from app.indicators.registry import get` at module scope, so patching `registry.get` alone leaves
the parser rejecting an injected indicator by name before the guard ever sees the tree. The test
looked like it had caught a lookahead violation when it had caught a typo. Both bindings are now
patched, and the test that documents this says why.

Also: `Callable` used in an annotation without being imported (masked by
`from __future__ import annotations`), and three unused imports.

## The carried-forward RSI question, resolved — and I had the mechanism wrong

Phase 6 flagged that a flat price series yields RSI = 100, and that this might trip an overbought
rule once Phase 7 attached rules to thresholds. Two things turned out to be false.

**A flat run does not drive RSI to 100.** During one, `avg_gain` and `avg_loss` decay by the same
factor, so their ratio is constant and RSI *freezes* at its pre-run value. DX-Y.NYB's real 11-bar
identical-close run (1971-08-16 → 08-30) holds RSI at exactly 16.317 throughout — reading oversold,
not overbought. Across 148,000 stored bars in 21 symbols there are zero flat-14 windows and RSI never
reaches 100.

**And where it does occur, the baseline neutralises it.** Pointing a scan at the two instruments that
genuinely produce RSI = 100:

| Instrument | fires | hit rate @20 | baseline | **edge** |
|---|---|---|---|---|
| Constant $1.00 NAV | 386/400 | 0.0 | 0.0 | **0.0** |
| Monotonic riser | 386/400 | **1.0** | 1.0 | **0.0** |

The second row is the point: a rule with a **100% hit rate over 366 samples** correctly reports zero
edge, because the instrument rose in 100% of all windows. Without the baseline that renders as a
discovery. There is nothing to fix, and a special case would only mask the demonstration.

## One shared implementation, not two

`app.rules.evidence` now imports `forward_returns`, `independent_count` and `hit_rate` from
`app.backtest.forward` instead of carrying its own copy. Two forward-return implementations agreeing
today is not a property anyone can maintain, and when they drift the decision table and the workbench
report different numbers for the same question with nothing to say which is right. All 49 existing
Phase 6 evidence and API tests stayed green through the refactor, untouched.

## Process note

Seven build agents and three QA agents were dispatched in parallel; a session limit killed nine of
them mid-flight. Drawdown, events, scan and run cards survived as files on disk. Guards, the service
layer, the API router, four test suites and the remaining frontend were finished inline. The three QA
agents produced nothing, so defect hunting was done directly — which is where the four defects above
came from.

## Carried forward to Phase 8

The FDR denominator here is **per-scan**. The plan's global trial ledger — every thesis ever
registered for a ticker, persisted in SQLite so the q-value of thesis #40 reflects the 39 before it —
is Phase 9's `thesis/ledger.py`, along with pre-registration and the locked holdout. Nothing in Phase
7 claims more than "this scan, this family".

Reverse conditioning's output is labelled exploratory but nothing yet *enforces* that a candidate
read off it gets counted as a trial when later tested. That enforcement is the pre-registration
guard, and it belongs with the ledger.

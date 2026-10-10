# Phase 8 — Strategy backtest, grounded narrative, report export

Commit `ab52332`. 1244 tests pass (up from 1162), `ruff` and `mypy --strict` clean across 81 files,
frontend typechecks and builds. Verified live against 4,129 stored SOXL sessions and 6,897 QQQ.

## What shipped

- **Strategy backtest** (`backtest/strategy.py`, `metrics.py`) — full entry/exit equity curve with
  CAGR, Sharpe, Sortino, max drawdown, exposure, turnover and win rate, always against buy-and-hold
  over the identical window.
- **The citation contract** (`report/narrative.py`, `builder.py`) — prose that may cite computed
  facts and may not write numbers.
- **Per-holding report** (`report/service.py`, `api/report.py`) plus a Markdown export that carries
  its own fact table.
- A `Report` page with narrative sections, drawdown, decision summary, strategy card and the bundle.

## The grounding contract

No LLM is configured in this repo, and the contract does not need one. That is the design, not a
limitation.

"Only cite figures from the bundle" is an instruction a language model follows most of the time. The
failures are not obvious — they are fluent, plausible sentences containing a number nobody computed,
which is the hardest kind of error for a reader to catch, because everything about the sentence
signals that someone did the work. So the enforcement is a checker.

**A narrative holds no numbers.** It is a template in which every figure is a `{{fact:id}}`
reference, resolved against the bundle at render time. A bare numeral anywhere outside a reference
is a rejection, not a warning — the alternative is deciding per number whether the writer had a
source, and that decision cannot be made by reading the text, which is the whole problem.

**Digits are matched by Unicode category, not `0-9`.** U+FF14 and U+0664 render as ordinary numbers
and `int()` parses them; an ASCII-only scan waves them through. Four such codepoints are in the test
suite, written as `chr()` calls so the linter's own ambiguous-character rule — the same instinct this
check encodes — does not have to be suppressed.

**There is no path from an unverified draft to displayable text.** `render()` takes the
`GroundingReport` as an argument rather than recomputing it, so "was this verified?" is something the
caller must already have an answer to. `compose()` returns a union of the narrative or the failing
report, so a caller who wants prose has to look at which one they got.

**The default narrator is not exempt.** Its templates go through the identical verification. They are
written by hand against ids the builder emits, and the two drift the moment either changes — running
them through `verify` turns that drift into a failing test rather than a report sentence reading
`the deepest drawdown was {{fact:...}}`.

### What it does not catch, stated on every report

Verbal quantities carry no digits and pass. "Roughly a third", "nearly doubled", "catastrophic" are
outside what this check can see. `GroundingReport.caveat` says so wherever a narrative renders,
because a green check implying more than it verified is worse than no check.

### The adversarial tests

Each of these is refused, verified live against the real SOXL bundle:

| Attempt | Verdict |
|---|---|
| `SOXL fell 90.5% from its 2021 peak.` | `bare_numeral` |
| `The Sharpe ratio was {{fact:strategy.sharpe}}.` | `unknown_fact` |
| `It fell {{fact:drawdown.max_depth}} and recovered within 14 months.` | `bare_numeral` |
| `It fell {{fact:drawdown.max_depth}} from {{fact:drawdown.peak_date}}.` | grounded |

The third is the realistic failure: mostly-correct prose that cites properly and then adds one figure
of its own. A checker that stopped at the first valid reference would pass it.

## Why a template rather than finished prose

A stored narrative cannot drift from its data. Update the bars, re-render, and the sentence moves
with them or fails loudly. A draft that had quoted `-90.5%` directly would be frozen at the moment
someone wrote it and silently wrong afterwards, which is what makes a stale report worse than no
report. There is a test that renders one draft against two bundles and asserts both readings.

## The strategy backtest

**Buy-and-hold is a required field**, for the reason `baseline_hit_rate` is: a 14% CAGR next to a 19%
buy-and-hold is a loss, and a page showing only the 14% has reported a success. Measured over the
identical window by the same code, so the pair is comparable by construction.

**Frictions are measured, not estimated.** `cost_drag` re-runs the whole simulation at zero cost,
because slippage moves the fill price and therefore the stop-loss trigger — subtracting an estimate
would be wrong on exactly the strategies where it matters.

**Every metric carries its assumption.** Sharpe records the risk-free rate it was computed against;
CAGR is `None` under a year rather than extrapolated; Sortino is `None` when no bar lost money,
because an infinite Sortino is an empty denominator rather than a strong result; the win rate
excludes a position still open at the end.

**Stops fill at the stop, not the close.** A bar that dips through the level and closes back above it
fills at the stop; a gap through it fills at the open, which is worse — and is what actually happens.

### What it measured

| Strategy | Return | Buy & hold | Excess | Exposure | Max DD | Sharpe |
|---|---|---|---|---|---|---|
| QQQ band touch, 20-bar hold | +192.2% | +1301.4% | **−1109.2%** | 33.7% | −58.3% | 0.30 vs 0.49 |
| QQQ golden/death cross | +1337.1% | +1301.4% | **+35.7%** | 72.0% | **−30.3%** vs −83.0% | **0.68** vs 0.49 |
| SOXL oversold, 10% stop | −24.7% | +19567.2% | −19591.8% | 7.0% | −76.6% | 0.11 vs 0.81 |

The middle row is the only one that looks good, and it is worth being careful about: 14 trades, and
Phase 7's scan already put the golden cross at `q = 0.907`. The better max drawdown and Sharpe at 72%
exposure are the real observations; the +35.7% excess rests on very few independent events.

The SOXL row is the useful one. 22 of 30 trades stopped out, a 26.7% win rate, against an instrument
that returned +19567% by being held. A backtest that reported only the strategy's number would have
described that as a −24.7% year.

## Two defects in prose the report actually generated

**"Of 12 catalogued rules, 1 are currently firing."** A narrator may *read* a fact's value freely —
what it may not do is write a numeral. Branching on the count to pick "is" or "are" is fine, and
skipping it produces a sentence that reads as a broken report.

**An edge reported without its grade.** The evidence sentence named the largest measured edge — the
golden cross at +29.1% — with no significance attached. Selecting by magnitude systematically picks
the smallest sample: a big edge on few observations is exactly what noise produces, and taking the
maximum across twelve rules is a selection procedure with no correction. The sentence now names the
grade and the independent count in the same breath, and a following sentence spells out the selection
effect. Reporting the figure alone would have reproduced, inside the report, the error the whole
project is arranged to prevent.

## Contract gaps I introduced, found by the agents

**A commission with no unit.** `Costs.commission_per_trade` is a currency amount; the equity curve is
a unitless multiplier starting at 1.0. Converting one to the other needs a notional, and my contract
had none. The build agent invented a module constant and documented it honestly. That was the right
call for a file it owned, but a constant buried in the simulator silently sets a number the reader
sees without appearing anywhere they could find it — so it is now `Costs.notional`, a declared field
that reaches the run card's params and the API.

**A three-way distinction collapsed into a boolean.** `edgeInsideCosts` fired on any excess below the
cost drag, including a catastrophically negative one, so the UI told a reader that a run trailing
buy-and-hold by 130 percentage points had an edge "smaller than what frictions cost". That describes
a rout as a close call. Now `edgeVerdict` returns `underperforms` / `inside_costs` / `exceeds_costs`
/ `unmeasurable`, and the two failure modes get different severities.

## A false alarm, checked rather than assumed

A `ReferenceError: edgeVerdict is not defined` appeared in the browser console after the contract
edit. It was stale HMR state — a clean dev-server restart cleared it, and the new callout had
rendered correctly throughout. Separately, `/report/SOXL` showed 182px of horizontal overflow, which
turned out to be the pane sitting at a 375px viewport: the untouched Phase 7 `/backtest` page
overflows **199px** at the same width, and at the app's actual 1280px target every page including
this one measures **0**. Both are the pre-existing fixed-200px-sidebar shell limitation recorded in
the Phase 6 report, not a Phase 8 regression.

## Carried forward to Phase 9

Phase 9 is gated on 6, 7 and 8 being trustworthy, and it adds no statistics of its own — it is an
agent loop over these engines. What it still needs and this phase does not provide:

- **Pre-registration** — a content-hashed thesis frozen before any backtest runs.
- **A global trial ledger** — Phase 7's FDR denominator is per-scan; Phase 9's is every thesis ever
  registered for a ticker, persisted, so the q-value of thesis #40 reflects the 39 before it.
- **A locked holdout**, with a second look refused and the refusal surfaced.
- **A declared iteration budget**, where exhausting it with nothing surviving is a reportable result.

The grounding contract built here is what Phase 9's report writer runs under: no agent may assert a
number it did not compute through these engines, and the checker rather than the prompt is what makes
that true.

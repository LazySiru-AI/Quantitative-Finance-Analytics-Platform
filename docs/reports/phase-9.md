# Phase 9 — The thesis loop

Commit `9c12a3a`. 1378 tests pass (up from 1244), `ruff` and `mypy --strict` clean across 92 files,
frontend typechecks and builds. Verified against 6,897 QQQ / 8,438 SPY / 4,129 SOXL stored sessions
and 700 synthetic null series.

## The hazard, stated first

An agent that generates theses and tests them until one looks good is a p-hacking machine. That is
not a risk of this design, it is the **default behaviour** of it. Three properties make this setup
worse than ordinary multiple testing: the trial count is invisible when a loop discards weak theses
and never mentions them; the generator sees the data, so a thesis proposed after looking at the chart
is a description of the sample dressed as a hypothesis; and iteration is unbounded, so "loop until
proven" always terminates successfully because there is always another specification that works.

So this package is mostly machinery for saying no, and it adds **no statistics of its own** — every
number comes from the Phase 6–8 engines.

## The four guards

**Pre-registration.** The hypothesis, entry, exit, holding cap, stop, horizon, predicted direction
and falsification criterion are content-hashed before any backtest runs. There is no edit path:
changing any of them yields a different hash, a different record, another trial. The rationale field
is deliberately *excluded* from the hash — it carries no claim, and hashing it would charge a trial
for a cosmetic edit, which teaches people to leave it blank. `falsifies_if` is required and non-empty
on a frozen model; a criterion supplied after the numbers arrive is one tuned to pass.

**Global trial ledger.** Every thesis ever registered for a ticker persists in its own SQLite file —
never the brokerage ledger; a research feature must not be able to write near the user's real
transactions — including abandoned ones. Benjamini–Hochberg runs over that whole family. Verified
against an independently hand-written step-up: all ten q-values matched exactly, and counting the two
abandoned trials made every q-value **1.20× harsher**.

**Locked holdout.** Stateful per ticker, split positionally at a fixed 25% from the end so the
boundary cannot be chosen for what it contains, and frozen once set — recomputing as history grows
would slide previously-held-out sessions into the in-sample period and the guarantee would decay
untouched. One evaluation. A second attempt is **recorded as burned**, not silently refused: a
refusal leaving no trace produces a system where the stored result still looks clean to anyone who
did not witness it.

**Declared iteration budget.** Decremented on every iteration whether or not it produced anything.
Exhausting it with nothing surviving is a valid, reportable outcome.

**And direction is checked, not just magnitude.** A significant effect *opposite* to the prediction
refutes a thesis. A loop scoring on `abs(edge)` would report it as a discovery, which is how a
mean-reversion claim survives on momentum data.

## The null-series test, and the hole it found

The most important test in the feature: pointed at driftless random walks for a full budget, the loop
must report zero survivors. It earned its keep on the first run.

The holdout confirmation was originally a **sign check** — does the out-of-sample edge point the
predicted way. On a driftless walk that is a coin flip, so a thesis that squeaked through the
in-sample screen had roughly even odds of being "confirmed". Seed 3 duly produced a survivor on pure
noise.

The holdout now requires the same power floor as the in-sample screen (30 independent observations)
plus an **unadjusted** p ≤ 0.05. Unadjusted is correct rather than an oversight: everywhere else in
this project a raw p-value misleads because the family is large and was searched, but this is one
pre-registered test of one frozen thesis against data nothing has looked at — the single situation
where a raw p-value means what it says, and the entire reason a quarter of the history is reserved.

After the fix: zero survivors across 8 seeds here, and an adversarial pass found none across **700
series spanning 14 generator families** — GBM at three volatilities and three lengths, Student-t fat
tails, GARCH volatility clustering, drifting series, Ornstein–Uhlenbeck, AR(1) momentum clustering,
and fast/slow Markov regime switching.

The margin is worth recording. The closest near-miss came on slow regime-switching noise, where a
thesis produced a holdout `p = 0.0113` — comfortably inside the threshold — with a correctly signed
edge, and was stopped by the sample-size floor at 19 independent observations rather than by the
p-value. **The power floor is load-bearing, not decorative.**

## Two test-construction mistakes of mine

Both the same error in different clothes, and both worth recording because they are how a planted
effect fails to be a test at all.

The first planted-effect series used asymmetric drift on `close > sma(200)`, which trends the series
up almost everywhere: 99.9% of all 20-bar windows were positive, so the conditional and unconditional
hit rates were *identical* and the edge was exactly zero. The effect was in the data and the
measurement was correct — there was nothing left to discriminate.

Making the drifts symmetric did not help, because the condition has **positive feedback**: above the
average implies upward drift implies still above the average. It locked on, firing on 2,781 of 2,800
bars, so the conditional sample simply *was* the baseline sample.

A planted effect needs a condition that is both genuinely selective and not self-reinforcing. A
band excursion is both — it is mean-reverting by construction, so the bounce it triggers pushes price
back out of the condition rather than deeper into it.

## Five defects found by adversarial QA

Four were in the guards themselves, which is the point: guards need attacking, not exercising. All
were reproduced and verified before fixing.

**`LoopResult.survivors` was structurally always empty.** It filtered `cards`, which the loop never
populates, so it returned `[]` on every run whatever the verdicts were — and the null-series
assertion built on it was **passing vacuously**. Only the paired `outcome` check was load-bearing.
Now derived from `records`.

**`holdout.claim()` had a read-then-write race.** `SELECT`, branch in Python, `UPDATE` keyed only by
symbol. Eight concurrent callers produced **six clean looks**, all recorded as a single evaluation
with the row reading `spent`. The whole guarantee is "one look", so the decision now happens inside
`BEGIN IMMEDIATE` against the row being updated. Verified: 1 of 8 granted, status `burned`, attempts
8.

**A second run silently re-rolled stored p-values.** The loop re-proposed the identical catalogue and
re-tested every hash, and `update_outcome` overwrote the stored value — five of five changed against
different bars while the trial count stayed at five. The first evaluation vanished from the
denominator entirely: hazard property (1) reappearing inside the machinery built to prevent it.
Terminal theses are now skipped, and they consume no iteration.

**`update_outcome` accepted a payload describing a different thesis**, producing a row whose flat
columns described one thesis while its JSON payload described and endorsed another. Not reachable
through the shipped loop, but it is a missing check at a documented trust boundary.

**`BUDGET_EXHAUSTED` was reported when the catalogue, not the budget, was the limit.** With five
templates against a budget of twelve, every run reported as if twelve attempts had been made. "No
thesis survived twelve attempts" is information about the ticker; "the author had five ideas and none
worked" is information about the author. `CATALOGUE_EXHAUSTED` now distinguishes them.

## What it measured on real history

Nothing survived on QQQ, SOXL or SPY. That is the expected result.

SPY is the demonstration worth keeping:

| | in-sample | holdout |
|---|---|---|
| `close < bb_lower(20,2)` | edge **+8.6%**, n=110, **p = 0.0616** | edge +3.2%, n=34, **p = 0.856** |

That in-sample figure cleared the screen and the BH threshold on its merits, so it earned the one
holdout evaluation SPY will ever get. The holdout refused to replicate it and the verdict came back
**inconclusive** — the exact sequence the guard exists to produce. QQQ's holdout was never spent,
because nothing survived in-sample and spending the single look on something already refuted would
waste it.

## Known limitations, stated

- ~~**No marginal tax rate exists in config**~~ — **fixed**, see `docs/reports/defects-1.md`. The
  rate is now configurable and the figure records which basis produced it. The wash-sale count it
  reports was, and still is, the real Phase 3 engine.
- ~~**`ira_exposure` is always False.**~~ — **fixed**, see `docs/reports/defects-1.md`. It is now
  tri-state and reports unknown, because detecting it needs the user's real cross-account holdings
  and the card layer is deliberately walled off from `data/`. A hardcoded `False` was a claim this
  code had no basis for.
- **The unlevered comparison is descriptive, not a second registered trial.** Running the same rules
  on the underlying is a sanity check on leverage decay, not an independent hypothesis.
- **The author is blind to the sample by construction** — it sees the symbol, the interval and the
  instrument class, never the bars. That makes its proposals unoriginal, which is the point: an
  unoriginal hypothesis tested honestly beats a bespoke one tested circularly.

## What this will not do

It will not place orders. It will not tell anyone to buy anything — a strategy card reports what a
rule did historically, with its sample size and its failures. And it will not report a thesis it
cannot support: underpowered is a verdict, not a gap to be filled with narrative, and `inconclusive`
is the expected outcome for most theses on most tickers.

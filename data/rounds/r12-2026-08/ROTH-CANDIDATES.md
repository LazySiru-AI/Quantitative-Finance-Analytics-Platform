# Roth candidates on the tournament's own windows

**Not investment advice.** Simulated results on stored price history. I am not a licensed financial
adviser and none of this is a recommendation about real capital.

Produced by `strategy-program/tools/roth_matrix.py`. Full stdout: `data/rounds/r12-2026-08/roth-matrix.txt`.
Machine-readable: `data/rounds/r12-2026-08/roth-matrix.json`.

## What this is

Round 11 closed by naming the binding constraint on the programme: `ROTH-MOMENTUM.md` and
`ROTH-VOLTARGET.md` hold the only genuinely new ideas since round 5, and neither has ever run on the
windows a future round would actually gate a card on. This report runs both families' `WeightFn`
factories (unmodified, reused directly from `roth_momentum.py` / `roth_voltarget.py`) through the
existing contribution-funded harness (`contributions.py`, $7,500/year), over `strategy-program/tools/
windows.py`'s round-5 horizon ladder (21 windows, 6 months to 10 years) plus its six bear-supplement
windows -- the same calendar `app.tournament` gates a `StrategyCard` against.

Seven variants were run: from `ROTH-MOMENTUM.md`, absolute momentum, the moving-average regime switch
(that document's own named best candidate), the confirmed-regime blend, and the static 40/30/30
QLD/SCHD/IEF baseline; from `ROTH-VOLTARGET.md`, vol-target 12% at a 20-session lookback (that
document's own named best candidate), the risk-budgeted core ("credible second choice"), and the
volatility circuit-breaker (flagged in its own document as neither clearly keep nor discard). SCHD
stands in for both families' "income sleeve" throughout, because every round-5 window used here starts
in 2013 or later -- after SCHD's own first bar (2011-10-20) -- so no SPY-proxy substitution was needed
anywhere in this run, unlike the families' own longer 2006-origin windows.

## Coverage: every window ran, for a reason that matters

**All 27 windows (21 ladder + 6 bear) produced a real result for every one of the seven variants and
both benchmarks -- zero cells skipped for missing price history.** QLD (2006-06-21), SCHD
(2011-10-20), IEF (2002-07-30), SPY (1993-01-29) and QQQ (1999-03-10) all predate the earliest round-5
window (`h10y-1`, starting 2013-09-03) by a wide margin. That is a property of this symbol selection,
not a general guarantee -- a future variant reaching for GLD, TQQQ, SGOV or any 2020-era-only symbol
would hit real skips on the pre-2020 windows, and `roth_matrix.py`'s `eligibility_reason` would report
them the way `score.py` treats a missing cell: as absent, never as zero.

**A second, more important coverage problem showed up that has nothing to do with price history.** This
script feeds each window only that window's own bars, matching how a lump-sum `StrategyCard` is bounded
by its own window in `app.tournament`. Two of the momentum family's three active strategies gate their
first real position on a 200- or 252-*session* lookback computed from those bars alone. For any window
shorter than that lookback, the strategy's internal state never leaves its initial all-defensive weight
-- the row is mechanically indistinguishable from "100% SCHD" (absolute momentum) or "50/50 SCHD/IEF"
(the MA regime switch and the confirmed-regime blend) for the entire window, which is not a
demonstration of the rule at all. Counted directly from this run:

| variant | ladder windows with no real signal | which horizons |
|---|---|---|
| abs momentum (QLD/SCHD) | 10 of 21 | all 6 six-month, 4 of 6 one-year |
| MA regime (QLD vs 50/50 SCHD/IEF) | 6 of 21 | all 6 six-month |
| confirmed regime (QLD vs 50/50 SCHD/IEF) | 6 of 21 | all 6 six-month |
| every vol-target/circuit-breaker/risk-budgeted variant | 0 of 21 | -- (20-session lookback clears every window comfortably) |
| static 40/30/30 baseline | 0 of 21 | -- (no lookback at all) |

Every affected row is marked with a trailing `*` in `roth-matrix.txt` and carries `"signal_activated":
false` in the JSON. This is not a defect in the strategies -- `make_abs_momentum` and `make_ma_regime`
are doing exactly what their own docstrings say (park in the defensive default until there is enough
history to evaluate a real signal) -- it is a real gap in what this script can make comparable: a future
integration into the tournament proper needs to prime a momentum-family strategy's lookback state from
bars *before* the window starts, the same way `strategy-program/tools/windows.py`'s own
`_bars_to_calendar_days` already computes a warmup deadline for `StrategyCard` eligibility, without
letting that lead-in period also collect a phantom contribution it should not. That is real work, not a
two-line patch, and this script does not attempt it.

## The single most important caveat: these numbers are not the tournament's numbers

**Every figure in `roth-matrix.txt` is a contribution-funded quantity -- $7,500 deposited every
January -- and every `StrategyCard`'s `adjusted_excess` in `score.py` is a lump-sum quantity: one
deposit at inception, never touched again.** `contributions.py`'s own module docstring explains why
this is not a rounding difference: sequence risk *inverts* between the two shapes. A lump-sum investor
is hurt by a crash near the end of the window, when the balance is largest; a contributor is *helped*
by one early, because the same dollars buy more. A strategy that looks defensive under a lump sum can
look merely expensive under contributions, and the reverse. Because of this, this report deliberately
never quotes a Roth variant's IRR or excess-vs-SPY figure next to a `StrategyCard`'s `adjusted_excess`
in the same column -- the benchmark for every row here is a same-shape buy-and-hold of SPY or QQQ on
the identical annual contribution schedule, so a variant's number is read only as an excess over a
contribution-funded passive alternative.

**What a future round would need before these could be gated beside `StrategyCard`s at all:** either
(a) a lump-sum re-expression of each `WeightFn` run once through `app.tournament`'s own engine on
`StrategyCard`'s terms, which is nontrivial because these are continuous target-weight allocations, not
the boolean per-symbol entry/exit rules a card's grammar expresses; or (b) a formally separate,
labeled column in whatever scorer eventually ranks them, so a contribution-funded IRR and a lump-sum
`adjusted_excess` are never collapsed into one number a reader could rank across. Neither exists yet;
this report is the evidence that would motivate building one, not a substitute for it.

## What the results actually show

> **Corrected during integration, before this memo was published.** The first version of this section
> led with "the static 40/30/30 blend beats both families' named candidates on the ladder arm
> (+4.9% against +2.5% and +0.5%)". **That ordering was an artefact of signal-starved windows** and
> the corrected comparison reverses it. The contaminated figures are kept below rather than
> overwritten, because the mistake is instructive and is the same shape as `DEFECTS.md` D5.

### The comparison that can be ranked

A variant whose rule needs a 200-252 session lookback **cannot activate inside a 6-month window** --
its book holds the fallback sleeve start to finish (see "Coverage" above). Those cells are real
records of what the book did, but they are records of the *fallback*, not the strategy. Ranking a
20-session-lookback variant against a 252-session one on a window set that includes such cells
compares one strategy against another strategy's cash position.

Restricting to **common support** -- the windows where every variant's signal is live -- gives the
only cross-variant ranking that means anything. 11 of the 21 ladder windows qualify, and 3 of the 6
bear windows:

| variant | ladder (n=11) | bear (n=3) |
|---|---|---|
| **MA regime** (`ROTH-MOMENTUM.md`'s pick) | **+10.3%** | +6.2% |
| static 40/30/30 QLD/SCHD/IEF | +4.9% | **+2.5%** (worst) |
| confirmed regime | +4.9% | +11.7% |
| risk-budgeted core (lb20) | +4.2% | +9.1% |
| abs momentum | +3.6% | +5.4% |
| **vol-target 12% lb20** (`ROTH-VOLTARGET.md`'s pick) | +0.6% | **+12.8%** |
| circuit-breaker (lb20) | −1.4% | +5.2% |

**So the MA regime switch does beat the static blend on the ladder arm, by 5.4 points**, and the
static blend is the worst variant in the field on the bear arm. The starved cells were dragging the
momentum family down by 3.6 to 6.8 points of median each; the static blend and the whole vol-target
family have a 20-session lookback and were unaffected, so only one side of the comparison moved.

Reproduce with the "COMMON SUPPORT" block in `roth-matrix.txt`, or `common_support` in
`strategy-program/tools/roth_matrix.py`.

### The contaminated figures, kept for the record

Over **all 21** ladder windows the static blend posts +4.9% median / 81.0% hit rate, the MA regime
+2.5% / 52.4%, and vol-target 12% +0.5% / 52.4%. Those numbers are arithmetically correct and answer
a different, narrower question: *what did each book actually return over these windows, fallback
periods included*. They cannot be used to rank the variants against each other, and the first draft of
this memo did exactly that.

### What survives the correction

Both source documents' own warning still stands and is not undone by any of the above: much of the
momentum family's edge is a **leverage effect** -- more average time in QLD -- rather than timing
skill. `ROTH-MOMENTUM.md` records its best variants averaging 75-80% QLD. A rule that beats a static
blend mostly by holding more of the leveraged sleeve is not the same thing as a rule that times the
market, and the ladder arm cannot tell those apart. The bear arm is where it would show, and there the
static blend is indeed the only variant with a negative median across all six windows (−1.3%).

**The genuinely new finding from this run is not a ranking at all.** It is that **10 of 21 ladder
windows are too short for the momentum family's own signal to fire**, which means the tournament's
existing window ladder cannot evaluate a long-lookback allocation strategy without either priming the
lookback from pre-window bars or restricting the comparison to common support. That is a window-design
problem for whoever gates these candidates, and it is not visible from any single variant's numbers.

**The picture reverses in the bear-supplement arm, which is the one place a regime-switching mechanism
is actually supposed to earn its complexity.** Over the six bear-supplement windows (each pre-registered
to start near a market top and run through a real drawdown), the confirmed-regime blend has the best
median excess IRR vs SPY (+13.7%), the MA regime switch is close behind (+11.5%), and the volatility
circuit-breaker also does well (+12.2%) despite its own document flagging it as the riskiest variant in
the field. **The static 40/30/30 baseline is the only variant with a *negative* median excess in the
bear arm (-1.3%)** -- it is the best performer on ordinary regime-sampled windows and the worst,
relative to the field, in the six windows deliberately chosen to contain a real drawdown. Read together,
these two findings are the honest version of the leverage-trap warning both source documents make:
timing mechanisms cost something in calm, regime-sampled history and pay for that cost specifically in
a crash, and a matrix that only reports one arm would misstate which of those trades a reader is
actually being offered.

**Per-horizon (ladder arm only, bear arm excluded from this cut to avoid mixing a deliberately
drawdown-selected 6-month sample into an ordinary one -- see `roth-matrix.txt`'s own note):** the MA
regime switch's median excess climbs with horizon length -- -9.6% at 6m (fully no-signal-contaminated,
so this number describes "100% SCHD/IEF" not the switching rule), +7.4% at 1y, +4.4% at 3y, +19.2% at
5y, +7.7% at 10y -- consistent with a rule that needs years, not months, to show its edge. Vol-target
12% lb20 never clears +5% median at any single horizon and is negative at 6m (-6.5%) and 10y (-1.3%),
which does not straightforwardly support "keep this one" as strongly as `ROTH-VOLTARGET.md`'s own
three-window verdict did -- that document's MAR-based ranking used only CRISIS/PRIMARY/FULL, three
highly overlapping views of one historical path (its own "what could not be tested" section says so
directly), and the 21-window ladder is a materially different, less flattering picture for this
specific candidate.

## Negatives, stated as plainly as the positives

- **Neither family's own "best candidate" wins the median comparison on the tournament's own ladder.**
  Both were selected against each family's own three long, overlapping historical windows; neither is
  the ladder's best median performer once the comparison broadens to 21 shorter, more varied slices.
- **A third of the momentum family's ladder cells (16 of 63 run-cells across its three active
  strategies) are not measuring the rule at all** -- see the coverage section above. Any reader of
  `roth-matrix.txt` who does not notice the `*` marker could mistake "100% SCHD, unconditionally" for
  "absolute momentum" in ten of twenty-one ladder windows.
  - **The vol-scaled family's apparent robustness is partly a lookback artifact, not a strategy
    strength.** Its 20-session lookback clears every window in this ladder cleanly, where the
    momentum family's 200/252-session lookback does not -- that is a fact about how fast each
    family's signal warms up, not evidence that vol-targeting is the better-designed rule.
- **The circuit-breaker's bear-arm result (+12.2% median) sits awkwardly next to its own document's
  verdict** ("the strategy to flag rather than either keep or discard outright," because its
  all-or-nothing trigger missed 2009-shaped recovery rallies in the CRISIS window). This run's six bear
  windows are shorter and more numerous than that one long crisis slice, and do not settle the
  disagreement -- they add one more data point on each side.
- **Turnover and slippage cost are not broken out separately in this report** the way
  `ROTH-VOLTARGET.md`'s own tables do (its "cost of turnover" sections). `contrib.summarise`'s `rebal`
  column is printed per window in `roth-matrix.txt`, and it confirms the same pattern that document
  found -- the vol-scaled family trades far more than the momentum family or the static baseline in
  every window -- but a bp-of-final-balance cost figure was not recomputed here.

## What was not attempted

- No lump-sum re-expression of any variant through `app.tournament`'s engine -- explicitly out of
  scope for this pass (see "single most important caveat" above).
- No sweep of lookback, target-vol, or regime-switch parameters -- every variant uses exactly the
  parameters its own source document names as the candidate worth testing.
- No priming of momentum-family lookback state from bars before a window's start. This is the fix that
  would resolve the no-signal contamination noted above; it was judged real, non-trivial work (getting
  the contribution schedule right across a lead-in/window boundary) rather than something to improvise
  inside this script's scope.

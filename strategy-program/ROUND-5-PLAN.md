# Round 5 — the horizon ladder

Rounds 1–4 all asked the same shape of question: *which card is best over a set of named market
regimes?* Round 4 answered a different one by accident, and the answer disqualified the question.

This round asks: **does the answer depend on how long you hold the competition open?**

## 1. Why this round, and why now

Round 4's finding was that its own verdicts, and round 3's, were largely properties of the window
matrix rather than of the cards. Round 3's eight windows carried a mean benchmark return of −9.45%
(six of eight falling); round 4's six carried +17.13% (two of six falling). The same frozen cards
reversed completely between them — `c14-riskmanaged-wide` went from the Pareto frontier to 13th of
14, and the retired A family came back positive and would have placed second.

The obvious response is "balance the matrix." That is necessary but not sufficient, because it
leaves a second variable untested: every window this programme has ever scored is between 45 and 284
sessions long. **Nothing has ever been measured over a multi-year hold.** A card whose edge is a
handful of well-timed entries per quarter and a card that compounds slowly are indistinguishable at
64 sessions and completely different at ten years, and the programme has been ranking them against
each other as though they were the same kind of object.

Round 5 varies **duration** deliberately, holding the sampling rule constant, so that horizon can be
read off separately from regime.

## 2. The design

### The common period is 12.4 years, and that is a hard constraint

Every card must be able to run every window, or the comparison is not like-for-like — round 4's
report made that point about `taper-2013` and it applies with much more force here. The binding
symbol is `NOW` in the four `B*` universes, first bar **2012-06-29**, which with a 200-day warmup
plus margin puts the earliest safe start at **2013-09-03**. The design cutoff is **2026-02-13**.

That leaves **2013-09-03 → 2026-02-13**, 12.4 years, for a ladder whose top rung is ten years.

### Arm A — the ladder (21 windows)

| horizon | windows | sessions each | overlap within horizon |
|---|---|---|---|
| 6m | 6 | ~126 | none |
| 1y | 6 | ~252 | none |
| 3y | 4 | ~755 | none |
| 5y | 3 | ~1258 | partial |
| 10y | 2 | ~2516 | **62%** |

Sampled by one rule — evenly spread across the same calendar — so the horizons are comparable to each
other. That is the whole point: a difference between the 6m and 10y columns has to be attributable to
duration, not to one horizon having drawn a different decade.

**The 5y and 10y rungs cannot be independent, and pretending otherwise would be the round's first
lie.** Twelve years of common history contains one non-overlapping decade. The two 10y windows share
62% of their sessions and differ mainly in where they *stop* — 2023-08 and 2026-02. That is still
worth measuring, because endpoint sensitivity is the honest long-horizon question, but their two
results are close to one measurement and are reported as such, never as a median of two.

### Arm B — the bear supplement (6 windows)

Arm A inherits the calendar it is drawn from, and 2013–2026 was one of the longest bull runs on
record: **the benchmark rises in 19 of the 21 ladder windows.** At 10y there is no alternative — no
decade in this data has a falling benchmark, and saying so is a finding, not a defect. At 6m and 1y
there is, so Arm B adds three of each, selected for a deeply negative benchmark:

| tag | period | SPY |
|---|---|---|
| `b6m-1` | 2019-09-20 → 2020-03-23 | −25.3% |
| `b6m-2` | 2021-12-15 → 2022-06-16 | −22.1% |
| `b6m-3` | 2018-06-25 → 2018-12-24 | −13.5% |
| `b1y-1` | 2021-12-28 → 2022-12-28 | −21.0% |
| `b1y-2` | 2019-03-22 → 2020-03-23 | −20.2% |
| `b1y-3` | 2015-02-11 → 2016-02-11 | −11.6% |

Arm B exists to separate *horizon* from *regime*, and it is **selected on the outcome variable** —
that is exactly the selection effect round 4 was about. It is therefore never pooled into Arm A's
medians, and any card that looks good only in Arm B has demonstrated that it is a hedge, not that it
is a strategy.

Nine of the 27 windows have a falling benchmark.

## 3. The metric had to change, and this is the round's real harness work

**Adjusted excess is not comparable across horizons.** It is
`total_return − capital_exposure × benchmark_return`, and the benchmark term is +259% over `h10y-2`
and +6.0% over `h6m-6`. Taking a median of a card's 6-month and 10-year numbers is arithmetic on two
different units. Rounds 1–4 never had to notice this because every window was within a factor of six
of every other; the ladder spans a factor of twenty.

Round 5 therefore reports **annualized** adjusted excess:

```
annualized_return           = (1 + total_return) ** (1 / years) - 1
annualized_adjusted_excess  = annualized_return - capital_exposure * annualized_benchmark
```

with per-horizon medians rather than one median across the matrix, and the raw figures still
available beside them. A card is scored **within** each horizon and then compared across horizons —
never averaged over them.

**The gate is per horizon: 2 run windows minimum.** The 10y rung only has two, so two is the floor
that keeps every rung scorable. A whole-matrix gate would let a card clear on twelve short windows
and be reported as if it had a long-horizon result.

## 4. The field: 15 cards, and no new submissions

Round 4's 14, plus **`A-rotation`** reinstated as the high-exposure comparator its control arm earned
it. No new analyst cards this round.

That is deliberate. Round 5 is a **measurement study on a fixed field**, not a submission round.
Adding new cards would confound the horizon question with a field change, and the programme has just
spent a round learning what happens when two variables move at once. The next submission round should
come after round 6 has chosen the paper-trading four, briefed on whatever the ladder shows.

## 5. What round 5 cannot settle

- **It is not out-of-sample.** No calendar time has passed since round 3, the design cutoff has not
  moved, and every window here ends on or before 2026-02-13. The ladder brings windows the *cards*
  have not seen; it does not bring data the *analysts* could not have studied. The walk-forward
  begins when real time has elapsed.
- **The long rungs are nearly one sample.** See §2. Two overlapping decades is not a distribution.
- **The era is one era.** Every window is drawn from 2013–2026. A ten-year result here is a result
  about *this* decade, and the 2000s or the 1970s would very likely rank the field differently. The
  6m and 1y rungs at least sample nine falling windows; the 10y rung samples none.
- **Annualizing does not make a 6-month result as trustworthy as a ten-year one.** It makes them the
  same *units*. A 6-month window's annualized figure has roughly twenty times the sampling error of
  the decade's, and the per-horizon tables must be read with that in mind rather than as a league
  table across rungs.

## 6. What this feeds into

Round 6 selects **four** cards for the live paper desk. Round 5 exists to give that decision the one
piece of evidence it has never had: whether a card's ranking survives a change of holding period, and
whether the cards that win at six months are the same ones that win at ten years. If they are not,
the paper desk — which holds positions forward indefinitely — should be picked on the long rungs, and
four rounds of short-window leaderboards were answering the wrong question for it.

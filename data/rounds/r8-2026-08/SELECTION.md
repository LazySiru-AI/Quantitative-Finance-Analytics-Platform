# Round 8 — re-selection under the reference-signal rule

**Not investment advice.** Simulated books on a paper account, selected to be informative to watch.
I am not a licensed financial adviser and none of this is a recommendation about real capital.

---

## The rule, as executed

Rounds 6 and 7 selected the four desk cards as if they were **one portfolio**: a rho <= 0.70
return-correlation cap (round 6) and a 25%-of-book holdings-overlap cap (round 7), both applied
pairwise across every seated card. Round 7's own correction (`data/rounds/r7-2026-08/SELECTION.md`
section 9) measured the price of that premise: the overlap cap dropped `A-rotation` (+37.36%
out-of-sample) in favour of `H-trend-diversified` (-3.14%), and round 7's roster returned +8.76%
out-of-sample against round 6's +17.39% and SPY's +12.84%.

That premise is retired. The desk's owner reads each of these four cards as an **independent
reference signal** for what to buy in a single real account. Nobody holds all four; they do not need
to be uncorrelated with each other.

**Retired outright, not amended:**

- **The return-correlation cap.** It answered "would this pair make one portfolio too concentrated,"
  a question that does not apply to four cards nobody combines.
- **The holdings-overlap cap.** Same reasoning, and round 7 section 9.2 already priced its cost:
  roughly nine points against round 6's roster, four against holding SPY, over the only out-of-sample
  window the programme has.
- **The book veto** (rounds 6-7: reject a selection if the combined book underperforms the best single
  card). Four independent references are not a book. There is nothing to veto, so this round computes
  no combined-book figure at all.

**New constraint — distinctness of idea, not of return:**

- At most **one card per `StrategyCard.discipline`.**
- At most **one card per base family** — `B-momentum`, `B2-hold-90`, `B3-concentrated` and
  `B4-tight-stop` count as one card. They differ by a single sizing/stop decision and round 5 measured
  them within 0.45 points of each other at ten years (round 6 section 1 flagged the same thing).

Three agents independently saying "buy NVDA" is a signal under the reference framing, not a defect —
so nothing here polices *what* the four cards hold in common, only how many of them are allowed to be
the same *kind* of decision.

**Gates, unchanged from round 7:**

- **Gate A.** Positive median annualized adjusted excess at both the 5y and 10y rungs of round 5's
  ladder, against both SPY and QQQ.
- **Gate L (liveness).** At least one trade in the out-of-sample window 2026-02-17 to 2026-08-18.

**Ranking.** Among cards clearing both gates, rank by out-of-sample adjusted excess versus QQQ — the
only genuinely out-of-sample evidence the programme has, and the more demanding of the two benchmarks
for this field. Take the best card in each of the distinct discipline/family groups the survivors
span, up to four.

---

## The result

| rank | card | discipline | out-of-sample adj. vs QQQ | why it won its group |
|---|---|---|---|---|
| 1 | **`B-momentum`** | momentum (family) | +20.98% | **seated by the desk owner over the ranking's pick — see section 6** |
| 2 | **`A-rotation`** | pairs-rotation | **+24.28%** | the card round 7's overlap cap dropped; the correction stands |
| 3 | **`c07-chop`** | mean-reversion | **-0.77%** | only mean-reversion candidate to clear Gate A |
| 4 | **`H-trend-diversified`** | trend | **-5.49%** | beats `C-trend`'s -6.02% within the trend discipline |

**Dropped: `B3-concentrated`, `B2-hold-90`, `B4-tight-stop`, `C-trend`, and every card that failed Gate A**
(`c09-convex`, `c11-breakout`, `c14-riskmanaged-wide`, `c18-meanrev`, `c19-volatility`, `c20-rotation`,
`c21-uncorrelated`).

**The momentum seat was decided by a person, not by the ranking.** Applying this round's rule as
written selects `B3-concentrated` — a variant of `B-momentum` holding fewer, more concentrated
positions, which returned +51.63% raw through the out-of-sample window against `B-momentum`'s
+31.97%. The desk owner seated `B-momentum` instead. Section 6 records the override and the evidence
on both sides; the ranking above is left showing what the rule produced, so the two are not
confused.

---

## 1. Gate A — recomputed from round 5's ladder

Median annualized adjusted excess at the 5-year rungs (`h5y-1/2/3`) and 10-year rungs (`h10y-1/2`),
against both SPY (the engine's own `benchmark_return`) and QQQ (recomputed from the bar store's own
QQQ history over each window's dates, per this round's brief). Loaded from
`data/rounds/r5-2026-08/results` (run tag `r1`) via `strategy-program/tools/score.py`, not copied from
any prior round's document.

| card | 5y SPY | 5y QQQ | 10y SPY | 10y QQQ | verdict |
|---|---|---|---|---|---|
| `B-momentum` | +14.87% | +9.29% | +7.59% | +3.92% | pass |
| `B4-tight-stop` | +15.12% | +7.79% | +7.14% | +3.51% | pass |
| `B2-hold-90` | +13.05% | +8.39% | +7.56% | +4.60% | pass |
| `A-rotation` | +10.46% | +3.39% | +5.28% | +0.63% | pass |
| `B3-concentrated` | +8.33% | +7.33% | +5.78% | +1.90% | pass |
| `C-trend` | +7.35% | +2.53% | +4.45% | +1.28% | pass |
| `H-trend-diversified` | +4.82% | +1.89% | +3.35% | +1.32% | pass |
| `c07-chop` | +3.28% | +2.65% | +0.85% | +0.27% | pass |
| `c19-volatility` | +2.86% | +1.87% | -1.75% | -2.56% | **fail** |
| `c09-convex` | -0.49% | -1.38% | -0.46% | -0.98% | fail |
| `c18-meanrev` | -1.06% | -2.65% | -0.88% | -1.77% | fail |
| `c21-uncorrelated` | -2.38% | -4.15% | -1.40% | -3.09% | fail |
| `c14-riskmanaged-wide` | -2.83% | -5.35% | -1.79% | -3.25% | fail |
| `c11-breakout` | -3.96% | -7.28% | -2.39% | -4.90% | fail |
| `c20-rotation` | -4.28% | -7.14% | -3.77% | -6.12% | fail |

**Eight survivors, the same eight round 6 found** (`data/rounds/r6-2026-08/SELECTION.md` section 1):
the four `B*` momentum variants, `A-rotation`, `C-trend`, `H-trend-diversified`, `c07-chop`.

**Numbers differ from round 6's published table, in the SPY columns only, by no more than 0.08
points** (e.g. `B-momentum` 5y-SPY here reads +14.87% against round 6's +14.79%; `B4-tight-stop`
10y-SPY reads +7.14% against +7.14% unchanged, while its 5y-SPY reads +15.12% against +15.04%). Every
recomputed QQQ figure matches round 6's published number exactly.

**Cause, established after this round was scored: the two computations anchor the SPY benchmark
differently, and round 5 already documented it.** Round 6's SPY column used the engine's own
`benchmark_return`, which is measured over the sessions the run actually traded; this round's
recomputation prices SPY from the bar store over each window's calendar dates. Measured directly on
the five 5y/10y ladder windows the two differ by a **maximum of 0.124 and a mean of 0.090 annualized
points** — and `data/rounds/r5-2026-08/REPORT.md` section 3 recorded the same effect across all 21
ladder windows at a maximum of 0.85 and a mean of 0.25 points, for the same reason. The QQQ columns
match exactly because both rounds priced QQQ the same way, from the store.

So it is not an input change and not a reproducibility failure: it is one benchmark measured two
defensible ways. Round 5's report reached the same conclusion and resolved it by pricing every
benchmark identically within a single table. Anything comparing a SPY figure across rounds should
state which anchor it used.

## 2. Gate L — the out-of-sample tournament, run fresh for this round

Run directly, not read from round 7's document: fifteen staged cards through
`app.tournament --start 2026-02-17 --end 2026-08-18` against the `pro-investor-01` persona. Over this
window the bar store prices **QQQ at +19.33%** and **SPY at +12.39%**, and every adjusted-excess
figure below is computed against those.

Round 7's document reports +19.20% and +12.84% for the same window. **That is not a data change — the
store is byte-identical, SPY still ending at 2026-08-18 with 8,445 rows — it is three anchors for one
period.** +12.39% runs from the 2026-02-17 close, +12.57% (round 7 section 9's split table) from the
2026-02-13 close on the other side of the design cutoff, and +12.84% is the engine's own
`benchmark_return` over the sessions its run actually traded. Each is defensible; none is a revision
of another. This is the same anchoring effect section 1 identifies in the Gate-A columns, showing up
a second time in the same round, which is why the recommendation for round 9 is to state the anchor
rather than to chase the number.

| card | return | adj. vs SPY | adj. vs QQQ | exposure | trades | max DD | liveness |
|---|---|---|---|---|---|---|---|
| `B3-concentrated` | +51.63% | +44.07% | **+39.83%** | 61.0% | 6 | -28.50% | pass |
| `A-rotation` | +37.36% | +28.97% | **+24.28%** | 67.7% | 29 | -16.87% | pass |
| `B-momentum` | +31.97% | +24.93% | +20.98% | 56.9% | 11 | -25.23% | pass |
| `B4-tight-stop` | +31.97% | +24.93% | +20.98% | 56.9% | 11 | -25.23% | pass |
| `B2-hold-90` | +29.89% | +23.08% | +19.27% | 54.9% | 12 | -21.01% | pass |
| `c20-rotation` | +5.30% | +0.48% | -2.22% | 38.9% | 32 | -11.94% | pass |
| `c18-meanrev` | +2.02% | -0.61% | -2.08% | 21.2% | 56 | -3.84% | pass |
| `C-trend` | +1.87% | -3.19% | -6.02% | 40.8% | 10 | -17.39% | pass |
| `c11-breakout` | +0.90% | -1.21% | -2.39% | 17.0% | 2 | -1.35% | pass |
| `c07-chop` | +0.22% | -0.42% | **-0.77%** | 5.2% | 3 | -2.04% | pass |
| `c09-convex` | +0.10% | -0.12% | -0.24% | 1.8% | 2 | -0.36% | pass |
| `c14-riskmanaged-wide` | 0.00% | 0.00% | 0.00% | 0.0% | **0** | 0.00% | **FAIL** |
| `c19-volatility` | -0.14% | -0.43% | -0.59% | 2.3% | 1 | -1.37% | pass |
| `H-trend-diversified` | -3.14% | -4.65% | **-5.49%** | 12.2% | 7 | -5.21% | pass |
| `c21-uncorrelated` | -5.28% | -6.71% | -7.51% | 11.5% | 7 | -7.63% | pass |

Only `c14-riskmanaged-wide` fails Gate L (zero trades), and it already fails Gate A, so no gate
interaction changes the outcome. Every one of the eight Gate-A survivors clears Gate L.

## 3. Ranking and the distinctness constraint

The eight Gate-A-and-Gate-L survivors span exactly four discipline/family groups, so the distinctness
constraint and the ranking together determine the roster without any further tie-break needed:

| group | members (Gate A survivors) | best by adj. vs QQQ | runner-up in group |
|---|---|---|---|
| momentum (family) | `B-momentum`, `B2-hold-90`, `B3-concentrated`, `B4-tight-stop` | **`B3-concentrated`** +39.83% | `B-momentum`/`B4-tight-stop` +20.98% |
| pairs-rotation | `A-rotation` | **`A-rotation`** +24.28% | — (only member) |
| trend | `C-trend`, `H-trend-diversified` | **`H-trend-diversified`** -5.49% | `C-trend` -6.02% |
| mean-reversion | `c07-chop` | **`c07-chop`** -0.77% | — (only member) |

Four groups, four seats: nothing was traded off against a card from a different group, because no
group is short a candidate and none has a spare seat to give up.

## 4. What retiring the caps changes, and what it costs

**What it changes.** `A-rotation` re-enters the desk. Round 7's overlap cap removed it specifically
because it held NVDA, AVGO and TSM at 99% of book, 45% shared with `B-momentum` — a fact about the
combined book's concentration, not about `A-rotation`'s quality as a standalone signal. Read as a
reference rather than a component, that overlap is no longer a reason to exclude it, and on the
out-of-sample evidence it is the programme's second-best card.

**What it does not change.** The one-per-family rule still forces a choice among the four momentum
variants, and this round that choice fell on `B3-concentrated` over `B-momentum` itself —
`B-momentum`'s exit is a consequence of the family rule, not of the caps' retirement. Likewise
`C-trend` is still excluded (now by the discipline rule rather than the overlap rule), because
`H-trend-diversified` posted the better out-of-sample number within the same discipline.

**What it costs.** Nothing measurable against round 7's roster on this evidence — every retired cap
was actively costing the desk money (section 9.2 of round 7's document), so removing them and
re-ranking on out-of-sample adjusted excess only recovers value here. The cost of the *new* rule is
narrower and real: a card can be dropped from the desk purely for resembling a seated card in
*discipline*, even where the two would have made an excellent, genuinely diversifying pair by every
overlap and correlation measure this programme has used before. `C-trend` and `H-trend-diversified`
are not measured against each other on holdings overlap or return correlation at all this round; one
of them loses the seat solely because `StrategyCard.discipline` labels them the same kind of decision.
Whether "kind of decision" is the right axis to police, rather than "kind of holding," is a judgement
call this round makes rather than proves.

**What it does not do.** It does not make the four cards any less likely to move together in practice
— they may hold the same names on the same day, exactly as `B3-concentrated`, `A-rotation` and
`H-trend-diversified` might all be long NVDA at once. Under the reference framing that is not a defect
in the selection; it is only a defect if the reader forgets that nobody holds all four and treats the
paper desk's combined equity curve as if it meant something a single-account investor could
experience. It cannot, by construction, any more than it could when the caps were in force — the
combined curve was never real money either way.

## 5. What this is not evidence of

- **Still not a portfolio recommendation, and now explicitly disclaimed as one.** With the caps gone,
  a reader who assembles all four into one book is doing something this round's rule was written
  specifically to not evaluate. No combined-book figure is computed anywhere in this document.
- **Not evidence that `B-momentum` degraded.** It cleared every gate this round exactly as it has
  every round; it lost a seat to a variant of itself on a six-month sample, which round 6 already
  warned was too close a race to resolve on ten years of ladder evidence, let alone six months of
  out-of-sample trading.
- **Still one out-of-sample window.** 2026-02-17 to 2026-08-18 is the only period nobody could have
  designed a card against, and it is 127 sessions — round 7 section 9.4 already flagged that this is
  roughly halfway to the ~250 sessions the live desk needs before its own matrix can be trusted as a
  ranking input (fix 4, still deferred). A ranking built entirely on this one window, as this round's
  rule specifies, inherits whatever is idiosyncratic about this particular six months — a period that
  happened to reward concentrated momentum broadly.
- **The Gate-A/round-6 numeric drift (section 1) is now explained** -- the engine anchors its SPY
  benchmark to the sessions it traded and a calendar-date recomputation does not, an effect round 5's
  report had already measured. The stored results are reproducible; the benchmark was being read two
  ways. Section 1 carries the numbers.

---

## For whoever runs round 9

1. **Fix 4 (score the live desk's own matrix, weighted above backtests) is closer still** — the desk
   will have accumulated more live sessions by then, and this round's ranking rests entirely on the
   same 127-session out-of-sample window round 7 used, not on anything new.
2. **Revisit whether `discipline` is the right distinctness axis.** Section 4 names the specific case
   (`C-trend` vs `H-trend-diversified`) where it excludes a pairing that overlap and correlation
   measures alone would not have flagged. If a future round wants "different kinds of holding" rather
   than "different kinds of decision," that is a different, and separately pre-registerable, rule.
3. **State the benchmark anchor wherever a SPY figure crosses a round boundary.** Section 1's drift
   was two defensible measurements of one index, not a data problem -- but it cost a round's attention
   to establish that, and it will cost the next one too unless the tables say which anchor they used.


---

## 6. The momentum seat: an override, recorded as one

This round's rule ranks on out-of-sample adjusted excess versus QQQ, and on that criterion
`B3-concentrated` wins the momentum seat outright. **The desk owner seated `B-momentum` instead.**

The number that argues against the decision, stated first:

| | out-of-sample raw | adj. vs QQQ | max drawdown |
|---|---|---|---|
| `B3-concentrated` | **+51.63%** | **+39.83%** | −28.50% |
| `B-momentum` | +31.97% | +20.98% | **−25.23%** |

The evidence the owner weighted instead:

| | worst rank across r2 / r4 / r5-ladder | 10y adj. vs SPY | 10y adj. vs QQQ |
|---|---|---|---|
| `B-momentum` | **3** (ranks 3 / 2 / 2) | **+7.59%** | **+3.92%** |
| `B3-concentrated` | 5 (ranks 2 / 1 / 5) | +5.78% | +1.90% |

**Both readings are supported by the programme's own numbers, and neither is obviously wrong.** The
ranking rests on one 127-session window that, as section 5 notes, happened to reward concentration
broadly — `A-rotation`, `B3-concentrated` and every `B*` variant all posted large gains in it. The
long-rung figures rest on the round-5 ladder, whose top rung is effectively a single overlapping
decade sample and 95% in-sample. Neither body of evidence is strong enough to overrule the other.

What settles it is the desk's purpose rather than either number: it holds forward indefinitely and is
read as a standing reference, so the card that has never been worse than third across three different
matrices is the more useful thing to watch than the card that won the most recent six months.

**It is written up as an override rather than folded into the rule.** A selection rule quietly
restated to produce the answer someone wanted is not a rule, and `ROUND-6-PLAN.md` opens by saying
exactly that. The rule's own output stands in section 1's ranking; this section is what changed.

For round 9: if long-horizon stability is what the desk should be selected on, that belongs *in* the
rule — a rank-stability gate, or ranking on the 5y/10y rungs rather than the out-of-sample window —
pre-registered before the next round's numbers exist. Making it a rule is how this stops being an
override.

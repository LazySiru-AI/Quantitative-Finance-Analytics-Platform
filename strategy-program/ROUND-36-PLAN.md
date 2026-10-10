# Round 36 — does relative strength decide the slot? `rank_by` against the ordering-noise floor

Pre-registered **2026-09-08**, before any measurement in this round exists. Nothing below was written
with sight of a result, and **the round has not been run.**

Not investment advice. Every number this round will produce is a backtest on price-only bars with no
dividends, on a universe held disjoint from the taxable books for a tax reason, not a return reason.
The honest prior is in §10: the most likely outcome is that nothing separates.

---

## 1. The question

**When more names qualify than there are slots, does choosing by relative strength change the result
by more than the ordering-noise floor — and is "strongest first" any different from "weakest first"?**

`PROTOCOL.md` §7 states the problem in one paragraph and this round is entirely about that paragraph:

> When more symbols qualify than there are slots, something has to choose between them. For a card
> that leaves `rank_by` unset — which is every card frozen before that field existed, and therefore
> every result this programme has published to date — that chooser is the order the universe array is
> written in. Re-running one identical card under twelve orderings moved its three-year return across
> a **53.9-point spread, σ = 21.2 points**.

`backend/app/paper/library/README.md` carries the table that measurement came from
(`docs/tournament/results/a07-order/`): best random ordering +161.83%, relative-strength ordering
+158.74%, median random +142.21%, alphabetical-as-submitted +145.08%, worst random +107.98%.
**Relative strength ranked 9th of 10 against random draws — better than the alphabet, and inside the
noise.** That is the *only* measurement of ordering-by-strength this programme owns, it was taken on
nine semiconductor names under one card, and it has never been repeated.

Two things have changed since, and together they make the question askable properly.

**First, the engine grew the operator.** `StrategyCard.rank_by` now names the chooser explicitly. Its
docstring is emphatic about what that does and does not buy:

> The one place this engine compares symbols to each other rather than to their own bars. […] What it
> removes is the arbitrary part of a choice the engine was already making silently.

`PROTOCOL.md` §7 adds the caveat that matters here: naming the chooser "does **not** make the spread
above disappear, and it is not itself evidence of an improvement." Nothing in the programme has tested
it. This round is that test.

**Second, round 17 measured ordering noise on a *different* universe and got a different answer.**
`ROUND-18-PLAN.md` §3 records it: "That replication found ~1pp of ordering noise on this universe" —
eleven (later nine) sector SPDRs — against the 21.2pp measured on nine semiconductor names. Both
numbers are real. The obvious reading is that **ordering noise scales with the universe's
cross-sectional dispersion**: when the candidates are near-identical, which one gets the slot barely
matters; when they are nine semis in a momentum regime, it decides the result. That reading has never
been tested on a third universe, and it is the second thing this round measures.

**And there is a card whose thesis depends on the answer.** `c20-rotation`'s thesis says this engine
"has no cross-symbol operator … so 'rotation' here is produced entirely by the universe, the fixed
fill order, and a 3-of-6 slot cap," and calls its own fill order "an arbitrary-but-reasoned tiebreak"
rather than dressing it up as a finding. `rank_by` is precisely the feature that changes that claim.
This round runs **that card's filter** so the answer lands on the card that raised the question.

## 2. What the engine actually does with the slot

Quoted rather than paraphrased, because the whole design rests on it.

**The fill order *is* the selection rule.** `app.tournament.runner._ordered_entry_candidates`:

> **This function is the whole point of `rank_by`.** The runner fills entries until the slots run
> out, so whichever order it walks the universe in *is* the selection rule whenever more names qualify
> than fit. Left unranked that order is the order the array was typed in, worth a measured 53.9-point
> spread over twelve orderings of one identical card.

**Unset reproduces the old path exactly, not merely equivalently.** Same function:

> An empty table — the card left `rank_by` unset — returns `universe` unchanged and byte-for-byte
> reproduces every result recorded before this field existed.

That is what makes the `canonical` and `reversed` arms a clean control: they are the *pre-`rank_by`*
engine path, twice, with the same names in two orders.

**Set, the sort is highest-first, stable, and deterministic.** Same function:

> Ranked, the order is: every symbol with a key, highest key first; then every symbol without one.
> Ties and unknowns keep universe order, because the sort is stable over a list already in that order.

Highest-first with no direction field is why "weakest first" must be written as a negation
(`0 - close / sma(200)`), and the `rank_by` docstring says so: "negation inverts it … so there is
exactly one way to express any order and no second direction field to disagree with the expression."

**An unknown key is not a zero.** `_RankTable`:

> Through an indicator's warmup a symbol has no key — `close / sma(200)` is `NaN` for a name with 150
> bars of history. That is not "ranks lowest"; it is "this run cannot say", and
> `_ordered_entry_candidates` puts those names behind every ranked one in universe order.

This matters for the `weak` arm specifically: a warmup `NaN` would sit *behind* the ranked names in
both the `strong` and `weak` arms, so a universe with names still warming up would contaminate the
contrast asymmetrically. §6 shows it does not happen here — every name clears the 200-day warmup in
every window, including `gfc`.

**The key is guarded exactly as the rules are.** `runner._guard_card`, around the `kind="ranking"`
call:

> The ranking key is guarded exactly as the two rules are, and for a sharper reason: a non-causal key
> would pick which name gets a scarce slot using a bar from after the decision, and would do it while
> the entry rule beside it stayed clean and passing.

So a rank key that could see the future is refused at run time, per symbol, before the card trades.
`StrategyCard` additionally refuses an unparseable key at load. Both were exercised before this field
was frozen — see §6.

## 3. The field — five orderings × two slot caps, 10 cells

Authored by `strategy-program/tools/round36.py`. **Exactly one thing varies within a slot arm: which
qualifying name takes a scarce slot.**

| arm | `universe` | `rank_by` | what it is |
|---|---|---|---|
| `canonical` | pinned order | *(unset)* | the arbitrary written order — the pre-`rank_by` engine path |
| `reversed` | `tuple(reversed(UNIVERSE))` | *(unset)* | the same names, the same path, the order written backwards |
| `strong` | pinned order | `close / sma(200)` | strongest first — the key the `A-rotation` study used |
| `weak` | pinned order | `0 - close / sma(200)` | weakest first — the **exact negation** of `strong` |
| `volunits` | pinned order | `(close - sma(50)) / atr(14)` | strongest first, in volatility units |

Crossed with a slot cap of **2** and **4** on eight names → 10 cells, ids `r36-<ordering>-k<slots>`.

**Held identical across all ten cells:** entry `close > sma(100) and rsi(14) > 50 and rsi(14) < 75`;
exit `close < sma(100) or rsi(14) < 40`; `stop_loss_pct` 0.10; no take-profit; `max_hold_days` 150;
the universe *as a set*; `purpose = roth`; `designed_through = 2026-02-13` (the programme's
`DESIGN_THROUGH`); and **maximum capital at risk, at 50%** (2 × 0.25 = 4 × 0.125).

**Why that rule and not a new one.** It is `c20-rotation`'s absolute filter, character for character,
taken from `backend/app/paper/library/candidates/c20-rotation.json`. Using an existing card's rule
means no threshold in this round was chosen with this round's question in view — every one of them was
frozen before the question was asked. The round-18 fixed entry (`close > sma(200)` plus an
`ema(10)/ema(30)` cross) was the alternative and was rejected for one reason: it is a *trend-following*
entry whose qualifying set is heavily correlated with the `close / sma(200)` ranking key, so the entry
would pre-select for the thing the key ranks on and blunt the contrast the round exists to measure.
`c20`'s filter is an RSI band with a ceiling — it explicitly *excludes* the most extended names
(`rsi(14) < 75`) — so the qualifying set is not already sorted by strength.

**Why sizing was equalised rather than held constant.** `PROTOCOL.md` §4 measures `adjusted_excess` as
scaling with exposure (Pearson r = +0.797 against GFC adjusted excess across ten cards) and requires
any card more than 2× off the field median exposure to be flagged. Holding `position_pct` constant at
0.15 would have made the k=4 arm carry twice the k=2 arm's capital and put the two arms on
non-commensurable footing. Equalising the ceiling costs the other thing, and it is stated here rather
than discovered later: **slot count and position size move together, so a *level* difference between
the k=2 and k=4 arms cannot be attributed to the cap alone.** The round does not need that
attribution — every contrast it decides on is computed *within* a k arm, where sizing is identical.

**Parameter budget (`PROTOCOL.md` §3 rule 3, ten free numbers per card).** Counted as *choices*, not
literal tokens: the sma period 100 and the rsi period 14 are each one decision used in two rules.

| # | free number | where |
|---|---|---|
| 1 | sma period 100 | entry and exit |
| 2 | rsi period 14 | entry and exit |
| 3 | rsi upper 75 | entry |
| 4 | rsi lower 50 | entry |
| 5 | rsi exit 40 | exit |
| 6 | `stop_loss_pct` 0.10 | bracket |
| 7 | `max_hold_days` 150 | hold cap |
| 8 | `max_positions` (2 or 4) | slot count |
| 9 | `position_pct` (0.25 or 0.125) | position size — pinned by #8 to the 50% ceiling |
| 10 | the `rank_by` period (200, or 50 for `volunits`) | ranking key, ranked arms only |

**9 for the two unranked arms, 10 for the three ranked arms — at the budget, with zero headroom.** That
is deliberate and it is also the reason no sixth ordering was added: any further key would have to
spend a number this field does not have. `rank_by` is not in §3's enumerated list (the clause predates
the field); it is counted anyway, because a period chosen for a ranking key is exactly as free as one
chosen for an entry rule. The leading `0 -` in the weakest key is the negation *idiom* the engine
requires, not a chosen parameter, and is not counted. `tests/test_round36_field.py::TestParameterBudget`
asserts the ≤10 bound.

## 4. The universe, and the constraint that picked it

```
XME  XRT  XHB  XSD  XOP  XBI  ITA  VNQ
```

SPDR S&P Metals & Mining, Retail, Homebuilders, Semiconductor, Oil & Gas E&P and Biotech; iShares US
Aerospace & Defense; Vanguard Real Estate. **Identical to the sibling industry round, 34**, and pinned
so the two rounds stay comparable. It is written **once**, in `round36.py`'s `UNIVERSE`; the reversed
arm is `tuple(reversed(UNIVERSE))`, derived in code, so the two orderings are provably the same set —
a hand-copied second tuple with one ticker mistyped would silently turn this round's cheapest control
into a universe comparison. `tests/test_round36_field.py::TestUniverseIsOnePinnedSet` pins both.

**Why industry ETFs at all.** The round needs a universe with *more* cross-sectional dispersion than
round 17's broad sector SPDRs and *less* than nine semiconductor names — otherwise it re-measures one
of the two existing points rather than adding a third. Industry-level baskets are the natural middle:
mechanically defined, they do not die, they were not chosen by looking at returns, and they disperse
(homebuilders against biotech against oil E&P) far more than XLP against XLV.

**The binding constraint is tax, not returns.** Every card carries `purpose = roth`, and
`app.tournament.purposes.find_disjointness_violations` enforces `THREE-PURPOSES-PLAN.md` §6's
invariant: no symbol traded by a Roth-purpose card may appear in the universe of any `savings`- or
`trading`-purpose card. `round36.py` recomputes the taxable ticker set **from the live library at
build time** — all four `load_library` tiers *plus* `library/allocation/` and `library/ladder/`, which
`load_library` does not walk and which between them hold AGG, BIL, QLD, SCHD and SGOV — and **refuses
`--write` on any violation**. As of 2026-09-08 that is 61 purposed cards and 84 taxable tickers; the
intersection with this universe is empty.

**Substantial identity, stated because it would be dishonest to leave implied.** XSD's index is not
SOXX's or SMH's, and XOP's is not XLE's — but that is an argument about economics, and what was
checked is tickers. `purposes.py` says this at length and it is not softened here: IRC §1091 turns on
securities being *substantially identical*, not on symbols matching, and "nothing here should be read
to imply that a roster clearing this check is safe under §1091 — only that the one specific, checkable
thing this function checks did not fire." **This round makes no §1091 safety claim.**

**Nothing in this round reads a ledger.** The cards read the Parquet/DuckDB bar store and nothing
else: no `data/accounts.toml`, no `data/sectors.toml`, no `data/store/ledger.sqlite`, no `app.tax`.

## 5. Windows, metric, and the decision rule

**Windows and metric are unchanged**: `WINDOWS.md`'s eight main windows, SPY as each window's own
benchmark, ranked on median `adjusted_excess` per `PROTOCOL.md` §4. The regime gate is five of eight
(§3 rule 7); §6 shows all ten cells clear it at 8 of 8.

**The floor is 21.2 percentage points.** Round 17 declined to lower it after measuring ~1pp of
ordering noise on sector SPDRs, and `ROUND-18-PLAN.md` §3 inherited that decision explicitly. This
round inherits it too — and note the awkward fact squarely: **this round is measuring the very
quantity the floor is made of, on a third universe.** It therefore cannot use its own result to lower
its own bar. Whatever this round measures is a *new datapoint for a future round to set a floor from*,
never a reason to re-read this round's own margins against a smaller number. That sentence is here so
it cannot be quietly forgotten once the numbers exist.

**Simulated spreads under pure noise at σ = 21.2pp** (400,000 draws, seed 36), for reading any spread
this round produces:

| comparison | E[max − min] | 95th percentile |
|---|---|---|
| one pairwise contrast (2 cells) | 23.9pp | 58.7pp |
| the five orderings inside one slot arm | 49.3pp | 81.8pp |
| all ten cells | 65.3pp | 94.8pp |

A single pre-specified pairwise contrast needs **|diff| > 58.8pp** to clear 95% under that σ — the same
arithmetic and the same figure `ROUND-17-PLAN.md` §4 quotes, reproduced independently here.

### The decision rule, stated before any number exists

**`rank_by` carries slot-level information on this universe if and only if all three hold:**

1. **strongest-first minus weakest-first, on median `adjusted_excess` across the eight main windows,
   exceeds 21.2pp**, at the same slot cap (`r36-strong-k2` − `r36-weak-k2`, and/or the k4 pair); **and**
2. **the sign of that difference is the same in at least five of the eight windows** — the same
   5-of-8 proportion the regime gate uses, so the result is not one window carrying a median; **and**
3. **it survives Benjamini–Hochberg across every cell run in this comparison — denominator 10**, per
   `PROTOCOL.md` §3 rule 8. Not 6 (the ranked cells), not 2 (the pair being quoted). All ten cells
   were run in this comparison and all ten are in the denominator.

**Anything less is reported as inside the floor, in those words.** A strong−weak difference of 15pp is
not a small finding; it is not a finding.

**Nothing will be promoted from this round in either direction.** It is a measurement study, like
rounds 15, 16, 17 and 18. `PROTOCOL.md` §6(b) already forbids a promotion on a margin inside the
floor, and a card here that cleared the floor would still need two consecutive rounds on differing
window sets before it could become a candidate.

**The secondary contrast, decided by the same rule.** `canonical` − `reversed`, at each slot cap, is
this round's direct measurement of ordering noise on this universe: identical rule, identical names,
identical sizing, identical engine path, opposite order. It is reported as a **magnitude, |diff|**, not
as a signed result — neither order is a hypothesis, so a sign would be meaningless.

**The `volunits` arm is a spelling check, not a third hypothesis.** If relative strength carries
information, two reasonable spellings of "how far above trend, strongest first" should not disagree by
more than the floor. `|strong − volunits|` above the floor while `|strong − weak|` sits below it would
say the *spelling* is doing the work — a finding about noise, not about strength — and would be
reported that way.

## 6. Eligibility and guard rehearsal — checked before the freeze, not after

First stored daily bars: XHB / XSD / XBI 2006-02-06, ITA 2006-05-05, XME / XRT / XOP 2006-06-22, VNQ
2004-09-29. `strategy-program/tools/windows.py --cards data/rounds/r36-2026-09/cards` reports **8 of 8
main windows eligible, gate PASS, for all ten cards.** (The two `inv-2000` / `inv-2006` investing-
horizon windows fail on 2006 first bars; neither is a main window and neither counts toward the gate.)

**One quirk a reader must know about, because `windows.py` cannot see it.** `eligible_windows`
computes warmup from `max_indicator_period(card.entry)` and `max_indicator_period(card.exit)` only —
it does **not** look at `rank_by`. Six of these ten cards carry a `sma(200)` or `sma(50)` ranking key
attached to a 100-day rule, so `windows.py`'s eligibility figure is computed on a shorter warmup than
the runner will actually demand of them. That gap was closed by hand rather than assumed away: every
expression in the field was run through the real `app.backtest.guards.check` against the real bars, at
the tightest window in the matrix (`gfc`, first decision 2007-10-09, `lookback_days=720`, which is
what `runner._guard_card` uses), for all eight symbols:

```
XME bars=327  entry=passed  exit=passed  strong=passed  weak=passed  volunits=passed
XRT bars=327  entry=passed  exit=passed  strong=passed  weak=passed  volunits=passed
XHB bars=422  entry=passed  exit=passed  strong=passed  weak=passed  volunits=passed
XSD bars=422  entry=passed  exit=passed  strong=passed  weak=passed  volunits=passed
XOP bars=327  entry=passed  exit=passed  strong=passed  weak=passed  volunits=passed
XBI bars=422  entry=passed  exit=passed  strong=passed  weak=passed  volunits=passed
ITA bars=360  entry=passed  exit=passed  strong=passed  weak=passed  volunits=passed
VNQ bars=496  entry=passed  exit=passed  strong=passed  weak=passed  volunits=passed
```

The binding case is 327 bars against a 200-period warmup plus the 40 post-warmup bars
`app.backtest.guards._MIN_BARS_FOR_CAUSALITY` requires — 240 needed, 327 available, ~87 bars of
headroom. **Every name therefore carries a real ranking key from the first session of every window,
so no cell ever falls back to universe order through a warmup `NaN`**, which is the contamination
§2 flags. `round36.py` additionally re-runs a store-free guard rehearsal on a synthetic causal series
on every invocation and refuses `--write` if any expression fails.

## 7. Falsifiable predictions

Stated in advance so this document can be wrong. Every one is a claim about a number that does not
exist yet.

1. **`|canonical − reversed|` on this universe is closer to round 17's ~1pp than to 21.2pp — under
   5pp at both slot caps.** The dispersion reading in §1 says ordering noise scales with how different
   the candidates are, and eight industry baskets are far less dispersed than nine semis. *Refuted if*
   either slot arm's canonical-vs-reversed magnitude exceeds 21.2pp.
2. **`strong − weak` is inside the 21.2pp floor at both slot caps.** This is the null and it is the
   round's central prediction: relative strength carries no slot-level information here, exactly as
   the `A-rotation` study's 9th-of-10 placing suggests. *Refuted if* the difference exceeds 21.2pp
   with a consistent sign in ≥5 of 8 windows.
3. **The k=2 arm shows a larger ordering spread (max − min across its five cells) than the k=4 arm.**
   Two slots on eight names binds far harder than four, so ordering has more work to do. *Refuted if*
   k=4's spread is greater than or equal to k=2's.
4. **`strong`'s worst window is `covid`, and in `covid` `strong ≤ weak` at both caps.** This is the
   pre-registered failure regime for strongest-first: `covid` is the sharpest reversal in the matrix
   and the leader is the first to break, so buying the most-extended qualifying name into February
   2020 is where strongest-first should lose most to weakest-first. *Refuted if* `strong > weak` in
   `covid`, or if `strong`'s worst window is not `covid`.
5. **The slot cap binds: within the k=2 arm, at least two orderings differ in trade count in at least
   five of the eight windows.** The non-vacuity check — see §8. *Refuted if* the arm's cells are
   identical, which would mean the round measured nothing.
6. **All ten cells clear the regime gate at 8 of 8 main windows.** Already verified in §6, before the
   run; recorded as a prediction so a run that contradicts it is a loud failure rather than a quiet
   one.

## 8. The precondition — the cap must bind, and how that is detected

**If the slot cap never binds, no ordering can matter and the round measures nothing.** This is stated
as a precondition rather than assumed, because it is the one way this design can silently fail.

The prior is good. `c20-rotation` measured its own filter's breadth over 4,994 sessions on six names:
"a median of 3 of 6 and a mean of 2.78 of 6 qualify simultaneously; at least 3 qualify on 56.4% of
sessions." Scaled to eight names that is a median of ~4 qualifying, which binds *always* at k=2 and
about half the time at k=4. But that was measured on different names, and it is a prior, not a result.

**Detection, pre-registered, in two forms:**

- **Structural, and decisive.** Runs are deterministic (`PROTOCOL.md` §8: same cards, same persona,
  same window, same store gives byte-identical results). So **if the five orderings inside a slot arm
  produce identical trade logs in a window, the cap did not bind in that window** — there was nothing
  for any chooser to choose. The report will state, per window per slot arm, how many of the five
  cells are distinct. An arm where all five collapse to one measured nothing and will be reported as
  measuring nothing, not as a null result about `rank_by`.
- **Quantitative.** `score.py`'s scorecard already carries `trades` and `capital_exposure_` per
  window. Mean `capital_exposure_` at or near the 0.50 ceiling means the book was full, i.e. the cap
  was the binding constraint; well below it means the entry filter was. Both are reported per cell.

**The two failure modes are different findings and must not be merged.** "Ordering did not matter"
and "ordering never got a chance to matter" produce the same flat table and mean opposite things.

## 9. What reproduces what — and what does not

**No cell in this round reproduces any existing frozen card**, and the near-miss is named here so a
reader cannot mistake it for one.

`r36-canonical-k4` is `c20-rotation`'s entry, exit, stop and hold cap — **on a different universe, at a
different slot count and a different position size.** It is *not* a reproduction of `c20-rotation` and
its number is not comparable to `c20`'s, in either direction. Round 18's built-in reproduction check
(`ROUND-18-PLAN.md` §2, two cells reproducing round 17's committed figures to the digit) has no
equivalent here, and the reason is worth stating: **the reproduction that would have been useful is
illegal.** Re-running `c20`'s own universe (XLP, USO, DBC, XLU, XLV, XLE) under Roth purpose would
violate the disjointness invariant §4 enforces — every one of those six names is held by a taxable
card. So this round runs without an instrument-drift check, and if its figures look strange against
neighbouring rounds, that is a hypothesis to test, not a check that failed.

What the two unranked arms *do* reproduce is the **engine path**: `_ordered_entry_candidates` returns
`universe` unchanged when `rank_by` is unset and "byte-for-byte reproduces every result recorded before
this field existed." So `canonical` and `reversed` are the old engine, twice, and any difference
between them is ordering noise and nothing else.

## 10. The honest prior

**The likeliest outcome is prediction 2 holding: `strong − weak` inside the floor.** The one existing
measurement puts relative-strength ordering 9th of 10 against random draws, `PROTOCOL.md` §7 already
says naming the chooser "is not itself evidence of an improvement," and rounds 1–33 have found no
durable edge in anything tested. A programme-wide null is the base rate here, not a disappointment.

That would still be worth having. It would convert `c20-rotation`'s honest hedge — "I am not claiming
this ordering is itself a source of edge" — from a caveat into a measurement, and it would tell every
future card author that spending a free number on `rank_by` buys tidiness rather than return.

**The result that would change the programme's direction is prediction 1 failing** — a
canonical-vs-reversed spread on eight industry ETFs that looks like 21.2pp rather than 1pp. That would
mean ordering noise does *not* fall away with broader baskets, that round 17's ~1pp was a property of
how similar the sector SPDRs are rather than of breadth, and that **every unranked card in the
library — which is all of them — carries an unquantified ~20pp of ordering exposure that nobody has
been subtracting.** That is a bigger finding than anything about `rank_by`.

## 11. What this round cannot settle

- **One entry rule.** A different filter selects a different qualifying set, and ordering can only
  matter among names that qualify. A null here is a null for `c20`'s filter on these names.
- **One universe.** By construction this is a third datapoint on the dispersion hypothesis, not a test
  of it — three universes, three ordering-noise figures, no controlled variation of dispersion itself.
  A proper test would sweep dispersion deliberately, and that is a different round.
- **It cannot separate "`rank_by` is uninformative" from "the cap did not bind hard enough."** §8's
  detector distinguishes *never bound* from *bound*, which is the coarse version; it cannot say what
  would have happened at a cap that bound harder still.
- **`rank_by` is not cross-sectionality.** Its own docstring: it "cannot express a spread, a pair, or
  an entry condition contingent on another symbol — `entry` is still evaluated per symbol in
  isolation, and a name that fails it is never ranked at all." A null here says nothing about
  cross-sectional strategies the engine still cannot express.
- **Price-only and dividend-free**, like every backtest in this programme. On REIT and energy baskets
  across a `gfc` window that omission is not small.
- **No §1091 claim.** §4. Ticker disjointness is necessary and not sufficient.
- **Nothing is promoted.** Two consecutive qualifying rounds on differing window sets would be needed
  before any cell here could become a candidate, and §5 forbids a promotion inside the floor anyway.

## 12. The run recipe

Not executed as of this writing. The store is single-writer and a round takes hours; `run_round.sh`
refuses to start when another tournament process is alive (`PROTOCOL.md` §8), and another session may
hold it.

```
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round36.py --write
bash strategy-program/tools/run_round.sh data/rounds/r36-2026-09/cards data/rounds/r36-2026-09/results
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/score.py \
    --results data/rounds/r36-2026-09/results --json data/rounds/r36-2026-09/scorecard.json
```

Reconcile run files against `FAILED` lines after every window regardless of how the run looked
(`PROTOCOL.md` §8): the runner walks past a failed card by design, so a shortfall is silent.

## 13. Honesty register

Everything a later reader could otherwise mistake, collected in one place.

1. **The round has not been run.** No number in this document is a result; §6's guard and eligibility
   output are pre-run checks on the field, not measurements of it.
2. **Pre-registered 2026-09-08**, before any measurement. `PROTOCOL.md` §2 makes the freeze the
   integrity boundary: a card edited after any result exists "is not a strategy, it is a memory of
   one."
3. **This round cannot lower its own floor** with its own ordering-noise measurement. §5.
4. **`windows.py` does not check `rank_by`'s warmup.** The 8-of-8 eligibility table is computed on the
   100-day rule, not the 200-day key. The gap was closed by a live guard run against real bars, §6 —
   but a future card with a longer key on a shorter-history universe will hit this, and `windows.py`
   will not warn about it.
5. **The k arms differ in two things at once** (slot count and position size), by choice, to hold the
   capital ceiling equal. Every decision-relevant contrast is computed within a k arm. §3.
6. **No cell reproduces a frozen card**, and the reproduction that would have been useful is barred by
   the Roth invariant. §9.
7. **The taxable ticker set is recomputed from the live library at build time**, never hardcoded, and
   `--write` refuses on a violation. The figure as of 2026-09-08 is 84 tickers across 61 purposed
   cards; a card added to the library tomorrow changes it, which is the point.
8. **Ticker disjointness is not §1091 safety.** §4.
9. **Not investment advice**, and nothing here will be seated on any book.

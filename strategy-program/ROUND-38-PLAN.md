# Round 38 — the real yield on the savings book: the programme's first macro-conditioned savings round

Pre-registered **2026-09-09**, before any measurement in this round exists. **The round has NOT been
run.** No card here has been executed over any evaluation window, no margin has been computed, and
nothing below reports an outcome. **Not investment advice.**

Authored by `strategy-program/tools/round38.py`; the frozen field is
`data/rounds/r38-2026-09/cards/*.json` (7 cards); the tests that pin the field to this document are
`tests/test_round38_field.py`.

---

## 1. Why this round is new

Two facts, both verified against the round scripts and the DSL on 2026-09-09, and together they are
this round's entire justification:

1. **Every macro round this programme has run — 21, 22, 23, 25, 30, 31, 32 — conditioned a
   `trading`-purpose `StrategyCard`.** No macro series has ever been attached to a `savings`- or
   `roth`-purpose book. The macro line was opened, measured and closed entirely on one of the three
   books, and on one of the two card shapes.
2. **Of the seven `MacroField` series in the DSL (`backend/app/rules/nodes.py`: `DGS10 T10Y2Y T10YIE
   DCOILWTICO PCEPI PCEPILFE CPILFESL`), `T10YIE` has never been combined with `DGS10`.** Round 30
   measured each of them *alone*, as a level and as a rate of change, against forward returns, and
   found both null. It never formed the difference.

Nominal minus breakeven is the **real yield** — the inflation-adjusted discount rate — and it is a
different quantity from either leg. It can be high because nominal rates are high, or because
expected inflation is low, and those are opposite macroeconomic states that the two round-30 cells
could not distinguish between. It is also the discount rate a 10–20 year savings book is actually
exposed to, which is why this is the book to test it on rather than the trading book.

So: a new quantity, on a new book, on a card shape (`AllocationCard`) that no macro round has ever
used. That is what makes this a round rather than a re-run.

## 2. The prior is a null, and this round pre-registers a null

This must be stated before anything else, because the honest reading of this programme's record is
that the macro line is closed:

- **Round 30** measured the three untouched daily series (`DGS10`, `DCOILWTICO`, `T10YIE`) as
  regime-conditional forward returns with an orthogonality-to-price control on every cell. Null.
- **Round 31** measured the remaining FRED series and closed the macro line on a null; all seven are
  measured-null across rounds 22–25/30/31.
- **Round 32** took round 31's one genuine near-miss (core CPI YoY above its 60-month trailing mean)
  to a dedicated round with a true out-of-sample half, and **it dissolved**.

Nothing about attaching a macro term to a different `purpose`, a different card shape, or a
different benchmark gives that term information it did not previously have. Changing the *book* does
not change the *signal*.

**This round therefore predicts a null** (section 5, prediction P1). It earns its place by testing
something the programme has not tested, not by expecting a different answer. The value of running it
is that "the real yield, specifically, on a long-horizon defensive book, specifically" is currently
an untested claim rather than a refuted one, and leaving it untested while the corpus keeps repeating
it is how an unfalsified folk belief survives.

## 3. Where the hypothesis comes from

Two personas in the app's influencer vault supply it. `creator-b` ("Creator B") argues a ten-year
structural-stagnation view and reads dollar and rate stress as the binding macro constraint;
`creator-d` ("Creator D") reads Fed rate-cut expectations as the driver of risk appetite.
Neither states a numeric rule. What they share is one claim: **the real discount rate should decide
how defensive a long-horizon book is.** This round converts that shared claim into one testable
threshold.

**The corpus supplies the hypothesis; the programme supplies the null.** No influencer is being
endorsed, no persona's track record is being measured, and a null here is not a verdict on either
speaker — it is a verdict on one mechanical reading of one shared claim.

## 4. The book, the field, and every number in it

### 4a. The book

`purpose = Purpose.SAVINGS`: **$100,000 lump sum, 10–20 year horizon, taxable**, benchmark
**`30-70-spy-agg`** (`backend/app/paperdesk/benchmarks.py`), and a mandate that is explicitly
**lowest drawdown, least return accepted of the three books**. Drawdown and MAR therefore matter at
least as much as return, and section 9's decision rule ranks on that basis rather than on return.

**Taxable/roth disjointness.** A taxable card must not use a ticker claimed by a live `roth` card.
`round38.py` recomputes the roth union live from `app.evolution.promotion._library_cards` (which
walks all six library tiers) and **refuses `--write` on a violation** — it does not read a pasted
list. Measured 2026-09-09, that union is 21 tickers: `AAPL ADBE AMAT BND CRM CSCO IGV INTU ITA KLAC
LRCX SSO VIG VNQ VUG XBI XHB XME XOP XRT XSD`. None of this field's sleeves appears in it.
Taxable-to-taxable overlap is legal, so reusing the savings book's own tickers is not a collision.

### 4b. The base allocation, identical on every card including the control

| sleeve | weight | why this and not another |
|---|---|---|
| SPY | 0.30 | **The savings benchmark's own equity share.** Pinning it there means no card in this field makes an unstated equity-beta bet against the thing it is scored against — which is exactly how round 29's "survivor" dissolved into the beta premium. |
| AGG | 0.50 | The bulk of the benchmark's own 70% bond share. |
| GLD | 0.10 | The non-bond diversifier. |
| BIL | 0.10 | T-bills. **The honest defensive destination for this specific tilt**: a high real yield is precisely the state in which long-duration `AGG` is hurt, so shifting into `AGG` to "de-risk" against a rate signal would be moving into the instrument the signal is about. |

`band_pct = 0.05`, the same 5-point band both live allocation cards carry
(`backend/app/paper/library/allocation/qld-schd-sgov.json` and
`spy-schd-agg-gld-bil-atr-tilt.json`), reused rather than re-chosen so this round varies the tilt
condition and nothing else against the shipped family (PROTOCOL.md §7).

**Sleeve history clears every window.** First bars read live from the store 2026-09-09: SPY
1993-01-29, AGG 2003-09-29, GLD 2004-11-18, BIL 2007-05-30. The earliest window used is `h10y-1`
(2013-09-03), so no sleeve binds. `SCHD` (2011-10-20) and `SGOV` (2020-06-01) are deliberately
excluded: `SGOV` alone would truncate the field to post-2020 and destroy the 10-year rungs the
savings mandate is judged on.

### 4c. The field — 7 cards, no grid

`shift_pct = 0.10` on every rule: ten points of the **whole book** (`TiltRule.shift_pct` is a
fraction of the portfolio, not of `from_symbol`'s own weight), moving the equity sleeve from 30% to
20% — a third of the equity exposure, materially different but not a regime switch. **It is
deliberately larger than the 5-point band**: a shift smaller than the band could be absorbed entirely
by it and never produce a trade, leaving a tilt that is present, plausible and unread. At 0.10
against 0.05 a firing rule always breaches, so a true condition is guaranteed to be *expressed*.

| card | condition | shift | role |
|---|---|---|---|
| `r38-control` | *(none — `rules == ()`)* | — | **Mandatory control.** Same sleeves, same band, no rule. |
| `r38-realyield-hi-1` | `macro(DGS10) - macro(T10YIE) > 1.0` | SPY → BIL | **Primary treatment.** |
| `r38-realyield-hi-2` | `macro(DGS10) - macro(T10YIE) > 2.0` | SPY → BIL | Threshold sensitivity — pre-registered degenerate, see §6. |
| `r38-realyield-lo-1` | `macro(DGS10) - macro(T10YIE) < 1.0` | BIL → SPY | The opposite-direction half: risk-**on** when money is cheap. |
| `r38-nominal-hi-4` | `macro(DGS10) > 4.0` | SPY → BIL | Separability leg A: the nominal leg alone. |
| `r38-breakeven-lo-2` | `macro(T10YIE) < 2.0` | SPY → BIL | Separability leg B: the breakeven leg alone. |
| `r38-price-placebo` | `close < sma(200)` | SPY → BIL | **Price-only placebo — no macro term at all.** |

`r38-realyield-lo-1` is the exact mirror of `r38-realyield-hi-1` on one axis, which makes them a
clean §7 one-decision variant pair. When it fires, `BIL` (0.10) is emptied into `SPY` (0.30 → 0.40)
by the engine's own `min(shift, weights[from_symbol])` clamp; the card then holds three sleeves in
that regime. That is stated here rather than left for a reader to discover.

The two separability legs exist because **the real yield is not one signal but the difference of
two**, and a margin on `r38-realyield-hi-1` means nothing if `r38-nominal-hi-4` produces the same
margin — that would say the breakeven subtraction contributes nothing and round 30 already measured
`DGS10` alone as null. The placebo exists because a margin on *any* macro card means nothing if
"a tilt fires sometimes" produces the same margin on a rule with no macro content whatsoever.

**Free numbers (PROTOCOL.md §3 rule 3, budget 10):** control **5** (4 sleeve weights + band); every
other card **7** (4 weights + band + 1 threshold + 1 shift). Counted mechanically by
`round38.free_numbers`, which walks the parsed condition tree and counts bare literals and numeric
indicator arguments; sleeve weights are counted in full rather than as `n − 1` independent numbers,
because counting generously is the direction that cannot flatter a card. `round38.py` refuses to
write a field that exceeds the budget.

### 4d. Every threshold, and why it is not a searched number

**No return series was read while choosing any of these.** Each is a round number fixed by a concept
before any measurement in this round existed.

- **1.0% real yield** (primary) — the round "one percent real" line. It is also the threshold that
  survives the feasibility screen in §6; that screen reads `DGS10` and `T10YIE` only and touches no
  price and no outcome, and it is disclosed rather than hidden precisely because "I picked the
  threshold that had data behind it" is a claim a reader is entitled to audit.
- **2.0% real yield** — the round figure conventionally treated as the boundary between
  accommodative and restrictive long-run real rates. Kept in the field **despite being degenerate**
  (§6): dropping it would hide the feasibility screen and present 1.0% as if it had been the only
  candidate.
- **4.0% nominal 10-year** — a round number, one whole percentage point above the 3% that anchors
  most long-run nominal-rate discussion.
- **2.0% breakeven** — **the Federal Reserve's own stated inflation target.** A threshold set by an
  institution, not by this programme, and the least tunable number in the field.
- **`sma(200)`** on the placebo — the textbook constant already frozen in
  `app.evolution.ruleforms` before this round was conceived, used unmodified in round 17.
- **`shift_pct = 0.10`** — justified above, against the band rather than against any outcome.

**No grid search** (§3 rule 4). Two thresholds on one series is a stated sensitivity pair, not a
sweep, and the degenerate one is pre-declared as degenerate rather than reported as a second draw.

## 5. Predictions — falsifiable, fixed before the run

**P1 (the pre-registered null, and the primary prediction).** The treatment-minus-control margin in
max drawdown for `r38-realyield-hi-1` will be **inside ±2 percentage points** across the eligible 5y
and 10y rungs, and its MAR margin inside ±0.10. This is what rounds 30/31/32 predict, and this round
expects it. *Falsified by* a drawdown margin consistently outside that band with the same sign across
both 10-year rungs and at least two 5-year rungs.

**P2 (separability).** If any margin does appear on `r38-realyield-hi-1`, `r38-nominal-hi-4` will
show a margin of the **same sign and within half its size** — i.e. the real-yield construction adds
nothing over the nominal leg round 30 already measured null. *Falsified by* the real-yield card
beating the nominal-only card by more than the noise floor on the drawdown margin, which would be the
first evidence in this programme that the breakeven subtraction carries information.

**P3 (the placebo).** `r38-price-placebo` will move max drawdown by **at least as much as** every
macro card, because a 200-day-mean de-risking rule is a genuine drawdown reducer and a macro rate
threshold is not. *Falsified by* any macro card beating the placebo on drawdown margin by more than
the noise floor. **If P3 is not falsified, no macro result in this round can be attributed to the
macro term**, whatever its size.

**P4 (the named failure regime — a sustained low-real-yield decade with rising equities).** From
2013 to 2021 the real yield sat below 1% almost continuously (§6). Across that stretch
`r38-realyield-hi-1` is **identical to its own control by construction** — it cannot fire — and
`r38-realyield-lo-1` fires on essentially every session, making it a *different static allocation*
rather than a conditional tilt. The prediction: any margin this round reports on the 10-year rungs
will be dominated by the single 2022 regime transition, not by ten years of evidence. *Falsified by*
a margin of consistent sign in `h10y-1` (2013-09-03 → 2023-08-31), where the primary treatment fires
on only 11.6% of macro observations and 0% before 2022.

**P5 (direction asymmetry).** `r38-realyield-lo-1` (risk-on when money is cheap) will show a
**larger** absolute CAGR margin and a **worse** drawdown margin than `r38-realyield-hi-1`, because
over every window in the set the low-real-yield state coincides with the post-2009 equity expansion.
*Falsified by* the two cards' margins being symmetric. This prediction is deliberately one this
round is likely to confirm for a reason that has nothing to do with the hypothesis — it is a
**beta-in-disguise check**, and confirming it is evidence *against* reading the low card as a signal.

## 6. The structural power of this round — measured on the regressor, before any outcome

This is the section a reader should distrust the round without.

**What was measured, and what was deliberately not.** Before authoring the field, the *support of the
conditioning variables themselves* was computed from round 21's frozen pin: how often each condition
is true in each candidate window. This reads `DGS10` and `T10YIE` and **nothing else** — no price
series, no return, no equity curve, no card. It is a feasibility screen, not a result, and it is
reported here so that "the threshold was chosen with some knowledge of the data" is on the record.

Real yield (`DGS10 − T10YIE`) over the pin's full overlap, n = 5,918, 2003-01-02 → 2026-08-27:
min −1.19, p10 −0.57, **median 1.05**, p90 2.20, max 3.15. Fraction of observations above 0.0%:
0.836; above 1.0%: **0.508**; above 2.0%: 0.189.

Firing rate per window (fraction of macro observations inside the window on which the condition is
true). A cell at 0.000 means the card is **identical to the control by construction**; a cell at
1.000 means it is a *different static allocation*, not a conditional tilt. Both are degenerate.

| window | span | RY > 1.0 | RY > 2.0 | DGS10 > 4.0 | T10YIE < 2.0 |
|---|---|---|---|---|---|
| `h10y-1` | 2013-09-03 → 2023-08-31 | 0.116 | **0.000** | 0.018 | 0.523 |
| `h10y-2` | 2016-02-16 → 2026-02-13 | 0.361 | 0.099 | 0.234 | 0.384 |
| `h5y-1` | 2013-09-03 → 2018-08-31 | **0.000** | **0.000** | **0.000** | 0.621 |
| `h5y-2` | 2016-02-16 → 2021-02-12 | 0.040 | **0.000** | **0.000** | 0.769 |
| `h5y-3` | 2021-02-16 → 2026-02-13 | 0.682 | 0.198 | 0.469 | **0.000** |
| `h3y-1` | 2014-02-18 → 2017-02-15 | **0.000** | **0.000** | **0.000** | 0.771 |
| `h3y-2` | 2017-02-16 → 2020-02-14 | 0.067 | **0.000** | **0.000** | 0.678 |
| `h3y-3` | 2020-02-18 → 2023-02-15 | 0.138 | **0.000** | 0.023 | 0.293 |
| `h3y-4` | 2023-02-16 → 2026-02-13 | **1.000** | 0.332 | 0.761 | **0.000** |
| `b6m-1` | 2019-09-20 → 2020-03-23 | **0.000** | **0.000** | **0.000** | **1.000** |
| `b6m-2` | 2021-12-15 → 2022-06-16 | **0.000** | **0.000** | **0.000** | **0.000** |
| `b6m-3` | 2018-06-25 → 2018-12-24 | 0.384 | **0.000** | **0.000** | 0.192 |
| `b1y-1` | 2021-12-28 → 2022-12-28 | 0.283 | **0.000** | 0.068 | **0.000** |
| `b1y-2` | 2019-03-22 → 2020-03-23 | **0.000** | **0.000** | **0.000** | **1.000** |
| `b1y-3` | 2015-02-11 → 2016-02-11 | **0.000** | **0.000** | **0.000** | **1.000** |

`r38-realyield-lo-1` is the complement of the `RY > 1.0` column and has the identical eligible set.

**Eligible windows per horizon**, against `windows.py`'s own `MIN_ELIGIBLE_R5_PER_HORIZON = 2`:

| card | 10y (of 2) | 5y (of 3) | 3y (of 4) | bear (of 6) | gate |
|---|---|---|---|---|---|
| `r38-realyield-hi-1` / `-lo-1` | 2 | 2 | 2 | 2 | **passes at every horizon** |
| `r38-realyield-hi-2` | 1 | 1 | 1 | **0** | **FAILS at every horizon** |
| `r38-nominal-hi-4` | 2 | **1** | 2 | 1 | **fails at 5y** |
| `r38-breakeven-lo-2` | 2 | 2 | 3 | 1 | passes on the ladder |

Three consequences, all pre-registered:

1. **`r38-realyield-hi-2` is structurally incapable of producing evidence.** It is reported as a
   degenerate cell, never as a second measurement of the hypothesis, and never as a confirmation of
   `-hi-1`. Re-running a card that cannot fire is not a new draw.
2. **`r38-nominal-hi-4`'s 5-year arm carries one window.** Its separability verdict (P2) rests on the
   10y and 3y rungs.
3. **The bear supplement is thin for every macro card** — 2 of 6 windows at best, 0 of 6 for the 2.0%
   threshold, because the 2013–2021 bear episodes all sit inside the low-real-yield decade. **This
   round cannot say what a real-yield tilt does in a bear market**, and any drawdown claim it makes is
   a claim about the ladder, not about crisis behaviour.

**The placebo's firing rate was deliberately not computed.** Verifying it requires reading SPY's
price series, which is the one thing this screen refused to touch. It is *expected* to be
non-degenerate in every window; that expectation is stated as an expectation, not as a measurement.

## 7. Windows

**The R5 horizon ladder plus the bear supplement**, both from `strategy-program/tools/windows.py`:
`R5_LADDER_WINDOW_TAGS` (`h10y-1`, `h10y-2`, `h5y-1..3`, `h3y-1..4`) and `R5_BEAR_WINDOW_TAGS`
(`b6m-1..3`, `b1y-1..3`) — 15 windows, listed with their spans in §6.

**Why not the 8-window trading matrix.** A $100,000 lump sum with a 10–20 year horizon is judged on
how it compounds and how deep it draws down over multi-year holds, and the trading matrix's regime
slices answer a different question about a different book. The ladder is the instrument the savings
and ladder families are already measured on, and reusing it is what lets this round's numbers sit
beside `SAVINGS-FAMILY.md`'s.

**Ranking uses the 5y and 10y rungs; 3y and the bear windows are supplements.** The mandate is
10–20 years. The 3-year rungs are reported and are what P2's separability verdict partly rests on,
but a three-year result does not decide a two-decade card.

**T10YIE starts 2003-01-02**, which is earlier than every window in the set, so the macro series is
not the binding history constraint — the windows themselves are.

## 8. Evaluation procedure — and the harness gap this round will hit

**There is no `score.py` equivalent for `AllocationCard`s, and pretending otherwise would make this
plan unrunnable.** `strategy-program/tools/score.py` is hard-typed to
`app.tournament.models.AgentResult`, and `AllocationResult` deliberately is not that class (see
`app.tournament.allocation`'s module docstring: `AgentResult.card` is typed as `StrategyCard`
specifically, so an allocation result cannot round-trip through `score.py`'s `_load_results`).
`tools/run_round.sh` will not work here. Every savings and roth backtest this programme has run is a
bespoke script that calls `run_allocation` / `run_ladder_card` directly and reports its own metrics —
`savings_gap.py`, `ladder_horizon.py`, `allocation_family.py`.

**The script this round will use: `strategy-program/tools/round38_run.py`, modelled on
`savings_gap.py`.** Not yet written; it is not part of this pre-registration's deliverable, and
writing it is a separate step so that the field is frozen before the harness that scores it exists.
Its exact shape:

- `INVDASH_MACRO_PIN` set to `data/rounds/r21-2026-08/macro-pin.json` — round 21's frozen
  seven-series pin, the same one rounds 23/25/30 used. **A macro condition fails closed without it**
  (`MissingPinError`), and re-fetching FRED would serve today's revised values against the same
  reference dates and make this round non-comparable with those.
- `mandate = desk_mandate(Purpose.SAVINGS)` — `from app.paperdesk.desk import _mandate as
  desk_mandate` — called rather than reconstructed, so it cannot drift from the live book's mandate.
- Per card, per window: `run_allocation(card, settings=settings, mandate=mandate, start=..., end=...)`.
  7 cards × 15 windows = **105 runs**. The bar store is single-writer; the round runs serially.
- Metrics per cell, following `savings_gap.engine_row`:
  - **CAGR** = `(ending_equity / starting_cash) ** (TRADING_DAYS / sessions) − 1`
  - **max drawdown** = `result.max_drawdown` (from `app.backtest.metrics.compute`, never recomputed —
    this repository has already shipped a defect from two disagreeing drawdown implementations)
  - **MAR** = `CAGR / abs(max_drawdown)`
  - **volatility**, **sessions**, **trades**, **rejections** reported beside them.
- **The benchmark must be computed separately, and this is a trap worth naming.**
  `AllocationResult.benchmark_return` is computed against `_BENCHMARK = "SPY"`, hard-coded in
  `app.tournament.allocation` — it is **not** the savings book's 30/70 blend. The round's benchmark
  column comes from `app.paperdesk.benchmarks.price_blend(REGISTRY["30-70-spy-agg"], start=..., end=...)`.
  Reporting `result.benchmark_return` as "the savings benchmark" would silently compare a defensive
  book against 100% equity.
- **Every reported figure is a margin: treatment metric minus the same metric on `r38-control`, in
  the same window.** Treatment-versus-benchmark is reported as context only and never as the round's
  finding.
- Degenerate cells (§6) are labelled `degenerate` in the output, excluded from margin aggregates, and
  their window count is printed beside every aggregate so no reader can mistake a 2-window median for
  a 15-window one.

**Distributions are not modelled.** AGG, GLD and BIL all pay distributions this harness does not
model, so every CAGR figure is understated; the drawdown column is the trustworthy half. Same caveat
`savings_gap.py` carries, restated because it applies to three of this field's four sleeves.

## 9. Decision rule — pre-registered

**Nothing is promoted from a measurement round.** No card in this field is a candidate for the paper
desk, the library, or any tier, whatever it returns. That is not a hedge; it is what a measurement
round is.

**The ranking criterion, given the savings mandate.** The mandate is lowest drawdown, least return
accepted. So the round is decided on the **max-drawdown margin** (treatment minus control) as the
primary criterion and the **MAR margin** as the joint criterion; the **CAGR margin** is reported and
is not a ranking key. A card that improves CAGR and worsens drawdown has failed this book's mandate
regardless of its return.

**The noise floor.** PROTOCOL.md §7's floor is **21.2 percentage points** (σ across twelve universe
orderings of one identical card), and every margin in this round will be stated against it
explicitly. **One honesty note that cuts against this round's own ability to claim anything:** that
floor was measured on a `StrategyCard`'s universe-ordering tiebreak, a mechanism that **does not
exist for an `AllocationCard`** — every sleeve is held at all times and there is no slot contention
to break. So 21.2pp is inherited conservatism, not a floor measured for this card shape. No
equivalent floor has ever been measured for allocation cards, and measuring one is a separate round.
This round may not claim that a sub-21.2pp margin is real on the grounds that the floor does not
apply to it.

**Multiple comparisons.** Any correction uses a denominator of **7** — every card the round runs,
including the control and the degenerate cell (§3 rule 8). A correction over the "interesting"
subset is the exact failure the correction exists to prevent, and this project has made it once.

**The verdicts:**

- **P1 holds (the expected outcome)** → the real yield adds nothing to a long-horizon savings book.
  The macro line stays closed, and it is now closed on both card shapes and two of the three books
  rather than one. The persona claim in §3 is measured-null as a mechanical rule. **No follow-up
  round on this series.**
- **P1 falsified but P3 not falsified** (a macro margin appears, but the price placebo matches or
  beats it) → the margin is "a tilt fired sometimes", not the real yield. Treated as a **null for the
  hypothesis** and a note that the savings book is sensitive to de-risking tilts in general — which is
  a finding about `band_pct` and `shift_pct`, not about macro.
- **P1 falsified, P3 falsified, P2 holds** (the macro card beats the placebo, but the nominal-only leg
  matches it) → it is `DGS10` in disguise, which round 30 already measured null. The real-yield
  construction earns nothing.
- **P1 falsified, P3 falsified, P2 falsified** → the first evidence in this programme that a macro
  quantity carries information a price rule does not, on the book where it would matter. This still
  **promotes nothing**. It would justify one dedicated follow-up round with a genuine out-of-sample
  split, exactly as round 32 was the follow-up to round 31's near-miss — and §6's structural warning
  applies with full force: with 2 eligible bear windows and one regime transition doing most of the
  work, this round cannot distinguish "a signal" from "2022".

## 10. Determinism, scope, and what this round cannot settle

- **Deterministic.** `build()` is pure — no clock, no randomness, no store access — and is asserted
  byte-identical across calls in `tests/test_round38_field.py`. The pin is frozen. `run_allocation`
  is deterministic and its slippage is always adverse.
- **`designed_through = DESIGN_THROUGH` (2026-02-13)** on every card, enforced by the model.
- **Release-lag honesty, and why this round does *not* inherit the inflation rounds' caveat.** Rounds
  21/31/32 bind a macro series to its **release** date rather than its period date, and argue at
  length about the 45-day conservative placeholder lag on the monthly CPI/PCE indices and the
  unclosed **revision** channel behind it (FRED serves today's revised figure against a historical
  reference date; closing that needs ALFRED vintages, which the provider does not speak). **Neither
  argument applies here.** `DGS10` and `T10YIE` are daily, market-observed series; `RELEASE_LAG`
  gives both one trading day, which is the engine's own existing convention, and a market-observed
  yield is not revised. Inheriting the inflation rounds' lag caveat would be borrowing a disclaimer
  this round has not earned; saying so explicitly is the point of this bullet.
- **Verified 2026-09-09 that the guard actually passes**, including the two-term subtraction:
  `guards.check("macro(DGS10) - macro(T10YIE) > 2.0", …)` returns `GuardStatus.PASSED` with
  `macro_release_binding` passing, once `INVDASH_MACRO_PIN` is set. Without the pin it returns
  `FAILED` with `MissingPinError`, which is the guard failing closed, correctly.
- **`on_symbol = "SPY"` supplies the session axis, not a price signal.** On every card but the
  placebo the condition contains no price term. A reader scanning the JSON will see `"on_symbol":
  "SPY"` and could reasonably infer SPY is being read as a signal; it is not.
- **What this round cannot settle:** bear-market behaviour of a real-yield tilt (2 eligible bear
  windows at best, §6); whether 21.2pp is the right noise floor for an `AllocationCard` (§9); whether
  a *continuously sized* tilt (`shift_expr`) would behave differently from this constant 10-point one
  — `ALLOCATION-FAMILY.md` records that continuous vol-targeting and inverse-vol parity are the two
  strategies that need it and that inverse-vol posted the family's shallowest drawdown anywhere, and
  this round deliberately does not open that door; and anything about after-tax outcomes, since the
  harness models no distributions and no taxes.
- **Not investment advice.** Price-only bars, one pin, no distributions, no taxes, and a
  pre-registered expectation that the answer is nothing.

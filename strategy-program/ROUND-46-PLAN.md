# Round 46 — do two independent savings de-risking reads stack additively?

Pre-registered **2026-09-09**, before any measurement in this round exists. **The round has NOT been
run.** No card here has been executed over any evaluation window, no margin has been computed, and
nothing below reports an outcome. **Not investment advice.**

Authored by `strategy-program/tools/round46.py`; the frozen field is
`data/rounds/r46-2026-09/cards/*.json` (7 cards); the tests that pin the field to this document are
`tests/test_round46_field.py`. Round 46 is one of three sibling mix-and-match rounds pre-registered
together in `strategy-program/MIX-AND-MATCH-PLAN.md` (§3, "Round 46 — savings: do two independent
de-risking reads stack?"); rounds 45 and 47 are authored by other sessions and touch none of this
round's files.

---

## 1. Why this round is new

Round 43 (`ROUND-43-PLAN.md`, run 2026-09-09) measured two de-risking reads on the identical savings
book **separately**: `r43-price-placebo-spy` (the equity sleeve's own trend, `SPY close < sma(200) ->
SPY->BIL`) moved the drawdown margin **+0.94pp**; `r43-agg-trend-bil` (the bond sleeve's own trend,
`AGG close < sma(200) -> AGG->BIL`) moved it **+1.34pp** (`data/rounds/r43-2026-09/REPORT.md` §1).
Both cards ran in the same round, on the same windows, against the same control — but never on the
same card. No card in round 43, round 38, or any prior savings-family round has ever carried more than
one tilt rule at once. Whether two reads that each move the drawdown by about a point **combine** when
stacked — moving it by roughly the sum, because they capture two separable risks — or whether one
swamps or cancels the other — because SPY's and AGG's 200-day trends are not independent signals but
two readings of the same broad-market stress — has never been tested. §6 below measures exactly how
correlated the two conditions' firing patterns are, directly, before any card built from them runs.

Two further cards ask whether a third rule improves the two-sleeve stack: Creator A's metals
destination (already measured alone in round 43 as `r43-gld-trend`, drawdown margin **−0.38pp** —
a CAGR bet, not a defensive one) and Creator B's trim-after-gains on the equity sleeve, which no
`AllocationCard` in this programme has carried before (round 44 tested it as a `StrategyCard`
entry/exit pair on thematic baskets, not as a sleeve tilt on this book).

## 2. The prior is a null, and this round pre-registers one

Every card this round reuses has already returned a null on its own: round 43's SPY placebo (+0.94pp),
AGG primary (+1.34pp) and GLD-trend arm (−0.38pp) are all inside the programme's floor
(`data/rounds/r43-2026-09/REPORT.md` §1, §5). Round 44's trim arm returned "best trim +2.4pp"
(`PROTOCOL.md` §9, r42-44-2026-09 entry), also inside the floor. **Stacking two null-sized effects is
this programme's prior for a third null-sized effect, not for a discovery** — this round earns its
place by testing whether the stack is additive, sub-additive or super-additive, not by expecting a
material drawdown improvement from any card in it.

**The corpus supplies the components; the programme supplies the stacking question.** No influencer
proposed carrying two rules on one card — Creator D and Creator A each spoke to their own sleeve/
destination in isolation, and Creator B's trim was voiced as a discipline on individual
positions, not as an addition to a bond-sleeve tilt. The additivity question is this round's own,
asked because round 43 happened to measure the two ingredients this round now combines.

## 3. Where each rule comes from

Quoted verbatim, ≤15 words each, from `PERSONA-DISCUSSION-2026-09-09.md` §3 (the savings/roth
answers) — the identical citations `ROUND-43-PLAN.md` §3 and `ROUND-44-PLAN.md` used, because this
round's rules are literally those two rounds' cards recombined:

- **Creator D (Creator D):** "Rising bond yields are a real risk to portfolios." — `r46-agg-derisk`,
  reproducing `r43-agg-trend-bil` verbatim (`ROUND-43-PLAN.md` §3).
- **Creator A:** "overweighting precious metals during macro stress" — the `AGG -> GLD` destination
  rule carried in `r46-both-gld`, reproducing `r43-gld-trend`'s rule verbatim.
- **Creator B (creator-b):** "trim on weakness to lock profits" (`PERSONA-DISCUSSION-2026-09-09.md`
  line 113/117) and, in the triage table, "a price-extension trim is expressible: exit when
  `close > sma(200) * 1.15`" (line 135) — the rule carried in `r46-trim-high` and `r46-both-trim`,
  the identical threshold round 44's trim arm used.
- **The SPY-sleeve read (`r46-spy-derisk`)** is round 38's price-only placebo, reproduced verbatim a
  second time (round 43 already reproduced it once) — it has no persona attribution of its own; its
  role here, as in round 43, is the equity-sleeve yardstick the bond-sleeve read is measured against.

`Creator B` himself, asked directly about savings-sleeve rebalancing
(`PERSONA-DISCUSSION-2026-09-09.md` §3, savings answer, lines 115-117), declined to offer a mechanical
threshold: "I don't have a specific sleeve-shift rule to propose because sleeve allocation decisions
should emerge from macro regime conviction, not from pattern-matching on daily bars." The trim
threshold used here is round 44's own mechanical translation of his *trading-discipline* framing
("trim on weakness to lock profits"), not a sleeve-rebalancing rule he stated — the same caveat
`ROUND-43-PLAN.md` §3 gives for the bond-sleeve threshold, restated here because this round inherits
the rule, not the caveat automatically.

## 4. The book, the field, and every number in it

### 4a. The book

Identical to round 38 and round 43: `purpose = Purpose.SAVINGS`, **$100,000 lump sum, 10–20 year
horizon, taxable**, benchmark **`30-70-spy-agg`**, mandate lowest drawdown, least return accepted.

**Taxable/roth disjointness.** `round46.roth_union` recomputes the live roth union from
`app.evolution.promotion._library_cards`, identical method to `round43.roth_union` /
`round38.roth_union`, and `round46.py` refuses to write on a collision. This field's sleeves are
`SPY AGG GLD BIL`, the identical set round 38 and round 43 already cleared against the same union.

### 4b. The base allocation, identical on every card including the control

Reused from round 38 and round 43 without modification, because this round varies which rules a card
carries and nothing else (PROTOCOL.md §7): **SPY 0.30 / AGG 0.50 / GLD 0.10 / BIL 0.10**,
`band_pct = 0.05`, `designed_through = DESIGN_THROUGH` (2026-02-13).

### 4c. The field — 7 cards, no grid

`shift_pct = 0.10` on **every** rule in every card, the identical round-38/round-43 justification:
larger than the 5-point band, so a firing condition always breaches and is guaranteed to be expressed
as a trade rather than absorbed. Where a card carries two or three rules and more than one fires on
the same session, each still moves its own ten points — the engine does not treat a doubly-fired
session specially (`app.tournament.allocation.TiltRule`'s own docstring, quoted in round 43's tool).

| card | rules (in order) | role |
|---|---|---|
| `r46-control` | *(none)* | **Mandatory control.** Same sleeves, same band, no rule. |
| `r46-spy-derisk` | SPY `close < sma(200)` → SPY→BIL | Equity-sleeve read alone — `r43-price-placebo-spy`, verbatim. |
| `r46-agg-derisk` | AGG `close < sma(200)` → AGG→BIL | Bond-sleeve read alone — `r43-agg-trend-bil`, verbatim. |
| `r46-both` | spy rule; agg rule | **The additivity test.** Both single-sleeve reads on one card. |
| `r46-both-gld` | spy rule; agg rule; GLD `close > sma(200)` → AGG→GLD | Both + Creator A's metals destination. |
| `r46-trim-high` | SPY `close > sma(200) * 1.15` → SPY→BIL | Creator B's trim-after-gains on the equity sleeve, alone. |
| `r46-both-trim` | spy rule; agg rule; trim rule | Both + Creator B's trim. |

**`r46-spy-derisk`'s rule equals `r43-price-placebo-spy`'s and `r46-agg-derisk`'s equals
`r43-agg-trend-bil`'s, byte-for-byte.** `round46.check_r43_drift` reads both source cards live from
`data/rounds/r43-2026-09/cards/` every run (dry run and `--write` alike) and compares
`(condition, on_symbol, from_symbol, to_symbol, shift_pct)`; `round46.py` refuses to write (raises
`R43Drift`) on any mismatch, exactly as it refuses on a taxable/roth collision. This is the harness
literally re-reading the file, not a comment asserting the two rounds agree.

**Free numbers (PROTOCOL.md §3 rule 3, budget 10) — measured, and one deviation disclosed.**
`round46.free_numbers` is the identical method `round43.free_numbers` / `round38.free_numbers` use
(sleeve weights + band, counted in full, plus each rule's condition literals and its own shift):

| card | free numbers | within the 10 budget? |
|---|---:|---|
| `r46-control` | 5 | yes |
| `r46-spy-derisk` | 7 | yes |
| `r46-agg-derisk` | 7 | yes |
| `r46-both` | 9 | yes |
| `r46-both-gld` | **11** | **no** |
| `r46-trim-high` | 8 | yes |
| `r46-both-trim` | **12** | **no** |

Round 38 and round 43 never carried more than one rule per card, so their tools refuse to write any
card that exceeds ten. This round's whole scientific purpose is to test whether rules that EACH
already cleared the budget on their own (`r46-spy-derisk` and `r46-agg-derisk` at 7 apiece, run once
already in round 43) combine when stacked; stacking mechanically raises the count without a single new
threshold being searched — every literal in every rule here is reused, unmodified, from a card this
programme has already authored (round 38's placebo, round 43's AGG-trend/GLD-trend rules, round 44's
trim threshold translated into this card shape). `round46.py`'s dry run and `--write` both print every
card's count and flag anything over ten; unlike `round43.py`, they do **not** refuse to write on that
basis — only the r43-drift check and the taxable/roth collision check are hard refusals here. This is
a considered, disclosed departure from round 43's convention (stated in `round46.py`'s own module
docstring as well as here), not a silent relaxation of PROTOCOL.md §3 rule 3 — the count for every card
is reported, per the rule's own text ("Reported in every memo").

### 4d. Every threshold, and why it is not a searched number

- **`sma(200)`** on `SPY`, `AGG` and `GLD` — the textbook constant already frozen in
  `app.evolution.ruleforms`, reused unmodified a third time (round 17, round 38/43, now round 46).
- **`sma(200) * 1.15`** — Creator B's own trim threshold, reused unmodified from round 44's
  trim arm; no return series was read while choosing it for this round.
- **`shift_pct = 0.10`** and **`band_pct = 0.05`** — round 38's figures, unchanged.

**No grid search.** Every threshold in this field is a value a prior round already fixed before any
measurement; this round introduces no new numeric parameter anywhere — only new **combinations** of
already-fixed rules on already-fixed cards. That is the entire experimental manipulation.

## 5. Predictions — falsifiable, fixed before the run

**P1 (additivity, the primary prediction).** `r46-both`'s drawdown margin (treatment minus control)
will sit within **±0.5pp** of the sum of `r46-spy-derisk`'s and `r46-agg-derisk`'s own margins, on the
rungs where all three fired — the signature of two separable risks. *Falsified by* `both − (spy + agg)`
exceeding ±0.5pp, which would show the two conditions are reading substantially the same underlying
stress rather than two different ones. §6 below measures the two conditions' pairwise firing overlap
directly, before any card runs, as the mechanical explanation for whichever way P1 comes out.

**P2 (no card exceeds a few points).** Every card's drawdown margin against the control, on the judged
5y/10y rungs, will be **a few points at most** — consistent with every savings tilt this programme has
measured, including every single-sleeve component this round stacks. *Falsified by* any card's margin
exceeding a few points, consistently signed, across at least two judged rungs.

**P3 (the trim rule is a drag, not a benefit).** `r46-trim-high` will show a **CAGR drag with no
drawdown benefit** — SPY trades more than 15% above its own 200-day mean on a small minority of
sessions (measured in §6), concentrated in sustained rallies rather than in drawdowns, so stepping to
cash there is predicted to give back upside without shallowing a drawdown it was never positioned to
prevent. *Falsified by* `r46-trim-high` showing a positive drawdown margin alongside a positive or
flat CAGR margin.

**P4 (a third rule does not improve the stack).** Neither `r46-both-gld` nor `r46-both-trim` will
improve `r46-both`'s own drawdown margin by more than **0.5pp**. *Falsified by* either add-on card
beating `r46-both` by more than 0.5pp of drawdown margin, which would show the third rule earns its
place on the stack rather than merely adding trades and cost.

**Hindsight, stated bluntly, as round 43 §5 states it.** `b6m-2` (2021-12-15 → 2022-06-16) and `b1y-1`
(2021-12-28 → 2022-12-28) sit inside the exact 2021-2022 regime the corpus's bond-stress thesis was
voiced after. **These two windows are in-sample to the hypothesis, not out-of-sample evidence for
it**, and the harness (§8) prints them in a table separate from every other window. A margin that
appears only in `b6m-2`/`b1y-1` and nowhere else is hindsight confirming what was already known when
the claim was made, not a finding.

**Named failure regimes, as round 43 §5 plus one new one.**

- **The 2013 taper-tantrum-style whipsaw** and **the 2019 bond rally the tilt sits out** — identical to
  round 43's §5, inherited unchanged by every card here that carries the AGG-derisk rule.
- **The opportunity cost of a simultaneous double de-risk.** On any session where both the SPY and AGG
  conditions are true at once, `r46-both` (and `r46-both-trim`) route **ten points from SPY and ten
  points from AGG into BIL in the same session — twenty points of the whole book moved to cash**, on
  top of BIL's own 10% starting weight. A stack that de-risks both sleeves at once in 2022 therefore
  sits roughly **thirty points of the book in BIL** during exactly the regime both conditions are most
  likely to co-fire (§6 measures how often that is). BIL's yield is unmodelled (§8), so the harness
  cannot show what that cash gave up while parked — this is the stack's own structural cost, stated
  here rather than left for a reader to discover, and it is the mechanical reason P1's ±0.5pp tolerance
  is a real test and not a formality: two conditions that fire together often will not add their
  drawdown benefits, because the second rule mostly re-defends a session the first rule already
  defended, while still paying the double trading and cash-drag cost.

## 6. The structural power of this round — measured on the regressor, before any outcome

**What was measured, and what was deliberately not.** Before authoring the field, the *support* of
every distinct condition this round uses, and the **pairwise overlap** of the two single-sleeve
conditions, were computed against the live bar store, 2013-09-03 (the earliest window's start,
identical to round 43's `SUPPORT_FROM`) through `DESIGN_THROUGH`. Both read price only, touch no
return series, no card and no window's outcome, and `round46.py`'s dry run / `--write` re-measure them
every time rather than freezing a screen computed once (`round46.support_table` and
`round46.overlap_fraction`). Measured 2026-09-09:

| condition | on_symbol | fraction of sessions true |
|---|---|---:|
| `close < sma(200)` | SPY | 17.4% |
| `close < sma(200)` | AGG | 44.6% |
| `close > sma(200)` | GLD | 61.2% |
| `close > sma(200) * 1.15` | SPY | 1.7% |

The first three figures are unchanged from round 43's own support screen (§6 of that plan) — the same
conditions on the same symbols over the same span. `close > sma(200) * 1.15` on SPY, this round's one
genuinely new condition, is true on only **1.7%** of sessions: SPY spends most of its time within 15%
of its own 200-day mean, so `r46-trim-high` is predicted to fire rarely and, per P3, to give back
upside on the rallies where it does.

**The pairwise overlap — the direct, pre-registered test of whether the two reads are independent.**
Fraction of sessions on which **both** the SPY-derisk and AGG-derisk conditions are true, the two
frames joined on date:

| quantity | value |
|---|---:|
| actual joint fraction (both true) | **12.6%** |
| expected if independent (17.4% × 44.6%) | 7.8% |
| actual ÷ independent-expected | **1.62×** |

The two conditions fire together **62% more often than independence would predict**. This is measured
on the regressor alone — no return, no card, no window outcome — and it is the mechanical reason P1's
prediction is genuinely uncertain rather than a formality: a joint fraction this far above the
independence benchmark means the sessions on which AGG is below its 200-day mean are disproportionately
sessions on which SPY already is too (both trend down together in a broad drawdown), which is exactly
the condition under which `r46-both`'s margin would fall short of the sum of its two components' own
margins — not because either rule is broken, but because the second rule mostly re-flags a session the
first rule already caught.

**Eligible windows per horizon**, against `windows.py`'s `MIN_ELIGIBLE_R5_PER_HORIZON = 2`: because
every condition in this field is well-conditioned (1.7%–61.2% support, none near-degenerate for the
single-sleeve and GLD reads; the trim condition's 1.7% is the one figure worth watching, and the
harness reports it `UNMEASURED` per horizon rather than folding a near-zero-fire rung into an
aggregate if it falls short of the gate) — this is disclosed as an expectation, re-verified once the
harness actually runs.

## 7. Windows

Identical to round 38 and round 43: **the R5 horizon ladder plus the bear supplement**
(`strategy-program/tools/windows.py`, `R5_LADDER_WINDOW_TAGS` + `R5_BEAR_WINDOW_TAGS`) — 15 windows.
**Ranking uses the 5y and 10y rungs; 3y and the bear windows are supplements.** `b6m-2` and `b1y-1` are
additionally reported in their own hindsight-flagged table (§8), per §5.

## 8. Evaluation procedure

**No `score.py` equivalent exists for `AllocationCard`s** (`ROUND-38-PLAN.md` §8's argument, inherited
by round 43 and again here — `score.py` is hard-typed to `AgentResult`).
`strategy-program/tools/round46_run.py` is round 43's harness, adapted:

- **No macro pin.** Every condition in this field is price-only; `INVDASH_MACRO_PIN` is never set and
  no card carries a `macro(...)` term.
- `mandate = desk_mandate(Purpose.SAVINGS)`, called live, identical to round 38/43.
- Per card, per window: `run_allocation(card, settings=settings, mandate=mandate, start=..., end=...)`.
  7 cards × 15 windows = **105 runs**, serial (the bar store is single-writer).
- Metrics per cell: CAGR, `max_drawdown`, MAR, volatility, sessions, trades — identical formulas to
  `round43_run.py`.
- **The benchmark is the 30/70 SPY/AGG blend**, recomputed per window, never
  `AllocationResult.benchmark_return` (hard-coded to SPY) — identical to round 38/43.
- **Every reported figure is treatment minus `r46-control`, in the same window.**
- **A per-bear-window table labels `b6m-2` and `b1y-1` "2022 (in-sample to the hypothesis)"**,
  identical to round 43's convention.
- **Five pairwise lines, per rung then median across the rungs where the relevant cards fired**, are
  this round's whole point: `both − spy`, `both − agg`, `both − (spy + agg)` (the direct test of P1),
  `both-gld − both` and `both-trim − both` (the direct test of P4).
- Degenerate or unmeasured cells (fired in fewer than `MIN_ELIGIBLE_R5_PER_HORIZON = 2` windows of a
  horizon) are labelled `UNMEASURED` and excluded from the aggregate, identical to round 38/43.

**Distributions are not modelled** (AGG/GLD/BIL pay distributions this harness does not simulate), so
every CAGR figure understates the real one, and the opportunity cost named in §5 (cash sitting idle
during a simultaneous double de-risk) is invisible to this harness beyond BIL's own unmodelled yield —
the drawdown column remains the trustworthy half.

## 9. Decision rule — pre-registered

**Nothing is promoted from a measurement round.** No card in this field is a candidate for the paper
desk, the library, or any tier, whatever it returns.

**Ranked on the max-drawdown margin** (treatment minus control, positive = shallower) as the primary
criterion and the **MAR margin** as the joint criterion, per the savings mandate. **CAGR margin is
reported, never ranked.**

**The noise floor.** PROTOCOL.md §7's 21.2pp floor is inherited conservatism, not load-bearing for
`AllocationCard`s, identical to round 38 §9 and round 43 §9 — it was measured on a `StrategyCard`'s
universe-ordering tiebreak, a mechanism this card shape does not have. Every margin is stated against
it anyway, as the only reference point on record, named as inherited and possibly too conservative.

**Multiple comparisons.** Any correction uses a denominator of **7** — every card this round runs,
including the control (PROTOCOL.md §3 rule 8: every card run in the comparison, never a subgroup).

**The verdicts:**

- **P1 holds (additive within ±0.5pp)** — the two reads are independent enough on this book that a
  stack captures both; this is the first evidence in this programme's savings line that two
  conditionally-fired tilts compose the way their designers might naively expect. Still promotes
  nothing — a measurement round's result, not a candidate.
- **P1 falsified, both − (spy + agg) < −0.5pp (sub-additive)** — the expected outcome given §6's
  1.62× overlap: the two conditions substantially double-count the same broad-drawdown regime, and
  stacking them buys less than the sum of their parts while paying the double trading/cash-drag cost
  named in §5. This closes the additivity question with a negative answer and needs no follow-up.
- **P1 falsified, both − (spy + agg) > +0.5pp (super-additive)** — a genuine surprise: the two
  conditions would have to be catching materially different sessions in a way that compounds rather
  than merely occurring together. Given §6's measured 1.62× overlap this is not predicted, and would
  justify one dedicated follow-up examining exactly which sessions each rule uniquely catches.
- **P3 falsified (trim shows a drawdown benefit)** — reported as a genuine surprise about the trim
  rule's behaviour on this specific book and threshold, not evidence for trim rules generally.
- **P4 falsified (a third rule improves the stack by >0.5pp)** — reported as the one card worth a
  closer look in a future round, still not promoted from this one.

## 10. Determinism, scope, and what this round cannot settle

- **Deterministic.** `build()` is pure — no clock, no randomness, no store access — asserted
  byte-identical across calls in `tests/test_round46_field.py`. `run_allocation` is deterministic and
  its slippage is always adverse.
- **`designed_through = DESIGN_THROUGH` (2026-02-13)** on every card, enforced by the model.
- **No macro pin, no release-lag question** — identical to round 43 §10.
- **What this round cannot settle.** Seven cards, one round, price-only conditions already measured
  individually in prior rounds, no true out-of-sample split beyond the walk-forward the ladder already
  provides, and two of fifteen windows in-sample to the hypothesis by construction. A result here
  settles the additivity question for exactly these two conditions on exactly this book, shift size and
  band — it says nothing about whether any other pair of conditionally-fired tilts would stack the same
  way. Nothing here is investment advice.

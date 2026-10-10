# Round 6 — selection: four cards for the paper desk

**Written before round 5 was scored.** That is deliberate and is the single most important thing
about this document. Round 6 is a *selection* round, not a measurement round, and a selection rule
written after seeing the results it will be applied to is not a rule — it is a description of a
choice already made. Every threshold below was fixed while round 5's results directory was still
filling up.

If applying this rule produces an answer that looks wrong, the correct response is to **record that
it looks wrong and apply it anyway**, then argue the rule in round 7. Rounds 3 and 4 both produced
verdicts that the next round overturned; the programme's value is in that being visible, which
requires the rule to be older than the data.

## 1. What round 6 decides

Four cards go on the live paper desk (`backend/app/paperdesk/`), which trades forward from inception
against real market data on a simulated $100k account. It currently runs three, chosen ad hoc.

This is a different decision from every round so far, in three ways that change the criteria:

1. **The desk holds forward indefinitely.** It has no window. Every leaderboard this programme has
   produced ranks cards over a *fixed, ended* period, and four of five rounds used periods under 300
   sessions. The desk's horizon is "until someone turns it off."
2. **The four run simultaneously, so they are a book, not a shortlist.** Round 3 established that the
   interaction between cards matters more than any card's own median. Picking the top four of a
   leaderboard would pick four versions of the same trade — `B-momentum`, `B2`, `B3` and `B4`
   correlate at +0.46 to +1.00 with each other.
3. **It is observed, not scored.** Nobody is ranked at the end. The desk exists to show what these
   strategies actually do, day by day, on data that did not exist when they were designed. That makes
   *legibility* a real criterion: four cards that all do the same thing teach nothing.

## 2. The evidence, and what is wrong with all of it

| round | matrix | what it can support | what it cannot |
|---|---|---|---|
| 1 | 5 regime windows | first ranking | superseded by r2's larger matrix |
| 2 | 8 regime windows | the base ranking, 26 cards | mean benchmark −9.45%: bear-weighted |
| 3 | same 8 windows | the correlation/portfolio finding | same matrix as r2 — not an independent draw |
| 4 | 6 new regime windows | falsified r3's promotions | mean benchmark +17.13%: bull-weighted |
| 5 | 27 horizon windows | the horizon question, 9 falling windows | one era (2013–2026); 10y rung is ~1 sample |

**The governing fact is round 4's:** every leaderboard this programme has produced is conditional on
its matrix's regime mix, and rounds 3 and 4 reversed each other completely on identical frozen cards.
No single round's rank is admissible evidence on its own. Round 6's rule is therefore built entirely
out of **agreement across matrices** rather than out of any one ranking.

Two further constraints carried forward:

- **Sub-5%-exposure cells are not results.** `c12-meanrev-wide` was retired for a +55.3% raw excess
  earned on one trade at 0.6% capital exposure, and `c07-chop`'s best round-4 cell was one trade at
  0.8%. A book that is not invested is not being tested. No slot below may be won on such a cell.
- **The noise floor is ±21.2 points**, from universe ordering alone (`PROTOCOL.md` §7). Any margin
  inside that band decides nothing, and where the rule below produces one, the tie-break applies.

## 3. The rule

Four slots, each with a different job. **A card may fill only one slot**, and each slot is decided by
a stated criterion computed over stated data — no slot is decided by overall rank.

### Slot 1 — the core: rank stability across matrices

The card with the best **worst rank** across the round-2, round-4 and round-5-ladder matrices,
scored on adjusted excess (annualized, on round 5). Ties broken by the better median of the three
ranks, then by the higher median adjusted excess in the round-5 **5y and 10y** rungs.

*Why worst rank rather than mean:* the question this slot answers is "which card has never been
bad," and a mean lets a spectacular bull-matrix result pay for a terrible bear-matrix one. Round 4's
whole finding is that such a trade is a bet on the next regime.

**Eligibility:** must have cleared the gate in all three matrices. A card that could not run round
2's `gfc` on universe history is not disqualified by that alone — the gate, not the full set, is the
bar — but a card missing an entire matrix cannot fill this slot.

### Slot 2 — the horizon anchor: the long rungs

The card with the best median annualized adjusted excess over round 5's **10y and 5y windows**
(5 windows), subject to a mean capital exposure ≥ 0.05.

*Why this slot exists at all:* the desk operates at an unbounded horizon, and this is the only
evidence the programme has ever produced at multi-year holds. If slot 1's winner also wins here, slot
2 goes to the runner-up and that coincidence is reported as a finding — it would be the first time
the short-window leaderboards and the long-horizon result agreed.

### Slot 3 — the diversifier: low correlation, in both directions

Among cards not already selected, the one with the lowest **maximum** per-window return correlation
to the slot-1 and slot-2 cards, computed **separately** on round 4's matrix and round 5's bear arm,
taking the worse (higher) of the two figures. Subject to mean capital exposure ≥ 0.05 and a median
annualized adjusted excess that is not the worst in the field.

*Why the maximum of two matrices:* `c14-riskmanaged-wide` measured ρ = +0.04 to `C-trend` on round
3's windows and ρ = −0.554 on round 4's — the *same two frozen cards*. A correlation from one matrix
is not a property of the pair. Taking the worse figure means a card only wins this slot if it is
uncorrelated on evidence that did not get to choose its own regime.

*Why an exposure floor and a performance floor:* without them this slot reliably selects whichever
card trades least, since a book that is mostly cash is uncorrelated with everything. That is the
`c07`/`c12` pattern and it is not diversification, it is absence.

### Slot 4 — the declared hedge

Among cards not already selected, the best **worst-window** annualized adjusted excess across round
5's **bear arm** (6 windows) and round 2's four falling windows, taking the worse of the two.

This slot is explicitly **expected to lose money in a rising market**, and that expectation is
recorded now so it cannot later be reported as a disappointment. Round 4 already demonstrated the
mechanism: `c14` deployed 28% of capital into a +75% benchmark and posted −19.78% adjusted excess.
A hedge behaves like that. The desk carries one so the book has a leg that is not long equity beta,
and its job is to be judged on the falling weeks, not the rising ones.

### The book check, which can veto

Once four cards are chosen, `strategy-program/tools/portfolio.py` scores them as an equal-weight book
on **every** available matrix — r2, r4, r5-ladder, r5-bear. The result is reported whatever it says.

The one veto: **if the four-card book has a worse worst-window than the slot-1 card alone on more
than one matrix, the selection is rejected and slot 4 is re-drawn from the next candidate.** Round 4
found exactly this failure — round 3's trio was beaten by `B-momentum` alone on every axis — and a
selection rule that cannot detect it would repeat it.

If a second draw also fails the veto, the desk runs **three** cards and the fourth slot is reported
as unfilled, with the reason. Filling a slot with a card that makes the book worse in order to reach
a target number would be the worst possible outcome of this round.

## 4. Anti-selection rules

These bind the person applying the rule, including when the answer is unwelcome.

1. **No card is selected on a single round's result.** Every slot above reads at least two matrices.
2. **No slot is won on a cell below 5% capital exposure.** Check the cell, not just the aggregate.
3. **Every selection must name the matrix it would have lost on.** If a card would not have been
   selected under round 3's evidence, say so beside it.
4. **Margins inside ±21.2 points decide nothing.** Where the top two are within the noise floor, the
   tie-break in the slot's definition applies; if that is also inside the band, prefer the card with
   the **lower** capital exposure, on the grounds that it risks less to produce the same
   indistinguishable number.
5. **The four variants of one base count as one card for slot purposes.** `B-momentum`, `B2`, `B3`
   and `B4` differ by one decision each and correlate up to +1.000. At most one may be on the desk.
6. **No new cards.** Round 6 selects from what has been measured. A card designed for this selection
   would be fitted to five rounds of published results.

## 5. What round 6 produces

1. The four cards, with the slot each fills and the numbers that filled it.
2. For each, the matrix it would have lost on (rule 4.3).
3. The four-card book scored on all four matrices, and the veto check.
4. The desk reconfigured to that roster, and the roster recorded in configuration rather than in
   source.
5. An explicit list of what this selection is **not** evidence of.

## 6. What round 6 cannot settle, stated in advance

- **It is still not out-of-sample.** Every matrix it reads ends on or before 2026-02-13, and the
  design cutoff has not moved since round 2. The selection is the best available *retrospective*
  choice; the desk is what turns it into a forward test, and that test has not started yet.
- **Four cards from a field of fifteen, chosen on four matrices, is a small selection from a small
  sample.** The rule is designed to be robust rather than optimal, and a robust rule on thin evidence
  is still a rule on thin evidence.
- **The desk's own result will be one path.** However the four perform from inception, that is one
  realisation, not a distribution, and it will be tempting to read it as a verdict on this rule. It
  is not one, and this paragraph exists to be quoted back when someone does.
- **Nothing here is a claim about what anyone should own.** These are simulated books on a paper
  account, selected to be informative to watch, not to be held.

---

## 7. Amendments made before execution (revision 2)

The rule above was pre-registered before round 5 was scored. Round 5's results and the live paper
desk then supplied evidence the original rule could not have used, and two changes were made **before
the rule was run**. Both are recorded here rather than edited silently into the text above, so the
original and the amended version stay separately readable.

### 7.1 Slots 1 and 2 replaced by Gate A: long-horizon, dual-benchmark

*Original:* slot 1 on rank stability across matrices, slot 2 on the 5y/10y rungs, each a separate
seat.

*Amended:* a single admission gate — a **positive median annualized adjusted excess at both the 5y
and 10y rungs, against both SPY and QQQ** — and the seats filled from whoever clears it.

*Why:* round 5 §2.1 showed the field's best annualized figure falls from +31.6% at one year to +7.6%
at ten, so a criterion reading short windows selects on the rung where noise is largest; and §3
showed that swapping SPY for QQQ roughly halves every AI/semis book's edge, with `A-rotation`'s
decade figure going from +5.28% to **+0.63%**. A gate that does not ask for both is not asking much.

The original slot-2 tie-break also produced a bad answer on its own terms — it seated `C-trend`
alongside `B-momentum`, two books that correlate at +0.909.

### 7.2 Gate B added: a hard correlation cap of +0.70 between any two desk cards

*Original:* one diversifier slot chosen on lowest correlation; nothing stopped the other three seats
from being mutually redundant.

*Amended:* **no two cards on the desk may exceed ρ = +0.70** on any matrix, taking the maximum across
round 4's matrix, round 5's ladder and round 5's bear arm.

*Why:* the live desk. The current roster holds `B-momentum` and `C-trend`, ρ = +0.909, and over 55
live sessions they returned −5.21% and −7.24% — the same trade, twice, into the same rotation. A rule
that permits that is not selecting a book.

### 7.3 What was **not** amended, and should have been

The hedge slot's exposure floor is measured on **historical** windows. `c14-riskmanaged-wide` clears
it on the backtest bear arm (20.06% mean exposure, 52 trades) and has taken **zero trades in 55 live
sessions**, sitting entirely in cash.

This was noticed *after* the rule had already selected `c14`, and it was therefore left alone rather
than patched — §1's opening paragraph is explicit that a rule edited after seeing what it selects is
not a rule. It is logged as the first item for round 7: **a desk card must be shown to trade in the
regime it is about to be run in**, not merely in the windows it was scored on.

The same discipline was applied to `c20-rotation`, which has the strongest hedge signature in the
programme (+14.8-point bear-minus-ladder swing) and was excluded by Gate B on a single round-4 raw
correlation of +0.917 — a statistic round 5 gave specific reason to distrust, since the same pair
reads −0.591 on the annualized bear arm. It was excluded anyway, and flagged for round 7.

The executed result is in `data/rounds/r6-2026-08/SELECTION.md`.

# Round 12 — distinctness, restated over holdings

**Not investment advice.** Simulated books on a paper account, selected to be informative to watch.
I am not a licensed financial adviser and none of this is a recommendation about real capital.

**Pre-registered 2026-08-22, before any round-12 selection has been run.** §5 discloses in full the
one computation that *was* run before this document was written — a feasibility check against round
11's already-published field — and states what it changed and what it did not.

---

## 1. Why distinctness needs replacing

Rounds 6–11 decided "is this a different idea?" with two proxies: `StrategyCard.discipline`, and a
base-family map treating the four `B` variants as one entry. **Both classify a card by what it
descends from, not by what it shows the reader**, and both have now failed on that axis.

- **Round 8 flagged the discipline clause** as possibly excluding the wrong pairing
  (`C-trend` / `H-trend-diversified`) and left it open. It is still open.
- **Round 11 §8 broke the base-family clause.** `B3-concentrated` and `B-momentum` are one family and
  therefore mutually exclusive under the rule, while their holdings differ by two names in six. The
  owner seated both; the rule had no way to express why that was reasonable.

This is the **second rule in three rounds to fail on the same axis** — round 10 §2 records the first,
where Gate S ranked globally while distinctness worked per discipline and the two selected against
each other.

## 2. This is not round 7's overlap cap revived

Round 7 used a 25%-of-book holdings-overlap cap and **round 8 retired it outright**. Reviving a
retired rule under a new name is exactly what this programme exists to catch, so the difference is
stated before the rule is.

**Round 8's stated reason for retiring it** (`data/rounds/r8-2026-08/SELECTION.md`): the cap answered
*"would this pair make one portfolio too concentrated"* — a question that does not apply to reference
signals nobody combines. **That reasoning is correct and nothing here disputes it.** There is no
combined book, so there is no concentration risk to cap.

**The question round 12 asks is a different one that happens to use the same measurement:** *would a
reader learn anything from the second panel that the first did not already show them?* That is a
property of the desk as a **display**, not as a book. It applies exactly as much to signals nobody
holds together as to positions somebody does, and it is the question the owner was actually answering
in round 11 §8 when the base-family rule could not.

**Round 8's second objection — that the cap cost roughly nine points of out-of-sample return by
dropping `A-rotation`** — is answered by where the measurement sits, not by arguing with it. Under
round 12, **overlap never chooses between cards.** The ranking does that and runs first. Overlap only
asks whether a card *already beaten* by a seated one still adds something to look at. A card cannot be
dropped in favour of a worse one, which is precisely what happened in round 7.

Round 7 §9.4 proposed re-opening the cap as a **sizing** rule (capping combined weight in shared
symbols) instead of an exclusion. Round 12 does not do that: sizing a combined book is portfolio
mathematics again, and there is still no combined book.

## 3. The rule

**Replaces both the discipline clause and the base-family clause.** One rule, stated over holdings.

Every other clause is unchanged from round 11: Gate A and Gate L as backtest floors, Gate C as the
live consistency clause, Gate S′ as a tie-break, the ranking on median live adjusted excess, and the
seat count an output capped at four with no floor.

### Novelty

For a candidate `C` and the set `S` of cards already seated, over each session `t` of the live
out-of-sample window:

```
novel_names(C) = mean over invested sessions of  | H_C(t) \ ∪_{s∈S} H_s(t) |
```

**Seat `C` if `novel_names(C) >= 1.0`.**

### Why a count and not a percentage

A percentage needs a threshold nobody can derive, and on this field the choice between 20% and 34% is
exactly the choice between seating the owner's fifth card and not — the kind of free parameter this
programme has twice had to unpick.

A count has a natural unit: **one whole position.** A panel earns its place by showing, on average,
at least one name that no other panel shows. That is the smallest thing a reader could learn from it,
and it is not a number anyone picked.

The count also self-adjusts for slot count, which a fraction does not: one new name out of four is
25% and one out of six is 17%, but both are the same single thing to look at, and a fixed percentage
would hold a wide card to a stricter standard than a narrow one for no reason connected to what
either shows.

### Why asymmetric, and why against the union

**Asymmetric.** A card holding six names, four of which a seated card also holds, shows two new
things. The same pair in the other order shows *nothing* new — the narrower card's names are all
already on the page. Jaccard and the overlap coefficient collapse those two cases into one number and
cannot express "seat the wide one, then the narrow one adds nothing", which is the exact `B`-variant
case that broke the old rule.

**Against the union of everything seated**, not pairwise, because the question is what is already on
the page — not what any single other panel holds.

### Measured across every session, not today

Round 7's cap was computed on one day's holdings, and §9.2 of that document named this as its main
weakness: *"Two cards that overlap now may not in three months."* Round 12 reconstructs each card's
held set per session from its trade log across the whole 127-session live window, so a pair that
converges on one date is not mistaken for a pair that tracks each other for six months.

Sessions where a candidate holds nothing are **skipped**, not scored zero or one: a card in cash is
neither showing a new name nor repeating one, and counting those sessions either way would turn
novelty into a measure of how often a card is invested.

## 4. What this rule cannot do

- **It cannot assess a card that has not traded live.** Novelty is computed from the live window, so a
  new candidate — the contribution-funded families in `data/rounds/r12-2026-08/ROTH-CANDIDATES.md`,
  for instance — has no holdings to measure. Such a card must either be seated outside the competition
  the way `ladder-qld-schd` is, or have its distinctness measured on backtest holdings over a window
  common to it and every seated card. **Round 12 does not decide which; that is a genuine gap and it
  is named here rather than discovered later.**
- **It measures names, not weights.** A card holding the same names at very different position sizes
  scores zero novelty, even though the conviction it expresses is different. `B3-concentrated` against
  `B-momentum` is exactly that case, and under this rule the narrower card is redundant *if the wider
  one is seated first*. The ranking decides which comes first, so this is a real dependency on rank
  order and not a symmetric judgement.
- **Order-dependence can reject a card a laxer walk would seat.** Because novelty is measured against
  the union of what is already seated, a card's score falls as the desk fills. At a high enough
  threshold this produces perverse orderings — see the 1.50 column in §5, where a strong card is
  rejected and a weaker one seated. The rule is only sound at a threshold low enough that this does
  not bite, which is a constraint on the threshold, not a free choice within it.
- **One market environment.** The live window is six months of one regime, and every limitation round
  11 §4 records about that applies here unchanged.

## 5. Feasibility check — disclosed in full

Run against round 11's published field **before this document was written**, because a rule that
produces a perverse roster is broken regardless of how principled it reads. This is a check on the
rule, not a round-12 result.

`strategy-program/tools/holdings_overlap.py`; output in `data/rounds/r12-2026-08/holdings-overlap.txt`.

### Novel names, row given column alone

| | B3-conc | B-mom | B4-tight | B2-hold | A-rot | C-trend |
|---|---|---|---|---|---|---|
| `B3-concentrated` | — | **0.00** | **0.00** | 0.22 | 2.14 | 2.06 |
| `B-momentum` | 1.32 | — | **0.00** | 0.22 | 3.37 | 3.23 |
| `B4-tight-stop` | 1.32 | **0.00** | — | 0.22 | 3.37 | 3.23 |
| `B2-hold-90` | 1.41 | 0.08 | 0.08 | — | 3.17 | 3.03 |
| `A-rotation` | 1.42 | 1.32 | 1.32 | 1.26 | — | 1.81 |
| `C-trend` | 1.84 | 1.64 | 1.64 | 1.56 | 2.46 | — |

**`B4-tight-stop` and `B-momentum` held identical books on all 127 sessions** — 0.00 novel names in
both directions, mean daily Jaccard **100%**. Over six months the tighter stop never once changed a
holding. That is consistent with `strategy-program/VARIANT-DISCRIMINATION.md`'s finding that the
8%-versus-12% stop rarely binds because most adverse moves clear both thresholds together, and it is
the single clearest case for a holdings-based rule: no proxy for "different idea" could have said
this, and the two cards are indistinguishable as displays.

**`B3-concentrated` shows nothing `B-momentum` does not**, across the whole window and not merely on
the snapshot round 11 §8 quoted.

### The walk, at three thresholds

| threshold | seats |
|---|---|
| ≥ 0.50 novel names | `B3-concentrated`, `B-momentum`, `A-rotation`, `C-trend` |
| **≥ 1.00 (the rule)** | **`B3-concentrated`, `B-momentum`, `A-rotation`, `C-trend`** |
| ≥ 1.50 | `B3-concentrated`, `C-trend` — and it rejects `A-rotation` at 1.42 while seating `C-trend` at 1.84, the order-dependence pathology of §4 |

**The roster is identical at 0.50 and 1.00.** That stability is the argument for the count: the same
walk stated as a percentage gave four seats at 20% and three at 34%, so the answer sat on the
threshold. It does not here.

### The result reproduces the owner's overridden roster, and that deserves suspicion

The rule seats `B3-concentrated`, `B-momentum`, `A-rotation` and `C-trend` — **exactly the four
`StrategyCard`s the desk currently trades**, which reached that state through an owner override of the
rule this document replaces. A reader is entitled to suspect the rule was fitted to ratify that
decision.

What can be offered against that suspicion is a matter of record, not argument:

1. **The threshold was fixed by a unit, not a number** — one whole position — and §5's sensitivity
   shows the roster is unchanged at half that bar. It is not balanced on the chosen value.
2. **The rule rejects things.** `B4-tight-stop` and `B2-hold-90` clear every other gate and are
   excluded here at 0.00 and 0.08 novel names. A rule fitted to produce a wanted roster would not need
   to be able to say no.
3. **It also reproduces a decision the owner argued *against* the rule for**, which is the point: the
   owner's stated reason in round 11 §8 was that the two `B` cards differ in what they hold. This rule
   is that reason, made measurable. Agreeing with a specific, checkable argument is different from
   agreeing with a preference.

What cannot be offered: this is one field, one window, and the first outing of the rule. **If round 12
seats the same four cards, that is not independent confirmation of anything** — it is the same
evidence read through a rule written after seeing it.

## 6. For whoever runs round 13

1. **Decide how a card with no live record is assessed** (§4, first bullet). This blocks every new
   candidate the programme has produced since round 5, and it is now the binding constraint on
   widening the field — which rounds 10, 11 and 12 all name as the real problem.
2. **Consider whether `B4-tight-stop` should remain in the field at all.** A card that held an
   identical book to another card on all 127 sessions is not a distinct entry in a competition; it is
   a duplicate row. Retiring it, or re-designing it so its stop can actually bind, are both better
   than carrying it.
3. **Weights, not just names** (§4, second bullet). The one thing this rule provably cannot see is the
   difference between four positions at 22% and six at 15% — which is the exact difference between the
   two cards on the desk it seats together.

# Round 16 — what the cash constraint is worth

**Not investment advice.** Simulated books on a paper account. I am not a licensed financial adviser
and none of this is a recommendation about real capital.

**Pre-registered 2026-08-24, before any round-16 run exists.** Every figure below is a property of
round 15's committed record, the engine source, or the bar store — never of a round-16 result.

---

## 1. What this round is asking

Round 15 shipped every savings and Roth figure with a caveat stamped on the file:
`cash_constraint_modelled: false`. This round removes the caveat by measuring it.

`contributions.simulate` and `run_allocation` agree exactly about **what to hold** — round 15's
weight gate put 753 comparisons at zero mismatches, worst gap zero. They disagree about what happens
when you cannot afford it. In round 15's own control window, `run_allocation` rejected **58 buy
orders for insufficient cash** while `simulate` rebalanced to target every time.

The mechanism is visible in the source. `contributions.simulate`'s rebalance branch is:

    for s in symbols:
        move = desired[s] - holdings[s]
        holdings[s] += move
        cash -= move + cost

There is no check that `cash` covers `move`, and symbols are walked in dict order, so the book can
buy before it has sold. Across the whole book the moves net out — but a real account cannot spend
proceeds it has not received.

So:

> **How much of round 15's savings and Roth result is an artifact of an account that can always
> afford to rebalance?**

## 2. Why this is worth a round rather than a footnote

Round 15's headline finding was that the monthly drip **lost** to an equivalent lump sum in two of
three windows, winning only in `h5y-3` — the one window containing a bear market.

That win is precisely the case where the bias should bite hardest. A drip's advantage is buying a
fallen sleeve; a real account buying a fallen sleeve in a drawdown is exactly when the cash is not
there, because the sleeve it would sell to fund the purchase has fallen too. The unconstrained
harness credits the strategy with a rebalance a real account would have failed to make.

**If the bias is large, round 15's P1 result changes sign or magnitude.** That is a live risk to a
committed finding, not a tidy-up.

## 3. What gets built

A `cash_constrained: bool = False` mode in `contributions.simulate`. Default `False`, so **every
round-15 number stays reproducible** and all six existing family-script callers are untouched.

Under `cash_constrained=True`:

1. **Sells execute before buys.** Not dict order.
2. **Buys are capped at available cash.** A buy that cannot be funded is partially filled or skipped,
   and the shortfall is counted, not silently absorbed.
3. **A rejection counter** on `ContributionResult`, so the bias has a mechanism attached to it rather
   than only a size. A result reporting a 3-point drag and 200 rejections is a different claim from
   one reporting a 3-point drag and two.

**Settlement lag is deliberately NOT modelled in this round.** T+1 would be more faithful and is a
second variable; introducing it at the same time as the cash cap would leave the round unable to say
which of the two caused what it measures. If the cash cap alone does not close the gap to
`run_allocation`, settlement is the pre-registered next suspect.

## 4. The control

Round 15's gate 2 is the control, re-run:

    run_allocation:            ending 86510.30   rejections 58
    contributions.simulate:    ending 85942.19   rebalances 2
    relative divergence: 0.6567%

**Pre-registered expectation: with `cash_constrained=True`, that divergence shrinks.** If it does
not, the cash cap is not what separates the two paths and the round's premise is wrong — which is a
result, and must be reported as one rather than patched around.

The weight gate must also still pass at zero. A cash constraint changes what gets *filled*; it must
not change what the card *wants*. If `r15_weight_gate.py` moves off zero, the change has leaked into
the wrong layer.

## 5. What gets run

Every round-15 contribution cell, both ways — `cash_constrained` False and True — over the same five
long windows, same cards, same drip sizes. The comparison is paired: same card, same window, same
schedule, one variable.

The trading arm is not re-run. It already goes through `run_allocation`'s real cash account, so it
has no such bias to measure.

## 6. What this round predicts, in advance

1. **The bias is real and one-directional: every cash-constrained figure will be ≤ its unconstrained
   twin.** Falsified if any card improves under the constraint.

2. **The bias will be largest for `qld-schd-sgov`**, the card holding 35% in a 2×-leveraged sleeve,
   because its rebalances are the largest relative to book size and its drawdowns the deepest.
   Falsified if a lower-volatility card takes a bigger hit.

3. **Round 15's P1 will survive in direction but shrink in magnitude.** The drip's `h5y-3` win of
   +2.52 points should narrow, because that window is where the constraint bites hardest. Falsified
   if P1 reverses outright — which would mean round 15's headline was an artifact and must be
   corrected in its own record, not quietly superseded here.

4. **The `r15_control.py` divergence falls below 0.30%**, less than half its current 0.6567%.
   Falsified if it stays above 0.50%, which would indicate settlement lag rather than the cash cap
   is the dominant term.

## 7. What this round does not do

- **It does not amend round 15's numbers.** They were correctly labelled with the caveat they carry.
  If prediction 3 is falsified, round 15's `SELECTION.md` gets a dated correction pointing here —
  the record is amended in the open, never rewritten.
- **It does not model settlement lag**, for the reason in §3.
- **It does not promote anything.** `PROTOCOL.md` §6 still requires two consecutive rounds on
  differing window sets, and round 16 re-uses round 15's windows by design — the whole point is a
  paired comparison, which makes it explicitly *not* the second independent measurement §6(b)
  requires.

---

**Not investment advice.**

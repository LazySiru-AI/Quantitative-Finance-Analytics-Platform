# Round 16 — what the cash constraint is worth

**Not investment advice.** Simulated books on a paper account. I am not a licensed financial adviser
and none of this is a recommendation about real capital.

Pre-registered in `strategy-program/ROUND-16-PLAN.md` on 2026-08-24, before any run existed. Run
2026-08-24.

---

## 1. The answer: nothing. It never fires.

Round 15 shipped every savings and Roth figure stamped `cash_constraint_modelled: false`, on the
argument that the harness always affords a rebalance a real account sometimes cannot. Round 16 built
the constraint and measured it across all 31 contribution cells — same cards, same windows, same
drip sizes, one variable.

    regression check: all 31 unconstrained cells reproduce round 15 exactly

    P1(bias is one-directional): 0 worse, 0 better, 31 unchanged
      mean drag  : +0.000 pp
      worst drag : -0.000 pp
      underfunded buys, every cell: 0 ($0)

**Zero underfunded buys in 31 cells.** Not a small bias — no bias, because the constraint never
binds.

### Why, having measured rather than assumed

Two mechanisms already made the harness cash-safe, and neither was noticed when round 15 wrote its
caveat:

1. The contribution pre-buy step already spends only `min(cash, need)`. It could never overdraw.
2. The band-breach rebalance nets to zero across the book by construction — targets sum to at most
   1 of equity, so `sum(move) = cash` when fully invested. With sells executing before buys, the
   proceeds are always there before the buys need them.

The unconstrained path could overdraw only *transiently*, mid-loop, because it walked symbols in
dict order and could buy before selling. Netted across the session it always balanced. Ordering the
sells first removes the transient — and changes no outcome, because the transient never had one.

## 2. So round 15's stated cause was wrong

Round 15 attributed the 0.6567% divergence between `contributions.simulate` and `run_allocation` to
the cash constraint, citing the 58 `insufficient_cash` rejections the real broker logged. The
rejections are real. The inference was not: **the aggregate cash was never the binding constraint.**

`r15_control.py` re-run after this change still reports:

    relative divergence: 0.6567%

Unchanged, because the control does not opt into the constraint — and now known to be unchangeable
by it. Whatever separates the two paths is something else. The named suspects, in order:

- **Whole-share fills.** `PaperBroker` transacts shares; the harness transacts dollars. A rebalance
  needing 3.7 shares gets 3, and the residual accumulates.
- **Settlement lag.** Deliberately excluded from this round (plan §3) to keep one variable. Still
  unexcluded as a cause.
- **The decide/fill lag.** The engine decides at one session's close and fills at the next open; the
  harness works on closes only. Named in round 15's control as the tolerance's justification.

That the 58 rejections coexist with zero aggregate cash shortfall is itself the clue: a broker that
rejects a buy it cannot fund *in whole shares at the open* is not the same as a book that cannot
fund it *in dollars at the close*.

## 3. What was predicted, and what happened

| # | Prediction | Verdict |
|---|---|---|
| 1 | The bias is real and one-directional; every constrained figure ≤ its twin | **FALSIFIED** — zero, not small |
| 2 | The bias is largest for `qld-schd-sgov`, the leveraged card | **FALSIFIED** — no card took any hit |
| 3 | Round 15's P1 survives in direction but shrinks in magnitude | **HALF** — survives exactly; magnitude does not shrink at all |
| 4 | `r15_control.py` divergence falls below 0.30% | **FALSIFIED** — unchanged at 0.6567% |

Three falsified outright and one half-right, from four predictions written down first. The round's
premise — that the cash constraint was the missing term — was wrong, and it was wrong in a way that
only a measurement could show, because the mechanism it named (58 real rejections) genuinely exists.

Prediction 4 named its own consequence in advance: "*falsified if it stays above 0.50%, which would
indicate settlement lag rather than the cash cap is the dominant term.*" That is now the standing
hypothesis, and it is a better one than round 16 started with.

## 4. The defect this round found in round 15

Building the paired comparison surfaced something the round was not looking for.

Round 15's runner created one `card_weight_fn` per **card** and reused it across all five windows.
For an `AllocationCard` that is harmless — its closure is stateless, and every one of the 26
allocation cells reproduced exactly. **`LadderCard`'s closure is a state machine**, carrying armed
rung depth and the cycle-starting high. Each window therefore inherited the previous window's state.

Isolated directly:

    SHARED closure  : run1 cagr=11.6330%  run2 cagr=26.5207%   same=False
    FRESH closures  : run1 cagr=11.6330%  run2 cagr=11.6330%   same=True

The corrected figures, and the diagnostic pattern that confirms the cause:

| window | round 15 | corrected | delta | QQQ | beat QQQ? |
|---|---|---|---|---|---|
| h10y-1 | 8.14% | 8.14% | **+0.00** | 17.43% | no |
| h10y-2 | 18.53% | 10.64% | −7.90 | 19.65% | no |
| h5y-1 | 22.16% | 6.09% | **−16.07** | 19.76% | no |
| h5y-2 | 27.36% | 11.63% | −15.73 | 27.46% | no |
| h5y-3 | 16.96% | 9.77% | −7.19 | 12.42% | no |

**`h10y-1` is unchanged because it ran first, with a fresh closure.** Every later window is
contaminated. That is not a story fitted to the data — it is the signature the hypothesis predicted
before the table was built.

### What it changes in round 15

Round 15's **P4 verdict still holds**, and holds more strongly: it predicted no candidate would beat
QQQ on both return and drawdown, and the corrected figures show `ladder-sso-vig-bnd` never beat QQQ
on **either**, in any window. But round 15's supporting discussion — that the card "beat QQQ on
return in two of five windows" and that "its case rests on return, and drawdown is the bill" — is
**false and has been corrected in that round's own record**.

Nothing else in round 15 moves. P1, P2 and P3 concern the savings arm and the allocation cards,
every one of which reproduced to the last digit.

The original records are kept, not deleted, at
`data/rounds/r15-2026-08/contributions/roth-CONTAMINATED-INVALID/` — the same convention round 11
used for the instrument D5 retired.

## 5. What this round leaves

- **The 0.66% divergence is still unexplained**, and now has a shorter list of suspects. Whole-share
  fills are testable cheaply: run `r15_control.py` with `allow_fractional_shares=False` toggled on
  the engine side and see whether the gap moves.
- **`cash_constrained=True` stays in the harness** even though it changed nothing here. It costs one
  branch, it is proven inert on this field of cards, and a future card with a larger rebalance
  relative to its book may well bind where these did not. An invariant that never fires today is
  cheap insurance; an invariant nobody wrote is not.
- **Nothing is promoted.** Round 16 re-uses round 15's windows by design — a paired comparison is
  explicitly not the second independent measurement `PROTOCOL.md` §6(b) requires.

---

## FOLLOW-UP, same day: the divergence is settlement, and this round's suspect list was wrong

Round 16 left the 0.6567% gap unexplained and listed three suspects in order. **The first was wrong
when it was written, the third is now eliminated by measurement, and the second is confirmed.**

### Suspect 1, whole-share fills — wrong, and already controlled for

`r15_control.py:168` passes `allow_fractional_shares=True`, with its own comment saying why: *"no
whole-share flooring noise -- simulate() has none either."* The control has been eliminating that
term since it was written. Naming it as the leading candidate was an error of not re-reading the
control being explained — the same species of error as reading a phase heading instead of a phase
body.

### Suspect 3, the decide/fill lag — eliminated by measurement

`r16_fill_lag.py` runs the identical card and window through `simulate` twice, changing only the
price each target transacts at: today's `close[i]` against `open[i+1]`, which is what the engine
actually fills at. Weights are untouched — `r15_weight_gate.py` proved those match exactly.

    run_allocation (engine)              ending 86,547.09   rejections 59
    simulate @ close[i]   (today)        ending 85,942.19   rebalances 2
    simulate @ open[i+1]  (engine fill)  ending 85,930.70   rebalances 1

    vs engine, close[i]   :  -604.90  (-0.6989%)
    vs engine, open[i+1]  :  -616.39  (-0.7122%)

Adopting the engine's own fill convention made the gap **1.9% worse**, not better. The fill
convention is not the term.

### Suspect 2, settlement — confirmed, with the mechanism

The engine rejects **59 orders, all `insufficient_cash`**, with fractional shares enabled and every
friction zeroed. Round 16's own cash-constrained mode recorded **zero** underfunded buys across 31
cells. Both are true, and the only way they can both be true is that the engine's constraint is one
the cash cap does not model.

`backend/app/paper/paperbroker.py` says what it is:

```python
self._unsettled: list[tuple[dt.date, Decimal]] = []
"""``(available_on, amount)`` for sale proceeds not yet settled. A cash account cannot
   rebuy with unsettled proceeds without triggering a good-faith violation..."""

available = self.settled_cash(fill_date)          # line 412 -- buys check SETTLED cash
"...unsettled proceeds are not spendable in a cash account"   # line 439, the rejection text
```

A band rebalance sells one sleeve to fund another. The engine cannot spend those proceeds for
`settlement_days`; the harness spends them the same session. Round 16 implemented sells-before-buys
with an instant-cash cap — **settlement-free by construction** — which is precisely why it never
bound. The round excluded settlement deliberately, to keep one variable, and in doing so excluded
the only variable that mattered.

### What this means for the round's conclusion

Round 16's headline stands: **the cash constraint as implemented is worth nothing**, zero across 31
cells. What changes is the interpretation. That result is not evidence that a real account's
funding constraint is immaterial — it is evidence that *a cash cap without settlement is not the
constraint a real account has*. The optimistic bias round 15 warned about is real; round 16 built
the wrong instrument to measure it, and now knows which one to build.

The savings and Roth figures therefore still carry `cash_constraint_modelled: false`, and it is
still true. Nothing in this follow-up changes a single measured number.

**Next, concretely:** give `contributions.simulate` a settlement lag, not just a cash cap, and
re-run this comparison. The prediction to write down first is that the gap closes materially — and
if it does not, the remaining term is something none of the three suspects named.

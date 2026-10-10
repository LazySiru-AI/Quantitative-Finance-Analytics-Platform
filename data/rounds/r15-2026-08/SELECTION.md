# Round 15 — three accounts, three scoring bases

**Not investment advice.** Simulated books on a paper account. I am not a licensed financial adviser
and none of this is a recommendation about real capital.

Pre-registered in `strategy-program/ROUND-15-PLAN.md` on 2026-08-24, before any run existed. Run
2026-08-24. Nothing below overrides the plan; where a result contradicts it, the plan wins and the
prediction is recorded as falsified.

---

## 1. The gates, first

Every other figure here is unreadable if these two failed.

**Gate 1 — does the bridge compute the engine's weights?** `strategy-program/tools/r15_weight_gate.py`,
`qld-schd-sgov` over 251 sessions of 2022:

    comparisons     : 753
    weight mismatches (>1e-9): 0
    worst absolute weight gap: 0

Exact. Not "within tolerance" — zero. The plan's §7 asked for agreement "to within rounding", and on
the question of *what to hold*, the bridge meets that standard with nothing to round.

**Gate 2 — do the two account models agree on ending equity?** `r15_control.py`, same card, same
window, contributions zeroed:

    run_allocation:            ending 86510.30   rejections 58
    contributions.simulate:    ending 85942.19   rebalances 2
    relative divergence: 0.6567%   tolerance 1.00%   PASS

That is a pass against a tolerance fixed before the run, but it is **not** "within rounding", and
the reason matters more than the number. `run_allocation` drives a real `PaperBroker` cash account
and rejected **58 buy orders it could not fund** as QLD fell and SCHD ran out of room to finance
top-ups. `contributions.simulate` has no cash constraint whatever and always rebalances to target.

Gate 1 proves the two paths agree about what to hold. Gate 2 measures what happens when you cannot
afford it, and they do not agree about that at all.

### The consequence, stated once and carried on every record

**Every savings and Roth number in this round is systematically optimistic**, and most optimistic
exactly where it matters least defensibly: a deep drawdown in a leveraged sleeve is when rebalancing
to target is both most valuable and least affordable, and the harness always manages it. This is a
property of the measuring instrument, not of the strategies. It is stamped on every contribution
record as `cash_constraint_modelled: false` rather than left in a document nobody re-reads.

## 2. What was predicted, and what happened

| # | Prediction | Verdict |
|---|---|---|
| 1 | `qld-schd-sgov` ranks **better** under a monthly drip than a lump sum | **FALSIFIED** |
| 2 | IRR and time-weighted CAGR diverge >2pp on ≥1 card, largest for the highest-drawdown card | **HELD**, both clauses |
| 3 | The $500 and $1,000 savings arms produce the same ordering | **HELD** |
| 4 | No candidate beats QQQ on **both** return and drawdown | **HELD** |

### P1, falsified — and this is the round's most useful result

Same card, same windows, same harness; only the funding shape differs. A lump sum of the identical
total money against the monthly drip:

| window | monthly IRR | lump IRR | delta |
|---|---|---|---|
| h10y-1 | 11.45% | 14.23% | **−2.78** |
| h10y-2 | 15.19% | 15.99% | **−0.80** |
| h5y-3 | 12.79% | 10.27% | **+2.52** |

The stated reasoning was "a drip buys more of a sleeve that has fallen". That mechanism is real and
visible in `h5y-3` — the only one of the three windows containing a bear market, where the drip wins
by 2.52 points. It is simply not the dominant term. Across both decade windows the cost of being
*out* of a rising market swamps the benefit of buying its dips, and the drip loses.

Comparing against `run_allocation` would have confounded funding shape with execution model, so the
lump-sum arm was run through the **same** harness with `contribution=0` and the whole sum seeded.
The only thing that differs between the two columns is when the money arrived.

**So the answer to the round's central question is yes, funding shape changes the answer — in the
opposite direction to the one predicted.** A card selected on lump-sum evidence is not automatically
the right card for an account that receives a monthly deposit, and vice versa.

### P2, held on both clauses

Exactly one card exceeds 2 points of IRR/CAGR divergence, and it is the one holding 35% in a
2×-leveraged sleeve:

    qld-schd-sgov                  3.11 pp
    spy-schd-agg-gld-bil-static    1.86 pp
    ladder-sso-vig-bnd             1.19 pp
    sso-vig-bnd-mean-reversion     0.87 pp
    sso-vig-bnd-static             0.82 pp

Reporting only one of the two figures would have moved `qld-schd-sgov` by 3.11 points in whichever
direction flattered it. `PROTOCOL.md` §7 requires both; this is what that rule is for.

### P3, held

| window | $1,000/mo | $500/mo |
|---|---|---|
| h10y-1 | qld-schd-sgov (11.45%) > spy-static (6.45%) | qld-schd-sgov (12.81%) > spy-static (6.41%) |
| h10y-2 | qld-schd-sgov (15.19%) > spy-static (9.52%) | qld-schd-sgov (15.61%) > spy-static (9.52%) |
| h5y-3 | qld-schd-sgov (12.79%) > spy-static (10.01%) | qld-schd-sgov (12.11%) > spy-static (9.43%) |

Ordering identical at both drip sizes in all three windows, even though `qld-schd-sgov`'s own IRR
moves 1.36 points between them in `h10y-1`. Magnitudes are a property of the schedule; the ranking
is a property of the strategies.

### P4, held — but only on the second clause

`ladder-sso-vig-bnd` beat QQQ **on return** in two of five windows. It never beat it on drawdown:

| window | ladder CAGR | QQQ CAGR | ladder maxDD | QQQ maxDD |
|---|---|---|---|---|
| h5y-1 | **22.16%** | 19.76% | −27.04% | **−16.36%** |
| h5y-3 | **16.96%** | 12.42% | −44.75% | **−35.62%** |

The prediction's falsification condition required both. It bought 2.40 and 4.54 points of annual
return with 10.7 and 9.1 extra points of drawdown, which is what a 2× sleeve is for and what it
costs. The plan's framing — "the case for every one of them will rest on drawdown instead" — is
exactly backwards for this card: its case rests on *return*, and drawdown is the bill.

## 3. Do conditional tilts earn their complexity?

Each purpose fielded a matched pair, identical sleeves, differing only in whether tilt rules exist.
That is `PROTOCOL.md` §7's "isolate exactly one decision", asked three times under three funding
shapes.

**Roth — yes, consistently, and cheaply.** `sso-vig-bnd-mean-reversion` beat `sso-vig-bnd-static`
in **5 of 5** windows, by +0.27 to +0.65 points of CAGR, for about 1.5 points of extra drawdown
(−37.83% vs −36.35%). Small, one-directional, and it never lost.

**Trading — mixed, and it depends entirely on the regime.** `qqq-ief-gld-atr-tilt` against
`qqq-ief-gld-static` over the eight main windows:

| window | tilt | static | tilt worth |
|---|---|---|---|
| gfc | −20.53% | −24.18% | **+3.65** |
| q4-2018 | −9.84% | −10.55% | +0.71 |
| bear-2022 | −24.38% | −24.60% | +0.22 |
| chop-2015 | +3.10% | +3.17% | −0.07 |
| bull-2024 | +15.49% | +16.64% | −1.15 |
| chop-2011 | +8.44% | +9.84% | −1.40 |
| covid | +5.67% | +7.82% | −2.15 |
| recent | +20.59% | +20.59% | **0.00** |

It pays in the two deepest drawdowns and charges in every rally. In `recent` the two are identical
to the last decimal — the ATR gate never fired once in that window, so the card was its own static
twin for a full year. A tilt that does nothing for a year is not free: it is an unexercised claim
on the reader's attention and a parameter in the budget.

### The trading leaderboard, which sharpens the point

Ranked on median excess over the eight main windows -- `adjusted_excess` is unavailable to an
invested-value book by construction, and the reader raises rather than substituting a number:

| # | card | median excess |
|---|---|---|
| 1 | `ladder-qld-schd` | +6.76% |
| 2 | `qqq-ief-gld-static` | +6.35% |
| 3 | `qqq-ief-gld-atr-tilt` | +5.81% |

**The tilted card ranks last, behind its own static twin.** The window table above shows why: the
tilt's whole contribution is concentrated in two tail events, and the median is precisely the
statistic that ignores tails. Whether that is a defect or the entire point depends on what the
account is for -- which is the question this round exists to ask, and is not answered by the
ranking column.

`rank_by=excess-per-exposure` is refused for this round rather than computed. An allocation book's
capital exposure sits near 1.0 for its whole life, so dividing by it is nearly a no-op, and a
column still labelled "excess per exposure" would stop discriminating between strategies while
claiming to.

## 4. What did not run, and why that is a result

**`spy-schd-agg-gld-bil-atr-tilt` did not run in the savings arm at all.** Both its rules gate on
`atr(14)`, ATR needs high and low, and `contributions.simulate` passes closes only. The bridge
raises rather than evaluating it:

> condition 'atr(14) > close * 0.018' uses indicator 'atr', which this bridge does not support --
> only ['bb', 'ema', 'macd', 'rsi', 'sma'] are computable from closes alone.

The alternative was to let the tilts silently never fire, which would have scored it as its own
static twin and answered "do the tilts earn their complexity?" with a number containing no tilts.
The trading arm is unaffected — it runs through the real engine, which has full bars.

**`qld-schd-sgov` is unranked in two of five long windows.** SGOV's bars begin 2020-06-01, so the
card does not exist during `h5y-1` (2013–2018) and has only 178 sessions of common support in
`h5y-2`, under the pre-registered three-year minimum. It is eligible in three, which clears the
`MIN_ELIGIBLE` bar — but only just, and by construction rather than by merit.

## 5. Benchmarks

| window | SPY | QQQ | 60/40 SPY/AGG |
|---|---|---|---|
| h10y-1 | 173.95% (10.61%/yr) | 398.01% (17.43%/yr) | 83.71% (6.28%/yr) |
| h10y-2 | 259.23% (13.65%/yr) | 500.54% (19.65%/yr) | 116.96% (8.06%/yr) |
| h5y-1 | 76.60% (12.07%/yr) | 145.92% (19.76%/yr) | 42.54% (7.36%/yr) |
| h5y-2 | 106.89% (15.68%/yr) | 235.68% (27.46%/yr) | 62.20% (10.18%/yr) |
| h5y-3 | 73.78% (11.71%/yr) | 79.39% (12.42%/yr) | 34.08% (6.05%/yr) |

The `qqq` blend was added for this round. Round 5 had already measured why: QQQ compounded at
+18.56%/yr against SPY's +12.14%/yr over the decade, roughly halving the reported edge of every card
graded against SPY alone. Grading leveraged-Nasdaq sleeves against SPY only is choosing a flattering
denominator, and the table above shows the size of the choice — 7 points a year in `h10y-1`.

## 6. Nothing is promoted

`PROTOCOL.md` §6 requires two consecutive rounds on differing window sets before a candidate moves
tier. Round 15 is the **first round any savings or Roth card has ever run in**. Every figure here is
one round's evidence, and §6(b) exists precisely to stop this from being enough.

The savings and Roth leaderboards were empty before today for absence of measurement, not for poor
results. They are no longer empty. They are also not yet a basis for moving anything.

## 7. What this round leaves open

- **The cash-constraint asymmetry is unclosed.** Every contribution-funded number is optimistic by
  an amount nobody has measured. Measuring it — running the contribution arms through a cash-aware
  broker — is the single highest-value follow-up, and it may move the P1 result, since the drip's
  advantage in `h5y-3` is exactly the case where a real account would most often fail to fund the
  rebalance.
- **Vol-targeting and inverse-vol risk parity remain inexpressible.** `TiltRule.shift_pct` is a
  fixed `Decimal`, not a function of an indicator's magnitude. `ALLOCATION-FAMILY.md` found the
  vol-target variant the strongest on risk-adjusted terms, and it is still not a card. Closing that
  needs a formula-valued tilt field or a fourth card type; a boolean staircase imitating a
  continuous function was explicitly refused.
- **ATR-gated cards cannot be scored under any contribution schedule** until the bridge carries
  high/low, which means the savings arm structurally cannot evaluate one of its own frozen cards.

---

## CORRECTION, 2026-08-24 (same day, by round 16)

**`ladder-sso-vig-bnd`'s figures in §2's P4 discussion were wrong.** Round 16 found the cause while
building a paired comparison, and this round's own record is amended here rather than rewritten
above, so the error and its correction both stay visible.

**The defect.** `round15.py` created one `card_weight_fn` per *card* and reused it across all five
long windows. `AllocationCard`'s closure is stateless, so every one of the 26 allocation cells is
unaffected and reproduces to the last digit. **`LadderCard`'s closure is a state machine**, carrying
armed rung depth and the cycle-starting high — so each window inherited the previous one's state.

| window | as published above | corrected | delta | QQQ CAGR |
|---|---|---|---|---|
| h10y-1 | 8.14% | 8.14% | **+0.00** | 17.43% |
| h10y-2 | 18.53% | 10.64% | −7.90 | 19.65% |
| h5y-1 | 22.16% | **6.09%** | −16.07 | 19.76% |
| h5y-2 | 27.36% | 11.63% | −15.73 | 27.46% |
| h5y-3 | 16.96% | 9.77% | −7.19 | 12.42% |

`h10y-1` is unchanged because it ran first, with a fresh closure — the signature that confirms the
cause rather than merely fitting it.

**What changes.** §2's P4 table and the sentence "its case rests on *return*, and drawdown is the
bill" are **false**. `ladder-sso-vig-bnd` did not beat QQQ on return in `h5y-1` or `h5y-3`. It never
beat QQQ on either return or drawdown, in any window.

**What does not change.** P4's *verdict* — no candidate beats QQQ on both return and drawdown —
holds, and holds more strongly than when it was written. P1, P2 and P3 concern the savings arm and
the allocation cards, all of which reproduced exactly; §3's tilt findings are unaffected; the
trading arm never used this path.

The original records are kept as evidence at `contributions/roth-CONTAMINATED-INVALID/`, following
round 11's convention for the instrument D5 retired. Full account: `data/rounds/r16-2026-08/SELECTION.md`.

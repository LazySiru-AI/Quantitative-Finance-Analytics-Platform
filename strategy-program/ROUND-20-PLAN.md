# Round 20 — fixing D8: funding a band-breaching buy

Pre-registered 2026-08-30, **before the fix is written**. The funding rule below is chosen from the
mechanism and from what `band_pct` is documented to mean, not from any restated result — no figure
produced under the fix existed when this was written.

Not investment advice.

---

## 1. The defect, in one line

`_rebalance_moves` applies `card.band_pct` per sleeve. A sleeve more than the band under its target
produces a buy; a sleeve more than the band over produces a sell. **The overweight offsetting a
breaching underweight can be spread across sleeves that are each individually inside the band**, so a
buy is emitted with nothing sold to fund it. The engine submits an order it cannot pay for, the
rejection leaves the sleeve underweight, and the same order returns every session. Measured on
`qld-schd-sgov` over 2022-08-23 → 2022-12-30: 65 attempts, 6 fills, **59 rejections on 59 distinct
sessions**, 59 of 61 band-firings emitting buys with no sell. Full write-up: `DEFECTS.md` D8.

It requires **three or more sleeves**. With two, the deviations are equal and opposite, so a buy always
has a matching sell — which is why every existing test passes and the behaviour still ships.

## 2. The funding rule, pre-registered

This is a strategy choice, not a bug fix, which is why it is written down before the code.

> **When any sleeve breaches the band, the buys it triggers are funded first from available cash, and
> then by selling from *every* overweight sleeve — not only those that individually breach — sized
> pro-rata to each sleeve's overweight, for exactly the amount still needed.**

Three properties, and the reasons they were chosen ahead of the alternatives:

- **The band stays a trigger, not a filter.** Nothing is traded while every sleeve sits inside the
  band; `band_pct`'s own docstring says it exists so the card does not trade "on drift that is
  measurement noise". That property is preserved exactly — the existing churn-suppression tests must
  continue to pass unchanged, and they are the check that this rule did not quietly become a daily
  reset.
- **Pro-rata across overweights, not greedy from the largest.** Greedy is path-dependent on sleeve
  order and concentrates turnover in one sleeve for no stated reason. Pro-rata is order-independent,
  which matters here specifically: this programme's own noise floor of 21.2 points came from a study
  of how much a result moves when a card's symbol *ordering* changes.
- **Only the amount needed, not a full reset to target.** Minimum turnover to make the breaching
  sleeve whole. Selling every overweight all the way back to target would be a different strategy —
  more turnover, more slippage — and would need its own justification.

**Rejected alternative, named so it is not silently reconsidered later:** rebalancing the whole book
to target on any breach. That is what `contributions.simulate` does, and it is why the harness's buys
are always fundable. It is a defensible strategy, but adopting it here would change what an
`AllocationCard` *means* rather than fix what it does, and it would make the band a trip-switch for a
full reset. If it is ever wanted, it belongs in a card field, not in a defect fix.

## 3. Settlement interacts with this, and the fix does not hide it

`PaperBroker` fills buys against **settled** cash, and a sale settles at
`_add_business_days(trade_date, settlement_days)` — T+1 under `default_mandate`. So a sell emitted
this session does **not** fund a buy in the same session. Under the fix the buy will still be rejected
on the breach session and fill a session or two later, once the proceeds settle.

**That is correct behaviour, not a residual bug**, and the fix must not paper over it by pre-crediting
unsettled proceeds. A real cash account has exactly this constraint — it is the constraint round 19
implemented in the harness for the same reason. What changes is that the retry now *terminates*:
today the buy can never be funded at all, so it repeats until the window ends.

**Prediction 1:** rejections fall sharply but do not reach zero, and the surviving ones cluster in the
one or two sessions between a funding sell and its settlement.

## 4. Falsifiable predictions

1. **Rejections fall sharply but not to zero**, for the settlement reason in §3.
2. **The two-sleeve tests are untouched.** Every existing test in `tests/test_allocation_card.py`
   passes without modification, including both churn-suppression tests. If any needs editing, the fix
   has changed the band's meaning rather than its funding, and it is wrong.
3. **The strict `xfail` added with D8 flips to passing**, and is un-marked in the same commit.
4. **`qld-schd-sgov`'s ending equity over the D8 window changes**, because the book actually
   rebalances rather than drifting. Direction is *not* predicted: the window is falling and the sleeve
   being bought is a 2× leveraged ETF, so completing the rebalance may well make the result worse.
   Predicting the sign here would be predicting the market.
5. **The harness/engine gap from round 19 narrows.** Round 19 measured −0.6989% with the harness
   *below* the engine, and established the harness rebalances where the engine could not. If the gap
   does not narrow, the defect was not the term that separated them and §5's conclusion below is
   wrong.

## 5. What gets restated, and what does not

**Established by inspection before the fix:**

- **No committed round scorecard is affected.** Round 15's 26 allocation cells and all 31
  contribution cells were produced by `contributions.simulate`, not `run_allocation`; rounds 17 and 18
  are `StrategyCard` rounds. `data/rounds/r15-2026-08/results` and `r16-2026-08` hold no
  `run_allocation` output for a ≥3-sleeve card.
- **The affected figures are the control and diagnostic runs**: `r15_control.py`, `r16_fill_lag.py`
  and `round19.py`, each of which reports an engine ending equity for `qld-schd-sgov`. Those are
  diagnostics quoted in `SELECTION.md` prose and in `ROUND-19-SETTLEMENT.md`, not scored round
  results.
- **The live paper desk is affected**, and this is the part that matters outside the record: two
  seated cards carry ≥3 sleeves — `qld-schd-sgov` (3) and `spy-schd-agg-gld-bil-atr-tilt` (5) — and
  their desks have been silently not rebalancing.

**The restatement:** re-run `round19.py` after the fix and record both figures side by side in
`ROUND-19-SETTLEMENT.md` and in `DEFECTS.md` D8, with the pre-fix numbers kept rather than replaced.
Round 19's own conclusion — that settlement is not the term and the harness is not optimistic — is
re-examined against the new gap in §4's prediction 5, and amended in place if it no longer holds.

## 6. What this round does not do

- It does not change `contributions.simulate`. The harness already funds its buys by construction.
- It does not promote, seat or retire anything.
- It does not touch `band_pct`'s meaning, the tilt rules, or the two-sleeve path.

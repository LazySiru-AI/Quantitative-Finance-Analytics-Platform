# Round 40 — report: no confirmation conjunct pays for itself; the RSI arm is positive but inside the floor

Run 2026-09-09, eight main windows, 8 cards, 64 runs, zero `FAILED` lines. Pre-registration:
`strategy-program/ROUND-40-PLAN.md` (2026-09-09). Computed tables: `ANALYSIS.md`, from
`strategy-program/tools/round34_36_report.py --round 40`, mirrored in `analysis.json`. Scorecard:
`scorecard.json` (`score.py --pin-store`). All cards `purpose = trading`.

**Not investment advice.** Price-only bars, SPY benchmark, a synthetic paper book. From
`creator-e`'s claim that a signal is valid only with a confirmation term attached — given a fair
test, not an endorsement. The persona is partly Korean-language and machine-summarised (a provenance
caveat).

---

## 0. The reachability gate did its job first

This round exists partly because a parallel session's Round 37 used `bb_upper(4, 4)` — an expression
that can never fire (the max z-score inside a 4-bar window is √3 ≈ 1.73 < 4), yet passed every
pre-flight gate. Round 40's tool measured every entry and exit against the store before freezing: base
`close crosses_above bb_mid(20,2)` fires 58.1/1000, the swing conjunct retains 11.2%, the RSI conjunct
14.0%, the divergence negative control 93.3%. All fire; both treatments filter meaningfully. No dead
rule reached the field.

## 1. Result — null by the decision rule

| arm (vs its same-slot `none` control) | slots 3 | slots 6 | clears 21.2pp? |
|---|---|---|---|
| swing-structure | −1.50pp | −1.02pp | no |
| **rsi-confirm** | **+7.82pp** | **+4.82pp** | no |
| divergence-proxy (negative control) | −3.63pp | −0.04pp | no |

BH over all 8 cells: minimum q **0.96**. Every arm-minus-control margin is inside the 21.2pp floor.

**Decision rule (plan §5), applied:** a conjunct "pays for itself" only if arm-minus-control exceeds
21.2pp and survives BH q<0.10. None does. **The null is the result: adding a confirmation term to an
entry that already fires does not, on this evidence, pay for itself.**

## 2. What the numbers do say, short of a finding

1. **RSI-confirm is the sole positive cell in the whole persona-round family** — arm-minus-control
   +7.82pp (3 slots) / +4.82pp (6 slots), median adjusted excess +5.65pp / +4.01pp. Directionally it
   is the one conjunct that helped. But +7.82pp is a third of the floor, sign agreement is only 4-5 of
   8 windows, and its worst window is severe (−30.73pp at 3 slots, −17.21pp at 6): the positive median
   rides on low exposure (0.13–0.21) earning the adjusted-excess credit, with a fat left tail. Not a
   finding, and not a book you would hold through its worst window without flinching.
2. **The divergence negative control behaved exactly as predicted** — −0.04pp from its control at 6
   slots. The plan pre-registered that `rsi_at_swing_low(14,10) < rsi(14)` (93% retention) is a
   near-no-op and should be indistinguishable from `none`; it is. That the measurement caught a
   designed non-effect at four-hundredths of a point is evidence the harness is calibrated.
3. **Nothing was switched off.** The lowest-firing arm still took 94 trades across the matrix, so every
   cell is measured, not silently disabled — the trap this programme flags where a zero-trade window
   scores exactly 0.00 and flatters a non-firing card.

## 3. Disposition

- **Nothing promoted by the rule** (null; no margin clears the floor).
- **`r40-rsi-confirm-slots6` was promoted to `candidates/` by direction on 2026-09-09** — the family's
  sole positive cell, under observation, exactly the inside-floor directed move `r34-ma-crossover-on`
  received. `slots6` (median +4.01pp, worst −17.21pp) was chosen over the higher-median `slots3`
  (+5.65pp, worst −30.73pp) on tail-risk grounds. `PROTOCOL.md` §9 records it. It is **not seated on
  any book**: the live-desk seat is left as an explicit owner call, because it is inside the floor,
  carries a −17.2pp worst window, and §6's promotion rule does not apply to the `trading` purpose (the
  r21 amendment makes trading seating owner judgment).
- **Seated on the trading paper book by direction, 2026-09-09.** The owner then directed the live-desk
  seat: `r40-rsi-confirm-slots6` is now in `app.paperdesk.desk.AGENT_IDS`, the third directed seat on
  the trading book beside `C-trend` and `I-13f-duquesne-2026q2`, disclosed on the desk as a candidate
  seated by decision with its −17.2pp worst window flagged (`PROTOCOL.md` §9). To unseat: remove it
  from `AGENT_IDS`. To swap to the higher-median, deeper-tail sibling: seat `r40-rsi-confirm-slots3`.
- Nothing from the round's other seven cells is promoted.
- Files: `cards/`, `results/<window>/runs/`, `scorecard.json`, `ANALYSIS.md`, `analysis.json`.

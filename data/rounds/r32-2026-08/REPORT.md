# Round 32 — the near-miss passes its rule by the letter and fails it out of sample

Run 2026-08-30 against `ROUND-32-PLAN.md` (`8a18eb3`), committed before the measurement. **Not
investment advice.** A regime-conditional forward-return analysis; no card, no engine, no backtest,
nothing promotable.

---

## 1. The uncomfortable result, stated first

The pre-registered decision rule said: *card candidate iff the 1970-1992 out-of-sample sign holds AND
the spread survives the rate-level control.* **Both fired, and the script prints `CARD CANDIDATE: True`.
All four pre-registered predictions held by their letter.** And I am not going to call it a card
candidate, because the number the whole round was built to produce says the effect is not there out of
sample:

| Test 1 sub-sample | n | hot | cool | spread | p |
|---|---:|---:|---:|---:|---:|
| 1970-2026 full | 222 | +1.63% | +4.04% | **−2.41%** | 0.034 |
| **1970-1992 (out-of-sample)** | 89 | +2.87% | +3.69% | **−0.82%** | **0.51** |
| 1993-2026 (in-sample) | 133 | +0.74% | +4.26% | **−3.52%** | 0.021 |

The effect round 31 found is entirely in the 1993-2026 half (−3.52%, p=0.021). On the 1970-1992 data it
was never fit to — **the era of the most extreme inflation in the modern record (1974, 1980
double-digit)** — the spread collapses to −0.82% at **p=0.51**. The sign held, which is all my
pre-registered rule asked; the *magnitude fell by 77% and the significance vanished*, which is what
actually matters. If this were a structural inflation-to-equity relationship it should have been
**strongest** when inflation was most extreme. It is absent there.

## 2. Why I follow the evidence and not the letter of my own rule

This is the one place a pre-registered rule can mislead, and the direction matters. Pre-registration
exists to stop me **moving goalposts to manufacture a win** — inventing a stricter bar after the fact to
rescue a positive. It does **not** obligate me to *declare* a win when my own decisive test undercuts it.
My rule's out-of-sample gate was a **bare sign test** (`spread < 0`), and a sign at p=0.51 is a coin
flip, not evidence. The rule was under-specified — it should have required the OOS effect to be
*significant*, not merely negative. Reporting that transparently, and declining the card, is following
the evidence; it is not tightening the bar to dismiss an inconvenient positive. The letter says candidate;
the substance says the out-of-sample test is where this thesis quietly died. I record both.

## 3. What genuinely held — and does not rescue it

- **Test 2, the rate-level confound: passed cleanly.** Residualizing the portfolio return within terciles
  of the contemporaneous 10-year rate barely moved the spread (−2.41% → −2.29%, p=0.037). So the effect
  is **not the rate level in disguise** — a real distinction, and the one part of the thesis that
  survives. But it controls a full-sample effect that only exists in-sample anyway, so it cannot revive
  the out-of-sample null.
- **Test 3, exploitability: marginal even in-sample.** Hot-regime equity beats the 10-year cash floor by
  only +0.24% (cool: +2.48%). So *"be less long in hot inflation"* is a real but thin tilt where it
  works, and the effect is lower gains, not an avoidable loss — prediction 3 held, and it describes a
  weak signal.

## 4. The honest counter-caveat: the out-of-sample test is not clean either

The only equity series with 1970 history in the store is the 26-name cohort, and it is **inflation-
defensive by composition** — heavy in energy (XOM, CVX), staples (KO, PG, MO) and utilities (AEP, ED,
DTE, CNP), exactly the sectors that *held up* during the 1970s inflation. An equal-weight portfolio of
them props up hot-regime returns (hot +2.87% is not weak), which mechanically compresses the very spread
this test measures. So the 1970-1992 null is **confounded**, not decisive: it could be "the effect isn't
structural" or "this portfolio is the wrong instrument to see it." I will **not** slice the cohort into
its cyclical names to chase a cleaner OOS number — that is out-of-sample p-hacking, selecting a subset
after seeing the result. The honest status of the out-of-sample question is therefore **inconclusive**,
and an inconclusive out-of-sample test is not a basis to build a card.

## 5. Predictions: all four held by their letter, and it did not save the thesis

1. **OOS half negative — HELD** (−0.82%), but at p=0.51, which is the whole story of §1.
2. **Survives the rate control — HELD** cleanly (§3). The one durable part.
3. **Hot still beats the cash floor — HELD** (+0.24%): lower gains, not avoidable loss; weakly
   exploitable.
4. **Full-sample negative, larger n — HELD** (−2.41%, n=222 vs round 31's 130).

All four holding while the thesis fails is the lesson: a set of predictions can each be technically
correct and still not add up to an edge, when the binding question — *does it hold on data it was not
selected on* — is answered "not significantly."

## 6. Verdict and disposition

**No card.** The macro line's one near-miss resolves as a **1993-2026-specific pattern**: real and robust
within the modern era (round 31), not the rate level in disguise (Test 2), but it **does not survive the
one genuine out-of-sample test** (Test 1, p=0.51), and the only available out-of-sample instrument is too
inflation-defensive to make even that null decisive. Under the pre-registered rule's *intent* — an effect
that generalizes — it fails; under its *letter* it passes on a coin-flip sign, and I decline to build on
a coin flip.

This is round 29's shape a third time: there a survivor **cleared** the bar and stress-testing dissolved
it into the beta premium; in round 31 a near-miss **missed** by the grid tax and every robustness check
refused to dissolve it; here the same near-miss **passes its dedicated rule by the letter** and the
out-of-sample test dissolves it anyway. The macro line stays closed. If the inflation question is ever
reopened, it needs an instrument this repository does not hold: a **broad, non-defensive total-return
market series reaching back to the 1970s**, so the out-of-sample test is clean. Absent that, there is
nothing more to measure here.

## 7. What this round cannot settle

- The out-of-sample instrument is inflation-defensive (§4) — the central unresolved confound.
- 26 survivors; survivorship inflates the return *level* (less clearly the spread).
- DGS10 is a 10-year proxy for a cash rate the pin does not carry; the exploitability floor is
  approximate.
- CPI revision leak unchanged; h=63 only, by design.
- Return statistic only; **nothing here is a card, and nothing is promotable.**

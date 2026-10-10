# Round 22 — the curve round: does `T10Y2Y` change a result where the curve actually moves?

Pre-registered 2026-08-30, before any card in this round has been run and before any cell's result
exists. Round 21's engine is unchanged and is not re-litigated here; what changes is the window
matrix, and only that.

**Not investment advice.** Price-only bars plus one macro scalar, no dividends.

---

## 1. Why this round exists, and what it is not

Round 21 asked whether a macro gate changes a card's result and **could not answer**: `T10Y2Y > 0`
blocked 81 of 1,716 sessions across the eight main windows, 24 of 32 (form, window) pairs came back
byte-identical, and the gate marginal of +0.044pp was an arithmetic consequence of six identical pairs
rather than a measurement of anything. `ROUND-21-PLAN.md` §9 records that in full.

The cause was a selection mismatch: the eight main windows were chosen on **equity** regimes and the
curve inverted elsewhere. This round supplies windows in which **the treatment actually varies**.

### 1a. This is selection on the treatment, not on the outcome — and the distinction is load-bearing

`PROTOCOL.md` and round 5's Arm B are emphatic that selecting windows on the outcome variable is the
failure round 4 exists to document. It would be, and this round would be worthless, if the windows had
been chosen because a gated card *did well* in them.

**They were not.** They were chosen because the gate's own input crosses its threshold there — which
is a property of the independent variable, and without it there is no experiment at all. An
experiment that holds its treatment constant does not have a conservative design; it has no design.

**What was inspected before choosing, disclosed exactly:**

1. The fraction of sessions the gate would block in each candidate window. This is the treatment.
2. **SPY's direction over each candidate window.** This is outcome-adjacent and its use has to be
   stated precisely: it was used to guarantee that **both** directions are represented, and
   specifically to *include* the window most hostile to the gate. It was not used to exclude any
   window in which the gate might look bad. §2 names the hostile window and predicts the gate loses
   in it.
3. Whether all nine universe symbols have bars throughout. This is round 17's Amendment 1 lesson.

**No gated card was run in any candidate window before these windows were fixed.** No adjusted excess,
no return, no trade count for any round-22 cell existed when this document was written.

## 2. The windows

Four candidate periods of sustained curve inversion exist inside the nine sector SPDRs' history
(which begins 1998-12-21). Three are used; one is discarded, for round 21's exact reason.

| tag | span | sessions | **gate blocks** | SPY over window | why it is here |
|---|---|---|---|---|---|
| `inv-2000` | 1999-06-01 → 2001-06-29 | 523 | **43.6%** | **−5.6%** | inverted **and falling** — the case the gate should suit |
| `inv-2006` | 2006-03-01 → 2007-12-31 | 462 | **49.1%** | **+13.0%** | inverted **and rising**, and the most balanced split in the set |
| `inv-2022` | 2022-01-03 → 2024-12-31 | 748 | **72.9%** | **+22.7%** | **the adversarial window** — the gate sits out nearly three quarters of a strongly rising market |

**Discarded: `inv-2019`** (2019-01-02 → 2020-01-31). The gate blocks **2.2%** of its sessions — round
21's failure exactly, and including it would dilute the field with a fourth near-identical pair.
Recorded here rather than silently omitted.

All nine SPDRs carry bars across all three windows (minimum 462 sessions in the shortest), checked
against the store before this document was written.

**Three windows is fewer than PROTOCOL §3 rule 7's five, and this round is therefore unranked by
construction.** That is deliberate and it is not a workaround: the alternative — slicing the 782-day
2022–24 inversion into three "windows" to reach five — would manufacture independence out of one
regime, which is precisely what `00-EVERYTHING-TESTED.md` §4 criticises in round 11's six live
sub-periods ("one regime sliced six ways rather than a regime sample"). **No median is computed
across these three windows.** Each is reported on its own, and the comparison of interest is
within-window, between a cell and its own gate-off twin.

## 3. The field

Identical to round 21's in every respect except the windows: **4 forms × gate on/off = 8 cells**,
`ma-crossover`, `rsi-pullback`, `channel-breakout`, `vol-compression`, fast/slow/regime 10/30/200,
`max_positions` 6, `position_pct` 0.15, no brackets, nine sector SPDRs, gate
`and macro(T10Y2Y) > 0`.

Holding all of that fixed is the point: round 21 and round 22 differ **only** in where they are
scored, so a difference between them is attributable to the windows and to nothing else. The cards
are re-used byte-for-byte from `data/rounds/r21-2026-08/cards/`, frozen at `a49ab48`, rather than
re-authored — a re-authored card is a new card, and this round's whole claim is that it is running the
old one somewhere new.

**Parameter budget** (§3 rule 3): fast=10, slow=30, regime_ma=200, threshold=0, max_positions=6,
position_pct=0.15 — six of ten, unchanged from round 21.

**The pin is round 21's**, `data/rounds/r21-2026-08/macro-pin.json`, digest
`d83b5191832085b0eeceae8de939a39ced386a748970653ad2ac92d78a4d96c6`, unchanged and re-used. Re-pinning
would introduce a second variable — a possibly-revised `T10Y2Y` — into a round designed to change one
thing. `DGS10` reaches 1962 and `T10Y2Y` 1976, so 1999 is covered.

## 4. The null

**Circular-shift permutation of the gate mask**, as pre-registered in `ROUND-21-PLAN.md` §4 and for
the reasons given there: the mask is autocorrelated, so an i.i.d. reshuffle would destroy its
run-length structure and produce an artificially tight null. A circular shift preserves the on/off
proportion and the run-length distribution exactly, randomising only phase.

**Run on `ma-crossover` only, 200 shifts, all three windows — 600 runs.** Round 21 pre-registered 200
shifts across four forms (6,400 runs) and then did not run it at all. Running one form at full depth
is a better-powered and more honest commitment than four forms shallowly, it keeps the
multiple-comparison denominator at one form, and `ma-crossover` is the most-evidenced entry in this
programme by a wide margin — the sole template the evolution loop emitted for generations 1–1915.

**The other three forms' gate marginals are reported descriptively and are explicitly not tested
against this null.** Quoting them as though they had cleared a bar they were never measured against
is the exact move `00-EVERYTHING-TESTED.md` recommendation #5 warns about.

**Decision rule:** the `ma-crossover` gate marginal, per window, matters only if it falls outside the
**2.5th–97.5th percentile** of that window's own circular-shift null. Two-tailed, because §5 predicts
the gate *loses* in one window and *gains* in another — a one-tailed test would be unable to see half
of what this round predicts.

**Round 17's 21.2pp floor is not the decision rule here** and is reported beside the result only so a
reader has the programme's numbers in one frame. If the two disagree, the circular-shift null governs.
Fixed now, before either exists.

## 5. Pre-registered predictions

**The prior, stated plainly: the most likely outcome is still nothing.** ~50 concepts, near-zero
survivors. What has changed since round 21 is that the question can now be *asked*, not that the
answer is expected to be yes.

1. **The gate loses in `inv-2022`.** It blocks 72.9% of a window in which SPY rose 22.7%; a filter
   that sits out three quarters of a rising market should give up return. **A gate that wins here
   would be the round's most surprising result** and would demand explanation before belief.
2. **The gate wins in `inv-2000`**, the falling window. If predictions 1 and 2 both hold, the gate is
   behaving as a *risk-off filter correlated with equity direction*, which is a much weaker claim than
   "the curve carries information" — and §6 says why that distinction cannot be settled here.
3. **`inv-2006` is the discriminating window.** Inverted, balanced 49.1/50.9, and *rising*. If the
   gate wins here — where it is inverted but equities went up 13% — that is the only configuration in
   this round that is evidence for the curve carrying information rather than for the gate tracking
   drawdowns. **This is the cell to read first.**
4. **The `ma-crossover` marginal falls inside its circular-shift null in at least two of the three
   windows.** The central prediction, and it predicts a null.
5. **No cell is byte-identical to its twin in any of the three windows.** Round 21's collapse must not
   recur; a byte-identical pair here would mean the window selection failed again and the round is
   void. Checked before scoring, as round 21's amendment was.

## 6. What this round cannot answer

- **It cannot separate "the curve is informative" from "inversion correlates with drawdowns".** Three
  windows, two of which rose and one of which fell, is not enough to disentangle a regime signal from
  its correlate. Prediction 3 names the single cell that bears on it; one cell is a hint, not a
  finding.
- **Three windows, and they are not independent draws.** They are three episodes from one economy, and
  `inv-2000` and `inv-2006` share a monetary regime that `inv-2022` does not. No median is computed
  across them precisely because that would imply an independence they do not have.
- **`adjusted_excess` structurally favours a low-exposure book against a large negative benchmark**
  (PROTOCOL §4, measured at Pearson r = +0.797 across ten cards in round 2). A gate that cuts exposure
  in `inv-2000` therefore collects a credit that is partly arithmetic. Exposure is reported beside
  every figure and `inv-2000`'s result must be read with it.
- **Everything round 21 could not do, it still cannot**: no stationary transform of a trending series,
  one series in the comparison, no revision-vintage data, the 45-day monthly lag is still a
  conservative placeholder, and the guard proves the configured lag was respected rather than that it
  is correct.
- **Nothing is promotable.** A measurement study, like rounds 15–18 and 21 — and the r21 amendment to
  `PROTOCOL.md` §9 removed §6's promotion rule from the `trading` purpose in any case.

## 7. Amendment and disclosure discipline

As round 21 §7, unchanged, and it was exercised there rather than merely stated: a failed or
invalidated attempt is preserved on disk under an `-INVALID` name, the amendment is written into this
document with what was wrong and whether any §5 prediction is weakened by it, and nothing learned from
a failed run informs a still-open design choice in the surviving version.

**Specifically for this round:** if prediction 5 fails — if any pair comes back byte-identical — the
window selection has failed the same way round 21's did, and the correct response is to record that
and stop, not to reach for a fourth window.

---

## 8. Amendment 1, 2026-08-30 — `inv-2000`'s start moves to 1999-12-02 (warmup, not results)

**Recorded before any `inv-2000` result existed**, because none does: all eight cards were refused by
the lookahead guard and the window produced zero run files.

### What happened

Every card failed with:

> `causality: sma_200: only 109 bars against a 199-bar warmup leaves no post-warmup region to
> truncate, so causality could not be demonstrated -- this guard reports that as a failure rather
> than passing on no evidence`

§2 checked that all nine SPDRs carry bars **inside** each window. It did not check that they carry
enough bars **before** it. The nine sector SPDRs begin 1998-12-21; a window opening 1999-06-01 leaves
109 prior sessions against `sma(200)`'s 199-bar warmup plus the guard's 40-bar minimum.

**This is round 17's Amendment 1 in a new costume** — "the tickers had been checked against the store
and not against the guard" — and round 21's too. Third occurrence of the same class of error in three
rounds, which is worth stating plainly rather than filing as bad luck: *a coverage check is not a
feasibility check, and only the guard knows the difference.*

### The correction, and why it is not selection on the outcome

The new start is **1999-12-02**, derived mechanically: the earliest date on which every one of the
nine symbols has 239 prior sessions (199 warmup + the guard's 40-bar causality minimum). It is not a
date chosen for what it produces — **no card had run in any variant of this window when it was
picked**, and the rule that produced it would give the same answer to anyone applying it.

Revised window: **`inv-2000` = 1999-12-02 → 2001-06-29.** 397 sessions, gate blocks **57.4%** (up
from 43.6% in the discarded span), SPY **−14.8%** (from −5.6%). It still opens 72 days before the
inversion begins on 2000-02-12, so it still straddles rather than sitting inside the regime.

### What this does and does not change

- **No §5 prediction is altered or weakened.** Prediction 2 says the gate wins in the falling window;
  the window is still the falling one and is now more strongly falling and more strongly gated, which
  makes the prediction easier to falsify, not harder.
- **`inv-2006` and `inv-2022` are untouched** and their results — which existed before this amendment
  was written — are not restated.
- **Nothing learned from the failure informs a still-open choice.** The failure produced no scored
  result in any window; it produced a guard refusal, which carries no information about returns.

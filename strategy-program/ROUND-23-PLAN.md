# Round 23 — the curve as a *sizing* input, not a gate

Pre-registered 2026-08-30, before any card in this round is authored and before any cell's result
exists. Every number below is a property of the **treatment** — the pinned `T10Y2Y` series — computed
before a single backtest ran.

**Not investment advice.** Price-only bars plus one macro scalar, no dividends, no promotion.

---

## 1. Why this round exists

Round 22 asked whether a `T10Y2Y > 0` **entry gate** changes a result, in three windows where the
curve actually crosses its threshold, and got a clean null: inside the null in 3 of 3 windows under
all three definitions. Its §6 names precisely what that does not settle:

> one threshold (`> 0`), one series, one universe, four forms, and an entry-gate expression. **A
> different cut, a rate-of-change rather than a level, or the curve as a *sizing* input rather than a
> binary gate are all untouched.**

This round takes the sizing variant. It is not a re-run of round 22 and does not re-litigate it: a
binary gate and a continuously-sized tilt are different hypotheses about the same series, and round 22
tested only the first.

**It is newly possible.** `TiltRule.shift_expr` did not exist when
`docs/research/programme/00-EVERYTHING-TESTED.md` was written; that report listed continuous sizing as
**inexpressible by the engine** and ranked fixing it the programme's #2 outstanding change.
`shift_expr` landed since, is parsed through `parse_ranking` and guarded as a ranking key — because a
magnitude that is not causal sizes today's position from tomorrow's data, which is lookahead in the
*sizing* step and is harder to spot than lookahead in a condition. Verified before writing this plan:
`0.2 * macro(T10Y2Y)` parses.

## 2. The design — three arms, one card, one variable

`qld-schd-sgov`, the seated three-sleeve allocation card, tilting **QLD → SGOV**: out of 2× Nasdaq
into T-bills as the curve inverts. That direction is the conventional reading of an inversion and is
fixed in advance; the opposite direction would be a different rule with the symbols swapped, and
`shift_expr`'s own contract clamps a negative shift rather than silently reversing a stated direction.

| arm | tilt |
|---|---|
| **A — control** | no tilt |
| **B — binary** | `condition: macro(T10Y2Y) < 0`, `shift_pct: 0.172` |
| **C — sized** | `condition: macro(T10Y2Y) < 0`, `shift_expr: "-0.5 * macro(T10Y2Y)"` |

### 2a. The calibration is from the treatment, and this is the round's load-bearing choice

Arm C's coefficient and arm B's constant were **both derived from the pinned series' own distribution
in these windows, before any card ran**:

| window | sessions firing | mean shift (C) | max shift (C) |
|---|---:|---:|---:|
| `inv-2000` | 227 | 0.1373 | 0.2600 |
| `inv-2006` | 215 | 0.0372 | 0.0950 |
| `inv-2022` | 541 | 0.2399 | 0.5400 |

Pooled mean shift over firing sessions is **0.1719**, and arm B's `shift_pct` is set to **0.172** for
exactly that reason.

**So B and C move the same average weight and differ only in how it is distributed across sessions.**
Without that, a difference between them would be a difference in *magnitude* wearing the name of a
difference in *gradation*, and the round would answer a question nobody asked. `-0.5` was chosen so
the deepest inversion in the set (−1.08, in `inv-2022`) moves about half the sleeve — a property of
the series' range, not of any return.

## 3. Windows and metric

`inv-2000` (1999-06-01 → 2001-06-29), `inv-2006` (2006-03-01 → 2007-12-31), `inv-2022`
(2022-01-03 → 2024-12-31) — round 22's, reused unchanged. They were selected on the **treatment**
(the curve crosses its threshold there), which round 22 §1a argues at length is the only way this
experiment exists at all, and their reuse carries no outcome-selection because round 22's result was
null in all three.

**The metric is not round 22's.** An `AllocationCard` carries the `invested-value` exposure basis, and
`app.tournament.results` **refuses** to compute `adjusted_excess` for it rather than emit a
same-named, structurally different number. So this round reports **CAGR, total return, max drawdown
and MAR**, and the exposure-credit caveat that dominated round 22's §5 does not apply here in the same
form. That is a consequence of the card shape, not a choice made to avoid the caveat.

## 4. Falsifiable predictions

1. **B and C will not differ by more than the 21.2pp noise floor** on total return, in any window.
   The honest prior, on a base rate of ~50 concepts and near-zero survivors.
2. **Whether you tilt will matter more than how you size it** — `|A − B|` and `|A − C|` will each
   exceed `|B − C|`, in at least 2 of 3 windows. This is the round's central claim and the one worth
   the compute: if gradation matters less than the decision to tilt at all, `shift_expr`'s value is in
   the strategies it *enables* rather than in fine-tuning this one.
3. **Both tilted arms reduce total return in `inv-2022`.** The curve is inverted 72.2% of a window in
   which SPY rose 22.7%; a rule that sits out that much of a rising market should cost return. If this
   fails, the tilt is being credited for something other than timing.
4. **Both tilted arms post a shallower max drawdown than control in `inv-2000`**, the falling window.
   This is the case the tilt is designed for; if it fails there, it fails everywhere.
5. **Arm C's turnover exceeds arm B's.** A shift that moves with the curve rebalances on every change
   in its level; a constant shift moves once on each crossing. If C is *not* the busier arm, the
   band is absorbing the gradation and the two arms are not actually different.

## 5. The null

Arm C's marginal against arm A is compared to a **circular-shift null on the macro series** — the same
construction round 22 used, for the same reason: a phase-randomised series preserves the level
distribution and the autocorrelation while destroying the alignment to market events, so it isolates
"this series, at this phase" from "a series shaped like this one". 200 shifts, matching round 22.

A marginal inside that null is not evidence of anything, however large it looks.

## 6. What this round cannot settle

- **One direction, one pair of sleeves, one coefficient.** A different scale, a rate-of-change input,
  or a tilt on a different sleeve pair are untouched — as are all six other series in the round-21 pin.
- **Three windows from one economy.** `inv-2000` and `inv-2006` share a monetary regime `inv-2022`
  does not. No median will be computed across them.
- **Nothing about the entry-gate question**, which round 22 answered and this round does not revisit.
- **Nothing is promotable.** A measurement study, like rounds 15–18 and 21–22.

---

## 7. Amendment 1 — the base is the card's *allocation*, not the card

**Recorded 2026-08-30, before any cell of this round has run.**

§2 said the field is "`qld-schd-sgov`, the seated three-sleeve allocation card". Reading the card
before authoring the arms shows it already carries **two price-driven tilt rules**:

    close < sma(150)        QLD   SCHD -> QLD    shift 0.08
    close > bb_upper(20,2)  QLD   QLD  -> SGOV   shift 0.08

Both fire on QLD's own bars and both move weight between the same sleeves the curve tilt would. Left
in, they interact with the curve tilt in ways no arm can separate: arm C's shift would be applied on
top of a base allocation that is itself moving for price reasons, and a difference between arms B and
C could be an interaction with `bb_upper` rather than a property of gradation.

**All three arms therefore use the card's sleeves and band with `rules: []`** — a static 35/40/25
QLD/SCHD/SGOV allocation, plus the curve tilt in arms B and C and nothing in arm A.

Two consequences, stated so neither is discovered later:

- **This is a derived card, not the seated one.** No figure this round produces restates
  `qld-schd-sgov`'s own record, and none should be read against it. The seated card keeps its price
  rules and its committed numbers.
- **The calibration in §2a is unaffected.** Those figures are properties of the pinned `T10Y2Y`
  series, computed from the series alone; nothing about the card entered them.

The alternative — keeping the price rules and adding the curve tilt as a fourth — would measure "does
a curve tilt add anything *to this particular card*", which is a narrower and less transferable
question than the one §1 asks, and would confound the B-vs-C comparison that prediction 2 rests on.

---

## 8. Amendment 2 — the sleeves, because the card's own three do not exist in two of the three windows

**Recorded 2026-08-30, before any cell of this round has produced a usable number.**

Amendment 1 stripped the base card's price tilts. Attempting the first run then exposed a larger
problem with the base card itself:

| sleeve | first bar | covers `inv-2000` (from 1999-06-01)? |
|---|---|---|
| `QLD` | 2006-06-20 | **no** |
| `SCHD` | 2011-10-19 | **no** |
| `SGOV` | 2020-05-31 | **no** |

**None of `qld-schd-sgov`'s three sleeves existed in 1999, and only `QLD` existed in 2006.** The card
can run in `inv-2022` and nowhere else, which removes the cross-window comparison predictions 2, 3 and
4 all rest on.

**How it presented is worth recording.** The control arm did not fail — it returned **`+0.00%` on 0
trades, 0 rejections**: an empty book reported as an ordinary result. Nothing in the output said "this
card holds nothing here". That is the same shape as `DEFECTS.md` D3 and the round-17 amendment, and it
is the second time in this programme's record that a universe's history has produced a plausible
number instead of a refusal.

**The amendment.** The arms keep their structure, weights and band and change sleeves to three that
cover every window in the set:

| sleeve | weight | first bar | role |
|---|---:|---|---|
| `XLK` | 0.35 | 1998-12-21 | the cyclical leg — the tilt's `from_symbol` |
| `XLP` | 0.40 | 1998-12-21 | consumer staples, the defensive leg — the tilt's `to_symbol` |
| `XLU` | 0.25 | 1998-12-21 | utilities, held static |

The tilt becomes **XLK → XLP**: rotate out of technology into staples as the curve inverts. That is
the conventional defensive-rotation reading of an inversion, it is the same *shape* of hypothesis as
the QLD → SGOV version it replaces, and it is expressible over all three windows.

**What is unaffected:** §2a's calibration. Those figures — the 0.1719 pooled mean shift and the −0.5
coefficient — are properties of the pinned `T10Y2Y` series computed from the series alone. No sleeve
entered them, so the arms remain matched on average shift and differ only in gradation.

**What changes:** this is no longer a derived version of a seated card at all, but a purpose-built
three-sector allocation. Nothing here bears on `qld-schd-sgov`'s record in either direction, and §6's
"one pair of sleeves" caveat now names `XLK`/`XLP`.

**Predictions are unchanged.** All five were stated over arms and windows, not over tickers.
Prediction 4 — a shallower drawdown for the tilted arms in the falling window — is if anything a
harder test on a staples leg than on T-bills, since staples fall in a crash and bills do not.

---

## 9. Amendment 3 — about half of the null applies no treatment at all

**Recorded 2026-08-30, after the pre-registered null in §5 ran and was committed at `7cc352c`, and
before the diagnostic re-run described below. Nothing in §5's decision rule is changed, and no verdict
already committed is withdrawn here.**

The committed null reports `null_median: 0.0` in all three windows. That is not a rounding artefact.
Counting firing sessions directly from the pinned series, for the same 200 offsets the null used:

| window | sessions in window | observed firing | replicates firing **zero** times | replicate firing count (min / median / max) |
|---|---:|---:|---:|---:|
| `inv-2000` | 524 | 227 (43.3%) | **105 / 200 (52.5%)** | 0 / 0 / 513 |
| `inv-2006` | 462 | 215 (46.5%) | **111 / 200 (55.5%)** | 0 / 0 / 462 |
| `inv-2022` | 749 | 541 (72.2%) | **85 / 200 (42.5%)** | 0 / 18 / 657 |

The pinned series spans 1976–2026 and the curve is inverted in a minority of it, so a circular shift
lands the window on a non-inverted stretch about half the time. When that happens the tilt never
fires, arm C reproduces arm A exactly, and the replicate's marginal is exactly `0.0`.

**So the null is not "this series at a random phase" throughout — roughly half of it is "no treatment
at all".** §5 claimed the construction "preserves the level distribution and the autocorrelation while
destroying the alignment to market events". It preserves them *over the whole series*; it does not
preserve the presence of the treatment *inside the window*, which is what the comparison needs.

### The direction of the bias, measured rather than argued

Round 22 used the same construction and its `null.json` retains `raw_marginals`, so the effect can be
measured there directly. Rebuilding its intervals from treated replicates only:

| window | zero replicates | width, all 200 | width, treated only | verdict |
|---|---:|---:|---:|---|
| `inv-2000` | 125 (62.5%) | 0.1025 | **0.1249** (n=75) | unchanged, inside |
| `inv-2006` | 117 (58.5%) | 0.0804 | **0.0892** (n=83) | unchanged, inside |
| `inv-2022` | 92 (46.0%) | 0.1205 | **0.1277** (n=108) | unchanged, inside |

**The point mass makes the interval too narrow, in every window, which makes `outside` easier to
reach.** That has opposite consequences for the two rounds:

- **Round 22's null is strengthened.** It concluded "inside in 3 of 3" using a test biased *toward*
  finding an effect, and all three verdicts survive the correction unchanged. A conservative test that
  finds nothing is better evidence of nothing than a neutral one.
- **Round 23's single `outside` verdict is the vulnerable one.** `inv-2022` cleared its boundary by
  0.25pp, and the boundary is understated by exactly this mechanism.

### The diagnostic re-run, and why it is not a second draw

`round23_null.py` will be changed to persist `raw_marginals`, as round 22's harness already does, and
re-run at the same 200 shifts.

**This is instrumentation, not a new measurement.** The offsets are computed deterministically
(`((i * step) + 1) % n`, no RNG), the cards are frozen and committed, and the store is pinned — so the
re-run recomputes the identical distribution and merely records values the first run discarded.
`round23_null.py` will **assert that the recomputed `null_p2_5`, `null_p97_5` and `observed_marginal`
match the values committed at `7cc352c` exactly**; if they do not, the re-run is a different
measurement and its output is void rather than an update.

That assertion is the whole safeguard, and it is why this does not breach §2 of `PROTOCOL.md`: a card
re-run under identical frozen inputs is the same draw observed more closely, not a fresh one. See also
the standing hazard that a deterministic re-run can be mistaken for independent confirmation — the
danger runs the other way here, and the assertion is what keeps it honest.

**What the re-run may change, stated before it runs:** if `inv-2022`'s treated-only interval contains
`-12.61pp`, this round is **null in 3 of 3 windows** and §5's `outside` verdict for that window is
withdrawn as an artefact of the null's construction. Round 22's scaling (its `inv-2022` lower bound
moved 8.4% more extreme on 46.0% zeros) applied to round 23's `-12.359` gives roughly `-13.4`, which
would contain the observation — so **the expected outcome is that the verdict flips to inside.** That
is written down now, before the run, so it cannot be claimed as a prediction afterwards.

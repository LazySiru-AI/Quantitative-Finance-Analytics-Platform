# Round 22 — the curve round: the question got asked, and the answer is no

**Not investment advice.** Price-only bars plus one macro scalar, no dividends, no promotion.

Pre-registration: [`strategy-program/ROUND-22-PLAN.md`](../../../strategy-program/ROUND-22-PLAN.md),
frozen at **`e0c6eef`**. Amendment 1 at **`e388369`**.
Cards re-used byte-for-byte from round 21, frozen at **`a49ab48`**.

---

## 1. The headline

Round 21 could not ask its question. **This round asked it, and the answer is no.**

`macro(T10Y2Y) > 0` produced **no effect distinguishable from a randomly-phased mask with the same
statistics**, in any of three windows, under three separate definitions of the null. The observed
`ma-crossover` marginals — +6.27pp, −5.19pp, +5.65pp — look large and are ordinary: a circular shift
of the same mask produces that spread routinely.

**And the sharpest single number is not the null verdict.** In `inv-2022`, where the gate is most
active, the observed marginal of **+5.65pp sits at the bottom edge of the null restricted to
replicates that gate a comparable fraction, [+5.11pp, +12.37pp]**. Among masks that cut roughly as
much exposure, the *real* curve did worse than typical. Whatever the gate bought there, it bought by
cutting exposure, not by knowing when.

## 2. The design worked, which is the thing round 21 could not manage

**Zero byte-identical pairs in any window** — prediction 5 holds. Round 21's collapse (24 of 32 pairs
identical) does not recur. The gate blocks 57.4% / 49.1% / 72.9% of sessions and moves exposure hard:
`ma-crossover` runs at 42.1% → 16.1%, 57.3% → 31.4%, 37.1% → 8.5%.

| window | span | gate blocks | SPY | mean marginal (4 forms) |
|---|---|---|---|---|
| `inv-2000` | 1999-12-02 → 2001-06-29 | 57.4% | **−14.8%** | **−0.67pp** |
| `inv-2006` | 2006-03-01 → 2007-12-31 | 49.1% | +13.0% | **−1.80pp** |
| `inv-2022` | 2022-01-03 → 2024-12-31 | 72.9% | +22.7% | **+0.68pp** |

Per-form adjusted excess (gate off → on):

| form | `inv-2000` | `inv-2006` | `inv-2022` |
|---|---|---|---|
| ma-crossover | −9.12 → −2.86 (**+6.27**) | +3.19 → −2.01 (**−5.19**) | −10.54 → −4.89 (**+5.65**) |
| rsi-pullback | +16.83 → +5.98 (**−10.85**) | +4.16 → −0.37 (**−4.54**) | −0.95 → −6.44 (**−5.49**) |
| channel-breakout | −9.42 → −11.20 (**−1.79**) | −5.95 → −8.13 (**−2.18**) | −15.14 → −14.46 (**+0.68**) |
| vol-compression | −14.15 → −10.45 (**+3.70**) | −6.43 → −1.72 (**+4.71**) | −11.31 → −9.41 (**+1.90**) |

**No consistent sign anywhere.** Within-window spread across four forms reaches 17pp; between-window
means disagree in sign. That is what noise looks like.

## 3. The null

Pre-registered: circular-shift permutation, `ma-crossover`, 200 shifts, three windows, two-tailed at
2.5/97.5. 600 runs, executed.

| window | observed | null p2.5 | null p97.5 | verdict |
|---|---|---|---|---|
| `inv-2000` | +6.27pp | −0.72pp | +9.53pp | **inside** |
| `inv-2006` | −5.19pp | −5.93pp | +2.11pp | **inside** |
| `inv-2022` | +5.65pp | −2.25pp | +9.79pp | **inside** |

**Prediction 4 held** — it predicted "inside in at least two of three"; the answer is three of three.

### 3a. A weakness in this null, found and quantified rather than left implicit

**Between 42.5% and 58.5% of the 200 replicates gate nothing at all.** The curve is un-inverted for
most of its history, so a randomly-phased mask frequently lands on an all-positive stretch. The median
replicate blocks **0.0%** of sessions in `inv-2000` and `inv-2006`, and 2.9% in `inv-2022`, against a
real mask blocking 57.4% / 49.1% / 72.9%.

So the pre-registered null partly compares *a gate* against *no gate* rather than against a comparably
aggressive one, and a null that wide is easy to sit inside. Reporting "inside" without this would be
overclaiming.

**Two stricter nulls, computed as a disclosed secondary analysis** — not pre-registered, and stricter
rather than looser, so they can only move a verdict from inside to outside:

| window | obs | active-only (b > 0) | verdict | matched (\|b − real\| ≤ 10pp) | verdict |
|---|---|---|---|---|---|
| `inv-2000` | +6.27pp | n=83, [−0.92, +10.46] | inside | n=12, [−0.45, +9.20] | inside |
| `inv-2006` | −5.19pp | n=89, [−6.71, +2.21] | inside | n=15, [−7.14, +2.11] | inside |
| `inv-2022` | +5.65pp | n=115, [−2.44, +10.33] | inside | **n=11, [+5.11, +12.37]** | inside |

**The verdict survives every definition.** The matched nulls carry 11–15 replicates each and are
underpowered — they cannot refute much — but they are the comparison that matters, and `inv-2022`'s
is the one to read: the observed value sits at its **lower edge**, meaning comparably-aggressive
random masks typically did *better* than the real curve.

## 4. Predictions, scored

| # | prediction | outcome |
|---|---|---|
| 1 | gate **loses** in `inv-2022` | **refuted on the metric, confirmed on raw return** — see §5 |
| 2 | gate **wins** in `inv-2000` (falling) | **refuted** — mean −0.67pp; `ma-crossover` +6.27pp but `rsi-pullback` −10.85pp |
| 3 | `inv-2006` is discriminating; a win there would be evidence for the curve | **no win** — mean −1.80pp, 3 of 4 forms negative. No evidence for curve information |
| 4 | marginal inside the null in ≥2 of 3 windows | **held** — inside in 3 of 3, under all three null definitions |
| 5 | no byte-identical pair in any window | **held** — 0 of 4 in each window |

Two held, two refuted, one answered in the negative. **Every prediction engaged the data**, which is
the difference between this round and round 21's four "untested".

## 5. Prediction 1 is the round's most useful result, and it is about the metric

I predicted the gate would lose in `inv-2022` — it sits out 72.9% of a window in which SPY rose 22.7%.
On **raw return it did**, in all four forms: `ma-crossover` −1.99% → −2.94%, `rsi-pullback` +7.04% →
−3.47%, `channel-breakout` −2.61% → −10.94%, `vol-compression` +1.63% → −5.89%.

On **`adjusted_excess` it did not**: +0.68pp mean, +5.65pp for `ma-crossover`.

The two disagree because `adjusted_excess = total_return − capital_exposure × benchmark_return`, and
gate-on's exposure is a quarter of gate-off's (8.5% vs 37.1%). A book measured against a passive
position of its own size gets a structural credit for being small. **This is exactly the caveat
pre-registered in §6**, quoting PROTOCOL §4's own measurement of the effect at Pearson r = +0.797
across ten cards in round 2 — written before the result, not after it.

The matched null in §3a is what settles the reading: among random masks cutting comparable exposure,
+5.65pp is a *below-median* outcome. **The metric's credit is real and the gate did not earn it.**

## 6. What this round establishes, and what it does not

**Establishes:** on this universe, in the three windows where the US yield curve actually crossed its
threshold, a `T10Y2Y > 0` entry gate produced nothing separable from a phase-randomised mask with
identical statistics. That is a genuine null on a genuine test — the first in this programme for the
macro class, since round 21's could not run.

**Does not establish:**

- **That the curve carries no information.** One threshold (`> 0`), one series, one universe, four
  forms, and an entry-gate expression. A different cut, a rate-of-change rather than a level, or the
  curve as a *sizing* input rather than a binary gate are all untouched.
- **Any separation of "the curve is informative" from "inversion correlates with drawdowns".** §6 of
  the plan said three windows could not settle this and they did not. Prediction 3 was the cell that
  bore on it and it came back negative, which is a hint, not a finding.
- **Independence across the three windows.** They are three episodes from one economy; `inv-2000` and
  `inv-2006` share a monetary regime `inv-2022` does not. No median was computed across them, and
  none should be.
- **Anything about the other three forms against a null.** They were reported descriptively, as
  pre-registered. Only `ma-crossover` was tested.

## 7. Promotion

**None.** A measurement study, like rounds 15–18 and 21; and the r21 amendment to `PROTOCOL.md` §9
removed §6's promotion rule from the `trading` purpose in any case.

## 8. What it cost, and what the programme now has

Two rounds and an engine change to reach one clean null. Round 21's field was unusable and its
failure is recorded rather than buried; round 22 re-used its cards byte-for-byte so the only variable
between them was where they were scored.

What survives both rounds is the capability: `docs/research/programme/00-EVERYTHING-TESTED.md` §3b's
"collected, displayed, **unreachable by any card**" is no longer true of FRED macro series. A card can
name one, the guard verifies per session that no value was read before publication, the data is pinned
and digest-verified, and the null harness that tests it exists and runs in 24 minutes. The next macro
question costs a fraction of what this one did.

**The honest summary of the finding itself:** ~50 concepts, near-zero survivors, and this is one more
on the pile — measured properly this time.

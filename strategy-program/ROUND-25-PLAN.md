# Round 25 — the curve's *rate of change*, against its level

Pre-registered 2026-08-30, before any card in this round is authored and before any cell's result
exists. Every number below is a property of the **treatment** — the pinned `T10Y2Y` series — computed
before a single backtest ran.

**Not investment advice.** Price-only bars plus one macro scalar, no dividends, no promotion.

---

## 1. Why this round exists, and why it is the last one in this line

Round 22 answered the curve as an **entry gate**: null in 3 of 3. Round 23 answered it as a **sizing
term**: null in 3 of 3, once its null was corrected. Both named the same remaining variant, and
`docs/research/programme/00-EVERYTHING-TESTED.md` §6 item 4 now records it as the only untouched shape:

> **What remains untouched is now only the rate-of-change input**, plus the other six series in the
> round-21 pin.

This round takes it. After this, the macro line is exhausted at the level of *shape* — what would
remain is other series, not other forms of the same one.

## 2. It is not expressible by the DSL, and this round does not pretend otherwise

`macro()` takes a bare series name and nothing else. `MacroRef` holds a field and no lag, `NumExpr`
has no lag node, and the indicator registry operates on the OHLCV frame. `MacroField`'s own docstring
states the position deliberately:

> Expressing "core inflation is rising" needs a year-over-year transform, which needs a macro value to
> be an *argument to an indicator* (`sma(macro(CPILFESL), 12)`), **which this change deliberately does
> not build** — the indicator registry operates on the OHLCV frame and wiring a differently-sampled
> series into it is a second engine change.

**So a rate of change cannot be written in a card today.** This round therefore measures the
*hypothesis* and not the *shippable capability*, and the distinction is load-bearing:

- **What it can settle:** whether the curve's rate of change carries information its level does not,
  on this universe and these windows.
- **What it cannot settle:** anything about a card a user could actually write. If the answer is null,
  the engine change is not worth building. If the answer is not null, the engine change becomes
  justified — and would still have to be built, guarded and pre-registered separately before anything
  here could be traded.

**The mechanism is one this programme has already reviewed twice.** `round22_null.py` and
`round23_null.py` both substitute `macro_pin.active_pin` in-process for the duration of a run, so
binding, guard and engine execute unchanged against a series the round supplies. This round uses the
same substitution to supply a **derived** series rather than a shifted one. Nothing is written to a
pin file, and the committed round-21 pin is never mutated — which matters here more than in the null,
because a file on disk named `T10Y2Y` containing deltas would be a trap for every later reader.

**Causality is preserved by construction, and this is the part worth checking rather than asserting.**
`ROC(d) = value(d) − value(d − 20 sessions)`. Both terms are on or before `d`, so the derived point at
reference date `d` depends on nothing published after `d`. The substituted series is carried on the
*same reference dates* as the original, so `macro_binding`'s release-lag join applies to it unchanged:
whatever lag makes `T10Y2Y(d)` knowable makes `ROC(d)` knowable, because the later of its two inputs
*is* `T10Y2Y(d)`. A lag can only make information older, never newer.

## 3. The design — three arms, one variable

Sleeves, weights and band are round 23's: a purpose-built static 35/40/25 `XLK`/`XLP`/`XLU`
allocation, tilting `XLK → XLP`, all three from 1998-12-21 so they cover every window. Round 23's
Amendment 2 explains why the seated `qld-schd-sgov` card cannot be used and that reasoning is
unchanged. `rules: []` apart from the curve tilt, per round 23's Amendment 1.

| arm | series read | condition | shift |
|---|---|---|---|
| **A — control** | — | — | no tilt |
| **B — level** | `T10Y2Y` as pinned | `macro(T10Y2Y) < 0` | `-0.5 * macro(T10Y2Y)` |
| **C — rate** | `T10Y2Y` **substituted with its 20-session change** | `macro(T10Y2Y) < 0` | `-1.748 * macro(T10Y2Y)` |

Arm B is **round 23's arm `c-sized`, unchanged** — same card, same windows, same pin. Arm C is the
same card reading a series that has been replaced by its own rate of change. Both express "tilt
defensive when the signal is negative"; they differ only in *which signal*.

**A falling curve is the conventional deterioration signal**, the same direction round 23's inversion
tilt took, and it is fixed in advance. `shift_expr` clamps a negative shift rather than reversing a
stated direction, so the opposite reading would be a different rule with the symbols swapped.

### 3a. The lookback is a convention, fixed before looking at any return

**20 sessions ≈ one month.** Chosen as a convention, not fitted: no return, drawdown or marginal
entered the choice, and no other lookback was evaluated against an outcome. `ROC60` was computed
alongside it purely to confirm the series is not degenerate at either scale (pooled |mean| 0.143 at 20
sessions, 0.267 at 60). Testing several lookbacks and reporting the best would be the multiple-
comparisons failure this programme's §1 record exists to document.

### 3b. The calibration, and why it differs from round 23's

Round 23 matched B and C on **mean shift over firing sessions**, which was right there because both
arms fired on the same condition. **Here they do not** — arm B fires when the level is negative, arm C
when the change is negative — so matching the firing-session mean would leave the two arms moving
different total amounts of weight, and a difference between them would be partly a difference in dose.

**So the arms are matched on mean shift across *all* sessions in the window set**, computed from the
pinned series alone before any card ran:

| window | sessions | B fires | B mean shift (all sessions) | C fires | C at k=1 |
|---|---:|---:|---:|---:|---:|
| `inv-2000` | 524 | 227 | 0.0595 | 212 | 0.0460 |
| `inv-2006` | 462 | 215 | 0.0173 | 171 | 0.0203 |
| `inv-2022` | 749 | 541 | 0.1733 | 397 | 0.0844 |

Pooled over 1,735 sessions: **B moves 0.0974 per session, C at k=1 moves 0.0557.** Arm C's
coefficient is therefore **k = 1.748**, so both arms move the same total weight over the window set
and differ only in *when* they move it.

For the record, B's mean shift over its own firing sessions is **0.1719**, reproducing round 23 §2a's
committed figure exactly — which is a check that this plan computes the calibration the same way that
round did, not a new result.

## 4. Windows and metric

Round 23's three, reused unchanged: `inv-2000` (1999-06-01 → 2001-06-29), `inv-2006` (2006-03-01 →
2007-12-31), `inv-2022` (2022-01-03 → 2024-12-31).

**The reuse carries no outcome selection and the treatment does vary in them**, which is the condition
round 21 failed and round 22 was built to satisfy. Confirmed before fixing them:

| window | ROC20 sd | ROC20 range | sessions falling |
|---|---:|---|---:|
| `inv-2000` | 0.1816 | [−0.48, +0.66] | 212 (40.5%) |
| `inv-2006` | 0.1104 | [−0.23, +0.41] | 171 (37.0%) |
| `inv-2022` | 0.1917 | [−0.46, +0.61] | 397 (53.0%) |

They were originally selected on the *level* crossing zero, and round 23 returned null in all three,
so nothing about these windows was chosen for favouring this round's arm.

**Metric:** total return, max drawdown and MAR. An `AllocationCard` carries the `invested-value`
basis and `app.tournament.results` refuses `adjusted_excess` for it, so round 22 §5's exposure-credit
caveat does not arise — a consequence of the card shape, as recorded in round 23.

## 5. Falsifiable predictions

1. **Arm B reproduces round 23's `c-sized` figures exactly**, to the cent, in all three windows. This
   is an **instrument check, not a hypothesis** — it is the same card on the same windows under the
   same pin. If it fails, this round is measuring something other than it claims and its output is
   void rather than interesting.
2. **`|A − C|` will not exceed the 21.2pp noise floor in any window.** The honest prior, on a base
   rate of ~50 concepts and no durable survivors.
3. **Arm C's marginal against A is inside its null in at least 2 of 3 windows.** The round's central
   claim. Rounds 22 and 23 were null in 3 of 3 for the level; the prior is that the derivative of an
   uninformative signal is also uninformative.
4. **Arm C trades more than arm B in all three windows.** The level crosses zero rarely; the change
   oscillates around zero constantly, so C's tilt switches on and off far more often. **If C is not
   the busier arm, the band is absorbing the oscillation** — which would be round 23's prediction-5
   mechanism recurring at a different frequency, and is the more interesting outcome of the two.
5. **Arm C outperforms arm B in `inv-2022` on total return.** The curve is inverted for 72.2% of that
   rising window, so the level arm sits defensive through a rally; the change is negative only 53.0%
   of it. If C does *not* beat B there, the tilt is not being driven by how much of the window it sits
   out, and prediction 3's reading would need revisiting.

## 6. The null, and it corrects round 23's

Arm C's marginal against arm A, compared to **200 circular shifts of the derived ROC series' values** —
the construction rounds 22 and 23 used, applied to this round's treatment.

**The primary decision rule is the treated-only interval**, not the all-replicate one. Round 23's
Amendment 3 established that 42.5%–62.5% of replicates in this construction apply no treatment at all
— a circular shift lands the window on a stretch where the signal never fires, the card reproduces the
control exactly, and the replicate contributes a zero. That point mass makes the interval too narrow
and `outside` too easy to reach, and it is what produced round 23's one spurious `outside`.

Both intervals will be reported, so this round stays comparable with rounds 22 and 23 as published.
**Where they disagree, the treated-only interval governs**, and that is fixed here rather than chosen
after seeing which one is more convenient.

A marginal inside that null is not evidence of anything, however large it looks.

## 7. What this round cannot settle

- **Not expressible in a card.** §2. A null here closes the question; a non-null would only open an
  engine-change question, and nothing in this round is promotable under any outcome.
- **One lookback, one direction, one sleeve pair, one coefficient, one series.**
- **Three windows from one economy**, sharing two monetary regimes between them. No median will be
  computed across them.
- **Nothing about rounds 22 or 23**, whose questions are answered and are not revisited here.

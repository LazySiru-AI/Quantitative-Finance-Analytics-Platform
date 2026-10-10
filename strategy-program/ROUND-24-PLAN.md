# Round 24 — does the trading book's ranking survive the trading book's own mandate?

**Pre-registered 2026-08-30, before any run in this round existed.** Cards were written to
`data/rounds/r24-2026-08/cards/` and this document committed before the first backtest.
`PROTOCOL.md` §2 phase 2 is the integrity boundary; nothing below is revised after a result.

**Not investment advice.** Every figure this round will produce is a simulation against stored price
history on a paper account.

## 1. Why this round exists

`ACCOUNT-DEPLOYMENT-PLAN.md` §0 records the owner's mandate for the trading book:

> horizon: **days to 6 months, 6 the maximum**

Two of the four rules cards seated on that book cannot honour it. `max_hold_days` is counted in
**sessions** (`app.tournament.runner._decide_exit`: `held = session.index - lot.entry_session_index`),
so at ~21 sessions per calendar month:

| card | `max_hold_days` | ≈ calendar | inside the mandate? |
|---|---|---|---|
| `B3-concentrated` | 180 sessions | **8.6 months** | **no** |
| `B-momentum` | 180 sessions | **8.6 months** | **no** |
| `A-rotation` | 120 sessions | 5.7 months | yes |
| `C-trend` | 120 sessions | 5.7 months | yes |

This is not hypothetical. As of `as_of = 2026-08-28` both momentum cards hold **MRVL entered
2026-03-11 — 118 sessions, ~5.6 calendar months — with 62 sessions still to run before their time
stop fires.** That position crosses the owner's six-month line in roughly eight sessions and the card
will not exit it; the stop is set to let it run until roughly December.

It matters because of where those cards' returns live. On the live book (2026-01-01 → 2026-08-28):

| card | total return | realised P&L | unrealised P&L | trades |
|---|---|---|---|---|
| `A-rotation` | +56.83% | **+$37,039** | −$2,940 | 35 |
| `B3-concentrated` | +47.11% | **−$4,916** | +$33,184 | 5 |
| `B-momentum` | +28.85% | **−$4,784** | +$22,097 | 8 |
| `C-trend` | −3.07% | −$1,345 | −$496 | 10 |

`B3-concentrated` ranks **first** on round 11's live matrix (+7.41% median adjusted excess) and its
realised P&L is negative. Its entire standing is two positions — MRVL +131.3% and AMD +99.7%,
together $30,356 of $33,184 unrealised — held past the point the account's mandate allows.

## 2. The question, in one sentence

**If the two non-compliant cards are made to honour the six-month mandate, does the live ranking that
seats them survive?**

## 3. Arms

Six cards, one matrix. The four seated rules cards unchanged, plus one variant each for the two that
breach the mandate. Each variant isolates **exactly one** decision (`PROTOCOL.md` §7): `max_hold_days`
180 → **126** (6 calendar months at 21 sessions/month). Nothing else differs, byte for byte.

- `B3-concentrated` / `B3-concentrated-cap126`
- `B-momentum` / `B-momentum-cap126`
- `A-rotation`, `C-trend` — already compliant, run as controls so all six share one matrix

## 4. Matrix

Round 11's live matrix, unchanged and for the same reason: six **cumulative** runs from one fixed
start `2026-02-17`, differenced into sub-periods (`run_live_matrix.sh`; independent sub-windows are
DEFECTS.md D5 and are not used). Boundaries `2026-03-18, 2026-04-17, 2026-05-18, 2026-06-17,
2026-07-20, 2026-08-18`.

Scored on `adjusted_excess`, the `PROTOCOL.md` §4 key.

## 5. Pre-registered predictions

Recorded now so the report prints prediction beside outcome.

1. **The card's own author predicts the cap hurts.** `B3-concentrated`'s thesis states that capping
   the hold "cut mean per-signal return to 2-9%" and that letting it run "produced roughly triple the
   aggregate return of either capped variant". So: **both `-cap126` variants post a lower live median
   than their base.** If they do not, the thesis is wrong about its own strategy.
2. **The cap binds inside this window.** MRVL is at 118 sessions; a 126-session cap fires on it before
   2026-08-18. So **the variants take at least one time-stop exit their bases do not.** If trade counts
   are identical the round measured nothing and must be reported as inert (this is the failure round 21
   hit and it is named here in advance).
3. **`A-rotation` leads on realised P&L regardless of arm**, because no arm changes it.

## 6. What the round can and cannot decide

**Can:** whether the momentum cards' live standing depends on holding past the mandate.

**Cannot:** which card is better in any general sense. Six contiguous sub-periods of one period are
not six regime draws (`desk.py`'s own roster note, round 11 §4). And every margin here is subject to
`PROTOCOL.md` §7's ordering floor — σ = 21.2 points, measured on three-year returns. **No promotion,
in either direction, on a margin inside that floor**, §6(b). A live-matrix spread of a few points
does not clear it, and this round will not pretend otherwise.

## 7. Falsification

If the variants match their bases within the noise floor **and** take the same trades, this round
found nothing and says so. A null is the expected outcome of most rounds in this programme.

---

## 8. Result of the live arm, and amendment 1 — pre-registered before the second arm ran

**The live arm is INERT. Prediction 2's falsification clause fired, and prediction 1 is refuted on a
zero.** Full scorecard: `data/rounds/r24-2026-08/scorecard.json`.

| | base median | cap126 median | delta | trades | exit reasons |
|---|---|---|---|---|---|
| `B3-concentrated` | +7.41% | +7.41% | **0.00pp** | 6 = 6 | `{rule: 2}` = `{rule: 2}` |
| `B-momentum` | +4.82% | +4.82% | **0.00pp** | 11 = 11 | `{rule: 5}` = `{rule: 5}` |

Byte-identical. **Zero time-stop exits in either arm**, so the cap never fired and the two arms are
the same measurement. Prediction 1 reads "REFUTED" only because a zero delta is not a negative one;
nothing about the author's claim was tested.

**Why, and it is my pre-registration that was wrong, not the engine.** §1 read MRVL's `bars_held =
118` off the desk at `as_of = 2026-08-28` and §5 asserted a 126-session cap "fires on it before
2026-08-18". Those are two different dates. At the r11 matrix's own 2026-08-18 boundary MRVL had been
held ~110 sessions, and **as of 2026-08-28 it is still 8 sessions short of 126.** The cap binds in the
future — roughly the second week of September — not inside the window this arm measured. A round
cannot measure a constraint that has not bound yet.

**Amendment 1, pre-registered here before the second arm runs.** The mandate question moves to the
window set where a 126-vs-180 session difference can actually express itself: the round 2 main matrix,
eight regime windows spanning the GFC, COVID, two bears, two chop regimes and two bull runs
(`score.R2_MATRIX`). Same six frozen cards, unchanged, same commit `9dcd283`. Nothing about the cards
moves; only the windows they are measured on.

**Predictions for the second arm, recorded now:**

1. **The cap binds here.** Both `-cap126` variants take at least one `time` exit their bases do not.
   If trade counts are again identical across all eight windows, the mandate is unmeasurable on this
   engine and the whole round is a null — stated as such, not rescued with a third arm.
2. **The author's claim, finally testable: the cap costs return.** Both variants post a lower median
   adjusted excess than their base. The thesis says "roughly triple the aggregate return" for the
   uncapped form, so the predicted gap is large — but §6's floor still binds, and a gap inside 21.2pp
   decides nothing either way.
3. **`A-rotation` and `C-trend` are unchanged in both arms** (both already at 120 < 126). Any
   difference in their numbers between arms is a matrix effect, not a card effect, and is the control
   that says so.

---

## 9. Result of arm 2 — the cap binds, and the card author's own claim is refuted

Scorecard: `data/rounds/r24-2026-08/scorecard-r2.json`. Six of eight main windows carried the whole
field; `gfc` lost all six cards to AVGO (first bar 2009-08, after the window ends) and `chop-2011`
lost five to META (first bar 2012-05) — the identical universe-history wall round 1 §1 documented,
not a new failure. **Zero `IOException` among the failure lines**, so no card was lost to store
contention (DEFECTS.md D3). Six eligible windows clears §3 rule 7's five-of-eight gate.

| card | q4-2018 | covid | bear-2022 | chop-2015 | bull-2024 | recent | **median** | trades | time exits |
|---|---|---|---|---|---|---|---|---|---|
| `B3-concentrated` | −1.18% | +26.76% | −7.75% | **+23.29%** | +4.50% | +31.52% | **+13.89%** | 56 | 2 |
| `B3-concentrated-cap126` | −1.18% | +26.76% | −7.75% | **+13.14%** | +4.50% | +31.52% | **+8.82%** | 58 | 3 |
| `B-momentum` | −0.79% | +27.70% | −5.15% | **+24.60%** | +7.40% | +16.91% | **+12.16%** | 70 | 3 |
| `B-momentum-cap126` | −0.79% | +27.70% | −5.15% | **+16.54%** | +7.40% | +16.91% | **+11.97%** | 74 | 4 |

**Prediction 1 — HELD.** The cap binds: trade counts and time-stop exits both move (56→58 / 2→3 and
70→74 / 3→4). This arm measured something the live arm could not.

**Prediction 2 — direction HELD, magnitude REFUTED, and the magnitude was the claim.**

| | cost of honouring the six-month mandate |
|---|---|
| `B3-concentrated` | **−5.07pp** of median adjusted excess (+13.89% → +8.82%) |
| `B-momentum` | **−0.19pp** (+12.16% → +11.97%) |

`B3-concentrated`'s thesis states that capping the hold "cut mean per-signal return to 2-9%" and that
running uncapped "produced roughly triple the aggregate return of either capped variant." **Measured
against a six-month cap on eight regime windows, the cost is five points on one card and two tenths of
a point on the other.** Nothing here is triple anything.

**And both costs sit inside the 21.2pp ordering floor**, so under §6(b) neither is a margin this
programme promotes or demotes on. That cuts one way only: it means **there is no measured reason to
keep holding past the mandate.** A card cannot claim a cost it cannot demonstrate.

**Where the cost actually lives, which the median hides.** Five of the six windows are byte-identical
between arms. The entire difference is `chop-2015` — B3 +23.29% → +13.14%, B-momentum +24.60% →
+16.54%. The cap costs money in exactly one regime: a directionless market, where a position runs on
without ever triggering the trend-break exit and only a clock gets it out. In every trending window,
up or down, the six-month cap was free.

**Prediction 3 — the control worked, and it reproduced the programme's oldest lesson.** `A-rotation`
and `C-trend` are unchanged between arms (both already 120 < 126). `A-rotation` posts a **−7.16%**
median here — last in the field — while posting **+3.47%** on the live matrix and **+19.92pp/yr** at
round 5's six-month rung. Same frozen card, three window sets, three different verdicts. That is
round 4-against-round 3 and round 5's bear arm all over again: the ranking is a property of the
window mix.

## 10. What round 24 decided, and what it did not

**Decided:** the six-month mandate is affordable. Honouring it costs `B3-concentrated` ~5pp and
`B-momentum` ~0.2pp of median adjusted excess, both inside the noise floor, and both concentrated in
a single chop window.

**Not decided:** which card is better. No margin in this round clears 21.2pp, in either arm, on
either matrix. Under §9's r21 amendment the `trading` purpose has no promotion rule at all, so nothing
here promotes or demotes anything by rule — it is evidence handed to the owner, which is what that
amendment says the trading book now runs on.

---

## 11. Correction, 2026-08-30 — this round tested a different lever than §5, §9 and its own title claim

Raised by `investing-dashboard-f8` while folding this round into `00-EVERYTHING-TESTED.md`, checked
against the card's own thesis text, and **upheld**. §5, §9 and §9's heading are wrong on one point,
and they are left standing above with this section as the correction rather than edited — §2 phase 2
freezes cards, and §8 already set the precedent that a pre-registration error in this round gets
recorded where a reader meets it.

**What the thesis actually says.** Quoted in full from `B3-concentrated.json`:

> I tested a fixed take-profit and a fast rule exit against simply riding the position to a stop or a
> genuine trend break, on this same entry: **capping gains at 8-30%** cut mean per-signal return to
> 2-9%, and a **fast 20-day-EMA exit** (even with a 3-day confirmation filter) cut it to 3-5% [...]
> Letting the position run to a stop, a 200-day trend-break, **or a 180-day backstop** produced
> roughly triple the aggregate return of **either capped variant**.

So the two "capped variants" are a **take-profit** and a **fast EMA exit**. The **180-day backstop is
part of the uncapped arm the author prefers** — it is on the winning side of that comparison, not the
losing one.

**What this round actually did.** It moved `max_hold_days` 180 → 126. That **shortens the preferred
uncapped arm**; it does not construct either variant the "roughly triple" claim is about. Neither a
take-profit nor a fast EMA exit was ever built here.

| | status |
|---|---|
| The measurement — `B3-concentrated` **−5.07pp**, `B-momentum` **−0.19pp** of median adjusted excess, both inside the 21.2pp floor, both confined to `chop-2015` | **stands, untouched** |
| Prediction 1 binding (the cap binds: 56→58 and 70→74 trades, time exits 2→3 and 3→4) | **stands** |
| §9's heading "the card author's own claim is refuted", and §9's "Nothing here is triple anything" | **withdrawn** |
| The "roughly triple" claim | **still untested** |

**Why the error is worth more than the correction.** §5 pre-registered a prediction attributed to the
card's author — "the card's own author predicts the cap hurts" — that the author never made about
this lever. A pre-registered prediction is supposed to be the thing that cannot move after the fact;
this one was mis-sourced *before* the round ran, so the round carried a borrowed authority it was
never entitled to. It did not corrupt a number, because the arms were frozen and the engine does not
read prose. It did corrupt the claim placed on top of them, which then propagated into
`app.paperdesk.desk`'s roster docstring, this round's commit messages, and a published report.

**What the round is, restated without the borrowed claim.** It asked whether the trading book could
afford its own mandate, and answered yes: honouring a six-month bound costs 5.07pp and 0.19pp of
median adjusted excess, both inside the noise floor. That is the whole finding, and it never needed
the thesis to support it.

**One further caveat from the same review, and it does not touch the headline.** §9's table shows six
windows for every card, but `A-rotation` has results in **seven** — it is the only card in the field
without META, so it survived `chop-2011` where the other five did not. Its **−7.16%** median is
therefore computed over a different window set than the medians beside it, and the cross-card ordering
in §9 compares across mixed sets. Every base-vs-`cap126` comparison is **within-card over the same six
windows**, so the round's actual result is unaffected; only the "A-rotation finishes last" aside is,
and that aside was already making the point that rankings move with the window mix.

# Thesis audit — what the seated cards claim, and what was ever measured

Run 2026-08-30, executing recommendation 7 of
[`00-EVERYTHING-TESTED.md`](00-EVERYTHING-TESTED.md). **Not investment advice.**

**Why this exists.** A card's `thesis` is prose. It is what a reader takes the card to have
established, it is displayed beside the card's live numbers, and **nothing in the apparatus checks
it** — no gate reads it, no test asserts against it, and no round has ever been designed to test one.
Round 24 was the first round to measure a claim a card makes about its own configuration, and this
audit is what that prompted.

**Method.** The seated roster is `app.paperdesk.desk`'s `AGENT_IDS`, `SAVINGS_AGENT_IDS` and
`ROTH_AGENT_IDS` — six cards. For each, every quantitative or falsifiable claim in its `thesis` was
extracted and marked:

- **measured** — a run outside the card's own design window tested it
- **in-sample** — the number is real but comes from the design window the card was built on, and has
  never been re-measured
- **contradicted** — a measurement disagrees with it
- **untestable here** — a judgment or a legal question, not a backtest question

**All six cards were read in full; nothing below is quoted from another document's summary of them.**
That matters, because the first finding is a misquotation in exactly such a summary.

---

## 1. The scoreboard

**Counted as distinct claims**, since `B3-concentrated` and `B-momentum` share a byte-identical thesis
and therefore share its four claims. The §4 table below is the authoritative list: **eleven distinct
claims**, of which two were measured when this audit was written.

| card | book | falsification clause | distinct claims | measured out of sample |
|---|---|---|---:|---:|
| `B3-concentrated` + `B-momentum` | trading | ~~none~~ → **added, retrospective** | 4 (shared) | ~~0~~ → **1** |
| `A-rotation` | trading | ~~none~~ → **added, retrospective** | 2 | ~~0~~ → **1** |
| `C-trend` | trading | ~~none~~ → **added, retrospective** | 3 | ~~0~~ → **2** (1 unaskable) |
| `spy-schd-agg-gld-bil-atr-tilt` | savings | **yes**, by its author | 1 | **1** |
| `ladder-sso-vig-bnd` | roth | **yes**, three, by its author | 1 | **1** |

**Corrected 2026-08-30:** this table previously read "eleven of thirteen" and counted the shared
thesis twice, giving a total that cannot be derived from §4's list. The derivable figure is **nine of
eleven never measured**, as audited. Round 26 has since moved four of those nine (§10).

**The four "added" clauses are not equivalent to the two authored ones and the table should not be
read as if they were** — see §8. They were written on 2026-08-30, after the cards had live records,
so they are not pre-registrations; each says so in its own first sentence. **Writing a condition
measures nothing** — the column moved only when round 26 ran them (§10).

**As audited, the split was total and ran along card type.** Both allocation-family cards state in
advance what would make them wrong, name the document that will contain the number, and the number
exists. **None of the four trading cards stated a falsification condition at all** — that gap is now
filled retrospectively (§8) — and not one of their eleven quantitative claims has been re-measured
outside the window it was fitted on. **That second half is unchanged and is the finding that matters.**

### Why the split runs that way, found while building the fix

It is not a difference in the analysts. It is written into the models. `AllocationCard.thesis`'s
docstring has always demanded a falsification condition:

> A thesis for this card shape **additionally has to say what result would prove it *wrong***.

`StrategyCard.thesis`'s docstring never did, and neither did `LadderCard`'s — though the seated ladder
card volunteered three clauses anyway. **The roster reflects which shape was asked.** Every card that
was told to state a falsification condition stated one; no card that was not, did.

That is a better explanation than any about care or rigour, and it is the argument for §6's fix: the
requirement already worked, on the one shape that carried it, and it was never written down where the
other two shapes could see it.

## 2. Two seated cards carry the same thesis, byte for byte

`B3-concentrated` and `B-momentum` — two of the four cards seated on the trading book — have
**identical** `thesis` strings: 1,890 characters, character-for-character the same.

They are not the same card. Round 24 measured them over six regime windows and they behave
differently: 56 trades against 70, medians of +13.89% and +12.16%, and 2 time-stop exits against 3.
So one rationale is doing duty for two distinct configurations, and a reader comparing the two cards
on the desk is given no stated reason to prefer either.

This also sits against the desk's own seating rule, which says at most one card per base family may be
seated *"so the desk does not show one idea twice."* By the test a reader would actually apply —
does the card explain itself differently — the desk is showing one idea twice.

## 3. Round 24's refutation is misattributed, and this report repeated it

Round 24 §9 states:

> `B3-concentrated`'s thesis states that capping **the hold** "cut mean per-signal return to 2-9%"

The thesis says **capping gains**:

> capping **gains at 8-30%** cut mean per-signal return to 2-9%, and a fast 20-day-EMA exit … cut it
> to 3-5% … Letting the position run to a stop, a 200-day trend-break, or a **180-day backstop**
> produced roughly triple the aggregate return of **either capped variant**

The two "capped variants" are a **take-profit** and a **fast EMA exit**. The 180-session backstop is
part of the *uncapped* arm the thesis prefers. Round 24 changed `max_hold_days` from 180 to 126 — it
shortened the backstop **inside** the preferred arm, which is neither capped variant.

**So round 24 measured a lever the "roughly triple" claim was never about.** Its measurement stands
and is useful; the mapping onto the thesis does not. `00-EVERYTHING-TESTED.md` §5g and recommendation
7 repeated the misattribution and are corrected in the same commit as this file.

**What round 24 did establish**, stated correctly: shortening the backstop from 180 to 126 sessions
costs **5.07pp** of median adjusted excess on `B3-concentrated` and **0.19pp** on `B-momentum`, both
inside the 21.2pp floor, and the entire difference lives in one chop window.

**And the "triple" claim remains untested.** The nearest evidence is round 18, which measured exit
discrimination directly and found an exit marginal of **3.58pp** — far inside the floor — on a
different universe and different forms. That is tension, not a refutation, and the honest status of
the claim is *in-sample, never re-measured*.

## 4. The trading cards' numbers are all design-window numbers

Every quantitative claim on the four trading cards is measured "on the design-window history" or
"through 2026-02-13" — which is `DESIGN_THROUGH`, the boundary the engine enforces precisely so that
design-window evidence cannot leak into scoring.

| card | claim | status |
|---|---|---|
| `B3` / `B-momentum` | move duration median 3–4 weeks, >2 months at p75 (NVDA 256 sessions, MSFT 169, TSM 189) | in-sample |
| `B3` / `B-momentum` | take-profit at 8–30% cuts mean per-signal return to 2–9% | in-sample |
| `B3` / `B-momentum` | fast 20-day-EMA exit cuts return to 3–5%, win rate to 42–49% | in-sample |
| `B3` / `B-momentum` | uncapped produced "roughly triple" either capped variant | in-sample; see §3 |
| `A-rotation` | mean pairwise correlation 0.589, range 0.286–0.824 across the 9 names | in-sample |
| `A-rotation` | breadth: median 4 of 9 qualify; ≥4 on 50.6% of sessions, ≥6 on 21.3% | in-sample |
| `C-trend` | 77 trades, 49.4% win rate, winners +29.6% = 4.1× losers −7.3%, held 118d vs 16d | in-sample |
| `C-trend` | speculative names (IREN, OKLO, APLD, BE, KORU) show negative 60-day forward returns | in-sample |
| `C-trend` | stop 8%→12% cuts stop-outs 12/77→7/77, mean trade return 0.093→0.093 | in-sample |

**This is not an accusation of lookahead.** These are honest design-window measurements and the
guard is what keeps them out of the scoring. The point is narrower and worse: **a reader cannot tell
which of these numbers survived contact with an out-of-sample window, because none of them were ever
put to one.**

**Two cards deserve credit inside this.** `A-rotation`'s thesis states plainly that the engine cannot
express relative strength, that the card is "a concentrated sector bet dressed as a 3-of-9 rotation,
and I am not pretending otherwise", and that its fill order is an arbitrary alphabetical tiebreak
rather than a leader-selection mechanism. `C-trend` excludes five names **on measured evidence**
rather than on a prior. Those are the two most falsifiable-in-spirit statements on the trading book,
and neither is a falsification clause.

**The uncomfortable pairing.** `C-trend` has the most carefully measured thesis of the four and the
worst live record of the four: **−3.07%** total return on the live book, against +56.83%, +47.11% and
+28.85%. Whatever the theses are doing, they are not ordering the cards.

## 5. The two allocation-family cards did what the recommendation asks for

**`spy-schd-agg-gld-bil-atr-tilt` (savings)** states its falsification condition — the thesis is wrong
"if elevated SPY ATR is not followed by continued or deepening equity stress often enough to be worth
the shift's cost", and is "further undermined" if the tilt's turnover costs more than the drawdown it
avoids. It names `ALLOCATION-FAMILY.md` as where the test lives, and **the test is there**, against a
static no-tilt control of the same five sleeves, with 5bp one-way slippage modelled rather than
zeroed:

| 2011–2026 | ending | total | CAGR | max DD | MAR | rebalances |
|---|---:|---:|---:|---:|---:|---:|
| static core-satellite | $32,141 | 221.6% | 8.23% | −21.5% | 0.38 | 7 |
| ATR-tilt core-satellite | $30,694 | 207.1% | 7.89% | **−19.9%** | **0.40** | **44** |

**The falsification condition is not met** — the tilt does buy a shallower drawdown (−21.5% → −19.9%,
and −36.3% → −32.6% in the 2007–2011 crisis slice), at 25.0bp of final balance in slippage. But the
margin is thin: **MAR moves 0.38 → 0.40** for **6.3× the turnover**, and in the crisis slice MAR
actually *falls* (0.02 → 0.01) despite the shallower drawdown. **No null was computed for any of it**,
so by this programme's own standard the tilt is not established as worth its cost either — it is
"measured, not refuted, not confirmed", which is a materially better position than any trading card
occupies.

**`ladder-sso-vig-bnd` (roth)** is the best-documented card on the desk. It states **three** distinct
falsification conditions, and for the third it explicitly refuses to pre-empt the number: *"see that
script's own report for the measured number, not a claim made here in advance of running it."* The
number exists, in `ROTH-DISJOINT-LADDER.md`:

| cost of holding the strategy on Roth-disjoint tickers | |
|---|---|
| money-weighted IRR | **−2.02pp** (11.59% → 9.56%) |
| time-weighted CAGR | **−1.72pp** (10.60% → 8.88%) |
| MAR | **−0.09** (0.45 → 0.36) |

Whether that price is worth the tax protection is left as the owner's judgment, which is the correct
place for it — the clause asked for a number, and a number was produced.

## 6. What this changes

1. **`00-EVERYTHING-TESTED.md` §5g and recommendation 7 are corrected** for the misattribution in §3.
   Round 24 refuted no thesis claim; it measured a different lever and found the cost inside the floor.
2. **The headline finding is not "a thesis was wrong" — it is that eleven of thirteen claims cannot be
   wrong yet**, because nothing has ever tested them. The two that can be are on the two cards nobody
   was worried about.
3. ~~The cheapest fix is structural, not another round.~~ **Built, same day.** `falsification` is now
   a field on all three card models, and `tests/test_thesis_falsification.py` enforces it over the
   desk's three seated rosters — the set a reader sees beside live money — rather than over the whole
   library, where ~35 committed JSONs and the evolution loop's genome population would make a
   required field a migration instead of a check.

   The two cards that already stated a clause carry it in the field now, extracted **verbatim**;
   their theses are left byte-identical, because a thesis is written before the window ran and is not
   a later reader's to rewrite. **The remaining four are pinned by `xfail(strict=True)`** — the same
   device that held D8's intended behaviour before its fix existed. It fails today and XPASSes the
   moment the clauses are written, which forces the marker off.

   **That xfail was waiting for an author, not a code change** — the value of the field is an author
   naming, in advance, the measurement that would settle a claim, and the two cards that did went on
   to produce the number. **The four were then written by this audit instead, on the owner's
   instruction (§8).** That does not recover what an author would have supplied and §8 says so
   plainly; what it does is convert eleven untestable claims into named, runnable tests. The `xfail`
   came off in the same commit.

## 7. What this audit does not establish

- **It reads claims, it does not test them.** Nothing here re-measures a design-window number; it
  records which have been re-measured. Turning any of §4's rows into a result is a pre-registered
  round, not a reading exercise.
- **Six cards.** The library holds far more, including the whole evolution-loop population; only what
  is seated to a book was audited, because that is what a reader sees beside live money.
- **A thesis being unmeasured is not evidence the card is bad**, and this audit ranks nothing. It says
  what is and is not known, which on the trading book turns out to be very little.

---

## 8. Amendment, 2026-08-30 — the four missing clauses were written, and they are not pre-registrations

The `xfail` in §6 said it was waiting for an author. It was then written by this audit rather than by
the cards' authors, on the owner's instruction, and **that difference is not cosmetic** — the whole
value of the field is an author naming, in advance, the measurement that would settle a claim. Nothing
here recovers that. What it can do is convert eleven untestable claims into named, runnable tests.

**Three rules were held to, so the clauses are admissible rather than decorative:**

1. **Each names a measurement that has *not* been run.** A falsification condition written with the
   answer already in hand is precisely the failure the field exists to prevent, and §4's own record —
   *pre-registration protects a claim from moving afterwards and does nothing about one that was wrong
   going in* — is the sharper version. One candidate was dropped for exactly this: `A-rotation`'s
   universe-ordering sensitivity **has** been measured, on this card's predecessor, and is where the
   53.9-point spread and the 21.2-point floor come from. Writing it as a falsification condition would
   have been a test whose answer is already published.
2. **Each is traceable to a claim the thesis already makes**, so the clause names the settling
   measurement rather than inventing a claim on the author's behalf.
3. **Each announces itself.** Every one opens *"Added 2026-08-30 … This is NOT a pre-registration"*,
   and `tests/test_thesis_falsification.py::test_retrospective_clauses_say_that_they_are_retrospective`
   fails if a retrospectively-added clause omits the disclosure. A retrospective clause that did not
   say so would be the §4 failure wearing the field's authority.

### What each one asks for

| card | the measurement it names |
|---|---|
| `B3-concentrated` | Build the two capped variants the thesis names — a take-profit at 8–30% and a fast 20-day-EMA exit — as competing arms on round 2's regime matrix. "Roughly triple" is unsupported if the uncapped advantage sits inside the floor. |
| `B-momentum` | If the edge is "concentrated in a minority of large winners", six positions at 15% should dilute it against four at 22%. Falsified if this card does not post a lower median than `B3-concentrated`. |
| `C-trend` | Re-measure the 4.1× winner/loser asymmetry out of sample; run the five excluded speculative names as an arm, since an exclusion measured on the window it is applied to is the shape of a fit; re-run both stop widths. |
| `A-rotation` | Re-measure breadth on the regime matrix. If the 3-of-9 cap rarely binds, the card is "hold everything that qualifies" wearing a rotation's name. |

### The clause that found something while being written

`B3-concentrated` and `B-momentum` differ in **exactly two fields** — `max_positions` 4 against 6, and
`position_pct` 0.22 against 0.15. Same universe, entry, exit, stop, hold, and a byte-identical thesis
that **never mentions concentration at all**.

So the two cards are a concentration pair whose distinguishing decision has no stated rationale on
either card. Their clauses are written from opposite sides of that one difference, and both commit in
advance to the same conclusion: **if the two medians differ by less than the floor across the regime
matrix, the pair is one idea holding two seats.** §6's prediction — that a required field "would have
caught the duplicate thesis the moment the second card had to write down a distinct way of being
wrong" — is the one thing here that can be checked, and it held.

### Status of the xfail

Un-marked in the same commit that wrote the clauses, as its own reason required. The test is now a
**ratchet**: seating a card with no falsification clause fails, which is the only moment the
requirement is cheap to meet — before the card has a live record to write the clause around.

---

## 9. Amendment, 2026-08-30 — two of the four clauses named measurements that had already been run

§8 committed to three rules, and the first was that **each clause names a measurement that has not
been run**. Two of the four broke it, and a third partly did. Recorded here rather than quietly
repaired, because the failure is more instructive than the clauses were.

| clause | condition | status as written | truth |
|---|---|---|---|
| `B3-concentrated` | build the two capped variants | unrun | **unrun** ✓ |
| `B3-concentrated` | concentration vs `B-momentum` | unrun | **already run** ✗ |
| `B-momentum` | concentration dilution | unrun | **already run** ✗ |
| `C-trend` | win/loss asymmetry out of sample | unrun | **partly measured** ~ |
| `C-trend` | universe exclusion; stop width | unrun | **unrun** ✓ |
| `A-rotation` | breadth; the ordering horn | unrun | **unrun** ✓ |

**Round 24's arm 2 had already run every seated trading card on round 2's regime matrix as controls.**
Its scorecard was read, quoted and folded into `00-EVERYTHING-TESTED.md` §5g the same morning these
clauses were written. The check §3 of this document names — *quote the source and diff it against the
source* — is exactly the one not applied here, hours after naming it. §4 of the consolidated report
records that pre-registration cannot catch a claim that was wrong going in; this is that failure,
committed by the document that recorded it.

### What the already-run measurement says, and it is a finding

`B3-concentrated` and `B-momentum` differ in exactly two fields — `max_positions` 4 against 6,
`position_pct` 0.22 against 0.15 — under a byte-identical thesis. Round 24 ran both on an identical
six windows:

| window | B3 (4×22%) | B-momentum (6×15%) | B3 − Bm |
|---|---:|---:|---:|
| `q4-2018` | −1.18% | −0.79% | −0.39 |
| `covid` | +26.76% | +27.70% | −0.93 |
| `bear-2022` | −7.75% | −5.15% | −2.60 |
| `chop-2015` | +23.29% | +24.60% | −1.31 |
| `bull-2024` | +4.50% | +7.40% | −2.90 |
| `recent` | +31.52% | +16.91% | **+14.61** |
| **median** | **+13.89%** | **+12.16%** | **+1.74** |

**The concentration difference is doing no measurable work.** 1.74pp is inside the 21.2-point floor,
which is the condition both clauses committed to in advance: **the pair is one idea holding two
seats**, and §2's concern is now confirmed with a number rather than an argument.

**And the median flatters `B3-concentrated`.** `B-momentum` is higher in *five of six* windows; the
entire gap comes from `recent`. The directional prediction — that the six-position card posts the
lower median — is satisfied on one window by a margin inside noise, which is not support for the
thesis's "edge concentrated in a minority of large winners" so much as an illustration of why a
six-window median is a fragile statistic.

### And `C-trend`'s rationale has come apart

The same results answer half of `C-trend`'s first condition. Its `realised_reward_risk` out of sample
runs **3.45 to 5.55** across the four windows where it is defined — the thesis's 4.1× asymmetry
survives at the same magnitude. Its **win rate does not**: 49.4% on the design window against 0.0%,
0.0%, 0.0%, 15.4%, 40.0% and 20.0% out of sample.

So the card cuts losses as sharply as it claims and is right far less often than it claims, and the
two halves of "right less than half the time and still profitable" have separated. The hold-duration
half of the claim — winners held a median 118 days against 16 — is in no committed result, and that
is what the narrowed clause now asks for.

### What this changes about §8

Nothing about the disclosure rule, which held: every clause announced itself as retrospective. What
failed is the *unrun* rule, and it failed because the author checked the claim against memory instead
of against the scorecard sitting in the same repository. The three affected clauses now record the
measurement and its result, and name only what genuinely remains.

---

## 10. Amendment, 2026-08-30 — round 26 ran the clauses, and four of nine claims moved

`ROUND-26-PLAN.md`, committed before any card was authored; full write-up at
`data/rounds/r26-2026-08/REPORT.md`. Seven arms on the eight-window regime matrix, each isolating one
field. **All three controls reproduced round 24's committed medians exactly**, so the instrument is
verified and every figure came from one code version.

| claim | card | verdict |
|---|---|---|
| uncapped beats both capped variants | `B3` / `B-momentum` | **direction holds** — +13.89% against +3.01% (take-profit) and +9.63% (fast exit) |
| the 3-of-9 cap binds often enough to matter | `A-rotation` | **no** — median breadth below 4 in 6 of 8 windows |
| 77 trades, 49.4% win, 4.1× asymmetry, 118d vs 16d | `C-trend` | **half holds** — 3.23× and 82d vs 12d, but win rate 19.5% |
| widening the stop 8% → 12% is justified | `C-trend` | **not supported** — the 8% stop is marginally better |
| the five excluded names do not sustain the signal | `C-trend` | **unaskable on this matrix** — §2 of the plan |
| mean pairwise correlation 0.589 | `A-rotation` | still unmeasured |
| move duration median 3–4 weeks | `B3` / `B-momentum` | still unmeasured |

**So the count moves from nine of eleven never measured to five** — four measured, one established as
unaskable. That is the only thing that ever moved it: §8's clauses measured nothing, and said so.

### The finding that changes how a card should be read

**`A-rotation`'s two conditions answered each other.** Imposing a ranking key moved its median only
7.59pp — inside the floor — and the breadth scan says why: median names qualifying is below 4 in six
of eight windows and **0 or 1 in three of them**. The thesis defends the cap by arguing breadth
"genuinely varies session to session… so the cap binds and actually forces a choice often enough to
matter". Out of sample it usually does not, so the fill order the thesis was honest about barely gets
consulted. **The card is closer to "hold everything that qualifies" than to a rotation**, and its
candour about the alphabetical tiebreak turns out to have been worrying about the wrong thing.

### The finding that goes the card's way

**`B3-concentrated`'s central claim survives its first test, and then some.** The take-profit arm
posts +3.01% against the control's +13.89% — a ratio of **4.6×**, more than the "roughly triple" the
thesis asserts, measured on a matrix its author never ran. The fast-exit arm is only 1.44×, so the
claim holds for one of the two variants it names.

This is the first time in this programme's record that a seated card's own argument has been tested
and come back *supported*. It should be read with the caveat that governs the whole round: **10.88pp
is inside the 21.2-point floor**, so this is a direction, not a magnitude.

### What the whole exercise cost, and what it bought

Recommendation 7 produced a field and eleven named tests. Recommendation 8 ran four of them. The
pattern across every one is the pattern §1 of the consolidated report has recorded for twenty-six
rounds: **the mechanisms are real and the magnitudes sit inside the noise.** What is new is only that
the claims under test were the cards' own, and that three of five pre-registered predictions were
refuted — which is a better yield of surprise than any round in the macro line returned.

---

## 11. Amendment, 2026-08-30 — round 27 measured the last three claims, and the scoreboard is closed

`ROUND-27-PLAN.md`, committed before any measurement existed; write-up at
`data/rounds/r27-2026-08/REPORT.md`. All three claims were stated as statistics about bars and
signals, so each was measured directly rather than through a backtest. **Every headline was recomputed
independently and matched to the digit.**

| claim | card | verdict |
|---|---|---|
| pairwise correlation ~0.589 | `A-rotation` | **holds, and understated** — mean above 0.589 in 6 of 8 windows |
| move duration 3-4 weeks / past two months | `B3` / `B-momentum` | **p75 holds; the median claim is 2.5x too low** — measured 47.5 sessions |
| excluded names show negative forward returns | `C-trend` | **refuted** — pooled +19.89%, every name positive |

**All nine of section 1's originally-unmeasured claims are now resolved:** five measured across rounds
26-27, one settled without a run (concentration, section 9), one established unaskable as a backtest
(`C-trend`'s exclusion, though its cited *statistic* is refuted here), and two -- `A-rotation`'s named
min/max pairs -- checked and found not to reproduce. Nothing on the four seated trading cards is now an
untested quantitative claim.

**The finding across both rounds is not that the cards are bad.** It is that a thesis is prose written
before a live record, and prose drifts from measurement **in both directions**. `A-rotation`
understates its own correlation; the momentum cards understate their own move duration; `C-trend`
asserts a forward-return sign that is simply wrong. The `falsification` field does not fix that for the
seated cards -- their theses are already written -- but it makes the next card's claims measurable by
construction rather than three rounds after the fact, which was the whole point of recommendation 7.


# Round 43 — does the bond sleeve's own trend decide how defensive a savings book should be?

Pre-registered **2026-09-09**, before any measurement in this round exists. **The round has NOT been
run.** No card here has been executed over any evaluation window, no margin has been computed, and
nothing below reports an outcome. **Not investment advice.**

Authored by `strategy-program/tools/round43.py`; the frozen field is
`data/rounds/r43-2026-09/cards/*.json` (6 cards); the tests that pin the field to this document are
`tests/test_round43_field.py`.

---

## 1. Why this round is new

Every savings-purpose tilt this programme has run — the ATR-tilt in `ALLOCATION-FAMILY.md`, the
vol-trim variants, and round 38's real-yield and price-placebo cards — reads its condition off **the
EQUITY sleeve's own bars, or off a macro series**, and moves weight out of equity when that condition
fires. `SAVINGS-FAMILY.md`, `ALLOCATION-FAMILY.md` and `ROUND-38-PLAN.md` were re-read on 2026-09-09
to confirm this: `close < sma(200)` on SPY (round 38's placebo, and the family's textbook constant),
SPY's own rolling ATR(14) (the allocation family's tilt), and the round-38 macro terms are all read off
SPY or a FRED series — never off `AGG`. The bond sleeve has been held at a static weight, rebalanced
only by the drift band, in every card this programme has ever run.

`PERSONA-DISCUSSION-2026-09-09.md` §3 supplies a hypothesis this specific gap has never tested: the
corpus's savings-relevant theme is not "equity is risky", it is "the bond sleeve is the risk." Creator E
Dante (Creator D): "rising bond yields are a real risk to portfolios" (§3, savings answer). Creator A
volunteers the destination: "overweighting precious metals during macro stress" (§3, savings answer).
Creator B reads the regime as "financial repression, currency cycles" among the forces that
should decide sleeve allocation (§3, savings answer) — a framing under which bonds are structurally
disfavoured, not merely cyclically. None of the three states a numeric threshold; §5 of the discussion
doc says so explicitly, and this round supplies the threshold itself rather than attributing it to any
persona.

So: a new sleeve read on the same book, the same card shape, and the same family this programme has
already measured — round 38's placebo (`close < sma(200)` on SPY, SPY → BIL) is reproduced **verbatim**
as this round's comparator, so the only thing that varies between the new field and a result this
programme has already reported is which sleeve's bars the condition reads and where the shifted weight
goes.

## 2. The prior is a null, and this round pre-registers one

Round 38 (the only prior savings-purpose conditional-tilt round with a written verdict) found: the
real-yield macro tilt moved drawdown by **+0.37pp**, and its own price-only placebo — `close < sma(200)`
on SPY, SPY → BIL — beat it, at **+0.94pp**, "the best in r38's field"
(`data/rounds/r38-2026-09/REPORT.md` §§1–2). Every allocation-family tilt in `ALLOCATION-FAMILY.md`
and every savings-family variant in `SAVINGS-FAMILY.md` reads as a modest, inside-the-floor effect at
best. Nothing about reading a *different* sleeve's bars changes what has been true of every other tilt
this programme has tested: **this round predicts a null** (§5, P1). It earns its place by testing an
unread sleeve, not by expecting a different answer.

**The corpus supplies the hypothesis; the programme supplies the threshold and the null.** No
influencer is endorsed, no persona's track record is measured, and a null here is a verdict on one
mechanical reading of a claim three personas share in different words — not on any of them.

## 3. Where the hypothesis comes from

Quoted verbatim, ≤15 words each, from `PERSONA-DISCUSSION-2026-09-09.md` §3 (the savings answers):

- **Creator D (Creator D):** "Rising bond yields are a real risk to portfolios."
- **Creator A:** "overweighting precious metals during macro stress"
- **Creator B (creator-b):** "inflation, deflation, financial repression, currency cycles"
- **Creator C**, on the *failure* side (his own pre-registered regime for any MA de-risk on this
  book): "would have hurt badly in the 1995–1996 Fed hiking cycle" — and again, per the same answer,
  in 2021–2022.

The triage table (§4 of the discussion doc) routes Creator D's savings answer and Creator A's
destination to this round explicitly: *"the bond sleeve's own trend is expressible: `close < sma(200)`
on AGG ... Round 43 (hypothesis; thresholds are the programme's, not his)"* and *"the destination is
expressible (AGG → GLD) ... Round 43 comparator arm."* Creator B's trim-the-winner rule is
routed to round 44, not here; his macro-regime framing is cited above only as the third independent
voice for "the bond sleeve, not the equity sleeve, is where the risk sits."

## 4. The book, the field, and every number in it

### 4a. The book

`purpose = Purpose.SAVINGS`: **$100,000 lump sum, 10–20 year horizon, taxable**, benchmark
**`30-70-spy-agg`**, mandate lowest drawdown, least return accepted — identical to round 38's book, so
this round's numbers sit beside that report's without re-justifying the mandate.

**Taxable/roth disjointness.** `round43.py` recomputes the live roth union from
`app.evolution.promotion._library_cards` (all six tiers) and refuses `--write` on a violation, exactly
as `round38.roth_union` does. This field's sleeves are `SPY AGG GLD BIL` — the identical set round 38
already cleared against the same union on the same day.

### 4b. The base allocation, identical on every card including the control

Reused from round 38 without modification, because this round varies the tilt's sleeve and destination
and nothing else (PROTOCOL.md §7): **SPY 0.30 / AGG 0.50 / GLD 0.10 / BIL 0.10**, `band_pct = 0.05`,
`designed_through = DESIGN_THROUGH` (2026-02-13). SPY is pinned at 30% because that is the savings
benchmark's own equity share — no card in this field makes an unstated equity-beta bet against what it
is scored against. Every sleeve's first bar clears every window used here (SPY 1993-01-29, AGG
2003-09-29, GLD 2004-11-18, BIL 2007-05-30, re-verified against the live store in the tool's dry run);
the earliest window is `h10y-1` (2013-09-03), so no sleeve binds.

### 4c. The field — 6 cards, no grid

`shift_pct = 0.10` on every rule, the same round-38 justification: larger than the 5-point band, so a
firing condition always breaches and is guaranteed to be *expressed* as a trade rather than absorbed.

| card | condition | on_symbol | shift | role |
|---|---|---|---|---|
| `r43-control` | *(none — `rules == ()`)* | — | — | **Mandatory control.** Same sleeves, same band, no rule. |
| `r43-agg-trend-bil` | `close < sma(200)` | `AGG` | AGG → BIL | **Primary treatment.** The bond sleeve's own trend, de-risking into cash. |
| `r43-agg-trend-gld` | `close < sma(200)` | `AGG` | AGG → GLD | Same condition, Creator A's metals-in-stress destination instead of cash. |
| `r43-agg-trend-bil-sma100` | `close < sma(100)` | `AGG` | AGG → BIL | Threshold-insensitivity check (§3 rule 4) — 100 sessions ≈ Creator C's 20-week line. |
| `r43-gld-trend` | `close > sma(200)` | `GLD` | AGG → GLD | Trend-*confirmed* metals tilt: only rotate into GLD while GLD's own trend is up. |
| `r43-price-placebo-spy` | `close < sma(200)` | `SPY` | SPY → BIL | **Round 38's placebo, reproduced verbatim** — this round's comparator. |

`r43-price-placebo-spy` is byte-for-byte the same condition, `on_symbol`, `from_symbol`, `to_symbol`
and `shift_pct` as `r38-price-placebo`; only the `agent_id`, `designed_through` (unchanged — both
rounds share `DESIGN_THROUGH`) and the surrounding field differ. Its role is not to re-measure round
38 — the two rounds share windows and a re-run would be one measurement counted twice
(PROTOCOL.md §6(a)) — its role is to be the **within-round** yardstick the bond-sleeve cards are
compared against, on the identical windows, in the identical run.

**Free numbers (PROTOCOL.md §3 rule 3, budget 10):** control **5** (4 sleeve weights + band); every
other card **7** (4 weights + band + 1 threshold literal in `sma(N)` + 1 shift). Counted mechanically
by `round43.free_numbers`, ported unmodified from `round38.free_numbers` (same tree walk, same
generous-counting convention: sleeve weights counted in full, not as `n − 1` independent numbers).

### 4d. Every threshold, and why it is not a searched number

- **`sma(200)`** on `AGG`, `GLD` and the placebo `SPY` — the textbook constant already frozen in
  `app.evolution.ruleforms`, reused unmodified from round 17 and round 38's placebo. No return series
  was read while choosing it for any of the three sleeves it is applied to here.
- **`sma(100)`** on the sensitivity card — approximately Creator C's own 20-week moving average (20
  weeks × 5 sessions = 100 sessions), the number he names as his own working timeframe in the
  discussion doc's roth/savings answers, kept round rather than converted to a literal 20-week
  resample.
- **`shift_pct = 0.10`** — round 38's figure, unchanged, justified against the band rather than any
  outcome (§4c above).
- **`band_pct = 0.05`**, the base weights — round 38's figures, unchanged; see 4b.

**No grid search.** Two thresholds on one series (`sma(200)` vs `sma(100)`, both on `AGG`) is a stated
sensitivity pair, per §3 rule 4, not a sweep — P3 below is the falsifiable claim the pair exists to
test, and both cells are reported regardless of which one, if either, shows a margin.

## 5. Predictions — falsifiable, fixed before the run

**P1 (the pre-registered null, and the primary prediction).** The treatment-minus-control margin in
max drawdown for `r43-agg-trend-bil` will be **a fraction of a percentage point** across the eligible
5y and 10y rungs — the same order of magnitude every prior savings tilt in this programme has shown
(round 38's largest margin was 0.94pp; the allocation family's largest was single digits of a point).
*Falsified by* a drawdown margin exceeding a few points, consistent in sign, across both 10-year rungs
and at least two 5-year rungs.

**P2 (the bond-sleeve read does not beat the equity-sleeve read).** `r43-agg-trend-bil`'s drawdown
margin will **not** exceed `r43-price-placebo-spy`'s (round 38's own best cell, +0.94pp). *Falsified
by* the AGG-trend card beating the SPY-trend placebo on the drawdown margin by more than the noise
floor — the first time in this programme's savings line that reading the bond sleeve's own bars has
outperformed reading the equity sleeve's.

**P3 (insensitivity).** `r43-agg-trend-bil-sma100` will be statistically and practically
indistinguishable from `r43-agg-trend-bil` — different firing sessions (AGG's `sma(100)` and
`sma(200)` cross the price at different times), similar aggregate margin, because a genuine bond-stress
signal should not evaporate one notch away from an arbitrarily chosen window length. *Falsified by* a
drawdown margin on one card that is materially larger than the other's *and* opposite in sign, which
would indicate a fitted rather than a structural rule.

**P4 (GLD is not a cash proxy).** `r43-agg-trend-gld`'s realised volatility, over any window where it
differs from `r43-agg-trend-bil`, will be **higher** — GLD is a volatile, non-yielding commodity, not a
defensive cash instrument, so routing the same de-risking signal into it rather than BIL should widen
the return distribution even where it also shifts the drawdown number. *Falsified by* the GLD
destination showing volatility at or below the BIL destination's on the same fired sessions.

**Hindsight, stated bluntly.** Every note in the persona vault carries `published = null`
(`PERSONA-HYPOTHESES.md` §2, §7), and the bond-stress thesis quoted in §3 is voiced with 2022 already
known. Two of this round's six bear-supplement windows, `b6m-2` (2021-12-15 → 2022-06-16) and `b1y-1`
(2021-12-28 → 2022-12-28), sit inside the exact regime the hypothesis was voiced after. **These two
windows are therefore in-sample to the hypothesis, not out-of-sample evidence for it**, and the harness
(§8) prints them in a table separate from every other window, labelled as such. A margin that appears
**only** in `b6m-2`/`b1y-1` and nowhere else in the 15-window set is hindsight confirming what was
already known when the claim was made, not a finding — this is pre-registered here so that no later
reading of this round's tables can mistake one for the other.

**Named failure regimes.**

- **The 2013 taper-tantrum-style whipsaw.** A bond-trend condition can flip on a false break that
  reverts within weeks — `taper-2013` (2013-05-22 → 2013-09-05, not in this round's ladder but the
  regime it names) is the canonical instance; `h5y-1`/`h3y-1`/`h10y-1`, which include 2013–2014, are
  where this shows up if it does. The tilt is predicted to whipsaw here, adding trades and volatility
  without a compensating drawdown benefit.
- **The 2019 bond rally the tilt sits out.** `AGG` rallied through 2019 as rates fell; a card that
  de-risks *out of* AGG on a downtrend signal has nothing to say about missing a rally it was never
  positioned to catch, but a rule that also somehow triggers a false defensive shift during it (chasing
  noise in an uptrend) would show up as a negative CAGR margin with no drawdown benefit in `h3y-2`/`h5y-2`.

## 6. The structural power of this round — measured on the regressor, before any outcome

**What was measured, and what was deliberately not.** Before authoring the field, the *support of each
condition* was computed against the live bar store, 2013-09-03 (the earliest window's start) through
`DESIGN_THROUGH` — how often each condition is true on its own sleeve's bars. This reads price only,
touches no return series, no card and no window's outcome, and `round43.py --write`/the plain dry run
re-measures it every time rather than freezing a screen computed once (see the tool's `support_table`
function). The figures below were measured 2026-09-09 and are re-verified in the tool's own dry-run
output:

| condition | on_symbol | fraction of sessions true |
|---|---|---|
| `close < sma(200)` | AGG | 44.6% |
| `close < sma(100)` | AGG | 45.7% |
| `close > sma(200)` | GLD | 61.2% |
| `close < sma(200)` | SPY (placebo) | 17.4% |

None of the four is near 0% or 100% — every condition is a genuine, frequently-alternating regime
split rather than a near-static allocation or a condition that can never fire. This is a materially
better-conditioned regressor than round 38's real-yield terms, several of which were 0% in individual
windows (`ROUND-38-PLAN.md` §6) — but a well-conditioned regressor is a **necessary**, not sufficient,
condition for a real effect, and §5's predictions are pre-registered assuming it will not be
sufficient here either.

**Eligible windows per horizon**, against `windows.py`'s `MIN_ELIGIBLE_R5_PER_HORIZON = 2`: because
`AGG`'s and `GLD`'s trend conditions cross regularly (44–61% support, not a rare event), every horizon
in the ladder is expected to clear the gate for every treatment card in this field — unlike round 38,
where the 2.0% real-yield threshold was structurally degenerate in several horizons. This is stated as
an expectation, re-verified once the harness actually runs; a horizon where a card fires zero or one
time will still be reported UNMEASURED rather than folded into the aggregate, exactly as round 38's
harness does.

**Why the SPY placebo's support (17.4%) is much lower than the AGG/GLD conditions' (45–61%), and why
that is not itself informative.** SPY trades below its 200-day mean far less often than AGG trades
below its own — equities trend up more persistently than a broad bond index chops around its mean.
This asymmetry in *how often each condition fires* is a fact about the two instruments' own price
behaviour, not about which one is the better regime signal, and no ranking claim in §9 rests on
comparing firing rates across sleeves.

## 7. Windows

**The R5 horizon ladder plus the bear supplement**, `strategy-program/tools/windows.py`:
`R5_LADDER_WINDOW_TAGS` (`h10y-1`, `h10y-2`, `h5y-1..3`, `h3y-1..4`) and `R5_BEAR_WINDOW_TAGS`
(`b6m-1..3`, `b1y-1..3`) — 15 windows, the identical set round 38 used, for the identical reason: a
$100,000 lump sum with a 10–20 year horizon is judged on multi-year compounding and drawdown, not on
the trading matrix's short regime slices.

**Ranking uses the 5y and 10y rungs; 3y and the bear windows are supplements**, exactly as round 38.
**`b6m-2` and `b1y-1` are additionally reported in their own hindsight-flagged table** (§8), per the
hindsight discussion in §5.

## 8. Evaluation procedure

**No `score.py` equivalent exists for `AllocationCard`s** (`ROUND-38-PLAN.md` §8's argument applies
unchanged — `score.py` is hard-typed to `AgentResult`). `strategy-program/tools/round43_run.py` is
round 38's harness, adapted:

- **No macro pin.** This round's conditions are price-only (`close`/`sma` on `AGG`, `GLD` and `SPY`);
  `INVDASH_MACRO_PIN` is never set and no card in this field contains a `macro(...)` term.
- `mandate = desk_mandate(Purpose.SAVINGS)`, called live, not reconstructed — identical to round 38.
- Per card, per window: `run_allocation(card, settings=settings, mandate=mandate, start=..., end=...)`.
  6 cards × 15 windows = **90 runs**, serial (the bar store is single-writer).
- Metrics per cell: CAGR, `max_drawdown` (from `app.backtest.metrics.compute`, never recomputed), MAR,
  volatility, sessions, trades — identical formulas to `round38_run.py`.
- **The benchmark is the 30/70 SPY/AGG blend** (`app.paperdesk.benchmarks.price_blend`), recomputed per
  window, never `AllocationResult.benchmark_return` (hard-coded to 100% SPY in
  `app.tournament.allocation` — reporting that as "the savings benchmark" would be the trap round 38's
  harness names).
- **Every reported figure is treatment minus `r43-control`, in the same window** — never
  treatment-versus-benchmark, and never treatment-versus-round-38's-placebo-result (that would be
  comparing across two different program runs of the identical card, which is not how a within-round
  comparison works; the comparison this round makes is `r43-price-placebo-spy` run *inside this round*,
  on this round's own windows and this round's own control).
- **A per-bear-window table labels `b6m-2` and `b1y-1` "2022 (in-sample to the hypothesis)"**,
  distinctly from `b6m-1`, `b6m-3`, `b1y-2`, `b1y-3`, per §5's hindsight discussion.
- **A pairwise line, "primary minus placebo"**, reports `r43-agg-trend-bil`'s drawdown and MAR margins
  minus `r43-price-placebo-spy`'s, on the rungs where both fired — the direct test of P2.
- Degenerate or unmeasured cells (fired in fewer than `MIN_ELIGIBLE_R5_PER_HORIZON = 2` windows of a
  horizon) are labelled `UNMEASURED` and excluded from the aggregate, exactly as round 38.

**Distributions are not modelled** (AGG/GLD/BIL pay distributions this harness does not simulate), so
every CAGR figure understates the real one; the drawdown column is the trustworthy half — the same
caveat round 38 and `ALLOCATION-FAMILY.md` carry.

## 9. Decision rule — pre-registered

**Nothing is promoted from a measurement round.** No card in this field is a candidate for the paper
desk, the library, or any tier, whatever it returns.

**Ranked on the max-drawdown margin** (treatment minus control, positive = shallower) as the primary
criterion and the **MAR margin** as the joint criterion, per the savings mandate. **CAGR margin is
reported, never ranked** — a card that improves CAGR and worsens drawdown has failed this book's
mandate regardless of return.

**The noise floor.** PROTOCOL.md §7's 21.2pp floor is **inherited conservatism, not load-bearing for
`AllocationCard`s**, exactly as `ROUND-38-PLAN.md` §9 states: it was measured on a `StrategyCard`'s
universe-ordering tiebreak, a mechanism an `AllocationCard` does not have (every sleeve is always held,
no slot contention to break). No equivalent floor has been measured for this card shape. This round
does not claim a sub-21.2pp margin is real on the grounds the floor does not apply to it — it states
every margin against the 21.2pp figure anyway, as the only reference point on record, while naming it
as an inherited and possibly-too-conservative one.

**Multiple comparisons.** Any correction uses a denominator of **6** — every card this round runs,
including the control.

**The verdicts:**

- **P1 holds, P2 holds (bond-sleeve trend does not beat the SPY placebo)** — the expected outcome.
  Reading the bond sleeve's own bars adds nothing over reading the equity sleeve's; both are
  small, inside-any-reasonable-floor de-risking effects at best. The corpus's bond-stress framing is
  measured-null as a mechanical rule on this book, joining round 38's real-yield result. No follow-up.
- **P1 falsified, P2 holds** — a real drawdown effect exists but the equity-sleeve read (already
  measured in round 38) captures it just as well or better; the bond-sleeve read earns nothing over
  what round 38 already reported.
- **P1 falsified, P2 falsified** — the bond sleeve's own trend beats the equity-sleeve placebo on
  drawdown, outside the floor, on rungs other than the 2022 bear windows. This would be the first
  evidence in this programme's savings line that a bond-sleeve read outperforms an equity-sleeve read.
  It still **promotes nothing** — it would justify one dedicated follow-up round with a genuine
  out-of-sample split, the same posture round 32 took to round 31's near-miss, and any margin
  concentrated in `b6m-2`/`b1y-1` must be discounted as hindsight per §5.
- **P3 falsified (sma100 and sma200 diverge materially)** — reported as evidence the rule is fitted to
  a particular window length rather than structural, regardless of which threshold shows the larger
  margin.
- **P4 falsified (GLD destination is not more volatile than BIL)** — reported as a genuine surprise
  about GLD's behaviour on these specific fired sessions, not evidence GLD is a defensive instrument in
  general.

## 10. Determinism, scope, and what this round cannot settle

- **Deterministic.** `build()` is pure — no clock, no randomness, no store access — asserted
  byte-identical across calls in `tests/test_round43_field.py`. `run_allocation` is deterministic and
  its slippage is always adverse.
- **`designed_through = DESIGN_THROUGH` (2026-02-13)** on every card, enforced by the model.
- **No macro pin, no release-lag question.** Every condition in this field is priced off daily OHLC
  bars already stored for AGG/GLD/SPY; there is no macro series, no `MissingPinError` path, and none
  of round 38's or round 21's release-lag or revision arguments apply here at all.
- **What this round cannot settle.** Six cards, one round, price-only conditions, no true
  out-of-sample split beyond the walk-forward the ladder already provides, and two of fifteen windows
  in-sample to the hypothesis by construction (§5, §8). A null here closes one more untested corner of
  the savings-tilt space; it does not and cannot rule out every possible bond-sleeve condition, only the
  four tested. Nothing here is investment advice.

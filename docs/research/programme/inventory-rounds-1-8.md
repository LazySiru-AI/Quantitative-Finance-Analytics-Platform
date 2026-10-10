# Evidence inventory — Strategy Programme rounds 1–8

**Purpose.** A read-only inventory feeding a consolidated "everything this programme has ever
tested" report. Covers rounds 1 through 8 only. Round 9 onward is out of scope except where a round
1–8 document's own forward-looking text is quoted for context (always labelled as such).

**Primary source.** `data/rounds/PROGRAMME-REPORT.md` (compiled 2026-08-22, §§1–14 and appendix),
cross-checked against `data/rounds/r1-2026-08/` through `r8-2026-08/` (`BRIEF.md`, `REPORT.md`,
`SELECTION.md`, memos, `NARRATIVE.json`), `strategy-program/PROTOCOL.md`, `CONSTRAINTS.md`,
`DEFECTS.md`, `ROUND-4-PLAN.md`, `ROUND-5-PLAN.md`, `ROUND-6-PLAN.md`, and
`backend/app/paper/library/retired/README.md`. Figures are attributed to the specific document and
section they came from; where documents disagree, both figures are given (see §9, the appendix).

**A note on the source material itself.** `PROGRAMME-REPORT.md` is unusually careful about
attribution and about not silently resolving disagreements between documents. This inventory follows
the same discipline rather than re-deriving numbers.

---

## 1. Round 1 — twenty-two strategies against five regimes

**Source:** `data/rounds/r1-2026-08/BRIEF.md`, `REPORT.md`.

**Question pre-registered.** Whether a new exposure-adjusted scoring metric and a regime-window
matrix would change the picture produced by a prior (flawed) tournament, testing six new
analyst-designed cards alongside sixteen inherited cards.

**Field.** 22 ranked/unranked cards plus 8 variants — 84 card-window runs. Six new cards, one per
"discipline" (mean-reversion, volatility, breakout, risk-managed, trend, 13F-derived momentum):
`c01-meanrev`, `c02-volatility`, `c03-breakout`, `c04-riskmanaged`, `c05-trend`,
`c06-13f-momentum`. Sixteen inherited cards: the `A` (pairs-rotation), `B` (momentum), `C` (trend),
`D` (13F-derived momentum), `E` (asymmetric/payoff-shape), `F` (fast mean-reversion), `G`
(volatility), `H` (cross-asset trend) families and their variants. Universe: 173 symbols with
readable daily bars, chosen freely per card (1–12 tickers, fixed for the run).

**Windows.** Five: `gfc` (2007-10-09→2009-03-09, SPY −56.23%), `covid` (2020-02-19→2020-06-30, SPY
−8.71%), `bear-2022` (2022-01-03→2022-10-12, SPY −25.14%), `bull-2024` (2024-08-21→2025-08-20, SPY
+14.00%), `recent` (2025-08-21→2026-08-18, SPY +20.62%), plus a special-case `13f-legal` window.
Gate: <3 of 5 → unranked.

**Result.** Top six by median adjusted excess: `B2-hold-90`, `B3-concentrated`, `G-volatility`,
`B-momentum`, `A2-cash-headroom`, `B4-tight-stop` (`REPORT.md` §2) — but the report itself flagged
the `B` family's best window (`covid`) as an artifact of structural absence during the crash, not
defence. Not one inherited legacy card (`A`/`B`/`C`/`D`/`H`) could run `gfc` (blocked by
insufficient universe history — AVGO 2009, NOW 2012, META, INDA). The five new challenger cards had
the five lowest cross-window spreads (IQR 1.70–4.50 vs incumbents' 8.85–47.38) but ranked worst on
median. `c04-riskmanaged` finished the 56% bear market up 1.38% on 43.8% capital deployed across 28
trades yet ranked 18th of 19, because median-only scoring cannot see the difference between a hedge
and an absence. Eight variant experiments were run; none cleared the noise floor — the pure
ordering-artifact control (`A1-alpha-order` vs `A-rotation`, universe array order only) itself
produced a **+6.47 point** gap, larger than five of the seven substantive comparisons.

**Verdict.** No formal promotion/retirement round yet (that begins round 2/round 4); this round
established the field and the scoring problems later rounds would fix. `c06-13f-momentum`'s universe
was initially scored on windows predating its 13F filing date — the same basket-lookahead defect the
prior tournament made — caught by a human reader and corrected before the report was finalised.

**Defects found.** D1 (`total_return` silently rebased to first session's close, flipping sign on
two card-window pairs) and D2 (`exposure` measures session presence, not capital at risk — a card
reporting 97.19% session exposure had 43.8% capital actually deployed), both found round 1, fixed
before round 2 (`REPORT.md` §6, `strategy-program/DEFECTS.md`).

**What it left open.** Whether the variant programme (take-profit, cash-headroom, tight-stop
attribution tests) could ever separate from noise; the B-family `covid` absence-as-defence pattern,
later generalised by round 4.

---

## 2. Round 2 — eight regimes, a metric that can see insurance, a promotion rule that cannot count

**Source:** `data/rounds/r2-2026-08/REPORT.md`.

**Question.** Does widening the window matrix to eight regimes (adding a genuine crash-quarter
window and two directionless "chop" windows) change the ranking, and does a dominance view (median +
worst + hit rate + Pareto frontier) fix the median-only metric's blindness to convex/hedge payoffs
round 1 exposed?

**Field.** 27 cards (22 carried forward, 5 new: `c07-chop` (mean-reversion/sideways specialist),
`c08-generalist` (broad mandate), `c09-convex` (volatility, convex payoff via TLT/GLD),
`c10-momentum`, `c11-breakout`); 170 card-window runs, 47 honest guard refusals.

**Windows.** Eight: `q4-2018`, `covid`, `bear-2022`, `chop-2015`, `chop-2011`, `bull-2024`, `recent`,
`gfc` — 1,729 sessions, mean benchmark return **−9.45%**, six of eight windows falling (figure
computed in `r4-2026-08/REPORT.md` §1 from round 2's matrix). Gate: <5 of 8 → unranked.

**Result.** The dominance view earned its place: `c09-convex` reached the Pareto frontier at 4th of
22 by Borda composite on 6.80–7.5% mean capital exposure, where median-only scoring would have
placed it 11th. But decomposing the GFC window found capital exposure correlates with adjusted
excess at **Pearson r = +0.797** in a falling market — the metric credits *more* exposure in a
crash, because the adjustment is a credit proportional to exposure against a negative benchmark; per
unit of capital deployed the ordering inverted (the two smallest books in GFC were the best per unit
at risk). The two new "chop" windows mostly re-measured variance the matrix already carried
(`chop-2011`/`bear-2022` at Spearman ρ = 0.732; the single most redundant *pair* in the whole matrix
was `q4-2018`/`bear-2022` at ρ = 0.734, not a chop pair at all). A signature-based screen intended to
pre-select future windows agreed with the measured redundancy on only 1 of 8 windows and would have
recommended keeping both chop windows as twins — the mistake the round made.

**Verdict.** Promoted to `candidates/`: `c07-chop`, `c09-convex`, `c10-momentum`, `c11-breakout`,
`c01-meanrev` (held at `candidates/`). D1 and D2 confirmed fixed (`max |total_return −
ending/starting| = 0.000000pp` across all 170 runs). D3 found: a concurrent reader colliding with
the tournament's write lock, mis-recorded as an honest per-card failure — cost round 2's first
attempt entirely: 135 card-runs, zero results, from a run whose driving shell loop survived
`taskkill /IM python.exe`.

**What it invalidated.** The two-consecutive-rounds promotion rule: because cards are frozen and
windows are fixed dates, re-running a round-1 card on a round-1 window recomputes the identical
number (verified bit-identical on 20 of 20 checked pairs) rather than sampling anything — a
promotion rule requiring "positive median in two consecutive rounds" therefore double-counts one
measurement unless the second round brings genuinely new windows. Applying the promotion rule
mechanically would have replaced `B-momentum` with `B2-hold-90` on margins of **+5.62 and +4.15
points** — both inside the ordering noise floor the same protocol document calls meaningless. No
such promotion was made; the rule was flagged for amendment.

**What it left open.** Round 2's own admission that ranking biases (exposure credit vs. worst-window
favouring small books) were "small in aggregate" (ρ = 0.922 between two ranking methods) but
"concentrated in single-window comparisons" foreshadowed round 4's finding that the whole matrix's
regime mix drives the ranking, not just single windows.

---

## 3. Round 3 — does a wider universe change the result?

**Source:** `data/rounds/r3-2026-08/BRIEF.md`, `REPORT.md`.

**Question.** The symbol store grew from 173 to 633 symbols (symbols reaching the GFC grew from 86
to 380). Does more choice produce a better field, and does a controlled re-cut of the two base
strategies onto the wider universe change their results?

**Field.** Ten cards: a controlled arm (`B-wide`, `C-wide` — byte-identical to `B-momentum`/`C-trend`
except universe) and six open-arm analyst cards (`c12-meanrev-wide` through
`c17-defensive-trend-wide`); 78 run files.

**Windows.** Same eight as round 2, unchanged (`BRIEF.md` §0: "Windows, scoring, the DSL... are
unchanged from round 2"). Gate: 5 of 8.

**Result.** **The controlled arm found no detectable effect from breadth.** `B-momentum`→`B-wide`:
−4.3 points; `C-trend`→`C-wide`: −0.8 points; `C-trend`→`c17-defensive-trend-wide` (same entry rule,
different universe): −9.0 points — every margin inside the 53.9-point / σ = 21.2 ordering noise
floor. The open arm's centre of mass was unchanged from round 2 (median of medians +5.7%→+6.2%) and
its best card was materially worse (+19.3% round 2 best vs. +10.4% here). The GFC's raw excess
figures were shown to be an artifact twice over: first, D2 in action — `c12-meanrev-wide` posted
+55.3% raw GFC excess on one trade at 0.6% capital exposure ("declined to attend," adjusts to
−0.5%); second, survivorship — `c15-volatility-wide` and `c14-riskmanaged-wide` survived the
exposure correction in GFC partly because a universe drawn from *today's* S&P 500 cannot contain
Lehman Brothers, Bear Stearns, Washington Mutual or Countrywide. `c15`'s own analyst had
pre-registered `gfc` as its predicted *worst* window on sound 2008-bank-balance-sheet reasoning; it
came back as the card's *best* window (+69.6% raw / +18.4% adjusted) — recorded as the project's
clearest survivorship demonstration, sharper because the prediction preceded the (wrong) result. The
round's one genuinely useful new card, `c14-riskmanaged-wide` (TLT/IEF/GLD/LQD), used no symbol added
by the universe expansion at all — reached the Pareto frontier on best worst-window (−1.0%) and best
hit rate (75%).

**Headline / combined-book finding** (computed on round 3's matrix, written up in
`strategy-program/ROUND-4-PLAN.md` §1): combining `B-momentum`, `C-trend` and `c14-riskmanaged-wide`
in equal thirds produced median excess **+15.4%**, worst window **−11.1%** (vs `C-trend` alone's
−22.9%), 75% hit rate across all eight windows, because `C-trend`/`c14` measured **ρ = +0.04**
(effectively uncorrelated) while `B-momentum`/`C-trend` measured **ρ = +0.57** (near-redundant).
Disclosed caveat: two-thirds of the "crisis" excess was non-participation (cash), not alpha.

**Verdict.** `c14-riskmanaged-wide` promoted to `candidates/` pending confirmation on new windows.
`B-wide`/`C-wide` "did their job" and were not carried forward as strategies. Several open-arm cards
(`c12`, `c15`, `c17`) were later retired (see round 4 trim, §4 below and retired/README.md).

**What a later round overturned — the central reversal of the programme.** Round 4 re-ran the
*identical, unchanged* cards on six new windows (mean benchmark +17.13%, bull-weighted, vs round 3's
−9.45% bear-weighted) and found the combined book does not replicate: it is beaten by `B-momentum`
alone on every axis (round 3's book: median +1.06%, worst −6.59%, hit 50%; `B-momentum` alone:
median +5.82%, worst +0.04%, hit 100% — `r4-2026-08/REPORT.md` §6). Mechanism: `C-trend`/`c14`'s
correlation flipped sign, ρ = +0.04 (round 3's windows) → ρ = **−0.554** (round 4's windows), the
same two frozen cards. Round 4's own heading: **"Round 3's conclusions were properties of round 3's
windows."**

---

## 4. Round 4 — which cards belong together, and a matrix that reverses everything

**Source:** `strategy-program/ROUND-4-PLAN.md`, `data/rounds/r4-2026-08/BRIEF.md`, `REPORT.md`.

**Question.** Shifted from "which card is best" to "which cards belong together," built on the
finding that live desks' actual holdings were far more correlated than their nominal universes
suggested (`C-trend`'s four positions: mean pairwise ρ = 0.765, one of the four — SOXX — a basket of
the other three; `ROUND-4-PLAN.md` §1). Set out to confirm/reject `B2-hold-90` and
`c14-riskmanaged-wide` on genuinely new windows, test four new cards' claimed diversification, and
score the combined book for the first time.

**Field.** 14 cards (10 returning, 4 new: `c18-meanrev`, `c19-volatility`, `c20-rotation`,
`c21-uncorrelated` — the latter two submitted specifically as uncorrelated diversifiers); 78 run
files plus a 25-run control arm re-testing the retired A family unchanged.

**Windows.** Six, **all new** — none used in rounds 1–3: `recovery-2009`, `taper-2013`, `oil-2014`,
`volmageddon-2018`, `inflation-2021`, `banks-2023`. Mean benchmark **+17.13%**, 2 of 6 falling. Gate:
4 of 6.

**Result.** The central reversal: round 3's combined book does not replicate; round 3's conclusions
were "properties of round 3's windows" (see §3 above). `B2-hold-90` was **not promoted** — lost to
its own base `B-momentum` on all three axes and was the only B-family card with a negative worst
window; the take-profit/max-hold-days axis had by now been tested three separate ways with no
version beating the base twice, and was recommended closed. `c14-riskmanaged-wide` was **not
confirmed as a standalone rankable card** (median swung +2.3%→−2.32%, worst window −1.0%→−19.78%,
rank Pareto frontier→13th of 14), but its correlation claim replicated and strengthened in the
opposite direction its round-3 evidence suggested (ρ to `C-trend`: +0.04→−0.554); it was kept as a
labelled hedging leg only, never scored on median again. **All four cards submitted specifically as
uncorrelated diversifiers failed that test**: `c20-rotation` and `c21-uncorrelated` were the *most*
correlated cards in the field with `B-momentum` (ρ = +0.917, +0.907), above even `C-trend`.
`c21`'s own memo had pre-registered the exact falsification condition ("if the realized number lands
well above 0.3 ... the correlation argument in this memo is wrong") and it was recorded as such. The
cause: analysts had measured *daily-return* correlation (0.36–0.41) while the scorer used
*window-level* correlation, dominated by equity beta rather than trade timing. Scoring the combined
book (new scorer capability, built this round per §2 item 1) found no combination beat its single
strongest leg on median; the one combination that "worked" (`B-momentum`+`c07-chop`) did so partly on
a spectator cell — one trade at 0.8% capital exposure in the one window `B` cannot run at all.

**Verdict.** `B2-hold-90` recommended retired (not promoted). `c14-riskmanaged-wide` retained as
hedge-leg-only, non-rankable. `c20-rotation`/`c21-uncorrelated` fail their own pre-registered claim.
The A family (5 cards) had been retired in `ROUND-4-PLAN.md` §3 with the stated reasoning: *"they
look acceptable on raw return because they are heavily invested in a rising market, and they lose
once that exposure is paid for."* An un-pre-registered control arm re-ran the five retired cards
unchanged on round 4's six windows:

| card | median adj. excess | worst | hit | mean exposure | would rank |
|---|---|---|---|---|---|
| `A-rotation` | +4.20% | +0.20% | 100% | 76.5% | 2nd of 19 |
| `A4-tight-stop` | +4.20% | +0.20% | 100% | 76.4% | 3rd |
| `A3-no-target` | +3.02% | −0.74% | 80% | 77.0% | 6th |
| `A2-cash-headroom` | +2.58% | −0.97% | 80% | 72.0% | 8th |
| `A1-alpha-order` | +0.40% | −6.50% | 60% | 76.5% | 12th |

`A-rotation` and `A4-tight-stop` finished ahead of `B-momentum` on Borda composite. **The specific
retirement claim was falsified**: at 76.5% mean exposure, `A-rotation` posted a positive median and
worst window and beat every surviving candidate, once the exposure correction was applied on a
bull-weighted matrix instead of a bear-weighted one. What survived: the A family really is the
highest-exposure book ever measured, it really did lose badly on a bear-weighted matrix, and the
four A variants really are dominated by their own base on both matrices — so their retirement stands
on separate grounds. The retirement log was amended with these figures (not edited silently), and
`A-rotation` was reinstated to `candidates/` as a "high-exposure comparator."

**What it left open.** The portfolio-scoring question was newly settled as answerable; whether any
combination *could* beat its best single leg remained open pending more candidates. `E-asymmetric`,
`F-fastrev`, `G-volatility` retired "as written" with explicit invitations to resubmit re-cut on the
now-380-symbol long-history universe.

---

## 5. Round 5 — the horizon ladder

**Source:** `strategy-program/ROUND-5-PLAN.md`, `data/rounds/r5-2026-08/REPORT.md`.

**Question.** Every window measured in rounds 1–4 was between 45 and 284 sessions long. Does the
ranking depend on how long the competition holds cards open — six months versus ten years —
separately from the regime-mix question round 4 had just answered? (`ROUND-5-PLAN.md` §1: "Nothing
has ever been measured over a multi-year hold.")

**Field.** 15 cards — round 4's 14 plus `A-rotation` reinstated by the control arm. No new
submissions: "Round 5 is a measurement study on a fixed field, not a submission round"
(`ROUND-5-PLAN.md` §4). 405 of 405 run files completed.

**Windows.** 27 total. **Arm A (the ladder, 21 windows):** evenly sampled across a common
2013-09-03→2026-02-13 period at five horizons — 6m ×6, 1y ×6, 3y ×4, 5y ×3, 10y ×2 (the two 10y
windows share 62% of their sessions and are explicitly *not* treated as independent). The benchmark
rises in 19 of the 21 ladder windows — no decade in the available data has a falling benchmark.
**Arm B (the bear supplement, 6 windows):** selected on a falling benchmark (e.g. `b6m-1`
2019-09-20→2020-03-23, SPY −25.3%), reported separately and never pooled into the ladder's medians —
"selected on the outcome variable... any card that looks good only in Arm B has demonstrated that it
is a hedge, not that it is a strategy" (`ROUND-5-PLAN.md` §2). Gate: 2 windows per horizon (Arm A).

**Result — the horizon finding.** "The best annualized figure in the field falls from **+31.6% at
one year to +7.6% at ten** — the same cards, the same engine, the same metric, the same calendar"
(`r5-2026-08/REPORT.md` §2.1). Per-horizon best-card figures: 6m +19.92%, 1y **+31.55%**, 3y +15.36%,
5y +15.12%, 10y **+7.59%**. `A-rotation` moved from rank 1 at 6m/1y to rank 5 at 10y. **The variant
experiments measure nothing at a long hold:** `B2-hold-90` differed from `B-momentum` by 11.8 points
at one year and was inside **0.45 points** of it (and of `B4-tight-stop`) at ten years — closing the
take-profit/max-hold axis this programme spent four cards and three rounds on. **The bear arm
identified the field's real hedges, inverting the ladder ranking:** `c20-rotation`, last of fifteen
at every ladder horizon, was first in the bear arm — a **+14.79-point** swing between the two arms,
"not a failed strategy but an unlabelled hedge." **The QQQ benchmark finding:** re-deriving every
ladder result against QQQ instead of SPY: "the ordering barely moves; the magnitudes roughly halve."
At ten years: `B-momentum` +7.59% (SPY)→**+3.9%** (QQQ); `A-rotation` +5.28%→**+0.6%**; `C-trend`
+4.45%→+1.3% — aggregate: +11.20%/yr SPY vs +15.76%/yr QQQ mean across the ladder (§3.1), stated as
a rough characterisation, not a uniform per-card multiplier.

**Caveat that limits everything above.** Every top card's universe was chosen by an analyst writing
in 2026, then run from 2013 — a decade over which knowing which semiconductor names to hold was
worth the most, and the programme's survivorship gate (`universe_knowable_from`) does not catch
thesis-picked baskets over a multi-year hold, only mechanically index-derived ones. Every long-rung
figure is stated as an upper bound for this reason (`REPORT.md` §4).

**Verdict.** No promotions/retirements — a measurement study, not a submission round. Feeds directly
into round 6.

**What round 5 explicitly could not settle** (`ROUND-5-PLAN.md` §5, quoted near-verbatim):
- "It is not out-of-sample. No calendar time has passed since round 3... The walk-forward begins when
  real time has elapsed."
- "The long rungs are nearly one sample" — two overlapping decades is not a distribution.
- "The era is one era." Every window is drawn from 2013–2026; a ten-year result is a result about
  *this* decade — "the 2000s or the 1970s would very likely rank the field differently."
- "Annualizing does not make a 6-month result as trustworthy as a ten-year one. It makes them the
  same units." A 6-month figure has roughly twenty times the sampling error of the decade's.

---

## 6. Round 6 — four cards for the paper desk

**Source:** `strategy-program/ROUND-6-PLAN.md`, `data/rounds/r6-2026-08/SELECTION.md`.

**Question.** Which four cards should trade forward, live, on the paper desk — a different kind of
decision because the desk holds indefinitely, runs four cards as a book, and is observed rather than
scored. The selection rule was pre-registered *before* round 5's results existed.

**Evidence read, not a new backtest window:** rounds 2, 4, 5 (ladder + bear arms), plus the
already-running live desk.

**The rule (four slots, one card per slot):** Slot 1 — core, best worst-rank across the r2/r4/r5-
ladder matrices. Slot 2 — horizon anchor, best median annualized adjusted excess over the 5y/10y
rungs (exposure ≥ 5%). Slot 3 — diversifier, lowest maximum per-window correlation to slots 1&2
across r4 and r5-bear (exposure floor + performance floor, to stop a mostly-cash book winning by
default). Slot 4 — declared hedge, best worst-window across r5-bear and r2's four falling windows
(explicitly expected to lose money in a rising market). A book-check veto: if the four-card book has
a worse worst-window than slot 1 alone on more than one matrix, the selection is rejected and
re-drawn.

**Amendments made before execution, logged not folded in** (`ROUND-6-PLAN.md` §7): Gate A collapsed
slots 1&2 into a single admission gate — positive median annualized adjusted excess at both 5y and
10y, against **both** SPY and QQQ — because round 5 showed a short-window criterion selects on the
noisiest rung and the QQQ requirement roughly halves `A-rotation`'s decade edge (+5.28%→+0.63%). Gate
B added a hard correlation cap of ρ ≤ +0.70 between any two desk cards, forced by the live desk
already holding `B-momentum` and `C-trend` at ρ = +0.909 (same rotation twice).

**Result.** `B-momentum` (core), `A-rotation` (second engine, ρ = +0.497 to core), `c07-chop`
(diversifier, ρ = −0.283 to `A-rotation`), `c14-riskmanaged-wide` (hedge, only candidate clearing
both the correlation cap and the exposure floor). `C-trend` dropped from the incumbent desk. Book
check passed (veto count 1, fires above 1).

**What it exposed.** The card with the strongest hedge signature in the entire programme,
`c20-rotation` (+14.8-point bear/ladder swing, three times the next card's), was excluded on a single
raw correlation number, ρ = +0.917 to `B-momentum` — flagged by the same document as suspect, since
the pair reads ρ = **−0.591** on the annualized bear arm. The rule was applied as written; flagged
for round 7. **The live desk — the programme's only out-of-sample evidence at the time —
contradicted every backtest conclusion above.** Over 55 live sessions (2026-06-01→2026-08-18, SPY
+1.17%, QQQ −3.40%), the ladder's rank-1 short-horizon winner (`A-rotation`) was last of ten live at
**−12.77%**, and the ladder's 8th-of-10 card (`c18-meanrev`) was the only one making money live, at
+2.44%. **Spearman between round 5's ladder ranking and the live ranking: −0.539** (`SELECTION.md`
§6) — later withdrawn in round 7, see §7 below. Two of the four selected cards (`c07-chop`,
`c14-riskmanaged-wide`) took **zero trades** in 55 live sessions and sat at 100% cash — the exposure
floor that qualified them was measured on historical windows, not on the regime the desk was about
to trade — logged as a defect for round 7.

**What round 6 stated it could not settle** (`ROUND-6-PLAN.md` §6): "It is still not out-of-sample";
"Four cards from a field of fifteen, chosen on four matrices, is a small selection from a small
sample"; "The desk's own result will be one path... it will be tempting to read it as a verdict on
this rule. It is not one"; "Nothing here is a claim about what anyone should own."

---

## 7. Round 7 — re-selection under the live-evidence gates

**Source:** `data/rounds/r7-2026-08/SELECTION.md`.

**Question.** Apply the four fixes round 6 pre-registered for itself: a liveness gate, a
holdings-overlap cap alongside the return-correlation cap, re-specifying correlation on annualized
figures only, and scoring the live desk as its own matrix once it has enough sessions.

**Result.** Fix 1 (liveness gate) removed `c07-chop` and `c14-riskmanaged-wide` outright — both had
taken zero trades in the 60 sessions before selection. Fix 2 (holdings-overlap cap, ≤25% shared book
weight) was the round's real finding: every pair among the six equity-family books breached it,
including `B-momentum`/`A-rotation` at only ρ = +0.497 (well under Gate B's cap) but **45% shared
holdings weight** (same NVDA/AVGO/TSM names). After the cap, `H-trend-diversified` was the only card
that could sit beside *any* equity book — capping the desk at two performance seats as a consequence,
not a design choice. Fix 3 (annualized-only correlation) vindicated round 6's flag on
`c20-rotation`: its correlation to `B-momentum` measured **−0.054** annualized-only vs **+0.917**
raw-inclusive — the same two frozen cards; `c20-rotation` took the hedge seat. Fix 4 (score the live
desk as its own matrix) **could not be applied** — 55 sessions is far too few, and doing so "would
give a single quarter's rotation more weight than every backtest combined"; deferred to ~250
sessions, roughly mid-2027.

**Verdict.** `B-momentum` and `H-trend-diversified` (performance seats), `c20-rotation` and
`c11-breakout` (hedge seats). Dropped: `A-rotation`, `c07-chop`, `c14-riskmanaged-wide`.

**§9's self-correction — the finding this document is most notable for.** The desk was backdated
from 2026-06-01 to 2026-01-01, exposing the 55-session window used throughout the rest of the
document as an unrepresentative slice. Section 9 corrects two claims: "Spearman: round 5's ladder
rank vs forward result — on the 55-session slice (§6, as reported): **−0.539**. On the full
127-session out-of-sample period, raw return: **+0.625**. Same, on adjusted excess: **+0.536**."
**The sign flips.** The document's own words: *"The claim in §6 — 'the backtests ordered this field
roughly backwards over the only period no analyst could have studied' — was true of the slice I
measured and false of the period it was meant to describe. It is withdrawn."* Over the genuine
127-session out-of-sample window (2026-02-17→2026-08-18, SPY +12.84%, QQQ +19.20%), the five cards
round 5's ladder ranked highest were the five that finished highest out of sample, led by
`B3-concentrated` at +51.63% raw / +39.91% adjusted vs QQQ.

Section 9 also disclosed round 7's own selection **underperformed out-of-sample**: round 7's four
returned +8.76% against round 6's four at +17.39% and SPY at +12.84% — the holdings-overlap cap's
foreseeable cost, removing `A-rotation` (+37.36% out of sample) in favour of `H-trend-diversified`
(−3.14%). The methodological lesson, recorded as the author's own: *"I computed a rank correlation on
55 sessions and reported its sign as a finding... A forward window shorter than roughly one full
cycle should be reported as an observation and never as a correlation"* (§9.4).

**What it invalidated.** Its own §6 finding (see above — explicitly withdrawn, not silently
corrected). **What it left open.** Fix 4 (live-desk-as-matrix), deferred to round 9+ territory (not
resolved until round 11, out of this inventory's scope).

---

## 8. Round 8 — re-selection under the reference-signal rule

**Source:** `data/rounds/r8-2026-08/SELECTION.md`.

**Question.** Rounds 6 and 7 selected the desk's four cards as if they were one combined portfolio
(pairwise return-correlation cap + holdings-overlap cap). Round 7's own §9.2 priced that premise: the
overlap cap cost roughly nine points against round 6's roster and four against holding SPY over the
only out-of-sample window available. Round 8 retires the "one combined portfolio" premise itself.

**Result.** The correlation cap, the holdings-overlap cap and the book veto were **retired outright,
not amended** — the desk owner reads each of the four cards as an **independent reference signal**
for what to buy in a single real account; "nobody holds all four at once; they do not need to be
uncorrelated with each other, and there is nothing to veto." In their place: at most one card per
`StrategyCard.discipline` and at most one per base family (distinctness of *idea*, not of *return*),
plus two carried-over gates: Gate A (positive median annualized adjusted excess at both 5y/10y, both
SPY and QQQ) and Gate L (at least one trade in the 127-session out-of-sample window). Ranking among
survivors: **out-of-sample adjusted excess vs QQQ** — "the only genuinely out-of-sample evidence the
programme has." Eight cards cleared both gates (the same eight round 6 found), spanning exactly four
distinctness groups, so ranking determined the roster without further tie-break.

**Verdict.** `B-momentum` (momentum family, see override below), `A-rotation` (pairs-rotation,
+24.28% adj. vs QQQ — "the card round 7's overlap cap dropped; the correction stands"), `c07-chop`
(mean-reversion, only candidate in that discipline to clear Gate A despite −0.77% adj. vs QQQ),
`H-trend-diversified` (trend, beating `C-trend`'s −6.02% with −5.49%).

**§6 — the owner override, recorded as an override rather than folded into the rule.** Applying
round 8's own rule as written selects `B3-concentrated` for the momentum seat (+51.63% raw / +39.83%
adjusted vs QQQ out of sample, against `B-momentum`'s +31.97% / +20.98%). **The desk's owner seated
`B-momentum` instead**, on the evidence it has never been worse than third across three different
historical matrices (ranks 3/2/2 on r2/r4/r5-ladder) and posts the better 10-year figure against both
benchmarks (+7.59%/+3.92% vs `B3`'s +5.78%/+1.90%). The document's own framing: *"Both readings are
supported by the programme's own numbers, and neither is obviously wrong... It is written up as an
override rather than folded into the rule. A selection rule quietly restated to produce the answer
someone wanted is not a rule."*

**A benchmark-anchoring artifact, found and explained rather than corrected as an error.** Round 8's
recomputed SPY figures for the same cards differ from round 6's published figures by up to 0.124
annualized points; the out-of-sample SPY/QQQ figures for the identical 2026-02-17→2026-08-18 window
differ across round 7's and round 8's own documents (SPY +12.84% vs +12.39%; QQQ +19.20% vs +19.33%)
because the engine's `benchmark_return` is measured over sessions actually traded while a
calendar-date recomputation is not — "one benchmark measured two defensible ways," a reprise of an
effect round 5's report had already documented (up to 0.85 points across 21 windows).

**What it left open** (round 8's own closing list): Fix 4 (live-desk-as-matrix) closer but still
deferred; whether `discipline` is the right distinctness axis is unresolved, with `C-trend` vs.
`H-trend-diversified` named as the specific case it may be getting wrong; every SPY figure crossing a
round boundary should state its anchor.

---

## 9. Cross-cutting: the defects log (D1–D4), touching rounds 1–4

Source: `strategy-program/DEFECTS.md`, consolidated in `PROGRAMME-REPORT.md` §11.

- **D1** — `total_return` rebased to first session's close, not starting equity. Found round 1, fixed
  before round 2. 14 card-window pairs in round 1 differed from the true figure by >0.05pp; **two
  changed sign** (e.g. `A-rotation` in `covid`: reported −0.652%, true +0.465%).
- **D2** — `exposure` measured session presence, not capital at risk. Found round 1, fixed before
  round 2 (added `capital_exposure` as a separate field). `c04-riskmanaged`'s naive GFC adjusted
  excess was +55.45% against a corrected +25.45%; `c03-breakout`'s GFC figure changed sign, +13.43%→
  −1.71%.
- **D3** — a concurrent DuckDB reader mis-recorded as an ordinary card failure. Found during round 1
  setup, recurred in round 2's own setup and cost 135 card-runs / zero results. `run_round.sh` now
  refuses to start while another tournament process is alive.
- **D4** — indicator values depended on an arbitrary 400-day lookback that could flip a signal. Found
  2026-08-21 while attempting a performance optimisation, not by reading the code — a tiny (~1.8e-5
  relative error) seeding error for recursive indicators (`ema`, Wilder `rsi`). All 330 committed
  round 1–3 run files were re-run; exactly 3 of 330 results moved (all `C-trend` in `covid`, present
  in all three rounds), by 0.065 percentage points. No ranking, promotion, Pareto frontier or
  conclusion in any of the three round reports changed.

---

## 10. Strategy ideas tested, named explicitly (A-to-Z of concepts)

Every distinct strategy *concept* rounds 1–8 put through the engine, named by idea rather than card
id. Card ids are given for traceability.

1. **Pairs-rotation / high-exposure momentum rotation** — `A-rotation` and its four attribution
   variants (`A1-alpha-order`: universe ordering only; `A2-cash-headroom`: capital reserve; `A3-no-
   target`: no take-profit; `A4-tight-stop`: tighter stop). Retired round 4 on a bear-weighted
   matrix, control-arm-vindicated on a bull-weighted one, reinstated round 6.
2. **Momentum (base "B" family)** — `B-momentum`, incumbent core strategy. Variant axis tested three
   separate ways across three rounds: hold-period extension (`B2-hold-90`), position concentration
   (`B3-concentrated`), tighter stop (`B4-tight-stop`), and take-profit target (`B1-with-target`).
   Take-profit/max-hold axis formally closed round 4/5 — no variant ever beat the base twice, and
   differences collapse to <0.5pp at a 10-year hold.
3. **Trend-following on the equity/semiconductor complex ("C" family)** — `C-trend`, moving-average-
   break entry (per `c05-trend`'s thesis: `sma(200)` break as a mechanically-watched level triggering
   correlated follow-on flow). Concentration finding: mean pairwise ρ = 0.765 across its four
   holdings, one of which (SOXX) is a basket of the other three.
4. **Cross-asset trend, applied off the equity complex** — `H-trend-diversified`, same trend
   mechanism run independently across equity, rate and gold exposures so the three signals are not
   forced to fire together. Never resolved against `C-trend` on the distinctness question (open as of
   round 8).
5. **13F institutional-momentum, filing-derived universe** — `c06-13f-momentum` (round 1) and
   `D-13f-newbuys` (inherited). Provenance-constrained: legal only in the single `13f-legal` window;
   `D-13f-newbuys` could not clear even that window (universe symbol lacked sufficient history) and
   was retired after two consecutive zero-trade rounds.
6. **Mean-reversion (fast)** — `c01-meanrev` (round 1), `F-fastrev` (inherited, retired for
   eligibility). Retired round 4, near-zero and dominated.
7. **Mean-reversion, sideways/chop specialist** — `c07-chop` (round 2). Best median of non-B
   candidates in its debut round; later found to trade almost never live (100% cash for 92+
   sessions), removed from the desk round 7 for zero live trades.
8. **Volatility, convex payoff** — `c09-convex` (round 2), designed explicitly to test whether the
   dominance/Pareto view was worth adding; holds TLT/GLD at low exposure (0.08). Never confirmed
   safe by any tested stop mechanism — zero of 69 trades ever exited via `stop`.
9. **Volatility, non-convex ("squeeze"/breakout-adjacent)** — `c02-volatility` (round 1),
   `c19-volatility` (round 4), `G-volatility` (inherited). `G-volatility` posted the single most
   "genuinely promising, genuinely unrankable" figure of round 1 (+12.6% median across 3 windows) but
   failed the eligibility gate; retired with an explicit invitation to resubmit on the wider
   universe.
10. **Breakout** — `c03-breakout` (round 1), `c11-breakout` (round 2), `c13-breakout-wide` (round 3).
    `c11-breakout`'s round-2 headline (+23.89pp beat of SPY in bear-2022) was later read as absence,
    not defence, on one trade.
11. **Risk-managed / defensive multi-asset basket** — `c04-riskmanaged` (round 1, TLT/IEF/GLD/LQD
    concept), `c14-riskmanaged-wide` (round 3, same four names, already in the pre-expansion store).
    `c14` is the programme's clearest case study in a card's status changing with the window matrix:
    Pareto frontier (round 3) → 13th of 14 and correlation sign flip (round 4) → labelled hedge-only,
    never rankable again → excluded from the desk on the liveness gate (round 7, zero live trades).
12. **Concentrated vs. diversified universe / breadth** — the round-3 universe expansion (173→633
    symbols) tested via a controlled arm (`B-wide`, `C-wide` byte-identical except universe) and an
    open arm (`c12`–`c17`); found no detectable breadth effect (every margin inside the 53.9-point
    noise floor). A second, distinct breadth test — one name per sector, deliberately low pairwise
    correlation (`c16-dispersion-wide`, ρ = 0.245) — also failed: 7th of 10, worse than the
    concentrated risk-managed basket. Explicit finding: "diversifying *inside* a card did not work."
13. **Combined-book / multi-card portfolio scoring** — first attempted by hand (round 3's B+C+c14
    thirds), formalised as a scorer capability in round 4. Central finding: no combination ever beat
    its single strongest leg on median; the one combination that "worked" did so on a spectator cell.
14. **Uncorrelated diversifier, purpose-built** — `c20-rotation` and `c21-uncorrelated` (round 4),
    submitted specifically to test whether a card could be designed to diversify `B-momentum`. Both
    failed on window-level correlation (ρ = +0.917, +0.907) despite low daily-return correlation
    (0.36–0.41) — the clearest pre-registered-and-falsified claim in the programme (`c21`'s own memo
    named the falsification threshold in advance). `c20-rotation` was later shown (round 5's bear
    arm) to have the strongest hedge signature in the entire programme by a different measure
    (+14.79-point bear/ladder swing), an apparent contradiction resolved in round 7 by re-specifying
    correlation on annualized-only figures (ρ becomes −0.054/−0.591).
15. **13F-derived momentum, "newbuys" variant** — `D-13f-newbuys`, inherited; unreproducible: the
    prior tournament's +56.93%-vs-+11.99% headline could not be re-run because the universe's binding
    symbol lacks sufficient history in the current store.
16. **Asymmetric/convex payoff-shape strategy** — `E-asymmetric`, inherited; eligible in only 1 of 8
    windows (+21.21% on `recent` alone), retired for eligibility, invited back re-cut.
17. **Generalist / broad-mandate** — `c08-generalist` (round 2); highest capital exposure in its
    field (0.59) yet negative median — retired.
18. **Tactical drawdown-ladder allocation (SCHD/QLD/IEF three-sleeve rule)** — `ladder-qld-schd`,
    tested outside the `StrategyCard` tournament entirely by a dedicated backtester
    (`strategy-program/tools/drawdown_ladder.py`; see `strategy-program/DRAWDOWN-LADDER.md`). As
    originally specified (no bounce confirmation, no reserve sleeve, no exit condition on continued
    decline), it produced a **−72.7% max drawdown** through 2006-06→2011-10 — worse than a static
    60/40 blend (−69.5%) and worse than SPY buy-and-hold (−56.5%) — because it has no de-risking
    trigger besides a new all-time high, which was over four years away in 2008. Fixes tested: time
    stops (actively hurt — turned crisis CAGR negative by selling at the bottom); larger tranche
    sizes (scored better but explicitly **not adopted**, diagnosed as "more QLD did better in a
    period where QLD did well" rather than a genuine fix); bounce confirmation (close back above
    50-session average before a rung fires — nearly tripled crisis MAR, 0.06→0.17); a genuine reserve
    sleeve (IEF, funded before SCHD — took crisis MAR to 0.25 at 40% reserve weight). Final tested
    version: CAGR +13.70%, max drawdown −55.0%, MAR 0.25 over the same window — still worse than QLD
    buy-and-hold on both return (13.95% vs 24.50% over 20 years) and MAR (0.25 vs 0.29); this is a
    deliberate return-for-drawdown trade, tested only on two crises in twenty years, entirely
    in-sample.
19. **Buy-and-hold benchmark** — SPY and (from round 5 onward) QQQ, used throughout as the scoring
    benchmark rather than as a competing card; QQQ was tested as an *alternative* benchmark in round
    5 specifically because SPY was judged "the flattering choice for a field of AI/semiconductor
    books," and roughly halves every top card's apparent long-horizon edge.
20. **Ordering-as-a-variable (control)** — a pure methodological test, not a strategy: the identical
    `A-rotation` card re-run under twelve different universe array orderings, establishing the
    programme's **±21.2-point noise floor** (53.9-point spread) that every subsequent promotion
    decision is checked against.

---

## 11. Ideas raised and explicitly NOT tested, with reasons (verbatim where available)

This is the section the task marks as most valuable. Round documents in this programme are unusually
candid about scope limits — both engine-level (things the DSL/backtester structurally cannot
express) and round-level (things a specific round declined to measure). Quoted verbatim where the
source uses first-person or declarative language; paraphrased with page reference otherwise.

### Engine-level: things no card in rounds 1–8 could express, at all

From `data/rounds/r1-2026-08/BRIEF.md` §7 and `strategy-program/CONSTRAINTS.md`:

> "Not expressible at all, so do not plan around them: ADX, stochastics, Ichimoku, volume-profile,
> Fibonacci levels, cross-sectional ranking, per-symbol volatility-scaled position sizing,
> multi-timeframe confluence." (`r1-2026-08/BRIEF.md` §7; restated in `CONSTRAINTS.md` with `vwap()`
> added as "registered for intraday intervals only and fails on daily bars.")

- **No cross-sectional comparison — "buy the strongest of these" cannot be expressed.**
  (`BRIEF.md` §3: "the engine has no cross-sectional comparison — you cannot express 'buy the
  strongest of these.'") When more symbols qualify than there are slots, the broker fills in
  universe-array order — an arbitrary tiebreak, not a relative-strength mechanism. Later measured
  (`CONSTRAINTS.md`): the one time relative-strength ordering (`rank_by`) *was* tried against random
  orderings of the same card, it ranked "9th of 10 — better than the alphabet, and inside the
  noise."
- **No cross-symbol regime gates — a rule cannot reference a second symbol's bars.** From
  `r1-2026-08/memos/c02-volatility.md`, an analyst's own record of an abandoned attempt to gate a
  tradeable name's entry on `^VIX`: *"What I could express: a rule that trades `^VIX` itself using
  its own close (not useful, since it isn't a position you can actually hold). What I could not
  express: 'buy SPY when `^VIX` is elevated' or any other cross-symbol regime gate as a single DSL
  rule — there is no mechanism in the grammar to reference a second symbol's bars from within one
  symbol's rule."* Confirmed against the engine's node types (`PriceRef`, `IndicatorRef`, `Arith`,
  `Comparison`, `Cross`, `Not`, `BoolOp`) — each resolves against a single bars frame. The analyst
  substituted intrinsic (same-symbol) ATR comparison instead.
- **Band-width contraction relative to its own history (a literal Bollinger "squeeze")** — same memo:
  "not expressible. `sma()`/`ema()` take an integer [period, not another indicator's output]."
- **Per-symbol volatility-scaled position/stop sizing.** From `r1-2026-08/memos/c05-trend.md`: "I
  have no mechanism available (per-symbol volatility-scaled sizing is explicitly not expressible in
  this DSL) to size the stop or the position to the asset actually held" — flagged by the analyst as
  the "weakest assumption" of a three-asset (SPY/TLT/GLD) trend card applying one fixed stop and one
  fixed position size across assets of different volatility character.
- **Shorting, options, and leverage beyond a leveraged-ETF's own decay.**
  `strategy-program/CONSTRAINTS.md`: *"Long only. No shorts, no options, no leverage beyond holding a
  leveraged ETF and accepting its decay."* Consequence noted independently in
  `r1-2026-08/analysis/bear-2022.md`: three long-only cards analysed there "cannot express a short
  view, so 'handling' a down-only [regime] means minimizing exposure, not profiting from it."
- **13F option/derivative positions.** `CONSTRAINTS.md`: "§13(f) covers US-listed equities only, and
  puts and calls appear as separate lines. Scion's four largest disclosed holdings — 95% of that book
  — are option lines. A long copy of that book takes the opposite of the trade." No 13F-derived card
  in rounds 1–8 could therefore faithfully replicate an options-heavy institutional filer's actual
  position.
- **A universe that rotates mid-window.** `BRIEF.md` §3: "the engine cannot rotate a universe
  mid-window" — every card's universe is fixed for the entire run, which is the direct cause of the
  eligibility gate and the GFC-ineligibility of every AI/semiconductor-era universe.
- **No dividends anywhere**, for benchmark or strategy. `BRIEF.md` §9: "This flatters every strategy
  against a real buy-and-hold investor by roughly 2 points a year" — never corrected for in rounds
  1–8's reported figures.
- **Intraday stop realism.** Stops are checked against the *previous close*, not the session's
  intraday low, because "the decision-maker cannot see the session's low." Cited concretely: "one
  prior card's worst trade lost 19.9% against a 12% stop." Not a defect — a deliberately conservative
  model — but it means no card's reported stop-loss discipline was ever tested against intraday
  realism.

### Round-level: things a specific round declined to measure, and why

- **Round 1** priced but never resolved whether a fill-order tiebreak amounts to a hidden strategy
  choice; it measured only that the ordering-artifact control (`A1-alpha-order`) itself produced a
  gap larger than most substantive comparisons, and left the question of a principled tiebreak open
  (later partially answered by the `rank_by` experiment cited above).
- **Round 2**: the signature-based window-redundancy screen was tested as a *candidate future
  pre-selection tool*, not adopted — it agreed with measured redundancy on only 1 of 8 windows and
  "would have recommended keeping both chop windows as if they were twins — precisely the mistake the
  round made." No round after round 2 used a signature-based screen for window selection.
- **Round 5's own §5, "What round 5 cannot settle,"** verbatim in part:
  - *"It is not out-of-sample. No calendar time has passed since round 3, the design cutoff has not
    moved, and every window here ends on or before 2026-02-13. The ladder brings windows the cards
    have not seen; it does not bring data the analysts could not have studied. The walk-forward
    begins when real time has elapsed."*
  - *"The long rungs are nearly one sample."* Two overlapping decades were explicitly not treated as
    two independent draws.
  - *"The era is one era. Every window is drawn from 2013–2026... the 2000s or the 1970s would very
    likely rank the field differently."* No pre-2013 data was used anywhere in rounds 1–8 (the store
    reaches back to 2004 for some symbols by round 3, but round 5's ladder specifically bounds itself
    to 2013–2026 for the common-period constraint).
  - *"Annualizing does not make a 6-month result as trustworthy as a ten-year one. It makes them the
    same units."*
- **Round 6's own §6, "What round 6 cannot settle, stated in advance"** (a genuine pre-registration,
  written before the selection ran):
  - *"It is still not out-of-sample... The selection is the best available retrospective choice; the
    desk is what turns it into a forward test, and that test has not started yet."*
  - *"Four cards from a field of fifteen, chosen on four matrices, is a small selection from a small
    sample. The rule is designed to be robust rather than optimal, and a robust rule on thin evidence
    is still a rule on thin evidence."*
  - *"The desk's own result will be one path... it will be tempting to read it as a verdict on this
    rule. It is not one, and this paragraph exists to be quoted back when someone does."*
  - *"Nothing here is a claim about what anyone should own. These are simulated books on a paper
    account, selected to be informative to watch, not to be held."*
  - Round 6 also explicitly deferred "fix 4" — scoring the live desk's own record as its own matrix —
    stating 55 sessions was far too few and that doing so prematurely "would give a single quarter's
    rotation more weight than every backtest combined." (Round 7 restates and further defers this to
    ~250 sessions, "roughly mid-2027"; it is not resolved within rounds 1–8.)
- **Round 7's own §9.4**, on why a 55-session live slice's rank correlation was withdrawn rather than
  kept as a caveated finding: *"A forward window shorter than roughly one full cycle should be
  reported as an observation and never as a correlation."* This is a standing methodological
  refusal — the programme declined, after round 7, to treat any sub-cycle live window as evidence of
  a correlation, only as an anecdote.
- **`c06-13f-momentum`'s own report** (round 1, restated round 2): the card's three pre-registered
  failure regimes (a rotation away from mega-cap tech; a sharp AI/semiconductor drawdown; prolonged
  sideways chop) were named in advance but **none occurred** in the card's one legitimate window —
  "the honest read is that the card was not tested against any of its own named risks; it got a
  favorable regime on its one legitimate look, which validates nothing about how it would behave in
  the regime it fears." The card's three-year-plus figures against pre-filing windows are shown but
  explicitly "not a measurement of this strategy... reported here only because the assignment asks
  for them to be shown, labeled, not scored."
- **`c09-convex`'s own report** (round 2): its 10% stop-loss was never actually triggered across 69
  trades in any window — "there is consequently nothing to quantify against the brief's previous-
  close stop-fill gap... the 10% stop was, as the memo disclosed up front, never tested by this
  history rather than confirmed safe by it."
- **The A-family retirement reasoning (round 4)** was itself an example of an untested-generalisation
  claim later caught: the original retirement stated a structural failure ("they lose once that
  exposure is paid for") without ever testing it against a bull-weighted matrix — round 4's control
  arm was the first time that counterfactual was actually run, and it falsified the unconditional
  version of the claim.
- **Programme-wide, never done in rounds 1–8:** no round scored the live paper desk's own trading
  record as an independent evidence matrix (fix 4, deferred through round 8, not implemented until
  round 11 — outside this inventory's scope); no round tested a pre-2013 backtest window at any
  horizon longer than the round-2/3/4 short windows already covered pre-2013 dates individually (the
  systematic multi-year *ladder* never reaches earlier than 2013-09-03); no round tested any
  strategy shape involving shorting, options, or leverage beyond a leveraged ETF; and no round
  resolved whether `StrategyCard.discipline` is the correct axis for judging two strategies
  "distinct" (flagged open at the close of round 8, naming `C-trend` vs `H-trend-diversified`
  specifically as the case it may be getting wrong).

---

## 12. Figures the programme itself documents as stated inconsistently (attribution required)

Per `PROGRAMME-REPORT.md`'s appendix — reproduced here because any consolidated report drawing on
rounds 1–8 risks repeating one of these without attribution:

1. **`c06-13f-momentum`'s one legal-window adjusted excess.** Round 1 (`r1-2026-08/REPORT.md` §5):
   "+3.19 points raw, **+11.03 adjusted**, on 56 trades at **46.3%** capital exposure." Round 2
   (`r2-2026-08/REPORT.md` §7): "+3.19 raw, **+10.99 adjusted**, 56 trades at **46.6%** capital
   exposure," introduced as "the same number round 1 produced," which it is not. Resolved by
   `PROGRAMME-REPORT.md` 2026-08-22: the two run files are byte-identical (188 sessions, +17.7865%
   return, 56 trades, +14.5961% benchmark, capital exposure 0.4656969840 exactly); round 2's
   +10.99 is the arithmetically correct figure (`17.7865 − 0.4657×14.5961`), round 1's +11.03 used a
   rounded 46.3% exposure input. Round 1's figure should be read as superseded — nothing else in
   either round depends on it.
2. **Round 5/10-year and 5-year adjusted-excess figures for the Gate-A survivors, between round 6 and
   round 8.** Round 6 (`r6-2026-08/SELECTION.md` §1): `B-momentum` 5y-SPY +14.79%. Round 8
   (`r8-2026-08/SELECTION.md` §1, recomputed "not copied from any prior round's document"): same cell
   +14.87%. `B4-tight-stop` 5y-SPY: round 6 +15.04% vs round 8 +15.12%. Round 8 itself attributes
   this to session-traded vs. calendar-date SPY pricing (max 0.124-point difference) and states every
   QQQ figure between the two rounds matches exactly.
3. **The 2026-02-17→2026-08-18 out-of-sample benchmark returns, round 7 vs round 8.** Round 7
   (`r7-2026-08/SELECTION.md` §9.1): SPY +12.84%, QQQ +19.20%. Round 8 (`r8-2026-08/SELECTION.md`
   §2, re-running fresh rather than reading round 7's figures): SPY +12.39%, QQQ +19.33%, plus a
   third value (SPY +12.57%) anchoring the same window to 2026-02-13 instead of 2026-02-17. Round 8's
   own text: "That is not a data change... it is three anchors for one period. Each is defensible;
   none is a revision of another." Downstream per-card figures differ accordingly, e.g. `B-momentum`
   adj. vs SPY: +24.67% (r7) vs +24.93% (r8); adj. vs QQQ: +21.06% (r7) vs +20.98% (r8).
4. **The Spearman correlation between backtest rank and live/forward result, within round 7 itself.**
   Reported first (round 6 §6, restated at the top of round 7) as **−0.539** on a 55-session live
   slice; corrected in round 7 §9.1 to **+0.625** (raw return) / **+0.536** (adjusted excess) on the
   full 127-session window — an explicit sign reversal the document performs and labels a withdrawal,
   not a data revision. This is (per `PROGRAMME-REPORT.md`) "the most consequential number in the
   programme to have been stated both ways."

No other numeric disagreement of this kind (two documents purporting to state the *same*
measurement) was found in the rounds 1–8 documents read for this inventory. The many other instances
of "round N's number changed in round N+1" throughout §§1–8 above are deliberate re-measurements on
new windows, not restatements of the same measurement, and are not inconsistencies.

---

## 13. What rounds 1–8, taken together, established and did not establish

Carried forward from `PROGRAMME-REPORT.md` §14, scoped to what rounds 1–8 alone support (i.e.
excluding the round-9-onward out-of-sample confirmation, which this inventory does not cover):

**Established, per the source documents:**
- A deterministic-engine promotion rule that re-scores frozen cards on old windows double-counts a
  single measurement (round 2).
- Verdicts about which cards are best, hedges, or diversifiers are conditional on the window matrix's
  regime mix — proven by round 4 against round 3, and independently by round 5's bear arm against its
  own ladder.
- Two real engine defects (D1, D2) materially changed reported returns, including sign flips, before
  being fixed; D3 cost real compute twice through operational error; D4 was present in every
  published figure for its first eleven days and moved exactly three results by 0.065 points when
  corrected — no conclusion in any round-1–3 report changed.

**Not established, by rounds 1–8's own account:**
- Nothing in rounds 1–8 is out of sample in the walk-forward sense; every backtested figure,
  including every 5- and 10-year "long-horizon" number, ends on or before the 2026-02-13 design
  cutoff.
- Every card's universe was chosen by an analyst writing in 2026; the survivorship/provenance gate
  only fires on a mechanically index-derived universe, not a thesis-picked one, so every long-horizon
  figure is an unmeasured upper bound.
- The noise floor is ±21.2 points from universe ordering alone; several early promotion/demotion
  decisions were not checked against it until corrected.
- The desk's selection rule changed twice within rounds 6–8 (correlation/overlap caps → discipline/
  family distinctness), and round 8's own closing section flags that the discipline axis may be
  excluding a genuinely diversifying pair no correlation measure would have caught.

---

## Summary

**Rounds covered:** 1 through 8 (r1-2026-08 through r8-2026-08), plus the cross-cutting defects log
(D1–D4) and the separately-tracked drawdown-ladder specification.

**Distinct strategy ideas/concepts tested:** 20 (§10 above) — spanning pairs-rotation, momentum (plus
four attribution variants), trend (two independent implementations), 13F-derived momentum (two
variants), mean-reversion (three variants), volatility/convex payoff (two variants), breakout (three
variants), risk-managed defensive baskets (two variants), universe-breadth/concentration as its own
axis, combined-book portfolio scoring, purpose-built uncorrelated diversifiers, a generalist mandate,
a tactical drawdown-ladder allocation rule (tested outside the card tournament), buy-and-hold
benchmarking (SPY and QQQ), and a pure methodological control (universe-ordering noise).

**Explicitly-untested ideas found:** roughly a dozen distinct, separately-justified items (§11) —
eight engine-level expressiveness gaps (cross-sectional ranking, cross-symbol regime gates,
volatility-scaled sizing, Bollinger-squeeze-relative-to-own-history, shorting/options/leverage,
13F option positions, mid-window universe rotation, dividends, intraday stop realism) and roughly
half a dozen round-level refusals (out-of-sample walk-forward evidence before round 9, pre-2013 long-
horizon data, live-desk-as-its-own-matrix before ~250 sessions, sub-cycle live correlations after
round 7's withdrawal, and the discipline-as-distinctness-axis question left open at round 8's close).

**The three most significant "never measured" gaps:**
1. **No round in 1–8 ever scored the live paper desk's own trading record as evidence** — every
   selection rule (rounds 6, 7, 8) ranked cards on backtests alone, even though the one live record
   the programme had (round 6's 55 sessions, later round 7's corrected 127 sessions) repeatedly
   contradicted the backtest rankings. This gap ("fix 4") is named as open in every round from 6
   through 8 and is not closed until round 11, well outside this inventory.
2. **No card in rounds 1–8 could express a cross-symbol regime gate or cross-sectional ranking** —
   documented first-hand by an analyst's abandoned attempt to gate an equity entry on `^VIX`, and
   structurally by the engine's per-symbol rule evaluator. This forecloses an entire class of
   strategy ("buy the strongest," "reduce risk when volatility regime shifts") that was never once
   tested, not because it failed, but because it could not be written.
3. **Every long-horizon figure (5y/10y, round 5 onward) is contaminated by 2026-hindsight universe
   selection and is explicitly flagged, by the programme's own round-5 report, as an unmeasured upper
   bound** — the survivorship gate only catches mechanically index-derived universes, not
   analyst-thesis-picked baskets of names that happened to win, and no round in 1–8 devised a way to
   test or correct for this.

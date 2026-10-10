# The Strategy Programme — a consolidated report, rounds 1–11

**Not investment advice.** Every figure in this document comes from a specification tested against
stored price history on a simulated paper account. Nothing here is a recommendation about real
capital, and I am not a licensed financial adviser. Several of the round documents this report
consolidates carry the identical disclaimer, and it is repeated here rather than assumed.

**Compiled 2026-08-22**, reading every `BRIEF.md`, `REPORT.md` and `SELECTION.md` under
`data/rounds/r1-2026-08/` through `r8-2026-08/`, `strategy-program/PROTOCOL.md`,
`strategy-program/CONSTRAINTS.md`, `strategy-program/DEFECTS.md`, `strategy-program/WINDOWS.md`,
`strategy-program/ROUND-4-PLAN.md`, `strategy-program/ROUND-5-PLAN.md`,
`strategy-program/ROUND-6-PLAN.md`, `strategy-program/DRAWDOWN-LADDER.md`,
`backend/app/paper/library/retired/README.md` and the `AGENT_IDS` block of
`backend/app/paperdesk/desk.py`.

**§10 was revised and extended 2026-08-22, after compilation.** `data/rounds/r9-2026-08/` did not exist when the
rest of this report was written; round 9 was being run concurrently. It landed, and so did the owner
decision that followed it, so §10 now records both rather than the placeholder it originally held.
Every other section is as compiled and reads rounds 1–8 only.

This report reads nine rounds' worth of documents but changes none of them. Where two documents give
different numbers for what is presented as the same measurement, both numbers are quoted rather than
one being silently preferred — see the appendix.

---

## 1. What the programme is

The Strategy Programme is a running competition between frozen trading-rule specifications
("cards"), each entered once by an analyst and then never revised. Every round traces the same loop
(`strategy-program/PROTOCOL.md` §2): analysts design cards against data bounded by a fixed cutoff
date; the cards are frozen in git before any backtest runs; an orchestrator runs them, serially,
across a matrix of named market-regime windows they did not choose and in most rounds did not know in
advance; a scorer ranks them on the **median exposure-adjusted excess return** across the windows
each card is eligible for, with the worst window and hit rate reported beside the median rather than
folded into it; and the results promote or demote cards between four library tiers — `base/`,
`candidates/`, `variants/` and `retired/` — under `backend/app/paper/library/`. A subset of that
library — currently four rule-based cards plus one non-rule specification, see §9 and §12 — trades
forward, live, on a simulated paper account (`backend/app/paperdesk/`) against whatever the market
actually does after the cards were frozen.

The programme exists because of a documented prior failure. A tournament that preceded it ran 26
strategies over 127 sessions, ranked them on the data their authors had studied, then re-ran the
identical cards over three subsequent years: the rank correlation between the two orderings was
**Spearman ρ = 0.162** — a card placed 13th of 26 in-sample finished 3rd of 24 out of sample
(`strategy-program/PROTOCOL.md` §1). A second, related failure was that exposure — simply being
invested — correlated with three-year return at **ρ = 0.648**, so much of what looked like skill was
being long in a bull market (`strategy-program/PROTOCOL.md` §4, `strategy-program/README.md` "What
this program corrects"). Every structural feature of this programme — the regime matrix, the
exposure-adjusted scoring key, the eligibility gate tying universe choice to which regimes a card can
be judged against, the two-consecutive-rounds promotion rule, the information quarantine between
analysts and prior results — exists to attack one or the other of those two findings.

The programme's own value, made explicit by its own documents, is less in any single round's
leaderboard than in how often a later round overturned an earlier one on the *same, unchanged* cards
simply by changing which windows were measured. Round 4 found that round 3's headline result was a
property of round 3's bear-weighted window mix, not of the cards (`data/rounds/r4-2026-08/REPORT.md`
§1). Round 5 found that the entire programme, rounds 1 through 4, had only ever measured 45-to-284
session holds, and that the measured edge of every top card collapses by roughly a factor of four
once the same cards are held for a decade instead of a year (`data/rounds/r5-2026-08/REPORT.md` §2.1).
Round 7 found that its own headline — that the backtests had ranked the field backwards out of sample
— was itself an artifact of a 55-session slice, and that the full 127-session out-of-sample record
said the opposite (`data/rounds/r7-2026-08/SELECTION.md` §9). A report that read these nine rounds as
nine successive confirmations of a stable ranking would misrepresent what is in the documents; the
reversals are the finding.

---

## 2. Round 1 — twenty-two strategies against five regimes

**Source:** `data/rounds/r1-2026-08/BRIEF.md`, `data/rounds/r1-2026-08/REPORT.md`.

**The question.** Six new analyst-designed cards (`c01-meanrev` through `c06-13f-momentum`), one per
discipline, were traded alongside sixteen cards inherited from the prior tournament (the `A`, `B`,
`C`, `D`, `E`, `F`, `G`, `H` families and their variants), across five market-regime windows, to see
whether the new exposure-adjusted metric and regime matrix would change the picture the prior
tournament's flawed methodology had produced.

**Window matrix (five windows, `strategy-program/WINDOWS.md` predecessor tuple; figures from
`REPORT.md` line 12–19):** `gfc` (2007-10-09 → 2009-03-09, SPY −56.23%), `covid` (2020-02-19 →
2020-06-30, SPY −8.71%), `bear-2022` (2022-01-03 → 2022-10-12, SPY −25.14%), `bull-2024` (2024-08-21 →
2025-08-20, SPY +14.00%), `recent` (2025-08-21 → 2026-08-18, SPY +20.62%), plus the special-case
`13f-legal` window. Gate: eligible in fewer than 3 of 5 main windows → unranked.

**Field size.** 22 ranked/unranked cards plus variants: 84 card-window runs completed
(`REPORT.md` line 9).

**What it concluded.**

- **Not one inherited card could run the GFC.** Every `A`, `B`, `C`, `D`, `H` card was blocked by a
  universe symbol with insufficient history (AVGO 2009, NOW 2012, META, INDA) — the entire legacy
  field was built on names that did not exist in 2008 (`REPORT.md` §1).
- The ranked leaderboard's top six by median adjusted excess were `B2-hold-90`, `B3-concentrated`,
  `G-volatility`, `B-momentum`, `A2-cash-headroom`, `B4-tight-stop` (`REPORT.md` §2 table). But the
  report itself flagged the B family's best window, `covid`, as an artifact: no B-family card held a
  position before 2020-03-30, the post-bottom date, because its entry rule structurally cannot fire
  during a crash — the family scored well by being absent during the fall and present for the
  recovery (`REPORT.md` §2).
- The five new challengers had the five lowest cross-window spreads in the field (IQR 1.70–4.50
  points against incumbents' 8.85–47.38) but ranked worst on median — "consistent and mediocre" against
  incumbents "volatile and higher-median" (`REPORT.md` §3). `c04-riskmanaged` finished a 56% bear
  market up 1.38% on 43.8% capital deployed across 28 trades, yet ranked 18th of 19 because the
  median-only metric cannot see the difference between a hedge and an absence (`REPORT.md` §3).
- Eight variants were run to isolate single design decisions; **none separated from its own base by a
  margin that cleared the noise floor.** The pure ordering-artifact control (`A1-alpha-order` vs
  `A-rotation`, differing only in the order the universe array is written) itself produced a **+6.47
  point** gap — larger than five of the seven substantive variant comparisons (`REPORT.md` §4).
- Two engine defects were found and reproduced mid-round: **D1** (`total_return` silently rebased to
  the first session's close, changing the sign of return for two card-window pairs) and **D2**
  (`exposure` measures session presence, not capital at risk — a card reporting 97.19% session
  exposure had 43.8% capital actually deployed) (`REPORT.md` §6, `strategy-program/DEFECTS.md`).
- `c06-13f-momentum`'s universe was derived from 13F filings dated 2025-11-14 but was initially scored
  on windows beginning years before that date — the same basket-lookahead error the prior tournament
  made, caught here by a human reader rather than a control, and corrected before the report was
  finalised (`REPORT.md` §2, the boxed correction).

**What a later round overturned.** The B family's `covid` result (an artifact of absence during the
crash) foreshadows a pattern round 4 would generalise: raw performance figures in this programme
routinely reflect the window mix rather than the rule. The variant programme's inconclusiveness (§4)
would recur through round 4, when `B2-hold-90` — this round's best-performing variant — failed
promotion twice more.

---

## 3. Round 2 — eight regimes, a metric that can see insurance, and a promotion rule that cannot count

**Source:** `data/rounds/r2-2026-08/REPORT.md`.

**The question.** Does widening the window matrix to eight regimes — adding a genuine crash-quarter
window (`q4-2018`) and, for the first time, two directionless "chop" windows — change the ranking,
and does a dominance view (median + worst + hit rate + Pareto frontier) fix the median-only metric's
blindness to convex/hedge payoffs that round 1 exposed?

**Window matrix (eight windows, `strategy-program/WINDOWS.md`):** `q4-2018`, `covid`, `bear-2022`,
`chop-2015`, `chop-2011`, `bull-2024`, `recent`, `gfc` — 1,729 sessions, mean benchmark return
**−9.45%**, six of eight windows falling (this mean/count is stated directly in
`data/rounds/r4-2026-08/REPORT.md` §1, computed from round 2's own matrix). Gate: 5 of 8 → unranked.

**Field size.** 27 cards (22 carried forward, 5 new: `c07-chop`, `c08-generalist`, `c09-convex`,
`c10-momentum`, `c11-breakout`); 170 card-window runs, 47 honest guard refusals, zero lost to
contention (`REPORT.md` header table).

**What it concluded.**

- **The two-consecutive-rounds promotion rule does not survive contact with a deterministic engine.**
  Because cards are frozen and windows are fixed dates, re-running a round-1 card on a round-1 window
  in round 2 recomputes the identical number rather than sampling anything — verified bit-identical
  on twenty of twenty checked pairs (`REPORT.md` §1). A promotion rule requiring "positive median in
  two consecutive rounds" therefore counts one measurement twice unless the second round brings
  genuinely new windows.
- The dominance view earned its place: `c09-convex`, designed to test whether it was worth adding,
  reached the Pareto frontier at 4th of 22 by Borda composite on 6.80–7.5% mean capital exposure,
  where round 1's median-only rule would have placed it 11th (`REPORT.md` §2).
- But decomposing the GFC window showed **capital exposure correlates with adjusted excess at Pearson
  r = +0.797** in a falling market — the metric credits more exposure in a crash, not less, because
  the adjustment is a credit proportional to exposure against a negative benchmark. Per unit of
  capital actually deployed, the ordering **inverts**: the two smallest books in the GFC were the best
  performers per unit at risk (`REPORT.md` §2).
- The two new "chop" windows mostly re-measured variance the matrix already carried:
  `chop-2011` correlated with `bear-2022` at Spearman **ρ = 0.732**, and the single most redundant
  *pair* in the whole matrix was not a chop pair at all — `q4-2018`/`bear-2022` at **ρ = 0.734**
  (`REPORT.md` §3). A signature-based screen (return, vol, drawdown, path efficiency) that would have
  been used to pre-select future windows agreed with the measured redundancy on only 1 of 8 windows,
  and would have recommended keeping both chop windows as if they were twins — precisely the mistake
  the round made (`REPORT.md` §8, item 3).
- Applying the promotion rule mechanically would have replaced `B-momentum` with `B2-hold-90` on
  margins of **+5.62 and +4.15 points** — both comfortably inside the ordering noise floor the same
  protocol document calls meaningless (`REPORT.md` §5). No such promotion was made; the rule was
  flagged for amendment.
- D1 and D2 were confirmed fixed in the engine (`max |total_return − ending/starting| = 0.000000pp`
  across all 170 runs), and a third defect, D3 (a concurrent read colliding with the tournament's
  write lock), recurred during round 2's own setup and cost an entire first attempt: 135 card-runs,
  zero results, from a detached run whose driving shell loop survived being killed by
  `taskkill /IM python.exe` (`REPORT.md` §6, `strategy-program/DEFECTS.md` D3).

**What a later round overturned.** Round 2's own admission — that the ranking's biases (exposure
credit vs. worst-window favouring small books) were "small in aggregate" (ρ = 0.922 between two
ranking methods) but "concentrated in single-window comparisons" — foreshadows round 4's finding that
the *whole matrix's* regime mix, not just single windows, drives the ranking. Round 2's promotions to
`candidates/` (`c07-chop`, `c09-convex`, `c10-momentum`, `c11-breakout`, and `c01-meanrev` held at
`candidates/`) were made on the corrected rule; round 3 and round 4 would re-test several of them.

---

## 4. Round 3 — does a wider universe change the result?

**Source:** `data/rounds/r3-2026-08/BRIEF.md`, `data/rounds/r3-2026-08/REPORT.md`.

**The question.** The store grew from 173 symbols to 633 (513 current S&P 500/Nasdaq-100
constituents), with symbols reaching the GFC growing from 86 to 380. Does more choice produce a
better field, and does a controlled re-cut of the two base strategies onto the wider universe change
their results?

**Window matrix.** The same eight windows as round 2, unchanged (`REPORT.md` line 1, "Windows,
scoring, the DSL... are unchanged from round 2" per `BRIEF.md` §0). Gate: 5 of 8.

**Field size.** Ten cards: a controlled arm (`B-wide`, `C-wide`, byte-identical to `B-momentum` and
`C-trend` except universe) and six open-arm analyst cards (`c12-meanrev-wide` through
`c17-defensive-trend-wide`), 78 run files (`REPORT.md` header).

**What it concluded.**

- **The controlled arm found no detectable effect from breadth.** `B-momentum` → `B-wide`: −4.3
  points; `C-trend` → `C-wide`: −0.8 points; `C-trend` → `c17-defensive-trend-wide` (same entry rule,
  different universe): −9.0 points. Every margin sat inside the 53.9-point / σ = 21.2 ordering noise
  floor (`REPORT.md` §1).
- The open arm's centre of mass was unchanged from round 2 (median of medians +5.7% → +6.2%) and its
  best card was materially *worse* (+19.3% in round 2 vs. +10.4% here) (`REPORT.md` §2).
- **The GFC's raw excess figures were an artifact twice over.** First, `DEFECTS.md` D2 in action: a
  card posting +55.3% raw excess on **one trade at 0.6% capital exposure** (`c12-meanrev-wide`) had
  simply declined to attend, and adjusts to −0.5%. Second, **survivorship**: the two cards whose GFC
  adjusted excess survived the exposure correction (`c15-volatility-wide`, `c14-riskmanaged-wide`)
  did so partly because a universe drawn from *today's* S&P 500 cannot contain Lehman Brothers, Bear
  Stearns, Washington Mutual or Countrywide — every one removed from the index because it collapsed.
  `c15`'s own analyst had pre-registered `gfc` as its predicted *worst* window on sound reasoning about
  impaired 2008 bank balance sheets; it came back as the card's *best* window, +69.6% raw / +18.4%
  adjusted (`REPORT.md` §3). This was recorded as the project's clearest demonstration of
  survivorship, precisely because the prediction preceded the (wrong) result.
- **The round's one genuinely useful new card, `c14-riskmanaged-wide` (universe: TLT, IEF, GLD, LQD),
  used no symbol added by the universe expansion at all** — every one of its four names was already in
  the 173-symbol store (`REPORT.md` §5). It reached the Pareto frontier on best worst-window (−1.0%)
  and best hit rate (75%) and was promoted to `candidates/` pending a second round on new windows
  (`REPORT.md` §6).
- **The combined-book finding** (this is `strategy-program/ROUND-4-PLAN.md` §1, written using round
  3's eight-window matrix; it is treated here as belonging to round 3's evidence base because it is
  computed on round 3's data before round 4 ran any new windows): combining `B-momentum`, `C-trend`
  and `c14-riskmanaged-wide` in equal thirds, rebalanced per window, produced a median excess of
  **+15.4%**, a worst window of **−11.1%** against `C-trend` alone's −22.9%, and 75% hit rate across
  all eight windows — because `C-trend` and `c14` measured at **ρ = +0.04** (effectively
  uncorrelated) while `B-momentum` and `C-trend` measured at **ρ = +0.57** (near-redundant). This was
  presented as the strongest result the programme had produced to that point, with one disclosed
  caveat: two-thirds of the "crisis" excess was non-participation (cash), not alpha.

**What a later round overturned — this is the central reversal the task instructs to surface.** Round
4 re-ran the *identical, unchanged* cards on six windows they had never seen, with a mean benchmark
return of **+17.13%** (bull-weighted, vs. round 3's −9.45% bear-weighted mean) and found:

> "Round 3's combined book does not replicate. It is beaten by `B-momentum` alone on every axis.
> Adding the two cards designed as diversifiers... makes the worst window three to four times deeper
> than holding `B` on its own." (`data/rounds/r4-2026-08/REPORT.md` §6, table row "`B` + `C` + `c14`
> (round 3's book)": median +1.06%, worst −6.59%, hit 50%, against `B-momentum` alone: median
> +5.82%, worst +0.04%, hit 100%.)

The mechanism was the correlation itself flipping sign: `C-trend`/`c14` measured **ρ = +0.04** on
round 3's matrix and **ρ = −0.554** on round 4's — the same two frozen cards
(`data/rounds/r4-2026-08/REPORT.md` §4). Round 4's own words: **"Round 3's conclusions were
properties of round 3's windows"** (`REPORT.md` §1 heading). This is treated in this report as the
canonical instance of "round 3's combined-book finding, falsified by round 4."

---

## 5. Round 4 — which cards belong together, and a matrix that reverses everything

**Source:** `strategy-program/ROUND-4-PLAN.md`, `data/rounds/r4-2026-08/BRIEF.md`,
`data/rounds/r4-2026-08/REPORT.md`.

**The question.** Round 4 shifted from "which card is best" to "which cards belong together,"
built on the concentration finding that the live desks' actual holdings were far more correlated than
their nominal universes suggested (`C-trend`'s four positions: mean pairwise ρ = 0.765, one of the
four — SOXX — a basket of the other three) (`ROUND-4-PLAN.md` §1). It set out to confirm or reject
`B2-hold-90` and `c14-riskmanaged-wide` on genuinely new windows, test four new cards' claimed
diversification, and score the combined book.

**Window matrix.** Six windows, **all new** — none used in rounds 1–3: `recovery-2009`,
`taper-2013`, `oil-2014`, `volmageddon-2018`, `inflation-2021`, `banks-2023`. Mean benchmark **+17.13%**,
2 of 6 falling (`BRIEF.md` §1, `REPORT.md` §1). Gate: 4 of 6.

**Field size.** 14 cards (10 returning, 4 new: `c18-meanrev`, `c19-volatility`, `c20-rotation`,
`c21-uncorrelated`); 78 run files plus 25 in a separate control arm (`REPORT.md` Appendix).

**What it concluded.**

- **The finding this report treats as the single most important reversal of the programme: "round 3's
  conclusions were properties of round 3's windows."** See §4 above for the mechanism and figures.
- **Verdicts are conditional on the window matrix's regime mix, and this round measured it directly.**
  Round 3's eight windows were **6 of 8 falling** (mean benchmark −9.45%); round 4's six windows were
  **2 of 6 falling** (mean benchmark +17.13%) (`REPORT.md` §1 table). A low-exposure, flight-to-quality
  leg (`c14`) wins the first matrix and loses the second mechanically, without the card changing at
  all.
- `B2-hold-90` was **not promoted**: it lost to its own base, `B-momentum`, on all three axes in round
  4, and it is the only B-family card with a negative worst window there (`REPORT.md` §3). The
  take-profit/max-hold-days axis had by this point been tested three separate ways with no version
  beating the base twice, and the axis was recommended closed.
- `c14-riskmanaged-wide` was **not confirmed as a standalone rankable card** (median swung from +2.3%
  to **−2.32%**, worst window from −1.0% to **−19.78%**, rank from Pareto frontier to 13th of 14) but
  its correlation claim **replicated and strengthened** in the opposite direction its round-3 evidence
  suggested (ρ to `C-trend`: +0.04 → **−0.554**). It was kept in the library as a labelled hedging leg
  only, never again to be scored on median (`REPORT.md` §4).
- **All four cards submitted specifically to be uncorrelated diversifiers failed that test.** The two
  built explicitly for it, `c20-rotation` and `c21-uncorrelated`, were the *most* correlated cards in
  the field with `B-momentum` (ρ = +0.917, +0.907) — above even `C-trend`. `c21`'s own memo had
  pre-registered the exact falsification condition ("if the realized number lands well above 0.3 ...
  the correlation argument in this memo is wrong") and it was recorded as such (`REPORT.md` §5). The
  cause: analysts had measured *daily-return* correlation (0.36–0.41) while the scorer used
  *window-level* correlation, which is dominated by equity beta, not by trade timing.
- Scoring the combined book found no combination beat its single strongest leg on median; the one
  combination that "worked" (`B-momentum` + `c07-chop`) did so partly on a spectator cell — one trade
  at 0.8% capital exposure in the one window `B` cannot run at all (`REPORT.md` §6).

**The control arm — the retirement reasoning for the A family was regime-conditional, not
structural.** This is the finding the task instructs to surface explicitly. `ROUND-4-PLAN.md` §3
retired the five-card A family on the stated reasoning: *"they look acceptable on raw return because
they are heavily invested in a rising market, and they lose once that exposure is paid for."*
Un-pre-registered, run after the leaderboard because §1 implied it, the five retired A cards were
re-run unchanged on round 4's six windows:

| card | median adj. excess | worst | hit | mean exposure | would rank |
|---|---|---|---|---|---|
| `A-rotation` | **+4.20%** | **+0.20%** | **100%** | 76.5% | **2nd of 19** |
| `A4-tight-stop` | +4.20% | +0.20% | 100% | 76.4% | 3rd |
| `A3-no-target` | +3.02% | −0.74% | 80% | 77.0% | 6th |
| `A2-cash-headroom` | +2.58% | −0.97% | 80% | 72.0% | 8th |
| `A1-alpha-order` | +0.40% | −6.50% | 60% | 76.5% | 12th |

(`data/rounds/r4-2026-08/REPORT.md` §7.) `A-rotation` and `A4-tight-stop` finished ahead of
`B-momentum` on the Borda composite. **The specific claim in the retirement note was falsified**: at
76.5% mean capital exposure, `A-rotation` posted a positive median and worst window and beat every
surviving candidate, once the exposure correction that supposedly damned it was applied on a
bull-weighted matrix instead of a bear-weighted one. What survived: the A family really is the
highest-exposure book ever measured in the programme, it really did lose badly on a bear-weighted
matrix, and the four A variants really are dominated by their own base on both matrices — so their own
retirement stands on separate grounds (`REPORT.md` §7). The retirement log was amended with these
figures rather than edited silently (see §11 below and
`backend/app/paper/library/retired/README.md`), and `A-rotation` was reinstated to `candidates/` as a
"high-exposure comparator."

---

## 6. Round 5 — the horizon ladder

**Source:** `strategy-program/ROUND-5-PLAN.md`, `data/rounds/r5-2026-08/REPORT.md`.

**The question.** Every window measured in rounds 1–4 was between 45 and 284 sessions long. Does the
ranking depend on how long the competition holds cards open — six months versus ten years — separate
from the regime-mix question round 4 had just answered?

**Window matrix.** 27 windows total: a 21-window "ladder" arm sampled evenly across a common
2013-09-03 → 2026-02-13 period at five horizons (6m ×6, 1y ×6, 3y ×4, 5y ×3, 10y ×2 — the two 10y
windows share 62% of their sessions and are explicitly *not* treated as independent), and a 6-window
"bear" arm selected on a falling benchmark, reported separately and never pooled into the ladder's
medians (`ROUND-5-PLAN.md` §2, `REPORT.md` header). The benchmark rises in 19 of the 21 ladder
windows — no decade in the available data has a falling benchmark. Gate: 2 windows per horizon.

**Field size.** 15 cards — round 4's 14 plus `A-rotation` reinstated by the control arm — no new
submissions; this was a deliberate measurement study on a fixed field, not a submission round
(`REPORT.md` header, `ROUND-5-PLAN.md` §4). 405 of 405 run files completed, every card eligible for
every window.

**What it concluded — the horizon finding, verified exactly against the task's figures.**

> "The best annualized figure in the field falls from **+31.6% at one year to +7.6% at ten** — the
> same cards, the same engine, the same metric, the same calendar." (`data/rounds/r5-2026-08/REPORT.md`
> §2.1.) The per-horizon best-card figures given in the report's own table: 6m +19.92%, 1y **+31.55%**,
> 3y +15.36%, 5y +15.12%, 10y **+7.59%** (§2.1 table). The card in question, `A-rotation`, moved from
> rank 1 at 6m and 1y to rank 5 at 10y (§1 table).

- **The variant experiments measure nothing at a long hold.** `B2-hold-90` differed from
  `B-momentum` by an 11.8-point spread at one year and was inside **0.45 points** of it, and of
  `B4-tight-stop`, at ten years — the entire take-profit/max-hold axis this programme spent four cards
  and three rounds attributing "was measuring the length of the window rather than the merit of the
  rule" (`REPORT.md` §2.2).
- **The bear arm identified the field's real hedges**, inverting the ladder ranking:
  `c20-rotation`, last of fifteen at every ladder horizon, was first in the bear arm with a
  **+14.79-point** swing between the two arms — "not a failed strategy but an unlabelled hedge"
  (`REPORT.md` §2.3).
- **The QQQ benchmark finding, verified exactly against the task's figure.** SPY is the scored
  benchmark throughout the programme, and it is "the flattering choice" for a field of AI/semiconductor
  books. Re-deriving every ladder result against QQQ instead: "The ordering barely moves. The
  magnitudes roughly halve." At ten years: `B-momentum` +7.59% (SPY) → **+3.9%** (QQQ); `A-rotation`
  +5.28% → **+0.6%**; `C-trend` +4.45% → +1.3% (`REPORT.md` §3.3 table). The report's own summary: "for
  the AI and semiconductor books the QQQ column is the more demanding and the more relevant one"
  (§3.3). This is the finding recorded in the task as "swapping SPY for QQQ roughly halves every
  AI/semis book's edge" — confirmed as stated, with the caveat that the halving is a rough
  characterisation of the *aggregate* effect (+11.20%/yr SPY vs +15.76%/yr QQQ mean across the ladder,
  §3.1) rather than a uniform per-card multiplier.
- **The caveat that limits everything above:** every top card's universe was chosen by an analyst
  writing in 2026 and then run from 2013 — a decade over which knowing which semiconductor names to
  hold was worth the most, and the programme's own survivorship gate does not catch thesis-picked
  (as opposed to mechanically index-derived) baskets over a multi-year hold (`REPORT.md` §4). Every
  long-rung figure in the report is stated as an upper bound for this reason.

**What this feeds into.** Round 5 exists explicitly to give round 6's paper-desk selection "the one
piece of evidence it has never had" — whether short-window and long-horizon rankings agree
(`ROUND-5-PLAN.md` §6). They mostly do not.

---

## 7. Round 6 — four cards for the paper desk

**Source:** `strategy-program/ROUND-6-PLAN.md`, `data/rounds/r6-2026-08/SELECTION.md`.

**The question.** Which four cards should trade forward, live, on the paper desk — a fundamentally
different decision from every prior round because the desk holds forward indefinitely, runs four
cards simultaneously as a book rather than a shortlist, and is observed rather than scored
(`ROUND-6-PLAN.md` §1). The selection rule was pre-registered *before* round 5's results existed —
stated explicitly as the single most important property of the document (`ROUND-6-PLAN.md` header).

**Evidence read, not a new backtest window:** rounds 2, 4 and 5 (ladder and bear arms) plus the
already-running live desk.

**What it concluded.**

- Two amendments were made to the pre-registered rule *before* it was executed, both logged rather
  than silently folded in (`ROUND-6-PLAN.md` §7): Gate A collapsed the original two-slot rank-stability
  design into a single admission gate — positive median annualized adjusted excess at both the 5y and
  10y rungs, against **both** SPY and QQQ — because round 5 showed a short-window criterion selects on
  the noisiest rung and the QQQ requirement roughly halves `A-rotation`'s apparent decade edge (+5.28%
  → **+0.63%**). Gate B added a hard correlation cap of ρ ≤ +0.70 between any two desk cards, forced
  by the live desk itself already holding `B-momentum` and `C-trend` at ρ = +0.909, trading the same
  rotation twice (§7.2).
- **The result:** `B-momentum` (core, best worst-rank across three matrices), `A-rotation` (second
  engine, ρ = +0.497 to the core), `c07-chop` (diversifier, ρ = −0.283 to `A-rotation`), and
  `c14-riskmanaged-wide` (hedge, the only candidate clearing both the correlation cap and the exposure
  floor) (`SELECTION.md` header table). `C-trend` was dropped from the incumbent desk.
- **The card with the strongest hedge signature in the entire programme, `c20-rotation`
  (+14.8-point bear/ladder swing, three times the next card's), was excluded on a single number** — a
  raw round-4 correlation of ρ = +0.917 to `B-momentum` — that the same document flags as suspect,
  since the same pair reads ρ = **−0.591** on the annualized bear arm (`SELECTION.md` §3). The rule
  was applied as written rather than rewritten around this result, and `c20-rotation` was flagged for
  round 7.
- **The live desk — the programme's only out-of-sample evidence at the time — contradicted every
  backtest conclusion above.** Over 55 live sessions (2026-06-01 to 2026-08-18, SPY +1.17%, QQQ
  −3.40%), the ladder's rank-1 short-horizon winner (`A-rotation`) was **last of ten live at −12.77%**,
  and the ladder's 8th-of-10 card (`c18-meanrev`) was the *only* one making money live, at +2.44%.
  **Spearman rank correlation between round 5's ladder ranking and the live ranking: −0.539**
  (`SELECTION.md` §6). This is the figure the task specifically requires — see §9 below for its own
  reversal one round later.
- Two of the four selected cards, `c07-chop` and `c14-riskmanaged-wide`, took **zero trades** in the
  55 live sessions and sat at 100% cash, because the exposure floor that qualified them for the hedge
  slot was measured on historical windows, not on the regime the desk was actually about to trade
  (`SELECTION.md` §6.1) — logged as a defect for round 7 rather than silently patched.
- The book check (equal-weight across all four matrices) passed with a veto count of 1 (the veto fires
  above 1) — the selection stood (`SELECTION.md` §4).

---

## 8. Round 7 — re-selection under the live-evidence gates

**Source:** `data/rounds/r7-2026-08/SELECTION.md`.

**The question.** Apply the four fixes round 6 pre-registered for itself (§6.3 of that document): a
liveness gate, a holdings-overlap cap alongside the return-correlation cap, re-specifying correlation
on annualized figures only, and scoring the live desk as its own matrix once it has enough sessions.

**What it concluded.**

- **Fix 1 (liveness gate)** removed `c07-chop` and `c14-riskmanaged-wide` outright — both had taken
  zero trades in the 60 sessions before selection (`SELECTION.md` §1).
- **Fix 2 (holdings-overlap cap, ≤25% shared book weight)** was the round's real finding: every pair
  among the six equity-family books breached it, including `B-momentum`/`A-rotation` at only ρ =
  +0.497 (comfortably under Gate B's correlation cap) but **45% shared holdings weight** — the same
  NVDA/AVGO/TSM names. After the cap, `H-trend-diversified` was the only card in the field that could
  sit beside *any* equity book at all, capping the desk at two performance seats as a consequence
  rather than a design choice (`SELECTION.md` §2).
- **Fix 3 (annualized-only correlation)** vindicated round 6's flag on `c20-rotation`: its correlation
  to `B-momentum` measured **−0.054** on the annualized-only rule against **+0.917** on round 6's
  raw-inclusive rule — the same two frozen cards (`SELECTION.md` §3). `c20-rotation` took the hedge
  seat.
- **Fix 4 (score the live desk as its own matrix) could not be applied** — 55 sessions is far too few,
  and doing so "would give a single quarter's rotation more weight than every backtest combined"
  (`SELECTION.md` §4). Deferred to ~250 sessions, roughly mid-2027.
- **The result:** `B-momentum` and `H-trend-diversified` (performance seats), `c20-rotation` and
  `c11-breakout` (hedge seats). Dropped: `A-rotation`, `c07-chop`, `c14-riskmanaged-wide`.

**§9's self-correction — the finding the task specifically requires, stated precisely.** The desk was
subsequently backdated from 2026-06-01 to 2026-01-01, exposing that the 55-session window used
throughout the rest of the document was an unrepresentative slice. Section 9 corrects two claims:

> "Spearman: round 5's ladder rank vs forward result — on the 55-session slice (§6, as reported):
> **−0.539**. On the full 127-session out-of-sample period, raw return: **+0.625**. Same, on adjusted
> excess: **+0.536**." (`SELECTION.md` §9.1.)

**The sign flips.** The report's own words: *"The claim in §6 — 'the backtests ordered this field
roughly backwards over the only period no analyst could have studied' — was true of the slice I
measured and false of the period it was meant to describe. It is withdrawn."* (§9.1.) Over the genuine
127-session out-of-sample window (2026-02-17 → 2026-08-18, SPY +12.84%, QQQ +19.20%), the five cards
round 5's ladder ranked highest were the five that finished highest out of sample, led by
`B3-concentrated` at +51.63% raw / +39.91% adjusted vs. QQQ.

Section 9 also disclosed that round 7's own selection **underperformed out-of-sample**: round 7's four
returned +8.76% against round 6's four at +17.39% and SPY at +12.84% — the holdings-overlap cap's
foreseeable cost, removing `A-rotation` (+37.36% out of sample) in favour of `H-trend-diversified`
(−3.14%) (`SELECTION.md` §9.2). The methodological lesson was recorded as the author's own, not the
programme's: "I computed a rank correlation on 55 sessions and reported its sign as a finding... A
forward window shorter than roughly one full cycle should be reported as an observation and never as
a correlation" (§9.4).

---

## 9. Round 8 — re-selection under the reference-signal rule

**Source:** `data/rounds/r8-2026-08/SELECTION.md`.

**The question.** Rounds 6 and 7 selected the desk's four cards as if they were one combined
portfolio (a return-correlation cap and a holdings-overlap cap, both pairwise). Round 7's own §9.2
priced that premise: the overlap cap cost roughly nine points against round 6's roster and four
against holding SPY over the only out-of-sample window available. Round 8 retires that premise.

**What it concluded.**

- **The correlation-cap, the holdings-overlap cap and the book veto were retired outright, not
  amended** (`SELECTION.md` header, "The rule, as executed"). The stated reasoning: the desk's owner
  reads each of the four cards as an **independent reference signal** for what to buy in a single real
  account. Nobody holds all four at once; they do not need to be uncorrelated with each other, and
  "there is nothing to veto."
- In place of the caps: **at most one card per `StrategyCard.discipline`, and at most one per base
  family** — distinctness of *idea*, not of *return* — plus two gates carried over from round 7: Gate
  A (positive median annualized adjusted excess at both 5y/10y rungs, against both SPY and QQQ) and
  Gate L (at least one trade in the 2026-02-17 → 2026-08-18 out-of-sample window).
- Ranking, among survivors of both gates, was by **out-of-sample adjusted excess vs. QQQ** — "the only
  genuinely out-of-sample evidence the programme has" — taking the best card in each distinct
  discipline/family group. Eight cards cleared both gates — the same eight round 6 found
  (`SELECTION.md` §1) — spanning exactly four groups, so the ranking determined the roster without
  further tie-break (§3).
- **The result:** `B-momentum` (momentum family — see the override below), `A-rotation`
  (pairs-rotation, +24.28% adj. vs QQQ — "the card round 7's overlap cap dropped; the correction
  stands"), `c07-chop` (mean-reversion, the only candidate in that discipline to clear Gate A, despite
  −0.77% adj. vs QQQ), `H-trend-diversified` (trend, beating `C-trend`'s −6.02% with −5.49%).
- **§6 — the owner override, recorded as an override rather than folded into the rule.** Applying
  round 8's own rule as written selects `B3-concentrated` for the momentum seat: +51.63% raw /
  +39.83% adjusted vs QQQ out of sample, against `B-momentum`'s +31.97% / +20.98%. **The desk's owner
  seated `B-momentum` instead**, on the evidence that it has never been worse than third across three
  different historical matrices (ranks 3/2/2 on r2/r4/r5-ladder) and posts the better 10-year figure
  against both benchmarks (+7.59%/+3.92% vs `B3`'s +5.78%/+1.90%). The document's own framing: *"Both
  readings are supported by the programme's own numbers, and neither is obviously wrong... It is
  written up as an override rather than folded into the rule. A selection rule quietly restated to
  produce the answer someone wanted is not a rule."* (§6.) This is the specific finding the task
  requires under "the owner override on the momentum seat recorded in its §6."
- **A benchmark-anchoring artifact was found and explained, not corrected as an error**: round 8's
  recomputed SPY figures for the same cards differ from round 6's published figures by up to 0.124
  annualized points, and the out-of-sample SPY/QQQ figures for the identical 2026-02-17→2026-08-18
  window differ across round 7's and round 8's own documents (SPY +12.84% vs +12.39%; QQQ +19.20% vs
  +19.33%) because the engine's own `benchmark_return` is measured over the sessions actually traded
  while a calendar-date recomputation is not — "one benchmark measured two defensible ways," a
  reprise of an effect round 5's report had already documented at up to 0.85 points across 21 windows
  (`SELECTION.md` §1–2, §5). See the appendix below.

**What survives to round 9.** The document leaves three items explicitly open: fix 4 (score the live
desk's own matrix) is closer but still deferred; whether `discipline` is the right distinctness axis
is unresolved, with `C-trend` vs. `H-trend-diversified` named as the specific case it may be getting
wrong; and every SPY figure crossing a round boundary should state its anchor.

---

## 10. Round 9 — a pre-registered rule that under-filled, and what was done about it

**Revised after compilation.** This section originally recorded that `data/rounds/r9-2026-08/` did not
exist on disk. It does now (`SELECTION.md`, six sections), and this replaces the placeholder.

### The rule

Round 8 ranked the momentum seat on a single 127-session out-of-sample window, selected
`B3-concentrated`, and the desk owner overrode it in favour of `B-momentum` on rank stability across
matrices — then asked for that reasoning to become a rule (§9 above; `r8/SELECTION.md` §6). Round 9 is
that rule, pre-registered before its own numbers existed:

- **Gate A** unchanged — positive median annualized adjusted excess at round 5's 5y and 10y rungs
  against both SPY and QQQ. Eight of fifteen cards clear it, the same eight rounds 6 and 8 found.
- **Gate L** tightened — must have traded out-of-sample **and** hold a position now or have traded
  within 60 sessions. This closes the hole `c07-chop` fell through in round 8: it cleared that round's
  one-trade liveness bar and has since sat at 100% cash for 92 sessions.
- **Gate S** new — worst rank across the round-2, round-4 and round-5-ladder matrices ≤ 5.
- **Ranking** changed — median annualized adjusted excess over the 5y and 10y rungs vs QQQ, replacing
  round 8's six-month out-of-sample window.
- **Distinctness** unchanged, and **take the top four**.

### What it produced

**It settled the thing it was built to settle.** `B-momentum` clears Gate S with a worst rank of 3
(3/2/2) and wins the ranking outright at **+7.68%** median annualized adjusted excess vs QQQ, against
`B4-tight-stop`'s +4.96% and `B3-concentrated`'s +2.72%. The momentum seat now falls out of the rule
rather than out of a person's judgement, and no override is recorded because none was needed.

**And it filled one of four ranked seats.** Only three cards clear Gates A, L and S — `B-momentum`,
`B4-tight-stop`, `B3-concentrated` — and all three are the same base family, so distinctness allows
exactly one. `A-rotation`, `B2-hold-90`, `C-trend` and `H-trend-diversified` clear Gates A and L and
fail Gate S (worst ranks n/a, 7, 6 and 8); `c07-chop` fails the tightened Gate L. Round 9's own output
was therefore a two-card desk: `B-momentum` plus the unranked `ladder-qld-schd`.

`A-rotation`'s failure is the sharpest case: it has **no round-4 matrix result at all**, having been
retired after round 4 and reinstated for round 5. Gate S treats an absent matrix the way this
programme treats every missing number — not invented, not assumed favourable — so an availability gap
reads identically to a bad rank.

The round did **not** loosen the threshold after seeing the seat count, and `r9/SELECTION.md` §5 says
so explicitly, naming a looser ≤7 bar as the substitution it is refusing to make.

### The owner decision (§6 of that document, 2026-08-22)

The choice put to the desk owner was: ship the two-card roster, or keep round 8's five and repair
Gate S for round 10. **The second was chosen.** The desk trades `B-momentum`, `A-rotation`,
`c07-chop`, `H-trend-diversified` and `ladder-qld-schd`, unchanged from round 8, and
`strategy-program/ROUND-10-PLAN.md` pre-registers the replacement gate.

Two defects were identified as the reason a re-threshold would not have been enough:

1. **Gate S and distinctness select against each other.** A global top-five bar is clearable only by
   the strongest *family*; distinctness then collapses that family to one seat. The tighter Gate S is,
   the fewer disciplines reach the ranking at all.
2. **Gate S measures competitiveness, which Gate A and the ranking already measure.** What round 8's
   override was reaching for was *dispersion*: `B-momentum` at 3/2/2 against `B3-concentrated` at
   2/1/5. `B3` has the better level on two of three matrices; `B-momentum` has the tighter spread. A
   level bar cannot express that and separated the two here only because `B3`'s worst rank landed
   exactly on the line.

Round 10's Gate S′ replaces the level bar with a coverage clause (a result on ≥2 of 3 matrices, never
imputed) and a pure dispersion bar (`max rank − min rank ≤ 3`), and makes the seat count an **output
rather than a target** — the fixed four is what turned an under-fill into a problem. Under S′,
`A-rotation` still fails, but now for a substantive reason: **10th of fifteen on round 2's
bear-weighted matrix and 1st on round 5's ladder arm**, the largest rank swing in the field and a
direct instance of round 4's central finding that rankings are conditional on the window mix.

That plan's own disclosed feasibility check projects **two ranked seats plus the ladder** — better
than one, still short of four. The honest reading is that this is a fact about the field's width, not
about any gate: eight cards clear Gate A and four of the eight are variants of one base card.

### What this means for §9's open items

Round 8's third open item — whether `discipline` is the right distinctness axis, with `C-trend` vs.
`H-trend-diversified` named as the case it may be getting wrong — is **still open**, and round 10's
feasibility check lands squarely on it: those two are the trend pair whose seat S′ leaves undecided,
separated by 0.04 points on the 10-year rung.

---

### 10.1 Round 10 — Gate S′ applied, and the desk drops its best performer

**Kept inside §10 on purpose.** Rounds 9 and 10 are one rule and its repair applied to **one body of
evidence**, not two measurements. The bar store is unchanged (SPY 8,445 rows ending 2026-08-18, QQQ
6,903, verified rather than assumed), every card is frozen, and the out-of-sample window is the same
127 sessions. Round 10 recomputes the arithmetic and **carries Gate L forward rather than re-running
it**, because re-running a frozen tournament over an unchanged store reproduces it exactly and would
then read as independent confirmation — the error this programme already caught itself making once
(`strategy-program/PROTOCOL.md` §6(a)).

**Gate S′** replaced round 9's level bar with two clauses and no level term at all: a result on ≥2 of
the three matrices (an absent matrix never imputed in either direction), and `max rank − min rank ≤ 3`
across the matrices actually run. **Four cards clear it** — `B-momentum` (3/2/2, range 1),
`B4-tight-stop` (4/3/4, range 1), `C-trend` (5/5/6, range 1), `H-trend-diversified` (6/8/7, range 2).
Distinctness seats one per discipline: **`B-momentum`** (+7.68% median annualized adjusted excess vs
QQQ, against `B4-tight-stop`'s +4.96%) and **`C-trend`** (+2.01% against `H-trend-diversified`'s
+1.79%).

**Two seats of four, for the second round running** — but this time not a decision to escalate. The
plan pre-registered the seat count as an *output with no floor*, and that single change, more than the
change to Gate S itself, is what stopped an under-fill from becoming a question somebody had to answer
under pressure to loosen a threshold.

**Gate A is unchanged and reproduces round 9's table figure for figure**; Gate L removes only
`c07-chop` (100% cash, 92 sessions).

**What it cost.** The desk goes from five references to three, and it drops **`A-rotation`, its best
live performer** — +65.18% since inception, +37.36% out-of-sample — for `C-trend` at −2.03% live. That
is the **third rule in four rounds to drop this card, each for a different stated reason**: round 7's
holdings-overlap cap (which round 7's own correction later found cost roughly nine points of
out-of-sample return), round 9's absent round-4 matrix, and now round 10's rank dispersion. Round 8
reinstated it once already.

**The owner has since overridden that and kept `A-rotation` on the desk** (round 10 §7, added after
its §§1–6). The desk trades four references: `B-momentum`, `C-trend`, `A-rotation` and
`ladder-qld-schd`. The rule's output is unchanged and `A-rotation` is still recorded as failing Gate
S′; the override sits beside the rule rather than inside it.

**That is the second override in three rounds, and it is the real finding of both.** Round 8's
override asked for its reasoning to become a rule; that request produced two entire rounds of careful
rule-writing — round 9 pre-registered a stability gate, round 10 repaired a genuine defect in it — and
the repaired rule was overridden too. Both times the rule ranked on backtests and the owner weighted
the live record. **Nothing in Gates A, L, S′ or the ranking scores the live desk's own performance**;
Gate L touches it only to ask whether a card is *alive*, never whether it is *right*. A fourth gate
will not close that. Fix 4 will, and it is open since round 6.

Round 10's §5 gives both readings and settles neither. The gate may be working — a card that ranks
1st when the window mix favours risk and 10th of fifteen when it does not is exactly what a dispersion
bar exists to catch, and the live period has been overwhelmingly one of those regimes. Or the gate may
be discarding the desk's most useful signal on backtest evidence while a 127-session live record says
otherwise. **The programme has no rule for resolving live evidence against backtests**, which is fix 4
(§ the carried-forward list below), open since round 6 — and this is the first time it would have
changed a seat rather than a footnote.

**One genuine improvement, separate from the seat.** Round 9 excluded `A-rotation` because its
round-4 matrix is *absent* — an availability gap that read identically to a bad rank. Under S′ the
absent matrix is simply not counted, the card clears the coverage floor on two matrices, and it then
fails on what those two actually say. Same verdict, honest reason.

**Two things flagged as unsettled in round 10's own document, not discovered later:** the trend seat is
decided by **0.22 points**, far inside the programme's measured noise floor, with both medians leaning
on a single outsized `h5y-3` rung — round 8's still-open question about whether `discipline` is the
right distinctness axis lands exactly here. And no card passed S′ on reduced coverage, so the plan's
disclosed two-matrix weakness does not bear on this result at all.

---

### 10.2 Round 11 — fix 4, and a measurement defect caught by a failed prediction

**The recommendation open since round 6 was finally implemented**: score the live desk's own record
and weight it above the backtests. Gates A and L stay as floors, **Gate S′ stops eliminating and
becomes a tie-break**, a new **Gate C** requires a positive result in at least 3 of 6 live
sub-periods, and the ranking moves to the median `adjusted_excess` across those six.

**The first attempt at the live matrix was invalid and was thrown away.** Six *independent*
sub-window runs each start with a flat book, so a card that entered in March and held into August was
forced to liquidate and re-enter six times. `B-momentum` showed **zero trades and 0.0% exposure in two
whole sub-windows while fully invested**, because its entry rule cannot accumulate its lookback in 21
sessions from flat. The bias was directional, not random: high-turnover cards barely notice a reset,
hold-and-ride cards are destroyed by it, and on the broken matrix all four momentum variants and both
trend cards scored 1/6 while the two highest-turnover cards scored 4/6 and 5/6.

**It was caught by a pre-committed prediction failing, not by inspection.** `ROUND-11-PLAN.md` §6
predicted `B3-concentrated` would lead the live matrix. The broken matrix instead seated `A-rotation`
alone — the same card the owner had overridden round 10's rule to keep the day before, and precisely
the outcome §5 of that plan told a reader to be suspicious of. The contradiction prompted looking at
the `+0.00%` cells rather than shipping the roster. Recorded as **D5**; the invalid output is kept as
its evidence. The runs are now cumulative from one fixed start and differenced, which is exact for
return, benchmark and exposure alike, and a runtime self-check confirms the first sub-period reduces
to `score.adjusted_excess` for all 15 cards. **No threshold, gate or boundary moved**, and the
correction moved the answer away from the convenient one.

**The result: three seats** — `B3-concentrated` (live median +7.41%, 4/6), `A-rotation` (+3.47%, 4/6),
`C-trend` (+1.81%, 3/6), plus the unranked ladder. Gate C removed one card,
`H-trend-diversified` (1/6). All four of the plan's pre-committed expectations held.

**What fix 4 actually settled: it split the two overrides rather than ratifying them.**

| | the rule said | the owner said | the live record says |
|---|---|---|---|
| round 8 | `B3-concentrated` | overrode → `B-momentum` | **`B3-concentrated`** (+7.41% vs +4.82%) |
| round 10 | drop `A-rotation` | overrode → kept it | **keep it** (seated on the rule) |

**Round 8's override is reversed and round 10's is vindicated by the same evidence**, which is the
most trustworthy outcome available here: a live-first rule that had simply agreed with every owner
decision would be indistinguishable from one fitted to them. `B-momentum` leaves the desk — it clears
every gate and ranks second, but `B3-concentrated` is the same base family and outranks it.

**The tie-break chain earned its keep.** The three `B` variants posted identical medians *and* hit
rates and identical cells in five of six sub-periods — over six months their differing exits almost
never bound. Gate S′'s rank range separated `B2-hold-90` (6) from the other two (1 each), and Gate A's
10-year QQQ median finally separated `B-momentum` (+3.92%) from `B4-tight-stop` (+3.51%). Demoted from
gate to tie-break, S′ now does real work exactly where a tie-break should and none where it used to do
damage.

**The limitation, which the round states rather than buries:** six contiguous sub-periods of one
period are not six regime draws. Every survivor's row has the same shape because they all lived
through the same market. The three backtest matrices — a GFC, a COVID crash, two chop regimes, a
decade of bull market, 27 horizon windows — are where regime coverage lived, and this rule weights six
months of 2026 above all of it. That is fix 4's whole content, and it is a trade rather than an
upgrade. `A-rotation`'s 10th-to-1st backtest swing has not gone away; under this rule it costs a
tie-break instead of a seat.

---

## 11. The defects log — D1 through D5

**Source:** `strategy-program/DEFECTS.md`. All four were found while running competition rounds, never
patched mid-round, and fixed between rounds; where a workaround exists in `strategy-program/tools/score.py`
it was kept after the fix because it derives from quantities correct under both the old and new
engine, preserving cross-round comparability.

- **D1 — `total_return` was rebased to the first session's close, not to starting equity.** Found
  round 1, fixed between rounds 1 and 2. The runner divided its whole equity curve by a constant
  (`starting_equity`) that then cancelled out of the ratio `equity[-1]/equity[0]`, silently rebasing
  every return to the mark on the first session's close instead of to the true starting point. This
  invalidated `total_return` (and `cagr`) for any card that filled on its first session — 14 card-window
  pairs in round 1 differed from the true `ending_equity/starting_equity − 1` by more than 0.05
  percentage points, and **two changed sign** (e.g. `A-rotation` in `covid`: reported −0.652%, true
  +0.465%). `max_drawdown`, `volatility` and per-bar returns were unaffected because the constant
  cancels harmlessly in those computations. Fixed by prepending the starting-equity point to the
  curve so it genuinely begins at 1.0.

- **D2 — `exposure` measured session presence, not capital at risk.** Found round 1, fixed between
  rounds 1 and 2 by adding a separate `capital_exposure` field rather than redefining `exposure`. A
  card holding one slot of four on every session reported `exposure = 1.0` — the fraction of *sessions*
  with any open position — with only a quarter of its capital actually deployed. This over-credited
  low-slot-utilization cards in the ranking metric, worst in falling windows where the credited term
  is negative: `c04-riskmanaged`'s naive adjusted excess in the GFC was +55.45% against a corrected
  +25.45% once capital-weighted exposure (43.83%, matching the author's own ~45% design-time estimate)
  replaced the raw 97.19% session-presence figure. `c03-breakout`'s GFC figure changed sign, +13.43% →
  −1.71%.

- **D3 — a concurrent reader was reported as an ordinary card failure.** Found during round 1 setup,
  fixed by making the bar store's three pure-read call sites use an in-memory DuckDB connection
  (verified: three concurrent readers now all succeed, where any two previously collided with an
  `IOException`). Before the fix, the store's default connection took a write lock even for reads, so
  a second process touching it during a tournament run failed with an error the runner recorded as an
  honest per-card `FAILED` and walked past — silently and indistinguishably from a legitimate
  eligibility refusal. This recurred in round 2 and cost an entire first attempt: a run launched
  detached, killed by killing the `python.exe` process rather than the bash loop driving it, so the
  loop spawned a replacement that fought a second run for five windows — **135 card-runs, zero
  results**, invisible at a glance because "0 run files, 27 FAILED lines" looks identical to a
  legitimately ineligible field. `run_round.sh` now refuses to start while another tournament process
  is alive.

- **D4 — indicator values depended on an arbitrary 400-day lookback that could flip a signal.** Found
  2026-08-21 while attempting a performance optimisation, not by reading the code. Every rule
  evaluation re-read a trailing 400-day window rather than full history — harmless for windowed
  indicators (`sma`) but a genuine, if tiny (~1.8e-5 relative error), seeding error for recursive ones
  (`ema`, Wilder `rsi`). Reproduction found exactly **one** signal flip across 244-of-246 checked
  round-2/round-3 runs: `TSM` on 2020-05-14, where `C-trend`'s `ema(20)`/`ema(50)` crossover was
  decided by that error margin. **Fixed** by adding `lookback_days=None` (full history) to
  `AsOfMarket.history`, and **all 330 committed run files across rounds 1–3 were re-run and
  overwritten.** Exactly **3 of 330 results moved**, all the same card/window (`C-trend` in `covid`,
  present in all three rounds), by **0.065 percentage points** of starting equity; `C-trend`'s covid
  excess moved +24.5% → +24.6%. No ranking, promotion, Pareto frontier or conclusion in any of the
  three round reports changed. The fix also unblocked a 4.5× performance gain in the desk's cold-load
  path (from evaluating each rule once per symbol rather than once per session).

---

## 12. Every card measured — status, discipline and range of results

Compiled from the round reports, `backend/app/paper/library/retired/README.md`, and
`backend/app/paperdesk/desk.py`'s `AGENT_IDS` block. "Best" and "worst" are the most extreme
adjusted-excess (or, for round 5, annualized adjusted-excess) figures found stated for that card in
any round document read for this report — not a recomputed statistic — and each is cited to the round
it came from. Several cards were measured in only one or two rounds; where discipline could not be
confirmed from the documents read, it is marked "per name."

| card | discipline | best result found | worst result found | status as of 2026-08-22 |
|---|---|---|---|---|
| `B-momentum` | momentum | +5.82%→+8.60% range varies by matrix; out-of-sample +20.98% adj. vs QQQ (r8 §2) | live −5.21% over 55 sessions (r6 §6) | **on paper desk** (`AGENT_IDS`) |
| `A-rotation` | pairs-rotation (r8 §3) | 1y ladder rank 1, +31.6% annualized (r5 §1); out-of-sample +24.28% adj. vs QQQ (r8) | live −12.77% over 55 sessions (r6 §6); 10y vs QQQ only +0.63% (r6 Gate A) | **on paper desk**; retired-then-reinstated (see retired README) |
| `c07-chop` | mean-reversion (r8 §3) | +6.00% (`chop-2015`, r2 §3) | zero trades, 55 & 127 live sessions (r6 §6.1, r7 §1) | **on paper desk** |
| `H-trend-diversified` | trend | +17.32% naive GFC-adjacent bear-2022 (pre-D2 correction, r1 §6) → +0.71% corrected | out-of-sample −5.49% adj. vs QQQ (r8 §3) | **on paper desk** |
| `ladder-qld-schd` | not a `StrategyCard` (drawdown-ladder specification, §13) | final version: GFC-era MAR 0.25, −55.0% max DD (DRAWDOWN-LADDER.md §6) | as-specified version: −72.7% max DD through 2008 (§3) | **on paper desk**, fifth/appended seat (`desk.py` `AGENT_IDS`) |
| `C-trend` | trend | +14.6% median (r3 §4); ranked 2nd of ranked cards round 3 | out-of-sample −6.02% adj. vs QQQ (r8 §3) | library `base/` (per `strategy-program/README.md`), **dropped from desk** at r6 |
| `B2-hold-90` | momentum (variant of B) | +19.4% at 1y ladder (r5 §1); +16.3% median round 3 | +0.75% median round 4; 10y within 0.45pt of base (r5 §2.2) | recommended retired (r4 §9), not yet in retired README as of documents read |
| `B3-concentrated` | momentum (variant of B) | out-of-sample +51.63% raw / +39.83% adj. vs QQQ (r7 §9.1, r8 §2) — **highest single out-of-sample figure in the programme** | 9th (of 15) at 6-month ladder rank (r5 §1) | in library; excluded from r8 desk by one-per-family rule despite winning its own ranking (r8 §6) |
| `B4-tight-stop` | momentum (variant of B) | +15.1% (5y ladder, r5 §1) | round-1 stop-outs roughly tripled base's, no fill-quality gain (r2 §10) | in library |
| `c14-riskmanaged-wide` | risk-managed | best worst-window & hit rate of round 3 (−1.0%, 75%, r3 §4) | −19.78% adjusted excess, round 4 (r4 §4); zero trades, 55 & 127 live sessions | dropped from desk at r7 (liveness gate); labelled hedge-leg-only, never rankable |
| `c20-rotation` | rotation/hedge | out-of-sample +5.30% raw (r7/r8 §2); +14.79-pt bear-vs-ladder swing, largest in programme (r5 §2.3) | last of 15 at every ladder horizon (r5 §1) | dropped from desk at r8 (discipline/one-per-group rule did not apply; excluded on Gate A fail per r8 §1 table's fail-list) |
| `c11-breakout` | breakout | +23.89-pt beat of SPY in bear-2022 on one trade (r2 §9, later read as absence not defence) | worst window −20.68% (r4 §2) | fails Gate A as of round 6/8 (r6 §1 table) |
| `c09-convex` | volatility (convex payoff) | reached Pareto frontier at 4th of 22 by Borda, round 2 | fails Gate A (r6/r8) | in library, unranked at long horizon |
| `c19-volatility` | volatility | +5.4% (1y ladder, r5 §1) | −7.35% bear-arm median vs +1.70% ladder — "worse in panics" (r5 §2.3); fails Gate A | in library |
| `c18-meanrev` | mean-reversion | **only card making money live at 55 sessions**, +2.44% (r6 §6) | fails Gate A both rounds (r6, r8) | in library; excluded r7 by overlap-cap collision with `c20-rotation` |
| `c21-uncorrelated` | (submitted as diversifier; correlation claim falsified, r4 §5) | +1.5% (3y ladder, r5 §1) | measured ρ = +0.907 to `B-momentum`, "falsified" (r4 §5) | fails Gate A |
| `A1-alpha-order` / `A2-cash-headroom` / `A3-no-target` / `A4-tight-stop` | pairs-rotation (variants of A) | `A4-tight-stop` +4.20% median, round 4 control arm (r4 §7) | negative medians both rounds where scored (r1, r2/retired README) | **retired**, dominated by own base on both matrices |
| `c01-meanrev` | mean-reversion | +4.00% adjusted excess, GFC (r1 §3) | near-zero median, dominated (+0.4%, retired README) | **retired** |
| `c02-volatility` | volatility | — | −1.3% median, hit 12% (retired README) | **retired** |
| `c03-breakout` | breakout | — | −3.1% median, hit 25%; GFC sign flip via D2 (+13.43%→−1.71%) | **retired** |
| `c04-riskmanaged` | risk-managed | +26.03%/+26.10% adjusted excess, GFC (r1 §3, r2 §2) | −1.5% median across rounds; ranked 18th of 19 round 1 despite GFC result | **retired** |
| `c05-trend` | trend | ancestor of `C-trend`; +24.6% adjusted excess, covid, post-D4 restatement | −0.07%/+0.2% near-zero median | superseded by `C-trend`, near-zero/dominated per retired README |
| `c06-13f-momentum` | momentum (13F-derived) | +17.79% vs +14.60% benchmark, **+10.99 adjusted** (r2 §7; round 1's +11.03 is superseded — see appendix) | unranked by construction in every other window (basket lookahead) | **retired**, provenance-constrained, standing worked example |
| `c08-generalist` | (generalist mandate) | best GFC adjusted excess of round 2, +19.20% | −0.6% median at 0.59 (highest) exposure | **retired** |
| `c10-momentum` | momentum | — | +0.4% near-zero median | **retired**, dominated |
| `D-13f-newbuys` | momentum (13F-derived) | prior tournament +56.93% vs +11.99% (unreproducible) | zero trades in every window, two consecutive rounds | **retired** |
| `E-asymmetric` | (payoff-shape) | +21.21% on `recent` alone | eligible in 1 of 8 windows | **retired**, invited back re-cut |
| `F-fastrev` | mean-reversion (fast) | — | eligible in 2 of 8 windows | **retired**, invited back re-cut |
| `G-volatility` | volatility | **+12.6% median across 3 windows** — "genuinely promising, genuinely unrankable" | eligible in 3 of 8 windows | **retired**, invited back re-cut on long-history universe |
| `B-wide` / `C-wide` | momentum / trend (index-derived, gated) | — | provenance-unranked on every window (`universe_knowable_from` 2026-03-31) | not carried past round 3, "did their job" |
| `c12-meanrev-wide` | mean-reversion | +55.3% raw GFC excess on **1 trade at 0.6% exposure** | −0.5% adjusted (D2-corrected) — "declined to attend" | **retired**, "not a strategy, a spectator" |
| `c13-breakout-wide` | breakout | best round-3 open-arm median, +10.4% (i.e. below round 2's best) | — | dropped, not carried (r4 §3) |
| `c15-volatility-wide` | volatility | +18.4% adjusted GFC excess — later shown to be survivorship, not skill | thesis "falsified": predicted GFC as worst window, it was best | **retired** on a falsified thesis |
| `c16-dispersion-wide` | (breadth experiment) | ρ = 0.245 mean pairwise correlation (deliberately low) | 7th of 10 despite the low correlation | **retired**; finding kept ("diversifying inside a card did not work") |
| `c17-defensive-trend-wide` | trend | — | −0.6% median, hit 38%; lost 9.0 pts of median to `C-trend` on identical entry rule | **retired** |
| `B1-with-target` | momentum (variant of B) | +4.6% median | beaten by B2/B3/B4 on median and hit rate | **retired**, dominated within family |

---

## 13. The drawdown ladder

**Source:** `strategy-program/DRAWDOWN-LADDER.md`.

This is a separate specification from the `StrategyCard` competition field above — a three-sleeve
tactical-allocation rule (hold SCHD, rotate into QLD at −10%/−20%/−30% S&P drawdowns from an all-time
high, halve QLD on a new high), tested by a dedicated backtester
(`strategy-program/tools/drawdown_ladder.py`) rather than run through the tournament engine.

**The headline finding:** the strategy exactly as originally specified — no bounce confirmation, no
reserve sleeve, no time or profit exit — reaches a **−72.7% maximum drawdown through the 2006-06 →
2011-10 crisis window**, worse than a static 60/40 blend (−69.5%) and far worse than the S&P index it
triggers on (SPY buy-and-hold: −56.5%) (§3). The mechanism: the ladder has no exit condition on
continued decline, so it accumulates maximum leverage (80% QLD) at the point of maximum subsequent
loss, and its only de-risking condition — a new all-time high — was more than four years away in 2008
(§3).

**What was tested and found not to fix it:** time stops actively *hurt* — cutting leverage after a
fixed number of sessions without a new high turned crisis-window CAGR negative, selling at the bottom
and missing the recovery (§4). Larger tranche sizes (25/75/100 vs. 20/60/80) scored better on
risk-adjusted return in every window and were explicitly **not adopted**, because the improvement was
identified as "more QLD did better in a period where QLD did well" rather than a genuine fix (§5).

**What did fix it:** requiring the index to close back above its own 50-session average before a rung
fires ("bounce confirmation") nearly tripled crisis MAR (0.06 → 0.17), and adding a genuine reserve
sleeve — IEF Treasuries, funded before SCHD — took crisis MAR to 0.25 at a 40% reserve weight, on a
surface the report describes as "smooth across 30–50%, not a knife edge" (§4). A reserve sleeve had
been part of the original three-ticker sketch (QLD/SCHD/SGOV) and was dropped from the written
specification that was actually tested.

**The final, tested version** (§6): 60% SCHD / 40% IEF, signal SPY drawdown from all-time high, rungs
−10%→20% QLD / −20%→60% / −30%→80%, funded from IEF then SCHD, a rung fires only above the 50-session
average, halve QLD on new high, full exit at +10% above the cycle's starting high or 60 sessions after
the new high (whichever first). Result over 2006-06 → 2011-10: CAGR +13.70%, max drawdown **−55.0%**,
MAR 0.25 — against the as-specified version's +4.49% CAGR, −72.7% max drawdown, MAR 0.06. Turnover
roughly halved (14 rotations over 20 years vs. 27).

**What it is explicitly not** (§7): it does not beat QLD buy-and-hold on return (13.95% vs. QLD's
24.50% over 20 years) or on MAR (0.25 vs. QLD's 0.29) — it trades return for a −55.0%-vs.−84.0%
drawdown. The sample is two crises in twenty years; the 2006–2011 test substitutes SPY for SCHD, which
did not yet exist; and **every window in the analysis is in-sample** — the specification was written
with knowledge of these periods, and "nothing here is a forward test" (§7).

This specification, under the id `ladder-qld-schd`, is the fifth seat on the live paper desk —
appended after round 8's four rule-based cards rather than competing for one of their slots, because
it is "a different card *shape*" not scored against the same `StrategyCard` gates
(`backend/app/paperdesk/desk.py`, `AGENT_IDS` docstring).

---

## 14. What the programme has and has not established

Stated bluntly, per the instruction to be blunt.

**Established:**
- A deterministic-engine promotion rule that treats re-scoring frozen cards on old windows as new
  evidence double-counts a single measurement (round 2, §3 above).
- Verdicts about which cards are best, which are hedges, and which are diversifiers are conditional on
  the window matrix's regime mix — proven twice, by round 4 against round 3 and by round 5's bear arm
  against its own ladder.
- Two real engine defects (D1, D2) materially changed reported returns, including sign flips, before
  being fixed; a third (D3) cost real compute twice through operational error; a fourth (D4) was
  present in every published figure in the programme for its first eleven days and moved exactly three
  results by 0.065 points when corrected.
- The one out-of-sample record the programme has (127 sessions, 2026-02-17 → 2026-08-18) shows a
  *positive* Spearman correlation between round 5's ladder rank and forward result (+0.625 raw,
  +0.536 adjusted) — this is the only forward confirmation of any ranking the programme has produced,
  and it arrived only after a shorter, negative-correlation slice (55 sessions, ρ = −0.539) was
  withdrawn as an artifact.

**Not established, and the programme's own documents say so:**
- **Nothing is out of sample except that single 127-session forward window.** Every backtested figure
  in rounds 1–8, including every 5-year and 10-year "long-horizon" number, ends on or before the
  2026-02-13 design cutoff (`strategy-program/ROUND-5-PLAN.md` §5, restated in every round-5-onward
  document's closing caveats).
- **Every card's universe was chosen by an analyst writing in 2026.** The programme's own
  survivorship/provenance gate (`universe_knowable_from`) only fires on a universe *mechanically*
  derived from a current index-constituent list; a thesis-picked basket of the semiconductor names
  that happened to win is not caught by it, and is explicitly flagged as an unmeasured upper bound on
  every long-horizon figure (`data/rounds/r5-2026-08/REPORT.md` §4).
- **The noise floor is ±21.2 points, from universe ordering alone** — re-running one identical card
  under twelve different universe orderings moved its three-year return across a 53.9-point spread,
  standard deviation 21.2 points (`strategy-program/PROTOCOL.md` §7, restated in
  `strategy-program/ROUND-6-PLAN.md` §2). Every promotion and demotion decision in this programme is
  required to be checked against that floor, and several early ones (documented above) were not, until
  corrected.
- **The single out-of-sample confirmation is one window, 127 sessions, one era** — not a distribution.
  Round 7 itself withdraws a conclusion drawn from a 55-session slice of the same period and states the
  general lesson: a forward window shorter than roughly one full cycle should be reported as an
  observation, never as a correlation (`data/rounds/r7-2026-08/SELECTION.md` §9.4).
- **The desk's selection has changed its own rule twice in three rounds** (correlation-and-overlap
  caps in rounds 6–7, replaced by a discipline/family distinctness rule in round 8), and round 8's own
  closing section flags that the discipline axis may be excluding a genuinely diversifying pair
  (`C-trend` vs. `H-trend-diversified`) that no overlap or correlation measure would have flagged
  (`data/rounds/r8-2026-08/SELECTION.md` §4).

---

## 15. Open questions and what should happen next

Compiled from the "for round 9" / "what changes for round N+1" sections of rounds 4, 5, 6, 7 and 8,
which are the programme's own standing to-do list:

1. **Fix 4 was implemented in round 11 (§10.2) — at 127 sessions, half the ~250 this item
   specifies.** Round 7 deferred it until the desk reached ~250 sessions, "around mid-2027"; round 11
   ran it on request at half that. The call is defensible — round 10 showed the cost of having no
   live-evidence rule at all — but it is a departure from a standard the programme set for itself, and
   `strategy-program/ROUND-11-PLAN.md` §4 listed what fix 4 gives up without mentioning it. **Any round-11 seat decided
   by a margin smaller than the gap between two sub-periods should be read as provisional**, which
   covers the entire `B`-variant tie. What remains open is narrower than the original item: the live
   matrix is one environment and only time makes it multi-regime, so the backtest matrices stay
   reported beside it — as floors and a tie-break, which is what round 11 does rather than discarding
   them.
2. **Whether `StrategyCard.discipline` is the right distinctness axis for desk selection is
   unresolved** — round 8 names the specific pairing (`C-trend`/`H-trend-diversified`) it may be
   wrongly excluding and proposes a "kind of holding" rule as a separately pre-registerable
   alternative (`data/rounds/r8-2026-08/SELECTION.md` §4, "For whoever runs round 9" item 2).
3. **Benchmark anchoring needs to be stated explicitly wherever a SPY or QQQ figure crosses a round
   boundary** — round 8's own numbers differ from round 6's and round 7's by up to 0.124 annualized
   points and up to 0.45 percentage points respectively, for a reason (session-traded vs. calendar-date
   pricing) documented independently in round 5 and rediscovered in round 8
   (`data/rounds/r8-2026-08/SELECTION.md` §1, §2, "For whoever runs round 9" item 3).
4. **The take-profit/max-hold-days axis (the B-family variant question) is closed** on the programme's
   own recommendation — three tests across three rounds, no version beat the base twice, and round 5
   showed the whole axis is unmeasurable at the desk's actual (multi-year) horizon
   (`data/rounds/r4-2026-08/REPORT.md` §9 item 2, `data/rounds/r5-2026-08/REPORT.md` §2.2).
5. **`G-volatility`, `E-asymmetric` and `F-fastrev` remain explicit standing invitations** to
   resubmit re-cut on a longer-history universe — the store now carries 380 symbols reaching 2004
   against the 86 available when they were designed and retired
   (`backend/app/paper/library/retired/README.md`).
6. **The momentum-seat override (round 8 §6) is flagged by its own author as something that should
   become a rule rather than remain a standing override** — either a rank-stability gate or a ranking
   on the 5y/10y ladder rungs, pre-registered before the next round's numbers exist
   (`data/rounds/r8-2026-08/SELECTION.md` §6, closing paragraph). **Done in round 9** — and the rule
   it produced is itself now being replaced for round 10; see §10.
7. **Rounds 9 and 10 are done, and item 1 is now the binding one** (§10, §10.1). Round 10 dropped
   `A-rotation` — the desk's best live performer, +65.18% — on backtest dispersion while a
   127-session live record said the opposite, and the programme has no rule for resolving that. Every
   previous round could defer fix 4 as a refinement; this is the first round where it would have
   changed a seat.
8. **New candidates, not new thresholds** (round 10, "For whoever runs round 11"). Eight cards clear
   Gate A and six of the eight are variants of two base cards, so after distinctness there were never
   more than about four separate ideas to seat. `strategy-program/ROTH-MOMENTUM.md` and
   `strategy-program/ROTH-VOLTARGET.md` hold the only genuinely new ideas since round 5 and neither
   has been through a gate; they need an execution path or an explicit decision to seat them unranked
   the way `ladder-qld-schd` is.

---

## Appendix — figures found stated inconsistently across the round documents

These are the specific numeric disagreements found while compiling this report between documents that
each present themselves as reporting the same measurement. In every case below, both figures are
reproduced from the source files rather than one being silently preferred.

1. **The 13F card's one legal-window adjusted excess.** `data/rounds/r1-2026-08/REPORT.md` §5: "+3.19
   points raw, **+11.03 adjusted**, on 56 trades at **46.3%** capital exposure." `data/rounds/r2-2026-08/REPORT.md`
   §7: "+3.19 raw, **+10.99 adjusted**, 56 trades at **46.6%** capital exposure" — introduced in the
   same sentence as "**the same number round 1 produced (+11.03)**, recomputed." The two reports thus
   disagree with each other by 0.04 points on the adjusted-excess figure and by 0.3 points on capital
   exposure, for a card both explicitly describe as producing an identical, unchanged recomputation on
   the identical window.

   **Resolved, 2026-08-22.** The two run files are byte-identical --
   `data/rounds/r1-2026-08/results/13f-legal/runs/r1-c06-13f-momentum.json` and its round-2 twin both
   record 188 sessions, a +17.7865% return, 56 trades, a +14.5961% benchmark and a capital exposure of
   **0.4656969840**. So no measurement changed. What differs is only the arithmetic each report did on
   top of it:

   * `17.7865 - 0.4657 x 14.5961 = +10.99` -- round 2, correct
   * `17.7865 - 0.463  x 14.5961 = +11.03` -- round 1, computed from a rounded 46.3% exposure

   **Round 2's number is right; round 2's claim is wrong.** It is not "the same number round 1
   produced" -- it is the corrected one, and describing a correction as a reproduction is the part
   worth fixing. Round 1's +11.03 should be read as superseded. Nothing else in either round depends
   on it: `c06-13f-momentum` is provenance-constrained to a single window and has never been ranked.

2. **Round 5/10-year and 5-year adjusted-excess figures for the Gate-A survivors, between round 6 and
   round 8.** Round 6 (`data/rounds/r6-2026-08/SELECTION.md` §1) reports `B-momentum` at 5y-SPY
   +14.79%; round 8 (`data/rounds/r8-2026-08/SELECTION.md` §1) recomputing "not copied from any prior
   round's document" reports the same cell at **+14.87%**. `B4-tight-stop` 5y-SPY: round 6 **+15.04%**
   vs. round 8 **+15.12%**. Round 8 itself identifies and explains the discrepancy (session-traded vs.
   calendar-date SPY pricing, max 0.124-point difference on these cells) rather than treating it as an
   error, and states every QQQ figure between the two rounds matches exactly.

3. **The 2026-02-17→2026-08-18 out-of-sample benchmark returns, across round 7 and round 8.** Round 7
   (`data/rounds/r7-2026-08/SELECTION.md` §9.1) states SPY +12.84%, QQQ +19.20% for this window. Round
   8 (`data/rounds/r8-2026-08/SELECTION.md` §2), re-running the tournament fresh rather than reading
   round 7's figures, states SPY **+12.39%**, QQQ **+19.33%** for the identical window, and further
   notes a third value, SPY +12.57%, from anchoring the same window to the 2026-02-13 close instead of
   2026-02-17. Round 8's own text: "That is not a data change... it is three anchors for one period.
   Each is defensible; none is a revision of another." The downstream per-card adjusted-excess figures
   for this window accordingly differ slightly between the two documents — e.g. `B-momentum` adj. vs.
   SPY: **+24.67%** (r7 §9.1) vs. **+24.93%** (r8 §2); adj. vs. QQQ: **+21.06%** (r7) vs. **+20.98%**
   (r8).

4. **The Spearman correlation between backtest rank and live/forward result, within round 7 itself.**
   Reported first (round 6 §6, restated at the top of round 7) as **−0.539** on a 55-session live
   slice; corrected in round 7 §9.1 to **+0.625** (raw return) / **+0.536** (adjusted excess) on the
   full 127-session out-of-sample window — an explicit sign reversal the document itself performs and
   labels a withdrawal, not a data revision, but it is the most consequential number in the programme
   to have been stated both ways and is repeated here so a reader encountering round 6's or the
   uncorrected part of round 7's text in isolation does not take −0.539 as current.

No other numeric disagreement of this kind was found between documents purporting to state the same
measurement; the many other instances of "round N's number changed in round N+1" documented in §2–§9
above are the programme's deliberate re-measurements on new windows, not restatements of the same
measurement, and are not counted here as inconsistencies.

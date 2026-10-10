# Everything Investigated — Complete Research & Effectiveness Report

*Compiled 2026-09-01. Covers the strategy-competition programme (rounds 1–33), the discovery/selector
study, the evolution loop, the Agent Desk / Agent Workflow studies, and the Round 33 dynamic-universe
work through today. Not investment advice.*

---

## 0. Bottom line

Across **33 pre-registered rounds**, ~50 distinct strategy concepts, a **9,480-cell** timeframe sweep,
a **291-generation / 2,944-evaluation** evolution loop, a survivorship-aware discovery study, and a
purpose-built agent-research desk, **this programme has not found a durable, out-of-sample edge on
price-only OHLCV data.** That is the headline, and every part of this report is consistent with it.

The only positive statistical survivors ever found are, honestly labelled:

1. **A beta premium, not alpha** (round 29): high-volatility names predict high forward *relative*
   return, but the effect is symmetric across up/down markets (IC +0.167 up, −0.140 down) — capturable
   with a high-beta ETF, not the cross-symbol machinery it would have justified. The decision rule
   **declined** it.
2. **A drawdown-reducing allocation** (`ladder-qld-schd`): CAGR +13.70%, max drawdown −55.0%, MAR 0.25
   — a real product (roughly half the drawdown at two-thirds the return), but **entirely in-sample**,
   never forward-tested, and it does not beat buy-and-hold on return or MAR.
3. **3 of 9,480 timeframe-sweep cells** and a **core-CPI near-miss** (round 31, q=0.139) that
   **collapsed out-of-sample** (round 32, p=0.51 on 1970–1992 data).

**The new question this session opened** — does *dynamically choosing which tickers to research* help
the agent-research desk (Round 33 Phase B) — **is not yet answerable.** No researched (gated) candidate
data exists: the effectiveness gate has `passed_n = 0` for every gate. What exists today is a
**deterministic backfill** of the null (raw-signal) arm and its candidate log; the researched arms
accrue live going forward.

---

## 1. The strategy-competition programme (rounds 1–32)

**Scoring.** Every round ranks on the **median exposure-adjusted excess return** across eligible
windows: `adjusted_excess = strategy_return − capital_exposure × benchmark_return`, `rank_key =
median(adjusted_excess)`. The metric exists to attack the prior tournament's two failures — rank
instability (Spearman ρ = **0.162** in-sample→OOS) and exposure-driven returns (exposure/return
ρ = **0.648**). Capital exposure is reconstructed per session from the trade log.

**The noise floor.** Re-running one identical card under twelve `universe` orderings spread its
three-year return across a **53.9-point range, σ = 21.2 points**. **21.2pp is the programme's noise
floor**: any margin smaller than it is not evidence. Round 17 later showed this floor is *conservative*
for a nine-ETF design (shrinks toward ~1pp there), but no round has produced a corrected margin that
clears it as a durable edge.

**Verdicts are conditional on the window mix.** Round 4 falsified round 3's conclusions simply by
changing the window matrix (between-card correlation flipped ρ = +0.04 → −0.554). At least four
distinct window matrices exist; round 4's own heading: *"Round 3's conclusions were properties of
round 3's windows."*

### Rounds 1–11 (from `PROGRAMME-REPORT.md`)

| Round | What it established |
|---|---|
| 1 | Ordering-artifact control alone produced a +6.47pp gap; defects D1 (return rebasing sign-flips) and D2 (exposure = session presence, not capital) found. |
| 2 | Two-consecutive-rounds promotion double-counts identical re-scored windows (20/20 bit-identical); exposure/adjusted-excess r=+0.797 in the GFC; a mechanical rule would have wrongly promoted on 5.62/4.15pt margins (inside the floor). |
| 3 | **No detectable breadth effect** (all inside the 53.9pt floor); a combined book looked good at ρ=+0.04. |
| 4 | **Falsified round 3's combined book** (correlation flipped to −0.554); retired `A-rotation` would have ranked 2nd on this matrix → reinstated. Regime-conditional, not structural. |
| 5 | **Horizon finding**: best annualized return falls **+31.6% (1y) → +7.6% (10y)**, same cards. QQQ vs SPY roughly halves the field at 10y. No decade-length window is ever falling. |
| 6 | Live desk over 55 sessions **contradicted every backtest conclusion**: the ladder's rank-1 card (`A-rotation`) finished last live (−12.77%); rank-8 `c18-meanrev` was the only live winner. |
| 7 | The −0.539 live/ladder correlation was withdrawn as a 55-session slice artifact; on 127 sessions Spearman is **+0.625/+0.536**. Round 7's own picks underperformed OOS. |
| 8–10 | Four different selection rules in four rounds each dropped `A-rotation` (the best live performer) for a different stated reason; **owner overrode twice**. Trend seat decided by 0.22pt ("far inside the noise floor"). |
| 11 | Scored the **live desk itself** (Gate C): 3 seats — `B3-concentrated` (+7.41%), `A-rotation` (+3.47%), `C-trend` (+1.81%). Vindicated the round-10 override; reversed the round-8 override. |

### Rounds 12–18 — the factorial / consolidation era

Consolidated in `00-EVERYTHING-TESTED.md`. Round 17 (48-cell factorial: 8 rule forms × regime filter ×
3 bracket policies): **form marginal 7.56pp, regime filter 0.26pp, brackets 0.14pp — all inside the
21.2pp floor.** The whole 48-cell field spanned 9.47pp vs a pure-noise expectation of 94.8pp. Round 18
(exit discrimination): exit marginal **3.58pp**; two of eight "different" exits were byte-identical.
Consolidated verdict across ~865 lab cells and the 9,480-cell timeframe sweep: **essentially nothing
survived correction** (1 positive cell in 9,480, and it graded q=1.0).

### Rounds 19–32 — engine repair, the macro line, the cross-symbol line, the thesis audit

| Round | Question | Verdict |
|---|---|---|
| 19–20 | Settlement lag & engine defect D8 (unfunded buys) | D8 fixed; rejections 59→3; harness is +0.06% optimistic, not "systematically" so (original headline withdrawn). |
| 21 | First macro gate (`T10Y2Y > 0`) | **Not askable** — equity-regime windows barely inverted; 24/32 pairs byte-identical. Engine capability validated. |
| 22 | Macro gate on truly-inverted windows | **Null, 3/3.** The programme's first genuine macro null. |
| 23 | Curve as a sizing tilt | **Null, 3/3** (an "outside" verdict was a null-construction artifact, corrected). |
| 24 | 6-month hold-cap cost | Both cards inside the floor (−5.07pp / −0.19pp); wrong-lever headline withdrawn. |
| 25 | Curve rate-of-change | **Null, 3/3.** "Macro line exhausted at the level of shape." |
| 26–27 | The 4 seated cards' own falsification clauses & thesis statistics | Mechanisms real, **magnitudes inside the floor**. `C-trend`'s exclusion claim **wrong-signed** (excluded names +19.89% vs kept +6.93%). |
| 28 | Cross-sectional rank IC, concentrated universes | **0/20 survive BH** (one apparent survivor was a window-overlap artifact). |
| 29 | Same test, diversified universe | **2 survivors (`vol_60`)** — but it's the **beta premium**, not alpha. Decision rule declines. **Cross-symbol line closes.** |
| 30 | 3 daily macro series | **0/24 survive BH**; orthogonality control shows the nulls are price-independent noise. |
| 31 | 3 monthly inflation indices | **0/24 survive BH** (best q=0.139) — a genuine near-miss (core CPI level → SPY, p=0.009). |
| 32 | OOS test of the near-miss (1970–1992) | **Collapses to p=0.51 OOS.** No card. **Macro line fully closed** (all 7 FRED series null). |

**Three classes of "never tested"** (from `00-EVERYTHING-TESTED.md` §3): (a) *inexpressible by the
engine* — no cross-sectional ranking / cross-symbol regime gate, which forecloses pairs, relative
strength, dispersion, and inverse-vol risk parity as a class (pairs-rotation was the evolution loop's
single most common discipline label — 348/934 legacy genomes — yet permanently unreachable); (b) *data
collected but unreachable* — Fear & Greed, event calendar, 13F consensus (FRED became reachable in
round 21); (c) *designed but never run* — a cash-aware contribution harness, synthetic history, and 12
dividend/duration tickers that return empty from the bar store.

**The evolution loop:** reached generation 1935 (291 generation directories, 289 scored), 2,944 ledger
evaluations across 2,371 distinct genomes — no durable edge; its promotions cluster into roughly one
rule family.

---

## 2. The discovery / selector study (`DISCOVERY.md`)

**Question:** could a rule on contemporaneous data have found the next sector theme, without
survivorship bias? **Answer:** it surfaces the themes (semis 2004/2015/2020, solar 2014/2020, uranium
2022) years early — the 2020 pick returned **+68.2% net excess** — **but has no measurable ranking
skill.** Across 272 monthly cross-sections, `mom12_1` IC = **−0.0073 (bootstrap p = 0.892)**; the sign
flips between eras (−0.064 → +0.099); net excess across 23 theme trials is mean +3.98% / **median
+0.09%** with SD 22.39% — "a fat-tailed coin flip," an order of magnitude inside the 21.2pp floor.
Nothing survives BH (best q=0.186). Round 28 confirmed the same IC≈0 on single names.

**The programme's own conclusion:** "the asymmetry a discovery system needs has to come from exits and
risk control, not from better ranking."

---

## 3. The Agent Desk & Agent Workflow studies

**Architecture.** Three desks on one wire contract: **Trading Agents** (single-ticker analyst→debate→
trader→risk pipeline, `final_rating`), **Vibe Trading** (preset role-agent DAG, `VERDICT`), and
**Agent Workflow** (the orchestrator: regime → strategy select → candidate scan → child TA/Vibe research
→ entry plan → stage next-open orders onto a persistent paper book).

**The pre-registered 4-arm study** (`WORKFLOW-STUDY-PLAN.md`) asks: *does gating a strategy's entry
signals on model research beat taking every signal?* Four arms share everything but the gate:
`raw_signal` (null), `ta_gated` (Buy/Overweight), `vibe_gated` (SUPPORT), `full_workflow` (the chain).
Primary metric `adjusted_excess`; the **discrimination test** (passed vs refused forward returns at
h=21 sessions, BH m=3) is "the powered instrument." **Decision rule:** effective only if *both*
`full_workflow` beats `raw_signal` at paired-bootstrap p ≤ 0.10 **and** the discrimination test clears
q ≤ 0.10. **Floor: 60 sessions and 40 gated candidates before the rule is evaluated at all.**

**The power analysis is the load-bearing finding here.** At the pre-registered 40-candidate minimum,
detecting an effect at 80% power needs a **~35-percentage-point** hit-rate gap between passed and
refused sets — versus a programme base rate of "1 positive cell in 9,480." Power stays under 0.7 for a
10pp effect until **~n=400**. At the desk's historical firing rate (**0.101 gated candidates/session**),
the 40-candidate bar was **1.5–3.5 years away**. In plain terms: *the 4-arm study, as originally
specified, was structurally too slow and too underpowered to ever measure what it set out to.* (Round
33's relaxed entry, §5, is the direct response.)

**Monitoring reports (explicitly not evidence, n≈1):** a 753-session **regime backtest** (regime mix
53.5% risk-on / 30.8% risk-off / 15.1% high-vol / 0.5% chop; three of four primary cards did *worse*
in their target regime than out); a **decision-attribution** report (gate concordance n=1); and a
**prompt-compression** run confirming ~27% output-token savings on Haiku with identical decisions
(now the committed default).

---

## 4. Round 33 — dynamic ticker selection (this session)

The Agent Workflow desk previously scanned a fixed ≤12-ticker `card.universe`. Round 33 lets the
pipeline **choose which tickers to research dynamically**, since costly LLM research should point only
where it's warranted.

### Phase A — the selector bake-off ($0 LLM spend), committed and run

Eight deterministic selectors (six real + two controls) graded on bootstrapped IC vs the candidate
pool's own equal weight, over a walk-forward split (in-sample 2004-12-28 → 2017-12-29, 3,276 sessions;
held-out 2018 → 2026, 2,168 sessions), with a **frozen, mechanical §7 gate**.

**Result — `mom12_1_hysteresis` promoted** (branch 2: lowest shortlist churn, 0.037/session, among the
six entrants not statistically worse than either control). It posted a *small, individually-significant*
in-sample IC (**+0.0398, bootstrap p = 0.016**) — which technically **refutes the pre-registered
prediction** that it would be indistinguishable from zero — but it **does not survive multiple-comparison
correction** (BH q = 0.126, no entrant clears q ≤ 0.10) and **does not replicate out of sample**
(held-out IC +0.0284, p = 0.105). The programme's signature pattern held once more: a marginal
in-sample signal that clears neither correction nor OOS.

Two disclosed artifacts: `control_card_universe` has an undefined IC (it "picks" its whole universe, so
branch 1 was structurally unreachable and the round always resolves on branch 2); and the regime
instrument was 3-signal (no historical Fear & Greed feed), a weaker instrument than the live 4-signal
desk.

### Phase B — live-forward study, built this session

- New deterministic **`universe_select` pipeline stage** + `resolve_universe` (screen mode swaps the
  card's universe for the promoted selector's shortlist; card mode is byte-for-byte unchanged).
- **A critical routing bug was caught and fixed before it could do damage:** `_stage_orders` and the
  gate reads defaulted to the *card* books, so a screen run would have overwritten the in-flight
  4-arm study's books. Now keyed by `(arm, universe_source)`; screen books live under
  `book/screen/<arm>.json`.
- **Live hysteresis wiring** (the deferred item) completed — the promoted selector's low churn depends
  on it.
- **Shortlist widened to `screen_top_n = 10`** (owner decision, for accrual) — the selector's top_n and
  hysteresis bands scale together; live-confirmed 3 → 9 symbols (10 requested, 9 after correlation
  collapse).
- **A less-restrictive screen-mode entry** (owner decision): a trending *state*
  `close > sma(200) and ema(20) > ema(50)` replaces the card's crossover *event*, because the event
  fired only ~2×/month even at 10 symbols (≈20 months to the 40-candidate floor). Configurable and
  validated; card mode untouched.
- **Daily cadence:** `run_phase_b_step` (fill screen books + launch the screened decision) driven by a
  Windows scheduled task (`Round33-PhaseB-Daily`, weekdays 17:00), isolated from the running card
  autopilot.
- **Agent worker model defaulted to Haiku 4.5** across the desks (selectable per run), for these
  high-volume research runs.

### The backfill

The last 21 sessions were replayed through the real pipeline with research **starved** (budget below
one child → the budget backstop skips every launch): **zero spend, zero look-ahead.** *Zero look-ahead
matters because the research evidence layer reads current news with no as-of gate* — so backdated
*research* is invalid, and only the price-only deterministic path (regime/selector/entry/raw staging)
can be backfilled honestly. The gated arms accrue live, where the news is contemporaneous.

- With the card's crossover entry: **2 candidates** in 21 sessions.
- With the relaxed trending-state entry: **132 candidate observations** (10 distinct symbols, 21 dates;
  27 with resolved 21-session forward returns), and the raw null-arm book holds 5 positions (117
  mandate-rejected — the raw arm buys everything; the book caps at 8 positions).

---

## 5. Effectiveness measurement — as of 2026-09-01

Run via `app.workflow.study.build_study(universe_source="screen")` and the candidate log.

**The gate's effectiveness is not yet measurable.** Every candidate in the backfill was research-skipped
(deliberately, `budget_exhausted`), so the discrimination test has **`passed_n = 0` for all three gates**
(`ta_gated`, `vibe_gated`, `full_workflow`) — there is no gated set to compare against the refused set.
`mean_diff`, `p_value`, `q_value` are all `None`.

**Correction, later on 2026-09-01.** The first draft of this section reported the paired comparison as
`mean_daily_diff = 0, bootstrap_p = None` and "both screen books score all-zero on returns". That zero was a
**defect, not a measurement**: `app.workflow.book.snapshot_equity` — the only writer of a book's equity
curve — was never called by any fill path, so every workflow book (all four card books and both screen
books) had an empty curve, `build_study`'s window was `None`, and every arm metric the 4-arm study had
*ever* reported was structurally zero. Fixed the same day (`book.mark_equity_through`, wired into the Phase
B step, the autopilot loop and `POST /book/execute`; curves backfilled from each book's own fill history).
Re-scored on the real screen books: `raw_signal` **+5.12% total return, +4.60% adjusted excess, 95% exposure,
5 trades**; `full_workflow` a flat cash line (it never traded — every candidate was research-starved);
paired diff −0.23%/day, bootstrap p = 0.27. Still below floor; still monitoring, not evidence. The repeatable
report is `strategy-program/tools/phase_b_report.py` → `data/rounds/r33-2026-08/PHASE-B-REPORT.md`.

| Measurement | Value | Reading |
|---|---|---|
| Screen candidate observations | **132** (10 symbols, 21 dates) | The candidate universe log — the study instrument. |
| — with resolved forward return | 27 (mean **+7.84%** over 21 sessions, hit-rate **0.889**, range −11.2%…+23.0%; corrected 2026-09-01 — an earlier draft printed the fraction 0.078 as "0.078%") | Descriptive of the *shortlist's* forward returns in a month when biotech ETFs ran hard (XBI, ARKG, IBB), **not** a gate comparison. |
| Gate discrimination (each gate) | passed_n = **0**, refused_n = 27 | **Gate effectiveness unmeasurable** — no researched candidates yet. |
| Paired `full_workflow` − `raw_signal` | −0.23%/day, bootstrap p = 0.27 (after the equity-curve fix; the draft's "0 / None" was the defect) | `full_workflow` never traded, so this is "raw shortlist buys vs cash" in a strong month — not a gate result. |
| vs the 60-session / 40-candidate floor | 21 sessions, 0 *gated* candidates | Below floor. Monitoring, not evidence. |

**What is genuinely measured elsewhere:** the *selector's* effectiveness (Phase A: IC +0.0398
in-sample, fails BH q=0.126 and OOS p=0.105 — a null in the programme's terms), and the *study's power*
(needs ~35pp to detect at n=40). The relaxed entry has moved the candidate-arrival rate from ~0.1/session
to ~6/session, so the **40-candidate floor is now ~1 month away rather than 1.5–3.5 years** — but with
only 10 distinct symbols across 132 observations, the *effective independent* sample is far smaller than
132, so the power gain is real but smaller than the raw count suggests.

---

## 6. What is established, and what is not

**Established.**
- No durable, OOS, price-only edge across 33 rounds, the evolution loop, and the discovery study.
- The two measured "structural products": a beta premium (declined as not-alpha) and a
  drawdown-reducing allocation (in-sample only).
- The programme's own instruments are sound and self-correcting: an explicit 21.2pp noise floor, BH
  correction across every cell tried, walk-forward/OOS discipline, and a documented defect log (D1–D8)
  where each defect that mattered was caught and quantified.
- The Agent Workflow 4-arm study is **structurally underpowered** at its own pre-registered floor.

**Not established (open or unmeasurable).**
- **Whether research-gating adds value** (the 4-arm study's core question) — no gated data has ever
  cleared the floor; `passed_n = 0` today.
- **Whether dynamic ticker selection helps** (Phase B) — pending live gated accrual.
- Anything requiring cross-symbol expressiveness (pairs, relative strength, inverse-vol parity) — a
  permanent engine limitation, not a measured null.
- Live/forward performance of anything — the single 127-session Spearman +0.625/+0.536 is the only
  forward confirmation the programme has, and it is about rank stability, not alpha.

---

## 7. Open lines & recommendations

1. **Let Phase B accrue.** The relaxed entry + `screen_top_n=10` should reach the 40-candidate floor in
   ~1 month of live weekday runs; the discrimination test becomes evaluable then. Watch
   `data/round33/phase_b_daily.log` and re-run `build_study(universe_source="screen")`.
2. **Treat the 132-observation figure with its overlap caveat.** Only 10 distinct symbols; the effective
   independent sample is closer to those names than to 132. Consider widening the candidate pool or
   diversifying the shortlist if independent power is the goal.
3. **The macro and cross-symbol lines are closed.** Further price-only rule search on these universes is
   very likely to keep returning nulls inside the 21.2pp floor — the programme's own recommendation is
   to stop mining ranking and focus on exits/risk control, or on capabilities the engine cannot yet
   express (which is a build, not a study).
4. **The honest framing for any live adoption:** per the r21 posture, seating the promoted selector (or
   any gate) into the live default is an **owner judgment**, not a mechanical promotion — and the
   evidence to date does not compel it.

---

## Appendix — sources

`docs/research/programme/00-EVERYTHING-TESTED.md` (rounds 1–32 consolidation) · `data/rounds/PROGRAMME-REPORT.md`
(rounds 1–11) · `strategy-program/PROTOCOL.md` · `strategy-program/DISCOVERY.md` ·
`strategy-program/ROUND-{19..32}-*.md` + `data/rounds/r{19..32}-2026-08/` · `docs/AGENT-DESK-CONTRACT.md` ·
`docs/WORKFLOW-STUDY-PLAN.md` · `docs/reports/workflow-study-power-analysis.md` ·
`docs/reports/{regime-backtest,decision-attribution,prompt-compression-run-2026-08-31}.md` ·
`strategy-program/ROUND-33-PLAN.md` + `data/rounds/r33-2026-08/PHASE-A-REPORT.md` ·
`docs/WORKFLOW-UNIVERSE-{STUDY-PLAN,BUILD-SPEC}.md` · `docs/WORKFLOW-RESEARCH-SPEND-SPEC.md` ·
live `build_study(universe_source="screen")` + candidate-observation log, measured 2026-09-01.

*Note: several committed docs (the power-analysis report's "three runs", the contract's "universe_select
not built" build-status note) predate this session; this report reflects the current state
(`universe_select` built, screen books populated, 132 backfilled observations).*

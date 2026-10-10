# Dynamic Ticker Selection Round — Design Draft

**Status: DESIGN LOCKED, then BUILT.** Phase A ran; Phase B shipped and is live.
**Build status (2026-09-01):** BUILT — commits d75792b (feature), be6b67b (hysteresis),
679272d (book routing), e35c967 (screen_top_n), bc5f178/ce4006b (daily step), 865de91
(backfill), 106ba5f (screen_entry_rule). Sections below are the pre-build design and are
kept verbatim as the pre-registration; where they say "not built"/"flagged, not built", see
`docs/AGENT-DESK-CONTRACT.md` for the current surface.

Drafted 2026-08-31 from a four-track design study (funnel architecture, selector
catalogue, research-spend policy, competition structure); owner locked all six open
decisions the same day. This is now the INDEX document. The frozen detail lives in
four children, and where they disagree with this file, THEY win:

| Document | Covers |
|---|---|
| `strategy-program/ROUND-33-PLAN.md` | Phase A pre-registration: 8 frozen entrants, grading, A→B gate |
| `docs/WORKFLOW-UNIVERSE-STUDY-PLAN.md` | Phase B pre-registration: live arms, metrics, decision rule |
| `docs/WORKFLOW-UNIVERSE-BUILD-SPEC.md` | Build spec: `universe_select` stage, config, contract, tests |
| `docs/WORKFLOW-RESEARCH-SPEND-SPEC.md` | Build spec: necessity gates, verdict cache, budgets, accounting |

Nothing here was pre-registered until the frozen parameters were COMMITTED before any
measurement runs (PROTOCOL.md §2 integrity boundary) — see `docs/reports/EVERYTHING-INVESTIGATED-2026-09-01.md`
§4-5 for what has since been measured. As of 2026-09-01, Phase A and Phase B are both built; see the
build-status block above.

## 0. Corrections found while freezing (these override the draft below)

1. **Phase A is $0 in model spend but NOT zero build.** `discovery.selector.select()`
   and `exam.run_exam()` support only unconditional top-N over one of three rank keys.
   There is no gating, hysteresis, cooldown, or regime conditioning anywhere in them.
   Six of the eight entrants therefore need net-new selector code before Phase A can
   run at all. The "free phase" is free of dollars, not of work.
2. **Historical regime calls are a weaker instrument than live ones.** `classify()`'s
   Fear & Greed signal needs current component readings scored against calibration
   constants from a ~40-day fixture; no historical feed for those components exists.
   Phase A freezes `fear_greed_components=()` for the whole replay, degrading every
   historical regime call to 3 signals instead of 4. Phase A and Phase B regime labels
   are consequently NOT directly comparable — carry the caveat forward.
3. **`study._research_cost_usd` does not exist.** The function is
   `_research_call_summary` (`study.py:340`); `research_cost_usd` is a field on
   `ArmMetrics` (`study.py:115`) fed by it. Verified directly.
4. **The tax gate is card-switch-level, not per-symbol.** `taxcheck.evaluate_switch`
   runs once per run inside `_stage_strategy_select` — which is chronologically BEFORE
   `universe_select` exists. So it cannot consider the screened universe, and the §2
   "gate 4" below is mis-stated as a per-candidate check. See the spend spec for the
   corrected mapping of all four `SwitchOutcome` values.
5. **`book_path(settings, arm)` takes one axis today** (`book.py:103`), and
   `WorkflowArm` is a closed 4-value Literal used by `BookState`, `ArmMetrics` and
   `build_study` alike. The screened books cannot be persisted without the
   `universe_source` keyword described below — this is more binding than "contract
   caution" suggested.
6. **The literal is `"screen"`, not `"screened"`,** everywhere.

## 1. Problem statement

The Agent Workflow desk's candidate scan iterates `card.universe` — a hand-authored
≤12-ticker list baked into whichever `StrategyCard` the regime map selects
(`pipeline.py::_scan_signals`, line ~258, `for symbol in card.universe`). The desk
therefore never engages with any stock the card's author didn't pre-select, and the
expensive research machinery (child TA run ≈ $4, observed $12–20/day at defaults ≈
3.8%/yr drag on the $100k book) is pointed by a static list, not by where research
could actually change a decision.

Goal of this round: let the pipeline **decide dynamically which tickers deserve paid
research**, while spending strictly less than today, and measure whether that helps.

Honesty anchor (00-EVERYTHING-TESTED.md): 18+ rounds found no durable edge; the
discovery momentum selector graded IC −0.0073 (p=0.892); noise floor 21.2pp. No
selector below is pitched as "picks winners." A selector is pitched as an
**attention allocator**: given a fixed research budget, point it where the research
gate has the most new information to evaluate, and avoid paying twice for the same
answer.

## 2. Round shape: two phases, spend gated behind a free phase

### Phase A — selector bake-off, backtest-only, $0 LLM spend

`app.discovery` (selector/exam/stats/clusters/costs) is already the machinery for
this: point-in-time selector grading against the candidate pool's own equal weight,
via `AsOfMarket`, over years of stored bars, zero model calls. Extend, don't rebuild.

**Entrants** (all deterministic; parameters frozen before the first run):

| # | Selector | Rule sketch | Regime conditioning | Churn control |
|---|---|---|---|---|
| 1 | Momentum continuity | `select(rank_key="mom12_1", top_n=3, collapse=True)` | top_n 3/2/1/skip by regime | rank-band hysteresis (stay to rank 5, enter at rank 2) |
| 2 | Breakout / vol-expansion | near 252d high (≥ −2%) AND ATR14 ≥ 1.25× its 60d mean, rank by expansion | active in stress/chop, top_n 1 in risk_on, skip risk_off | 10-day re-research cooldown |
| 3 | Mean-reversion / oversold | RSI14 < 35, rank ascending, BB-lower tie-break | ONLY risk_off / high_vol_stress (else empty) | hold until RSI > 50 |
| 4 | Stability-first | rank_key="trend" (close/SMA200), enter at rank 1, exit below rank 6 or SMA200 cross | widen exit band in stress | ≤1 change per 2–4 weeks by design |
| 5 | Signal-density | count of catalog rules firing (≥3 to qualify), from `app.rules.catalog` | defensive rule subset in risk_off/stress | density ≥5 to bump incumbent |
| 6 | Diversification-first | `select(rank_key="mom6", top_n=3, collapse=True)` on THEME roster — 3 picks from 3 correlation groups | none (log group count as diagnostic) | rank-band keyed on group membership |
| C1 | **Control: fixed card universe** | the active card's own static `card.universe`, returned every day | none | zero |
| C2 | **Control: seeded rotation** | alphabetical pool, offset = ISO week % pool size (no RNG, no price data) | none | exactly top_n changes/week |

**Candidate pool:** `StoredETFCandidates` (sector roster for defensive regimes,
theme roster — with its stated survivorship bias — for risk_on). This is the only
pool in the repo built for point-in-time correctness. **Single-stock broad screening
is out of scope for this round**: the bar store holds no delisted names (LEH, BSC,
SIVB etc. absent), so any single-stock pool is survivor-biased by construction; that
needs a point-in-time constituent feed, which is separate infrastructure.

**Grading (pre-registered before running):**
- Primary: bootstrapped IC per selector vs the pool's equal weight
  (`stats.ic_summary(bootstrap=True, block≈21)`), horizon = 21 days matching
  `workflow.candidates.HOLDING_DAYS` (calendar days — keep the existing
  inconsistency deliberately for comparability).
- Secondary: hit rate + `binomial_p_value`, `benjamini_hochberg` with m = ALL
  entrants including both controls (PROTOCOL §3 rule 8); shortlist churn (mean
  picks changed per rebalance) and implied $/day at $4/research.
- Walk-forward split: select on an in-sample slice, confirm on a held-out later
  slice never touched during selection. One measurement only — re-running the same
  deterministic selector on the same history is not confirmation
  (rerunning-a-frozen-card lesson).
- Floor: ~500 decision dates (~2 years daily) before evaluation.

**Pre-registered null:** no selector's IC clears q ≤ 0.10 or beats both controls
beyond the noise floor restated in IC terms. The record predicts exactly this.

### Phase A → B gate: two variants for the owner to choose

- **Strict:** Phase B runs only if a selector clears the IC gate. Under the
  programme's own prediction, Phase B never runs and the round costs $0. Cleanest,
  but tests only the alpha question — not the attention-allocation question the
  round exists for.
- **Pragmatic (recommended):** Phase B runs regardless, on a selector chosen by a
  pre-registered secondary criterion — the cheapest-churn selector that is **not
  significantly worse** than both controls (expected winner on current designs:
  Stability-first #4, ~$0.15–0.30/day steady-state; Diversification-first #6 as
  named backup). Rationale: the live question is whether the research gate
  discriminates better on dynamically-chosen names ("deeply acknowledging the
  stock"), which an IC null does not answer; and the owner's revealed policy weights
  the live record over backtest gates. The criterion must be frozen now, not chosen
  after seeing Phase A.

### Phase B — live-forward test run, two new books

**Architecture (funnel Option A):** new deterministic stage `universe_select`
between `strategy_select` and `candidate_scan`:

```
regime_call → strategy_select (card keeps entry/exit/sizing rules)
           → universe_select   (NEW: regime → CandidateSet → frozen selector → shortlist)
           → candidate_scan    (_scan_signals(card, universe=shortlist))
           → research_{SYM} → followup → vibe_{SYM} → entry_plan → stage_orders
```

- New module `app.workflow.universe::select_universe(card, regime, *, settings,
  as_of, config)` wrapping `discovery.candidates` + `discovery.selector` verbatim.
  Deterministic, `as_of`-gated; the LLM-free orchestrator invariant holds.
- `WorkflowRunRequest` gains `universe_mode: "card" | "screen"` (default
  `"card"` = byte-for-byte today's behavior), plus `candidate_pool`, `rank_key`,
  `screen_top_n`. The in-flight 4-arm study is untouched.
- The card's **entry rule still gates**: shortlist ∩ entry-rule-fires. Rank alone
  never justifies spend (a screened name the rule rejects is logged, not traded).
- `CandidateObservation` gains provenance (`universe_source: "card" | "screen"`) so
  the discrimination instrument can score screen-sourced candidates separately.
- Contract caution: `WorkflowArm` is a closed Literal union pinned in
  AGENT-DESK-CONTRACT.md and mirrored in the frontend TS union
  (closed-unions-kill-pages lesson). Decide before coding: new arm values vs an
  orthogonal `universe_source` axis on the run. Leaning: **orthogonal axis** — the
  arm set stays 4, and Phase B books are keyed (arm, universe_source).

**Arms/books:** exactly two new books — `raw_signal` and `full_workflow` under
`universe_mode="screen"`. No `ta_gated`/`vibe_gated` here: the existing study
already isolates each gate on the static universe; re-running them re-tests the
gate question at 2× cost with no new information about *selection*. The static
4-arm study keeps running and serves as a secondary, descriptive, explicitly
under-powered cross-universe comparison (staggered start, carried positions).

**Research-spend policy (the "only when necessary" machinery):**

Necessity gates, cheapest first — a symbol gets a paid child run only if ALL pass:
1. Card entry rule fires on the symbol (not just selector rank).
2. No still-valid cached verdict. **TTL = 21 sessions**, early-invalidated by two
   free triggers only: regime label flip, or adverse move > 2×ATR14 vs the thesis
   direction. (Earnings-date invalidation is NOT buildable today —
   `events_evidence` is prediction markets, no earnings calendar exists in the
   codebase; future proposal if wanted.) Re-entry after leaving the shortlist =
   invalidated by construction.
3. Book capacity exists (`default_mandate`: max_positions=8, 25% single-name cap,
   $500 min clip) — never research what the book structurally cannot buy.
4. Tax-switch gate: wash-sale-blocked ⇒ skip; churn-limiter-blocked (7-day) ⇒
   research allowed but verdict cached for when the block lifts (owner to confirm).
5. Not a correlation-duplicate (ρ≥0.95, `discovery.clusters`) of an already-held or
   already-researched name.
6. Remaining budget funds one more child (existing backstop, stays last).

Every skip logs WHICH gate skipped it (extend the observation log) — "cache hit"
vs "no capacity" vs "correlation-dup" are different facts.

**Budget envelope (test run):** per-run cap $20 and per-child $4 unchanged;
`max_research_symbols` stays 3 as a ceiling; expected typical spend with TTL reuse
and a low-churn selector: **$4–6/day**, vs $12–20 today. New weekly circuit breaker
$80–100. Cheaper-run levers in order: (1) reduce `analysts`/`debate_rounds`/
`risk_rounds` (plumbed today, honest accounting); (2) cheaper model tier ONLY after
adding its row to `_PRICE_TABLE_PER_MILLION` — today everything is priced as
opus-5, so sonnet-class savings can't be honestly reported and the budget cap trips
on phantom spend.

**Metrics + decision rule (mirrors WORKFLOW-STUDY-PLAN §7, restated not inherited):**
- Primary: paired bootstrap p ≤ 0.10 on daily-return diffs, screened
  `full_workflow` vs screened `raw_signal`; discrimination test on the one gate in
  play (m=1 restated in the BH denominator, not 3).
- Secondary: `net_adjusted_excess` (research cost charged per arm, existing
  machinery); **cost-per-decision-changed** = research $ / count of gate rulings
  that differed from what the raw arm did (a gate that never flips a decision is
  paying for agreement); selector-vs-static shortlist divergence rate.
- Floor: 60 sessions / 40 gated candidates (same as the existing study).
- Explicit null: dynamic selection changes neither the gate's discrimination nor
  net-of-cost returns; the mechanism prior is unchanged by the universe.
- Free add-on: shadow-log every non-selected entrant's daily shortlist during
  Phase B (no LLM spend) for the next round's counterfactual record.

**Rejected design: interleaving selectors across days/weeks.** Deterministic
selectors don't gain sample variance from alternation; it just partitions the
calendar by regime (whoever owns the bull days wins), and churns the tax/wash-sale
logic daily. Recorded here so it isn't re-proposed.

## 3. Guardrails

- Freeze all selector formulas/params/seed and this document's decision rules
  before any measurement; a selector edited after seeing its IC is a memory, not a
  selector.
- BH denominator = everything tried, controls included.
- PROTOCOL §6 promotion does NOT mechanically apply (a selector is not a card);
  adoption into the live default is an owner decision under the r21 posture
  (Gate L + Gate C + judgment), and a mechanical rule for a 8-entrant search would
  launder noise into a live default.
- Phase B is a NEW run cohort (clean break), never blended into the in-flight
  4-arm study's results.

## 4. Build inventory (when authorized — nothing built yet)

Revised upward after correction 1: the selector framework itself must be built
before Phase A can run, because `select()` supports no gating/hysteresis/regime input.

| Item | Size |
|---|---|
| Phase A: selector framework — gating, hysteresis state machines, cooldowns, regime conditioning (none exist today) | M |
| Phase A: the 8 frozen entrants on that framework + exam driver loop over the walk-forward split | M |
| Phase A: report (IC/hit/churn/$ per selector, in-sample + holdout) | S |
| Phase B: `app.workflow.universe` + `universe_select` stage + `universe_mode` config | M |
| Phase B: necessity-gate chain + `app.workflow.research_cache` (TTL + 2 invalidation triggers) + skip-reason logging | M |
| Phase B: `universe_source` axis through book/study/contract/frontend + two screened books | M |
| Price-table row for any cheaper model tier (prerequisite for that lever) | XS |

## 5. Locked decisions (owner, 2026-08-31)

All six open questions were answered "go with the recommendations". Frozen:

1. **Pool scope:** ETF sector/theme rosters only. Single-stock screening is a
   separate later round, gated on a point-in-time constituent feed that does not
   exist (the bar store holds no delisted names → survivor bias by construction).
2. **Phase A→B gate:** pragmatic. Phase B proceeds regardless; the promoted selector
   is the IC-clearing entrant if one exists, else the lowest-churn entrant not
   statistically worse than both controls, ties broken by lower implied $/day then
   alphabetically. Mechanical, frozen in ROUND-33-PLAN.md §7 before any run.
3. **Entry semantics:** card entry rule is a HARD FILTER. Researched set =
   shortlist ∩ entry-rule-fires. Selector rank alone never justifies spend.
4. **Spend ceiling:** $20/day cap retained with ~$4–6 typical expected; new weekly
   circuit breaker $80–100.
5. **Tax gate scope:** wash-sale block skips research; churn-limiter (7-day) and
   near-long-term blocks allow research and cache the verdict for when the block
   lifts. (Applies at card-switch level — see correction 4 above.)
6. **Contract axis:** orthogonal `universe_source: "card" | "screen"`. Books are
   keyed by the PAIR (arm, universe_source); `WorkflowArm` stays a closed 4-value
   union. Agreed convention across both build specs:
   `book_path(settings, arm, *, universe_source="card")`, where `"card"` resolves to
   today's unchanged path and `"screen"` to `book/screen/<arm>.json` (subdirectory,
   not a filename suffix); `BookState`, `ArmMetrics`, `PairedComparison` and
   `GateDiscrimination` each gain a `universe_source` field defaulting to `"card"`.

### Model-change sequencing note

Two specs add fields to the same Pydantic models. They do not collide by name, but
must be applied in one pass, not in parallel:
`CandidateObservation` gains `universe_source` (build spec) plus `skip_reason`,
`skip_detail`, `avoided_cost_usd` (spend spec); nested `GateDecision` gains
`verdict_source: "fresh" | "cached" | "mixed"`. Skip-reason literals are
`weekly_budget_exhausted`, `no_book_capacity`, `tax_wash_sale_blocked`,
`correlation_duplicate`, `budget_exhausted` — deliberately with no `cache_hit`
value, since a cache hit is carried by `verdict_source` instead.

The `verdict_source` distinction is load-bearing for the study, not bookkeeping: the
discrimination test must be able to separate "gate passed on fresh research" from
"gate passed on a cached verdict", or the cache silently contaminates the instrument.

## 6. Source reports

Four design-worker reports (funnel architecture, selector catalogue, spend policy,
round structure) synthesized 2026-08-31; key recon corrections folded in:
`events_evidence` is prediction markets not earnings; one workflow run funds all
four arms (the $12–20/day is per day, not per arm); `_PRICE_TABLE_PER_MILLION` has
only claude-opus-5; evidence/market layers have no per-symbol allowlist (any listed
ticker flows through, fundamentals empty for ETFs by design).

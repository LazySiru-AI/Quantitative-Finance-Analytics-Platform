# Inventory: everything this programme has tested outside the numbered competition rounds

*Compiled 2026-08-29, read-only research pass.* The numbered competition (`strategy-program/ROUND-*-PLAN.md`,
`data/rounds/`) is one of several ways this codebase can put a question to market data. This document
inventories the others: what each capability can measure, whether a real question has ever actually been
run through it or only tests/demos have touched it, which pre-registered studies are blocked and on what,
and which upstream data sources the programme owns but has never wired into a strategy.

Every figure below is attributed to a named document or source file. Where a claim could not be
confirmed from a document or the code, it is marked **not established** rather than inferred.

---

## 1. Summary table — capability vs. real use

| Capability | Code | What it measures | Real question run through it? |
|---|---|---|---|
| Event study | `app.backtest.events.event_study` | Confirmatory: forward-return arms of pre-chosen conditions vs. a shared baseline, hit rate + distribution per horizon | **Yes** — Strategy Lab (150 primary tests), timeframe-effect studies |
| Scan + FDR | `app.backtest.scan` (exact binomial test, Benjamini-Hochberg) | Many conditions at once, one honest trial count, q-values | **Yes** — Strategy Lab, the 9,480-cell timeframe sweep, thesis loop, tournament scoring, evolution ledger all reuse this module directly |
| Lookahead guards | `app.backtest.guards.check` | AST whitelist + empirical tail-truncation causality proof that a rule could not have seen the future | **Yes** — gates every rule the timeframe sweep and Strategy Lab ran; 147 of 540 portfolio-path runs in the timeframe study failed it legitimately |
| Reverse conditioning | `app.backtest.events.reverse_conditioning` | Exploratory: profiles what indicators were doing before the top tail of forward returns | **Built, not used.** Wired to `/api/backtest/reverse` and a `ReverseConditioning.tsx` panel; no research document in this repo records a finding produced through it. Exercised only by API/component tests. |
| Drawdown profiling | `app.backtest.drawdown.profile` | Peak-to-trough-to-recovery episode decomposition | **Yes** — Strategy Lab's universe characterisation (§3 below), `app.report.service` and `app.thesis` use it for real cards |
| Thesis loop (4 guards: pre-registration, global BH ledger, locked holdout, iteration budget) | `app.thesis` | Whether a single, pre-registered hypothesis about one ticker survives an in-sample screen and a one-shot holdout look | **Yes**, on real history (QQQ/SOXL/SPY). Nothing survived; see §2.1 |
| Discovery (as-of universe selection) | `app.discovery` | Whether a mechanical rule, using only contemporaneous data, would have picked winning sectors/themes ahead of time | **Yes**, on 23 years of sector/theme baskets; see §2.2 |
| Timeframe rule-accuracy sweep | `app.timeframes` | How each of 12 rules behaves at each of 7 candle sizes and 4 horizons | **Yes** — 9,480 cells computed; see §2.3 |
| Timeframe strategy-effect study | `tournament/runner.py` (interval-parametric) | Whether a whole card (entry+exit+stop+sizing+ranking) prefers a particular candle | **Yes**, three runs; see §2.4 |
| Evolutionary / genetic strategy search | `app.evolution` | Whether bred (mutated/crossed) genomes outscore random ones under the tournament's own gates | **Yes** — 231 scored generations, 2,374 candidate evaluations analysed independently; see §2.5 |
| Strategy Lab (ad-hoc harness over the above) | `docs/research/strategy-lab/` | 17 claims from a user's chart-analysis note, tested one by one | **Yes** — see §2.6 |
| News/sentiment agent architecture (TradingAgents, Vibe-Trading) | `strategy-program/NEWS-AGENTS-STUDY.md` | Not a market study — a source-grounded read of two external codebases to inform a build plan | N/A — architecture research, not a market question |
| News-as-genome-bias | `app.evolution.news_signal` | Whether currently-newsworthy tickers get proposed as genomes more often | **Yes**, narrowly — 35 of 2,374 ledger rows carry `origin=news`; see §4 |
| Institutional 13F as universe input | `app.institutions` + hand-authored cards | Whether a manager's fresh 13F position, filtered by a trend confirmation, beats a benchmark | **Yes**, twice, both outside the guarded engines (manual card authorship); see §4 |
| Cross-institution 13F consensus | `app.institutions.consensus` | Which positions the most tracked funds bought/sold in the same direction | **Built, never consumed by a card** — API-only; see §4 |
| Macro series (FRED rates/curve/energy), Fear & Greed, event calendar (FOMC/releases/earnings) | `app.market.macro`, `app.market.fear_greed`, `app.market.calendar` | Display panels on the Macro/Calendar tabs | **Never reachable by a strategy at all** — architectural, not a matter of habit; see §5 |

---

## 2. Studies that actually ran, with results

### 2.1 The thesis loop — "does a single pre-registered hypothesis survive?"

Source: `docs/reports/phase-9.md`, module docstring `backend/app/thesis/__init__.py`.

**Question.** For one ticker, does a specific, pre-registered entry condition show a forward edge
in-sample that then replicates on a locked, single-look holdout?

**Ran, on real data.** 6,897 QQQ / 8,438 SPY / 4,129 SOXL stored sessions, plus 700 synthetic
null series across 14 generator families (GBM, Student-t, GARCH, OU, AR(1), fast/slow Markov
regime-switching) used to adversarially test the guards themselves, not the tickers.

**Result: nothing survived on QQQ, SOXL or SPY — a real, reported null.** The one case worth
recording in full:

| ticker · condition | in-sample | holdout |
|---|---|---|
| SPY, `close < bb_lower(20,2)` | edge **+8.6%**, n=110, p=0.0616 | edge +3.2%, n=34, p=0.856 |

The in-sample figure cleared the screen and the BH threshold on its own merits and earned the
one holdout evaluation SPY will ever get for that thesis; the holdout refused to replicate it, and
the loop recorded the verdict **inconclusive** — "the exact sequence the guard exists to produce."
QQQ's holdout was never spent because nothing survived in-sample for it.

**On the null-series adversarial test**: after fixing a holdout-power bug (originally a sign check
only, which let seed 3 "confirm" a thesis on pure noise), zero survivors across 8 seeds and across
all 700 planted-null series. The closest near-miss (slow regime-switching noise, holdout p=0.0113)
was correctly stopped by the sample-size floor (19 independent observations), not the p-value —
"the power floor is load-bearing, not decorative."

**Five defects found by adversarial QA**, four inside the guards themselves (a structurally-empty
`survivors` field that made the null-series assertion pass vacuously; a read-then-write race in
`holdout.claim()` that let 8 concurrent callers produce 6 clean holdout looks recorded as one; a
second run silently overwriting a stored p-value, erasing the first evaluation from the BH
denominator; `BUDGET_EXHAUSTED` reported when the five-template catalogue, not the declared budget,
was actually the limit).

**Verdict for this capability**: real question, real null result, real bugs found and fixed. This
is the best-exercised of all the non-competition capabilities.

### 2.2 Discovery — "would a mechanical rule have found the next semiconductors?"

Source: `strategy-program/DISCOVERY.md`. Code: `backend/app/discovery/`, 39 tests.

**Question.** Running only contemporaneous (as-of) data, does a stated momentum rule surface
winning sectors/themes before they finish running — and is the ranking itself skillful?

**Ran, on 23 annual decision dates, 2003-01-02 → 2025-01-02**, `mom12_1` (12-month momentum
skipping the most recent month), top-3, near-duplicates collapsed by measured correlation, 10bp
costs, on both a sector roster and a theme roster.

**Result — mixed, and honestly separated.**

- **The rule does find the themes.** Semiconductors picked in 2004, 2006, 2015, 2017, 2020, 2024,
  2025; solar (TAN) in 2014/2020/2021; uranium (URA) in 2022; rare earths (REMX) in 2018/2022. 2020
  alone: SMH+TAN picks, **+68.20% net excess**.
- **It has no measurable ranking skill.** Information coefficient across 272 monthly
  cross-sections: **IC = −0.0073**, bootstrap p = **0.892** (stationary block bootstrap, block=12).
  On 23 annual cross-sections the strongest key (`mom12_1`) reaches IC = +0.021, t = +0.23 — still
  indistinguishable from zero.
- **Nothing survives multiple-comparison correction.** Six roster×rank-key combinations tested;
  best uncorrected p = 0.035 (`theme/mom6`), q = 0.186 after BH. **Zero of six discoveries.**
- **The measured edge (mean +3.98%, std 22.39% across 23 theme-roster trials) is an order of
  magnitude smaller than this programme's own measured 21.2-point noise floor** from universe
  ordering alone (`PROTOCOL.md` §7).
- **The sign of the IC flips between eras** (2003-2013: IC = −0.064; 2014-2025: IC = +0.099),
  neither significant — an effect that reverses across an arbitrary split is noise read as signal.

**What the null points at**: wins average +19.25%, losses −12.68%, near-equal counts — the paper's
own conclusion is that the missing piece for a discovery system is exits and risk control, not a
better rank key, and that is a testable next step rather than a slogan.

**Verdict**: a real, negative, well-corrected finding — "naive momentum rotation is not the
mechanism that will find the next semiconductors."

### 2.3 Multi-timeframe rule-accuracy sweep

Source: `docs/research/timeframes/07-sweep-findings.md`.

**Question.** How does each of 12 decision rules behave at each of 7 candle sizes (5m/15m/30m/1h/
4h/1d/1w) and 4 horizons (1/5/20/60 bars) — and does the daily candle the strategy currently trades
on actually win?

**Ran, on the full 20-symbol research universe.** **9,480 cells computed** across symbol, sector
and universe scope.

**Result: coverage is the honest headline, and almost nothing survives correction.**

- Sufficiency (`n_independent >= 20`) is poor at symbol scope for the noisiest intervals — 30m
  clears the gate on only 6.8% of symbol-scope cells; 15m and 4h under 38%.
- Of 3,416 sufficient symbol-scope cells and 1,989 sector-scope cells, **zero** survive
  Benjamini-Hochberg at α=0.10. Of 310 sufficient universe-scope cells, **exactly three** survive.
- **The three survivors, everywhere in the sweep:**

  | rule | interval | horizon | lift | q | n_independent |
  |---|---|---:|---:|---:|---:|
  | `bb_lower_touch` | 1w | 1 bar | **+6.7pp** | 0.014 | 903 |
  | `vwap_reclaim` | 5m | 1 bar | **−3.7pp** (anti-signal) | 0.014 | 2,872 |
  | `bb_upper_touch` | 5m | 1 bar | **−4.2pp** (anti-signal) | 0.034 | 1,913 |

- **Daily does not win, but nothing else clearly beats it either.** Zero of 44 sufficient daily
  universe cells survive FDR; daily's lift distribution (mean +0.18pp) is unremarkable, not
  distinguishably worse than any other interval.
- Cost sensitivity: **no 5m or 15m edge survives both FDR correction and a flat 5bps round-trip
  cost simultaneously** — the two FDR-significant 5m cells are already anti-signals and get 4-5x
  worse under costs.
- Not measured in this pass: regime-conditioned lift (rising/falling), explicitly flagged
  **NOT MEASURED** rather than assumed absent.

### 2.4 Per-strategy candle-timeframe effect (the paper-desk unit, not bare rules)

Source: `docs/research/timeframes/08-strategy-timeframe-effect.md`.

**Question.** Does an existing card (entry+exit+stop+max-hold+sizing) actually prefer the candle
its author wrote it for?

**Ran, three times, with an increasingly rigorous design** — 3,885 symbol-unit cells (run 1, off-
thesis universe), 2,231 symbol-unit cells (run 2, on-thesis universe after a 340-pair intraday
backfill), 540 portfolio-unit cells (run 3, full `run_card` simulation with `max_positions`,
ranking, sizing and cash).

**Result.**

- No interval beats simply holding for the same fraction of the window at the median (metric:
  `excess = log(1+strategy_return) − exposure·log(1+buyhold_return)`, gated at ≥10 closed trades).
  Daily reaches near-parity (median excess −0.0144, run 2) while every other interval stays
  meaningfully negative; 5m is worst everywhere and has **negative capture** — the strategy loses
  while the market gains.
- **Split-half replication: a strategy's preferred candle is a real property (2.6x chance rate,
  36.5% vs. 14.3% chance), but still fails to replicate 63% of the time** — unsafe to act on for
  any single card.
- **The cleanest result in the study, from run 3's paired portfolio comparison**: on 32 cards
  runnable at both 1h and 1d over an identical 2-year window (same holdings, same beta, same
  window — all three major confounds cancel), **daily beat hourly for 28 of 32 cards, median
  +27.9 percentage points.**
- **The intraday half of the question is not answerable with this card library**: median hold is
  ~110 bars; 5m/15m/30m retain only 60 days of history (a Yahoo provider ceiling), so no window
  exists in which both a daily and a 5m card can complete a trade. This is a structural limit, not
  a modelling choice.

### 2.5 Evolutionary / genetic strategy search — an independent statistical audit

Source: `docs/research/loop/01-what-the-search-found.md` and `02-the-twenty-five.md` (frozen
snapshot 2026-08-26 09:00Z).

**Question.** Does the genetic loop's breeding mechanism (mutation/crossover against random
candidates) actually improve strategy quality, and are the 28 promotions/25 pending seat requests
it produced real findings?

**Ran, on the loop's own accumulated ledger.** 231 scored generations (of 233 directories; 2
unusable — a 0-byte OUTCOME.json and a planned-but-unscored generation), 2,374 candidate-generation
evaluations, 1,887 distinct genomes, 35.7 wall-clock hours (of which 27.55 hours / 77.1% was a dead
gap with zero output, since fixed).

**Result — the search is not doing nothing, but nowhere near what the promoted count implies.**

- **Bred cards do beat random cards**: selection-median gap +6.75pp [95% CI +5.84, +7.52], holdout
  gap +2.81pp [+2.02, +5.04] (bootstrap, 20,000 resamples; Mann-Whitney U rejects the null at every
  cut, though its independence assumption is violated by shared lineage, noted explicitly).
- **But that gap is smaller than the programme's own 21.2pp noise floor** (`PROTOCOL.md` §7,
  measured from re-running one identical card under twelve universe orderings).
- **The field's median score did not improve over 202 continuous generations**: OLS slope
  +0.0036pp/generation, 95% CI [−0.0135, +0.0208] — straddles zero. Elitism reliably carries the
  winner forward (93.6% vs. 10.7% survival, permutation p ≈ 0.00005) without the field compounding.
- **The benchmark itself is structurally generous to a partly-invested book**: `gfc` window median
  +37.5pp, the covid+q4-2018 holdout pair +15.0pp — drawn from the same "sharp drawdown" regime
  family that already inflates the best selection window — while the one genuinely bullish window
  (`bull-2024`) has a **negative** median (−8.4pp).
- **Every one of the 28 promotions cleared its "two differing window sets" gate by sharing 4 of 5
  windows and rotating exactly one** (Jaccard overlap 0.667, zero variance across all 28) — a much
  weaker claim than two independent measurements.
- **A root cause, found from source rather than the ledger and fixed after this document was
  written**: `app.evolution.proposer._rules_card` composed every one of the 2,374 evaluations from
  one hardcoded rule template — the search explored parameters, never strategy *form*. Fixed
  2026-08-26 (`rule_shape` trait, eight templates); the analysis above still describes the
  single-template run only.
- Of the 28 promotions, **21 beat the all-time field holdout median** rather than merely being
  positive (the metric that actually discriminates).

**Verdict**: a real, load-bearing statistical audit of a running capability, distinct from the
numbered competition rounds, that materially changed the loop's own design (rule-shape diversity,
window-overlap surfacing, a `savings`-purpose UI bug fixed as a direct consequence).

### 2.6 Strategy Lab — 17 claims from a user's chart-analysis note

Source: `docs/research/strategy-lab/BRIEF.md`, `REPORT.md` (run 2026-08-11; six analysts plus an
adversarial QA pass, using `app.backtest.events.event_study`, `app.backtest.scan`,
`app.backtest.guards.check`, `app.backtest.strategy.backtest`, and `app.backtest.drawdown.profile`
directly as its harness — "if a number here disagrees with the app, the app is right").

**Question.** Do 17 specific claims from a chart-analysis note (MA/MACD crossovers, RSI, Bollinger
Bands, divergence, confluence stacking, seasonality, VIX/Fear&Greed, ATR sizing, multi-timeframe
confluence) hold up on 25+ years of five primary instruments (SPY/QQQ/IWM/XLK/XLV) plus a 13-symbol
replication set?

**Ran.** 150 primary tests (4 rule streams × ideas × 5 symbols), ~625 exploratory horizon-sweep
trials, a 75-cell seasonality family, a 15-cell VIX-threshold family — all pre-registered as one
correction family before any cell was computed.

**Result — a clean, well-corrected null across the whole note, with several claims usefully
falsified or clarified rather than merely "not significant.":**

| | value |
|---|---|
| Primary tests | 150 |
| Survivors at q≤0.10 (within-stream) | **0** |
| Survivors at q≤0.10 (study-wide pooled) | **0** |
| Horizon-sweep trials | ~625, **0** discoveries |
| Seasonality family | 75 cells, **0** survivors (all q ≥ 0.98) |
| VIX-threshold family | 15 cells, **0** survivors |
| Lookahead guards | 150 of 150 **passed** |

Selected findings: the note's literal "ideal entry" indicator ordering beat the "corrected" reading
analysts assumed was intended (positive edge on all 5 symbols vs. mixed sign); MACD's "more falsy
than MA crossover" claim is **not supported** (MACD-signal win rate 41.96% vs MA crossover 39.80%);
confluence/indicator-stacking loses 26-32% of independent sample every time for no consistent
hit-rate benefit; "Sell in May" and "March-April bull" are **not supported** (all 75 seasonality
cells q≥0.98). **Two independent studies on this repo (the prior 2026-08-11 study plus this one)
now put 225 total tests at zero survivors** — this repo's most robust finding about technical rules
on daily bars.

One genuinely interesting result was explicitly *not* claimed as a finding: `rsi_oversold_reversion`
on IWM returned +51.4% across 6 trades through the 2007-09 crash — one cell, one instrument, one
window, no correction applied, "recorded as interesting, claimed as nothing."

**Six claims could not be tested at all, for structural reasons the study names explicitly**:
divergence (no `swing_high`/`swing_low` primitive — later built specifically to close this gap, see
below), ATR position sizing and max-drawdown caps (the engine is long-only, all-in, with no sizing
concept), Volume Profile/ADX/Stochastic/Ichimoku/Fibonacci (not in the indicator registry),
multi-timeframe confluence (one expression sees one interval), and **Fear & Greed as a strategy
input — explicitly named "architecturally untestable": no entry in `macro._SERIES_CATALOG`, no
persisted history to join** (see §5).

**Follow-on**: claim #7 (divergence) was reopened 2026-08-12 after a `swing_high`/`swing_low`
operator was built — bullish divergence: **0 of 45** survivors, and does not beat its own control
arms; bearish MACD divergence survived the pooled ledger (q=0.017) while failing per-symbol, with
caveats recorded.

**Defects found by this study, in the application** (per its own no-fix-while-researching rule):
`app.market.store.read_frame` opens DuckDB read-write despite only reading, causing concurrent-
reader collisions that silently drop symbols from a study (cost this study 4 symbols on one stream);
`ensure_series`'s staleness gate left symbols 4 days stale (benign for backtests, not for a live
macro panel); `app.thesis.instruments.REGISTRY` has no entry for QLD or SSO.

---

## 3. Blocked studies — pre-registered, cannot run as designed

### 3.1 D-social — blocked by data that must accumulate forward

Source: `strategy-program/AGENTS-INTEGRATION-PLAN.md` §4 Phase D; `PHASE-D-NEWS-FEASIBILITY.md`.

**The pre-registered question**: does an extreme StockTwits bull ratio carry any forward return at
any horizon, after correction, across `strategy-program/WINDOWS.md`'s window matrix?

**Why it is blocked, structurally rather than by effort.** StockTwits and Reddit's RSS endpoint
each serve only a live window with no historical query — `SocialProvider` deliberately has no
`as_of` parameter, specifically so a backtest cannot silently ask for 2019 and receive today's
messages relabelled. **There is no way to manufacture a social-sentiment history retroactively; it
can only be accumulated forward from stored snapshots.**

**Current state, as documented:**

- The durable snapshot store shipped 2026-08-24 (`app.market.social_history`, SQLite,
  append-only, keyed on `(symbol, source)`, storing only raw counts — never a derived ratio).
- A background scheduler call site was wired 2026-08-25 (`app.main.lifespan` →
  `social_history.start_scheduler`), gated on `Settings.social_snapshot_scheduler_enabled`
  (env `INVDASH_SOCIAL_SNAPSHOT_SCHEDULER_ENABLED`), which **defaults to `False`**
  (confirmed in `backend/app/config.py:138`) specifically so ordinary `TestClient(app)` test runs
  never spawn a background thread making live network calls. Cadence when on: every 6 hours.
- As of the 2026-08-25 note in `AGENTS-INTEGRATION-PLAN.md`, the flag was set only in "this
  machine's local `.env`" — one developer machine, not a deployment — and the document is explicit
  that "the honest reading is that accumulation has begun here and nowhere else."
- **Whether the scheduler is still running as of this document's date (2026-08-29) is not
  established.** No document in this repository states current accumulation status past
  2026-08-25, and no `data/` inspection was performed for this read-only pass (the task scope is
  documentation, not measuring the live database).

**What unblocks it**: months of continuous accumulation on a deployment that stays up, after which
D-social becomes runnable at its pre-registered scope.

### 3.2 D-news — probed live, and refused at the pre-registered scope

Source: `strategy-program/PHASE-D-NEWS-FEASIBILITY.md` (2026-08-26).

**The pre-registered question**: does a news-volume spike carry forward return after correction,
across the eight main windows in `WINDOWS.md`?

**Why it is blocked, and it is a fixed property of the upstream, not an engineering gap.** GDELT's
DOC 2.0 API does accept `startdatetime`/`enddatetime` (verified live: `q4-2018` returns 95 daily
buckets), but **its archive begins 2017-01-01**, established by bisection against the live
endpoint on 2026-08-26 (2016-12-15 refused with `Invalid query start date.`; 2017-01-01 returned
JSON).

**Consequence for the window matrix:**

| tag | window | reachable |
|---|---|---|
| `gfc` | 2007-10-09 → 2009-03-09 | **no** |
| `chop-2011` | 2011-05-26 → 2012-06-06 | **no** |
| `chop-2015` | 2015-04-07 → 2016-04-15 | **no** |
| `q4-2018`, `covid`, `bear-2022`, `bull-2024`, `recent` | — | yes (5 of 8) |

Five reachable windows sits **exactly on `MIN_ELIGIBLE_MAIN_WINDOWS = 5` with zero slack**; holding
out `covid`/`q4-2018` the way every other study in this programme does leaves only **three**
selection windows, below the eligibility floor outright. The three unreachable windows are not a
random three — they are the deepest drawdown in the matrix plus both sideways windows, added in
round 2 specifically because round 1 lacked anything that "went nowhere."

**This is explicitly weaker evidence than a null.** The document distinguishes "measured and found
absent" (a real null, the outcome D-social's blocker calls "worth being pleased about") from "not
measurable at the stated scope" (this case) — the latter must not be reported as if it were the
former.

**What was built anyway**: `GdeltProvider.fetch_volume_series` (`app/market/providers/gdelt.py`),
16 tests, a named `COVERAGE_START` constant recording the bisection, a result contract that reports
`requested_start_before_coverage` rather than silently truncating.

**The owner's stated branch options** (from the document, recommendation marked): (1) run on the
five reachable windows with no holdout, labelled strictly conditional — **the recommended
branch, and only if Phases E/F are wanted for other reasons**; (2) run on three windows with a
holdout, openly below the eligibility floor; (3) buy a commercial archive reaching 2008 — costs
real money for a hypothesis the plan's own honest prior already calls "weak and crowded"; (4)
cancel D-news and, with it, Phases E and F (agent orchestration, LLM-authored theses). **Not
established: which branch, if any, the owner has since chosen** — no later document records a
decision.

---

## 4. Upstream data that has reached a strategy — and what has not

**13F institutional holdings — has reached a strategy, twice, both outside the guarded engines.**

- `D-13f-newbuys` (`backend/app/paper/library/retired/D-13f-newbuys.json`): diffed consecutive 13F
  filings across six concentrated managers (BRK, APPALOOSA, DUQUESNE, TIGERGLOBAL, COATUE,
  LONEPINE) for fresh position initiations. **Result, stated in the card's own thesis field**: 25
  tradeable "NEW" disclosures, forward return from filing date averaged +12.3% (median +9.9%) vs. a
  QQQM benchmark average of +4.3% — but the raw beat-rate was **52%, a coin flip**, driven by a few
  large winners (SNDK +146%, INTC +96%) offsetting several losers (NFLX −31%, ORCL −35%). The card
  adds a trend-confirmation filter (`close > sma(50) and close > sma(200) and rsi(14) > 50`) on top
  of the raw 13F signal rather than trading it directly. **Retired after round 2**: zero trades in
  every window of two consecutive rounds — `SNDK`'s stored history starts too late for the card's
  `sma(200)` warmup, not a refutation of the finding.
- `c06-13f-momentum`, referenced in `backend/app/paper/library/retired/README.md` as "legal only in
  the `13f-legal` window" (a provenance-constrained card), is documented as the standing example of
  the provenance-gate rule but **no card file for it exists on disk in this pass** — apparently
  removed rather than archived; its retirement history is known only from the README's prose.

**Cross-institution 13F consensus — built, never consumed by a card.** `app.institutions.consensus`
(ranks positions by how many of the 22 tracked filers moved the same way, with a sponsor-overlap
de-duplication rule for managers who file both a 13F and an NPORT) is wired only to
`app.api.institutions_consensus` — an API surface for browsing, not an input any strategy card,
the thesis loop, the rules DSL, or the evolution loop can read.

**News/social sentiment — reaches the evolution loop narrowly, as a universe-selection bias, never
as a scoring signal.** `app.evolution.news_signal.trending_symbols` probes news+social coverage
(counts only — "an agent may propose, name, argue and select; an agent may never emit a number")
and occasionally proposes a genome built around a currently-newsworthy ticker. The independent
ledger audit (§2.5) found **35 of 2,374 candidate-generation rows carry `origin=news`**, with
selection median +7.36pp and holdout median +16.55pp — both between the random and bred groups.
This is explicitly not evidence that news predicts returns; the module's own docstring states
Phase D ("measure before believing") is what would establish that, and it has not run at the
pre-registered scope (§3.2). News never touches scoring — only which tickers get proposed for
testing.

**Fear & Greed index, macro series (FRED rates/curve/energy), and the event calendar (FOMC/
economic releases/earnings) — never consumed by any strategy, and not for lack of trying.** This is
architectural, not habitual: `app.rules.nodes.PriceField` — the enum of bar columns a rule
expression may reference — contains only `open/high/low/close/volume`. There is no path from a
rule's entry/exit/ranking expression to a macro fact, a Fear & Greed reading, or a calendar event.
Confirmed independently by the Strategy Lab study, which tried and named the gap explicitly: claim
#14 ("Fear & Greed / VIX-based strategy") is marked **"architecturally untestable — no entry in
`macro._SERIES_CATALOG`, no persisted history to join."** All three surfaces (`app.market.macro`,
`app.market.fear_greed`, `app.market.calendar`) exist solely to render the Macro and Calendar tabs
and one MCP tool (`app.mcp.tools`); `app.tournament.roster`'s own use of "calendar" is unrelated —
a trading-day-gap sanity check on stored bars, not the economic-event calendar.

**Analyst consensus / sell-side ratings / price targets — not established to exist as an upstream
source in this codebase at all.** A repo-wide search for analyst-rating, price-target or
recommendation-consensus data (as distinct from the 13F/NPORT institutional-holdings surface, which
is unrelated) found nothing under `backend/app`. This is not a "built but unused" capability; it
appears never to have been built.

---

## 5. The built-but-never-used set, gathered

The highest-value output of this inventory, per the task brief — machinery this repo owns that has
never had a real question put through it:

1. **`app.backtest.events.reverse_conditioning`** — wired to `/api/backtest/reverse` and a
   `ReverseConditioning.tsx` panel, but no research document in this repository records a finding
   produced through it. Exercised only by API and component tests.
2. **Cross-institution 13F consensus (`app.institutions.consensus`)** — API-only; never an input to
   a card, the thesis loop, or the evolution loop.
3. **Agent/LLM orchestration (Phases E and F of `AGENTS-INTEGRATION-PLAN.md`)** — not built at all.
   Gated behind Phase D reporting a real signal, and Phase D has not cleared that gate (§3).
4. **Single-ticker discovery** (`app.discovery`'s `CandidateSet` protocol is shaped for it, per
   `DISCOVERY.md` §7) — cannot be implemented without a survivorship-free price history, which
   would require a paid dataset (CRSP, Norgate, Sharadar, EODHD); `stooq` was tried and refused
   (JavaScript proof-of-work bot check, no CSV served at all, "not bypassed and should not be").
5. **Fear & Greed, macro series, event calendar** as strategy inputs — not merely unused but
   structurally unreachable from the rules DSL today (§4).
6. **Analyst consensus / price targets** — no upstream source exists to even attempt using.

---

## 6. What this inventory did not check

Per its own read-only, documentation-first scope: no live database inspection was performed to
confirm whether the social-snapshot scheduler (§3.1) is currently running as of 2026-08-29, no
`git log` was run to check for documents newer than what a file listing surfaced, and the
`c06-13f-momentum` card's full history (§4) could not be recovered beyond the retired README's
prose since the card file itself is not present on disk in this working tree.

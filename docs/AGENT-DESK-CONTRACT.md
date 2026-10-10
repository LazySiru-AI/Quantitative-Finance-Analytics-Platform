# Agent Desk — pinned wire contract

Three features share this contract: **Trading Agents** (`/trading-agents`), **Vibe Trading**
(`/vibe-trading`) and **Agent Workflow** (`/agent-workflow`). It is written down because the backend
and the frontend for each are built in parallel, and an interface fanned out to two workers gets two
guesses unless the literal field names are fixed first.

Agent Workflow is an orchestrator: one staged run that classifies the market regime, selects a
strategy card (tax-aware), scans it for entry candidates, runs child Trading Agents and Vibe Trading
runs for research, synthesises an entry plan, and stages next-open orders onto a persistent paper
book. Its run object is the same `DeskRun` the other two produce; its extra surface (the book, the
execute step, the effectiveness study) is defined in [its own section](#agent-workflow--apiworkflow)
below.

**Nothing in this file is negotiable by a worker.** If a shape here is wrong or insufficient, say so
in your report and stop — do not invent a replacement. A field renamed on one side and not the other
is the exact failure this document exists to prevent.

Backing Python types: [`backend/app/agentdesk/models.py`](../backend/app/agentdesk/models.py).

---

## Conventions

- **Money is a decimal string, never a JSON number.** `cost_usd`, `cap_usd`, `spent_usd`. Same rule
  as the rest of this codebase; render with the helpers in `frontend/src/api/client.ts`.
- **Timestamps are ISO-8601 strings**, or `null` when the event has not happened.
- Every response model is a frozen Pydantic model with `extra="forbid"`.
- Routers are thin: they wire routes and translate domain exceptions to status codes. Logic lives in
  the sibling package.

## Shared wire types

```ts
type StageState =
  | "pending" | "running" | "succeeded" | "degraded" | "failed" | "blocked" | "skipped";
type RunState = "queued" | "running" | "succeeded" | "failed" | "cancelled";
type DeskKind = "tradingagents" | "vibedesk" | "workflow";

interface GroundingIssue {
  kind: "ungrounded_number" | "no_evidence" | "empty_output";
  detail: string;
}

interface GroundingVerdict {
  ok: boolean;
  issues: GroundingIssue[];
  attempts: number;
  degraded: boolean;
  checked_tokens: number;
}

interface StageRecord {
  stage_id: string;
  role: string;
  label: string;
  seat: string;              // "" for Trading Agents
  state: StageState;
  layer: number;
  depends_on: string[];
  started_at: string | null;
  completed_at: string | null;
  output_md: string;
  summary: string;
  grounding: GroundingVerdict | null;
  call_ids: string[];
  cost_usd: DecimalString;
  error: string;
}

interface BudgetWire {
  cap_usd: DecimalString;
  spent_usd: DecimalString;
  calls: number;
}

interface DeskRun {
  run_id: string;
  kind: DeskKind;
  state: RunState;
  created_at: string;
  completed_at: string | null;
  config: Record<string, unknown>;
  stages: StageRecord[];
  final_md: string;
  final_rating: string;      // "" for Vibe Trading
  degraded: boolean;
  error: string;
  budget: BudgetWire;
}

/** What list endpoints return. Never carries `stages`, `final_md` or `config`. */
interface DeskRunSummary {
  run_id: string;
  kind: DeskKind;
  state: RunState;
  label: string;             // "NVDA · 2026-08-29" | "investment_committee · NVDA"
  created_at: string;
  completed_at: string | null;
  degraded: boolean;
  error: string;
  final_rating: string;
  cost_usd: DecimalString;
  stages_total: number;
  stages_done: number;       // succeeded + degraded
}
```

---

## Trading Agents — `/api/tradingagents`

| Method | Path | Body / query | Response |
|---|---|---|---|
| `GET` | `/config` | — | `TradingAgentsConfig` |
| `POST` | `/runs` | `StartRunRequest` | `202` → `DeskRun` |
| `GET` | `/runs` | `?limit=` (default 25) | `{ "runs": DeskRunSummary[] }` |
| `GET` | `/runs/{run_id}` | — | `DeskRun` (`404` if unknown) |
| `DELETE` | `/runs/{run_id}` | — | `DeskRun` with `state: "cancelled"` |
| `GET` | `/memory` | `?symbol=` optional | `{ "entries": MemoryEntry[] }` |

```ts
interface TradingAgentsConfig {
  analysts: { key: string; label: string; blurb: string }[];   // market | sentiment | news | fundamentals
  default_debate_rounds: number;      // 1
  default_risk_rounds: number;        // 1
  max_rounds: number;                 // 3
  default_budget_usd: DecimalString;  // "5.00"
  default_model: string;              // "claude-opus-5"
  agent_available: boolean;           // from app.agents.client.is_available()
  agent_reason: string;
}

interface StartRunRequest {
  symbol: string;                     // required, uppercased server-side
  trade_date?: string | null;         // ISO date; null = newest stored session
  analysts?: string[];                // default: all four
  debate_rounds?: number;             // default 1, clamped 1..max_rounds
  risk_rounds?: number;               // default 1, clamped 1..max_rounds
  budget_usd?: DecimalString;         // default "5.00"
  model?: string;
}

interface MemoryEntry {
  entry_id: string;
  symbol: string;
  trade_date: string;
  rating: string;
  state: "pending" | "resolved";
  raw_return_pct: DecimalString | null;   // null while pending. FRACTION, not percent: 0.0532 = +5.32%
  alpha_return_pct: DecimalString | null; // FRACTION: symbol_return - benchmark_return, e.g. 0.021 = +2.1pp
  benchmark: string;                      // "SPY"
  holding_days: number | null;
  decision_md: string;
  reflection: string;                     // "" while pending
}
```

### Fixed stage ids and labels

The pipeline's stage ids are stable — the page keys its progress board off them.

| `stage_id` | `role` | `label` | layer |
|---|---|---|---|
| `market_analyst` | `market_analyst` | Market Analyst | 0 |
| `sentiment_analyst` | `sentiment_analyst` | Sentiment Analyst | 0 |
| `news_analyst` | `news_analyst` | News Analyst | 0 |
| `fundamentals_analyst` | `fundamentals_analyst` | Fundamentals Analyst | 0 |
| `bull_{n}` / `bear_{n}` | `bull_researcher` / `bear_researcher` | Bull Researcher (round n) | 1 |
| `research_manager` | `research_manager` | Research Manager | 2 |
| `trader` | `trader` | Trader | 3 |
| `risk_aggressive_{n}` / `risk_conservative_{n}` / `risk_neutral_{n}` | matching risk role | Aggressive Analyst (round n) | 4 |
| `portfolio_manager` | `portfolio_manager` | Portfolio Manager | 5 |

`n` is 1-based. `final_rating` ∈ `Buy | Overweight | Hold | Underweight | Sell`.

---

## Vibe Trading — `/api/vibedesk`

| Method | Path | Body / query | Response |
|---|---|---|---|
| `GET` | `/presets` | — | `{ "presets": PresetSummary[] }` |
| `GET` | `/presets/{name}` | — | `PresetDetail` (`404` if unknown) |
| `POST` | `/runs` | `StartSwarmRequest` | `202` → `DeskRun` |
| `GET` | `/runs` | `?limit=` (default 25) | `{ "runs": DeskRunSummary[] }` |
| `GET` | `/runs/{run_id}` | — | `DeskRun` (`404` if unknown) |
| `DELETE` | `/runs/{run_id}` | — | `DeskRun` with `state: "cancelled"` |

```ts
interface PresetSummary {
  name: string;              // "investment_committee"
  label: string;             // "Investment Committee"
  blurb: string;
  agent_count: number;
  layer_count: number;
}

interface PresetDetail extends PresetSummary {
  agents: { id: string; label: string; blurb: string }[];
  tasks: { id: string; agent_id: string; depends_on: string[]; layer: number }[];
  variables: { name: string; label: string; required: boolean; default: string }[];
}

interface StartSwarmRequest {
  preset: string;                      // required
  symbol?: string;
  question?: string;
  variables?: Record<string, string>;
  budget_usd?: DecimalString;          // default "5.00"
  model?: string;
}
```

`config` on a Vibe run echoes `{preset, symbol, question, variables, model}`.
`agent_available` / `agent_reason` are exposed by `GET /api/agents/health`, which the page already
has — Vibe Trading has no `/config` endpoint of its own.

### Error statuses (both desks)

| Condition | Status |
|---|---|
| Unknown `run_id` or preset | `404` |
| A run is already in flight (single-slot registry) | `409` |
| Invalid symbol / unknown analyst key / unknown preset variable | `422` |
| Agent layer unavailable (no credential) | `503`, body names the reason |

---

## Agent Workflow — `/api/workflow`

The orchestrator desk. A run is a `DeskRun` with `kind: "workflow"`; it launches child
`tradingagents` and `vibedesk` runs in-process and stages orders onto a persistent paper book. The
book, the execute step and the study are surface this desk adds on top of the shared run object.

| Method | Path | Body / query | Response |
|---|---|---|---|
| `GET` | `/config` | — | `WorkflowConfig` |
| `POST` | `/runs` | `WorkflowRunRequest` | `202` → `DeskRun` |
| `GET` | `/runs` | `?limit=` (default 25) | `{ "runs": DeskRunSummary[] }` |
| `GET` | `/runs/{run_id}` | — | `DeskRun` (`404` if unknown) |
| `DELETE` | `/runs/{run_id}` | — | `DeskRun` with `state: "cancelled"` |
| `GET` | `/book` | `?universe_source=` (optional; `card` \| `screen`) | `{ "books": WorkflowBook[] }` (omitted = four card books + any screen books on disk; `card` = the four card books; `screen` = only screen books that exist — never seeded by a read) |
| `POST` | `/book/execute` | `ExecuteRequest` | `WorkflowExecuteResult` |
| `GET` | `/study` | `?universe_source=` (optional; default `card`) | `WorkflowStudy` (`screen` scores `SCREENED_ARMS` only) |
| `GET` | `/candidates` | `?universe_source=&state=&symbol=&limit=` (all optional; `limit` default 200, 1..2000) | `WorkflowCandidates` |

```ts
type WorkflowArm = "raw_signal" | "ta_gated" | "vibe_gated" | "full_workflow";
type OrderStatus = "pending" | "filled" | "rejected" | "cancelled" | "expired";
type PriceSource = "stored_open" | "live_quote";
type SwitchOutcome = "held" | "switched" | "switch_blocked_by_tax";
type VibeVerdict = "SUPPORT" | "REFUTE" | "INCONCLUSIVE";
// The request's `universe_mode` and the response's `universe_source` (on `WorkflowBook`, `ArmMetrics`
// and a paired-comparison row) share this closed two-value vocabulary -- see "Dynamic universe" below.
// `WorkflowArm` itself is unchanged, still exactly four values: a book/arm-metrics row is now
// identified by the *pair* `(arm, universe_source)`, not `arm` alone. Render an unrecognised value
// gracefully (a fallback label), never a throwing exhaustiveness check -- the exact hazard that took
// the Paper Desk page down once already.
type UniverseMode = "card" | "screen";

interface WorkflowConfig {
  arms: { key: WorkflowArm; label: string; blurb: string }[];
  default_budget_usd: DecimalString;       // "20.00"
  default_per_child_budget_usd: DecimalString; // "4.00"
  default_max_research_symbols: number;    // 3
  default_model: string;                   // "claude-haiku-4-5-20251001"
  agent_available: boolean;
  agent_reason: string;
  cards: { agent_id: string; label: string; purpose: string }[]; // selectable strategy cards
  universe_modes: UniverseMode[];          // ["card", "screen"]
  candidate_pools: string[];               // app.workflow.universe.CANDIDATE_POOLS, e.g. ["sector-etf", "theme-etf"]
  rank_keys: string[];                     // sorted app.discovery.selector.RANK_KEYS, e.g. ["mom12_1", "mom6", "trend"]
  selector_ids: string[];                  // app.discovery.workflow_selectors.SELECTOR_IDS, the 8 frozen Round-33 selectors
  default_universe_mode: UniverseMode;     // "card"
  default_candidate_pool: string;          // "sector-etf"
  default_rank_key: string;                // "mom12_1"
  default_screen_top_n: number;            // 3
}

interface WorkflowRunRequest {
  agent_card_id?: string | null;   // null = auto-select from regime
  trade_date?: string | null;      // ISO date; null = newest stored session
  budget_usd?: DecimalString;      // default "20.00", whole-run cap across children
  per_child_budget_usd?: DecimalString; // default "4.00", cap per child TA/Vibe run
  max_research_symbols?: number;   // default 3, cap on research_<SYM>/vibe_<SYM> fan-out
  analysts?: string[];             // passthrough to child Trading Agents runs
  debate_rounds?: number;          // passthrough, clamped 1..3
  risk_rounds?: number;            // passthrough, clamped 1..3
  arms_enabled?: WorkflowArm[];    // default: all four
  model?: string;
  universe_mode?: UniverseMode;    // default "card" -- byte-for-byte today's behaviour when omitted
  candidate_pool?: string;         // required (or defaulted) when universe_mode === "screen"; "sector-etf" | "theme-etf"; ignored when selector_id is set
  rank_key?: string;                // required when universe_mode === "screen"; "mom12_1" | "mom6" | "trend"; ignored when selector_id is set
  selector_id?: string;            // the primary screen-mode path: one of the 8 frozen Round-33 selectors (app.discovery.workflow_selectors.SELECTOR_IDS); takes precedence over candidate_pool/rank_key when set; unknown value -> 422
  screen_top_n?: number;           // optional cap on the screened shortlist size; omitted = backend default; still overrides selector_id's own shortlist size when set
  screen_entry_rule?: string;      // optional rules-DSL expression (app.rules.grammar) replacing the chosen card's own entry rule for a screen-mode scan; parsed/validated at submission (422 on a bad expression); ignored in card mode
  weekly_budget_usd?: DecimalString; // trailing-7-day research-spend ceiling, independent of budget_usd; default "100"
}
```

### Dynamic universe (`universe_mode` / `universe_source`)

`universe_mode: "card"` (the default, and every request that predates this section) scans the
strategy card's own static `universe`, unchanged. `universe_mode: "screen"` scans a dynamic
discovery-selector shortlist instead, by one of two paths: `selector_id` (the primary Round-33 path —
one of the eight frozen selectors in `app.discovery.workflow_selectors.SELECTOR_IDS`, which chooses
the pool and applies hysteresis/regime-conditioning internally, the only path that faithfully
reproduces a selector that is not a bare `rank_key`) or, when `selector_id` is omitted, the raw
fallback of `candidate_pool` (`"sector-etf"` | `"theme-etf"`, from `app.discovery.candidates`) and
`rank_key` (`"mom12_1"` | `"mom6"` | `"trend"`, from `app.discovery.selector.RANK_KEYS`). `screen_top_n`
optionally caps the shortlist size under either path. `screen_entry_rule` optionally replaces the
chosen card's own (often event-based, rare-firing) entry rule with a less-restrictive rules-DSL
expression when scanning the screened shortlist, so a screen run can accrue study candidates faster;
ignored in card mode. `candidate_pool`, `rank_key` and `selector_id` are all validated as plain
strings one layer down (`app.workflow.service`), not as TS/Pydantic literal unions at the wire-schema
level — the same choice `app.workflow.schemas.WorkflowRunRequest` itself documents, to avoid a
circular import between the orchestrator and the new selector module. `weekly_budget_usd` is a
separate, independent knob (the research-spend circuit breaker,
`docs/WORKFLOW-RESEARCH-SPEND-SPEC.md`), not part of the universe axis, but lands on the same request.

**Build status, as of 2026-09-01.** All of it is built. `universe_select` is a committed pipeline
stage (`app.workflow.pipeline._stage_universe_select`) that actions `universe_mode: "screen"` via
`app.workflow.universe.resolve_universe`, with `load_prior_shortlist`/`save_prior_shortlist` carrying
hysteresis across runs. `GET /config` surfaces the full catalogue (`universe_modes`, `candidate_pools`,
`rank_keys`, `selector_ids`, and the four `default_*` fields above). `GET /book`, `POST /book/execute`
and `GET /study` all take a `universe_source` query/body param and route to the screen-mode books
(`data/agentdesk/workflow/book/screen/<arm>.json`) when asked. `GET /candidates` is a new endpoint
over the candidate-observation log, with `universe_source`/`skip_reason`/`avoided_cost_usd`/
`verdict_source` provenance. The research-spend necessity-gate chain
(`app.workflow.research_cache` + `pipeline._apply_necessity_gates`) is built and wired into
`_stage_orders`. Frontend code against this contract should still tolerate a book/arm-metrics/
candidate row whose `universe_source` is missing or unrecognised, rendering a fallback label rather
than throwing — that advice does not expire just because the backend caught up.

### Fixed stage ids and labels

Per-run stages are fixed; per-symbol stages are named by suffixing the uppercased symbol. The page
keys its progress board off `stage_id`.

Nine run-level stages: seven fixed (`_FIXED_STAGES`, `pipeline.py`) plus two per-symbol templates
(`research_{SYM}`, `vibe_{SYM}`) spliced in by `_splice_symbol_stages` once the scan knows which
symbols it kept — the contract pins those as templates, not a fixed count, because the count is a
property of the scan, not the request. `universe_select` sits between `strategy_select` and
`candidate_scan`: it must run after the card is chosen (screen mode's shortlist is regime/card-
conditioned) and before the scan, which iterates whichever universe it picked.

| `stage_id` | `role` | `label` | layer |
|---|---|---|---|
| `regime_call` | `market_analyst` | Regime Call | 0 |
| `strategy_select` | `research_manager` | Strategy Selection | 1 |
| `universe_select` | `trader` | Universe Selection | 2 |
| `candidate_scan` | `trader` | Candidate Scan | 3 |
| `research_{SYM}` | `research_manager` | Research · {SYM} | 4 |
| `followup_questions` | `research_manager` | Follow-up Questions | 5 |
| `vibe_{SYM}` | `risk_neutral` | Vibe Review · {SYM} | 6 |
| `entry_plan` | `portfolio_manager` | Entry Plan | 7 |
| `stage_orders` | `portfolio_manager` | Stage Orders | 8 |

`role` values are existing `AgentRole` members (no new roles). `final_rating` is `""` for a workflow
run — the deliverable is the entry plan in `final_md`, not a single rating.

The `config` echoed on a workflow run is
`{agent_card_id, trade_date, budget_usd, per_child_budget_usd, max_research_symbols, analysts,
debate_rounds, risk_rounds, arms_enabled, model, universe_mode, selector_id, candidate_pool, rank_key,
screen_top_n, screen_entry_rule, weekly_budget_usd, child_runs}`. `call_ids` on a stage is **not**
reused to point at child runs — that field means model-call ids, same as the other desks. Child run
ids are recorded in `config.child_runs`, a `{stage_id: run_id}` map, and echoed in the stage's
`summary`.

### The paper book (per arm)

Money and prices are decimal strings. One `WorkflowBook` per enabled arm; all four are paired
(same regime call, card, candidate set, dates, mandate, starting cash) and diverge only at the gate.

```ts
interface WorkflowFill {
  price: DecimalString;
  price_source: PriceSource;
  qty: DecimalString;
  slippage: DecimalString;
  filled_at: string;                 // ISO timestamp
}

interface WorkflowOrder {
  order_id: string;
  arm: WorkflowArm;
  agent_card_id: string;
  symbol: string;
  side: "buy" | "sell";
  notional: DecimalString;
  decision_date: string;             // ISO date the order was staged (close of N)
  fill_date: string;                 // ISO date it fills at open (N+1)
  status: OrderStatus;
  thesis: string;
  invalidation: string;
  stop_level: DecimalString | null;
  regime: string;
  conviction: DecimalString | null;
  evidence: string[];
  created_by_run_id: string;
  fill: WorkflowFill | null;         // null until filled/rejected
  reject_reason: string;             // "" unless status === "rejected"
}

interface WorkflowBookPosition {
  symbol: string;
  qty: DecimalString;
  avg_cost: DecimalString;
  market_value: DecimalString | null; // null when unpriceable at the as-of
}

interface WorkflowBook {
  arm: WorkflowArm;
  universe_source: UniverseMode;     // "card" (today's only value in practice) | "screen"; see "Dynamic universe" above -- a book is identified by the pair (arm, universe_source), not arm alone
  current_card_id: string;
  card_adopted_date: string;
  starting_cash: DecimalString;
  cash: DecimalString;
  equity: DecimalString | null;
  positions: WorkflowBookPosition[];
  orders: WorkflowOrder[];
  equity_curve: { date: string; equity: DecimalString }[];
  tax: PaperTaxSummary | null;       // shape reused from api/paperdesk.ts; null for no-tax/unpriceable books
  as_of: string | null;
}

interface ExecuteRequest {
  as_of?: string | null;             // ISO date; null = newest stored session ("today")
  arms?: WorkflowArm[];              // default: all enabled for the given universe_source
  universe_source?: UniverseMode;    // default "card"; under "screen" only raw_signal/full_workflow are eligible (422 on any other arm), and an absent screen book is skipped, never seeded
}

interface WorkflowExecuteResult {
  as_of: string;
  filled: number;
  rejected: number;
  still_pending: number;
  price_source_mix: { stored_open: number; live_quote: number };
  universe_source: UniverseMode;     // echoes the request's universe_source
}
```

### Candidate observations

```ts
type GateName = "ta_gated" | "vibe_gated" | "full_workflow";
type VerdictSource = "fresh" | "cached" | "mixed";

interface GateDecision {
  gate: GateName;
  passed: boolean;
  detail: string;                    // the gate's own words: a TA rating ("Buy", "Hold") or a Vibe verdict
  was_explicit: boolean;             // false when the gate defaulted rather than ruled (unparseable report, degraded/incomplete child run)
  verdict_source: VerdictSource;     // "fresh" (a child run judged this candidate this cycle) | "cached" (served from a still-valid ResearchVerdictCacheEntry) | "mixed" (full_workflow only: one of TA/Vibe cached, the other forced fresh)
}

interface CandidateObservation {
  obs_id: string;
  run_id: string;                    // the workflow DeskRun that scanned this candidate
  symbol: string;
  decision_date: string;             // ISO date; the session whose close produced the signal
  agent_card_id: string;
  regime: string;
  entry_rank: number;                // position among that session's competing candidates, per the card's rank_by
  gates: GateDecision[];
  state: "pending" | "resolved";
  horizon_days: number | null;
  forward_return_pct: DecimalString | null;   // fraction of one; null while pending or if unpriceable
  benchmark_return_pct: DecimalString | null;
  alpha_return_pct: DecimalString | null;     // forward_return_pct - benchmark_return_pct
  resolved_at: string | null;        // ISO timestamp
  unpriceable: boolean;              // true when resolution was attempted but the window held too few bars
  universe_source: UniverseMode;     // which universe this candidate was scanned from; default "card"
  skip_reason: string | null;        // one of the necessity-gate SKIP_REASONS below, or null if the candidate was actually researched (fresh or cached)
  skip_detail: string;               // human-readable elaboration on skip_reason; "" when skip_reason is null
  avoided_cost_usd: DecimalString;   // dollars saved by reusing a cached verdict instead of a fresh child run; "0" if none avoided
}

// SKIP_REASONS (app.workflow.candidates.SKIP_REASONS): "weekly_budget_exhausted" | "no_book_capacity"
// | "tax_wash_sale_blocked" | "correlation_duplicate" | "budget_exhausted". Deliberately excludes
// "cache_hit" -- a cache hit is carried by GateDecision.verdict_source === "cached", not this taxonomy;
// a candidate served from cache was still researched, never skipped.

interface WorkflowCandidates {
  universe_source: UniverseMode | null;   // echoes the request's filter; null if omitted. NOTE: unlike GET /book, an omitted filter here means UNFILTERED (card and screen rows mixed), not "card" -- a page showing one universe must send the filter explicitly
  total: number;                          // count of every row matching the filters, before limit truncates observations
  observations: CandidateObservation[];   // newest decision_date first, tie-broken by symbol ascending; truncated to limit
  skip_reasons: Record<string, number>;   // counts by skip_reason, over every matching row
  verdict_sources: Record<"fresh" | "cached" | "mixed", number>; // counts of every GateDecision.verdict_source across every matching row's gates
  avoided_cost_usd: DecimalString;        // summed over every matching row
}
```

### The effectiveness study

```ts
interface ArmMetrics {
  arm: WorkflowArm;
  universe_source: UniverseMode;     // same meaning as WorkflowBook.universe_source, set uniformly across every row in one response
  total_return: DecimalString;
  max_drawdown: DecimalString;
  realized_vol: DecimalString;        // non-annualised daily-return stdev
  win_rate: DecimalString | null;
  exposure: DecimalString;
  adjusted_excess: DecimalString;     // total_return - exposure * benchmark_return
  trades: number;
  live_fill_fraction: DecimalString;  // share of fills priced from live_quote
}

interface WorkflowStudy {
  benchmark: string;                  // "SPY"
  benchmark_return: DecimalString;
  window: { start: string; end: string } | null;
  arms: ArmMetrics[];
  paired: {                           // each treated arm vs raw_signal, paired daily diffs
    arm: WorkflowArm;
    universe_source: UniverseMode;    // same meaning as ArmMetrics.universe_source
    mean_daily_diff: DecimalString;
    bootstrap_p: DecimalString;       // stationary-bootstrap p on daily return differences
  }[];
  vibe_verdict_compliance: DecimalString | null; // share of vibe runs that emitted a parseable VERDICT
  note: string;                       // directional-study caveat, live/stored mix
}
```

### Error statuses

Same table as the other desks (`404` unknown run, `409` a workflow run already in flight, `422`
invalid card id / arm / date, `503` agent layer unavailable). `/book/execute` returns `409` if a
workflow run is currently staging orders (it must not fill against a book mid-write).

## Frontend — pinned names

| Thing | Exact value |
|---|---|
| Nav section id | `agents` |
| Section label / blurb | `Agent Desk` / `Model-run research desks, on our own data` |
| Item 1 | `{ to: "/trading-agents", label: "Trading Agents", blurb: "A full analyst-to-portfolio-manager pipeline on one ticker" }` |
| Item 2 | `{ to: "/vibe-trading", label: "Vibe Trading", blurb: "Preset desks of role agents, run as a DAG" }` |
| Item 3 | `{ to: "/agent-workflow", label: "Agent Workflow", blurb: "Regime → strategy → research → plan → next-open execution, measured against single-tool arms" }` |
| Page 1 | `frontend/src/pages/TradingAgents.tsx`, default export `TradingAgents` |
| Page 2 | `frontend/src/pages/VibeTrading.tsx`, default export `VibeTrading` |
| Page 3 | `frontend/src/pages/AgentWorkflow.tsx`, default export `AgentWorkflow` |
| API module 1 | `frontend/src/api/tradingagents.ts`, exports `tradingAgentsApi` |
| API module 2 | `frontend/src/api/vibedesk.ts`, exports `vibeDeskApi` |
| API module 3 | `frontend/src/api/workflow.ts`, exports `workflowApi` |

Section placement: **after `strategy`, before `market`** in the `NAV` tuple. Item 3 follows Item 2
within the `agents` section.

Each API module carries its own local `requestJson<T>` copy — that is this codebase's convention
(see the docstring at the top of `frontend/src/api/evolution.ts`), not an oversight to fix.

## Page layout (both pages, per the owner's brief)

1. **Top — a static explainer.** How the desk works, as a numbered sequence of its stages. Rendered
   from a constant in the page file, not fetched. This is the "brief summary of how it is working on
   the top" the feature was asked for.
2. **Below — the working surface.** Run configuration, a start button, a live progress board keyed
   on `stage_id`, per-stage output, and the final report.

Polling: `GET /runs/{run_id}` every 2s while `state` is `queued` or `running`. No SSE — the
job-registry poll pattern is what `app/tournament/jobs.py` and `/api/competition/jobs` already
establish, and `strategy-program/AGENTS-INTEGRATION-PLAN.md` recommends it over SSE for this shape.

---

## Telemetry — additive, non-contract extension

**Everything in this subsection is explicitly *not* part of the pinned contract above.** Nothing here
renames, removes, or reshapes a field this document already promised; it only adds a new endpoint and
new extension fields on `WorkflowStudy`/`ArmMetrics` for per-run/per-stage token and cost reporting.
Backing Python: [`backend/app/agentdesk/telemetry.py`](../backend/app/agentdesk/telemetry.py) (the
`AgentCall`-archive summarizer both desk- and workflow-level telemetry are built from) and
[`backend/app/workflow/telemetry.py`](../backend/app/workflow/telemetry.py) (the workflow-run walk).

### `GET /api/workflow/runs/{run_id}/telemetry`

Token and cost totals for one workflow run: its own stages (ordinarily empty-summary, since the
deterministic spine never calls a model and the `research_<SYM>`/`vibe_<SYM>` stages only copy a
child's *cost* onto themselves, not its call ids) plus every `tradingagents`/`vibedesk` child run it
launched, per-stage and per-child, with a combined run total. `404` on an unknown `run_id`, following
the same `service.get_run` lookup `GET /api/workflow/runs/{run_id}` itself uses.

```ts
interface CallCostSummary {
  call_count: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_input_tokens: number;
  cache_creation_input_tokens: number;
  cost_usd: DecimalString;
}

interface StageTelemetry {
  stage_id: string;
  label: string;
  summary: CallCostSummary;
}

interface ChildRunTelemetry {
  stage_id: string;          // the workflow stage that launched this child, e.g. "research_AMZN"
  kind: DeskKind;             // "tradingagents" | "vibedesk"
  run_id: string;
  stages: StageTelemetry[];
  summary: CallCostSummary;   // totals across every stage of this child run
}

interface WorkflowRunTelemetry {
  run_id: string;
  stages: StageTelemetry[];       // the workflow run's own stages
  children: ChildRunTelemetry[];  // every research_*/vibe_* child it launched
  total: CallCostSummary;         // combined total across own stages + every child
}
```

A missing or unreadable `AgentCall` archive file, or a `child_runs` entry that does not resolve to a
readable child `DeskRun`, degrades that one call/child's contribution to zero rather than failing the
whole response — this is a report, not a ledger.

### `WorkflowStudy`/`ArmMetrics` extension fields

Alongside the extension fields `docs/WORKFLOW-STUDY-PLAN.md` §3-4 already required (`excess_per_
exposure`, `research_cost_usd`, `net_adjusted_excess`, `discrimination` — see
`backend/app/workflow/study.py`'s own module docstring), `GET /api/workflow/study` now additionally
returns:

- `ArmMetrics.research_input_tokens` / `research_output_tokens` / `research_cache_read_tokens` /
  `research_cache_creation_tokens` (`number`) — token totals over the same TA/Vibe child call set
  `research_cost_usd` sums, per arm.
- `WorkflowStudy.grounding_retry_rate` (`DecimalString | null`) — share of every graded stage (a
  stage with a `GroundingVerdict` attached; deterministic spine stages, which carry none, are
  excluded rather than counted as clean passes), across every stored workflow run and every TA/Vibe
  child it launched, whose `grounding.attempts > 1`. `null` when no stored workflow run has a single
  graded stage yet.
- `WorkflowStudy.grounding_retry_waste_usd` (`DecimalString`) — summed cost of every call before the
  last (accepted) one, across every retried stage counted in `grounding_retry_rate`'s numerator. Zero,
  not `null`, when nothing was ever retried.

None of these five fields are read by the frontend's pinned `ArmMetrics`/`WorkflowStudy` TypeScript
interfaces above; a caller that only reads the contract's named fields is unaffected.

---

## Live data — the `live` opt-in and the live decisions loop

Everything in this section is additive. A `StartRunRequest`/`StartSwarmRequest` written before it
existed starts exactly the run it always did: `live` defaults `false` on both desks, and a non-live
run's evidence sections, `As of:` line and prompt bytes are unchanged.

### `live?: boolean` on both desks

```ts
interface StartRunRequest {   // POST /api/tradingagents/runs — extends the interface above
  live?: boolean;             // default false
}

interface StartSwarmRequest { // POST /api/vibedesk/runs — extends the interface above
  live?: boolean;             // default false
}
```

- **Requires `trade_date` to be `null` or today (UTC).** Trading Agents returns `422` (`"live runs
  must be as of today"`) for any other date: the `live_quote` and `intraday` evidence sections are
  empty by construction for a past `as_of` (a historical view must not see the current market), so a
  back-dated live run would be an ordinary run wearing a live label. Vibe Trading has no `trade_date`
  — its ground truth is always built as of now — so the constraint does not arise there.
- **What it adds.** Trading Agents: the market and sentiment analysts' packs gain `live_quote` and
  `intraday`; the shared downstream pack (debate → trader → risk panel → portfolio manager) gains
  `live_quote`; the analysts' `As of:` line reads `live · <ISO-8601 UTC timestamp>` instead of a
  session. Vibe Trading: the one shared ground-truth pack gains `live_quote` and `intraday` on top of
  whatever the preset's agents declared, still ordered by `SECTION_KEYS`.
- Both desks call `app.market.livefeed.watch([symbol])` best-effort at run start. A failure there is
  logged and ignored — the quote is fetched on demand either way.
- `live` is echoed on the run's own `config` (`DeskRun.config.live`).
- **A live run is not reproducible.** Two live runs a minute apart read different quotes. That is the
  point of the flag, and the reason it is per-run rather than a deployment setting.

### Live decisions — `/api/agentdesk/live`

An opt-in in-process daemon (`app.agentdesk.live_loop`, off unless
`INVDASH_LIVE_DECISIONS_ENABLED=1`) that, during a `REGULAR` market state only, asks for one grounded
model decision per watched symbol, records it, and serves it back.

**Decisions only.** No route on this router, and nothing reachable from it, places, stages or fills a
trade. A decision is a JSONL line and a JSON response, nothing more.

| Method | Path | Body / query | Response |
|---|---|---|---|
| `GET` | `/status` | — | `LiveLoopStatus` (always answers, including when disabled) |
| `GET` | `/decisions` | `?symbol=` optional, `?limit=` 1..200 (default 50) | `{ "decisions": LiveDecisionRecord[] }` |
| `POST` | `/decide` | `{ "symbol": string }` | `{ "decision": LiveDecisionRecord }` |

```ts
interface LiveLoopStatus {         // exactly these twelve keys
  enabled: boolean;                // Settings.live_decisions_enabled
  running: boolean;                // the daemon thread is alive
  healthy: boolean | null;         // null before the first tick
  market_state: string | null;     // from the last tick: "REGULAR" | "PRE" | "POST" | "CLOSED" | null
  last_tick_at: string | null;     // ISO-8601 UTC
  next_wake_at: string | null;     // ISO-8601 UTC; null when not running
  ticks: number;
  decisions_today: number;         // lines in today's UTC record file
  consecutive_failures: number;
  symbols: string[];               // last tick's watchlist, else the configured list
  interval_minutes: number;
  cap_usd: DecimalString;          // per tick, shared across every symbol in it
}

interface LiveDecisionRecord {
  decided_at: string;              // ISO-8601 UTC
  symbol: string;
  stance: "buy" | "sell" | "hold" | "no_action";  // no_action = the evidence did not support a view
  confidence: number;              // 0..1, the model's own self-report
  rationale: string;               // <= 600 chars, cites pack numbers only
  horizon: "intraday" | "days" | "weeks";
  price: DecimalString | null;     // the live price it was decided against; null when no quote
  quoted_at: string | null;        // ISO-8601 UTC
  market_state: string | null;
  grounded: boolean;               // GroundingVerdict.ok
  degraded: boolean;               // released despite failing the gate after every retry
  cost_usd: DecimalString;         // summed over every attempt, not just the accepted one
  model: string;
  source: "daemon" | "manual";
  call_ids: string[];              // AgentCall ids under data/loop/agent_calls/
}
```

Error statuses on `POST /decide`:

| Condition | Status |
|---|---|
| Not a ticker, or a missing `symbol` | `422` |
| The per-decision `AgentBudget` cap was reached | `409` |
| Rolling-24h `model_spend_daily_cap_usd` already spent | `429` (the process-wide `SpendCapExceeded` handler, with `Retry-After`) |
| Agent layer unavailable (no credential) | `503`, body names the reason |

`healthy` is `null` until the first tick, then `false` once `_MAX_CONSECUTIVE_FAILURES` (5) consecutive
ticks decided nothing while failing at least once. A skipped tick — closed market, empty watchlist, a
spend cap already reached — is not a failure and does not affect it.

Records live at `data/agentdesk/live_decisions/<YYYY-MM-DD>.jsonl` (UTC date), append-only, one JSON
object per line. `GET /decisions` reads today's and yesterday's files only, so a request just after
midnight UTC still shows the US afternoon session.

---

## Manager Desk — `/api/manager` (pinned 2026-09-09)

Design: `docs/MANAGER-DESK-PLAN.md`. Backing types: `backend/app/manager/models.py` — **that file is
the contract; this section is its TS mirror.** `DeskKind` gains `"manager"`. The whole `/api/manager`
prefix is **owner-only** in v1 (`app.auth.gate.OWNER_ONLY_PREFIXES`) because a brief folds account
and tax state in.

```ts
type DeskKind = "tradingagents" | "vibedesk" | "workflow" | "manager";
type Scope = "owner" | "member";  type Window = "yesterday" | "week" | "custom";
type Severity = "attention" | "notable" | "fyi";
type Area = "account"|"tax"|"paperdesk"|"persona_books"|"persona_traders"|"research"|"desks"|"live"|"personas"|"market"|"events"|"news"|"data"|"activity";
type CommissionKind = "tradingagents" | "vibedesk" | "workflow" | "persona_chat";
type CommissionState = "proposed"|"approved"|"running"|"succeeded"|"failed"|"cancelled"|"declined";

interface SourceRef { kind: "run"|"note"|"symbol"|"event"|"gen"|"snapshot"|"txn"|"persona"|"seat"; id: string; label: string; }
interface SectionItem { id: string; label: string; figures: Record<string,string>; observed_at: string|null; refs: SourceRef[]; text: string; }
interface SnapshotSection { key: Area; ok: boolean; as_of: string|null; text: string; figures: Record<string,string>; items: SectionItem[]; warnings: string[]; }
interface ManagerSnapshot { scope: Scope; as_of: string; generated_at: string; sections: SnapshotSection[]; warnings: string[]; }

interface ChangeItem { id: string; area: Area; rule: string; severity: Severity; headline: string; detail: string;
  as_of: string|null; observed_at: string|null; figures: Record<string,string>; source_refs: SourceRef[]; }
interface ChangeSet { window: Window; since: string|null; until: string; scope: Scope; items: ChangeItem[];
  sections_missing: string[]; prior_snapshot: string|null; warnings: string[]; }

interface Commission { commission_id: string; kind: CommissionKind; params: Record<string,unknown>; rationale: string;
  budget_usd: string; state: CommissionState; child_run_id: string|null; child_summary: string; source_refs: SourceRef[]; }
interface BriefBullet { text: string; source_refs: SourceRef[]; }
interface Synthesis { assessment: BriefBullet[]; agreements: BriefBullet[]; conflicts: BriefBullet[]; risks: BriefBullet[];
  open_questions: BriefBullet[]; caveat: string; }          // NO instruction field, by design
interface DataHealth { stale: string[]; unknown: string[]; }
interface Brief { brief_id: string; run_id: string; scope: Scope; window: Window; as_of: string; generated_at: string;
  attention: ChangeItem[]; changes: ChangeSet; synthesis: Synthesis; commissions: Commission[]; data_health: DataHealth;
  degraded: boolean; grounding: GroundingVerdict; cost_usd: string; final_md: string; }

interface Caps { brief_usd: string; commission_usd: string; chat_usd: string; daily_usd: string; }
interface ManagerConfig { agent_available: boolean; agent_reason: string; autonomy: string; unattended_kinds: string[];
  autopilot_enabled: boolean; brief_time_et: string; caps: Caps; last_brief_at: string|null; last_snapshot_at: string|null; spent_today_usd: string; }

interface ManagerChatTurn { turn_id: string; asked_at: string; question: string; answer: string; source_refs: SourceRef[];
  commissions: Commission[]; refreshed: boolean; grounding: GroundingVerdict; degraded: boolean; cost_usd: string; }
interface ManagerChatThread { thread_id: string; title: string; created_at: string; updated_at: string; turn_count: number;
  spent_usd: string; turns: ManagerChatTurn[]; }
```

Pinned vocabularies (`app.manager.models`): `AREAS`, `FIGURE_KEYS[area]`, `RULES` (the 34 change-detector
ids), `MANAGER_STAGES = collect, triage, synthesis, research_plan, commission, brief`.

```
GET    /api/manager/config                                   -> ManagerConfig
GET    /api/manager/changes?window=yesterday|week|custom&date= -> ChangeSet   (deterministic; works with the model down)
POST   /api/manager/snapshot                                 -> {as_of, scope, generated_at}   (collect + save now)
POST   /api/manager/briefs {window?, date?}                  -> DeskRun (202, kind "manager"); poll /runs/{run_id}
GET    /api/manager/runs                                     -> {runs: DeskRunSummary[]}
GET    /api/manager/runs/{run_id}                            -> DeskRun
GET    /api/manager/runs/{run_id}/telemetry                  -> (workflow-shaped telemetry: own stages + children)
POST   /api/manager/runs/{run_id}/cancel                     -> DeskRun
GET    /api/manager/briefs/latest                            -> Brief   (404 when none yet)
GET    /api/manager/briefs/{brief_id}                        -> Brief
POST   /api/manager/commissions/{commission_id}/approve      -> Commission   (starts the child; propose mode)
POST   /api/manager/commissions/{commission_id}/decline      -> Commission
GET    /api/manager/chats                                    -> ManagerChatThread[]   (turns: [])
POST   /api/manager/chats                                    -> ManagerChatThread (201)
GET    /api/manager/chats/{thread_id}                        -> ManagerChatThread
DELETE /api/manager/chats/{thread_id}                        -> 204
POST   /api/manager/chats/{thread_id}/turns {question, refresh?} -> ManagerChatTurn
```
Errors: the desk table (404 unknown; 409 manager slot busy / budget / turn cap; 422; 503 agent layer
unavailable) + 429 daily spend cap. Runs persist under `data/agentdesk/manager/runs/` (standard
`RunStore`); snapshots under `data/agentdesk/manager/snapshots/<date>.<scope>.json`; chats under
`data/agentdesk/manager/chats/`. Settings: `manager_brief_cap_usd`, `manager_commission_cap_usd`,
`manager_chat_cap_usd`, `manager_autonomy`, `manager_unattended_kinds`, `manager_model`,
`manager_synthesis_model`, `manager_autopilot_enabled`, `manager_brief_time_et`.

Frontend pinned names: nav item `{ to: "/manager", label: "Manager", blurb: "What changed and what matters, curated across every desk" }`
inserted in the `agents` section directly after `Overview`; page `frontend/src/pages/Manager.tsx`
(default export `Manager`); API module `frontend/src/api/manager.ts` exporting `managerApi`; i18n shard
`frontend/src/i18n/messages/manager.ts`. Every page rule from the plan §4 (not-advice line
unconditional; degraded/stale pills always visible; `sections_missing` named; the Changes panel renders
with `agent_available=false`; commission approval is a click) is a test.

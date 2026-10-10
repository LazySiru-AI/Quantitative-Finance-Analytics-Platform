/**
 * Typed client for Agent Workflow -- the orchestrator desk that classifies the market regime, selects
 * a strategy card, scans it for candidates, runs child Trading Agents/Vibe Trading runs for research,
 * synthesises an entry plan, and stages next-open orders onto a persistent paper book, one per arm.
 *
 * `frontend/src/api/tradingagents.ts` and `frontend/src/api/vibedesk.ts` are this desk's siblings and
 * share almost every wire type with this module (`StageState`, `RunState`, `GroundingIssue`,
 * `GroundingVerdict`, `StageRecord`, `BudgetWire`, `DeskRun`, `DeskRunSummary`) -- see
 * `docs/AGENT-DESK-CONTRACT.md`, the pinned source of truth for all three. Every type below is
 * duplicated here rather than imported from either sibling module, per this codebase's "one copy of
 * shared wire vocabulary per API module" convention (see the docstring at the top of `api/evolution.ts`,
 * which does the same against `api/competition.ts`). A field renamed on one side and not the other is
 * exactly the failure the contract doc exists to catch -- do not "fix" a mismatch here by importing
 * from a sibling module instead.
 *
 * Carries its own local `requestJson<T>`, same five-line shape as every other API module in this
 * codebase (`api/competition.ts`, `api/evolution.ts`, `api/vibedesk.ts`) -- duplicated on purpose, not
 * an oversight.
 *
 * `WorkflowBook.tax` reuses `PaperTaxSummary`'s *shape* from `@/api/paperdesk` (that is where the
 * paper-desk tax summary type actually lives, not `@/api/tax`) per the contract, so that one type is
 * imported rather than re-declared -- the contract calls this out explicitly as the one exception to
 * the "duplicate everything" rule, because `PaperTaxSummary` is itself a large, actively maintained
 * shape and copying it would be the thing most likely to silently drift.
 */
import { ApiRequestError, type DecimalString } from "@/api/client";
import type { PaperTaxSummary } from "@/api/paperdesk";

// --- shared wire types (see this module's docstring on why these are duplicated, not imported) -------

export type StageState =
  | "pending"
  | "running"
  | "succeeded"
  | "degraded"
  | "failed"
  | "blocked"
  | "skipped";

export type RunState = "queued" | "running" | "succeeded" | "failed" | "cancelled";

/** Includes `"workflow"` alongside the two sibling desks' kinds -- a backend enum member missing on
 *  this side is exactly the drift `tests/test_frontend_contract.py` guards against on the Python
 *  side, and a page rendering a run whose `kind` this union does not know renders blank rather than
 *  erroring, which is worse. */
export type DeskKind = "tradingagents" | "vibedesk" | "workflow";

export interface GroundingIssue {
  kind: "ungrounded_number" | "no_evidence" | "empty_output";
  detail: string;
}

export interface GroundingVerdict {
  ok: boolean;
  issues: GroundingIssue[];
  attempts: number;
  degraded: boolean;
  checked_tokens: number;
}

/** One node in the run's DAG. `seat` is `""` for the run-level stages (`regime_call`,
 *  `strategy_select`, `candidate_scan`, `followup_questions`, `entry_plan`, `stage_orders`) -- render
 *  `role` or `label` when `seat` is empty rather than showing a blank. */
export interface StageRecord {
  stage_id: string;
  role: string;
  label: string;
  seat: string;
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

export interface BudgetWire {
  cap_usd: DecimalString;
  spent_usd: DecimalString;
  calls: number;
}

export interface DeskRun {
  run_id: string;
  kind: DeskKind;
  state: RunState;
  created_at: string;
  completed_at: string | null;
  /** Echoes `WorkflowRunRequest` plus `child_runs` (a `{stage_id: run_id}` map of the child
   *  Trading Agents/Vibe Trading runs this workflow launched) -- see this module's own note below
   *  `WorkflowRunRequest` on why that map is not typed further here. */
  config: Record<string, unknown>;
  stages: StageRecord[];
  final_md: string;
  /** Always `""` for a workflow run -- the deliverable is the entry plan in `final_md`, not a single
   *  Buy/Hold/Sell rating. */
  final_rating: string;
  degraded: boolean;
  error: string;
  budget: BudgetWire;
}

/** What `listRuns` returns. Never carries `stages`, `final_md` or `config` -- fetch `getRun` for
 *  those. */
export interface DeskRunSummary {
  run_id: string;
  kind: DeskKind;
  state: RunState;
  label: string;
  created_at: string;
  completed_at: string | null;
  degraded: boolean;
  error: string;
  final_rating: string;
  cost_usd: DecimalString;
  stages_total: number;
  /** succeeded + degraded, per the contract -- not the same as "not pending/blocked". */
  stages_done: number;
}

// --- Agent Workflow's own types -------------------------------------------------------------------

export type WorkflowArm = "raw_signal" | "ta_gated" | "vibe_gated" | "full_workflow";

export type OrderStatus = "pending" | "filled" | "rejected" | "cancelled" | "expired";

export type PriceSource = "stored_open" | "live_quote";

/** The two-value closed union shared by `WorkflowRunRequest.universe_mode` (the request) and
 *  `WorkflowBook`/`ArmMetrics`/the paired-comparison row's own `universe_source` (the response) --
 *  `"card"` is the strategy card's own static universe (today's only behaviour), `"screen"` is a
 *  dynamic discovery-selector shortlist. See `app.workflow.book_models.BookState.universe_source`'s
 *  own docstring, which names the exact hazard this codebase already hit once: a throwing
 *  exhaustiveness check over a server-supplied string took the Paper Desk page down
 *  (`docs/closed-unions-over-server-data-kill-pages` in this repo's own memory). A book is now
 *  identified by the *pair* `(arm, universe_source)`, not `arm` alone -- `WorkflowArm` itself stays a
 *  closed 4-value union on purpose; this is the orthogonal axis, not a widening of that one. Any code
 *  that branches on this value must render an unrecognised one gracefully (a fallback label), never
 *  throw -- see `universeSourceLabel` in `AgentWorkflow.tsx` for the pattern to copy, and
 *  `stageStateLabel` in that same file for the pattern *not* to copy for this field. */
export type UniverseMode = "card" | "screen";

export interface WorkflowConfig {
  arms: { key: WorkflowArm; label: string; blurb: string }[];
  default_budget_usd: DecimalString;
  default_per_child_budget_usd: DecimalString;
  default_max_research_symbols: number;
  default_model: string;
  agent_available: boolean;
  agent_reason: string;
  /** Selectable strategy cards for the run form's dropdown; `null`/omitted selection in
   *  `WorkflowRunRequest.agent_card_id` means "auto-select from the regime call" instead. */
  cards: { agent_id: string; label: string; purpose: string }[];
  /** The rest of these fields are the dynamic-universe (screen-mode) catalogue -- all optional
   *  because a backend that has not yet rolled this out simply omits them; the run form falls back
   *  to its own hardcoded `CANDIDATE_POOLS`/`RANK_KEYS` copies when absent. Deliberately typed as
   *  plain `string[]`/`string`, not narrowed to `UniverseMode` or a literal union, matching this
   *  module's own rule for server-supplied catalogue data (see `UniverseMode`'s doc comment on why a
   *  closed union over a value the backend can extend is the wrong shape here). */
  universe_modes?: string[];
  candidate_pools?: string[];
  rank_keys?: string[];
  /** The Round-33 named selector catalogue (`app.discovery.selector`), 8 ids including
   *  `"mom12_1_hysteresis"` -- the promoted selector. Choosing one of these on a screen-mode run is
   *  the primary path; `WorkflowRunRequest.candidate_pool`/`rank_key` are ignored server-side when
   *  `selector_id` is set. */
  selector_ids?: string[];
  default_universe_mode?: string;
  default_candidate_pool?: string;
  default_rank_key?: string;
  default_screen_top_n?: number;
}

/**
 * `POST /runs` body. `agent_card_id: null` (or omitted) means the run auto-selects a card from its
 * own regime call -- the run form's card dropdown must offer that as an explicit "auto" option
 * alongside `config.cards`, not just default to the first card, since auto-select is a real,
 * distinct choice the backend understands.
 */
export interface WorkflowRunRequest {
  agent_card_id?: string | null;
  trade_date?: string | null;
  budget_usd?: DecimalString;
  per_child_budget_usd?: DecimalString;
  max_research_symbols?: number;
  analysts?: string[];
  debate_rounds?: number;
  risk_rounds?: number;
  arms_enabled?: WorkflowArm[];
  model?: string;
  /** Omitted defaults to `"card"` server-side -- byte-for-byte today's behaviour, so every existing
   *  caller that never sends this field is unaffected. `"screen"` runs a dynamic discovery-selector
   *  shortlist through the `universe_select` stage instead of the card's own static universe. See
   *  `app.workflow.schemas.WorkflowRunRequest.universe_mode`. */
  universe_mode?: UniverseMode;
  /** Required (or defaulted server-side) when `universe_mode === "screen"`; ignored otherwise. One
   *  of `"sector-etf" | "theme-etf"` (`app.discovery.candidates.sector_candidates`/
   *  `theme_candidates`). Kept as a plain `string`, not a literal union, matching the backend's own
   *  choice (`WorkflowRunRequest.candidate_pool`'s docstring) to validate this one layer down in
   *  `app.workflow.service`, not at the wire-schema level. */
  candidate_pool?: string;
  /** Required when `universe_mode === "screen"`; ignored otherwise. One of
   *  `"mom12_1" | "mom6" | "trend"` (`app.discovery.selector.RANK_KEYS`), validated at the same
   *  place and for the same reason as `candidate_pool`. */
  rank_key?: string;
  /** Optional cap on the screened shortlist size; omitted lets the backend apply its own default.
   *  Positive int -- the backend rejects `< 1` with a 422. */
  screen_top_n?: number;
  /** The trailing-7-day research-spend circuit breaker (`app.workflow.schemas.WorkflowRunRequest.
   *  weekly_budget_usd`, default `"100"` server-side when omitted). Independent of `budget_usd`/
   *  `per_child_budget_usd` -- this is a weekly ceiling, not the per-run cap. */
  weekly_budget_usd?: DecimalString;
  /** A named Round-33 selector (`app.discovery.selector`). When set on a screen run this is the
   *  PRIMARY path and the backend ignores `candidate_pool`/`rank_key` entirely -- the run form must
   *  omit both from the request when a named selector is chosen, not just leave them at their
   *  defaults. Omitted falls back to `candidate_pool`+`rank_key`. Unknown id -> 422. Ignored in card
   *  mode. */
  selector_id?: string;
  /** A rules-DSL expression (e.g. `"close > sma(200) and ema(20) > ema(50)"`) overriding the card's
   *  own entry rule, screen-mode runs only -- ignored in card mode. The backend parses it and returns
   *  422 on a bad expression. */
  screen_entry_rule?: string;
}

export interface WorkflowFill {
  price: DecimalString;
  price_source: PriceSource;
  qty: DecimalString;
  slippage: DecimalString;
  filled_at: string;
}

export interface WorkflowOrder {
  order_id: string;
  arm: WorkflowArm;
  agent_card_id: string;
  symbol: string;
  side: "buy" | "sell";
  notional: DecimalString;
  decision_date: string;
  fill_date: string;
  status: OrderStatus;
  thesis: string;
  invalidation: string;
  stop_level: DecimalString | null;
  regime: string;
  conviction: DecimalString | null;
  evidence: string[];
  created_by_run_id: string;
  /** `null` until `status` reaches `"filled"` or `"rejected"`. */
  fill: WorkflowFill | null;
  /** `""` unless `status === "rejected"`. */
  reject_reason: string;
}

export interface WorkflowBookPosition {
  symbol: string;
  qty: DecimalString;
  avg_cost: DecimalString;
  /** `null` when unpriceable at the as-of date -- render "—", not `$0.00`. */
  market_value: DecimalString | null;
}

export interface WorkflowBook {
  arm: WorkflowArm;
  /** Which universe this book's orders were sourced from -- see `UniverseMode`'s own doc comment.
   *  A book is identified by the pair `(arm, universe_source)`, not `arm` alone, once screen-mode
   *  books exist alongside the four card-mode ones -- `GET /book` can then return more than one book
   *  per `arm` value, so callers must key lists/rows on the pair, never `arm` in isolation. */
  universe_source: UniverseMode;
  current_card_id: string;
  card_adopted_date: string;
  starting_cash: DecimalString;
  cash: DecimalString;
  /** `null` when the book cannot be marked at the as-of date. */
  equity: DecimalString | null;
  positions: WorkflowBookPosition[];
  orders: WorkflowOrder[];
  equity_curve: { date: string; equity: DecimalString }[];
  /** `null` for a Roth-style/no-tax book -- render nothing, not an empty tax panel. Shape reused
   *  verbatim from `@/api/paperdesk`'s `PaperTaxSummary`, per the contract. */
  tax: PaperTaxSummary | null;
  as_of: string | null;
}

export interface ExecuteRequest {
  /** `null`/omitted means the newest stored session ("today"). */
  as_of?: string | null;
  /** Omitted means every enabled arm. Under `universe_source: "screen"` the backend only accepts
   *  `"raw_signal"`/`"full_workflow"` and skips screen books that don't exist on disk. */
  arms?: WorkflowArm[];
  /** Which book(s) to execute against -- same field, same reasoning as `WorkflowBook.universe_source`.
   *  Omitted defaults to `"card"` server-side, byte-for-byte today's behaviour. */
  universe_source?: UniverseMode;
}

export interface WorkflowExecuteResult {
  as_of: string;
  filled: number;
  rejected: number;
  still_pending: number;
  price_source_mix: { stored_open: number; live_quote: number };
  /** Echoes the `universe_source` this execution ran against. */
  universe_source: UniverseMode;
}

export interface ArmMetrics {
  arm: WorkflowArm;
  /** Which universe the book behind this row was loaded from -- same field, same reasoning as
   *  `WorkflowBook.universe_source`. Set uniformly across every row in one `WorkflowStudy` response;
   *  a study never mixes card-mode and screen-mode rows in the same `arms` array. */
  universe_source: UniverseMode;
  total_return: DecimalString;
  max_drawdown: DecimalString;
  /** Non-annualised daily-return stdev. */
  realized_vol: DecimalString;
  win_rate: DecimalString | null;
  exposure: DecimalString;
  /** `total_return - exposure * benchmark_return`. */
  adjusted_excess: DecimalString;
  trades: number;
  /** Share of fills priced from `live_quote` rather than `stored_open`. */
  live_fill_fraction: DecimalString;
}

export interface WorkflowStudy {
  benchmark: string;
  benchmark_return: DecimalString;
  window: { start: string; end: string } | null;
  arms: ArmMetrics[];
  /** Each treated arm vs `raw_signal`, paired on daily return diffs. */
  paired: {
    arm: WorkflowArm;
    /** Same field, same reasoning as `ArmMetrics.universe_source`. */
    universe_source: UniverseMode;
    mean_daily_diff: DecimalString;
    /** Stationary-bootstrap p-value on the daily return differences. */
    bootstrap_p: DecimalString;
  }[];
  /** Share of vibe runs that emitted a parseable VERDICT; `null` when no vibe runs are in the
   *  window. */
  vibe_verdict_compliance: DecimalString | null;
  /** The directional-study caveat and live/stored fill mix, in the backend's own words -- render
   *  this prominently, not tucked below the metrics table. This is a directional study, not a
   *  backtest with guaranteed fills, and `note` is where that limitation is actually stated. */
  note: string;
  /** Per-gate discrimination: whether candidates a gate passed actually did better than the ones it
   *  refused. Optional -- an older backend, or a window with no gated candidates, omits it. Render a
   *  compact table when present; when every row's `passed_n` is `0`, gate effectiveness is not yet
   *  measurable and the panel must say so rather than rendering a misleadingly empty/zero table. */
  discrimination?: GateDiscrimination[];
}

/** One row of `WorkflowStudy.discrimination` -- one gate's passed-vs-refused split. `gate` is a
 *  plain `string`, not narrowed to `WorkflowArm`/a literal union -- render it as-is, a fallback label
 *  for an unrecognised value, never a throwing exhaustiveness check (see `UniverseMode`'s own doc
 *  comment on why closed unions over server-supplied strings are the wrong shape in this module). */
export interface GateDiscrimination {
  gate: "ta_gated" | "vibe_gated" | "full_workflow" | string;
  passed_n: number;
  refused_n: number;
  passed_hit_rate: DecimalString | null;
  refused_hit_rate: DecimalString | null;
  passed_mean_forward_return: DecimalString | null;
  refused_mean_forward_return: DecimalString | null;
  mean_diff: DecimalString | null;
  p_value: DecimalString | null;
  q_value: DecimalString | null;
}

/** One gate's ruling on one candidate observation. `verdict_source` says whether that ruling came
 *  from a fresh child-agent call, a cached prior verdict, or a mix (some gates fresh, some cached) --
 *  render this visibly next to the ruling, not just the pass/fail. Kept as a plain `string` beyond
 *  the three known values for the same reason as `GateDiscrimination.gate` above. */
export interface GateDecision {
  gate: string;
  passed: boolean;
  detail: string;
  was_explicit: boolean;
  verdict_source: "fresh" | "cached" | "mixed" | string;
}

/** One scanned candidate's full observation record -- one row of `WorkflowCandidates.observations`.
 *  `state === "pending"` means the forward-return fields are not resolved yet; `skip_reason` is
 *  `null` unless the candidate never made it past a gate, in which case it names why (and
 *  `skip_detail`/`avoided_cost_usd` carry the specifics -- the research spend this skip avoided). */
export interface CandidateObservation {
  obs_id: string;
  run_id: string;
  symbol: string;
  decision_date: string;
  agent_card_id: string;
  regime: string;
  entry_rank: number;
  gates: GateDecision[];
  state: "pending" | "resolved" | string;
  horizon_days: number | null;
  forward_return_pct: DecimalString | null;
  benchmark_return_pct: DecimalString | null;
  alpha_return_pct: DecimalString | null;
  resolved_at: string | null;
  unpriceable: boolean;
  universe_source: UniverseMode | string;
  skip_reason: string | null;
  skip_detail: string;
  avoided_cost_usd: DecimalString;
}

/** `GET /candidates`'s response: a page of observations plus summary aggregates -- the summary
 *  counts (`skip_reasons`, `verdict_sources`, `avoided_cost_usd`) are computed by the backend over
 *  the *filtered* set (`total`/`observations.length`), not the whole table, so they always agree with
 *  what's rendered below them. */
export interface WorkflowCandidates {
  universe_source: UniverseMode | null;
  total: number;
  observations: CandidateObservation[];
  skip_reasons: Record<string, number>;
  verdict_sources: { fresh: number; cached: number; mixed: number };
  avoided_cost_usd: DecimalString;
}

const BASE = "/api/workflow";

/** Same five-line contract as every other API module's `requestJson` -- see `api/evolution.ts`'s own
 *  copy's docstring for why it is duplicated rather than imported. */
async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new ApiRequestError(response.status, body || response.statusText);
  }
  return (await response.json()) as T;
}

/** Whether a poll loop over `GET /runs/{run_id}` should keep going -- mirrors `isRunActive` in
 *  `api/vibedesk.ts`/`api/tradingagents.ts`. `"queued"` and `"running"` keep polling; every other
 *  state is a settled end state. An unrecognised state is treated as active, the same conservative
 *  default those two make, so a live run's updates are never silently dropped over a value this
 *  build has not been taught to end on. */
export function isRunActive(state: RunState): boolean {
  switch (state) {
    case "queued":
    case "running":
      return true;
    case "succeeded":
    case "failed":
    case "cancelled":
      return false;
    default: {
      const _exhaustive: never = state;
      void _exhaustive;
      return true;
    }
  }
}

export const workflowApi = {
  /** Strategy cards, arm descriptions and defaults for the run form. */
  config: (signal?: AbortSignal) =>
    requestJson<WorkflowConfig>(`${BASE}/config`, { signal: signal ?? null }),

  /** Starts a workflow run. Returns the `202` body immediately, before a single stage has run --
   *  poll `getRun` for live progress. `409` means a workflow run is already in flight (single-slot
   *  registry), `422` an invalid card id/arm/date, `503` the agent layer being unavailable (its body
   *  names the reason -- check `config().agent_available` before letting a reader click Start, but
   *  the run endpoint enforces it independently too). */
  startRun: (body: WorkflowRunRequest, signal?: AbortSignal) =>
    requestJson<DeskRun>(`${BASE}/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: signal ?? null,
    }),

  /** Past and current runs, newest first, summary only. `limit` caps how many come back; omitted,
   *  the backend applies its own default of 25. */
  listRuns: (limit?: number, signal?: AbortSignal) =>
    requestJson<{ runs: DeskRunSummary[] }>(
      `${BASE}/runs${limit !== undefined ? `?limit=${encodeURIComponent(String(limit))}` : ""}`,
      { signal: signal ?? null },
    ),

  /** One run's full detail, including every stage's own output -- the poll target while a run is
   *  `queued`/`running`. `404` if `runId` is unknown. */
  getRun: (runId: string, signal?: AbortSignal) =>
    requestJson<DeskRun>(`${BASE}/runs/${encodeURIComponent(runId)}`, { signal: signal ?? null }),

  /** Cancels a run in flight. Returns the run with `state: "cancelled"` rather than an empty body,
   *  so the caller renders it exactly like any other poll result. */
  cancelRun: (runId: string, signal?: AbortSignal) =>
    requestJson<DeskRun>(`${BASE}/runs/${encodeURIComponent(runId)}`, {
      method: "DELETE",
      signal: signal ?? null,
    }),

  /** One `WorkflowBook` per enabled arm -- all four are paired (same regime call, card, candidate
   *  set, dates, mandate, starting cash) and diverge only at the gate. `universeSource` omitted is
   *  today's behaviour byte-for-byte: every card book plus any screen books on disk, all in one list
   *  (rows are keyed on the pair `(arm, universe_source)`, never `arm` alone, for exactly this
   *  reason). Passing `"card"`/`"screen"` filters to just that universe. */
  book: (universeSource?: UniverseMode, signal?: AbortSignal) =>
    requestJson<{ books: WorkflowBook[] }>(
      `${BASE}/book${universeSource ? `?universe_source=${encodeURIComponent(universeSource)}` : ""}`,
      { signal: signal ?? null },
    ),

  /** Fills every pending order eligible at `as_of` (default: newest stored session) at that date's
   *  open, across `arms` (default: every enabled arm) and `universe_source` (default: `"card"`,
   *  today's behaviour). `409` if a workflow run is currently staging orders -- the backend refuses
   *  to fill against a book mid-write. */
  executeBook: (body: ExecuteRequest = {}, signal?: AbortSignal) =>
    requestJson<WorkflowExecuteResult>(`${BASE}/book/execute`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: signal ?? null,
    }),

  /** The effectiveness study: per-arm metrics, paired bootstrap significance against `raw_signal`,
   *  vibe verdict compliance, the directional-study caveat in `note`, and (when present) per-gate
   *  discrimination. `universeSource` omitted defaults to `"card"` server-side. */
  study: (universeSource?: UniverseMode, signal?: AbortSignal) =>
    requestJson<WorkflowStudy>(
      `${BASE}/study${universeSource ? `?universe_source=${encodeURIComponent(universeSource)}` : ""}`,
      { signal: signal ?? null },
    ),

  /** Individual candidate observations -- why a candidate was skipped (`skip_reason`), whether its
   *  gate verdicts came from cache (`verdict_source`), and forward/alpha returns once resolved. All
   *  filters optional; `limit` defaults to 200 server-side (1..2000). */
  candidates: (
    params: {
      universeSource?: UniverseMode;
      state?: "pending" | "resolved";
      symbol?: string;
      limit?: number;
    } = {},
    signal?: AbortSignal,
  ) => {
    const query = new URLSearchParams();
    if (params.universeSource) query.set("universe_source", params.universeSource);
    if (params.state) query.set("state", params.state);
    if (params.symbol) query.set("symbol", params.symbol);
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    const qs = query.toString();
    return requestJson<WorkflowCandidates>(`${BASE}/candidates${qs ? `?${qs}` : ""}`, {
      signal: signal ?? null,
    });
  },
};

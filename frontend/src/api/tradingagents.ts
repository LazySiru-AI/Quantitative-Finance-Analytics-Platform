/**
 * Typed client for the Trading Agents desk -- a full analyst-to-portfolio-manager pipeline run on
 * one ticker. Mirrors `docs/AGENT-DESK-CONTRACT.md` field for field; that document is the pinned wire
 * contract shared with the sibling Vibe Trading desk (`@/api/vibedesk`) and is authoritative over
 * this file, not the other way around.
 *
 * Carries its own local `requestJson<T>` copy rather than importing one -- this codebase's
 * convention, not an oversight. See the docstring at the top of `@/api/evolution` for why: every API
 * module in this app duplicates this same five-line function instead of sharing it, so a change to
 * one module's error handling can never silently change another's.
 *
 * **Money is a decimal string, never a JSON number**, exactly like every other module here --
 * `cost_usd`, `cap_usd`, `spent_usd` are `DecimalString`. `formatMoney` below is a local copy of the
 * same string/BigInt digit-shifting rule `@/api/tax`'s `formatMoney` and `@/api/client`'s
 * `parseDecimalString` already establish -- never `Number`/`parseFloat` on one of these.
 */

import { ApiRequestError, type DecimalString } from "@/api/client";
import { formatMoney } from "@/format/money";
import { t } from "@/i18n";

// --- shared wire types (docs/AGENT-DESK-CONTRACT.md "Shared wire types") ---------------------------

export type StageState =
  | "pending"
  | "running"
  | "succeeded"
  | "degraded"
  | "failed"
  | "blocked"
  | "skipped";

export type RunState = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export type DeskKind = "tradingagents" | "vibedesk";

export interface GroundingIssue {
  kind: "ungrounded_number" | "no_evidence" | "empty_output";
  detail: string;
}

/** Whether a stage's own numbers were checked against the evidence it was given. `degraded: true`
 * means the check failed three times in a row and the stage is shown marked "ungrounded" rather than
 * hidden -- see `StageRecord.grounding`'s own docstring. */
export interface GroundingVerdict {
  ok: boolean;
  issues: GroundingIssue[];
  attempts: number;
  degraded: boolean;
  checked_tokens: number;
}

/** One node in the pipeline -- an analyst report, a debate round, the trader's proposal, a risk
 * review, or the final portfolio-manager rating. `stage_id` is stable across runs (see the contract's
 * "Fixed stage ids and labels" table) and is what the progress board keys its rows on. `seat` is
 * always `""` for Trading Agents -- it exists only because this type is shared with Vibe Trading,
 * where it names which swarm agent produced the stage. */
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
  config: Record<string, unknown>;
  stages: StageRecord[];
  final_md: string;
  final_rating: string;
  degraded: boolean;
  error: string;
  budget: BudgetWire;
}

/** What list endpoints return. Never carries `stages`, `final_md` or `config` -- fetch `getRun` for
 * those once a row is actually opened. */
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
  stages_done: number;
}

// --- Trading Agents -- /api/tradingagents ------------------------------------------------------------

export interface AnalystOption {
  key: string;
  label: string;
  blurb: string;
}

export interface ModelOption {
  /** The wire value passed as `StartRunRequest.model`, and what pins a specific version. */
  id: string;
  label: string;
}

export interface TradingAgentsConfig {
  analysts: AnalystOption[];
  default_debate_rounds: number;
  default_risk_rounds: number;
  max_rounds: number;
  default_budget_usd: DecimalString;
  default_model: string;
  /** The worker models a run may pick from; the first is the default. */
  available_models: ModelOption[];
  /** From `app.agents.client.is_available()`. When `false`, no run can start -- `agent_reason` says
   * why (typically a missing credential), and the page must disable Start rather than let a reader
   * discover the 503 by clicking it. */
  agent_available: boolean;
  agent_reason: string;
}

export interface StartRunRequest {
  symbol: string;
  trade_date?: string | null;
  analysts?: string[];
  debate_rounds?: number;
  risk_rounds?: number;
  budget_usd?: DecimalString;
  model?: string;
  /** Opt-in to today's live quote and 5-minute bars instead of the stored end-of-day close. Default
   *  `false`. The backend 422s a `live: true` request whose `trade_date` is not today -- the run
   *  form clears/disables the trade-date input while this is checked so that rejection can't happen
   *  from the UI. */
  live?: boolean;
}

export interface MemoryEntry {
  entry_id: string;
  symbol: string;
  trade_date: string;
  rating: string;
  state: "pending" | "resolved";
  raw_return_pct: DecimalString | null;
  alpha_return_pct: DecimalString | null;
  benchmark: string;
  holding_days: number | null;
  decision_md: string;
  reflection: string;
}

export interface RunsListResponse {
  runs: DeskRunSummary[];
}

export interface MemoryListResponse {
  entries: MemoryEntry[];
}

const BASE = "/api/tradingagents";

/** Same five-line contract as every other API module's `requestJson` -- see this module's own
 * docstring for why it is duplicated rather than imported. */
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

export const tradingAgentsApi = {
  /** The desk's own configuration: which analysts exist, the default/max round counts, the default
   * budget and model, and whether the agent layer can run at all right now. Fetch once on mount --
   * this rarely changes mid-session. */
  config: (signal?: AbortSignal) =>
    requestJson<TradingAgentsConfig>(`${BASE}/config`, { signal: signal ?? null }),

  /** Starts a run. Returns the `202` body immediately -- a `DeskRun` in `state: "queued"` (or already
   * `"running"`), before a single stage has completed. Poll `getRun` for live progress. A `409` means
   * a run is already in flight (single-slot registry); a `422` names the rejected symbol or analyst
   * key; a `503` means the agent layer is unavailable, body names the reason. */
  startRun: (body: StartRunRequest, signal?: AbortSignal) =>
    requestJson<DeskRun>(`${BASE}/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: signal ?? null,
    }),

  /** Past and in-flight runs, newest first per the backend's own order -- not re-sorted here.
   * `limit` caps how many come back; omitted, the backend applies its own default (25). */
  listRuns: (limit?: number, signal?: AbortSignal) =>
    requestJson<RunsListResponse>(
      `${BASE}/runs${limit !== undefined ? `?limit=${encodeURIComponent(String(limit))}` : ""}`,
      { signal: signal ?? null },
    ),

  /** One run's full detail -- every stage, the final report, the budget spent so far. `404` when
   * `run_id` is unknown. This is the poll target while a run is `queued`/`running`. */
  getRun: (runId: string, signal?: AbortSignal) =>
    requestJson<DeskRun>(`${BASE}/runs/${encodeURIComponent(runId)}`, { signal: signal ?? null }),

  /** Cancels a run. Returns the run's own record with `state: "cancelled"`, exactly like any other
   * poll result, rather than an empty body -- so a caller renders it the same way `getRun` renders
   * anything else. `404` when `run_id` is unknown. */
  cancelRun: (runId: string, signal?: AbortSignal) =>
    requestJson<DeskRun>(`${BASE}/runs/${encodeURIComponent(runId)}`, {
      method: "DELETE",
      signal: signal ?? null,
    }),

  /** Past decisions the desk has recorded, optionally filtered to one symbol -- including ones whose
   * outcome is still `"pending"`. This is the "lessons from past decisions" the portfolio manager
   * stage is informed by; `reflection` is `""` while pending. */
  memory: (symbol?: string, signal?: AbortSignal) =>
    requestJson<MemoryListResponse>(
      `${BASE}/memory${symbol !== undefined ? `?symbol=${encodeURIComponent(symbol)}` : ""}`,
      { signal: signal ?? null },
    ),
};

// --- display helpers -----------------------------------------------------------------------------

// `formatMoney` moved to `@/format/money` (was a local copy identical to `@/api/tax` and
// `@/api/personas`'s own); re-exported here so every existing `import { formatMoney } from
// "@/api/tradingagents"` across the app keeps working unchanged.
export { formatMoney };

/** Whether a poll loop over `getRun` should keep going. Mirrors `isLoopActive`
 * (`@/api/evolution`)/`isTerminalJobStatus` (`@/api/competition`)'s own shape for this codebase's
 * job-registry poll pattern: `"queued"`/`"running"` keep the `setInterval` alive, every other state
 * is a settled end state. */
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
      return false;
    }
  }
}

/** `error.message` for a failed `startRun` is the raw response body -- `{"detail": "..."}` or
 * `{"detail": [{"msg": "...", ...}, ...]}` for a pydantic `422`, a fragment of the wire protocol, not
 * something to render verbatim (see `@/api/evolution`'s `describeStartLoopError` for the same lesson
 * applied to the sibling loop endpoint). Unwraps `detail` when the body parses as JSON; falls back to
 * a plain, readable sentence for a `409` (a run is already in flight) and a `503` (the agent layer is
 * unavailable) since both name their own reason in the body already. */
export function describeStartRunError(error: unknown): string {
  if (!(error instanceof ApiRequestError)) {
    return error instanceof Error && error.message
      ? error.message
      : t("agentDesk.trading.startError.generic");
  }
  if (error.status === 422) {
    return parseErrorDetail(error.message) ?? t("agentDesk.trading.startError.rejected");
  }
  if (error.status === 409) {
    return parseErrorDetail(error.message) ?? t("agentDesk.trading.startError.runInFlight");
  }
  if (error.status === 503) {
    return parseErrorDetail(error.message) ?? t("agentDesk.trading.agentUnavailable");
  }
  return error.message || t("agentDesk.trading.startError.generic");
}

function parseErrorDetail(body: string): string | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return null;
  }
  if (parsed === null || typeof parsed !== "object" || !("detail" in parsed)) return null;
  const detail = (parsed as { detail: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : null))
      .filter((m): m is string => m !== null);
    return messages.length > 0 ? messages.join("; ") : null;
  }
  return null;
}

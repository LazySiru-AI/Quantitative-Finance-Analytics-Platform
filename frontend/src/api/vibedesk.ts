/**
 * Typed client for Vibe Trading -- preset desks of role agents, run as a DAG over pre-fetched market
 * data. `frontend/src/api/tradingagents.ts` is Vibe Trading's sibling feature and shares almost every
 * wire type with this module (`StageState`, `RunState`, `GroundingIssue`, `GroundingVerdict`,
 * `StageRecord`, `BudgetWire`, `DeskRun`, `DeskRunSummary`) -- see `docs/AGENT-DESK-CONTRACT.md`,
 * the pinned source of truth for both. Every type below is duplicated here rather than imported from
 * that module, per this codebase's "one copy of shared wire vocabulary per API module" convention
 * (see the docstring at the top of `api/evolution.ts`, which does the same against `api/competition.ts`).
 * A field renamed on one side and not the other is exactly the failure the contract doc exists to
 * catch -- do not "fix" a mismatch here by importing from `api/tradingagents.ts` instead.
 *
 * Carries its own local `requestJson<T>`, same five-line shape as every other API module in this
 * codebase (`api/competition.ts`, `api/evolution.ts`) -- duplicated on purpose, not an oversight.
 *
 * **Vibe Trading has no `/config` endpoint of its own.** Whether the agent layer can even run right
 * now (`AgentHealth`) is exposed at `GET /api/agents/health`, a route that belongs to neither desk --
 * `agentHealth()` below just calls it. `AgentHealth`'s shape mirrors `backend/app/api/agents.py`'s
 * `AgentHealth` model exactly: `available`, `credential_source`, `reason`, `model`, `sdk_installed`.
 */
import { ApiRequestError, type DecimalString } from "@/api/client";

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

export type DeskKind = "tradingagents" | "vibedesk";

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

/** One node in the run's DAG. `seat` is always `""` for Vibe Trading (it is only meaningful for
 *  Trading Agents' fixed pipeline roles) -- render `role` or `label` when `seat` is empty rather than
 *  showing a blank. */
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
  /** Always `""` for Vibe Trading -- `final_rating` is Trading Agents' Buy/Hold/Sell scale, and Vibe
   *  Trading has no equivalent rating to report. */
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
  /** e.g. `"investment_committee · NVDA"` -- already composed server-side, render as-is. */
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

// --- Vibe Trading's own types ---------------------------------------------------------------------

/** One selectable worker model: `id` is the wire value passed as `StartSwarmRequest.model` (and what
 *  pins a specific version), `label` the name shown in the picker. Mirrors
 *  `api/tradingagents.ts`'s own `ModelOption` field for field -- the two desks share the identical
 *  catalogue server-side (`app.vibedesk.service.build_config` reuses
 *  `app.tradingagents.service.AVAILABLE_MODELS` verbatim), so this type must stay in lockstep with
 *  that one even though, per this module's docstring, it is not literally imported from it. */
export interface ModelOption {
  id: string;
  label: string;
}

/** `GET /config`'s response body: the default worker model and the catalogue a run may pick from --
 *  the same catalogue Trading Agents' own `/config` exposes (`TradingAgentsConfig.available_models`
 *  in `api/tradingagents.ts`), plus Vibe's own default. Fetch once on mount, like
 *  `tradingAgentsApi.config()`. */
export interface VibeConfig {
  default_model: string;
  available_models: ModelOption[];
}

export interface PresetSummary {
  name: string;
  label: string;
  blurb: string;
  agent_count: number;
  layer_count: number;
}

export interface PresetAgent {
  id: string;
  label: string;
  blurb: string;
}

export interface PresetTask {
  id: string;
  agent_id: string;
  depends_on: string[];
  layer: number;
}

export interface PresetVariable {
  name: string;
  label: string;
  required: boolean;
  default: string;
}

export interface PresetDetail extends PresetSummary {
  agents: PresetAgent[];
  tasks: PresetTask[];
  variables: PresetVariable[];
}

/** `POST /runs` body. `preset` is the only required field -- everything else, including which of
 *  `symbol`/`question` a given preset actually reads, is between the preset's own prompts and the
 *  agent layer; nothing in `PresetDetail` says which of the two a preset expects (see this module's
 *  own note in `VibeTrading.tsx` on that gap), so the run form sends whichever the reader filled in. */
export interface StartSwarmRequest {
  preset: string;
  symbol?: string;
  question?: string;
  variables?: Record<string, string>;
  budget_usd?: DecimalString;
  model?: string;
  /** Opt-in to today's live quote and 5-minute bars instead of the stored end-of-day close. Default
   *  `false`. Mirrors `StartRunRequest.live` in `@/api/tradingagents` field for field -- see that
   *  module's own docstring on the `trade_date`-must-be-today `422`. */
  live?: boolean;
}

/** `GET /api/agents/health` -- shared by both desks, owned by neither. Mirrors
 *  `backend/app/api/agents.py`'s `AgentHealth` model field for field. Never a `5xx`: the backend's own
 *  docstring guarantees this endpoint degrades to `available: false` with a `reason` rather than
 *  throwing, so callers do not need special error handling beyond the ordinary network-failure case. */
export interface AgentHealth {
  available: boolean;
  credential_source: string;
  reason: string;
  model: string;
  sdk_installed: boolean;
}

const BASE = "/api/vibedesk";

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

/** Whether a poll loop over `GET /runs/{run_id}` should keep going -- mirrors `isLoopActive` in
 *  `api/evolution.ts`/`isTerminalJobStatus` in `api/competition.ts`. `"queued"` and `"running"` keep
 *  polling; every other state is a settled end state. An unrecognised state is treated as active, the
 *  same conservative default those two make, so a live run's updates are never silently dropped over a
 *  value this build has not been taught to end on. */
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

export const vibeDeskApi = {
  /** The desk's own configuration: the default worker model and the models a run may pick from.
   *  Mirrors `tradingAgentsApi.config()` -- fetch once on mount, this rarely changes mid-session. */
  config: (signal?: AbortSignal) =>
    requestJson<VibeConfig>(`${BASE}/config`, { signal: signal ?? null }),

  /** Every preset desk on offer, summary only -- fetch `preset(name)` for its agents/tasks/variables. */
  presets: (signal?: AbortSignal) =>
    requestJson<{ presets: PresetSummary[] }>(`${BASE}/presets`, { signal: signal ?? null }),

  /** One preset's full detail: its committee, its task DAG, and the variables its run form must
   *  collect. `404` when `name` does not match a known preset. */
  preset: (name: string, signal?: AbortSignal) =>
    requestJson<PresetDetail>(`${BASE}/presets/${encodeURIComponent(name)}`, {
      signal: signal ?? null,
    }),

  /** Starts a swarm run. Returns the `202` body immediately, before a single stage has run -- poll
   *  `getRun` for live progress. `409` means a run is already in flight (single-slot registry), `422`
   *  an invalid symbol or unknown preset variable, `503` the agent layer being unavailable (its body
   *  names the reason -- `agentHealth()` below is how the page checks this *before* letting a reader
   *  click Start, but the run endpoint enforces it independently too). */
  startRun: (body: StartSwarmRequest, signal?: AbortSignal) =>
    requestJson<DeskRun>(`${BASE}/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: signal ?? null,
    }),

  /** Past and current runs, newest first, summary only. `limit` caps how many come back; omitted, the
   *  backend applies its own default of 25. */
  listRuns: (limit?: number, signal?: AbortSignal) =>
    requestJson<{ runs: DeskRunSummary[] }>(
      `${BASE}/runs${limit !== undefined ? `?limit=${encodeURIComponent(String(limit))}` : ""}`,
      { signal: signal ?? null },
    ),

  /** One run's full detail, including every stage's own output -- the poll target while a run is
   *  `queued`/`running`. `404` if `runId` is unknown. */
  getRun: (runId: string, signal?: AbortSignal) =>
    requestJson<DeskRun>(`${BASE}/runs/${encodeURIComponent(runId)}`, { signal: signal ?? null }),

  /** Cancels a run in flight. Returns the run with `state: "cancelled"` rather than an empty body, so
   *  the caller renders it exactly like any other poll result. */
  cancelRun: (runId: string, signal?: AbortSignal) =>
    requestJson<DeskRun>(`${BASE}/runs/${encodeURIComponent(runId)}`, {
      method: "DELETE",
      signal: signal ?? null,
    }),

  /** Is the agent layer usable right now, and why not if it isn't -- see `AgentHealth`'s own docstring.
   *  Not under `${BASE}`: this route is shared with Trading Agents and owned by neither desk. */
  agentHealth: (signal?: AbortSignal) =>
    requestJson<AgentHealth>(`/api/agents/health`, { signal: signal ?? null }),
};

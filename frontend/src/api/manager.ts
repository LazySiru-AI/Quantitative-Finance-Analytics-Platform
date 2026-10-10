/**
 * Typed client for the Manager tab.
 *
 * Phase 1: the deterministic, rule-derived "what changed" feed (`GET /changes`), the desk's own
 * status/config (`GET /config`) and the manual snapshot trigger (`POST /snapshot`).
 *
 * Phase C (this addition): the model-driven surfaces -- run + poll a grounded brief
 * (`POST /briefs`, `GET /runs/{run_id}`, `GET /briefs/latest`), approve/decline the commissions a
 * brief proposes (`POST /commissions/{id}/approve|decline`), and a multi-turn chat
 * (`GET|POST /chats`, `POST /chats/{id}/turns`). All of it must degrade gracefully with the agent
 * layer down -- see `ManagerConfig.agent_available` -- exactly like the Phase 1 feed already does.
 *
 * This wire contract is pinned by the brief that commissioned this module -- the backend is built
 * against these exact shapes, field for field. Do not rename a field to match this codebase's own
 * naming conventions elsewhere (`camelCase` vs the wire's `snake_case`) -- that mismatch is exactly
 * what a pinned contract exists to prevent. See `docs/AGENT-DESK-CONTRACT.md`'s "Manager Desk"
 * section, the pinned source of truth this module mirrors.
 *
 * `StageState`/`RunState`/`StageRecord`/`BudgetWire`/`DeskRun`/`GroundingIssue`/`GroundingVerdict`
 * are the same wire shapes `api/workflow.ts`/`api/tradingagents.ts`/`api/vibedesk.ts` each carry
 * their own copy of -- duplicated here too, per this codebase's "one copy of shared wire vocabulary
 * per API module" convention (see `api/workflow.ts`'s own docstring). `DeskRun.kind` is narrowed to
 * the literal `"manager"` here, since this module only ever fetches this desk's own runs.
 *
 * Carries its own local `requestJson<T>`, same five-line shape as every other API module in this
 * codebase (`api/workflow.ts`, `api/competition.ts`, `api/evolution.ts`, `api/vibedesk.ts`) --
 * duplicated on purpose, not an oversight. See `api/workflow.ts`'s own docstring for the reasoning:
 * one copy of shared wire vocabulary per API module. `requestVoid` (below it) is the same shape for
 * the one endpoint with no response body (`DELETE /chats/{id}` -> `204`), matching
 * `api/personas.ts`'s own `requestVoid`.
 */
import { ApiRequestError } from "@/api/client";

export type Scope = "owner" | "member";

export type Window = "yesterday" | "week" | "custom";

export type Severity = "attention" | "notable" | "fyi";

export type Area =
  | "account"
  | "tax"
  | "paperdesk"
  | "persona_books"
  | "persona_traders"
  | "research"
  | "desks"
  | "live"
  | "personas"
  | "market"
  | "events"
  | "news"
  | "data"
  | "activity";

export interface SourceRef {
  kind: "run" | "note" | "symbol" | "event" | "gen" | "snapshot" | "txn" | "persona" | "seat";
  id: string;
  label: string;
}

export interface ChangeItem {
  id: string;
  area: Area;
  rule: string;
  severity: Severity;
  headline: string;
  detail: string;
  as_of: string | null;
  observed_at: string | null;
  figures: Record<string, string>;
  source_refs: SourceRef[];
}

export interface ChangeSet {
  window: Window;
  since: string | null;
  until: string;
  scope: Scope;
  items: ChangeItem[];
  sections_missing: string[];
  prior_snapshot: string | null;
  warnings: string[];
}

export interface Caps {
  brief_usd: string;
  commission_usd: string;
  chat_usd: string;
  daily_usd: string;
}

export interface ManagerConfig {
  agent_available: boolean;
  agent_reason: string;
  autonomy: string;
  unattended_kinds: string[];
  autopilot_enabled: boolean;
  brief_time_et: string;
  caps: Caps;
  last_brief_at: string | null;
  last_snapshot_at: string | null;
  spent_today_usd: string;
}

export interface SnapshotResult {
  as_of: string;
  scope: Scope;
  generated_at: string;
}

// --- Brief / Synthesis / Commission (Phase C -- mirrors docs/AGENT-DESK-CONTRACT.md "Manager Desk") --

export interface GroundingIssue {
  kind: "ungrounded_number" | "no_evidence" | "empty_output";
  detail: string;
}

/** Local copy, not an import -- the contract lists this as a shared shape every desk module already
 *  carries its own copy of (`api/workflow.ts`, `api/tradingagents.ts`, `api/vibedesk.ts`,
 *  `api/personas.ts`); this module's copy is no different. */
export interface GroundingVerdict {
  ok: boolean;
  issues: GroundingIssue[];
  attempts: number;
  degraded: boolean;
  checked_tokens: number;
}

export interface BriefBullet {
  text: string;
  source_refs: SourceRef[];
}

/** No `instruction` field, by design (see the contract) -- this is a model's descriptive synthesis,
 *  never a directive. `caveat` is the not-advice line for the brief specifically and must always
 *  render, unconditionally, same rule as `manager.notAdvice` for the page as a whole. */
export interface Synthesis {
  assessment: BriefBullet[];
  agreements: BriefBullet[];
  conflicts: BriefBullet[];
  risks: BriefBullet[];
  open_questions: BriefBullet[];
  caveat: string;
}

export type CommissionKind = "tradingagents" | "vibedesk" | "workflow" | "persona_chat";

export type CommissionState =
  | "proposed"
  | "approved"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "declined";

/** One piece of follow-up research the manager proposes handing to a child desk. `state ===
 *  "proposed"` is the only state a reader can act on (approve/decline) -- every other state is the
 *  desk's own record of what happened after. Approving spends the child desk's own budget, not just
 *  a click -- render that plainly, not just the button. */
export interface Commission {
  commission_id: string;
  kind: CommissionKind;
  params: Record<string, unknown>;
  rationale: string;
  budget_usd: string;
  state: CommissionState;
  child_run_id: string | null;
  child_summary: string;
  source_refs: SourceRef[];
}

export interface DataHealth {
  stale: string[];
  unknown: string[];
}

export interface Brief {
  brief_id: string;
  run_id: string;
  scope: Scope;
  window: Window;
  as_of: string;
  generated_at: string;
  attention: ChangeItem[];
  changes: ChangeSet;
  synthesis: Synthesis;
  commissions: Commission[];
  data_health: DataHealth;
  degraded: boolean;
  grounding: GroundingVerdict;
  cost_usd: string;
  final_md: string;
}

// --- DeskRun (Phase C -- mirrors `api/workflow.ts`'s own copy; this module's `kind` is always
//     `"manager"`, since `/api/manager/runs` only ever returns this desk's own runs) -------------

export type StageState =
  | "pending"
  | "running"
  | "succeeded"
  | "degraded"
  | "failed"
  | "blocked"
  | "skipped";

export type RunState = "queued" | "running" | "succeeded" | "failed" | "cancelled";

/** One node in the run's DAG -- `MANAGER_STAGES` (`collect, triage, synthesis, research_plan,
 *  commission, brief`) per the contract's pinned vocabulary; `seat` is `""` for every one of those
 *  (all run-level, no per-child-desk seats at this layer). */
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
  cost_usd: string;
  error: string;
}

export interface BudgetWire {
  cap_usd: string;
  spent_usd: string;
  calls: number;
}

export interface DeskRun {
  run_id: string;
  kind: "manager";
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

/** What `runs` returns -- never carries `stages`/`final_md`/`config`, fetch `run` for those. Mirrors
 *  `DeskRunSummary` in `api/workflow.ts` field for field (the contract's own name for this shape);
 *  kept as its own type here, `ManagerRunSummary`, per this module's "one copy per API module"
 *  convention. */
export interface ManagerRunSummary {
  run_id: string;
  kind: "manager";
  state: RunState;
  label: string;
  created_at: string;
  completed_at: string | null;
  degraded: boolean;
  error: string;
  final_rating: string;
  cost_usd: string;
  stages_total: number;
  /** succeeded + degraded, per the contract -- not the same as "not pending/blocked". */
  stages_done: number;
}

/** Whether a poll loop over `GET /runs/{run_id}` should keep going -- mirrors `isRunActive` in
 *  `api/workflow.ts`/`api/vibedesk.ts`/`api/tradingagents.ts`. `"queued"`/`"running"` keep polling;
 *  every other state is a settled end state. An unrecognised state is treated as active, the same
 *  conservative default those siblings make, so a live run's updates are never silently dropped. */
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

// --- Manager chat (Phase C) ----------------------------------------------------------------------

/** One question/answer exchange. `commissions` are any new commissions this specific turn proposed
 *  (in addition to whatever a brief already proposed) -- render them the same way a brief's own
 *  commissions render. `grounding`/`degraded` are the same fact denormalised twice on the wire (one
 *  model call, one verdict), same rule as `PersonaChat.tsx`'s `ChatTurn`. */
export interface ManagerChatTurn {
  turn_id: string;
  asked_at: string;
  question: string;
  answer: string;
  source_refs: SourceRef[];
  commissions: Commission[];
  refreshed: boolean;
  grounding: GroundingVerdict;
  degraded: boolean;
  cost_usd: string;
}

export interface ManagerChatThread {
  thread_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  turn_count: number;
  spent_usd: string;
  turns: ManagerChatTurn[];
}

const BASE = "/api/manager";

/** Same five-line contract as every other API module's `requestJson` -- see `api/workflow.ts`'s own
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

/** For the one endpoint here with no response body (`DELETE /chats/{id}` -> `204`) -- `requestJson`
 *  would fail trying to parse an empty body as JSON. Matches `api/personas.ts`'s own `requestVoid`. */
async function requestVoid(path: string, init?: RequestInit): Promise<void> {
  const response = await fetch(path, {
    headers: { Accept: "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new ApiRequestError(response.status, body || response.statusText);
  }
}

export const managerApi = {
  /** The desk's own status: whether the model layer is up (and why not, when it isn't), autonomy
   *  mode, spend caps and today's spend, and the last brief/snapshot timestamps. Phase 1 renders
   *  this even with `agent_available: false` -- the deterministic change feed does not depend on it. */
  config: (signal?: AbortSignal) =>
    requestJson<ManagerConfig>(`${BASE}/config`, { signal: signal ?? null }),

  /** The rule-derived change feed for one window. `date` is only meaningful for `window: "custom"`
   *  -- Phase 1's UI never sends it (no date picker yet), so it is optional and omitted entirely
   *  rather than sent as `undefined` when absent. */
  changes: (params: { window: Window; date?: string }, signal?: AbortSignal) => {
    const query = new URLSearchParams();
    query.set("window", params.window);
    if (params.date !== undefined) query.set("date", params.date);
    return requestJson<ChangeSet>(`${BASE}/changes?${query.toString()}`, {
      signal: signal ?? null,
    });
  },

  /** Manually triggers a snapshot right now, independent of the daily scheduled one. Returns just
   *  enough to confirm it happened (`as_of`/`scope`/`generated_at`) -- callers refetch `changes`
   *  themselves afterward rather than this method trying to hand back a full `ChangeSet`. */
  snapshot: (signal?: AbortSignal) =>
    requestJson<SnapshotResult>(`${BASE}/snapshot`, {
      method: "POST",
      signal: signal ?? null,
    }),

  // --- Brief (Phase C) --------------------------------------------------------------------------

  /** Starts a grounded brief run. Returns the `202` body immediately, before a single stage has run
   *  -- poll `run` for live progress, matching `workflowApi.startRun`'s own contract. `date` is only
   *  meaningful alongside `window: "custom"`. `409` a manager run is already in flight (single-slot),
   *  `503` the agent layer being unavailable (check `config().agent_available` first), `429` the
   *  daily spend cap. */
  startBrief: (body: { window?: Window; date?: string } = {}, signal?: AbortSignal) =>
    requestJson<DeskRun>(`${BASE}/briefs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: signal ?? null,
    }),

  /** Past and current manager runs, newest first, summary only. */
  runs: (signal?: AbortSignal) =>
    requestJson<{ runs: ManagerRunSummary[] }>(`${BASE}/runs`, { signal: signal ?? null }),

  /** One run's full detail, including every stage -- the poll target while `state` is
   *  `"queued"`/`"running"` (`isRunActive`). */
  run: (runId: string, signal?: AbortSignal) =>
    requestJson<DeskRun>(`${BASE}/runs/${encodeURIComponent(runId)}`, { signal: signal ?? null }),

  /** Cancels a run in flight. Returns the run with `state: "cancelled"` rather than an empty body,
   *  so the caller renders it exactly like any other poll result. */
  cancelRun: (runId: string, signal?: AbortSignal) =>
    requestJson<DeskRun>(`${BASE}/runs/${encodeURIComponent(runId)}/cancel`, {
      method: "POST",
      signal: signal ?? null,
    }),

  /** The most recent finished brief, `404` when none exists yet -- callers should treat a 404 here
   *  as "no brief yet", not as an error to surface as a red banner. */
  latestBrief: (signal?: AbortSignal) =>
    requestJson<Brief>(`${BASE}/briefs/latest`, { signal: signal ?? null }),

  brief: (briefId: string, signal?: AbortSignal) =>
    requestJson<Brief>(`${BASE}/briefs/${encodeURIComponent(briefId)}`, { signal: signal ?? null }),

  // --- Commissions (Phase C) ---------------------------------------------------------------------

  /** Approves a proposed commission -- starts the child run. Spends that commission's own budget;
   *  the caller must say so before this is clicked, not just after. */
  approveCommission: (commissionId: string, signal?: AbortSignal) =>
    requestJson<Commission>(`${BASE}/commissions/${encodeURIComponent(commissionId)}/approve`, {
      method: "POST",
      signal: signal ?? null,
    }),

  declineCommission: (commissionId: string, signal?: AbortSignal) =>
    requestJson<Commission>(`${BASE}/commissions/${encodeURIComponent(commissionId)}/decline`, {
      method: "POST",
      signal: signal ?? null,
    }),

  // --- Chat (Phase C) -----------------------------------------------------------------------------

  /** Thread list, newest first -- each entry's `turns` is `[]` (fetch `chat` for a thread's turns). */
  chats: (signal?: AbortSignal) =>
    requestJson<ManagerChatThread[]>(`${BASE}/chats`, { signal: signal ?? null }),

  createChat: (signal?: AbortSignal) =>
    requestJson<ManagerChatThread>(`${BASE}/chats`, { method: "POST", signal: signal ?? null }),

  chat: (threadId: string, signal?: AbortSignal) =>
    requestJson<ManagerChatThread>(`${BASE}/chats/${encodeURIComponent(threadId)}`, {
      signal: signal ?? null,
    }),

  deleteChat: (threadId: string, signal?: AbortSignal) =>
    requestVoid(`${BASE}/chats/${encodeURIComponent(threadId)}`, {
      method: "DELETE",
      signal: signal ?? null,
    }),

  /** Asks one question in a thread. `refresh: true` re-collects the underlying snapshot before
   *  answering ("refresh data first" in the composer) -- omitted, the model answers off the thread's
   *  existing context. */
  sendTurn: (
    threadId: string,
    body: { question: string; refresh?: boolean },
    signal?: AbortSignal,
  ) =>
    requestJson<ManagerChatTurn>(`${BASE}/chats/${encodeURIComponent(threadId)}/turns`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: signal ?? null,
    }),
};

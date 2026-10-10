/**
 * Typed client for the live-quote decision daemon under `/api/agentdesk/live` -- shared by the
 * "Live (today's quote)" opt-in on the Trading Agents and Vibe Trading run forms (`liveHint`) and
 * the Live Decisions panel on Trading Agents (daemon status, recent decisions, manual "Decide now").
 *
 * Carries its own local `requestJson<T>`, the same five-line shape every other API module in this
 * codebase duplicates rather than imports -- see `@/api/tradingagents`'s own docstring for why.
 *
 * Money crosses the wire as a `DecimalString`, never a JSON number -- same rule as every other
 * module here (`@/api/client`'s own docstring): `cap_usd`, `cost_usd`, `price` are `DecimalString`.
 *
 * `LiveDecisionRecord.stance`/`.source` are closed unions of today's known values, but per this
 * repo's own rule against a throwing exhaustiveness check over server-supplied data (see
 * `closed-unions-over-server-data-kill-pages` in this repo's history -- a throwing check over a
 * server string took a whole page down before), a value outside either union must render with a
 * neutral fallback, never throw. `LiveDecisionsPanel.tsx` is the one caller and does exactly that.
 */
import { ApiRequestError, type DecimalString } from "@/api/client";

/** `GET /api/agentdesk/live/status`. */
export interface LiveStatus {
  enabled: boolean;
  running: boolean;
  healthy: boolean | null;
  market_state: string | null;
  last_tick_at: string | null;
  next_wake_at: string | null;
  ticks: number;
  decisions_today: number;
  consecutive_failures: number;
  symbols: string[];
  interval_minutes: number;
  cap_usd: DecimalString;
}

/** One decision the live daemon (or a manual `decideNow` call) recorded. */
export interface LiveDecisionRecord {
  decided_at: string;
  symbol: string;
  stance: "buy" | "sell" | "hold" | "no_action";
  confidence: number;
  rationale: string;
  horizon: string;
  price: DecimalString | null;
  quoted_at: string | null;
  market_state: string | null;
  grounded: boolean;
  degraded: boolean;
  cost_usd: DecimalString;
  model: string;
  source: "daemon" | "manual";
  call_ids: string[];
}

/** `GET /api/agentdesk/live/decisions`. */
export interface LiveDecisionsResponse {
  decisions: LiveDecisionRecord[];
}

/** `POST /api/agentdesk/live/decide` body. */
export interface DecideNowRequest {
  symbol: string;
}

/** `POST /api/agentdesk/live/decide`'s `200` body. */
export interface DecideNowResponse {
  decision: LiveDecisionRecord;
}

const BASE = "/api/agentdesk/live";

/** Same five-line contract as every other API module's `requestJson` -- see `@/api/tradingagents`'s
 *  own copy's docstring for why it is duplicated rather than imported. */
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

export const liveDecisionsApi = {
  /** Daemon status: whether the live-quote loop is enabled/running/healthy, its cadence, and how
   *  many decisions it has made today. Never expected to 404 -- see this module's docstring. */
  status: (signal?: AbortSignal) =>
    requestJson<LiveStatus>(`${BASE}/status`, { signal: signal ?? null }),

  /** Recent decisions, optionally scoped to one `symbol` and capped at `limit`. Newest first, per
   *  the backend's own order -- not re-sorted here. */
  decisions: (symbol?: string, limit?: number, signal?: AbortSignal) => {
    const params = new URLSearchParams();
    if (symbol) params.set("symbol", symbol);
    if (limit !== undefined) params.set("limit", String(limit));
    const qs = params.toString();
    return requestJson<LiveDecisionsResponse>(`${BASE}/decisions${qs ? `?${qs}` : ""}`, {
      signal: signal ?? null,
    });
  },

  /** Runs one manual decision for `symbol` right now -- 10-60s round trip. `422` names a bad symbol,
   *  `429` means the spend cap is reached, `503` means the agent layer is unavailable. The caller
   *  (`LiveDecisionsPanel.tsx`) renders any failure via `describeError` from `@/api/client`, same as
   *  every other mutation in this codebase. */
  decideNow: (symbol: string, signal?: AbortSignal) =>
    requestJson<DecideNowResponse>(`${BASE}/decide`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol } satisfies DecideNowRequest),
      signal: signal ?? null,
    }),
};

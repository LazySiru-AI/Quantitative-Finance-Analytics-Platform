/**
 * Typed client for the local navigation-telemetry endpoints (`app.api.telemetry_nav`).
 *
 * `record` posts a batch of route-change events; the backend resolves the caller's role itself from
 * the session cookie, so the payload here never carries a username or role -- just where the caller
 * went and when. `summary` reads the owner-only rollup for the Data > Health panel.
 *
 * Same five-line `requestJson` shape as every other API module here (`@/api/i18n`, `@/api/personas`,
 * ...) -- duplicated rather than imported, per this codebase's "one copy per module" convention.
 */
import { ApiRequestError } from "@/api/client";

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

/** One route-change hit, as the browser reports it -- no role, no username. */
export interface NavEvent {
  path: string;
  tab?: string;
  ts: string;
}

export interface NavRecordResult {
  recorded: number;
}

export interface NavRouteSummary {
  path: string;
  tab: string | null;
  hits: number;
  last_ts: string;
}

export interface NavSummary {
  days: number;
  since: string;
  total: number;
  routes: NavRouteSummary[];
}

export const telemetryApi = {
  record(events: NavEvent[]): Promise<NavRecordResult> {
    return requestJson<NavRecordResult>("/api/telemetry/nav", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ events }),
    });
  },

  summary(days = 30): Promise<NavSummary> {
    return requestJson<NavSummary>(`/api/telemetry/nav/summary?days=${days}`);
  },
};

/**
 * Typed client for the operator-only health endpoints the Data page's Data-health tab reads.
 *
 * Deliberately its own small module rather than additions to `@/api/market`: the two status
 * endpoints below mirror `dict[str, Any]` FastAPI return types (`app.main.market_refresh_status`,
 * `app.api.market.social_scheduler_status`) with no Pydantic response model, so there is no shared
 * shape or helper to fold into `@/api/market`'s existing (typed, `response_model`-backed) contract
 * -- adding them there would mean editing a shared, actively-used module for two routes nothing
 * else in this app currently consumes. Field names below are copied from each status dataclass's
 * own `to_dict()` (`app.market.refresh.RefreshProgress`, `app.market.social_history.
 * SocialSchedulerStatus`), not from a response model, since neither route declares one.
 *
 * Both status endpoints share one contract worth stating once: **they always answer.** Neither
 * 404s when its feature is off or has never run in this process -- `running`/`total_ticks` just
 * read as the empty/zero state. A caller may poll either unconditionally.
 *
 * `triggerRefresh`/`freshness` are the two additions backing the Fetch-data-now button and the
 * per-source freshness table: `POST /api/market/refresh` (202, starts the sweep this module
 * already polls the status of) and `GET /api/data/freshness` (200, one row per data source this
 * app reads from). Both are pinned contracts shared with the backend worker building the routes,
 * not inferred from a running server -- `FreshnessSource.key`/`.status` are closed unions the
 * backend may in practice emit a value outside of (a source added server-side before this file is
 * updated), so every render site here must treat them as "known subset of a wider server string",
 * never exhaustively switch and throw on the rest.
 *
 * `retention` is the odd one out of the module's own opening claim: `GET /api/data/retention` is
 * **not** owner-only (it backs the About panel, which every signed-in user can open), and it is a
 * typed Pydantic-free `dict` for the same reason the other two are -- see `app.api.data_admin`'s own
 * docstring for the hard "counts and generic names only" contract that shape is held to.
 */

import { ApiRequestError } from "@/api/client";

/** `GET /api/market/refresh/status` -- progress of the background startup market-data sweep. */
export interface RefreshStatus {
  running: boolean;
  queued: number;
  refreshed: number;
  skipped_fresh: number;
  failed: number;
  /** `"SYMBOL:interval"` for up to a capped number of failures -- diagnostic detail on top of the
   *  exact `failed` count above, not a replacement for it. */
  failed_symbols: string[];
  /** `refreshed + skipped_fresh + failed`. */
  processed: number;
  /** `false` only when the sweep's own wall-time cap stopped it before the worklist was exhausted
   *  -- a partial sweep, never reported as finished. */
  complete: boolean;
  stopped_reason: string | null;
  /** `null` (not attempted yet), `"ok"` or `"failed"` -- the FRED/CNN macro snapshot, tracked
   *  separately from the per-symbol counters above. */
  macro_snapshot: string | null;
  /** `"pending"` until the social-snapshot pass runs, then `"<n> written, <m> failed"`, or
   *  `"failed"` if the whole pass could not open its store. */
  social_snapshots: string;
  /** ISO-8601 UTC, or `null` before the first sweep in this process. */
  started_at: string | null;
  finished_at: string | null;
  /** Set only if the sweep itself raised something its own per-symbol handling did not already
   *  catch. */
  error: string | null;
}

/** `GET /api/market/social/status` -- health of the recurring social-snapshot scheduler. */
export interface SocialStatus {
  /** `false` once `consecutive_all_failed_ticks` reaches `max_consecutive_all_failed_ticks`. A
   *  scheduler that has never ticked (`total_ticks === 0`) reads `true` -- not yet run is not
   *  unhealthy. */
  healthy: boolean;
  total_ticks: number;
  last_tick_at: string | null;
  last_written: number;
  last_failed: number;
  consecutive_all_failed_ticks: number;
  max_consecutive_all_failed_ticks: number;
  /** Set when the most recent tick could not even open its store -- distinct from a per-symbol
   *  provider failure, which `last_failed` already counts. */
  last_error: string | null;
}

/** `POST /api/market/refresh` -- 202, starts the sweep (or reports one already running). */
export interface RefreshTriggerResult {
  started: boolean;
  /** Set only when `started` is `false`. */
  reason: "already_running" | null;
  status: RefreshStatus;
}

/**
 * One row of `GET /api/data/freshness`.
 *
 * `key`, `freshness_class`, `policy` and `status` are typed as closed unions of the values the
 * backend documents today, but this is a display contract, not a validated one: a caller must
 * render a value outside the union (a source or status the server adds later) with a neutral
 * fallback rather than throwing. See this module's docstring.
 */
export interface FreshnessSource {
  key:
    | "bars_daily"
    | "bars_intraday"
    | "macro_snapshot"
    | "calendar_events"
    | "fundamentals_edgar"
    | "institutions_filings"
    | "news"
    | "social_snapshots"
    | "live_quotes"
    | "ledger"
    | "persona_corpus";
  freshness_class: "day_frame" | "intraday" | "local";
  policy: "on_demand" | "startup_sweep" | "scheduled" | "streaming" | "computed" | "manual";
  provider: string;
  /** ISO-8601, or `null` if this source has never been populated. */
  last_updated: string | null;
  age_seconds: number | null;
  status: "fresh" | "stale" | "unknown" | "disabled" | "live";
  detail: string;
  /** `true` -- the Fetch-data-now button's sweep covers this source. */
  refreshable: boolean;
  enabled: boolean;
}

/** `GET /api/data/freshness` -- live feed transport, separate from the on-demand sources above. */
export interface LiveFeedStatus {
  enabled: boolean;
  transport: "poll" | "stream";
  running: boolean;
  /** `null` when the feed has never connected long enough to know. */
  healthy: boolean | null;
  watched: number;
  symbols: string[];
  market_state: string | null;
  last_snapshot_at: string | null;
  started_at: string | null;
}

/** `GET /api/data/freshness` -- the full report backing the Data-health freshness table. */
export interface FreshnessReport {
  as_of: string;
  sources: FreshnessSource[];
  refresh: RefreshStatus;
  live: LiveFeedStatus;
}

/**
 * `GET /api/data/retention` -- how much this instance has accumulated in each store it keeps,
 * behind the Data > About panel. Not owner-only (every signed-in user can open About), which is
 * exactly why the backend's own contract for this shape is "counts and generic store names only,
 * never a path or an account label" -- see `app.api.data_admin`'s module docstring.
 *
 * `desk_runs` is a count per `DeskKind` (`tradingagents` / `vibedesk` / `workflow` / `manager`
 * today), typed as `Record<string, number>` rather than a closed set of literal keys: a caller here
 * only ever sums or lists it, so there is no render site that needs to exhaustively switch on a key
 * and could be broken by the backend adding a fifth kind -- the same reasoning `FreshnessSource`'s
 * own docstring gives for its closed unions, applied by simply not creating a closed union at all
 * where nothing here needs one.
 */
export interface RetentionReport {
  ledger: { exists: boolean; transactions: number };
  auth: { users: number };
  manager_briefs: { count: number; oldest: string | null; newest: string | null };
  manager_chats: { count: number };
  persona_chats: { count: number };
  persona_vault_notes: { count: number };
  desk_runs: Record<string, number>;
  paperdesk_books: { count: number };
  i18n_cache: { present: boolean };
  /** Always `"manual"` today -- nothing in this application purges on a schedule. */
  retention_policy: string;
  /** Real `DELETE` route shapes (`"DELETE /api/personas/{slug}"`), never an instantiated id -- the
   *  panel links a reader to the page that hosts each control rather than rendering these literally. */
  purge_endpoints: string[];
}

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

export const dataAdminApi = {
  refreshStatus: (signal?: AbortSignal) =>
    requestJson<RefreshStatus>("/api/market/refresh/status", { signal: signal ?? null }),

  socialStatus: (signal?: AbortSignal) =>
    requestJson<SocialStatus>("/api/market/social/status", { signal: signal ?? null }),

  triggerRefresh: (signal?: AbortSignal) =>
    requestJson<RefreshTriggerResult>("/api/market/refresh", {
      method: "POST",
      signal: signal ?? null,
    }),

  freshness: (signal?: AbortSignal) =>
    requestJson<FreshnessReport>("/api/data/freshness", { signal: signal ?? null }),

  retention: (signal?: AbortSignal) =>
    requestJson<RetentionReport>("/api/data/retention", { signal: signal ?? null }),
};

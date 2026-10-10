/**
 * Typed client for the multi-timeframe rule research endpoints.
 *
 * Mirrors `docs/research/timeframes/06-interface-contract.md` sections 2 ("`RuleAccuracyCell` — the
 * atom") and 4 ("HTTP layer") field-for-field. Read that document before changing this file — it is
 * the frozen boundary between the service layer, the HTTP layer and this client, and a shape change
 * made unilaterally here breaks the other two silently.
 *
 * **Every numeric field in this module is a statistic, not money or a quantity, and that is
 * deliberate.** `@/api/paperdesk`, `@/api/portfolio` and `@/api/tax` carry money as a `DecimalString`
 * because a `Decimal` round-tripped through an IEEE double is a wrong ledger figure. `lift`,
 * `hit_rate`, `p_value`, `q_value` and friends below are plain JSON `number` instead, on purpose:
 * nothing here is summed against a cost basis or reconciled to the cent, every consumer (the matrix,
 * the drill-down chart) is float maths already, and wrapping these in `DecimalString` would force a
 * parse at every call site for zero accuracy gained. A future reader should not "fix" this module by
 * making it consistent with the money clients — the two contracts are answering different questions.
 *
 * **`sufficient === false` implies every measurement field is `null`** (contract §2, invariant 1):
 * `hit_rate`, `base_rate`, `lift`, both CI bounds, `p_value`, `q_value` and `cost_adjusted_edge` all
 * come back `null` together. The UI must treat `sufficient` as the single source of truth for "is
 * this cell a real measurement" and must never re-derive that question from whether a number happens
 * to be present — rendering code that checks `lift !== null` instead of `sufficient` would still be
 * correct today only because the service enforces the invariant upstream, which is the wrong place
 * to depend on it from.
 *
 * **`horizon_minutes` is the only field the UI may use to align cells across intervals** (contract
 * §5, rule 3). `horizon_bars` is comparable within one interval only — 20 bars is 100 minutes at 5m
 * and a month at 1d. Never sort, group, or join cells on `horizon_bars` across an interval boundary.
 */

import { ApiRequestError } from "@/api/client";
import type { Bar, IndicatorSeries, Interval } from "@/api/market";
import { t } from "@/i18n";

export type { Interval };

export type Scope = "symbol" | "sector" | "universe";
export type Regime = "all" | "rising" | "falling" | "flat";

/**
 * One rule, one interval, one scope, one horizon — mirrors contract §2's `RuleAccuracyCell` exactly.
 * `hit_rate`/`base_rate` are 0-1 fractions, matching the convention `@/api/rules`' `Evidence` already
 * uses for the same measurement — format with `formatRate`/`formatSignedRate` from that module rather
 * than a second copy.
 */
export interface RuleAccuracyCell {
  // identity
  rule_id: string;
  interval: Interval;
  scope: Scope;
  /** `"AAPL"` for `scope: "symbol"`, `"Technology"` for `"sector"`, `"ALL"` for `"universe"`. */
  scope_key: string;
  horizon_bars: number;
  horizon_minutes: number;
  horizon_label: string;

  // sample -- always present, even when `sufficient` is false. Describes the sample, not the
  // measurement, so showing `n_independent` beside an insufficient cell is honest and useful.
  n_raw: number;
  n_episodes: number;
  n_independent: number;
  sufficient: boolean;

  // measurement -- all `null` together whenever `sufficient` is false (contract §2 invariant 1)
  hit_rate: number | null;
  base_rate: number | null;
  /** hit_rate - base_rate. THE headline number — never render `hit_rate` alone. */
  lift: number | null;
  lift_ci_low: number | null;
  lift_ci_high: number | null;
  median_return: number | null;
  baseline_median_return: number | null;

  // significance
  p_value: number | null;
  /** Benjamini-Hochberg, computed once across the whole returned grid. */
  q_value: number | null;

  // costs
  cost_bps_assumed: number;
  cost_adjusted_edge: number | null;

  // provenance
  regime: Regime;
  first_bar: string;
  last_bar: string;
  /** Never `null` (contract §2 invariant 5) — empty array when clean. Must be reachable from the UI
   *  (tooltip or drill-down), per contract §5 rule 4. */
  warnings: readonly string[];
}

/**
 * `hit_rate - base_rate`, recomputed client-side rather than trusted blindly — mirrors `edgeOf` in
 * `@/api/rules`. `null` whenever either input is `null`, which per contract §2 invariant 1 is exactly
 * when `sufficient` is false; callers should still branch on `sufficient` directly rather than on
 * this function's result, since that is the field the service actually guarantees.
 */
export function liftOf(cell: RuleAccuracyCell): number | null {
  if (cell.hit_rate === null || cell.base_rate === null) return null;
  return cell.hit_rate - cell.base_rate;
}

/** Display word for a raw `Regime` wire value -- the enum itself stays an identifier. */
export function regimeLabel(regime: Regime): string {
  switch (regime) {
    case "all":
      return t("strategy.regime.all");
    case "rising":
      return t("strategy.regime.rising");
    case "falling":
      return t("strategy.regime.falling");
    case "flat":
      return t("strategy.regime.flat");
    default: {
      const _exhaustive: never = regime;
      void _exhaustive;
      return String(regime);
    }
  }
}

// --- /intervals -------------------------------------------------------------------------------

/** The seven intervals this feature covers, with retention and bars/session (contract §0). */
export interface IntervalInfo {
  interval: Interval;
  /** `null` for `1w`, which has no bars/session of its own — it is derived from daily. */
  bars_per_session: number | null;
  /** Contract §0's own words, verbatim: `"60 days"`, `"730 days"`, `"unbounded"`. */
  retention: string;
  bars_per_year: number;
}

// --- /universe ----------------------------------------------------------------------------------

/** One of the 20 liquid names in the frozen research universe (contract §1), with its sector. */
export interface UniverseEntry {
  symbol: string;
  sector: string;
}

// --- /matrix --------------------------------------------------------------------------------------

export interface MatrixQuery {
  symbols?: string[];
  sectors?: string[];
  intervals?: Interval[];
  rule_ids?: string[];
  horizon_minutes?: number;
  scope?: Scope;
  cost_bps?: number;
}

/**
 * How much of the grid is actually measurable — deliberately surfaced as the honest headline for
 * this feature (contract §4), not buried beside the cells themselves.
 */
export interface MatrixCoverage {
  symbols: number;
  intervals: number;
  rules: number;
  cells_total: number;
  cells_sufficient: number;
}

export interface MatrixResponse {
  cells: RuleAccuracyCell[];
  generated_at: string;
  coverage: MatrixCoverage;
  warnings: string[];
}

// --- /signal --------------------------------------------------------------------------------------

export interface SignalQuery {
  symbol: string;
  interval: Interval;
  rule_id: string;
}

/**
 * Mirrors contract §3's `SignalTrace`, for the drill-down chart. `fired_at` is rising edges only —
 * the same de-duplication the accuracy path uses to produce `n_episodes` — so the markers drawn from
 * it match the sample the matrix cell reports; mapping every `true` bar instead would draw far more
 * markers than the cell's own `n_episodes` implies.
 */
export interface SignalTrace {
  symbol: string;
  interval: Interval;
  rule_id: string;
  expression: string;
  bars: Bar[];
  indicators: IndicatorSeries[];
  fired_at: string[];
  warmup_until: string | null;
}

// --- job endpoints (async full sweep) ---------------------------------------------------------

/**
 * The frozen contract (§4) specifies only that `POST /matrix/jobs` returns `{job_id}` and that the
 * status endpoint is polled for "status/result", mirroring `app.tournament.jobs`'s submit/poll idiom
 * (contract §3's "Signal trace" section references the same jobs module for the async sweep). The
 * exact field names below are this client's own inference from that idiom, not a shape the contract
 * spells out field-for-field the way §2's `RuleAccuracyCell` is — flagged as under-specified in this
 * slice's delivery report. `startSweep`/`sweepStatus` are wired but not exercised by the matrix view
 * in this slice, which only calls the synchronous `/matrix` endpoint (contract §8: a handful of
 * symbols is comfortably synchronous; a full-universe sweep is the case these two exist for).
 */
export interface MatrixJobAccepted {
  job_id: string;
}

export type MatrixJobState = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface MatrixJobStatus {
  job_id: string;
  status: MatrixJobState;
  completed_cells: number;
  total_cells: number;
  result: MatrixResponse | null;
  error: string | null;
}

// --- requests -----------------------------------------------------------------------------------

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new ApiRequestError(response.status, detailOf(body) || response.statusText);
  }
  return (await response.json()) as T;
}

/** FastAPI wraps an `HTTPException` message in `{"detail": ...}` -- unwrapped here the same way
 *  `@/api/paperdesk`'s `detailOf` does, so a 422 from the `MAX_SYNC_PAIRS` guard (contract §4)
 *  surfaces its specific reason instead of a raw JSON blob. */
function detailOf(body: string): string {
  if (!body) return "";
  try {
    const parsed: unknown = JSON.parse(body);
    if (parsed && typeof parsed === "object" && "detail" in parsed) {
      const detail = (parsed as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
      return JSON.stringify(detail);
    }
  } catch {
    // Not JSON. The raw body is still the best thing to show.
  }
  return body;
}

function query(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value));
  }
  return search.toString();
}

/** `symbols`/`sectors`/`intervals`/`rule_ids` are repeated query params (contract §4's `GET
 *  /matrix` param table), not a single csv value -- built separately from `query()` above because
 *  each needs zero-or-more `append()` calls rather than one `set()`. */
function matrixQueryString(params: MatrixQuery): string {
  const search = new URLSearchParams();
  for (const s of params.symbols ?? []) search.append("symbols", s);
  for (const s of params.sectors ?? []) search.append("sectors", s);
  for (const i of params.intervals ?? []) search.append("intervals", i);
  for (const r of params.rule_ids ?? []) search.append("rule_ids", r);
  if (params.horizon_minutes !== undefined) {
    search.set("horizon_minutes", String(params.horizon_minutes));
  }
  if (params.scope !== undefined) search.set("scope", params.scope);
  if (params.cost_bps !== undefined) search.set("cost_bps", String(params.cost_bps));
  return search.toString();
}

export const timeframesApi = {
  intervals: (signal?: AbortSignal) =>
    requestJson<IntervalInfo[]>("/api/timeframes/intervals", { signal: signal ?? null }),

  universe: (signal?: AbortSignal) =>
    requestJson<UniverseEntry[]>("/api/timeframes/universe", { signal: signal ?? null }),

  matrix: (params: MatrixQuery, signal?: AbortSignal) =>
    requestJson<MatrixResponse>(`/api/timeframes/matrix?${matrixQueryString(params)}`, {
      signal: signal ?? null,
    }),

  signal: (params: SignalQuery, signal?: AbortSignal) =>
    requestJson<SignalTrace>(
      `/api/timeframes/signal?${query({
        symbol: params.symbol,
        interval: params.interval,
        rule_id: params.rule_id,
      })}`,
      { signal: signal ?? null },
    ),

  /** Full sweep, too large for the synchronous `/matrix` path (contract §4's `MAX_SYNC_PAIRS`
   *  guard). Returns immediately with a job id to poll via `sweepStatus`. */
  startSweep: (params: MatrixQuery) =>
    requestJson<MatrixJobAccepted>("/api/timeframes/matrix/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    }),

  sweepStatus: (jobId: string, signal?: AbortSignal) =>
    requestJson<MatrixJobStatus>(`/api/timeframes/matrix/jobs/${encodeURIComponent(jobId)}`, {
      signal: signal ?? null,
    }),
};

/**
 * Typed client for the backtest workbench.
 *
 * Mirrors `backend/app/backtest/models.py` and `backend/app/api/backtest.py` field for field.
 * `frontend/src/api/rules.ts` is the sibling contract for Phase 6; its three rendering rules — never
 * show a hit rate without its baseline, never render `null` as `0.0%`, never style "unknown" like
 * "false" — hold verbatim here and are not restated.
 *
 * Four things are specific to this surface, and each is a way the workbench could mislead someone
 * who is, by the time they reach this page, deliberately looking for an edge.
 *
 * **The trial count belongs next to the result, not in a footnote.** `ScanResult.trials` is the
 * denominator every `q_value` on the page depends on. A table showing four discoveries without
 * saying they came out of eighty tests has shown the reader a different number than the one that
 * exists.
 *
 * **`discovery` is not "true".** It means `q_value <= alpha` — an expected-false-discovery-rate
 * statement about the whole set, conditional on this scan being the entire family tested. At
 * `alpha = 0.10`, roughly one in ten flagged entries is expected to be noise, and the UI should say
 * so where the badge is.
 *
 * **Exploratory output must not look like a result.** `ReverseConditioning` deliberately has no
 * `hit_rate`, `p_value` or `q_value` field, because the moves were selected by looking at the
 * outcome. Do not render it with the same component as `EventStudy`, and do not compute a rate from
 * its counts to fill the gap.
 *
 * **A guard that did not run is a failure.** `GuardStatus` has three values and only `"passed"`
 * permits rendering the numbers. `"unverified"` must be styled as a problem, not as a pending state
 * — see `guardOk`.
 */

import { ApiRequestError } from "@/api/client";
import type { Interval, MarketWarning } from "@/api/market";
import type { Entry } from "@/api/rules";
import { t } from "@/i18n";

export type { Entry, Interval, MarketWarning };

/**
 * Forward-return horizons in bars, matching `STUDY_HORIZONS` in the backend contract.
 * One longer than the decision table's `HORIZONS`, which omits 10.
 */
export const STUDY_HORIZONS = [1, 5, 10, 20, 60] as const;
export type StudyHorizon = (typeof STUDY_HORIZONS)[number];

/** Independent-sample size below which a result carries a small-sample caveat. */
export const SMALL_SAMPLE_THRESHOLD = 30;

// --- distributions ----------------------------------------------------------

/**
 * The shape of a return sample. Percentiles rather than mean ± sigma: these samples are skewed and
 * fat-tailed, and `p05` is the number that answers "how bad was the bad case" — the one a mean
 * hides.
 */
export interface Distribution {
  count: number;
  mean: number | null;
  median: number | null;
  /** Sample standard deviation. `null` below two observations, where it is undefined, not zero. */
  stdev: number | null;
  p05: number | null;
  p25: number | null;
  p75: number | null;
  p95: number | null;
  minimum: number | null;
  maximum: number | null;
}

// --- drawdown ---------------------------------------------------------------

/**
 * Which price series a depth was measured on. Never render a depth without it: the three give
 * materially different answers for the same instrument and none of them is wrong.
 */
export type DrawdownBasis = "close" | "adj_close" | "intraday";

export interface DrawdownEpisode {
  peak_date: string;
  peak_value: number;
  trough_date: string;
  trough_value: number;
  /**
   * Negative fraction: `-0.82` is an 82% decline.
   *
   * **Peak to trough — the worst the episode ever got, not where it is now.** For a live episode
   * those are different numbers, and rendering this one under a "current drawdown" label said XLE
   * was 15.6% below its peak while the gap was 1.04%. Use `depth_now` for "now".
   */
  depth: number;
  bars_to_trough: number;
  recovery_date: string | null;
  /** `null` while still underwater — deliberately not the bars elapsed so far. */
  bars_to_recovery: number | null;
  /** A **lower bound** when `still_underwater`; the UI must say so. */
  bars_underwater: number;
  still_underwater: boolean;
  /**
   * Peak to the latest observation. `null` unless `still_underwater` — a recovered episode has no
   * current depth, and `0` would claim it is sitting exactly at its peak today.
   */
  depth_now: number | null;
  /** The observation `depth_now` is measured from, so the figure can be checked. */
  last_value: number | null;
  /** As-of for `depth_now`. Differs from the series' last bar only when the final prints are missing. */
  last_value_date: string | null;
}

export interface DrawdownProfile {
  symbol: string;
  interval: Interval;
  basis: DrawdownBasis;
  generated_at: string;
  bars: number;
  first_bar: string | null;
  last_bar: string | null;
  /** Deepest first, truncated to the requested top-N. */
  episodes: DrawdownEpisode[];
  /** Total found before truncation, so a top-10 table cannot read as the whole history. */
  episodes_considered: number;
  /** The live drawdown, if any. Often not in the top N, and it is the question the card asks. */
  current: DrawdownEpisode | null;
  warnings: MarketWarning[];
}

// --- guards -----------------------------------------------------------------

/** `"unverified"` is a failure state, not a pending one. Only `"passed"` permits rendering. */
export type GuardStatus = "passed" | "failed" | "unverified";

export interface GuardFinding {
  check: string;
  passed: boolean;
  detail: string;
}

export interface GuardReport {
  status: GuardStatus;
  expression: string;
  findings: GuardFinding[];
}

// --- event study ------------------------------------------------------------

export interface HorizonStats {
  horizon: number;
  entry: Entry;
  hit_rate: number | null;
  baseline_hit_rate: number | null;
  distribution: Distribution;
  baseline_distribution: Distribution;
  sample_size: number;
  independent_sample_size: number;
  baseline_sample_size: number;
}

export interface ConditionArm {
  label: string;
  expression: string;
  guard: GuardReport;
  stats: HorizonStats[];
  /**
   * Every bar the condition fired on, including those too close to the series end to have a
   * complete forward window — excluded from `sample_size`, but they happened, and the chart
   * overlay marks them.
   */
  trigger_dates: string[];
  triggers: number;
  evaluable_bars: number;
  warnings: MarketWarning[];
}

/**
 * What adding a condition changed. Both fields matter together: a 12-point hit-rate gain built on
 * a sample that shrank from 140 triggers to 9 is not an improvement, and rendering only
 * `hit_rate_delta` invites reading it as one.
 */
export interface ArmDelta {
  horizon: number;
  hit_rate_delta: number | null;
  median_delta: number | null;
  sample_size_delta: number;
  independent_sample_size_delta: number;
}

export interface EventStudy {
  symbol: string;
  interval: Interval;
  generated_at: string;
  entry: Entry;
  horizons: number[];
  bars: number;
  first_bar: string | null;
  last_bar: string | null;
  arms: ConditionArm[];
  /** Each non-base arm against `arms[0]`, flattened `(armIndex - 1) * horizons.length + hIndex`. */
  deltas: ArmDelta[];
  run_id: string | null;
  warnings: MarketWarning[];
}

// --- reverse conditioning ---------------------------------------------------

export interface IndicatorProfile {
  spec: string;
  column: string;
  selected: Distribution;
  baseline: Distribution;
  /**
   * Median shift in units of the unconditional IQR — robust and unitless, so RSI and a price-scale
   * band width belong in the same column. `null` when the indicator was constant over the sample.
   */
  separation: number | null;
}

/**
 * **Exploratory.** The moves were selected on their forward return, so every number here describes
 * the sample rather than testing a hypothesis about it. Carries no hit rate, p-value or q-value by
 * design. Render it as a candidate generator; a candidate becomes a result only after being tested
 * as a declared trial in a scan.
 */
export interface ReverseConditioning {
  symbol: string;
  interval: Interval;
  generated_at: string;
  horizon: number;
  /** Upper-tail cutoff, 0–1. `0.9` selects the top decile. */
  quantile: number;
  lookback: number;
  selected_dates: string[];
  selected_count: number;
  /** Top-decile moves cluster hard; the raw count overstates how many distinct episodes this is. */
  independent_selected_count: number;
  /** Sorted by `|separation|` descending, unmeasurable ones last. */
  profiles: IndicatorProfile[];
  exploratory: boolean;
  run_id: string | null;
  warnings: MarketWarning[];
}

// --- scan -------------------------------------------------------------------

export interface ScanEntry {
  label: string;
  expression: string;
  horizon: number;
  guard: GuardReport;
  /** `null` when the condition could not be evaluated — it still consumed a trial. */
  stats: HorizonStats | null;
  /** Two-sided exact binomial on the *independent* sample size. */
  p_value: number | null;
  /** Benjamini–Hochberg adjusted. The number to read. */
  q_value: number | null;
  discovery: boolean;
}

export interface ScanResult {
  symbol: string;
  interval: Interval;
  generated_at: string;
  entry: Entry;
  alpha: number;
  /** Always equals `entries.length`; the backend refuses to construct otherwise. */
  trials: number;
  entries: ScanEntry[];
  discoveries: number;
  bars: number;
  first_bar: string | null;
  last_bar: string | null;
  run_id: string | null;
  warnings: MarketWarning[];
}

// --- run card ---------------------------------------------------------------

export interface RunCard {
  run_id: string;
  kind: string;
  created_at: string;
  symbol: string;
  interval: Interval;
  params: Record<string, unknown>;
  params_hash: string;
  /**
   * Identifies the exact bars the study saw. Two run cards with the same `params_hash` and a
   * different `data_fingerprint` mean the data moved under an unchanged question.
   */
  data_fingerprint: string;
  code_version: string;
  results: Record<string, unknown>;
}

// --- requests ---------------------------------------------------------------

export interface EventStudyRequest {
  symbol: string;
  interval?: Interval;
  /** Arm 0 is the base every delta is measured against. */
  conditions: string[];
  horizons?: number[];
  entry?: Entry;
}

export interface ReverseRequest {
  symbol: string;
  interval?: Interval;
  horizon?: number;
  quantile?: number;
  lookback?: number;
  /** Indicator spec strings. Empty asks the backend for its default profile set. */
  indicators?: string[];
}

export interface ScanRequest {
  symbol: string;
  interval?: Interval;
  /** Every expression here is a trial, whether or not it survives. */
  expressions: string[];
  horizons?: number[];
  entry?: Entry;
  alpha?: number;
}

// --- fetchers ---------------------------------------------------------------

const BASE = "/api/backtest";

/** Same shape as `rules.ts`'s own `requestJson` — duplicated rather than shared for the reason the
 * backend routers duplicate their `_handle`: it is a five-line contract, and importing it would tie
 * this module's loadability to another API module it otherwise has nothing to do with. */
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

/** `null` rather than a dropped key: `exactOptionalPropertyTypes` is on, and `RequestInit.signal`
 * is `AbortSignal | null`, so an explicit `undefined` is a type error while `null` is the documented
 * "no signal" value. */
function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return requestJson<T>(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: signal ?? null,
  });
}

export const backtestApi = {
  drawdowns: (
    symbol: string,
    options: { interval?: Interval; basis?: DrawdownBasis; top?: number; signal?: AbortSignal } = {},
  ) => {
    const params = new URLSearchParams({ symbol });
    if (options.interval) params.set("interval", options.interval);
    if (options.basis) params.set("basis", options.basis);
    if (options.top !== undefined) params.set("top", String(options.top));
    return requestJson<DrawdownProfile>(`${BASE}/drawdowns?${params.toString()}`, {
      signal: options.signal ?? null,
    });
  },

  eventStudy: (request: EventStudyRequest, signal?: AbortSignal) =>
    postJson<EventStudy>("/event-study", request, signal),

  /** Exploratory. See `ReverseConditioning` — its output is a candidate, never a finding. */
  reverse: (request: ReverseRequest, signal?: AbortSignal) =>
    postJson<ReverseConditioning>("/reverse", request, signal),

  /** Every expression in the request is a trial, whether or not it survives. */
  scan: (request: ScanRequest, signal?: AbortSignal) =>
    postJson<ScanResult>("/scan", request, signal),

  runCard: (runId: string, signal?: AbortSignal) =>
    requestJson<RunCard>(`${BASE}/runs/${encodeURIComponent(runId)}`, { signal: signal ?? null }),
};

// --- display helpers --------------------------------------------------------

/** Only `"passed"` permits rendering a study's numbers. `"unverified"` is a failure, not pending. */
export function guardOk(guard: GuardReport): boolean {
  return guard.status === "passed";
}

/** Display word for a raw `GuardStatus` wire value -- the enum itself stays an identifier. */
export function guardStatusLabel(status: GuardStatus): string {
  switch (status) {
    case "passed":
      return t("strategy.guardStatus.passed");
    case "failed":
      return t("strategy.guardStatus.failed");
    case "unverified":
      return t("strategy.guardStatus.unverified");
  }
}

/** Hit rate minus baseline. `null` when either side is unmeasurable — render an em dash. */
export function edgeOfStats(stats: HorizonStats): number | null {
  if (stats.hit_rate === null || stats.baseline_hit_rate === null) return null;
  return stats.hit_rate - stats.baseline_hit_rate;
}

export function isSmallSample(stats: HorizonStats): boolean {
  return stats.independent_sample_size < SMALL_SAMPLE_THRESHOLD;
}

/**
 * Format a q-value. Below 0.001 it renders as `<0.001` rather than `0.000`, which would read as
 * certainty about a quantity that is an expected rate over a set.
 */
export function formatQ(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  if (value < 0.001) return "<0.001";
  return value.toFixed(3);
}

/** Depth as a positive percentage for display, keeping the sign convention out of the template. */
export function formatDepth(depth: number): string {
  return `${(Math.abs(depth) * 100).toFixed(1)}%`;
}

/** Bars underwater, marked as a floor when the episode has not recovered. */
export function formatUnderwater(episode: DrawdownEpisode): string {
  return episode.still_underwater
    ? t("strategy.backtest.underwaterBarsOngoing", { count: episode.bars_underwater })
    : t("strategy.backtest.underwaterBars", { count: episode.bars_underwater });
}

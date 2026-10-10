/**
 * Typed client for the rule DSL and the decision table.
 *
 * Mirrors `backend/app/rules/models.py` and `backend/app/api/rules.py` field for field.
 *
 * The table is a research instrument, not a signal service, and three things about the wire format
 * exist to keep the UI from overstating it.
 *
 * **A hit rate must never be shown without its baseline.** `hit_rate: 0.58` is not an edge if the
 * instrument rose on 56% of all bars; the edge is 2 points, not 58. Every `Evidence` carries
 * `baseline_hit_rate` over the same sample, and `edgeOf` computes the difference. Rendering the
 * hit rate alone is the single easiest way to make noise look like a strategy.
 *
 * **`null` means unmeasurable, not zero.** A rule with too few triggers has no history to report.
 * Rendering `null` as `0.0%` claims the rule reliably precedes a flat move, which is a much
 * stronger statement than "we don't know".
 *
 * **`state` is three-valued.** Through an indicator's warmup window a rule has no truth value at
 * all. `"unknown"` must not be styled like `"false"` — one means the rule is quiet, the other means
 * it has not started yet.
 */

import { ApiRequestError } from "@/api/client";
import type { Interval, MarketWarning } from "@/api/market";
import { t } from "@/i18n";

export type { Interval, MarketWarning };

/** Forward-return horizons in bars, matching `HORIZONS` in the backend contract. */
export const HORIZONS = [1, 5, 20, 60] as const;
export type Horizon = (typeof HORIZONS)[number];

/** A rule's truth value on one bar. `unknown` is warmup or a gap — not a quiet day. */
export type TriState = "true" | "false" | "unknown";

/**
 * Where the forward-return clock starts.
 *
 * `next_open` is the only honestly tradeable choice: the condition is known once bar `t` closes, so
 * the first obtainable price is the next session's open. `same_close` assumes a fill at the very
 * price that produced the signal and is an upper bound, never an estimate — label it as such
 * wherever it appears.
 */
export type Entry = "next_open" | "same_close";

/**
 * Deliberately coarse. These rules are picked by a human looking at the same history they are then
 * scored against, and a table of twenty rules is twenty simultaneous tests with no correction.
 * `suggestive` means "worth opening the backtest workbench", never "significant".
 */
export type Significance = "insufficient" | "weak" | "suggestive";

export interface Rule {
  rule_id: string;
  name: string;
  /** The DSL source as the user wrote it. Round-trips through the parser. */
  expression: string;
  description: string;
  /** Intervals the rule is defined on. Empty means any. */
  intervals: Interval[];
}

export interface RuleState {
  state: TriState;
  as_of: string | null;
  /** `null` means it never fired in the stored history — distinct from "fired long ago". */
  last_trigger: string | null;
  bars_since_trigger: number | null;
  triggers_in_history: number;
}

export interface Evidence {
  horizon: number;
  entry: Entry;
  /** 0–1, not a percentage. `null` when unmeasurable. */
  hit_rate: number | null;
  /** The same measurement over every evaluable bar. Show it next to `hit_rate`, always. */
  baseline_hit_rate: number | null;
  /** Fraction, not percent. Median, so one outlier move cannot carry the statistic. */
  median_return: number | null;
  baseline_median_return: number | null;
  /** Triggers with a complete forward window. */
  sample_size: number;
  /** Triggers left after dropping overlapping forward windows. Significance rests on this one. */
  independent_sample_size: number;
  significance: Significance;
}

export interface DecisionRow {
  rule: Rule;
  state: RuleState;
  /** One per horizon, in `HORIZONS` order. */
  evidence: Evidence[];
  /** Why this row is degraded. A row that could not be evaluated still appears, with its reason. */
  warnings: MarketWarning[];
}

export interface DecisionTable {
  symbol: string;
  interval: Interval;
  generated_at: string;
  bars_evaluated: number;
  first_bar: string | null;
  /** Every number in the table is conditional on this span. Show it. */
  last_bar: string | null;
  rows: DecisionRow[];
  /**
   * The thresholds the `significance` grades are assigned by, so a reader can check a row against
   * the rule instead of trusting the word.
   *
   * Sent with the table rather than restated in this file: the Scan page names its method
   * (Benjamini–Hochberg) while the decision table graded every rule "insufficient" with no test or
   * threshold beside it, and a legend hard-coded here would drift from the constants in
   * `app.rules.evidence` the first time one moved. `null` from an older backend.
   */
  criteria: SignificanceCriteria | null;
  warnings: MarketWarning[];
}

export interface SignificanceCriteria {
  weak_min_independent: number;
  /**
   * Absolute hit-rate edge as a fraction: `0.15` is fifteen **percentage points** more often than
   * the baseline, not a 15% return. Both the sample and the edge condition must hold together.
   */
  weak_min_edge: number;
  suggestive_min_independent: number;
  suggestive_min_edge: number;
}

/** Result of checking a rule expression without running it against data. */
export interface RuleValidation {
  valid: boolean;
  /** Human-readable parse error, with the offending position where the parser could identify one. */
  error: string | null;
  /** The tree rendered back to text. Lets the UI show how the expression was actually understood. */
  normalized: string | null;
  /** Indicator specs the expression needs, e.g. `["rsi:14", "bb:20,2"]`. */
  indicators: string[];
}

// --- requests ---------------------------------------------------------------

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

export const rulesApi = {
  /** The catalog of named rules, independent of any symbol. */
  catalog: () => requestJson<Rule[]>("/api/rules/catalog"),

  decisions: (symbol: string, interval: Interval, signal?: AbortSignal) =>
    requestJson<DecisionTable>(
      `/api/rules/decisions?symbol=${encodeURIComponent(symbol)}&interval=${interval}`,
      { signal: signal ?? null },
    ),

  /** Check an expression without evaluating it. Used by the editor, so it must be cheap. */
  validate: (expression: string) =>
    requestJson<RuleValidation>("/api/rules/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expression }),
    }),
};

// --- display helpers --------------------------------------------------------

/**
 * Hit rate minus baseline — the number that actually means something.
 * `null` when either side is unmeasurable, which must render as an em dash, not as zero edge.
 */
export function edgeOf(evidence: Evidence): number | null {
  if (evidence.hit_rate === null || evidence.baseline_hit_rate === null) return null;
  return evidence.hit_rate - evidence.baseline_hit_rate;
}

/** Format a 0–1 fraction as a percentage. `null` becomes an em dash, never `0.0%`. */
export function formatRate(value: number | null, digits = 1): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

/** Signed percentage, for returns and edges. */
export function formatSignedRate(value: number | null, digits = 1): string {
  if (value === null || !Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(digits)}%`;
}

export function stateLabel(state: TriState): string {
  switch (state) {
    case "true":
      return t("strategy.ruleState.firing");
    case "false":
      return t("strategy.ruleState.quiet");
    case "unknown":
      return t("strategy.ruleState.noData");
  }
}

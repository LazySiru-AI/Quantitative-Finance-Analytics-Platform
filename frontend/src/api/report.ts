/**
 * Typed client for per-holding reports and the strategy backtest.
 *
 * Mirrors `backend/app/report/models.py`, the strategy section of `backend/app/backtest/models.py`,
 * and `backend/app/api/report.py` field for field. The rendering rules in `api/rules.ts` and
 * `api/backtest.ts` hold verbatim and are not restated.
 *
 * Four things are specific to this surface.
 *
 * **Prose is already rendered and already verified.** A `RenderedNarrative` only exists because a
 * `GroundingReport` passed — the backend has no path from an unverified draft to rendered text. The
 * UI's job is not to re-check it but to *show that it was checked*: surface `grounding.cited` so a
 * reader can see which computed figures the sentence leaned on, and surface `grounding.caveat`,
 * which states the limit of the guarantee. A section whose draft failed verification arrives with
 * `narrative: null` and a warning; render the warning, never a fallback sentence of your own.
 *
 * **A strategy return without buy-and-hold is not a result.** `StrategyResult.buy_hold` is required
 * on the wire for the same reason `HorizonStats.baseline_hit_rate` is. Show them adjacently, and
 * give the difference the emphasis. A 14% CAGR next to a 19% buy-and-hold is a loss.
 *
 * **Exposure changes what a return means.** A strategy in the market 5% of the time carrying a
 * return near buy-and-hold's is doing something remarkable; the same return at 100% exposure is
 * doing nothing. Never render `total_return` without `exposure` in view.
 *
 * **`cost_drag` is what the frictions took.** A strategy whose edge is smaller than this number has
 * no edge, and the UI should make that comparison easy rather than leaving it to arithmetic.
 */

import { ApiRequestError } from "@/api/client";
import type { DrawdownProfile, GuardReport, Interval, MarketWarning } from "@/api/backtest";
import type { Quote } from "@/api/market";
import type { DecisionTable } from "@/api/rules";

export type { DrawdownProfile, GuardReport, Interval, MarketWarning };

// --- facts ------------------------------------------------------------------

/**
 * How a fact renders. Decided by the backend, never by the component — the same number means
 * different things in different units, and a fraction shown where a percentage was meant reads as
 * merely odd rather than as wrong.
 */
export type FactKind =
  | "percent"
  | "signed_percent"
  | "ratio"
  | "currency"
  | "count"
  | "date"
  | "text";

export interface Fact {
  id: string;
  label: string;
  /** `null` is a legitimate value: a statistic that could not be measured. Render an em dash. */
  value: number | string | null;
  kind: FactKind;
  unit: string;
  /** Which engine and window produced it — specific enough to re-derive. Show it in footnotes. */
  source: string;
  as_of: string | null;
}

export interface FactBundle {
  symbol: string;
  interval: Interval;
  generated_at: string;
  facts: Record<string, Fact>;
  warnings: MarketWarning[];
}

// --- grounding --------------------------------------------------------------

export type ViolationKind =
  | "unknown_fact"
  | "bare_numeral"
  | "malformed_reference"
  | "empty";

export interface GroundingViolation {
  kind: ViolationKind;
  detail: string;
  position: number | null;
  excerpt: string;
}

/**
 * `grounded: true` says every numeral in the prose resolves to a computed fact. It does **not** say
 * the prose is true — `caveat` states that limit, and the UI must show it rather than presenting a
 * green check that implies more.
 */
export interface GroundingReport {
  grounded: boolean;
  violations: GroundingViolation[];
  /** Fact ids the prose actually cited, in order of appearance. */
  cited: string[];
  caveat: string;
}

export interface NarrativeDraft {
  text: string;
  source: string;
  model: string | null;
  temperature: number | null;
}

export interface RenderedNarrative {
  /** Fully rendered and already verified. Safe to display. */
  text: string;
  draft: NarrativeDraft;
  grounding: GroundingReport;
  cited_facts: Fact[];
}

// --- strategy ---------------------------------------------------------------

export type ExitReason = "signal" | "horizon" | "stop" | "end_of_data";

export interface Costs {
  /** Basis points each way. The backend default is deliberately non-zero. */
  slippage_bps: number;
  commission_per_trade: number;
  /**
   * Only used to express a flat commission as a fraction of a unitless equity curve. Not a
   * position size — see the backend field's docstring.
   */
  notional: number;
}

export interface StrategySpec {
  entry: string;
  exit: string | null;
  max_holding_bars: number | null;
  /** Fractional adverse move, e.g. `0.10` for 10%. Filled at the stop, not the bar's close. */
  stop_loss_pct: number | null;
}

export interface Trade {
  entry_date: string;
  entry_price: number;
  exit_date: string;
  exit_price: number;
  exit_reason: ExitReason;
  bars_held: number;
  return_pct: number;
  /** An unrealised mark, not a result. Excluded from the win rate. */
  open_at_end: boolean;
}

export interface EquityPoint {
  date: string;
  equity: number;
  buy_hold: number;
  in_position: boolean;
}

export interface StrategyMetrics {
  total_return: number | null;
  /** `null` under a year of data — annualising a short window is an extrapolation. */
  cagr: number | null;
  volatility: number | null;
  sharpe: number | null;
  /** `null` when no bar lost money: an empty denominator, not a strong result. */
  sortino: number | null;
  max_drawdown: number | null;
  /** Fraction of bars holding a position. Never show a return without this. */
  exposure: number | null;
  trades: number;
  trades_per_year: number | null;
  /** Closed trades only. */
  win_rate: number | null;
  /** Sharpe is meaningless without it, so it travels with the result. */
  risk_free_rate: number;
  bars_per_year: number;
}

export interface StrategyResult {
  symbol: string;
  interval: Interval;
  generated_at: string;
  spec: StrategySpec;
  costs: Costs;
  guard: GuardReport;
  metrics: StrategyMetrics;
  /** Required. A strategy return without the return of doing nothing is not a result. */
  buy_hold: StrategyMetrics;
  /** Always ≤ 0. A strategy whose edge is smaller than this has no edge. */
  cost_drag: number | null;
  equity_curve: EquityPoint[];
  trades: Trade[];
  open_trades: number;
  bars: number;
  first_bar: string | null;
  last_bar: string | null;
  run_id: string | null;
  warnings: MarketWarning[];
}

// --- report -----------------------------------------------------------------

export interface Profile {
  symbol: string;
  name: string | null;
  exchange: string | null;
  exchange_timezone: string;
  currency: string;
  instrument_type: string | null;
  first_trade_date: string | null;
  source: string;
}

/**
 * Re-exported from `api/market.ts` rather than declared again here.
 *
 * This was a hand-rolled subset — four fields, `price` typed `number | null`, and an index
 * signature swallowing the rest — while the backend model it mirrors has thirteen fields and a
 * **required** `price`. Nothing rendered wrongly because of it: the one call site guards with
 * `quote?.price ?? null` and `formatPrice` handles null. But the two declarations disagreed about
 * what the server guarantees, and the looser one was the one the report page believed. A divergence
 * that costs nothing today is still a second source of truth, and the index signature meant no
 * amount of backend drift could ever make it fail to compile.
 */
export type { Quote };

export interface ReportSection {
  section_id: string;
  title: string;
  /** `null` when the section is tables only, or when its draft failed verification. */
  narrative: RenderedNarrative | null;
  fact_ids: string[];
  warnings: MarketWarning[];
}

export interface Report {
  symbol: string;
  interval: Interval;
  generated_at: string;
  profile: Profile | null;
  quote: Quote | null;
  bundle: FactBundle;
  sections: ReportSection[];
  drawdown: DrawdownProfile | null;
  decisions: DecisionTable | null;
  strategy: StrategyResult | null;
  run_id: string | null;
  warnings: MarketWarning[];
  disclaimer: string;
}

// --- requests ---------------------------------------------------------------

export interface StrategyRequest {
  symbol: string;
  interval?: Interval;
  entry: string;
  exit?: string;
  max_holding_bars?: number;
  stop_loss_pct?: number;
  slippage_bps?: number;
  commission_per_trade?: number;
  notional?: number;
  risk_free_rate?: number;
}

// --- fetchers ---------------------------------------------------------------

const BASE = "/api/report";

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

export const reportApi = {
  get: (symbol: string, interval: Interval = "1d", signal?: AbortSignal) =>
    requestJson<Report>(
      `${BASE}?symbol=${encodeURIComponent(symbol)}&interval=${interval}`,
      { signal: signal ?? null },
    ),

  facts: (symbol: string, interval: Interval = "1d", signal?: AbortSignal) =>
    requestJson<FactBundle>(
      `${BASE}/facts?symbol=${encodeURIComponent(symbol)}&interval=${interval}`,
      { signal: signal ?? null },
    ),

  strategy: (request: StrategyRequest, signal?: AbortSignal) =>
    requestJson<StrategyResult>(`${BASE}/strategy`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: signal ?? null,
    }),

  /** Markdown export of the whole report. Returns text, not JSON. */
  exportUrl: (symbol: string, interval: Interval = "1d") =>
    `${BASE}/export?symbol=${encodeURIComponent(symbol)}&interval=${interval}`,
};

// --- display helpers --------------------------------------------------------

/** Render a fact by its declared kind. `null` is always an em dash, never a zero. */
export function formatFact(fact: Fact): string {
  if (fact.value === null) return "—";
  if (typeof fact.value === "string") return fact.value;
  switch (fact.kind) {
    case "percent":
      return `${(fact.value * 100).toFixed(1)}%`;
    case "signed_percent": {
      const sign = fact.value > 0 ? "+" : "";
      return `${sign}${(fact.value * 100).toFixed(1)}%`;
    }
    case "ratio":
      return fact.value.toFixed(2);
    case "currency":
      return fact.value.toLocaleString(undefined, { style: "currency", currency: "USD" });
    case "count":
      return fact.value.toLocaleString();
    default:
      return String(fact.value);
  }
}

/**
 * The number that matters: strategy return minus buy-and-hold over the same window.
 * `null` when either side is unmeasurable — render an em dash, not a zero edge.
 */
export function excessReturn(result: StrategyResult): number | null {
  const a = result.metrics.total_return;
  const b = result.buy_hold.total_return;
  if (a === null || b === null) return null;
  return a - b;
}

/** Same comparison on an annualised basis. */
export function excessCagr(result: StrategyResult): number | null {
  const a = result.metrics.cagr;
  const b = result.buy_hold.cagr;
  if (a === null || b === null) return null;
  return a - b;
}

/**
 * How a strategy's excess over buy-and-hold should be read.
 *
 * Three outcomes, not two, because "the edge is inside its costs" and "the strategy lost badly" are
 * different findings and the first phrasing is actively misleading applied to the second — a run
 * that trails buy-and-hold by 130 percentage points is not a marginal call that frictions explain.
 */
export type EdgeVerdict = "underperforms" | "inside_costs" | "exceeds_costs" | "unmeasurable";

export function edgeVerdict(result: StrategyResult): EdgeVerdict {
  const excess = excessReturn(result);
  if (excess === null || result.cost_drag === null) return "unmeasurable";
  if (excess <= 0) return "underperforms";
  return excess <= Math.abs(result.cost_drag) ? "inside_costs" : "exceeds_costs";
}

/**
 * True only when the strategy *beat* buy-and-hold by less than its own frictions cost — a result
 * that is inside its own error bars on costs alone. A losing strategy returns `false` here and is
 * described by `edgeVerdict` instead.
 */
export function edgeInsideCosts(result: StrategyResult): boolean {
  return edgeVerdict(result) === "inside_costs";
}

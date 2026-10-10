/**
 * Typed client for the market-data endpoints.
 *
 * Mirrors `backend/app/market/models.py` and `backend/app/api/market.py` field for field.
 *
 * **Prices here are JSON `number`, not `DecimalString` — and that is deliberate.** Everything in
 * `api/tax.ts` crosses the wire as a decimal string because a cent of drift there is a wrong tax
 * return. Market data is the opposite case: it is observational, the upstream hands it over as an
 * IEEE double already, and every consumer (charts, indicators, statistics) is float maths. Carrying
 * it as a string would buy no accuracy and force a parse at every point of use.
 *
 * The rule that follows from the split: **never add a market number to a ledger number.** A position
 * value shown against a cost basis is a display juxtaposition, not an arithmetic one. Anything that
 * must be exact is computed server-side in `Decimal` and arrives through the tax client.
 *
 * Indicator values are `number | null`. `null` is the warmup window — an EMA(200) has no value
 * until 200 bars exist. Render a gap. A `null` coerced to 0 draws a band collapsing to the axis,
 * which reads as a crash rather than as missing data.
 */

import { ApiRequestError } from "@/api/client";

export type Interval = "5m" | "15m" | "30m" | "1h" | "4h" | "1d" | "1w";

export const INTERVALS: readonly Interval[] = ["5m", "15m", "30m", "1h", "4h", "1d", "1w"] as const;

/**
 * `INTERVALS` with display labels, for the interval pickers on Report, Thesis and Backtest.
 *
 * One list, not three: each of those pages previously carried its own `[Daily, Weekly]` literal, so
 * adding `15m`/`30m`/`4h` to the backend left all three silently offering the old pair. Same reason
 * `nav.ts` refuses to let a second copy of the sidebar list exist.
 *
 * Ordered finest to coarsest, matching `INTERVALS` and the backend `Interval` enum. Pages default
 * their own state to `"1d"` explicitly rather than reading position 0, so this order is a display
 * choice and nothing depends on it.
 *
 * Note for anyone reading an intraday backtest here: `cagr`, `volatility`, `sharpe` and `sortino`
 * come back `null` on every sub-daily interval, by design -- see `app.backtest.metrics.compute`'s
 * `annualisable` parameter. `total_return` and `max_drawdown` are populated at every interval.
 */
export const INTERVAL_OPTIONS: readonly { value: Interval; label: string }[] = [
  { value: "5m", label: "5 min" },
  { value: "15m", label: "15 min" },
  { value: "30m", label: "30 min" },
  { value: "1h", label: "1 hour" },
  { value: "4h", label: "4 hour" },
  { value: "1d", label: "Daily" },
  { value: "1w", label: "Weekly" },
] as const;

/** Where a series came from. A fallback is worth showing rather than hiding. */
export type BarSource = "yahoo" | "stooq" | "store" | "derived";

export interface MarketWarning {
  /** Stable token: `clamped`, `short_history`, `provider_fallback`, `partial_bar`, `stale`, `gap`. */
  kind: string;
  message: string;
}

export interface Bar {
  /** ISO 8601, UTC. Daily and weekly bars are the exchange-local session date at 00:00 UTC. */
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  /** Split- and dividend-adjusted. Daily only; `null` on intraday. */
  adj_close: number | null;
  volume: number | null;
  /**
   * The session behind this bar has not closed. Never true for a stored bar — the store holds
   * settled bars only, so a backtest cannot see one. Only the live tail carries it.
   */
  partial: boolean;
}

export interface BarSeries {
  symbol: string;
  interval: Interval;
  source: BarSource;
  bars: Bar[];
  warnings: MarketWarning[];
}

export interface Quote {
  symbol: string;
  price: number;
  ts: string;
  currency: string;
  previous_close: number | null;
  change: number | null;
  change_pct: number | null;
  day_high: number | null;
  day_low: number | null;
  fifty_two_week_high: number | null;
  fifty_two_week_low: number | null;
  volume: number | null;
  /** Provider's own label: `REGULAR`, `CLOSED`, `PRE`, `POST`. Shown verbatim. */
  market_state: string | null;
  source: BarSource;
}

export interface Profile {
  symbol: string;
  name: string | null;
  exchange: string | null;
  exchange_timezone: string;
  currency: string;
  /** Provider classification: `EQUITY`, `ETF`, `INDEX`, `CRYPTOCURRENCY`. */
  instrument_type: string | null;
  first_trade_date: string | null;
  source: BarSource;
}

export interface Coverage {
  symbol: string;
  interval: Interval;
  rows: number;
  first_ts: string | null;
  last_ts: string | null;
  fetched_at: string | null;
}

// --- indicators -------------------------------------------------------------

/** Where the indicator is drawn. Comes from the server so the chart cannot disagree with the maths. */
export type Pane = "price" | "oscillator";

/**
 * `choice_or_date` is one of the fixed `choices` *or* an arbitrary ISO date. It exists for the
 * anchored VWAP anchor, which is either `session` or a date to accumulate from — a control that
 * must offer both, since the date-anchored form is the reason an *anchored* VWAP is worth having.
 */
export type ParamKind = "int" | "float" | "date" | "choice" | "choice_or_date";

export interface ParamSpec {
  name: string;
  kind: ParamKind;
  default: number | string;
  minimum: number | null;
  maximum: number | null;
  choices: string[];
  label: string;
}

/**
 * One entry of the server's indicator registry. The overlay menu is built from this rather than
 * from a hardcoded list, so an indicator added in Phase 6 or 7 appears in the UI without a
 * frontend change — and, more to the point, cannot appear with parameters the backend rejects.
 */
export interface IndicatorCatalogEntry {
  name: string;
  title: string;
  pane: Pane;
  params: ParamSpec[];
  /** Column suffixes for a multi-line indicator: Bollinger is `["upper","mid","lower"]`. */
  outputs: string[];
  /** `null` means every interval. Anchored VWAP lists `["5m","1h"]` only. */
  intervals: Interval[] | null;
  description: string;
  /** The default spec string, ready to send back: `"bb:20,2"`. */
  default_spec: string;
}

export interface IndicatorSeries {
  /** Round-trips to the spec string that produced it: `sma_50`, `bb_20_2`. */
  key: string;
  name: string;
  title: string;
  pane: Pane;
  /** Column name -> aligned values. Keys are `bb_20_2_upper` etc.; one key when single-output. */
  columns: Record<string, (number | null)[]>;
  /** Leading values that are `null` by definition. Studies drop this region; charts just gap it. */
  warmup: number;
}

export interface IndicatorResponse {
  symbol: string;
  interval: Interval;
  /** Aligned index for every series below. Same length as each column array. */
  ts: string[];
  series: IndicatorSeries[];
  warnings: MarketWarning[];
}

// --- ticker summary ---------------------------------------------------------

export interface FundamentalFact {
  concept: string;
  label: string;
  value: number;
  unit: string;
  period_end: string;
  fiscal_period: string;
  form: string;
  /** SEC accession number — the filing this figure was read from. */
  accession: string;
}

export interface Fundamentals {
  symbol: string;
  cik: string | null;
  entity_name: string | null;
  facts: FundamentalFact[];
  /**
   * Why there are no facts, when there are none. ETFs file nothing on this endpoint, so an empty
   * result is the common case for this portfolio and must read as an explained absence.
   */
  unavailable_reason: string | null;
}

export interface TickerSummary {
  symbol: string;
  profile: Profile | null;
  quote: Quote | null;
  coverage: Coverage[];
  fundamentals: Fundamentals | null;
  warnings: MarketWarning[];
}

export interface SyncResult {
  symbol: string;
  interval: Interval;
  source: BarSource;
  rows_written: number;
  coverage: Coverage;
  warnings: MarketWarning[];
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

function query(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value));
  }
  return search.toString();
}

export interface BarsOptions {
  start?: string;
  end?: string;
  limit?: number;
  /** Force a provider fetch before reading. Off by default: the store is the normal source. */
  refresh?: boolean;
  /**
   * Aborts the request when it fires — see `useChartSeries`'s effect cleanup, which aborts the
   * in-flight bars/indicators request for a symbol or interval that has already been navigated away
   * from, rather than letting it complete and discarding the result. Never sent as a query param:
   * destructured out of `options` below before the rest is spread into `query()`, the same split
   * `backtestApi.drawdowns` (`api/backtest.ts`) uses for the same reason.
   */
  signal?: AbortSignal;
}

export const marketApi = {
  bars: (symbol: string, interval: Interval, options: BarsOptions = {}) => {
    const { signal, ...params } = options;
    return requestJson<BarSeries>(`/api/market/bars?${query({ symbol, interval, ...params })}`, {
      signal: signal ?? null,
    });
  },

  quote: (symbol: string) => requestJson<Quote>(`/api/market/quote?${query({ symbol })}`),

  profile: (symbol: string) => requestJson<Profile>(`/api/market/profile?${query({ symbol })}`),

  ticker: (symbol: string) =>
    requestJson<TickerSummary>(`/api/market/ticker/${encodeURIComponent(symbol)}`),

  catalog: () => requestJson<IndicatorCatalogEntry[]>("/api/market/indicators/catalog"),

  /** `specs` are spec strings: `["sma:50", "bb:20,2"]`. Sent as repeated `spec` parameters. */
  indicators: (symbol: string, interval: Interval, specs: string[], options: BarsOptions = {}) => {
    const { signal, ...params } = options;
    const search = new URLSearchParams(query({ symbol, interval, ...params }));
    for (const spec of specs) search.append("spec", spec);
    return requestJson<IndicatorResponse>(`/api/market/indicators?${search.toString()}`, {
      signal: signal ?? null,
    });
  },

  sync: (symbol: string, interval: Interval) =>
    requestJson<SyncResult>(`/api/market/sync?${query({ symbol, interval })}`, { method: "POST" }),
};

// --- display helpers --------------------------------------------------------

/** Plain number formatting for prices. Market data, so ordinary float formatting is correct here. */
export function formatPrice(value: number | null | undefined, currency = "USD"): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: value < 1 ? 4 : 2,
  }).format(value);
}

export function formatPercent(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

export function formatVolume(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
  return value.toFixed(0);
}

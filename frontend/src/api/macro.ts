/**
 * Typed client for the macro dashboard.
 *
 * Mirrors `backend/app/market/macro_models.py` and `backend/app/api/macro.py` field for field.
 *
 * Values are JSON `number` for the same reason as `api/market.ts`: these are observations, not
 * money, and nothing on this page is summed into a ledger figure.
 *
 * Three things here are easy to get wrong and are worth reading before using the types.
 *
 * **A macro observation is a `date`, not a timestamp.** `MacroPoint.date` is `YYYY-MM-DD`. Do not
 * pass it to `new Date(...)` and then format it in the local zone: `new Date("2026-08-07")` parses
 * as midnight *UTC*, so west of Greenwich it renders as the 6th. Format the string directly, or
 * append a time and construct with explicit UTC accessors.
 *
 * **Changes are not all percentages.** `SeriesChange.mode` says how to read the numbers, and it
 * varies by tile: a yield or a spread moves in basis points, a price moves in percent. Formatting a
 * basis-point move with a `%` suffix understates a big day in the bond market by two orders of
 * magnitude. Use `formatChange`.
 *
 * **`null` means unknown, not zero.** A missing horizon, a gap row in a series, an unavailable
 * value — all arrive as `null` and must render as an em dash or a break in the line. A `null`
 * coerced to `0` turns a market holiday into a rate collapse.
 */

import { ApiRequestError } from "@/api/client";
import type { MarketWarning } from "@/api/market";
import { getLanguage, localeTag } from "@/i18n";

export type { MarketWarning };

// --- provenance -------------------------------------------------------------

/**
 * Where a number came from. `yahoo` is a *proxy* standing in for an official series (`^TNX` for
 * `DGS10`), which is directionally right but not the same series — worth surfacing, not hiding.
 */
export type MacroSource = "fred" | "yahoo" | "cnn" | "computed" | "store";

// --- units and change semantics ---------------------------------------------

export type MacroUnit = "percent" | "percent_spread" | "usd" | "index";

export type ChangeMode = "percent" | "basis_points" | "absolute";

/**
 * Movement over the standard horizons. Every field is optional because a horizon is genuinely
 * unavailable when the series does not reach back that far — distinct from "unchanged".
 */
export interface SeriesChange {
  mode: ChangeMode;
  day: number | null;
  week: number | null;
  month: number | null;
  /** Measured from the last observation of the previous calendar year, not from January 1st. */
  ytd: number | null;
}

// --- series -----------------------------------------------------------------

/** One observation. `value` is `null` for a published gap (holiday, or no data yet). */
export interface MacroPoint {
  /** `YYYY-MM-DD`. See the module note — do not round-trip through a local-zone `Date`. */
  date: string;
  value: number | null;
}

export interface MacroSeries {
  series_id: string;
  title: string;
  unit: MacroUnit;
  source: MacroSource;
  points: MacroPoint[];
  warnings: MarketWarning[];
  fetched_at: string | null;
}

// --- tiles ------------------------------------------------------------------

export interface MacroTile {
  /** Stable token for layout and tests: `us10y`, `2s10s`, `wti`, `brent`. */
  key: string;
  label: string;
  value: number | null;
  unit: MacroUnit;
  as_of: string | null;
  change: SeriesChange;
  /** Oldest first. `null` values are breaks in the line, never bridged. */
  spark: MacroPoint[];
  source: MacroSource;
  warnings: MarketWarning[];
}

export interface MoverTile {
  symbol: string;
  label: string;
  price: number | null;
  /**
   * The currency `price` is quoted in. Meaningful *only* when `unit` is `"usd"` -- for an index
   * level (`DX-Y.NYB`, `^VIX`) or a percentage the backend still has to put something here, but it
   * does not mean the number is money. `currency` alone was never sufficient to decide whether to
   * print a `$`: it answers "in what currency, if any," not "is this a currency amount at all."
   * That second question is `unit`'s job.
   */
  currency: string;
  /** What kind of number `price` is: `"usd"` for an actual price (SPY, GLD, BTC-USD), `"index"` for
   * an index level with no currency (DX-Y.NYB, ^VIX), `"percent"` / `"percent_spread"` for a rate.
   * Formatting must switch on this, not on `currency` -- see `formatValue` in this module and
   * `formatMoverValue` in `pages/Macro.tsx`. */
  unit: MacroUnit;
  change: SeriesChange;
  spark: MacroPoint[];
  as_of: string | null;
  source: MacroSource;
  warnings: MarketWarning[];
}

// --- fear & greed -----------------------------------------------------------

export type Rating = "extreme fear" | "fear" | "neutral" | "greed" | "extreme greed";

/**
 * Which engine produced the index.
 *
 * `composite` is **our approximation, not CNN's number.** CNN publishes each component's raw
 * underlying value but not the normalisation that maps it onto 0–100, so the composite re-derives
 * its own scoring. It tracks direction and rough level; it will not match. The UI must label it.
 */
export type FearGreedSource = "cnn" | "composite";

export interface FearGreedComponent {
  key: string;
  label: string;
  /** The component's own unit — an index level, a ratio, a spread. Not comparable across components. */
  raw_value: number | null;
  /**
   * Short unit for `raw_value`: `index`, `ratio`, `pp`. `null` when the backend has no unit on
   * record for this component, which must render as *no suffix* rather than a guessed one — the
   * whole point is that these seven numbers are in seven different units, and a wrong label is
   * worse than an absent one.
   */
  raw_unit: string | null;
  /** What `raw_value` measures, in a phrase. For a tooltip, not a column. */
  raw_description: string | null;
  /** 0–100 contribution. `null` from CNN, which never publishes it; populated by the composite. */
  score: number | null;
  rating: Rating | null;
  as_of: string | null;
}

/**
 * `raw_value` with its unit, or an em dash.
 *
 * Two decimal places on every component regardless of magnitude, matching what was there before:
 * an S&P level reads `6,842.13` and a put/call ratio `0.77`, and both are the number CNN published.
 */
export function formatComponentRaw(component: FearGreedComponent): string {
  if (component.raw_value === null) return "—";
  const value = component.raw_value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return component.raw_unit ? `${value} ${component.raw_unit}` : value;
}

export interface FearGreed {
  score: number;
  rating: Rating;
  source: FearGreedSource;
  as_of: string;
  components: FearGreedComponent[];
  previous_close: number | null;
  previous_week: number | null;
  previous_month: number | null;
  previous_year: number | null;
  history: MacroPoint[];
  warnings: MarketWarning[];
}

// --- the page ---------------------------------------------------------------

export interface MacroSnapshot {
  generated_at: string;
  rates: MacroTile[];
  oil: MacroTile[];
  fear_greed: FearGreed | null;
  movers: MoverTile[];
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

export const macroApi = {
  /** The whole page in one request, so no two panels disagree about what "now" means. */
  snapshot: (refresh = false, signal?: AbortSignal) =>
    requestJson<MacroSnapshot>(`/api/macro/snapshot${refresh ? "?refresh=true" : ""}`, {
      signal: signal ?? null,
    }),

  /** Full history for one series, for the expanded view. */
  series: (seriesId: string) =>
    requestJson<MacroSeries>(`/api/macro/series/${encodeURIComponent(seriesId)}`),

  fearGreed: () => requestJson<FearGreed>("/api/macro/fear-greed"),
};

// --- display helpers --------------------------------------------------------

/** CNN's bands, shared with the backend so a source switch cannot move a rating boundary. */
export function ratingFor(score: number): Rating {
  if (score < 25) return "extreme fear";
  if (score < 45) return "fear";
  if (score < 55) return "neutral";
  if (score < 75) return "greed";
  return "extreme greed";
}

/**
 * Format a change according to its own mode. The `mode` is why this exists: `+0.10` on a yield is
 * `+10 bp`, and rendering it as `+0.10%` is wrong by a factor of 100.
 */
export function formatChange(value: number | null, mode: ChangeMode): string {
  if (value === null || !Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : "";
  switch (mode) {
    case "basis_points":
      return `${sign}${Math.round(value)} bp`;
    case "percent":
      return `${sign}${value.toFixed(2)}%`;
    case "absolute":
      return `${sign}${value.toFixed(2)}`;
  }
}

/**
 * Format a level for display, using its unit.
 *
 * The `usd` and `index` cases group thousands. A bare `toFixed(2)` was adequate while every
 * dollar-denominated macro series was a two-figure oil price, but Bitcoin joined the movers and
 * renders around ninety-five thousand: `$95000.00` is a number a reader has to stop and count the
 * digits of, and at a glance it is indistinguishable from `$9500.00`. Grouping is the whole reason
 * the separator exists, and every other money surface in this app already groups.
 *
 * Percentages deliberately do *not* group: a yield or a spread has no magnitude where a separator
 * could ever apply, and adding one would only invite the reader to wonder what it means.
 */
export function formatValue(value: number | null, unit: MacroUnit): string {
  if (value === null || !Number.isFinite(value)) return "—";
  const grouped = (v: number) =>
    v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  switch (unit) {
    case "percent":
    case "percent_spread":
      return `${value.toFixed(2)}%`;
    case "usd":
      return `$${grouped(value)}`;
    case "index":
      return grouped(value);
  }
}

/**
 * Render a `YYYY-MM-DD` observation date without going through a local-zone `Date`.
 * `new Date("2026-08-07").toLocaleDateString()` prints the 6th anywhere west of Greenwich.
 */
export function formatObservationDate(date: string | null): string {
  if (!date) return "—";
  const [year, month, day] = date.split("-").map(Number);
  if (!year || !month || !day) return date;
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString(localeTag(getLanguage()), {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

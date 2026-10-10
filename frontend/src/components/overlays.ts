/**
 * Overlay instances: one configured indicator, drawn in one colour.
 *
 * The distinction that matters is between an *indicator* and an *instance of* one. The server's
 * catalog describes indicators; what a chart draws is instances — `sma:20`, `sma:50`, `sma:100`,
 * `sma:200` are four lines from one definition, and the whole point of a moving-average ribbon is
 * seeing them together. The backend already supports this (repeated `spec` parameters produce
 * distinct `sma_20` / `sma_50` columns); this is the model the UI needs to express it.
 *
 * Colour belongs to the instance, not the indicator, for the same reason: four SMAs in one colour
 * are unreadable, and which one is which has to be legible from the chart alone.
 */

import type { Interval } from "@/api/market";

export interface Overlay {
  /** Stable across param edits, so React keys and colour assignments survive retuning. */
  id: string;
  /** Indicator name from the catalog: `sma`, `bb`, `macd`. */
  name: string;
  title: string;
  /** The spec string sent to the API: `sma:50`, `bb:20,2`. */
  spec: string;
  color: string;
  /**
   * Copied from the catalog entry so a chart can filter without re-reading it. `null` means every
   * interval. The four-timeframe view depends on this: sending `vwap:session` to the daily panel
   * is a 400, so each panel drops the overlays its interval cannot support.
   */
  intervals: Interval[] | null;
}

/**
 * Distinguishable on a near-black ground, and deliberately avoiding the candle greens and reds --
 * an overlay that shares a colour with the price bars stops reading as a separate thing.
 */
export const OVERLAY_PALETTE = [
  "#39f2d0",
  "#ff4fd8",
  "#ffb454",
  "#9d7bff",
  "#b6f24a",
  "#4fc3ff",
  "#ff7a5c",
  "#5ce1e6",
] as const;

export function paletteColor(index: number): string {
  return OVERLAY_PALETTE[index % OVERLAY_PALETTE.length] ?? OVERLAY_PALETTE[0];
}

/** Overlays this interval can actually compute. See {@link Overlay.intervals}. */
export function overlaysFor(overlays: Overlay[], interval: Interval): Overlay[] {
  return overlays.filter((o) => o.intervals === null || o.intervals.includes(interval));
}

/**
 * Map each returned series key to its instance colour.
 *
 * Zipped by position rather than by parsing the key back out of the spec string. The API builds its
 * response by walking the `spec` parameters in order, so index *i* of the response is index *i* of
 * what was sent — whereas reconstructing `bb_20_2` from `bb:20,2` means reimplementing the server's
 * number formatting in TypeScript and staying bug-for-bug compatible with it forever.
 */
export function colorsByKey(sent: Overlay[], keys: string[]): Record<string, string> {
  const colors: Record<string, string> = {};
  keys.forEach((key, i) => {
    const overlay = sent[i];
    if (overlay) colors[key] = overlay.color;
  });
  return colors;
}

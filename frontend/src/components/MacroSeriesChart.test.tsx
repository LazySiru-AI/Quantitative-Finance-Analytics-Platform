/**
 * Unit tests for the pure span/range helpers behind `MacroSeriesChart` and `MacroTile`'s
 * sparkline caption. These are what fixes "I can't tell what span a line covers" -- so the
 * assertions pin the actual wording, not just that a string comes back non-empty.
 *
 * No component is rendered here (rendering `MacroSeriesChart` would exercise lightweight-charts
 * against a real DOM canvas, which is more than this file needs), so `setupTests.ts`'s
 * network-request guard never comes into play.
 */
import { describe, expect, it } from "vitest";

import type { MacroPoint } from "@/api/macro";
import {
  computeRangeChange,
  describeSpan,
  filterPointsByRange,
} from "@/components/MacroSeriesChart";
import { describeSparkSpan } from "@/components/MacroTile";

function points(pairs: [string, number | null][]): MacroPoint[] {
  return pairs.map(([date, value]) => ({ date, value }));
}

describe("describeSpan", () => {
  it("reports the actual first/last date, not the tab name", () => {
    const p = points([
      ["2025-08-07", 4.1],
      ["2026-08-07", 4.52],
    ]);
    expect(describeSpan(p)).toBe("Aug 7, 2025 – Aug 7, 2026 · 2 observations");
  });

  it("says so when a series only has a short history, even under a long-range tab", () => {
    // Simulates a 6-month-old series still plotted under the "5Y" tab: filterPointsByRange
    // would not have trimmed anything, and describeSpan must not imply five years.
    const p = points([
      ["2026-02-01", 100],
      ["2026-08-01", 110],
    ]);
    expect(describeSpan(p)).toBe("Feb 1, 2026 – Aug 1, 2026 · 2 observations");
  });

  it("counts only non-null points as observations, not calendar rows", () => {
    const p = points([
      ["2026-01-01", 10],
      ["2026-01-02", null],
      ["2026-01-03", null],
      ["2026-01-04", 12],
    ]);
    expect(describeSpan(p)).toBe("Jan 1, 2026 – Jan 4, 2026 · 2 observations");
  });

  it("reports no data for an empty series", () => {
    expect(describeSpan([])).toBe("No data");
  });

  it("reports no data when every point is null", () => {
    expect(describeSpan(points([["2026-01-01", null]]))).toBe("No data");
  });
});

describe("filterPointsByRange", () => {
  const monthly = points([
    ["2024-01-15", 1],
    ["2024-07-15", 2],
    ["2025-01-15", 3],
    ["2025-07-15", 4],
    ["2026-01-15", 5],
    ["2026-07-15", 6],
    ["2026-08-15", 7],
  ]);

  it("anchors the cutoff on the series' own last observation, not today's date", () => {
    const oneYear = filterPointsByRange(monthly, "1Y");
    expect(oneYear.map((p) => p.date)).toEqual(["2026-01-15", "2026-07-15", "2026-08-15"]);
  });

  it("MAX returns every point unchanged", () => {
    expect(filterPointsByRange(monthly, "MAX")).toEqual(monthly);
  });

  it("handles an empty series without throwing", () => {
    expect(filterPointsByRange([], "1M")).toEqual([]);
  });
});

describe("computeRangeChange", () => {
  it("reads a percent series in basis points", () => {
    const p = points([
      ["2026-01-01", 4.1],
      ["2026-06-01", 4.52],
    ]);
    const result = computeRangeChange(p, "percent");
    expect(result.mode).toBe("basis_points");
    expect(result.value).toBeCloseTo(42, 5);
  });

  it("reads a usd/index series in percent", () => {
    const p = points([
      ["2026-01-01", 100],
      ["2026-06-01", 112],
    ]);
    const result = computeRangeChange(p, "index");
    expect(result.mode).toBe("percent");
    expect(result.value).toBeCloseTo(12, 5);
  });

  it("returns null rather than dividing by zero on a flat-at-zero series", () => {
    const p = points([
      ["2026-01-01", 0],
      ["2026-06-01", 0],
    ]);
    expect(computeRangeChange(p, "usd").value).toBeNull();
  });

  it("returns null when fewer than two known values are in range", () => {
    const p = points([
      ["2026-01-01", null],
      ["2026-06-01", 4.5],
    ]);
    expect(computeRangeChange(p, "percent").value).toBeNull();
  });
});

describe("describeSparkSpan (MacroTile)", () => {
  it("derives the span from the data instead of a hard-coded window", () => {
    const spark = points([
      ["2026-06-01", 10],
      ["2026-07-01", 11],
      ["2026-08-30", 12],
    ]);
    expect(describeSparkSpan(spark)).toBe("90 days · Jun 1, 2026 – Aug 30, 2026");
  });

  it("handles an empty spark", () => {
    expect(describeSparkSpan([])).toBe("no data");
  });

  it("handles an all-null spark", () => {
    expect(describeSparkSpan(points([["2026-01-01", null]]))).toBe("no data");
  });

  it("handles a single known point without a nonsensical zero-day span", () => {
    expect(describeSparkSpan(points([["2026-08-01", 5]]))).toBe("Aug 1, 2026");
  });

  it("ignores null points at the edges when finding the span", () => {
    const spark = points([
      ["2026-05-01", null],
      ["2026-06-01", 10],
      ["2026-07-01", 11],
      ["2026-08-01", null],
    ]);
    expect(describeSparkSpan(spark)).toBe("30 days · Jun 1, 2026 – Jul 1, 2026");
  });
});

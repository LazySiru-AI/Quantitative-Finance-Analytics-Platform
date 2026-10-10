/**
 * Unit tests for `FearGreedHistoryChart`'s data-normalisation, the one piece with real logic. The
 * chart body is not rendered here on purpose: like `MacroSeriesChart.test`, it would exercise
 * `lightweight-charts`, which cannot draw under jsdom. The bug these guard against was found in the
 * browser, not in a test — CNN's `fear_and_greed_historical` block carries duplicate and out-of-order
 * dates, and lightweight-charts asserts "data must be asc ordered by time" and takes the whole panel
 * down through the error boundary. `normalizeHistory` is what stands between that feed and the chart.
 */
import { describe, expect, it } from "vitest";

import type { MacroPoint } from "@/api/macro";
import { normalizeHistory } from "@/components/FearGreedHistoryChart";

const p = (date: string, value: number | null): MacroPoint => ({ date, value });

describe("normalizeHistory", () => {
  it("collapses duplicate dates, keeping the last occurrence (the fresher reading)", () => {
    const out = normalizeHistory([p("2026-08-10", 40), p("2026-08-10", 55)]);
    expect(out).toHaveLength(1);
    expect(out[0]).toEqual({ date: "2026-08-10", value: 55 });
  });

  it("sorts ascending by date regardless of input order", () => {
    const out = normalizeHistory([p("2026-08-10", 60), p("2026-06-01", 30), p("2026-07-15", 45)]);
    expect(out.map((x) => x.date)).toEqual(["2026-06-01", "2026-07-15", "2026-08-10"]);
  });

  it("produces strictly increasing, unique dates from a duplicated, unsorted feed", () => {
    // The exact shape that crashed the chart: repeats and disorder together.
    const out = normalizeHistory([
      p("2026-08-10", 64),
      p("2026-08-10", 64),
      p("2026-06-12", 33),
      p("2026-07-01", 50),
      p("2026-06-12", 34),
    ]);
    const dates = out.map((x) => x.date);
    expect(dates).toEqual(["2026-06-12", "2026-07-01", "2026-08-10"]);
    for (let i = 1; i < dates.length; i++) {
      expect(dates[i]! > dates[i - 1]!).toBe(true);
    }
    // Last-wins survives even when the duplicate is not adjacent to its twin.
    expect(out.find((x) => x.date === "2026-06-12")?.value).toBe(34);
  });

  it("preserves null gaps as points rather than dropping them", () => {
    const out = normalizeHistory([p("2026-06-12", 33), p("2026-06-13", null), p("2026-06-14", 40)]);
    expect(out).toHaveLength(3);
    expect(out[1]).toEqual({ date: "2026-06-13", value: null });
  });

  it("returns an empty array unchanged", () => {
    expect(normalizeHistory([])).toEqual([]);
  });
});

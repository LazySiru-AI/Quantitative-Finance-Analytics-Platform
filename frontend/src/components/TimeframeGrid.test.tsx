/**
 * TimeframeGrid: off-the-happy-path panels keep the same footprint as a loaded one.
 *
 * `styles.css`'s `.timeframe-grid` stretches every panel in a row to the row's own height, but a
 * loading/error/no-bars panel has no `Chart` to give it a natural height -- just a one-line
 * `.placeholder`. Without a floor on that branch the row still "equalises" around whatever the
 * shortest panel happens to be, which collapses to that one line the moment every panel in a row is
 * off the happy path together (e.g. all four still loading), and then jumps again the instant a
 * `Chart` lands. `PANEL_HEIGHT`/`.timeframe-panel-placeholder` exist to keep all four panels the same
 * size in every phase, not just once data has arrived -- see the comment on `TimeframePanel` in
 * `TimeframeGrid.tsx`.
 *
 * jsdom has no layout engine, so "the same height" itself is not assertable here (left to the browser
 * probe, same caveat `Card.test.tsx` states for its own equal-height claim). What IS assertable is
 * that every off-the-happy-path branch renders the class that carries the floor, and that the loaded
 * branch does not (a `Chart` already has its own height and does not need one).
 *
 * `useChartSeries` and `Chart` are mocked at the module boundary -- this file's job is to prove the
 * grid gives every panel the right treatment for its own phase, not to re-test either the fetch hook
 * or the chart renderer.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Bar, Interval } from "@/api/market";
import type { ChartSeriesState } from "@/hooks/useChartSeries";

vi.mock("@/components/Chart", () => ({ default: () => <div data-testid="chart-stub" /> }));

const chartSeriesMock = vi.fn<(interval: Interval) => ChartSeriesState>();
vi.mock("@/hooks/useChartSeries", () => ({
  useChartSeries: (_symbol: string, interval: Interval) => chartSeriesMock(interval),
}));

const { default: TimeframeGrid } = await import("@/components/TimeframeGrid");

const BAR: Bar = {
  ts: "2026-09-08",
  open: 1,
  high: 1,
  low: 1,
  close: 1,
  adj_close: 1,
  volume: 100,
  partial: false,
};

function state(overrides: Partial<ChartSeriesState>): ChartSeriesState {
  return {
    bars: [],
    barsInterval: null,
    source: null,
    ts: [],
    tsInterval: null,
    series: [],
    colors: {},
    warnings: [],
    barsPhase: "loaded",
    barsMessage: null,
    indicatorsPhase: "idle",
    indicatorsMessage: null,
    ...overrides,
  };
}

/** One state per interval, covering every branch `TimeframePanel` can render: loading, an error, a
 *  genuinely empty series, and a loaded chart -- the remaining intervals reuse the loaded case so
 *  every one of the seven still renders something. */
function stateForInterval(interval: Interval): ChartSeriesState {
  switch (interval) {
    case "5m":
      return state({ barsPhase: "loading" });
    case "15m":
      return state({ barsPhase: "error", barsMessage: "Cannot reach the API" });
    case "30m":
      return state({ barsPhase: "loaded", bars: [] });
    default:
      return state({
        barsPhase: "loaded",
        bars: [BAR],
        barsInterval: interval,
        tsInterval: interval,
        source: "yahoo",
      });
  }
}

describe("TimeframeGrid", () => {
  it("floors the loading, error and no-bars panels to the chart's own height", () => {
    chartSeriesMock.mockImplementation(stateForInterval);
    render(<TimeframeGrid symbol="AAPL" overlays={[]} />);

    // Loading (5m), error (15m) and no-bars (30m) all render the placeholder floor.
    for (const label of ["AAPL 5m", "AAPL 15m", "AAPL 30m"]) {
      const panel = screen.getByRole("region", { name: label });
      const placeholder = panel.querySelector(".placeholder");
      expect(placeholder).not.toBeNull();
      expect(placeholder?.className).toContain("timeframe-panel-placeholder");
      // Inline, not class-only: the floor has to match `PANEL_HEIGHT`, the same number the `Chart`
      // below is given, and a CSS class alone cannot be asserted against that constant in jsdom.
      expect((placeholder as HTMLElement).style.minHeight).toBe("260px");
    }

    // A loaded panel renders its `Chart` instead, and gets no placeholder floor -- it already has a
    // real height from the chart itself.
    const loaded = screen.getByRole("region", { name: "AAPL 1h" });
    expect(loaded.querySelector(".timeframe-panel-placeholder")).toBeNull();
    expect(screen.getAllByTestId("chart-stub").length).toBeGreaterThan(0);
  });
});

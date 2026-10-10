/**
 * `useChartSeries` — the bars/interval pairing invariant.
 *
 * Found by a UAT button sweep on 2026-08-29, not by a test: switching the ticker chart from 4h to 1d
 * crashed it into its error boundary with lightweight-charts' "Assertion failed: data must be asc
 * ordered by time", 3/3 reproducible on both SPY and QQQ, and only in that direction.
 *
 * The cause is a one-render inconsistency rather than bad data. `Chart.toTime` renders a daily bar as
 * a `"YYYY-MM-DD"` business-day string and an intraday bar as epoch seconds. `Ticker` used to pass its
 * own `interval` state next to `single.bars`; on an interval change React re-renders with the new
 * interval **before** this hook's fetch effect has run, so for exactly one render the chart got the
 * previous 4h bars labelled `1d`, sliced every intraday timestamp to its date, and produced duplicates.
 * Measured against the live API: 998 4h bars yield 499 duplicate date strings that way, while daily
 * bars rendered as intraday stay strictly ascending — which is why only 4h → 1d ever crashed.
 *
 * `barsPhase` cannot guard this: it is set inside the same effect that has not run yet. So the fix is
 * to publish the interval the bars were actually fetched with and have the consumer pair with that,
 * making the mismatch unrepresentable. These tests pin that pairing, not the crash — the crash is a
 * downstream consequence and asserting on a chart library's assertion text would be brittle.
 */

import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Bar, BarSeries, IndicatorResponse, Interval } from "@/api/market";
import type { Overlay } from "@/components/overlays";
import { useChartSeries } from "@/hooks/useChartSeries";

const bars = vi.hoisted(() => vi.fn());
const indicators = vi.hoisted(() => vi.fn());

vi.mock("@/api/market", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/market")>();
  return { ...actual, marketApi: { ...actual.marketApi, bars, indicators } };
});

/** Two 4h bars inside one session — the pair that collapses to a single date string when a daily
 * renderer slices them, which is the whole mechanism. */
const FOUR_HOUR: Bar[] = [
  { ts: "2024-09-03T13:30:00Z", open: 1, high: 2, low: 1, close: 2, adj_close: null, volume: 10 },
  { ts: "2024-09-03T17:30:00Z", open: 2, high: 3, low: 2, close: 3, adj_close: null, volume: 20 },
] as Bar[];

const DAILY: Bar[] = [
  { ts: "2024-09-03T00:00:00Z", open: 1, high: 2, low: 1, close: 2, adj_close: 2, volume: 10 },
  { ts: "2024-09-04T00:00:00Z", open: 2, high: 3, low: 2, close: 3, adj_close: 3, volume: 20 },
] as Bar[];

function series(interval: Interval, rows: Bar[]): BarSeries {
  return { symbol: "SPY", interval, source: "store" as BarSeries["source"], bars: rows, warnings: [] };
}

describe("useChartSeries pairs bars with the interval they were fetched with", () => {
  beforeEach(() => {
    bars.mockReset();
    indicators.mockReset();
  });

  it("reports the interval its bars actually came from", async () => {
    bars.mockResolvedValue(series("4h", FOUR_HOUR));
    const { result } = renderHook(() => useChartSeries("SPY", "4h", []));

    await waitFor(() => expect(result.current.barsPhase).toBe("loaded"));
    expect(result.current.barsInterval).toBe("4h");
    expect(result.current.bars).toHaveLength(2);
  });

  it("keeps reporting the old interval while the new one is still in flight", async () => {
    // The regression. Between the click and the response, `bars` still holds 4h data — so
    // `barsInterval` must still say "4h". A consumer reading the *selected* interval here would
    // render intraday bars through the daily code path.
    bars.mockResolvedValue(series("4h", FOUR_HOUR));
    const { result, rerender } = renderHook(
      ({ interval }: { interval: Interval }) => useChartSeries("SPY", interval, []),
      { initialProps: { interval: "4h" as Interval } },
    );
    await waitFor(() => expect(result.current.barsInterval).toBe("4h"));

    // Switch to 1d with the fetch deliberately never resolving.
    bars.mockReturnValue(new Promise<BarSeries>(() => {}));
    rerender({ interval: "1d" as Interval });

    expect(result.current.bars).toBe(result.current.bars);
    expect(result.current.barsInterval).toBe("4h");
    // And the pair is self-consistent: the bars on hand are the 4h ones it still names.
    expect(result.current.bars[0]?.ts).toBe("2024-09-03T13:30:00Z");
  });

  it("flips bars and interval together once the new fetch resolves", async () => {
    bars.mockResolvedValue(series("4h", FOUR_HOUR));
    const { result, rerender } = renderHook(
      ({ interval }: { interval: Interval }) => useChartSeries("SPY", interval, []),
      { initialProps: { interval: "4h" as Interval } },
    );
    await waitFor(() => expect(result.current.barsInterval).toBe("4h"));

    bars.mockResolvedValue(series("1d", DAILY));
    await act(async () => {
      rerender({ interval: "1d" as Interval });
    });

    await waitFor(() => expect(result.current.barsInterval).toBe("1d"));
    expect(result.current.bars[0]?.ts).toBe("2024-09-03T00:00:00Z");
    expect(result.current.bars).toHaveLength(2);
  });

  it("clears the interval when the fetch fails, so no stale pairing survives an error", async () => {
    bars.mockResolvedValue(series("4h", FOUR_HOUR));
    const { result, rerender } = renderHook(
      ({ interval }: { interval: Interval }) => useChartSeries("SPY", interval, []),
      { initialProps: { interval: "4h" as Interval } },
    );
    await waitFor(() => expect(result.current.barsInterval).toBe("4h"));

    bars.mockRejectedValue(new Error("upstream is down"));
    await act(async () => {
      rerender({ interval: "1d" as Interval });
    });

    await waitFor(() => expect(result.current.bars).toHaveLength(0));
    expect(result.current.barsInterval).toBeNull();
  });
});

/**
 * The second half of the same pairing invariant, one effect over. `bars`/`barsInterval` are set
 * together (proven above), but the indicators effect used to set `ts`/`series` with no paired
 * interval at all -- so a user switching interval with overlays active could have the indicators
 * request resolve before the bars request, leaving `Ticker.tsx` holding fresh `ts`/`series` for the
 * *new* interval next to `barsInterval` still naming the *old* one. `Chart.tsx` renders `series`/`ts`
 * under whatever `interval` its caller passes for the candles, so that mismatch is exactly the
 * "4h data captioned 1d" shape the bars-side fix above already solved once. `tsInterval` closes the
 * other half: consumers must gate `series`/`ts` on `tsInterval === barsInterval` (see `Ticker.tsx`).
 */
function indicatorResponse(interval: Interval, ts: string[]): IndicatorResponse {
  return {
    symbol: "SPY",
    interval,
    ts,
    series: [{ key: "sma_50", name: "sma", title: "SMA 50", pane: "price", columns: { sma_50: ts.map(() => 1) }, warmup: 0 }],
    warnings: [],
  };
}

const OVERLAY: Overlay = {
  id: "o1",
  name: "sma",
  title: "SMA 50",
  spec: "sma:50",
  color: "#39f2d0",
  intervals: null,
};

describe("useChartSeries pairs ts/series with the interval they were fetched with", () => {
  beforeEach(() => {
    bars.mockReset();
    indicators.mockReset();
    // Bars resolve immediately in every test below -- these tests are about the indicators pairing,
    // not the bars one already covered above.
    bars.mockResolvedValue(series("4h", FOUR_HOUR));
  });

  it("reports the interval its indicators actually came from", async () => {
    indicators.mockResolvedValue(indicatorResponse("4h", ["2024-09-03T13:30:00Z"]));
    const { result } = renderHook(() => useChartSeries("SPY", "4h", [OVERLAY]));

    await waitFor(() => expect(result.current.indicatorsPhase).toBe("loaded"));
    expect(result.current.tsInterval).toBe("4h");
    expect(result.current.ts).toEqual(["2024-09-03T13:30:00Z"]);
  });

  it("does not hand out ts/series under the new interval before tsInterval agrees with it", async () => {
    // The regression: the indicators request for the *new* interval resolves before the bars
    // request does, so `tsInterval` must keep naming the *old* interval until its own fetch settles
    // -- never silently adopt the argument.
    indicators.mockResolvedValue(indicatorResponse("4h", ["2024-09-03T13:30:00Z"]));
    const { result, rerender } = renderHook(
      ({ interval }: { interval: Interval }) => useChartSeries("SPY", interval, [OVERLAY]),
      { initialProps: { interval: "4h" as Interval } },
    );
    await waitFor(() => expect(result.current.tsInterval).toBe("4h"));

    // Switch to 1d: indicators resolve fast, bars never do (irrelevant to this hook's own state, but
    // matches the real race this test reproduces).
    indicators.mockResolvedValue(indicatorResponse("1d", ["2024-09-03"]));
    bars.mockReturnValue(new Promise<BarSeries>(() => {}));
    await act(async () => {
      rerender({ interval: "1d" as Interval });
    });

    await waitFor(() => expect(result.current.tsInterval).toBe("1d"));
    // Self-consistent: the `ts` on hand actually came from the 1d response `tsInterval` now names,
    // not stale 4h data mislabelled.
    expect(result.current.ts).toEqual(["2024-09-03"]);
  });

  it("clears tsInterval when the indicators fetch fails, so no stale pairing survives an error", async () => {
    indicators.mockResolvedValue(indicatorResponse("4h", ["2024-09-03T13:30:00Z"]));
    const { result, rerender } = renderHook(
      ({ interval }: { interval: Interval }) => useChartSeries("SPY", interval, [OVERLAY]),
      { initialProps: { interval: "4h" as Interval } },
    );
    await waitFor(() => expect(result.current.tsInterval).toBe("4h"));

    indicators.mockRejectedValue(new Error("upstream is down"));
    await act(async () => {
      rerender({ interval: "1d" as Interval });
    });

    await waitFor(() => expect(result.current.indicatorsPhase).toBe("error"));
    expect(result.current.tsInterval).toBeNull();
  });
});

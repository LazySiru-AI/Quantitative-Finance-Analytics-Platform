/**
 * `Chart`'s marker wiring: the only thing under test here is the `setMarkers` seam, not the rest of
 * the chart (candles/volume/overlays would exercise lightweight-charts against a real canvas, which
 * `MacroSeriesChart.test.tsx` deliberately avoids for the same reason). `lightweight-charts` is
 * mocked at the module boundary, same idiom as the `vi.mock("@/api/...")` stubs in
 * `Overview.test.tsx` -- a factory registered with `vi.mock`, backed by `vi.hoisted` handles so the
 * assertions in each test can reach the same mock instances the component used.
 *
 * What these tests pin:
 *  - markers are sorted time-ascending before reaching `setMarkers`, regardless of input order --
 *    lightweight-charts requires ascending order and misbehaves silently otherwise;
 *  - a changed `markers` prop causes a fresh `setMarkers` call with the new data, not a stale one;
 *  - an empty/undefined `markers` prop clears any previous markers via `setMarkers([])`, rather than
 *    leaving the last non-empty set on the chart.
 */
import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Bar, IndicatorSeries } from "@/api/market";
import Chart, { type ChartMarker } from "@/components/Chart";

// jsdom has no ResizeObserver; Chart.tsx observes both chart containers unconditionally.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(globalThis as any).ResizeObserver = ResizeObserverStub;

const { setMarkersMock, setDataMock, createChartMock, addCandlestickSeriesMock } = vi.hoisted(
  () => ({
    setMarkersMock: vi.fn(),
    setDataMock: vi.fn(),
    createChartMock: vi.fn(),
    addCandlestickSeriesMock: vi.fn(),
  }),
);

vi.mock("lightweight-charts", () => ({
  ColorType: { Solid: "solid" },
  LineStyle: { Solid: 0, Dashed: 2 },
  createChart: createChartMock,
}));

// Re-applied before every test rather than supplied once at `vi.fn()` creation: the suite's
// `restoreMocks: true` (vitest.config.ts) restores every mock before each test, and a `beforeEach`
// here is guaranteed to run after that regardless of exactly how vitest orders the built-in step.
beforeEach(() => {
  addCandlestickSeriesMock.mockImplementation(() => ({
    setData: setDataMock,
    setMarkers: setMarkersMock,
  }));
  createChartMock.mockImplementation(() => ({
    addCandlestickSeries: addCandlestickSeriesMock,
    addHistogramSeries: vi.fn(() => ({
      setData: vi.fn(),
      priceScale: () => ({ applyOptions: vi.fn() }),
      createPriceLine: vi.fn(),
    })),
    addLineSeries: vi.fn(() => ({ setData: vi.fn() })),
    resize: vi.fn(),
    remove: vi.fn(),
    timeScale: () => ({
      subscribeVisibleLogicalRangeChange: vi.fn(),
      setVisibleLogicalRange: vi.fn(),
      applyOptions: vi.fn(),
    }),
  }));
});

afterEach(() => {
  setMarkersMock.mockClear();
  setDataMock.mockClear();
});

// Volume is omitted (`volume: null`) purely to keep the mock surface small -- these tests assert
// nothing about the histogram series.
const bars: Bar[] = [
  {
    ts: "2026-01-01T00:00:00Z",
    open: 10,
    high: 11,
    low: 9,
    close: 10.5,
    adj_close: null,
    volume: null,
    partial: false,
  },
  {
    ts: "2026-01-02T00:00:00Z",
    open: 10.5,
    high: 12,
    low: 10,
    close: 11.5,
    adj_close: null,
    volume: null,
    partial: false,
  },
  {
    ts: "2026-01-03T00:00:00Z",
    open: 11.5,
    high: 12.5,
    low: 11,
    close: 12,
    adj_close: null,
    volume: null,
    partial: false,
  },
];

// Stable references, reused across every render call in this file. `series`/`ts` sit in the same
// effect dependency array as `markers`; a fresh `[]` literal on every render would make the effect
// re-run (and re-call setMarkers) regardless of what markers actually changed, which would make the
// "content-identical markers, no re-apply" test meaningless.
const emptySeries: IndicatorSeries[] = [];
const emptyTs: string[] = [];

function renderChart(markers?: ChartMarker[]) {
  // Spread rather than pass `markers={markers}` directly: with `exactOptionalPropertyTypes` on, an
  // explicit `markers={undefined}` is not assignable to the optional `markers?: ChartMarker[]` prop
  // (absent-key and present-but-undefined are distinct types) -- so the key must be omitted
  // entirely for the "no markers prop" case, exactly as a real caller would.
  const props = markers !== undefined ? { markers } : {};
  return render(<Chart bars={bars} series={emptySeries} ts={emptyTs} interval="1d" {...props} />);
}

describe("Chart markers", () => {
  it("sorts markers ascending by time before calling setMarkers, regardless of input order", () => {
    const markers: ChartMarker[] = [
      {
        time: "2026-01-03T00:00:00Z",
        position: "aboveBar",
        shape: "arrowDown",
        color: "#ff0000",
        text: "sell",
      },
      {
        time: "2026-01-01T00:00:00Z",
        position: "belowBar",
        shape: "arrowUp",
        color: "#00ff00",
        text: "buy",
      },
      {
        time: "2026-01-02T00:00:00Z",
        position: "aboveBar",
        shape: "circle",
        color: "#0000ff",
      },
    ];

    renderChart(markers);

    expect(setMarkersMock).toHaveBeenCalledTimes(1);
    // "1d" bars render as the session date string (see `toTime`), so the sorted, converted output
    // is asserted verbatim rather than re-deriving it from the input.
    expect(setMarkersMock).toHaveBeenLastCalledWith([
      { time: "2026-01-01", position: "belowBar", shape: "arrowUp", color: "#00ff00", text: "buy" },
      { time: "2026-01-02", position: "aboveBar", shape: "circle", color: "#0000ff", text: undefined },
      { time: "2026-01-03", position: "aboveBar", shape: "arrowDown", color: "#ff0000", text: "sell" },
    ]);
  });

  it("calls setMarkers with an empty array when no markers prop is given", () => {
    renderChart();

    expect(setMarkersMock).toHaveBeenCalledTimes(1);
    expect(setMarkersMock).toHaveBeenLastCalledWith([]);
  });

  it("re-applies setMarkers with the new data when the markers prop changes", () => {
    const first: ChartMarker[] = [
      { time: "2026-01-01T00:00:00Z", position: "aboveBar", shape: "circle", color: "#123456" },
    ];
    const second: ChartMarker[] = [
      { time: "2026-01-02T00:00:00Z", position: "belowBar", shape: "square", color: "#654321" },
    ];

    const { rerender } = renderChart(first);
    expect(setMarkersMock).toHaveBeenCalledTimes(1);
    expect(setMarkersMock).toHaveBeenLastCalledWith([
      { time: "2026-01-01", position: "aboveBar", shape: "circle", color: "#123456", text: undefined },
    ]);

    rerender(<Chart bars={bars} series={emptySeries} ts={emptyTs} interval="1d" markers={second} />);

    expect(setMarkersMock).toHaveBeenCalledTimes(2);
    expect(setMarkersMock).toHaveBeenLastCalledWith([
      { time: "2026-01-02", position: "belowBar", shape: "square", color: "#654321", text: undefined },
    ]);
  });

  it("does not re-apply setMarkers when a new, content-identical markers array is passed", () => {
    const markersA: ChartMarker[] = [
      { time: "2026-01-01T00:00:00Z", position: "aboveBar", shape: "circle", color: "#123456" },
    ];
    const markersB: ChartMarker[] = [
      { time: "2026-01-01T00:00:00Z", position: "aboveBar", shape: "circle", color: "#123456" },
    ];

    const { rerender } = renderChart(markersA);
    expect(setMarkersMock).toHaveBeenCalledTimes(1);

    rerender(<Chart bars={bars} series={emptySeries} ts={emptyTs} interval="1d" markers={markersB} />);

    // Same content, different array reference: the effect's `markersKey` (JSON.stringify) must not
    // see a change, so no teardown/rebuild and no second setMarkers call -- mirrors the `colorKey`
    // behaviour for the `colors` prop.
    expect(setMarkersMock).toHaveBeenCalledTimes(1);
  });

  it("clears markers via setMarkers([]) when the prop goes from populated to undefined", () => {
    const markers: ChartMarker[] = [
      { time: "2026-01-01T00:00:00Z", position: "aboveBar", shape: "circle", color: "#123456" },
    ];

    const { rerender } = renderChart(markers);
    expect(setMarkersMock).toHaveBeenLastCalledWith([expect.objectContaining({ time: "2026-01-01" })]);

    rerender(<Chart bars={bars} series={emptySeries} ts={emptyTs} interval="1d" />);

    expect(setMarkersMock).toHaveBeenCalledTimes(2);
    expect(setMarkersMock).toHaveBeenLastCalledWith([]);
  });
});

/**
 * Candlestick chart, themed to the terminal palette.
 *
 * lightweight-charts v4 has no built-in multi-pane layout. Overlay indicators (`pane: "price"`,
 * e.g. SMA, Bollinger Bands, anchored VWAP) draw on the same chart instance as the candles.
 * Oscillator indicators (`pane: "oscillator"`, e.g. RSI, MACD) need their own y-axis scale, so they
 * get a second, stacked chart instance whose time scale is kept in lock-step with the first by
 * hand -- see the sync block below.
 */
import { useEffect, useRef } from "react";
import { ColorType, LineStyle, createChart } from "lightweight-charts";
import type {
  CandlestickData,
  HistogramData,
  IChartApi,
  LineData,
  LogicalRange,
  Time,
  UTCTimestamp,
  WhitespaceData,
} from "lightweight-charts";

import type { Bar, IndicatorSeries, Interval } from "@/api/market";

interface ChartProps {
  bars: Bar[];
  series: IndicatorSeries[];
  ts: string[];
  interval: Interval;
  /**
   * Series key -> line colour, chosen by the overlay picker. Passed in rather than assigned here so
   * the swatch beside `sma:50` in the controls is the same colour as the line on the chart. A chart
   * that picks its own colours by draw order silently renumbers every line whenever one is removed.
   */
  colors?: Record<string, string>;
  height?: number;
  /** Hides the volume histogram and thins the axes, for the four-up timeframe grid. */
  compact?: boolean;
  /**
   * "This rule fired on this bar." Rendered as `SeriesMarker`s on the candlestick series via
   * `setMarkers`. Optional and independent of `series` -- a rule signal is not an indicator output.
   */
  markers?: ChartMarker[];
}

/** Mirrors lightweight-charts' own `SeriesMarkerPosition`/`SeriesMarkerShape` unions (v4 also allows
 *  `"inBar"`, deliberately omitted here -- a rule fires on a closed bar, never inside one). */
export type ChartMarkerPosition = "aboveBar" | "belowBar";
export type ChartMarkerShape = "arrowUp" | "arrowDown" | "circle" | "square";

/**
 * One rule-fired annotation. Field names mirror lightweight-charts' `SeriesMarker` (`position`,
 * `shape`, `color`, `text`) so the mapping in the effect below is a straight pass-through, but `time`
 * is kept as the ISO string every other caller in this file already uses for a bar -- the same
 * convention as `Bar.ts` -- and is run through the existing `toTime()` helper, not the library's
 * `Time` type, so a caller building markers from `bars`/`ts` never has to pre-convert.
 */
export interface ChartMarker {
  time: string;
  position: ChartMarkerPosition;
  shape: ChartMarkerShape;
  color: string;
  text?: string;
}

const DEFAULT_HEIGHT = 360;
const OSCILLATOR_HEIGHT = 140;

/** Fallback only, for a series with no assigned colour. */
const LINE_COLOR_VARS = ["--accent", "--accent-2", "--warn", "--up", "--down"] as const;

/**
 * Within one multi-output indicator the columns share the instance colour and separate by dash
 * pattern: a Bollinger band is one idea drawn as three lines, and colouring the envelope
 * differently from its own midline breaks that reading.
 */
function lineStyleFor(columnKey: string, seriesKey: string): { dashed: boolean; width: 1 | 2 } {
  if (columnKey === seriesKey) return { dashed: false, width: 2 };
  const suffix = columnKey.slice(seriesKey.length + 1);
  if (suffix === "upper" || suffix === "lower" || suffix === "signal") {
    return { dashed: true, width: 1 };
  }
  return { dashed: false, width: 1 };
}

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value.length > 0 ? value : fallback;
}

/**
 * Daily and weekly bars are the exchange-local session date at midnight UTC (see `session_date`
 * in the backend contract). lightweight-charts renders a `"YYYY-MM-DD"` business-day string as
 * that session date on the axis; feeding it a UTC-seconds timestamp instead would put the label a
 * day off for any reader west of UTC. Intraday bars keep the true instant, in seconds.
 */
function toTime(ts: string, interval: Interval): Time {
  if (interval === "1d" || interval === "1w") {
    return ts.slice(0, 10);
  }
  return Math.floor(new Date(ts).getTime() / 1000) as UTCTimestamp;
}

/** `"bb_20_2_upper"` -> `"Bollinger Bands upper"` rather than the raw column key. */
function columnLabel(series: IndicatorSeries, columnKey: string): string {
  if (columnKey === series.key) return series.title;
  const prefix = `${series.key}_`;
  if (columnKey.startsWith(prefix)) return `${series.title} ${columnKey.slice(prefix.length)}`;
  return `${series.title} ${columnKey}`;
}

/**
 * `null` is the warmup window (or an anchored indicator's undefined stretch) and must never reach
 * the chart as a plotted value -- a Bollinger band reading 0 through warmup draws a spike to the
 * axis that reads as a crash.
 *
 * A `null` becomes a *whitespace* point (`{ time }` with no `value`) rather than being dropped.
 * Dropping is adequate for a leading warmup, where the line simply starts later, but it is wrong
 * for a gap in the middle of a series: with the point omitted the renderer joins the values either
 * side of the hole into one continuous segment, drawing a line across data that does not exist.
 * Whitespace keeps the bar on the time scale and breaks the line there, which is what the absence
 * actually means.
 */
function buildLinePoints(
  values: (number | null)[],
  ts: string[],
  interval: Interval,
): (LineData | WhitespaceData)[] {
  const points: (LineData | WhitespaceData)[] = [];
  const len = Math.min(values.length, ts.length);
  for (let i = 0; i < len; i++) {
    const value = values[i];
    const t = ts[i];
    if (t === undefined) continue;
    const time = toTime(t, interval);
    if (value === null || value === undefined || !Number.isFinite(value)) {
      points.push({ time });
    } else {
      points.push({ time, value });
    }
  }
  return points;
}

/** True for a column that is a signed distance derived from two other lines in the same series
 * (MACD's `hist = macd - signal`, and any future oscillator output shaped the same way). Drawn as
 * a line it is just a third, redundant curve indistinguishable from the gap between the other two;
 * drawn as bars its magnitude *and* sign both read at a glance, which is the point of a histogram
 * output in the first place. */
function isHistogramColumn(columnKey: string, seriesKey: string): boolean {
  if (columnKey === seriesKey) return false;
  return columnKey.slice(seriesKey.length + 1) === "hist";
}

/**
 * Same null-safety as `buildLinePoints` (see above) but for histogram bars: warmup/gap values
 * become whitespace points, never a bar sitting at `value: 0`, which would read as a real
 * macd/signal crossover instead of "no data yet". Each bar is coloured by sign so the histogram's
 * two readings -- above/below zero, and how far -- are both visible without a legend.
 */
function buildHistogramPoints(
  values: (number | null)[],
  ts: string[],
  interval: Interval,
  upColor: string,
  downColor: string,
): (HistogramData | WhitespaceData)[] {
  const points: (HistogramData | WhitespaceData)[] = [];
  const len = Math.min(values.length, ts.length);
  for (let i = 0; i < len; i++) {
    const value = values[i];
    const t = ts[i];
    if (t === undefined) continue;
    const time = toTime(t, interval);
    if (value === null || value === undefined || !Number.isFinite(value)) {
      points.push({ time });
    } else {
      points.push({ time, value, color: value >= 0 ? upColor : downColor });
    }
  }
  return points;
}

/**
 * `--up`/`--down` are theme CSS custom properties and are not guaranteed to resolve to a 6-digit
 * hex (a themer could set `rgb(...)`, a name, `oklch(...)`, etc.). Appending an alpha suffix to
 * anything else produces an invalid colour string lightweight-charts will silently fail to apply.
 * Only known-safe 6-digit hex gets the translucent variant; everything else stays solid.
 */
function translucent(color: string, alphaHex: string): string {
  return /^#[0-9a-fA-F]{6}$/.test(color) ? `${color}${alphaHex}` : color;
}

export default function Chart({
  bars,
  series,
  ts,
  interval,
  colors,
  height,
  compact = false,
  markers,
}: ChartProps) {
  const priceContainerRef = useRef<HTMLDivElement | null>(null);
  const oscContainerRef = useRef<HTMLDivElement | null>(null);
  const priceHeight = height ?? DEFAULT_HEIGHT;
  const hasOscillator = series.some((s) => s.pane === "oscillator");
  const colorKey = JSON.stringify(colors ?? {});
  // Same by-content-key trick as `colorKey` just above: a caller re-deriving the same markers on
  // every render (a new array literal, identical entries) must not tear down and rebuild the whole
  // chart, only a change in the actual marker content should.
  const markersKey = JSON.stringify(markers ?? []);

  useEffect(() => {
    const priceContainer = priceContainerRef.current;
    if (!priceContainer) return;

    const textColor = cssVar("--muted", "#7c93a0");
    const gridColor = cssVar("--border", "#1b2530");
    const borderColor = cssVar("--border", "#1b2530");
    const accentColor = cssVar("--accent", "#39f2d0");
    const upColor = cssVar("--up", "#35e28a");
    const downColor = cssVar("--down", "#ff4d6a");
    // Phrased as "not daily-or-weekly" rather than by listing the intraday values, so a new
    // sub-daily interval gets its time axis automatically. This mirrors the same daily/intraday
    // split `toTime` makes above -- the two must agree, or a bar's axis label contradicts its
    // own x-position.
    const timeVisible = interval !== "1d" && interval !== "1w";

    function baseOptions(el: HTMLDivElement, chartHeight: number) {
      return {
        width: el.clientWidth,
        height: chartHeight,
        layout: {
          background: { type: ColorType.Solid, color: "transparent" },
          textColor,
          fontFamily: "var(--font-mono)",
        },
        grid: {
          vertLines: { color: gridColor },
          horzLines: { color: gridColor },
        },
        crosshair: {
          vertLine: { color: accentColor, labelBackgroundColor: accentColor },
          horzLine: { color: accentColor, labelBackgroundColor: accentColor },
        },
        rightPriceScale: { borderColor },
        timeScale: { borderColor, timeVisible, secondsVisible: false },
      };
    }

    let colorIndex = 0;
    function colorFor(seriesKey: string): string {
      const assigned = colors?.[seriesKey];
      if (assigned) return assigned;
      const varName = LINE_COLOR_VARS[colorIndex % LINE_COLOR_VARS.length] ?? "--accent";
      colorIndex += 1;
      return cssVar(varName, accentColor);
    }

    const chart = createChart(priceContainer, baseOptions(priceContainer, priceHeight));

    const candleSeries = chart.addCandlestickSeries({
      upColor,
      downColor,
      borderUpColor: upColor,
      borderDownColor: downColor,
      wickUpColor: upColor,
      wickDownColor: downColor,
    });
    const candleData: CandlestickData[] = bars.map((b) => ({
      time: toTime(b.ts, interval),
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));
    candleSeries.setData(candleData);

    // Markers must be time-ascending -- lightweight-charts requires it and misbehaves silently
    // (markers missing or mis-placed) if it isn't, so sort defensively rather than trust the caller.
    // Sorting on the original ISO string is enough: lexicographic order on a full ISO 8601 timestamp
    // is chronological order, and it sidesteps comparing mixed `Time` shapes (number vs "YYYY-MM-DD").
    const sortedMarkers = [...(markers ?? [])]
      .sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0))
      .map((m) => ({
        time: toTime(m.time, interval),
        position: m.position,
        shape: m.shape,
        color: m.color,
        // `exactOptionalPropertyTypes` (and `SeriesMarker.text` itself) treat an explicit
        // `text: undefined` as distinct from the key being absent -- only carry the key over when
        // a label was actually given.
        ...(m.text !== undefined ? { text: m.text } : {}),
      }));
    // Always called, even with an empty array -- that's what clears a previous set of markers when
    // the prop goes empty/undefined, with no separate branch to forget.
    candleSeries.setMarkers(sortedMarkers);

    const volumeData: HistogramData[] = [];
    for (const b of bars) {
      if (b.volume === null) continue;
      volumeData.push({
        time: toTime(b.ts, interval),
        value: b.volume,
        color: b.close >= b.open ? upColor : downColor,
      });
    }
    // Volume is dropped in the four-up grid: at a third of the height it compresses the price
    // range it sits under without being readable itself.
    if (volumeData.length > 0 && !compact) {
      const volumeSeries = chart.addHistogramSeries({
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
        color: upColor,
      });
      volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      volumeSeries.setData(volumeData);
    }

    for (const s of series) {
      if (s.pane !== "price") continue;
      const color = colorFor(s.key);
      for (const [columnKey, values] of Object.entries(s.columns)) {
        const style = lineStyleFor(columnKey, s.key);
        const line = chart.addLineSeries({
          color,
          lineWidth: compact ? 1 : style.width,
          lineStyle: style.dashed ? LineStyle.Dashed : LineStyle.Solid,
          title: compact ? "" : columnLabel(s, columnKey),
        });
        line.setData(buildLinePoints(values, ts, interval));
      }
    }

    let oscChart: IChartApi | null = null;
    const oscContainer = oscContainerRef.current;
    const oscillatorSeries = series.filter((s) => s.pane === "oscillator");
    if (oscillatorSeries.length > 0 && oscContainer) {
      oscChart = createChart(oscContainer, baseOptions(oscContainer, OSCILLATOR_HEIGHT));
      let zeroBaselineDrawn = false;
      for (const s of oscillatorSeries) {
        const color = colorFor(s.key);
        for (const [columnKey, values] of Object.entries(s.columns)) {
          if (isHistogramColumn(columnKey, s.key)) {
            // No `priceScaleId` here, same as the line series below: leaving it unset puts the
            // bars on the shared default ("right") price scale, so `hist` reads on the same axis
            // and in the same units as the `macd`/`signal` lines it was derived from, rather than
            // getting auto-scaled against its own tiny range on a separate scale.
            const hist = oscChart.addHistogramSeries({
              base: 0,
              title: compact ? "" : columnLabel(s, columnKey),
            });
            hist.setData(
              buildHistogramPoints(
                values,
                ts,
                interval,
                translucent(upColor, "cc"),
                translucent(downColor, "cc"),
              ),
            );
            // Zero is meaningful for every histogram output (sign is the whole point), so one
            // price line per oscillator pane is enough even if more than one histogram column is
            // ever present.
            if (!zeroBaselineDrawn) {
              hist.createPriceLine({
                price: 0,
                color: borderColor,
                lineWidth: 1,
                lineStyle: LineStyle.Solid,
                axisLabelVisible: false,
                title: "",
              });
              zeroBaselineDrawn = true;
            }
            continue;
          }
          const style = lineStyleFor(columnKey, s.key);
          const line = oscChart.addLineSeries({
            color,
            lineWidth: compact ? 1 : style.width,
            lineStyle: style.dashed ? LineStyle.Dashed : LineStyle.Solid,
            title: compact ? "" : columnLabel(s, columnKey),
          });
          line.setData(buildLinePoints(values, ts, interval));
        }
      }

      // Mirror each chart's visible range onto the other. `syncing` breaks the feedback loop --
      // without it, mirroring chart A's change onto chart B fires B's own subscription, which
      // mirrors back onto A, forever.
      const priceChart = chart;
      const secondChart = oscChart;
      let syncing = false;
      const onPriceRange = (range: LogicalRange | null) => {
        if (syncing || range === null) return;
        syncing = true;
        secondChart.timeScale().setVisibleLogicalRange(range);
        syncing = false;
      };
      const onOscRange = (range: LogicalRange | null) => {
        if (syncing || range === null) return;
        syncing = true;
        priceChart.timeScale().setVisibleLogicalRange(range);
        syncing = false;
      };
      priceChart.timeScale().subscribeVisibleLogicalRangeChange(onPriceRange);
      secondChart.timeScale().subscribeVisibleLogicalRangeChange(onOscRange);
    }

    const resizeObserver = new ResizeObserver(() => {
      chart.resize(priceContainer.clientWidth, priceHeight);
      if (oscChart && oscContainer) {
        oscChart.resize(oscContainer.clientWidth, OSCILLATOR_HEIGHT);
      }
    });
    resizeObserver.observe(priceContainer);
    if (oscContainer) resizeObserver.observe(oscContainer);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      oscChart?.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars, series, ts, interval, priceHeight, compact, colorKey, markersKey]);

  return (
    <div className="chart-wrap">
      <div ref={priceContainerRef} className="chart-container" style={{ height: priceHeight }} />
      <div
        ref={oscContainerRef}
        className="oscillator-container"
        style={{ height: OSCILLATOR_HEIGHT, display: hasOscillator ? "block" : "none" }}
      />
    </div>
  );
}

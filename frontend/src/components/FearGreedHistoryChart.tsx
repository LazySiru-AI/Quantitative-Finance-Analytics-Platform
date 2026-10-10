/**
 * Interactive history chart for the Fear & Greed index — the readable replacement for the bare
 * pink sparkline that used to sit in `FearGreedGauge`.
 *
 * A reader looking at the old sparkline could not answer any of the three questions that make this
 * number mean anything: *what span* does the line cover, *what scale* is it on, and *when was the
 * market afraid vs greedy*. This chart answers all three, and does it the same way the WTI / Dollar
 * Index charts a few centimetres up the same Overview page do — same `lightweight-charts` library,
 * same range-tab chrome, same honest span line — so Fear & Greed stops being the one panel whose
 * history you cannot read.
 *
 * What is specific to a 0–100 sentiment index, and why a generic `MacroSeriesChart` would not do:
 *
 * - **The y-axis is pinned to 0–100**, not autoscaled to the data's own min/max. A sentiment index
 *   that ranged 33–64 over the window must still be drawn against the full 0–100 field, or "64"
 *   reads as if it were near the top of the scale when it is in fact mild greed. `autoscaleInfoProvider`
 *   forces the fixed domain.
 * - **The rating bands are drawn on the plot** as horizontal reference lines at the real
 *   `ratingFor` cut-points (25 / 45 / 55 / 75). This is what turns a line into something a reader can
 *   interpret without a legend in their head: the line crossing 55 upward *is* the market tipping
 *   into greed.
 * - **It takes points directly**, not a `seriesId` to fetch. Fear & Greed is not a registered
 *   `/api/macro/series/{id}` — its history arrives embedded in the `/api/macro/fear-greed` payload —
 *   so this component is handed `data.history` and never fetches.
 *
 * Empty history is a real, expected state (the local composite fallback carries none, and tests pass
 * `history: []`). It renders an explained absence and never initialises the chart — which also keeps
 * it safe under jsdom, where `lightweight-charts` cannot draw.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { ColorType, LineStyle, createChart } from "lightweight-charts";
import type { IChartApi, ISeriesApi, LineData, Time, WhitespaceData } from "lightweight-charts";

import type { MacroPoint, Rating } from "@/api/macro";
import { formatObservationDate, ratingFor } from "@/api/macro";
import { describeSpan, filterPointsByRange, type RangeKey } from "@/components/MacroSeriesChart";
import { useT, type MessageKey, type Translator } from "@/i18n";

import "./FearGreedHistoryChart.css";

export interface FearGreedHistoryChartProps {
  /** The `data.history` from a `FearGreed` reading. Oldest first; `null` values are gaps. */
  points: MacroPoint[];
  /** Pixel height of the plot area. Default 200. */
  height?: number;
}

/** The range tabs offered here — a subset of `MacroSeriesChart`'s, dropping `5Y` because CNN's
 * history block does not reach that far and an always-empty tab is worse than an absent one. */
const RANGES: RangeKey[] = ["1M", "3M", "6M", "1Y", "MAX"];

/** The rating band boundaries, straight off `ratingFor` (frontend) / `rating_for` (backend). Drawn
 * as labelled reference lines so the plotted line can be read against the bands it moves through.
 * `emphasis` marks the two boundaries a reader cares about most — the fear line and the greed line —
 * which are drawn solid; the extreme cut-points are dashed and quieter.
 *
 * Titles are message keys, not text -- `bandLines()` below resolves them through the caller's own
 * `t` at render time. The 25/75 lines use sentence-case `misc.fearGreed.band.*` keys (byte-distinct
 * from the Title Case `misc.fearGreed.rating.*` words `ratingLabel` uses); `Fear`/`Greed` alone read
 * identically either way, so the 45/55 lines just reuse `rating.fear`/`rating.greed`. */
const BAND_LINE_DEFS: { price: number; key: MessageKey; colorVar: string; fallback: string; emphasis: boolean }[] = [
  { price: 25, key: "misc.fearGreed.band.extremeFear", colorVar: "--down", fallback: "#ff4d6a", emphasis: false },
  { price: 45, key: "misc.fearGreed.rating.fear", colorVar: "--down", fallback: "#ff4d6a", emphasis: true },
  { price: 55, key: "misc.fearGreed.rating.greed", colorVar: "--up", fallback: "#35e28a", emphasis: true },
  { price: 75, key: "misc.fearGreed.band.extremeGreed", colorVar: "--up", fallback: "#35e28a", emphasis: false },
];

function bandLines(t: Translator): { price: number; title: string; colorVar: string; fallback: string; emphasis: boolean }[] {
  return BAND_LINE_DEFS.map((d) => ({ ...d, title: t(d.key) }));
}

/** Colour a rating gets in the crosshair readout — the same red/green split as the band lines. */
const RATING_COLOR: Record<Rating, { colorVar: string; fallback: string }> = {
  "extreme fear": { colorVar: "--down", fallback: "#ff4d6a" },
  fear: { colorVar: "--down", fallback: "#ff4d6a" },
  neutral: { colorVar: "--muted", fallback: "#7d93a1" },
  greed: { colorVar: "--up", fallback: "#35e28a" },
  "extreme greed": { colorVar: "--up", fallback: "#35e28a" },
};

/** Title Case rating words -- local copy of the same lookup `FearGreedGauge.tsx` keeps, per this
 * codebase's one-copy-per-module convention (see e.g. `api/personas.ts`'s own docstring on it). */
const RATING_LABEL_KEYS: Record<Rating, MessageKey> = {
  "extreme fear": "misc.fearGreed.rating.extremeFear",
  fear: "misc.fearGreed.rating.fear",
  neutral: "misc.fearGreed.rating.neutral",
  greed: "misc.fearGreed.rating.greed",
  "extreme greed": "misc.fearGreed.rating.extremeGreed",
};

function ratingLabel(rating: Rating, t: Translator): string {
  return t(RATING_LABEL_KEYS[rating]);
}

function cssVar(name: string, fallback: string): string {
  if (typeof document === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

/**
 * Collapse to one point per date, ascending. `lightweight-charts` asserts its data is strictly
 * ascending and unique by time, but CNN's `fear_and_greed_historical` block is neither: it carries
 * repeated rows for the same calendar day (the old index-plotted sparkline never noticed, since it
 * spaced points by array position, not by date). Left unhandled this throws
 * "data must be asc ordered by time" and takes the whole panel down through the error boundary.
 *
 * Last occurrence wins on a duplicate date — a later row is the fresher reading for that day — and
 * ISO `YYYY-MM-DD` strings sort lexically the same as chronologically, so this is a plain string
 * sort with no local-zone `Date` in sight.
 */
export function normalizeHistory(points: MacroPoint[]): MacroPoint[] {
  const byDate = new Map<string, MacroPoint>();
  for (const p of points) byDate.set(p.date, p);
  return [...byDate.values()].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
}

/** Same null-safety as the other charts here: a null value is a whitespace point that breaks the
 * line rather than bridging the gap, and the raw `"YYYY-MM-DD"` string is fed straight through as a
 * business-day time so the axis label never drifts a day west of Greenwich. */
function buildLinePoints(points: MacroPoint[]): (LineData<Time> | WhitespaceData<Time>)[] {
  return points.map((p) => {
    const time = p.date as Time;
    if (p.value === null || !Number.isFinite(p.value)) return { time };
    return { time, value: p.value };
  });
}

/** A crosshair `time` comes back either as the raw string we supplied or as a `{year,month,day}`
 * business-day object, depending on lightweight-charts' internals. Normalise both back to the
 * `"YYYY-MM-DD"` string `formatObservationDate` expects, without ever building a local-zone `Date`. */
function crosshairDateString(time: unknown): string | null {
  if (typeof time === "string") return time;
  if (time && typeof time === "object" && "year" in time && "month" in time && "day" in time) {
    const t = time as { year: number; month: number; day: number };
    const mm = String(t.month).padStart(2, "0");
    const dd = String(t.day).padStart(2, "0");
    return `${t.year}-${mm}-${dd}`;
  }
  return null;
}

interface Readout {
  date: string | null;
  score: number;
  rating: Rating;
}

export default function FearGreedHistoryChart({ points, height = 200 }: FearGreedHistoryChartProps) {
  const { t } = useT();
  const [range, setRange] = useState<RangeKey>("6M");
  const [readout, setReadout] = useState<Readout | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const normalized = useMemo(() => normalizeHistory(points), [points]);
  const filtered = useMemo(() => filterPointsByRange(normalized, range), [normalized, range]);
  const spanText = useMemo(() => describeSpan(filtered), [filtered]);
  const hasData = useMemo(
    () => filtered.some((p) => p.value !== null && Number.isFinite(p.value)),
    [filtered],
  );
  // Whether the *whole* series has anything, independent of the selected range — decides between the
  // "no history at all" empty state and a live chart whose current tab merely happens to be empty.
  const seriesHasData = useMemo(
    () => points.some((p) => p.value !== null && Number.isFinite(p.value)),
    [points],
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !hasData) return;

    const textColor = cssVar("--muted", "#7d93a1");
    const gridColor = cssVar("--border", "#1c2733");
    const lineColor = cssVar("--accent-2", "#ff4fd8");

    const chart: IChartApi = createChart(container, {
      width: container.clientWidth,
      height,
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
        vertLine: { color: lineColor, labelBackgroundColor: lineColor },
        horzLine: { color: lineColor, labelBackgroundColor: lineColor },
      },
      rightPriceScale: { borderColor: gridColor },
      timeScale: { borderColor: gridColor, timeVisible: false, secondsVisible: false },
    });

    const lineSeries: ISeriesApi<"Line"> = chart.addLineSeries({
      color: lineColor,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      // Pin the visible field to the index's true 0–100 domain, so a mild-greed 64 is drawn as
      // mild greed and not as "near the top of whatever this window happened to reach".
      autoscaleInfoProvider: () => ({
        priceRange: { minValue: 0, maxValue: 100 },
      }),
      priceFormat: {
        type: "custom",
        formatter: (price: number) => `${Math.round(price)}`,
        minMove: 1,
      },
    });
    lineSeries.setData(buildLinePoints(filtered));

    for (const band of bandLines(t)) {
      lineSeries.createPriceLine({
        price: band.price,
        color: cssVar(band.colorVar, band.fallback),
        lineWidth: 1,
        lineStyle: band.emphasis ? LineStyle.Dashed : LineStyle.Dotted,
        axisLabelVisible: true,
        title: band.title,
      });
    }

    chart.timeScale().fitContent();

    const onMove = (param: Parameters<Parameters<IChartApi["subscribeCrosshairMove"]>[0]>[0]) => {
      const raw = param.seriesData.get(lineSeries) as LineData<Time> | undefined;
      const value = raw && "value" in raw ? raw.value : undefined;
      if (param.time === undefined || value === undefined || !Number.isFinite(value)) {
        setReadout(null);
        return;
      }
      setReadout({ date: crosshairDateString(param.time), score: value, rating: ratingFor(value) });
    };
    chart.subscribeCrosshairMove(onMove);

    const resizeObserver = new ResizeObserver(() => {
      chart.resize(container.clientWidth, height);
    });
    resizeObserver.observe(container);

    return () => {
      chart.unsubscribeCrosshairMove(onMove);
      resizeObserver.disconnect();
      chart.remove();
      setReadout(null);
    };
  }, [filtered, hasData, height, t]);

  if (!seriesHasData) {
    return (
      <div className="fg-chart">
        <div className="fg-chart-empty">{t("misc.fearGreed.history.noHistory")}</div>
      </div>
    );
  }

  return (
    <div className="fg-chart">
      <div className="fg-chart-head">
        <span className="fg-chart-readout" aria-live="polite">
          {readout ? (
            <>
              <span className="fg-chart-readout-date">{formatObservationDate(readout.date)}</span>
              <span className="fg-chart-readout-score">{Math.round(readout.score)}</span>
              <span
                className="fg-chart-readout-band"
                style={{
                  color: cssVar(
                    RATING_COLOR[readout.rating].colorVar,
                    RATING_COLOR[readout.rating].fallback,
                  ),
                }}
              >
                {ratingLabel(readout.rating, t)}
              </span>
            </>
          ) : (
            <span className="fg-chart-readout-date">{t("misc.fearGreed.history.hoverPrompt")}</span>
          )}
        </span>
        <span className="fg-chart-span">{spanText}</span>
      </div>

      <div className="timeframe-tabs" role="tablist" aria-label={t("misc.fearGreed.history.rangeAriaLabel")}>
        {RANGES.map((r) => (
          <button
            key={r}
            type="button"
            role="tab"
            aria-selected={r === range}
            className={`timeframe-tab${r === range ? " active" : ""}`}
            onClick={() => setRange(r)}
          >
            {r}
          </button>
        ))}
      </div>

      {hasData ? (
        <div
          ref={containerRef}
          className="fg-chart-plot"
          style={{ height }}
          role="img"
          aria-label={t("misc.fearGreed.history.chartAriaLabel", { span: spanText })}
        />
      ) : (
        <div className="fg-chart-empty">{t("misc.fearGreed.history.noObservationsInRange")}</div>
      )}

      <div className="fg-chart-legend" aria-hidden="true">
        {bandLines(t).map((b) => (
          <span key={b.price} className="fg-chart-legend-item">
            <span
              className="fg-chart-legend-swatch"
              style={{ background: cssVar(b.colorVar, b.fallback) }}
            />
            {b.title} ≥ {b.price}
          </span>
        ))}
      </div>
    </div>
  );
}

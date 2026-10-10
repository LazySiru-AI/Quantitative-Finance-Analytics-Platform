/**
 * Interactive, range-selectable chart for one macro series -- the expanded view a tile opens
 * into. Fetches the full history once via `macroApi.series`, then every range tab (`1M`..`MAX`)
 * slices that same array client-side rather than refetching, per the endpoint contract (it always
 * returns the full history in one call).
 *
 * The complaint this exists to fix is "I can't tell what span a line covers." So the resolved
 * span -- the *actual* first/last observation date of whatever is currently plotted, not just the
 * tab name -- is always rendered next to the chart. A series with six months of history and the
 * `5Y` tab selected must say "six months," not silently imply five years.
 *
 * Correctness rules carried over from `frontend/src/api/macro.ts` and `Chart.tsx`:
 * - `MacroPoint.date` is a date, not a timestamp -- never round-tripped through a local-zone
 *   `Date`. Rendered via `formatObservationDate`; fed to the chart as the raw `"YYYY-MM-DD"`
 *   string, which is what lightweight-charts wants for a daily business-day axis (see
 *   `Chart.tsx`'s `toTime`).
 * - `null` is unknown, never zero. A null point becomes a whitespace point (`{ time }`, no
 *   `value`), which breaks the line instead of bridging or flooring it.
 * - A flat series (every known value identical) must not divide by zero -- lightweight-charts
 *   handles its own y-scale, so this only matters for the client-side change calculation, which
 *   guards divide-by-zero explicitly.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { ColorType, createChart } from "lightweight-charts";
import type { IChartApi, LineData, Time, WhitespaceData } from "lightweight-charts";

import { ApiRequestError } from "@/api/client";
import type { ChangeMode, MacroPoint, MacroSeries, MacroSource, MacroUnit } from "@/api/macro";
import { formatChange, formatObservationDate, formatValue, macroApi } from "@/api/macro";
import { t, useT, type MessageKey } from "@/i18n";
import { resolveVocab } from "@/i18n/messages/serverVocab";

import "./MacroSeriesChart.css";

export type RangeKey = "1M" | "3M" | "6M" | "1Y" | "5Y" | "MAX";

export interface MacroSeriesChartProps {
  /** Macro series id the backend can serve: "DGS10", "DCOILWTICO", "DX-Y.NYB", "BTC-USD". */
  seriesId: string;
  /** Display name for the chart heading and the accessible label. */
  title: string;
  unit: MacroUnit;
  /** Pixel height of the plot area. Default 220. */
  height?: number;
  /** Initial range tab. Default "1Y". */
  initialRange?: RangeKey;
  /** Compact chrome for a small tile: smaller range tabs, tighter axes. Default false. */
  compact?: boolean;
}

type Phase = "loading" | "notfound" | "error" | "empty" | "loaded";

const RANGES: RangeKey[] = ["1M", "3M", "6M", "1Y", "5Y", "MAX"];

const RANGE_MONTHS: Record<Exclude<RangeKey, "MAX">, number> = {
  "1M": 1,
  "3M": 3,
  "6M": 6,
  "1Y": 12,
  "5Y": 60,
};

/** `yahoo` stands in for an official series and is worth flagging as a proxy, not hiding. */
const SOURCE_LABEL_KEY: Record<MacroSource, MessageKey> = {
  fred: "macro.source.fred",
  yahoo: "macro.source.yahoo",
  cnn: "macro.source.cnn",
  computed: "macro.source.computed",
  store: "macro.source.store",
};

/** `"YYYY-MM-DD"` minus `months` calendar months, staying in UTC throughout so it never drifts
 * across the local-zone boundary the rest of this module is careful to avoid. */
function shiftMonthsBack(dateStr: string, months: number): string {
  const [y, m, d] = dateStr.split("-").map(Number);
  if (!y || !m || !d) return dateStr;
  const dt = new Date(Date.UTC(y, m - 1 - months, d));
  const yy = dt.getUTCFullYear();
  const mm = String(dt.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(dt.getUTCDate()).padStart(2, "0");
  return `${yy}-${mm}-${dd}`;
}

/**
 * Slice the full history to one range tab, anchored on the *series'* last observation rather than
 * on today's wall-clock date -- a backend running a day behind must not make every tab look one
 * day short. `MAX` returns the array unchanged. ISO date strings sort lexically the same as
 * chronologically, so this is a plain string comparison.
 */
export function filterPointsByRange(points: MacroPoint[], range: RangeKey): MacroPoint[] {
  if (range === "MAX" || points.length === 0) return points;
  const lastPoint = points[points.length - 1];
  if (!lastPoint) return points;
  const cutoff = shiftMonthsBack(lastPoint.date, RANGE_MONTHS[range]);
  return points.filter((p) => p.date >= cutoff);
}

/**
 * The headline span text: the actual first/last date of what is plotted, plus how many real
 * observations (non-null values) that covers. Never just echoes the tab name -- a `5Y` tab over a
 * six-month-old series must read as six months.
 */
export function describeSpan(points: MacroPoint[]): string {
  if (points.length === 0) return t("macro.series.noData");
  const known = points.filter((p) => p.value !== null && Number.isFinite(p.value));
  if (known.length === 0) return t("macro.series.noData");
  const first = points[0]?.date;
  const last = points[points.length - 1]?.date;
  const countLabel = t(
    known.length === 1 ? "macro.series.observationCount_one" : "macro.series.observationCount_other",
    { count: known.length },
  );
  if (!first || !last || first === last) {
    return t("macro.series.spanSingleDate", { date: formatObservationDate(first ?? null), count: countLabel });
  }
  return t("macro.series.spanDateRange", {
    start: formatObservationDate(first),
    end: formatObservationDate(last),
    count: countLabel,
  });
}

/**
 * Change across whatever is currently plotted, from the first to the last known (non-null) value
 * in `points`. Unit decides the mode, matching the rest of this codebase's convention
 * (`SeriesChange.mode` on the snapshot tiles): a percent/percent_spread series moves in basis
 * points, a usd/index series moves in percent. Reuses `formatChange` for rendering -- this only
 * computes the number and picks the mode.
 */
export function computeRangeChange(
  points: MacroPoint[],
  unit: MacroUnit,
): { value: number | null; mode: ChangeMode } {
  const mode: ChangeMode = unit === "percent" || unit === "percent_spread" ? "basis_points" : "percent";
  const known = points.filter(
    (p): p is MacroPoint & { value: number } => p.value !== null && Number.isFinite(p.value),
  );
  if (known.length < 2) return { value: null, mode };
  const first = known[0]?.value;
  const last = known[known.length - 1]?.value;
  if (first === undefined || last === undefined) return { value: null, mode };
  if (mode === "basis_points") {
    // 1 percentage point = 100 basis points; the stored value is already in percentage units
    // (e.g. 4.10 for 4.10%), so the raw delta times 100 is the basis-point move.
    return { value: (last - first) * 100, mode };
  }
  if (first === 0) return { value: null, mode }; // avoid a divide-by-zero on a flat-at-zero series
  return { value: ((last - first) / Math.abs(first)) * 100, mode };
}

/** Human label for the change line, e.g. "+42 bp over 1Y" / "-3.10% over max history". */
function rangeChangeLabel(range: RangeKey, value: number | null, mode: ChangeMode): string {
  const suffix = range === "MAX" ? t("macro.series.maxHistory") : range;
  return t("macro.series.changeOverRange", { change: formatChange(value, mode), range: suffix });
}

function cssVar(name: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

/** `--accent` is a theme custom property and is not guaranteed to resolve to a 6-digit hex (a
 * themer could set `rgb(...)`, a name, `oklch(...)`, etc.). Appending an alpha suffix to anything
 * else produces an invalid colour string lightweight-charts will silently fail to apply, so only
 * known-safe hex gets the translucent fill; everything else falls back to fully transparent. */
function translucent(color: string, alphaHex: string): string {
  return /^#[0-9a-fA-F]{6}$/.test(color) ? `${color}${alphaHex}` : "transparent";
}

/** Same null-safety as `Chart.tsx`'s `buildLinePoints`: a null value becomes a whitespace point
 * (`{ time }`, no `value`), breaking the line rather than bridging across the gap or floor-ing it
 * at zero. Dates are daily, so the raw `"YYYY-MM-DD"` string is what lightweight-charts wants --
 * feeding UTC seconds instead would put the axis label a day off west of Greenwich. */
function buildAreaPoints(points: MacroPoint[]): (LineData<Time> | WhitespaceData<Time>)[] {
  return points.map((p) => {
    const time = p.date as Time;
    if (p.value === null || !Number.isFinite(p.value)) return { time };
    return { time, value: p.value };
  });
}

export default function MacroSeriesChart({
  seriesId,
  title,
  unit,
  height = 220,
  initialRange = "1Y",
  compact = false,
}: MacroSeriesChartProps) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [message, setMessage] = useState<string | null>(null);
  const [series, setSeries] = useState<MacroSeries | null>(null);
  const [range, setRange] = useState<RangeKey>(initialRange);
  const { t: tt } = useT();

  // The heading, the range tabs' aria-label and three placeholder lines all name this series. The
  // caller passes the name it had on the tile it was opened from; `seriesId` is the stable FRED id
  // (`DGS10`, `T10Y2Y`), so a chart mounted anywhere -- including outside the macro tile grid --
  // resolves the same translated name from that id. An id this build does not know keeps the
  // caller's `title` verbatim; the wire's own `series.title` is the bare id and is never shown.
  const seriesTitle = resolveVocab(tt, `serverVocab.fred.${seriesId}.title`, title);

  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    setPhase("loading");
    setMessage(null);
    setSeries(null);
    macroApi
      .series(seriesId)
      .then((s) => {
        if (cancelled) return;
        setSeries(s);
        const hasData = s.points.some((p) => p.value !== null && Number.isFinite(p.value));
        setPhase(hasData ? "loaded" : "empty");
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        if (e instanceof ApiRequestError && e.status === 404) {
          setPhase("notfound");
          setMessage(t("macro.series.notFound", { id: seriesId }));
          return;
        }
        const text = e instanceof Error ? e.message : String(e);
        setPhase("error");
        setMessage(text || t("macro.series.loadFailed"));
      });
    return () => {
      cancelled = true;
    };
  }, [seriesId]);

  const filteredPoints = useMemo(
    () => (series ? filterPointsByRange(series.points, range) : []),
    [series, range],
  );

  const latestPoint = useMemo(() => {
    if (!series) return null;
    for (let i = series.points.length - 1; i >= 0; i--) {
      const p = series.points[i];
      if (p && p.value !== null && Number.isFinite(p.value)) return p;
    }
    return null;
  }, [series]);

  const rangeChange = useMemo(() => computeRangeChange(filteredPoints, unit), [filteredPoints, unit]);
  const spanText = useMemo(() => describeSpan(filteredPoints), [filteredPoints]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || phase !== "loaded") return;

    const textColor = cssVar("--muted", "#7c93a0");
    const gridColor = cssVar("--border", "#1b2530");
    const borderColor = cssVar("--border", "#1b2530");
    const accentColor = cssVar("--accent", "#39f2d0");

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
        vertLine: { color: accentColor, labelBackgroundColor: accentColor },
        horzLine: { color: accentColor, labelBackgroundColor: accentColor },
      },
      rightPriceScale: { borderColor },
      timeScale: { borderColor, timeVisible: false, secondsVisible: false },
    });

    const areaSeries = chart.addAreaSeries({
      lineColor: accentColor,
      topColor: translucent(accentColor, "33"),
      bottomColor: translucent(accentColor, "00"),
      lineWidth: compact ? 1 : 2,
      priceFormat: {
        type: "custom",
        formatter: (price: number) => formatValue(price, unit),
        minMove: 0.01,
      },
    });
    areaSeries.setData(buildAreaPoints(filteredPoints));
    chart.timeScale().fitContent();

    const resizeObserver = new ResizeObserver(() => {
      chart.resize(container.clientWidth, height);
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
    };
  }, [filteredPoints, height, compact, unit, phase]);

  const warnings = series?.warnings ?? [];

  return (
    <div className={`macro-chart${compact ? " macro-chart-compact" : ""}`} data-series={seriesId}>
      <div className="macro-chart-head">
        <div className="macro-chart-titlerow">
          <span className="macro-chart-title">{seriesTitle}</span>
          {series && (
            <span className={`macro-tile-source src-${series.source}`}>
              {tt(SOURCE_LABEL_KEY[series.source])}
            </span>
          )}
        </div>

        {phase === "loaded" && (
          <>
            <div className="macro-chart-value">
              {formatValue(latestPoint?.value ?? null, unit)}
              <span className="macro-chart-asof">
                {tt("macro.series.asOf", { date: formatObservationDate(latestPoint?.date ?? null) })}
              </span>
            </div>
            <div className="macro-chart-change">{rangeChangeLabel(range, rangeChange.value, rangeChange.mode)}</div>
            <div className="macro-chart-span">{spanText}</div>
          </>
        )}
      </div>

      <div className="timeframe-tabs" role="tablist" aria-label={tt("macro.series.rangeAriaLabel", { title: seriesTitle })}>
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

      {phase === "loading" && <div className="placeholder">{tt("macro.series.loadingTitle", { title: seriesTitle })}</div>}
      {phase === "notfound" && <div className="placeholder">{message}</div>}
      {phase === "error" && (
        <div className="placeholder">{tt("macro.series.loadError", { title: seriesTitle, message: message ?? "" })}</div>
      )}
      {phase === "empty" && <div className="placeholder">{tt("macro.series.noObservations", { title: seriesTitle })}</div>}

      {/* The plot is a canvas drawn by lightweight-charts; role="img" names it for assistive tech and
          hides the canvas internals (A11Y-09, 2026-09-10 audit). The numeric readout beside it is
          the accessible alternative, so the label only needs to say what the picture is. */}
      {phase === "loaded" && (
        <div
          ref={containerRef}
          className="chart-container macro-chart-plot"
          style={{ height }}
          role="img"
          aria-label={tt("macro.series.chartAriaLabel", { title: seriesTitle, span: spanText })}
        />
      )}

      {warnings.length > 0 && (
        <ul className="macro-tile-warnings warning-list">
          {warnings.map((w, i) => (
            <li key={`${w.kind}-${i}`}>
              <span className="kind">{w.kind}</span> {w.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

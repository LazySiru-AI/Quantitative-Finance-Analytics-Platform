/**
 * One macro/mover tile: label, headline value, the four horizon changes, a sparkline, and
 * provenance.
 *
 * Deliberately dumb about numbers: `valueText` arrives pre-formatted from the caller via
 * `formatValue` / `formatPrice`, and every horizon change is routed through `formatChange(value,
 * change.mode)` right here so a caller cannot forget it and render a basis-point yield move with a
 * `%` suffix. The one judgement call this component makes is colour: `tone="signed"` applies the
 * conventional up=green/down=red treatment (for the movers grid, where it means price direction);
 * `tone="neutral"` never colours a change, because an "up" yield or spread is not a P&L gain.
 *
 * **Optional expandable chart.** When the caller passes `seriesId` (and `chartUnit`), the tile
 * grows a disclosure control that reveals a full `MacroSeriesChart` for that series -- this is how
 * the Rates and Oil tiles in `Macro.tsx` get a real interactive chart instead of just a sparkline.
 * The chart component is intentionally *not* mounted until the reader opens the disclosure: it
 * fetches its own history on mount (`macroApi.series`), and this same `MacroTile` also renders the
 * 20-odd Movers grid tiles, none of which pass `seriesId`. If the chart mounted eagerly whenever the
 * prop was present, that would be fine today (movers omit it), but it would only take one future
 * caller wiring a mover's `seriesId` to turn "reader opens one chart" into "20 history requests
 * fired on every page load." Rendering nothing at all pre-expansion (not a hidden/`display:none`
 * chart) is what keeps that failure mode structurally impossible rather than just currently avoided.
 */
import { useId, useState } from "react";

import type { ChangeMode, MacroPoint, MacroSource, MacroUnit, MarketWarning, SeriesChange } from "@/api/macro";
import { formatChange, formatObservationDate } from "@/api/macro";
import MacroSeriesChart from "@/components/MacroSeriesChart";
import Sparkline from "@/components/Sparkline";
import { t, useT, type MessageKey } from "@/i18n";

import "./MacroSeriesChart.css";
import "./MacroTileChart.css";

export type TileTone = "neutral" | "signed";

export interface MacroTileProps {
  /** Stable identity for the list key at the call site (`tile.key` / `mover.symbol`). */
  tileKey: string;
  label: string;
  /** Pre-formatted headline value -- `formatValue(tile.value, tile.unit)` or `formatPrice(...)`. */
  valueText: string;
  change: SeriesChange;
  /** Oldest first, `null` values are breaks in the line. Passed straight to `Sparkline`. */
  spark: MacroPoint[];
  asOf: string | null;
  source: MacroSource;
  warnings: MarketWarning[];
  tone: TileTone;
  /** Macro series id (`"DGS10"`, `"DCOILBRENTEU"`, ...) for an optional expandable chart. Omitted
   * by the Movers grid, which keeps rendering exactly as before -- only Rates/Oil tiles set this.
   * Typed `| undefined` (not just `?`) because the caller looks this up in a `Record<string, string>`
   * by tile key, which itself yields `string | undefined` under `exactOptionalPropertyTypes`. */
  seriesId?: string | undefined;
  /** Unit for the chart's axis/crosshair formatting. Required alongside `seriesId`; ignored if
   * `seriesId` is absent. */
  chartUnit?: MacroUnit | undefined;
}

const SOURCE_LABEL_KEY: Record<MacroSource, MessageKey> = {
  fred: "macro.source.fred",
  yahoo: "macro.source.yahoo",
  cnn: "macro.source.cnn",
  computed: "macro.source.computed",
  store: "macro.source.store",
};

const HORIZONS: { key: "day" | "week" | "month" | "ytd"; label: string }[] = [
  { key: "day", label: "1D" },
  { key: "week", label: "1W" },
  { key: "month", label: "1M" },
  { key: "ytd", label: "YTD" },
];

export default function MacroTile({
  tileKey,
  label,
  valueText,
  change,
  spark,
  asOf,
  source,
  warnings,
  tone,
  seriesId,
  chartUnit,
}: MacroTileProps) {
  const [chartOpen, setChartOpen] = useState(false);
  const chartPanelId = useId();
  const { t: tt } = useT();

  return (
    <div className="macro-tile panel" data-tile={tileKey} data-tone={tone}>
      <div className="macro-tile-head">
        <span className="macro-tile-label">{label}</span>
        <span className={`macro-tile-source src-${source}`}>{tt(SOURCE_LABEL_KEY[source])}</span>
      </div>

      <div className="macro-tile-value">{valueText}</div>

      <div className="macro-tile-changes">
        {HORIZONS.map((h) => (
          <ChangeStat key={h.key} label={h.label} value={change[h.key]} mode={change.mode} tone={tone} />
        ))}
      </div>

      <Sparkline
        points={spark}
        label={tt("macro.tile.sparklineLabel", { label })}
        stroke={tone === "signed" ? signedStroke(change.day) : "var(--accent)"}
        height={36}
        width={150}
      />
      <div className="macro-tile-span">{describeSparkSpan(spark)}</div>

      <div className="macro-tile-foot">{tt("macro.asOf", { date: formatObservationDate(asOf) })}</div>

      {seriesId && chartUnit && (
        <div className="macro-tile-chart-disclosure">
          <button
            type="button"
            className="macro-tile-chart-toggle"
            aria-expanded={chartOpen}
            aria-controls={chartPanelId}
            onClick={() => setChartOpen((open) => !open)}
          >
            {chartOpen ? tt("macro.tile.hideChart") : tt("macro.tile.showChart")}
          </button>

          {/* Mounted only while open -- see the module docstring for why this must stay lazy
              rather than rendering hidden behind CSS. `MacroSeriesChart` fetches on mount. */}
          {chartOpen && (
            <div id={chartPanelId} className="macro-tile-chart-panel">
              <MacroSeriesChart seriesId={seriesId} title={label} unit={chartUnit} compact height={180} />
            </div>
          )}
        </div>
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

/** Only the movers grid gets a directional colour, and only on the sparkline's own 1D move. */
function signedStroke(day: number | null): string {
  if (day === null || day === 0) return "var(--muted)";
  return day > 0 ? "var(--up)" : "var(--down)";
}

/**
 * The direct fix for "is this a day or a year?" -- a caption under the sparkline stating its
 * actual span, derived from the first and last *non-null* point rather than a hard-coded window
 * length (the caller's fetch window can change without this drifting out of sync).
 *
 * Degenerate cases: an empty or all-null `spark` has no known dates to report, so it reads "no
 * data" rather than a blank line; a single known point has no span to speak of, so it reports just
 * that one date instead of a nonsensical "0 days".
 */
export function describeSparkSpan(spark: MacroPoint[]): string {
  const known = spark.filter(
    (p): p is MacroPoint & { value: number } => p.value !== null && Number.isFinite(p.value),
  );
  if (known.length === 0) return t("macro.tile.sparkNoData");
  const first = known[0];
  const last = known[known.length - 1];
  if (!first || !last) return t("macro.tile.sparkNoData");
  if (known.length === 1) return formatObservationDate(first.date);
  const days = daysBetween(first.date, last.date);
  const dayLabel = t(days === 1 ? "macro.tile.sparkDays_one" : "macro.tile.sparkDays_other", { count: days });
  return t("macro.tile.sparkSpan", {
    dayLabel,
    start: formatObservationDate(first.date),
    end: formatObservationDate(last.date),
  });
}

/** Calendar days between two `"YYYY-MM-DD"` dates, computed in UTC throughout -- same rule as the
 * rest of this module: never round-trip a macro date through a local-zone `Date`. */
function daysBetween(a: string, b: string): number {
  const [ay, am, ad] = a.split("-").map(Number);
  const [by, bm, bd] = b.split("-").map(Number);
  if (!ay || !am || !ad || !by || !bm || !bd) return 0;
  const start = Date.UTC(ay, am - 1, ad);
  const end = Date.UTC(by, bm - 1, bd);
  return Math.round((end - start) / 86400000);
}

function ChangeStat({
  label,
  value,
  mode,
  tone,
}: {
  label: string;
  value: number | null;
  mode: ChangeMode;
  tone: TileTone;
}) {
  const text = formatChange(value, mode);
  const cls = tone === "signed" && value !== null ? (value > 0 ? "pos" : value < 0 ? "neg" : "") : "";
  return (
    <div className="macro-change-stat">
      <span className="macro-change-label">{label}</span>
      <span className={`macro-change-value${cls ? ` ${cls}` : ""}`}>{text}</span>
    </div>
  );
}

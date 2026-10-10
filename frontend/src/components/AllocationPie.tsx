/**
 * Reusable donut chart for a portfolio allocation, toggled between "by ticker" and "by sector".
 *
 * Donut geometry, palette approach and legend structure follow `HoldingsPieChart.tsx` -- read that
 * file first. One circle per slice, swept via `strokeDasharray`/`strokeDashoffset`, wrapped in a
 * `rotate(-90)` group so the sweep starts at 12 o'clock; the same `SLICE_COLORS` approach (design
 * tokens first, then a fixed numbered set) with one muted colour reserved for the "Other" aggregate.
 *
 * **The one deliberate difference from `HoldingsPieChart`: this chart IS renormalised.**
 * `HoldingsPieChart` never renormalises, because a 13F's `weight` is a share of one filing's
 * US-listed-equities slice, and stretching that to fill the circle would misstate a partial book as
 * a whole one. `AllocationPie` has no such partial-book problem -- the caller already decided what
 * counts as "the portfolio" (all tickers, or all sectors) and passes exactly those slices, so their
 * sum IS the total by construction. Each slice's sweep and legend percent is therefore its own
 * `value` as a share of the SUM OF THE SLICES PASSED IN, not of some larger, unstated whole. Do not
 * "fix" this to match `HoldingsPieChart`'s no-renormalisation rule, and do not "fix"
 * `HoldingsPieChart` to renormalise -- they answer different questions about different kinds of
 * data.
 */
import { decimalStringToCents, type DecimalString } from "@/api/client";
import { compareMoneyDesc, formatMoney, sumMoney } from "@/api/portfolio";
import { type Translator, useT } from "@/i18n";

import "./AllocationPie.css";

export interface AllocationSlice {
  /** Stable react key. */
  key: string;
  /** Ticker symbol, or sector name. */
  label: string;
  /** Sector label; equals `label` in sector mode. */
  sector: string;
  /** Dollars, non-negative. */
  value: DecimalString;
  /** `null` for the aggregate "Other" slice and for cash slices. */
  ticker: string | null;
}

export type AllocationMode = "ticker" | "sector";

export interface AllocationPieProps {
  /** Caller supplies slices ALREADY in the current mode. */
  slices: AllocationSlice[];
  mode: AllocationMode;
  onModeChange: (mode: AllocationMode) => void;
  title: string;
  /** How many slices before the tail is folded into one "Other" slice. Default 12. */
  topN?: number;
  footnote?: string;
  /** Called with the ticker when a slice with a resolved ticker is activated. */
  onSelectTicker?: (ticker: string) => void;
}

/**
 * Categorical palette for real slices -- design tokens first (matching the rest of the app's
 * accent/warn/up/down vocabulary), then a fixed, distinguishable numbered set defined in
 * `AllocationPie.css`. Deliberately its own constant rather than importing `HoldingsPieChart`'s
 * `SLICE_COLORS` or `InstitutionsPanels.css`'s numbered custom properties: this component must not
 * depend on the Institutions page having loaded its CSS first.
 */
const SLICE_COLORS = [
  "var(--accent)",
  "var(--accent-2)",
  "var(--warn)",
  "var(--up)",
  "var(--down)",
  "var(--alloc-pie-color-6)",
  "var(--alloc-pie-color-7)",
  "var(--alloc-pie-color-8)",
  "var(--alloc-pie-color-9)",
  "var(--alloc-pie-color-10)",
] as const;

/** The "Other" slice always gets this fixed, muted colour rather than cycling the palette above --
 *  it is an aggregate bucket, not a holding, and should read as "the rest" rather than compete for a
 *  vivid colour slot next to real positions. */
const OTHER_COLOR = "var(--muted)";

interface RenderSlice {
  key: string;
  label: string;
  sector: string;
  value: DecimalString;
  ticker: string | null;
  color: string;
}

const RADIUS = 70;
const STROKE = 30;
const CENTER = 100;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/**
 * The one deliberate string -> float conversion in this file, confined to slice geometry AND the
 * percent label next to it (the same fraction drives both, so there is exactly one conversion site
 * rather than two that could disagree). Mirrors `weightToFraction` in `HoldingsPieChart.tsx`: every
 * *displayed* dollar figure goes through `formatMoney` on the original `DecimalString`, and every
 * *ordering* decision goes through `compareMoneyDesc`'s exact `BigInt` comparison -- neither touches
 * this function. This exists only to answer "how many degrees of arc, and what percent label", where
 * the output is a pixel position and a rounded-to-one-decimal label, not a figure a reader would
 * expect to reconcile against the dollar totals to the cent. A portfolio's dollar total is never
 * large or precise enough for a double's ~15-17 significant digits to lose anything that would move
 * a slice boundary or a percent label by a visible amount.
 */
function valueToFraction(value: DecimalString, total: DecimalString): number {
  const t = Number(total);
  if (!Number.isFinite(t) || t <= 0) return 0;
  const v = Number(value);
  if (!Number.isFinite(v) || v <= 0) return 0;
  return v / t;
}

function formatPercent(fraction: number): string {
  return `${(fraction * 100).toFixed(1)}%`;
}

function ModeToggle({
  mode,
  onModeChange,
  t,
}: {
  mode: AllocationMode;
  onModeChange: (mode: AllocationMode) => void;
  t: Translator;
}) {
  return (
    <div className="view-tabs alloc-pie-toggle" role="tablist" aria-label={t("misc.alloc.modeAriaLabel")}>
      <button
        type="button"
        role="tab"
        aria-selected={mode === "ticker"}
        className={`timeframe-tab${mode === "ticker" ? " active" : ""}`}
        onClick={() => onModeChange("ticker")}
      >
        {t("misc.alloc.modeTicker")}
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={mode === "sector"}
        className={`timeframe-tab${mode === "sector" ? " active" : ""}`}
        onClick={() => onModeChange("sector")}
      >
        {t("misc.alloc.modeSector")}
      </button>
    </div>
  );
}

export default function AllocationPie({
  slices,
  mode,
  onModeChange,
  title,
  topN = 12,
  footnote,
  onSelectTicker,
}: AllocationPieProps) {
  const { t } = useT();

  // The exact sum of every slice's own value -- the renormalisation total. Computed via `sumMoney`
  // (exact integer cents), never `Number()`-summed, so a zero/negative check below never misreads
  // float drift as a real total.
  const total = sumMoney(slices.map((s) => s.value));
  const isEmpty = slices.length === 0 || decimalStringToCents(total) <= 0n;

  if (isEmpty) {
    return (
      <section className="panel alloc-pie-panel">
        <div className="alloc-pie-head">
          <h2 className="alloc-pie-title">{title}</h2>
          <ModeToggle mode={mode} onModeChange={onModeChange} t={t} />
        </div>
        <div className="placeholder">{t("misc.alloc.empty")}</div>
        {footnote && <p className="muted alloc-pie-footnote">{footnote}</p>}
      </section>
    );
  }

  // Sorted descending by exact-decimal comparison -- never a float comparison of dollar strings.
  const sorted = [...slices].sort((a, b) => compareMoneyDesc(a.value, b.value));
  const top = sorted.slice(0, topN);
  const rest = sorted.slice(topN);

  const renderSlices: RenderSlice[] = top.map((s, i) => ({
    key: s.key,
    label: s.label,
    sector: s.sector,
    value: s.value,
    ticker: s.ticker,
    color: SLICE_COLORS[i % SLICE_COLORS.length] ?? SLICE_COLORS[0],
  }));
  if (rest.length > 0) {
    renderSlices.push({
      key: "__other__",
      label: t("misc.alloc.other"),
      sector: "",
      // The exact sum of what this slice folds in -- not a renormalised share of it.
      value: sumMoney(rest.map((s) => s.value)),
      ticker: null,
      color: OTHER_COLOR,
    });
  }

  let cumulative = 0;
  const arcs = renderSlices.map((slice) => {
    const fraction = valueToFraction(slice.value, total);
    const dash = fraction * CIRCUMFERENCE;
    const gap = Math.max(0, CIRCUMFERENCE - dash);
    const offset = -cumulative * CIRCUMFERENCE;
    cumulative += fraction;
    return { ...slice, dash, gap, offset, fraction };
  });

  return (
    <section className="panel alloc-pie-panel">
      <div className="alloc-pie-head">
        <h2 className="alloc-pie-title">{title}</h2>
        <ModeToggle mode={mode} onModeChange={onModeChange} t={t} />
      </div>
      <div className="alloc-pie-body">
        <svg
          className="alloc-pie-donut"
          viewBox={`0 0 ${CENTER * 2} ${CENTER * 2}`}
          role="img"
          aria-label={t(arcs.length === 1 ? "misc.alloc.donutLabel_one" : "misc.alloc.donutLabel_other", {
            title,
            count: arcs.length,
          })}
        >
          <g transform={`rotate(-90 ${CENTER} ${CENTER})`}>
            <circle cx={CENTER} cy={CENTER} r={RADIUS} fill="none" stroke="var(--border)" strokeWidth={STROKE} />
            {arcs.map((arc) => (
              <circle
                key={arc.key}
                cx={CENTER}
                cy={CENTER}
                r={RADIUS}
                fill="none"
                stroke={arc.color}
                strokeWidth={STROKE}
                strokeDasharray={`${arc.dash} ${arc.gap}`}
                strokeDashoffset={arc.offset}
              />
            ))}
          </g>
        </svg>
        <ul className="alloc-pie-legend">
          {arcs.map((slice) => {
            const percent = formatPercent(slice.fraction);
            const value = formatMoney(slice.value);
            const rowBody = (
              <>
                <span className="alloc-pie-swatch" style={{ background: slice.color }} aria-hidden="true" />
                <span className="alloc-pie-legend-label">{slice.label}</span>
                {mode === "ticker" && slice.sector && (
                  <span className="badge alloc-pie-sector">{slice.sector}</span>
                )}
                <span className="alloc-pie-legend-value">{value}</span>
                <span className="alloc-pie-legend-percent">{percent}</span>
              </>
            );
            const clickable = slice.ticker !== null && onSelectTicker !== undefined;
            return (
              <li key={slice.key} className="alloc-pie-legend-row">
                {clickable ? (
                  <button
                    type="button"
                    className="alloc-pie-legend-btn"
                    onClick={() => onSelectTicker?.(slice.ticker as string)}
                    aria-label={t("misc.alloc.legendButtonLabel", { label: slice.label, value, percent })}
                  >
                    {rowBody}
                  </button>
                ) : (
                  <div className="alloc-pie-legend-static">{rowBody}</div>
                )}
              </li>
            );
          })}
        </ul>
      </div>
      {footnote && <p className="muted alloc-pie-footnote">{footnote}</p>}
    </section>
  );
}

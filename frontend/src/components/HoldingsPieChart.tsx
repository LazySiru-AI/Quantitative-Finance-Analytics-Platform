/**
 * A donut chart of one filer's portfolio by weight.
 *
 * Weights come from `Holding.weight`, and what that means depends on `source` (see `@/api/
 * institutions`'s module docstring): for a 13F it is weight *within the filing's US-listed-equities
 * slice*, not of the manager's whole book -- no bonds, no cash, no foreign listings. For an NPORT-P
 * it is weight of the ETF's *actual whole portfolio* -- an ETF does not file a 13F, and none of the
 * 13F's three exclusions apply to it. A donut is the single easiest chart on this page to misread as
 * "this is the whole portfolio" when it is not, so the caption beneath it states which kind of
 * filing backs the numbers every time it renders, not just on an about page nobody opens -- and
 * says the *opposite* of the 13F caveat for an NPORT fund rather than printing the wrong one.
 *
 * Never renormalised. Each slice's sweep is that holding's own `weight` as a share of a full circle
 * -- not its share of the slices actually drawn. If every holding's `weight` sums to less than one
 * (a real filing can undercount, for reasons this component has no way to diagnose), the circle is
 * left honestly short rather than stretched to fill it; `totalWeight` below is always shown next to
 * the chart so that shortfall is never hidden.
 */
import { compareDecimalStrings, parseDecimalString } from "@/api/client";
import { formatWeight } from "@/api/institutions";
import type { Holding, Source } from "@/api/institutions";
import { useT } from "@/i18n";

import "./InstitutionsPanels.css";

export interface HoldingsPieChartProps {
  holdings: Holding[];
  /** Fund display name, for the accessible label. */
  fundName: string;
  /** Which filing this fund's holdings came from -- 13F or NPORT-P. Selects the caption below: a
   *  13F is a manager's US-listed-equities slice only (no bonds, no cash, no foreign listings), but
   *  an NPORT-P is an ETF's *whole* portfolio, and captioning an NPORT fund with the 13F caveat
   *  states all three exclusions as fact about a filing that carries none of them. See
   *  `SOURCE_NOTE` in `@/api/institutions` for the same distinction `Institutions.tsx` already
   *  makes elsewhere on this page. */
  source: Source;
  /** How many slices before the tail is aggregated into "Other". Default 10. */
  topN?: number;
  /** Called with the ticker when a slice with a resolved ticker is activated. */
  onSelectTicker?: (ticker: string) => void;
}

/**
 * Exact sum of decimal strings via `BigInt`, generalising `sumMoney` (`@/api/portfolio`) from a
 * fixed two-decimal (cents) scale to whatever fractional precision the inputs actually carry --
 * weights arrive with varying decimal lengths, not a fixed currency scale. The only caller is the
 * "Other" slice below, which must show the real sum of the positions it folds in, not a
 * renormalised share of them.
 *
 * Built on `parseDecimalString` (`@/api/client`), which expands scientific notation before this
 * ever sees a digit -- a diffuse book's smallest weights land in "Other", exactly the values most
 * likely to be `Decimal`-serialised in scientific notation in the first place.
 */
function sumDecimalStrings(values: string[]): string {
  if (values.length === 0) return "0";
  const parsed = values.map((v) => parseDecimalString(v));
  const fracLen = Math.max(...parsed.map((p) => p.fracRaw.length));
  let total = 0n;
  for (const p of parsed) {
    const magnitude = BigInt(p.wholeRaw + p.fracRaw.padEnd(fracLen, "0"));
    total += p.negative ? -magnitude : magnitude;
  }
  const negative = total < 0n;
  const digitsStr = (negative ? -total : total).toString().padStart(fracLen + 1, "0");
  const whole = digitsStr.slice(0, digitsStr.length - fracLen) || "0";
  const frac = fracLen > 0 ? digitsStr.slice(digitsStr.length - fracLen) : "";
  return `${negative ? "-" : ""}${whole}${frac ? `.${frac}` : ""}`;
}

/**
 * The one deliberate string -> float conversion in this file, confined to slice geometry.
 *
 * Every *displayed* number in this component is formatted straight from the original
 * `DecimalString` via `formatWeight`, and every *ordering* decision goes through
 * `compareDecimalStrings`'s `BigInt` comparison above -- neither touches this function. This exists
 * only to answer "how many degrees of arc should this slice sweep", where the output is a pixel
 * position on an SVG circle, not a figure a reader reads off directly. A `weight` is a fraction of
 * one filing's US-equities slice: it is never large or precise enough for a double's ~15-17
 * significant digits to lose anything that would move a slice boundary by a visible fraction of a
 * pixel. That is why the conversion is safe here and nowhere else in this file.
 */
function weightToFraction(value: string): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

/**
 * Categorical palette for real slices. Leads with the same design tokens the rest of the app uses
 * for accent/warn/up/down, then extends with a fixed, distinguishable set of custom properties
 * defined in `InstitutionsPanels.css` -- the same house approach `OVERLAY_PALETTE`
 * (`@/components/overlays.ts`) takes to a categorical palette on a near-black ground, read there
 * only, not imported (it is tuned for chart line series, not donut slices, and this component owns
 * its own CSS file rather than reaching into another component's constant).
 */
const SLICE_COLORS = [
  "var(--accent)",
  "var(--accent-2)",
  "var(--warn)",
  "var(--up)",
  "var(--down)",
  "var(--inst-pie-color-6)",
  "var(--inst-pie-color-7)",
  "var(--inst-pie-color-8)",
  "var(--inst-pie-color-9)",
  "var(--inst-pie-color-10)",
] as const;

/** The "Other" slice always gets this fixed, muted colour rather than cycling the palette above --
 *  it is an aggregate bucket, not a holding, and should read as "the rest" rather than compete for
 *  a vivid colour slot next to real positions. */
const OTHER_COLOR = "var(--muted)";

interface Slice {
  key: string;
  label: string;
  weight: string;
  ticker: string | null;
  color: string;
}

const RADIUS = 70;
const STROKE = 30;
const CENTER = 100;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export default function HoldingsPieChart({
  holdings,
  fundName,
  source,
  topN = 10,
  onSelectTicker,
}: HoldingsPieChartProps) {
  const { t } = useT();

  if (holdings.length === 0) {
    return (
      <section className="panel inst-pie-panel">
        <h2 className="inst-pie-title">{t("desk.holdingsPie.title")}</h2>
        <div className="placeholder">{t("desk.holdingsPie.noHoldings", { fundName })}</div>
      </section>
    );
  }

  const sorted = [...holdings].sort((a, b) => compareDecimalStrings(b.weight, a.weight));
  const top = sorted.slice(0, topN);
  const rest = sorted.slice(topN);

  const slices: Slice[] = top.map((h, i) => ({
    key: h.cusip,
    label: h.issuer,
    weight: h.weight,
    ticker: h.ticker,
    color: SLICE_COLORS[i % SLICE_COLORS.length] ?? SLICE_COLORS[0],
  }));
  if (rest.length > 0) {
    slices.push({
      key: "__other__",
      label: t(rest.length === 1 ? "desk.holdingsPie.otherLabel_one" : "desk.holdingsPie.otherLabel_other", {
        count: rest.length,
      }),
      weight: sumDecimalStrings(rest.map((h) => h.weight)),
      ticker: null,
      color: OTHER_COLOR,
    });
  }

  // The real sum of every holding's weight, not just the ones drawn as their own slice -- equal to
  // the sum of all rendered slices (top N plus "Other"), since "Other" is that exact remainder, not
  // a renormalised share of it. Shown honestly even when it falls short of 100%.
  const totalWeight = sumDecimalStrings(holdings.map((h) => h.weight));

  let cumulative = 0;
  const arcs = slices.map((slice) => {
    const fraction = Math.max(0, weightToFraction(slice.weight));
    const dash = fraction * CIRCUMFERENCE;
    const gap = Math.max(0, CIRCUMFERENCE - dash);
    const offset = -cumulative * CIRCUMFERENCE;
    cumulative += fraction;
    return { ...slice, dash, gap, offset };
  });

  return (
    <section className="panel inst-pie-panel">
      <h2 className="inst-pie-title">{t("desk.holdingsPie.title")}</h2>
      <p className="muted inst-pie-caption">
        {source === "13F"
          ? t("desk.holdingsPie.caption13f", { fundName })
          : t("desk.holdingsPie.captionNport", { fundName })}
      </p>
      <div className="inst-pie-body">
        <svg
          className="inst-pie-donut"
          viewBox={`0 0 ${CENTER * 2} ${CENTER * 2}`}
          role="img"
          aria-label={t(slices.length === 1 ? "desk.holdingsPie.donutLabel_one" : "desk.holdingsPie.donutLabel_other", {
            fundName,
            count: slices.length,
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
        <ul className="inst-pie-legend">
          {slices.map((slice) => {
            const rowBody = (
              <>
                <span className="inst-pie-swatch" style={{ background: slice.color }} aria-hidden="true" />
                <span className="inst-pie-legend-label">{slice.label}</span>
                {slice.ticker && <span className="badge inst-pie-ticker">{slice.ticker}</span>}
                <span className="inst-pie-legend-weight">{formatWeight(slice.weight)}</span>
              </>
            );
            return (
              <li key={slice.key} className="inst-pie-legend-row">
                {slice.ticker ? (
                  <button
                    type="button"
                    className="inst-pie-legend-btn"
                    onClick={() => onSelectTicker?.(slice.ticker as string)}
                    aria-label={t("desk.holdingsPie.legendButtonLabel", {
                      label: slice.label,
                      ticker: slice.ticker,
                      weight: formatWeight(slice.weight),
                    })}
                  >
                    {rowBody}
                  </button>
                ) : (
                  <div className="inst-pie-legend-static">{rowBody}</div>
                )}
              </li>
            );
          })}
        </ul>
      </div>
      <p className="muted inst-pie-total">
        {t("desk.holdingsPie.total", { weight: formatWeight(totalWeight) })}
      </p>
    </section>
  );
}

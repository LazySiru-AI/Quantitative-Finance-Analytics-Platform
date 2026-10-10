/**
 * The confidence-interval renderer shared by every persona panel.
 *
 * This is the single most important honesty signal in the persona feature: a hit rate of 0.16 over
 * `n=192` and a hit rate of 1.0 over `n=6` must never read the same. A bare percentage throws away
 * the sample size that tells a reader how much to trust it, so `n` is never optional here -- it is
 * shown every time anything is shown, with the same visual weight as the point value itself.
 *
 * **`null` must never look like a real zero.** A `null` point (not enough data, not yet computed)
 * renders the empty label -- never `0`, never `0%`, never a bare dash that could be misread as a
 * real measurement. This mirrors the same rule `PersonaScorecard.tsx` enforces for `hit_rate` and
 * `median_return_pct`.
 *
 * **Structural typing on purpose.** `StatEstimateLike` is declared locally rather than imported from
 * `@/api/personas` -- that module is being rewritten concurrently elsewhere, and this component only
 * needs the shape, not the identity, of whatever estimate type callers hold.
 *
 * **Return values arrive already scaled to percent, never as fractions** — the backend's
 * `_pct_return` is `(other/entry - 1) * 100`, so a `return_ci`/`excess_ci` point of `4.32` already
 * means 4.32%, exactly like every other `*_pct` field this app renders through `formatReturnPct`
 * (`@/api/personas`). `format="percent"` therefore appends `%` at 2dp and does NOT multiply by 100 —
 * matching that house helper. Rates that genuinely arrive as 0..1 fractions (`hit_rate_ci`, a
 * `proportion`) use `format="rate"` instead, which renders the raw fraction. A previous draft of this
 * component multiplied `percent` by 100 on the mistaken premise that returns were fractions; that
 * would render 4.32% as "432%". `StatValue.test.tsx` pins the corrected convention with a regression
 * case.
 *
 * **Direction glyph, added without touching the value's own text node.** Per
 * `docs/APP-UX-REFACTOR-ANALYSIS.md` §3.3, every money/percent delta gets a ▲/▼ direction glyph
 * alongside its existing sign. `rate` values (`hit_rate_ci`, any 0..1 proportion) are never a delta
 * -- they cannot go negative and "up"/"down" would misrepresent a bare probability -- so the arrow
 * only appears for `percent`/`number`, and only when `point` is genuinely signed (nonzero). The
 * `<Glyph>` is rendered as a sibling *before* the existing `<span>`, not as a child of it: the span
 * that carries `data-testid`/`title`/`aria-label` and the exact rendered `text` is completely
 * unchanged, so every existing byte-for-byte `textContent` assertion in `StatValue.test.tsx` (and
 * every page test that does the same against this component) keeps passing. The glyph is
 * `aria-hidden` (no `label`) because the sign is already in the text and in `aria-label`.
 */
import { Glyph } from "@/components/Glyph";
import { useT } from "@/i18n/useT";

import "./StatValue.css";

/** The shape this component needs from a confidence-interval estimate, independent of whoever
 * defines the "real" type. */
export interface StatEstimateLike {
  n: number;
  point: number | null;
  low: number | null;
  high: number | null;
  /** e.g. 0.90 for a 90% interval. */
  confidence: number;
  method: string;
}

export interface StatValueProps {
  estimate: StatEstimateLike | null | undefined;
  /** How to render `point`/`low`/`high`. Default "percent". */
  format?: "percent" | "rate" | "number" | undefined;
  /** Rendered when `estimate` is null/undefined or `point` is null. */
  emptyLabel?: string | undefined;
  /**
   * Show the ▲/▼ direction glyph beside a signed `percent`/`number` point (§3.3). Defaults to
   * `true`; the glyph never appears for `format="rate"` or a zero point regardless of this prop,
   * since a bare proportion is not a delta. Set `false` to suppress it entirely for a caller that
   * doesn't want it.
   */
  showDirection?: boolean | undefined;
  className?: string | undefined;
  "data-testid"?: string | undefined;
}

function formatMagnitude(value: number, format: "percent" | "rate" | "number"): string {
  // `percent` values are already scaled to percent (see this file's docstring): append the unit at
  // 2dp exactly like `formatReturnPct`, never multiply by 100.
  if (format === "percent") return `${value.toFixed(2)}%`;
  if (format === "rate") return value.toFixed(2);
  return value.toFixed(2);
}

export function StatValue({
  estimate,
  format = "percent",
  emptyLabel,
  showDirection = true,
  className,
  "data-testid": dataTestId,
}: StatValueProps) {
  const { t } = useT();

  const classes = ["stat-value"];
  if (className) classes.push(className);

  if (estimate == null || estimate.point === null) {
    const label = emptyLabel ?? t("personaAtoms.statValue.noData");
    return (
      <span className={[...classes, "stat-value-empty"].join(" ")} data-testid={dataTestId}>
        {label}
      </span>
    );
  }

  const { n, point, low, high, confidence, method } = estimate;
  const pointStr = formatMagnitude(point, format);

  const hasCi = low !== null && high !== null && method !== "none";

  const text = hasCi
    ? t("personaAtoms.statValue.withCi", {
        point: pointStr,
        n,
        confidence: Math.round(confidence * 100),
        // Non-null asserted just above via `hasCi`.
        low: formatMagnitude(low as number, format),
        high: formatMagnitude(high as number, format),
      })
    : t("personaAtoms.statValue.pointOnly", { point: pointStr, n });

  // A `rate` is a 0..1 proportion, never a delta -- no direction glyph regardless of `showDirection`.
  // A zero point has no direction either way. Rendered as a sibling *before* the value span (not a
  // child of it) so the span's own text node -- what every exact `textContent` assertion checks --
  // is byte-for-byte unchanged. See this file's docstring for the full reasoning.
  const direction = showDirection && format !== "rate" && point !== 0 ? (point > 0 ? "up" : "down") : null;

  return (
    <>
      {direction && <Glyph name={direction} className="stat-value-direction" />}
      <span className={classes.join(" ")} title={text} aria-label={text} data-testid={dataTestId}>
        {text}
      </span>
    </>
  );
}

export default StatValue;

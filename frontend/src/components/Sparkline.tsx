/**
 * A minimal inline line sparkline for one macro/mover series.
 *
 * Two correctness rules this exists to enforce, both called out by the macro contract
 * (`frontend/src/api/macro.ts`):
 *
 * - A `null` point is a gap, not a bridge. A point is only ever joined to its neighbour when both
 *   are known values; a `null` always starts a new segment. A bridged one-day holiday would be
 *   invisible and a bridged two-week outage would read as a real, if boring, market.
 * - A flat series -- every known value identical, e.g. an unchanged policy rate -- must not divide
 *   by zero when computing the y-scale. It draws as a flat line through the middle, which is the
 *   correct picture: nothing moved, not "no data."
 *
 * Purely presentational: it takes points and draws them. It does not fetch, does not know about
 * `ChangeMode`, and does not decide colour on its own -- callers pass `stroke` explicitly, which is
 * what keeps the up=green/down=red convention out of tiles (rates, spreads) where that framing does
 * not apply.
 */
import type { MacroPoint } from "@/api/macro";
import { useT } from "@/i18n";

export interface SparklineProps {
  points: MacroPoint[];
  /**
   * Accessible description, e.g. "US 10-year yield, recent history". This is the only description
   * a screen reader gets for the shape of the line, so make it identify the series.
   */
  label: string;
  width?: number;
  height?: number;
  /** CSS colour value for the line and the latest-point marker. Defaults to the neutral accent. */
  stroke?: string;
}

interface Point {
  x: number;
  y: number;
}

const DEFAULT_WIDTH = 140;
const DEFAULT_HEIGHT = 36;
const PAD = 3;

export default function Sparkline({
  points,
  label,
  width = DEFAULT_WIDTH,
  height = DEFAULT_HEIGHT,
  stroke = "var(--accent)",
}: SparklineProps) {
  const { t } = useT();
  const known = points.filter(
    (p): p is MacroPoint & { value: number } => p.value !== null && Number.isFinite(p.value),
  );

  if (points.length === 0 || known.length === 0) {
    return (
      <div className="sparkline sparkline-empty" role="img" aria-label={t("desk.sparkline.noData", { label })}>
        <span aria-hidden="true">—</span>
      </div>
    );
  }

  const min = Math.min(...known.map((p) => p.value));
  const max = Math.max(...known.map((p) => p.value));
  const flat = max === min;
  const n = points.length;
  const innerWidth = width - PAD * 2;
  const innerHeight = height - PAD * 2;
  const xStep = n > 1 ? innerWidth / (n - 1) : 0;

  // Break into segments at every null -- adjacent known points join, a null starts a fresh one.
  const segments: Point[][] = [];
  let current: Point[] = [];

  points.forEach((p, i) => {
    const x = PAD + (n > 1 ? i * xStep : innerWidth / 2);
    if (p.value === null || !Number.isFinite(p.value)) {
      if (current.length > 0) segments.push(current);
      current = [];
      return;
    }
    const y = flat ? height / 2 : PAD + (1 - (p.value - min) / (max - min)) * innerHeight;
    current.push({ x, y });
  });
  if (current.length > 0) segments.push(current);

  // The most recent known point, read back out of the segments rather than tracked in a `let` the
  // forEach callback assigns to. TypeScript's control-flow analysis cannot see an assignment made
  // inside a closure, so the tracked variable stays narrowed to `null` and every use of it is a
  // type error -- the segments already hold the answer, so there is nothing to track.
  const lastSegment = segments[segments.length - 1];
  const lastKnown = lastSegment ? lastSegment[lastSegment.length - 1] : null;

  return (
    <svg
      className="sparkline"
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      height={height}
      preserveAspectRatio="none"
      role="img"
      aria-label={label}
    >
      {segments.map((seg, i) => {
        if (seg.length >= 2) {
          return (
            <polyline
              key={i}
              points={seg.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" ")}
              fill="none"
              stroke={stroke}
              strokeWidth={1.5}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          );
        }
        const only = seg[0];
        if (!only) return null;
        // A single known point stranded between gaps still deserves a mark, not silent omission.
        return <circle key={i} cx={only.x} cy={only.y} r={1.5} fill={stroke} />;
      })}
      {lastKnown && <circle cx={lastKnown.x} cy={lastKnown.y} r={2.25} fill={stroke} />}
    </svg>
  );
}

/**
 * Small reusable label/value grid for summary numbers -- symbol, date range, sample sizes and the
 * like. Wraps the existing `.status-grid`/`.stat` classes from `styles.css` rather than defining new
 * ones; every workbench section uses this for its header metadata instead of hand-rolling a grid.
 */
import type { ReactNode } from "react";

export interface StatGridItem {
  label: string;
  value: ReactNode;
}

export default function StatGrid({ items }: { items: StatGridItem[] }) {
  return (
    <div className="status-grid">
      {items.map((item, i) => (
        <div className="stat" key={`${item.label}-${i}`}>
          <span className="label">{item.label}</span>
          <span className="value">{item.value}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * Single tile for a `.tile-grid` summary row -- label, a value, an optional hint line, and an
 * optional "danger" variant for the border/tint. Shared by `Tax.tsx` and `WashSales.tsx`, whose
 * private `Tile` components were byte-for-byte identical apart from Tax's `formatMoney` call
 * baked into the value. That formatting now happens at each call site instead -- `value` here is
 * already display-ready, so this component (unlike `StatGrid` above) is not itself money-aware.
 *
 * Not folded in with `Portfolio.tsx`'s `MoneyTile`, `Activity.tsx`'s `Tile`, or `PaperDesk.tsx`'s
 * `Stat`: per `Activity.tsx`'s own note on its `Tile`, those pages agree on the CSS contract
 * (`stat tile`/`label`/`value`/`tile-hint`), not on a component, and that reasoning still holds
 * for them.
 */
export function StatTile({
  label,
  value,
  hint,
  variant,
  emphasize,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  variant?: "danger";
  emphasize?: boolean;
}) {
  return (
    <div className={`stat tile${variant ? ` tile-${variant}` : ""}`}>
      <span className="label">{label}</span>
      <span className={`value${emphasize ? " value-emphasize" : ""}`}>{value}</span>
      {hint && <span className="tile-hint">{hint}</span>}
    </div>
  );
}

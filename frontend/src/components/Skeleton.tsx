/**
 * A placeholder shaped like the content that is coming, not the word "Loading…".
 *
 * The alternative this replaces is a single centred spinner or a `<p>Loading…</p>` dropped into a
 * panel that otherwise holds a table or a stat grid: the panel collapses to one line while the
 * fetch is in flight and then snaps open to its real height the instant data lands, which reads as
 * a layout jump rather than progress. Drawing `rows` placeholder blocks in the rough shape of the
 * eventual content (`rows` for a table, `tiles` for a stat grid, `text` for a paragraph) means the
 * panel already occupies close to its final height before the first byte of real data arrives, so
 * the swap is a content change, not a reflow.
 *
 * This is deliberately not a full skeleton-matches-columns system (no per-column widths, no
 * variable row heights) -- that would require every call site to describe its own table shape in
 * detail, which is more ceremony than three variants justify. `variant` picks a silhouette; it does
 * not attempt to mirror the exact layout it stands in for.
 *
 * **Why a live region and not silence.** A spinner with no text is invisible to a screen reader
 * unless something else on the page happens to say "loading" -- and most of this app's panels
 * don't. `role="status"` + `aria-live="polite"` means assistive tech is told once, without
 * interrupting whatever the user was already doing (an `assertive` region would cut off in-progress
 * speech every time a fetch starts, which for a page with several panels loading independently
 * would be constant noise). The same text renders visibly too: sighted users get exactly the same
 * information a screen reader announces, rather than a caption that only exists in the accessibility
 * tree.
 */
import { useT } from "@/i18n/useT";

import "./Skeleton.css";

export interface SkeletonProps {
  /** How many placeholder rows to draw. Default 3. */
  rows?: number | undefined;
  /** What is being loaded, for the accessible live message, e.g. "filers". */
  what?: string | undefined;
  /** Shown when the caller knows how far along it is. */
  progress?: { done: number; total: number } | undefined;
  variant?: "rows" | "tiles" | "text" | undefined;
}

export function Skeleton({ rows = 3, what, progress, variant = "rows" }: SkeletonProps) {
  const { t } = useT();

  const label = what ? t("interaction.skeleton.label", { what }) : t("common.loading");
  const progressText = progress
    ? t("interaction.skeleton.progress", { done: progress.done, total: progress.total })
    : undefined;
  const announced = progressText ? `${label} ${progressText}` : label;

  // A skeleton with zero rows is a contradiction -- something is always being waited for -- so a
  // non-positive count is clamped rather than rendered as an empty, silently useless placeholder.
  const count = Math.max(1, Math.floor(rows));
  const blocks = Array.from({ length: count }, (_unused, index) => index);

  return (
    <div className={`skeleton skeleton-${variant}`}>
      <div className="skeleton-blocks" aria-hidden="true">
        {blocks.map((index) => (
          <div key={index} className="skeleton-block" />
        ))}
      </div>
      <p role="status" aria-live="polite" className="skeleton-status">
        {announced}
      </p>
    </div>
  );
}

export default Skeleton;

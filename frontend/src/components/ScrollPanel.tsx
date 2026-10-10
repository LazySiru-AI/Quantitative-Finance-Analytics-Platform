/**
 * The bounded, scrolling card body this app never had.
 *
 * Before this component, eight places hand-rolled their own `max-height` + `overflow-y`
 * (`comp-leaderboard-scroll`, `comp-gens-scroll`, `comp-job-log`, `comp-gens-plan-text`,
 * `wf-output-md`, `ta-stage-output`, `vibe-output-md`, `event-calendar-scroll`) and everything else
 * grew without limit: the two Persona profile cards measured 9,100px and 19,625px tall on a 720px
 * viewport, and the Paper Desk page ran 5.8 screens before a single desk was expanded. `.table-wrap`
 * (styles.css) only ever set `overflow-x`, so a 1,341-row disposals table pushed the page, not the
 * card.
 *
 * Two exports, because the call sites split cleanly in two:
 *
 *   - `ScrollRegion` -- just the bounded box. Use it when a panel already exists and only *part* of
 *     its content is the long part (a table under a paragraph of context, a list beside a stat
 *     grid). This is the common case.
 *   - `ScrollPanel`  -- a whole `.panel` card whose heading and actions stay fixed above the
 *     scrolling body. Use it when the card *is* the long thing.
 *
 * Conventions this follows, all pre-existing in the codebase:
 *   - The heading and any controls sit OUTSIDE the scroll region, so they never scroll away --
 *     `EventCalendar.css` says this explicitly and it is the behaviour the owner already likes.
 *   - `max-height` is a `clamp()` in `vh`, not a fixed pixel height, so a short viewport is not
 *     handed a card taller than itself (the mistake `EventCalendar.css` documents avoiding).
 *   - Expanding lifts the cap entirely rather than growing it, matching `.event-calendar-panel.expanded`.
 *   - No ARIA is hand-rolled beyond what a scrollable region genuinely needs: `role="region"` plus
 *     an accessible name, and a tab stop so a keyboard user can actually reach and scroll it. A
 *     scrollable box with no tab stop is keyboard-inaccessible content -- which is why `label` is
 *     required. The stop is gated on the region actually overflowing, though: a region whose
 *     content fits does not scroll, and a tab stop that does nothing is just an extra press.
 *
 * ONE scroll region per card. A scroller nested inside another scroller traps the wheel and makes
 * the inner content unreachable on touch; if a card has two long lists, it wants two cards or one
 * region around both.
 */
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { useT } from "@/i18n/useT";

import "./ScrollPanel.css";

/**
 * How tall the region is allowed to get before it scrolls.
 *
 * `sm` -- logs, stage output, "recent activity" lists: things read at a glance, ~8 rows.
 * `md` -- tables and lists (holdings, disposals, fills, runs). The default.
 * `lg` -- profile and dossier cards read top to bottom (Persona profile, candidate dossier).
 */
export type ScrollPanelSize = "sm" | "md" | "lg";

export interface ScrollRegionProps {
  children: React.ReactNode;
  /** Height cap. Defaults to `"md"`. */
  size?: ScrollPanelSize | undefined;
  /**
   * DOM id for the scrolling element, so an expand control elsewhere can point `aria-controls` at
   * the thing it actually expands. `ScrollPanel` wraps its children in an extra `<div>` to carry
   * this instead, for backward compatibility with the markup its call sites already render.
   */
  id?: string | undefined;
  /**
   * Accessible name for the scrollable region. Required: the region becomes a tab stop whenever it
   * can actually scroll, and a tab stop that announces nothing is worse than no tab stop at all.
   */
  label: string;
  /** Lift the cap. Owned by the caller (`ScrollPanel` drives it from its own expand button). */
  expanded?: boolean | undefined;
  /** Extra class on the scrolling element. */
  className?: string | undefined;
  "data-testid"?: string | undefined;
}

/**
 * The bounded box on its own, for embedding in a panel that already exists.
 *
 * The `data-more` attribute drives a bottom fade in CSS: it is `"true"` only while there is content
 * below the fold, so a card that happens to fit, or one scrolled to its end, never shows a fade that
 * lies about there being more. It is measured rather than assumed because "does this overflow?"
 * depends on the data, the viewport and the font, none of which CSS can hand to a gradient.
 */
export function ScrollRegion({
  children,
  size = "md",
  id,
  label,
  expanded = false,
  className,
  "data-testid": dataTestId,
}: ScrollRegionProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [more, setMore] = useState(false);

  const measure = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    // 2px of slack: sub-pixel layout rounding otherwise leaves a scrolled-to-bottom region
    // reporting a stray fraction of a pixel of remaining scroll and the fade never turns off.
    const remaining = el.scrollHeight - el.clientHeight - el.scrollTop;
    setMore(!expanded && remaining > 2);
  }, [expanded]);

  useEffect(() => {
    measure();
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    // Content arrives asynchronously on nearly every page here (a fetch resolves, a `<details>`
    // opens), so a one-shot measurement on mount would be measuring the empty state.
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    for (const child of Array.from(el.children)) observer.observe(child);
    return () => observer.disconnect();
  }, [measure, children]);

  const classes = ["scroll-region", `scroll-region-${size}`];
  if (expanded) classes.push("expanded");
  if (className) classes.push(className);

  return (
    <div
      ref={ref}
      id={id}
      className={classes.join(" ")}
      data-more={more ? "true" : "false"}
      onScroll={measure}
      role="region"
      aria-label={label}
      // A tab stop only where there is something to scroll. This region is used 96 times, and most
      // of those instances hold content that fits -- making every one of them a stop puts dozens of
      // extra presses between a keyboard user and the next real control, for boxes that do not move
      // when they get there. `more` is the same measurement the fade uses, so the stop appears
      // exactly when the scrollbar does; `expanded` is included because an expanded region has had
      // its cap lifted and its overflow state is no longer what `more` describes.
      tabIndex={more || expanded ? 0 : -1}
      data-testid={dataTestId}
    >
      {children}
    </div>
  );
}

// `id` is omitted rather than forwarded: this panel puts the id on an inner wrapper `<div>` so the
// expand button's `aria-controls` resolves, and accepting a second one would give callers a prop
// that quietly did nothing.
export interface ScrollPanelProps extends Omit<ScrollRegionProps, "expanded" | "id"> {
  /** The always-visible header. Pass your own heading element, as `Collapsible` does. */
  title?: React.ReactNode | undefined;
  /** Controls or badges pinned beside the title, above the scroll region. */
  actions?: React.ReactNode | undefined;
  /** Show the expand/collapse control. Off by default -- most bounded tables do not need it. */
  expandable?: boolean | undefined;
  /** Extra class on the root `.panel`. `className` still lands on the scrolling element. */
  panelClassName?: string | undefined;
}

/** A whole card whose heading stays put while its body scrolls. */
export function ScrollPanel({
  children,
  title,
  actions,
  expandable = false,
  size = "md",
  label,
  className,
  panelClassName,
  "data-testid": dataTestId,
}: ScrollPanelProps) {
  const { t } = useT();
  const [expanded, setExpanded] = useState(false);
  const regionId = useId();

  const rootClasses = ["panel", "scroll-panel"];
  if (expanded) rootClasses.push("expanded");
  if (panelClassName) rootClasses.push(panelClassName);

  const hasHead = Boolean(title || actions || expandable);

  return (
    <section className={rootClasses.join(" ")} data-testid={dataTestId}>
      {hasHead && (
        <div className="scroll-panel-head">
          {title}
          <div className="scroll-panel-actions">
            {actions}
            {expandable && (
              <button
                type="button"
                className="scroll-panel-expand"
                aria-expanded={expanded}
                aria-controls={regionId}
                onClick={() => setExpanded((v) => !v)}
              >
                {expanded ? t("ui.scroll.collapse") : t("ui.scroll.expand")}
              </button>
            )}
          </div>
        </div>
      )}
      <ScrollRegion
        size={size}
        label={label}
        expanded={expanded}
        className={className}
        data-testid={dataTestId ? `${dataTestId}-region` : undefined}
      >
        <div id={regionId}>{children}</div>
      </ScrollRegion>
    </section>
  );
}

export default ScrollPanel;

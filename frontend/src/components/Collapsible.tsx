/**
 * Generic expand/collapse wrapper, built on native `<details>/<summary>` rather than React state.
 *
 * This is a deliberate, documented choice for this codebase, not a style preference. `styles.css`
 * puts it two ways:
 *
 *   "Every symbol card, open or closed, is a `<details>` so the drill-down is collapsed by default
 *   and keyboard/AT-navigable for free -- the same disclosure primitive `.warning-detail` and
 *   `.empty-accounts-detail` already use elsewhere in this file, rather than a second hand-rolled
 *   expand/collapse implemented in React state."
 *
 *   "...matching this file's existing preference for native interactive elements
 *   (`<details>/<summary>`) over hand-rolled ARIA."
 *
 * The browser owns the open/closed state and all of the interaction: click, Enter/Space on the
 * summary, screen-reader disclosure semantics, and find-in-page all work with zero ARIA of our own.
 * `onToggle` only mirrors that state into React for callers that want to know; it never intercepts
 * or drives the toggle itself. No `role`, `aria-expanded` or `aria-controls` are added -- `<details>`
 * already conveys all of that natively, and adding them on top would be exactly the hand-rolled-ARIA
 * duplication the codebase is trying to avoid.
 *
 * Children are always rendered, never lazy-mounted: `<details>` hides collapsed content natively
 * (it stays in the DOM, just not painted/exposed), so find-in-page and any test that queries
 * collapsed content keep working. `MacroTile.tsx` lazy-mounts its chart deliberately -- that is a
 * special case for an expensive canvas child that fetches its own data on mount, not the general
 * rule for this wrapper.
 */
import { useState } from "react";

import "./Collapsible.css";

export interface CollapsibleProps {
  /** The always-visible header. A ReactNode, not a string, so a caller passes its OWN heading
   *  element (e.g. `<h2 className="section-heading">Changes since last filing</h2>`). */
  title: React.ReactNode;
  children: React.ReactNode;
  /** Open on first render. Defaults to `true`. */
  defaultOpen?: boolean;
  /** Extra class on the root `<details>`. */
  className?: string;
  /** Forwarded to the root element so callers can query it in tests. */
  "data-testid"?: string;
}

export default function Collapsible({
  title,
  children,
  defaultOpen = true,
  className,
  "data-testid": dataTestId,
}: CollapsibleProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <details
      className={className ? `collapsible ${className}` : "collapsible"}
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
      data-testid={dataTestId}
    >
      <summary className="collapsible-summary">{title}</summary>
      <div className="collapsible-body">{children}</div>
    </details>
  );
}

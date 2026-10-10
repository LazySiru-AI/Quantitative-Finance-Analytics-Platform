/**
 * The fixed-height card, and the grid that keeps a row of them the same height.
 *
 * `ScrollPanel` already solved "this one card must not grow without limit". What it does not solve
 * is the thing that actually makes a dashboard readable: a *row* of cards whose bottom edges line
 * up. A grid of `.panel`s each sized by its own content gives every row a ragged bottom edge and a
 * different amount of dead space, and the reader has to re-find the baseline in every column. So
 * height here is a property of the GRID (`grid-auto-rows`), not of each card -- the card fills its
 * track (`height: 100%`) and its body scrolls inside whatever it was given.
 *
 * Three pieces of behaviour are load-bearing:
 *
 *   - **The head and foot never scroll.** Same convention `ScrollPanel` follows and
 *     `EventCalendar.css` documents: the title, status and controls stay put, the body moves. A
 *     control that scrolls out of a bounded box is a control the reader has to hunt for.
 *   - **Expansion happens in place, and only one card at a time.** A card inside a `CardGrid`
 *     expands to `grid-column: 1 / -1` and `height: auto` -- it becomes a full-width row where it
 *     already was, rather than opening a modal or navigating away. The grid owns which card that is,
 *     so expanding a second card collapses the first; two full-width cards would defeat the point of
 *     the grid.
 *   - **That choice lives in the URL** (`?card=<id>`), via `useUrlState`, so an expanded card
 *     survives a refresh and can be linked to -- the same argument `useUrlState`'s docstring makes
 *     for tabs. A `CardGrid` rendered outside a router (a unit test, a storybook-style harness)
 *     silently falls back to local state instead of throwing; the grid is a presentation primitive
 *     and must not require routing context to render.
 *
 * `height="auto"` opts out of the whole bounded-body mechanism: no `ScrollRegion`, no cap, no
 * `label` requirement. It exists for the short cards (a four-stat summary, a single chart) that sit
 * in the same grid as the long ones and would look absurd with a scrollbar. They still get
 * `height: 100%` from the grid track, so the row still lines up.
 *
 * This does NOT share head markup with `ScrollPanel`. `Card` imports `ScrollRegion` from
 * `ScrollPanel.tsx`, so a shared head living in either file would close an import cycle between the
 * two modules; and the two heads differ anyway (`Card` carries a `status` slot and its own class
 * names, which `ScrollPanel`'s ten call sites depend on staying exactly as they are). Twenty lines
 * of duplication is the cheaper of the two prices.
 */
import { createContext, useCallback, useContext, useId, useMemo, useRef, useState } from "react";
import { useInRouterContext } from "react-router-dom";

import { ScrollRegion } from "@/components/ScrollPanel";
import { useUrlState } from "@/hooks/useUrlState";
import { useT } from "@/i18n/useT";

import "./Card.css";

/**
 * How tall the card's body is allowed to get. `sm`/`md`/`lg` are `ScrollPanelSize` verbatim -- the
 * caps are the same three numbers, so a `Card` and a `ScrollPanel` on the same page agree.
 *
 * `auto` means "size to content": no scroll region at all. Use it for cards that are short by
 * construction, never as a way to avoid picking a cap for a card that is genuinely long.
 */
export type CardHeight = "sm" | "md" | "lg" | "auto";

/** The query-string key a `CardGrid` uses to remember which of its cards is expanded. */
const CARD_URL_KEY = "card";

interface CardGridContextValue {
  /** The `id` of the currently expanded card, or `""` for none. */
  expandedId: string;
  setExpandedId: (id: string) => void;
}

const CardGridContext = createContext<CardGridContextValue | null>(null);

interface CardCommonProps {
  children: React.ReactNode;
  /**
   * Stable identifier, used as the expansion key inside a `CardGrid` and written to `?card=`.
   * Omit it and the card still expands, just privately (local state) and not in the URL.
   */
  id?: string | undefined;
  /** The always-visible heading. Pass your own heading element, as `ScrollPanel` does. */
  title?: React.ReactNode | undefined;
  /** A badge or one-line summary shown beside the title -- freshness, count, state. */
  status?: React.ReactNode | undefined;
  /** Controls pinned beside the title, above the body. */
  actions?: React.ReactNode | undefined;
  /** Show the expand/collapse control. */
  expandable?: boolean | undefined;
  /**
   * Controlled expansion. When provided, the card renders exactly this and never changes it itself:
   * the caller is expected to move it in `onExpandedChange`. Leave it out for the normal
   * (uncontrolled, or grid-coordinated) case.
   */
  expanded?: boolean | undefined;
  /** Fires on every toggle, controlled or not, with the state the card is moving TO. */
  onExpandedChange?: ((next: boolean) => void) | undefined;
  /** Pinned below the body -- a total, a "showing 20 of 400", a link out. Never scrolls. */
  footer?: React.ReactNode | undefined;
  /** Extra class on the BODY (the scrolling element), matching `ScrollPanel`'s convention. */
  className?: string | undefined;
  /** Extra class on the root `.panel`. */
  panelClassName?: string | undefined;
  /**
   * Names the card's `<section>` landmark from a heading id (pass the `id` you put on the heading
   * in `title`). Without it the landmark is anonymous -- fine for a tile in a grid, not for a page
   * section a screen-reader user navigates to by name.
   */
  "aria-labelledby"?: string | undefined;
  "data-testid"?: string | undefined;
}

/**
 * `label` is required for every height that produces a scroll region, and meaningless for `auto`,
 * which produces none. Expressing that as a union rather than an optional prop plus a runtime check
 * is what stops an unnamed tab stop reaching a screen reader -- the exact failure `ScrollRegion`'s
 * required `label` exists to prevent.
 */
export type CardProps = CardCommonProps &
  (
    | { height?: "sm" | "md" | "lg" | undefined; label: string }
    | { height: "auto"; label?: string | undefined }
  );

/** A card whose head and foot stay put while its body scrolls inside a fixed height. */
export function Card(props: CardProps) {
  const {
    children,
    id,
    title,
    status,
    actions,
    expandable = false,
    expanded: controlledExpanded,
    onExpandedChange,
    footer,
    className,
    panelClassName,
    "aria-labelledby": ariaLabelledBy,
    "data-testid": dataTestId,
  } = props;
  const height = props.height ?? "md";
  const label = props.label;

  const { t } = useT();
  const grid = useContext(CardGridContext);
  const bodyId = useId();
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const [localExpanded, setLocalExpanded] = useState(false);

  const isControlled = controlledExpanded !== undefined;
  // A card only joins the grid's one-at-a-time expansion if it has something to be identified BY.
  // Without an `id` there is nothing to put in `?card=`, so it falls back to private local state
  // rather than fighting its siblings over an empty key.
  const gridDriven = !isControlled && grid !== null && id !== undefined && id !== "";

  const expanded = isControlled
    ? controlledExpanded
    : gridDriven
      ? grid.expandedId === id
      : localExpanded;

  const setExpanded = useCallback(
    (next: boolean) => {
      if (!isControlled) {
        if (gridDriven) {
          grid.setExpandedId(next ? (id as string) : "");
        } else {
          setLocalExpanded(next);
        }
      }
      onExpandedChange?.(next);
    },
    [isControlled, gridDriven, grid, id, onExpandedChange],
  );

  const onToggle = useCallback(() => {
    const next = !expanded;
    setExpanded(next);
    // Collapsing removes the content the reader was just in. Putting focus back on the control that
    // did it keeps the keyboard user where they are instead of dumping them at the top of the
    // document -- and it must happen only on a self-initiated collapse, never when the grid
    // collapses this card because a sibling opened, or the card would steal focus from that sibling.
    if (!next) buttonRef.current?.focus();
  }, [expanded, setExpanded]);

  const rootClasses = ["panel", "card", `card-${height}`];
  if (expanded) rootClasses.push("expanded");
  if (panelClassName) rootClasses.push(panelClassName);

  const bodyClasses = ["card-body"];
  if (className) bodyClasses.push(className);

  const hasHead = Boolean(title || status || actions || expandable);
  const bodyTestId = dataTestId ? `${dataTestId}-body` : undefined;

  return (
    <section
      className={rootClasses.join(" ")}
      aria-labelledby={ariaLabelledBy}
      data-card-id={id}
      data-expanded={expanded ? "true" : "false"}
      data-testid={dataTestId}
    >
      {hasHead && (
        <div className="card-head">
          <div className="card-head-main">
            {title}
            {status !== undefined && status !== null && status !== false && (
              <span className="card-status">{status}</span>
            )}
          </div>
          <div className="card-actions">
            {actions}
            {expandable && (
              <button
                ref={buttonRef}
                type="button"
                className="card-expand"
                aria-expanded={expanded}
                aria-controls={bodyId}
                onClick={onToggle}
              >
                {expanded ? t("ui.scroll.collapse") : t("ui.scroll.expand")}
              </button>
            )}
          </div>
        </div>
      )}
      {height === "auto" ? (
        <div id={bodyId} className={bodyClasses.join(" ")} data-testid={bodyTestId}>
          {children}
        </div>
      ) : (
        <ScrollRegion
          id={bodyId}
          size={height}
          label={label ?? ""}
          expanded={expanded}
          className={bodyClasses.join(" ")}
          data-testid={bodyTestId}
        >
          {children}
        </ScrollRegion>
      )}
      {footer !== undefined && footer !== null && footer !== false && (
        <div className="card-foot">{footer}</div>
      )}
    </section>
  );
}

/**
 * Expansion state in the URL. Split into its own component (rather than a hook with a conditional
 * branch) because the two sources need different hooks, and swapping which hooks run inside one
 * component is exactly the thing React forbids. Which of the two renders is fixed for the life of
 * the tree, so nothing ever remounts.
 */
function UrlExpansionScope({ children }: { children: React.ReactNode }) {
  // Explicitly `<string>`: left to infer, `T` binds to the literal type `""` of the fallback and
  // the setter will only accept an empty string back.
  const [expandedId, setExpandedId] = useUrlState<string>(CARD_URL_KEY, "");
  const value = useMemo<CardGridContextValue>(
    () => ({ expandedId, setExpandedId }),
    [expandedId, setExpandedId],
  );
  return <CardGridContext.Provider value={value}>{children}</CardGridContext.Provider>;
}

/** The router-less fallback: same contract, no URL. */
function LocalExpansionScope({ children }: { children: React.ReactNode }) {
  const [expandedId, setExpandedId] = useState("");
  const value = useMemo<CardGridContextValue>(
    () => ({ expandedId, setExpandedId }),
    [expandedId, setExpandedId],
  );
  return <CardGridContext.Provider value={value}>{children}</CardGridContext.Provider>;
}

export interface CardGridProps {
  children: React.ReactNode;
  /**
   * The height every track in this grid gets, which is what makes the row line up. Cards inherit it
   * for their own bodies only if they are given the same `height` -- pass it to both.
   * `auto` gives equal-height rows sized to the tallest card in each row (`grid-auto-rows: 1fr`).
   */
  height?: CardHeight | undefined;
  /** Minimum column width before the grid drops to fewer columns. Any CSS length. */
  min?: string | undefined;
  className?: string | undefined;
  "data-testid"?: string | undefined;
}

/** A responsive grid of equal-height cards, coordinating which one is expanded. */
export function CardGrid({
  children,
  height = "md",
  min = "320px",
  className,
  "data-testid": dataTestId,
}: CardGridProps) {
  // `useUrlState` calls `useSearchParams`, which throws outside a router. Asking first is cheaper
  // and honest-er than catching: a grid in a test harness has no URL to write to, and should say so
  // rather than crash the page it is decorating.
  const inRouter = useInRouterContext();
  const Scope = inRouter ? UrlExpansionScope : LocalExpansionScope;

  const classes = ["card-grid", `card-grid-${height}`];
  if (className) classes.push(className);

  return (
    <Scope>
      <div
        className={classes.join(" ")}
        style={{ "--card-min": min } as React.CSSProperties}
        data-testid={dataTestId}
      >
        {children}
      </div>
    </Scope>
  );
}

export default Card;

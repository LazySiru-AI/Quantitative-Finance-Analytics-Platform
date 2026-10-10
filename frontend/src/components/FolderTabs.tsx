/**
 * The app-wide "pick one of a few" control, for state that switches which local content renders.
 *
 * `styles.css` already has a control that looks like this -- `.nav-sections` -- and its own comment
 * explains exactly why `FolderTabs` cannot just be that class reused: `.nav-sections` renders links
 * to different ROUTED pages, so it is deliberately never given `role="tab"`, because that role
 * promises assistive tech roving-tabindex and a panel in the same subtree, and a page link has
 * neither. `FolderTabs` is for the other case -- Account's positions view, Persona's active tab,
 * Agent Desk's pipeline picker -- where picking an item swaps content already in the DOM. That is
 * exactly what `role="tablist"` is for, so this component earns the role `.nav-sections` correctly
 * declines.
 *
 * Visually it is a deliberate evolution of `.view-tabs` / `.timeframe-tab` (Ticker's chart-layout
 * switch), not a second, competing tab style: same mono uppercase pill vocabulary, same token
 * palette. What `.timeframe-tab` does not have, and what this needs, is the "which tab is currently
 * FOCUSED and which is currently PICKED" distinction that only matters once keyboard users are a
 * first-class citizen. `.timeframe-tab` gets away with a plain `<button>` list because it is small
 * (never more than five items observed today); `FolderTabs` is meant for call sites that can grow
 * past that, so it does the accessible-tabs pattern properly:
 *
 *   - **Automatic activation.** Per the WAI-ARIA Authoring Practices tabs pattern, this is an
 *     "automatic activation" tablist: moving focus with the arrow keys ALSO selects, rather than
 *     requiring a separate Enter/Space. That is the correct choice specifically because switching
 *     here is cheap and instant (no network round-trip gates the panel change) -- the pattern's own
 *     guidance is to reserve "manual activation" (focus without selecting) for tabs whose content is
 *     expensive to load.
 *   - **Roving tabindex.** Only the selected tab is in the page's Tab order (`tabIndex=0`); the rest
 *     are `-1` and reachable only via the arrow keys once the rail has focus. This is what keeps a
 *     10-tab rail from costing a keyboard user 10 stops just to get past it.
 *   - **A panel the tabs actually control.** `role="tab"` is a promise of two things, and the rail
 *     alone only kept one of them: until this component grew `children`/`panelId`, no `aria-controls`
 *     and no `role="tabpanel"` existed anywhere in the app, so a screen-reader user was told "tab 2
 *     of 5" and given nothing to move into. Passing the active content as `children` renders it in
 *     an owned `role="tabpanel"` wired both ways; `panelId` covers a caller that must keep its
 *     panel elsewhere in the tree. Both are optional, so no existing call site had to change.
 *   - **The rail scrolls, the page does not.** `overflow-x: auto` lives on the rail div itself, and
 *     the active tab is scrolled into view by hand-adjusting `rail.scrollLeft` against the two
 *     elements' bounding rects rather than calling `element.scrollIntoView()` -- `scrollIntoView`
 *     walks up and can scroll an ancestor (here, the page) into a position that "helps" the rail at
 *     the cost of yanking the whole viewport, which is the one failure mode a horizontally-scrolling
 *     rail exists to avoid.
 *
 * Two sizes so a page can stack a primary view rail above a secondary selection rail (the Account
 * page's intended layout: view on top, account choice beneath) and have the pair read as a
 * hierarchy rather than as two unrelated peers -- `sm` is deliberately quieter (smaller type,
 * tighter padding), not just smaller.
 *
 * This component does not read or write the URL. `useUrlState` (`hooks/useUrlState.ts`) is the
 * other half of this pair; keeping them separate is what lets `FolderTabs` also serve ephemeral,
 * non-URL state (a modal's internal step picker, say) without dragging routing into it.
 */
import { useCallback, useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from "react";

import { useT } from "@/i18n/useT";

import "./FolderTabs.css";

export type FolderTabTone = "neutral" | "ok" | "warn" | "bad";

export type FolderTabItem = {
  id: string;
  label: string;
  /** A count or amount rendered small after the label, e.g. "12" or "$41.2k". */
  badge?: string | undefined;
  /** Colours the badge only, never the tab itself. */
  tone?: FolderTabTone | undefined;
};

export interface FolderTabsProps {
  items: readonly FolderTabItem[];
  active: string;
  onChange: (id: string) => void;
  /** Accessible name for the tablist, e.g. "Account". */
  label: string;
  size?: "md" | "sm" | undefined;
  /**
   * The id of the element that holds the active tab's content, when the caller renders that panel
   * itself rather than passing it as `children`. Supplying it is what lets each tab carry a truthful
   * `aria-controls`; the caller is then responsible for putting `role="tabpanel"` and
   * `aria-labelledby` on that element. Ignored when `children` is given -- this component's own
   * panel wins, because it is the one it can guarantee exists.
   */
  panelId?: string | undefined;
  /**
   * The active tab's content. When given, this component renders it inside its own
   * `role="tabpanel"` element wired to the selected tab in both directions (`aria-controls` down,
   * `aria-labelledby` back up), which is the whole reason `role="tab"` is allowed here at all.
   * Optional so that every call site that predates this stays valid: without it the rail renders
   * exactly as before, just with stable `id`s.
   */
  children?: ReactNode | undefined;
}

/** Above this many options, callers use a grouped dropdown instead of a tab rail -- a horizontally
 *  scrolling rail is still technically usable well past this, but it stops being SCANNABLE, which
 *  is the actual point of a tab rail over a `<select>`. */
export const FOLDER_TAB_MAX = 8;

export function FolderTabs({
  items,
  active,
  onChange,
  label,
  size = "md",
  panelId,
  children,
}: FolderTabsProps) {
  const { t } = useT();
  const railRef = useRef<HTMLDivElement | null>(null);
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  // `useId`, not the item ids alone: a page can mount two rails (the Account page's view rail above
  // its account rail) and both could legitimately contain an item called "all". Ids collide, and a
  // colliding `aria-labelledby` points a panel at whichever duplicate the browser found first.
  const uid = useId();
  const tabDomId = (itemId: string) => `${uid}-tab-${itemId}`;
  const ownPanelId = `${uid}-panel`;
  // Only claim to control a panel that actually exists. An `aria-controls` pointing at nothing is
  // worse than none at all -- a screen reader offers the user a jump that goes nowhere.
  const controlledPanelId = children !== undefined ? ownPanelId : panelId;

  useEffect(() => {
    const rail = railRef.current;
    const activeTab = tabRefs.current[active];
    if (!rail || !activeTab) return;
    // Manual scroll-into-view, scoped to `rail.scrollLeft` only, rather than
    // `activeTab.scrollIntoView()` -- see the module docstring for why that matters here.
    const railRect = rail.getBoundingClientRect();
    const tabRect = activeTab.getBoundingClientRect();
    if (tabRect.left < railRect.left) {
      rail.scrollLeft -= railRect.left - tabRect.left;
    } else if (tabRect.right > railRect.right) {
      rail.scrollLeft += tabRect.right - railRect.right;
    }
  }, [active]);

  const selectByIndex = useCallback(
    (index: number) => {
      const item = items[index];
      if (!item) return;
      onChange(item.id);
      // Automatic activation moves both selection AND focus together -- see module docstring.
      tabRefs.current[item.id]?.focus();
    },
    [items, onChange],
  );

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
      const count = items.length;
      if (count === 0) return;
      switch (event.key) {
        case "ArrowRight":
          event.preventDefault();
          selectByIndex((index + 1) % count);
          break;
        case "ArrowLeft":
          event.preventDefault();
          selectByIndex((index - 1 + count) % count);
          break;
        case "Home":
          event.preventDefault();
          selectByIndex(0);
          break;
        case "End":
          event.preventDefault();
          selectByIndex(count - 1);
          break;
        default:
          break;
      }
    },
    [items.length, selectByIndex],
  );

  return (
    <div className={`folder-tabs folder-tabs-${size}`}>
      <div className="folder-tabs-rail" role="tablist" aria-label={label} ref={railRef}>
        {items.map((item, index) => {
          const selected = item.id === active;
          const hasBadge = item.badge !== undefined;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              id={tabDomId(item.id)}
              aria-selected={selected}
              aria-controls={controlledPanelId}
              tabIndex={selected ? 0 : -1}
              className="folder-tab"
              ref={(el) => {
                tabRefs.current[item.id] = el;
              }}
              onClick={() => onChange(item.id)}
              onKeyDown={(event) => handleKeyDown(event, index)}
            >
              {item.label}
              {hasBadge && (
                <>
                  {/* Visible, tone-coloured, and excluded from the accessible name -- the
                      visually-hidden span below supplies that name instead, so the badge is heard
                      as part of the tab's one name rather than as a second control. */}
                  <span
                    className={`folder-tab-badge folder-tab-badge-${item.tone ?? "neutral"}`}
                    aria-hidden="true"
                  >
                    {item.badge}
                  </span>
                  <span className="visually-hidden">
                    {`, ${t("interaction.tabs.badgeLabel", { badge: item.badge ?? "" })}`}
                  </span>
                </>
              )}
            </button>
          );
        })}
      </div>
      {children !== undefined && (
        // `tabIndex={0}` per the WAI-ARIA tabs pattern: a panel whose content holds no focusable
        // element of its own would otherwise be unreachable by keyboard, and this component cannot
        // know what its callers put inside.
        <div
          id={ownPanelId}
          role="tabpanel"
          tabIndex={0}
          aria-labelledby={tabDomId(active)}
          className="folder-tabs-panel"
        >
          {children}
        </div>
      )}
    </div>
  );
}

export default FolderTabs;

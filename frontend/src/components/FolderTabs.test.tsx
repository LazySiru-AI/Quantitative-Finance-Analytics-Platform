/**
 * FolderTabs: one `role="tab"` per item with correct `aria-selected`, clicking and the WAI-ARIA
 * roving-tabindex arrow-key contract (wrap at both ends, Home/End), and a badge that is rendered
 * but folded into the tab's single accessible name rather than announced as a separate control.
 *
 * jsdom has no layout engine, so the scroll-into-view effect (which reads `getBoundingClientRect`)
 * is a no-op here -- every rect is zero -- and is left to the browser probe run at integration time,
 * same convention `ScrollPanel.test.tsx` documents for its own measurement effect.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FolderTabs, FOLDER_TAB_MAX, type FolderTabItem } from "@/components/FolderTabs";

afterEach(cleanup);

const ITEMS: FolderTabItem[] = [
  { id: "open", label: "Open" },
  { id: "closed", label: "Closed" },
  { id: "all", label: "All" },
];

describe("FolderTabs", () => {
  it("renders one tab per item with the active one marked selected", () => {
    render(<FolderTabs items={ITEMS} active="closed" onChange={vi.fn()} label="Account" />);

    const tablist = screen.getByRole("tablist", { name: "Account" });
    expect(tablist).toBeTruthy();

    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(3);

    const open = screen.getByRole("tab", { name: "Open" });
    const closed = screen.getByRole("tab", { name: "Closed" });
    expect(open.getAttribute("aria-selected")).toBe("false");
    expect(closed.getAttribute("aria-selected")).toBe("true");
  });

  it("roving tabindex: only the active tab is in the page tab order", () => {
    render(<FolderTabs items={ITEMS} active="open" onChange={vi.fn()} label="Account" />);
    expect(screen.getByRole("tab", { name: "Open" }).getAttribute("tabindex")).toBe("0");
    expect(screen.getByRole("tab", { name: "Closed" }).getAttribute("tabindex")).toBe("-1");
    expect(screen.getByRole("tab", { name: "All" }).getAttribute("tabindex")).toBe("-1");
  });

  it("clicking a tab calls onChange with its id", () => {
    const onChange = vi.fn();
    render(<FolderTabs items={ITEMS} active="open" onChange={onChange} label="Account" />);
    fireEvent.click(screen.getByRole("tab", { name: "Closed" }));
    expect(onChange).toHaveBeenCalledWith("closed");
  });

  it("ArrowRight from the last tab wraps to the first", () => {
    const onChange = vi.fn();
    render(<FolderTabs items={ITEMS} active="all" onChange={onChange} label="Account" />);
    fireEvent.keyDown(screen.getByRole("tab", { name: "All" }), { key: "ArrowRight" });
    expect(onChange).toHaveBeenCalledWith("open");
  });

  it("ArrowLeft from the first tab wraps to the last", () => {
    const onChange = vi.fn();
    render(<FolderTabs items={ITEMS} active="open" onChange={onChange} label="Account" />);
    fireEvent.keyDown(screen.getByRole("tab", { name: "Open" }), { key: "ArrowLeft" });
    expect(onChange).toHaveBeenCalledWith("all");
  });

  it("ArrowRight from a middle tab moves forward without wrapping", () => {
    const onChange = vi.fn();
    render(<FolderTabs items={ITEMS} active="open" onChange={onChange} label="Account" />);
    fireEvent.keyDown(screen.getByRole("tab", { name: "Open" }), { key: "ArrowRight" });
    expect(onChange).toHaveBeenCalledWith("closed");
  });

  it("Home jumps to the first tab, End jumps to the last", () => {
    const onChange = vi.fn();
    render(<FolderTabs items={ITEMS} active="closed" onChange={onChange} label="Account" />);
    fireEvent.keyDown(screen.getByRole("tab", { name: "Closed" }), { key: "Home" });
    expect(onChange).toHaveBeenLastCalledWith("open");
    fireEvent.keyDown(screen.getByRole("tab", { name: "Closed" }), { key: "End" });
    expect(onChange).toHaveBeenLastCalledWith("all");
  });

  it("automatic activation moves focus to the newly selected tab", () => {
    const onChange = vi.fn();
    render(<FolderTabs items={ITEMS} active="open" onChange={onChange} label="Account" />);
    fireEvent.keyDown(screen.getByRole("tab", { name: "Open" }), { key: "ArrowRight" });
    expect(document.activeElement).toBe(screen.getByRole("tab", { name: "Closed" }));
  });

  it("renders the badge and folds it into the tab's accessible name", () => {
    const items: FolderTabItem[] = [
      { id: "roth", label: "Roth IRA", badge: "12", tone: "ok" },
      { id: "brokerage", label: "Brokerage" },
    ];
    render(<FolderTabs items={items} active="roth" onChange={vi.fn()} label="Account" />);

    // The visible badge text is on the page...
    expect(screen.getByText("12")).toBeTruthy();
    // ...and the whole tab announces as one control whose name includes it, not as two controls.
    // (The accessible-name algorithm joins the label text node and the visually-hidden text node
    // with a space of its own, hence "Roth IRA , 12" rather than "Roth IRA, 12".)
    expect(screen.getByRole("tab", { name: "Roth IRA , 12" })).toBeTruthy();
    expect(screen.getAllByRole("tab")).toHaveLength(2);
  });

  it("a tab without a badge has no badge markup", () => {
    render(<FolderTabs items={ITEMS} active="open" onChange={vi.fn()} label="Account" />);
    const openTab = screen.getByRole("tab", { name: "Open" });
    expect(openTab.querySelector(".folder-tab-badge")).toBeNull();
  });

  it("applies the sm size class for the secondary-rail variant", () => {
    const { container } = render(
      <FolderTabs items={ITEMS} active="open" onChange={vi.fn()} label="Account" size="sm" />,
    );
    expect(container.querySelector(".folder-tabs-sm")).toBeTruthy();
  });
});

/**
 * The `role="tabpanel"` half of the tabs contract. `role="tab"` promises assistive tech a panel it
 * controls; before this the rail declared the role and no element anywhere in the app carried the
 * matching one, so the promise was unkept on every rail in the product.
 */
describe("FolderTabs panel wiring", () => {
  it("renders children in an owned tabpanel wired to the selected tab in both directions", () => {
    render(
      <FolderTabs items={ITEMS} active="closed" onChange={vi.fn()} label="Account">
        <p>closed positions</p>
      </FolderTabs>,
    );

    const panel = screen.getByRole("tabpanel");
    const closed = screen.getByRole("tab", { name: "Closed" });
    expect(closed.getAttribute("aria-controls")).toBe(panel.getAttribute("id"));
    expect(panel.getAttribute("aria-labelledby")).toBe(closed.getAttribute("id"));
    expect(screen.getByText("closed positions")).toBeTruthy();
  });

  it("moves the panel's label to whichever tab is selected", () => {
    const { rerender } = render(
      <FolderTabs items={ITEMS} active="open" onChange={vi.fn()} label="Account">
        <p>body</p>
      </FolderTabs>,
    );
    expect(screen.getByRole("tabpanel").getAttribute("aria-labelledby")).toBe(
      screen.getByRole("tab", { name: "Open" }).getAttribute("id"),
    );

    rerender(
      <FolderTabs items={ITEMS} active="all" onChange={vi.fn()} label="Account">
        <p>body</p>
      </FolderTabs>,
    );
    expect(screen.getByRole("tabpanel").getAttribute("aria-labelledby")).toBe(
      screen.getByRole("tab", { name: "All" }).getAttribute("id"),
    );
  });

  it("gives the panel a tab stop, since its content may hold nothing focusable", () => {
    render(
      <FolderTabs items={ITEMS} active="open" onChange={vi.fn()} label="Account">
        <p>text only</p>
      </FolderTabs>,
    );
    expect(screen.getByRole("tabpanel").getAttribute("tabindex")).toBe("0");
  });

  it("points aria-controls at a caller-rendered panel when given panelId", () => {
    render(
      <FolderTabs
        items={ITEMS}
        active="open"
        onChange={vi.fn()}
        label="Account"
        panelId="elsewhere"
      />,
    );
    for (const tab of screen.getAllByRole("tab")) {
      expect(tab.getAttribute("aria-controls")).toBe("elsewhere");
    }
  });

  it("claims no aria-controls at all when there is no panel to point at", () => {
    // An `aria-controls` naming a missing element is worse than none: it offers a keyboard user a
    // jump that lands nowhere. Every call site that predates the panel prop is in this shape.
    render(<FolderTabs items={ITEMS} active="open" onChange={vi.fn()} label="Account" />);
    expect(screen.queryByRole("tabpanel")).toBeNull();
    for (const tab of screen.getAllByRole("tab")) {
      expect(tab.hasAttribute("aria-controls")).toBe(false);
    }
  });

  it("gives two rails on one page non-colliding ids for the same item id", () => {
    render(
      <>
        <FolderTabs items={ITEMS} active="all" onChange={vi.fn()} label="View">
          <p>one</p>
        </FolderTabs>
        <FolderTabs items={ITEMS} active="all" onChange={vi.fn()} label="Account">
          <p>two</p>
        </FolderTabs>
      </>,
    );
    const [first, second] = screen.getAllByRole("tabpanel");
    expect(first?.getAttribute("aria-labelledby")).not.toBe(second?.getAttribute("aria-labelledby"));
    const ids = screen.getAllByRole("tab").map((tab) => tab.getAttribute("id"));
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("FOLDER_TAB_MAX", () => {
  it("is the documented threshold above which callers switch to a dropdown", () => {
    expect(FOLDER_TAB_MAX).toBe(8);
  });
});

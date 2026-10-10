/**
 * ScrollPanel / ScrollRegion: the cap is applied by class, the region is reachable and named for
 * keyboard and AT users, the heading stays outside the scrolling body, expanding lifts the cap, and
 * the "more below" affordance reflects a real measurement rather than being always on.
 *
 * jsdom has no layout engine -- every element reports zero height -- so this file asserts the
 * contract that survives that (classes, roles, names, DOM position, state transitions) and leaves
 * the actual pixel heights to the browser probe run at integration time.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ScrollPanel, ScrollRegion } from "@/components/ScrollPanel";

afterEach(cleanup);

describe("ScrollRegion", () => {
  it("defaults to the md cap and applies the size class", () => {
    const { rerender } = render(
      <ScrollRegion label="Holdings" data-testid="r">
        rows
      </ScrollRegion>,
    );
    expect(screen.getByTestId("r").className).toContain("scroll-region-md");

    rerender(
      <ScrollRegion label="Holdings" size="lg" data-testid="r">
        rows
      </ScrollRegion>,
    );
    expect(screen.getByTestId("r").className).toContain("scroll-region-lg");
  });

  it("is a named region, and a tab stop only once there is something to scroll", () => {
    render(
      <ScrollRegion label="Tax disposals" data-testid="r">
        rows
      </ScrollRegion>,
    );
    const region = screen.getByRole("region", { name: "Tax disposals" });
    expect(region).toBe(screen.getByTestId("r"));

    // jsdom reports every dimension as 0, so nothing overflows: the region cannot scroll, and a tab
    // stop on it would cost a keyboard user a press for a box that does not move. Across 96 call
    // sites that is dozens of dead stops, so the default has to be "not a stop".
    expect(region.getAttribute("tabindex")).toBe("-1");

    // Give it content that genuinely overflows and drive the same measurement the component runs on
    // scroll (there is no ResizeObserver in jsdom, so the scroll handler is the live path).
    Object.defineProperty(region, "scrollHeight", { value: 900, configurable: true });
    Object.defineProperty(region, "clientHeight", { value: 400, configurable: true });
    fireEvent.scroll(region);

    expect(region.getAttribute("tabindex")).toBe("0");
  });

  it("is a tab stop while expanded, where `more` no longer describes the overflow", () => {
    render(
      <ScrollRegion label="Tax disposals" expanded data-testid="r">
        rows
      </ScrollRegion>,
    );
    expect(screen.getByTestId("r").getAttribute("tabindex")).toBe("0");
  });

  it("lifts the cap when expanded", () => {
    render(
      <ScrollRegion label="Holdings" expanded data-testid="r">
        rows
      </ScrollRegion>,
    );
    expect(screen.getByTestId("r").className).toContain("expanded");
  });

  it("reports no content below the fold when nothing overflows", () => {
    // jsdom reports every dimension as 0, so scrollHeight - clientHeight - scrollTop === 0: the
    // honest answer is "nothing more", and the fade must stay off rather than defaulting to on.
    render(
      <ScrollRegion label="Holdings" data-testid="r">
        rows
      </ScrollRegion>,
    );
    expect(screen.getByTestId("r").getAttribute("data-more")).toBe("false");
  });

  it("turns the fade on when the content actually overflows", () => {
    render(
      <ScrollRegion label="Holdings" data-testid="r">
        rows
      </ScrollRegion>,
    );
    const region = screen.getByTestId("r");
    Object.defineProperty(region, "scrollHeight", { value: 900, configurable: true });
    Object.defineProperty(region, "clientHeight", { value: 400, configurable: true });

    fireEvent.scroll(region);

    expect(region.getAttribute("data-more")).toBe("true");
  });

  it("turns the fade off again once scrolled to the end", () => {
    render(
      <ScrollRegion label="Holdings" data-testid="r">
        rows
      </ScrollRegion>,
    );
    const region = screen.getByTestId("r");
    Object.defineProperty(region, "scrollHeight", { value: 900, configurable: true });
    Object.defineProperty(region, "clientHeight", { value: 400, configurable: true });
    Object.defineProperty(region, "scrollTop", { value: 500, configurable: true });

    fireEvent.scroll(region);

    expect(region.getAttribute("data-more")).toBe("false");
  });
});

describe("ScrollPanel", () => {
  it("keeps the heading outside the scrolling region", () => {
    render(
      <ScrollPanel
        title={<h2 className="section-heading">Holdings</h2>}
        label="Holdings rows"
        data-testid="p"
      >
        <p>row content</p>
      </ScrollPanel>,
    );

    const heading = screen.getByRole("heading", { name: "Holdings" });
    const region = screen.getByRole("region", { name: "Holdings rows" });
    expect(region.contains(heading)).toBe(false);
    expect(screen.getByTestId("p").contains(heading)).toBe(true);
  });

  it("renders no expand control unless asked", () => {
    render(
      <ScrollPanel label="Holdings rows">
        <p>rows</p>
      </ScrollPanel>,
    );
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("expands and collapses, and says which it is doing", () => {
    render(
      <ScrollPanel label="Holdings rows" expandable data-testid="p">
        <p>rows</p>
      </ScrollPanel>,
    );

    const button = screen.getByRole("button", { name: "Expand" });
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByTestId("p-region").className).not.toContain("expanded");

    fireEvent.click(button);

    const collapse = screen.getByRole("button", { name: "Collapse" });
    expect(collapse.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByTestId("p-region").className).toContain("expanded");

    fireEvent.click(collapse);
    expect(screen.getByRole("button", { name: "Expand" })).toBeTruthy();
  });

  it("points the expand control at the region it controls", () => {
    render(
      <ScrollPanel label="Holdings rows" expandable>
        <p>rows</p>
      </ScrollPanel>,
    );
    const controls = screen.getByRole("button").getAttribute("aria-controls");
    expect(controls).toBeTruthy();
    expect(document.getElementById(controls as string)).toBeTruthy();
  });

  it("renders actions beside the title, above the scroll region", () => {
    render(
      <ScrollPanel
        label="Holdings rows"
        title={<h2>Holdings</h2>}
        actions={<span data-testid="action">badge</span>}
      >
        <p>rows</p>
      </ScrollPanel>,
    );
    const region = screen.getByRole("region", { name: "Holdings rows" });
    expect(region.contains(screen.getByTestId("action"))).toBe(false);
  });
});

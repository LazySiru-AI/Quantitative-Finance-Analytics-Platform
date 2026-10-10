/**
 * Card / CardGrid: the structural contract a fixed-height card has to keep.
 *
 * jsdom has no layout engine, so "the cards are the same height" is not assertable here and is left
 * to the browser probe. What IS assertable is everything that makes that height reachable and
 * honest: the head and foot sit outside the scrolling body, there is exactly one scroller per card
 * (a scroller inside a scroller traps the wheel), the expand control names the element it expands,
 * and the grid -- not the card -- decides which single card is open, with that choice in the URL.
 *
 * The router-less case is tested deliberately rather than incidentally. `useUrlState` calls
 * `useSearchParams`, which throws outside a router, and a presentation primitive that cannot render
 * in a plain `render()` is a primitive nobody can unit-test around.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Card, CardGrid } from "@/components/Card";

afterEach(cleanup);

function UrlProbe() {
  const location = useLocation();
  return <span data-testid="url">{location.search}</span>;
}

describe("Card", () => {
  it("keeps the head and the foot outside the scrolling body", () => {
    render(
      <Card
        title={<h2>Holdings</h2>}
        status={<span data-testid="status">12 lots</span>}
        actions={<button type="button">Refresh</button>}
        footer={<span data-testid="foot">showing 12 of 400</span>}
        label="Holdings rows"
        data-testid="c"
      >
        <p>row content</p>
      </Card>,
    );

    const region = screen.getByRole("region", { name: "Holdings rows" });
    const card = screen.getByTestId("c");

    for (const outside of [
      screen.getByRole("heading", { name: "Holdings" }),
      screen.getByTestId("status"),
      screen.getByRole("button", { name: "Refresh" }),
      screen.getByTestId("foot"),
    ]) {
      expect(region.contains(outside)).toBe(false);
      expect(card.contains(outside)).toBe(true);
    }
  });

  it("has exactly one scroll region, and it is the card body", () => {
    render(
      <Card title={<h2>Fills</h2>} label="Fill rows" expandable data-testid="c">
        <table>
          <tbody>
            <tr>
              <td>row</td>
            </tr>
          </tbody>
        </table>
      </Card>,
    );

    const card = screen.getByTestId("c");
    // Two nested scrollers would make the inner content unreachable on touch and steal the wheel on
    // desktop, which is the failure this primitive exists to make structurally impossible.
    expect(card.querySelectorAll(".scroll-region")).toHaveLength(1);

    const body = screen.getByTestId("c-body");
    expect(body.className).toContain("scroll-region");
    expect(body.className).toContain("card-body");
    expect(body.className).toContain("scroll-region-md");
  });

  it("applies the requested height to both the card and its body cap", () => {
    render(
      <Card label="Log lines" height="sm" data-testid="c">
        log
      </Card>,
    );
    expect(screen.getByTestId("c").className).toContain("card-sm");
    expect(screen.getByTestId("c-body").className).toContain("scroll-region-sm");
  });

  it('renders no scroll region at all when height="auto"', () => {
    render(
      <Card title={<h2>Summary</h2>} height="auto" data-testid="c">
        <p>four stats</p>
      </Card>,
    );

    const card = screen.getByTestId("c");
    expect(card.querySelectorAll(".scroll-region")).toHaveLength(0);
    expect(screen.queryByRole("region")).toBeNull();
    expect(screen.getByTestId("c-body").className).toBe("card-body");
  });

  it("points the expand control at the body it expands", () => {
    render(
      <Card label="Holdings rows" expandable data-testid="c">
        rows
      </Card>,
    );

    const button = screen.getByRole("button", { name: "Expand" });
    expect(button.getAttribute("aria-expanded")).toBe("false");

    const controls = button.getAttribute("aria-controls");
    expect(controls).toBeTruthy();
    // The id must land on the scrolling element itself, not a wrapper beside it: `aria-controls`
    // that resolves to something other than the thing that changed is worse than none.
    expect(document.getElementById(controls as string)).toBe(screen.getByTestId("c-body"));
  });

  it("renders no expand control unless asked", () => {
    render(
      <Card label="Holdings rows" data-testid="c">
        rows
      </Card>,
    );
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("expands and collapses on its own, and says which it is doing", () => {
    render(
      <Card label="Holdings rows" expandable data-testid="c">
        rows
      </Card>,
    );

    const button = screen.getByRole("button", { name: "Expand" });
    expect(screen.getByTestId("c").className).not.toContain("expanded");

    fireEvent.click(button);

    const collapse = screen.getByRole("button", { name: "Collapse" });
    expect(collapse.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByTestId("c").className).toContain("expanded");
    expect(screen.getByTestId("c-body").className).toContain("expanded");

    fireEvent.click(collapse);
    expect(screen.getByRole("button", { name: "Expand" })).toBeTruthy();
    expect(screen.getByTestId("c").className).not.toContain("expanded");
  });

  it("puts focus back on the expand control after a collapse", () => {
    render(
      <Card label="Holdings rows" expandable data-testid="c">
        rows
      </Card>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    const collapse = screen.getByRole("button", { name: "Collapse" });
    collapse.blur();

    fireEvent.click(collapse);

    // The content the reader was inside has just gone. Focus has to land somewhere deliberate.
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Expand" }));
  });

  it("stays where the caller put it when expansion is controlled", () => {
    const onExpandedChange = vi.fn();
    render(
      <Card
        label="Holdings rows"
        expandable
        expanded={false}
        onExpandedChange={onExpandedChange}
        data-testid="c"
      >
        rows
      </Card>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Expand" }));

    expect(onExpandedChange).toHaveBeenCalledWith(true);
    // Controlled means controlled: the card must not move itself, or the caller's state and the DOM
    // disagree for a frame and the component becomes the source of truth it was told not to be.
    expect(screen.getByTestId("c").className).not.toContain("expanded");
    expect(screen.getByRole("button", { name: "Expand" })).toBeTruthy();
  });
});

describe("CardGrid", () => {
  it("sizes its tracks and its minimum column width", () => {
    render(
      <MemoryRouter>
        <CardGrid height="lg" min="420px" data-testid="g">
          <Card id="a" label="A rows">
            a
          </Card>
        </CardGrid>
      </MemoryRouter>,
    );

    const grid = screen.getByTestId("g");
    expect(grid.className).toContain("card-grid");
    expect(grid.className).toContain("card-grid-lg");
    expect(grid.style.getPropertyValue("--card-min")).toBe("420px");
  });

  it("expands exactly one card at a time, and puts the choice in ?card=", () => {
    render(
      <MemoryRouter initialEntries={["/account"]}>
        <UrlProbe />
        <CardGrid>
          <Card id="holdings" label="Holdings rows" expandable data-testid="a">
            a
          </Card>
          <Card id="lots" label="Lot rows" expandable data-testid="b">
            b
          </Card>
        </CardGrid>
      </MemoryRouter>,
    );

    const a = screen.getByTestId("a");
    const b = screen.getByTestId("b");
    expect(screen.getByTestId("url").textContent).toBe("");

    fireEvent.click(within(a).getByRole("button", { name: "Expand" }));

    expect(a.className).toContain("expanded");
    expect(b.className).not.toContain("expanded");
    expect(screen.getByTestId("url").textContent).toBe("?card=holdings");

    fireEvent.click(within(b).getByRole("button", { name: "Expand" }));

    // Two full-width cards would defeat the grid, so opening one closes the other.
    expect(b.className).toContain("expanded");
    expect(a.className).not.toContain("expanded");
    expect(screen.getByTestId("url").textContent).toBe("?card=lots");

    fireEvent.click(within(b).getByRole("button", { name: "Collapse" }));

    expect(b.className).not.toContain("expanded");
    // Collapsing back to the default leaves a clean URL rather than `?card=` forever after.
    expect(screen.getByTestId("url").textContent).toBe("");
  });

  it("restores the expanded card from the URL on first render", () => {
    render(
      <MemoryRouter initialEntries={["/account?card=lots"]}>
        <CardGrid>
          <Card id="holdings" label="Holdings rows" expandable data-testid="a">
            a
          </Card>
          <Card id="lots" label="Lot rows" expandable data-testid="b">
            b
          </Card>
        </CardGrid>
      </MemoryRouter>,
    );

    expect(screen.getByTestId("b").className).toContain("expanded");
    expect(screen.getByTestId("a").className).not.toContain("expanded");
    expect(within(screen.getByTestId("b")).getByRole("button", { name: "Collapse" })).toBeTruthy();
  });

  it("leaves other query params alone", () => {
    render(
      <MemoryRouter initialEntries={["/account?view=lots&account=rh"]}>
        <UrlProbe />
        <CardGrid>
          <Card id="holdings" label="Holdings rows" expandable data-testid="a">
            a
          </Card>
        </CardGrid>
      </MemoryRouter>,
    );

    fireEvent.click(within(screen.getByTestId("a")).getByRole("button", { name: "Expand" }));

    const search = screen.getByTestId("url").textContent ?? "";
    expect(search).toContain("view=lots");
    expect(search).toContain("account=rh");
    expect(search).toContain("card=holdings");
  });

  it("still expands with no router in the tree, falling back to local state", () => {
    // `useUrlState` -> `useSearchParams` throws outside a router. A grid that cannot render in a
    // bare `render()` is one no other component's test can contain.
    render(
      <CardGrid data-testid="g">
        <Card id="holdings" label="Holdings rows" expandable data-testid="a">
          a
        </Card>
        <Card id="lots" label="Lot rows" expandable data-testid="b">
          b
        </Card>
      </CardGrid>,
    );

    const a = screen.getByTestId("a");
    const b = screen.getByTestId("b");

    fireEvent.click(within(a).getByRole("button", { name: "Expand" }));
    expect(a.className).toContain("expanded");

    fireEvent.click(within(b).getByRole("button", { name: "Expand" }));
    expect(b.className).toContain("expanded");
    expect(a.className).not.toContain("expanded");
  });

  it("gives a card with no id private expansion, not a shared empty key", () => {
    render(
      <MemoryRouter>
        <UrlProbe />
        <CardGrid>
          <Card label="Holdings rows" expandable data-testid="a">
            a
          </Card>
          <Card label="Lot rows" expandable data-testid="b">
            b
          </Card>
        </CardGrid>
      </MemoryRouter>,
    );

    fireEvent.click(within(screen.getByTestId("a")).getByRole("button", { name: "Expand" }));
    fireEvent.click(within(screen.getByTestId("b")).getByRole("button", { name: "Expand" }));

    // Nothing to identify them by means nothing to coordinate on; both stay open and the URL is
    // untouched, rather than the two of them fighting over `?card=`.
    expect(screen.getByTestId("a").className).toContain("expanded");
    expect(screen.getByTestId("b").className).toContain("expanded");
    expect(screen.getByTestId("url").textContent).toBe("");
  });
});

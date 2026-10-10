/**
 * `Filers.tsx`'s own job, and only that job: the shared banner, the two-item tab rail, `useUrlState`
 * wiring, and mounting exactly one of the two tab bodies at a time.
 *
 * `InstitutionsView`/`ConsensusView` are mocked at the module boundary, the same technique
 * `Institutions.test.tsx` already uses for `HoldingsPieChart`/`RecentMoves`: this file's
 * responsibility is proving `Filers.tsx` wires the right tab to the right view and to the URL, not
 * re-testing either view's own fetch/phase machine -- that already has its own coverage in
 * `Institutions.test.tsx` and `Consensus.test.tsx`, both still green and unchanged in shape by this
 * merge (see those two files).
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/pages/Institutions", () => ({
  InstitutionsView: () => <div data-testid="institutions-view">institutions view</div>,
}));

vi.mock("@/pages/Consensus", () => ({
  ConsensusView: () => <div data-testid="consensus-view">consensus view</div>,
}));

const { default: Filers } = await import("@/pages/Filers");

function renderFilers(initialEntry = "/filers") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Filers />
    </MemoryRouter>,
  );
}

describe("Filers banner", () => {
  it("titles the page with the same word the nav entry uses", () => {
    renderFilers();
    // The heading is `nav.page./filers.label` -- the string the sidebar link carries -- not a join
    // of the two tab titles. A reader who clicks "Filers" and lands on a page headed something
    // else has no confirmation the click did what they asked.
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Filers");
  });

  it("keeps the two old page titles as the tab names", () => {
    renderFilers();
    expect(screen.getByRole("tab", { name: "Institutions" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Consensus" })).toBeTruthy();
  });

  it("wires each tab to the panel holding the active view", () => {
    renderFilers();
    const panel = screen.getByRole("tabpanel");
    const selected = screen
      .getAllByRole("tab")
      .find((tab) => tab.getAttribute("aria-selected") === "true");
    expect(selected).toBeTruthy();
    // Both directions: the tab points at the panel, the panel names itself by the tab.
    expect(selected?.getAttribute("aria-controls")).toBe(panel.getAttribute("id"));
    expect(panel.getAttribute("aria-labelledby")).toBe(selected?.getAttribute("id"));
    expect(panel.contains(screen.getByTestId("institutions-view"))).toBe(true);
  });

  it("renders exactly one tablist with two tabs", () => {
    renderFilers();
    const tablist = screen.getByRole("tablist");
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(2);
    expect(tabs.every((tab) => tablist.contains(tab))).toBe(true);
  });
});

describe("Filers tab switching", () => {
  it("mounts InstitutionsView, not ConsensusView, by default", () => {
    renderFilers();
    expect(screen.getByTestId("institutions-view")).toBeTruthy();
    expect(screen.queryByTestId("consensus-view")).toBeNull();
  });

  it("switches to ConsensusView on click, unmounting InstitutionsView", () => {
    renderFilers();
    fireEvent.click(screen.getByRole("tab", { name: /consensus/i }));
    expect(screen.getByTestId("consensus-view")).toBeTruthy();
    expect(screen.queryByTestId("institutions-view")).toBeNull();
  });

  it("switching back to Institutions unmounts ConsensusView again", () => {
    renderFilers();
    fireEvent.click(screen.getByRole("tab", { name: /consensus/i }));
    fireEvent.click(screen.getByRole("tab", { name: /institutions/i }));
    expect(screen.getByTestId("institutions-view")).toBeTruthy();
    expect(screen.queryByTestId("consensus-view")).toBeNull();
  });

  it("opens directly on the Consensus tab when the URL already says so", () => {
    renderFilers("/filers?tab=consensus");
    expect(screen.getByTestId("consensus-view")).toBeTruthy();
    expect(screen.queryByTestId("institutions-view")).toBeNull();
    expect(screen.getByRole("tab", { name: /consensus/i }).getAttribute("aria-selected")).toBe(
      "true",
    );
  });

  it("falls back to the Institutions tab for an unrecognised ?tab= value rather than rendering neither view", () => {
    renderFilers("/filers?tab=not-a-real-tab");
    expect(screen.getByTestId("institutions-view")).toBeTruthy();
    expect(screen.queryByTestId("consensus-view")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// This page is where the `?tab=` pattern started, and its logic is what `useTabParam` lifted out.
// The deep-link and fallback cases are covered above; what was missing is the other direction --
// that a tab CLICK rewrites the URL, which is what makes the view linkable and Back-able rather
// than merely reachable by hand-typing a query string.
// ---------------------------------------------------------------------------

/** Shows the current route's path + query, so a test can assert the tab landed in the URL. */
function FilersLocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname + location.search}</div>;
}

describe("Filers tab in the URL", () => {
  it("clicking a tab puts it in the URL", () => {
    render(
      <MemoryRouter initialEntries={["/filers"]}>
        <FilersLocationProbe />
        <Filers />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("location-probe").textContent).not.toContain("tab=");

    fireEvent.click(screen.getByRole("tab", { name: "Consensus" }));

    expect(screen.getByTestId("location-probe").textContent).toContain("tab=consensus");
    expect(screen.getByTestId("consensus-view")).toBeTruthy();
  });

  it("preserves another query param already on the URL across a tab click", () => {
    render(
      <MemoryRouter initialEntries={["/filers?cik=0001067983"]}>
        <FilersLocationProbe />
        <Filers />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Consensus" }));

    const url = screen.getByTestId("location-probe").textContent ?? "";
    expect(url).toContain("tab=consensus");
    // A `setSearchParams({ tab })` would have dropped this.
    expect(url).toContain("cik=0001067983");
  });
});

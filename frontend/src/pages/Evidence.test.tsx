/**
 * Evidence: the tab shell over Backtest, Timeframes, Rules and Thesis.
 *
 * The three tabbed pages are the real components, not stubs -- the whole point of this page is that
 * they render unchanged -- so their own network calls need stubbing here exactly as their own test
 * files stub them: `@/api/rules` (`Rules.tsx` and `Timeframes.tsx`'s header/table share nothing here,
 * but `rulesApi.catalog` backs `Rules.tsx`) and `@/api/timeframes` (`Timeframes.tsx`'s matrix/
 * universe fetches). `Backtest.tsx` renders its four sections only once a symbol is submitted, so
 * with no symbol touched here it fetches nothing and needs no stub, matching `Backtest.test.tsx`.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Rule } from "@/api/rules";
import type { MatrixQuery, MatrixResponse, UniverseEntry } from "@/api/timeframes";

const catalogMock = vi.fn<() => Promise<Rule[]>>();
const matrixMock = vi.fn<(params: MatrixQuery) => Promise<MatrixResponse>>();
const universeMock = vi.fn<() => Promise<UniverseEntry[]>>();

vi.mock("@/api/rules", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/rules")>();
  return { ...actual, rulesApi: { ...actual.rulesApi, catalog: () => catalogMock() } };
});

vi.mock("@/api/timeframes", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/timeframes")>();
  return {
    ...actual,
    timeframesApi: {
      ...actual.timeframesApi,
      matrix: (params: MatrixQuery) => matrixMock(params),
      universe: () => universeMock(),
    },
  };
});

const { default: Evidence } = await import("@/pages/Evidence");

/** Shows the current route's query string, so a test can assert the tab reached the URL without
 *  reaching into the router's internals. Same device `Tax.test.tsx` uses for its own rail. */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname + location.search}</div>;
}

/** The tab now lives in `?tab=`, so a test whose assertions are on a non-default tab lands there the
 *  way a bookmark or the `/thesis/:symbol?` redirect would, rather than clicking to it. */
function renderPage(initialPath = "/evidence") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <LocationProbe />
      <Evidence />
    </MemoryRouter>,
  );
}

afterEach(() => {
  catalogMock.mockReset();
  matrixMock.mockReset();
  universeMock.mockReset();
});

describe("Evidence", () => {
  it("renders the four tabs, defaulting to Backtest, with no duplicate wrapper heading", () => {
    renderPage();

    // The wrapper itself renders no heading/subtitle any more -- only the tab strip, plus whichever
    // child page is active. "Evidence" was the wrapper's own (now-removed) title, so it must not
    // appear; "Backtest" below is the active child's own heading.
    expect(screen.queryByRole("heading", { level: 1, name: "Evidence" })).toBeNull();

    const tablist = screen.getByRole("tablist", { name: "Evidence view" });
    const tabs = within(tablist).getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      "Backtest",
      "Across intervals",
      "Rules",
      "Thesis",
    ]);

    const backtestTab = within(tablist).getByRole("tab", { name: "Backtest" });
    expect(backtestTab.getAttribute("aria-selected")).toBe("true");

    // The Backtest page itself is showing -- its own symbol form, unmodified. Its heading is
    // DEMOTED to `<h2>` by `embedded` (A11Y-02): this page already renders the document's one
    // `<h1>` ("Evidence") above, and a tab body that also claims `<h1>` gives a screen reader's
    // heading list two top-level documents on one page. `/backtest` still gets its own `<h1>`.
    expect(screen.getByRole("heading", { level: 2, name: "Backtest" })).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 1, name: "Backtest" })).toBeNull();
    expect(screen.getByRole("textbox", { name: "Symbol" })).toBeTruthy();
  });

  it("switching to Rules shows the rule-catalogue heading", async () => {
    catalogMock.mockResolvedValue([]);

    renderPage();

    fireEvent.click(screen.getByRole("tab", { name: "Rules" }));

    expect(screen.getByRole("tab", { name: "Rules" }).getAttribute("aria-selected")).toBe("true");
    // `Rules.tsx`'s own heading, DEMOTED to `<h2>` by `embedded`: this page already renders the
    // document's one `<h1>` ("Evidence"), and a tab body that also claims `<h1>` gives a screen
    // reader's heading list two top-level documents on one page. `/rules` still gets its `<h1>`.
    expect(screen.getByRole("heading", { level: 2, name: "Rules" })).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 1, name: "Rules" })).toBeNull();
    expect(screen.getByRole("heading", { level: 2, name: "Test a rule expression" })).toBeTruthy();
    await waitFor(() => expect(catalogMock).toHaveBeenCalled());
  });

  it("switching to Across intervals shows the Timeframes matrix heading", async () => {
    matrixMock.mockResolvedValue({
      cells: [],
      generated_at: "2026-09-05T00:00:00Z",
      coverage: { symbols: 1, intervals: 7, rules: 0, cells_total: 0, cells_sufficient: 0 },
      warnings: [],
    });
    universeMock.mockResolvedValue([]);

    renderPage();

    fireEvent.click(screen.getByRole("tab", { name: "Across intervals" }));

    expect(screen.getByRole("tab", { name: "Across intervals" }).getAttribute("aria-selected")).toBe(
      "true",
    );
    // Demoted to `<h2>` by `embedded`, same reason as the Rules tab above.
    expect(screen.getByRole("heading", { level: 2, name: "Timeframes" })).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 1, name: "Timeframes" })).toBeNull();
    await waitFor(() => expect(matrixMock).toHaveBeenCalled());
  });
});

/**
 * Thesis, folded in from its own former nav entry and route.
 *
 * `/thesis/:symbol?` redirects here carrying `?tab=thesis&symbol=…` (see `App.test.tsx`), so what
 * this page has to hold up its end of is: the tab is addressable by query string, and the symbol is
 * read from one too. The empty prompt is what renders with no symbol, and it fetches nothing --
 * which is also why running the loop is still exactly as far away as it was before the fold: behind
 * a symbol, and then behind the Run button and its warning.
 */
describe("Evidence: the Thesis tab", () => {
  it("opens directly on Thesis from ?tab=thesis, showing the symbol prompt", () => {
    renderPage("/evidence?tab=thesis");

    expect(screen.getByRole("tab", { name: "Thesis" }).getAttribute("aria-selected")).toBe("true");
    // The empty prompt, since no `?symbol=` came with it -- and no run control, because there is no
    // symbol to run against yet.
    expect(screen.getByRole("textbox", { name: "Symbol" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Run the loop/ })).toBeNull();
  });

  it("keeps the symbol out of the way of the tab, and vice versa", () => {
    // Two independent `useUrlState` keys on one page: switching tabs must not drop `?symbol=`, which
    // is the failure mode a naive `setSearchParams({ tab })` would produce.
    renderPage("/evidence?tab=thesis&symbol=NVDA");

    expect(screen.getByRole("tab", { name: "Thesis" }).getAttribute("aria-selected")).toBe("true");
    // The detail view, not the prompt: the symbol names the section.
    expect(screen.getByRole("heading", { level: 2, name: "NVDA" })).toBeTruthy();
  });

  it("switching to Thesis by click selects it without a route change", () => {
    renderPage();

    fireEvent.click(screen.getByRole("tab", { name: "Thesis" }));

    expect(screen.getByRole("tab", { name: "Thesis" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tab", { name: "Backtest" }).getAttribute("aria-selected")).toBe("false");
  });
});

// ---------------------------------------------------------------------------
// The tab in the URL (finding UX-11). Before this, the active tab was a plain `useState`: the
// three tools were not linkable, a reload threw the reader back to Backtest, and six tab clicks
// pushed nothing onto the history stack, so Back left the page rather than walking the tabs.
// ---------------------------------------------------------------------------
describe("Evidence tab in the URL", () => {
  it("opens directly on Rules when the initial URL already says so", async () => {
    catalogMock.mockResolvedValue([]);

    renderPage("/evidence?tab=rules");

    expect(screen.getByRole("tab", { name: "Rules" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("heading", { level: 2, name: "Rules" })).toBeTruthy();
    // Backtest's own symbol form is NOT mounted -- the deep link opened the tab, it did not merely
    // scroll to it.
    expect(screen.queryByRole("textbox", { name: "Symbol" })).toBeNull();
    await waitFor(() => expect(catalogMock).toHaveBeenCalled());
  });

  it("opens directly on Across intervals when the initial URL says so", async () => {
    matrixMock.mockResolvedValue({
      cells: [],
      generated_at: "2026-09-05T00:00:00Z",
      coverage: { symbols: 1, intervals: 7, rules: 0, cells_total: 0, cells_sufficient: 0 },
      warnings: [],
    });
    universeMock.mockResolvedValue([]);

    renderPage("/evidence?tab=timeframes");

    expect(screen.getByRole("tab", { name: "Across intervals" }).getAttribute("aria-selected")).toBe(
      "true",
    );
    await waitFor(() => expect(matrixMock).toHaveBeenCalled());
  });

  it("clicking a tab puts it in the URL, so the view can be linked to", async () => {
    catalogMock.mockResolvedValue([]);

    renderPage();
    expect(screen.getByTestId("location-probe").textContent).not.toContain("tab=");

    fireEvent.click(screen.getByRole("tab", { name: "Rules" }));

    expect(screen.getByTestId("location-probe").textContent).toContain("tab=rules");
    await waitFor(() => expect(catalogMock).toHaveBeenCalled());
  });

  it("falls back to Backtest for an unrecognised ?tab= value rather than rendering no tab body", () => {
    // A bookmark from before a tab was renamed, or a hand-edited query string. The page must open
    // on its default, not hand `"nonsense"` to the `tab === ...` guards and render an empty shell.
    renderPage("/evidence?tab=nonsense");

    expect(screen.getByRole("tab", { name: "Backtest" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("textbox", { name: "Symbol" })).toBeTruthy();
  });
});

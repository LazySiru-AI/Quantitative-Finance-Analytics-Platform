/**
 * The navigation shell: two levels, and the invariants that keep them honest.
 *
 * The first test in this repo to touch the nav at all. It exists because the nav now has two
 * sources of coupling it did not have as a flat list -- `NAV` against the `<Route>` table, and
 * `NAV` against `NotFound`'s destination list -- and the second of those pairs had already drifted
 * silently once: the 404 named nine pages when the app had thirteen, so four were unreachable from
 * the page whose entire job is telling someone where to go.
 *
 * Every page component is stubbed. These tests are about routing and section derivation; letting
 * the real pages mount would pull in every API module and make a nav test fail for reasons that
 * have nothing to do with the nav.
 */
import type { ReactNode } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "@/App";
import type { AuthValue } from "@/auth";
import { FAVORITES_STORAGE_KEY, refreshFavoritesFromStorage } from "@/favorites";
import { NAV, NAV_ITEMS, sectionForPath } from "@/nav";
import { refreshPrivacyFromStorage } from "@/privacy";

// Each stub renders its own name, so a test can assert which page is showing without depending
// on anything inside the real component. The factories are written out one by one rather than
// built from a helper: `vi.mock` is hoisted above every top-level binding in this file, so a
// shared `stub()` would not exist yet when the factory runs.
vi.mock("@/pages/Overview", () => ({ default: () => <div data-testid="page">Overview</div> }));
vi.mock("@/pages/Portfolio", () => ({ default: () => <div data-testid="page">Portfolio</div> }));
vi.mock("@/pages/Designer", () => ({ default: () => <div data-testid="page">Designer</div> }));
vi.mock("@/pages/PaperDesk", () => ({ default: () => <div data-testid="page">PaperDesk</div> }));
vi.mock("@/pages/Activity", () => ({ default: () => <div data-testid="page">Activity</div> }));
vi.mock("@/pages/Tax", () => ({ default: () => <div data-testid="page">Tax</div> }));
vi.mock("@/pages/Competition", () => ({ default: () => <div data-testid="page">Competition</div> }));
vi.mock("@/pages/Evidence", () => ({ default: () => <div data-testid="page">Evidence</div> }));
vi.mock("@/pages/Backtest", () => ({ default: () => <div data-testid="page">Backtest</div> }));
vi.mock("@/pages/StrategyLanding", () => ({
  default: () => <div data-testid="page">StrategyLanding</div>,
}));
vi.mock("@/pages/Rules", () => ({ default: () => <div data-testid="page">Rules</div> }));
vi.mock("@/pages/Symbol", () => ({ default: () => <div data-testid="page">Symbol</div> }));
vi.mock("@/pages/Filers", () => ({ default: () => <div data-testid="page">Filers</div> }));
vi.mock("@/pages/Data", () => ({ default: () => <div data-testid="page">Data</div> }));
vi.mock("@/pages/Macro", () => ({ default: () => <div data-testid="page">Macro</div> }));
vi.mock("@/pages/Timeframes", () => ({ default: () => <div data-testid="page">Timeframes</div> }));
vi.mock("@/pages/AgentDeskLanding", () => ({
  default: () => <div data-testid="page">AgentDeskLanding</div>,
}));
vi.mock("@/pages/ResearchDesk", () => ({ default: () => <div data-testid="page">ResearchDesk</div> }));
vi.mock("@/pages/TradingAgents", () => ({ default: () => <div data-testid="page">TradingAgents</div> }));
vi.mock("@/pages/VibeTrading", () => ({ default: () => <div data-testid="page">VibeTrading</div> }));
vi.mock("@/pages/AgentWorkflow", () => ({ default: () => <div data-testid="page">AgentWorkflow</div> }));
vi.mock("@/pages/Manager", () => ({ default: () => <div data-testid="page">Manager</div> }));
vi.mock("@/pages/Personas", () => ({ default: () => <div data-testid="page">Personas</div> }));
vi.mock("@/pages/personas/PersonaDetail", () => ({
  default: () => <div data-testid="page">PersonaDetail</div>,
}));

// Auth is stubbed to a signed-in user so these nav tests run synchronously against the dashboard.
// The real provider fetches `/api/auth/me` on mount, which would leave the app on its loading line
// (the test setup's fetch stub throws), and gating is exercised by the auth suite, not here.
// Owner by default -- these nav tests predate roles and assert the full nav (every owner-only
// destination included). The member-hides-owner-only-entries behavior gets its own `describe`
// below, which points `mockUseAuth` at `MEMBER_AUTH` for the duration of each of its tests; the
// shared `beforeEach` further down points it back at `OWNER_AUTH` so that override never leaks
// into an unrelated test.
const OWNER_AUTH: AuthValue = {
  status: "authed",
  username: "tester",
  authEnabled: true,
  role: "owner",
  isOwner: true,
  refresh: async () => {},
  onSignedIn: () => {},
  signOut: async () => {},
};
const MEMBER_AUTH: AuthValue = { ...OWNER_AUTH, username: "member", role: "member", isOwner: false };
const mockUseAuth = vi.fn<() => AuthValue>(() => OWNER_AUTH);

vi.mock("@/auth", () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => children,
  useAuth: () => mockUseAuth(),
}));

/** Sections are looked up by id, never by index. `NAV[1]` was how this file used to name Strategy
 *  Lab, and inserting the Overview section at the front silently repointed it at Portfolio -- the
 *  assertion still passed for a while because both sections happened to have five items. */
function section(id: string) {
  const found = NAV.find((s) => s.id === id);
  if (!found) throw new Error(`no NAV section with id ${id}`);
  return found;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

/** The level-1 rail. Queried by its container class because section links and page links are both
 *  plain anchors, and several share a label -- "Account" is both a section and a page. */
function sectionRail() {
  const rail = document.querySelector(".nav-sections");
  if (!rail) throw new Error("no .nav-sections rail rendered");
  return within(rail as HTMLElement);
}

function pageRail() {
  const rail = document.querySelector(".nav");
  if (!rail) throw new Error("no .nav rail rendered");
  return within(rail as HTMLElement);
}

/** The favourites section, queried the same way as the other two rails and for the same reason:
 *  a favourited page's label and star `aria-label` both appear a second time in `.nav`, so an
 *  unscoped query throws on the ambiguity rather than picking the "wrong" one. */
function favoritesRail() {
  const rail = document.querySelector(".nav-favorites");
  if (!rail) throw new Error("no .nav-favorites rail rendered");
  return within(rail as HTMLElement);
}

// The favourites store is module-level state (see `favorites.ts`), so it outlives any one test in
// this file unless it is reset. Without this, a star clicked in one test is still pressed at the
// start of the next.
beforeEach(() => {
  window.localStorage.clear();
  refreshFavoritesFromStorage();
  // Privacy mode is module-level state too, and it writes to `<html>` -- left un-reset, a test that
  // hides amounts leaves every later test rendering into a redacted document.
  refreshPrivacyFromStorage();
  mockUseAuth.mockImplementation(() => OWNER_AUTH);
});

describe("every nav destination is routed", () => {
  // Guards the drift that matters most: a page added to `NAV` without a `<Route>`, or a route
  // renamed without updating `NAV`. Either shows the 404 -- which is a real page, so nothing else
  // in the app would have failed.
  it.each(NAV_ITEMS.map((item) => [item.to, item.label] as const))(
    "%s (%s) renders a page, not the 404",
    (to) => {
      renderAt(to);
      expect(screen.queryByText("Not found")).toBeNull();
      expect(screen.getByTestId("page")).toBeTruthy();
    },
  );

  // `/personas/:slug` is deliberately not in `NAV` -- reachable only by following a link off
  // `/personas`, same as `/ticker/:symbol` and `/report/:symbol?` -- so it is not covered by the
  // loop above and needs its own assertion that the route is actually wired up.
  it("/personas/:slug renders PersonaDetail, not the 404", () => {
    renderAt("/personas/creator-a");
    expect(screen.queryByText("Not found")).toBeNull();
    expect(screen.getByTestId("page").textContent).toBe("PersonaDetail");
  });
});

describe("the active section is derived from the URL", () => {
  it("opens a deep link with the right section already expanded", () => {
    renderAt("/tax");

    // Tax is under the Account section, so the Account pill is active and the page rail shows
    // Account's pages -- not Strategy Lab's, and not all thirteen.
    expect(sectionRail().getByText("Account").className).toContain("active");
    expect(pageRail().getByText("Activity")).toBeTruthy();
    expect(pageRail().queryByText("Competition")).toBeNull();
  });

  it("matches a path carrying a symbol parameter", () => {
    // The case an equality check would miss. `/symbol/AAPL` is where the Symbol jump and the legacy
    // `/ticker/AAPL` links land; arriving there must open the Market section, not fall back.
    renderAt("/symbol/AAPL");

    expect(sectionForPath("/symbol/AAPL").id).toBe("market");
    expect(sectionRail().getByText("Market").className).toContain("active");
    expect(pageRail().getByText("Macro")).toBeTruthy();
  });

  it("redirects a legacy /ticker/:symbol link into the Symbol page under Market", () => {
    // Ticker merged into Symbol; the old path still resolves via a redirect, and the redirect target
    // must open with Market expanded (the whole point of preserving the link).
    renderAt("/ticker/AAPL");

    expect(screen.getByTestId("page").textContent).toBe("Symbol");
    expect(sectionRail().getByText("Market").className).toContain("active");
  });

  it("does not prefix-match a longer unrelated path", () => {
    // `/taxonomy` must not be swallowed by `/tax`; that is what the trailing slash in the
    // comparison is for. It has no route, so it 404s -- and falls back to the first section.
    expect(sectionForPath("/taxonomy").id).toBe(NAV[0].id);
  });

  it("shows only the active section's pages", () => {
    renderAt("/competition");

    expect(pageRail().queryAllByRole("link")).toHaveLength(section("strategy").items.length);
    expect(pageRail().queryByText("Tax")).toBeNull();
  });
});

describe("the section rail navigates", () => {
  it("takes you to that section's first page", async () => {
    const user = userEvent.setup();
    renderAt("/portfolio");

    await user.click(sectionRail().getByText("Market"));

    // Market's first item is now Symbol (Ticker + Report merged).
    expect(screen.getByTestId("page").textContent).toBe("Symbol");
    expect(sectionRail().getByText("Market").className).toContain("active");
  });

  // Strategy Lab and Agent Desk both gained a landing page as their first item -- clicking either
  // section pill used to land cold on Competition / Trading Agents respectively, with no framing at
  // all. `nav.ts`'s ordering is what these two tests actually pin.
  it("takes you to the Strategy Lab landing, not straight to Competition", async () => {
    const user = userEvent.setup();
    renderAt("/portfolio");

    await user.click(sectionRail().getByText("Strategy Lab"));

    expect(screen.getByTestId("page").textContent).toBe("StrategyLanding");
    expect(sectionRail().getByText("Strategy Lab").className).toContain("active");
  });

  it("takes you to the Agent Desk landing, not straight to Trading Agents", async () => {
    const user = userEvent.setup();
    renderAt("/portfolio");

    await user.click(sectionRail().getByText("Agent Desk"));

    expect(screen.getByTestId("page").textContent).toBe("AgentDeskLanding");
    expect(sectionRail().getByText("Agent Desk").className).toContain("active");
  });
});

describe("the shell symbol jump", () => {
  it("opens a symbol's Symbol page on submit", async () => {
    const user = userEvent.setup();
    renderAt("/overview");
    const input = screen.getByLabelText(/go to a symbol/i);
    await user.type(input, "aapl{Enter}");
    expect(screen.getByTestId("page").textContent).toBe("Symbol");
  });

  it("focuses on the / shortcut, then clears after navigating", async () => {
    const user = userEvent.setup();
    renderAt("/overview");
    await user.keyboard("/");
    const input = screen.getByLabelText(/go to a symbol/i) as HTMLInputElement;
    expect(document.activeElement).toBe(input);
    await user.type(input, "msft{Enter}");
    expect(screen.getByTestId("page").textContent).toBe("Symbol");
    expect(input.value).toBe("");
  });
});

describe("the two new section landings render at their own routes", () => {
  it("/strategy renders StrategyLanding, not the 404", () => {
    renderAt("/strategy");
    expect(screen.queryByText("Not found")).toBeNull();
    expect(screen.getByTestId("page").textContent).toBe("StrategyLanding");
  });

  it("/agents renders AgentDeskLanding, not the 404", () => {
    renderAt("/agents");
    expect(screen.queryByText("Not found")).toBeNull();
    expect(screen.getByTestId("page").textContent).toBe("AgentDeskLanding");
  });
});

/**
 * The three nav demotions. Each old top-level route still resolves -- as a redirect into the tab or
 * panel its surface now lives in -- so every bookmark, favourite and in-app link written against the
 * old path keeps working. The pages are stubbed here as everywhere else in this file, so what these
 * assert is the routing: which page component the old path lands on, and with which query string.
 * That the destination surface actually renders inside its host is each host page's own test.
 */
describe("demoted destinations still resolve from their old paths", () => {
  /** The current location, read from a probe route rendered alongside the app's own. Cheaper and
   *  more direct than inferring the query string from a stubbed page's contents. */
  function locationProbe() {
    const el = document.querySelector("[data-testid='location']");
    return el?.textContent ?? "";
  }

  function renderWithProbe(path: string) {
    function Probe() {
      const location = useLocation();
      return <span data-testid="location">{`${location.pathname}${location.search}`}</span>;
    }
    return render(
      <MemoryRouter initialEntries={[path]}>
        <Probe />
        <App />
      </MemoryRouter>,
    );
  }

  it("/wash-sales lands on the Tax page's Wash sales tab", () => {
    renderWithProbe("/wash-sales");

    expect(screen.getByTestId("page").textContent).toBe("Tax");
    expect(locationProbe()).toBe("/tax?tab=wash");
    expect(sectionRail().getByText("Account").className).toContain("active");
  });

  it("/thesis lands on Evidence's Thesis tab with no symbol", () => {
    renderWithProbe("/thesis");

    expect(screen.getByTestId("page").textContent).toBe("Evidence");
    expect(locationProbe()).toBe("/evidence?tab=thesis");
  });

  it("/thesis/:symbol carries the symbol across, upper-cased", () => {
    // The whole point of preserving this link: a bookmark to one ticker's thesis must arrive at
    // that ticker, not at the empty symbol prompt.
    renderWithProbe("/thesis/nvda");

    expect(screen.getByTestId("page").textContent).toBe("Evidence");
    expect(locationProbe()).toBe("/evidence?tab=thesis&symbol=NVDA");
    expect(sectionRail().getByText("Strategy Lab").className).toContain("active");
  });

  it("/backfill lands on the Personas page with its backfill panel open", () => {
    renderWithProbe("/backfill");

    expect(screen.getByTestId("page").textContent).toBe("Personas");
    expect(locationProbe()).toBe("/personas?panel=backfill");
    expect(sectionRail().getByText("Agent Desk").className).toContain("active");
  });

  it("drops the three demoted paths from the nav and from the 404's destination list", () => {
    // A demoted page that is still advertised in either place is a page the reader will keep
    // arriving at by the old door, which is how a redirect quietly becomes permanent.
    const paths = NAV_ITEMS.map((item) => item.to);
    expect(paths).not.toContain("/wash-sales");
    expect(paths).not.toContain("/thesis");
    expect(paths).not.toContain("/backfill");
  });
});

describe("first load and unknown paths", () => {
  it("redirects the root to the overview", () => {
    // The landing page changed from Portfolio to Overview. `/` is still a redirect rather than a
    // route of its own, so the section rail has to resolve it through `/overview`.
    renderAt("/");
    expect(screen.getByTestId("page").textContent).toBe("Overview");
    expect(sectionRail().getByText("Overview").className).toContain("active");
  });

  it("renders a real 404 that names the path", () => {
    renderAt("/nope");
    expect(screen.getByText("Not found")).toBeTruthy();
    expect(screen.getByText("/nope")).toBeTruthy();
  });

  it("offers every destination on the 404, grouped by section", () => {
    // The drift guard. `NotFound` reads `NAV` now, so this asserts the wiring rather than a list --
    // if someone reintroduces a local copy, the counts diverge here first.
    renderAt("/nope");

    const panel = document.querySelector(".panel");
    const links = within(panel as HTMLElement).getAllByRole("link");
    expect(links).toHaveLength(NAV_ITEMS.length);

    // Queried by class, not by text: "Account" is both a section heading and a page link inside
    // this panel, so a plain text query matches two elements and fails on the ambiguity.
    const headings = Array.from(
      (panel as HTMLElement).querySelectorAll(".destination-group-title"),
    ).map((h) => h.textContent);
    expect(headings).toEqual(NAV.map((section) => section.label));
  });
});

describe("favouriting a page", () => {
  it("gives every page-rail link a star, initially unpressed", () => {
    renderAt("/portfolio");

    const stars = pageRail().getAllByRole("button");
    expect(stars).toHaveLength(section("portfolio").items.length);
    for (const star of stars) {
      expect(star.getAttribute("aria-pressed")).toBe("false");
    }
  });

  it("adds the page to .nav-favorites immediately, without navigating away", async () => {
    const user = userEvent.setup();
    renderAt("/macro");

    await user.click(pageRail().getByRole("button", { name: "Add Macro to favorites" }));

    expect(favoritesRail().getByText("Macro")).toBeTruthy();
    // Still on Macro: starring is not navigation.
    expect(screen.getByTestId("page").textContent).toBe("Macro");
  });

  it("removes the page from .nav-favorites on a second click", async () => {
    const user = userEvent.setup();
    renderAt("/macro");

    const star = pageRail().getByRole("button", { name: "Add Macro to favorites" });
    await user.click(star);
    expect(favoritesRail().getByText("Macro")).toBeTruthy();

    await user.click(pageRail().getByRole("button", { name: "Remove Macro from favorites" }));

    expect(favoritesRail().queryByText("Macro")).toBeNull();
    expect(favoritesRail().getByText("Star a page to pin it here.")).toBeTruthy();
  });

  it("keeps a favourite from another section visible after navigating away from it", async () => {
    const user = userEvent.setup();
    renderAt("/macro");

    await user.click(pageRail().getByRole("button", { name: "Add Macro to favorites" }));

    // Market's own page rail is gone the moment the section changes, but the favourite persists.
    // Strategy Lab's first item is now its landing, not Competition -- see `nav.ts`.
    await user.click(sectionRail().getByText("Strategy Lab"));

    expect(screen.getByTestId("page").textContent).toBe("StrategyLanding");
    expect(pageRail().queryByText("Macro")).toBeNull();
    expect(favoritesRail().getByText("Macro")).toBeTruthy();
  });

  it("shows a seeded favourite after a remount", () => {
    window.localStorage.setItem(FAVORITES_STORAGE_KEY, JSON.stringify(["/macro"]));
    refreshFavoritesFromStorage();

    renderAt("/portfolio");

    expect(favoritesRail().getByText("Macro")).toBeTruthy();
  });

  it("renders the empty state when nothing is favourited", () => {
    renderAt("/portfolio");

    expect(favoritesRail().getByText("Star a page to pin it here.")).toBeTruthy();
  });

  it("can be un-starred from within the favourites section itself", async () => {
    const user = userEvent.setup();
    renderAt("/macro");

    await user.click(pageRail().getByRole("button", { name: "Add Macro to favorites" }));
    await user.click(sectionRail().getByText("Strategy Lab"));

    // Now on the Strategy Lab landing, so "Macro" only appears once -- inside .nav-favorites -- and
    // its own star button lives there too.
    await user.click(favoritesRail().getByRole("button", { name: "Remove Macro from favorites" }));

    expect(favoritesRail().queryByText("Macro")).toBeNull();
    expect(favoritesRail().getByText("Star a page to pin it here.")).toBeTruthy();
  });
});

describe("a member does not see owner-only destinations", () => {
  it("hides owner-only entries from the page rail, keeping the rest of the section", () => {
    mockUseAuth.mockImplementation(() => MEMBER_AUTH);
    renderAt("/paper-desk");

    // Portfolio's owner-only pages -- Account, Activity, Tax -- are all gone; Paper Desk, which
    // reads no owner-only prefix, stays.
    expect(pageRail().queryByText("Account")).toBeNull();
    expect(pageRail().queryByText("Activity")).toBeNull();
    expect(pageRail().queryByText("Tax")).toBeNull();
    expect(pageRail().getByText("Paper Desk")).toBeTruthy();
  });

  it("shows every owner-only entry for the owner (unchanged behavior)", () => {
    renderAt("/paper-desk");

    expect(pageRail().getByText("Account")).toBeTruthy();
    expect(pageRail().getByText("Activity")).toBeTruthy();
    expect(pageRail().getByText("Tax")).toBeTruthy();
  });

  // Manager reads across the owner-only holdings and tax prefixes, so it belongs on the same list
  // as Tax -- it was the one route that read them while being neither gated nor hidden.
  it("hides Manager from the Agent Desk rail for a member, keeping the rest of the section", () => {
    mockUseAuth.mockImplementation(() => MEMBER_AUTH);
    renderAt("/agents");

    expect(pageRail().queryByText("Manager")).toBeNull();
    expect(pageRail().getByText("Research Desk")).toBeTruthy();
  });

  it("shows Manager in the Agent Desk rail for the owner", () => {
    renderAt("/agents");

    expect(pageRail().getByText("Manager")).toBeTruthy();
  });

  it("renders the owner-only notice instead of the Manager page for a member", () => {
    mockUseAuth.mockImplementation(() => MEMBER_AUTH);
    renderAt("/manager");

    // The mocked Manager stub never mounts -- the desk's owner-only fetches never fire.
    expect(screen.queryByTestId("page")).toBeNull();
    expect(
      screen.getByText("This section is available to the owner account only."),
    ).toBeTruthy();
  });

  it("still renders Manager at the same route for the owner", () => {
    renderAt("/manager");

    expect(screen.getByTestId("page").textContent).toBe("Manager");
  });

  it("renders an inline notice instead of the page on a deep link to an owner-only route", () => {
    mockUseAuth.mockImplementation(() => MEMBER_AUTH);
    renderAt("/tax");

    // The mocked Tax stub never mounts -- no 403 ever reaches it.
    expect(screen.queryByTestId("page")).toBeNull();
    expect(
      screen.getByText("This section is available to the owner account only."),
    ).toBeTruthy();
  });

  it("still renders the real page at the same route for the owner", () => {
    renderAt("/tax");

    expect(screen.getByTestId("page").textContent).toBe("Tax");
    expect(
      screen.queryByText("This section is available to the owner account only."),
    ).toBeNull();
  });

  it("drops a favourited owner-only page from .nav-favorites for a member", () => {
    // Seeded as if starred while signed in as the owner, or before a demotion -- the storage key is
    // shared across accounts on one browser profile.
    window.localStorage.setItem(FAVORITES_STORAGE_KEY, JSON.stringify(["/tax", "/macro"]));
    refreshFavoritesFromStorage();
    mockUseAuth.mockImplementation(() => MEMBER_AUTH);

    renderAt("/paper-desk");

    expect(favoritesRail().queryByText("Tax")).toBeNull();
    expect(favoritesRail().getByText("Macro")).toBeTruthy();
  });
});

/**
 * The shell's accessibility contract.
 *
 * These are the four things a keyboard or screen-reader user meets before any page does: a way past
 * the sidebar, a `<main>` that can actually receive focus, three named rails instead of three
 * anonymous ones, and -- when the login gate is off -- something on screen that says so.
 */
describe("the shell is navigable without a mouse", () => {
  it("puts the skip link first in the tab order", async () => {
    const user = userEvent.setup();
    renderAt("/overview");

    await user.tab();

    const focused = document.activeElement as HTMLElement;
    expect(focused.tagName).toBe("A");
    expect(focused.textContent).toBe("Skip to content");
    expect(focused.getAttribute("href")).toBe("#content");
  });

  it("targets a <main> that can take focus", () => {
    renderAt("/overview");

    const link = screen.getByRole("link", { name: "Skip to content" });
    const href = link.getAttribute("href") ?? "";
    expect(href.startsWith("#")).toBe(true);

    const target = document.getElementById(href.slice(1));
    expect(target).not.toBeNull();
    expect(target?.tagName).toBe("MAIN");
    // Without `tabindex="-1"` the jump scrolls but leaves focus in the sidebar, so the next Tab
    // lands back on the second nav link and the skip link looks broken.
    expect(target?.getAttribute("tabindex")).toBe("-1");
  });

  it("names all three nav rails", () => {
    renderAt("/overview");

    const rails = screen.getAllByRole("navigation");
    expect(rails.map((rail) => rail.getAttribute("aria-label"))).toEqual([
      "Sections",
      "Pages",
      "Favorites",
    ]);
  });

  it("does not wrap the rails in a fourth, unnamed navigation landmark", () => {
    renderAt("/overview");

    // The sidebar container is a `<div>`: an outer landmark with no name would put a screen
    // reader's landmark list back to "navigation, navigation, navigation, navigation".
    expect(document.querySelector(".sidebar")?.tagName).toBe("DIV");
    expect(screen.getAllByRole("navigation")).toHaveLength(3);
  });
});

describe("privacy mode", () => {
  it("flips data-redact on the document element from the sidebar", async () => {
    const user = userEvent.setup();
    renderAt("/overview");

    expect(document.documentElement.dataset["redact"]).not.toBe("on");
    await user.click(screen.getByRole("button", { name: "Hide amounts" }));
    expect(document.documentElement.dataset["redact"]).toBe("on");

    await user.click(screen.getByRole("button", { name: "Show amounts" }));
    expect(document.documentElement.dataset["redact"]).not.toBe("on");
  });

  it("marks the signed-in username as redactable", () => {
    renderAt("/overview");

    const user = document.querySelector(".nav-account-user");
    expect(user).not.toBeNull();
    // The class is the contract with `styles.css`: a username on a shared screen is the one thing
    // in the shell that says whose money is on it.
    expect(user?.className).toContain("redactable");
  });
});

describe("the login gate's own state is visible", () => {
  it("shows a warning pill in the footer when auth is disabled", () => {
    mockUseAuth.mockImplementation(() => ({
      ...OWNER_AUTH,
      authEnabled: false,
      username: null,
    }));
    renderAt("/overview");

    const pill = screen.getByTestId("auth-gate-off");
    expect(pill.textContent).toBe("Login off");
    expect(pill.className).toContain("status-pill-warn");
    expect(pill.getAttribute("title")).toBe(
      "Every route is open; the server must stay on loopback.",
    );
    // No account footer to sign out of -- that is exactly the state the pill is announcing.
    expect(screen.queryByText("Sign out")).toBeNull();
  });

  it("shows the account footer and no pill when auth is on", () => {
    renderAt("/overview");

    expect(screen.queryByTestId("auth-gate-off")).toBeNull();
    expect(screen.getByText("Sign out")).toBeTruthy();
  });
});

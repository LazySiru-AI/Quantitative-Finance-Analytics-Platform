/**
 * Smoke test for Macro.tsx's `FolderTabs` rail: the page renders a tablist with all six sections
 * (Fear & Greed, Key indicators, Rates, Oil, Movers, News), only the active tab's content is mounted,
 * clicking a tab writes it into the URL, and a `MarketWarning.kind` shows as a translated
 * `StatusPill`, never as the raw wire token.
 *
 * `FearGreedGauge`, `MacroKeyIndicators` and `MacroNewsPanel` are mocked to a one-line marker --
 * they are components/*, out of this page's scope, and this file only needs to prove Macro.tsx
 * still mounts each of them inside its own tab, not re-test their own internals (which already have
 * their own test files). `Rates`/`Oil`/`Movers` are left real -- they are the sections this page's
 * own `Section` helper wraps in a `ScrollPanel`, and an empty tile/mover array exercises that
 * wrapper via each grid's own empty-state placeholder without needing `MacroTile`'s chart fetching.
 *
 * Rendered under a `MemoryRouter` -- `useUrlState` (the tab rail's URL persistence) calls
 * `react-router-dom`'s `useSearchParams`, which throws outside a Router, matching how
 * `Tax.test.tsx` renders `<Tax />`.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MacroSnapshot } from "@/api/macro";
import type { MacroNewsState } from "@/hooks/useMacroNews";
import type { MacroSnapshotState } from "@/hooks/useMacroSnapshot";

const snapshotMock = vi.fn<() => MacroSnapshotState>();
const newsMock = vi.fn<() => MacroNewsState>();

vi.mock("@/hooks/useMacroSnapshot", () => ({ useMacroSnapshot: () => snapshotMock() }));
vi.mock("@/hooks/useMacroNews", () => ({ useMacroNews: () => newsMock() }));

vi.mock("@/components/FearGreedGauge", () => ({ default: () => <div>fear-greed-mock</div> }));
vi.mock("@/components/MacroKeyIndicators", () => ({ default: () => <div>key-indicators-mock</div> }));
vi.mock("@/components/MacroNewsPanel", () => ({ default: () => <div>news-panel-mock</div> }));

const { default: Macro } = await import("@/pages/Macro");

function snapshot(overrides: Partial<MacroSnapshot> = {}): MacroSnapshot {
  return {
    generated_at: "2026-09-05T12:00:00Z",
    rates: [],
    oil: [],
    fear_greed: null,
    movers: [],
    warnings: [],
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  snapshotMock.mockReset();
  newsMock.mockReset();
});

/** Shows the current route's query string, so a test can assert the tab landed in the URL without
 *  reaching into the router's internals -- mirrors `Tax.test.tsx`'s `LocationProbe`. */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname + location.search}</div>;
}

function renderMacro(initialPath = "/macro") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <LocationProbe />
      <Macro />
    </MemoryRouter>,
  );
}

function loadedSnapshot(overrides: Partial<MacroSnapshot> = {}) {
  snapshotMock.mockReturnValue({
    snapshot: snapshot(overrides),
    phase: "loaded",
    message: null,
    refresh: vi.fn(),
  });
  newsMock.mockReturnValue({ data: null, phase: "loading", message: null });
}

describe("Macro page tab strip", () => {
  it("renders a tablist naming all six sections, defaulting to Fear & Greed", () => {
    loadedSnapshot();
    renderMacro();

    expect(screen.getByRole("tablist")).toBeTruthy();
    for (const name of ["Fear & Greed", "Key indicators", "Rates", "Oil", "Movers", "News"]) {
      expect(screen.getByRole("tab", { name })).toBeTruthy();
    }
    expect(screen.getByRole("tab", { name: "Fear & Greed" }).getAttribute("aria-selected")).toBe(
      "true",
    );
    expect(screen.getByText("fear-greed-mock")).toBeTruthy();
    // Only the active tab's content is mounted -- the other five are absent, not just hidden. "Rates"
    // as a section *heading* (as opposed to its tab-rail button, which is expected to be present) is
    // the actual proof, since the tab label text is present regardless of which tab is active.
    expect(screen.queryByText("key-indicators-mock")).toBeNull();
    expect(screen.queryByText("news-panel-mock")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Rates" })).toBeNull();
  });

  it("mounts a section only once its tab is selected, and writes the tab into the URL", () => {
    loadedSnapshot();
    renderMacro();

    fireEvent.click(screen.getByRole("tab", { name: "Movers" }));

    // "Movers" now appears twice (the tab label and the section's own `<h2>`) -- assert the heading
    // specifically, not the ambiguous text match.
    expect(screen.getByRole("heading", { name: "Movers" })).toBeTruthy();
    expect(screen.queryByText("fear-greed-mock")).toBeNull();
    expect(screen.getByTestId("location-probe").textContent).toContain("tab=movers");
  });

  it("opens directly on a non-default tab when the initial URL already says so -- a reload on /macro?tab=news", () => {
    loadedSnapshot();
    renderMacro("/macro?tab=news");

    expect(screen.getByRole("tab", { name: "News" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByText("news-panel-mock")).toBeTruthy();
    expect(screen.queryByText("fear-greed-mock")).toBeNull();
  });

  it("falls back to the default tab for an unrecognized ?tab= value instead of rendering nothing", () => {
    loadedSnapshot();
    renderMacro("/macro?tab=nonsense");

    expect(screen.getByRole("tab", { name: "Fear & Greed" }).getAttribute("aria-selected")).toBe(
      "true",
    );
    expect(screen.getByText("fear-greed-mock")).toBeTruthy();
  });

  it("shows a translated pill for a warning kind, above the tab rail, never the raw wire token", () => {
    loadedSnapshot({
      warnings: [{ kind: "provider_fallback", message: "FRED unreachable; using Yahoo proxy." }],
    });
    renderMacro();

    expect(screen.getByText("Provider fallback")).toBeTruthy();
    expect(screen.getByText("FRED unreachable; using Yahoo proxy.")).toBeTruthy();
    expect(screen.queryByText("provider_fallback")).toBeNull();
  });

  it("falls a still-unmapped warning kind through to a readable pill, not the raw token", () => {
    loadedSnapshot({ warnings: [{ kind: "some_future_kind", message: "A new backend warning." }] });
    renderMacro();

    expect(screen.getByText("Notice")).toBeTruthy();
    expect(screen.queryByText("some_future_kind")).toBeNull();
  });

  it("still shows the loading state, with no tab rail, when the snapshot has not resolved yet", () => {
    snapshotMock.mockReturnValue({ snapshot: null, phase: "loading", message: null, refresh: vi.fn() });
    newsMock.mockReturnValue({ data: null, phase: "loading", message: null });

    renderMacro();

    expect(screen.getByText("Loading macro snapshot…")).toBeTruthy();
    expect(screen.queryByRole("tablist")).toBeNull();
  });
});

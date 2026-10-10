/**
 * Research Desk: the toggle over Trading Agents and Vibe Trading.
 *
 * This page does no fetching of its own -- it just renders one of the two real page components,
 * unchanged, based on which tab is active. So unlike `TradingAgents.test.tsx` / `VibeTrading.test.tsx`,
 * nothing here stubs `@/api/tradingagents` or `@/api/vibedesk`: the global `fetch` stub from
 * `src/test/setup.ts` already makes every one of their mount-time fetches reject harmlessly, and
 * both pages render their static heading/explainer content regardless of fetch outcome -- exactly
 * the synchronous content these tests assert on.
 *
 * What this pins, per the task brief: both tabs render, the page opens on the analyst pipeline
 * (Trading Agents), and switching to Committee swaps in Vibe Trading in place -- proven by a heading
 * unique to each side (`agentDesk.trading.title` / `agentDesk.vibe.presetPicker.title`), not by a
 * stubbed placeholder.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import ResearchDesk from "@/pages/ResearchDesk";

function renderPage() {
  return render(
    <MemoryRouter>
      <ResearchDesk />
    </MemoryRouter>,
  );
}

describe("ResearchDesk", () => {
  it("renders both tabs", () => {
    renderPage();

    expect(screen.getByRole("tab", { name: "Analyst pipeline" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Committee" })).toBeTruthy();
  });

  it("defaults to the analyst pipeline desk", () => {
    renderPage();

    expect(screen.getByRole("tab", { name: "Analyst pipeline" }).getAttribute("aria-selected")).toBe(
      "true",
    );
    expect(screen.getByRole("tab", { name: "Committee" }).getAttribute("aria-selected")).toBe(
      "false",
    );
    // Trading Agents' own heading, not a stub -- proves the real component is mounted.
    // Embedded under the Research Desk shell the desk heading is an <h2>: the page keeps one <h1>
    // (A11Y-02, 2026-09-10 audit); /trading-agents on its own still renders the <h1>.
    expect(screen.getByRole("heading", { level: 2, name: "Trading Agents" })).toBeTruthy();
    // Vibe Trading is not mounted at all yet.
    expect(screen.queryByText("Choose a preset")).toBeNull();
  });

  it("switches to the committee desk on click", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("tab", { name: "Committee" }));

    expect(screen.getByRole("tab", { name: "Committee" }).getAttribute("aria-selected")).toBe("true");
    // Vibe Trading's preset-picker heading -- unique to that page, proves it is the real component
    // now mounted in place of Trading Agents.
    expect(screen.getByText("Choose a preset")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "Vibe Trading" })).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 2, name: "Trading Agents" })).toBeNull();
  });
});

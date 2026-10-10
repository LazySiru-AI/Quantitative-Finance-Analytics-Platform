/**
 * Agent Desk landing: the availability note, the funnel, and the try-this cards.
 *
 * `@/api/tradingagents` is stubbed at the module boundary, matching `TradingAgents.test.tsx`'s own
 * approach -- only `config()` is replaced, since it is the only call this page makes.
 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TradingAgentsConfig } from "@/api/tradingagents";

const configMock = vi.fn<() => Promise<TradingAgentsConfig>>();

vi.mock("@/api/tradingagents", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/tradingagents")>();
  return {
    ...actual,
    tradingAgentsApi: { ...actual.tradingAgentsApi, config: () => configMock() },
  };
});

const { default: AgentDeskLanding } = await import("@/pages/AgentDeskLanding");

function tradingAgentsConfig(overrides: Partial<TradingAgentsConfig> = {}): TradingAgentsConfig {
  return {
    analysts: [],
    default_debate_rounds: 1,
    default_risk_rounds: 1,
    max_rounds: 3,
    default_budget_usd: "5.00",
    default_model: "claude-haiku-4-5-20251001",
    available_models: [{ id: "claude-haiku-4-5-20251001", label: "Haiku 4.5" }],
    agent_available: true,
    agent_reason: "",
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <AgentDeskLanding />
    </MemoryRouter>,
  );
}

afterEach(() => {
  configMock.mockReset();
});

describe("AgentDeskLanding", () => {
  it("shows the agent layer as available once config resolves", async () => {
    configMock.mockResolvedValue(tradingAgentsConfig({ agent_available: true }));

    renderPage();

    expect(await screen.findByText("Agents online")).toBeTruthy();
    expect(screen.getByText("The agent layer is reachable — a run can start now.")).toBeTruthy();
  });

  it("shows the reason when the agent layer is unavailable", async () => {
    configMock.mockResolvedValue(
      tradingAgentsConfig({ agent_available: false, agent_reason: "missing ANTHROPIC_API_KEY" }),
    );

    renderPage();

    expect(await screen.findByText("Agents offline")).toBeTruthy();
    expect(screen.getByText("Agent layer unavailable: missing ANTHROPIC_API_KEY")).toBeTruthy();
  });

  it("degrades to an unknown state, not a false 'offline', when the config fetch fails", async () => {
    configMock.mockRejectedValue(new Error("network down"));

    renderPage();

    expect(await screen.findByText("Unknown")).toBeTruthy();
    expect(screen.queryByText("Agents offline")).toBeNull();
  });

  it("renders the funnel in order: Ask, Orchestrate, Measure, Follow", () => {
    configMock.mockResolvedValue(tradingAgentsConfig());

    renderPage();

    // Each step after the first carries a leading `aria-hidden` arrow glyph as part of its own
    // `textContent` -- see `adl-funnel-arrow` in `AgentDeskLanding.tsx` -- so the visible words
    // alone are checked with a substring match rather than equality.
    const steps = screen.getAllByRole("listitem").map((el) => el.textContent);
    expect(steps).toHaveLength(4);
    expect(steps[0]).toBe("Ask");
    expect(steps[1]).toContain("Orchestrate");
    expect(steps[2]).toContain("Measure");
    expect(steps[3]).toContain("Follow");
  });

  it("renders three try-this cards to concrete destinations", () => {
    configMock.mockResolvedValue(tradingAgentsConfig());

    renderPage();

    // Both cards now point at the one Research Desk page -- the analyst pipeline and committee
    // desk are a toggle inside it, not two separate destinations. See `nav.ts` / `App.tsx`.
    expect(screen.getByRole("link", { name: /Research one ticker/ }).getAttribute("href")).toBe(
      "/research-desk",
    );
    expect(screen.getByRole("link", { name: /Ask a committee/ }).getAttribute("href")).toBe(
      "/research-desk",
    );
    expect(screen.getByRole("link", { name: /Run the workflow/ }).getAttribute("href")).toBe(
      "/agent-workflow",
    );
  });
});

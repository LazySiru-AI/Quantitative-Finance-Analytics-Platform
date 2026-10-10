/**
 * Strategy Lab landing: the verdict, the funnel, the live counts, and the try-this cards.
 *
 * `@/api/rules` and `@/api/competition` are stubbed at the module boundary, matching
 * `TradingAgents.test.tsx`/`Competition.test.tsx`'s own approach -- `importOriginal` keeps every
 * other export (types, format helpers) real, and only the two network calls this page makes are
 * replaced.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Rule } from "@/api/rules";
import type { RoundSummary, RoundsResponse } from "@/api/competition";

const catalogMock = vi.fn<() => Promise<Rule[]>>();
const roundsMock = vi.fn<() => Promise<RoundsResponse>>();

vi.mock("@/api/rules", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/rules")>();
  return { ...actual, rulesApi: { ...actual.rulesApi, catalog: () => catalogMock() } };
});

vi.mock("@/api/competition", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/competition")>();
  return {
    ...actual,
    competitionApi: { ...actual.competitionApi, rounds: () => roundsMock() },
  };
});

const { default: StrategyLanding } = await import("@/pages/StrategyLanding");

function rule(overrides: Partial<Rule> = {}): Rule {
  return {
    rule_id: "close_above_sma20",
    name: "Close above SMA(20)",
    expression: "close > sma(20)",
    description: "Price closed above its 20-bar simple moving average.",
    intervals: ["1d"],
    ...overrides,
  };
}

function round(overrides: Partial<RoundSummary> = {}): RoundSummary {
  return {
    round_id: "r33-2026-09",
    label: "r33 — Sep 2026",
    windows: ["r5-ladder"],
    agents: 12,
    has_report: true,
    has_brief: true,
    has_results: true,
    has_selection: true,
    sequence: 33,
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <StrategyLanding />
    </MemoryRouter>,
  );
}

afterEach(() => {
  catalogMock.mockReset();
  roundsMock.mockReset();
});

describe("StrategyLanding", () => {
  it("renders the headline verdict", () => {
    catalogMock.mockResolvedValue([]);
    roundsMock.mockResolvedValue({ rounds: [] });

    renderPage();

    expect(screen.getByText("No durable edge")).toBeTruthy();
    expect(
      screen.getByText(
        "No durable out-of-sample edge across 33 rounds, a 9,480-cell timeframe sweep and 291 loop generations.",
      ),
    ).toBeTruthy();
  });

  it("renders the funnel in order: Rules, Evidence, Competition, Paper Desk", () => {
    catalogMock.mockResolvedValue([]);
    roundsMock.mockResolvedValue({ rounds: [] });

    renderPage();

    // Each step after the first carries a leading `aria-hidden` arrow glyph as part of its own
    // `textContent` -- see `sl-funnel-arrow` in `StrategyLanding.tsx` -- so the visible words alone
    // are checked with a substring match rather than equality.
    const steps = screen.getAllByRole("listitem").map((el) => el.textContent);
    expect(steps).toHaveLength(4);
    expect(steps[0]).toBe("Rules");
    expect(steps[1]).toContain("Evidence");
    expect(steps[2]).toContain("Competition");
    expect(steps[3]).toContain("Paper Desk");
  });

  it("renders three try-this cards to concrete destinations", () => {
    catalogMock.mockResolvedValue([]);
    roundsMock.mockResolvedValue({ rounds: [] });

    renderPage();

    expect(screen.getByRole("link", { name: /Test one rule on one symbol/ }).getAttribute("href")).toBe(
      "/evidence",
    );
    expect(
      screen.getByRole("link", { name: /Read the last round's findings/ }).getAttribute("href"),
    ).toBe("/competition");
    expect(screen.getByRole("link", { name: /Review a promoted card/ }).getAttribute("href")).toBe(
      "/competition",
    );
  });

  it("shows the live rule and round counts once both fetches resolve", async () => {
    catalogMock.mockResolvedValue([rule(), rule({ rule_id: "rsi_oversold" })]);
    roundsMock.mockResolvedValue({ rounds: [round(), round({ round_id: "r32", sequence: 32 })] });

    renderPage();

    // Both tiles land on the same count in this fixture, so assert there are two "2"s rather than
    // picking one arbitrarily with `getByText`, which throws on more than one match.
    await waitFor(() => expect(screen.getAllByText("2")).toHaveLength(2));
  });

  it("degrades a single failed count to an em dash without blanking the other", async () => {
    catalogMock.mockRejectedValue(new Error("network down"));
    roundsMock.mockResolvedValue({ rounds: [round()] });

    renderPage();

    await waitFor(() => expect(screen.getByText("1")).toBeTruthy());
    expect(screen.getByText("—")).toBeTruthy();
  });
});

/**
 * Rules: a smoke test for the page shell.
 *
 * Prerequisite coverage added alongside `pages/Evidence.tsx`, which mounts this page unchanged as
 * one of its tabs -- there was previously no test file for this page at all. `@/api/rules` is
 * stubbed at the module boundary, the same idiom `StrategyLanding.test.tsx` uses for the same
 * module: `importOriginal` keeps every other export (types, format helpers) real, and only
 * `rulesApi.catalog` -- the one network call this page makes on mount -- is replaced. `RuleEditor`
 * itself never fetches with an empty, untouched input (see `components/RuleEditor.tsx`'s effect,
 * which no-ops on an empty trimmed expression), so `rulesApi.validate` needs no stub here.
 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Rule } from "@/api/rules";

const catalogMock = vi.fn<() => Promise<Rule[]>>();

vi.mock("@/api/rules", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/rules")>();
  return { ...actual, rulesApi: { ...actual.rulesApi, catalog: () => catalogMock() } };
});

const { default: Rules } = await import("@/pages/Rules");

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

function renderPage() {
  return render(
    <MemoryRouter>
      <Rules />
    </MemoryRouter>,
  );
}

afterEach(() => {
  catalogMock.mockReset();
});

describe("Rules", () => {
  it("renders the page heading, subtitle and the expression tester heading", () => {
    catalogMock.mockResolvedValue([]);

    renderPage();

    expect(screen.getByRole("heading", { level: 1, name: "Rules" })).toBeTruthy();
    expect(screen.getByText(/Vocabulary plus a scratchpad to test expressions/)).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "Test a rule expression" })).toBeTruthy();
  });

  it("renders the catalogue table from the mocked catalog once it loads", async () => {
    catalogMock.mockResolvedValue([
      rule(),
      rule({ rule_id: "rsi_oversold", name: "RSI oversold", expression: "rsi(14) < 30" }),
    ]);

    renderPage();

    const table = await screen.findByRole("table");
    expect(table).toBeTruthy();
    expect(screen.getByRole("rowheader", { name: "Close above SMA(20)" })).toBeTruthy();
    expect(screen.getByRole("rowheader", { name: "RSI oversold" })).toBeTruthy();
    expect(screen.getByText("rsi(14) < 30")).toBeTruthy();
  });

  it("shows the empty-catalogue message when there are no rules", async () => {
    catalogMock.mockResolvedValue([]);

    renderPage();

    expect(await screen.findByText("The rule catalog is empty.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("renders each interval as its own badge rather than one comma-joined string", async () => {
    catalogMock.mockResolvedValue([rule({ intervals: ["15m", "1h", "1d"] })]);

    renderPage();
    await screen.findByRole("table");

    // Three separate elements, not the text "15m, 1h, 1d" -- the point is that a bounded set of
    // short tokens can wrap and stack instead of competing with the description column for width.
    const badges = document.querySelectorAll(".rules-interval-badge");
    expect(Array.from(badges).map((b) => b.textContent)).toEqual(["15m", "1h", "1d"]);
  });

  it("marks an unconstrained rule's interval cell as an absence, not a fourth interval", async () => {
    catalogMock.mockResolvedValue([rule({ intervals: [] })]);

    renderPage();
    await screen.findByRole("table");

    const any = document.querySelector(".rules-interval-badge.rules-interval-any");
    expect(any).toBeTruthy();
    expect(any?.textContent).toBe("any");
  });

  it("gives the description column the wrapping class the catalogue's prose needs", async () => {
    catalogMock.mockResolvedValue([rule()]);

    renderPage();
    await screen.findByRole("table");

    // `.data-table` sets `white-space: nowrap` on every cell; jsdom applies no stylesheet, so what
    // is assertable here is that the cell opts into the override. The rendered width is a browser
    // check, not a unit one.
    const cell = document.querySelector("td.rules-description");
    expect(cell?.textContent).toContain("20-bar simple moving average");
  });

  it("makes the catalogue's horizontal scroller a named, reachable region", async () => {
    catalogMock.mockResolvedValue([rule()]);

    renderPage();
    await screen.findByRole("table");

    const region = screen.getByRole("region", { name: "Catalog" });
    // Without a tab stop a keyboard user cannot scroll an overflowing wrapper at all.
    expect(region.getAttribute("tabindex")).toBe("0");
    expect(region.classList.contains("table-wrap")).toBe(true);
  });

  it("keeps the h1 on its own route and drops to h2 only when embedded", async () => {
    catalogMock.mockResolvedValue([]);

    const { rerender } = renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Rules" })).toBeTruthy();

    rerender(
      <MemoryRouter>
        <Rules embedded />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { level: 2, name: "Rules" })).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 1, name: "Rules" })).toBeNull();
  });
});

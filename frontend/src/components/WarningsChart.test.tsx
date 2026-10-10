/**
 * `WarningsChart`'s bar-count and top-symbols contract, at render level.
 *
 * No API is stubbed here: the component takes its data as props (`warningGroups`/`warnings`,
 * already fetched by `Portfolio.tsx`'s `usePortfolio()`), so these tests build fixtures directly.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { TaxWarning, WarningGroup } from "@/api/portfolio";
import WarningsChart from "@/components/WarningsChart";

function group(overrides: Partial<WarningGroup> = {}): WarningGroup {
  return {
    kind: "missing_basis",
    account_id: "rh-taxable",
    broker: "Robinhood",
    count: 3,
    sample_detail: "no basis row for lot",
    ...overrides,
  };
}

function warning(overrides: Partial<TaxWarning> = {}): TaxWarning {
  return {
    kind: "missing_basis",
    account_id: "rh-taxable",
    broker: "Robinhood",
    symbol: "NVDA",
    trade_date: "2026-03-02",
    detail: "no basis row for lot",
    ...overrides,
  };
}

describe("WarningsChart", () => {
  it("renders one bar total per kind, equal to the sum of that kind's group counts", () => {
    render(
      <WarningsChart
        warningGroups={[
          group({ kind: "missing_basis", account_id: "rh-taxable", count: 3 }),
          group({ kind: "missing_basis", account_id: "wb-margin", broker: "Webull", count: 4 }),
          group({ kind: "fees_unknown", account_id: "rh-taxable", count: 2 }),
        ]}
        warnings={[]}
      />,
    );

    // missing_basis: 3 + 4 = 7; fees_unknown: 2. Both totals render as visible text next to their bar.
    expect(screen.getByText("7")).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy();

    // Each segment carries its own count in a hover title, per-account, never summed across accounts
    // inside a single segment.
    const titles = Array.from(document.querySelectorAll("title")).map((el) => el.textContent);
    expect(titles.some((t) => t?.includes("· 3"))).toBe(true);
    expect(titles.some((t) => t?.includes("· 4"))).toBe(true);
    expect(titles.some((t) => t?.includes("· 2"))).toBe(true);
  });

  it("lists top symbols sorted descending by count", () => {
    render(
      <WarningsChart
        warningGroups={[group()]}
        warnings={[
          warning({ symbol: "AAA" }),
          warning({ symbol: "BBB" }),
          warning({ symbol: "BBB" }),
          warning({ symbol: "BBB" }),
          warning({ symbol: "CCC" }),
          warning({ symbol: "CCC" }),
        ]}
      />,
    );

    const rows = Array.from(document.querySelectorAll(".wc-top-symbol-row")).map((el) => el.textContent ?? "");
    // BBB (3) must precede CCC (2), which must precede AAA (1).
    const bbbIndex = rows.findIndex((r) => r.includes("BBB"));
    const cccIndex = rows.findIndex((r) => r.includes("CCC"));
    const aaaIndex = rows.findIndex((r) => r.includes("AAA"));
    expect(bbbIndex).toBeGreaterThanOrEqual(0);
    expect(bbbIndex).toBeLessThan(cccIndex);
    expect(cccIndex).toBeLessThan(aaaIndex);
  });

  it("renders without crashing when there is no symbol-level warning data", () => {
    render(
      <WarningsChart
        warningGroups={[group()]}
        warnings={[warning({ symbol: null }), warning({ symbol: null })]}
      />,
    );

    // The bar chart itself still renders (groups are non-empty)...
    expect(document.querySelector(".wc-svg")).toBeTruthy();
    // ...but the top-symbols list is empty, and says so rather than rendering a blank list.
    expect(document.querySelector(".wc-top-symbol-row")).toBeNull();
    expect(screen.getByText(/none of these warnings name a specific symbol/i)).toBeTruthy();
  });

  it("renders a designed empty state when there are no warning groups at all", () => {
    render(<WarningsChart warningGroups={[]} warnings={[]} />);
    expect(document.querySelector(".wc-svg")).toBeNull();
    expect(screen.getByText(/no warnings to chart/i)).toBeTruthy();
  });
});

/**
 * AllocationPie: renormalised percentages (unlike HoldingsPieChart, this donut always totals 100%
 * of the slices passed in), topN truncation into an exact-summed "Other" slice, the empty/zero-total
 * placeholder, the mode toggle, the ticker-only sector badge, and legend-row interactivity.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { formatMoney } from "@/api/portfolio";
import AllocationPie, { type AllocationSlice } from "@/components/AllocationPie";

afterEach(cleanup);

function slice(overrides: Partial<AllocationSlice> = {}): AllocationSlice {
  return {
    key: "AAA",
    label: "AAA",
    sector: "SOFTWARE",
    value: "10",
    ticker: "AAA",
    ...overrides,
  };
}

describe("empty / zero-total", () => {
  it("renders the placeholder and does not throw when there are no slices", () => {
    const onModeChange = vi.fn();
    expect(() =>
      render(<AllocationPie slices={[]} mode="ticker" onModeChange={onModeChange} title="Allocation" />),
    ).not.toThrow();
    expect(screen.getByText(/no allocation data/i)).toBeTruthy();
    expect(document.querySelector("svg")).toBeNull();
  });

  it("renders the placeholder, not a NaN donut, when every slice's value is zero", () => {
    const onModeChange = vi.fn();
    const slices = [slice({ key: "A", value: "0" }), slice({ key: "B", value: "0" })];
    expect(() =>
      render(<AllocationPie slices={slices} mode="ticker" onModeChange={onModeChange} title="Allocation" />),
    ).not.toThrow();
    expect(screen.getByText(/no allocation data/i)).toBeTruthy();
    expect(document.querySelector("svg")).toBeNull();
  });
});

describe("renormalised percentages", () => {
  it("sums every rendered slice's percent to 100, unlike HoldingsPieChart's honest shortfall", () => {
    const onModeChange = vi.fn();
    const slices = [
      slice({ key: "A", label: "Alpha", value: "50" }),
      slice({ key: "B", label: "Beta", value: "30" }),
      slice({ key: "C", label: "Gamma", value: "20" }),
    ];
    const { container } = render(
      <AllocationPie slices={slices} mode="ticker" onModeChange={onModeChange} title="Allocation" />,
    );
    const percents = Array.from(container.querySelectorAll(".alloc-pie-legend-percent")).map((el) =>
      Number.parseFloat(el.textContent ?? "0"),
    );
    expect(percents).toHaveLength(3);
    const total = percents.reduce((sum, p) => sum + p, 0);
    expect(total).toBeCloseTo(100, 5);
  });

  it("renders a single slice as a full ring (100%) rather than a partial arc", () => {
    const onModeChange = vi.fn();
    const slices = [slice({ key: "A", label: "Alpha", value: "42" })];
    const { container } = render(
      <AllocationPie slices={slices} mode="ticker" onModeChange={onModeChange} title="Allocation" />,
    );
    const percent = container.querySelector(".alloc-pie-legend-percent");
    expect(percent?.textContent).toBe("100.0%");
  });
});

describe("topN truncation", () => {
  it("folds the tail into one 'Other' slice carrying the exact summed value, not a renormalised share", () => {
    const onModeChange = vi.fn();
    const slices = [
      slice({ key: "A", label: "Alpha", value: "50" }),
      slice({ key: "B", label: "Beta", value: "30" }),
      slice({ key: "C", label: "Gamma", value: "10" }),
      slice({ key: "D", label: "Delta", value: "6" }),
      slice({ key: "E", label: "Epsilon", value: "4" }),
    ];
    render(
      <AllocationPie slices={slices} mode="ticker" onModeChange={onModeChange} title="Allocation" topN={2} />,
    );

    // Only the top two render as their own rows.
    expect(screen.getByText("Alpha")).toBeTruthy();
    expect(screen.getByText("Beta")).toBeTruthy();
    expect(screen.queryByText("Gamma")).toBeNull();
    expect(screen.queryByText("Delta")).toBeNull();
    expect(screen.queryByText("Epsilon")).toBeNull();

    // The remaining three (10 + 6 + 4 = 20) fold into one "Other" row with the exact summed dollar
    // value, not e.g. an equal three-way split or a renormalised figure.
    expect(screen.getByText("Other")).toBeTruthy();
    expect(screen.getByText(formatMoney("20"))).toBeTruthy();
  });

  it("draws no 'Other' row when there are topN or fewer slices", () => {
    const onModeChange = vi.fn();
    const slices = [slice({ key: "A", label: "Alpha", value: "10" })];
    render(
      <AllocationPie slices={slices} mode="ticker" onModeChange={onModeChange} title="Allocation" topN={12} />,
    );
    expect(screen.queryByText("Other")).toBeNull();
  });
});

describe("mode toggle", () => {
  it("is a two-tab tablist that calls onModeChange with the OTHER mode when clicked", () => {
    const onModeChange = vi.fn();
    const slices = [slice({ key: "A", value: "10" })];
    render(<AllocationPie slices={slices} mode="ticker" onModeChange={onModeChange} title="Allocation" />);

    const tablist = screen.getByRole("tablist");
    expect(tablist).toBeTruthy();

    const sectorTab = screen.getByRole("tab", { name: /by sector/i });
    expect(sectorTab.getAttribute("aria-selected")).toBe("false");
    fireEvent.click(sectorTab);
    expect(onModeChange).toHaveBeenCalledWith("sector");

    const tickerTab = screen.getByRole("tab", { name: /by ticker/i });
    expect(tickerTab.getAttribute("aria-selected")).toBe("true");
  });

  it("still renders a clickable toggle in the empty state", () => {
    const onModeChange = vi.fn();
    render(<AllocationPie slices={[]} mode="sector" onModeChange={onModeChange} title="Allocation" />);
    fireEvent.click(screen.getByRole("tab", { name: /by ticker/i }));
    expect(onModeChange).toHaveBeenCalledWith("ticker");
  });
});

describe("sector badge", () => {
  it("shows the sector badge in ticker mode", () => {
    const onModeChange = vi.fn();
    const slices = [slice({ key: "A", label: "NVDA", sector: "SEMI", ticker: "NVDA", value: "10" })];
    render(<AllocationPie slices={slices} mode="ticker" onModeChange={onModeChange} title="Allocation" />);
    expect(screen.getByText("NVDA")).toBeTruthy();
    expect(screen.getByText("SEMI")).toBeTruthy();
  });

  it("hides the sector badge in sector mode", () => {
    const onModeChange = vi.fn();
    // In sector mode the caller sets label === sector (per the frozen contract); the badge must not
    // duplicate that same text as a second element.
    const slices = [slice({ key: "SEMI", label: "SEMI", sector: "SEMI", ticker: null, value: "10" })];
    render(<AllocationPie slices={slices} mode="sector" onModeChange={onModeChange} title="Allocation" />);
    expect(screen.getAllByText("SEMI")).toHaveLength(1);
    expect(document.querySelector(".alloc-pie-sector")).toBeNull();
  });
});

describe("legend row interactivity", () => {
  it("calls onSelectTicker with the right ticker when a row with a ticker is clicked", () => {
    const onModeChange = vi.fn();
    const onSelectTicker = vi.fn();
    const slices = [
      slice({ key: "A", label: "Alpha Corp", ticker: "ALPH", value: "10" }),
      slice({ key: "B", label: "Beta Corp", ticker: "BETA", value: "5" }),
    ];
    render(
      <AllocationPie
        slices={slices}
        mode="ticker"
        onModeChange={onModeChange}
        title="Allocation"
        onSelectTicker={onSelectTicker}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Alpha Corp/i }));
    expect(onSelectTicker).toHaveBeenCalledWith("ALPH");
    expect(onSelectTicker).not.toHaveBeenCalledWith("BETA");
  });

  it("renders a plain row, not a button, when the slice has no ticker", () => {
    const onModeChange = vi.fn();
    const onSelectTicker = vi.fn();
    const slices = [slice({ key: "Cash", label: "Cash", sector: "", ticker: null, value: "10" })];
    render(
      <AllocationPie
        slices={slices}
        mode="ticker"
        onModeChange={onModeChange}
        title="Allocation"
        onSelectTicker={onSelectTicker}
      />,
    );
    expect(screen.getByText("Cash")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Cash/i })).toBeNull();
  });

  it("renders a plain row, not a button, when no onSelectTicker is supplied even though the slice has a ticker", () => {
    const onModeChange = vi.fn();
    const slices = [slice({ key: "A", label: "Alpha Corp", ticker: "ALPH", value: "10" })];
    render(<AllocationPie slices={slices} mode="ticker" onModeChange={onModeChange} title="Allocation" />);
    expect(screen.getByText("Alpha Corp")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Alpha Corp/i })).toBeNull();
  });
});

describe("accessibility", () => {
  it("labels the donut with an img role and a meaningful aria-label", () => {
    const onModeChange = vi.fn();
    const slices = [slice({ key: "A", value: "10" })];
    render(<AllocationPie slices={slices} mode="ticker" onModeChange={onModeChange} title="My Portfolio" />);
    const svg = document.querySelector("svg[role='img']");
    expect(svg?.getAttribute("aria-label")).toMatch(/my portfolio/i);
  });
});

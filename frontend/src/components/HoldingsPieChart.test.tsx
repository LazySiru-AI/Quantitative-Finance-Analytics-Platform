/**
 * HoldingsPieChart: top-N truncation into an honest "Other" bucket, ticker-gated interactivity, the
 * empty state, and the no-renormalisation rule -- a 13F's weights are of its own equities-only
 * slice, and this component must never stretch them to look like a complete 100% book.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Holding } from "@/api/institutions";

import HoldingsPieChart from "@/components/HoldingsPieChart";

afterEach(cleanup);

function holding(overrides: Partial<Holding> = {}): Holding {
  return {
    cusip: "0000000000",
    issuer: "Example Corp",
    value: "1000000",
    shares: "1000",
    weight: "0.01",
    ticker: null,
    ...overrides,
  };
}

describe("empty holdings", () => {
  it("renders a worded placeholder, not a zero-radius circle", () => {
    render(<HoldingsPieChart holdings={[]} fundName="Example Fund" source="13F" />);
    expect(screen.getByText(/no holdings on record for example fund/i)).toBeTruthy();
    expect(document.querySelector("svg")).toBeNull();
  });
});

describe("top-N truncation", () => {
  it("aggregates the tail into a single 'Other' slice naming how many positions it folds in", () => {
    const holdings = Array.from({ length: 13 }, (_, i) =>
      holding({
        cusip: `CUSIP${i}`,
        issuer: `Issuer ${i}`,
        // Descending weights so the sort order is predictable: 0.20, 0.19, ... down to 0.08.
        weight: (0.2 - i * 0.01).toFixed(2),
      }),
    );
    render(<HoldingsPieChart holdings={holdings} fundName="Example Fund" source="13F" topN={10} />);

    // The 10 largest render as their own rows; the remaining 3 fold into one "Other" row.
    expect(screen.getByText("Issuer 0")).toBeTruthy();
    expect(screen.getByText("Issuer 9")).toBeTruthy();
    expect(screen.queryByText("Issuer 10")).toBeNull();
    expect(screen.getByText(/Other \(3 positions\)/)).toBeTruthy();

    // The "Other" slice's own weight is the exact sum of the folded-in positions (0.10+0.09+0.08),
    // not a renormalised share -- 27.00% here, verified against formatWeight's own rendering.
    expect(screen.getByText("27.00%")).toBeTruthy();
  });

  it("draws no 'Other' slice when there are topN or fewer holdings", () => {
    const holdings = [holding({ cusip: "A", issuer: "Only One", weight: "0.5" })];
    render(<HoldingsPieChart holdings={holdings} fundName="Example Fund" source="13F" topN={10} />);
    expect(screen.queryByText(/Other \(/)).toBeNull();
  });
});

describe("ticker-gated interactivity", () => {
  it("fires onSelectTicker when a slice with a resolved ticker is activated", () => {
    const onSelectTicker = vi.fn();
    const holdings = [holding({ cusip: "A", issuer: "Has Ticker Inc", weight: "0.3", ticker: "HTI" })];
    render(<HoldingsPieChart holdings={holdings} fundName="Example Fund" source="13F" onSelectTicker={onSelectTicker} />);

    fireEvent.click(screen.getByRole("button", { name: /Has Ticker Inc.*HTI/i }));
    expect(onSelectTicker).toHaveBeenCalledWith("HTI");
  });

  it("renders no button for a holding without a resolved ticker", () => {
    const holdings = [holding({ cusip: "A", issuer: "No Ticker Inc", weight: "0.3", ticker: null })];
    render(<HoldingsPieChart holdings={holdings} fundName="Example Fund" source="13F" />);

    expect(screen.getByText("No Ticker Inc")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /No Ticker Inc/i })).toBeNull();
  });
});

describe("no renormalisation", () => {
  it("shows the true total when weights fall short of 100%, without inflating any slice", () => {
    const holdings = [
      holding({ cusip: "A", issuer: "Alpha", weight: "0.30" }),
      holding({ cusip: "B", issuer: "Beta", weight: "0.20" }),
    ];
    render(<HoldingsPieChart holdings={holdings} fundName="Example Fund" source="13F" />);

    // Each slice keeps its own literal weight -- neither is stretched toward 100%.
    expect(screen.getByText("30.00%")).toBeTruthy();
    expect(screen.getByText("20.00%")).toBeTruthy();
    // And the shortfall (50%, not 100%) is stated honestly.
    expect(screen.getByText(/total 50\.00% of the filing/i)).toBeTruthy();
  });
});

describe("caption states the right facts for the filing kind actually on screen", () => {
  // The bug this guards: the caption used to hardcode the 13F caveat ("no bonds, no cash, no
  // foreign listings ... not of the whole portfolio") regardless of which filing backed the
  // holdings. That is true of a 13F and false on all three counts of an NPORT-P ETF filing, whose
  // holdings *are* the fund's whole reported portfolio.
  it("states the 13F equities-only-slice caveat for a 13F fund", () => {
    const holdings = [holding({ cusip: "A", issuer: "Alpha", weight: "0.3" })];
    render(<HoldingsPieChart holdings={holdings} fundName="Example Fund" source="13F" />);
    expect(screen.getByText(/13F: weights cover this filing.s US equities/i)).toBeTruthy();
    expect(screen.queryByText(/NPORT-P/)).toBeNull();
  });

  it("states the NPORT-P whole-portfolio fact for an ETF fund, not the 13F caveat", () => {
    const holdings = [holding({ cusip: "A", issuer: "Alpha", weight: "0.3" })];
    render(<HoldingsPieChart holdings={holdings} fundName="Example Fund" source="NPORT" />);
    expect(screen.getByText(/NPORT-P: weights cover Example Fund.s whole portfolio/i)).toBeTruthy();
    expect(screen.queryByText(/no bonds, cash, foreign listings/i)).toBeNull();
  });
});

describe("accessibility", () => {
  it("labels the chart with the fund name and what is charted, on an img-role SVG", () => {
    const holdings = [holding({ cusip: "A", issuer: "Alpha", weight: "0.3" })];
    render(<HoldingsPieChart holdings={holdings} fundName="Example Fund" source="13F" />);

    const svg = document.querySelector("svg[role='img']");
    expect(svg?.getAttribute("aria-label")).toMatch(/example fund/i);
    expect(svg?.getAttribute("aria-label")).toMatch(/weight/i);
  });
});

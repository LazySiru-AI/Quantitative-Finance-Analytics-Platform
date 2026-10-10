/**
 * RecentMoves: ranking by |weight_delta| (never value_delta), the null-shares_pct_change "new"
 * rendering, all four `phase` states, and the "of portfolio" framing that is the whole point of this
 * panel -- a bare "+2.1%" reads as "the position grew", not "the portfolio moved by this much".
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { HoldingChange, PortfolioDelta } from "@/api/institutions";

import RecentMoves from "@/components/RecentMoves";

afterEach(cleanup);

function change(overrides: Partial<HoldingChange> = {}): HoldingChange {
  return {
    cusip: "0000000000",
    issuer: "Example Corp",
    ticker: null,
    action: "add",
    shares_before: "1000",
    shares_after: "1100",
    shares_delta: "100",
    shares_pct_change: "0.10",
    value_before: "1000000",
    value_after: "1100000",
    value_delta: "100000",
    weight_before: "0.05",
    weight_after: "0.055",
    weight_delta: "0.005",
    ...overrides,
  };
}

function delta(changes: HoldingChange[]): PortfolioDelta {
  return {
    fund: { key: "BRK", name: "Berkshire Hathaway Inc", source: "13F", cik: "0000001", series_id: null, ticker: null, principal: "Warren Buffett" },
    from_period: "2026-03-31",
    to_period: "2026-06-30",
    from_accession: "0000000000-26-000001",
    to_accession: "0000000000-26-000002",
    total_value_before: "1000000000",
    total_value_after: "1050000000",
    changes,
    counts: { new: 0, exit: 0, add: 0, trim: 0, hold: 0 },
    median_shares_pct_change: null,
  };
}

describe("ranking is by |weight_delta|, never value_delta", () => {
  it("ranks a small-value, large-weight-swing row above a large-value, tiny-weight row", () => {
    const changes = [
      // Huge dollar swing, but a rounding-sized share of the whole portfolio.
      change({ cusip: "A", issuer: "Big Value Small Weight", value_delta: "500000000", weight_delta: "0.001" }),
      // Modest dollar swing, but a large share of the whole portfolio -- this is the real story.
      change({ cusip: "B", issuer: "Small Value Big Weight", value_delta: "10000", weight_delta: "-0.21" }),
    ];
    render(<RecentMoves delta={delta(changes)} phase="loaded" />);

    const rows = screen.getAllByText(/Big Value Small Weight|Small Value Big Weight/);
    expect(rows[0]?.textContent).toBe("Small Value Big Weight");
    expect(rows[1]?.textContent).toBe("Big Value Small Weight");
  });

  it("ranks by the magnitude of weight_delta regardless of sign", () => {
    const changes = [
      change({ cusip: "A", issuer: "Small Positive", weight_delta: "0.01" }),
      change({ cusip: "B", issuer: "Large Negative", weight_delta: "-0.30", action: "trim" }),
    ];
    render(<RecentMoves delta={delta(changes)} phase="loaded" />);

    const rows = screen.getAllByText(/Small Positive|Large Negative/);
    expect(rows[0]?.textContent).toBe("Large Negative");
  });
});

describe("shares_pct_change === null renders as 'new'", () => {
  it("never renders 0% or infinity for a brand-new position", () => {
    const changes = [change({ cusip: "A", issuer: "Brand New Position", action: "new", shares_before: "0", shares_pct_change: null })];
    render(<RecentMoves delta={delta(changes)} phase="loaded" />);

    expect(screen.getByText(/\(new\)/)).toBeTruthy();
    expect(screen.queryByText(/\(0%\)/)).toBeNull();
    expect(screen.queryByText(/∞|Infinity/)).toBeNull();
  });
});

describe("weight delta is labelled as a share of the portfolio", () => {
  it("shows +2.10% explicitly qualified as 'of portfolio', for weight_delta 0.021", () => {
    const changes = [change({ cusip: "A", issuer: "Grew A Lot", weight_delta: "0.021" })];
    render(<RecentMoves delta={delta(changes)} phase="loaded" />);

    expect(screen.getByText("+2.10%")).toBeTruthy();
    expect(screen.getByText(/of portfolio/i)).toBeTruthy();
  });
});

describe("the four phases render distinct, honest states", () => {
  it("loading", () => {
    render(<RecentMoves delta={null} phase="loading" />);
    expect(screen.getByText(/loading recent moves/i)).toBeTruthy();
  });

  it("error shows the given message, not a generic one, when provided", () => {
    render(<RecentMoves delta={null} phase="error" error="The filings service returned 500." />);
    expect(screen.getByText("The filings service returned 500.")).toBeTruthy();
  });

  it("empty is worded as an expected state, not a failure", () => {
    render(<RecentMoves delta={null} phase="empty" />);
    expect(screen.getByText(/only one filing is on record/i)).toBeTruthy();
    expect(screen.queryByText(/loading recent moves/i)).toBeNull();
  });

  it("loaded renders the comparison period and the ranked rows", () => {
    render(<RecentMoves delta={delta([change()])} phase="loaded" />);
    expect(screen.getByText(/comparing/i)).toBeTruthy();
    expect(screen.getByText("Example Corp")).toBeTruthy();
  });
});

describe("ticker-gated interactivity", () => {
  it("fires onSelectTicker for a row with a resolved ticker", () => {
    const onSelectTicker = vi.fn();
    const changes = [change({ cusip: "A", issuer: "Has A Ticker", ticker: "HAT" })];
    render(<RecentMoves delta={delta(changes)} phase="loaded" onSelectTicker={onSelectTicker} />);

    fireEvent.click(screen.getByRole("button", { name: /Has A Ticker.*HAT/i }));
    expect(onSelectTicker).toHaveBeenCalledWith("HAT");
  });

  it("renders no button for a row without a resolved ticker", () => {
    const changes = [change({ cusip: "A", issuer: "No Ticker Here", ticker: null })];
    render(<RecentMoves delta={delta(changes)} phase="loaded" />);

    expect(screen.getByText("No Ticker Here")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /No Ticker Here/i })).toBeNull();
  });
});

describe("limit", () => {
  it("shows at most `limit` rows, defaulting to 6", () => {
    const changes = Array.from({ length: 10 }, (_, i) =>
      change({ cusip: `C${i}`, issuer: `Issuer ${i}`, weight_delta: (0.01 * (10 - i)).toFixed(4) }),
    );
    render(<RecentMoves delta={delta(changes)} phase="loaded" />);

    expect(screen.getAllByText(/Issuer \d/)).toHaveLength(6);
  });
});

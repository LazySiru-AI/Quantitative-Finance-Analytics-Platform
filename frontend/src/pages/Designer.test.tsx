/**
 * The Portfolio Planner page's contract, at render level.
 *
 * The three API modules the page depends on are stubbed at the module boundary (the seam the page
 * actually uses), following `WashSales.test.tsx`. What these tests pin, matching the feature's
 * definition of done:
 *  - the board renders one column per account, empty by default (no cards, a drop hint)
 *  - "Pull current holdings" reads the live portfolio and adds each account's holdings to its
 *    column, then persists via `saveBoard`
 *  - a ticker carrying a wash-sale-disallowed loss in its *current* basis shows the deferred-loss
 *    lock; an open wash window shows the "Wait Nd" badge
 *  - edits persist: placing a ticker calls `saveBoard`
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DesignerBoard, UniverseSymbol } from "@/api/designer";
import type { PortfolioReport } from "@/api/portfolio";
import type { WashSaleTracker } from "@/api/washsales";

const boardMock = vi.fn<() => Promise<DesignerBoard>>();
const universeMock = vi.fn<() => Promise<UniverseSymbol[]>>();
const saveBoardMock = vi.fn<(b: DesignerBoard) => Promise<DesignerBoard>>();
const reportMock = vi.fn<() => Promise<PortfolioReport>>();
const trackerMock = vi.fn<() => Promise<WashSaleTracker>>();

vi.mock("@/api/designer", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/designer")>();
  return {
    ...actual,
    designerApi: {
      board: () => boardMock(),
      universe: () => universeMock(),
      saveBoard: (b: DesignerBoard) => saveBoardMock(b),
    },
  };
});

vi.mock("@/api/portfolio", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/portfolio")>();
  return { ...actual, portfolioApi: { ...actual.portfolioApi, report: () => reportMock() } };
});

vi.mock("@/api/washsales", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/washsales")>();
  return { ...actual, washSalesApi: { ...actual.washSalesApi, tracker: () => trackerMock() } };
});

import Designer from "@/pages/Designer";

function board(tickers: string[] = []): DesignerBoard {
  return {
    columns: [
      {
        account_id: "rh-taxable",
        label: "Robinhood Individual",
        tax_treatment: "taxable",
        account_type: "cash",
        note: "",
        tickers: tickers.map((symbol) => ({ symbol })),
      },
    ],
    updated_at: null,
  };
}

function reportWith(embeddedDeferred: string): PortfolioReport {
  return {
    positions: [
      {
        symbol: "NVDA",
        sector: "SEMI",
        quantity: "5",
        market_value: "900.00",
        unrealized: "-40.00",
        wash_sale_adjustment: embeddedDeferred,
        accounts: [{ account_id: "rh-taxable", quantity: "5" }],
      },
    ],
  } as unknown as PortfolioReport;
}

function trackerOpen(): WashSaleTracker {
  return {
    symbols: [
      {
        symbol: "NVDA",
        window_is_open: true,
        days_until_safe: 7,
        repurchase_safe_on: "2026-09-26",
        deferred_disallowed: "100.00",
        last_sale_date: "2026-08-26",
      },
    ],
  } as unknown as WashSaleTracker;
}

describe("Designer (Portfolio Planner)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    boardMock.mockResolvedValue(board());
    universeMock.mockResolvedValue([{ symbol: "NVDA", sector: "SEMI" }]);
    saveBoardMock.mockImplementation(async (b) => ({ ...b, updated_at: "2026-09-19T00:00:00Z" }));
    reportMock.mockResolvedValue(reportWith("21.70"));
    trackerMock.mockResolvedValue(trackerOpen());
  });

  it("renders one empty column per account by default, with a drop hint", async () => {
    render(<Designer />);
    expect(await screen.findByText("Robinhood Individual")).toBeTruthy();
    expect(screen.getByText("Drag tickers here")).toBeTruthy();
  });

  // A held symbol appears twice (the palette chip and, after pulling, the board card), so card
  // assertions scope to the `.dz-card` container rather than a bare `findByText`.
  async function pulledCard(container: HTMLElement): Promise<HTMLElement> {
    fireEvent.click(await screen.findByRole("button", { name: "Pull current holdings" }));
    return await waitFor(() => {
      const card = container.querySelector<HTMLElement>(".dz-card");
      expect(card).toBeTruthy();
      return card!;
    });
  }

  it("pulls current holdings into each account column and persists", async () => {
    const { container } = render(<Designer />);
    const card = await pulledCard(container);
    expect(within(card).getByText("NVDA")).toBeTruthy();
    await waitFor(() => expect(saveBoardMock).toHaveBeenCalled());
    const saved = saveBoardMock.mock.calls.at(-1)![0];
    expect(saved.columns[0]!.tickers.map((tk) => tk.symbol)).toContain("NVDA");
  });

  it("shows the open wash window and the deferred-loss lock on a pulled ticker", async () => {
    const { container } = render(<Designer />);
    const card = await pulledCard(container);
    expect(within(card).getByText(/Wait 7d/)).toBeTruthy();
    expect(card.className).toContain("has-deferred");
  });

  it("omits the deferred lock when the current basis carries no embedded loss", async () => {
    reportMock.mockResolvedValue(reportWith("0"));
    const { container } = render(<Designer />);
    const card = await pulledCard(container);
    expect(card.className).not.toContain("has-deferred");
  });
});

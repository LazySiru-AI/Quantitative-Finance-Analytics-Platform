/**
 * Activity page: the density/interaction pass pins two things.
 *
 * - The transaction table renders inside a bounded `ScrollRegion` (`.scroll-region`) rather than
 *   pushing the page -- the same primitive every other long table in this app now uses.
 * - The symbol filter is live: typing into it re-queries immediately (no separate "Apply" step)
 *   and `FilterBar`'s own "Showing N of M" note reflects the freshly-fetched page.
 *
 * The API module is stubbed at `@/api/transactions`, the seam the page actually depends on, so
 * these are tests about rendering and wiring, not about JSON parsing.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TransactionPage, TransactionQuery } from "@/api/transactions";

const listMock = vi.fn<(query?: TransactionQuery) => Promise<TransactionPage>>();

vi.mock("@/api/transactions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/transactions")>();
  return {
    ...actual,
    transactionsApi: {
      ...actual.transactionsApi,
      list: (query?: TransactionQuery) => listMock(query),
    },
  };
});

import Activity from "@/pages/Activity";

function row(overrides: Partial<TransactionPage["transactions"][number]> = {}) {
  return {
    txn_id: "t1",
    account_id: "acct-1",
    broker: "webull",
    action: "buy",
    trade_date: "2026-08-01",
    settle_date: "2026-08-03",
    executed_at: null,
    sequence: 0,
    symbol: "AAPL",
    instrument_id: null,
    cusip: null,
    quantity: "10",
    price: "150.00",
    fees: "0.00",
    amount: "-1500.00",
    description: null,
    raw_code: null,
    import_id: "11111111-2222-3333-4444-555555555555",
    source_row: 4,
    ...overrides,
  };
}

function page(overrides: Partial<TransactionPage> = {}): TransactionPage {
  return {
    transactions: [row()],
    total: 1,
    limit: 100,
    offset: 0,
    has_more: false,
    as_of: "2026-08-01",
    earliest: "2026-01-01",
    total_bought: "1500.00",
    total_sold: "0.00",
    net_cash_flow: "-1500.00",
    ...overrides,
  };
}

async function renderActivity(resolved: TransactionPage) {
  listMock.mockResolvedValue(resolved);
  render(<Activity />);
  await screen.findByText("AAPL");
}

beforeEach(() => {
  listMock.mockReset();
});

describe("the transaction table", () => {
  it("renders bounded in a ScrollRegion, not a bare table-wrap", async () => {
    await renderActivity(page());

    const region = document.querySelector(".scroll-region");
    expect(region).not.toBeNull();
    expect(region?.querySelector("table.data-table")).not.toBeNull();
    // A real tab stop and accessible name, not a plain div -- the same contract `ScrollRegion`
    // enforces everywhere else it is used.
    expect(region?.getAttribute("role")).toBe("region");
    expect(region?.getAttribute("aria-label")).toBeTruthy();
  });

  it("shows a pager both above and below the table when there is more than one page", async () => {
    await renderActivity(
      page({
        transactions: [row()],
        total: 250,
        has_more: true,
      }),
    );

    const pagers = document.querySelectorAll(".pager");
    expect(pagers.length).toBe(2);
  });
});

describe("table caption (EXP-15, WCAG 1.3.1)", () => {
  it("captions the ledger table with the shown/total rows and no page clause below one page", async () => {
    await renderActivity(page({ transactions: [row(), row({ txn_id: "t2", symbol: "MSFT" })], total: 2 }));

    const caption = screen.getByText("Transactions, 2 of 2 rows");
    expect(caption.tagName).toBe("CAPTION");
    expect(caption.className).toBe("visually-hidden");
    // The single-page variant carries no page count -- there is nothing to page through.
    expect(screen.queryByText(/page \d+ of \d+/)).toBeNull();
  });

  it("adds the page/limit clause once the ledger spans more than one page", async () => {
    await renderActivity(
      page({ transactions: [row()], total: 250, limit: 100, offset: 100, has_more: true }),
    );

    const caption = screen.getByText("Transactions, 1 of 250 rows, page 2 of 3");
    expect(caption.tagName).toBe("CAPTION");
  });
});

describe("the live symbol filter", () => {
  function filterInput(): HTMLInputElement {
    return screen.getByPlaceholderText("ALL") as HTMLInputElement;
  }

  it("re-queries as soon as the field changes, with no Apply click", async () => {
    await renderActivity(page());
    listMock.mockClear();
    listMock.mockResolvedValue(page({ transactions: [row({ symbol: "MSFT" })], total: 1 }));

    fireEvent.change(filterInput(), { target: { value: "msft" } });

    await waitFor(() => {
      expect(listMock).toHaveBeenCalled();
    });
    const lastCall = listMock.mock.calls.at(-1)?.[0];
    expect(lastCall?.symbol).toBe("MSFT");
    // There is no separate "Apply" button left to click for the symbol filter -- FilterBar's own
    // Clear button is the only button in the row.
    expect(screen.queryByRole("button", { name: /^Apply$/ })).toBeNull();
  });

  it("shows FilterBar's own \"showing N of M\" note against the freshly-fetched page", async () => {
    listMock.mockResolvedValue(
      page({ transactions: [row(), row({ txn_id: "t2", symbol: "MSFT" })], total: 37 }),
    );
    render(<Activity />);
    await screen.findByText("MSFT");

    expect(screen.getByText(/Showing 2 of 37/)).toBeTruthy();
  });

  it("clears the filter and re-queries with no symbol via FilterBar's Clear button", async () => {
    await renderActivity(page());
    fireEvent.change(filterInput(), { target: { value: "AAPL" } });
    await waitFor(() => expect(listMock.mock.calls.at(-1)?.[0]?.symbol).toBe("AAPL"));

    fireEvent.click(screen.getByRole("button", { name: /clear/i }));

    await waitFor(() => {
      expect(listMock.mock.calls.at(-1)?.[0]?.symbol).toBeUndefined();
    });
    expect(filterInput().value).toBe("");
  });
});

describe("loading and error states", () => {
  it("shows the loading placeholder before the fetch resolves", () => {
    listMock.mockReturnValue(new Promise<TransactionPage>(() => {}));
    render(<Activity />);
    expect(screen.getByText(/Loading activity/)).toBeTruthy();
  });

  it("shows the no-ledger empty state when an unfiltered fetch returns nothing", async () => {
    listMock.mockResolvedValue(page({ transactions: [], total: 0 }));
    render(<Activity />);
    await screen.findByText(/import a broker export above/);
  });
});

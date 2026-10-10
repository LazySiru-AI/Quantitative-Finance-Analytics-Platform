/**
 * The wash-sale tracker client's parsing contract.
 *
 * Matches the idiom in `money.test.ts` / `labels.test.ts`: exercise the actual exported shape
 * rather than trusting the type annotations alone, since a `DecimalString` field is only as safe
 * as the code that never calls `Number()` or `parseFloat()` on it. `fetch` is stubbed directly
 * (per `src/test/setup.ts`, the global throws on any unstubbed call) since this file tests the API
 * layer itself, not a page consuming it.
 */
import { describe, expect, it, vi } from "vitest";

import {
  washSalesApi,
  type WashSaleTracker,
  type WashSaleTrackerSale,
  type WashSaleTrackerSymbol,
} from "@/api/washsales";

function stubFetchOnce(body: unknown, ok = true, status = 200): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok,
      status,
      statusText: ok ? "OK" : "Error",
      json: async () => body,
      text: async () => JSON.stringify(body),
    })),
  );
}

function wellFormedSale(overrides: Partial<WashSaleTrackerSale> = {}): WashSaleTrackerSale {
  return {
    disposal_id: "disp-1",
    sale_date: "2026-07-15",
    account_id: "rh-taxable",
    quantity_sold: "7",
    quantity_replaced: "7",
    loss_amount: "26.25",
    disallowed_loss: "26.25",
    permanently_disallowed: false,
    replacement_account_ids: ["rh-taxable"],
    window_closes_on: "2026-08-15",
    ...overrides,
  };
}

function wellFormedSymbol(overrides: Partial<WashSaleTrackerSymbol> = {}): WashSaleTrackerSymbol {
  return {
    symbol: "NVDA",
    deferred_disallowed: "1234.56",
    permanently_disallowed: "0.00",
    event_count: 3,
    loss_sale_count: 2,
    first_sale_date: "2026-03-02",
    last_sale_date: "2026-07-15",
    repurchase_safe_on: "2026-08-15",
    days_until_safe: 0,
    window_is_open: false,
    accounts: ["rh-taxable"],
    sales: [wellFormedSale()],
    ...overrides,
  };
}

function wellFormedTracker(overrides: Partial<WashSaleTracker> = {}): WashSaleTracker {
  return {
    as_of: "2026-08-16",
    generated_at: "2026-08-16T20:00:00Z",
    total_deferred: "94998.50",
    total_permanently_disallowed: "2790.52",
    open_window_count: 46,
    symbol_count: 81,
    symbols: [wellFormedSymbol()],
    ...overrides,
  };
}

describe("washSalesApi.tracker", () => {
  it("fetches the whole-ledger endpoint with no query parameters", async () => {
    const payload = wellFormedTracker();
    stubFetchOnce(payload);

    const result = await washSalesApi.tracker();

    expect(fetch).toHaveBeenCalledTimes(1);
    const call = vi.mocked(fetch).mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    expect(String(call[0])).toBe("/api/tax/wash-sales");
    expect(result).toEqual(payload);
  });

  it("parses a well-formed response into the exported types", async () => {
    const payload = wellFormedTracker();
    stubFetchOnce(payload);

    const result = await washSalesApi.tracker();

    expect(result.as_of).toBe("2026-08-16");
    expect(result.generated_at).toBe("2026-08-16T20:00:00Z");
    expect(result.open_window_count).toBe(46);
    expect(result.symbol_count).toBe(81);
    expect(result.symbols).toHaveLength(1);

    const symbol = result.symbols[0];
    if (!symbol) throw new Error("expected one symbol");
    expect(symbol.symbol).toBe("NVDA");
    expect(symbol.event_count).toBe(3);
    expect(symbol.loss_sale_count).toBe(2);
    expect(symbol.window_is_open).toBe(false);
    expect(symbol.accounts).toEqual(["rh-taxable"]);
    expect(symbol.sales).toHaveLength(1);

    const sale = symbol.sales[0];
    if (!sale) throw new Error("expected one sale");
    expect(sale.disposal_id).toBe("disp-1");
    expect(sale.sale_date).toBe("2026-07-15");
    expect(sale.permanently_disallowed).toBe(false);
    expect(sale.replacement_account_ids).toEqual(["rh-taxable"]);
    expect(sale.window_closes_on).toBe("2026-08-15");
  });

  it("keeps every money field a string, never coerced to number", async () => {
    // The precise values matter less than the type: a real figure like "94998.50" would silently
    // become 94998.5 (losing the trailing zero) or worse if it ever round-tripped through
    // `Number()`/`parseFloat()`. Asserting `typeof === "string"` on the actual parsed result is
    // what catches a future edit that starts coercing.
    const payload = wellFormedTracker();
    stubFetchOnce(payload);

    const result = await washSalesApi.tracker();

    expect(typeof result.total_deferred).toBe("string");
    expect(typeof result.total_permanently_disallowed).toBe("string");
    expect(result.total_deferred).toBe("94998.50");
    expect(result.total_permanently_disallowed).toBe("2790.52");

    const symbol = result.symbols[0];
    if (!symbol) throw new Error("expected one symbol");
    expect(typeof symbol.deferred_disallowed).toBe("string");
    expect(typeof symbol.permanently_disallowed).toBe("string");

    const sale = symbol.sales[0];
    if (!sale) throw new Error("expected one sale");
    expect(typeof sale.quantity_sold).toBe("string");
    expect(typeof sale.quantity_replaced).toBe("string");
    expect(typeof sale.loss_amount).toBe("string");
    expect(typeof sale.disallowed_loss).toBe("string");
  });

  it("never sums deferred and permanently-disallowed totals -- they stay independent fields", () => {
    // Not a runtime assertion so much as a guard against a future refactor collapsing these into
    // one "impact" figure, per the module docstring on `WashSaleTracker`. A single combined number
    // would misstate money that is not equally at stake: `total_deferred` still exists on a
    // replacement lot's basis, `total_permanently_disallowed` is destroyed outright.
    const tracker = wellFormedTracker({
      total_deferred: "100.00",
      total_permanently_disallowed: "50.00",
    });
    expect(tracker.total_deferred).not.toBe(tracker.total_permanently_disallowed);
    expect(Object.keys(tracker)).not.toContain("total_impact");
    expect(Object.keys(tracker)).not.toContain("wash_sale_impact");
  });

  it("handles an empty symbols array", async () => {
    const payload = wellFormedTracker({
      symbols: [],
      symbol_count: 0,
      open_window_count: 0,
      total_deferred: "0.00",
      total_permanently_disallowed: "0.00",
    });
    stubFetchOnce(payload);

    const result = await washSalesApi.tracker();

    expect(result.symbols).toEqual([]);
    expect(result.symbol_count).toBe(0);
  });

  it("handles a symbol with an empty sales array", async () => {
    const payload = wellFormedTracker({
      symbols: [wellFormedSymbol({ sales: [] })],
    });
    stubFetchOnce(payload);

    const result = await washSalesApi.tracker();

    const symbol = result.symbols[0];
    if (!symbol) throw new Error("expected one symbol");
    expect(symbol.sales).toEqual([]);
    // The rollup figures are still present and untouched even with no sale-level detail.
    expect(symbol.deferred_disallowed).toBe("1234.56");
  });

  it("throws ApiRequestError on a non-ok response", async () => {
    stubFetchOnce({ detail: "boom" }, false, 500);

    await expect(washSalesApi.tracker()).rejects.toMatchObject({
      name: "ApiRequestError",
      status: 500,
    });
  });
});

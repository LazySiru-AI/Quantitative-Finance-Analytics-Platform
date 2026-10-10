/**
 * Unit coverage for the pure helpers `Portfolio.tsx`'s split pulled into this module -- the account
 * rail's badge formatting in particular, since that logic is new (not merely relocated) and the
 * full-page `Portfolio.test.tsx` suite only exercises it indirectly through one or two fixtures.
 */
import { describe, expect, it } from "vitest";

import type { AccountPosition, AccountSummary, PortfolioReport, Position } from "@/api/portfolio";

import type { AccountCashBalance } from "@/api/portfolio";

import { accountTabBadge, buildScopedPositionRows, computeAccountMarketValue, formatCompactMoney } from "./aggregates";

function accountCash(overrides: Partial<AccountCashBalance> = {}): AccountCashBalance {
  return {
    account_id: "rh-taxable",
    account_label: "Robinhood Taxable",
    broker: "Robinhood",
    tax_treatment: "taxable",
    verdict: "derived",
    balance: "500.00",
    settled: "500.00",
    unsettled: "0",
    unsettled_next_date: null,
    unsettled_full_date: null,
    reason: null,
    missing_opening_balance: null,
    coverage_start: "2026-01-01",
    coverage_end: "2026-08-06",
    declared_as_of: null,
    declared_note: null,
    derived_balance: null,
    ...overrides,
  };
}

function accountPosition(overrides: Partial<AccountPosition> = {}): AccountPosition {
  return {
    account_id: "rh-taxable",
    account_label: "Robinhood Taxable",
    broker: "Robinhood",
    quantity: "50",
    cost_basis: "1205.00",
    lot_count: 1,
    basis_uncertain: false,
    fees_unknown: false,
    ...overrides,
  };
}

function position(overrides: Partial<Position> = {}): Position {
  return {
    instrument_id: "i-soxl",
    symbol: "SOXL",
    quantity: "50",
    cost_basis: "1205.00",
    basis_per_share: "24.10",
    price: "26.00",
    price_as_of: "2026-08-13",
    market_value: "1300.00",
    unrealized: "95.00",
    unrealized_pct: 0.0788,
    weight_pct: 1,
    sector: "Unclassified",
    previous_close: null,
    day_change: null,
    day_change_pct: null,
    short_term_quantity: "50",
    long_term_quantity: "0",
    earliest_acquired: "2026-03-02",
    latest_acquired: "2026-03-02",
    lot_count: 1,
    basis_uncertain: false,
    fees_unknown: false,
    wash_sale_adjustment: "0.00",
    accounts: [],
    ...overrides,
  };
}

function report(overrides: Partial<PortfolioReport> = {}): PortfolioReport {
  return {
    as_of: "2026-08-06",
    generated_at: "2026-08-14T00:00:00Z",
    positions: [],
    total_cost_basis: "0.00",
    total_market_value: null,
    total_unrealized: null,
    total_unrealized_pct: null,
    priced_position_count: 0,
    unpriced_symbols: [],
    cash_balance: null,
    settled_cash: null,
    unsettled_cash: null,
    unsettled_next_date: null,
    unsettled_full_date: null,
    total_equity: null,
    equity_is_complete: false,
    accounts_without_cash: [],
    cash_by_account: [],
    positions_with_uncertain_basis: 0,
    positions_with_unknown_fees: 0,
    warnings: [],
    warning_groups: [],
    accounts: [],
    open_account_count: 0,
    total_day_change: null,
    total_day_change_pct: null,
    excluded_closed_positions: 0,
    excluded_closed_symbols: [],
    ...overrides,
  };
}

function accountSummary(overrides: Partial<AccountSummary> = {}): AccountSummary {
  return {
    account_id: "rh-taxable",
    label: "Robinhood Taxable",
    broker: "Robinhood",
    tax_treatment: "taxable",
    account_type: "cash",
    status: "open",
    realized_gain: "10.00",
    realized_proceeds: "10.00",
    disposed_cost_basis: "0.00",
    position_count: 1,
    ...overrides,
  };
}

describe("formatCompactMoney", () => {
  it("renders an em dash for null, never a fabricated $0", () => {
    expect(formatCompactMoney(null)).toBe("—");
  });

  it("renders sub-thousand figures at whole-dollar precision", () => {
    expect(formatCompactMoney("850.00")).toBe("$850");
  });

  it("renders thousands with one decimal and a 'k' suffix", () => {
    expect(formatCompactMoney("41234.00")).toBe("$41.2k");
  });

  it("renders millions with one decimal and an 'M' suffix", () => {
    expect(formatCompactMoney("1234567.00")).toBe("$1.2M");
  });

  it("keeps the sign on a negative figure", () => {
    expect(formatCompactMoney("-41234.00")).toBe("-$41.2k");
  });
});

describe("computeAccountMarketValue", () => {
  it("sums only the given account's slices of priced positions", () => {
    const wbSlice = accountPosition({ account_id: "wb-margin", quantity: "10" });
    const rhSlice = accountPosition({ account_id: "rh-taxable", quantity: "50" });
    const r = report({
      positions: [position({ price: "26.00", accounts: [wbSlice, rhSlice] })],
    });
    expect(computeAccountMarketValue(r, "rh-taxable")).toBe("1300.00");
    expect(computeAccountMarketValue(r, "wb-margin")).toBe("260.00");
  });

  it("returns null, not a fabricated zero, when the account holds nothing priced", () => {
    const r = report({
      positions: [position({ price: null, market_value: null, accounts: [accountPosition()] })],
    });
    expect(computeAccountMarketValue(r, "rh-taxable")).toBeNull();
    expect(computeAccountMarketValue(r, "no-such-account")).toBeNull();
  });
});

describe("accountTabBadge", () => {
  it("joins the account's position count and compact market value with ' · '", () => {
    const r = report({
      positions: [position({ price: "26.00", accounts: [accountPosition({ quantity: "50" })] })],
    });
    expect(accountTabBadge(r, accountSummary({ position_count: 1 }))).toBe("1 · $1.3k");
  });

  it("still names the position count when the account holds nothing priced", () => {
    const r = report({ positions: [] });
    expect(accountTabBadge(r, accountSummary({ account_id: "wb-roth", position_count: 0 }))).toBe("0 · —");
  });
});

describe("buildScopedPositionRows", () => {
  /**
   * The tax-treatment view's scope control (all / taxable / retirement, optionally narrowed to one
   * account) reads through this. Fixture: SOXL held in a taxable account (rh-taxable, 30 shares) AND
   * in a Roth account (wb-roth, 20 shares) of the SAME instrument, plus NVDA held only in the taxable
   * account -- so "taxable only" must show both symbols summed to the taxable slice alone, and
   * "retirement only" must show SOXL alone at the Roth slice alone, never the combined 50 shares.
   */
  const taxableSlice = accountPosition({ account_id: "rh-taxable", quantity: "30", cost_basis: "700.00" });
  const rothSlice = accountPosition({
    account_id: "wb-roth",
    account_label: "Webull Roth",
    broker: "Webull",
    quantity: "20",
    cost_basis: "400.00",
  });
  const nvdaTaxableSlice = accountPosition({ account_id: "rh-taxable", quantity: "5", cost_basis: "40.00" });

  function twoAccountReport() {
    return report({
      positions: [
        position({
          instrument_id: "i-soxl",
          symbol: "SOXL",
          price: "26.00",
          accounts: [taxableSlice, rothSlice],
        }),
        position({
          instrument_id: "i-nvda",
          symbol: "NVDA",
          price: "10.00",
          accounts: [nvdaTaxableSlice],
        }),
      ],
      cash_by_account: [
        accountCash({ account_id: "rh-taxable", tax_treatment: "taxable", balance: "100.00" }),
        accountCash({
          account_id: "wb-roth",
          account_label: "Webull Roth",
          broker: "Webull",
          tax_treatment: "roth_ira",
          balance: "50.00",
        }),
      ],
    });
  }

  it("returns every account's rows and cash when no scope is given", () => {
    const { rows, cashTotal } = buildScopedPositionRows(twoAccountReport(), {});
    expect(rows.map((r) => r.symbol).sort()).toEqual(["NVDA", "SOXL"]);
    const soxl = rows.find((r) => r.symbol === "SOXL");
    // Both accounts' quantity summed -- 30 + 20 -- never one slice alone.
    expect(soxl?.quantity).toBe("50.00");
    expect(cashTotal).toBe("150.00");
  });

  it("narrows to the taxable group's own slice of each instrument, excluding the Roth's share", () => {
    const { rows, cashTotal } = buildScopedPositionRows(twoAccountReport(), { treatment: "taxable" });
    expect(rows.map((r) => r.symbol).sort()).toEqual(["NVDA", "SOXL"]);
    const soxl = rows.find((r) => r.symbol === "SOXL");
    expect(soxl?.quantity).toBe("30");
    expect(soxl?.marketValue).toBe("780.00");
    expect(cashTotal).toBe("100.00");
  });

  it("narrows to the retirement group's own slice, excluding NVDA (taxable-only) entirely", () => {
    const { rows, cashTotal } = buildScopedPositionRows(twoAccountReport(), { treatment: "retirement" });
    expect(rows.map((r) => r.symbol)).toEqual(["SOXL"]);
    expect(rows[0]?.quantity).toBe("20");
    expect(rows[0]?.marketValue).toBe("520.00");
    expect(cashTotal).toBe("50.00");
  });

  it("narrows to taxable AND one account together -- the combined case", () => {
    const { rows, cashTotal } = buildScopedPositionRows(twoAccountReport(), {
      treatment: "taxable",
      accountId: "rh-taxable",
    });
    expect(rows.map((r) => r.symbol).sort()).toEqual(["NVDA", "SOXL"]);
    expect(rows.find((r) => r.symbol === "SOXL")?.quantity).toBe("30");
    expect(cashTotal).toBe("100.00");
  });

  it("returns nothing when the account and treatment scopes disagree", () => {
    // wb-roth is a Roth account, not taxable -- asking for both together must exclude it, not fall
    // back to matching either condition alone.
    const { rows, cashTotal } = buildScopedPositionRows(twoAccountReport(), {
      treatment: "taxable",
      accountId: "wb-roth",
    });
    expect(rows).toEqual([]);
    expect(cashTotal).toBeNull();
  });

  it("narrows to a single account regardless of treatment when only accountId is given", () => {
    const { rows, cashTotal } = buildScopedPositionRows(twoAccountReport(), { accountId: "wb-roth" });
    expect(rows.map((r) => r.symbol)).toEqual(["SOXL"]);
    expect(rows[0]?.quantity).toBe("20");
    expect(cashTotal).toBe("50.00");
  });
});

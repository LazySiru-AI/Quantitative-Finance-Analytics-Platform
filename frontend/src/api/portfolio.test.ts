/**
 * Wire-type contract for `@/api/portfolio`.
 *
 * The primary thing worth testing here is that a `PortfolioReport` fixture carrying every field
 * this module declares -- including the account-status/sector/day-change fields added alongside
 * `AccountSummary` -- actually type-checks against the exported interfaces. TypeScript gives no
 * runtime signal when an interface and its real callers drift, so a fixture that compiles is the
 * check: if a field is renamed, dropped, or given the wrong wire shape, this file fails to build
 * rather than failing an assertion. The `describe` blocks around it exercise the existing
 * money/percent helpers against values shaped like the new fields (`day_change`, `day_change_pct`,
 * an `AccountSummary`'s realized figures), the same way `money.test.ts` already exercises them
 * against `Position`-shaped values -- not because this module adds new helpers (it does not), but
 * because a fixture with no runtime assertions at all would silently stop testing anything the
 * moment someone "cleaned up" the unused import.
 */
import { describe, expect, it } from "vitest";

import type { AccountSummary, PortfolioReport, Position } from "@/api/portfolio";
import {
  compareMoneyDesc,
  formatSignedFractionPct,
  formatSignedMoney,
  formatWeightPct,
  moneyTone,
  sumMoney,
  taxTreatmentLabel,
} from "@/api/portfolio";

function makeAccountSummary(overrides: Partial<AccountSummary> = {}): AccountSummary {
  return {
    account_id: "rh-taxable",
    label: "Robinhood Taxable",
    broker: "robinhood",
    tax_treatment: "taxable",
    account_type: "cash",
    status: "open",
    realized_gain: "1250.00",
    realized_proceeds: "9000.00",
    disposed_cost_basis: "7750.00",
    position_count: 4,
    ...overrides,
  };
}

function makePosition(overrides: Partial<Position> = {}): Position {
  return {
    instrument_id: "inst-nvda",
    symbol: "NVDA",
    quantity: "10",
    cost_basis: "1000.00",
    basis_per_share: "100.00",
    price: "120.00",
    price_as_of: "2026-09-04",
    market_value: "1200.00",
    unrealized: "200.00",
    unrealized_pct: 0.2,
    weight_pct: 0.5,
    sector: "SEMI",
    previous_close: "115.00",
    day_change: "50.00",
    day_change_pct: 0.0435,
    short_term_quantity: "10",
    long_term_quantity: "0",
    earliest_acquired: "2026-01-01",
    latest_acquired: "2026-01-01",
    lot_count: 1,
    basis_uncertain: false,
    fees_unknown: false,
    wash_sale_adjustment: "0",
    accounts: [],
    ...overrides,
  };
}

function makeReport(overrides: Partial<PortfolioReport> = {}): PortfolioReport {
  return {
    unsettled_next_date: null,
    unsettled_full_date: null,
    as_of: "2026-09-05",
    generated_at: "2026-09-05T00:00:00Z",
    positions: [makePosition()],
    total_cost_basis: "1000.00",
    total_market_value: "1200.00",
    total_unrealized: "200.00",
    total_unrealized_pct: 0.2,
    priced_position_count: 1,
    unpriced_symbols: [],
    cash_balance: "500.00",
    settled_cash: "500.00",
    unsettled_cash: "0.00",
    total_equity: "1700.00",
    equity_is_complete: true,
    accounts_without_cash: [],
    cash_by_account: [],
    positions_with_uncertain_basis: 0,
    positions_with_unknown_fees: 0,
    warnings: [],
    warning_groups: [],
    accounts: [
      makeAccountSummary(),
      makeAccountSummary({
        account_id: "rh-roth",
        label: "Robinhood Roth (closed)",
        tax_treatment: "roth_ira",
        account_type: "retirement",
        status: "closed",
        realized_gain: "-300.00",
        position_count: 0,
      }),
    ],
    open_account_count: 1,
    total_day_change: "50.00",
    total_day_change_pct: 0.0435,
    excluded_closed_positions: 2,
    excluded_closed_symbols: ["ARKK", "SOFI"],
    ...overrides,
  };
}

describe("PortfolioReport fixture (section 5 wire shape)", () => {
  it("type-checks with every new field present and reads back unchanged", () => {
    const report = makeReport();

    expect(report.accounts).toHaveLength(2);
    expect(report.open_account_count).toBe(1);
    expect(report.total_day_change).toBe("50.00");
    expect(report.total_day_change_pct).toBeCloseTo(0.0435);
    expect(report.excluded_closed_positions).toBe(2);
    expect(report.excluded_closed_symbols).toEqual(["ARKK", "SOFI"]);
  });

  it("accepts null on every field the contract marks nullable", () => {
    const report = makeReport({
      total_day_change: null,
      total_day_change_pct: null,
    });

    expect(report.total_day_change).toBeNull();
    expect(report.total_day_change_pct).toBeNull();
  });

  it("keeps excluded_closed_symbols sorted-and-deduped as the contract requires the server to send", () => {
    // This module does not enforce the sort/dedup itself (that is the server's job per the
    // contract) -- this asserts the fixture is a faithful stand-in for what the wire actually
    // sends, so downstream tests built on this fixture are not accidentally testing against an
    // unrealistic shape.
    const report = makeReport();
    const sorted = [...report.excluded_closed_symbols].sort();
    expect(report.excluded_closed_symbols).toEqual(sorted);
    expect(new Set(report.excluded_closed_symbols).size).toBe(report.excluded_closed_symbols.length);
  });
});

describe("Position (section 5 additions: sector/day-change)", () => {
  it("carries a non-null sector even for an unmapped symbol", () => {
    const position = makePosition({ sector: "Unclassified", symbol: "ZZZZ" });
    expect(position.sector).toBe("Unclassified");
  });

  it("keeps previous_close/day_change/day_change_pct null together when unpriced", () => {
    const position = makePosition({
      price: null,
      market_value: null,
      previous_close: null,
      day_change: null,
      day_change_pct: null,
    });
    expect(position.previous_close).toBeNull();
    expect(position.day_change).toBeNull();
    expect(position.day_change_pct).toBeNull();
  });

  it("formats day_change with the existing signed-money/percent helpers", () => {
    const position = makePosition();
    expect(formatSignedMoney(position.day_change!)).toBe("+$50.00");
    expect(formatSignedFractionPct(position.day_change_pct)).toBe("+4.3%");
    expect(moneyTone(position.day_change!)).toBe("pos");
  });

  it("formats a negative day_change without a leading plus", () => {
    const position = makePosition({ day_change: "-12.34", day_change_pct: -0.02 });
    expect(formatSignedMoney(position.day_change!)).toBe("-$12.34");
    expect(formatSignedFractionPct(position.day_change_pct)).toBe("-2.0%");
    expect(moneyTone(position.day_change!)).toBe("neg");
  });

  it("still formats weight_pct on the unsigned 0-1 scale used elsewhere in this contract", () => {
    const position = makePosition({ weight_pct: 0.153 });
    expect(formatWeightPct(position.weight_pct)).toBe("15.3%");
  });
});

describe("AccountSummary (new interface)", () => {
  it("carries an all-time realized result independent of any status", () => {
    const open = makeAccountSummary();
    const closed = makeAccountSummary({ status: "closed", account_id: "sofi-taxable" });
    expect(open.status).toBe("open");
    expect(closed.status).toBe("closed");
    // Both shapes are the same interface -- status does not gate which fields are present.
    expect(closed.realized_gain).toBe("1250.00");
  });

  it("sums realized_gain across accounts with the existing exact-money helper", () => {
    const accounts = [
      makeAccountSummary({ realized_gain: "100.00" }),
      makeAccountSummary({ realized_gain: "-40.50" }),
      makeAccountSummary({ realized_gain: "0.005" }),
    ];
    expect(sumMoney(accounts.map((a) => a.realized_gain))).toBe("59.51");
  });

  it("sorts accounts by realized_gain with the existing exact comparator", () => {
    const accounts = [
      makeAccountSummary({ account_id: "a", realized_gain: "10.00" }),
      makeAccountSummary({ account_id: "b", realized_gain: "500.00" }),
      makeAccountSummary({ account_id: "c", realized_gain: "-5.00" }),
    ];
    const sorted = [...accounts].sort((x, y) => compareMoneyDesc(x.realized_gain, y.realized_gain));
    expect(sorted.map((a) => a.account_id)).toEqual(["b", "a", "c"]);
  });

  it("reuses taxTreatmentLabel for AccountSummary.tax_treatment the same way it does for cash balances", () => {
    const roth = makeAccountSummary({ tax_treatment: "roth_ira" });
    const taxable = makeAccountSummary({ tax_treatment: "taxable" });
    expect(taxTreatmentLabel(roth.tax_treatment)).not.toBe(taxTreatmentLabel(taxable.tax_treatment));
  });

  it("accepts every account_type string the contract documents without narrowing the type", () => {
    // account_type is a bare `string` on the wire type (matching the backend's `str`, not a
    // closed union) -- assert that stays true by assigning values the contract lists in prose.
    const types: string[] = ["cash", "margin", "retirement"];
    for (const account_type of types) {
      const account = makeAccountSummary({ account_type });
      expect(account.account_type).toBe(account_type);
    }
  });
});

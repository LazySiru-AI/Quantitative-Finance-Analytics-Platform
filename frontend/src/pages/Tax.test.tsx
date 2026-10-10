/**
 * The uncertain-basis caveat's honesty rules, at render level.
 *
 * The caveat used to say only "N disposals above used a cost basis the replay could not
 * establish" -- a row count with no size attached. On a real ledger such rows can be a small share of
 * the count but most of the reported gain, so a reader who trusted the row count concluded the
 * headline figure was approximately right. It was mostly missing basis. Every assertion below
 * guards against that regression coming back in a smaller, easier-to-miss form: a percentage
 * silently dropped, a `NaN%` on a denominator of zero, or a money figure that quietly round-tripped
 * through `parseFloat` and lost precision a `DecimalString` was carrying on the wire.
 *
 * The API module is stubbed rather than `fetch`, matching `Portfolio.test.tsx` -- it is the seam
 * the page actually depends on.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  formatMoney,
  moneyPercentOf,
  type GainRow,
  type GainsReport,
  type Form8949Report,
  type Form8949Row,
  type TaxReport,
  type WashSaleEvent,
  type WashSaleSummary,
  type WashSaleSymbolSummary,
} from "@/api/tax";
import type { TransactionPage, TransactionQuery, TransactionRow } from "@/api/transactions";
import type { WashSaleTracker, WashSaleTrackerSymbol } from "@/api/washsales";

/**
 * `(year, page)`, not `()` -- the paging tests below need to see exactly what `Tax.tsx` asked for
 * (`{ limit, offset }`), which a no-argument stub would silently discard. Every pre-existing test
 * that never inspects `reportMock.mock.calls` is unaffected: it only ever reads the resolved value.
 */
const reportMock = vi.fn<(year?: number, page?: { limit?: number; offset?: number }) => Promise<TaxReport>>();

vi.mock("@/api/tax", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/tax")>();
  return {
    ...actual,
    taxApi: {
      ...actual.taxApi,
      report: (year: number, page?: { limit?: number; offset?: number }) => reportMock(year, page),
    },
  };
});

// Only reached if the report is empty, which none of these tests exercise deliberately -- but
// stubbed anyway, matching `Portfolio.test.tsx`, so a bug that did reach it fails loudly instead
// of hanging on an unstubbed rejection.
vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    api: { ...actual.api, stores: () => Promise.reject(new Error("stores not stubbed")) },
  };
});

// The page now resolves its default tax year from the most recent transaction on mount (see
// `resolveDefaultYear` in `Tax.tsx`), so every render -- not only the tests about that behaviour --
// goes through `transactionsApi.list`. Stubbed at the module boundary like the other two mocks
// above, with a `beforeEach` default (a single transaction in `thisYear`) so tests that don't care
// about the default year don't have to set one up themselves.
const transactionsListMock = vi.fn<(query?: TransactionQuery) => Promise<TransactionPage>>();

vi.mock("@/api/transactions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/transactions")>();
  return {
    ...actual,
    transactionsApi: {
      ...actual.transactionsApi,
      list: (query?: TransactionQuery) => transactionsListMock(query),
    },
  };
});

// The Wash sales tab now also mounts the whole-ledger open-window tracker folded in from the former
// `/wash-sales` page, which fetches on mount. Stubbed at the same module boundary as the three above
// so it resolves deterministically instead of hitting the setup's throwing `fetch`. Defaulted in the
// `beforeEach` below to an empty tracker, so tests that are not about it need no setup of their own.
const trackerMock = vi.fn<() => Promise<WashSaleTracker>>();

vi.mock("@/api/washsales", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/washsales")>();
  return {
    ...actual,
    washSalesApi: { ...actual.washSalesApi, tracker: () => trackerMock() },
  };
});

const { default: Tax } = await import("@/pages/Tax");

function gainRow(overrides: Partial<GainRow> = {}): GainRow {
  return {
    disposal_id: "d1",
    instrument_id: "i1",
    symbol: "TEST",
    account_id: "acct-1",
    account_label: "Test Account",
    quantity: "10",
    lot_id: "lot1",
    lot_method: "fifo",
    acquired_date: "2026-01-01",
    holding_start: "2026-01-01",
    disposed_date: "2026-02-01",
    term: "short",
    proceeds: "1000.00",
    cost_basis: "900.00",
    fees: "0.00",
    gain_loss: "100.00",
    disallowed_loss: "0.00",
    permanently_disallowed_loss: "0.00",
    permanently_disallowed: false,
    reportable_gain_loss: "100.00",
    is_wash_sale: false,
    basis_uncertain: false,
    fees_unknown: false,
    ...overrides,
  };
}

function gainsReport(overrides: Partial<GainsReport> = {}): GainsReport {
  return {
    start: "2026-01-01",
    end: "2026-12-31",
    rows: [],
    short_term_proceeds: "0.00",
    short_term_basis: "0.00",
    short_term_gain: "0.00",
    long_term_proceeds: "0.00",
    long_term_basis: "0.00",
    long_term_gain: "0.00",
    disallowed_loss_total: "0.00",
    permanently_disallowed_total: "0.00",
    excluded_account_ids: [],
    rows_with_uncertain_basis: 0,
    gain_on_uncertain_basis: "0.00",
    proceeds_on_uncertain_basis: "0.00",
    basis_on_uncertain_basis: "0.00",
    rows_with_unknown_fees: 0,
    ...overrides,
  };
}

function form8949Report(overrides: Partial<Form8949Report> = {}): Form8949Report {
  return {
    rows: [],
    short_term_total_proceeds: "0.00",
    short_term_total_basis: "0.00",
    short_term_total_adjustment: "0.00",
    short_term_total_gain: "0.00",
    long_term_total_proceeds: "0.00",
    long_term_total_basis: "0.00",
    long_term_total_adjustment: "0.00",
    long_term_total_gain: "0.00",
    ...overrides,
  };
}

function taxReport(overrides: Partial<TaxReport> = {}): TaxReport {
  return {
    tax_year: 2026,
    generated_at: "2026-08-15T00:00:00Z",
    gains: gainsReport(),
    form8949: form8949Report(),
    wash_sales: [],
    unsettled: [],
    warnings: [],
    warning_groups: [],
    wash_sale_summary: null,
    ...overrides,
  };
}

function washSaleSymbolSummary(
  overrides: Partial<WashSaleSymbolSummary> = {},
): WashSaleSymbolSummary {
  return {
    symbol: "TEST",
    deferred_disallowed: "500.00",
    permanently_disallowed: "0.00",
    event_count: 1,
    loss_sale_count: 1,
    first_sale_date: "2026-01-15",
    last_sale_date: "2026-01-15",
    repurchase_safe_on: "2026-02-15",
    days_until_safe: 0,
    window_is_open: false,
    accounts: ["acct-1"],
    ...overrides,
  };
}

function washSaleSummary(overrides: Partial<WashSaleSummary> = {}): WashSaleSummary {
  return {
    as_of: "2026-08-15",
    symbols: [washSaleSymbolSummary()],
    total_deferred: "500.00",
    total_permanently_disallowed: "0.00",
    open_window_count: 0,
    ...overrides,
  };
}

/**
 * Minimal `WashSaleEvent`, used only to keep `taxReport()` out of the page's "empty year" state in
 * the per-symbol-panel tests below -- `isEmptyReport` does not look at `wash_sale_summary`, so a
 * report with a summary but nothing else non-empty is, correctly, still "empty" by that check and
 * renders the import-nudge placeholder instead of the panel under test.
 */
function washSaleEvent(overrides: Partial<WashSaleEvent> = {}): WashSaleEvent {
  return {
    event_id: "w1",
    disposal_id: "d1",
    instrument_id: "i1",
    symbol: "TEST",
    sale_date: "2026-01-15",
    sale_account_id: "acct-1",
    quantity_sold: "5",
    loss_amount: "500.00",
    quantity_replaced: "5",
    disallowed_loss: "500.00",
    replacement_txn_ids: [],
    replacement_lot_ids: [],
    replacement_account_ids: ["acct-1"],
    permanently_disallowed: false,
    basis_added_to_lot_id: null,
    holding_period_tolled_to: null,
    is_chained: false,
    ...overrides,
  };
}

function form8949Row(overrides: Partial<Form8949Row> = {}): Form8949Row {
  return {
    box: "A",
    description: "10 sh TEST",
    date_acquired: "2026-01-01",
    date_sold: "2026-02-01",
    proceeds: "1000.00",
    cost_basis: "900.00",
    adjustment_code: null,
    adjustment_amount: "0.00",
    gain_loss: "100.00",
    disposal_id: "d1",
    ...overrides,
  };
}

function transactionRow(overrides: Partial<TransactionRow> = {}): TransactionRow {
  return {
    txn_id: "t1",
    account_id: "acct-1",
    broker: "robinhood",
    action: "buy",
    trade_date: "2026-01-15",
    settle_date: null,
    executed_at: null,
    sequence: 0,
    symbol: "TEST",
    instrument_id: "i1",
    cusip: null,
    quantity: "10",
    price: "10.00",
    fees: "0.00",
    amount: "-100.00",
    description: null,
    raw_code: null,
    import_id: "imp1",
    source_row: 1,
    ...overrides,
  };
}

function transactionPage(overrides: Partial<TransactionPage> = {}): TransactionPage {
  return {
    transactions: [],
    total: 0,
    limit: 1,
    offset: 0,
    has_more: false,
    as_of: null,
    earliest: null,
    total_bought: "0.00",
    total_sold: "0.00",
    net_cash_flow: "0.00",
    ...overrides,
  };
}

/** The real current year at test-run time -- assertions below are shaped around it rather than a
 *  literal like `2026`, so the suite does not go stale the day the calendar turns. */
const thisYear = new Date().getFullYear();

/**
 * Renders `<Tax />` under a `MemoryRouter`, optionally starting on a given `?tab=` path -- the page
 * now splits into a `FolderTabs` rail (Summary / Disposals / Wash sales / Form 8949) that mounts
 * only the active tab's content, so a caller whose assertions live on a non-default tab must land
 * there before the page even renders, the same way a bookmark or a page reload would.
 *
 * Waits for the tab rail itself (`role="tablist"`) rather than any one tab's content: the rail is
 * the only thing guaranteed to be in the DOM regardless of which tab `initialPath` opens on, so this
 * one wait condition works for every caller instead of each needing its own ready-signal.
 */
async function renderTax(data: TaxReport, initialPath = "/tax") {
  reportMock.mockResolvedValue(data);
  render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Tax />
    </MemoryRouter>,
  );
  await screen.findByRole("tablist");
}

/** `renderTax`, landed on the Wash sales tab -- for the panels that tab now owns. */
const renderWash = (data: TaxReport) => renderTax(data, "/tax?tab=wash");

/** `renderTax`, landed on the Form 8949 tab -- for the boxes and subtotals that tab now owns. */
const renderF8949 = (data: TaxReport) => renderTax(data, "/tax?tab=f8949");

/** The whole-ledger tracker the Wash sales tab's folded-in section reads -- `@/api/washsales`'s
 *  shape, mirroring `WashSales.test.tsx`'s own factories. */
function washSaleTracker(overrides: Partial<WashSaleTracker> = {}): WashSaleTracker {
  return {
    as_of: "2026-08-17",
    generated_at: "2026-08-17T12:00:00Z",
    total_deferred: "0.00",
    total_permanently_disallowed: "0.00",
    open_window_count: 0,
    symbol_count: 0,
    symbols: [],
    ...overrides,
  };
}

function washSaleTrackerSymbol(
  overrides: Partial<WashSaleTrackerSymbol> = {},
): WashSaleTrackerSymbol {
  return {
    symbol: "NVDA",
    deferred_disallowed: "1234.56",
    permanently_disallowed: "0.00",
    event_count: 1,
    loss_sale_count: 1,
    first_sale_date: "2026-07-15",
    last_sale_date: "2026-07-15",
    repurchase_safe_on: "2026-08-15",
    days_until_safe: 2,
    window_is_open: true,
    accounts: ["rh-taxable"],
    sales: [],
    ...overrides,
  };
}

beforeEach(() => {
  reportMock.mockReset();
  transactionsListMock.mockReset();
  trackerMock.mockReset();
  trackerMock.mockResolvedValue(washSaleTracker());
  // Default: a single transaction dated this year, so the page's own default-year resolution
  // settles quickly and predictably for every test that isn't specifically about that behaviour.
  transactionsListMock.mockResolvedValue(
    transactionPage({ transactions: [transactionRow({ trade_date: `${thisYear}-06-01` })], total: 1 }),
  );
});

describe("uncertain-basis caveat states the size of the doubt", () => {
  it("names the dollar amount and share of the headline gain the uncertain rows contribute, not just their count", async () => {
    // Shaped like a real ledger's pathology: a handful of uncertain rows carrying a gain larger
    // than the reported headline, so the "clean" remainder is actually a loss -- the exact
    // contradiction a row-count-only caveat hides. 1 of 10 rows (10%) contributes $12,000.00
    // against a $10,000.00 headline (120%); the other 9 rows net to a $2,000.00 loss.
    const rows: GainRow[] = [
      gainRow({ disposal_id: "u1", basis_uncertain: true, reportable_gain_loss: "12000.00" }),
      ...Array.from({ length: 9 }, (_, i) =>
        gainRow({ disposal_id: `c${i}`, basis_uncertain: false }),
      ),
    ];
    await renderTax(
      taxReport({
        gains: gainsReport({
          rows,
          short_term_gain: "10000.00",
          rows_with_uncertain_basis: 1,
          gain_on_uncertain_basis: "12000.00",
          proceeds_on_uncertain_basis: "15000.00",
          basis_on_uncertain_basis: "3000.00",
        }),
      }),
    );

    const body = document.body.textContent ?? "";
    expect(body).toContain("1/10 disposal");
    expect(body).toContain("$12,000.00");
    expect(body).toContain("(120%)");
    expect(body).toMatch(/\$10,000\.00 gain reported (above|below)/);
    expect(body).toContain("9 disposals");
    expect(body).toContain("a loss of $2,000.00");
    expect(body).toContain("$15,000.00 of proceeds");
    expect(body).toContain("$3,000.00 of established cost");

    // The bound-versus-estimate distinction and the actual fix, not just the number.
    expect(body).toContain("Bound, not estimate");
    expect(body).toContain("[[opening_position]]");
    expect(body).toContain("data/accounts.toml");
  });

  it("divides by the year's disposal count, not by the fetched page -- 4/1,500, never 4/100", async () => {
    // The defect this pins: `rows_with_uncertain_basis` and `gain_on_uncertain_basis` are whole-year
    // aggregates the backend leaves untouched by paging, while `gains.rows` is one 100-row page. A
    // denominator read off that array made the caveat say "4/100 disposals lack cost basis" -- 4%,
    // inside a role="alert" above the headline gain -- on a year with 1,500 of them, 0.3%. Worse,
    // the ratio moved as the reader paged, because the last page is shorter than the first.
    const rows: GainRow[] = Array.from({ length: 100 }, (_, i) =>
      gainRow({ disposal_id: `d${i}`, basis_uncertain: i < 4 }),
    );
    await renderTax(
      taxReport({
        disposals_total: 1500,
        limit: 100,
        offset: 0,
        disposals_has_more: true,
        gains: gainsReport({
          rows,
          short_term_gain: "10000.00",
          rows_with_uncertain_basis: 4,
          gain_on_uncertain_basis: "100.00",
          proceeds_on_uncertain_basis: "900.00",
          basis_on_uncertain_basis: "800.00",
        }),
      }),
    );

    const body = document.body.textContent ?? "";
    expect(body).toContain("4/1,500 disposals");
    expect(body).not.toContain("4/100");
    // The remainder sentence counts off the same population -- 1,500 - 4, not 100 - 4.
    const detail = document.querySelector(".warning-detail")!;
    expect(detail.textContent).toContain("The remaining 1,496 disposals");
    expect(detail.textContent).not.toContain("The remaining 96 disposals");
  });

  it("takes the promotion threshold off the year total too, so paging cannot fire a legal callout", async () => {
    // 30 uncertain rows in a 100-row page is 30% -- over the 20% row threshold. Against the year's
    // 1,500 disposals it is 2%, and the gain share (1%) is under its own threshold. The caveat
    // belongs beneath the tiles, not promoted above the headline in the danger tone.
    const rows: GainRow[] = Array.from({ length: 100 }, (_, i) =>
      gainRow({ disposal_id: `d${i}`, basis_uncertain: i < 30 }),
    );
    await renderTax(
      taxReport({
        disposals_total: 1500,
        limit: 100,
        offset: 0,
        disposals_has_more: true,
        gains: gainsReport({
          rows,
          short_term_gain: "10000.00",
          rows_with_uncertain_basis: 30,
          gain_on_uncertain_basis: "100.00",
        }),
      }),
    );

    expect(document.querySelector(".callout-danger")).toBeNull();
    const warn = document.querySelector(".callout-warn")!;
    expect(warn.textContent).toContain("30/1,500 disposals");
  });

  it("still reads the array's own length when the response carries no paging metadata at all", async () => {
    // An older backend (or a hand-built fixture) omits `disposals_total`; `.length` is then exactly
    // the year's count, and the fallback must keep it rather than rendering "of 0".
    const rows: GainRow[] = Array.from({ length: 7 }, (_, i) =>
      gainRow({ disposal_id: `d${i}`, basis_uncertain: i < 2 }),
    );
    await renderTax(
      taxReport({
        gains: gainsReport({
          rows,
          short_term_gain: "1000.00",
          rows_with_uncertain_basis: 2,
          gain_on_uncertain_basis: "100.00",
        }),
      }),
    );

    expect(document.body.textContent).toContain("2/7 disposals");
  });

  it("phrases the remainder as a gain, not a loss, when the established-basis rows are still net positive", async () => {
    const rows: GainRow[] = [
      gainRow({ disposal_id: "u1", basis_uncertain: true, reportable_gain_loss: "8000.00" }),
      gainRow({ disposal_id: "u2", basis_uncertain: true, reportable_gain_loss: "0.00" }),
      ...Array.from({ length: 3 }, (_, i) =>
        gainRow({ disposal_id: `c${i}`, basis_uncertain: false }),
      ),
    ];
    await renderTax(
      taxReport({
        gains: gainsReport({
          rows,
          short_term_gain: "10000.00",
          rows_with_uncertain_basis: 2,
          gain_on_uncertain_basis: "8000.00",
          proceeds_on_uncertain_basis: "9000.00",
          basis_on_uncertain_basis: "1000.00",
        }),
      }),
    );

    const body = document.body.textContent ?? "";
    expect(body).toContain("2/5 disposal");
    expect(body).toContain("(80%)");
    expect(body).toContain("a gain of $2,000.00");
    expect(body).not.toContain("a loss of $2,000.00");
  });

  it("renders nothing, and never divides by zero, when no row has an uncertain basis", async () => {
    const rows: GainRow[] = [gainRow({ basis_uncertain: false })];
    await renderTax(
      taxReport({
        gains: gainsReport({
          rows,
          short_term_gain: "100.00",
          rows_with_uncertain_basis: 0,
        }),
      }),
    );

    const body = document.body.textContent ?? "";
    expect(body).not.toContain("used a cost basis the replay could not establish");
    expect(body).not.toContain("NaN");
    expect(body).not.toContain("Infinity");
  });

  it("renders nothing for a year with no disposals at all, even if rows_with_uncertain_basis is nonzero", async () => {
    // Pathological/defensive: this combination should not occur from the real backend (the count
    // is derived from the rows array), but the guard is written against `total === 0` specifically
    // -- not just `uncertain === 0` -- and this is the only way to prove that branch fires rather
    // than passing by coincidence. `wash_sales` carries one entry so the page does not fall into
    // its separate "empty report" state, which would skip this component entirely and prove
    // nothing.
    await renderTax(
      taxReport({
        gains: gainsReport({ rows: [], rows_with_uncertain_basis: 3 }),
        wash_sales: [
          {
            event_id: "w1",
            disposal_id: "d1",
            instrument_id: "i1",
            symbol: "TEST",
            sale_date: "2026-01-01",
            sale_account_id: "acct-1",
            quantity_sold: "5",
            loss_amount: "10.00",
            quantity_replaced: "5",
            disallowed_loss: "10.00",
            replacement_txn_ids: [],
            replacement_lot_ids: [],
            replacement_account_ids: ["acct-1"],
            permanently_disallowed: false,
            basis_added_to_lot_id: null,
            holding_period_tolled_to: null,
            is_chained: false,
          },
        ],
      }),
    );

    const body = document.body.textContent ?? "";
    expect(body).not.toContain("used a cost basis the replay could not establish");
    expect(body).not.toContain("NaN");
    expect(body).not.toContain("Infinity");
  });

  it("omits the percentage clause, without producing NaN% or Infinity%, when the headline gain is zero", async () => {
    const rows: GainRow[] = [
      gainRow({ disposal_id: "u1", basis_uncertain: true, reportable_gain_loss: "500.00" }),
      gainRow({ disposal_id: "u2", basis_uncertain: false, reportable_gain_loss: "-500.00" }),
    ];
    await renderTax(
      taxReport({
        gains: gainsReport({
          rows,
          short_term_gain: "0.00",
          rows_with_uncertain_basis: 1,
          gain_on_uncertain_basis: "500.00",
          proceeds_on_uncertain_basis: "600.00",
          basis_on_uncertain_basis: "100.00",
        }),
      }),
    );

    const body = document.body.textContent ?? "";
    expect(body).toContain("1 of 2 disposal");
    expect(body).toContain("$500.00");
    expect(body).not.toContain("NaN");
    expect(body).not.toContain("Infinity");
    expect(body).not.toContain("gain reported above");
  });

  it("never round-trips a money figure through parseFloat -- a value a float would visibly round differently survives verbatim", async () => {
    // 141010.555 is deliberately three decimal places: `formatMoney` truncates to 2 (the server
    // already rounded, so this never occurs in practice) and Number("141010.555") is not exactly
    // representable in an IEEE double, so a `parseFloat().toFixed(2)` path is not guaranteed to
    // agree with the string-exact truncation. Asserting the exact truncated string catches either
    // form of tampering.
    const rows: GainRow[] = [
      gainRow({ disposal_id: "u1", basis_uncertain: true, reportable_gain_loss: "141010.555" }),
    ];
    await renderTax(
      taxReport({
        gains: gainsReport({
          rows,
          short_term_gain: "171966.42",
          rows_with_uncertain_basis: 1,
          gain_on_uncertain_basis: "141010.555",
          proceeds_on_uncertain_basis: "232026.185",
          basis_on_uncertain_basis: "96952.705",
        }),
      }),
    );

    const body = document.body.textContent ?? "";
    expect(body).toContain(formatMoney("141010.555"));
    expect(body).toContain("$141,010.55");
    expect(body).toContain(formatMoney("232026.185"));
    expect(body).toContain(formatMoney("96952.705"));
    // Never the naively-rounded neighbour a float round-trip could produce.
    expect(body).not.toContain("$141,010.56");
  });
});

describe("moneyPercentOf", () => {
  it("computes an exact rounded percentage via integer cents, not parseFloat", () => {
    expect(moneyPercentOf("8000.00", "10000.00")).toBe(80);
    expect(moneyPercentOf("12000.00", "10000.00")).toBe(120);
    expect(moneyPercentOf("-500.00", "1000.00")).toBe(-50);
  });

  it("returns null rather than NaN or Infinity when the denominator is zero", () => {
    expect(moneyPercentOf("500.00", "0.00")).toBe(null);
    expect(moneyPercentOf("0.00", "0.00")).toBe(null);
  });

  it("rounds ties away from zero, matching sumMoney/quantize_money", () => {
    // 1/8 = 12.5% exactly -- a genuine tie, which half-up rounds to 13, not 12.
    expect(moneyPercentOf("1.00", "8.00")).toBe(13);
  });
});

// ---------------------------------------------------------------------------
// Promotion above the headline
//
// The promoted caveat sits above the figures rather than eleven screens below them, and until now
// it fired only on the *share of rows* that carried an unestablished basis. That has a blind spot
// wide enough to swallow the year: an unestablished basis attaches to shares that arrived rather
// than were bought -- transfers, and positions older than the export -- which are the large ones.
// On a real ledger that can be a small share of rows, comfortably under the 20% row gate, carrying
// most of the reported gain. Mostly guesswork, promoted nowhere.
// ---------------------------------------------------------------------------

describe("the promoted caveat fires on money, not only on row count", () => {
  /**
   * The page carries more than one `role="alert"` -- the tile-level magnitude note is one too -- so
   * every assertion here selects the *promoted* caveat by the sentence only it says. Matching on
   * the role alone would silently assert against whichever alert happened to render first.
   */
  const promoted = (): HTMLElement | null =>
    screen
      .queryAllByRole("alert")
      .find(
        (el) =>
          el.classList.contains("callout-danger") &&
          // "Bound, not estimate" is the fixIt sentence every render of this caveat carries
          // unconditionally, regardless of which headline variant (ratio vs. plain count) fired --
          // the stable fragment across all its shapes.
          /Bound, not estimate/.test(el.textContent ?? ""),
      ) ?? null;

  /** The real shape: few rows, most of the gain. */
  function fewRowsMostOfTheGain(): TaxReport {
    return taxReport({
      gains: gainsReport({
        rows: Array.from({ length: 100 }, (_, i) =>
          gainRow({ disposal_id: `d${i}`, basis_uncertain: i < 8 }),
        ),
        rows_with_uncertain_basis: 8, // 8% -- under the 20% row threshold
        short_term_gain: "50000.00",
        gain_on_uncertain_basis: "41000.00", // 82% of it
        proceeds_on_uncertain_basis: "65000.00",
        basis_on_uncertain_basis: "24000.00",
      }),
    });
  }

  it("promotes when a minority of rows carries a majority of the gain", async () => {
    await renderTax(fewRowsMostOfTheGain());
    const alert = promoted();
    expect(alert).not.toBeNull();
    expect(alert!.textContent).toContain("8/100 disposals");
    // The money is the point, and it has to be in the promoted text, not only in the tile note.
    expect(alert!.textContent).toContain("$41,000.00");
    expect(alert!.textContent).toContain("82%");
  });

  it("still promotes on row share when the gain share is small", async () => {
    /** The original trigger, which must keep working: a year that is mostly guesswork by row count
     *  but happens to net out to little, so the money test alone would stay silent. */
    await renderTax(
      taxReport({
        gains: gainsReport({
          rows: Array.from({ length: 10 }, (_, i) =>
            gainRow({ disposal_id: `d${i}`, basis_uncertain: i < 5 }),
          ),
          rows_with_uncertain_basis: 5, // 50%
          short_term_gain: "10000.00",
          gain_on_uncertain_basis: "100.00", // 1%
        }),
      }),
    );
    expect(promoted()?.textContent).toContain("5/10 disposals");
  });

  it("stays silent when both the row share and the gain share are small", async () => {
    await renderTax(
      taxReport({
        gains: gainsReport({
          rows: Array.from({ length: 100 }, (_, i) =>
            gainRow({ disposal_id: `d${i}`, basis_uncertain: i < 2 }),
          ),
          rows_with_uncertain_basis: 2, // 2%
          short_term_gain: "10000.00",
          gain_on_uncertain_basis: "100.00", // 1%
        }),
      }),
    );
    expect(promoted()).toBeNull();
  });

  it("says nothing about a percentage it cannot compute", async () => {
    /** A year whose gains net to zero has no denominator. The caveat must still promote on rows and
     *  must not render `NaN%` or `Infinity%` -- the failure this page's own money rules exist to
     *  prevent. */
    await renderTax(
      taxReport({
        gains: gainsReport({
          rows: Array.from({ length: 10 }, (_, i) =>
            gainRow({ disposal_id: `d${i}`, basis_uncertain: i < 5 }),
          ),
          rows_with_uncertain_basis: 5,
          short_term_gain: "0.00",
          gain_on_uncertain_basis: "5000.00",
        }),
      }),
    );
    const alert = promoted();
    expect(alert).not.toBeNull();
    expect(alert!.textContent).toContain("5 of 10 disposals");
    expect(alert!.textContent).not.toMatch(/NaN|Infinity/);
  });

  it("stays silent when nothing is uncertain at all", async () => {
    await renderTax(
      taxReport({
        gains: gainsReport({
          rows: [gainRow()],
          rows_with_uncertain_basis: 0,
          short_term_gain: "100.00",
          gain_on_uncertain_basis: "0.00",
        }),
      }),
    );
    expect(promoted()).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Per-symbol wash-sale panel
//
// `wash_sale_summary` is nullable on the wire -- the backend worker's contract -- so the panel's
// first job is to do nothing at all when it is absent, rather than render an empty table that
// implies "zero wash sales" for a report that simply never computed the summary. Its second job is
// to keep the deferred and permanently-disallowed figures legibly separate: a reader who saw
// "$940 deferred" next to "12 days" must not conclude those two numbers are connected, because they
// are not -- the days-remaining clock governs only the *next* purchase, not the return of money
// already added to a replacement lot's basis.
// ---------------------------------------------------------------------------

describe("per-symbol wash-sale panel", () => {
  const panelHeading = () => screen.queryByRole("heading", { name: /Wash sales by symbol/i });

  it("renders no panel when the summary is null", async () => {
    await renderWash(
      taxReport({ wash_sales: [washSaleEvent()], wash_sale_summary: null }),
    );
    expect(panelHeading()).toBeNull();
  });

  it("renders no table -- but an explicit empty state -- when symbols is empty", async () => {
    await renderWash(
      taxReport({
        wash_sales: [washSaleEvent()],
        wash_sale_summary: washSaleSummary({ symbols: [], open_window_count: 0 }),
      }),
    );
    expect(panelHeading()).not.toBeNull();
    expect(document.querySelector(".wash-summary-table")).toBeNull();
    const body = document.body.textContent ?? "";
    expect(body).toContain("No wash-sale activity to summarize by symbol");
    // The empty state must not claim a year scope the panel doesn't have (problem #1 of the audit).
    expect(body).not.toContain("No wash-sale activity to summarize by symbol for this year");
  });

  it("shows a symbol's deferred and permanently-disallowed amounts as separate figures", async () => {
    await renderWash(
      taxReport({
        wash_sales: [washSaleEvent()],
        wash_sale_summary: washSaleSummary({
          symbols: [
            washSaleSymbolSummary({
              symbol: "AAA",
              deferred_disallowed: "940.00",
              permanently_disallowed: "0.00",
            }),
            washSaleSymbolSummary({
              symbol: "BBB",
              deferred_disallowed: "0.00",
              permanently_disallowed: "250.00",
              window_is_open: false,
            }),
          ],
          total_deferred: "940.00",
          total_permanently_disallowed: "250.00",
        }),
      }),
    );

    const table = document.querySelector(".wash-summary-table");
    expect(table).not.toBeNull();
    const body = table!.textContent ?? "";
    expect(body).toContain("AAA");
    expect(body).toContain("$940.00");
    expect(body).toContain("BBB");
    expect(body).toContain("$250.00");
    // The two totals appear (never combined into one figure) in the trailing summary line too.
    const panelText = panelHeading()!.closest(".panel")!.textContent ?? "";
    expect(panelText).toContain("$940.00 deferred");
    expect(panelText).toContain("$250.00 permanently disallowed");
  });

  it("shows an open window as days remaining plus the safe-again date", async () => {
    await renderWash(
      taxReport({
        wash_sales: [washSaleEvent()],
        wash_sale_summary: washSaleSummary({
          symbols: [
            washSaleSymbolSummary({
              symbol: "OPEN",
              last_sale_date: "2026-02-14",
              repurchase_safe_on: "2026-03-17",
              days_until_safe: 12,
              window_is_open: true,
            }),
          ],
          open_window_count: 1,
        }),
      }),
    );

    const table = document.querySelector(".wash-summary-table");
    const body = table!.textContent ?? "";
    expect(body).toContain("12 days");
    expect(body).toContain("2026-03-17");
    expect(document.querySelector(".badge.wash-window-open")).not.toBeNull();
    expect(body).not.toContain("safe to repurchase");
  });

  it("reads a closed window as safe, not as a number of days", async () => {
    await renderWash(
      taxReport({
        wash_sales: [washSaleEvent()],
        wash_sale_summary: washSaleSummary({
          symbols: [
            washSaleSymbolSummary({
              symbol: "SAFE",
              window_is_open: false,
              days_until_safe: 0,
            }),
          ],
          open_window_count: 0,
        }),
      }),
    );

    const table = document.querySelector(".wash-summary-table");
    const body = table!.textContent ?? "";
    expect(body).toContain("safe to repurchase");
    expect(document.querySelector(".badge.wash-window-safe")).not.toBeNull();
    expect(document.querySelector(".badge.wash-window-open")).toBeNull();
  });

  it("states in prose that deferred and permanent are different and that waiting recovers neither", async () => {
    await renderWash(
      taxReport({
        wash_sales: [washSaleEvent()],
        wash_sale_summary: washSaleSummary({
          symbols: [washSaleSymbolSummary({ permanently_disallowed: "100.00" })],
          total_permanently_disallowed: "100.00",
        }),
      }),
    );

    const panelText = panelHeading()!.closest(".panel")!.textContent ?? "";
    // Deferred comes back on a sale of the replacement lot, not on a date.
    expect(panelText).toContain("Deferred, not released");
    expect(panelText).toContain("added to the replacement shares' basis");
    // Permanent is destroyed outright and unaffected by waiting.
    expect(panelText).toContain("Gone, not deferred");
    expect(panelText).toContain("waiting won't recover it");
    // The repurchase-safe date is explicitly scoped to future purchases, not to money already
    // deferred -- the panel must not let the two read as connected.
    expect(panelText).toContain("Doesn't affect money already deferred");
  });

  it("states an explicit scope line distinguishing this panel's ledger-wide total from the year-scoped tile above", async () => {
    await renderWash(
      taxReport({
        wash_sales: [washSaleEvent()],
        wash_sale_summary: washSaleSummary(),
      }),
    );

    const panelText = panelHeading()!.closest(".panel")!.textContent ?? "";
    expect(panelText).toContain("every wash sale in your full history");
    // The year is named rather than referred to, so the reader can check this panel's total against
    // the year-scoped tile without first working out which year that tile covers. Matched by shape
    // because the page defaults to the previous calendar year, which moves with the clock.
    expect(panelText).toMatch(/not just \d{4}/);
    // "deliberate" is the new copy's stand-in for the old "that is not an error" phrasing.
    expect(panelText).toContain("deliberate");
    expect(panelText).toContain("repurchase safety is a today question");
  });

  it("carries a footer disclaiming options, substantially-identical securities, and unconnected accounts", async () => {
    await renderWash(
      taxReport({
        wash_sales: [washSaleEvent()],
        wash_sale_summary: washSaleSummary(),
      }),
    );

    const panelText = panelHeading()!.closest(".panel")!.textContent ?? "";
    expect(panelText).toContain("Connected accounts only");
    expect(panelText).toContain("excludes options");
    expect(panelText).toContain("unconnected purchases");
    expect(panelText).toContain("Calculation only");
    // The section 1091 nuance the short footer cannot hold lives in the InfoNote body, still in the
    // DOM (the disclosure keeps its children mounted): substantially-identical securities, contracts
    // to acquire, and related-party repurchases are all things this panel does not detect.
    expect(panelText).toContain("substantially identical");
    expect(panelText).toContain("spouse's account");
    expect(panelText).toContain("reconcile with your 1099-B");
  });

  it("marks a symbol with a zero deferred total and an open window as the pending, actionable row it is -- not an empty one", async () => {
    await renderWash(
      taxReport({
        wash_sales: [washSaleEvent()],
        wash_sale_summary: washSaleSummary({
          symbols: [
            washSaleSymbolSummary({
              symbol: "PEND",
              deferred_disallowed: "0.00",
              permanently_disallowed: "0.00",
              window_is_open: true,
              days_until_safe: 9,
              repurchase_safe_on: "2026-08-24",
            }),
          ],
          open_window_count: 1,
          total_deferred: "0.00",
        }),
      }),
    );

    const row = document.querySelector("tr.wash-row-pending");
    expect(row).not.toBeNull();
    // A real "0.00" is a figure, not an absence -- the deferred cell renders a dollar amount, not
    // a dash, per this page's null-vs-zero convention.
    const deferredCell = row!.querySelectorAll("td")[1]!;
    expect(deferredCell.textContent).toBe("$0.00");
    expect(deferredCell.textContent).not.toContain("—");
    // The status cell is the point of this row: it carries the open-window badge plus an explicit
    // note that zero-deferred-and-open does not mean nothing is going on.
    const body = row!.textContent ?? "";
    expect(document.querySelector(".badge.wash-window-open")).not.toBeNull();
    expect(body).toContain("no repurchase yet");
    expect(body).toContain("buying back before the date above creates a wash sale");
  });

  it("sorts by any column and filters to completed windows", async () => {
    await renderWash(
      taxReport({
        wash_sales: [washSaleEvent()],
        wash_sale_summary: washSaleSummary({
          symbols: [
            washSaleSymbolSummary({
              symbol: "AAA",
              deferred_disallowed: "100.00",
              window_is_open: true,
              days_until_safe: 5,
            }),
            washSaleSymbolSummary({
              symbol: "BBB",
              deferred_disallowed: "900.00",
              window_is_open: false,
            }),
            washSaleSymbolSummary({
              symbol: "CCC",
              deferred_disallowed: "500.00",
              window_is_open: false,
            }),
          ],
          open_window_count: 1,
          total_deferred: "1500.00",
        }),
      }),
    );

    const washTable = () => document.querySelector(".wash-summary-table")!;
    const symbolsInOrder = () =>
      Array.from(washTable().querySelectorAll("tbody tr td:first-child")).map((td) =>
        (td.textContent ?? "").trim().slice(0, 3),
      );
    const headerButton = (label: string) =>
      Array.from(washTable().querySelectorAll<HTMLButtonElement>("thead .tbl-sort-button")).find(
        (b) => (b.textContent ?? "").includes(label),
      )!;

    // Default sort is deferred descending: the largest deferred loss leads.
    expect(symbolsInOrder()).toEqual(["BBB", "CCC", "AAA"]);

    // Clicking the Symbol header re-sorts alphabetically ascending.
    fireEvent.click(headerButton("Symbol"));
    expect(symbolsInOrder()).toEqual(["AAA", "BBB", "CCC"]);

    // Filtering to Completed hides the one open window.
    const select = document.querySelector<HTMLSelectElement>(".tbl-filter-bar select")!;
    fireEvent.change(select, { target: { value: "completed" } });
    const shown = symbolsInOrder();
    expect(shown).toEqual(["BBB", "CCC"]);
    expect(shown).not.toContain("AAA");
  });
});

describe("wash-sale panel against an older API", () => {
  it("renders the rest of the page when the field is absent, not just when it is null", async () => {
    /**
     * A backend that predates this feature omits `wash_sale_summary` entirely, so the field arrives
     * as `undefined` rather than `null`. A `=== null` guard lets that through to `summary.symbols`
     * and takes the whole Tax page down to its ErrorBoundary — which happened for real during this
     * feature's own rollout, with the frontend live against a backend that had not restarted.
     *
     * The cast is the point of the test: it reproduces a payload the type says cannot exist but the
     * wire can still deliver.
     */
    // Non-empty, or the page renders its empty state and never reaches the panel at all.
    const stale = taxReport({ gains: gainsReport({ rows: [gainRow()], short_term_gain: "100.00" }) });
    delete (stale as { wash_sale_summary?: unknown }).wash_sale_summary;

    await renderTax(stale as typeof stale);

    // The page rendered rather than falling over, and the panel simply is not there.
    expect(screen.getByText(/Short-term gain/)).toBeTruthy();
    expect(document.querySelector(".wash-summary-table")).toBeNull();
    expect(document.body.textContent).not.toMatch(/went wrong|Render failed/i);
  });
});

// ---------------------------------------------------------------------------
// Defect 1 -- the page must open on the most recent year with activity, not `currentYear - 1`
//
// `currentYear - 1` is right only in January, when the current year genuinely has no transactions
// yet. The rest of the year it opens the page on a year with nothing in it -- three concurrent UAT
// persona runs did exactly that against a ledger dated entirely in the current year, landed on last
// year, and read "No <year> activity at all" as a failed import rather than a wrong default.
// ---------------------------------------------------------------------------

describe("default tax year", () => {
  it("opens on the most recent year with ledger activity, not currentYear - 1", async () => {
    transactionsListMock.mockResolvedValue(
      transactionPage({
        transactions: [transactionRow({ trade_date: `${thisYear}-03-02` })],
        total: 1,
      }),
    );
    await renderTax(
      taxReport({
        tax_year: thisYear,
        gains: gainsReport({ rows: [gainRow()], short_term_gain: "100.00" }),
      }),
    );

    const select = screen.getByLabelText(/Tax year/i) as HTMLSelectElement;
    expect(select.value).toBe(String(thisYear));
    // The old, unconditional default -- must not win when the ledger has activity this year.
    expect(select.value).not.toBe(String(thisYear - 1));
  });

  it("falls back to currentYear - 1 when the ledger has no transactions at all", async () => {
    transactionsListMock.mockResolvedValue(transactionPage({ transactions: [], total: 0 }));
    await renderTax(
      taxReport({
        tax_year: thisYear - 1,
        gains: gainsReport({ rows: [gainRow()], short_term_gain: "100.00" }),
      }),
    );

    const select = screen.getByLabelText(/Tax year/i) as HTMLSelectElement;
    expect(select.value).toBe(String(thisYear - 1));
  });

  it("falls back to currentYear - 1 when the transaction lookup itself fails, rather than getting stuck", async () => {
    transactionsListMock.mockRejectedValue(new Error("network error"));
    await renderTax(
      taxReport({
        tax_year: thisYear - 1,
        gains: gainsReport({ rows: [gainRow()], short_term_gain: "100.00" }),
      }),
    );

    const select = screen.getByLabelText(/Tax year/i) as HTMLSelectElement;
    expect(select.value).toBe(String(thisYear - 1));
  });

  it("keeps the resolved default year selectable even when it falls outside the normal option window", async () => {
    // A ledger whose only activity is older than the normal 9-year option window (currentYear down
    // to currentYear - 8) must still land the selector on a value that is actually one of its own
    // options, not a year silently missing from the list it was chosen from.
    const oldYear = thisYear - 12;
    transactionsListMock.mockResolvedValue(
      transactionPage({ transactions: [transactionRow({ trade_date: `${oldYear}-05-01` })], total: 1 }),
    );
    await renderTax(
      taxReport({
        tax_year: oldYear,
        gains: gainsReport({ rows: [gainRow()], short_term_gain: "100.00" }),
      }),
    );

    const select = screen.getByLabelText(/Tax year/i) as HTMLSelectElement;
    expect(select.value).toBe(String(oldYear));
    expect(screen.getByRole("option", { name: String(oldYear) })).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Defect 2 -- the repurchase-safe date must not vanish once the §1091 window closes
//
// The caption under the table promises "this date tells you when a new purchase will stop creating
// a new wash sale" for every row, but the closed-window branch used to render only a bare "safe to
// repurchase" badge with no date at all -- a promise the caption made and the closed branch broke.
// ---------------------------------------------------------------------------

describe("repurchase-safe date survives the window closing", () => {
  it("shows the date while the window is open", async () => {
    await renderWash(
      taxReport({
        wash_sales: [washSaleEvent()],
        wash_sale_summary: washSaleSummary({
          symbols: [
            washSaleSymbolSummary({
              symbol: "OPEN",
              window_is_open: true,
              days_until_safe: 5,
              repurchase_safe_on: "2026-09-01",
            }),
          ],
          open_window_count: 1,
        }),
      }),
    );

    const table = document.querySelector(".wash-summary-table");
    expect(table!.textContent).toContain("2026-09-01");
  });

  it("still shows the date once the window has closed, phrased for the past rather than dropped", async () => {
    await renderWash(
      taxReport({
        wash_sales: [washSaleEvent()],
        wash_sale_summary: washSaleSummary({
          symbols: [
            washSaleSymbolSummary({
              symbol: "CLOSED",
              window_is_open: false,
              days_until_safe: 0,
              repurchase_safe_on: "2026-03-17",
            }),
          ],
          open_window_count: 0,
        }),
      }),
    );

    const table = document.querySelector(".wash-summary-table");
    const body = table!.textContent ?? "";
    expect(body).toContain("safe to repurchase");
    // The date the old closed branch dropped entirely.
    expect(body).toContain("2026-03-17");
    // Still the same badge class as before -- only the content inside it changed.
    expect(document.querySelector(".badge.wash-window-safe")).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Defect 3 -- a wash-sale-tolled holding period on a lot that is still held must be visible
// somewhere, not only on a disposals-table row that a still-held lot can never produce.
// ---------------------------------------------------------------------------

describe("tolled holding period on an open replacement lot", () => {
  it("surfaces the tolled-to date for a replacement lot this year's Disposals table does not show as sold", async () => {
    await renderWash(
      taxReport({
        gains: gainsReport({
          rows: [gainRow({ lot_id: "sold-lot", disposal_id: "d1" })],
          short_term_gain: "100.00",
        }),
        wash_sales: [
          washSaleEvent({
            symbol: "TOLL",
            basis_added_to_lot_id: "open-lot-1",
            holding_period_tolled_to: "2025-11-01",
          }),
        ],
        wash_sale_summary: washSaleSummary({
          symbols: [washSaleSymbolSummary({ symbol: "TOLL" })],
        }),
      }),
    );

    const panelText =
      screen.getByRole("heading", { name: /Wash sales by symbol/i }).closest(".panel")!.textContent ??
      "";
    expect(panelText).toContain("2025-11-01");
  });

  it("does not repeat the tolled date for a replacement lot this year's Disposals table already shows as sold", async () => {
    await renderWash(
      taxReport({
        gains: gainsReport({
          // The replacement lot itself was sold this year -- `DisposalsTable` already carries its
          // tolled holding period via `holding_start`, so the by-symbol panel must not duplicate it.
          rows: [gainRow({ lot_id: "already-shown-lot", disposal_id: "d1" })],
          short_term_gain: "100.00",
        }),
        wash_sales: [
          washSaleEvent({
            symbol: "TOLL2",
            basis_added_to_lot_id: "already-shown-lot",
            holding_period_tolled_to: "2025-11-01",
          }),
        ],
        wash_sale_summary: washSaleSummary({
          symbols: [washSaleSymbolSummary({ symbol: "TOLL2" })],
        }),
      }),
    );

    const panelText =
      screen.getByRole("heading", { name: /Wash sales by symbol/i }).closest(".panel")!.textContent ??
      "";
    expect(panelText).not.toContain("2025-11-01");
  });

  it("renders nothing extra for a symbol with no tolled replacement lot", async () => {
    await renderWash(
      taxReport({
        wash_sales: [washSaleEvent()],
        wash_sale_summary: washSaleSummary(),
      }),
    );

    const panelText =
      screen.getByRole("heading", { name: /Wash sales by symbol/i }).closest(".panel")!.textContent ??
      "";
    expect(panelText).not.toContain("holding tolled to");
  });
});

/**
 * `Form8949Section` used to attach the short-term subtotal to Box C and the long-term subtotal to
 * Box F unconditionally -- and an empty box renders nothing at all (`if (rows.length === 0) return
 * null`), so a year where every disposal landed in Boxes A/B/D/E (broker-reported basis -- the common
 * covered-securities case) showed no subtotal whatsoever, even though `short_term_total_*` and
 * `long_term_total_*` were already on the wire. The fix anchors each subtotal to the *last non-empty*
 * box in its term instead of a fixed one.
 */
describe("Form 8949 subtotals render for the common covered-securities case", () => {
  it("renders the short-term subtotal under Box A when Box C is empty", async () => {
    await renderF8949(
      taxReport({
        form8949: form8949Report({
          rows: [form8949Row({ box: "A", disposal_id: "a1" })],
          short_term_total_proceeds: "1000.00",
          short_term_total_basis: "900.00",
          short_term_total_gain: "100.00",
        }),
      }),
    );

    expect(screen.getByText("Box A — short-term, basis reported to the IRS")).toBeTruthy();
    expect(screen.queryByText(/Box C/)).toBeNull();

    const subtotal = document.querySelector(".form8949-subtotal");
    expect(subtotal).not.toBeNull();
    expect(subtotal!.textContent).toContain("Short-term subtotal");
    expect(subtotal!.textContent).toContain("proceeds $1,000.00");
    expect(subtotal!.textContent).toContain("basis $900.00");
    expect(subtotal!.textContent).toContain("gain/loss $100.00");
    // Exactly one subtotal on the page -- it must not also (or instead) attach to a box that never
    // rendered.
    expect(document.querySelectorAll(".form8949-subtotal")).toHaveLength(1);
  });

  it("renders the long-term subtotal under Box D when Box F is empty", async () => {
    await renderF8949(
      taxReport({
        form8949: form8949Report({
          rows: [form8949Row({ box: "D", disposal_id: "d1" })],
          long_term_total_proceeds: "1000.00",
          long_term_total_basis: "900.00",
          long_term_total_gain: "100.00",
        }),
      }),
    );

    expect(screen.getByText("Box D — long-term, basis reported to the IRS")).toBeTruthy();
    expect(screen.queryByText(/Box F/)).toBeNull();

    const subtotal = document.querySelector(".form8949-subtotal");
    expect(subtotal).not.toBeNull();
    expect(subtotal!.textContent).toContain("Long-term subtotal");
    expect(subtotal!.textContent).toContain("proceeds $1,000.00");
    expect(subtotal!.textContent).toContain("basis $900.00");
    expect(subtotal!.textContent).toContain("gain/loss $100.00");
    expect(document.querySelectorAll(".form8949-subtotal")).toHaveLength(1);
  });

  it("still attaches each subtotal to Box C / Box F when they are the ones with rows", async () => {
    await renderF8949(
      taxReport({
        form8949: form8949Report({
          rows: [
            form8949Row({ box: "A", disposal_id: "a1" }),
            form8949Row({ box: "C", disposal_id: "c1" }),
            form8949Row({ box: "F", disposal_id: "f1" }),
          ],
        }),
      }),
    );

    const boxASection = screen.getByText("Box A — short-term, basis reported to the IRS").closest(
      ".form8949-box",
    )!;
    expect(boxASection.textContent).not.toContain("subtotal");

    const boxCSection = screen
      .getByText("Box C — short-term, not on any 1099-B")
      .closest(".form8949-box")!;
    expect(boxCSection.textContent).toContain("Short-term subtotal");

    const boxFSection = screen
      .getByText("Box F — long-term, not on any 1099-B")
      .closest(".form8949-box")!;
    expect(boxFSection.textContent).toContain("Long-term subtotal");
  });
});

// ---------------------------------------------------------------------------
// Tab navigation -- the §3.6 contract this page is judged against: the page splits into a
// `FolderTabs` rail (Summary / Disposals / Wash sales / Form 8949), the tab lives in the URL, and
// only the active tab's content is ever mounted. The ~1,341-row Disposals table is the concrete
// case this exists for: before this refactor it, and every other panel, rendered unconditionally.
// ---------------------------------------------------------------------------

/** Shows the current route's path + query string, so a test can assert the tab landed in the URL
 *  without reaching into the router's internals. */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname + location.search}</div>;
}

/** A bare Back button driven by the router, standing in for the browser's own Back -- `MemoryRouter`
 *  has no window history to click a real Back button against, but `navigate(-1)` exercises the same
 *  history-stack pop `useUrlState`'s default `"push"` mode is built to support. */
function BackButton() {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate(-1)}>
      go back
    </button>
  );
}

async function renderTaxWithChrome(data: TaxReport, initialPath = "/tax") {
  reportMock.mockResolvedValue(data);
  render(
    <MemoryRouter initialEntries={[initialPath]}>
      <LocationProbe />
      <BackButton />
      <Tax />
    </MemoryRouter>,
  );
  await screen.findByRole("tablist");
}

/** A report with something in every tab, so a test can move between all four without hitting an
 *  empty-panel branch that would confound "is this tab's content mounted" with "does this tab have
 *  anything to show." */
function reportWithEverything(): TaxReport {
  return taxReport({
    gains: gainsReport({ rows: [gainRow()], short_term_gain: "100.00" }),
    wash_sales: [washSaleEvent()],
    wash_sale_summary: washSaleSummary(),
    form8949: form8949Report({ rows: [form8949Row()] }),
  });
}

describe("tab navigation", () => {
  it("mounts only the active tab's heavy table -- Disposals is absent on Summary and appears once selected", async () => {
    await renderTaxWithChrome(reportWithEverything());

    // Summary is the default tab: the Disposals table must not exist in the DOM at all, not just
    // be visually hidden -- this is the whole point of the refactor.
    expect(screen.queryByTestId("disposals-table")).toBeNull();
    expect(screen.getByText(/Short-term gain/)).toBeTruthy();

    fireEvent.click(screen.getByRole("tab", { name: /Disposals/ }));

    expect(await screen.findByTestId("disposals-table")).toBeTruthy();
    // Switching away unmounts the Summary-only content and writes the new tab into the URL.
    expect(screen.queryByText(/Short-term gain/)).toBeNull();
    expect(screen.getByTestId("location-probe").textContent).toContain("tab=disposals");
  });

  it("opens directly on the Wash sales tab when the initial URL already says so -- a reload on /tax?tab=wash", async () => {
    await renderTaxWithChrome(reportWithEverything(), "/tax?tab=wash");

    expect(screen.getByRole("heading", { name: /Wash sales by symbol/i })).toBeTruthy();
    expect(screen.queryByTestId("disposals-table")).toBeNull();
    expect(screen.queryByText(/Short-term gain/)).toBeNull();
    expect(screen.getByRole("tab", { name: /Wash sales/ }).getAttribute("aria-selected")).toBe(
      "true",
    );
  });

  it("falls back to Summary for an unrecognized ?tab= value instead of rendering nothing", async () => {
    await renderTaxWithChrome(reportWithEverything(), "/tax?tab=nonsense");

    expect(screen.getByText(/Short-term gain/)).toBeTruthy();
    expect(screen.getByRole("tab", { name: /Summary/ }).getAttribute("aria-selected")).toBe("true");
  });

  it("restores the previously selected tab on Back", async () => {
    await renderTaxWithChrome(reportWithEverything());

    fireEvent.click(screen.getByRole("tab", { name: /Disposals/ }));
    await screen.findByTestId("disposals-table");
    fireEvent.click(screen.getByRole("tab", { name: /Wash sales/ }));
    await screen.findByRole("heading", { name: /Wash sales by symbol/i });

    fireEvent.click(screen.getByText("go back"));

    // Back from Wash sales lands on Disposals -- the tab selected immediately before it, not
    // Summary and not stuck on Wash sales.
    expect(await screen.findByTestId("disposals-table")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: /Wash sales by symbol/i })).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Server-side paging -- `GET /api/tax/report`'s `limit`/`offset` now slice `gains.rows` and
// `wash_sales`, and this page asks for a page of whichever list the active tab owns rather than
// fetching the whole report at once. `TaxReport.disposals_total`/`wash_events_total` carry the true
// counts so a client never mistakes "this page is short" for "the year is small".
// ---------------------------------------------------------------------------

describe("server-side paging", () => {
  it("requests the Disposals tab's own page on load, not the whole report", async () => {
    await renderTax(
      taxReport({ gains: gainsReport({ rows: [gainRow()], short_term_gain: "100.00" }) }),
      "/tax?tab=disposals",
    );
    expect(reportMock).toHaveBeenCalledWith(thisYear, { limit: 100, offset: 0 });
  });

  it("shows the tab badge and footer sentence from the year's true total, not the current page's row count", async () => {
    // A 40-row page standing in for one page of a much larger year -- the badge and footer must both
    // read `disposals_total` (250), never `gains.rows.length` (40).
    const rows = Array.from({ length: 40 }, (_, i) => gainRow({ disposal_id: `d${i}` }));
    await renderTax(
      taxReport({
        gains: gainsReport({ rows, short_term_gain: "100.00" }),
        disposals_total: 250,
        disposals_has_more: true,
      }),
      "/tax?tab=disposals",
    );

    expect(screen.getByRole("tab", { name: /Disposals/ }).textContent).toContain("250");
    const body = document.body.textContent ?? "";
    expect(body).toContain("250 disposals");
    expect(body).not.toContain("40 disposals");
  });

  it("renders a working Pager when the year's total exceeds one page, and pages forward on Next", async () => {
    const rows = Array.from({ length: 100 }, (_, i) => gainRow({ disposal_id: `d${i}` }));
    await renderTax(
      taxReport({
        gains: gainsReport({ rows, short_term_gain: "100.00" }),
        disposals_total: 250,
        disposals_has_more: true,
      }),
      "/tax?tab=disposals",
    );

    // Two `TaxPager`s render for this table -- one above it, one below -- so every assertion here
    // takes the first of each rather than a role query that would otherwise match more than one.
    const nextButtons = screen.getAllByRole<HTMLButtonElement>("button", { name: "Next" });
    const previousButtons = screen.getAllByRole<HTMLButtonElement>("button", { name: "Previous" });
    expect(previousButtons[0]!.disabled).toBe(true);
    expect(nextButtons[0]!.disabled).toBe(false);

    fireEvent.click(nextButtons[0]!);

    await waitFor(() => {
      expect(reportMock).toHaveBeenLastCalledWith(thisYear, { limit: 100, offset: 100 });
    });
  });

  it("hides the Pager once everything already fits on one page", async () => {
    await renderTax(
      taxReport({
        gains: gainsReport({ rows: [gainRow()], short_term_gain: "100.00" }),
        disposals_total: 1,
      }),
      "/tax?tab=disposals",
    );
    expect(screen.queryByRole("button", { name: "Next" })).toBeNull();
  });

  it("treats a non-empty year with a (currently) empty page as loaded, not as the import-nudge empty state", async () => {
    // The shape a stale offset produces after the underlying data shrank: this "page" has no rows,
    // but the year plainly is not empty. `isEmptyReport` must read `disposals_total`, not
    // `gains.rows.length`, or this renders the "go import something" placeholder for a real year.
    await renderTax(
      taxReport({
        gains: gainsReport({ rows: [], short_term_gain: "100.00" }),
        disposals_total: 150,
      }),
      "/tax?tab=disposals",
    );
    expect(screen.getByTestId("disposals-table")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/import broker exports/i);
  });

  it("requests the Wash sales tab's own page, independently of the Disposals tab's offset", async () => {
    await renderTax(
      taxReport({
        gains: gainsReport({ rows: [gainRow()], short_term_gain: "100.00" }),
        wash_sales: [washSaleEvent()],
        wash_sale_summary: washSaleSummary(),
      }),
      "/tax?tab=wash",
    );
    expect(reportMock).toHaveBeenCalledWith(thisYear, { limit: 100, offset: 0 });
  });

  it("keeps each tab's paging offset independent -- paging Disposals forward does not leak into the Wash sales fetch", async () => {
    const rows = Array.from({ length: 100 }, (_, i) => gainRow({ disposal_id: `d${i}` }));
    await renderTaxWithChrome(
      taxReport({
        gains: gainsReport({ rows, short_term_gain: "100.00" }),
        disposals_total: 250,
        disposals_has_more: true,
        wash_sales: [washSaleEvent()],
        wash_sale_summary: washSaleSummary(),
      }),
      "/tax?tab=disposals",
    );

    fireEvent.click(screen.getAllByRole("button", { name: "Next" })[0]!);
    await waitFor(() => {
      expect(reportMock).toHaveBeenLastCalledWith(thisYear, { limit: 100, offset: 100 });
    });

    fireEvent.click(screen.getByRole("tab", { name: /Wash sales/ }));
    await screen.findByRole("heading", { name: /Wash sales by symbol/i });
    // The Wash sales tab's own first page -- offset 0 -- not the 100 Disposals was just paged to.
    expect(reportMock).toHaveBeenLastCalledWith(thisYear, { limit: 100, offset: 0 });
  });
});

describe("main disclaimer", () => {
  it("leads with a 'Not advice' status pill, ahead of the unchanged title and body", async () => {
    // `isEmptyReport` would otherwise swap the report view for the import-nudge placeholder, which
    // does not render this disclaimer -- at least one gains row keeps the page on the real view.
    await renderTax(taxReport({ gains: gainsReport({ rows: [gainRow()] }) }));

    const disclaimer = document.querySelector(".panel.disclaimer")!;
    const pill = disclaimer.querySelector(".status-pill-warn")!;
    expect(pill).not.toBeNull();
    expect(pill.textContent).toBe("Not advice");

    // The lead sentence is the canonical short form from the language audit -- the same words on
    // this page and on Wash Sales, which is what makes it one disclaimer rather than two. `getByText`
    // throws if no match is found, so reaching the next assertion is itself proof of the wording.
    screen.getByText("Calculation only, not tax advice.", { selector: "strong" });
    expect(disclaimer.textContent).toContain(
      "Reconcile every figure below against your actual 1099-B forms before filing.",
    );

    // The pill renders before the title in document order, per the DOM.
    const strongEl = disclaimer.querySelector("strong")!;
    expect(pill.compareDocumentPosition(strongEl) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("names what the engine cannot see -- options and unconnected accounts -- on the page that generates the Form 8949", async () => {
    // The Wash Sales page said this and this page did not, which is backwards: §1091 applies across
    // every account a taxpayer controls, and this is where the form a filer actually submits is
    // produced. Asserted on the Summary tab and again on Form 8949 below, the two tabs a filer is on
    // when the numbers leave the app.
    await renderTax(taxReport({ gains: gainsReport({ rows: [gainRow()] }) }));

    const disclaimer = document.querySelector(".panel.disclaimer")!;
    expect(disclaimer.textContent).toContain("Excludes options and purchases in unconnected accounts");
    expect(disclaimer.textContent).toContain("including a spouse's");
  });

  it("keeps that scope sentence on the Form 8949 tab", async () => {
    await renderF8949(
      taxReport({
        gains: gainsReport({ rows: [gainRow()] }),
        form8949: form8949Report({ rows: [form8949Row()] }),
      }),
    );

    const disclaimer = document.querySelector(".panel.disclaimer")!;
    expect(disclaimer.textContent).toContain("Excludes options and purchases in unconnected accounts");
  });
});

// ---------------------------------------------------------------------------
// Summary tile scope
//
// Every tile in the Summary row is one tax year (`GainsReport` is built from the disposals inside
// `[start, end]`, aggregates included), and the deferred wash-sale tile has a whole-ledger twin on
// the Wash Sales page several times its size. Unlabelled, the two read as the same quantity
// disagreeing with itself. DEFINITIONS.md standing rule 2.
// ---------------------------------------------------------------------------

describe("summary tiles carry their scope", () => {
  it("names the tax year in every tile label, not in a hint under one of them", async () => {
    await renderTax(
      taxReport({
        gains: gainsReport({
          rows: [gainRow()],
          short_term_gain: "100.00",
          disallowed_loss_total: "400.00",
        }),
      }),
    );

    const grid = document.querySelector(".tile-grid")!;
    const labels = [...grid.querySelectorAll(".label")].map((el) => el.textContent);
    expect(labels).toEqual([
      `Short-term gain (${thisYear})`,
      `Long-term gain (${thisYear})`,
      `Net gain (${thisYear})`,
      `Wash-sale disallowed, deferred (${thisYear})`,
      `Permanently disallowed, IRA (${thisYear})`,
    ]);
  });

  it("re-labels the tiles when the year selector moves, rather than pinning the first year loaded", async () => {
    await renderTax(
      taxReport({ gains: gainsReport({ rows: [gainRow()], short_term_gain: "100.00" }) }),
    );

    fireEvent.change(screen.getByLabelText(/Tax year/), {
      target: { value: String(thisYear - 1) },
    });

    await waitFor(() =>
      expect(screen.getByText(`Net gain (${thisYear - 1})`)).toBeTruthy(),
    );
  });
});

describe("cross-links (UX refactor 3.3)", () => {
  it("links a disposal row's symbol to the Symbol page", async () => {
    await renderTax(
      taxReport({ gains: gainsReport({ rows: [gainRow({ symbol: "AAPL" })] }) }),
      "/tax?tab=disposals",
    );
    await screen.findByTestId("disposals-table");

    const link = screen.getByRole("link", { name: "AAPL" });
    expect(link.getAttribute("href")).toBe("/symbol/AAPL");
  });

  it("links a wash-sale event row's symbol to the Symbol page, and the row itself to the Disposals tab", async () => {
    await renderWash(taxReport({ wash_sales: [washSaleEvent({ symbol: "TSLA" })] }));

    const symbolLink = screen.getByRole("link", { name: "TSLA" });
    expect(symbolLink.getAttribute("href")).toBe("/symbol/TSLA");

    const disposalsLink = screen.getByRole("link", { name: "see disposals" });
    expect(disposalsLink.getAttribute("href")).toBe("/tax?tab=disposals");
  });
});

/**
 * The open-window tracker folded in from the former `/wash-sales` page.
 *
 * `/wash-sales` redirects here (see `App.test.tsx`), so this tab is now the only place that surface
 * is reachable and it has to actually render. The one thing worth pinning beyond "it is present" is
 * that it stays *distinguishable* from the two year-scoped wash-sale panels above it: they answer
 * "what did wash sales cost me in this tax year", it answers "which windows are open today", and a
 * reader comparing two tables that legitimately disagree needs the scope stated, not inferred.
 */
describe("the Wash sales tab carries the whole-ledger open-window tracker", () => {
  it("renders the tracker's open-window row beneath the year-scoped panels", async () => {
    trackerMock.mockResolvedValue(
      washSaleTracker({
        open_window_count: 1,
        symbol_count: 1,
        symbols: [
          washSaleTrackerSymbol({ symbol: "SOXL", days_until_safe: 4, repurchase_safe_on: "2026-08-21" }),
        ],
      }),
    );

    await renderWash(taxReport({ wash_sales: [washSaleEvent()] }));

    // Its own subheading, naming the scope that makes it different from the panels above it.
    expect(
      await screen.findByRole("heading", { name: /Open repurchase windows, whole ledger/ }),
    ).toBeTruthy();

    const openTable = document.querySelector(".wsale-open-table");
    expect(openTable).not.toBeNull();
    expect((openTable as HTMLElement).textContent).toContain("SOXL");
    expect((openTable as HTMLElement).textContent).toContain("2026-08-21");
  });

  it("does not mount the tracker on any other tab", async () => {
    // Only the active tab's subtree is mounted -- the whole point of this page's tab split, and the
    // reason folding another fetching surface into one tab does not cost the other three anything.
    await renderTax(taxReport({ gains: gainsReport({ rows: [gainRow()] }) }));

    expect(screen.queryByRole("heading", { name: /Open repurchase windows, whole ledger/ })).toBeNull();
    expect(trackerMock).not.toHaveBeenCalled();
  });
});

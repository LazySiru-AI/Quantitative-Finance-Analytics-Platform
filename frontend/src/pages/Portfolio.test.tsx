/**
 * The portfolio page's honesty rules, at render level.
 *
 * Every rule asserted here is stated somewhere in this codebase as a requirement and was, until
 * now, enforced only by whoever last read the file:
 *
 * - a withheld figure renders `—`, never `$0.00` (`app.core.cash`, `api/portfolio.ts`);
 * - a partial total names what it excludes, at the point the total is shown, not in a footnote —
 *   the behaviour a UAT persona explicitly credited the page for;
 * - the summary total carries an as-of, and says outright when it is mixing pricing dates;
 * - equity is withheld unless both halves are complete, because there is no honest partial version
 *   of "what is this worth".
 *
 * Two of these have already been broken once each and fixed — see the null-safety note in
 * `d5c6bae`, where `.filter()` narrowing nothing for the type checker would have rendered `$0.00`
 * for an absent figure in a module whose own docstring forbids it in as many words.
 *
 * The API module is stubbed rather than `fetch`: it is the seam the page actually depends on, and
 * stubbing at the transport would make these tests about JSON parsing instead of about rendering.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  formatMoney,
  multiplyMoneyByQuantity,
  subtractMoney,
  sumMoney,
  type AccountCashBalance,
  type AccountPosition,
  type AccountSummary,
  type PortfolioReport,
  type Position,
  type SectorVocabulary,
} from "@/api/portfolio";
import type { WashSaleTracker, WashSaleTrackerSymbol } from "@/api/washsales";

const reportMock = vi.fn<() => Promise<PortfolioReport>>();
const sectorsMock = vi.fn<() => Promise<SectorVocabulary>>();
const setSectorMock = vi.fn<(symbol: string, sector: string) => Promise<{ symbol: string; sector: string }>>();

vi.mock("@/api/portfolio", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/portfolio")>();
  return {
    ...actual,
    portfolioApi: {
      ...actual.portfolioApi,
      report: () => reportMock(),
      sectors: () => sectorsMock(),
      setSector: (symbol: string, sector: string) => setSectorMock(symbol, sector),
    },
  };
});

// Read-only: the wash-sale tracker the By-tax-treatment view's Deferred loss column reads from.
// Stubbed at the module boundary, same as `portfolioApi` above, so a test that does not care about
// it can just resolve an empty tracker rather than the page's fetch hanging forever.
const washTrackerMock = vi.fn<() => Promise<WashSaleTracker>>();

vi.mock("@/api/washsales", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/washsales")>();
  return {
    ...actual,
    washSalesApi: { ...actual.washSalesApi, tracker: () => washTrackerMock() },
  };
});

// The page also reads store status for its header tiles. Irrelevant to everything below, and left
// rejecting so a test that started depending on it would say so rather than quietly pass.
vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    api: { ...actual.api, stores: () => Promise.reject(new Error("stores not stubbed")) },
  };
});

const { default: Portfolio } = await import("@/pages/Portfolio");

function washSaleTrackerSymbol(overrides: Partial<WashSaleTrackerSymbol> = {}): WashSaleTrackerSymbol {
  return {
    symbol: "SOXL",
    deferred_disallowed: "150.00",
    permanently_disallowed: "0.00",
    event_count: 1,
    loss_sale_count: 1,
    first_sale_date: "2026-07-01",
    last_sale_date: "2026-07-01",
    repurchase_safe_on: "2026-08-01",
    days_until_safe: 0,
    window_is_open: false,
    accounts: ["rh-taxable"],
    sales: [],
    ...overrides,
  };
}

function washSaleTracker(overrides: Partial<WashSaleTracker> = {}): WashSaleTracker {
  return {
    as_of: "2026-08-06",
    generated_at: "2026-08-06T00:00:00Z",
    total_deferred: "150.00",
    total_permanently_disallowed: "0.00",
    open_window_count: 0,
    symbol_count: 1,
    symbols: [washSaleTrackerSymbol()],
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
    // Neutral defaults for the account-status shard's new fields -- most tests below do not care
    // about sector or day-change, so the default is the "nothing to say" value each field itself
    // documents (an unmapped sector, and `null` day-change under "the store could not produce two
    // bars"), never a value likely to collide with a test's own assertions.
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
    // Nothing pending by default -- matches `unsettled: "0"` above, per
    // `AccountCash.unsettled_next_date`'s "nothing pending" rule. Tests that override `unsettled` to a
    // nonzero figure supply their own date(s); tests that withhold the split override both together.
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

/** One entry in the new `report.accounts` roster (`AccountSummary[]`) that drives the by-account
 *  picker's option list and its "N open" status-strip hint. Defaults match `accountCash()`'s own
 *  default `account_id`/`account_label`/`broker` so a test that overrides one to point at the same
 *  account does not have to repeat itself in both places.
 *
 *  `realized_gain` defaults to a small NONZERO figure rather than `"0.00"` -- deliberately, per the
 *  functional-fix-2 Realized/Accumulated tiles: with a zero default, Accumulated (`realized_gain +
 *  unrealizedTotal`) would always render the exact same text as the Unrealized tile, and a test that
 *  scopes `getByText` to one exact money string inside an account panel would then match two
 *  elements and throw. `"10.00"` is distinct from every other dollar figure this file's account-view
 *  fixtures produce. */
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

function report(overrides: Partial<PortfolioReport> = {}): PortfolioReport {
  return {
    as_of: "2026-08-06",
    generated_at: "2026-08-14T00:00:00Z",
    positions: [position()],
    total_cost_basis: "1205.00",
    total_market_value: "1300.00",
    total_unrealized: "95.00",
    total_unrealized_pct: 0.0788,
    priced_position_count: 1,
    unpriced_symbols: [],
    cash_balance: "4068.33",
    settled_cash: "3017.88",
    unsettled_cash: "1050.45",
    // A range, not one date -- the default fixture deliberately exercises the "more than one
    // settlement date" path, since that is the case the settlement-date feature exists to render
    // honestly (see `settlementClause`'s docstring). Tests that need a single-date or "nothing
    // pending" shape override these alongside `unsettled_cash`.
    unsettled_next_date: "2026-08-10",
    unsettled_full_date: "2026-08-13",
    total_equity: "5368.33",
    equity_is_complete: true,
    accounts_without_cash: [],
    cash_by_account: [],
    positions_with_uncertain_basis: 0,
    positions_with_unknown_fees: 0,
    warnings: [],
    warning_groups: [],
    // Empty by default -- most tests below never open the by-account picker, and an empty roster
    // renders its own designed "no positions" placeholder rather than crashing (see `AccountsView`).
    // Tests that DO switch to "By account" supply their own `accounts` alongside matching
    // `cash_by_account`/`positions` entries.
    accounts: [],
    open_account_count: 0,
    total_day_change: null,
    total_day_change_pct: null,
    excluded_closed_positions: 0,
    excluded_closed_symbols: [],
    ...overrides,
  };
}

async function renderPortfolio(data: PortfolioReport) {
  reportMock.mockResolvedValue(data);
  render(
    <MemoryRouter>
      <Portfolio />
    </MemoryRouter>,
  );
  // The page renders its heading immediately and the report after the promise resolves.
  await screen.findByText(/Ledger as of|Positions as of/);
}

/** Renders `location.pathname + location.search` into the DOM so a test can assert on the URL a
 *  `useUrlState` call wrote, without reaching into `MemoryRouter`'s internal history stack. */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname + location.search}</div>;
}

/** Like `renderPortfolio`, but starting from a given URL (e.g. a bookmarked
 *  `"/portfolio?view=account&account=wb-margin"` deep link) and with a `LocationProbe` mounted
 *  alongside `Portfolio` so a test can also assert on where `useUrlState`'s two rails land the URL
 *  after a click. */
async function renderPortfolioAt(data: PortfolioReport, initialEntry: string) {
  reportMock.mockResolvedValue(data);
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <LocationProbe />
      <Portfolio />
    </MemoryRouter>,
  );
  await screen.findByText(/Ledger as of|Positions as of/);
}

beforeEach(() => {
  reportMock.mockReset();
  // `Portfolio` fetches the sector vocabulary unconditionally on mount (every row's
  // `SectorBadgeEditor` shares this one fetch) and the By-tax-treatment view fetches the wash-sale
  // tracker on its own mount -- both get a harmless default here so tests that do not care about
  // either still render cleanly; the tests that DO care override these explicitly.
  sectorsMock.mockReset();
  sectorsMock.mockResolvedValue({ vocabulary: [], map: {} });
  setSectorMock.mockReset();
  washTrackerMock.mockReset();
  washTrackerMock.mockResolvedValue(washSaleTracker({ symbols: [] }));
});

describe("withheld figures", () => {
  it("renders an absent cash balance as a dash, not as zero", async () => {
    /**
     * The shape this guards is the real one: on a real ledger **every** account's cash
     * can be withheld, because a broker export may carry no funding rows or may begin
     * after the accounts were funded. `$0.00` there would state that the user holds no cash.
     */
    await renderPortfolio(
      report({
        cash_balance: null,
        settled_cash: null,
        unsettled_cash: null,
        unsettled_next_date: null,
        unsettled_full_date: null,
        total_equity: null,
        equity_is_complete: false,
        accounts_without_cash: ["rh-taxable", "wb-cash", "wb-margin"],
      }),
    );

    const body = document.body.textContent ?? "";
    expect(body).toContain("—");
    // The withheld figures must not have become zeros. A genuine $0.00 elsewhere on the page is
    // fine; what must not appear is the cash *tile* reading zero, so the assertion is scoped.
    const cashTile = screen.getByText(/^Cash\b/).closest(".stat");
    expect(cashTile?.textContent).not.toContain("$0.00");
    expect(cashTile?.textContent).toContain("—");
  });

  it("names the accounts excluded from a partial cash total", async () => {
    await renderPortfolio(
      report({
        cash_balance: "1000.00",
        unsettled_cash: "0",
        unsettled_next_date: null,
        unsettled_full_date: null,
        accounts_without_cash: ["wb-cash", "wb-margin"],
      }),
    );
    expect(document.body.textContent).toContain("2 accounts excluded");
  });

  it("states the exclusion even when there are also unsettled proceeds", async () => {
    /**
     * Both facts belong on that tile and they used to compete for it: the settled/unsettled split
     * won the single hint slot and the size of the gap was stated nowhere. This test is what found
     * that. The `(partial)` in the label flags *that* there is a gap; naming it is a separate
     * obligation, and the one `unpriced_symbols` discharges two tiles over.
     */
    await renderPortfolio(
      report({
        cash_balance: "1000.00",
        settled_cash: "800.00",
        unsettled_cash: "200.00",
        accounts_without_cash: ["wb-cash", "wb-margin", "wb-roth"],
      }),
    );
    const body = document.body.textContent ?? "";
    expect(body).toContain("3 accounts excluded");
    expect(body).toContain("unsettled");
    // The settlement-date clause rides alongside the settled/unsettled split rather than competing
    // with it for the same slot -- unlike the accounts-excluded fact above, this one is *part of* the
    // unsettled figure's own sentence, not a second fact fighting for room.
    expect(body).toContain("clears 2026-08-10 → 2026-08-13");
  });

  it("withholds equity rather than understating it", async () => {
    /**
     * Unlike its two components, an equity figure has no honest partial version: it is read as
     * *the* answer to "what is this worth". The server withholds it; the page must not fill the gap
     * back in.
     */
    await renderPortfolio(
      report({ total_equity: null, equity_is_complete: false, cash_balance: null }),
    );
    const equityTile = screen.getByText(/Total equity/i).closest(".stat");
    expect(equityTile?.textContent).toContain("—");
    expect(equityTile?.textContent).not.toContain("$0.00");
  });
});

describe("when the unsettled cash clears", () => {
  /**
   * `portfolio-unsettled-cash-lacks-settlement-date` (BACKLOG.md §R13): the settle date behind the
   * unsettled figure was computed on the server and discarded before it reached this page, so a UAT
   * persona had to hand-reconstruct it from the Activity page. These pin the three states the summary
   * tile and each per-account tile must render distinctly: one date, a range of dates, and nothing
   * pending at all (which must render no clause, not a stale-looking blank date).
   */
  it("shows a single settlement date on the summary tile when every pending row shares one", async () => {
    await renderPortfolio(
      report({
        cash_balance: "4240.00",
        settled_cash: "4000.00",
        unsettled_cash: "240.00",
        unsettled_next_date: "2026-08-10",
        unsettled_full_date: "2026-08-10",
      }),
    );
    const cashTile = screen.getByText(/^Cash\b/).closest(".stat");
    expect(cashTile?.textContent).toContain("clears 2026-08-10");
    // A single shared date must not render as a range -- the arrow would claim two different dates
    // exist when there is only one.
    expect(cashTile?.textContent).not.toContain("→");
  });

  it("shows the full range on the summary tile when pending rows settle on different dates", async () => {
    await renderPortfolio(
      report({
        cash_balance: "4252.34",
        settled_cash: "4000.00",
        unsettled_cash: "252.34",
        unsettled_next_date: "2026-08-10",
        unsettled_full_date: "2026-08-13",
      }),
    );
    const cashTile = screen.getByText(/^Cash\b/).closest(".stat");
    expect(cashTile?.textContent).toContain("clears 2026-08-10 → 2026-08-13");
  });

  it("shows no settlement clause on the summary tile when nothing is pending", async () => {
    await renderPortfolio(
      report({
        cash_balance: "4000.00",
        settled_cash: "4000.00",
        unsettled_cash: "0",
        unsettled_next_date: null,
        unsettled_full_date: null,
      }),
    );
    const cashTile = screen.getByText(/^Cash\b/).closest(".stat");
    expect(cashTile?.textContent).not.toContain("clears");
  });

  it("carries the same settlement date onto the per-account cash tile", async () => {
    await renderPortfolio(
      report({
        // Gives "rh-taxable" an open position, per `accountPosition()`'s default `account_id`, so
        // the account card renders by default -- see the module docstring's "accounts holding
        // nothing" rule for why an account with no position and no cash of its own is hidden.
        positions: [position({ accounts: [accountPosition()] })],
        cash_by_account: [
          accountCash({
            balance: "4240.00",
            settled: "4000.00",
            unsettled: "240.00",
            unsettled_next_date: "2026-08-10",
            unsettled_full_date: "2026-08-10",
          }),
        ],
        accounts: [accountSummary()],
      }),
    );
    fireEvent.click(screen.getByRole("tab", { name: "By account" }));
    // The account rail defaults to "All open accounts" now (`?account=all-open`), so this selects
    // the one real account explicitly rather than relying on it being first.
    fireEvent.click(screen.getByRole("tab", { name: /Robinhood Taxable/ }));
    const section = screen
      .getByRole("heading", { level: 2, name: "Robinhood Taxable" })
      .closest(".account-card") as HTMLElement;
    // Scoped to the money-tile row specifically: a positive cash balance also renders a "Cash"
    // legend row in the account's own allocation pie now (`AllocationPie`'s cash slice), which is a
    // second, textually-identical "Cash" -- `.account-card-figures` is the money tiles alone.
    const figures = section.querySelector(".account-card-figures") as HTMLElement;
    const cashTile = within(figures).getByText(/^Cash\b/).closest(".stat");
    expect(cashTile?.textContent).toContain("clears 2026-08-10");
  });
});

describe("partial totals", () => {
  it("names the unpriced symbols where the total is displayed", async () => {
    // SPCX (pre-IPO) and ETH have no reliable quote, and this is the behaviour the UAT persona
    // credited by name: the exclusion is stated at the total, not in a footnote.
    await renderPortfolio(
      report({
        unpriced_symbols: ["SPCX", "ETH"],
        positions: [position(), position({ symbol: "SPCX", price: null, price_as_of: null, market_value: null })],
      }),
    );
    const body = document.body.textContent ?? "";
    expect(body).toContain("SPCX");
    expect(body).toContain("ETH");
  });

  it("stays visible, unlike the other three caveats, inside the merged strip", async () => {
    // The four caveat blocks (partial totals, cash, uncertainty, closed accounts) collapsed into one
    // `.caveat-strip` panel -- this pins that the merge did not touch the one rule that matters:
    // partial totals is load-bearing and must never be a click away, while the other three keep
    // their own `InfoNote` disclosure exactly as before.
    await renderPortfolio(
      report({
        unpriced_symbols: ["SPCX"],
        positions: [position(), position({ symbol: "SPCX", price: null, price_as_of: null, market_value: null })],
        positions_with_uncertain_basis: 1,
        excluded_closed_positions: 1,
        excluded_closed_symbols: ["OLDCO"],
      }),
    );
    const strip = document.querySelector(".caveat-strip") as HTMLElement;
    expect(strip).not.toBeNull();
    // Partial totals: visible directly in the strip's own text, no `<details>` involved.
    expect(within(strip).getByText(/SPCX/).closest("details")).toBeNull();
    // The other two still render inside the merged strip (their own disclosure keeps their long
    // form one click away, same as before the merge -- see `CaveatStrip.tsx`).
    expect(within(strip).getByText(/basis uncertain/i)).toBeTruthy();
    expect(within(strip).getByText(/OLDCO/)).toBeTruthy();
  });
});

describe("the as-of stamp", () => {
  it("states a single pricing date plainly", async () => {
    await renderPortfolio(report());
    expect(document.body.textContent).toContain("priced at the close of");
    expect(document.body.textContent).toContain("2026-08-13");
  });

  it("says outright when the total mixes several pricing dates", async () => {
    /**
     * The case the stamp exists for. Each row already carried its own date; the summary total —
     * the first figure read — silently aggregated all of them.
     */
    await renderPortfolio(
      report({
        positions: [
          position({ price_as_of: "2026-08-11" }),
          position({ instrument_id: "i-nvda", symbol: "NVDA", price_as_of: "2026-08-13" }),
          position({ instrument_id: "i-amd", symbol: "AMD", price_as_of: "2026-08-12" }),
        ],
      }),
    );
    const body = document.body.textContent ?? "";
    expect(body).toContain("2026-08-11");
    expect(body).toContain("2026-08-13");
    expect(body).toMatch(/mix 3 different pricing dates/);
  });

  it("says nothing is priced rather than showing a zero total", async () => {
    await renderPortfolio(
      report({
        positions: [position({ price: null, price_as_of: null, market_value: null, unrealized: null })],
        total_market_value: null,
        total_unrealized: null,
        total_unrealized_pct: null,
        priced_position_count: 0,
        unpriced_symbols: ["SOXL"],
      }),
    );
    expect(document.body.textContent).toContain("nothing is priced");
  });
});

describe("account money helpers", () => {
  /**
   * These back every subtotal in the by-account view below, and the module docstring for
   * `api/portfolio.ts` is explicit that nothing here may drift to `parseFloat`. Tested directly,
   * the same way `addMoney`/`formatMoney` are in `api/money.test.ts` -- this file just owns them
   * because `api/portfolio.ts` has no dedicated test file of its own.
   */
  it("sumMoney adds an arbitrary list exactly, in cents, not in floating point", () => {
    expect(sumMoney(["700.00", "50.00", "0.01"])).toBe("750.01");
    expect(sumMoney([])).toBe("0.00");
    expect(sumMoney(["-2.88", "-3.60", "6.48"])).toBe("0.00");
  });

  it("subtractMoney is exact and handles a negative result", () => {
    expect(subtractMoney("55.00", "50.00")).toBe("5.00");
    expect(subtractMoney("50.00", "55.00")).toBe("-5.00");
  });

  it("multiplyMoneyByQuantity mirrors the backend's quantize_money(price * quantity)", () => {
    expect(multiplyMoneyByQuantity("26.00", "30")).toBe("780.00");
    // A fractional share (a DRIP) priced to the cent lands between cents.
    expect(multiplyMoneyByQuantity("10.00", "5.5")).toBe("55.00");
    expect(multiplyMoneyByQuantity("61.985", "100")).toBe("6198.50");
    // Exact tie rounds away from zero (ROUND_HALF_UP), matching `quantize_money`, not banker's
    // rounding and not truncation.
    expect(multiplyMoneyByQuantity("0.005", "1")).toBe("0.01");
    expect(multiplyMoneyByQuantity("-10.00", "2")).toBe("-20.00");
  });
});

describe("by-account view", () => {
  /**
   * The account-level counterpart to `describe("withheld figures")` and
   * `describe("partial totals")` above: same honesty rules, applied to the per-account slice the
   * instrument roll-up hides rather than to the report-wide totals. See the module docstring's
   * "By-instrument is the default" section for why the roll-up stays default and this is a second
   * lens, not a replacement.
   */
  function switchToAccountView() {
    fireEvent.click(screen.getByRole("tab", { name: "By account" }));
  }

  it("toggles between the by-instrument and by-account views", async () => {
    await renderPortfolio(
      report({
        positions: [position({ accounts: [accountPosition()] })],
        cash_by_account: [accountCash()],
        accounts: [accountSummary()],
      }),
    );

    // "Robinhood Taxable" also appears as a row in the always-rendered "Cash by account" panel
    // below, so presence is checked via the account-card heading specifically, not via the
    // label text alone.
    const accountHeading = () =>
      screen.queryByRole("heading", { level: 2, name: "Robinhood Taxable" });

    expect(screen.getByRole("tab", { name: "By instrument" }).getAttribute("aria-selected")).toBe(
      "true",
    );
    expect(screen.getByText("Positions")).toBeTruthy();
    expect(accountHeading()).toBeNull();

    switchToAccountView();
    // The account rail defaults to "All open accounts", not any one account -- select the one real
    // account explicitly so the heading this test checks actually appears.
    fireEvent.click(screen.getByRole("tab", { name: /Robinhood Taxable/ }));

    expect(screen.getByRole("tab", { name: "By account" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.queryByText("Positions")).toBeNull();
    expect(accountHeading()).toBeTruthy();

    // Switching back restores the unchanged default table -- the toggle is non-destructive.
    fireEvent.click(screen.getByRole("tab", { name: "By instrument" }));
    expect(screen.getByText("Positions")).toBeTruthy();
    expect(accountHeading()).toBeNull();
  });

  it("computes per-account subtotals exactly from decimal strings", async () => {
    const soxlAccount = accountPosition({ quantity: "30", cost_basis: "700.00" });
    const nvdaAccount = accountPosition({ quantity: "5.5", cost_basis: "50.00" });
    await renderPortfolio(
      report({
        positions: [
          position({
            instrument_id: "i-soxl",
            symbol: "SOXL",
            price: "26.00",
            accounts: [soxlAccount],
          }),
          position({
            instrument_id: "i-nvda",
            symbol: "NVDA",
            price: "10.00",
            market_value: "55.00",
            unrealized: "5.00",
            accounts: [nvdaAccount],
          }),
        ],
        cash_by_account: [accountCash()],
        accounts: [accountSummary()],
      }),
    );

    switchToAccountView();
    // Defaults to "All open accounts" now -- select the one real account explicitly.
    fireEvent.click(screen.getByRole("tab", { name: /Robinhood Taxable/ }));

    const expectedMarketValue = sumMoney([
      multiplyMoneyByQuantity("26.00", "30"),
      multiplyMoneyByQuantity("10.00", "5.5"),
    ]);
    const expectedCostBasis = sumMoney(["700.00", "50.00"]);
    const expectedUnrealized = subtractMoney(expectedMarketValue, expectedCostBasis);
    expect(expectedMarketValue).toBe("835.00");
    expect(expectedUnrealized).toBe("85.00");

    const section = screen
      .getByRole("heading", { level: 2, name: "Robinhood Taxable" })
      .closest(".account-card");
    expect(section).not.toBeNull();
    const scoped = within(section as HTMLElement);
    expect(scoped.getByText(formatMoney(expectedCostBasis))).toBeTruthy();
    expect(scoped.getByText(formatMoney(expectedMarketValue))).toBeTruthy();
    expect(scoped.getByText(`+${formatMoney(expectedUnrealized)}`)).toBeTruthy();
  });

  it("shows a Realized tile with the selected account's all-time realized_gain", async () => {
    /**
     * Functional fix 2 (UAT major): `AccountSummary.realized_gain` was computed at real cost and
     * summed into the whole-page Accumulated tile, but never surfaced for the selected account
     * itself. This pins the Realized tile's value to the selected account's own figure -- not the
     * page total -- and that Accumulated on this panel is realized plus this panel's unrealized,
     * not the page-wide unrealized.
     */
    await renderPortfolio(
      report({
        positions: [position({ price: "26.00", accounts: [accountPosition()] })],
        cash_by_account: [accountCash()],
        accounts: [accountSummary({ realized_gain: "321.45" })],
      }),
    );

    switchToAccountView();
    // Defaults to "All open accounts" now -- select the one real account explicitly.
    fireEvent.click(screen.getByRole("tab", { name: /Robinhood Taxable/ }));

    const section = screen
      .getByRole("heading", { level: 2, name: "Robinhood Taxable" })
      .closest(".account-card") as HTMLElement;
    const figures = section.querySelector(".account-card-figures") as HTMLElement;
    const realizedTile = within(figures).getByText("Realized").closest(".stat");
    expect(realizedTile?.textContent).toContain(formatMoney("321.45"));

    // Accumulated = this account's realized_gain + this panel's own unrealized total, not the
    // page-wide unrealized (the fixture's single position is worth $1,300, cost $1,205 -> +$95.00
    // unrealized, so Accumulated is 321.45 + 95.00 = 416.45).
    const accumulatedTile = within(figures).getByText("Accumulated").closest(".stat");
    expect(accumulatedTile?.textContent).toContain(formatMoney("416.45"));
  });

  it("marks an account's subtotal partial, not silently short, when one of its positions is unpriced", async () => {
    // BRK.B is a realistic case: a ticker that can be genuinely unpriced.
    const pricedSlice = accountPosition({ quantity: "30", cost_basis: "700.00" });
    const unpricedSlice = accountPosition({ quantity: "10", cost_basis: "200.00" });
    await renderPortfolio(
      report({
        positions: [
          position({
            instrument_id: "i-soxl",
            symbol: "SOXL",
            price: "26.00",
            accounts: [pricedSlice],
          }),
          position({
            instrument_id: "i-brkb",
            symbol: "BRK.B",
            price: null,
            price_as_of: null,
            market_value: null,
            unrealized: null,
            accounts: [unpricedSlice],
          }),
        ],
        unpriced_symbols: ["BRK.B"],
        cash_by_account: [accountCash()],
        accounts: [accountSummary()],
      }),
    );

    switchToAccountView();
    // Defaults to "All open accounts" now -- select the one real account explicitly.
    fireEvent.click(screen.getByRole("tab", { name: /Robinhood Taxable/ }));

    const section = screen
      .getByRole("heading", { level: 2, name: "Robinhood Taxable" })
      .closest(".account-card") as HTMLElement;
    const scoped = within(section);
    expect(scoped.getByText(/Market value \(partial\)/)).toBeTruthy();
    expect(scoped.getByText("1 of 2 priced")).toBeTruthy();
    // The subtotal is the priced row's market value alone -- not zero, not silently omitted. It
    // renders twice in this fixture (the account's subtotal tile, and the lone priced row's own
    // market-value cell happen to be the same number here), so this checks presence rather than a
    // single match.
    const expectedMarketValue = multiplyMoneyByQuantity("26.00", "30");
    expect(expectedMarketValue).toBe("780.00");
    expect(scoped.getAllByText(formatMoney(expectedMarketValue)).length).toBeGreaterThan(0);
    expect(
      scoped.getByText("Unpriced — no market data, excluded from this account's totals above"),
    ).toBeTruthy();
  });

  it("does not let one account's basis_uncertain flag leak onto another account's clean slice (the DRAM case)", async () => {
    // Mirrors the real finding: DRAM held at two brokers, one account's basis uncertain, the
    // other's clean, and the roll-up badges the combined row "uncertain basis" regardless. Unlike
    // the old three-column grid (which rendered both accounts' cards at once), the by-account view
    // now shows one account's panel at a time, so this checks the flag by selecting each account in
    // turn through the picker rather than by scoping two simultaneously-rendered cards.
    const flaggedSlice = accountPosition({
      account_id: "wb-margin",
      account_label: "Webull Margin",
      broker: "Webull",
      quantity: "100",
      cost_basis: "6198.50",
      basis_uncertain: true,
    });
    const cleanSlice = accountPosition({
      account_id: "rh-taxable",
      account_label: "Robinhood Taxable",
      broker: "Robinhood",
      quantity: "300",
      cost_basis: "18595.50",
      basis_uncertain: false,
    });
    await renderPortfolio(
      report({
        positions: [
          position({
            instrument_id: "i-dram",
            symbol: "DRAM",
            quantity: "400",
            price: "61.985",
            cost_basis: "24794.00",
            market_value: "24794.00",
            unrealized: "0.00",
            basis_uncertain: true, // the aggregate row inherits the worse flag -- this is the bug
            accounts: [flaggedSlice, cleanSlice],
          }),
        ],
        cash_by_account: [
          accountCash({ account_id: "wb-margin", account_label: "Webull Margin", broker: "Webull" }),
          accountCash(),
        ],
        accounts: [
          accountSummary({ account_id: "wb-margin", label: "Webull Margin", broker: "Webull" }),
          accountSummary(),
        ],
      }),
    );

    switchToAccountView();
    // Defaults to "All open accounts" now -- select "Webull Margin", the flagged one, explicitly.
    fireEvent.click(screen.getByRole("tab", { name: /Webull Margin/ }));
    const flaggedSection = screen
      .getByRole("heading", { level: 2, name: "Webull Margin" })
      .closest(".account-card") as HTMLElement;
    expect(within(flaggedSection).getByText("uncertain basis")).toBeTruthy();

    fireEvent.click(screen.getByRole("tab", { name: /Robinhood Taxable/ }));

    const cleanSection = screen
      .getByRole("heading", { level: 2, name: "Robinhood Taxable" })
      .closest(".account-card") as HTMLElement;
    expect(within(cleanSection).queryByText("uncertain basis")).toBeNull();
  });

  it("renders a withheld account's cash reason, never a fabricated $0.00", async () => {
    await renderPortfolio(
      report({
        positions: [
          position({
            accounts: [
              accountPosition({ account_id: "wb-cash", account_label: "Webull Cash", broker: "Webull" }),
            ],
          }),
        ],
        cash_by_account: [
          accountCash({
            account_id: "wb-cash",
            account_label: "Webull Cash",
            broker: "Webull",
            verdict: "no_funding_rows",
            balance: null,
            settled: null,
            unsettled: null,
            reason:
              "Webull exported order history only -- no deposits, withdrawals or income rows -- so a cash balance cannot be reconstructed from it",
          }),
        ],
        accounts: [accountSummary({ account_id: "wb-cash", label: "Webull Cash", broker: "Webull" })],
      }),
    );

    switchToAccountView();
    fireEvent.click(screen.getByRole("tab", { name: /Webull Cash/ }));

    const section = screen
      .getByRole("heading", { level: 2, name: "Webull Cash" })
      .closest(".account-card") as HTMLElement;
    const scoped = within(section);
    const cashTile = scoped.getByText(/^Cash\b/).closest(".stat");
    expect(cashTile).not.toBeNull();
    expect(cashTile?.textContent).toContain("—");
    expect(cashTile?.textContent).not.toContain("$0.00");
    expect(scoped.getByText(/no deposits, withdrawals or income rows/)).toBeTruthy();
  });

  it("shows the account's tax treatment as a headline next to its name", async () => {
    await renderPortfolio(
      report({
        positions: [
          position({
            accounts: [
              accountPosition({ account_id: "wb-roth", account_label: "Webull Roth", broker: "Webull" }),
            ],
          }),
        ],
        cash_by_account: [
          accountCash({ account_id: "wb-roth", account_label: "Webull Roth", broker: "Webull", tax_treatment: "roth_ira" }),
        ],
        accounts: [
          accountSummary({ account_id: "wb-roth", label: "Webull Roth", broker: "Webull", tax_treatment: "roth_ira" }),
        ],
      }),
    );

    switchToAccountView();
    fireEvent.click(screen.getByRole("tab", { name: /Webull Roth/ }));

    const section = screen
      .getByRole("heading", { level: 2, name: "Webull Roth" })
      .closest(".account-card") as HTMLElement;
    expect(within(section).getByText(/Roth IRA/)).toBeTruthy();
  });
});

describe("accounts holding nothing", () => {
  /**
   * The real shape this guards: on a real ledger, some accounts can exist while holding
   * nothing. There is no more hide-by-default mechanism now that "By account" is a picker rather
   * than a grid of cards -- every account the report knows about is listed in the picker regardless
   * of what it holds (see `AccountsView` in `Portfolio.tsx`), and selecting one that holds nothing
   * shows a designed empty state rather than a blank table.
   */
  function switchToAccountView() {
    fireEvent.click(screen.getByRole("tab", { name: "By account" }));
  }

  it("lists an account with no open positions in the picker and shows a designed empty state when selected", async () => {
    await renderPortfolio(
      report({
        positions: [position({ accounts: [accountPosition()] })],
        cash_by_account: [
          accountCash(),
          accountCash({
            account_id: "rh-roth",
            account_label: "Robinhood Roth",
            broker: "Robinhood",
            verdict: "declared",
            balance: "0.00",
            settled: null,
            unsettled: null,
            declared_as_of: "2026-08-14",
          }),
        ],
        accounts: [
          accountSummary(),
          accountSummary({
            account_id: "rh-roth",
            label: "Robinhood Roth",
            broker: "Robinhood",
            tax_treatment: "roth_ira",
            position_count: 0,
          }),
        ],
      }),
    );

    switchToAccountView();

    // Listed in the rail even though it holds nothing.
    const rail = screen.getByRole("tablist", { name: "Account" });
    expect(within(rail).getByRole("tab", { name: /Robinhood Roth/ })).toBeTruthy();

    fireEvent.click(within(rail).getByRole("tab", { name: /Robinhood Roth/ }));

    expect(screen.getByRole("heading", { level: 2, name: "Robinhood Roth" })).toBeTruthy();
    expect(screen.getByText("No positions in this account.")).toBeTruthy();
  });

  it("does not hide an account that holds cash but genuinely no stock", async () => {
    // The case the task explicitly warns about: a cash-only account is not the same thing as an
    // account holding nothing, even though its position count is also zero.
    await renderPortfolio(
      report({
        positions: [position({ accounts: [accountPosition()] })],
        cash_by_account: [
          accountCash(),
          accountCash({
            account_id: "rh-cash-only",
            account_label: "Robinhood Cash Reserve",
            broker: "Robinhood",
            verdict: "declared",
            balance: "15000.00",
            settled: null,
            unsettled: null,
            declared_as_of: "2026-08-14",
          }),
        ],
        accounts: [
          accountSummary(),
          accountSummary({
            account_id: "rh-cash-only",
            label: "Robinhood Cash Reserve",
            broker: "Robinhood",
            position_count: 0,
          }),
        ],
      }),
    );

    switchToAccountView();
    fireEvent.click(screen.getByRole("tab", { name: /Robinhood Cash Reserve/ }));

    const section = screen
      .getByRole("heading", { level: 2, name: "Robinhood Cash Reserve" })
      .closest(".account-card") as HTMLElement;
    // Scoped to the money tiles: the same dollar figure also renders in the account's own
    // allocation pie legend (a lone Cash slice) and in the always-on "Cash by account" table below,
    // so an unscoped query is ambiguous.
    const figures = section.querySelector(".account-card-figures") as HTMLElement;
    expect(within(figures).getByText(formatMoney("15000.00"))).toBeTruthy();
    expect(screen.getByText("No positions in this account.")).toBeTruthy();
  });
});

describe("account picker: the account rail (FolderTabs)", () => {
  /**
   * The by-account counterpart to Paper Desk's "desk visibility chooser" tests
   * (`PaperDesk.test.tsx`), covering what `ByAccountView`'s `FolderTabs` rail replaced the old
   * `<select>` with: one tab per open account plus "All open" (task DoD (a)), switching the panel on
   * a tab click and writing `?account=` (DoD (b)), and never inventing a tab the payload does not
   * carry. `?view=account&account=<id>` opening straight into that account (DoD (c)) is covered
   * below in `describe("account rail: URL state")`.
   */
  function switchToAccountView() {
    fireEvent.click(screen.getByRole("tab", { name: "By account" }));
  }

  function twoOpenAccountsReport() {
    const soxl = accountPosition({ account_id: "rh-taxable", account_label: "Robinhood Taxable", broker: "Robinhood" });
    const nvda = accountPosition({ account_id: "wb-margin", account_label: "Webull Margin", broker: "Webull" });
    return report({
      positions: [
        position({ instrument_id: "i-soxl", symbol: "SOXL", accounts: [soxl] }),
        position({
          instrument_id: "i-nvda",
          symbol: "NVDA",
          price: "10.00",
          market_value: "500.00",
          unrealized: "50.00",
          accounts: [nvda],
        }),
      ],
      cash_by_account: [
        accountCash({ account_id: "rh-taxable", account_label: "Robinhood Taxable", broker: "Robinhood" }),
        accountCash({ account_id: "wb-margin", account_label: "Webull Margin", broker: "Webull" }),
      ],
      accounts: [
        accountSummary({ account_id: "rh-taxable", label: "Robinhood Taxable", broker: "Robinhood" }),
        accountSummary({ account_id: "wb-margin", label: "Webull Margin", broker: "Webull" }),
      ],
    });
  }

  it("defaults to All open accounts, showing exactly one combined panel", async () => {
    // The account rail's fallback is `"all-open"`, not "the first account" -- the leftmost tab is
    // the one lit by default, matching how the primary view rail itself defaults to its first tab.
    await renderPortfolio(twoOpenAccountsReport());
    switchToAccountView();

    expect(screen.getByRole("heading", { level: 2, name: "All open accounts" })).toBeTruthy();
    expect(document.querySelectorAll(".account-card")).toHaveLength(1);
    expect(screen.getByRole("tab", { name: "All open accounts" }).getAttribute("aria-selected")).toBe("true");
  });

  it("renders one tab per open account, plus All open, left to right in report.accounts order", async () => {
    await renderPortfolio(twoOpenAccountsReport());
    switchToAccountView();

    const rail = screen.getByRole("tablist", { name: "Account" });
    const tabNames = within(rail)
      .getAllByRole("tab")
      .map((tab) => tab.textContent ?? "");
    // "Robinhood Taxable" before "Webull Margin" -- the order `twoOpenAccountsReport()` gives
    // `report.accounts` in -- with "All open accounts" leading and each account tab carrying its
    // position-count/market-value badge (see `accountTabBadge` in `pages/portfolio/aggregates.ts`).
    expect(tabNames).toHaveLength(3);
    expect(tabNames[0]).toBe("All open accounts");
    expect(tabNames[1]).toContain("Robinhood Taxable");
    expect(tabNames[2]).toContain("Webull Margin");
  });

  it("switches the panel and writes ?account= when a different account tab is clicked", async () => {
    await renderPortfolio(twoOpenAccountsReport());
    switchToAccountView();

    fireEvent.click(screen.getByRole("tab", { name: /Webull Margin/ }));

    expect(screen.getByRole("heading", { level: 2, name: "Webull Margin" })).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 2, name: "Robinhood Taxable" })).toBeNull();
    expect(document.querySelectorAll(".account-card")).toHaveLength(1);
    expect(screen.getByRole("tab", { name: /Webull Margin/ }).getAttribute("aria-selected")).toBe("true");
  });

  it('aggregates every open account under "All open accounts"', async () => {
    await renderPortfolio(twoOpenAccountsReport());
    switchToAccountView();
    // Switch away and back, to prove the combined panel is reachable by a click too, not only by
    // being the default.
    fireEvent.click(screen.getByRole("tab", { name: /Webull Margin/ }));
    fireEvent.click(screen.getByRole("tab", { name: "All open accounts" }));

    expect(screen.getByRole("heading", { level: 2, name: "All open accounts" })).toBeTruthy();
    // Both instruments show up combined in the one panel.
    const positionsTable = document.querySelector(".account-position-table") as HTMLElement;
    expect(within(positionsTable).getByText("SOXL")).toBeTruthy();
    expect(within(positionsTable).getByText("NVDA")).toBeTruthy();
  });

  it("never lists a tab for an account the payload does not carry", async () => {
    // There is no fixed named default here (unlike Paper Desk's roster-independent
    // `DEFAULT_VISIBLE_AGENT_IDS`) -- the rail's tabs come straight from `report.accounts`, so an id
    // naming nothing in the current payload cannot enter the rail through the UI.
    await renderPortfolio(twoOpenAccountsReport());
    switchToAccountView();

    const rail = screen.getByRole("tablist", { name: "Account" });
    const tabNames = within(rail)
      .getAllByRole("tab")
      .map((tab) => tab.textContent ?? "");
    expect(tabNames).toHaveLength(3);
  });
});

describe("account picker: open and closed accounts", () => {
  /**
   * UAT blocker fix: the picker used to offer a Closed optgroup too, and selecting a closed account
   * always landed on an empty "no positions" panel because the backend strips a closed account's
   * holdings from `positions` entirely (see `excluded_closed_symbols`) -- a false promise the owner
   * named directly ("a dropdown with the four that's open"). A closed account is now reachable only
   * through the rail's dedicated trailing "Closed (n)" tab (`ByAccountView`'s `ClosedAccountsPanel`),
   * never as a same-shaped tab alongside the open ones.
   */
  it("lists only open accounts as ordinary tabs -- a closed account gets the trailing Closed tab instead", async () => {
    await renderPortfolio(
      report({
        positions: [position({ accounts: [accountPosition()] })],
        cash_by_account: [
          accountCash(),
          accountCash({
            account_id: "rh-roth",
            account_label: "Robinhood Roth",
            broker: "Robinhood",
            verdict: "declared",
            balance: "500.00",
            settled: null,
            unsettled: null,
            declared_as_of: "2026-08-14",
          }),
        ],
        accounts: [
          accountSummary(),
          accountSummary({
            account_id: "rh-roth",
            label: "Robinhood Roth",
            broker: "Robinhood",
            tax_treatment: "roth_ira",
            status: "closed",
            position_count: 0,
          }),
        ],
      }),
    );

    fireEvent.click(screen.getByRole("tab", { name: "By account" }));

    const rail = screen.getByRole("tablist", { name: "Account" });
    const tabNames = within(rail)
      .getAllByRole("tab")
      .map((tab) => tab.textContent ?? "");
    // "All open accounts", the one open account, and a trailing "Closed (1)" -- never a same-shaped
    // "Robinhood Roth" tab standing in for the closed account.
    expect(tabNames).toHaveLength(3);
    expect(tabNames[0]).toBe("All open accounts");
    expect(tabNames[1]).toContain("Robinhood Taxable");
    expect(tabNames[2]).toBe("Closed (1)");
    expect(within(rail).queryByRole("tab", { name: /^Robinhood Roth/ })).toBeNull();

    // The panel still defaults to "All open accounts", never the closed one.
    expect(screen.getByRole("heading", { level: 2, name: "All open accounts" })).toBeTruthy();

    // Clicking the Closed tab shows the closed account's own browsing view, not an empty state.
    fireEvent.click(within(rail).getByRole("tab", { name: "Closed (1)" }));
    const closedHeading = screen.getByRole("heading", { level: 2, name: "Closed accounts" });
    expect(closedHeading).toBeTruthy();
    // Scoped to the Closed tab's own panel: "Robinhood Roth" also appears in the always-rendered
    // "Cash by account" table below (it carries a declared balance), so an unscoped query is
    // ambiguous.
    const closedPanel = closedHeading.closest(".account-card") as HTMLElement;
    expect(within(closedPanel).getByText("Robinhood Roth")).toBeTruthy();
  });
});

describe("account rail: URL state", () => {
  /**
   * The task's definition of done, points (b) and (c): clicking an account tab writes `?account=`
   * so Back and a deep link both work, and a URL that already names `?view=account&account=<id>`
   * opens straight into that account's panel -- no click needed, no flash of "All open accounts"
   * first. `LocationProbe`/`renderPortfolioAt` (see above) read `MemoryRouter`'s location directly
   * rather than reaching into its internal history stack.
   */
  function twoOpenAccountsReport() {
    const soxl = accountPosition({ account_id: "rh-taxable", account_label: "Robinhood Taxable", broker: "Robinhood" });
    const nvda = accountPosition({ account_id: "wb-margin", account_label: "Webull Margin", broker: "Webull" });
    return report({
      positions: [
        position({ instrument_id: "i-soxl", symbol: "SOXL", accounts: [soxl] }),
        position({
          instrument_id: "i-nvda",
          symbol: "NVDA",
          price: "10.00",
          market_value: "500.00",
          unrealized: "50.00",
          accounts: [nvda],
        }),
      ],
      cash_by_account: [
        accountCash({ account_id: "rh-taxable", account_label: "Robinhood Taxable", broker: "Robinhood" }),
        accountCash({ account_id: "wb-margin", account_label: "Webull Margin", broker: "Webull" }),
      ],
      accounts: [
        accountSummary({ account_id: "rh-taxable", label: "Robinhood Taxable", broker: "Robinhood" }),
        accountSummary({ account_id: "wb-margin", label: "Webull Margin", broker: "Webull" }),
      ],
    });
  }

  it("writes ?view=account&account=<id> to the URL when an account tab is clicked", async () => {
    await renderPortfolioAt(twoOpenAccountsReport(), "/portfolio");

    fireEvent.click(screen.getByRole("tab", { name: "By account" }));
    fireEvent.click(screen.getByRole("tab", { name: /Webull Margin/ }));

    const probe = screen.getByTestId("location-probe");
    expect(probe.textContent).toContain("view=account");
    expect(probe.textContent).toContain("account=wb-margin");
  });

  it("writing back to the default account removes ?account= from the URL rather than pinning it", async () => {
    // `useUrlState`'s own contract: the fallback has no representation in the URL, so the default,
    // unremarkable state of the rail is a clean URL, not `?account=all-open` forever after.
    await renderPortfolioAt(twoOpenAccountsReport(), "/portfolio");

    fireEvent.click(screen.getByRole("tab", { name: "By account" }));
    fireEvent.click(screen.getByRole("tab", { name: /Webull Margin/ }));
    fireEvent.click(screen.getByRole("tab", { name: "All open accounts" }));

    const probe = screen.getByTestId("location-probe");
    expect(probe.textContent).not.toContain("account=");
  });

  it("opens straight into the selected account when ?view=account&account=<id> is already in the URL", async () => {
    await renderPortfolioAt(twoOpenAccountsReport(), "/portfolio?view=account&account=wb-margin");

    // No click needed -- the account rail's primary tab AND the secondary account tab both start
    // already selected, and the panel is Webull Margin's, not "All open accounts".
    expect(screen.getByRole("tab", { name: "By account" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("heading", { level: 2, name: "Webull Margin" })).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 2, name: "All open accounts" })).toBeNull();
  });

  it("falls back to the default view/account for a stale or hostile query string, never throwing", async () => {
    await renderPortfolioAt(twoOpenAccountsReport(), "/portfolio?view=account&account=does-not-exist");

    expect(screen.getByRole("heading", { level: 2, name: "All open accounts" })).toBeTruthy();
  });
});

describe("closed-account note", () => {
  it("names the count and symbols excluded because their only account is closed", async () => {
    await renderPortfolio(
      report({
        excluded_closed_positions: 2,
        excluded_closed_symbols: ["OLDCO", "DEFUNCT"],
      }),
    );
    const body = document.body.textContent ?? "";
    expect(body).toContain("OLDCO");
    expect(body).toContain("DEFUNCT");
  });

  it("says nothing when no positions were excluded for a closed account", async () => {
    await renderPortfolio(report({ excluded_closed_positions: 0, excluded_closed_symbols: [] }));
    expect(document.body.textContent).not.toContain("closed account");
  });

  it("uses the singular key for exactly one excluded position, plural for more than one", async () => {
    // Pluralization fix (density UAT): the lazy "(s)" form is gone, replaced by this file's
    // `_one`/`_other` convention -- these pin both branches of `ClosedAccountsNote`'s key choice.
    await renderPortfolio(
      report({ excluded_closed_positions: 1, excluded_closed_symbols: ["OLDCO"] }),
    );
    expect(document.body.textContent).toContain("1 position excluded — closed account: OLDCO");
    expect(document.body.textContent).not.toContain("1 positions excluded");
  });

  it("uses the plural key for more than one excluded position", async () => {
    await renderPortfolio(
      report({ excluded_closed_positions: 2, excluded_closed_symbols: ["OLDCO", "DEFUNCT"] }),
    );
    expect(document.body.textContent).toContain(
      "2 positions excluded — closed account: OLDCO, DEFUNCT",
    );
  });
});

describe("table captions (EXP-15, WCAG 1.3.1)", () => {
  /**
   * Every `<table>` this page renders gets an accessible `<caption>` via `TableCaption`
   * (`@/components/tableSort`) -- visually-hidden by default, naming the table, the row count
   * actually rendered right now, and the account/tax-group scope the surrounding view shows.
   */
  it("captions the by-instrument positions table with the rendered row count", async () => {
    await renderPortfolio(
      report({
        positions: [
          position({ instrument_id: "i-soxl", symbol: "SOXL" }),
          position({ instrument_id: "i-nvda", symbol: "NVDA" }),
        ],
      }),
    );
    const caption = screen.getByText("Positions by instrument, 2 rows, across all accounts");
    expect(caption.tagName).toBe("CAPTION");
    expect(caption.className).toBe("visually-hidden");
    expect(caption.closest("table")?.className).toContain("position-table");
  });

  it("captions the by-account positions table with the selected account and its row count", async () => {
    await renderPortfolio(
      report({
        positions: [position({ accounts: [accountPosition()] })],
        cash_by_account: [accountCash()],
        accounts: [accountSummary()],
      }),
    );
    fireEvent.click(screen.getByRole("tab", { name: "By account" }));
    fireEvent.click(screen.getByRole("tab", { name: /Robinhood Taxable/ }));

    const caption = screen.getByText("Robinhood Taxable — Positions, 1 rows");
    expect(caption.tagName).toBe("CAPTION");
    expect(caption.className).toBe("visually-hidden");
  });

  it("captions the by-tax-treatment group tables with the group name and row count", async () => {
    await renderPortfolio(
      report({
        positions: [position({ accounts: [accountPosition()] })],
        cash_by_account: [accountCash()],
        accounts: [accountSummary()],
      }),
    );
    fireEvent.click(screen.getByRole("tab", { name: "By tax treatment" }));

    const caption = screen.getByText("Taxable — Positions, 1 rows");
    expect(caption.tagName).toBe("CAPTION");
  });

  it("captions the Closed tab's table with the closed-account row count and gives it a scroll-region role", async () => {
    await renderPortfolio(
      report({
        positions: [position({ accounts: [accountPosition()] })],
        cash_by_account: [accountCash()],
        accounts: [
          accountSummary(),
          accountSummary({
            account_id: "rh-roth",
            label: "Robinhood Roth",
            broker: "Robinhood",
            tax_treatment: "roth_ira",
            status: "closed",
            position_count: 0,
          }),
        ],
      }),
    );
    fireEvent.click(screen.getByRole("tab", { name: "By account" }));
    fireEvent.click(screen.getByRole("tab", { name: "Closed (1)" }));

    const caption = screen.getByText("Closed accounts, 1 rows");
    expect(caption.tagName).toBe("CAPTION");
    // A11Y-03: not wrapped in the shared `ScrollRegion`, so the table-wrap div itself carries the
    // scrollable-region role, an accessible name and a keyboard tab stop.
    const wrap = caption.closest("table")?.parentElement as HTMLElement;
    expect(wrap.className).toContain("table-wrap");
    expect(wrap.getAttribute("role")).toBe("region");
    expect(wrap.getAttribute("aria-label")).toBe("Closed accounts");
    expect(wrap.getAttribute("tabIndex")).toBe("0");
  });
});

describe("day-change and unrealized-percent columns", () => {
  it("renders signed values with positive/negative tone", async () => {
    await renderPortfolio(
      report({
        positions: [
          position({
            instrument_id: "i-up",
            symbol: "UP",
            previous_close: "24.00",
            day_change: "100.00",
            day_change_pct: 0.0833,
            unrealized: "95.00",
            unrealized_pct: 0.0788,
          }),
          position({
            instrument_id: "i-down",
            symbol: "DOWN",
            price: "20.00",
            market_value: "1000.00",
            previous_close: "22.00",
            day_change: "-100.00",
            day_change_pct: -0.0909,
            unrealized: "-50.00",
            unrealized_pct: -0.04,
          }),
        ],
      }),
    );

    const upRow = screen.getByText("UP").closest("tr") as HTMLElement;
    const upDayChange = within(upRow).getByText("+$100.00");
    expect(upDayChange.className).toContain("pos");
    expect(within(upRow).getByText("+8.3%")).toBeTruthy();

    const downRow = screen.getByText("DOWN").closest("tr") as HTMLElement;
    const downDayChange = within(downRow).getByText("-$100.00");
    expect(downDayChange.className).toContain("neg");
    expect(within(downRow).getByText("-9.1%")).toBeTruthy();
    expect(within(downRow).getByText("-4.0%")).toBeTruthy();
  });
});

describe("allocation pie", () => {
  it("swaps between ticker and sector slices when the mode toggle is clicked", async () => {
    const soxl = accountPosition({ account_id: "rh-taxable" });
    const nvda = accountPosition({ account_id: "rh-taxable" });
    await renderPortfolio(
      report({
        positions: [
          position({ instrument_id: "i-soxl", symbol: "SOXL", sector: "SEMI", accounts: [soxl] }),
          position({
            instrument_id: "i-nvda",
            symbol: "NVDA",
            sector: "SEMI",
            price: "10.00",
            market_value: "500.00",
            unrealized: "50.00",
            accounts: [nvda],
          }),
        ],
        cash_by_account: [accountCash()],
        accounts: [accountSummary()],
      }),
    );

    fireEvent.click(screen.getByRole("tab", { name: "By account" }));

    const legend = () => document.querySelector(".alloc-pie-legend") as HTMLElement;

    // Ticker mode (default): both symbols are separate legend rows.
    expect(within(legend()).getByText("SOXL")).toBeTruthy();
    expect(within(legend()).getByText("NVDA")).toBeTruthy();

    fireEvent.click(screen.getByRole("tab", { name: "By sector" }));

    // Sector mode: both roll up into one "SEMI" slice; the per-ticker legend rows are gone.
    expect(within(legend()).getByText("SEMI")).toBeTruthy();
    expect(within(legend()).queryByText("NVDA")).toBeNull();
  });
});

describe("positions table filter and sort", () => {
  it("narrows rows by the symbol filter and reorders via a sort header", async () => {
    await renderPortfolio(
      report({
        positions: [
          position({ instrument_id: "i-soxl", symbol: "SOXL", cost_basis: "5000.00" }),
          position({
            instrument_id: "i-nvda",
            symbol: "NVDA",
            cost_basis: "100.00",
            price: "10.00",
            market_value: "5000.00",
            unrealized: "4900.00",
          }),
        ],
      }),
    );

    // Both rows present initially.
    expect(screen.getByText("SOXL")).toBeTruthy();
    expect(screen.getByText("NVDA")).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText("Filter symbol"), { target: { value: "nvda" } });
    expect(screen.queryByText("SOXL")).toBeNull();
    expect(screen.getByText("NVDA")).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText("Filter symbol"), { target: { value: "" } });
    expect(screen.getByText("SOXL")).toBeTruthy();

    // Default sort is market value descending: NVDA ($5,000) precedes SOXL ($1,300).
    let rows = document.querySelectorAll(".position-table tbody tr");
    expect(rows[0]?.textContent).toContain("NVDA");

    // Clicking a fresh column's header sorts by that column at ITS OWN default direction
    // (descending for a money column) -- cost basis: SOXL ($5,000) now precedes NVDA ($100).
    fireEvent.click(screen.getByRole("button", { name: /Cost basis/ }));
    rows = document.querySelectorAll(".position-table tbody tr");
    expect(rows[0]?.textContent).toContain("SOXL");
  });
});

describe("by-tax-treatment view", () => {
  function switchToTaxView() {
    fireEvent.click(screen.getByRole("tab", { name: "By tax treatment" }));
  }

  it("groups positions into exactly Taxable and Retirement (IRA)", async () => {
    await renderPortfolio(
      report({
        positions: [position({ accounts: [accountPosition({ account_id: "rh-taxable" })] })],
        cash_by_account: [accountCash({ account_id: "rh-taxable", tax_treatment: "taxable" })],
      }),
    );

    switchToTaxView();

    expect(screen.getByRole("heading", { level: 2, name: "Taxable" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "Retirement (IRA)" })).toBeTruthy();
  });

  it("puts a retirement-held position only in the retirement group, with its own share", async () => {
    const rothSlice = accountPosition({
      account_id: "wb-roth",
      account_label: "Webull Roth",
      broker: "Webull",
      quantity: "20",
      cost_basis: "400.00",
    });
    await renderPortfolio(
      report({
        positions: [
          position({
            instrument_id: "i-soxl",
            symbol: "SOXL",
            price: "26.00",
            accounts: [rothSlice],
          }),
        ],
        cash_by_account: [
          accountCash({ account_id: "wb-roth", account_label: "Webull Roth", broker: "Webull", tax_treatment: "roth_ira" }),
        ],
      }),
    );

    switchToTaxView();

    const taxable = screen.getByRole("heading", { level: 2, name: "Taxable" }).closest(".account-section") as HTMLElement;
    const retirement = screen
      .getByRole("heading", { level: 2, name: "Retirement (IRA)" })
      .closest(".account-section") as HTMLElement;

    expect(within(taxable).queryByText("SOXL")).toBeNull();
    // The row's own market-value cell is scoped via its <tr> rather than matched against the whole
    // section, because with a single row the group's subtotal tile renders the identical figure --
    // matching against the section would find both and the assertion would be ambiguous about which
    // one it actually proved.
    const soxlRow = within(retirement).getByText("SOXL").closest("tr") as HTMLElement;
    expect(
      within(soxlRow).getByText(formatMoney(multiplyMoneyByQuantity("26.00", "20"))),
    ).toBeTruthy();
  });

  it("splits one instrument across a taxable and a retirement account into both groups, each with only its own share", async () => {
    const taxableSlice = accountPosition({
      account_id: "rh-taxable",
      account_label: "Robinhood Taxable",
      broker: "Robinhood",
      quantity: "30",
      cost_basis: "700.00",
    });
    const rothSlice = accountPosition({
      account_id: "wb-roth",
      account_label: "Webull Roth",
      broker: "Webull",
      quantity: "20",
      cost_basis: "400.00",
    });
    await renderPortfolio(
      report({
        positions: [
          position({
            instrument_id: "i-soxl",
            symbol: "SOXL",
            quantity: "50",
            price: "26.00",
            accounts: [taxableSlice, rothSlice],
          }),
        ],
        cash_by_account: [
          accountCash({ account_id: "rh-taxable", account_label: "Robinhood Taxable", broker: "Robinhood", tax_treatment: "taxable" }),
          accountCash({ account_id: "wb-roth", account_label: "Webull Roth", broker: "Webull", tax_treatment: "roth_ira" }),
        ],
      }),
    );

    switchToTaxView();

    const taxable = screen.getByRole("heading", { level: 2, name: "Taxable" }).closest(".account-section") as HTMLElement;
    const retirement = screen
      .getByRole("heading", { level: 2, name: "Retirement (IRA)" })
      .closest(".account-section") as HTMLElement;

    // Both groups show SOXL -- never once with the whole 50-share quantity.
    expect(within(taxable).getByText("SOXL")).toBeTruthy();
    expect(within(retirement).getByText("SOXL")).toBeTruthy();

    const taxableMarketValue = multiplyMoneyByQuantity("26.00", "30");
    const retirementMarketValue = multiplyMoneyByQuantity("26.00", "20");
    expect(taxableMarketValue).toBe("780.00");
    expect(retirementMarketValue).toBe("520.00");
    // Scoped to each row's own <tr>, not the whole section -- with one row per group the subtotal
    // tile renders the same figure as the row, so matching against the section is ambiguous.
    const taxableRow = within(taxable).getByText("SOXL").closest("tr") as HTMLElement;
    const retirementRow = within(retirement).getByText("SOXL").closest("tr") as HTMLElement;
    expect(within(taxableRow).getByText(formatMoney(taxableMarketValue))).toBeTruthy();
    expect(within(retirementRow).getByText(formatMoney(retirementMarketValue))).toBeTruthy();
    // Neither row shows the combined 50-share quantity.
    expect(within(taxableRow).queryByText("50")).toBeNull();
    expect(within(retirementRow).queryByText("50")).toBeNull();
  });

  it("sums each group's subtotals exactly from decimal strings, across two accounts in the same group", async () => {
    const rothSlice = accountPosition({
      account_id: "wb-roth",
      account_label: "Webull Roth",
      broker: "Webull",
      quantity: "20",
      cost_basis: "400.00",
    });
    const traditionalSlice = accountPosition({
      account_id: "rh-trad-ira",
      account_label: "Robinhood Traditional IRA",
      broker: "Robinhood",
      quantity: "10",
      cost_basis: "50.00",
    });
    await renderPortfolio(
      report({
        positions: [
          position({
            instrument_id: "i-soxl",
            symbol: "SOXL",
            price: "26.00",
            accounts: [rothSlice],
          }),
          position({
            instrument_id: "i-nvda",
            symbol: "NVDA",
            price: "10.00",
            market_value: "100.00",
            unrealized: "50.00",
            accounts: [traditionalSlice],
          }),
        ],
        cash_by_account: [
          accountCash({ account_id: "wb-roth", account_label: "Webull Roth", broker: "Webull", tax_treatment: "roth_ira" }),
          accountCash({
            account_id: "rh-trad-ira",
            account_label: "Robinhood Traditional IRA",
            broker: "Robinhood",
            tax_treatment: "traditional_ira",
          }),
        ],
      }),
    );

    switchToTaxView();

    const expectedMarketValue = sumMoney([
      multiplyMoneyByQuantity("26.00", "20"),
      multiplyMoneyByQuantity("10.00", "10"),
    ]);
    const expectedCostBasis = sumMoney(["400.00", "50.00"]);
    const expectedUnrealized = subtractMoney(expectedMarketValue, expectedCostBasis);
    expect(expectedMarketValue).toBe("620.00");
    expect(expectedUnrealized).toBe("170.00");

    const retirement = screen
      .getByRole("heading", { level: 2, name: "Retirement (IRA)" })
      .closest(".account-section") as HTMLElement;
    const scoped = within(retirement);
    expect(scoped.getByText(formatMoney(expectedCostBasis))).toBeTruthy();
    expect(scoped.getByText(formatMoney(expectedMarketValue))).toBeTruthy();
    expect(scoped.getByText(`+${formatMoney(expectedUnrealized)}`)).toBeTruthy();
    // Two retirement accounts, both counted in the group's account count. Checked via the heading's
    // own subtitle span rather than `getByText`, since the cash tile's hint renders the identical
    // "2 accounts" text elsewhere in the same section.
    expect(retirement.querySelector(".account-broker")?.textContent).toContain("2 accounts");
  });

  it("states the tax-boundary rationale on screen, not just in a code comment", async () => {
    await renderPortfolio(report());
    switchToTaxView();
    expect(document.body.textContent).toMatch(/aren't taxed/);
  });
});

describe("tax-treatment scope control", () => {
  /**
   * The scope control above the two tax groups (task: add a taxable/non-taxable + per-account SCOPE
   * control with its own allocation pie). Its own URL key, `scope` (owned by `Portfolio.tsx`'s
   * `useUrlState("scope", "all", ...)` call), independent of `view` -- clicking a scope tab writes
   * `?scope=`, a deep link with `?scope=` already set opens straight into that tab, and writing back
   * to the default ("all") removes the key rather than pinning `?scope=all` forever, mirroring the
   * account rail's own URL-state contract pinned in `describe("account rail: URL state")` above.
   */
  function switchToTaxView() {
    fireEvent.click(screen.getByRole("tab", { name: "By tax treatment" }));
  }

  function twoAccountReport() {
    const taxableSlice = accountPosition({ account_id: "rh-taxable", account_label: "Robinhood Taxable", broker: "Robinhood" });
    const rothSlice = accountPosition({
      account_id: "wb-roth",
      account_label: "Webull Roth",
      broker: "Webull",
      quantity: "20",
      cost_basis: "400.00",
    });
    return report({
      positions: [
        position({ instrument_id: "i-soxl", symbol: "SOXL", price: "26.00", accounts: [taxableSlice] }),
        position({
          instrument_id: "i-nvda",
          symbol: "NVDA",
          price: "10.00",
          market_value: "500.00",
          unrealized: "50.00",
          accounts: [rothSlice],
        }),
      ],
      cash_by_account: [
        accountCash({ account_id: "rh-taxable", account_label: "Robinhood Taxable", broker: "Robinhood", tax_treatment: "taxable" }),
        accountCash({ account_id: "wb-roth", account_label: "Webull Roth", broker: "Webull", tax_treatment: "roth_ira" }),
      ],
      accounts: [
        accountSummary({ account_id: "rh-taxable", label: "Robinhood Taxable", broker: "Robinhood", tax_treatment: "taxable" }),
        accountSummary({ account_id: "wb-roth", label: "Webull Roth", broker: "Webull", tax_treatment: "roth_ira" }),
      ],
    });
  }

  it("renders exactly the All / Taxable / Retirement scope tabs, defaulting to All", async () => {
    await renderPortfolio(twoAccountReport());
    switchToTaxView();

    const scopeRail = screen.getByRole("tablist", { name: "Scope" });
    const tabNames = within(scopeRail)
      .getAllByRole("tab")
      .map((tab) => tab.textContent ?? "");
    expect(tabNames).toEqual(["All", "Taxable", "Retirement (IRA)"]);
    expect(within(scopeRail).getByRole("tab", { name: "All" }).getAttribute("aria-selected")).toBe("true");
  });

  it("writes ?view=tax&scope=taxable to the URL when the Taxable scope tab is clicked", async () => {
    await renderPortfolioAt(twoAccountReport(), "/portfolio");
    switchToTaxView();

    const scopeRail = screen.getByRole("tablist", { name: "Scope" });
    fireEvent.click(within(scopeRail).getByRole("tab", { name: "Taxable" }));

    const probe = screen.getByTestId("location-probe");
    expect(probe.textContent).toContain("view=tax");
    expect(probe.textContent).toContain("scope=taxable");
  });

  it("writing back to the default All scope removes ?scope= from the URL rather than pinning it", async () => {
    await renderPortfolioAt(twoAccountReport(), "/portfolio");
    switchToTaxView();

    const scopeRail = screen.getByRole("tablist", { name: "Scope" });
    fireEvent.click(within(scopeRail).getByRole("tab", { name: "Taxable" }));
    fireEvent.click(within(scopeRail).getByRole("tab", { name: "All" }));

    const probe = screen.getByTestId("location-probe");
    expect(probe.textContent).not.toContain("scope=");
  });

  it("opens straight into the Taxable scope tab when ?view=tax&scope=taxable is already in the URL -- a reload survives", async () => {
    await renderPortfolioAt(twoAccountReport(), "/portfolio?view=tax&scope=taxable");

    const scopeRail = screen.getByRole("tablist", { name: "Scope" });
    expect(within(scopeRail).getByRole("tab", { name: "Taxable" }).getAttribute("aria-selected")).toBe("true");
    expect(within(scopeRail).getByRole("tab", { name: "All" }).getAttribute("aria-selected")).toBe("false");
  });

  it("falls back to the default All scope for a stale or hostile ?scope=, never throwing", async () => {
    await renderPortfolioAt(twoAccountReport(), "/portfolio?view=tax&scope=does-not-exist");

    const scopeRail = screen.getByRole("tablist", { name: "Scope" });
    expect(within(scopeRail).getByRole("tab", { name: "All" }).getAttribute("aria-selected")).toBe("true");
  });

  it("shows only the taxable account's own instrument in the pie legend once Taxable is selected, excluding the Roth's", async () => {
    await renderPortfolioAt(twoAccountReport(), "/portfolio?view=tax&scope=taxable");

    // Scoped to the scope control's own pie (the first `.alloc-pie-legend` in the DOM) -- each of
    // the two tax-group sections below has no pie of its own, so this is unambiguous.
    const legend = document.querySelector(".alloc-pie-legend") as HTMLElement;
    expect(within(legend).getByText("SOXL")).toBeTruthy();
    expect(within(legend).queryByText("NVDA")).toBeNull();
  });

  it("narrows further to one account via the account dropdown once a scope tab is selected", async () => {
    await renderPortfolioAt(twoAccountReport(), "/portfolio?view=tax");
    // "All" scope lists both accounts in the dropdown.
    const select = screen.getByLabelText("Account") as HTMLSelectElement;
    const optionLabels = Array.from(select.querySelectorAll("option")).map((o) => o.textContent);
    expect(optionLabels).toEqual(["All accounts", "Robinhood Taxable", "Webull Roth"]);

    fireEvent.change(select, { target: { value: "wb-roth" } });

    const legend = document.querySelector(".alloc-pie-legend") as HTMLElement;
    expect(within(legend).getByText("NVDA")).toBeTruthy();
    expect(within(legend).queryByText("SOXL")).toBeNull();
  });
});

describe("deferred wash-sale loss (By tax treatment view)", () => {
  /**
   * The task's definition of done: the taxable group's positions table shows a Deferred loss value
   * for a symbol the wash-sale tracker knows about, and a dash for one it does not -- and neither
   * the by-instrument table nor the by-account view grows this column at all.
   */
  function switchToTaxView() {
    fireEvent.click(screen.getByRole("tab", { name: "By tax treatment" }));
  }

  it("shows the tracker's deferred_disallowed for a flagged symbol and a dash for an unflagged one, in the taxable group only", async () => {
    washTrackerMock.mockResolvedValue(
      washSaleTracker({ symbols: [washSaleTrackerSymbol({ symbol: "SOXL", deferred_disallowed: "150.00" })] }),
    );
    await renderPortfolio(
      report({
        positions: [
          position({
            instrument_id: "i-soxl",
            symbol: "SOXL",
            accounts: [accountPosition({ account_id: "rh-taxable" })],
          }),
          position({
            instrument_id: "i-nvda",
            symbol: "NVDA",
            price: "10.00",
            market_value: "500.00",
            unrealized: "50.00",
            accounts: [accountPosition({ account_id: "rh-taxable" })],
          }),
        ],
        cash_by_account: [accountCash({ account_id: "rh-taxable", tax_treatment: "taxable" })],
      }),
    );

    switchToTaxView();
    // "Deferred loss" itself is ambiguous (it names both the tile and the sortable column header),
    // so this waits on the group heading instead -- the group only renders once the wash tracker
    // fetch (and the rest of the async render) has settled.
    await screen.findByRole("heading", { level: 2, name: "Taxable" });

    const taxable = screen.getByRole("heading", { level: 2, name: "Taxable" }).closest(".account-section") as HTMLElement;
    const soxlRow = within(taxable).getByText("SOXL").closest("tr") as HTMLElement;
    const nvdaRow = within(taxable).getByText("NVDA").closest("tr") as HTMLElement;
    // The Deferred loss cell is the LAST cell in the row -- scoped that way rather than by text,
    // since NVDA's row has more than one "—" cell (day-change and day-change % are also null for it).
    const lastCellOf = (row: HTMLElement): HTMLElement => {
      const cells = row.querySelectorAll("td");
      return cells[cells.length - 1] as HTMLElement;
    };
    expect(lastCellOf(soxlRow).textContent).toBe(formatMoney("150.00"));
    expect(lastCellOf(nvdaRow).textContent).toBe("—");

    // The by-instrument and by-account views never grow this column at all.
    fireEvent.click(screen.getByRole("tab", { name: "By instrument" }));
    expect(screen.queryByText("Deferred loss")).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "By account" }));
    expect(screen.queryByText("Deferred loss")).toBeNull();
  });

  it("sums deferred loss across the taxable group's own symbols into a tile, never fabricating a figure for a failed fetch", async () => {
    washTrackerMock.mockRejectedValue(new Error("network error"));
    await renderPortfolio(
      report({
        positions: [
          position({ instrument_id: "i-soxl", symbol: "SOXL", accounts: [accountPosition({ account_id: "rh-taxable" })] }),
        ],
        cash_by_account: [accountCash({ account_id: "rh-taxable", tax_treatment: "taxable" })],
      }),
    );

    switchToTaxView();

    const taxable = await screen.findByRole("heading", { level: 2, name: "Taxable" });
    const section = taxable.closest(".account-section") as HTMLElement;
    // A failed fetch withholds the tile's figure (a dash), never a fabricated $0.00, and names the
    // gap rather than pretending the column simply is not there.
    await within(section).findByText(/wash-sale data unavailable/i);
    // "Deferred loss" is ambiguous within the section (it also names the sortable column header,
    // which still renders even on a failed fetch -- every row just reads "—"), so this picks out
    // the one instance that sits inside a `.stat` tile.
    const deferredTile = within(section)
      .getAllByText("Deferred loss")
      .map((el) => el.closest(".stat"))
      .find((el): el is HTMLElement => el !== null);
    expect(deferredTile).toBeTruthy();
    expect(deferredTile?.textContent).toContain("—");
    expect(deferredTile?.textContent).not.toContain("$0.00");
  });

  it("shows a not-deductible caveat for the retirement group instead of a dash column", async () => {
    await renderPortfolio(
      report({
        positions: [
          position({
            instrument_id: "i-soxl",
            symbol: "SOXL",
            accounts: [accountPosition({ account_id: "wb-roth", account_label: "Webull Roth", broker: "Webull" })],
          }),
        ],
        cash_by_account: [
          accountCash({ account_id: "wb-roth", account_label: "Webull Roth", broker: "Webull", tax_treatment: "roth_ira" }),
        ],
      }),
    );

    switchToTaxView();

    const retirement = await screen.findByRole("heading", { level: 2, name: "Retirement (IRA)" });
    const section = retirement.closest(".account-section") as HTMLElement;
    expect(within(section).queryByText("Deferred loss")).toBeNull();
    expect(within(section).getByText(/aren't deductible/i)).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Declared cash
//
// Some accounts export order history with no cash rows at all, so a declared
// balance is the only reason an equity total exists at all. It carries a different risk from a
// derived one: it is a snapshot, correct on the day it was read and drifting silently from then on,
// and nothing in this application can notice that happening. These pin the consequences for the UI.
// ---------------------------------------------------------------------------

describe("declared cash", () => {
  it("renders the balance and never without the date it was read", async () => {
    await renderPortfolio(
      report({
        cash_by_account: [
          accountCash({
            verdict: "declared",
            balance: "11077.15",
            settled: null,
            unsettled: null,
            declared_as_of: "2026-08-14",
            declared_note: "Robinhood buying power",
            reason: "declared from the broker as of 2026-08-14, not derived from the export",
          }),
        ],
        cash_balance: "11077.15",
      }),
    );

    const body = document.body.textContent ?? "";
    expect(body).toContain("$11,077.15");
    // The date is the load-bearing half: undated, a month-old figure reads as a live one.
    expect(body).toContain("2026-08-14");
  });

  it("counts a declared account as having a balance rather than listing it as excluded", async () => {
    /**
     * `declared` is not `derived`, and the obvious wrong reading of that is "therefore missing".
     * A declaration supplies a real balance; the caveat that fires for a withheld one must not.
     */
    await renderPortfolio(
      report({
        cash_by_account: [
          accountCash({
            account_id: "wb-individual",
            account_label: "Webull Individual Margin",
            verdict: "declared",
            balance: "622.05",
            settled: null,
            unsettled: null,
            declared_as_of: "2026-08-14",
          }),
        ],
        cash_balance: "622.05",
        accounts_without_cash: [],
      }),
    );

    const body = document.body.textContent ?? "";
    expect(body).not.toContain("Cash is unavailable for");
    expect(body).toContain("$622.05");
  });

  it("still withholds and explains a balance that could not be derived or declared", async () => {
    await renderPortfolio(
      report({
        cash_by_account: [
          accountCash({
            verdict: "no_funding_rows",
            balance: null,
            settled: null,
            unsettled: null,
            reason: "webull exported order history only",
          }),
        ],
        cash_balance: null,
        settled_cash: null,
        unsettled_cash: null,
        unsettled_next_date: null,
        unsettled_full_date: null,
        total_equity: null,
        equity_is_complete: false,
        accounts_without_cash: ["rh-taxable"],
      }),
    );

    const body = document.body.textContent ?? "";
    expect(body).toContain("webull exported order history only");
    // The table only lists accounts that have a balance, so a withheld one must not appear in it.
    expect(screen.queryByRole("heading", { name: /cash by account/i })).toBeNull();
  });
});

describe("positions view note", () => {
  it("shows a short label and keeps every explanation one disclosure away", async () => {
    /**
     * A second density-UAT copy pass shortened the visible summary further, from a full sentence
     * down to a label ("By instrument = risk view"), and moved the wash-sale/concentration clause
     * that used to be the visible sentence into the InfoNote's disclosure alongside the by-account/
     * by-tax detail that was already there. `<details>` keeps its body in the DOM even collapsed, so
     * both the label and the restored detail are asserted directly rather than by simulating a click.
     */
    await renderPortfolio(report());

    const body = document.body.textContent ?? "";
    // The short label that survived the second copy pass.
    expect(body).toContain("By instrument = risk view");
    // The full sentence this replaced must not still be the visible summary.
    expect(body).not.toContain(
      '"By instrument" is the risk view: wash-sale rules and concentration apply across every account, not within one.',
    );
    // The wash-sale/concentration clause, and the by-account/by-tax detail, both restored behind
    // the disclosure.
    expect(body).toContain("Wash-sale rules and concentration apply across every account, not one");
    expect(body).toContain("shows which broker's cash and tax figures to trust");
    expect(body).toContain("splits taxable vs. retirement");
  });
});

describe("warnings box: collapsed by default, chart on demand", () => {
  function twoWarningsReport() {
    return report({
      warnings: [
        {
          kind: "missing_basis",
          account_id: "rh-taxable",
          broker: "Robinhood",
          symbol: "SOXL",
          trade_date: "2026-03-02",
          detail: "no basis row for lot",
        },
        {
          kind: "fees_unknown",
          account_id: "wb-margin",
          broker: "Webull",
          symbol: "NVDA",
          trade_date: "2026-03-05",
          detail: "no fee column in export",
        },
      ],
      warning_groups: [
        { kind: "missing_basis", account_id: "rh-taxable", broker: "Robinhood", count: 1, sample_detail: "no basis row for lot" },
        { kind: "fees_unknown", account_id: "wb-margin", broker: "Webull", count: 1, sample_detail: "no fee column in export" },
      ],
    });
  }

  it("shows only the headline count -- the chart and group table are not in the DOM -- until expanded", async () => {
    await renderPortfolio(twoWarningsReport());

    // The trimmed headline is visible immediately.
    expect(screen.getByText(/2 basis\/fee gaps the replay could not resolve/)).toBeTruthy();
    // Nothing else the expanded box would show is mounted yet.
    expect(document.querySelector(".wc-svg")).toBeNull();
    expect(document.querySelector(".warning-group-table")).toBeNull();
    expect(screen.queryByText("no basis row for lot")).toBeNull();

    // Queried by its aria-label rather than `{ expanded: false }` -- the by-instrument table's own
    // per-row "N accts" breakdown button also carries `aria-expanded={false}` by default, so matching
    // on that alone would be ambiguous whenever a position renders (which the default fixture does).
    const toggle = screen.getByRole("button", { name: "Show or hide the warnings breakdown and chart" });
    fireEvent.click(toggle);

    // Now the chart and the group table are both in the DOM.
    expect(document.querySelector(".wc-svg")).toBeTruthy();
    expect(document.querySelector(".warning-group-table")).toBeTruthy();
    expect(screen.getByText("no basis row for lot")).toBeTruthy();
  });

  it("collapses again on a second click", async () => {
    await renderPortfolio(twoWarningsReport());
    const toggle = screen.getByRole("button", { name: "Show or hide the warnings breakdown and chart" });
    fireEvent.click(toggle);
    expect(document.querySelector(".wc-svg")).toBeTruthy();

    fireEvent.click(toggle);
    expect(document.querySelector(".wc-svg")).toBeNull();
  });
});

describe("sector badge editor (double-click to reassign)", () => {
  it("double-clicking a sector badge in the positions table opens an editor whose vocabulary came from portfolioApi.sectors", async () => {
    sectorsMock.mockResolvedValue({ vocabulary: ["Semiconductors", "Software"], map: {} });
    await renderPortfolio(report({ positions: [position({ sector: "Semiconductors" })] }));

    // Located by its double-click hint rather than by text: the by-instrument table's own sector
    // filter dropdown also renders an `<option>Semiconductors</option>`, which collides with a plain
    // text query once the vocabulary includes the same label.
    const badge = await screen.findByTitle("Double-click to change sector");
    fireEvent.doubleClick(badge);

    // Named, not just role-queried: the by-instrument table's own sector filter is ALSO a
    // `combobox`, so an unscoped `getByRole("combobox")` would be ambiguous once opened.
    const select = screen.getByRole("combobox", { name: "Sector for SOXL" }) as HTMLSelectElement;
    const optionLabels = Array.from(select.querySelectorAll("option")).map((o) => o.textContent);
    expect(optionLabels).toEqual(["Semiconductors", "Software"]);
  });

  it("saving a new sector calls setSector and refreshes the report", async () => {
    sectorsMock.mockResolvedValue({ vocabulary: ["Semiconductors", "Software"], map: {} });
    setSectorMock.mockResolvedValue({ symbol: "SOXL", sector: "Software" });
    reportMock.mockResolvedValue(report({ positions: [position({ symbol: "SOXL", sector: "Semiconductors" })] }));

    render(
      <MemoryRouter>
        <Portfolio />
      </MemoryRouter>,
    );
    await screen.findByText(/Ledger as of|Positions as of/);

    // Located by its double-click hint rather than by text: the by-instrument table's own sector
    // filter dropdown also renders an `<option>Semiconductors</option>`, which collides with a plain
    // text query once the vocabulary includes the same label.
    const badge = await screen.findByTitle("Double-click to change sector");
    fireEvent.doubleClick(badge);
    const select = screen.getByRole("combobox", { name: "Sector for SOXL" }) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "Software" } });

    // Report re-fetch (triggered by `onChanged` -> `refresh()`) reflects the server's new sector.
    reportMock.mockResolvedValue(report({ positions: [position({ symbol: "SOXL", sector: "Software" })] }));
    fireEvent.keyDown(select, { key: "Enter" });

    await vi.waitFor(() => {
      expect(setSectorMock).toHaveBeenCalledWith("SOXL", "Software");
    });
    // `reportMock` was called again -- once at mount, once by `refresh()`.
    await vi.waitFor(() => {
      expect(reportMock.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
  });
});

describe("cross-links (UX refactor 3.3)", () => {
  it("links a basis-uncertain row (by-instrument, the default view) to the Tax page's Disposals tab", async () => {
    await renderPortfolio(report({ positions: [position({ basis_uncertain: true })] }));

    const link = screen.getByRole("link", { name: "see disposals" });
    expect(link.getAttribute("href")).toBe("/tax?tab=disposals");
  });

  it("does not render the Tax cross-link for a row with an established basis", async () => {
    await renderPortfolio(report({ positions: [position({ basis_uncertain: false })] }));
    expect(screen.queryByRole("link", { name: "see disposals" })).toBeNull();
  });

  it("links a basis-uncertain row in the by-account view to the same Tax tab", async () => {
    const flaggedSlice = accountPosition({ basis_uncertain: true });
    await renderPortfolio(
      report({
        positions: [position({ basis_uncertain: true, accounts: [flaggedSlice] })],
        cash_by_account: [accountCash()],
        accounts: [accountSummary()],
      }),
    );

    // `switchToAccountView` is redeclared per-describe-block above rather than hoisted to module
    // scope (see those blocks' own definitions) -- inlined here rather than adding a fourth copy.
    fireEvent.click(screen.getByRole("tab", { name: "By account" }));
    const link = screen.getByRole("link", { name: "see disposals" });
    expect(link.getAttribute("href")).toBe("/tax?tab=disposals");
  });
});

describe("the loading state", () => {
  it("draws a shaped skeleton, not a one-line placeholder, while the report is in flight", async () => {
    // Many seconds on a large book: every holding is reconstructed from transaction history before a
    // single row can render. A collapsed one-line panel for that long, then a snap open to a caveat
    // strip, four totals and a positions table, reads as the page jumping rather than arriving.
    reportMock.mockReturnValue(new Promise(() => {}));
    const { container } = render(
      <MemoryRouter>
        <Portfolio />
      </MemoryRouter>,
    );

    expect(container.querySelector(".skeleton-rows")).toBeTruthy();
    // The half a bare spinner drops: `Skeleton` announces itself politely, so a screen reader is
    // told the page is working without having its in-progress speech cut off.
    const status = await screen.findByRole("status");
    expect(status.getAttribute("aria-live")).toBe("polite");
    expect(status.textContent).toContain("Account");
  });
});

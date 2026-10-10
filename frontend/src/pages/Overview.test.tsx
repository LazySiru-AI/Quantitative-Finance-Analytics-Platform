/**
 * The Overview page's honesty rules, at render level -- the same discipline `Portfolio.test.tsx`
 * and `PaperDesk.test.tsx` pin for their own pages, applied to the landing page that summarises all
 * four of them at once.
 *
 * What these tests pin, matching the task brief's definition of done:
 *  - the loaded state renders all four sections (portfolio, market, reference desk, attention);
 *  - a failing macro fetch still renders the portfolio section -- the four fetches fail
 *    independently and one going down must not blank the rest of the page;
 *  - a non-empty `unpriced_symbols` produces a visible "(partial)" caveat on the affected tile,
 *    never a silently-short total;
 *  - `equity_is_complete: false` is disclosed on the equity tile, never hidden behind a number that
 *    looks whole;
 *  - the "nothing needs attention" case renders an explicit message, not an empty box;
 *  - the three paper-desk books (savings/trading/roth) render as separate cards and their desks'
 *    returns are never summed into one figure -- no book-level or desk-level total appears anywhere
 *    that was not already on the wire.
 *
 * Since the page moved onto the `Card`/`CardGrid` primitive, three more:
 *  - every card in a row is a direct child of a `.card-grid` (jsdom cannot measure height, so the
 *    structure that produces equal height is what gets pinned -- see the "card rows" block);
 *  - the Attention card holds exactly one scroll region, findings and "could not be checked" notes
 *    in the same list, and a book card's head, benchmark and table-wrap stay outside its body;
 *  - the outbound links point at the merged pages (`/symbol`, `/filers?tab=consensus`), never at the
 *    `/ticker`//`/consensus` redirect shims, and the `/manager` bridge is owner-only.
 *
 * All four API modules are stubbed at the module boundary (`@/api/portfolio`, `@/api/macro`,
 * `@/api/paperdesk`, `@/api/washsales`), the same seam `Portfolio.test.tsx`/`PaperDesk.test.tsx`/
 * `WashSales.test.tsx` stub, so these tests are about rendering, not about JSON parsing. `Overview`
 * also renders `MacroKeyIndicators`, which embeds `MacroSeriesChart` per tile; that component fetches
 * its own series history via `macroApi.series`, which is left unstubbed here on purpose (mirroring
 * that nothing in this test suite renders `MacroSeriesChart` directly against a real canvas) -- the
 * chart tile degrades to its own internal error state instead of crashing the page, and nothing
 * these tests assert on depends on it succeeding.
 */
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "@/api/client";
import type { AuthValue } from "@/auth";
import type { PortfolioReport, Position } from "@/api/portfolio";
import type { FearGreed, MacroSnapshot, MacroTile } from "@/api/macro";
import type { Book, Desk, Funding, PaperDeskState } from "@/api/paperdesk";
import type { WashSaleTracker, WashSaleTrackerSymbol } from "@/api/washsales";
import { daysUntil, type CalendarEventItem, type EventCalendar } from "@/api/calendar";
import type { LoopConfig, LoopStatus } from "@/api/evolution";
import type { TradingAgentsConfig } from "@/api/tradingagents";
import type { RoundSummary, RoundsResponse } from "@/api/competition";
import type { GainsReport, Form8949Report, TaxReport } from "@/api/tax";
import type { TransactionPage, TransactionRow } from "@/api/transactions";
import type { ConsensusResponse, ConsensusRow } from "@/api/consensus";

const portfolioReportMock = vi.fn<() => Promise<PortfolioReport>>();
const macroSnapshotMock = vi.fn<() => Promise<MacroSnapshot>>();
const deskStateMock = vi.fn<() => Promise<PaperDeskState>>();
const washTrackerMock = vi.fn<() => Promise<WashSaleTracker>>();
const calendarUpcomingMock = vi.fn<() => Promise<EventCalendar>>();
const evolutionLoopMock = vi.fn<() => Promise<LoopStatus>>();
const agentConfigMock = vi.fn<() => Promise<TradingAgentsConfig>>();
const competitionRoundsMock = vi.fn<() => Promise<RoundsResponse>>();
const taxReportMock = vi.fn<() => Promise<TaxReport>>();
const transactionsListMock = vi.fn<() => Promise<TransactionPage>>();
const consensusGetMock = vi.fn<() => Promise<ConsensusResponse>>();

vi.mock("@/api/portfolio", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/portfolio")>();
  return {
    ...actual,
    portfolioApi: { ...actual.portfolioApi, report: () => portfolioReportMock() },
  };
});

vi.mock("@/api/macro", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/macro")>();
  return {
    ...actual,
    macroApi: { ...actual.macroApi, snapshot: () => macroSnapshotMock() },
  };
});

vi.mock("@/api/paperdesk", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/paperdesk")>();
  return {
    ...actual,
    paperdeskApi: { ...actual.paperdeskApi, state: () => deskStateMock() },
  };
});

vi.mock("@/api/washsales", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/washsales")>();
  return {
    ...actual,
    washSalesApi: { ...actual.washSalesApi, tracker: () => washTrackerMock() },
  };
});

vi.mock("@/api/calendar", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/calendar")>();
  return {
    ...actual,
    calendarApi: { ...actual.calendarApi, upcoming: () => calendarUpcomingMock() },
  };
});

vi.mock("@/api/evolution", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/evolution")>();
  return {
    ...actual,
    evolutionApi: { ...actual.evolutionApi, loop: () => evolutionLoopMock() },
  };
});

vi.mock("@/api/tradingagents", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/tradingagents")>();
  return {
    ...actual,
    tradingAgentsApi: { ...actual.tradingAgentsApi, config: () => agentConfigMock() },
  };
});

vi.mock("@/api/competition", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/competition")>();
  return {
    ...actual,
    competitionApi: { ...actual.competitionApi, rounds: () => competitionRoundsMock() },
  };
});

vi.mock("@/api/tax", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/tax")>();
  return {
    ...actual,
    taxApi: { ...actual.taxApi, report: () => taxReportMock() },
  };
});

vi.mock("@/api/transactions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/transactions")>();
  return {
    ...actual,
    transactionsApi: { ...actual.transactionsApi, list: () => transactionsListMock() },
  };
});

vi.mock("@/api/consensus", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/consensus")>();
  return {
    ...actual,
    consensusApi: { ...actual.consensusApi, get: () => consensusGetMock() },
  };
});

// `Overview` calls `useAuth()` directly now (see its own comment on the four owner-only fetches),
// and this file renders `<Overview />` with no real `AuthProvider` above it. Mocked the same way
// `App.test.tsx`/`Data.test.tsx` mock `@/auth` -- `mockUseAuth`, owner by default -- so every
// existing test in this file (all written before roles existed) keeps exercising the owner path
// unchanged; the "member view" describe block below is what points it at `MEMBER_AUTH`.
const OWNER_AUTH: AuthValue = {
  status: "authed",
  username: "owner",
  authEnabled: true,
  role: "owner",
  isOwner: true,
  refresh: async () => {},
  onSignedIn: () => {},
  signOut: async () => {},
};
const MEMBER_AUTH: AuthValue = { ...OWNER_AUTH, username: "member", role: "member", isOwner: false };
const mockUseAuth = vi.fn<() => AuthValue>(() => OWNER_AUTH);

vi.mock("@/auth", () => ({ useAuth: () => mockUseAuth() }));

const { default: Overview } = await import("@/pages/Overview");

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function position(overrides: Partial<Position> = {}): Position {
  return {
    instrument_id: "i-nvda",
    symbol: "NVDA",
    quantity: "10",
    cost_basis: "1500.00",
    basis_per_share: "150.00",
    price: "191.40",
    price_as_of: "2026-08-21",
    market_value: "1914.00",
    unrealized: "414.00",
    unrealized_pct: 0.276,
    weight_pct: 1.0,
    sector: "SEMI",
    previous_close: "189.00",
    day_change: "24.00",
    day_change_pct: 0.0127,
    short_term_quantity: "10",
    long_term_quantity: "0",
    earliest_acquired: "2026-01-05",
    latest_acquired: "2026-01-05",
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
    unsettled_next_date: null,
    unsettled_full_date: null,
    as_of: "2026-08-21",
    generated_at: "2026-08-21T21:00:00Z",
    positions: [position()],
    total_cost_basis: "1500.00",
    total_market_value: "1914.00",
    total_unrealized: "414.00",
    total_unrealized_pct: 0.276,
    priced_position_count: 1,
    unpriced_symbols: [],
    cash_balance: "3000.00",
    settled_cash: "3000.00",
    unsettled_cash: "0",
    total_equity: "4914.00",
    equity_is_complete: true,
    accounts_without_cash: [],
    cash_by_account: [],
    positions_with_uncertain_basis: 0,
    positions_with_unknown_fees: 0,
    warnings: [],
    warning_groups: [],
    accounts: [],
    open_account_count: 0,
    total_day_change: "24.00",
    total_day_change_pct: 0.0127,
    excluded_closed_positions: 0,
    excluded_closed_symbols: [],
    ...overrides,
  };
}

function macroTile(overrides: Partial<MacroTile> = {}): MacroTile {
  return {
    key: "us10y",
    label: "US 10-Year Treasury",
    value: 4.12,
    unit: "percent",
    as_of: "2026-08-21",
    change: { mode: "basis_points", day: 1, week: -3, month: 8, ytd: 20 },
    spark: [],
    source: "fred",
    warnings: [],
    ...overrides,
  };
}

function fearGreed(overrides: Partial<FearGreed> = {}): FearGreed {
  return {
    score: 62,
    rating: "greed",
    source: "cnn",
    as_of: "2026-08-21",
    components: [],
    previous_close: 60,
    previous_week: 55,
    previous_month: 50,
    previous_year: 45,
    history: [],
    warnings: [],
    ...overrides,
  };
}

function macroSnapshot(overrides: Partial<MacroSnapshot> = {}): MacroSnapshot {
  return {
    generated_at: "2026-08-21T21:00:00Z",
    rates: [macroTile()],
    oil: [macroTile({ key: "wti", label: "WTI Crude", unit: "usd", value: 70.1 })],
    fear_greed: fearGreed(),
    movers: [],
    warnings: [],
    ...overrides,
  };
}

function funding(overrides: Partial<Funding> = {}): Funding {
  return {
    purpose: "trading",
    shape: "lump_sum",
    seed: "50000",
    contribution: "0",
    horizon_years_min: null,
    horizon_years_max: null,
    tax_treatment: "taxable",
    ...overrides,
  };
}

function desk(overrides: Partial<Desk> = {}): Desk {
  return {
    agent_id: "B-momentum",
    display_name: "B-momentum",
    discipline: "momentum",
    thesis: "Ride established uptrends.",
    kind: "rules",
    universe: ["NVDA", "AMD"],
    entry: "ema(20) crosses_above ema(50)",
    exit: "close crosses_below sma(200)",
    rank_by: null,
    stop_loss_pct: "0.12",
    take_profit_pct: null,
    max_hold_days: 180,
    max_positions: 6,
    position_pct: "0.15",
    ladder: null,
    starting_equity: "100000.00",
    cash: "63000.00",
    positions_value: "38200.00",
    equity: "101200.00",
    total_return: "0.0120",
    excess_return: "-0.0003",
    max_drawdown: "0.0210",
    capital_exposure: 0.37,
    realised_pnl: "400.00",
    unrealised_pnl: "800.00",
    open_positions: 2,
    slots_free: 4,
    holdings: [],
    trades: [],
    decisions: [],
    signals: [],
    rejections: [],
    rejection_count: 0,
    live_fills: [],
    live_rejections: [],
    live_as_of: null,
    ...overrides,
  };
}

function book(overrides: Partial<Book> = {}): Book {
  return {
    purpose: "trading",
    label: "Trading",
    funding: funding(),
    starting_cash: "100000.00",
    benchmark: { symbol: "SPY", return_pct: "0.0123" },
    notes: [],
    desks: [desk()],
    ...overrides,
  };
}

function deskState(overrides: Partial<PaperDeskState> = {}): PaperDeskState {
  return {
    inception: "2026-08-01",
    inception_default: "2026-08-01",
    inception_is_custom: false,
    design_cutoff: "2026-02-13",
    in_sample_sessions: 0,
    earliest_inception: "1993-01-29",
    latest_inception: "2026-08-21",
    as_of: "2026-08-21",
    latest_bar: "2026-08-21",
    stale_days: 0,
    first_session: "2026-08-03",
    sessions: 12,
    notes: [],
    books: [
      book({ purpose: "savings", label: "Savings", desks: [desk({ agent_id: "S-core", display_name: "S-core" })] }),
      book({ purpose: "trading", label: "Trading", desks: [desk({ agent_id: "B-momentum", display_name: "B-momentum" })] }),
      book({ purpose: "roth", label: "Roth IRA", desks: [desk({ agent_id: "R-growth", display_name: "R-growth" })] }),
    ],
    ...overrides,
  };
}

function washTracker(overrides: Partial<WashSaleTracker> = {}): WashSaleTracker {
  return {
    as_of: "2026-08-21",
    generated_at: "2026-08-21T21:00:00Z",
    total_deferred: "0.00",
    total_permanently_disallowed: "0.00",
    open_window_count: 0,
    symbol_count: 0,
    symbols: [],
    ...overrides,
  };
}

function washSymbol(overrides: Partial<WashSaleTrackerSymbol> = {}): WashSaleTrackerSymbol {
  return {
    symbol: "NVDA",
    deferred_disallowed: "100.00",
    permanently_disallowed: "0.00",
    event_count: 1,
    loss_sale_count: 1,
    first_sale_date: "2026-08-01",
    last_sale_date: "2026-08-30",
    repurchase_safe_on: "2026-09-30",
    days_until_safe: 20,
    window_is_open: true,
    accounts: ["rh-taxable"],
    sales: [],
    ...overrides,
  };
}

function calendarEvent(overrides: Partial<CalendarEventItem> = {}): CalendarEventItem {
  return {
    kind: "fomc",
    title: "FOMC Meeting",
    date: "2026-09-16",
    end_date: "2026-09-17",
    timing: "unknown",
    confidence: "confirmed",
    source: "federal_reserve",
    symbol: null,
    detail: null,
    ...overrides,
  };
}

function calendarFixture(overrides: Partial<EventCalendar> = {}): EventCalendar {
  return {
    generated_at: "2026-08-25T12:00:00Z",
    start: "2026-08-25",
    end: "2026-10-24",
    events: [calendarEvent()],
    holdings_total: 41,
    holdings_covered: 12,
    warnings: [],
    ...overrides,
  };
}

function loopConfig(overrides: Partial<LoopConfig> = {}): LoopConfig {
  return {
    purposes: ["trading"],
    population: 10,
    max_workers: 4,
    elite_count: 3,
    windows: ["gfc"],
    holdout_windows: [],
    max_generations: null,
    rank_by: "median",
    promotion_margin_pp: "0.02",
    promotion_consecutive: 3,
    promotion_max_shared_windows: null,
    seat_on_paper_desk: true,
    use_news: false,
    news_fraction: 0,
    seed: 1,
    cooldown_seconds: 60,
    goal: "",
    focus_symbols: [],
    avoid_symbols: [],
    ...overrides,
  };
}

function loopStatus(overrides: Partial<LoopStatus> = {}): LoopStatus {
  return {
    loop_id: "loop-1",
    state: "idle",
    phase: "idle",
    config: loopConfig(),
    generation: 0,
    completed_generations: 0,
    candidates_tested: 0,
    started_at: null,
    updated_at: null,
    stopped_at: null,
    current_round_id: null,
    current_job_id: null,
    current_purpose: null,
    best: null,
    promotions: [],
    history: [],
    log: [],
    error: null,
    ...overrides,
  };
}

function agentConfigFixture(overrides: Partial<TradingAgentsConfig> = {}): TradingAgentsConfig {
  return {
    analysts: [],
    default_debate_rounds: 1,
    default_risk_rounds: 1,
    max_rounds: 3,
    default_budget_usd: "5.00",
    default_model: "gpt",
    available_models: [{ id: "gpt", label: "GPT" }],
    agent_available: true,
    agent_reason: "",
    ...overrides,
  };
}

function roundSummary(overrides: Partial<RoundSummary> = {}): RoundSummary {
  return {
    round_id: "r5-2026-08",
    label: "R5",
    windows: ["gfc"],
    agents: 6,
    has_report: true,
    has_brief: true,
    has_results: true,
    has_selection: true,
    sequence: 5,
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

function transactionRow(overrides: Partial<TransactionRow> = {}): TransactionRow {
  return {
    txn_id: "t1",
    account_id: "rh-taxable",
    broker: "robinhood",
    action: "buy",
    trade_date: "2026-09-01",
    settle_date: "2026-09-03",
    executed_at: "2026-09-01T14:00:00Z",
    sequence: 1,
    symbol: "NVDA",
    instrument_id: "i-nvda",
    cusip: null,
    quantity: "10",
    price: "191.40",
    fees: "0.00",
    amount: "-1914.00",
    description: null,
    raw_code: null,
    import_id: "imp-1",
    source_row: 1,
    ...overrides,
  };
}

function transactionPage(overrides: Partial<TransactionPage> = {}): TransactionPage {
  return {
    transactions: [transactionRow()],
    total: 1103,
    limit: 1,
    offset: 0,
    has_more: true,
    as_of: "2026-09-05",
    earliest: "2020-01-01",
    total_bought: "0.00",
    total_sold: "0.00",
    net_cash_flow: "0.00",
    ...overrides,
  };
}

function consensusRow(overrides: Partial<ConsensusRow> = {}): ConsensusRow {
  return {
    cusip: "037833100",
    issuer: "Apple Inc",
    ticker: "AAPL",
    buyer_count: 4,
    seller_count: 0,
    net_funds: 4,
    total_weight_delta: "0.02",
    movers: [],
    ...overrides,
  };
}

function consensusResponse(overrides: Partial<ConsensusResponse> = {}): ConsensusResponse {
  return {
    generated_at: "2026-09-01T00:00:00Z",
    as_of: "2026-06-30",
    checked: ["ark", "berkshire"],
    unchecked: [],
    buys: [consensusRow()],
    sells: [
      consensusRow({ cusip: "999999999", issuer: "Foo Corp", ticker: "FOO", buyer_count: 0, seller_count: 3 }),
    ],
    ...overrides,
  };
}

function renderOverview() {
  return render(
    <MemoryRouter>
      <Overview />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mockUseAuth.mockImplementation(() => OWNER_AUTH);
  portfolioReportMock.mockReset();
  macroSnapshotMock.mockReset();
  deskStateMock.mockReset();
  washTrackerMock.mockReset();
  calendarUpcomingMock.mockReset();
  evolutionLoopMock.mockReset();
  agentConfigMock.mockReset();
  competitionRoundsMock.mockReset();
  taxReportMock.mockReset();
  transactionsListMock.mockReset();
  consensusGetMock.mockReset();
  // Sane defaults for the programme strip so tests that are not about it do not have to think about
  // it -- the same reasoning the other four fixtures above already follow.
  evolutionLoopMock.mockResolvedValue(loopStatus());
  agentConfigMock.mockResolvedValue(agentConfigFixture());
  competitionRoundsMock.mockResolvedValue({ rounds: [roundSummary()] });
  // Sane defaults for the three tiles added to make Overview the real front door -- same reasoning.
  taxReportMock.mockResolvedValue(taxReport());
  transactionsListMock.mockResolvedValue(transactionPage());
  consensusGetMock.mockResolvedValue(consensusResponse());
});

// ---------------------------------------------------------------------------

describe("loaded state", () => {
  it("renders all five sections", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();

    expect(await screen.findByRole("heading", { name: "Account" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Market context" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Reference desk" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Calendar" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Attention" })).toBeTruthy();

    // Portfolio headline figures.
    expect(screen.getByText("Total equity")).toBeTruthy();
    expect(screen.getByText("$4,914.00")).toBeTruthy();

    // Market context: MacroKeyIndicators + FearGreedGauge both compose in.
    expect(screen.getByText("Key indicators")).toBeTruthy();
    expect(screen.getByText("Fear & Greed")).toBeTruthy();

    // Reference desk: all three books present.
    expect(screen.getByText("Savings")).toBeTruthy();
    expect(screen.getByText("Trading")).toBeTruthy();
    expect(screen.getByText("Roth IRA")).toBeTruthy();

    // Calendar: the FOMC event from the default fixture, and its holdings denominator.
    expect(screen.getByText("FOMC Meeting")).toBeTruthy();
    expect(screen.getByText(/12 of 41 holdings/)).toBeTruthy();
  });

  it("links each section through to its full page", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();
    await screen.findByRole("heading", { name: "Account" });

    const links = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(links).toContain("/portfolio");
    expect(links).toContain("/macro");
    expect(links).toContain("/paper-desk");
    // The tiles/links added to make this page the real front door: Tax, Activity, Filer consensus,
    // and the two cross-links into sibling systems the page otherwise never reached (Strategy Lab,
    // Agent Desk).
    expect(links).toContain("/tax");
    expect(links).toContain("/activity");
    expect(links).toContain("/strategy");
    expect(links).toContain("/agents");
  });

  /**
   * Ticker→Symbol and Institutions/Consensus→Filers were merged, and `App.tsx` keeps the old paths
   * alive as `RedirectToSymbol`/`RedirectToFilers` shims so existing bookmarks still resolve. A shim
   * is for links this app no longer controls; a page that still writes one costs every reader a
   * redirect and keeps a dead name in circulation. These assert the destinations, and that the two
   * legacy paths are gone from this page entirely.
   */
  it("links at the merged pages, never at the legacy redirect shims", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();
    await screen.findByRole("heading", { name: "Account" });

    const links = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(links).toContain("/symbol");
    expect(links).toContain("/filers?tab=consensus");
    expect(links).not.toContain("/ticker");
    expect(links).not.toContain("/consensus");
  });
});

/**
 * The card rows. jsdom performs no layout, so equal height cannot be asserted here at all -- these
 * pin the structure that produces it (every card is a direct child of a `.card-grid`, so
 * `grid-auto-rows` governs its height) and the contract the primitive is for: one bounded, scrolling
 * body per card, with the head outside it.
 */
describe("card rows", () => {
  async function renderLoaded() {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());
    renderOverview();
    await screen.findByRole("heading", { name: "Account" });
  }

  function cardFor(headingName: string): HTMLElement {
    return screen.getByRole("heading", { name: headingName }).closest("section.card") as HTMLElement;
  }

  it("puts Tax, Activity, Attention and the three books in a CardGrid", async () => {
    await renderLoaded();

    for (const heading of ["Tax", "Activity", "Attention", "Savings", "Trading", "Roth IRA"]) {
      const card = cardFor(heading);
      expect(card, `no .card found for ${heading}`).toBeTruthy();
      // Direct child of the grid: `grid-auto-rows` sizes tracks, and a card one level down would sit
      // inside a track rather than being one.
      expect(card.parentElement?.classList.contains("card-grid"), `${heading} is not in a card-grid`).toBe(
        true,
      );
    }
  });

  /**
   * The Attention panel used to stack two `sm` scroll regions in one box -- findings in the first,
   * "could not be checked" notes in the second -- which gave a list that is usually three items long
   * two scrollbars, two tab stops, and two regions sharing one accessible name. One card, one region.
   */
  it("renders the attention list in exactly one scroll region", async () => {
    portfolioReportMock.mockResolvedValue(
      report({
        warnings: [
          {
            kind: "missing_basis",
            account_id: "rh-taxable",
            broker: "robinhood",
            symbol: "NVDA",
            trade_date: "2026-01-05",
            detail: "basis gap",
          },
        ],
      }),
    );
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    // A failed desk fetch is what produces an "unavailable" note alongside a real finding -- the
    // exact pair that used to need two regions.
    deskStateMock.mockRejectedValue(new ApiRequestError(503, "desk down"));
    washTrackerMock.mockResolvedValue(washTracker({ open_window_count: 2, symbol_count: 2 }));
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();
    await screen.findByText(/2 open wash-sale windows/);

    const attention = cardFor("Attention");
    expect(attention.querySelectorAll(".scroll-region")).toHaveLength(1);
    // Both kinds reached the one list.
    expect(within(attention).getByText(/2 open wash-sale windows/)).toBeTruthy();
    expect(within(attention).getByText(/1 portfolio warning/)).toBeTruthy();
    expect(within(attention).getByText(/Paper desk staleness could not be checked/)).toBeTruthy();
    expect(attention.querySelectorAll(".overview-attention-list")).toHaveLength(1);
  });

  /** The head is what must not scroll: the heading, the desk count and the link out all sit outside
   *  the body, which is the only bounded element in the card. */
  it("keeps each book card's head and benchmark outside its one scrolling body", async () => {
    await renderLoaded();

    const trading = screen.getByText("Trading").closest(".overview-book-card") as HTMLElement;
    expect(trading.querySelectorAll(".scroll-region")).toHaveLength(1);
    const body = trading.querySelector(".card-body") as HTMLElement;
    expect(within(body).queryByText("Trading")).toBeNull();
    expect(within(body).queryByText(/Benchmark/)).toBeNull();
    // The desk table is the body's own child: a `.table-wrap` between them would be a second
    // scrolling box, and the sticky `thead` would scroll away with the rows it labels.
    expect(body.querySelector(".table-wrap")).toBeNull();
    expect(body.querySelector("table.overview-desk-table")).toBeTruthy();
  });
});

describe("the Manager cross-link", () => {
  it("offers the owner the change feed that answers the question this card cannot", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();
    await screen.findByRole("heading", { name: "Attention" });

    const attention = screen
      .getByRole("heading", { name: "Attention" })
      .closest("section.card") as HTMLElement;
    const link = within(attention).getByText(/What changed since yesterday/).closest("a");
    expect(link?.getAttribute("href")).toBe("/manager");
  });

  it("does not offer it to a member, whose session would only get a 403", async () => {
    mockUseAuth.mockImplementation(() => MEMBER_AUTH);
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();
    await screen.findByText("Key indicators");

    expect(screen.queryByText(/What changed since yesterday/)).toBeNull();
    expect(screen.getAllByRole("link").map((a) => a.getAttribute("href"))).not.toContain("/manager");
  });
});

describe("the portfolio mark note", () => {
  /** A `YYYY-MM-DD` date `n` days before today, in UTC.
   *
   *  Derived from the clock rather than hardcoded because the day count under test is computed
   *  against the real "today". A fixed date like `"2026-08-21"` would read as 5 days behind on the
   *  day it was written and 40 a month later, silently crossing the warn threshold and turning a
   *  passing assertion into a failing one with nothing in the diff to explain it. Both this and
   *  `calendarDaysBehind` reduce to a UTC calendar day, so they cannot disagree about the boundary.
   */
  function isoDaysAgo(n: number): string {
    return new Date(Date.now() - n * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
  }

  function renderWithPricing(overrides: Partial<PortfolioReport>) {
    portfolioReportMock.mockResolvedValue(report(overrides));
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());
    renderOverview();
  }

  /** The gap this note was added to close: `Total equity` was a bare dollar figure with no date
   *  anywhere on it, on the same screen where the desk card stated its own staleness plainly. */
  it("states what the tiles are priced at, and how far behind today that is", async () => {
    const priced = isoDaysAgo(2);
    renderWithPricing({ as_of: priced, positions: [position({ price_as_of: priced })] });

    const note = (await screen.findByText(/priced at the close of/)) as HTMLElement;
    expect(note.textContent).toContain(priced);
    expect(note.textContent).toMatch(/2 calendar days behind today/);
  });

  it("escalates to an alert callout once the mark is past the warn threshold", async () => {
    const priced = isoDaysAgo(9);
    renderWithPricing({ as_of: priced, positions: [position({ price_as_of: priced })] });

    const callout = (await screen.findByRole("alert")) as HTMLElement;
    expect(callout.className).toContain("callout-warn");
    expect(callout.textContent).toMatch(/newest price behind these figures is 9 days old/);
    expect(callout.textContent).toMatch(/treat every figure below as that many days stale/);
  });

  /** Matches the threshold `ReferenceDeskSection` uses fifteen lines below on this same page. The
   *  two cards must agree about what counts as stale; one warning while the other stays quiet about
   *  the same lag is the inconsistency this whole note exists to remove. */
  it("does not escalate at exactly the threshold", async () => {
    const priced = isoDaysAgo(5);
    renderWithPricing({ as_of: priced, positions: [position({ price_as_of: priced })] });

    await screen.findByText(/priced at the close of/);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  /** A total that silently aggregates several different price dates is a mix, and saying so is the
   *  point -- the same rule `Portfolio.tsx`'s own totals panel keeps. */
  it("names the span when positions are priced at different closes", async () => {
    const older = isoDaysAgo(3);
    const newer = isoDaysAgo(1);
    renderWithPricing({
      positions: [
        position({ symbol: "NVDA", price_as_of: older }),
        position({ instrument_id: "i-msft", symbol: "MSFT", price_as_of: newer }),
      ],
    });

    const note = (await screen.findByText(/priced at closes ranging/)) as HTMLElement;
    expect(note.textContent).toContain(older);
    expect(note.textContent).toContain(newer);
    expect(note.textContent).toMatch(/a mix of 2 pricing dates/);
  });

  it("says nothing is priced rather than implying a mark that does not exist", async () => {
    renderWithPricing({
      positions: [position({ price_as_of: null })],
      total_market_value: null,
      total_unrealized: null,
      total_unrealized_pct: null,
      priced_position_count: 0,
      unpriced_symbols: ["NVDA"],
    });

    const note = (await screen.findByText(/nothing is priced/)) as HTMLElement;
    expect(note.textContent).toMatch(/no market value is stated below/);
    expect(note.textContent).not.toMatch(/behind today/);
  });

  /** An unreadable date must not render as "today". `daysUntil` answers `0` for anything it cannot
   *  parse, and `0` reads as current -- the one reassurance this note has least right to give about
   *  a date it could not understand. */
  it("omits the day count for an unreadable price date rather than calling it current", async () => {
    renderWithPricing({ positions: [position({ price_as_of: "not-a-date" })] });

    const note = (await screen.findByText(/priced at the close of/)) as HTMLElement;
    expect(note.textContent).not.toMatch(/behind today/);
    expect(note.textContent).not.toMatch(/· today/);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("economic_release events", () => {
  it("renders a scheduled economic release alongside FOMC, without inflating holdings coverage", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(
      calendarFixture({
        events: [
          calendarEvent(), // FOMC Meeting, from the default fixture
          calendarEvent({
            kind: "economic_release",
            title: "PCE inflation (Personal Income and Outlays)",
            date: "2026-08-26",
            end_date: null,
            timing: "before_open",
            confidence: "confirmed",
            source: "fred",
            symbol: null,
            detail: "BEA -- the Fed's preferred inflation gauge, headline and core PCE",
          }),
        ],
        // holdings_total/holdings_covered are read straight off the wire payload -- a release's
        // symbol is always null, so adding one to `events` must never move this number.
        holdings_total: 41,
        holdings_covered: 12,
      }),
    );

    renderOverview();

    // The release reaches the page next to the FOMC row, in the same card.
    expect(await screen.findByText("FOMC Meeting")).toBeTruthy();
    expect(screen.getByText(/PCE inflation/)).toBeTruthy();

    // The coverage sentence still reads verbatim from holdings_covered/holdings_total -- a
    // symbol-less release event does not, and structurally cannot, change this count.
    expect(screen.getByText(/12 of 41 holdings/)).toBeTruthy();
  });
});

describe("independent failures", () => {
  it("a failing macro fetch still renders the portfolio section", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockRejectedValue(new ApiRequestError(502, "upstream unavailable"));
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();

    // Portfolio section renders its real figures despite the macro failure elsewhere on the page.
    expect(await screen.findByText("$4,914.00")).toBeTruthy();

    // Market context reports its own failure rather than rendering blank or stale data.
    expect(await screen.findByText(/Market context failed to load/)).toBeTruthy();
    expect(screen.getByText(/502/)).toBeTruthy();

    // The other two independent sections are unaffected.
    expect(screen.getByText("Savings")).toBeTruthy();
  });

  it("a failing portfolio fetch still renders the market and reference-desk sections", async () => {
    portfolioReportMock.mockRejectedValue(new ApiRequestError(500, "boom"));
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();

    expect(await screen.findByText(/Portfolio failed to load/)).toBeTruthy();
    expect(screen.getByText("Key indicators")).toBeTruthy();
    expect(screen.getByText("Trading")).toBeTruthy();
  });

  it("a failing paper-desk fetch shows its own error and does not blank the attention section", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockRejectedValue(new ApiRequestError(503, "desk down"));
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();

    expect(await screen.findByText(/Reference desk failed to load/)).toBeTruthy();
    // Attention still renders -- it just cannot assess desk staleness, and says so rather than
    // silently going quiet on that one point.
    expect(screen.getByText(/Paper desk staleness could not be checked/)).toBeTruthy();
  });

  it("a failing calendar fetch shows its own error and does not blank the other four sections", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockRejectedValue(new ApiRequestError(502, "calendar upstream down"));

    renderOverview();

    expect(await screen.findByText(/Calendar failed to load/)).toBeTruthy();
    expect(screen.getByText(/502/)).toBeTruthy();

    // The other four independent sections are unaffected by the calendar failure.
    expect(screen.getByText("$4,914.00")).toBeTruthy();
    expect(screen.getByText("Key indicators")).toBeTruthy();
    expect(screen.getByText("Savings")).toBeTruthy();
    expect(await screen.findByText(/Nothing needs attention/)).toBeTruthy();
  });
});

describe("partial-total honesty", () => {
  it("a non-empty unpriced_symbols produces a visible partial caveat on the affected tiles", async () => {
    portfolioReportMock.mockResolvedValue(
      report({
        unpriced_symbols: ["ZZZZ"],
        priced_position_count: 1,
        positions: [position(), position({ instrument_id: "i-zzzz", symbol: "ZZZZ", price: null, market_value: null, unrealized: null, unrealized_pct: null, weight_pct: null })],
      }),
    );
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();

    expect(await screen.findByText(/Unrealized P&L \(partial\)/)).toBeTruthy();
    expect(screen.getByText(/1 of 2 positions priced/)).toBeTruthy();
    expect(screen.getByText(/1 unpriced/)).toBeTruthy();
  });
});

describe("equity-completeness honesty", () => {
  it("discloses equity_is_complete: false rather than rendering a number that looks whole", async () => {
    portfolioReportMock.mockResolvedValue(
      report({ total_equity: null, equity_is_complete: false, cash_balance: null, accounts_without_cash: ["wb-cash"] }),
    );
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();

    expect(await screen.findByText("Total equity")).toBeTruthy();
    // The equity tile renders the withheld dash, not a computed zero, and names the caveat.
    const equityTile = screen.getByText("Total equity").closest(".tile");
    expect(equityTile).toBeTruthy();
    expect(within(equityTile as HTMLElement).getByText("—")).toBeTruthy();
    expect(within(equityTile as HTMLElement).getByText(/incomplete/)).toBeTruthy();
  });
});

describe("attention section", () => {
  it("renders an explicit all-clear message when nothing needs attention", async () => {
    portfolioReportMock.mockResolvedValue(report({ warnings: [] }));
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState({ stale_days: 0 }));
    washTrackerMock.mockResolvedValue(washTracker({ open_window_count: 0 }));
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();

    expect(
      await screen.findByText(/Nothing needs attention/),
    ).toBeTruthy();
  });

  it("does not claim all-clear while the fetches it speaks for are still in flight", async () => {
    // Caught in a browser, not by the unit tests: on first paint every source was still null, so
    // `items.length === 0` was trivially true and the panel rendered "Nothing needs your attention
    // right now" -- then replaced it with "42 open wash-sale windows across 81 symbols" once the
    // tracker resolved. A reader who glances once and looks away is told the opposite of the truth.
    //
    // The wash tracker is left hanging deliberately: an all-clear is a claim about all three
    // fetches, so one unresolved fetch must be enough to withhold it.
    portfolioReportMock.mockResolvedValue(report({ warnings: [] }));
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState({ stale_days: 0 }));
    washTrackerMock.mockReturnValue(new Promise(() => {}));
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();

    expect(await screen.findByText(/Checking for anything that needs attention/)).toBeTruthy();
    expect(screen.queryByText(/Nothing needs attention/)).toBeNull();
  });

  it("surfaces open wash-sale windows, portfolio warnings, and a stale desk when present", async () => {
    portfolioReportMock.mockResolvedValue(
      report({
        warnings: [
          {
            kind: "missing_basis",
            account_id: "rh-taxable",
            broker: "robinhood",
            symbol: "NVDA",
            trade_date: "2026-01-05",
            detail: "basis gap",
          },
        ],
      }),
    );
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState({ stale_days: 9, latest_bar: "2026-08-21" }));
    washTrackerMock.mockResolvedValue(washTracker({ open_window_count: 2, symbol_count: 2 }));
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();

    expect(await screen.findByText(/2 open wash-sale windows/)).toBeTruthy();
    expect(screen.getByText(/1 portfolio warning/)).toBeTruthy();
    // "days behind" also appears in the Reference desk section's own staleness callout -- scope to
    // the Attention section specifically to confirm it surfaced there too.
    const attentionSection = screen
      .getByRole("heading", { name: "Attention" })
      .closest("section") as HTMLElement;
    expect(within(attentionSection).getByText(/9 days behind/)).toBeTruthy();
    expect(screen.queryByText(/Nothing needs your attention/)).toBeNull();
  });
});

describe("paper desk books are never summed", () => {
  it("shows all three books separately, each with its own desk's return, and no combined total", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(
      deskState({
        books: [
          book({
            purpose: "savings",
            label: "Savings",
            benchmark: { symbol: "AGG60", return_pct: "0.02" },
            desks: [desk({ agent_id: "S-core", display_name: "S-core", total_return: "0.0500" })],
          }),
          book({
            purpose: "trading",
            label: "Trading",
            benchmark: { symbol: "SPY", return_pct: "0.10" },
            desks: [
              desk({ agent_id: "B-momentum", display_name: "B-momentum", total_return: "0.0120" }),
              desk({ agent_id: "C-trend", display_name: "C-trend", total_return: "-0.0150" }),
            ],
          }),
          book({
            purpose: "roth",
            label: "Roth IRA",
            benchmark: { symbol: "AGG60", return_pct: "0.03" },
            desks: [desk({ agent_id: "R-growth", display_name: "R-growth", total_return: "0.0800" })],
          }),
        ],
      }),
    );
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();

    await screen.findByText("Savings");

    // Each book renders as its own card with its own desk count -- never merged into one list.
    const savingsCard = screen.getByText("Savings").closest(".overview-book-card") as HTMLElement;
    const tradingCard = screen.getByText("Trading").closest(".overview-book-card") as HTMLElement;
    const rothCard = screen.getByText("Roth IRA").closest(".overview-book-card") as HTMLElement;
    expect(within(savingsCard).getByText("1 desk seated")).toBeTruthy();
    expect(within(tradingCard).getByText("2 desks seated")).toBeTruthy();
    expect(within(rothCard).getByText("1 desk seated")).toBeTruthy();

    // Each desk's own return renders individually, per book.
    expect(within(savingsCard).getByText("S-core")).toBeTruthy();
    expect(within(savingsCard).getByText("+5.00%")).toBeTruthy();
    expect(within(tradingCard).getByText("B-momentum")).toBeTruthy();
    expect(within(tradingCard).getByText("+1.20%")).toBeTruthy();
    expect(within(tradingCard).getByText("C-trend")).toBeTruthy();
    expect(within(tradingCard).getByText("-1.50%")).toBeTruthy();
    expect(within(rothCard).getByText("R-growth")).toBeTruthy();
    expect(within(rothCard).getByText("+8.00%")).toBeTruthy();

    // No combined "my performance" figure exists on this section at all -- each number that
    // renders is traceable to exactly one field already on the wire (one desk's `total_return` or
    // one book's own `benchmark.return_pct`), never a sum this page computed itself.
    const deskSection = screen.getByRole("heading", { name: "Reference desk" }).closest("section") as HTMLElement;
    expect(within(deskSection).queryByText(/my performance/i)).toBeNull();
    expect(within(deskSection).queryByText(/combined/i)).toBeNull();
    // The trading book's two desks (+1.20%, -1.50%) never collapse into one summed trading-book
    // figure such as "-0.30%".
    expect(within(tradingCard).queryByText("-0.30%")).toBeNull();
  });

  it("marks the whole section as simulated money, visibly, in the header and in a caveat line", async () => {
    // UX-02. This panel prints a RETURN % per agent directly under the real-money equity tiles at
    // the top of the same page. The marking may not live behind a disclosure (docs/COPY-STYLE.md
    // rule 6), so both halves of it are asserted as ordinary rendered text.
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();

    const deskSection = (await screen.findByRole("heading", { name: "Reference desk" })).closest(
      "section",
    ) as HTMLElement;
    expect(within(deskSection).getByText("Simulated")).toBeTruthy();
    expect(
      within(deskSection).getByText("Paper money. Own capital per desk, not a portfolio."),
    ).toBeTruthy();
    // Not inside a <details>/disclosure: the caveat is in the page's ordinary flow.
    expect(deskSection.querySelector("details")).toBeNull();
  });

  it("names each book's scrollable table region, so three regions on one row are distinguishable", async () => {
    // A11Y-09/A11Y-03. `ScrollRegion` already supplies `role="region"` + `tabIndex`; what was
    // missing was a distinguishing *name* -- all three books passed the same "Reference desk".
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();
    await screen.findByRole("heading", { name: "Reference desk" });

    expect(screen.getByRole("region", { name: "Savings desks" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Trading desks" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Roth IRA desks" })).toBeTruthy();
  });
});

describe("page heading", () => {
  it("renders exactly one <h1>, so the page's heading outline does not start at level 2", async () => {
    // A11Y-02. Every section on this page is an <h2>; without a page-level heading a screen-reader
    // user jumping by heading had nothing naming the page they had landed on.
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();
    await screen.findByRole("heading", { name: "Reference desk" });

    const h1s = screen.getAllByRole("heading", { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]?.textContent).toBe("Overview");
  });
});

describe("programme status strip", () => {
  function findProgrammeSection() {
    return screen.getByRole("heading", { name: "Programme" }).closest("section") as HTMLElement;
  }

  it("renders the loop, agent-layer, and newest-scored-round stats from their own endpoints", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    evolutionLoopMock.mockResolvedValue(loopStatus({ state: "running" }));
    agentConfigMock.mockResolvedValue(
      agentConfigFixture({ agent_available: false, agent_reason: "Missing ANTHROPIC_API_KEY" }),
    );
    // Three rounds: the highest-sequence one (r20) never ran and has no leaderboard, so the newest
    // *scored* round must be r9, not r20 -- exactly the distinction `has_results` exists to draw.
    competitionRoundsMock.mockResolvedValue({
      rounds: [
        roundSummary({ round_id: "r3-2026-08", label: "R3", sequence: 3, has_results: true }),
        roundSummary({ round_id: "r9-2026-08", label: "R9", sequence: 9, has_results: true }),
        roundSummary({ round_id: "r20-2026-08", label: "R20", sequence: 20, has_results: false }),
      ],
    });

    renderOverview();

    await screen.findByRole("heading", { name: "Programme" });
    const section = findProgrammeSection();

    // Loop: running -> "Running" pill.
    expect(within(section).getByText("Strategy loop")).toBeTruthy();
    expect(await within(section).findByText("Running")).toBeTruthy();

    // Agent layer: unavailable -> "Unavailable" pill, carrying the reason as its detail.
    expect(within(section).getByText("Agent layer")).toBeTruthy();
    const agentPill = await within(section).findByText("Unavailable");
    expect(agentPill.getAttribute("title")).toBe("Missing ANTHROPIC_API_KEY");

    // Newest round: r9 (highest sequence *with* results), never r20 (higher sequence, no results).
    expect(within(section).getByText("Newest round")).toBeTruthy();
    expect(await within(section).findByText("R9")).toBeTruthy();
    expect(within(section).queryByText("R20")).toBeNull();
  });

  it("shows the idle pill when the loop has never been started (a 404, not an error)", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());
    evolutionLoopMock.mockRejectedValue(new ApiRequestError(404, "no loop record"));

    renderOverview();

    await screen.findByRole("heading", { name: "Programme" });
    const programme = findProgrammeSection();
    expect(await within(programme).findByText("Idle")).toBeTruthy();
  });

  it("shows the ready pill when the agent layer is available", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());
    agentConfigMock.mockResolvedValue(agentConfigFixture({ agent_available: true }));

    renderOverview();

    await screen.findByRole("heading", { name: "Programme" });
    const programme = findProgrammeSection();
    expect(await within(programme).findByText("Ready")).toBeTruthy();
  });

  it("shows 'None yet' when no round has a leaderboard", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());
    competitionRoundsMock.mockResolvedValue({
      rounds: [roundSummary({ has_results: false })],
    });

    renderOverview();

    await screen.findByRole("heading", { name: "Programme" });
    const programme = findProgrammeSection();
    expect(await within(programme).findByText("None yet")).toBeTruthy();
  });

  it("degrades a failed fetch to a muted line rather than throwing or blanking the page", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());
    evolutionLoopMock.mockRejectedValue(new ApiRequestError(500, "loop status boom"));

    renderOverview();

    // The page as a whole is unharmed -- the portfolio figure still renders.
    expect(await screen.findByText("$4,914.00")).toBeTruthy();

    const programme = findProgrammeSection();
    expect(within(programme).getByText("Unavailable — the fetch failed.")).toBeTruthy();
    // The other two stats in the same strip are unaffected by the loop fetch's failure.
    expect(await within(programme).findByText("Ready")).toBeTruthy();
    expect(await within(programme).findByText("R5")).toBeTruthy();
  });

  it("links each stat through to the page it summarises", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();

    await screen.findByRole("heading", { name: "Programme" });
    const programme = findProgrammeSection();

    const loopLink = within(programme).getByText("Strategy loop").closest("a");
    const agentLink = within(programme).getByText("Agent layer").closest("a");
    const roundLink = within(programme).getByText("Newest round").closest("a");

    expect(loopLink?.getAttribute("href")).toBe("/competition");
    // Points at the Agent Desk landing page, not the Trading-Agents-specific sub-page: this pill is
    // the only per-desk agent-health signal available (see `useAgentAvailability`'s own docstring --
    // there is no per-desk breakdown endpoint), so it is treated as Overview's one link into the
    // whole Agent Desk system rather than one narrow pipeline within it.
    expect(agentLink?.getAttribute("href")).toBe("/agents");
    expect(roundLink?.getAttribute("href")).toBe("/competition");

    // Strategy Lab has no fetch of its own on this page -- it gets a plain cross-link rather than a
    // fourth `ProgrammeStat` tile.
    const strategyLink = within(programme).getByText("Strategy Lab →").closest("a");
    expect(strategyLink?.getAttribute("href")).toBe("/strategy");
  });
});

describe("tax tile", () => {
  function findTaxSection() {
    return screen.getByRole("heading", { name: "Tax" }).closest("section") as HTMLElement;
  }

  it("shows YTD realized gain, deferred wash total, and open windows from their own endpoints", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(
      washTracker({ open_window_count: 2, symbol_count: 2, total_deferred: "150.00" }),
    );
    calendarUpcomingMock.mockResolvedValue(calendarFixture());
    taxReportMock.mockResolvedValue(
      taxReport({ gains: gainsReport({ short_term_gain: "500.00", long_term_gain: "-120.00" }) }),
    );

    renderOverview();

    const section = findTaxSection();
    // short_term_gain (500.00) + long_term_gain (-120.00) = 380.00, exact via addMoney -- never a
    // client-side re-derivation that could drift from the wire figures.
    expect(await within(section).findByText("+$380.00")).toBeTruthy();
    expect(within(section).getByText("$150.00")).toBeTruthy();
    expect(within(section).getByText("2")).toBeTruthy();
  });

  it("links through to the full tax page", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();

    const section = findTaxSection();
    const link = within(section).getByText("Full tax page →").closest("a");
    expect(link?.getAttribute("href")).toBe("/tax");
  });

  it("shows a dash and does not blank the page when the tax report fetch fails", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());
    taxReportMock.mockRejectedValue(new ApiRequestError(500, "tax engine down"));

    renderOverview();

    expect(await screen.findByText(/Tax summary failed to load/)).toBeTruthy();
    // The rest of the page is unaffected.
    expect(await screen.findByText("$4,914.00")).toBeTruthy();
  });

  it("shows a tax year-end countdown next to the tax tile, computed off Dec 31 of the current year", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();

    const section = await screen.findByRole("heading", { name: "Tax" });
    const container = section.closest("section") as HTMLElement;
    expect(within(container).getByText("Tax year-end")).toBeTruthy();

    // Computed the same way the page does (`daysUntil` against real "now"), so this assertion holds
    // regardless of what day the suite happens to run on -- never a hardcoded day count.
    const year = new Date().getFullYear();
    const remaining = daysUntil(`${year}-12-31`);
    const expectedCaption =
      remaining === 1 ? "1 day left" : remaining === 0 ? "Due today" : `${remaining} days left`;
    expect(within(container).getByText(expectedCaption)).toBeTruthy();
  });

  it("shows the tax year-end countdown even when the tax report fetch fails", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());
    taxReportMock.mockRejectedValue(new ApiRequestError(500, "tax engine down"));

    renderOverview();

    await screen.findByText(/Tax summary failed to load/);
    const section = screen.getByRole("heading", { name: "Tax" }).closest("section") as HTMLElement;
    expect(within(section).getByText("Tax year-end")).toBeTruthy();
  });
});

describe("activity tile", () => {
  it("shows the last transaction and the ledger's transaction count", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());
    transactionsListMock.mockResolvedValue(
      transactionPage({ transactions: [transactionRow({ trade_date: "2026-09-04", action: "sell", symbol: "AMD" })], total: 42 }),
    );

    renderOverview();

    const section = screen.getByRole("heading", { name: "Activity" }).closest("section") as HTMLElement;
    expect(await within(section).findByText("2026-09-04")).toBeTruthy();
    expect(within(section).getByText("42")).toBeTruthy();
    const link = within(section).getByText("Full activity log →").closest("a");
    expect(link?.getAttribute("href")).toBe("/activity");
  });

  it("shows an explicit empty state rather than a blank tile when the ledger has no transactions", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());
    transactionsListMock.mockResolvedValue(transactionPage({ transactions: [], total: 0 }));

    renderOverview();

    const section = screen.getByRole("heading", { name: "Activity" }).closest("section") as HTMLElement;
    expect(await within(section).findByText("No transactions yet")).toBeTruthy();
  });
});

describe("cold-load skeletons", () => {
  /** Never resolves -- pins every panel in its loading phase for the assertions below. */
  function pending<T>(): Promise<T> {
    return new Promise<T>(() => {});
  }

  it("draws a shaped Skeleton for every panel, not a bare loading line", async () => {
    portfolioReportMock.mockReturnValue(pending());
    macroSnapshotMock.mockReturnValue(pending());
    deskStateMock.mockReturnValue(pending());
    washTrackerMock.mockReturnValue(pending());
    calendarUpcomingMock.mockReturnValue(pending());
    taxReportMock.mockReturnValue(pending());
    transactionsListMock.mockReturnValue(pending());
    consensusGetMock.mockReturnValue(pending());

    const { container } = renderOverview();

    // Eight independent fetches back this page, and on a cold load the slowest of them used to sit
    // on a one-line "Loading…" for fifteen seconds while the fast panels rendered around it. Each
    // panel now announces what it is waiting on through `Skeleton`'s own live region.
    const announced = (await screen.findAllByRole("status")).map((el) => el.textContent);
    expect(announced).toContain("Loading account…");
    expect(announced).toContain("Loading market context…");
    expect(announced).toContain("Loading Fear & Greed…");
    expect(announced).toContain("Loading reference desk…");
    expect(announced).toContain("Loading tax…");
    expect(announced).toContain("Loading activity…");
    expect(announced).toContain("Loading calendar…");
    expect(announced).toContain("Loading filer consensus…");

    // And each draws placeholder blocks roughly the shape of the content that is coming, so the
    // panel already occupies close to its final height before the first byte lands.
    expect(container.querySelectorAll(".skeleton-block").length).toBeGreaterThan(8);
    // Nothing is left on the old bare treatment.
    expect(container.querySelectorAll(".panel.placeholder").length).toBe(0);
  });
});

describe("attention: open wash-sale windows are actionable", () => {
  function attentionSection(): HTMLElement {
    return screen.getByRole("heading", { name: "Attention" }).closest("section") as HTMLElement;
  }

  it("names the soonest safe repurchase date alongside the count", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());
    washTrackerMock.mockResolvedValue(
      washTracker({
        open_window_count: 3,
        symbol_count: 2,
        symbols: [
          washSymbol({ symbol: "NVDA", repurchase_safe_on: "2026-09-30" }),
          washSymbol({ symbol: "AMD", repurchase_safe_on: "2026-09-14" }),
        ],
      }),
    );

    renderOverview();
    await screen.findByRole("heading", { name: "Account" });
    const section = attentionSection();

    expect(await within(section).findByText("3 open wash-sale windows across 2 symbols")).toBeTruthy();
    // The earliest OPEN window's date, not the first symbol in the array -- a count with no date
    // told the reader something was true and nothing about when they could act on it.
    expect(within(section).getByText("Soonest repurchase safe on 2026-09-14")).toBeTruthy();
  });

  it("ignores closed windows when picking the soonest date", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());
    washTrackerMock.mockResolvedValue(
      washTracker({
        open_window_count: 1,
        symbol_count: 1,
        symbols: [
          // Already safe: its date is earlier, but it is not what the reader is waiting on.
          washSymbol({ symbol: "AMD", repurchase_safe_on: "2026-08-01", window_is_open: false }),
          washSymbol({ symbol: "NVDA", repurchase_safe_on: "2026-09-30" }),
        ],
      }),
    );

    renderOverview();
    await screen.findByRole("heading", { name: "Account" });
    const section = attentionSection();

    expect(await within(section).findByText("Soonest repurchase safe on 2026-09-30")).toBeTruthy();
    expect(within(section).queryByText("Soonest repurchase safe on 2026-08-01")).toBeNull();
  });

  it("links through to Wash Sales even when nothing needs attention", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());
    washTrackerMock.mockResolvedValue(washTracker());

    renderOverview();
    await screen.findByRole("heading", { name: "Account" });
    const section = attentionSection();

    const link = await within(section).findByRole("link", { name: "Open Wash Sales" });
    expect(link.getAttribute("href")).toBe("/tax?tab=wash");
  });
});

describe("filer consensus tile", () => {
  function findConsensusSection() {
    return screen.getByRole("heading", { name: "Filer consensus" }).closest("section") as HTMLElement;
  }

  it("shows a Skeleton, not a bare loading line, while the slow endpoint is in flight", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());
    // Never resolves -- pins the panel in its loading phase for this assertion.
    consensusGetMock.mockReturnValue(new Promise(() => {}));

    renderOverview();

    const section = findConsensusSection();
    // `Skeleton` renders shaped placeholder blocks plus a `role="status"` live region naming what is
    // loading -- not the plain `.panel.placeholder` line every other loading panel on this page uses
    // (see `misc.overview.tax.loading`/`misc.overview.activity.loading` etc.), which is the bare
    // "Loading…" treatment the brief explicitly rules out for this one tile.
    const status = await within(section).findByRole("status");
    expect(status.textContent).toBe("Loading filer consensus…");
    expect(section.querySelector(".skeleton-block")).toBeTruthy();
    expect(section.querySelector(".panel.placeholder")).toBeNull();
  });

  it("shows the top consensus buy and sell, with the checked-filer denominator, once loaded", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());
    consensusGetMock.mockResolvedValue(
      consensusResponse({
        checked: ["ark", "berkshire", "tiger"],
        buys: [consensusRow({ ticker: "AAPL", buyer_count: 3 })],
        sells: [consensusRow({ ticker: "TSLA", issuer: "Tesla Inc", seller_count: 2 })],
      }),
    );

    renderOverview();

    const section = findConsensusSection();
    expect(await within(section).findByText("AAPL")).toBeTruthy();
    expect(within(section).getByText("TSLA")).toBeTruthy();
    // Denominator is the checked-filer count, never the full tracked universe -- see
    // `@/api/consensus`'s own module docstring on why `unchecked` can never be dropped silently.
    expect(within(section).getByText(/3 of 3 filers buying/)).toBeTruthy();
    expect(within(section).getByText(/2 of 3 filers selling/)).toBeTruthy();
  });

  it("degrades to a dash on failure without blanking the rest of the page", async () => {
    portfolioReportMock.mockResolvedValue(report());
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    washTrackerMock.mockResolvedValue(washTracker());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());
    consensusGetMock.mockRejectedValue(new ApiRequestError(504, "cold cache timeout"));

    renderOverview();

    const section = findConsensusSection();
    // No error banner, no status code -- just a quiet dash on each tile.
    await within(section).findByText("Top consensus buy");
    const dashes = within(section).getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(2);
    expect(within(section).queryByText(/504/)).toBeNull();
    expect(within(section).queryByText(/cold cache timeout/)).toBeNull();

    // The rest of the page rendered fine despite the consensus failure.
    expect(await screen.findByText("$4,914.00")).toBeTruthy();
    expect(screen.getByText("Savings")).toBeTruthy();
  });
});

describe("member view (isOwner: false)", () => {
  beforeEach(() => {
    mockUseAuth.mockImplementation(() => MEMBER_AUTH);
  });

  it("never fetches any of the four owner-only endpoints", async () => {
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();

    // Give the page a chance to settle -- if any owner-only fetch were going to fire, it already
    // would have by the time the market tile (a real, non-owner-only fetch) has resolved.
    await screen.findByText("Key indicators");

    expect(portfolioReportMock).not.toHaveBeenCalled();
    expect(taxReportMock).not.toHaveBeenCalled();
    expect(transactionsListMock).not.toHaveBeenCalled();
    expect(washTrackerMock).not.toHaveBeenCalled();
    // The research tiles are unaffected -- they fetch exactly as they do for the owner.
    expect(macroSnapshotMock).toHaveBeenCalled();
    expect(deskStateMock).toHaveBeenCalled();
  });

  it("shows a compact owner-only line in place of the Portfolio, Tax and Activity tiles", async () => {
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();
    await screen.findByText("Key indicators");

    const notices = screen.getAllByText("This section is available to the owner account only.");
    expect(notices).toHaveLength(3);

    const portfolioSection = screen.getByRole("heading", { name: "Account" }).closest("section") as HTMLElement;
    expect(within(portfolioSection).queryByText("Total equity")).toBeNull();

    const taxSection = screen.getByRole("heading", { name: "Tax" }).closest("section") as HTMLElement;
    expect(within(taxSection).queryByText("Tax year-end")).toBeNull();
    expect(within(taxSection).queryByText("YTD realized gain")).toBeNull();

    const activitySection = screen.getByRole("heading", { name: "Activity" }).closest("section") as HTMLElement;
    expect(within(activitySection).queryByText("Last transaction")).toBeNull();

    // Section links still point through to the real pages -- a member landing on any of them sees
    // `OwnerOnlyNotice` there too (see `App.tsx`'s `OwnerGate`), not a broken link.
    expect(within(portfolioSection).getByText("Full account →").closest("a")?.getAttribute("href")).toBe(
      "/portfolio",
    );
  });

  it("still renders the research tiles (market, reference desk) untouched", async () => {
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState());
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();

    expect(await screen.findByRole("heading", { name: "Market context" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Reference desk" })).toBeTruthy();
    expect(screen.getByText("Savings")).toBeTruthy();
    expect(screen.getByText("Trading")).toBeTruthy();
    expect(screen.getByText("Roth IRA")).toBeTruthy();
  });

  it("resolves the attention panel from desk data alone, rather than sitting on 'Checking' forever", async () => {
    // Regression guard: disabling a fetch leaves that hook's own `phase` stuck at `"loading"`
    // forever (see `Overview()`'s own comment on why it substitutes a resolved literal for a
    // member). If that override were dropped, `AttentionSection`'s `pending` calculation would never
    // clear and this panel would read "Checking…" for the rest of the session.
    macroSnapshotMock.mockResolvedValue(macroSnapshot());
    deskStateMock.mockResolvedValue(deskState({ stale_days: 0 }));
    calendarUpcomingMock.mockResolvedValue(calendarFixture());

    renderOverview();

    expect(await screen.findByText(/Nothing needs attention/)).toBeTruthy();
    expect(screen.queryByText(/Checking for anything that needs attention/)).toBeNull();
  });
});

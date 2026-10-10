/**
 * The Paper Desk page's honesty rules, at render level -- the same discipline `Portfolio.test.tsx`
 * pins for the Portfolio page, applied to a live paper-trading account view instead of a replayed
 * ledger. See that file's docstring for the shared vocabulary this one reuses.
 *
 * What these tests pin, matching the task's definition of done:
 *  - both desks render with `equity` displayed exactly as given, never recomputed client-side from
 *    `cash + positions_value` (the two can legitimately disagree by a rounding/timing gap, and a
 *    client-side sum would silently paper over that);
 *  - a `null` figure (`stop_price`, `sessions_to_time_stop`, `take_profit_pct`) renders `—`, never
 *    `0` or `$0.00`;
 *  - `realised_pnl` and `unrealised_pnl` are two distinct labelled figures, the unrealised one
 *    labelled as a mark, and their sum never appears anywhere on the page;
 *  - the as-of/staleness line names the mark date and a large `stale_days` renders the warning
 *    callout, while a small one does not;
 *  - an empty desk (no holdings, no trades) renders its empty states instead of a blank table;
 *  - every universe symbol appears in the signals table, a held symbol is visibly marked held, and
 *    a `blocked` reason is shown when set;
 *  - `rejections` render visibly, in a warning callout, when non-empty;
 *  - the refresh button calls `paperdeskApi.refresh` and shows a pending state meanwhile.
 *
 * The API module is stubbed at the module boundary (`@/api/paperdesk`), not `fetch` -- the same
 * seam `Portfolio.test.tsx`/`Institutions.test.tsx` stub, so these tests are about rendering, not
 * about JSON parsing.
 *
 * A `kind === "ladder"` desk (the `describe("a drawdown-ladder desk", ...)` block near the bottom)
 * gets its own coverage on top of the rules-card behaviour above: it must render its own rules
 * block (`DeskLadderDescription`, not `DeskRules`) while every kind-agnostic part of the page --
 * upcoming signals, recent decisions, holdings, the collapsed book statistics, the dormant badge --
 * keeps working exactly as it does for a rules desk.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "@/api/client";
import type {
  AutopilotDescription,
  Book,
  Decision,
  Desk,
  FetchSummary,
  Funding,
  Holding,
  LadderDescription,
  PaperDeskState,
  PaperTaxSummary,
  Signal,
  Trade,
} from "@/api/paperdesk";
import type { PersonaBook, PersonaHolding, TraderBook } from "@/api/personas";

const stateMock = vi.fn<() => Promise<PaperDeskState>>();
const refreshMock = vi.fn<() => Promise<PaperDeskState>>();
const setInceptionMock = vi.fn<(inception: string) => Promise<PaperDeskState>>();
const resetInceptionMock = vi.fn<() => Promise<PaperDeskState>>();
// Independent of `stateMock` above -- the persona books section fetches through its own seam
// (`personasApi.books`), never coupled to `paperdeskApi.state`.
const personaBooksMock = vi.fn<() => Promise<PersonaBook[]>>();
// Independent of both `stateMock` and `personaBooksMock` -- the persona TRADER books section
// (Phase 10) fetches through its own seam (`personasApi.traderBooks`), never coupled to either.
const traderBooksMock = vi.fn<() => Promise<TraderBook[]>>();

vi.mock("@/api/paperdesk", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/paperdesk")>();
  return {
    ...actual,
    paperdeskApi: {
      ...actual.paperdeskApi,
      state: () => stateMock(),
      refresh: () => refreshMock(),
      setInception: (inception: string) => setInceptionMock(inception),
      resetInception: () => resetInceptionMock(),
    },
  };
});

vi.mock("@/api/personas", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/personas")>();
  return {
    ...actual,
    personasApi: {
      ...actual.personasApi,
      books: () => personaBooksMock(),
      traderBooks: () => traderBooksMock(),
    },
  };
});

const { default: PaperDesk } = await import("@/pages/PaperDesk");

// ---------------------------------------------------------------------------
// Fixtures -- mirror the contract in the task brief field for field.
// ---------------------------------------------------------------------------

function holding(overrides: Partial<Holding> = {}): Holding {
  return {
    symbol: "NVDA",
    quantity: "120",
    entry_date: "2026-08-05",
    entry_price: "185.20",
    cost_basis: "22224.00",
    last_price: "191.40",
    last_price_date: "2026-08-19",
    market_value: "22968.00",
    unrealised_pnl: "744.00",
    return_pct: "0.0335",
    bars_held: 9,
    weight: 0.227,
    stop_price: "162.98",
    target_price: null,
    sessions_to_time_stop: 171,
    ...overrides,
  };
}

function trade(overrides: Partial<Trade> = {}): Trade {
  return {
    symbol: "MU",
    entry_date: "2026-08-04",
    entry_price: "50.00",
    exit_date: "2026-08-12",
    exit_price: "45.00",
    quantity: "20",
    exit_reason: "stop",
    pnl: "-1200.00",
    return_pct: "-0.084",
    bars_held: 6,
    ...overrides,
  };
}

function decision(overrides: Partial<Decision> = {}): Decision {
  return {
    date: "2026-08-05",
    symbol: "NVDA",
    action: "enter",
    reason: "entry rule fired",
    price: "185.20",
    quantity: "120",
    notional: "22224.00",
    ...overrides,
  };
}

function signal(overrides: Partial<Signal> = {}): Signal {
  return {
    symbol: "NVDA",
    held: true,
    entry_fires: false,
    exit_fires: false,
    last_close: "191.40",
    blocked: null,
    // Unranked by default -- what every card in the library that predates `rank_by` sends. Tests
    // about ranking opt in by passing `rank_value`/`entry_rank` and a `rank_by` on the desk.
    rank_value: null,
    entry_rank: null,
    ...overrides,
  };
}

// The default fixture names whichever momentum card is currently *default-visible*, not merely
// rostered. That distinction is load-bearing: the id must appear in `DEFAULT_VISIBLE_AGENT_IDS` or no
// panel renders at all, and every assertion below then fails for a reason unrelated to what it is
// testing. It has followed the desk twice now -- to `B3-concentrated` when round 11 gave it the
// ranked seat, back to `B-momentum` when the owner re-seated that as the default view -- which is a
// standing cost of seeding view state from a hardcoded id list, and worth remembering if a third
// re-rostering turns this into churn rather than a one-line rename.
function desk(overrides: Partial<Desk> = {}): Desk {
  return {
    agent_id: "B-momentum",
    display_name: "B-momentum",
    discipline: "momentum",
    thesis: "Ride established uptrends confirmed by a long-term moving average.",
    kind: "rules",
    universe: ["NVDA", "AMD"],
    entry: "ema(20) crosses_above ema(50) and close > sma(200)",
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
    holdings: [holding()],
    trades: [trade()],
    decisions: [decision()],
    signals: [signal(), signal({ symbol: "AMD", held: false, blocked: "insufficient cash" })],
    rejections: [],
    rejection_count: 0,
    live_fills: [],
    live_rejections: [],
    live_as_of: null,
    ...overrides,
  };
}

function cTrendDesk(overrides: Partial<Desk> = {}): Desk {
  return desk({
    agent_id: "C-trend",
    display_name: "C-trend",
    discipline: "trend",
    universe: ["XLE", "XLF"],
    equity: "98500.00",
    cash: "98500.00",
    positions_value: "0.00",
    total_return: "-0.0150",
    excess_return: "-0.0270",
    realised_pnl: "-300.00",
    unrealised_pnl: "0.00",
    open_positions: 0,
    slots_free: 6,
    holdings: [],
    trades: [],
    decisions: [],
    signals: [
      signal({ symbol: "XLE", held: false, blocked: null }),
      signal({ symbol: "XLF", held: false, blocked: null }),
    ],
    ...overrides,
  });
}

function aRotationDesk(overrides: Partial<Desk> = {}): Desk {
  return desk({
    agent_id: "A-rotation",
    display_name: "A-rotation",
    discipline: "rotation",
    universe: ["XLK", "XLV"],
    holdings: [],
    trades: [],
    decisions: [],
    signals: [signal({ symbol: "XLK", held: false, blocked: null })],
    ...overrides,
  });
}

function ladderDescription(overrides: Partial<LadderDescription> = {}): LadderDescription {
  return {
    signal_symbol: "SPY",
    defensive_symbol: "SCHD",
    bond_symbol: "IEF",
    leveraged_symbol: "QLD",
    base_defensive_weight_pct: "0.60",
    base_bond_weight_pct: "0.40",
    rungs: [
      { drawdown_pct: "-0.10", leveraged_weight_pct: "0.20" },
      { drawdown_pct: "-0.20", leveraged_weight_pct: "0.60" },
      { drawdown_pct: "-0.30", leveraged_weight_pct: "0.80" },
    ],
    confirm_ma_sessions: 50,
    ath_haircut_pct: "0.5",
    recovery_gain_pct: "0.10",
    recovery_sessions: 60,
    ...overrides,
  };
}

function ladderDesk(overrides: Partial<Desk> = {}): Desk {
  return desk({
    agent_id: "ladder-qld-schd",
    display_name: "Drawdown Ladder - QLD/SCHD/IEF",
    discipline: "drawdown-ladder",
    kind: "ladder",
    universe: ["SCHD", "IEF", "QLD"],
    entry: null,
    exit: null,
    stop_loss_pct: null,
    take_profit_pct: null,
    max_hold_days: null,
    max_positions: null,
    position_pct: null,
    ladder: ladderDescription(),
    equity: "100000.00",
    cash: "0.00",
    positions_value: "100000.00",
    total_return: "0.0000",
    excess_return: "0.0000",
    realised_pnl: "0.00",
    unrealised_pnl: "0.00",
    open_positions: 2,
    slots_free: 1,
    holdings: [
      holding({
        symbol: "SCHD",
        quantity: "1200",
        entry_price: "50.00",
        cost_basis: "60000.00",
        last_price: "50.00",
        market_value: "60000.00",
        unrealised_pnl: "0.00",
        return_pct: "0.0000",
        weight: 0.6,
        stop_price: null,
        target_price: null,
        sessions_to_time_stop: null,
      }),
      holding({
        symbol: "IEF",
        quantity: "400",
        entry_price: "100.00",
        cost_basis: "40000.00",
        last_price: "100.00",
        market_value: "40000.00",
        unrealised_pnl: "0.00",
        return_pct: "0.0000",
        weight: 0.4,
        stop_price: null,
        target_price: null,
        sessions_to_time_stop: null,
      }),
    ],
    trades: [],
    decisions: [],
    signals: [
      signal({ symbol: "SCHD", held: true, blocked: null }),
      signal({ symbol: "IEF", held: true, blocked: null }),
      signal({ symbol: "QLD", held: false, blocked: null, last_close: "40.00" }),
    ],
    ...overrides,
  });
}

function autopilotDescription(overrides: Partial<AutopilotDescription> = {}): AutopilotDescription {
  return {
    arm: "full_workflow",
    universe_source: "screen",
    current_card_id: "momentum-v2",
    card_adopted_date: "2026-08-01",
    orders_total: 5,
    orders_filled: 3,
    orders_pending: 2,
    orders_rejected: 0,
    last_run_id: "run-2026-08-18-0900",
    last_run_state: "succeeded",
    last_run_at: "2026-08-18T13:05:00Z",
    last_run_outcome: "2 entry candidates fired",
    exits: "none",
    ...overrides,
  };
}

/** Minimal `PaperTaxSummary` fixture -- this page never computes any of these figures, only renders
 *  what the server sent, so the values themselves are arbitrary as long as they are internally
 *  consistent (`net_realized_gain = short_term_gain + long_term_gain`, `tax_owed` non-negative). */
function paperTax(overrides: Partial<PaperTaxSummary> = {}): PaperTaxSummary {
  return {
    account_id: "paper-trading",
    start: "2026-08-01",
    end: "2026-08-18",
    short_term_gain: "500.00",
    long_term_gain: "0.00",
    net_realized_gain: "500.00",
    disallowed_loss_total: "0.00",
    permanently_disallowed_total: "0.00",
    wash_sales: [],
    short_term_rate: "0.37",
    long_term_rate: "0.20",
    rate_basis: "statutory_upper_bound",
    tax_owed: "185.00",
    after_tax_realized_gain: "315.00",
    ...overrides,
  };
}

/** A `kind === "autopilot"` seat: the Agent Workflow desk's full-workflow arm. `agent_id` matches
 *  `DEFAULT_VISIBLE_AGENT_IDS`'s `"autopilot-workflow"` deliberately, so a plain `renderPaperDesk`
 *  call (no `revealAllDesks()`) already shows this desk's panel -- the same reasoning the module
 *  docstring gives for `B-momentum`/`A-rotation`/`ladder-qld-schd`.
 *
 *  Every rules-card-only field (`entry`, `exit`, `stop_loss_pct`, `take_profit_pct`, `max_hold_days`,
 *  `max_positions`, `position_pct`, `rank_by`) is `null`, mirroring `ladderDesk`'s own fixture --
 *  this card has no per-symbol boolean rule and no ranking key, same as a ladder desk, for a
 *  different reason (see `AutopilotDescription`'s own docstring in `api/paperdesk.ts`). */
function autopilotDesk(overrides: Partial<Desk> = {}): Desk {
  return desk({
    agent_id: "autopilot-workflow",
    display_name: "Agent Workflow - Autopilot",
    discipline: "autopilot",
    kind: "autopilot",
    universe: ["NVDA", "AMD", "MSFT"],
    entry: null,
    exit: null,
    stop_loss_pct: null,
    take_profit_pct: null,
    max_hold_days: null,
    max_positions: null,
    position_pct: null,
    rank_by: null,
    ladder: null,
    autopilot: autopilotDescription(),
    staged_orders: [],
    equity: "103400.00",
    cash: "40000.00",
    positions_value: "63400.00",
    total_return: "0.0340",
    excess_return: "0.0011",
    realised_pnl: "1200.00",
    unrealised_pnl: "600.00",
    open_positions: 2,
    slots_free: 0,
    holdings: [],
    trades: [],
    decisions: [],
    signals: [signal({ symbol: "NVDA", held: true, blocked: null })],
    ...overrides,
  });
}

function funding(overrides: Partial<Funding> = {}): Funding {
  return {
    purpose: "trading",
    shape: "lump_sum",
    seed: "100000",
    contribution: "0",
    horizon_years_min: null,
    horizon_years_max: null,
    tax_treatment: "taxable",
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
    desks: [desk(), cTrendDesk()],
    ...overrides,
  };
}

/** Accepts the flat keys this fixture used before the desk had books, and wraps them into a single
 *  trading book.
 *
 *  Nearly every test in this file overrides `desks` to assert how one desk renders; none of them is
 *  about how books are laid out, so the shape change should cost them nothing. `books` may be passed
 *  directly by the tests that *are* about the books. */
type StateOverrides = Partial<Omit<PaperDeskState, "books">> &
  Partial<Pick<Book, "desks" | "starting_cash" | "benchmark" | "benchmarks">> & {
    books?: Book[];
  };

function state(overrides: StateOverrides = {}): PaperDeskState {
  const { desks, starting_cash, benchmark, benchmarks, books, ...rest } = overrides;
  const trading = book({
    ...(desks !== undefined ? { desks } : {}),
    ...(starting_cash !== undefined ? { starting_cash } : {}),
    ...(benchmark !== undefined ? { benchmark } : {}),
    ...(benchmarks !== undefined ? { benchmarks } : {}),
  });
  return {
    inception: "2026-08-01",
    // The inception-picker fields the backend added alongside `inception`. Defaulted to "no override
    // in effect, nothing in-sample" so every test written before the picker existed keeps passing
    // unchanged; the "inception control" and "in-sample warning" describe blocks below override these
    // deliberately to exercise a custom date and a straddled design cutoff.
    inception_default: "2026-08-01",
    inception_is_custom: false,
    design_cutoff: "2026-06-01",
    in_sample_sessions: 0,
    earliest_inception: "2020-01-02",
    latest_inception: "2026-08-15",
    // `as_of` equals `latest_bar` by default -- the store's mark is the newest stored session, not
    // perpetually a day behind it. The corrected relationship the backend now sends; the specific
    // "as-of / staleness line" tests below override both fields deliberately to exercise a genuine
    // multi-day gap.
    as_of: "2026-08-18",
    latest_bar: "2026-08-18",
    stale_days: 0,
    first_session: "2026-08-03",
    sessions: 12,
    notes: [],
    books: books ?? [trading],
    ...rest,
  };
}

/**
 * `MemoryRouter` wraps every render, not only the autopilot-desk tests below -- `BookStatistics.tsx`
 * renders a react-router `Link` to `/agent-workflow` for a `kind === "autopilot"` desk, and
 * `<Link>` throws if it is ever mounted outside a router context. No existing desk kind takes that
 * branch, so this is a no-op for every test above the autopilot describe block; the same pattern
 * `Overview.test.tsx` already uses for its own `Link`-rendering component.
 */
async function renderPaperDesk(data: PaperDeskState) {
  stateMock.mockResolvedValue(data);
  render(
    <MemoryRouter>
      <PaperDesk />
    </MemoryRouter>,
  );
  await screen.findByText(/marked to .*close/);
}

/**
 * Ticks every currently-unticked desk checkbox, so every desk the payload sent renders its panel.
 * Only the three `DEFAULT_VISIBLE_AGENT_IDS` render a panel on first paint (see the "desk
 * visibility chooser" describe block below) -- the tests above that block predate the chooser and
 * assert on every desk's own panel content regardless of which agent ids happen to be in the
 * default set, so they reveal the full roster first rather than being rewritten around a viewing
 * preference that has nothing to do with what they are actually checking.
 */
function revealAllDesks() {
  for (const cb of screen.getAllByRole("checkbox") as HTMLInputElement[]) {
    if (!cb.checked) fireEvent.click(cb);
  }
}

beforeEach(() => {
  stateMock.mockReset();
  refreshMock.mockReset();
  setInceptionMock.mockReset();
  resetInceptionMock.mockReset();
  // Default to an empty, successfully-loaded persona books collection -- every test above the
  // "influencer paper books" describe block predates that section and is not about it, so it
  // should see the section's quiet default (empty note) rather than an unresolved fetch or an
  // error state neither asserts on.
  personaBooksMock.mockReset();
  personaBooksMock.mockResolvedValue([]);
  // Default to an empty, successfully-loaded persona TRADER books collection (Phase 10) for the
  // same reason as `personaBooksMock` above -- every test that predates this section is not about
  // it and should see its quiet empty default.
  traderBooksMock.mockReset();
  traderBooksMock.mockResolvedValue([]);
});

describe("equity is displayed as given, never recomputed", () => {
  it("shows both desks' equity exactly as the server sent it, not cash + positions_value", async () => {
    // Deliberately inconsistent with cash + positions_value (63000 + 38200 = 101200.00) so a
    // client-side recompute would silently disagree with the server's own figure -- $99,500.00 is
    // simply what the server sent this fixture, standing in for a rounding or timing gap between
    // the two halves.
    await renderPaperDesk(
      state({
        desks: [
          desk({ agent_id: "B-momentum", cash: "63000.00", positions_value: "38200.00", equity: "99500.00" }),
          cTrendDesk({ agent_id: "C-trend", cash: "50000.00", positions_value: "1000.00", equity: "52000.00" }),
        ],
      }),
    );
    revealAllDesks(); // C-trend is not in the default visible set.

    const body = document.body.textContent ?? "";
    expect(body).toContain("$99,500.00");
    expect(body).toContain("$52,000.00");
    // The naive client-side sums must never appear as the equity figure.
    expect(body).not.toContain("$101,200.00");
    expect(body).not.toContain("$51,000.00");
  });
});

describe("null figures render a dash, never zero", () => {
  it("renders null stop_price, sessions_to_time_stop and take_profit_pct as em dashes", async () => {
    await renderPaperDesk(
      state({
        desks: [
          desk({
            take_profit_pct: null,
            holdings: [
              holding({
                symbol: "NVDA",
                stop_price: null,
                sessions_to_time_stop: null,
              }),
            ],
          }),
          cTrendDesk(),
        ],
      }),
    );

    // "NVDA" appears in both the holdings row and the signals row for this desk, so the lookup is
    // scoped to the holdings table specifically.
    const holdingsTable = document.querySelector(".desk-holdings-table") as HTMLElement;
    const row = within(holdingsTable).getByText("NVDA").closest("tr") as HTMLElement;
    const scoped = within(row);
    // Two dashes for stop price and sessions-to-time-stop; neither renders as "0" or "$0.00".
    expect(scoped.getAllByText("—").length).toBeGreaterThanOrEqual(2);
    expect(row.textContent).not.toContain("$0.00");
    // A lone "0" text node would also be wrong for sessions_to_time_stop -- confirm it is absent
    // from this row entirely.
    const cells = Array.from(row.querySelectorAll("td")).map((td) => td.textContent?.trim());
    expect(cells).not.toContain("0");

    // The desk's own rules block renders the null take-profit as a dash too.
    const rulesBlock = document.querySelector(".desk-rules-block") as HTMLElement;
    expect(within(rulesBlock).getByText(/take profit:/)).toBeTruthy();
    expect(rulesBlock.textContent).toMatch(/take profit:\s*—/);
  });

  it("renders a signal's null last_close as an em dash, paired with its 'no price' block reason", async () => {
    // The live case: a young ticker with no bar yet at the decision session. `blocked` already
    // explains why; `last_close` must not silently become $0.00 next to it.
    await renderPaperDesk(
      state({
        desks: [
          desk({
            agent_id: "B-momentum",
            universe: ["NVDA", "IPOX"],
            signals: [
              signal({ symbol: "NVDA", held: true, blocked: null }),
              signal({ symbol: "IPOX", held: false, entry_fires: false, last_close: null, blocked: "no price" }),
            ],
          }),
          cTrendDesk(),
        ],
      }),
    );

    const signalsTable = document.querySelectorAll(".desk-signals-table")[0] as HTMLElement;
    const row = within(signalsTable).getByText("IPOX").closest("tr") as HTMLElement;
    const scoped = within(row);
    expect(scoped.getByText("—")).toBeTruthy();
    expect(row.textContent).not.toContain("$0.00");
    const cells = Array.from(row.querySelectorAll("td")).map((td) => td.textContent?.trim());
    expect(cells).not.toContain("0");
    expect(scoped.getByText("no price")).toBeTruthy();
  });

  it("says plainly that a card has no stop loss and no hold cap, rather than a bare dash", async () => {
    // A card is allowed to decline a hard stop entirely, or run with no hold cap -- both distinct
    // from a stop/cap that is merely wide or absent-by-formatting-accident. The rules block must
    // say so in words, not leave a dash a reader could mistake for a bug.
    await renderPaperDesk(
      state({
        desks: [
          desk({ agent_id: "B-momentum", stop_loss_pct: null, max_hold_days: null, take_profit_pct: null }),
          cTrendDesk(),
        ],
      }),
    );

    const rulesBlock = document.querySelectorAll(".desk-rules-block")[0] as HTMLElement;
    expect(rulesBlock.textContent).toMatch(/stop loss:\s*no stop loss/);
    expect(rulesBlock.textContent).toMatch(/max hold:\s*no hold cap/);
    // Neither reads as a bare, unexplained dash.
    expect(rulesBlock.textContent).not.toMatch(/stop loss:\s*—/);
    expect(rulesBlock.textContent).not.toMatch(/max hold:\s*—/);
  });
});

describe("realised and unrealised P&L are never summed", () => {
  it("shows both figures separately, the unrealised one labelled as a mark, with no element showing their sum", async () => {
    await renderPaperDesk(
      state({
        desks: [
          desk({ agent_id: "B-momentum", realised_pnl: "400.00", unrealised_pnl: "800.00" }),
          cTrendDesk({ agent_id: "C-trend", realised_pnl: "-300.00", unrealised_pnl: "0.00" }),
        ],
      }),
    );

    // "Realized P&L" / "Unrealized P&L" render once per desk, so the label lookup is scoped to the
    // first desk panel specifically.
    const firstPanel = document.querySelectorAll(".desk-panel")[0] as HTMLElement;
    const scoped = within(firstPanel);
    expect(scoped.getByText(/^Realized P&L$/)).toBeTruthy();
    // The Holdings table also has an "Unrealized P&L" column header, so the tile label -- which
    // carries the "(mark)" qualifier the header does not -- is matched specifically.
    const unrealisedLabel = scoped.getByText(/Unrealized P&L \(mark\)/);
    expect(unrealisedLabel.textContent?.toLowerCase()).toContain("mark");

    const body = document.body.textContent ?? "";
    expect(body).toContain("+$400.00");
    expect(body).toContain("+$800.00");
    // The sum of realised + unrealised for the B-momentum desk (400 + 800 = +1200.00) must not
    // appear anywhere as a combined figure. Matched with a sign-aware regex rather than a bare
    // substring check -- the Trades fixture's own "-$1,200.00" (an unrelated closed-trade loss)
    // contains "$1,200.00" as a substring and would otherwise make this assertion a false positive.
    expect(body).not.toMatch(/(?<!-)\$1,200\.00/);

    // Each is its own tile, never merged into a single node.
    const realisedTile = scoped.getByText(/^Realized P&L$/).closest(".stat");
    const unrealisedTile = scoped.getByText(/Unrealized P&L \(mark\)/).closest(".stat");
    expect(realisedTile).not.toBe(unrealisedTile);
    expect(realisedTile?.textContent).not.toEqual(unrealisedTile?.textContent);
  });
});

describe("the as-of / staleness line", () => {
  it("names the mark date plainly and does not warn when staleness is small", async () => {
    await renderPaperDesk(state({ as_of: "2026-08-18", latest_bar: "2026-08-19", stale_days: 1 }));

    const body = document.body.textContent ?? "";
    expect(body).toContain("marked to");
    expect(body).toContain("2026-08-18");
    expect(document.querySelector(".desk-stale-callout")).toBeNull();
  });

  /** `stale_days` is `today - latest_bar`. `as_of` and `latest_bar` are equal by construction, so a
   *  line describing `stale_days` as a gap *between those two* would print one date twice and then
   *  claim they differ -- which is what this line used to do. */
  it("describes stale_days as a lag behind today, not a gap between two equal dates", async () => {
    await renderPaperDesk(
      state({ as_of: "2026-08-25", latest_bar: "2026-08-25", stale_days: 1 }),
    );

    const note = document.querySelector(".desk-mark-note") as HTMLElement;
    expect(note.textContent).toMatch(/1 calendar day behind today/);
    expect(note.textContent).not.toMatch(/ahead of the mark/);
  });

  it("renders a warning callout when stale_days is large", async () => {
    await renderPaperDesk(state({ as_of: "2026-08-10", latest_bar: "2026-08-19", stale_days: 9 }));

    const callout = document.querySelector(".desk-stale-callout");
    expect(callout).not.toBeNull();
    expect(callout?.textContent).toMatch(/9 days/);
  });

  /** The pill is an at-a-glance duplicate of the same fact, not a replacement for the callout: it
   *  fires at any `stale_days > 0`, including a lag too small to earn the louder `callout-warn`
   *  above (that one needs `stale_days > STALE_DAYS_WARN_THRESHOLD`). */
  it("shows a stale-days pill whenever stale_days is above zero, even when the callout does not fire", async () => {
    await renderPaperDesk(state({ as_of: "2026-08-18", latest_bar: "2026-08-19", stale_days: 1 }));

    expect(document.querySelector(".desk-stale-callout")).toBeNull();
    const pill = document.querySelector(".desk-stale-pill");
    expect(pill).not.toBeNull();
    expect(pill?.textContent).toMatch(/Stale 1d/);
  });

  it("omits the stale-days pill when stale_days is zero", async () => {
    await renderPaperDesk(state({ as_of: "2026-08-18", latest_bar: "2026-08-18", stale_days: 0 }));

    expect(document.querySelector(".desk-stale-pill")).toBeNull();
  });
});

describe("an empty desk", () => {
  it("renders its empty states rather than blank tables", async () => {
    await renderPaperDesk(
      state({
        desks: [
          desk({ agent_id: "B-momentum" }),
          cTrendDesk({ agent_id: "C-trend", holdings: [], trades: [] }),
        ],
      }),
    );
    revealAllDesks(); // C-trend is not in the default visible set.

    expect(screen.getByText("No open positions.")).toBeTruthy();
    expect(screen.getByText("No closed trades yet.")).toBeTruthy();
    // No empty <table> body should be silently rendered for the empty desk's holdings/trades.
    expect(screen.queryAllByRole("table").length).toBeGreaterThan(0); // the desk with data still has tables
  });
});

describe("signals", () => {
  it("renders every universe symbol, marks a held symbol distinctly, and shows a blocked reason", async () => {
    await renderPaperDesk(
      state({
        desks: [
          desk({
            agent_id: "B-momentum",
            universe: ["NVDA", "AMD"],
            signals: [
              signal({ symbol: "NVDA", held: true, blocked: null }),
              signal({ symbol: "AMD", held: false, entry_fires: false, blocked: "insufficient cash" }),
            ],
          }),
          cTrendDesk(),
        ],
      }),
    );

    // NVDA/AMD also appear in the holdings table for this desk, so lookups are scoped to the
    // signals table specifically.
    const signalsTables = document.querySelectorAll(".desk-signals-table");
    const signalsTable = signalsTables[0] as HTMLElement;

    const nvdaRow = within(signalsTable).getByText("NVDA").closest("tr") as HTMLElement;
    expect(within(nvdaRow).getByText("Held")).toBeTruthy();

    const amdRow = within(signalsTable).getByText("AMD").closest("tr") as HTMLElement;
    expect(within(amdRow).getByText("Not held")).toBeTruthy();
    expect(within(amdRow).getByText("insufficient cash")).toBeTruthy();
  });
});

describe("rejections", () => {
  it("renders visibly in a warning callout when non-empty", async () => {
    await renderPaperDesk(
      state({
        desks: [
          desk({
            agent_id: "B-momentum",
            rejections: [
              {
                rule: "max_positions",
                label: "Exceeds max positions",
                count: 1,
                symbols: ["TSLA"],
                detail: ["Order for TSLA rejected: exceeds max_positions"],
              },
            ],
            rejection_count: 1,
          }),
          cTrendDesk(),
        ],
      }),
    );

    const callout = document.querySelector(".desk-rejections");
    expect(callout).not.toBeNull();
    expect(callout?.textContent).toMatch(/TSLA/);
    expect(callout?.className).toContain("callout-warn");
  });

  it("renders no rejections callout when the array is empty", async () => {
    await renderPaperDesk(state({ desks: [desk({ rejections: [] }), cTrendDesk({ rejections: [] })] }));
    expect(document.querySelector(".desk-rejections")).toBeNull();
  });
});

describe("desk count is never hardcoded -- one card per desk the API actually returns", () => {
  // The roster is `app.paperdesk.desk`'s own decision (`AGENT_IDS`), not a number this page may
  // assume -- it has already grown from two desks to three once (see the module docstring), and
  // round 5 grows it again to four. These fixtures stand in for a third and fourth desk without
  // reusing `cTrendDesk`'s agent_id, so each renders as its own distinct panel.
  function thirdDesk(overrides: Partial<Desk> = {}): Desk {
    return desk({
      agent_id: "D-carry",
      display_name: "D-carry",
      discipline: "carry",
      universe: ["TLT", "HYG"],
      holdings: [],
      trades: [],
      decisions: [],
      signals: [signal({ symbol: "TLT", held: false, blocked: null })],
      ...overrides,
    });
  }
  function fourthDesk(overrides: Partial<Desk> = {}): Desk {
    return desk({
      agent_id: "E-value",
      display_name: "E-value",
      discipline: "value",
      universe: ["BRK.B", "JPM"],
      holdings: [],
      trades: [],
      decisions: [],
      signals: [signal({ symbol: "BRK.B", held: false, blocked: null })],
      ...overrides,
    });
  }

  it("renders one panel per desk for a three-element roster", async () => {
    await renderPaperDesk(state({ desks: [desk(), cTrendDesk(), thirdDesk()] }));
    revealAllDesks(); // only B-momentum is in the default visible set here.

    const panels = document.querySelectorAll(".desk-panel");
    expect(panels.length).toBe(3);
    // Each desk's own agent_id also appears in the header's roster sentence, so panel titles are
    // matched specifically rather than via a page-wide text lookup that would find both.
    const titles = Array.from(document.querySelectorAll(".desk-panel-title")).map((t) => t.textContent);
    expect(titles).toEqual(["B-momentum", "C-trend", "D-carry"]);
    expect(screen.getByText(/3 strategies, \d+ books/)).toBeTruthy();
  });

  it("renders one panel per desk for a four-element roster, with no desk dropped or merged", async () => {
    await renderPaperDesk(state({ desks: [desk(), cTrendDesk(), thirdDesk(), fourthDesk()] }));
    revealAllDesks(); // only B-momentum is in the default visible set here.

    const panels = document.querySelectorAll(".desk-panel");
    expect(panels.length).toBe(4);
    const titles = Array.from(document.querySelectorAll(".desk-panel-title")).map((t) => t.textContent);
    expect(titles).toEqual(["B-momentum", "C-trend", "D-carry", "E-value"]);
    expect(screen.getByText(/4 strategies, \d+ books/)).toBeTruthy();

    // Every panel's discipline badge is distinct -- proof the fourth desk is its own render, not a
    // duplicate of an existing one produced by an off-by-one in a fixed-length layout.
    const disciplines = Array.from(panels).map(
      (p) => p.querySelector(".desk-discipline-badge")?.textContent,
    );
    expect(new Set(disciplines).size).toBe(4);
  });
});

describe("what it would do next -- upcoming buys and sells from signals", () => {
  it("surfaces an unheld symbol with entry_fires as an upcoming buy", async () => {
    await renderPaperDesk(
      state({
        desks: [
          desk({
            agent_id: "B-momentum",
            universe: ["NVDA", "AMD"],
            signals: [
              signal({ symbol: "NVDA", held: true, entry_fires: false, exit_fires: false }),
              signal({ symbol: "AMD", held: false, entry_fires: true, exit_fires: false, last_close: "172.50" }),
            ],
          }),
          cTrendDesk(),
        ],
      }),
    );

    const firstPanel = document.querySelectorAll(".desk-panel")[0] as HTMLElement;
    const upcoming = firstPanel.querySelector(".desk-upcoming-section") as HTMLElement;
    expect(upcoming).not.toBeNull();
    expect(within(upcoming).getByText(/Buy signal/)).toBeTruthy();
    const amdItem = within(upcoming).getByText("AMD").closest(".desk-upcoming-item") as HTMLElement;
    expect(within(amdItem).getByText("$172.50")).toBeTruthy();
    // The held, non-firing NVDA signal must not itself show up as an upcoming buy or sell.
    expect(within(upcoming).queryByText("NVDA")).toBeNull();
    // The note names this as a forward-looking read, not something already done.
    expect(upcoming.textContent).toMatch(/next/i);
  });

  it("surfaces a held symbol with exit_fires as an upcoming sell", async () => {
    await renderPaperDesk(
      state({
        desks: [
          desk({
            agent_id: "B-momentum",
            universe: ["NVDA", "AMD"],
            signals: [
              signal({ symbol: "NVDA", held: true, entry_fires: false, exit_fires: true, last_close: "191.40" }),
              signal({ symbol: "AMD", held: false, entry_fires: false, exit_fires: false }),
            ],
          }),
          cTrendDesk(),
        ],
      }),
    );

    const firstPanel = document.querySelectorAll(".desk-panel")[0] as HTMLElement;
    const upcoming = firstPanel.querySelector(".desk-upcoming-section") as HTMLElement;
    expect(within(upcoming).getByText(/Sell signal/)).toBeTruthy();
    const nvdaItem = within(upcoming).getByText("NVDA").closest(".desk-upcoming-item") as HTMLElement;
    expect(within(nvdaItem).getByText("$191.40")).toBeTruthy();
    // A signal that is merely held with no exit firing is not a sell.
    expect(within(upcoming).queryByText("AMD")).toBeNull();
  });

  it("renders a designed empty state when no signal fires either way", async () => {
    await renderPaperDesk(
      state({
        desks: [
          desk({
            agent_id: "B-momentum",
            universe: ["NVDA", "AMD"],
            signals: [
              signal({ symbol: "NVDA", held: true, entry_fires: false, exit_fires: false }),
              signal({ symbol: "AMD", held: false, entry_fires: false, exit_fires: false }),
            ],
          }),
          cTrendDesk({
            signals: [
              signal({ symbol: "XLE", held: false, entry_fires: false, exit_fires: false }),
              signal({ symbol: "XLF", held: false, entry_fires: false, exit_fires: false }),
            ],
          }),
        ],
      }),
    );

    const panels = document.querySelectorAll(".desk-panel");
    for (const panel of Array.from(panels)) {
      const upcoming = panel.querySelector(".desk-upcoming-section") as HTMLElement;
      expect(upcoming).not.toBeNull();
      expect(within(upcoming).getByText(/No entry or exit signal fired/)).toBeTruthy();
      expect(upcoming.querySelector(".desk-upcoming-grid")).toBeNull();
    }
  });
});

describe("ranked entries -- which qualifying name actually takes the slot", () => {
  /** Three names firing into two free slots, ranked by `close / sma(200)`. Before `rank_by`
   *  reached this panel the reader saw three equal-looking rows and had no way to tell which the
   *  desk buys; `signals[]` arrives in the engine's own order, so the assertions below are about
   *  the page preserving and *labelling* that order rather than re-deriving it. */
  /** The ranked desk is always rendered first, and every assertion below is about its panel.
   *  Indexing `querySelectorAll` returns `Element | undefined` under this project's
   *  `noUncheckedIndexedAccess`, so the cast lives here once instead of at every call site. */
  function firstPanel(): HTMLElement {
    return document.querySelectorAll(".desk-panel")[0] as HTMLElement;
  }

  function rankedDesk() {
    return desk({
      agent_id: "B-momentum",
      universe: ["NVDA", "AMD", "AVGO"],
      rank_by: "close / sma(200)",
      max_positions: 6,
      open_positions: 4,
      slots_free: 2,
      holdings: [],
      signals: [
        signal({ symbol: "AVGO", held: false, entry_fires: true, last_close: "310.00", rank_value: 1.1842, entry_rank: 1 }),
        signal({ symbol: "NVDA", held: false, entry_fires: true, last_close: "191.40", rank_value: 1.0713, entry_rank: 2 }),
        signal({ symbol: "AMD", held: false, entry_fires: true, last_close: "172.50", rank_value: 1.0091, entry_rank: 3 }),
      ],
    });
  }

  it("lists the buys in engine order with a queue position and the key value", async () => {
    await renderPaperDesk(state({ desks: [rankedDesk(), cTrendDesk()] }));

    const firstPanel = document.querySelectorAll(".desk-panel")[0] as HTMLElement;
    const upcoming = firstPanel.querySelector(".desk-upcoming-section") as HTMLElement;

    const items = Array.from(upcoming.querySelectorAll(".desk-upcoming-item"));
    expect(items.map((i) => i.querySelector(".position-symbol")?.textContent)).toEqual([
      "AVGO",
      "NVDA",
      "AMD",
    ]);
    expect(items.map((i) => i.querySelector(".desk-rank-badge")?.textContent)).toEqual([
      "#1",
      "#2",
      "#3",
    ]);
    // The key value is shown, at four decimals -- rounding harder would print #1 and #2 as the
    // same number while the desk ranked one above the other.
    expect(items.map((i) => i.querySelector(".desk-upcoming-rank-value")?.textContent)).toEqual([
      "1.1842",
      "1.0713",
      "1.0091",
    ]);
  });

  it("says what the ranking is and how far down it the money reaches", async () => {
    await renderPaperDesk(state({ desks: [rankedDesk(), cTrendDesk()] }));

    const upcoming = firstPanel().querySelector(".desk-upcoming-section") as HTMLElement;
    const note = upcoming.querySelector(".desk-upcoming-rank-note") as HTMLElement;
    expect(note).not.toBeNull();
    // Naming the expression is the point: `1.1842` means nothing without it.
    expect(note.textContent).toContain("close / sma(200)");
    expect(note.textContent).toMatch(/2 slots free/);
    expect(note.textContent).toMatch(/#2/);
  });

  it("dims the names past the last free slot without dropping them", async () => {
    await renderPaperDesk(state({ desks: [rankedDesk(), cTrendDesk()] }));

    const upcoming = firstPanel().querySelector(".desk-upcoming-section") as HTMLElement;
    const outranked = Array.from(
      upcoming.querySelectorAll(".desk-upcoming-item-outranked .position-symbol"),
    ).map((n) => n.textContent);
    // Two slots free, so only #3 misses out -- and it is still listed, because a reader wants to
    // know what the desk passed over.
    expect(outranked).toEqual(["AMD"]);
    expect(within(upcoming).getByText("AMD")).toBeTruthy();
  });

  it("says plainly when a full book means nothing in the queue gets bought", async () => {
    await renderPaperDesk(
      state({ desks: [desk({ ...rankedDesk(), slots_free: 0, open_positions: 6 }), cTrendDesk()] }),
    );

    const note = firstPanel().querySelector(".desk-upcoming-rank-note") as HTMLElement;
    expect(note.textContent).toMatch(/No slot is free/);
    // Every contender is past the (zero) cutoff, so all three are dimmed -- and all three remain.
    const upcoming = firstPanel().querySelector(".desk-upcoming-section") as HTMLElement;
    expect(upcoming.querySelectorAll(".desk-upcoming-item-outranked").length).toBe(3);
  });

  it("adds a labelled key column to the full signals table", async () => {
    await renderPaperDesk(state({ desks: [rankedDesk(), cTrendDesk()] }));

    const table = firstPanel().querySelector(".desk-signals-table") as HTMLElement;
    expect(table).not.toBeNull();
    expect(within(table).getByText("Rank key")).toBeTruthy();

    const rows = Array.from(table.querySelectorAll("tbody tr"));
    expect(rows.map((r) => r.querySelector(".position-symbol")?.textContent)).toEqual([
      "AVGO",
      "NVDA",
      "AMD",
    ]);
    const firstKeyCell = (rows[0] as HTMLElement).querySelector(
      ".desk-signals-rank-cell",
    ) as HTMLElement;
    expect(firstKeyCell.textContent).toContain("1.1842");
    expect(firstKeyCell.textContent).toContain("#1");
  });

  it("leaves an unranked desk exactly as it was -- no column, no badges, no note", async () => {
    await renderPaperDesk(
      state({
        desks: [
          desk({
            agent_id: "B-momentum",
            universe: ["NVDA", "AMD"],
            signals: [
              signal({ symbol: "NVDA", held: false, entry_fires: true, last_close: "191.40" }),
              signal({ symbol: "AMD", held: false, entry_fires: true, last_close: "172.50" }),
            ],
          }),
          cTrendDesk(),
        ],
      }),
    );

    const panel = document.querySelectorAll(".desk-panel")[0] as HTMLElement;
    expect(panel.querySelector(".desk-upcoming-rank-note")).toBeNull();
    expect(panel.querySelector(".desk-rank-badge")).toBeNull();
    expect(panel.querySelector(".desk-signals-rank-cell")).toBeNull();
    const table = panel.querySelector(".desk-signals-table") as HTMLElement;
    expect(within(table).queryByText("Rank key")).toBeNull();
    // The buys themselves still render -- only the ranking apparatus is absent.
    const upcoming = panel.querySelector(".desk-upcoming-section") as HTMLElement;
    expect(upcoming.querySelectorAll(".desk-upcoming-item").length).toBe(2);
  });
});

describe("what it just did -- recent decisions", () => {
  it("lists decisions newest first, capped, above the holdings table", async () => {
    await renderPaperDesk(
      state({
        desks: [
          desk({
            agent_id: "B-momentum",
            decisions: [
              decision({ date: "2026-08-05", symbol: "NVDA", action: "enter" }),
              decision({ date: "2026-08-12", symbol: "AMD", action: "enter" }),
              decision({ date: "2026-08-18", symbol: "NVDA", action: "exit" }),
            ],
          }),
          cTrendDesk(),
        ],
      }),
    );

    const firstPanel = document.querySelectorAll(".desk-panel")[0] as HTMLElement;
    const recentSection = firstPanel.querySelector(".desk-recent-section") as HTMLElement;
    expect(recentSection).not.toBeNull();
    const dates = Array.from(recentSection.querySelectorAll(".desk-recent-date")).map(
      (el) => el.textContent,
    );
    expect(dates).toEqual(["2026-08-18", "2026-08-12", "2026-08-05"]);

    // The recent-activity section appears before the holdings table in document order.
    const holdings = firstPanel.querySelector(".desk-holdings-table") as HTMLElement;
    expect(
      recentSection.compareDocumentPosition(holdings) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});

describe("book statistics are demoted into a collapsed section", () => {
  it("still exposes equity, P&L and the full signals/decisions/trades tables inside it", async () => {
    await renderPaperDesk(state());

    const firstPanel = document.querySelectorAll(".desk-panel")[0] as HTMLElement;
    const bookStats = firstPanel.querySelector(".desk-book-stats") as HTMLElement;
    expect(bookStats).not.toBeNull();
    expect(bookStats.tagName.toLowerCase()).toBe("details");
    expect(within(bookStats).getByText(/^Realized P&L$/)).toBeTruthy();
    expect(bookStats.querySelector(".desk-signals-table")).not.toBeNull();
    expect(bookStats.querySelector(".desk-decisions-table")).not.toBeNull();
    expect(bookStats.querySelector(".desk-trades-table")).not.toBeNull();

    // It comes after the upcoming-signals / recent-activity / holdings block, not before.
    const upcoming = firstPanel.querySelector(".desk-upcoming-section") as HTMLElement;
    expect(
      upcoming.compareDocumentPosition(bookStats) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});

/**
 * The equal-height card grid. This page was the app's worst-aligned one: `.desk-grid` set
 * `align-items: start` and every panel sized itself from the SUM of up to six sibling scroll
 * regions plus three unbounded blocks, so one card with an open `<details>` ran roughly 2,500px
 * while its row-mates stayed put. The fix is structural rather than cosmetic -- the height belongs
 * to the grid's tracks and each card has exactly one scrolling body -- so these assertions are
 * about that structure, not about any particular pixel count (jsdom computes no layout anyway).
 */
describe("desk cards are one bounded body each, in an equal-height grid", () => {
  /** Direct children only. Several of a card's own blocks (the upcoming buy/sell lists) are
   *  themselves `.scroll-region`s nested inside the body, so a descendant query would count them
   *  too and this assertion would pass for exactly the shape it exists to rule out. */
  function bodiesOf(card: Element): Element[] {
    return Array.from(card.children).filter((el) => el.classList.contains("card-body"));
  }

  it("puts every desk in a CardGrid that keeps the page's own 3-up column count", async () => {
    await renderPaperDesk(state({ desks: [desk(), aRotationDesk(), ladderDesk()] }));

    const grid = document.querySelector(".card-grid.desk-grid") as HTMLElement;
    expect(grid).not.toBeNull();
    // `lg` on the grid, not just on each card: `grid-auto-rows` is what equalises a row, and a
    // card whose own height literal disagreed with its grid's would size its body against a track
    // it was never given.
    expect(grid.className).toContain("card-grid-lg");
    expect(grid.querySelectorAll(":scope > .desk-panel")).toHaveLength(3);
  });

  it("gives each desk card exactly one scrolling body, and it is the card body itself", async () => {
    await renderPaperDesk(state({ desks: [desk(), aRotationDesk(), ladderDesk()] }));

    const cards = Array.from(document.querySelectorAll(".desk-panel.card"));
    expect(cards).toHaveLength(3);
    for (const card of cards) {
      const bodies = bodiesOf(card);
      expect(bodies).toHaveLength(1);
      expect(bodies[0]?.classList.contains("scroll-region")).toBe(true);
      // Named, because a scrollable box that becomes a tab stop and announces nothing is worse
      // than no tab stop at all (`ScrollRegion`'s own required-`label` contract).
      expect(bodies[0]?.getAttribute("aria-label")).toBe(
        card.querySelector(".desk-panel-title")?.textContent,
      );
    }
  });

  it("bounds each upcoming buy/sell list rather than letting the column grow without limit", async () => {
    await renderPaperDesk(
      state({
        desks: [
          desk({
            agent_id: "B-momentum",
            universe: ["NVDA", "AMD"],
            signals: [
              signal({ symbol: "NVDA", held: true, entry_fires: false, exit_fires: true }),
              signal({ symbol: "AMD", held: false, entry_fires: true, exit_fires: false }),
            ],
          }),
        ],
      }),
    );

    const grid = document.querySelector(".desk-upcoming-grid") as HTMLElement;
    expect(grid).not.toBeNull();
    // Both columns -- the buy side carries a `QueueNote` the sell side does not, and until this
    // existed that alone made the two columns different heights on top of both being unbounded.
    const lists = Array.from(grid.querySelectorAll(".desk-upcoming-items"));
    expect(lists).toHaveLength(2);
    for (const list of lists) {
      expect(list.closest(".scroll-region")).not.toBeNull();
    }
  });

  it("bounds the after-tax wash-sale table, which sits outside the grid and nothing else caps", async () => {
    await renderPaperDesk(
      state({
        desks: [
          desk({
            tax: paperTax({
              wash_sales: [
                {
                  symbol: "MU",
                  loss_date: "2026-08-12",
                  repurchase_date: "2026-08-20",
                  quantity_sold: "20",
                  quantity_replaced: "20",
                  disallowed_amount: "1200.00",
                  permanently_disallowed: false,
                  disposal_id: "d-1",
                  event_id: "w-1",
                },
              ],
            }),
          }),
        ],
      }),
    );

    const taxPanel = Array.from(document.querySelectorAll(".desk-panel")).find(
      (p) => p.querySelector(".desk-panel-title")?.textContent === "B-momentum — after tax",
    ) as HTMLElement;
    expect(taxPanel).toBeTruthy();
    const table = taxPanel.querySelector("table") as HTMLElement;
    expect(within(table).getByText("MU")).toBeTruthy();
    expect(table.closest(".scroll-region")).not.toBeNull();
  });
});

describe("page-level framing note", () => {
  it("states the desks are independent reference strategies, not a combined portfolio", async () => {
    await renderPaperDesk(state());

    const note = document.querySelector(".desk-framing-note") as HTMLElement;
    expect(note).not.toBeNull();
    expect(note.textContent).toMatch(/own simulated capital, own rules/i);
    expect(note.textContent).toMatch(/not a combined portfolio/i);
    expect(note.textContent).toMatch(/book totals aren.t comparable across books/i);
  });
});

describe("the fetch button", () => {
  /** The `FetchSummary` shape the server returns from `POST /api/paperdesk/refresh?fetch=true`.
   *  Defaults describe the *interesting* case -- a fetch that pulled new bars and moved the mark --
   *  so a test asserting the boring one has to say so explicitly. */
  function fetchSummary(overrides: Partial<FetchSummary> = {}): FetchSummary {
    return {
      requested: 40,
      advanced: 38,
      unchanged: 2,
      failed: 0,
      rows_merged: 60,
      failures: [],
      started_at: "2026-08-26T11:19:00Z",
      finished_at: "2026-08-26T11:19:38Z",
      duration_seconds: 38.2,
      latest_bar_before: "2026-08-24",
      latest_bar_after: "2026-08-25",
      ...overrides,
    };
  }

  it("calls the refresh function and shows a pending state", async () => {
    await renderPaperDesk(state());

    let resolveRefresh!: (value: PaperDeskState) => void;
    refreshMock.mockReturnValue(
      new Promise<PaperDeskState>((resolve) => {
        resolveRefresh = resolve;
      }),
    );

    const button = screen.getByRole("button", { name: /Fetch latest data/ });
    fireEvent.click(button);

    expect(refreshMock).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("button", { name: /Fetching/ })).toBeTruthy();
    expect((screen.getByRole("button", { name: /Fetching/ }) as HTMLButtonElement).disabled).toBe(
      true,
    );

    resolveRefresh(state({ as_of: "2026-08-19", stale_days: 0 }));
    expect(await screen.findByRole("button", { name: /^Fetch latest data$/ })).toBeTruthy();
  });

  it("says what the fetch pulled and that the mark moved", async () => {
    await renderPaperDesk(state());
    refreshMock.mockResolvedValue(
      state({ as_of: "2026-08-25", stale_days: 1, fetch: fetchSummary() }),
    );

    fireEvent.click(screen.getByRole("button", { name: /Fetch latest data/ }));

    const summary = (await screen.findByText(/40 symbols in/)) as HTMLElement;
    expect(summary.textContent).toMatch(/38 adv/);
    expect(summary.textContent).toMatch(/2 cur\b/);
    expect(summary.textContent).not.toMatch(/failed/);
    // "merged", never "new": the provider re-sends a short overlap on every request, so this count
    // is large even on a press that stored no new session at all.
    expect(summary.textContent).toMatch(/60 bars merged/);
    expect(summary.textContent).not.toMatch(/new bars|new daily bars/);

    const mark = document.querySelector(".desk-fetch-mark") as HTMLElement;
    expect(mark.textContent).toMatch(/moved from 2026-08-24 to 2026-08-25/);
  });

  /** The outcome most likely to read as a broken button: the fetch worked, every symbol answered,
   *  and the mark legitimately did not move because no later session exists yet. The page has to
   *  say that in words rather than leave a reader comparing an unchanged date against a button they
   *  just pressed. */
  it("explains an unmoved mark rather than leaving it to be inferred", async () => {
    await renderPaperDesk(state());
    refreshMock.mockResolvedValue(
      state({
        fetch: fetchSummary({
          advanced: 0,
          unchanged: 40,
          rows_merged: 56,
          latest_bar_before: "2026-08-25",
          latest_bar_after: "2026-08-25",
        }),
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: /Fetch latest data/ }));

    const mark = (await screen.findByText(/the provider had no later session/)) as HTMLElement;
    expect(mark.textContent).toMatch(/2026-08-25/);
    expect(mark.textContent).toMatch(/the mark is unchanged/);
    // The contradiction this pairing used to produce: 56 rows came back, no session moved, and the
    // line above said "56 new daily bars stored" directly beneath "still 2026-08-25".
    const summary = document.querySelector(".desk-fetch-summary") as HTMLElement;
    expect(summary.textContent).toMatch(/0 adv/);
    expect(summary.textContent).toMatch(/56 bars merged/);
    expect(summary.textContent).not.toMatch(/new bars|new daily bars/);
  });

  /** A rate-limited ticker among forty is not a page-level error: the recompute ran and every other
   *  symbol is current. It must still be listed by name -- a count alone leaves a reader unable to
   *  tell whether the symbol they care about is one of them. */
  it("lists per-symbol failures without failing the page", async () => {
    await renderPaperDesk(state());
    refreshMock.mockResolvedValue(
      state({
        fetch: fetchSummary({
          advanced: 37,
          unchanged: 1,
          failed: 2,
          failures: ["NVDA: rate limited", "SGOV: provider unavailable"],
        }),
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: /Fetch latest data/ }));

    expect(await screen.findByText(/NVDA: rate limited/)).toBeTruthy();
    expect(screen.getByText(/SGOV: provider unavailable/)).toBeTruthy();
    expect(document.querySelector(".desk-refresh-error")).toBeNull();
  });

  /** A plain page load fetched nothing, so there is nothing to report -- and reporting some earlier
   *  press's counters would be worse than reporting none. */
  it("renders no fetch report before the button has ever been pressed", async () => {
    await renderPaperDesk(state());
    expect(document.querySelector(".desk-fetch-report")).toBeNull();
  });
});

describe("benchmarks", () => {
  it("renders every benchmark the server sends, with its label", async () => {
    // The page showed SPY alone until round 5 measured that QQQ compounds roughly six points a year
    // faster over the decade and roughly halves every AI/semis book's edge against it. Showing one
    // number was showing the flattering one.
    await renderPaperDesk(
      state({
        benchmark: { symbol: "SPY", return_pct: "0.0117", label: "broad market" },
        benchmarks: [
          { symbol: "SPY", return_pct: "0.0117", label: "broad market" },
          { symbol: "QQQ", return_pct: "-0.0340", label: "Nasdaq-100" },
        ],
      }),
    );

    expect(screen.getByText("SPY (broad market)")).toBeTruthy();
    expect(screen.getByText("QQQ (Nasdaq-100)")).toBeTruthy();
    expect(screen.getByText("+1.17%")).toBeTruthy();
    expect(screen.getByText("-3.40%")).toBeTruthy();
  });

  it("falls back to the legacy single benchmark when the server sends no list", async () => {
    // A server predating `benchmarks` sends only `benchmark`. Rendering nothing would silently drop
    // the comparison the page exists to make.
    await renderPaperDesk(state({ benchmark: { symbol: "SPY", return_pct: "0.0123" } }));

    expect(screen.getByText("SPY benchmark")).toBeTruthy();
    expect(screen.getByText("+1.23%")).toBeTruthy();
  });
});

describe("a desk that has never traded", () => {
  it("is marked, and says a flat return means it did not participate", async () => {
    // Two of round 6's four selected cards held 100% cash and took zero trades for 55 straight
    // sessions, and the page rendered that identically to a card that traded to roughly flat. Round
    // 7's liveness gate reads exactly this condition; the screen now shows it.
    await renderPaperDesk(
      state({ desks: [desk({ holdings: [], trades: [], total_return: "0.0000" })] }),
    );

    expect(screen.getByText("no trades since inception")).toBeTruthy();
    expect(screen.getByText(/flat means no trade, not breakeven/)).toBeTruthy();
  });

  it("does not mark a desk that is in cash but has closed trades", async () => {
    // Sitting in cash *after* trading is an ordinary state, and often the strategy working. The
    // badge must separate "has done nothing at all" from "is flat right now", or it says nothing.
    const traded = desk({ holdings: [] });
    expect(traded.trades.length).toBeGreaterThan(0);

    await renderPaperDesk(state({ desks: [traded] }));

    expect(screen.queryByText("no trades since inception")).toBeNull();
  });
});

describe("a drawdown-ladder desk", () => {
  it("renders its own rules block instead of DeskRules, including the rung table", async () => {
    await renderPaperDesk(state({ desks: [ladderDesk(), cTrendDesk()] }));

    const panels = document.querySelectorAll(".desk-panel");
    const ladderPanel = Array.from(panels).find(
      (p) => p.querySelector(".desk-panel-title")?.textContent === "Drawdown Ladder - QLD/SCHD/IEF",
    ) as HTMLElement;
    expect(ladderPanel).toBeTruthy();

    // Open the collapsed "Book statistics" disclosure so its contents are queryable -- jsdom does
    // not evaluate CSS, but `<details>` still starts closed and React Testing Library queries
    // hidden content just fine either way; this documents that the ladder's own rules block lives in
    // the same place `DeskRules` normally would.
    const rulesSection = ladderPanel.querySelector(".desk-ladder-section") as HTMLElement;
    expect(rulesSection).not.toBeNull();

    // The ladder's own vocabulary is present...
    expect(within(rulesSection).getByText(/confirmation:/)).toBeTruthy();
    expect(within(rulesSection).getByText(/funding order:/)).toBeTruthy();
    expect(within(rulesSection).getByText(/recovery:/)).toBeTruthy();
    expect(rulesSection.textContent).toMatch(/SCHD/);
    expect(rulesSection.textContent).toMatch(/IEF/);
    expect(rulesSection.textContent).toMatch(/QLD/);

    // ...and a rules card's own vocabulary (entry/exit rule labels, max positions, position size) is
    // absent -- this is a different card shape, not a relabelled one.
    expect(within(rulesSection).queryByText(/^entry:/)).toBeNull();
    expect(within(rulesSection).queryByText(/^exit:/)).toBeNull();
    expect(within(rulesSection).queryByText(/max positions:/)).toBeNull();
    expect(within(rulesSection).queryByText(/position size:/)).toBeNull();

    // The rung table itself: three rungs, each drawdown paired with its own leveraged target.
    // Looked up on the panel, not inside `.desk-ladder-section`: the rungs are this card kind's
    // forward-looking block and now render in the card body, in the slot `UpcomingSignals` fills
    // for a rules desk -- the rules prose above stays inside the "Statistics & details" disclosure.
    const rungTable = ladderPanel.querySelector(".desk-ladder-rungs-table") as HTMLElement;
    expect(rungTable).not.toBeNull();
    const rungRows = within(rungTable).getAllByRole("row").slice(1); // drop the header row
    expect(rungRows).toHaveLength(3);
    expect(rungTable.textContent).toMatch(/-10\.00%/);
    expect(rungTable.textContent).toMatch(/20\.00%/);
    expect(rungTable.textContent).toMatch(/-30\.00%/);
    expect(rungTable.textContent).toMatch(/80\.00%/);
  });

  it("does not render the DeskRules entry/exit block for the ladder desk specifically", async () => {
    // A rules desk on the same page still gets its own DeskRules block -- only the ladder desk's
    // own panel must omit it.
    await renderPaperDesk(state({ desks: [ladderDesk(), cTrendDesk()] }));
    revealAllDesks(); // C-trend is not in the default visible set.

    const panels = Array.from(document.querySelectorAll(".desk-panel"));
    const ladderPanel = panels.find(
      (p) => p.querySelector(".desk-panel-title")?.textContent === "Drawdown Ladder - QLD/SCHD/IEF",
    ) as HTMLElement;
    const rulesPanel = panels.find(
      (p) => p.querySelector(".desk-panel-title")?.textContent === "C-trend",
    ) as HTMLElement;

    expect(ladderPanel.querySelector(".desk-rules-block")?.textContent).not.toMatch(/^entry:/m);
    expect(rulesPanel.querySelector(".desk-rules-block")?.textContent).toMatch(/entry:/);
  });

  it("keeps every kind-agnostic part of the page working: holdings, signals and open-positions count", async () => {
    await renderPaperDesk(state({ desks: [ladderDesk(), cTrendDesk()] }));

    const panels = Array.from(document.querySelectorAll(".desk-panel"));
    const ladderPanel = panels.find(
      (p) => p.querySelector(".desk-panel-title")?.textContent === "Drawdown Ladder - QLD/SCHD/IEF",
    ) as HTMLElement;

    // Holdings table renders both open sleeves with no null/max_positions crash anywhere on render.
    const holdingsTable = ladderPanel.querySelector(".desk-holdings-table") as HTMLElement;
    expect(within(holdingsTable).getByText("SCHD")).toBeTruthy();
    expect(within(holdingsTable).getByText("IEF")).toBeTruthy();

    // Signals cover every universe symbol, including the currently-unheld leveraged sleeve.
    const signalsTable = ladderPanel.querySelectorAll(".desk-signals-table")[0] as HTMLElement;
    const qldRow = within(signalsTable).getByText("QLD").closest("tr") as HTMLElement;
    expect(within(qldRow).getByText("Not held")).toBeTruthy();

    // `max_positions` is null for a ladder desk -- the tile falls back to the universe's own size
    // (3) rather than rendering a blank denominator.
    expect(ladderPanel.textContent).toMatch(/2 \/ 3/);
  });
});

describe("a kind === \"autopilot\" desk", () => {
  /** Finds the autopilot seat's own panel by its display name, the same lookup pattern the ladder
   *  describe block above uses -- title text is unambiguous where array position is not. */
  function autopilotPanel(): HTMLElement {
    return Array.from(document.querySelectorAll(".desk-panel")).find(
      (p) => p.querySelector(".desk-panel-title")?.textContent === "Agent Workflow - Autopilot",
    ) as HTMLElement;
  }

  it("is seated on first load -- no visibility click needed -- and renders its own provenance block instead of DeskRules", async () => {
    // `autopilot-workflow` is now in `DEFAULT_VISIBLE_AGENT_IDS`; this asserts the panel is on
    // screen from a plain `renderPaperDesk` call, with no `revealAllDesks()`.
    await renderPaperDesk(state({ desks: [desk(), cTrendDesk(), autopilotDesk()] }));

    const panel = autopilotPanel();
    expect(panel).toBeTruthy();

    const section = panel.querySelector(".desk-autopilot-section") as HTMLElement;
    expect(section).not.toBeNull();

    // The pair that identifies the book -- arm and universe source together, in the reader's words,
    // not the raw "screen" token -- plus the explicit "never by arm alone" framing.
    expect(section.textContent).toContain("full_workflow");
    expect(section.textContent).toMatch(/screened universe/);
    expect(section.textContent).toMatch(/never the arm alone/);

    // The card the regime call last selected, and its own inception -- explicitly not the desk's.
    expect(section.textContent).toContain("momentum-v2");
    expect(section.textContent).toContain("2026-08-01");
    expect(section.textContent).toMatch(/this seat's own inception, not the desk's/);

    // The four order counts, plus the note that they need not sum to the total.
    expect(section.textContent).toMatch(/5 total/);
    expect(section.textContent).toMatch(/3 filled/);
    expect(section.textContent).toMatch(/2 pending/);
    expect(section.textContent).toMatch(/0 rejected/);
    expect(section.textContent).toMatch(/need not sum to the total/);

    // The last run: id, state, when, and outcome.
    expect(section.textContent).toContain("run-2026-08-18-0900");
    expect(section.textContent).toContain("succeeded");
    // Through `formatInstant` -- readable, still UTC, microseconds trimmed. See the equivalent
    // assertion in `DeskPanel.test.tsx` for why the zone is deliberately not localised.
    expect(section.textContent).toContain("2026-08-18 13:05 UTC");
    expect(section.textContent).toContain("2 entry candidates fired");

    // Exits, stated in words -- never a bare "none".
    expect(section.textContent).toMatch(/only ever buys/);
    expect(section.textContent).not.toMatch(/exits:\s*none\s*$/m);

    // A link to the run detail on the Agent Workflow desk.
    const link = within(section).getByRole("link", { name: /run detail on the Agent Workflow desk/ });
    expect(link.getAttribute("href")).toBe("/agent-workflow");

    // DeskRules' own vocabulary (a rule this card genuinely does not have) is absent -- the same
    // discipline the ladder desk's own coverage above pins.
    expect(within(section).queryByText(/^entry:/)).toBeNull();
    expect(within(section).queryByText(/^exit:/)).toBeNull();
    expect(within(section).queryByText(/max positions:/)).toBeNull();
    expect(within(section).queryByText(/position size:/)).toBeNull();
  });

  it("renders the server's own exit-policy sentence when the seat has one, instead of the buy-only wording", async () => {
    // `exits` is no longer always the literal "none" -- the backend now derives it from the
    // selected card's actual rules. This is the "real policy" shape: a sentence naming the rules
    // in force, which the client must render as-is (never restate or re-derive) and must not be
    // shadowed by the "none" case's buy-only prose.
    await renderPaperDesk(
      state({
        desks: [
          desk(),
          cTrendDesk(),
          autopilotDesk({
            autopilot: autopilotDescription({
              exits: "12% stop, 120-session hold cap, and exit rule ema(20) crosses_below ema(50)",
            }),
          }),
        ],
      }),
    );

    const panel = autopilotPanel();
    const section = panel.querySelector(".desk-autopilot-section") as HTMLElement;
    expect(section).not.toBeNull();

    // The server's own sentence, verbatim, introduced as how this desk closes a position -- not
    // restated or re-derived client-side, and the "none" case's buy-only claim is gone.
    expect(section.textContent).toContain(
      "how this desk closes a position: 12% stop, 120-session hold cap, and exit rule ema(20) crosses_below ema(50)",
    );
    expect(section.textContent).not.toMatch(/only ever buys/);

    // Every other provenance field the "none"-shape test above covers still renders unchanged:
    // arm, universe source, card, adoption date, order counts, last run.
    expect(section.textContent).toContain("full_workflow");
    expect(section.textContent).toMatch(/screened universe/);
    expect(section.textContent).toMatch(/never the arm alone/);
    expect(section.textContent).toContain("momentum-v2");
    expect(section.textContent).toContain("2026-08-01");
    expect(section.textContent).toMatch(/this seat's own inception, not the desk's/);
    expect(section.textContent).toMatch(/5 total/);
    expect(section.textContent).toMatch(/3 filled/);
    expect(section.textContent).toMatch(/2 pending/);
    expect(section.textContent).toMatch(/0 rejected/);
    expect(section.textContent).toMatch(/need not sum to the total/);
    expect(section.textContent).toContain("run-2026-08-18-0900");
    expect(section.textContent).toContain("succeeded");
    expect(section.textContent).toContain("2026-08-18 13:05 UTC");
    expect(section.textContent).toContain("2 entry candidates fired");
  });

  it("gets an after-tax panel when its book is taxable, same as a rules desk", async () => {
    // `book()`'s default funding is `tax_treatment: "taxable"` (see the `funding` fixture), so this
    // desk carrying a real `tax` summary is exactly the case `taxedVisibleDesks` must widen for.
    await renderPaperDesk(
      state({ desks: [desk(), cTrendDesk(), autopilotDesk({ tax: paperTax() })] }),
    );

    const titles = Array.from(document.querySelectorAll(".desk-panel-title")).map(
      (t) => t.textContent,
    );
    expect(titles).toContain("Agent Workflow - Autopilot — after tax");

    const taxPanel = Array.from(document.querySelectorAll(".desk-panel")).find(
      (p) => p.querySelector(".desk-panel-title")?.textContent === "Agent Workflow - Autopilot — after tax",
    ) as HTMLElement;
    // "Tax owed" is unsigned (`formatMoney`); "After-tax realized gain" is signed (`formatSignedMoney`)
    // and this fixture's value is positive, so it carries an explicit "+" -- see that helper's own
    // accessibility-contract docstring in `api/portfolio.ts`.
    expect(within(taxPanel).getByText("$185.00")).toBeTruthy(); // tax_owed
    expect(within(taxPanel).getByText("+$315.00")).toBeTruthy(); // after_tax_realized_gain
  });

  it("is not required for the page to render -- a payload with no autopilot desk at all works exactly as before", async () => {
    // The regression guard: every other test in this file already exercises a payload with no
    // `kind === "autopilot"` desk, but this asserts it explicitly and checks that nothing autopilot-
    // specific leaks onto the page in that case.
    await renderPaperDesk(state());

    expect(document.querySelector(".desk-autopilot-section")).toBeNull();
    expect(screen.queryByRole("link", { name: /run detail on the Agent Workflow desk/ })).toBeNull();
    // The ordinary rules-desk panel still renders normally.
    expect(screen.getByText(/^Realized P&L$/)).toBeTruthy();
  });
});

describe("desk visibility chooser", () => {
  // A four-desk roster matching the live one after round 10: three of them (B-momentum, A-rotation,
  // ladder-qld-schd) are the owner's named default set (`DEFAULT_VISIBLE_AGENT_IDS`); C-trend is
  // the fourth, present on the roster but not in the defaults, standing in for "an agent the chooser
  // must still list even though it starts unticked". A-rotation is on that roster by owner override
  // rather than by round 10's rule (`data/rounds/r10-2026-08/SELECTION.md` section 7), which makes
  // no difference to the chooser -- it renders whatever the payload carries -- but explains why the
  // rule's own two-seat output and this four-desk fixture disagree.
  function fourDeskRoster() {
    return [desk(), aRotationDesk(), cTrendDesk(), ladderDesk()];
  }

  it("shows exactly the three named defaults on first render, with the fourth desk listed but hidden", async () => {
    await renderPaperDesk(state({ desks: fourDeskRoster() }));

    const titles = Array.from(document.querySelectorAll(".desk-panel-title")).map((t) => t.textContent);
    expect(titles).toEqual(["B-momentum", "A-rotation", "Drawdown Ladder - QLD/SCHD/IEF"]);
    expect(document.querySelectorAll(".desk-panel")).toHaveLength(3);

    // C-trend does not have a panel yet...
    expect(screen.queryByRole("checkbox", { name: "C-trend" })).toBeTruthy();
    // ...but its checkbox is present in the chooser, unticked, so it can be switched on.
    const cTrendCheckbox = screen.getByRole("checkbox", { name: "C-trend" }) as HTMLInputElement;
    expect(cTrendCheckbox.checked).toBe(false);

    // Every default's own checkbox is ticked.
    expect((screen.getByRole("checkbox", { name: "B-momentum" }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("checkbox", { name: "A-rotation" }) as HTMLInputElement).checked).toBe(true);
    expect(
      (screen.getByRole("checkbox", { name: "Drawdown Ladder - QLD/SCHD/IEF" }) as HTMLInputElement)
        .checked,
    ).toBe(true);
  });

  it("reveals a hidden desk's panel when its checkbox is ticked", async () => {
    await renderPaperDesk(state({ desks: fourDeskRoster() }));
    expect(document.querySelectorAll(".desk-panel")).toHaveLength(3);

    fireEvent.click(screen.getByRole("checkbox", { name: "C-trend" }));

    expect(document.querySelectorAll(".desk-panel")).toHaveLength(4);
    const titles = Array.from(document.querySelectorAll(".desk-panel-title")).map((t) => t.textContent);
    expect(titles).toContain("C-trend");
  });

  it("hides a visible desk's panel when its checkbox is unticked", async () => {
    await renderPaperDesk(state({ desks: fourDeskRoster() }));

    fireEvent.click(screen.getByRole("checkbox", { name: "B-momentum" }));

    expect(document.querySelectorAll(".desk-panel")).toHaveLength(2);
    const titles = Array.from(document.querySelectorAll(".desk-panel-title")).map((t) => t.textContent);
    expect(titles).not.toContain("B-momentum");
  });

  it("shows a designed empty state, not a blank area, when every desk is unticked", async () => {
    await renderPaperDesk(state({ desks: fourDeskRoster() }));

    fireEvent.click(screen.getByRole("checkbox", { name: "B-momentum" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "A-rotation" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Drawdown Ladder - QLD/SCHD/IEF" }));

    expect(document.querySelectorAll(".desk-panel")).toHaveLength(0);
    expect(screen.getByText(/No desks are selected/)).toBeTruthy();
    // Says how to get one back, not just that nothing is shown.
    expect(screen.getByText(/tick a desk above/i)).toBeTruthy();
    // The chooser itself stays on screen so the reader can act on that instruction.
    expect(document.querySelector(".desk-visibility-panel")).not.toBeNull();
  });

  it("does not crash when a default id names a desk the roster no longer carries", async () => {
    // The roster changes between selection rounds (see the module docstring) -- a default naming a
    // card that has been dropped (here, ladder-qld-schd is simply absent from the payload) must not
    // render an empty slot or throw, and the remaining two defaults still show normally.
    await renderPaperDesk(state({ desks: [desk(), aRotationDesk(), cTrendDesk()] }));

    const titles = Array.from(document.querySelectorAll(".desk-panel-title")).map((t) => t.textContent);
    expect(titles).toEqual(["B-momentum", "A-rotation"]);
    expect(document.querySelectorAll(".desk-panel")).toHaveLength(2);
    // No checkbox exists for the absent ladder desk.
    expect(screen.queryByRole("checkbox", { name: "Drawdown Ladder - QLD/SCHD/IEF" })).toBeNull();
    // C-trend is still listed in the chooser, unticked, same as any other non-default desk.
    expect((screen.getByRole("checkbox", { name: "C-trend" }) as HTMLInputElement).checked).toBe(false);
  });
});

describe("three books, one per purpose, shown one at a time via tabs", () => {
  const savings = (): Book =>
    book({
      purpose: "savings",
      label: "Savings",
      starting_cash: "20000.00",
      funding: funding({
        purpose: "savings",
        shape: "monthly_contribution",
        seed: "20000",
        contribution: "1000",
        horizon_years_min: 10,
        horizon_years_max: 20,
      }),
      benchmark: { symbol: "60-40-spy-agg", return_pct: "-0.0050", label: "60/40 SPY/AGG" },
      notes: ["This book is funded by contributions and the desk does not model them."],
      desks: [desk({ agent_id: "alloc-1", kind: "allocation" })],
    });

  // Trading is the default tab, so its own book is on screen without any interaction; reaching
  // another book's content means clicking its tab first -- see the "book tab rail" describe block
  // below for the coverage on the tabs themselves (labels, aria-selected, hide/show).
  it("shows the trading book by default, and a tab click swaps in the savings book's own figures", async () => {
    await renderPaperDesk(state({ books: [savings(), book()] }));

    expect(screen.getByRole("heading", { name: "Trading" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Savings" })).toBeNull();
    const tradingSection = screen.getByLabelText("Trading book");
    expect(within(tradingSection).getByText("$100,000.00")).toBeTruthy();

    fireEvent.click(screen.getByRole("tab", { name: "Savings" }));

    expect(screen.getByRole("heading", { name: "Savings" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Trading" })).toBeNull();
    const savingsSection = screen.getByLabelText("Savings book");
    expect(within(savingsSection).getByText("$20,000.00")).toBeTruthy();
    expect(within(savingsSection).getByText(/60\/40 SPY\/AGG/)).toBeTruthy();
  });

  it("renders a funded book that seats no cards, rather than hiding it", async () => {
    await renderPaperDesk(state({ books: [savings(), book({ desks: [] })] }));

    // Trading is still the default tab, so its (empty) book is what's on screen without any click.
    const tradingSection = screen.getByLabelText("Trading book");
    expect(within(tradingSection).getByText(/No cards are seated for this purpose yet/)).toBeTruthy();
    // The funding is still shown: an empty book is a funded book with no card, not a blank slot.
    // `getAllByText` because the opening capital appears both as its own stat and inside the
    // funding summary line -- one match would be as wrong as none.
    expect(within(tradingSection).getAllByText(/\$100,000\.00/).length).toBeGreaterThan(0);
  });

  it("shows an unbounded horizon as unbounded, never as a number, in each book's own tab", async () => {
    await renderPaperDesk(state({ books: [savings(), book()] }));

    // The trading purpose's horizon is deliberately unstated; encoding a large number that pretends
    // to be a bound would be worse than leaving it open.
    const tradingSection = screen.getByLabelText("Trading book");
    expect(within(tradingSection).getByText(/no fixed horizon/)).toBeTruthy();

    fireEvent.click(screen.getByRole("tab", { name: "Savings" }));

    const savingsSection = screen.getByLabelText("Savings book");
    expect(within(savingsSection).getByText(/10-20 years/)).toBeTruthy();
  });

  it("prints a book's own notes under that book and not the others", async () => {
    await renderPaperDesk(state({ books: [savings(), book()] }));

    fireEvent.click(screen.getByRole("tab", { name: "Savings" }));
    const savingsSection = screen.getByLabelText("Savings book");
    expect(
      within(savingsSection).getByText(/the desk does not model them/),
    ).toBeTruthy();

    // The contribution disclosure is true of two of the three purposes and would misdescribe the
    // third, which is funded exactly as shown.
    fireEvent.click(screen.getByRole("tab", { name: "Trading" }));
    const tradingSection = screen.getByLabelText("Trading book");
    expect(within(tradingSection).queryByText(/the desk does not model them/)).toBeNull();
  });
});

describe("book tab rail", () => {
  const savings = (): Book =>
    book({
      purpose: "savings",
      label: "Savings",
      starting_cash: "20000.00",
      funding: funding({
        purpose: "savings",
        shape: "monthly_contribution",
        seed: "20000",
        contribution: "1000",
        horizon_years_min: 10,
        horizon_years_max: 20,
      }),
      benchmark: { symbol: "60-40-spy-agg", return_pct: "-0.0050", label: "60/40 SPY/AGG" },
      // agent_id "A-rotation" is deliberately one of DEFAULT_VISIBLE_AGENT_IDS, so this desk's panel
      // renders the moment its book's tab is selected, with no extra checkbox click needed -- the
      // desk-visibility chooser's ticks are irrelevant to what this describe block is testing.
      desks: [desk({ agent_id: "A-rotation", kind: "allocation", display_name: "Savings Allocator" })],
    });

  // desks: [] on purpose -- a purpose can be funded before any card is designed for it, and that
  // book must still get a tab rather than being silently dropped from the rail.
  const roth = (): Book =>
    book({
      purpose: "roth",
      label: "Roth",
      starting_cash: "7000.00",
      funding: funding({
        purpose: "roth",
        shape: "annual_contribution",
        seed: "7000",
        contribution: "7000",
        horizon_years_min: 20,
        horizon_years_max: 40,
        tax_treatment: "roth",
      }),
      benchmark: { symbol: "SPY", return_pct: "0.0400" },
      desks: [],
    });

  it("renders all three book labels as tabs, with exactly one selected", async () => {
    await renderPaperDesk(state({ books: [savings(), book(), roth()] }));

    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Savings", "Trading", "Roth"]);

    const selected = tabs.filter((t) => t.getAttribute("aria-selected") === "true");
    expect(selected).toHaveLength(1);
    expect(selected[0]?.textContent).toBe("Trading");
  });

  it("renders the trading book's desks by default, and not the savings book's", async () => {
    await renderPaperDesk(state({ books: [savings(), book()] }));

    expect(screen.getByRole("heading", { name: "Trading" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Savings" })).toBeNull();
    // Scoped to the panel title specifically -- "B-momentum" also appears as a desk-visibility
    // checkbox label, which is not what this assertion is about.
    const panelTitles = Array.from(document.querySelectorAll(".desk-panel-title")).map(
      (t) => t.textContent,
    );
    expect(panelTitles).toContain("B-momentum");
    expect(panelTitles).not.toContain("Savings Allocator");
  });

  it("clicking the Savings tab shows that book's opening capital and desks, and hides trading's", async () => {
    await renderPaperDesk(state({ books: [savings(), book()] }));

    fireEvent.click(screen.getByRole("tab", { name: "Savings" }));

    const savingsSection = screen.getByLabelText("Savings book");
    expect(within(savingsSection).getByText("$20,000.00")).toBeTruthy();
    expect(
      within(savingsSection).getByText("Savings Allocator", { selector: ".desk-panel-title" }),
    ).toBeTruthy();
    expect(screen.queryByLabelText("Trading book")).toBeNull();
    const panelTitles = Array.from(document.querySelectorAll(".desk-panel-title")).map(
      (t) => t.textContent,
    );
    expect(panelTitles).not.toContain("B-momentum");
  });

  it("still shows a tab for a book with no desks, and selecting it shows the no-cards-seated placeholder", async () => {
    await renderPaperDesk(state({ books: [savings(), book(), roth()] }));

    expect(screen.getByRole("tab", { name: "Roth" })).toBeTruthy();

    fireEvent.click(screen.getByRole("tab", { name: "Roth" }));

    const rothSection = screen.getByLabelText("Roth book");
    expect(within(rothSection).getByText(/No cards are seated for this purpose yet/)).toBeTruthy();
  });

  it("moves aria-selected with the selection", async () => {
    await renderPaperDesk(state({ books: [savings(), book(), roth()] }));

    const tradingTab = screen.getByRole("tab", { name: "Trading" });
    const savingsTab = screen.getByRole("tab", { name: "Savings" });
    expect(tradingTab.getAttribute("aria-selected")).toBe("true");
    expect(savingsTab.getAttribute("aria-selected")).toBe("false");

    fireEvent.click(savingsTab);

    expect(savingsTab.getAttribute("aria-selected")).toBe("true");
    expect(tradingTab.getAttribute("aria-selected")).toBe("false");
  });
});

describe("the inception control", () => {
  /** The date input beside `DeskHeader`'s own Refresh button -- one text-labelled `Inception`
   *  field, bounded by `earliest_inception`/`latest_inception`. */
  function dateInput(): HTMLInputElement {
    return document.querySelector(".desk-inception-field input[type='date']") as HTMLInputElement;
  }

  function applyButton(): HTMLButtonElement {
    return screen.getByRole("button", { name: /^Apply$/ }) as HTMLButtonElement;
  }

  /** The confirm sheet's own Confirm button, scoped to the dialog -- `Confirm` alone would also
   *  match `interaction.confirm.confirm` used elsewhere, but only one `role="dialog"` is ever open
   *  at a time on this page. Awaits the dialog rather than assuming it is already committed to the
   *  DOM the instant `fireEvent.click` returns -- under a loaded test run the two can land a tick
   *  apart, and `findBy*`'s own retry is what a real click-then-look reader gets for free too. */
  async function confirmDialogConfirmButton(): Promise<HTMLButtonElement> {
    const dialog = await screen.findByRole("dialog");
    return within(dialog).getByRole("button", { name: /^Confirm$/ }) as HTMLButtonElement;
  }

  it("opens a confirm sheet on Apply and does not call setInception until Confirm is pressed", async () => {
    setInceptionMock.mockReturnValue(new Promise<PaperDeskState>(() => {})); // never resolves in this test
    await renderPaperDesk(state());

    fireEvent.change(dateInput(), { target: { value: "2025-01-15" } });
    fireEvent.click(applyButton());

    // The click alone must not have fired the mutation -- the whole point of the gate.
    expect(setInceptionMock).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toMatch(/2025-01-15/);

    fireEvent.click(await confirmDialogConfirmButton());

    expect(setInceptionMock).toHaveBeenCalledTimes(1);
    expect(setInceptionMock).toHaveBeenCalledWith("2025-01-15");
  });

  it("calls setInception with the new date once the confirm sheet is confirmed", async () => {
    setInceptionMock.mockReturnValue(new Promise<PaperDeskState>(() => {})); // never resolves in this test
    await renderPaperDesk(state());

    fireEvent.change(dateInput(), { target: { value: "2025-01-15" } });
    fireEvent.click(applyButton());
    fireEvent.click(await confirmDialogConfirmButton());

    expect(setInceptionMock).toHaveBeenCalledTimes(1);
    expect(setInceptionMock).toHaveBeenCalledWith("2025-01-15");
  });

  it("closes the confirm sheet on Cancel without ever calling setInception", async () => {
    await renderPaperDesk(state());

    fireEvent.change(dateInput(), { target: { value: "2025-01-15" } });
    fireEvent.click(applyButton());
    const dialog = await screen.findByRole("dialog");

    fireEvent.click(within(dialog).getByRole("button", { name: /^Cancel$/ }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(setInceptionMock).not.toHaveBeenCalled();
  });

  it("shows a success toast once the apply actually lands", async () => {
    setInceptionMock.mockResolvedValue(state({ inception: "2025-01-15" }));
    await renderPaperDesk(state());

    fireEvent.change(dateInput(), { target: { value: "2025-01-15" } });
    fireEvent.click(applyButton());
    fireEvent.click(await confirmDialogConfirmButton());

    expect(await screen.findByText(/2025-01-15/, { selector: ".toast-message" })).toBeTruthy();
  });

  it("bounds the date input by earliest_inception and latest_inception", async () => {
    await renderPaperDesk(
      state({ earliest_inception: "2019-03-04", latest_inception: "2026-08-10" }),
    );

    const input = dateInput();
    expect(input.min).toBe("2019-03-04");
    expect(input.max).toBe("2026-08-10");
  });

  it("disables Apply when the draft equals the current inception, and enables it once changed", async () => {
    await renderPaperDesk(state({ inception: "2026-08-01" }));

    // Untouched, the draft is seeded from the current inception -- Apply starts disabled.
    expect(applyButton().disabled).toBe(true);

    fireEvent.change(dateInput(), { target: { value: "2025-06-01" } });
    expect(applyButton().disabled).toBe(false);

    // Changed back to the original value, Apply is disabled again -- this is about the *value*
    // matching, not merely having been edited once.
    fireEvent.change(dateInput(), { target: { value: "2026-08-01" } });
    expect(applyButton().disabled).toBe(true);
  });

  it("does not show a reset control when inception_is_custom is false", async () => {
    await renderPaperDesk(state({ inception_is_custom: false }));
    expect(screen.queryByRole("button", { name: /Reset to default/ })).toBeNull();
  });

  it("shows the reset control when inception_is_custom is true, labelled with the default date, and calls resetInception", async () => {
    resetInceptionMock.mockResolvedValue(
      state({ inception: "2026-08-01", inception_is_custom: false }),
    );
    await renderPaperDesk(
      state({ inception: "2025-01-15", inception_default: "2026-08-01", inception_is_custom: true }),
    );

    const resetButton = screen.getByRole("button", { name: /Reset to default/ });
    expect(resetButton.textContent).toContain("2026-08-01");
    expect(resetButton.getAttribute("title")).toContain("2026-08-01");

    fireEvent.click(resetButton);
    expect(resetInceptionMock).toHaveBeenCalledTimes(1);
  });

  it("renders a 422's specific reason rather than a generic failure", async () => {
    setInceptionMock.mockRejectedValue(
      new ApiRequestError(422, "2019-01-01 is before the earliest stored benchmark bar"),
    );
    await renderPaperDesk(state());

    fireEvent.change(dateInput(), { target: { value: "2019-01-01" } });
    fireEvent.click(applyButton());
    fireEvent.click(await confirmDialogConfirmButton());

    const callout = await screen.findByText(/before the earliest stored benchmark bar/);
    expect(callout.closest(".desk-inception-error")).not.toBeNull();
    expect(callout.closest(".desk-inception-error")?.className).toContain("callout-danger");
  });

  it("shows a busy state on the whole desk while the request is in flight, and clears it after", async () => {
    let resolveApply!: (value: PaperDeskState) => void;
    setInceptionMock.mockReturnValue(
      new Promise<PaperDeskState>((resolve) => {
        resolveApply = resolve;
      }),
    );
    await renderPaperDesk(state({ inception: "2026-08-01" }));

    fireEvent.change(dateInput(), { target: { value: "2025-06-01" } });
    fireEvent.click(applyButton());
    fireEvent.click(await confirmDialogConfirmButton());

    // The control names what is happening and why it takes a moment.
    expect(await screen.findByText(/Re-running every agent from 2025-06-01/)).toBeTruthy();
    expect(document.querySelector(".desk-content-busy")).not.toBeNull();
    // Apply itself reflects the pending request and cannot be double-clicked. Looked up by class
    // rather than `applyButton()`'s accessible-name query -- the button's own name is now
    // "Applying…", not "Apply", which is exactly the state being asserted.
    const apply = document.querySelector(".desk-inception-apply") as HTMLButtonElement;
    expect(apply.disabled).toBe(true);
    expect(apply.textContent).toMatch(/Applying/);

    resolveApply(state({ inception: "2025-06-01" }));

    // Waits on the condition under test, not on a proxy for it.
    //
    // This previously did `await screen.findByText("2025-06-01")` and then asserted the busy class
    // synchronously -- which is a race, and it failed roughly one run in three. "2025-06-01" is
    // already in the document the moment the test types it into the date input, so that `findByText`
    // resolves on the *input's* value immediately, without waiting for React to flush the state
    // update that clears the busy flag. The assertion then ran a tick too early.
    //
    // Awaiting the disappearance directly removes the race rather than hiding it behind a longer
    // timeout, which would have left the same ordering bug in place and merely made it rarer.
    await waitFor(() => {
      expect(document.querySelector(".desk-content-busy")).toBeNull();
    });
    expect(screen.queryByText(/Re-running every agent from/)).toBeNull();
    // And the returned state actually landed: the desk now reports the new inception, so the input
    // matches it and Apply has disabled itself again (its "nothing to change" condition).
    expect(dateInput().value).toBe("2025-06-01");
    expect(applyButton().disabled).toBe(true);
  });

  it("states plainly that Apply re-runs every agent and does not fetch new data or reseat strategies", async () => {
    await renderPaperDesk(state());

    const hint = document.querySelector(".desk-inception-hint");
    expect(hint).not.toBeNull();
    expect(hint?.textContent).toMatch(/re-runs every agent/i);
    expect(hint?.textContent).toMatch(/fetches no data/i);
    expect(hint?.textContent).toMatch(/doesn.t change seated strategies/i);
  });
});

describe("the in-sample warning", () => {
  it("renders when in_sample_sessions is greater than zero, naming the count and the design cutoff", async () => {
    await renderPaperDesk(state({ in_sample_sessions: 27, design_cutoff: "2026-06-15" }));

    const callout = document.querySelector(".desk-insample-callout");
    expect(callout).not.toBeNull();
    expect(callout?.className).toContain("callout-warn");
    expect(callout?.textContent).toMatch(/27/);
    expect(callout?.textContent).toMatch(/2026-06-15/);
    expect(callout?.textContent).toMatch(/fitted, not forward/i);
  });

  it("is absent when in_sample_sessions is zero", async () => {
    await renderPaperDesk(state({ in_sample_sessions: 0 }));
    expect(document.querySelector(".desk-insample-callout")).toBeNull();
  });

  it("does not print the same design-cutoff sentence twice when the backend's own note repeats it", async () => {
    // The backend adds a note to `PaperDeskState.notes` naming the same fact this page's dedicated
    // callout states. Rendering both verbatim would duplicate the sentence on screen.
    await renderPaperDesk(
      state({
        in_sample_sessions: 12,
        design_cutoff: "2026-05-01",
        notes: [
          "12 of this window's sessions fall at or before the strategy design cutoff (2026-05-01).",
        ],
      }),
    );

    // Counted over the flattened page text rather than `getAllByText` -- the phrase is split across
    // sibling text/expression nodes inside a `<strong>`, and `getAllByText` would separately match
    // both that node and its containing `<div>`, over-counting a single rendered sentence.
    const body = document.body.textContent ?? "";
    const occurrences = (body.match(/design cutoff/gi) ?? []).length;
    expect(occurrences).toBe(1);
    // The one treatment that does survive is the dedicated callout, not the generic notes list.
    expect(document.querySelector(".desk-insample-callout")?.textContent).toMatch(/design cutoff/i);
    expect(document.querySelector(".desk-notes-list")?.textContent ?? "").not.toMatch(/design cutoff/i);
  });
});


describe("the funding summary line joins its two money figures", () => {
  /* Found in a browser pass, not by a test -- which is the point of adding these.
   *
   * `fundingSummary` built the monthly branch as `then $X every month` and the annual branch as
   * `$X once a year`, with no joining word. Rendered after the opening capital that produced
   * "$30,000.00 $7,500.00 once a year" on the Roth book: two money figures butted together with
   * nothing between them, which reads as one malformed number rather than as a contribution
   * schedule. Every existing funding assertion matched on `/funding order:/` or on the money values
   * individually, so all three shapes rendered and none of them checked how the sentence read. */

  const bookWith = (over: Partial<Funding>, cash: string): Book =>
    book({
      purpose: over.purpose ?? "trading",
      label: over.purpose === "roth" ? "Roth IRA" : over.purpose === "savings" ? "Savings" : "Trading",
      starting_cash: cash,
      funding: funding({ seed: cash, ...over }),
      desks: [],
    });

  it("says 'then' before an annual contribution", async () => {
    await renderPaperDesk(state({ books: [
      bookWith(
        {
          purpose: "roth",
          shape: "annual_contribution",
          contribution: "7500",
          tax_treatment: "roth_ira",
        },
        "30000.00",
      ),
    ] }));

    expect(
      await screen.findByText("$30,000.00 then $7,500.00 once a year - no fixed horizon - roth ira"),
    ).toBeTruthy();
  });

  it("says 'then' before a monthly contribution", async () => {
    await renderPaperDesk(state({ books: [
      bookWith(
        {
          purpose: "savings",
          shape: "monthly_contribution",
          contribution: "1000",
          horizon_years_min: 10,
          horizon_years_max: 20,
        },
        "20000.00",
      ),
    ] }));

    expect(
      await screen.findByText("$20,000.00 then $1,000.00 every month - 10-20 years - taxable"),
    ).toBeTruthy();
  });

  it("says no such thing for a lump sum, which has no second figure", async () => {
    await renderPaperDesk(state({ books: [bookWith({ shape: "lump_sum", contribution: "0" }, "100000.00")] }));

    const line = await screen.findByText(/once, with no additions/);
    expect(line.textContent).toBe("$100,000.00 once, with no additions - no fixed horizon - taxable");
    expect(line.textContent).not.toContain("then");
  });
});

describe("influencer paper books", () => {
  /** Mirrors `PersonaBookCard.test.tsx`'s own fixture shape -- this describe block is about the
   *  section wiring (fetch, phases, one card per book), not about `PersonaBookCard`'s own
   *  rendering, which already has full coverage of its own. */
  function personaHolding(overrides: Partial<PersonaHolding> = {}): PersonaHolding {
    return {
      symbol: "NVDA",
      stance: "bullish",
      note_id: "note-1",
      entry_date: "2026-08-01",
      entry_price: "1234.50",
      quantity: "10",
      cost_basis: "12345.00",
      last_price: "1300.75",
      last_price_date: "2026-09-01",
      market_value: "13000.75",
      unrealised_pnl: "600.00",
      return_pct: "0.1000",
      bars_held: 20,
      weight: 0.5,
      last_bullish_on: "2026-02-01",
      ...overrides,
    };
  }

  function personaBook(overrides: Partial<PersonaBook> = {}): PersonaBook {
    const holdings = overrides.holdings ?? [personaHolding()];
    return {
      persona: "creator-a",
      display_name: "Creator A",
      inception: "2026-01-01",
      as_of: "2026-09-01",
      starting_cash: "100000.00",
      notional_per_position: "10000.00",
      cash: "40000.00",
      equity: "100000.00",
      holdings,
      cost_basis_total: "12345.00",
      market_value_total: "20500.25",
      unrealised_pnl_total: "1250.00",
      realised_pnl_total: "0.00",
      return_pct: "0.0000",
      trade_count: 0,
      open_count: holdings.length,
      trades: [],
      skipped: [],
      warnings: [],
      ...overrides,
    };
  }

  it("renders a card per fetched persona book", async () => {
    personaBooksMock.mockResolvedValue([
      personaBook({ persona: "creator-a", display_name: "Creator A" }),
      personaBook({ persona: "other-persona", display_name: "Other Persona", holdings: [] }),
    ]);
    await renderPaperDesk(state());

    expect(await screen.findByText(/Creator A.*paper book/)).toBeTruthy();
    expect(await screen.findByText(/Other Persona.*paper book/)).toBeTruthy();
    expect(document.querySelectorAll(".persona-book-card").length).toBe(2);
  });

  it("renders the empty note, not an error, when the collection is empty", async () => {
    personaBooksMock.mockResolvedValue([]);
    await renderPaperDesk(state());

    expect(await screen.findByText(/No persona paper books yet/)).toBeTruthy();
    expect(document.querySelectorAll(".persona-book-card").length).toBe(0);
  });

  it("does not blank the rest of the desk when the persona books fetch fails", async () => {
    personaBooksMock.mockRejectedValue(new Error("network down"));
    await renderPaperDesk(state());

    // The failure is confined to its own section...
    expect(
      await screen.findByText(/Could not load persona paper books right now/),
    ).toBeTruthy();
    // ...while the rest of the loaded desk -- reached via `renderPaperDesk`'s own wait -- is still
    // fully rendered: the desk header, its panels, and the page-level framing note.
    expect(document.querySelectorAll(".desk-panel").length).toBeGreaterThan(0);
    expect(document.querySelector(".desk-framing-note")).not.toBeNull();
  });

  it("shows a loading placeholder before the fetch resolves", async () => {
    let resolveBooks!: (books: PersonaBook[]) => void;
    personaBooksMock.mockReturnValue(
      new Promise<PersonaBook[]>((resolve) => {
        resolveBooks = resolve;
      }),
    );
    await renderPaperDesk(state());

    expect(screen.getByText(/Loading persona paper books/)).toBeTruthy();
    resolveBooks([personaBook()]);
    expect(await screen.findByText(/Creator A.*paper book/)).toBeTruthy();
  });
});

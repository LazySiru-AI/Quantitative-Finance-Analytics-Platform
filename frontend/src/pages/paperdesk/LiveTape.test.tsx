/**
 * The Live Tape's own honesty rules, at render level -- matching the vocabulary
 * `PaperDesk.test.tsx` establishes for the rest of this page.
 *
 * The pure tagging/placement/action derivation logic (`deriveLiveTapeSymbols`,
 * `filterLiveTapeSymbols`, and friends) lives in `./liveTapeModel` and is unit-tested independent of
 * rendering in `liveTapeModel.test.ts` -- this file does not duplicate those assertions. What this
 * file pins is what actually reaches the screen:
 *
 *  - a held symbol, a signalled symbol, and a symbol traded in the most recent session all appear,
 *    each carrying a badge naming both the tag AND the book it earned it in ("Held · Trading"), never
 *    a bare tag name -- and a symbol two books both touch renders one badge per (tag, book) pair;
 *  - a symbol that is none of the three (not held, no signal fired/blocked, not in the most recent
 *    traded session) does NOT appear;
 *  - the account/status checkbox filter bar renders one checkbox per book present (in `BOOK_ORDER`
 *    order) and one per status tag; by default (owner decision, 2026-09-09) only Trading is checked
 *    among accounts and only Held + Signal among statuses -- falling back to every book when no
 *    trading book is present -- and toggling one narrows which rows, badges, and actions render,
 *    and re-subscribes to the reduced symbol set;
 *  - a `live_fills` entry and a firing-signal-with-no-fill both render as an action line ("Sell
 *    $286.42 × 12" / "Buy $141.03"), a blocked-only signal renders no action line at all, and a null
 *    `last_close` renders `—`, never `$0.00`;
 *  - the empty state renders a real message when nothing qualifies, and a *different* real message
 *    when rows exist but the current filters admit none of them;
 *  - an unrecognised `market_state` string renders without throwing -- `market_state` is an open
 *    string on the wire (see `@/api/paperlive`'s module docstring), and this page must never assume
 *    it already knows the whole set, the same lesson `paperdesk.ts`'s `exitReasonLabel` docstring
 *    records for `rebalance_trim` taking the rest of this page down once already;
 *  - `subscribe` is stubbed at the module boundary (`@/api/paperlive`), matching this app's test
 *    idiom -- these tests are about rendering the tape's derived rows and the pushed snapshot, not
 *    about the transport itself (SSE vs. polling is `paperlive.test.ts`'s job, and that suite proves
 *    the polling fallback engages when `EventSource` is absent -- true unconditionally in this
 *    project's jsdom test environment).
 */
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type {
  Book,
  Desk,
  Funding,
  Holding,
  LiveFill,
  PaperDeskState,
  Signal,
  Trade,
} from "@/api/paperdesk";
import type { PaperLiveQuotes } from "@/api/paperlive";

// ---------------------------------------------------------------------------
// Stub @/api/paperlive at the module boundary. `subscribe` is captured so a test can push a
// snapshot through it exactly as the real transport would, without this file caring whether that
// snapshot arrived over SSE or a poll tick.
// ---------------------------------------------------------------------------

type QuotesHandler = (data: PaperLiveQuotes) => void;
type ErrorHandler = (error: unknown) => void;

let lastOnQuotes: QuotesHandler | null = null;
let lastOnError: ErrorHandler | null = null;
let lastSymbols: string[] | null = null;
const unsubscribeMock = vi.fn();
const subscribeMock = vi.fn(
  (symbols: string[], onQuotes: QuotesHandler, onError: ErrorHandler, _pollIntervalMs?: number) => {
    lastSymbols = symbols;
    lastOnQuotes = onQuotes;
    lastOnError = onError;
    return unsubscribeMock;
  },
);

vi.mock("@/api/paperlive", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/paperlive")>();
  return {
    ...actual,
    subscribe: (...args: Parameters<typeof actual.subscribe>) => subscribeMock(...args),
  };
});

const { default: LiveTape } = await import("@/pages/paperdesk/LiveTape");

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function holding(overrides: Partial<Holding> = {}): Holding {
  return {
    symbol: "AAPL",
    quantity: "50",
    entry_date: "2026-08-01",
    entry_price: "300.00",
    cost_basis: "15000.00",
    last_price: "319.70",
    last_price_date: "2026-08-18",
    market_value: "15985.00",
    unrealised_pnl: "985.00",
    return_pct: "0.0657",
    bars_held: 12,
    weight: 0.2,
    stop_price: null,
    target_price: null,
    sessions_to_time_stop: null,
    ...overrides,
  };
}

function signal(overrides: Partial<Signal> = {}): Signal {
  return {
    symbol: "AAPL",
    held: true,
    entry_fires: false,
    exit_fires: false,
    last_close: "319.70",
    blocked: null,
    rank_value: null,
    entry_rank: null,
    ...overrides,
  };
}

function trade(overrides: Partial<Trade> = {}): Trade {
  return {
    symbol: "GOOG",
    entry_date: "2026-08-10",
    entry_price: "170.00",
    exit_date: "2026-08-18",
    exit_price: "180.00",
    quantity: "10",
    exit_reason: "rule",
    pnl: "100.00",
    return_pct: "0.0588",
    bars_held: 6,
    ...overrides,
  };
}

/** A live-priced fill, keyed off the exact figures the task's own DOM contract uses ($286.42 × 12)
 *  so a test that overrides nothing still exercises the pinned example verbatim. */
function liveFill(overrides: Partial<LiveFill> = {}): LiveFill {
  return {
    symbol: "AAPL",
    side: "sell",
    quantity: "12",
    price: "286.42",
    quote_price: "286.50",
    quote_ts: "2026-08-28T20:00:01Z",
    notional: "3437.04",
    ...overrides,
  };
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

function desk(overrides: Partial<Desk> = {}): Desk {
  return {
    agent_id: "momentum",
    display_name: "Momentum",
    discipline: "momentum",
    thesis: "Ride established uptrends.",
    kind: "rules",
    universe: ["AAPL"],
    entry: "close > sma(200)",
    exit: "close < sma(200)",
    rank_by: null,
    stop_loss_pct: null,
    take_profit_pct: null,
    max_hold_days: null,
    max_positions: 6,
    position_pct: "0.15",
    ladder: null,
    starting_equity: "100000.00",
    cash: "84000.00",
    positions_value: "15985.00",
    equity: "99985.00",
    total_return: "-0.0001",
    excess_return: "-0.0001",
    max_drawdown: "0.02",
    capital_exposure: 0.16,
    realised_pnl: "0.00",
    unrealised_pnl: "985.00",
    open_positions: 1,
    slots_free: 5,
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
    benchmark: { symbol: "SPY", return_pct: "0.01" },
    notes: [],
    desks: [desk()],
    ...overrides,
  };
}

function state(overrides: Partial<PaperDeskState> = {}): PaperDeskState {
  return {
    inception: "2026-08-01",
    inception_default: "2026-08-01",
    inception_is_custom: false,
    design_cutoff: "2026-06-01",
    in_sample_sessions: 0,
    earliest_inception: "2020-01-02",
    latest_inception: "2026-08-15",
    as_of: "2026-08-18",
    latest_bar: "2026-08-18",
    stale_days: 0,
    first_session: "2026-08-03",
    sessions: 12,
    notes: [],
    books: [book()],
    ...overrides,
  };
}

function quoteFor(symbol: string, overrides: Partial<PaperLiveQuotes["quotes"][number]> = {}) {
  return {
    symbol,
    price: "319.70",
    previous_close: "309.35",
    change: "10.35",
    change_pct: "3.3457",
    ts: "2026-08-28T20:00:01Z",
    stale: false,
    source: "yahoo",
    ...overrides,
  };
}

function snapshot(overrides: Partial<PaperLiveQuotes> = {}): PaperLiveQuotes {
  return {
    as_of: "2026-08-30T06:51:44Z",
    market_state: "POST",
    transport: "poll",
    healthy: true,
    quotes: [],
    errors: [],
    ...overrides,
  };
}

/**
 * Matches an element whose OWN full text content equals `text` exactly -- e.g. a tag badge whose
 * visible text is split across a parent text node ("Held") and a child `<span>` (" · Trading"), so a
 * plain string match against either node alone would never find "Held · Trading" as a whole, and
 * would also never accidentally match on the bare "Held" half a test wants to prove is NOT what
 * renders.
 *
 * Paired with `{ selector }` at every call site (`tagBadge`/`actionLine` below) rather than used
 * bare: `getByText`'s default matcher walks every element in the tree, and a badge (or action line)
 * that is its parent's only child leaves the parent's own `textContent` identical to the child's --
 * an unscoped match against "Held · Trading" hits both the `.live-tape-tag` span AND the
 * `.live-tape-tags` wrapper around it and throws "multiple elements". The `selector` option filters
 * candidates to the one class that actually identifies "this is a badge" (or "this is an action
 * line") before the text matcher ever runs, so only the intended node is a candidate.
 */
function exactText(text: string) {
  return (_content: string, element: Element | null) => element?.textContent === text;
}

/** A tag badge (`.live-tape-tag`) whose full text is exactly `text`, e.g. `"Held · Trading"`. */
function tagBadge(text: string) {
  return screen.getByText(exactText(text), { selector: ".live-tape-tag" });
}

/** `null` when no `.live-tape-tag` badge has full text exactly `text`. */
function queryTagBadge(text: string) {
  return screen.queryByText(exactText(text), { selector: ".live-tape-tag" });
}

/** An action line (`.live-tape-action`) whose full text is exactly `text`, e.g. `"Sell $286.42 × 12"`. */
function actionLine(text: string) {
  return screen.getByText(exactText(text), { selector: ".live-tape-action" });
}

/**
 * The `.live-tape-row` containing `symbol`'s own symbol span -- for scoping a badge lookup to one
 * row when two different rows can legitimately carry an identically-worded badge (e.g. two symbols
 * both "Held · Trading"). `tagBadge`/`queryTagBadge` search the whole document and throw/return
 * ambiguously in that case; `within(rowFor(symbol))` narrows the search to the one row a test means.
 */
function rowFor(symbol: string): HTMLElement {
  const symbolEl = screen.getByText(symbol, { selector: ".live-tape-symbol" });
  const row = symbolEl.closest(".live-tape-row");
  if (!row) throw new Error(`no .live-tape-row ancestor for symbol "${symbol}"`);
  return row as HTMLElement;
}

/** `tagBadge`, scoped to one row -- see `rowFor`. */
function tagBadgeIn(row: HTMLElement, text: string) {
  return within(row).getByText(exactText(text), { selector: ".live-tape-tag" });
}

/** `queryTagBadge`, scoped to one row -- see `rowFor`. */
function queryTagBadgeIn(row: HTMLElement, text: string) {
  return within(row).queryByText(exactText(text), { selector: ".live-tape-tag" });
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

describe("LiveTape", () => {
  it("renders a held, a signalled, and a traded symbol, each badge naming its tag AND its book, and omits a quiet symbol", async () => {
    const user = userEvent.setup();
    const d = desk({
      display_name: "Momentum",
      holdings: [holding({ symbol: "AAPL" })],
      signals: [
        signal({ symbol: "AAPL", held: true }),
        signal({ symbol: "TSLA", held: false, entry_fires: true }),
        signal({ symbol: "MSFT", held: false, entry_fires: false, exit_fires: false, blocked: null }),
      ],
      trades: [trade({ symbol: "GOOG", exit_date: "2026-08-18" })],
    });
    render(<LiveTape state={state({ books: [book({ desks: [d] })] })} />);

    // "Traded" is off by default (owner default, 2026-09-09): GOOG qualifies only through TRADED, so
    // it is hidden until the reader asks for it -- one click away, never gone.
    expect(screen.queryByText("GOOG")).toBeNull();
    await user.click(screen.getByRole("checkbox", { name: "Traded" }));

    expect(screen.getByText("AAPL")).toBeTruthy();
    expect(screen.getByText("TSLA")).toBeTruthy();
    expect(screen.getByText("GOOG")).toBeTruthy();
    expect(screen.queryByText("MSFT")).toBeNull();

    // The whole point of the tag rework: a badge names the book it earned the tag in, never a bare
    // tag name on its own.
    expect(tagBadge("Held · Trading")).toBeTruthy();
    expect(tagBadge("Signal · Trading")).toBeTruthy();
    expect(tagBadge("Traded · Trading")).toBeTruthy();
    expect(queryTagBadge("Held")).toBeNull();
    expect(queryTagBadge("Signal")).toBeNull();
    expect(queryTagBadge("Traded")).toBeNull();
  });

  it("renders two badges naming both books when a symbol is held in two different books", async () => {
    const user = userEvent.setup();
    const trading = book({
      purpose: "trading",
      label: "Trading",
      desks: [desk({ display_name: "Desk A", holdings: [holding({ symbol: "AAPL" })] })],
    });
    const savings = book({
      purpose: "savings",
      label: "Savings",
      funding: funding({ purpose: "savings" }),
      desks: [desk({ display_name: "Desk B", holdings: [holding({ symbol: "AAPL" })] })],
    });
    render(<LiveTape state={state({ books: [trading, savings] })} />);
    // Savings is unchecked by default (owner default: Trading only) -- opt it in to see both badges.
    await user.click(screen.getByRole("checkbox", { name: "Savings" }));

    // One row, not two -- the symbol still dedupes -- carrying one badge per (tag, book) pair.
    expect(screen.getAllByText("AAPL")).toHaveLength(1);
    expect(tagBadge("Held · Trading")).toBeTruthy();
    expect(tagBadge("Held · Savings")).toBeTruthy();
  });

  it("renders one account checkbox per book present, in BOOK_ORDER order, and one per status tag -- Trading, Held and Signal checked initially, the rest not", () => {
    const savings = book({
      purpose: "savings",
      label: "Savings",
      funding: funding({ purpose: "savings" }),
      desks: [desk({ display_name: "Desk S", holdings: [holding({ symbol: "BND" })] })],
    });
    const trading = book({
      purpose: "trading",
      label: "Trading",
      desks: [desk({ display_name: "Desk T", holdings: [holding({ symbol: "AAPL" })] })],
    });
    const roth = book({
      purpose: "roth",
      label: "Roth IRA",
      funding: funding({ purpose: "roth" }),
      desks: [desk({ display_name: "Desk R", holdings: [holding({ symbol: "VTI" })] })],
    });
    // Deliberately out of BOOK_ORDER in `books` to prove the checkbox list follows BOOK_ORDER, not
    // array position.
    render(<LiveTape state={state({ books: [roth, trading, savings] })} />);

    const accountsGroup = screen.getByRole("group", { name: "Accounts" });
    const accountBoxes = within(accountsGroup).getAllByRole("checkbox") as HTMLInputElement[];
    expect(accountBoxes.map((cb) => cb.closest("label")?.textContent?.trim())).toEqual([
      "Savings",
      "Trading",
      "Roth IRA",
    ]);
    // Owner default (2026-09-09): the trading book alone starts checked.
    expect(accountBoxes.map((cb) => cb.checked)).toEqual([false, true, false]);

    const statusGroup = screen.getByRole("group", { name: "Status" });
    const statusBoxes = within(statusGroup).getAllByRole("checkbox") as HTMLInputElement[];
    expect(statusBoxes.map((cb) => cb.closest("label")?.textContent?.trim())).toEqual([
      "Held",
      "Signal",
      "Traded",
    ]);
    // Owner default (2026-09-09): Held and Signal start checked; Traded does not.
    expect(statusBoxes.map((cb) => cb.checked)).toEqual([true, true, false]);
  });

  it("falls back to every book checked when no trading book is present -- a default must never start by hiding everything", () => {
    const savings = book({
      purpose: "savings",
      label: "Savings",
      funding: funding({ purpose: "savings" }),
      desks: [desk({ display_name: "Desk S", holdings: [holding({ symbol: "BND" })] })],
    });
    const roth = book({
      purpose: "roth",
      label: "Roth IRA",
      funding: funding({ purpose: "roth" }),
      desks: [desk({ display_name: "Desk R", holdings: [holding({ symbol: "VTI" })] })],
    });
    render(<LiveTape state={state({ books: [savings, roth] })} />);

    const accountsGroup = screen.getByRole("group", { name: "Accounts" });
    const accountBoxes = within(accountsGroup).getAllByRole("checkbox") as HTMLInputElement[];
    expect(accountBoxes.map((cb) => cb.checked)).toEqual([true, true]);
    expect(screen.getByText("BND")).toBeTruthy();
    expect(screen.getByText("VTI")).toBeTruthy();
  });

  it("unchecking an account hides rows whose only placements are in that account, and hides that account's badges on rows that survive via another account", async () => {
    const user = userEvent.setup();
    const trading = book({
      purpose: "trading",
      label: "Trading",
      desks: [
        desk({
          display_name: "Desk A",
          holdings: [holding({ symbol: "AAPL" }), holding({ symbol: "MSFT" })],
        }),
      ],
    });
    const savings = book({
      purpose: "savings",
      label: "Savings",
      funding: funding({ purpose: "savings" }),
      desks: [
        desk({
          display_name: "Desk S",
          holdings: [holding({ symbol: "MSFT" }), holding({ symbol: "GOOG" })],
        }),
      ],
    });
    render(<LiveTape state={state({ books: [trading, savings] })} />);
    // Savings starts unchecked (owner default: Trading only). Opt it in first, so the toggle-OFF
    // behaviour this test is about is exercised from a state where Savings rows are visible.
    await user.click(screen.getByRole("checkbox", { name: "Savings" }));

    expect(screen.getByText("AAPL")).toBeTruthy();
    expect(screen.getByText("GOOG")).toBeTruthy();
    // Two different rows legitimately carry an identically-worded "Held · Trading" badge (AAPL and
    // MSFT) -- scope each lookup to its own row via `rowFor` rather than searching the whole document.
    expect(tagBadgeIn(rowFor("AAPL"), "Held · Trading")).toBeTruthy();
    expect(tagBadgeIn(rowFor("MSFT"), "Held · Trading")).toBeTruthy();
    expect(tagBadgeIn(rowFor("MSFT"), "Held · Savings")).toBeTruthy();
    expect(tagBadgeIn(rowFor("GOOG"), "Held · Savings")).toBeTruthy();

    await user.click(screen.getByRole("checkbox", { name: "Savings" }));

    // GOOG's only placement was Savings -- the whole row disappears.
    expect(screen.queryByText("GOOG")).toBeNull();
    // AAPL survives via its Trading placement, untouched.
    expect(screen.getByText("AAPL")).toBeTruthy();
    expect(tagBadgeIn(rowFor("AAPL"), "Held · Trading")).toBeTruthy();
    // MSFT survives via its Trading placement, but its Savings badge is gone.
    expect(screen.getByText("MSFT")).toBeTruthy();
    expect(tagBadgeIn(rowFor("MSFT"), "Held · Trading")).toBeTruthy();
    expect(queryTagBadgeIn(rowFor("MSFT"), "Held · Savings")).toBeNull();
  });

  it("unchecking a status tag hides rows whose only placements carry that tag, and hides that tag's badge on rows that survive via another tag", async () => {
    const user = userEvent.setup();
    const d = desk({
      display_name: "Desk A",
      holdings: [holding({ symbol: "AAPL" })],
      signals: [
        signal({ symbol: "AAPL", held: true, entry_fires: true, exit_fires: false, last_close: "320.00" }),
        signal({ symbol: "TSLA", held: false, entry_fires: true, exit_fires: false, last_close: "250.00" }),
      ],
    });
    render(<LiveTape state={state({ books: [book({ desks: [d] })] })} />);

    expect(screen.getByText("TSLA")).toBeTruthy();
    // AAPL's and TSLA's rows both carry a "Signal · Trading" badge -- scope each lookup to its own
    // row via `rowFor` rather than searching the whole document.
    expect(tagBadgeIn(rowFor("AAPL"), "Held · Trading")).toBeTruthy();
    expect(tagBadgeIn(rowFor("AAPL"), "Signal · Trading")).toBeTruthy();
    expect(tagBadgeIn(rowFor("TSLA"), "Signal · Trading")).toBeTruthy();

    await user.click(screen.getByRole("checkbox", { name: "Signal" }));

    // TSLA's only placement was SIGNAL -- the whole row disappears.
    expect(screen.queryByText("TSLA")).toBeNull();
    // AAPL survives via its HELD placement, untouched.
    expect(screen.getByText("AAPL")).toBeTruthy();
    expect(tagBadgeIn(rowFor("AAPL"), "Held · Trading")).toBeTruthy();
    // No "Signal · Trading" badge remains anywhere -- AAPL's is hidden, TSLA's row is gone. This
    // check is safely unscoped: an absence check is unambiguous regardless of how many rows there
    // are, unlike the presence checks above.
    expect(queryTagBadge("Signal · Trading")).toBeNull();
  });

  it("renders the filtered-empty placeholder, with its exact text, once every account checkbox is unchecked -- distinct from the genuinely-empty placeholder", async () => {
    const user = userEvent.setup();
    const d = desk({ holdings: [holding({ symbol: "AAPL" })] });
    render(<LiveTape state={state({ books: [book({ desks: [d] })] })} />);

    expect(screen.getByText("AAPL")).toBeTruthy();
    await user.click(screen.getByRole("checkbox", { name: "Trading" }));

    expect(
      screen.getByText("No symbol matches the current account and status filters."),
    ).toBeTruthy();
    // `rows.length` is still 1 here -- only `filteredRows.length` is 0 -- so the genuinely-empty
    // placeholder's own text must not appear.
    expect(screen.queryByText(/nothing is in play right now/i)).toBeNull();
  });

  it("renders the real empty-state message when nothing qualifies, not a blank panel", () => {
    render(<LiveTape state={state({ books: [book({ desks: [desk()] })] })} />);
    expect(
      screen.getByText(/no symbol is currently held, signalling, or was traded/i),
    ).toBeTruthy();
    expect(subscribeMock).not.toHaveBeenCalled();
  });

  it("renders a live_fills entry as 'Sell $286.42 × 12' with the desk and book named in its title", () => {
    const d = desk({
      display_name: "Desk A",
      holdings: [holding({ symbol: "AAPL" })],
      live_fills: [liveFill({ symbol: "AAPL", side: "sell", price: "286.42", quantity: "12" })],
    });
    render(<LiveTape state={state({ books: [book({ desks: [d] })] })} />);

    const action = actionLine("Sell $286.42 × 12");
    expect(action).toBeTruthy();
    expect(action.getAttribute("title")).toBe("Desk A — Trading");
  });

  it("renders a firing signal with no matching fill as 'Buy $141.03', title noting it is not yet filled, and no quantity part", () => {
    const d = desk({
      display_name: "Desk B",
      signals: [
        signal({ symbol: "MSFT", held: false, entry_fires: true, exit_fires: false, last_close: "141.03" }),
      ],
    });
    render(<LiveTape state={state({ books: [book({ desks: [d] })] })} />);

    const action = actionLine("Buy $141.03");
    expect(action).toBeTruthy();
    expect(action.getAttribute("title")).toBe("Desk B — Trading (signal, not yet filled)");
  });

  it("renders a blocked-only signal as a Signal badge with zero action lines", () => {
    const d = desk({
      signals: [
        signal({
          symbol: "XLE",
          held: false,
          entry_fires: false,
          exit_fires: false,
          blocked: "insufficient cash",
          last_close: "50.00",
        }),
      ],
    });
    const { container } = render(<LiveTape state={state({ books: [book({ desks: [d] })] })} />);

    expect(tagBadge("Signal · Trading")).toBeTruthy();
    // No accessible name distinguishes one action line from another (or from none) -- counting is
    // the only question here, so a class-name query is the right tool per this file's own guidance.
    expect(container.querySelectorAll(".live-tape-action")).toHaveLength(0);
  });

  it("renders a null last_close as '—', never '$0.00'", () => {
    const d = desk({
      signals: [
        signal({ symbol: "NFLX", held: false, entry_fires: true, exit_fires: false, last_close: null }),
      ],
    });
    render(<LiveTape state={state({ books: [book({ desks: [d] })] })} />);

    expect(actionLine("Buy —")).toBeTruthy();
    expect(screen.queryByText(/\$0\.00/)).toBeNull();
  });

  it("subscribes to exactly the derived symbol set, not the desk's full universe", () => {
    const d = desk({
      universe: ["AAPL", "TSLA", "MSFT", "GOOG"],
      holdings: [holding({ symbol: "AAPL" })],
      signals: [signal({ symbol: "AAPL", held: true })],
    });
    render(<LiveTape state={state({ books: [book({ desks: [d] })] })} />);
    expect(lastSymbols).toEqual(["AAPL"]);
  });

  it("re-subscribes to the reduced symbol set when an account filter is toggled off", async () => {
    const user = userEvent.setup();
    const trading = book({
      purpose: "trading",
      label: "Trading",
      desks: [desk({ display_name: "Desk T", holdings: [holding({ symbol: "AAPL" })] })],
    });
    const savings = book({
      purpose: "savings",
      label: "Savings",
      funding: funding({ purpose: "savings" }),
      desks: [desk({ display_name: "Desk S", holdings: [holding({ symbol: "MSFT" })] })],
    });
    render(<LiveTape state={state({ books: [trading, savings] })} />);

    // Default is Trading only, so the initial subscription already excludes the Savings symbol.
    expect(lastSymbols).toEqual(["AAPL"]);

    await user.click(screen.getByRole("checkbox", { name: "Savings" }));
    expect(lastSymbols).toEqual(["AAPL", "MSFT"]);

    await user.click(screen.getByRole("checkbox", { name: "Savings" }));
    expect(lastSymbols).toEqual(["AAPL"]);
  });

  it("renders a pushed quote's price, change and change_pct once subscribe delivers a snapshot", () => {
    const d = desk({ holdings: [holding({ symbol: "AAPL" })] });
    render(<LiveTape state={state({ books: [book({ desks: [d] })] })} />);

    expect(lastOnQuotes).not.toBeNull();
    act(() => {
      lastOnQuotes?.(snapshot({ quotes: [quoteFor("AAPL")] }));
    });

    expect(screen.getByText("319.70")).toBeTruthy();
    expect(screen.getByText(/3\.3457/)).toBeTruthy();
    expect(screen.getByText(/\+\$10\.35/)).toBeTruthy();
  });

  it("shows a stale badge only when the pushed quote says stale: true", () => {
    const d = desk({ holdings: [holding({ symbol: "AAPL" })] });
    render(<LiveTape state={state({ books: [book({ desks: [d] })] })} />);
    act(() => {
      lastOnQuotes?.(snapshot({ quotes: [quoteFor("AAPL", { stale: true })] }));
    });
    expect(screen.getByText("stale")).toBeTruthy();
  });

  it("shows the unhealthy warning only when the pushed snapshot says healthy: false", () => {
    const d = desk({ holdings: [holding({ symbol: "AAPL" })] });
    render(<LiveTape state={state({ books: [book({ desks: [d] })] })} />);
    act(() => {
      lastOnQuotes?.(snapshot({ healthy: false, quotes: [quoteFor("AAPL")] }));
    });
    expect(screen.getByRole("alert").textContent).toMatch(/unhealthy/i);
  });

  it("renders market_state and transport as whatever open string the server sent, without crashing", () => {
    const d = desk({ holdings: [holding({ symbol: "AAPL" })] });
    render(<LiveTape state={state({ books: [book({ desks: [d] })] })} />);

    expect(() =>
      act(() => {
        lastOnQuotes?.(
          snapshot({ market_state: "SOME_FUTURE_STATE", transport: "some_future_transport" }),
        );
      }),
    ).not.toThrow();

    expect(screen.getByText("SOME_FUTURE_STATE")).toBeTruthy();
    expect(screen.getByText(/some_future_transport/)).toBeTruthy();
  });

  it("surfaces a per-symbol error from the snapshot instead of leaving the row blank", () => {
    const d = desk({ holdings: [holding({ symbol: "AAPL" })] });
    render(<LiveTape state={state({ books: [book({ desks: [d] })] })} />);
    act(() => {
      lastOnQuotes?.(snapshot({ quotes: [], errors: [{ symbol: "AAPL", message: "not found" }] }));
    });
    expect(screen.getByText("not found")).toBeTruthy();
  });

  it("surfaces a subscribe-level error (e.g. every poll failing) as a visible callout", () => {
    const d = desk({ holdings: [holding({ symbol: "AAPL" })] });
    render(<LiveTape state={state({ books: [book({ desks: [d] })] })} />);
    expect(lastOnError).not.toBeNull();
    act(() => {
      lastOnError?.(new Error("provider unreachable"));
    });
    expect(screen.getByText("provider unreachable")).toBeTruthy();
  });

  it("unsubscribes on unmount", () => {
    const d = desk({ holdings: [holding({ symbol: "AAPL" })] });
    const { unmount } = render(<LiveTape state={state({ books: [book({ desks: [d] })] })} />);
    expect(unsubscribeMock).not.toHaveBeenCalled();
    unmount();
    expect(unsubscribeMock).toHaveBeenCalledTimes(1);
  });
});

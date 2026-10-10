/**
 * Unit tests for `liveTapeModel.ts` -- the Live Tape's pure derivation logic, tested without
 * rendering anything. Fixture builders are copied from `LiveTape.test.tsx` rather than imported from
 * it (that file is owned by a different agent editing it concurrently) -- kept in sync by hand where
 * the two suites overlap.
 *
 * Ports every assertion from `LiveTape.test.tsx`'s `describe("deriveLiveTapeSymbols", ...)` block so
 * no coverage is lost in the split, then adds coverage for what's new here: per-book placements,
 * `LiveFill.side` normalisation and the unrecognised-side skip, blocked-only signals producing a
 * placement but no action, fill-beats-signal dedupe, action sort order, and `filterLiveTapeSymbols`.
 */
import { describe, expect, it } from "vitest";

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

import {
  BOOK_ORDER,
  deriveLiveTapeSymbols,
  filterLiveTapeSymbols,
  signalIsRaised,
  TAG_LABEL,
  TAG_ORDER,
  type LiveTapeSymbol,
  type LiveTapeTag,
} from "./liveTapeModel";

// ---------------------------------------------------------------------------
// Fixtures -- copied from LiveTape.test.tsx, extended with live_fills/purpose/label as needed.
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

function liveFill(overrides: Partial<LiveFill> = {}): LiveFill {
  return {
    symbol: "AAPL",
    side: "buy",
    quantity: "10",
    price: "320.10",
    quote_price: "320.00",
    quote_ts: "2026-08-30T14:00:00Z",
    notional: "3201.00",
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

function placementsFor(rows: LiveTapeSymbol[], symbol: string) {
  return rows.find((r) => r.symbol === symbol)?.placements ?? [];
}

// ---------------------------------------------------------------------------
// Ported from LiveTape.test.tsx's describe("deriveLiveTapeSymbols", ...)
// ---------------------------------------------------------------------------

describe("deriveLiveTapeSymbols -- ported coverage", () => {
  it("tags a held symbol HELD, a firing/blocked signal SIGNAL, and a most-recent-session trade TRADED", () => {
    const deskA = desk({
      display_name: "Momentum",
      holdings: [holding({ symbol: "AAPL" })],
      signals: [
        signal({ symbol: "AAPL", held: true }), // not itself "raised" -- HELD only, via holdings
        signal({ symbol: "TSLA", held: false, entry_fires: true }), // SIGNAL
        signal({ symbol: "MSFT", held: false, entry_fires: false, exit_fires: false, blocked: null }), // quiet -- must not appear
      ],
      trades: [trade({ symbol: "GOOG", exit_date: "2026-08-18" })],
    });
    const s = state({ books: [book({ desks: [deskA] })] });

    const rows = deriveLiveTapeSymbols(s);
    const bySymbol = new Map(rows.map((r) => [r.symbol, r]));

    expect(bySymbol.get("AAPL")?.tags).toEqual(["HELD"]);
    expect(bySymbol.get("TSLA")?.tags).toEqual(["SIGNAL"]);
    expect(bySymbol.get("GOOG")?.tags).toEqual(["TRADED"]);
    expect(bySymbol.has("MSFT")).toBe(false);
  });

  it("tags a blocked (but not firing) signal SIGNAL too -- blocked is still something raised", () => {
    const d = desk({
      signals: [signal({ symbol: "XLE", held: false, entry_fires: false, exit_fires: false, blocked: "insufficient cash" })],
    });
    const rows = deriveLiveTapeSymbols(state({ books: [book({ desks: [d] })] }));
    expect(rows.map((r) => r.symbol)).toContain("XLE");
    expect(rows.find((r) => r.symbol === "XLE")?.tags).toEqual(["SIGNAL"]);
  });

  it("only tags TRADED for the most recent session date present in the state, not every closed trade", () => {
    const d = desk({
      trades: [
        trade({ symbol: "GOOG", exit_date: "2026-08-18" }),
        trade({ symbol: "NFLX", exit_date: "2026-08-10" }), // older session -- must not be TRADED
      ],
    });
    const rows = deriveLiveTapeSymbols(state({ books: [book({ desks: [d] })] }));
    expect(rows.map((r) => r.symbol)).toContain("GOOG");
    expect(rows.map((r) => r.symbol)).not.toContain("NFLX");
  });

  it("dedupes a symbol two desks both touch into one row carrying every tag and every desk name", () => {
    const deskA = desk({
      agent_id: "momentum",
      display_name: "Momentum",
      holdings: [holding({ symbol: "AAPL" })],
      signals: [],
    });
    const deskB = desk({
      agent_id: "rotation",
      display_name: "Rotation",
      holdings: [],
      signals: [signal({ symbol: "AAPL", held: false, blocked: "insufficient cash" })],
    });
    const rows = deriveLiveTapeSymbols(state({ books: [book({ desks: [deskA, deskB] })] }));

    expect(rows).toHaveLength(1);
    expect(rows[0]?.symbol).toBe("AAPL");
    expect(rows[0]?.tags).toEqual(["HELD", "SIGNAL"]);
    expect(rows[0]?.deskNames).toEqual(["Momentum", "Rotation"]);
  });

  it("returns no rows when nothing on the desk qualifies", () => {
    const rows = deriveLiveTapeSymbols(state({ books: [book({ desks: [desk()] })] }));
    expect(rows).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// signalIsRaised -- now a public export.
// ---------------------------------------------------------------------------

describe("signalIsRaised", () => {
  it("is true when entry_fires, exit_fires, or blocked is set, false when the signal is quiet", () => {
    expect(signalIsRaised(signal({ entry_fires: true }))).toBe(true);
    expect(signalIsRaised(signal({ exit_fires: true }))).toBe(true);
    expect(signalIsRaised(signal({ blocked: "book full" }))).toBe(true);
    expect(signalIsRaised(signal({ entry_fires: false, exit_fires: false, blocked: null }))).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// TAG_ORDER / TAG_LABEL / BOOK_ORDER -- the constants three other shards code against by name.
// ---------------------------------------------------------------------------

describe("constants", () => {
  it("TAG_ORDER and TAG_LABEL cover HELD/SIGNAL/TRADED", () => {
    expect(TAG_ORDER).toEqual(["HELD", "SIGNAL", "TRADED"]);
    const labelled: LiveTapeTag[] = ["HELD", "SIGNAL", "TRADED"];
    for (const tag of labelled) expect(typeof TAG_LABEL[tag]).toBe("string");
  });

  it("BOOK_ORDER covers savings/trading/roth", () => {
    expect(BOOK_ORDER).toEqual(["savings", "trading", "roth"]);
  });
});

// ---------------------------------------------------------------------------
// Per-book placements
// ---------------------------------------------------------------------------

describe("deriveLiveTapeSymbols -- placements", () => {
  it("gives a symbol held in two books two HELD placements, each with the right book label and desk names", () => {
    const savingsBook = book({
      purpose: "savings",
      label: "Savings",
      desks: [desk({ display_name: "Savings Momentum", holdings: [holding({ symbol: "AAPL" })] })],
    });
    const tradingBook = book({
      purpose: "trading",
      label: "Trading",
      desks: [desk({ display_name: "Trading Momentum", holdings: [holding({ symbol: "AAPL" })] })],
    });

    const rows = deriveLiveTapeSymbols(state({ books: [savingsBook, tradingBook] }));
    const aapl = rows.find((r) => r.symbol === "AAPL");
    expect(aapl?.tags).toEqual(["HELD"]);
    expect(aapl?.purposes).toEqual(["savings", "trading"]);

    const placements = aapl?.placements ?? [];
    expect(placements).toHaveLength(2);
    expect(placements[0]).toMatchObject({ tag: "HELD", purpose: "savings", bookLabel: "Savings", deskNames: ["Savings Momentum"] });
    expect(placements[1]).toMatchObject({ tag: "HELD", purpose: "trading", bookLabel: "Trading", deskNames: ["Trading Momentum"] });
  });

  it("orders placements by TAG_ORDER then BOOK_ORDER regardless of book/desk iteration order", () => {
    const rothBook = book({
      purpose: "roth",
      label: "Roth IRA",
      desks: [desk({ display_name: "Roth Desk", signals: [signal({ symbol: "AAPL", held: false, entry_fires: true })] })],
    });
    const savingsBook = book({
      purpose: "savings",
      label: "Savings",
      desks: [desk({ display_name: "Savings Desk", holdings: [holding({ symbol: "AAPL" })] })],
    });
    // Books deliberately passed roth-then-savings to prove sort order does not follow input order.
    const rows = deriveLiveTapeSymbols(state({ books: [rothBook, savingsBook] }));
    const placements = placementsFor(rows, "AAPL");

    expect(placements.map((p) => `${p.tag}:${p.purpose}`)).toEqual(["HELD:savings", "SIGNAL:roth"]);
  });

  it("two desks in the same book earning the same tag merge into one placement with both desk names", () => {
    const b = book({
      desks: [
        desk({ display_name: "Momentum", holdings: [holding({ symbol: "AAPL" })] }),
        desk({ display_name: "Rotation", holdings: [holding({ symbol: "AAPL" })] }),
      ],
    });
    const rows = deriveLiveTapeSymbols(state({ books: [b] }));
    const placements = placementsFor(rows, "AAPL");
    expect(placements).toHaveLength(1);
    expect(placements[0]?.deskNames).toEqual(["Momentum", "Rotation"]);
  });
});

// ---------------------------------------------------------------------------
// Actions -- fills, signals, unrecognised sides, blocked-only, dedupe, sort order.
// ---------------------------------------------------------------------------

describe("deriveLiveTapeSymbols -- actions", () => {
  it("produces a buy action from a signal's entry_fires and a sell action from exit_fires", () => {
    const d = desk({
      display_name: "Momentum",
      signals: [
        signal({ symbol: "TSLA", held: false, entry_fires: true, last_close: "250.00" }),
        signal({ symbol: "AAPL", held: true, exit_fires: true, last_close: "319.70" }),
      ],
    });
    const rows = deriveLiveTapeSymbols(state({ books: [book({ desks: [d] })] }));

    const tsla = rows.find((r) => r.symbol === "TSLA");
    expect(tsla?.actions).toEqual([
      { side: "buy", price: "250.00", quantity: null, purpose: "trading", bookLabel: "Trading", deskName: "Momentum", source: "signal" },
    ]);

    const aapl = rows.find((r) => r.symbol === "AAPL");
    expect(aapl?.actions).toEqual([
      { side: "sell", price: "319.70", quantity: null, purpose: "trading", bookLabel: "Trading", deskName: "Momentum", source: "signal" },
    ]);
  });

  it("a signal that fires both ways emits both a sell and a buy action", () => {
    const d = desk({
      display_name: "Momentum",
      signals: [signal({ symbol: "AAPL", held: true, entry_fires: true, exit_fires: true, last_close: "319.70" })],
    });
    const rows = deriveLiveTapeSymbols(state({ books: [book({ desks: [d] })] }));
    const aapl = rows.find((r) => r.symbol === "AAPL");
    expect(aapl?.actions.map((a) => a.side)).toEqual(["sell", "buy"]);
  });

  it("a blocked-only signal earns a SIGNAL placement but emits no action", () => {
    const d = desk({
      display_name: "Momentum",
      signals: [signal({ symbol: "XLE", held: false, entry_fires: false, exit_fires: false, blocked: "insufficient cash" })],
    });
    const rows = deriveLiveTapeSymbols(state({ books: [book({ desks: [d] })] }));
    const xle = rows.find((r) => r.symbol === "XLE");
    expect(xle?.tags).toEqual(["SIGNAL"]);
    expect(xle?.actions).toEqual([]);
  });

  it("a live fill produces a fill action with its real price/quantity", () => {
    const d = desk({
      display_name: "Momentum",
      live_fills: [liveFill({ symbol: "AAPL", side: "buy", price: "320.10", quantity: "10" })],
    });
    const rows = deriveLiveTapeSymbols(state({ books: [book({ desks: [d] })] }));
    const aapl = rows.find((r) => r.symbol === "AAPL");
    expect(aapl?.actions).toEqual([
      { side: "buy", price: "320.10", quantity: "10", purpose: "trading", bookLabel: "Trading", deskName: "Momentum", source: "fill" },
    ]);
  });

  it("normalises fill side case/whitespace, and skips an unrecognised side without throwing", () => {
    const d = desk({
      display_name: "Momentum",
      live_fills: [
        liveFill({ symbol: "AAPL", side: "  SELL  " }),
        liveFill({ symbol: "MSFT", side: "short" }), // unrecognised -- must be skipped, not thrown
      ],
    });

    let rows: LiveTapeSymbol[] = [];
    expect(() => {
      rows = deriveLiveTapeSymbols(state({ books: [book({ desks: [d] })] }));
    }).not.toThrow();

    const aapl = rows.find((r) => r.symbol === "AAPL");
    expect(aapl?.actions).toEqual([
      expect.objectContaining({ side: "sell", source: "fill" }),
    ]);

    const msft = rows.find((r) => r.symbol === "MSFT");
    expect(msft).toBeUndefined(); // no holding/signal/trade for it either -- an unrecognised-side fill alone earns no row
  });

  it("drops the signal-sourced action when a fill already covers the same symbol/desk/side", () => {
    const d = desk({
      display_name: "Momentum",
      signals: [signal({ symbol: "AAPL", held: false, entry_fires: true, last_close: "319.70" })],
      live_fills: [liveFill({ symbol: "AAPL", side: "buy", price: "320.10", quantity: "10" })],
    });
    const rows = deriveLiveTapeSymbols(state({ books: [book({ desks: [d] })] }));
    const aapl = rows.find((r) => r.symbol === "AAPL");
    // Only the fill action survives -- the signal's buy for the same (symbol, desk, side) is dropped.
    expect(aapl?.actions).toEqual([
      expect.objectContaining({ source: "fill", side: "buy", price: "320.10" }),
    ]);
  });

  it("keeps the signal action when the fill is for a different desk or a different side", () => {
    const deskA = desk({
      display_name: "Momentum",
      signals: [signal({ symbol: "AAPL", held: false, entry_fires: true, last_close: "319.70" })],
    });
    const deskB = desk({
      agent_id: "rotation",
      display_name: "Rotation",
      live_fills: [liveFill({ symbol: "AAPL", side: "buy", price: "320.10" })],
    });
    const rows = deriveLiveTapeSymbols(state({ books: [book({ desks: [deskA, deskB] })] }));
    const aapl = rows.find((r) => r.symbol === "AAPL");
    expect(aapl?.actions).toHaveLength(2);
    expect(aapl?.actions.some((a) => a.source === "signal" && a.deskName === "Momentum")).toBe(true);
    expect(aapl?.actions.some((a) => a.source === "fill" && a.deskName === "Rotation")).toBe(true);
  });

  it("sorts actions sells-before-buys, then fill-before-signal, then deskName", () => {
    const d = desk({
      display_name: "Zulu", // deliberately late alphabetically to prove sort isn't accidental
      signals: [
        signal({ symbol: "AAPL", held: false, entry_fires: true, last_close: "1" }),
        signal({ symbol: "AAPL", held: false, exit_fires: true, last_close: "2" }),
      ],
      live_fills: [
        liveFill({ symbol: "AAPL", side: "sell", price: "3" }),
      ],
    });
    const alpha = desk({
      agent_id: "alpha",
      display_name: "Alpha",
      signals: [signal({ symbol: "AAPL", held: false, entry_fires: true, last_close: "4" })],
    });
    const rows = deriveLiveTapeSymbols(state({ books: [book({ desks: [d, alpha] })] }));
    const aapl = rows.find((r) => r.symbol === "AAPL");

    // Expect: sell/fill(Zulu), sell/signal is deduped away by the fill on the same desk+side,
    // buy/signal(Alpha), buy/signal(Zulu) -- sells first, then buys ordered fill-before-signal then
    // by desk name.
    expect(aapl?.actions.map((a) => `${a.side}:${a.source}:${a.deskName}`)).toEqual([
      "sell:fill:Zulu",
      "buy:signal:Alpha",
      "buy:signal:Zulu",
    ]);
  });
});

// ---------------------------------------------------------------------------
// filterLiveTapeSymbols
// ---------------------------------------------------------------------------

describe("filterLiveTapeSymbols", () => {
  function twoBookRows(): LiveTapeSymbol[] {
    const savingsBook = book({
      purpose: "savings",
      label: "Savings",
      desks: [desk({ display_name: "Savings Desk", holdings: [holding({ symbol: "AAPL" })] })],
    });
    const tradingBook = book({
      purpose: "trading",
      label: "Trading",
      desks: [desk({ display_name: "Trading Desk", signals: [signal({ symbol: "TSLA", held: false, entry_fires: true })] })],
    });
    return deriveLiveTapeSymbols(state({ books: [savingsBook, tradingBook] }));
  }

  it("returns everything when every tag and every purpose is selected", () => {
    const rows = twoBookRows();
    const filtered = filterLiveTapeSymbols(rows, new Set(TAG_ORDER), new Set(BOOK_ORDER));
    expect(filtered.map((r) => r.symbol)).toEqual(["AAPL", "TSLA"]);
  });

  it("returns [] when tags is empty, even with every purpose selected", () => {
    const rows = twoBookRows();
    const filtered = filterLiveTapeSymbols(rows, new Set(), new Set(BOOK_ORDER));
    expect(filtered).toEqual([]);
  });

  it("returns [] when purposes is empty, even with every tag selected", () => {
    const rows = twoBookRows();
    const filtered = filterLiveTapeSymbols(rows, new Set(TAG_ORDER), new Set());
    expect(filtered).toEqual([]);
  });

  it("a partial account (purpose) selection keeps only rows placed in that book", () => {
    const rows = twoBookRows();
    const filtered = filterLiveTapeSymbols(rows, new Set(TAG_ORDER), new Set(["savings"]));
    expect(filtered.map((r) => r.symbol)).toEqual(["AAPL"]);
  });

  it("a tag selection keeps only rows with a matching placement's tag", () => {
    const rows = twoBookRows();
    const filtered = filterLiveTapeSymbols(rows, new Set(["SIGNAL"]), new Set(BOOK_ORDER));
    expect(filtered.map((r) => r.symbol)).toEqual(["TSLA"]);
  });

  it("preserves input row order and returns row objects unmodified (placements not pruned to the matching subset)", () => {
    const rows = twoBookRows(); // AAPL, TSLA in that order (symbol.localeCompare)
    const filtered = filterLiveTapeSymbols(rows, new Set(["HELD"]), new Set(["savings", "trading"]));
    expect(filtered).toHaveLength(1);
    expect(filtered[0]).toBe(rows[0]); // same object reference, not a rebuilt row
    expect(filtered[0]?.placements).toEqual(rows[0]?.placements);
  });
});

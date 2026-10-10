/**
 * `PersonaBookCard` -- the persona cash-constrained paper book card.
 *
 * What this pins, matching the task's definition of done:
 *  - `return_pct` on the wire is a 0-1 FRACTION (`"0.0642"`), never a whole percent. The historical
 *    bug rendered a fraction as if it were already a percent (multiplying by 100 a second time),
 *    producing "+6427%" for a real +6.42% return. This suite asserts the fraction renders as
 *    "+6.42%" and never as "+642%" or "+6427%" -- proving the fix, not merely the happy path;
 *  - the tile row renders equity, cash, unrealised P&L, realised P&L and return, each toned/signed
 *    through the `@/api/paperdesk` helpers rather than a raw wire string;
 *  - a closed trade renders with its reason spelled out in words, never the raw enum;
 *  - a skipped call renders with its symbol, date and reason;
 *  - an empty `trades`/`skipped` list hides that whole section rather than rendering an empty table;
 *  - `warnings` always render, independent of every other section;
 *  - the paper-projection / not-advice caveat is always visible.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import type { PersonaBook, PersonaHolding, PersonaSkippedCall, PersonaTrade } from "@/api/personas";

import PersonaBookCard from "./PersonaBookCard";

afterEach(cleanup);

function holding(overrides: Partial<PersonaHolding> = {}): PersonaHolding {
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
    return_pct: "0.0300",
    bars_held: 20,
    weight: 0.5,
    last_bullish_on: "2026-08-28",
    ...overrides,
  };
}

function trade(overrides: Partial<PersonaTrade> = {}): PersonaTrade {
  return {
    symbol: "TSLA",
    note_id: "note-2",
    entry_date: "2026-06-01",
    entry_price: "200.00",
    exit_date: "2026-07-15",
    exit_price: "180.00",
    quantity: "50",
    realised_pnl: "-1000.00",
    return_pct: "-0.1000",
    reason: "flip_bearish",
    ...overrides,
  };
}

function skipped(overrides: Partial<PersonaSkippedCall> = {}): PersonaSkippedCall {
  return {
    symbol: "AAPL",
    said_on: "2026-08-15",
    reason: "no_market_data",
    ...overrides,
  };
}

function book(overrides: Partial<PersonaBook> = {}): PersonaBook {
  return {
    persona: "creator-a",
    display_name: "Creator A",
    inception: "2026-01-01",
    as_of: "2026-09-01",
    starting_cash: "100000.00",
    notional_per_position: "10000.00",
    cash: "79499.75",
    equity: "92500.50",
    holdings: [holding()],
    cost_basis_total: "12345.00",
    market_value_total: "13000.75",
    unrealised_pnl_total: "600.00",
    realised_pnl_total: "-1000.00",
    return_pct: "0.0642",
    trade_count: 1,
    open_count: 1,
    trades: [],
    skipped: [],
    warnings: [],
    ...overrides,
  };
}

function renderCard(b: PersonaBook) {
  return render(
    <MemoryRouter>
      <PersonaBookCard book={b} />
    </MemoryRouter>,
  );
}

describe("tiles", () => {
  it("renders equity, cash, unrealised P&L and realised P&L through the money helpers", () => {
    renderCard(book());
    expect(screen.getByText("$92,500.50")).toBeTruthy(); // equity
    expect(screen.getByText("$79,499.75")).toBeTruthy(); // cash
    // Unrealised P&L tile and the holding's own unrealised P&L cell both legitimately show
    // "+$600.00" for this fixture (one holding, whose figure equals the book total).
    expect(screen.getAllByText("+$600.00").length).toBeGreaterThan(0);
    expect(screen.getByText("-$1,000.00")).toBeTruthy(); // realised P&L, signed (no trades yet in this fixture)
  });

  it("renders a fraction return_pct as a correctly-scaled percent, not the historical x100 bug", () => {
    renderCard(book({ return_pct: "0.0642" }));
    // The bug: a fraction re-treated as an already-a-percent value renders "+642%" (x100 once too
    // many) or, compounded further, "+6427%". Neither must ever appear.
    expect(screen.getByText("+6.42%")).toBeTruthy();
    expect(screen.queryByText("+642.00%")).toBeNull();
    expect(screen.queryByText("+6427%")).toBeNull();
    expect(screen.queryByText(/\+6427/)).toBeNull();
  });

  it("formats a holding's own return_pct fraction to 2dp as well", () => {
    renderCard(book({ holdings: [holding({ return_pct: "0.0300" })] }));
    expect(screen.getByText("+3.00%")).toBeTruthy();
    expect(screen.queryByText("0.0300")).toBeNull();
  });
});

describe("holdings", () => {
  it("renders a row per holding, formatted through the paperdesk helpers", () => {
    renderCard(book());
    expect(screen.getByText("NVDA")).toBeTruthy();
    expect(screen.getByText("bullish", { selector: ".persona-ticker-stance" })).toBeTruthy();
    expect(screen.getByText("$1,234.50")).toBeTruthy();
    expect(screen.queryByText("1234.50")).toBeNull();
  });

  it("links each symbol to its ticker page", () => {
    renderCard(book());
    const links = screen.getAllByRole("link", { name: /NVDA/i });
    expect(links[0]?.getAttribute("href")).toBe("/symbol/NVDA");
  });

  it("shows 'No open positions' (not an error) for an empty holdings list, section still present", () => {
    renderCard(book({ holdings: [], as_of: null }));
    expect(screen.getByText(/no open positions/i)).toBeTruthy();
    expect(screen.getByText(/holdings/i)).toBeTruthy();
  });
});

describe("closed trades", () => {
  it("renders a closed trade with its reason spelled out in words", () => {
    renderCard(book({ trades: [trade({ reason: "flip_bearish" })] }));
    expect(screen.getByText("TSLA")).toBeTruthy();
    expect(screen.getByText(/turned bearish/i)).toBeTruthy();
    // The trade's own realised P&L and the book-level realised P&L tile both legitimately show
    // "-$1,000.00" for this fixture (one trade, whose figure equals the book total).
    expect(screen.getAllByText("-$1,000.00").length).toBeGreaterThan(0);
    expect(screen.getByText("-10.00%")).toBeTruthy();
  });

  it("spells out the other two reasons distinctly", () => {
    renderCard(
      book({
        trades: [
          trade({ symbol: "AMD", note_id: "n3", reason: "flip_neutral" }),
          trade({ symbol: "MSFT", note_id: "n4", reason: "replaced" }),
        ],
      }),
    );
    expect(screen.getByText(/turned neutral/i)).toBeTruthy();
    expect(screen.getByText(/fund another call/i)).toBeTruthy();
  });

  it("hides the closed-trades section entirely when there are none", () => {
    renderCard(book({ trades: [] }));
    expect(screen.queryByText(/closed trades/i)).toBeNull();
  });
});

describe("skipped calls", () => {
  it("renders a skipped call with symbol, date and reason", () => {
    renderCard(book({ skipped: [skipped({ symbol: "AAPL", said_on: "2026-08-15", reason: "no_market_data" })] }));
    expect(screen.getByText("AAPL")).toBeTruthy();
    expect(screen.getByText("2026-08-15")).toBeTruthy();
    expect(screen.getByText(/no market data/i)).toBeTruthy();
  });

  it("spells out the other two skipped reasons distinctly", () => {
    renderCard(
      book({
        skipped: [
          skipped({ symbol: "SPY", said_on: "2026-08-16", reason: "no_cash" }),
          skipped({ symbol: "QQQ", said_on: "2026-08-17", reason: "no_bar_since" }),
        ],
      }),
    );
    expect(screen.getByText(/no cash free/i)).toBeTruthy();
    expect(screen.getByText(/no price yet/i)).toBeTruthy();
  });

  it("hides the skipped-calls section entirely when there are none", () => {
    renderCard(book({ skipped: [] }));
    expect(screen.queryByText(/skipped calls/i)).toBeNull();
  });
});

describe("warnings", () => {
  it("always render alongside a populated book", () => {
    renderCard(book({ warnings: [{ source: "AAPL", reason: "no market data" }] }));
    expect(screen.getByText("AAPL: no market data")).toBeTruthy();
  });

  it("always render alongside an empty book", () => {
    renderCard(book({ holdings: [], as_of: null, warnings: [{ source: "TSLA", reason: "no market data" }] }));
    expect(screen.getByText("TSLA: no market data")).toBeTruthy();
  });
});

describe("framing", () => {
  it("always shows the shortened paper-projection / not-advice caveat", () => {
    renderCard(book());
    expect(screen.getByText(/not advice/i)).toBeTruthy();
    expect(screen.getByText(/paper book/i, { selector: ".info-note-line" })).toBeTruthy();
  });

  it("names the persona in the heading", () => {
    renderCard(book({ display_name: "Example Persona" }));
    expect(screen.getByRole("heading", { name: /Example Persona/ })).toBeTruthy();
  });
});

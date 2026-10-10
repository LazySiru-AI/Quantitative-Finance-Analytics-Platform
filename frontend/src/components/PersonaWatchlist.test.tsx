/**
 * `PersonaWatchlist`: the cross-persona bullish watchlist panel.
 *
 * What these tests pin, matching this feature's definition of done:
 *  - entries render in the exact order the backend sent them (no client-side re-sort);
 *  - a non-equity entry shows an `InstrumentBadge`, a plain equity shows none;
 *  - changing the date input calls `onAsOfChange` with the typed value;
 *  - clearing the date input calls `onAsOfChange` with `null` ("latest");
 *  - `caveat` always renders once a watchlist is loaded;
 *  - `entries: []` renders an empty note, never an error and never a loading placeholder.
 *
 * Symbols render via `react-router-dom`'s `Link` (`/symbol/{symbol}`), so every render is wrapped in
 * `<MemoryRouter>` -- the same technique `DeskPanel.test.tsx`/`Portfolio.test.tsx` use for their own
 * `Link`-rendering components.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { InfluencerWatchlist, WatchlistEntry } from "@/api/personas";

import PersonaWatchlist, { type WatchlistState } from "./PersonaWatchlist";

afterEach(cleanup);

function entry(overrides: Partial<WatchlistEntry> = {}): WatchlistEntry {
  return {
    symbol: "AAPL",
    bullish_count: 3,
    bearish_count: 1,
    personas: ["creator-a", "someguy"],
    latest_reasoning: "Strong iPhone cycle ahead of the holiday quarter.",
    as_of: "2026-09-01",
    instrument: "equity",
    ...overrides,
  };
}

function watchlist(overrides: Partial<InfluencerWatchlist> = {}): InfluencerWatchlist {
  return {
    as_of: "2026-09-01",
    entries: [entry()],
    caveat: "Descriptive reference only, never a recommendation to buy.",
    ...overrides,
  };
}

function renderPanel(
  state: WatchlistState,
  asOf: string | null = null,
  onAsOfChange = vi.fn(),
  personaNames?: Record<string, string>,
) {
  return render(
    <MemoryRouter>
      <PersonaWatchlist
        state={state}
        asOf={asOf}
        onAsOfChange={onAsOfChange}
        personaNames={personaNames}
      />
    </MemoryRouter>,
  );
}

describe("loading and error phases", () => {
  it("renders a loading placeholder without an error or a table", () => {
    renderPanel({ phase: "loading" });
    expect(screen.getByText("Loading the watchlist…")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("renders the error message as an alert", () => {
    renderPanel({ phase: "error", message: "The watchlist could not be loaded." });
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toBe("The watchlist could not be loaded.");
  });
});

describe("loaded: entry order and instrument badges", () => {
  it("renders entries in the exact order the backend sent, never re-sorted", () => {
    const wl = watchlist({
      entries: [
        entry({ symbol: "ZETA", bullish_count: 1 }),
        entry({ symbol: "AAPL", bullish_count: 9 }),
        entry({ symbol: "MSFT", bullish_count: 5 }),
      ],
    });
    renderPanel({ phase: "loaded", watchlist: wl });
    const rows = screen.getAllByRole("row").slice(1); // drop the header row
    const symbolsInOrder = rows.map((row) => row.textContent ?? "");
    expect(symbolsInOrder[0]).toContain("ZETA");
    expect(symbolsInOrder[1]).toContain("AAPL");
    expect(symbolsInOrder[2]).toContain("MSFT");
  });

  it("shows an InstrumentBadge for a non-equity entry and none for a plain equity", () => {
    const wl = watchlist({
      entries: [
        entry({ symbol: "BTC", instrument: "crypto" }),
        entry({ symbol: "AAPL", instrument: "equity" }),
      ],
    });
    renderPanel({ phase: "loaded", watchlist: wl });
    expect(screen.getByText("Crypto")).toBeTruthy();
    // The equity row's cell holds only the ticker chip -- no pill text anywhere near "AAPL".
    const aaplLink = screen.getByRole("link", { name: "AAPL" });
    const aaplCell = aaplLink.closest("td");
    expect(aaplCell?.querySelector(".status-pill")).toBeNull();
  });

  it("links each symbol to /symbol/{symbol}", () => {
    renderPanel({ phase: "loaded", watchlist: watchlist({ entries: [entry({ symbol: "AAPL" })] }) });
    const link = screen.getByRole("link", { name: "AAPL" });
    expect(link.getAttribute("href")).toBe("/symbol/AAPL");
  });

  it("renders latest_reasoning verbatim", () => {
    const wl = watchlist({ entries: [entry({ latest_reasoning: "Verbatim reasoning, unmodified." })] });
    renderPanel({ phase: "loaded", watchlist: wl });
    expect(screen.getByText("Verbatim reasoning, unmodified.")).toBeTruthy();
  });
});

describe("the as_of date filter", () => {
  it("calls onAsOfChange with the typed date", () => {
    const onAsOfChange = vi.fn();
    renderPanel({ phase: "loading" }, null, onAsOfChange);
    const input = screen.getByLabelText("As of") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "2026-08-15" } });
    expect(onAsOfChange).toHaveBeenCalledWith("2026-08-15");
  });

  it("calls onAsOfChange with null when the date is cleared", () => {
    const onAsOfChange = vi.fn();
    renderPanel({ phase: "loading" }, "2026-08-15", onAsOfChange);
    const input = screen.getByLabelText("As of") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "" } });
    expect(onAsOfChange).toHaveBeenCalledWith(null);
  });

  it("reflects the current asOf prop as the input's value", () => {
    renderPanel({ phase: "loading" }, "2026-08-15");
    const input = screen.getByLabelText("As of") as HTMLInputElement;
    expect(input.value).toBe("2026-08-15");
  });
});

describe("live symbol filter", () => {
  it("narrows the visible rows and shows the shown/total count as the query changes", () => {
    const wl = watchlist({
      entries: [
        entry({ symbol: "AAPL" }),
        entry({ symbol: "MSFT" }),
        entry({ symbol: "AMZN" }),
      ],
    });
    renderPanel({ phase: "loaded", watchlist: wl });

    // All three rows visible, unfiltered.
    expect(screen.getAllByRole("row")).toHaveLength(4); // header + 3
    expect(screen.getByText("Showing 3 of 3")).toBeTruthy();

    const input = screen.getByPlaceholderText("Filter by symbol") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "A" } });

    // "A" matches AAPL and AMZN, not MSFT -- narrowed from 3 to 2, and the count says so.
    expect(screen.getByText("Showing 2 of 3")).toBeTruthy();
    expect(screen.getByRole("link", { name: "AAPL" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "AMZN" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "MSFT" })).toBeNull();
  });

  it("renders backend order untouched among whatever the filter leaves visible", () => {
    const wl = watchlist({
      entries: [
        entry({ symbol: "ZETA" }),
        entry({ symbol: "AAPL" }),
        entry({ symbol: "ZOOM" }),
      ],
    });
    renderPanel({ phase: "loaded", watchlist: wl });

    const input = screen.getByPlaceholderText("Filter by symbol") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Z" } });

    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.map((r) => r.textContent ?? "")[0]).toContain("ZETA");
    expect(rows.map((r) => r.textContent ?? "")[1]).toContain("ZOOM");
  });

  it("shows a no-match note, not an empty table, when the filter matches nothing", () => {
    renderPanel({ phase: "loaded", watchlist: watchlist({ entries: [entry({ symbol: "AAPL" })] }) });
    const input = screen.getByPlaceholderText("Filter by symbol") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "ZZZ" } });

    expect(screen.getByText("No symbol matches this filter.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("caveat and empty state", () => {
  it("always renders the caveat once loaded", () => {
    const wl = watchlist({ caveat: "This is a reference, not investment advice." });
    renderPanel({ phase: "loaded", watchlist: wl });
    expect(screen.getByText("This is a reference, not investment advice.")).toBeTruthy();
  });

  it("renders the caveat even when entries is empty", () => {
    const wl = watchlist({ entries: [], caveat: "Still a reference, even with nothing to show." });
    renderPanel({ phase: "loaded", watchlist: wl });
    expect(screen.getByText("Still a reference, even with nothing to show.")).toBeTruthy();
  });

  it("renders an empty note, not an error, when entries is empty", () => {
    renderPanel({ phase: "loaded", watchlist: watchlist({ entries: [] }) });
    expect(
      screen.getByText("No symbol has bullish backing from a followed influencer right now."),
    ).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("the AS OF timestamp (EXP-14)", () => {
  it("formats the wire's ISO datetime as a date plus HH:MM, never raw", () => {
    const wl = watchlist({ as_of: "2026-09-10T04:31:07.884512Z" });
    renderPanel({ phase: "loaded", watchlist: wl });

    const note = screen.getByText(/Showing the consensus as of/);
    const text = note.textContent ?? "";
    expect(text).not.toContain("T04:31");
    expect(text).not.toContain("Z");
    expect(text).not.toContain("884512");
    expect(text).toMatch(/\d{2}:\d{2}/);
    expect(text).toContain("2026");
  });

  it("renders a bare YYYY-MM-DD as that same calendar day, with no invented time", () => {
    const wl = watchlist({ as_of: "2026-09-01" });
    renderPanel({ phase: "loaded", watchlist: wl });

    const text = screen.getByText(/Showing the consensus as of/).textContent ?? "";
    // UTC-pinned like `api/macro.ts`'s own bare-date helper: never the 31st in a western zone.
    expect(text).toContain("Sep 1, 2026");
    expect(text).not.toMatch(/\d{2}:\d{2}/);
  });

  it("says the date is unknown rather than printing an unparseable value", () => {
    const wl = watchlist({ as_of: "not-a-date" });
    renderPanel({ phase: "loaded", watchlist: wl });

    expect(screen.getByText(/Showing the consensus as of Unknown/)).toBeTruthy();
  });
});

describe("provenance on the model-written reasoning (EXP-08)", () => {
  it("marks the reasoning column as a model summary", () => {
    renderPanel({ phase: "loaded", watchlist: watchlist() });
    expect(screen.getAllByText("Model summary").length).toBeGreaterThan(0);
  });

  it("states, in the open, that the prose is a summary of a dated note and not a quote", () => {
    renderPanel({ phase: "loaded", watchlist: watchlist() });
    const note = screen.getByTestId("watchlist-summary-note");
    expect(note.textContent).toContain("not a quote");
    // Never behind a disclosure -- COPY-STYLE.md rule 6.
    expect(note.closest("details")).toBeNull();
  });

  it("dates each row from its own entry.as_of", () => {
    const wl = watchlist({ entries: [entry({ as_of: "2026-08-20" })] });
    renderPanel({ phase: "loaded", watchlist: wl });
    expect(screen.getByText("Note dated Aug 20, 2026")).toBeTruthy();
  });

  it("says so when a row has no note date, rather than borrowing the panel's", () => {
    const wl = watchlist({ as_of: "2026-09-01", entries: [entry({ as_of: null })] });
    renderPanel({ phase: "loaded", watchlist: wl });
    expect(screen.getByText("No note date")).toBeTruthy();
  });
});

describe("backer handles", () => {
  it("renders raw handles when the caller supplies no name map", () => {
    const wl = watchlist({ entries: [entry({ personas: ["creator-a", "someguy"] })] });
    renderPanel({ phase: "loaded", watchlist: wl });
    expect(screen.getByText("creator-a, someguy")).toBeTruthy();
  });

  it("resolves the handles it can and leaves the ones it cannot verbatim", () => {
    const wl = watchlist({ entries: [entry({ personas: ["creator-a", "someguy"] })] });
    renderPanel({ phase: "loaded", watchlist: wl }, null, vi.fn(), { "creator-a": "Creator A" });
    expect(screen.getByText("Creator A, someguy")).toBeTruthy();
  });
});

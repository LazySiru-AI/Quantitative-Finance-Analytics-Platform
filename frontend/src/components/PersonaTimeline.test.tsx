/**
 * PersonaTimeline.tsx's render-level guardrails.
 *
 * No API mocking needed here (unlike `Consensus.test.tsx`) -- this component fetches nothing, so
 * every test builds a `TimelineFetchState` directly, matching `PersonaScorecard.tsx`'s own
 * presentational contract. Wrapped in `MemoryRouter` because ticker symbols render as `<Link>`s to
 * `/symbol/{symbol}`; `useT()` needs no provider (`@/i18n`'s store is module-level, not React
 * context), so no i18n wrapper is required either -- matching every other component test in this
 * codebase (see `Consensus.test.tsx`).
 *
 * Assertions use `.toBeTruthy()` / `queryBy...().toBeNull()` rather than jest-dom's
 * `toBeInTheDocument()`, matching this project's existing convention.
 *
 * What these tests pin, per the task's definition of done:
 *  - the dated feed renders newest-first, exactly as `entries` arrives (no client re-sort)
 *  - `published: null` renders the "date unknown" label, never a fake/invalid date
 *  - a symbol whose stance changed across its points is flagged and ordered before one that did not
 *  - a stance track's own points render oldest-first, exactly as `points` arrives (no re-sort)
 *  - `entries: []` and `stance_timelines: []` together render a plain empty note, not an error
 *  - the loading and error phases each render something distinct from the loaded body
 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { PersonaTimeline as Timeline, StanceTimeline, TimelineEntry } from "@/api/personas";

import PersonaTimeline, { type TimelineFetchState } from "./PersonaTimeline";

function entry(overrides: Partial<TimelineEntry> = {}): TimelineEntry {
  return {
    note_id: "note-1",
    published: "2026-08-01T00:00:00Z",
    title: "A note title",
    summary: "A summary of what was said.",
    themes: [],
    symbols: [],
    url: "https://example.com/note-1",
    ...overrides,
  };
}

function stanceTrack(overrides: Partial<StanceTimeline> = {}): StanceTimeline {
  return {
    symbol: "AAPL",
    points: [
      { note_id: "n1", said_on: "2026-06-01T00:00:00Z", stance: "bullish", reasoning: "Liked the setup." },
    ],
    ...overrides,
  };
}

function timeline(overrides: Partial<Timeline> = {}): Timeline {
  return {
    persona: "creator-a",
    entries: [],
    stance_timelines: [],
    ...overrides,
  };
}

function renderState(state: TimelineFetchState) {
  return render(
    <MemoryRouter>
      <PersonaTimeline displayName="Creator A" state={state} />
    </MemoryRouter>,
  );
}

describe("PersonaTimeline", () => {
  it("renders a loading placeholder distinct from the loaded body", () => {
    renderState({ phase: "loading" });
    expect(screen.getByText(/loading timeline/i)).toBeTruthy();
    expect(screen.queryByText(/nothing on the timeline/i)).toBeNull();
  });

  it("renders the error message on the error phase", () => {
    renderState({ phase: "error", message: "boom: could not reach the server" });
    expect(screen.getByRole("alert").textContent).toContain("boom: could not reach the server");
  });

  it("renders a plain empty-state note, not an error, when entries and stance_timelines are both empty", () => {
    renderState({ phase: "loaded", timeline: timeline() });
    expect(screen.getByText(/nothing on the timeline/i)).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("renders the dated feed newest-first, exactly as entries arrives", () => {
    const newest = entry({ note_id: "n-newest", title: "Newest note", published: "2026-08-20T00:00:00Z" });
    const oldest = entry({ note_id: "n-oldest", title: "Oldest note", published: "2026-01-05T00:00:00Z" });
    renderState({
      phase: "loaded",
      timeline: timeline({ entries: [newest, oldest] }), // already newest-first, per the contract
    });

    const titles = screen.getAllByRole("link", { name: /newest note|oldest note/i }).map((el) => el.textContent);
    expect(titles).toEqual(["Newest note", "Oldest note"]);
  });

  it("renders a 'date unknown' label instead of a fake date when published is null", () => {
    renderState({
      phase: "loaded",
      timeline: timeline({ entries: [entry({ published: null, title: "Undated note" })] }),
    });
    expect(screen.getByText(/date unknown/i)).toBeTruthy();
    // Never a stringified null / "Invalid Date" leaking through.
    expect(screen.queryByText(/invalid date/i)).toBeNull();
    expect(screen.queryByText(/^null$/i)).toBeNull();
  });

  it("renders a javascript: entry URL as plain text, never an anchor", () => {
    renderState({
      phase: "loaded",
      timeline: timeline({
        entries: [entry({ url: "javascript:alert(1)", title: "Poisoned entry" })],
      }),
    });

    expect(screen.getByText("Poisoned entry")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Poisoned entry/i })).toBeNull();
  });

  it("still renders an https entry URL as an out-linking anchor", () => {
    renderState({
      phase: "loaded",
      timeline: timeline({
        entries: [entry({ url: "https://example.com/safe-note", title: "Safe entry" })],
      }),
    });

    const link = screen.getByRole("link", { name: /Safe entry/i });
    expect(link.getAttribute("href")).toBe("https://example.com/safe-note");
  });

  it("falls back to an untitled label when title is null, without dropping the entry", () => {
    renderState({
      phase: "loaded",
      timeline: timeline({ entries: [entry({ title: null, summary: "Body text still shows." })] }),
    });
    expect(screen.getByText(/untitled/i)).toBeTruthy();
    expect(screen.getByText("Body text still shows.")).toBeTruthy();
  });

  it("renders each entry's symbols as ticker links to /symbol/{symbol}", () => {
    renderState({
      phase: "loaded",
      timeline: timeline({ entries: [entry({ symbols: ["AAPL", "TSLA"] })] }),
    });
    const aapl = screen.getByRole("link", { name: /AAPL/ });
    expect(aapl.getAttribute("href")).toBe("/symbol/AAPL");
    const tsla = screen.getByRole("link", { name: /TSLA/ });
    expect(tsla.getAttribute("href")).toBe("/symbol/TSLA");
  });

  it("surfaces a symbol whose stance changed before one whose stance did not", () => {
    const unchanged = stanceTrack({
      symbol: "MSFT",
      points: [
        { note_id: "m1", said_on: "2026-05-01T00:00:00Z", stance: "bullish", reasoning: "Steady." },
        { note_id: "m2", said_on: "2026-06-01T00:00:00Z", stance: "bullish", reasoning: "Still steady." },
      ],
    });
    const changed = stanceTrack({
      symbol: "NVDA",
      points: [
        { note_id: "v1", said_on: "2026-05-01T00:00:00Z", stance: "bullish", reasoning: "Loved it." },
        { note_id: "v2", said_on: "2026-07-01T00:00:00Z", stance: "bearish", reasoning: "Turned cautious." },
      ],
    });
    // Deliberately given unchanged-first, so a passing test proves the component re-orders rather
    // than merely preserving input order.
    renderState({
      phase: "loaded",
      timeline: timeline({ stance_timelines: [unchanged, changed] }),
    });

    const tickerLinks = screen
      .getAllByRole("link")
      .filter((el) => el.getAttribute("href")?.startsWith("/symbol/"));
    const symbolOrder = tickerLinks.map((el) => el.textContent).filter((t) => t === "MSFT" || t === "NVDA");
    expect(symbolOrder[0]).toBe("NVDA");
    expect(symbolOrder).toContain("MSFT");

    expect(screen.getByText(/stance changed/i)).toBeTruthy();
  });

  it("renders one stance track's points oldest-first, exactly as points arrives", () => {
    const track = stanceTrack({
      symbol: "GOOG",
      points: [
        { note_id: "g1", said_on: "2026-01-01T00:00:00Z", stance: "bullish", reasoning: "First take." },
        { note_id: "g2", said_on: "2026-03-01T00:00:00Z", stance: "neutral", reasoning: "Second take." },
        { note_id: "g3", said_on: "2026-05-01T00:00:00Z", stance: "bearish", reasoning: "Third take." },
      ],
    });
    renderState({ phase: "loaded", timeline: timeline({ stance_timelines: [track] }) });

    // Read them back off the DOM in document order and compare to the source (oldest-first) order.
    const reasonings = screen.getAllByText(/take\.$/);
    expect(reasonings.map((el) => el.textContent)).toEqual(["First take.", "Second take.", "Third take."]);
  });
});

/**
 * `PersonaRegime`: the cross-persona risk-on/off regime tally panel.
 *
 * What these tests pin, matching this feature's definition of done:
 *  - the risk_on/risk_off/mixed tally renders as the headline;
 *  - a persona without `has_view` is noted, never rendered as a fake `RegimeView`;
 *  - a persona with `has_view` renders its risk posture, rates, sectors and summary verbatim;
 *  - `caveat` always renders once a consensus is loaded.
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { PersonaRegime as PersonaRegimeEntry, RegimeConsensus, RegimeView } from "@/api/personas";

import PersonaRegime, { type RegimeState } from "./PersonaRegime";

afterEach(cleanup);

function view(overrides: Partial<RegimeView> = {}): RegimeView {
  return {
    risk: "on",
    rates: "Fed likely on hold through year-end.",
    summary: "Constructive on equities into year-end seasonality.",
    sectors_favoured: ["Semis", "Industrials"],
    sectors_avoided: ["Utilities"],
    citations: ["note-1"],
    has_signal: true,
    ...overrides,
  };
}

function personaEntry(overrides: Partial<PersonaRegimeEntry> = {}): PersonaRegimeEntry {
  return {
    persona: "macro-mike",
    display_name: "Macro Mike",
    view: view(),
    has_view: true,
    as_of: "2026-09-01",
    ...overrides,
  };
}

function consensus(overrides: Partial<RegimeConsensus> = {}): RegimeConsensus {
  return {
    as_of: "2026-09-01",
    personas: [personaEntry()],
    risk_on: 1,
    risk_off: 0,
    mixed: 0,
    caveat: "A reference input, never a trading signal.",
    ...overrides,
  };
}

function renderPanel(state: RegimeState) {
  return render(<PersonaRegime state={state} />);
}

describe("loading and error phases", () => {
  it("renders a loading placeholder without an error", () => {
    renderPanel({ phase: "loading" });
    expect(screen.getByText("Loading the regime consensus…")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("renders the error message as an alert", () => {
    renderPanel({ phase: "error", message: "The regime consensus could not be loaded." });
    expect(screen.getByRole("alert").textContent).toBe("The regime consensus could not be loaded.");
  });
});

describe("the risk_on/risk_off/mixed tally", () => {
  it("renders the counts as the headline, before any per-persona detail", () => {
    const { container } = renderPanel({
      phase: "loaded",
      consensus: consensus({ risk_on: 4, risk_off: 2, mixed: 1, personas: [] }),
    });
    expect(screen.getByText("Leaning risk-on")).toBeTruthy();
    expect(screen.getByText("Leaning risk-off")).toBeTruthy();
    expect(screen.getByText("Mixed signals")).toBeTruthy();

    const values = Array.from(container.querySelectorAll(".persona-regime-tally-value")).map(
      (el) => el.textContent,
    );
    expect(values).toEqual(["4", "2", "1"]);

    // The tally sits before the per-persona list in document order.
    const tally = container.querySelector(".persona-regime-tally");
    const empty = screen.getByText("No persona has offered a regime view yet.");
    expect(
      tally?.compareDocumentPosition(empty) === Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBe(true);
  });
});

describe("per-persona regime views", () => {
  it("renders risk posture, rates, sectors and summary verbatim for a persona with has_view", () => {
    const entry = personaEntry({
      display_name: "Macro Mike",
      view: view({
        risk: "off",
        rates: "Cuts pushed out to next year.",
        summary: "Defensive positioning warranted here.",
        sectors_favoured: ["Staples"],
        sectors_avoided: ["Semis", "Homebuilders"],
      }),
    });
    renderPanel({ phase: "loaded", consensus: consensus({ personas: [entry] }) });

    expect(screen.getByText("Macro Mike")).toBeTruthy();
    expect(screen.getByText("Risk-off")).toBeTruthy();
    expect(screen.getByText("Cuts pushed out to next year.")).toBeTruthy();
    expect(screen.getByText("Defensive positioning warranted here.")).toBeTruthy();
    expect(screen.getByText("Staples")).toBeTruthy();
    expect(screen.getByText("Semis, Homebuilders")).toBeTruthy();
  });

  it("notes a persona without has_view instead of rendering a fake view", () => {
    const noView = personaEntry({
      persona: "chartist",
      display_name: "Pure Chartist",
      has_view: false,
      view: view({ has_signal: false, risk: "unclear", summary: "", rates: "" }),
    });
    renderPanel({ phase: "loaded", consensus: consensus({ personas: [noView] }) });

    expect(screen.getByText("Pure Chartist")).toBeTruthy();
    expect(screen.getByText("No regime view from this persona.")).toBeTruthy();
    // Never fabricates posture/sector content for a no-view persona.
    expect(screen.queryByText("Unclear")).toBeNull();
  });

  it("renders citations for a persona with a view", () => {
    renderPanel({
      phase: "loaded",
      consensus: consensus({ personas: [personaEntry({ view: view({ citations: ["note-42"] }) })] }),
    });
    expect(screen.getByText("note-42")).toBeTruthy();
  });
});

describe("caveat", () => {
  it("always renders once loaded", () => {
    renderPanel({
      phase: "loaded",
      consensus: consensus({ caveat: "Never advice, always descriptive." }),
    });
    expect(screen.getByText("Never advice, always descriptive.")).toBeTruthy();
  });

  it("renders the caveat even when no persona has a view", () => {
    const noView = personaEntry({ has_view: false, view: view({ has_signal: false }) });
    renderPanel({
      phase: "loaded",
      consensus: consensus({ personas: [noView], caveat: "Still shown with zero views." }),
    });
    expect(screen.getByText("Still shown with zero views.")).toBeTruthy();
  });
});

describe("empty personas list", () => {
  it("renders an empty note rather than an error", () => {
    renderPanel({ phase: "loaded", consensus: consensus({ personas: [] }) });
    expect(screen.getByText("No persona has offered a regime view yet.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

// Re-exercise `within` to scope a query to one row-level container without relying on `screen`
// global text lookups colliding with the tally labels above (`Risk-on`/`Risk-off`/`Mixed` also
// appear as posture pill labels).
describe("tally labels vs. posture pill labels do not collide", () => {
  it("scopes the posture pill lookup to the persona row", () => {
    const entry = personaEntry({ view: view({ risk: "mixed" }) });
    const { container } = renderPanel({ phase: "loaded", consensus: consensus({ personas: [entry] }) });
    const row = container.querySelector(".persona-regime-row");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("Mixed")).toBeTruthy();
  });
});

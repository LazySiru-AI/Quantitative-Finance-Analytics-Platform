/**
 * PersonaProfile: the methodology ("how they trade") section renders only when `methodology` is
 * non-empty and shows no header at all when it is empty (a pure macro commentator has nothing to
 * say here, and that emptiness must not read as a missing section); the regime section renders only
 * when `regime` is non-null AND `regime.has_signal` is true. Both reuse the existing
 * `ClaimSection`/`ClaimItem` citation-chip idiom this file already establishes for beliefs/playbook.
 */
import { MemoryRouter } from "react-router-dom";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import PersonaProfile, { type ProfileFetchState } from "@/components/PersonaProfile";
import type { PersonaProfile as Profile, RegimeView } from "@/api/personas";

afterEach(cleanup);

function profile(overrides: Partial<Profile> = {}): Profile {
  return {
    persona: "creator-a",
    version: 3,
    consolidated_at: "2026-08-01T00:00:00Z",
    note_count: 12,
    summary: "Trades momentum breakouts on large-cap tech.",
    beliefs: [{ text: "Rates stay higher for longer.", citations: ["note-1"] }],
    playbook: [{ text: "Buys the first pullback after a breakout.", citations: ["note-2"] }],
    methodology: [],
    regime: null,
    vocabulary: [],
    degraded: false,
    path: "profile.md",
    ...overrides,
  };
}

function regime(overrides: Partial<RegimeView> = {}): RegimeView {
  return {
    risk: "on",
    rates: "expects two cuts this year",
    summary: "Leaning risk-on into year end.",
    sectors_favoured: ["Semiconductors"],
    sectors_avoided: ["Utilities"],
    citations: ["note-3"],
    has_signal: true,
    ...overrides,
  };
}

function renderLoaded(p: Profile) {
  const state: ProfileFetchState = { phase: "loaded", profile: p };
  return render(
    <MemoryRouter>
      <PersonaProfile
        displayName="Creator A"
        currentNoteCount={12}
        state={state}
        theses={[]}
        consolidatePending={false}
        consolidateError={null}
        onConsolidate={vi.fn()}
      />
    </MemoryRouter>,
  );
}

describe("methodology section", () => {
  it("renders the heading and claims when methodology is non-empty", () => {
    renderLoaded(
      profile({
        methodology: [{ text: "Uses the 20-day moving average as a trend filter.", citations: ["note-4"] }],
      }),
    );
    expect(screen.getByText("Methodology")).toBeTruthy();
    expect(screen.getByText("Uses the 20-day moving average as a trend filter.")).toBeTruthy();
    expect(screen.getByText("note-4")).toBeTruthy();
  });

  it("renders no heading at all when methodology is empty", () => {
    renderLoaded(profile({ methodology: [] }));
    expect(screen.queryByText("Methodology")).toBeNull();
  });
});

describe("regime section", () => {
  it("renders when regime is non-null and has_signal is true", () => {
    renderLoaded(profile({ regime: regime() }));
    expect(screen.getByText("Regime view")).toBeTruthy();
    expect(screen.getByText("Leaning risk-on into year end.")).toBeTruthy();
    expect(screen.getByText("Semiconductors")).toBeTruthy();
    expect(screen.getByText("Utilities")).toBeTruthy();
    expect(screen.getByText("note-3")).toBeTruthy();
  });

  it("renders nothing when regime is null", () => {
    renderLoaded(profile({ regime: null }));
    expect(screen.queryByText("Regime view")).toBeNull();
  });

  it("renders nothing when has_signal is false, even with other fields populated", () => {
    renderLoaded(profile({ regime: regime({ has_signal: false }) }));
    expect(screen.queryByText("Regime view")).toBeNull();
    expect(screen.queryByText("Leaning risk-on into year end.")).toBeNull();
  });
});

describe("existing behavior stays intact", () => {
  it("still renders beliefs and playbook alongside the new sections", () => {
    renderLoaded(profile());
    expect(screen.getByText("Rates stay higher for longer.")).toBeTruthy();
    expect(screen.getByText("Buys the first pullback after a breakout.")).toBeTruthy();
  });

  it("still renders the loading state", () => {
    render(
      <MemoryRouter>
        <PersonaProfile
          displayName="Creator A"
          currentNoteCount={12}
          state={{ phase: "loading" }}
          theses={[]}
          consolidatePending={false}
          consolidateError={null}
          onConsolidate={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText("Loading profile…")).toBeTruthy();
  });
});

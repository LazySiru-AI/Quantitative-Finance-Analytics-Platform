/**
 * PersonaStrategyCard: `mapped: false` renders `reason` as a plain, valid answer (no alert role, no
 * error styling) -- distinct from `state.phase === "error"`, which keeps the loud callout. The
 * fidelity meter always shows "expresses {represented} of {total} techniques" plus the named
 * `unrepresentable` list on a mapped card. `caveat` is visible on every drafted card, mapped or not.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import PersonaStrategyCard, { type StrategyCardState } from "@/components/PersonaStrategyCard";
import type { SavedStrategyDraft, StrategyCardDraft } from "@/api/personas";

afterEach(cleanup);

function draft(overrides: Partial<StrategyCardDraft> = {}): StrategyCardDraft {
  return {
    persona: "creator-a",
    mapped: true,
    reason: "",
    rule_shape: "trend_follow",
    card: { universe: "large_cap_tech", entry: "close > sma(20)", exit: "close < sma(20)" },
    rationale: "Mirrors their stated preference for buying breakouts above the 20-day average.",
    citations: ["note-1", "note-2"],
    caveat: "An exploration lens, inspired by their notes -- not a recommendation and no edge is expected.",
    degraded: false,
    cost_usd: "0.04",
    version: 2,
    fidelity: 0.5,
    techniques_total: 4,
    techniques_represented: 2,
    unrepresentable: ["discretionary news reaction", "position sizing by conviction"],
    ...overrides,
  };
}

function savedDraft(overrides: Partial<SavedStrategyDraft> = {}): SavedStrategyDraft {
  return {
    draft: draft(),
    saved_at: "2020-01-01T00:00:00Z",
    filename: "strategy/2.json",
    ...overrides,
  };
}

function renderCard(state: StrategyCardState, history: SavedStrategyDraft[] = [], onDraft = vi.fn()) {
  render(
    <PersonaStrategyCard displayName="Creator A" state={state} history={history} onDraft={onDraft} />,
  );
  return onDraft;
}

describe("idle / pending", () => {
  it("calls onDraft when the draft button is clicked", () => {
    const onDraft = renderCard({ phase: "idle" });
    fireEvent.click(screen.getByText("Draft a strategy from their method"));
    expect(onDraft).toHaveBeenCalledTimes(1);
  });

  it("disables the button and shows the pending label while drafting", () => {
    renderCard({ phase: "pending" });
    const button = screen.getByText("Drafting…") as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });
});

describe("error phase", () => {
  it("renders the message as a loud alert", () => {
    renderCard({ phase: "error", message: "the model is unavailable" });
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("the model is unavailable");
  });
});

describe("mapped: false", () => {
  it("renders the reason as a plain, valid answer -- not an error", () => {
    renderCard({
      phase: "drafted",
      draft: draft({ mapped: false, reason: "no mechanical methodology to map", card: null, rule_shape: null }),
    });
    expect(screen.getByText("no mechanical methodology to map")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("still shows the caveat", () => {
    renderCard({
      phase: "drafted",
      draft: draft({ mapped: false, reason: "no current-bullish tickers", card: null, rule_shape: null }),
    });
    expect(screen.getByText(/not a recommendation/)).toBeTruthy();
  });
});

describe("mapped: true", () => {
  it("renders the card's key/value fields", () => {
    renderCard({ phase: "drafted", draft: draft() });
    expect(screen.getByText("universe")).toBeTruthy();
    expect(screen.getByText("large_cap_tech")).toBeTruthy();
    expect(screen.getByText("entry")).toBeTruthy();
    expect(screen.getByText("close > sma(20)")).toBeTruthy();
  });

  it("renders the rationale and citations", () => {
    renderCard({ phase: "drafted", draft: draft() });
    expect(screen.getByText(/Mirrors their stated preference/)).toBeTruthy();
    expect(screen.getByText("note-1")).toBeTruthy();
    expect(screen.getByText("note-2")).toBeTruthy();
  });

  it("shows the fidelity honesty meter and the unrepresentable list", () => {
    renderCard({ phase: "drafted", draft: draft({ techniques_represented: 2, techniques_total: 4 }) });
    expect(screen.getByText("Expresses 2 of 4 techniques")).toBeTruthy();
    expect(screen.getByText("discretionary news reaction")).toBeTruthy();
    expect(screen.getByText("position sizing by conviction")).toBeTruthy();
  });

  it("omits the fidelity meter entirely when fidelity is null", () => {
    renderCard({ phase: "drafted", draft: draft({ fidelity: null }) });
    expect(screen.queryByText(/Expresses/)).toBeNull();
  });

  it("shows the caveat unconditionally", () => {
    renderCard({ phase: "drafted", draft: draft() });
    expect(screen.getByText(/not a recommendation/)).toBeTruthy();
  });

  it("shows the degraded fact-check warning when true", () => {
    renderCard({ phase: "drafted", draft: draft({ degraded: true }) });
    expect(screen.getByText("Fact-check failed")).toBeTruthy();
  });

  it("does not show the degraded warning when false", () => {
    renderCard({ phase: "drafted", draft: draft({ degraded: false }) });
    expect(screen.queryByText("Fact-check failed")).toBeNull();
  });
});

describe("history", () => {
  it("shows the empty state with no saved drafts", () => {
    renderCard({ phase: "idle" }, []);
    expect(screen.getByText("No saved drafts yet")).toBeTruthy();
  });

  it("renders each prior draft's filename and relative age", () => {
    renderCard({ phase: "idle" }, [savedDraft()]);
    expect(screen.getByText("strategy/2.json")).toBeTruthy();
    expect(screen.getByText(/d ago/)).toBeTruthy();
  });
});

describe("promote to library", () => {
  const drafted: StrategyCardState = { phase: "drafted", draft: draft({ version: 2 }) };

  it("shows a promote button on a mapped card and calls onPromote with the version", () => {
    const onPromote = vi.fn();
    render(
      <PersonaStrategyCard
        displayName="x"
        state={drafted}
        history={[]}
        onDraft={vi.fn()}
        onPromote={onPromote}
        promoteState={{ phase: "idle" }}
      />,
    );
    fireEvent.click(screen.getByText("Promote to library"));
    expect(onPromote).toHaveBeenCalledWith(2);
  });

  it("shows no promote button when onPromote is not wired", () => {
    render(<PersonaStrategyCard displayName="x" state={drafted} history={[]} onDraft={vi.fn()} />);
    expect(screen.queryByText("Promote to library")).toBeNull();
  });

  it("shows no promote button for an unmapped draft (nothing to promote)", () => {
    render(
      <PersonaStrategyCard
        displayName="x"
        state={{ phase: "drafted", draft: draft({ mapped: false, card: null }) }}
        history={[]}
        onDraft={vi.fn()}
        onPromote={vi.fn()}
        promoteState={{ phase: "idle" }}
      />,
    );
    expect(screen.queryByText("Promote to library")).toBeNull();
  });

  it("disables the button and shows the pending label while promoting", () => {
    render(
      <PersonaStrategyCard
        displayName="x"
        state={drafted}
        history={[]}
        onDraft={vi.fn()}
        onPromote={vi.fn()}
        promoteState={{ phase: "pending" }}
      />,
    );
    expect((screen.getByText("Promoting…") as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows the added state with the shelf id once done", () => {
    render(
      <PersonaStrategyCard
        displayName="x"
        state={drafted}
        history={[]}
        onDraft={vi.fn()}
        onPromote={vi.fn()}
        promoteState={{ phase: "done", agentId: "P-creator-a-v2" }}
      />,
    );
    expect(screen.getByText("Added to the library")).toBeTruthy();
  });

  it("treats already-on-shelf (409) as info, not an error", () => {
    render(
      <PersonaStrategyCard
        displayName="x"
        state={drafted}
        history={[]}
        onDraft={vi.fn()}
        onPromote={vi.fn()}
        promoteState={{ phase: "exists" }}
      />,
    );
    expect(screen.getByText("Already on the shelf")).toBeTruthy();
    expect(screen.queryByText("Could not promote")).toBeNull();
  });

  it("surfaces a real failure message", () => {
    render(
      <PersonaStrategyCard
        displayName="x"
        state={drafted}
        history={[]}
        onDraft={vi.fn()}
        onPromote={vi.fn()}
        promoteState={{ phase: "error", message: "boom" }}
      />,
    );
    expect(screen.getByText("Could not promote")).toBeTruthy();
  });
});

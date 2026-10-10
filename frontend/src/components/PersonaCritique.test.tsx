/**
 * PersonaCritique: the trigger firing `onCritique`, disabling + explaining when `canCritique` is
 * false, the per-verdict badge, and the always-visible backend `caveat`.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CardCritique } from "@/api/personas";
import PersonaCritique, { type CritiqueState } from "@/components/PersonaCritique";

afterEach(cleanup);

function critique(overrides: Partial<CardCritique> = {}): CardCritique {
  return {
    persona: "creator-a",
    verdict: "aligned",
    assessment: "This tracks how they'd actually trade it.",
    citations: ["note-1"],
    caveat: "This is a model's reading of their methodology, not their endorsement.",
    degraded: false,
    cost_usd: "0.01",
    ...overrides,
  };
}

describe("the always-visible impression caveat", () => {
  it("renders regardless of phase, before a critique is requested", () => {
    render(
      <PersonaCritique displayName="TestName" state={{ phase: "idle" }} canCritique onCritique={vi.fn()} />,
    );
    expect(screen.getByText(/model's impression of how TestName would critique/i)).toBeTruthy();
  });
});

describe("the trigger", () => {
  it("calls onCritique when clicked and a card is available", () => {
    const onCritique = vi.fn();
    render(
      <PersonaCritique displayName="TestName" state={{ phase: "idle" }} canCritique onCritique={onCritique} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Ask for a critique" }));
    expect(onCritique).toHaveBeenCalledTimes(1);
  });

  it("disables the trigger and explains why when canCritique is false", () => {
    const onCritique = vi.fn();
    render(
      <PersonaCritique
        displayName="TestName"
        state={{ phase: "idle" }}
        canCritique={false}
        onCritique={onCritique}
      />,
    );
    const button = screen.getByRole("button", { name: "Ask for a critique" });
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(screen.getByText("No card to critique yet.")).toBeTruthy();

    fireEvent.click(button);
    expect(onCritique).not.toHaveBeenCalled();
  });

  it("disables the trigger while a request is pending", () => {
    render(
      <PersonaCritique displayName="TestName" state={{ phase: "pending" }} canCritique onCritique={vi.fn()} />,
    );
    const button = screen.getByRole("button", { name: /Asking TestName/ });
    expect(button.hasAttribute("disabled")).toBe(true);
  });

  it("shows no disabled explanation when a card is available", () => {
    render(
      <PersonaCritique displayName="TestName" state={{ phase: "idle" }} canCritique onCritique={vi.fn()} />,
    );
    expect(screen.queryByText("No card to critique yet.")).toBeNull();
  });
});

describe("the error phase", () => {
  it("renders the error message", () => {
    const state: CritiqueState = { phase: "error", message: "the critique endpoint is down" };
    render(<PersonaCritique displayName="TestName" state={state} canCritique onCritique={vi.fn()} />);
    expect(screen.getByText("the critique endpoint is down")).toBeTruthy();
  });
});

describe("the done phase", () => {
  it("renders a distinct badge per verdict value", () => {
    const verdicts: { verdict: CardCritique["verdict"]; label: string }[] = [
      { verdict: "aligned", label: "Aligned" },
      { verdict: "mixed", label: "Mixed" },
      { verdict: "misaligned", label: "Misaligned" },
      { verdict: "cannot_say", label: "Cannot say" },
    ];

    for (const { verdict, label } of verdicts) {
      const state: CritiqueState = { phase: "done", critique: critique({ verdict }) };
      const { unmount } = render(
        <PersonaCritique displayName="TestName" state={state} canCritique onCritique={vi.fn()} />,
      );
      const badge = screen.getByTestId("persona-critique-verdict");
      expect(badge.textContent).toBe(label);
      unmount();
    }
  });

  it("renders the assessment verbatim and its citations", () => {
    const state: CritiqueState = { phase: "done", critique: critique() };
    render(<PersonaCritique displayName="TestName" state={state} canCritique onCritique={vi.fn()} />);
    expect(screen.getByText("This tracks how they'd actually trade it.")).toBeTruthy();
    expect(screen.getByText("note-1")).toBeTruthy();
  });

  it("always renders the caveat", () => {
    const state: CritiqueState = { phase: "done", critique: critique() };
    render(<PersonaCritique displayName="TestName" state={state} canCritique onCritique={vi.fn()} />);
    expect(
      screen.getByText("This is a model's reading of their methodology, not their endorsement."),
    ).toBeTruthy();
  });

  it("shows a degraded fact-check warning when degraded is true", () => {
    const state: CritiqueState = { phase: "done", critique: critique({ degraded: true }) };
    render(<PersonaCritique displayName="TestName" state={state} canCritique onCritique={vi.fn()} />);
    expect(screen.getByText("Fact-check failed")).toBeTruthy();
  });

  it("shows no fact-check warning when degraded is false", () => {
    const state: CritiqueState = { phase: "done", critique: critique({ degraded: false }) };
    render(<PersonaCritique displayName="TestName" state={state} canCritique onCritique={vi.fn()} />);
    expect(screen.queryByText("Fact-check failed")).toBeNull();
  });
});

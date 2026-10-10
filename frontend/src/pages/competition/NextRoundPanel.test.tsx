/**
 * `NextRoundPanel`'s honesty rules, at render level -- mirrors `RoundNarrativeCard.test.tsx`'s
 * approach: this component takes its data as props (the parent owns the fetch), so there is no API
 * module to stub here, only a fixture that mirrors `@/api/competition`'s `NextRoundBriefing` and
 * `RoundFinding` wire types field for field.
 *
 * What these tests pin, matching the task's definition of done:
 *  - the happy path renders every field;
 *  - `pre_registered: false` renders the warning callout and `true` does not (both directions);
 *  - both carries-forward lists empty renders the explicit "nothing recorded as carrying forward"
 *    wording, not an empty container;
 *  - the authored list and the heuristic `carries_forward` list render as visually distinguishable
 *    blocks -- an item present only in the heuristic list must not appear under the authored heading,
 *    proving the two are not merged into one list;
 *  - blockers are surfaced, never used to hide or disable the run affordance.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { NextRoundBriefing, RoundFinding } from "@/api/competition";
import NextRoundPanel from "@/pages/competition/NextRoundPanel";

// --- fixtures --------------------------------------------------------------------------------------

function roundFinding(overrides: Partial<RoundFinding> = {}): RoundFinding {
  return {
    id: "f1",
    round_id: "r5-2026-08",
    kind: "follow-up",
    title: "Re-check the gate threshold",
    body: "The eligibility gate should be re-checked against a wider sample before r6 seats anything.",
    source: "SELECTION.md § 8",
    carries_forward: true,
    ...overrides,
  };
}

function nextRoundBriefing(overrides: Partial<NextRoundBriefing> = {}): NextRoundBriefing {
  return {
    previous_round_id: "r5-2026-08",
    next_round_id: "r6-2026-09",
    plan_path: "rounds/r6-2026-09/PLAN.md",
    pre_registered: true,
    focus: "Whether a wider sample changes the gate threshold.",
    authored_carries_forward: ["Re-check the gate threshold against a wider sample."],
    carries_forward: [roundFinding()],
    blockers: [],
    ...overrides,
  };
}

// --- tests ------------------------------------------------------------------------------------------

describe("NextRoundPanel", () => {
  it("renders every field on the happy path", () => {
    render(<NextRoundPanel briefing={nextRoundBriefing()} phase="loaded" message={null} />);

    expect(screen.getAllByText(/r6-2026-09/).length).toBeGreaterThan(0);
    expect(screen.getByText("rounds/r6-2026-09/PLAN.md")).toBeTruthy();
    expect(screen.getByText("Whether a wider sample changes the gate threshold.")).toBeTruthy();
    // Authored list (primary).
    expect(screen.getByText("Re-check the gate threshold against a wider sample.")).toBeTruthy();
    // Heuristic list (secondary).
    expect(screen.getByText("Re-check the gate threshold")).toBeTruthy();
    expect(
      screen.getByText(
        "The eligibility gate should be re-checked against a wider sample before r6 seats anything.",
      ),
    ).toBeTruthy();
    expect(screen.getAllByText(/r5-2026-08/).length).toBeGreaterThan(0);
  });

  it("renders the warning callout when pre_registered is false, with the reason in plain words", () => {
    const { container } = render(
      <NextRoundPanel
        briefing={nextRoundBriefing({ pre_registered: false, plan_path: null, focus: null })}
        phase="loaded"
        message={null}
      />,
    );

    expect(container.querySelector(".comp-next-preregistration-warning")).toBeTruthy();
    expect(screen.getByText("No committed plan")).toBeTruthy();
    expect(screen.getByText(/plan committed before any run exists/i)).toBeTruthy();
  });

  it("does not render the warning callout when pre_registered is true", () => {
    const { container } = render(
      <NextRoundPanel briefing={nextRoundBriefing({ pre_registered: true })} phase="loaded" message={null} />,
    );

    expect(container.querySelector(".comp-next-preregistration-warning")).toBeNull();
    expect(screen.queryByText("No committed plan")).toBeNull();
  });

  it("says focus is unset when focus is null and the round is not pre-registered", () => {
    render(
      <NextRoundPanel
        briefing={nextRoundBriefing({ pre_registered: false, plan_path: null, focus: null })}
        phase="loaded"
        message={null}
      />,
    );

    expect(screen.getByText(/focus is unset/i)).toBeTruthy();
  });

  it("renders the explicit empty wording when both carries-forward lists are empty, not an empty container", () => {
    const { container } = render(
      <NextRoundPanel
        briefing={nextRoundBriefing({ authored_carries_forward: [], carries_forward: [] })}
        phase="loaded"
        message={null}
      />,
    );

    expect(screen.getByText("Nothing recorded as carrying forward.")).toBeTruthy();
    expect(container.querySelector(".comp-next-authored-list")).toBeNull();
    expect(container.querySelector(".comp-next-heuristic-list")).toBeNull();
  });

  it("says the previous round recorded nothing explicit when authored_carries_forward is empty, without promoting the heuristic list into the primary slot", () => {
    render(
      <NextRoundPanel
        briefing={nextRoundBriefing({
          previous_round_id: "r5-2026-08",
          authored_carries_forward: [],
          carries_forward: [roundFinding({ title: "Heuristic-only item" })],
        })}
        phase="loaded"
        message={null}
      />,
    );

    expect(screen.getByText(/r5-2026-08 recorded nothing explicit/i)).toBeTruthy();
    // The heuristic list still renders, but the empty-authored message is not silently replaced by it.
    expect(screen.getByText("Heuristic-only item")).toBeTruthy();
  });

  it("renders the authored and heuristic carries-forward lists as distinguishable blocks, never merged", () => {
    const { container } = render(
      <NextRoundPanel
        briefing={nextRoundBriefing({
          authored_carries_forward: ["Authored-only conclusion."],
          carries_forward: [roundFinding({ id: "h1", title: "Heuristic-only flag", carries_forward: true })],
        })}
        phase="loaded"
        message={null}
      />,
    );

    const authoredBlock = container.querySelector(".comp-next-authored-list") as HTMLElement;
    const heuristicBlock = container.querySelector(".comp-next-heuristic-list") as HTMLElement;
    expect(authoredBlock).toBeTruthy();
    expect(heuristicBlock).toBeTruthy();

    // The item unique to the heuristic (parser) list must not appear inside the authored block -- a
    // component that silently merged the two lists into one would fail this.
    expect(authoredBlock.textContent).not.toContain("Heuristic-only flag");
    expect(heuristicBlock.textContent).toContain("Heuristic-only flag");
    expect(authoredBlock.textContent).toContain("Authored-only conclusion.");
    expect(heuristicBlock.textContent).not.toContain("Authored-only conclusion.");

    // The heuristic block is labelled with its own uncertainty, distinguishing it from the record.
    expect(screen.getByText(/findings parser/i)).toBeTruthy();
  });

  it("omits the blockers block entirely when blockers is empty", () => {
    const { container } = render(
      <NextRoundPanel briefing={nextRoundBriefing({ blockers: [] })} phase="loaded" message={null} />,
    );

    expect(container.querySelector(".comp-next-blockers")).toBeNull();
  });

  it("surfaces blockers without hiding or disabling the run affordance", () => {
    const onRun = vi.fn();
    render(
      <NextRoundPanel
        briefing={nextRoundBriefing({ blockers: ["r5's DEFECTS.md entry has not been resolved."] })}
        phase="loaded"
        message={null}
        onRun={onRun}
      />,
    );

    expect(screen.getByText("r5's DEFECTS.md entry has not been resolved.")).toBeTruthy();
    const button = screen.getByRole("button", { name: /go to run form/i }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);

    fireEvent.click(button);
    expect(onRun).toHaveBeenCalledTimes(1);
  });

  it("does not render a run button when onRun is not provided", () => {
    render(<NextRoundPanel briefing={nextRoundBriefing()} phase="loaded" message={null} />);

    expect(screen.queryByRole("button", { name: /go to run form/i })).toBeNull();
  });

  it("renders the actual error message on phase 'error', not a generic string", () => {
    render(<NextRoundPanel briefing={null} phase="error" message="next-round endpoint returned 503" />);

    expect(screen.getByText("next-round endpoint returned 503")).toBeTruthy();
  });

  it("renders a loading placeholder on phase 'loading'", () => {
    render(<NextRoundPanel briefing={null} phase="loading" message={null} />);

    expect(screen.getByText(/loading next-round briefing/i)).toBeTruthy();
  });
});

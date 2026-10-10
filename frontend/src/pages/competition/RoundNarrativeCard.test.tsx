/**
 * `RoundNarrativeCard`'s honesty rules, at render level -- mirrors `FindingsSection.test.tsx`'s
 * approach: this component takes its data as props (the parent owns the fetch), so there is no API
 * module to stub here, only a fixture that mirrors `@/api/competition`'s `RoundNarrative` wire type
 * field for field.
 *
 * What these tests pin, matching the task's definition of done:
 *  - the happy path renders every field;
 *  - `outcome` with two `\n\n`-delimited paragraphs renders as two separate `<p>` elements, asserted on
 *    element count rather than substring -- the plain-text contract, not markdown;
 *  - `owner_override: null` renders no override callout at all, and a non-null value renders a visible,
 *    clearly-labelled one -- both directions asserted, so a component that always renders the callout
 *    (or never does) fails one of the two;
 *  - `seated: []` renders the explicit "seated nothing" sentence, not an empty container;
 *  - the notFound state renders the designed "no authored narrative yet" message, not a blank area or
 *    the generic error copy;
 *  - the outcome's `Collapsible` starts closed (`open === false` on the `<details>`), its paragraphs
 *    are nonetheless present in the DOM while collapsed (`Collapsible` always mounts children -- only
 *    a visibility-based query would see otherwise), clicking the `<summary>` opens it, and the
 *    headline/focus stay visible without expanding anything.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RoundNarrative } from "@/api/competition";
import RoundNarrativeCard from "@/pages/competition/RoundNarrativeCard";

// --- fixtures --------------------------------------------------------------------------------------

function roundNarrative(overrides: Partial<RoundNarrative> = {}): RoundNarrative {
  return {
    round_id: "r5-2026-08",
    title: "r5 — Choppy markets, tighter gates",
    focus: "Whether the eligibility gate holds up in a choppy window.",
    headline: "The gate held, but only two cards cleared it.",
    outcome:
      "The round ran eight cards across three windows.\n\nOnly two cleared the eligibility gate, both mean-reversion disciplines.",
    seated: ["c07-chop", "c02-volatility"],
    owner_override: null,
    carries_forward: ["Re-check the gate threshold against a wider sample."],
    sources: ["rounds/r5-2026-08/SELECTION.md"],
    ...overrides,
  };
}

// --- tests ------------------------------------------------------------------------------------------

describe("RoundNarrativeCard", () => {
  it("renders every field on the happy path", () => {
    render(<RoundNarrativeCard narrative={roundNarrative()} phase="loaded" message={null} notFound={false} />);

    expect(screen.getByText("r5 — Choppy markets, tighter gates")).toBeTruthy();
    expect(screen.getByText("The gate held, but only two cards cleared it.")).toBeTruthy();
    expect(screen.getByText("Whether the eligibility gate holds up in a choppy window.")).toBeTruthy();
    expect(screen.getByText("Re-check the gate threshold against a wider sample.")).toBeTruthy();
    expect(screen.getByText("rounds/r5-2026-08/SELECTION.md")).toBeTruthy();
    expect(screen.getByText("c07-chop")).toBeTruthy();
    expect(screen.getByText("c02-volatility")).toBeTruthy();
  });

  it("renders outcome with two \\n\\n-delimited paragraphs as two separate <p> elements", () => {
    const { container } = render(
      <RoundNarrativeCard narrative={roundNarrative()} phase="loaded" message={null} notFound={false} />,
    );

    const paragraphs = container.querySelectorAll(".comp-narrative-outcome-p");
    expect(paragraphs.length).toBe(2);
    expect(paragraphs[0]?.textContent).toBe("The round ran eight cards across three windows.");
    expect(paragraphs[1]?.textContent).toBe(
      "Only two cleared the eligibility gate, both mean-reversion disciplines.",
    );
  });

  it("renders no override callout when owner_override is null", () => {
    const { container } = render(
      <RoundNarrativeCard
        narrative={roundNarrative({ owner_override: null })}
        phase="loaded"
        message={null}
        notFound={false}
      />,
    );

    expect(container.querySelector(".comp-narrative-override")).toBeNull();
    expect(screen.queryByText("Owner override")).toBeNull();
  });

  it("renders a visible, clearly-labelled callout when owner_override is non-null", () => {
    const { container } = render(
      <RoundNarrativeCard
        narrative={roundNarrative({
          owner_override: "Seated c02-volatility despite missing the gate -- owner call, see SELECTION.md.",
        })}
        phase="loaded"
        message={null}
        notFound={false}
      />,
    );

    expect(container.querySelector(".comp-narrative-override")).toBeTruthy();
    expect(screen.getByText("Owner override")).toBeTruthy();
    expect(
      screen.getByText("Seated c02-volatility despite missing the gate -- owner call, see SELECTION.md."),
    ).toBeTruthy();
  });

  it("renders the explicit 'seated nothing' sentence for an empty seated array, not an empty container", () => {
    const { container } = render(
      <RoundNarrativeCard narrative={roundNarrative({ seated: [] })} phase="loaded" message={null} notFound={false} />,
    );

    expect(screen.getByText("This round seated nothing.")).toBeTruthy();
    expect(container.querySelector(".comp-narrative-seated-chips")).toBeNull();
  });

  it("omits the carries-forward block entirely when carries_forward is empty", () => {
    const { container } = render(
      <RoundNarrativeCard
        narrative={roundNarrative({ carries_forward: [] })}
        phase="loaded"
        message={null}
        notFound={false}
      />,
    );

    expect(container.querySelector(".comp-narrative-carries")).toBeNull();
  });

  it("renders the designed empty state for notFound, not blank or a generic error", () => {
    render(<RoundNarrativeCard narrative={null} phase="loaded" message={null} notFound />);

    expect(screen.getByText(/no authored narrative yet/i)).toBeTruthy();
    expect(screen.queryByText(/could not load/i)).toBeNull();
  });

  it("renders the actual error message on phase 'error', not a generic string", () => {
    render(
      <RoundNarrativeCard narrative={null} phase="error" message="narrative endpoint returned 503" notFound={false} />,
    );

    expect(screen.getByText("narrative endpoint returned 503")).toBeTruthy();
  });

  it("renders a loading placeholder on phase 'loading'", () => {
    render(<RoundNarrativeCard narrative={null} phase="loading" message={null} notFound={false} />);

    expect(screen.getByText(/loading round narrative/i)).toBeTruthy();
  });

  it("collapses the outcome by default", () => {
    const { container } = render(
      <RoundNarrativeCard narrative={roundNarrative()} phase="loaded" message={null} notFound={false} />,
    );

    const details = container.querySelector(".comp-narrative-outcome-collapsible");
    expect(details).toBeTruthy();
    expect((details as HTMLDetailsElement).open).toBe(false);
  });

  it("still mounts the outcome paragraphs in the DOM while collapsed", () => {
    render(<RoundNarrativeCard narrative={roundNarrative()} phase="loaded" message={null} notFound={false} />);

    const outcome = screen.getByTestId("comp-narrative-outcome");
    const paragraphs = outcome.querySelectorAll("p");
    expect(paragraphs.length).toBe(2);
    expect(paragraphs[0]?.textContent).toBe("The round ran eight cards across three windows.");
  });

  it("expands the outcome when the summary is clicked", () => {
    const { container } = render(
      <RoundNarrativeCard narrative={roundNarrative()} phase="loaded" message={null} notFound={false} />,
    );

    const details = container.querySelector(".comp-narrative-outcome-collapsible") as HTMLDetailsElement;
    const summary = details.querySelector("summary") as HTMLElement;
    expect(details.open).toBe(false);

    summary.click();

    expect(details.open).toBe(true);
  });

  it("shows the headline and focus without expanding the outcome", () => {
    render(<RoundNarrativeCard narrative={roundNarrative()} phase="loaded" message={null} notFound={false} />);

    expect(screen.getByText("The gate held, but only two cards cleared it.")).toBeTruthy();
    expect(screen.getByText("Whether the eligibility gate holds up in a choppy window.")).toBeTruthy();
  });
});

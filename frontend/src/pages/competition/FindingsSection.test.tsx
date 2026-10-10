/**
 * `FindingsSection`'s honesty rules, at render level -- mirrors `Competition.test.tsx`'s approach one
 * level down: this component takes its data as props (the parent owns the fetch), so there is no API
 * module to stub here, only fixtures that mirror `@/api/competition`'s wire types field for field.
 *
 * What these tests pin, matching the task's definition of done:
 *  - `carries_forward: true` puts an entry in "Carried forward" regardless of its `kind` -- proven
 *    with a `"defect"` entry, since `kind === "follow-up"` is deliberately *not* the filter;
 *  - a `carries_forward: false` entry of any kind is left out of "Carried forward";
 *  - a `kind` string the frontend has never seen renders under its own raw text rather than going
 *    blank or throwing -- the same contract-drift concern `api/competition.ts`'s module docstring
 *    documents for `JobRunStatus`;
 *  - `notFound: true` renders the designed empty state, not the generic error copy;
 *  - `phase === "error"` renders `props.message` verbatim;
 *  - `body` renders as literal text -- a `<script>` tag inside it never becomes a DOM element;
 *  - the round picker sorts newest-first by `sequence`, not by `round_id` as a string.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { FindingsResponse, RoundFinding, RoundSummary } from "@/api/competition";
import FindingsSection from "@/pages/competition/FindingsSection";

// --- fixtures --------------------------------------------------------------------------------------

function roundFinding(overrides: Partial<RoundFinding> = {}): RoundFinding {
  return {
    id: "f1",
    round_id: "r5-2026-08",
    kind: "finding",
    title: "A finding",
    body: "Plain body text.",
    source: "SELECTION.md § 8",
    carries_forward: false,
    ...overrides,
  };
}

function findingsResponse(overrides: Partial<FindingsResponse> = {}): FindingsResponse {
  return {
    round_id: "r5-2026-08",
    findings: [],
    follow_ups: [],
    sources: ["SELECTION.md"],
    ...overrides,
  };
}

function roundSummary(overrides: Partial<RoundSummary> = {}): RoundSummary {
  return {
    round_id: "r5-2026-08",
    label: "r5 — Aug 2026",
    windows: ["gfc"],
    agents: 10,
    has_report: true,
    has_brief: true,
    has_results: true,
    has_selection: true,
    sequence: 5,
    ...overrides,
  };
}

const noop = () => {};

// --- tests ------------------------------------------------------------------------------------------

describe("FindingsSection", () => {
  it("puts a carries_forward defect in Carried forward, and leaves out a non-carrying finding", () => {
    const carriedDefect = roundFinding({
      id: "d1",
      kind: "defect",
      title: "Drawdown calc double-counts a flat day",
      carries_forward: true,
    });
    const nonCarryingFinding = roundFinding({
      id: "f2",
      kind: "finding",
      title: "Mean reversion held up in choppy windows",
      carries_forward: false,
    });

    render(
      <FindingsSection
        rounds={[roundSummary()]}
        roundsPhase="loaded"
        selectedRoundId="r5-2026-08"
        onSelectRound={noop}
        findings={findingsResponse({ findings: [carriedDefect, nonCarryingFinding] })}
        phase="loaded"
        message={null}
        notFound={false}
      />,
    );

    const carried = screen.getByRole("region", { name: "Carried forward" });
    // The flag put it here, not the kind -- kind is "defect", not "follow-up".
    expect(within(carried).getByText("Drawdown calc double-counts a flat day")).toBeTruthy();
    expect(within(carried).queryByText("Mean reversion held up in choppy windows")).toBeNull();

    // The Full record section below still carries both entries -- this is the same record, not a
    // narrower one.
    expect(screen.getAllByText("Drawdown calc double-counts a flat day").length).toBe(2);
    expect(screen.getByText("Mean reversion held up in choppy windows")).toBeTruthy();
  });

  it("renders a kind the frontend has never seen under its own raw key, not blank or thrown", () => {
    const mystery = roundFinding({
      id: "m1",
      kind: "risk-flag" as unknown as RoundFinding["kind"],
      title: "Unclassified entry",
      carries_forward: false,
    });

    expect(() =>
      render(
        <FindingsSection
          rounds={[roundSummary()]}
          roundsPhase="loaded"
          selectedRoundId="r5-2026-08"
          onSelectRound={noop}
          findings={findingsResponse({ findings: [mystery] })}
          phase="loaded"
          message={null}
          notFound={false}
        />,
      ),
    ).not.toThrow();

    expect(screen.getByText("Unclassified entry")).toBeTruthy();
    // The raw key, not blank -- `findingKindLabel`'s fallback.
    expect(screen.getAllByText("risk-flag").length).toBeGreaterThan(0);
  });

  it("renders the designed empty state for a 404, not the generic error copy", () => {
    render(
      <FindingsSection
        rounds={[roundSummary()]}
        roundsPhase="loaded"
        selectedRoundId="r9-2026-08"
        onSelectRound={noop}
        findings={null}
        phase="loaded"
        message={null}
        notFound
      />,
    );

    expect(screen.getByText(/no written record for r9-2026-08 yet/i)).toBeTruthy();
    expect(screen.queryByText(/could not load/i)).toBeNull();
  });

  it("renders the actual error message on phase 'error', not a generic string", () => {
    render(
      <FindingsSection
        rounds={[roundSummary()]}
        roundsPhase="loaded"
        selectedRoundId="r5-2026-08"
        onSelectRound={noop}
        findings={null}
        phase="error"
        message="findings endpoint returned 503"
        notFound={false}
      />,
    );

    expect(screen.getByText("findings endpoint returned 503")).toBeTruthy();
  });

  it("renders a body containing a script tag as literal text, never as markup", () => {
    const dangerousBody = 'Card rule: exit when `total_return` < <script>alert(1)</script> threshold.';
    const { container } = render(
      <FindingsSection
        rounds={[roundSummary()]}
        roundsPhase="loaded"
        selectedRoundId="r5-2026-08"
        onSelectRound={noop}
        findings={findingsResponse({
          findings: [roundFinding({ id: "s1", body: dangerousBody, title: "Escaping check" })],
        })}
        phase="loaded"
        message={null}
        notFound={false}
      />,
    );

    // No script element was ever created from the body text.
    expect(container.querySelector("script")).toBeNull();
    // The literal characters are present as text.
    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeTruthy();
  });

  it("distinguishes 'files read, nothing parseable' from 'nothing written' using sources", () => {
    const { rerender } = render(
      <FindingsSection
        rounds={[roundSummary()]}
        roundsPhase="loaded"
        selectedRoundId="r5-2026-08"
        onSelectRound={noop}
        findings={findingsResponse({ findings: [], sources: ["SELECTION.md", "DEFECTS.md"] })}
        phase="loaded"
        message={null}
        notFound={false}
      />,
    );
    expect(screen.getByText(/nothing parseable was found/i)).toBeTruthy();

    rerender(
      <FindingsSection
        rounds={[roundSummary()]}
        roundsPhase="loaded"
        selectedRoundId="r5-2026-08"
        onSelectRound={noop}
        findings={findingsResponse({ findings: [], sources: [] })}
        phase="loaded"
        message={null}
        notFound={false}
      />,
    );
    expect(screen.getByText(/wrote nothing down/i)).toBeTruthy();
    expect(screen.queryByText(/nothing parseable was found/i)).toBeNull();
  });

  it("sorts the round picker newest-first by sequence, not by round_id string order", () => {
    const onSelectRound = vi.fn();
    render(
      <FindingsSection
        rounds={[
          roundSummary({ round_id: "r9-2026-04", label: "r9", sequence: 9 }),
          roundSummary({ round_id: "r13-2026-08", label: "r13", sequence: 13 }),
          roundSummary({ round_id: "r2-2025-11", label: "r2", sequence: 2 }),
        ]}
        roundsPhase="loaded"
        selectedRoundId="r13-2026-08"
        onSelectRound={onSelectRound}
        findings={findingsResponse()}
        phase="loaded"
        message={null}
        notFound={false}
      />,
    );

    const select = screen.getByLabelText("Round") as HTMLSelectElement;
    const optionLabels = Array.from(select.options).map((o) => o.textContent);
    // r13 (sequence 13) first, then r9, then r2 -- lexicographic string order would put r13 before r2
    // before r9, so this pins the numeric-by-sequence requirement specifically.
    //
    // The option text is derived from `round_id` (see `roundOption.ts`), never the authored `label`,
    // so a round whose label is a whole sentence cannot widen the control -- which is why these read
    // "r13 · Aug 2026" rather than the fixtures' own "r13".
    expect(optionLabels).toEqual(["r13 · Aug 2026", "r9 · Apr 2026", "r2 · Nov 2025"]);
    // The label itself is not lost -- it renders under the select instead.
    expect(screen.getByText("r13")).toBeTruthy();

    fireEvent.change(select, { target: { value: "r2-2025-11" } });
    expect(onSelectRound).toHaveBeenCalledWith("r2-2025-11");
  });
});

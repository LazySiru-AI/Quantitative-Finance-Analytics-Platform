/**
 * `outcomeText`'s exhaustiveness guard, mirroring `src/api/labels.test.ts`'s
 * "renders an unknown server value instead of throwing" tests for the sibling `outcomeLabel`/
 * `verdictLabel` functions in `@/api/thesis`.
 *
 * `outcomeText` used to call a local `assertNeverOutcome` that threw on any `LoopOutcome` its
 * `switch` did not list. `LoopOutcome` describes a value the *server* sends, not one this code
 * constructs, so a throwing default closed the compile-time exhaustiveness hole but reopened a
 * worse one at runtime: the first outcome value this build had not been updated for would take the
 * whole Thesis page down over one render, the exact failure `docs/reports/defects-1.md` first
 * recorded for `outcomeLabel` (see `src/api/labels.test.ts`'s module docstring). Fixed to degrade to
 * the raw wire value instead, matching that file's already-fixed siblings.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { LoopOutcome, LoopResult } from "@/api/thesis";
import { ThesisSection, outcomeText } from "@/pages/Thesis";

function loopResult(overrides: Partial<LoopResult> = {}): LoopResult {
  return {
    symbol: "SPY",
    interval: "1d",
    started_at: "2026-08-01T00:00:00Z",
    finished_at: "2026-08-01T00:05:00Z",
    outcome: "survivor_found",
    budget: 12,
    iterations_used: 3,
    records: [],
    cards: [],
    ledger: null,
    holdout: null,
    warnings: [],
    ...overrides,
  };
}

/**
 * The section form, which is how this surface is mounted now: `/thesis/:symbol?` redirects into
 * Evidence's Thesis tab, and the symbol arrives as a prop rather than a route param. What matters
 * here is that the symbol still comes in and still goes back out -- and that the section renders no
 * `<h1>` of its own, since the page it sits inside already has one.
 *
 * `symbol={null}` is the empty prompt, which fetches nothing. The detail branch is not rendered here:
 * it mounts the ledger/holdout fetches, and `useThesis`'s stubbing belongs with the hook's own tests,
 * not in this file whose subject is `outcomeText`.
 */
describe("ThesisSection", () => {
  it("renders the empty prompt with no <h1>, and reports a submitted symbol upper-cased", () => {
    const onSymbolChange = vi.fn<(symbol: string) => void>();
    render(
      <MemoryRouter>
        <ThesisSection symbol={null} onSymbolChange={onSymbolChange} />
      </MemoryRouter>,
    );

    // The host page owns the page title; a second `<h1>` inside it is a document-outline error.
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();

    const input = screen.getByRole("textbox", { name: "Symbol" });
    fireEvent.change(input, { target: { value: "nvda" } });
    fireEvent.click(screen.getByRole("button", { name: "Go" }));

    // Upper-cased on the way out, so the caller never has to normalise it back.
    expect(onSymbolChange).toHaveBeenCalledWith("NVDA");
  });

  it("does not navigate on an empty submission", () => {
    const onSymbolChange = vi.fn<(symbol: string) => void>();
    render(
      <MemoryRouter>
        <ThesisSection symbol={null} onSymbolChange={onSymbolChange} />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Go" }));

    expect(onSymbolChange).not.toHaveBeenCalled();
  });
});

describe("outcomeText", () => {
  it("renders distinct prose for every known outcome", () => {
    const outcomes: LoopOutcome[] = [
      "survivor_found",
      "budget_exhausted",
      "catalogue_exhausted",
      "no_data",
      "holdout_unavailable",
    ];
    const seen = new Set<string>();
    for (const outcome of outcomes) {
      const text = outcomeText(loopResult({ outcome }));
      expect(text, `${outcome} produced no text`).toBeTruthy();
      expect(seen.has(text), `${outcome} duplicated another outcome's text`).toBe(false);
      seen.add(text);
    }
  });

  it("renders an unknown server value instead of throwing", () => {
    // This is exactly the drift `src/api/labels.test.ts` guards against for `outcomeLabel`, one
    // layer over: a `LoopOutcome` this build has never heard of. The old `assertNeverOutcome` threw,
    // which escapes render entirely and blanks the whole page over one unrecognised outcome.
    const fromAFutureBackend = "budget_exceeded_with_survivor" as LoopOutcome;
    const result = loopResult({ outcome: fromAFutureBackend });
    expect(() => outcomeText(result)).not.toThrow();
    expect(outcomeText(result)).toBe(fromAFutureBackend);
  });
});

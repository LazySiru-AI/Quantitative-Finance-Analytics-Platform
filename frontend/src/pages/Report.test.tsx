/**
 * Smoke test for the height-cut pass on Report.tsx: the page renders, the first narrative section
 * stays open while a later one starts collapsed behind a `Collapsible`, the disclaimer stays on
 * screen, and a `MarketWarning.kind` shows as a translated `StatusPill`, never the raw wire token.
 *
 * `StrategyCard` and `FactTable` are left real (see this page's own imports) -- neither fetches on
 * mount, so rendering them costs nothing here and proves this page still mounts them at all
 * (the same rationale `Ticker.test.tsx` gives for not mocking `NewsPanel`).
 */
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { Report as ReportData, ReportSection } from "@/api/report";
import type { ReportState } from "@/hooks/useReport";

const reportMock = vi.fn<() => ReportState>();

// `useReport` and `useStrategy` (used by the real, unmocked `StrategyCard`) both live in this one
// module -- only `useReport` is replaced, everything else passes through untouched.
vi.mock("@/hooks/useReport", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useReport")>();
  return { ...actual, useReport: () => reportMock() };
});

const { default: Report } = await import("@/pages/Report");

function section(overrides: Partial<ReportSection> & Pick<ReportSection, "section_id" | "title">): ReportSection {
  return {
    narrative: {
      text: `Narrative body for ${overrides.title}.`,
      draft: { text: "", source: "model", model: null, temperature: null },
      grounding: { grounded: true, violations: [], cited: [], caveat: "Every figure above resolves to a fact." },
      cited_facts: [],
    },
    fact_ids: [],
    warnings: [],
    ...overrides,
  };
}

function report(overrides: Partial<ReportData> = {}): ReportData {
  return {
    symbol: "AAPL",
    interval: "1d",
    generated_at: "2026-09-05T12:00:00Z",
    profile: null,
    quote: null,
    bundle: { symbol: "AAPL", interval: "1d", generated_at: "2026-09-05T12:00:00Z", facts: {}, warnings: [] },
    sections: [
      section({ section_id: "overview", title: "Overview" }),
      section({ section_id: "risk", title: "Risk profile" }),
    ],
    drawdown: null,
    decisions: null,
    strategy: null,
    run_id: null,
    warnings: [],
    disclaimer: "This report is not investment advice.",
    ...overrides,
  };
}

function renderReport() {
  return render(
    <MemoryRouter initialEntries={["/report/AAPL"]}>
      <Routes>
        <Route path="/report/:symbol" element={<Report />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Report page", () => {
  it("keeps the first narrative section open and the disclaimer visible", async () => {
    reportMock.mockReturnValue({ report: report(), phase: "loaded", message: null });

    renderReport();

    expect(await screen.findByText("Overview")).toBeTruthy();
    expect(screen.getByText("Narrative body for Overview.")).toBeTruthy();
    expect(screen.getByText("This report is not investment advice.")).toBeTruthy();
  });

  it("collapses every narrative section after the first behind a closed disclosure", async () => {
    reportMock.mockReturnValue({ report: report(), phase: "loaded", message: null });

    renderReport();

    await screen.findByText("Overview");

    // "Risk profile" appears twice once the disclosure is present: once as the `Collapsible`
    // summary (title text reused as the disclosure label, see `NarrativeSections`' own comment),
    // and once more as `NarrativeSection`'s own heading inside the collapsed body. The summary is
    // the one actually inside a `<summary>` element.
    const riskTitles = screen.getAllByText("Risk profile");
    const summaryTitle = riskTitles.find((el) => el.closest("summary") !== null);
    expect(summaryTitle).toBeTruthy();
    const details = summaryTitle?.closest("details");
    expect(details).toBeTruthy();
    expect(details?.hasAttribute("open")).toBe(false);

    // Native `<details>` never unmounts its body -- the app's own `Collapsible` docstring is
    // explicit that content stays in the DOM, just not painted, so find-in-page keeps working.
    expect(within(details as HTMLElement).getByText("Narrative body for Risk profile.")).toBeTruthy();
  });

  it("shows a translated pill for a warning kind, never the raw wire token", async () => {
    reportMock.mockReturnValue({
      report: report({
        warnings: [{ kind: "clamped", message: "Value clamped to the 52-week range." }],
      }),
      phase: "loaded",
      message: null,
    });

    renderReport();

    expect(await screen.findByText("Clamped")).toBeTruthy();
    expect(screen.getByText("Value clamped to the 52-week range.")).toBeTruthy();
    expect(screen.queryByText("clamped")).toBeNull();
  });

  it("still shows the loading state before the report resolves", () => {
    reportMock.mockReturnValue({ report: null, phase: "loading", message: null });

    renderReport();

    expect(screen.getByText("Loading report for AAPL…")).toBeTruthy();
  });
});

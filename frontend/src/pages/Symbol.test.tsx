/**
 * That `Symbol.tsx` (the merged Ticker + Report page, UX refactor 2.1) mounts exactly one of its
 * five views at a time, switches which one on a tab click, and defaults to Chart.
 *
 * Follows `Ticker.test.tsx` and `Report.test.tsx`'s own mocking boundary exactly, since this page
 * renders the same `Ticker*View`/`ReportView` components those two files already exercise --
 * everything each of those views fetches is stubbed at its module boundary, and only the
 * composition (which view is on screen, and that switching tabs unmounts the previous one) is
 * actually under test here.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { TickerNewsPanel } from "@/api/news";
import type { Report as ReportData, ReportSection } from "@/api/report";
import type { ReportState } from "@/hooks/useReport";

const tickerNewsMock = vi.fn<() => Promise<TickerNewsPanel>>();
const reportMock = vi.fn<() => ReportState>();

vi.mock("@/api/news", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/news")>();
  return { ...actual, newsApi: { ...actual.newsApi, ticker: () => tickerNewsMock() } };
});

// The ticker summary fetch never resolves -- nothing in these tests needs the profile/quote header,
// only that the Chart tab's own always-rendered chrome (its heading, the rule editor) is on screen.
vi.mock("@/api/market", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/market")>();
  return {
    ...actual,
    marketApi: { ...actual.marketApi, ticker: () => new Promise(() => {}) },
  };
});
vi.mock("@/components/DecisionTable", () => ({ default: () => <div>decision table</div> }));
vi.mock("@/components/RuleEditor", () => ({ default: () => <div>rule editor</div> }));
vi.mock("@/components/InstitutionalHolders", () => ({ default: () => <div>filers</div> }));
vi.mock("@/components/Chart", () => ({ default: () => <div>chart</div> }));
vi.mock("@/components/TimeframeGrid", () => ({ default: () => <div>grid</div> }));
vi.mock("@/hooks/useChartSeries", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useChartSeries")>();
  return {
    ...actual,
    useChartSeries: () => ({ bars: [], phase: "loaded", message: null, warnings: [] }),
  };
});
vi.mock("@/hooks/useReport", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useReport")>();
  return { ...actual, useReport: () => reportMock() };
});

const { default: Symbol } = await import("@/pages/Symbol");

function newsPanel(overrides: Partial<TickerNewsPanel> = {}): TickerNewsPanel {
  return {
    symbol: "AAPL",
    generated_at: "2026-09-06T18:00:00Z",
    as_of: null,
    news: [],
    news_source: "yahoo_news",
    social: null,
    warnings: [],
    ...overrides,
  };
}

function reportSection(
  overrides: Partial<ReportSection> & Pick<ReportSection, "section_id" | "title">,
): ReportSection {
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
    generated_at: "2026-09-06T12:00:00Z",
    profile: null,
    quote: null,
    bundle: { symbol: "AAPL", interval: "1d", generated_at: "2026-09-06T12:00:00Z", facts: {}, warnings: [] },
    sections: [reportSection({ section_id: "overview", title: "Overview" })],
    drawdown: null,
    decisions: null,
    strategy: null,
    run_id: null,
    warnings: [],
    disclaimer: "This report is not investment advice.",
    ...overrides,
  };
}

function renderSymbol() {
  return render(
    <MemoryRouter initialEntries={["/symbol/AAPL"]}>
      <Routes>
        <Route path="/symbol/:symbol" element={<Symbol />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("the Symbol page", () => {
  it("shows the symbol heading and defaults to the Chart tab", async () => {
    tickerNewsMock.mockResolvedValue(newsPanel());
    reportMock.mockReturnValue({ report: null, phase: "loading", message: null });

    renderSymbol();

    expect(await screen.findByRole("heading", { name: "AAPL", level: 1 })).toBeTruthy();
    // The rule editor only ever mounts as part of the Chart tab's content.
    expect(await screen.findByText("rule editor")).toBeTruthy();
    expect(screen.queryByText("decision table")).toBeNull();
    expect(screen.queryByText("filers")).toBeNull();
  });

  it("mounts the Decision view, and only the Decision view, once that tab is picked", async () => {
    tickerNewsMock.mockResolvedValue(newsPanel());
    reportMock.mockReturnValue({ report: null, phase: "loading", message: null });

    renderSymbol();
    await screen.findByText("rule editor");

    fireEvent.click(screen.getByRole("tab", { name: "Decision" }));

    expect(await screen.findByText("decision table")).toBeTruthy();
    // Switching tabs unmounts the previous one -- Symbol.tsx never keeps every section in the DOM
    // the way the old, un-merged `/ticker` page's `TickerView` does.
    expect(screen.queryByText("rule editor")).toBeNull();
  });

  it("mounts the Report view, fetched through useReport, once that tab is picked", async () => {
    tickerNewsMock.mockResolvedValue(newsPanel());
    reportMock.mockReturnValue({ report: report(), phase: "loaded", message: null });

    renderSymbol();
    await screen.findByText("rule editor");

    fireEvent.click(screen.getByRole("tab", { name: "Report" }));

    expect(await screen.findByText("Overview")).toBeTruthy();
    expect(screen.getByText("This report is not investment advice.")).toBeTruthy();
  });

  it("mounts the Holders view once that tab is picked", async () => {
    tickerNewsMock.mockResolvedValue(newsPanel());
    reportMock.mockReturnValue({ report: null, phase: "loading", message: null });

    renderSymbol();
    await screen.findByText("rule editor");

    fireEvent.click(screen.getByRole("tab", { name: "Holders" }));

    expect(await screen.findByText("filers")).toBeTruthy();
  });

  it("mounts the News view once that tab is picked", async () => {
    tickerNewsMock.mockResolvedValue(newsPanel());
    reportMock.mockReturnValue({ report: null, phase: "loading", message: null });

    renderSymbol();
    await screen.findByText("rule editor");

    fireEvent.click(screen.getByRole("tab", { name: "News" }));

    expect(await screen.findByText(/news & sentiment/i)).toBeTruthy();
  });

  it("shows the same empty-state prompt shape as Ticker.tsx when there is no symbol", async () => {
    render(
      <MemoryRouter initialEntries={["/symbol"]}>
        <Routes>
          <Route path="/symbol/:symbol?" element={<Symbol />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("lookup --symbol=_")).toBeTruthy();
    expect(screen.getByRole("button", { name: "QQQ" })).toBeTruthy();
  });

  it("links out to Research Desk, Paper Desk and Filers (UX refactor 3.3)", async () => {
    tickerNewsMock.mockResolvedValue(newsPanel());
    reportMock.mockReturnValue({ report: null, phase: "loading", message: null });

    renderSymbol();
    await screen.findByRole("heading", { name: "AAPL", level: 1 });

    // None of the three destinations take a symbol parameter today (see `Symbol.tsx`'s own comment
    // at the call site), so these are plain links, not `/research-desk/AAPL`-shaped ones.
    expect(screen.getByRole("link", { name: "Research Desk" }).getAttribute("href")).toBe(
      "/research-desk",
    );
    expect(screen.getByRole("link", { name: "Paper Desk" }).getAttribute("href")).toBe(
      "/paper-desk",
    );
    expect(screen.getByRole("link", { name: "Filers" }).getAttribute("href")).toBe("/filers");
  });

  it("caveats the Decision tab's edge and significance figures, in view rather than behind a disclosure", async () => {
    tickerNewsMock.mockResolvedValue(newsPanel());
    reportMock.mockReturnValue({ report: null, phase: "loading", message: null });

    renderSymbol();
    await screen.findByText("rule editor");

    fireEvent.click(screen.getByRole("tab", { name: "Decision" }));
    await screen.findByText("decision table");

    const note = screen.getByRole("note");
    // Both pills, and the sentence that says what the limitation actually is. COPY-STYLE.md rule 6
    // lists "not advice" and in-sample returns as things that may be shortened but never hidden,
    // so these are asserted as VISIBLE text, not as an `InfoNote` body.
    expect(note.textContent).toContain("Not advice");
    expect(note.textContent).toContain("In-sample");
    expect(note.textContent).toContain("measured on the same bars they describe");
  });

  it("does not caveat the tabs that show no edge figure", async () => {
    tickerNewsMock.mockResolvedValue(newsPanel());
    reportMock.mockReturnValue({ report: null, phase: "loading", message: null });

    renderSymbol();
    await screen.findByText("rule editor");

    // The Chart tab prints prices, not an edge or a significance grade -- a NOT ADVICE pill on
    // every tab is a pill nobody reads on the one tab that needs it.
    expect(screen.queryByRole("note")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// The tab in the URL (finding UX-11). Symbol already kept its page-level tab in `?tab=`; these pin
// that it still does through the shared `useTabParam` hook, INCLUDING the legacy route redirect
// `App.tsx` builds on it (`/report/:symbol` -> `/symbol/:symbol?tab=report`).
// ---------------------------------------------------------------------------

/** Shows the current route's path + query, so a test can assert the tab landed in the URL. */
function SymbolLocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname + location.search}</div>;
}

function renderSymbolAt(initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <SymbolLocationProbe />
      <Routes>
        <Route path="/symbol/:symbol" element={<Symbol />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("the Symbol page's tab in the URL", () => {
  it("opens on the Report tab for ?tab=report, the shape App.tsx's /report redirect produces", async () => {
    tickerNewsMock.mockResolvedValue(newsPanel());
    reportMock.mockReturnValue({ report: null, phase: "loading", message: null });

    renderSymbolAt("/symbol/AAPL?tab=report");

    const reportTab = await screen.findByRole("tab", { name: "Report" });
    expect(reportTab.getAttribute("aria-selected")).toBe("true");
  });

  it("opens on the News tab for ?tab=news", async () => {
    tickerNewsMock.mockResolvedValue(newsPanel());
    reportMock.mockReturnValue({ report: null, phase: "loading", message: null });

    renderSymbolAt("/symbol/AAPL?tab=news");

    const newsTab = await screen.findByRole("tab", { name: "News" });
    expect(newsTab.getAttribute("aria-selected")).toBe("true");
  });

  it("clicking a tab puts it in the URL, keeping the /symbol/:symbol path intact", async () => {
    tickerNewsMock.mockResolvedValue(newsPanel());
    reportMock.mockReturnValue({ report: null, phase: "loading", message: null });

    renderSymbolAt("/symbol/AAPL");

    fireEvent.click(await screen.findByRole("tab", { name: "News" }));

    const url = screen.getByTestId("location-probe").textContent ?? "";
    expect(url).toContain("tab=news");
    // The route param is a path segment, not a query param, and must survive the rewrite.
    expect(url).toContain("/symbol/AAPL");
  });

  it("falls back to Chart for an unrecognised ?tab= value rather than mounting no view", async () => {
    tickerNewsMock.mockResolvedValue(newsPanel());
    reportMock.mockReturnValue({ report: null, phase: "loading", message: null });

    renderSymbolAt("/symbol/AAPL?tab=not-a-real-tab");

    const chartTab = await screen.findByRole("tab", { name: "Chart" });
    expect(chartTab.getAttribute("aria-selected")).toBe("true");
  });
});

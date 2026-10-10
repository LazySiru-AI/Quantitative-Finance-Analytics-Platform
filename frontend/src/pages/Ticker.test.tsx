/**
 * That the Ticker page actually mounts the News & Sentiment panel.
 *
 * This file exists because nothing else could catch its absence. `App.test.tsx` mocks
 * `@/pages/Ticker` wholesale to test routing, `NewsPanel.test.tsx` renders the panel in isolation,
 * and the backend suite proves `/api/news/ticker/{symbol}` answers — every one of those stays green
 * if the panel is never placed on the page at all. A built component that no route renders is
 * indistinguishable, from a test suite, from a shipped feature.
 *
 * Everything on the page that fetches is stubbed at its module boundary, following
 * `Institutions.test.tsx`. `NewsPanel` is deliberately **not** mocked — it is the thing under test
 * here, and mocking it would reduce this file to asserting that a mock renders.
 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TickerNewsPanel } from "@/api/news";

const tickerNewsMock = vi.fn<() => Promise<TickerNewsPanel>>();

vi.mock("@/api/news", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/news")>();
  return { ...actual, newsApi: { ...actual.newsApi, ticker: () => tickerNewsMock() } };
});

// Everything else on the page that reaches for the network. None of it is what this file checks.
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

const { default: Ticker } = await import("@/pages/Ticker");

function panel(overrides: Partial<TickerNewsPanel> = {}): TickerNewsPanel {
  return {
    symbol: "AAPL",
    generated_at: "2026-08-24T18:00:00Z",
    as_of: null,
    news: [
      {
        title: "Chipmakers push technology higher",
        url: "https://example.com/a",
        published: "2026-08-24T17:00:00Z",
        source: "yahoo_news",
        publisher: "MT Newswires",
        summary: null,
      },
    ],
    news_source: "yahoo_news",
    social: {
      snapshot: {
        symbol: "AAPL",
        source: "stocktwits",
        as_of: "2026-08-24T18:00:00Z",
        window_start: "2026-08-24T16:55:21Z",
        bullish: 2,
        bearish: 2,
        neutral: 8,
      },
      bull_ratio: 0.5,
      labelled_share: 4 / 12,
    },
    warnings: [],
    ...overrides,
  };
}

function renderTicker() {
  return render(
    <MemoryRouter initialEntries={["/ticker/AAPL"]}>
      <Routes>
        <Route path="/ticker/:symbol" element={<Ticker />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("the Ticker page mounts the news panel", () => {
  beforeEach(() => {
    tickerNewsMock.mockReset();
  });

  it("renders the News & sentiment section", async () => {
    tickerNewsMock.mockResolvedValue(panel());

    renderTicker();

    expect(await screen.findByText(/news & sentiment/i)).toBeTruthy();
  });

  it("asks the news API for the symbol in the route", async () => {
    tickerNewsMock.mockResolvedValue(panel());

    renderTicker();

    await screen.findByText(/news & sentiment/i);
    expect(tickerNewsMock).toHaveBeenCalled();
  });

  it("shows a headline once the panel loads", async () => {
    tickerNewsMock.mockResolvedValue(panel());

    renderTicker();

    expect(await screen.findByText(/chipmakers push technology higher/i)).toBeTruthy();
  });

  it("shows the labelled denominator beside the bull ratio, never the ratio alone", async () => {
    tickerNewsMock.mockResolvedValue(panel());

    renderTicker();

    await screen.findByText(/news & sentiment/i);
    // 8 of 12 messages carried no label. A reader must not be able to see "50%" without also
    // seeing how thin the sample behind it is, so both halves are asserted from one string --
    // matching them separately would pass even if the denominator moved to another element.
    // A function matcher, because the line is assembled from several text nodes (`{ratio} bullish ·
    // {labelled} of {total} messages labelled`) and an element-level regex cannot span them.
    expect(
      screen.getByText((_text, element) =>
        Boolean(
          element?.className === "value" &&
            /50% bullish · 4 of 12 messages labelled/.test(element.textContent ?? ""),
        ),
      ),
    ).toBeTruthy();
  });

  it("still renders the rest of the page when the news request fails", async () => {
    tickerNewsMock.mockRejectedValue(new Error("boom"));

    renderTicker();

    // The panel reports its own failure; the decision table and the filers panel survive it.
    expect(await screen.findByText(/news & sentiment/i)).toBeTruthy();
    expect(screen.getByText("decision table")).toBeTruthy();
    expect(screen.getByText("filers")).toBeTruthy();
  });
});

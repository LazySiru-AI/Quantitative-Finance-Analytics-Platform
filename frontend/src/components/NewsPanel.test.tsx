/**
 * `NewsPanel` is presentational (it fetches nothing -- `phase`/`data`/`message` are props), so every
 * test here just renders it with a hand-built `TickerNewsPanel`. The suite is built around the three
 * display rules the component exists to enforce (see the module docstring in `NewsPanel.tsx`):
 * a bull ratio never appears without its labelled-count denominator, `null` never reads as `0%`, and
 * `social: null` (unreachable) reads as a different sentence than a reachable-but-empty window.
 */
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { NewsItem, SocialSummary, TickerNewsPanel } from "@/api/news";
import NewsPanel from "@/components/NewsPanel";

function item(overrides: Partial<NewsItem> = {}): NewsItem {
  return {
    title: "Apple unveils new product line",
    url: "https://example.com/aapl-news",
    published: "2026-08-24T17:00:00Z",
    source: "yahoo_news",
    publisher: "MT Newswires",
    summary: null,
    ...overrides,
  };
}

function social(overrides: Partial<SocialSummary> = {}): SocialSummary {
  return {
    snapshot: {
      symbol: "AAPL",
      source: "stocktwits",
      as_of: "2026-08-24T18:02:00Z",
      window_start: "2026-08-24T16:55:21Z",
      bullish: 2,
      bearish: 2,
      neutral: 8,
    },
    bull_ratio: 0.5,
    labelled_share: 0.3333,
    ...overrides,
  };
}

function panel(overrides: Partial<TickerNewsPanel> = {}): TickerNewsPanel {
  return {
    symbol: "AAPL",
    generated_at: "2026-08-24T18:02:11.123Z",
    as_of: null,
    news: [item()],
    news_source: "yahoo_news",
    social: social(),
    warnings: [],
    ...overrides,
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("loading and error phases", () => {
  it("renders a loading placeholder and nothing else", () => {
    render(<NewsPanel data={null} phase="loading" message={null} />);
    expect(screen.getByText(/loading news/i)).toBeTruthy();
  });

  it("renders the error message when the fetch failed", () => {
    render(<NewsPanel data={null} phase="error" message="API returned 502: Bad Gateway" />);
    expect(screen.getByText(/502: Bad Gateway/)).toBeTruthy();
  });

  it("falls back to a generic message when none was given", () => {
    render(<NewsPanel data={null} phase="error" message={null} />);
    expect(screen.getByText(/could not load news/i)).toBeTruthy();
  });
});

describe("headlines", () => {
  it("renders each headline as an out-linking anchor with publisher and relative age", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-24T20:00:00Z"));

    render(<NewsPanel data={panel({ news: [item()] })} phase="loaded" message={null} />);

    const link = screen.getByRole("link", { name: /Apple unveils new product line/i });
    expect(link).toBeTruthy();
    expect(link.getAttribute("href")).toBe("https://example.com/aapl-news");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");

    expect(screen.getByText(/MT Newswires/)).toBeTruthy();
    // published 17:00Z, "now" pinned to 20:00Z above -- exactly 3 hours.
    expect(screen.getByText(/3h ago/)).toBeTruthy();
  });

  it("renders an explained empty state for an empty news array, not a blank box", () => {
    render(<NewsPanel data={panel({ news: [] })} phase="loaded" message={null} />);
    expect(screen.getByText(/no recent headlines/i)).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("renders a javascript: URL headline as plain text, never an anchor", () => {
    render(
      <NewsPanel
        data={panel({ news: [item({ url: "javascript:alert(1)", title: "Poisoned headline" })] })}
        phase="loaded"
        message={null}
      />,
    );

    expect(screen.getByText("Poisoned headline")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("still renders an https headline as an out-linking anchor", () => {
    render(
      <NewsPanel
        data={panel({ news: [item({ url: "https://example.com/safe", title: "Safe headline" })] })}
        phase="loaded"
        message={null}
      />,
    );

    const link = screen.getByRole("link", { name: /Safe headline/i });
    expect(link.getAttribute("href")).toBe("https://example.com/safe");
  });
});

describe("bull ratio and its denominator", () => {
  it("never renders the ratio without the labelled-count denominator beside it", () => {
    render(
      <NewsPanel
        data={panel({
          social: social({
            snapshot: {
              symbol: "AAPL",
              source: "stocktwits",
              as_of: "2026-08-24T18:02:00Z",
              window_start: "2026-08-24T16:55:21Z",
              bullish: 2,
              bearish: 2,
              neutral: 8,
            },
            bull_ratio: 0.5,
            labelled_share: 0.3333,
          }),
        })}
        phase="loaded"
        message={null}
      />,
    );

    expect(screen.getByText(/50%/)).toBeTruthy();
    expect(screen.getByText(/4 of 12 messages labelled/i)).toBeTruthy();
  });

  it("renders bull_ratio: null as an em dash, never 0%, even with a non-empty labelled count", () => {
    // Non-empty window (10 messages) where none carried a directional label -- bull_ratio is null,
    // but this is not the empty-window case: labelled_share would be 0, not null.
    render(
      <NewsPanel
        data={panel({
          social: social({
            snapshot: {
              symbol: "AAPL",
              source: "stocktwits",
              as_of: "2026-08-24T18:02:00Z",
              window_start: "2026-08-24T16:55:21Z",
              bullish: 0,
              bearish: 0,
              neutral: 10,
            },
            bull_ratio: null,
            labelled_share: 0,
          }),
        })}
        phase="loaded"
        message={null}
      />,
    );

    expect(screen.queryByText(/0%/)).toBeNull();
    expect(screen.getByText(/—\s*bullish/)).toBeTruthy();
    expect(screen.getByText(/0 of 10 messages labelled/i)).toBeTruthy();
  });
});

describe("social: null vs an empty window", () => {
  it("says the provider could not be reached when social is null", () => {
    render(<NewsPanel data={panel({ social: null })} phase="loaded" message={null} />);
    expect(screen.getByText(/could not reach a social sentiment provider/i)).toBeTruthy();
  });

  it("says the window was empty when social is present but nobody posted -- a different sentence", () => {
    render(
      <NewsPanel
        data={panel({
          social: social({
            snapshot: {
              symbol: "AAPL",
              source: "stocktwits",
              as_of: "2026-08-24T18:02:00Z",
              window_start: "2026-08-24T16:55:21Z",
              bullish: 0,
              bearish: 0,
              neutral: 0,
            },
            bull_ratio: null,
            labelled_share: null,
          }),
        })}
        phase="loaded"
        message={null}
      />,
    );

    expect(screen.getByText(/no messages were posted/i)).toBeTruthy();
    // The two messages must read as genuinely different statements, not the same copy reused.
    expect(screen.queryByText(/could not reach a social sentiment provider/i)).toBeNull();
  });
});

describe("warnings", () => {
  it("renders non-empty warnings rather than swallowing them", () => {
    render(
      <NewsPanel
        data={panel({
          warnings: [
            { kind: "provider_fallback", message: "yahoo_news unavailable, fell back to stub feed" },
          ],
        })}
        phase="loaded"
        message={null}
      />,
    );

    expect(screen.getByText("provider_fallback")).toBeTruthy();
    expect(screen.getByText(/fell back to stub feed/i)).toBeTruthy();
  });

  it("renders nothing extra when warnings is empty", () => {
    render(<NewsPanel data={panel({ warnings: [] })} phase="loaded" message={null} />);
    expect(screen.queryByText(/provider_fallback/i)).toBeNull();
  });
});

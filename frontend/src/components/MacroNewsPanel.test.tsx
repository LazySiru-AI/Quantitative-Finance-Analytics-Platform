/**
 * `MacroNewsPanel` is presentational (it fetches nothing -- `phase`/`data`/`message` are props), so
 * every test here renders it with a hand-built `MacroNewsPanel` (the wire type from `@/api/news`).
 * The suite is built around the rules the component exists to enforce (see its own module docstring):
 * a dead Polymarket chain reads as a different sentence than "no markets matched" even though both
 * arrive on the wire as `events: []`, a dead news chain reads differently from `news_source` being
 * non-null with an empty `news` array, one dead section never takes the other section down with it,
 * and every count on screen carries the `MACRO_NEWS_LIMIT` denominator it was actually requested
 * against.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MACRO_NEWS_LIMIT } from "@/api/news";
import type { EventMarket, MacroNewsPanel as MacroNewsPanelData, NewsItem } from "@/api/news";
import MacroNewsPanel from "@/components/MacroNewsPanel";

function newsItem(overrides: Partial<NewsItem> = {}): NewsItem {
  return {
    title: "Central banks signal coordinated pause",
    url: "https://example.com/macro-news",
    published: "2026-08-24T17:00:00Z",
    source: "gdelt",
    publisher: "Reuters",
    summary: null,
    ...overrides,
  };
}

function event(overrides: Partial<EventMarket> = {}): EventMarket {
  return {
    question: "Will the Fed cut rates in September 2026?",
    slug: "fed-cut-september-2026",
    source: "polymarket",
    as_of: "2026-08-24T18:00:00Z",
    probability: 0.62,
    volume: 4_500_000,
    resolution_date: "2026-09-17",
    ...overrides,
  };
}

function panel(overrides: Partial<MacroNewsPanelData> = {}): MacroNewsPanelData {
  return {
    generated_at: "2026-08-24T18:02:11.123Z",
    as_of: null,
    query: "Fed interest rate decision OR S&P 500 earnings GDP",
    news: [newsItem()],
    news_source: "gdelt",
    events: [event()],
    warnings: [],
    ...overrides,
  };
}

describe("loading and error phases", () => {
  it("renders a loading placeholder and nothing else", () => {
    render(<MacroNewsPanel data={null} phase="loading" message={null} />);
    expect(screen.getByText(/loading macro news/i)).toBeTruthy();
  });

  it("renders the error message when the fetch failed", () => {
    render(<MacroNewsPanel data={null} phase="error" message="API returned 502: Bad Gateway" />);
    expect(screen.getByText(/502: Bad Gateway/)).toBeTruthy();
  });

  it("falls back to a generic message when none was given", () => {
    render(<MacroNewsPanel data={null} phase="error" message={null} />);
    expect(screen.getByText(/could not load macro news/i)).toBeTruthy();
  });

  it("loading and error are visibly distinct from a loaded panel", () => {
    const { rerender } = render(<MacroNewsPanel data={null} phase="loading" message={null} />);
    // The `<h2>` title renders in every phase; what must be absent while loading is any content
    // gated behind `phase === "loaded" && data`, such as the query line built from `data.query`.
    expect(screen.queryByText(/query:/i)).toBeNull();

    rerender(<MacroNewsPanel data={panel()} phase="loaded" message={null} />);
    expect(screen.queryByText(/loading macro news/i)).toBeNull();
    expect(screen.getByText(/Will the Fed cut rates/i)).toBeTruthy();
  });
});

describe("event markets: dead provider vs. genuinely empty", () => {
  it("says the provider could not be reached when a prediction-markets warning is present", () => {
    render(
      <MacroNewsPanel
        data={panel({
          events: [],
          warnings: [
            {
              kind: "provider_fallback",
              message: "prediction markets unavailable for Fed rate decision: all providers failed",
            },
          ],
        })}
        phase="loaded"
        message={null}
      />,
    );

    expect(screen.getByText(/could not reach a prediction-market provider/i)).toBeTruthy();
    expect(screen.queryByText(/no event markets matching/i)).toBeNull();
  });

  it("says no markets matched when events is empty with no such warning -- a different sentence", () => {
    render(<MacroNewsPanel data={panel({ events: [] })} phase="loaded" message={null} />);

    expect(screen.getByText(/no event markets matching today's query/i)).toBeTruthy();
    expect(screen.queryByText(/could not reach a prediction-market provider/i)).toBeNull();
  });

  it("a dead events provider degrades only the events section -- headlines still render", () => {
    render(
      <MacroNewsPanel
        data={panel({
          events: [],
          warnings: [
            {
              kind: "provider_fallback",
              message: "prediction markets unavailable for query: polymarket timed out",
            },
          ],
        })}
        phase="loaded"
        message={null}
      />,
    );

    expect(screen.getByText(/could not reach a prediction-market provider/i)).toBeTruthy();
    // Headlines section is unaffected by the events-only failure.
    expect(
      screen.getByRole("link", { name: /Central banks signal coordinated pause/i }),
    ).toBeTruthy();
  });

  it("renders each event tile with its probability, and the shown-of-requested denominator", () => {
    render(
      <MacroNewsPanel
        data={panel({
          events: [
            event(),
            event({ slug: "second-market", question: "Second market?", probability: 0.35 }),
          ],
        })}
        phase="loaded"
        message={null}
      />,
    );

    expect(screen.getByText("62%")).toBeTruthy();
    expect(screen.getByText("35%")).toBeTruthy();
    expect(screen.getByText(new RegExp(`2 of up to ${MACRO_NEWS_LIMIT} requested`, "i"))).toBeTruthy();
  });
});

describe("headlines: dead provider vs. genuinely empty", () => {
  it("says the provider could not be reached when news_source is null", () => {
    render(<MacroNewsPanel data={panel({ news_source: null, news: [] })} phase="loaded" message={null} />);

    expect(screen.getByText(/could not reach a global-news provider/i)).toBeTruthy();
  });

  it("says nothing matched when news_source is present but news is empty -- a different sentence", () => {
    render(
      <MacroNewsPanel data={panel({ news_source: "gdelt", news: [] })} phase="loaded" message={null} />,
    );

    expect(screen.getByText(/no headlines matched today's query/i)).toBeTruthy();
    expect(screen.queryByText(/could not reach a global-news provider/i)).toBeNull();
  });

  it("a dead news provider degrades only the headlines section -- events still render", () => {
    render(
      <MacroNewsPanel data={panel({ news_source: null, news: [] })} phase="loaded" message={null} />,
    );

    expect(screen.getByText(/could not reach a global-news provider/i)).toBeTruthy();
    expect(screen.getByText(/Will the Fed cut rates/i)).toBeTruthy();
  });

  it("renders each headline as an out-linking anchor with its shown-of-requested denominator", () => {
    render(
      <MacroNewsPanel
        data={panel({ news: [newsItem(), newsItem({ url: "https://example.com/second", title: "Second story" })] })}
        phase="loaded"
        message={null}
      />,
    );

    const link = screen.getByRole("link", { name: /Central banks signal coordinated pause/i });
    expect(link.getAttribute("href")).toBe("https://example.com/macro-news");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(screen.getByText(new RegExp(`2 of up to ${MACRO_NEWS_LIMIT} requested`, "i"))).toBeTruthy();
  });

  it("renders a javascript: URL headline as plain text, never an anchor", () => {
    render(
      <MacroNewsPanel
        data={panel({ news: [newsItem({ url: "javascript:alert(1)", title: "Poisoned headline" })] })}
        phase="loaded"
        message={null}
      />,
    );

    expect(screen.getByText("Poisoned headline")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("still renders an https headline as an out-linking anchor", () => {
    render(
      <MacroNewsPanel
        data={panel({ news: [newsItem({ url: "https://example.com/safe", title: "Safe headline" })] })}
        phase="loaded"
        message={null}
      />,
    );

    const link = screen.getByRole("link", { name: /Safe headline/i });
    expect(link.getAttribute("href")).toBe("https://example.com/safe");
  });
});

describe("warnings", () => {
  it("renders non-empty warnings rather than swallowing them", () => {
    render(
      <MacroNewsPanel
        data={panel({
          warnings: [{ kind: "provider_fallback", message: "gdelt throttled, fell back to yahoo_news" }],
        })}
        phase="loaded"
        message={null}
      />,
    );

    expect(screen.getByText("provider_fallback")).toBeTruthy();
    expect(screen.getByText(/fell back to yahoo_news/i)).toBeTruthy();
  });

  it("renders nothing extra when warnings is empty", () => {
    render(<MacroNewsPanel data={panel({ warnings: [] })} phase="loaded" message={null} />);
    expect(screen.queryByText(/provider_fallback/i)).toBeNull();
  });
});

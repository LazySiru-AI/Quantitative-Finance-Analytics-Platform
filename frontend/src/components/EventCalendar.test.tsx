/**
 * `EventCalendar` is presentational (it takes a fully loaded `EventCalendar` wire object as a prop;
 * `pages/Overview.tsx`'s `EventCalendarSection` owns the loading/error/empty phase gating), so every
 * test here renders it directly with a hand-built fixture -- mirroring `MacroNewsPanel.test.tsx`.
 *
 * The suite pins the honesty rules the component exists to enforce (see its own module docstring):
 * an `estimated` event is visibly marked and a `confirmed` one is not, `holdings_covered`/
 * `holdings_total` always renders as a denominator rather than a bare numerator, every `warnings[]`
 * entry renders visibly, `timing: "unknown"` produces no visible "unknown" text, and an empty event
 * list reads as a quiet stretch rather than an error.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CalendarEventItem, EventCalendar as EventCalendarData } from "@/api/calendar";
import EventCalendar from "@/components/EventCalendar";

function eventItem(overrides: Partial<CalendarEventItem> = {}): CalendarEventItem {
  return {
    kind: "fomc",
    title: "FOMC Meeting",
    date: "2026-09-16",
    end_date: "2026-09-17",
    timing: "unknown",
    confidence: "confirmed",
    source: "federal_reserve",
    symbol: null,
    detail: null,
    ...overrides,
  };
}

function calendarFixture(overrides: Partial<EventCalendarData> = {}): EventCalendarData {
  return {
    generated_at: "2026-08-25T12:00:00Z",
    start: "2026-08-25",
    end: "2026-10-24",
    events: [eventItem()],
    holdings_total: 41,
    holdings_covered: 12,
    warnings: [],
    ...overrides,
  };
}

describe("economic releases", () => {
  function release(overrides: Partial<CalendarEventItem> = {}): CalendarEventItem {
    return eventItem({
      kind: "economic_release",
      title: "PCE inflation (Personal Income and Outlays)",
      date: "2026-08-26",
      end_date: null,
      timing: "before_open",
      confidence: "confirmed",
      source: "fred",
      symbol: null,
      detail: "BEA -- the Fed's preferred inflation gauge, headline and core PCE",
      ...overrides,
    });
  }

  it("renders a release with its own kind badge and accent, not the earnings one", () => {
    render(<EventCalendar calendar={calendarFixture({ events: [release()] })} />);

    expect(screen.getByText("Release")).toBeTruthy();
    expect(screen.queryByText("Earnings")).toBeNull();
    expect(document.querySelector(".event-calendar-row-economic_release")).not.toBeNull();
    expect(document.querySelector(".event-calendar-kind-economic_release")).not.toBeNull();
  });

  it("names the release and says who publishes it and when in the session", () => {
    render(<EventCalendar calendar={calendarFixture({ events: [release()] })} />);

    expect(screen.getByText(/PCE inflation/)).toBeTruthy();
    const detail = document.querySelector(".event-calendar-row-detail") as HTMLElement;
    expect(detail.textContent).toMatch(/before open/);
    expect(detail.textContent).toMatch(/BEA/);
  });

  /** These dates come from the agencies' own published schedules, so they are confirmed. The "est."
   *  badge appearing here would tell a reader the PCE date might move by two weeks, which is the
   *  specific claim the badge exists to make about a *vendor-projected* earnings date. */
  it("carries no est. badge and no ticker", () => {
    render(<EventCalendar calendar={calendarFixture({ events: [release()] })} />);

    expect(document.querySelector(".event-calendar-badge-estimated")).toBeNull();
    expect(document.querySelector(".event-calendar-badge-snapshot")).toBeNull();
  });

  it("keeps releases interleaved by date with FOMC and earnings rather than grouped", () => {
    render(
      <EventCalendar
        calendar={calendarFixture({
          events: [
            release({ title: "CPI", date: "2026-09-11" }),
            eventItem({ kind: "fomc", title: "FOMC meeting", date: "2026-09-15", end_date: null }),
            release({ title: "Retail sales", date: "2026-09-16" }),
          ],
        })}
      />,
    );

    const titles = Array.from(document.querySelectorAll(".event-calendar-title")).map(
      (node) => node.textContent,
    );
    expect(titles).toEqual(["CPI", "FOMC meeting", "Retail sales"]);
  });

  /** The rule the closed-union comment in `api/calendar.ts` exists to protect: a kind this build
   *  has never heard of must render as a row with an odd badge, not take the card down. */
  it("degrades on an unknown kind instead of throwing", () => {
    const unknown = { ...eventItem(), kind: "treasury_auction" } as unknown as CalendarEventItem;

    render(<EventCalendar calendar={calendarFixture({ events: [unknown] })} />);

    expect(screen.getByText("treasury_auction")).toBeTruthy();
    expect(screen.getByText("FOMC Meeting")).toBeTruthy();
  });
});

describe("estimated vs confirmed", () => {
  it("marks an estimated event visibly", () => {
    render(
      <EventCalendar
        calendar={calendarFixture({
          events: [
            eventItem({
              kind: "earnings",
              title: "NVDA earnings",
              symbol: "NVDA",
              confidence: "estimated",
              source: "nasdaq",
            }),
          ],
        })}
      />,
    );

    expect(screen.getByText("est.")).toBeTruthy();
  });

  it("does not mark a confirmed event", () => {
    render(
      <EventCalendar
        calendar={calendarFixture({
          events: [
            eventItem({
              kind: "earnings",
              title: "AAPL earnings",
              symbol: "AAPL",
              confidence: "confirmed",
              source: "nasdaq",
            }),
          ],
        })}
      />,
    );

    expect(screen.queryByText("est.")).toBeNull();
  });
});

describe("holdings coverage", () => {
  it("renders holdings_covered/holdings_total as a denominator, never a bare numerator", () => {
    render(<EventCalendar calendar={calendarFixture({ holdings_covered: 12, holdings_total: 41 })} />);

    expect(screen.getByText(/12 of 41 holdings/)).toBeTruthy();
  });
});

describe("warnings", () => {
  it("renders a warnings[] entry visibly via the shared callout-warn treatment", () => {
    render(
      <EventCalendar
        calendar={calendarFixture({
          warnings: [{ kind: "earnings_sweep_degraded", message: "Nasdaq earnings sweep timed out for 6 symbols" }],
        })}
      />,
    );

    const warning = screen.getByText(/Nasdaq earnings sweep timed out for 6 symbols/);
    expect(warning.className).toContain("callout-warn");
  });

  it("renders nothing extra when warnings is empty", () => {
    render(<EventCalendar calendar={calendarFixture({ warnings: [] })} />);
    expect(screen.queryByText(/callout-warn/)).toBeNull();
  });
});

describe("timing", () => {
  it("renders no timing text at all when timing is unknown", () => {
    render(
      <EventCalendar
        calendar={calendarFixture({
          events: [eventItem({ timing: "unknown" })],
        })}
      />,
    );

    expect(screen.queryByText(/unknown/i)).toBeNull();
  });

  it("renders the described timing when it is known", () => {
    render(
      <EventCalendar
        calendar={calendarFixture({
          events: [eventItem({ kind: "earnings", symbol: "MSFT", timing: "after_close" })],
        })}
      />,
    );

    expect(screen.queryByText(/unknown/i)).toBeNull();
    expect(screen.getByText(/after/i)).toBeTruthy();
  });
});

describe("empty calendar", () => {
  it("renders the quiet-stretch copy rather than an error or a blank card", () => {
    render(<EventCalendar calendar={calendarFixture({ events: [] })} />);

    expect(screen.getByText(/No scheduled events in the next 60 days\./)).toBeTruthy();
  });
});

describe("FOMC vs earnings distinguishability", () => {
  it("tells an FOMC row and an earnings row apart at a glance while staying in one date-ordered list", () => {
    render(
      <EventCalendar
        calendar={calendarFixture({
          events: [
            eventItem({ kind: "fomc", title: "FOMC Meeting", date: "2026-09-16" }),
            eventItem({
              kind: "earnings",
              title: "NVDA earnings",
              symbol: "NVDA",
              date: "2026-09-20",
              confidence: "estimated",
              source: "nasdaq",
            }),
          ],
        })}
      />,
    );

    expect(screen.getByText("FOMC")).toBeTruthy();
    expect(screen.getByText("Earnings")).toBeTruthy();
    expect(screen.getByText("NVDA")).toBeTruthy();
    // One list, not two -- both rows are present under a single <ul>.
    const list = document.querySelector(".event-calendar-list");
    expect(list?.children.length).toBe(2);
  });
});

describe("bundled-schedule provenance", () => {
  it("indicates when an FOMC date came from a committed snapshot rather than a live feed", () => {
    render(
      <EventCalendar
        calendar={calendarFixture({
          events: [eventItem({ kind: "fomc", source: "bundled_schedule" })],
        })}
      />,
    );

    expect(screen.getByText("snapshot")).toBeTruthy();
    expect(screen.getByText(/committed FOMC schedule/)).toBeTruthy();
  });

  it("does not show the snapshot note when every event came from a live source", () => {
    render(
      <EventCalendar
        calendar={calendarFixture({
          events: [eventItem({ kind: "fomc", source: "federal_reserve" })],
        })}
      />,
    );

    expect(screen.queryByText("snapshot")).toBeNull();
  });
});

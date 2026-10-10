/**
 * The event calendar client's request shape and display helpers.
 *
 * `fetch` is stubbed directly (per `src/test/setup.ts`, the global throws on any unstubbed call)
 * since this file tests the API layer itself, matching the idiom in `washsales.test.ts`.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  calendarApi,
  daysUntil,
  describeTiming,
  formatEventDate,
  formatEventDateRange,
  type CalendarEventItem,
  type EventCalendar,
} from "@/api/calendar";

function stubFetchOnce(body: unknown, ok = true, status = 200): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok,
      status,
      statusText: ok ? "OK" : "Error",
      json: async () => body,
      text: async () => JSON.stringify(body),
    })),
  );
}

function wellFormedCalendar(overrides: Partial<EventCalendar> = {}): EventCalendar {
  return {
    generated_at: "2026-08-25T13:00:00Z",
    start: "2026-08-25",
    end: "2026-10-24",
    events: [
      {
        kind: "fomc",
        title: "FOMC Meeting",
        date: "2026-09-15",
        end_date: "2026-09-16",
        timing: "unknown",
        confidence: "confirmed",
        source: "federal_reserve",
        symbol: null,
        detail: null,
      },
    ],
    holdings_total: 12,
    holdings_covered: 9,
    warnings: [],
    ...overrides,
  };
}

describe("calendarApi.upcoming", () => {
  it("requests the endpoint with no query parameters by default", async () => {
    const payload = wellFormedCalendar();
    stubFetchOnce(payload);

    const result = await calendarApi.upcoming();

    expect(fetch).toHaveBeenCalledTimes(1);
    const call = vi.mocked(fetch).mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    expect(String(call[0])).toBe("/api/calendar/events");
    expect(result).toEqual(payload);
  });

  it("adds a days query parameter when a non-default value is passed", async () => {
    stubFetchOnce(wellFormedCalendar());

    await calendarApi.upcoming(90);

    const call = vi.mocked(fetch).mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    expect(String(call[0])).toBe("/api/calendar/events?days=90");
  });

  it("omits the query parameter when 60 (the default) is passed explicitly", async () => {
    stubFetchOnce(wellFormedCalendar());

    await calendarApi.upcoming(60);

    const call = vi.mocked(fetch).mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    expect(String(call[0])).toBe("/api/calendar/events");
  });

  it("throws ApiRequestError carrying the status on a non-ok response", async () => {
    stubFetchOnce({ detail: "boom" }, false, 503);

    await expect(calendarApi.upcoming()).rejects.toMatchObject({
      name: "ApiRequestError",
      status: 503,
    });
  });
});

describe("formatEventDateRange", () => {
  it("renders a single day (no end date) without a range", () => {
    expect(formatEventDateRange("2026-09-15", null)).toBe("Sep 15, 2026");
  });

  it("renders a same-month range collapsing the shared month/year", () => {
    expect(formatEventDateRange("2026-09-15", "2026-09-16")).toBe("Sep 15–16, 2026");
  });

  it("renders a range spanning a month boundary", () => {
    expect(formatEventDateRange("2027-04-30", "2027-05-01")).toBe("Apr 30 – May 1, 2027");
  });

  it("renders a range spanning a year boundary", () => {
    expect(formatEventDateRange("2026-12-31", "2027-01-01")).toBe("Dec 31, 2026 – Jan 1, 2027");
  });

  it("renders a single day when end_date equals date", () => {
    expect(formatEventDateRange("2026-09-15", "2026-09-15")).toBe("Sep 15, 2026");
  });
});

describe("formatEventDate", () => {
  const originalTz = process.env.TZ;

  afterEach(() => {
    process.env.TZ = originalTz;
  });

  it("does not off-by-one under a timezone west of UTC", () => {
    // A naive implementation -- `new Date("2026-08-07").toLocaleDateString()` with no explicit
    // `timeZone: "UTC"` -- renders the *previous* day (the 6th) in any zone west of Greenwich.
    // Proving UTC-safety means running under exactly such a zone and asserting the day is still 7,
    // not re-deriving the expected string with the same `Date` construction the implementation
    // uses (which would just repeat the bug if the bug were present).
    process.env.TZ = "America/Los_Angeles";

    const result = formatEventDate("2026-08-07");

    // Asserted as a literal, not re-derived via another `Date` construction -- a naive
    // implementation would produce the distinct string "Aug 6, 2026" under this timezone, so this
    // exact match genuinely distinguishes the correct rendering from the off-by-one bug.
    expect(result).toBe("Aug 7, 2026");
  });

  it("renders a well-formed date with month, day and year", () => {
    process.env.TZ = "UTC";
    expect(formatEventDate("2026-09-15")).toBe("Sep 15, 2026");
  });
});

describe("describeTiming", () => {
  it("returns null for unknown so the UI can omit the field", () => {
    expect(describeTiming("unknown")).toBeNull();
  });

  it("describes before_open, after_close and during_session", () => {
    expect(describeTiming("before_open")).toBe("before open");
    expect(describeTiming("after_close")).toBe("after close");
    expect(describeTiming("during_session")).toBe("14:00 ET");
  });
});

describe("daysUntil", () => {
  const today = new Date(Date.UTC(2026, 7, 25, 12, 0, 0)); // 2026-08-25, noon UTC

  it("returns 0 for today", () => {
    expect(daysUntil("2026-08-25", today)).toBe(0);
  });

  it("returns a positive count for a future date", () => {
    expect(daysUntil("2026-09-15", today)).toBe(21);
  });

  it("returns a negative count for a past date", () => {
    expect(daysUntil("2026-08-01", today)).toBe(-24);
  });
});

describe("economic_release events", () => {
  /** The wire shape a scheduled federal release actually takes -- the worked example from
   *  `api/calendar.ts`'s module docstring. `symbol` stays `null` (a macro print is not tied to a
   *  holding) and `confidence` stays `"confirmed"` (these dates come from the agencies' own
   *  published schedules, not a vendor's extrapolation), so both are pinned as literals here rather
   *  than left to a generic override. */
  function releaseEvent(overrides: Partial<CalendarEventItem> = {}): CalendarEventItem {
    return {
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
    };
  }

  it("formats a release's single day with no range, same as any other end_date: null event", () => {
    const event = releaseEvent();
    expect(formatEventDateRange(event.date, event.end_date)).toBe("Aug 26, 2026");
  });

  it("describes before_open timing the same way for a release as for any other event kind", () => {
    expect(describeTiming(releaseEvent().timing)).toBe("before open");
  });

  it("round-trips two same-day releases (GDP and PCE) through calendarApi.upcoming untouched", async () => {
    // GDP (advance estimate) and PCE genuinely land on the same morning each quarter -- this is
    // the ordinary case for a quarter's last release, not a hypothetical crafted for coverage.
    // The client does no grouping or dedup of its own, so both must survive as distinct events
    // sharing a date. This also exercises the compile-time side of the change: `kind:
    // "economic_release"` and `source: "fred"` only type-check because both were added to the
    // `EventKind`/`EventSource` unions in api/calendar.ts -- a regressed union fails `npx tsc
    // --noEmit` on this fixture, not just the runtime assertion below.
    const gdp = releaseEvent({ title: "GDP (advance estimate)", date: "2026-09-26" });
    const pce = releaseEvent({ date: "2026-09-26" });
    const payload = wellFormedCalendar({ events: [gdp, pce] });
    stubFetchOnce(payload);

    const result = await calendarApi.upcoming();

    expect(result).toEqual(payload);
    expect(result.events.map((event) => event.title)).toEqual([
      "GDP (advance estimate)",
      "PCE inflation (Personal Income and Outlays)",
    ]);
    expect(result.events[0]?.date).toBe(result.events[1]?.date);
  });
});

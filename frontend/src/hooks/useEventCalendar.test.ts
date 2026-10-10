/**
 * `useEventCalendar` — the `slow` flag, and only that.
 *
 * `/api/calendar/events` has two response times and, until now, one message. Warm it answers in about
 * 0.6s (measured, twice, consecutively). Cold — the first call of the day, which fetches the exchange
 * calendar upstream before caching it — a 2026-08-29 UAT sweep sat on `Loading calendar…` for over
 * eight seconds with nothing else on screen. Eight silent seconds under three words that normally
 * mean half a second is indistinguishable from a hang, and the reader's only available conclusion is
 * that the page is broken.
 *
 * These tests pin the threshold behaviour rather than any wording: that an ordinary load never trips
 * it, that a long one does, and that the flag is cleared by whatever ends the fetch. The wording
 * belongs to the card and is free to change; the timing contract is what a future reader needs held.
 */

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SLOW_AFTER_MS, useEventCalendar } from "@/hooks/useEventCalendar";

const upcoming = vi.hoisted(() => vi.fn());

vi.mock("@/api/calendar", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/calendar")>();
  return { ...actual, calendarApi: { ...actual.calendarApi, upcoming } };
});

const CALENDAR = { events: [{ kind: "fomc" }], warnings: [] };

beforeEach(() => {
  vi.useFakeTimers();
  upcoming.mockReset();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("useEventCalendar slow-load flag", () => {
  it("does not trip on a warm load", async () => {
    upcoming.mockResolvedValue(CALENDAR);
    const { result } = renderHook(() => useEventCalendar());

    await act(async () => {
      vi.advanceTimersByTime(600); // the measured warm response
    });

    expect(result.current.phase).toBe("loaded");
    expect(result.current.slow).toBe(false);
  });

  it("trips once a fetch outlasts the threshold", async () => {
    upcoming.mockReturnValue(new Promise(() => {})); // never resolves: the cold case, exaggerated
    const { result } = renderHook(() => useEventCalendar());

    await act(async () => {
      vi.advanceTimersByTime(SLOW_AFTER_MS - 100);
    });
    expect(result.current.slow).toBe(false);

    await act(async () => {
      vi.advanceTimersByTime(200);
    });
    expect(result.current.slow).toBe(true);
    // Still loading, not an error: a slow calendar has not failed, and must not be dressed as one.
    expect(result.current.phase).toBe("loading");
  });

  it("stays false when a slow fetch finally lands", async () => {
    let resolve!: (v: unknown) => void;
    upcoming.mockReturnValue(new Promise((r) => { resolve = r; }));
    const { result } = renderHook(() => useEventCalendar());

    await act(async () => {
      vi.advanceTimersByTime(SLOW_AFTER_MS + 100);
    });
    expect(result.current.slow).toBe(true);

    await act(async () => {
      resolve(CALENDAR);
    });

    expect(result.current.phase).toBe("loaded");
  });

  it("does not trip after a fetch that failed fast", async () => {
    // The timer must be cleared by the error path too, or a card that already said "failed to load"
    // sprouts a "still working" line seconds later.
    upcoming.mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useEventCalendar());

    await act(async () => {
      vi.advanceTimersByTime(10);
    });
    expect(result.current.phase).toBe("error");

    await act(async () => {
      vi.advanceTimersByTime(SLOW_AFTER_MS + 500);
    });
    expect(result.current.slow).toBe(false);
  });

  it("resets on refresh, so a quick retry does not inherit the last wait", async () => {
    upcoming.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useEventCalendar());
    await act(async () => {
      vi.advanceTimersByTime(SLOW_AFTER_MS + 100);
    });
    expect(result.current.slow).toBe(true);

    upcoming.mockResolvedValue(CALENDAR);
    await act(async () => {
      result.current.refresh();
    });

    expect(result.current.slow).toBe(false);
  });
});

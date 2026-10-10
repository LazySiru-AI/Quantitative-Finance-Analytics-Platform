/**
 * Typed client for the upcoming event calendar (FOMC meetings, scheduled federal economic releases
 * -- PCE, CPI, the jobs report, GDP, PPI, retail sales -- and earnings dates for held symbols).
 *
 * Mirrors `GET /api/calendar/events`. The type is named `CalendarEventItem`, not `CalendarEvent`,
 * on purpose: `CalendarEvent` is a DOM lib global (the Web/File System Access API type), and
 * shadowing it invites confusing type errors at any call site that also touches DOM types.
 *
 * Dates here (`date`, `end_date`, `start`, `end`) are `YYYY-MM-DD` strings, never money and never a
 * JS `number`. As with `api/macro.ts`, do not round-trip one through a local-zone `Date`:
 * `new Date("2026-08-07").toLocaleDateString()` prints the 6th anywhere west of Greenwich. Every
 * helper below that touches a date string builds its `Date` via `Date.UTC(...)` and reads it back
 * with an explicit `timeZone: "UTC"`, the same idiom as `formatObservationDate` in `api/macro.ts`.
 */

import { ApiRequestError } from "@/api/client";

// --- wire types ---------------------------------------------------------------

/** Kept in step with `app.market.calendar_models.EventKind`. Every consumer must degrade on an
 *  unrecognised value rather than throw: this string is server-supplied, and a closed union with a
 *  throwing exhaustiveness check turns "the backend added a kind" into a blank page instead of an
 *  unstyled row. `kindLabel` in `components/EventCalendar.tsx` is where that rule is enforced. */
export type EventKind = "fomc" | "earnings" | "economic_release";
export type EventSource = "federal_reserve" | "bundled_schedule" | "nasdaq" | "fred";
export type EventConfidence = "confirmed" | "estimated";
export type SessionTiming = "before_open" | "after_close" | "during_session" | "unknown";

export interface CalendarEventItem {
  kind: EventKind;
  /** For an `economic_release` this is the release's name ("CPI", "PCE inflation (Personal Income
   *  and Outlays)"), not a ticker -- `symbol` stays `null`, since a macro print is not tied to a
   *  position. */
  title: string;
  /** `YYYY-MM-DD`. */
  date: string;
  /** `YYYY-MM-DD`, or `null` for a single-day event. Set for a multi-day FOMC meeting. */
  end_date: string | null;
  timing: SessionTiming;
  confidence: EventConfidence;
  source: EventSource;
  symbol: string | null;
  detail: string | null;
}

export interface EventCalendar {
  /** ISO 8601 timestamp of when the backend built this response. */
  generated_at: string;
  /** `YYYY-MM-DD`. */
  start: string;
  /** `YYYY-MM-DD`. */
  end: string;
  events: CalendarEventItem[];
  holdings_total: number;
  holdings_covered: number;
  warnings: { kind: string; message: string }[];
}

// --- requests ------------------------------------------------------------------

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new ApiRequestError(response.status, body || response.statusText);
  }
  return (await response.json()) as T;
}

const DEFAULT_DAYS = 60;

export const calendarApi = {
  /** Upcoming events over the next `days` days (default 60). The default is omitted from the
   *  query string rather than sent explicitly, matching `macroApi.snapshot`'s pattern for a
   *  parameter whose common case is "don't send it".
   *
   *  `refresh` maps to `?refresh=true`, which pins the endpoint's on-disk HTTP cache TTL to zero for
   *  this one request so every FOMC/Nasdaq/FRED read is a real round trip -- see `backend/app/api/
   *  calendar.py`'s `refresh` section. Same "omit when false" treatment as `days` and as
   *  `macroApi.snapshot`'s own flag, so the default cached path keeps building the exact URLs the
   *  tests pin. */
  upcoming: (days?: number, signal?: AbortSignal, refresh = false) => {
    const params = new URLSearchParams();
    const effectiveDays = days ?? DEFAULT_DAYS;
    if (effectiveDays !== DEFAULT_DAYS) params.set("days", String(effectiveDays));
    if (refresh) params.set("refresh", "true");
    const query = params.toString() ? `?${params.toString()}` : "";
    return requestJson<EventCalendar>(`/api/calendar/events${query}`, { signal: signal ?? null });
  },
};

// --- display helpers -------------------------------------------------------------

function parseYMD(date: string): { year: number; month: number; day: number } | null {
  const [year, month, day] = date.split("-").map(Number);
  if (!year || !month || !day) return null;
  return { year, month, day };
}

/**
 * Render a `YYYY-MM-DD` event date without going through a local-zone `Date`. Same idiom as
 * `formatObservationDate` in `api/macro.ts`: `new Date("2026-08-07").toLocaleDateString()` prints
 * the 6th anywhere west of Greenwich, so the `Date` is built with `Date.UTC` and read back with an
 * explicit `timeZone: "UTC"`.
 */
export function formatEventDate(date: string): string {
  const parsed = parseYMD(date);
  if (!parsed) return date;
  return new Date(Date.UTC(parsed.year, parsed.month - 1, parsed.day)).toLocaleDateString(
    undefined,
    { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" },
  );
}

function monthLabel(year: number, month: number, day: number): string {
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString(undefined, {
    month: "short",
    timeZone: "UTC",
  });
}

/**
 * Render a single event day, or a two-day span (an FOMC meeting) as e.g. `"Sep 15–16, 2026"`,
 * collapsing the shared month/year rather than repeating them. A span crossing a month boundary
 * reads `"Apr 30 – May 1, 2027"`; one crossing a year boundary reads full dates on both sides,
 * `"Dec 31, 2026 – Jan 1, 2027"`.
 */
export function formatEventDateRange(date: string, endDate: string | null): string {
  if (!endDate || endDate === date) return formatEventDate(date);
  const start = parseYMD(date);
  const end = parseYMD(endDate);
  if (!start || !end) return formatEventDate(date);

  const startMonth = monthLabel(start.year, start.month, start.day);
  if (start.year === end.year && start.month === end.month) {
    return `${startMonth} ${start.day}–${end.day}, ${start.year}`;
  }
  const endMonth = monthLabel(end.year, end.month, end.day);
  if (start.year === end.year) {
    return `${startMonth} ${start.day} – ${endMonth} ${end.day}, ${start.year}`;
  }
  return `${startMonth} ${start.day}, ${start.year} – ${endMonth} ${end.day}, ${end.year}`;
}

/**
 * A short phrase for when in the session an event lands, or `null` for `"unknown"` so the UI can
 * omit the field entirely rather than print the word "unknown".
 */
export function describeTiming(timing: SessionTiming): string | null {
  switch (timing) {
    case "before_open":
      return "before open";
    case "after_close":
      return "after close";
    case "during_session":
      return "14:00 ET";
    case "unknown":
      return null;
  }
}

const MS_PER_DAY = 24 * 60 * 60 * 1000;

/**
 * Whole days from `today` to `date`, UTC-safe and negative for a date already in the past. `today`
 * defaults to now; both it and `date` are reduced to a UTC calendar day before differencing, so a
 * caller's local clock never shifts which day "today" counts as.
 */
export function daysUntil(date: string, today: Date = new Date()): number {
  const parsed = parseYMD(date);
  if (!parsed) return 0;
  const target = Date.UTC(parsed.year, parsed.month - 1, parsed.day);
  const todayUtc = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  return Math.round((target - todayUtc) / MS_PER_DAY);
}

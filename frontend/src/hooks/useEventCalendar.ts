/**
 * The upcoming event calendar (FOMC meetings + earnings dates for held symbols) for the Overview
 * dashboard's calendar card.
 *
 * Mirrors the stale-response guard in `useMacroSnapshot`/`usePortfolio`: an `AbortController` is
 * created per effect run and aborted on cleanup, so a component unmount or a `refresh()` fired
 * before the previous fetch resolved never leaves an abandoned request running to overwrite fresher
 * state that already landed. `AbortError` is expected on every genuine cancellation and is swallowed
 * rather than surfaced as a failed request.
 *
 * `"empty"` (zero events over the requested window) is treated the same way `usePortfolio` treats a
 * zero-position report: a real, expected state -- a quiet stretch between FOMC meetings and earnings
 * seasons -- not an error, so it gets its own phase rather than being lumped into `"loaded"`.
 *
 * **`slow` exists because this endpoint has two completely different response times and only one
 * message.** Warm, `/api/calendar/events` answers in about 0.6s. Cold -- the first call of the day,
 * which fetches the exchange calendar upstream before caching it -- a 2026-08-29 UAT sweep measured
 * it at over 8 seconds, during which the card said `Loading calendar...` and nothing else. Eight
 * silent seconds under the same three words that normally mean "half a second" is indistinguishable
 * from a hang, and the reader's only available conclusion is that the page is broken.
 *
 * So this is not a spinner. It is a flag the view uses to say *why* the wait is happening, and it is
 * deliberately a property of the hook rather than of the card: the timing fact belongs next to the
 * fetch that owns it, and it is testable here without rendering anything.
 */
import { useCallback, useEffect, useState } from "react";

import { ApiRequestError } from "@/api/client";
import { calendarApi, type EventCalendar } from "@/api/calendar";
import { t } from "@/i18n";

export type CalendarPhase = "loading" | "loaded" | "empty" | "error";

export interface UseEventCalendar {
  calendar: EventCalendar | null;
  phase: CalendarPhase;
  message: string | null;
  /** This fetch has been in flight longer than `SLOW_AFTER_MS`. Only meaningful while `phase` is
   * `"loading"`; the view is expected to explain the wait rather than merely show it. */
  slow: boolean;
  /** Re-fetches the calendar. */
  refresh: () => void;
}

/** How long a fetch may run before the card starts explaining itself.
 *
 * 2.5s sits well above the warm response (~0.6s measured) so an ordinary load never trips it, and
 * well below the cold one (8s+ measured) so the one case this exists for always does. */
export const SLOW_AFTER_MS = 2500;

export function useEventCalendar(days?: number): UseEventCalendar {
  const [calendar, setCalendar] = useState<EventCalendar | null>(null);
  const [phase, setPhase] = useState<CalendarPhase>("loading");
  const [message, setMessage] = useState<string | null>(null);
  const [slow, setSlow] = useState(false);
  // Bumped by `refresh()` to force a re-run of the effect below without changing `days`.
  const [requestId, setRequestId] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setPhase("loading");
    setMessage(null);
    setSlow(false);
    // Cleared on resolve and on cleanup. A late fire would be harmless anyway -- the view only reads
    // `slow` while loading -- but leaving a timer to run past its own fetch is the kind of thing that
    // becomes a real bug the moment someone else reads this flag somewhere else.
    const slowTimer = window.setTimeout(() => setSlow(true), SLOW_AFTER_MS);
    // Always reads the server's day-scale cache (primed by the startup warm), on the mount and on a
    // `refresh()` alike -- unlike `useMacroSnapshot`, this card is NOT forced cold by the Overview
    // "Fetch data" button. Forcing it (`?refresh=true`) re-fetches every earnings day in the window
    // as a separate cold Nasdaq round trip -- ~60-90s, and enough concurrent requests to risk the
    // provider's rate limiter -- to refresh FOMC meetings and earnings dates that do not move
    // intraday. The cache is already current to the day; the button re-fetches it (cheap) rather
    // than forcing it. `calendarApi.upcoming` still takes a `refresh` flag for a caller that wants
    // it; this hook simply does not ask.
    calendarApi
      .upcoming(days, controller.signal)
      .then((data) => {
        window.clearTimeout(slowTimer);
        setCalendar(data);
        setPhase(data.events.length === 0 ? "empty" : "loaded");
      })
      .catch((e: unknown) => {
        window.clearTimeout(slowTimer);
        if (e instanceof DOMException && e.name === "AbortError") return;
        setMessage(
          e instanceof ApiRequestError
            ? t("misc.fetch.apiError", { status: e.status, message: e.message })
            : t("misc.fetch.unreachable"),
        );
        setCalendar(null);
        setPhase("error");
      });
    return () => {
      controller.abort();
      window.clearTimeout(slowTimer);
    };
  }, [days, requestId]);

  const refresh = useCallback(() => setRequestId((id) => id + 1), []);

  return { calendar, phase, message, slow, refresh };
}

/**
 * Reports every route change to the local navigation-telemetry log (`app.api.telemetry_nav`), so the
 * owner can see which pages and tabs are actually used without any network call, username, or
 * analytics vendor involved.
 *
 * **A module-level queue, not component state.** `NavTelemetry` (the component that calls this hook)
 * mounts once near the app root, but keeping the queue and its flush timer at module scope rather
 * than in `useState`/`useRef` means the flush cadence is a property of the page, not of any one
 * component instance -- there is exactly one 10s timer regardless of how many times this hook is
 * invoked.
 *
 * **Two flush triggers, matching how a browser tab actually ends a session:**
 *   - a plain interval, so a long-lived tab still reports periodically;
 *   - `visibilitychange` -> `hidden`, because a closed tab or a switch to another tab never fires a
 *     graceful unmount, and that is the moment most of a session's navigation would otherwise be lost.
 *     That flush prefers `navigator.sendBeacon`, which is designed to survive exactly this moment --
 *     an ordinary `fetch` can be cancelled by the browser once the page starts unloading.
 *
 * The `visibilitychange` listener is attached and removed per mount (a plain `useEffect` cleanup),
 * even though the queue it flushes is module-level -- `NavTelemetry` never unmounts in production, so
 * this is one listener for the app's lifetime there, and it is what lets a test unmount cleanly
 * between cases (`@testing-library/react`'s `cleanup()`, wired in `src/test/setup.ts`) without
 * accumulating a stale listener per test.
 *
 * **Never throws, never blocks navigation.** Every failure -- a rejected `telemetryApi.record` call,
 * a browser without `sendBeacon` -- is swallowed. This is best-effort usage data, not a feature the
 * user is relying on; it must never be the reason a page fails to render or a click feels slow.
 */
import { useEffect } from "react";
import { useLocation, useSearchParams } from "react-router-dom";

import { telemetryApi, type NavEvent } from "@/api/telemetry";

const FLUSH_INTERVAL_MS = 10_000;
const RECORD_PATH = "/api/telemetry/nav";

let queue: NavEvent[] = [];
let flushTimer: ReturnType<typeof setTimeout> | null = null;

function sendBeaconJson(events: NavEvent[]): boolean {
  if (typeof navigator === "undefined" || typeof navigator.sendBeacon !== "function") return false;
  try {
    const blob = new Blob([JSON.stringify({ events })], { type: "application/json" });
    return navigator.sendBeacon(RECORD_PATH, blob);
  } catch {
    return false;
  }
}

function flush(): void {
  if (flushTimer !== null) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  if (queue.length === 0) return;
  const batch = queue;
  queue = [];
  if (sendBeaconJson(batch)) return;
  telemetryApi.record(batch).catch(() => {
    // Best-effort: a dropped telemetry batch is never worth surfacing to the user.
  });
}

function scheduleFlush(): void {
  if (flushTimer !== null) return;
  flushTimer = setTimeout(flush, FLUSH_INTERVAL_MS);
}

/** Call once, near the app root (`<NavTelemetry />`) -- every mount shares the one module queue. */
export function useNavTelemetry(): void {
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const tab = searchParams.get("tab");

  useEffect(() => {
    function handleVisibilityChange(): void {
      if (document.visibilityState === "hidden") flush();
    }
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => document.removeEventListener("visibilitychange", handleVisibilityChange);
  }, []);

  useEffect(() => {
    const event: NavEvent = { path: location.pathname, ts: new Date().toISOString() };
    if (tab !== null) event.tab = tab;
    queue.push(event);
    scheduleFlush();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `tab` (a string | null primitive) is
    // the only piece of `searchParams` this hook reads; depending on `searchParams` itself would
    // re-fire on every unrelated query-param change too.
  }, [location.pathname, tab]);
}

/**
 * Test-only escape hatch: clears the module-level queue and cancels any pending flush timer.
 *
 * Nothing in the app ever calls this -- `NavTelemetry` mounts once and the queue is meant to
 * persist for the tab's whole lifetime. It exists solely so `useNavTelemetry.test.tsx` can start
 * each case from a known-empty queue without needing `vi.resetModules()` (which does not play well
 * with this module's top-level `let` state across a dynamic re-import).
 */
export function __resetNavTelemetryForTests(): void {
  if (flushTimer !== null) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  queue = [];
}

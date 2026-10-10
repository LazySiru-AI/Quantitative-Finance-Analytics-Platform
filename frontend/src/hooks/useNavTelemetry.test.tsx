/**
 * useNavTelemetry: batches route changes into a module-level queue, flushes at most every 10s (or
 * immediately on `visibilitychange` -> `hidden`, preferring `navigator.sendBeacon`), and never fires
 * on an empty queue.
 *
 * The queue is module state, not component state (see the hook's own docstring for why), so every
 * case starts from `__resetNavTelemetryForTests()` rather than a fresh module instance -- and each
 * `renderHook` result is unmounted at the end of the test (`cleanup()` in `src/test/setup.ts`), which
 * is what keeps the `visibilitychange` listener from accumulating across cases.
 *
 * `renderHook` needs a router in scope because the hook calls `useLocation`/`useSearchParams` --
 * `MemoryRouter` is the technique the rest of this suite already uses for that (`useUrlState.test.tsx`).
 */
import type { ReactNode } from "react";

import { act, renderHook } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { NavEvent, NavRecordResult } from "@/api/telemetry";

const recordMock = vi.fn<(events: NavEvent[]) => Promise<NavRecordResult>>();

vi.mock("@/api/telemetry", () => ({
  telemetryApi: {
    record: (events: NavEvent[]) => recordMock(events),
    summary: vi.fn(),
  },
}));

const { useNavTelemetry, __resetNavTelemetryForTests } = await import("./useNavTelemetry");

function wrapper(initialEntry: string) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <MemoryRouter initialEntries={[initialEntry]}>{children}</MemoryRouter>;
  };
}

describe("useNavTelemetry", () => {
  beforeEach(() => {
    __resetNavTelemetryForTests();
    recordMock.mockReset();
    recordMock.mockResolvedValue({ recorded: 1 });
    vi.useFakeTimers();
    // No `sendBeacon` by default -- exercises the `telemetryApi.record` fallback path. Tests that
    // want the beacon path define it explicitly on top of this.
    Object.defineProperty(window.navigator, "sendBeacon", { value: undefined, configurable: true });
  });

  afterEach(() => {
    __resetNavTelemetryForTests();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("queues a route change and flushes it via telemetryApi.record after 10s", async () => {
    renderHook(() => useNavTelemetry(), { wrapper: wrapper("/tax?tab=lots") });

    expect(recordMock).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });

    expect(recordMock).toHaveBeenCalledTimes(1);
    const [events] = recordMock.mock.calls[0]!;
    expect(events).toEqual([{ path: "/tax", tab: "lots", ts: expect.any(String) }]);
  });

  it("omits tab entirely when the URL carries none", async () => {
    renderHook(() => useNavTelemetry(), { wrapper: wrapper("/overview") });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });

    const [events] = recordMock.mock.calls[0]!;
    expect(events).toEqual([{ path: "/overview", ts: expect.any(String) }]);
  });

  it("never flushes an empty queue", async () => {
    // No render at all -- nothing was ever queued, so even letting well over 10s of fake time pass
    // must not call `telemetryApi.record`.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(recordMock).not.toHaveBeenCalled();
  });

  it("swallows a rejected record() call instead of throwing", async () => {
    recordMock.mockRejectedValue(new Error("network down"));
    renderHook(() => useNavTelemetry(), { wrapper: wrapper("/tax") });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });

    expect(recordMock).toHaveBeenCalledTimes(1);
  });

  it("flushes immediately via sendBeacon on visibilitychange -> hidden, ahead of the 10s timer", async () => {
    const sendBeaconMock = vi.fn().mockReturnValue(true);
    Object.defineProperty(window.navigator, "sendBeacon", {
      value: sendBeaconMock,
      configurable: true,
    });

    renderHook(() => useNavTelemetry(), { wrapper: wrapper("/tax") });

    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));

    expect(sendBeaconMock).toHaveBeenCalledTimes(1);
    const [beaconUrl, beaconBody] = sendBeaconMock.mock.calls[0]!;
    expect(beaconUrl).toBe("/api/telemetry/nav");
    expect(beaconBody).toBeInstanceOf(Blob);
    expect(recordMock).not.toHaveBeenCalled();

    // The beacon flush already emptied the queue -- the 10s timer fires on nothing further.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(sendBeaconMock).toHaveBeenCalledTimes(1);
    expect(recordMock).not.toHaveBeenCalled();
  });
});

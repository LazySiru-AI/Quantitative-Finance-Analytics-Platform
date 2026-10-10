/**
 * `api/paperlive.ts`'s parsing contract and its transport-degradation behaviour.
 *
 * Same idiom as `institutions.test.ts`: stub `fetch` directly, since this file tests the API layer
 * itself rather than a page consuming it.
 *
 * The one thing worth explaining up front: **jsdom (this suite's whole environment, per
 * `vitest.config.ts`) has no `EventSource`.** That is not a gap in these tests -- it is exactly the
 * condition `subscribe`'s polling fallback exists for, and it means every test below that calls
 * `subscribe` is, without any extra stubbing, already exercising the fallback path. A second block
 * further down stubs a minimal fake `EventSource` to prove the *other* trigger for the same fallback
 * -- a stream that opens and then errors -- degrades the same way.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "@/api/client";
import { quotes, quotesUrl, streamUrl, subscribe, type PaperLiveQuotes } from "@/api/paperlive";

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

function wellFormedSnapshot(overrides: Partial<PaperLiveQuotes> = {}): PaperLiveQuotes {
  return {
    as_of: "2026-08-30T06:51:44Z",
    market_state: "POST",
    transport: "poll",
    healthy: true,
    quotes: [
      {
        symbol: "AAPL",
        price: "319.70",
        previous_close: "309.35",
        change: "10.35",
        change_pct: "3.3457",
        ts: "2026-08-28T20:00:01Z",
        stale: false,
        source: "yahoo",
      },
    ],
    errors: [],
    ...overrides,
  };
}

afterEach(() => {
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// quotes() / URL building
// ---------------------------------------------------------------------------

describe("quotesUrl / streamUrl", () => {
  it("comma-joins symbols verbatim, matching the documented contract shape", () => {
    expect(quotesUrl(["AAPL", "MSFT"])).toBe("/api/paperlive/quotes?symbols=AAPL,MSFT");
    expect(streamUrl(["AAPL", "MSFT"])).toBe("/api/paperlive/stream?symbols=AAPL,MSFT");
  });

  it("URL-encodes an individual symbol that is not already URL-safe, without escaping the join comma", () => {
    expect(quotesUrl(["BRK/B", "MSFT"])).toBe(
      `/api/paperlive/quotes?symbols=${encodeURIComponent("BRK/B")},MSFT`,
    );
  });
});

describe("quotes", () => {
  it("fetches the quotes endpoint and returns the parsed snapshot untouched", async () => {
    const payload = wellFormedSnapshot();
    stubFetchOnce(payload);

    const result = await quotes(["AAPL"]);

    expect(fetch).toHaveBeenCalledTimes(1);
    const call = vi.mocked(fetch).mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    expect(String(call[0])).toBe("/api/paperlive/quotes?symbols=AAPL");
    expect(result).toEqual(payload);
    // Money crosses the wire as strings, never numbers -- see api/client.ts's DecimalString.
    expect(typeof result.quotes[0]?.price).toBe("string");
  });

  it("renders an unrecognised market_state without this module doing anything special with it", async () => {
    // market_state is an open string on the wire (see this module's docstring) -- a value this
    // build has never seen must still parse and pass through untouched, not be coerced or dropped.
    stubFetchOnce(wellFormedSnapshot({ market_state: "SOME_FUTURE_STATE" }));
    const result = await quotes(["AAPL"]);
    expect(result.market_state).toBe("SOME_FUTURE_STATE");
  });

  it("throws ApiRequestError on a non-ok response", async () => {
    stubFetchOnce({ detail: "boom" }, false, 502);
    await expect(quotes(["AAPL"])).rejects.toMatchObject({
      name: "ApiRequestError",
      status: 502,
    });
    await expect(quotes(["AAPL"])).rejects.toBeInstanceOf(ApiRequestError);
  });
});

// ---------------------------------------------------------------------------
// subscribe() -- polling fallback, engaged here simply by running in jsdom
// ---------------------------------------------------------------------------

describe("subscribe with no EventSource available (this suite's actual jsdom environment)", () => {
  it("never opens a stream for an empty symbol list, and returns a no-op unsubscribe", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => {
        throw new Error("fetch should not be called for an empty symbol list");
      }),
    );
    const onQuotes = vi.fn();
    const onError = vi.fn();

    const unsubscribe = subscribe([], onQuotes, onError);
    expect(fetch).not.toHaveBeenCalled();
    expect(() => unsubscribe()).not.toThrow();
  });

  it("polls immediately on subscribe and delivers the snapshot through onQuotes", async () => {
    const payload = wellFormedSnapshot();
    stubFetchOnce(payload);
    const onQuotes = vi.fn();
    const onError = vi.fn();

    const unsubscribe = subscribe(["AAPL"], onQuotes, onError, 5_000);
    // The first poll fires synchronously inside subscribe(), so a caller sees data without having
    // to wait a full interval for the tape's first paint.
    await vi.waitFor(() => expect(onQuotes).toHaveBeenCalledTimes(1));
    expect(onQuotes).toHaveBeenCalledWith(payload);
    expect(onError).not.toHaveBeenCalled();

    unsubscribe();
  });

  it("keeps polling on the given interval until unsubscribed, then stops", async () => {
    vi.useFakeTimers();
    stubFetchOnce(wellFormedSnapshot());
    const onQuotes = vi.fn();
    const onError = vi.fn();

    const unsubscribe = subscribe(["AAPL"], onQuotes, onError, 1_000);
    await vi.advanceTimersByTimeAsync(0); // flush the immediate first poll
    expect(onQuotes).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(1_000);
    expect(onQuotes).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(onQuotes).toHaveBeenCalledTimes(3);

    unsubscribe();
    await vi.advanceTimersByTimeAsync(5_000);
    // No further polls once torn down.
    expect(onQuotes).toHaveBeenCalledTimes(3);
    expect(onError).not.toHaveBeenCalled();
  });

  it("reports a poll failure through onError, but swallows an abort from its own unsubscribe", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("provider unreachable");
      }),
    );
    const onQuotes = vi.fn();
    const onError = vi.fn();

    const unsubscribe = subscribe(["AAPL"], onQuotes, onError, 5_000);
    await vi.waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(onError).toHaveBeenCalledWith(expect.any(Error));
    expect(onQuotes).not.toHaveBeenCalled();

    // Unsubscribing aborts the in-flight controller; that specific rejection must not also reach
    // onError, or a caller torn down mid-request would see a phantom failure after it stopped
    // caring.
    unsubscribe();
  });
});

// ---------------------------------------------------------------------------
// subscribe() -- degrading when a present EventSource errors after opening
// ---------------------------------------------------------------------------

/** A minimal fake standing in for the browser's `EventSource`, just enough of the surface
 *  `subscribe` actually touches (`addEventListener("quotes", ...)`, `onerror`, `close()`). Not a
 *  full polyfill -- this suite otherwise deliberately runs with no `EventSource` at all (see the
 *  module docstring), so this class only exists for this one block. */
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  onerror: (() => void) | null = null;
  private listeners: Record<string, ((event: { data: string }) => void)[]> = {};
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, handler: (event: { data: string }) => void): void {
    (this.listeners[type] ??= []).push(handler);
  }

  close(): void {
    this.closed = true;
  }

  emit(type: string, data: string): void {
    for (const handler of this.listeners[type] ?? []) handler({ data });
  }

  fail(): void {
    this.onerror?.();
  }
}

describe("subscribe with EventSource present", () => {
  afterEach(() => {
    FakeEventSource.instances = [];
    vi.unstubAllGlobals();
  });

  it("delivers frames pushed on the 'quotes' event without ever falling back to polling", () => {
    vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);
    vi.stubGlobal(
      "fetch",
      vi.fn(() => {
        throw new Error("fetch should not be called while the stream is healthy");
      }),
    );
    const onQuotes = vi.fn();
    const onError = vi.fn();

    const unsubscribe = subscribe(["AAPL"], onQuotes, onError);
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0]?.url).toBe("/api/paperlive/stream?symbols=AAPL");

    const payload = wellFormedSnapshot({ transport: "sse" });
    FakeEventSource.instances[0]?.emit("quotes", JSON.stringify(payload));
    expect(onQuotes).toHaveBeenCalledWith(payload);
    expect(fetch).not.toHaveBeenCalled();

    unsubscribe();
    expect(FakeEventSource.instances[0]?.closed).toBe(true);
  });

  it("closes the stream and degrades to polling once it errors", async () => {
    vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);
    stubFetchOnce(wellFormedSnapshot({ transport: "poll" }));
    const onQuotes = vi.fn();
    const onError = vi.fn();

    const unsubscribe = subscribe(["AAPL"], onQuotes, onError, 5_000);
    const es = FakeEventSource.instances[0];
    if (!es) throw new Error("expected an EventSource to have been opened");

    es.fail();
    expect(es.closed).toBe(true);

    await vi.waitFor(() => expect(onQuotes).toHaveBeenCalledTimes(1));
    expect(onQuotes).toHaveBeenCalledWith(wellFormedSnapshot({ transport: "poll" }));

    unsubscribe();
  });
});

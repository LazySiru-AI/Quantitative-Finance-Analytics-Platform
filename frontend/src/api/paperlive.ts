/**
 * Typed client for the paper-live price feed (`/api/paperlive/quotes`, `/api/paperlive/stream`).
 *
 * Same wire discipline as `api/paperdesk.ts`: `price`, `previous_close`, `change` and `change_pct`
 * are `DecimalString`s, never JSON numbers -- see `api/client.ts`'s `DecimalString` docstring.
 * Nothing here parses one of those for arithmetic; `LiveTape.tsx` renders them and colours them via
 * `moneyTone`/`fractionStringTone` (re-exported from `@/api/paperdesk`), the same sign-only parse
 * every other money figure in this app uses.
 *
 * **`market_state`, `transport` and `source` are open strings, not closed unions.** They are typed
 * `string` here on purpose. `@/api/paperdesk`'s own module docstring records what happened the one
 * time this app modelled a server-supplied string as a closed TypeScript union with a throwing
 * exhaustiveness check (`ExitReason` gaining `rebalance_trim`): the whole Paper Desk page went down
 * over one label the client had never seen. `market_state` in particular is exactly that shape again
 * -- a backend enum a client build cannot see ahead of a deploy -- so this file renders whatever
 * string arrives rather than asserting it already knows the whole set.
 */

import { ApiRequestError, type DecimalString } from "@/api/client";

export interface PaperLiveQuote {
  symbol: string;
  price: DecimalString;
  previous_close: DecimalString;
  change: DecimalString;
  change_pct: DecimalString;
  ts: string;
  stale: boolean;
  /** Open string (e.g. `"yahoo"`) -- see the module docstring. Render verbatim, never switch on it. */
  source: string;
}

export interface PaperLiveQuoteError {
  symbol: string;
  message: string;
}

/** The body both `GET /api/paperlive/quotes` and the `event: quotes` SSE frames carry. */
export interface PaperLiveQuotes {
  as_of: string;
  /** Open string (e.g. `"PRE" | "REGULAR" | "POST" | "CLOSED"`, but never assumed closed here --
   *  see the module docstring). Render verbatim. */
  market_state: string;
  /** Open string (`"poll"`, `"sse"`, ...) naming how this snapshot was produced. Render verbatim. */
  transport: string;
  healthy: boolean;
  quotes: PaperLiveQuote[];
  errors: PaperLiveQuoteError[];
}

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

/** Builds the `symbols=` query value verbatim as the contract shows it (`AAPL,MSFT`) -- a literal
 *  comma-joined list, each symbol individually escaped, rather than `encodeURIComponent` on the
 *  whole joined string (which would percent-encode the commas and produce a URL that still works
 *  but no longer matches the documented shape). */
function symbolsParam(symbols: string[]): string {
  return symbols.map((s) => encodeURIComponent(s)).join(",");
}

export function quotesUrl(symbols: string[]): string {
  return `/api/paperlive/quotes?symbols=${symbolsParam(symbols)}`;
}

export function streamUrl(symbols: string[]): string {
  return `/api/paperlive/stream?symbols=${symbolsParam(symbols)}`;
}

/** One-shot fetch of the current snapshot for `symbols`. Used directly by the polling fallback in
 *  `subscribe` below, and available to any caller that just wants a single read. */
export function quotes(symbols: string[], signal?: AbortSignal): Promise<PaperLiveQuotes> {
  return requestJson<PaperLiveQuotes>(quotesUrl(symbols), { signal: signal ?? null });
}

export type Unsubscribe = () => void;

/** How often the polling fallback re-fetches. Chosen as a reasonable "feels live" cadence for a
 *  desk view, not a value the contract specifies -- there is no server-driven interval to defer to
 *  since polling only ever engages when the push transport (SSE) is unavailable. */
const DEFAULT_POLL_INTERVAL_MS = 10_000;

/**
 * Live-updates `symbols` via SSE, falling back to polling `quotes()` on an interval whenever
 * `EventSource` is unavailable (jsdom, this app's own test environment, has none) or the stream
 * itself errors out. Returns an unsubscribe function that tears down whichever transport is
 * currently active.
 *
 * `onQuotes` fires once per snapshot, whichever transport produced it -- a caller does not need to
 * know or care which one is currently active; `PaperLiveQuotes.transport` on the payload itself
 * already says that. `onError` fires for a parse failure on a pushed frame, or for a poll request
 * that rejected for a reason other than its own abort (an aborted in-flight poll from a torn-down
 * subscription is not an error a caller needs to hear about).
 *
 * An empty `symbols` list subscribes to nothing and returns a no-op unsubscribe -- there is no
 * sensible request to make for a live tape with no rows, and neither transport is opened.
 */
export function subscribe(
  symbols: string[],
  onQuotes: (data: PaperLiveQuotes) => void,
  onError: (error: unknown) => void,
  pollIntervalMs: number = DEFAULT_POLL_INTERVAL_MS,
): Unsubscribe {
  if (symbols.length === 0) return () => {};

  if (typeof EventSource === "undefined") {
    return pollFallback(symbols, onQuotes, onError, pollIntervalMs);
  }

  let closed = false;
  let source: EventSource | null = new EventSource(streamUrl(symbols));
  let fallback: Unsubscribe | null = null;

  const degradeToPolling = () => {
    if (closed || fallback) return;
    source?.close();
    source = null;
    fallback = pollFallback(symbols, onQuotes, onError, pollIntervalMs);
  };

  source.addEventListener("quotes", (event) => {
    const raw = (event as MessageEvent<string>).data;
    try {
      onQuotes(JSON.parse(raw) as PaperLiveQuotes);
    } catch (e) {
      onError(e);
    }
  });

  // `EventSource` retries on its own schedule after an error and never surfaces the failure to
  // application code beyond `onerror` firing -- left alone, a reader watching the tape would just
  // see it go silent with no indication anything is wrong. Closing it here and switching to polling
  // means the tape keeps updating (on a coarser cadence) instead of quietly going stale.
  source.onerror = () => {
    degradeToPolling();
  };

  return () => {
    closed = true;
    source?.close();
    source = null;
    fallback?.();
    fallback = null;
  };
}

function pollFallback(
  symbols: string[],
  onQuotes: (data: PaperLiveQuotes) => void,
  onError: (error: unknown) => void,
  intervalMs: number,
): Unsubscribe {
  let cancelled = false;
  const controller = new AbortController();

  const tick = () => {
    quotes(symbols, controller.signal)
      .then((data) => {
        if (!cancelled) onQuotes(data);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        if (e instanceof DOMException && e.name === "AbortError") return;
        onError(e);
      });
  };

  tick();
  const timer = setInterval(tick, intervalMs);

  return () => {
    cancelled = true;
    controller.abort();
    clearInterval(timer);
  };
}

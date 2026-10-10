/**
 * The Influencer Personas API client's request-shaping and error-handling contract.
 *
 * `fetch` is stubbed directly (per `src/test/setup.ts`, the global throws on any unstubbed call),
 * matching the idiom in `washsales.test.ts`/`workflow.test.ts` -- this file tests the API layer
 * itself (query-string construction, POST bodies, error unwrapping), not a rendered page.
 */
import { describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "@/api/client";
import { personasApi } from "@/api/personas";

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

function lastCall(): [unknown, RequestInit | undefined] {
  const call = vi.mocked(fetch).mock.calls[0];
  if (!call) throw new Error("fetch was not called");
  return call as [unknown, RequestInit | undefined];
}

describe("personasApi query-string construction", () => {
  it("book: omits both as_of and exclude_intraday when neither is given", async () => {
    stubFetchOnce({
      persona: "creator-a",
      display_name: "Creator A",
      inception: "2026-01-01",
      as_of: null,
      notional_per_position: "1000",
      holdings: [],
      cost_basis_total: "0",
      market_value_total: "0",
      unrealised_pnl_total: "0",
      return_pct: "0",
      warnings: [],
    });

    await personasApi.book("creator-a");

    const [url] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/book");
  });

  it("book: includes as_of alone when only as_of is given", async () => {
    stubFetchOnce({
      persona: "creator-a",
      display_name: "Creator A",
      inception: "2026-01-01",
      as_of: "2026-08-01",
      notional_per_position: "1000",
      holdings: [],
      cost_basis_total: "0",
      market_value_total: "0",
      unrealised_pnl_total: "0",
      return_pct: "0",
      warnings: [],
    });

    await personasApi.book("creator-a", { as_of: "2026-08-01" });

    const [url] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/book?as_of=2026-08-01");
  });

  it("book: serializes exclude_intraday as the literal string true/false, not a coerced value", async () => {
    stubFetchOnce({
      persona: "creator-a",
      display_name: "Creator A",
      inception: "2026-01-01",
      as_of: null,
      notional_per_position: "1000",
      holdings: [],
      cost_basis_total: "0",
      market_value_total: "0",
      unrealised_pnl_total: "0",
      return_pct: "0",
      warnings: [],
    });

    await personasApi.book("creator-a", { as_of: "2026-08-01", exclude_intraday: true });

    const [url] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/book?as_of=2026-08-01&exclude_intraday=true");
  });

  it("watchlist: omits as_of when not given", async () => {
    stubFetchOnce({ as_of: "2026-09-01T00:00:00Z", entries: [], caveat: "reference only" });

    await personasApi.watchlist();

    const [url] = lastCall();
    expect(String(url)).toBe("/api/personas/watchlist");
  });

  it("watchlist: includes as_of when given", async () => {
    stubFetchOnce({ as_of: "2026-08-01T00:00:00Z", entries: [], caveat: "reference only" });

    await personasApi.watchlist({ as_of: "2026-08-01" });

    const [url] = lastCall();
    expect(String(url)).toBe("/api/personas/watchlist?as_of=2026-08-01");
  });

  it("books: takes no query params at all", async () => {
    stubFetchOnce([]);

    await personasApi.books();

    const [url] = lastCall();
    expect(String(url)).toBe("/api/personas/books");
  });

  it("regime: takes no query params at all", async () => {
    stubFetchOnce({ as_of: "2026-09-01T00:00:00Z", personas: [], risk_on: 0, risk_off: 0, mixed: 0, caveat: "" });

    await personasApi.regime();

    const [url] = lastCall();
    expect(String(url)).toBe("/api/personas/regime");
  });

  it("profileDiff: builds the query with the literal from/to param names", async () => {
    stubFetchOnce({
      persona: "creator-a",
      from_version: 1,
      to_version: 2,
      changes: [],
      added: 0,
      removed: 0,
      recited: 0,
    });

    await personasApi.profileDiff("creator-a", { from: 1, to: 2 });

    const [url] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/profile/diff?from=1&to=2");
  });
});

describe("personasApi POST bodies", () => {
  it("ask: POSTs a JSON body with the question, omitting symbol when absent", async () => {
    stubFetchOnce({
      persona: "creator-a",
      question: "What do you think of NVDA?",
      symbol: null,
      answer: "No clear stance recorded.",
      citations: [],
      stance: null,
      grounding: { ok: true, issues: [], attempts: 1, degraded: false, checked_tokens: 0 },
      degraded: false,
      cost_usd: "0.01",
    });

    await personasApi.ask("creator-a", { question: "What do you think of NVDA?" });

    const [url, init] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/ask");
    expect(init?.method).toBe("POST");
    expect(init?.headers).toMatchObject({ "Content-Type": "application/json" });
    expect(init?.body).toBe(JSON.stringify({ question: "What do you think of NVDA?" }));
  });

  it("ask: includes symbol in the body when given", async () => {
    stubFetchOnce({
      persona: "creator-a",
      question: "Bullish or bearish on NVDA?",
      symbol: "NVDA",
      answer: "Bullish, per their latest note.",
      citations: ["note-1"],
      stance: "bullish",
      grounding: { ok: true, issues: [], attempts: 1, degraded: false, checked_tokens: 12 },
      degraded: false,
      cost_usd: "0.02",
    });

    await personasApi.ask("creator-a", { question: "Bullish or bearish on NVDA?", symbol: "NVDA" });

    const [, init] = lastCall();
    expect(init?.body).toBe(
      JSON.stringify({ question: "Bullish or bearish on NVDA?", symbol: "NVDA" }),
    );
  });

  it("critique: POSTs the card as JSON with the right headers", async () => {
    stubFetchOnce({
      persona: "creator-a",
      verdict: "mixed",
      assessment: "Partially aligned with their methodology.",
      citations: ["note-1"],
      caveat: "An impression of their view, not advice.",
      degraded: false,
      cost_usd: "0.03",
    });

    const card = { rule_shape: "momentum", params: { lookback: 12 } };
    await personasApi.critique("creator-a", { card });

    const [url, init] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/critique");
    expect(init?.method).toBe("POST");
    expect(init?.headers).toMatchObject({ "Content-Type": "application/json" });
    expect(init?.body).toBe(JSON.stringify({ card }));
  });

  it("strategyCard: POSTs with no body", async () => {
    stubFetchOnce({
      persona: "creator-a",
      mapped: true,
      reason: "",
      rule_shape: "momentum",
      card: { rule_shape: "momentum" },
      rationale: "Maps their trend-following technique.",
      citations: ["note-1"],
      caveat: "Inspired-by, no edge expected.",
      degraded: false,
      cost_usd: "0.05",
      version: 1,
      fidelity: 0.6,
      techniques_total: 5,
      techniques_represented: 3,
      unrepresentable: ["opening-range box"],
    });

    await personasApi.strategyCard("creator-a");

    const [url, init] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/strategy-card");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeUndefined();
  });

  it("consolidate: keeps its original two-argument call signature working (slug, signal)", async () => {
    stubFetchOnce({
      persona: "creator-a",
      version: 2,
      consolidated_at: "2026-09-01T00:00:00Z",
      note_count: 10,
      summary: "A trend-following trader.",
      beliefs: [],
      playbook: [],
      methodology: [],
      regime: null,
      vocabulary: [],
      degraded: false,
      path: "profile.md",
    });

    const controller = new AbortController();
    await personasApi.consolidate("creator-a", controller.signal);

    const [url, init] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/consolidate");
    expect(init?.method).toBe("POST");
    expect(init?.signal).toBe(controller.signal);
  });

  it("consolidate: sends incremental=true when requested via the options form", async () => {
    stubFetchOnce({
      persona: "creator-a",
      version: 3,
      consolidated_at: "2026-09-02T00:00:00Z",
      note_count: 12,
      summary: "A trend-following trader.",
      beliefs: [],
      playbook: [],
      methodology: [],
      regime: null,
      vocabulary: [],
      degraded: false,
      path: "profile.md",
    });

    await personasApi.consolidate("creator-a", { incremental: true });

    const [url] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/consolidate?incremental=true");
  });

  it("consolidate: omits the query param entirely when called with no options at all", async () => {
    stubFetchOnce({
      persona: "creator-a",
      version: 4,
      consolidated_at: "2026-09-03T00:00:00Z",
      note_count: 13,
      summary: "A trend-following trader.",
      beliefs: [],
      playbook: [],
      methodology: [],
      regime: null,
      vocabulary: [],
      degraded: false,
      path: "profile.md",
    });

    await personasApi.consolidate("creator-a");

    const [url] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/consolidate");
  });
});

describe("personasApi GET routes", () => {
  it("timeline: fetches the right path and parses the response", async () => {
    const payload = {
      persona: "creator-a",
      entries: [
        {
          note_id: "note-1",
          published: "2026-08-01T00:00:00Z",
          title: "Market update",
          summary: "Bullish on NVDA.",
          themes: ["semiconductors"],
          symbols: ["NVDA"],
          url: "https://youtube.com/watch?v=abc",
        },
      ],
      stance_timelines: [
        {
          symbol: "NVDA",
          points: [
            { note_id: "note-1", said_on: "2026-08-01T00:00:00Z", stance: "bullish", reasoning: "Strong earnings." },
          ],
        },
      ],
    };
    stubFetchOnce(payload);

    const result = await personasApi.timeline("creator-a");

    const [url] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/timeline");
    expect(result).toEqual(payload);
  });

  it("backtest: fetches the right path", async () => {
    stubFetchOnce({
      persona: "creator-a",
      as_of: "2026-09-01T00:00:00Z",
      benchmark: "SPY",
      call_count: 0,
      horizons: [],
      caveat: "Small samples are not evidence of skill.",
      warnings: [],
    });

    await personasApi.backtest("creator-a");

    const [url] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/backtest");
  });

  it("strategyCards: fetches the right path", async () => {
    stubFetchOnce([]);

    await personasApi.strategyCards("creator-a");

    const [url] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/strategy-cards");
  });
});

describe("personasApi chat routes (Phase 9)", () => {
  function chatThread(overrides: Record<string, unknown> = {}) {
    return {
      thread_id: "thread-1",
      persona: "creator-a",
      title: "",
      created_at: "2026-09-05T00:00:00Z",
      updated_at: "2026-09-05T00:00:00Z",
      turn_count: 0,
      spent_usd: "0.00",
      turns: [],
      ...overrides,
    };
  }

  function chatTurn(overrides: Record<string, unknown> = {}) {
    return {
      turn_id: "turn-1",
      asked_at: "2026-09-05T00:01:00Z",
      question: "What do you think of NVDA?",
      symbol: null,
      lang: "en",
      answer: "Bullish, per their latest note.",
      citations: ["note-1"],
      retrieved: ["note-1", "note-2"],
      stance: null,
      grounding: { ok: true, issues: [], attempts: 1, degraded: false, checked_tokens: 10 },
      degraded: false,
      cost_usd: "0.01",
      ...overrides,
    };
  }

  it("chats: fetches the thread list", async () => {
    stubFetchOnce([chatThread()]);

    const result = await personasApi.chats("creator-a");

    const [url, init] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/chats");
    expect(init?.method).toBeUndefined();
    expect(result).toEqual([chatThread()]);
  });

  it("createChat: POSTs with no body to create a new thread", async () => {
    stubFetchOnce(chatThread());

    const result = await personasApi.createChat("creator-a");

    const [url, init] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/chats");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeUndefined();
    expect(result).toEqual(chatThread());
  });

  it("chat: fetches one thread by id", async () => {
    stubFetchOnce(chatThread({ turns: [chatTurn()] }));

    await personasApi.chat("creator-a", "thread-1");

    const [url] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/chats/thread-1");
  });

  it("deleteChat: DELETEs the thread and returns nothing", async () => {
    stubFetchOnce(null);

    await personasApi.deleteChat("creator-a", "thread-1");

    const [url, init] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/chats/thread-1");
    expect(init?.method).toBe("DELETE");
  });

  it("sendTurn: POSTs the JSON body and omits symbol/lang when absent", async () => {
    stubFetchOnce(chatTurn());

    await personasApi.sendTurn("creator-a", "thread-1", { question: "What do you think of NVDA?" });

    const [url, init] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/chats/thread-1/turns");
    expect(init?.method).toBe("POST");
    expect(init?.headers).toMatchObject({ "Content-Type": "application/json" });
    expect(init?.body).toBe(JSON.stringify({ question: "What do you think of NVDA?" }));
  });

  it("sendTurn: includes symbol and lang in the body when given", async () => {
    stubFetchOnce(chatTurn({ symbol: "NVDA", stance: "bullish", lang: "ko" }));

    await personasApi.sendTurn("creator-a", "thread-1", {
      question: "Bullish or bearish on NVDA?",
      symbol: "NVDA",
      lang: "ko",
    });

    const [, init] = lastCall();
    expect(init?.body).toBe(
      JSON.stringify({ question: "Bullish or bearish on NVDA?", symbol: "NVDA", lang: "ko" }),
    );
  });

  it("chatContext: fetches the stale-profile context", async () => {
    stubFetchOnce({ profile_version: 1, profile_note_count: 3, note_count: 5, stale: true });

    const result = await personasApi.chatContext("creator-a");

    const [url] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/chat-context");
    expect(result).toEqual({ profile_version: 1, profile_note_count: 3, note_count: 5, stale: true });
  });
});

describe("personasApi trader routes (Phase 10)", () => {
  function traderBook(overrides: Record<string, unknown> = {}) {
    return {
      persona: "creator-a",
      display_name: "Creator A",
      inception: "2026-01-01",
      as_of: "2026-09-01",
      starting_cash: "100000.00",
      cash: "50000.00",
      equity: "105000.00",
      return_pct: "0.05",
      benchmark: "SPY",
      benchmark_return_pct: "0.12",
      excess_pct: "-0.07",
      positions: [],
      equity_curve: [],
      decisions: [],
      spent_usd: "1.50",
      warnings: [],
      ...overrides,
    };
  }

  function traderJob(overrides: Record<string, unknown> = {}) {
    return {
      job_id: "job-1",
      persona: "creator-a",
      state: "queued",
      decided_count: 0,
      started_at: null,
      finished_at: null,
      spent_usd: "0",
      error: null,
      ...overrides,
    };
  }

  it("traderBooks: fetches the collection endpoint with no query params", async () => {
    stubFetchOnce([]);

    await personasApi.traderBooks();

    const [url] = lastCall();
    expect(String(url)).toBe("/api/personas/trader/books");
  });

  it("traderBook: fetches one persona's trader book by slug", async () => {
    stubFetchOnce(traderBook());

    const result = await personasApi.traderBook("creator-a");

    const [url] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/trader");
    expect(result).toEqual(traderBook());
  });

  it("resetTrader: DELETEs the trader book and returns nothing", async () => {
    stubFetchOnce(null);

    await personasApi.resetTrader("creator-a");

    const [url, init] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/trader");
    expect(init?.method).toBe("DELETE");
  });

  it("traderDecide: POSTs with no body and returns the updated book", async () => {
    stubFetchOnce(traderBook({ as_of: "2026-09-08" }));

    const result = await personasApi.traderDecide("creator-a");

    const [url, init] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/trader/decide");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeUndefined();
    expect(result.as_of).toBe("2026-09-08");
  });

  it("traderBackfill: POSTs the inception in the JSON body when given", async () => {
    stubFetchOnce(traderJob(), true, 202);

    await personasApi.traderBackfill("creator-a", { inception: "2026-01-01" });

    const [url, init] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/trader/backfill");
    expect(init?.method).toBe("POST");
    expect(init?.headers).toMatchObject({ "Content-Type": "application/json" });
    expect(init?.body).toBe(JSON.stringify({ inception: "2026-01-01" }));
  });

  it("traderBackfill: sends an empty body (no inception key) when omitted", async () => {
    stubFetchOnce(traderJob(), true, 202);

    await personasApi.traderBackfill("creator-a", {});

    const [, init] = lastCall();
    expect(init?.body).toBe(JSON.stringify({}));
  });

  it("traderBackfillJob: fetches the job by slug and job id", async () => {
    stubFetchOnce(traderJob({ state: "running", decided_count: 4 }));

    const result = await personasApi.traderBackfillJob("creator-a", "job-1");

    const [url] = lastCall();
    expect(String(url)).toBe("/api/personas/creator-a/trader/backfill/job-1");
    expect(result.decided_count).toBe(4);
  });
});

describe("personasApi error handling", () => {
  it("throws ApiRequestError carrying the status on a non-ok response", async () => {
    stubFetchOnce({ detail: "no persona 'nope'" }, false, 404);

    await expect(personasApi.timeline("nope")).rejects.toMatchObject({
      name: "ApiRequestError",
      status: 404,
    });
  });

  it("throws ApiRequestError for a mutating route's non-ok response too", async () => {
    stubFetchOnce({ detail: "budget cap exceeded" }, false, 409);

    await expect(personasApi.ask("creator-a", { question: "?" })).rejects.toBeInstanceOf(
      ApiRequestError,
    );
  });
});

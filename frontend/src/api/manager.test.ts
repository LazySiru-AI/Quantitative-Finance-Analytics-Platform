/**
 * The Manager API client's request-shaping contract: URL, method, and query-string construction
 * for all three endpoints. `fetch` is stubbed directly (per `src/test/setup.ts`, the global throws
 * on any unstubbed call), matching the idiom in `personas.test.ts`/`washsales.test.ts` -- this file
 * tests the API layer itself, not a rendered page.
 */
import { describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "@/api/client";
import {
  managerApi,
  type Brief,
  type ChangeSet,
  type Commission,
  type DeskRun,
  type ManagerChatThread,
  type ManagerChatTurn,
  type ManagerConfig,
  type ManagerRunSummary,
  type SnapshotResult,
} from "@/api/manager";

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

function managerConfig(overrides: Partial<ManagerConfig> = {}): ManagerConfig {
  return {
    agent_available: true,
    agent_reason: "",
    autonomy: "supervised",
    unattended_kinds: [],
    autopilot_enabled: false,
    brief_time_et: "07:00",
    caps: { brief_usd: "1.00", commission_usd: "0.50", chat_usd: "0.25", daily_usd: "5.00" },
    last_brief_at: null,
    last_snapshot_at: null,
    spent_today_usd: "0.00",
    ...overrides,
  };
}

function changeSet(overrides: Partial<ChangeSet> = {}): ChangeSet {
  return {
    window: "yesterday",
    since: "2026-09-08",
    until: "2026-09-09",
    scope: "owner",
    items: [],
    sections_missing: [],
    prior_snapshot: "2026-09-08T07:00:00Z",
    warnings: [],
    ...overrides,
  };
}

function deskRun(overrides: Partial<DeskRun> = {}): DeskRun {
  return {
    run_id: "run-1",
    kind: "manager",
    state: "running",
    created_at: "2026-09-09T07:00:00Z",
    completed_at: null,
    config: {},
    stages: [],
    final_md: "",
    final_rating: "",
    degraded: false,
    error: "",
    budget: { cap_usd: "1.00", spent_usd: "0.00", calls: 0 },
    ...overrides,
  };
}

function runSummary(overrides: Partial<ManagerRunSummary> = {}): ManagerRunSummary {
  return {
    run_id: "run-1",
    kind: "manager",
    state: "succeeded",
    label: "Brief",
    created_at: "2026-09-09T07:00:00Z",
    completed_at: "2026-09-09T07:01:00Z",
    degraded: false,
    error: "",
    final_rating: "",
    cost_usd: "0.10",
    stages_total: 6,
    stages_done: 6,
    ...overrides,
  };
}

function commission(overrides: Partial<Commission> = {}): Commission {
  return {
    commission_id: "com-1",
    kind: "tradingagents",
    params: {},
    rationale: "Check NVDA earnings reaction.",
    budget_usd: "0.50",
    state: "proposed",
    child_run_id: null,
    child_summary: "",
    source_refs: [],
    ...overrides,
  };
}

function brief(overrides: Partial<Brief> = {}): Brief {
  return {
    brief_id: "brief-1",
    run_id: "run-1",
    scope: "owner",
    window: "yesterday",
    as_of: "2026-09-09",
    generated_at: "2026-09-09T07:00:00Z",
    attention: [],
    changes: changeSet(),
    synthesis: {
      assessment: [],
      agreements: [],
      conflicts: [],
      risks: [],
      open_questions: [],
      caveat: "A model's synthesis -- descriptive, not advice.",
    },
    commissions: [],
    data_health: { stale: [], unknown: [] },
    degraded: false,
    grounding: { ok: true, issues: [], attempts: 1, degraded: false, checked_tokens: 100 },
    cost_usd: "0.20",
    final_md: "",
    ...overrides,
  };
}

function chatTurn(overrides: Partial<ManagerChatTurn> = {}): ManagerChatTurn {
  return {
    turn_id: "turn-1",
    asked_at: "2026-09-09T07:05:00Z",
    question: "What changed in tax?",
    answer: "A wash sale window closed.",
    source_refs: [],
    commissions: [],
    refreshed: false,
    grounding: { ok: true, issues: [], attempts: 1, degraded: false, checked_tokens: 50 },
    degraded: false,
    cost_usd: "0.02",
    ...overrides,
  };
}

function chatThread(overrides: Partial<ManagerChatThread> = {}): ManagerChatThread {
  return {
    thread_id: "thread-1",
    title: "Tax question",
    created_at: "2026-09-09T07:05:00Z",
    updated_at: "2026-09-09T07:05:00Z",
    turn_count: 0,
    spent_usd: "0.00",
    turns: [],
    ...overrides,
  };
}

describe("managerApi.config", () => {
  it("fetches GET /api/manager/config with no query string", async () => {
    stubFetchOnce(managerConfig());

    const result = await managerApi.config();

    const [url, init] = lastCall();
    expect(String(url)).toBe("/api/manager/config");
    expect(init?.method).toBeUndefined();
    expect(result).toEqual(managerConfig());
  });

  it("passes an AbortSignal through when given", async () => {
    stubFetchOnce(managerConfig());
    const controller = new AbortController();

    await managerApi.config(controller.signal);

    const [, init] = lastCall();
    expect(init?.signal).toBe(controller.signal);
  });
});

describe("managerApi.changes", () => {
  it("builds the query string with window alone, omitting date when not given", async () => {
    stubFetchOnce(changeSet());

    await managerApi.changes({ window: "yesterday" });

    const [url] = lastCall();
    expect(String(url)).toBe("/api/manager/changes?window=yesterday");
  });

  it("includes date when given, alongside window", async () => {
    stubFetchOnce(changeSet({ window: "custom" }));

    await managerApi.changes({ window: "custom", date: "2026-09-05" });

    const [url] = lastCall();
    expect(String(url)).toBe("/api/manager/changes?window=custom&date=2026-09-05");
  });

  it("sends the week window verbatim", async () => {
    stubFetchOnce(changeSet({ window: "week" }));

    await managerApi.changes({ window: "week" });

    const [url] = lastCall();
    expect(String(url)).toBe("/api/manager/changes?window=week");
  });

  it("parses the response", async () => {
    const payload = changeSet({ since: null, warnings: ["no live feed"] });
    stubFetchOnce(payload);

    const result = await managerApi.changes({ window: "yesterday" });

    expect(result).toEqual(payload);
  });
});

describe("managerApi.snapshot", () => {
  it("POSTs to /api/manager/snapshot with no body", async () => {
    const payload: SnapshotResult = {
      as_of: "2026-09-09",
      scope: "owner",
      generated_at: "2026-09-09T12:00:00Z",
    };
    stubFetchOnce(payload);

    const result = await managerApi.snapshot();

    const [url, init] = lastCall();
    expect(String(url)).toBe("/api/manager/snapshot");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeUndefined();
    expect(result).toEqual(payload);
  });
});

describe("managerApi error handling", () => {
  it("throws ApiRequestError carrying the status on a non-ok response", async () => {
    stubFetchOnce({ detail: "no session" }, false, 401);

    await expect(managerApi.config()).rejects.toMatchObject({
      name: "ApiRequestError",
      status: 401,
    });
  });

  it("throws ApiRequestError for the snapshot endpoint's non-ok response too", async () => {
    stubFetchOnce({ detail: "budget cap exceeded" }, false, 409);

    await expect(managerApi.snapshot()).rejects.toBeInstanceOf(ApiRequestError);
  });
});

describe("managerApi layer C (briefs, runs, chats, commissions)", () => {
  it("POSTs /briefs with the window/date body", async () => {
    stubFetchOnce(deskRun());
    await managerApi.startBrief({ window: "week" });
    const [url, init] = lastCall();
    expect(String(url)).toContain("/api/manager/briefs");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ window: "week" });
  });

  it("GETs /runs and parses the summary rows", async () => {
    stubFetchOnce({ runs: [runSummary()] });
    const res = await managerApi.runs();
    const [url] = lastCall();
    expect(String(url)).toContain("/api/manager/runs");
    expect(res.runs[0]?.run_id).toBe("run-1");
  });

  it("GETs one run by id", async () => {
    stubFetchOnce(deskRun());
    await managerApi.run("run-1");
    expect(String(lastCall()[0])).toContain("/api/manager/runs/run-1");
  });

  it("POSTs a run cancel", async () => {
    stubFetchOnce(deskRun({ state: "cancelled" }));
    await managerApi.cancelRun("run-1");
    const [url, init] = lastCall();
    expect(String(url)).toContain("/api/manager/runs/run-1/cancel");
    expect(init?.method).toBe("POST");
  });

  it("GETs the latest brief", async () => {
    stubFetchOnce(brief());
    const res = await managerApi.latestBrief();
    expect(String(lastCall()[0])).toContain("/api/manager/briefs/latest");
    expect(res.synthesis.caveat).toContain("not advice");
  });

  it("GETs one brief by id", async () => {
    stubFetchOnce(brief());
    await managerApi.brief("brief-1");
    expect(String(lastCall()[0])).toContain("/api/manager/briefs/brief-1");
  });

  it("GETs the chat thread list", async () => {
    stubFetchOnce([chatThread()]);
    const res = await managerApi.chats();
    expect(String(lastCall()[0])).toContain("/api/manager/chats");
    expect(res[0]?.thread_id).toBe("thread-1");
  });

  it("POSTs to create a chat thread", async () => {
    stubFetchOnce(chatThread());
    await managerApi.createChat();
    const [url, init] = lastCall();
    expect(String(url)).toContain("/api/manager/chats");
    expect(init?.method).toBe("POST");
  });

  it("DELETEs a chat thread", async () => {
    stubFetchOnce(null, true, 204);
    await managerApi.deleteChat("thread-1");
    const [url, init] = lastCall();
    expect(String(url)).toContain("/api/manager/chats/thread-1");
    expect(init?.method).toBe("DELETE");
  });

  it("POSTs a chat turn with the question and refresh flag", async () => {
    stubFetchOnce(chatTurn());
    await managerApi.sendTurn("thread-1", { question: "what changed?", refresh: true });
    const [url, init] = lastCall();
    expect(String(url)).toContain("/api/manager/chats/thread-1/turns");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ question: "what changed?", refresh: true });
  });

  it("POSTs a commission approval", async () => {
    stubFetchOnce(commission({ state: "approved" }));
    await managerApi.approveCommission("com-1");
    const [url, init] = lastCall();
    expect(String(url)).toContain("/api/manager/commissions/com-1/approve");
    expect(init?.method).toBe("POST");
  });

  it("POSTs a commission decline", async () => {
    stubFetchOnce(commission({ state: "declined" }));
    await managerApi.declineCommission("com-1");
    const [url, init] = lastCall();
    expect(String(url)).toContain("/api/manager/commissions/com-1/decline");
    expect(init?.method).toBe("POST");
  });
});

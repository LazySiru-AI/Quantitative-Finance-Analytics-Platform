/**
 * Agent Workflow's request shaping and error handling.
 *
 * `fetch` is stubbed directly (per `src/test/setup.ts`, the global throws on any unstubbed call),
 * matching the idiom in `calendar.test.ts`/`washsales.test.ts` -- this file tests the API layer
 * itself, not a rendered page.
 */
import { describe, expect, it, vi } from "vitest";

import {
  isRunActive,
  workflowApi,
  type DeskRun,
  type DeskRunSummary,
  type ExecuteRequest,
  type RunState,
  type WorkflowBook,
  type WorkflowConfig,
  type WorkflowExecuteResult,
  type WorkflowRunRequest,
  type WorkflowStudy,
} from "@/api/workflow";

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

function wellFormedConfig(overrides: Partial<WorkflowConfig> = {}): WorkflowConfig {
  return {
    arms: [
      { key: "raw_signal", label: "Raw Signal", blurb: "The candidate scan, unfiltered." },
      { key: "ta_gated", label: "TA Gated", blurb: "Gated by Trading Agents." },
      { key: "vibe_gated", label: "Vibe Gated", blurb: "Gated by Vibe Trading." },
      { key: "full_workflow", label: "Full Workflow", blurb: "Every gate applied." },
    ],
    default_budget_usd: "20.00",
    default_per_child_budget_usd: "4.00",
    default_max_research_symbols: 3,
    default_model: "claude-opus-5",
    agent_available: true,
    agent_reason: "",
    cards: [{ agent_id: "momentum_v1", label: "Momentum v1", purpose: "Trend following" }],
    ...overrides,
  };
}

function wellFormedRun(overrides: Partial<DeskRun> = {}): DeskRun {
  return {
    run_id: "wf-run-1",
    kind: "workflow",
    state: "running",
    created_at: "2026-08-30T00:00:00Z",
    completed_at: null,
    config: { agent_card_id: null, child_runs: {} },
    stages: [],
    final_md: "",
    final_rating: "",
    degraded: false,
    error: "",
    budget: { cap_usd: "20.00", spent_usd: "0.00", calls: 0 },
    ...overrides,
  };
}

function wellFormedRunSummary(overrides: Partial<DeskRunSummary> = {}): DeskRunSummary {
  return {
    run_id: "wf-run-1",
    kind: "workflow",
    state: "succeeded",
    label: "NVDA · 2026-08-29",
    created_at: "2026-08-30T00:00:00Z",
    completed_at: "2026-08-30T00:05:00Z",
    degraded: false,
    error: "",
    final_rating: "",
    cost_usd: "3.50",
    stages_total: 8,
    stages_done: 8,
    ...overrides,
  };
}

function wellFormedBook(overrides: Partial<WorkflowBook> = {}): WorkflowBook {
  return {
    arm: "full_workflow",
    universe_source: "card",
    current_card_id: "momentum_v1",
    card_adopted_date: "2026-08-01",
    starting_cash: "100000.00",
    cash: "82000.00",
    equity: "101250.00",
    positions: [],
    orders: [],
    equity_curve: [],
    tax: null,
    as_of: "2026-08-29",
    ...overrides,
  };
}

function wellFormedStudy(overrides: Partial<WorkflowStudy> = {}): WorkflowStudy {
  return {
    benchmark: "SPY",
    benchmark_return: "0.041",
    window: { start: "2026-06-01", end: "2026-08-29" },
    arms: [],
    paired: [],
    vibe_verdict_compliance: null,
    note: "Directional study: fills mix stored-open and live-quote prices.",
    ...overrides,
  };
}

describe("workflowApi.config", () => {
  it("requests /api/workflow/config with no body", async () => {
    const payload = wellFormedConfig();
    stubFetchOnce(payload);

    const result = await workflowApi.config();

    expect(fetch).toHaveBeenCalledTimes(1);
    const call = vi.mocked(fetch).mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    expect(String(call[0])).toBe("/api/workflow/config");
    expect(result).toEqual(payload);
  });
});

describe("workflowApi.startRun", () => {
  it("POSTs the request body as JSON to /api/workflow/runs", async () => {
    stubFetchOnce(wellFormedRun());
    const body: WorkflowRunRequest = {
      agent_card_id: "momentum_v1",
      budget_usd: "20.00",
      arms_enabled: ["raw_signal", "full_workflow"],
    };

    await workflowApi.startRun(body);

    const call = vi.mocked(fetch).mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    expect(String(call[0])).toBe("/api/workflow/runs");
    const init = call[1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({ "Content-Type": "application/json" });
    expect(JSON.parse(init.body as string)).toEqual(body);
  });

  it("sends agent_card_id: null verbatim for an auto-selected card, rather than dropping the field", async () => {
    stubFetchOnce(wellFormedRun());

    await workflowApi.startRun({ agent_card_id: null });

    const call = vi.mocked(fetch).mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    const init = call[1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({ agent_card_id: null });
  });

  it("throws ApiRequestError carrying the status on a 409 (a workflow run already in flight)", async () => {
    stubFetchOnce({ detail: "a workflow run is already in flight" }, false, 409);

    await expect(workflowApi.startRun({})).rejects.toMatchObject({
      name: "ApiRequestError",
      status: 409,
    });
  });
});

describe("workflowApi.listRuns", () => {
  it("requests the endpoint with no query parameters by default", async () => {
    stubFetchOnce({ runs: [wellFormedRunSummary()] });

    await workflowApi.listRuns();

    const call = vi.mocked(fetch).mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    expect(String(call[0])).toBe("/api/workflow/runs");
  });

  it("adds a limit query parameter when one is passed", async () => {
    stubFetchOnce({ runs: [] });

    await workflowApi.listRuns(10);

    const call = vi.mocked(fetch).mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    expect(String(call[0])).toBe("/api/workflow/runs?limit=10");
  });
});

describe("workflowApi.getRun", () => {
  it("requests /api/workflow/runs/{id}, URL-encoded", async () => {
    stubFetchOnce(wellFormedRun());

    await workflowApi.getRun("run with space");

    const call = vi.mocked(fetch).mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    expect(String(call[0])).toBe("/api/workflow/runs/run%20with%20space");
  });

  it("throws ApiRequestError on a 404 for an unknown run", async () => {
    stubFetchOnce({ detail: "not found" }, false, 404);

    await expect(workflowApi.getRun("nope")).rejects.toMatchObject({
      name: "ApiRequestError",
      status: 404,
    });
  });
});

describe("workflowApi.cancelRun", () => {
  it("sends DELETE to /api/workflow/runs/{id} and returns the cancelled run", async () => {
    const cancelled = wellFormedRun({ state: "cancelled" });
    stubFetchOnce(cancelled);

    const result = await workflowApi.cancelRun("wf-run-1");

    const call = vi.mocked(fetch).mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    expect(String(call[0])).toBe("/api/workflow/runs/wf-run-1");
    expect((call[1] as RequestInit).method).toBe("DELETE");
    expect(result.state).toBe("cancelled");
  });
});

describe("workflowApi.book", () => {
  it("requests /api/workflow/book and returns one book per arm", async () => {
    const payload = { books: [wellFormedBook(), wellFormedBook({ arm: "raw_signal" })] };
    stubFetchOnce(payload);

    const result = await workflowApi.book();

    const call = vi.mocked(fetch).mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    expect(String(call[0])).toBe("/api/workflow/book");
    expect(result).toEqual(payload);
  });
});

describe("workflowApi.executeBook", () => {
  it("POSTs an empty object by default (execute every enabled arm at the newest session)", async () => {
    const result: WorkflowExecuteResult = {
      as_of: "2026-08-29",
      filled: 2,
      rejected: 0,
      still_pending: 1,
      price_source_mix: { stored_open: 2, live_quote: 0 },
      universe_source: "card",
    };
    stubFetchOnce(result);

    const actual = await workflowApi.executeBook();

    const call = vi.mocked(fetch).mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    expect(String(call[0])).toBe("/api/workflow/book/execute");
    const init = call[1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({});
    expect(actual).toEqual(result);
  });

  it("passes as_of and arms through untouched when given", async () => {
    stubFetchOnce({
      as_of: "2026-08-28",
      filled: 1,
      rejected: 0,
      still_pending: 0,
      price_source_mix: { stored_open: 1, live_quote: 0 },
    });
    const body: ExecuteRequest = { as_of: "2026-08-28", arms: ["full_workflow"] };

    await workflowApi.executeBook(body);

    const call = vi.mocked(fetch).mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    expect(JSON.parse((call[1] as RequestInit).body as string)).toEqual(body);
  });

  it("throws ApiRequestError on a 409 (a workflow run is currently staging orders)", async () => {
    stubFetchOnce({ detail: "a workflow run is staging orders" }, false, 409);

    await expect(workflowApi.executeBook()).rejects.toMatchObject({
      name: "ApiRequestError",
      status: 409,
    });
  });
});

describe("workflowApi.study", () => {
  it("requests /api/workflow/study and returns the effectiveness study", async () => {
    const payload = wellFormedStudy();
    stubFetchOnce(payload);

    const result = await workflowApi.study();

    const call = vi.mocked(fetch).mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    expect(String(call[0])).toBe("/api/workflow/study");
    expect(result).toEqual(payload);
  });
});

describe("isRunActive", () => {
  it("keeps the poll alive for queued/running, ends it for everything else", () => {
    expect(isRunActive("queued")).toBe(true);
    expect(isRunActive("running")).toBe(true);
    expect(isRunActive("succeeded")).toBe(false);
    expect(isRunActive("failed")).toBe(false);
    expect(isRunActive("cancelled")).toBe(false);
  });

  it("treats an unknown state as active rather than throwing", () => {
    const fromAFutureBackend = "paused" as RunState;
    expect(() => isRunActive(fromAFutureBackend)).not.toThrow();
    expect(isRunActive(fromAFutureBackend)).toBe(true);
  });
});

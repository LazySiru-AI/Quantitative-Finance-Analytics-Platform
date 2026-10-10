/**
 * The Trading Agents page's honesty rules, at render level.
 *
 * Mirrors `Competition.test.tsx`'s approach: `@/api/tradingagents` is stubbed at the module boundary
 * rather than `fetch`, and fixture factories mirror the wire contract (`docs/AGENT-DESK-CONTRACT.md`)
 * field for field so a drift between this file and `api/tradingagents.ts` shows up as a type error
 * rather than a silently-wrong fixture.
 *
 * What these tests pin, matching the task's definition of done:
 *  - the static explainer renders with no fetch having resolved at all;
 *  - the run form disables Start and shows `agent_reason` when `agent_available` is `false`;
 *  - a run in `"running"` state renders its stage board, keyed on `stage_id` and grouped by `layer`;
 *  - a `"degraded"` stage's grounding issues render once that stage is expanded;
 *  - once a polled run reaches a terminal state (`"succeeded"`), the polling interval is cleared --
 *    proven with fake timers by asserting no further `getRun()` calls happen.
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import type {
  BudgetWire,
  DeskRun,
  DeskRunSummary,
  MemoryEntry,
  MemoryListResponse,
  RunsListResponse,
  StageRecord,
  StartRunRequest,
  TradingAgentsConfig,
} from "@/api/tradingagents";

const configMock = vi.fn<() => Promise<TradingAgentsConfig>>();
const startRunMock = vi.fn<(body: StartRunRequest) => Promise<DeskRun>>();
const listRunsMock = vi.fn<() => Promise<RunsListResponse>>();
const getRunMock = vi.fn<(runId: string) => Promise<DeskRun>>();
const cancelRunMock = vi.fn<(runId: string) => Promise<DeskRun>>();
const memoryMock = vi.fn<() => Promise<MemoryListResponse>>();

vi.mock("@/api/tradingagents", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/tradingagents")>();
  return {
    ...actual,
    tradingAgentsApi: {
      ...actual.tradingAgentsApi,
      config: () => configMock(),
      startRun: (body: StartRunRequest) => startRunMock(body),
      listRuns: () => listRunsMock(),
      getRun: (runId: string) => getRunMock(runId),
      cancelRun: (runId: string) => cancelRunMock(runId),
      memory: () => memoryMock(),
    },
  };
});

const { default: TradingAgents } = await import("@/pages/TradingAgents");

// The Final Report panel links to `/report/{symbol}` via react-router-dom's `Link`, which throws
// without a surrounding router -- wrap every render in a `MemoryRouter`, same as `Account.test.tsx`.
function renderTradingAgents() {
  return render(
    <MemoryRouter>
      <TradingAgents />
    </MemoryRouter>,
  );
}

// --- fixtures ----------------------------------------------------------------------------------

function tradingAgentsConfig(overrides: Partial<TradingAgentsConfig> = {}): TradingAgentsConfig {
  return {
    analysts: [
      { key: "market", label: "Market Analyst", blurb: "Price action and technicals." },
      { key: "sentiment", label: "Sentiment Analyst", blurb: "Social and options sentiment." },
      { key: "news", label: "News Analyst", blurb: "Recent headlines and events." },
      { key: "fundamentals", label: "Fundamentals Analyst", blurb: "Filings and financial statements." },
    ],
    default_debate_rounds: 1,
    default_risk_rounds: 1,
    max_rounds: 3,
    default_budget_usd: "5.00",
    default_model: "claude-haiku-4-5-20251001",
    available_models: [
      { id: "claude-haiku-4-5-20251001", label: "Haiku 4.5 (default, fastest, cheapest)" },
      { id: "claude-sonnet-5", label: "Sonnet 5" },
      { id: "claude-opus-5", label: "Opus 5 (most capable, slower)" },
    ],
    agent_available: true,
    agent_reason: "",
    ...overrides,
  };
}

function deskRunSummary(overrides: Partial<DeskRunSummary> = {}): DeskRunSummary {
  return {
    run_id: "run-1",
    kind: "tradingagents",
    state: "running",
    label: "NVDA · 2026-08-29",
    created_at: "2026-08-29T12:00:00Z",
    completed_at: null,
    degraded: false,
    error: "",
    final_rating: "",
    cost_usd: "1.23",
    stages_total: 10,
    stages_done: 3,
    ...overrides,
  };
}

function budgetWire(overrides: Partial<BudgetWire> = {}): BudgetWire {
  return { cap_usd: "5.00", spent_usd: "1.23", calls: 6, ...overrides };
}

function stageRecord(overrides: Partial<StageRecord> = {}): StageRecord {
  return {
    stage_id: "market_analyst",
    role: "market_analyst",
    label: "Market Analyst",
    seat: "",
    state: "succeeded",
    layer: 0,
    depends_on: [],
    started_at: "2026-08-29T12:00:00Z",
    completed_at: "2026-08-29T12:00:05Z",
    output_md: "# Market Analyst\n\nPrice is up on volume.",
    summary: "Bullish technical setup.",
    grounding: null,
    call_ids: ["call-1"],
    cost_usd: "0.10",
    error: "",
    ...overrides,
  };
}

function deskRun(overrides: Partial<DeskRun> = {}): DeskRun {
  return {
    run_id: "run-1",
    kind: "tradingagents",
    state: "running",
    created_at: "2026-08-29T12:00:00Z",
    completed_at: null,
    config: { symbol: "NVDA" },
    stages: [stageRecord()],
    final_md: "",
    final_rating: "",
    degraded: false,
    error: "",
    budget: budgetWire(),
    ...overrides,
  };
}

function memoryEntry(overrides: Partial<MemoryEntry> = {}): MemoryEntry {
  return {
    entry_id: "mem-1",
    symbol: "NVDA",
    trade_date: "2026-08-20",
    rating: "Buy",
    state: "resolved",
    // Fraction `DecimalString`s, same convention as `return_pct` elsewhere in this app (see
    // `formatReturnPct`'s docstring in `TradingAgents.tsx`) -- "0.0210" is +2.10%.
    raw_return_pct: "0.0530",
    alpha_return_pct: "0.0210",
    benchmark: "SPY",
    holding_days: 5,
    decision_md: "# Decision\n\nBought on strength into an upgrade.",
    reflection: "The alpha thesis held up despite a volatile week for the sector.",
    ...overrides,
  };
}

/** Renders the page with every fetch stubbed to a sane, resolvable default -- individual tests
 * override whichever mock they care about before rendering. */
function stubDefaults() {
  configMock.mockResolvedValue(tradingAgentsConfig());
  listRunsMock.mockResolvedValue({ runs: [] });
  memoryMock.mockResolvedValue({ entries: [] });
}

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("static explainer", () => {
  it("renders the pipeline explainer with no fetch having resolved", () => {
    // Deliberately never-resolving promises: this proves the explainer is a rendered constant, not
    // something that appears only once `config()`/`listRuns()`/`memory()` come back.
    configMock.mockReturnValue(new Promise<TradingAgentsConfig>(() => {}));
    listRunsMock.mockReturnValue(new Promise<RunsListResponse>(() => {}));
    memoryMock.mockReturnValue(new Promise<MemoryListResponse>(() => {}));

    renderTradingAgents();

    expect(screen.getByText("How the desk works")).toBeTruthy();
    expect(screen.getByText("Four analysts write grounded reports")).toBeTruthy();
    expect(screen.getByText("Bull and bear researchers debate")).toBeTruthy();
    expect(screen.getByText("A research manager judges the debate")).toBeTruthy();
    expect(screen.getByText("A trader turns the rating into a proposal")).toBeTruthy();
    expect(screen.getByText("Three risk analysts stress the proposal")).toBeTruthy();
    expect(screen.getByText("A portfolio manager issues the final rating")).toBeTruthy();
    expect(screen.getByText(/checked against the evidence it was given/)).toBeTruthy();
    expect(screen.getByText(/marked .ungrounded. rather than hidden/)).toBeTruthy();
  });
});

describe("run form availability", () => {
  it("disables Start and shows agent_reason when the agent layer is unavailable", async () => {
    configMock.mockResolvedValue(
      tradingAgentsConfig({
        agent_available: false,
        agent_reason: "ANTHROPIC_API_KEY is not set.",
      }),
    );
    listRunsMock.mockResolvedValue({ runs: [] });
    memoryMock.mockResolvedValue({ entries: [] });

    renderTradingAgents();

    expect(await screen.findByText("ANTHROPIC_API_KEY is not set.")).toBeTruthy();
    const startButton = screen.getByRole("button", { name: "Start" }) as HTMLButtonElement;
    expect(startButton.disabled).toBe(true);
  });

  it("lets the user pick a worker model, defaulting to the config default and sending the choice", async () => {
    configMock.mockResolvedValue(tradingAgentsConfig());
    listRunsMock.mockResolvedValue({ runs: [] });
    memoryMock.mockResolvedValue({ entries: [] });
    startRunMock.mockResolvedValue(deskRun());

    renderTradingAgents();

    // Seeded from config.default_model once config loads.
    const modelSelect = (await screen.findByRole("combobox")) as HTMLSelectElement;
    expect(modelSelect.value).toBe("claude-haiku-4-5-20251001");
    // Both selectable models are offered.
    expect(screen.getByRole("option", { name: "Opus 5 (most capable, slower)" })).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "NVDA" } });
    fireEvent.change(modelSelect, { target: { value: "claude-opus-5" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Start" }));
    });

    expect(startRunMock).toHaveBeenCalledTimes(1);
    expect(startRunMock.mock.calls[0]?.[0]?.model).toBe("claude-opus-5");
  });

  it("checking Live puts live: true in the posted body and clears the trade-date field", async () => {
    configMock.mockResolvedValue(tradingAgentsConfig());
    listRunsMock.mockResolvedValue({ runs: [] });
    memoryMock.mockResolvedValue({ entries: [] });
    startRunMock.mockResolvedValue(deskRun());

    renderTradingAgents();

    fireEvent.change(await screen.findByLabelText("Symbol"), { target: { value: "NVDA" } });
    const tradeDateInput = screen.getByLabelText("Trade date (optional)") as HTMLInputElement;
    fireEvent.change(tradeDateInput, { target: { value: "2026-08-20" } });
    expect(tradeDateInput.value).toBe("2026-08-20");

    const liveCheckbox = screen.getByRole("checkbox", {
      name: "Live (today's quote)",
    }) as HTMLInputElement;
    fireEvent.click(liveCheckbox);
    expect(liveCheckbox.checked).toBe(true);
    // Checking Live clears the trade-date field and disables it -- a live run's as-of date must be
    // today, so the UI cannot hand the backend a stale date it would 422 on anyway.
    expect(tradeDateInput.value).toBe("");
    expect(tradeDateInput.disabled).toBe(true);
    expect(screen.getByText(/the as-of date must be today/)).toBeTruthy();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Start" }));
    });

    expect(startRunMock).toHaveBeenCalledTimes(1);
    expect(startRunMock.mock.calls[0]?.[0]?.live).toBe(true);
    expect(startRunMock.mock.calls[0]?.[0]?.trade_date).toBeUndefined();
  });
});

describe("progress board", () => {
  it("renders a running run's stage board keyed on stage_id", async () => {
    stubDefaults();
    listRunsMock.mockResolvedValue({ runs: [deskRunSummary()] });
    getRunMock.mockResolvedValue(
      deskRun({
        state: "running",
        stages: [
          stageRecord({ stage_id: "market_analyst", role: "market_analyst", label: "Market Analyst", layer: 0, state: "succeeded" }),
          stageRecord({
            stage_id: "sentiment_analyst",
            role: "sentiment_analyst",
            label: "Sentiment Analyst",
            layer: 0,
            state: "running",
            output_md: "",
            summary: "",
            started_at: "2026-08-29T12:00:06Z",
            completed_at: null,
          }),
          stageRecord({
            stage_id: "news_analyst",
            role: "news_analyst",
            label: "News Analyst",
            layer: 0,
            state: "pending",
            output_md: "",
            summary: "",
            started_at: null,
            completed_at: null,
          }),
        ],
      }),
    );

    renderTradingAgents();

    const runRow = await screen.findByText("NVDA · 2026-08-29");
    fireEvent.click(runRow);

    // The stage board's own rows, not the run form's analyst checkboxes above it -- both render text
    // like "Market Analyst", so these are scoped to the stage row buttons specifically.
    expect(await screen.findByRole("button", { name: /Market Analyst/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Sentiment Analyst/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /News Analyst/ })).toBeTruthy();
    expect(screen.getByText("Running…")).toBeTruthy();
    expect(screen.getByText("Pending")).toBeTruthy();
    // The layer heading specifically -- the run form above it has its own "Analysts" section title.
    expect(screen.getByText("Analysts", { selector: "h3.ta-layer-title" })).toBeTruthy();
  });

  it("renders a degraded stage's grounding issues once expanded", async () => {
    stubDefaults();
    listRunsMock.mockResolvedValue({ runs: [deskRunSummary()] });
    getRunMock.mockResolvedValue(
      deskRun({
        state: "running",
        stages: [
          stageRecord({
            stage_id: "research_manager",
            role: "research_manager",
            label: "Research Manager",
            layer: 2,
            state: "degraded",
            output_md: "# Verdict\n\nBuy.",
            summary: "Judged the debate.",
            grounding: {
              ok: false,
              degraded: true,
              attempts: 3,
              checked_tokens: 240,
              issues: [
                {
                  kind: "ungrounded_number",
                  detail: "Claimed 40% EPS growth not found in any provided evidence.",
                },
              ],
            },
          }),
        ],
      }),
    );

    renderTradingAgents();

    const runRow = await screen.findByText("NVDA · 2026-08-29");
    fireEvent.click(runRow);

    // Scoped to the stage row's own button: the layer heading above it ("Research Manager" is also
    // this layer's label) renders the identical text.
    const stageHeader = await screen.findByRole("button", { name: /Research Manager/ });
    // Issue text is inside the stage's expandable body -- not visible until the row is opened.
    expect(screen.queryByText(/Claimed 40% EPS growth/)).toBeNull();

    fireEvent.click(stageHeader);

    expect(await screen.findByText(/Claimed 40% EPS growth not found/)).toBeTruthy();
    expect(screen.getByText("Degraded (ungrounded)")).toBeTruthy();
  });
});

describe("run polling", () => {
  it("stops polling getRun once the run reaches a terminal state", async () => {
    stubDefaults();
    listRunsMock.mockResolvedValue({ runs: [deskRunSummary({ state: "running" })] });
    getRunMock.mockResolvedValue(deskRun({ state: "running" }));

    renderTradingAgents();

    const runRow = await screen.findByText("NVDA · 2026-08-29");

    vi.useFakeTimers();
    fireEvent.click(runRow);

    // Flush the initial `getRun()` call triggered by opening the run -- plain microtask ticks, which
    // fake timers do not gate (only setTimeout/setInterval are faked).
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(getRunMock).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Progress -- running")).toBeTruthy();

    // First poll tick: the run finishes.
    getRunMock.mockResolvedValue(deskRun({ state: "succeeded", final_rating: "Buy", final_md: "# Buy NVDA" }));
    listRunsMock.mockResolvedValue({ runs: [deskRunSummary({ state: "succeeded", final_rating: "Buy" })] });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(getRunMock).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Progress -- succeeded")).toBeTruthy();

    // Further wall-clock time passes, but the interval was cleared on the terminal state -- no more
    // calls to getRun().
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000 * 5);
    });
    expect(getRunMock).toHaveBeenCalledTimes(2);
  });
});

describe("decision memory panel", () => {
  it("renders a resolved entry with alpha shown as the headline figure, raw return secondary", async () => {
    stubDefaults();
    memoryMock.mockResolvedValue({ entries: [memoryEntry()] });

    renderTradingAgents();

    expect(await screen.findByText("Decision memory")).toBeTruthy();
    // The heading above renders immediately regardless of fetch state -- wait on the memory entry's
    // own content (which only appears once `memoryMock` resolves) before asserting on it, rather than
    // racing the fetch with a synchronous `getByText`.
    expect(await screen.findByText("NVDA", { selector: ".ta-memory-symbol" })).toBeTruthy();
    expect(screen.getByText("2026-08-20")).toBeTruthy();
    expect(screen.getByText("Resolved")).toBeTruthy();
    // Alpha is labelled against its own benchmark and rendered signed -- the headline metric.
    expect(screen.getByText("Alpha vs SPY")).toBeTruthy();
    expect(screen.getByText("+2.10%", { selector: ".ta-memory-metric-value" })).toBeTruthy();
    // Raw return is present but rendered as the secondary figure, not the headline one.
    expect(screen.getByText("Raw return")).toBeTruthy();
    expect(screen.getByText("+5.30%", { selector: ".ta-memory-metric-value-secondary" })).toBeTruthy();
    expect(screen.getByText("5d")).toBeTruthy();
    expect(screen.getByText(/alpha thesis held up/)).toBeTruthy();

    // `decision_md` is collapsed until expanded.
    expect(screen.queryByText(/Bought on strength/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Show decision/ }));
    expect(await screen.findByText(/Bought on strength/)).toBeTruthy();
  });

  it("renders a pending entry without showing a fake zero for its outcome fields", async () => {
    stubDefaults();
    memoryMock.mockResolvedValue({
      entries: [
        memoryEntry({
          entry_id: "mem-2",
          state: "pending",
          raw_return_pct: null,
          alpha_return_pct: null,
          holding_days: null,
          reflection: "",
        }),
      ],
    });

    renderTradingAgents();

    expect(await screen.findByText("Pending")).toBeTruthy();
    // Both outcome figures and the holding-days field render an em dash, never "0.00%"/"0d" -- a
    // null outcome and a zero outcome are different things this app is careful not to conflate.
    const alphaValue = screen.getByText("Alpha vs SPY").parentElement;
    expect(alphaValue?.textContent).toContain("—");
    expect(alphaValue?.textContent).not.toContain("0.00%");
    expect(screen.queryByText("0.00%")).toBeNull();
    expect(screen.queryByText("0d")).toBeNull();
    // No reflection yet -- `reflection` is `""` while pending, per the contract.
    expect(screen.queryByText(/alpha thesis held up/)).toBeNull();
  });

  it("renders an honest empty state when no decisions have been recorded", async () => {
    stubDefaults();
    memoryMock.mockResolvedValue({ entries: [] });

    renderTradingAgents();

    expect(await screen.findByText("No decisions recorded yet.")).toBeTruthy();
  });

  it("does not blank the rest of the page when the memory fetch fails", async () => {
    configMock.mockResolvedValue(tradingAgentsConfig());
    listRunsMock.mockResolvedValue({ runs: [] });
    memoryMock.mockRejectedValue(new Error("memory endpoint is down"));

    renderTradingAgents();

    expect(await screen.findByText("memory endpoint is down")).toBeTruthy();
    // Every other panel on the page still renders normally -- one bad request must not blank it.
    expect(screen.getByText("How the desk works")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start" })).toBeTruthy();
    expect(await screen.findByText("No runs yet -- start one above.")).toBeTruthy();
  });
});

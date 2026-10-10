/**
 * The Agent Workflow page's honesty rules, at render level.
 *
 * Mirrors `VibeTrading.test.tsx`'s approach: `@/api/workflow` is stubbed at the module boundary
 * rather than `fetch`, and fixture factories mirror the wire contract
 * (`docs/AGENT-DESK-CONTRACT.md`) field for field so a drift between this file and `api/workflow.ts`
 * shows up as a type error rather than a silently-wrong fixture.
 *
 * What these tests pin:
 *  - the static explainer renders immediately, before any fetch resolves -- it is a constant, not
 *    fetched content;
 *  - Start is disabled, with the backend's own reason shown, when the agent layer is unavailable;
 *  - a started run renders its stages grouped into layers, including a per-symbol research stage;
 *  - the book panel renders per-arm cash/equity, positions and orders (with fill price/source);
 *  - the study panel renders the arm metrics table and, prominently, the directional-study `note`.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  BudgetWire,
  CandidateObservation,
  DeskRun,
  DeskRunSummary,
  ExecuteRequest,
  GateDecision,
  StageRecord,
  UniverseMode,
  WorkflowBook,
  WorkflowCandidates,
  WorkflowConfig,
  WorkflowExecuteResult,
  WorkflowRunRequest,
  WorkflowStudy,
} from "@/api/workflow";

const configMock = vi.fn<() => Promise<WorkflowConfig>>();
const startRunMock = vi.fn<(body: WorkflowRunRequest) => Promise<DeskRun>>();
const listRunsMock = vi.fn<() => Promise<{ runs: DeskRunSummary[] }>>();
const getRunMock = vi.fn<(runId: string) => Promise<DeskRun>>();
const cancelRunMock = vi.fn<(runId: string) => Promise<DeskRun>>();
const bookMock = vi.fn<(universeSource?: UniverseMode) => Promise<{ books: WorkflowBook[] }>>();
const executeBookMock = vi.fn<(body?: ExecuteRequest) => Promise<WorkflowExecuteResult>>();
const studyMock = vi.fn<(universeSource?: UniverseMode) => Promise<WorkflowStudy>>();
const candidatesMock = vi.fn<
  (params?: {
    universeSource?: UniverseMode;
    state?: "pending" | "resolved";
    symbol?: string;
    limit?: number;
  }) => Promise<WorkflowCandidates>
>();

vi.mock("@/api/workflow", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/workflow")>();
  return {
    ...actual,
    workflowApi: {
      config: () => configMock(),
      startRun: (body: WorkflowRunRequest) => startRunMock(body),
      listRuns: () => listRunsMock(),
      getRun: (runId: string) => getRunMock(runId),
      cancelRun: (runId: string) => cancelRunMock(runId),
      book: (universeSource?: UniverseMode) => bookMock(universeSource),
      executeBook: (body?: ExecuteRequest) => executeBookMock(body),
      study: (universeSource?: UniverseMode) => studyMock(universeSource),
      candidates: (params?: Parameters<typeof candidatesMock>[0]) => candidatesMock(params),
    },
  };
});

const { default: AgentWorkflow } = await import("@/pages/AgentWorkflow");

// --- fixtures --------------------------------------------------------------------------------------

function workflowConfig(overrides: Partial<WorkflowConfig> = {}): WorkflowConfig {
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

function stageRecord(overrides: Partial<StageRecord> = {}): StageRecord {
  return {
    stage_id: "regime_call",
    role: "market_analyst",
    label: "Regime Call",
    seat: "",
    state: "succeeded",
    layer: 0,
    depends_on: [],
    started_at: "2026-08-30T00:00:00Z",
    completed_at: "2026-08-30T00:01:00Z",
    output_md: "# Regime\nRisk-on.",
    summary: "Risk-on.",
    grounding: { ok: true, issues: [], attempts: 1, degraded: false, checked_tokens: 100 },
    call_ids: ["call-1"],
    cost_usd: "0.20",
    error: "",
    ...overrides,
  };
}

function budgetWire(overrides: Partial<BudgetWire> = {}): BudgetWire {
  return { cap_usd: "20.00", spent_usd: "0.20", calls: 1, ...overrides };
}

function deskRun(overrides: Partial<DeskRun> = {}): DeskRun {
  return {
    run_id: "wf-run-1",
    kind: "workflow",
    state: "running",
    created_at: "2026-08-30T00:00:00Z",
    completed_at: null,
    config: { agent_card_id: null, child_runs: {} },
    stages: [stageRecord()],
    final_md: "",
    final_rating: "",
    degraded: false,
    error: "",
    budget: budgetWire(),
    ...overrides,
  };
}

function workflowBook(overrides: Partial<WorkflowBook> = {}): WorkflowBook {
  return {
    arm: "full_workflow",
    universe_source: "card",
    current_card_id: "momentum_v1",
    card_adopted_date: "2026-08-01",
    starting_cash: "100000.00",
    cash: "82000.00",
    equity: "101250.00",
    positions: [
      { symbol: "NVDA", qty: "50", avg_cost: "120.00", market_value: "6500.00" },
    ],
    orders: [
      {
        order_id: "ord-1",
        arm: "full_workflow",
        agent_card_id: "momentum_v1",
        symbol: "NVDA",
        side: "buy",
        notional: "6000.00",
        decision_date: "2026-08-28",
        fill_date: "2026-08-29",
        status: "filled",
        thesis: "Momentum continuation.",
        invalidation: "Close below 20dma.",
        stop_level: "110.00",
        regime: "risk_on",
        conviction: "0.7",
        evidence: ["research_NVDA"],
        created_by_run_id: "wf-run-0",
        fill: { price: "120.00", price_source: "stored_open", qty: "50", slippage: "0.00", filled_at: "2026-08-29T13:30:00Z" },
        reject_reason: "",
      },
    ],
    equity_curve: [{ date: "2026-08-29", equity: "101250.00" }],
    tax: null,
    as_of: "2026-08-29",
    ...overrides,
  };
}

function workflowStudy(overrides: Partial<WorkflowStudy> = {}): WorkflowStudy {
  return {
    benchmark: "SPY",
    benchmark_return: "0.041",
    window: { start: "2026-06-01", end: "2026-08-29" },
    arms: [
      {
        arm: "full_workflow",
        universe_source: "card",
        total_return: "0.062",
        max_drawdown: "-0.03",
        realized_vol: "0.011",
        win_rate: "0.55",
        exposure: "0.8",
        adjusted_excess: "0.029",
        trades: 12,
        live_fill_fraction: "0.10",
      },
    ],
    paired: [
      { arm: "full_workflow", universe_source: "card", mean_daily_diff: "0.0004", bootstrap_p: "0.08" },
    ],
    vibe_verdict_compliance: "0.92",
    note: "Directional study: fills mix stored-open and live-quote prices, not a guaranteed-fill backtest.",
    ...overrides,
  };
}

function candidateObservation(overrides: Partial<CandidateObservation> = {}): CandidateObservation {
  return {
    obs_id: "obs-1",
    run_id: "wf-run-1",
    symbol: "NVDA",
    decision_date: "2026-08-28",
    agent_card_id: "momentum_v1",
    regime: "risk_on",
    entry_rank: 1,
    gates: [
      {
        gate: "ta_gated",
        passed: true,
        detail: "Trend confirmed.",
        was_explicit: true,
        verdict_source: "fresh",
      } satisfies GateDecision,
    ],
    state: "resolved",
    horizon_days: 10,
    forward_return_pct: "0.021",
    benchmark_return_pct: "0.008",
    alpha_return_pct: "0.013",
    resolved_at: "2026-08-29T13:30:00Z",
    unpriceable: false,
    universe_source: "card",
    skip_reason: null,
    skip_detail: "",
    avoided_cost_usd: "0.00",
    ...overrides,
  };
}

function workflowCandidates(overrides: Partial<WorkflowCandidates> = {}): WorkflowCandidates {
  return {
    universe_source: null,
    total: 0,
    observations: [],
    skip_reasons: {},
    verdict_sources: { fresh: 0, cached: 0, mixed: 0 },
    avoided_cost_usd: "0.00",
    ...overrides,
  };
}

/** The default happy-path wiring most tests start from. Individual tests override whichever mock
 *  they need a different answer from before rendering. */
function mockHappyPath() {
  configMock.mockResolvedValue(workflowConfig());
  listRunsMock.mockResolvedValue({ runs: [] });
  bookMock.mockResolvedValue({ books: [] });
  studyMock.mockResolvedValue(workflowStudy({ arms: [], paired: [] }));
  candidatesMock.mockResolvedValue(workflowCandidates());
}

beforeEach(() => {
  configMock.mockReset();
  startRunMock.mockReset();
  listRunsMock.mockReset();
  getRunMock.mockReset();
  cancelRunMock.mockReset();
  bookMock.mockReset();
  executeBookMock.mockReset();
  studyMock.mockReset();
  candidatesMock.mockReset();
  // A sane default so tests that don't care about the candidates panel don't have to wire it up --
  // `workflowApi.candidates` is called unconditionally on mount, and an unmocked `vi.fn()` returns
  // `undefined`, which would throw inside the page's `.then()` chain rather than just leaving the
  // panel in its loading state.
  candidatesMock.mockResolvedValue(workflowCandidates());
});

// --- tests -------------------------------------------------------------------------------------------

describe("the static explainer", () => {
  it("renders immediately, before any fetch resolves", () => {
    // Every mock is left pending (never resolved) -- if the explainer depended on a fetch, none of
    // its text would appear yet.
    configMock.mockReturnValue(new Promise(() => {}));
    listRunsMock.mockReturnValue(new Promise(() => {}));
    bookMock.mockReturnValue(new Promise(() => {}));
    studyMock.mockReturnValue(new Promise(() => {}));

    render(<AgentWorkflow />);

    expect(screen.getByText(/A regime call reads current market data/)).toBeTruthy();
    expect(screen.getByText(/strategy card is selected for that regime/)).toBeTruthy();
    expect(screen.getByText(/entry candidates/)).toBeTruthy();
    expect(screen.getByText(/child Trading Agents run and Vibe Trading review/)).toBeTruthy();
    expect(screen.getByText(/stages onto four books at once/)).toBeTruthy();
  });
});

describe("agent availability", () => {
  it("disables Start and shows the backend's own reason when the agent layer is unavailable", async () => {
    configMock.mockResolvedValue(
      workflowConfig({ agent_available: false, agent_reason: "no ANTHROPIC_API_KEY set" }),
    );
    listRunsMock.mockResolvedValue({ runs: [] });
    bookMock.mockResolvedValue({ books: [] });
    studyMock.mockResolvedValue(workflowStudy({ arms: [], paired: [] }));

    render(<AgentWorkflow />);

    const startButton = (await screen.findByRole("button", {
      name: /Start run/,
    })) as HTMLButtonElement;
    await screen.findByText(/no ANTHROPIC_API_KEY set/);
    expect(startButton.disabled).toBe(true);
  });

  it("leaves Start enabled once the agent layer reports available", async () => {
    mockHappyPath();

    render(<AgentWorkflow />);

    const startButton = (await screen.findByRole("button", {
      name: /Start run/,
    })) as HTMLButtonElement;
    expect(startButton.disabled).toBe(false);
  });
});

describe("a running workflow's stage board", () => {
  it("groups run-level and per-symbol stages by layer", async () => {
    mockHappyPath();
    startRunMock.mockResolvedValue(
      deskRun({
        state: "succeeded",
        final_md: "# Entry plan\nBuy NVDA at next open.",
        stages: [
          stageRecord({ stage_id: "regime_call", label: "Regime Call", layer: 0 }),
          stageRecord({ stage_id: "strategy_select", label: "Strategy Selection", layer: 1 }),
          stageRecord({ stage_id: "candidate_scan", label: "Candidate Scan", layer: 2 }),
          stageRecord({
            stage_id: "research_NVDA",
            label: "Research · NVDA",
            layer: 3,
            role: "research_manager",
          }),
          stageRecord({
            stage_id: "entry_plan",
            label: "Entry Plan",
            layer: 6,
            role: "portfolio_manager",
          }),
        ],
      }),
    );

    render(<AgentWorkflow />);

    fireEvent.click(await screen.findByRole("button", { name: /Start run/ }));

    expect(await screen.findByText("Regime Call")).toBeTruthy();
    expect(screen.getByText("Strategy Selection")).toBeTruthy();
    expect(screen.getByText("Candidate Scan")).toBeTruthy();
    expect(screen.getByText("Research · NVDA")).toBeTruthy();
    expect(screen.getByText("Entry Plan")).toBeTruthy();
    expect(screen.getByText("Layer 0")).toBeTruthy();
    expect(screen.getByText("Layer 3")).toBeTruthy();
    expect(screen.getByText("Layer 6")).toBeTruthy();

    // The final entry plan renders once the run carries a `final_md`.
    expect(await screen.findByText(/Buy NVDA at next open/)).toBeTruthy();
  });

  it("sends the chosen arms and an explicit null card for auto-select", async () => {
    mockHappyPath();
    startRunMock.mockResolvedValue(deskRun());

    render(<AgentWorkflow />);
    fireEvent.click(await screen.findByRole("button", { name: /Start run/ }));

    expect(startRunMock).toHaveBeenCalledWith(
      expect.objectContaining({
        agent_card_id: null,
        arms_enabled: expect.arrayContaining([
          "raw_signal",
          "ta_gated",
          "vibe_gated",
          "full_workflow",
        ]),
      }),
    );
  });
});

describe("the dynamic universe controls", () => {
  it("defaults to card mode, hides the screen-only fields, and sends a request with none of the four universe keys", async () => {
    mockHappyPath();
    startRunMock.mockResolvedValue(deskRun());

    render(<AgentWorkflow />);

    // "card" is the default -- the screen-only fields never render until "screen" is chosen.
    expect(screen.queryByText("Candidate pool")).toBeNull();
    expect(screen.queryByText("Rank key")).toBeNull();
    expect(screen.queryByText(/Screen top N/)).toBeNull();

    fireEvent.click(await screen.findByRole("button", { name: /Start run/ }));

    expect(startRunMock).toHaveBeenCalledTimes(1);
    const body = startRunMock.mock.calls[0]?.[0];
    expect(body).not.toHaveProperty("universe_mode");
    expect(body).not.toHaveProperty("candidate_pool");
    expect(body).not.toHaveProperty("rank_key");
    expect(body).not.toHaveProperty("screen_top_n");
  });

  it("reveals candidate pool / rank key / top-N once screen mode is chosen, and sends them on submit", async () => {
    mockHappyPath();
    startRunMock.mockResolvedValue(deskRun());

    render(<AgentWorkflow />);

    const universeSelect = (await screen.findByLabelText("Universe")) as HTMLSelectElement;
    fireEvent.change(universeSelect, { target: { value: "screen" } });

    expect(await screen.findByText("Candidate pool")).toBeTruthy();
    expect(screen.getByText("Rank key")).toBeTruthy();

    const topNInput = screen.getByPlaceholderText("backend default");
    fireEvent.change(topNInput, { target: { value: "5" } });

    fireEvent.click(screen.getByRole("button", { name: /Start run/ }));

    expect(startRunMock).toHaveBeenCalledWith(
      expect.objectContaining({
        universe_mode: "screen",
        candidate_pool: "sector-etf",
        rank_key: "mom12_1",
        screen_top_n: 5,
      }),
    );
  });
});

describe("the paper book panel", () => {
  it("renders per-arm cash/equity, positions and order fill price/source", async () => {
    configMock.mockResolvedValue(workflowConfig());
    listRunsMock.mockResolvedValue({ runs: [] });
    bookMock.mockResolvedValue({ books: [workflowBook()] });
    studyMock.mockResolvedValue(workflowStudy({ arms: [], paired: [] }));

    render(<AgentWorkflow />);
    // The book/study/candidates panels live under the "Measure" tab -- "Run" is the default view.
    fireEvent.click(await screen.findByRole("tab", { name: "Measure" }));

    expect(await screen.findByText("full_workflow")).toBeTruthy();
    expect(screen.getByText(/Card: momentum_v1/)).toBeTruthy();
    // NVDA appears once in the positions table and once in the orders table.
    expect(screen.getAllByText("NVDA")).toHaveLength(2);
    expect(screen.getByText("stored_open")).toBeTruthy();
    expect(screen.getByText("filled")).toBeTruthy();
  });

  it("distinguishes a card-sourced book from a screen-sourced one by its universe_source badge", async () => {
    configMock.mockResolvedValue(workflowConfig());
    listRunsMock.mockResolvedValue({ runs: [] });
    bookMock.mockResolvedValue({
      books: [
        workflowBook({ universe_source: "card" }),
        workflowBook({ arm: "raw_signal", universe_source: "screen" }),
      ],
    });
    studyMock.mockResolvedValue(workflowStudy({ arms: [], paired: [] }));

    const { container } = render(<AgentWorkflow />);
    fireEvent.click(await screen.findByRole("tab", { name: "Measure" }));

    // Scoped to `.wf-universe-badge` specifically -- the page's own Card/Screened universe-filter
    // toggle (a different control, elsewhere on the page) renders the same two words as button
    // labels, so a bare `getByText` would match both and throw on ambiguity.
    await screen.findByText("full_workflow");
    const badgeTexts = Array.from(container.querySelectorAll(".wf-universe-badge")).map(
      (el) => el.textContent,
    );
    expect(badgeTexts).toContain("Card");
    expect(badgeTexts).toContain("Screened");
  });

  it("executes pending orders on click", async () => {
    configMock.mockResolvedValue(workflowConfig());
    listRunsMock.mockResolvedValue({ runs: [] });
    bookMock.mockResolvedValue({ books: [workflowBook()] });
    studyMock.mockResolvedValue(workflowStudy({ arms: [], paired: [] }));
    executeBookMock.mockResolvedValue({
      as_of: "2026-08-29",
      filled: 1,
      rejected: 0,
      still_pending: 0,
      price_source_mix: { stored_open: 1, live_quote: 0 },
      universe_source: "card",
    });

    render(<AgentWorkflow />);
    fireEvent.click(await screen.findByRole("tab", { name: "Measure" }));

    fireEvent.click(await screen.findByRole("button", { name: /Execute pending/ }));

    expect(await screen.findByText(/1\/0\/0 filled\/rejected\/pending 2026-08-29/)).toBeTruthy();
    expect(executeBookMock).toHaveBeenCalled();
  });
});

describe("the effectiveness study panel", () => {
  it("renders the arm metrics table and the directional-study caveat prominently", async () => {
    configMock.mockResolvedValue(workflowConfig());
    listRunsMock.mockResolvedValue({ runs: [] });
    bookMock.mockResolvedValue({ books: [] });
    studyMock.mockResolvedValue(workflowStudy());

    render(<AgentWorkflow />);
    fireEvent.click(await screen.findByRole("tab", { name: "Measure" }));

    const note = await screen.findByText(/Directional study: fills mix stored-open/);
    expect(note).toBeTruthy();
    expect(note.className).toContain("wf-study-note");

    expect(screen.getByText("6.20%")).toBeTruthy(); // total_return, a fraction rendered as percent
    expect(screen.getByText("0.08")).toBeTruthy(); // bootstrap_p
    expect(screen.getByText("0.92")).toBeTruthy(); // vibe verdict compliance
  });

  it("states the minimum detectable effect at the current n beside the significance heading", async () => {
    configMock.mockResolvedValue(workflowConfig());
    listRunsMock.mockResolvedValue({ runs: [] });
    bookMock.mockResolvedValue({ books: [] });
    studyMock.mockResolvedValue(
      workflowStudy({
        discrimination: [
          {
            gate: "full_workflow",
            passed_n: 9,
            refused_n: 13,
            passed_hit_rate: "0.55",
            refused_hit_rate: "0.50",
            passed_mean_forward_return: "0.01",
            refused_mean_forward_return: "0.00",
            mean_diff: "0.01",
            p_value: "0.44",
            q_value: "0.66",
          },
        ],
      }),
    );

    render(<AgentWorkflow />);
    fireEvent.click(await screen.findByRole("tab", { name: "Measure" }));

    // n is the gated-candidate count (9 passed + 13 refused), not `paired.length` -- see
    // `gatedCandidateN` in the page for why counting arms would be the wrong n.
    const power = await screen.findByTestId("wf-study-power");
    expect(power.textContent).toContain("At n=22 gated candidates");
    expect(power.textContent).toContain("about 35pp or larger");

    // A p-value with nothing beside it invites "not significant" to be read as "no effect"; the
    // power line has to sit with the significance table, not in a report nobody opens.
    const heading = screen.getByRole("heading", { name: "Paired significance vs raw signal" });
    expect(heading.compareDocumentPosition(power) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("falls back to the pre-registered figure when the backend sends no discrimination rows", async () => {
    configMock.mockResolvedValue(workflowConfig());
    listRunsMock.mockResolvedValue({ runs: [] });
    bookMock.mockResolvedValue({ books: [] });
    studyMock.mockResolvedValue(workflowStudy());

    render(<AgentWorkflow />);
    fireEvent.click(await screen.findByRole("tab", { name: "Measure" }));

    const power = await screen.findByTestId("wf-study-power");
    expect(power.textContent).toContain("No gated candidates yet");
    expect(power.textContent).toContain("about 35pp or larger");
  });

  it("shows the not-measurable notice when every gate's passed_n is 0", async () => {
    configMock.mockResolvedValue(workflowConfig());
    listRunsMock.mockResolvedValue({ runs: [] });
    bookMock.mockResolvedValue({ books: [] });
    studyMock.mockResolvedValue(
      workflowStudy({
        arms: [],
        paired: [],
        discrimination: [
          {
            gate: "ta_gated",
            passed_n: 0,
            refused_n: 12,
            passed_hit_rate: null,
            refused_hit_rate: "0.40",
            passed_mean_forward_return: null,
            refused_mean_forward_return: "-0.01",
            mean_diff: null,
            p_value: null,
            q_value: null,
          },
          {
            gate: "vibe_gated",
            passed_n: 0,
            refused_n: 5,
            passed_hit_rate: null,
            refused_hit_rate: "0.60",
            passed_mean_forward_return: null,
            refused_mean_forward_return: "0.02",
            mean_diff: null,
            p_value: null,
            q_value: null,
          },
        ],
      }),
    );

    render(<AgentWorkflow />);
    fireEvent.click(await screen.findByRole("tab", { name: "Measure" }));

    expect(
      await screen.findByText(/No gated candidates yet — gate effectiveness not measurable/),
    ).toBeTruthy();
    // The row data itself still renders -- the notice supplements the table, it does not replace it.
    expect(screen.getByText("ta_gated")).toBeTruthy();
    expect(screen.getByText("12")).toBeTruthy(); // refused_n
  });
});

describe("the run form's screen-mode selector control", () => {
  it("shows a Selector select under screen mode, defaults to the promoted selector, and sends selector_id without candidate_pool/rank_key", async () => {
    configMock.mockResolvedValue(
      workflowConfig({ selector_ids: ["mom12_1_hysteresis", "trend_breakout"] }),
    );
    listRunsMock.mockResolvedValue({ runs: [] });
    bookMock.mockResolvedValue({ books: [] });
    studyMock.mockResolvedValue(workflowStudy({ arms: [], paired: [] }));
    startRunMock.mockResolvedValue(deskRun());

    render(<AgentWorkflow />);

    const universeSelect = (await screen.findByLabelText("Universe")) as HTMLSelectElement;
    fireEvent.change(universeSelect, { target: { value: "screen" } });

    const selectorSelect = (await screen.findByLabelText("Selector")) as HTMLSelectElement;
    expect(selectorSelect.value).toBe("mom12_1_hysteresis");
    // The raw pool/rank-key fields are ignored server-side once a named selector is active, so the
    // form hides them rather than showing controls that no longer do anything.
    expect(screen.queryByText("Candidate pool")).toBeNull();
    expect(screen.queryByText("Rank key")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Start run/ }));

    expect(startRunMock).toHaveBeenCalledTimes(1);
    const body = startRunMock.mock.calls[0]?.[0];
    expect(body).toMatchObject({ universe_mode: "screen", selector_id: "mom12_1_hysteresis" });
    expect(body).not.toHaveProperty("candidate_pool");
    expect(body).not.toHaveProperty("rank_key");
  });

  it("keeps sending candidate_pool/rank_key without selector_id when 'Raw pool + rank key' is chosen", async () => {
    configMock.mockResolvedValue(
      workflowConfig({
        selector_ids: ["mom12_1_hysteresis"],
        candidate_pools: ["sector-etf", "theme-etf"],
        rank_keys: ["mom12_1", "mom6", "trend"],
      }),
    );
    listRunsMock.mockResolvedValue({ runs: [] });
    bookMock.mockResolvedValue({ books: [] });
    studyMock.mockResolvedValue(workflowStudy({ arms: [], paired: [] }));
    startRunMock.mockResolvedValue(deskRun());

    render(<AgentWorkflow />);

    const universeSelect = (await screen.findByLabelText("Universe")) as HTMLSelectElement;
    fireEvent.change(universeSelect, { target: { value: "screen" } });

    const selectorSelect = (await screen.findByLabelText("Selector")) as HTMLSelectElement;
    const rawOption = screen.getByRole("option", {
      name: "Raw pool + rank key",
    }) as HTMLOptionElement;
    fireEvent.change(selectorSelect, { target: { value: rawOption.value } });

    expect(await screen.findByText("Candidate pool")).toBeTruthy();
    expect(screen.getByText("Rank key")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Start run/ }));

    expect(startRunMock).toHaveBeenCalledTimes(1);
    const body = startRunMock.mock.calls[0]?.[0];
    expect(body).toMatchObject({ candidate_pool: "sector-etf", rank_key: "mom12_1" });
    expect(body).not.toHaveProperty("selector_id");
  });

  it("sends screen_entry_rule and weekly_budget_usd when filled, and omits them when left empty", async () => {
    mockHappyPath();
    startRunMock.mockResolvedValue(deskRun());

    render(<AgentWorkflow />);

    // First submission: card mode, both fields left empty -- neither should appear on the body.
    fireEvent.click(await screen.findByRole("button", { name: /Start run/ }));
    expect(startRunMock).toHaveBeenCalledTimes(1);
    expect(startRunMock.mock.calls[0]?.[0]).not.toHaveProperty("weekly_budget_usd");
    expect(startRunMock.mock.calls[0]?.[0]).not.toHaveProperty("screen_entry_rule");

    // Fill the weekly budget (applies in both modes) and switch to screen mode with an entry rule.
    const weeklyBudgetInput = screen.getByLabelText(
      "Weekly research budget (USD)",
    ) as HTMLInputElement;
    fireEvent.change(weeklyBudgetInput, { target: { value: "50" } });

    const universeSelect = screen.getByLabelText("Universe") as HTMLSelectElement;
    fireEvent.change(universeSelect, { target: { value: "screen" } });

    const entryRuleInput = (await screen.findByPlaceholderText(
      "close > sma(200) and ema(20) > ema(50)",
    )) as HTMLInputElement;
    fireEvent.change(entryRuleInput, {
      target: { value: "close > sma(200) and ema(20) > ema(50)" },
    });

    fireEvent.click(screen.getByRole("button", { name: /Start run/ }));

    expect(startRunMock).toHaveBeenCalledTimes(2);
    const secondBody = startRunMock.mock.calls[1]?.[0];
    expect(secondBody).toMatchObject({
      weekly_budget_usd: "50",
      screen_entry_rule: "close > sma(200) and ema(20) > ema(50)",
    });
  });
});

describe("the universe filter toggle", () => {
  it("requests screen-filtered book, study and candidates once Screened is selected", async () => {
    mockHappyPath();

    render(<AgentWorkflow />);
    // The universe toggle lives in the Measure view -- switching tabs is render-only and does not
    // re-trigger any fetch, so the calls asserted below are still each panel's mount-time fetch.
    fireEvent.click(await screen.findByRole("tab", { name: "Measure" }));

    // The default ("Card") position omits `universe_source` entirely from every request -- the
    // page's very first fetch of each is byte-for-byte what it was before this toggle existed.
    await screen.findByRole("button", { name: "Screened" });
    expect(bookMock).toHaveBeenCalledWith(undefined);
    expect(studyMock).toHaveBeenCalledWith(undefined);
    // Candidates always sends the filter explicitly -- an omitted `universe_source` there is
    // "unfiltered" (card + screen mixed), not "card".
    expect(candidatesMock).toHaveBeenCalledWith({ universeSource: "card", limit: 100 });

    fireEvent.click(screen.getByRole("button", { name: "Screened" }));

    await waitFor(() => expect(bookMock).toHaveBeenLastCalledWith("screen"));
    expect(studyMock).toHaveBeenLastCalledWith("screen");
    expect(candidatesMock).toHaveBeenLastCalledWith({ universeSource: "screen", limit: 100 });
  });
});

describe("the candidates panel", () => {
  it("renders a skip reason and a cached verdict badge", async () => {
    configMock.mockResolvedValue(workflowConfig());
    listRunsMock.mockResolvedValue({ runs: [] });
    bookMock.mockResolvedValue({ books: [] });
    studyMock.mockResolvedValue(workflowStudy({ arms: [], paired: [] }));
    candidatesMock.mockResolvedValue(
      workflowCandidates({
        total: 2,
        observations: [
          candidateObservation({
            obs_id: "obs-1",
            symbol: "NVDA",
            gates: [
              {
                gate: "ta_gated",
                passed: true,
                detail: "Trend confirmed via a cached prior verdict.",
                was_explicit: true,
                verdict_source: "cached",
              },
            ],
          }),
          candidateObservation({
            obs_id: "obs-2",
            symbol: "AMD",
            state: "pending",
            forward_return_pct: null,
            alpha_return_pct: null,
            skip_reason: "vibe_refused",
            skip_detail: "Vibe gate refused: thesis lacked evidence.",
            gates: [],
          }),
        ],
        skip_reasons: { vibe_refused: 1 },
        verdict_sources: { fresh: 0, cached: 1, mixed: 0 },
        avoided_cost_usd: "4.20",
      }),
    );

    render(<AgentWorkflow />);
    fireEvent.click(await screen.findByRole("tab", { name: "Measure" }));

    expect(await screen.findByText("vibe_refused")).toBeTruthy();
    expect(screen.getByText(/\(cached\)/)).toBeTruthy();
  });

  it("shows an empty-state line when there are no observations", async () => {
    mockHappyPath();

    render(<AgentWorkflow />);
    fireEvent.click(await screen.findByRole("tab", { name: "Measure" }));

    expect(await screen.findByText("No candidate observations yet.")).toBeTruthy();
  });
});

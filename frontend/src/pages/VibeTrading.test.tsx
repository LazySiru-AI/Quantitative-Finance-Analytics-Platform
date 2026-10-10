/**
 * The Vibe Trading page's honesty rules, at render level.
 *
 * Mirrors `Competition.test.tsx`'s approach: `@/api/vibedesk` is stubbed at the module boundary
 * rather than `fetch`, and fixture factories mirror the wire contract (`docs/AGENT-DESK-CONTRACT.md`)
 * field for field so a drift between this file and `api/vibedesk.ts` shows up as a type error rather
 * than a silently-wrong fixture.
 *
 * What these tests pin:
 *  - the static explainer renders immediately, before any fetch resolves -- it is a constant, not
 *    fetched content;
 *  - selecting a preset loads that preset's own detail (agents/tasks/variables);
 *  - Start is disabled, with the backend's own reason shown, when the agent layer is unavailable;
 *  - a started run renders its stages grouped into layers;
 *  - a `blocked` stage and a `failed` stage render with different classes and different labels --
 *    collapsing the two would misreport what happened in the run;
 *  - polling `getRun` stops the moment the run reaches a terminal state, proven with fake timers by
 *    asserting no further calls happen once it has settled.
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AgentHealth,
  BudgetWire,
  DeskRun,
  DeskRunSummary,
  GroundingVerdict,
  PresetDetail,
  PresetSummary,
  StageRecord,
  StartSwarmRequest,
  VibeConfig,
} from "@/api/vibedesk";

const presetsMock = vi.fn<() => Promise<{ presets: PresetSummary[] }>>();
const presetMock = vi.fn<(name: string) => Promise<PresetDetail>>();
const startRunMock = vi.fn<(body: StartSwarmRequest) => Promise<DeskRun>>();
const listRunsMock = vi.fn<() => Promise<{ runs: DeskRunSummary[] }>>();
const getRunMock = vi.fn<(runId: string) => Promise<DeskRun>>();
const cancelRunMock = vi.fn<(runId: string) => Promise<DeskRun>>();
const agentHealthMock = vi.fn<() => Promise<AgentHealth>>();
const configMock = vi.fn<() => Promise<VibeConfig>>();

vi.mock("@/api/vibedesk", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/vibedesk")>();
  return {
    ...actual,
    vibeDeskApi: {
      config: () => configMock(),
      presets: () => presetsMock(),
      preset: (name: string) => presetMock(name),
      startRun: (body: StartSwarmRequest) => startRunMock(body),
      listRuns: () => listRunsMock(),
      getRun: (runId: string) => getRunMock(runId),
      cancelRun: (runId: string) => cancelRunMock(runId),
      agentHealth: () => agentHealthMock(),
    },
  };
});

const { default: VibeTrading } = await import("@/pages/VibeTrading");

// --- fixtures --------------------------------------------------------------------------------------

function presetSummary(overrides: Partial<PresetSummary> = {}): PresetSummary {
  return {
    name: "investment_committee",
    label: "Investment Committee",
    blurb: "A committee of role agents debates one thesis.",
    agent_count: 5,
    layer_count: 3,
    ...overrides,
  };
}

function presetDetail(overrides: Partial<PresetDetail> = {}): PresetDetail {
  return {
    ...presetSummary(),
    agents: [
      { id: "bull", label: "Bull", blurb: "Argues for the thesis." },
      { id: "bear", label: "Bear", blurb: "Argues against it." },
    ],
    tasks: [
      { id: "bull_case", agent_id: "bull", depends_on: [], layer: 0 },
      { id: "bear_case", agent_id: "bear", depends_on: [], layer: 0 },
      { id: "verdict", agent_id: "chair", depends_on: ["bull_case", "bear_case"], layer: 1 },
    ],
    // `required: false` so submitting the form in tests never trips native HTML5 constraint
    // validation on an empty required field, which is not what any of these tests are about.
    variables: [{ name: "thesis", label: "Thesis", required: false, default: "" }],
    ...overrides,
  };
}

function groundingVerdict(overrides: Partial<GroundingVerdict> = {}): GroundingVerdict {
  return { ok: true, issues: [], attempts: 1, degraded: false, checked_tokens: 100, ...overrides };
}

function stageRecord(overrides: Partial<StageRecord> = {}): StageRecord {
  return {
    stage_id: "bull_case",
    role: "bull",
    label: "Bull Case",
    seat: "",
    state: "succeeded",
    layer: 0,
    depends_on: [],
    started_at: "2026-08-30T00:00:00Z",
    completed_at: "2026-08-30T00:01:00Z",
    output_md: "# Bull case\nStrong buy.",
    summary: "Strong buy.",
    grounding: groundingVerdict(),
    call_ids: ["call-1"],
    cost_usd: "0.10",
    error: "",
    ...overrides,
  };
}

function budgetWire(overrides: Partial<BudgetWire> = {}): BudgetWire {
  return { cap_usd: "5.00", spent_usd: "0.10", calls: 1, ...overrides };
}

function deskRun(overrides: Partial<DeskRun> = {}): DeskRun {
  return {
    run_id: "run-1",
    kind: "vibedesk",
    state: "running",
    created_at: "2026-08-30T00:00:00Z",
    completed_at: null,
    config: { preset: "investment_committee" },
    stages: [stageRecord()],
    final_md: "",
    final_rating: "",
    degraded: false,
    error: "",
    budget: budgetWire(),
    ...overrides,
  };
}

function agentHealth(overrides: Partial<AgentHealth> = {}): AgentHealth {
  return {
    available: true,
    credential_source: "api_key",
    reason: "",
    model: "claude-opus-5",
    sdk_installed: true,
    ...overrides,
  };
}

/** `GET /config`'s body -- the same worker-model catalogue Trading Agents' own config exposes, per
 *  `app.vibedesk.service.build_config` reusing `AVAILABLE_MODELS` verbatim. Three entries here (not
 *  the full four-model catalogue) is deliberate: these tests must prove the page renders *whatever*
 *  `available_models` says, not one particular hardcoded list. */
function vibeConfig(overrides: Partial<VibeConfig> = {}): VibeConfig {
  return {
    default_model: "claude-haiku-4-5-20251001",
    available_models: [
      { id: "claude-haiku-4-5-20251001", label: "Haiku 4.5 (default, fastest, cheapest)" },
      { id: "claude-sonnet-5", label: "Sonnet 5" },
      { id: "claude-opus-5", label: "Opus 5 (most capable, slower)" },
    ],
    ...overrides,
  };
}

/** The default happy-path wiring most tests start from: one preset, its detail, no recent runs, an
 *  available agent layer, and the worker-model config. Individual tests override whichever mock they
 *  need a different answer from before rendering. */
function mockHappyPath() {
  presetsMock.mockResolvedValue({ presets: [presetSummary()] });
  presetMock.mockResolvedValue(presetDetail());
  listRunsMock.mockResolvedValue({ runs: [] });
  agentHealthMock.mockResolvedValue(agentHealth());
  configMock.mockResolvedValue(vibeConfig());
}

beforeEach(() => {
  presetsMock.mockReset();
  presetMock.mockReset();
  startRunMock.mockReset();
  listRunsMock.mockReset();
  getRunMock.mockReset();
  cancelRunMock.mockReset();
  agentHealthMock.mockReset();
  configMock.mockReset();
});

// --- tests -------------------------------------------------------------------------------------------

describe("the static explainer", () => {
  it("renders immediately, before any fetch resolves", () => {
    // Every mock is left pending (never resolved) -- if the explainer depended on a fetch, none of
    // its text would appear yet.
    presetsMock.mockReturnValue(new Promise(() => {}));
    presetMock.mockReturnValue(new Promise(() => {}));
    listRunsMock.mockReturnValue(new Promise(() => {}));
    agentHealthMock.mockReturnValue(new Promise(() => {}));
    configMock.mockReturnValue(new Promise(() => {}));

    render(<VibeTrading />);

    expect(
      screen.getByText(/committee of role agents, defined as data, not code/),
    ).toBeTruthy();
    expect(screen.getByText(/runs in parallel/)).toBeTruthy();
    expect(screen.getByText(/never the full output text/)).toBeTruthy();
    expect(screen.getByText(/injected into every agent's prompt as ground truth/)).toBeTruthy();
    expect(
      screen.getByText(/marked blocked, never quietly completed on missing input/),
    ).toBeTruthy();
  });
});

describe("preset selection", () => {
  it("loads the selected preset's own agent/task/variable detail", async () => {
    presetsMock.mockResolvedValue({
      presets: [presetSummary(), presetSummary({ name: "quant_desk", label: "Quant Desk" })],
    });
    presetMock.mockImplementation((name: string) =>
      Promise.resolve(
        presetDetail({
          name,
          label: name === "quant_desk" ? "Quant Desk" : "Investment Committee",
        }),
      ),
    );
    listRunsMock.mockResolvedValue({ runs: [] });
    agentHealthMock.mockResolvedValue(agentHealth());
    configMock.mockResolvedValue(vibeConfig());

    render(<VibeTrading />);

    // The first preset loads its own detail on mount (it is selected by default). Await the
    // detail-dependent field before asserting the detail fetch fired: `preset()` resolves a
    // microtask later than the picker label, so asserting the mock immediately after `findByText`
    // races the async chain and flaked under load once the config fetch was added to mount.
    await screen.findByText("Investment Committee");
    expect(await screen.findByLabelText(/Thesis/)).toBeTruthy();
    expect(presetMock).toHaveBeenCalledWith("investment_committee");

    // Selecting the second preset loads a fresh detail for it.
    fireEvent.click(screen.getByText("Quant Desk"));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(presetMock).toHaveBeenCalledWith("quant_desk");
  });
});

describe("the Live opt-in", () => {
  it("checking Live puts live: true in the posted startRun body", async () => {
    mockHappyPath();
    startRunMock.mockResolvedValue(deskRun());

    render(<VibeTrading />);

    await screen.findByText("Investment Committee");
    const liveCheckbox = (await screen.findByRole("checkbox", {
      name: "Live (today's quote)",
    })) as HTMLInputElement;
    fireEvent.click(liveCheckbox);
    expect(liveCheckbox.checked).toBe(true);
    expect(screen.getByText("Uses today's live quote and 5-minute bars.")).toBeTruthy();

    fireEvent.click(await screen.findByRole("button", { name: /Start run/ }));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(startRunMock).toHaveBeenCalledTimes(1);
    expect(startRunMock.mock.calls[0]?.[0]?.live).toBe(true);
  });

  it("omits live from the body when the checkbox is left unchecked", async () => {
    mockHappyPath();
    startRunMock.mockResolvedValue(deskRun());

    render(<VibeTrading />);

    await screen.findByText("Investment Committee");
    fireEvent.click(await screen.findByRole("button", { name: /Start run/ }));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(startRunMock).toHaveBeenCalledTimes(1);
    expect(startRunMock.mock.calls[0]?.[0]?.live).toBeUndefined();
  });
});

describe("agent availability", () => {
  it("disables Start and shows the backend's own reason when the agent layer is unavailable", async () => {
    presetsMock.mockResolvedValue({ presets: [presetSummary()] });
    presetMock.mockResolvedValue(presetDetail());
    listRunsMock.mockResolvedValue({ runs: [] });
    agentHealthMock.mockResolvedValue(
      agentHealth({ available: false, reason: "no ANTHROPIC_API_KEY set" }),
    );
    configMock.mockResolvedValue(vibeConfig());

    render(<VibeTrading />);

    const startButton = (await screen.findByRole("button", {
      name: /Start run/,
    })) as HTMLButtonElement;
    await screen.findByText(/no ANTHROPIC_API_KEY set/);
    expect(startButton.disabled).toBe(true);
  });

  it("leaves Start enabled once the agent layer reports available", async () => {
    mockHappyPath();

    render(<VibeTrading />);

    const startButton = (await screen.findByRole("button", {
      name: /Start run/,
    })) as HTMLButtonElement;
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(startButton.disabled).toBe(false);
  });
});

describe("a running desk's DAG board", () => {
  it("groups stages by layer", async () => {
    mockHappyPath();
    startRunMock.mockResolvedValue(
      deskRun({
        state: "succeeded",
        stages: [
          stageRecord({ stage_id: "bull_case", label: "Bull Case", layer: 0 }),
          stageRecord({ stage_id: "bear_case", label: "Bear Case", layer: 0 }),
          stageRecord({
            stage_id: "verdict",
            label: "Verdict",
            layer: 1,
            depends_on: ["bull_case", "bear_case"],
          }),
        ],
      }),
    );

    render(<VibeTrading />);
    await screen.findByText("Investment Committee");
    // Await the button rather than grabbing it synchronously: the run form is gated on the
    // preset-detail fetch, which resolves one async hop *after* the preset-list text this test
    // first waits on. A synchronous getByRole here is a race the test can lose.
    fireEvent.click(await screen.findByRole("button", { name: /Start run/ }));

    expect(await screen.findByText("Bull Case")).toBeTruthy();
    expect(screen.getByText("Bear Case")).toBeTruthy();
    expect(screen.getByText("Verdict")).toBeTruthy();
    expect(screen.getByText("Layer 0")).toBeTruthy();
    expect(screen.getByText("Layer 1")).toBeTruthy();
  });

  it("renders a blocked stage distinctly from a failed one", async () => {
    mockHappyPath();
    startRunMock.mockResolvedValue(
      deskRun({
        state: "failed",
        stages: [
          stageRecord({
            stage_id: "market",
            label: "Market Analyst",
            layer: 0,
            state: "failed",
            error: "provider timeout",
          }),
          stageRecord({
            stage_id: "verdict",
            label: "Verdict",
            layer: 1,
            state: "blocked",
            depends_on: ["market"],
            output_md: "",
            summary: "",
            grounding: null,
          }),
        ],
      }),
    );

    render(<VibeTrading />);
    await screen.findByText("Investment Committee");
    // Await the button rather than grabbing it synchronously: the run form is gated on the
    // preset-detail fetch, which resolves one async hop *after* the preset-list text this test
    // first waits on. A synchronous getByRole here is a race the test can lose.
    fireEvent.click(await screen.findByRole("button", { name: /Start run/ }));

    const failedLabel = await screen.findByText("Market Analyst");
    const blockedLabel = await screen.findByText("Verdict");
    const failedCard = failedLabel.closest("button");
    const blockedCard = blockedLabel.closest("button");

    expect(failedCard?.className).toContain("vibe-stage-failed");
    expect(failedCard?.className).not.toContain("vibe-stage-blocked");
    expect(blockedCard?.className).toContain("vibe-stage-blocked");
    expect(blockedCard?.className).not.toContain("vibe-stage-failed");

    // The state labels themselves must also differ -- collapsing the two states would collapse
    // this text too.
    expect(screen.getByText("Failed")).toBeTruthy();
    expect(screen.getByText("Blocked")).toBeTruthy();
  });
});

describe("worker model picker", () => {
  it("renders options from the fetched config, with the backend's default preselected", async () => {
    mockHappyPath();

    render(<VibeTrading />);
    await screen.findByText("Investment Committee");

    const select = (await screen.findByLabelText(/Worker model/)) as HTMLSelectElement;
    // Every model the config named renders as an option, by its own backend-supplied label -- not a
    // hardcoded local list.
    expect(screen.getByRole("option", { name: "Haiku 4.5 (default, fastest, cheapest)" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Sonnet 5" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Opus 5 (most capable, slower)" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Custom version…" })).toBeTruthy();
    // Preselected to the config's own `default_model`, once the fetch resolves.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(select.value).toBe("claude-haiku-4-5-20251001");
  });

  it("falls back to just the Custom version… option when the config fetch fails", async () => {
    presetsMock.mockResolvedValue({ presets: [presetSummary()] });
    presetMock.mockResolvedValue(presetDetail());
    listRunsMock.mockResolvedValue({ runs: [] });
    agentHealthMock.mockResolvedValue(agentHealth());
    configMock.mockRejectedValue(new Error("network error"));

    render(<VibeTrading />);
    await screen.findByText("Investment Committee");

    const select = (await screen.findByLabelText(/Worker model/)) as HTMLSelectElement;
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    // The form still works: no model options crashed the page, and the only option left is Custom.
    expect(select.querySelectorAll("option")).toHaveLength(1);
    expect(screen.getByRole("option", { name: "Custom version…" })).toBeTruthy();
  });
});

describe("run polling", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls getRun every 2000ms while the run is active and stops once it is terminal", async () => {
    mockHappyPath();
    startRunMock.mockResolvedValue(deskRun({ state: "running" }));

    render(<VibeTrading />);
    await screen.findByText("Investment Committee");

    // Find the button on real timers first -- the run form is gated on the preset-detail fetch,
    // which resolves an async hop after the preset-list text above, and an async findBy* deadlocks
    // once fake timers are installed. Then switch to fake timers *before* clicking, so the polling
    // interval the component sets after startRun resolves is a fake one this test can advance.
    const startButton = await screen.findByRole("button", { name: /Start run/ });
    vi.useFakeTimers();
    fireEvent.click(startButton);

    // Flush the `startRun()` promise and the state update it seeds -- plain microtask ticks, which
    // fake timers do not gate (only setTimeout/setInterval are faked).
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(getRunMock).not.toHaveBeenCalled();

    // First poll tick: ~2000ms later, still running.
    getRunMock.mockResolvedValue(deskRun({ state: "running" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(getRunMock).toHaveBeenCalledTimes(1);
    expect(getRunMock).toHaveBeenCalledWith("run-1");

    // Second poll tick: the run reaches a terminal state.
    getRunMock.mockResolvedValue(deskRun({ state: "succeeded" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(getRunMock).toHaveBeenCalledTimes(2);

    // Further wall-clock time passes, but the interval was cleared on the terminal state -- no more
    // calls to getRun().
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000 * 5);
    });
    expect(getRunMock).toHaveBeenCalledTimes(2);
  });
});

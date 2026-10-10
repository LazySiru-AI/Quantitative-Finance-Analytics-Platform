/**
 * `LoopPanel`'s honesty rules, at render level -- mirrors `NextRoundPanel.test.tsx`'s approach: this
 * component takes its data as props (the parent owns the fetch and the poll), so there is no API
 * module to stub here, only fixtures that mirror `@/api/evolution`'s wire types field for field.
 *
 * What these tests pin, matching the task's definition of done:
 *  - idle (no status) renders "Start the loop" and clicking it calls `onStart`;
 *  - a running loop renders "Stop the loop" and clicking it calls `onStop`;
 *  - `"stopping"` disables the toggle and shows "Stopping…";
 *  - the best standing renders both the selection and holdout medians, with the holdout labelled as
 *    never used for selection;
 *  - a `null` status on a `"loaded"` phase renders the idle state, not an error;
 *  - findings render one row per finding with the kind as a badge;
 *  - the start form: the agents-per-generation dropdown defaults to 10 and changing it, typing a goal,
 *    and typing comma-separated tickers all flow into the `Partial<LoopConfig>` handed to `onStart`;
 *  - the form is hidden and the started config shown read-only while the loop is running;
 *  - a 422 rejection message is surfaced;
 *  - a goal holding a config-shaped directive (`purposes=['trading', 'roth', 'saving']`) warns beside
 *    the field, names the illegal value, and **still starts the loop with the goal verbatim** -- a
 *    warning, never a gate. The detection itself is unit-tested in `goalDirectives.test.ts`; what is
 *    pinned here is that it reaches the reader and that it changes nothing about what gets sent.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  DEFAULT_LOOP_FORM_DRAFT,
  type Finding,
  type GenerationOutcome,
  type LoopConfig,
  type LoopFormDraft,
  type LoopStatus,
  type PromotionRecord,
  type Standing,
} from "@/api/evolution";
import LoopPanel, { type LoopPanelProps } from "@/pages/competition/LoopPanel";

// --- fixtures --------------------------------------------------------------------------------------

function standing(overrides: Partial<Standing> = {}): Standing {
  return {
    genome_id: "g-042",
    agent_id: "c07-chop",
    display_name: "Chop Specialist",
    rank: 1,
    eligible: true,
    windows_run: 6,
    median_excess: "0.0741",
    worst_excess: "-0.0120",
    hit_rate: 0.83,
    total_trades: 214,
    holdout_median_excess: "0.0312",
    q_value: 0.02,
    ...overrides,
  };
}

function promotion(overrides: Partial<PromotionRecord> = {}): PromotionRecord {
  return {
    genome_id: "g-042",
    agent_id: "c07-chop",
    purpose: "trading",
    promoted_at: "2026-08-20T00:00:00Z",
    generations: [3, 4, 5],
    window_sets: [["gfc", "covid"]],
    median_excess: "0.0741",
    holdout_median_excess: "0.0312",
    q_value: 0.02,
    library_path: "library/tier-1/c07-chop.json",
    seated: true,
    reason: "Cleared the promotion margin for three consecutive generations.",
    ...overrides,
  };
}

function finding(overrides: Partial<Finding> = {}): Finding {
  return {
    kind: "winner",
    summary: "c07-chop cleared the promotion margin on the ladder windows.",
    evidence: {},
    ...overrides,
  };
}

function generationOutcome(overrides: Partial<GenerationOutcome> = {}): GenerationOutcome {
  return {
    generation: 5,
    round_id: "loop-r5-g5",
    purpose: "trading",
    job_id: "job-123",
    status: "succeeded",
    started_at: "2026-08-20T00:00:00Z",
    finished_at: "2026-08-20T01:00:00Z",
    windows: ["gfc", "covid"],
    holdout_windows: ["banks-2023"],
    genome_ids: ["g-042"],
    standings: [standing()],
    findings: [finding()],
    promoted: ["g-042"],
    error: null,
    ...overrides,
  };
}

function loopConfig(overrides: Partial<LoopConfig> = {}): LoopConfig {
  return {
    purposes: ["trading"],
    population: 12,
    max_workers: 4,
    elite_count: 3,
    windows: ["gfc", "covid"],
    holdout_windows: ["banks-2023"],
    max_generations: null,
    rank_by: "median",
    promotion_margin_pp: "0.0200",
    promotion_consecutive: 3,
    promotion_max_shared_windows: null,
    seat_on_paper_desk: true,
    use_news: false,
    news_fraction: 0,
    seed: 7,
    cooldown_seconds: 60,
    goal: "",
    focus_symbols: [],
    avoid_symbols: [],
    ...overrides,
  };
}

function loopStatus(overrides: Partial<LoopStatus> = {}): LoopStatus {
  return {
    loop_id: "loop-1",
    state: "running",
    phase: "scoring",
    config: loopConfig(),
    generation: 5,
    completed_generations: 4,
    candidates_tested: 48,
    started_at: "2026-08-19T00:00:00Z",
    updated_at: "2026-08-20T01:00:00Z",
    stopped_at: null,
    current_round_id: "loop-r5-g5",
    current_job_id: "job-123",
    current_purpose: "trading",
    best: standing(),
    promotions: [promotion()],
    history: [generationOutcome()],
    log: ["[g5] scoring standings…"],
    error: null,
    ...overrides,
  };
}

function noop() {
  // Deliberately does nothing -- used as the callback prop this test isn't exercising.
}

/** Renders `LoopPanel` with sensible defaults for every prop, overridable per test -- keeps each test
 * focused on the one or two props it actually cares about instead of repeating the full prop list. */
function renderPanel(overrides: Partial<LoopPanelProps> = {}) {
  const defaults: LoopPanelProps = {
    status: null,
    phase: "loaded",
    message: null,
    busy: false,
    onStart: noop,
    onStop: noop,
    draft: DEFAULT_LOOP_FORM_DRAFT,
    onDraftChange: noop,
  };
  return render(<LoopPanel {...defaults} {...overrides} />);
}

// --- tests ------------------------------------------------------------------------------------------

describe("LoopPanel", () => {
  it("renders 'Start the loop' when idle and calls onStart on click", () => {
    const onStart = vi.fn();
    renderPanel({ status: null, onStart });

    const button = screen.getByRole("button", { name: "Start the loop" }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);

    fireEvent.click(button);
    expect(onStart).toHaveBeenCalledTimes(1);
  });

  it("renders 'Stop the loop' when running and calls onStop on click", () => {
    const onStop = vi.fn();
    renderPanel({ status: loopStatus({ state: "running" }), onStop });

    const button = screen.getByRole("button", { name: "Stop the loop" }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);

    fireEvent.click(button);
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it("disables the toggle and shows 'Stopping…' while state is 'stopping'", () => {
    renderPanel({ status: loopStatus({ state: "stopping" }) });

    const button = screen.getByRole("button", { name: "Stopping…" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("disables the toggle while busy, regardless of state", () => {
    renderPanel({ status: null, busy: true });

    const button = screen.getByRole("button", { name: "Start the loop" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("renders both the selection and holdout medians for the best standing, with the holdout labelled as never used for selection", () => {
    renderPanel({
      status: loopStatus({ best: standing({ median_excess: "0.0741", holdout_median_excess: "0.0312" }) }),
    });

    expect(screen.getByText("+7.41%")).toBeTruthy();
    expect(screen.getByText("+3.12%")).toBeTruthy();
    expect(screen.getByText(/never used for selection/i)).toBeTruthy();
  });

  it("renders a null status on phase 'loaded' as the idle state, not an error", () => {
    const { container } = renderPanel({ status: null, phase: "loaded" });

    expect(screen.getByText(/Never started/i)).toBeTruthy();
    expect(container.querySelector(".comp-loop-empty")).toBeTruthy();
    expect(screen.queryByText(/could not load/i)).toBeNull();
  });

  it("renders the actual error message on phase 'error', not a generic string", () => {
    renderPanel({ status: null, phase: "error", message: "loop endpoint returned 503" });

    expect(screen.getByText("loop endpoint returned 503")).toBeTruthy();
  });

  it("renders a loading placeholder on phase 'loading'", () => {
    renderPanel({ status: null, phase: "loading" });

    expect(screen.getByText(/loading the evolution loop/i)).toBeTruthy();
  });

  it("renders one row per finding, each with its kind as a badge", () => {
    const findings: Finding[] = [
      finding({ kind: "winner", summary: "c07-chop cleared the margin." }),
      finding({ kind: "regime", summary: "The ladder windows skewed bullish this generation." }),
      finding({ kind: "holdout", summary: "Holdout median diverged from the selection median for g-041." }),
    ];
    renderPanel({ status: loopStatus({ history: [generationOutcome({ generation: 7, findings })] }) });

    expect(screen.getByText("c07-chop cleared the margin.")).toBeTruthy();
    expect(screen.getByText("The ladder windows skewed bullish this generation.")).toBeTruthy();
    expect(
      screen.getByText("Holdout median diverged from the selection median for g-041."),
    ).toBeTruthy();
    expect(screen.getByText("Winner")).toBeTruthy();
    expect(screen.getByText("Regime")).toBeTruthy();
    expect(screen.getByText("Holdout")).toBeTruthy();
  });

  it("takes the finding list from the generation with the highest generation number, not history order", () => {
    renderPanel({
      status: loopStatus({
        history: [
          generationOutcome({
            generation: 9,
            findings: [finding({ kind: "winner", summary: "Latest generation's finding." })],
          }),
          generationOutcome({
            generation: 3,
            findings: [finding({ kind: "failure", summary: "An earlier generation's finding." })],
          }),
        ],
      }),
    });

    expect(screen.getByText("Latest generation's finding.")).toBeTruthy();
    expect(screen.queryByText("An earlier generation's finding.")).toBeNull();
  });

  it("renders the promotions list with seated state and reason", () => {
    renderPanel({
      status: loopStatus({
        promotions: [
          promotion({ genome_id: "g-042", agent_id: "c07-chop", seated: true, reason: "Cleared the margin." }),
          promotion({
            genome_id: "g-051",
            agent_id: "c09-drift",
            seated: false,
            reason: "Cleared the margin but no seat was free.",
          }),
        ],
      }),
    });

    expect(screen.getByText("Seated on paper desk")).toBeTruthy();
    expect(screen.getByText("Not seated")).toBeTruthy();
    expect(screen.getByText("Cleared the margin.")).toBeTruthy();
    expect(screen.getByText("Cleared the margin but no seat was free.")).toBeTruthy();
  });

  it("renders the empty states for promotions and findings when there are none", () => {
    renderPanel({ status: loopStatus({ promotions: [], history: [] }) });

    expect(screen.getByText(/nothing has been promoted yet/i)).toBeTruthy();
    expect(screen.getByText(/no findings recorded/i)).toBeTruthy();
  });

  // --- the start form -----------------------------------------------------------------------------

  it("defaults the agents-per-generation dropdown to 10, and changing it flows into onDraftChange", () => {
    const onDraftChange = vi.fn();
    renderPanel({ status: null, draft: DEFAULT_LOOP_FORM_DRAFT, onDraftChange });

    const select = screen.getByLabelText(/agents per generation/i) as HTMLSelectElement;
    expect(select.value).toBe("10");

    fireEvent.change(select, { target: { value: "20" } });
    expect(onDraftChange).toHaveBeenCalledWith({ population: 20 });
  });

  it("assembles the current draft (including a changed population) into the config passed to onStart", () => {
    const onStart = vi.fn();
    const draft: LoopFormDraft = { ...DEFAULT_LOOP_FORM_DRAFT, population: 20 };
    renderPanel({ status: null, draft, onStart });

    fireEvent.click(screen.getByRole("button", { name: "Start the loop" }));

    expect(onStart).toHaveBeenCalledTimes(1);
    expect(onStart).toHaveBeenCalledWith(expect.objectContaining({ population: 20, max_workers: 4 }));
  });

  it("passes a typed goal through to onStart's config", () => {
    const onStart = vi.fn();
    const draft: LoopFormDraft = {
      ...DEFAULT_LOOP_FORM_DRAFT,
      goal: "Does a small-cap semiconductor tilt survive a drawdown better than a pure trend book?",
    };
    renderPanel({ status: null, draft, onStart });

    fireEvent.click(screen.getByRole("button", { name: "Start the loop" }));

    expect(onStart).toHaveBeenCalledWith(
      expect.objectContaining({
        goal: "Does a small-cap semiconductor tilt survive a drawdown better than a pure trend book?",
      }),
    );
  });

  it("warns beside the goal field when the goal holds a directive the form does not act on, naming the illegal value", () => {
    const draft: LoopFormDraft = {
      ...DEFAULT_LOOP_FORM_DRAFT,
      goal: "add saving as one of purpose as well\npurposes=['trading', 'roth', 'saving']",
    };
    renderPanel({ status: null, draft });

    const warning = screen.getByRole("status");
    expect(warning.textContent).toContain("does not steer the search");
    expect(warning.textContent).toContain('"Books to breed for"');
    // The illegal value is named, with the legal set beside it -- gen1873's second, unsurfaced fault.
    expect(warning.textContent).toContain('"saving" is not a purpose');
    expect(warning.textContent).toContain("savings, trading, roth");
  });

  it("does not warn on a goal that reads like the question the field is for", () => {
    const draft: LoopFormDraft = {
      ...DEFAULT_LOOP_FORM_DRAFT,
      goal: "does a small semiconductor tilt survive a drawdown better than a pure trend book?",
    };
    renderPanel({ status: null, draft });

    expect(screen.queryByRole("status")).toBeNull();
  });

  it("warns but never blocks: the toggle still starts the loop, with the goal passed through verbatim", () => {
    const onStart = vi.fn();
    const goal = "purposes=['trading', 'roth', 'saving']";
    renderPanel({ status: null, draft: { ...DEFAULT_LOOP_FORM_DRAFT, goal }, onStart });

    const toggle = screen.getByRole("button", { name: "Start the loop" }) as HTMLButtonElement;
    expect(screen.getByRole("status").textContent).toContain("does not steer the search");
    expect(toggle.disabled).toBe(false);
    fireEvent.click(toggle);

    // The warning changes nothing about what is sent: the goal is recorded exactly as typed, and no
    // part of it is parsed into `purposes` -- see `LoopPanel.tsx`'s docstring on why that must stay so.
    expect(onStart).toHaveBeenCalledWith(expect.objectContaining({ goal }));
    // The config now carries `purposes` -- it is a real control. What matters for *this* test is
    // unchanged: the goal text is passed through verbatim and the directive in it changed nothing,
    // so the books sent are still the draft's own defaults rather than the three the goal names.
    expect(onStart.mock.calls[0]?.[0]).toMatchObject({ purposes: ["trading", "roth"] });
  });

  it("drops the warning once the directive's values are in the field that actually carries them", () => {
    const draft: LoopFormDraft = {
      ...DEFAULT_LOOP_FORM_DRAFT,
      goal: "focus=NVDA,AMD",
      focusSymbolsInput: "NVDA, AMD",
    };
    renderPanel({ status: null, draft });

    expect(screen.queryByRole("status")).toBeNull();
  });

  it("turns comma-separated ticker input into an uppercased, trimmed array, and an empty field into []", () => {
    const onStart = vi.fn();
    const draft: LoopFormDraft = {
      ...DEFAULT_LOOP_FORM_DRAFT,
      focusSymbolsInput: " nvda, amd ,nvda ",
      avoidSymbolsInput: "   ",
    };
    renderPanel({ status: null, draft, onStart });

    fireEvent.click(screen.getByRole("button", { name: "Start the loop" }));

    expect(onStart).toHaveBeenCalledWith(
      expect.objectContaining({
        focus_symbols: ["NVDA", "AMD", "NVDA"],
        avoid_symbols: [],
      }),
    );
  });

  it("updates the goal and ticker fields via onDraftChange as the reader types", () => {
    const onDraftChange = vi.fn();
    renderPanel({ status: null, draft: DEFAULT_LOOP_FORM_DRAFT, onDraftChange });

    fireEvent.change(screen.getByLabelText(/^goal$/i), { target: { value: "New goal text" } });
    expect(onDraftChange).toHaveBeenCalledWith({ goal: "New goal text" });

    fireEvent.change(screen.getByLabelText(/must include tickers/i), { target: { value: "nvda, amd" } });
    expect(onDraftChange).toHaveBeenCalledWith({ focusSymbolsInput: "nvda, amd" });

    fireEvent.change(screen.getByLabelText(/must avoid tickers/i), { target: { value: "tsla" } });
    expect(onDraftChange).toHaveBeenCalledWith({ avoidSymbolsInput: "tsla" });
  });

  it("hides the start form and shows the started config read-only while the loop is running", () => {
    renderPanel({
      status: loopStatus({
        state: "running",
        config: loopConfig({ population: 16, max_workers: 6, focus_symbols: ["NVDA"], avoid_symbols: ["TSLA"] }),
      }),
    });

    // The form's own controls are gone.
    expect(screen.queryByLabelText(/agents per generation/i)).toBeNull();
    expect(screen.queryByLabelText(/^goal$/i)).toBeNull();

    // The started config renders read-only instead.
    //
    // Each value is asserted against its own label rather than by searching the whole document for a
    // bare number. `max_workers: 6` and the fixture standing's `windows_run: 6` both render "6", so
    // `getByText("6")` matched two elements and threw -- and had the fixture happened to avoid that
    // collision, the assertion would have passed while proving only that the digit appeared
    // *somewhere* on the panel, which is not the claim.
    const heading = screen.getByText(/this run was started with/i);
    const block = heading.parentElement as HTMLElement;
    const valueFor = (label: string) =>
      within(block)
        .getByText(label)
        .parentElement?.querySelector(".value")?.textContent;

    expect(valueFor("Agents per generation")).toBe("16");
    expect(valueFor("Parallel workers")).toBe("6");
    expect(valueFor("Must include")).toBe("NVDA");
    expect(valueFor("Must avoid")).toBe("TSLA");
  });

  it("renders the run's non-empty goal beside the findings, marked as stated intent rather than a finding", () => {
    renderPanel({
      status: loopStatus({
        config: loopConfig({ goal: "Find out whether the chop specialist survives a rate shock." }),
      }),
    });

    expect(
      screen.getByText("Find out whether the chop specialist survives a rate shock."),
    ).toBeTruthy();
    expect(screen.getByText(/stated goal for this run/i)).toBeTruthy();
    expect(screen.getByText(/not a finding/i)).toBeTruthy();
  });

  it("renders nothing goal-related when the run's goal is empty", () => {
    renderPanel({ status: loopStatus({ config: loopConfig({ goal: "" }) }) });

    expect(screen.queryByText(/stated goal for this run/i)).toBeNull();
  });

  it("surfaces a 422 rejection message from a failed start attempt", () => {
    renderPanel({
      status: null,
      message: "AAPL cannot be named in both focus_symbols and avoid_symbols.",
    });

    expect(
      screen.getByText("AAPL cannot be named in both focus_symbols and avoid_symbols."),
    ).toBeTruthy();
  });

  // --- "Books to breed for" -----------------------------------------------------------------------
  //
  // The control exists because `buildLoopConfigFromDraft` did not carry `purposes` at all, so every
  // run this page ever started took the backend default and `savings` was unreachable from the UI --
  // `docs/research/loop/01-what-the-search-found.md` point 6, measured as zero savings coverage across
  // 231 generations.

  it("ticks the two default books and offers savings as a third", () => {
    renderPanel({ status: null, draft: DEFAULT_LOOP_FORM_DRAFT });

    expect((screen.getByLabelText("Trading") as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText("Roth IRA") as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText("Savings") as HTMLInputElement).checked).toBe(false);
  });

  it("ticking savings adds it to the draft in PURPOSE_ORDER, not in click order", () => {
    const onDraftChange = vi.fn();
    renderPanel({ status: null, draft: DEFAULT_LOOP_FORM_DRAFT, onDraftChange });

    fireEvent.click(screen.getByLabelText("Savings"));

    expect(onDraftChange).toHaveBeenCalledWith({ purposes: ["trading", "roth", "savings"] });
  });

  it("unticking a book removes it from the draft", () => {
    const onDraftChange = vi.fn();
    renderPanel({ status: null, draft: DEFAULT_LOOP_FORM_DRAFT, onDraftChange });

    fireEvent.click(screen.getByLabelText("Roth IRA"));

    expect(onDraftChange).toHaveBeenCalledWith({ purposes: ["trading"] });
  });

  it("disables the last remaining book so the draft can never reach zero", () => {
    // `LoopConfig.purposes` is `min_length=1` on the backend because an empty tuple builds zero lanes
    // and the supervisor dies on a modulo by zero. The form says so before the request is made.
    const draft: LoopFormDraft = { ...DEFAULT_LOOP_FORM_DRAFT, purposes: ["savings"] };
    const onDraftChange = vi.fn();
    renderPanel({ status: null, draft, onDraftChange });

    const savings = screen.getByLabelText("Savings") as HTMLInputElement;
    expect(savings.checked).toBe(true);
    expect(savings.disabled).toBe(true);
    fireEvent.click(savings);
    expect(onDraftChange).not.toHaveBeenCalled();
  });

  it("sends the selected books through to onStart's config", () => {
    const onStart = vi.fn();
    const draft: LoopFormDraft = {
      ...DEFAULT_LOOP_FORM_DRAFT,
      purposes: ["savings", "trading", "roth"],
    };
    renderPanel({ status: null, draft, onStart });

    fireEvent.click(screen.getByRole("button", { name: "Start the loop" }));

    expect(onStart).toHaveBeenCalledWith(
      expect.objectContaining({ purposes: ["trading", "roth", "savings"] }),
    );
  });

  it("stops warning about a purposes directive the checkboxes already satisfy", () => {
    // The same rule the ticker fields follow: a goal naming exactly what the control is already set to
    // is redundant, not misleading, and warning about it would train the reader to ignore the callout.
    const draft: LoopFormDraft = {
      ...DEFAULT_LOOP_FORM_DRAFT,
      purposes: ["trading", "roth", "savings"],
      goal: "purposes=[trading, roth, savings]",
    };
    renderPanel({ status: null, draft });

    expect(screen.queryByText(/names a setting the goal field cannot change/i)).toBeNull();
  });

  it("still warns when the goal asks for a book the checkboxes do not have ticked", () => {
    const draft: LoopFormDraft = {
      ...DEFAULT_LOOP_FORM_DRAFT,
      goal: "purposes=['trading', 'roth', 'saving']",
    };
    renderPanel({ status: null, draft });

    expect(screen.getByText(/names a setting the goal field cannot change/i)).toBeTruthy();
    // The control exists now, so the wording points at it rather than saying the form has no field.
    expect(screen.getByText(/"Books to breed for"/)).toBeTruthy();
    // And `saving` is still not a purpose -- the legality half of the warning is unchanged.
    expect(screen.getByText(/is not a purpose/i)).toBeTruthy();
  });
});

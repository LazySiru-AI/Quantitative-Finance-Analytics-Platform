/**
 * `GenerationsPanel`'s honesty rules, at render level -- mirrors `Competition.test.tsx`'s approach:
 * `@/api/evolution` is stubbed at the module boundary (this component fetches its own data, unlike
 * `LoopPanel`), and fixture factories mirror the wire contract field for field so a drift between this
 * file and `api/evolution.ts` shows up as a type error rather than a silently-wrong fixture.
 *
 * What these tests pin, matching the task's definition of done:
 *  - rows render newest-first, ordinary generations and collapsed failure streaks interleaved by
 *    generation number;
 *  - a failure streak of 400 renders as ONE collapsed row naming the error, never 400 rows;
 *  - a generation with `field.median_excess === null` renders "no field", never a zero;
 *  - expanding a generation fetches its detail and renders every standing, including ineligible ones;
 *  - a review renders its verdict, direction, and amendments;
 *  - a missing review renders the explicit "no model reviewed this" state, not an empty box;
 *  - the purpose filter changes which generations feed the sparkline;
 *  - fraction-based columns (`median_excess`) and percentage-point columns (`holdout_gap_pp`) format
 *    differently -- the obvious 100x bug this contract calls out explicitly;
 *  - an API error renders a readable message rather than a blank panel.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  FailureStreak,
  GenerationDetailResponse,
  GenerationOutcome,
  GenerationReview,
  GenerationSummary,
  GenerationsListResponse,
  Purpose,
  StatSummary,
  Standing,
} from "@/api/evolution";

// --- module mock -------------------------------------------------------------------------------------

const generationsMock = vi.fn<
  (params: {
    limit?: number;
    offset?: number;
    purpose?: Purpose;
    status?: "succeeded" | "failed" | "cancelled";
    succeeded_only?: boolean;
  }) => Promise<GenerationsListResponse>
>();
const generationDetailMock = vi.fn<(generation: number) => Promise<GenerationDetailResponse>>();
const failureStreaksMock = vi.fn<() => Promise<{ streaks: FailureStreak[] }>>();

vi.mock("@/api/evolution", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/evolution")>();
  return {
    ...actual,
    evolutionApi: {
      ...actual.evolutionApi,
      generations: (params: Parameters<typeof generationsMock>[0]) => generationsMock(params),
      generationDetail: (generation: number) => generationDetailMock(generation),
      failureStreaks: () => failureStreaksMock(),
    },
  };
});

const { default: GenerationsPanel } = await import("@/pages/competition/GenerationsPanel");

// --- fixtures ------------------------------------------------------------------------------------------

function statSummary(overrides: Partial<StatSummary> = {}): StatSummary {
  return {
    n: 8,
    min: "-0.0200",
    p25: "0.0100",
    median: "0.0741",
    p75: "0.1100",
    max: "0.1800",
    mean: "0.0750",
    ...overrides,
  };
}

function generationSummary(overrides: Partial<GenerationSummary> = {}): GenerationSummary {
  return {
    generation: 10,
    round_id: "loop-r1-g10",
    purpose: "trading",
    status: "succeeded",
    started_at: "2026-08-20T00:00:00Z",
    finished_at: "2026-08-20T01:00:00Z",
    duration_seconds: 300,
    windows: ["gfc", "covid"],
    holdout_windows: ["banks-2023"],
    candidates: 10,
    ranked: 9,
    eligible: 7,
    error: null,
    field: {
      median_excess: statSummary({ median: "0.0741", n: 9 }),
      worst_excess: statSummary({ median: "-0.0120", n: 9 }),
      hit_rate: statSummary({ median: "0.6500", n: 9 }),
      holdout_median: statSummary({ median: "0.0312", n: 9 }),
      holdout_gap_pp: statSummary({ median: "2.5000", n: 9 }),
      total_trades: statSummary({ median: "180", n: 9 }),
      q_value: statSummary({ median: "0.0200", n: 9 }),
    },
    gate: { cleared: 3, eligible: 7, margin_pp: "1.0000" },
    promoted: ["g-042"],
    leader: {
      genome_id: "g-042",
      display_name: "Chop Specialist",
      rank: 1,
      median_excess: "0.0741",
      holdout_median_excess: "0.0312",
    },
    findings_by_kind: { winner: 1 },
    has_review: false,
    ...overrides,
  };
}

function failureStreak(overrides: Partial<FailureStreak> = {}): FailureStreak {
  return {
    first_generation: 1,
    last_generation: 400,
    count: 400,
    error: "Backtest worker crashed: connection reset by peer",
    started_at: "2026-06-01T00:00:00Z",
    finished_at: "2026-07-15T00:00:00Z",
    ...overrides,
  };
}

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

function generationOutcome(overrides: Partial<GenerationOutcome> = {}): GenerationOutcome {
  return {
    generation: 10,
    round_id: "loop-r1-g10",
    purpose: "trading",
    job_id: "job-10",
    status: "succeeded",
    started_at: "2026-08-20T00:00:00Z",
    finished_at: "2026-08-20T01:00:00Z",
    windows: ["gfc", "covid"],
    holdout_windows: ["banks-2023"],
    genome_ids: ["g-042"],
    standings: [standing()],
    findings: [{ kind: "winner", summary: "c07-chop cleared the margin.", evidence: {} }],
    promoted: ["g-042"],
    error: null,
    ...overrides,
  };
}

function generationReview(overrides: Partial<GenerationReview> = {}): GenerationReview {
  return {
    generation: 10,
    purpose: "trading",
    shape: "swing",
    verdict: "promising",
    post_mortem: "The chop specialist held up across the ladder windows.",
    per_candidate: [{ genome_id: "g-042", note: "Kept for another generation.", keep: true }],
    direction: {
      headline: "Push further into semiconductor chop names.",
      hypotheses: ["A tighter stop may reduce the worst-window drawdown."],
      focus_symbols: ["NVDA"],
      avoid_symbols: [],
      emphasise_disciplines: ["mean-reversion"],
      retire_disciplines: [],
    },
    amendments: [
      { field: "population", value: 16, reason: "More diversity needed to escape the current plateau." },
    ],
    ...overrides,
  };
}

function generationDetailResponse(
  overrides: Partial<GenerationDetailResponse> = {},
): GenerationDetailResponse {
  return {
    outcome: generationOutcome(),
    plan_markdown: "## Plan\nTry more semiconductor chop names this generation.",
    review: generationReview(),
    ...overrides,
  };
}

function listResponse(generations: GenerationSummary[], overrides: Partial<GenerationsListResponse> = {}): GenerationsListResponse {
  return {
    total: generations.length,
    returned: generations.length,
    offset: 0,
    unreadable: 0,
    generations,
    ...overrides,
  };
}

// --- helpers ---------------------------------------------------------------------------------------

/** Default every fetch to an empty, harmless response so a test only needs to override what it
 * actually cares about. */
function setupDefaultMocks() {
  generationsMock.mockResolvedValue(listResponse([]));
  failureStreaksMock.mockResolvedValue({ streaks: [] });
}

describe("GenerationsPanel", () => {
  it("renders generation rows newest-first, interleaved with failure streak rows by generation number", async () => {
    setupDefaultMocks();
    generationsMock.mockResolvedValue(
      listResponse([generationSummary({ generation: 5 }), generationSummary({ generation: 20 })]),
    );
    failureStreaksMock.mockResolvedValue({
      streaks: [failureStreak({ first_generation: 6, last_generation: 12, count: 7 })],
    });

    const { container } = render(<GenerationsPanel />);

    const genCells = await screen.findAllByText(/^Gen \d+$/);
    expect(genCells.map((el) => el.textContent)).toEqual(["Gen 20", "Gen 5"]);

    // The streak (spanning up to generation 12) sorts between the two, confirming rows interleave by
    // generation number rather than being split into two separately-ordered lists. Body rows carry
    // `role="button"` (see `GenerationRowView`/`FailureStreakRow`, matching `LeaderboardSection`'s own
    // clickable-row convention), which overrides their implicit `"row"` ARIA role -- so this walks the
    // table DOM directly rather than querying `role="row"`, which would only ever find the header.
    const rowTexts = Array.from(container.querySelectorAll("tbody tr")).map((r) => r.textContent ?? "");
    const idxGen20 = rowTexts.findIndex((t) => t.includes("Gen 20"));
    const idxStreak = rowTexts.findIndex((t) => t.includes("7 consecutive generations failed"));
    const idxGen5 = rowTexts.findIndex((t) => t.includes("Gen 5"));
    expect(idxGen20).toBeGreaterThanOrEqual(0);
    expect(idxStreak).toBeGreaterThan(idxGen20);
    expect(idxGen5).toBeGreaterThan(idxStreak);
  });

  it("collapses a 400-generation failure streak into exactly one row naming the error, not 400 rows", async () => {
    setupDefaultMocks();
    generationsMock.mockResolvedValue(
      listResponse([generationSummary({ generation: 405 }), generationSummary({ generation: 401 })]),
    );
    failureStreaksMock.mockResolvedValue({
      streaks: [
        failureStreak({
          first_generation: 1,
          last_generation: 400,
          count: 400,
          error: "Backtest worker crashed: connection reset by peer",
        }),
      ],
    });

    render(<GenerationsPanel />);

    expect(
      await screen.findByText(/400 consecutive generations failed with:/i),
    ).toBeTruthy();
    expect(screen.getByText("Backtest worker crashed: connection reset by peer")).toBeTruthy();

    // Only two ordinary generation rows plus the one collapsed streak row -- never one row per failure.
    const genRows = screen.getAllByText(/^Gen \d+$/);
    expect(genRows).toHaveLength(2);
    const streakRows = screen.getAllByText(/consecutive generations failed with:/i);
    expect(streakRows).toHaveLength(1);
  });

  it("renders 'no field' for a null StatSummary, never a zero", async () => {
    setupDefaultMocks();
    generationsMock.mockResolvedValue(
      listResponse([
        generationSummary({
          generation: 30,
          field: {
            median_excess: null,
            worst_excess: null,
            hit_rate: null,
            holdout_median: null,
            holdout_gap_pp: null,
            total_trades: null,
            q_value: null,
          },
        }),
      ]),
    );

    render(<GenerationsPanel />);

    await screen.findByText("Gen 30");
    const noFieldCells = screen.getAllByText("no field");
    // Both the median-excess and the holdout-gap columns are null in this fixture.
    expect(noFieldCells.length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText("0.00%")).toBeNull();
    expect(screen.queryByText("0.00pp")).toBeNull();
  });

  it("expands a generation, fetches its detail, and renders every standing including ineligible ones", async () => {
    setupDefaultMocks();
    generationsMock.mockResolvedValue(listResponse([generationSummary({ generation: 10 })]));
    generationDetailMock.mockResolvedValue(
      generationDetailResponse({
        outcome: generationOutcome({
          standings: [
            standing({ genome_id: "g-042", display_name: "Chop Specialist", rank: 1, eligible: true }),
            standing({
              genome_id: "g-099",
              display_name: "Overtrader",
              rank: 9,
              eligible: false,
              agent_id: "c09-overtrade",
            }),
          ],
        }),
      }),
    );

    render(<GenerationsPanel />);

    const genRow = (await screen.findByText("Gen 10")).closest("tr") as HTMLElement;
    fireEvent.click(genRow);

    expect(generationDetailMock).toHaveBeenCalledWith(10);
    expect(await screen.findByText("Chop Specialist")).toBeTruthy();
    expect(await screen.findByText("Overtrader")).toBeTruthy();
    expect(screen.getByText("not eligible")).toBeTruthy();
  });

  it("renders the review's verdict, direction, and amendments when one exists", async () => {
    setupDefaultMocks();
    generationsMock.mockResolvedValue(listResponse([generationSummary({ generation: 10, has_review: true })]));
    generationDetailMock.mockResolvedValue(generationDetailResponse());

    render(<GenerationsPanel />);

    const genRow = (await screen.findByText("Gen 10")).closest("tr") as HTMLElement;
    fireEvent.click(genRow);

    expect(await screen.findByText("Promising")).toBeTruthy();
    expect(screen.getByText("Push further into semiconductor chop names.")).toBeTruthy();
    expect(screen.getByText(/loop changed its own configuration/i)).toBeTruthy();
    expect(screen.getByText("population")).toBeTruthy();
    expect(screen.getByText("More diversity needed to escape the current plateau.")).toBeTruthy();
  });

  it("renders the explicit 'no model has reviewed' state when review is null", async () => {
    setupDefaultMocks();
    generationsMock.mockResolvedValue(listResponse([generationSummary({ generation: 10 })]));
    generationDetailMock.mockResolvedValue(generationDetailResponse({ review: null }));

    render(<GenerationsPanel />);

    const genRow = (await screen.findByText("Gen 10")).closest("tr") as HTMLElement;
    fireEvent.click(genRow);

    expect(await screen.findByText(/no model has reviewed this generation/i)).toBeTruthy();
    expect(screen.queryByText("Promising")).toBeNull();
  });

  it("changes which generations feed the sparkline when the purpose filter changes", async () => {
    setupDefaultMocks();
    generationsMock.mockImplementation((params) => {
      if (params.purpose === "savings") {
        return Promise.resolve(
          listResponse([
            generationSummary({ generation: 50, purpose: "savings" }),
            generationSummary({ generation: 60, purpose: "savings" }),
          ]),
        );
      }
      return Promise.resolve(
        listResponse([
          generationSummary({ generation: 10, purpose: "trading" }),
          generationSummary({ generation: 20, purpose: "trading" }),
        ]),
      );
    });

    render(<GenerationsPanel />);

    // Default purpose is "trading" -- every sparkline's accessible name (via `role="img"` +
    // `aria-label`) names its generation range. Three tiles (median excess / holdout gap / gate
    // clearance) all plot the same generation range, so this asserts on the count of matches rather
    // than a single element.
    const tradingLabels = await screen.findAllByRole("img", { name: /from generation 10 to 20/i });
    expect(tradingLabels.length).toBeGreaterThan(0);

    fireEvent.change(screen.getByLabelText(/purpose/i), { target: { value: "savings" } });

    const savingsLabels = await screen.findAllByRole("img", { name: /from generation 50 to 60/i });
    expect(savingsLabels.length).toBeGreaterThan(0);
    expect(screen.queryAllByRole("img", { name: /from generation 10 to 20/i })).toHaveLength(0);
  });

  it("formats a fraction column and a percentage-point column differently -- the 100x bug this contract calls out", async () => {
    setupDefaultMocks();
    generationsMock.mockResolvedValue(
      listResponse([
        generationSummary({
          generation: 10,
          field: {
            median_excess: statSummary({ median: "0.1940", n: 9 }), // a fraction: 19.40%
            worst_excess: statSummary({ median: "-0.0120", n: 9 }),
            hit_rate: statSummary({ median: "0.6500", n: 9 }),
            holdout_median: statSummary({ median: "0.0312", n: 9 }),
            holdout_gap_pp: statSummary({ median: "2.5000", n: 9 }), // already pp: 2.50pp, NOT 250.00%
            total_trades: statSummary({ median: "180", n: 9 }),
            q_value: statSummary({ median: "0.0200", n: 9 }),
          },
        }),
      ]),
    );

    render(<GenerationsPanel />);

    await screen.findByText("Gen 10");
    // Fraction column: 0.1940 -> +19.40%.
    expect(screen.getByText(/\+19\.40% \(n=9\)/)).toBeTruthy();
    // Percentage-point column: 2.5000 -> +2.50pp, not +250.00% and not +2.50%.
    expect(screen.getByText(/\+2\.50pp \(n=9\)/)).toBeTruthy();
    expect(screen.queryByText(/250\.00%/)).toBeNull();
    expect(screen.queryByText(/\+2\.50% /)).toBeNull();
  });

  it("renders a readable error message rather than a blank panel when the API call fails", async () => {
    failureStreaksMock.mockResolvedValue({ streaks: [] });
    // Only the main list call fails here (`succeeded_only` unset); the trend call
    // (`succeeded_only: true`) succeeds with nothing, isolating the failure to the list section so
    // this test checks one error surfacing in one place, not two.
    generationsMock.mockImplementation((params) =>
      params.succeeded_only
        ? Promise.resolve(listResponse([]))
        : Promise.reject(new Error("evolution loop service unavailable")),
    );

    render(<GenerationsPanel />);

    expect(await screen.findByText("evolution loop service unavailable")).toBeTruthy();
  });
});
